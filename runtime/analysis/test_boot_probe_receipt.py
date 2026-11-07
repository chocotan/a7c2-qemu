import json
from pathlib import Path
import tempfile
import unittest

from boot_probe_receipt import begin, finish, validate_profile


class BootProbeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / 'run-one'
        self.run.mkdir()
        self.image = self.root / 'selected.cpio'
        self.image.write_bytes(b'actual selected guest image')

    def test_other_profile_never_falls_back_to_diagnostic(self):
        for profile in ('original-init-cold', 'ram-hotboot', 'wbi-resume', 'sd-update', 'unknown'):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                validate_profile(profile)
        with self.assertRaises(ValueError):
            validate_profile('direct-bootin', True)

    def test_prelaunch_is_unknown_and_never_full_boot(self):
        receipt = begin(self.run, self.image, ['kernel-wrapper', str(self.image)])
        self.assertEqual(receipt['stages'], [])
        data = json.loads((self.run / 'boot-flow.json').read_text())
        self.assertFalse(data['coverage']['full_boot_verified'])
        self.assertFalse(data['coverage']['cold_guest_chain_verified'])
        self.assertFalse(data['receipt']['execution_limits']['wbi_resume_executed'])

    def test_flags_and_fake_summary_do_not_count_as_guest_execution(self):
        receipt = begin(self.run, self.image, ['kernel-wrapper', '--bootin'])
        (self.run / 'console.log').write_text('QEMU_BOOT_TYPE=1\nbootin requested\n')
        coverage = finish(self.run, receipt, {'appfw_init_entered': True, 'appfw_init_returned': True})
        self.assertFalse(coverage['ap_verified'])
        self.assertFalse(coverage['full_boot_verified'])

    def test_ap_consumption_stays_partial_when_chroot_cp_and_wbi_absent(self):
        receipt = begin(self.run, self.image, ['kernel-wrapper'])
        (self.run / 'console.log').write_text(
            '[    0.000000] Linux version 4.9.337-scel+\n'
            '[    0.000000] Kernel command line: root=/dev/ram0 rdinit=/init initcall_blacklist=__boottime___udif_init_udif_wdt\n'
            'enter_asi=1 return_asi=1\n')
        coverage = finish(self.run, receipt, {'appfw_init_entered': True, 'appfw_init_returned': True})
        self.assertTrue(coverage['ap_verified'])
        self.assertTrue(coverage['stage_verified']['kernel'])
        self.assertTrue(coverage['stage_verified']['kernelargs'])
        self.assertFalse(coverage['stage_verified']['chroot'])
        self.assertFalse(coverage['stage_verified']['cp'])
        self.assertFalse(coverage['stage_verified']['wbi'])
        self.assertFalse(coverage['full_boot_verified'])
        self.assertTrue(any('watchdog initialization is bypassed' in value for value in coverage['blockers']))

    def test_failure_before_guest_console_keeps_input_binding(self):
        receipt = begin(self.run, self.image, ['kernel-wrapper'])
        digest = receipt['binding_digest']
        coverage = finish(self.run, receipt)
        self.assertFalse(coverage['stage_verified']['kernel'])
        saved = json.loads((self.run / 'boot-flow.json').read_text())
        self.assertEqual(saved['receipt']['binding_digest'], digest)


if __name__ == '__main__':
    unittest.main()
