#!/usr/bin/env python3
"""Build the Claude Code and Codex plugins from the shared base and the platform overlays.

Usage:
    scripts/build.py          # regenerate plugins/claude and plugins/codex
    scripts/build.py --check  # fail if the committed plugins differ from a fresh build
"""

from __future__ import annotations

import filecmp
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "base"
OVERLAYS = ROOT / "overlays"
PLATFORMS = ("claude", "codex")
PLUGIN_NAME = "pechynho"
CODEX_AGENT_PREFIX = "pechynho_"

BLOCK_RE = re.compile(r"<!-- platform:(\w+) -->\n(.*?)<!-- /platform -->\n", re.S)
LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)

PREAMBLE = (
    "Before starting, resolve the [project context](shared/project-context.md) and follow the\n"
    "[ground rules](shared/ground-rules.md); the project's own instructions apply on top of them.\n"
)


def render(text: str, platform: str) -> str:
    """Keep the platform blocks of `platform`, drop the others."""

    def keep(match: re.Match[str]) -> str:
        if match.group(1) not in PLATFORMS:
            raise ValueError(f"unknown platform block: {match.group(1)}")
        return match.group(2) if match.group(1) == platform else ""

    out = BLOCK_RE.sub(keep, text)
    if "<!-- platform:" in out or "<!-- /platform -->" in out:
        raise ValueError("unbalanced platform block")
    return out


def split_frontmatter(text: str, path: Path) -> tuple[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path}: missing frontmatter")
    return match.group(1), text[match.end():]


def frontmatter_value(frontmatter: str, key: str) -> str:
    match = re.search(rf"^{key}:\s*(.+)$", frontmatter, re.M)
    if not match:
        raise ValueError(f"missing frontmatter key: {key}")
    return match.group(1).strip().strip('"')


def add_preamble(body: str) -> str:
    head, sep, rest = body.lstrip("\n").partition("\n\n")
    if not head.startswith("# "):
        raise ValueError("SKILL.md body must start with an H1")
    return f"\n{head}{sep}{PREAMBLE}\n{rest}"


def copy_rendered(src: Path, dst: Path, platform: str) -> None:
    for path in sorted(src.rglob("*")):
        if path.is_dir():
            continue
        target = dst / path.relative_to(src)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".md":
            target.write_text(render(path.read_text(), platform))
        else:
            shutil.copy2(path, target)


def build_skill(skill_dir: Path, out_skills: Path, platform: str) -> None:
    name = skill_dir.name
    dst = out_skills / name
    copy_rendered(skill_dir, dst, platform)
    copy_rendered(BASE / "shared", dst / "shared", platform)

    skill_md = dst / "SKILL.md"
    frontmatter, body = split_frontmatter(skill_md.read_text(), skill_md)
    if frontmatter_value(frontmatter, "name") != name:
        raise ValueError(f"{skill_md}: name must match the directory")
    if platform == "claude":
        extra = OVERLAYS / "claude" / "skills" / f"{name}.yaml"
        if extra.exists():
            frontmatter = f"{frontmatter}\n{extra.read_text().strip()}"
    else:
        meta = OVERLAYS / "codex" / "skills" / f"{name}.openai.yaml"
        if meta.exists():
            (dst / "agents").mkdir(exist_ok=True)
            shutil.copy2(meta, dst / "agents" / "openai.yaml")
    skill_md.write_text(f"---\n{frontmatter}\n---\n{add_preamble(body)}")


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_agents(out: Path, platform: str) -> None:
    for agent in sorted((BASE / "agents").glob("*.md")):
        frontmatter, body = split_frontmatter(agent.read_text(), agent)
        name = frontmatter_value(frontmatter, "name")
        description = frontmatter_value(frontmatter, "description")
        body = render(body, platform).strip() + "\n"
        extra = (OVERLAYS / platform / "agents" / f"{name}.yaml").read_text().strip()
        if platform == "claude":
            target = out / "agents" / f"{name}.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"---\nname: {name}\ndescription: {description}\n{extra}\n---\n\n{body}"
            )
        else:
            codex_name = CODEX_AGENT_PREFIX + name.replace("-", "_")
            lines = [f"name = {toml_string(codex_name)}", f"description = {toml_string(description)}"]
            for line in extra.splitlines():
                key, _, value = line.partition(":")
                lines.append(f"{key.strip()} = {toml_string(value.strip())}")
            body = body.replace('"""', '\\"\\"\\"')
            lines.append(f'developer_instructions = """\n{body}"""')
            target = out / "custom-agents" / f"{codex_name}.toml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(lines) + "\n")


def build_manifest(out: Path, platform: str, version: str) -> None:
    manifest = json.loads((OVERLAYS / platform / "plugin.json").read_text())
    if manifest["name"] != PLUGIN_NAME:
        raise ValueError(f"{platform} plugin.json: name must be {PLUGIN_NAME}")
    manifest["version"] = version
    folder = out / (".claude-plugin" if platform == "claude" else ".codex-plugin")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def github_anchor(heading: str) -> str:
    anchor = heading.strip().lower()
    anchor = re.sub(r"[^\w\- ]", "", anchor)
    return anchor.replace(" ", "-")


def anchors_of(path: Path) -> set[str]:
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
    return {github_anchor(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", text, re.M)}


def check_links(out: Path) -> list[str]:
    errors = []
    for md in sorted(out.rglob("*.md")):
        text = re.sub(r"```.*?```", "", md.read_text(), flags=re.S)
        for link in LINK_RE.findall(text):
            if re.match(r"^[a-z]+://", link) or link.startswith("mailto:"):
                continue
            target, _, anchor = link.partition("#")
            dest = (md.parent / target).resolve() if target else md
            if not dest.exists():
                errors.append(f"{md.relative_to(out)}: missing target {link}")
            elif anchor and dest.suffix == ".md" and anchor not in anchors_of(dest):
                errors.append(f"{md.relative_to(out)}: missing anchor {link}")
    return errors


def build(dest: Path) -> None:
    version = (ROOT / "VERSION").read_text().strip()
    for platform in PLATFORMS:
        out = dest / platform
        if out.exists():
            shutil.rmtree(out)
        build_manifest(out, platform, version)
        for skill_dir in sorted((BASE / "skills").iterdir()):
            if (skill_dir / "SKILL.md").exists():
                build_skill(skill_dir, out / "skills", platform)
        build_agents(out, platform)
        errors = check_links(out)
        if errors:
            raise SystemExit("broken links:\n  " + "\n  ".join(errors))


def same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(same_tree(a / d, b / d) for d in cmp.common_dirs)


def main() -> None:
    if "--check" in sys.argv[1:]:
        with tempfile.TemporaryDirectory() as tmp:
            build(Path(tmp))
            for platform in PLATFORMS:
                committed = ROOT / "plugins" / platform
                if not committed.exists() or not same_tree(Path(tmp) / platform, committed):
                    raise SystemExit(f"plugins/{platform} is stale; run scripts/build.py")
        print("plugins are up to date")
        return
    build(ROOT / "plugins")
    print("built plugins/claude and plugins/codex")


if __name__ == "__main__":
    main()
