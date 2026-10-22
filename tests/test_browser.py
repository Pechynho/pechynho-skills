"""Tests of base/shared/browser.py, the tool that tracks a click-through pass.

The tool runs as a subprocess against a temporary testing folder. `run` executes real scenario scripts
with node against the fake Playwright in tests/fixtures/fake-playwright, which logs its browser events
to FAKE_PW_LOG and serves the pages described in FAKE_PW_SITE.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path

from tests.helpers import SHARED, ToolTestCase, load_module, read_json, read_jsonl, run_tool, write_json

BROWSER = SHARED / "browser.py"
HARNESS = SHARED / "browser-harness.mjs"
FAKE = Path(__file__).resolve().parent / "fixtures" / "fake-playwright"
NODE = shutil.which("node")

PASS = "await step('open', () => page.goto(url('/ok')));\nawait check('greeting', page.getByText('Hello'));"
FAIL_CHECK = "await step('open', () => page.goto(url('/ok')));\nawait step('verify', () => check('saved', page.getByText('Saved'), { timeout: 50 }));"
THROW = "await step('open', () => page.goto(url('/ok')));\nawait step('submit', () => { throw new Error('button disabled'); });"
SHOT = "await step('open', () => page.goto(url('/ok')));\nawait shot('home');"
HANG = "await step('open', () => page.goto(url('/ok')));\nawait step('hang', () => new Promise((r) => setTimeout(r, 60000)));"
SLOW = "await page.goto(url('/ok'));\nawait page.waitForTimeout(700);"
SITE = {"/ok": {"title": "Home", "text": ["Hello"]}}


def load_browser_module():
    return load_module(BROWSER, "browser_tool")


def alive(pid: int) -> bool:
    """Whether a process runs; a zombie counts as gone."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        return stat.rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return sys.platform != "linux"


def max_overlap(events: list[dict]) -> int:
    """The largest number of browsers open at once, from the launch and close events of the fake."""
    points = sorted([(e["t"], 1) for e in events if e["event"] == "launch"]
                    + [(e["t"], -1) for e in events if e["event"] == "close"], key=lambda p: (p[0], p[1]))
    current = peak = 0
    for _, delta in points:
        current += delta
        peak = max(peak, current)
    return peak


class BrowserCase(ToolTestCase):
    """A testing folder in self.dir; self.site is the fake application served to the scenario scripts."""

    def setUp(self) -> None:
        super().setUp()
        self.dir = self.tmp / "pw"
        self.site = dict(SITE)
        self.events = self.tmp / "events.jsonl"

    def env(self, extra: dict | None = None) -> dict:
        site = self.tmp / "site.json"
        write_json(site, self.site)
        return {"FAKE_PW_SITE": str(site), "FAKE_PW_LOG": str(self.events), **(extra or {})}

    def bt(self, *args, env: dict | None = None, cwd: Path | None = None, timeout: float = 60):
        return run_tool(BROWSER, self.dir, *args, cwd=cwd or self.tmp, env=self.env(env), timeout=timeout)

    def ok(self, *args, **kw):
        result = self.bt(*args, **kw)
        self.assertOk(result)
        return result

    def refused(self, *args, pattern: str | None = None, **kw):
        result = self.bt(*args, **kw)
        self.assertExit(result, 1)
        self.assertIn("refused:", result.stderr)
        if pattern:
            self.assertRegex(result.stderr, pattern)
        return result

    def init(self, *extra: str) -> None:
        self.ok("init", "--scope", "demo", "--url", "http://app.test", "--no-repo", "--playwright", str(FAKE),
                "--timeout", "30", *extra)

    def state(self) -> dict:
        return read_json(self.dir / "testing.json")

    def save_state(self, state: dict) -> None:
        write_json(self.dir / "testing.json", state)

    def log(self, type_: str | None = None) -> list[dict]:
        records = read_jsonl(self.dir / "log.jsonl")
        return [r for r in records if type_ is None or r["type"] == type_]

    def browser_events(self) -> list[dict]:
        return read_jsonl(self.events) if self.events.exists() else []

    def script(self, sid: str, body: str, options: str | None = None) -> Path:
        path = self.dir / "scenarios" / f"{sid}.mjs"
        path.write_text("import { run } from '../harness.mjs';\n"
                        "await run(async ({ page, url, step, check, shot, note }) => {\n"
                        f"{body}\n}}{', ' + options if options else ''});\n")
        return path

    def scenario(self, sid: str, group: str = "g1", kind: str = "functional", *extra: str) -> None:
        self.ok("scenario", sid, "--title", f"Scenario {sid}", "--group", group, "--kind", kind, *extra)

    def ready(self, sid: str, body: str = PASS, group: str = "g1", kind: str = "functional") -> None:
        """A scenario whose script ran once and was confirmed by its author."""
        self.scenario(sid, group, kind)
        self.script(sid, body)
        self.ok("run", sid)
        self.ok("ready", sid)

    def sc(self, sid: str) -> dict:
        return self.state()["scenarios"][sid]


@unittest.skipUnless(NODE, "node is required")
class InitTest(BrowserCase):
    def test_init_creates_the_folder_with_defaults(self):
        result = self.bt("init", "--scope", "orders", "--url", "http://app.test", "--no-repo")
        self.assertOk(result)
        self.assertIn("initialized", result.stdout)
        self.assertIn("no git", result.stdout)
        self.assertIn("warning: no repository", result.stdout)
        self.assertRegex(result.stdout, r"node v\d+")
        for folder in ("scenarios", "results", "findings"):
            self.assertTrue((self.dir / folder).is_dir(), folder)
        self.assertEqual((self.dir / "harness.mjs").read_bytes(), HARNESS.read_bytes())
        s = self.state()
        self.assertEqual(s["schema_version"], 1)
        self.assertEqual(s["scope"], "orders")
        self.assertEqual(s["revision"]["repo"], None)
        self.assertEqual(s["config"], {
            "url": "http://app.test", "max_browsers": 2, "timeout": 180,
            "viewports": {"desktop": {"width": 1440, "height": 900, "mobile": False},
                          "mobile": {"width": 390, "height": 844, "mobile": True}},
            "playwright_from": [], "browser": "chromium", "diff_threshold": 0.0, "diff_tolerance": 24})
        self.assertEqual((s["scenarios"], s["findings"], s["assignments"], s["runs"]), ({}, {}, {}, []))
        [record] = self.log()
        self.assertEqual(record["type"], "init")
        self.assertIn("at", record)

    def test_init_options(self):
        self.ok("init", "--scope", "s", "--url", "http://x", "--no-repo", "--max-browsers", "3", "--timeout", "9",
                "--viewport", "wide=1920x1080", "phone=375x667:mobile", "--playwright", str(FAKE), "--browser", "webkit")
        c = self.state()["config"]
        self.assertEqual((c["max_browsers"], c["timeout"], c["browser"]), (3, 9, "webkit"))
        self.assertEqual(list(c["viewports"]), ["wide", "phone"], "the first viewport stays the primary one")
        self.assertEqual(c["viewports"]["phone"], {"width": 375, "height": 667, "mobile": True})
        self.assertEqual(c["playwright_from"], [str(FAKE.resolve())])

    def test_init_refuses_twice(self):
        self.init()
        self.refused("init", "--scope", "demo", "--url", "http://x", "--no-repo", pattern="already exists")

    def test_init_needs_a_repository_unless_no_repo(self):
        self.refused("init", "--scope", "demo", "--url", "http://x", pattern="not inside a git repository")
        self.assertFalse((self.dir / "testing.json").exists())

    def test_init_refuses_a_bad_viewport(self):
        self.refused("init", "--scope", "demo", "--url", "http://x", "--no-repo", "--viewport", "desktop=wide",
                     pattern="NAME=WIDTHxHEIGHT")

    def test_init_validates_limits_like_config(self):
        self.refused("init", "--scope", "demo", "--url", "http://x", "--no-repo", "--max-browsers", "0")
        self.refused("init", "--scope", "demo", "--url", "http://x", "--no-repo", "--timeout", "0")

    def test_init_records_the_revision_of_a_git_repository(self):
        repo = make_repo(self.tmp / "repo")
        result = self.bt("init", "--scope", "demo", "--url", "http://x", "--repo", str(repo), "--base", "HEAD")
        self.assertOk(result)
        rev = self.state()["revision"]
        head = git(repo, "rev-parse", "HEAD")
        self.assertEqual(rev["repo"], str(repo.resolve()))
        self.assertEqual(rev["head"], "HEAD")
        self.assertEqual(rev["head_sha"], head)
        self.assertEqual(rev["base_sha"], head)
        self.assertEqual(rev["working_tree"], False)
        self.assertEqual(rev["fingerprint"], head[:12])
        self.assertIn(head[:12], result.stdout)


@unittest.skipUnless(NODE, "node is required")
class UsageTest(BrowserCase):
    def test_commands_need_a_testing_folder(self):
        result = self.bt("status")
        self.assertExit(result, 2)
        self.assertIn("missing testing.json", result.stderr)

    def test_wrong_usage_exits_2(self):
        self.init()
        self.assertExit(self.bt("bogus"), 2)
        self.assertExit(self.bt("scenario", "S1", "--kind", "weird"), 2)
        self.assertExit(self.bt("set", "S1", "failed", "--reason", "x"), 2)
        self.assertExit(self.bt("run", "--todo", "--all"), 2)
        self.assertExit(self.bt("log", "bogus", "text=x"), 2)
        self.assertExit(self.bt("resolve", "F1", "closed", "--reason", "x"), 2)
        self.assertExit(self.bt("finding", "F1", "--kind", "functional_bug", "--title", "t"), 2)


@unittest.skipUnless(NODE, "node is required")
class ConfigTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_config_without_options_prints_the_settings(self):
        result = self.ok("config")
        self.assertEqual(json.loads(result.stdout), self.state()["config"])

    def test_config_changes_and_logs_settings(self):
        self.ok("config", "--url", "http://other", "--max-browsers", "4", "--timeout", "5", "--diff-threshold", "0.01",
                "--diff-tolerance", "0", "--browser", "firefox", "--viewport", "desktop=1280x800")
        c = self.state()["config"]
        self.assertEqual((c["url"], c["max_browsers"], c["timeout"], c["diff_threshold"], c["diff_tolerance"], c["browser"]),
                         ("http://other", 4, 5, 0.01, 0, "firefox"))
        self.assertEqual(c["viewports"], {"desktop": {"width": 1280, "height": 800, "mobile": False}})
        self.assertEqual(self.log("config")[-1]["max_browsers"], 4)

    def test_config_refuses_invalid_values(self):
        before = self.state()["config"]
        self.refused("config", "--max-browsers", "0", pattern="max_browsers")
        self.refused("config", "--timeout", "0", pattern="timeout")
        self.refused("config", "--diff-threshold", "1.5", pattern="diff_threshold")
        self.refused("config", "--diff-threshold", "-0.1", pattern="diff_threshold")
        self.refused("config", "--diff-tolerance", "256", pattern="diff_tolerance")
        self.refused("config", "--viewport", "bad")
        self.assertEqual(self.state()["config"], before)

    def test_config_refuses_to_drop_a_viewport_a_scenario_names(self):
        self.scenario("S1", "g1", "visual", "--viewports", "mobile")
        self.refused("config", "--viewport", "desktop=1440x900", pattern="mobile")
        self.ok("config", "--viewport", "desktop=1440x900", "mobile=400x800:mobile")


@unittest.skipUnless(NODE, "node is required")
class HarnessTest(BrowserCase):
    def test_harness_restores_the_tool_harness(self):
        self.init()
        (self.dir / "harness.mjs").write_text("// old\n")
        result = self.ok("validate")
        self.assertIn("warning: harness.mjs differs", result.stdout)
        self.ok("harness")
        self.assertEqual((self.dir / "harness.mjs").read_bytes(), HARNESS.read_bytes())
        self.assertNotIn("differs", self.ok("validate").stdout)
        self.assertEqual(len(self.log("harness")), 1)


@unittest.skipUnless(NODE, "node is required")
class ScenarioTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_add_with_defaults_and_update(self):
        result = self.ok("scenario", "S1", "--title", "Add order", "--group", "orders")
        self.assertIn("S1 added", result.stdout)
        self.assertIn("viewports=desktop (default)", result.stdout, "a functional scenario uses the primary viewport")
        sc = self.sc("S1")
        self.assertEqual((sc["kind"], sc["priority"], sc["outcome"], sc["script"], sc["viewports"]),
                         ("functional", "medium", "pending", "scenarios/S1.mjs", None))
        result = self.ok("scenario", "S1", "--kind", "visual", "--priority", "high", "--data", "order #1")
        self.assertIn("S1 updated", result.stdout)
        self.assertIn("viewports=desktop,mobile (default)", result.stdout, "a visual scenario uses all viewports")
        sc = self.sc("S1")
        self.assertEqual((sc["title"], sc["group"], sc["kind"], sc["priority"], sc["data"]),
                         ("Add order", "orders", "visual", "high", "order #1"))
        self.ok("scenario", "S1", "--viewports", "mobile", "--role", "admin", "--script", "scenarios/custom.mjs")
        sc = self.sc("S1")
        self.assertEqual((sc["viewports"], sc["role"], sc["script"]), (["mobile"], "admin", "scenarios/custom.mjs"))
        self.assertEqual([r["action"] for r in self.log("scenario")], ["added", "updated", "updated"])

    def test_scenario_validation(self):
        self.refused("scenario", "S1", "--title", "No group", pattern="needs a title and a group")
        self.refused("scenario", "1S", "--title", "T", "--group", "g", pattern="starting with a letter")
        self.refused("scenario", "S1", "--title", "T", "--group", "bad group", pattern="group")
        self.refused("scenario", "S1", "--title", "T", "--group", "g", "--viewports", "tablet", pattern="unknown viewport tablet")
        self.assertEqual(self.state()["scenarios"], {})

    def test_scenarios_file_loads_a_list_or_an_object(self):
        write_json(self.tmp / "list.json", [
            {"id": "S1", "title": "One", "group": "g1"},
            {"id": "S2", "title": "Two", "group": "g2", "kind": "both", "viewports": ["desktop"], "outcome": "passed"},
        ])
        result = self.ok("scenarios", self.tmp / "list.json")
        self.assertIn("2 added, 0 updated; groups: g1, g2", result.stdout)
        self.assertEqual(self.sc("S2")["outcome"], "pending", "an outcome cannot be loaded from the file")
        write_json(self.tmp / "obj.json", {"scenarios": [{"id": "S1", "priority": "low"}, {"id": "S3", "title": "Three", "group": "g1"}]})
        self.assertIn("1 added, 1 updated", self.ok("scenarios", self.tmp / "obj.json").stdout)
        self.assertEqual(self.sc("S1")["priority"], "low")
        self.assertEqual(self.sc("S1")["title"], "One")

    def test_scenarios_file_is_all_or_nothing(self):
        write_json(self.tmp / "bad.json", [{"id": "S1", "title": "One", "group": "g1"}, {"id": "S2", "title": "Two"}])
        self.refused("scenarios", self.tmp / "bad.json", pattern="S2")
        self.assertEqual(self.state()["scenarios"], {})
        write_json(self.tmp / "kind.json", [{"id": "S1", "title": "One", "group": "g1", "kind": "weird"}])
        self.refused("scenarios", self.tmp / "kind.json", pattern="kind")
        write_json(self.tmp / "noid.json", [{"title": "One", "group": "g1"}])
        self.refused("scenarios", self.tmp / "noid.json")
        write_json(self.tmp / "dict.json", {"items": []})
        self.refused("scenarios", self.tmp / "dict.json", pattern="JSON list")
        (self.tmp / "broken.json").write_text("[{")
        self.refused("scenarios", self.tmp / "broken.json", pattern="invalid JSON")
        self.refused("scenarios", self.tmp / "missing.json", pattern="missing")
        self.assertEqual(self.state()["scenarios"], {})


@unittest.skipUnless(NODE, "node is required")
class ReadyTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_ready_needs_a_completed_run_of_the_current_script(self):
        self.scenario("S1")
        self.refused("ready", "S1", pattern="does not exist")
        self.script("S1", PASS)
        self.refused("ready", "S1", pattern="run the current script first")
        self.ok("run", "S1")
        self.assertIn("ready: S1", self.ok("ready", "S1").stdout)
        self.assertIn("1 ready", self.ok("status").stdout)
        # Changing the file makes it written again.
        self.script("S1", PASS + "\n// changed")
        self.assertIn("1 written", self.ok("status").stdout)
        self.refused("ready", "S1", pattern="run the current script first")

    def test_a_failed_run_can_be_confirmed_but_not_a_crash(self):
        self.scenario("S1")
        self.script("S1", FAIL_CHECK)
        self.ok("run", "S1")
        self.ok("ready", "S1")
        self.scenario("S2")
        (self.dir / "scenarios" / "S2.mjs").write_text("process.exit(3);\n")
        self.ok("run", "S2")
        self.assertEqual(self.sc("S2")["last_run"]["status"], "crashed")
        self.refused("ready", "S2", pattern="not crashed")

    def test_ready_is_all_or_nothing(self):
        self.ready("S1")
        self.scenario("S2")
        self.script("S2", PASS)
        self.refused("ready", "S1", "S2")
        self.refused("ready", "S1", "NOPE", pattern="unknown scenario NOPE")


@unittest.skipUnless(NODE, "node is required")
class RunTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_a_passing_scenario(self):
        self.scenario("S1")
        self.script("S1", PASS)
        result = self.ok("run", "S1")
        self.assertIn("run r001: 1 scenario(s) in 1 group(s), at most 2 browser(s)", result.stdout)
        self.assertRegex(result.stdout, r"(?m)^S1\s+passed\s+[\d.]+s\s+checks 1/1$")
        self.assertIn("summary: 1 passed", result.stdout)
        sc = self.sc("S1")
        self.assertEqual(sc["outcome"], "passed")
        self.assertIsNone(sc["running"])
        run = sc["last_run"]
        self.assertEqual((run["run"], run["status"], run["dir"], run["failed_checks"], run["error"], run["attempts"], run["cleaned"]),
                         ("r001", "passed", "results/S1/r001", [], None, None, None))
        self.assertEqual(run["script_hash"], hashlib.sha256((self.dir / "scenarios/S1.mjs").read_bytes()).hexdigest()[:16])
        folder = self.dir / run["dir"]
        self.assertEqual(read_json(folder / "result.json")["status"], "passed")
        self.assertTrue((folder / "output.log").is_file())
        pids = read_json(folder / "pids.json")
        self.assertFalse(alive(pids["browser"]), "the browser was closed")
        self.assertEqual(self.state()["runs"][0]["scenarios"], ["S1"])
        self.assertEqual([r["type"] for r in self.log()][-2:], ["run_started", "run"])
        # The harness got the settings of the folder.
        launch = [e for e in self.browser_events() if e["event"] == "launch"]
        self.assertEqual(launch[0]["scenario"], "S1")
        self.assertEqual(launch[0]["browser"], "chromium")
        goto = [e for e in self.browser_events() if e["event"] == "goto"]
        self.assertEqual(goto[0]["url"], "http://app.test/ok")
        self.assertEqual(read_json(folder / "result.json")["viewports"],
                         [{"name": "desktop", "width": 1440, "height": 900, "mobile": False}])
        # Run IDs count up.
        self.assertIn("run r002", self.ok("run", "S1").stdout)
        self.assertEqual(self.sc("S1")["last_run"]["dir"], "results/S1/r002")

    def test_a_failing_check(self):
        self.scenario("S1")
        self.script("S1", FAIL_CHECK)
        result = self.ok("run", "S1")
        self.assertRegex(result.stdout, r"(?m)^S1\s+FAILED\s+.*checks 0/1\s+failed: saved")
        self.assertIn("summary: 1 failing; triage: S1", result.stdout)
        sc = self.sc("S1")
        self.assertEqual(sc["outcome"], "failing")
        self.assertEqual(sc["last_run"]["failed_checks"], ["saved"])
        out = self.ok("result", "S1").stdout
        self.assertIn("outcome=failing", out)
        self.assertIn("step verify: failed", out)
        self.assertRegex(out, r"failed check: saved \(.*Timeout 50ms.*\) in step verify")
        self.assertIn("error: check \"saved\" failed", out)
        self.assertRegex(out, r"failure screenshot: .*failure\.png at http://app\.test/ok")
        self.assertTrue((self.dir / sc["last_run"]["dir"] / "failure.png").is_file())

    def test_a_thrown_error_and_automatic_checks(self):
        self.site["/ok"] = {"text": ["Hello"], "console": ["TypeError in app.js"],
                            "responses": [{"status": 502, "url": "/api", "method": "POST"}],
                            "failedRequests": [{"url": "/font.woff", "errorText": "net::ERR_FAILED"}]}
        self.scenario("S1")
        self.script("S1", THROW)
        result = self.ok("run", "S1")
        self.assertRegex(result.stdout, r"(?m)^S1\s+FAILED.*error: button disabled")
        sc = self.sc("S1")
        self.assertEqual(sc["last_run"]["error"], "button disabled")
        self.assertEqual(sc["outcome"], "failing")
        out = self.ok("result", "S1").stdout
        self.assertIn("step submit: failed button disabled", out)
        self.assertIn("error: button disabled in step submit", out)
        self.assertIn("console error: TypeError in app.js", out)
        self.assertIn("http 502 POST http://app.test/api", out)
        self.assertIn("request failed: net::ERR_FAILED http://app.test/font.woff", out)
        # A completed body with console errors and 5xx responses fails on the automatic checks.
        self.scenario("S2")
        self.script("S2", PASS)
        result = self.ok("run", "S2")
        self.assertRegex(result.stdout, r"(?m)^S2\s+FAILED.*checks 1/1\s+failed: no console errors; no HTTP 5xx responses")
        self.assertEqual(self.sc("S2")["last_run"]["failed_checks"], ["no console errors", "no HTTP 5xx responses"])
        self.assertEqual(self.sc("S2")["outcome"], "failing")

    def test_a_crash_without_result(self):
        self.scenario("S1")
        (self.dir / "scenarios" / "S1.mjs").write_text("console.log('before'); process.exit(3);\n")
        result = self.ok("run", "S1")
        self.assertRegex(result.stdout, r"(?m)^S1\s+CRASHED.*see results/S1/r001/output\.log")
        self.assertEqual(self.sc("S1")["last_run"]["status"], "crashed")
        self.assertEqual(self.sc("S1")["outcome"], "failing")
        self.assertIn("before", (self.dir / "results/S1/r001/output.log").read_text())
        self.assertIn("no result.json; see", self.ok("result", "S1").stdout)

    def test_a_hanging_script_is_killed_at_the_timeout(self):
        self.ok("config", "--timeout", "1")
        self.scenario("S1")
        self.script("S1", HANG)
        started = time.time()
        result = self.ok("run", "S1", timeout=30)
        self.assertLess(time.time() - started, 8)
        self.assertRegex(result.stdout, r"(?m)^S1\s+TIMEOUT.*see results/S1/r001/output\.log\s+killed node, browser")
        run = self.sc("S1")["last_run"]
        self.assertEqual((run["status"], run["cleaned"]), ("timeout", ["node", "browser"]))
        self.assertEqual(self.sc("S1")["outcome"], "failing")
        pids = read_json(self.dir / run["dir"] / "pids.json")
        self.assertFalse(alive(pids["node"]), "node process left running")
        self.assertFalse(alive(pids["browser"]), "browser process left running")
        self.assertIsNone(self.sc("S1")["running"])
        self.refused("ready", "S1", pattern="not crashed or timed out")

    def test_screenshots_are_collected(self):
        self.scenario("S1", "g1", "visual")
        self.script("S1", SHOT)
        result = self.ok("run", "S1")
        self.assertIn("shots 2 (2 to judge)", result.stdout)
        self.assertIn("shots to judge: 2", result.stdout)
        shots = self.sc("S1")["shots"]
        self.assertEqual(sorted(shots), ["home@desktop", "home@mobile"])
        desktop = shots["home@desktop"]
        self.assertEqual((desktop["path"], desktop["run"], desktop["size"], desktop["judgment"], desktop["diff"], desktop["judged"]),
                         ("results/S1/r001/shots/home@desktop.png", "r001", "1440x900", "pending", None, None))
        self.assertTrue((self.dir / desktop["path"]).is_file())
        self.assertEqual(shots["home@mobile"]["size"], "390x844")

    def test_selection_errors(self):
        self.refused("run", pattern="name scenarios or use")
        self.refused("run", "NOPE", pattern="unknown scenario NOPE")
        self.scenario("S1")
        self.refused("run", "S1", pattern="no script yet: S1")
        self.refused("run", "--group", "g1", pattern="no script yet: S1")
        self.script("S1", PASS)
        self.refused("run", "S1", "--repeat", "0", pattern="--repeat")
        self.assertEqual(self.state()["runs"], [])

    def test_unknown_viewport_and_already_running_are_refused(self):
        self.scenario("S1")
        self.script("S1", PASS)
        s = self.state()
        s["scenarios"]["S1"]["viewports"] = ["tablet"]
        self.save_state(s)
        self.refused("run", "S1", pattern="unknown viewports in S1")
        s["scenarios"]["S1"]["viewports"] = None
        s["scenarios"]["S1"]["running"] = {"pid": os.getpid(), "run": "r009", "at": "x", "node_pid": None, "dir": None}
        self.save_state(s)
        self.refused("run", "S1", pattern="already running: S1")

    def test_todo_runs_ready_scripts_not_run_yet_or_reset(self):
        self.ready("S1")
        self.ready("S2")
        self.scenario("S3")
        self.script("S3", PASS)  # written, not ready
        self.assertIn("nothing to run", self.ok("run", "--todo").stdout)
        self.ok("set", "S2", "pending")
        self.ok("run", "--todo")
        self.assertEqual(self.state()["runs"][-1]["scenarios"], ["S2"])
        self.assertEqual(self.sc("S2")["outcome"], "passed")

    def test_failed_runs_failing_failed_and_flaky(self):
        for sid in ("S1", "S2", "S3", "S4", "S5"):
            self.scenario(sid)
            self.script(sid, FAIL_CHECK)
        self.script("S5", PASS)
        self.ok("run", "--group", "g1")
        self.ok("triage", "S2", "app", "--note", "bug")
        self.ok("triage", "S3", "flaky", "--note", "passes 2 of 3")
        self.ok("triage", "S4", "env", "--note", "db down")
        self.ok("run", "--failed")
        self.assertEqual(self.state()["runs"][-1]["scenarios"], ["S1", "S2", "S3"])

    def test_all_runs_every_ready_script_and_group_runs_a_group(self):
        self.ready("S1")
        self.ready("S2", group="g2")
        self.scenario("S3")
        self.script("S3", PASS)
        self.ok("run", "--all")
        self.assertEqual(self.state()["runs"][-1]["scenarios"], ["S1", "S2"])
        self.ok("run", "--group", "g1")
        self.assertEqual(self.state()["runs"][-1]["scenarios"], ["S1", "S3"], "a group run includes written scripts")
        self.ok("run", "--all", "--group", "g2")
        self.assertEqual(self.state()["runs"][-1]["scenarios"], ["S2"])

    def test_repeat_records_every_attempt(self):
        self.scenario("S1")
        # Fails on odd attempts, passes on even ones.
        self.script("S1", "const f = new URL('../count.txt', import.meta.url);\n"
                          "const fs = await import('node:fs');\n"
                          "const n = (fs.existsSync(f) ? Number(fs.readFileSync(f, 'utf8')) : 0) + 1;\n"
                          "fs.writeFileSync(f, String(n));\n"
                          "await check('even attempt', n % 2 === 0);")
        result = self.ok("run", "S1", "--repeat", "2")
        self.assertRegex(result.stdout, r"(?m)^S1\s+PASSED.*1/2 passed")
        run = self.sc("S1")["last_run"]
        self.assertEqual(run["attempts"], ["failed", "passed"])
        self.assertEqual(run["dir"], "results/S1/r001.2")
        self.assertTrue((self.dir / "results/S1/r001.1/result.json").is_file())
        self.assertEqual(self.sc("S1")["outcome"], "failing", "an unstable result waits for triage")
        self.assertIsNone(self.sc("S1")["running"])
        self.assertEqual(self.state()["runs"][-1]["repeat"], 2)

        self.scenario("S2")
        self.script("S2", PASS)
        result = self.ok("run", "S2", "--repeat", "3")
        self.assertIn("3/3 passed", result.stdout)
        self.assertEqual(self.sc("S2")["outcome"], "passed")

    def test_groups_run_in_parallel_up_to_max_browsers_and_in_id_order_within_a_group(self):
        for sid, group in (("S10", "g1"), ("S2", "g1"), ("S3", "g2"), ("S4", "g3")):
            self.scenario(sid, group)
            self.script(sid, SLOW)
        result = self.ok("run", "S2", "S10", "S3", "S4")
        self.assertIn("4 scenario(s) in 3 group(s), at most 2 browser(s)", result.stdout)
        events = self.browser_events()
        self.assertEqual(max_overlap(events), 2, "two groups run at once, never more")
        order = [e["scenario"] for e in events if e["event"] == "launch" and e["scenario"] in ("S2", "S10")]
        self.assertEqual(order, ["S2", "S10"], "scenarios of one group run one after another")
        self.assertIn("summary: 4 passed", result.stdout)

    def test_a_group_runs_in_natural_id_order(self):
        for sid in ("S10", "S2", "S1"):
            self.scenario(sid)
            self.script(sid, "await page.goto(url('/ok'));")
        self.ok("run", "--group", "g1")
        self.assertEqual([e["scenario"] for e in self.browser_events() if e["event"] == "launch"], ["S1", "S2", "S10"])

    def test_named_scenarios_of_a_group_run_in_id_order(self):
        for sid in ("S10", "S2"):
            self.scenario(sid)
            self.script(sid, "await page.goto(url('/ok'));")
        self.ok("run", "S10", "S2")
        self.assertEqual([e["scenario"] for e in self.browser_events() if e["event"] == "launch"], ["S2", "S10"])

    def test_one_browser_at_a_time(self):
        self.ok("config", "--max-browsers", "1")
        for sid, group in (("S1", "g1"), ("S2", "g2")):
            self.scenario(sid, group)
            self.script(sid, SLOW)
        self.ok("run", "S1", "S2")
        self.assertEqual(max_overlap(self.browser_events()), 1)

    def test_the_limit_is_shared_between_processes(self):
        self.ok("config", "--max-browsers", "1")
        for sid, group in (("S1", "g1"), ("S2", "g2")):
            self.scenario(sid, group)
            self.script(sid, SLOW)
        env = {**os.environ, **self.env()}
        procs = [subprocess.Popen([sys.executable, str(BROWSER), str(self.dir), "run", sid], cwd=self.tmp, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for sid in ("S1", "S2")]
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, out + err)
        self.assertEqual(max_overlap(self.browser_events()), 1)
        self.assertEqual(self.sc("S1")["outcome"], "passed")
        self.assertEqual(self.sc("S2")["outcome"], "passed")

    def test_an_interrupted_run_keeps_the_previous_outcome(self):
        self.scenario("S1")
        self.script("S1", HANG)
        env = {**os.environ, **self.env()}
        proc = subprocess.Popen([sys.executable, str(BROWSER), str(self.dir), "run", "S1"], cwd=self.tmp, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pids_file = self.dir / "results/S1/r001/pids.json"
        deadline = time.time() + 20
        while not pids_file.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(pids_file.exists())
        time.sleep(0.2)
        proc.send_signal(signal.SIGINT)
        out, err = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 1, out + err)
        self.assertIn("interrupted", err)
        sc = self.sc("S1")
        self.assertEqual((sc["outcome"], sc["last_run"], sc["running"]), ("pending", None, None))
        pids = read_json(pids_file)
        self.assertFalse(alive(pids["node"]))
        self.assertFalse(alive(pids["browser"]))
        self.assertEqual([r["type"] for r in self.log()][-1], "run_interrupted")


@unittest.skipUnless(NODE, "node is required")
class TriageAndSetTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.scenario("S1")
        self.script("S1", FAIL_CHECK)

    def failing(self):
        self.ok("run", "S1")
        self.assertEqual(self.sc("S1")["outcome"], "failing")

    def test_triage_is_for_a_failing_run(self):
        self.refused("triage", "S1", "app", pattern="is pending")
        self.refused("triage", "NOPE", "app", pattern="unknown scenario")

    def test_app_makes_it_failed_and_links_the_finding(self):
        self.failing()
        (self.dir / "findings" / "F1.md").write_text("# F1\n")
        self.ok("finding", "F1", "--scenarios", "S1", "--kind", "functional_bug", "--title", "Save fails")
        self.refused("triage", "S1", "app", "--finding", "F9", pattern="unknown finding F9")
        result = self.ok("triage", "S1", "app", "--finding", "F1", "--note", "500 on save")
        self.assertIn("S1: failed (app)", result.stdout)
        sc = self.sc("S1")
        self.assertEqual((sc["outcome"], sc["reason"], sc["findings"]), ("failed", "500 on save", ["F1"]))
        self.assertEqual(sc["triage"], {"cause": "app", "note": "500 on save", "run": "r001"})
        self.assertEqual(self.state()["findings"]["F1"]["scenarios"], ["S1"])
        self.assertIn("triage: app 500 on save", self.ok("result", "S1").stdout)

    def test_env_and_flaky_need_evidence(self):
        self.failing()
        self.refused("triage", "S1", "env", pattern="needs --note")
        self.refused("triage", "S1", "flaky", pattern="needs --note")
        self.ok("triage", "S1", "env", "--note", "dev DB down")
        self.assertEqual((self.sc("S1")["outcome"], self.sc("S1")["reason"]), ("blocked", "dev DB down"))
        # A blocked scenario can be triaged again.
        self.ok("triage", "S1", "flaky", "--note", "passes 2 of 3")
        self.assertEqual(self.sc("S1")["outcome"], "flaky")

    def test_script_returns_the_script_to_its_author(self):
        self.ok("run", "S1")
        self.ok("ready", "S1")
        self.ok("triage", "S1", "script", "--note", "wrong selector")
        sc = self.sc("S1")
        self.assertEqual((sc["outcome"], sc["reason"], sc["ready_hash"]), ("pending", None, None))
        self.assertIn("scripts to finish (run and mark ready): g1: S1", self.ok("next").stdout)
        self.assertEqual(self.log("triage")[-1]["cause"], "script")

    def test_set_outcome_by_hand(self):
        self.ok("set", "S1", "unverified", "--reason", "drag and drop unsupported")
        self.assertEqual((self.sc("S1")["outcome"], self.sc("S1")["reason"]), ("unverified", "drag and drop unsupported"))
        self.assertIn("nothing open", self.ok("next").stdout, "an unverified scenario needs no script")
        self.ok("set", "S1", "blocked", "--reason", "no account")
        self.assertEqual(self.sc("S1")["outcome"], "blocked")
        self.ok("set", "S1", "pending")
        self.assertEqual((self.sc("S1")["outcome"], self.sc("S1")["reason"]), ("pending", None))
        result = self.bt("set", "S1", "blocked")
        self.assertExit(result, 2)
        self.assertIn("needs --reason", result.stderr)
        self.refused("set", "NOPE", "pending")
        self.assertEqual(self.log("set")[0]["outcome"], "unverified")


@unittest.skipUnless(NODE, "node is required")
class ShotsAndJudgeTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.scenario("S1", "g1", "visual")
        self.script("S1", SHOT)

    def test_judgments_and_the_verdict_of_a_visual_scenario(self):
        self.refused("judge", "S1", "ok", pattern="no pending screenshots")
        self.ok("run", "S1")
        self.assertEqual(self.sc("S1")["outcome"], "passed")
        status = self.ok("status").stdout
        self.assertIn("outcomes: 1 pending", status, "a passed visual scenario waits for its judgments")
        self.assertIn("screenshots: 2 pending", status)
        self.assertIn("screenshots to judge: g1: S1", self.ok("next").stdout)
        out = self.ok("shots").stdout
        self.assertIn(f"{self.dir.resolve()}/results/S1/r001/shots/home@desktop.png", out)
        self.assertRegex(out, r"S1\s+home@desktop\s+pending")

        self.refused("judge", "S1", "ok", "--shots", "home@tablet", pattern="unknown screenshot home@tablet")
        self.refused("judge", "S1", "issue", "--shots", "home@mobile", pattern="needs --finding or --note")
        self.assertIn("S1: 1 screenshot(s) ok", self.ok("judge", "S1", "ok", "--shots", "home@desktop").stdout)
        self.assertEqual(self.ok("shots", "--pending").stdout.count("\n"), 1)
        self.assertIn("home@mobile", self.ok("shots", "--pending").stdout)
        self.ok("judge", "S1", "issue", "--note", "button overlaps the menu")
        shot = self.sc("S1")["shots"]["home@mobile"]
        self.assertEqual((shot["judgment"], shot["note"], shot["judged"]["judgment"], shot["judged"]["path"]),
                         ("issue", "button overlaps the menu", "issue", shot["path"]))
        status = self.ok("status").stdout
        self.assertIn("outcomes: 1 failed", status)
        self.assertIn("screenshot judged as an issue: home@mobile", status)
        self.assertIn("button overlaps the menu", self.ok("shots", "S1").stdout)
        self.assertIn("no screenshots", self.ok("shots", "--pending").stdout)
        self.assertIn("warning: scenario S1: shot home@mobile judged as an issue without a finding", self.ok("validate").stdout)

        self.ok("judge", "S1", "ok", "--shots", "home@mobile")
        self.assertIn("outcomes: 1 passed", self.ok("status").stdout)
        self.assertEqual(self.log("judge")[0]["shots"], ["home@desktop"])

    def test_judge_links_a_finding(self):
        self.ok("run", "S1")
        (self.dir / "findings" / "F1.md").write_text("# F1\n")
        self.ok("scenario", "S2", "--title", "Two", "--group", "g1")
        self.ok("finding", "F1", "--scenarios", "S2", "--kind", "ui_bug", "--title", "Overlap")
        self.refused("judge", "S1", "issue", "--finding", "F9")
        self.ok("judge", "S1", "issue", "--finding", "F1")
        self.assertEqual(self.sc("S1")["findings"], ["F1"])
        self.assertEqual(self.state()["findings"]["F1"]["scenarios"], ["S2", "S1"])

    def test_an_unchanged_screenshot_keeps_its_judgment(self):
        self.ok("run", "S1")
        self.ok("judge", "S1", "ok")
        result = self.ok("run", "S1")
        self.assertIn("shots 2 (0 to judge)", result.stdout)
        self.assertNotIn("shots to judge", result.stdout)
        shot = self.sc("S1")["shots"]["home@desktop"]
        self.assertEqual((shot["run"], shot["judgment"], shot["inherited"], shot["diff"], shot["diff_pixels"]),
                         ("r002", "ok", True, 0, 0))
        self.assertEqual(shot["judged"]["run"], "r001")
        self.assertIn("(unchanged since judged, 0 px differ)", self.ok("shots").stdout)
        self.assertIn("outcomes: 1 passed", self.ok("status").stdout)

    def test_a_changed_screenshot_waits_for_a_judgment_with_a_diff(self):
        self.ok("run", "S1")
        self.ok("judge", "S1", "ok")
        self.site["/ok"] = {"text": ["Hello"], "dots": [[0, 0, [255, 0, 0, 255]], [3, 3, [0, 0, 0, 255]]]}
        result = self.ok("run", "S1")
        self.assertIn("(2 to judge)", result.stdout)
        shot = self.sc("S1")["shots"]["home@desktop"]
        self.assertEqual((shot["judgment"], shot["inherited"], shot["diff_pixels"]), ("pending", False, 2))
        self.assertAlmostEqual(shot["diff"], 2 / (36 * 23), places=6)
        self.assertEqual(shot["diff_image"], "results/S1/r002/shots/home@desktop.diff.png")
        self.assertTrue((self.dir / shot["diff_image"]).is_file())
        out = self.ok("shots", "S1").stdout
        self.assertIn("2 px = ", out)
        self.assertIn("differ from the one judged ok, diff image", out)
        # The baseline stays the last judged screenshot, also when a newer run was not judged.
        self.ok("run", "S1")
        shot = self.sc("S1")["shots"]["home@desktop"]
        self.assertEqual((shot["run"], shot["judgment"], shot["judged"]["run"], shot["diff_pixels"]), ("r003", "pending", "r001", 2))

    def test_a_diff_threshold_tolerates_small_changes(self):
        self.ok("run", "S1")
        self.ok("judge", "S1", "issue", "--note", "ugly")
        self.ok("config", "--diff-threshold", "0.01")
        self.site["/ok"] = {"text": ["Hello"], "dots": [[0, 0, [255, 0, 0, 255]]]}
        self.ok("run", "S1")
        shot = self.sc("S1")["shots"]["home@desktop"]
        self.assertEqual((shot["judgment"], shot["inherited"], shot["note"], shot["diff_pixels"]), ("issue", True, "ugly", 1))
        self.assertIn("outcomes: 1 failed", self.ok("status").stdout)

    def test_shots_of_an_older_run_are_marked(self):
        self.ok("run", "S1")
        self.script("S1", PASS)
        self.ok("run", "S1")
        out = self.ok("shots", "S1").stdout
        self.assertIn("from run r001, not produced by the last run r002", out)
        self.assertIn("no screenshots", self.ok("shots", "--group", "nogroup").stdout)
        self.refused("shots", "NOPE")

    def test_a_size_change_is_reported_without_a_pixel_count(self):
        self.ok("run", "S1")
        self.ok("judge", "S1", "ok")
        self.ok("config", "--viewport", "desktop=1280x800", "mobile=390x844:mobile")
        self.ok("run", "S1")
        shot = self.sc("S1")["shots"]["home@desktop"]
        self.assertEqual((shot["judgment"], shot["diff"]), ("pending", 1))
        self.assertNotIn("None", self.ok("shots", "S1").stdout)


@unittest.skipUnless(NODE, "node is required")
class FindingTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.scenario("S1")
        self.scenario("S2")

    def test_finding_is_indexed_and_linked(self):
        result = self.bt("finding", "F1", "--scenarios", "S1", "S2", "--kind", "functional_bug", "--title", "Save fails",
                         "--severity", "high")
        self.assertOk(result)
        self.assertIn("warning: write findings/F1.md", result.stderr)
        self.assertEqual(self.state()["findings"]["F1"], {"title": "Save fails", "kind": "functional_bug", "severity": "high",
                                                          "scenarios": ["S1", "S2"], "status": "open", "history": []})
        self.assertEqual(self.sc("S2")["findings"], ["F1"])
        (self.dir / "findings" / "F2.md").write_text("# F2\n")
        self.assertNotIn("warning", self.bt("finding", "F2", "--scenarios", "S1", "--kind", "question", "--title", "Q").stderr)

    def test_finding_validation(self):
        self.ok("finding", "F1", "--scenarios", "S1", "--kind", "ui_bug", "--title", "t")
        self.refused("finding", "F1", "--scenarios", "S1", "--kind", "ui_bug", "--title", "t", pattern="IDs are stable")
        self.refused("finding", "F2", "--scenarios", "NOPE", "--kind", "ui_bug", "--title", "t", pattern="unknown scenario")
        self.refused("finding", "2F", "--scenarios", "S1", "--kind", "ui_bug", "--title", "t", pattern="starting with a letter")
        self.assertEqual(list(self.state()["findings"]), ["F1"])

    def test_resolve_keeps_a_history(self):
        self.ok("finding", "F1", "--scenarios", "S1", "--kind", "ui_bug", "--title", "t")
        self.ok("finding", "F2", "--scenarios", "S1", "--kind", "ui_bug", "--title", "t")
        self.ok("resolve", "F1", "fixed", "--reason", "commit abc")
        self.ok("resolve", "F1", "verified", "--reason", "S1 passes")
        f = self.state()["findings"]["F1"]
        self.assertEqual(f["status"], "verified")
        self.assertEqual([(h["from"], h["to"], h["reason"]) for h in f["history"]],
                         [("open", "fixed", "commit abc"), ("fixed", "verified", "S1 passes")])
        self.refused("resolve", "F2", "duplicate", "--reason", "same", pattern="--duplicate-of")
        self.refused("resolve", "F2", "duplicate", "--reason", "same", "--duplicate-of", "F9", pattern="unknown finding F9")
        self.ok("resolve", "F2", "duplicate", "--reason", "same", "--duplicate-of", "F1")
        self.assertEqual(self.state()["findings"]["F2"]["duplicate_of"], "F1")
        self.refused("resolve", "F9", "fixed", "--reason", "x")
        self.assertExit(self.bt("resolve", "F1", "fixed"), 2)

    def test_findings_lists_open_ones_by_severity(self):
        self.assertIn("no findings", self.ok("findings").stdout)
        self.ok("finding", "F1", "--scenarios", "S1", "--kind", "ux_recommendation", "--title", "Low one", "--severity", "low")
        self.ok("finding", "F2", "--scenarios", "S1", "--kind", "functional_bug", "--title", "Critical one", "--severity", "critical")
        self.ok("finding", "F3", "--scenarios", "S2", "--kind", "question", "--title", "No severity")
        self.ok("finding", "F4", "--scenarios", "S2", "--kind", "ui_bug", "--title", "Rejected", "--severity", "high")
        self.ok("resolve", "F4", "rejected", "--reason", "by design")
        lines = self.ok("findings").stdout.splitlines()
        self.assertEqual([line.split()[0] for line in lines], ["F2", "F1", "F3"])
        self.assertRegex(lines[0], r"F2\s+open\s+functional_bug\s+critical\s+S1: Critical one")
        self.assertRegex(lines[2], r"F3\s+open\s+question\s+-\s+S2: No severity")
        self.assertEqual([line.split()[0] for line in self.ok("findings", "--all").stdout.splitlines()], ["F2", "F4", "F1", "F3"])
        self.assertIn("findings: 3 open, 1 rejected", self.ok("status").stdout)


@unittest.skipUnless(NODE, "node is required")
class AssignTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.scenario("S1")
        self.scenario("S2")
        self.scenario("S3", "g2")

    def test_assign_and_release(self):
        self.assertIn("T1: script S1 S2", self.ok("assign", "--owner", "T1", "--task", "script", "--group", "g1").stdout)
        a = self.state()["assignments"]["T1"]
        self.assertEqual((a["task"], a["scenarios"], a["group"], a["status"]), ("script", ["S1", "S2"], "g1", "active"))
        self.refused("assign", "--owner", "T1", "--task", "triage", "S3", pattern="already has an active assignment")
        self.refused("assign", "--owner", "T2", "--task", "script", "S2", "S3", pattern="T1 already has script for S2")
        self.ok("assign", "--owner", "T2", "--task", "visual", "S2", "--note", "judge the list")
        self.ok("assign", "--owner", "T3", "--task", "explore")
        self.refused("assign", "--owner", "T4", "--task", "script", pattern="name scenarios or a --group")
        self.refused("assign", "--owner", "T4", "--task", "script", "NOPE", pattern="unknown scenario")
        self.refused("assign", "--owner", "bad owner", "--task", "explore", pattern="owner")
        self.assertIn("  assigned: T1", self.ok("next").stdout)
        self.assertRegex(self.ok("status").stdout, r"assignment T1: script S1 S2 since \S+")

        self.assertEqual(self.ok("release", "T1").stdout.strip(), "T1: done")
        self.refused("release", "T1", pattern="no active assignment")
        self.refused("release", "T9", pattern="no active assignment")
        self.assertIn("brief a new run", self.ok("release", "T3", "--lost").stdout)
        assignments = self.state()["assignments"]
        self.assertEqual((assignments["T1"]["status"], assignments["T3"]["status"]), ("done", "lost"))
        self.assertIn("released_at", assignments["T1"])
        # A released owner can take a new assignment.
        self.ok("assign", "--owner", "T1", "--task", "triage", "S3")
        self.assertEqual([r["type"] for r in self.log() if r["type"] in ("assign", "release")],
                         ["assign", "assign", "assign", "release", "release", "assign"])


@unittest.skipUnless(NODE, "node is required")
class NextAndStatusTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_next_walks_through_the_pass(self):
        self.assertIn("nothing open", self.ok("next").stdout)
        self.scenario("S1")
        self.scenario("S2", "g2")
        self.assertIn("scripts to write: g1: S1; g2: S2", self.ok("next").stdout)
        self.script("S1", PASS)
        out = self.ok("next").stdout
        self.assertIn("scripts to write: g2: S2", out)
        self.assertIn("scripts to finish (run and mark ready): g1: S1", out)
        self.ok("set", "S2", "unverified", "--reason", "cannot be scripted")
        self.ok("run", "S1")
        self.ok("ready", "S1")
        self.assertIn("nothing open", self.ok("next").stdout)
        self.ok("set", "S1", "pending")
        self.assertIn("to run: g1: S1", self.ok("next").stdout)
        self.script("S1", FAIL_CHECK)
        self.ok("run", "S1")
        self.assertIn("to triage: g1: S1", self.ok("next").stdout)
        self.ok("finding", "F1", "--scenarios", "S1", "--kind", "functional_bug", "--title", "t")
        self.ok("triage", "S1", "app", "--finding", "F1")
        self.ok("resolve", "F1", "fixed", "--reason", "fixed in code")
        self.assertNotIn("verify them", self.ok("next").stdout)
        self.script("S1", PASS)
        self.ok("run", "--failed")
        self.assertIn("fixed findings whose scenarios pass now, verify them: F1", self.ok("next").stdout)

    def test_status_overview(self):
        self.scenario("S1")
        self.scenario("S2", "g2", "visual")
        self.script("S1", FAIL_CHECK)
        self.ok("run", "S1")
        self.ok("set", "S2", "blocked", "--reason", "no test account")
        out = self.ok("status").stdout
        self.assertIn("scope demo · http://app.test · chromium · at most 2 browser(s) · "
                      "viewports desktop 1440x900, mobile 390x844 mobile", out)
        self.assertIn("code now unknown, at init unknown", out)
        self.assertIn("scenarios 2 in 2 group(s): g1, g2", out)
        self.assertIn("scripts: 1 pending, 1 written", out)
        self.assertIn("outcomes: 1 failing, 1 blocked", out)
        self.assertRegex(out, r"S1\s+failing\s+saved")
        self.assertRegex(out, r"S2\s+blocked\s+no test account")
        self.assertRegex(out, r"runs 1, last r001 at \S+ \(1 scenario\(s\)\)")

    def test_status_returns_a_dead_run_to_the_queue_and_kills_its_leftovers(self):
        self.scenario("S1")
        self.script("S1", PASS)
        # A dead run process and the node and browser processes it left behind.
        dead = subprocess.Popen(["true"])
        dead.wait()
        node = orphan(NODE, "-e", "setInterval(() => {}, 1e6)", "leftover-scenario")
        browser = orphan(NODE, "-e", "setInterval(() => {}, 1e6)", "fake-chromium-browser")
        self.addCleanup(kill_quietly, node)
        self.addCleanup(kill_quietly, browser)
        self.assertTrue(alive(node) and alive(browser))
        run_dir = self.dir / "results/S1/r001"
        run_dir.mkdir(parents=True)
        write_json(run_dir / "pids.json", {"node": node, "browser": browser})
        s = self.state()
        s["scenarios"]["S1"]["running"] = {"pid": dead.pid, "run": "r001", "at": "x", "node_pid": node,
                                           "dir": "results/S1/r001"}
        self.save_state(s)
        out = self.ok("status").stdout
        self.assertIn("recovered from a dead run: S1", out)
        self.assertNotIn("running:", out)
        self.assertIsNone(self.sc("S1")["running"])
        self.assertFalse(alive(node), "leftover node process")
        self.assertFalse(alive(browser), "leftover browser process")
        [record] = self.log("recovered")
        self.assertEqual((record["scenario"], record["run"], record["killed_leftovers"]), ("S1", "r001", True))
        self.ok("run", "S1")
        self.assertEqual(self.sc("S1")["outcome"], "passed")

    def test_a_reused_pid_is_spared(self):
        self.scenario("S1")
        dead = subprocess.Popen(["true"])
        dead.wait()
        other = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(lambda: other.poll() is None and other.kill())
        s = self.state()
        s["scenarios"]["S1"]["running"] = {"pid": dead.pid, "run": "r001", "at": "x", "node_pid": other.pid, "dir": None}
        self.save_state(s)
        self.assertIn("recovered from a dead run: S1", self.ok("status").stdout)
        self.assertIsNone(other.poll(), "a process that is not node was killed")
        self.assertFalse(self.log("recovered")[0]["killed_leftovers"])

    def test_a_running_scenario_is_listed(self):
        self.scenario("S1")
        s = self.state()
        s["scenarios"]["S1"]["running"] = {"pid": os.getpid(), "run": "r001", "at": "x", "node_pid": None, "dir": None}
        self.save_state(s)
        self.assertIn("running: S1", self.ok("status").stdout)
        self.assertIn("running: S1", self.ok("next").stdout)
        self.assertIsNotNone(self.sc("S1")["running"], "a live run is not reaped")


@unittest.skipUnless(NODE, "node is required")
class CodeStateTest(BrowserCase):
    def test_results_from_another_code_state(self):
        repo = make_repo(self.tmp / "repo")
        self.dir = repo / "work" / "pw"
        self.ok("init", "--scope", "demo", "--url", "http://app.test", "--repo", str(repo), "--playwright", str(FAKE),
                cwd=repo)
        self.ready("S1")
        self.ready("S2")
        out = self.ok("status").stdout
        self.assertNotIn("another code state", out, "the testing folder inside the repository is not a code change")
        head = git(repo, "rev-parse", "HEAD")[:12]
        self.assertEqual(self.sc("S1")["last_run"]["fingerprint"], head)

        (repo / "app.txt").write_text("changed\n")
        out = self.ok("status").stdout
        self.assertRegex(out, rf"code now {head}\+[0-9a-f]{{8}}, at init {head}")
        self.assertIn("results from another code state: S1 S2", out)
        self.assertIn("to run again, code changed since their run: g1: S1 S2", self.ok("next").stdout)
        self.ok("run", "--todo")
        self.assertEqual(self.state()["runs"][-1]["scenarios"], ["S1", "S2"])
        self.assertNotIn("another code state", self.ok("status").stdout)
        self.assertIn("nothing to run", self.ok("run", "--todo").stdout)

        (repo / "new-file.txt").write_text("untracked\n")
        self.assertIn("results from another code state: S1 S2", self.ok("status").stdout)


@unittest.skipUnless(NODE, "node is required")
class ValidateTest(BrowserCase):
    def setUp(self):
        super().setUp()
        self.init()

    def test_a_fresh_folder_is_valid(self):
        self.assertEqual(self.ok("validate").stdout.strip(), "valid")

    def test_errors_exit_1(self):
        self.scenario("S1", "g1", "visual")
        self.script("S1", SHOT)
        self.ok("run", "S1")
        self.ok("finding", "F1", "--scenarios", "S1", "--kind", "ui_bug", "--title", "t")
        (self.dir / "harness.mjs").unlink()
        Path(self.dir / self.sc("S1")["shots"]["home@desktop"]["path"]).unlink()
        s = self.state()
        s["scenarios"]["S1"]["viewports"] = ["tablet"]
        s["scenarios"]["S2"] = dict(s["scenarios"]["S1"], outcome="blocked", reason=None, viewports=None, shots={},
                                    findings=["F9"], kind="weird")
        s["findings"]["F1"]["scenarios"].append("S9")
        s["assignments"]["T1"] = {"task": "cleanup", "scenarios": [], "status": "active"}
        self.save_state(s)
        with (self.dir / "log.jsonl").open("a") as f:
            f.write('{"note": "no type"}\n')
        result = self.bt("validate")
        self.assertExit(result, 1)
        out = result.stdout
        for expected in ("error: harness.mjs missing", "error: scenario S1: unknown viewport tablet",
                         "error: scenario S1: shot home@desktop file missing", "error: scenario S2: invalid kind 'weird'",
                         "error: scenario S2: blocked without a reason", "error: scenario S2: unknown finding F9",
                         "error: finding F1: missing findings/F1.md", "error: finding F1: unknown scenario S9",
                         "error: assignment T1: invalid task 'cleanup'", "missing at or type"):
            self.assertIn(expected, out)
        self.assertRegex(out, r"\d+ error\(s\)\s*$")

    def test_warnings_do_not_fail(self):
        self.scenario("S1")
        self.script("S1", FAIL_CHECK)
        self.ok("run", "S1")
        self.ok("triage", "S1", "app", "--note", "bug")
        self.scenario("S2", "g1", "visual")
        self.script("S2", PASS)
        self.ok("run", "S2")
        out = self.ok("validate").stdout
        self.assertIn("warning: scenario S1: failed without a finding", out)
        self.assertIn("warning: scenario S2: a visual scenario without screenshots", out)
        self.assertTrue(out.strip().endswith("valid"))

    def test_an_unreadable_log_is_refused(self):
        with (self.dir / "log.jsonl").open("a") as f:
            f.write("{not json\n")
        self.refused("validate", pattern="invalid JSON")


@unittest.skipUnless(NODE, "node is required")
class LogTest(BrowserCase):
    def test_log_records(self):
        self.init()
        self.assertIn("logged data", self.ok("log", "data", "text=order #123 for tester@example.com", "count=3").stdout)
        self.ok("log", "check", "subject=login", "result=ok", "ids=[1,2]", "flag=true")
        record = self.log("data")[0]
        self.assertEqual((record["text"], record["count"]), ("order #123 for tester@example.com", 3))
        record = self.log("check")[0]
        self.assertEqual((record["subject"], record["result"], record["ids"], record["flag"]), ("login", "ok", [1, 2], True))
        self.assertIn("at", record)
        self.refused("log", "check", "subject=login", pattern="check needs result")
        self.refused("log", "decision", pattern="decision needs text")
        self.refused("log", "note", "no-equals-sign", pattern="expected key=value")
        self.refused("log", "note", "=value", pattern="expected key=value")
        for type_ in ("decision", "note", "explore"):
            self.ok("log", type_, "text=x")
        self.assertEqual(len(self.log()), 6)


class HelpersTest(unittest.TestCase):
    """Pure helpers of browser.py."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_browser_module()

    def test_parse_viewports(self):
        self.assertEqual(self.m.parse_viewports(["desktop=1440x900", "phone-s=320x568:mobile"]), {
            "desktop": {"width": 1440, "height": 900, "mobile": False},
            "phone-s": {"width": 320, "height": 568, "mobile": True}})
        for bad in ("desktop", "desktop=1440", "desktop=1440x900:tablet", "=1x1", "a b=1x1"):
            with self.assertRaises(self.m.Refused, msg=bad):
                self.m.parse_viewports([bad])

    def test_natural_order(self):
        self.assertEqual(sorted(["S10", "S2", "S1", "A3"], key=self.m.natural), ["A3", "S1", "S2", "S10"])

    def test_check_id(self):
        for good in ("S1", "orders.list-2", "a_b"):
            self.assertEqual(self.m.check_id(good, "x"), good)
        for bad in ("1S", "-a", "a b", "", None, 5):
            with self.assertRaises(self.m.Refused):
                self.m.check_id(bad, "x")

    def test_scenario_viewports(self):
        config = {"viewports": {"desktop": {}, "mobile": {}}}
        self.assertEqual(self.m.scenario_viewports(config, {"kind": "functional"}), ["desktop"])
        self.assertEqual(self.m.scenario_viewports(config, {"kind": "visual"}), ["desktop", "mobile"])
        self.assertEqual(self.m.scenario_viewports(config, {"kind": "both", "viewports": None}), ["desktop", "mobile"])
        self.assertEqual(self.m.scenario_viewports(config, {"kind": "visual", "viewports": ["mobile"]}), ["mobile"])

    def test_verdict(self):
        def sc(kind, outcome, *judgments, run="r2"):
            shots = {f"k{i}": {"run": "r2", "judgment": j} for i, j in enumerate(judgments)}
            return {"kind": kind, "outcome": outcome, "shots": shots, "last_run": {"run": run}}
        self.assertEqual(self.m.verdict(sc("functional", "passed", "issue")), "passed")
        self.assertEqual(self.m.verdict(sc("visual", "failing", "ok")), "failing")
        self.assertEqual(self.m.verdict(sc("visual", "passed", "ok", "ok")), "passed")
        self.assertEqual(self.m.verdict(sc("both", "passed", "ok", "pending")), "pending")
        self.assertEqual(self.m.verdict(sc("visual", "passed", "pending", "issue")), "failed")
        self.assertEqual(self.m.verdict(sc("visual", "passed", "issue", run="r3")), "passed",
                         "only screenshots of the last run count")


def orphan(*command: str) -> int:
    """Start a process in its own session through a short-lived parent, so that it is not our child."""
    code = ("import subprocess, sys; print(subprocess.Popen(sys.argv[1:], start_new_session=True, "
            "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid)")
    return int(subprocess.run([sys.executable, "-c", code, *command], capture_output=True, text=True, check=True).stdout)


def kill_quietly(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q")
    (path / "app.txt").write_text("app\n")
    git(path, "add", "app.txt")
    git(path, "-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", "initial")
    return path


if __name__ == "__main__":
    unittest.main()
