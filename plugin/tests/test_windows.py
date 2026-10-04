"""ADR-0019 decision 3: Windows in the same tree.

These run on every OS. Windows-only branches are exercised by flipping the
module's platform switch and stubbing the process calls, so a POSIX CI run
still pins them; the windows-latest CI job runs the whole suite natively.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gatekit import hookio, jobs, paths  # noqa: E402

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[1]

#: ADR-0030: each name is probed silently before it runs the gate, so a Store
#: placeholder that prints "Python" and exits non-zero never reaches stdout.
PROBE = '-c "import sys;sys.exit(sys.version_info<(3,9))" >/dev/null 2>&1'
CHAIN_RE = re.compile(
    r'^\(python3 ' + re.escape(PROBE) + r' && python3 "(?P<s>\$\{CLAUDE_PLUGIN_ROOT\}/gatekit/gates/\w+\.py)"\)'
    r' \|\| \(python ' + re.escape(PROBE) + r' && python "(?P=s)"\)'
    r' \|\| py -3 "(?P=s)"$'
)


def chain(script: str, suffix: str = "") -> str:
    """The hook command for *script*, as hooks.json spells it."""
    run = '"%s"%s' % (script, suffix)
    return ("(python3 %s && python3 %s) || (python %s && python %s) || py -3 %s"
            % (PROBE, run, PROBE, run, run))


def _stub(bindir: pathlib.Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class TestHookInterpreterChain(unittest.TestCase):
    """3a (ADR-0030): a hook must start where only `python` or `py` exists, and a
    placeholder on PATH must not leak into the hook's stdout."""

    def test_every_plugin_hook_probes_then_runs_three_interpreters(self) -> None:
        data = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = [h["command"] for group in data["hooks"].values() for e in group for h in e["hooks"]]
        self.assertTrue(commands)
        for command in commands:
            self.assertRegex(command, CHAIN_RE)

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "needs a POSIX sh")
    def test_chain_falls_through_to_python_when_python3_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = pathlib.Path(tmp)
            _stub(bindir, "python", 'exec "%s" "$@"\n' % sys.executable)
            script = bindir / "probe.py"
            script.write_text("print('ran')\n", encoding="utf-8")
            proc = subprocess.run(
                [shutil.which("sh"), "-c", chain(str(script))],
                env={"PATH": str(bindir)},  # no python3, no py
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "ran\n")

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "needs a POSIX sh")
    def test_store_placeholder_never_reaches_stdout(self) -> None:
        """Windows ships `python3`/`python` placeholders that print `Python`
        with no newline and exit 49 (owner's PC, 2026-10-04). The old chain
        produced `PythonPython{json}`; the probed chain must not."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = pathlib.Path(tmp)
            _stub(bindir, "python3", "printf Python\nexit 49\n")
            _stub(bindir, "python", "printf Python\nexit 49\n")
            _stub(bindir, "py", 'shift\nexec "%s" "$@"\n' % sys.executable)  # py -3 <script>
            script = bindir / "gate.py"
            script.write_text("import json; print(json.dumps({'decision': 'deny'}))\n", encoding="utf-8")
            old = 'python3 "{s}" || python "{s}" || py -3 "{s}"'.format(s=script)
            polluted = subprocess.run([shutil.which("sh"), "-c", old], env={"PATH": str(bindir)},
                                      capture_output=True, text=True, timeout=30)
            clean = subprocess.run([shutil.which("sh"), "-c", chain(str(script))], env={"PATH": str(bindir)},
                                   capture_output=True, text=True, timeout=30)
        # the bug, pinned so the test is known to exercise it
        self.assertTrue(polluted.stdout.startswith("PythonPython"), polluted.stdout)
        # the fix
        self.assertEqual(clean.returncode, 0, clean.stderr)
        self.assertEqual(json.loads(clean.stdout), {"decision": "deny"})

    @unittest.skipIf(os.name == "nt" or not shutil.which("sh"), "needs a POSIX sh")
    def test_a_python2_on_path_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindir = pathlib.Path(tmp)
            # a "python3" whose version check fails, standing in for Python 2 or a broken install
            _stub(bindir, "python3", 'case "$*" in *version_info*) exit 1;; esac\necho WRONG\n')
            _stub(bindir, "python", 'exec "%s" "$@"\n' % sys.executable)
            script = bindir / "gate.py"
            script.write_text("print('ran')\n", encoding="utf-8")
            proc = subprocess.run([shutil.which("sh"), "-c", chain(str(script))], env={"PATH": str(bindir)},
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.stdout, "ran\n", proc.stderr)

    def test_codex_layer_uses_the_same_probed_chain(self) -> None:
        from gatekit import hosts
        data = hosts.codex_hooks(PLUGIN_DIR)
        commands = [h["command"] for group in data["hooks"].values() for e in group for h in e["hooks"]]
        self.assertTrue(commands)
        for command in commands:
            self.assertIn("--host codex", command)
            self.assertIn("(python3 %s && python3 " % PROBE, command)
            self.assertNotRegex(command, r'^python3 "')


class TestHookStdioIsUtf8(unittest.TestCase):
    """3b: a Korean prompt survives a cp949 console."""

    def test_utf8_round_trip_under_a_legacy_locale_encoding(self) -> None:
        program = (
            "import sys; sys.path.insert(0, %r)\n"
            "from gatekit import hookio\n"
            "hookio.run(lambda e: {'echo': e.get('prompt')}, exit_process=False)\n"
        ) % str(PLUGIN_DIR)
        env = dict(os.environ, PYTHONIOENCODING="cp949")
        env.pop("PYTHONUTF8", None)
        event = json.dumps({"prompt": "뭘 만들지 모르겠어 — 한글"}, ensure_ascii=False)
        proc = subprocess.run(
            [sys.executable, "-c", program],
            input=event.encode("utf-8"), capture_output=True, env=env, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout.decode("utf-8"))["echo"], "뭘 만들지 모르겠어 — 한글")


class TestArgvZeroIsResolved(unittest.TestCase):
    """3c: `npm` must find `npm.cmd` without a shell."""

    def test_bare_program_name_is_resolved_through_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            name = "gatekit-fake-tool"
            exe = pathlib.Path(tmp) / (name + (".cmd" if os.name == "nt" else ""))
            exe.write_text("@echo off\n" if os.name == "nt" else "#!/bin/sh\n", encoding="utf-8")
            exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
            with mock.patch.dict(os.environ, {"PATH": tmp + os.pathsep + os.environ.get("PATH", "")}):
                out = paths.expand_argv([name, "run", "e2e"])
        self.assertEqual(pathlib.Path(out[0]).resolve(), exe.resolve())
        self.assertEqual(out[1:], ["run", "e2e"])

    def test_unresolvable_name_passes_through(self) -> None:
        self.assertEqual(paths.expand_argv(["no-such-tool-xyz", "a"]), ["no-such-tool-xyz", "a"])

    def test_explicit_path_is_left_alone(self) -> None:
        self.assertEqual(paths.expand_argv(["./node_modules/.bin/x"]), ["./node_modules/.bin/x"])


class TestWindowsProcessControl(unittest.TestCase):
    """3d: on Windows, os.kill(pid, 0) terminates the process; never call it."""

    def setUp(self) -> None:
        self.calls = []
        patcher_win = mock.patch.object(jobs, "_IS_WINDOWS", True)
        patcher_kill = mock.patch.object(jobs.os, "kill", side_effect=AssertionError("os.kill on Windows"))
        patcher_run = mock.patch.object(jobs.subprocess, "run", side_effect=self.fake_run)
        for p in (patcher_win, patcher_kill, patcher_run):
            p.start()
            self.addCleanup(p.stop)

    def fake_run(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = b""
        if argv[0] == "tasklist":
            out = b'"python.exe","4242","Console","1","10,000 K"\r\n'
        elif argv[0] == "powershell":
            out = b"30.5\r\n"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr=b"")

    def test_liveness_uses_tasklist(self) -> None:
        self.assertTrue(jobs._pid_alive(4242))
        self.assertEqual(self.calls[0][0], "tasklist")

    def test_age_uses_powershell(self) -> None:
        self.assertAlmostEqual(jobs._process_age_s(4242), 30.5)
        self.assertEqual(self.calls[0][0], "powershell")

    def test_terminate_uses_taskkill_tree(self) -> None:
        self.assertTrue(jobs._terminate_pid(4242, grace_s=0))
        killed = [c for c in self.calls if c[0] == "taskkill"]
        self.assertTrue(killed)
        self.assertIn("/T", killed[0])
        self.assertIn("4242", killed[0])


class TestMsysPaths(unittest.TestCase):
    """3e: Git Bash reports /c/work/app for C:\\work\\app."""

    def test_msys_drive_path_becomes_a_windows_path(self) -> None:
        self.assertEqual(paths.from_msys("/c/work/app/x.ts", windows=True), "C:/work/app/x.ts")

    def test_other_paths_unchanged(self) -> None:
        self.assertEqual(paths.from_msys("/c/work/app", windows=False), "/c/work/app")
        self.assertEqual(paths.from_msys("src/x.ts", windows=True), "src/x.ts")
        self.assertEqual(paths.from_msys("/usr/bin/x", windows=True), "/usr/bin/x")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
