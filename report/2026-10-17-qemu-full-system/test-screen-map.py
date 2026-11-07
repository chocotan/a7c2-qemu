#!/usr/bin/env python3
"""Tests for screen recognition: every learned screen must match itself, and nothing else.

The map is only useful if a known page is never confused with another known page, so the
tests assert the margin between distinct screens as well as the self-match.
"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('screen_map',HERE/'screen-map.py')
SM=importlib.util.module_from_spec(spec);spec.loader.exec_module(SM)
MAP=HERE/'screens.json'


@unittest.skipUnless(MAP.is_file(),'screens.json is not present')
class Recognition(unittest.TestCase):
    def setUp(self):
        self.data=json.loads(MAP.read_text())
        self.entries=self.data['screens']

    def test_every_known_screen_matches_itself(self):
        for entry in self.entries:
            sample=HERE/entry['sample']
            if not sample.is_file():continue
            name,distance=SM.classify(sample,MAP)
            self.assertEqual(name,entry['name'],f'{entry["name"]} matched {name} at {distance}')

    def test_distinct_screens_keep_a_margin(self):
        distances=[SM.hamming(a['hash'],b['hash'])
                   for i,a in enumerate(self.entries) for b in self.entries[i+1:]]
        self.assertGreater(min(distances),24,'tolerance-12 regions must not overlap')

    def test_keys_are_mapped(self):
        self.assertEqual(SM.key_for('creators_app',MAP),'DELETE')
        self.assertEqual(SM.key_for('privacy_notice',MAP),'ENTER')
        self.assertIsNone(SM.key_for('system_error',MAP))
        for name in ('setup_area_editor','setup_date_format','setup_datetime_editor','creators_app_guide','touch_operation_guide'):
            self.assertEqual(SM.keys_for(name,MAP),['ENTER'])

    def test_unknown_frame_is_not_forced(self):
        with tempfile.TemporaryDirectory() as directory:
            blank=Path(directory)/'blank.png'
            Image.new('RGB',(320,240),'black').save(blank)
            name,_=SM.classify(blank,MAP)
            self.assertIsNone(name)

    def test_hamming_is_a_distance(self):
        self.assertEqual(SM.hamming('0'*16,'0'*16),0)
        self.assertEqual(SM.hamming('0'*16,'f'*16),64)


if __name__=='__main__':unittest.main()
