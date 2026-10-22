#!/usr/bin/env python3
"""Track a click-through pass: scenarios, their scripts, runs in a limited number of headless browsers,
triage of failures, judgments of screenshots and findings.

Usage:
    browser.py DIR init --scope S --url URL [--repo DIR] [--head REF] [--base REF] [--working-tree] [--max-browsers N]
                        [--timeout SEC] [--viewport NAME=WxH ...] [--playwright DIR ...] [--browser B]
    browser.py DIR config [--url URL] [--max-browsers N] [--timeout SEC] [--viewport NAME=WxH ...] ...
    browser.py DIR harness                                 copy the current harness.mjs into DIR
    browser.py DIR scenario ID --title T --group G [--kind K] [--priority P] [--role R] [--viewports V ...]
    browser.py DIR scenarios FILE                          add or update scenarios from a JSON list
    browser.py DIR ready ID [ID ...]                       the author confirms a script after running it
    browser.py DIR run [ID ...] [--group G] [--todo|--failed|--all] [--repeat N]
    browser.py DIR result ID                               compact view of the last run of a scenario
    browser.py DIR triage ID app|script|env|flaky [--finding F] [--note N]
    browser.py DIR set ID pending|blocked|unverified --reason R
    browser.py DIR shots [ID ...] [--group G] [--pending]  screenshots with layout hints and diffs
    browser.py DIR judge ID ok|issue [--shots KEY ...] [--finding F] [--note N]
    browser.py DIR finding ID --scenarios S [S ...] --kind K --title T [--severity S]
    browser.py DIR resolve ID STATUS --reason R [--duplicate-of ID]
    browser.py DIR findings [--all]
    browser.py DIR assign --owner O --task T [ID ...] [--group G]
    browser.py DIR release OWNER [--lost]
    browser.py DIR next                                    what to brief, run, triage or judge now
    browser.py DIR status                                  derived overview, the entry point on resume
    browser.py DIR validate
    browser.py DIR log TYPE key=value ...                  append a record (check, decision, note, explore, data)

The format is described in shared/browser-tool.md. Python 3.8+, standard library only; the scenario
scripts need Node 18+ and Playwright. Exit code 0 on success, 1 on a validation error or a refused
change, 2 on wrong usage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows: commands are not serialized between processes
    fcntl = None

SCHEMA_VERSION = 1
HARNESS = Path(__file__).resolve().parent / "browser-harness.mjs"
KINDS = ("functional", "visual", "both")
PRIORITIES = ("high", "medium", "low")
OUTCOMES = ("pending", "passed", "failing", "failed", "blocked", "unverified", "flaky")
OPEN_OUTCOMES = ("pending", "failing")
CAUSES = ("app", "script", "env", "flaky")
JUDGMENTS = ("pending", "ok", "issue")
FINDING_KINDS = ("functional_bug", "ui_bug", "ux_recommendation", "question", "environment")
SEVERITIES = ("critical", "high", "medium", "low")
FINDING_STATUSES = ("open", "awaiting_decision", "fixed", "verified", "rejected", "duplicate")
TASKS = ("script", "triage", "visual", "explore")
LOG_REQUIRED = {"check": ("subject", "result"), "decision": ("text",), "note": ("text",),
                "explore": ("text",), "data": ("text",)}
DEFAULT_VIEWPORTS = {"desktop": {"width": 1440, "height": 900, "mobile": False},
                     "mobile": {"width": 390, "height": 844, "mobile": True}}
DEFAULT_MAX_BROWSERS = 2
DEFAULT_TIMEOUT = 180
DEFAULT_DIFF_THRESHOLD = 0.0
DEFAULT_DIFF_TOLERANCE = 24
ID_RE = re.compile(r"^[A-Za-z][\w.-]*$")


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


def file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.is_file() else None


def natural(key: str):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", key)]


def pid_alive(pid) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    # A killed child of ours stays a zombie until it is reaped; it is gone for our purposes.
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def cmdline(pid: int) -> str:
    """The command of a process: /proc on Linux, ps elsewhere (macOS)."""
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        pass
    try:
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def read_pids(run_dir: Path) -> dict:
    """The node and browser pids the harness wrote for one scenario run, or nothing."""
    try:
        pids = json.loads((run_dir / "pids.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return pids if isinstance(pids, dict) else {}


def kill_group(pid, expect: str) -> bool:
    """Terminate a leftover process group of ours: only when its command still matches, so a reused pid is spared."""
    if os.name != "posix" or not pid_alive(pid) or not re.search(expect, cmdline(pid), re.I):
        return False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        for _ in range(30):
            if not pid_alive(pid):
                return True
            time.sleep(0.1)
    return True


class Testing:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state_path = self.root / "testing.json"
        self.log_path = self.root / "log.jsonl"
        self.findings_dir = self.root / "findings"
        self.results_dir = self.root / "results"
        self.state: dict = {}
        self._thread_lock = threading.RLock()

    @contextmanager
    def locked(self):
        """Serialize state changes between threads and between processes working on the same folder."""
        with self._thread_lock, open(self.root / ".lock", "a+") as handle:
            if fcntl:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                self.state = read_json(self.state_path)
                yield self.state
            finally:
                if fcntl:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def save(self) -> None:
        self.state["updated_at"] = now()
        write_json(self.state_path, self.state)

    def append_log(self, record: dict) -> None:
        record = {"at": now(), **record}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        records = []
        for n, line in enumerate(self.log_path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise Refused(f"{self.log_path}:{n}: invalid JSON: {e}")
        return records

    def scenario(self, sid: str) -> dict:
        if sid not in self.state["scenarios"]:
            raise Refused(f"unknown scenario {sid}")
        return self.state["scenarios"][sid]

    def finding(self, fid: str) -> dict:
        if fid not in self.state["findings"]:
            raise Refused(f"unknown finding {fid}")
        return self.state["findings"][fid]

    def ids(self, group: str | None = None) -> list[str]:
        return sorted((k for k, s in self.state["scenarios"].items() if group in (None, s["group"])), key=natural)

    def script_path(self, sc: dict) -> Path:
        return self.root / sc["script"]

    def script_status(self, sc: dict) -> str:
        current = file_hash(self.script_path(sc))
        if current is None:
            return "pending"
        return "ready" if sc.get("ready_hash") == current else "written"

    def fingerprint(self) -> str | None:
        """HEAD plus a hash of uncommitted changes, so that results from another code state are visible."""
        repo = self.state["revision"].get("repo")
        head = git(repo, "rev-parse", "HEAD")
        if not repo or not head:
            return None
        digest = hashlib.sha256()
        diff = subprocess.run(["git", "-C", repo, "diff", "HEAD", "--binary"], capture_output=True).stdout
        digest.update(diff)
        dirty = bool(diff)
        untracked = git(repo, "ls-files", "--others", "--exclude-standard", "-z") or ""
        for name in sorted(filter(None, untracked.split("\0"))):
            path = (Path(repo) / name).resolve()
            if path == self.root or self.root in path.parents:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            digest.update(f"{name}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
            dirty = True
        return head[:12] + (f"+{digest.hexdigest()[:8]}" if dirty else "")

    def stale(self, sc: dict, fingerprint: str | None) -> bool:
        run = sc.get("last_run")
        return bool(run and fingerprint and run.get("fingerprint") and run["fingerprint"] != fingerprint)

    def reap(self) -> list[str]:
        """Return the scenarios of a dead run to the queue and kill what that run left behind."""
        recovered = []
        for sid, sc in self.state["scenarios"].items():
            running = sc.get("running")
            if not running or pid_alive(running.get("pid")):
                continue
            browser_pid = read_pids(self.root / running["dir"]).get("browser") if running.get("dir") else None
            killed = [kill_group(running.get("node_pid"), r"node"), kill_group(browser_pid, r"chrom|firefox|webkit")]
            sc["running"] = None
            recovered.append(sid)
            self.append_log({"type": "recovered", "scenario": sid, "run": running.get("run"),
                             "killed_leftovers": any(killed)})
        return recovered


# --- validation -------------------------------------------------------------------------------


def parse_viewports(values: list[str]) -> dict:
    viewports = {}
    for value in values:
        match = re.fullmatch(r"([\w-]+)=(\d+)x(\d+)(:mobile)?", value)
        if not match:
            raise Refused(f"viewport {value!r}: expected NAME=WIDTHxHEIGHT or NAME=WIDTHxHEIGHT:mobile")
        viewports[match.group(1)] = {"width": int(match.group(2)), "height": int(match.group(3)),
                                     "mobile": bool(match.group(4))}
    return viewports


def scenario_viewports(config: dict, sc: dict) -> list[str]:
    """The scenario's own viewports, or the defaults of the current settings: all of them for a visual
    scenario, the primary one for a functional one."""
    names = list(config["viewports"])
    return sc.get("viewports") or (names if sc["kind"] != "functional" else names[:1])


def check_id(value, what: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise Refused(f"{what} {value!r}: use letters, digits, '-', '_' or '.', starting with a letter")
    return value


def validate(t: Testing) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    s = t.state
    for key in ("config", "revision", "scenarios", "findings", "assignments", "runs"):
        if key not in s:
            errors.append(f"testing.json: missing {key}")
    if errors:
        return errors, warnings
    viewports = s["config"].get("viewports", {})
    harness = t.root / "harness.mjs"
    if not harness.exists():
        errors.append("harness.mjs missing; run the harness command")
    elif HARNESS.exists() and file_hash(harness) != file_hash(HARNESS):
        warnings.append("harness.mjs differs from the tool's harness; run the harness command to update it")
    for sid, sc in s["scenarios"].items():
        if sc.get("kind") not in KINDS:
            errors.append(f"scenario {sid}: invalid kind {sc.get('kind')!r}")
        if sc.get("priority") not in PRIORITIES:
            errors.append(f"scenario {sid}: invalid priority {sc.get('priority')!r}")
        if sc.get("outcome") not in OUTCOMES:
            errors.append(f"scenario {sid}: invalid outcome {sc.get('outcome')!r}")
        if sc.get("outcome") in ("blocked", "unverified", "flaky") and not sc.get("reason"):
            errors.append(f"scenario {sid}: {sc['outcome']} without a reason")
        for name in sc.get("viewports") or []:
            if name not in viewports:
                errors.append(f"scenario {sid}: unknown viewport {name}")
        for fid in sc.get("findings", []):
            if fid not in s["findings"]:
                errors.append(f"scenario {sid}: unknown finding {fid}")
        if sc.get("outcome") == "failed" and not sc.get("findings"):
            warnings.append(f"scenario {sid}: failed without a finding")
        if sc.get("kind") != "functional" and sc.get("outcome") == "passed" and not sc.get("shots"):
            warnings.append(f"scenario {sid}: a visual scenario without screenshots; call shot() in its script")
        for key, shot in sc.get("shots", {}).items():
            if shot.get("judgment") not in JUDGMENTS:
                errors.append(f"scenario {sid}: shot {key} has an invalid judgment")
            elif shot["judgment"] == "issue" and not shot.get("finding"):
                warnings.append(f"scenario {sid}: shot {key} judged as an issue without a finding")
            if not (t.root / shot.get("path", "")).is_file():
                errors.append(f"scenario {sid}: shot {key} file missing")
    for fid, f in s["findings"].items():
        if not (t.findings_dir / f"{fid}.md").exists():
            errors.append(f"finding {fid}: missing findings/{fid}.md")
        if f.get("status") not in FINDING_STATUSES:
            errors.append(f"finding {fid}: invalid status {f.get('status')!r}")
        if f.get("kind") not in FINDING_KINDS:
            errors.append(f"finding {fid}: invalid kind {f.get('kind')!r}")
        for sid in f.get("scenarios", []):
            if sid not in s["scenarios"]:
                errors.append(f"finding {fid}: unknown scenario {sid}")
        if f.get("duplicate_of") and f["duplicate_of"] not in s["findings"]:
            errors.append(f"finding {fid}: duplicate of unknown {f['duplicate_of']}")
    for owner, a in s["assignments"].items():
        if a.get("task") not in TASKS:
            errors.append(f"assignment {owner}: invalid task {a.get('task')!r}")
    for n, record in enumerate(t.log(), 1):
        if "at" not in record or "type" not in record:
            errors.append(f"log.jsonl record {n}: missing at or type")
    return errors, warnings


# --- commands ---------------------------------------------------------------------------------


def check_limits(config: dict) -> None:
    if config.get("max_browsers", 1) < 1:
        raise Refused("max_browsers must be at least 1")
    if config.get("timeout", 1) < 1:
        raise Refused("timeout must be at least 1 second")
    if not 0 <= config.get("diff_threshold", 0) <= 1:
        raise Refused("diff_threshold is a share of the pixels, from 0 to 1")
    if not 0 <= config.get("diff_tolerance", 0) <= 255:
        raise Refused("diff_tolerance is a per-channel difference, from 0 to 255")


def cmd_init(t: Testing, args) -> None:
    if t.state_path.exists():
        raise Refused("testing.json already exists; continue with status")
    check_limits({"max_browsers": args.max_browsers, "timeout": args.timeout})
    t.root.mkdir(parents=True, exist_ok=True)
    for folder in ("scenarios", "results", "findings"):
        (t.root / folder).mkdir(exist_ok=True)
    repo = None if args.no_repo else git(args.repo, "rev-parse", "--show-toplevel")
    if not repo and not args.no_repo:
        raise Refused(f"{args.repo or 'the current directory'} is not inside a git repository; "
                      "pass --repo DIR, or --no-repo for a project without git")
    revision = {"repo": repo, "head": args.head, "head_sha": git(repo, "rev-parse", "--verify", "--quiet", args.head),
                "base": args.base, "working_tree": args.working_tree}
    if args.base:
        revision["base_sha"] = git(repo, "rev-parse", "--verify", "--quiet", args.base)
    viewports = parse_viewports(args.viewport) if args.viewport else dict(DEFAULT_VIEWPORTS)
    t.state = {
        "schema_version": SCHEMA_VERSION, "scope": args.scope, "created_at": now(), "updated_at": now(),
        "revision": revision,
        "config": {"url": args.url, "max_browsers": args.max_browsers, "timeout": args.timeout,
                   "viewports": viewports, "playwright_from": [str(Path(p).resolve()) for p in args.playwright],
                   "browser": args.browser, "diff_threshold": DEFAULT_DIFF_THRESHOLD,
                   "diff_tolerance": DEFAULT_DIFF_TOLERANCE},
        "scenarios": {}, "findings": {}, "assignments": {}, "runs": [],
    }
    shutil.copy2(HARNESS, t.root / "harness.mjs")
    revision["fingerprint"] = t.fingerprint()
    t.save()
    t.append_log({"type": "init", "scope": args.scope, "url": args.url, "revision": revision})
    node = shutil.which("node")
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() if node else None
    print(f"initialized {t.root} for {args.scope} at {revision['fingerprint'] or 'no git'}")
    print(f"node {version}" if version else "warning: node not found; scenario scripts need Node 18+")
    if not repo:
        print("warning: no repository; results cannot be matched to a code state")


def cmd_config(t: Testing, args) -> None:
    c = t.state["config"]
    changes = {}
    for key, value in (("url", args.url), ("max_browsers", args.max_browsers), ("timeout", args.timeout),
                       ("browser", args.browser), ("diff_threshold", args.diff_threshold),
                       ("diff_tolerance", args.diff_tolerance)):
        if value is not None:
            changes[key] = value
    if args.viewport:
        changes["viewports"] = parse_viewports(args.viewport)
    if args.playwright:
        changes["playwright_from"] = [str(Path(p).resolve()) for p in args.playwright]
    if not changes:
        print(json.dumps(c, indent=2, ensure_ascii=False))
        return
    check_limits(changes)
    if "viewports" in changes:
        used = sorted({v for sc in t.state["scenarios"].values() for v in sc.get("viewports") or []
                       if v not in changes["viewports"]})
        if used:
            raise Refused(f"scenarios still name the viewports {', '.join(used)}; change them first")
    c.update(changes)
    t.save()
    t.append_log({"type": "config", **changes})
    print("config: " + ", ".join(f"{k}={v}" for k, v in changes.items()))


def cmd_harness(t: Testing, args) -> None:
    shutil.copy2(HARNESS, t.root / "harness.mjs")
    t.append_log({"type": "harness", "hash": file_hash(HARNESS)})
    print(f"harness.mjs updated ({file_hash(HARNESS)})")


def upsert_scenario(t: Testing, sid: str, fields: dict) -> str:
    check_id(sid, "scenario")
    existing = t.state["scenarios"].get(sid)
    if existing is None and not (fields.get("title") and fields.get("group")):
        raise Refused(f"new scenario {sid} needs a title and a group")
    if fields.get("group") is not None:
        check_id(fields["group"], "group")
    if fields.get("kind") not in (None, *KINDS):
        raise Refused(f"scenario {sid}: kind must be one of {', '.join(KINDS)}")
    if fields.get("priority") not in (None, *PRIORITIES):
        raise Refused(f"scenario {sid}: priority must be one of {', '.join(PRIORITIES)}")
    viewports = t.state["config"]["viewports"]
    for name in fields.get("viewports") or []:
        if name not in viewports:
            raise Refused(f"scenario {sid}: unknown viewport {name} (configured: {', '.join(viewports)})")
    sc = existing or {"title": None, "group": None, "kind": "functional", "priority": "medium", "role": None,
                      "viewports": None, "data": None, "script": f"scenarios/{sid}.mjs", "ready_hash": None,
                      "outcome": "pending", "reason": None, "last_run": None, "triage": None, "findings": [],
                      "shots": {}, "running": None}
    for key in ("title", "group", "kind", "priority", "role", "viewports", "data", "script"):
        if fields.get(key) is not None:
            sc[key] = fields[key]
    t.state["scenarios"][sid] = sc
    return "updated" if existing else "added"


def cmd_scenario(t: Testing, args) -> None:
    fields = {"title": args.title, "group": args.group, "kind": args.kind, "priority": args.priority,
              "role": args.role, "viewports": args.viewports, "data": args.data, "script": args.script}
    action = upsert_scenario(t, args.id, fields)
    t.save()
    t.append_log({"type": "scenario", "scenario": args.id, "action": action,
                  **{k: v for k, v in fields.items() if v is not None}})
    sc = t.scenario(args.id)
    names = scenario_viewports(t.state["config"], sc)
    print(f"{args.id} {action}: {sc['group']} {sc['kind']} viewports={','.join(names)}"
          f"{'' if sc['viewports'] else ' (default)'} script={sc['script']}")


def cmd_scenarios(t: Testing, args) -> None:
    data = read_json(args.file)
    if isinstance(data, dict):
        data = data.get("scenarios")
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise Refused("expected a JSON list of scenario objects (or {\"scenarios\": [...]})")
    before = json.loads(json.dumps(t.state["scenarios"]))
    try:
        actions = [(item.get("id"), upsert_scenario(t, item.get("id"), item)) for item in data]
    except Refused:
        t.state["scenarios"] = before
        raise
    t.save()
    t.append_log({"type": "scenarios", "file": str(args.file), "scenarios": [sid for sid, _ in actions]})
    groups = sorted({t.scenario(sid)["group"] for sid, _ in actions}, key=natural)
    print(f"{sum(a == 'added' for _, a in actions)} added, {sum(a == 'updated' for _, a in actions)} updated; "
          f"groups: {', '.join(groups)}")


def cmd_ready(t: Testing, args) -> None:
    for sid in args.ids:
        sc = t.scenario(sid)
        current = file_hash(t.script_path(sc))
        if current is None:
            raise Refused(f"{sid}: script {sc['script']} does not exist")
        run = sc.get("last_run")
        if not run or run.get("script_hash") != current or run.get("status") not in ("passed", "failed"):
            raise Refused(f"{sid}: run the current script first; a ready script has a completed run "
                          f"(passed or failed, not crashed or timed out)")
    for sid in args.ids:
        sc = t.scenario(sid)
        sc["ready_hash"] = sc["last_run"]["script_hash"]
    t.save()
    t.append_log({"type": "ready", "scenarios": args.ids})
    print(f"ready: {' '.join(args.ids)}")


# --- running ----------------------------------------------------------------------------------


def select_for_run(t: Testing, args, fingerprint: str | None) -> list[str]:
    scenarios = t.state["scenarios"]
    if args.ids:
        for sid in args.ids:
            t.scenario(sid)
        chosen = sorted(dict.fromkeys(args.ids), key=natural)
    else:
        chosen = t.ids(args.group)
        if args.todo:
            chosen = [sid for sid in chosen if t.script_status(scenarios[sid]) == "ready"
                      and (scenarios[sid]["outcome"] == "pending" or t.stale(scenarios[sid], fingerprint))]
        elif args.failed:
            chosen = [sid for sid in chosen if scenarios[sid]["outcome"] in ("failing", "failed", "flaky")]
        elif args.all:
            chosen = [sid for sid in chosen if t.script_status(scenarios[sid]) == "ready"]
        elif not args.group:
            raise Refused("name scenarios or use --group, --todo, --failed or --all")
    missing = [sid for sid in chosen if t.script_status(scenarios[sid]) == "pending"]
    if missing:
        raise Refused(f"no script yet: {' '.join(missing)}")
    unknown = [sid for sid in chosen if any(v not in t.state["config"]["viewports"] for v in scenarios[sid].get("viewports") or [])]
    if unknown:
        raise Refused(f"unknown viewports in {' '.join(unknown)}; see validate")
    busy = [sid for sid in chosen if scenarios[sid].get("running")]
    if busy:
        raise Refused(f"already running: {' '.join(busy)}")
    return chosen


def current_shots(sc: dict) -> dict:
    run = (sc.get("last_run") or {}).get("run")
    return {k: x for k, x in sc.get("shots", {}).items() if run and x.get("run") == run}


def verdict(sc: dict) -> str:
    """The outcome including the look: a passed visual scenario fails with a screenshot judged as an
    issue and stays pending while its screenshots wait for a judgment."""
    if sc["outcome"] != "passed" or sc["kind"] == "functional":
        return sc["outcome"]
    judgments = [x["judgment"] for x in current_shots(sc).values()]
    if "issue" in judgments:
        return "failed"
    return "pending" if "pending" in judgments else "passed"


def baselines(t: Testing, sc: dict) -> dict:
    """The last judged screenshot per key, also when newer ones wait for a judgment."""
    return {key: str(t.root / shot["judged"]["path"]) for key, shot in sc.get("shots", {}).items() if shot.get("judged")}


class Runner:
    def __init__(self, t: Testing, run_id: str, fingerprint: str | None, repeat: int):
        self.t = t
        self.run_id = run_id
        self.fingerprint = fingerprint
        self.repeat = repeat
        self.stop = threading.Event()
        self.procs: dict[str, subprocess.Popen] = {}
        self.print_lock = threading.Lock()
        self.summary: dict[str, list[str]] = {}

    def say(self, line: str) -> None:
        with self.print_lock:
            print(line, flush=True)

    def claim(self, sid: str) -> bool:
        """Wait for a free browser slot, counted across all processes working on this folder."""
        while not self.stop.is_set():
            with self.t.locked() as s:
                self.t.reap()
                running = sum(1 for sc in s["scenarios"].values() if sc.get("running"))
                if running < s["config"]["max_browsers"]:
                    s["scenarios"][sid]["running"] = {"pid": os.getpid(), "run": self.run_id, "at": now(),
                                                      "node_pid": None, "dir": None}
                    self.t.save()
                    return True
            time.sleep(1)
        return False

    def group(self, sids: list[str]) -> None:
        for sid in sids:
            if self.stop.is_set():
                return
            attempts = []
            for n in range(1, self.repeat + 1):
                if self.stop.is_set() or not self.claim(sid):
                    break
                attempts.append(self.attempt(sid, n))
                self.release(sid)
            if attempts:
                self.record(sid, attempts)

    def release(self, sid: str) -> None:
        """Free the slot between attempts, so that a repeated scenario does not wait for itself."""
        with self.t.locked() as s:
            s["scenarios"][sid]["running"] = None
            self.t.save()

    def attempt(self, sid: str, n: int) -> dict:
        with self.t.locked() as s:
            sc = s["scenarios"][sid]
            config = dict(s["config"])
            script = self.t.script_path(sc)
            script_hash = file_hash(script)
            base = baselines(self.t, sc)
            viewports = [{"name": v, **config["viewports"][v]} for v in scenario_viewports(config, sc)]
        name = self.run_id if self.repeat == 1 else f"{self.run_id}.{n}"
        out = self.t.results_dir / sid / name
        out.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, BT_OUT=str(out), BT_SCENARIO=sid, BT_BASE_URL=config["url"] or "",
                   BT_VIEWPORTS=json.dumps(viewports), BT_BASELINES=json.dumps(base),
                   BT_DIFF_TOLERANCE=str(config["diff_tolerance"]), BT_BROWSER=config["browser"],
                   BT_PLAYWRIGHT_FROM=os.pathsep.join(config["playwright_from"]))
        started = time.time()
        status = None
        with (out / "output.log").open("w", encoding="utf-8") as log:
            try:
                proc = subprocess.Popen(["node", str(script)], cwd=self.t.root, env=env, stdout=log,
                                        stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
            except OSError as e:
                log.write(f"cannot start node: {e}\n")
                proc = None
                status = "crashed"
            if proc:
                self.procs[sid] = proc
                with self.t.locked() as s:
                    s["scenarios"][sid]["running"].update(node_pid=proc.pid, dir=str(out.relative_to(self.t.root)))
                    self.t.save()
                try:
                    proc.wait(timeout=config["timeout"])
                except subprocess.TimeoutExpired:
                    status = "timeout"
                finally:
                    self.procs.pop(sid, None)
        cleaned = self.cleanup(proc, out)
        result = None
        if (out / "result.json").is_file():
            try:
                result = read_json(out / "result.json")
            except Refused:
                result = None
        if status is None:
            status = result["status"] if result and result.get("status") in ("passed", "failed") else "crashed"
        if self.stop.is_set() and status != "passed":
            status = "interrupted"
        return {"status": status, "dir": str(out.relative_to(self.t.root)), "script_hash": script_hash,
                "duration": round(time.time() - started, 1), "result": result, "cleaned": cleaned}

    def cleanup(self, proc, out: Path) -> list[str]:
        """Kill the scenario's node process group and its browser if either is still alive."""
        cleaned = []
        pids = read_pids(out)
        if proc and proc.poll() is None:
            if os.name == "posix":
                kill_group(proc.pid, r"node")
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            cleaned.append("node")
        if kill_group(pids.get("browser"), r"chrom|firefox|webkit"):
            cleaned.append("browser")
        return cleaned

    def record(self, sid: str, attempts: list[dict]) -> None:
        last = attempts[-1]
        result = last.pop("result") or {}
        statuses = [a["status"] for a in attempts]
        with self.t.locked() as s:
            sc = s["scenarios"][sid]
            sc["running"] = None
            if "interrupted" in statuses:
                self.t.save()
                self.t.append_log({"type": "run", "run": self.run_id, "scenario": sid, "status": "interrupted"})
                self.say(f"{sid:<10} interrupted")
                return
            failed_checks = [c["name"] for c in result.get("checks", []) + result.get("automatic", []) if not c["ok"]]
            run = {"run": self.run_id, "at": now(), "status": last["status"], "dir": last["dir"],
                   "duration": last["duration"], "fingerprint": self.fingerprint, "script_hash": last["script_hash"],
                   "failed_checks": failed_checks, "error": (result.get("error") or {}).get("message"),
                   "attempts": statuses if len(statuses) > 1 else None, "cleaned": last["cleaned"] or None}
            sc["last_run"] = run
            all_passed = all(x == "passed" for x in statuses)
            if all_passed:
                sc["outcome"], sc["reason"], sc["triage"] = "passed", None, None
            else:
                sc["outcome"], sc["reason"], sc["triage"] = "failing", None, None
            changed = self.merge_shots(sc, result, last["dir"], s["config"]["diff_threshold"])
            self.t.save()
            self.t.append_log({"type": "run", "run": self.run_id, "scenario": sid, "status": run["status"],
                               "attempts": run["attempts"], "dir": run["dir"], "fingerprint": self.fingerprint,
                               "failed_checks": failed_checks, "cleaned": run["cleaned"]})
        self.summary.setdefault(sc["outcome"], []).append(sid)
        line = f"{sid:<10} {run['status'].upper() if not all_passed else 'passed':<8} {run['duration']:>6}s"
        if len(statuses) > 1:
            line += f"  {statuses.count('passed')}/{len(statuses)} passed"
        checks = result.get("checks", [])
        if checks:
            line += f"  checks {sum(c['ok'] for c in checks)}/{len(checks)}"
        if result.get("shots"):
            line += f"  shots {len(result['shots'])} ({changed} to judge)"
        if failed_checks:
            line += f"  failed: {'; '.join(failed_checks)[:120]}"
        elif run["error"]:
            line += f"  error: {run['error'][:120]}"
        if run["status"] in ("crashed", "timeout"):
            line += f"  see {run['dir']}/output.log"
        if run["cleaned"]:
            line += f"  killed {', '.join(run['cleaned'])}"
        self.say(line)

    def merge_shots(self, sc: dict, result: dict, run_dir: str, threshold: float) -> int:
        """Keep the latest shot per key with its last judged one; within the threshold it inherits the judgment."""
        to_judge = 0
        for shot in result.get("shots", []):
            key = shot.get("key")
            if not key:
                continue
            previous = sc["shots"].get(key) or {}
            diff = shot.get("diff")
            entry = {"path": f"{run_dir}/{shot['path']}", "run": self.run_id, "size": shot.get("size"),
                     "layout": shot.get("layout") or [], "judgment": "pending", "diff": None,
                     "diff_pixels": None, "diff_image": None, "judged": previous.get("judged"),
                     "inherited": False, "finding": None, "note": None}
            if diff is not None:
                entry["diff"] = round(diff.get("ratio", 1), 6)
                entry["diff_pixels"] = diff.get("pixels")
                if diff.get("size_changed"):
                    entry["size_changed"] = diff["size_changed"]
                if diff.get("image"):
                    entry["diff_image"] = f"{run_dir}/{diff['image']}"
            judged = entry["judged"]
            if judged and diff is not None and diff.get("ratio", 1) <= threshold:
                entry.update(judgment=judged["judgment"], finding=judged.get("finding"), note=judged.get("note"),
                             inherited=True)
            else:
                to_judge += 1
            sc["shots"][key] = entry
        return to_judge

    def interrupt(self) -> None:
        self.stop.set()
        for proc in list(self.procs.values()):
            if proc.poll() is None:
                if os.name == "posix":
                    kill_group(proc.pid, r"node")
                if proc.poll() is None:
                    proc.kill()


def cmd_run(t: Testing, args) -> None:
    if args.repeat < 1:
        raise Refused("--repeat must be at least 1")
    if not shutil.which("node"):
        raise Refused("node not found on PATH")
    with t.locked() as s:
        t.reap()
        fingerprint = t.fingerprint()
        chosen = select_for_run(t, args, fingerprint)
        if not chosen:
            t.save()
            print("nothing to run")
            return
        run_id = f"r{len(s['runs']) + 1:03d}"
        s["runs"].append({"id": run_id, "at": now(), "scenarios": chosen, "fingerprint": fingerprint,
                          "repeat": args.repeat})
        t.save()
        t.append_log({"type": "run_started", "run": run_id, "scenarios": chosen, "fingerprint": fingerprint})
        groups: dict[str, list[str]] = {}
        for sid in chosen:
            groups.setdefault(s["scenarios"][sid]["group"], []).append(sid)
        max_browsers = s["config"]["max_browsers"]
    runner = Runner(t, run_id, fingerprint, args.repeat)
    print(f"run {run_id}: {len(chosen)} scenario(s) in {len(groups)} group(s), at most {max_browsers} browser(s), "
          f"code {fingerprint or 'unknown'}; scenarios of one group run in order", flush=True)
    pool = ThreadPoolExecutor(max_workers=max(1, min(max_browsers, len(groups))))
    try:
        futures = [pool.submit(runner.group, sids) for sids in groups.values()]
        while any(not f.done() for f in futures):
            time.sleep(0.2)
        for f in futures:
            f.result()
    except KeyboardInterrupt:
        runner.interrupt()
        pool.shutdown(wait=True)
        with t.locked() as s:
            for sid in chosen:
                if (s["scenarios"][sid].get("running") or {}).get("run") == run_id:
                    s["scenarios"][sid]["running"] = None
            t.save()
        t.append_log({"type": "run_interrupted", "run": run_id})
        raise Refused(f"run {run_id} interrupted; unfinished scenarios keep their previous outcome")
    pool.shutdown()
    with t.locked() as s:
        triage = [sid for sid in chosen if s["scenarios"][sid]["outcome"] == "failing"]
        judge = sum(1 for sid in chosen for shot in s["scenarios"][sid]["shots"].values()
                    if shot["run"] == run_id and shot["judgment"] == "pending")
    counts = ", ".join(f"{len(v)} {k}" for k, v in sorted(runner.summary.items()))
    print(f"summary: {counts or 'nothing recorded'}" + (f"; triage: {' '.join(triage)}" if triage else "")
          + (f"; shots to judge: {judge}" if judge else ""))


# --- results ----------------------------------------------------------------------------------


def cmd_result(t: Testing, args) -> None:
    sc = t.scenario(args.id)
    run = sc.get("last_run")
    print(f"{args.id} {sc['title']} [{sc['group']}, {sc['kind']}] outcome={sc['outcome']} script={t.script_status(sc)}")
    if not run:
        print("  not run yet")
        return
    folder = t.root / run["dir"]
    print(f"  last run {run['run']} {run['status']} {run['duration']}s code={run.get('fingerprint')} dir={folder}")
    if run.get("attempts"):
        print(f"  attempts: {' '.join(run['attempts'])}")
    result = read_json(folder / "result.json") if (folder / "result.json").is_file() else {}
    for step in result.get("steps", []):
        if step.get("status") != "ok":
            print(f"  step {step['name']}: {step['status']} {step.get('error') or ''}".rstrip())
    for c in result.get("checks", []) + result.get("automatic", []):
        if not c["ok"]:
            print(f"  failed check: {c['name']}" + (f" ({c['detail']})" if c.get("detail") else "")
                  + (f" in step {c['step']}" if c.get("step") else ""))
    if result.get("error"):
        print(f"  error: {result['error']['message']}" + (f" in step {result['error']['step']}" if result["error"].get("step") else ""))
    for key, label in (("page_errors", "page error"), ("console", "console error")):
        for item in result.get(key, [])[:5]:
            print(f"  {label}: {item['text'][:200]}")
    for item in [h for h in result.get("http", []) if h["status"] >= 500][:5]:
        print(f"  http {item['status']} {item['method']} {item['url']}")
    for item in result.get("request_failed", [])[:3]:
        print(f"  request failed: {item['failure']} {item['url']}")
    for note in result.get("notes", []):
        print(f"  note: {note}")
    if result.get("failure_shot"):
        print(f"  failure screenshot: {folder / result['failure_shot']} at {result.get('failure_url')}")
    if not result:
        print(f"  no result.json; see {folder / 'output.log'}")
    if sc.get("triage"):
        print(f"  triage: {sc['triage']['cause']} {sc['triage'].get('note') or ''}".rstrip())


def cmd_triage(t: Testing, args) -> None:
    sc = t.scenario(args.id)
    if sc["outcome"] not in ("failing", "failed", "flaky", "blocked"):
        raise Refused(f"{args.id} is {sc['outcome']}; triage is for a failing run")
    if args.cause in ("env", "flaky") and not args.note:
        raise Refused(f"triage {args.cause} needs --note with the evidence")
    if args.finding:
        f = t.finding(args.finding)
        if args.id not in f["scenarios"]:
            f["scenarios"].append(args.id)
        if args.finding not in sc["findings"]:
            sc["findings"].append(args.finding)
    sc["triage"] = {"cause": args.cause, "note": args.note, "run": (sc.get("last_run") or {}).get("run")}
    if args.cause == "app":
        sc["outcome"], sc["reason"] = "failed", args.note
    elif args.cause == "env":
        sc["outcome"], sc["reason"] = "blocked", args.note
    elif args.cause == "flaky":
        sc["outcome"], sc["reason"] = "flaky", args.note
    else:
        sc["outcome"], sc["reason"], sc["ready_hash"] = "pending", None, None
    t.save()
    t.append_log({"type": "triage", "scenario": args.id, "cause": args.cause, "note": args.note,
                  "finding": args.finding})
    hint = {"app": "record the finding if not done", "env": "fix the environment and run again",
            "flaky": "keep the finding or note with the conditions", "script": "fix the script, run it and mark it ready"}
    print(f"{args.id}: {sc['outcome']} ({args.cause}); {hint[args.cause]}")


def cmd_set(t: Testing, args) -> None:
    sc = t.scenario(args.id)
    sc["outcome"], sc["reason"] = args.outcome, args.reason
    t.save()
    t.append_log({"type": "set", "scenario": args.id, "outcome": args.outcome, "reason": args.reason})
    print(f"{args.id}: {args.outcome}")


def shot_line(t: Testing, sid: str, key: str, shot: dict) -> str:
    line = f"{sid:<8} {key:<28} {shot['judgment']:<7} {t.root / shot['path']}"
    if shot.get("inherited"):
        line += f" (unchanged since judged, {shot.get('diff_pixels') or 0} px differ)"
    elif shot.get("size_changed"):
        line += f" (size changed {shot['size_changed']} against the one judged {shot['judged']['judgment']}"
    elif shot.get("diff") is not None:
        line += f" ({shot.get('diff_pixels', '?')} px = {shot['diff']:.3%} differ from the one judged {shot['judged']['judgment']}"
        line += f", diff image {t.root / shot['diff_image']})" if shot.get("diff_image") else ")"
    for item in shot.get("layout", []):
        line += f"\n{'':<10}layout: {item['kind']} {item.get('detail', '')}"
        if item.get("elements"):
            line += f": {'; '.join(item['elements'])[:200]}"
    if shot.get("note"):
        line += f"\n{'':<10}note: {shot['note']}"
    return line


def cmd_shots(t: Testing, args) -> None:
    ids = args.ids or t.ids(args.group)
    lines = []
    for sid in ids:
        sc = t.scenario(sid)
        current = (sc.get("last_run") or {}).get("run")
        for key in sorted(sc["shots"], key=natural):
            shot = sc["shots"][key]
            if args.pending and shot["judgment"] != "pending":
                continue
            line = shot_line(t, sid, key, shot)
            if current and shot["run"] != current:
                line += f"\n{'':<10}from run {shot['run']}, not produced by the last run {current}"
            lines.append(line)
    print("\n".join(lines) if lines else "no screenshots")


def cmd_judge(t: Testing, args) -> None:
    sc = t.scenario(args.id)
    keys = args.shots or [k for k, s in sc["shots"].items() if s["judgment"] == "pending"]
    if not keys:
        raise Refused(f"{args.id}: no pending screenshots; name them with --shots")
    for key in keys:
        if key not in sc["shots"]:
            raise Refused(f"{args.id}: unknown screenshot {key} (known: {', '.join(sc['shots'])})")
    if args.judgment == "issue" and not (args.finding or args.note):
        raise Refused("an issue needs --finding or --note")
    if args.finding:
        f = t.finding(args.finding)
        if args.id not in f["scenarios"]:
            f["scenarios"].append(args.id)
        if args.finding not in sc["findings"]:
            sc["findings"].append(args.finding)
    for key in keys:
        shot = sc["shots"][key]
        shot.update(judgment=args.judgment, finding=args.finding, note=args.note, inherited=False,
                    judged={"path": shot["path"], "run": shot["run"], "judgment": args.judgment,
                            "finding": args.finding, "note": args.note})
    t.save()
    t.append_log({"type": "judge", "scenario": args.id, "shots": keys, "judgment": args.judgment,
                  "finding": args.finding, "note": args.note})
    print(f"{args.id}: {len(keys)} screenshot(s) {args.judgment}")


def cmd_finding(t: Testing, args) -> None:
    check_id(args.id, "finding")
    if args.id in t.state["findings"]:
        raise Refused(f"finding {args.id} exists; IDs are stable, use resolve to change it")
    for sid in args.scenarios:
        t.scenario(sid)
    if not (t.findings_dir / f"{args.id}.md").exists():
        print(f"warning: write findings/{args.id}.md in the results format", file=sys.stderr)
    t.state["findings"][args.id] = {"title": args.title, "kind": args.kind, "severity": args.severity,
                                    "scenarios": list(args.scenarios), "status": "open", "history": []}
    for sid in args.scenarios:
        sc = t.scenario(sid)
        if args.id not in sc["findings"]:
            sc["findings"].append(args.id)
    t.save()
    t.append_log({"type": "finding", "finding": args.id, "kind": args.kind, "severity": args.severity,
                  "scenarios": args.scenarios, "title": args.title})
    print(f"{args.id}: {args.kind} {args.severity or ''} {args.title}".replace("  ", " "))


def cmd_resolve(t: Testing, args) -> None:
    f = t.finding(args.id)
    if args.status == "duplicate":
        if not args.duplicate_of:
            raise Refused("duplicate needs --duplicate-of")
        t.finding(args.duplicate_of)
        f["duplicate_of"] = args.duplicate_of
    f["history"].append({"at": now(), "from": f["status"], "to": args.status, "reason": args.reason})
    f["status"] = args.status
    t.save()
    t.append_log({"type": "resolve", "finding": args.id, "status": args.status, "reason": args.reason})
    print(f"{args.id}: {args.status}")


def cmd_findings(t: Testing, args) -> None:
    order = {s: i for i, s in enumerate(SEVERITIES)}
    lines = []
    for fid, f in sorted(t.state["findings"].items(), key=lambda x: (order.get(x[1]["severity"], 9), natural(x[0]))):
        if not args.all and f["status"] in ("verified", "rejected", "duplicate"):
            continue
        lines.append(f"{fid:<8} {f['status']:<17} {f['kind']:<17} {f['severity'] or '-':<8} "
                     f"{' '.join(f['scenarios'])}: {f['title']}")
    print("\n".join(lines) if lines else "no findings")


def cmd_assign(t: Testing, args) -> None:
    check_id(args.owner, "owner")
    if t.state["assignments"].get(args.owner, {}).get("status") == "active":
        raise Refused(f"{args.owner} already has an active assignment; release it first")
    ids = list(args.ids) + (t.ids(args.group) if args.group else [])
    if not ids and args.task != "explore":
        raise Refused("name scenarios or a --group")
    for sid in ids:
        t.scenario(sid)
    for owner, a in t.state["assignments"].items():
        if a["status"] == "active" and a["task"] == args.task and set(a["scenarios"]) & set(ids):
            raise Refused(f"{owner} already has {args.task} for {' '.join(sorted(set(a['scenarios']) & set(ids)))}")
    t.state["assignments"][args.owner] = {"task": args.task, "scenarios": ids, "group": args.group,
                                          "note": args.note, "at": now(), "status": "active"}
    t.save()
    t.append_log({"type": "assign", "owner": args.owner, "task": args.task, "scenarios": ids, "note": args.note})
    print(f"{args.owner}: {args.task} {' '.join(ids)}".rstrip())


def cmd_release(t: Testing, args) -> None:
    a = t.state["assignments"].get(args.owner)
    if not a or a["status"] != "active":
        raise Refused(f"{args.owner} has no active assignment")
    a["status"] = "lost" if args.lost else "done"
    a["released_at"] = now()
    t.save()
    t.append_log({"type": "release", "owner": args.owner, "status": a["status"]})
    print(f"{args.owner}: {a['status']}" + ("; brief a new run for what it left open (see next)" if args.lost else ""))


def grouped(t: Testing, ids: list[str]) -> str:
    by_group: dict[str, list[str]] = {}
    for sid in ids:
        by_group.setdefault(t.state["scenarios"][sid]["group"], []).append(sid)
    return "; ".join(f"{g}: {' '.join(v)}" for g, v in sorted(by_group.items(), key=lambda x: natural(x[0])))


def cmd_next(t: Testing, args) -> None:
    if t.reap():
        t.save()
    s = t.state
    fingerprint = t.fingerprint()
    ids = t.ids()
    sc = s["scenarios"]
    active = {sid: owner for owner, a in s["assignments"].items() if a["status"] == "active" for sid in a["scenarios"]}
    scripted = [i for i in ids if sc[i]["outcome"] != "unverified"]
    sections = [
        ("scripts to write", [i for i in scripted if t.script_status(sc[i]) == "pending"]),
        ("scripts to finish (run and mark ready)", [i for i in scripted if t.script_status(sc[i]) == "written"]),
        ("to run", [i for i in ids if t.script_status(sc[i]) == "ready" and sc[i]["outcome"] == "pending"]),
        ("to run again, code changed since their run", [i for i in ids if t.script_status(sc[i]) == "ready"
                                                         and sc[i]["outcome"] != "pending" and t.stale(sc[i], fingerprint)]),
        ("to triage", [i for i in ids if sc[i]["outcome"] == "failing"]),
        ("screenshots to judge", [i for i in ids if any(x["judgment"] == "pending" for x in sc[i]["shots"].values())]),
    ]
    fixed = [fid for fid, f in s["findings"].items() if f["status"] == "fixed" and f["scenarios"]
             and all(verdict(sc[x]) == "passed" and not t.stale(sc[x], fingerprint) for x in f["scenarios"])]
    printed = False
    for title, items in sections:
        if items:
            printed = True
            print(f"{title}: {grouped(t, items)}")
            taken = sorted({active[i] for i in items if i in active})
            if taken:
                print(f"  assigned: {', '.join(taken)}")
    if fixed:
        printed = True
        print(f"fixed findings whose scenarios pass now, verify them: {' '.join(fixed)}")
    running = [i for i in ids if sc[i].get("running")]
    if running:
        printed = True
        print(f"running: {' '.join(running)}")
    if not printed:
        print("nothing open: every scenario has a result and every screenshot a judgment")


def cmd_status(t: Testing, args) -> None:
    recovered = t.reap()
    if recovered:
        t.save()
    s = t.state
    c = s["config"]
    fingerprint = t.fingerprint()
    sc = s["scenarios"]
    ids = t.ids()
    rev = s["revision"]
    viewports = ", ".join(f"{k} {v['width']}x{v['height']}" + (" mobile" if v.get("mobile") else "")
                          for k, v in c["viewports"].items())
    print(f"scope {s['scope']} · {c['url']} · {c['browser']} · at most {c['max_browsers']} browser(s) · "
          f"viewports {viewports}")
    print(f"code now {fingerprint or 'unknown'}, at init {rev.get('fingerprint') or 'unknown'}")
    groups = sorted({x["group"] for x in sc.values()}, key=natural)
    print(f"scenarios {len(ids)} in {len(groups)} group(s): {', '.join(groups) or '-'}")
    scripts = [t.script_status(sc[i]) for i in ids]
    print("scripts: " + ", ".join(f"{scripts.count(k)} {k}" for k in ("pending", "written", "ready") if scripts.count(k)))
    outcomes = [verdict(sc[i]) for i in ids]
    print("outcomes: " + (", ".join(f"{outcomes.count(k)} {k}" for k in OUTCOMES if outcomes.count(k)) or "-"))
    shots = [x["judgment"] for i in ids for x in sc[i]["shots"].values()]
    if shots:
        print("screenshots: " + ", ".join(f"{shots.count(k)} {k}" for k in JUDGMENTS if shots.count(k)))
    stale = [i for i in ids if t.stale(sc[i], fingerprint)]
    if stale:
        print(f"results from another code state: {' '.join(stale)}")
    for i in ids:
        v = verdict(sc[i])
        if v in ("failing", "failed", "blocked", "unverified", "flaky"):
            detail = sc[i].get("reason") or "; ".join((sc[i].get("last_run") or {}).get("failed_checks") or []) \
                or (sc[i].get("last_run") or {}).get("error") or ""
            if v != sc[i]["outcome"]:
                detail = "screenshot judged as an issue: " + ", ".join(
                    k for k, x in current_shots(sc[i]).items() if x["judgment"] == "issue")
            print(f"  {i:<8} {v:<10} {detail[:140]}")
    running = [i for i in ids if sc[i].get("running")]
    if running:
        print(f"running: {' '.join(running)}")
    if recovered:
        print(f"recovered from a dead run: {' '.join(recovered)}")
    for owner, a in s["assignments"].items():
        if a["status"] == "active":
            print(f"assignment {owner}: {a['task']} {' '.join(a['scenarios'])} since {a['at']}".rstrip())
    statuses = [f["status"] for f in s["findings"].values()]
    if statuses:
        print("findings: " + ", ".join(f"{statuses.count(k)} {k}" for k in FINDING_STATUSES if statuses.count(k)))
    if s["runs"]:
        last = s["runs"][-1]
        print(f"runs {len(s['runs'])}, last {last['id']} at {last['at']} ({len(last['scenarios'])} scenario(s))")


def cmd_validate(t: Testing, args) -> None:
    errors, warnings = validate(t)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    print("valid" if not errors else f"{len(errors)} error(s)")
    if errors:
        raise SystemExit(1)


def parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def cmd_log(t: Testing, args) -> None:
    record = {"type": args.type}
    for field in args.fields:
        key, sep, value = field.partition("=")
        if not sep or not key:
            raise Refused(f"expected key=value, got {field!r}")
        record[key] = parse_value(value)
    missing = [k for k in LOG_REQUIRED[args.type] if k not in record]
    if missing:
        raise Refused(f"{args.type} needs {', '.join(missing)}")
    t.append_log(record)
    print(f"logged {args.type}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("testing_dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init")
    p.add_argument("--scope", required=True)
    p.add_argument("--url", required=True, help="base URL of the verified dev application")
    p.add_argument("--repo", help="the tested repository, the one of the current directory by default")
    p.add_argument("--no-repo", action="store_true", help="a project without git; no code state is recorded")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--base")
    p.add_argument("--working-tree", action="store_true")
    p.add_argument("--max-browsers", type=int, default=DEFAULT_MAX_BROWSERS)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="seconds per scenario run")
    p.add_argument("--viewport", nargs="+", default=[],
                   help="NAME=WIDTHxHEIGHT[:mobile], the first is the primary one")
    p.add_argument("--playwright", nargs="+", default=[], help="directories to resolve Playwright from")
    p.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    p = sub.add_parser("config")
    p.add_argument("--url")
    p.add_argument("--max-browsers", type=int)
    p.add_argument("--timeout", type=int)
    p.add_argument("--viewport", nargs="+")
    p.add_argument("--playwright", nargs="+")
    p.add_argument("--browser", choices=("chromium", "firefox", "webkit"))
    p.add_argument("--diff-threshold", type=float, help="share of changed pixels a screenshot may differ by")
    p.add_argument("--diff-tolerance", type=int, help="per-channel difference (0-255) that still counts as equal")
    sub.add_parser("harness")
    p = sub.add_parser("scenario")
    p.add_argument("id")
    p.add_argument("--title")
    p.add_argument("--group")
    p.add_argument("--kind", choices=KINDS)
    p.add_argument("--priority", choices=PRIORITIES)
    p.add_argument("--role")
    p.add_argument("--viewports", nargs="+")
    p.add_argument("--data", help="the test data the scenario owns or needs")
    p.add_argument("--script", help="path relative to the folder, scenarios/{ID}.mjs by default")
    p = sub.add_parser("scenarios")
    p.add_argument("file", type=Path)
    p = sub.add_parser("ready")
    p.add_argument("ids", nargs="+")
    p = sub.add_parser("run")
    p.add_argument("ids", nargs="*")
    p.add_argument("--group")
    which = p.add_mutually_exclusive_group()
    which.add_argument("--todo", action="store_true", help="ready scripts not run yet or run on other code")
    which.add_argument("--failed", action="store_true", help="failing, failed and flaky scenarios")
    which.add_argument("--all", action="store_true", help="every ready script")
    p.add_argument("--repeat", type=int, default=1, help="run each scenario N times, for instability")
    p = sub.add_parser("result")
    p.add_argument("id")
    p = sub.add_parser("triage")
    p.add_argument("id")
    p.add_argument("cause", choices=CAUSES)
    p.add_argument("--finding")
    p.add_argument("--note")
    p = sub.add_parser("set")
    p.add_argument("id")
    p.add_argument("outcome", choices=("pending", "blocked", "unverified"))
    p.add_argument("--reason")
    p = sub.add_parser("shots")
    p.add_argument("ids", nargs="*")
    p.add_argument("--group")
    p.add_argument("--pending", action="store_true")
    p = sub.add_parser("judge")
    p.add_argument("id")
    p.add_argument("judgment", choices=("ok", "issue"))
    p.add_argument("--shots", nargs="+", help="screenshot keys NAME@VIEWPORT; all pending by default")
    p.add_argument("--finding")
    p.add_argument("--note")
    p = sub.add_parser("finding")
    p.add_argument("id")
    p.add_argument("--scenarios", nargs="+", required=True)
    p.add_argument("--kind", choices=FINDING_KINDS, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--severity", choices=SEVERITIES)
    p = sub.add_parser("resolve")
    p.add_argument("id")
    p.add_argument("status", choices=FINDING_STATUSES)
    p.add_argument("--reason", required=True)
    p.add_argument("--duplicate-of")
    p = sub.add_parser("findings")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("assign")
    p.add_argument("ids", nargs="*")
    p.add_argument("--owner", required=True)
    p.add_argument("--task", choices=TASKS, required=True)
    p.add_argument("--group")
    p.add_argument("--note")
    p = sub.add_parser("release")
    p.add_argument("owner")
    p.add_argument("--lost", action="store_true", help="the run ended without a result")
    sub.add_parser("next")
    sub.add_parser("status")
    sub.add_parser("validate")
    p = sub.add_parser("log")
    p.add_argument("type", choices=list(LOG_REQUIRED))
    p.add_argument("fields", nargs="*", help="key=value; values are parsed as JSON when possible")
    args = parser.parse_args()

    t = Testing(args.testing_dir)
    if args.command != "init" and not t.state_path.exists():
        parser.error(f"{args.testing_dir} is not a testing folder (missing testing.json; run init)")
    if args.command == "set" and args.outcome != "pending" and not args.reason:
        parser.error(f"set {args.outcome} needs --reason")
    commands = {
        "config": cmd_config, "harness": cmd_harness, "scenario": cmd_scenario, "scenarios": cmd_scenarios,
        "ready": cmd_ready, "result": cmd_result, "triage": cmd_triage, "set": cmd_set, "shots": cmd_shots,
        "judge": cmd_judge, "finding": cmd_finding, "resolve": cmd_resolve, "findings": cmd_findings,
        "assign": cmd_assign, "release": cmd_release, "next": cmd_next, "status": cmd_status,
        "validate": cmd_validate, "log": cmd_log,
    }
    try:
        if args.command == "init":
            cmd_init(t, args)
        elif args.command == "run":
            cmd_run(t, args)
        else:
            with t.locked():
                commands[args.command](t, args)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
