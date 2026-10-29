"""The display switch must not choose the QEMU build.

An isolated USB-Ethernet run names a candidate QEMU build that carries the sysbus
xHCI controller. Before this test the native-window branch overwrote that choice
with the shipped `build-sony-ui`, so `-device usb-net` failed with
"No 'usb-bus' bus found" and the whole network run died at startup.
"""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('menu_control', BASE/'menu_control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
live_spec = importlib.util.spec_from_file_location('menu_live', BASE/'menu_live.py')
live = importlib.util.module_from_spec(live_spec)
live_spec.loader.exec_module(live)

CANDIDATE = '/tmp/candidate/qemu-11.1.2/build'


class IsolatedNetdevSocket(unittest.TestCase):
    def test_alias_keeps_the_socket_path_inside_the_af_unix_limit(self):
        # menu-runs paths are ~155 characters, past the 108-byte sun_path limit;
        # the peer must therefore connect through the short alias.
        with tempfile.TemporaryDirectory() as temporary:
            deep = Path(temporary)/('d'*60)/('e'*60)/'run-abcdefgh'
            deep.mkdir(parents=True)
            socket_path, alias = live.netdev_socket_alias(deep)
            try:
                self.assertGreater(len(str(deep/'ethernet.sock')), 107)
                self.assertLess(len(str(socket_path)), 108)
                self.assertTrue(alias.is_symlink())
                self.assertEqual(socket_path.parent.resolve(), deep.resolve())
            finally:
                alias.unlink(missing_ok=True)

    def test_alias_is_replaced_when_a_stale_one_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            deep = Path(temporary)/'run-zzzzzzzz'
            deep.mkdir()
            socket_path, alias = live.netdev_socket_alias(deep)
            alias.unlink(missing_ok=True)
            second, alias2 = live.netdev_socket_alias(deep)
            try:
                self.assertEqual(str(second), str(socket_path))
                self.assertTrue(alias2.is_symlink())
            finally:
                alias2.unlink(missing_ok=True)


class BackupSaveForwarding(unittest.TestCase):
    """Backup_save is opt-in and must survive both launcher profiles.

    profile_environment() scrubs every MENU_* name, so a flag missing from both
    whitelists silently disables the experiment; that has happened three times.
    """

    def test_natural_and_non_natural_profiles_both_forward_the_flag(self):
        for natural in (True, False):
            forwarded = control.launcher.profile_environment(
                {'MENU_BACKUP_SAVE': '1'}, natural_boot=natural)
            self.assertEqual(forwarded.get('MENU_BACKUP_SAVE'), '1', natural)

    def test_flag_stays_absent_when_not_requested(self):
        for natural in (True, False):
            forwarded = control.launcher.profile_environment({}, natural_boot=natural)
            self.assertNotIn('MENU_BACKUP_SAVE', forwarded, natural)


class WifiCommand(unittest.TestCase):
    def _vm(self, usb_net):
        vm = control.VM(usb_net=usb_net)
        vm.state = 'running'
        return vm

    def test_wifi_is_refused_when_this_run_has_no_isolated_network(self):
        with self.assertRaises(ValueError):
            self._vm(False).enqueue({'action': 'wifi', 'enabled': True})

    def test_wifi_needs_a_real_boolean_not_an_int_or_string(self):
        for value in (1, 0, 'true', None, 'false'):
            with self.assertRaises(ValueError):
                self._vm(True).enqueue({'action': 'wifi', 'enabled': value})

    def test_wifi_is_queued_unchanged_when_enabled(self):
        vm = self._vm(True)
        vm.enqueue({'action': 'wifi', 'enabled': False})
        self.assertEqual(vm.commands.get_nowait(), {'action': 'wifi', 'enabled': False})


class NativeDisplayEnvironment(unittest.TestCase):
    def test_explicit_candidate_build_survives_the_display_switch(self):
        env = {'QEMU_SYSTEM_DIR': CANDIDATE}
        control.native_display_environment(env, 'gtk')
        self.assertEqual(env['QEMU_SYSTEM_DIR'], CANDIDATE)
        self.assertEqual(env['MENU_NATIVE_WINDOW'], '1')
        self.assertEqual(env['QEMU_NATIVE_DISPLAY'], 'gtk')
        self.assertEqual(env['QEMU_NATIVE_INPUT'], '1')

    def test_default_build_is_used_when_no_candidate_is_named(self):
        env = control.native_display_environment({}, 'gtk')
        self.assertTrue(env['QEMU_SYSTEM_DIR'].endswith('sources/qemu-11.1.2/build-sony-ui'))

    def test_candidate_named_for_usb_net_reaches_the_display_branch_intact(self):
        # The launcher forwards the candidate only in the isolated-USB profile;
        # the display branch must then keep that exact path.
        forwarded = control.launcher.profile_environment(
            {'MENU_USB_NET': '1', 'QEMU_SYSTEM_DIR': CANDIDATE,
             'QEMU_SYSTEM_BINARY': 'qemu-system-aarch64'}, natural_boot=True)
        self.assertEqual(forwarded['QEMU_SYSTEM_DIR'], CANDIDATE)
        control.native_display_environment(forwarded, 'gtk')
        self.assertEqual(forwarded['QEMU_SYSTEM_DIR'], CANDIDATE)

    def test_usb_profile_without_a_candidate_still_gets_the_shipped_build(self):
        forwarded = control.launcher.profile_environment({'MENU_USB_NET': '1'}, natural_boot=True)
        control.native_display_environment(forwarded, 'gtk')
        self.assertTrue(forwarded['QEMU_SYSTEM_DIR'].endswith('sources/qemu-11.1.2/build-sony-ui'))


class FunctionalShutdown(unittest.TestCase):
    def test_wait_only_never_terminates_or_kills_a_live_owner(self):
        process = mock.Mock(pid=456)
        process.wait.side_effect = subprocess.TimeoutExpired('functional-owner', 65)
        with mock.patch.object(control.os, 'killpg') as signal_group:
            with self.assertRaises(subprocess.TimeoutExpired):
                control.wait_functional_camera_owner(process)
        signal_group.assert_not_called()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_group_must_really_be_gone_after_owner_exit(self):
        process = mock.Mock(pid=456)
        with mock.patch.object(control.os, 'killpg') as signal_group:
            with self.assertRaisesRegex(RuntimeError, '进程组尚未退出'):
                control.wait_functional_camera_owner(process)
        signal_group.assert_called_once_with(456, 0)
        with mock.patch.object(control.os, 'killpg', side_effect=ProcessLookupError):
            control.wait_functional_camera_owner(process)
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_functional_startup_cancel_queues_save_and_keeps_control_channel(self):
        vm = control.VM(natural_boot=True)
        vm.functional_camera = True
        vm.state = 'starting'
        vm.stop()
        self.assertEqual(vm.state, 'stopping')
        self.assertEqual(vm.commands.get_nowait(), {'action':'export_sd', '_shutdown':True})
        self.assertFalse(vm.cancel.is_set())
        vm.stop()
        self.assertTrue(vm.commands.empty())
        vm.functional_camera = False
        vm.state = 'starting'
        vm.stop()
        self.assertTrue(vm.cancel.is_set())

    def test_actual_capture_guard_refuses_shutdown_without_export_or_channel_teardown(self):
        vm = control.VM(natural_boot=True)
        vm.functional_camera = True
        vm.state = 'running'
        vm.stop()
        command = vm.commands.get_nowait()
        shutdown = command.pop('_shutdown')
        tree = ast.parse((BASE/'menu_control.py').read_text())
        run = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_run')
        loop = next(node for node in ast.walk(run) if isinstance(node, ast.While) and
                    any(isinstance(item, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'saving'
                        for target in item.targets) for item in node.body))
        start = next(index for index, node in enumerate(loop.body) if isinstance(node, ast.Assign) and
                     any(isinstance(target, ast.Name) and target.id == 'saving' for target in node.targets))
        dispatch = loop.body[start:start+4]
        finish = next(node for node in ast.walk(loop) if isinstance(node, ast.If) and
                      isinstance(node.test, ast.Name) and node.test.id == 'shutdown')
        parent, send, receive = mock.Mock(), mock.Mock(), mock.Mock()
        scope = dict(vars(control), self=vm, command=command, shutdown=shutdown, parent=parent,
                     send_message=send, receive_message=receive, cancelled=lambda:False)
        with mock.patch('functional_camera_runner.require_capture_closed', side_effect=ValueError('Original clip Close is pending')):
            exec(compile(ast.Module(body=dispatch + [finish], type_ignores=[]), '<actual-controller-close-guard>', 'exec'), scope)
        send.assert_not_called()
        receive.assert_not_called()
        parent.close.assert_not_called()
        self.assertEqual(vm.state, 'running')
        self.assertFalse(vm.cancel.is_set())
        self.assertTrue(vm.shutdown_done.is_set())
        self.assertIn('Close is pending', vm.error)

    def test_functional_retry_retains_instance_and_disk_leases_without_group_term(self):
        vm = control.VM(natural_boot=True)
        vm.functional_camera = True
        vm.cleanup_error = 'broker still running'
        vm.cancel.set()
        vm.owned_process = mock.Mock(pid=456)
        vm.host_sd_context = mock.MagicMock()
        vm.instance_lease = mock.MagicMock()
        with mock.patch.object(control.os, 'killpg') as group, mock.patch.object(control, 'wait_functional_camera_owner',
                side_effect=subprocess.TimeoutExpired('functional-owner', 65)), mock.patch.object(control, 'terminate_owned') as terminate:
            with self.assertRaisesRegex(RuntimeError, '仍失败'):
                vm.close()
        group.assert_not_called()
        terminate.assert_not_called()
        vm.instance_lease.__exit__.assert_not_called()
        vm.host_sd_context.__exit__.assert_not_called()
        self.assertIsNotNone(vm.instance_lease)
        self.assertIsNotNone(vm.host_sd_context)
        self.assertIsNotNone(vm.owned_process)

    def test_functional_early_startup_failures_keep_owner_without_legacy_signals(self):
        failures = (
            RuntimeError('VM 控制通道已关闭'),
            {'type':'error', 'error':'guest exception monitor during settle'},
            {'type':'ready', 'run':'/invalid-functional-run'},
        )
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                vm = control.VM(natural_boot=True)
                vm.state = 'starting'
                process = mock.Mock(pid=456)
                process.poll.return_value = None
                process.wait.side_effect = subprocess.TimeoutExpired('functional-owner', 65)
                received = ({'side_effect':failure} if isinstance(failure, Exception)
                            else {'return_value':failure})
                with mock.patch.object(control, 'BASE', base), \
                        mock.patch.object(control.launcher, 'profile_environment', return_value={
                            'A7C2_FUNCTIONAL_CAMERA':'virtual-functional-camera-v1'}), \
                        mock.patch.object(control.subprocess, 'Popen', return_value=process), \
                        mock.patch.object(control, 'receive_message', **received), \
                        mock.patch.object(control.os, 'killpg') as group, \
                        mock.patch.object(control, 'terminate_owned') as terminate, \
                        mock.patch.object(control, 'terminate_host_disk_owner') as terminate_disk:
                    vm._run()
                    self.assertTrue(vm.functional_camera)
                    self.assertEqual(vm.state, 'error')
                    self.assertIs(vm.owned_process, process)
                    self.assertTrue(vm.cleanup_error)
                    self.assertFalse(vm.cancel.is_set())
                    self.assertFalse(vm.status()['can_start'])
                    self.assertTrue(Path(vm.log_path).is_file())
                    process.wait.assert_called_once_with(timeout=65)
                    group.assert_not_called()
                    terminate.assert_not_called()
                    terminate_disk.assert_not_called()
                    process.terminate.assert_not_called()
                    process.kill.assert_not_called()
                    self.assertTrue(any('VM 错误：' in event['message'] for event in vm.events))

    def test_functional_early_eof_keeps_unsaved_disk_and_instance_until_actual_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            vm = control.VM(natural_boot=True)
            vm.state = 'starting'
            vm.host_sd_context = mock.MagicMock()
            vm.host_sd_lease = {}
            vm.instance_lease = mock.MagicMock()
            vm._release_instance_lease = mock.Mock(wraps=vm._release_instance_lease)
            vm._release_host_sd_lease = mock.Mock(wraps=vm._release_host_sd_lease)
            process = mock.Mock(pid=456)
            process.poll.return_value = None
            with mock.patch.object(control, 'BASE', base), \
                    mock.patch.object(control.launcher, 'profile_environment', return_value={
                        'A7C2_FUNCTIONAL_CAMERA':'virtual-functional-camera-v1'}), \
                    mock.patch.object(control.subprocess, 'Popen', return_value=process), \
                    mock.patch.object(control, 'receive_message', side_effect=RuntimeError('VM 控制通道已关闭')), \
                    mock.patch('settings_instance.load_for_boot', return_value={'generation':None, 'state':'empty'}), \
                    mock.patch.object(control.os, 'killpg') as group, \
                    mock.patch.object(control, 'terminate_owned') as terminate, \
                    mock.patch.object(control, 'terminate_host_disk_owner') as terminate_disk:
                vm._run()
                self.assertEqual(vm.state, 'error')
                self.assertIn('未完成保存', vm.cleanup_error)
                self.assertIs(vm.owned_process, process)
                self.assertFalse(vm.cancel.is_set())
                self.assertFalse(vm.status()['can_start'])
                self.assertTrue(Path(vm.log_path).is_file())
                vm._release_instance_lease.assert_not_called()
                vm._release_host_sd_lease.assert_not_called()
                process.wait.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, '宿主磁盘尚未通过保存'):
                    vm.close()
                self.assertIsNotNone(vm.host_sd_context)
                self.assertIsNotNone(vm.instance_lease)
                self.assertIsNone(vm.sd_export)
                process.poll.return_value = 1
                with mock.patch.object(control.os, 'killpg', side_effect=ProcessLookupError):
                    vm.close()
                process.wait.assert_called_once_with(timeout=65)
                self.assertIsNone(vm.owned_process)
                self.assertIsNone(vm.host_sd_context)
                self.assertIsNone(vm.instance_lease)
                self.assertIsNone(vm.sd_export)
                group.assert_not_called()
                terminate.assert_not_called()
                terminate_disk.assert_not_called()
                process.terminate.assert_not_called()
                process.kill.assert_not_called()

    def test_actual_controller_eof_waits_for_broker_guard_before_owned_vm_quit(self):
        # A Python signal recipient stands in for QEMU; the controller, socket loop and runner guard are real.
        script = r'''
import ast, json, os, signal, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import functional_camera_runner as runner
import menu_live
run = Path(sys.argv[2])
runner.transport.RUNS = run.parent
safe = dict.fromkeys(runner.CLOSE_FIELDS, True)
safe['errors'] = []
def record(event):
    with (run/'order.jsonl').open('a') as stream: stream.write(json.dumps(event)+'\n')
child = subprocess.Popen([sys.executable, '-u', '-c',
    'import signal,sys; print("ready", flush=True); signal.signal(signal.SIGTERM, lambda *_: sys.exit(0)); signal.pause()'], stdout=subprocess.PIPE)
child.stdout.readline()
child.stdout.close()
instance = runner.FunctionalCameraRunner(run, {'library':'host-double'})
mailbox = dict(phys0=0x410000000, nonce=41251, pid=123, pages=[0x410000000+4096*n for n in range(16)])
instance.binding = {'mailbox':mailbox}
identity = runner.transport.process_identity(child.pid)
instance.handoff = {'qemu_identity':identity}
instance.proc = child
receipts = []
def emit(kind, **fields):
    receipts.append(dict(kind=kind, event=len(receipts)+1, model_instance=mailbox['nonce'], **fields))
    (run/(runner.transport.PREFIX+'-receipts.jsonl')).write_text(''.join(json.dumps(e)+'\n' for e in receipts))
    (run/(runner.transport.PREFIX+'-receipts.jsonl')).chmod(0o600)
emit('binding', mailbox=mailbox, config={'owner':instance.owner, 'qemu':identity})
emit('attached')
class Broker:
    start_error = None
    def stop(self):
        assert child.poll() is None, 'guest exited before broker cleanup'
        record('broker-stop-alive')
        emit('detach_commit', model_work_stopped=True, no_further_ram_after_ack=True)
        emit('mailbox_detached', cleanup_detach=True, protocol_physmode_restored=True)
        emit('debugger_disconnected', detached=True, protocol_physmode_restored=True)
        emit('cleanup', **safe)
        return safe
instance.broker = Broker()
functional_camera = instance
functional_camera_profile = runner.FUNCTIONAL_CAMERA_PROFILE
resize_mmio_watch = False
probe = ast.parse((Path(sys.argv[1])/'qemu-menu-probe.py').read_text())
term_guard = next(node for node in probe.body if isinstance(node, ast.If) and
    any(isinstance(item, ast.FunctionDef) and item.name=='stop_live' for item in node.body))
exec(compile(ast.Module(body=[term_guard], type_ignores=[]), '<actual-launcher-term>', 'exec'))
finalbody = next(node.finalbody for node in ast.walk(probe) if isinstance(node, ast.Try) and node.finalbody and
    any(isinstance(call, ast.Call) and ast.unparse(call.func)=='functional_camera.guard_shutdown' for call in ast.walk(node.finalbody[0])) and
    any(isinstance(call, ast.Call) and ast.unparse(call.func)=='proc.kill' for item in node.finalbody for call in ast.walk(item)))
def qmp(name):
    assert name=='quit' and instance.closed and instance.cleanup['safe_to_close']
    record('quit-after-cleanup')
    child.terminate()
def export():
    assert child.poll() is None and not instance.closed
    record('export-while-active')
    return {'ok':True}
proc, out = child, run
early_media_watch, host_sd_fd, directory_sd_fd, host_sd_export_verified = None, None, 40, [True]
menu_live.serial_command = lambda *args, **kwargs: b''
os.environ['MENU_LIVE_KEY_FILE'] = 'host-double'
try:
    try:
        menu_live.run_live(child, run, int(os.environ['MENU_CONTROL_FD']), sd_export=export)
    except RuntimeError as error:
        assert str(error)=='VM 控制通道已关闭', str(error)
        record('control-eof')
finally:
    exec(compile(ast.Module(body=finalbody, type_ignores=[]), '<actual-launcher-finally>', 'exec'))
record('launcher-exited')
'''
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            run = base/'menu-runs/run-fixture'
            run.mkdir(parents=True)
            (run/'runtime-manifest.json').write_text('{}')
            (run/'console.log').write_text('')
            vm = control.VM([sys.executable, '-u', '-c', script, str(BASE), str(run)], natural_boot=True, native_display='none')
            vm.mock = False
            env = {**os.environ, 'A7C2_FUNCTIONAL_CAMERA':'virtual-functional-camera-v1'}
            with mock.patch.object(control, 'BASE', base), mock.patch.object(control.launcher, 'profile_environment', return_value=env), \
                    mock.patch.object(control.os, 'killpg', wraps=os.killpg) as group, \
                    mock.patch.object(control, 'terminate_host_disk_owner', side_effect=AssertionError('may not broadcast TERM')), \
                    mock.patch.object(control, 'terminate_owned', side_effect=AssertionError('may not broadcast TERM/KILL')):
                vm.start()
                deadline = time.monotonic()+5
                while vm.state == 'starting' and time.monotonic()<deadline: time.sleep(.01)
                self.assertEqual(vm.state, 'running', vm.error)
                vm.close()
                self.assertEqual(vm.state, 'exited', vm.error)
                self.assertFalse(vm.thread.is_alive())
                self.assertIsNone(vm.owned_process)
                self.assertTrue(all(call.args[1] == 0 for call in group.call_args_list))
            self.assertEqual([json.loads(line) for line in (run/'order.jsonl').read_text().splitlines()],
                             ['export-while-active', 'control-eof', 'broker-stop-alive', 'quit-after-cleanup', 'launcher-exited'])
            final = json.loads((run/'functional-camera-runner.json').read_text())
            self.assertEqual(final['phase'], 'closed')
            self.assertTrue(final['cleanup']['mailbox_detached'])
            self.assertFalse(final['capture_verified'])


if __name__ == '__main__':
    unittest.main()
