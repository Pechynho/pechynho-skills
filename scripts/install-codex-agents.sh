#!/usr/bin/env bash
# Link the Codex custom agents of this collection into ${CODEX_HOME:-~/.codex}/agents.
# Codex plugins cannot ship custom agents yet, so they are installed from this checkout;
# `git pull` then updates them in place.
#
# Usage: scripts/install-codex-agents.sh [--uninstall]
set -euo pipefail

src="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/plugins/codex/custom-agents"
dest="${CODEX_HOME:-$HOME/.codex}/agents"
mode="${1:-install}"

mkdir -p "$dest"
for agent in "$src"/*.toml; do
    target="$dest/$(basename "$agent")"
    if [[ "$mode" == "--uninstall" ]]; then
        if [[ -L "$target" && "$(readlink "$target")" == "$agent" ]]; then
            rm "$target" && echo "removed $target"
        fi
        continue
    fi
    if [[ -L "$target" && "$(readlink "$target")" == "$agent" ]]; then
        echo "ok      $target"
    elif [[ -e "$target" || -L "$target" ]]; then
        echo "skipped $target (exists and is not managed by this script)" >&2
    else
        ln -s "$agent" "$target" && echo "linked  $target"
    fi
done
