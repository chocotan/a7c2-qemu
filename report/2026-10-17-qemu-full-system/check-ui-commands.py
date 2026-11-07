#!/usr/bin/env python3
"""Linux/X11 UI hit-test and command encoding check; no firmware acceptance."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time
from PIL import Image

HERE=Path(__file__).resolve().parent


def main():
    for tool in ('xdotool','import'):
        if not shutil.which(tool):raise RuntimeError('Required X11 test tool missing: '+tool)
    binary=HERE/'camera-ui-rs/target/release/camera-ui-rs'
    checks=HERE/'runtime/analysis/ui-command-checks';checks.mkdir(exist_ok=True)
    out=Path(tempfile.mkdtemp(prefix='check-',dir=checks))
    commands=out/'commands';commands.mkdir()
    env={**os.environ,'WINIT_X11_SCALE_FACTOR':'1','LIBGL_ALWAYS_SOFTWARE':'1'}
    env.pop('WAYLAND_DISPLAY',None)
    env.setdefault('DISPLAY',':0')
    def xdo(*argv,timeout=15):
        return subprocess.check_output(['xdotool',*map(str,argv)],env=env,timeout=timeout).decode().strip()
    try:previous=xdo('getactivewindow')
    except subprocess.CalledProcessError:previous=None  # Dedicated Xvfb may have no window manager.
    result={'scope':'UI command encoding and pointer hit-test only; no VM or firmware acceptance',
            'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'state':'failed','actions':[]}
    process=None
    try:
        with (out/'ui.log').open('wb') as log:
            process=subprocess.Popen([str(binary),'--input-dir',str(commands)],env=env,
                                     stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        window=xdo('search','--sync','--onlyvisible','--pid',process.pid,'--name','ILCE-7CM2').splitlines()[0]
        xdo('windowsize','--sync',window,1420,880)
        if previous:xdo('windowactivate','--sync',window)
        else:xdo('windowfocus','--sync',window)
        screenshot=out/'ui.png'
        # Wait for an actual painted silver top plate, rather than a fixed sleep.
        deadline=time.monotonic()+8
        transform=None
        while time.monotonic()<deadline:
            subprocess.run(['import','-window',window,str(screenshot)],env=env,check=True,timeout=10)
            with Image.open(screenshot) as original:
                image=original.convert('RGB')
                if image.width!=1420 or image.height!=880:raise RuntimeError('Unexpected X11 scale/viewport')
                def silver(x,y):
                    r,g,b=image.getpixel((x,y));return min(r,g,b)>150 and max(r,g,b)-min(r,g,b)<12
                top=next((y for y in range(220) if silver(100,y)),None)
                if top is not None:
                    row=min(top+70,image.height-1)
                    xs=[x for x in range(int(image.width*.77)) if silver(x,row)]
                    if xs and max(xs)-min(xs)>900:
                        # Silver deck is x=8..1052,y=6 in virtual coordinates.
                        scale=(max(xs)-min(xs))/1044
                        transform=(min(xs)-8*scale,top-6*scale,scale)
                        break
            time.sleep(.05)
        if transform is None:raise RuntimeError('UI did not paint its expected top plate')
        ox,oy,scale=transform;result['transform']={'x':ox,'y':oy,'scale':scale}
        # Each action lists the exact (code,status) records the UI must encode.
        # Shutter and power are real codes now (raw->UIBIZ table 0x3704b98:
        # 0x1f1 half press, 0xa7 full press, 0x02 power), and the shutter is a
        # two-stage release, so it must emit four records in this order.
        actions=[('ring-left',769.23,586,[(0x1000001d,-24)]),
                 ('ring-right',990.77,586,[(0x1000001d,24)]),
                 ('MENU',623,232,[(0x1ab,1),(0x1ab,0)]),
                 ('DOWN',880,650,[(0x30,1),(0x30,0)]),
                 ('ENTER',880,586,[(0x1ac,1),(0x1ac,0)]),
                 ('Fn',838,412,[(0x7095,1),(0x7095,0)]),
                 ('AF-ON',838,336,[(0x0f000004,1),(0x0f000004,0)]),
                 ('SHUTTER',958,96,[(0x1f1,1),(0xa7,1),(0xa7,0),(0x1f1,0)]),
                 ('POWER',1019,86,[(0x02,1),(0x02,0)])]
        for label,vx,vy,expected in actions:
            before=set(commands.glob('*.cmd'))
            xdo('mousemove','--window',window,round(ox+vx*scale),round(oy+vy*scale))
            xdo('click',1)
            deadline=time.monotonic()+2
            new=set()
            while time.monotonic()<deadline:
                new=set(commands.glob('*.cmd'))-before
                if new:break
                time.sleep(.03)
            if len(new)!=1:raise AssertionError(f'{label}: expected one atomic request, got {len(new)}')
            path=new.pop();text=path.read_text()
            payloads=re.findall(r'/simulation/inject-key 0x807a0020 0x92840747 (0x[0-9a-f]+) 0 (0x[0-9a-f]+) 0 1',text)
            records=[(int(c,16),0,struct.unpack('<i',struct.pack('<I',int(s,16)))[0],0,1) for c,s in payloads]
            got=[(r[0],r[2]) for r in records]
            if got!=expected:
                raise AssertionError(f'{label}: unexpected payloads {records}; expected {expected}')
            if any(r[4]!=1 for r in records):raise AssertionError('Unexpected input source type')
            result['actions'].append({'label':label,'request':path.name,'records':records})
        if list(commands.glob('*.tmp')):raise AssertionError('Partial request file left visible')
        subprocess.run(['import','-window',window,str(screenshot)],env=env,check=True,timeout=10)
        result['state']='passed'
    except Exception as error:
        result['error']=str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        try:
            if previous:xdo('windowactivate',previous,timeout=2)
        except (subprocess.SubprocessError,OSError):pass
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('UI_COMMAND_CHECK',out,result['state'],flush=True)


if __name__=='__main__':main()
