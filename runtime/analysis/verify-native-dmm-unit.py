"""Check original config-backed unit capacity reply and AP property readback."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

CONFIG_SHA='d3466cee62fd86d927236a2c6c37dd633f76cdc181b4ad07a9863696aab76660'


def require(ok,why):
    if not ok:raise ValueError(why)


def verify(run):
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    summary=json.loads((run/'summary.json').read_text())
    console=(run/'console.log').read_bytes();text=console.decode(errors='replace')
    require(manifest.get('dmm_unit_config_service') is True and summary.get('probe_collected') is True and
            manifest['selected_initramfs_verified_files'].get('cp/DmmCfg.bin')==CONFIG_SHA,
            'Original config profile/selected image identity/completed capture missing')
    require(Path(summary['run']).resolve()==run.resolve() and 'Entering exception monitor.' not in text,
            'Run identity or terminal exception differs')
    rows=[(i,l,dict(re.findall(r'(\w+)=([^\s]+)',l))) for i,l in enumerate(text.splitlines())]
    require(not any('OBS FULL_DMM_UNIT_FAULT ' in r[1] for r in rows),'Unit reply ownership fault')
    def event(kind,after=-1):
        return next(r for r in rows if r[0]>after and r[1].startswith('OBS FULL_DMM_UNIT_'+kind+' '))
    q=event('REQUEST');a=event('REPLY_QUEUED',q[0]);c=event('COMMIT',a[0]);f=event('NATIVE_REPLY_FREE',c[0])
    raw=bytes.fromhex(q[2]['raw']);reply=bytes.fromhex(a[2]['raw'])
    expected=struct.pack('<HHI',0x18,0,0x50b58)+bytes(32)
    require(raw==expected and len(reply)==40 and struct.unpack_from('<HHHH',reply)==(0x8018,0,0,0) and
            struct.unpack_from('<I',reply,16)[0]==0x9600000 and not any(reply[8:16]+reply[20:]),
            'Original unit request/reply fields differ')
    require(int(q[2]['destination'],0)==int(a[2]['source'],0)==0x9061003c and
            q[2]['source']==a[2]['destination']==f[2]['destination']==f[2]['expected'],'Unit dynamic route differs')
    require(q[2]['tid']==a[2]['tid']==c[2]['tid']==f[2]['tid']==f[2]['sender'] and f[2]['waiter']=='1' and
            a[2]['reply']==c[2]['reply']==f[2]['reply'] and a[2]['lease']==c[2]['lease']==f[2]['lease'] and
            c[2]['request_free_rc']==f[2]['rc']=='0','Original unit caller/lease/free differs')
    require(int(c[2]['unit'],0)==0x50b58 and int(c[2]['extent'],0)==0xf0 and int(c[2]['size'],0)==0x9600000 and
            c[2]['config_fnv64']=='b17ed6044f6bf2de' and c[2]['allocated_bytes']=='0', 'Config table lookup scope differs')
    block=re.search(r'^MAIN_IMAGE_UNIT_SIZE_BEGIN\r?\n(.*?)^MAIN_IMAGE_UNIT_SIZE_RC=(\d+)\r?$',text,re.M|re.S)
    require(block and block[2]=='0','Original AP property readback missing')
    values=re.findall(r'^[0-9a-f]{16}:((?: [0-9a-f]{2}){4})\r?$',block[1],re.M)
    require(len(values)==1 and bytes.fromhex(values[0])==struct.pack('<I',0x9600000),'Original AP main_image_unit_size differs')
    return {'run':run.name,'config_backed_unit_size_verified':True,'unit':'0x50b58','extent':'0xf0','size':0x9600000,
            'caller_tid':int(q[2]['tid']),'original_ap_property_readback_verified':True,'property':'main_image_unit_size',
            'property_elf_va':'0x7ecfbf0','original_model_publish_callback_verified':False,
            'config_sha256':CONFIG_SHA,'console_sha256':hashlib.sha256(console).hexdigest(),'allocated_bytes':0,
            'camera_startup_verified':False,'pixels_consumed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError) as error:
        proof={'config_backed_unit_size_verified':False,'error':str(error) or type(error).__name__,
               'camera_startup_verified':False,'pixels_consumed':False,'allocated_bytes':0}
    (args.run/'dmm-unit-size-native-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['config_backed_unit_size_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
