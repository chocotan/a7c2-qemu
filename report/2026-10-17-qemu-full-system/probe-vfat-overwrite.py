#!/usr/bin/env python3
"""Prove a VFAT overwrite reaches the guest, not just the host image.

The VFAT backend is already tested against public factory volumes on the host,
but that only shows the image was written correctly. This probe places two new
files on VFAT-backed partitions (/system and /cp), lets the ORIGINAL firmware
read them back through its own shell and OpenSSL, and compares the guest's
digest with the digest of the bytes we wrote. A host-side match without a guest
readback is not acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import shlex
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent

# guest path -> overwrite-relative source path
PROBES={
    '/system/vfat-system-probe.txt':'system/vfat-system-probe.txt',
    '/cp/vfat-cp-probe.txt':'cp/vfat-cp-probe.txt',
}


def contents(guest_path):
    return (f'VFAT overwrite readback probe for {guest_path}\n'
            f'written by probe-vfat-overwrite.py; no device data.\n').encode()


def readback_command(guest,nonce):
    if ';' in guest or any(ord(c)<32 or ord(c)==127 for c in guest):
        raise ValueError('Unsupported command separator/control character in guest path')
    return '\n'.join([f'echo OVERWRITE_BEGIN_{nonce}',
        '/usr/bin/openssl dgst -sha256 '+shlex.quote(guest),
        'rc=$?',f'echo OVERWRITE_RC_{nonce}=$rc',f'echo OVERWRITE_END_{nonce}'])


def guest_digest(console,guest,expected,nonce=None):
    """Return the single guest-reported digest, or raise.

    A missing, duplicated or conflicting report is a failed readback; the probe
    must never fall back to the host-side digest.
    """
    if nonce:
        blocks=re.findall(rf'(?m)^OVERWRITE_BEGIN_{nonce}\r?$\n(.*?)^OVERWRITE_END_{nonce}\r?$',console,re.S|re.M)
        if not blocks:raise ValueError('missing complete guest readback for '+guest)
        for block in blocks:
            statuses=re.findall(rf'^OVERWRITE_RC_{nonce}=(\d+)\r?$',block,re.M)
            if statuses!=['0']:raise ValueError('guest digest command failed for '+guest)
        console='\n'.join(blocks)
    found=re.findall(re.escape(guest)+r'\)=\s*([0-9a-f]{64})',console)
    if not found:raise ValueError('guest never reported a digest for '+guest)
    if len(set(found))!=1:raise ValueError('guest reported conflicting digests for '+guest)
    if found[0]!=expected:raise ValueError('guest digest differs from the written bytes for '+guest)
    return found[0]


def image_manifest_errors(expected,manifest):
    recorded={};errors=[]
    for entry in manifest.get('user_overwrite',{}).get('files',[]):
        if entry['path'] in recorded:raise ValueError('duplicate image manifest file path')
        recorded[entry['path']]=entry['sha256']
    for guest,info in expected.items():
        if recorded.get(guest)!=info['sha256']:
            errors.append({'guest_path':guest,'error':'missing or mismatched SHA256 in image manifest'})
    return recorded,errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--all-files',action='store_true',
                        help='read back all regular files in existing overwrite/ without adding probe files')
    args=parser.parse_args()
    workspace=args.workspace.resolve();workspace.mkdir(parents=True,exist_ok=True)
    overwrite=workspace/'overwrite'
    expected={}
    metadata=[]
    if args.all_files:
        scan=runpy.run_path(str(HERE/'overwrite-images.py'))['scan_overlay']
        with tempfile.TemporaryDirectory(prefix='overwrite-audit-') as temporary:
            for entry in scan(overwrite,Path(temporary)):
                if entry['kind']=='file':
                    expected[entry['guest_path']]={'sha256':entry['sha256'],'bytes':entry['size'],
                                                  'source':'overwrite/'+entry['source']}
                else:metadata.append({'path':entry['guest_path'],'kind':entry['kind']})
        if not expected:raise ValueError('No regular files in overwrite/ to verify')
    else:
        if any(os.path.lexists(overwrite/relative) for relative in PROBES.values()):
            raise ValueError('Probe files already exist; use a fresh workspace or --all-files')
        secure_open=runpy.run_path(str(HERE/'fat_image.py'))['secure_open']
        for guest,relative in PROBES.items():
            target=overwrite/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            data=contents(guest)
            parent_fd=secure_open(target.parent,directory=True)
            try:
                fd=os.open(target.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent_fd)
                with os.fdopen(fd,'wb') as output:output.write(data)
            finally:os.close(parent_fd)
            expected[guest]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),
                             'source':str(target.relative_to(workspace))}
    nonces={guest:secrets.token_hex(12) for guest in expected}
    if 25+10*(len(expected)-1)+15>args.seconds:
        raise ValueError('Increase --seconds to fit every overwrite file readback')
    plan=';'.join(f'{25+10*index}:'+readback_command(guest,nonces[guest])
                  for index,guest in enumerate(expected))
    process=subprocess.run([sys.executable,'-B',str(HERE/'start-official-camera.py'),
                            '--workspace',str(workspace),'--headless','--seconds',str(args.seconds),
                            '--key-plan',plan],capture_output=True,text=True)
    (workspace/'probe-runner.log').write_text(process.stdout+process.stderr)
    if process.returncode:
        print(process.stdout[-2000:],file=sys.stderr);print(process.stderr[-2000:],file=sys.stderr)
        raise SystemExit('official entry failed; keep '+str(workspace/'probe-runner.log'))
    runtime=re.search(r'^OFFICIAL_CAMERA_RUNTIME (.+)$',process.stdout,re.M)
    run=re.search(r'^FULLSYSTEM_RUN (.+)$',process.stdout,re.M)
    if not runtime or not run:raise SystemExit('missing runtime/run banner')
    runtime=Path(runtime.group(1)).resolve();run=Path(run.group(1)).resolve()
    if not runtime.is_relative_to(workspace/'.a7c2/sessions') or run.parent!=runtime/'analysis/runs':
        raise ValueError('foreign runtime/run path')
    console=(run/'console.log').read_text(errors='replace')
    result={'schema':'vfat-overwrite-readback-v1','run':str(run),'workspace':str(workspace),
            'console_sha256':hashlib.sha256((run/'console.log').read_bytes()).hexdigest(),
            'probes':{},'errors':[],'scope':'all regular overwrite files' if args.all_files else 'fixed VFAT samples',
            'metadata_not_guest_verified':metadata}
    for guest,info in expected.items():
        try:
            digest=guest_digest(console,guest,info['sha256'],nonces[guest])
            result['probes'][guest]={**info,'guest_sha256':digest,'verified':True}
        except ValueError as error:
            result['errors'].append({'guest_path':guest,'error':str(error)})
    # The image side must also record the operation; otherwise the guest could
    # be reading a leftover file from an earlier image.
    modified=runtime.parent/'modified-images'
    manifest=modified/'manifest.json'
    if manifest.is_file():
        recorded,errors=image_manifest_errors(expected,json.loads(manifest.read_text()))
        result['image_operations']=sorted(recorded)
        result['errors'].extend(errors)
    else:
        result['errors'].append({'guest_path':'-','error':'modified image manifest missing'})
    out=run/'vfat-overwrite-proof.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('VFAT_OVERWRITE_PROOF '+str(out))
    for guest,entry in result['probes'].items():
        print(f"  {guest}: guest_sha256={entry['guest_sha256'][:16]} verified={entry['verified']}")
    return 0 if not result['errors'] and len(result['probes'])==len(expected) else 1


if __name__=='__main__':raise SystemExit(main())
