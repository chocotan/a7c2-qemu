#!/usr/bin/env python3
"""Associate original sound queries/tables with real backing and native frees."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import struct

BASE = 0x81d000000
CPU = 0x1d000000
BYTES = 0x10340
CAPACITY = 0x20000
SOURCE_SHA = '5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def number(value):
    return int(value, 0)


def digest(data):
    result = 0xcbf29ce484222325
    for byte in data:
        result = ((result ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return f'{result:016x}'


def observer_lines(console, families=('AUDIO',), deduplicate=True):
    """Resynchronize intact audio records after interleaved tty input echo.

    Never repair an event's fields or raw bytes. Multiple observer records in
    one physical line are ambiguous and rejected, not silently split/merged.
    """
    lines, recovered = [], 0
    family = '|'.join(re.escape(name) for name in families)
    marker = re.compile(r'OBS FULL_(?:' + family + r')_[A-Z_]+ ')
    for line in console.decode(errors='replace').splitlines():
        markers = list(marker.finditer(line))
        require(len(markers) <= 1, 'Ambiguous observer framing')
        if markers and markers[0].start():
            recovered += 1
            line = line[markers[0].start():]
        lines.append(line)
    return (list(dict.fromkeys(lines)) if deduplicate else lines), recovered


def received(records, request):
    index, _, req = request
    tid, dst, command = (number(req[key]) for key in ('tid', 'source', 'command'))
    qindex, _, queued = next(row for row in records if row[0] > index and
        row[1].startswith('OBS FULL_AUDIO_REPLY_QUEUED ') and
        number(row[2]['tid']) == tid and number(row[2]['destination']) == dst and
        number(row[2]['command']) == command)
    reply = bytes.fromhex(queued['raw'])
    length = 24 if command == 0x33f else 28 if command == 0x327 else 12
    require(len(reply) == length and number(queued['source']) == 0x92840747, 'Reply source/length differs')
    require(struct.unpack_from('<4H', reply) == (0x200d, command | 0x1000, length, 0x8001),
            'Reply frame/command/flags differs')
    require(struct.unpack_from('<I', reply, 8)[0] == 0x580000, 'Raw status is not domain-tagged success')
    cindex, _, commit = next(row for row in records if row[0] > qindex and
        row[1].startswith('OBS FULL_AUDIO_COMMIT ') and
        row[2].get('reply') == queued['reply'] and row[2].get('lease') == queued['lease'])
    require(number(commit['tid']) == tid and number(commit['request_free_rc']) == 0,
            'Original request release failed')
    findex, _, freed = next(row for row in records if row[0] > cindex and
        row[1].startswith('OBS FULL_AUDIO_NATIVE_REPLY_FREE ') and
        row[2].get('reply') == queued['reply'] and row[2].get('lease') == queued['lease'])
    require(number(freed['tid']) == tid and number(freed['sender']) == tid and
            number(freed['waiter']) == 1 and number(freed['rc']) == 0 and
            number(freed['destination']) == dst and number(freed['command']) == command,
            'Native reply was not released by the original waiter')
    return findex, reply, commit


def verify(run, native=False):
    console = (run / 'console.log').read_bytes()
    if native:
        result = json.loads((run / 'summary.json').read_text())
        identity = json.loads((run / 'runtime-manifest.json').read_text())
        require(identity.get('audio_boot_config_service') is True and identity.get('system_sound_owner') is True and
                identity.get('original_libraries_unchanged') is True and result.get('probe_collected') is True,
                'Explicit native sound owner/completed capture missing')
        require(Path(result['run']).resolve() == run.resolve() and b'Entering exception monitor.' not in console,
                'Native run identity or exception differs')
        selected = identity['selected_initramfs_verified_files']
        require(selected.get('cp/SysSound.bin') == SOURCE_SHA and
                selected.get('simulation/system-sound-owner') == identity['compiled_observer']['system_sound_owner_sha256'],
                'Selected sound source/helper image identity differs')
        here = Path(__file__).resolve().parent
        command = runpy.run_path(str(here.parent / 'native-sound-region.py'))['verify_reservation'](
            run, here / '../../sources/qemu-tools/usr/lib/libfdt.so.1')
        require(re.findall(rb'(?:^|\n)SYSTEM_SOUND_INIT_OK\r?\n',console) and
                not re.findall(rb'(?:^|\n)SYSTEM_SOUND_INIT_FAILED\r?\n',console), 'Guest sound owner did not initialize')
    else:
        result = json.loads((run / 'result.json').read_text())
        identity = json.loads((run / 'inputs.json').read_text())
        require(identity['experiment'].get('audio_service') == 'boot', 'Boot audio profile was not enabled')
        require(result.get('terminal_evidence_checked') is True and
                result['terminal_console_sha256'] == hashlib.sha256(console).hexdigest(), 'Terminal console differs')
    lines, recovered_prefixes = observer_lines(console)
    require(not any(line.startswith('OBS FULL_AUDIO_FAULT ') for line in lines), 'Audio ownership fault')
    records = [(i, line, dict(re.findall(r'(\w+)=([^\s]+)', line))) for i, line in enumerate(lines)]
    if not native:
        memory = json.loads((run / 'system-sound-memory-proof.json').read_text())
        require(memory.get('system_sound_memory_verified') is True and
                memory['console_sha256'] == result['terminal_console_sha256'], 'Independent backing proof missing')
    data = (run / ('system-sound-ram.bin' if native else 'system-sound-memory.bin')).read_bytes()
    require(len(data) == CAPACITY and hashlib.sha256(data[:BYTES]).hexdigest() == SOURCE_SHA and not any(data[BYTES:]),
            'Independent original sound bytes differ')
    query = next(row for row in records if row[1].startswith('OBS FULL_AUDIO_REQUEST ') and
                 number(row[2]['command']) == 0x33f)
    require(bytes.fromhex(query[2]['raw']) == bytes.fromhex('0d203f0308000180'), 'Original query differs')
    qfree, reply, commit = received(records, query)
    require(struct.unpack_from('<Q', reply, 16)[0] == BASE and not any(reply[12:16]), 'Query address/padding differs')
    require(commit['owner_readback'] == '1' and number(commit['phys64']) == BASE and
            number(commit['capacity']) == CAPACITY and number(commit['bytes']) == BYTES,
            'Query did not validate the owned backing')
    tid = number(query[2]['tid'])
    tables = [row for row in records if row[0] > qfree and row[1].startswith('OBS FULL_AUDIO_REQUEST ') and
              number(row[2]['command']) == 0x329 and number(row[2]['tid']) == tid]
    require(len(tables) == 25, f'Original default table count differs: {len(tables)}')
    volumes = [row for row in records if row[0] > qfree and row[1].startswith('OBS FULL_AUDIO_REQUEST ') and
               number(row[2]['command']) == 0x32c and number(row[2]['tid']) == tid]
    require(len(volumes) == 25, f'Original per-kind volume count differs: {len(volumes)}')
    kinds, enabled, disabled, slices, volume_configs = [], [], [], [], []
    for ordinal, row in enumerate(tables):
        raw = bytes.fromhex(row[2]['raw'])
        require(len(raw) == 40 and struct.unpack_from('<4H', raw) == (0x200d, 0x329, 40, 0x8001), 'Table envelope differs')
        table_free, _, applied = received(records, row)
        kind, regist = raw[20], raw[22]
        require(kind != 0 and regist in (0, 1) and number(applied['service_status']) == 0 and
                number(applied['kind']) == kind and number(applied['regist']) == regist, 'Table identity/status differs')
        kinds.append(kind)
        volume_row = volumes[ordinal]
        volume_raw = bytes.fromhex(volume_row[2]['raw'])
        require(table_free < volume_row[0] and len(volume_raw) == 10 and
                struct.unpack_from('<4H', volume_raw) == (0x200d, 0x32c, 10, 0x8001) and
                volume_raw[9] == kind and volume_raw[8] < 8, 'Per-kind volume does not follow the original table')
        volume_free, _, volume_commit = received(records, volume_row)
        require(number(volume_commit['kind']) == kind and number(volume_commit['vol']) == volume_raw[8] and
                number(volume_commit['matched']) == 1 and number(volume_commit['readback']) == volume_raw[8] and
                number(volume_commit['service_status']) == 0, 'Actual per-kind volume readback differs')
        if ordinal + 1 < len(tables):
            require(volume_free < tables[ordinal + 1][0], 'Next table preceded the original volume waiter free')
        volume_configs.append({'kind': kind, 'volume': volume_raw[8]})
        if not regist:
            disabled.append(kind)
            continue
        address, size = struct.unpack_from('<QI', raw, 8)
        offset = address - BASE
        require(address >= BASE and offset < BYTES and offset + size <= BYTES and
                offset + size + 0x40 <= CAPACITY, 'Table range exceeds sound owner')
        expected = digest(data[offset:offset + size])
        require(number(applied['offset']) == offset and number(applied['size']) == size and
                number(applied['phys64']) == address and number(applied['cpu']) == CPU + offset and
                applied['fnv64'] == expected and applied['slice_readback'] == '1', 'Actual slice readback differs')
        enabled.append(kind);slices.append({'kind': kind, 'offset': offset, 'size': size, 'fnv64': expected})
    require(len(set(kinds)) == 25, 'Default table IDs were not unique')
    require(bool(enabled), 'No active original sound slice was registered')
    return {'schema': 2, 'system_sound_config_verified': True, 'query_caller_tid': tid, 'query_address': hex(BASE),
            'evidence_kind': 'native' if native else 'full-system', 'whole_run_success_verified': False,
            'system_sound_memory_verified': True, 'source_sha256': SOURCE_SHA,
            'backing_sha256': hashlib.sha256(data).hexdigest(), 'pixels_consumed': False,
            'observer_prefix_recoveries': recovered_prefixes,
            'default_table_count': len(tables), 'enabled_kinds': enabled, 'disabled_kinds': disabled,
            'slices': slices, 'per_kind_volume': volume_configs,
            'console_sha256': hashlib.sha256(console).hexdigest(),
            'audio_output_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--native', action='store_true', help='Use actual native manifest, summary and RAM export')
    args = parser.parse_args()
    try:
        proof = verify(args.run, native=args.native)
    except (OSError, KeyError, ValueError, StopIteration) as error:
        proof = {'system_sound_config_verified': False, 'error': str(error) or type(error).__name__,
                 'camera_startup_verified': False, 'audio_output_verified': False}
    (args.run / 'system-sound-config-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['system_sound_config_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
