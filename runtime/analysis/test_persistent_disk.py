import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

api=runpy.run_path(str(Path(__file__).with_name('persistent_disk.py')))


class CameraDiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.source.mkdir()
        self.config=self.root/'partinf.conf';rows=[];records=[];start=128
        for part in range(1,31):
            size=8 if part in api['PARTS'] else 0
            rows.append(f'0x{start:08x},0x{size:08x},0x00000004,0xffffffff\n')
            if size:
                name=api['image_name'](part);data=bytes([part])*4096
                (self.source/name).write_bytes(data)
                records.append({'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            start+=size
        self.config.write_text(''.join(rows))
        for part in ('B0','B1'):
            data=bytes(api['BOOT_BYTES']);name='nflasha'+part+'.img'
            (self.source/name).write_bytes(data)
            records.append({'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        (self.source/'manifest.json').write_text(json.dumps({'source':'official-bodydata-derived','images':records}))
        self.output=self.root/'instance'

    def create(self):
        with patch.dict(api['create'].__globals__,USER_CAPACITY=1024*1024,shutil=SimpleNamespace(disk_usage=lambda p:SimpleNamespace(free=1<<36))):
            return api['create'](self.source,self.config,self.output)

    def test_one_disk_contains_exact_label_slices_and_independent_boot_areas(self):
        result=self.create();geometry=json.loads((self.output/'geometry.json').read_text())
        disk=self.output/'camera.emmc';self.assertEqual(disk.stat().st_size,geometry['backing_bytes'])
        self.assertEqual(geometry['backing_bytes'],geometry['user_bytes']+2*api['BOOT_BYTES'])
        fd=os.open(disk,os.O_RDONLY)
        try:
            label=os.pread(fd,512,0);self.assertEqual(label[:8],b'82462.00')
            self.assertEqual(len(geometry['slices']),19)
            for row in geometry['slices']:
                self.assertEqual(api['hashed'](fd,row['offset'],row['bytes']),row['source_sha256'])
        finally:os.close(fd)
        self.assertEqual(result['generation'],0)
        self.assertIn('reuse',result['normal_restart_policy'])

    def test_root_file_block_changes_persist_across_next_disk_lease(self):
        self.create()
        with api['lease'](self.output) as first:
            target=next(v for v in first['geometry']['slices'] if v['id']=='nflasha15')
            position=target['offset']+512
            self.assertEqual(os.pwrite(first['fd'],b'changed appFw block',position),19)
            os.fsync(first['fd'])
            with self.assertRaises(BlockingIOError):
                with api['lease'](self.output):pass
        with api['lease'](self.output) as second:
            self.assertEqual(os.pread(second['fd'],19,position),b'changed appFw block')
        self.assertEqual((self.source/'a7c2-usr.img').read_bytes(),bytes([15])*4096)

    def test_inherited_disk_ofd_blocks_new_lease_until_last_descriptor_closes(self):
        self.create();held=None;image=self.output/'camera.emmc'
        before=hashlib.sha256(image.read_bytes()).hexdigest()
        try:
            with api['lease'](self.output) as first:
                held=os.dup(first['fd'])
            with self.assertRaises(BlockingIOError):
                with api['lease'](self.output):self.fail('live OFD admitted another writer')
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)
            lock=api['_DiskLock'](fcntl.F_WRLCK,os.SEEK_SET,0,1,0)
            fcntl.fcntl(held,fcntl.F_OFD_SETLK,bytes(lock))
            self.assertEqual(os.pread(held,8,0),b'82462.00')
        finally:
            if held is not None:os.close(held)
        with api['lease'](self.output) as second:
            self.assertEqual(os.pread(second['fd'],8,0),b'82462.00')

    def test_unsupported_disk_lock_abi_refuses_lease_without_writing(self):
        self.create();image=self.output/'camera.emmc';before=hashlib.sha256(image.read_bytes()).hexdigest()
        with patch.dict(api['lease'].__wrapped__.__globals__,ctypes=SimpleNamespace(sizeof=lambda _type:0)):
            with self.assertRaisesRegex(ValueError,'Unsupported OFD'):
                with api['lease'](self.output):self.fail('unsupported ABI admitted')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)

    def test_ofd_lock_error_fails_closed_and_releases_lease(self):
        self.create();image=self.output/'camera.emmc';before=hashlib.sha256(image.read_bytes()).hexdigest()
        def reject(*_args):raise OSError(errno.EINVAL,'OFD lock unsupported')
        proxy=SimpleNamespace(flock=fcntl.flock,LOCK_EX=fcntl.LOCK_EX,LOCK_NB=fcntl.LOCK_NB,
                              F_OFD_SETLK=fcntl.F_OFD_SETLK,F_WRLCK=fcntl.F_WRLCK,fcntl=reject)
        with patch.dict(api['lease'].__wrapped__.__globals__,fcntl=proxy):
            with self.assertRaises(OSError) as error:
                with api['lease'](self.output):self.fail('unsupported lock admitted')
        self.assertEqual(error.exception.errno,errno.EINVAL)
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)
        with api['lease'](self.output) as leased:self.assertEqual(os.pread(leased['fd'],8,0),b'82462.00')

    def test_lock_open_failure_closes_instance_directory(self):
        self.create();opened=[];original=api['lease'].__wrapped__.__globals__['SECURE_OPEN']
        def secure(path,*args,**kwargs):
            if kwargs.get('directory'):
                fd=original(path,*args,**kwargs);opened.append(fd);return fd
            if Path(path).name=='.disk.lock':raise FileNotFoundError('synthetic missing lock')
            return original(path,*args,**kwargs)
        with patch.dict(api['lease'].__wrapped__.__globals__,SECURE_OPEN=secure):
            with self.assertRaisesRegex(FileNotFoundError,'missing lock'):
                with api['lease'](self.output):self.fail('missing lock admitted')
        self.assertEqual(len(opened),1)
        with self.assertRaises(OSError):os.fstat(opened[0])

    def test_owner_marker_binds_actual_shared_lease_and_survives_release(self):
        from owner_quarantine import Marker,Rejected
        self.create();marker=self.output/'owner-quarantine.json'
        with api['lease'](self.output) as leased:
            token=Marker(leased['dir_fd'],leased['lock_fd'],leased['fd'],'synthetic-run','synthetic-owner')
            try:
                token.arm_before_gate();token.require_armed_before_gate()
                raw=marker.read_bytes()
            finally:token.close()
        self.assertEqual(marker.read_bytes(),raw)
        with self.assertRaisesRegex(Rejected,'unfinished quarantine marker'):
            with api['lease'](self.output):self.fail('retained owner marker ignored')
        self.assertEqual(marker.read_bytes(),raw)

    def test_unfinished_owner_marker_blocks_shared_disk_lease(self):
        self.create();image=self.output/'camera.emmc';before=hashlib.sha256(image.read_bytes()).hexdigest()
        marker=self.output/'owner-quarantine.json';marker.write_bytes(b'partial or unknown owner')
        with self.assertRaisesRegex(RuntimeError,'unfinished quarantine marker'):
            with api['lease'](self.output):self.fail('unfinished owner admitted')
        self.assertEqual(marker.read_bytes(),b'partial or unknown owner')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)

    def test_quarantine_marker_symlink_never_counts_as_absent(self):
        self.create();marker=self.output/'owner-quarantine.json';marker.symlink_to(self.root/'missing')
        with self.assertRaisesRegex(RuntimeError,'unfinished quarantine marker'):
            with api['lease'](self.output):self.fail('symlink marker admitted')
        self.assertTrue(marker.is_symlink())

    def test_pending_settings_recovery_blocks_all_disk_leases(self):
        self.create();image=self.output/'camera.emmc';before=hashlib.sha256(image.read_bytes()).hexdigest()
        marker=self.output/'settings-reset-pending.json';marker.symlink_to(self.root/'missing')
        with self.assertRaisesRegex(ValueError,'未完成'):
            with api['lease'](self.output):self.fail('pending disk admitted')
        self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)
        marker.unlink()
        with api['lease'](self.output) as leased:self.assertEqual(api['hashed'](leased['fd']),before)

    def test_fixed_model_capacity_retains_unallocated_tail_and_boot_boundaries(self):
        rows,extent=api['parse_layout'](self.config.read_bytes())
        self.create()
        geometry=json.loads((self.output/'geometry.json').read_text())
        self.assertEqual(geometry['user_bytes'],1024*1024)
        self.assertEqual(geometry['unused_user_tail_bytes'],1024*1024-extent)
        boot=next(row for row in geometry['slices'] if row['id']=='nflashaB0')
        self.assertEqual(boot['offset'],1024*1024)
        self.assertIn('fixed publicly recorded',geometry['user_capacity_basis'])

    def test_non_official_factory_is_refused_without_creating_output(self):
        p=self.source/'manifest.json';value=json.loads(p.read_text());value['source']='private-device-dump';p.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.create()
        self.assertFalse(self.output.exists())

    def test_existing_output_never_reinitializes_instance(self):
        self.create();before=(self.output/'camera.emmc').stat().st_ino
        with self.assertRaises(ValueError):self.create()
        self.assertEqual((self.output/'camera.emmc').stat().st_ino,before)

    def test_source_hash_size_or_partition_capacity_mismatch_rejected(self):
        (self.source/'a7c2-usr.img').write_bytes(b'bad')
        with self.assertRaises(ValueError):self.create()
        self.assertFalse(self.output.exists())

    def test_unsafe_source_and_metadata_cannot_follow_symlinks(self):
        target=self.source/'a7c2-usr.img';target.unlink();target.symlink_to('/dev/null')
        with self.assertRaises(ValueError):self.create()
        target.unlink();target.write_bytes(bytes([15])*4096);self.create()
        info=self.output/'geometry.json';saved=self.root/'outside.json';saved.write_bytes(info.read_bytes())
        info.unlink();info.symlink_to(saved)
        with self.assertRaises(ValueError):
            with api['lease'](self.output):pass

    def test_geometry_mutation_and_backing_capacity_change_rejected(self):
        self.create();path=self.output/'camera.emmc'
        with path.open('r+b') as stream:stream.truncate(path.stat().st_size+512)
        with self.assertRaises(ValueError):
            with api['lease'](self.output):pass

    def test_layout_rejects_overlap_missing_or_unbounded_partitions(self):
        data=self.config.read_bytes()
        for invalid in [data.replace(b'0x00000080',b'0x00000000',1),data.splitlines()[0],data.replace(b'0x00000008',b'0x7fffffff',1)]:
            with self.subTest(invalid=invalid[:80]),self.assertRaises(ValueError):api['parse_layout'](invalid)


if __name__=='__main__':unittest.main()
