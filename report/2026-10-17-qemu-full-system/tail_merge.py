#!/usr/bin/env python3
"""Offline merge of one receiver epoch. No claim is inferred from a missing tap."""
import hashlib
import re
LIMITS=(12,16,32,40,64,40,24,28)
FAMILIES=('identity','signature','format','backend_open_getinfo_stat','writer_flush_readback','plugin','endupdate_power','failure_saturation')

def merge(raw,receiver_pid,ledger=None):
    if not isinstance(raw,bytes) or not isinstance(receiver_pid,int) or receiver_pid<=0:raise ValueError('Expected bytes and exact receiver PID')
    start=f'UPDATE_SD_RECEIVER_START pid={receiver_pid} original=/usr/bin/sdfileinput.elf'.encode()
    if sum(l.rstrip(b'\r\n')==start for l in raw.splitlines(keepends=True))!=1:raise ValueError('Need exactly one original receiver start')
    records=[];used=[0]*8;total=0;offset=0;original=[];start_seen=False;ended=False
    for line in raw.splitlines(keepends=True):
        text=line.decode('ascii','backslashreplace').rstrip('\r\n');loc={'offset':offset,'sha256':hashlib.sha256(line).hexdigest()};offset+=len(line)
        if line.rstrip(b'\r\n')==start:start_seen=True
        if not start_seen:continue
        if text.startswith('P1_TAIL '):
            m=re.match(r'^P1_TAIL pid=(\d+) family=(\d+) op=([^ ]+) (.*) rc=(-?\d+) errno=(-?\d+) caller=(\S+)$',text)
            if not m:raise ValueError('Malformed tail record')
            pid,family=int(m[1]),int(m[2])
            if pid!=receiver_pid:raise ValueError('Tail record crosses receiver epoch')
            if ended or len(line)>1024 or family>=8:raise ValueError('Tail record out of bounds')
            used[family]+=1;total+=len(line)
            if used[family]>LIMITS[family] or sum(used)>256 or total>262144:raise ValueError('Tail family/byte budget exceeded')
            records.append(dict(loc,family=FAMILIES[family],op=m[3],data=m[4],rc=int(m[5]),errno=int(m[6]),caller=m[7]))
        elif text.startswith(('P1_TRUST_KEY ','P1_SD_NATIVE ','P1_SD_EXCEPTION ','P1_DECRYPT_PASSIVE ','P1_CBC_MODEL ','P1_PMBP ')):
            original.append(dict(loc,text=text))
        elif text.startswith(f'UPDATE_SD_RECEIVER_EXIT pid={receiver_pid} '):
            original.append(dict(loc,text=text));ended=True
        elif any(x in text for x in ('[UD_COM_PIC]','Darwin firmup','Darwin update','UdrAPI,99,Plugin.cpp','End unpacking','MediaUpdateCompleteFlag','User Update OK','ud_pd_firmup','ud_reboot')):
            original.append(dict(loc,text=text))
    receipts=[r for r in records if r['op']=='receipt']
    if len(receipts)>1:raise ValueError('Duplicate epoch receipt')
    # Ledger is opaque data from the existing independent postrun verifier, never manufactured here.
    return dict(schema='p1-tail-merge-v1',receiver_pid=receiver_pid,serial_sha256=hashlib.sha256(raw).hexdigest(),
        family_records=dict(zip(FAMILIES,used)),tail_bytes=total,records=records,original=original,
        receipt_present=bool(receipts),saturated=any(r['op']=='saturation' for r in records),
        postrun_ledger=ledger,installation_verified=False,rsa_dynamic_verified=False,format_actual_verified=False,
        power_hardware_receipt_verified=False)
