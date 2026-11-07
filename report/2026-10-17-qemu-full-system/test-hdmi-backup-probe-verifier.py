#!/usr/bin/env python3
import json
from pathlib import Path
import runpy
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-hdmi-backup-probe.py'))['verify']
FULL=[(0x010d008d,1,1,1,1),(0x003e0005,16,16,16,1),(0x009a0001,10,10,10,1),
      (0x010704fd,1,1,1,1),(0x009a0009,1,1,1,1),(0x009a000a,1,1,1,1),
      (0x009a000b,1,1,1,1),(0x009a000c,4,4,4,1)]


def make(run,rows,enabled=True,readable=None,marker=True):
    text=''.join('HDMI_BACKUP_PROBE_KEY key=0x%08x size_before=0x%x original_nread=0x%x '
                 'size_after=0x%x complete=%d fnv64=%s\n'
                 %(k,b,r,a,c,'0123456789abcdef' if c else '0'*16) for k,b,r,a,c in rows)
    if marker:
        n=readable if readable is not None else sum(x[4] for x in rows)
        text+='HDMI_BACKUP_PROBE_DONE keys=8 readable=%d original_cp_task=0 camera_startup_verified=0\n'%n
    (run/'hdmi-backup-probe.log').write_text(text)
    (run/'inputs.json').write_text(json.dumps({'experiment':{'probe_hdmi_backup':enabled}}))


class Probe(unittest.TestCase):
    def test_all_keys_and_missing_required_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);make(run,FULL)
            proof=VERIFY(run)
            self.assertEqual(proof['readable_keys'],8)
            self.assertTrue(proof['cold_exit_settings_available'])
            self.assertEqual(proof['required_missing'],[])
            # Missing required configuration must be reported, never invented.
            rows=list(FULL);rows[5]=(0x009a000a,1,0xffffffff,1,0)
            make(run,rows)
            proof=VERIFY(run)
            self.assertFalse(proof['cold_exit_settings_available'])
            self.assertEqual(proof['required_missing'],['0x9a000a'])
            self.assertFalse(proof['offline_dump_equality_adopted'])

    def test_optional_key_unavailable_does_not_block(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);rows=list(FULL);rows[0]=(0x010d008d,0,0xffffffff,0,0)
            make(run,rows);proof=VERIFY(run)
            self.assertTrue(proof['cold_exit_settings_available'])
            self.assertFalse(proof['keys']['0x10d008d']['complete'])

    def test_rejects_unstable_short_order_marker_and_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d)
            rows=list(FULL);rows[1]=(0x003e0005,16,16,15,1);make(run,rows)
            with self.assertRaises(ValueError):VERIFY(run)
            rows=list(FULL);rows[1]=(0x003e0005,16,8,16,1);make(run,rows)
            with self.assertRaises(ValueError):VERIFY(run)
            make(run,list(reversed(FULL)))
            with self.assertRaises(ValueError):VERIFY(run)
            make(run,FULL,marker=False)
            with self.assertRaises(ValueError):VERIFY(run)
            make(run,FULL,enabled=False)
            with self.assertRaises(ValueError):VERIFY(run)
            make(run,FULL,readable=7)
            with self.assertRaises(ValueError):VERIFY(run)
            rows=list(FULL);rows[2]=(0x009a0001,300,300,300,1);make(run,rows)
            with self.assertRaises(ValueError):VERIFY(run)


if __name__=='__main__':unittest.main()
