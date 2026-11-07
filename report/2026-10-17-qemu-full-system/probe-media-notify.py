#!/usr/bin/env python3
"""Deliver the media-in notification the way the FIRMWARE itself delivers it.

`libInfraMediaDetect` does not talk to the mount code directly: appFw converts the
notification into a 5 x u32 record shaped exactly like a physical key
(`{key_code, 0, status, ex_info, 0}`) and sends it to libObj's input queue
`0x807a0020`. `InfraInput::RecvThread@0xd01a8` then maps that raw code through the
body's raw->UIBIZ table (file offset 0x3704b98) into `UIBIZ_KEY_MEDIA_INOUT00..15`.

So injecting the raw code is not "faking a mount": it is the same message the
firmware generates, delivered at the same point in the chain. What IS modelled
here -- and what this probe records honestly -- is the upstream producer:

    CP/Frontcon publisher -> libInfraMediaDetect trigger -> appFw 35503dc converter

Everything from `InfraInput::RecvThread` onward (mapping, callback, event bus,
models, sequence, mcmn/mmc driver, IPSXWRP/ADMA, Fsys writes) is the original
firmware doing its own work. `media_io_verified` therefore only becomes true if the
original driver actually opened the card and the original FAT/Fsys path wrote to
it; a mount attempt that fails is reported as a failed attempt, not as success.

The slot index is NOT statically knowable (the 16 entries are filled from a runtime
param blob), so every candidate is tried, one at a time, and the console tells us
which one the firmware reacts to.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
MENU_PROBE=runpy.run_path(str(HERE/'probe-media-mount-action.py'))
press_validity=MENU_PROBE['press_validity']

# Two families exist in the body's raw->UIBIZ table (0x3704b98):
#   raw 0x0c000000..0x0c000002 -> UIBIZ_KEY_MEDIA_REMOVABLEMEDIA1..3   (idx 679..681)
#   raw 0x0c000003..0x0c000012 -> UIBIZ_KEY_MEDIA_INOUT00..15          (idx 682..697)
# appFw's own key table `4c8cb48` only covers the INOUT family, so the card slots
# are most likely the REMOVABLEMEDIA entries -- the first run injected only
# INOUT00..15 and the mount path stayed silent. Both families are tried.
REMOVABLE_CODES=tuple(hex(0x0c000000+k) for k in range(3))
INOUT_CODES=tuple(hex(0x0c000003+k) for k in range(16))
MEDIA_CODES=REMOVABLE_CODES+INOUT_CODES

# What "the firmware decided to use the card" would look like in the console.
# Only specific names: loose ones like 'mount'/'Mount' match unrelated text (paths,
# other subsystems) and would turn a silent run into a false positive.
MARKERS=('sequence_media_mount','exec_mount','mcmn_drv_open','do_mmc_hw_open',
         'mmc_card_open','supply_bus_power','wait_card_state_stable','mmc_hw_ipsxwrp_init',
         'MCMND_INSERTEDMEDIA','FULL_MCMN','FULL_MMC_TRACE','mcmnd_api_setmediapower',
         'Fsys_WriteDirectFileAsync')


def notify_plan(at,step,release,status=1):
    """Press/release every candidate media code, spaced so the guest can react."""
    plan=[];t=at
    for code in MEDIA_CODES:
        plan.append(f'{t:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code} 0 {status} 0 1')
        plan.append(f'{t+release:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code} 0 0 0 1')
        t+=step
    return plan


def codes_seen(text,codes):
    """Which of `codes` reached the original input consumer.

    The firmware prints codes without leading zeros (`0xc00000c`), so the numbers
    are compared, not a padded literal -- a padded regex silently reports zero.
    """
    wanted={int(code,16) for code in codes}
    found={int(m.group(1),16) for m in
           re.finditer(r'FULL_INPUT_RECEIVE .*code=(0x[0-9a-f]+)',text)}
    return sorted((hex(v) for v in found&wanted),key=lambda s:int(s,16))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=760)
    parser.add_argument('--notify-at',type=float,default=500)
    parser.add_argument('--step',type=float,default=3.0)
    parser.add_argument('--release',type=float,default=0.6)
    parser.add_argument('--status',type=int,default=1)
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    plan=walk.split(';')
    plan.extend(MENU_PROBE['normalize_plan'](args.notify_at))
    plan.extend(notify_plan(args.notify_at,args.step,args.release,args.status))
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='media-notify-',dir=runtime/'analysis'))
    command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
             *configure(queue,args.seconds,True,official=True,key_plan=';'.join(plan)),
             '--bluetooth-policy','original']
    run=None
    with (queue/'runner.log').open('w') as output:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            for line in process.stdout:
                output.write(line);output.flush();print(line,end='',flush=True)
                if line.startswith('FULLSYSTEM_RUN '):run=Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
            rc=process.wait()
        except BaseException:
            process.terminate();process.wait(timeout=30);raise
        finally:process.stdout.close()
    if run is None:raise SystemExit('no owned run; keep '+str(queue/'runner.log'))
    if run.parent.resolve()!=(runtime/'analysis/runs').resolve():raise ValueError('Foreign run path')
    console=(run/'console.log').read_bytes();text=console.decode(errors='replace')
    result={'schema':'media-notify-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),
            'returncode':rc,
            # Be explicit: the upstream producer is a model, not Sony's CP firmware.
            'notification_source':'modeled (CP/Frontcon publisher not emulated)',
            'injected_codes':list(MEDIA_CODES),'status':args.status,
            'markers':{},'media_io_verified':False,'experiment_valid':False,
            'press_validity':'','codes_seen':[]}
    for marker in MARKERS:
        count=len(re.findall(re.escape(marker),text))
        if count:result['markers'][marker]=count
    result['codes_seen']=codes_seen(text,MEDIA_CODES)
    invalid=press_validity(text,MEDIA_CODES,{code:1 for code in MEDIA_CODES})
    result['press_validity']=invalid or 'ok'
    result['experiment_valid']=not invalid
    mount_seen=any(name in result['markers'] for name in
                   ('sequence_media_mount','exec_mount','mcmn_drv_open','do_mmc_hw_open','mmc_card_open'))
    result['mount_path_observed']=mount_seen
    # Only the original driver + original FAT/Fsys writing would justify true.
    result['media_io_verified']=False
    out=run/'media-notify.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('MEDIA_NOTIFY '+str(out))
    print('  notification source:',result['notification_source'])
    print('  injected codes:',len(MEDIA_CODES),'status',args.status)
    print('  codes that reached the original input consumer:',result['codes_seen'])
    print('  mount path observed:',mount_seen)
    print('  markers:',result['markers'])
    print('  press validity:',result['press_validity'])
    print('  media_io_verified: False (would need the original driver + Fsys to actually write)')
    if invalid:
        print('MEDIA_NOTIFY_INVALID '+invalid)
        return 2
    return 0 if mount_seen else 1


if __name__=='__main__':raise SystemExit(main())
