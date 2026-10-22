"""Shared helpers for the tests of the tools in base/shared and scripts.

The tools are command-line programs used by agents, so the tests run their command lines against a
temporary directory and check their exit codes, output and the files they write.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "base" / "shared"
SCRIPTS = ROOT / "scripts"


def run_tool(script: Path, *args: str, cwd: Path | None = None, env: dict | None = None,
             input: str | None = None, timeout: float = 60, isolated: bool = False) -> subprocess.CompletedProcess:
    """Run a tool's command line and capture its exit code and output as text.

    By default the tool's main() runs in this process, as starting an interpreter per call made the suite
    several times slower; isolated=True runs a real subprocess, for tools that read the environment on
    import or tests that need a separate process.
    """
    if isolated:
        return subprocess.run(
            [sys.executable, str(script), *map(str, args)],
            cwd=cwd, env={**os.environ, **(env or {})}, input=input, capture_output=True, text=True,
            timeout=timeout,
        )
    module = _tools.get(script) or _tools.setdefault(script, load_module(script, f"tool_{Path(script).stem}"))
    stdout, stderr = io.StringIO(), io.StringIO()
    argv = [str(script), *map(str, args)]
    with mock.patch.dict(os.environ, env or {}), mock.patch.object(sys, "argv", argv), \
            mock.patch.object(sys, "stdin", io.StringIO(input or "")), _chdir(cwd), \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            module.main()
            code = 0
        except SystemExit as e:
            if e.code is None or isinstance(e.code, int):
                code = e.code or 0
            else:
                print(e.code, file=sys.stderr)
                code = 1
        except Exception:
            traceback.print_exc()
            code = 1
    return subprocess.CompletedProcess(argv, code, stdout.getvalue(), stderr.getvalue())


_tools: dict = {}


@contextlib.contextmanager
def _chdir(path: Path | None):
    previous = os.getcwd()
    if path is not None:
        os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def read_json(path: Path):
    return json.loads(Path(path).read_text())


def read_jsonl(path: Path) -> list:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path: Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n")


class ToolTestCase(unittest.TestCase):
    """A test case with a fresh temporary directory in self.tmp and assertions on tool results."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def assertExit(self, result: subprocess.CompletedProcess, code: int) -> None:
        self.assertEqual(
            result.returncode, code,
            f"exit {result.returncode}, expected {code}\n--- stdout\n{result.stdout}--- stderr\n{result.stderr}",
        )

    def assertOk(self, result: subprocess.CompletedProcess) -> None:
        self.assertExit(result, 0)


def load_module(path: Path, name: str):
    """Import a tool as a module to unit-test its helpers, without leaving bytecode next to it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    dont_write, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write
    return module
