#!/usr/bin/env python3
"""Exact P1 file-media contract; source/host evidence only, never read_verified.

Entry point for the P1 builder: inspect(root) before composing an SD profile.
Runtime opt-in for BODYDATA observations: A7C2_FILE_MEDIA_TEST=1 and
A7C2_P1_FILE_MEDIA_PROFILE=original-sd-v1. This is a functional adapter switch,
not a Sony property. No updater/script/runner changes are made here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

SAMPLES = {
    'media': ('usr/lib/libInfraMediaCommon.so', 488280, 'efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec'),
    'elf': ('usr/bin/sdfileinput.elf', 10304, 'c369699a8bbd8919e7951295c8f17d2229327b69484d5875f81e571f03d773af'),
    'sd': ('usr/lib/libsdfileinputupdaterapi.so', 60600, '1a6a3226993ce7c25659bd58e20871d91869083b31440650eec555a06d592d2f'),
    'common': ('usr/lib/libupdatercommon.so', 60152, 'b601bf34b09ca34b74d9ee99f0de0b83d34fab30e3d2648468ab479a0bf6eb05'),
    'fsys': ('usr/lib/libInfraFsys.so', 638528, 'ba0467674b056b3389a34ba974b1f0bbe99f4189d8aa36ad509843596ccacb62'),
}
# VA, length, SHA256 of exact unrelocated original bytes, not decompiler output.
PINS = {
    'media': {
        'init_levels': (0x14f90, 224, '76a18d73d791d0c4a77b424bba575e3b5fcd1e16d1e23f47ed7e2c31d688a342'),
        'virtual_modules': (0x848b8, 80, '5b6fb58e61fa475939767d68a446f97f1bff02c0e5935a3ea8bb51e6515783d8'),
        'driver_open': (0x17f40, 1276, '790c9f6dc6e0a12cc2060776979964f1c932678a89d48afeda855ffcea64bf6e'),
        'rm_init': (0x324ec, 792, '3759030cac6fbebc557a380495ecda6d6c869b93e053e92735591b7aa0184c56'),
        'rm_exchange': (0x2f52c, 340, '882317587f785d1aecce766b7444e69bb73fbbb789d72093ddbab0a011b33516'),
        'mcmn_init': (0x15150, 8, '558365ef3da7d3015cadec4e88e5020cc5e2cb1f57b0370b5c5d70eae5f2fd39'),
        'driver_init': (0x1b1ec, 68, '308bb9d4540c6ddd5b298f9085ac248b174875a976395448ec1d98db09bc5757'),
        'driver_select': (0x27f3c, 296, 'f9774e67348721b48e2e1a8e58bd54945723060a317f4438f0f11b6adda2f456'),
        'dummy_open': (0x21824, 2376, 'ca8d1e7acba819177effe38b53de4bb529cc17dc272c266856fdd3cc6e464104'),
        'dummy_mount': (0x21618, 524, 'b8bce775cc181c3575136db7c78273d5b98d145d37b8926d96a949686cad4f4a'),
        'geometry': (0x1e718, 64, 'c57b1bd115c9dcf3e7058ef3e0b6f336d6ae82a7dca4721f59addd9469c6ba10'),
        'read_impl': (0x1e9b8, 240, '8b914b838b2270cacbe1e03e3eeadb10725effdf741d3b5ac3bdebe47126b828'),
        'write_impl': (0x1eaa8, 280, 'b66b3dbc1eed3693d57a8252157e3b479c405a37359f847300a1a0e7b179226b'),
        'dummy_write_map': (0x209e8, 436, 'acfa5ceddc790f2dd2e6a87a2f4463856abfd8ba55366e6082bea8b77f94aab9'),
        'partition_map': (0x21248, 64, 'ec1467255c5eb082de121d530af9ce9614c4d79259ac246313aeff405b5d14ce'),
        'dummy_read_map': (0x21288, 312, '7a9e648c8fff3a03e7fe9315a065832bbb0620b8eed0aa0ff4baf3b5af964b55'),
        'mbr_gpt_map': (0x20f20, 740, 'ea953cd3f8032da77a480760402f0374cbffd21c384c468f4327c8d095cac2d9'),
        'param_get': (0x40d4c, 160, '972929856ffdac8e0b43bcc09e312e955f529291a7b5accd2d6e2ab3d372addf'),
        'param_set': (0x41088, 140, '9ae6f72273b80759fe34a147a6d101241b5ce74f530e9a6083ea6f3ab7d28236'),
        'param_init': (0x418b4, 564, '0565daadc6a5ac9a77e806fbeeed26dce4b29006be92182369c758693d465288'),
        'mmap_init': (0x3f454, 112, '762b979bc5fc2a70fca14bd057c9bb4de8fa9d8b9a1ccccb061fc098235f9dbc'),
        'rmcmnd_init': (0x41d4c, 40, '180bb9272b2a613cf7210cfd61876ee5c5135e29af1c498696e7a5e4032ec653'),
        'mmca_path': (0x7f5f8, 32, 'c94f5e7082946062eaa00effa3c59dc72232cbedaac2e9b8e19fe146d686a953'),
        'param_69': (0x82420, 32, 'ee124b69f51b4cbe93cd6326f85f104e2141c59e6148459c47ac64809d46742d'),
        'param_f6': (0x835c0, 32, 'f1ce00f57905a1d5ca0694d35c4dd3e3969208487c0b24ca7a96747324ee90b5'),
    },
    'sd': {
        'sd_init': (0xa758, 236, '18b3689b0fc5973c5a82aa5fb510ac03178dda5f1ee469bef3f0e7f506d03249'),
        'firmware_find': (0xa8f8, 176, '2d479005ed7152a59c223b28be22f84f163ead7390d7e218af67de05164fbc72'),
        'header_open': (0x8470, 36, 'f0f48be6946c95483f568149fde7be3420cab95cc59284287604a73b716c08e6'),
    },
    'common': {
        'handler_open': (0x8d9c, 108, '6650cbdf9a92252ae20f828d0bc1ffa4ec93650482d4dbfab460ebabebefc1fd'),
        'handler_close': (0x8e08, 92, '6f97eeb722f1d459872ad4833b557bb40269c9c06e51cc23708373730a621152'),
        'handler_read': (0x8f2c, 184, 'e2b3e4b85d454397a4e11279a0a00ab32090c1a32e54fc051be441671697fa09'),
        'handler_seek': (0x8fe4, 176, '0859226b74a1e28772bc8147dd3e1c7fef2940fcf970e1cd7a0df9905f2086aa'),
    },
    'fsys': {'read_entry': (0x2edc0, 16, 'aa486af301553e45ed3a2fc0cea20c16e19494ae30974c6eec72294032ad8745')},
    'elf': {'backup_path': (0x400a64, 24, 'ecf94d53ae282e294b66c32843dcf62be8e508549d8b4aae30403b4a44b2d20c')},
}


def va_offset(data, address, length):
    if data[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('Expected little endian ELF64 AArch64')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    for i in range(count):
        kind, _, offset, va, _, filesz, _, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + i * size)
        if kind == 1 and va <= address and 0 <= length <= filesz - (address - va):
            return offset + address - va
    raise ValueError('VA is outside file backed PT_LOAD')


def inspect(root):
    """Reject every wrong input, record windows plus original dynamic bindings."""
    root = Path(root)
    records, images, pins = {}, {}, []
    for key, (relative, size, digest) in SAMPLES.items():
        path = root / relative
        data = path.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('P1 identity mismatch: ' + relative)
        images[key] = data
        records[key] = dict(path=relative, size=size, sha256=digest)
        for name, (va, count, expected) in PINS[key].items():
            offset = va_offset(data, va, count)
            actual = hashlib.sha256(data[offset:offset + count]).hexdigest()
            if actual != expected:
                raise ValueError('P1 pin mismatch: ' + name)
            pins.append(dict(sample=key, name=name, va=hex(va), offset=hex(offset), size=count, sha256=actual))
    dynamic = subprocess.run(['aarch64-linux-gnu-readelf', '-dWrVs', str(root / SAMPLES['media'][0])],
                             text=True, capture_output=True, check=True).stdout
    for symbol in ('mcmn_param_init', 'mcmn_param_getul', 'mcmn_param_setul'):
        if not re.search(r'FUNC\s+GLOBAL\s+DEFAULT\s+10\s+' + symbol + r'\s', dynamic):
            raise ValueError('Unexpected export binding: ' + symbol)
    if 'SYMBOLIC' in dynamic or not re.search(r'R_AARCH64_JUMP_SLOT\s+\S+\s+mcmn_param_init\s', dynamic):
        raise ValueError('Original init is not preemptible through its PLT')
    media = images['media']
    if struct.unpack_from('<H', media, 0x6ed4 + 190 * 2)[0] != 1:
        raise ValueError('P1 mcmn_param_init has an unexpected symbol version')
    def string(va):
        off = va_offset(media, va, 1)
        return media[off:media.index(0, off)].decode('ascii')
    path = va_offset(media, 0x7f5f8, 32)
    real, image = struct.unpack_from('<QQ', media, path)
    if (string(real), string(image)) != ('/dev/mmca', '/image_mmca'):
        raise ValueError('Unexpected path table')
    return dict(schema='p1-file-media-contract-v1', source_class='functional-adapter',
                inputs=records, pins=pins, source_verified=True, guest_executed=False, read_verified=False,
                binding=dict(call='0x14ff0 -> PLT 0x13820 -> mcmn_param_init@Base 0x418b4',
                             dynamic_sha256=hashlib.sha256(dynamic.encode()).hexdigest(),
                             readback_required=['EXISTMEDIADRIVER=0', 'DBG_DRV_DUMMY_OMIT_WRITE(0xf6)=0']),
                selection=dict(parameter='0x69', branch='0x27f70', zero_module_table='0x848b8 (2 x 40B)',
                               nonzero_module_table='0x847a0 (7 x 40B)',
                               zero_device_table='0x83f20 (68 x 32B)', zero_root_table='0x85108',
                               real_path=string(real), image_path=string(image), flags='open64 O_RDWR|O_CLOEXEC=0x80002, no create'),
                dependencies=dict(module_free=False, reason='Original init still opens /dev/mcmn and /dev/stream2; selected RM init exchanges OSAL queue 0x80d9016e messages; Fsys/Backup remain required'),
                bodydata=dict(path='A:/BODYDATA.DAT (uppercase drive A-Z)',
                              chain='Updater::FsysFileHandler -> Fsys_*@plt -> PrFILE FAT',
                              expected_input='Profile builder must supply immutable expected BODYDATA bytes/size/SHA256',
                              coverage=False, mount_find_open_validated=False))


BODY_READ = re.compile(r'P1_BODY_READ pid=(\d+) handle=([0-9a-f]+) generation=(\d+) offset=(\d+) '
                       r'requested=(-?\d+) actual=(-?\d+) hashed=(\d+) known=([01]) actor=([01]) sha256=([0-9a-f]{64}|-)')


def body_observations(text, expected, owner):
    """Compare only real returned-data digests; never promote log coverage to VM proof.

    Separate handles/generations and holes remain separate. A short read contributes
    only its actual bytes. Hash caps and unknown offsets/actors contribute no coverage.
    """
    if type(owner) is not int or owner <= 0 or not isinstance(expected, bytes) or not expected:
        raise ValueError('Require nonempty expected bytes and exact positive owner PID')
    observations, spans = [], {}
    for line in text.splitlines():
        if not line.startswith('P1_BODY_READ '):
            continue
        match = BODY_READ.fullmatch(line)
        if not match:
            raise ValueError('Malformed BODYDATA read observation')
        pid, handle, generation, offset, requested, actual, hashed, known, actor, digest = match.groups()
        pid, generation, offset, requested, actual, hashed, known, actor = map(int,
            (pid, generation, offset, requested, actual, hashed, known, actor))
        valid = (pid == owner and generation > 0 and known == actor == 1 and
                 0 < hashed <= actual <= requested and hashed <= 65536 and
                 offset + actual <= len(expected) and
                 hashlib.sha256(expected[offset:offset + hashed]).hexdigest() == digest)
        observations.append(dict(pid=pid, handle=handle, generation=generation, offset=offset,
                                 actual=actual, hashed=hashed, matches_expected_slice=valid))
        if valid:
            spans.setdefault((pid, handle, generation), []).append((offset, offset + hashed))
    covered = False
    for intervals in spans.values():
        end = 0
        for start, stop in sorted(intervals):
            if start > end:
                break
            end = max(end, stop)
        covered |= end == len(expected)
    return dict(observations=observations, expected_size=len(expected),
                expected_sha256=hashlib.sha256(expected).hexdigest(), observed_byte_coverage=covered,
                coverage=False, read_verified=False,
                reason='Read observations alone do not bind original mount/find/open lifecycle or a completed P1 run')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inspect(args.root)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"P1_FILE_MEDIA_SOURCE pins={len(report['pins'])} read_verified=false")


if __name__ == '__main__':
    main()
