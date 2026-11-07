#!/usr/bin/env python3
"""Parse the read-only HDMI Backup probe; record guest values, assert nothing.

Guest Backup content is allowed to differ from the offline dump. This verifier
therefore binds identity and completeness only: original program/library,
per-key size before/after agreement, and full-length original reads.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

KEYS=(0x010d008d,0x003e0005,0x009a0001,0x010704fd,0x009a0009,0x009a000a,0x009a000b,0x009a000c)
SHAPES={0x010d008d:(1,1),0x003e0005:(1,16),0x009a0001:(1,'small'),0x010704fd:(1,1),
        0x009a0009:(0,1),0x009a000a:(0,1),0x009a000b:(0,1),0x009a000c:(0,4)}
LINE=re.compile(r'^HDMI_BACKUP_PROBE_KEY key=0x([0-9a-f]+) size_before=0x([0-9a-f]+) '
                r'original_nread=0x([0-9a-f]+) size_after=0x([0-9a-f]+) complete=(\d+) fnv64=([0-9a-f]{16})$')


def verify(run):
    log=(run/'hdmi-backup-probe.log').read_bytes()
    identity=json.loads((run/'inputs.json').read_text())
    rows=[]
    for raw in log.decode(errors='replace').splitlines():
        match=LINE.match(raw.strip())
        if not match:continue
        key,before,rc,after,complete,fnv=(int(match[1],16),int(match[2],16),int(match[3],16),
                                          int(match[4],16),int(match[5]),match[6])
        rows.append({'key':key,'size_before':before,'original_nread':rc,'size_after':after,
                     'complete':bool(complete),'fnv64':fnv})
    if [row['key'] for row in rows]!=list(KEYS):
        raise ValueError('Probe key set/order differs from the declared read-only list')
    done=re.search(rb'HDMI_BACKUP_PROBE_DONE keys=8 readable=(\d+) original_cp_task=0 '
                   rb'camera_startup_verified=0',log)
    if not done:raise ValueError('Probe completion marker missing')
    if identity['experiment'].get('probe_hdmi_backup') is not True:
        raise ValueError('Probe was not explicitly enabled in this run')
    for row in rows:
        if row['complete']:
            if row['original_nread']!=row['size_before'] or row['size_after']!=row['size_before']:
                raise ValueError('Completed read is not full-length and stable: '+hex(row['key']))
        elif row['original_nread'] not in (0xffffffff,0) and row['original_nread']<row['size_before']:
            raise ValueError('Positive short read was not rejected: '+hex(row['key']))
    readable=sum(row['complete'] for row in rows)
    if readable!=int(done[1]):raise ValueError('Readable count disagrees with per-key rows')
    profile={}
    for row in rows:
        optional,expected=SHAPES[row['key']]
        if row['complete'] and expected!='small' and row['size_before']!=expected:
            raise ValueError('Key size differs from the documented original shape: '+hex(row['key']))
        if row['complete'] and expected=='small' and row['size_before']>256:
            raise ValueError('Optional small key exceeds its bounded buffer')
        profile[hex(row['key'])]={'complete':row['complete'],'size':row['size_before'],
                                  'fnv64':row['fnv64'] if row['complete'] else None,
                                  'required_for_cold_exit':optional==0}
    required_missing=[hex(k) for k in (0x009a0009,0x009a000a,0x009a000b,0x009a000c)
                      if not profile[hex(k)]['complete']]
    return {'hdmi_backup_probe_completed':True,'readable_keys':readable,'keys':profile,
            'required_missing':required_missing,
            'cold_exit_settings_available':not required_missing,
            'guest_values_recorded_privately':True,
            'offline_dump_equality_adopted':False,
            'original_cp_task_running':False,'fourth_connection_verified':False,
            'camera_startup_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,TypeError) as error:
        proof={'hdmi_backup_probe_completed':False,'error':str(error),'camera_startup_verified':False}
    (args.run/'hdmi-backup-probe-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['hdmi_backup_probe_completed'] else 1


if __name__=='__main__':raise SystemExit(main())
