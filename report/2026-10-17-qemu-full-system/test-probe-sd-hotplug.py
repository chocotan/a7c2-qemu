#!/usr/bin/env python3
"""Boundary tests for the SD hotplug criteria in the firmware-file-media probe.

The verdict must key only on receipts the original firmware printed: its own
Unmount, its own re-Mount, and its own Fsys reads after that re-Mount. A changed
card file on the host, or an extra notification, is never enough.
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_file_media',HERE/'probe-file-media.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


def read(file,handle,generation,actual=9670656):
    return (f'FILE_MEDIA_READ pid=445 file={file} handle={handle} generation={generation} '
            f'offset=0 requested=10485760 actual={actual} hashed=65536 fnv64=816aa684e477b2c7')


MOUNT='FILE_MEDIA_FSYS op=Mount path=/nondev/rm2 flags=0x300 drive=65 result=0'
UNMOUNT='FILE_MEDIA_FSYS op=Unmount drive=65 flags=0x1 result=0'
PAYLOADS=['02000007000000','02000007000200']


def snapshot(media,filesystem,at=500.0):
    return {'verified':True,'observation_seconds':at,'fields':{
        'media_mount_state_slot1':{'value':media},
        'media_filesystem_mount_state_slot1':{'value':filesystem},
        'media_mount_state_slot2':{'value':0},
        'media_filesystem_mount_state_slot2':{'value':0}}}


class HotplugVerdict(unittest.TestCase):
    def verdict(self,text,payloads=None,snapshots=None,exported=True):
        return PROBE.hotplug_verdict(text,snapshots if snapshots is not None else [snapshot(2,1)],
                                     PAYLOADS if payloads is None else payloads,
                                     exported)

    def test_full_cycle_verifies(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3)])
        result=self.verdict(text)
        self.assertTrue(result['hotplug_cycle_verified'])
        self.assertEqual(len(result['unmount_receipts']),1)
        self.assertEqual(len(result['remounts_after_unmount']),1)
        self.assertEqual([entry['generation'] for entry in result['reads_after_remount']],[3])

    def test_read_before_unmount_does_not_count_as_reread(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT])
        self.assertFalse(self.verdict(text)['hotplug_cycle_verified'])

    def test_failed_unmount_is_not_an_unmount(self):
        text='\n'.join([MOUNT,read(1,'1',1),
                        'FILE_MEDIA_FSYS op=Unmount drive=65 flags=0x1 result=-6',
                        MOUNT,read(1,'42',3)])
        result=self.verdict(text)
        self.assertEqual(result['unmount_receipts'][0]['result'],-6)
        self.assertFalse(result['remounts_after_unmount'])
        self.assertFalse(result['hotplug_cycle_verified'])

    def test_both_payloads_required(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3)])
        self.assertFalse(self.verdict(text,payloads=['02000007000200'])['hotplug_cycle_verified'])
        self.assertFalse(self.verdict(text,payloads=['02000007000000'])['hotplug_cycle_verified'])

    def test_zero_length_read_is_not_evidence(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3,actual=0)])
        self.assertFalse(self.verdict(text)['hotplug_cycle_verified'])

    def test_unverified_snapshot_blocks_verdict(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3)])
        broken=[{'verified':False,'error':'capture gate system_mode: missing'}]
        self.assertFalse(self.verdict(text,snapshots=broken)['hotplug_cycle_verified'])

    def test_failed_card_export_blocks_verdict(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3)])
        self.assertFalse(self.verdict(text,exported=False)['hotplug_cycle_verified'])
        self.assertIsNone(self.verdict(text,exported=None)['card_export_verified'])

    def test_filesystem_series_is_reported_without_gating(self):
        series=[snapshot(2,1,500.0),snapshot(0,1,520.0),snapshot(2,1,545.0)]
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3)])
        result=self.verdict(text,snapshots=series)
        self.assertEqual([row['media_state_slot1'] for row in result['filesystem_state_series']],
                         [2,0,2])
        self.assertEqual([row['filesystem_state_slot1'] for row in result['filesystem_state_series']],
                         [1,1,1])
        self.assertTrue(result['filesystem_state_observed'])
        self.assertTrue(result['hotplug_cycle_verified'])

    def test_missing_destination_fields_are_not_silently_ignored(self):
        text='\n'.join([MOUNT,read(1,'1',1),UNMOUNT,MOUNT,read(1,'42',3)])
        result=self.verdict(text,snapshots=[{'verified':True,'fields':{
            'media_mount_state_slot1':{'value':2}}}])
        self.assertFalse(result['filesystem_state_observed'])


if __name__=='__main__':unittest.main()
