#!/usr/bin/env python3
"""Original-kernel export/p32 branch pins; no execution or guest writes."""
import hashlib
from pathlib import Path
import struct

root = Path(__file__).resolve().parents[3]/'runtime/analysis'
path = root/'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
data = path.read_bytes()
assert hashlib.sha256(data).hexdigest() == '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
# This linked image base was additionally bound to the actual kernel UDIF
# symbol and inline device record in trial-3l3vi7ab; not an AP/CP address rule.
base = 0xffffff8008080000
exports = {'udif_devices': 0xffffff80086be230,
           'arch_p32_to_p64': 0xffffff800839b780,
           'arch_phys_to_va': 0xffffff800839b608,
           'arch_phys_to_noncache': 0xffffff800839b298}
for name, expected in exports.items():
    values = set()
    start = 0
    while True:
        offset = data.find(name.encode()+b'\0', start)
        if offset < 0:
            break
        # Names may occur in diagnostic text too. Require the export's actual
        # name pointer paired with its function/data value, never the first hit.
        search = 0
        while True:
            position = data.find(struct.pack('<Q', base+offset), search)
            if position < 0:
                break
            if position >= 8:
                value = struct.unpack_from('<Q', data, position-8)[0]
                if base <= value < base+len(data):
                    values.add(value)
            search = position+1
        start = offset+1
    assert values == {expected}, (name, values)
    print(f'PASS actual kernel export {name} {expected:x}')
assert data[0x63e470:0x63e477] == b'330d-0\0'
assert base+0x63e470-0x240 == exports['udif_devices']
expected = bytes.fromhex('0140a0121f00016b88000054e003002a00005eb2c0035fd6'
                         '0140a05202e0bf120100010b3f00026b88000054e003002ac0035fd6')
assert data[0x31b780:0x31b7b4] == expected
print('PASS: <=fdffffff gains bit34; fe000000..feffffff identity; ff range enters error path')
