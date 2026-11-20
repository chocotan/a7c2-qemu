"""Synthetic GDB only: no subprocess, guest, endpoint or VM."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest
import hdmi_upm_watch as w
import model17c_runtime_observer as model

PINS = json.loads((Path(__file__).parent / 'model17c_runtime_pins.json').read_text())
BASE = 0x7000000000
PAGE_OFFSET = 0xffffffc000000000
TASK = 0xffffff8008700000
MM = 0xffffff8008710000
PGD = 0xffffffc000123000
MEMSTART = 0x400000000
TTBR = PGD - PAGE_OFFSET + MEMSTART
SYMS = {'__entry_task': 0xffffff8008661490, '__per_cpu_offset': 0xffffff8008687108}
TEXTS = {'upm': 0xffffff800095e000, 'osal_uipc': 0xffffff80004be000}


def binding():
    return dict(profile=model.PROFILE, inline_profile=model.PROFILE, pid=233, base=BASE, ttbr0=TTBR,
                task=TASK, mm=MM, pgd=PGD, memstart=MEMSTART, cpu=0, symbols=dict(SYMS),
                abi={'task_mm': 0x2d8, 'mm_pgd': 0x40},
                maps=f'{BASE:x}-{BASE+0x10000000:x} r-xp 00000000 00:01 10 /usr/lib/appFw.so\n')


def run_owner(tmp_path, monkeypatch, failure=None, sites=('date_gate', 'helper_return'), detached=False):
    bound = dict(binding(), asset_sha256=model.ASSET_SHA256, maps_sha256='synthetic')
    config = dict(run=str(tmp_path), context=w.context(TEXTS), owner_pid=123,
                  owner_starttime=1, owner_exe='test', seconds=w.SECONDS, model17c_runtime=bound)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    monkeypatch.setattr(w, 'revalidate', lambda _: config)
    monkeypatch.setattr(w, 'original_opcodes', lambda _: {name: b'abcd' for name in w.POINTS})
    monkeypatch.setattr(w, 'process_identity', lambda _: dict(starttime=1, exe='test'))
    trace, bps, memory = [], [], {}

    def poke(address, raw):
        for n, byte in enumerate(raw):
            memory[address + n] = byte

    registers = {f'x{i}': 0 for i in range(31)}
    registers.update(pc=BASE + 0x209ec38, sp=0x7100000000, x29=0x7100000000, cpsr=0, tpidr=44)
    if detached:
        registers['pc'] = BASE + 0x1000  # Fresh attach after the early detach need not be at the gate.
        # The fresh stop may be a kernel thread with no user mm; installation
        # must not resolve the bound AP task until an actual observation event.
        poke(SYMS['__entry_task'], (0).to_bytes(8, 'little'))
        binding_sha = w.hashlib.sha256(json.dumps(bound, sort_keys=True).encode('ascii')).hexdigest()
        (tmp_path/'model17c-startup-result.json').write_text(json.dumps(dict(
            schema='a7c2-model17c-startup-detached-v1', detached=True,
            separate_process_handoff=True, early_breakpoints_remaining=[],
            runtime_binding_sha256=binding_sha)))
    for pin in PINS['points'].values():
        poke(BASE + pin['va'], bytes.fromhex(pin['original_hex']))
    poke(BASE + 0x267b698, bytes.fromhex(PINS['setter_full_hex']))
    for offset, size in model.STATIC.values():
        for n in range(size):
            memory[BASE + offset + n] = 0
    for n in range(4):
        memory[registers['x29'] + 0x8c + n] = 0
    pointer = 0x7200000000
    for offset, raw in [(0, (BASE+0x7e5d570).to_bytes(8, 'little')),
                        (8, bytes(8)), (0x10, (0x17c).to_bytes(4, 'little')), (0x18, bytes(8))]:
        poke(pointer + offset, raw)
    # Per-cpu current task and its mm->pgd chain, replacing the unavailable
    # sp_el0/ttbr0_el1 register reads of the old contract.
    poke(SYMS['__per_cpu_offset'] + 8 * 0, (0).to_bytes(8, 'little'))
    poke(SYMS['__entry_task'], TASK.to_bytes(8, 'little'))
    poke(TASK + 0x2d8, MM.to_bytes(8, 'little'))
    poke(MM + 0x40, PGD.to_bytes(8, 'little'))
    poke(TASK + 0x388, (44).to_bytes(4, 'little'))
    poke(TASK + 0x38c, (44).to_bytes(4, 'little'))
    hook = None
    cursor = 0
    remote_count = 0
    class BP:
        def __init__(self, spec, type, internal):
            if failure == 'create' and len(bps) == 3:
                raise ValueError('no hardware slot')
            self.number = len(bps) + 1
            self.type, self.pc = type, int(spec[1:], 16)
            self.enabled, self.pending, self.valid = True, False, True
            bps.append(self)
            trace.append(('install', self.number))
        def is_valid(self):
            return self.valid
        def delete(self):
            trace.append(('delete', self.number))
            if failure == 'delete' and self.number == 1:
                raise ValueError('delete refused')
            self.valid = False
    def read(address, size):
        for name, (module_name, offset) in w.POINTS.items():
            if address == TEXTS[module_name] + offset:
                return b'abcd'
        if failure == 'pin' and address == BASE + 0x209ee20:
            return bytes(size)
        if failure == 'read' and cursor and address == BASE + 0x7e5d570:
            raise ValueError('static read failed')
        return bytes(memory[address+n] for n in range(size))
    def reg(name):
        if failure == 'register' and cursor and name == 'tpidr':
            raise ValueError('missing TLS')
        return registers[name]
    def parse_and_eval(expr):
        return reg(expr[1:])
    def selected_thread():
        return NS(num=1 + 0)
    def connect(handler):
        nonlocal hook
        hook = handler
    def execute(command, to_string=True):
        nonlocal cursor, remote_count
        trace.append(('command', command))
        if command.startswith('target remote '):
            remote_count += 1
            if detached and remote_count > 1:
                poke(SYMS['__entry_task'], TASK.to_bytes(8, 'little'))
        if command == 'set breakpoint always-inserted on':
            if failure == 'insert':
                raise ValueError('hardware insertion refused')
            if failure == 'pending':
                bps[0].pending = True
        if command == 'continue':
            if detached:
                poke(SYMS['__entry_task'], TASK.to_bytes(8, 'little'))
            assert all(bp.valid for bp in bps)
            assert ('command', 'set breakpoint always-inserted on') in trace
            for site in sites:
                cursor += 1
                registers['pc'] = BASE + PINS['points'][site]['va']
                if site == 'setter_entry':
                    registers.update(x0=pointer, x1=0, x30=BASE+PINS['points']['setter_wrapper_return']['va'])
                elif site == 'setter_wrapper_return':
                    registers['x0'] = pointer
                if failure == 'wrong-asid':
                    # Foreign per-cpu task: same filtering the old TTBR0 check performed.
                    poke(SYMS['__entry_task'], (TASK + 0x40000).to_bytes(8, 'little'))
                bp = next(bp for bp in bps if bp.pc == registers['pc'])
                if bp.stop():
                    trace.append(('model-stopped', site))
                    hook(NS(breakpoints=[bp], stop_signal=None))
                    return ''
            hook(NS(breakpoints=[], stop_signal='SIGINT'))
        return ''
    fake = NS(Breakpoint=BP, BP_HARDWARE_BREAKPOINT=1, execute=execute,
              parameter=lambda name: False, selected_frame=lambda: NS(read_register=reg),
              selected_inferior=lambda: NS(read_memory=read), parse_and_eval=parse_and_eval,
              selected_thread=selected_thread,
              events=NS(stop=NS(connect=connect, disconnect=lambda _: trace.append(('disconnect-hook',)))))
    monkeypatch.setitem(sys.modules, 'gdb', fake)
    monkeypatch.setattr(w, 'retain_model17c_stop', lambda: trace.append(('retain-stopped',)))
    # A foreign pre-existing breakpoint must not be deleted by this owner.
    foreign = BP('*0x1234', 1, True)
    bps.clear()
    if failure == 'gate':
        registers['pc'] += 4
    if failure == 'ttbr':
        # Wrong mm->pgd: derived TTBR0 can no longer match the bound address space.
        poke(MM + 0x40, (PGD + 0x1000).to_bytes(8, 'little'))
    w.gdb_main(path, detached_handoff=detached)
    assert foreign.valid
    result = json.loads((tmp_path / (w.PREFIX+'-result.json')).read_text())
    return result, trace, bps


def test_install_events_cleanup_detach_and_handoff_order(tmp_path, monkeypatch):
    result, trace, bps = run_owner(tmp_path, monkeypatch, sites=(
        'date_gate', 'helper_return', 'setter_entry', 'setter_exit', 'setter_wrapper_return', 'clear_return'))
    assert result['model17c_installed'] == len(PINS['points'])
    assert result['model17c_cleanup'] == dict(deleted=True, pending=0)
    assert result['model17c_counts']['setter_wrapper_return'] == 1
    assert result['detached'] and not result.get('error')
    w.model17c_handoff(result)
    trace.append(('broker-handoff',))
    det = trace.index(('command', 'detach'))
    assert max(i for i, event in enumerate(trace) if event[0] == 'delete') < det
    assert det < trace.index(('broker-handoff',))
    assert all(not bp.valid for bp in bps)
    events = [json.loads(line) for line in (tmp_path/(w.PREFIX+'-events.jsonl')).read_text().splitlines()]
    assert len(events) == 6 and events[-1]['wrapper_return_type'].startswith('void')
    assert events[-2]['original_return_observed'] is True
    assert not any('may-write-memory on' in str(item) or 'set $' in str(item) for item in trace)


def test_detached_handoff_does_not_require_the_old_pre_gate_pc(tmp_path, monkeypatch):
    result, _, _ = run_owner(tmp_path, monkeypatch, detached=True,
                             sites=('date_gate', 'helper_return'))
    assert result['model17c_installed'] == len(PINS['points'])
    assert result['detached'] and not result.get('error')


@pytest.mark.parametrize('failure', ['create', 'pin', 'insert', 'pending', 'gate', 'ttbr', 'register', 'read', 'delete'])
def test_failure_never_resumes_or_hands_off(tmp_path, monkeypatch, failure):
    result, trace, bps = run_owner(tmp_path, monkeypatch, failure)
    assert result['must_remain_stopped'] and not result['detached']
    assert ('command', 'detach') not in trace and trace[-1] == ('retain-stopped',)
    with pytest.raises(ValueError, match='handoff'):
        w.model17c_handoff(result)
    continues = [item for item in trace if item == ('command', 'continue')]
    assert len(continues) == (1 if failure in ('register', 'read', 'delete') else 0)
    if failure != 'delete':
        assert all(not bp.valid for bp in bps)


def test_unpaired_setter_at_window_end_blocks_handoff(tmp_path, monkeypatch):
    result, trace, _ = run_owner(tmp_path, monkeypatch, sites=('setter_entry',))
    assert result['model17c_cleanup']['pending'] == 1 and result['must_remain_stopped']
    assert ('command', 'detach') not in trace


def test_foreign_address_space_events_are_filtered(tmp_path, monkeypatch):
    result, _, _ = run_owner(tmp_path, monkeypatch, 'wrong-asid')
    assert result['model17c_counts'] == {} and result['detached']


@pytest.mark.parametrize('field,value', [('inline_profile', ''), ('base', BASE+4096),
    ('maps', ''), ('profile', 'unknown'), ('ttbr0', 0), ('pid', 1), ('task', 0x1000),
    ('mm', 0x18), ('pgd', PGD+0x18), ('memstart', 0), ('cpu', 64)])
def test_binding_requires_original_actual_mapping(field, value):
    data = binding()
    data[field] = value
    with pytest.raises(ValueError):
        w.model17c_binding(data, None)


def test_actual_original_asset_digest_and_mapping_bind(monkeypatch):
    product = Path(w.__file__).resolve().parent
    if not (product / 'menu-root/usr/lib/appFw.so').exists():
        pytest.skip('Original appFw is not distributed')
    monkeypatch.setattr(w, 'BASE', product)
    result = w.model17c_binding(binding(), None)
    assert result['asset_sha256'] == model.ASSET_SHA256
    assert result['maps_sha256'] == w.hashlib.sha256(binding()['maps'].encode()).hexdigest()


def test_hdmi_receipt_replay_ignores_only_admitted_model_events(tmp_path, monkeypatch):
    info = tmp_path.stat()
    config = dict(run=str(tmp_path), run_device=info.st_dev, run_inode=info.st_ino, limit=w.LIMIT,
                  context=w.context(TEXTS), model17c_runtime=binding())
    (tmp_path/(w.PREFIX+'-config.json')).write_text(json.dumps(config))
    records = [dict(kind='model17c_runtime_observation'), dict(kind='original-kernel-evidence'),
               dict(kind='model17c_setter_filtered'), dict(kind='model17c_observer_error')]
    (tmp_path/(w.PREFIX+'-events.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in records))
    fed = []
    monkeypatch.setattr(w, 'validate_run', lambda _: (tmp_path, info))
    monkeypatch.setattr(w, 'Correlator', lambda *args: NS(context=config['context'], feed=fed.append,
                                                       receipts=['native-receipt']))
    assert w.read_receipts(tmp_path) == ['native-receipt']
    assert fed == [records[1]]


def test_start_forwards_only_explicit_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(w, 'Watch', lambda *args, **kwargs: calls.append((args, kwargs)))
    w.start('run', 123, TEXTS)
    w.start('run', 123, TEXTS, model17c_runtime=binding())
    assert calls[0][1] == {}
    assert calls[1][1] == dict(model17c_runtime=binding())


def test_profile_default_off_and_identity_only_mailbox_binding():
    assert w.model17c_binding(None, {'unrelated': 'legacy'}) is None
    # With a mailbox the binding stays identity-only; gdb_main refuses the
    # model17c observer install for the same config instead.
    assert w.model17c_binding(binding(), {})['maps_sha256']


@pytest.mark.parametrize('damage', ['error', 'must_remain_stopped', 'pending', 'binding'])
def test_actual_runner_handoff_rejects_failed_observer(tmp_path, monkeypatch, damage):
    import functional_camera_runner as runner
    config = dict(model17c_runtime=binding())
    result = dict(model17c_runtime=binding(), detached=True,
                  model17c_cleanup=dict(deleted=True, pending=0))
    if damage == 'pending':
        result['model17c_cleanup']['pending'] = 1
    elif damage == 'binding':
        result['model17c_runtime'] = {}
    else:
        result[damage] = True
    (tmp_path/'hdmi-upm-watch-config.json').write_text(json.dumps(config))
    (tmp_path/'hdmi-upm-watch-result.json').write_text(json.dumps(result))
    monkeypatch.setattr(runner.transport, 'validate_run', lambda _: (tmp_path, tmp_path.stat()))
    monkeypatch.setattr(runner.transport, 'endpoint_roots', lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match='model17c'):
        runner.debugger_handoff(tmp_path, 123)


def test_stop_keeps_failed_live_owner_without_signal_or_reconnect(tmp_path):
    watch = w.Watch.__new__(w.Watch)
    watch.config = dict(model17c_runtime=binding())
    watch.run, watch.cleanup = tmp_path, None
    watch.process = NS(poll=lambda: None)  # Any send_signal/terminate/reconnect would fail.
    (tmp_path/(w.PREFIX+'-result.json')).write_text('{}')
    assert watch.stop()['safe_to_close'] is False


def test_startup_handoff_starts_a_fresh_runtime_gdb_process(tmp_path, monkeypatch):
    import functional_camera_runner as runner
    original = binding()
    validated = dict(original, asset_sha256='asset', maps_sha256='maps')
    stop = dict(schema='a7c2-model17c-startup-stop-v2', handoff='separate-gdb-process-v1',
                early_breakpoints_deleted=True, binding=original, runtime_binding=validated)
    binding_sha = w.hashlib.sha256(json.dumps(validated, sort_keys=True).encode('ascii')).hexdigest()
    result = dict(schema='a7c2-model17c-startup-detached-v1', detached=True,
                  separate_process_handoff=True, early_breakpoints_remaining=[],
                  runtime_binding_sha256=binding_sha)
    (tmp_path/'model17c-startup-stop.json').write_text(json.dumps(stop))
    (tmp_path/'model17c-startup-result.json').write_text(json.dumps(result))
    log = NS(closed=False, close=lambda: setattr(log, 'closed', True))
    early = NS(process=NS(poll=lambda: 0), log=log)
    runtime = NS(config=dict(model17c_runtime=validated))
    calls = []
    monkeypatch.setattr(w, 'model17c_binding', lambda value, mailbox: validated)
    monkeypatch.setattr(w, 'start', lambda *args, **kwargs: calls.append((args, kwargs)) or runtime)
    monkeypatch.setattr(runner, '_publish', lambda root, name, value:
                        (root/name).write_text(json.dumps(value)))
    owner = runner.FunctionalCameraRunner.__new__(runner.FunctionalCameraRunner)
    owner.run, owner.owner, owner.artifact = tmp_path, dict(pid=123), {}
    owner.model17c_startup = dict(module_texts=TEXTS)
    owner.socket_options, owner.hdmi_watch, owner.hdmi_cleanup = {}, early, None
    owner.model17c_handed_off = False
    owner._handoff_model17c_startup()
    assert owner.hdmi_watch is runtime and owner.model17c_handed_off
    assert owner.hdmi_binding == dict(model17c_runtime=validated)
    assert calls[0][1]['model17c_runtime'] == original and log.closed
    assert json.loads((tmp_path/'model17c-startup-coordinator.json').read_text()) == result


def test_startup_handoff_identity_only_defers_runtime_probes(tmp_path, monkeypatch):
    import functional_camera_runner as runner
    original = binding()
    validated = dict(original, asset_sha256='asset', maps_sha256='maps')
    stop = dict(schema='a7c2-model17c-startup-stop-v2', handoff='separate-gdb-process-v1',
                early_breakpoints_deleted=True, binding=original, runtime_binding=validated)
    binding_sha = w.hashlib.sha256(json.dumps(validated, sort_keys=True).encode('ascii')).hexdigest()
    result = dict(schema='a7c2-model17c-startup-detached-v1', detached=True,
                  separate_process_handoff=True, early_breakpoints_remaining=[],
                  runtime_binding_sha256=binding_sha)
    (tmp_path/'model17c-startup-stop.json').write_text(json.dumps(stop))
    (tmp_path/'model17c-startup-result.json').write_text(json.dumps(result))
    log = NS(closed=False, close=lambda: setattr(log, 'closed', True))
    early = NS(process=NS(poll=lambda: 0), log=log)
    monkeypatch.setattr(w, 'model17c_binding', lambda value, mailbox: validated)
    monkeypatch.setattr(w, 'start', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('runtime GDB started')))
    monkeypatch.setattr(runner, '_publish', lambda root, name, value:
                        (root/name).write_text(json.dumps(value)))
    owner = runner.FunctionalCameraRunner.__new__(runner.FunctionalCameraRunner)
    owner.run, owner.owner, owner.artifact = tmp_path, dict(pid=123), {}
    owner.model17c_startup = dict(module_texts=TEXTS)
    owner.socket_options, owner.hdmi_watch, owner.hdmi_cleanup = {}, early, None
    owner.model17c_handed_off = False
    owner.model17c_identity_only = True
    owner._handoff_model17c_startup()
    assert owner.hdmi_watch is None and owner.model17c_identity == original
    assert owner.model17c_startup is None and owner.model17c_handed_off and log.closed


def test_startup_source_cannot_reintroduce_in_process_runtime_recursion():
    source = (Path(w.__file__).parent/'model17c_startup.py').read_text()
    assert 'h.gdb_main(' not in source
    assert "gdb.execute('detach', to_string=True)" in source


def test_arm_publishes_model17c_route_only_after_deadline_and_watch():
    import functional_camera_runner as runner
    source = (Path(runner.__file__).read_text())
    arm = source.split('    def arm_model17c(self, raw):', 1)[1].split('    def _guest_exception_recovery', 1)[0]
    publish = arm.index('self.model17c_startup = startup')
    assert arm.index('self.hdmi_watch = hdmi_upm_watch.start') < publish
    assert arm.index('self.model17c_startup_deadline = time.monotonic() + 900') < publish


def test_receipt_publish_uses_distinct_atomic_tempnames_across_threads(tmp_path, monkeypatch):
    import functional_camera_runner as runner
    import threading
    monkeypatch.setattr(runner.transport, 'validate_run', lambda _: (tmp_path, tmp_path.stat()))
    errors = []
    def writer(number):
        try:
            for index in range(30):
                runner._publish(tmp_path, 'shared.json', dict(writer=number, index=index))
        except BaseException as error:
            errors.append(error)
    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert not errors
    assert json.loads((tmp_path/'shared.json').read_text())['index'] == 29
    assert not list(tmp_path.glob('.shared.json.*.tmp'))
