#!/usr/bin/env python3
"""Install the Codex custom agents of this collection into ${CODEX_HOME:-~/.codex}/agents.

Codex plugins cannot ship custom agents yet, so they are installed from this checkout. Codex has no
model aliases, so the model of each tier is resolved at install time from Codex's model catalog
(~/.codex/models_cache.json): the newest listed SOL model for the stronger tier and the newest listed
LUNA model for the weaker one. Without the catalog the defaults from the build are kept.
Re-run after `git pull` or when new models come out.

Usage: scripts/install-codex-agents.py [--uninstall] [--dry-run]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "plugins" / "codex" / "custom-agents"
HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
DEST = HOME / "agents"
MARKER = "# managed-by: pechynho-skills\n"
MODEL_RE = re.compile(r'^model = "([^"]+)"$', re.M)


def newest(family: str) -> str | None:
    # The catalog orders models by `priority` (lower is preferred) and Codex lists the newest
    # generation first, so the lowest priority among the listed `*-<family>` slugs is the newest one.
    try:
        catalog = json.loads((HOME / "models_cache.json").read_text())
    except (OSError, ValueError):
        return None
    models = [
        m for m in catalog.get("models", [])
        if m.get("visibility") == "list" and m.get("slug", "").endswith(f"-{family}")
    ]
    return min(models, key=lambda m: m.get("priority", 1 << 30))["slug"] if models else None


def resolve(text: str) -> str:
    def swap(match: re.Match[str]) -> str:
        default = match.group(1)
        family = default.rsplit("-", 1)[-1]
        return f'model = "{newest(family) or default}"'

    return MODEL_RE.sub(swap, text)


def main() -> None:
    uninstall = "--uninstall" in sys.argv
    dry_run = "--dry-run" in sys.argv
    if not uninstall and not dry_run:
        DEST.mkdir(parents=True, exist_ok=True)
    for agent in sorted(SRC.glob("*.toml")):
        target = DEST / agent.name
        managed = target.is_file() and target.read_text().startswith(MARKER)
        if target.exists() and not managed:
            print(f"skipped {target} (exists and is not managed by this script)", file=sys.stderr)
            continue
        if uninstall:
            if managed and not dry_run:
                target.unlink()
            if managed:
                print(f"removed {target}")
            continue
        content = MARKER + resolve(agent.read_text())
        model = MODEL_RE.search(content)
        if not dry_run:
            target.write_text(content)
        print(f"wrote   {target} ({model.group(1) if model else 'inherited model'})")


if __name__ == "__main__":
    main()
