#!/usr/bin/env python3
"""Summarise the IPSXWRP MMC access trace produced by QEMU_SONY_MMC_TRACE.

The trace device only records accesses and answers one constant value, so this
output is evidence about which offsets the original driver touches and in what
order. It is NOT evidence that a card works, and it does not replace the
disassembly-derived register contract.
"""
import argparse
import json
from pathlib import Path
import re
import sys

CREATED=re.compile(r'SONY_MMC_TRACE_CREATED phys=(0x[0-9a-f]+) bytes=(0x[0-9a-f]+) reset=(0x[0-9a-f]+)')
ACCESS=re.compile(r'SONY_MMC_TRACE_(READ|WRITE) base=(0x[0-9a-f]+) n=(\d+) '
                  r'off=(0x[0-9a-f]+) size=(\d+)(?: value=(0x[0-9a-f]+))?')
WINDOWS={0xf1388000:0x33000,0xf10d2000:0x2000,0xf10d4000:0x2000}


def parse(console):
    text=console.read_text(errors='replace')
    devices=[]
    for match in CREATED.finditer(text):
        devices.append({'phys':int(match.group(1),16),'bytes':int(match.group(2),16),
                        'reset':int(match.group(3),16)})
    accesses=[]
    for match in ACCESS.finditer(text):
        accesses.append({'event_index':len(accesses),'op':match.group(1).lower(),'base':int(match.group(2),16),
                         'n':int(match.group(3)),
                         'offset':int(match.group(4),16),'size':int(match.group(5)),
                         'value':int(match.group(6),16) if match.group(6) else None})
    if len(accesses)!=len(re.findall(r'SONY_MMC_TRACE_(?:READ|WRITE)\b',text)):
        raise ValueError('Unattributed legacy or malformed trace records; preserve the original console')
    return devices,accesses


def summarise(devices,accesses):
    errors=[]
    declared={d['phys']:d for d in devices}
    if len(declared)!=len(devices) or {b:d['bytes'] for b,d in declared.items()}!=WINDOWS:
        errors.append('Missing unique declarations for all three trace windows')
    if not accesses:errors.append('No attributed device access was recorded')
    counters={}
    per_offset={}
    for entry in accesses:
        base,offset,size=entry['base'],entry['offset'],entry['size']
        device=declared.get(base)
        if not device or size not in (1,2,4,8) or offset+size>device['bytes']:
            errors.append('Access is outside its declared device window')
        counter=(base,entry['op'])
        if entry['n']!=counters.get(counter,0)+1 or entry['n']>512:
            errors.append('Missing, duplicated or out-of-order per-device access counter')
        counters[counter]=entry['n']
        if entry['op']=='write' and entry['value'] is None:
            errors.append('Write record has no value')
        key=(entry['base'],entry['offset'],entry['size'],entry['op'])
        slot=per_offset.setdefault(key,{'base':entry['base'],'offset':entry['offset'],
                                        'size':entry['size'],
                                        'op':entry['op'],'count':0,'first_n':entry['n'],
                                        'first_event':entry['event_index'],
                                        'values':[]})
        slot['count']+=1
        if entry['value'] is not None and len(slot['values'])<8 and entry['value'] not in slot['values']:
            slot['values'].append(entry['value'])
    rows=sorted(per_offset.values(),key=lambda row:row['first_event'])
    return {'devices':devices,'total_accesses':len(accesses),
            'trace_capture_verified':not errors,'errors':list(dict.fromkeys(errors)),
            'record_limit_per_device_per_operation':512,
            'media_io_verified':False,'driver_identity_verified':False,
            'reads':sum(1 for e in accesses if e['op']=='read'),
            'writes':sum(1 for e in accesses if e['op']=='write'),
            'distinct_offsets':len({(e['base'],e['offset'],e['size']) for e in accesses}),
            'bases':sorted({e['base'] for e in accesses}),
            'by_first_access':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path,help='run directory containing console.log')
    parser.add_argument('--json',action='store_true',help='emit JSON instead of text')
    args=parser.parse_args()
    console=args.run/'console.log'
    if not console.is_file():
        print(f'no console.log in {args.run}',file=sys.stderr);return 2
    try:devices,accesses=parse(console)
    except ValueError as error:
        if args.json:print(json.dumps({'trace_capture_verified':False,'errors':[str(error)],'media_io_verified':False}))
        else:print(str(error),file=sys.stderr)
        return 1
    summary=summarise(devices,accesses)
    if args.json:
        print(json.dumps(summary,indent=2));return 0 if summary['trace_capture_verified'] else 1
    if not devices:
        print('No SONY_MMC_TRACE_CREATED: the MMC overlay was not enabled for this run.')
        return 1
    for device in devices:
        print(f"device phys=0x{device['phys']:08x} bytes=0x{device['bytes']:x} reset=0x{device['reset']:08x}")
    print(f"accesses: {summary['total_accesses']} "
          f"(read={summary['reads']} write={summary['writes']}, "
          f"distinct offset/size={summary['distinct_offsets']})")
    print()
    print(f"{'first':>6} {'base':>12} {'off':>8} {'sz':>3} {'op':<5} {'cnt':>5}  values")
    for row in summary['by_first_access']:
        values=','.join(f'0x{v:x}' for v in row['values']) or '-'
        print(f"{row['first_n']:>6} 0x{row['base']:08x} 0x{row['offset']:05x} {row['size']:>3} "
              f"{row['op']:<5} {row['count']:>5}  {values}")
    for error in summary['errors']:print('REJECT: '+error,file=sys.stderr)
    return 0 if summary['trace_capture_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
