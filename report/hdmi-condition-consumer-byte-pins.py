#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Offline ALLLANG HDMI consumer pins; never executes firmware or changes ready."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

MANIFEST = Path(__file__).with_suffix('.json')
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / 'runtime/analysis/menu-root'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_blob(data, artifact, identity=True):
    name = artifact['path']
    require(data[:6] == b'\x7fELF\x02\x01' and len(data) >= 64, name + ': not ELF64 LE')
    require(struct.unpack_from('<H', data, 18)[0] == 183, name + ': not AArch64')
    if identity:
        require(len(data) == artifact['bytes'], name + ': file size')
        require(hashlib.sha256(data).hexdigest() == artifact['sha256'], name + ': file SHA256')
    for pin in artifact['pins']:
        start = int(pin['file_offset'], 16)
        expected = bytes.fromhex(pin['hex'])
        require(start >= 0 and start + len(expected) <= len(data), pin['id'] + ': range')
        require(hashlib.sha256(expected).hexdigest() == pin['sha256'], pin['id'] + ': manifest digest')
        require(data[start:start + len(expected)] == expected, pin['id'] + ': original bytes differ')


def bl_target(data, address):
    instruction, = struct.unpack_from('<I', data, address)
    require(instruction & 0xfc000000 == 0x94000000, hex(address) + ': not BL')
    immediate = instruction & 0x03ffffff
    if immediate & 0x02000000:
        immediate -= 0x04000000
    return address + immediate * 4


def verify(root, manifest):
    root = root.resolve(strict=True)
    images = {}
    for artifact in manifest['artifacts']:
        path = (root / artifact['path']).resolve(strict=True)
        require(path.is_relative_to(root), 'artifact escapes public root')
        data = path.read_bytes()
        check_blob(data, artifact)
        images[artifact['path']] = data
    ap = images['usr/lib/appFw.so']
    for site, target in ((0x34e3fc4, 0x165e940), (0x34e3fcc, 0x165f720),
                         (0x34e40c0, 0x1660350), (0x34e68d8, 0x36ec384),
                         (0x36ec318, 0x165dbd0), (0x34eccc4, 0x34e4fe4)):
        require(bl_target(ap, site) == target, hex(site) + ': call target')
    mask = ap[0x4c670f0:0x4c67110]
    mapping = struct.unpack_from('<32H', ap, 0x4c67110)
    published = {i + 0x11: mapping[i] for i, active in enumerate(mask) if active}
    require(published == {**{i: 0xf7b + i - 0x11 for i in range(0x11, 0x18)},
                          0x21: 0xf82, 0x22: 0xf83, 0x23: 0xf84, 0x30: 0x5a},
            'unexpected native condition publication map')
    return {
        'result': 'HDMI_CONDITION_CONSUMER_BYTE_PINS_PASS',
        'artifacts': len(manifest['artifacts']),
        'pins': sum(len(a['pins']) for a in manifest['artifacts']),
        'receiver_elf_va': '0x34e3f7c',
        'original_queue': '0x802a0116',
        'condition_source': '0x91ca0816',
        'delivery': 'blocking_osal_rcv_msg_tmo_then_native_osal_free_msg',
        'condition_callback_binding_proven': False,
        'runtime_observed': False, 'hardware_verified': False, 'ready_asserted': False,
        'publication_map': {hex(k): hex(v) for k, v in sorted(published.items())},
    }


def self_test(root, manifest):
    result = verify(root, manifest)
    mutations = 0
    for artifact in manifest['artifacts']:
        data = (root / artifact['path']).read_bytes()
        check_blob(data, artifact)
        for pin in artifact['pins']:
            changed = bytearray(data)
            changed[int(pin['file_offset'], 16)] ^= 1
            try:
                check_blob(changed, artifact, identity=False)
            except ValueError:
                mutations += 1
            else:
                raise ValueError(pin['id'] + ': mutated pin accepted')
        try:
            check_blob(data[:-1], artifact)
        except ValueError:
            mutations += 1
        else:
            raise ValueError(artifact['path'] + ': truncated input accepted')
    bad = bytearray(0x34e3fc4 + 4)
    try:
        bl_target(bad, 0x34e3fc4)
    except ValueError:
        mutations += 1
    else:
        raise ValueError('non-BL instruction accepted')
    result['negative_checks'] = mutations
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT,
                        help='read-only public ALLLANG menu-root')
    parser.add_argument('--self-test', action='store_true',
                        help='also reject one-byte mutations of every pin, truncation and a non-BL')
    args = parser.parse_args()
    try:
        manifest = json.loads(MANIFEST.read_text())
        result = self_test(args.root, manifest) if args.self_test else verify(args.root, manifest)
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, 'HDMI_CONDITION_CONSUMER_BYTE_PINS_FAIL: ' + str(error) + '\n')
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
