#!/usr/bin/env python3
"""Real default-package/new-window/SD-close check; use a private Xvfb, never hardware."""
import argparse
import ctypes
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import time
from PIL import Image


def close_window(window):
    x=ctypes.CDLL('libX11.so.6')
    x.XOpenDisplay.restype=ctypes.c_void_p
    x.XInternAtom.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int]
    x.XInternAtom.restype=ctypes.c_ulong
    class Message(ctypes.Structure):
        _fields_=[('type',ctypes.c_int),('serial',ctypes.c_ulong),('send_event',ctypes.c_int),
                  ('display',ctypes.c_void_p),('window',ctypes.c_ulong),('message_type',ctypes.c_ulong),
                  ('format',ctypes.c_int),('data',ctypes.c_long*5)]
    class Event(ctypes.Union):
        _fields_=[('message',Message),('pad',ctypes.c_long*24)]
    x.XSendEvent.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_long,ctypes.POINTER(Event)]
    x.XFlush.argtypes=[ctypes.c_void_p]
    x.XCloseDisplay.argtypes=[ctypes.c_void_p]
    display=x.XOpenDisplay(None)
    if not display:raise RuntimeError('Cannot open private X display')
    try:
        event=Event();event.message.type=33;event.message.display=display
        event.message.window=int(window);event.message.format=32
        event.message.message_type=x.XInternAtom(display,b'WM_PROTOCOLS',0)
        event.message.data[0]=x.XInternAtom(display,b'WM_DELETE_WINDOW',0)
        if not x.XSendEvent(display,int(window),0,0,ctypes.byref(event)):raise RuntimeError('WM_DELETE_WINDOW failed')
        x.XFlush(display)
    finally:x.XCloseDisplay(display)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path)
    args=parser.parse_args()
    if not os.environ.get('DISPLAY'):raise RuntimeError('Run under xvfb-run -a')
    base=Path(__file__).resolve().parent;product=base.parents[1]
    latest=base/'latest-menu-run.txt';before=latest.read_text().strip() if latest.exists() else ''
    command=['bash',str(product/'start.sh')]
    if args.cache:command+=['--cache',str(args.cache.resolve())]
    run=None;window=None;proof={'ok':False,'automation_checks_passed':False}
    log=base/'bodydata-default-ui.log'
    with log.open('wb') as output:
        child=subprocess.Popen(command,cwd=product,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        def wait(check,timeout=360):
            deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                if child.poll() is not None:raise RuntimeError(f'Public launcher exited {child.returncode}: {log}')
                try:
                    result=check()
                    if result:return result
                except (OSError,ValueError):pass
                time.sleep(.1)
            raise TimeoutError(str(log))
        owner_pid=None
        def new_run():
            value=latest.read_text().strip()
            if value==before:return None
            candidate=Path(value)
            metadata=json.loads((candidate/'runtime-manifest.json').read_text())
            return candidate if metadata.get('host_control_owner_pid')==owner_pid else None
        def windows():
            result=subprocess.run(['xdotool','search','--onlyvisible','--name','单窗口相机控制'],capture_output=True,text=True)
            return result.stdout.split() if result.returncode==0 else None
        def frame():
            with Image.open(run/'ui-display.ppm') as image:
                image.load();return image.convert('RGB')
        def digest(image):return hashlib.sha256(image.tobytes()).hexdigest()
        def window_image():
            subprocess.run(['import','-window',window,str(run/'default-bodydata-ui-current.png')],check=True)
            with Image.open(run/'default-bodydata-ui-current.png') as image:return image.convert('RGB')
        def orange_row(image):
            width,height=image.size;pixels=image.load();rows=[]
            for y in range(height):
                count=0
                for x in range(width):
                    red,green,blue=pixels[x,y]
                    if red>100 and 10<green<120 and blue<50 and red>2*green:count+=1
                if count>200:rows.append(y)
            return sum(rows)/len(rows) if rows else None
        try:
            found=wait(windows);assert len(found)==1,found
            window=found[0]
            property_text=subprocess.check_output(['xprop','-id',window,'_NET_WM_PID'],text=True)
            owner_pid=int(re.search(r'=\s*(\d+)',property_text).group(1))
            run=wait(new_run)
            image=wait(frame);image.save(run/'default-bodydata-lcd-before.png');initial=digest(image)
            initial_row=wait(lambda:orange_row(window_image()))
            subprocess.run(['xdotool','windowfocus','--sync',window,'key','Down'],check=True)
            image=wait(lambda:(im if digest(im:=frame())!=initial else None),30)
            image.save(run/'default-bodydata-lcd-down.png')
            down_row=wait(lambda:(row if (row:=orange_row(window_image())) is not None and row>initial_row+20 else None),30)
            subprocess.run(['xdotool','windowfocus','--sync',window,'key','Up'],check=True)
            image=wait(lambda:(im if digest(im:=frame())==initial else None),30)
            image.save(run/'default-bodydata-lcd-up.png')
            wait(lambda:(row is not None and abs(row-initial_row)<5) if (row:=orange_row(window_image())) is not None else False,30)
            window_image().save(run/'default-bodydata-ui.png')
            close_window(window)
            assert child.wait(timeout=200)==0
            saved=json.loads((run/'SD/export.json').read_text())
            assert saved['ok'] and saved['quiesce']['original_Fsys_FlushVolume_rc']==0
            proof.update(automation_checks_passed=True,default_package_discovered=True,single_visible_window=True,
                         actual_lcd_down_up=True,window_close_saved_sd=True,sd_sha256=saved['sha256'],
                         window_highlights={'before':initial_row,'down':down_row,'up':initial_row},
                         images_require_main_session_review=True)
            print('BODYDATA_DEFAULT_UI_CANDIDATE',run,json.dumps(proof),flush=True)
        except BaseException as error:
            proof['error']=f'{type(error).__name__}: {error}'
            raise
        finally:
            if run:(run/'bodydata-default-ui-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
            if child.poll() is None:
                if window:close_window(window)
                else:
                    # Signal only the launcher-owned group, then allow GTK's handler to save.
                    children=Path(f'/proc/{child.pid}/task/{child.pid}/children')
                    for pid in children.read_text().split() if children.exists() else []:
                        try:
                            if os.getpgid(int(pid))==child.pid:os.kill(int(pid),signal.SIGTERM)
                        except ProcessLookupError:pass
                try:child.wait(timeout=200)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=10)


if __name__=='__main__':main()
