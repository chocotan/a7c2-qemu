#!/usr/bin/env python3
"""Boundary tests for the VFAT guest-readback probe."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_vfat',HERE/'probe-vfat-overwrite.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)

DIGEST='a'*64
OTHER='b'*64


class GuestReadback(unittest.TestCase):
    def test_framed_digest_requires_complete_successful_command(self):
        nonce='a1b2';guest='/system/a b.txt'
        framed=f'OVERWRITE_BEGIN_{nonce}\nSHA256({guest})= {DIGEST}\nOVERWRITE_RC_{nonce}=0\nOVERWRITE_END_{nonce}\n'
        self.assertEqual(PROBE.guest_digest(framed,guest,DIGEST,nonce),DIGEST)
        for broken in (framed.replace('RC_a1b2=0','RC_a1b2=1'),
                       framed.replace('OVERWRITE_END_a1b2','missing'),
                       framed.replace('OVERWRITE_BEGIN_a1b2','echo OVERWRITE_BEGIN_a1b2')):
            with self.subTest(broken=broken),self.assertRaises(ValueError):
                PROBE.guest_digest(broken,guest,DIGEST,nonce)

    def test_manifest_path_without_the_matching_digest_does_not_pass(self):
        expected={'/system/a.txt':{'sha256':DIGEST}}
        recorded,errors=PROBE.image_manifest_errors(expected,{
            'user_overwrite':{'files':[{'path':'/system/a.txt','sha256':OTHER}]}})
        self.assertEqual(len(errors),1)
        recorded,errors=PROBE.image_manifest_errors(expected,{
            'user_overwrite':{'files':[{'path':'/system/a.txt','sha256':DIGEST}]}})
        self.assertFalse(errors)

    def test_path_is_shell_quoted_and_does_not_split_the_plan(self):
        command=PROBE.readback_command('/system/space $(do_not_run).txt','1234')
        self.assertIn("'/system/space $(do_not_run).txt'",command)
        self.assertNotIn(';',command)
        with self.assertRaises(ValueError):PROBE.readback_command('/a\nb','1234')
        with self.assertRaises(ValueError):PROBE.readback_command('/a;b','1234')

    def test_all_files_failure_keeps_user_sources_and_records_runner_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'overwrite';folder.mkdir()
            source=folder/'mine.txt';source.write_bytes(b'keep these bytes')
            with patch.object(sys,'argv',['probe','--workspace',str(root),'--all-files']), \
                 patch.object(PROBE.subprocess,'run',return_value=subprocess.CompletedProcess([],1,'boot failed','reason')):
                with self.assertRaises(SystemExit):PROBE.main()
            self.assertEqual(source.read_bytes(),b'keep these bytes')
            self.assertEqual(list(folder.iterdir()),[source])
            self.assertIn('boot failed',(root/'probe-runner.log').read_text())

    def test_default_probe_never_overwrites_existing_user_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'overwrite/system/vfat-system-probe.txt'
            target.parent.mkdir(parents=True);target.write_bytes(b'user file')
            with patch.object(sys,'argv',['probe','--workspace',str(root)]):
                with self.assertRaisesRegex(ValueError,'already exist'):PROBE.main()
            self.assertEqual(target.read_bytes(),b'user file')

    def test_matching_guest_digest_is_accepted(self):
        console=f'SHA2-256(/system/vfat-system-probe.txt)= {DIGEST}\n'
        self.assertEqual(PROBE.guest_digest(console,'/system/vfat-system-probe.txt',DIGEST),DIGEST)

    def test_missing_report_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'never reported'):
            PROBE.guest_digest('nothing here','/system/vfat-system-probe.txt',DIGEST)

    def test_conflicting_reports_are_rejected(self):
        console=(f'SHA2-256(/cp/vfat-cp-probe.txt)= {DIGEST}\n'
                 f'SHA2-256(/cp/vfat-cp-probe.txt)= {OTHER}\n')
        with self.assertRaisesRegex(ValueError,'conflicting'):
            PROBE.guest_digest(console,'/cp/vfat-cp-probe.txt',DIGEST)

    def test_host_only_match_is_rejected(self):
        console=f'SHA2-256(/cp/vfat-cp-probe.txt)= {OTHER}\n'
        with self.assertRaisesRegex(ValueError,'differs from the written bytes'):
            PROBE.guest_digest(console,'/cp/vfat-cp-probe.txt',DIGEST)

    def test_probes_target_vfat_mounts_and_are_new_paths(self):
        for guest,relative in PROBE.PROBES.items():
            with self.subTest(guest=guest):
                self.assertTrue(guest.startswith(('/system/','/cp/','/setting/')))
                self.assertEqual(relative,guest.lstrip('/'))
                self.assertIn(b'no device data',PROBE.contents(guest))


if __name__=='__main__':unittest.main()
