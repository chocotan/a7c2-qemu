"""Concentrated host checks for the passive USB tail; invoke only after integration."""
import ast
import copy
import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def selected_definitions(path, names, namespace):
    tree = ast.parse(path.read_text())
    chosen = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in chosen} != set(names):
        raise ValueError('Missing reviewed definition')
    exec(compile(ast.Module(body=chosen, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def resource_fixture():
    base, pid, tid = 0x100000, 11, 22
    identity = ('USB_START DSO_IDENTITY tid=22 path=/usr/lib/appFw.so map=/usr/lib/appFw.so '
                f'base={base:#x} bytes=99960744 sha256=2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b pid={pid}\n')
    def row(event, text):
        return f'USB_START RESOURCE_{event} pid={pid} tid={tid} serial=1 {text}\n'
    return (identity +
        row('RPC_ENTER', f'destination=0x92840747 request=0x1230 bytes=10 response=0x4560 reply_bytes=12 raw=0d2046010a0001800100 caller={base + 0x34e8b68:#x}') +
        row('RPC_FREE_ENTER', f'owner=0x81cf1234 message=0x7890 source=0x92840747 bytes=12 raw=0d2046110c00018000005900 caller={base + 0x34e57a8:#x}') +
        row('RPC_FREE_RETURN', 'owner=0x81cf1234 message=0x7890 rc=0 errno=71') +
        row('RPC_RETURN', 'response=0x4560 bytes=12 read=1 raw=0d2046110c00018000005900 return_type=void errno=71')).encode()


def direct_touch_fixture():
    lines = resource_fixture().splitlines(keepends=True)
    return b''.join((lines[0], lines[1], lines[4]))


def touch_model_fixture():
    return b'''FULL_TOUCH_PANEL_REQUEST tid=22 destination=0x92840747 source=0x81cf1234 bytes=10 raw=0d2046010a0001800100 virtual_config_only=1
FULL_TOUCH_PANEL_CONFIG enabled=1 profile=virtual-config-v1 original_cp_executed=0 hardware_touch_verified=0
FULL_TOUCH_PANEL_REPLY_QUEUED tid=22 destination=0x81cf1234 source=0x92840747 reply=0x7890 lease=1 bytes=12 raw_status=0x590000 raw=0d2046110c00018000005900
FULL_TOUCH_PANEL_DEVPANEL tid=22 f02f=01202ff00c00010001000000 f02f_destination=0x90590819 vdf_reply_sid=0x9059000e cache=1 readback=1 control_gate_virtual=0 control=0300000001000000 control_submissions=1 control_result_verified=0 f02f_transport_verified=0 original_cp_executed=0 hardware_touch_verified=0
FULL_TOUCH_PANEL_COMMIT tid=22 enable=1 cache=1 readback=1 outer_status=0x590000 applied=1 queued=1 request_free_rc=0 request_retained=0 clean_completion=1 f02f_transport_verified=0 control_result_verified=0 hardware_touch_verified=0 camera_capture_verified=0
FULL_TOUCH_PANEL_REPLY_FREE tid=22 destination=0x81cf1234 reply=0x7890 lease=1 rc=0
'''


class TailObservations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = selected_definitions(HERE / 'usb-ap-probe.py',
            ('classify_usb_message', 'resource_trace_summary'), {'re': re})

    def test_only_exact_wire_and_source_identify_a_message(self):
        classify = self.api['classify_usb_message']
        self.assertEqual(classify(0x90bf0274, 12, '0600a3200000000000000000'), 'ee-capability')
        self.assertEqual(classify(0x92840747, 12, '0d2046110c00018000005900'), 'touch-config-reply')
        self.assertEqual(classify(0x81cf1234, 10, '0d2046010a0001800100'), 'touch-config-request')
        for source, size, raw in ((0x92840747, 12, '0600a3200000000000000000'),
                (0x90bf0274, 12, '0d2046110c00018000005900'),
                (0x81cf1234, 10, '0d2046010a0001800200'),
                (0x80000000, 10, '0d2046010a0001800100'),
                (0x92840747, 10, '0d2046110c00018000005900'),
                (0x92840747, 12, 'unavailable'), (True, 12, '0600a3200000000000000000'),
                (0x90bf0274, 12, '0600a3200000000000000001')):
            with self.subTest(source=source, size=size, raw=raw):
                self.assertEqual(classify(source, size, raw), 'unknown')

    def test_original_touch_boundary_keeps_function_and_hardware_claims_false(self):
        trace = resource_fixture()
        result = self.api['resource_trace_summary'](trace)
        self.assertTrue(result['trace_integrity'], result)
        self.assertTrue(result['original_touch_rpc_complete'], result)
        self.assertEqual(len(result['records']), 4)
        self.assertEqual([row['raw'] for row in result['records']], trace.decode().splitlines()[1:])
        rpc = result['touch_rpc'][0]
        self.assertEqual(rpc['original_free_rc'], 0)
        self.assertEqual(rpc['reply_status'], 0x590000)
        self.assertFalse(rpc['virtual_backend_consumption_verified'])
        for key in ('original_function_bound', 'descriptor_verified', 'configuration_verified',
                    'bulk_verified', 'host_enumerated', 'authentication_verified',
                    'guest_root_over_usb_verified', 'original_cp_history_verified'):
            self.assertFalse(result[key], key)

    def test_incomplete_or_mismatched_touch_cannot_be_promoted(self):
        trace = resource_fixture()
        changes = ((b'destination=0x92840747', b'destination=0x92840748'),
            (b'bytes=10', b'bytes=12'), (b'reply_bytes=12', b'reply_bytes=10'),
            (b'raw=0d2046010a0001800100', b'raw=0d2046010a0001800200'),
            (b'owner=0x81cf1234', b'owner=0x80020002'),
            (b'source=0x92840747', b'source=0x90bf0274'),
            (b'message=0x7890 rc=0', b'message=0x7891 rc=0'),
            (b'rc=0 errno=71', b'rc=-28 errno=28'),
            (b'read=1', b'read=0'), (b'response=0x4560 bytes=12', b'response=0x4561 bytes=12'),
            (b'return_type=void', b'return_type=int'),
            (b'caller=0x35e57a8', b'caller=0x35e57ac'),
            (b'pid=11 tid=22 serial=1 owner=', b'pid=11 tid=23 serial=1 owner='),
            (b'sha256=2ea02f7e', b'sha256=0ea02f7e'))
        for before, after in changes:
            with self.subTest(before=before):
                self.assertIn(before, trace)
                result = self.api['resource_trace_summary'](trace.replace(before, after, 1))
                self.assertFalse(result['original_touch_rpc_complete'], result)
                self.assertIn('error', result)
        lines = trace.splitlines(keepends=True)
        for index in range(1, 5):
            for changed in (b''.join(lines[:index] + lines[index + 1:]), trace + lines[index]):
                result = self.api['resource_trace_summary'](changed)
                self.assertFalse(result['original_touch_rpc_complete'], result)

    def test_budgets_duplicates_and_default_absence_are_strict(self):
        parse = self.api['resource_trace_summary']
        self.assertFalse(parse(b'USB_START INITIALIZED tid=1 pid=1 passive=1\n')['available'])
        row = b'USB_START RESOURCE_NOISE pid=11 tid=22 n=0\n'
        result = parse(row * 64 + b'USB_START RESOURCE_CAP records=64\n')
        self.assertTrue(result['capped'])
        self.assertFalse(result['trace_integrity'])
        self.assertFalse(result['original_touch_rpc_complete'])
        for trace in (row * 65, row + b'USB_START RESOURCE_CAP records=64\n',
                      row * 64 + b'USB_START RESOURCE_CAP records=64\n' + row,
                      row.replace(b'n=0', b'n=0 n=1'),
                      row.replace(b'n=0', b'raw=' + b'a' * 512)):
            self.assertIn('error', parse(trace))

    def test_combined_helper_keeps_the_real_provider_identity(self):
        parse = self.api['resource_trace_summary']; direct = direct_touch_fixture()
        model = touch_model_fixture()
        provider = HERE.parents[1] / 'runtime/analysis/device-models/touch-panel-device.c'
        self.assertIn('enabled=1 profile=virtual-config-v1 original_cp_executed=0 hardware_touch_verified=0', provider.read_text())
        for helper in ('virtual-config-v1', 'virtual-config-tcin-inactive-v1'):
            result = parse(direct, model, virtual_touch_profile=helper)
            self.assertTrue(result['virtual_backend_touch_rpc_complete'], result)
            self.assertEqual(result['virtual_touch_provider_profile'], 'virtual-config-v1')
            self.assertEqual(result['selected_virtual_helper_profile'], helper)
            self.assertEqual(result['touch_rpc'][0]['release_provenance'], 'virtual_backend-direct')
            self.assertFalse(result['original_touch_rpc_complete'])
        for helper in ('', False, 0, 'unknown'):
            rejected = parse(direct, model, virtual_touch_profile=helper)
            self.assertIn('error', rejected)
            self.assertFalse(rejected['virtual_backend_touch_rpc_complete'])

    def test_provider_config_cannot_be_relabelled_missing_or_duplicated(self):
        parse = self.api['resource_trace_summary']; model = touch_model_fixture()
        config = next(line + b'\n' for line in model.splitlines() if line.startswith(b'FULL_TOUCH_PANEL_CONFIG '))
        for changed in (model.replace(b'profile=virtual-config-v1', b'profile=virtual-config-tcin-inactive-v1'),
                        model.replace(b'profile=virtual-config-v1', b'profile=unknown'),
                        model.replace(config, b''), model + config):
            rejected = parse(direct_touch_fixture(), changed, virtual_touch_profile='virtual-config-tcin-inactive-v1')
            self.assertIn('error', rejected)
            self.assertFalse(rejected['virtual_backend_touch_rpc_complete'])
            self.assertFalse(rejected['original_touch_rpc_complete'])

    def test_direct_model_release_has_distinct_provenance(self):
        parse = self.api['resource_trace_summary']
        direct = direct_touch_fixture()
        unbound = parse(direct)
        self.assertTrue(unbound['trace_integrity'], unbound)
        self.assertFalse(unbound['touch_rpc'][0]['complete'])
        self.assertFalse(unbound['original_touch_rpc_complete'])
        result = parse(direct, touch_model_fixture())
        self.assertTrue(result['trace_integrity'], result)
        self.assertTrue(result['virtual_backend_touch_rpc_complete'], result)
        row = result['touch_rpc'][0]
        self.assertEqual(row['release_provenance'], 'virtual_backend-direct')
        self.assertEqual(row['model_direct_reply_free_rc'], 0)
        self.assertNotIn('original_free_rc', row)
        self.assertFalse(row['copied_reply_matches_pre_free'])
        self.assertFalse(row['original_pre_free_observed'])
        self.assertFalse(result['original_touch_rpc_complete'])
        for key in ('original_function_bound', 'descriptor_verified', 'configuration_verified',
                    'bulk_verified', 'host_enumerated', 'authentication_verified',
                    'guest_root_over_usb_verified', 'original_cp_history_verified'):
            self.assertFalse(result[key], key)

    def test_model_lease_commit_and_reply_must_all_match_same_rpc(self):
        parse = self.api['resource_trace_summary']
        model = touch_model_fixture()
        changes = ((b'lease=1 rc=0', b'lease=2 rc=0'),
            (b'reply=0x7890 lease=1 rc=0', b'reply=0x7891 lease=1 rc=0'),
            (b'destination=0x81cf1234 reply=', b'destination=0x81cf1235 reply='),
            (b'cache=1 readback=1', b'cache=1 readback=0'),
            (b'raw_status=0x590000', b'raw_status=0'),
            (b'request_free_rc=0', b'request_free_rc=-28'),
            (b'request_retained=0', b'request_retained=1'),
            (b'clean_completion=1', b'clean_completion=0'),
            (b'lease=1 rc=0', b'lease=1 rc=-1'),
            (b'original_cp_executed=0', b'original_cp_executed=1'),
            (b'virtual_config_only=1', b'virtual_config_only=0'),
            (b'REPLY_FREE tid=22', b'REPLY_FREE tid=23'))
        for before, after in changes:
            with self.subTest(before=before):
                result = parse(direct_touch_fixture(), model.replace(before, after, 1))
                self.assertFalse(result['virtual_backend_touch_rpc_complete'], result)
                self.assertFalse(result['original_touch_rpc_complete'], result)
                self.assertIn('error', result)
        for changed in (b'\n'.join(model.splitlines()[:-1]), model + model,
                        model + b'FULL_TOUCH_PANEL_FAULT reason=retained\n'):
            result = parse(direct_touch_fixture(), changed)
            self.assertFalse(result['virtual_backend_touch_rpc_complete'], result)
            self.assertIn('error', result)
        result = parse(resource_fixture(), model)
        self.assertFalse(result['trace_integrity'], result)
        self.assertFalse(result['original_touch_rpc_complete'], result)

    def test_tcin_shape_is_separate_from_touch_and_ee(self):
        trace = resource_fixture().replace(b'0d2046010a0001800100', b'0d2029040a0001800000')
        trace = trace.replace(b'0d2046110c00018000005900', b'0d2029140c00018000000000')
        trace = trace.replace(b'caller=0x35e8b68', b'caller=0x35ef634')
        result = self.api['resource_trace_summary'](trace)
        self.assertTrue(result['original_tcin_rpc_complete'], result)
        self.assertFalse(result['original_touch_rpc_complete'], result)
        self.assertFalse(result['virtual_backend_touch_rpc_complete'], result)
        self.assertEqual(result['tcin_rpc'][0]['reply_status'], 0)

    def test_model_direct_touch_receipt_cannot_repair_prime_history(self):
        prior = runpy.run_path(str(HERE / 'test-usb-ee-prime-lifecycle.py'))
        trace = prior['kernel_trace']()
        future = prior['event_rows'](trace, 'FREE_RETURN', prior['PRIME_POINTER'])[0]
        result = self.api['resource_trace_summary'](direct_touch_fixture(), touch_model_fixture())
        self.assertTrue(result['virtual_backend_touch_rpc_complete'], result)
        summary = prior['PARSE'](prior['FIXTURE'].capture(trace + direct_touch_fixture() + future),
                                 copy.deepcopy(prior['CONTRACT']), diagnostic_only=True)
        self.assertFalse(summary['native_content_verified'], summary)
        self.assertFalse(summary['resource_safe_to_close'], summary)
        self.assertIn('Prime native pointer reused', summary.get('error', ''))

    def test_native_free_chain_and_default_installation_are_preserved(self):
        source = (HERE / 'usb-start-observe.c').read_text()
        private = selected_definitions(HERE / 'usb-start-observe.py', ('resource_observer_enabled',), {})
        for value in (None, {}, {'diagnostic_checkpoints': False}):
            self.assertIs(private['resource_observer_enabled'](value), False)
        self.assertIs(private['resource_observer_enabled']({'diagnostic_checkpoints': True}), True)
        for value in (0, 1, None, 'true', [], {}):
            with self.assertRaises(ValueError):
                private['resource_observer_enabled']({'diagnostic_checkpoints': value})
        command = ['cc', '-E', '-P', '-DUSB_OBSERVE_HOST_TEST=1', '-I', str(HERE),
                   str(HERE / 'usb-start-observe.c')]
        default = subprocess.run(command, check=True, capture_output=True, text=True).stdout
        selected = subprocess.run([*command[:-1], '-DUSB_RESOURCE_OBSERVE=1', command[-1]],
                                  check=True, capture_output=True, text=True).stdout
        for name in ('u_gadget_create', 'u_resource_rpc', 'resource_rpc_free_enter', 'u_ko_insmod'):
            self.assertNotIn(name, default)
            self.assertIn(name, selected)
        for slot in ('30478', '302c0', '30800'):
            self.assertNotRegex(source, r'got\(base,0x' + slot)
        ee = (HERE / 'usb-ee-zero-observe.inc').read_text()
        self.assertIn('int32_t r=ee_real_free(owner,msg);int e=errno;', ee)
        self.assertNotIn('ee_real_free(owner,msg)', (HERE / 'usb-resources-observe.inc').read_text())

    def test_typed_c_wrappers_and_pre_free_capture(self):
        with tempfile.TemporaryDirectory(prefix='usb-tail-') as directory:
            root = Path(directory)
            binary = root / 'tail-check'
            subprocess.run(['cc', '-std=gnu11', '-O2', '-g', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-function', '-Wno-unused-variable', '-fno-omit-frame-pointer',
                '-fsanitize=address,undefined', '-I', str(HERE),
                str(HERE / 'test-usb-tail-observe.c'), '-ldl', '-o', str(binary)],
                check=True, capture_output=True, text=True)
            subprocess.run([str(binary), str(root / 'trace.log')], check=True, capture_output=True, text=True)

    def test_original_storage_request_is_still_denied_without_running_any_module(self):
        original = (HERE / 'guest/insmod').read_text()
        self.assertIn('65755c15be728daa2f6889d72a0aa0db9efadfb48361390222ba7a0e568529fa', original)
        self.assertIn('expected_bytes=104288', original)
        self.assertIn('builtin=unknown registration_proven=0', original)
        with tempfile.TemporaryDirectory(prefix='usb-storage-policy-') as directory:
            root = Path(directory)
            # Every absolute module-capable command is replaced before execution.
            helper = root / 'busybox'
            helper.write_text('#!/bin/sh\nif [ "$1" = insmod ]; then echo unsafe > "$TEST_MODULE_CALLED"; exit 99; fi\nif [ "$1" = grep ]; then shift; exec grep "$@"; fi\nexit 98\n')
            helper.chmod(0o700)
            for name, data in (('cmdline', 'fullsystem.usb-service=original-sen-observe-v1\n'),
                               ('modules', ''), ('policy', 'media-rm\n')):
                (root / name).write_text(data)
            text = original.replace('/bin/busybox', str(helper)).replace('/usr/bin/openssl', '/bin/false')
            for before, after in (('/proc/cmdline', root / 'cmdline'), ('/proc/modules', root / 'modules'),
                                  ('/tmp/fullsystem-insmod-policy', root / 'policy')):
                text = text.replace(before, str(after))
            script = root / 'insmod-test'
            script.write_text(text)
            for module in ('/usr/kmod/usbg_storage.ko', '/tmp/usbg_storage.ko'):
                result = subprocess.run(['sh', str(script), module, 'debug=0'],
                    env={**os.environ, 'TEST_MODULE_CALLED': str(root / 'called')},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
                self.assertFalse((root / 'called').exists())
                self.assertIn('FULLSYSTEM_MODULE_REQUEST', result.stdout)
                self.assertIn('FULLSYSTEM_USB_STORAGE_DENIED', result.stdout)
                self.assertIn('FULLSYSTEM_MODULE_UNSUPPORTED usbg_storage', result.stdout)

    def test_touch_provenance_does_not_suppress_old_prime_pointer_violations(self):
        prior = runpy.run_path(str(HERE / 'test-usb-ee-prime-lifecycle.py'))
        trace = prior['kernel_trace']()
        future = prior['event_rows'](trace, 'FREE_RETURN', prior['PRIME_POINTER'])[0]
        # Even a separate complete touch receipt cannot turn this orphan into an EE lease.
        summary = prior['PARSE'](prior['FIXTURE'].capture(trace + resource_fixture() + future),
                                 copy.deepcopy(prior['CONTRACT']), diagnostic_only=True)
        self.assertFalse(summary['native_content_verified'], summary)
        self.assertFalse(summary['resource_safe_to_close'], summary)
        self.assertFalse(summary['business_complete'], summary)
        self.assertIn('Prime native pointer reused', summary.get('error', ''))
        self.assertEqual(summary['trace_sha256'], hashlib.sha256(trace + resource_fixture() + future).hexdigest())


if __name__ == '__main__':
    unittest.main()
