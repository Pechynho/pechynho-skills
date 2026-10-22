"""Tests of scripts/build.py: platform blocks, skills, agents, manifests, link checks and --check."""

from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, SCRIPTS, ToolTestCase, load_module, run_tool

build = load_module(SCRIPTS / "build.py", "build_under_test")

SKILL = """---
name: demo
description: A demo skill.
---

# Demo

Intro paragraph.

<!-- platform:claude -->
Claude only.
<!-- /platform -->
<!-- platform:codex -->
Codex only.
<!-- /platform -->
See [the rules](shared/rules.md#the-rules) and [the tool](shared/tool.py).
"""

AGENT = """---
name: helper
description: Helps with "things".
---

Do the work.
<!-- platform:codex -->
Codex note with \"\"\" quotes.
<!-- /platform -->
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class RenderTest(unittest.TestCase):
    def test_keeps_own_blocks_and_drops_others(self):
        text = "a\n<!-- platform:claude -->\nC\n<!-- /platform -->\n<!-- platform:codex -->\nX\n<!-- /platform -->\nb\n"
        self.assertEqual(build.render(text, "claude"), "a\nC\nb\n")
        self.assertEqual(build.render(text, "codex"), "a\nX\nb\n")

    def test_unknown_platform_fails(self):
        with self.assertRaisesRegex(ValueError, "unknown platform"):
            build.render("<!-- platform:vim -->\nx\n<!-- /platform -->\n", "claude")

    def test_unbalanced_block_fails(self):
        with self.assertRaisesRegex(ValueError, "unbalanced"):
            build.render("<!-- platform:claude -->\nx\n", "claude")

    def test_preamble_follows_the_heading(self):
        body = build.add_preamble("\n# Title\n\nText.\n")
        self.assertTrue(body.startswith("\n# Title\n\nBefore starting"))
        self.assertTrue(body.endswith("\nText.\n"))
        with self.assertRaisesRegex(ValueError, "H1"):
            build.add_preamble("Text without a heading.\n")

    def test_github_anchor(self):
        self.assertEqual(build.github_anchor("Run a pass (headless)"), "run-a-pass-headless")
        self.assertEqual(build.github_anchor("plan.py `set`"), "planpy-set")


class FixtureTest(ToolTestCase):
    """Builds a small fixture tree instead of the real base/ and overlays/."""

    def setUp(self):
        super().setUp()
        self.base = self.tmp / "base"
        self.overlays = self.tmp / "overlays"
        write(self.tmp / "VERSION", "1.2.3\n")
        write(self.base / "skills" / "demo" / "SKILL.md", SKILL)
        write(self.base / "shared" / "rules.md", "# The rules\n\nBe nice.\n")
        write(self.base / "shared" / "tool.py", "print('hi')\n")
        write(self.base / "shared" / "project-context.md", "# Project context\n")
        write(self.base / "shared" / "ground-rules.md", "# Ground rules\n")
        write(self.base / "shared" / "__pycache__" / "tool.cpython-314.pyc", "junk")
        write(self.base / "agents" / "helper.md", AGENT)
        for platform in build.PLATFORMS:
            write(self.overlays / platform / "plugin.json", json.dumps({"name": "pechynho"}))
            write(self.overlays / platform / "agents" / "helper.yaml", "model: some-model\n")
        write(self.overlays / "claude" / "skills" / "demo.yaml", "allowed-tools: Read\n")
        write(self.overlays / "codex" / "skills" / "demo.openai.yaml", "interface: {}\n")
        for name, value in (("ROOT", self.tmp), ("BASE", self.base), ("OVERLAYS", self.overlays)):
            patcher = mock.patch.object(build, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.out = self.tmp / "out"

    def test_claude_plugin(self):
        build.build(self.out)
        out = self.out / "claude"
        self.assertEqual(json.loads((out / ".claude-plugin" / "plugin.json").read_text())["version"], "1.2.3")
        skill = (out / "skills" / "demo" / "SKILL.md").read_text()
        self.assertIn("allowed-tools: Read\n---\n", skill)
        self.assertIn("Claude only.", skill)
        self.assertNotIn("Codex only.", skill)
        self.assertIn(build.PREAMBLE, skill)
        self.assertTrue((out / "skills" / "demo" / "shared" / "tool.py").is_file())
        agent = (out / "agents" / "helper.md").read_text()
        self.assertTrue(agent.startswith("---\nname: helper\n"))
        self.assertIn("model: some-model\n---\n", agent)
        self.assertNotIn("Codex note", agent)

    def test_codex_plugin(self):
        build.build(self.out)
        out = self.out / "codex"
        self.assertEqual(json.loads((out / ".codex-plugin" / "plugin.json").read_text())["version"], "1.2.3")
        skill = (out / "skills" / "demo" / "SKILL.md").read_text()
        self.assertIn("Codex only.", skill)
        self.assertNotIn("allowed-tools", skill)
        self.assertTrue((out / "skills" / "demo" / "agents" / "openai.yaml").is_file())
        agent = tomllib.loads((out / "custom-agents" / "pechynho_helper.toml").read_text())
        self.assertEqual(agent["name"], "pechynho_helper")
        self.assertEqual(agent["description"], 'Helps with "things".')
        self.assertEqual(agent["model"], "some-model")
        self.assertIn('Codex note with """ quotes.', agent["developer_instructions"])

    def test_bytecode_is_not_copied(self):
        build.build(self.out)
        self.assertEqual(list(self.out.rglob("__pycache__")), [])

    def test_rebuild_removes_stale_files(self):
        build.build(self.out)
        stale = self.out / "claude" / "skills" / "gone" / "SKILL.md"
        write(stale, "old")
        build.build(self.out)
        self.assertFalse(stale.exists())

    def test_skill_name_must_match_directory(self):
        write(self.base / "skills" / "demo" / "SKILL.md", SKILL.replace("name: demo", "name: other"))
        with self.assertRaisesRegex(ValueError, "must match the directory"):
            build.build(self.out)

    def test_broken_link_fails(self):
        write(self.base / "skills" / "demo" / "SKILL.md", SKILL + "[x](shared/missing.md)\n")
        with self.assertRaisesRegex(SystemExit, "missing target shared/missing.md"):
            build.build(self.out)

    def test_broken_anchor_fails(self):
        write(self.base / "skills" / "demo" / "SKILL.md", SKILL + "[x](shared/rules.md#nope)\n")
        with self.assertRaisesRegex(SystemExit, "missing anchor shared/rules.md#nope"):
            build.build(self.out)

    def test_links_in_code_and_urls_are_ignored(self):
        extra = "```\n[x](nowhere.md)\n```\n[site](https://example.com/x) [mail](mailto:a@b.c)\n"
        write(self.base / "skills" / "demo" / "SKILL.md", SKILL + extra)
        build.build(self.out)

    def test_same_tree(self):
        build.build(self.out)
        build.build(self.tmp / "again")
        self.assertTrue(build.same_tree(self.out / "claude", self.tmp / "again" / "claude"))
        write(self.tmp / "again" / "claude" / "skills" / "demo" / "shared" / "rules.md", "# Changed\n")
        self.assertFalse(build.same_tree(self.out / "claude", self.tmp / "again" / "claude"))


class RepositoryTest(unittest.TestCase):
    def test_committed_plugins_are_up_to_date(self):
        result = run_tool(SCRIPTS / "build.py", "--check", cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("up to date", result.stdout)

    def test_every_platform_block_is_rendered(self):
        for path in (ROOT / "plugins").rglob("*.md"):
            self.assertNotIn("<!-- platform:", path.read_text(), path)


if __name__ == "__main__":
    unittest.main()
