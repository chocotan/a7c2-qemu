#!/usr/bin/env python3
"""Verify a completed edges1..10+13 run without controlling a VM.

Usage: python3 scratch/evaluate-graph-batch-native.py run-BASENAME | --self-test
Fill the three EXPECTED_* build pins only after the independent original-libc
ABI check. That receipt must bind scratch/graph-batch-host-regression-v2.json via
host_regression_sha256, and contain observer_sha256, source_count,
source_archive_sha256, returncode, stdout, host_tests_passed,
host_subtests_passed. Gzip timestamps are not source identity.
Only complete evidence creates graph-batch-native-evaluation.json, exclusively.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tarfile

BASE = Path(__file__).resolve().parents[1]
EXPECTED_OBSERVER_SHA256 = 'c7d81562164603511fca3438d642c86e57687c73725d6fbf8c64c95152fd7752'
EXPECTED_SOURCE_COUNT = 302
EXPECTED_ABI_SHA256 = 'c32a43ad3c867c2bf25a64dadaeeecc38957b39e94a818241bd66496b5ca61d1'
HELPERS = {
    'scratch/evaluate-six-edges-native.py': '3a10557b02d2436510e6a3d7e8e19416e55412ac448f5ffbe63bc8708f6bfe12',
    'scratch/evaluate-five-edges-native.py': 'e8a27645a1f0b65f20db6fce4094c547e9856153ea00c61afcec3f5aa1fc0395',
    'initramfs_identity.py': 'e5e4b149ce671edacd9d41efebd9b0eef33ba7eedc0dafef7bda85f9c7484afe',
    'tts_dmm_evidence.py': 'ddbf0e0d5de1d446a54fddacca18a8b4767813cb70a075e70896681358ac9c0d',
}
PRODUCTION_SHA = 'e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d'
PUBLIC_CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
ALLLANG_SHA = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
LIBRARIES = {
    'usr/lib/libosal_utm.so': 'd9510b4ce1d7e59a0f2e9b5be14624a4cece6f514879e8a6d23ce890a46d25eb',
    'usr/lib/libInfraMediaMount.so': '90571d016f5f80b4c8cb4d9ff80c7600d19e0199a1ab7cfa6e9ee5d79587f612',
    'usr/lib/libInfraMediaCommon.so': 'd7cd602e9348e51703a6d3da396cfda949ea306856df7fa0deb62df1ff4ca974',
    'usr/lib/libbackup.so': '6a3c5f6067620c00d790cbe520844acdbb721fa5d0e7433b00a227f922ab9d0d',
    'usr/lib/appFw.so': '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
    'usr/lib/libObj.so': 'c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc',
    'usr/lib/libgpe.so': '80fc6236379933f80c2689aa002e0cf39483da8d45e876705d2a427cd1a2a7d1',
    'usr/lib/libInfraFsys.so': '33451a884b65f946ac8aca44b620cd3cec677d05752c52f2ff0e212a01824bfa',
    'usr/lib/libosal_uipc.so': '09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3',
    'usr/lib/libMWF.so': '63104a2506a385144ee4b485357c72cff7420aedc8d705e40124df20e6f97e69',
    'usr/lib/libmpr.so': '4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9',
    'usr/lib/libInfraMediaConfig.so': '756aa62554f970b7fbfd609d2a53008a3ecc80c608a98ef778baa399efcbebaf',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load_helper(relative):
    path = BASE / relative
    if sha(path.read_bytes()) != HELPERS[relative]:
        raise ValueError('read-only helper changed: ' + relative)
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Pin dependencies before an imported module can execute its own imports.
for _relative, _digest in HELPERS.items():
    if sha((BASE / _relative).read_bytes()) != _digest:
        raise ValueError('read-only helper changed: ' + _relative)
six = load_helper('scratch/evaluate-six-edges-native.py')
old, image = six.old, six.image
tts = load_helper('tts_dmm_evidence.py')
require, fields_equal, fnv = old.require, old.fields_equal, old.fnv
Log, raw_bytes, frame_bytes, model_frame = old.Log, old.raw_bytes, old.frame_bytes, old.model_frame
SEVENTH = ('FULL_VEF_PINMEM_CONTROL_CONNECT', 'vef_pinmem_control_connection',
    'virtual-vef-control0-pinmem-control0-v1', (8, 2, 0, 0x905a0048), (8, 1, 0, 0x90590818))
PEER_PROFILE = 'virtual-pinmem-scalar-adf-drawinfo-chain-v1'
NEW = (SEVENTH,
    ('FULL_SCALAR_CONNECT', 'pinmem_peer_connections', PEER_PROFILE,
     (0, 2, 1, 0x90590818), (0, 1, 4, 0x91670464)),
    ('FULL_ADF_CONNECT', 'pinmem_peer_connections', PEER_PROFILE,
     (0, 2, 2, 0x90590818), (0, 1, 0, 0x9058003f)),
    ('FULL_PINMEM_DRAWINFO_CONNECT', 'pinmem_peer_connections', PEER_PROFILE,
     (6, 2, 0, 0x90590818), (6, 1, 0, 0x928d0783)),
    ('FULL_ADF_HDMI_AUDIO_CONNECT', 'adf_hdmi_audio_connection',
     'virtual-adf-audio0-hdmi-audio0-v1', (5, 2, 0, 0x9058003f), (5, 1, 0, 0x909a015a)))
OWNERS = {0x905a0048: ('VEF', 15), 0x90590818: ('PINMEM', None),
          0x91670464: ('SCALAR', 4), 0x9058003f: ('ADF', None),
          0x928d0783: ('DRAWINFO', 1), 0x909a015a: ('HDMIPIN', 1)}
SLOTS = {(8, 2, 0, 0x905a0048): 15, (8, 1, 0, 0x90590818): 12,
    (0, 2, 1, 0x90590818): 4, (0, 1, 4, 0x91670464): 4,
    (0, 2, 2, 0x90590818): 5, (0, 1, 0, 0x9058003f): 0,
    (6, 2, 0, 0x90590818): 10, (6, 1, 0, 0x928d0783): 1,
    (5, 2, 0, 0x9058003f): 9, (5, 1, 0, 0x909a015a): 1}


def check_build_pins():
    require(re.fullmatch('[0-9a-f]{64}', EXPECTED_OBSERVER_SHA256 or '') and
            re.fullmatch('[0-9a-f]{64}', EXPECTED_ABI_SHA256 or '') and
            type(EXPECTED_SOURCE_COUNT) is int and EXPECTED_SOURCE_COUNT > six.SOURCE_COUNT,
            'new build pins unset: fill EXPECTED_OBSERVER_SHA256/EXPECTED_SOURCE_COUNT/EXPECTED_ABI_SHA256 after actual ABI check')


def verify_source_baseline(sources, tested, current):
    require(set(sources) == set(tested) == set(current), 'tested/run/current source sets differ')
    for name, entry in sources.items():
        require(entry['sha256'] == tested[name] == current[name], ('tested/run/current source SHA differs', name))


def verify_host_baseline(host, indexed, current):
    require(current == host, 'actual host profile set/SHA differs from ABI-bound regression')
    for name in host.keys() & indexed.keys():
        require(indexed[name] == host[name], ('indexed host profile SHA differs', name))
    return sorted(host.keys() - indexed.keys())


def read_archive(path, inputs):
    require(sha(path.read_bytes()) == inputs['source_archive_sha256'], 'same-run source archive receipt SHA differs')
    sources, frozen = inputs['sources'], {}
    with tarfile.open(path) as archive:
        members = [m for m in archive.getmembers() if not m.isdir()]
        require(all(m.isfile() for m in members) and len({m.name for m in members}) == len(members),
                'nonregular or duplicate archive input')
        require(json.load(archive.extractfile('source-inputs.json')) == sources, 'archived input index differs')
        paths = [entry['archive_path'] for entry in sources.values()]
        require(len(set(paths)) == len(paths) and {m.name for m in members} == set(paths) | {'source-inputs.json'},
                'archive source set differs')
        for name, entry in sources.items():
            p = PurePosixPath(entry['archive_path'])
            require(not p.is_absolute() and '..' not in p.parts and p.name == Path(name).name,
                    ('nonlocal archive input', name))
            data = archive.extractfile(str(p)).read()
            require(sha(data) == entry['sha256'], ('archived source SHA differs', name))
            frozen[name] = data
    return frozen


def verify_build(run, manifest):
    check_build_pins()
    abi_path = BASE / 'scratch/graph-batch-abi-v2.json'
    abi_raw = abi_path.read_bytes()
    require(sha(abi_raw) == EXPECTED_ABI_SHA256, 'independent batch ABI receipt pin differs')
    abi = json.loads(abi_raw)
    require((abi['returncode'], abi['observer_sha256'], abi['source_count']) ==
            (0, EXPECTED_OBSERVER_SHA256, EXPECTED_SOURCE_COUNT) and
            'PASS: constructor thread and application-init wrapper preserved behavior' in abi['stdout'],
            'batch original-libc ABI check or identity differs')
    require(abi['all_compiled_source_bytes_equal_tested_inputs'] is True and abi['capture_verified'] is False and
            abi['environment'] == {'MENU_OBSERVE_SELFTEST': '1'}, 'ABI receipt lacks tested-source/original-load scope')
    reg_raw = (BASE / 'scratch/graph-batch-host-regression-v2.json').read_bytes()
    regression = json.loads(reg_raw)
    require(sha(reg_raw) == abi['host_regression_sha256'] and regression['returncode'] == 0 and
            regression['production_sources_changed'] == [] and regression['host_profile_sources_changed'] == [] and
            regression['module_count'] == len(regression['modules']) == 52, 'ABI-bound stable 52-module regression differs')
    test_log = Path(regression['log']).read_bytes()
    require(re.search(rb'\b' + str(abi['host_tests_passed']).encode() + rb' passed, ' +
        str(abi['host_subtests_passed']).encode() + rb' subtests passed\b', test_log) and
        abi['host_tests_passed'] > 0 and abi['host_subtests_passed'] > 0, 'ABI-bound regression PASS log differs')
    inputs_raw = (run / 'observer-build-inputs.json').read_bytes()
    inputs = json.loads(inputs_raw)
    require(inputs == manifest['compiled_observer'] and inputs['observer_sha256'] == EXPECTED_OBSERVER_SHA256 and
            manifest['selected_observer_matches_build'] is True and len(inputs['sources']) == EXPECTED_SOURCE_COUNT,
            'same-run observer/build-inputs identity differs')
    frozen = read_archive(run / 'observer-build-sources.tar.gz', inputs)
    current = {name: sha(Path(name).read_bytes()) for name in inputs['sources']}
    verify_source_baseline(inputs['sources'], regression['production_sources_before'], current)
    host = regression['host_profile_sources_before']
    require({Path(name).name for name in host} == {'backup_profile.py', 'start-menu.py', 'qemu-menu-probe.py',
        'menu_control.py', 'menu_live.py'}, 'host profile baseline set differs')
    files, selected = manifest['files'], manifest['selected_initramfs_verified_files']
    host_index_omissions = verify_host_baseline(host, files,
        {name: sha(Path(name).read_bytes()) for name in host})
    for name, entry in inputs['sources'].items():
        if name in files:
            require(files[name] == entry['sha256'], ('manifest source SHA differs', name))
    require(files[str(BASE / 'observer-build-inputs.json')] == sha(inputs_raw), 'run build index manifest SHA differs')
    require(files[str(BASE / 'menu-observe.so')] == selected['simulation/menu-observe.so'] == EXPECTED_OBSERVER_SHA256 and
        sha((BASE / 'menu-observe.so').read_bytes()) == EXPECTED_OBSERVER_SHA256, 'actual new observer SHA differs')
    require({p: h for p, h in selected.items() if p.startswith('usr/lib/')} == LIBRARIES and
            manifest['original_libraries_unchanged'] is True, 'selected original twelve-library set/SHA differs')
    require(selected['cp/cpapp-b.bin'] == PUBLIC_CP_SHA, 'selected public CP differs')
    for name, digest in selected.items():
        path = BASE / 'menu-root' / name
        require(sha(path.read_bytes()) == digest, ('selected actual file SHA differs', name))
        if str(path) in files:
            require(files[str(path)] == digest, ('general selected file SHA differs', name))
    archive_image = Path(manifest['probe_args']['initramfs_file'] or BASE / 'menu-initramfs.cpio')
    require(sha(archive_image.read_bytes()) == files[str(archive_image)] and
            image.verify_image(archive_image, selected) == selected, 'selected initramfs actual file bytes differ')
    backup = manifest['backup_transport']
    require(backup['binary_sha256'] == files[backup['binary']] == old.QEMU_SHA and
            sha(Path(backup['binary']).read_bytes()) == old.QEMU_SHA, 'actual a0d candidate differs')
    production = BASE.parent / 'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'
    require(sha(production.read_bytes()) == PRODUCTION_SHA, 'original production binary changed')
    require(backup['source_seed_sha256'] == ALLLANG_SHA and sha((BASE / 'menu-root/seed-backup.bin').read_bytes()) == ALLLANG_SHA,
            'public ALLLANG seed differs')
    require(backup['fixture_sha256'] == 'a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977' and
            backup['fixture_bytes'] == 1419512 and sha(Path(backup['fixture']).read_bytes()) == backup['fixture_sha256'],
            'public Backup fixture differs')
    for _, key, profile, _, _ in six.SPECS + NEW:
        require(manifest[key + '_profile'] == backup[key + '_profile'] == profile, ('batch profile differs', key))
        require(manifest[key + '_capture_verified'] is False and backup[key + '_capture_verified'] is False,
                ('intent manifest promoted capture evidence', key))
        for name in ('native_verified', 'ap_consumed', 'connection_verified', 'connections_verified', 'frames_verified'):
            field = key + '_' + name
            if field in manifest or field in backup:
                require(manifest[field] is False and backup[field] is False,
                        ('intent manifest promoted runtime evidence', field))
    def source(name):
        matches = [(p, b.decode()) for p, b in frozen.items() if Path(p).name == name]
        require(len(matches) == 1, ('missing/ambiguous frozen implementation', name))
        return matches[0]
    provenance = []
    def contains(name, *tokens):
        path, text = source(name)
        for token in tokens:
            require(token in text, ('frozen source contract differs', name, token))
            provenance.append({'file': path, 'sha256': sha(frozen[path]),
                'line': text[:text.index(token)].count('\n') + 1, 'checked_source': token})
        return text
    contains('build-observers.sh', 'vef-pinmem-control-connection', 'scalar-connection',
             'adf-connection', 'pinmem-drawinfo-connection', 'adf-hdmi-audio-connection')
    observer = contains('menu-observe.c', 'FULL_HDMI_INPUT_AUDIT ', 'FULL_PINMEM_INPUT_AUDIT ',
        'bytes<=4096', 'bytes_complete && source_known')
    dispatch = observer[observer.index('int osal_snd_msg('):]
    for call in ('full_vef_pinmem_control_connection_dispatch(', 'full_scalar_connection_native_dispatch(',
                 'full_adf_connection_native_dispatch(', 'full_pinmem_drawinfo_connection_native_dispatch(',
                 'full_adf_hdmi_audio_connection_dispatch('):
        require(dispatch.index(call) < dispatch.index('full_vef_resource_send_enter('), 'batch endpoint after legacy resource gate')
    contains('pin-registry-core.c', 'pin_registry_key_get_retired', 'owner->retired_get[found.pin_index]=1',
        'found.sender==syscall(SYS_gettid)', 'pin_index=FULL_PIN_REGISTRY_CAPACITY')
    contains('vef-pinmem-control-connection.c', 'pin_registry_key_get_retired(full_vef_registry(),S)',
        'pin_registry_key_get_retired(full_pinmem_registry(),P)', 'unsigned char parameter[32]={0}',
        'e.body==(unsigned char *)e.answer+24', 'canonical(io,request,e.request,64,state.reply_destination)',
        'memcmp(e.request+48,(unsigned char *)e.body+24,3*sizeof(unsigned int))',
        'u32(e.request+60)==u32((unsigned char *)e.body+36)', 'return memcmp(&after,before,sizeof after)?-1:0;',
        'unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire)',
        'state.sender_tid=syscall(SYS_gettid);current_request=request;',
        'long sender=state.sender_tid,tid=syscall(SYS_gettid);', 'state.ap_consumed=tid==sender;',
        'unsigned int faults=state.faults,consumed=state.ap_consumed;', 'tid=%ld sender=%ld waiter=%u',
        'getpid(),tid,sender,(unsigned int)(tid==sender),destination,dst,reply,rc,faults,consumed')
    contains('pin-peer-connection.inc', 'pin_registry_key_get_retired(full_pinmem_registry(),S)',
        'pin_registry_key_get_retired(PEER_REGISTRY(),P)', 'unsigned char parameter[12]={0}',
        'e.body==(unsigned char *)e.answer+24', 'memcmp(e.request,saved_request,64)',
        'memcmp(e.request+48,(unsigned char *)e.body+24,4*sizeof(unsigned int))',
        'state.phase!=1 || state.wait_primary!=6', 'readback(&before_source,&before_peer,1,native)',
        'unsigned char final_wire[56];memcpy(final_wire,final,sizeof final_wire)', 'state.ap_consumed=(tid==waiter)')
    contains('adf-hdmi-audio-connection.c', 'pin_registry_key_get_retired(full_adf_registry(),S)',
        'pin_registry_key_get_retired(full_hdmi_pin_registry(),P)', 'full_hdmi_audio_pin_connected_one()',
        'after.hdmi.audio_pin_connected_owner_pid!=getpid()', 'return memcmp(&after,before,sizeof after)?-1:0;',
        'unsigned char final_wire[56];memcpy(final_wire,final,56)', 'if(tid==sender)')
    contains('hdmi-pin-device.c', 'struct pin_registry_owner *full_hdmi_pin_registry(void){return &registry;}')
    return {'ABI_receipt': abi, 'ABI_sha256': sha(abi_raw), 'observer_sha256': EXPECTED_OBSERVER_SHA256,
        'source_count': len(frozen), 'source_archive_sha256': inputs['source_archive_sha256'],
        'run_gzip_differs_from_ABI': inputs['source_archive_sha256'] != abi['source_archive_sha256'],
        'tested_archived_and_current_source_sets_and_every_SHA_equal': True,
        'five_host_profile_sources_verified': host, 'host_profile_manifest_index_omissions': host_index_omissions,
        'selected_original_libraries': LIBRARIES,
        'public_CP_sha256': PUBLIC_CP_SHA, 'public_ALLLANG_sha256': ALLLANG_SHA,
        'public_QEMU_sha256': old.QEMU_SHA, 'unchanged_production_QEMU_sha256': PRODUCTION_SHA,
        'original_initramfs_file_bytes_verified': True, 'frozen_source_contracts': provenance,
        'read_only_helpers': HELPERS, 'host_regression_sha256': sha(reg_raw), 'host_log_sha256': sha(test_log)}


def verify_get(log, key, identity, caller, after, before):
    owner = OWNERS[key[3]][0]
    prefix = 'FULL_' + owner
    requests = []
    for row in log.rows(prefix + '_REQUEST'):
        if after < row['line'] < before and row['fields'].get('tid') == identity[1]:
            wire = raw_bytes(row, 48)
            if struct.unpack_from('<3I', wire, 32) == key[:3]:
                requests.append(row)
    require(len(requests) == 1, ('missing/duplicate actual canonical Get for edge key', key))
    request = requests[0]
    wire = raw_bytes(request, 48)
    fields_equal(request, tid=identity[1], source=hex(caller), destination=hex(key[3]), reply_destination=hex(caller))
    require(wire == frame_bytes(48, 0, 2, key[:3] + (0,), caller, wire[20:24]), ('Get full request differs', key))
    replies = [r for r in log.rows(prefix + '_REPLY_QUEUED') if request['line'] < r['line'] < before
               and r['fields'].get('tid') == identity[1] and struct.unpack_from('<3I', raw_bytes(r, 56), 32) == key[:3]]
    require(len(replies) == 1, ('missing/duplicate Get reply', key))
    reply = replies[0]
    fields_equal(reply, tid=identity[1], source=hex(key[3]), destination=hex(caller))
    require(raw_bytes(reply, 56) == frame_bytes(56, 0x8000, 2, key[:3] + (1, key[3], 0)), ('Get full returned key/state/owner differs', key))
    pointer, lease = reply['fields']['reply'], reply['fields']['lease']
    require(int(pointer, 0) > 0 and int(lease) > 0, 'Get reply lacks allocation/lease')
    commits = [r for r in log.rows(prefix + '_COMMIT') if r['fields'].get('lease') == lease]
    frees = [r for r in log.rows(prefix + '_NATIVE_REPLY_FREE') if r['fields'].get('lease') == lease]
    require(len(commits) == len(frees) == 1, ('Get lease commit/free count differs', key, lease))
    commit, freed = commits[0], frees[0]
    fields_equal(commit, tid=identity[1], slot=SLOTS[key], type=key[0], dir=key[1], index=key[2],
        pin_state=1, owner=hex(key[3]), status=0, reply=pointer, lease=lease, request_free_rc=0,
        connect_performed=0, pixels_consumed=0, camera_startup_verified=0)
    fields_equal(freed, tid=identity[1], sender=identity[1], waiter=1, destination=hex(caller),
        expected=hex(caller), reply=pointer, lease=lease, bytes=56, rc=0)
    require(request['line'] < reply['line'] < commit['line'] < freed['line'] < before, 'actual Get lease not retired before connection')
    generic = [r for r in log.rows('PIN_QUERY') if after < r['line'] < request['line'] and
        r['fields'].get('tid') == identity[1] and r['fields'].get('raw') == wire.hex()]
    require(len(generic) == 1, ('canonical Get missing original AP sender bytes', key))
    fields_equal(generic[0], destination=hex(key[3]), source=hex(caller), bytes=48)
    return {'key': key, 'original_AP_query': generic[0], 'request': request, 'reply': reply, 'commit': commit,
            'actual_same_sender_free': freed, 'lease': lease}


def verify_new_edge(log, spec, previous_free, identity, first_graph_request):
    prefix, key, profile, source, peer = spec
    require(first_graph_request <= previous_free, 'graph phase must begin before predecessor free')
    for suffix in ('FAULT', 'CLEANUP_FAULT', 'REQUEST_FREE_FAULT', 'UNSUPPORTED', 'RESOURCES_REFUSED', 'RESOURCES_FAULT'):
        require(not log.rows(prefix + '_' + suffix), (prefix, 'failed transaction', suffix))
    early = log.rows(prefix + '_UNADMITTED')
    for row in early:
        fields_equal(row, requests=0, faults_unchanged=1)
        if 'owner_not_reset' in row['fields']:
            fields_equal(row, owner_not_reset=1)
        require(row['line'] < first_graph_request, (prefix, 'unexpected late unadmitted request'))
    scalar = prefix in ('FULL_SCALAR_CONNECT', 'FULL_ADF_CONNECT', 'FULL_PINMEM_DRAWINFO_CONNECT')
    tags = ['REQUEST', 'PEER_REQUEST', 'PEER_REPLY', 'REPLY_QUEUED',
            'STATE_READBACK' if scalar else 'COMMIT', 'NATIVE_REPLY_FREE' if scalar else 'REPLY_FREE']
    edge = {tag: log.one(prefix + '_' + tag) for tag in tags}
    original, caller = old.request_bytes(edge['REQUEST'], source, peer)
    for tag in tags[:4] + tags[-1:]:
        fields_equal(edge[tag], pid=identity[0], tid=identity[1])
    model_frame(edge['PEER_REQUEST'], 64, 0x100, 1, source[3], peer[3], source + peer)
    model_frame(edge['PEER_REPLY'], 72, 0x8100, 1, peer[3], source[3], source + peer + (0, 0))
    model_frame(edge['REPLY_QUEUED'], 56, 0x8001, 2, source[3], caller, source + (0, 0))
    final = edge[tags[-1]]
    fields_equal(final, destination=hex(caller), expected=hex(caller), bytes=56, rc=0, faults=0, ap_consumed=1)
    fields_equal(final, sender=identity[1], waiter=1)
    final_pointer = final['fields']['reply' if scalar else 'pointer']
    require(final_pointer == edge['REPLY_QUEUED']['fields']['pointer'] and
        final_pointer != edge['REQUEST']['fields']['pointer'], (prefix, 'actual AP free pointer differs/aliases request'))
    pointers = [edge[tag]['fields']['pointer'] for tag in tags[:3]]
    require(len(set(pointers)) == 3 and all(int(p, 0) > 0 for p in pointers), 'independent simultaneously live control allocations required')
    order = [edge[tag]['line'] for tag in tags]
    require(order == sorted(set(order)) and previous_free < order[0], (prefix, 'transaction/free order differs'))
    profile_tag = 'FULL_PINMEM_PEER_CONNECT_PROFILE' if scalar else prefix + '_PROFILE'
    profiles = [r for r in log.rows(profile_tag) if r['fields'].get('pid') == identity[0]]
    require(len(profiles) == 1 and profiles[0]['line'] < order[0], 'actual AP owner profile missing/late')
    fields_equal(profiles[0], requested=profile, enabled=1, first_missing='none', before_any_input=1)
    resources = log.one(prefix + '_RESOURCES_RESERVED', tid=identity[1], accepted=1,
        allocations=4, releases=4, control_live=0, control_faults=0, control_bound=1,
        dmm_domain=2, foreign_speech_kept=1, dmm_allocation_count=2, dmm_lifecycle_changed=0,
        dmm_slots='1/1', dmm_opens='1/1', dmm_handles='0x8400/0x8401', dmm_generations='1/1',
        dmm_epochs='1/2', dmm_creators='1/1', format_consumed=1, buffer_released=1,
        connection_reply_frees=1, connection_faults=0, vef_pending=0, vef_live=0, vef_retained=0,
        vef_faults=0, pinmem_pending=0, pinmem_live=0, pinmem_retained=0, pinmem_faults=0)
    require(previous_free < resources['line'] < order[0], 'new resource readback not between predecessor free and request')
    dependencies = log.one(prefix + '_RESOURCE_DEPENDENCIES', pid=identity[0], tid=identity[1], accepted=1,
        proc_ap_consumed=1, input_ap_consumed=1, output_ap_consumed=1, output_faults=0)
    require(previous_free < dependencies['line'] < resources['line'], 'new resource dependency order differs')
    if scalar:
        fields_equal(profiles[0], owner_pids=','.join([identity[0]] * 3), initialized='1,1,1')
    else:
        fields_equal(profiles[0], owner_pid=identity[0], initialized=1)
    frees = log.rows(prefix + '_INTERNAL_FREE')
    require(len(frees) == 2, (prefix, 'exact two independent peer frees required'))
    for row, tag in zip(frees, ('PEER_REQUEST', 'PEER_REPLY')):
        fields_equal(row, pid=identity[0], rc=0, pointer=edge[tag]['fields']['pointer'],
                     **{'owner' if scalar else 'destination': hex(caller)})
        if prefix != NEW[-1][0]:
            fields_equal(row, tid=identity[1])
        require(edge['PEER_REPLY']['line'] < row['line'] < edge['REPLY_QUEUED']['line'], 'internal free after publication')
    gets = [verify_get(log, pin, identity, caller, previous_free, order[0]) for pin in (source, peer)]
    # Pointers may be reused after free, including across transactions.
    require(gets[0]['actual_same_sender_free']['line'] < gets[1]['request']['line'], 'source/peer canonical Get order differs')
    for suffix in ('DMM_REQUEST', 'DMM_REPLY', 'FORMAT_WRITTEN', 'FORMAT_NOTIFY', 'FORMAT_CONSUMED',
                   'REFERENCE_READBACK', 'BUFFER_RETIRED', 'PEER_MARKER_WRITTEN', 'COMMAND_REQUEST',
                   'COMMAND_PREPARED', 'COMMAND_RETURNED'):
        require(not log.rows(prefix + '_' + suffix), (prefix, 'unexpected model side effect', suffix))
    for row in log.records:
        if order[0] < row['line'] < order[-1]:
            require(not re.search(r'_(DMM_REQUEST|DMM_REPLY|FORMAT_NOTIFY|FORMAT_WRITTEN|FORMAT_CONSUMED|COMMAND_REQUEST)$', row['tag']),
                    (prefix, 'unexpected DMM/format/command work', row['tag']))
    edge.update(prefix=prefix, source_pin=source, sink_pin=peer, caller=caller,
        original_request_fnv=fnv(original), profile=profiles[0], canonical_Get_retirements=gets,
        resources=resources, resource_dependencies=dependencies, internal_frees=frees, REPLY_FREE=final,
        early_unadmitted_requests={'unadmitted': early, 'before_graph_phase': True,
            'basis': 'requests=0 and faults_unchanged=1 before the first admitted graph request; no raw early request claim'})
    if scalar:
        edge['COMMIT'] = edge['STATE_READBACK']
    return edge


def verify_new_effects(log, edges, identity):
    seventh = edges[0]
    p = seventh['prefix']
    manager = log.one(p + '_SINK_MANAGER', type=8, choice_raw='0xf7474', branch_raw='0xf74a2',
        manager_get_raw='0x5d6a78', manager_CP_VA='0x10f5008', vtable_CP_VA='0xd270f0',
        method_offset='0xc', method_raw='0x5d6a86', typed_callback_called=1, rc=0,
        DMM=0, markers=0, events=0, clocks=0, MMIO=0, original_CP_executed=0)
    enqueued = log.one(p + '_EVENT8_ENQUEUED', producer_raw='0x5f99fe-0x5f9a4e', event=8,
        parameter_bytes=32, cleared_bytes=32, body_offset=24, token='0x56450001',
        token_policy='owned-answer-body-map', borrowed_reply_held=1, bounded_local_queue=1,
        original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
    consumed = log.one(p + '_EVENT8_CONSUMED', consumer_raw='0x10cb3e-0x10cb6a', event=8,
        actual_parameter_read=1, token_body_binding_verified=1, saved_original_header_bytes=24,
        original_peer_type_dir_index_verified=1, strict_peer_owner_verified=1, status=0, tail=0,
        source_complete_raw='0x5839a6', consumed=1, pending=0,
        original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
    posthook = log.one(p + '_POSTHOOK_NO_FORMAT', handler_raw='0x5f9a30', posthook_raw='0x10c89c',
        lookup_raw='0x5f8628', source_ordinal=15, owned_table_readback=1, selected_ordinals='1,2,3',
        selected=0, current_info_calls=0, f008_calls=0, DMM_allocations=0, notifications=0,
        cache_writes=0, marker_writes=0, clock_writes=0, MMIO_writes=0)
    fields_equal(seventh['COMMIT'], connections=1, source_slot=15, peer_ordinal=12, source_state=0,
        peer_state=0, source_pending=0, manager_calls=1, manager_rc=0, event8_enqueued=1,
        event8_consumed=1, event8_pending=0, source_posthook_ordinal=15, selected=0, format_work=0,
        marker_writes=0, prior_six_edges_live_caches_DMM_NoMem_AB_failure_S0_preserved=1, unique_reply=1)
    require(seventh['PEER_REQUEST']['line'] < manager['line'] < seventh['PEER_REPLY']['line'] <
        enqueued['line'] < consumed['line'] < posthook['line'] < seventh['internal_frees'][0]['line'], 'seventh manager/event/borrow lifetime order differs')
    seventh.update(manager=manager, event_enqueued=enqueued, event_consumed=consumed, posthook=posthook,
        event_parameter_expected_raw=(struct.pack('<I', 0x56450001) + bytes(28)).hex(),
        event_parameter_raw_logged=False,
        event_parameter_basis='actual event consumption log plus ABI-bound frozen full parameter/body/request comparison',
        original_CP_event_pointer_identity_verified=False, original_RTOS_scheduling_verified=False)
    for edge, source_slot, peer_slot in zip(edges[1:4], (4, 5, 10), (4, 0, 1)):
        p, source, peer = edge['prefix'], edge['source_pin'], edge['sink_pin']
        token = 0x504d0000 | (source[0] << 12) | source[2]
        parameter = struct.pack('<I', token) + bytes(8)
        enqueued = log.one(p + '_EVENT6_ENQUEUED', producer_raw='0x5d74ba', event=6, parameter_bytes=12,
            cleared_bytes=12, token=hex(token), raw=parameter.hex(), token_policy='owned-answer-plus24-map',
            saved_original_request_bytes=64, queue_phase=1, wait_primary=6, wait_secondary=0, keep_pending=1,
            context_kind=2, original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
        consumed = log.one(p + '_EVENT6_CONSUMED', consumer_raw='0x5dd814', work_raw='0xf882c',
            context_getters_raw='0x5db244,0x5db25a,0x5db24a,0x5db39a', parameter_bytes=12,
            parameter_fnv=fnv(parameter), token=hex(token), actual_parameter_read=1, token_body_binding_verified=1,
            saved_dynamic_destination=hex(edge['caller']), saved_request_fnv=edge['original_request_fnv'],
            reply_peer=','.join([str(v) for v in peer[:3]] + [hex(peer[3])]), full_peer_u32_verified=4,
            source_complete_raw='0x5839a6', status=0, tail=0, consumed=1, pending=0,
            original_CP_event_pointer_identity_verified=0, original_RTOS_scheduling_verified=0)
        if source[0] == 0:
            callback = log.one(p + '_YC_DIRECTION_CHECK', command='0x8100', selected_group='source', type=0,
                dir=2, index=source[2], callback_raw='0x5d6bc2', return_raw='0x5d6bf6', format_published=0, buffer_allocated=0)
            require(not log.rows(p + '_DRAWINFO_MANAGER'), 'YC edge selected DrawInfo manager')
        else:
            callback = log.one(p + '_DRAWINFO_MANAGER', selected_group='source', type=6, dir=2,
                manager='DrawInfoRawManager', method_offset='0xc', typed_callback_called=1, rc=0,
                YC_called=0, DMM=0, notifications=0, markers=0, MMIO=0)
            require(not log.rows(p + '_YC_DIRECTION_CHECK'), 'DrawInfo edge selected YC callback')
        fields_equal(edge['COMMIT'], source_type=source[0], source_slot=source_slot, peer_slot=peer_slot,
            source_state=0, peer_state=0, source_pending=0, event6_consumed=1, parameter_bytes=12,
            yc_format_published=0, AP_reply_after_source_callback=1, pixels_consumed=0)
        freed = log.one(p + '_REQUEST_FREE', pid=identity[0], tid=identity[1], owner=hex(source[3]),
            pointer=edge['REQUEST']['fields']['pointer'], bytes=64, rc=0)
        require(edge['PEER_REPLY']['line'] < enqueued['line'] < consumed['line'] < callback['line'] <
                edge['internal_frees'][0]['line'] < edge['REPLY_QUEUED']['line'] < freed['line'] <
                edge['COMMIT']['line'] < edge['REPLY_FREE']['line'], 'event6/request/free/state order differs')
        edge.update(event_enqueued=enqueued, event_consumed=consumed, source_callback=callback, original_request_free=freed)
    audio = edges[-1]
    p = audio['prefix']
    marker = log.one(p + '_HDMI_MARKER_READBACK', hook_raw='0x1297fe', Generic_tag_ADF_byte4=1,
        state_vtable_offset='0x34', old_known=0, connected=1, known=1, writes=1, readback=1,
        singleton_offset='0x60', next_state_null=1, state_identity_known=0,
        original_CP_memory_identity_verified=0, DMM=0, SSYN=0, clocks=0, PCM=0, MMIO=0)
    complete = log.one(p + '_SOURCE_COMPLETED', handler_raw='0x1976d8', method_CP_VA='0x68b9a6', source='5,2,0',
        complete_direct=1, event6=0, event8=0, postguard_raw='0x1977e0', selected_type5_dir1_index0=0,
        format_published=0, source_state=0)
    require(not any(r['tag'].startswith(p + '_EVENT') for r in log.records), 'audio edge used event6/8 instead of direct completion')
    fields_equal(audio['COMMIT'], connections=1, source_slot=9, peer_ordinal=1, source_state=0, peer_state=0,
        source_pending=0, marker_known=1, marker=1, marker_writes=1, direct_source_handler=1,
        format_work=0, prior_ten_and_unrelated_HDMI_pins_preserved=1, original_RTOS_scheduling_verified=0)
    require(audio['PEER_REPLY']['line'] < marker['line'] < complete['line'] < audio['internal_frees'][0]['line'],
            'HDMI shared marker/direct handler/free order differs')
    audio.update(shared_HDMI_marker=marker, direct_source_completion=complete,
        sink_posthook_return_meaning='NULL next state; protocol status comes from the canonical 72B reply',
        marker_owner_basis='actual AP wire identity plus ABI-bound shared HDMI singleton PID readback and preservation checks')


def verify_legacy(log, identity, first_line):
    speech = tts.prove_initial_creation(log.raw)
    require(speech['ap_pid'] == int(identity[0]) and speech['initial_speech_lifecycle_verified'] is True and
            speech['resource_release_authorized'] is False, 'same-run Speech405/406 ownership history differs')
    legacy = {
        'cpu': log.one('FULL_PIN_FORMAT_CPU_STATE_READBACK', tid=identity[1], handle='0x8000', source_slot=10,
            ordinal=1, downstream_pin=2, status=0, status_source='virtual-cold-constructor',
            currentinfo_raw='0200000001000000010000008007000038040000', original_runtime_state_verified=0, pixels_consumed=0),
        'persistent': log.one('FULL_PIN_FORMAT_PERSISTENT_READBACK', tid=identity[1], handle='0x8000',
            format_cpu_consumed=1, buffer_released=1, live=0, pin_index=2, ordinal=1, code=1, component=0,
            encoded_flags=0, width=1920, height=1080, camera_startup_verified=0),
        'input': log.one('FULL_ADF_SET_INPUT_APPLIED', pid=identity[0], generation=2, AB_status=1,
            AIP_first_task_rc='0x1004', AB_register_writes=0, AIP_uninspected=7, hardware_audio_success=0),
        'output': log.one('FULL_ADF_SET_OUTPUT_APPLIED', pid=identity[0], generation=3, control3_old_mask=8,
            target_mask=8, B0_newly_consumed=1, disable_writes_total=21, disable_readbacks_total=21,
            global_event=9, shadow_writes_added=0, inner_consumed=1),
    }
    for row in legacy.values():
        require(row['line'] < first_line, 'legacy history first appeared after graph connections')
    dispatches = log.rows('FULL_ADF_SET_INPUT_AIP_DISPATCH')
    require(len(dispatches) == 4, 'AB failure history count differs')
    for index, row in enumerate(dispatches):
        fields_equal(row, pid=identity[0], generation=2, event=index + 5, dispatches=index + 1,
            AB_status=1, task_rc='0x1004' if index == 0 else 0, first_uninspected_preserved=7,
            failure_history_preserved=1, old_tail_rechecked=0, ring_read=9, ring_write=9)
    events = [log.rows(tag) for tag in ('FULL_ADF_PROC_EVENT', 'FULL_ADF_SET_INPUT_EVENT', 'FULL_ADF_SET_OUTPUT_EVENT')]
    require([[int(r['fields']['event']) for r in rows] for rows in events] == [[1, 2, 3, 4], [5, 6, 7, 8], [9]],
            'source7 clock history changed/reset')
    output_free = log.one('FULL_ADF_SET_OUTPUT_REPLY_FREE', pid=identity[0], tid=identity[1],
        kind='queued-reply', rc=0, faults=0, retained=0, ap_consumed=1)
    bb = {
        'request': log.one('FULL_BB_SET_MODE_REQUEST', pid=identity[0], tid=identity[1], bytes=10,
            raw='0d2010010a0001800000', encoded_operation_mode=0, state_word=1),
        'first': log.one('FULL_BB_MODE_FIRST_COMPLETION', event='0x21a', result=0, mode_work_pending=1, unique_1110_pending=1),
        'outer': log.one('FULL_BB_MODE_OUTER_WORK', task=30, target=3, bytes=1760, known_bytes=4, unknown_bytes=1756,
            queue3_queued=0, queue3_inflight=1, operation_mode=0, inner_job_enqueued=1),
        'second': log.one('FULL_BB_MODE_SECOND_COMPLETION', event='0x21a', result=0, linked_byte5=1,
            linked_byte7=0, execution_gate_byte4=1, duplicate_reply_suppressed=1),
        'applied': log.one('FULL_BB_SET_MODE_APPLIED', state_word=1, target=3, operation_mode=0,
            work1aaddd_returned=1, work1b37ed_returned=1, internal_completions=2, unique_reply=1),
        'reply': log.one('FULL_BB_SET_MODE_REPLY_QUEUED', bytes=12, raw='0d2010110c00018000000000', source='0x92840747'),
        'commit': log.one('FULL_BB_SET_MODE_COMMIT', request_free_rc=0, retained_request=0, clean_completion=1),
        'freed': log.one('FULL_BB_SET_MODE_REPLY_FREE', kind='queued-reply', rc=0, faults=0, retained=0, ap_consumed=1),
    }
    order = [r['line'] for r in bb.values()]
    require(order == sorted(set(order)) and output_free['line'] < order[0] < order[-1] < first_line,
            'original output/BB mode consumer order differs')
    require(bb['outer']['fields']['live_fnv'] == bb['outer']['fields']['snapshot_fnv'] and
            bb['outer']['fields']['live_known_fnv'] == bb['outer']['fields']['snapshot_known_fnv'],
            'BB config bytes/known mask snapshot differs')
    require(bb['request']['fields']['caller'] == bb['reply']['fields']['destination'] ==
        bb['freed']['fields']['destination'] == bb['freed']['fields']['expected'] and
        bb['request']['fields']['request'] != bb['reply']['fields']['reply'] == bb['freed']['fields']['pointer'],
        'original BB reply identity/free allocation differs')
    return {'Speech': speech, 'retained_histories': legacy, 'AB_failure_dispatches': dispatches,
            'source7_events': events, 'SetPath': old.verify_path_producer(log, first_line),
            'original_AP_output_reply_free': output_free, 'BB_mode': bb, 'BB_reply_free_TID_logged': False}


def verify_audits(log):
    evidence, seen = [], set()
    for prefix in ('FULL_HDMI_INPUT_AUDIT', 'FULL_PINMEM_INPUT_AUDIT'):
        rows, chunks = log.rows(prefix), log.rows(prefix + '_BYTES')
        for row in rows:
            f = row['fields']; sequence = f['sequence']
            require(sequence not in seen, 'duplicate full input audit sequence')
            seen.add(sequence)
            fields_equal(row, state_verified=0, capture_verified=0,
                destination=hex(0x909a015a if prefix == 'FULL_HDMI_INPUT_AUDIT' else 0x90590818))
            require(int(f['pid']) > 1 and int(f['tid']) > 1, 'invalid input audit process/thread identity')
            require(f['size_known'] in ('0', '1') and f['source_known'] in ('0', '1'), 'invalid audit known flags')
            size_known, source_known = f['size_known'] == '1', f['source_known'] == '1'
            n = int(f['bytes'])
            require(n >= 0, 'negative audit size')
            complete_bytes = size_known and n <= 4096
            fields_equal(row, bytes_complete=int(complete_bytes), complete=int(complete_bytes and source_known))
            pieces = [r for r in chunks if r['fields'].get('sequence') == sequence]
            data, offset = bytearray(), 0
            for piece in pieces:
                fields_equal(piece, pid=f['pid'], tid=f['tid'], offset=offset)
                count = int(piece['fields']['bytes']); part = raw_bytes(piece, count)
                require(complete_bytes and count == min(128, n - offset) and count > 0,
                        'audit has extra/oversized/unrequested chunks')
                data.extend(part); offset += count
                require(piece['line'] > row['line'], 'audit chunk precedes metadata')
            require(len({r['line'] for r in pieces}) == len(pieces) and
                    [r['line'] for r in pieces] == sorted(r['line'] for r in pieces), 'audit chunk order/identity differs')
            require((offset == n) if complete_bytes else not pieces, 'full input audit bytes incomplete')
            evidence.append({'metadata': row, 'chunks': pieces, 'bytes_sha256': sha(data) if complete_bytes else None,
                             'state_verified': False})
        require(all(any(r['fields'].get('sequence') == c['fields'].get('sequence') for r in rows) for c in chunks),
                'audit byte chunk lacks metadata')
    require(evidence, 'full input audit was not mirrored')
    return evidence


def verify_remaining(log, tenth, audio, identity):
    expected = ((4, 2, 0, 0x90590818, 4, 1, 0, 0x909a015a),
                (1, 3, 0, 0x90590818, 1, 3, 0, 0x9080003b))
    rows = [r for r in log.rows('PIN_CONTROL_REQUEST') if r['line'] > tenth['REPLY_FREE']['line']]
    require(len(rows) == 2, ('only video11 and OSD12 may remain unsupported', len(rows)))
    for row, pins in zip(rows, expected):
        old.request_bytes(row, pins[:4], pins[4:]); fields_equal(row, tid=identity[1])
        require(row['line'] < audio['REQUEST']['line'], 'remaining edge ordered after audio13')
        end = min(old.next_pin_send(log, row), audio['REQUEST']['line'])
        refusals = [r for r in log.records if row['line'] < r['line'] < end and r['tag'].endswith('_UNSUPPORTED')]
        require(refusals, 'video/OSD request lacks explicit boundary refusal')
        require(not any(row['line'] < r['line'] < end and r['tag'].endswith(('_REPLY_QUEUED', '_REPLY_FREE'))
                        for r in log.records), 'unsupported video/OSD request received a success reply')
        row['refusals'] = refusals
    pending = [r for r in log.rows('NATIVE_CP_BACKGROUND_UNHANDLED') if r['fields'].get('opcode') == '0x302c']
    require(pending, 'same-run unhandled 302c evidence missing')
    return rows, pending


def normalize_transport(raw):
    prefix = (b'OBS FULL_INFRABB_VEF_CONNECT_COMMIT connections=1 source_state=0 peer_state=0 '
        b'source_pending=0 format_consumed=1 buffer_freed=1 unique_reply=1 prior_edges_')
    warning = b'qemu-system-aarch64: warning: vvfat: host directory commit pending\n'
    suffix = b'NoMem_AB_failure_S0_preserved=1 original_CP_executed=0 frames_verified=0 capture_verified=0'
    pattern = prefix + warning + suffix
    recovered, cursor = [], 0
    while True:
        position = raw.find(pattern, cursor)
        if position < 0:
            break
        start = position + len(prefix)
        recovered.append({'raw_warning_start': start, 'raw_warning_end': start + len(warning),
            'raw_record_line': raw[:position].count(b'\n') + 1,
            'host_warning': warning.decode().rstrip('\n'),
            'guest_bytes_invented': False, 'scope': 'exact fixed fourth-edge COMMIT split by host stderr'})
        cursor = start + len(warning)
    normalized = raw.replace(pattern, prefix + suffix)
    return normalized, recovered


def evaluate(run):
    check_build_pins()
    manifest = json.loads((run / 'runtime-manifest.json').read_text())
    cleanup = old.exited_processes(manifest['host_control_owner_pid'])
    build = verify_build(run, manifest)
    raw_console = (run / 'console.log').read_bytes()
    normalized_console, transport_recoveries = normalize_transport(raw_console)
    log = Log(normalized_console)
    edges, identity, resources, early = six.verify_graph(log)
    legacy = verify_legacy(log, identity, edges[0]['REQUEST']['line'])
    added, last = [], edges[-1]['REPLY_FREE']['line']
    for spec in NEW:
        edge = verify_new_edge(log, spec, last, identity, edges[0]['REQUEST']['line'])
        added.append(edge); last = edge['REPLY_FREE']['line']
        early[spec[0]] = edge['early_unadmitted_requests']
    verify_new_effects(log, added, identity)
    remaining, pending = verify_remaining(log, added[3], added[4], identity)
    audits = verify_audits(log)
    card, sd = old.verify_sd(run, manifest, log, identity[0], last)
    gtk = json.loads((run / 'gtk-input-proof.json').read_text())
    require(gtk['ok'] is False, 'graph control success unexpectedly promoted overall capture status')
    ee = six.verify_ee(run, log, identity[0], last)
    cleanup.update(old.exited_processes(manifest['host_control_owner_pid']))
    cleanup['locks_exclusive_acquired_and_released'] = old.verify_locks(card)
    return {'scope': 'eleven explicit virtual graph connections (1..10,13), control formats and metadata-only SD',
        'run': run.name, 'console_sha256': sha(raw_console),
        'parsed_console_sha256': sha(normalized_console), 'transport_interleavings': transport_recoveries,
        'record_line_numbers_refer_to': 'parsed console; each recovered raw offset/line is retained separately',
        'build': build,
        'original_AP_pid': int(identity[0]), 'original_AP_tid': int(identity[1]),
        'edges': edges + added, 'resources': resources, 'early_unadmitted_requests': early,
        'eleven_AP_replies_consumed': True, 'graph_batch_native_verified': True,
        'legacy_histories': legacy, 'full_input_audits': audits, 'remaining_two_connections_refused': remaining,
        '302c_unhandled': pending, '302c_completed': False, 'SD': sd, 'EE': ee, 'cleanup': cleanup,
        **{k: False for k in ('original_CP_executed', 'original_CP_page_tables_verified',
            'original_RTOS_scheduler_verified', 'original_CP_command_list_verified', 'PCM_verified',
            'hardware_verified', 'frames_verified', 'CMOS_verified', 'JPEG_verified', 'MP4_verified', 'capture_verified')}}


def self_test():
    path = BASE / 'scratch/test_evaluate_graph_batch_native.py'
    spec = importlib.util.spec_from_file_location('graph_batch_self_tests', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.run_tests(sys.modules[__name__])


def main():
    if sys.argv[1:] == ['--self-test']:
        self_test(); return 0
    require(len(sys.argv) == 2 and re.fullmatch(r'run-[A-Za-z0-9_-]+', sys.argv[1]), 'expected one run-BASENAME')
    run = BASE / 'menu-runs' / sys.argv[1]
    require(run.is_dir() and not run.is_symlink(), 'run directory missing/symlinked')
    output = run / 'graph-batch-native-evaluation.json'
    require(not output.exists() and not output.is_symlink(), 'evaluation already exists; will not overwrite/backfill')
    proof = evaluate(run)
    with output.open('x') as stream:
        stream.write(json.dumps(proof, indent=2) + '\n')
    print(json.dumps({'evaluation': str(output), 'eleven_AP_replies_consumed': True,
        'remaining_connections_refused': 2, 'same_run_SD_verified': True, 'cleanup_verified': True,
        'capture_verified': False}, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (old.EvidenceError, OSError, KeyError, ValueError, TypeError, struct.error, tarfile.TarError) as error:
        print(json.dumps({'graph_batch_native_verified': False, 'capture_verified': False,
            'error': str(error), 'success_artifact_written': False}, indent=2), file=sys.stderr)
        sys.exit(1)
