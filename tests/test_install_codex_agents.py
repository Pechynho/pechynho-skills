"""Tests of scripts/install-codex-agents.py against a temporary CODEX_HOME."""

from __future__ import annotations

import json
import unittest

from tests.helpers import ROOT, SCRIPTS, ToolTestCase, run_tool, write_json

SCRIPT = SCRIPTS / "install-codex-agents.py"
SRC = ROOT / "plugins" / "codex" / "custom-agents"
MARKER = "# managed-by: pechynho-skills\n"


class InstallTest(ToolTestCase):
    def setUp(self):
        super().setUp()
        self.agents = self.tmp / "agents"
        self.names = sorted(p.name for p in SRC.glob("*.toml"))
        self.assertTrue(self.names, "no built Codex agents")

    def install(self, *args):
        result = run_tool(SCRIPT, *args, env={"CODEX_HOME": str(self.tmp)}, isolated=True)
        self.assertOk(result)
        return result

    def test_installs_every_agent_with_the_marker(self):
        self.install()
        self.assertEqual(sorted(p.name for p in self.agents.iterdir()), self.names)
        for name in self.names:
            text = (self.agents / name).read_text()
            self.assertTrue(text.startswith(MARKER))
            # Without a model catalog the defaults from the build are kept.
            self.assertEqual(text[len(MARKER):], (SRC / name).read_text())

    def test_models_come_from_the_catalog(self):
        write_json(self.tmp / "models_cache.json", {"models": [
            {"slug": "gpt-9-sol", "visibility": "list", "priority": 2},
            {"slug": "gpt-10-sol", "visibility": "list", "priority": 1},
            {"slug": "gpt-11-sol", "visibility": "hide", "priority": 0},
            {"slug": "gpt-10-luna", "visibility": "list", "priority": 5},
        ]})
        self.install()
        models = {name: (self.agents / name).read_text() for name in self.names}
        for name, text in models.items():
            source = (SRC / name).read_text()
            if '-sol"' in source:
                self.assertIn('model = "gpt-10-sol"', text, name)
            if '-luna"' in source:
                self.assertIn('model = "gpt-10-luna"', text, name)

    def test_broken_catalog_keeps_the_defaults(self):
        (self.tmp / "models_cache.json").write_text("{not json")
        self.install()
        name = self.names[0]
        self.assertEqual((self.agents / name).read_text(), MARKER + (SRC / name).read_text())

    def test_foreign_files_are_left_alone(self):
        self.agents.mkdir()
        foreign = self.agents / self.names[0]
        foreign.write_text("mine\n")
        result = self.install()
        self.assertEqual(foreign.read_text(), "mine\n")
        self.assertIn("skipped", result.stderr)
        self.install("--uninstall")
        self.assertEqual(foreign.read_text(), "mine\n")

    def test_reinstall_overwrites_managed_files(self):
        self.install()
        managed = self.agents / self.names[0]
        managed.write_text(MARKER + "old\n")
        self.install()
        self.assertEqual(managed.read_text(), MARKER + (SRC / self.names[0]).read_text())

    def test_uninstall_removes_managed_files(self):
        self.install()
        (self.agents / "other.toml").write_text("keep\n")
        result = self.install("--uninstall")
        self.assertEqual([p.name for p in self.agents.iterdir()], ["other.toml"])
        self.assertEqual(result.stdout.count("removed"), len(self.names))

    def test_dry_run_writes_nothing(self):
        result = self.install("--dry-run")
        self.assertFalse(self.agents.exists())
        self.assertEqual(result.stdout.count("wrote"), len(self.names))
        self.install()
        self.install("--uninstall", "--dry-run")
        self.assertEqual(len(list(self.agents.iterdir())), len(self.names))


if __name__ == "__main__":
    unittest.main()
