#!/usr/bin/env python3
"""Press the ORIGINAL power key once and watch what the firmware does with it.

`POWER` is raw `0x02` -> `UIBIZ_KEY_TACT_POWER` in the body's raw->UIBIZ table
(file offset 0x3704b98, entry 1); it is the only power code with a real dispatch
branch (`0x17923f4 cmp w0,#0x1`, gated by `0x1798044`). `0x01 -> 0x00
UIBIZ_SLIKEY_POWER` is the weaker alternative and is NOT used here.

What counts as evidence:

* the press reaching the original consumer as a FRESH press (`repeat=0`) with a
  release -- otherwise the run is invalid, not a negative;
* the firmware's own power path appearing afterwards (`set_pre_power_off_seq`, the
  blank screen `0x309`, or the guest going away on its own).

A run that merely gets killed by the harness proves nothing, so the runner's
"interrupted" stage result is reported as `terminated_by_harness` rather than as a
successful power-off.
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

POWER=0x02
POWER_KEYS=('0x2',)
POWER_MARKERS=('set_pre_power_off_seq','POWER_OFF','power_off','shutdown','0x309',
               'PRE_POWER_OFF','powerdown','SUSPEND','set_power_state')


def power_gate_command():
    return '\n'.join(['set -- $(busybox pidof im.elf)','if [ "$#" = 1 ]','then',
        'echo POWER_GATE_BEGIN','/simulation/menu-readmem /proc/$1/mem 0x5bc35b0 4 appFw.so',
        'echo POWER_GATE_END','else','echo POWER_GATE_AMBIGUOUS_PROCESS','false','fi'])


def power_gate_snapshots(text):
    snapshots=[]
    for block in re.findall(r'(?m)^POWER_GATE_BEGIN\r?$\n(.*?)^POWER_GATE_END\r?$',text,re.S|re.M):
        records=re.findall(r'READMEM /proc/(\d+)/mem address=([0-9a-f]+) bytes=4',block)
        rows=re.findall(r'(?m)^([0-9a-f]{16}):((?: [0-9a-f]{2}){4})\r?$',block)
        if len(records)!=1 or len(rows)!=1 or int(records[0][1],16)!=int(rows[0][0],16):
            snapshots.append({'verified':False});continue
        index=int.from_bytes(bytes.fromhex(rows[0][1]),'little',signed=True)
        if not 0<=index<26:snapshots.append({'verified':False,'index':index});continue
        snapshots.append({'verified':True,'pid':int(records[0][0]),'index':index,
                          'gate':0 if index in (18,21) else 1,
                          'semantics':'TACT_POWER' if index in (18,21) else 'press_OFF_release_ON'})
    return snapshots


def power_plan(at,release,times=1):
    plan=[]
    for index in range(times):
        t=at+index*3.0
        plan.append(f'{t:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {POWER:#x} 0 0x1 0 1')
        plan.append(f'{t+release:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {POWER:#x} 0 0x0 0 1')
    return plan


def power_off_verified(valid,markers,harness_stopped,guest_shutdown=False,natural_exit=False):
    """The firmware powered itself off -- and the harness did not just stop it.

    A run that the harness tore down prints "interrupted; cleaning this owned VM";
    that is our teardown, not the camera's power path, so it must never count.
    """
    return bool(valid and markers and guest_shutdown and natural_exit and not harness_stopped)


def after_power_press(text):
    for match in re.finditer(r'^.*FULL_INPUT_RECEIVE[^\r\n]*$',text,re.M):
        code=re.search(r'\bcode=(0x[0-9a-fA-F]+)',match[0])
        status=re.search(r'\bstatus=(0x[0-9a-fA-F]+|\d+)',match[0])
        if code and status and int(code[1],0)==POWER and int(status[1],0)==1:
            return text[match.end():]
    return ''


def harness_terminated(text,vm_result):
    return bool('interrupted; cleaning this owned VM' in text or
                ('owned_process_returncode_before_cleanup' in vm_result and
                 vm_result['owned_process_returncode_before_cleanup'] is None))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--power-at',type=float,default=500)
    parser.add_argument('--release',type=float,default=0.6)
    parser.add_argument('--times',type=int,default=1)
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    plan=walk.split(';')
    plan.extend(MENU_PROBE['normalize_plan'](args.power_at))
    plan.extend(power_plan(args.power_at,args.release,args.times))
    for at in (args.power_at-15,args.power_at+3):
        plan.append(f'{at:.1f}:'+power_gate_command())
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='power-key-',dir=runtime/'analysis'))
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
    after=after_power_press(text)
    vm_result=json.loads((run/'result.json').read_text())
    stage=''
    match=re.search(r'FULLSYSTEM_STAGE_(?:COMPLETED|FAILED) (\w+)([^\r\n]*)',text)
    if match:stage=match.group(0)
    result={'schema':'power-key-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),
            'returncode':rc,'power_code':hex(POWER),'presses':args.times,
            'markers':{},'press_validity':'','experiment_valid':False,
            'power_path_observed':False,'terminated_by_harness':False,
            'power_off_verified':False,'stage':stage}
    log=run/'key-plan.log'
    result['power_gate_snapshots']=power_gate_snapshots(log.read_text(errors='replace')) if log.is_file() else []
    for marker in POWER_MARKERS:
        count=len(re.findall(re.escape(marker),after))
        if count:result['markers'][marker]=count
    invalid=press_validity(text,POWER_KEYS,{'0x2':args.times})
    result['press_validity']=invalid or 'ok'
    result['experiment_valid']=not invalid
    result['power_path_observed']=bool(result['markers'])
    # Normal observation completion also tears down a still-running owned VM.
    result['terminated_by_harness']=harness_terminated(text,vm_result)
    result['guest_shutdown_observed']=bool(re.search(r'reboot: Power down|reboot: System halted',after))
    result['owned_process_returncode_before_cleanup']=vm_result.get('owned_process_returncode_before_cleanup')
    result['natural_exit']=result['owned_process_returncode_before_cleanup']==0
    result['power_off_verified']=power_off_verified(result['experiment_valid'],
                                                   result['power_path_observed'],
                                                   result['terminated_by_harness'],
                                                   result['guest_shutdown_observed'],
                                                   result['natural_exit'])
    out=run/'power-key.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('POWER_KEY '+str(out))
    print('  power code:',result['power_code'],'presses:',args.times)
    print('  press validity:',result['press_validity'])
    print('  markers:',result['markers'])
    print('  stage:',stage)
    print('  terminated by harness:',result['terminated_by_harness'])
    print('  power_off_verified:',result['power_off_verified'])
    if invalid:
        print('POWER_KEY_INVALID '+invalid)
        return 2
    return 0 if result['power_off_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
