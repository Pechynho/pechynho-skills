#!/usr/bin/env python3
"""Track a code review: chunks of the diff, perspective groups, coverage cells, waves and findings.

Usage:
    review.py DIR [--as ID] COMMAND ...                   --as: a reviewer or verifier recording its own results
    review.py DIR init --scope S --base REF [--head REF] [--working-tree] [--wave-size N]
                       [--single --groups G1="Perspective;Perspective" ...]
    review.py DIR init --scope S --audit PATTERN [PATTERN ...] [--head REF | --working-tree] ...
                                                          review whole files of an area, not a change
    review.py DIR audit-diff FILE                         the current full-content diff of an audit
    review.py DIR triage [--chunk-lines N] [--out FILE]   propose chunks from DIR/diff.patch
    review.py DIR chunks FILE                             load the (edited) chunk proposal
    review.py DIR chunk ID [--title T] [--files F ...] [--risk R] [--treatment T] [--integration]
    review.py DIR group ID --perspectives P [P ...] [--title T]
    review.py DIR cell CHUNK GROUP [GROUP ...]            cells that a reviewer has to cover
    review.py DIR omit CHUNK [CHUNK ...] --groups G [G ...] --reason R
                                                          perspective groups not relevant to chunks
    review.py DIR overview                                one line per chunk, the orientation for reviewers
    review.py DIR estimate                                chunks, cells and waves still needed
    review.py DIR approve --coverage full|risk_first [--note N]
    review.py DIR next [--limit N]                        cells to brief in the next wave
    review.py DIR start --owner R CELL [CELL ...]         cells handed to reviewer R in a wave
    review.py DIR set CELL [CELL ...] STATUS [--unchecked F ...] [--skipped PATTERN=REASON ...] [--reason R]
                      [--impact F ...] [--impact-unchecked F ...]   files outside the chunk the change affects
    review.py DIR finding ID --cell CELL --kind K --title T [--severity S] [--files F ...] [--outside] [--reviewer R]
                          [--body TEXT|-]                 the full finding, written to findings/ID.md
    review.py DIR verify ID [ID ...] VERDICT --verifier V [--severity S] [--note TEXT|-]
    review.py DIR resolve ID [ID ...] STATUS --reason R [--duplicate-of ID]
    review.py DIR findings [--status S] [--chunk C] [--all]
    review.py DIR coverage                                gaps in the coverage of the diff
    review.py DIR refresh FILE [--dry-run]                compare a fresh diff with diff.patch and reopen what changed
    review.py DIR status                                  derived overview, the entry point on resume
    review.py DIR validate
    review.py DIR log TYPE key=value ...                  append a record (check, decision, note)
    review.py DIR batch FILE|-                            several recording commands, all or nothing

File arguments take glob patterns: * within a directory, ** across directories, a trailing / for a
whole directory. A pattern is matched against the files of the diff (or of the repository for
--impact, --impact-unchecked and --audit) and stored as the files it matched; a pattern that
matches nothing is refused.
The format is described in shared/review-tool.md. Python 3.8+, standard library only.
Exit code 0 on success, 1 on a validation error or a refused change, 2 on wrong usage.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    import fcntl
except ImportError:  # Windows: commands are not serialized between processes
    fcntl = None

SCHEMA_VERSION = 1
RISKS = ("high", "medium", "low")
TREATMENTS = ("full", "light", "excluded")
CELL_STATUSES = ("pending", "running", "covered", "partial", "omitted")
OPEN_CELLS = ("pending", "running", "partial")
KINDS = ("bug", "recommendation", "question")
SEVERITIES = ("critical", "high", "medium", "low")
VERDICTS = ("confirmed", "refuted", "undecidable")
FINDING_STATUSES = ("unverified", "disputed", "awaiting_decision", "duplicate", "stale") + VERDICTS
SETTLED_FINDINGS = ("refuted", "duplicate")
LOG_REQUIRED = {"check": ("subject", "result"), "decision": ("text",), "note": ("text",)}
DEFAULT_WAVE_SIZE = 6
DEFAULT_CHUNK_LINES = 2500

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "composer.lock",
    "Cargo.lock", "poetry.lock", "Pipfile.lock", "uv.lock", "Gemfile.lock", "go.sum", "packages.lock.json",
    "mix.lock", "pubspec.lock", "flake.lock",
}
VENDOR_DIRS = {"vendor", "node_modules", "third_party", "bower_components"}
BUILD_DIRS = {"dist", "build", "out", ".next", "coverage", "target", "public/build"}
GENERATED_SUFFIXES = (".min.js", ".min.css", ".map", ".pb.go", "_pb2.py", ".g.dart", ".snap")
GENERATED_MARKERS = re.compile(r"@generated|do not edit|auto-?generated|generated by", re.I)


class Refused(Exception):
    """A change or a check that must not pass."""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise Refused(f"missing {path}")
    except json.JSONDecodeError as e:
        raise Refused(f"{path}: invalid JSON: {e}")


def write_json(path: Path, data) -> None:
    """Replace the file atomically so that an interruption never leaves half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def git(repo: str | None, *args: str) -> str | None:
    """Output of a git command, or None when git or the repository is not available."""
    try:
        result = subprocess.run(["git", "-C", repo or ".", *args], capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def resolve_sha(repo: str | None, ref: str) -> str | None:
    return git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")


def cell_id(chunk: str, group: str) -> str:
    return f"{chunk}/{group}"


class Review:
    def __init__(self, root: Path):
        self.root = root
        self.state_path = root / "review.json"
        self.log_path = root / "log.jsonl"
        self.diff_path = root / "diff.patch"
        self.findings_dir = root / "findings"
        self._state: dict | None = None
        self._pending_log: list[dict] | None = None  # buffered while a transaction runs
        self._pending_files: dict[Path, str] = {}
        self._dirty = False
        self.actor: str | None = None  # a subagent recording its own results, --as
        self.in_batch = False
        self._diff_files: list[str] | None = None
        self._impact_universe: set[str] | None = None

    @property
    def state(self) -> dict:
        if self._state is None:
            self._state = read_json(self.state_path)
        return self._state

    def save(self) -> None:
        self.state["updated_at"] = now()
        if self._pending_log is not None:
            self._dirty = True
            return
        write_json(self.state_path, self.state)

    def append_log(self, record: dict) -> None:
        record = {"at": now(), **record}
        if self.actor:
            record["by"] = self.actor
        if self._pending_log is not None:
            self._pending_log.append(record)
            return
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_file(self, path: Path) -> str | None:
        if path in self._pending_files:
            return self._pending_files[path]
        return path.read_text(encoding="utf-8") if path.exists() else None

    def write_file(self, path: Path, text: str) -> None:
        """A finding file, written with the state at the end of the transaction."""
        if self._pending_log is None:
            path.write_text(text, encoding="utf-8")
        else:
            self._pending_files[path] = text

    @contextlib.contextmanager
    def locked(self):
        """Serialize the commands of the orchestrator and of the subagents recording their own results."""
        with open(self.root / ".lock", "a+") as handle:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self._state = None  # read the state another process may have changed
                self._diff_files = self._impact_universe = None
                yield
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @contextlib.contextmanager
    def transaction(self):
        """Write the state, the log and the finding files only when the whole block succeeds; a refusal
        leaves them as they were."""
        self._pending_log, self._pending_files, self._dirty = [], {}, False
        try:
            yield
        except BaseException:
            self._state = None
            raise
        else:
            for path, text in self._pending_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            if self._dirty:
                write_json(self.state_path, self.state)
            if self._pending_log:
                with self.log_path.open("a", encoding="utf-8") as f:
                    for record in self._pending_log:
                        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        finally:
            self._pending_log, self._pending_files, self._dirty = None, {}, False

    def log(self) -> list[dict]:
        records = []
        if self.log_path.exists():
            for n, line in enumerate(self.log_path.read_text(encoding="utf-8").splitlines(), 1):
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise Refused(f"{self.log_path}:{n}: invalid JSON: {e}")
        return records + list(self._pending_log or [])

    def diff_files(self) -> list[str]:
        if self._diff_files is None:  # parsed once per command or batch; only refresh replaces the diff
            self._diff_files = sorted(parse_diff(self.diff_path)) if self.diff_path.exists() else []
        return self._diff_files

    def impact_universe(self) -> set[str]:
        """The repository on disk and the diff, listed once per command or batch."""
        if self._impact_universe is None:
            rev = self.state["revision"]
            files = set(repo_files(rev["repo"], rev["head"], True)) if rev.get("repo") else set()
            self._impact_universe = files | set(self.diff_files())
        return self._impact_universe

    def repo(self) -> str | None:
        return self.state["revision"].get("repo")

    def chunk(self, cid: str) -> dict:
        if cid not in self.state["chunks"]:
            raise Refused(f"unknown chunk {cid}")
        return self.state["chunks"][cid]

    def cell(self, key: str) -> dict:
        if key not in self.state["cells"]:
            raise Refused(f"unknown cell {key} (expected CHUNK/GROUP)")
        return self.state["cells"][key]

    def finding(self, fid: str) -> dict:
        if fid not in self.state["findings"]:
            raise Refused(f"unknown finding {fid}")
        return self.state["findings"][fid]

    def open_cells(self) -> list[str]:
        return [k for k, c in self.state["cells"].items() if c["status"] in OPEN_CELLS]

    def waves_needed(self) -> int:
        waiting = [k for k, c in self.state["cells"].items() if c["status"] in ("pending", "partial")]
        return math.ceil(len(waiting) / self.state["wave_size"]) if waiting else 0


# --- diff parsing -----------------------------------------------------------------------------


def parse_diff(path: Path) -> dict[str, dict]:
    """Per-file stats of a unified git diff: added and deleted lines, rename, binary, new or deleted,
    and a hash of the file's section that tells whether the file's change differs between two diffs."""
    if not path.exists():
        raise Refused(f"missing {path}; write the reviewed diff there first")
    files: dict[str, dict] = {}
    current: dict | None = None
    in_hunk = False
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if line.startswith("diff --git "):
                rest = line[len("diff --git "):]
                name = rest.split(" b/", 1)[1] if " b/" in rest else rest
                current = {"path": name, "added": 0, "deleted": 0, "status": "modified", "similarity": None,
                           "binary": False, "sample": [], "hash": hashlib.sha256()}
                files[name] = current
                in_hunk = False
            if current is None:
                continue
            if not line.startswith("index "):  # abbreviated blob IDs vary in length between runs
                current["hash"].update(raw.encode("utf-8"))
            if line.startswith("diff --git "):
                continue
            if line.startswith("@@"):
                in_hunk = True
            elif not in_hunk:
                if line.startswith("new file mode"):
                    current["status"] = "added"
                elif line.startswith("deleted file mode"):
                    current["status"] = "deleted"
                elif line.startswith("rename to "):
                    current["status"] = "renamed"
                    rename(files, current, line[len("rename to "):])
                elif line.startswith("similarity index "):
                    current["similarity"] = int(line[len("similarity index "):].rstrip("%") or 0)
                elif line.startswith("+++ b/"):
                    rename(files, current, line[len("+++ b/"):])
                elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
                    current["binary"] = True
            elif line.startswith("+"):
                current["added"] += 1
                if len(current["sample"]) < 20:
                    current["sample"].append(line[1:])
            elif line.startswith("-"):
                current["deleted"] += 1
    for info in files.values():
        info["hash"] = info["hash"].hexdigest()
    return files


def rename(files: dict[str, dict], current: dict, name: str) -> None:
    if name != current["path"]:
        files.pop(current["path"], None)
        current["path"] = name
        files[name] = current


def classify(info: dict) -> str:
    """A suggestion only; the orchestrator confirms or corrects it."""
    path = PurePosixPath(info["path"])
    parts = set(path.parts[:-1])
    if info["binary"]:
        return "binary"
    if path.name in LOCKFILES:
        return "lockfile"
    if parts & VENDOR_DIRS:
        return "vendor"
    if str(path).endswith(GENERATED_SUFFIXES) or any(GENERATED_MARKERS.search(s) for s in info["sample"]):
        return "generated"
    if parts & BUILD_DIRS:
        return "build_output"
    if info["status"] == "renamed" and info["similarity"] == 100:
        return "rename_only"
    return "logic"


def size(info: dict) -> int:
    return info["added"] + info["deleted"]


def chunk_lines(files: list[str], diff: dict[str, dict]) -> int:
    return sum(size(diff[p]) for p in files if p in diff)


def pack(files: list[dict], budget: int, depth: int = 0) -> list[list[dict]]:
    """Group files by directory so that each group stays within the line budget where possible."""
    if sum(size(f) for f in files) <= budget:
        return [files]
    groups: dict[str, list[dict]] = {}
    for f in files:
        parts = PurePosixPath(f["path"]).parts
        groups.setdefault(parts[depth] if len(parts) > depth + 1 else "", []).append(f)
    if list(groups) == [""]:
        out, current, total = [], [], 0
        for f in sorted(files, key=lambda x: x["path"]):
            if current and total + size(f) > budget:
                out.append(current)
                current, total = [], 0
            current.append(f)
            total += size(f)
        return out + ([current] if current else [])
    out, current, total = [], [], 0
    for key in sorted(groups):
        group = groups[key]
        group_size = sum(size(f) for f in group)
        if group_size > budget:
            out.extend(pack(group, budget, depth + 1) if key else pack_flat(group, budget))
            continue
        if current and total + group_size > budget:
            out.append(current)
            current, total = [], 0
        current.extend(group)
        total += group_size
    return out + ([current] if current else [])


def pack_flat(files: list[dict], budget: int) -> list[list[dict]]:
    return pack(files, budget, depth=10_000)


# --- patterns and whole-file diffs --------------------------------------------------------------


def is_pattern(item: str) -> bool:
    return item.endswith("/") or any(c in item for c in "*?[")


def glob_regex(pattern: str) -> re.Pattern:
    """A git-like glob: * and ? stay within a directory, ** crosses directories, a trailing / is a directory."""
    pattern = pattern[2:] if pattern.startswith("./") else pattern
    if pattern.endswith("/"):
        pattern += "**"
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
            continue
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
            continue
        if c == "*":
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[" and pattern.find("]", i + 2) != -1:
            end = pattern.find("]", i + 2)
            body = pattern[i + 1:end].replace("\\", "\\\\")
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body) + "]")
            i = end + 1
            continue
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out))


def expand(items: list[str], universe, what: str, literal: str = "keep") -> list[str]:
    """Replace each pattern by the files of the universe it matches, in order and without duplicates.

    A literal item is kept as it is (literal="keep"), or must be in the universe (literal="require"). Like
    git, an item that names a file of the universe exactly is that file, also with [ in its name."""
    universe = sorted(universe)
    known = set(universe)
    out: list[str] = []
    for item in items:
        path = item[2:] if item.startswith("./") else item
        if path in known:
            out.append(path)
        elif is_pattern(item):
            regex = glob_regex(item)
            matched = [f for f in universe if regex.fullmatch(f)]
            if not matched:
                raise Refused(f"{item} matches no file of {what}")
            out.extend(matched)
        else:
            if literal == "require":
                raise Refused(f"{item} is not a file of {what}")
            out.append(path)
    return list(dict.fromkeys(out))


def repo_files(repo: str, head: str | None, working_tree: bool) -> list[str]:
    """The files of the repository at head, or on disk (tracked and untracked, not ignored)."""
    if working_tree:
        out = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    else:
        out = git(repo, "ls-tree", "-r", "-z", "--name-only", head or "HEAD")
    if out is None:
        raise Refused(f"cannot list the files of the repository {repo}")
    files = sorted({f for f in out.split("\0") if f})
    if working_tree:
        files = [f for f in files if os.path.islink(os.path.join(repo, f)) or os.path.isfile(os.path.join(repo, f))]
    return files


def file_contents(repo: str, head: str | None, working_tree: bool, paths: list[str]) -> dict[str, bytes]:
    if working_tree:
        contents = {}
        for p in paths:
            full = os.path.join(repo, p)
            contents[p] = os.readlink(full).encode("utf-8") if os.path.islink(full) else Path(full).read_bytes()
        return contents
    request = "".join(f"{head or 'HEAD'}:{p}\n" for p in paths).encode("utf-8")
    result = subprocess.run(["git", "-C", repo, "cat-file", "--batch"], input=request, capture_output=True)
    if result.returncode != 0:
        raise Refused(f"git cat-file failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    data, pos, contents = result.stdout, 0, {}
    for p in paths:
        end = data.index(b"\n", pos)
        header = data[pos:end].decode("utf-8", "replace").split()
        pos = end + 1
        if len(header) < 3:  # missing
            continue
        size_ = int(header[2])
        if header[1] == "blob":
            contents[p] = data[pos:pos + size_]
        pos += size_ + 1
    return contents


def whole_file_diff(path: str, content: bytes) -> str:
    """The file as a new file of a unified diff, so that the diff tooling covers whole files."""
    head = f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
    if b"\0" in content:
        return head + f"Binary files /dev/null and b/{path} differ\n"
    if not content:
        return head
    text = content.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    body = "".join(f"+{line}\n" for line in lines)
    tail = "" if text.endswith("\n") else "\\ No newline at end of file\n"
    return head + f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n" + body + tail


def write_audit_diff(revision: dict, out: Path) -> list[str]:
    """Write the whole files the audit patterns match; each pattern has to match a file."""
    repo, head, working_tree = revision["repo"], revision["head"], revision["working_tree"]
    if not repo:
        raise Refused("an audit needs a git repository; run init inside it")
    files = expand(revision["audit"], repo_files(repo, head, working_tree), "the repository", literal="require")
    contents = file_contents(repo, head, working_tree, files)
    with out.open("w", encoding="utf-8", newline="") as f:
        for path in files:
            if path in contents:
                f.write(whole_file_diff(path, contents[path]))
    return [p for p in files if p in contents]


def common_dir(paths: list[str]) -> str:
    split = [PurePosixPath(p).parts[:-1] for p in paths]
    prefix = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        prefix.append(parts[0])
    return "/".join(prefix) or "."


# --- validation -------------------------------------------------------------------------------


def validate(review: Review) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    s = review.state
    for key in ("chunks", "groups", "cells", "findings"):
        if not isinstance(s.get(key), dict):
            errors.append(f"review.json: {key} must be an object")
    if errors:
        return errors, warnings

    if review.diff_path.exists():
        diff_files = set(parse_diff(review.diff_path))
        chunked = {f for c in s["chunks"].values() for f in c.get("files", [])}
        for f in sorted(diff_files - chunked):
            errors.append(f"{f}: in diff.patch but in no chunk")
        for f in sorted(chunked - diff_files):
            warnings.append(f"{f}: in a chunk but not in diff.patch")
    else:
        warnings.append("diff.patch not found; file coverage not checked")

    for cid, chunk in s["chunks"].items():
        if chunk.get("risk") not in RISKS:
            errors.append(f"chunk {cid}: invalid risk {chunk.get('risk')!r}")
        if chunk.get("treatment") not in TREATMENTS:
            errors.append(f"chunk {cid}: invalid treatment {chunk.get('treatment')!r}")
        if chunk.get("treatment") == "excluded" and not chunk.get("reason"):
            errors.append(f"chunk {cid}: excluded without a reason")
        if chunk.get("treatment") != "excluded" and not any(k.startswith(cid + "/") for k in s["cells"]):
            errors.append(f"chunk {cid}: no cells; add cells or omissions for every perspective group")
    for gid, group in s["groups"].items():
        if not group.get("perspectives"):
            errors.append(f"group {gid}: no perspectives")
    for key, cell in s["cells"].items():
        chunk, _, group = key.partition("/")
        if chunk not in s["chunks"]:
            errors.append(f"cell {key}: unknown chunk")
        if group not in s["groups"]:
            errors.append(f"cell {key}: unknown group")
        if cell.get("status") not in CELL_STATUSES:
            errors.append(f"cell {key}: invalid status {cell.get('status')!r}")
        if cell.get("status") == "partial" and not cell.get("unchecked"):
            errors.append(f"cell {key}: partial without the unchecked files or sections")
        if cell.get("status") == "omitted" and not cell.get("reason"):
            errors.append(f"cell {key}: omitted without a reason")
        skipped = cell.get("skipped") or {}
        chunk_files = set(s["chunks"].get(chunk, {}).get("files", []))
        for path in sorted(set(skipped) - chunk_files):
            errors.append(f"cell {key}: skipped {path} is not a file of chunk {chunk}")
        for path in sorted(set(skipped) & set(cell.get("unchecked") or [])):
            errors.append(f"cell {key}: {path} is both skipped and unchecked")
        for path, reason in skipped.items():
            if not reason:
                errors.append(f"cell {key}: skipped {path} without a reason")
    for cid in s["chunks"]:
        if s["chunks"][cid].get("treatment") == "excluded" or s["chunks"][cid].get("kind") == "integration":
            continue
        for gid in s["groups"]:
            if cell_id(cid, gid) not in s["cells"]:
                warnings.append(f"{cid}: group {gid} neither assigned nor omitted")

    for fid, f in s["findings"].items():
        if not (review.findings_dir / f"{fid}.md").exists():
            errors.append(f"finding {fid}: missing findings/{fid}.md")
        if f.get("cell") not in s["cells"]:
            errors.append(f"finding {fid}: unknown cell {f.get('cell')!r}")
        if f.get("status") not in FINDING_STATUSES:
            errors.append(f"finding {fid}: invalid status {f.get('status')!r}")
        if f.get("duplicate_of") and f["duplicate_of"] not in s["findings"]:
            errors.append(f"finding {fid}: duplicate of unknown {f['duplicate_of']}")
        verifiers = [v["verifier"] for v in f.get("verifications", [])]
        if f.get("reviewer") in verifiers:
            errors.append(f"finding {fid}: verified by its own reviewer {f['reviewer']}")
        if needs_second(f) and len(set(verifiers)) < 2:
            warnings.append(f"finding {fid}: {f.get('severity') or f['status']} needs a second verifier")
        if f.get("status") == "stale":
            warnings.append(f"finding {fid}: stale after a refresh, needs a new verification")

    if review.waves_needed() > 1 and not s.get("approval"):
        warnings.append("more than one wave is needed and the user has not approved the estimate")
    for n, record in enumerate(review.log(), 1):
        if "at" not in record or "type" not in record:
            errors.append(f"log.jsonl record {n}: missing at or type")
    return errors, warnings


def needs_second(f: dict) -> bool:
    return f.get("status") == "disputed" or (f.get("severity") == "critical" and f.get("status") == "confirmed")


# --- commands ---------------------------------------------------------------------------------


def cmd_init(review: Review, args) -> None:
    if review.state_path.exists():
        raise Refused("review.json already exists; continue with status")
    review.root.mkdir(parents=True, exist_ok=True)
    review.findings_dir.mkdir(exist_ok=True)
    repo = git(None, "rev-parse", "--show-toplevel")
    revision = {"base": args.base, "head": args.head, "working_tree": args.working_tree, "repo": repo,
                "base_sha": resolve_sha(repo, args.base) if args.base else None,
                "head_sha": resolve_sha(repo, args.head)}
    if args.audit:
        revision["audit"] = args.audit
        files = write_audit_diff(revision, review.diff_path)
        print(f"audit: {len(files)} whole files written to diff.patch")
    review._state = {
        "schema_version": SCHEMA_VERSION,
        "scope": args.scope,
        "revision": revision,
        "single": args.single,
        "wave_size": args.wave_size,
        "created_at": now(),
        "updated_at": now(),
        "approval": None,
        "chunks": {},
        "groups": {},
        "cells": {},
        "waves": [],
        "findings": {},
        "refreshes": [],
    }
    if args.single:
        single(review, args.groups)
    review.save()
    review.log_path.touch()
    review.append_log({"type": "init", "scope": args.scope, "revision": review.state["revision"],
                       "single": args.single})
    print(f"created review.json, log.jsonl and findings/ in {review.root}")
    if not revision["head_sha"] or not (revision["base_sha"] or args.audit):
        print("warning: base or head not resolved in a git repository; status cannot report moved revisions")
    if args.single:
        print(f"one chunk C01 ({len(review.state['chunks']['C01']['files'])} files), "
              f"cells {', '.join(review.state['cells'])}")


def single(review: Review, groups: list[str]) -> None:
    """A review one reviewer run covers: one chunk with the whole diff and a cell per group."""
    if not groups:
        raise Refused("--single needs --groups G1=\"Perspective;Perspective\" ...")
    s = review.state
    diff = parse_diff(review.diff_path)
    files = sorted(diff)
    s["chunks"]["C01"] = {"title": "whole diff", "files": files, "lines": chunk_lines(files, diff), "kind": "logic",
                          "risk": "medium", "treatment": "full"}
    for spec in groups:
        gid, sep, names = spec.partition("=")
        perspectives = [n.strip() for n in names.split(";") if n.strip()]
        if not sep or not gid or not perspectives:
            raise Refused(f"expected G1=\"Perspective;Perspective\", got {spec!r}")
        s["groups"][gid] = {"title": ", ".join(perspectives), "perspectives": perspectives}
        s["cells"][cell_id("C01", gid)] = {"status": "pending", "owner": None, "wave": None, "unchecked": []}


def cmd_audit_diff(review: Review, args) -> None:
    revision = review.state["revision"]
    if not revision.get("audit"):
        raise Refused("not an audit; write the fresh diff the same way as diff.patch")
    if args.file.resolve() == review.diff_path.resolve():
        raise Refused("write the fresh diff into another file, e.g. diff.new.patch")
    files = write_audit_diff(revision, args.file)
    print(f"{len(files)} whole files written to {args.file}; continue with refresh")


def cmd_triage(review: Review, args) -> None:
    files = parse_diff(review.diff_path)
    by_kind: dict[str, list[dict]] = {}
    for info in files.values():
        by_kind.setdefault(classify(info), []).append(info)
    chunks: dict[str, dict] = {}
    n = 0
    for group in pack(by_kind.pop("logic", []), args.chunk_lines):
        n += 1
        paths = sorted(f["path"] for f in group)
        chunks[f"C{n:02d}"] = {"title": common_dir(paths), "files": paths, "lines": sum(size(f) for f in group),
                               "kind": "logic", "risk": "medium", "treatment": "full"}
    for kind in sorted(by_kind):
        n += 1
        paths = sorted(f["path"] for f in by_kind[kind])
        chunks[f"C{n:02d}"] = {"title": kind.replace("_", " "), "files": paths,
                               "lines": sum(size(f) for f in by_kind[kind]), "kind": kind, "risk": "low",
                               "treatment": "light"}
    proposal = {"chunk_lines": args.chunk_lines, "chunks": chunks}
    out = args.out or review.root / "triage.json"
    write_json(out, proposal)
    total = sum(c["lines"] for c in chunks.values())
    print(f"{len(files)} files, {total} changed lines -> {len(chunks)} proposed chunks in {out}")
    for cid, c in chunks.items():
        print(f"  {cid}  {c['kind']:<12} {c['treatment']:<6} {c['lines']:>7} lines  {len(c['files']):>4} files  {c['title']}")
    print("edit risk, treatment, titles and file grouping (keep tests with their code), then run chunks")


def cmd_chunks(review: Review, args) -> None:
    proposal = read_json(args.file)
    started = {k.partition("/")[0] for k, c in review.state["cells"].items() if c["status"] != "pending"}
    for cid in proposal.get("chunks", {}):
        if cid in started:
            raise Refused(f"chunk {cid} already has reviewed cells; change it with chunk instead")
    diff = parse_diff(review.diff_path) if review.diff_path.exists() else {}
    for cid, chunk in proposal["chunks"].items():
        try:
            chunk["files"] = expand(chunk.get("files", []), diff, "diff.patch")
        except Refused as e:
            raise Refused(f"chunk {cid}: {e}")
        if diff:
            chunk["lines"] = chunk_lines(chunk["files"], diff)
        chunk.setdefault("risk", "medium")
        chunk.setdefault("treatment", "full")
        if chunk["risk"] not in RISKS or chunk["treatment"] not in TREATMENTS:
            raise Refused(f"chunk {cid}: risk must be {'/'.join(RISKS)}, treatment {'/'.join(TREATMENTS)}")
        if chunk["treatment"] == "excluded" and not chunk.get("reason"):
            raise Refused(f"chunk {cid}: excluded needs a reason")
        review.state["chunks"][cid] = chunk
    review.save()
    review.append_log({"type": "chunks", "file": str(args.file), "chunks": list(proposal["chunks"])})
    print(f"loaded {len(proposal['chunks'])} chunks")


def outside_files(review: Review, items: list[str], own: list[str], what: str) -> list[str]:
    """Files outside a chunk that its change affects, as a reviewer found them.

    Patterns match the repository on disk and the diff; files of the chunk itself are left out."""
    if not items:
        return []
    universe = review.impact_universe()
    files = expand(items, universe, "the repository", literal="require" if universe else "keep")
    named = [i for i in items if i in own]
    if named:
        raise Refused(f"{', '.join(named)} in {what}; its own files are not its impact")
    return sorted(f for f in files if f not in own)


def cmd_chunk(review: Review, args) -> None:
    chunk = review.state["chunks"].get(args.id, {})
    if not chunk and not args.title:
        raise Refused(f"new chunk {args.id} needs --title")
    if args.title:
        chunk["title"] = args.title
    chunk["risk"] = args.risk or chunk.get("risk", "medium")
    chunk["treatment"] = args.treatment or chunk.get("treatment", "full")
    if args.files is not None:
        diff = parse_diff(review.diff_path)
        chunk["files"] = sorted(expand(args.files, diff, "diff.patch"))
        chunk["lines"] = chunk_lines(chunk["files"], diff)
    chunk.setdefault("files", [])
    if args.integration:
        chunk["kind"] = "integration"
    chunk.setdefault("kind", "logic")
    if args.reason:
        chunk["reason"] = args.reason
    if chunk["treatment"] == "excluded" and not chunk.get("reason"):
        raise Refused("excluded needs --reason")
    review.state["chunks"][args.id] = chunk
    review.save()
    review.append_log({"type": "chunk", "id": args.id, **{k: v for k, v in chunk.items() if k != "files"}})
    print(f"chunk {args.id}: {chunk['kind']}, {chunk['treatment']}, {len(chunk['files'])} files")


def cmd_group(review: Review, args) -> None:
    review.state["groups"][args.id] = {"title": args.title or ", ".join(args.perspectives),
                                       "perspectives": args.perspectives}
    review.save()
    review.append_log({"type": "group", "id": args.id, "perspectives": args.perspectives})
    print(f"group {args.id}: {', '.join(args.perspectives)}")


def cmd_cell(review: Review, args) -> None:
    review.chunk(args.chunk)
    for gid in args.groups:
        if gid not in review.state["groups"]:
            raise Refused(f"unknown group {gid}")
        key = cell_id(args.chunk, gid)
        if key not in review.state["cells"] or review.state["cells"][key]["status"] == "omitted":
            review.state["cells"][key] = {"status": "pending", "owner": None, "wave": None, "unchecked": []}
    review.save()
    review.append_log({"type": "cell", "chunk": args.chunk, "groups": args.groups, "status": "pending"})
    print(f"{args.chunk}: cells {', '.join(args.groups)}")


def cmd_omit(review: Review, args) -> None:
    for chunk in args.chunks:
        review.chunk(chunk)
        for group in args.groups:
            if group not in review.state["groups"]:
                raise Refused(f"unknown group {group}")
            key = cell_id(chunk, group)
            cell = review.state["cells"].get(key)
            if cell and cell["status"] not in ("pending", "omitted"):
                raise Refused(f"{key} is already {cell['status']}")
            review.state["cells"][key] = {"status": "omitted", "reason": args.reason}
            review.append_log({"type": "cell", "id": key, "status": "omitted", "reason": args.reason})
            print(f"{key}: omitted")
    review.save()


def cmd_overview(review: Review, args) -> None:
    """One line per chunk, the orientation a reviewer gets about the rest of the review."""
    for cid, c in review.state["chunks"].items():
        where = "links between chunks" if c.get("kind") == "integration" else common_dir(c.get("files", []) or ["."])
        print(f"{cid}  [{c.get('risk')}/{c.get('treatment')}]  {len(c.get('files', [])):>4} files  {c['title']}  ({where})")


def cmd_estimate(review: Review, args) -> None:
    s = review.state
    treat = {t: [c for c in s["chunks"].values() if c.get("treatment") == t] for t in TREATMENTS}
    for t, chunks in treat.items():
        if chunks:
            lines = sum(c.get("lines", 0) for c in chunks)
            files = sum(len(c.get("files", [])) for c in chunks)
            print(f"{t}: {len(chunks)} chunks, {files} files, {lines} changed lines")
    counts = {st: sum(1 for c in s["cells"].values() if c["status"] == st) for st in CELL_STATUSES}
    print("cells: " + ", ".join(f"{st} {n}" for st, n in counts.items() if n))
    waiting = counts["pending"] + counts["partial"]
    integration = sum(1 for k, c in s["cells"].items()
                      if c["status"] in ("pending", "partial") and s["chunks"][k.partition("/")[0]].get("kind") == "integration")
    print(f"waves of {s['wave_size']}: {review.waves_needed()} (about {waiting} reviewer runs, "
          f"{integration} of them integration), plus verification and synthesis")


def cmd_approve(review: Review, args) -> None:
    review.state["approval"] = {"coverage": args.coverage, "note": args.note, "at": now()}
    review.save()
    review.append_log({"type": "decision", "text": f"coverage {args.coverage}", "note": args.note})
    print(f"approved: {args.coverage}")


def ready_cells(review: Review) -> list[str]:
    s = review.state
    chunk_of = lambda k: s["chunks"][k.partition("/")[0]]  # noqa: E731
    risk_first = (s.get("approval") or {}).get("coverage") == "risk_first"
    skipped = lambda k: risk_first and chunk_of(k).get("risk") == "low"  # noqa: E731
    local_open = any(c["status"] in OPEN_CELLS for k, c in s["cells"].items()
                     if chunk_of(k).get("kind") != "integration" and not skipped(k))
    order = {r: i for i, r in enumerate(RISKS)}
    ready = []
    for key, cell in s["cells"].items():
        if cell["status"] not in ("pending", "partial") or skipped(key):
            continue
        if chunk_of(key).get("kind") == "integration" and local_open:
            continue
        ready.append(key)
    return sorted(ready, key=lambda k: (cell_rank(s["cells"][k]), order.get(chunk_of(k).get("risk"), 9), k))


def cell_rank(cell: dict) -> int:
    return 0 if cell["status"] == "partial" else 1


def cmd_next(review: Review, args) -> None:
    s = review.state
    if review.waves_needed() > 1 and not s.get("approval"):
        raise Refused("more than one wave is needed; show estimate to the user and record approve first")
    running = [k for k, c in s["cells"].items() if c["status"] == "running"]
    free = (args.limit or s["wave_size"]) - len(running)
    if running:
        print(f"running: {', '.join(running)}")
    ready = ready_cells(review)
    for key in ready[:max(free, 0)]:
        chunk = s["chunks"][key.partition("/")[0]]
        cell = s["cells"][key]
        extra = f"  follow-up: {', '.join(cell['unchecked'])}" if cell["status"] == "partial" else ""
        print(f"{key}  [{chunk['risk']}/{chunk['treatment']}]  {len(chunk.get('files', []))} files  "
              f"{chunk['title']}{extra}")
    if not ready:
        print("no cell is ready" + (" (integration waits for the local cells)" if review.open_cells() else ""))
    elif free <= 0:
        print("no free slot in the current wave")


def cmd_start(review: Review, args) -> None:
    s = review.state
    cells = [review.cell(k) for k in args.cells]
    for key, cell in zip(args.cells, cells):
        if cell["status"] not in ("pending", "partial"):
            raise Refused(f"{key} is {cell['status']}")
    running = [c for c in s["cells"].values() if c["status"] == "running"]
    wave = running[0]["wave"] if running else len(s["waves"]) + 1
    if wave > len(s["waves"]):
        s["waves"].append({"wave": wave, "started_at": now(), "cells": []})
    s["waves"][wave - 1]["cells"].extend(args.cells)
    for cell in cells:
        cell.update({"status": "running", "owner": args.owner, "wave": wave})
    review.save()
    review.append_log({"type": "cell", "ids": args.cells, "status": "running", "owner": args.owner, "wave": wave})
    print(f"wave {wave}: {args.owner} -> {', '.join(args.cells)}")


def skipped_specs(specs: list[str]) -> list[tuple[str, str]]:
    out = []
    for spec in specs:
        pattern, sep, reason = spec.partition("=")
        if not sep or not pattern.strip() or not reason.strip():
            raise Refused(f"expected --skipped PATTERN=REASON, got {spec!r}")
        out.append((pattern.strip(), reason.strip()))
    return out


def cmd_set(review: Review, args) -> None:
    if args.status == "partial" and not args.unchecked:
        raise Refused("partial needs --unchecked with the concrete files or sections left unchecked")
    if args.status == "omitted" and not args.reason:
        raise Refused("omitted needs --reason")
    for option in ("skipped", "impact", "impact_unchecked"):
        if getattr(args, option) and args.status not in ("covered", "partial"):
            raise Refused(f"--{option.replace('_', '-')} belongs to a covered or partial cell")
    specs = skipped_specs(args.skipped or [])
    if review.actor and args.status not in ("covered", "partial"):
        raise Refused(f"{review.actor} records covered or partial; {args.status} is the orchestrator's decision")
    for key in args.cells:
        cell = review.cell(key)
        if review.actor and (cell.get("owner") != review.actor or cell["status"] != "running"):
            raise Refused(f"{key} is not running for {review.actor}")
        chunk = review.chunk(key.partition("/")[0])
        files = chunk.get("files", [])
        try:
            unchecked = expand(args.unchecked or [], files, f"chunk {key}")
            skipped = {}
            for pattern, reason in specs:
                for path in expand([pattern], files, f"chunk {key}", literal="require"):
                    skipped[path] = reason
            impact = outside_files(review, args.impact or [], files, "the chunk")
            impact_unchecked = outside_files(review, args.impact_unchecked or [], files, "the chunk")
        except Refused as e:
            raise Refused(f"{key}: {e}")
        both = sorted(set(skipped) & set(unchecked))
        if both:
            raise Refused(f"{key}: {', '.join(both)} both skipped and unchecked")
        both = sorted(set(impact) & set(impact_unchecked))
        if both:
            raise Refused(f"{key}: {', '.join(both)} both in --impact and --impact-unchecked")
        previous = cell["status"]
        cell["status"] = args.status
        cell["unchecked"] = unchecked
        if args.status in ("covered", "partial"):
            # A follow-up run reports on the files left unchecked; the earlier skips stay.
            kept = {p: r for p, r in (cell.get("skipped") or {}).items() if p not in unchecked}
            cell["skipped"] = {**kept, **skipped}
            # The impact adds up over the runs; a file checked later is no longer open.
            checked = sorted(set(cell.get("impact", [])) | set(impact))
            cell["impact"] = checked
            cell["impact_unchecked"] = sorted((set(cell.get("impact_unchecked", [])) | set(impact_unchecked))
                                               - set(checked))
        for option in ("skipped", "impact", "impact_unchecked"):
            if not cell.get(option) or args.status not in ("covered", "partial"):
                cell.pop(option, None)
        if args.reason:
            cell["reason"] = args.reason
        if args.status == "pending":
            cell.update({"owner": None, "wave": None})
        record = {"type": "cell", "id": key, "status": args.status, "from": previous}
        if unchecked:
            record["unchecked"] = unchecked
        if skipped:
            record["skipped"] = skipped
        if impact:
            record["impact"] = impact
        if impact_unchecked:
            record["impact_unchecked"] = impact_unchecked
        if args.reason:
            record["reason"] = args.reason
        review.append_log(record)
        notes = [f"{len(skipped)} files skipped"] if skipped else []
        notes += [f"{len(impact)} impact files checked"] if impact else []
        notes += [f"{len(impact_unchecked)} impact files not checked"] if impact_unchecked else []
        print(f"{key}: {previous} -> {args.status}" + (", " + ", ".join(notes) if notes else ""))
    review.save()


def body_text(review: Review, value: str, option: str) -> str:
    if value == "-" and review.in_batch:
        raise Refused(f"{option} - reads the standard input, which the batch uses; put the text into the line")
    text = sys.stdin.read() if value == "-" else value
    if not text.strip():
        raise Refused(f"{option} is empty")
    return text if text.endswith("\n") else text + "\n"


def cmd_finding(review: Review, args) -> None:
    cell = review.cell(args.cell)
    if review.actor:
        if cell.get("owner") != review.actor or cell["status"] != "running":
            raise Refused(f"{args.cell} is not running for {review.actor}")
        if args.reviewer not in (None, review.actor):
            raise Refused(f"{review.actor} records only its own findings")
        args.reviewer = review.actor
    if args.id in review.state["findings"]:
        raise Refused(f"finding {args.id} already exists; IDs are stable")
    path = review.findings_dir / f"{args.id}.md"
    if args.body is not None:
        if review.read_file(path) is not None:
            raise Refused(f"findings/{args.id}.md already exists")
        review.write_file(path, body_text(review, args.body, "--body"))
    elif review.read_file(path) is None:
        raise Refused(f"write findings/{args.id}.md with the full finding first, or pass it as --body")
    if args.kind == "bug" and not args.severity:
        raise Refused("a bug needs --severity")
    locations = [location_file(f) for f in args.files or []]
    if any(is_pattern(f) and f not in review.diff_files() for f in locations):
        print("warning: a finding's location names concrete files; patterns were expanded against diff.patch")
        locations = expand(locations, review.diff_files(), "diff.patch")
    files = sorted(set(locations))
    review.state["findings"][args.id] = {
        "cell": args.cell, "reviewer": args.reviewer or cell.get("owner"), "kind": args.kind, "severity": args.severity,
        "title": args.title, "files": files, "outside": args.outside, "status": "unverified", "verifications": [],
    }
    review.save()
    review.append_log({"type": "finding", "id": args.id, "status": "unverified", "cell": args.cell})
    print(f"{args.id}: recorded")
    if files and not args.outside and review.diff_path.exists():
        unknown = [f for f in files if f not in review.diff_files()]
        if unknown:
            print(f"warning: not in diff.patch, refresh will not track them: {', '.join(unknown)}")


def location_file(location: str) -> str:
    """The repository path of a location such as ./src/x.php:42 or src/x.php:10-20."""
    path = re.sub(r":\d+(?:[-:]\d+)*$", "", location.strip())
    return path[2:] if path.startswith("./") else path


def cmd_verify(review: Review, args) -> None:
    if review.actor and args.verifier not in (None, review.actor):
        raise Refused(f"{review.actor} records only its own verifications")
    args.verifier = args.verifier or review.actor
    if not args.verifier:
        raise Refused("verify needs --verifier")
    note = body_text(review, args.note, "--note") if args.note is not None else None
    for fid in args.ids:
        f = review.finding(fid)
        if note:
            path = review.findings_dir / f"{fid}.md"
            text = review.read_file(path) or ""
            review.write_file(path, f"{text.rstrip()}\n\n## Verification by {args.verifier}: {args.verdict}\n\n{note}")
        if args.verifier == f.get("reviewer"):
            raise Refused(f"{args.verifier} reported {fid}; a verifier is never the sole verifier of its own finding")
        f["verifications"].append({"verifier": args.verifier, "verdict": args.verdict, "at": now()})
        if args.severity:
            f["severity"] = args.severity
        verdicts = {v["verdict"] for v in f["verifications"]}
        f["status"] = next(iter(verdicts)) if len(verdicts) == 1 else "disputed"
        verifiers = {v["verifier"] for v in f["verifications"]}
        review.append_log({"type": "verification", "id": fid, "verifier": args.verifier, "verdict": args.verdict,
                           "status": f["status"]})
        print(f"{fid}: {f['status']}" + ("  (needs a second verifier)" if needs_second(f) and len(verifiers) < 2 else ""))
        before = f["refreshes"][-1]["status"] if f.get("refreshes") else None
        if before == "awaiting_decision" and len(f["verifications"]) == 1:
            print(f"{fid} was awaiting_decision before the refresh; resolve it again if the decision is still open")
    review.save()


def cmd_resolve(review: Review, args) -> None:
    if args.status == "duplicate" and not args.duplicate_of:
        raise Refused("duplicate needs --duplicate-of")
    for fid in args.ids:
        f = review.finding(fid)
        if args.status == "duplicate":
            if args.duplicate_of == fid:
                raise Refused(f"{fid} cannot be a duplicate of itself")
            review.finding(args.duplicate_of)
            f["duplicate_of"] = args.duplicate_of
        previous = f["status"]
        f["status"] = args.status
        f["resolution"] = args.reason
        review.append_log({"type": "finding", "id": fid, "status": args.status, "from": previous, "reason": args.reason})
        print(f"{fid}: {previous} -> {args.status}")
    review.save()


def finding_line(fid: str, f: dict) -> str:
    tag = f"{f.get('severity') or '-'}/{f['kind']}/{f['status']}"
    if f["status"] == "stale":
        tag += f", was {f['refreshes'][-1]['status']}"
    return f"{fid}  [{tag}]  {f['cell']}  {f['title']}" + ("  (outside the change)" if f.get("outside") else "")


def cmd_findings(review: Review, args) -> None:
    items = list(review.state["findings"].items())
    if args.status:
        items = [(i, f) for i, f in items if f["status"] == args.status]
    elif not args.all:
        items = [(i, f) for i, f in items if f["status"] not in ("refuted", "duplicate")]
    if args.chunk:
        items = [(i, f) for i, f in items if f["cell"].partition("/")[0] == args.chunk]
    rank = {s: i for i, s in enumerate(SEVERITIES)}
    for fid, f in sorted(items, key=lambda x: (rank.get(x[1].get("severity"), 9), x[0])):
        print(finding_line(fid, f))
    if not items:
        print("no findings")


def cmd_coverage(review: Review, args) -> None:
    s = review.state
    gaps = 0
    for key, cell in s["cells"].items():
        if cell["status"] in OPEN_CELLS:
            gaps += 1
            extra = f": {', '.join(cell['unchecked'])}" if cell.get("unchecked") else ""
            print(f"open {key} ({cell['status']}){extra}")
    for key, cell in s["cells"].items():
        if cell["status"] == "omitted":
            print(f"omitted {key}: {cell.get('reason')}")
    for key, cell in s["cells"].items():
        by_reason: dict[str, list[str]] = {}
        for path, reason in (cell.get("skipped") or {}).items():
            by_reason.setdefault(reason, []).append(path)
        for reason, paths in by_reason.items():
            print(f"skipped {key} ({len(paths)} files, {reason}): {', '.join(paths)}")
    for key, cell in s["cells"].items():
        if cell.get("impact_unchecked"):
            print(f"impact not checked {key} (a limitation, not a gap): {', '.join(cell['impact_unchecked'])}")
    for cid, chunk in s["chunks"].items():
        if chunk.get("treatment") == "excluded":
            print(f"excluded {cid} ({len(chunk.get('files', []))} files): {chunk.get('reason')}")
    errors, _ = validate(review)
    for e in errors:
        if "in no chunk" in e or "no cells" in e:
            gaps += 1
            print(f"gap: {e}")
    print("coverage complete" if not gaps else f"{gaps} open items")


def cmd_refresh(review: Review, args) -> None:
    """Compare a fresh diff of the same scope with diff.patch; reopen the cells and findings it touches."""
    s = review.state
    if args.file.resolve() == review.diff_path.resolve():
        raise Refused("write the fresh diff into another file, e.g. diff.new.patch")
    old, new = parse_diff(review.diff_path), parse_diff(args.file)
    changed = sorted(p for p in old.keys() & new.keys() if old[p]["hash"] != new[p]["hash"])
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    touched = set(changed) | set(removed)
    if not touched and not added:
        print("no change: the fresh diff matches diff.patch")
        if not args.dry_run:
            update_shas(review)
            review.save()
            review.append_log({"type": "refresh", "changed": [], "added": [], "removed": []})
        return

    single = s.get("single") and "C01" in s["chunks"]
    recheck = set(changed) | (set(added) if single else set())
    local = {cid: set(c.get("files", [])) for cid, c in s["chunks"].items() if c.get("kind") != "integration"}
    if single:
        local["C01"] |= set(added)
    cells: dict[str, list[str]] = {}
    for key, cell in s["cells"].items():
        cid = key.partition("/")[0]
        files = local[cid] & recheck if cid in local else recheck | set(added)
        if files and cell["status"] in ("covered", "partial", "running"):
            cells[key] = sorted(files)
    running = [k for k in cells if s["cells"][k]["status"] == "running"]
    if running:
        raise Refused(f"running cells on changed files: {', '.join(running)}; record their result or return "
                      "them with set … pending first")
    findings: dict[str, list[str]] = {}
    for fid, f in s["findings"].items():
        if f["status"] in SETTLED_FINDINGS:
            continue
        cid = f["cell"].partition("/")[0]
        scope = set(f.get("files") or []) or (local[cid] if cid in local else touched | set(added))
        hit = scope & (touched | set(added))
        if hit:
            findings[fid] = sorted(hit)

    print(f"changed {len(changed)}, added {len(added)}, removed {len(removed)} files")
    for label, paths in (("changed", changed), ("added", added), ("removed", removed)):
        for path in paths:
            print(f"  {label:<8} {path}")
    for key, files in cells.items():
        print(f"reopen {key} ({s['cells'][key]['status']} -> partial): {len(files)} files to recheck")
    for fid, files in findings.items():
        print(f"stale {fid} ({s['findings'][fid]['status']}): {', '.join(files)}")
    if args.dry_run:
        return

    number = len(s.setdefault("refreshes", [])) + 1
    previous = review.root / "previous" / f"diff-{number:02d}.patch"
    previous.parent.mkdir(exist_ok=True)
    os.replace(review.diff_path, previous)
    if args.file.resolve().parent == review.root.resolve():
        os.replace(args.file, review.diff_path)
    else:
        shutil.copyfile(args.file, review.diff_path)
    reason = f"refresh {number}: changed files"
    for key, files in cells.items():
        cell = s["cells"][key]
        cell.update({"status": "partial", "unchecked": sorted(set(cell.get("unchecked", [])) | set(files)),
                     "reason": reason})
    for cell in s["cells"].values():
        if cell.get("skipped"):  # a skip judged the old content; a changed or removed file is judged again
            cell["skipped"] = {p: r for p, r in cell["skipped"].items() if p not in touched}
            if not cell["skipped"]:
                del cell["skipped"]
        if cell.get("unchecked"):
            cell["unchecked"] = [u for u in cell["unchecked"] if u not in removed]
            if cell["status"] == "partial" and not cell["unchecked"]:
                cell.update({"status": "covered", "reason": f"refresh {number}: unchecked files left the diff"})
    for chunk in s["chunks"].values():
        chunk["files"] = [f for f in chunk.get("files", []) if f not in removed]
    if single:
        s["chunks"]["C01"]["files"] = sorted(local["C01"] - set(removed))
    for chunk in s["chunks"].values():
        chunk["lines"] = chunk_lines(chunk["files"], new)
    new_chunk = None
    if added and not single:
        numbers = [int(m.group(1)) for m in (re.fullmatch(r"C(\d+)", c) for c in s["chunks"]) if m]
        new_chunk = f"C{max(numbers, default=0) + 1:02d}"
        s["chunks"][new_chunk] = {"title": f"added by refresh {number}", "files": added,
                                  "lines": sum(size(new[p]) for p in added), "kind": "logic", "risk": "medium",
                                  "treatment": "full"}
    for fid, files in findings.items():
        f = s["findings"][fid]
        f.setdefault("refreshes", []).append({"refresh": number, "files": files, "status": f["status"],
                                              "verifications": f["verifications"]})
        f.update({"status": "stale", "verifications": []})
    update_shas(review)
    s["refreshes"].append({"at": now(), "previous": str(previous.relative_to(review.root)), "changed": changed,
                           "added": added, "removed": removed, "cells": list(cells), "findings": list(findings),
                           "new_chunk": new_chunk})
    review.save()
    review.append_log({"type": "refresh", "number": number, "changed": changed, "added": added, "removed": removed,
                       "cells": list(cells), "findings": list(findings), "new_chunk": new_chunk})
    print(f"refresh {number}: diff.patch replaced, previous kept in {previous.relative_to(review.root)}")
    if new_chunk:
        print(f"added files are in chunk {new_chunk} without cells: move them with chunk or assign cells")


def update_shas(review: Review) -> None:
    rev = review.state["revision"]
    if rev.get("repo"):
        if rev.get("base"):
            rev["base_sha"] = resolve_sha(rev["repo"], rev["base"]) or rev.get("base_sha")
        rev["head_sha"] = resolve_sha(rev["repo"], rev["head"]) or rev.get("head_sha")


def moved_revisions(rev: dict) -> list[str]:
    moved = []
    for side in ("base", "head"):
        recorded = rev.get(f"{side}_sha")
        current = resolve_sha(rev.get("repo"), rev[side]) if rev.get("repo") and recorded else None
        if current and current != recorded:
            moved.append(f"{side} {rev[side]} moved {recorded[:10]} -> {current[:10]}")
    return moved


def cmd_status(review: Review, args) -> None:
    s = review.state
    rev = s["revision"]
    if rev.get("audit"):
        print(f"scope: {s['scope']}  audit of {' '.join(rev['audit'])} at {'the working tree' if rev['working_tree'] else rev['head']}")
    else:
        print(f"scope: {s['scope']}  base {rev['base']} head {rev['head']}" + ("  + working tree" if rev["working_tree"] else ""))
    for line in moved_revisions(rev):
        print(f"changed: {line}; write the current diff and run refresh")
    if rev["working_tree"]:
        print("working tree: changes since diff.patch show only in refresh with the current diff"
              + (" (audit-diff writes it)" if rev.get("audit") else ""))
    approval = s.get("approval")
    print(f"approval: {approval['coverage'] if approval else 'none'}; wave size {s['wave_size']}; "
          f"waves started {len(s['waves'])}, still needed {review.waves_needed()}")
    counts = {st: sum(1 for c in s["cells"].values() if c["status"] == st) for st in CELL_STATUSES}
    print(f"chunks {len(s['chunks'])}, groups {len(s['groups'])}; cells: "
          + (", ".join(f"{st} {n}" for st, n in counts.items() if n) or "none"))
    for key, cell in s["cells"].items():
        if cell["status"] == "running":
            print(f"running: {key} ({cell.get('owner')}, wave {cell.get('wave')})")
    fcounts: dict[str, int] = {}
    for f in s["findings"].values():
        fcounts[f["status"]] = fcounts.get(f["status"], 0) + 1
    if fcounts:
        print("findings: " + ", ".join(f"{st} {n}" for st, n in sorted(fcounts.items())))
    second = [i for i, f in s["findings"].items() if needs_second(f) and len({v["verifier"] for v in f["verifications"]}) < 2]
    if second:
        print(f"needs a second verifier: {', '.join(second)}")
    stale = [i for i, f in s["findings"].items() if f["status"] == "stale"]
    if stale:
        print(f"stale after refresh, verify again: {', '.join(stale)}")
    ready = ready_cells(review)
    print(f"ready cells: {len(ready)}" + (f" (next: {', '.join(ready[:s['wave_size']])})" if ready else ""))


def cmd_validate(review: Review, args) -> None:
    errors, warnings = validate(review)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        raise SystemExit(1)
    print(f"ok: {len(review.state['cells'])} cells, {len(review.state['findings'])} findings, {len(warnings)} warnings")


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def log_field(pair: str) -> tuple[str, object]:
    key, sep, value = pair.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected key=value, got {pair!r}")
    if key in ("at", "type"):
        raise argparse.ArgumentTypeError(f"{key} is set by the tool")
    return key, parse_value(value)


def cmd_log(review: Review, args) -> None:
    record = {"type": args.type, **dict(args.fields)}
    missing = [f for f in LOG_REQUIRED[args.type] if f not in record]
    if missing:
        raise Refused(f"{args.type} needs: {', '.join(missing)}")
    review.append_log(record)
    print("logged " + json.dumps(record, ensure_ascii=False))


class UsageError(Exception):
    """Wrong usage of one command inside a batch."""


class Parser(argparse.ArgumentParser):
    raise_errors = False  # inside a batch a wrong line is refused instead of ending the process

    def error(self, message):
        if Parser.raise_errors:
            raise UsageError(message)
        super().error(message)


def build_parser() -> Parser:
    parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("--as", dest="actor", metavar="ID",
                        help="a reviewer or verifier recording its own results; limited to its cells and findings")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("--scope", required=True)
    p.add_argument("--base", help="the base of a change; not with --audit")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--audit", nargs="+", metavar="PATTERN", help="review the whole files these patterns match")
    p.add_argument("--working-tree", action="store_true")
    p.add_argument("--wave-size", type=int, default=DEFAULT_WAVE_SIZE)
    p.add_argument("--single", action="store_true", help="one chunk with the whole diff.patch, cells per group")
    p.add_argument("--groups", nargs="+", default=[], help='with --single: G1="Perspective;Perspective"')
    p = sub.add_parser("audit-diff")
    p.add_argument("file", type=Path, help="where to write the current whole files of the audit")
    p = sub.add_parser("triage")
    p.add_argument("--chunk-lines", type=int, default=DEFAULT_CHUNK_LINES)
    p.add_argument("--out", type=Path)
    p = sub.add_parser("chunks")
    p.add_argument("file", type=Path)
    p = sub.add_parser("chunk")
    p.add_argument("id")
    p.add_argument("--title", help="required for a new chunk")
    p.add_argument("--files", nargs="*")
    p.add_argument("--risk", choices=RISKS, help="medium for a new chunk; kept when omitted")
    p.add_argument("--treatment", choices=TREATMENTS, help="full for a new chunk; kept when omitted")
    p.add_argument("--integration", action="store_true", help="cross-chunk cells; ready after all local cells")
    p.add_argument("--reason")
    p = sub.add_parser("group")
    p.add_argument("id")
    p.add_argument("--perspectives", nargs="+", required=True)
    p.add_argument("--title")
    p = sub.add_parser("cell")
    p.add_argument("chunk")
    p.add_argument("groups", nargs="+")
    p = sub.add_parser("omit")
    p.add_argument("chunks", nargs="+")
    p.add_argument("--groups", nargs="+", required=True)
    p.add_argument("--reason", required=True)
    sub.add_parser("overview")
    sub.add_parser("estimate")
    p = sub.add_parser("approve")
    p.add_argument("--coverage", choices=("full", "risk_first"), required=True)
    p.add_argument("--note")
    p = sub.add_parser("next")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("start")
    p.add_argument("--owner", required=True, help="reviewer ID, e.g. R3")
    p.add_argument("cells", nargs="+")
    p = sub.add_parser("set")
    p.add_argument("cells", nargs="+")
    p.add_argument("status", choices=CELL_STATUSES)
    p.add_argument("--unchecked", nargs="+")
    p.add_argument("--skipped", nargs="+", metavar="PATTERN=REASON",
                   help="files of the chunk not relevant to the cell's perspectives, with the reason")
    p.add_argument("--impact", nargs="+", help="files outside the chunk the change affects, checked by the reviewer")
    p.add_argument("--impact-unchecked", nargs="+",
                   help="files outside the chunk the reviewer knows the change affects but did not check")
    p.add_argument("--reason")
    p = sub.add_parser("finding")
    p.add_argument("id")
    p.add_argument("--cell", required=True)
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--severity", choices=SEVERITIES)
    p.add_argument("--files", nargs="+", help="files of the finding's location; refresh marks it stale by them")
    p.add_argument("--outside", action="store_true", help="an existing problem outside the change")
    p.add_argument("--reviewer", help="defaults to the owner of the cell")
    p.add_argument("--body", help="the full finding, written to findings/ID.md; - reads the standard input")
    p = sub.add_parser("verify")
    p.add_argument("ids", nargs="+")
    p.add_argument("verdict", choices=VERDICTS)
    p.add_argument("--verifier", help="the verifier's ID; with --as that ID")
    p.add_argument("--note", help="the evidence, appended to findings/ID.md; - reads the standard input")
    p.add_argument("--severity", choices=SEVERITIES)
    p = sub.add_parser("resolve")
    p.add_argument("ids", nargs="+")
    p.add_argument("status", choices=FINDING_STATUSES)
    p.add_argument("--reason", required=True)
    p.add_argument("--duplicate-of")
    p = sub.add_parser("findings")
    p.add_argument("--status", choices=FINDING_STATUSES)
    p.add_argument("--chunk")
    p.add_argument("--all", action="store_true")
    sub.add_parser("coverage")
    p = sub.add_parser("refresh")
    p.add_argument("file", type=Path, help="a fresh diff of the same scope, written the same way as diff.patch")
    p.add_argument("--dry-run", action="store_true", help="print the impact without changing anything")
    sub.add_parser("status")
    sub.add_parser("validate")
    p = sub.add_parser("log")
    p.add_argument("type", choices=list(LOG_REQUIRED))
    p.add_argument("fields", nargs="*", type=log_field, help="key=value; values are parsed as JSON when possible")
    p = sub.add_parser("batch")
    p.add_argument("file", help="a file of commands, one per line, or - for the standard input")
    return parser


COMMANDS = {
    "init": cmd_init, "audit-diff": cmd_audit_diff, "triage": cmd_triage, "chunks": cmd_chunks, "chunk": cmd_chunk,
    "group": cmd_group, "cell": cmd_cell, "omit": cmd_omit, "overview": cmd_overview, "estimate": cmd_estimate,
    "approve": cmd_approve, "next": cmd_next, "start": cmd_start, "set": cmd_set, "finding": cmd_finding,
    "verify": cmd_verify, "resolve": cmd_resolve, "findings": cmd_findings, "coverage": cmd_coverage,
    "refresh": cmd_refresh, "status": cmd_status, "validate": cmd_validate, "log": cmd_log,
}
BATCH_COMMANDS = ("chunks", "chunk", "group", "cell", "omit", "approve", "start", "set", "finding", "verify",
                  "resolve", "log")


def batch_items(line: str) -> list[str]:
    """One batch line: shell-like arguments, or a JSON array of them."""
    if line.startswith("["):
        items = json.loads(line)
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise ValueError("a JSON line must be an array of strings")
        return items
    return shlex.split(line)


def cmd_batch(review: Review, args) -> None:
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
    output = io.StringIO()  # printed only when the whole batch is applied
    review.in_batch = True
    try:
        with contextlib.redirect_stdout(output):
            count = run_batch(review, args, text)
    finally:
        review.in_batch = False
    print(output.getvalue() + f"batch: {count} commands applied")


def run_batch(review: Review, args, text: str) -> int:
    parser, count = build_parser(), 0
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        Parser.raise_errors = True
        try:
            ns = parser.parse_args([str(args.review_dir), *batch_items(line)])
        except (ValueError, UsageError) as e:
            raise Refused(f"line {n}: {e}; nothing was written")
        except SystemExit:
            raise Refused(f"line {n}: wrong usage; nothing was written")
        finally:
            Parser.raise_errors = False
        if ns.command not in BATCH_COMMANDS:
            raise Refused(f"line {n}: {ns.command} is not allowed in a batch; nothing was written")
        if ns.actor not in (None, args.actor):
            raise Refused(f"line {n}: --as is given once for the whole batch; nothing was written")
        ns.actor = args.actor
        check_actor(ns)
        try:
            COMMANDS[ns.command](review, ns)
        except Refused as e:
            raise Refused(f"line {n}: {e}; nothing was written")
        count += 1
    return count


COMMANDS["batch"] = cmd_batch
# What a subagent may run with --as: its own findings, coverage and verifications, and the read-only views.
ACTOR_COMMANDS = ("finding", "set", "verify", "log", "batch", "next", "findings", "coverage", "overview", "status",
                  "estimate", "validate")


def check_actor(args) -> None:
    if args.actor and args.command not in ACTOR_COMMANDS:
        raise Refused(f"{args.command} is the orchestrator's; with --as only {', '.join(ACTOR_COMMANDS)}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "init" and not (args.base or args.audit):
        parser.error("init needs --base REF, or --audit PATTERN … for whole files")
    if args.command == "init" and args.base and args.audit:
        parser.error("init takes --base for a change or --audit for whole files, not both")

    review = Review(args.review_dir)
    if args.command != "init" and not review.state_path.exists():
        parser.error(f"{args.review_dir} is not a review folder (missing review.json; run init)")
    review.actor = args.actor
    try:
        check_actor(args)
        if args.command == "init":
            review.root.mkdir(parents=True, exist_ok=True)
        with review.locked(), review.transaction():
            COMMANDS[args.command](review, args)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
