import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'start-official-camera.py'))


class OfficialEntryTest(unittest.TestCase):
    def test_sd_configuration_uses_original_backend_and_safe_export_protocol(self):
        args=API['sd_run_arguments']('/tmp/owned-input',650,API['first_setup_plan']())
        self.assertEqual(args[args.index('--file-media')+1],'card')
        self.assertEqual(args[args.index('--insmod-policy')+1],'media-rm')
        self.assertIn('--card-export-flush',args)
        self.assertEqual(args[args.index('--card-export-at')+1],'600')
        plan=args[args.index('--key-plan')+1].split(';')
        publishers=[step for step in plan if '/simulation/cp-rm-notify' in step]
        self.assertEqual(publishers,['520.0:/simulation/cp-rm-notify 2 0 0 7 0 2 0'])
        self.assertEqual([float(step.partition(':')[0]) for step in plan],
                         sorted(float(step.partition(':')[0]) for step in plan))

    def test_unsupported_sd_modes_fail_before_creating_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'workspace'
            for args in (['--attach-sd','--headless'],['--attach-sd','--headless','--walk-first-setup'],
                         ['--attach-sd','--headless','--walk-first-setup','--seconds','650','--prepare-only']):
                done=subprocess.run(['python3','-B',str(HERE/'start-official-camera.py'),
                                     '--workspace',str(root),*args],capture_output=True,text=True)
                self.assertEqual(done.returncode,2,done.stderr)
                self.assertFalse(root.exists())

    def test_private_manifest_never_accepted_as_official(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'manifest.json').write_text(json.dumps({'source':'private-device-dump'}))
            with self.assertRaisesRegex(ValueError,'provenance'):API['verify_factory'](root)

    def test_reserved_adapter_override_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'overwrite';(folder/'sbin').mkdir(parents=True)
            (folder/'sbin/insmod').write_text('custom')
            with self.assertRaisesRegex(ValueError,'adapter path'):
                API['apply_overwrite'](root/'factory',folder,root/'output')
            self.assertFalse((root/'output').exists())

    def test_overlay_image_filename_reaches_partition_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);factory=root/'factory';factory.mkdir();folder=root/'overwrite';folder.mkdir()
            image=factory/'a7c2-rootfs.img'
            with image.open('wb') as stream:stream.truncate(4*1024**2)
            subprocess.run(['mke2fs','-q','-t','ext2','-F',str(image)],check=True)
            original=hashlib.sha256(image.read_bytes()).hexdigest()
            record={'name':image.name,'image_id':'nflasha7','bytes':image.stat().st_size,'sha256':original}
            (factory/'mounts.json').write_text(json.dumps({'schema':1,'images':[
                {'id':'nflasha7','file':image.name,'fs':'ext2','sha256':original}],
                'mounts':[{'guest':'/','image':'nflasha7','root':'/'}]}))
            (folder/'packed-probe.txt').write_bytes(b'original user bytes\n')
            fixture={'source':'official-bodydata-derived','images':[record]}
            with patch.dict(API['apply_overwrite'].__globals__,verify_factory=lambda path:fixture):
                output=API['apply_overwrite'](factory,folder,root/'modified')
            result=json.loads((output/'manifest.json').read_text())
            modified=result['images'][0]
            self.assertEqual(modified['name'],'a7c2-rootfs.img')
            self.assertEqual(modified['file'],'nflasha7.img')
            self.assertEqual(modified['sha256'],hashlib.sha256((output/modified['file']).read_bytes()).hexdigest())
            self.assertFalse(result['user_overwrite']['signed_update_package'])
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),original)

    def test_first_setup_walk_uses_only_real_keys_in_one_window(self):
        plan=API['first_setup_plan']()
        steps=plan.split(';')
        # every entry is "SECONDS:<single inject-key command>", never a shell script
        times=[]
        for step in steps:
            at,_,command=step.partition(':')
            times.append(float(at))
            self.assertTrue(command.startswith('/simulation/inject-key '),command)
            self.assertNotIn(';',command)
            self.assertNotIn('$',command)
            if ' 0 0x1 0x0 1' in command:
                self.assertTrue(command.endswith('--pulse-ms 50'),command)
            else:self.assertNotIn('--pulse-ms',command)
        self.assertEqual(len(steps),2*len(API['FIRST_SETUP_WALK']))
        # the shooting-menu round trip must fit inside one ~60s power-save window
        menu=[float(s.partition(':')[0]) for s in steps if float(s.partition(':')[0])>=450]
        self.assertLess(max(menu)-min(menu),60,'menu steps must stay inside one screen window')
        self.assertLessEqual(max(times),480)
        # DELETE is what selects the camera-setup branch; a focus move never worked
        codes={}
        for step in steps:
            at,_,command=step.partition(':')
            fields=command.split()
            self.assertEqual(fields[6],'0x0','raw ex_info must not be used as previous status')
            if fields[5]=='0x1':   # press edge only
                codes[float(at)]=fields[3]
        self.assertEqual(codes[160.0],'0x1f8')
        self.assertEqual(codes[452.0],'0x1ab')

    def test_automatic_factory_reuse_rejects_old_builder(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name,sha in (('candidate-002','old'),('candidate-003','current'),('candidate-004','old')):
                candidate=root/name;candidate.mkdir()
                (candidate/'manifest.json').write_text(json.dumps({'builder_source_sha256':sha}))
            self.assertEqual(API['find_factory_cache'](root,'current'),root/'candidate-003')
            self.assertIsNone(API['find_factory_cache'](root,'unknown'))

    def test_official_profile_contains_the_required_get_owners(self):
        configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
        args=configure('/tmp/input-fixture',500,official=True)
        for flag in ('--infrabb-service','--drawinfo-service','--grm-pin-service'):
            self.assertEqual(args[args.index(flag)+1],'registry')

    def test_walk_options_fail_before_creating_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'workspace'
            for args in (['--walk-first-setup'],['--walk-first-setup','--headless','--seconds','20']):
                result=subprocess.run(['python3','-B',str(HERE/'start-official-camera.py'),
                                       '--workspace',str(root),*args],capture_output=True,text=True)
                self.assertEqual(result.returncode,2,result.stderr)
                self.assertFalse(root.exists())


if __name__=='__main__':unittest.main()
