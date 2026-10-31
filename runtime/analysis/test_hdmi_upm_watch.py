"""Adversarial original-kernel allocation evidence, without QEMU or sockets."""
import copy
import ctypes
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hdmi_upm_watch as w

def test_unresponsive_debugger_is_retained_without_sigkill():
    events = []
    class Stuck:
        def poll(self): return None
        def send_signal(self, value): events.append(('signal', value))
        def terminate(self): events.append(('terminate',))
        def wait(self, timeout):
            events.append(('wait', timeout))
            raise subprocess.TimeoutExpired('owned-gdb', timeout)
        def kill(self): raise AssertionError('SIGKILL is forbidden')
    watcher = w.Watch.__new__(w.Watch)
    watcher.cleanup = None
    watcher.process = Stuck()
    watcher.log = None
    result = watcher.stop()
    assert result['safe_to_close'] is False and result['debugger_stopped'] is False
    assert result['detached'] is False and 'retained without SIGKILL' in result['errors'][0]
    assert events == [('signal', w.signal.SIGINT), ('wait', 6), ('terminate',), ('wait', 2)]


def test_actual_high_ddr_mailbox_pfn_range():
    assert w.mailbox_header({'phys': 0x50d7ff000, 'nonce': 7, 'pid': 258}) == struct.pack('<IIQI', w.MAILBOX_MAGIC, 1, 7, 258)
    for address in (0x3fffff000, 0x540000000, 0x50d7ff001):
        with pytest.raises(ValueError):
            w.mailbox_header({'phys': address, 'nonce': 7, 'pid': 258})


def test_startup_timeout_preserves_unsafe_cleanup_and_watcher(tmp_path, monkeypatch):
    config = dict(run=str(tmp_path), context=w.context(TEXTS))
    child = types.SimpleNamespace(poll=lambda: None, pid=12345)
    cleanup = dict(debugger_stopped=False, detached=False, safe_to_close=False, errors=['retained'])
    monkeypatch.setattr(w, 'owned_config', lambda *args: config)
    monkeypatch.setattr(w, 'revalidate', lambda _: config)
    monkeypatch.setattr(w.subprocess, 'Popen', lambda *args, **kwargs: child)
    monkeypatch.setattr(w.Watch, 'stop', lambda self: cleanup)
    ticks = iter((0, 13))
    monkeypatch.setattr(w.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(TimeoutError, match='did not arm') as caught:
        w.start(tmp_path, 1234, TEXTS)
    assert caught.value.hdmi_upm_cleanup is cleanup
    assert caught.value.hdmi_upm_watcher.process is child
    caught.value.hdmi_upm_watcher.log.close()


@pytest.fixture
def owned_qemu(tmp_path, monkeypatch):
    import socket
    run = tmp_path / 'run'
    run.mkdir()
    directory = os.open(run, os.O_RDONLY | os.O_DIRECTORY)
    server = socket.socket(socket.AF_UNIX)
    server.bind(f'/proc/self/fd/{directory}/' + w.SOCKET)
    os.chmod(run / w.SOCKET, 0o600)
    proc = tmp_path / 'proc'
    qemu = proc / '345'
    (qemu / 'net').mkdir(parents=True)
    (qemu / 'fd').mkdir()
    (qemu / 'root').mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    (qemu / 'root/out').symlink_to(run)
    (qemu / 'fd/4').symlink_to('socket:[678]')
    table = 'Num RefCount Protocol Flags Type St Inode Path\n000: 2 0 00010000 0001 01 678 /out/' + w.SOCKET + '\n'
    (qemu / 'net/unix').write_text(table)
    (proc / 'net').mkdir()
    (proc / 'net/unix').write_text(table.splitlines()[0] + '\n')
    executable = tmp_path / 'qemu-system-aarch64'
    executable.write_bytes(b'unit fixture, never executed')
    os.chmod(executable, 0o700)
    (qemu / 'exe').symlink_to(executable)
    monkeypatch.setattr(w, 'QEMU_SHA', w.hashlib.sha256(executable.read_bytes()).hexdigest())
    real_path = Path
    def path(value):
        if str(value) == '/proc':
            return proc
        return real_path(value)
    monkeypatch.setattr(w, 'Path', path)
    monkeypatch.setattr(w, 'RUNS', tmp_path)
    monkeypatch.setattr(w, 'original_opcodes', lambda _: {})
    def identity(pid):
        return dict(pid=pid, ppid=1234 if pid == 345 else 1, starttime=987,
                    exe='/tools/qemu-system-aarch64', cmdline=[b'qemu-system-aarch64', b'-m', b'24576',
                                                b'-gdb', ('unix:/out/' + w.SOCKET).encode()])
    monkeypatch.setattr(w, 'process_identity', identity)
    try:
        yield types.SimpleNamespace(run=run, proc=proc, qemu=qemu, binary=executable, other=other, table=table)
    finally:
        server.close()
        os.close(directory)


@pytest.mark.parametrize('scenario', ['owned-namespace', 'host-only-listener', 'wrong-out-mount'])
def test_listener_is_bound_in_owned_qemu_namespace(owned_qemu, scenario):
    fixture = owned_qemu
    if scenario == 'host-only-listener':
        (fixture.qemu / 'net/unix').write_text(fixture.table.splitlines()[0] + '\n')
        (fixture.proc / 'net/unix').write_text(fixture.table)
    elif scenario == 'wrong-out-mount':
        (fixture.qemu / 'root/out').unlink()
        (fixture.qemu / 'root/out').symlink_to(fixture.other)
    if scenario == 'owned-namespace':
        assert w.owned_config(fixture.run, 1234, TEXTS)['qemu_pid'] == 345
    else:
        with pytest.raises(ValueError, match='unique owned QEMU'):
            w.owned_config(fixture.run, 1234, TEXTS)


@pytest.fixture(params=(1, 2, 3))
def scope_owned(owned_qemu, tmp_path, monkeypatch, request):
    fixture = owned_qemu
    profile = w.scope_observer_profile
    version = {1: profile.PROFILE, 2: profile.PROFILE_V2, 3: profile.PROFILE_V3}[request.param]
    names = profile.SOURCE_SETS[version]
    native = tmp_path / 'native'
    base = native / 'runtime/analysis'
    base.mkdir(parents=True)
    source = profile.source_root(native, version)
    source.mkdir(parents=True)
    for name in names:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'owned source ' + name.encode())
    if version == profile.PROFILE_V3:
        schema = source / 'log-schema-v3.json'
        schema.write_text(json.dumps(dict(schema='readonly_scope_v3', profile=version)))
        (source / 'source-contract-v3.json').write_text(json.dumps(dict(
            schema='readonly_scope_source_contract_v3', profile=version, trace_schema='readonly_scope_v3',
            trace_schema_sha256=profile.sha(schema), actual_build_source_names_required=list(names))))
    header = native / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header.parent.mkdir(parents=True)
    header.write_bytes(b'owned API7 header')
    library = tmp_path / 'scope-observer.so'
    elf = bytearray(32)
    elf[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<HH', elf, 16, 3, 62)
    library.write_bytes(elf)
    receipt = tmp_path / 'scope-build.json'
    data = dict(schema=version, plugin_api=7, readonly_imports_verified=True,
        source_sha256={name: profile.sha(source / name) for name in names},
        qemu_header_sha256=profile.sha(header), qemu_sha256=profile.sha(fixture.binary),
        library=str(library), library_sha256=profile.sha(library))
    if version in (profile.PROFILE_V2, profile.PROFILE_V3):
        suffix = version[-2:]
        data.update(trace_schema='readonly_scope_' + suffix,
            trace_schema_sha256=data['source_sha256']['log-schema-' + suffix + '.json'],
            source_contract_sha256=data['source_sha256']['source-contract-' + suffix + '.json'],
            runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)
    if version == profile.PROFILE_V3:
        monkeypatch.setattr(profile, 'V3_QEMU_SHA256', profile.sha(fixture.binary))
        monkeypatch.setattr(profile, 'V3_HEADER_SHA256', profile.sha(header))
    receipt.write_text(json.dumps(data))
    build = profile.validate_build(native, receipt, fixture.binary)
    staged = fixture.run / 'readonly-scope-observer.so'
    staged.write_bytes(library.read_bytes())
    manifest = dict(readonly_scope_observer=dict(build, library=str(staged),
        log=str(fixture.run / 'readonly-scope-trace.log')),
        backup_transport=dict(binary=str(fixture.binary), binary_sha256=profile.sha(fixture.binary)),
        files={str(path): profile.sha(path) for path in
               (fixture.binary, receipt, staged, *(source / name for name in names))})
    manifest_path = fixture.run / 'runtime-manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(w, 'BASE', base)
    monkeypatch.setattr(w, 'QEMU_SHA', 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02')
    # Synthetic host bytes exercise the production guard without executing QEMU.
    monkeypatch.setattr(w, 'READONLY_SCOPE_QEMU_SHA', profile.sha(fixture.binary))
    return types.SimpleNamespace(**vars(fixture), native=native, source=source, header=header,
        library=library, staged=staged, receipt=receipt, manifest=manifest, manifest_path=manifest_path)


def test_reviewed_qemu_pins_remain_exact_and_distinct():
    assert w.QEMU_SHA == 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
    assert w.READONLY_SCOPE_QEMU_SHA == '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'


def test_receipt_reader_imports_from_its_own_base_without_pythonpath():
    code = '''import importlib.util, sys
from pathlib import Path
path=Path(sys.argv[1])
assert str(path.parent) not in sys.path
spec=importlib.util.spec_from_file_location('isolated_receipt_reader',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert Path(module.scope_observer_profile.__file__).resolve()==path.with_name('scope_observer_profile.py')
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(Path(w.__file__).resolve())],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_v2_scope_schema_metadata_cannot_differ_from_validated_receipt(scope_owned):
    f = scope_owned
    scope = f.manifest['readonly_scope_observer']
    if scope['profile'] == w.scope_observer_profile.PROFILE:
        assert 'trace_schema' not in scope
        return
    original = dict(scope)
    for key, value in (('trace_schema', 'readonly_scope_v1'), ('trace_schema_sha256', '0' * 64),
                       ('source_contract_sha256', '0' * 64)):
        scope[key] = value
        f.manifest_path.write_text(json.dumps(f.manifest))
        with pytest.raises(ValueError, match=scope['profile'][-2:] + ' manifest schema binding changed'):
            w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
        scope[key] = original[key]
    f.manifest_path.write_text(json.dumps(f.manifest))
    config = w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
    assert config['readonly_scope_observer']['profile'] == original['profile']
    assert w.revalidate(config) == config


def test_v3_scope_manifest_uses_selected_actual_new_root_and_no_alias_or_old_root_fallback(scope_owned):
    f = scope_owned
    scope = f.manifest['readonly_scope_observer']
    if scope['profile'] != w.scope_observer_profile.PROFILE_V3:
        return
    config = w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
    bound = config['readonly_scope_observer']
    assert bound['source_sha256'] == {name: w.scope_observer_profile.sha(f.source / name)
                                     for name in w.scope_observer_profile.SOURCE_NAMES_V3}
    assert len(bound['source_sha256']) == 9
    assert bound['trace_schema_sha256'] == w.scope_observer_profile.sha(f.source / 'log-schema-v3.json')
    for alias in ('schema_sha256', 'log_schema_sha256', 'v3_schema_sha256', 'source_root', 'Source_root', 'sourceDependencyFrozen'):
        scope[alias] = bound['trace_schema_sha256']
        f.manifest_path.write_text(json.dumps(f.manifest))
        with pytest.raises(ValueError, match='schema digest/root alias'):
            w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
        del scope[alias]
    old_root = f.native / 'report/2026-10-30-qemu-readonly-scope-observer'
    for name in bound['source_sha256']:
        digest = f.manifest['files'].pop(str(f.source / name))
        f.manifest['files'][str(old_root / name)] = digest
    f.manifest_path.write_text(json.dumps(f.manifest))
    with pytest.raises(ValueError, match='manifest.files'):
        w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)


def test_explicit_scope_receipt_returns_actual_owned_exe_and_default_stays_closed(scope_owned):
    f = scope_owned
    with pytest.raises(ValueError, match='actual running QEMU'):
        w.owned_config(f.run, 1234, TEXTS, MAILBOX)
    config = w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
    assert config['running_QEMU_sha256'] == w.scope_observer_profile.sha(f.qemu / 'exe')
    assert config['running_QEMU_sha256'] != w.QEMU_SHA
    assert config['readonly_scope_observer']['qemu_binary'] == str(f.binary)
    assert config['readonly_scope_observer']['build_receipt'] == str(f.receipt)
    assert config['readonly_scope_observer']['staged_library'] == str(f.staged)
    assert config['readonly_scope_observer']['identity_binding'] == 'unverified'
    assert config['readonly_scope_observer']['capture_verified'] is False
    assert w.revalidate(json.loads(json.dumps(config))) == config
    f.manifest['unrelated_runtime_progress'] = 'may change'
    f.manifest_path.write_text(json.dumps(f.manifest))
    assert w.revalidate(config) == config


@pytest.mark.parametrize('mutation', [
    'missing-scope', 'missing-profile', 'wrong-profile', 'unknown-exe', 'old-with-receipt',
    'receipt', 'receipt-reference', 'staged-library', 'original-library', 'source', 'header',
    'metadata-header', 'metadata-source', 'metadata-qemu', 'metadata-library', 'metadata-receipt',
    'metadata-identity', 'metadata-capture', 'metadata-physical', 'metadata-log',
    'binary-binding', 'symlink-binary', 'files-binary', 'files-receipt', 'files-library', 'files-source'])
def test_scope_admission_rejects_unbound_or_changed_assets(scope_owned, monkeypatch, mutation):
    f = scope_owned
    scope = f.manifest['readonly_scope_observer']
    if mutation == 'missing-scope':
        del f.manifest['readonly_scope_observer']
    elif mutation == 'missing-profile':
        del scope['profile']
    elif mutation == 'wrong-profile':
        scope['profile'] = 'other'
    elif mutation == 'unknown-exe':
        f.binary.write_bytes(b'unknown actual executable')
    elif mutation == 'old-with-receipt':
        monkeypatch.setattr(w, 'QEMU_SHA', w.READONLY_SCOPE_QEMU_SHA)
        monkeypatch.setattr(w, 'READONLY_SCOPE_QEMU_SHA', '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4')
        assert w.owned_config(f.run, 1234, TEXTS)['running_QEMU_sha256'] == w.QEMU_SHA
    elif mutation in ('receipt', 'staged-library', 'original-library', 'source', 'header'):
        path = {'receipt': f.receipt, 'staged-library': f.staged, 'original-library': f.library,
                'source': f.source / 'late-sites.inc', 'header': f.header}[mutation]
        path.write_bytes(path.read_bytes() + b' changed')
    elif mutation == 'receipt-reference':
        other = f.receipt.with_name('different-receipt.json')
        other.write_bytes(f.receipt.read_bytes())
        scope['build_receipt'] = str(other)
        f.manifest['files'][str(other)] = w.scope_observer_profile.sha(other)
    elif mutation.startswith('metadata-'):
        key = {'metadata-header': 'qemu_header_sha256', 'metadata-source': 'source_sha256',
               'metadata-qemu': 'qemu_sha256', 'metadata-library': 'library_sha256',
               'metadata-receipt': 'build_receipt_sha256', 'metadata-identity': 'identity_binding',
               'metadata-capture': 'capture_verified', 'metadata-physical': 'physical_asic_compatibility_verified',
               'metadata-log': 'log'}[mutation]
        scope[key] = {} if key == 'source_sha256' else 0 if key in (
            'capture_verified', 'physical_asic_compatibility_verified') else '0' * 64
    elif mutation == 'binary-binding':
        f.manifest['backup_transport']['binary_sha256'] = '0' * 64
    elif mutation == 'symlink-binary':
        alias = f.binary.with_name('alias-qemu')
        alias.symlink_to(f.binary)
        f.manifest['backup_transport']['binary'] = str(alias)
        f.manifest['files'][str(alias)] = w.READONLY_SCOPE_QEMU_SHA
    else:
        path = {'files-binary': f.binary, 'files-receipt': f.receipt, 'files-library': f.staged,
                'files-source': f.source / 'build-plugin.sh'}[mutation]
        f.manifest['files'][str(path)] = '0' * 64
    f.manifest_path.write_text(json.dumps(f.manifest))
    with pytest.raises(ValueError):
        w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)


def test_revalidation_rejects_even_a_valid_rebound_receipt(scope_owned):
    f = scope_owned
    config = w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
    f.receipt.write_bytes(f.receipt.read_bytes() + b' ')
    new_sha = w.scope_observer_profile.sha(f.receipt)
    f.manifest['readonly_scope_observer']['build_receipt_sha256'] = new_sha
    f.manifest['files'][str(f.receipt)] = new_sha
    f.manifest_path.write_text(json.dumps(f.manifest))
    assert w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)['readonly_scope_observer']['build_receipt_sha256'] == new_sha
    with pytest.raises(ValueError, match='binding changed'):
        w.revalidate(config)


def test_revalidation_retains_optional_plan_binding_and_rejects_changes(scope_owned):
    f = scope_owned
    f.manifest['readonly_scope_observer']['plan_binding'] = {'nonce': 123, 'batch_ready_sha256': '1' * 64}
    f.manifest_path.write_text(json.dumps(f.manifest))
    config = w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)
    assert config['readonly_scope_observer']['plan_binding'] == f.manifest['readonly_scope_observer']['plan_binding']
    assert w.revalidate(config) == config
    f.manifest['readonly_scope_observer']['plan_binding']['nonce'] = 124
    f.manifest_path.write_text(json.dumps(f.manifest))
    with pytest.raises(ValueError, match='binding changed'):
        w.revalidate(config)
    f.manifest['readonly_scope_observer']['plan_binding'] = False
    f.manifest_path.write_text(json.dumps(f.manifest))
    with pytest.raises(ValueError, match='plan binding must be an object'):
        w.owned_config(f.run, 1234, TEXTS, MAILBOX, f.receipt)


def test_start_generated_gdb_revalidation_and_detach_keep_scope_binding(scope_owned, monkeypatch):
    f = scope_owned
    calls, launches, recoveries = [], [], []
    validate = w.scope_observer_profile.validate_build
    def validate_build(*args):
        calls.append(args)
        return validate(*args)
    monkeypatch.setattr(w.scope_observer_profile, 'validate_build', validate_build)
    monkeypatch.setattr(w.shutil, 'which', lambda _: '/owned-gdb')
    child = types.SimpleNamespace(returncode=None, poll=lambda: child.returncode)
    def launch(*args, **kwargs):
        launches.append(args)
        w.publish_json(f.run, w.PREFIX + '-ready.json', dict(connected=True, armed=True, context=w.context(TEXTS)))
        return child
    monkeypatch.setattr(w.subprocess, 'Popen', launch)
    watcher = w.start(f.run, 1234, TEXTS, MAILBOX, scope_build_receipt=f.receipt)
    config_path = f.run / (w.PREFIX + '-config.json')
    config_raw = config_path.read_bytes()
    config_sha = w.hashlib.sha256(config_raw).hexdigest()
    script = (f.run / (w.PREFIX + '.gdb')).read_text()
    assert f'sys.path.insert(0, {str(w.BASE)!r})' in script
    assert f'config_sha256={config_sha!r}' in script
    class AfterValidation(Exception):
        pass
    def tracker(*args):
        raise AfterValidation()
    monkeypatch.setitem(sys.modules, 'gdb', types.SimpleNamespace())
    monkeypatch.setattr(w, 'Correlator', tracker)
    with pytest.raises(AfterValidation):
        w.gdb_main(config_path, config_sha256=config_sha)
    config_path.write_bytes(config_raw + b' ')
    with pytest.raises(ValueError, match='configuration changed'):
        w.gdb_main(config_path, config_sha256=config_sha)
    config_path.write_bytes(config_raw)
    child.returncode = 0
    (f.run / (w.PREFIX + '-result.json')).write_text('{"detached": false}')
    def recover(command, **kwargs):
        recoveries.append(command)
        assert child.poll() is not None
        assert command.count('target remote ' + w.SOCKET) == 1
        return types.SimpleNamespace(returncode=0, stdout=b'HDMI_UPM_DETACHED')
    monkeypatch.setattr(w.subprocess, 'run', recover)
    assert watcher.stop()['safe_to_close'] is True
    assert len(launches) == len(recoveries) == 1
    assert calls == [(f.native, f.receipt, f.binary)] * 4
    assert watcher.config['running_QEMU_sha256'] == w.READONLY_SCOPE_QEMU_SHA


T = 0xffffff8002000000
O = 0xffffff8001000000
TEXTS = {'upm': T, 'osal_uipc': O}
TASK = 0xffffffc010000000
PRODUCER = 0xffffffc010010000
FRAME = 0xffffffc011001000
USERBASE = 0x40000000
KBASE = 0xffffffc012000000
CTX = 0xffffffc013000000
LITERAL = 0xffffff8001010000
U = USERBASE + 0x1000
K = KBASE + 0x1000
# Independent instruction bytes from the original public ELF disassembly.
OPCODES = {'bridge': '421840f9e35340b2210002cb', 'send': '010a0094',
           'receive': 'e603002a', 'load': 'a01340f9', 'consumer': 'fd7bb7a9',
           'branch': 'f8f8ff97', 'handled': 'a11340f9', 'free_entry': '1f3840f2',
           'vpool': '26090094', 'vpool_fallback': '14090094', 'fblock': '19080094',
           'free_return': 'eaffff17'}


def header(ref=1, units=1, flags=0):
    return struct.pack('<QBBHIII', 0, units, flags, ref, 0x909a015a, 16, 0)


def body(op):
    return struct.pack('<4I', 0x00920117, op, 0x009a0000, 0)


def event(kind, seq, op=0, effective=0, u=U, k=K, allocator='vpool', units=1, flags=0):
    task = PRODUCER if kind in ('bridge', 'send') else TASK
    tid = 210 if task == PRODUCER else 144
    pcbase, offset = w.POINTS[kind]
    regs = dict.fromkeys(w.REGS, 0)
    regs.update(pc=TEXTS[pcbase] + offset, sp_el0=task, sp=FRAME, x29=FRAME)
    memory = {}
    def put(name, address, raw):
        memory[name] = dict(address=address, hex=raw.hex())
    put('opcode', regs['pc'], bytes.fromhex(OPCODES[kind]))
    put('task_pid', task + 0x388, struct.pack('<I', tid))
    if kind == 'bridge':
        regs.update(x0=0x80920572, x1=u, x2=CTX)
        put('user_pool', CTX + 48, struct.pack('<Q', USERBASE))
        put('kernel_literal', O + 0x1400, struct.pack('<Q', LITERAL))
        put('kernel_pool', LITERAL + 64, struct.pack('<Q', KBASE))
        put('user_header', u - 24, header(units=units, flags=flags))
        put('user_body', u, body(op))
    elif kind == 'send':
        regs.update(x0=0x80920572, x1=k, sp=FRAME - 16, x29=FRAME - 16)
    elif kind in ('receive', 'load', 'handled'):
        put('receive_slot', FRAME + 32, struct.pack('<Q', k))
    elif kind == 'consumer':
        regs.update(x0=k, x30=T + 0x140)
    elif kind == 'branch':
        regs.update(x19=k, x1=effective, x2=0x009a0000, sp=FRAME - 144, x29=FRAME - 144)
    elif kind == 'free_entry':
        regs.update(x0=0x80920572, x1=k, x30=T + 0x14c)
    elif kind in ('vpool', 'vpool_fallback', 'fblock'):
        regs.update(x0=KBASE, x1=k - 24 - (40 if flags & 0x40 else 0),
                    x2=units * 64 if units else 64, sp=FRAME - 16, x29=FRAME - 16)
        if kind == 'fblock':
            regs['x0'] = k - 24
        put('free_frame', FRAME - 16, struct.pack('<2Q', FRAME, T + 0x14c))
    if kind != 'free_return':
        ref = 0 if kind in ('vpool', 'vpool_fallback', 'fblock') else 1
        current_op = effective if kind in ('branch', 'handled', 'free_entry', 'vpool', 'vpool_fallback', 'fblock') else op
        put('header', k - 24, header(ref, units, flags))
        put('body', k, body(current_op))
    return dict(kind=kind, seq=seq, context=w.context(TEXTS), registers=regs, memory=memory,
                kernel_tid=tid, gdb_vcpu_thread=3)


def lifetime(start=1, op=0, effective=0, u=U, k=K, allocator='vpool', units=1, flags=0):
    kinds = ['bridge', 'send', 'receive', 'load', 'consumer', 'branch', 'handled',
             'free_entry', allocator, 'free_return']
    return [event(kind, start + i, op, effective, u, k, allocator, units, flags) for i, kind in enumerate(kinds)]


def feed(events, tracker=None):
    tracker = tracker or w.Correlator(TEXTS)
    for item in events:
        tracker.feed(item)
    return tracker


def commit(tracker):
    receipt = copy.deepcopy(tracker.pending)
    assert receipt is not None
    tracker.feed(dict(kind='receipt', seq=tracker.sequence + 1, context=w.context(TEXTS), receipt=receipt))
    return receipt


@pytest.mark.parametrize('effective', [2, 3])
@pytest.mark.parametrize('allocator,units,flags', [('vpool', 1, 0), ('vpool', 2, 0x40),
                                                   ('vpool', 0, 0), ('vpool_fallback', 1, 0x40),
                                                   ('fblock', 0, 0)])
def test_two_complete_actual_lifetimes_and_aba_after_retirement(effective, allocator, units, flags):
    tracker = feed(lifetime(allocator=allocator, units=units, flags=flags))
    first = commit(tracker)
    # Same U and K may be reused only after the first actual final retirement.
    feed(lifetime(tracker.sequence + 1, 2, effective, allocator=allocator, units=units, flags=flags), tracker)
    second = commit(tracker)
    assert first['tid'] == second['tid'] == 144
    assert first['producer_tid'] == 210
    assert first['raw_hex'] == first['effective_hex'] == body(0).hex()
    assert second['raw_hex'] == body(2).hex() and second['effective_hex'] == body(effective).hex()
    assert first['native_allocation_retired'] and not first['a_lease_binding_verified']
    assert second['bridge_seq'] > first['events']['free_return']
    assert len(tracker.receipts) == 2 and second['allocator'] == allocator


def test_checked_original_instruction_contract():
    actual = w.original_opcodes(TEXTS)
    assert {name: actual[name].hex() for name in OPCODES} == OPCODES


@pytest.mark.parametrize('stage', range(10))
def test_any_missing_tail_observation_leaves_no_receipt(stage):
    tracker = feed(lifetime()[:stage])
    assert tracker.receipts == [] and tracker.pending is None


def test_completed_but_unpublished_receipt_is_not_returned():
    tracker = feed(lifetime())
    assert tracker.pending is not None and tracker.receipts == []


def test_wrong_kernel_tid_cannot_be_substituted_by_vcpu_number():
    events = lifetime()
    wrong = events[7]
    wrong['kernel_tid'] = 145
    wrong['registers']['sp_el0'] += 0x20000
    wrong['memory']['task_pid'] = dict(address=wrong['registers']['sp_el0'] + 0x388, hex='91000000')
    with pytest.raises(ValueError, match='same-task'):
        feed(events)


def test_free_before_handler_is_rejected():
    events = lifetime()
    early = copy.deepcopy(events[7])
    early['seq'] = 6
    with pytest.raises(ValueError, match='Free before handler'):
        feed(events[:5] + [early])


@pytest.mark.parametrize('offset,value', [(12, 0x909a015b), (16, 8), (10, 2)])
def test_wrong_source_length_or_nonfinal_refcount(offset, value):
    events = lifetime()
    raw = bytearray.fromhex(events[0]['memory']['header']['hex'])
    struct.pack_into('<H' if offset == 10 else '<I', raw, offset, value)
    events[0]['memory']['header']['hex'] = raw.hex()
    with pytest.raises(ValueError, match='source/length/refcount'):
        feed(events)


def test_raw_mutation_before_consumer_is_rejected():
    events = lifetime()
    events[4]['memory']['body']['hex'] = body(2).hex()
    with pytest.raises(ValueError, match='mutated at consumer'):
        feed(events)


def test_reused_kernel_allocation_before_retirement_is_rejected():
    tracker = feed(lifetime()[:5])
    other = event('bridge', 6, op=2)
    with pytest.raises(ValueError, match='reused before final retirement'):
        tracker.feed(other)


def test_missing_allocator_call_is_not_final_release():
    events = lifetime()
    events[-1]['seq'] = 9
    with pytest.raises(ValueError, match='Missing final release'):
        feed(events[:8] + events[-1:])


def test_free_error_is_not_a_receipt():
    events = lifetime()
    events[-1]['registers']['x0'] = 0xfffffc00
    with pytest.raises(ValueError, match='free error'):
        feed(events)


def test_wrong_actual_mapping_is_rejected_at_send():
    events = lifetime()
    events[1]['registers']['x1'] += 64
    with pytest.raises(ValueError, match='frame/mapping'):
        feed(events)


def test_mapping_pool_bound_is_enforced():
    events = lifetime()
    events[0]['memory']['user_pool']['hex'] = struct.pack('<Q', U - 0x200000).hex()
    with pytest.raises(ValueError, match='pool mapping'):
        feed(events)


def test_missing_specific_branch_cannot_be_inferred_from_handler_return():
    events = lifetime()
    events[6]['seq'] = 6
    with pytest.raises(ValueError, match='specific branch'):
        feed(events[:5] + events[6:7])


def test_duplicate_receipt_cannot_retire_a_second_lease():
    tracker = feed(lifetime())
    receipt = commit(tracker)
    with pytest.raises(ValueError, match='duplicate receipt'):
        tracker.feed(dict(kind='receipt', seq=tracker.sequence + 1, context=w.context(TEXTS), receipt=receipt))


@pytest.mark.parametrize('mutation,match', [('ref', 'refcount'), ('frame', 'saved caller'),
                                            ('pointer', 'vpool allocation'), ('opcode', 'opcode/PC'),
                                            ('postfree', 'post-free read')])
def test_allocator_proof_must_be_exact(mutation, match):
    events = lifetime()
    if mutation == 'ref':
        events[8]['memory']['header']['hex'] = header(1).hex()
    elif mutation == 'frame':
        events[8]['memory']['free_frame']['hex'] = struct.pack('<2Q', FRAME, T + 0xdc).hex()
    elif mutation == 'pointer':
        events[8]['registers']['x1'] -= 40
    elif mutation == 'opcode':
        events[8]['memory']['opcode']['hex'] = '00000094'
    else:
        events[9]['memory']['body'] = dict(address=K, hex=body(0).hex())
    with pytest.raises(ValueError, match=match):
        feed(events)


MAILBOX = dict(phys=0x410000000, nonce=0x123456789abcdef0, pid=210)


def request_record(op=0, serial=4, index=0):
    raw = bytearray(256)
    struct.pack_into('<IIQIIQQ', raw, 0, 0x4d505548, 1, MAILBOX['nonce'], 210, 2, serial, U)
    raw[40:56] = body(op)
    raw[56:72] = body(index * 3)
    struct.pack_into('<I', raw, 108, index)
    struct.pack_into('<I', raw, 144, 210)
    struct.pack_into('<2Q4I', raw, 160, T, O, 0x909a015a, 0x80920572, 16, 0x009a0000)
    return bytes(raw)


def mailbox_receipt():
    tracker = w.Correlator(TEXTS, MAILBOX)
    events = lifetime()
    events[0]['memory']['mailbox_record'] = dict(address=MAILBOX['phys'], hex=request_record().hex())
    events[0]['memory']['task_tgid'] = dict(address=PRODUCER + 0x38c, hex=struct.pack('<I', 210).hex())
    feed(events, tracker)
    return tracker, copy.deepcopy(tracker.pending)


def test_physical_mailbox_full_receipt_abi_and_checksum():
    tracker, receipt = mailbox_receipt()
    raw = w.mailbox_payload(MAILBOX, request_record(), receipt)
    assert receipt['lease_serial'] == 4 and receipt['a_lease_binding_verified']
    assert raw[:20] == request_record()[:20] and raw[24:56] == request_record()[24:56]
    assert struct.unpack_from('<I', raw, 20)[0] == 3
    assert raw[56:72] == body(0)
    assert struct.unpack_from('<2Q6I', raw, 72) == (K, TASK, 144, 0, 1, 1, 0x7f, 0)
    assert struct.unpack_from('<4Q2I', raw, 112) == (T + 0x126e8, T + 0x14c, USERBASE, KBASE, 210, 0)
    # Independent known FNV-1a vector and independently replayed checksum.
    assert w.fnv64(b'hello') == 0xa430d84680aabd0b
    checksum = 14695981039346656037
    assert struct.unpack_from('<2Q4I4Q', raw, 160) == (T, O, 0x909a015a, 0x80920572, 16, 0x009a0000,
                                                     O + 0x4720, 1, 10, PRODUCER)
    assert raw[224:] == bytes(32)
    for byte in raw[:20] + raw[24:152] + raw[160:]:
        checksum = ((checksum ^ byte) * 1099511628211) % 2**64
    assert struct.unpack_from('<Q', raw, 152)[0] == checksum
    commit(tracker)


@pytest.mark.parametrize('field,offset,fmt,value', [('nonce', 8, '<Q', 1), ('owner', 16, '<I', 211),
                                                    ('status', 20, '<I', 3), ('lease', 24, '<Q', 0),
                                                    ('pointer', 32, '<Q', U + 64), ('index', 108, '<I', 1),
                                                    ('reserved', 148, '<I', 1)])
def test_mailbox_cannot_bind_a_foreign_or_stale_request(field, offset, fmt, value):
    _, receipt = mailbox_receipt()
    raw = bytearray(request_record())
    struct.pack_into(fmt, raw, offset, value)
    with pytest.raises(ValueError):
        w.mailbox_payload(MAILBOX, raw, receipt)


def test_python_receipt_is_accepted_by_independent_guest_c_validator(tmp_path):
    source = Path(w.__file__).parent / 'device-models/hdmi-upm-receipt.c'
    if not source.exists():
        pytest.skip('Partner guest implementation not delivered yet')
    library = tmp_path / 'receipt-validator.so'
    subprocess.run(['cc', '-std=c11', '-shared', '-fPIC', '-pthread', '-DFULL_HDMI_UPM_RECEIPT_TEST',
                    str(source), '-o', str(library)], check=True, capture_output=True)
    validate = ctypes.CDLL(str(library)).full_hdmi_upm_receipt_validate
    validate.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    validate.restype = ctypes.c_int
    _, receipt = mailbox_receipt()
    expected = ctypes.create_string_buffer(request_record())
    payload = w.mailbox_payload(MAILBOX, request_record(), receipt)
    assert validate(ctypes.create_string_buffer(payload), 256, expected) == 0
    bad = bytearray(payload)
    bad[104] = 0x3f
    assert validate(ctypes.create_string_buffer(bytes(bad)), 256, expected) == -1021


def test_mailbox_source_process_must_be_actual_kernel_tgid():
    tracker = w.Correlator(TEXTS, MAILBOX)
    events = lifetime()
    events[0]['memory']['mailbox_record'] = dict(address=MAILBOX['phys'], hex=request_record().hex())
    events[0]['memory']['task_tgid'] = dict(address=PRODUCER + 0x38c, hex=struct.pack('<I', 211).hex())
    with pytest.raises(ValueError, match='actual native producer TGID'):
        feed(events, tracker)


@pytest.mark.parametrize('action,failure', [('arm', None), ('receipt', None), ('receipt', 'write'),
                                           ('receipt', 'readback'), ('receipt', 'nonce'), ('read', 'packet')])
def test_only_dedicated_physical_mailbox_is_written_and_mode_is_restored(action, failure):
    _, receipt = mailbox_receipt()
    raw = bytearray(request_record())
    if action == 'arm':
        struct.pack_into('<I', raw, 20, 0)
    if failure == 'nonce':
        struct.pack_into('<Q', raw, 8, 1)
    commands, writes = [], []
    def execute(command, to_string):
        commands.append(command)
        if command.endswith('PhyMemMode:1') and failure == 'packet':
            return 'received: "E01"'
        return 'received: "OK"'
    def read_memory(address, size):
        assert commands[-1] != 'maintenance packet Qqemu.PhyMemMode:0'
        assert MAILBOX['phys'] <= address and address + size <= MAILBOX['phys'] + 256
        result = bytes(raw[address - MAILBOX['phys']:address - MAILBOX['phys'] + size])
        if writes and failure == 'readback':
            return bytes(size)
        return result
    def write_memory(address, data):
        assert commands[-1] == 'set may-write-memory on'
        assert (address, len(data)) in ((MAILBOX['phys'] + 56, 200), (MAILBOX['phys'] + 20, 4))
        writes.append((address, bytes(data)))
        if failure == 'write':
            raise RuntimeError('transport write failed')
        raw[address - MAILBOX['phys']:address - MAILBOX['phys'] + len(data)] = data
    debugger = types.SimpleNamespace(execute=execute)
    inferior = types.SimpleNamespace(read_memory=read_memory, write_memory=write_memory)
    if failure:
        with pytest.raises((ValueError, RuntimeError)):
            w.physical_mailbox(debugger, inferior, MAILBOX, action, receipt)
    else:
        result = w.physical_mailbox(debugger, inferior, MAILBOX, action, receipt)
        assert struct.unpack_from('<I', result, 20)[0] == (1 if action == 'arm' else 3)
        assert writes[-1] == (MAILBOX['phys'] + 20, struct.pack('<I', 1 if action == 'arm' else 3))
    assert commands[-1] == 'maintenance packet Qqemu.PhyMemMode:0'
    if writes:
        assert commands[-2] == 'set may-write-memory off'


def test_duplicate_json_fields_are_not_silently_adopted():
    with pytest.raises(ValueError, match='Duplicate JSON'):
        w.parse_json('{"seq":1,"seq":2}')


def published(tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'RUNS', tmp_path)
    run = tmp_path / 'owned'
    run.mkdir(mode=0o700)
    info = run.stat()
    config = dict(run=str(run), context=w.context(TEXTS), limit=64,
                  run_device=info.st_dev, run_inode=info.st_ino)
    (run / (w.PREFIX + '-config.json')).write_text(json.dumps(config))
    tracker = feed(lifetime())
    receipt = copy.deepcopy(tracker.pending)
    events = lifetime() + [dict(kind='receipt', seq=11, context=w.context(TEXTS), receipt=receipt)]
    path = run / (w.PREFIX + '-events.jsonl')
    path.write_text(''.join(json.dumps(item) + '\n' for item in events))
    return run, path


def test_strict_published_receipts(tmp_path, monkeypatch):
    run, path = published(tmp_path, monkeypatch)
    receipts = w.read_receipts(run)
    assert len(receipts) == 1 and receipts[0]['u'] == U
    original = path.read_text()
    path.write_text(original[:-1])
    with pytest.raises(ValueError, match='Incomplete'):
        w.read_receipts(run)
    path.write_text(original)
    path.rename(path.with_suffix('.real'))
    path.symlink_to(path.with_suffix('.real'))
    with pytest.raises(ValueError, match='Symlink'):
        w.read_receipts(run)


def test_acknowledgement_is_bound_to_a_complete_receipt(tmp_path, monkeypatch):
    run, _ = published(tmp_path, monkeypatch)
    receipt = w.ack_receipt(run, 1)
    assert receipt['native_allocation_retired']
    ack = json.loads((run / (w.PREFIX + '-ack-1.json')).read_text())
    assert ack['u'] == U and ack['events']['free_return'] == 10
    with pytest.raises(ValueError, match='No unique'):
        w.ack_receipt(run, 2)


def test_symlink_run_and_unknown_bases_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(w, 'RUNS', tmp_path)
    target = tmp_path / 'real'
    target.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(ValueError, match='nonsymlink'):
        w.validate_run(link)
    with pytest.raises(ValueError, match='actual module'):
        w.context({'upm': T})
    with pytest.raises(ValueError, match='base'):
        w.context({'upm': T, 'osal_uipc': 0})


def test_start_accepts_a_successfully_detached_capture_that_completed_immediately(tmp_path, monkeypatch):
    config = dict(run=str(tmp_path), context=w.context(TEXTS))
    monkeypatch.setattr(w, 'owned_config', lambda *args: config)
    monkeypatch.setattr(w, 'revalidate', lambda _: config)
    def launch(*args, **kwargs):
        w.publish_json(tmp_path, w.PREFIX + '-ready.json', dict(connected=True, armed=True, context=config['context']))
        (tmp_path / (w.PREFIX + '-result.json')).write_text(json.dumps(dict(detached=True, receipts=2)))
        return types.SimpleNamespace(poll=lambda: 0)
    monkeypatch.setattr(w.subprocess, 'Popen', launch)
    watcher = w.start(tmp_path, os.getpid(), TEXTS)
    assert watcher.stop()['safe_to_close']


def test_complete_gdb_observation_path_delivers_both_receipts_before_resuming(tmp_path, monkeypatch):
    config = dict(run=str(tmp_path), context=w.context(TEXTS), owner_pid=os.getpid(),
                  owner_starttime=1, owner_exe='test', mailbox=MAILBOX, limit=64,
                  run_device=tmp_path.stat().st_dev, run_inode=tmp_path.stat().st_ino)
    config_path = tmp_path / (w.PREFIX + '-config.json')
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(w, 'RUNS', tmp_path.parent)
    monkeypatch.setattr(w, 'revalidate', lambda _: config)
    monkeypatch.setattr(w, 'process_identity', lambda _: dict(starttime=1, exe='test'))
    inputs = lifetime() + lifetime(12, 2, 3)
    current = None
    cursor = 0
    physical = False
    page = bytearray(request_record())
    struct.pack_into('<I', page, 20, 0)
    commands, breakpoints, writes = [], {}, []
    stop_handler = None
    class BP:
        def __init__(self, spec, type, internal):
            self.number = len(breakpoints) + 1
            self.type = type
            self.pc = int(spec[1:], 16)
            self.deleted = False
            breakpoints[self.number] = self
        def delete(self):
            self.deleted = True
    def connect(handler):
        nonlocal stop_handler
        stop_handler = handler
    def execute(command, to_string):
        nonlocal physical, current, cursor, page
        commands.append(command)
        if 'PhyMemMode:' in command:
            physical = command.endswith(':1')
            return 'received: "OK"'
        if command == 'continue':
            assert not physical
            # A's guest callback consumes status=3 before publishing the next request.
            if cursor == 10:
                assert struct.unpack_from('<I', page, 20)[0] == 3
            current = inputs[cursor]
            cursor += 1
            if current['kind'] == 'bridge':
                page[:] = request_record(0 if cursor == 1 else 2, 4 if cursor == 1 else 5, 0 if cursor == 1 else 1)
            hit = [bp for bp in breakpoints.values() if bp.pc == current['registers']['pc']]
            assert len(hit) == 1 and hit[0].enabled
            stop_handler(types.SimpleNamespace(breakpoints=hit, stop_signal=None))
        return ''
    opcodes = w.original_opcodes(TEXTS)
    def read_memory(address, size):
        if physical:
            assert MAILBOX['phys'] <= address and address + size <= MAILBOX['phys'] + 256
            return bytes(page[address - MAILBOX['phys']:address - MAILBOX['phys'] + size])
        for kind, (module, offset) in w.POINTS.items():
            if address == TEXTS[module] + offset:
                return opcodes[kind]
        if current is not None:
            if address == PRODUCER + 0x38c and size == 4:
                return struct.pack('<I', 210)
            for item in current['memory'].values():
                if item['address'] == address and len(item['hex']) == size * 2:
                    return bytes.fromhex(item['hex'])
        raise AssertionError('Unexpected/post-free read ' + hex(address))
    def write_memory(address, data):
        assert physical and commands[-1] == 'set may-write-memory on'
        assert address in (MAILBOX['phys'] + 20, MAILBOX['phys'] + 56)
        writes.append((current['kind'] if current else 'arm', address, len(data)))
        page[address - MAILBOX['phys']:address - MAILBOX['phys'] + len(data)] = data
    def parse_and_eval(name):
        # QEMU XML exposes this system register in uppercase on some builds.
        if name == '$sp_el0':
            raise ValueError('Register spelling differs')
        return current['registers']['sp_el0' if name == '$SP_EL0' else name[1:]]
    fake = types.SimpleNamespace(execute=execute, Breakpoint=BP, BP_HARDWARE_BREAKPOINT=1,
                                 events=types.SimpleNamespace(stop=types.SimpleNamespace(connect=connect, disconnect=lambda _: None)),
                                 selected_inferior=lambda: types.SimpleNamespace(read_memory=read_memory, write_memory=write_memory),
                                 parse_and_eval=parse_and_eval, selected_thread=lambda: types.SimpleNamespace(num=3))
    monkeypatch.setitem(sys.modules, 'gdb', fake)
    w.gdb_main(config_path)
    result = json.loads((tmp_path / (w.PREFIX + '-result.json')).read_text())
    assert 'error' not in result and result['receipts'] == 2 and result['detached']
    assert len(result['mailbox_deliveries']) == 2 and cursor == 20
    assert all(kind == 'free_return' for kind, _, _ in writes[1:])
    assert len(w.read_receipts(tmp_path)) == 2
    assert struct.unpack_from('<I', page, 20)[0] == 3 and page[56:72] == body(3)
    assert not physical and all(bp.deleted for bp in breakpoints.values())


@pytest.mark.parametrize('failure', ['opcode', 'continue'])
def test_gdb_failure_always_deletes_hardware_breakpoints_and_detaches(tmp_path, monkeypatch, failure):
    run = tmp_path
    config = dict(run=str(run), context=w.context(TEXTS), owner_pid=os.getpid(),
                  owner_starttime=1, owner_exe='test')
    path = run / 'config.json'
    path.write_text(json.dumps(config))
    monkeypatch.setattr(w, 'revalidate', lambda _: config)
    monkeypatch.setattr(w, 'process_identity', lambda _: dict(starttime=1, exe='test'))
    commands, breakpoints = [], []
    hooks = types.SimpleNamespace(connect=lambda _: None, disconnect=lambda _: None)
    opcodes = w.original_opcodes(TEXTS)
    class BP:
        def __init__(self, spec, type, internal):
            self.number = len(breakpoints) + 1
            self.type = type
            self.deleted = False
            breakpoints.append(self)
        def delete(self):
            self.deleted = True
    def read_memory(address, size):
        for kind, (module, offset) in w.POINTS.items():
            if address == TEXTS[module] + offset:
                return b'\0' * size if failure == 'opcode' else opcodes[kind]
        raise AssertionError('Unexpected memory read')
    def execute(command, to_string):
        commands.append(command)
        if command == 'continue':
            raise RuntimeError('Injected debugger failure')
        return ''
    fake = types.SimpleNamespace(execute=execute, Breakpoint=BP, BP_HARDWARE_BREAKPOINT=1,
                                 events=types.SimpleNamespace(stop=hooks),
                                 selected_inferior=lambda: types.SimpleNamespace(read_memory=read_memory))
    monkeypatch.setitem(sys.modules, 'gdb', fake)
    w.gdb_main(path)
    result = json.loads((run / (w.PREFIX + '-result.json')).read_text())
    assert result['detached'] is True and 'error' in result
    assert commands[-1] == 'detach' and all(bp.deleted for bp in breakpoints)
    assert 'set may-write-memory off' in commands and 'set may-write-registers off' in commands
    assert not any(command.startswith(('set $', 'call ', 'jump ')) for command in commands)
    assert not (run / (w.PREFIX + '-ready.json')).exists() if failure == 'opcode' else result['armed']
