"""Host-only content roundtrips; synthetic evidence is never guest acceptance."""
import hashlib
import os
from pathlib import Path
import runpy
import json
import stat
import tempfile
import unittest
from unittest.mock import patch

API=runpy.run_path(str(Path(__file__).resolve().parent/'sd-directory.py'))


class DirectoryCard(unittest.TestCase):
    def test_export_directories_synced_bottom_up_before_sd_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root);image=root/'card.fat'
            baseline=API['pack'](sd,image);events=[]
            original_sync=os.fsync;original_rename=os.rename
            def sync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    events.append(('sync',os.readlink('/proc/self/fd/'+str(fd))))
                return original_sync(fd)
            def rename(*args,**kwargs):
                events.append(('rename',str(args[0])))
                return original_rename(*args,**kwargs)
            with patch.object(os,'fsync',side_effect=sync),patch.object(os,'rename',side_effect=rename):
                API['restore'](image,sd,baseline,self.evidence(image))
            before=events[:next(i for i,event in enumerate(events) if event[0]=='rename')]
            names=[Path(path).name for event,path in before]
            self.assertEqual(names[:2],['100MSDCF','DCIM'])
            self.assertEqual(len(names),3)
            self.assertTrue(names[2].startswith('.SD-export-'))

    def test_directory_sync_failure_does_not_publish_or_move_original_sd(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root);image=root/'card.fat'
            baseline=API['pack'](sd,image);original_sync=os.fsync
            def sync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('injected directory sync failure')
                return original_sync(fd)
            with patch.object(os,'fsync',side_effect=sync):
                with self.assertRaisesRegex(OSError,'injected'):
                    API['restore'](image,sd,baseline,self.evidence(image))
            self.assertEqual(API['directory_tree'](sd),baseline['tree'])
            self.assertFalse(list(root.glob('.SD-previous-*')))
            self.assertTrue(list(root.glob('.SD-export-*')))

    def test_growing_input_is_bounded_and_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            sd=Path(temporary)/'SD';sd.mkdir();source=sd/'growing.bin';source.write_bytes(b'a')
            original=os.fstat;seen=0
            def grow_after_size_read(fd):
                nonlocal seen
                info=original(fd)
                if os.readlink('/proc/self/fd/'+str(fd))==str(source):
                    seen+=1
                    if seen==2:
                        with source.open('ab') as stream:stream.write(b'b')
                return info
            with patch.object(os,'fstat',side_effect=grow_after_size_read):
                with self.assertRaisesRegex(ValueError,'grew'):
                    API['directory_tree'](sd)

    def fixture(self,root):
        sd=root/'SD';sd.mkdir();(sd/'DCIM').mkdir();(sd/'DCIM/100MSDCF').mkdir()
        (sd/'DCIM/100MSDCF/README.txt').write_bytes(b'host input fixture\x00\xff')
        (sd/'empty.bin').touch();(sd/'KeepCase.txt').write_bytes(b'case preserved')
        return sd

    def evidence(self,image):
        return {'card_snapshot_integrity_verified':True,'card_flush_lifecycle_verified':True,
                'state':'observation-completed',
                'card_image_sha256':hashlib.sha256(image.read_bytes()).hexdigest()}

    def test_nested_files_empty_file_and_case_survive_roundtrip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root);image=root/'card.fat'
            baseline=API['pack'](sd,image)
            report=API['restore'](image,sd,baseline,self.evidence(image))
            self.assertEqual(API['directory_tree'](sd),baseline['tree'])
            self.assertEqual(API['directory_tree'](Path(report['previous_directory'])),baseline['tree'])
            self.assertEqual((sd/'DCIM/100MSDCF/README.txt').read_bytes(),b'host input fixture\x00\xff')

    def test_input_image_is_exclusive_and_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root);image=root/'card.fat'
            before=API['directory_tree'](sd);image.write_bytes(b'keep original image')
            with self.assertRaises(FileExistsError):API['pack'](sd,image)
            self.assertEqual(image.read_bytes(),b'keep original image')
            self.assertEqual(API['directory_tree'](sd),before)

    def test_symlink_and_case_collisions_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root)
            (sd/'linked').symlink_to('/etc/passwd')
            with self.assertRaises((ValueError,OSError)):API['pack'](sd,root/'card.fat')
            (sd/'linked').unlink();(sd/'keepcase.TXT').write_text('conflict')
            with self.assertRaisesRegex(ValueError,'collision'):API['pack'](sd,root/'card.fat')

    def test_unverified_export_is_never_published(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root)
            before=API['directory_tree'](sd)
            with self.assertRaisesRegex(ValueError,'incomplete'):
                API['restore'](root/'absent.fat',sd,{'tree':before},{})
            self.assertEqual(API['directory_tree'](sd),before)

    def test_config_failure_does_not_discard_a_separately_completed_card_snapshot(self):
        receipts=runpy.run_path(str(Path(__file__).resolve().parent/'save-evidence.py'))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root);image=root/'card-image.bin'
            baseline=API['pack'](sd,image);size=image.stat().st_size;chunk=receipts['CHUNK']
            source={**self.evidence(image),'state':'failed','error':'injected config failure',
                    'failure_scope':receipts['CONFIG_FAILURE'],'configuration_save_failed':True,
                    'card_image_exported':True,'card_image_bytes':size,
                    'card_source_identity':'synthetic host fixture, not original guest evidence',
                    'card_input_producer_stopped_verified':True,'card_input_queue_empty_verified':True,
                    'terminal_evidence_checked':True,'terminal_console_sha256':'0'*64,
                    'card_chunk_receipts':[{'index':i,'offset':i*chunk,'bytes':min(chunk,size-i*chunk),
                                            'fnv64':'0'*16,'verified':True}
                                           for i in range((size+chunk-1)//chunk)]}
            raw=json.dumps(source).encode();(root/'result.json').write_bytes(raw)
            receipt=receipts['card_receipt'](source)
            receipt['session_result_sha256']=hashlib.sha256(raw).hexdigest()
            (root/'sd-terminal-receipt.json').write_text(json.dumps(receipt))
            report=API['restore'](image,sd,baseline,receipt)
            self.assertEqual(API['directory_tree'](sd),baseline['tree'])
            self.assertEqual(report['image_sha256'],source['card_image_sha256'])
            self.assertEqual(json.loads((root/'result.json').read_text())['state'],'failed')

    def test_host_edit_and_wrong_export_hash_preserve_sd(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sd=self.fixture(root);image=root/'card.fat'
            baseline=API['pack'](sd,image);proof=self.evidence(image)
            wrong=dict(proof,card_image_sha256='0'*64)
            with self.assertRaisesRegex(ValueError,'SHA'):API['restore'](image,sd,baseline,wrong)
            (sd/'new-host-file.txt').write_text('do not overwrite')
            edited=API['directory_tree'](sd)
            with self.assertRaisesRegex(ValueError,'Host SD changed'):
                API['restore'](image,sd,baseline,proof)
            self.assertEqual(API['directory_tree'](sd),edited)


if __name__=='__main__':unittest.main()
