"""Bounded mode0/D018 C fixtures only; no VM, original AP/CP, or real all13 claim."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent / "device-models"


class CpNotificationControl(unittest.TestCase):
    def test_mode0_consumer_wire_ownership_and_refusals(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "cp-notification-control"
            built = subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g",
                "-DNATIVE_CP_NOTIFICATION_TEST", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-no-pie", "-pthread",
                str(HERE / "cp-notification-control.c"),
                str(HERE / "test-cp-notification-control.c"), "-o", str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                               UBSAN_OPTIONS="halt_on_error=1")
            cases = (
                "normal", "opaque", "default-off", "preinit", "unrelated", "wrong-type",
                "other-destination", "short-header", "mode1", "mode2", "unknown-mode",
                "badlen", "long", "wrong-source", "missing-guard", "guard-incomplete",
                "diag-missing", "all13-missing", "reserve-refused", "allocfail",
                "short-allocation", "alias", "overlap", "bad-reply-source", "bad-reply-copy",
                "allocation-error-pointer", "lost-guard", "mutated-request", "cleanupfail",
                "sendfail", "send-cleanupfail", "requestfail", "replyfail", "inline-free",
                "fast-free-reuse", "reentrant", "inspect-reentrant", "reentrant-free",
                "async-inflight", "before-consumer-fault", "fork-lock", "wrong-waiter",
                "wrong-owner", "foreign", "altered-wire", "altered-source", "altered-size",
            )
            for case in cases:
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn("real AP/all13/CP/capture unverified", result.stdout)


if __name__ == "__main__":
    unittest.main()
