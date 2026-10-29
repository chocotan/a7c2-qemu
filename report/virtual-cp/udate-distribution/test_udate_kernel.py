import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


class UdateKernelClient(unittest.TestCase):
    def test_build_identity(self):
        result = subprocess.run(['bash', 'build.sh'], cwd=HERE, capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads((HERE / 'verification.json').read_text())
        self.assertTrue(receipt['resident'])
        self.assertTrue(receipt['backup_default_off'])
        self.assertEqual(receipt['imports'], sorted([
            'osal_dynamic_id', 'osal_free_msg', 'osal_get_msg_src', 'osal_rcv_msg_tmo',
            'osal_reg_public', 'osal_set_msg_src', 'osal_snd_msg',
            'osal_snd_sync_direct', 'osal_valloc_msg_wait', 'printk', 'param_ops_bool',
            'pci_get_domain_bus_and_slot','pci_enable_device','pci_disable_device',
            'pci_set_master','pci_dev_put','pci_bus_read_config_dword','pci_iomap_range',
            'pci_iounmap','__memcpy_fromio','pcidma_connect']))

    def run_backup_cases(self, source, cases):
        seed=HERE.parents[2]/'runtime/analysis/menu-root/seed-backup.bin'
        with seed.open('rb') as stream:
            self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),
                             '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47')
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'backup-kernel-test'
            built=subprocess.run([
                'cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-g',
                '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',
                str(HERE/source),'-o',str(binary),
            ],capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            environment=dict(os.environ,ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                             UBSAN_OPTIONS='halt_on_error=1')
            for case in cases:
                with self.subTest(case=case):
                    result=subprocess.run([str(binary),case,str(seed)],cwd=directory,
                                          env=environment,capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_backup_protocol_real_request_bounds_and_ownership(self):
        self.run_backup_cases('test_backup_endpoint.c',[
            'normal','disabled','no-backend','order','duplicate','corrupt',
            'short-object','allocate','freeze','read','send','request-free',
            'reply-free','unlock','busy','release-race',*map(str,range(10))])

    def test_backup_pci_binding_and_init_failures(self):
        self.run_backup_cases('test_backup_pci.c',[
            'default-off','normal','freeze-failure','epoch-mismatch',*map(str,range(1,13))])

    def test_protocol_and_failure_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'udate-kernel-test'
            built = subprocess.run([
                'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                str(HERE / 'test_client.c'), '-o', str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                               UBSAN_OPTIONS='halt_on_error=1')
            cases = ['normal', 'unsupported', *map(str, range(1, 11)),
                     'original-retry', 'busy', 'register']
            for case in cases:
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
