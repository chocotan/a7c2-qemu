#!/usr/bin/env python3
"""Host counterfactuals; synthesized RAM is never native residency evidence."""
import hashlib
import json
from pathlib import Path
import re
import runpy
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PROFILE = runpy.run_path(str(HERE / 'avcam-preload.py'))
VERIFY = runpy.run_path(str(HERE / 'verify-avcam-preload.py'))['verify']
LOADER = runpy.run_path(str(HERE / 'verify-liro-loader.py'))['verify']
MEMORY = runpy.run_path(str(HERE / 'verify-liro-memory.py'))['verify']
ARGUMENTS = ' adr=0x401000000  '


class CounterfactualParameters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = HERE / 'runtime/analysis/runs/run-du3q5xp5'
        image = HERE / 'runtime/analysis/liro-preload/av-cam.bin'
        if not cls.baseline.is_dir() or not image.is_file():
            raise unittest.SkipTest('Private inputs for host counterfactual not present')
        PROFILE['validate_image'](image)
        cls.image = image.read_bytes() + bytes(PROFILE['CAPACITY'] - PROFILE['IMAGE_BYTES'])

    def fixture(self, run, arguments=ARGUMENTS, flags=1):
        console = (self.baseline / 'console.log').read_bytes()

        def replace(match):
            row = match[0]
            for name, value in ((b'original_rc', str(len(arguments)).encode()),
                                (b'captured_bytes', str(len(arguments)).encode()),
                                (b'args_hex', arguments.encode('ascii').hex().encode()),
                                (b'flags', hex(flags).encode()), (b'argv_flags', hex(flags).encode())):
                row = re.sub(rb'(?<!\w)' + name + rb'=\S+', name + b'=' + value, row)
            return row

        console = b'FULLSYSTEM_AVCAM_DATA_PRELOAD_VALIDATED HOST_FIXTURE_ONLY\n' + re.sub(rb'FULL_LIRO_ARGS [^\r\n]+', replace, console)
        sha = hashlib.sha256(console).hexdigest()
        inputs = json.loads((self.baseline / 'inputs.json').read_text())
        inputs['experiment']['preload_avcam'] = True
        inputs['host_fixture_only'] = True
        inputs['avcam_preload'] = {'physical': PROFILE['PHYSICAL'], 'capacity': PROFILE['CAPACITY'],
            'bytes': PROFILE['IMAGE_BYTES'], 'sha256': PROFILE['IMAGE_SHA256'], 'sets_cpu_entry': False,
            'initializes_LIRO': False, 'supplies_image_data': True, 'original_module_arguments_changed': False}
        result = json.loads((self.baseline / 'result.json').read_text())
        result['terminal_console_sha256'] = sha;result['host_fixture_only'] = True
        memory = json.loads((self.baseline / 'liro-memory.json').read_text())
        memory.update(export_sha256=hashlib.sha256(self.image).hexdigest(), window_all_zero=False,
                      image_prefix_sha256=PROFILE['IMAGE_SHA256'], image_matches_original=True, header_magic_hex='4f52494c')
        (run / 'console.log').write_bytes(console)
        (run / 'liro-reserved-memory.bin').write_bytes(self.image)
        for name, value in (('inputs.json', inputs), ('result.json', result), ('liro-memory.json', memory)):
            (run / name).write_text(json.dumps(value))
        loader = LOADER(run)
        self.assertTrue(loader['liro_loader_observation_verified'])
        self.assertEqual(loader['actual_module_arguments'], arguments)
        (run / 'liro-loader-observation-proof-v2.json').write_text(json.dumps(loader))
        observed = MEMORY(run)
        self.assertTrue(observed['liro_reserved_window_verified'])
        (run / 'liro-reserved-window-proof.json').write_text(json.dumps(observed))

    def test_observed_parameters_pass_host_fixture_only(self):
        with tempfile.TemporaryDirectory(prefix='avcam-host-fixture-') as temporary:
            run = Path(temporary);self.fixture(run)
            proof = VERIFY(run)
            self.assertEqual(proof['schema'], 2)
            self.assertEqual(proof['actual_module_arguments'], ARGUMENTS)
            self.assertFalse(proof['LIRO_initialized_verified'])

    def test_foreign_load_parameters_refused_despite_both_upstream_proofs(self):
        with tempfile.TemporaryDirectory(prefix='avcam-host-fixture-') as temporary:
            run = Path(temporary);self.fixture(run, ' load=1 fn=/tmp/foreign.bin adr=0x401000000  ')
            with self.assertRaisesRegex(ValueError, 'Actual original module parameters or flags'):
                VERIFY(run)

    def test_flags_drift_refused_even_without_load_bit(self):
        with tempfile.TemporaryDirectory(prefix='avcam-host-fixture-') as temporary:
            run = Path(temporary);self.fixture(run, flags=0x2001)
            with self.assertRaisesRegex(ValueError, 'Actual original module parameters or flags'):
                VERIFY(run)


if __name__ == '__main__':
    unittest.main()
