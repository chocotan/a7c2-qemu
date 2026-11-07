from pathlib import Path
import hashlib
import json
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'persistent-camera-profile.py'))


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


class PersistentCameraProfile(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.analysis=self.root/'runtime/analysis';self.analysis.mkdir(parents=True)
        self.models={}
        for name in API['REQUIRED_MODELS']:
            path=self.source/name;path.write_text('source fixture '+name+'\n');self.models[name]=sha(path)
        self.adapters={}
        for name in ('system-sound-region.py','pin-buffer-region.py','reserved-region.py'):
            shutil.copy2(HERE/name,self.source/name);self.adapters[name]=sha(self.source/name)
        simulation=self.analysis/'root/simulation';simulation.mkdir(parents=True)
        for name in ('menu-observe.so','ramfb-viewer','system-sound-owner','bluetooth-policy'):(simulation/name).write_bytes(('guest fixture '+name).encode())
        workspace=self.analysis/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt'
        workspace.parent.mkdir(parents=True);workspace.write_text('memrsv=0x01000000@0x400000000:uc\n')
        self.workspace=workspace
        self.manifest={'imaging_observer':{'device_sources':dict(self.models),'observer_sha256':sha(simulation/'menu-observe.so'),
                       'persistent_display_claim':{'path':'/dev/qemu-simulation/headless-osd.claim',
                           'snapshot_path':'/dev/qemu-simulation/headless-osd-frame.bin','viewer_sha256':sha(simulation/'ramfb-viewer')}},'adapter_sources':self.adapters}
        self.path=self.analysis/'full-system.json';self.store()
        self.scope=patch.dict(API['expand'].__globals__,HERE=self.source);self.scope.start();self.addCleanup(self.scope.stop)

    def store(self):self.path.write_text(json.dumps(self.manifest))

    def test_strict_never_requires_functional_assets(self):
        result=API['expand']('strict',self.root/'absent')
        self.assertEqual(result['cmdline'],[]);self.assertEqual(result['environment'],{})
        self.assertFalse(result['functional_providers_requested'])
        with self.assertRaisesRegex(ValueError,'Unknown persistent camera profile'):
            API['expand']('guessed-profile',self.root/'absent')

    def test_real_reservation_validators_and_existing_provider_contracts(self):
        result=API['expand'](API['PROFILE'],self.analysis)
        self.assertIn('memrsv=0x00020000@0x41d000000:uc',result['cmdline'])
        self.assertIn('memrsv=0x00002000@0x500000000:uc',result['cmdline'])
        self.assertEqual(result['environment']['QEMU_TCG_THREAD'],'multi')
        self.assertEqual(result['insmod_policy'],'media-rm')
        self.assertFalse(result['actual_persistent_ap_consumed']);self.assertFalse(result['capture_verified'])
        self.assertTrue(all(row['sha256']==sha(Path(row['path'])) for row in result['source_bindings']))
        self.assertFalse(any(token.startswith(('root=','init=','rdinit=','persistent.profile=')) for token in result['cmdline']))

    def test_persistent_claim_cannot_reuse_a_disk_path(self):
        self.manifest['imaging_observer']['persistent_display_claim']['path']='/tmp/headless-osd.claim';self.store()
        with self.assertRaisesRegex(ValueError,'per-boot RAM claim'):API['expand'](API['PROFILE'],self.analysis)

    def test_viewer_path_cannot_be_mixed_with_another_family(self):
        (self.analysis/'root/simulation/ramfb-viewer').write_bytes(b'other-viewer')
        with self.assertRaisesRegex(ValueError,'viewer differs'):API['expand'](API['PROFILE'],self.analysis)

    def test_source_drift_is_rejected_before_launch(self):
        (self.source/'imaging-device.c').write_text('changed')
        with self.assertRaisesRegex(ValueError,'source changed'):API['expand'](API['PROFILE'],self.analysis)

    def test_missing_provider_and_unknown_paths_are_rejected(self):
        del self.manifest['imaging_observer']['device_sources']['vdf-device.c'];self.store()
        with self.assertRaisesRegex(ValueError,'lacks the required'):API['expand'](API['PROFILE'],self.analysis)
        self.manifest['imaging_observer']['device_sources']['vdf-device.c']=self.models['vdf-device.c']
        self.manifest['imaging_observer']['device_sources']['../foreign.c']='a'*64;self.store()
        with self.assertRaisesRegex(ValueError,'Invalid functional provider'):API['expand'](API['PROFILE'],self.analysis)

    def test_program_and_reservation_source_drift_are_rejected(self):
        program=self.analysis/'root/simulation/menu-observe.so';before=program.read_bytes();program.write_bytes(b'other')
        with self.assertRaisesRegex(ValueError,'program differs'):API['expand'](API['PROFILE'],self.analysis)
        program.write_bytes(before);(self.source/'system-sound-region.py').write_text('changed')
        with self.assertRaisesRegex(ValueError,'reservation adapter differs'):API['expand'](API['PROFILE'],self.analysis)

    def test_existing_ram_overlap_is_not_silently_replaced(self):
        self.workspace.write_text('memrsv=0x00020000@0x41d000000:uc\n')
        with self.assertRaisesRegex(ValueError,'overlaps virtual sound'):API['expand'](API['PROFILE'],self.analysis)

    def test_guest_helper_symlink_is_refused(self):
        path=self.analysis/'root/simulation/system-sound-owner';target=self.root/'foreign';path.rename(target);path.symlink_to(target)
        with self.assertRaisesRegex(ValueError,'ordinary functional-profile'):API['expand'](API['PROFILE'],self.analysis)


if __name__=='__main__':unittest.main()
