#!/usr/bin/env python3
"""Press the ORIGINAL shutter, with the body's real two-stage key codes.

The codes come from appFw's own raw->UIBIZ key table (file offset 0x3704b98):
`0x1f1 -> UIBIZ_KEY_TACT_LOCK` (half press) and `0xa7 -> UIBIZ_KEY_TACT_CAP`
(full press). `0xa7` is independently corroborated by the live chain
`a7 -> f -> 0x2070000 EVENT_INPUT_TACT_CAP_ON`.

What this proves and what it does not:

* It can prove the events reach the original input consumer in the right order
  with real (non-repeat) presses.
* It does NOT prove a photo was taken. `capture_verified` stays false unless the
  original encoder produced a real JPEG and the original Fsys wrote it to a
  mounted volume. Mount, frame readiness, encoding and write completion are
  separate acceptance conditions.

The validity gate is the same idea as the menu probe: if a press arrives as a
repeat (prev==status) the navigation/trigger never happened, and the run is
reported as invalid instead of as a negative.
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

S1=0x1f1   # half press -> UIBIZ_KEY_TACT_LOCK
S2=0xa7    # full press -> UIBIZ_KEY_TACT_CAP
SHUTTER_KEYS=('0x1f1','0xa7')

# Sampled downstream markers; absence alone cannot establish non-execution.
MARKERS=('EVENT_INPUT_TACT_CAP','2070000','20f0007','execute_cap_seq','cap_seq',
         'sdf_encode_jpeg','mc_still_enc','still_enc','Fsys_WriteDirectFileAsync',
         '2003:010e','CREATE_SCREEN_ARGS','set_pre_power_off_seq')


def shutter_plan(at, settle, hold):
    """Half press -> full press -> release full -> release half, absolute times.

    `settle` is the AF/AE window between half and full press (the whole point of a
    two-stage release), `hold` is how long the full press is held.
    """
    def inject(code,status,t):
        return f'{t:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {status} 0 1'
    return [inject(S1,1,at),
            inject(S2,1,at+settle),
            inject(S2,0,at+settle+hold),
            inject(S1,0,at+settle+hold+0.2)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=560)
    parser.add_argument('--shutter-at',type=float,default=500)
    parser.add_argument('--settle',type=float,default=5.0)
    parser.add_argument('--hold',type=float,default=1.0)
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    plan=walk.split(';')
    plan.extend(shutter_plan(args.shutter_at,args.settle,args.hold))
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='shutter-input-',dir=runtime/'analysis'))
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
    result={'schema':'shutter-input-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),
            'returncode':rc,'markers':{},'half_press':False,'full_press':False,
            'press_validity':'','experiment_valid':False,'capture_verified':False}
    for marker in MARKERS:
        count=len(re.findall(re.escape(marker),text))
        if count:result['markers'][marker]=count
    result['half_press']=bool(re.search(r'FULL_INPUT_RECEIVE .*code=0x1f1 status=1 ',text))
    result['full_press']=bool(re.search(r'FULL_INPUT_RECEIVE .*code=0xa7 status=1 ',text))
    invalid=press_validity(text,SHUTTER_KEYS)
    result['press_validity']=invalid or 'ok'
    result['experiment_valid']=not invalid
    out=run/'shutter-input.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('SHUTTER_INPUT '+str(out))
    print('  half press reached original consumer:',result['half_press'])
    print('  full press reached original consumer:',result['full_press'])
    print('  press validity:',result['press_validity'])
    print('  markers:',result['markers'])
    # Never report a photo here: only a real JPEG from the original encoder plus a
    # real Fsys write to a mounted volume would justify that.
    print('  capture_verified: False (requires original frame/encoding and completed file write)')
    if invalid:
        print('SHUTTER_INPUT_INVALID '+invalid)
        return 2
    return 0 if (result['half_press'] and result['full_press']) else 1


if __name__=='__main__':raise SystemExit(main())
