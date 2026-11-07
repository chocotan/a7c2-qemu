#!/usr/bin/env python3
"""Own an X11 Rust UI and VM; check pointer input, native receive and LCD pixels.

Run under a dedicated Xvfb display. Teardown is test interruption, not acceptance
of the camera power-off lifecycle. This does not accept factory setup or capture.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from PIL import Image,ImageChops,ImageStat

HERE=Path(__file__).resolve().parent


def orange(image):
    points=[]
    for y in range(70,420):
        for x in range(100,610):
            r,g,b=image.getpixel((x,y))
            if r>100 and g<120 and b<70 and r>1.3*g:points.append(y)
    return len(points),sum(points)/len(points) if points else None


# Controls addressed by where the pointer lands rather than by a hit-rect
# centre, plus the two that belong to other acceptance scopes.
GEOMETRY_CONTROLS={'wheel','mode_dial'}
# Controls that act on the host simulator itself, never through the guest input queue:
# the Wi-Fi toggle is disabled until its backend exists, and the reset buttons only
# drive reset-derived-state.py. They still have to pass the overlap check.
LOCAL_CONTROLS={'wifi_toggle','reset_open','reset_confirm','reset_cancel'}
LIFECYCLE_CONTROLS={'power','shutter'}
BUTTON_CODES=(('menu',0x1ab),('c1',0x66),('rec',0x1f0),('fn',0x7095),
              ('af_on',0x0f000004),('play',0x1f7),('delete',0x1f8),
              ('front_dial_0',0x1000001c),('front_dial_1',0x1000001c),
              ('rear_dial_0',0x10000016),('rear_dial_1',0x10000016),
              ('reartop_dial_0',0x10000013),('reartop_dial_1',0x10000013),
              ('seg_still',0x71c9),('seg_movie',0x71c9),('seg_sq',0x71c9))
MODE_ORDER=['M','1','2','3','AUTO','P','A','S']
# 模式盘的几何必须与 camera-ui-rs/src/main.rs::draw_mode_dial 一致；盘面下沿受
# 三段选择器（照片/录像/S&Q，上沿 SEG_ROW_TOP）约束。曾经的实测故障：圆心 y=96、
# r=76 时 AUTO 档的点击点 (742,150.7) 落在选择器矩形里，egui 把点击交给了后注册的
# 选择器，注入成 0x71c9/status=2（MOVIE），于是 0x7025 永远收不到——表面像"AUTO 档
# 固件没反应"。所以这里既按 UI 真实几何算点击点，也硬性要求点击点在选择器之上。
MODE_DIAL_CENTER=(742.0,86.0)
MODE_DIAL_RADIUS=62.0
MODE_DETENT_SCALE=0.72
SEG_ROW_TOP=150.0


def build_sweep(controls):
    """Click targets for every exported control, in original-code terms.

    A control the UI exports but this list does not cover is an error, not a
    silent skip: otherwise a newly added button would look verified.
    """
    sweep=[('wheel-UP',880,522,0x3),('wheel-LEFT',816,586,0x15),('wheel-RIGHT',944,586,0x1af),
           ('wheel-ring-left',769.23,586,0x1000001d),('wheel-ring-right',990.77,586,0x1000001d)]
    for name,code in BUTTON_CODES:
        if name in controls:sweep.append((name,controls[name][0],controls[name][1],code))
    for index,mode in enumerate(MODE_ORDER):
        angle=math.radians(index*45.0);radius=MODE_DIAL_RADIUS*MODE_DETENT_SCALE
        x=MODE_DIAL_CENTER[0]+math.sin(angle)*radius
        y=MODE_DIAL_CENTER[1]-math.cos(angle)*radius
        if y>=SEG_ROW_TOP:
            raise ValueError(f'mode detent {mode} lands on the segment selector row (y={y:.1f})')
        sweep.append(('mode-'+mode,x,y,0x7025))
    covered={label for label,_,_,_ in sweep}
    uncovered=sorted(set(controls)-covered-GEOMETRY_CONTROLS-LIFECYCLE_CONTROLS-LOCAL_CONTROLS)
    if uncovered:raise ValueError('Exported controls are not covered by the sweep: '+str(uncovered))
    return sweep


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-controls',action='store_true',
                        help='after the baseline actions, click every exported control')
    args=parser.parse_args()
    env={**os.environ,'WINIT_X11_SCALE_FACTOR':'1','LIBGL_ALWAYS_SOFTWARE':'1'}
    env.pop('WAYLAND_DISPLAY',None)
    base=HERE/'runtime/analysis/ui-live-checks';base.mkdir(exist_ok=True)
    out=Path(tempfile.mkdtemp(prefix='check-',dir=base))
    # The UI exports each control's virtual centre, so the sweep clicks by
    # name instead of duplicating hand-copied layout coordinates.
    controls_path=out/'ui-controls.json'
    env['CAMUI_CONTROLS_PATH']=str(controls_path)
    result={'state':'failed','scope':'Owned Rust pointer→atomic command→original receive→native LCD and UI crop; no factory/capture/power-off acceptance','actions':[]}
    process=None;session=None
    def xdo(*args):
        return subprocess.check_output(['xdotool',*map(str,args)],env=env,timeout=20).decode().strip()
    def wait(predicate,timeout,what):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            value=predicate()
            if value:return value
            if process is not None and process.poll() is not None:raise RuntimeError('Owned launcher ended before '+what)
            time.sleep(.1)
        raise TimeoutError(what)
    def console():return (Path(session['run'])/'console.log').read_text(errors='replace')
    try:
        started=time.monotonic()
        with (out/'launcher.log').open('wb') as log:
            # The control sweep needs a longer owned window than the baseline.
            seconds='420' if args.all_controls else '160'
            process=subprocess.Popen([sys.executable,'-B',str(HERE/'run-camera.py'),'--seconds',seconds,'--observe-input'],
                env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        def get_session():
            match=re.search(r'^CAMERA_UI_SESSION (.+)$',(out/'launcher.log').read_text(errors='replace'),re.M)
            return json.loads(match[1]) if match else None
        session=wait(get_session,100,'owned UI session');result['session']=session
        # 布局自检：UI 自己报告重叠的交互矩形。重叠意味着某个控件点不到，
        # 必须 fail-closed，不能靠后面的"注入成功"掩盖。
        overlap=sorted(set(re.findall(r'^CAMUI_LAYOUT_OVERLAP (.+)$',(out/'launcher.log').read_text(errors='replace'),re.M)))
        result['layout_overlap']=overlap
        if overlap:
            raise AssertionError('UI interactive rects overlap, some control is unreachable: '+'; '.join(overlap))
        commands=Path(session['input_dir']);frame=Path(session['frame'])
        window=xdo('search','--sync','--onlyvisible','--pid',session['ui_pid'],'--name','ILCE-7CM2').splitlines()[0]
        xdo('windowsize','--sync',window,1420,880);xdo('windowfocus','--sync',window)
        def screenshot(name):
            path=out/name
            subprocess.run(['import','-window',window,str(path)],env=env,check=True,timeout=10)
            return Image.open(path).convert('RGB')
        def find_transform():
            image=screenshot('ui-current.png')
            def silver(x,y):
                r,g,b=image.getpixel((x,y));return min(r,g,b)>150 and max(r,g,b)-min(r,g,b)<12
            for top in range(220):
                if not silver(100,top):continue
                xs=[x for x in range(int(image.width*.77)) if silver(x,min(top+70,image.height-1))]
                if xs and max(xs)-min(xs)>900:
                    scale=(max(xs)-min(xs))/1044
                    return min(xs)-8*scale,top-6*scale,scale
            return None
        ox,oy,scale=wait(find_transform,12,'painted camera body');result['transform']=[ox,oy,scale]
        wait(lambda:bool(re.search(r'CREATE_SCREEN_ARGS .* id=0 count=565 ',console())) and frame.is_file(),90,'original shooting main screen')
        def paired_frame(name):
            native=Image.open(frame).convert('RGB')
            if len(native.getcolors(100000) or [])<10:return None
            ui=screenshot(name+'-window.png')
            # Original image is 4:3 contained inside virtual bezel (52,302,644,406).
            rect=(round(ox+(374-406*2/3)*scale),round(oy+302*scale),
                  round(ox+(374+406*2/3)*scale),round(oy+708*scale))
            crop=ui.crop(rect).resize((640,480),Image.Resampling.BILINEAR)
            nc,ny=orange(native);uc,uy=orange(crop)
            if (nc>1000)!=(uc>1000):return None
            if nc>1000 and (abs(ny-uy)>6 or not .6<uc/nc<1.4):return None
            error=sum(ImageStat.Stat(ImageChops.difference(native.crop((12,12,628,430)),crop.crop((12,12,628,430)))).mean)/3
            if error>18:return None
            native.save(out/(name+'-native.png'));crop.save(out/(name+'-lcd.png'))
            return {'native_rgb_sha256':hashlib.sha256(native.tobytes()).hexdigest(),
                    'lcd_rgb_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
                    'orange_pixels':nc,'orange_y':ny,'ui_orange_y':uy,'ui_mean_absolute_error':error}
        previous=wait(lambda:paired_frame('00-main'),15,'matching main LCD');result['initial']=previous

        def act(index,label,vx,vy,code,want_menu=None,require_display=True):
            """Click one control and record what actually happened.

            Every control must reach the ORIGINAL input consumer. Whether the
            shooting screen repaints is a separate question: dials and the mode
            dial can legitimately leave it unchanged, so a missing repaint is
            recorded rather than turned into a failure.
            """
            nonlocal previous
            before=set(commands.glob('*.out'));received=len(re.findall(rf'FULL_INPUT_RECEIVE .* code={code:#x} ',console()))
            xdo('mousemove','--window',window,round(ox+vx*scale),round(oy+vy*scale));xdo('click',1)
            receipt=wait(lambda:next(iter(set(commands.glob('*.out'))-before),None),35,'guest command receipt')
            text=receipt.read_text()
            if not re.search(r'^MENU_DIAG_COMMAND_DONE_.*:0\s*$',text,re.M) or not re.search(r'^INJECT_(?:EVENT|KEY)_SEND .*result=0\s*$',text,re.M):
                raise AssertionError('Original injection failed: '+text)
            wait(lambda:len(re.findall(rf'FULL_INPUT_RECEIVE .* code={code:#x} ',console()))>received,25,'original input receive')
            def changed():
                shot=paired_frame(f'{index:02d}-{label}')
                if shot and want_menu is not None and (shot['orange_pixels']>1000)!=want_menu:return None
                return shot if shot and shot['lcd_rgb_sha256']!=previous['lcd_rgb_sha256'] and shot['native_rgb_sha256']!=previous['native_rgb_sha256'] else None
            if require_display:
                current=wait(changed,15,'native and visible LCD content change')
            else:
                current=None
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    candidate=changed()
                    if candidate:current=candidate;break
                    time.sleep(.1)
            if current is None:
                current=paired_frame(f'{index:02d}-{label}') or previous
                result['actions'].append({'label':label,'elapsed_host_seconds':time.monotonic()-started,
                    'receipt':receipt.name,'original_receive':True,'display_required':False,
                    'display_changed':False,**current})
                print('LIVE_UI_ACTION '+label+' original_receive=1 display_changed=0 (not required)',flush=True)
                return current
            result['actions'].append({'label':label,'elapsed_host_seconds':time.monotonic()-started,
                'receipt':receipt.name,'original_receive':True,'display_required':require_display,
                'display_changed':True,**current})
            previous=current
            print('LIVE_UI_ACTION '+label+' original_receive=1 actual_lcd_changed=1',flush=True)
            return current

        actions=[('MENU',623,232,0x1ab),('ring-right',990.77,586,0x1000001d),
                 ('ring-left',769.23,586,0x1000001d),('DOWN',880,650,0x30),
                 ('ENTER',880,586,0x1ac),('MENU-close',623,232,0x1ab),
                 ('MENU-mid',623,232,0x1ab),('DOWN-mid',880,650,0x30),('MENU-close',623,232,0x1ab),
                 ('MENU-late',623,232,0x1ab),('DOWN-late',880,650,0x30),('ENTER-late',880,586,0x1ac)]
        for index,(label,vx,vy,code) in enumerate(actions,1):
            if label=='MENU-mid':
                wait(lambda:time.monotonic()-started>=55,70,'mid interaction time')
            if label=='MENU-late':
                wait(lambda:time.monotonic()-started>=90,100,'late interaction time')
            want=(label!='MENU-close') if label.startswith('MENU') else None
            current=act(index,label,vx,vy,code,want)
            if label.startswith('MENU') and label!='MENU-close' and current['orange_pixels']<1000:raise AssertionError('MENU did not show native menu highlight')
            if label=='MENU-close' and current['orange_pixels']>1000:raise AssertionError('MENU did not return to shooting view')
            if label=='ring-left' and abs(current['orange_y']-result['actions'][0]['orange_y'])>4:
                raise AssertionError('One left ring step did not return to the original native menu row')

        if args.all_controls:
            # The baseline ends inside a submenu. Dials, the mode dial and the
            # Still/Movie/SQ switch only repaint the shooting screen, so the
            # sweep must return there first or it would report a false failure.
            for attempt in range(4):
                probe=paired_frame(f'9{attempt}-return')
                if probe and probe['orange_pixels']<1000:
                    previous=probe;break
                before=set(commands.glob('*.out'))
                xdo('mousemove','--window',window,round(ox+623*scale),round(oy+232*scale));xdo('click',1)
                wait(lambda:next(iter(set(commands.glob('*.out'))-before),None),35,'menu-close receipt')
                wait(lambda:time.monotonic(),0.6,'settle')
            else:
                raise AssertionError('Could not return to the shooting screen before the sweep')
            controls=wait(lambda:json.loads(controls_path.read_text()) if controls_path.is_file() else None,
                          20,'UI control map export')
            result['controls']=sorted(controls)
            # 布局自检（权威位置：此时已画出很多帧，UI 一定已报告过重叠）。
            overlap=sorted(set(re.findall(r'^CAMUI_LAYOUT_OVERLAP (.+)$',
                                         (out/'launcher.log').read_text(errors='replace'),re.M)))
            result['layout_overlap']=overlap
            if overlap:
                raise AssertionError('UI interactive rects overlap, some control is unreachable: '+'; '.join(overlap))
            sweep=build_sweep(controls)
            # Dials, the mode dial and the Still/Movie/SQ switch reach the
            # original consumer but need not repaint the shooting screen in this
            # build; that is recorded instead of failed.
            input_only=('front_dial','rear_dial','reartop_dial','seg_','mode-')
            failures=[]
            for offset,(label,vx,vy,code) in enumerate(sweep,100):
                try:
                    act(offset,label,vx,vy,code,
                        require_display=not label.startswith(input_only))
                except BaseException as error:
                    failures.append({'label':label,'error':type(error).__name__+': '+str(error)})
                    print('LIVE_UI_CONTROL_FAILED '+label+' '+failures[-1]['error'],flush=True)
                    if 'system-error' in str(error):raise
            result['control_failures']=failures
            result['input_only_controls']=[a['label'] for a in result['actions'] if a.get('display_required') is False]
            if failures:raise AssertionError(f'{len(failures)} controls did not reach the original input consumer')

        if 'id=0x30c ' in console():raise AssertionError('Original system-error screen appeared')
        result['state']='passed'
    except BaseException as error:
        result['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:process.wait(timeout=60)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
        if session is not None:
            run=Path(session['run'])
            if (run/'result.json').is_file():result['vm_result']=json.loads((run/'result.json').read_text())
            if (run/'console.log').is_file():result['terminal_console_sha256']=hashlib.sha256((run/'console.log').read_bytes()).hexdigest()
            shutil.copytree(session['input_dir'],out/'commands',dirs_exist_ok=True)
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('LIVE_UI_CHECK '+str(out)+' '+result['state'],flush=True)


if __name__=='__main__':main()
