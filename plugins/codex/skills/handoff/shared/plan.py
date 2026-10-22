#!/usr/bin/env python3
"""Work with a feature plan: the tasklist, the live progress and the append-only log.

Usage:
    plan.py PLAN_DIR init                      create progress.json and log.jsonl for a new plan
    plan.py PLAN_DIR validate                  check the tasklist, the progress and the log
    plan.py PLAN_DIR status                    derived overview of the plan
    plan.py PLAN_DIR next                      tasks ready to start (and parents ready to integrate)
    plan.py PLAN_DIR show ID                   one task with its status, dependencies and log
    plan.py PLAN_DIR set ID STATUS [options]   change a task status; logs the change with its evidence
    plan.py PLAN_DIR log TYPE key=value ...    append a record (check, finding, validation_plan, validation,
                                               checkpoint, note)
    plan.py PLAN_DIR findings [--all]          current state of findings, unresolved by default
    plan.py PLAN_DIR validations [--pass P | --open]
                                               cells of a validation pass, the last by default, or the cells
                                               not covered in all passes

The format is described in planning/references/artifacts.md. Python 3.8+, standard library only.
Exit code 0 on success, 1 on a validation error or a refused change, 2 on wrong usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
TASK_STATUSES = ("pending", "in_progress", "blocked", "done", "cancelled")
CLOSED = ("done", "cancelled")
PLAN_STATUSES = ("draft", "awaiting_decision", "validating", "ready")
IMPLEMENTATION_STATUSES = ("not_started", "in_progress", "blocked", "done")
DELIVERY_STATUSES = ("in_progress", "awaiting_user", "blocked", "ready_for_user", "accepted")
DELIVERY_PHASES = ("planning", "implementation", "playwright", "code_review", "fixes", "handoff")
FINDING_STATUSES = ("open", "resolved", "rejected", "awaiting_decision")
VALIDATION_MODES = ("single", "focus", "areas", "recheck")
COVERAGE = ("covered", "partial")
LOG_REQUIRED = {
    "task": ("id", "status"),
    "check": ("subject", "result"),
    "finding": ("id", "status"),
    "validation_plan": ("pass", "mode", "cells"),
    "validation": ("validators", "result"),
    "checkpoint": ("commit",),
    "note": ("text",),
}
PROGRESS_KEYS = {
    "schema_version", "feature", "updated_at", "plan_status", "implementation_status", "tasks",
    "open_questions", "handoff", "delivery",
}
AC_RE = re.compile(r"\bAC-\d+\b")


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


class Plan:
    def __init__(self, root: Path):
        self.root = root
        self.index = read_json(root / "tasks" / "index.json")
        self.tasks: dict[str, dict] = {}
        self.task_file: dict[str, str] = {}
        self.duplicates: list[str] = []
        for rel in self.index.get("task_files", []):
            if not (root / rel).exists():
                continue  # reported by validate
            data = read_json(root / rel)
            for task in data.get("tasks", []):
                tid = task.get("id")
                if tid in self.tasks:
                    self.duplicates.append(tid)
                self.tasks[tid] = task
                self.task_file[tid] = rel
        self.children: dict[str, list[str]] = {}
        for tid, task in self.tasks.items():
            if task.get("parent_id"):
                self.children.setdefault(task["parent_id"], []).append(tid)

    @property
    def progress_path(self) -> Path:
        return self.root / "progress.json"

    @property
    def log_path(self) -> Path:
        return self.root / "log.jsonl"

    def progress(self) -> dict:
        return read_json(self.progress_path)

    def log(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        records = []
        for n, line in enumerate(self.log_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise Refused(f"{self.log_path}:{n}: invalid JSON: {e}")
        return records

    def append_log(self, record: dict) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def leaves(self) -> list[str]:
        """Tasks that carry work of their own; a parent with subtasks only integrates them."""
        return [tid for tid in self.tasks if tid not in self.children]

    def status_of(self, progress: dict, tid: str) -> str:
        return progress.get("tasks", {}).get(tid, {}).get("status", "pending")

    def get(self, tid: str) -> dict:
        if tid not in self.tasks:
            raise Refused(f"unknown task {tid}")
        return self.tasks[tid]


# --- validation -------------------------------------------------------------------------------


def find_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in edges.get(node, []):
            if state.get(nxt) == 1:
                return stack[stack.index(nxt):] + [nxt]
            if nxt not in state:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in edges:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def validate(plan: Plan) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    root = plan.root

    for rel in plan.index.get("task_files", []):
        if not (root / rel).exists():
            errors.append(f"tasks/index.json: missing task file {rel}")
    for tid in plan.duplicates:
        errors.append(f"duplicate task ID {tid}")

    for tid, task in plan.tasks.items():
        where = f"{plan.task_file[tid]} {tid}"
        if not tid:
            errors.append(f"{plan.task_file[tid]}: task without an ID")
        for field in ("title", "outcome", "done_when", "complexity", "risk"):
            if not task.get(field):
                errors.append(f"{where}: missing {field}")
        parent = task.get("parent_id")
        if parent and parent not in plan.tasks:
            errors.append(f"{where}: unknown parent {parent}")
        ancestors = []
        while parent in plan.tasks and parent not in ancestors and parent != tid:
            ancestors.append(parent)
            parent = plan.tasks[parent].get("parent_id")
        for dep in task.get("depends_on", []):
            if dep not in plan.tasks:
                errors.append(f"{where}: unknown dependency {dep}")
            elif dep in ancestors:
                kind = "parent" if dep == ancestors[0] else "ancestor"
                errors.append(f"{where}: a subtask must not depend on its {kind} {dep}")
        for ref in task.get("references", []):
            target = ref.split("#", 1)[0]
            if target and not (root / target).exists():
                errors.append(f"{where}: missing reference {ref}")

    deps = {tid: [d for d in t.get("depends_on", []) if d in plan.tasks] for tid, t in plan.tasks.items()}
    cycle = find_cycle(deps)
    if cycle:
        errors.append("dependency cycle: " + " -> ".join(cycle))
    parents = {tid: [t["parent_id"]] for tid, t in plan.tasks.items() if t.get("parent_id") in plan.tasks}
    parent_cycle = find_cycle(parents)
    if parent_cycle:
        errors.append("parent cycle: " + " -> ".join(parent_cycle))
    if not cycle and not parent_cycle:
        # A parent is done only after its subtasks, so it waits for them like for its dependencies.
        waits = {tid: list(edges) for tid, edges in deps.items()}
        for tid, (parent,) in parents.items():
            waits[parent].append(tid)
        cycle = find_cycle(waits)
        if cycle:
            errors.append("cycle through dependencies and subtasks: " + " -> ".join(cycle))

    for phase in plan.index.get("phases", []):
        for tid in phase.get("tasks", []):
            if tid not in plan.tasks:
                errors.append(f"tasks/index.json phase {phase.get('id')}: unknown task {tid}")

    prd = root / "prd.md"
    if prd.exists():
        defined = set(AC_RE.findall(prd.read_text(encoding="utf-8")))
        used = {ac for t in plan.tasks.values() for ac in t.get("acceptance_criteria", [])}
        for ac in sorted(defined - used):
            errors.append(f"prd.md: {ac} is not covered by any task")
        for ac in sorted(used - defined):
            errors.append(f"tasks reference {ac}, which prd.md does not define")
    else:
        warnings.append("prd.md not found; acceptance criteria coverage not checked")

    if not plan.progress_path.exists():
        errors.append("missing progress.json (run init)")
        return errors, warnings
    try:
        progress = plan.progress()
    except Refused as e:
        errors.append(str(e))
        return errors, warnings
    for key in progress:
        if key not in PROGRESS_KEYS:
            warnings.append(f"progress.json: unexpected key {key} (history belongs in log.jsonl)")
    if progress.get("plan_status") not in PLAN_STATUSES:
        errors.append(f"progress.json: invalid plan_status {progress.get('plan_status')!r}")
    if progress.get("implementation_status") not in IMPLEMENTATION_STATUSES:
        errors.append(f"progress.json: invalid implementation_status {progress.get('implementation_status')!r}")
    delivery = progress.get("delivery")
    if delivery:
        if delivery.get("status") not in DELIVERY_STATUSES:
            errors.append(f"progress.json: invalid delivery.status {delivery.get('status')!r}")
        if delivery.get("phase") not in DELIVERY_PHASES:
            errors.append(f"progress.json: invalid delivery.phase {delivery.get('phase')!r}")
    states = progress.get("tasks", {})
    for tid in plan.tasks:
        if tid not in states:
            warnings.append(f"progress.json: no entry for {tid} (treated as pending)")
    for tid, entry in states.items():
        if tid not in plan.tasks:
            errors.append(f"progress.json: unknown task {tid}")
            continue
        status = entry.get("status")
        if status not in TASK_STATUSES:
            errors.append(f"progress.json {tid}: invalid status {status!r}")
        if status == "blocked" and not entry.get("blockers"):
            warnings.append(f"progress.json {tid}: blocked without blockers")
        if status == "done":
            for child in plan.children.get(tid, []):
                if plan.status_of(progress, child) not in CLOSED:
                    errors.append(f"progress.json {tid}: done while subtask {child} is not")
            for dep in plan.get(tid).get("depends_on", []):
                if plan.status_of(progress, dep) != "done":
                    errors.append(f"progress.json {tid}: done while dependency {dep} is not")

    try:
        records = plan.log()
    except Refused as e:
        errors.append(str(e))
        return errors, warnings
    for n, record in enumerate(records, 1):
        kind = record.get("type")
        if kind not in LOG_REQUIRED:
            errors.append(f"log.jsonl record {n}: unknown type {kind!r}")
            continue
        for field in ("at",) + LOG_REQUIRED[kind]:
            if field not in record:
                errors.append(f"log.jsonl record {n} ({kind}): missing {field}")
        if kind == "finding" and record.get("status") not in FINDING_STATUSES:
            errors.append(f"log.jsonl record {n}: invalid finding status {record.get('status')!r}")
        if kind == "finding" and "id" in record and not isinstance(record["id"], str):
            errors.append(f"log.jsonl record {n}: finding id must be a string, got {record['id']!r}")
        if kind in ("validation_plan", "validation"):
            passes = validation_passes(records[:n - 1])
            errors += [f"log.jsonl record {n}: {e}" for e in check_validation(plan, record, passes)]
    return errors, warnings


def validation_passes(records: list[dict]) -> dict[str, dict]:
    """Each validation pass with its cells and the last record of every cell, in log order."""
    passes: dict[str, dict] = {}
    for record in records:
        name = record.get("pass")
        if not isinstance(name, str):
            continue  # reported by validate
        if record.get("type") == "validation_plan" and isinstance(record.get("cells"), list):
            cells = {c["id"]: c for c in record["cells"] if isinstance(c, dict) and isinstance(c.get("id"), str)}
            passes[name] = {"mode": record.get("mode"), "cells": cells, "runs": {}}
        elif record.get("type") == "validation" and name in passes and isinstance(record.get("cell"), str):
            passes[name]["runs"][record["cell"]] = record
    return passes


def check_validation(plan: Plan, record: dict, passes: dict[str, dict]) -> list[str]:
    """The problems of one validation_plan or validation record against the passes before it."""
    errors: list[str] = []
    if "pass" in record and not isinstance(record["pass"], str):
        return errors + ["pass must be a string"]
    if record.get("type") == "validation_plan":
        if record.get("pass") in passes:
            errors.append(f"validation pass {record.get('pass')} already exists")
        if record.get("mode") not in VALIDATION_MODES:
            errors.append(f"validation mode must be one of {', '.join(VALIDATION_MODES)}")
        cells = record.get("cells")
        if not isinstance(cells, list) or not cells:
            return errors + ["cells must be a non-empty JSON list"]
        seen: set[str] = set()
        for cell in cells:
            cid = cell.get("id") if isinstance(cell, dict) else None
            if not isinstance(cid, str) or not cid:
                errors.append("every cell needs a string id")
                continue
            if cid in seen:
                errors.append(f"duplicate cell {cid}")
            seen.add(cid)
            for tid in as_list(cell.get("tasks")):
                if not isinstance(tid, str) or tid not in plan.tasks:
                    errors.append(f"cell {cid}: unknown task {tid!r}")
            for ref in as_list(cell.get("chapters")):
                if not isinstance(ref, str):
                    errors.append(f"cell {cid}: chapter must be a path, got {ref!r}")
                    continue
                target = ref.split("#", 1)[0]
                if target and not (plan.root / target).exists():
                    errors.append(f"cell {cid}: missing chapter {ref}")
        return errors
    if "pass" not in record and "cell" not in record:
        return errors  # a whole-plan validation without cells
    run = passes.get(record.get("pass"))
    if not run:
        return errors + [f"unknown validation pass {record.get('pass')!r}"]
    if not isinstance(record.get("cell"), str) or record["cell"] not in run["cells"]:
        errors.append(f"unknown cell {record.get('cell')!r} in pass {record.get('pass')}")
    if record.get("coverage") not in COVERAGE:
        errors.append(f"coverage must be one of {', '.join(COVERAGE)}")
    if record.get("coverage") == "partial" and not record.get("unchecked"):
        errors.append("partial coverage needs unchecked: what the validator could not check")
    return errors


def cell_states(run: dict) -> dict[str, str]:
    """covered, partial or pending per cell; an integration cell waits until the other cells are covered."""
    states = {cid: run["runs"].get(cid, {}).get("coverage", "pending") for cid in run["cells"]}
    local_open = any(states[c] != "covered" for c, cell in run["cells"].items() if not cell.get("integration"))
    for cid, cell in run["cells"].items():
        if cell.get("integration") and states[cid] == "pending" and local_open:
            states[cid] = "waiting"
    return states


# --- commands ---------------------------------------------------------------------------------


def cmd_init(plan: Plan, args) -> None:
    if plan.progress_path.exists():
        raise Refused("progress.json already exists; init is only for a new plan")
    progress = {
        "schema_version": SCHEMA_VERSION,
        "feature": plan.index.get("feature", plan.root.name),
        "updated_at": now(),
        "plan_status": "draft",
        "implementation_status": "not_started",
        "tasks": {tid: {"status": "pending", "owner": None, "blockers": []} for tid in plan.tasks},
        "open_questions": [],
        "handoff": {},
    }
    write_json(plan.progress_path, progress)
    plan.log_path.touch()
    print(f"created progress.json ({len(plan.tasks)} tasks) and log.jsonl")


def cmd_validate(plan: Plan, args) -> None:
    errors, warnings = validate(plan)
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        raise SystemExit(1)
    print(f"ok: {len(plan.tasks)} tasks, {len(warnings)} warnings")


def ready(plan: Plan, progress: dict) -> tuple[list[str], list[str]]:
    start, integrate = [], []
    for tid, task in plan.tasks.items():
        if plan.status_of(progress, tid) != "pending":
            continue
        # A subtask also waits for the dependencies of its parents.
        deps, parent, seen = list(task.get("depends_on", [])), task.get("parent_id"), {tid}
        while parent in plan.tasks and parent not in seen:
            seen.add(parent)
            deps += plan.tasks[parent].get("depends_on", [])
            parent = plan.tasks[parent].get("parent_id")
        if any(plan.status_of(progress, d) != "done" for d in deps):
            continue
        children = plan.children.get(tid)
        if not children:
            start.append(tid)
        elif all(plan.status_of(progress, c) in CLOSED for c in children):
            integrate.append(tid)
    return start, integrate


def line(plan: Plan, tid: str) -> str:
    t = plan.tasks[tid]
    return f"{tid}  [{t.get('complexity', '?')}/{t.get('risk', '?')}]  {t.get('title', '')}"


def cmd_status(plan: Plan, args) -> None:
    progress = plan.progress()
    print(f"feature: {progress.get('feature')}")
    print(f"plan: {progress.get('plan_status')}, implementation: {progress.get('implementation_status')}")
    delivery = progress.get("delivery")
    if delivery:
        print(f"delivery: {delivery.get('status')}, phase {delivery.get('phase')}")
    leaves = plan.leaves()
    counts = {s: 0 for s in TASK_STATUSES}
    for tid in leaves:
        # An invalid status is counted under its own name; validate reports it.
        status = plan.status_of(progress, tid)
        counts[status] = counts.get(status, 0) + 1
    active = len(leaves) - counts["cancelled"]
    pct = round(100 * counts["done"] / active) if active else 0
    print("tasks: " + ", ".join(f"{s} {n}" for s, n in counts.items() if n) + f"  ({pct}% done)")
    for tid in leaves + list(plan.children):
        entry = progress.get("tasks", {}).get(tid, {})
        if entry.get("status") == "blocked":
            print(f"blocked: {tid} — {'; '.join(entry.get('blockers', [])) or 'no blocker recorded'}")
        elif entry.get("status") == "in_progress":
            print(f"in progress: {tid} ({entry.get('owner') or 'no owner'})")
    if progress.get("open_questions"):
        print("open questions: " + ", ".join(map(str, progress["open_questions"])))
    open_findings = [f for f in findings(plan) if f.get("status") in ("open", "awaiting_decision")]
    if open_findings:
        print(f"unresolved findings: {len(open_findings)} (see findings)")
    passes = validation_passes(plan.log())
    if passes:
        name, run = list(passes.items())[-1]
        states = cell_states(run)
        covered = sum(1 for v in states.values() if v == "covered")
        print(f"validation {name} ({run['mode']}): {covered}/{len(states)} cells covered (see validations)")
        not_covered = open_cells(passes)
        if not_covered:
            print(f"cells not covered in all passes: {len(not_covered)} (see validations --open)")
    start, integrate = ready(plan, progress)
    print(f"ready to start: {', '.join(start) or '-'}")
    if integrate:
        print(f"ready to integrate: {', '.join(integrate)}")


def cmd_next(plan: Plan, args) -> None:
    start, integrate = ready(plan, plan.progress())
    for tid in start:
        print(line(plan, tid))
    for tid in integrate:
        print(line(plan, tid) + "  (integrate subtasks)")
    if not start and not integrate:
        print("no task is ready")


def cmd_show(plan: Plan, args) -> None:
    task = plan.get(args.id)
    progress = plan.progress()
    entry = progress.get("tasks", {}).get(args.id, {"status": "pending"})
    print(f"# {args.id} ({plan.task_file[args.id]})")
    print(json.dumps(task, indent=2, ensure_ascii=False))
    print(f"\nstatus: {json.dumps(entry, ensure_ascii=False)}")
    for label, ids in (("depends on", task.get("depends_on", [])), ("subtasks", plan.children.get(args.id, []))):
        if ids:
            print(f"{label}: " + ", ".join(f"{d} ({plan.status_of(progress, d)})" for d in ids))
    consumers = [t for t, v in plan.tasks.items() if args.id in v.get("depends_on", [])]
    if consumers:
        print("needed by: " + ", ".join(consumers))
    touches = lambda r: args.id == r.get("id") or args.id in as_list(r.get("tasks"))  # noqa: E731
    history = [r for r in plan.log() if r.get("type") != "finding" and touches(r)]
    history += [f for f in findings(plan) if touches(f)]
    if history:
        print("log:")
        for r in history:
            print("  " + json.dumps(r, ensure_ascii=False))


def as_list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def cmd_set(plan: Plan, args) -> None:
    task = plan.get(args.id)
    progress = plan.progress()
    status = args.status
    if status == "done":
        if not args.evidence:
            raise Refused("done needs --evidence: the met done_when conditions and the verification")
        open_children = [c for c in plan.children.get(args.id, []) if plan.status_of(progress, c) not in CLOSED]
        if open_children:
            raise Refused(f"subtasks not finished: {', '.join(open_children)}")
        open_deps = [d for d in task.get("depends_on", []) if plan.status_of(progress, d) != "done"]
        if open_deps:
            raise Refused(f"dependencies not done: {', '.join(open_deps)}")
    if status == "cancelled" and not args.reason:
        raise Refused("cancelled needs --reason, after checking the consumers and the criteria coverage")
    if status == "blocked" and not args.blocker and not progress.get("tasks", {}).get(args.id, {}).get("blockers"):
        raise Refused("blocked needs --blocker")

    entry = progress.setdefault("tasks", {}).setdefault(args.id, {"status": "pending", "owner": None, "blockers": []})
    previous = entry.get("status", "pending")
    entry["status"] = status
    if args.owner is not None:
        entry["owner"] = args.owner or None
    if args.blocker:
        entry["blockers"] = list(dict.fromkeys(entry.get("blockers", []) + args.blocker))
    if status in ("in_progress", "done", "cancelled") and not args.blocker:
        entry["blockers"] = []
    stamp = now()
    entry["updated_at"] = stamp
    progress["updated_at"] = stamp
    if status == "in_progress" and progress.get("implementation_status") == "not_started":
        progress["implementation_status"] = "in_progress"
    write_json(plan.progress_path, progress)

    record = {"at": stamp, "type": "task", "id": args.id, "status": status, "from": previous}
    for key in ("evidence", "reason"):
        if getattr(args, key):
            record[key] = getattr(args, key)
    if args.blocker:
        record["blockers"] = args.blocker
    plan.append_log(record)
    print(f"{args.id}: {previous} -> {status}")
    consumers = [t for t, v in plan.tasks.items() if args.id in v.get("depends_on", [])]
    if status == "cancelled" and consumers:
        print(f"warning: {', '.join(consumers)} depend on this task; update their depends_on via planning")


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


def cmd_log(plan: Plan, args) -> None:
    record = {"at": now(), "type": args.type, **dict(args.fields)}
    missing = [f for f in LOG_REQUIRED[args.type] if f not in record]
    if missing:
        raise Refused(f"{args.type} needs: {', '.join(missing)}")
    if args.type == "finding" and not isinstance(record["id"], str):
        raise Refused(f"finding id must be a string, got {record['id']!r}")
    if args.type == "finding" and record["status"] not in FINDING_STATUSES:
        raise Refused(f"finding status must be one of {', '.join(FINDING_STATUSES)}")
    if args.type in ("validation_plan", "validation"):
        problems = check_validation(plan, record, validation_passes(plan.log()))
        if problems:
            raise Refused("; ".join(problems))
    plan.append_log(record)
    print("logged " + json.dumps(record, ensure_ascii=False))


def findings(plan: Plan) -> list[dict]:
    """The current state of each finding: its log records merged in order, later fields win."""
    merged: dict[str, dict] = {}
    for record in plan.log():
        # A record without a usable ID is reported by validate and left out here.
        if record.get("type") == "finding" and isinstance(record.get("id"), str):
            merged.setdefault(record["id"], {}).update(record)
    return list(merged.values())


def cmd_findings(plan: Plan, args) -> None:
    items = findings(plan)
    if not args.all:
        items = [f for f in items if f.get("status") in ("open", "awaiting_decision")]
    for f in items:
        print(json.dumps({k: v for k, v in f.items() if k != "type"}, ensure_ascii=False))
    if not items:
        print("no findings" if args.all else "no unresolved findings")


def open_cells(passes: dict[str, dict]) -> list[tuple[str, str, str]]:
    """(pass, cell, state) of every cell not covered, in all passes; plan_status ready needs none."""
    return [(name, cid, state) for name, run in passes.items()
            for cid, state in cell_states(run).items() if state != "covered"]


def cmd_validations(plan: Plan, args) -> None:
    passes = validation_passes(plan.log())
    if not passes:
        print("no validation pass recorded (log validation_plan)")
        return
    if args.open:
        cells = open_cells(passes)
        for name, cid, state in cells:
            print(f"{name}/{cid}  [{state}]  {passes[name]['cells'][cid].get('focus', '')}")
        if not cells:
            print("every cell of every pass is covered")
        return
    name = args.pass_id or list(passes)[-1]
    if name not in passes:
        raise Refused(f"unknown validation pass {name}")
    run = passes[name]
    states = cell_states(run)
    print(f"pass {name} ({run['mode']})")
    for cid, cell in run["cells"].items():
        state = states[cid]
        extra = ""
        if state == "partial":
            extra = "  unchecked: " + json.dumps(run["runs"][cid].get("unchecked"), ensure_ascii=False)
        elif state in ("covered", "partial"):
            extra = f"  result: {run['runs'][cid].get('result')}"
        print(f"{cid}  [{state}]  {cell.get('focus', '')}{extra}")
    brief = [c for c, v in states.items() if v in ("pending", "partial")]
    print(f"to brief: {', '.join(brief) or '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan_dir", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("validate")
    sub.add_parser("status")
    sub.add_parser("next")
    p = sub.add_parser("show")
    p.add_argument("id")
    p = sub.add_parser("set")
    p.add_argument("id")
    p.add_argument("status", choices=TASK_STATUSES)
    p.add_argument("--owner", help="who works on it; an empty value clears it")
    p.add_argument("--blocker", action="append", help="a blocker, e.g. Q-003; repeatable")
    p.add_argument("--evidence", help="required for done")
    p.add_argument("--reason", help="required for cancelled")
    p = sub.add_parser("log")
    p.add_argument("type", choices=[t for t in LOG_REQUIRED if t != "task"])
    p.add_argument("fields", nargs="*", type=log_field, help="key=value; values are parsed as JSON when possible")
    p = sub.add_parser("findings")
    p.add_argument("--all", action="store_true")
    p = sub.add_parser("validations")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--pass", dest="pass_id", help="the pass to show; the last one by default")
    group.add_argument("--open", action="store_true", help="the cells not covered in all passes")
    args = parser.parse_args()

    if not (args.plan_dir / "tasks" / "index.json").exists():
        parser.error(f"{args.plan_dir} is not a plan folder (missing tasks/index.json)")
    commands = {
        "init": cmd_init, "validate": cmd_validate, "status": cmd_status, "next": cmd_next,
        "show": cmd_show, "set": cmd_set, "log": cmd_log, "findings": cmd_findings,
        "validations": cmd_validations,
    }
    try:
        commands[args.command](Plan(args.plan_dir), args)
    except Refused as e:
        print(f"refused: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
