#!/usr/bin/env python3
"""Read-only verifier for a completed six-edge run (no VM control).

Run: python3 scratch/evaluate-six-edges-native.py run-BASENAME | --self-test
Requires a separately produced scratch/six-edges-abi.json with observer_sha256,
source_archive_sha256, source_count and successful original-libc ABI returncode.
Only complete evidence creates six-edges-native-evaluation.json, exclusively.
"""
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile

BASE = Path(__file__).resolve().parents[1]
OBSERVER_SHA = '7ed5983503c6cfe1366b4c83a7869208c68465778859bf24ed9a121bcb2542dd'
SOURCE_ARCHIVE_SHA = 'bbf9b5349d503f041c0a5c0e6e53b9aa69d6b9a822b99ed0e7586aae5474e175'
SOURCE_COUNT = 291
HELPER_SHA = 'e8a27645a1f0b65f20db6fce4094c547e9856153ea00c61afcec3f5aa1fc0395'
IMAGE_HELPER_SHA = 'e5e4b149ce671edacd9d41efebd9b0eef33ba7eedc0dafef7bda85f9c7484afe'


def load_helper(path, digest):
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError('pure helper source changed: ' + str(path))
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    old = load_helper(BASE / 'scratch/evaluate-five-edges-native.py', HELPER_SHA)
    image = load_helper(BASE / 'initramfs_identity.py', IMAGE_HELPER_SHA)
except (OSError, ValueError, ImportError) as error:
    print(json.dumps({'six_edges_native_verified': False, 'capture_verified': False,
                      'error': str(error), 'success_artifact_written': False}), file=sys.stderr)
    raise SystemExit(1)
require, fields_equal, sha, fnv = old.require, old.fields_equal, old.sha, old.fnv
Log, raw_bytes, frame_bytes, model_frame = old.Log, old.raw_bytes, old.frame_bytes, old.model_frame
SIXTH = ('FULL_VEF_PINMEM_INPUT_CONNECT', 'vef_pinmem_input_connection',
         'virtual-vef-out2-pinmem-in0-forward-format-v1', (0, 2, 2, 0x905a0048), (0, 1, 0, 0x90590818))
SPECS = old.SPECS + (SIXTH,)
PAYLOAD = bytes.fromhex('01010300000000008007000038040000')
CURRENT = bytes.fromhex('0100000000000000010103008007000038040000')
OPS = (0x20, 0x21, 0x23, 0x24, 0x25, 0x24, 0x25, 0x24, 0x23)
HOPS = ((SIXTH[4], SIXTH[3]),
        ((0, 1, 1, 0x905a0048), old.SPECS[3][3]),
        (old.SPECS[0][4], old.SPECS[0][3]))


def verify_build(run, manifest):
    abi_path = BASE / 'scratch/six-edges-abi.json'
    abi = json.loads(abi_path.read_text())
    require((abi['returncode'], abi['observer_sha256'], abi['source_archive_sha256'], abi['source_count']) ==
            (0, OBSERVER_SHA, SOURCE_ARCHIVE_SHA, SOURCE_COUNT), 'sixth original-libc ABI identity/check differs')
    require((abi['host_tests_passed'], abi['host_subtests_passed'], abi['sixth_host_scenarios']) == (1364, 139, 253)
            and 'PASS: constructor thread and application-init wrapper preserved behavior' in abi['stdout'],
            'sixth ABI load/regression reference differs')
    observer = OBSERVER_SHA
    inputs_raw = (run / 'observer-build-inputs.json').read_bytes()
    inputs = json.loads(inputs_raw)
    require(inputs['observer_sha256'] == observer and manifest['compiled_observer'] == inputs,
            'run observer/build-inputs differ from independent ABI pin')
    require(manifest['selected_observer_matches_build'] is True, 'selected observer differs')
    files, selected, sources = manifest['files'], manifest['selected_initramfs_verified_files'], inputs['sources']
    require(len(sources) == abi['source_count'] and len(sources) >= old.INITIAL_SOURCE_COUNT,
            'run frozen source count differs from ABI')
    archive_path = run / 'observer-build-sources.tar.gz'
    require(sha(archive_path.read_bytes()) == inputs['source_archive_sha256'],
            'run source archive differs from its same-run build receipt')
    regression_path = BASE / 'scratch/six-edges-host-regression.json'
    regression_raw = regression_path.read_bytes()
    regression = json.loads(regression_raw)
    require(sha(regression_raw) == abi['host_regression_sha256'] and regression['returncode'] == 0
            and not regression['production_sources_changed'], 'ABI-bound tested source baseline differs')
    tested_sources = regression['production_sources_before']
    require(set(sources) == set(tested_sources), 'run and tested source input sets differ')
    require(all(entry['sha256'] == tested_sources[name] for name, entry in sources.items()),
            'same-run source bytes differ from ABI-bound tested inputs')
    require(files[str(BASE / 'observer-build-inputs.json')] == sha(inputs_raw), 'build input index digest differs')
    require(files[str(BASE / 'menu-observe.so')] == selected['simulation/menu-observe.so'] == observer and
            sha((BASE / 'menu-observe.so').read_bytes()) == observer, 'observer actual readback differs')
    frozen = {}
    with tarfile.open(archive_path) as archive:
        members = [m for m in archive.getmembers() if not m.isdir()]
        require(all(m.isfile() for m in members) and len({m.name for m in members}) == len(members),
                'nonregular/duplicate archived inputs')
        require(json.load(archive.extractfile('source-inputs.json')) == sources, 'archived source index differs')
        paths = [entry['archive_path'] for entry in sources.values()]
        require(len(set(paths)) == len(paths) and {m.name for m in members} == set(paths) | {'source-inputs.json'},
                'source archive file set differs')
        for name, entry in sources.items():
            path = PurePosixPath(entry['archive_path'])
            require(not path.is_absolute() and '..' not in path.parts and path.name == Path(name).name,
                    ('nonlocal archive path', name))
            data = archive.extractfile(str(path)).read()
            require(sha(data) == entry['sha256'], ('frozen source SHA differs', name))
            require(sha(Path(name).read_bytes()) == entry['sha256'], ('current source differs from frozen ABI', name))
            if name in files:
                require(files[name] == entry['sha256'], ('general source index differs', name))
            frozen[str(path)] = data
    def source(name):
        found = [(p, b.decode()) for p, b in frozen.items() if p.endswith('/' + name)]
        require(len(found) == 1, ('missing/ambiguous source', name))
        return found[0]
    provenance = []
    def contains(name, *tokens):
        path, text = source(name)
        for token in tokens:
            require(token in text, ('frozen implementation contract missing', name, token))
            provenance.append({'source': path, 'sha256': sha(frozen[path]), 'line': text[:text.index(token)].count('\n') + 1,
                               'checked_source': token})
        return text
    build_source = contains('build-observers.sh', *[name for name in ('imaging-pin-connection', 'imaging-control-connection',
        'imaging-adf-connection', 'infrabb-vef-connection', 'infrabb-vef-control-connection', 'vef-pinmem-input-connection')])
    require('vef-pinmem-control-connection' not in build_source, 'later seventh endpoint unexpectedly linked')
    observer_source = contains('menu-observe.c', 'MENU_VEF_PINMEM_INPUT_CONNECT', 'FULL_VEF_PINMEM_INPUT_CONNECT_',
        'full_vef_pinmem_input_connection_release', 'vef_pinmem_input_connection_reserve_resources')
    dispatch = observer_source[observer_source.index('int osal_snd_msg('):]
    require(dispatch.index('full_vef_pinmem_input_connection_dispatch(') < dispatch.index('full_vef_resource_send_enter('),
            'sixth dispatch must precede legacy VEF resource gate')
    require(not re.search(r'full_vef_pinmem_control_connection_dispatch|MENU_VEF_PINMEM_CONTROL_CONNECT', observer_source),
            'later seventh edge unexpectedly wired')
    contains('vef-path-device.c', 'runtime_status22_writer_generation', 'runtime_status22_writes')
    contains('vef-pinmem-input-connection.c', 'state.record=(struct pin_yc_parameters){3,1920,1080,1,1}',
        'if(!state.initialized)', 'state.record_index=0;state.record_bound=1', 'path->runtime_status22_known==1',
        'path->runtime_status22_writer_generation==1', 'cold_pin(&p->vef.pins[9],S)',
        'pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,1)',
        'pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,2)',
        'pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,3)',
        'if(src!=dst || src>>28!=8 || !(src&0xfffffff) || !canonical(io,request,expected_request,64,src))',
        'if(!dependencies(&before))return unadmitted', 'state.requests=1',
        'pin_registry_connect_step(full_vef_registry(),full_pinmem_registry(),S,P,4)',
        'return memcmp(&after,&expected,sizeof after)?-1:0;',
        'expected.pool.allocations++;expected.pool.releases++;expected.pool.payload_writes++;expected.pool.consumer_reads+=3;',
        'expected.pool.shares++;expected.pool.creator_releases++;expected.pool.consumer_opens+=3;expected.pool.consumer_closes+=3;expected.pool.consumer_releases++;',
        'memcmp(p,expected,n)', 'if(rc || (hop==2 && changed!=1) || live_caches(hop))goto failed;',
        'preserved(&before,0,1)', 'state.clean_completion=!state.faults && state.request_freed',
        'transaction-incomplete-partial-mapped-buffer-and-live-caches-preserved')
    for name in ('infrabb-vef-connection.c', 'imaging-pin-connection.c'):
        contains(name, 'pin_control_read_consumer(handle,0,packet,sizeof packet)', 'refs.owners!=1 || refs.opens!=1')
    libraries, omissions = {}, []
    require(manifest['original_libraries_unchanged'] is True, 'original libraries changed')
    for path, digest in selected.items():
        require(sha((BASE / 'menu-root' / path).read_bytes()) == digest, ('selected actual file differs', path))
        if path.startswith('usr/lib/'):
            libraries[path] = digest
            if str(BASE / 'menu-root' / path) not in files:
                omissions.append(path)
        if str(BASE / 'menu-root' / path) in files:
            require(files[str(BASE / 'menu-root' / path)] == digest, ('additional general file index differs', path))
    require(len(libraries) >= 10, 'original selected libraries incomplete')
    archive_image = Path(manifest['probe_args']['initramfs_file'] or BASE / 'menu-initramfs.cpio')
    require(sha(archive_image.read_bytes()) == files[str(archive_image)], 'selected initramfs actual digest differs')
    require(image.verify_image(archive_image, selected) == selected, 'actual initramfs readback differs')
    backup = manifest['backup_transport']
    require(backup['binary_sha256'] == files[backup['binary']] == old.QEMU_SHA and
            sha(Path(backup['binary']).read_bytes()) == old.QEMU_SHA, 'public a0d QEMU identity differs')
    for _, key, profile, _, _ in SPECS:
        require(manifest[key + '_profile'] == backup[key + '_profile'] == profile, ('six-edge profile differs', key))
    return {'ABI_pin': {'path': str(abi_path.relative_to(BASE)), 'sha256': sha(abi_path.read_bytes()), 'receipt': abi},
            'observer_sha256': observer, 'source_archive_sha256': inputs['source_archive_sha256'],
            'run_gzip_archive_differs_from_initial_ABI': inputs['source_archive_sha256'] != abi['source_archive_sha256'],
            'all_run_source_bytes_equal_ABI_bound_tested_inputs': True,
            'frozen_source_count': len(sources), 'all_archived_and_current_sources_verified': True,
            'all_selected_actual_files_and_initramfs_readback_verified': True, 'original_library_digests': libraries,
            'libraries_missing_only_from_general_file_index': omissions, 'public_qemu_sha256': old.QEMU_SHA,
            'source_provenance_refs': provenance, 'sixth_dispatch_before_legacy_gate': True,
            'record_scope': 'once-bound virtual public PinMem record0; no live CP RAM read',
            'helper_sources': {'evaluate-five-edges-native.py': HELPER_SHA, 'initramfs_identity.py': IMAGE_HELPER_SHA}}


def verify_sixth_edge(log, previous_free, identity):
    prefix, _, profile, source, sink = SIXTH
    for suffix in ('FAULT', 'CLEANUP_FAULT', 'RESOURCES_FAULT', 'RESOURCES_REFUSED', 'FORMAT_REFUSED', 'UNSUPPORTED'):
        require(not log.rows(prefix + '_' + suffix), ('sixth transaction failure', suffix))
    tags = ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED', 'COMMIT', 'REPLY_FREE')
    edge = {tag: log.one(prefix + '_' + tag) for tag in tags}
    original, caller = old.request_bytes(edge['REQUEST'], source, sink)
    for tag in ('REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED', 'REPLY_FREE'):
        fields_equal(edge[tag], pid=identity[0], tid=identity[1])
    model_frame(edge['PEER_REQUEST'], 64, 0x100, 1, source[3], sink[3], source + sink)
    model_frame(edge['PEER_REPLY'], 72, 0x8100, 1, sink[3], source[3], source + sink + (0, 0))
    model_frame(edge['REPLY_QUEUED'], 56, 0x8001, 2, source[3], caller, source + (0, 0))
    fields_equal(edge['REPLY_FREE'], bytes=56, rc=0, faults=0, ap_consumed=1,
                 destination=hex(caller), expected=hex(caller))
    require(edge['REPLY_QUEUED']['fields']['pointer'] == edge['REPLY_FREE']['fields']['pointer'] and
            edge['REPLY_QUEUED']['fields']['pointer'] != edge['REQUEST']['fields']['pointer'], 'sixth independent AP reply/free')
    pointers = [edge[tag]['fields']['pointer'] for tag in tags[:3]]
    require(len(set(pointers)) == 3 and all(int(p, 0) for p in pointers), 'sixth independent live control allocations')
    fields_equal(edge['COMMIT'], connections=1, unique_reply=1, source_state=0, peer_state=0, source_pending=0)
    order = [edge[tag]['line'] for tag in tags]
    require(order == sorted(set(order)) and previous_free < order[0], 'sixth transaction/AP reply ordering')
    profiles = [r for r in log.rows(prefix + '_PROFILE') if r['fields'].get('pid') == identity[0]]
    require(len(profiles) == 1 and profiles[0]['line'] < order[0], 'sixth actual AP profile missing/late')
    edge['profile'] = fields_equal(profiles[0], requested=profile, enabled=1, first_missing='none',
                                   owner_pid=identity[0], initialized=1, before_any_input=1)
    edge.update(prefix=prefix, source_pin=source, sink_pin=sink, caller=caller,
                opaque_original_word20=original[20:24].hex(),
                request_log_policy='actual endpoint REQUEST raw; top-level dispatch precedes generic PIN_CONTROL_REQUEST logger')
    return edge


def verify_graph(log):
    """First five contracts retained explicitly; sixth forwarding is now required."""
    require(b'Entering exception monitor.' not in log.raw, 'guest entered exception monitor')
    edges, identity, last = [], None, 0
    for spec in old.SPECS:
        edge, identity = old.verify_edge(log, spec, last, identity)
        edges.append(edge)
        last = edge['REPLY_FREE']['line']
    edges.append(verify_sixth_edge(log, last, identity))
    first, control, audio, fourth, fifth, sixth = edges
    for edge, address in ((first, '0x01acad10'), (control, '0x01acad0f')):
        row = log.one(edge['prefix'] + '_PEER_MARKER_WRITTEN', source_CP_VA=address,
                      old_value_known=0, value=1, readback=1, writes=1)
        require(edge['PEER_REPLY']['line'] < row['line'] < edge['REPLY_QUEUED']['line'], 'marker order')
        edge['marker'] = row
    control['posthook'] = log.one(control['prefix'] + '_POSTHOOK_NO_FORMAT', peer_dir=1, peer_index=0,
        format_mask='0x3fe', selected=0, DMM_allocations=0, notifications=0, cache_writes=0)
    fields_equal(control['COMMIT'], marker_readback=1, posthook_no_format=1, prior_data_edge_preserved=1)
    audio['callback'] = log.one(audio['prefix'] + '_CALLBACK_SKIPPED', peer_type=3, peer_dir=1, peer_index=0,
        callback_selected=0, marker_writes=0, DMM_allocations=0, notifications=0, cache_writes=0,
        PCM_consumed=0, B0_commands=0, AVIO_jobs=0, source7_events=0)
    fields_equal(audio['COMMIT'], no_format_checked=1, predecessor_preserved=1)
    old.verify_format(log, first, identity, True)
    old.verify_format(log, fourth, identity, False)
    fourth['command'] = log.one(fourth['prefix'] + '_COMMAND_REQUEST', pid=identity[0], tid=identity[1],
        bytes=36, source='0x905a0048', destination='0x905a0048')
    require(raw_bytes(fourth['command'], 36) == bytes.fromhex(
        '0000000000000000022008f01c0001000100000000000000010000008007000038040000'), 'full synchronous f008 command')
    fourth['prepared'] = log.one(fourth['prefix'] + '_COMMAND_PREPARED', frame=2002, command='f008', context=1,
        payload_bytes=20, copy_readback_equal=1, ordinal=0, command_state=0, known_bytes=20,
        old_ordinal1_preserved=1, original_CP_command_list_verified=0)
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
            require(not log.rows(edge['prefix'] + '_' + suffix), ('unexpected no-format work', edge['prefix'], suffix))
        require(not any(re.search(r'_(DMM_REQUEST|DMM_REPLY|FORMAT_CONSUMED|FORMAT_WRITTEN|FORMAT_NOTIFY)$', row['tag'])
            for row in log.records if edge['REQUEST']['line'] < row['line'] < edge['REPLY_FREE']['line']),
            ('foreign format/DMM work inside no-format transaction', edge['prefix']))
    require(not log.rows(fifth['prefix'] + '_PEER_MARKER_WRITTEN'), 'fifth unexpectedly writes marker')
    resources = {}
    for edge, frees, allocations in zip(edges, (7, 2, 2, 9, 2, 14), (1, 2, 2, 2, 3, 3)):
        old.verify_internal_frees(log, edge, identity, frees)
        row = log.one(edge['prefix'] + '_RESOURCES_RESERVED', tid=identity[1], accepted=1,
            allocations=allocations, releases=allocations, control_live=0, control_faults=0,
            dmm_domain=2, foreign_speech_kept=1, dmm_lifecycle_changed=0)
        require(row['line'] < edge['REQUEST']['line'], 'resource gate after request')
        resources[edge['prefix']] = row
    early = {edge['prefix']: old.verify_early_refusal(log, edge, first['REQUEST']['line'])
             for edge in (fourth, fifth)}
    refused = log.rows(SIXTH[0] + '_UNADMITTED')
    require(refused, 'sixth early boot refusal missing')
    for row in refused:
        fields_equal(row, requests=0, faults_unchanged=1, owner_not_reset=1)
        require(row['line'] < first['REQUEST']['line'], 'late sixth precondition refusal')
    early[SIXTH[0]] = {'unadmitted': refused, 'early_original_raw_logged': False,
        'basis': 'frozen dispatch checks full original key and canonical envelope before precondition refusal; top-level return skips generic sender logger'}
    verify_sixth(log, sixth, identity)
    return edges, identity, resources, early


def dmm_bytes(stage, handle, reply=False):
    opcode, length = OPS[stage - 1], 152 if stage <= 5 else 216
    token = 0 if stage <= 5 else 0x55
    data = bytearray(length)
    struct.pack_into('<H', data, 0, opcode | (0x8000 if reply else 0))
    struct.pack_into('<H', data, 6 if reply else 20, token)
    if reply:
        struct.pack_into('<I', data, 12, handle)
        if stage in (1, 2):
            struct.pack_into('<I', data, 16, 0x404)
        if opcode in (0x20, 0x24):
            struct.pack_into('<H', data, 8, 1)
            struct.pack_into('<Q', data, 24, 0x500000000)
            struct.pack_into('<I', data, 32, 512)
    else:
        struct.pack_into('<I', data, 4 if stage == 1 else 8, 0x404 if stage == 1 else handle)
        if stage == 2:
            struct.pack_into('<I', data, 4, 0x404)
        struct.pack_into('<I', data, 12, 0xffffffff if stage in (1, 6) else 0)
        struct.pack_into('<H', data, 22, 1 if stage == 1 else 2 if stage in (3, 9) else 0)
    return bytes(data)


def verify_sixth(log, edge, identity):
    prefix = SIXTH[0]
    one = lambda suffix, **fields: log.one(prefix + '_' + suffix, **fields)
    status = one('STATUS_READBACK', runtime_status22=1, known=1, writer_generation=1, writes=1,
        producer='SetPath-original-completion-raw109c3c-109cde', NoMem_state=2,
        distinct_old_ordinal1_status=0, not_forced=1)
    require(edge['REQUEST']['line'] < status['line'] < edge['PEER_REQUEST']['line'], 'status readback order')
    written = one('FORMAT_WRITTEN', pid=identity[0], tid=identity[1], physical='0x500000000', cp_virtual='0x80000000',
        bytes=80, record_index=0, raw_flags=3, code=1, component=1, width=1920, height=1080,
        source='public-PinMem-constructor-raw5d6b60-5d6bbe', header_word='0x01000000', key=0,
        payload=PAYLOAD.hex(), payload_fnv64=fnv(PAYLOAD), original_CP_RAM_read=0, original_CP_page_tables_verified=0)
    handle = int(written['fields']['handle'], 0)
    require(handle == 0x8800 + 0x400, 'sixth handle must be next generation after old/fourth retired handles')
    packet = bytearray(old.ssyn_packet(0x01000000, 0)); packet[64:] = PAYLOAD
    fields_equal(written, fnv64=fnv(packet))
    requests, replies = log.rows(prefix + '_DMM_REQUEST'), log.rows(prefix + '_DMM_REPLY')
    require(len(requests) == len(replies) == 9, 'exact nine DMM operations required')
    transaction_dmm = [r for r in log.records if edge['PEER_REPLY']['line'] < r['line'] < edge['REPLY_QUEUED']['line']
                       and r['tag'].endswith('_DMM_REQUEST')]
    require(transaction_dmm == requests, 'foreign or extra DMM operation inside sixth transaction')
    refs = log.rows(prefix + '_REFERENCE_READBACK')
    phases = ('allocated', 'shared', 'creator-released', 'vef-open', 'vef-closed', 'bb-open', 'bb-closed', 'imaging-open')
    values = ((1, 1, 1, 0, 0), (2, 1, 1, 1, 0), (1, 0, 0, 1, 0), (1, 1, 0, 1, 1),
              (1, 0, 0, 1, 0), (1, 1, 0, 1, 1), (1, 0, 0, 1, 0), (1, 1, 0, 1, 1))
    require(len(refs) == 9, 'reference readback history incomplete')
    for index, (row, phase, value) in enumerate(zip(refs, phases, values)):
        fields_equal(row, pid=identity[0], tid=identity[1], phase=phase, handle=hex(handle),
            current_consumer_sid='0' if index < 3 else hex(0x905a0048 if index < 5 else 0x9284074a if index < 7 else 0x90050004),
            **dict(zip(('owners', 'opens', 'creator', 'consumer', 'consumer_open'), value)))
    fields_equal(refs[-1], phase='retired', owners=0, opens=0, creator=0, consumer=0, consumer_open=0,
                 handle_lookup_refused=1, pool_live=0, exact_pool_deltas_verified=1)
    last = edge['PEER_REPLY']['line']
    for stage, (request, reply) in enumerate(zip(requests, replies), 1):
        sender = 0x9059000e if stage <= 3 else 0x905a0048 if stage <= 5 else 0x9284074a if stage <= 7 else 0x90050004
        for row, src, dst in ((request, sender, 0x61003c), (reply, 0x61003c, sender)):
            fields_equal(row, pid=identity[0], tid=identity[1], source=hex(src), destination=hex(dst),
                         transport_owner='virtual-local-caller', canonical_padding=1, original_CP_executed=0,
                         frames_verified=0, capture_verified=0)
            require(raw_bytes(row, 152 if stage <= 5 else 216) == dmm_bytes(stage, handle, row is reply),
                    ('sixth DMM complete canonical wire', stage, row['tag']))
        require(request['fields']['pointer'] == reply['fields']['pointer'] and
                request['fields']['pointer'] != edge['REQUEST']['fields']['pointer'], 'DMM response ownership/alias')
        require(last < request['line'] < reply['line'], ('DMM order', stage)); last = reply['line']
    notices = log.rows(prefix + '_FORMAT_NOTIFY')
    accepted, consumed = log.rows(prefix + '_FORMAT_NOTIFY_CONSUMED'), log.rows(prefix + '_FORMAT_CONSUMED')
    require(len(notices) == len(accepted) == len(consumed) == 3, 'three same-handle notifications/consumers required')
    authorities = []
    for hop, ((source, sink), notice, accept, consume) in enumerate(zip(HOPS, notices, accepted, consumed), 1):
        model_frame(notice, 80, 0x104, 1, source[3], sink[3], source + sink + (0x404, handle, 0, 0))
        fields_equal(notice, pid=identity[0], tid=identity[1], transport_owner='virtual-local-caller', canonical_padding=1)
        fields_equal(accept, hop=hop, source=hex(source[3]), destination=hex(sink[3]), handle=hex(handle),
                     offset=0, size='0x404', actual_notification_consumed=1, extra_share=0)
        fields_equal(consume, hop=hop, source=hex(source[3]), destination=hex(sink[3]), handle=hex(handle),
            mapped_read=1, payload_fnv64=fnv(PAYLOAD), changed=1 if hop == 2 else 0,
            live_authority_updated=1, old_ordinal1_preserved=1, frames_verified=0, capture_verified=0)
        authority = log.one(old.FORWARD_TAGS[hop] if hop < 3 else old.FORWARD_TAGS[0],
            pid=identity[0], tid=identity[1], handle=hex(handle), bytes=80, payload_bytes=16,
            mapped_backing_read=1, payload_fnv64=fnv(PAYLOAD))
        if hop < 3:
            fields_equal(authority, owners=1, opens=1, creator=0, consumer=1, consumer_open=1,
                changed=0 if hop == 1 else 1, current_raw=CURRENT.hex(),
                expected_raw=(old.PAYLOAD if hop == 1 else PAYLOAD).hex(), payload_raw=PAYLOAD.hex(),
                current_fnv64=fnv(CURRENT), command_fnv64=fnv(old.CURRENT), fourth_payload_fnv64=fnv(old.PAYLOAD),
                original_CP_RAM_read=0, original_CP_page_tables_verified=0)
        else:
            fields_equal(authority, unit='0x404', key=0, synchronization_object='0x21', cache='1,1,1920,1080,3',
                         consumed=2, forwarded_formats=1, original_cp_executed=0, original_CP_page_tables_verified=0)
        stage = 3 + 2 * (hop - 1)
        require(refs[stage - 1]['line'] < notice['line'] < accept['line'] < requests[stage]['line'] <
                replies[stage]['line'] < refs[stage]['line'] < authority['line'] < consume['line'] <
                requests[stage + 1]['line'] < replies[stage + 1]['line'] < refs[stage + 1]['line'],
                ('notification/read/close or final Free order', hop))
        authorities.append(authority)
    require(replies[0]['line'] < refs[0]['line'] < written['line'] < requests[1]['line'] <
            replies[1]['line'] < refs[1]['line'] < requests[2]['line'] < replies[2]['line'] < refs[2]['line'],
            'allocate/write/share/creator-release order')
    retired = one('BUFFER_RETIRED', DMM_requests=9, DMM_replies=9, notifications=3, mapped_reads=3,
        extra_share=0, consumer_Close25=2, final_Free23_option2_closes_once=1, owners=0, opens=0, live=0,
        old_ordinal1_preserved=1, capture_verified=0)
    require(refs[-1]['line'] < retired['line'] < edge['REPLY_QUEUED']['line'], 'buffer retired after publication')
    fields_equal(edge['COMMIT'], source_slot=9, peer_ordinal=0, DMM_requests=9, notifications=3, mapped_reads=3,
        VEF_BB_Imaging_live_caches_updated=1, buffer_freed=1, prior_five_histories_NoMem_AB_failure_S0_clocks_banks_preserved=1)
    edge.update(status_readback=status, format_written=written, DMM_requests=requests, DMM_replies=replies,
        references=refs, format_notices=notices, notices_consumed=accepted, format_consumed=consumed,
        live_authority_readbacks=authorities, retired=retired,
        packet_sha256=sha(packet), payload_sha256=sha(PAYLOAD), current_fnv64=fnv(CURRENT),
        exact_pool_delta_basis='frozen preserved() memcmp and retired readback; no standalone pool counter log')


def verify_remaining(log, sixth, tid):
    expected = ((8, 2, 0, 0x905a0048, 8, 1, 0, 0x90590818),
        (0, 2, 1, 0x90590818, 0, 1, 4, 0x91670464), (0, 2, 2, 0x90590818, 0, 1, 0, 0x9058003f),
        (6, 2, 0, 0x90590818, 6, 1, 0, 0x928d0783), (4, 2, 0, 0x90590818, 4, 1, 0, 0x909a015a),
        (1, 3, 0, 0x90590818, 1, 3, 0, 0x9080003b), (5, 2, 0, 0x9058003f, 5, 1, 0, 0x909a015a))
    rows = [r for r in log.rows('PIN_CONTROL_REQUEST') if r['line'] > sixth['REPLY_FREE']['line']]
    require(len(rows) == 7, ('remaining connection request count', len(rows)))
    for row, pins in zip(rows, expected):
        old.request_bytes(row, pins[:4], pins[4:]); fields_equal(row, tid=tid)
        refusals = [r for r in log.records if row['line'] < r['line'] < old.next_pin_send(log, row)
                    and r['tag'].endswith('_UNSUPPORTED')]
        require(refusals, ('remaining connection not explicitly refused', row['line']))
        row['refusal'] = refusals[0]
    pending = [r for r in log.rows('NATIVE_CP_BACKGROUND_UNHANDLED') if r['fields'].get('opcode') == '0x302c']
    require(pending, '302c unhandled evidence missing')
    return rows, pending


def verify_ee(run, log, pid, after_line):
    receipt = json.loads((run / 'ee-post-shutter.json').read_text())
    snapshot = Path(receipt['snapshot_dir'])
    require(receipt['ok'] is True and snapshot.parent.resolve() == run.resolve() and not snapshot.is_symlink(),
            'post-shutter snapshot not from this run')
    status_file = snapshot / 'ee_status.txt'
    require(status_file.is_file() and not status_file.is_symlink(), 'EE status readback file missing/symlinked')
    raw = status_file.read_bytes()
    readback = re.search(rb'READMEM /proc/' + str(pid).encode() + rb'/mem address=[0-9a-f]+ bytes=4\r?\n[0-9a-f]+: 00 00 00 00', raw)
    require(readback and readback[0].decode() in '\n'.join(log.lines[after_line:]) and
            re.search(rb'MENU_DIAG_COMMAND_DONE_[0-9a-f]+:0', raw), 'same-run post-sixth EE0 actual readback missing')
    return {'file': str((snapshot / 'ee_status.txt').relative_to(run)), 'sha256': sha(raw),
            'raw_readback': readback[0].decode(), 'EE_state': 0, 'atomic_snapshot': False}


def evaluate(run):
    manifest = json.loads((run / 'runtime-manifest.json').read_text())
    cleanup = old.exited_processes(manifest['host_control_owner_pid'])
    build = verify_build(run, manifest)
    log = Log((run / 'console.log').read_bytes())
    edges, identity, resources, early = verify_graph(log)
    producer = old.verify_path_producer(log, edges[0]['REQUEST']['line'])
    remaining, pending = verify_remaining(log, edges[-1], identity[1])
    card, sd = old.verify_sd(run, manifest, log, identity[0], edges[-1]['REPLY_FREE']['line'])
    ee = verify_ee(run, log, identity[0], edges[-1]['REPLY_FREE']['line'])
    cleanup.update(old.exited_processes(manifest['host_control_owner_pid']))
    cleanup['locks_exclusive_acquired_and_released'] = old.verify_locks(card)
    return {'scope': 'six explicit virtual graph edges and same-handle mapped control-format propagation; metadata-only SD',
        'run': run.name, 'console_sha256': sha(log.raw), 'build': build, 'edges': edges, 'resources': resources,
        'early_unadmitted_requests': early, 'SetPath_status22_producer': producer,
        'six_edges_native_verified': True, 'six_unique_AP_replies_consumed': True,
        'vef_pinmem_input_connection_native_verified': True, 'three_mapped_forwarded_format_reads_verified': True,
        'original_AP_pid': int(identity[0]), 'original_AP_tid': int(identity[1]),
        'remaining_7_connections_refused': remaining, '302c_unhandled': pending, '302c_completed': False,
        'SD': sd, 'EE': ee, 'cleanup': cleanup,
        **{key: False for key in ('original_CP_executed', 'original_CP_page_tables_verified', 'original_RTOS_scheduler_verified',
            'original_CP_command_list_verified', 'PCM_verified', 'hardware_verified', 'frames_verified', 'CMOS_verified',
            'JPEG_verified', 'MP4_verified', 'capture_verified')}}


def self_test():
    """Synthetic rejection tests only; no /proc, locks, VM, or native receipts."""
    import copy
    import tempfile
    from unittest.mock import patch
    checks = 0
    def rejects(callback):
        nonlocal checks
        try:
            callback()
        except (old.EvidenceError, OSError, KeyError, ValueError, struct.error):
            checks += 1
        else:
            raise AssertionError('corrupt/incomplete evidence accepted')
    # A full sixth-only fixture exercises semantic evidence checks independently of build/SD.
    records, handle, identity = [], 0x8c00, ('258', '381')
    edge = {'prefix': SIXTH[0]}
    def emit(tag, raw=None, **fields):
        row = {'line': len(records) + 1, 'tag': tag, 'raw': 'synthetic-self-test-only',
               'fields': {key: str(value) for key, value in fields.items()}}
        if raw is not None: row['fields'].update(raw=raw.hex(), bytes=str(len(raw)))
        records.append(row); return row
    def event(suffix, **fields): return emit(SIXTH[0] + '_' + suffix, **fields)
    def dmm(stage):
        sender = 0x9059000e if stage <= 3 else 0x905a0048 if stage <= 5 else 0x9284074a if stage <= 7 else 0x90050004
        for reply in (False, True):
            event('DMM_REPLY' if reply else 'DMM_REQUEST', raw=dmm_bytes(stage, handle, reply),
                pid=258, tid=381, source=hex(0x61003c if reply else sender), destination=hex(sender if reply else 0x61003c),
                pointer='0x1234', transport_owner='virtual-local-caller', canonical_padding=1,
                original_CP_executed=0, frames_verified=0, capture_verified=0)
    def refs(phase, values, sid='0'):
        return event('REFERENCE_READBACK', pid=258, tid=381, phase=phase, handle=hex(handle), current_consumer_sid=sid,
                     **dict(zip(('owners', 'opens', 'creator', 'consumer', 'consumer_open'), values)))
    edge['REQUEST'] = event('REQUEST', pointer='0x5678')
    event('STATUS_READBACK', runtime_status22=1, known=1, writer_generation=1, writes=1,
        producer='SetPath-original-completion-raw109c3c-109cde', NoMem_state=2, distinct_old_ordinal1_status=0, not_forced=1)
    edge['PEER_REQUEST'] = event('PEER_REQUEST'); edge['PEER_REPLY'] = event('PEER_REPLY')
    dmm(1); refs('allocated', (1, 1, 1, 0, 0))
    packet = bytearray(old.ssyn_packet(0x01000000, 0)); packet[64:] = PAYLOAD
    event('FORMAT_WRITTEN', pid=258, tid=381, handle=hex(handle), physical='0x500000000', cp_virtual='0x80000000',
        bytes=80, record_index=0, raw_flags=3, code=1, component=1, width=1920, height=1080,
        source='public-PinMem-constructor-raw5d6b60-5d6bbe', header_word='0x01000000', key=0,
        payload=PAYLOAD.hex(), payload_fnv64=fnv(PAYLOAD), fnv64=fnv(packet), original_CP_RAM_read=0, original_CP_page_tables_verified=0)
    dmm(2); refs('shared', (2, 1, 1, 1, 0)); dmm(3); refs('creator-released', (1, 0, 0, 1, 0))
    for hop, (source, sink) in enumerate(HOPS, 1):
        event('FORMAT_NOTIFY', raw=frame_bytes(80, 0x104, 1, source + sink + (0x404, handle, 0, 0)),
            pid=258, tid=381, source=hex(source[3]), destination=hex(sink[3]), transport_owner='virtual-local-caller', canonical_padding=1)
        common = dict(hop=hop, source=hex(source[3]), destination=hex(sink[3]), handle=hex(handle))
        event('FORMAT_NOTIFY_CONSUMED', **common, offset=0, size='0x404', actual_notification_consumed=1, extra_share=0)
        dmm(2 * hop + 2); refs(('vef-open', 'bb-open', 'imaging-open')[hop - 1], (1, 1, 0, 1, 1), hex(sink[3]))
        authority = dict(pid=258, tid=381, handle=hex(handle), bytes=80, payload_bytes=16,
                         mapped_backing_read=1, payload_fnv64=fnv(PAYLOAD), original_CP_page_tables_verified=0)
        if hop < 3:
            authority.update(owners=1, opens=1, creator=0, consumer=1, consumer_open=1, changed=int(hop == 2),
                current_raw=CURRENT.hex(), expected_raw=(old.PAYLOAD if hop == 1 else PAYLOAD).hex(), payload_raw=PAYLOAD.hex(),
                current_fnv64=fnv(CURRENT), command_fnv64=fnv(old.CURRENT), fourth_payload_fnv64=fnv(old.PAYLOAD), original_CP_RAM_read=0)
        else:
            authority.update(unit='0x404', key=0, synchronization_object='0x21', cache='1,1,1920,1080,3',
                             consumed=2, forwarded_formats=1, original_cp_executed=0)
        emit(old.FORWARD_TAGS[hop] if hop < 3 else old.FORWARD_TAGS[0], **authority)
        event('FORMAT_CONSUMED', **common, mapped_read=1, payload_fnv64=fnv(PAYLOAD), changed=int(hop == 2),
              live_authority_updated=1, old_ordinal1_preserved=1, frames_verified=0, capture_verified=0)
        dmm(2 * hop + 3)
        if hop < 3: refs('vef-closed' if hop == 1 else 'bb-closed', (1, 0, 0, 1, 0), hex(sink[3]))
    event('REFERENCE_READBACK', phase='retired', owners=0, opens=0, creator=0, consumer=0, consumer_open=0,
          handle_lookup_refused=1, pool_live=0, exact_pool_deltas_verified=1)
    event('BUFFER_RETIRED', DMM_requests=9, DMM_replies=9, notifications=3, mapped_reads=3, extra_share=0,
          consumer_Close25=2, final_Free23_option2_closes_once=1, owners=0, opens=0, live=0, old_ordinal1_preserved=1, capture_verified=0)
    edge['REPLY_QUEUED'] = event('REPLY_QUEUED')
    edge['COMMIT'] = event('COMMIT', source_slot=9, peer_ordinal=0, DMM_requests=9, notifications=3, mapped_reads=3,
        VEF_BB_Imaging_live_caches_updated=1, buffer_freed=1, prior_five_histories_NoMem_AB_failure_S0_clocks_banks_preserved=1)
    log = Log(b''); log.records = records
    verify_sixth(log, edge, identity); checks += 1
    mutations = [('DMM_REQUEST', 0, 'raw', '01'), ('DMM_REQUEST', 3, 'source', '0x9284074a'),
        ('REFERENCE_READBACK', 1, 'owners', '1'), ('FORMAT_NOTIFY', 1, 'destination', '0x90050004'),
        ('FORMAT_WRITTEN', 0, 'handle', '0x9000'), ('STATUS_READBACK', 0, 'writer_generation', '0'),
        ('DMM_REQUEST', 8, 'raw', '01'), ('REFERENCE_READBACK', 8, 'pool_live', '1')]
    for suffix, index, field, value in mutations:
        changed = copy.deepcopy(log)
        row = changed.rows(SIXTH[0] + '_' + suffix)[index]
        if field == 'raw': value = row['fields']['raw'][:-2] + value
        row['fields'][field] = value
        rejects(lambda changed=changed: verify_sixth(changed, edge, identity))
    changed = copy.deepcopy(log)
    free = changed.rows(SIXTH[0] + '_DMM_REQUEST')[-1]
    bad_free = bytearray.fromhex(free['fields']['raw']); struct.pack_into('<H', bad_free, 22, 0)
    free['fields']['raw'] = bad_free.hex()
    rejects(lambda: verify_sixth(changed, edge, identity))
    changed = copy.deepcopy(log); changed.one(old.FORWARD_TAGS[0])['fields']['cache'] = '0,1,1920,1080,0'
    rejects(lambda: verify_sixth(changed, edge, identity))
    with tempfile.TemporaryDirectory(prefix='six-edge-evaluator-') as directory:
        run = Path(directory); rejects(lambda: evaluate(run))
        (run / 'runtime-manifest.json').write_text(json.dumps({'host_control_owner_pid': os.getpid()}))
        with patch.object(old.fcntl, 'flock', side_effect=AssertionError('live run attempted locks')):
            rejects(lambda: evaluate(run))
        require(not list(run.glob('*evaluation.json')), 'partial run wrote successful evaluation')
        checks += 1
    require(fnv(PAYLOAD) == '37228cd728b41c0d', 'forwarded payload fingerprint'); checks += 1
    print(json.dumps({'self_test_checks_passed': checks, 'VM_contacted': False, 'locks_attempted': False,
                      'native_evidence_generated': False}, indent=2))


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test(); return 0
    require(len(sys.argv) == 2 and re.fullmatch(r'run-[A-Za-z0-9_-]+', sys.argv[1]), 'expected one run-BASENAME')
    run = BASE / 'menu-runs' / sys.argv[1]
    require(run.is_dir() and not run.is_symlink(), 'run directory missing/symlinked')
    proof = evaluate(run)
    output = run / 'six-edges-native-evaluation.json'
    with output.open('x') as stream:
        stream.write(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'evaluation': str(output), 'six_edges_native_verified': True,
        'same_run_SD_verified': True, 'cleanup_verified': True, 'capture_verified': False}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (old.EvidenceError, OSError, KeyError, ValueError, struct.error, tarfile.TarError) as error:
        print(json.dumps({'six_edges_native_verified': False, 'capture_verified': False,
                          'error': str(error), 'success_artifact_written': False}, indent=2), file=sys.stderr)
        sys.exit(1)
