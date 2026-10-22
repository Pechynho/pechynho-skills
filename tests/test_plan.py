"""Tests of base/shared/plan.py, the plan tool for the tasklist, progress.json and log.jsonl.

The expectations follow the module docstring, base/shared/plan-tool.md and
base/skills/planning/references/artifacts.md. The CLI is the contract the skills rely on, so most
tests run it as a subprocess against a small plan built in a temporary directory.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SHARED, ToolTestCase, load_module, run_tool, write_json

PLAN = SHARED / "plan.py"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CELLS = json.dumps([
    {"id": "A1", "focus": "data", "chapters": ["chapters/01-core.md"], "tasks": ["T-001"]},
    {"id": "A2", "focus": "ui", "tasks": ["T-002"]},
    {"id": "INT", "focus": "integration", "integration": True},
])


def task(tid: str, **fields) -> dict:
    """A task with every field validate requires; keyword arguments override them."""
    return {
        "id": tid, "title": f"{tid} title", "parent_id": None, "outcome": "it works",
        "references": [], "acceptance_criteria": [], "depends_on": [], "done_when": ["it works"],
        "complexity": "low", "risk": "low", **fields,
    }


def default_tasks() -> list[dict]:
    return [task("T-001"), task("T-002", depends_on=["T-001"])]


def hierarchy_tasks() -> list[dict]:
    """A parent T-001 with two subtasks and an independent T-002."""
    return [
        task("T-001"),
        task("T-001.1", parent_id="T-001"),
        task("T-001.2", parent_id="T-001"),
        task("T-002"),
    ]


def load_plan_module():
    return load_module(PLAN, "plan_tool")


class PlanTestCase(ToolTestCase):
    """Builds a plan folder in self.plan and runs the tool against it."""

    def setUp(self) -> None:
        super().setUp()
        self.plan = self.tmp / "demo-feature"

    def make_plan(self, tasks: list[dict] | None = None, *, extra_files: dict | None = None,
                  prd: str | None = "# PRD\n", phases: list | None = None, feature: str | None = "demo",
                  init: bool = True) -> None:
        index = {"schema_version": 1, "task_files": ["tasks/01-core.json"], "phases": phases or []}
        if feature is not None:
            index["feature"] = feature
        write_json(self.plan / "tasks" / "01-core.json",
                   {"schema_version": 1, "tasks": default_tasks() if tasks is None else tasks})
        for rel, file_tasks in (extra_files or {}).items():
            index["task_files"].append(rel)
            write_json(self.plan / rel, {"schema_version": 1, "tasks": file_tasks})
        write_json(self.plan / "tasks" / "index.json", index)
        (self.plan / "chapters").mkdir()
        (self.plan / "chapters" / "01-core.md").write_text("# Core\n", encoding="utf-8")
        if prd is not None:
            (self.plan / "prd.md").write_text(prd, encoding="utf-8")
        if init:
            self.assertOk(self.run_plan("init"))

    def run_plan(self, *args: str):
        return run_tool(PLAN, self.plan, *args, env={"PYTHONUTF8": "1"})

    def ok(self, *args: str) -> str:
        result = self.run_plan(*args)
        self.assertOk(result)
        return result.stdout

    def refused(self, *args: str, message: str) -> None:
        """The command exits 1 with the message and leaves progress.json and log.jsonl untouched."""
        before = self.snapshot()
        result = self.run_plan(*args)
        self.assertExit(result, 1)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.snapshot(), before)

    def snapshot(self) -> tuple:
        return tuple(p.read_bytes() if p.exists() else None
                     for p in (self.plan / "progress.json", self.plan / "log.jsonl"))

    def progress(self) -> dict:
        return json.loads((self.plan / "progress.json").read_text(encoding="utf-8"))

    def edit_progress(self, change) -> None:
        progress = self.progress()
        change(progress)
        write_json(self.plan / "progress.json", progress)

    def log(self) -> list[dict]:
        text = (self.plan / "log.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def write_log(self, records: list) -> None:
        lines = [r if isinstance(r, str) else json.dumps(r) for r in records]
        (self.plan / "log.jsonl").write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def assertValidateError(self, message: str) -> None:
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn(f"error: {message}", result.stdout)

    def assertValidateWarning(self, message: str) -> None:
        result = self.run_plan("validate")
        self.assertOk(result)
        self.assertIn(f"warning: {message}", result.stdout)


class UsageTest(PlanTestCase):
    def test_folder_without_index_is_wrong_usage(self):
        self.plan.mkdir()
        result = self.run_plan("status")
        self.assertExit(result, 2)
        self.assertIn("not a plan folder", result.stderr)

    def test_argument_errors_exit_2(self):
        self.make_plan()
        for args in (
            (),
            ("bogus",),
            ("set", "T-001"),
            ("set", "T-001", "finished"),
            ("show",),
            ("log", "task", "id=T-001", "status=done"),
            ("log", "bogus", "text=x"),
            ("validations", "--pass", "V1", "--open"),
        ):
            with self.subTest(args=args):
                self.assertExit(self.run_plan(*args), 2)

    def test_malformed_field_is_rejected_without_writing(self):
        self.make_plan()
        for field in ("novalue", "=value"):
            with self.subTest(field=field):
                result = self.run_plan("log", "note", "text=x", field)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("expected key=value", result.stderr)
                self.assertEqual(self.log(), [])

    def test_malformed_field_exits_2(self):
        self.make_plan()
        self.assertExit(self.run_plan("log", "note", "text=x", "novalue"), 2)


class InitTest(PlanTestCase):
    def test_creates_pending_progress_and_empty_log(self):
        self.make_plan(init=False)
        out = self.ok("init")
        self.assertIn("2 tasks", out)
        progress = self.progress()
        self.assertEqual(progress["schema_version"], 1)
        self.assertEqual(progress["feature"], "demo")
        self.assertRegex(progress["updated_at"], TIMESTAMP)
        self.assertEqual(progress["plan_status"], "draft")
        self.assertEqual(progress["implementation_status"], "not_started")
        self.assertEqual(progress["tasks"], {
            "T-001": {"status": "pending", "owner": None, "blockers": []},
            "T-002": {"status": "pending", "owner": None, "blockers": []},
        })
        self.assertEqual(progress["open_questions"], [])
        self.assertEqual(progress["handoff"], {})
        self.assertEqual((self.plan / "log.jsonl").read_text(), "")

    def test_feature_defaults_to_folder_name(self):
        self.make_plan(feature=None)
        self.assertEqual(self.progress()["feature"], "demo-feature")

    def test_refuses_an_existing_plan(self):
        self.make_plan()
        self.ok("set", "T-001", "in_progress")
        self.refused("init", message="already exists")

    def test_fresh_plan_validates_cleanly(self):
        self.make_plan()
        self.assertEqual(self.ok("validate"), "ok: 2 tasks, 0 warnings\n")


class ValidateTasklistTest(PlanTestCase):
    def test_missing_task_file(self):
        self.make_plan()
        index = json.loads((self.plan / "tasks" / "index.json").read_text())
        index["task_files"].append("tasks/02-missing.json")
        write_json(self.plan / "tasks" / "index.json", index)
        self.assertValidateError("tasks/index.json: missing task file tasks/02-missing.json")

    def test_invalid_json_in_task_file_exits_1(self):
        self.make_plan()
        (self.plan / "tasks" / "01-core.json").write_text("{not json")
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("invalid JSON", result.stderr)

    def test_invalid_json_in_index_exits_1(self):
        self.make_plan()
        (self.plan / "tasks" / "index.json").write_text("[")
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("invalid JSON", result.stderr)

    def test_duplicate_id_across_files(self):
        self.make_plan(extra_files={"tasks/02-more.json": [task("T-001")]})
        self.assertValidateError("duplicate task ID T-001")

    def test_missing_required_fields(self):
        for field in ("title", "outcome", "done_when", "complexity", "risk"):
            with self.subTest(field=field):
                self.plan = self.tmp / field
                self.make_plan([task("T-001", **{field: ""})])
                self.assertValidateError(f"tasks/01-core.json T-001: missing {field}")

    def test_unknown_parent_and_dependency(self):
        self.make_plan([task("T-001", parent_id="T-404", depends_on=["T-405"])])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("unknown parent T-404", result.stdout)
        self.assertIn("unknown dependency T-405", result.stdout)

    def test_subtask_must_not_depend_on_its_parent(self):
        self.make_plan([task("T-001"), task("T-001.1", parent_id="T-001", depends_on=["T-001"])])
        self.assertValidateError("tasks/01-core.json T-001.1: a subtask must not depend on its parent T-001")

    def test_dependency_cycle(self):
        self.make_plan([task("T-001", depends_on=["T-002"]), task("T-002", depends_on=["T-001"])])
        self.assertValidateError("dependency cycle: T-001 -> T-002 -> T-001")

    def test_self_dependency_is_a_cycle(self):
        self.make_plan([task("T-001", depends_on=["T-001"])])
        self.assertValidateError("dependency cycle: T-001 -> T-001")

    def test_parent_cycle(self):
        self.make_plan([task("T-001", parent_id="T-002"), task("T-002", parent_id="T-001")])
        self.assertValidateError("parent cycle")

    def test_cycle_through_dependencies_and_hierarchy(self):
        # T-001 is done only after T-001.1, which waits for T-002, which waits for T-001.
        self.make_plan([
            task("T-001"),
            task("T-001.1", parent_id="T-001", depends_on=["T-002"]),
            task("T-002", depends_on=["T-001"]),
        ])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("cycle", result.stdout)

    def test_subtask_must_not_depend_on_its_grandparent(self):
        self.make_plan([
            task("T-001"),
            task("T-001.1", parent_id="T-001"),
            task("T-001.1.1", parent_id="T-001.1", depends_on=["T-001"]),
        ])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("T-001.1.1: a subtask must not depend on its ancestor T-001", result.stdout)

    def test_references_must_exist(self):
        self.make_plan([task("T-001", references=["chapters/01-core.md#core", "chapters/missing.md#x"])])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("missing reference chapters/missing.md#x", result.stdout)
        self.assertNotIn("01-core.md", result.stdout)

    def test_references_must_stay_in_the_plan_folder(self):
        outside = self.tmp / "work" / "mockup.html"
        outside.parent.mkdir()
        outside.write_text("<p>mockup</p>")
        self.make_plan([task("T-001", references=[str(outside), "../work/mockup.html", "chapters/01-core.md"])])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn(f"reference outside the plan folder {outside}", result.stdout)
        self.assertIn("reference outside the plan folder ../work/mockup.html", result.stdout)
        self.assertNotIn("01-core.md", result.stdout)

    def test_phase_with_unknown_task(self):
        self.make_plan(phases=[{"id": "P1", "name": "First", "tasks": ["T-001", "T-404"]}])
        self.assertValidateError("tasks/index.json phase P1: unknown task T-404")

    def test_acceptance_criteria_coverage(self):
        self.make_plan([task("T-001", acceptance_criteria=["AC-001", "AC-003"])],
                       prd="# PRD\n- AC-001: one\n- AC-002: two\n")
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("error: prd.md: AC-002 is not covered by any task", result.stdout)
        self.assertIn("error: tasks reference AC-003, which prd.md does not define", result.stdout)
        self.assertNotIn("AC-001", result.stdout)

    def test_missing_prd_is_a_warning(self):
        self.make_plan(prd=None)
        self.assertValidateWarning("prd.md not found")
        self.assertIn("ok: 2 tasks, 1 warnings", self.ok("validate"))


class ValidateMockupsTest(PlanTestCase):
    """mockups/index.json: every file listed, approvals and refusals backed by decisions.md."""

    def make_mockups(self, mockups: list[dict], *, declined: list | None = None,
                     files: tuple[str, ...] = ("01-dashboard.html",), tasks: list[dict] | None = None,
                     decisions: str = "# Decisions\n\n## D-001 Dashboard look\n") -> None:
        self.make_plan(tasks)
        folder = self.plan / "mockups"
        folder.mkdir()
        for name in files:
            (folder / name).write_text("<p>mockup</p>", encoding="utf-8")
        write_json(folder / "index.json",
                   {"schema_version": 1, "mockups": mockups, "declined": declined or []})
        (self.plan / "decisions.md").write_text(decisions, encoding="utf-8")
        (self.plan / "README.md").write_text("[Mockups](mockups/index.json)\n", encoding="utf-8")

    def make_mockups_again(self, mockups: list[dict], **kwargs) -> None:
        shutil.rmtree(self.plan)
        self.make_mockups(mockups, **kwargs)

    def approved(self, **fields) -> dict:
        return {"id": "M-001", "file": "01-dashboard.html", "status": "approved", "decision": "D-001",
                **fields}

    def test_approved_mockup_referenced_by_a_task(self):
        self.make_mockups([self.approved()], tasks=[task("T-001", references=["mockups/01-dashboard.html"])])
        self.assertIn("ok: 1 tasks, 0 warnings", self.ok("validate"))

    def test_unlisted_file(self):
        self.make_mockups([self.approved()], files=("01-dashboard.html", "02-detail.html"))
        self.assertValidateError("mockups/index.json: mockups/02-detail.html is not listed")

    def test_listed_file_must_exist(self):
        self.make_mockups([self.approved(file="03-missing.html")], files=())
        self.assertValidateError("mockups/index.json M-001: missing file 03-missing.html")

    def test_file_outside_the_mockups_folder(self):
        self.make_mockups([self.approved(file="../../work/mockup.html")], files=())
        self.assertValidateError("mockups/index.json M-001: file must be a plain path inside the mockups folder")

    def test_file_path_must_be_plain(self):
        self.make_mockups([self.approved(file="./01-dashboard.html")])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("file must be a plain path inside the mockups folder: ./01-dashboard.html", result.stdout)

    def test_malformed_index(self):
        self.make_mockups([])
        index = self.plan / "mockups" / "index.json"
        for data, message in (([], "mockups/index.json: expected an object"),
                              ({"schema_version": 1, "mockups": ["01-dashboard.html"]},
                               "mockups/index.json: mockups must be a list of objects"),
                              ({"schema_version": 1, "declined": "none"},
                               "mockups/index.json: declined must be a list of objects"),
                              ({"schema_version": 2, "mockups": []},
                               "mockups/index.json: unsupported schema_version 2")):
            with self.subTest(data=data):
                write_json(index, data)
                result = self.run_plan("validate")
                self.assertExit(result, 1)
                self.assertIn(f"error: {message}", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_approval_needs_a_decision_in_decisions_md(self):
        self.make_mockups([self.approved(decision=None)])
        self.assertValidateError("mockups/index.json M-001: approved without a decision")
        self.make_mockups_again([self.approved(decision="D-009")])
        self.assertValidateError("mockups/index.json M-001: decision D-009 is not in decisions.md")

    def test_invalid_status_and_duplicate_id(self):
        self.make_mockups([self.approved(), self.approved(file="02-detail.html", status="final")],
                          files=("01-dashboard.html", "02-detail.html"))
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("error: mockups/index.json: duplicate mockup ID M-001", result.stdout)
        self.assertIn("error: mockups/index.json M-001: invalid status 'final'", result.stdout)

    def test_proposed_mockup_is_a_warning_and_cannot_guide_a_task(self):
        proposed = {"id": "M-001", "file": "01-dashboard.html", "status": "proposed"}
        self.make_mockups([proposed])
        self.assertValidateWarning("mockups/index.json M-001: not approved yet")
        self.make_mockups_again([proposed], tasks=[task("T-001", references=["mockups/01-dashboard.html"])])
        self.assertValidateError("tasks/01-core.json T-001: references mockups/01-dashboard.html, which is not approved")

    def test_declined_scope_needs_a_decision(self):
        self.make_mockups([], files=(), declined=[{"scope": "Notification e-mail", "decision": "D-001"}])
        self.assertIn("ok: 2 tasks", self.ok("validate"))
        self.make_mockups_again([], files=(), declined=[{"scope": "Notification e-mail"}])
        self.assertValidateError("mockups/index.json: declined 'Notification e-mail' without a decision")

    def test_task_reference_to_mockups_without_index(self):
        self.make_plan([task("T-001", references=["mockups/01-dashboard.html"])])
        (self.plan / "mockups").mkdir()
        (self.plan / "mockups" / "01-dashboard.html").write_text("<p>mockup</p>", encoding="utf-8")
        self.assertValidateError("missing")
        self.assertIn("mockups/index.json", self.run_plan("validate").stdout)

    def test_readme_without_a_link_is_a_warning(self):
        self.make_mockups([self.approved()])
        (self.plan / "README.md").write_text("# Feature\n", encoding="utf-8")
        self.assertValidateWarning("README.md: no link to the mockups")


class ValidateProgressTest(PlanTestCase):
    def test_missing_progress(self):
        self.make_plan(init=False)
        self.assertValidateError("missing progress.json (run init)")

    def test_invalid_progress_json(self):
        self.make_plan()
        (self.plan / "progress.json").write_text("{")
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("invalid JSON", result.stdout)

    def test_unexpected_key_is_a_warning(self):
        self.make_plan()
        self.edit_progress(lambda p: p.update(history=[]))
        self.assertValidateWarning("progress.json: unexpected key history")

    def test_invalid_plan_and_implementation_status(self):
        self.make_plan()
        self.edit_progress(lambda p: p.update(plan_status="done", implementation_status="finished"))
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("invalid plan_status 'done'", result.stdout)
        self.assertIn("invalid implementation_status 'finished'", result.stdout)

    def test_every_documented_status_is_accepted(self):
        self.make_plan()
        for plan_status in ("draft", "awaiting_decision", "validating", "ready"):
            for impl in ("not_started", "in_progress", "blocked", "done"):
                with self.subTest(plan_status=plan_status, impl=impl):
                    self.edit_progress(lambda p: p.update(plan_status=plan_status, implementation_status=impl))
                    self.ok("validate")

    def test_delivery(self):
        self.make_plan()
        self.edit_progress(lambda p: p.update(delivery={"status": "in_progress", "phase": "implementation"}))
        self.ok("validate")
        self.edit_progress(lambda p: p.update(delivery={"status": "shipping", "phase": "qa"}))
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("invalid delivery.status 'shipping'", result.stdout)
        self.assertIn("invalid delivery.phase 'qa'", result.stdout)

    def test_unknown_task_and_invalid_task_status(self):
        self.make_plan()
        self.edit_progress(lambda p: p["tasks"].update({
            "T-404": {"status": "pending"}, "T-001": {"status": "doing"},
        }))
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("progress.json: unknown task T-404", result.stdout)
        self.assertIn("progress.json T-001: invalid status 'doing'", result.stdout)

    def test_missing_entry_is_treated_as_pending(self):
        self.make_plan()
        self.edit_progress(lambda p: p["tasks"].pop("T-002"))
        self.assertValidateWarning("progress.json: no entry for T-002 (treated as pending)")

    def test_blocked_without_blockers_is_a_warning(self):
        self.make_plan()
        self.edit_progress(lambda p: p["tasks"]["T-001"].update(status="blocked", blockers=[]))
        self.assertValidateWarning("progress.json T-001: blocked without blockers")

    def test_done_before_dependency(self):
        self.make_plan()
        self.edit_progress(lambda p: p["tasks"]["T-002"].update(status="done"))
        self.assertValidateError("progress.json T-002: done while dependency T-001 is not")

    def test_done_parent_with_open_subtask(self):
        self.make_plan(hierarchy_tasks())
        self.edit_progress(lambda p: (p["tasks"]["T-001"].update(status="done"),
                                      p["tasks"]["T-001.1"].update(status="cancelled")))
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("progress.json T-001: done while subtask T-001.2 is not", result.stdout)
        self.assertNotIn("T-001.1 is not", result.stdout)


class ValidateLogTest(PlanTestCase):
    def test_invalid_json_line(self):
        self.make_plan()
        self.write_log([{"at": "2026-01-01T00:00:00Z", "type": "note", "text": "x"}, "not json"])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        self.assertIn("log.jsonl:2: invalid JSON", result.stdout)

    def test_record_problems(self):
        self.make_plan()
        at = "2026-01-01T00:00:00Z"
        self.write_log([
            {"at": at, "type": "bogus"},
            {"at": at, "type": "check", "subject": "make test"},
            {"type": "note", "text": "x"},
            {"at": at, "type": "finding", "id": "F-1", "status": "fixed"},
            {"at": at, "type": "validation", "pass": "V9", "cell": "A1", "validators": ["V"], "result": "ok",
             "coverage": "covered"},
        ])
        result = self.run_plan("validate")
        self.assertExit(result, 1)
        for message in (
            "log.jsonl record 1: unknown type 'bogus'",
            "log.jsonl record 2 (check): missing result",
            "log.jsonl record 3 (note): missing at",
            "log.jsonl record 4: invalid finding status 'fixed'",
            "log.jsonl record 5: unknown validation pass 'V9'",
        ):
            self.assertIn(f"error: {message}", result.stdout)

    def test_repeated_validation_pass(self):
        self.make_plan()
        record = {"at": "2026-01-01T00:00:00Z", "type": "validation_plan", "pass": "V1", "mode": "single",
                  "cells": [{"id": "ALL", "focus": "whole plan"}]}
        self.write_log([record, record])
        self.assertValidateError("log.jsonl record 2: validation pass V1 already exists")

    def test_log_written_by_the_tool_validates(self):
        self.make_plan()
        self.ok("set", "T-001", "in_progress", "--owner", "worker")
        self.ok("set", "T-001", "done", "--evidence", "tests pass")
        self.ok("set", "T-002", "blocked", "--blocker", "Q-001")
        self.ok("set", "T-002", "cancelled", "--reason", "out of scope")
        self.ok("log", "check", "subject=make test", "result=pass", "revision=abc123")
        self.ok("log", "finding", "id=F-1", "status=open", "severity=high", 'tasks=["T-001"]')
        self.ok("log", "finding", "id=F-1", "status=resolved")
        self.ok("log", "validation_plan", "pass=V1", "mode=areas", f"cells={CELLS}")
        self.ok("log", "validation", "pass=V1", "cell=A1", 'validators=["V-A1"]', "result=ok", "coverage=covered")
        self.ok("log", "validation", 'validators=["V"]', "result=ok")
        self.ok("log", "checkpoint", "commit=abc123")
        self.ok("log", "note", "text=resume from T-002")
        self.assertIn("ok: 2 tasks, 0 warnings", self.ok("validate"))


class StatusTest(PlanTestCase):
    def test_fresh_plan(self):
        self.make_plan()
        out = self.ok("status")
        self.assertIn("feature: demo", out)
        self.assertIn("plan: draft, implementation: not_started", out)
        self.assertIn("tasks: pending 2  (0% done)", out)
        self.assertIn("ready to start: T-001\n", out)
        self.assertNotIn("delivery", out)

    def test_invalid_status_is_shown_not_a_crash(self):
        self.make_plan()
        self.edit_progress(lambda p: p["tasks"]["T-001"].update(status="doing"))
        self.assertIn("doing 1", self.ok("status"))

    def test_counts_leaves_only_and_excludes_cancelled_from_the_percentage(self):
        self.make_plan(hierarchy_tasks())
        self.ok("set", "T-001.1", "done", "--evidence", "ok")
        self.ok("set", "T-001.2", "cancelled", "--reason", "not needed")
        out = self.ok("status")
        self.assertIn("tasks: pending 1, done 1, cancelled 1  (50% done)", out)
        self.assertIn("ready to start: T-002", out)
        self.assertIn("ready to integrate: T-001", out)

    def test_running_and_blocked_tasks(self):
        self.make_plan([task("T-001"), task("T-002"), task("T-003")])
        self.ok("set", "T-001", "in_progress", "--owner", "alice")
        self.ok("set", "T-002", "blocked", "--blocker", "Q-001", "--blocker", "Q-002")
        self.ok("set", "T-003", "in_progress")
        lines = self.ok("status").splitlines()
        self.assertIn("in progress: T-001 (alice)", lines)
        self.assertIn("in progress: T-003 (no owner)", lines)
        blocked = [line for line in lines if line.startswith("blocked: T-002")]
        self.assertEqual(len(blocked), 1)
        self.assertIn("Q-001; Q-002", blocked[0])
        self.assertIn("ready to start: -", lines)

    def test_delivery_questions_findings_and_validation(self):
        self.make_plan()
        self.edit_progress(lambda p: p.update(
            open_questions=["Q-001"], delivery={"status": "in_progress", "phase": "code_review"}))
        self.ok("log", "finding", "id=F-1", "status=open")
        self.ok("log", "finding", "id=F-2", "status=awaiting_decision")
        self.ok("log", "finding", "id=F-3", "status=rejected")
        self.ok("log", "validation_plan", "pass=V1", "mode=areas", f"cells={CELLS}")
        self.ok("log", "validation", "pass=V1", "cell=A1", 'validators=["V"]', "result=ok", "coverage=covered")
        out = self.ok("status")
        self.assertIn("delivery: in_progress, phase code_review", out)
        self.assertIn("open questions: Q-001", out)
        self.assertIn("unresolved findings: 2", out)
        self.assertIn("validation V1 (areas): 1/3 cells covered", out)
        self.assertIn("cells not covered in all passes: 2", out)

    def test_missing_progress_exits_1(self):
        self.make_plan(init=False)
        result = self.run_plan("status")
        self.assertExit(result, 1)
        self.assertIn("missing", result.stderr)


class NextTest(PlanTestCase):
    def test_tasks_with_done_dependencies(self):
        self.make_plan()
        self.assertEqual(self.ok("next"), "T-001  [low/low]  T-001 title\n")
        self.ok("set", "T-001", "in_progress")
        self.assertEqual(self.ok("next"), "no task is ready\n")
        self.ok("set", "T-001", "done", "--evidence", "ok")
        self.assertEqual(self.ok("next"), "T-002  [low/low]  T-002 title\n")
        self.ok("set", "T-002", "done", "--evidence", "ok")
        self.assertEqual(self.ok("next"), "no task is ready\n")

    def test_cancelled_dependency_does_not_unblock(self):
        self.make_plan()
        self.ok("set", "T-001", "cancelled", "--reason", "dropped")
        self.assertEqual(self.ok("next"), "no task is ready\n")

    def test_parent_waits_for_its_subtasks(self):
        self.make_plan(hierarchy_tasks())
        out = self.ok("next")
        self.assertIn("T-001.1", out)
        self.assertIn("T-001.2", out)
        self.assertIn("T-002", out)
        self.assertNotIn("T-001  ", out)
        self.ok("set", "T-001.1", "done", "--evidence", "ok")
        self.ok("set", "T-001.2", "cancelled", "--reason", "dropped")
        self.assertIn("T-001  [low/low]  T-001 title  (integrate subtasks)", self.ok("next"))

    def test_subtasks_wait_for_the_dependencies_of_their_parents(self):
        self.make_plan([
            task("T-001"),
            task("T-002", depends_on=["T-001"]),
            task("T-002.1", parent_id="T-002"),
            task("T-002.1.1", parent_id="T-002.1"),
        ])
        self.assertEqual(self.ok("next"), "T-001  [low/low]  T-001 title\n")
        self.ok("set", "T-001", "done", "--evidence", "ok")
        self.assertEqual(self.ok("next"), "T-002.1.1  [low/low]  T-002.1.1 title\n")


class ShowTest(PlanTestCase):
    def test_task_with_status_links_and_log(self):
        self.make_plan()
        self.ok("set", "T-001", "in_progress", "--owner", "worker")
        self.ok("log", "check", "subject=unit", "result=pass", 'tasks=["T-001"]')
        self.ok("log", "check", "subject=other", "result=pass", 'tasks=["T-002"]')
        self.ok("log", "finding", "id=F-1", "status=open", "summary=broken", "tasks=T-001")
        self.ok("log", "finding", "id=F-1", "status=resolved", "fix=patched")
        out = self.ok("show", "T-001")
        self.assertIn("# T-001 (tasks/01-core.json)", out)
        self.assertIn('"outcome": "it works"', out)
        self.assertIn('status: {"status": "in_progress", "owner": "worker"', out)
        self.assertIn("needed by: T-002", out)
        log = [json.loads(line) for line in out.split("log:\n", 1)[1].splitlines()]
        self.assertEqual([r["type"] for r in log], ["task", "check", "finding"])
        self.assertEqual(log[1]["subject"], "unit")
        self.assertEqual(log[2]["status"], "resolved")
        self.assertEqual(log[2]["summary"], "broken")
        self.assertEqual(log[2]["fix"], "patched")

    def test_dependencies_and_subtasks_with_their_status(self):
        self.make_plan(hierarchy_tasks() + [task("T-003", depends_on=["T-002"])])
        self.ok("set", "T-001.1", "in_progress")
        self.assertIn("subtasks: T-001.1 (in_progress), T-001.2 (pending)", self.ok("show", "T-001"))
        self.assertIn("depends on: T-002 (pending)", self.ok("show", "T-003"))

    def test_task_without_progress_entry_is_pending(self):
        self.make_plan()
        self.edit_progress(lambda p: p["tasks"].pop("T-002"))
        self.assertIn('status: {"status": "pending"}', self.ok("show", "T-002"))

    def test_unknown_task_exits_1(self):
        self.make_plan()
        result = self.run_plan("show", "T-404")
        self.assertExit(result, 1)
        self.assertIn("unknown task T-404", result.stderr)


class SetTest(PlanTestCase):
    def test_start_updates_progress_and_logs_the_change(self):
        self.make_plan()
        self.assertEqual(self.ok("set", "T-001", "in_progress", "--owner", "worker"),
                         "T-001: pending -> in_progress\n")
        progress = self.progress()
        entry = progress["tasks"]["T-001"]
        self.assertEqual((entry["status"], entry["owner"], entry["blockers"]), ("in_progress", "worker", []))
        self.assertRegex(entry["updated_at"], TIMESTAMP)
        self.assertEqual(progress["updated_at"], entry["updated_at"])
        self.assertEqual(progress["implementation_status"], "in_progress")
        self.assertEqual(self.log(), [{"at": entry["updated_at"], "type": "task", "id": "T-001",
                                       "status": "in_progress", "from": "pending"}])

    def test_implementation_status_moves_only_from_not_started(self):
        self.make_plan()
        self.edit_progress(lambda p: p.update(implementation_status="blocked"))
        self.ok("set", "T-001", "in_progress")
        self.assertEqual(self.progress()["implementation_status"], "blocked")

    def test_owner_is_kept_changed_and_cleared(self):
        self.make_plan()
        self.ok("set", "T-001", "in_progress", "--owner", "Žofie")
        self.assertIn("Žofie", (self.plan / "progress.json").read_text(encoding="utf-8"))
        self.ok("set", "T-001", "blocked", "--blocker", "Q-001")
        self.assertEqual(self.progress()["tasks"]["T-001"]["owner"], "Žofie")
        self.ok("set", "T-001", "in_progress", "--owner", "")
        self.assertIsNone(self.progress()["tasks"]["T-001"]["owner"])

    def test_done_needs_evidence(self):
        self.make_plan()
        self.refused("set", "T-001", "done", message="done needs --evidence")
        self.ok("set", "T-001", "done", "--evidence", "AC met, tests pass")
        record = self.log()[-1]
        self.assertEqual((record["status"], record["from"], record["evidence"]),
                         ("done", "pending", "AC met, tests pass"))

    def test_done_needs_done_dependencies(self):
        self.make_plan()
        self.refused("set", "T-002", "done", "--evidence", "ok", message="dependencies not done: T-001")
        self.ok("set", "T-001", "cancelled", "--reason", "dropped")
        self.refused("set", "T-002", "done", "--evidence", "ok", message="dependencies not done: T-001")

    def test_done_needs_closed_subtasks(self):
        self.make_plan(hierarchy_tasks())
        self.refused("set", "T-001", "done", "--evidence", "ok", message="subtasks not finished: T-001.1, T-001.2")
        self.ok("set", "T-001.1", "done", "--evidence", "ok")
        self.ok("set", "T-001.2", "cancelled", "--reason", "dropped")
        self.ok("set", "T-001", "done", "--evidence", "integrated")

    def test_cancel_needs_reason_and_warns_about_consumers(self):
        self.make_plan()
        self.refused("set", "T-001", "cancelled", message="cancelled needs --reason")
        out = self.ok("set", "T-001", "cancelled", "--reason", "out of scope")
        self.assertIn("warning: T-002 depend on this task", out)
        self.assertEqual(self.log()[-1]["reason"], "out of scope")
        self.assertNotIn("warning", self.ok("set", "T-002", "cancelled", "--reason", "follows T-001"))

    def test_blockers(self):
        self.make_plan()
        self.refused("set", "T-001", "blocked", message="blocked needs --blocker")
        self.ok("set", "T-001", "blocked", "--blocker", "Q-001")
        self.assertEqual(self.log()[-1]["blockers"], ["Q-001"])
        self.ok("set", "T-001", "blocked", "--blocker", "Q-002", "--blocker", "Q-001")
        self.assertEqual(self.progress()["tasks"]["T-001"]["blockers"], ["Q-001", "Q-002"])
        # A task that already has blockers may be set blocked again without a new one.
        self.ok("set", "T-001", "blocked")
        self.assertEqual(self.progress()["tasks"]["T-001"]["blockers"], ["Q-001", "Q-002"])
        self.ok("set", "T-001", "in_progress")
        self.assertEqual(self.progress()["tasks"]["T-001"]["blockers"], [])
        self.assertEqual(self.log()[-1]["from"], "blocked")

    def test_unknown_task_is_refused(self):
        self.make_plan()
        self.refused("set", "T-404", "in_progress", message="unknown task T-404")

    def test_writes_leave_valid_json_and_no_temporary_files(self):
        self.make_plan()
        for args in (("T-001", "in_progress"), ("T-001", "done", "--evidence", "ok"), ("T-002", "in_progress")):
            self.ok("set", *args)
            text = (self.plan / "progress.json").read_text(encoding="utf-8")
            self.assertTrue(text.endswith("}\n"))
            json.loads(text)
        self.assertEqual(sorted(p.name for p in self.plan.iterdir()),
                         ["chapters", "log.jsonl", "prd.md", "progress.json", "tasks"])
        self.assertEqual(len(self.log()), 3)


class LogTest(PlanTestCase):
    def test_every_record_type(self):
        self.make_plan()
        cases = [
            ("check", ["subject=make test", "result=pass", "revision=abc123"]),
            ("finding", ["id=F-1", "status=open", "severity=high"]),
            ("validation_plan", ["pass=V1", "mode=single", 'cells=[{"id": "ALL", "focus": "whole plan"}]']),
            ("validation", ['validators=["V-1"]', "result=ok", "pass=V1", "cell=ALL", "coverage=covered"]),
            ("checkpoint", ["commit=abc123", "milestone=backend"]),
            ("note", ["text=resume from T-002"]),
        ]
        for kind, fields in cases:
            with self.subTest(kind=kind):
                out = self.ok("log", kind, *fields)
                record = self.log()[-1]
                self.assertEqual(out, "logged " + json.dumps(record, ensure_ascii=False) + "\n")
                self.assertEqual(record["type"], kind)
                self.assertRegex(record["at"], TIMESTAMP)
        self.assertEqual(len(self.log()), len(cases))
        self.assertEqual(self.log()[0]["subject"], "make test")
        self.assertEqual(self.log()[2]["cells"], [{"id": "ALL", "focus": "whole plan"}])

    def test_values_are_parsed_as_json_when_possible(self):
        self.make_plan()
        self.ok("log", "note", "text=a=b", "count=3", "ratio=0.5", "flag=true", "none=null", 'tasks=["T-001"]',
                'meta={"k": 1}', "revision=abc123", "empty=", "quoted=\"42\"")
        record = self.log()[-1]
        self.assertEqual(record["text"], "a=b")
        self.assertEqual(record["count"], 3)
        self.assertEqual(record["ratio"], 0.5)
        self.assertIs(record["flag"], True)
        self.assertIsNone(record["none"])
        self.assertEqual(record["tasks"], ["T-001"])
        self.assertEqual(record["meta"], {"k": 1})
        self.assertEqual(record["revision"], "abc123")
        self.assertEqual(record["empty"], "")
        self.assertEqual(record["quoted"], "42")

    def test_required_fields(self):
        self.make_plan()
        for kind, fields, message in (
            ("check", ["subject=x"], "check needs: result"),
            ("finding", ["id=F-1"], "finding needs: status"),
            ("validation_plan", ["pass=V1"], "validation_plan needs: mode, cells"),
            ("validation", ["result=ok"], "validation needs: validators"),
            ("checkpoint", [], "checkpoint needs: commit"),
            ("note", [], "note needs: text"),
        ):
            with self.subTest(kind=kind):
                self.refused("log", kind, *fields, message=message)

    def test_finding_status_must_be_known(self):
        self.make_plan()
        self.refused("log", "finding", "id=F-1", "status=fixed", message="finding status must be one of")
        for status in ("open", "resolved", "rejected", "awaiting_decision"):
            self.ok("log", "finding", "id=F-1", f"status={status}")

    def test_appends_without_rewriting(self):
        self.make_plan()
        self.ok("log", "note", "text=first")
        before = (self.plan / "log.jsonl").read_bytes()
        self.ok("log", "note", "text=second")
        after = (self.plan / "log.jsonl").read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual([r["text"] for r in self.log()], ["first", "second"])

    def test_fields_cannot_set_the_type_or_time(self):
        self.make_plan()
        for field in ("type=check", "at=2000-01-01T00:00:00Z"):
            with self.subTest(field=field):
                result = self.run_plan("log", "note", "text=x", field)
                self.assertExit(result, 2)
                self.assertIn("is set by the tool", result.stderr)
        self.assertEqual(self.log(), [])


class FindingsTest(PlanTestCase):
    def test_empty(self):
        self.make_plan()
        self.assertEqual(self.ok("findings"), "no unresolved findings\n")
        self.assertEqual(self.ok("findings", "--all"), "no findings\n")

    def test_finding_id_must_be_a_string(self):
        self.make_plan()
        result = self.run_plan("log", "finding", 'id=["F-1"]', "status=open")
        self.assertExit(result, 1)
        self.assertIn("finding id must be a string", result.stderr)
        self.write_log([
            {"at": "2026-01-01T00:00:00Z", "type": "finding", "status": "open"},
            {"at": "2026-01-01T00:00:00Z", "type": "finding", "id": ["F-1"], "status": "open"},
        ])
        self.assertEqual(self.ok("findings"), "no unresolved findings\n")
        self.ok("status")
        self.assertValidateError("log.jsonl record 2: finding id must be a string")

    def test_records_merge_field_by_field(self):
        self.make_plan()
        self.ok("log", "finding", "id=F-1", "status=open", "severity=high", "summary=broken")
        self.ok("log", "finding", "id=F-2", "status=awaiting_decision", "summary=ask")
        self.ok("log", "finding", "id=F-3", "status=open")
        self.ok("log", "finding", "id=F-1", "status=resolved", "fix=patched")
        self.ok("log", "finding", "id=F-3", "status=rejected", "reason=by design")

        unresolved = [json.loads(line) for line in self.ok("findings").splitlines()]
        self.assertEqual([f["id"] for f in unresolved], ["F-2"])
        self.assertNotIn("type", unresolved[0])

        merged = {f["id"]: f for f in map(json.loads, self.ok("findings", "--all").splitlines())}
        self.assertEqual(list(merged), ["F-1", "F-2", "F-3"])
        self.assertEqual({k: merged["F-1"][k] for k in ("status", "severity", "summary", "fix")},
                         {"status": "resolved", "severity": "high", "summary": "broken", "fix": "patched"})
        self.assertEqual(merged["F-3"]["status"], "rejected")
        self.assertEqual(merged["F-1"]["at"], self.log()[3]["at"])


class ValidationsTest(PlanTestCase):
    def log_cell(self, cell: str, coverage: str, *extra: str, pass_id: str = "V1") -> None:
        self.ok("log", "validation", f"pass={pass_id}", f"cell={cell}", f'validators=["V-{cell}"]',
                f"result=ok-{cell}", f"coverage={coverage}", *extra)

    def test_no_pass(self):
        self.make_plan()
        self.assertEqual(self.ok("validations"), "no validation pass recorded (log validation_plan)\n")

    def test_validation_plan_is_checked(self):
        self.make_plan()
        self.ok("log", "validation_plan", "pass=V1", "mode=areas", f"cells={CELLS}")
        for fields, message in (
            (["pass=V1", "mode=recheck", 'cells=[{"id": "A1"}]'], "validation pass V1 already exists"),
            (["pass=V2", "mode=quick", 'cells=[{"id": "A1"}]'], "validation mode must be one of"),
            (["pass=V2", "mode=focus", "cells=[]"], "cells must be a non-empty JSON list"),
            (["pass=V2", "mode=focus", "cells=A1,A2"], "cells must be a non-empty JSON list"),
            (["pass=V2", "mode=focus", 'cells=[{"focus": "x"}]'], "every cell needs a string id"),
            (["pass=V2", "mode=focus", 'cells=[{"id": "A1"}, {"id": "A1"}]'], "duplicate cell A1"),
            (["pass=V2", "mode=focus", 'cells=[{"id": "A1", "tasks": ["T-404"]}]'], "cell A1: unknown task 'T-404'"),
            (["pass=V2", "mode=focus", 'cells=[{"id": "A1", "chapters": ["chapters/none.md#x"]}]'],
             "cell A1: missing chapter chapters/none.md#x"),
            (["pass=2", "mode=focus", 'cells=[{"id": "A1"}]'], "pass must be a string"),
        ):
            with self.subTest(fields=fields):
                self.refused("log", "validation_plan", *fields, message=message)
        for mode in ("single", "focus", "recheck"):
            self.ok("log", "validation_plan", f"pass=V-{mode}", f"mode={mode}",
                    'cells=[{"id": "A1", "chapters": ["chapters/01-core.md#core"], "tasks": ["T-001"]}]')

    def test_validation_is_checked(self):
        self.make_plan()
        self.ok("log", "validation_plan", "pass=V1", "mode=areas", f"cells={CELLS}")
        base = ['validators=["V"]', "result=ok"]
        for fields, message in (
            (["pass=V9", "cell=A1", "coverage=covered"], "unknown validation pass 'V9'"),
            (["cell=A1", "coverage=covered"], "unknown validation pass None"),
            (["pass=V1", "cell=Z9", "coverage=covered"], "unknown cell 'Z9' in pass V1"),
            (["pass=V1", "cell=A1", "coverage=done"], "coverage must be one of covered, partial"),
            (["pass=V1", "cell=A1"], "coverage must be one of covered, partial"),
            (["pass=V1", "cell=A1", "coverage=partial"], "partial coverage needs unchecked"),
        ):
            with self.subTest(fields=fields):
                self.refused("log", "validation", *base, *fields, message=message)
        # A whole-plan validation without cells stays possible.
        self.ok("log", "validation", *base)

    def test_cell_states_follow_the_last_record(self):
        self.make_plan()
        self.ok("log", "validation_plan", "pass=V1", "mode=areas", f"cells={CELLS}")
        self.assertEqual(self.ok("validations").splitlines(), [
            "pass V1 (areas)",
            "A1  [pending]  data",
            "A2  [pending]  ui",
            "INT  [waiting]  integration",
            "to brief: A1, A2",
        ])

        self.log_cell("A1", "covered")
        self.log_cell("A2", "partial", 'unchecked=["mobile layout"]')
        self.assertEqual(self.ok("validations").splitlines(), [
            "pass V1 (areas)",
            "A1  [covered]  data  result: ok-A1",
            'A2  [partial]  ui  unchecked: ["mobile layout"]',
            "INT  [waiting]  integration",
            "to brief: A2",
        ])

        # The partial cell is finished in the same pass; then the integration cell is due.
        self.log_cell("A2", "covered")
        out = self.ok("validations").splitlines()
        self.assertIn("A2  [covered]  ui  result: ok-A2", out)
        self.assertIn("INT  [pending]  integration", out)
        self.assertEqual(out[-1], "to brief: INT")

        self.log_cell("INT", "covered")
        self.assertEqual(self.ok("validations").splitlines()[-1], "to brief: -")
        self.assertEqual(self.ok("validations", "--open"), "every cell of every pass is covered\n")

    def test_pass_selection_and_open_cells_across_passes(self):
        self.make_plan()
        self.ok("log", "validation_plan", "pass=V1", "mode=single", 'cells=[{"id": "ALL", "focus": "whole"}]')
        self.ok("log", "validation_plan", "pass=V2", "mode=recheck", 'cells=[{"id": "ALL", "focus": "fixes"}]')
        self.log_cell("ALL", "covered", pass_id="V2")

        self.assertTrue(self.ok("validations").startswith("pass V2 (recheck)\n"))
        self.assertIn("ALL  [pending]  whole", self.ok("validations", "--pass", "V1"))
        # A later pass never closes a cell of an earlier one.
        self.assertEqual(self.ok("validations", "--open"), "V1/ALL  [pending]  whole\n")

        result = self.run_plan("validations", "--pass", "V9")
        self.assertExit(result, 1)
        self.assertIn("unknown validation pass V9", result.stderr)

    def test_partial_cell_is_open(self):
        self.make_plan()
        self.ok("log", "validation_plan", "pass=V1", "mode=single", 'cells=[{"id": "ALL", "focus": "whole"}]')
        self.log_cell("ALL", "partial", 'unchecked=["permissions"]')
        self.assertEqual(self.ok("validations", "--open"), "V1/ALL  [partial]  whole\n")


class HelpersTest(unittest.TestCase):
    """Pure helpers, tested directly where the CLI would only show them indirectly."""

    @classmethod
    def setUpClass(cls):
        cls.plan = load_plan_module()

    def test_find_cycle(self):
        find_cycle = self.plan.find_cycle
        self.assertIsNone(find_cycle({}))
        self.assertIsNone(find_cycle({"a": ["b"], "b": ["c"], "c": []}))
        self.assertIsNone(find_cycle({"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": []}))
        self.assertEqual(find_cycle({"a": ["a"]}), ["a", "a"])
        self.assertEqual(find_cycle({"a": ["b"], "b": ["a"]}), ["a", "b", "a"])
        self.assertEqual(find_cycle({"x": ["a"], "a": ["b"], "b": ["c"], "c": ["a"]}), ["a", "b", "c", "a"])

    def test_write_json_keeps_the_old_file_when_writing_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "progress.json"
            path.write_text('{"old": true}\n')
            with self.assertRaises(TypeError):
                self.plan.write_json(path, {"new": object()})
            self.assertEqual(path.read_text(), '{"old": true}\n')
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["progress.json"])


if __name__ == "__main__":
    unittest.main()
