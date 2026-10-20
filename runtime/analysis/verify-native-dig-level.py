"""Verify consumed virtual selector3 subscription, never an angle sample."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def require(ok,reason):
    if not ok:raise ValueError(reason)


def verify(run):
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    summary=json.loads((run/'summary.json').read_text())
    console=(run/'console.log').read_bytes()
    require(manifest.get('digital_level_profile')=='virtual' and summary.get('probe_collected') is True,
            'Explicit virtual notification profile/completed observation missing')
    require(Path(summary['run']).resolve()==run.resolve() and b'Entering exception monitor.' not in console,
            'Run identity/terminal exception differs')
    lines=console.decode(errors='replace').splitlines()
    require(not any('OBS FULL_DIG_LEVEL_FAULT ' in l for l in lines),'Digital Level ownership fault')
    rows=[(i,l,dict(re.findall(r'(\w+)=([^\s]+)',l))) for i,l in enumerate(lines)]
    def event(kind,after=-1):
        return next(r for r in rows if r[0]>after and r[1].startswith('OBS FULL_DIG_LEVEL_'+kind+' '))
    a=event('REQUEST');c=event('CONTROL_CONSUMED',a[0]);q=event('REPLY_QUEUED',c[0]);m=event('COMMIT',q[0]);f=event('NATIVE_REPLY_FREE',m[0])
    expected=bytes.fromhex('030000000000000000000000000000000000000000000000')
    require(bytes.fromhex(a[2]['raw'])==bytes.fromhex(q[2]['raw'])==expected,'Selector3 request/reply differs')
    require(int(a[2]['destination'],0)==int(q[2]['source'],0)==0x912f0335 and
            a[2]['source']==q[2]['destination']==f[2]['destination']==f[2]['expected'], 'Original dynamic route differs')
    require(a[2]['tid']==c[2]['tid']==q[2]['tid']==m[2]['tid']==f[2]['tid']==f[2]['sender'], 'Original sender/waiter differs')
    require(q[2]['reply']==m[2]['reply']==f[2]['reply'] and q[2]['lease']==m[2]['lease']==f[2]['lease'], 'Reply lease differs')
    require(q[2]['bytes']==f[2]['bytes']=='24' and m[2]['request_free_rc']==f[2]['rc']=='0' and f[2]['waiter']=='1', 'Original message release missing')
    require(c[2]['worker_execution']=='inline-virtual' and c[2]['mode']=='2' and c[2]['worker_started']=='1' and
            c[2]['notification_enabled']==m[2]['notification_enabled']=='1' and
            c[2]['countdown']==m[2]['countdown']=='30' and c[2]['consumed']=='1' and
            all(c[2][k]=='0' for k in ('sample_valid','latched_error','original_cp_task_running','angle_events')),
            'Virtual subscription state or sample scope differs')
    return {'run':run.name,'virtual_notification_subscription_verified':True,'mode_source':'explicit-virtual-profile',
            'worker_execution':'inline-virtual','notification_enabled':1,'countdown':30,'caller_tid':int(a[2]['tid']),
            'console_sha256':hashlib.sha256(console).hexdigest(),'sample_valid':False,'original_cp_task_running':False,
            'original_backup_mode_verified':False,'angle_events_emitted':0,'sensor_ready_verified':False,
            'camera_startup_verified':False,'pixels_consumed':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError) as error:
        proof={'virtual_notification_subscription_verified':False,'error':str(error) or type(error).__name__,
               'camera_startup_verified':False,'pixels_consumed':False,'sensor_ready_verified':False}
    (args.run/'digital-level-native-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['virtual_notification_subscription_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
