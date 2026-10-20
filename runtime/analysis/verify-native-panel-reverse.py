"""Verify virtual panel configuration, not physical flip scheduling or pixels."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def require(ok,why):
    if not ok:raise ValueError(why)


def verify(run):
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    summary=json.loads((run/'summary.json').read_text())
    console=(run/'console.log').read_bytes()
    require(manifest.get('panel_reverse_profile')=='virtual' and summary.get('probe_collected') is True,
            'Virtual panel profile/completed capture missing')
    require(Path(summary['run']).resolve()==run.resolve() and b'Entering exception monitor.' not in console,
            'Run identity or guest exception differs')
    rows=[(i,l,dict(re.findall(r'(\w+)=([^\s]+)',l))) for i,l in enumerate(console.decode(errors='replace').splitlines())]
    require(not any('OBS FULL_VDF_FAULT ' in r[1] for r in rows),'VDF ownership fault')
    def event(tag,after=-1):
        return next(r for r in rows if r[0]>after and r[1].startswith(tag))
    q=event('OBS FULL_VDF_REVERSE_REQUEST ')
    a=event('OBS FULL_VDF_REVERSE_REPLY_QUEUED ',q[0])
    c=event('OBS FULL_VDF_REVERSE_COMMIT ',a[0])
    f=next(r for r in rows if r[0]>c[0] and r[1].startswith('OBS FULL_VDF_NATIVE_REPLY_FREE ') and
           r[2].get('reply')==a[2]['reply'] and r[2].get('lease')==a[2]['lease'])
    require(q[2]['raw']=='0d2019011c0001800101000000000000000000000000000000000000',
            'Observed immediate HV request differs')
    require(a[2]['raw']=='0d2019110c00018000000000','1119 raw success must be zero without domain tag')
    require(q[2]['source']==a[2]['destination']==f[2]['destination']==f[2]['expected_destination'] and
            int(q[2]['destination'],0)==int(a[2]['source'],0)==0x92840747,'Dynamic panel route differs')
    require(q[2]['tid']==a[2]['tid']==c[2]['tid']==f[2]['tid']==f[2]['sender'] and f[2]['waiter']=='1',
            'Original panel waiter differs')
    require(a[2]['reply']==c[2]['reply'] and a[2]['lease']==c[2]['lease'] and
            c[2]['request_free_rc']==f[2]['rc']=='0' and f[2]['cmd']=='0x119','Panel lease/free differs')
    expected={'hrev':'1','vrev':'1','osdrev':'0','properties':'0,1,1,0','control':'3','control_readback':'3',
              'consumed':'1','applied':'1','timing':'0','owner':'virtual-panel-config',
              'hardware_driver_executed':'0','pixels_flipped':'0','camera_startup_verified':'0'}
    require(all(c[2].get(k)==v for k,v in expected.items()),'Virtual panel configuration readback/scope differs')
    return {'run':run.name,'virtual_panel_reverse_config_verified':True,'caller_tid':int(q[2]['tid']),
            'hrev':1,'vrev':1,'osdrev':0,'virtual_control':3,'raw_reply_status':0,
            'console_sha256':hashlib.sha256(console).hexdigest(),'original_device_phase_verified':False,
            'original_vfc_scheduling_verified':False,'hardware_driver_executed':False,'pixels_flipped':False,
            'camera_startup_verified':False,'pixels_consumed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError) as error:
        proof={'virtual_panel_reverse_config_verified':False,'error':str(error) or type(error).__name__,
               'camera_startup_verified':False,'pixels_flipped':False,'pixels_consumed':False}
    (args.run/'panel-reverse-native-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['virtual_panel_reverse_config_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
