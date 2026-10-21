#!/usr/bin/env python3
"""Actual GTK clicks/keys on a private Xvfb; the VM and public launcher are real."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import re
import hashlib

from PIL import Image
from request_queue_watch import RetainableTestDirectory

BASE = Path(__file__).resolve().parent

DRIVER = r'''
import importlib.util,json,os,sys,threading
from pathlib import Path
geometry=Path(sys.argv[1]);new_ui=len(sys.argv)>2 and sys.argv[2]=='new';sys.argv=['gtk-input-driver']
os.environ['A7C2_INSTANCE_DIR']=str(geometry.parent/'instances')
from menu_control import VM
ui_instance=None
if os.environ.get('A7C2_TEST_INFRA20')=='1':
 original_init=VM.__init__
 def physical_input_vm(self,*args,**kwargs):
  original_init(self,*args,**kwargs)
  self.command=['bash','-c','unset MENU_LIVE_APP_INPUT; exec bash "$1"','--',str(Path.cwd()/'run-menu-probe.sh')]
 VM.__init__=physical_input_vm
spec=importlib.util.spec_from_file_location('gtk_real_entry',Path.cwd()/('camera_ui.py' if new_ui else 'menu-native.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original_status=VM.status
main_thread=threading.get_ident()
def observed_status(self):
 with self.lock:
  state=original_status(self)
  png=self.png
 if threading.get_ident()==main_thread:
  info={k:state[k] for k in ('state','error','run','busy','pending','snapshot','events')}
  info['sd_export']=state.get('sd_export')
  if ui_instance is not None:
   info['button_positions']={}
   for name,button in ui_instance.buttons.items():
    point=button.translate_coordinates(ui_instance.window,0,0)
    if point is not None and button.get_mapped():
     info['button_positions'][name]=[point[0]+button.get_allocated_width()//2,
                                     point[1]+button.get_allocated_height()//2]
  info['mode_positions']={}
  if ui_instance is not None:
   popover=getattr(ui_instance,'mode_popover',None)
   if popover is not None and popover.get_mapped():
    choices=popover.get_child()
    if choices is not None:
     for choice in choices.get_children():
      point=choice.translate_coordinates(ui_instance.window,0,0)
      if point is not None and choice.get_mapped():
       info['mode_positions'][choice.get_label()]=[
        point[0]+choice.get_allocated_width()//2,
        point[1]+choice.get_allocated_height()//2]
  if png and state.get('snapshot'):
   image=Path(state['run'])/('driver-validated-%04d.png'%state['snapshot']['number'])
   if not image.exists():
    pending=image.with_suffix('.part');pending.write_bytes(png);os.replace(pending,image)
   info['validated_png']=str(image)
  temporary=geometry.with_suffix('.part');temporary.write_text(json.dumps(info));os.replace(temporary,geometry)
  action_file=geometry.with_suffix('.action')
  if action_file.exists():
   action=json.loads(action_file.read_text());action_file.unlink()
   if action not in ({'action':'export_sd'},{'action':'snapshot'}):raise ValueError('unknown integration-test action')
   self.enqueue(action)
 return state
VM.status=observed_status
if new_ui:
 original_ui_init=module.CameraUI.__init__
 def capture_ui_instance(self,*args,**kwargs):
  global ui_instance
  original_ui_init(self,*args,**kwargs)
  ui_instance=self
 module.CameraUI.__init__=capture_ui_instance
sys.argv=['camera_ui.py'] if new_ui else ['menu-native.py','--display','gtk','--natural-boot']
raise SystemExit(module.main())
'''


def main():
    new_ui='--new-ui' in sys.argv
    if new_ui and '--firstboot' not in sys.argv:raise ValueError('--new-ui currently requires --firstboot')
    if '--controls-smoke' in sys.argv and not new_ui:raise ValueError('--controls-smoke requires --new-ui')
    if '--body-controls-probe' in sys.argv and (not new_ui or '--sustain' in sys.argv):
        raise ValueError('--body-controls-probe requires --new-ui without --sustain')
    if '--mode-probe' in sys.argv and not new_ui:raise ValueError('--mode-probe requires --new-ui')
    if '--mode-reenter-probe' in sys.argv and '--mode-probe' not in sys.argv:raise ValueError('--mode-reenter-probe requires --mode-probe')
    if '--mode-wheel-probe' in sys.argv and (not new_ui or '--firstboot' not in sys.argv or
            any(flag in sys.argv for flag in ('--sustain','--body-controls-probe','--mode-probe','--switch-probe'))):
        raise ValueError('--mode-wheel-probe requires isolated new UI firstboot without other probes')
    if '--focus-controls-probe' in sys.argv and (not new_ui or '--firstboot' not in sys.argv or
            any(flag in sys.argv for flag in ('--sustain','--body-controls-probe','--mode-probe',
                                              '--switch-probe','--mode-wheel-probe'))):
        raise ValueError('--focus-controls-probe requires isolated new UI firstboot')
    queue_probe='--queue-watch-probe' in sys.argv
    media_probe=any(flag in sys.argv for flag in ('--media-predicate-probe','--media-policy-probe'))
    init_probe='--media-init-probe' in sys.argv
    if init_probe and (queue_probe or media_probe or not new_ui or '--firstboot' not in sys.argv or '--export-sd' not in sys.argv):
        raise ValueError('--media-init-probe requires isolated new UI firstboot and SD export')
    if media_probe and (queue_probe or not new_ui or '--firstboot' not in sys.argv or
                        '--body-controls-probe' not in sys.argv or '--export-sd' not in sys.argv):
        raise ValueError('--media-predicate-probe requires isolated new UI body probe and SD export')
    if '--queue-handoff-probe' in sys.argv and not queue_probe:
        raise ValueError('--queue-handoff-probe requires --queue-watch-probe')
    if queue_probe and (not new_ui or '--firstboot' not in sys.argv or '--sustain' not in sys.argv or '--export-sd' not in sys.argv or '--mode-probe' in sys.argv):
        raise ValueError('--queue-watch-probe requires new UI firstboot/sustain/export without MODE probe')
    if '--infra20' in sys.argv and not new_ui:raise ValueError('--infra20 requires --new-ui')
    if '--switch-probe' in sys.argv and not new_ui:raise ValueError('--switch-probe requires --new-ui')
    compile(DRIVER,'<single-window-gtk-test-driver>','exec')
    child = None
    queue_watch = None
    proof_path = None
    proof = {'ok': False, 'method': 'single QEMU window, real xdotool mouse/keyboard, public launcher', 'images': []}
    proof['requested_input_route']='infra20' if '--infra20' in sys.argv else 'app32'
    with RetainableTestDirectory() as temp_owner:
        temp = temp_owner.path
        read_fd, write_fd = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen', '0',
                                 '2560x1600x24', '-nolisten', 'tcp'], pass_fds=(write_fd,),
                                stderr=subprocess.DEVNULL, start_new_session=True)
        os.close(write_fd)
        with os.fdopen(read_fd) as stream:
            display = ':' + stream.readline().strip()
        env = dict(os.environ, DISPLAY=display, GDK_BACKEND='x11', NO_AT_BRIDGE='1')
        if queue_probe:
            env.update(A7C2_QUEUE_WATCH='1',A7C2_CAPTURE_POWER='1',A7C2_TEST_APO_CANCEL='1',A7C2_MODE_READBACK='1')
            proof['queue_watch_probe']='owned Unix QEMU debug; hardware break/watch only; observation not dispatch proof'
        if media_probe:
            env.update(A7C2_MEDIA_PREDICATE_WATCH='1',A7C2_MODE_READBACK='1')
            proof['media_predicate_probe']='owned Unix QEMU hardware breakpoints; original inputs and returns only'
        if init_probe:
            env.update(A7C2_MEDIA_INIT_WATCH='1',A7C2_MODE_READBACK='1')
            proof['media_init_probe']='bounded pre-init10s pacing and hardware data watch, no settings writes'
        # Any later subprocess that omits env must still inherit this private display.
        os.environ.update(DISPLAY=display,GDK_BACKEND='x11',NO_AT_BRIDGE='1')
        env.pop('A7C2_TEST_INFRA20',None)
        if '--infra20' in sys.argv:env['A7C2_TEST_INFRA20']='1'
        geometry = temp / 'geometry.json'

        def xdo(*args):
            return subprocess.check_output(['xdotool', *map(str, args)], env=env, text=True, timeout=10).strip()

        def wait(check, seconds=45):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if queue_watch is not None:
                    queue_watch.check_exited()
                if child.poll() is not None:
                    raise RuntimeError('GTK launcher exited: ' + str(child.returncode))
                state = json.loads(geometry.read_text()) if geometry.exists() else {}
                if state.get('error'):
                    raise RuntimeError(state['error'])
                if state.get('state') == 'error':
                    raise RuntimeError('VM startup failed')
                if check(state):
                    return state
                time.sleep(.1)
            raise TimeoutError('GTK action timed out')

        try:
            log_dir = BASE / 'native-controls-live'
            log_dir.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix='natural-gtk-input-',suffix='.log',dir=log_dir,delete=False) as log:
                proof['launcher_log']=log.name
                child = subprocess.Popen([sys.executable, '-u', '-c', DRIVER, str(geometry),'new' if new_ui else 'legacy'],
                                         cwd=BASE, env=env, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True)
                state = wait(lambda s: s.get('state') == 'running', 360)
                run = Path(state['run'])
                proof_path = run / 'gtk-input-proof.json'
                proof_path.write_text(json.dumps(proof, indent=2) + '\n')
                print('GTK_INPUT_RUN', run, flush=True)
                requested_cp=env.get('A7C2_CP_BACKGROUND','')
                if requested_cp:
                    actual=json.loads((run/'runtime-manifest.json').read_text())
                    proof['cp_background_admission']={'requested':requested_cp,
                        'actual':actual.get('cp_background_profile'),
                        'asset_identity':actual.get('cp_background_asset_identity')}
                    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                    if actual.get('cp_background_profile')!=requested_cp:
                        raise RuntimeError('Requested CP background profile not active in actual VM')
                    print('CP_BACKGROUND_PROFILE_BOUND',requested_cp,flush=True)
                windows = (xdo('search','--onlyvisible','--name','单窗口相机控制') if new_ui else xdo('search','--onlyvisible','--class','qemu')).splitlines()
                assert len(windows)==1, windows
                native=windows[0]
                companion=subprocess.run(['xdotool','search','--onlyvisible','--name','owned VM'],env=env,capture_output=True)
                assert not companion.stdout.strip(), 'A second controls window was created'
                xdo('windowmove', native, 0, 0)
                window_geometry=dict(line.split('=',1) for line in xdo('getwindowgeometry','--shell',native).splitlines())
                assert (int(window_geometry['WIDTH']),int(window_geometry['HEIGHT']))==((1360,930) if new_ui else (1053,606)),window_geometry
                # Positions measured from this classic GTK layout on the private 96-DPI Xvfb.
                button_positions={'UP':(798,113),'DOWN':(798,190),'ENTER':(798,152),'MENU':(994,113)}
                if new_ui:
                    button_positions={'UP':(1183,379),'DOWN':(1183,477),'ENTER':(1183,428),'MENU':(1089,233)}
                    button_positions.update(MODE=(816,150),FN=(1250,287),PLAYBACK=(1110,699),
                        MODE_STILL=(80,169),MODE_MOVIE=(140,169),MODE_SQ=(200,169),
                        FRONT_RIGHT=(954,152),REAR_RIGHT=(1304,233),CONTROL_RIGHT=(1265,567))
                    proof['method']='one new GTK window, real xdotool mouse/keyboard, original QMP LCD; no visible QEMU window'

                def idle():
                    if queue_watch is not None:
                        queue_watch.check_exited()
                    return wait(lambda s: s.get('state') == 'running' and not s.get('busy') and not s.get('pending'))

                def action(name, mouse, position=None):
                    state = idle()
                    previous = max(e['id'] for e in state['events'])
                    window = native
                    xdo('windowraise', window)
                    xdo('windowfocus', '--sync', window)
                    if mouse:
                        if new_ui:
                            point=(state.get('mode_positions',{}).get(position) if position is not None
                                   else state.get('button_positions',{}).get(name))
                            if not isinstance(point,list) or len(point)!=2:
                                raise RuntimeError('GTK button geometry not available: '+name)
                            x,y=point
                        else:
                            x,y=button_positions[name]
                        xdo('mousemove', '--window', window, x, y)
                        xdo('click', 1)
                    else:
                        xdo('key', {'UP': 'Up', 'DOWN': 'Down', 'ENTER': 'Return','MENU':'m','DELETE':'Delete'}[name])
                    if name=='MODE' and position is None:return previous
                    submitted=name+(' '+position if position is not None else '')
                    wait(lambda s: any(e['id'] > previous and e['kind'] == 'input' and
                                      e['message'].startswith(submitted+'：') for e in s.get('events', [])))
                    idle()

                def capture(label, expected_row=None):
                    state = idle()
                    if '--firstboot' in sys.argv:
                        if new_ui:
                            number=(state.get('snapshot') or {}).get('number',0)
                            request=geometry.with_suffix('.action.tmp');request.write_text(json.dumps({'action':'snapshot'}));os.replace(request,geometry.with_suffix('.action'))
                            state=wait(lambda s:(s.get('snapshot') or {}).get('number',0)>number and s.get('validated_png'))
                        time.sleep(.2)
                        window_path=run/('gtk-window-'+label+'.png')
                        subprocess.run(['import','-window',native,str(window_path)],env=env,check=True,timeout=10)
                        with Image.open(window_path) as window_image:
                            if new_ui:
                                with Image.open(state['validated_png']) as displayed:
                                    displayed.load();image=displayed.convert('RGB')
                                if hashlib.sha256(image.tobytes()).hexdigest()!=state['snapshot']['sha256']:
                                    raise ValueError('driver PNG does not match the validated snapshot')
                            else:image=window_image.convert('RGB').crop((0,76,640,556))
                            image.save(run/('gtk-'+label+'.png'))
                            pixels=hashlib.sha256(image.tobytes()).hexdigest()
                        console=(run/'console.log').read_text(errors='replace')
                        commits=[int(n) for n in re.findall(r'GUI_MODEL_COMMITTED packets=(\d+)',console)]
                        proof['images'].append({'label':label,'image':'gtk-'+label+'.png',
                            'snapshot_number':(state.get('snapshot') or {}).get('number'),
                            'snapshot_sequence':(state.get('snapshot') or {}).get('sequence'),
                            'source':'original QMP ramfb LCD plus actual GTK window' if new_ui else 'actual GTK window LCD crop','pixel_sha256':pixels,
                            'model_packets_observed_lower_bound':max(commits,default=0)})
                        proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                        print('GTK_FIRSTBOOT_CAPTURE',label,pixels,flush=True)
                        return
                    number = (state.get('snapshot') or {}).get('number', 0)
                    xdo('windowraise', native)
                    xdo('windowfocus', '--sync', native)
                    xdo('key', 'F12')
                    state = wait(lambda s: (s.get('snapshot') or {}).get('number', 0) > number)
                    path = run / f'user-snapshot-{state["snapshot"]["number"]:03d}.png'
                    wait(lambda s: path.exists())
                    subprocess.run(['import','-window',native,str(run/('gtk-window-'+label+'.png'))],
                                   env=env,check=True,timeout=10)
                    with Image.open(path) as image:
                        image = image.convert('RGB')
                        assert image.size == (640, 480)
                        image.save(run / ('gtk-' + label + '.png'))
                        scores = []
                        for y0 in (67, 136, 206, 276, 346):
                            scores.append(sum(r > 120 and r > 1.4*g and g > 1.5*b
                                              for r, g, b in image.crop((85, y0, 550, y0 + 45)).getdata()))
                        if isinstance(expected_row,int):
                            assert scores[expected_row] > 12000 and max(range(5), key=scores.__getitem__) == expected_row, scores
                        elif expected_row is None:
                            assert max(scores) < 12000, 'ENTER did not leave language list'
                    models = json.loads((run / 'gui-model-latest.json').read_text())
                    assert models['ok'] and models['present'] == 63
                    record = {'label': label, 'image': 'gtk-' + label + '.png',
                              'snapshot': state['snapshot'], 'orange_scores': scores,
                              'model_packets': models['packets'], 'model_sha256': models['sha256']}
                    proof['images'].append(record)
                    proof_path.write_text(json.dumps(proof, indent=2) + '\n')
                    print('GTK_CAPTURE', label, 'rows', scores, 'model_packets', models['packets'], flush=True)

                capture('before', 1)
                if '--firstboot' in sys.argv:
                    shooting_at=None
                    if '--simplified-chinese' in sys.argv:
                        for language_step in range(40):
                            console=(run/'console.log').read_text(errors='replace')
                            if re.search(r'RESOURCE_OPEN .*result=\d+ .*path=/tmp/images/MYingHeiC-GB18030-SJ_wIcon\.ltt',console):
                                # The font is first preloaded while Arabic is highlighted;
                                # the observed next two candidates are traditional/simplified Chinese.
                                action('DOWN',True)
                                action('DOWN',True)
                                capture('simplified-chinese-selected','any')
                                break
                            action('DOWN',True)
                        else:
                            raise RuntimeError('Simplified Chinese font was not selected by original language navigation')
                    for step in range(1,31):
                        if (proof['images'][-1]['pixel_sha256']=='d8f6c43dce8e4e5a2dff8e95cfcde28ff67f54a8dde14fb5037d5ce6f8ca9457'):
                            # This original Chinese page explicitly labels DELETE as "set up on camera".
                            action('DELETE',False)
                            capture('setup-on-camera','any')
                            continue
                        console=(run/'console.log').read_text(errors='replace')
                        ids=re.findall(r'CREATE_SCREEN_ARGS call=\d+ id=(0x[0-9a-f]+|0) ',console)
                        if ids and int(ids[-1],0)==0x431:
                            action('DOWN',True)
                        if ids and int(ids[-1],0)==0x1c6:
                            latest=run/proof['images'][-1]['image']
                            with Image.open(latest) as reader_image:
                                reader_image=reader_image.convert('RGB')
                                lower=sum(r>120 and r>1.4*g and g>1.5*b for r,g,b in reader_image.crop((200,340,440,395)).getdata())
                                upper=sum(r>120 and r>1.4*g and g>1.5*b for r,g,b in reader_image.crop((200,275,440,330)).getdata())
                            if lower<=upper:
                                action('DOWN',True)
                                capture('reader-do-not-set','any')
                        start=len(console)
                        action('ENTER',True)
                        capture(f'firstboot-{step:02d}','any')
                        delta=(run/'console.log').read_text(errors='replace')[start:]
                        if re.search(r'CREATE_SCREEN_ARGS call=\d+ id=0x343 ',delta) and shooting_at is None:
                            shooting_at=step
                        elif shooting_at is not None and step>shooting_at:
                            deadline=time.monotonic()+10
                            while time.monotonic()<deadline:
                                idle();time.sleep(.1)
                            capture('shooting-after-setup','any')
                            if queue_probe:
                                from request_queue_watch import QueueWatch
                                queue_watch=QueueWatch(run,proof['images'][-1]['snapshot_sequence'],child.pid,
                                                       'handoff' if '--queue-handoff-probe' in sys.argv else 'counter',
                                                       autostart=False)
                                queue_watch.start()
                                print('QUEUE_WATCH_PUBLICATION_BREAKPOINT_READY',run,flush=True)
                            if '--mode-probe' in sys.argv:
                                reenter_probe='--mode-reenter-probe' in sys.argv
                                positions=('P','A') if reenter_probe else ('P','A','S','M','AUTO')
                                if reenter_probe:print('MODE_REENTER_PROBE_SCOPE P/A only; ordinary MENU traversal after A; no additional MODE position',flush=True)
                                for index,position in enumerate(positions):
                                    previous=action('MODE',True)
                                    xdo('key',*(['Down']*index),'Return')
                                    wait(lambda s:any(e['id']>previous and e['kind']=='input' and 'MODE '+position in e['message'] for e in s.get('events',[])))
                                    deadline=time.monotonic()+1
                                    while time.monotonic()<deadline:idle();time.sleep(.02)
                                    capture('mode-'+position.lower()+'-early','any')
                                    deadline=time.monotonic()+3
                                    while time.monotonic()<deadline:idle();time.sleep(.02)
                                    capture('mode-'+position.lower(),'any')
                                    if reenter_probe and position=='A':
                                        action('MENU',True)
                                        deadline=time.monotonic()+1
                                        while time.monotonic()<deadline:idle();time.sleep(.02)
                                        capture('mode-a-enter-menu','any')
                                        action('MENU',True)
                                        deadline=time.monotonic()+3
                                        while time.monotonic()<deadline:idle();time.sleep(.02)
                                        capture('mode-a-after-menu-return','any')
                                        proof['mode_reenter_probe']='P/A only; A followed by ordinary MENU/return, with no additional MODE input; scene review required'
                                proof['mode_probe_labels']=list(positions)
                            if '--switch-probe' in sys.argv:
                                for name in ('MODE_STILL','MODE_MOVIE','MODE_SQ','MODE_STILL'):
                                    action(name,True)
                                    deadline=time.monotonic()+1
                                    while time.monotonic()<deadline:idle();time.sleep(.02)
                                    capture('switch-'+name.lower()+'-'+str(len(proof['images'])),'any')
                                proof['switch_probe_symbols']=['MODE_STILL','MODE_MOVIE','MODE_SQ','MODE_STILL']
                            action('MENU',True)
                            capture('menu-after-setup','any')
                            deadline=time.monotonic()+10
                            while time.monotonic()<deadline:
                                idle();time.sleep(.1)
                            capture('menu-stable','any')
                            if '--sustain' in sys.argv:
                                print('FIRSTBOOT_NEW_UI_SUSTAIN_60_BEGIN',flush=True)
                                deadline=time.monotonic()+60
                                while time.monotonic()<deadline:idle();time.sleep(.2)
                                capture('menu-after-60s','any')
                                action('MENU',True)
                                deadline=time.monotonic()+5
                                while time.monotonic()<deadline:idle();time.sleep(.1)
                                capture('main-after-60s','any')
                                action('MENU',True);capture('menu-reopened-after-60s','any')
                            if '--controls-smoke' in sys.argv:
                                for name in ('FRONT_RIGHT','REAR_RIGHT','CONTROL_RIGHT'):
                                    action(name,True);capture('control-'+name.lower(),'any')
                                action('MENU',True);capture('control-main','any')
                                action('FN',True);capture('control-fn','any')
                                action('MENU',True);capture('control-after-fn','any')
                                action('PLAYBACK',True);capture('control-playback','any')
                                action('PLAYBACK',True);capture('control-after-playback','any')
                                proof['control_probe_symbols']=['FRONT_RIGHT','REAR_RIGHT','CONTROL_RIGHT','FN','PLAYBACK']
                            if '--body-controls-probe' in sys.argv:
                                # Back to the shooting screen first: body keys must be judged
                                # in the shooting context, and each redraw restarts the
                                # ~60s original power-off window.
                                action('MENU',True)
                                deadline=time.monotonic()+2
                                while time.monotonic()<deadline:idle();time.sleep(.02)
                                capture('body-shooting-before','any')
                                for name in ('C1','SHUTTER_HALF','SHUTTER','REC'):
                                    if media_probe and name == 'REC':
                                        from request_queue_watch import QueueWatch
                                        queue_watch=QueueWatch(run,proof['images'][-1]['snapshot_sequence'],child.pid,
                                                               'media-policy' if '--media-policy-probe' in sys.argv else 'media',autostart=False)
                                        queue_watch.start()
                                        proof['media_rec_submit_host_monotonic_ns']=time.monotonic_ns()
                                    action(name,True)
                                    deadline=time.monotonic()+2
                                    while time.monotonic()<deadline:idle();time.sleep(.02)
                                    capture('body-'+name.lower(),'any')
                                proof['body_controls_probe_symbols']=['C1','SHUTTER_HALF','SHUTTER','REC']
                                proof['body_controls_note']='GTK submissions and snapshots only; original receive and scene require review; AF/capture not claimed'
                            if '--mode-wheel-probe' in sys.argv:
                                action('MENU',True)
                                capture('mode-wheel-shooting-before','any')
                                probe_started=time.monotonic()
                                trace=[]
                                def step(name,position=None):
                                    if time.monotonic()-probe_started>=45:
                                        raise TimeoutError('MODE/wheel short-window budget exhausted')
                                    if position is not None:
                                        action('MODE',True)
                                        wait(lambda s:position in s.get('mode_positions',{}),5)
                                    action(name,True,position=position)
                                    capture('mode-wheel-'+(position.lower() if position else name.lower()),'any')
                                    trace.append(position if position else name)
                                # Request P again before the three opposite wheel pairs.
                                for position in ('MR1','MR2','MR3','P'):
                                    step('MODE',position)
                                for name in ('FRONT_LEFT','FRONT_RIGHT','REAR_LEFT',
                                             'REAR_RIGHT','CONTROL_LEFT','CONTROL_RIGHT'):
                                    step(name)
                                proof['mode_wheel_probe_symbols']=trace
                                proof['mode_wheel_probe_seconds']=time.monotonic()-probe_started
                                proof['mode_wheel_probe_note']='GTK submissions/snapshots only; original consumer, MR state and wheel business effects require review'
                                proof['main_review_required']=True
                                # Continue to the existing SD export and owned cleanup.
                            if '--focus-controls-probe' in sys.argv:
                                action('MENU',True)
                                capture('focus-controls-shooting-before','any')
                                action('MODE',True)
                                wait(lambda s:'MR1' in s.get('mode_positions',{}),5)
                                action('MODE',True,position='MR1')
                                # Earlier immediate MR1 frame was inconclusive. Give
                                # the ordinary firmware path four seconds to settle.
                                deadline=time.monotonic()+4
                                while time.monotonic()<deadline:idle();time.sleep(.05)
                                capture('focus-controls-mr1-settled','any')
                                action('MODE',True)
                                wait(lambda s:'P' in s.get('mode_positions',{}),5)
                                action('MODE',True,position='P')
                                deadline=time.monotonic()+2
                                while time.monotonic()<deadline:idle();time.sleep(.05)
                                capture('focus-controls-p','any')
                                for name in ('SHUTTER_HALF','AF_ON'):
                                    action(name,True)
                                    deadline=time.monotonic()+2
                                    while time.monotonic()<deadline:idle();time.sleep(.05)
                                    capture('focus-controls-'+name.lower(),'any')
                                proof['focus_controls_symbols']=['MR1','P','SHUTTER_HALF','AF_ON']
                                proof['focus_controls_note']='separate settled MR1 and P-context input/LCD review; AF success requires independent evidence'
                                proof['main_review_required']=True
                            if '--export-sd' in sys.argv:
                                if queue_watch is not None:
                                    proof['queue_watch_cleanup']=queue_watch.stop()
                                    if not proof['queue_watch_cleanup']['safe_to_close']:
                                        raise RuntimeError('Debug CPU resume unconfirmed; retain VM before SD export')
                                geometry.with_suffix('.action').write_text(json.dumps({'action':'export_sd'}))
                                exported=wait(lambda s:s.get('sd_export') is not None,240)['sd_export']
                                proof['sd_export']=exported
                                if not exported.get('ok'):raise RuntimeError('SD export failed: '+str(exported.get('error')))
                                print('FIRSTBOOT_SD_EXPORT_PASS',exported.get('sha256'),flush=True)
                                if exported.get('initialization_observation',{}).get('observation_error'):
                                    raise RuntimeError('Initial media write observation failed: '+
                                                       exported['initialization_observation']['observation_error'])
                                if queue_watch is not None and proof['queue_watch_cleanup'].get('observation_error'):
                                    raise RuntimeError('Media predicate observation failed: '+
                                                       proof['queue_watch_cleanup']['observation_error'])
                            proof.update(ok=False,automation_completed=True,shooting_screen_created=True,menu_input_sent=True,
                                         images_require_main_session_review=True,full_camera_capture_implemented=False)
                            print('FIRSTBOOT_MENU_CANDIDATE',run,flush=True)
                            break
                    else:
                        raise RuntimeError('firstboot did not reach shooting controller within 30 manual clicks')
                    return
                action('DOWN', True)
                capture('mouse-down', 2)
                action('UP', True)
                capture('mouse-up', 1)
                action('DOWN', False)
                capture('keyboard-down', 2)
                action('UP', False)
                capture('keyboard-up', 1)
                print('GTK_SUSTAIN_BEGIN', flush=True)
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    idle()
                    time.sleep(.2)
                action('DOWN', True)
                capture('late-mouse-down', 2)
                action('UP', False)
                capture('late-keyboard-up', 1)
                action('ENTER', True)
                capture('mouse-enter')
                assert proof['images'][-1]['model_packets'] > 489
                assert proof['images'][-1]['model_packets'] > proof['images'][0]['model_packets']
                proof.update(ok=True, manual_firstboot_completed=False,
                             cp_subscriptions_implemented=False, guest_exposure_queries_implemented=False)
                print('GTK_INPUT_PASS', run, flush=True)
        except BaseException as error:
            proof.update(ok=False, error=str(error))
            raise
        finally:
            def retain_resources(reason):
                temp_owner.retain=True
                proof.update(ok=False,automation_completed=False,cleanup_error=reason,
                             retained_vm_resources=dict(control_directory=str(temp),geometry=str(geometry),display=display,
                                                        launcher_pid=child.pid if child else None,xvfb_pid=xvfb.pid))
            if queue_watch is not None:
                proof['queue_watch_cleanup']=queue_watch.stop()
                if not proof['queue_watch_cleanup']['safe_to_close']:
                    retain_resources('CPU resume unconfirmed; own GUI/VM/Xvfb/control mailbox retained')
            if not temp_owner.retain and child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=240)
                except subprocess.TimeoutExpired:
                    retain_resources('Launcher shutdown not confirmed; no SIGKILL of potentially held SD VM')
            if proof_path:
                proof_path.write_text(json.dumps(proof, indent=2) + '\n')
            if not temp_owner.retain:
                xvfb.terminate()
                xvfb.wait(timeout=5)
            if not proof['ok'] and not proof.get('automation_completed') and sys.exc_info()[0] is None:
                raise RuntimeError(proof.get('cleanup_error','GTK acceptance failed'))
    if not proof['ok'] and not proof.get('automation_completed'):
        raise RuntimeError(proof.get('cleanup_error','GTK acceptance failed'))


if __name__ == '__main__':
    main()
