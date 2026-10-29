#!/usr/bin/env python3
"""Read-only check of the two actual firmware-script execution runs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

OLD='845f5d3c5d6827e9719321d0898e8199aeae4f6979922f1da8b45d0b8c1e0ff8'
NEW='f42a90d3ebc1578aefbb30e6473d9bb7a85f051bf0504ee162e1960db1bc38c2'


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def require(condition,message):
    if not condition:raise ValueError(message)


def phase(run,patched):
    expected=NEW if patched else OLD
    rc=7 if patched else 1
    serial=(run/'overwrite-execution-serial.txt').read_bytes()
    hashes=re.findall(rb'^[A-Za-z0-9-]+\(/usr/bin/get_finger_print.sh\)= ([0-9a-f]{64})\r?$',serial,re.M)
    exits=re.findall(rb'^OVERWRITE_EXEC_RC=([0-9]+)\r?$',serial,re.M)
    no_key=re.findall(rb'^OVERWRITE_NO_KEY=([0-9]+)\r?$',serial,re.M)
    require(hashes==[expected.encode()] and exits==[str(rc).encode()] and no_key==[b'0'],
            'Missing or contradictory original serial execution evidence')
    evidence=json.loads((run/'overwrite-execution.json').read_text())
    require(evidence['ok'] is True and evidence['phase']==('patched' if patched else 'rollback')
            and evidence['actual_rc']==[rc] and evidence['guest_sha256']==[expected]
            and evidence['capture_verified'] is False,'Execution JSON differs from original serial')
    manifest_path=run/'overwrite-manifest.json'
    base=None
    if patched:
        manifest=json.loads(manifest_path.read_text());entries=manifest['entries']
        require(len(entries)==1 and entries[0]['path']=='usr/bin/get_finger_print.sh'
                and entries[0]['old_sha256']==OLD and entries[0]['new_sha256']==NEW,
                'Overlay manifest does not describe the one intended replacement')
        base=manifest['base_cpio_sha256']
    else:
        require(not manifest_path.exists(),'Rollback still has an overlay manifest')
    export=json.loads((run/'SD/export.json').read_text())
    card=run/'SD/card.img'
    require(export['ok'] is True and export['fsck_rc']==0
            and export['quiesce']['original_Fsys_FlushVolume_rc']==0
            and export['flush_lifecycle']['resumed'] is True,'SD flush/resume evidence failed')
    require(sha(card)==export['sha256'],'Actual SD differs from export')
    checked=subprocess.run(['fsck.fat','-n',str(card)],capture_output=True,text=True)
    require(checked.returncode==0,'Independent fsck rejected SD')
    return {'phase':evidence['phase'],'guest_sha256':expected,'actual_rc':rc,
            'base_cpio_sha256':base,'sd_sha256':export['sha256'],'independent_fsck_rc':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--patched',type=Path,required=True)
    parser.add_argument('--rollback',type=Path,required=True)
    parser.add_argument('--base-cpio',type=Path,required=True)
    parser.add_argument('--original-script',type=Path,required=True)
    args=parser.parse_args()
    try:
        patched=phase(args.patched,True);rollback=phase(args.rollback,False)
        require(args.patched.resolve()!=args.rollback.resolve(),'Two separate boots required')
        require(sha(args.base_cpio)==patched['base_cpio_sha256'],'Current base changed')
        require(sha(args.original_script)==OLD,'Original host script changed')
        print(json.dumps({'ok':True,'scope':'one original utility patch and clean-boot rollback',
                          'phases':[patched,rollback],'base_unchanged':True,
                          'capture_verified':False,'arbitrary_binary_compatibility_verified':False},indent=2))
    except (OSError,ValueError,KeyError,TypeError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
