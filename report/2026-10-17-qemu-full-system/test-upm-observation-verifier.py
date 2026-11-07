#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-upm-observation.py'))['verify']
FRAME=runpy.run_path(str(HERE/'test-upm-message-probe.py'))['frame']
PROBE=runpy.run_path(str(HERE/'upm-message-probe.py'))


class Acceptance(unittest.TestCase):
    def make(self,run):
        records=[FRAME(0),FRAME(2)]
        for r in records:r['ng_before']=[];r['ng_after']=[];r['effect_verified']=True
        console=b''
        for selector,r in zip((0,2),records):
            console+=f"UPM_DIAG_SEND selector={selector} destination=0x80920572 source=0x12345678 pointer=0x8000 raw={r['received_raw']} original_cp_task=0\n".encode()
            console+=f'UPM_DIAG_SEND_RETURN selector={selector} rc=0 cleanup=0 ownership_transferred=1\n'.encode()
        console+=b'UPM_DIAG_PRODUCER_RC=0\n'
        (run/'console.log').write_bytes(console)
        (run/'result.json').write_text(json.dumps(dict(state='observation-completed',terminal_evidence_checked=True,
            terminal_console_sha256=hashlib.sha256(console).hexdigest(),upm_diagnostic_only=True,
            upm_original_receive_process_free_verified=True)))
        (run/'inputs.json').write_text(json.dumps(dict(experiment={'observe_upm_notify':True},
            upm_observer_module_sha256=PROBE['UPM_SHA'],adapter_sources={n:hashlib.sha256((HERE/n).read_bytes()).hexdigest()
            for n in ('upm-message-probe.py','upm-notify-check.c','guest/upm-notify-observe.sh','boot-fatal-probe.py')})))
        (run/'upm-message-observation.json').write_text(json.dumps(dict(module_sha256=PROBE['UPM_SHA'],records=records,
            in_flight=None,two_notifications_consumed=True,original_cp_task_running=False,
            fourth_connection_verified=False,camera_startup_verified=False)))

    def test_complete_and_partial_or_altered_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.make(run)
            proof=VERIFY(run)
            self.assertTrue(proof['upm_original_receive_process_free_verified'])
            self.assertTrue(proof['native_message_reference_release_verified'])
            self.assertFalse(proof['native_message_final_backing_retirement_verified'])
            for key,value in [('in_flight',{}),('records',[]),('camera_startup_verified',True),('module_sha256','bad')]:
                self.make(run);p=run/'upm-message-observation.json';j=json.loads(p.read_text());j[key]=value;p.write_text(json.dumps(j))
                with self.subTest(key=key),self.assertRaises(ValueError):VERIFY(run)
            self.make(run);p=run/'upm-message-observation.json';j=json.loads(p.read_text());j['records'][0]['free_rc']=-1;p.write_text(json.dumps(j))
            with self.assertRaises(ValueError):VERIFY(run)
            self.make(run);p=run/'console.log';p.write_bytes(p.read_bytes()+b'late bytes\n')
            with self.assertRaises(ValueError):VERIFY(run)


if __name__=='__main__':unittest.main()
