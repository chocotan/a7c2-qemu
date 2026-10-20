"""Host contract test for the SD hot-plug transition core (sd-state.c).

Provenance: the core and its C test were selected from an independent A/B pair.
This wrapper runs variant A with one mechanical difference: the two
`#include "sd_state.h"` lines were renamed to `sd-state.h` so the production
filenames follow the existing `rm-file-device.*` dash convention. Nothing else
in the selected variant changed.

    sd-state.c       sha256 1cf17fa41b8f05f26210a66646ad75a4080976ccdac9c3c0d2205d392f4b4720
    sd-state.h       sha256 fb1ada9230e4b4348fe7cc2afa7c59b11cde75bfe93f0480f411591d56fb9161
    test-sd-state.c  sha256 2336267d5648c6784dca881a0ee1851337318543ba6d094981aa947791ca3808

Variant B (scratch/sd-state-core-b, sha256 5174a056...) was rejected as the base:
it keeps the 7-byte notification payload outside the core and its rollback guard
is expressed as a single negation, while A builds the payload the device model
actually sends and separates "definitely not sent" from "delivery uncertain".

Contract asserted by the C test (see also report/sd-hotplug-progress.md):
generation-tagged observations, two-phase finalisation (filesystem ack plus
notification free), RemoveCnt modulo 16, rollback only when delivery is provably
not sent, and FAILED_UNCERTAIN without rollback once delivery is uncertain.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
EXPECTED = {
    'sd-state.c': 'c06e80daa966f81962f3f831e3489e3a07f3c13408f468571631642c3ddc2658',
    'sd-state.h': 'fb1ada9230e4b4348fe7cc2afa7c59b11cde75bfe93f0480f411591d56fb9161',
    'test-sd-state.c': '5975be2c6a7b74e4267a2127ec1644967b5de05ae78b9a3c30ea199c547b6a92',
}


class SdStateCore(unittest.TestCase):
    def test_pinned_sources(self):
        import hashlib
        for name, digest in EXPECTED.items():
            path = HERE / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest, name)
        core_lines = sum(len((HERE/name).read_text().splitlines())
                         for name in ('sd-state.c', 'sd-state.h'))
        self.assertLessEqual(core_lines, 400)

    def test_contract_under_sanitizers(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / 'test-sd-state'
            compiled = subprocess.run(
                ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g',
                 '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                 '-fno-omit-frame-pointer', '-fno-pie', '-no-pie',
                 str(HERE/'sd-state.c'), str(HERE/'test-sd-state.c'), '-o', str(binary)],
                text=True, capture_output=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout+compiled.stderr)
            result = subprocess.run([str(binary)], cwd=temporary, text=True,
                                    capture_output=True, timeout=120,
                                    env={'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1',
                                         'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1',
                                         'PATH': '/usr/bin:/bin'})
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn('PASS', result.stdout)
            self.assertFalse(list(Path(temporary).glob('sentinel-*')))


if __name__ == '__main__':
    unittest.main()
