#!/usr/bin/env python3
"""Standard offline manager pointer test: preview, cancel, CAS race and tombstone.

Only new owned workspaces are changed. This does not claim an original guest
reset: it checks the actual Rust window and the next standard prepare selection.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'workspace-config.py'))
UI_TOOLS=runpy.run_path(str(HERE/'check-config-value-roundtrip.py'))


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def close_window(display_name, window):
    """Send the normal WM_DELETE_WINDOW client message on our own X server."""
    class Data(ctypes.Union):
        _fields_=[('b',ctypes.c_char*20),('s',ctypes.c_short*10),('l',ctypes.c_long*5)]
    class Client(ctypes.Structure):
        _fields_=[('type',ctypes.c_int),('serial',ctypes.c_ulong),('send_event',ctypes.c_int),
                  ('display',ctypes.c_void_p),('window',ctypes.c_ulong),('message_type',ctypes.c_ulong),
                  ('format',ctypes.c_int),('data',Data)]
    class Event(ctypes.Union):
        _fields_=[('client',Client),('pad',ctypes.c_long*24)]
    lib=ctypes.CDLL('libX11.so.6')
    lib.XOpenDisplay.argtypes=[ctypes.c_char_p];lib.XOpenDisplay.restype=ctypes.c_void_p
    lib.XInternAtom.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int];lib.XInternAtom.restype=ctypes.c_ulong
    lib.XSendEvent.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_long,ctypes.POINTER(Event)]
    lib.XFlush.argtypes=[ctypes.c_void_p];lib.XCloseDisplay.argtypes=[ctypes.c_void_p]
    display=lib.XOpenDisplay(display_name.encode())
    if not display:raise RuntimeError('owned display unavailable')
    try:
        event=Event();event.client.type=33;event.client.send_event=1;event.client.display=display
        event.client.window=int(window);event.client.message_type=lib.XInternAtom(display,b'WM_PROTOCOLS',0)
        event.client.format=32;event.client.data.l[0]=lib.XInternAtom(display,b'WM_DELETE_WINDOW',0)
        if not lib.XSendEvent(display,int(window),0,0,ctypes.byref(event)):
            raise RuntimeError('normal window-close event was rejected')
        lib.XFlush(display)
    finally:lib.XCloseDisplay(display)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True)
    args=parser.parse_args()
    source=args.source_run.resolve(strict=True);rt=source.parents[2]
    if not source.is_relative_to((HERE/'runtime').resolve()):raise ValueError('owned F source run required')
    ref=API['official_reference'](rt)
    out=Path(tempfile.mkdtemp(prefix='workspace-reset-ui-',dir=HERE/'runtime/analysis'))
    workspace=out/'workspace';workspace.mkdir()
    source_workspace=Path(json.loads((rt.parent/'session.json').read_text())['workspace'])
    shutil.copytree(source_workspace/'SD',workspace/'SD')
    sd_api=runpy.run_path(str(HERE/'sd-directory.py'));sd_before=sd_api['directory_tree'](workspace/'SD')
    with API['locked'](workspace) as store:
        saved=store.save_run(source,ref)
        history=store.current(ref)['directory']
    old_files={name:sha(history/name) for name in ('Backup.bin','Backup.bak')}
    controls=out/'controls.json'
    env={**os.environ,'WINIT_X11_SCALE_FACTOR':'1','LIBGL_ALWAYS_SOFTWARE':'1','CAMUI_CONTROLS_PATH':str(controls)}
    env.pop('WAYLAND_DISPLAY',None)
    shared=UI_TOOLS['SHARED'];server=manager=None
    result={'schema':'workspace-reset-ui-v1','verified':False,'scope':'actual standard offline Rust manager and host tombstone/factory selection, not a guest reset or new shooting run',
              'output':str(out),'workspace':str(workspace),'seed_generation':saved['generation']}
    source_files=['workspace-config.py','start-official-camera.py','run-camera.py',
                  'camera-ui-rs/src/main.rs','check-workspace-reset-ui.py']
    source_before={name:sha(HERE/name) for name in source_files}
    result['ui_sha256']=sha(HERE/'camera-ui-rs/target/release/camera-ui-rs')
    def xdo(*args):return subprocess.check_output(['xdotool',*map(str,args)],env=env,timeout=15).decode().strip()
    def wait(test,what,timeout=20):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            value=test()
            if value:return value
            if manager is not None and manager.poll() is not None:raise RuntimeError('manager ended before '+what)
            time.sleep(.1)
        raise TimeoutError(what)
    def mapping():
        try:return json.loads(controls.read_text())
        except (FileNotFoundError,json.JSONDecodeError):return {}
    def current():
        try:
            with API['locked'](workspace) as store:return store.current(ref)
        except RuntimeError as error:
            if 'busy' in str(error):return None
            raise
    try:
        server=UI_TOOLS['start_display'](out,env)
        command=[sys.executable,'-B',str(HERE/'start-official-camera.py'),'--workspace',str(workspace),*shared,'--manage-settings']
        with (out/'manager.log').open('w') as log:manager=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def owned_ui():
            records=[json.loads(s.split(' ',1)[1]) for s in (out/'manager.log').read_text(errors='replace').splitlines() if s.startswith('WORKSPACE_SETTINGS_UI ')]
            return records[-1] if records else None
        session=wait(owned_ui,'owned offline UI session',timeout=300);result['session']=session
        if Path(session['workspace'])!=workspace:raise RuntimeError('foreign manager workspace')
        window=xdo('search','--sync','--onlyvisible','--pid',session['ui_pid'],'--name','ILCE-7CM2').splitlines()[0]
        xdo('windowsize','--sync',window,1420,880);xdo('windowfocus','--sync',window)
        def screenshot(name):
            path=out/name;subprocess.run(['import','-window',window,str(path)],env=env,check=True,timeout=10)
            return Image.open(path).convert('RGB')
        def transform():
            image=screenshot('current.png')
            def silver(x,y):
                pixel=image.getpixel((x,y));return min(pixel)>150 and max(pixel)-min(pixel)<12
            for top in range(220):
                if not silver(100,top):continue
                xs=[x for x in range(int(image.width*.77)) if silver(x,min(top+70,image.height-1))]
                if xs and max(xs)-min(xs)>900:
                    scale=(max(xs)-min(xs))/1044;return min(xs)-8*scale,top-6*scale,scale
        ox,oy,scale=wait(transform,'painted body geometry');result['transform']=[ox,oy,scale]
        def click(name):
            point=wait(lambda:mapping().get(name),'control '+name)
            xdo('mousemove','--window',window,round(ox+point[0]*scale),round(oy+point[1]*scale));xdo('click',1)
        wait(lambda:'reset_open' in mapping(),'control export')
        with API['locked'](workspace):
            click('reset_open');old=controls.stat().st_mtime_ns
            wait(lambda:controls.stat().st_mtime_ns!=old,'disabled-state frame')
            assert 'reset_confirm' not in mapping();screenshot('01-workspace-busy.png')
        click('reset_open');wait(lambda:'reset_confirm' in mapping(),'validated preview')
        screenshot('02-confirm-scope.png')
        click('reset_open')  # A repeated open must not schedule a late preview.
        click('reset_cancel')
        wait(lambda:'reset_confirm' not in mapping(),'cancel')
        assert current()['identity']==saved['generation']
        click('reset_open');wait(lambda:'reset_confirm' in mapping(),'CAS preview')
        with API['locked'](workspace) as store:
            changed=store.save_run(source,ref,saved['generation'])
        click('reset_confirm');wait(lambda:'reset_confirm' not in mapping(),'stale confirmation closed')
        def reopened():
            if 'reset_confirm' in mapping():return True
            click('reset_open');return 'reset_confirm' in mapping()
        wait(reopened,'failed CAS handled and fresh preview available',timeout=30)
        assert current()['identity']==changed['generation'] and current()['state']=='backup'
        screenshot('03-fresh-confirm-after-stale.png')
        click('reset_confirm')
        reset=wait(lambda:(c if (c:=current()) and c['state']=='reset' else None),'actual reset tombstone',timeout=30)
        wait(reopened,'completed reset receives another valid preview',timeout=30)
        click('reset_cancel');wait(lambda:'reset_confirm' not in mapping(),'final cancel')
        screenshot('04-workspace-reset-completed.png')
        assert sd_api['directory_tree'](workspace/'SD')==sd_before
        assert all(sha(history/name)==value for name,value in old_files.items())
        assert 'CAMUI_LAYOUT_OVERLAP' not in (out/'manager.log').read_text(errors='replace')
        close_window(env['DISPLAY'],window);manager.wait(timeout=15);assert manager.returncode==0
        with (out/'next-prepare.log').open('w') as log:
            next_run=subprocess.run([sys.executable,'-B',str(HERE/'start-official-camera.py'),'--workspace',str(workspace),*shared,'--prepare-only'],stdout=log,stderr=subprocess.STDOUT,timeout=600)
        assert next_run.returncode==0
        paths=[s.split(' ',1)[1] for s in (out/'next-prepare.log').read_text().splitlines() if s.startswith('OFFICIAL_CAMERA_RUNTIME ')]
        target=Path(paths[-1]);load=json.loads((target.parent/'config-load.json').read_text())
        assert load['generation']==reset['identity']
        assert API['STATE']['extract'](target/'analysis/root/partitions/nflasha2.img','BACKUP.BIN')==ref
        assert not (target/'analysis/config-generation.json').exists()
        assert 'FULLSYSTEM_RUN ' not in (out/'manager.log').read_text(errors='replace')
        source_after={name:sha(HERE/name) for name in source_files}
        assert source_before==source_after
        result.update(verified=True,manager_rc=manager.returncode,reset_generation=reset['identity'],next_prepared_runtime=str(target),factory_selection_verified=True,
                      cancel_unchanged=True,stale_cas_refused=True,workspace_busy_refused=True,sd_tree_preserved=True,old_generations_preserved=True,layout_overlap=[],
                      limits=['offline standard manager; next prepare/default image only, no new guest/LCD reset run','Wi-Fi backend not implemented'])
    except BaseException as error:
        result['error']=repr(error);raise
    finally:
        if manager is not None and manager.poll() is None:
            os.killpg(manager.pid,15)
            try:manager.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(manager.pid,9);manager.wait(timeout=5)
        if server is not None and server.poll() is None:
            server.terminate()
            try:server.wait(timeout=5)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=5)
        result['source_before']=source_before
        result['source_after']={name:sha(HERE/name) for name in source_files}
        result['source_unchanged']=result['source_before']==result['source_after']
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print('WORKSPACE_RESET_UI_CHECK',out,flush=True)


if __name__=='__main__':main()
