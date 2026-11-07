#!/usr/bin/env python3
"""Local controller contracts and small real UFU/FDAT fixtures; never starts a VM."""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


DEV = module('firmware_development_tested', HERE / 'firmware-development.py')
FIXTURE = module('firmware_development_update_fixture', HERE / 'test-virtual-update.py')


class FirmwareDevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='firmware-development-test-')
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir(mode=0o700)
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.disk = self.root / 'instance.raw'
        self.disk.write_bytes(b'local-test-disk' * 512)
        self.disk.chmod(0o600)
        self.manifest = self.root / 'instance.json'
        DEV.write_json(self.manifest, {'test_fixture_only': True})
        info = self.disk.stat()
        self.instance = {'id': 'test-one-instance', 'generation': 3, 'disk': str(self.disk),
                         'manifest': str(self.manifest), 'dev': info.st_dev, 'ino': info.st_ino,
                         'bytes': info.st_size, 'geometry_sha256': 'a' * 64}
        self.context_path = self.root / 'context.json'
        self.context = {'schema': DEV.CONTEXT_SCHEMA, 'workspace': str(self.workspace),
                        'runtime': str(self.runtime), 'instance_identity': self.instance,
                        'routes': {'root': copy.deepcopy(self.instance), 'bodydata': copy.deepcopy(self.instance)},
                        'runtime_state': {'actual_ap_sha256': 'b' * 64, 'wbi_state': 'incompatible',
                                          'changed_persistent': True}, 'available_capabilities': {},
                        'package_tools': {'fwtool_dir': str(HERE), 'python': sys.executable}}
        self.save_context()
        self.package = self.root / 'literal ; $(touch injected) `echo BAD` BODYDATA.DAT'
        tar, _ = FIXTURE.tar_bytes()
        self.clear = FIXTURE.fdat_bytes(tar)
        self.package.write_bytes(FIXTURE.package_bytes(self.clear))
        self.package.chmod(0o600)
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def save_context(self):
        DEV.write_json(self.context_path, self.context)

    def args(self, action='status', **values):
        result = argparse.Namespace(action=action, target='cold', context=self.context_path,
                                    package=self.package, profile='official', virtual_dev_update=False)
        for key, value in values.items():
            setattr(result, key, value)
        return result

    def capability(self, action, *, audit=True):
        value = {'available': True, 'contract': DEV.SCHEMA,
                 'instance_identity': copy.deepcopy(self.instance)}
        if action in ('hot', 'sequence') and audit:
            proof = self.root / 'retained-audit.json'
            DEV.write_json(proof, {'fixture_only': True})
            value['retained_audit'] = {'complete': True, 'compatible': True,
                                      'external_state_verified': True, 'instance_identity': copy.deepcopy(self.instance),
                                      'evidence': str(proof)}
        if action == 'sequence' and audit:
            proof.write_bytes(DEV.RETAINED_PROOF.read_bytes())
            value['retained_audit'].update(evidence_sha256=hashlib.sha256(proof.read_bytes()).hexdigest(),
                profile=DEV.RETAINED_PROFILE, qemu_sha256=DEV.RETAINED_QEMU_SHA,
                source_tree_sha256=DEV.RETAINED_SOURCE_SHA, scope=DEV.RETAINED_SCOPE)
            (self.runtime / 'analysis').mkdir(exist_ok=True)
            value.update(runtime_analysis=str(self.runtime / 'analysis'), origin_qemu_build=str(self.runtime),
                backend_source={'path': str(HERE / 'retained-camera-test.py'),
                                'sha256': hashlib.sha256((HERE / 'retained-camera-test.py').read_bytes()).hexdigest()})
            for name in ('cold_manifest', 'combo_manifest', 'persistent_module'):
                path = self.root / (name + '.json')
                DEV.write_json(path, {'host_fixture_only': True})
                value[name] = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        self.context['available_capabilities'][action] = value
        self.save_context()

    def controller_runner(self, argv, **kwargs):
        self.calls.append(argv)
        self.assertNotIn('shell', kwargs)
        self.assertNotIn('timeout', kwargs)
        self.assertEqual(argv[-2], '--firmware-development-request')
        request = DEV.read_json(argv[-1])
        directory = Path(request['output_dir'])
        stages = {}
        for stage in request['required_stages']:
            evidence = directory / (stage + '.json')
            contents = {'mock_runner_only': True, 'stage': stage}
            if request['action'] in ('sequence', 'hot'):
                contents.update({key: request[key] for key in ('schema', 'job_id', 'run_id', 'instance_identity', 'action')})
                contents.update(verified=True, sony_wbi_verified=False, hardware_hotboot_verified=False, capture_verified=False)
            DEV.write_json(evidence, contents)
            stages[stage] = {'verified': True, 'path': str(evidence),
                             'sha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
                             'execution_kind': 'persistent_device' if stage in DEV.PERSISTENT_STAGES else 'guest_original'}
        receipt = {key: request[key] for key in ('schema', 'job_id', 'run_id', 'instance_identity', 'action')}
        receipt.update(status='completed', stages=stages)
        DEV.write_json(Path(request['controller_result']), receipt)
        return subprocess.CompletedProcess(argv, 0)

    def assert_blocked(self, result, code):
        self.assertEqual(result['status'], 'blocked', result)
        self.assertEqual(result['blocked_reason']['code'], code, result)

    def test_status_reads_explicit_context_and_observed_values(self):
        result = DEV.dispatch(self.args(), runner=lambda *_args, **_kw: self.fail('status launched process'))
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['ap_sha'], 'b' * 12)
        self.assertEqual(result['instance'], self.instance['id'])
        self.assertEqual(result['wbi'], 'incompatible')
        self.context['runtime_state']['actual_ap_sha256'] = 'selected-file-not-running'
        self.save_context()
        self.assertEqual(DEV.dispatch(self.args())['ap_sha'], '未观测')

    def test_context_private_owned_regular_bounded_and_no_links(self):
        self.context_path.chmod(0o644)
        self.assert_blocked(DEV.dispatch(self.args()), 'private_path_required')
        self.context_path.chmod(0o600)
        link = self.root / 'link.json'
        link.symlink_to(self.context_path)
        self.assert_blocked(DEV.dispatch(self.args(context=link)), 'symlink_path')
        hardlink = self.root / 'hardlink.json'
        os.link(self.context_path, hardlink)
        self.assert_blocked(DEV.dispatch(self.args()), 'unowned_path')
        hardlink.unlink()
        self.context_path.write_text(' ' * (DEV.LIMIT + 1))
        self.assert_blocked(DEV.dispatch(self.args()), 'invalid_json_file')
        self.context_path.write_text('{"schema":1,"schema":2}')
        self.assert_blocked(DEV.dispatch(self.args()), 'duplicate_json_key')
        for path in ('relative.json', '/dev/null', '/tmp/../context.json', '/tmp/a\n.json'):
            with self.assertRaises((DEV.Blocked, FileNotFoundError)):
                DEV.path_checked(path)

    def test_missing_binding_never_selects_another_source(self):
        self.context.pop('instance_identity')
        self.context['sources'] = ['official', 'private']
        self.save_context()
        result = DEV.dispatch(self.args('cold'), runner=lambda *_a, **_k: self.fail('fallback'))
        self.assert_blocked(result, 'instance_not_bound')
        self.assertTrue(Path(result['first_error_path']).is_file())
        self.assertTrue(Path(result['result_path']).is_file())

    def test_root_and_bodydata_require_one_instance_for_both_routes(self):
        for target in ('file-test', 'update'):
            self.capability(target)
            self.context['routes']['bodydata']['generation'] = 99
            self.save_context()
            self.assert_blocked(DEV.dispatch(self.args(target), support=lambda _: True,
                                             runner=lambda *_a, **_k: self.fail('route mismatch executed')),
                                'route_instance_mismatch')
        self.assertEqual(self.disk.read_bytes(), b'local-test-disk' * 512)

    def test_disk_inode_and_geometry_cannot_be_guessed(self):
        self.disk.rename(self.root / 'saved-disk.raw')
        self.disk.write_bytes(b'replacement')
        self.assert_blocked(DEV.dispatch(self.args('cold')), 'instance_changed')
        self.disk.unlink()
        (self.root / 'saved-disk.raw').rename(self.disk)
        self.context['instance_identity']['geometry_sha256'] = ''
        self.save_context()
        self.assert_blocked(DEV.dispatch(self.args('cold')), 'geometry_not_bound')

    def test_unknown_profile_and_signature_scope_never_fall_back(self):
        for args, code in [(self.args('cold', profile='unknown'), 'unknown_profile'),
                           (self.args('cold', profile='virtual-dev', virtual_dev_update=True), 'signature_scope'),
                           (self.args('update', virtual_dev_update=True), 'signature_scope'),
                           (self.args('update', profile='virtual-dev'), 'signature_scope')]:
            self.assert_blocked(DEV.dispatch(args, runner=lambda *_a, **_k: self.fail('fallback')), code)

    def test_hot_and_sequence_audit_block_before_cold_is_started(self):
        for target in ('hot', 'sequence'):
            self.capability(target, audit=False)
            self.assert_blocked(DEV.dispatch(self.args(target), support=lambda _: True,
                                             runner=lambda *_a, **_k: self.fail('cold fallback')),
                                'retained_audit_required')

    def test_no_capability_and_legacy_copy_controller_stay_blocked(self):
        self.assert_blocked(DEV.dispatch(self.args('cold')), 'required_stage_unavailable')
        self.capability('workspace-overwrite')
        self.assert_blocked(DEV.dispatch(self.args('workspace-overwrite'), support=lambda _: False,
                                         runner=lambda *_a, **_k: self.fail('legacy copy')),
                            'controller_not_integrated')

    def test_controller_marker_is_literal_and_has_no_import_side_effect(self):
        source = self.root / 'controller.py'
        source.write_text('FIRMWARE_DEVELOPMENT_API = 1\nraise RuntimeError("must not import")\n')
        self.assertTrue(DEV.controller_supported(source))
        source.write_text('FIRMWARE_DEVELOPMENT_API = True\n')
        self.assertFalse(DEV.controller_supported(source))
        source.write_text('FIRMWARE_DEVELOPMENT_API = int("1")\n')
        self.assertFalse(DEV.controller_supported(source))

    def test_plan_launches_nothing_and_records_required_stages(self):
        self.capability('cold')
        result = DEV.dispatch(self.args('plan'), support=lambda _: True,
                              runner=lambda *_a, **_k: self.fail('plan launched process'))
        self.assertEqual(result['status'], 'planned')
        self.assertIn('original_init_cold', result['plan']['required_stages'])
        self.assertIn('system_runtime', result['plan']['required_stages'])
        self.assertFalse(result['plan']['cold_fallback_allowed'])

    def test_bound_controller_called_with_fixed_literal_argv(self):
        self.capability('cold')
        result = DEV.dispatch(self.args('cold'), runner=self.controller_runner, support=lambda _: True)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(Path(self.calls[0][2]), HERE / 'boot-session.py')
        self.assertEqual(len(self.calls[0]), 5)
        request = DEV.read_json(self.calls[0][-1])
        self.assertEqual(request['boot_profile'], 'original-init-cold')
        self.assertEqual(request['instance_identity'], self.instance)
        self.assertEqual(request['profile'], 'official')
        self.assertNotIn('--functional-install', self.calls[0])

    def test_sequence_uses_same_fixed_controller_and_unique_qemu_profile(self):
        self.capability('sequence')
        result = DEV.dispatch(self.args('sequence'), runner=self.controller_runner, support=lambda _: True)
        self.assertEqual(result['status'], 'completed', result)
        request = DEV.read_json(self.calls[0][-1])
        self.assertEqual(request['boot_profile'], 'qemu-retained-roundtrip')
        self.assertEqual(request['required_stages'], list(DEV.STAGES['sequence']))
        self.assertEqual(request['instance_identity'], self.instance)
        self.assertEqual(request['signature_policy'], 'verify-official')
        self.assertEqual(Path(self.calls[0][2]), HERE / 'boot-session.py')

    def test_live_hot_requires_reviewed_actual_and_explicit_owner_binding(self):
        self.capability('hot')
        self.assert_blocked(DEV.dispatch(self.args('plan', target='hot'), support=lambda _: True), 'live_owner_required')
        self.capability('sequence')
        live = DEV.live_module()
        proof = self.root / 'live-validation.json'
        report = dict(schema=live.SCHEMA, status='passed', actual_content_verified=True, owners_closed=True,
            instance_identity=self.instance, profile=DEV.RETAINED_PROFILE, qemu_sha256=DEV.RETAINED_QEMU_SHA,
            source_tree_sha256=DEV.RETAINED_SOURCE_SHA, source_bindings=live.SOURCE_BINDINGS, **live.LIMITS)
        DEV.write_json(proof, report)
        self.context['available_capabilities']['hot'] = dict(available=True, contract=DEV.SCHEMA,
            instance_identity=self.instance, retained_audit=copy.deepcopy(self.context['available_capabilities']['sequence']['retained_audit']),
            backend_source=dict(path=str(HERE / 'retained-camera-live.py'), sha256=hashlib.sha256((HERE / 'retained-camera-live.py').read_bytes()).hexdigest()),
            live_owner=dict(path='/host-fixture-only/live-owner.json', sha256='f' * 64),
            live_validation=dict(path=str(proof), sha256=hashlib.sha256(proof.read_bytes()).hexdigest()))
        self.save_context()
        observed = []
        with patch.object(DEV, 'live_module', return_value=type('HostOnly', (), {
                'SOURCE_BINDINGS': live.SOURCE_BINDINGS,
                'inspect_owner': staticmethod(lambda row, instance: observed.append((row, instance)))})()):
            result = DEV.dispatch(self.args('hot'), runner=self.controller_runner, support=lambda _: True)
            self.assertEqual(result['status'], 'completed', result)
            request = DEV.read_json(self.calls[-1][-1])
            self.assertEqual(request['boot_profile'], 'qemu-live-retained-roundtrip')
            self.assertTrue(observed)
            report['actual_content_verified'] = False
            DEV.write_json(proof, report)
            self.context['available_capabilities']['hot']['live_validation']['sha256'] = hashlib.sha256(proof.read_bytes()).hexdigest()
            self.save_context()
            self.assert_blocked(DEV.dispatch(self.args('plan', target='hot'), support=lambda _: True), 'live_actual_validation_required')

    def test_sequence_stage_false_contents_and_other_job_are_rejected(self):
        self.capability('sequence')
        for mutation in ('verified', 'job_id', 'sony_wbi_verified'):
            def runner(argv, **kwargs):
                completed = self.controller_runner(argv, **kwargs)
                request = DEV.read_json(argv[-1]); path = Path(request['controller_result'])
                receipt = DEV.read_json(path); stage = receipt['stages']['retained_restore']
                evidence = Path(stage['path']); content = DEV.read_json(evidence)
                content[mutation] = 'another-job' if mutation == 'job_id' else mutation != 'verified'
                DEV.write_json(evidence, content)
                stage['sha256'] = hashlib.sha256(evidence.read_bytes()).hexdigest()
                DEV.write_json(path, receipt)
                return completed
            self.assert_blocked(DEV.dispatch(self.args('sequence'), runner=runner, support=lambda _: True),
                                'required_stage_unverified')

    def test_sequence_capability_is_not_automatically_published(self):
        self.capability('cold')
        before = self.context_path.read_bytes()
        self.assert_blocked(DEV.dispatch(self.args('sequence'), runner=lambda *_a, **_k: self.fail('automatic fallback')),
                            'required_stage_unavailable')
        self.assertEqual(self.context_path.read_bytes(), before)

    def test_stdout_ack_wrong_binding_missing_stages_and_host_functional_are_not_success(self):
        self.capability('cold')
        for mutation, code in [('instance', 'receipt_binding'), ('stage', 'required_stage_unverified'),
                               ('host', 'required_stage_unverified'), ('hash', 'evidence_hash')]:
            def runner(argv, **kwargs):
                completed = self.controller_runner(argv, **kwargs)
                request = DEV.read_json(argv[-1])
                path = Path(request['controller_result'])
                receipt = DEV.read_json(path)
                if mutation == 'instance':
                    receipt['instance_identity']['generation'] += 1
                elif mutation == 'stage':
                    receipt['stages'].pop('system_runtime')
                elif mutation == 'host':
                    receipt['stages']['system_runtime']['execution_kind'] = 'host_functional'
                else:
                    receipt['stages']['system_runtime']['sha256'] = '0' * 64
                DEV.write_json(path, receipt)
                return completed
            self.assert_blocked(DEV.dispatch(self.args('cold'), runner=runner, support=lambda _: True), code)

    def test_controller_exit_code_cannot_promote_complete_receipt(self):
        self.capability('cold')
        def runner(argv, **kwargs):
            self.controller_runner(argv, **kwargs)
            return subprocess.CompletedProcess(argv, 1)
        self.assert_blocked(DEV.dispatch(self.args('cold'), runner=runner, support=lambda _: True), 'controller_failed')

    def test_signature_policy_never_bypasses_crc(self):
        for signature in ('invalid', 'unknown'):
            inspection = {'outer_crc_valid': True, 'signature': {'status': signature}}
            with self.assertRaises(DEV.Blocked):
                DEV.signature_policy(inspection, False)
            result = DEV.signature_policy(inspection, True)
            self.assertTrue(result['bypassed'])
            self.assertEqual(result['observed'], signature)
            inspection['outer_crc_valid'] = False
            with self.assertRaises(DEV.Blocked):
                DEV.signature_policy(inspection, True)
        self.assertFalse(DEV.signature_policy({'outer_crc_valid': True, 'signature': {'status': 'valid'}}, False)['bypassed'])

    def test_real_ufu_crc_and_official_signature_gate(self):
        args = self.args('_inspect')
        result = DEV.dispatch(args)
        self.assert_blocked(result, 'signature_not_verified')
        inspection = DEV.read_json(Path(result['record_dir']) / 'package/ufu-inspection.json')
        self.assertTrue(inspection['outer_crc_valid'])
        self.assertEqual(inspection['signature']['status'], 'unknown')
        data = bytearray(self.package.read_bytes())
        data[65] ^= 1
        self.package.write_bytes(data)
        result = DEV.dispatch(self.args('_inspect', profile='virtual-dev', virtual_dev_update=True))
        self.assertEqual(result['status'], 'failed', result)
        self.assertIn('CRC', result['message'])

    def test_real_fdat_header_crc_and_section_inspection_with_explicit_fixture_decoder(self):
        # The fixture decoder is not production crypto; actual UFU/FDAT checks
        # remain the existing implementation. It cannot assert guest install.
        def decoder(src, dst, fwtool):
            metadata = FIXTURE.plaintext_decoder(src, dst, fwtool)
            metadata['block_checksums_valid'] = True
            return metadata
        with patch.object(DEV, 'update_module', return_value=FIXTURE.UPDATE), \
                patch.object(FIXTURE.UPDATE, '_default_decoder', decoder):
            result = DEV.dispatch(self.args('_inspect', profile='virtual-dev', virtual_dev_update=True))
        self.assertEqual(result['status'], 'completed', result)
        self.assertTrue(result['inspection']['header_crc_valid'])
        self.assertFalse(result['guest_original_install_verified'])
        self.assertTrue(result['signature_policy']['bypassed'])
        self.assertEqual(result['signature_policy']['observed'], 'unknown')
        bad = bytearray(self.clear)
        bad[42] ^= 1
        self.package.write_bytes(FIXTURE.package_bytes(bad))
        with patch.object(DEV, 'update_module', return_value=FIXTURE.UPDATE), \
                patch.object(FIXTURE.UPDATE, '_default_decoder', decoder):
            result = DEV.dispatch(self.args('_inspect', profile='virtual-dev', virtual_dev_update=True))
        self.assertEqual(result['status'], 'failed')
        self.assertIn('FDAT header CRC', result['message'])

    def test_validation_standalone_process_receipt_and_literal_package_path(self):
        def runner(argv, **kwargs):
            self.calls.append(argv)
            self.assertEqual(argv[2], str(HERE / 'firmware-development.py'))
            self.assertEqual(argv[3], '_inspect')
            self.assertEqual(argv[argv.index('--package') + 1], str(self.package))
            result = {'schema': DEV.SCHEMA, 'action': '_inspect', 'status': 'blocked',
                      'blocked_reason': {'code': 'signature_not_verified', 'detail': 'invalid signature'}}
            kwargs['stdout'].write(json.dumps(result))
            return subprocess.CompletedProcess(argv, 2)
        result = DEV.dispatch(self.args('validate-package'), runner=runner)
        self.assert_blocked(result, 'signature_not_verified')
        self.assertEqual(len(self.calls), 1)
        self.assertFalse((self.root / 'injected').exists())

    def test_update_does_not_start_receiver_after_invalid_signature(self):
        self.capability('update')
        def runner(argv, **kwargs):
            self.assertEqual(argv[3], '_inspect', 'receiver must not start')
            result = {'schema': DEV.SCHEMA, 'action': '_inspect', 'status': 'blocked',
                      'blocked_reason': {'code': 'signature_not_verified', 'detail': 'invalid signature'}}
            kwargs['stdout'].write(json.dumps(result))
            return subprocess.CompletedProcess(argv, 2)
        self.assert_blocked(DEV.dispatch(self.args('update'), runner=runner, support=lambda _: True), 'signature_not_verified')

    def test_cli_emits_structured_blocked_and_real_standalone_validation(self):
        result = subprocess.run([sys.executable, '-B', str(HERE / 'firmware-development.py'),
                                 'validate-package', '--context', str(self.context_path), '--package', str(self.package)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)['blocked_reason']['code'], 'signature_not_verified')
        result = subprocess.run([sys.executable, '-B', str(HERE / 'firmware-development.py'), 'hot',
                                 '--context', str(self.context_path), '--human'], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith('FIRMWARE_DEV_V1\n'))
        self.assertIn('status=blocked\n', result.stdout)
        self.assertTrue(result.stdout.rstrip().endswith('END'))

    def test_same_instance_root_and_update_reach_fixed_controllers(self):
        for target in ('file-test', 'update'):
            self.capability(target)
        def runner(argv, **kwargs):
            if argv[3] != '_inspect':
                return self.controller_runner(argv, **kwargs)
            # Explicit mock crypto worker, not real signature or VM evidence.
            result_path = Path(kwargs['stdout'].name).parent / 'mock-inspection.json'
            child = {'schema': DEV.SCHEMA, 'action': '_inspect', 'status': 'completed',
                     'message': 'mock crypto result', 'result_path': str(result_path),
                     'package_sha256': hashlib.sha256(self.package.read_bytes()).hexdigest()}
            DEV.write_json(result_path, child)
            kwargs['stdout'].write(json.dumps(child))
            self.assertIn('--virtual-dev-update', argv)
            return subprocess.CompletedProcess(argv, 0)
        root = DEV.dispatch(self.args('file-test'), runner=runner, support=lambda _: True)
        update = DEV.dispatch(self.args('update', profile='virtual-dev', virtual_dev_update=True),
                              runner=runner, support=lambda _: True)
        self.assertEqual(root['status'], 'completed', root)
        self.assertEqual(update['status'], 'completed', update)
        requests = [DEV.read_json(argv[-1]) for argv in self.calls]
        self.assertEqual([row['action'] for row in requests], ['file-test', 'update'])
        self.assertEqual(requests[0]['instance_identity'], requests[1]['instance_identity'])
        self.assertEqual(requests[1]['signature_policy'], 'virtual-device-only-bypass')
        self.assertTrue(requests[1]['package_validation_result'])
        self.assertEqual(self.disk.read_bytes(), b'local-test-disk' * 512)

    def test_real_invalid_rsa_signature_is_never_official_success(self):
        if not shutil.which('openssl') or not (HERE / 'keys/sony-update-public.pem').is_file():
            self.skipTest('existing openssl / pinned public key unavailable')
        self.package.write_bytes(FIXTURE.package_bytes(bytes(272 + 1024)))
        result = DEV.dispatch(self.args('_inspect'))
        self.assert_blocked(result, 'signature_not_verified')
        inspected = DEV.read_json(Path(result['record_dir']) / 'package/ufu-inspection.json')
        self.assertTrue(inspected['outer_crc_valid'])
        self.assertEqual(inspected['signature']['status'], 'invalid')
        self.assertTrue(DEV.signature_policy(inspected, True)['bypassed'])

    def test_human_protocol_encodes_newlines_equals_and_unicode(self):
        result = {'action': 'cold', 'status': 'blocked', 'message': 'line\nEND\na=b 测试',
                  'blocked_reason': {'code': 'not-ready'}}
        text = DEV.human(result)
        self.assertIn('message=line%0AEND%0Aa%3Db%20', text)
        self.assertEqual(text.count('\nEND\n'), 1)


if __name__ == '__main__':
    unittest.main()
