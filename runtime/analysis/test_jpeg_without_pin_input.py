"""Host-only partial metadata checks; no VM, pixel producer or JPEG encoder."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODELS = HERE / "device-models"
VERIFIER = HERE.parents[1] / "report/jpeg-without-pin/verify.py"


class JpegWithoutPinInput(unittest.TestCase):
    def test_partial_metadata_contract_under_sanitizers(self):
        with tempfile.TemporaryDirectory(prefix="jpeg-without-pin-") as directory:
            binary = Path(directory) / "metadata-test"
            compiled = subprocess.run([
                "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic",
                "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-fno-omit-frame-pointer", "-no-pie",
                str(MODELS / "jpeg-without-pin-input.c"),
                str(MODELS / "test-jpeg-without-pin-input.c"), "-o", str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run(
                [str(binary)], cwd=directory, capture_output=True, text=True, timeout=20,
                env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                         UBSAN_OPTIONS="halt_on_error=1"),
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("metadata contract cases; unknown fields remain unsupported", run.stdout)
            print(run.stdout.strip())

    def test_original_source_anchors_using_existing_verifier(self):
        run = subprocess.run([sys.executable, str(VERIFIER), "--self-test"],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("WITHOUT_PIN_METADATA_VERIFIED true", run.stdout)
        self.assertIn("PIXEL_LAYOUT_VERIFIED false", run.stdout)
        self.assertIn("ORIGINAL_JPEG_BITSTREAM_DECODED false", run.stdout)
        self.assertIn("CAPTURE_VERIFIED false", run.stdout)
        print(run.stdout.strip())


if __name__ == "__main__":
    unittest.main()
