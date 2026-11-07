#!/usr/bin/env python3
"""Exercise overwrite against real disposable ext2 images, not mocked tool RCs."""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

API=runpy.run_path(str(Path(__file__).with_name('overwrite-images.py')))


@unittest.skipUnless(all(shutil.which(x) for x in ('mke2fs','debugfs','e2fsck')),'e2fsprogs required')
class RealImageOverlay(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='overwrite-image-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);tree=self.root/'base-tree';(tree/'usr/bin').mkdir(parents=True)
        program=tree/'usr/bin/program';program.write_bytes(b'original-program\n');program.chmod(0o755)
        os.link(program,tree/'usr/bin/program-alias')
        (tree/'unrelated').write_bytes(b'keep-this-content\n')
        os.symlink('/usr/bin/program',tree/'program-link')
        self.image=self.root/'base.img'
        with self.image.open('wb') as f:f.truncate(8*1024**2)
        subprocess.run(['mke2fs','-q','-t','ext2','-F','-d',str(tree),str(self.image)],check=True)
        for field,value in (('uid',70000&65535),('uid_hi',70000>>16),('gid',80000&65535),('gid_hi',80000>>16)):
            subprocess.run(['debugfs','-w','-R',f'set_inode_field /usr/bin/program {field} {value}',str(self.image)],
                           check=True,capture_output=True)
        self.before=API['digest'](self.image)
        self.config=self.root/'mounts.json'
        self.config.write_text(json.dumps({'schema':1,'images':[{'id':'system','file':'base.img','fs':'ext2'}],
                                          'mounts':[{'guest':'/','image':'system'}]}))
        self.overwrite=self.root/'overwrite';self.overwrite.mkdir()
        self.output=self.root/'derived'

    def test_replace_preserves_execute_and_verifies_whole_tree(self):
        (self.overwrite/'usr/bin').mkdir(parents=True)
        replacement=self.overwrite/'usr/bin/program';replacement.write_bytes(b'custom-program\n');replacement.chmod(0o644)
        (self.overwrite/'usr/bin/new-empty').write_bytes(b'')
        os.symlink('program',self.overwrite/'usr/bin/new-link')
        report=API['build'](self.config,self.overwrite,self.output)
        self.assertEqual(API['digest'](self.image),self.before)
        self.assertTrue(report['images']['system']['full_tree_compared'])
        operations={o['guest_path']:o for o in report['operations']}
        changed=operations['/usr/bin/program']
        self.assertEqual(changed['action'],'replace')
        self.assertEqual(changed['after']['mode']&0o777,0o755)
        self.assertEqual(changed['after']['sha256'],hashlib.sha256(b'custom-program\n').hexdigest())
        self.assertEqual(changed['before']['uid'],changed['after']['uid'])
        self.assertEqual(changed['after']['uid'],70000)
        self.assertEqual(changed['after']['gid'],80000)
        self.assertEqual(operations['/usr/bin/new-empty']['after']['size'],0)
        retained=self.root/'retained.bin'
        subprocess.run(['debugfs','-R',f'dump /usr/bin/program-alias {retained}',str(self.output/'system.img')],
                       check=True,capture_output=True)
        self.assertEqual(retained.read_bytes(),b'original-program\n')
        self.assertFalse(report['signed_update_package'])
        self.assertEqual(json.loads((self.output/'overwrite-manifest.json').read_text()),report)

    def test_dry_run_does_not_publish_or_change_input(self):
        (self.overwrite/'unrelated').write_bytes(b'preview-only')
        report=API['build'](self.config,self.overwrite,self.output,dry_run=True)
        self.assertTrue(report['dry_run']);self.assertFalse(self.output.exists())
        self.assertEqual(API['digest'](self.image),self.before)

    def test_directory_file_conflict_never_publishes(self):
        (self.overwrite/'unrelated').mkdir()
        with self.assertRaisesRegex(ValueError,'type conflict'):
            API['build'](self.config,self.overwrite,self.output)
        self.assertFalse(self.output.exists());self.assertEqual(API['digest'](self.image),self.before)

    def test_mount_alias_collision_is_rejected(self):
        self.config.write_text(json.dumps({'schema':1,'images':[{'id':'system','file':'base.img','fs':'ext2'}],
            'mounts':[{'guest':'/etc','image':'system'},{'guest':'/tmp','image':'system'}]}))
        for directory,value in (('etc',b'one'),('tmp',b'two')):
            (self.overwrite/directory).mkdir();(self.overwrite/directory/'same').write_bytes(value)
        with self.assertRaisesRegex(ValueError,'Alias collision'):
            API['build'](self.config,self.overwrite,self.output)
        self.assertFalse(self.output.exists())

    def test_guest_symlink_is_not_a_host_parent(self):
        (self.overwrite/'program-link').mkdir()
        (self.overwrite/'program-link'/'outside').write_bytes(b'not-written-through-a-link')
        with self.assertRaisesRegex(ValueError,'type conflict'):
            API['build'](self.config,self.overwrite,self.output)
        self.assertFalse(self.output.exists());self.assertEqual(API['digest'](self.image),self.before)

    def test_symlink_escaping_guest_root_is_rejected(self):
        os.symlink('../../outside',self.overwrite/'escape')
        with self.assertRaisesRegex(ValueError,'escapes guest root'):
            API['build'](self.config,self.overwrite,self.output)
        self.assertFalse(self.output.exists())


def find_mtools():
    root=Path(__file__).resolve().parent/'runtime/analysis'
    return next((p for p in sorted(root.glob('mtools-*/extracted/usr/bin'))
                 if (p/'mcopy').is_file() and (p/'mdel').is_file()),None)


FACTORY=Path(__file__).resolve().parent/'runtime/factory-images/candidate-003'


@unittest.skipUnless(find_mtools() and (FACTORY/'mounts.json').is_file()
                     and all(shutil.which(x) for x in ('fsck.fat','debugfs','e2fsck')),
                     'mtools, fsck.fat and a public factory candidate are required')
class RealVfatAndExt2Overlay(unittest.TestCase):
    """Real VFAT12 volumes from the public factory build, copied into a temp dir."""

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='overwrite-vfat-test-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        manifest=json.loads((FACTORY/'mounts.json').read_text())
        # Only the volumes this test touches are copied, still byte-identical.
        keep={'nflasha2','nflasha7','nflasha3'}
        images=[]
        for image in manifest['images']:
            if image['id'] not in keep:continue
            shutil.copy2(FACTORY/image['file'],self.root/image['file'])
            images.append(dict(image))
        self.config=self.root/'mounts.json'
        mounts=[dict(m) for m in manifest['mounts'] if m['image'] in keep]
        self.config.write_text(json.dumps({'schema':1,'images':images,'mounts':mounts}))
        self.hashes={i['file']:API['digest'](self.root/i['file']) for i in images}
        self.overwrite=self.root/'overwrite';(self.overwrite/'setting').mkdir(parents=True)
        (self.overwrite/'setting/setting-probe.txt').write_bytes(b'vfat-probe-content\n')
        (self.overwrite/'usr/lib').mkdir(parents=True)
        (self.overwrite/'usr/lib/ext2-probe.txt').write_bytes(b'ext2-probe-content\n')
        self.output=self.root/'derived'

    def test_touched_vfat_and_ext2_with_full_tree_readback(self):
        report=API['build'](self.config,self.overwrite,self.output,
                            mtools_dir=str(find_mtools()),vfat_fmask=0o022,vfat_dmask=0o022)
        rows={row['guest_path']:row for row in report['operations']}
        self.assertEqual(rows['/setting/setting-probe.txt']['action'],'create')
        self.assertEqual(rows['/usr/lib/ext2-probe.txt']['action'],'create')
        vfat=report['images']['nflasha2'];ext2=report['images']['nflasha7']
        self.assertTrue(vfat['full_tree_compared'] and ext2['full_tree_compared'])
        self.assertTrue(report['images']['nflasha3']['unchanged_bytes_verified'])
        self.assertNotEqual(vfat['sha256'],self.hashes['nflasha2.img'])
        for name,hashed in self.hashes.items():
            self.assertEqual(API['digest'](self.root/name),hashed)
        self.assertEqual(subprocess.run(['fsck.fat','-n',str(self.output/vfat['file'])],
                                        capture_output=True).returncode,0)

    def test_touched_vfat_without_masks_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'explicit fmask/dmask'):
            API['build'](self.config,self.overwrite,self.output,mtools_dir=str(find_mtools()))
        self.assertFalse(self.output.exists())
        for name,hashed in self.hashes.items():
            self.assertEqual(API['digest'](self.root/name),hashed)


if __name__=='__main__':unittest.main()
