#!/usr/bin/env python3
"""Host contracts. Optional real build receipts: A7C2_UPDATE_BOOT_TEST_STAGE=... ."""
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
M = runpy.run_path(str(HERE / 'update-boot.py'))
RUNTIME = HERE.parents[1] / 'runtime/analysis'
REAL_STAGE = os.environ.get('A7C2_UPDATE_BOOT_TEST_STAGE')


class Contracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.scratch = Path(self.temporary.name)
        def host_tools(_runtime):
            paths = [shutil.which(name) for name in ('mformat', 'mcopy', 'mmd', 'mdel')]
            if not all(paths):
                self.skipTest('Install host mtools for synthetic FAT fixtures')
            directories = {Path(path).parent for path in paths}
            self.assertEqual(len(directories), 1, 'host mtools must share one bin directory')
            return directories.pop()
        for namespace in (M, M['prepare_sd'].__globals__):
            self.enterContext(patch.dict(namespace, tools=host_tools))

    def sample(self, name='selected.dat', text=b'\x89UFU\r\n\x1a\n' + bytes(range(256)) * 300):
        source = self.scratch / name
        source.write_bytes(text)
        return source

    def output(self, name='output'):
        path = self.scratch / name
        path.mkdir()
        return path

    def test_mode_is_required(self):
        with self.assertRaises(TypeError):
            M['build'](self.scratch, RUNTIME, self.scratch / 'unused')

    def test_unknown_mode_does_not_create_directory(self):
        target = self.scratch / 'not-created'
        for mode in (None, '', 'physical', 'auto', 'hostvirtual-update'):
            with self.assertRaises(ValueError):
                M['build'](self.scratch, RUNTIME, target, mode=mode)
        self.assertFalse(target.exists())

    def test_readonly_fd_copy_and_readback(self):
        source = self.sample()
        before = M['record'](source)
        fd = os.open(source, os.O_RDONLY)
        try:
            target = self.scratch / 'range'
            row = M['copy_range'](fd, 7, 65539, target)
            self.assertEqual(target.read_bytes(), source.read_bytes()[7:7 + 65539])
            self.assertTrue(row['readback_verified'])
            self.assertEqual(M['record'](source), before)
            with self.assertRaises(ValueError):
                M['copy_range'](fd, 0, before['bytes'] + 1, self.scratch / 'invalid')
        finally:
            os.close(fd)

    def test_host_symlink_source_refused(self):
        source = self.sample()
        alias = self.scratch / 'alias'
        alias.symlink_to(source)
        with self.assertRaises((ValueError, OSError)):
            M['copy_input'](alias, self.scratch / 'copy')
        self.assertFalse((self.scratch / 'copy').exists())

    def test_existing_destination_is_not_replaced(self):
        source = self.sample()
        target = self.sample('target', b'keep')
        with self.assertRaises(FileExistsError):
            M['copy_input'](source, target)
        self.assertEqual(target.read_bytes(), b'keep')

    def test_fat_sd_reads_actual_sample_and_preserves_nonzero_partition_tail(self):
        source = self.sample()
        original = M['record'](source)
        out = self.output()
        sd = M['prepare_sd'](source, None, RUNTIME, out)
        self.assertTrue(sd['ordinary_fat'])
        self.assertFalse(sd['guest_consumed'])
        self.assertFalse(sd['host_install_performed'])
        card = out / 'card.fat'
        with card.open('ab') as stream:
            stream.write(b'preserved nonzero partition tail')
        fat, inv, tail = M['fat_view'](card, out, 'tail-test')
        try:
            extracted = self.scratch / 'readback.dat'
            M['fat_extract'](fat, inv, '/BODYDATA.DAT', extracted)
            self.assertEqual(extracted.read_bytes(), source.read_bytes())
            self.assertEqual(tail['sha256'], hashlib.sha256(b'preserved nonzero partition tail').hexdigest())
            self.assertEqual(M['record'](source), original)
        finally:
            fat.close()

    def test_supplied_sd_must_match_selected_bodydata(self):
        source = self.sample()
        first = self.output('first')
        M['prepare_sd'](source, None, RUNTIME, first)
        other = self.sample('other', b'\x89UFU\r\n\x1a\nwrong payload')
        with self.assertRaisesRegex(ValueError, 'differs'):
            M['prepare_sd'](other, first / 'card.fat', RUNTIME, self.output('second'))

    def test_non_ufu_file_is_not_accepted_as_sd_input(self):
        with self.assertRaisesRegex(ValueError, 'Sony UFU'):
            M['prepare_sd'](self.sample(text=b'plain replacement tar archive'), None, RUNTIME, self.output())

    def test_real_fat_mode_precedence_and_incomplete_state(self):
        out = self.output()
        M['prepare_sd'](self.sample(), None, RUNTIME, out)
        tools = M['tools'](RUNTIME)
        env = dict(PATH='/usr/bin:/bin', MTOOLSRC='/dev/null', MTOOLS_SKIP_CHECK='1')
        subprocess.run([str(tools / 'mmd'), '-i', str(out / 'card.fat'), '::/updater'], env=env,
                       check=True, capture_output=True)
        empty = self.sample('empty', b'')
        for name in ('mode', 'mode5', 'comp', 'uincomp'):
            subprocess.run([str(tools / 'mcopy'), '-i', str(out / 'card.fat'), str(empty), '::/updater/' + name],
                           env=env, check=True, capture_output=True)
        fat, inv, _ = M['fat_view'](out / 'card.fat', out, 'setting')
        try:
            state = M['setting_state'](inv)
            self.assertEqual(state['predicted_outer_mode'], 5)
            self.assertTrue(state['uincomp_blocks_receiver'])
            self.assertTrue(state['comp_removes_modes_before_receiver'])
            self.assertFalse(state['sd_dispatch_eligible'])
            self.assertEqual(state['normal_ap_frontend'], 'notexecuted')
            inv['entries'].pop('/updater/uincomp')
            self.assertTrue(M['setting_state'](inv)['sd_dispatch_eligible'])
            inv['entries']['/updater/mode3'] = dict(kind='file')
            self.assertEqual(M['setting_state'](inv)['predicted_outer_mode'], 3)
            self.assertEqual(M['setting_state'](inv, serial=True)['predicted_outer_mode'], 1)
            inv['entries'].pop('/updater/mode')
            self.assertEqual(M['setting_state'](inv)['predicted_outer_mode'], 1)
        finally:
            fat.close()

    def test_newc_is_readable_by_independent_cpio(self):
        root = self.output('root')
        (root / 'dev').mkdir()
        (root / 'sbin').mkdir()
        (root / 'sbin/init').write_bytes(b'original init bytes\n')
        (root / 'link').symlink_to('sbin/init')
        path = self.scratch / 'bootstrap.cpio.gz'
        M['archive'](root, path)
        payload = gzip.decompress(path.read_bytes())
        result = subprocess.run(['cpio', '-i', '--to-stdout', 'sbin/init'], input=payload, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b'original init bytes\n')

    def module_fixture(self, *, fixed=True):
        module = dict(path='/selected/module.ko', bytes=56432,
                      sha256=M['CURRENT_MODULE_SHA'] if fixed else M['LEGACY_MODULE_SHA'])
        kernel = dict(path='/selected/kernel', bytes=6582280, sha256=M['KERNEL_SHA'])
        driver = dict(path='/selected/compiled.c', bytes=6440 if fixed else 6323,
                      sha256=M['CURRENT_DRIVER_SHA'] if fixed else
                      '850ec0d764a1cc3e1226318a82e82c9b8372390398623ee06b4214a999d9fd23')
        receipt = dict(schema='a7c2-original-p1-persistent-module-v1', status='compiled',
                       force_load_allowed=False, exports=dict(status='verified', missing=[]),
                       original_kernel=kernel, module=dict(file=module,
                       vermagic=['4.9.186-scel SMP preempt mod_unload aarch64']),
                       driver_copies={'sony_persistent_flash.c': driver})
        path = self.scratch / 'module.json'
        path.write_text(json.dumps(receipt))
        return module, kernel, driver, receipt, path

    def test_module_receipt_binds_actual_kernel_module_and_large_io_source(self):
        for fixed in (False, True):
            module, kernel, driver, receipt, path = self.module_fixture(fixed=fixed)
            with patch.dict(M['module_contract'].__globals__, record=lambda p: dict(driver)):
                result = M['module_contract'](module, kernel, path)
                self.assertTrue(result['build_bound'])
                self.assertEqual(result['large_io_fix_bound'], fixed)
                self.assertEqual(result['updater_write_eligible'], fixed)
                self.assertFalse(result['guest_read_path_verified'])
                for target in ('module', 'kernel'):
                    changed = dict(module if target == 'module' else kernel, sha256='f' * 64)
                    with self.assertRaisesRegex(ValueError, 'actual kernel/module'):
                        M['module_contract'](changed if target == 'module' else module,
                            changed if target == 'kernel' else kernel, path)
                receipt['driver_copies']['sony_persistent_flash.c'] = dict(driver, sha256='0' * 64)
                path.write_text(json.dumps(receipt))
                with self.assertRaisesRegex(ValueError, 'source differs'):
                    M['module_contract'](module, kernel, path)

    def test_unreviewed_true_probe_cannot_promote_module(self):
        module, kernel, driver, receipt, path = self.module_fixture(fixed=False)
        probe = self.scratch / 'probe.json'
        probe.write_text(json.dumps(dict(verified=True, guest_read_path_verified=True,
                                        module_loaded=True, disk_unchanged=True)))
        with patch.dict(M['module_contract'].__globals__, record=lambda p: driver):
            with self.assertRaisesRegex(ValueError, 'not reviewed'):
                M['module_contract'](module, kernel, path, probe)
        with self.assertRaisesRegex(ValueError, 'requires module'):
            M['module_contract'](module, kernel, probe_receipt=probe)

    def test_default_without_receipts_stays_unverified(self):
        self.assertFalse(M['module_contract']({}, {})['build_bound'])

    def test_p2_unknown_explicit_mode_is_zero_not_production_or_sd(self):
        entries = {'/updater/mode': dict(kind='file'), '/updater/comp': dict(kind='file')}
        state = M['setting_state'](dict(entries=entries))
        self.assertEqual(state['predicted_outer_mode'], 0)
        self.assertFalse(state['sd_dispatch_eligible'])
        entries['/updater/mode5'] = dict(kind='file')
        state = M['setting_state'](dict(entries=entries))
        self.assertEqual(state['predicted_outer_mode'], 5)
        self.assertTrue(state['comp_removes_modes_before_receiver'])
        self.assertTrue(state['sd_dispatch_eligible'])

    def test_resource_exports_require_real_pointer_pairs(self):
        source = self.scratch / 'symbols.S'
        source.write_text('.text\n.globl provider\nprovider: ret\n.globl consumer\nconsumer: b missing\n'
            '.section __ksymtab_strings,"a"\nname: .asciz "provider"\n'
            '.section __ksymtab,"a"\n.xword provider\n.xword name\n')
        obj = self.scratch / 'symbols.o'
        subprocess.run(['clang', '--target=aarch64-linux-gnu', '-c', str(source), '-o', str(obj)], check=True, capture_output=True)
        imports, exports = M['resource_symbols'](obj)
        self.assertEqual(imports, ['missing'])
        self.assertEqual([r['name'] for r in exports], ['provider'])
        source.write_text(source.read_text().replace('.asciz "provider"', '.asciz "imposter"'))
        subprocess.run(['clang', '--target=aarch64-linux-gnu', '-c', str(source), '-o', str(obj)], check=True, capture_output=True)
        with self.assertRaisesRegex(ValueError, 'target/name differs'):
            M['resource_symbols'](obj)

    def test_original_resource_bool_is_explicit(self):
        for value in (None, 'all', 1):
            with self.assertRaisesRegex(ValueError, 'Explicit bool'):
                M['build'](self.scratch, RUNTIME, self.scratch / 'absent', mode='official', original_resources=value)
        self.assertFalse((self.scratch / 'absent').exists())

    def module_shim(self, path='/usr/kmod/osal_uipc.ko', *, digest_ok=True):
        simulation = self.scratch / 'simulation'; simulation.mkdir()
        (simulation / 'original-modules').write_text(f'{path} 123 {"a" * 64}\n')
        audit = simulation / 'audit'
        audit.write_text('#!/bin/sh\nexit ' + ('0' if digest_ok else '7') + '\n'); audit.chmod(0o755)
        bb = self.scratch / 'busybox'
        bb.write_text('#!/usr/bin/python3\nimport json,os,sys\n'
            'if sys.argv[1] == "rm": sys.exit(0)\n'
            'assert sys.argv[1] == "insmod"\n'
            'open(os.environ["ARGV_LOG"],"w").write(json.dumps(sys.argv[2:]))\n'
            'sys.exit(int(os.environ.get("TEST_RC","0")))\n'); bb.chmod(0o755)
        text = (HERE / 'guest/update-storage-bootstrap').read_text()
        text = text.replace('/simulation/', str(simulation) + '/').replace('bb=/bin/busybox', 'bb=' + str(bb))
        shim = self.scratch / 'insmod'; shim.write_text(text)
        return shim, dict(os.environ, ARGV_LOG=str(self.scratch / 'argv.json'), TEST_RC='17')

    def test_original_module_real_returncode_and_literal_argument_boundaries(self):
        shim, env = self.module_shim()
        arguments = ['/usr/kmod/osal_uipc.ko', 'literal=$(touch ' + str(self.scratch / 'BAD') + ')', 'space=a b', 'semi=;false']
        result = subprocess.run(['/bin/sh', str(shim), *arguments], capture_output=True, env=env)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(json.loads((self.scratch / 'argv.json').read_text()), arguments)
        self.assertIn(b'original_module_rc=17', result.stdout)
        self.assertFalse((self.scratch / 'BAD').exists())

    def test_original_module_missing_policy_digest_path_and_force_rejected(self):
        shim, env = self.module_shim(digest_ok=False)
        for args in (['/usr/kmod/osal_uipc.ko'], ['/tmp/osal_uipc.ko'], ['osal_uipc.ko'],
                     ['/usr/kmod/../kmod/osal_uipc.ko'], ['/usr/kmod/osal_uipc.ko', '-f'], ['/usr/kmod/pciedma.ko']):
            result = subprocess.run(['/bin/sh', str(shim), *args], capture_output=True, env=env)
            self.assertEqual(result.returncode, 125, args)
        self.assertFalse((self.scratch / 'argv.json').exists())
        (self.scratch / 'simulation/original-modules').unlink()
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/osal_uipc.ko'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 125)

    def test_backup_save_nonzero_and_unbound_cleanup_rejected(self):
        shim, env = self.module_shim('/usr/kmod/backup.ko')
        for args in (['Backup_save=1'], ['Backup_save=0', 'Backup_save=1'], ['Backup_save=0', 'Backup_pri_file=/tmp/new']):
            result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/backup.ko', *args], capture_output=True, env=env)
            self.assertEqual(result.returncode, 125)
        self.assertFalse((self.scratch / 'argv.json').exists())
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/backup.ko', 'Backup_save=0'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 17)
        rmmod = self.scratch / 'rmmod'; rmmod.symlink_to(shim)
        result = subprocess.run(['/bin/sh', str(rmmod), 'backup'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 125)

    def test_backup_file_load_requires_readonly_and_preserves_original_arguments(self):
        shim, env = self.module_shim('/usr/kmod/backup.ko')
        simulation = self.scratch / 'simulation'
        (simulation / 'backup-file-source').write_text('/setting/Backup.bin 123 ' + 'b' * 64 + '\n')
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/backup.ko', 'Backup_save=0'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 125)
        self.assertFalse((self.scratch / 'argv.json').exists())
        (simulation / 'read-only-probe').touch()
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/backup.ko', 'Backup_save=0'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(json.loads((self.scratch / 'argv.json').read_text()),
                         ['/usr/kmod/backup.ko', 'Backup_save=0', 'Backup_load=1'])
        self.assertIn(b'UPDATE_BACKUP_FILE bytes=123', result.stdout)
        self.assertIn(b'original_argv=preserved', result.stdout)

    def test_media_paths_need_explicit_profile_and_forbid_module_parameters(self):
        shim, env = self.module_shim('/usr/kmod/stream2.ko')
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/stream2.ko'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 125)
        simulation = self.scratch / 'simulation'
        (simulation / 'media-profile').write_text('original-p1-media-readonly-v1\n')
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/stream2.ko', 'skipprobe=1'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 125)
        self.assertFalse((self.scratch / 'argv.json').exists())
        result = subprocess.run(['/bin/sh', str(shim), '/usr/kmod/stream2.ko'], capture_output=True, env=env)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(json.loads((self.scratch / 'argv.json').read_text()), ['/usr/kmod/stream2.ko'])

    def test_bootstrap_rejects_modules_without_success_reply(self):
        script = HERE / 'guest/update-storage-bootstrap'
        alias = self.scratch / 'insmod'
        alias.symlink_to(script)
        result = subprocess.run(['/bin/sh', str(alias), '/kmod/crypt-emmc.ko'], capture_output=True)
        self.assertEqual(result.returncode, 125)
        self.assertIn(b'original_module_rc=notexecuted', result.stderr)
        self.assertNotIn(b'ready', result.stdout.lower())
        self.assertNotIn(b'ACK', result.stdout)


class DevStagePipeline(unittest.TestCase):
    def test_synthetic_host_stage_preserves_original_and_pins_executor_input(self):
        """Execute production stage/loop AST with typed host ELF, never firmware/build/VM."""
        fixture = runpy.run_path(str(HERE / 'test-dev-update-profile.py'))
        profile = fixture['PROFILE']
        executor = runpy.run_path(str(HERE / 'p1-update-execution.py'))
        relative = 'usr/lib/libsdfileinputupdaterapi.so'
        original = fixture['fixture']().ljust(60600, b'\0')
        facts = dict(size=len(original), sha256=hashlib.sha256(original).hexdigest())
        real_run_path = runpy.run_path

        def load(path):
            return vars(profile) if Path(path).name == 'dev-update-profile.py' else real_run_path(path)

        def execute(name, kind, predicate, environment):
            nodes = [node for node in ast.walk(ast.parse((HERE / name).read_text()))
                     if isinstance(node, kind) and predicate(node)]
            self.assertEqual(len(nodes), 1)
            code = compile(ast.Module(body=nodes, type_ignores=[]), '<synthetic-host-stage>', 'exec')
            exec(code, environment)

        with tempfile.TemporaryDirectory(prefix='p1-dev-stage-') as temporary:
            output = Path(temporary)
            root = output / 'root'
            simulation = root / 'simulation'
            simulation.mkdir(parents=True)
            receiver = root / relative
            receiver.parent.mkdir(parents=True)
            receiver.write_bytes(original)
            old_row = M['record'](receiver)
            report = dict(sd=dict(synthetic_host_fixture=True), mode=M['MODES'][1],
                          original_files={relative: dict(old_row)})
            environment = dict(M, report=report, root=root, simulation=simulation,
                               output=output, mode=report['mode'])
            with patch.object(profile, '_SOURCE_FACTS', facts), patch.object(runpy, 'run_path', side_effect=load):
                execute('update-boot.py', ast.If,
                        lambda node: ast.unparse(node.test) == 'mode == MODES[1]', environment)
                saved_row = report['original_files'][relative]
                saved = Path(saved_row['path'])
                self.assertEqual(saved, output / 'original-libsdfileinputupdaterapi.so')
                self.assertEqual(saved.read_bytes(), original)
                self.assertEqual(saved.stat().st_mode & 0o777, 0o444)
                self.assertNotEqual(saved.stat().st_ino, receiver.stat().st_ino)
                self.assertEqual(report['receiver']['source']['path'], str(saved))
                for field in ('bytes', 'sha256'):
                    self.assertEqual(saved_row[field], old_row[field])
                current = receiver.read_bytes()
                self.assertEqual(len(current), 60600)
                self.assertEqual([i for i, (a, b) in enumerate(zip(original, current)) if a != b],
                                 list(range(0xae08, 0xae0c)))
                self.assertEqual(current[0xae08:0xae14].hex(), '200080521f04007140010054')
                # The old in-place row fails while the independent saved original stays valid.
                with self.assertRaisesRegex(ValueError, 'Input bytes differ'):
                    executor['checked'](old_row)
                executor['checked'](saved_row)
                execution = dict(executor, UPDATE=M, update=report, root=root, inputs=[], originals={},
                                 expected_files={relative: facts | dict(bytes=len(original))})
                execute('p1-update-execution.py', ast.For,
                        lambda node: ast.unparse(node.iter) == "update['original_files'].items()", execution)
                self.assertEqual(len(execution['inputs']), 1)
                self.assertEqual(execution['inputs'][0]['path'], str(saved))
                self.assertEqual(execution['originals']['/' + relative]['sha256'],
                                 hashlib.sha256(current).hexdigest())
                saved.chmod(0o600)
                saved.write_bytes(original[:-1] + b'X')
                saved.chmod(0o444)
                with self.assertRaisesRegex(ValueError, 'Input bytes differ'):
                    executor['checked'](execution['inputs'][0])
                saved.chmod(0o600)
                saved.write_bytes(original)
                saved.chmod(0o444)
                executor['checked'](execution['inputs'][0])
                damaged = bytearray(current)
                damaged[0x300] ^= 1
                receiver.write_bytes(damaged)
                forged = json.loads(json.dumps(report['receiver']))
                forged['output']['sha256'] = hashlib.sha256(damaged).hexdigest()
                with self.assertRaisesRegex(ValueError, 'outside the prescribed four-byte patch'):
                    profile.verify_derived_receiver(receiver, forged)


@unittest.skipUnless(REAL_STAGE, 'set A7C2_UPDATE_BOOT_TEST_STAGE for real p1 build receipts')
class OriginalBuilds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stage = Path(REAL_STAGE)
        cls.stock = json.loads((cls.stage / 'official-build-v3/update-boot.json').read_text())
        cls.dev = json.loads((cls.stage / 'dev-build-v2/update-boot.json').read_text())

    def test_real_p1_kernel_and_original_root_bound(self):
        for report in (self.stock, self.dev):
            self.assertEqual(report['status'], 'built', report.get('error'))
            self.assertEqual(M['record'](report['boot']['kernel'])['sha256'], M['KERNEL_SHA'])
            self.assertEqual(M['record'](report['p1']['p1-root.squashfs']['path'])['sha256'], M['ROOT_SHA'])
            self.assertEqual(report['sources']['p1']['sha256'], report['sources']['p1']['source_sha256'])
            self.assertFalse(report['source_dump_opened_writable'])
            self.assertFalse(report['physical_devices_used'])

    def test_official_vs_development_is_exact_four_bytes(self):
        stock = Path(self.stock['output']) / 'root/usr/lib/libsdfileinputupdaterapi.so'
        dev = Path(self.dev['output']) / 'root/usr/lib/libsdfileinputupdaterapi.so'
        before, after = stock.read_bytes(), dev.read_bytes()
        offset = 0xae08
        self.assertEqual(len(before), len(after))
        self.assertEqual(before[:offset], after[:offset])
        self.assertEqual(before[offset + 4:], after[offset + 4:])
        self.assertEqual(before[offset:offset + 4].hex(), '72f1ff97')
        self.assertEqual(after[offset:offset + 4].hex(), '20008052')
        self.assertFalse(self.stock['bypass_configured'])
        self.assertTrue(self.dev['bypass_configured'])
        self.assertFalse(self.dev['bypass_executed'])

    def test_p2_is_actual_fat_and_never_a_claimed_menu_visit(self):
        for report in (self.stock, self.dev):
            p2 = report['p2']
            self.assertFalse(p2['flags']['mode'])
            self.assertFalse(p2['flags']['mode5'])
            self.assertTrue(p2['flags']['comp'])
            self.assertFalse(p2['flags']['uincomp'])
            self.assertEqual(p2['predicted_outer_mode'], 1)
            self.assertEqual(p2['normal_ap_frontend'], 'notexecuted')
            self.assertFalse(report['menu_entry_verified'])

    def test_instance_identity_geometry_and_abi_blocker_preserved(self):
        for report in (self.stock, self.dev):
            instance = report['instance']
            current = M['record'](Path(instance['path']) / 'camera.emmc')
            for field in ('path', 'device', 'inode', 'bytes'):
                self.assertEqual(current[field], instance['disk'][field], field)
            # Persistent contents may change after this build under a later owner.
            for part in ('p1', 'p2'):
                self.assertEqual(M['record'](report['sources'][part]['path'])['sha256'],
                                 report['sources'][part]['source_sha256'])
            self.assertEqual(M['record'](instance['geometry']['path']), instance['geometry'])
            self.assertEqual(instance['user_bytes'], 1864 * 1024**2)
            self.assertEqual(instance['container_bytes'], (1864 + 8) * 1024**2)
            self.assertTrue(instance['same_fd_for_all_flash_slices'])
            self.assertTrue(instance['boot_areas_separate'])
            self.assertEqual(report['module_abi']['kernel_release'], '4.9.186-scel')
            self.assertFalse(report['module_abi']['force_load_allowed'])
            self.assertFalse(report['boot']['launch_preflight_passed'])

    def test_real_bodydata_is_in_ordinary_fat_and_not_installed(self):
        sd = self.dev['sd']
        self.assertGreater(sd['bodydata']['size'], 1024**3)
        created = json.loads((self.stage / 'dev-build-v1/update-boot.json').read_text())
        selected = created['sd']['source']['bodydata']
        self.assertEqual(sd['bodydata']['sha256'], M['record'](selected['path'])['sha256'])
        self.assertEqual(sd['image']['sha256'], sd['source']['sha256'])
        self.assertFalse(sd['guest_consumed'])
        for key in ('installation_verified', 'bodywriter_executed', 'original_init_executed',
                    'udtrmain_executed', 'sdfileinput_executed', 'guest_execution_verified'):
            self.assertFalse(self.dev[key], key)
        self.assertIsNone(self.dev['boot']['qemu_command'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
