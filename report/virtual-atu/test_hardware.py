#!/usr/bin/env python3
"""Actual virtual PCI peer/aperture bytes, not original CP/ATU-driver proof."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parent
DMA = HERE.parent/'virtual-dma330'
sys.path.insert(0, str(DMA))
from admission import idle_lock
spec = importlib.util.spec_from_file_location('qtest_machine', DMA/'sony-pl330/test_hardware.py')
hardware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hardware)


def program(machine, slot, target, start=0xc0000000):
    register = 0xf7300000+slot*512
    for offset, value in ((0x14,target&0xffffffff), (0x18,target>>32),
                          (8,start), (0xc,0), (0x10,start+0xfffff), (0x20,0),
                          (4,0x80000000)):
        machine.writel(register+offset, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    stage = args.candidate.resolve()
    binary = stage/'build/qemu-system-aarch64'
    proof = json.loads((stage/'build-proof.json').read_text())
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == proof['binary_sha256']
    output = Path(tempfile.mkdtemp(prefix='atu-qtest-', dir='/var/tmp'))
    print('ATU_HARDWARE_OUTPUT', output, flush=True)
    result = {'scope':'explicit virtual PCI peer RAM, not actual CP', 'binary_sha256':proof['binary_sha256'],
              'original_driver_verified':False, 'capture_verified':False, 'slots':[]}
    with idle_lock(HERE.parents[1]/'runtime/analysis/.menu-probe.lock'):
        for enabled in (False, True):
            run = output/('enabled' if enabled else 'disabled'); run.mkdir()
            machine = hardware.Machine(binary, run, False, atu_test=enabled)
            try:
                machine.connect()
                if not enabled:
                    result['default_off_register'] = machine.readl(0xf7300004)
                    continue
                for slot in range(8):
                    target = 0x04000000+slot*0x100000
                    endpoint = 0x600000000+slot*0x100000
                    payload = bytes((i*19+slot*29)&255 for i in range(256))
                    machine.write(endpoint, b'\xa5'*288)
                    machine.write(endpoint+16, payload)
                    program(machine, slot, target)
                    assert machine.readl(0xf7300000+slot*512+4) == 0x80000000
                    assert machine.read(0xc0000010, 256) == payload
                    changed = bytes(value^0x5c for value in payload)
                    machine.write(0xc0000010, changed)
                    assert machine.read(endpoint, 288) == b'\xa5'*16+changed+b'\xa5'*16
                    machine.writel(0xf7300000+slot*512+4, 0)
                    before = machine.read(endpoint, 288)
                    machine.write(0xc0000010, b'\x3d'*256)
                    assert machine.read(endpoint, 288) == before, 'disabled window still writes peer'
                    result['slots'].append({'slot':slot,'actual_peer_and_aperture_bytes_verified':True,
                                            'outside_guards_unchanged':True,'disable_prevents_peer_write':True})
                # High PCI target is outside explicit test backing; never alias it
                # to low RAM or mutate the previous endpoint via truncation.
                program(machine, 0, 0x10004000000)
                before = machine.read(0x600000000, 288)
                machine.write(0xc0000010, b'\x55'*256)
                assert machine.read(0x600000000, 288) == before
                result['high_target_not_truncated'] = True
            finally:
                machine.close()
    result['hardware_aperture_verified'] = True
    (output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print('ATU_HARDWARE_BYTES_PASS', len(result['slots']), flush=True)


if __name__ == '__main__':
    main()
