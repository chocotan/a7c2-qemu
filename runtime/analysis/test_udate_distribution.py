import ast
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_adf_set_output_profile import guest_environment, guest_setup

HERE = Path(__file__).resolve().parent / 'device-models'


class UdateDistribution(unittest.TestCase):
    def test_roundtrip_and_failure_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'udate'
            built = subprocess.run([
                'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
                '-DNATIVE_UDATE_DISTRIBUTION_TEST',
                str(HERE / 'udate-distribution.c'), str(HERE / 'test-udate-distribution.c'),
                '-o', str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                               UBSAN_OPTIONS='halt_on_error=1')
            cases = ['normal', 'unsupported', *map(str, range(1, 16)),
                     'original-retry', 'busy', 'fork', 'fork-release']
            for case in cases:
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_kernel_endpoint_is_exclusive_and_explicit(self):
        source = (HERE.parent / 'menu-observe.c').read_text()
        self.assertNotIn('native_udate_distribution_dispatch', source)
        self.assertNotIn('NATIVE_UDATE_', source)
        build = (HERE.parent / 'build-observers.sh').read_text()
        self.assertIn('report/virtual-cp/udate-distribution/build.sh', build)
        self.assertIn('sony_udate_distribution.ko', build)
        self.assertIn('put32((unsigned char *)query+0x0c,reply_queue);',
                      (HERE / 'udate-distribution.c').read_text())
        probe = (HERE.parent / 'qemu-menu-probe.py').read_text()
        gtk = (HERE.parent / 'check-natural-gtk-input.py').read_text()
        self.assertIn('insmod /simulation/sony_udate_distribution.ko', probe)
        self.assertIn('kernel-public-roundtrip-v1', probe)
        self.assertIn('udate_distribution_kernel', probe)
        tree=ast.parse(probe)
        output_guard=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
                          isinstance(node.test,ast.Name) and node.test.id=='adf_set_output_profile')
        markers=[node for node in ast.walk(tree) if isinstance(node,ast.Constant) and
                 isinstance(node.value,str) and node.value.startswith('export MENU_UDATE_DISTRIBUTION=')]
        self.assertEqual([node.value for node in markers],
                         ['export MENU_UDATE_DISTRIBUTION=virtual-roundtrip-v1'])
        self.assertTrue(all(node in list(ast.walk(output_guard)) for node in markers))
        setup=guest_setup({'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1',
                           'MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1'})
        self.assertNotIn('MENU_UDATE_DISTRIBUTION',guest_environment(setup))
        self.assertEqual(sum('insmod /simulation/sony_udate_distribution.ko' in line for line in setup),1)
        sender=(HERE.parents[2]/'report/virtual-cp/udate-distribution/client.c').read_text()
        self.assertEqual(sender.count('rc = osal_reg_public((long)&sender_handle);'),1)
        self.assertIn('sender_handle = udate_sender;',sender)
        self.assertIn('if udate_distribution and not manifest[\'selected_observer_matches_build\']:', probe)
        self.assertIn('kernel-public-roundtrip-v1', gtk)
        self.assertIn('UDATE_K_REGISTER: rc=0', gtk)
        self.assertIn("actual['udate_distribution_kernel'].get('receipt',{}).get('sha256')", gtk)
        self.assertIn('UDATE kernel module differs from its ABI receipt', probe)
        self.assertIn("actual.get('selected_observer_matches_build') is not True", gtk)


if __name__ == '__main__':
    unittest.main()
