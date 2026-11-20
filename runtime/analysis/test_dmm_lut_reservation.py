"""Compile the actual observer parser against the original launcher reservations."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class DmmLutReservation(unittest.TestCase):
    def test_original_launcher_and_execute_reservation(self):
        source = (HERE / 'menu-observe.c').read_text()
        parser = source[source.index('static int dmm_lut_number('):source.index('\nstatic int headless_osd_enabled;')]
        owner = 'memrsv=0x00030000@0x41d000000:uc'
        original = ('memrsv=0x00001000@0x400000000 memrsv=0x00060000@0x400020000 '
                    'memrsv=0x01000000@0x401000000:ex memrsv=0x00200000@0x403e00000:uc '
                    'memrsv=0x00C00000@0x404000000 memrsv=0x00400000@0x404C00000:uc '
                    'memrsv=0x01000000@0x405000000 memrsv=0x00200000@0x410000000 '
                    'memrsv=0x0BE00000@0x410200000:uc memrsv=0x02000000@0x422000000 '
                    'memrsv=0x0C400000@0x424000000 memrsv=0xCFC00000@0x430400000:uc '
                    'memrsv=0x00100000@0x41e000000:uc memrsv=0x00900000@0x41e100000:uc '
                    'memrsv=0x00002000@0x500000000:uc ' + owner)
        cases = [(original, 1), (owner + ' memrsv=0x1000@0x1000:ex', 1),
                 (owner + ' memrsv=0x1000@0x41d020000:ex', 0),
                 (owner + ' memrsv=0x1000@0x1000:exgarbage', 0),
                 (owner + ' memrsv=0x1000@0x1000:ex:uc', 0),
                 (owner + ' memrsv=4096@17666539520:ex', 0),
                 (owner + ' ' + owner, 0),
                 (owner + ' memrsv=0x1000@0x1000:garbage', 0)]
        code = '#include <assert.h>\n#include <errno.h>\n#include <stdlib.h>\n#include <string.h>\n#include "dmm-service.h"\n'
        code += parser + '\nint main(void) {\n'
        code += ''.join(f'assert(dmm_lut_reserved({json.dumps(command)}) == {expected});\n' for command, expected in cases)
        code += 'return 0; }\n'
        with tempfile.TemporaryDirectory(prefix='.dmm-lut-test-', dir=HERE) as temp:
            folder = Path(temp)
            (folder / 'test.c').write_text(code)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                            '-I', str(HERE), str(folder / 'test.c'), '-o', str(folder / 'test')], check=True)
            subprocess.run([str(folder / 'test')], check=True)


if __name__ == '__main__':
    unittest.main()
