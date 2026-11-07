import hashlib
import json
import os
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

api=runpy.run_path(str(Path(__file__).with_name('camera-disk.py')))


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
        (self.source/'manifest.json').write_text(json.dumps({'images':records}))
        self.output=self.root/'instance'

    def create(self,capacity_record=None):
        with patch.dict(api['create'].__globals__,shutil=SimpleNamespace(disk_usage=lambda p:SimpleNamespace(free=1<<36))):
            return api['create'](self.source,self.config,self.output,capacity_record=capacity_record)

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

    def test_original_capacity_preserves_unallocated_tail_and_boot_boundaries(self):
        rows,extent=api['parse_layout'](self.config.read_bytes())
        capacities={'pnflasha':extent+31*1024**2,'nflashaB0':api['BOOT_BYTES'],'nflashaB1':api['BOOT_BYTES']}
        capacities.update({'pnflasha'+str(row['part']):row['bytes'] for row in rows if row['bytes']})
        record=self.root/'capacities.json';record.write_text(json.dumps({'block_devices_bytes':capacities}))
        self.create(record)
        geometry=json.loads((self.output/'geometry.json').read_text())
        self.assertEqual(geometry['user_bytes'],capacities['pnflasha'])
        self.assertEqual(geometry['unused_user_tail_bytes'],31*1024**2)
        boot=next(row for row in geometry['slices'] if row['id']=='nflashaB0')
        self.assertEqual(boot['offset'],capacities['pnflasha'])
        self.assertEqual(geometry['user_capacity_basis'],'original device capacity readback')

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
