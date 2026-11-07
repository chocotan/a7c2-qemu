#!/usr/bin/env python3
"""Host checks: disposable real ext2 filesystems and independent SHA256 vectors."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('cold_chain', HERE/'cold-init-chain.py')
API = importlib.util.module_from_spec(spec)
spec.loader.exec_module(API)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image(tree, target, size=8*1024**2):
    with target.open('xb') as stream:
        stream.truncate(size)
    subprocess.run(['mke2fs','-q','-t','ext2','-F','-d',str(tree),str(target)],check=True,capture_output=True)


@unittest.skipUnless(shutil.which('clang'),'clang required')
class AuditCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='cold-audit-host-')
        cls.root = Path(cls.temp.name)
        cls.program = cls.root/'audit'
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-O2','-DCOLD_AUDIT_HOST',
                        str(HERE/'guest/cold-start-audit.c'),'-o',str(cls.program)],check=True,capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_release_receipt_has_real_newline(self):
        source=self.root/'release-receipt.c'
        source.write_text('#define COLD_AUDIT_HOST\n#define main audit_main\n'
            '#define fork fake_fork\n#define waitpid fake_waitpid\n#define open fake_open\n'
            '#define read fake_read\n#define close fake_close\n'
            '#include "'+str(HERE/'guest/cold-start-audit.c')+'"\n'
            '#undef main\n#include <assert.h>\n'
            'int fake_fork(void){return 12;}\n'
            'int fake_waitpid(int pid,int *status,int flags){assert(pid==12 && flags==0);*status=0;return pid;}\n'
            'int fake_open(const char *path,int flags,...){assert(!strcmp(path,"/dev/ram0") && flags==0x20000);return 55;}\n'
            'long fake_read(int fd,void *data,size_t size){assert(fd==55 && size==512);for(size_t i=0;i<size;i++)((u8*)data)[i]=0;return 512;}\n'
            'int fake_close(int fd){assert(fd==55);return 0;}\n'
            'int main(void){char *args[]={"audit","release","/dev/ram0",0};return run(3,args);}\n')
        program=self.root/'release-receipt'
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(program)],check=True,capture_output=True)
        result=subprocess.run([str(program)],capture_output=True,check=True)
        self.assertEqual(result.stdout,b'COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512\n')

    def test_sha_vectors_and_readback(self):
        for index,data in enumerate((b'',b'abc',b'a'*55,b'b'*56,b'c'*63,b'd'*64,b'e'*65,bytes(range(256))*4097)):
            with self.subTest(size=len(data)):
                source = self.root/f'source-{index}'
                target = self.root/f'target-{index}'
                source.write_bytes(data)
                result = subprocess.run([str(self.program),'copy',str(source),str(target),str(len(data)),
                                         hashlib.sha256(data).hexdigest(),'640'],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(target.read_bytes(),data)
                self.assertEqual(target.stat().st_mode & 0o777,0o640)

    def test_wrong_digest_size_existing_destination_and_symlink_are_refused(self):
        source = self.root/'negative-source'
        source.write_bytes(b'actual bytes')
        for label,count,digest in [('digest',12,'0'*64),('short',11,sha(source)),('long',13,sha(source))]:
            target = self.root/('negative-'+label)
            result = subprocess.run([str(self.program),'copy',str(source),str(target),str(count),digest,'600'],capture_output=True)
            self.assertNotEqual(result.returncode,0)
        existing = self.root/'existing'
        existing.write_bytes(b'keep')
        link = self.root/'link'
        link.symlink_to(source)
        for src,dst in [(source,existing),(link,self.root/'symlink-output')]:
            result = subprocess.run([str(self.program),'copy',str(src),str(dst),'12',sha(source),'600'],capture_output=True)
            self.assertNotEqual(result.returncode,0)
        self.assertEqual(existing.read_bytes(),b'keep')
        self.assertEqual(subprocess.run([str(self.program),'space',str(self.root),str(2**63)],capture_output=True).returncode,4)


@unittest.skipUnless(all(shutil.which(x) for x in ('mke2fs','debugfs','e2fsck','resize2fs')),'e2fsprogs required')
class Builder(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cold-chain-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.runtime = self.base/'runtime-analysis'
        self.root = self.runtime/'root'
        self.parts = self.root/'partitions'
        self.parts.mkdir(parents=True)
        self.output = self.base/'output'
        ram_tree = self.base/'ram-tree'
        p7_tree = self.base/'p7-tree'
        p15_tree = self.base/'p15-tree'
        ram_tree.mkdir();p7_tree.mkdir();p15_tree.mkdir()
        self.ram_identity = {}
        self.p7_identity = {}
        self.script_bytes = {}
        for tree,wanted,dest in [(ram_tree,API.RAM_SCRIPTS,self.ram_identity),(p7_tree,API.P7_SCRIPTS,self.p7_identity)]:
            for name in wanted:
                data = ('#!/bin/busybox sh\n# fixture '+name+'\n').encode()
                path = tree/name.lstrip('/')
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(data)
                path.chmod(0o755)
                dest[name] = sha(path)
                self.script_bytes[name] = data
        for tree in (ram_tree,p7_tree):
            (tree/'bin').mkdir(exist_ok=True)
            (tree/'bin/busybox').write_bytes(b'fixture busybox inode; never executed\n')
            (tree/'sbin/insmod').symlink_to('../bin/busybox')
        # Existing unusual directory permissions must survive addition of children.
        (ram_tree/'sbin').chmod(0o750)
        self.ram = self.base/'original-ram.ext2'
        image(ram_tree,self.ram)
        image(p7_tree,self.parts/'a7c2-rootfs.img')
        bootin = p15_tree/'bin/bootin.elf'
        bootin.parent.mkdir()
        bootin.write_bytes(b'original ELF fixture; never executed\n')
        bootin.chmod(0o755)
        self.bootin_sha = sha(bootin)
        im = p15_tree/'bin/im.elf'
        im.write_bytes(b'synthetic IM executable fixture; never executed\n')
        im.chmod(0o755)
        self.im_sha, self.im_bytes = sha(im), im.stat().st_size
        self.wrapper = self.base/'authoritative-bootin-wrapper'
        self.wrapper.write_text((HERE/'guest/bootin-wrapper').read_text().replace(API.BOOTIN_SHA,self.bootin_sha))
        image(p15_tree,self.parts/'a7c2-usr.img')
        for name in API.NAMES.values():
            path = self.parts/name
            if not path.exists():
                path.write_bytes(bytes(4096))
        sim = self.root/'simulation'
        sim.mkdir()
        for name in ('attach-loop','bootin-wrapper','ramfb-viewer','menu-observe.so','seed-power-on'):
            path = sim/name
            path.write_bytes(('prepared helper '+name+'\n').encode())
            path.chmod(0o755)
        (self.root/'sbin').mkdir()
        self.insmod = self.root/'sbin/insmod'
        self.insmod.write_bytes(b'#!/bin/busybox sh\nexit 78\n')
        (self.root/'lib').mkdir()
        self.libc = self.root/'lib/libc-2.25.so'
        self.libc.write_bytes(b'fixture link dependency, compiler mocked\n')
        self.manifest = {'schema':1,'source':'private-device-dump',
                         'images':[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(self.parts.iterdir())],
                         'derived_files':{'sbin/insmod':sha(self.insmod),'lib/libc-2.25.so':sha(self.libc)}}
        self.manifest_path = self.runtime/'full-system.json'
        self.save_manifest()
        self.patches = [patch.object(API,'ORIGINAL_RAMROOT_SHA',sha(self.ram)),
                        patch.object(API,'RAM_SCRIPTS',self.ram_identity),
                        patch.object(API,'P7_SCRIPTS',self.p7_identity),
                        patch.object(API,'BOOTIN_SHA',self.bootin_sha),
                        patch.object(API,'IM_SHA',self.im_sha),
                        patch.object(API,'IM_BYTES',self.im_bytes),
                        patch.object(API,'INSMOD',API.INSMOD.replace(API.IM_SHA,self.im_sha)),
                        patch.object(API,'BOOTIN_WRAPPER_SOURCE',self.wrapper),
                        patch.object(API,'_extract_initrd',side_effect=lambda source,target:shutil.copyfile(self.ram,target)),
                        patch.object(API,'_compile_audit',side_effect=lambda source,libc,target:target.write_bytes(b'guest audit fixture\n'))]
        for item in self.patches:
            item.start();self.addCleanup(item.stop)

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest))

    def test_real_ext2_build_preserves_scripts_sources_and_independent_inodes(self):
        before = {p.name:sha(p) for p in self.parts.iterdir()}
        result = API.build(self.runtime,self.output)
        self.assertTrue(result['build_verified'])
        self.assertEqual(result['expected_im'],{'schema':1,'version':API.IM_VERSION,
                         'bytes':self.im_bytes,'sha256':self.im_sha})
        self.assertEqual(result['source'],'private-device-dump')
        self.assertEqual(result['script_identity'],{'ram0':self.ram_identity,'p7':self.p7_identity})
        self.assertEqual(json.loads((self.output/'manifest.json').read_text()),result)
        self.assertEqual(result['guest_evidence']['pivot_chroot'],None)
        self.assertFalse(result['capture_verified'])
        selected = result['helper_selection']['bootin-wrapper']
        self.assertTrue(selected['prepared_copy_replaced'])
        self.assertEqual(selected['selected_sha256'],sha(self.wrapper))
        self.assertNotEqual(selected['selected_sha256'],selected['prepared_source']['sha256'])
        self.assertEqual((Path(result['simulation_dir'])/'bootin-wrapper').read_bytes(),self.wrapper.read_bytes())
        self.assertEqual(result['simulation_identity']['bootin-wrapper']['sha256'],sha(self.wrapper))
        self.assertNotIn('rdinit=',result['cold_cmdline'])
        self.assertIn('rw noatime',result['cold_cmdline'])
        self.assertEqual(len(result['derived_volumes']),19)
        for row in result['derived_volumes']:
            source = self.parts/row['name']
            self.assertEqual(sha(source),before[row['name']])
            self.assertNotEqual(source.stat().st_ino,Path(row['path']).stat().st_ino)
            self.assertEqual(sha(Path(row['path'])),row['sha256'])
            self.assertEqual(row['access'],'ro' if row['part'] in ('7','15') else 'rw')
        for path in ('/sbin/init','/sbin/initrc/setup_rootfs'):
            value = subprocess.run(['debugfs','-R','cat '+path,result['ram0_image']],capture_output=True,check=True)
            self.assertEqual(value.stdout,self.script_bytes[path])
        scratch = self.output/'check';scratch.mkdir()
        overlay = API.runpy.run_path(str(HERE/'overwrite-images.py'))
        inventory = overlay['Ext2'](Path(result['ram0_image']),scratch).inventory()
        self.assertEqual(inventory['entries']['/sbin']['mode'] & 0o777,0o750)
        self.assertEqual(inventory['entries']['/partitions']['target'],'/dev/qemu-partitions')
        self.assertIn('/qemu-input/partitions/a7c2-rootfs.img',inventory['entries'])

    def test_nonordinary_files_and_linked_parents_are_refused(self):
        original = self.parts/'nflasha1.img'
        moved = self.base/'held-volume';original.rename(moved)
        original.symlink_to(moved)
        with self.assertRaisesRegex(ValueError,'symlink'):
            API.build(self.runtime,self.output)
        original.unlink();os.mkfifo(original)
        with self.assertRaisesRegex(ValueError,'ordinary'):
            API.build(self.runtime,self.output)
        original.unlink();moved.rename(original)
        directory = self.base/'real-partitions';self.parts.rename(directory);self.parts.symlink_to(directory,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'symlink'):
            API.build(self.runtime,self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_source_profile_and_sd_loop18_are_refused(self):
        for key,value in [('source','mixed-fallback'),('schema',True),('bootin_wrapper_experiment',{'virtual_sd_present':True})]:
            old = dict(self.manifest)
            self.manifest[key] = value;self.save_manifest()
            with self.subTest(key=key),self.assertRaises(ValueError):
                API.build(self.runtime,self.output)
            self.manifest = old;self.save_manifest()
        (self.parts/'bootin-sd-ext2.img').write_bytes(b'card')
        with self.assertRaisesRegex(ValueError,'SD conflict'):
            API.build(self.runtime,self.output)
        self.assertFalse(self.output.exists())

    def test_size_hash_capacity_and_existing_output_are_refused(self):
        for size in (True,4097,4096,4*1024**3+4096):
            with self.subTest(size=size),self.assertRaisesRegex(ValueError,'RAM0 size'):
                API.build(self.runtime,self.output,ram0_bytes=size)
        self.manifest['images'][0]['bytes'] = 0x80000001;self.save_manifest()
        with self.assertRaisesRegex(ValueError,'size differs'):
            API.build(self.runtime,self.output)
        self.manifest['images'][0]['bytes'] = (self.parts/self.manifest['images'][0]['name']).stat().st_size
        self.manifest['images'][0]['sha256'] = '0'*64;self.save_manifest()
        with self.assertRaisesRegex(ValueError,'identity'):
            API.build(self.runtime,self.output)
        self.manifest['images'][0]['sha256'] = sha(self.parts/self.manifest['images'][0]['name']);self.save_manifest()
        with patch.object(API.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(1,1,0)):
            with self.assertRaisesRegex(OSError,'Insufficient space'):
                API.build(self.runtime,self.output)
        self.assertFalse(self.output.exists())
        self.output.mkdir()
        with self.assertRaisesRegex(ValueError,'new directory'):
            API.build(self.runtime,self.output)

    def test_source_change_and_build_failure_retain_work_without_success(self):
        def changed(source,target):
            shutil.copyfile(self.ram,target)
            self.insmod.write_bytes(b'changed while building')
        with patch.object(API,'_extract_initrd',side_effect=changed):
            with self.assertRaisesRegex(ValueError,'Source changed'):
                API.build(self.runtime,self.output)
        self.assertTrue((self.output/'failure.json').is_file())
        self.assertTrue((self.output/'work/ram0.ext2').is_file())
        self.assertFalse((self.output/'manifest.json').exists())

    def test_stale_authoritative_wrapper_protocol_is_rejected_before_build(self):
        self.wrapper.write_text('#!/bin/busybox sh\nexec /simulation/bootin-original "$@"\n')
        with self.assertRaisesRegex(ValueError,'original-ELF handoff'):
            API.build(self.runtime,self.output)
        self.assertFalse(self.output.exists())

    def test_original_script_mismatch_does_not_publish(self):
        bad = dict(self.ram_identity);bad['/sbin/init'] = '0'*64
        with patch.object(API,'RAM_SCRIPTS',bad):
            with self.assertRaisesRegex(ValueError,'Original script identity'):
                API.build(self.runtime,self.output)
        self.assertFalse((self.output/'manifest.json').exists())
        self.assertTrue((self.output/'failure.json').exists())

    def test_raw_launch_adapter_preserves_owner_and_refuses_unknown_templates(self):
        template = '''#!/bin/bash
set -euo pipefail
[[ -S /tmp/cold-test-socket ]] || :
test_initrd="${5:-$bootfs/initrd.img}"
if [[ "$native_window" == 1 ]] && { [[ "$skip_hwtimer" != 1 || "$boot_memory" != 1 ]] || [[ "$test_initrd" != *.cpio && "$test_initrd" != *.cpio.gz ]]; }; then
  echo 'Native ramfb requires high-DDR boot memory and cpio initramfs'; exit 2
fi
cmdline='console=ttyAMA0 earlycon=pl011,0x09000000 loglevel=8 root=/dev/ram0 init=/bin/sh'
    cmdline+=" ramdisk_size=$image_kib"
if [[ "$test_initrd" == *.cpio || "$test_initrd" == *.cpio.gz ]]; then
      cmdline+=' rdinit=/init'
      cmdline+=' memrsv=0x1000@0x400000000'
fi
: <<'PYTHON'
ddr_size = 0x200000000  # explicit full-dump experiment: 8 GiB guest DDR
PYTHON
memory_config=24576
: -kernel /kernel.img -initrd /initrd.img
if [[ "${QEMU_PREPARE_ONLY:-0}" == 1 ]]; then
    exit 0
fi
'''
        manifest = {'schema':1,'profile':API.PROFILE,'build_verified':True,
                    'cold_cmdline':'root=/dev/ram0 rootfstype=ext2 init=/sbin/cold-storage-bootstrap coldchain.profile='+API.PROFILE,
                    'ram0_image':'/isolated/cold.ext2'}
        text = API.launch_script(template,manifest)
        target = self.base/'launch.sh';target.write_text(text)
        subprocess.run(['bash','-n',str(target)],check=True)
        self.assertNotIn('rdinit=/init',text)
        self.assertNotIn('-initrd /initrd.img',text)
        self.assertIn('memory_config=24576',text)
        self.assertIn('rw noatime',text)
        self.assertIn('ddr_size = 0x200000000',text)
        self.assertIn('QEMU_UI_LIVE',text)
        self.assertIn('Conflicting cold-chain',text)
        self.assertIn('memrsv=0x1000@0x400000000',text)
        self.assertEqual(subprocess.run(['bash',str(target)],env={'PATH':os.defpath},capture_output=True).returncode,2)
        self.assertEqual(subprocess.run(['bash',str(target)],env={'PATH':os.defpath,'QEMU_UI_LIVE':'1','QEMU_OUTPUT_DIR':'/tmp/unused-cold-test','QEMU_EXTRA_CMDLINE':'init=/bin/sh'},capture_output=True).returncode,2)
        launch_input = self.base/'launch-runtime/analysis'
        launch_input.mkdir(parents=True)
        (launch_input.parent/'sources').mkdir()
        (launch_input/'full-system.json').write_text(json.dumps({'source':'private-device-dump'}))
        (launch_input/'qemu-kernel-probe.sh').write_text(template)
        for name in ['boot-handoff.bin','boards/virt-four.dtb',
                     'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin',
                     'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt']:
            path = launch_input/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'launch asset fixture')
        launch_ram = self.base/'launch-ram.ext2';launch_ram.write_bytes(b'bound image')
        ready = {**manifest,'source':'private-device-dump','ram0_image':str(launch_ram),'ram0_sha256':sha(launch_ram),'inputs':[]}
        run = subprocess.run
        def prepare_only(command,**kwargs):
            if command[0]!='bash':return run(command,**kwargs)
            self.assertEqual(kwargs['env']['QEMU_PREPARE_ONLY'],'1')
            output = Path(kwargs['env']['QEMU_OUTPUT_DIR']);output.mkdir()
            (output/'virt.dtb').write_bytes(b'dtb fixture')
            (output/'cold-cmdline.txt').write_text(ready['cold_cmdline']+'\n')
            return subprocess.CompletedProcess(command,0)
        launch_dir = self.base/'prepared-launch'
        with patch.object(API,'KERNEL_SHA',hashlib.sha256(b'launch asset fixture').hexdigest()), \
             patch.object(API.subprocess,'run',side_effect=prepare_only):
            prepared = API.prepare_launch(launch_input,ready,launch_dir)
        self.assertFalse(prepared['guest_started'])
        self.assertFalse(prepared['qemu_initially_paused'])
        self.assertEqual(prepared['env']['QEMU_FULL_BOOT_SHIM'],'1')
        self.assertEqual(prepared['env']['QEMU_FULL_USB_INIT'],'original')
        self.assertNotIn('QEMU_PREPARE_ONLY',prepared['env'])
        self.assertEqual(prepared['guest_ddr_bytes'],8*1024**3)
        launch_ram.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError,'RAM0 SHA256'):
            API.prepare_launch(launch_input,ready,self.base/'tampered-launch')
        for wrong in (text,template+'\nqemu-system-aarch64 -S\n',template.replace('memory_config=24576','memory_config=other')):
            with self.assertRaises(ValueError):API.launch_script(wrong,manifest)
        for key,value in [('profile','other'),('build_verified',False),('cold_cmdline','$(false)'),
                          ('cold_cmdline',manifest['cold_cmdline']+' ro')]:
            with self.assertRaises(ValueError):API.launch_script(template,{**manifest,key:value})

    def test_bootstrap_has_no_early_root_or_application_handoff(self):
        script = (HERE/'guest/cold-storage-bootstrap').read_text()
        for command in ('pivot_root','chroot','/sbin/init2','/usr/bin/bootin.elf','mount -a'):
            self.assertNotIn(command,script)
        self.assertIn('exec /bin/busybox sh -x /sbin/init',script)
        self.assertIn(' - devtmpfs ',script)
        self.assertIn('/proc/self/mountinfo',script)
        self.assertIn('/qemu/cold-start-audit copy',script)
        self.assertLess(script.index('managed-memory'),script.index('while read -r relative'))
        subprocess.run(['sh','-n',str(HERE/'guest/cold-storage-bootstrap')],check=True)


if __name__ == '__main__':
    unittest.main()
