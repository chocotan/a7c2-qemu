#!/usr/bin/env python3
"""Verify the isolated diagnostic's original-kernel UPM receive/use/free."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent


def verify(run):
    module=runpy.run_path(str(HERE/'upm-message-probe.py'))
    inputs=json.loads((run/'inputs.json').read_text());result=json.loads((run/'result.json').read_text())
    observed=json.loads((run/'upm-message-observation.json').read_text());console=(run/'console.log').read_bytes()
    sha=hashlib.sha256(console).hexdigest()
    if result.get('state')!='observation-completed' or result.get('terminal_evidence_checked') is not True or \
            result.get('terminal_console_sha256')!=sha:
        raise ValueError('UPM diagnostic lacks completed/stable whole-run evidence')
    if inputs['experiment'].get('observe_upm_notify') is not True or result.get('upm_diagnostic_only') is not True:
        raise ValueError('UPM diagnostic explicit opt-in missing')
    if result.get('upm_original_receive_process_free_verified') is not True:
        raise ValueError('UPM original consumer/free was not verified by the observer')
    for name in ('upm-message-probe.py','upm-notify-check.c','guest/upm-notify-observe.sh','boot-fatal-probe.py'):
        if inputs['adapter_sources'].get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
            raise ValueError('UPM diagnostic source differs from captured input: '+name)
    if observed.get('module_sha256')!=module['UPM_SHA'] or inputs.get('upm_observer_module_sha256')!=module['UPM_SHA']:
        raise ValueError('UPM original module identity differs')
    records=observed.get('records',[])
    if len(records)!=2 or observed.get('in_flight') is not None or observed.get('two_notifications_consumed') is not True:
        raise ValueError('UPM two-message lifecycle incomplete')
    if any(r.get('effect_verified') is not True or not module['verified_effect'](r) for r in records):
        raise ValueError('UPM receive/API/NG/free raw content validation failed')
    for record in records:
        if not isinstance(record.get('message_refs_before_free'),int) or not 1<=record['message_refs_before_free']<=0xffff:
            raise ValueError('UPM original message reference count before free missing or invalid')
        for key in ('receive_frame','process_frame','free_frame','received_pointer','processed_pointer','freed_pointer'):
            address=int(record[key],16)
            if not 0xffffff8000000000<=address<=0xfffffffffffffff0 or address%8:
                raise ValueError('UPM recorded frame/message address is outside aligned kernel memory')
    received=[int.from_bytes(bytes.fromhex(r['received_raw'])[4:8],'little') for r in records]
    if received!=[0,2]:raise ValueError('UPM original message selectors differ')
    sends=re.findall(rb'(?:^|\n)UPM_DIAG_SEND selector=(\d+) destination=0x80920572 source=(0x[0-9a-f]+) pointer=(0x[0-9a-f]+) raw=([0-9a-f]{32}) original_cp_task=0\r?(?:\n|$)',console)
    if len(sends)!=2 or [int(s[0]) for s in sends]!=[0,2] or \
            [s[3].decode() for s in sends]!=[r['received_raw'] for r in records]:
        raise ValueError('UPM diagnostic producer raw data differs from original kernel receive')
    returns=re.findall(rb'(?:^|\n)UPM_DIAG_SEND_RETURN selector=(\d+) rc=0 cleanup=0 ownership_transferred=1\r?(?:\n|$)',console)
    if returns!=[b'0',b'2'] or re.findall(rb'(?:^|\n)UPM_DIAG_PRODUCER_RC=(\d+)\r?(?:\n|$)',console)!=[b'0']:
        raise ValueError('UPM diagnostic producer ownership/exit evidence incomplete')
    if any(observed.get(name) is not False for name in ('original_cp_task_running','fourth_connection_verified','camera_startup_verified')):
        raise ValueError('UPM diagnostic scope flags unexpectedly claim camera/CP success')
    return {'upm_original_receive_process_free_verified':True,'console_sha256':sha,
            'native_message_reference_release_verified':True,
            'native_message_final_backing_retirement_verified':False,
            'native_message_references_before_free':[r['message_refs_before_free'] for r in records],
            'original_module_sha256':module['UPM_SHA'],'received_selectors':received,
            'processed_selectors':[int.from_bytes(bytes.fromhex(r['processed_raw'])[4:8],'little') for r in records],
            'ng_rows_before':[len(r['ng_before']) for r in records],
            'ng_rows_after':[len(r['ng_after']) for r in records],
            'diagnostic_producer':True,'qemu_breakpoints_used':True,
            'original_cp_task_running':False,'fourth_connection_verified':False,'camera_startup_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,TypeError) as error:
        proof={'upm_original_receive_process_free_verified':False,'error':str(error),
               'native_message_reference_release_verified':False,
               'native_message_final_backing_retirement_verified':False,
               'fourth_connection_verified':False,'camera_startup_verified':False}
    (args.run/'upm-original-consumer-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['upm_original_receive_process_free_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
