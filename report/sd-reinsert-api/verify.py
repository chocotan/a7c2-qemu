#!/usr/bin/env python3
"""Verify an explicit original Fsys storage diagnostic against an exported card."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys


def verify(run,runtime):
    sys.path.insert(0,str(runtime/'vendor/fwtool'))
    from fwtool.archive.fat import readFat
    raw=(run/'console.log').read_bytes()
    hits=re.findall(rb'FSYS_REINSERT_DIAG step=DONE rc=0 path=([A-Z]):/([A-F0-9]{8}\.BIN) bytes=4096 fnv1a64=([0-9a-f]{16})',raw)
    if len(hits)!=1:raise ValueError('Expected exactly one successful explicit diagnostic')
    drive,name,guest_fnv=hits[0];path='/'+name.decode()
    for step,rc in (('OpenWrite',0),('Write',4096),('Flush',0),('CloseWrite',0),('OpenRead',0),('Read',4096),('CloseRead',0)):
        tag=('FSYS_REINSERT_DIAG step='+step+' rc='+str(rc)+' path='+drive.decode()+':/'+name.decode()+' ').encode()
        if raw.count(tag)!=1:raise ValueError('Missing or ambiguous original operation '+step)
    card=run/'SD/card.img';export=json.loads((run/'SD/export.json').read_text())
    with card.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
    if sha!=export['sha256'] or not export['flush_lifecycle']['resumed']:raise ValueError('Card/export or owner resume differs')
    with card.open('rb') as stream:
        files={entry.path:entry.contents.read() for entry in readFat(stream) if stat.S_ISREG(entry.mode)}
    expected=bytearray((i*37+11)&255 for i in range(4096))
    label=b'A7C2 original Fsys reinsert storage diagnostic; not a photo or video\n';expected[:len(label)]=label
    if files.get(path)!=expected:raise ValueError('All original written/read bytes must match actual FAT file')
    value=14695981039346656037
    for byte in files[path]:value=((value^byte)*1099511628211)&((1<<64)-1)
    if f'{value:016x}'!=guest_fnv.decode():raise ValueError('Original diagnostic and exported content digest differs')
    fsck=subprocess.run(['fsck.fat','-n',str(card)],capture_output=True,text=True,check=True)
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    selected=manifest['selected_initramfs_verified_files']
    if not selected.get('simulation/fsys-reinsert-smoke.so'):raise ValueError('No selected diagnostic image binding')
    return {'original_fsys_api_reinsert_write_flush_close_readback_verified':True,
            'independent_exported_file_bytes_verified':True,'natural_camera_reinsert_write_verified':False,
            'capture_verified':False,'diagnostic_file':path,'bytes':4096,'file_fnv64':f'{value:016x}',
            'file_sha256':hashlib.sha256(files[path]).hexdigest(),'sd_sha256':sha,'independent_fsck_rc':fsck.returncode,
            'owner_resumed':True,'selected_diagnostic_sha256':selected['simulation/fsys-reinsert-smoke.so'],
            'left_behind':[path],'scope':'explicit same-process original API diagnostic, not photo/video'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    parser.add_argument('--runtime',type=Path,default=Path(__file__).resolve().parents[2]/'runtime/analysis')
    args=parser.parse_args()
    try:
        result=verify(args.run,args.runtime)
        (args.run/'sd-reinsert-api-review.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))
    except (OSError,ValueError,KeyError,subprocess.CalledProcessError) as error:parser.exit(1,str(error)+'\n')
