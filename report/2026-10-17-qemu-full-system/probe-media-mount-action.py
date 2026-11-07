#!/usr/bin/env python3
"""Ask the ORIGINAL firmware to touch the card through its own menu.

The SD path is blocked on "media notification -> start of the mount sequence".
Rather than fabricating a notification, this probe walks the first-setup plan to
the shooting screen and then selects the menu's card-format entry with real
keys, which is an ordinary user action. If the firmware decides to open the
media, the original mount path should appear in the console; if it does not,
that is reported as a negative result rather than worked around.
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

# Original console evidence for these functions, used only as markers.
MARKERS=('sequence_media_mount','exec_mount','mcmn_drv_open','do_mmc_hw_open',
         'mmc_card_open','supply_bus_power','wait_card_state_stable','mmc_hw_ipsxwrp_init',
         'MCMND_INSERTEDMEDIA','FULL_MCMN','FULL_MMC_TRACE','mcmnd_api_setmediapower')
# Menu path to the card-format entry: MENU, DOWN to フォーマット, ENTER, ENTER (confirm).
MENU_KEYS=('0x1ab','0x30','0x1ac','0x1ac')
# How many presses each code gets in the menu phase; the validity gate looks at the
# LAST that many receives so the first-setup walk's own presses cannot be mistaken
# for the menu ones.
MENU_PRESSES={'0x1ab':1,'0x30':1,'0x1ac':2}
# Codes the first-setup walk uses. A release the serial console dropped leaves the
# key logically held (`prev=1`), and then the next press arrives as a repeat -- so the
# probe re-releases them before its own menu keys.
WALK_CODES=('0x1ab','0x30','0x1ac','0x1f8')


def normalize_plan(at):
    """Release-only pass over the walk's codes, just before the menu keys.

    The walk schedules its releases only 0.2 s after each press; when the guest is
    busy printing, some of those bytes are lost and the front-end keeps the key
    held. Re-releasing is what a real key-up would do, so this restores a known
    input state instead of papering over a repeat.
    """
    plan=[]
    for index,code in enumerate(WALK_CODES):
        t=at-4.0+index*0.4
        plan.append(f'{t:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code} 0 0x0 0 1')
    return plan


def menu_plan(menu_at,step,release):
    """Press/release as SEPARATE absolute-time entries.

    Packing "press;release" into one entry makes the second half absolute, so the
    release fires at t=release (seconds after boot) -- before the press. That is
    what happened in run-zn6ghm6w, and it silently invalidated the experiment:
    every menu press arrived with prev=1 and was counted as a repeat.
    """
    plan=[];at=menu_at
    for name in MENU_KEYS:
        plan.append(f'{at:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {name} 0 0x1 0 1')
        plan.append(f'{at+release:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {name} 0 0x0 0 1')
        at+=step
    return plan


def press_validity(text,keys,presses=None):
    """Return why the run is unusable as evidence, or '' when the presses were real.

    Only the LAST `presses[key]` receives are examined: earlier receives belong to
    the first-setup walk, whose lost releases are not what this probe is testing.
    """
    presses=presses or MENU_PRESSES
    for name in keys:
        expected=presses.get(name,1)
        events=re.findall(rf'FULL_INPUT_RECEIVE [^\r\n]*code={re.escape(name)} status=([01]) [^\r\n]*repeat=(\d+)',text)
        down=[i for i,(status,_repeat) in enumerate(events) if status=='1']
        if len(down)<expected:
            return f'{name}: only {len(down)} press(es) reached the original consumer, expected {expected}'
        tail=[int(events[i][1]) for i in down[-expected:]]
        if any(r!=0 for r in tail):
            return (f'{name}: menu press counted as a repeat ({tail}) -- the key was still '
                    'held, so the firmware did not see a fresh press')
        for index in down[-expected:]:
            if index+1>=len(events) or events[index+1][0]!='0':
                return f'{name}: no release after the tested press reached the original consumer'
    return ''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=560)
    parser.add_argument('--menu-at',type=float,default=490)
    parser.add_argument('--step',type=float,default=6)
    parser.add_argument('--release',type=float,default=0.6,help='press-to-release gap in seconds')
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    plan=walk.split(';')
    plan.extend(normalize_plan(args.menu_at))
    plan.extend(menu_plan(args.menu_at,args.step,args.release))
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='media-mount-input-',dir=runtime/'analysis'))
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
    result={'schema':'media-mount-menu-action-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),
            'returncode':rc,'markers':{},'screens':[]}
    for marker in MARKERS:
        count=len(re.findall(re.escape(marker),text))
        if count:result['markers'][marker]=count
    result['screens']=sorted(set(re.findall(r'CREATE_SCREEN_ARGS [^\r\n]*?\bid=(0x[0-9a-f]+|0)\b',text)))
    result['menu_screens_seen']=any(s in ('0x346','0x2c9','0x2ca') for s in result['screens'])
    result['mount_path_observed']=any(name in result['markers'] for name in
        ('sequence_media_mount','exec_mount','mcmn_drv_open','do_mmc_hw_open','mmc_card_open'))
    result['media_io_verified']=False
    # Validity gate: a negative only means something if the menu keys really
    # arrived as fresh presses. run-zn6ghm6w failed this: the release halves were
    # scheduled at absolute 6 s, so every menu press arrived with prev=1 and the
    # front-end counted it as repeat=411/412 -- the navigation never happened.
    invalid=press_validity(text,MENU_KEYS)
    result['press_validity']=invalid or 'ok'
    result['experiment_valid']=not invalid
    out=run/'media-mount-menu-action.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('MEDIA_MOUNT_MENU_ACTION '+str(out))
    print('  menu screens seen:',result['menu_screens_seen'])
    print('  mount path observed:',result['mount_path_observed'])
    print('  markers:',result['markers'])
    print('  press validity:',result['press_validity'])
    if invalid:
        print('MEDIA_MOUNT_MENU_ACTION_INVALID '+invalid)
        return 2
    # A negative result is a real answer: the firmware did not choose to open
    # the media from this action. Do not turn it into a pass.
    return 0 if result['menu_screens_seen'] else 1


if __name__=='__main__':raise SystemExit(main())
