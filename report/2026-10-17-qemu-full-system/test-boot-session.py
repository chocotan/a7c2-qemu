import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
m = runpy.run_path(str(HERE / 'boot-session.py'))


class BootSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root/'runtime'
        self.analysis = self.runtime/'analysis'
        self.analysis.mkdir(parents=True)
        (self.analysis/'full-system.json').write_text('{}')
        self.args = argparse.Namespace(output=self.root/'session', dump=None, runtime=self.runtime,
            profile='original-init-cold', predicates=None)

    def test_missing_backend_is_recorded_and_never_becomes_cold(self):
        self.args.profile = 'wbi-resume'
        with patch.dict(m['prepare'].__globals__,
                verified_runtime=lambda p: (self.analysis, {'source':'private-device-dump','images':[]}),
                inspect_inputs=lambda a,b: {'wbi': {'has_wbi2_header':True}}):
            output, result = m['prepare'](self.args)
        self.assertEqual(result['state'], 'blocked')
        self.assertIsNone(result['backend'])
        self.assertEqual(result['route_model']['status'], 'unknown')
        self.assertFalse(result['coverage']['full_boot_verified'])
        self.assertFalse(result['coverage']['stage_verified']['wbi'])
        self.assertEqual(json.loads((output/'session.json').read_text())['source_class'], 'private-device-dump')

    def test_cold_build_is_preparation_not_execution_or_loader_selection(self):
        calls=[]
        def load(path, **kwargs):
            self.assertEqual(Path(path).name, 'cold-init-chain.py')
            return {'build':lambda source,target: calls.append((source,target)) or {'build_verified':True}}
        with patch.dict(m['prepare'].__globals__,
                verified_runtime=lambda p: (self.analysis, {'source':'private-device-dump','images':[]}),
                inspect_inputs=lambda a,b: {'wbi': {'has_wbi2_header':False}}), \
                patch.object(m['runpy'], 'run_path', side_effect=load):
            _, result=m['prepare'](self.args)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['state'],'prepared')
        self.assertFalse(result['route_model_is_original_loader_execution'])
        self.assertEqual(result['receipt']['stages'],[])
        self.assertFalse(result['coverage']['cold_guest_chain_verified'])

    def test_persistent_preparation_binds_disk_not_helper_partition_images(self):
        instance=self.root/'instance';instance.mkdir();self.args.instance=instance
        built={'source':'private-device-dump','instance':str(instance),
               'instance_geometry':{'user_bytes':1954545664},
               'native_elf_identity':{'/lib/appFw.so':{'sha256':'a'*64}}}
        calls=[]
        def load(path,**kwargs):
            self.assertEqual(Path(path).name,'persistent-boot.py')
            def build(selected,analysis,output,**options):
                calls.append((selected,analysis,output,options));return built
            return {'build':build}
        with patch.object(m['runpy'],'run_path',side_effect=load),patch.dict(m['prepare'].__globals__,
                verified_runtime=lambda _:self.fail('helper images must not replace the current disk'),
                inspect_inputs=lambda *_:self.fail('stale helper p5/AP must not be inspected')):
            _,result=m['prepare'](self.args)
        self.assertEqual(calls[0][:2],(instance,self.analysis))
        self.assertEqual(result['backend'],'original-init-with-persistent-device')
        self.assertEqual(result['receipt']['bindings']['persistent_instance'],str(instance))
        self.assertEqual(result['cold_chain'],built)
        self.assertFalse(result['coverage']['full_boot_verified'])
        self.assertEqual(json.loads((self.args.output/'input-inspection.json').read_text())['wbi_ap_compatibility']['status'],'unknown')

    def test_persistent_instance_never_falls_back_to_another_route(self):
        self.args.instance=self.root/'instance';self.args.instance.mkdir()
        self.args.profile='wbi-resume'
        with self.assertRaisesRegex(ValueError,'Persistent instance requires'):
            m['prepare'](self.args)
        self.assertEqual(json.loads((self.args.output/'session.json').read_text())['state'],'failed')

    def test_executor_runs_inside_the_persistent_lease(self):
        output=self.root/'execution';output.mkdir()
        instance=self.root/'instance';instance.mkdir();events=[];active=[False]
        state={'state':'prepared','runtime':str(self.runtime),'backend':'original-init-with-persistent-device','cold_chain':{'build_verified':True}}
        @contextmanager
        def lease(launch):
            active[0]=True;events.append('lease-enter')
            try:yield {'bound-disk-fd':9}
            finally:active[0]=False;events.append('lease-exit')
        def run(bound,cold,target,seconds):
            self.assertTrue(active[0]);self.assertEqual(bound,{'bound-disk-fd':9})
            events.append('execute');return {'cold_guest_chain_verified':True,'full_boot_verified':False}
        def load(path,**kwargs):
            name=Path(path).name
            if name=='persistent-boot.py':
                return {'prepare_launch':lambda *a,**kw:{'command':['owned-test'],'env':{}},'leased_launch':lease}
            if name=='boot-execution.py':return {'run':run}
            self.fail('Unexpected controller '+name)
        with patch.dict(m['main'].__globals__,prepare=lambda _: (output,state)),patch.object(m['runpy'],'run_path',side_effect=load):
            rc=m['main'](['--profile','original-init-cold','--runtime',str(self.runtime),
                          '--instance',str(instance),'--output',str(output),'--seconds','2'])
        self.assertEqual(rc,0);self.assertEqual(events,['lease-enter','execute','lease-exit'])
        self.assertEqual(json.loads((output/'session.json').read_text())['state'],'finished')

    def test_firmware_request_entry_forwards_sequence_to_fixed_controller(self):
        request = self.root / 'sequence-request.json'
        request.write_text('{"action":"sequence","boot_profile":"qemu-retained-roundtrip"}')
        for status, expected_rc in (('completed', 0), ('blocked', 2), ('failed', 2)):
            calls = []
            def load(path):
                self.assertEqual(Path(path), HERE / 'firmware-boot-request.py')
                return {'execute': lambda value: calls.append(value) or {'action': 'sequence', 'status': status}}
            with patch.object(m['runpy'], 'run_path', side_effect=load), patch.dict(m['main'].__globals__,
                    prepare=lambda _: self.fail('request entry must not create a cold fallback')):
                self.assertEqual(m['main'](['--firmware-development-request', str(request)]), expected_rc)
            self.assertEqual(calls, [request])
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            m['main'](['--firmware-development-request', str(request), '--profile', 'ram-hotboot'])

    def test_preparation_failure_is_retained_without_success(self):
        def fail(path): raise ValueError('bad partition identity')
        with patch.dict(m['prepare'].__globals__, verified_runtime=fail), self.assertRaises(ValueError):
            m['prepare'](self.args)
        record=json.loads((self.args.output/'session.json').read_text())
        self.assertEqual(record['state'],'failed')
        self.assertIn('bad partition identity',record['error'])
        self.assertFalse(record['full_boot_verified'])

    def test_existing_output_and_symlink_inputs_are_rejected(self):
        self.args.output.mkdir()
        (self.args.output/'keep').write_text('evidence')
        with self.assertRaises(ValueError):m['prepare'](self.args)
        self.assertEqual((self.args.output/'keep').read_text(),'evidence')
        alias=self.root/'alias';alias.symlink_to(self.runtime,target_is_directory=True)
        with self.assertRaises(ValueError):m['ordinary'](alias,directory=True)
        with self.assertRaises(ValueError):m['ordinary']('/dev/null')


if __name__=='__main__':unittest.main()
