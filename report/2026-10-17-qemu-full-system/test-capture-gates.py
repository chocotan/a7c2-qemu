#!/usr/bin/env python3
import runpy
from pathlib import Path
import unittest

API=runpy.run_path(str(Path(__file__).with_name('capture-gates.py')))


def fixture(include_sources=False,include_destination=False,include_context_end=False):
    text=''
    fields={**API['FIELDS'],**API['SOURCE_FIELDS']} if include_sources or include_destination else API['FIELDS']
    if include_destination:fields={**fields,**API['DESTINATION_FIELDS']}
    if include_context_end:fields={**fields,**API['CONTEXT_END_FIELDS']}
    for name,(address,size) in fields.items():
        address+=0x7f00000000
        raw=(2).to_bytes(size,'little').hex(' ')
        text+=(f'CAPTURE_GATE_BEGIN_{name}\n'
               f'READMEM /proc/453/mem address={address:x} bytes={size}\n'
               f'{address:016x}: {raw}\n'
               f'CAPTURE_GATE_END_{name}\n')
    return text


class Gates(unittest.TestCase):
    def test_destination_snapshot_does_not_confuse_volume_and_media_models(self):
        parsed=API['parse'](fixture(include_destination=True),include_destination=True)
        self.assertIn('media_mount_state_slot1',parsed)
        self.assertIn('media_filesystem_mount_state_slot1',parsed)
        self.assertNotEqual(parsed['media_mount_state_slot1']['address'],
                            parsed['media_filesystem_mount_state_slot1']['address'])
        command=API['command'](include_destination=True)
        self.assertIn('/simulation/capture-gates-reader "$1" 2',command)
        self.assertNotIn(';',command)
        with self.assertRaises(ValueError):
            API['parse'](fixture(True),include_destination=True)

    def test_boot_snapshot_is_not_a_valid_still_capture_context(self):
        fields=API['parse'](fixture(include_context_end=True))
        fields['system_mode']['value']=1
        fields['system_mode_option']['value']=fields['mode_transition']['value']=0
        fields['system_mode_end']['value']=2
        fields['system_mode_option_end']['value']=fields['mode_transition_end']['value']=0
        self.assertFalse(API['still_capture_context']({'verified':True,'fields':fields}))
        fields['system_mode']['value']=2
        self.assertTrue(API['still_capture_context']({'verified':True,'fields':fields}))
        self.assertFalse(API['still_capture_context']({'verified':False,'fields':fields}))
        fields['mode_transition']['value']=1
        self.assertFalse(API['still_capture_context']({'verified':True,'fields':fields}))

    def test_mode_change_during_sampling_and_missing_end_context_are_rejected(self):
        fields=API['parse'](fixture(include_context_end=True))
        for suffix in ('','_end'):
            fields['system_mode_option'+suffix]['value']=fields['mode_transition'+suffix]['value']=0
        self.assertTrue(API['still_capture_context']({'verified':True,'fields':fields}))
        fields['system_mode_end']['value']=0
        self.assertFalse(API['still_capture_context']({'verified':True,'fields':fields}))
        del fields['system_mode_end']
        self.assertFalse(API['still_capture_context']({'verified':True,'fields':fields}))

    def test_optional_sources_do_not_invalidate_older_base_snapshots(self):
        parsed=API['parse'](fixture())
        self.assertEqual(set(parsed),set(API['FIELDS']))
        with self.assertRaises(ValueError):API['parse'](fixture(),include_sources=True)

    def test_complete_source_snapshot_has_one_bias_and_read_only_commands(self):
        parsed=API['parse'](fixture(True),include_sources=True)
        self.assertEqual(set(parsed),set(API['FIELDS'])|set(API['SOURCE_FIELDS']))
        command=API['command'](include_sources=True)
        self.assertIn('/simulation/capture-gates-reader "$1" 1',command)
        self.assertNotIn(';',command)
        self.assertNotIn('writemem',command)

    def test_one_field_with_a_different_bias_is_rejected(self):
        text=fixture().replace('7f07e5d498','7f07e5d49c')
        with self.assertRaisesRegex(ValueError,'load bias'):API['parse'](text)

    def test_aslr_readback_and_types(self):
        parsed=API['parse'](fixture())
        self.assertEqual(parsed['capture_inhibit']['bytes'],1)
        self.assertEqual(parsed['ee_status']['value'],2)
        self.assertEqual(parsed['ee_status']['pid'],453)

    def test_repeated_identical_receipt_is_allowed(self):
        self.assertEqual(API['parse'](fixture()*2),API['parse'](fixture()))

    def test_conflicting_readback_is_rejected(self):
        with self.assertRaises(ValueError):
            API['parse'](fixture()+fixture().replace(': 02',': 03'))

    def test_short_read_or_kernel_interleaving_fails_closed(self):
        for text in (fixture().replace('bytes=4','bytes=0'),
                     fixture().replace(': 02',': [kernel] 02')):
            with self.subTest(text=text),self.assertRaises(ValueError):API['parse'](text)

    def test_command_reads_only_and_does_not_split_plan(self):
        command=API['command']()
        self.assertNotIn(';',command)
        self.assertIn('"$#" = 1',command)
        self.assertEqual(command.count('/simulation/capture-gates-reader '),1)
        self.assertIn('/simulation/capture-gates-reader "$1" 0',command)
        self.assertNotIn('/dev/mem',command)


if __name__=='__main__':unittest.main()
