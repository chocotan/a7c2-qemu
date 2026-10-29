#!/usr/bin/env python3
"""Verify one completed five-edge native run; never contact or control the VM.

Usage: python3 scratch/evaluate-five-edges-native.py run-BASENAME
       python3 scratch/evaluate-five-edges-native.py --self-test
Only a fully verified run gets five-edges-native-evaluation.json. Missing or
partial evidence fails closed; no summary.json or public proof is generated.
"""
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile

BASE = Path(__file__).resolve().parents[1]
OBSERVER_SHA = '7cc66542d4e387d3341c47cdd9d09e8ec68a31e25df4f6f6eacfec21581d33c9'
QEMU_SHA = 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
INITIAL_ARCHIVE_SHA = '98f681cc44683cb7a09c7f974439665801cafe2202f887f3351af8ade1cb3b8e'
INITIAL_SOURCE_COUNT = 291
SPECS = (
    ('FULL_IMAGING_PIN_CONNECT', 'imaging_pin_connection',
     'virtual-imaging-out1-bb-in1-v1', (0, 2, 1, 0x90050004), (0, 1, 1, 0x9284074a)),
    ('FULL_IMAGING_CONTROL_CONNECT', 'imaging_control_connection',
     'virtual-imaging-control0-bb-control0-v1', (8, 2, 0, 0x90050004), (8, 1, 0, 0x9284074a)),
    ('FULL_IMAGING_ADF_CONNECT', 'imaging_adf_connection',
     'virtual-imaging-audio0-adf-audio0-v1', (3, 2, 0, 0x90050004), (3, 1, 0, 0x9058003f)),
    ('FULL_INFRABB_VEF_CONNECT', 'infrabb_vef_connection',
     'virtual-infrabb-out1-vef-in1-same-format-v1', (0, 2, 1, 0x9284074a), (0, 1, 1, 0x905a0048)),
    ('FULL_INFRABB_VEF_CONTROL_CONNECT', 'infrabb_vef_control_connection',
     'virtual-infrabb-control0-vef-control0-v1', (8, 2, 0, 0x9284074a), (8, 1, 0, 0x905a0048)),
)
PAYLOAD = bytes.fromhex('01000000000000008007000038040000')
CURRENT = bytes.fromhex('0100000000000000010000008007000038040000')
FORWARD_TAGS = (
    'FULL_IMAGING_PIN_CONNECT_FORWARD_FORMAT_CONSUMED',
    'FULL_INFRABB_VEF_FORWARD_VEF_FORMAT_CONSUMED',
    'FULL_INFRABB_VEF_FORWARD_BB_FORMAT_CONSUMED',
)


class EvidenceError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise EvidenceError(str(reason))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fnv(data):
    h = 0xcbf29ce484222325
    for value in data:
        h = ((h ^ value) * 0x100000001b3) & 0xffffffffffffffff
    return f'{h:016x}'


def fields_equal(row, **expected):
    for key, value in expected.items():
        require(row['fields'].get(key) == str(value),
                (row['line'], key, row['fields'].get(key), value))
    return row


class Log:
    def __init__(self, raw):
        self.raw = raw
        self.lines = raw.decode(errors='replace').split('\n')
        self.records = []
        for number, line in enumerate(self.lines, 1):
            match = re.search(r'\bOBS (\w+) ', line)
            if match:
                text = line[match.start():].strip()
                self.records.append({'line': number, 'tag': match[1], 'raw': text,
                                     'fields': dict(re.findall(r'(\w+)=([^\s]+)', text))})

    def rows(self, tag):
        return [row for row in self.records if row['tag'] == tag]

    def one(self, tag, **expected):
        found = self.rows(tag)
        require(len(found) == 1, (tag, 'expected exactly one record', len(found)))
        return fields_equal(found[0], **expected)


def raw_bytes(row, length):
    data = bytes.fromhex(row['fields']['raw'])
    fields_equal(row, bytes=length)
    require(len(data) == length, (row['tag'], 'wire length', len(data), length))
    return data


def frame_bytes(length, opcode, kind, words, caller=0, opaque=b'\0' * 4):
    data = bytearray(length)
    struct.pack_into('<IIHHII', data, 0, caller, 0xa0a0a0a0, 1, length, 24, length)
    data[20:24] = opaque
    struct.pack_into('<4H', data, 24, 0x1000, opcode, length - 24, kind)
    struct.pack_into('<' + 'I' * len(words), data, 32, *words)
    return bytes(data)


def request_bytes(row, source, sink):
    data = raw_bytes(row, 64)
    caller = struct.unpack_from('<I', data)[0]
    require(caller >> 28 == 8 and caller & 0xfffffff, (row['tag'], 'dynamic caller', caller))
    fields_equal(row, source=hex(caller), destination=hex(source[3]))
    # The original request's word at +20 is opaque, not a zero-initialized model field.
    require(data == frame_bytes(64, 1, 2, source + sink, caller, data[20:24]),
            (row['tag'], 'complete original request shape/key'))
    return data, caller


def model_frame(row, length, opcode, kind, source, destination, words):
    data = raw_bytes(row, length)
    fields_equal(row, source=hex(source), destination=hex(destination))
    require(data == frame_bytes(length, opcode, kind, words),
            (row['tag'], 'complete independent model frame'))
    return data


def verify_build(run, manifest):
    inputs_raw = (run / 'observer-build-inputs.json').read_bytes()
    inputs = json.loads(inputs_raw)
    require(inputs['observer_sha256'] == OBSERVER_SHA, 'observer SHA differs from fifth-edge ABI build')
    require(manifest['compiled_observer'] == inputs, 'compiled manifest differs from archived build inputs')
    require(manifest['selected_observer_matches_build'] is True, 'selected observer mismatch')
    selected = manifest['selected_initramfs_verified_files']
    require(selected['simulation/menu-observe.so'] == OBSERVER_SHA, 'initramfs observer mismatch')
    files = manifest['files']
    require(files[str(BASE / 'menu-observe.so')] == OBSERVER_SHA, 'manifest observer digest mismatch')
    require(files[str(BASE / 'observer-build-inputs.json')] == sha(inputs_raw), 'build-input manifest digest mismatch')
    archive_path = run / 'observer-build-sources.tar.gz'
    require(sha(archive_path.read_bytes()) == inputs['source_archive_sha256'], 'source archive digest mismatch')
    sources = inputs['sources']
    require(len(sources) >= INITIAL_SOURCE_COUNT, 'missing frozen fifth-edge sources')
    archived = {}
    with tarfile.open(archive_path) as archive:
        members = [member for member in archive.getmembers() if not member.isdir()]
        require(all(member.isfile() for member in members), 'archive contains non-ordinary inputs')
        require(len({member.name for member in members}) == len(members), 'duplicate archive members')
        require(json.load(archive.extractfile('source-inputs.json')) == sources, 'source input index mismatch')
        paths = [entry['archive_path'] for entry in sources.values()]
        require(len(set(paths)) == len(paths), 'duplicate source input paths')
        require({member.name for member in members} == set(paths) | {'source-inputs.json'},
                'archive/index file set mismatch')
        for name, entry in sources.items():
            path = PurePosixPath(entry['archive_path'])
            require(not path.is_absolute() and '..' not in path.parts and path.name == Path(name).name,
                    ('invalid archive source path', name))
            data = archive.extractfile(str(path)).read()
            require(sha(data) == entry['sha256'], ('archived source digest mismatch', name))
            archived[str(path)] = data
    def source(name):
        matches = [data for path, data in archived.items() if path.endswith('/' + name)]
        require(len(matches) == 1, ('missing/ambiguous frozen source', name))
        return matches[0].decode()
    build = source('build-observers.sh')
    require('infrabb-vef-control-connection' in build, 'fifth endpoint not in frozen build')
    require('vef-pinmem-input-connection' not in build, 'sixth endpoint unexpectedly linked')
    observer = source('menu-observe.c')
    require('MENU_INFRABB_VEF_CONTROL_CONNECT' in observer, 'fifth profile absent from frozen observer')
    require('MENU_VEF_PINMEM_INPUT_CONNECT' not in observer, 'sixth endpoint unexpectedly wired')
    require('full_infrabb_vef_connection_accept_forwarded_vef_format' in source('infrabb-vef-connection.c'),
            'expected shared cache interface absent')
    require('runtime_status22_writer_generation' in source('vef-path-device.c'), 'SetPath producer tracking absent')
    require(manifest['original_libraries_unchanged'] is True, 'original libraries were modified')
    libraries = {}
    libraries_absent_from_general_index = []
    for path, digest in selected.items():
        if path.startswith('usr/lib/'):
            original = BASE / 'menu-root' / path
            require(sha(original.read_bytes()) == digest, ('original library readback mismatch', path))
            if str(original) in files:
                require(files[str(original)] == digest, ('original library manifest mismatch', path))
            else:
                libraries_absent_from_general_index.append(path)
            libraries[path] = digest
    require(len(libraries) >= 10, 'original library identity evidence incomplete')
    backup = manifest['backup_transport']
    require(backup['binary_sha256'] == QEMU_SHA, 'public a0d QEMU candidate mismatch')
    require(files[backup['binary']] == QEMU_SHA, 'QEMU manifest mismatch')
    require(sha(Path(backup['binary']).read_bytes()) == QEMU_SHA, 'QEMU binary readback mismatch')
    for _, profile_key, profile, _, _ in SPECS:
        require(manifest[profile_key + '_profile'] == profile, ('missing fifth-run profile', profile_key))
        require(backup[profile_key + '_profile'] == profile, ('backup profile mismatch', profile_key))
    sixth_fields = {key: value for key, value in manifest.items() if key.startswith('vef_pinmem_input')}
    require(not any(value is True or (key.endswith('_profile') and value)
                    for key, value in sixth_fields.items()), 'sixth endpoint unexpectedly enabled')
    abi_path = BASE / 'scratch/five-edges-abi.json'
    abi = json.loads(abi_path.read_text())
    require(abi['observer_sha256'] == OBSERVER_SHA and abi['returncode'] == 0,
            'fifth observer ABI check missing or unsuccessful')
    require(abi['source_count'] == INITIAL_SOURCE_COUNT and abi['source_archive_sha256'] == INITIAL_ARCHIVE_SHA,
            'initial fifth ABI source identity mismatch')
    require((abi['host_tests_passed'], abi['host_subtests_passed'], abi['fifth_host_scenarios']) == (1102, 139, 109),
            'host regression reference changed')
    return {'observer_sha256': OBSERVER_SHA, 'source_archive_sha256': inputs['source_archive_sha256'],
            'frozen_source_count': len(sources), 'all_frozen_sources_hash_verified': True,
            'compiled_manifest_and_selected_initramfs_match': True,
            'initial_ABI_source_count': INITIAL_SOURCE_COUNT, 'initial_ABI_archive_sha256': INITIAL_ARCHIVE_SHA,
            'run_rebuild_changed_source_archive': inputs['source_archive_sha256'] != INITIAL_ARCHIVE_SHA,
            'run_rebuild_retained_observer_SHA': True, 'original_library_digests': libraries,
            'libraries_missing_only_from_general_file_index': libraries_absent_from_general_index,
            'original_library_readback_policy': 'all selected initramfs library hashes checked against actual public library bytes; general index additionally checked where present',
            'public_qemu_sha256': QEMU_SHA,
            'sixth_endpoint': {'linked': False, 'wired': False, 'manifest_fields': sixth_fields,
                               'policy': 'frozen link script and observer omit sixth endpoint; absent manifest fields are not runtime false evidence'},
            'host_regression_reference': {'file': str(abi_path.relative_to(BASE)),
                                           'sha256': sha(abi_path.read_bytes()), 'tests': 1102,
                                           'subtests': 139, 'new_fifth_scenarios': 109,
                                           'native_evidence': False}}


def verify_edge(log, spec, previous_free, identity):
    prefix, _, profile, source, sink = spec
    for suffix in ('FAULT', 'CLEANUP_FAULT', 'RESOURCES_FAULT', 'RESOURCES_REFUSED', 'FORMAT_REFUSED'):
        require(not log.rows(prefix + '_' + suffix), (prefix, suffix))
    tags = ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED', 'COMMIT', 'REPLY_FREE')
    edge = {tag: log.one(prefix + '_' + tag) for tag in tags}
    original, caller = request_bytes(edge['REQUEST'], source, sink)
    q = edge['REQUEST']['fields']
    if identity is None:
        identity = (q['pid'], q['tid'])
    for tag in ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED', 'REPLY_FREE'):
        fields_equal(edge[tag], pid=identity[0], tid=identity[1])
    model_frame(edge['PEER_REQUEST'], 64, 0x100, 1, source[3], sink[3], source + sink)
    model_frame(edge['PEER_REPLY'], 72, 0x8100, 1, sink[3], source[3], source + sink + (0, 0))
    model_frame(edge['REPLY_QUEUED'], 56, 0x8001, 2, source[3], caller, source + (0, 0))
    fields_equal(edge['REPLY_FREE'], bytes=56, rc=0, faults=0, ap_consumed=1,
                 destination=hex(caller), expected=hex(caller))
    require(edge['REPLY_QUEUED']['fields']['pointer'] == edge['REPLY_FREE']['fields']['pointer'],
            (prefix, 'AP freed a different pointer'))
    live_pointers = [q['pointer'], edge['PEER_REQUEST']['fields']['pointer'], edge['PEER_REPLY']['fields']['pointer']]
    require(len(set(live_pointers)) == 3 and all(int(pointer, 0) for pointer in live_pointers),
            (prefix, 'independent live control allocations'))
    require(edge['REPLY_QUEUED']['fields']['pointer'] != q['pointer'], (prefix, 'AP reply aliases original request'))
    fields_equal(edge['COMMIT'], connections=1, unique_reply=1, source_state=0, peer_state=0, source_pending=0)
    order = [edge[tag]['line'] for tag in tags]
    require(order == sorted(set(order)) and previous_free < order[0], (prefix, 'transaction order'))
    profiles = [row for row in log.rows(prefix + '_PROFILE') if row['fields'].get('pid') == identity[0]]
    require(len(profiles) == 1, (prefix, 'one profile for actual AP process'))
    edge['profile'] = fields_equal(profiles[0], requested=profile, enabled=1, first_missing='none',
                                   owner_pid=identity[0], initialized=1, before_any_input=1)
    require(profiles[0]['line'] < order[0], (prefix, 'profile after request'))
    generic = [row for row in log.rows('PIN_CONTROL_REQUEST')
               if previous_free < row['line'] < order[0] and row['fields'].get('raw') == original.hex()]
    require(len(generic) == 1, (prefix, 'original sender raw request not matched'))
    fields_equal(generic[0], tid=identity[1], source=hex(caller), destination=hex(source[3]), bytes=64)
    edge.update(prefix=prefix, source_pin=source, sink_pin=sink, caller=caller,
                original_sender_request=generic[0], opaque_original_word20=original[20:24].hex())
    return edge, identity


def ssyn_packet(version, entry_type):
    data = bytearray(80)
    for offset, value in ((0, 0x4e595353), (4, version), (12, 1), (16, 32),
                          (32, 0x59525445), (40, entry_type), (44, 64), (48, 16)):
        struct.pack_into('<I', data, offset, value)
    data[64:] = PAYLOAD
    return bytes(data)


def verify_format(log, edge, identity, first):
    prefix = edge['prefix']
    source, sink = edge['source_pin'], edge['sink_pin']
    handle, version, etype = (0x8400, 0x06000000, 1) if first else (0x8800, 0x02000000, 0)
    commands = (0x20, 0x25, 0x24, 0x23) if first else (0x20, 0x25, 0x24, 0x25, 0x23)
    lengths = (216,) * 4 if first else (152, 152, 216, 216, 216)
    requests, answers = log.rows(prefix + '_DMM_REQUEST'), log.rows(prefix + '_DMM_REPLY')
    require(len(requests) == len(answers) == len(commands), (prefix, 'DMM operation count'))
    last = edge['PEER_REPLY']['line']
    for index, (request, answer, opcode, length) in enumerate(zip(requests, answers, commands, lengths)):
        consumer = index >= 2
        token = 0x55 if first or consumer else 0
        sender = source[3] if consumer else sink[3]
        fields_equal(request, pid=identity[0], tid=identity[1], source=hex(sender), destination='0x61003c')
        fields_equal(answer, pid=identity[0], tid=identity[1], source='0x61003c', destination=hex(sender))
        require(request['fields']['pointer'] == answer['fields']['pointer'], (prefix, opcode, 'DMM in-place reply'))
        want = bytearray(length)
        struct.pack_into('<H', want, 0, opcode)
        struct.pack_into('<H', want, 20, token)
        if opcode == 0x20:
            struct.pack_into('<I', want, 4, 0x404)
            struct.pack_into('<I', want, 12, 0xffffffff)
            struct.pack_into('<H', want, 22, 1)
        else:
            struct.pack_into('<I', want, 8, handle)
        if opcode == 0x24 and not first:
            struct.pack_into('<I', want, 12, 0xffffffff)
        if opcode == 0x23 and first:
            struct.pack_into('<H', want, 22, 2)
        require(raw_bytes(request, length) == want, (prefix, opcode, 'full DMM request'))
        want = bytearray(length)
        struct.pack_into('<H', want, 0, opcode | 0x8000)
        struct.pack_into('<H', want, 6, token)
        struct.pack_into('<I', want, 12, handle)
        if opcode == 0x20:
            struct.pack_into('<I', want, 16, 0x404)
        if opcode in (0x20, 0x24):
            struct.pack_into('<H', want, 8, 1)
            struct.pack_into('<Q', want, 24, 0x500000000)
            struct.pack_into('<I', want, 32, 512)
        require(raw_bytes(answer, length) == want, (prefix, opcode, 'full DMM reply'))
        require(last < request['line'] < answer['line'], (prefix, opcode, 'DMM ordering'))
        last = answer['line']
    refs = log.rows(prefix + '_REFERENCE_READBACK')
    expected = [('allocated', (1, 1, 1, 0, 0)), ('creator-closed', (1, 0, 1, 0, 0)),
                ('transferred', (1, 0, 0, 1, 0)), ('consumer-open', (1, 1, 0, 1, 1))]
    if not first:
        expected.append(('consumer-closed', (1, 0, 0, 1, 0)))
    require(len(refs) == len(expected), (prefix, 'reference history count'))
    for row, (phase, values) in zip(refs, expected):
        fields_equal(row, pid=identity[0], tid=identity[1], phase=phase, handle=hex(handle),
                     **dict(zip(('owners', 'opens', 'creator', 'consumer', 'consumer_open'), values)))
    written = log.one(prefix + '_FORMAT_WRITTEN', pid=identity[0], tid=identity[1], handle=hex(handle),
                      physical='0x500000000', cp_virtual='0x80000000', bytes=80,
                      header_word=f'0x{version:08x}', key=0, payload_bytes=16, payload=PAYLOAD.hex(),
                      fnv64=fnv(ssyn_packet(version, etype)))
    require(written['fields']['fnv64'] == ('88d47938b00f682e' if first else '472ea89986f7114b'),
            (prefix, 'SSYN typed packet fingerprint'))
    notify = log.one(prefix + '_FORMAT_NOTIFY', pid=identity[0], tid=identity[1])
    model_frame(notify, 80, 0x104, 1, sink[3], source[3], sink + source + (0x404, handle, 0, 0))
    consumed = log.one(prefix + '_FORMAT_CONSUMED', pid=identity[0], tid=identity[1], handle=hex(handle),
                       bytes=16, mapped_backing_read=1, payload_fnv64=fnv(PAYLOAD))
    require(fnv(PAYLOAD) == '1a3c540ebc5023bd', 'control payload fingerprint')
    if first:
        fields_equal(consumed, cache='0,1,1920,1080,0', synchronization_object='0x21', acquires=1, releases=1)
    else:
        fields_equal(consumed, currentinfo_bytes=20, current_fnv64=fnv(CURRENT), command_fnv64=fnv(CURRENT),
                     code=1, component=0, flags_u16=0, width=1920, height=1080, BB_IN1_state=0)
        require(fnv(CURRENT) == '3c3a32bb6809f4cc', 'VEF currentinfo fingerprint')
    retired = log.one(prefix + '_BUFFER_RETIRED', owners=0, opens=0, live=0,
                      **({'Free23_option2': 1, 'creator_Close25_was_not_release': 1, 'bytes_preserved': 1} if first
                         else {'Free23_option0': 1, 'creator_Close25': 1, 'consumer_Close25': 1, 'share21': 0}))
    require(edge['PEER_REPLY']['line'] < answers[0]['line'] < refs[0]['line'] < written['line'] <
            requests[1]['line'] < answers[1]['line'] < refs[1]['line'] < notify['line'] < refs[2]['line'] <
            requests[2]['line'] < answers[2]['line'] < refs[3]['line'] < consumed['line'] <
            requests[3]['line'] < answers[3]['line'] < retired['line'] < edge['REPLY_QUEUED']['line'],
            (prefix, 'format data and ownership sequence'))
    if not first:
        require(answers[3]['line'] < refs[4]['line'] < requests[4]['line'] < answers[4]['line'] < retired['line'],
                (prefix, 'Close25 must precede Free0'))
    edge.update(DMM_requests=requests, DMM_replies=answers, references=refs,
                format_written=written, format_notice=notify, format_consumed=consumed, retired=retired)


def verify_internal_frees(log, edge, identity, count):
    freed = log.rows(edge['prefix'] + '_INTERNAL_FREE')
    require(len(freed) == count, (edge['prefix'], 'internal free count', len(freed)))
    for row in freed:
        fields_equal(row, pid=identity[0], tid=identity[1], destination=hex(edge['caller']), rc=0)
        require(edge['REQUEST']['line'] < row['line'] < edge['REPLY_QUEUED']['line'],
                (edge['prefix'], 'internal ownership not retired before publication'))
    for tag in ('PEER_REQUEST', 'PEER_REPLY'):
        matches = [row for row in freed if row['fields']['pointer'] == edge[tag]['fields']['pointer']
                   and edge['PEER_REPLY']['line'] < row['line']]
        require(matches, (edge['prefix'], 'independent peer allocation not freed', tag))
    edge['internal_frees'] = freed


def next_pin_send(log, request):
    sends = [row['line'] for row in log.records if row['tag'] in ('PIN_QUERY', 'PIN_CONTROL_REQUEST')
             and row['fields'].get('tid') == request['fields']['tid'] and row['line'] > request['line']]
    return min(sends, default=len(log.lines) + 1)


def verify_early_refusal(log, edge, first_line):
    prefix = edge['prefix']
    refused = log.rows(prefix + '_UNADMITTED')
    require(refused, (prefix, 'missing early boot refusal'))
    for row in refused:
        fields_equal(row, requests=0, faults_unchanged=1, owner_not_reset=1)
        require(row['line'] < first_line, (prefix, 'unexpected late unadmitted request'))
    early = []
    for row in log.rows('PIN_CONTROL_REQUEST'):
        if row['line'] >= first_line:
            continue
        data = bytes.fromhex(row['fields']['raw'])
        if len(data) == 64 and struct.unpack_from('<8I', data, 32) == edge['source_pin'] + edge['sink_pin']:
            request_bytes(row, edge['source_pin'], edge['sink_pin'])
            require(data[4:] == bytes.fromhex(edge['REQUEST']['fields']['raw'])[4:],
                    (prefix, 'early and admitted wire differs beyond dynamic caller'))
            early.append(row)
    require(len(early) == len(refused), (prefix, 'early raw requests and unadmitted records differ'))
    for request, refusal in zip(early, refused):
        require(request['line'] < refusal['line'] < next_pin_send(log, request),
                (prefix, 'early refusal not tied to original thread send'))
    return {'unadmitted': refused, 'original_requests': early, 'owner_not_reset': True}


def verify_graph(log):
    require(b'Entering exception monitor.' not in log.raw, 'guest entered exception monitor')
    edges, identity, last = [], None, 0
    for spec in SPECS:
        edge, identity = verify_edge(log, spec, last, identity)
        edges.append(edge)
        last = edge['REPLY_FREE']['line']
    first, control, audio, fourth, fifth = edges
    for edge, address in ((first, '0x01acad10'), (control, '0x01acad0f')):
        marker = log.one(edge['prefix'] + '_PEER_MARKER_WRITTEN', source_CP_VA=address,
                         old_value_known=0, value=1, readback=1, writes=1)
        require(edge['PEER_REPLY']['line'] < marker['line'] < edge['REPLY_QUEUED']['line'], 'marker order')
        edge['marker'] = marker
    control['posthook'] = log.one(control['prefix'] + '_POSTHOOK_NO_FORMAT', peer_dir=1, peer_index=0,
                                   format_mask='0x3fe', selected=0, DMM_allocations=0, notifications=0, cache_writes=0)
    fields_equal(control['COMMIT'], marker_readback=1, posthook_no_format=1, prior_data_edge_preserved=1)
    audio['callback'] = log.one(audio['prefix'] + '_CALLBACK_SKIPPED', peer_type=3, peer_dir=1, peer_index=0,
                                callback_selected=0, marker_writes=0, DMM_allocations=0, notifications=0,
                                cache_writes=0, PCM_consumed=0, B0_commands=0, AVIO_jobs=0, source7_events=0)
    fields_equal(audio['COMMIT'], no_format_checked=1, predecessor_preserved=1)
    verify_format(log, first, identity, True)
    verify_format(log, fourth, identity, False)
    fourth['command'] = log.one(fourth['prefix'] + '_COMMAND_REQUEST', pid=identity[0], tid=identity[1],
                                 bytes=36, source='0x905a0048', destination='0x905a0048')
    require(raw_bytes(fourth['command'], 36) == bytes.fromhex(
        '0000000000000000022008f01c0001000100000000000000010000008007000038040000'), 'full synchronous f008 command')
    fourth['prepared'] = log.one(fourth['prefix'] + '_COMMAND_PREPARED', frame=2002, command='f008', context=1,
                                  payload_bytes=20, copy_readback_equal=1, ordinal=0, command_state=0,
                                  known_bytes=20, old_ordinal1_preserved=1, original_CP_command_list_verified=0)
    fourth['returned'] = log.one(fourth['prefix'] + '_COMMAND_RETURNED', context=3, type_table_entry=2,
                                  synchronous_execute=1, local_commands_inflight=0, local_commands_returned=1,
                                  old_command_owner_preserved=1, original_CP_command_list_verified=0)
    require(fourth['PEER_REPLY']['line'] < fourth['command']['line'] < fourth['prepared']['line'] <
            fourth['format_written']['line'] < fourth['retired']['line'] < fourth['returned']['line'] <
            fourth['REPLY_QUEUED']['line'], 'synchronous command order')
    fields_equal(fourth['COMMIT'], prior_edges_NoMem_AB_failure_S0_preserved=1)
    fifth['source_posthook'] = log.one(fifth['prefix'] + '_SOURCE_POSTHOOK',
        raw_ce08a_ce09a_type8_skips_marker=1, raw_cec90_cecf6_dir2_returns=1,
        source_slot=9, marker_writes=0, original_CP_RAM_read=0)
    fifth['posthook'] = log.one(fifth['prefix'] + '_POSTHOOK_NO_FORMAT', raw='0x10c7e8', lookup_raw='0x5f8628',
        peer_ordinal=14, selected_ordinals='1,2,3', selected=0, registry_objects=16,
        owned_type=8, owned_dir=1, owned_index=0, owned_sid='0x905a0048', peer_state=0,
        owned_table_readback=1, OtherPIN_raw='0x10c860', return_raw='0x10c866',
        DMM_allocations=0, notifications=0, cache_writes=0, marker_writes=0, clock_writes=0, MMIO_writes=0)
    fields_equal(fifth['COMMIT'], source_slot=9, peer_ordinal=14, posthook_selected=0,
                 format_work=0, marker_writes=0, prior_four_edges_NoMem_AB_failure_S0_preserved=1)
    require(fifth['PEER_REPLY']['line'] < fifth['source_posthook']['line'] < fifth['posthook']['line'] <
            fifth['REPLY_QUEUED']['line'], 'fifth posthook before AP publication')
    for edge in (control, audio, fifth):
        for suffix in ('DMM_REQUEST', 'DMM_REPLY', 'REFERENCE_READBACK', 'FORMAT_WRITTEN', 'FORMAT_NOTIFY',
                       'FORMAT_CONSUMED', 'BUFFER_RETIRED', 'COMMAND_REQUEST', 'COMMAND_PREPARED', 'COMMAND_RETURNED'):
            require(not log.rows(edge['prefix'] + '_' + suffix), (edge['prefix'], 'unexpected format work', suffix))
        for row in log.records:
            if edge['REQUEST']['line'] < row['line'] < edge['REPLY_FREE']['line']:
                require(not re.search(r'_(DMM_REQUEST|DMM_REPLY|FORMAT_CONSUMED|FORMAT_WRITTEN|FORMAT_NOTIFY)$', row['tag']),
                        (edge['prefix'], 'foreign format/DMM work inside no-format transaction', row['tag']))
    require(not log.rows(fifth['prefix'] + '_PEER_MARKER_WRITTEN'), 'fifth edge unexpectedly writes a marker')
    require(all(not log.rows(tag) for tag in FORWARD_TAGS), 'sixth-only forwarding consumer ran')
    require(not any(row['tag'].startswith('FULL_VEF_PINMEM_INPUT_CONNECT') for row in log.records),
            'sixth endpoint emitted runtime records')
    for edge, count in zip(edges, (7, 2, 2, 9, 2)):
        verify_internal_frees(log, edge, identity, count)
    resources = {}
    for edge, count in zip(edges, (1, 2, 2, 2, 3)):
        row = log.one(edge['prefix'] + '_RESOURCES_RESERVED', tid=identity[1], accepted=1,
                       allocations=count, releases=count, control_live=0, control_faults=0,
                       dmm_domain=2, foreign_speech_kept=1, dmm_lifecycle_changed=0)
        require(row['line'] < edge['REQUEST']['line'], (edge['prefix'], 'resources after admitted request'))
        resources[edge['prefix']] = row
    early = {edge['prefix']: verify_early_refusal(log, edge, first['REQUEST']['line']) for edge in (fourth, fifth)}
    return edges, identity, resources, early


def verify_path_producer(log, first_line):
    for suffix in ('FAULT', 'CLEANUP_REPLY_FREE', 'UNSUPPORTED'):
        require(not log.rows('FULL_VEF_PATH_' + suffix), ('SetPath unexpected record', suffix))
    applied = log.one('FULL_VEF_PATH_APPLIED', generation=1, inner_generation=1, requested_path=1,
        current_path=1, phase=2, state=2, object='PathProcessNoMem', property=2, input_selection='0x38',
        stage0_done=1, stage1_done=1, cache='ffffffff,ffffffff,ffffffff,ffffffff', extra=0, context=0,
        work=0, execution_status=0, outer_status='0x5a0000', applications=1,
        runtime_status22=1, runtime_status22_known=1, runtime_status22_writer_generation=1, runtime_status22_writes=1,
        inner_request='0220010014000100010001000000000000000000', inner_completion='022001100c00010000000000')
    commit = log.one('FULL_VEF_PATH_COMMIT', generation=1, current_path=1, phase=2, state=2,
                     request_free_rc=0, retained_request=0, queued=1, clean_completion=1)
    released = log.one('FULL_VEF_PATH_REPLY_FREE', generation=1, kind='queued-reply', rc=0,
                       retained=0, faults=0, ap_consumed=1)
    require(applied['line'] < commit['line'] < released['line'] < first_line, 'SetPath producer order')
    f11 = [row for row in log.records if any(row['fields'].get(key, '').lower() in ('0xf11', '0x0f11', '0f11')
                                           for key in ('opcode', 'command'))]
    require(not f11, '0f11 writer/event unexpectedly observed')
    return {'applied': applied, 'commit': commit, 'AP_reply_free': released,
            'runtime_status22_known': True, 'runtime_status22': 1, 'writer_generation': 1, 'writes': 1,
            'writer': 'same-run SetPath generation1 completion', 'observed_0f11_events': f11,
            'sixth_endpoint_writer_executed': False}


def verify_remaining(log, fifth, tid):
    expected = (
        (0, 2, 2, 0x905a0048, 0, 1, 0, 0x90590818),
        (8, 2, 0, 0x905a0048, 8, 1, 0, 0x90590818),
        (0, 2, 1, 0x90590818, 0, 1, 4, 0x91670464),
        (0, 2, 2, 0x90590818, 0, 1, 0, 0x9058003f),
        (6, 2, 0, 0x90590818, 6, 1, 0, 0x928d0783),
        (4, 2, 0, 0x90590818, 4, 1, 0, 0x909a015a),
        (1, 3, 0, 0x90590818, 1, 3, 0, 0x9080003b),
        (5, 2, 0, 0x9058003f, 5, 1, 0, 0x909a015a),
    )
    remaining = [row for row in log.rows('PIN_CONTROL_REQUEST') if row['line'] > fifth['REPLY_FREE']['line']]
    require(len(remaining) == len(expected), ('remaining refused connection count', len(remaining)))
    for index, (row, pins) in enumerate(zip(remaining, expected)):
        request_bytes(row, pins[:4], pins[4:])
        fields_equal(row, tid=tid)
        next_line = next_pin_send(log, row)
        refuse = [record for record in log.records if row['line'] < record['line'] < next_line
                  and record['tag'].endswith('_UNSUPPORTED')]
        require(refuse, ('remaining request not explicitly refused before next original thread send', row['line']))
        row['refusal'] = refuse[0]
    pending = [row for row in log.rows('NATIVE_CP_BACKGROUND_UNHANDLED') if row['fields'].get('opcode') == '0x302c']
    require(pending, '302c pending evidence missing')
    return remaining, pending


def verify_sd(run, manifest, log, pid, after_line):
    sd = json.loads((run / 'SD/export.json').read_text())
    gtk = json.loads((run / 'gtk-input-proof.json').read_text())
    require(gtk['automation_completed'] is True and gtk['shooting_screen_created'] is True,
            'GTK automation incomplete')
    require(gtk['natural_shutter']['input_submission_event_verified'] is True, 'natural shutter input evidence missing')
    require(gtk['full_camera_capture_implemented'] is False, 'unexpected capture claim in automation')
    card = Path(sd['host_directory'])
    require(card.parent == BASE / 'directory-sd-tests' and card.resolve().parent == (BASE / 'directory-sd-tests').resolve()
            and card.is_dir() and not card.is_symlink(), 'unexpected or symlinked directory SD')
    require(manifest['directory_sd_profile'] == 'directory-vvfat-256gb-v1', 'directory SD profile mismatch')
    stages = []
    for number, line in enumerate(log.lines, 1):
        if 'SD_FSYS_FLUSH_STAGE stage=' in line:
            stages.append({'line': number, 'raw': line.strip(), 'fields': dict(re.findall(r'(\w+)=([^\s]+)', line))})
    require(len(stages) == 8, ('expected two four-stage original flushes', len(stages)))
    exports = (gtk['sd_export'], sd)
    require(exports[0]['sequence'] != exports[1]['sequence'], 'two flushes reused one sequence')
    for export in exports:
        require(export['ok'] is True and export['bytes'] == 256000000000 and export['host_directory'] == str(card)
                and export['host_directory_verified'] is True and export['original_mount_verified'] is True,
                'same-run directory SD export identity/commit failed')
        require(export['original_capture_verified'] is False, 'metadata export claims capture')
        require(export['guest_block_sync_confirmed'] is True, 'guest block sync not confirmed')
        q, lifecycle, status = export['quiesce'], export['flush_lifecycle'], export['directory_commit_status']
        require(q['owner_stopped'] is True and q['original_Fsys_FlushVolume_rc'] == 0 and q['drive'] == 65
                and q['pid'] == int(pid) and q['sequence'] == export['sequence'], 'original flush/STOP identity mismatch')
        require(lifecycle['ok'] is True and lifecycle['resumed'] is True and lifecycle['status'] == 'resumed'
                and lifecycle['pid'] == int(pid) and lifecycle['sequence'] == export['sequence'], 'flush owner did not resume')
        require(status['available'] is True and status['pending'] is False and status['closed_pending'] is False,
                'directory commit is not clean')
        batch = [row for row in stages if row['fields']['seq'] == str(export['sequence'])]
        require([row['fields']['stage'] for row in batch] == ['accepted', 'before', 'after', 'reply'], 'original flush stage order')
        require(after_line < batch[0]['line'], 'SD export predates fifth-edge AP consumption')
        tids = {row['fields']['tid'] for row in batch}
        require(len(tids) == 1 and int(next(iter(tids))) > 0, 'original Fsys flush thread changed during call')
        for row in batch:
            fields_equal(row, pid=pid, drive=65, errno=0)
        fields_equal(batch[0], admitted=1)
        fields_equal(batch[1], calling=1)
        fields_equal(batch[2], rc=0)
        fields_equal(batch[3], stored=1)
    require(stages[3]['line'] < stages[4]['line'], 'two flush batches overlap')
    tree = []
    for path in sorted(card.rglob('*')):
        require(not path.is_symlink(), ('symlink in directory SD', path))
        if path.is_file():
            data = path.read_bytes()
            tree.append({'path': str(path.relative_to(card)), 'bytes': len(data), 'sha256': sha(data)})
        else:
            require(path.is_dir(), ('non-ordinary file in directory SD', path))
    require(tree == sorted(sd['files'], key=lambda item: item['path']) ==
            sorted(gtk['sd_export']['files'], key=lambda item: item['path']), 'same-run exported/host tree digest mismatch')
    require({entry['path'] for entry in tree} == {'INPUT.BIN', 'private/database/database.bin', 'private/m4root/mediapro.xml'},
            'unexpected host file tree; this evaluator only accepts the metadata-only five-edge run')
    require(sd['file_count'] == len(tree) == 3, 'directory SD file count mismatch')
    require(not any(Path(entry['path']).suffix.lower() in ('.jpg', '.jpeg', '.mp4') for entry in tree), 'capture output requires separate evaluation')
    return card, {'export': sd, 'GTK_export': gtk['sd_export'], 'flush_stages': stages, 'host_tree_readback': tree,
                   'original_sd_export_verified_this_run_only': True, 'two_original_flushes': True,
                   'STOP_and_resume_verified': True, 'clean_commit': True, 'capture_verified': False}


def exited_processes(owner):
    require(isinstance(owner, int) and owner > 1 and owner != os.getpid(), 'invalid host control owner PID')
    require(not Path('/proc', str(owner)).exists(), ('run is still active: owner exists', owner))
    inspected = 0
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            group = os.getpgid(int(path.name))
            require(group != owner, ('run process group still exists', path.name))
            try:
                executable = os.readlink(path / 'exe')
            except PermissionError:
                executable = ''
            except FileNotFoundError:
                executable = ''
            cmdline = (path / 'cmdline').read_bytes().split(b'\0')
            names = [Path(executable).name] + [os.fsdecode(arg).rsplit('/', 1)[-1] for arg in cmdline]
            require(not any(name.startswith('qemu-system-') for name in names), ('QEMU still active', path.name))
            inspected += 1
        except (ProcessLookupError, FileNotFoundError):
            continue
    require(not Path('/proc', str(owner)).exists(), 'owner appeared during exit check')
    return {'owner_pid': owner, 'owner_exited': True, 'owner_process_group_exited': True,
            'group_check': 'os.getpgid for live /proc processes', 'QEMU_absent': True,
            'processes_inspected': inspected, 'evaluator_signals_sent': False}


def verify_locks(card):
    paths = (BASE / '.menu-probe.lock', card.parent / ('.' + card.name + '.lock'))
    with ExitStack() as stack:
        for path in paths:
            require(path.is_file() and not path.is_symlink(), ('existing run lock missing/invalid', path))
            stream = stack.enter_context(path.open('rb'))
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return [str(path.relative_to(BASE)) for path in paths]


def evaluate(run):
    manifest = json.loads((run / 'runtime-manifest.json').read_text())
    # This check precedes all lock attempts; a partial/live run can never pass.
    cleanup = exited_processes(manifest['host_control_owner_pid'])
    build = verify_build(run, manifest)
    log = Log((run / 'console.log').read_bytes())
    edges, identity, resources, early = verify_graph(log)
    path = verify_path_producer(log, edges[0]['REQUEST']['line'])
    remaining, pending = verify_remaining(log, edges[-1], identity[1])
    card, sd = verify_sd(run, manifest, log, identity[0], edges[-1]['REPLY_FREE']['line'])
    cleanup.update(exited_processes(manifest['host_control_owner_pid']))
    cleanup['locks_exclusive_acquired_and_released'] = verify_locks(card)
    return {'scope': 'five explicit virtual graph edges, two mapped control-format consumptions, original AP replies and this-run SD; not image capture',
            'run': run.name, 'console_sha256': sha(log.raw), 'build': build, 'edges': edges,
            'resources': resources, 'early_fourth_and_fifth_refusals': early, 'SetPath_status22_producer': path,
            'five_edges_native_verified': True, 'infrabb_vef_control_connection_native_verified': True,
            'original_AP_pid': int(identity[0]), 'original_AP_tid': int(identity[1]),
            'five_unique_AP_replies_consumed': True, 'two_mapped_control_formats_consumed': True,
            'third_edge_no_PCM_or_format_verified': True, 'fifth_owned_ordinal14_not_selected': True,
            'fifth_zero_DMM_format_marker_MMIO_clock_effects_verified': True, 'prior_four_histories_preserved': True,
            'shared_forward_interfaces': {'consumer_log_events': [], 'sixth_endpoint_linked': False,
                                          'zero_forwarding_basis': 'sixth consumer omitted from frozen link/wiring; no forwarded-format consumer records; fifth before/after snapshot preserved',
                                          'expected_disabled_counter_values': {'imaging_forwarded_formats': 0, 'BB_forwarded_vef_formats': 0, 'BB_forwarded_bb_formats': 0},
                                          'direct_runtime_counter_readback_logged': False},
            'remaining_8_connections_refused': remaining, '302c_unhandled': pending, '302c_completed': False,
            'SD': sd, 'cleanup': cleanup, 'original_CP_executed': False, 'original_CP_page_tables_verified': False,
            'original_RTOS_scheduler_verified': False, 'original_CP_command_list_verified': False,
            'PCM_verified': False, 'hardware_verified': False, 'frames_verified': False,
            'CMOS_verified': False, 'JPEG_verified': False, 'MP4_verified': False, 'capture_verified': False}


def self_test():
    """Offline parser/wire negative checks; never inspect /proc or acquire a lock."""
    import tempfile
    from unittest.mock import patch
    checks = 0
    def rejects(callback):
        nonlocal checks
        try:
            callback()
        except (EvidenceError, FileNotFoundError, KeyError, ValueError):
            checks += 1
        else:
            raise AssertionError('invalid or incomplete evidence was accepted')
    source, sink = SPECS[4][3:]
    caller = 0x81cf61e9
    data = frame_bytes(64, 1, 2, source + sink, caller, b'\xfe\xed\xba\xbe')
    def row_for(data, length=64):
        return Log(('OBS REQUEST pid=258 tid=381 source=' + hex(caller) + ' destination=' + hex(source[3]) +
                    ' bytes=' + str(length) + ' raw=' + bytes(data).hex()).encode()).one('REQUEST')
    require(request_bytes(row_for(data), source, sink) == (data, caller), 'opaque word20 was incorrectly constrained')
    checks += 1
    bad = bytearray(data)
    bad[63] ^= 1
    rejects(lambda: request_bytes(row_for(bad), source, sink))
    rejects(lambda: request_bytes(row_for(data[:-1]), source, sink))
    bad = bytearray(data)
    struct.pack_into('<I', bad, 0, 0x9284074a)
    rejects(lambda: request_bytes(row_for(bad), source, sink))
    model = frame_bytes(64, 0x100, 1, source + sink)
    modelrow = row_for(model)
    modelrow['fields'].update(source=hex(source[3]), destination=hex(sink[3]))
    require(model_frame(modelrow, 64, 0x100, 1, source[3], sink[3], source + sink) == model, 'model frame check')
    checks += 1
    for offset in (0, 20, 30, 47, 63):
        bad = bytearray(model)
        bad[offset] ^= 1
        changed = row_for(bad)
        changed['fields'].update(source=hex(source[3]), destination=hex(sink[3]))
        rejects(lambda changed=changed: model_frame(changed, 64, 0x100, 1, source[3], sink[3], source + sink))
    duplicate = Log(b'OBS TEST rc=0\nOBS TEST rc=0\n')
    rejects(lambda: duplicate.one('TEST'))
    rejects(lambda: Log(b'').one('TEST'))
    ordered = Log(b'OBS PIN_CONTROL_REQUEST tid=381\nOBS PIN_QUERY tid=379\nOBS OTHER work=1\n'
                  b'OBS UNADMITTED requests=0\nOBS PIN_QUERY tid=381\n')
    require(next_pin_send(ordered, ordered.one('PIN_CONTROL_REQUEST')) == 5,
            'unrelated thread interleaving incorrectly bounded refusal')
    checks += 1
    require((fnv(ssyn_packet(0x06000000, 1)), fnv(ssyn_packet(0x02000000, 0)), fnv(PAYLOAD), fnv(CURRENT)) ==
            ('88d47938b00f682e', '472ea89986f7114b', '1a3c540ebc5023bd', '3c3a32bb6809f4cc'), 'typed data fingerprints')
    checks += 1
    with tempfile.TemporaryDirectory(prefix='five-edge-evaluator-') as directory:
        run = Path(directory)
        rejects(lambda: evaluate(run))
        (run / 'runtime-manifest.json').write_text(json.dumps({'host_control_owner_pid': os.getpid()}))
        with patch.object(fcntl, 'flock', side_effect=AssertionError('live/partial run must not touch locks')):
            rejects(lambda: evaluate(run))
        require(not (run / 'five-edges-native-evaluation.json').exists() and not (run / 'summary.json').exists(),
                'partial run wrote a success artifact')
        checks += 1
    print(json.dumps({'self_test_checks_passed': checks, 'VM_contacted': False, 'locks_attempted': False,
                      'native_evidence_generated': False}, indent=2))


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test()
        return 0
    require(len(sys.argv) == 2 and re.fullmatch(r'run-[A-Za-z0-9_-]+', sys.argv[1]), 'expected one run-BASENAME')
    run = BASE / 'menu-runs' / sys.argv[1]
    require(run.is_dir() and not run.is_symlink(), 'run directory missing or symlinked')
    proof = evaluate(run)
    out = run / 'five-edges-native-evaluation.json'
    out.write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'evaluation': str(out), 'five_AP_replies_consumed': True,
                      'two_mapped_control_formats_consumed': True, 'fifth_owned_ordinal14_not_selected': True,
                      'remaining_connections_refused': 8, 'same_run_SD_verified': True,
                      'cleanup_verified': True, 'capture_verified': False}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (EvidenceError, OSError, KeyError, ValueError, struct.error, tarfile.TarError) as error:
        print(json.dumps({'five_edges_native_verified': False, 'capture_verified': False,
                          'error': str(error), 'success_artifact_written': False}, indent=2), file=sys.stderr)
        sys.exit(1)
