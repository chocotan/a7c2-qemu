import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import media_initial_write as initial
import request_queue_watch as queue


@pytest.mark.parametrize('baseline,expired', [(0, False), (1, False), (0, True)])
def test_real_watch_callback_records_original_write_and_keeps_initial_boundary(tmp_path, monkeypatch, baseline, expired):
    base = 0x7f00000000
    config = dict(run=str(tmp_path), app_base=base, socket='owned-test', observer_gate_address=0x7e10004000)
    monkeypatch.setattr(queue, 'revalidate_gdb_config',
                        lambda supplied: (os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY), config))
    points, commands = [], []
    values = [baseline]
    pc = [base+0x1000]

    class Watch:
        def __init__(self, expression, type, internal, wp_class=None):
            if type == 7:
                assert expression == '*'+hex(base+0x1796918) and internal
                self.type = 7
            else:
                assert expression == '*((unsigned int*)'+hex(base+0x7e6e7f0)+')'
                assert (type, wp_class, internal) == (6, 2, True)
                self.type = 8
            points.append(self)

        def delete(self):
            commands.append('delete')

    def read(address, size):
        if address == config['observer_gate_address']:
            return (0 if expired else 1).to_bytes(4, 'little')
        if address == base+0x1796918:
            assert pc[0] == address  # never inspect an untouched code page in Linux context
            return bytes.fromhex('fd7bbaa9a31e02d0a2fb00d0')
        assert address == base+0x7e6e7f0 and size == 4
        return values[0].to_bytes(4, 'little')

    def execute(command, to_string):
        commands.append(command)
        if command == 'continue':
            if len(points) == 1:
                pc[0] = base+0x1796918
            else:
                pc[0] = base+0x2773020
                values[0] = 1
                points[-1].stop()

    fake = SimpleNamespace(Breakpoint=Watch, BP_HARDWARE_BREAKPOINT=7, BP_WATCHPOINT=6, WP_WRITE=2, BP_HARDWARE_WATCHPOINT=8,
                           selected_inferior=lambda: SimpleNamespace(read_memory=read),
                           parse_and_eval=lambda name: {'$pc': pc[0], '$x30': base+0x28bb140, '$x29': 0}[name],
                           execute=execute, events=SimpleNamespace(stop=SimpleNamespace(
                               connect=lambda cb: None, disconnect=lambda cb: None)))
    monkeypatch.setitem(sys.modules, 'gdb', fake)
    initial.gdb_main(config)
    result = json.loads((tmp_path/'media-predicate-result.json').read_text())
    if expired:
        assert 'expired' in result['error'] and not points and 'continue' not in commands
        assert commands[-1] == 'detach'
        return
    assert result['initial_value'] == baseline and result['initial_value_already_one'] == bool(baseline)
    assert result['original_init_entry_verified'] is True and len(points) == 2
    assert result['writes'][0]['value'] == 1 and result['writes'][0]['pc_minus_app_base'] == '0x2773020'
    assert result['first_transition_to_1_observed'] is (baseline == 0)
    if baseline == 1:
        # A partial trace is not sufficient to excuse an unrelated stop.
        assert 'Unexpected debugger stop' in result['error']
    else:
        assert result['error'] is None
    assert commands[-2:] == ['delete', 'detach']
    assert not any(c.startswith(('set ', 'call ')) for c in commands)


def test_shutdown_retains_owner_until_debug_cleanup_safe(tmp_path, monkeypatch):
    events = []
    states = iter([{'safe_to_close': False, 'cpu_running_verified': False},
                   {'safe_to_close': True, 'cpu_running_verified': True}])
    watch = SimpleNamespace(stop=lambda: (events.append('stop') or next(states)))
    proc = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(initial.time, 'sleep', lambda seconds: events.append('retain'))
    initial.guard_shutdown(watch, proc, tmp_path)
    assert events == ['stop', 'retain', 'stop']
    assert json.loads((tmp_path/'media-init-shutdown-guard.json').read_text())['safe_to_close']


def test_report_ENOSPC_cannot_bypass_unsafe_retention(tmp_path, monkeypatch):
    events = []
    states = iter([{'safe_to_close': False}, {'safe_to_close': True}])
    watch = SimpleNamespace(stop=lambda: (events.append('stop') or next(states)))
    proc = SimpleNamespace(poll=lambda: None)
    def full(*args, **kwargs):
        raise OSError(28, 'No space left on device')
    monkeypatch.setattr(Path, 'write_text', full)
    monkeypatch.setattr(initial.time, 'sleep', lambda seconds: events.append('retain'))
    initial.guard_shutdown(watch, proc, tmp_path)
    assert events == ['stop', 'retain', 'stop']


def test_actual_qmp_quit_guard_runs_before_wire_even_startup_exception(tmp_path):
    import ast
    source = Path(initial.__file__).parent/'qemu-menu-probe.py'
    tree = ast.parse(source.read_text())
    fn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'qmp')
    events = []
    # Replace the import with a controlled binding but execute the real body.
    # Guard blocks/fails: no quit JSON may be written or flushed.
    fn.body = [node for node in fn.body if not isinstance(node, ast.ImportFrom)]
    class Stream:
        def write(self, data):
            events.append('wire')
        def flush(self):
            events.append('flush')
        def readline(self):
            return b'{"return":{}}'
    from contextlib import nullcontext
    scope = dict(early_media_watch=object(), proc=object(), out=tmp_path,
                 stream=Stream(), json=json, functional_camera=None, nullcontext=nullcontext,
                 host_sd_fd=None, directory_sd_fd=None, host_sd_export_verified=[False])
    import media_initial_write
    original = media_initial_write.guard_shutdown
    def retain(*args):
        events.append('guard')
        raise RuntimeError('retained for test')
    try:
        media_initial_write.guard_shutdown = retain
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(source),'exec'),scope)
        with pytest.raises(RuntimeError, match='retained'):
            scope['qmp']('quit')
        assert events == ['guard']
        events.clear()
        assert scope['qmp']('query-status') == {'return': {}}
        assert events == ['wire', 'flush']
    finally:
        media_initial_write.guard_shutdown = original


def test_both_production_shutdown_paths_guard_before_qemu_stop():
    import ast
    tree = ast.parse((Path(initial.__file__).parent/'qemu-menu-probe.py').read_text())
    guarded = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and node.finalbody:
            body = ast.unparse(ast.Module(body=node.finalbody, type_ignores=[]))
            if "qmp('quit')" in body or 'proc.terminate()' in body:
                assert 'guard_shutdown(early_media_watch, proc, out)' in body
                assert body.index('guard_shutdown(') < min(
                    [body.index(token) for token in ("qmp('quit')", 'proc.terminate()') if token in body])
                guarded += 1
    assert guarded == 2


def test_bounded_debug_delay_is_optin_and_original_init_is_still_called():
    source = (Path(initial.__file__).parent/'menu-observe.c').read_text()
    block = source[source.index('static void *observe_application_init(void *argument) {'):]
    block = block[:block.index('record(result ?')]
    assert 'if (getenv("MENU_MEDIA_INIT_WATCH") && !getenv("MENU_OBSERVE_SELFTEST")' in block
    assert '!(appfw_base & 4095UL)' in block
    assert 'usleep(10000000)' in block
    assert block.count('real_application_init(argument)') == 1
    assert block.index('usleep(10000000)') < block.index('real_application_init(argument)')
