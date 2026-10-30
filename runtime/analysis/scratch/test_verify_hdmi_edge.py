"""Host C effects and offline replay tests; never starts/accesses a VM or socket."""
# SPDX-License-Identifier: MIT
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

import pytest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_hdmi_edge as v
from test_pinmem_hdmi_video_connection import video_connection_binary, ENV
from test_adf_set_input_device import public_adf_input_seed


class Log:
    """Same record schema as the parent checker, without importing its build pins."""
    def __init__(self, text):
        self.records = []
        for line, text in enumerate(text.splitlines(), 1):
            match = re.search(r'(?:^|\bOBS )((?:FULL_|HDMI_|RCV_|PIN_)\w+) (.*)', text)
            if match:
                self.records.append(dict(line=line, tag=match[1], raw=text,
                    fields=dict(re.findall(r'(\w+)=([^\s]+)', match[2]))))

    def rows(self, tag):
        return [r for r in self.records if r['tag'] == tag]


@pytest.fixture(scope='module')
def host_log(video_connection_binary, public_adf_input_seed):
    if public_adf_input_seed is None:
        pytest.skip('pinned public ALLLANG seed unavailable')
    result = subprocess.run([str(video_connection_binary), 'normal', str(public_adf_input_seed)],
                            env=ENV, capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PINMEM_HDMI_VIDEO_CONNECTION_HOST_TEST_PASS' in result.stdout
    return Log(result.stdout)


def change(log, tag, field, value, index=0):
    candidate = copy.deepcopy(log)
    candidate.rows(tag)[index]['fields'][field] = value
    return candidate


def test_actual_c_host_effects_remain_offline(host_log):
    result = v.verify_hdmi_effects(host_log)
    assert result['REQUEST'] is host_log.rows(v.PREFIX + '_REQUEST')[0]
    assert len(result['condition_messages']) == 24
    assert len(result['UPM_messages']) == 2
    assert not result['native_UPM_join_required']
    assert not result['condition_model_events_verified']
    assert not result['frames_verified'] and not result['capture_verified']


@pytest.mark.parametrize('suffix,field,value', [
    ('NATIVE_REPLY_FREE', 'sender', '999999'),
    ('NATIVE_REPLY_FREE', 'tid', '999999'),
    ('NATIVE_REPLY_FREE', 'waiter', '0'),
    ('NATIVE_REPLY_FREE', 'rc', '-1'),
    ('NATIVE_REPLY_FREE', 'faults', '1'),
    ('EVENT6_CONSUMED', 'saved_request_fnv', '0000000000000000'),
    ('EVENT6_CONSUMED', 'token', '0x504d4001'),
    ('VIDEO_MANAGER', 'gate', '1'),
    ('VIDEO_MANAGER', 'gate_reset_at_connect', '1'),
    ('STATE_READBACK', 'source_pending', '1'),
])
def test_bad_ap_sender_and_callback_effects_rejected(host_log, suffix, field, value):
    with pytest.raises(ValueError):
        v.verify_hdmi_effects(change(host_log, v.PREFIX + '_' + suffix, field, value))


@pytest.mark.parametrize('mutation', ['missing', 'source', 'sid', 'lease', 'receiver', 'unreceived', 'raw-hex-id'])
def test_condition_content_and_complete_leases_required(host_log, mutation):
    log = copy.deepcopy(host_log)
    published = v._kind(log, 'MESSAGE_PUBLISHED', 2)
    freed = v._kind(log, 'NATIVE_FREE', 2)
    if mutation == 'missing':
        log.records.remove(freed[-1])
    elif mutation == 'source':
        published[0]['fields']['source'] = hex(v.P[3])
    elif mutation == 'sid':
        published[0]['fields']['destination'] = '0x81cf618c'
    elif mutation == 'lease':
        published[1]['fields']['lease'] = published[0]['fields']['lease']
    elif mutation == 'receiver':
        freed[0]['fields']['receiver'] = '999999'
    elif mutation == 'unreceived':
        freed[0]['fields']['received'] = '0'
    else:
        # 0x17 is not decimal 17.
        published[1]['fields']['raw'] = published[1]['fields']['raw'].replace('17000000', '11000000', 1)
    with pytest.raises(ValueError):
        v.verify_hdmi_effects(log)


def test_late_fault_or_unsupported_never_passes(host_log):
    for tag in (v.PREFIX + '_FAULT', v.PREFIX + '_UNSUPPORTED', v.STATE + '_FREE_REJECTED'):
        log = copy.deepcopy(host_log)
        log.records.append(dict(line=1000000, tag=tag, fields={}, raw='offline adversarial record'))
        with pytest.raises(ValueError):
            v.verify_hdmi_effects(log)


@pytest.fixture(scope='module')
def delayed_native_log():
    run = BASE / 'menu-runs/run-xnodlttg'
    if not (run / 'console.log').is_file():
        pytest.skip('explicit completed delayed-free-note run unavailable')
    path = BASE.parents[1] / 'report/functional-graph-evidence/check_graph.py'
    spec = importlib.util.spec_from_file_location('_hdmi_test_source_reader', path)
    graph = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(graph)
    relative = 'runtime/analysis/scratch/evaluate-five-edges-native.py'
    legacy = graph.source_module(relative, {str(graph.NATIVE / relative): graph.sha(graph.read(graph.NATIVE / relative))})
    original = graph.read(run / 'console.log', graph.MAX_LOG)
    assert len(original) == 2850791
    assert graph.sha(original) == '042d72dda0dcd45594ff5926900013e3966e79e95d09ed2df107ec63b0554931'
    parsed, repairs = graph.console_records(original)
    assert len(repairs) == 1 and repairs[0]['kind'] == 'exact-host-vvfat-diagnostic'
    log = legacy.Log(parsed)
    previous = v.one(log, 'FULL_PINMEM_DRAWINFO_CONNECT_NATIVE_REPLY_FREE')['line']
    first = v.one(log, 'FULL_IMAGING_PIN_CONNECT_REQUEST')['line']
    request = v.one(log, v.PREFIX + '_REQUEST')
    return run, log, previous, first, (request['fields']['pid'], request['fields']['producer_tid'])


def test_original_delayed_note_full_hdmi_stage_is_source_bound(delayed_native_log):
    run, log, previous, first, identity = delayed_native_log
    with pytest.raises(ValueError, match='live message address reused'):
        v.verify_conditions(log)
    with pytest.raises((TypeError, ValueError)):
        v.verify_conditions(log, True)
    result = v.verify_hdmi_edge(log, previous, identity, first, run)
    assert result['full_native_effects_verified'] and not result['capture_verified']
    assert len(result['condition_messages']) == 24 and len(result['prefix_reply_retirements']) == 3
    late = [(item, old) for item in result['condition_messages'] for old in item.get('late_free_note_predecessors', [])]
    assert len(late) == 1
    item, old = late[0]
    assert old['sent']['line'] < item['published']['line'] < old['free_note']['line']
    assert old['source_proof']['source_sha256'] == v.CONDITION_LEDGER_SOURCES
    assert old['source_proof']['console_sha256'] == '042d72dda0dcd45594ff5926900013e3966e79e95d09ed2df107ec63b0554931'
    upm = result['native_UPM']['receipts']
    assert len(upm) == 2 and upm[0]['events']['free_return'] < upm[1]['bridge_seq']
    assert upm[0]['u'] == upm[1]['u'] == v.number(result['condition_messages'][0]['published'], 'pointer')
    assert result['UPM_messages'][-1]['freed']['line'] < result['condition_messages'][0]['published']['line']
    assert not result['condition_model_events_verified']


def test_strict_logged_pointer_reuse_needs_no_source_or_public_assets(delayed_native_log, monkeypatch):
    _, original, *_ = delayed_native_log
    log = copy.deepcopy(original)
    pubs, sends, frees = [v._kind(log, suffix, 2) for suffix in ('MESSAGE_PUBLISHED', 'MESSAGE_SENT', 'NATIVE_FREE')]
    pair = [row for p in (pubs[0], pubs[11]) for row in
            (p, next(r for r in sends if r['fields']['lease'] == p['fields']['lease']),
             next(r for r in frees if r['fields']['lease'] == p['fields']['lease']))]
    assert pair[0]['fields']['pointer'] == pair[3]['fields']['pointer']
    log.records = pair
    for line, row in enumerate(pair, 1):
        row['line'] = line
    def unexpected(*args):
        raise AssertionError('strict order must not read source evidence')
    monkeypatch.setattr(v, '_condition_source_proof', unexpected)
    assert len(v._leases(log, 2)) == 2


@pytest.mark.parametrize('mutation', ['missing-receive', 'missing-free', 'missing-send', 'receiver', 'pointer',
    'size', 'source', 'raw', 'serial', 'free-rc', 'unsent', 'alias-fault', 'other-run-trace'])
def test_delayed_conditions_never_excuse_incomplete_or_changed_lifetimes(delayed_native_log, mutation):
    run, original, *_ = delayed_native_log
    log = copy.deepcopy(original)
    p, s, f = [v._kind(log, suffix, 2)[0] for suffix in ('MESSAGE_PUBLISHED', 'MESSAGE_SENT', 'NATIVE_FREE')]
    if mutation in ('missing-free', 'missing-send'):
        log.records.remove(f if mutation == 'missing-free' else s)
    elif mutation == 'missing-receive':
        f['fields']['received'] = '0'
    elif mutation in ('receiver', 'pointer', 'size', 'free-rc'):
        key, value = {'receiver': ('receiver', '999999'), 'pointer': ('pointer', '0x1'),
                      'size': ('bytes', '19'), 'free-rc': ('rc', '-1')}[mutation]
        f['fields'][key] = value
    elif mutation in ('source', 'raw'):
        p['fields'][mutation] = '0x1' if mutation == 'source' else '00' * 20
    elif mutation == 'serial':
        v._kind(log, 'MESSAGE_PUBLISHED', 2)[1]['fields']['lease'] = p['fields']['lease']
    elif mutation == 'unsent':
        s['line'] = v._kind(log, 'MESSAGE_PUBLISHED', 2)[11]['line'] + 1
    elif mutation == 'alias-fault':
        log.records.append(dict(tag=v.STATE + '_FAULT', fields={}, raw='alias', line=1000000))
    else:
        # Still internally consistent content; a valid archive cannot bless another trace.
        p['fields']['tid'] = s['fields']['tid'] = f['fields']['sender'] = '999999'
    with pytest.raises(ValueError):
        v.verify_conditions(log, run)


@pytest.fixture
def condition_source_replay(delayed_native_log, tmp_path):
    original, log, *_ = delayed_native_log
    run, batch = tmp_path / 'source-run', tmp_path / 'source-batch'
    run.mkdir(); batch.mkdir()
    for name in ('console.log', 'observer-build-inputs.json', 'observer-build-sources.tar.gz',
                 'runtime-manifest.json', 'source-snapshot-run-binding.json'):
        (run / name).write_bytes((original / name).read_bytes())
    binding = json.loads((run / 'source-snapshot-run-binding.json').read_bytes())
    for name in ('ready.json', 'inputs.json', 'abi.json'):
        (batch / name).write_bytes((Path(binding['batch']) / name).read_bytes())
    binding.update(run=str(run), batch=str(batch))
    (run / 'source-snapshot-run-binding.json').write_text(json.dumps(binding))
    return run, batch, log


@pytest.mark.parametrize('mutation', ['missing-archive', 'archive-bytes', 'manifest', 'run-binding',
    'observer-binding', 'batch-binding', 'selected-observer', 'abi-binding'])
def test_delayed_note_requires_original_archive_and_all_bindings(condition_source_replay, mutation):
    run, batch, log = condition_source_replay
    assert v.verify_conditions(log, run)['receiver_tid']
    if mutation in ('missing-archive', 'archive-bytes'):
        path = run / 'observer-build-sources.tar.gz'
        if mutation == 'missing-archive':
            path.unlink()
        else:
            path.write_bytes(path.read_bytes() + b'tampered')
    elif mutation == 'abi-binding':
        path = batch / 'abi.json'
        data = json.loads(path.read_bytes()); data['observer_sha256'] = '0' * 64
        path.write_text(json.dumps(data))
    else:
        path = batch / 'ready.json' if mutation == 'batch-binding' else run / (
            'runtime-manifest.json' if mutation in ('manifest', 'selected-observer') else 'source-snapshot-run-binding.json')
        data = json.loads(path.read_bytes())
        if mutation == 'manifest':
            data['compiled_observer']['source_archive_sha256'] = '0' * 64
        elif mutation == 'selected-observer':
            data['selected_initramfs_verified_files']['simulation/menu-observe.so'] = '0' * 64
        elif mutation == 'run-binding':
            data['run'] += '-wrong'
        elif mutation == 'observer-binding':
            data['observer_sha256'] = '0' * 64
        else:
            data['inputs_sha256'] = '0' * 64
        path.write_text(json.dumps(data))
    with pytest.raises((ValueError, OSError)):
        v.verify_conditions(log, run)


@pytest.mark.parametrize('relative', tuple(v.CONDITION_LEDGER_SOURCES))
def test_changed_archived_guard_is_not_approved_by_self_consistent_metadata(condition_source_replay, relative):
    run, batch, log = condition_source_replay
    build = json.loads((run / 'observer-build-inputs.json').read_bytes())
    path = run / 'observer-build-sources.tar.gz'
    with tarfile.open(fileobj=io.BytesIO(path.read_bytes())) as archive:
        members = {m.name: archive.extractfile(m).read() for m in archive if m.isfile()}
    source = str(BASE / relative)
    entry = build['sources'][source]
    if relative == 'device-models/hdmi-video-state.c':
        members[entry['archive_path']] = members[entry['archive_path']].replace(
            b'pointer==state.retained_request || find(pointer)', b'pointer==state.retained_request')
    else:
        members[entry['archive_path']] += b'\n'
    entry['sha256'] = hashlib.sha256(members[entry['archive_path']]).hexdigest()
    assert entry['sha256'] != v.CONDITION_LEDGER_SOURCES[relative]
    members['source-inputs.json'] = json.dumps(build['sources']).encode()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, value in members.items():
            member = tarfile.TarInfo(name); member.size = len(value)
            archive.addfile(member, io.BytesIO(value))
    path.write_bytes(output.getvalue())
    build['source_archive_sha256'] = hashlib.sha256(output.getvalue()).hexdigest()
    build_raw = json.dumps(build).encode()
    (run / 'observer-build-inputs.json').write_bytes(build_raw)
    manifest = json.loads((run / 'runtime-manifest.json').read_bytes())
    manifest['compiled_observer'] = build
    manifest['files'][str(BASE / 'observer-build-inputs.json')] = hashlib.sha256(build_raw).hexdigest()
    (run / 'runtime-manifest.json').write_text(json.dumps(manifest))
    tested = json.loads((batch / 'inputs.json').read_bytes())
    tested['groups']['production'][source] = entry['sha256']
    tested_raw = json.dumps(tested).encode(); (batch / 'inputs.json').write_bytes(tested_raw)
    ready = json.loads((batch / 'ready.json').read_bytes())
    ready['inputs_sha256'] = hashlib.sha256(tested_raw).hexdigest()
    ready_raw = json.dumps(ready).encode(); (batch / 'ready.json').write_bytes(ready_raw)
    binding = json.loads((run / 'source-snapshot-run-binding.json').read_bytes())
    binding['batch_ready_sha256'] = hashlib.sha256(ready_raw).hexdigest()
    (run / 'source-snapshot-run-binding.json').write_text(json.dumps(binding))
    with pytest.raises(ValueError, match='unreviewed condition ledger/hook source'):
        v.verify_conditions(log, run)


def test_native_upm_never_inherits_condition_delayed_note_rule(delayed_native_log):
    run, original, *_ = delayed_native_log
    log = copy.deepcopy(original)
    retired = v._kind(log, 'KERNEL_RETIRED', 3)
    retired[0]['line'] = v._kind(log, 'MESSAGE_PUBLISHED', 3)[1]['line'] + 1
    with pytest.raises(ValueError):
        v._leases(log, 3, native=True, run=run)
    log = copy.deepcopy(original)
    extra = copy.deepcopy(v._kind(log, 'KERNEL_RETIRED', 3)[0])
    extra['tag'] = v.STATE + '_NATIVE_FREE'; log.records.append(extra)
    with pytest.raises(ValueError, match='only two kernel retirements'):
        v.verify_hdmi_upm(log, run)


@pytest.fixture(scope='module')
def successful_native_log():
    run = BASE / 'menu-runs/run-xgs_bvga'
    if not (run / 'hdmi-upm-watch-events.jsonl').is_file():
        pytest.skip('explicit successful HDMI11 run is unavailable')
    log = Log((run / 'console.log').read_text())
    previous = v.one(log, 'FULL_PINMEM_DRAWINFO_CONNECT_NATIVE_REPLY_FREE')['line']
    first = v.one(log, 'FULL_IMAGING_PIN_CONNECT_REQUEST')['line']
    return run, log, previous, first


def test_successful_actual_hdmi11_full_content(successful_native_log):
    run, log, previous, first = successful_native_log
    result = v.verify_hdmi_edge(log, previous, ('258', '381'), first, run)
    assert result['full_native_effects_verified']
    assert len(result['condition_messages']) == 24
    assert len(result['prefix_reply_retirements']) == 3
    assert len(result['native_UPM']['receipts']) == 2
    assert result['condition_receiver_tid'] == '349'
    assert result['backup_inputs']['public_CP_bank_verified']
    assert not result['backup_inputs']['AP_runtime_bytes_independently_logged']
    assert not result['condition_model_events_verified']
    assert not result['condition_receive_site_runtime_logged']
    assert not result['capture_verified']
    # Repeated addresses are separate complete leases, never deduplicated.
    assert len({x['published']['fields']['pointer'] for x in result['condition_messages']}) < 24
    assert any(x['freed']['line'] < x['sent']['line'] for x in result['condition_messages'])


@pytest.mark.parametrize('tag,field,value,index', [
    ('FULL_PINMEM_NATIVE_REPLY_FREE', 'sender', '999999', -1),
    ('FULL_HDMIPIN_COMMIT', 'slot', '1', -1),
    ('FULL_HDMIPIN_COMMIT', 'type', '5', -1),
    ('HDMI_PHOTO_REQUEST', 'value', '0x81cf618c', 2),
    ('FULL_HDMI_VIDEO_BACKUP_READ', 'rc', '-1', 8),
    ('FULL_HDMI_VIDEO_BACKUP_READ', 'source', 'AP-runtime', 2),
    ('FULL_HDMI_VIDEO_STATE_DRIVER_CONSUMED', 'config', '00' * 36, 0),
])
def test_full_edge_get_subscription_and_backup_mutations(successful_native_log, tag, field, value, index):
    run, log, previous, first = successful_native_log
    candidate = copy.deepcopy(log)
    start = v.one(candidate, v.PREFIX + '_REQUEST')['line']
    rows = candidate.rows(tag)
    if tag in ('FULL_PINMEM_NATIVE_REPLY_FREE', 'FULL_HDMIPIN_COMMIT'):
        rows = [row for row in rows if previous < row['line'] < start]
        assert len(rows) == 1
        rows[0]['fields'][field] = value
    else:
        rows[index]['fields'][field] = value
    with pytest.raises(ValueError):
        v.verify_hdmi_edge(candidate, previous, ('258', '381'), first, run)


def test_host_trace_cannot_pass_without_native_receipts(host_log, tmp_path):
    with pytest.raises((ValueError, OSError)):
        v.verify_hdmi_upm(host_log, tmp_path / 'no-native-run')


@pytest.fixture
def native_replay(tmp_path, monkeypatch):
    # Explicitly supplied completed UPM-only run, never discover/poll another run.
    original = BASE / 'menu-runs/run-_vpkt22p'
    if not (original / 'hdmi-upm-watch-events.jsonl').is_file():
        pytest.skip('explicit actual native UPM replay run is unavailable')
    run = tmp_path / 'offline-replay'
    run.mkdir(mode=0o700)
    for name in ('hdmi-upm-watch-config.json', 'hdmi-upm-watch-events.jsonl',
                 'hdmi-upm-watch-result.json', 'hdmi-upm-coordinator.json'):
        (run / name).write_bytes((original / name).read_bytes())
    path = run / 'hdmi-upm-watch-config.json'
    config = json.loads(path.read_bytes())
    config.update(run=str(run), run_device=run.stat().st_dev, run_inode=run.stat().st_ino)
    path.write_text(json.dumps(config))
    monkeypatch.setattr(v._watch(), 'RUNS', tmp_path)
    return run, Log((original / 'console.log').read_text())


def test_actual_two_native_upm_receipts_join_without_full_edge_claim(native_replay):
    run, log = native_replay
    result = v.verify_hdmi_upm(log, run)
    assert result['native_UPM_verified'] and not result['full_edge_verified']
    assert [r['lease_serial'] for r in result['receipts']] == [4, 5]
    assert [r['tid'] for r in result['receipts']] == [205, 205]
    assert [r['raw_hex'] for r in result['receipts']] == [
        '170192000000000000009a0000000000', '170192000200000000009a0000000000']
    assert result['receipts'][1]['effective_hex'] == '170192000300000000009a0000000000'
    with pytest.raises(ValueError):
        v.verify_hdmi_edge(log, 1, ('258', '381'), 1, run)


@pytest.mark.parametrize('mutation', ['raw', 'effective', 'kernel-tid', 'mapping', 'branch', 'return-rc',
                                     'missing-free', 'missing-allocator', 'early-bridge'])
def test_independent_native_decoder_rejects_changed_events(native_replay, mutation):
    run, log = native_replay
    path = run / 'hdmi-upm-watch-events.jsonl'
    events = [json.loads(line) for line in path.read_text().splitlines()]
    if mutation == 'raw':
        row = next(e for e in events if e['kind'] == 'bridge')
        row['memory']['body']['hex'] = '170192000100000000009a0000000000'
    elif mutation == 'effective':
        row = [e for e in events if e['kind'] == 'branch'][-1]
        row['memory']['body']['hex'] = '170192000400000000009a0000000000'
    elif mutation == 'kernel-tid':
        next(e for e in events if e['kind'] == 'receive')['kernel_tid'] = 3
    elif mutation == 'mapping':
        row = next(e for e in events if e['kind'] == 'bridge')
        row['memory']['kernel_pool']['hex'] = '0000000000000000'
    elif mutation == 'branch':
        next(e for e in events if e['kind'] == 'branch')['registers']['x2'] = 0
    elif mutation == 'return-rc':
        next(e for e in events if e['kind'] == 'free_return')['registers']['x0'] = 1
    elif mutation == 'missing-free':
        events.remove(next(e for e in events if e['kind'] == 'free_return'))
    elif mutation == 'missing-allocator':
        events.remove(next(e for e in events if e['kind'] == 'vpool_fallback'))
    else:
        bridge = [e for e in events if e['kind'] == 'bridge'][1]
        events.remove(bridge)
        events.insert(next(i for i, e in enumerate(events) if e['kind'] == 'free_return'), bridge)
        for seq, row in enumerate(events, 1):
            row['seq'] = seq
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))
    with pytest.raises(ValueError):
        v.verify_hdmi_upm(log, run)


@pytest.mark.parametrize('mutation', ['missing-commit', 'commit-sha', 'unsafe-cleanup', 'wrong-nonce', 'wrong-effective'])
def test_mailbox_and_cleanup_are_required(native_replay, mutation):
    run, log = native_replay
    if mutation in ('missing-commit', 'commit-sha'):
        path = run / 'hdmi-upm-watch-result.json'
        result = json.loads(path.read_bytes())
        if mutation == 'missing-commit':
            result['mailbox_deliveries'].pop()
        else:
            result['mailbox_deliveries'][0]['record_sha256'] = '0' * 64
        path.write_text(json.dumps(result))
    elif mutation == 'unsafe-cleanup':
        path = run / 'hdmi-upm-coordinator.json'
        result = json.loads(path.read_bytes())
        result['cleanup']['safe_to_close'] = False
        path.write_text(json.dumps(result))
    elif mutation == 'wrong-nonce':
        log = change(log, 'FULL_HDMI_UPM_MAILBOX_CONSUMED', 'nonce', '0x1')
    else:
        log = change(log, 'FULL_HDMI_UPM_MAILBOX_CONSUMED', 'effective', '170192000200000000009a0000000000', 1)
    with pytest.raises(ValueError):
        v.verify_hdmi_upm(log, run)
