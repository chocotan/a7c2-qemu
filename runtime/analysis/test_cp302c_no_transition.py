"""Strict and diagnostic transport host fixtures; no VM or real-AP claim."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent / "device-models"


class Cp302cNoTransition(unittest.TestCase):
    def test_finite_history_reply_ownership_and_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "cp302c-no-transition"
            built = subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g",
                "-DNATIVE_CP302C_TEST", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-no-pie", "-pthread",
                str(HERE / "cp302c-no-transition.c"),
                str(HERE / "test-cp302c-no-transition.c"), "-o", str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                               UBSAN_OPTIONS="halt_on_error=1")
            strict_cases = (
                "normal", "opaque", "early", "default-off", "guard", "other-endpoints",
                "malformed", "preinit", "unknown-type5", "unknown-mode",
                "prefix-before", "prefix-after", "prefix-short", "prefix-long", "prefix-source", "prefix-type",
                "prior-cookie", "prior-source", "prior-owner", "prior-queue", "prior-free",
                "prior-tid", "prior-short", "allocfail", "short-allocation", "alias",
                "bad-reply-source", "sendfail", "cleanupfail", "requestfail", "replyfail",
                "foreign", "wrong-owner", "reentrant", "fast-free-reuse", "async-inflight", "fork-lock",
            )
            diagnostic_cases = tuple("diag-" + case for case in (
                "normal", "opaque", "early", "default-off", "guard", "other-endpoints",
                "malformed", "preinit", "no-3007", "early-free",
                "input-short", "input-source", "input-type", "input-repeat",
                "prior-cookie", "prior-source", "prior-owner", "prior-queue", "prior-free",
                "prior-tid", "prior-freeing-tid", "prior-short", "prior-type", "prior-command", "prior-result",
                "allocfail", "short-allocation", "alias", "bad-reply-source", "during-allocation", "before-publication",
                "sendfail", "cleanupfail", "requestfail", "replyfail", "foreign", "wrong-owner",
                "reentrant", "fast-free-reuse", "async-inflight", "fork-lock",
            ))
            for case in strict_cases + diagnostic_cases:
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("real AP/all13/CP/capture unverified", result.stdout)


if __name__ == "__main__":
    unittest.main()
