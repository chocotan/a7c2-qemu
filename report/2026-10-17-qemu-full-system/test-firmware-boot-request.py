#!/usr/bin/env python3
"""Controlled cold-controller tests: real private files/disk lease, no VM/process."""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'firmware-boot-request.py'))
DEV = API['DEV']
DISK = runpy.run_path(str(HERE / 'camera-disk.py'))
EXEC = runpy.run_path(str(HERE / 'boot-execution.py'))
LIVE = runpy.run_path(str(HERE / 'retained-camera-live.py'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModuleCapabilityTests(unittest.TestCase):
    def test_fixed_module_identity_is_checked_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'module.ko';path.write_bytes(b'guest-module')
            binding={'path':str(path),'sha256':digest(path)}
            context={'available_capabilities':{'cold':{'persistent_module':binding}}}
            self.assertEqual(API['selected_module'](context),{'path':path,'sha256':binding['sha256']})
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'differs'):API['selected_module'](context)
            binding['sha256']='unknown'
            with self.assertRaisesRegex(ValueError,'path/SHA256'):API['selected_module'](context)
            self.assertIsNone(API['selected_module']({}))


class ColdRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='firmware-cold-request-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir(mode=0o700)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        (self.runtime / 'analysis').mkdir(mode=0o700)
        self.instance_dir = self.root / 'instance'
        self.instance_dir.mkdir(mode=0o700)
        self.disk = self.instance_dir / 'camera.emmc'
        self.disk.write_bytes(b'82462.00' + b'\x00' * (16384 - 8))
        self.disk.chmod(0o600)
        lock = self.instance_dir / '.disk.lock'
        lock.touch(mode=0o600)
        parts = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 15, 18, 22, 23, 30)
        self.geometry = {'schema': DISK['SCHEMA'], 'backing_file': 'camera.emmc', 'backing_bytes': 16384,
                         'user_bytes': 8192, 'partition_rows': [{'part': p, 'bytes': 512} for p in parts]}
        DEV['write_json'](self.instance_dir / 'geometry.json', self.geometry)
        self.state = {'schema': DISK['SCHEMA'], 'generation': 7,
                      'geometry_sha256': digest(self.instance_dir / 'geometry.json'),
                      'source_class': 'official-bodydata-derived', 'source_manifest_sha256': 'a' * 64}
        DEV['write_json'](self.instance_dir / 'instance.json', self.state)
        info = self.disk.stat()
        self.identity = {'id': 'controlled-local-instance', 'generation': 7, 'manifest': str(self.instance_dir / 'instance.json'),
                         'disk': str(self.disk), 'dev': info.st_dev, 'ino': info.st_ino, 'bytes': info.st_size,
                         'geometry_sha256': self.state['geometry_sha256']}
        self.build_dir = self.root / 'production/build'
        self.build_dir.mkdir(parents=True)
        (self.build_dir / 'qemu-system-aarch64').write_text('controlled fixture; never executed')
        (self.build_dir.parent / 'qemu-result.json').write_text('{}')
        self.context_path = self.root / 'context.json'
        self.context = {'schema': DEV['CONTEXT_SCHEMA'], 'runtime': str(self.runtime), 'workspace': str(self.workspace),
                        'instance_identity': self.identity, 'routes': {'root': copy.deepcopy(self.identity), 'bodydata': copy.deepcopy(self.identity)},
                        'available_capabilities': {'cold': {'available': True, 'contract': DEV['SCHEMA'],
                            'instance_identity': copy.deepcopy(self.identity), 'camera_profile': 'virtual-functional-camera-v1',
                            'qemu_build': str(self.build_dir)}}}
        self.save_context()
        args = type('Args', (), {'action': 'cold', 'profile': 'official'})()
        self.job, _ = DEV['new_job'](self.context, args)
        self.request = {'schema': DEV['SCHEMA'], 'job_id': self.job.name, 'run_id': self.job.name,
                        'action': 'cold', 'target': 'cold', 'context_path': str(self.context_path),
                        'runtime': str(self.runtime), 'workspace': str(self.workspace), 'instance_identity': self.identity,
                        'output_dir': str(self.job), 'controller_result': str(self.job / 'controller-result.json'),
                        'required_stages': list(DEV['STAGES']['cold']), 'profile': 'official',
                        'boot_profile': 'original-init-cold', 'controller': str(HERE / 'boot-session.py'),
                        'signature_policy': 'verify-official', 'virtual_dev_update': False,
                        'cold_fallback_allowed': False, 'host_functional_fallback_allowed': False, 'source_mutation_allowed': False}
        self.request_path = self.job / 'request.json'
        self.save_request()
        self.calls = []
        self.active = False
        self.variant = ''
        self.prepare_hook = None
        self.launch_hook = None
        self.executor_hook = None
        self.persistent = {'DISK': DISK, 'prepare_launch': self.prepare_launch, 'leased_launch': self.leased_launch}

    def save_context(self):
        DEV['write_json'](self.context_path, self.context)

    def save_request(self):
        DEV['write_json'](self.request_path, self.request)

    def load_core(self, path):
        name = Path(path).name
        if name == 'persistent-boot.py':
            return self.persistent
        if name == 'boot-session.py':
            return {'prepare': self.prepare}
        if name == 'boot-execution.py':
            return dict(EXEC, run=self.run_executor)
        self.fail('Unexpected code load: ' + str(path))

    def execute(self):
        with patch.object(API['execute'].__globals__['runpy'], 'run_path', side_effect=self.load_core):
            return API['execute'](self.request_path)

    def prepare(self, args):
        self.calls.append('prepare')
        self.assertEqual(args.instance, self.instance_dir)
        self.assertEqual(args.runtime, self.runtime)
        self.assertEqual(args.output, self.job / 'cold-session')
        self.assertEqual(args.profile, 'original-init-cold')
        self.assertEqual(args.camera_profile, 'virtual-functional-camera-v1')
        self.assertEqual(args.seconds, 120)
        self.assertIsNone(args.dump)
        self.assertFalse(args.functional_install)
        args.output.mkdir(mode=0o700)
        caps = {'pnflasha': self.geometry['user_bytes'] // 512,
                **{'cnflasha' + str(r['part']): r['bytes'] // 512 for r in self.geometry['partition_rows']},
                'nflashaB0': 8192, 'nflashaB1': 8192}
        self.cold = {'instance': str(self.instance_dir), 'instance_generation': 7, 'instance_geometry': self.geometry,
                     'instance_source_manifest_sha256': 'a' * 64, 'source': 'official-bodydata-derived',
                     'partition_images_in_ram0': 0, 'build_verified': True, 'capacity_checks': caps,
                     'ram0_sha256': 'b' * 64, 'script_identity': {'original': 'scripts'}}
        if self.prepare_hook:
            self.prepare_hook()
        return args.output, {'state': 'prepared', 'runtime': str(self.runtime),
                             'backend': 'original-init-with-persistent-device', 'cold_chain': self.cold}

    def prepare_launch(self, analysis, cold, output, **options):
        self.calls.append('prepare-launch')
        self.assertEqual(analysis, self.runtime / 'analysis')
        self.assertEqual(cold, self.cold)
        self.assertEqual(options, {'camera_profile': 'virtual-functional-camera-v1', 'qemu_build': self.build_dir})
        output.mkdir(mode=0o700)
        (output / 'run').mkdir(mode=0o700)
        script = output / 'launch.sh'
        script.write_text('# controlled script; never executed\n')
        self.launch = {'instance': str(self.instance_dir), 'script': str(script), 'script_sha256': digest(script),
                       'dtb_sha256': 'c' * 64, 'cmdline': 'root=/dev/ram0 persistent.profile=persistent-flash-cold-v1',
                       'env': {}}
        if self.launch_hook:
            self.launch_hook()
        return self.launch

    @contextmanager
    def leased_launch(self, launch):
        self.calls.append('lease-enter')
        with DISK['lease'](self.instance_dir) as leased:
            info = os.fstat(leased['fd'])
            env = {'PERSISTENT_INSTANCE': str(self.instance_dir), 'PERSISTENT_DISK_FD': str(leased['fd']),
                   'PERSISTENT_DISK_DEV': str(info.st_dev), 'PERSISTENT_DISK_INO': str(info.st_ino)}
            bound = dict(launch, fd=leased['fd'], pass_fds=(leased['fd'],), env=env, children=[])
            if self.variant == 'wrong-fd-env':
                bound['env']['PERSISTENT_DISK_INO'] = '0'
            self.active = True
            try:
                yield bound
            finally:
                self.active = False
                self.calls.append('lease-exit')

    def console_text(self):
        text = ('Linux version controlled-original-kernel\n'
                'COLD_KERNEL_CMDLINE_BEGIN\n' + self.launch['cmdline'] + '\nCOLD_KERNEL_CMDLINE_END\n'
                'PERSISTENT_FLASH_INSMOD rc=0\n'
                'sony_persistent_flash: real durable MMIO DMA, major=245 slices=19 base=0xb000000\n')
        for node, sectors in self.cold['capacity_checks'].items():
            actual = sectors + 1 if self.variant == 'capacity' and node == 'cnflasha7' else sectors
            text += f'PERSISTENT_CAPACITY node={node} expected={sectors} actual={actual}\n'
        text += ('COLD_BEFORE_ORIGINAL_INIT\n+ . /sbin/initrc/setup_rootfs\n'
                 '+ /sbin/pivot_root . /rootfs/initrd\n+ exec busybox chroot . /bin/ash\n'
                 'COLD_INIT2_PROCESS parent=12\n/bin/busybox\x00sh\x00/sbin/init2\x00\n'
                 'COLD_OLD_INITRD_PATH_ABSENT=0\nCOLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512\n'
                 'COLD_NATIVE_BOOTIN pid=42 sha256=' + EXEC['BOOTIN_SHA256'] + '\n'
                 'COLD_EXPECTED_IM version=' + EXEC['IM_VERSION'] + ' sha256=' + EXEC['IM_SHA256'] + '\n'
                 'COLD_PROCESS pid=42 exe=/usr/bin/im.elf\n'
                 'SHA256(/proc/42/exe)= ' + EXEC['IM_SHA256'] + '\n'
                 'COLD_NATIVE_IM pid=42 exe=/usr/bin/im.elf sha256=' + EXEC['IM_SHA256'] + '\n'
                 'COLD_EXECUTABLE=/usr/bin/im.elf\n')
        for i, (target, fs, part) in enumerate([('/', 'ext2', 7), ('/setting', 'vfat', 1), ('/system', 'vfat', 2),
                ('/cp', 'vfat', 8), ('/log', 'vfat', 11), ('/cert', 'vfat', 12), ('/lens', 'vfat', 18),
                ('/tmp', 'vfat', 10), ('/etc', 'vfat', 10), ('/var', 'vfat', 10), ('/usr', 'ext2', 15)], 100):
            opts = 'ro' if target in ('/', '/usr') else 'rw'
            major = 7 if self.variant == 'loop-root' and target == '/' else 245
            text += f'{i} 1 {major}:{128 + part} / {target} {opts} - {fs} /dev/nflasha{part} {opts}\n'
        if self.variant != 'ap-false':
            text += ('COLD_AP_MAP pid=42 sha256=' + EXEC['APPFW_SHA256'] + '\n'
                     'OBS OBSERVER_READY pid=42 base=0x7f12340000 mode=original\n'
                     'OBS CREATE_SCREEN_ARGS call=4 id=0 count=565 orientation=0\n'
                     'OBS OSD_HEADLESS_PERSISTED seq=8 pixel_source_seq=7 id=0x2 phys=0x410000000 '
                     'geometry=640x480 bytes=614400 fnv1a64=0011223344556677 mode=AP-RGBA4444-experimental '
                     'path=/dev/qemu-simulation/headless-osd-frame.bin\n')
        if self.variant == 'source-epoch':
            text = text.replace('pixel_source_seq=7', 'pixel_source_seq=0')
        if self.variant == 'wrong-screen':
            text = text.replace(' id=0 count=565 ', ' id=12 count=565 ')
        return text

    def run_executor(self, bound, cold, output, *, seconds):
        self.calls.append('execute')
        self.assertTrue(self.active)
        self.assertEqual(os.fstat(bound['fd']).st_ino, self.identity['ino'])
        self.assertEqual(bound['instance'], str(self.instance_dir))
        self.assertEqual(seconds, 120)
        output.mkdir(mode=0o700)
        console = output / 'console.log'
        console.write_text(self.console_text())
        receipt = EXEC['new_receipt']('original-init-cold', bindings={
            'run': output.name, 'source_class': cold['source'], 'ram0_sha256': cold['ram0_sha256'],
            'script_identity': cold['script_identity'], 'launch_script_sha256': bound['script_sha256'],
            'dtb_sha256': bound['dtb_sha256']}, kernel_cmdline=bound['cmdline'])
        coverage = EXEC['collect'](console, receipt)
        owner = {'qmp_quit_confirmed': True, 'qmp_quit_attempted': True, 'signals_sent': [], 'returncode': 0,
                 'process_still_running': False, 'owner_pid': 123}
        if self.variant == 'owner-retained':
            owner.update(process_still_running=True, returncode=None, qmp_quit_confirmed=False)
        if self.variant == 'owner-signaled':
            owner['signals_sent'] = ['SIGTERM']
        if self.variant == 'owner-nonzero':
            owner['returncode'] = 17
        pixels = b'\x00\x00\x00' * (640 * 480)
        if self.variant != 'uniform':
            pixels = b'\xFF\xFF\xFF' + pixels[3:]
        if self.variant == 'truncated-lcd':
            pixels = pixels[:-1]
        ppm = self.job / 'cold-session/launch/run/cold-display.ppm'
        ppm.write_bytes(b'P6\n640 480\n255\n' + pixels)
        if self.variant == 'external-evidence':
            outsider = self.root / 'external-console.log'
            outsider.write_text('external')
            receipt['stages'][0]['evidence']['artifacts'] = [{'path': str(outsider), 'sha256': digest(outsider)}]
        result = {'receipt': receipt, 'coverage': coverage, **coverage, 'owner': owner, 'guest_started': True}
        if self.variant == 'executor-failure':
            result.update(error='OriginalGuestError: rc=23 initial failure preserved')
            owner['returncode'] = 23
        EXEC['save'](output / 'owner-exit.json', owner)
        EXEC['save'](output / 'boot-flow.json', result)
        if self.executor_hook:
            self.executor_hook()
        if self.variant == 'executor-failure':
            raise RuntimeError('Cold boot failed; original error in boot-flow.json')
        return result

    def assert_blocked(self, result, code):
        self.assertEqual(result['status'], 'blocked', result)
        self.assertEqual(result['blocked_reason']['code'], code, result)

    def test_same_bound_instance_executes_inside_native_lease_and_receipt_verifies(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(self.calls, ['prepare', 'prepare-launch', 'lease-enter', 'execute', 'lease-exit'])
        self.assertEqual(DEV['read_json'](self.job / 'controller-result.json'), result)
        DEV['verified_receipt'](result, self.request, self.job, 0)
        for stage in result['stages'].values():
            self.assertTrue(stage['verified'])
            path = Path(stage['path'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(digest(path), stage['sha256'])
        for path in (self.job / 'stage-evidence').iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertFalse(result['hot_verified'])
        self.assertFalse(result['update_verified'])

    def test_runtime_ap_false_does_not_complete(self):
        self.variant = 'ap-false'
        result = self.execute()
        self.assert_blocked(result, 'true_required_stage_unverified')
        self.assertFalse(result['stages']['system_runtime']['verified'])

    def test_uniform_lcd_does_not_complete(self):
        self.variant = 'uniform'
        result = self.execute()
        self.assert_blocked(result, 'true_required_stage_unverified')
        self.assertFalse(result['stages']['system_runtime']['verified'])

    def test_truncated_lcd_does_not_complete(self):
        self.variant = 'truncated-lcd'
        self.assert_blocked(self.execute(), 'true_required_stage_unverified')

    def test_wrong_original_screen_and_missing_source_epoch_rejected(self):
        self.variant = 'source-epoch'
        result = self.execute()
        self.assert_blocked(result, 'true_required_stage_unverified')
        self.assertFalse(result['stages']['system_runtime']['verified'])

    def test_original_screen_is_required_even_with_nonuniform_pixels(self):
        self.variant = 'wrong-screen'
        self.assert_blocked(self.execute(), 'true_required_stage_unverified')

    def test_owner_retained_never_completes(self):
        self.variant = 'owner-retained'
        result = self.execute()
        self.assert_blocked(result, 'true_required_stage_unverified')
        self.assertIsNone(result['execution']['owner']['returncode'])

    def test_capacities_must_all_match(self):
        self.variant = 'capacity'
        result = self.execute()
        self.assert_blocked(result, 'true_required_stage_unverified')
        self.assertFalse(result['stages']['persistent_device']['verified'])

    def test_guest_root_major_must_match_persistent_module(self):
        self.variant = 'loop-root'
        result = self.execute()
        self.assert_blocked(result, 'true_required_stage_unverified')
        self.assertFalse(result['stages']['persistent_device']['verified'])

    def test_fd_environment_identity_is_rechecked_inside_lease(self):
        self.variant = 'wrong-fd-env'
        self.assert_blocked(self.execute(), 'lease_binding')
        self.assertNotIn('execute', self.calls)

    def test_request_identity_route_or_generation_changes_rejected(self):
        self.context['routes']['bodydata']['generation'] += 1
        self.save_context()
        self.assert_blocked(self.execute(), 'route_instance_mismatch')
        self.assertEqual(self.calls, [])

    def test_nonzero_owner_does_not_complete(self):
        self.variant = 'owner-nonzero'
        self.assert_blocked(self.execute(), 'true_required_stage_unverified')

    def test_signaled_owner_does_not_complete(self):
        self.variant = 'owner-signaled'
        self.assert_blocked(self.execute(), 'true_required_stage_unverified')

    def test_actual_manifest_generation_rebound(self):
        self.state['generation'] += 1
        DEV['write_json'](self.instance_dir / 'instance.json', self.state)
        self.assert_blocked(self.execute(), 'instance_changed')
        self.assertEqual(self.calls, [])

    def test_actual_disk_inode_rebound(self):
        replacement = self.instance_dir / 'replacement'
        replacement.write_bytes(self.disk.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(self.disk)
        self.assert_blocked(self.execute(), 'instance_changed')
        self.assertEqual(self.calls, [])

    def test_actual_geometry_hash_rebound(self):
        self.geometry['user_bytes'] += 512
        DEV['write_json'](self.instance_dir / 'geometry.json', self.geometry)
        self.assert_blocked(self.execute(), 'instance_changed')
        self.assertEqual(self.calls, [])

    def test_context_changes_between_prepare_and_launch_rejected(self):
        def change():
            self.context['available_capabilities']['cold']['available'] = False
            self.save_context()
        self.prepare_hook = change
        self.assert_blocked(self.execute(), 'context_changed')
        self.assertEqual(self.calls, ['prepare'])

    def test_generation_changed_after_launch_preparation_is_rejected_inside_lease(self):
        def change():
            self.state['generation'] += 1
            DEV['write_json'](self.instance_dir / 'instance.json', self.state)
        self.launch_hook = change
        self.assert_blocked(self.execute(), 'instance_changed')
        self.assertNotIn('execute', self.calls)
        self.assertEqual(self.calls[-1], 'lease-exit')

    def test_post_execution_context_change_rejected(self):
        def change():
            self.context['routes']['root']['generation'] += 1
            self.save_context()
        self.executor_hook = change
        self.assert_blocked(self.execute(), 'context_changed')
        self.assertEqual(self.calls[-1], 'lease-exit')

    def test_old_controller_receipt_never_overwritten(self):
        path = self.job / 'controller-result.json'
        DEV['write_json'](path, {'original': 'retain'})
        before = path.read_bytes()
        self.assert_blocked(self.execute(), 'result_exists')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.calls, [])

    def test_external_receipt_target_rejected_without_writing(self):
        self.request['controller_result'] = str(self.root / 'outside.json')
        self.save_request()
        self.assert_blocked(self.execute(), 'result_scope')
        self.assertFalse((self.root / 'outside.json').exists())
        self.assertEqual(self.calls, [])

    def test_external_original_stage_evidence_rejected(self):
        self.variant = 'external-evidence'
        self.assert_blocked(self.execute(), 'evidence_scope')

    def test_private_request_and_job_modes_required(self):
        self.request_path.chmod(0o644)
        self.assert_blocked(self.execute(), 'private_path_required')
        self.assertFalse((self.job / 'controller-result.json').exists())
        self.request_path.chmod(0o600)
        self.job.chmod(0o755)
        self.assert_blocked(self.execute(), 'private_path_required')

    def test_symlink_and_device_paths_rejected(self):
        self.request_path.unlink()
        self.request_path.symlink_to(self.context_path)
        self.assert_blocked(self.execute(), 'symlink_path')
        result = API['execute']('/dev/null')
        self.assert_blocked(result, 'invalid_path_type')

    def test_capability_not_invented_by_controller(self):
        self.context['available_capabilities'] = {}
        self.save_context()
        self.assert_blocked(self.execute(), 'required_stage_unavailable')
        self.assertEqual(self.calls, [])
        self.assertEqual(DEV['read_json'](self.context_path)['available_capabilities'], {})

    def test_capability_contract_and_instance_required(self):
        self.context['available_capabilities']['cold']['instance_identity']['generation'] += 1
        self.save_context()
        self.assert_blocked(self.execute(), 'capability_instance_mismatch')
        self.assertEqual(self.calls, [])

    def test_unknown_action_profile_and_path_parameters_rejected(self):
        self.request['action'] = 'shell'
        self.save_request()
        self.assert_blocked(self.execute(), 'unknown_action')
        self.assertEqual(self.calls, [])

    def test_unknown_profile_rejected(self):
        self.request['profile'] = 'anything'
        self.save_request()
        self.assert_blocked(self.execute(), 'unknown_profile')
        self.assertEqual(self.calls, [])

    def test_injected_shell_field_is_not_consumed(self):
        self.request['command'] = 'touch /tmp/must-not-run'
        self.save_request()
        self.assert_blocked(self.execute(), 'request_fields')
        self.assertEqual(self.calls, [])

    def test_hot_and_update_actions_are_structured_blocked(self):
        self.request.update(action='hot', target='hot', required_stages=list(DEV['STAGES']['hot']))
        self.save_request()
        self.assert_blocked(self.execute(), 'action_not_implemented')
        self.assertEqual(self.calls, [])

    def test_update_is_structured_blocked(self):
        self.request.update(action='update', target='update', required_stages=list(DEV['STAGES']['update']))
        self.save_request()
        self.assert_blocked(self.execute(), 'action_not_implemented')
        self.assertEqual(self.calls, [])

    def test_sequence_requires_its_explicit_capability(self):
        self.request.update(action='sequence', target='sequence', boot_profile='qemu-retained-roundtrip',
                            required_stages=list(DEV['STAGES']['sequence']))
        self.save_request()
        self.assert_blocked(self.execute(), 'required_stage_unavailable')
        self.assertEqual(self.calls, [])

    def test_malformed_action_is_structured_blocked(self):
        self.request['action'] = ['cold']
        self.save_request()
        self.assert_blocked(self.execute(), 'unknown_action')
        self.assertEqual(self.calls, [])

    def test_unknown_camera_profile_is_rejected(self):
        self.context['available_capabilities']['cold']['camera_profile'] = 'sh -c anything'
        self.save_context()
        self.assert_blocked(self.execute(), 'unknown_camera_profile')
        self.assertEqual(self.calls, [])

    def test_source_core_path_syntax_is_rejected(self):
        path = self.root / 'runtime;touch injected'
        path.mkdir(mode=0o700)
        self.context['runtime'] = self.request['runtime'] = str(path)
        self.save_context()
        self.save_request()
        self.assert_blocked(self.execute(), 'unsafe_core_path')
        self.assertEqual(self.calls, [])

    def test_original_receipt_reservation_cannot_be_replaced(self):
        def change():
            DEV['write_json'](self.job / 'controller-result.json', {'preserved': 'concurrent replacement'})
        self.executor_hook = change
        self.assert_blocked(self.execute(), 'result_changed')
        self.assertEqual(DEV['read_json'](self.job / 'controller-result.json'), {'preserved': 'concurrent replacement'})

    def test_stage_list_cannot_be_shortened(self):
        self.request['required_stages'] = ['original_init_cold']
        self.save_request()
        self.assert_blocked(self.execute(), 'required_stages')
        self.assertEqual(self.calls, [])

    def test_source_unknown_stays_false(self):
        self.state['source_class'] = 'unknown'
        DEV['write_json'](self.instance_dir / 'instance.json', self.state)
        result = self.execute()
        self.assert_blocked(result, 'source_unknown')
        self.assertFalse(result['source_known'])
        self.assertEqual(self.calls, [])

    def test_executor_original_error_rc_and_log_preserved(self):
        self.variant = 'executor-failure'
        result = self.execute()
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Cold boot failed', result['error']['detail'])
        retained = {Path(row['path']).name: row for row in result['failure_evidence']}
        raw = DEV['read_json'](retained['failed-boot-flow.json']['path'])
        self.assertEqual(raw['owner']['returncode'], 23)
        self.assertIn('OriginalGuestError: rc=23', raw['error'])
        self.assertEqual(retained['failed-console.log']['sha256'], digest(self.job / 'cold-session/evidence/console.log'))
        self.assertEqual(self.calls[-1], 'lease-exit')


class LiveHotRequestTests(unittest.TestCase):
    """Typed fake owner responses exercise dispatch only; no VM evidence."""
    setUp = ColdRequestTests.setUp
    save_context = ColdRequestTests.save_context
    save_request = ColdRequestTests.save_request
    prepare = ColdRequestTests.prepare
    prepare_launch = ColdRequestTests.prepare_launch
    leased_launch = ColdRequestTests.leased_launch
    assert_blocked = ColdRequestTests.assert_blocked

    def run_hot(self, fail_hot=False, fail_close=False, *, authenticated=False, refusal_state=None, frontend_enabled=False):
        self.request.update(action='hot', target='hot', boot_profile='qemu-live-retained-roundtrip',
                            required_stages=list(DEV['STAGES']['hot']))
        self.save_request()
        cap = dict(live_owner=dict(path='/host-fixture-only/live-owner.json', sha256='f' * 64))
        self.context['available_capabilities']['hot'] = dict(available=True, contract=DEV['SCHEMA'], instance_identity=self.identity)
        self.save_context()
        def request(owner, instance, action):
            self.calls.append(action)
            self.assertEqual(instance, self.identity)
            if (action == 'hot' and fail_hot) or (action == 'close' and fail_close):
                if authenticated:
                    raise LIVE['LiveRequestRefused']('original ' + action + ' failure', refusal_state)
                error = RuntimeError('original ' + action + ' failure')
                error.state = dict(live_owner_pids=[999])  # Unauthenticated attributes are not owner evidence.
                raise error
            return dict(schema=LIVE['SCHEMA'], status='completed',
                        result=dict(artifact=dict(path='/host-fixture-only/result.json', sha256='e' * 64),
                                    state=dict(live_owner_pids=[] if action == 'close' else [123])))
        backend = type('HostOnly', (), {'inspect_owner': staticmethod(lambda *a:
            dict(controller_identity=dict(pid=123), frontend_enabled=frontend_enabled)),
            'LiveRequestRefused': LIVE['LiveRequestRefused'],
            'request': staticmethod(request), 'verify_result': staticmethod(lambda *a: dict(host_only=True))})()
        with patch.dict(DEV, hot_capability=lambda *a: cap, live_module=lambda: backend), \
                patch.object(API['execute'].__globals__['runpy'], 'run_path', side_effect=lambda *a: self.fail('hot cannot load cold preparation')):
            return API['execute'](self.request_path)

    def test_frontend_flag_must_be_explicit_bool_before_any_owner_request(self):
        result = self.run_hot(frontend_enabled=1)
        self.assertEqual(result['status'], 'blocked', result)
        self.assertEqual(self.calls, [])
        self.assertIn('explicit bool', result['error']['detail'])

    def test_admitted_hot_only_uses_running_owner_then_typed_close(self):
        result = self.run_hot()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(self.calls, ['hot', 'close'])
        DEV['verified_receipt'](result, self.request, self.job, 0)
        self.assertFalse(result['gui_owner_switch_verified'])
        self.assertFalse(result['hot_verified'])
        self.assertFalse(result['capture_verified'])
        self.assertFalse((self.job / 'cold-session').exists())

    def test_failed_hot_preserves_owner_without_automatic_close(self):
        result = self.run_hot(fail_hot=True)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(self.calls, ['hot'])
        snapshots = self.job / 'stage-evidence'
        self.assertIn('original hot failure', DEV['read_json'](snapshots / 'live-hot-error.json')['error'])
        self.assertFalse((snapshots / 'live-close-response.json').exists())
        self.assertIsNone(result['owner_retained'])
        self.assertFalse(result['owner_state_confirmed'])
        self.assertIsNone(result['live_state'])
        self.assertIsNone(DEV['read_json'](snapshots / 'live-hot-error.json')['state'])
        self.assertTrue(result['lease_retained_until_owner_exit'])
        self.assertTrue(all(row['verified'] is False for row in result['stages'].values()))
        self.assertFalse(result['qemu_retained_roundtrip_verified'])

    def test_failed_close_preserves_the_original_error_and_owner_state(self):
        result = self.run_hot(fail_close=True)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(self.calls, ['hot', 'close'])
        snapshots = self.job / 'stage-evidence'
        self.assertIn('original close failure', DEV['read_json'](snapshots / 'live-close-error.json')['error'])
        self.assertTrue((snapshots / 'live-hot-response.json').exists())
        self.assertIsNone(result['owner_retained'])
        self.assertFalse(result['owner_state_confirmed'])
        self.assertIsNone(result['live_state'])
        self.assertIsNone(DEV['read_json'](snapshots / 'live-close-error.json')['state'])
        self.assertEqual(result['vm_signals_sent'], [])
        self.assertTrue(all(row['verified'] is False for row in result['stages'].values()))

    def assert_authenticated_failure(self, action, pids):
        state = dict(phase='target-owned' if pids else 'captured-source-exited',
                     owner_pid=pids[0] if pids else None, live_owner_pids=pids, capture_returned=True,
                     controller_pid=123, hot_consumed=True, gui_owner_switch_verified=False,
                     display='QMP at target' if pids else 'none',
                     input='owned target stdin' if pids else 'none')
        result = self.run_hot(fail_hot=action == 'hot', fail_close=action == 'close',
                              authenticated=True, refusal_state=state)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(self.calls, ['hot'] if action == 'hot' else ['hot', 'close'])
        self.assertIs(result['owner_retained'], bool(pids))
        self.assertTrue(result['owner_state_confirmed'])
        self.assertEqual(result['live_state'], state)
        receipt = DEV['read_json'](self.job / 'stage-evidence' / ('live-' + action + '-error.json'))
        self.assertEqual(receipt['state'], state)
        self.assertEqual(receipt['type'], 'LiveRequestRefused')
        self.assertIn('original ' + action + ' failure', receipt['error'])
        self.assertTrue(result['lease_retained_until_owner_exit'])
        self.assertEqual(result['vm_signals_sent'], [])
        self.assertFalse(result['qemu_retained_roundtrip_verified'])
        self.assertTrue(all(row['verified'] is False for row in result['stages'].values()))

    def test_authenticated_hot_refusal_after_source_exit_reports_no_live_owner(self):
        self.assert_authenticated_failure('hot', [])

    def test_authenticated_hot_refusal_reports_retained_live_owner(self):
        self.assert_authenticated_failure('hot', [201])

    def test_authenticated_close_refusal_after_exit_reports_no_live_owner(self):
        self.assert_authenticated_failure('close', [])

    def test_authenticated_close_refusal_reports_retained_live_owner(self):
        self.assert_authenticated_failure('close', [201])

    def test_refusal_without_authenticated_state_remains_unconfirmed(self):
        result = self.run_hot(fail_hot=True, authenticated=True)
        self.assertEqual(result['status'], 'failed', result)
        self.assertEqual(self.calls, ['hot'])
        self.assertIsNone(result['owner_retained'])
        self.assertFalse(result['owner_state_confirmed'])
        self.assertIsNone(result['live_state'])


RETAINED = runpy.run_path(str(HERE / 'retained-camera-test.py'))
RFIX = runpy.run_path(str(HERE / 'test-retained-camera-test.py'))


class SequenceRequestTests(unittest.TestCase):
    """Synthetic host evidence exercises real parsers; never a VM/actual pass."""
    save_context = ColdRequestTests.save_context
    save_request = ColdRequestTests.save_request
    assert_blocked = ColdRequestTests.assert_blocked
    prepare_launch = ColdRequestTests.prepare_launch
    leased_launch = ColdRequestTests.leased_launch

    def setUp(self):
        ColdRequestTests.setUp(self)
        self.request.update(action='sequence', target='sequence', boot_profile='qemu-retained-roundtrip',
                            required_stages=list(DEV['STAGES']['sequence']))
        self.save_request()
        self.proof = self.root / 'audit.json'
        self.proof.write_bytes(DEV['RETAINED_PROOF'].read_bytes())
        self.proof.chmod(0o600)
        self.module = self.root / 'module.ko'
        self.module.write_bytes(b'host fixture module, never loaded')
        self.wire = self.instance_dir / 'persistent-geometry.bin'
        self.wire.write_bytes(b'host wire fixture')
        self.wire.chmod(0o600)
        self.cold_path, self.combo_path = self.root / 'cold.json', self.root / 'combo.json'
        DEV['write_json'](self.combo_path, {'fixture': 'not a real combo'})
        self.backend = dict(RETAINED, P=dict(RETAINED['P'], current_kernel_binding=lambda _: None), run=self.run_retained)
        self.cap = {'available': True, 'contract': DEV['SCHEMA'], 'instance_identity': copy.deepcopy(self.identity),
                    'runtime_analysis': str(self.runtime / 'analysis'), 'origin_qemu_build': str(self.build_dir),
                    'backend_source': {'path': str(HERE / 'retained-camera-test.py'), 'sha256': digest(HERE / 'retained-camera-test.py')},
                    'persistent_module': {'path': str(self.module), 'sha256': digest(self.module)},
                    'retained_audit': {'complete': True, 'compatible': True, 'external_state_verified': True,
                        'instance_identity': copy.deepcopy(self.identity), 'evidence': str(self.proof),
                        'evidence_sha256': digest(self.proof), 'profile': DEV['RETAINED_PROFILE'],
                        'qemu_sha256': DEV['RETAINED_QEMU_SHA'], 'source_tree_sha256': DEV['RETAINED_SOURCE_SHA'],
                        'scope': DEV['RETAINED_SCOPE']}}
        self.geometry = self.schema_value(RETAINED['DS']['GEOMETRY_SCHEMA'])
        self.geometry.update(backing_bytes=self.identity['bytes'], user_bytes=8192)
        original_parts = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 15, 18, 22, 23, 30)
        for i, row in enumerate(self.geometry['partition_rows'], 1):
            row.update(part=i, bytes=512 if i in original_parts else 0)
        DEV['write_json'](self.instance_dir / 'geometry.json', self.geometry)
        self.identity['geometry_sha256'] = self.state['geometry_sha256'] = digest(self.instance_dir / 'geometry.json')
        DEV['write_json'](self.instance_dir / 'instance.json', self.state)
        for route in ('root', 'bodydata'):
            self.context['routes'][route] = copy.deepcopy(self.identity)
        self.cap['instance_identity'] = self.cap['retained_audit']['instance_identity'] = copy.deepcopy(self.identity)
        self.cold = {'profile': RETAINED['P']['PROFILE'], 'build_verified': True, 'instance': str(self.instance_dir),
            'instance_generation': 7, 'instance_geometry': self.geometry, 'source': self.state['source_class'],
            'instance_source_manifest_sha256': self.state['source_manifest_sha256'], 'partition_images_in_ram0': 0,
            'prepared_runtime_analysis': self.cap['runtime_analysis'], 'instance_wire': str(self.wire),
            'instance_wire_sha256': digest(self.wire), 'actual_kernel': {}, 'firmware_binding_schema': 1,
            'partition_bindings': [], 'block_module': {'path': str(self.module), 'sha256': digest(self.module)},
            'native_elf_identity': {name: {'sha256': value} for name, value in (
                ('/bin/bootin.elf', EXEC['BOOTIN_SHA256']), ('/lib/appFw.so', EXEC['APPFW_SHA256']))},
            'capacity_checks': {'pnflasha': 16, **{'cnflasha' + str(p): 1 for p in original_parts},
                                'nflashaB0': 8192, 'nflashaB1': 8192}}
        self.refresh_cold()
        self.cap['combo_manifest'] = {'path': str(self.combo_path), 'sha256': digest(self.combo_path)}
        self.context['available_capabilities']['sequence'] = self.cap
        self.save_context()
        self.save_request()
        self.variant = ''
        self.after_run = None

    def schema_value(self, schema):
        if 'const' in schema:
            return schema['const']
        kind = schema['type']
        if kind == 'object':
            return {k: self.schema_value(v) for k, v in schema['properties'].items()}
        if kind == 'array':
            return [self.schema_value(schema['items']) for _ in range(schema['minItems'])]
        if kind == 'string':
            return '0' * 64 if schema.get('pattern') == '^[0-9a-f]{64}$' else 'fixture'
        return 0 if kind == 'integer' else False

    def refresh_cold(self):
        DEV['write_json'](self.cold_path, self.cold)
        self.cap['cold_manifest'] = {'path': str(self.cold_path), 'sha256': digest(self.cold_path)}

    def execute(self):
        def load(path):
            self.assertEqual(Path(path), HERE / 'retained-camera-test.py', 'Sequence must not prepare/build or take an outer core lease')
            return self.backend
        with patch.object(API['execute'].__globals__['runpy'], 'run_path', side_effect=load):
            return API['execute'](self.request_path)

    def run_retained(self, runtime, manifest, output, **options):
        self.calls.append('retained-run')
        self.assertEqual((runtime, manifest, output), (self.runtime / 'analysis', self.cold_path, self.job / 'retained'))
        self.assertEqual(options, {'combo_manifest': self.combo_path, 'origin_qemu_build': self.build_dir})
        output.mkdir(mode=0o700)
        for sub in ('launch/run', 'launch/runtime/analysis', 'transaction/target'):
            (output / sub).mkdir(parents=True, mode=0o700)
        def save(name, value):
            DEV['write_json'](output / name, value)
        def raw(name, value):
            path = output / name
            path.write_bytes(value if isinstance(value, (bytes, bytearray)) else value.encode())
            path.chmod(0o600)
            return path
        cmdline = 'root=/dev/ram0 persistent.profile=persistent-flash-cold-v1 padding='
        self.launch = {'cmdline': cmdline + 'x'*(1652-len(cmdline))}
        token, nonce = 'a' * 32, 'f' * 32
        source_run, target_run = 'retained-source-' + token, 'retained-target-' + token
        marker = 'A7C2_RETAINED_GUEST_SYNC nonce=' + nonce + ' sync_rc=0'
        boot = ColdRequestTests.console_text(self).replace('pid=42', 'pid=31')
        boot = boot.replace('COLD_KERNEL_CMDLINE_BEGIN\n'+self.launch['cmdline']+'\nCOLD_KERNEL_CMDLINE_END\n',
                            'Kernel command line: '+self.launch['cmdline'][:968]+'\n')
        diagnostics, traced = [], []
        for line in boot.split('\n'):
            if line.startswith(('COLD_OLD_INITRD_PATH_ABSENT=', 'COLD_NATIVE_BOOTIN ', 'COLD_AP_MAP ')) or re.match(r'^\d+ 1 \d+:', line):
                diagnostics.append(line)
            elif not line.startswith(('COLD_EXECUTABLE=', 'COLD_PROCESS ', 'COLD_NATIVE_IM ', 'SHA256(/proc/42/exe)=')):
                traced.append(line)
        proof = RFIX['cold_proof_bytes'](token, self.launch['cmdline'], ('\n'.join(diagnostics)+'\n').encode())
        proof = proof.replace(b'pid=621', b'pid=31').replace(b'/proc/621/', b'/proc/31/')
        trace = '\n'.join(traced).encode() + RFIX['cold_transfer'](proof, token)
        source_log = raw('transaction/source-console.log', trace)
        collector_log = RETAINED['retain_cold_proof'](output, source_log, token)
        source_text = trace.decode() + RFIX['state_text']('source')
        source_text += 'RETAINED_DONE_source=' + token + '\n' + marker + '\n'
        with source_log.open('ab') as stream:
            stream.write(source_text.encode()[len(trace):])
        target_text = RFIX['state_text']('restored') + 'RETAINED_DONE_restored=' + token + '\n'
        for phase in ('menu', 'shooting'):
            target_text += RFIX['input_text'](phase) + RFIX['state_text'](phase) + 'RETAINED_DONE_' + phase + '=' + token + '\n'
        raw('transaction/target/console.log', target_text)
        states = {phase: RETAINED['parse_state'](source_text if phase == 'source' else target_text, phase)
                  for phase in ('source', 'restored', 'menu', 'shooting')}
        for phase, state in states.items():
            save(phase + '-state.json', state)
        save('frame-state-observations.json', states)
        frames = {}
        for phase in states:
            ppm, pool = RFIX['pixels'](phase)
            # A nonuniform original-sized LCD; keep the independent BGRX match.
            ppm = bytearray(ppm); ppm[-3:] = b'\x01\x02\x03'
            pool = bytearray(pool); pool[640 * 480 * 4 - 4:640 * 480 * 4] = b'\x03\x02\x01\0'
            base = 'launch/run/' if phase == 'source' else 'transaction/target/'
            raw(base + phase + '.ppm', ppm)
            raw(base + phase + '-scanout-pool.bin', pool)
            frames[phase] = RETAINED['pixel_review'](ppm, pool)
        save('frame-pixels.json', frames)
        for phase in ('menu', 'shooting'):
            save(phase + '-input.json', RETAINED['review_input'](RFIX['input_text'](phase), phase))
        receipt = EXEC['new_receipt']('original-init-cold', bindings={'run': source_run, 'source_class': self.cold['source']},
                                      kernel_cmdline=self.launch['cmdline'])
        save('source-cold-evidence.json', EXEC['collect'](collector_log, receipt))
        cold_row = RETAINED['COLD']['binding'](manifest, 'host-contract-fixture')
        script = raw('launch/run/script.sh', '# host fixture; never executed\n')
        self.launch.update(instance=str(self.instance_dir), runtime_analysis=str(output / 'launch/runtime/analysis'), profile=DEV['RETAINED_PROFILE'],
            incoming=False, disk_source_class=self.cold['source'], source_class='diagnostic-derived-retained-camera',
            qemu_sha256=DEV['RETAINED_QEMU_SHA'], cold_manifest_binding=cold_row, script=str(script), script_sha256=digest(script),
            template_inputs=[], launch_inputs=[], source_firmware_contract=RETAINED['P']['firmware_contract'](self.cold),
            combo_binding={'manifest': str(self.combo_path), 'declared_topology': RETAINED['L']['COMBO']['UPSTREAM_TOPOLOGY']})
        save('launch/launch.json', self.launch)
        save('preflight.json', {'cold_manifest': cold_row, 'source_bindings': RETAINED['SOURCE_BINDINGS']})
        with self.disk.open('rb') as f:
            disk_record = RETAINED['DS']['_record'](f.fileno())
        sync = raw('transaction/guest-sync.console', source_text)
        with sync.open('rb') as f:
            sync_record = dict(RETAINED['DS']['_record'](f.fileno()), sha256=digest(sync))
        binding = {'schema': RETAINED['DS']['SCHEMA'], 'phase': 'disk-binding-prepared', 'whole_machine_verified': False,
            'transaction': {'token': '1' * 64, 'parent_pid': os.getpid(), 'fd': 123},
            'capture': {'host_run': source_run, 'migration_generation': 0, 'guest_sync': {'path': str(sync), 'nonce': nonce,
                'marker': marker, 'evidence': sync_record, 'verification': 'caller-console-marker'}},
            'disk': disk_record, 'disk_generation': 7, 'source_class': self.cold['source'],
            'source_manifest_sha256': self.state['source_manifest_sha256'], 'geometry': self.geometry,
            'metadata': {k: dict(disk_record, sha256=self.identity['geometry_sha256'] if k == 'geometry' else '0' * 64)
                         for k in ('geometry', 'instance')},
            'wire': {'file': dict(disk_record, sha256=digest(self.wire)), 'hex': self.wire.read_bytes().hex()},
            'canonical_wire': {'sha256': digest(self.wire), 'hex': self.wire.read_bytes().hex()},
            'whole_disk_sha256': digest(self.disk), 'partition_bindings': [
                {'id': n, 'offset': 0, 'bytes': 1, 'sha256': '0' * 64} for n in ('nflasha3', 'nflasha7', 'nflasha15')]}
        save('transaction/disk-binding.json', binding)
        binding_sha = RETAINED['C']['R']['_digest'](binding)
        for i, phase in enumerate(RETAINED['DS']['PHASES']):
            qmp = [{'command': 'query-status', 'response': {'running': False, 'status': RETAINED['DS']['STATES'][i]}}] * 2
            if i == 1:
                qmp += [{'command': 'query-migrate', 'response': {'status': 'completed'}}] * 2
            save('transaction/disk-' + phase + '.json', {'schema': 1, 'phase': phase, 'disk_binding_verified': True,
                'binding_sha256': binding_sha, 'disk_generation': 7, 'host_run': source_run if i < 2 else target_run,
                'migration_generation': 0 if i < 2 else 1, 'whole_machine_verified': False, 'qmp': qmp})
        def proc(pid):
            return {'pid': pid, 'parent_pid': os.getpid(), 'start_ticks': 111, 'uid': os.getuid()}
        def identity(pid):
            return {'owner': proc(pid), 'peer': proc(pid + 1), 'version': {'qemu': {'major': 11, 'minor': 1, 'micro': 2}},
                'memory': {'base-memory': 24576 * 1024 ** 2}, 'options': [['--bind', str(self.instance_dir), '/instance']],
                'environment': {**RETAINED['L']['UPSTREAM_USB'], 'QEMU_A7PF_FD': '123',
                'QEMU_A7PF_DEV': str(self.identity['dev']), 'QEMU_A7PF_INO': str(self.identity['ino']),
                'QEMU_A7PF_RETAINED_STATE': '1', 'QEMU_A7PF_PROFILE': DEV['RETAINED_PROFILE']}}
        stream = raw('transaction/snapshot.partial', b'host fixture stream; never loadable RAM')
        with stream.open('rb') as f:
            stream_record = RETAINED['DS']['_record'](f.fileno())
        owner_exit = lambda pid: {'pid': pid, 'signals_sent': [], 'returncode': 0, 'quit_response': {}}
        captured = {'schema': 'a7c2-retained-camera-execution-v1', 'profile': DEV['RETAINED_PROFILE'],
            'external_state': RETAINED['C']['EXTERNAL'], 'status': 'captured-source-postmigrate', 'source_run': source_run,
            'source_identity': identity(900000001), 'disk_binding_sha256': binding_sha,
            'device_audit': {'type_counts': RETAINED['C']['SOURCE_COUNTS'], 'profile': DEV['RETAINED_PROFILE'],
                'qemu_sha256': DEV['RETAINED_QEMU_SHA'], 'source_tree_sha256': DEV['RETAINED_SOURCE_SHA'],
                'kind': RETAINED['C']['AUDIT_KIND'], 'external_state': RETAINED['C']['EXTERNAL']},
            'snapshot_sha256': digest(stream), 'snapshot_bytes': stream.stat().st_size, 'snapshot_file_record': stream_record,
            'migration_outgoing': {'status': 'completed'}, 'owners': [owner_exit(900000001)], 'guest_sync': {'nonce': nonce},
            'capture_verified': False, 'whole_machine_verified': False, 'cold_fallback_allowed': False}
        restored = dict(captured, status='restored-paused', target_identity=identity(900000003), target_run=target_run,
                        migration_incoming={'status': 'completed'})
        continued = dict(restored, status='continued-awaiting-new-guest-evidence', retained_cpu_resumed=True)
        closed = dict(continued, owners_closed=True, owners=[owner_exit(900000001), owner_exit(900000003)])
        for name, value in (('capture-result.json', captured), ('restore-paused-result.json', restored),
            ('transaction/restore-paused.json', restored), ('transaction/continued.json', continued),
            ('normal-close.json', closed), ('transaction/execution-closed.json', closed)):
            save(name, value)
        save('transaction/target-admission.json', {'transaction': binding['transaction'], 'disk_binding_sha256': binding_sha,
            'snapshot_sha256': digest(stream), 'run': target_run, 'disk_generation': 7, 'migration_generation': 1})
        result = {'schema': 'a7c2-retained-camera-test-v1', 'status': 'passed', 'actual_content_verified': True,
            'owners_closed': True, 'profile': DEV['RETAINED_PROFILE'], 'qemu_sha256': DEV['RETAINED_QEMU_SHA'],
            'source_tree_sha256': DEV['RETAINED_SOURCE_SHA'], 'whole_device_audit_scope': DEV['RETAINED_SCOPE'],
            'runtime_analysis': str(runtime), 'source_bindings': RETAINED['SOURCE_BINDINGS'], 'cold_manifest': cold_row,
            'source_run': source_run, 'target_run': target_run, 'headers': RETAINED['review_states'](states, frames, token),
            'frames': frames, 'normal_input_received_edges': 4, 'normal_input_free_enter_edges': 4,
            'same_kernel_ram_canary_ap_viewer_pid_and_flocks': True, 'vm_signals_sent': []}
        for name in ('full_device_audit_complete', 'full_boot_verified', 'sony_wbi_verified', 'hardware_ram_hotboot_verified',
                     'capture_verified', 'ui_hot_enabled', 'state_and_qmp_images_zero_race_coherent',
                     'display_under_one_second_verified', 'free_return_code_verified'):
            result[name] = False
        save('result.json', result)
        if self.after_run:
            self.after_run(output, result)
        return result

    def assert_failed(self, result, code=None):
        self.assertEqual(result['status'], 'failed', result)
        if code:
            self.assertEqual(result['blocked_reason']['code'], code, result)
        self.assertFalse(result['qemu_retained_roundtrip_verified'])
        self.assertFalse(result['hot_verified'])
        self.assertFalse(result['capture_verified'])

    def test_sequence_dispatch_and_all_content_stages_host_contract_only(self):
        result = self.execute()
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(self.calls, ['retained-run'])
        self.assertEqual(set(result['stages']), set(DEV['STAGES']['sequence']))
        DEV['verified_receipt'](result, self.request, self.job, 0)
        self.assertFalse(result['hot_verified'])
        self.assertFalse(result['sony_wbi_verified'])
        self.assertFalse(result['full_device_audit_complete'])
        self.assertFalse((self.job / 'stage-evidence/retained-transaction-snapshot.partial').exists())
        output = self.job / 'retained'
        trace = (output / 'source-cold-trace.log').read_bytes()
        self.assertTrue((output / 'transaction/source-console.log').read_bytes().startswith(trace))
        binding = DEV['read_json'](output / 'source-cold-proof.json')
        self.assertEqual(binding['trace']['sha256'], digest(output / 'source-cold-trace.log'))
        receipt = EXEC['new_receipt']('original-init-cold', bindings={'run': 'fixture', 'source_class': self.cold['source']},
                                      kernel_cmdline=self.launch['cmdline'])
        self.assertFalse(EXEC['collect'](output / 'source-cold-trace.log', receipt)['cold_guest_chain_verified'])
        self.assertTrue(DEV['read_json'](output / 'source-cold-evidence.json')['cold_guest_chain_verified'])
        for name in ('source-cold-trace.log', 'source-cold-proof.txt', 'source-cold-collector.log', 'source-cold-proof.json'):
            self.assertTrue((self.job / 'stage-evidence' / ('retained-'+name)).is_file())
        for path in (self.job / 'stage-evidence').iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def next_sequence_job(self):
        self.job, _ = DEV['new_job'](self.context, type('Args', (), {'action': 'sequence', 'profile': 'official'})())
        self.request.update(job_id=self.job.name, run_id=self.job.name, output_dir=str(self.job),
                            controller_result=str(self.job / 'controller-result.json'))
        self.request_path = self.job / 'request.json'
        self.save_request()

    def rewrite_cold_snapshot(self, output, proof, wire=None):
        """Keep forged sidecars mutually consistent; raw decoding must still reject."""
        trace_path = output / 'source-cold-trace.log'
        before = trace_path.read_bytes()
        trace = before[:before.index(b'RETAINED_COLD_META ')] + (RFIX['cold_transfer'](proof) if wire is None else wire)
        source = output / 'transaction/source-console.log'
        source.write_bytes(trace + source.read_bytes()[len(before):])
        trace_path.write_bytes(trace)
        (output / 'source-cold-proof.txt').write_bytes(proof)
        (output / 'source-cold-collector.log').write_bytes(trace + b'\n' + proof)
        DEV['write_json'](output / 'source-cold-proof.json', RETAINED['cold_proof_binding'](output, 'a'*32, trace, proof))

    def test_controller_rejects_tampered_proof_collector_or_json(self):
        for name in ('source-cold-proof.txt', 'source-cold-collector.log', 'source-cold-proof.json'):
            with self.subTest(name=name):
                def tamper(output, _result):
                    path = output / name
                    if name.endswith('.json'):
                        value = DEV['read_json'](path)
                        value['proof']['sha256'] = '0'*64
                        DEV['write_json'](path, value)
                    else:
                        path.write_bytes(path.read_bytes()+b'forged trailing content\n')
                self.after_run = tamper
                self.assert_failed(self.execute(), 'retained_evidence')
            self.next_sequence_job()

    def test_controller_independently_redecodes_transport_even_with_matching_sidecars(self):
        for damage in ('hash', 'base64', 'offset', 'nonce', 'noise', 'oversize', 'duplicate'):
            with self.subTest(damage=damage):
                def tamper(output, _result):
                    proof = (output / 'source-cold-proof.txt').read_bytes()
                    wire = RFIX['cold_transfer'](proof)
                    if damage == 'hash':
                        wire = wire.replace(hashlib.sha256(proof).hexdigest().encode(), b'0'*64)
                    elif damage == 'base64':
                        wire = wire.replace(b'data=', b'data=!', 1)
                    elif damage == 'offset':
                        wire = wire.replace(b'offset=0 ', b'offset=1 ', 1)
                    elif damage == 'nonce':
                        wire = wire.replace(b'CHUNK nonce='+b'a'*32, b'CHUNK nonce='+b'b'*32, 1)
                    elif damage == 'noise':
                        wire = wire.replace(b' offset=0 ', b' [kernel]noise offset=0 ', 1)
                    elif damage == 'oversize':
                        wire = wire.replace(('bytes='+str(len(proof))).encode(), b'bytes=1048577')
                    else:
                        lines = wire.splitlines(keepends=True)
                        wire = b''.join(lines[:2]+[lines[1]]+lines[2:])
                    self.rewrite_cold_snapshot(output, proof, wire)
                self.after_run = tamper
                result = self.execute()
                self.assert_failed(result)
                self.assertIn('proof', result['error']['detail'].lower())
            self.next_sequence_job()

    def test_rehashed_proof_cannot_invent_actual_im_identity(self):
        for before, after in ((b'SHA256(/proc/31/exe)= ', b'SHA256(/usr/bin/im.elf)= '),
                              (b'COLD_PROCESS pid=31', b'COLD_PROCESS pid=32'),
                              (RETAINED['IM_SHA256'].encode(), b'0'*64)):
            with self.subTest(before=before):
                def tamper(output, _result):
                    original_proof = (output / 'source-cold-proof.txt').read_bytes()
                    self.assertIn(before, original_proof)
                    self.rewrite_cold_snapshot(output, original_proof.replace(before, after))
                self.after_run = tamper
                result = self.execute()
                self.assert_failed(result)
                self.assertIn('IM', result['error']['detail'])
            self.next_sequence_job()

    def test_intact_rehashed_proof_still_requires_original_strong_cold_collector(self):
        for before, after in ((b'COLD_OLD_INITRD_PATH_ABSENT=0', b'COLD_OLD_INITRD_PATH_ABSENT=1'),
                              (b'COLD_AP_MAP pid=31', b'COLD_AP_MAP pid=99'),
                              (b'padding=', b'wrongarg=')):
            with self.subTest(before=before):
                def tamper(output, _result):
                    proof = (output / 'source-cold-proof.txt').read_bytes().replace(before, after)
                    self.rewrite_cold_snapshot(output, proof)
                self.after_run = tamper
                self.assert_failed(self.execute(), 'retained_evidence')
            self.next_sequence_job()

    def test_final_original_console_must_preserve_cold_snapshot_prefix(self):
        def tamper(output, _result):
            path = output / 'transaction/source-console.log'
            path.write_bytes(path.read_bytes().replace(b'Linux version ', b'Linux altered ', 1))
        self.after_run = tamper
        self.assert_failed(self.execute(), 'retained_evidence')

    def test_original_controller_parent_pid_guards_remain_enforced(self):
        for side in ('source', 'target'):
            with self.subTest(side=side):
                def tamper(output, _result):
                    for name in ('capture-result.json', 'restore-paused-result.json', 'transaction/restore-paused.json',
                                 'transaction/continued.json', 'normal-close.json', 'transaction/execution-closed.json'):
                        path = output / name
                        value = DEV['read_json'](path)
                        if side+'_identity' in value:
                            value[side+'_identity']['owner']['parent_pid'] += 1
                        DEV['write_json'](path, value)
                self.after_run = tamper
                self.assert_failed(self.execute(), 'retained_evidence')
            self.next_sequence_job()

    def test_launch_must_use_job_derived_runtime_not_input_helper(self):
        def mutate(output, _result):
            path = output / 'launch/launch.json'
            value = json.loads(path.read_text())
            value['runtime_analysis'] = self.cap['runtime_analysis']
            DEV['write_json'](path, value)
        self.after_run = mutate
        self.assert_failed(self.execute(), 'retained_evidence')

    def test_only_passed_status_without_raw_evidence_fails(self):
        self.backend['run'] = lambda *_a, **_kw: {'schema': 'a7c2-retained-camera-test-v1', 'status': 'passed', 'actual_content_verified': True}
        self.assert_failed(self.execute())

    def test_missing_or_wrong_capability_scope_and_proof_never_runs(self):
        for mutate, code in ((lambda c: c['retained_audit'].update(scope='full device audit'), 'retained_audit_scope'),
                             (lambda c: c['retained_audit'].update(evidence_sha256='0' * 64), 'sequence_input_changed'),
                             (lambda c: c.pop('cold_manifest'), 'sequence_capability_fields')):
            cap = copy.deepcopy(self.cap)
            mutate(self.cap)
            self.save_context()
            self.assert_blocked(self.execute(), code)
            (self.job / 'controller-result.json').unlink()
            self.cap.clear(); self.cap.update(cap)
        self.assertEqual(self.calls, [])

    def test_inputs_are_readonly_and_hash_bound(self):
        for path in (self.cold_path, self.combo_path, self.module):
            before = path.read_bytes()
            path.write_bytes(before + b'changed')
            self.assert_blocked(self.execute(), 'sequence_input_changed')
            (self.job / 'controller-result.json').unlink()
            path.write_bytes(before)
        self.assertEqual(self.calls, [])

    def test_cold_clone_generation_wire_and_stock_elf_drift_rejected(self):
        for key, value in (('instance', str(self.root)), ('instance_generation', 99),
                           ('instance_wire_sha256', '0' * 64), ('instance_geometry', {}),
                           ('native_elf_identity', {'/bin/bootin.elf': {'sha256': '0' * 64}})):
            previous = self.cold[key]
            self.cold[key] = value; self.refresh_cold(); self.save_context()
            self.assert_blocked(self.execute(), 'retained_evidence')
            self.cold[key] = previous
            self.job, _ = DEV['new_job'](self.context, type('Args', (), {'action': 'sequence', 'profile': 'official'})())
            self.request.update(job_id=self.job.name, run_id=self.job.name, output_dir=str(self.job),
                                controller_result=str(self.job / 'controller-result.json'))
            self.request_path = self.job / 'request.json'
            self.save_request()
        self.assertEqual(self.calls, [])

    def test_metadata_permissions_and_existing_output_are_never_repaired(self):
        self.wire.chmod(0o644)
        self.assert_failed(self.execute())
        self.assertEqual(self.wire.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.calls, [])

    def test_existing_retained_directory_is_preserved(self):
        (self.job / 'retained').mkdir(mode=0o700)
        DEV['write_json'](self.job / 'retained/failure.json', {'old_failure': True})
        self.assert_blocked(self.execute(), 'result_exists')
        self.assertTrue(DEV['read_json'](self.job / 'retained/failure.json')['old_failure'])

    def test_stream_hash_tampering_fails_and_large_stream_is_not_copied(self):
        def tamper(output, result):
            (output / 'transaction/snapshot.partial').write_bytes(b'changed stream')
        self.after_run = tamper
        self.assert_failed(self.execute(), 'retained_evidence')

    def test_stream_symlink_outside_job_is_rejected(self):
        def tamper(output, result):
            stream = output / 'transaction/snapshot.partial'
            external = self.root / 'old-stream'; external.write_bytes(stream.read_bytes()); external.chmod(0o600)
            stream.unlink(); stream.symlink_to(external)
        self.after_run = tamper
        self.assert_failed(self.execute(), 'symlink_path')

    def test_source_discontinuity_is_rejected_even_with_true_result(self):
        def tamper(output, result):
            path = output / 'transaction/target/console.log'
            path.write_text(path.read_text().replace('RETAINED_CANARY=' + 'a' * 32, 'RETAINED_CANARY=' + 'b' * 32))
        self.after_run = tamper
        self.assert_failed(self.execute(), 'retained_evidence')

    def test_actual_collector_and_cross_job_content_are_required(self):
        def tamper(output, result):
            path = output / 'source-cold-proof.txt'
            path.write_text(path.read_text().replace('COLD_AP_MAP pid=31', 'COLD_AP_MAP pid=99'))
        self.after_run = tamper
        self.assert_failed(self.execute(), 'retained_evidence')

    def test_false_disk_phase_cannot_promote_partial_stages(self):
        def tamper(output, result):
            path = output / 'transaction/disk-post-restore.json'
            data = DEV['read_json'](path); data['disk_binding_verified'] = False; DEV['write_json'](path, data)
        self.after_run = tamper
        result = self.execute()
        self.assert_failed(result, 'retained_evidence')
        self.assertTrue(all(row['verified'] is False for row in result['stages'].values()))

    def test_missing_stage_shortened_request_and_physical_route_refused(self):
        self.request['required_stages'].pop(); self.save_request()
        self.assert_blocked(self.execute(), 'required_stages')
        (self.job / 'controller-result.json').unlink()
        self.request['required_stages'] = list(DEV['STAGES']['sequence'])
        self.request['boot_profile'] = 'ram-hotboot'; self.save_request()
        self.assert_blocked(self.execute(), 'unknown_boot_profile')
        self.assertEqual(self.calls, [])

    def test_consistently_wrong_stream_hash_is_rejected_by_full_readback(self):
        def tamper(output, result):
            for name in ('capture-result.json', 'restore-paused-result.json', 'transaction/restore-paused.json',
                         'transaction/continued.json', 'normal-close.json', 'transaction/execution-closed.json'):
                path = output / name
                value = DEV['read_json'](path); value['snapshot_sha256'] = '0' * 64; DEV['write_json'](path, value)
        self.after_run = tamper
        self.assert_failed(self.execute(), 'evidence_hash')

    def test_missing_actual_phase_never_completes(self):
        self.after_run = lambda output, _result: (output / 'transaction/disk-pre-restore.json').unlink()
        self.assert_failed(self.execute())

    def test_request_drift_after_backend_is_rejected(self):
        def tamper(output, result):
            value = DEV['read_json'](self.request_path); value['source_mutation_allowed'] = True
            DEV['write_json'](self.request_path, value)
        self.after_run = tamper
        self.assert_failed(self.execute(), 'retained_evidence')

    def test_failure_original_argv_rc_and_console_are_preserved(self):
        def fail(_runtime, _cold, output, **_options):
            output.mkdir(mode=0o700)
            DEV['write_json'](output / 'source-owner-start.json', {'pid': 1, 'command': ['owned-source']})
            DEV['write_json'](output / 'failure.json', {'error': 'original rc=23', 'phase': 'source'})
            raise RuntimeError('original backend failure')
        self.backend['run'] = fail
        result = self.execute()
        self.assert_failed(result)
        failures = {Path(row['path']).name: row for row in result['failure_evidence']}
        raw = DEV['read_json'](failures['failed-retained-failure.json']['path'])
        self.assertEqual(raw['error'], 'original rc=23')
        self.assertEqual(DEV['read_json'](failures['failed-retained-source-owner-start.json']['path'])['command'], ['owned-source'])


if __name__ == '__main__':
    unittest.main()
