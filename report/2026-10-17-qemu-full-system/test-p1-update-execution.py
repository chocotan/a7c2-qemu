#!/usr/bin/env python3
"""Original p1 runner evidence and owner contracts, without starting QEMU."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'p1-update-execution.py'))


def manifest():
    return dict(schema=M['PROFILE'], status='built', mode='official', read_only=True,
        p2=dict(flags=dict(mode=False, mode5=False, comp=True, uincomp=False), predicted_outer_mode=1),
        original_audit=['/sbin/init', '/usr/bin/UdtrMain.sh'],
        original_files={name: dict(bytes=10, sha256='a' * 64) for name in ('/sbin/init', '/usr/bin/UdtrMain.sh')})


def serial():
    return ('UPDATE_CREDENTIAL kind=Uid: values=0,0,0,0\n'
        'UPDATE_CREDENTIAL kind=Gid: values=0,0,0,0\n'
        'UPDATE_RELEASE value=4.9.186-scel\nUPDATE_PERSISTENT_INSMOD_RC=0\n'
        'UPDATE_MODULES_BEGIN\nsony_persistent_flash 16384 0 - Live 0xffff0000 (O)\nUPDATE_MODULES_END\n'
        'UPDATE_P2_ACTUAL base=0 mode5=0 comp=1 uincomp=0 selected=1 frontend=notexecuted\n'
        + ''.join(f'UPDATE_ORIGINAL_BYTES path={p} bytes=10 sha256={"a"*64} rc=0\n' for p in manifest()['original_audit'])
        + ''.join(f'UPDATE_READONLY node=/dev/disk{i} set_rc=0 get_rc=0 readonly=1\n' for i in range(20))
        + 'UPDATE_ORIGINAL_INIT_EXEC=/sbin/init UDTRMAIN=unverified SDFILEINPUT=unverified BODYWRITER=unverified\n'
        '+UPDATE_TRACE pid=1 export HOME=/\n'
        'UPDATE_PROCESS pid=1 comm=sh\n/bin/sh\x00-x\x00/sbin/init\x00\n'
        'UPDATE_MAPS_BEGIN pid=1\n00400000-00410000 r-xp 00000000 00:01 1 /bin/busybox\nUPDATE_MAPS_END pid=1\n'
        'UPDATE_ORIGINAL_SCRIPT path=/usr/bin/UdtrMain.sh pid=42 interpreter=/bin/sh trace=external-x\n'
        '[DETAIL] MODE=1\n'
        'UPDATE_PROCESS pid=42 comm=sh\n/bin/sh\x00-x\x00/usr/bin/UdtrMain.sh\x00\n'
        'UPDATE_MAPS_BEGIN pid=42\n00400000-00410000 r-xp 00000000 00:01 1 /bin/busybox\nUPDATE_MAPS_END pid=42\n').encode()


class Evidence(unittest.TestCase):
    def test_actual_original_init_proof_does_not_claim_installation(self):
        result = M['collect'](serial(), manifest())
        for key in ('root_verified', 'kernel_release_verified', 'module_loaded', 'p2_matches_build',
                    'read_only_verified', 'original_init_executed', 'udtrmain_executed', 'maps_observed'):
            self.assertTrue(result[key], key)
        self.assertEqual(result['actual_dispatch_modes'], [1])
        for key in ('bypass_executed', 'installation_verified', 'bodywriter_executed', 'normal_ap_frontend'):
            self.assertFalse(result[key], key)

    def test_literal_busybox_ps4_still_requires_actual_pid1_and_maps(self):
        raw = serial().replace(b'+UPDATE_TRACE pid=1 ', b'+UPDATE_TRACE pid=$$ ')
        self.assertTrue(M['collect'](raw, manifest())['original_init_executed'])
        self.assertFalse(M['collect'](raw.replace(b'/sbin/init\x00', b'/untrusted\x00'), manifest())['original_init_executed'])
        self.assertFalse(M['collect'](raw.replace(b'UPDATE_MAPS_BEGIN pid=1', b'UPDATE_MAPS_BEGIN pid=9'), manifest())['original_init_executed'])

    def test_missing_duplicate_or_wrong_p2_is_not_replaced_with_build_prediction(self):
        line = b'UPDATE_P2_ACTUAL base=0 mode5=0 comp=1 uincomp=0 selected=1 frontend=notexecuted\n'
        for replacement in (b'', line + line, line.replace(b'selected=1', b'selected=5')):
            result = M['collect'](serial().replace(line, replacement), manifest())
            self.assertFalse(result['p2_matches_build'])

    def test_module_duplicate_audit_failure_and_nonroot_are_rejected(self):
        self.assertFalse(M['collect'](serial() + b'UPDATE_PERSISTENT_INSMOD_RC=0\n', manifest())['module_loaded'])
        self.assertFalse(M['collect'](serial().replace(b'values=0,0,0,0', b'values=1,0,0,0'), manifest())['root_verified'])
        self.assertFalse(M['collect'](serial().replace(b' rc=0\n', b' rc=7\n'), manifest())['original_init_executed'])
        self.assertFalse(M['collect'](serial().replace(b'get_rc=0', b'get_rc=-1'), manifest())['read_only_verified'])

    def test_original_fault_pc_and_rejected_modules_preserved(self):
        raw = serial() + (b'UPDATE_MODULE_REJECT applet=/sbin/insmod module=/usr/kmod/sio.ko '
            b'adapter_rc=125 original_module_rc=notexecuted reason=unmodeled-resource\n'
            b'Unhandled fault: synchronous external abort at 0x0000007f00\n'
            b'pc : [<0000000000401000>]\n')
        result = M['collect'](raw, manifest())
        self.assertEqual(len(result['original_error_lines']), 2)
        self.assertEqual(result['unsupported_modules'][0]['rc'], 125)
        self.assertIn('401000', result['original_error_lines'][1])
        self.assertEqual(result['raw_serial_sha256'], hashlib.sha256(raw).hexdigest())

    def test_sony_receiver_monitor_pc_and_actual_error_returns(self):
        raw = serial() + (b'open /dev/uipc error: : No such file or directory\n'
            b'Power IC type : 255\n'
            b'[ERR] SKData_Core_Init error SKData_Core_Init osal_reg_sync_msg_queue_cb -9\n'
            b'program: /usr/bin/sen.elf(sen.elf) (pid: 395, cpu:1, tid: -1)\n'
            b'[Exception Syndrome]\nAbort (PC=0x7f9368cafc)\n')
        result = M['collect'](raw, manifest())
        self.assertEqual(result['first_exception_pc'], '0x7f9368cafc')
        self.assertEqual(result['receiver_queue_returncodes'], [-9])
        self.assertEqual(result['power_ic_returncodes'], [255])
        self.assertIn('/dev/uipc', result['first_guest_error'])
        self.assertFalse(result['receiver_completed'])

    def test_resource_load_requires_bound_attempt_real_return_and_live_module(self):
        row = dict(path='/usr/kmod/osal_uipc.ko', file=dict(bytes=123, sha256='a' * 64))
        m = dict(manifest(), original_resources=dict(modules=[row]))
        raw = serial() + (f'UPDATE_MODULE_BEGIN module={row["path"]} bytes=123 sha256={"a" * 64} argc=1\n'
            f'UPDATE_MODULE_RESULT module={row["path"]} original_module_rc=0\n'
            'UPDATE_RESOURCE_MODULES_BEGIN\nosal_uipc 32768 0 - Live 0xffff0000 (O)\nUPDATE_RESOURCE_MODULES_END\n').encode()
        self.assertTrue(M['collect'](raw, m)['original_resource_chain_loaded'])
        for source in (raw.replace(b'original_module_rc=0', b'original_module_rc=22'),
                       raw.replace(b'bytes=123', b'bytes=122'), raw.replace(b' Live ', b' Loading '),
                       raw + b'UPDATE_MODULE_RESULT module=/usr/kmod/osal_uipc.ko original_module_rc=0\n'):
            self.assertFalse(M['collect'](source, m)['original_resource_chain_loaded'])
        result = M['collect'](raw + b'crw------- 1 root root 123,0 /dev/uipc\n', m)
        self.assertFalse(result['receiver_completed'])
        self.assertFalse(result['installation_verified'])

    def test_resource_policy_requires_exact_paths_and_contract_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'simulation').mkdir()
            row = dict(path='/kmod/devno.ko', file=dict(path='/new', bytes=123, sha256='a' * 64),
                       vermagic=['original'], undefined_symbols=[], module_providers={}, kernel_exports={})
            current = dict(policy='original-p1-resources-v1', inventory_sha256='b' * 64, inventory_count=90,
                kernel_sha256='c' * 64, force_load_allowed=False, original_arguments_preserved=True,
                guest_load_verified=False, physical_compatibility_verified=False, modules=[row], assets={})
            old = dict(current, modules=[dict(row, file=dict(row['file'], path='/old'))])
            update = dict(original_resources=old, original_module_allowlist=['/kmod/devno.ko'], p1={'kernel.img': {}})
            policy = root / 'simulation/original-modules'; policy.write_text('/kmod/devno.ko 123 ' + 'a' * 64 + '\n')
            with patch.dict(M['UPDATE'], original_resource_contract=lambda *args: current):
                self.assertEqual(M['resource_binding'](root, update), current)
                policy.write_text(policy.read_text().replace('/kmod/devno.ko', '/tmp/devno.ko'))
                with self.assertRaisesRegex(ValueError, 'guest policy differs'):
                    M['resource_binding'](root, update)
                with self.assertRaisesRegex(ValueError, 'allowlist differs'):
                    M['resource_binding'](root, dict(update, original_module_allowlist=['/tmp/devno.ko']))
                bad = dict(old, modules=[dict(row, file=dict(row['file'], sha256='d' * 64))])
                with self.assertRaisesRegex(ValueError, 'identity differs'):
                    M['resource_binding'](root, dict(update, original_resources=bad))
            with self.assertRaisesRegex(ValueError, 'lacks a resource contract'):
                M['resource_binding'](root, dict(original_module_allowlist=['/kmod/devno.ko']))
            with self.assertRaisesRegex(ValueError, 'Unexpected original'):
                M['resource_binding'](root, {})

    def test_original_uipc_status_and_backup_readback_do_not_promote_receiver(self):
        raw = serial() + (b'UPDATE_UIPC_NATIVE_GETSTATUS function=u_uipc_init original_rc=0 errno=0\n'
            b'UPDATE_UIPC_NATIVE_STAT words=1,2,3,4,5\n'
            b'UPDATE_BACKUP_FILE bytes=2390264 sha256=' + b'b' * 64 + b' rc=0\n')
        result = M['collect'](raw, manifest())
        self.assertEqual(result['native_uipc_getstatus_returncodes'], [0])
        self.assertEqual(result['native_uipc_stat_words'], [[1,2,3,4,5]])
        self.assertEqual(result['backup_file_readbacks'][0]['rc'], 0)
        self.assertFalse(result['receiver_completed'])
        self.assertFalse(result['installation_verified'])
        self.assertEqual(M['collect'](raw.replace(b'original_rc=0', b'original_rc=-9'), manifest())[
            'native_uipc_getstatus_returncodes'], [-9])

    def test_native_nodes_parameters_and_first_real_resource_error(self):
        raw = serial() + (b'[ 4.918] backup_init() error (file_load)\n'
            b'[ 4.919] initcall init_module+0x0/0xd88 [backup] returned -5 after 3122 usecs\n'
            b'crw-------    1 0        0         251, 207 Jan  1 00:00 /dev/uipc\n'
            b'crw-------    1 0        0         251, 208 Jan  1 00:00 /dev/backup\n'
            b'UPDATE_RESOURCE_PARAMETER path=/sys/module/backup/parameters/Backup_save\n0\n\n')
        result = M['collect'](raw, manifest())
        self.assertIn('file_load', result['first_guest_error'])
        self.assertEqual(result['original_module_init_returns'], [dict(module='backup', rc=-5)])
        self.assertEqual(result['native_device_nodes'], [dict(name='/dev/uipc', major=251, minor=207),
                                                        dict(name='/dev/backup', major=251, minor=208)])
        self.assertEqual(result['resource_parameters']['/sys/module/backup/parameters/Backup_save'], '0')
        self.assertFalse(result['receiver_completed'])

    def test_modified_manifest_refused_before_owner_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            m = dict(manifest(), output=str(path))
            M['save'](path / 'manifest.json', m)
            m['read_only'] = False
            with self.assertRaisesRegex(ValueError, 'differs from its built file'):
                M['actual'](m, path / 'not-created')
            self.assertFalse((path / 'not-created').exists())

    def test_cmdline_uses_original_p1_resources_and_explicit_blacklist(self):
        value = M['command_line']('kemco * rw init=/sbin/init root=/dev/ram0 rootfstype=squashfs mem=4G')
        self.assertIn('mem=4G', value)
        self.assertIn('rdinit=/init', value)
        self.assertIn('init=/init', value)
        self.assertIn(','.join(M['PROBE']['BLACKLIST']), value)
        self.assertNotIn('/p1-probe', value)

    def test_deadlines_reject_nonfinite_and_out_of_bounds_before_files(self):
        for value in (-1, 0, float('nan'), float('inf'), 601, '60'):
            with self.assertRaises(ValueError):
                M['actual'](manifest(), '/not-created', seconds=value)

    def test_live_owner_identity_has_starttime(self):
        first = M['owner_identity'](os.getpid())
        self.assertEqual(first, M['owner_identity'](os.getpid()))
        self.assertTrue(first['starttime'].isdigit())
        self.assertTrue(first['boot_id'])


class Owner(unittest.TestCase):
    def test_deadline_uses_bound_qmp_quit_and_wait_before_lease_release(self):
        self.exercise_owner(True)

    def test_wrong_qmp_owner_is_not_sent_quit(self):
        self.exercise_owner(False)

    def exercise_owner(self, name_matches):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            disk = folder / 'camera.emmc'; disk.write_bytes(b'private virtual disk')
            fd = os.open(disk, os.O_RDWR)
            self.addCleanup(os.close, fd)
            work = folder / 'work'; work.mkdir()
            instance = folder / 'instance'; instance.mkdir()
            state = M['UPDATE']['record'](disk)
            m = dict(manifest(), instance=str(instance), output=str(work), inputs=[], artifacts=[],
                     state=state, geometry=state, disk_sha256=state['sha256'],
                     disk_device=state['device'], disk_inode=state['inode'])
            M['save'](work / 'manifest.json', m)
            events = []
            @contextmanager
            def lease(path):
                events.append('lease-acquired')
                yield dict(fd=fd)
                events.append('lease-released')
            class Process:
                pid = os.getpid()
                returncode = None
                def poll(self): return self.returncode
                def wait(self, timeout=None):
                    events.append('wait')
                    self.returncode = 0
                    return 0
            process = Process()
            def popen(argv, **kwargs):
                events.append('launch')
                kwargs['stdout'].write(serial()); kwargs['stdout'].flush()
                self.assertEqual(kwargs['pass_fds'], (fd,))
                return process
            def qmp(path):
                def command(name, args=None):
                    events.append(name)
                    if name == 'query-name':
                        return {'return': {'name': 'p1-update-0123' if name_matches else 'another-owner'}}
                    return {'return': {}}
                class Stream:
                    def close(self): events.append('connection-close')
                return Stream(), Stream(), command
            globals_ = M['actual'].__globals__
            with patch.dict(M['DISK'], lease=lease), patch.object(M['subprocess'], 'Popen', popen), \
                    patch.object(M['time'], 'monotonic', side_effect=[1., 2.]), \
                    patch.object(M['secrets'], 'token_hex', return_value='0123'), \
                    patch.dict(M['OWNER'], qmp_connect=qmp), \
                    patch.dict(globals_, launch_command=lambda *a: ['bound-qemu']):
                result = M['actual'](m, folder / 'guest', seconds=.1)
            self.assertTrue(result['deadline_reached'])
            self.assertEqual(result['vm_signals'], [])
            if name_matches:
                self.assertTrue(result['verified'], result)
                self.assertTrue(result['normal_exit_verified'])
                self.assertLess(events.index('quit'), events.index('wait'))
            else:
                self.assertFalse(result['verified'])
                self.assertFalse(result['normal_exit_verified'])
                self.assertIn('not this registered owner', result['shutdown_error'])
                self.assertNotIn('quit', events)
            self.assertLess(events.index('wait'), events.index('lease-released'))
            self.assertTrue(result['lease_released_after_owner_exit'])
            self.assertFalse(result['installation_verified'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
