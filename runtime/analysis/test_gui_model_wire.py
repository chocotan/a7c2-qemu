"""Protocol boundaries only; this test does not claim CP drawing or live input."""
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent


class GuiModelWireTests(unittest.TestCase):
    def test_inline_models_and_atomic_rejection(self):
        fixture = r'''
#include "gui-model-wire.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(int argc, char **argv) {
    assert(argc == 3);
    unsigned char raw[8192];
    FILE *f = fopen(argv[1], "rb"); assert(f);
    size_t n = fread(raw, 1, sizeof raw, f); assert(!ferror(f)); fclose(f);
    struct gui_model_batch out, before;
    memset(&out, 0xa5, sizeof out); before = out;
    int rc = gui_model_decode(raw, n, &out);
    if (!atoi(argv[2])) {
        assert(rc && !memcmp(&out, &before, sizeof out));
    } else if(atoi(argv[2])==2) {
        assert(!rc && out.opaque && out.records<=64);
    } else {
        assert(!rc && out.present == 63);
        unsigned int types[] = {0x10,0x15,0x16,0x19,0x1a,0x1b};
        unsigned int sizes[] = {0x274,0xc,0x14,0xc,4,0x10};
        for (int i=0;i<6;i++) {
            assert(out.values[i].type == types[i] && out.values[i].bytes == sizes[i]);
            for (unsigned int j=0;j<sizes[i];j++) assert(out.values[i].data[j] == i+1);
        }
    }
    assert(gui_model_decode(0, 8, &out));
    assert(gui_model_decode(raw, n, 0));
}
'''
        compiler = shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(compiler)
        records = b''.join(struct.pack('<II', kind, size) + bytes([i + 1]) * size
                           for i, (kind, size) in enumerate([
                               (0x10, 0x274), (0x15, 12), (0x16, 20),
                               (0x19, 12), (0x1a, 4), (0x1b, 16)]))
        valid = struct.pack('<II', 0, len(records)) + records
        self.assertEqual(len(valid), 748)
        bad_size = bytearray(valid)
        struct.pack_into('<I', bad_size, 12, 0xffffffff)
        unknown = bytearray(valid)
        struct.pack_into('<I', unknown, 8, 0x11)
        duplicate = valid + records[:8 + 0x274]
        duplicate = struct.pack('<II', 0, len(duplicate) - 8) + duplicate[8:]
        extras = b''.join(struct.pack('<II', kind, count)+bytes(count)
                          for kind,count in ((0x12,8),(0x13,28),(0x14,20),(0x18,20),(0x1d,8)))
        main_packet = struct.pack('<II',0,len(records)+len(extras))+records+extras
        self.assertEqual(len(main_packet),872)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            binary = root / 'check'
            subprocess.run([compiler, '-x', 'c', '-', str(BASE / 'gui-model-wire.c'),
                            '-I', str(BASE), '-o', str(binary), '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined'], input=fixture, text=True, check=True,
                           capture_output=True)
            cases = [('valid', valid, True), ('truncated-header', valid[:7], False),
                     ('truncated-data', valid[:-1], False), ('bad-size', bad_size, False),
                     ('new-type', unknown, 2), ('main-screen-models',main_packet,2),
                     ('arbitrary-type',struct.pack('<IIII',0,8,0xaabbccdd,0),2),
                     ('too-many',struct.pack('<II',0,65*8)+b''.join(struct.pack('<II',i,0) for i in range(65)),False),
                     ('duplicate', duplicate, False),
                     ('wrong-command', b'\x01' + valid[1:], False),
                     ('trailing-byte', valid + b'\0', False), ('oversize', valid * 6, False)]
            for label, raw, accepted in cases:
                with self.subTest(label=label):
                    path = root / 'packet'
                    path.write_bytes(raw)
                    subprocess.run([str(binary), str(path), str(int(accepted))], check=True,
                                   capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
