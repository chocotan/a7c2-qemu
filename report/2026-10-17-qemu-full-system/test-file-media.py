#!/usr/bin/env python3
"""Boundary tests for the firmware-file-media probe.

The probe's whole point is that the ORIGINAL mount/Fsys code writes the card, so
the criteria must key on the firmware's own evidence: the EXISTMEDIADRIVER flip,
the original `Fsys_Mount` wrapper receipt, and the card actually changing.
"""
import importlib.util
import hashlib
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_file_media',HERE/'probe-file-media.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


class Plan(unittest.TestCase):
    def test_the_digest_step_is_an_absolute_single_command(self):
        plan=PROBE.plan_with_digest('70:/simulation/inject-key a b c 0 1 0 1',560.0)
        digest=[entry for entry in plan if 'openssl' in entry]
        self.assertEqual(len(digest),1)
        self.assertTrue(digest[0].startswith('560.0:'))
        self.assertNotIn(';',digest[0])
        self.assertIn('/image_mmca',digest[0])

    def test_the_firmware_name_scan_is_a_single_pipeline(self):
        # The runner splits the plan on ';', so the scan must not contain one, and it
        # must look for the firmware's own directory names.
        self.assertNotIn(';',PROBE.SCAN_COMMAND)
        for name in ('DATABASE','M4ROOT','MEDIAPRO'):
            self.assertIn(name,PROBE.SCAN_COMMAND)
        self.assertIn('/image_mmca',PROBE.SCAN_COMMAND)

    def test_the_scan_comes_after_the_digest(self):
        plan=PROBE.plan_with_digest('70:x',560.0)
        digest=next(i for i,e in enumerate(plan) if 'dgst' in e)
        scan=next(i for i,e in enumerate(plan) if 'grep' in e)
        self.assertLess(digest,scan)

    def test_card_names_parses_the_counted_names(self):
        text='      2 DATABASE\n      1 M4ROOT\n'
        self.assertEqual(PROBE.card_names(text),{'DATABASE':2,'M4ROOT':1})
        self.assertEqual(PROBE.card_names('no names'),{})

    def test_the_walk_is_preserved(self):
        plan=PROBE.plan_with_digest('70:x;100:y',560.0)
        self.assertIn('70:x',plan)
        self.assertIn('100:y',plan)

    def test_plan_stays_time_ordered(self):
        plan=PROBE.plan_with_digest('70:x;600:y',560.0)
        times=[float(entry.partition(':')[0]) for entry in plan]
        self.assertEqual(times,sorted(times))


@unittest.skipUnless(shutil.which('fsck.fat'),'requires fsck.fat')
class HostVerification(unittest.TestCase):
    def test_an_identical_image_is_reported_as_unchanged(self):
        template=runpy.run_path(str(HERE/'file-media-template.py'))
        with tempfile.TemporaryDirectory() as directory:
            image=template['create'](Path(directory)/'card.fat')
            before=hashlib.sha256(image.read_bytes()).hexdigest()
            report=PROBE.verify_card_image(image,before)
            self.assertTrue(report['matches_template'])
            self.assertEqual(report['fsck_rc'],0)
            self.assertEqual(report['files'],{})
            self.assertIn('SEED',report['listing'])
            self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(),before)

    def test_matching_digest_does_not_hide_invalid_fat(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'corrupt.fat'
            image.write_bytes(b'not a FAT image'*512)
            report=PROBE.verify_card_image(image,hashlib.sha256(image.read_bytes()).hexdigest())
            self.assertTrue(report['matches_template'])
            self.assertNotEqual(report['fsck_rc'],0)
            self.assertIsNone(report['listing'])
            self.assertEqual(report['files'],{})


class Criteria(unittest.TestCase):
    def test_requested_destination_fields_cannot_silently_downgrade_to_base(self):
        gates=runpy.run_path(str(HERE/'test-capture-gates.py'))
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'key-plan.log';log.write_text(gates['fixture']())
            inferred=PROBE.capture_gate_snapshots(log)
            required=PROBE.capture_gate_snapshots(log,include_destination=True)
        self.assertTrue(inferred[0]['verified'])
        self.assertFalse(required[0]['verified'])

    def test_old_file_read_proof_requires_preload_and_original_mount(self):
        result=self.seeded_result()
        verified={'matches_template':True,'read_matches':[
            {'file':1,'verified':True},{'file':2,'verified':True}]}
        self.assertTrue(PROBE.existing_reads_verified(result,verified))
        for field in ('preload_applied','mount_via_file_backend','host_card_verified'):
            with self.subTest(field=field):
                self.assertFalse(PROBE.existing_reads_verified({**result,field:False},verified))

    def test_old_file_read_proof_rejects_missing_or_failed_file_receipts(self):
        result=self.seeded_result()
        for receipts in ([],[{'file':1,'verified':True}],
                         [{'file':1,'verified':True},{'file':2,'verified':False}]):
            with self.subTest(receipts=receipts):
                self.assertFalse(PROBE.existing_reads_verified(result,{
                    'matches_template':True,'read_matches':receipts}))
        verified={'matches_template':False,'read_matches':[
            {'file':1,'verified':True},{'file':2,'verified':True}]}
        self.assertFalse(PROBE.existing_reads_verified(result,verified))
        verified['matches_template']=True;result['seed']={'generated':True}
        self.assertFalse(PROBE.existing_reads_verified(result,verified))

    def test_read_receipts_match_only_the_exact_seed_slice(self):
        raw=b'abcdefg'
        # FNV-1a("abc") known vector, not calculated by the verifier under test.
        receipt={'offset':0,'actual':3,'requested':7,'hashed':3,'fnv64':'e71fa2190541574b'}
        self.assertTrue(PROBE.match_read(raw,receipt))
        for changes in ({'offset':1},{'actual':8},{'requested':2},{'hashed':2},{'fnv64':'0'*16}):
            with self.subTest(changes=changes):self.assertFalse(PROBE.match_read(raw,{**receipt,**changes}))

    def test_read_receipts_have_explicit_handle_generation_and_actual_count(self):
        line='FILE_MEDIA_READ pid=444 file=2 handle=15 generation=2 offset=0 requested=406 actual=406 hashed=406 fnv64=0000000000000001'
        got=PROBE.read_receipts(line)
        self.assertEqual(len(got),1)
        self.assertEqual(got[0]['file'],2)
        self.assertEqual(got[0]['actual'],406)
        self.assertEqual(got[0]['generation'],2)
        self.assertEqual(PROBE.read_receipts('Fsys_Read result=0'),[])

    def seeded_result(self):
        return {'returncode':0,'vm_state':'observation-completed','seed':{'source_unchanged':True},
                'preload_applied':True,'mount_via_file_backend':True,'existing_database_opened':True,
                'card_changed':False,'host_card_verified':True,'card_flush_lifecycle_verified':True,
                'firmware_wrote_card':False,'existing_database_consumed':False}

    def test_seed_open_preservation_does_not_require_a_new_write(self):
        self.assertTrue(PROBE.verified_goal(self.seeded_result()))

    def test_seed_snapshot_requires_flush_recovery_and_original_mount(self):
        for field in ('preload_applied','mount_via_file_backend','existing_database_opened',
                      'host_card_verified','card_flush_lifecycle_verified'):
            result=self.seeded_result();result[field]=False
            with self.subTest(field=field):self.assertFalse(PROBE.verified_goal(result))
        result=self.seeded_result();result['card_changed']=True
        self.assertFalse(PROBE.verified_goal(result))

    def test_failure_cannot_pass_despite_partial_storage_evidence(self):
        result=self.seeded_result();result['returncode']=1
        self.assertFalse(PROBE.verified_goal(result))
        result=self.seeded_result();result['vm_state']='failed'
        self.assertFalse(PROBE.verified_goal(result))

    def test_fresh_card_still_requires_original_firmware_write(self):
        result=self.seeded_result();result['seed']={}
        self.assertFalse(PROBE.verified_goal(result))
        result['firmware_wrote_card']=True
        self.assertTrue(PROBE.verified_goal(result))

    def test_generated_template_metadata_does_not_select_the_old_card_goal(self):
        result=self.seeded_result();result['seed']={'generated':True}
        self.assertFalse(PROBE.verified_goal(result))
        result['firmware_wrote_card']=True
        self.assertTrue(PROBE.verified_goal(result))

    def test_early_vm_exit_preserves_missing_gate_log_as_negative_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            result=PROBE.capture_gate_snapshots(Path(directory)/'key-plan.log')
        self.assertEqual(len(result),1)
        self.assertFalse(result[0]['verified'])
        self.assertIn('not produced',result[0]['error'])

    def test_partial_gate_log_does_not_produce_verified_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'key-plan.log'
            log.write_text('CAPTURE_GATE_BEGIN_system_mode\ntruncated\n')
            result=PROBE.capture_gate_snapshots(log)
        self.assertEqual(len(result),1)
        self.assertFalse(result[0]['verified'])

    def test_layer_three_keys_on_the_original_database_path(self):
        # The firmware's own log is what proves it used the volume, so the marker
        # must be the real path and not a generic word like "PRIVATE".
        self.assertIn('A:/PRIVATE/DATABASE',PROBE.CARD_PATH_MARKERS)

    def test_the_digest_uses_the_guest_openssl(self):
        command=PROBE.digest_probe_command()
        self.assertTrue(command.startswith('/usr/bin/openssl dgst -sha256 '))
        self.assertTrue(command.endswith('/image_mmca'))


if __name__=='__main__':unittest.main()
