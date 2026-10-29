import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('natural_gtk_directory', BASE / 'check-natural-gtk-input.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NaturalGtkDirectory(unittest.TestCase):
    def test_option_is_explicit_and_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(module.directory_sd_argument(['x', '--host-sd-dir', directory]),
                             str(Path(directory).resolve()))
            file_path = Path(directory) / 'file'
            file_path.write_bytes(b'x')
            for argv in (['x', '--host-sd-dir'],
                         ['x', '--host-sd-dir', '--natural-shutter'],
                         ['x', '--host-sd-dir', str(file_path)],
                         ['x', '--host-sd-dir', 'relative'],
                         ['x', '--host-sd-dir=/tmp'],
                         ['x', '--host-sd-dir', directory, '--host-sd-dir', directory]):
                with self.subTest(argv=argv):
                    with self.assertRaises(ValueError):
                        module.directory_sd_argument(argv)
            self.assertIsNone(module.directory_sd_argument(['x', '--natural-shutter']))

    def test_candidate_build_identity_and_rejection(self):
        self.assertIsNone(module.candidate_build_argument(['x']))
        with tempfile.TemporaryDirectory() as directory:
            stage=Path(directory)
            binary=stage/'build/qemu-system-aarch64'
            binary.parent.mkdir()
            binary.write_bytes(b'synthetic candidate identity fixture')
            digest=hashlib.sha256(binary.read_bytes()).hexdigest()
            receipt=stage/'pci-hardware-build.json'
            valid={'scope':'default-off PCI/ATU hardware in native GTK/USB/directory-SD build',
                   'binary_sha256':digest}
            receipt.write_text(json.dumps(valid))
            args=['x','--candidate-build',directory]
            self.assertEqual(module.candidate_build_argument(args),
                             {'build':str(stage),'binary':str(binary),'sha256':digest})
            for argv in (['x','--candidate-build'],['x','--candidate-build','relative'],
                         ['x','--candidate-build',directory,'--candidate-build',directory],
                         ['x','--candidate-build='+directory]):
                with self.subTest(argv=argv),self.assertRaises(ValueError):
                    module.candidate_build_argument(argv)
            for bad in ([],{**valid,'scope':'diagnostic-only'},
                        {**valid,'binary_sha256':'0'*64}):
                receipt.write_text(json.dumps(bad))
                with self.subTest(receipt=bad),self.assertRaises(ValueError):
                    module.candidate_build_argument(args)
            receipt.write_text(json.dumps(valid))
            binary.write_bytes(b'changed after build')
            with self.assertRaisesRegex(ValueError,'does not match'):
                module.candidate_build_argument(args)
        compile(module.DRIVER,'<candidate-gtk-driver>','exec')

    def test_adf_requires_explicit_safe_firstboot_before_any_process(self):
        safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--export-sd']
        with tempfile.TemporaryDirectory() as directory:
            safe+=['--host-sd-dir',directory]
            env={'A7C2_ADF_PROC_PATH':'virtual-source7-idle-v1',
                 'A7C2_VEF_PATH':'virtual-nomem-v1'}
            for argv,values in ((safe,{**env,'A7C2_ADF_PROC_PATH':'bad'}),
                                (safe,{**env,'A7C2_VEF_PATH':''}),
                                ([v for v in safe if v!='--new-ui'],env),
                                ([v for v in safe if v!='--firstboot'],env),
                                ([v for v in safe if v!='--export-sd'],env),
                                (safe[:-2],env),
                                (safe,{**env,'MENU_BB_READY_INJECT':'1'}),
                                (safe,{**env,'MENU_YC_INJECT':'1'})):
                with self.subTest(argv=argv,env=values),mock.patch.object(module.sys,'argv',argv), \
                     mock.patch.dict(module.os.environ,values,clear=True), \
                     mock.patch.object(module.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
                    with self.assertRaises(ValueError):module.main()

    def test_adf_intent_and_admission_require_selected_matching_model(self):
        tree=ast.parse((BASE/'check-natural-gtk-input.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        intent=next(n for n in main.body if isinstance(n,ast.If) and
                    isinstance(n.test,ast.Name) and n.test.id=='requested_adf')
        admission=next(n for n in ast.walk(main) if isinstance(n,ast.If) and
                       isinstance(n.test,ast.Name) and n.test.id=='requested_adf' and
                       isinstance(n.body[0],ast.Assign) and
                       isinstance(n.body[0].targets[0],ast.Name) and n.body[0].targets[0].id=='expected_adf')
        profile='virtual-source7-idle-v1'
        fields=module.adf_proc_profile_fields(profile)
        code=compile(ast.Module(body=[intent,admission],type_ignores=[]),'<gtk-adf-admission>','exec')
        actual={**fields,'backup_transport':dict(fields),'selected_observer_matches_build':True}
        scope={'requested_adf':'','proof':{},'adf_proc_profile_fields':module.adf_proc_profile_fields,'actual':actual}
        exec(code,scope)
        self.assertEqual(scope['proof'],{})
        scope['requested_adf']=profile
        exec(code,scope)
        self.assertEqual(scope['proof']['adf_proc_path_intent'],fields)
        self.assertEqual(scope['proof']['adf_proc_path_admission'],fields)
        for section in ('top','transport'):
            for name,value in (('adf_proc_path_profile',None),('adf_proc_clock_period_ns',2),
                               ('adf_proc_clock_period_ns',1000000.0),
                               ('adf_proc_capture_verified',True),('adf_proc_pcm_verified',0)):
                changed=copy.deepcopy(actual)
                target=changed if section=='top' else changed['backup_transport']
                target[name]=value
                scope.update(actual=changed,proof={})
                with self.subTest(section=section,name=name),self.assertRaises(RuntimeError):exec(code,scope)
        scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
        with self.assertRaises(RuntimeError):exec(code,scope)

    def test_adf_set_input_rejects_unknown_or_missing_chain_before_any_process(self):
        import backup_profile
        from test_backup_profile import adf_host_environment
        with tempfile.TemporaryDirectory() as directory:
            safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--export-sd',
                  '--host-sd-dir',directory]
            env={**adf_host_environment(directory),'A7C2_ADF_SET_INPUT':backup_profile.INPUT_PROFILE}
            for name in ('A7C2_ADF_PROC_PATH','A7C2_VEF_PATH','A7C2_DFS_SELECTOR',
                         'A7C2_TCIN_DETECT','A7C2_BACKUP_SYNC','A7C2_BACKUP_BUILD',
                         'A7C2_CP_BACKGROUND','A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL'):
                with self.subTest(missing=name),mock.patch.object(module.sys,'argv',safe), \
                     mock.patch.dict(module.os.environ,{k:v for k,v in env.items() if k!=name},clear=True), \
                     mock.patch.object(module.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
                    with self.assertRaises(ValueError):module.main()
            for argv,values in ((safe,{**env,'A7C2_ADF_SET_INPUT':'bad'}),
                                (safe,{**env,'MENU_YC_INJECT':'1'}),
                                (safe,{**env,'SEED_BACKUP':'private'}),
                                ([v for v in safe if v!='--new-ui'],env),
                                ([v for v in safe if v!='--firstboot'],env),
                                ([v for v in safe if v!='--export-sd'],env),
                                (safe[:-2],env)):
                with self.subTest(argv=argv,env=values),mock.patch.object(module.sys,'argv',argv), \
                     mock.patch.dict(module.os.environ,values,clear=True), \
                     mock.patch.object(module.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
                    with self.assertRaises(ValueError):module.main()

    def test_adf_set_input_intent_and_admission_preserve_failure_and_claim_boundaries(self):
        import backup_profile
        tree=ast.parse((BASE/'check-natural-gtk-input.py').read_text())
        main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
        intent=next(n for n in main.body if isinstance(n,ast.If) and
                    isinstance(n.test,ast.Name) and n.test.id=='requested_adf_input' and
                    isinstance(n.body[0],ast.Assign))
        admission=next(n for n in ast.walk(main) if isinstance(n,ast.If) and
                       isinstance(n.test,ast.Name) and n.test.id=='requested_adf_input' and
                       isinstance(n.body[0],ast.Assign) and
                       isinstance(n.body[0].targets[0],ast.Name) and n.body[0].targets[0].id=='expected_adf_input')
        profile=backup_profile.INPUT_PROFILE
        fields=module.adf_set_input_profile_fields(profile)
        code=compile(ast.Module(body=[intent,admission],type_ignores=[]),'<gtk-adf-input-admission>','exec')
        actual={**fields,'backup_transport':dict(fields),'selected_observer_matches_build':True}
        scope={'requested_adf_input':'','proof':{},
               'adf_set_input_profile_fields':module.adf_set_input_profile_fields,'actual':actual}
        exec(code,scope)
        self.assertEqual(scope['proof'],{})
        scope['requested_adf_input']=profile
        exec(code,scope)
        self.assertEqual(scope['proof']['adf_set_input_intent'],fields)
        self.assertEqual(scope['proof']['adf_set_input_admission'],fields)
        self.assertFalse(fields['adf_set_input_ap_consumed'])
        self.assertFalse(fields['adf_set_input_capture_verified'])
        for section in ('top','transport'):
            for name,value in fields.items():
                changed=copy.deepcopy(actual)
                target=changed if section=='top' else changed['backup_transport']
                target.pop(name)
                scope.update(actual=changed,proof={})
                with self.subTest(section=section,missing=name),self.assertRaises(RuntimeError):exec(code,scope)
                target[name]=int(value) if type(value) is bool else (float(value) if type(value) is int else 'wrong')
                scope.update(proof={})
                with self.subTest(section=section,changed=name),self.assertRaises(RuntimeError):exec(code,scope)
        scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
        with self.assertRaises(RuntimeError):exec(code,scope)

    def test_backend_admission_is_required(self):
        source = (BASE / 'check-natural-gtk-input.py').read_text()
        self.assertIn("env['A7C2_DIRECTORY_SD']=directory_sd", source)
        self.assertIn("actual.get('directory_sd_profile')!='directory-vvfat-256gb-v1'", source)
        self.assertIn("actual.get('rm_file_image_bytes')!=256000000000", source)
        self.assertIn('DIRECTORY_SD_PROFILE_BOUND', source)


if __name__ == '__main__':
    unittest.main()
