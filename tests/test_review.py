"""Tests of base/shared/review.py: diff parsing and chunking, every command, validation and refresh.

The spec is the module docstring and shared/review-tool.md. The commands run as subprocesses; the pure
helpers (parse_diff, classify, pack, common_dir, location_file) are imported directly.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import SHARED, ToolTestCase, load_module, read_json, read_jsonl, run_tool, write_json

REVIEW = SHARED / "review.py"
review = load_module(REVIEW, "review_under_test")


# --- diff fixtures --------------------------------------------------------------------------------


def modified(path: str, minus=(), plus=(), index: str = "1111111..2222222", start: int = 1) -> str:
    """One modified file with a single hunk."""
    lines = [f"diff --git a/{path} b/{path}", f"index {index} 100644", f"--- a/{path}", f"+++ b/{path}",
             f"@@ -{start},{len(minus)} +{start},{len(plus)} @@"]
    lines += ["-" + m for m in minus] + ["+" + p for p in plus]
    return "\n".join(lines) + "\n"


def added(path: str, plus=(), index: str = "0000000..3333333") -> str:
    lines = [f"diff --git a/{path} b/{path}", "new file mode 100644", f"index {index}", "--- /dev/null",
             f"+++ b/{path}", f"@@ -0,0 +1,{len(plus)} @@"] + ["+" + p for p in plus]
    return "\n".join(lines) + "\n"


def renamed(old: str, new: str) -> str:
    return f"diff --git a/{old} b/{new}\nsimilarity index 100%\nrename from {old}\nrename to {new}\n"


def binary(path: str) -> str:
    return (f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..5555555\n"
            f"Binary files /dev/null and b/{path} differ\n")


MIXED = """\
diff --git a/src/app.py b/src/app.py
index 83db48f..bf269f4 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,3 +1,4 @@
 import os
-x = 1
+x = 2
+y = 3
 print(x)
@@ -20,2 +21,2 @@ def f():
-    return 1
+    return 2
diff --git a/old/name.py b/new/name.py
similarity index 100%
rename from old/name.py
rename to new/name.py
diff --git a/lib/util.py b/lib/helpers.py
similarity index 80%
rename from lib/util.py
rename to lib/helpers.py
index 1111111..2222222 100644
--- a/lib/util.py
+++ b/lib/helpers.py
@@ -1,2 +1,2 @@
-def a(): pass
+def b(): pass
 x = 1
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
index 3333333..0000000
--- a/gone.txt
+++ /dev/null
@@ -1,2 +0,0 @@
-one
-two
diff --git a/docs/new.md b/docs/new.md
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/docs/new.md
@@ -0,0 +1,3 @@
+# Title
+
+text
diff --git a/img/logo.png b/img/logo.png
new file mode 100644
index 0000000..5555555
Binary files /dev/null and b/img/logo.png differ
"""


def info(path: str, *, binary=False, status="modified", similarity=None, sample=(), added=1, deleted=0) -> dict:
    return {"path": path, "binary": binary, "status": status, "similarity": similarity, "sample": list(sample),
            "added": added, "deleted": deleted}


GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "Test",
           "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "test@example.com"}


class ReviewTestCase(ToolTestCase):
    """Runs review.py on self.dir; commands run in self.tmp, which is kept out of any git repository."""

    def setUp(self) -> None:
        super().setUp()
        self.dir = self.tmp / "review"
        # HOME isolates git from the user's configuration also where GIT_CONFIG_GLOBAL is not supported.
        self.env = {**GIT_ENV, "GIT_CEILING_DIRECTORIES": str(self.tmp.parent), "HOME": str(self.tmp),
                    "XDG_CONFIG_HOME": str(self.tmp / ".config")}

    def rv(self, *args, cwd: Path | None = None):
        return run_tool(REVIEW, self.dir, *args, cwd=cwd or self.tmp, env=self.env)

    def ok(self, *args, cwd: Path | None = None) -> str:
        result = self.rv(*args, cwd=cwd)
        self.assertOk(result)
        return result.stdout

    def refused(self, *args, contains: str | None = None):
        result = self.rv(*args)
        self.assertExit(result, 1)
        self.assertIn("refused:", result.stderr)
        if contains:
            self.assertIn(contains, result.stderr)
        return result

    def state(self) -> dict:
        return read_json(self.dir / "review.json")

    def log(self) -> list:
        return read_jsonl(self.dir / "log.jsonl")

    def write_diff(self, text: str, name: str = "diff.patch") -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / name
        path.write_text(text)
        return path

    def write_finding(self, fid: str) -> None:
        (self.dir / "findings").mkdir(parents=True, exist_ok=True)
        (self.dir / "findings" / f"{fid}.md").write_text(f"# {fid}\n")

    def add_finding(self, fid: str, *args) -> str:
        self.write_finding(fid)
        return self.ok("finding", fid, *args)

    def init_single(self, diff: str | None = None, *groups: str, wave_size: int | None = None) -> str:
        self.write_diff(diff if diff is not None else modified("x.py", ["a"], ["b"]))
        extra = ["--wave-size", str(wave_size)] if wave_size else []
        return self.ok("init", "--scope", "s", "--base", "main", "--head", "HEAD", *extra, "--single",
                       "--groups", *(groups or ('G1=Correctness and regressions;Testability and risk coverage',
                                                "G2=Security")))

    def init_plain(self, diff: str = "", wave_size: int | None = None) -> str:
        self.write_diff(diff)
        extra = ["--wave-size", str(wave_size)] if wave_size else []
        return self.ok("init", "--scope", "s", "--base", "main", "--head", "HEAD", *extra)

    def first_tokens(self, out: str) -> list[str]:
        return [line.split()[0] for line in out.splitlines() if line.strip()]


class GitRepo:
    """A throwaway git repository isolated from the user's configuration."""

    def __init__(self, root: Path, env: dict):
        self.root = root
        self.env = {**os.environ, **env}
        root.mkdir(parents=True)
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, env=self.env, check=True, capture_output=True,
                              text=True).stdout

    def write(self, files: dict) -> None:
        for rel, content in files.items():
            path = self.root / rel
            if content is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def commit(self, files: dict, message: str = "change") -> str:
        self.write(files)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.sha("HEAD")

    def sha(self, ref: str) -> str:
        return self.git("rev-parse", f"{ref}^{{commit}}").strip()

    def diff(self, *refs: str) -> str:
        return self.git("diff", "-M", *refs)


# --- pure helpers ---------------------------------------------------------------------------------


class ParseDiffTest(ToolTestCase):
    def parse(self, text: str) -> dict:
        path = self.tmp / "d.patch"
        path.write_text(text)
        return review.parse_diff(path)

    def test_mixed_diff(self):
        files = self.parse(MIXED)
        self.assertEqual(set(files), {"src/app.py", "new/name.py", "lib/helpers.py", "gone.txt", "docs/new.md",
                                      "img/logo.png"})
        app = files["src/app.py"]
        self.assertEqual((app["status"], app["added"], app["deleted"], app["binary"]), ("modified", 3, 2, False))

        pure = files["new/name.py"]
        self.assertEqual((pure["status"], pure["similarity"], pure["added"], pure["deleted"]), ("renamed", 100, 0, 0))
        edited = files["lib/helpers.py"]
        self.assertEqual((edited["status"], edited["similarity"], edited["added"], edited["deleted"]),
                         ("renamed", 80, 1, 1))
        self.assertNotIn("lib/util.py", files)

        gone = files["gone.txt"]
        self.assertEqual((gone["status"], gone["added"], gone["deleted"]), ("deleted", 0, 2))
        new = files["docs/new.md"]
        self.assertEqual((new["status"], new["added"], new["deleted"]), ("added", 3, 0))
        logo = files["img/logo.png"]
        self.assertEqual((logo["status"], logo["binary"], logo["added"]), ("added", True, 0))

    def test_header_like_lines_inside_a_hunk_are_content(self):
        # A removed SQL comment "-- x" and an added line "++ y" look like file headers but are content.
        files = self.parse(modified("q.sql", ["-- old comment", "--- banner"], ["++ y", "+++ z", "select 1"]))
        self.assertEqual((files["q.sql"]["added"], files["q.sql"]["deleted"]), (3, 2))

    def test_no_newline_marker_is_not_counted(self):
        text = modified("a.txt", ["a"], ["b"]) + "\\ No newline at end of file\n"
        self.assertEqual((self.parse(text)["a.txt"]["added"], self.parse(text)["a.txt"]["deleted"]), (1, 1))

    def test_git_binary_patch_is_binary(self):
        text = "diff --git a/a.bin b/a.bin\nindex 1..2 100644\nGIT binary patch\nliteral 3\nKcmZ?l\n\nliteral 0\n"
        self.assertTrue(self.parse(text)["a.bin"]["binary"])

    def test_path_with_spaces(self):
        self.assertEqual(set(self.parse(modified("my dir/a file.txt", ["a"], ["b"]))), {"my dir/a file.txt"})

    def test_hash_ignores_index_line_but_not_content(self):
        base = self.parse(modified("a.py", ["a"], ["b"], index="1111111..2222222"))["a.py"]["hash"]
        longer = self.parse(modified("a.py", ["a"], ["b"], index="111111111..222222222"))["a.py"]["hash"]
        other = self.parse(modified("a.py", ["a"], ["c"]))["a.py"]["hash"]
        self.assertEqual(base, longer)
        self.assertNotEqual(base, other)

    def test_hash_is_per_file(self):
        one = self.parse(modified("a.py", ["a"], ["b"]) + modified("b.py", ["a"], ["b"]))
        two = self.parse(modified("a.py", ["a"], ["b"]) + modified("b.py", ["a"], ["CHANGED"]))
        self.assertEqual(one["a.py"]["hash"], two["a.py"]["hash"])
        self.assertNotEqual(one["b.py"]["hash"], two["b.py"]["hash"])

    def test_sample_keeps_added_lines_up_to_twenty(self):
        files = self.parse(added("a.py", [f"line {i}" for i in range(30)]))
        self.assertEqual(files["a.py"]["sample"], [f"line {i}" for i in range(20)])
        self.assertEqual(files["a.py"]["added"], 30)

    def test_empty_diff_and_missing_file(self):
        self.assertEqual(self.parse(""), {})
        with self.assertRaises(review.Refused):
            review.parse_diff(self.tmp / "missing.patch")


class ClassifyTest(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "binary": info("src/a.py", binary=True),
            "lockfile": info("app/package-lock.json"),
            "vendor": info("vendor/acme/lib.php"),
            "generated": info("web/app.min.js"),
            "build_output": info("dist/bundle.js"),
            "rename_only": info("src/b.py", status="renamed", similarity=100, added=0),
            "logic": info("src/c.py"),
        }
        for kind, item in cases.items():
            with self.subTest(kind):
                self.assertEqual(review.classify(item), kind)

    def test_generated_marker_in_added_lines(self):
        self.assertEqual(review.classify(info("src/model.py", sample=["# Code generated by protoc. DO NOT EDIT."])),
                         "generated")
        self.assertEqual(review.classify(info("src/model.py", sample=["x = 1"])), "logic")

    def test_edited_rename_and_vendor_named_file_are_logic(self):
        self.assertEqual(review.classify(info("src/b.py", status="renamed", similarity=90)), "logic")
        self.assertEqual(review.classify(info("src/vendor.py")), "logic")  # only a directory named vendor counts

    def test_binary_wins_over_other_kinds(self):
        self.assertEqual(review.classify(info("vendor/logo.png", binary=True)), "binary")


class PackTest(unittest.TestCase):
    @staticmethod
    def files(spec: dict) -> list[dict]:
        return [info(p, added=n) for p, n in spec.items()]

    @staticmethod
    def paths(groups) -> list[list[str]]:
        return sorted(sorted(f["path"] for f in g) for g in groups)

    def assertPartition(self, groups, files, budget):
        flat = [f["path"] for g in groups for f in g]
        self.assertEqual(sorted(flat), sorted(f["path"] for f in files))  # every file exactly once
        for g in groups:
            if len(g) > 1:
                self.assertLessEqual(sum(review.size(f) for f in g), budget)

    def test_within_budget_is_one_group(self):
        files = self.files({"a/x.py": 2, "b/y.py": 3})
        self.assertEqual(self.paths(review.pack(files, 10)), [["a/x.py", "b/y.py"]])

    def test_groups_by_directory(self):
        files = self.files({"a/x.py": 3, "a/y.py": 3, "b/z.py": 4, "c/m/1.py": 2, "c/n/2.py": 2})
        groups = review.pack(files, 6)
        self.assertPartition(groups, files, 6)
        self.assertEqual(self.paths(groups), [["a/x.py", "a/y.py"], ["b/z.py"], ["c/m/1.py", "c/n/2.py"]])

    def test_large_directory_is_split_by_subdirectory(self):
        files = self.files({"d/x/1.py": 3, "d/y/2.py": 3})
        self.assertEqual(self.paths(review.pack(files, 5)), [["d/x/1.py"], ["d/y/2.py"]])

    def test_files_of_one_directory_are_split_flat(self):
        files = self.files({"d/a.py": 3, "d/b.py": 3, "d/c.py": 3, "e.py": 3})
        groups = review.pack(files, 6)
        self.assertPartition(groups, files, 6)
        self.assertEqual(self.paths(groups), [["d/a.py", "d/b.py"], ["d/c.py"], ["e.py"]])

    def test_file_larger_than_budget_gets_its_own_group(self):
        files = self.files({"a/big.py": 50, "a/small.py": 1})
        groups = review.pack(files, 10)
        self.assertPartition(groups, files, 10)
        self.assertIn(["a/big.py"], self.paths(groups))

    def test_deep_tree_terminates_and_partitions(self):
        files = self.files({f"r/{i % 3}/{i % 2}/f{i}.py": 4 for i in range(20)})
        groups = review.pack(files, 9)
        self.assertPartition(groups, files, 9)


class SmallHelpersTest(unittest.TestCase):
    def test_common_dir(self):
        self.assertEqual(review.common_dir(["src/a/x.py", "src/b/y.py"]), "src")
        self.assertEqual(review.common_dir(["src/a/x.py", "src/a/y.py"]), "src/a")
        self.assertEqual(review.common_dir(["src/x.py", "lib/y.py"]), ".")
        self.assertEqual(review.common_dir(["x.py"]), ".")

    def test_location_file(self):
        for raw, expected in {"src/x.php:42": "src/x.php", "./src/x.php:10-20": "src/x.php",
                              " src/x.php ": "src/x.php", "src/x.php:3:7": "src/x.php", "a.py": "a.py"}.items():
            with self.subTest(raw):
                self.assertEqual(review.location_file(raw), expected)


# --- usage and exit codes -------------------------------------------------------------------------


class UsageTest(ReviewTestCase):
    def test_command_without_review_folder_is_usage_error(self):
        result = self.rv("status")
        self.assertExit(result, 2)
        self.assertIn("not a review folder", result.stderr)

    def test_argument_errors_exit_2(self):
        self.init_single()
        for args in (["bogus"], ["set", "C01/G1", "done"], ["omit", "C01", "G1"], ["approve", "--coverage", "all"],
                     ["finding", "F1", "--cell", "C01/G1", "--kind", "nit", "--title", "t"], ["log", "memo", "text=x"],
                     ["chunk", "C02", "--title", "t", "--risk", "huge"], ["verify", "F1", "maybe", "--verifier", "V"]):
            with self.subTest(args=args):
                self.assertExit(self.rv(*args), 2)

    def test_init_requires_scope_and_refs(self):
        self.assertExit(self.rv("init", "--scope", "s"), 2)
        self.assertFalse((self.dir / "review.json").exists())


# --- init -----------------------------------------------------------------------------------------


class InitTest(ReviewTestCase):
    def test_plain_init_creates_the_folder(self):
        out = self.init_plain(wave_size=3)
        s = self.state()
        self.assertEqual(s["schema_version"], 1)
        self.assertEqual((s["scope"], s["wave_size"], s["single"], s["approval"]), ("s", 3, False, None))
        for key in ("chunks", "groups", "cells", "findings"):
            self.assertEqual(s[key], {})
        self.assertEqual((s["waves"], s["refreshes"]), ([], []))
        self.assertTrue((self.dir / "findings").is_dir())
        self.assertEqual([r["type"] for r in self.log()], ["init"])
        # self.tmp is no repository, so the SHAs stay unknown and the tool says so.
        self.assertIsNone(s["revision"]["base_sha"])
        self.assertIsNone(s["revision"]["repo"])
        self.assertIn("warning: base or head not resolved", out)

    def test_init_without_diff_creates_the_folder(self):
        self.ok("init", "--scope", "s", "--base", "a", "--head", "b")
        self.assertEqual(self.state()["revision"]["base"], "a")
        self.assertEqual(self.state()["wave_size"], 6)

    def test_init_twice_is_refused(self):
        self.init_plain()
        self.refused("init", "--scope", "s", "--base", "main", "--head", "HEAD", contains="already exists")

    def test_single_creates_one_chunk_groups_and_cells(self):
        diff = modified("b.py", ["a"], ["b"]) + added("a.py", ["x", "y"])
        out = self.init_single(diff, "G1=Correctness and regressions; Testability and risk coverage", "G2=Security")
        s = self.state()
        self.assertTrue(s["single"])
        self.assertEqual(list(s["chunks"]), ["C01"])
        c01 = s["chunks"]["C01"]
        self.assertEqual((c01["files"], c01["risk"], c01["treatment"]), (["a.py", "b.py"], "medium", "full"))
        self.assertEqual(s["groups"]["G1"]["perspectives"], ["Correctness and regressions",
                                                             "Testability and risk coverage"])
        self.assertEqual(s["groups"]["G2"]["perspectives"], ["Security"])
        self.assertEqual(set(s["cells"]), {"C01/G1", "C01/G2"})
        self.assertTrue(all(c["status"] == "pending" for c in s["cells"].values()))
        self.assertIn("one chunk C01 (2 files)", out)
        self.ok("validate")

    def test_single_without_groups_or_with_bad_groups_is_refused(self):
        self.write_diff(modified("a.py", ["a"], ["b"]))
        base = ["init", "--scope", "s", "--base", "main", "--head", "HEAD", "--single"]
        self.refused(*base, contains="--single needs --groups")
        for spec in ("G1", "=Security", "G1=", "G1= ; "):
            with self.subTest(spec=spec):
                self.refused(*base, "--groups", spec, contains="expected G1=")
        self.assertFalse((self.dir / "review.json").exists())

    def test_single_without_diff_is_refused_and_can_be_retried(self):
        args = ["init", "--scope", "s", "--base", "main", "--head", "HEAD", "--single", "--groups", "G1=Security"]
        self.refused(*args, contains="diff.patch")
        self.assertFalse((self.dir / "review.json").exists())
        self.write_diff(modified("a.py", ["a"], ["b"]))
        self.ok(*args)

    def test_single_estimate_counts_the_changed_lines(self):
        self.init_single(modified("a.py", ["a"], ["b", "c"]))
        self.assertIn("full: 1 chunks, 1 files, 3 changed lines", self.ok("estimate"))


class GitInitTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo = GitRepo(self.tmp / "repo", self.env)
        self.repo.commit({"a.py": "a1\n"}, "base")
        self.repo.git("tag", "base")
        self.repo.commit({"a.py": "a2\n"}, "head")
        self.write_diff(self.repo.diff("base", "HEAD"))

    def test_init_records_the_shas_of_both_refs(self):
        out = self.ok("init", "--scope", "branch", "--base", "base", "--head", "HEAD", "--single",
                      "--groups", "G1=Security", cwd=self.repo.root)
        rev = self.state()["revision"]
        self.assertEqual(rev["base_sha"], self.repo.sha("base"))
        self.assertEqual(rev["head_sha"], self.repo.sha("HEAD"))
        self.assertEqual(Path(rev["repo"]).resolve(), self.repo.root.resolve())
        self.assertFalse(rev["working_tree"])
        self.assertNotIn("warning", out)
        self.assertEqual(self.state()["chunks"]["C01"]["files"], ["a.py"])

    def test_status_reports_moved_head_until_refresh(self):
        self.ok("init", "--scope", "branch", "--base", "base", "--head", "HEAD", "--single",
                "--groups", "G1=Security", cwd=self.repo.root)
        self.assertNotIn("changed:", self.ok("status"))
        self.repo.commit({"a.py": "a3\n"}, "more")
        out = self.ok("status")  # runs outside the repository; the recorded repo is used
        self.assertIn("changed: head HEAD moved", out)
        self.assertNotIn("changed: base", out)
        self.write_diff(self.repo.diff("base", "HEAD"), "diff.new.patch")
        self.ok("refresh", str(self.dir / "diff.new.patch"))
        self.assertEqual(self.state()["revision"]["head_sha"], self.repo.sha("HEAD"))
        self.assertNotIn("changed:", self.ok("status"))

    def test_unchanged_refresh_still_records_the_new_shas(self):
        self.ok("init", "--scope", "branch", "--base", "base", "--head", "HEAD", "--single",
                "--groups", "G1=Security", cwd=self.repo.root)
        self.repo.commit({"b.txt": "x\n"}, "unrelated")
        self.repo.commit({"b.txt": None}, "revert")  # HEAD moved, the diff is the same
        self.write_diff(self.repo.diff("base", "HEAD"), "diff.new.patch")
        self.assertIn("no change", self.ok("refresh", str(self.dir / "diff.new.patch")))
        self.assertEqual(self.state()["revision"]["head_sha"], self.repo.sha("HEAD"))
        self.assertNotIn("changed:", self.ok("status"))

    def test_working_tree_review(self):
        self.repo.write({"a.py": "a-dirty\n"})
        self.write_diff(self.repo.diff("HEAD"))
        self.ok("init", "--scope", "wt", "--base", "HEAD", "--head", "HEAD", "--working-tree", "--single",
                "--groups", "G1=Security", cwd=self.repo.root)
        self.assertTrue(self.state()["revision"]["working_tree"])
        out = self.ok("status")
        self.assertIn("+ working tree", out)
        self.assertIn("working tree: changes since diff.patch show only in refresh", out)


# --- triage, chunks, chunk, group, cell, omit, estimate -------------------------------------------


TRIAGE_DIFF = (
    modified("src/api/a.py", ["o"], ["n1", "n2", "n3"])
    + added("src/api/b.py", ["x", "y"])
    + added("src/ui/c.py", ["1", "2", "3", "4", "5"])
    + added("docs/readme.md", ["hi"])
    + modified("package-lock.json", [], [f"l{i}" for i in range(10)])
    + added("vendor/lib/x.js", ["a", "b"])
    + added("web/app.min.js", ["a"])
    + added("gen/model.py", ["# @generated by tool"])
    + added("dist/bundle.js", ["a"])
    + renamed("old/n.py", "new/n.py")
    + binary("img/logo.png")
)


class TriageTest(ReviewTestCase):
    def test_triage_proposes_chunks_by_kind_and_directory(self):
        self.init_plain(TRIAGE_DIFF)
        out = self.ok("triage", "--chunk-lines", "6")
        self.assertIn("11 files", out)
        proposal = read_json(self.dir / "triage.json")
        self.assertEqual(proposal["chunk_lines"], 6)
        chunks = proposal["chunks"]

        all_files = [f for c in chunks.values() for f in c["files"]]
        self.assertEqual(sorted(all_files), sorted(review.parse_diff(self.dir / "diff.patch")))  # each once

        logic = {tuple(c["files"]): c for c in chunks.values() if c["kind"] == "logic"}
        self.assertEqual(set(logic), {("src/api/a.py", "src/api/b.py"), ("src/ui/c.py",), ("docs/readme.md",)})
        self.assertEqual(logic[("src/api/a.py", "src/api/b.py")]["title"], "src/api")
        self.assertEqual(logic[("src/api/a.py", "src/api/b.py")]["lines"], 6)
        for c in logic.values():
            self.assertEqual((c["risk"], c["treatment"]), ("medium", "full"))
            self.assertLessEqual(c["lines"], 6)

        other = {c["kind"]: c for c in chunks.values() if c["kind"] != "logic"}
        self.assertEqual(other["lockfile"]["files"], ["package-lock.json"])
        self.assertEqual(other["vendor"]["files"], ["vendor/lib/x.js"])
        self.assertEqual(other["generated"]["files"], ["gen/model.py", "web/app.min.js"])
        self.assertEqual(other["build_output"]["files"], ["dist/bundle.js"])
        self.assertEqual(other["rename_only"]["files"], ["new/n.py"])
        self.assertEqual(other["binary"]["files"], ["img/logo.png"])
        self.assertEqual(other["build_output"]["title"], "build output")
        for c in other.values():
            self.assertEqual((c["risk"], c["treatment"]), ("low", "light"))
        self.assertEqual(sorted(chunks), [f"C{i:02d}" for i in range(1, 10)])
        # triage only proposes; the state is untouched.
        self.assertEqual(self.state()["chunks"], {})

    def test_triage_default_budget_and_out(self):
        self.init_plain(TRIAGE_DIFF)
        out_path = self.tmp / "elsewhere.json"
        self.ok("triage", "--out", str(out_path))
        proposal = read_json(out_path)
        self.assertEqual(proposal["chunk_lines"], 2500)
        self.assertEqual(sum(1 for c in proposal["chunks"].values() if c["kind"] == "logic"), 1)
        self.assertFalse((self.dir / "triage.json").exists())

    def test_triage_without_diff_is_refused(self):
        self.ok("init", "--scope", "s", "--base", "a", "--head", "b")
        self.refused("triage", contains="diff.patch")

    def test_chunks_estimate_and_validate_flow(self):
        self.init_plain(TRIAGE_DIFF)
        self.ok("triage", "--chunk-lines", "6")
        self.assertIn("loaded 9 chunks", self.ok("chunks", str(self.dir / "triage.json")))
        s = self.state()
        self.assertEqual(s["chunks"], read_json(self.dir / "triage.json")["chunks"])
        self.assertEqual(self.log()[-1]["type"], "chunks")

        result = self.rv("validate")
        self.assertExit(result, 1)
        self.assertIn("no cells", result.stdout)

        self.ok("group", "G1", "--perspectives", "Correctness and regressions")
        for cid, chunk in s["chunks"].items():
            if chunk["kind"] == "logic":
                self.ok("cell", cid, "G1")
            else:
                self.ok("omit", cid, "--groups", "G1", "--reason", "not logic")
        out = self.ok("estimate")
        self.assertIn("full: 3 chunks, 4 files, 12 changed lines", out)
        self.assertIn("light: 6 chunks, 7 files, 15 changed lines", out)
        self.assertIn("cells: pending 3, omitted 6", out)
        self.assertIn("waves of 6: 1 (about 3 reviewer runs, 0 of them integration)", out)
        self.assertIn("ok: 9 cells", self.ok("validate"))

    def test_chunks_applies_defaults_and_rejects_invalid(self):
        self.init_plain(modified("a.py", ["a"], ["b"]))
        proposal = self.tmp / "p.json"
        write_json(proposal, {"chunks": {"C01": {"title": "a", "files": ["a.py"]}}})
        self.ok("chunks", str(proposal))
        self.assertEqual(self.state()["chunks"]["C01"]["risk"], "medium")
        self.assertEqual(self.state()["chunks"]["C01"]["treatment"], "full")

        for bad, message in (({"risk": "huge"}, "risk must be"), ({"treatment": "excluded"}, "excluded needs")):
            with self.subTest(bad=bad):
                write_json(proposal, {"chunks": {"C01": {"title": "a", "files": ["a.py"]},
                                                 "C02": {"title": "b", "files": [], **bad}}})
                self.refused("chunks", str(proposal), contains=message)
                self.assertNotIn("C02", self.state()["chunks"])  # nothing of a refused proposal is saved

        write_json(proposal, {"chunks": {"C02": {"title": "b", "files": [], "treatment": "excluded",
                                                 "reason": "generated"}}})
        self.ok("chunks", str(proposal))
        self.assertEqual(self.state()["chunks"]["C02"]["treatment"], "excluded")

    def test_chunks_refuses_a_chunk_with_reviewed_cells(self):
        self.init_plain(modified("a.py", ["a"], ["b"]))
        proposal = self.tmp / "p.json"
        write_json(proposal, {"chunks": {"C01": {"title": "a", "files": ["a.py"]}}})
        self.ok("chunks", str(proposal))
        self.ok("group", "G1", "--perspectives", "Security")
        self.ok("cell", "C01", "G1")
        self.ok("chunks", str(proposal))  # pending cells only: reload allowed
        self.ok("start", "--owner", "R1", "C01/G1")
        self.refused("chunks", str(proposal), contains="already has reviewed cells")

    def test_chunks_with_invalid_json_is_refused(self):
        self.init_plain()
        (self.tmp / "p.json").write_text("{nope")
        self.refused("chunks", str(self.tmp / "p.json"), contains="invalid JSON")
        self.refused("chunks", str(self.tmp / "missing.json"), contains="missing")


class ChunkGroupCellTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.init_plain(modified("a.py", ["a"], ["b"]) + modified("b.py", ["a"], ["b"]))

    def test_chunk_create_and_integration(self):
        out = self.ok("chunk", "C01", "--title", "core", "--files", "b.py", "a.py", "a.py", "--risk", "high")
        self.assertIn("chunk C01: logic, full, 2 files", out)
        c = self.state()["chunks"]["C01"]
        self.assertEqual((c["files"], c["risk"], c["kind"], c["title"]), (["a.py", "b.py"], "high", "logic", "core"))
        self.ok("chunk", "CI", "--title", "links", "--integration")
        ci = self.state()["chunks"]["CI"]
        self.assertEqual((ci["kind"], ci["files"]), ("integration", []))
        self.assertEqual(self.log()[-1]["type"], "chunk")

    def test_chunk_change_keeps_files_unless_given(self):
        self.ok("chunk", "C01", "--title", "core", "--files", "a.py")
        self.ok("chunk", "C01", "--title", "renamed")
        self.assertEqual(self.state()["chunks"]["C01"]["files"], ["a.py"])
        self.assertEqual(self.state()["chunks"]["C01"]["title"], "renamed")

    def test_chunk_change_keeps_risk_and_treatment_unless_given(self):
        self.ok("chunk", "C01", "--title", "core", "--files", "a.py", "--risk", "high")
        self.ok("chunk", "C01", "--title", "renamed")
        self.assertEqual(self.state()["chunks"]["C01"]["risk"], "high")

    def test_chunk_files_set_the_changed_lines(self):
        self.ok("chunk", "C01", "--title", "core", "--files", "a.py", "missing.py")
        self.assertEqual(self.state()["chunks"]["C01"]["lines"], 2)
        self.ok("chunk", "C01", "--title", "core", "--files", "a.py", "b.py")
        self.assertEqual(self.state()["chunks"]["C01"]["lines"], 4)

    def test_excluded_chunk_needs_a_reason(self):
        self.refused("chunk", "C09", "--title", "x", "--treatment", "excluded", contains="excluded needs --reason")
        self.assertNotIn("C09", self.state()["chunks"])
        self.ok("chunk", "C09", "--title", "x", "--files", "b.py", "--treatment", "excluded", "--reason", "lockfile")
        self.assertEqual(self.state()["chunks"]["C09"]["reason"], "lockfile")

    def test_group_title_defaults_to_the_perspectives(self):
        self.ok("group", "G1", "--perspectives", "Security", "Performance")
        self.assertEqual(self.state()["groups"]["G1"], {"title": "Security, Performance",
                                                        "perspectives": ["Security", "Performance"]})
        self.ok("group", "G2", "--perspectives", "Security", "--title", "Sec")
        self.assertEqual(self.state()["groups"]["G2"]["title"], "Sec")

    def test_cell_and_omit(self):
        self.ok("chunk", "C01", "--title", "all", "--files", "a.py", "b.py")
        self.ok("group", "G1", "--perspectives", "Security")
        self.ok("group", "G2", "--perspectives", "Performance")
        self.refused("cell", "C99", "G1", contains="unknown chunk C99")
        self.refused("cell", "C01", "G9", contains="unknown group G9")
        self.refused("omit", "C99", "--groups", "G1", "--reason", "r", contains="unknown chunk")

        self.ok("cell", "C01", "G1", "G2")
        self.assertEqual(self.state()["cells"]["C01/G1"],
                         {"status": "pending", "owner": None, "wave": None, "unchecked": []})
        self.ok("omit", "C01", "--groups", "G2", "--reason", "no hot paths")
        self.assertEqual(self.state()["cells"]["C01/G2"], {"status": "omitted", "reason": "no hot paths"})
        # cell turns an omission back into a pending cell
        self.ok("cell", "C01", "G2")
        self.assertEqual(self.state()["cells"]["C01/G2"]["status"], "pending")

        # cell never resets a reviewed cell, and omit refuses it
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G1", "covered")
        self.ok("cell", "C01", "G1")
        self.assertEqual(self.state()["cells"]["C01/G1"]["status"], "covered")
        self.refused("omit", "C01", "--groups", "G1", "--reason", "r", contains="already covered")


# --- waves: approve, next, start, set -------------------------------------------------------------


class WaveTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.init_plain(modified("h.py", ["a"], ["b"]) + modified("m.py", ["a"], ["b"]) + modified("l.py", ["a"], ["b"]))
        self.ok("chunk", "CH", "--title", "high", "--files", "h.py", "--risk", "high")
        self.ok("chunk", "CM", "--title", "medium", "--files", "m.py", "--risk", "medium")
        self.ok("chunk", "CL", "--title", "low", "--files", "l.py", "--risk", "low")
        self.ok("group", "G1", "--perspectives", "Correctness and regressions")
        for cid in ("CL", "CM", "CH"):
            self.ok("cell", cid, "G1")

    def test_next_orders_by_risk_and_follow_ups_first(self):
        self.assertEqual(self.first_tokens(self.ok("next")), ["CH/G1", "CM/G1", "CL/G1"])
        self.ok("set", "CL/G1", "partial", "--unchecked", "l.py")
        out = self.ok("next")
        self.assertEqual(self.first_tokens(out), ["CL/G1", "CH/G1", "CM/G1"])
        self.assertIn("follow-up: l.py", out)
        self.assertIn("[high/full]", out)
        self.assertEqual(self.first_tokens(self.ok("next", "--limit", "2")), ["CL/G1", "CH/G1"])

    def test_next_counts_running_cells_against_the_slots(self):
        self.ok("start", "--owner", "R1", "CH/G1")
        out = self.ok("next", "--limit", "2")
        self.assertIn("running: CH/G1", out)
        self.assertEqual([t for t in self.first_tokens(out) if "/" in t and t != "running:"], ["CM/G1"])
        out = self.ok("next", "--limit", "1")
        self.assertIn("no free slot in the current wave", out)
        self.assertNotIn("CM/G1", out)

    def test_next_needs_approval_for_more_than_one_wave(self):
        s = self.state()
        s["wave_size"] = 2
        write_json(self.dir / "review.json", s)
        self.assertIn("waves of 2: 2 (about 3 reviewer runs", self.ok("estimate"))
        self.refused("next", contains="approve")
        self.assertIn("more than one wave", self.rv("validate").stdout)
        self.ok("approve", "--coverage", "full", "--note", "ok by user")
        approval = self.state()["approval"]
        self.assertEqual((approval["coverage"], approval["note"]), ("full", "ok by user"))
        self.assertEqual(self.log()[-1]["type"], "decision")
        self.assertEqual(self.first_tokens(self.ok("next")), ["CH/G1", "CM/G1"])

    def test_risk_first_leaves_low_risk_cells_open(self):
        self.ok("approve", "--coverage", "risk_first")
        self.assertEqual(self.first_tokens(self.ok("next")), ["CH/G1", "CM/G1"])
        self.ok("set", "CH/G1", "covered")
        self.ok("set", "CM/G1", "covered")
        self.assertIn("no cell is ready", self.ok("next"))
        self.assertIn("open CL/G1 (pending)", self.ok("coverage"))

    def test_integration_cells_wait_for_local_cells(self):
        self.ok("chunk", "CI", "--title", "links", "--integration", "--risk", "high")
        self.ok("cell", "CI", "G1")
        self.assertNotIn("CI/G1", self.ok("next"))
        self.ok("start", "--owner", "R1", "CH/G1", "CM/G1", "CL/G1")
        self.assertIn("no cell is ready (integration waits for the local cells)", self.ok("next"))
        for cid in ("CH", "CM"):
            self.ok("set", f"{cid}/G1", "covered")
        self.ok("set", "CL/G1", "partial", "--unchecked", "l.py")
        self.assertEqual(self.first_tokens(self.ok("next")), ["CL/G1"])  # a partial local cell is still open
        self.ok("set", "CL/G1", "covered")
        self.assertEqual(self.first_tokens(self.ok("next")), ["CI/G1"])
        self.assertIn("1 of them integration", self.ok("estimate"))

    def test_integration_ignores_low_risk_cells_skipped_by_risk_first(self):
        self.ok("chunk", "CI", "--title", "links", "--integration")
        self.ok("cell", "CI", "G1")
        self.ok("approve", "--coverage", "risk_first")
        self.ok("set", "CH/G1", "covered")
        self.ok("set", "CM/G1", "covered")
        self.assertEqual(self.first_tokens(self.ok("next")), ["CI/G1"])

    def test_start_groups_parallel_runs_into_waves(self):
        self.assertIn("wave 1: R1 -> CH/G1", self.ok("start", "--owner", "R1", "CH/G1"))
        self.assertIn("wave 1: R2 -> CM/G1", self.ok("start", "--owner", "R2", "CM/G1"))
        s = self.state()
        self.assertEqual(len(s["waves"]), 1)
        self.assertEqual(s["waves"][0]["cells"], ["CH/G1", "CM/G1"])
        self.assertEqual((s["cells"]["CM/G1"]["status"], s["cells"]["CM/G1"]["owner"], s["cells"]["CM/G1"]["wave"]),
                         ("running", "R2", 1))
        self.ok("set", "CH/G1", "covered")
        self.ok("set", "CM/G1", "covered")
        self.assertIn("wave 2: R3 -> CL/G1", self.ok("start", "--owner", "R3", "CL/G1"))
        self.assertEqual([w["wave"] for w in self.state()["waves"]], [1, 2])
        self.assertEqual(self.log()[-1], {**self.log()[-1], "type": "cell", "ids": ["CL/G1"], "status": "running",
                                          "owner": "R3", "wave": 2})

    def test_start_refuses_closed_or_unknown_cells(self):
        self.ok("set", "CH/G1", "covered")
        self.refused("start", "--owner", "R1", "CM/G1", "CH/G1", contains="CH/G1 is covered")
        self.assertEqual(self.state()["cells"]["CM/G1"]["status"], "pending")  # all or nothing
        self.assertEqual(self.state()["waves"], [])
        self.refused("start", "--owner", "R1", "CX/G1", contains="unknown cell")
        self.refused("start", "--owner", "R1", "CH", contains="unknown cell")

    def test_set_records_coverage(self):
        self.ok("start", "--owner", "R1", "CH/G1")
        self.refused("set", "CH/G1", "partial", contains="--unchecked")
        self.refused("set", "CH/G1", "omitted", contains="--reason")
        self.assertIn("CH/G1: running -> partial", self.ok("set", "CH/G1", "partial", "--unchecked", "h.py",
                                                            "error paths"))
        self.assertEqual(self.state()["cells"]["CH/G1"]["unchecked"], ["h.py", "error paths"])
        record = self.log()[-1]
        self.assertEqual((record["id"], record["status"], record["from"], record["unchecked"]),
                         ("CH/G1", "partial", "running", ["h.py", "error paths"]))
        self.ok("set", "CH/G1", "covered")
        self.assertEqual(self.state()["cells"]["CH/G1"]["unchecked"], [])
        self.ok("set", "CM/G1", "omitted", "--reason", "nothing to check")
        self.assertEqual(self.state()["cells"]["CM/G1"]["reason"], "nothing to check")
        self.refused("set", "CX/G1", "covered", contains="unknown cell")

    def test_set_pending_returns_a_lost_run_to_the_queue(self):
        self.ok("start", "--owner", "R1", "CH/G1")
        self.ok("set", "CH/G1", "pending")
        cell = self.state()["cells"]["CH/G1"]
        self.assertEqual((cell["status"], cell["owner"], cell["wave"]), ("pending", None, None))
        self.assertIn("CH/G1", self.first_tokens(self.ok("next")))


# --- findings -------------------------------------------------------------------------------------


class FindingTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.init_single(modified("src/a.py", ["a"], ["b"]))
        self.ok("start", "--owner", "R1", "C01/G1")

    def test_finding_needs_its_file_and_a_unique_id(self):
        self.refused("finding", "R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t",
                     contains="write findings/R1-01.md")
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")
        self.refused("finding", "R1-01", "--cell", "C01/G1", "--kind", "question", "--title", "again",
                     contains="already exists")
        self.write_finding("R1-02")
        self.refused("finding", "R1-02", "--cell", "C01/G1", "--kind", "bug", "--title", "t", contains="--severity")
        self.refused("finding", "R1-02", "--cell", "C09/G1", "--kind", "question", "--title", "t",
                     contains="unknown cell")
        self.assertEqual(list(self.state()["findings"]), ["R1-01"])

    def test_finding_record(self):
        out = self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "Crash",
                               "--files", "./src/a.py:12", "src/a.py:20-30")
        self.assertNotIn("warning", out)
        f = self.state()["findings"]["R1-01"]
        self.assertEqual(f, {"cell": "C01/G1", "reviewer": "R1", "kind": "bug", "severity": "high", "title": "Crash",
                             "files": ["src/a.py"], "outside": False, "status": "unverified", "verifications": []})
        self.assertEqual(self.log()[-1]["type"], "finding")

    def test_finding_outside_the_diff(self):
        out = self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "recommendation", "--title", "t",
                               "--files", "lib/other.py:3")
        self.assertIn("warning: not in diff.patch", out)
        self.assertIn("lib/other.py", out)
        out = self.add_finding("R1-02", "--cell", "C01/G1", "--kind", "bug", "--severity", "low", "--title", "old bug",
                               "--files", "lib/other.py", "--outside")
        self.assertNotIn("warning", out)
        self.assertTrue(self.state()["findings"]["R1-02"]["outside"])
        self.assertIn("(outside the change)", self.ok("findings"))

    def test_explicit_reviewer(self):
        self.add_finding("X-01", "--cell", "C01/G2", "--kind", "question", "--title", "t", "--reviewer", "R9")
        self.assertEqual(self.state()["findings"]["X-01"]["reviewer"], "R9")
        self.refused("verify", "X-01", "confirmed", "--verifier", "R9", contains="never the sole verifier")

    def test_verification_rules(self):
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")
        self.refused("verify", "R1-01", "confirmed", "--verifier", "R1", contains="never the sole verifier")
        self.refused("verify", "R9-99", "confirmed", "--verifier", "V1", contains="unknown finding")

        self.assertIn("R1-01: confirmed", self.ok("verify", "R1-01", "confirmed", "--verifier", "V1"))
        self.assertIn("R1-01: confirmed", self.ok("verify", "R1-01", "confirmed", "--verifier", "V2"))
        out = self.ok("verify", "R1-01", "refuted", "--verifier", "V3")
        self.assertIn("R1-01: disputed", out)
        f = self.state()["findings"]["R1-01"]
        self.assertEqual([v["verifier"] for v in f["verifications"]], ["V1", "V2", "V3"])
        self.assertEqual(self.log()[-1]["type"], "verification")

    def test_critical_and_disputed_findings_need_a_second_verifier(self):
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")
        out = self.ok("verify", "R1-01", "confirmed", "--verifier", "V1", "--severity", "critical")
        self.assertIn("needs a second verifier", out)
        self.assertEqual(self.state()["findings"]["R1-01"]["severity"], "critical")
        self.assertIn("needs a second verifier: R1-01", self.ok("status"))
        self.assertIn("critical needs a second verifier", self.ok("validate"))
        out = self.ok("verify", "R1-01", "confirmed", "--verifier", "V2")
        self.assertNotIn("needs a second verifier", out)
        self.assertNotIn("needs a second verifier", self.ok("status"))

        self.add_finding("R1-02", "--cell", "C01/G1", "--kind", "bug", "--severity", "low", "--title", "t")
        self.assertNotIn("second", self.ok("verify", "R1-02", "confirmed", "--verifier", "V1"))
        # the same verifier changing its mind is a dispute that still needs a second verifier
        self.assertIn("needs a second verifier", self.ok("verify", "R1-02", "refuted", "--verifier", "V1"))

    def test_resolve(self):
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")
        self.add_finding("R1-02", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "same")
        self.refused("resolve", "R1-02", "duplicate", "--reason", "r", contains="--duplicate-of")
        self.refused("resolve", "R1-02", "duplicate", "--reason", "r", "--duplicate-of", "R9-09",
                     contains="unknown finding R9-09")
        self.assertEqual(self.state()["findings"]["R1-02"]["status"], "unverified")
        self.assertIn("R1-02: unverified -> duplicate",
                      self.ok("resolve", "R1-02", "duplicate", "--reason", "same as R1-01", "--duplicate-of", "R1-01"))
        f = self.state()["findings"]["R1-02"]
        self.assertEqual((f["status"], f["duplicate_of"], f["resolution"]), ("duplicate", "R1-01", "same as R1-01"))
        self.ok("resolve", "R1-01", "awaiting_decision", "--reason", "business rule")
        record = self.log()[-1]
        self.assertEqual((record["status"], record["from"], record["reason"]),
                         ("awaiting_decision", "unverified", "business rule"))
        self.refused("resolve", "R9-01", "confirmed", "--reason", "r", contains="unknown finding")

    def test_findings_index(self):
        self.ok("chunk", "C02", "--title", "other", "--files")
        self.ok("cell", "C02", "G1")
        specs = {"A-1": ("C01/G1", "bug", "low"), "A-2": ("C01/G1", "bug", "critical"),
                 "A-3": ("C01/G2", "question", None), "A-4": ("C02/G1", "bug", "medium"),
                 "A-5": ("C01/G1", "bug", "high"), "A-6": ("C01/G1", "recommendation", "high")}
        for fid, (cell, kind, severity) in specs.items():
            self.add_finding(fid, "--cell", cell, "--kind", kind, "--title", f"title {fid}",
                             *(["--severity", severity] if severity else []), "--reviewer", "R1")
        self.ok("verify", "A-5", "refuted", "--verifier", "V1")
        self.ok("resolve", "A-6", "duplicate", "--reason", "r", "--duplicate-of", "A-2")

        self.assertEqual(self.first_tokens(self.ok("findings")), ["A-2", "A-4", "A-1", "A-3"])
        self.assertEqual(self.first_tokens(self.ok("findings", "--all")), ["A-2", "A-5", "A-6", "A-4", "A-1", "A-3"])
        self.assertEqual(self.first_tokens(self.ok("findings", "--status", "refuted")), ["A-5"])
        self.assertEqual(self.first_tokens(self.ok("findings", "--chunk", "C02")), ["A-4"])
        out = self.ok("findings")
        self.assertIn("A-2  [critical/bug/unverified]  C01/G1  title A-2", out)
        self.assertIn("A-3  [-/question/unverified]", out)
        self.assertEqual(self.ok("findings", "--status", "confirmed").strip(), "no findings")
        self.assertIn("findings: duplicate 1, refuted 1, unverified 4", self.ok("status"))


# --- coverage, status, validate, log --------------------------------------------------------------


class CoverageTest(ReviewTestCase):
    def test_coverage_lists_gaps_until_complete(self):
        self.init_plain(modified("a.py", ["a"], ["b"]) + modified("b.py", ["a"], ["b"]) + modified("c.lock", [], ["x"]))
        self.ok("chunk", "C01", "--title", "a", "--files", "a.py")
        self.ok("chunk", "C02", "--title", "lock", "--files", "c.lock", "--treatment", "excluded",
                "--reason", "lockfile")
        self.ok("group", "G1", "--perspectives", "Security")
        self.ok("group", "G2", "--perspectives", "Performance")
        self.ok("cell", "C01", "G1")
        self.ok("omit", "C01", "--groups", "G2", "--reason", "no loops")
        out = self.ok("coverage")
        self.assertIn("open C01/G1 (pending)", out)
        self.assertIn("omitted C01/G2: no loops", out)
        self.assertIn("excluded C02 (1 files): lockfile", out)
        self.assertIn("gap: b.py: in diff.patch but in no chunk", out)
        self.assertIn("2 open items", out)

        self.ok("chunk", "C01", "--title", "a", "--files", "a.py", "b.py")
        self.ok("set", "C01/G1", "partial", "--unchecked", "b.py")
        out = self.ok("coverage")
        self.assertIn("open C01/G1 (partial): b.py", out)
        self.assertIn("1 open items", out)
        self.ok("set", "C01/G1", "covered")
        out = self.ok("coverage")
        self.assertIn("coverage complete", out)
        self.assertIn("omitted C01/G2", out)  # omissions and exclusions stay reported

    def test_chunk_without_cells_is_a_gap(self):
        self.init_plain(modified("a.py", ["a"], ["b"]))
        self.ok("chunk", "C01", "--title", "a", "--files", "a.py")
        self.assertIn("gap: chunk C01: no cells", self.ok("coverage"))


class StatusTest(ReviewTestCase):
    def test_status_overview(self):
        self.init_single(modified("a.py", ["a"], ["b"]), "G1=Security", "G2=Performance", "G3=Readability")
        out = self.ok("status")
        self.assertIn("scope: s  base main head HEAD", out)
        self.assertNotIn("working tree", out)
        self.assertIn("approval: none; wave size 6; waves started 0, still needed 1", out)
        self.assertIn("chunks 1, groups 3; cells: pending 3", out)
        self.assertIn("ready cells: 3 (next: C01/G1, C01/G2, C01/G3)", out)

        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G2", "covered")
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")
        out = self.ok("status")
        self.assertIn("waves started 1", out)
        self.assertIn("cells: pending 1, running 1, covered 1", out)
        self.assertIn("running: C01/G1 (R1, wave 1)", out)
        self.assertIn("findings: unverified 1", out)
        self.assertIn("ready cells: 1 (next: C01/G3)", out)


class ValidateTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.init_single(modified("a.py", ["a"], ["b"]))
        self.ok("start", "--owner", "R1", "C01/G1")
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")

    def corrupt(self, change) -> str:
        s = self.state()
        change(s)
        write_json(self.dir / "review.json", s)
        result = self.rv("validate")
        self.assertExit(result, 1)
        return result.stdout

    def test_valid_review(self):
        self.assertIn("ok: 2 cells, 1 findings, 0 warnings", self.ok("validate"))

    def test_state_errors(self):
        cases = {
            "invalid risk 'huge'": lambda s: s["chunks"]["C01"].update(risk="huge"),
            "invalid treatment": lambda s: s["chunks"]["C01"].update(treatment="skip"),
            "excluded without a reason": lambda s: s["chunks"]["C01"].update(treatment="excluded"),
            "group G1: no perspectives": lambda s: s["groups"]["G1"].update(perspectives=[]),
            "cell C01/G9: unknown group": lambda s: s["cells"].update({"C01/G9": {"status": "pending"}}),
            "cell C09/G1: unknown chunk": lambda s: s["cells"].update({"C09/G1": {"status": "pending"}}),
            "invalid status 'done'": lambda s: s["cells"]["C01/G2"].update(status="done"),
            "partial without the unchecked": lambda s: s["cells"]["C01/G2"].update(status="partial", unchecked=[]),
            "omitted without a reason": lambda s: s["cells"]["C01/G2"].update(status="omitted"),
            "unknown cell 'C09/G1'": lambda s: s["findings"]["R1-01"].update(cell="C09/G1"),
            "finding R1-01: invalid status": lambda s: s["findings"]["R1-01"].update(status="fixed"),
            "duplicate of unknown R9": lambda s: s["findings"]["R1-01"].update(duplicate_of="R9"),
            "verified by its own reviewer R1": lambda s: s["findings"]["R1-01"]["verifications"].append(
                {"verifier": "R1", "verdict": "confirmed"}),
            "a.py: in diff.patch but in no chunk": lambda s: s["chunks"]["C01"].update(files=[]),
            "chunks must be an object": lambda s: s.update(chunks=[]),
        }
        original = self.state()
        for message, change in cases.items():
            with self.subTest(message):
                write_json(self.dir / "review.json", original)
                self.assertIn(message, self.corrupt(change))

    def test_missing_finding_file_and_bad_log(self):
        (self.dir / "findings" / "R1-01.md").unlink()
        result = self.rv("validate")
        self.assertExit(result, 1)
        self.assertIn("missing findings/R1-01.md", result.stdout)
        self.write_finding("R1-01")
        with (self.dir / "log.jsonl").open("a") as f:
            f.write('{"note": "no type"}\n')
        result = self.rv("validate")
        self.assertExit(result, 1)
        self.assertIn("missing at or type", result.stdout)

    def test_warnings_do_not_fail(self):
        self.ok("group", "G3", "--perspectives", "Readability")
        self.ok("chunk", "C02", "--title", "ghost", "--files", "ghost.py")
        self.ok("cell", "C02", "G1", "G2", "G3")
        out = self.ok("validate")
        self.assertIn("warning: C01: group G3 neither assigned nor omitted", out)
        self.assertIn("warning: ghost.py: in a chunk but not in diff.patch", out)
        (self.dir / "diff.patch").unlink()
        self.assertIn("warning: diff.patch not found", self.ok("validate"))


class LogTest(ReviewTestCase):
    def test_log_records(self):
        self.init_plain()
        out = self.ok("log", "check", "subject=make test", "result=pass", "count=3", "ok=true")
        self.assertIn("logged", out)
        record = self.log()[-1]
        self.assertEqual({k: v for k, v in record.items() if k != "at"},
                         {"type": "check", "subject": "make test", "result": "pass", "count": 3, "ok": True})
        self.assertTrue(record["at"].endswith("Z"))
        self.ok("log", "decision", "text=keep the API")
        self.ok("log", "note", "text=a=b")
        self.assertEqual(self.log()[-1]["text"], "a=b")
        self.refused("log", "check", "subject=x", contains="check needs: result")
        self.refused("log", "note", contains="note needs: text")

    def test_malformed_pair_is_a_usage_error(self):
        self.init_plain()
        self.assertExit(self.rv("log", "note", "text=x", "oops"), 2)

    def test_fields_cannot_set_the_type_or_time(self):
        self.init_plain()
        for field in ("type=check", "at=2000-01-01T00:00:00Z"):
            with self.subTest(field=field):
                result = self.rv("log", "note", "text=x", field)
                self.assertExit(result, 2)
                self.assertIn("is set by the tool", result.stderr)
        self.assertEqual([r["type"] for r in self.log()], ["init"])

    def test_every_change_is_logged(self):
        self.init_single(modified("a.py", ["a"], ["b"]))
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G1", "covered")
        self.ok("approve", "--coverage", "full")
        types = [r["type"] for r in self.log()]
        self.assertEqual(types, ["init", "cell", "cell", "decision"])
        self.assertTrue(all("at" in r for r in self.log()))


# --- refresh --------------------------------------------------------------------------------------


class SingleRefreshTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.old = modified("x.py", ["a"], ["b"])
        self.init_single(self.old, "G1=Security", "G2=Performance")

    def cover_all(self):
        self.ok("start", "--owner", "R1", "C01/G1", "C01/G2")
        self.ok("set", "C01/G1", "covered")
        self.ok("set", "C01/G2", "covered")

    def test_refuses_diff_patch_itself_and_a_missing_file(self):
        self.refused("refresh", str(self.dir / "diff.patch"), contains="another file")
        self.refused("refresh", str(self.dir / "nope.patch"), contains="missing")

    def test_no_change_ignores_index_abbreviations(self):
        self.cover_all()
        fresh = self.write_diff(modified("x.py", ["a"], ["b"], index="111111111..222222222"), "diff.new.patch")
        out = self.ok("refresh", str(fresh))
        self.assertIn("no change", out)
        s = self.state()
        self.assertEqual(s["refreshes"], [])
        self.assertTrue(all(c["status"] == "covered" for c in s["cells"].values()))
        self.assertEqual((self.dir / "diff.patch").read_text(), self.old)
        self.assertFalse((self.dir / "previous").exists())
        record = self.log()[-1]
        self.assertEqual((record["type"], record["changed"], record["added"], record["removed"]),
                         ("refresh", [], [], []))

    def test_dry_run_changes_nothing(self):
        self.cover_all()
        fresh = self.write_diff(modified("x.py", ["a"], ["CHANGED"]), "diff.new.patch")
        before, log_before = self.state(), self.log()
        out = self.ok("refresh", str(fresh), "--dry-run")
        self.assertIn("changed 1, added 0, removed 0 files", out)
        self.assertIn("reopen C01/G1 (covered -> partial): 1 files to recheck", out)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.log(), log_before)
        self.assertTrue(fresh.exists())
        self.assertEqual((self.dir / "diff.patch").read_text(), self.old)
        self.assertFalse((self.dir / "previous").exists())

    def test_refresh_recounts_the_changed_lines(self):
        fresh = self.write_diff(modified("x.py", ["a"], ["b", "c", "d"]) + modified("y.py", [], ["e"]), "diff.new.patch")
        self.ok("refresh", str(fresh))
        self.assertEqual(self.state()["chunks"]["C01"]["lines"], 5)
        self.assertIn("full: 1 chunks, 2 files, 5 changed lines", self.ok("estimate"))

    def test_running_cell_on_changed_file_is_refused(self):
        self.ok("start", "--owner", "R1", "C01/G1")
        fresh = self.write_diff(modified("x.py", ["a"], ["CHANGED"]), "diff.new.patch")
        self.refused("refresh", str(fresh), contains="running cells on changed files: C01/G1")
        self.assertEqual((self.dir / "diff.patch").read_text(), self.old)
        self.assertTrue(fresh.exists())
        self.assertFalse((self.dir / "previous").exists())
        # a lost run returned to the queue unblocks the refresh; pending cells stay pending
        self.ok("set", "C01/G1", "pending")
        self.ok("refresh", str(fresh))
        self.assertEqual(self.state()["cells"]["C01/G1"]["status"], "pending")
        self.assertEqual(self.state()["cells"]["C01/G2"]["status"], "pending")

    def test_added_file_joins_c01_and_reopens_cells(self):
        self.cover_all()
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t")
        self.ok("resolve", "R1-01", "awaiting_decision", "--reason", "ask the user")
        new = self.old + added("y.py", ["z"])
        fresh = self.write_diff(new, "diff.new.patch")
        out = self.ok("refresh", str(fresh))
        self.assertNotIn("without cells", out)
        s = self.state()
        self.assertEqual(list(s["chunks"]), ["C01"])
        self.assertEqual(s["chunks"]["C01"]["files"], ["x.py", "y.py"])
        for key in ("C01/G1", "C01/G2"):
            self.assertEqual((s["cells"][key]["status"], s["cells"][key]["unchecked"]), ("partial", ["y.py"]))
        # a finding without files is judged by its whole chunk
        f = s["findings"]["R1-01"]
        self.assertEqual(f["status"], "stale")
        self.assertEqual(f["refreshes"][0]["status"], "awaiting_decision")
        self.assertIn("stale, was awaiting_decision", self.ok("findings"))
        # diff.patch replaced by the fresh diff, which was moved from the review folder
        self.assertEqual((self.dir / "diff.patch").read_text(), new)
        self.assertEqual((self.dir / "previous" / "diff-01.patch").read_text(), self.old)
        self.assertFalse(fresh.exists())
        self.assertIn("ok:", self.ok("validate"))
        out = self.ok("verify", "R1-01", "confirmed", "--verifier", "V1")
        self.assertIn("was awaiting_decision before the refresh", out)
        self.assertEqual(self.state()["findings"]["R1-01"]["status"], "confirmed")

    def test_fresh_diff_outside_the_folder_is_copied_and_refreshes_are_numbered(self):
        self.cover_all()
        first = self.tmp / "fresh1.patch"
        first.write_text(modified("x.py", ["a"], ["v2"]))
        self.ok("refresh", str(first))
        self.assertTrue(first.exists())
        self.assertEqual((self.dir / "diff.patch").read_text(), first.read_text())
        second = self.tmp / "fresh2.patch"
        second.write_text(modified("x.py", ["a"], ["v3"]))
        self.assertIn("refresh 2", self.ok("refresh", str(second)))
        self.assertEqual((self.dir / "previous" / "diff-02.patch").read_text(), first.read_text())
        self.assertEqual([r["previous"] for r in self.state()["refreshes"]],
                         ["previous/diff-01.patch", "previous/diff-02.patch"])

    def test_removed_file_closes_partial_cells_and_stales_findings_on_it(self):
        two = self.old + modified("w.py", ["a"], ["b"])
        self.write_diff(two)
        self.ok("chunk", "C01", "--title", "whole diff", "--files", "x.py", "w.py")
        self.ok("start", "--owner", "R1", "C01/G1", "C01/G2")
        self.ok("set", "C01/G1", "partial", "--unchecked", "w.py")
        self.ok("set", "C01/G2", "covered")
        self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "low", "--title", "t",
                         "--files", "w.py:3")
        self.add_finding("R1-02", "--cell", "C01/G2", "--kind", "bug", "--severity", "low", "--title", "t",
                         "--files", "x.py")
        self.ok("verify", "R1-02", "refuted", "--verifier", "V1")
        self.add_finding("R1-03", "--cell", "C01/G2", "--kind", "question", "--title", "t", "--files", "x.py")
        fresh = self.write_diff(self.old, "diff.new.patch")
        self.ok("refresh", str(fresh))
        s = self.state()
        self.assertEqual(s["chunks"]["C01"]["files"], ["x.py"])
        self.assertEqual(s["cells"]["C01/G1"]["status"], "covered")  # its unchecked file left the diff
        self.assertEqual(s["cells"]["C01/G2"]["status"], "covered")  # removal alone reopens nothing
        self.assertEqual(s["findings"]["R1-01"]["status"], "stale")
        self.assertEqual(s["findings"]["R1-01"]["refreshes"][0]["files"], ["w.py"])
        self.assertEqual(s["findings"]["R1-02"]["status"], "refuted")  # settled findings stay
        self.assertEqual(s["findings"]["R1-03"]["status"], "unverified")  # its file did not change
        self.assertEqual(s["refreshes"][0]["removed"], ["w.py"])


class GitRefreshTest(ReviewTestCase):
    """A multi-chunk review over a real repository whose head moves during the review."""

    def test_refresh_reopens_cells_and_stales_findings(self):
        repo = GitRepo(self.tmp / "repo", self.env)
        repo.commit({"src/a.py": "a1\n", "src/b.py": "b1\n", "lib/c.py": "c1\n", "old.py": "o1\n"}, "base")
        repo.git("tag", "base")
        repo.commit({"src/a.py": "a2\n", "src/b.py": "b2\n", "lib/c.py": "c2\n", "old.py": "o2\n"}, "head 1")
        old_diff = repo.diff("base", "HEAD")
        self.write_diff(old_diff)
        self.ok("init", "--scope", "feature", "--base", "base", "--head", "HEAD", cwd=repo.root)
        self.ok("group", "G1", "--perspectives", "Correctness and regressions")
        self.ok("group", "G2", "--perspectives", "Security")
        self.ok("chunk", "C01", "--title", "core", "--files", "src/a.py", "src/b.py", "--risk", "high")
        self.ok("chunk", "C02", "--title", "rest", "--files", "lib/c.py", "old.py")
        self.ok("chunk", "C03", "--title", "links", "--integration")
        self.ok("cell", "C01", "G1", "G2")
        self.ok("cell", "C02", "G1")
        self.ok("omit", "C02", "--groups", "G2", "--reason", "no input handling")
        self.ok("cell", "C03", "G1")
        self.ok("start", "--owner", "R1", "C01/G1", "C01/G2", "C02/G1")
        self.ok("set", "C01/G1", "covered")
        self.ok("set", "C01/G2", "partial", "--unchecked", "src/b.py")
        self.ok("set", "C02/G1", "partial", "--unchecked", "old.py")
        self.ok("start", "--owner", "R2", "C03/G1")
        self.ok("set", "C03/G1", "covered")
        self.add_finding("F1", "--cell", "C01/G1", "--kind", "bug", "--severity", "high", "--title", "t",
                         "--files", "src/a.py:10")
        self.add_finding("F2", "--cell", "C01/G2", "--kind", "recommendation", "--title", "t", "--files", "src/b.py")
        self.add_finding("F3", "--cell", "C02/G1", "--kind", "question", "--title", "t")
        self.add_finding("F4", "--cell", "C01/G1", "--kind", "bug", "--severity", "low", "--title", "t",
                         "--files", "src/a.py")
        self.ok("verify", "F4", "refuted", "--verifier", "V1")
        self.add_finding("F5", "--cell", "C01/G1", "--kind", "bug", "--severity", "medium", "--title", "t",
                         "--files", "src/a.py")
        self.ok("verify", "F5", "confirmed", "--verifier", "V1")
        self.assertIn("ok:", self.ok("validate"))

        # The head moves: src/a.py changes again, old.py is reverted, new/d.py appears.
        repo.commit({"src/a.py": "a3\n", "old.py": "o1\n", "new/d.py": "d\n"}, "head 2")
        self.assertIn("changed: head HEAD moved", self.ok("status"))
        new_diff = repo.diff("base", "HEAD")
        fresh = self.write_diff(new_diff, "diff.new.patch")

        out = self.ok("refresh", str(fresh), "--dry-run")
        self.assertIn("changed 1, added 1, removed 1 files", out)
        self.assertEqual(self.state()["cells"]["C01/G1"]["status"], "covered")

        out = self.ok("refresh", str(fresh))
        for line in ("changed  src/a.py", "added    new/d.py", "removed  old.py", "stale F1", "stale F5",
                     "added files are in chunk C04 without cells"):
            self.assertIn(line, out)
        s = self.state()
        cells = s["cells"]
        self.assertEqual((cells["C01/G1"]["status"], cells["C01/G1"]["unchecked"]), ("partial", ["src/a.py"]))
        self.assertEqual((cells["C01/G2"]["status"], cells["C01/G2"]["unchecked"]),
                         ("partial", ["src/a.py", "src/b.py"]))
        self.assertEqual(cells["C02/G1"]["status"], "covered")  # its only unchecked file left the diff
        self.assertEqual(cells["C02/G2"]["status"], "omitted")
        # an integration cell is reopened by any changed or new file
        self.assertEqual((cells["C03/G1"]["status"], cells["C03/G1"]["unchecked"]),
                         ("partial", ["new/d.py", "src/a.py"]))

        self.assertEqual(s["chunks"]["C02"]["files"], ["lib/c.py"])
        self.assertEqual(s["chunks"]["C04"]["files"], ["new/d.py"])
        self.assertEqual((s["chunks"]["C04"]["kind"], s["chunks"]["C04"]["treatment"]), ("logic", "full"))
        self.assertFalse(any(k.startswith("C04/") for k in cells))

        findings = s["findings"]
        self.assertEqual({fid: f["status"] for fid, f in findings.items()},
                         {"F1": "stale", "F2": "unverified", "F3": "stale", "F4": "refuted", "F5": "stale"})
        f5 = findings["F5"]
        self.assertEqual(f5["verifications"], [])
        self.assertEqual(f5["refreshes"][0]["status"], "confirmed")
        self.assertEqual([v["verifier"] for v in f5["refreshes"][0]["verifications"]], ["V1"])
        self.assertEqual(findings["F3"]["refreshes"][0]["files"], ["old.py"])

        refresh = s["refreshes"][0]
        self.assertEqual((refresh["changed"], refresh["added"], refresh["removed"], refresh["new_chunk"]),
                         (["src/a.py"], ["new/d.py"], ["old.py"], "C04"))
        self.assertEqual(sorted(refresh["findings"]), ["F1", "F3", "F5"])
        self.assertEqual(s["revision"]["head_sha"], repo.sha("HEAD"))
        self.assertEqual((self.dir / "diff.patch").read_text(), new_diff)
        self.assertEqual((self.dir / "previous" / "diff-01.patch").read_text(), old_diff)
        self.assertEqual(self.log()[-1]["type"], "refresh")

        status = self.ok("status")
        self.assertNotIn("changed: head", status)
        self.assertIn("stale after refresh, verify again: F1, F3, F5", status)
        self.assertIn("F5  [medium/bug/stale, was confirmed]", self.ok("findings"))

        # the new chunk needs cells before the state is valid again
        result = self.rv("validate")
        self.assertExit(result, 1)
        self.assertIn("chunk C04: no cells", result.stdout)
        self.ok("cell", "C04", "G1")
        self.ok("omit", "C04", "--groups", "G2", "--reason", "no input handling")
        out = self.ok("validate")
        self.assertIn("finding F5: stale after a refresh", out)
        # partial follow-ups come first in the next wave; integration waits for them
        ready = self.first_tokens(self.ok("next"))
        self.assertEqual(ready[:2], ["C01/G1", "C01/G2"])
        self.assertNotIn("C03/G1", ready)
        self.assertIn("C04/G1", ready)

    def test_refresh_refuses_a_running_integration_cell(self):
        self.init_plain(modified("a.py", ["a"], ["b"]))
        self.ok("group", "G1", "--perspectives", "Security")
        self.ok("chunk", "C01", "--title", "a", "--files", "a.py")
        self.ok("chunk", "C02", "--title", "links", "--integration")
        self.ok("cell", "C01", "G1")
        self.ok("cell", "C02", "G1")
        self.ok("start", "--owner", "R1", "C02/G1")
        fresh = self.write_diff(modified("a.py", ["a"], ["b"]) + added("n.py", ["x"]), "diff.new.patch")
        self.refused("refresh", str(fresh), contains="C02/G1")



# --- patterns, several IDs, skipped files, batch, audit and impact ----------------------------------


class PatternTest(unittest.TestCase):
    FILES = ["a.py", "src/a.py", "src/x/b.py", "src/x/c.twig", "templates/p/a.html.twig", "templates/q.html.twig"]

    def match(self, pattern: str) -> list[str]:
        regex = review.glob_regex(pattern)
        return [f for f in self.FILES if regex.fullmatch(f)]

    def test_glob_semantics(self):
        cases = {
            "*.py": ["a.py"],  # * stays within a directory
            "src/*.py": ["src/a.py"],
            "src/**": ["src/a.py", "src/x/b.py", "src/x/c.twig"],
            "**/*.py": ["a.py", "src/a.py", "src/x/b.py"],  # **/ also matches no directory
            "templates/**/*.html.twig": ["templates/p/a.html.twig", "templates/q.html.twig"],
            "src/x/": ["src/x/b.py", "src/x/c.twig"],  # a trailing / is the whole directory
            "src/?/b.py": ["src/x/b.py"],
            "src/[!y]/*.twig": ["src/x/c.twig"],
            "./a.py": ["a.py"],
            "a.html.twig": [],  # dots are literal
        }
        for pattern, expected in cases.items():
            with self.subTest(pattern):
                self.assertEqual(self.match(pattern), expected)

    def test_expand(self):
        self.assertEqual(review.expand(["src/x/", "src/x/b.py", "sec. Foo::bar"], self.FILES, "u"),
                         ["src/x/b.py", "src/x/c.twig", "sec. Foo::bar"])
        with self.assertRaisesRegex(review.Refused, "tempaltes/\\*\\* matches no file of u"):
            review.expand(["tempaltes/**"], self.FILES, "u")
        with self.assertRaisesRegex(review.Refused, "x.py is not a file of u"):
            review.expand(["x.py"], self.FILES, "u", literal="require")

    def test_a_file_name_with_brackets_is_itself(self):
        files = ["app/[id]/page.tsx", "app/a/page.tsx"]
        self.assertEqual(review.expand(["app/[id]/page.tsx"], files, "u", literal="require"), ["app/[id]/page.tsx"])
        self.assertEqual(review.expand(["./app/[id]/page.tsx"], files, "u"), ["app/[id]/page.tsx"])
        # without an exact file of that name it stays a pattern, as in git
        self.assertEqual(review.expand(["app/[ai]/page.tsx"], files, "u"), ["app/a/page.tsx"])

    def test_whole_file_diff_parses_back(self):
        path = Path(tempfile.mkdtemp()) / "d.patch"
        self.addCleanup(lambda: path.unlink())
        path.write_text(review.whole_file_diff("a.py", b"one\ntwo\n") + review.whole_file_diff("b.py", b"x")
                        + review.whole_file_diff("e.txt", b"") + review.whole_file_diff("i.png", b"\x89P\0"))
        files = review.parse_diff(path)
        self.assertEqual({p: (f["status"], f["added"], f["binary"]) for p, f in files.items()},
                         {"a.py": ("added", 2, False), "b.py": ("added", 1, False), "e.txt": ("added", 0, False),
                          "i.png": ("added", 0, True)})


TWO_CHUNKS = (modified("src/a.php", ["a"], ["b"]) + added("templates/a.html.twig", ["x"])
              + added("templates/b.html.twig", ["y"]) + modified("lib/c.php", ["c"], ["d"]))


class SeveralIdsTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.init_plain(TWO_CHUNKS)
        self.ok("group", "G1", "--perspectives", "Correctness and regressions")
        self.ok("group", "G2", "--perspectives", "UX and accessibility")
        self.ok("chunk", "C01", "--title", "pay", "--files", "src/", "templates/**/*.html.twig")
        self.ok("chunk", "C02", "--title", "lib", "--files", "lib/*.php")
        self.ok("cell", "C01", "G1", "G2")
        self.ok("cell", "C02", "G1")

    def test_chunk_files_take_patterns(self):
        chunks = self.state()["chunks"]
        self.assertEqual(chunks["C01"]["files"], ["src/a.php", "templates/a.html.twig", "templates/b.html.twig"])
        self.assertEqual(chunks["C02"]["files"], ["lib/c.php"])
        self.refused("chunk", "C03", "--title", "t", "--files", "nowhere/**", contains="matches no file of diff.patch")
        self.refused("chunk", "C04", "--files", "lib/c.php", contains="needs --title")
        self.ok("chunk", "C02", "--risk", "high")  # an existing chunk keeps its title
        self.assertEqual(self.state()["chunks"]["C02"]["title"], "lib")

    def test_omit_several_chunks_and_groups(self):
        self.ok("cell", "C02", "G2")
        out = self.ok("omit", "C01", "C02", "--groups", "G2", "--reason", "no UI")
        self.assertIn("C01/G2: omitted", out)
        self.assertEqual([r["id"] for r in self.log() if r.get("status") == "omitted"], ["C01/G2", "C02/G2"])
        self.refused("omit", "C01", "--groups", "G9", "--reason", "r", contains="unknown group G9")

    def test_set_several_cells_with_skipped_files(self):
        self.ok("start", "--owner", "R1", "C01/G1", "C01/G2")
        out = self.ok("set", "C01/G1", "C01/G2", "covered", "--skipped", "templates/**=no logic of this group")
        self.assertIn("C01/G1: running -> covered, 2 files skipped", out)
        cells = self.state()["cells"]
        expected = {"templates/a.html.twig": "no logic of this group", "templates/b.html.twig": "no logic of this group"}
        self.assertEqual(cells["C01/G1"]["skipped"], expected)
        self.assertEqual(cells["C01/G2"]["skipped"], expected)
        records = [r for r in self.log() if r.get("status") == "covered"]
        self.assertEqual([(r["id"], r["skipped"]) for r in records], [("C01/G1", expected), ("C01/G2", expected)])
        self.assertIn("skipped C01/G1 (2 files, no logic of this group): templates/a.html.twig, templates/b.html.twig",
                      self.ok("coverage"))
        self.assertIn("ok:", self.ok("validate"))

    def test_skipped_needs_files_of_the_chunk_and_a_reason(self):
        self.ok("start", "--owner", "R1", "C01/G1", "C02/G1")
        before = (self.dir / "review.json").read_bytes(), (self.dir / "log.jsonl").read_bytes()
        self.refused("set", "C01/G1", "covered", "--skipped", "lib/c.php=r", contains="C01/G1: lib/c.php is not a file")
        self.refused("set", "C01/G1", "covered", "--skipped", "templates/**", contains="PATTERN=REASON")
        self.refused("set", "C01/G1", "pending", "--skipped", "templates/**=r", contains="covered or partial")
        # several cells are all or nothing: C02 has no templates, so C01 is not changed either
        self.refused("set", "C01/G1", "C02/G1", "covered", "--skipped", "templates/**=r",
                     contains="C02/G1: templates/** matches no file of chunk C02/G1")
        self.refused("set", "C01/G1", "partial", "--unchecked", "templates/a.html.twig",
                     "--skipped", "templates/**=r", contains="both skipped and unchecked")
        self.assertEqual(((self.dir / "review.json").read_bytes(), (self.dir / "log.jsonl").read_bytes()), before)

    def test_unchecked_patterns_and_sections(self):
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G1", "partial", "--unchecked", "templates/b*", "PaymentService::refund")
        self.assertEqual(self.state()["cells"]["C01/G1"]["unchecked"], ["templates/b.html.twig", "PaymentService::refund"])

    def test_follow_up_keeps_earlier_skips(self):
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G1", "partial", "--unchecked", "src/a.php", "--skipped", "templates/**=no logic")
        self.ok("start", "--owner", "R2", "C01/G1")
        self.ok("set", "C01/G1", "covered")
        self.assertEqual(len(self.state()["cells"]["C01/G1"]["skipped"]), 2)
        self.ok("set", "C01/G1", "pending")  # a lost run is judged again from scratch
        self.assertNotIn("skipped", self.state()["cells"]["C01/G1"])

    def test_verify_and_resolve_several_findings(self):
        self.ok("start", "--owner", "R1", "C01/G1")
        for fid in ("R1-01", "R1-02", "R1-03"):
            self.add_finding(fid, "--cell", "C01/G1", "--kind", "bug", "--severity", "low", "--title", "t")
        out = self.ok("verify", "R1-01", "R1-02", "confirmed", "--verifier", "V1")
        self.assertIn("R1-01: confirmed", out)
        self.assertIn("R1-02: confirmed", out)
        self.assertEqual([r["id"] for r in self.log() if r["type"] == "verification"], ["R1-01", "R1-02"])
        before = (self.dir / "review.json").read_bytes()
        self.refused("verify", "R1-03", "R9-99", "refuted", "--verifier", "V1", contains="unknown finding R9-99")
        self.assertEqual((self.dir / "review.json").read_bytes(), before)
        self.ok("resolve", "R1-02", "R1-03", "duplicate", "--reason", "same cause", "--duplicate-of", "R1-01")
        findings = self.state()["findings"]
        self.assertEqual([findings[f]["status"] for f in ("R1-02", "R1-03")], ["duplicate", "duplicate"])
        self.refused("resolve", "R1-01", "duplicate", "--reason", "r", "--duplicate-of", "R1-01", contains="itself")

    def test_finding_location_patterns_expand_with_a_warning(self):
        self.ok("start", "--owner", "R1", "C01/G1")
        out = self.add_finding("R1-01", "--cell", "C01/G1", "--kind", "question", "--title", "t", "--files", "templates/*")
        self.assertIn("warning: a finding's location names concrete files", out)
        self.assertEqual(self.state()["findings"]["R1-01"]["files"], ["templates/a.html.twig", "templates/b.html.twig"])

    def test_refresh_drops_the_skip_of_a_changed_file(self):
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G1", "covered", "--skipped", "templates/**=no logic")
        fresh = (modified("src/a.php", ["a"], ["b"]) + added("templates/a.html.twig", ["x", "{{ x|raw }}"])
                 + added("templates/b.html.twig", ["y"]) + modified("lib/c.php", ["c"], ["d"]))
        self.ok("refresh", self.write_diff(fresh, "diff.new.patch"))
        cell = self.state()["cells"]["C01/G1"]
        self.assertEqual(cell["status"], "partial")
        self.assertEqual(cell["unchecked"], ["templates/a.html.twig"])
        self.assertEqual(cell["skipped"], {"templates/b.html.twig": "no logic"})


class BatchTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.init_single(TWO_CHUNKS)
        self.ok("start", "--owner", "R1", "C01/G1", "C01/G2")
        for fid in ("R1-01", "R1-02"):
            self.write_finding(fid)

    def batch(self, text: str):
        return run_tool(REVIEW, self.dir, "batch", "-", cwd=self.tmp, env=self.env, input=text)

    def snapshot(self):
        return (self.dir / "review.json").read_bytes(), (self.dir / "log.jsonl").read_bytes()

    def test_batch_applies_both_line_forms(self):
        result = self.batch(
            "# reviewer R1\n\n"
            'finding R1-01 --cell C01/G1 --kind bug --severity high --title "Refund ignores the currency" --files src/a.php:3\n'
            '["finding", "R1-02", "--cell", "C01/G1", "--kind", "question", "--title", "Is a \\"partial\\" refund allowed?"]\n'
            "set C01/G1 C01/G2 covered --skipped 'templates/**=no logic of this group'\n"
            "verify R1-01 confirmed --verifier V1\n"
        )
        self.assertOk(result)
        self.assertIn("batch: 4 commands applied", result.stdout)
        s = self.state()
        self.assertEqual(s["findings"]["R1-02"]["title"], 'Is a "partial" refund allowed?')
        self.assertEqual(s["findings"]["R1-01"]["status"], "confirmed")
        self.assertEqual(s["cells"]["C01/G2"]["status"], "covered")
        added_records = self.log()[-5:]
        self.assertEqual([(r["type"], r.get("id")) for r in added_records],
                         [("finding", "R1-01"), ("finding", "R1-02"), ("cell", "C01/G1"), ("cell", "C01/G2"),
                          ("verification", "R1-01")])

    def test_a_refused_line_writes_nothing(self):
        before = self.snapshot()
        result = self.batch("finding R1-01 --cell C01/G1 --kind question --title t\n"
                            "verify R1-01 confirmed --verifier R1\n")
        self.assertExit(result, 1)
        self.assertIn("line 2: R1 reported R1-01", result.stderr)
        self.assertIn("nothing was written", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_wrong_usage_and_disallowed_commands(self):
        before = self.snapshot()
        for text, message in (("set C01/G1 done\n", "line 1: argument status: invalid choice"),
                              ("finding R1-01 --cell C01/G1 --kind question --title t\nstatus\n",
                               "line 2: status is not allowed in a batch"),
                              ("refresh x.patch\n", "line 1: refresh is not allowed"),
                              ("batch -\n", "line 1: batch is not allowed"),
                              ('["set", 1]\n', "line 1: a JSON line must be an array of strings"),
                              ("set 'C01/G1 covered\n", "line 1: No closing quotation")):
            with self.subTest(text):
                result = self.batch(text)
                self.assertExit(result, 1)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.snapshot(), before)

    def test_batch_from_a_file(self):
        path = self.tmp / "cmds.txt"
        path.write_text("set C01/G1 covered\nset C01/G2 partial --unchecked src/a.php\n")
        self.assertIn("batch: 2 commands applied", self.ok("batch", path))
        self.assertEqual(self.state()["cells"]["C01/G2"]["unchecked"], ["src/a.php"])


class AuditTest(ReviewTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo = GitRepo(self.tmp / "repo", self.env)
        self.repo.commit({"src/Payment/Pay.php": "<?php\npay();\n", "src/Payment/Refund.php": "<?php\nrefund();\n",
                          "src/Other.php": "<?php\n", "templates/payment/form.html.twig": "{{ form }}\n",
                          ".gitignore": "var/\n"}, "base")

    def test_audit_of_the_head_reviews_whole_files(self):
        self.repo.write({"src/Payment/Pay.php": "<?php\nchanged();\n"})  # not committed: not in a head audit
        out = self.ok("init", "--scope", "payments", "--audit", "src/Payment/**", "templates/payment/",
                      "--single", "--groups", "G1=Security and privacy", cwd=self.repo.root)
        self.assertIn("audit: 3 whole files", out)
        diff = (self.dir / "diff.patch").read_text()
        self.assertIn("+pay();", diff)
        self.assertNotIn("changed();", diff)
        s = self.state()
        self.assertEqual(s["chunks"]["C01"]["files"], ["src/Payment/Pay.php", "src/Payment/Refund.php",
                                                       "templates/payment/form.html.twig"])
        self.assertEqual(s["chunks"]["C01"]["lines"], 5)
        self.assertEqual(s["revision"]["audit"], ["src/Payment/**", "templates/payment/"])
        self.assertIsNone(s["revision"]["base"])
        self.assertIn("audit of src/Payment/** templates/payment/ at HEAD", self.ok("status", cwd=self.repo.root))
        self.assertIn("ok:", self.ok("validate"))

    def test_audit_of_the_working_tree_and_its_refresh(self):
        self.repo.write({"src/Payment/New.php": "<?php\nnew_();\n", "src/Payment/var/x.php": "ignored\n"})
        self.repo.write({".gitignore": "var/\n"})
        self.ok("init", "--scope", "payments", "--audit", "src/Payment/", "--working-tree", "--single",
                "--groups", "G1=Correctness and regressions", cwd=self.repo.root)
        self.assertEqual(self.state()["chunks"]["C01"]["files"],
                         ["src/Payment/New.php", "src/Payment/Pay.php", "src/Payment/Refund.php"])
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("set", "C01/G1", "covered")
        self.repo.write({"src/Payment/Refund.php": "<?php\nrefund(2);\n", "src/Payment/Pay.php": None,
                         "src/Payment/Fee.php": "<?php\n"})
        self.assertIn("whole files written", self.ok("audit-diff", self.dir / "diff.new.patch", cwd=self.repo.root))
        out = self.ok("refresh", self.dir / "diff.new.patch", cwd=self.repo.root)
        self.assertIn("changed 1, added 1, removed 1 files", out)
        cell = self.state()["cells"]["C01/G1"]
        self.assertEqual(cell["status"], "partial")
        self.assertEqual(cell["unchecked"], ["src/Payment/Fee.php", "src/Payment/Refund.php"])

    def test_audit_usage(self):
        self.assertExit(self.rv("init", "--scope", "s", cwd=self.repo.root), 2)
        self.assertExit(self.rv("init", "--scope", "s", "--base", "main", "--audit", "src/", cwd=self.repo.root), 2)
        self.refused_in_repo("init", "--scope", "s", "--audit", "src/Paymnet/**", contains="matches no file")
        self.refused_in_repo("init", "--scope", "s", "--audit", "src/Nope.php", contains="is not a file")

    def test_audit_diff_needs_an_audit(self):
        self.write_diff(modified("x.py", ["a"], ["b"]))
        self.ok("init", "--scope", "s", "--base", "main", "--head", "HEAD", cwd=self.repo.root)
        self.refused_in_repo("audit-diff", self.dir / "x.patch", contains="not an audit")

    def refused_in_repo(self, *args, contains: str):
        result = self.rv(*args, cwd=self.repo.root)
        self.assertExit(result, 1)
        self.assertIn(contains, result.stderr)


class ImpactTest(ReviewTestCase):
    """The core of a cell is its chunk; the impact outside it is the reviewer's judgment."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = GitRepo(self.tmp / "repo", self.env)
        self.repo.commit({"src/Pay.php": "a\n", "src/Use1.php": "u\n", "src/Use2.php": "u\n", "lib/Use3.php": "u\n"},
                         "base")
        self.repo.git("tag", "base")
        self.repo.commit({"src/Pay.php": "b\n"}, "head")
        self.write_diff(self.repo.diff("base", "HEAD"))
        self.ok("init", "--scope", "s", "--base", "base", "--single", "--groups", "G1=Correctness and regressions",
                cwd=self.repo.root)

    def run_ok(self, *args) -> str:
        return self.ok(*args, cwd=self.repo.root)

    def run_refused(self, *args, contains: str) -> None:
        result = self.rv(*args, cwd=self.repo.root)
        self.assertExit(result, 1)
        self.assertIn(contains, result.stderr)

    def test_the_impact_is_recorded_without_changing_the_coverage(self):
        self.run_ok("start", "--owner", "R1", "C01/G1")
        out = self.run_ok("set", "C01/G1", "covered", "--impact", "src/Use*.php", "--impact-unchecked", "lib/")
        self.assertIn("covered, 2 impact files checked, 1 impact files not checked", out)
        cell = self.state()["cells"]["C01/G1"]
        self.assertEqual(cell["status"], "covered")
        self.assertEqual(cell["impact"], ["src/Use1.php", "src/Use2.php"])
        self.assertEqual(cell["impact_unchecked"], ["lib/Use3.php"])
        self.assertEqual(self.log()[-1]["impact"], ["src/Use1.php", "src/Use2.php"])
        out = self.run_ok("coverage")
        self.assertIn("impact not checked C01/G1 (a limitation, not a gap): lib/Use3.php", out)
        self.assertIn("coverage complete", out)

    def test_unchecked_is_the_core_only_and_the_impact_adds_up(self):
        self.run_ok("start", "--owner", "R1", "C01/G1")
        self.run_refused("set", "C01/G1", "partial", "--unchecked", "lib/*.php", contains="matches no file of chunk")
        self.run_ok("set", "C01/G1", "partial", "--unchecked", "src/Pay.php", "--impact-unchecked", "src/Use1.php")
        self.run_ok("start", "--owner", "R2", "C01/G1")
        self.run_ok("set", "C01/G1", "covered", "--impact", "src/Use1.php")
        cell = self.state()["cells"]["C01/G1"]
        self.assertEqual(cell["impact"], ["src/Use1.php"])
        self.assertNotIn("impact_unchecked", cell)  # checked later, so no longer open
        self.run_refused("set", "C01/G1", "pending", "--impact", "src/Use1.php", contains="covered or partial")
        self.run_refused("set", "C01/G1", "covered", "--impact", "src/Pay.php", contains="its own files are not its impact")
        self.run_ok("set", "C01/G1", "pending")
        self.assertNotIn("impact", self.state()["cells"]["C01/G1"])

    def test_the_repository_is_listed_once_and_only_for_the_impact(self):
        from tests import helpers

        self.run_ok("status")
        tool = helpers._tools[REVIEW]  # the module run_tool runs in this process
        calls = []
        original = tool.repo_files

        def counting(*args):
            calls.append(args)
            return original(*args)

        tool.repo_files = counting
        self.addCleanup(setattr, tool, "repo_files", original)
        self.run_ok("group", "G2", "--perspectives", "Security")
        self.run_ok("cell", "C01", "G2")
        self.run_ok("start", "--owner", "R1", "C01/G1", "C01/G2")
        self.run_ok("set", "C01/G1", "partial", "--unchecked", "src/Pay.php")
        self.assertEqual(calls, [])
        path = self.tmp / "cmds.txt"
        path.write_text("set C01/G1 partial --unchecked src/Pay.php --impact src/Use1.php\n"
                        "set C01/G2 covered --impact src/Use2.php --impact-unchecked lib/Use3.php\n")
        self.run_ok("batch", path)
        self.assertEqual(len(calls), 1)

    def test_overview(self):
        out = self.run_ok("overview")
        self.assertIn("C01  [medium/full]     1 files  whole diff  (src)", out)



class ActorTest(ReviewTestCase):
    """Reviewers and verifiers record their own results with --as, limited to their cells and findings."""

    def setUp(self) -> None:
        super().setUp()
        self.init_single(TWO_CHUNKS)
        self.ok("start", "--owner", "R1", "C01/G1")
        self.ok("start", "--owner", "R2", "C01/G2")

    def as_(self, actor: str, *args, input: str | None = None):
        return run_tool(REVIEW, self.dir, "--as", actor, *args, cwd=self.tmp, env=self.env, input=input)

    def snapshot(self):
        return (self.dir / "review.json").read_bytes(), (self.dir / "log.jsonl").read_bytes()

    def test_a_reviewer_records_its_findings_and_coverage(self):
        body = "# R1-01 Refund ignores the currency\n\n- **Scenario:** a refund in EUR\n"
        lines = [json.dumps(["finding", "R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "high",
                             "--title", "Refund ignores the currency", "--files", "src/a.php", "--body", body]),
                 "set C01/G1 covered --skipped 'templates/**=no logic'"]
        result = self.as_("R1", "batch", "-", input="\n".join(lines) + "\n")
        self.assertOk(result)
        self.assertEqual((self.dir / "findings" / "R1-01.md").read_text(), body)
        s = self.state()
        self.assertEqual(s["findings"]["R1-01"]["reviewer"], "R1")
        self.assertEqual(s["cells"]["C01/G1"]["status"], "covered")
        self.assertEqual([r.get("by") for r in self.log()[-2:]], ["R1", "R1"])

    def test_a_reviewer_is_limited_to_its_own_cells(self):
        before = self.snapshot()
        for args, message in (
                (["set", "C01/G2", "covered"], "C01/G2 is not running for R1"),
                (["set", "C01/G1", "pending"], "pending is the orchestrator's decision"),
                (["finding", "R1-01", "--cell", "C01/G2", "--kind", "question", "--title", "t", "--body", "x"],
                 "C01/G2 is not running for R1"),
                (["finding", "R1-01", "--cell", "C01/G1", "--kind", "question", "--title", "t", "--body", "x",
                  "--reviewer", "R2"], "only its own findings"),
                (["start", "--owner", "R1", "C01/G2"], "start is the orchestrator's"),
                (["resolve", "X", "refuted", "--reason", "r"], "resolve is the orchestrator's"),
                (["chunk", "C01", "--risk", "low"], "chunk is the orchestrator's")):
            with self.subTest(args[0]):
                result = self.as_("R1", *args)
                self.assertExit(result, 1)
                self.assertIn(message, result.stderr)
        result = self.as_("R1", "batch", "-", input="--as R2 set C01/G2 covered\n")
        self.assertExit(result, 1)
        self.assertIn("--as is given once for the whole batch", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.dir / "findings" / "R1-01.md").exists())

    def test_a_refused_batch_writes_no_finding_file(self):
        result = self.as_("R1", "batch", "-", input=(
            "finding R1-01 --cell C01/G1 --kind question --title t --body 'Is it allowed?'\n"
            "set C01/G2 covered\n"))
        self.assertExit(result, 1)
        self.assertFalse((self.dir / "findings" / "R1-01.md").exists())
        self.assertNotIn("R1-01", self.state()["findings"])

    def test_body_from_stdin_and_stable_files(self):
        self.assertOk(self.as_("R1", "finding", "R1-01", "--cell", "C01/G1", "--kind", "question", "--title", "t",
                               "--body", "-", input="# R1-01\nfrom stdin"))
        self.assertEqual((self.dir / "findings" / "R1-01.md").read_text(), "# R1-01\nfrom stdin\n")
        self.write_finding("R1-02")
        result = self.as_("R1", "finding", "R1-02", "--cell", "C01/G1", "--kind", "question", "--title", "t",
                          "--body", "again")
        self.assertExit(result, 1)
        self.assertIn("findings/R1-02.md already exists", result.stderr)
        result = self.as_("R1", "finding", "R1-03", "--cell", "C01/G1", "--kind", "question", "--title", "t",
                          "--body", "  ")
        self.assertIn("--body is empty", result.stderr)

    def test_a_verifier_records_its_verdicts_with_the_evidence(self):
        self.assertOk(self.as_("R1", "finding", "R1-01", "--cell", "C01/G1", "--kind", "bug", "--severity", "low",
                               "--title", "t", "--body", "# R1-01\n"))
        self.assertOk(self.as_("V1", "verify", "R1-01", "confirmed", "--note", "Traced Refund::run, line 12."))
        self.assertEqual((self.dir / "findings" / "R1-01.md").read_text(),
                         "# R1-01\n\n## Verification by V1: confirmed\n\nTraced Refund::run, line 12.\n")
        f = self.state()["findings"]["R1-01"]
        self.assertEqual((f["status"], f["verifications"][0]["verifier"]), ("confirmed", "V1"))
        self.assertEqual(self.log()[-1]["by"], "V1")
        result = self.as_("V1", "verify", "R1-01", "confirmed", "--verifier", "V2")
        self.assertIn("V1 records only its own verifications", result.stderr)
        result = self.as_("R1", "verify", "R1-01", "refuted")
        self.assertIn("never the sole verifier of its own finding", result.stderr)
        self.refused("verify", "R1-01", "confirmed", contains="verify needs --verifier")

    def test_a_finding_id_cannot_leave_the_findings_folder(self):
        for fid in ("../../escape", "/tmp/x", "R1-01/../x", ".hidden", "R1 01"):
            with self.subTest(fid):
                result = self.as_("R1", "finding", fid, "--cell", "C01/G1", "--kind", "question", "--title", "t",
                                  "--body", "x")
                self.assertExit(result, 1)
                self.assertIn("use letters, digits", result.stderr)
        self.assertFalse((self.tmp / "escape.md").exists())

    def test_a_finding_needs_a_running_cell(self):
        self.assertOk(self.as_("R1", "set", "C01/G1", "covered"))
        result = self.as_("R1", "finding", "R1-01", "--cell", "C01/G1", "--kind", "question", "--title", "t",
                          "--body", "x")
        self.assertExit(result, 1)
        self.assertIn("C01/G1 is not running for R1", result.stderr)

    def test_body_from_stdin_inside_a_batch_is_refused_clearly(self):
        result = self.as_("R1", "batch", "-", input="finding R1-01 --cell C01/G1 --kind question --title t --body -\n")
        self.assertExit(result, 1)
        self.assertIn("the batch uses; put the text into the line", result.stderr)

    def test_parallel_subagents_do_not_lose_records(self):
        cells = [f"C01/G{n}" for n in range(3, 9)]
        for cell in cells:
            self.ok("group", cell.split("/")[1], "--perspectives", "Correctness and regressions")
        self.ok("cell", "C01", *[c.split("/")[1] for c in cells])
        for n, cell in enumerate(cells, 3):
            self.ok("start", "--owner", f"R{n}", cell)
        procs = [subprocess.Popen([sys.executable, str(REVIEW), str(self.dir), "--as", f"R{n}", "batch", "-"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  cwd=self.tmp, env={**os.environ, **self.env})
                 for n in range(3, 9)]
        for n, proc in enumerate(procs, 3):
            proc.stdin.write(f"finding R{n}-01 --cell C01/G{n} --kind question --title t --body x\n"
                             f"set C01/G{n} covered\n")
            proc.stdin.close()
        for proc in procs:
            self.assertEqual(proc.wait(timeout=60), 0, proc.stderr.read())
        s = self.state()
        self.assertEqual(sorted(s["findings"]), [f"R{n}-01" for n in range(3, 9)])
        self.assertTrue(all(s["cells"][c]["status"] == "covered" for c in cells))


if __name__ == "__main__":
    unittest.main()
