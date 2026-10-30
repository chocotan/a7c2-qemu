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
from backup_profile import (ADF_PROFILE, INPUT_PROFILE, OUTPUT_PROFILE, BB_SET_MODE_PROFILE,
                            IMAGING_CONNECT_PROFILE, IMAGING_CONTROL_CONNECT_PROFILE, IMAGING_ADF_CONNECT_PROFILE,
                            INFRABB_VEF_CONNECT_PROFILE, FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
                            FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE,
                            ADF_CONFLICTS, BB_MODE_CONFLICTS, FUNCTIONAL_CAMERA_PROFILE, adf_proc_profile_fields,
                            adf_set_input_profile_fields, adf_set_output_profile_fields,
                            bb_set_mode_profile_fields, imaging_pin_connection_profile_fields,
                            imaging_control_connection_profile_fields, imaging_adf_connection_profile_fields,
                            infrabb_vef_connection_profile_fields, infrabb_vef_control_connection_profile_fields,
                            vef_pinmem_input_connection_profile_fields)

BASE = Path(__file__).resolve().parent

DRIVER = r'''
import importlib.util,json,os,sys,threading,hashlib
from pathlib import Path
geometry=Path(sys.argv[1]);new_ui=len(sys.argv)>2 and sys.argv[2]=='new';sys.argv=['gtk-input-driver']
os.environ.setdefault('A7C2_INSTANCE_DIR',str(geometry.parent/'instances'))
from menu_control import VM
import menu_control
receipt_context=threading.local()
original_receive=menu_control.receive_message
original_event=VM.event
def observed_reply(*args,**kwargs):
 reply=original_receive(*args,**kwargs)
 receipt_context.reply=reply
 return reply
def observed_event(self,message,kind='status'):
 original_event(self,message,kind)
 reply=getattr(receipt_context,'reply',None)
 if kind=='input' and isinstance(reply,dict) and reply.get('type')=='camera_input':
  # VM._run has already matched the reply to its command before publishing this event.
  receipts=getattr(self,'_test_input_receipts',[])
  receipts.append(dict(reply,id=self.event_id))
  self._test_input_receipts=receipts[-12:]
  receipt_context.reply=None
menu_control.receive_message=observed_reply
VM.event=observed_event
if os.environ.get('A7C2_TEST_CANDIDATE_JSON'):
 import directory_sd_profile
 candidate=json.loads(os.environ['A7C2_TEST_CANDIDATE_JSON'])
 original_directory_profile=directory_sd_profile.prepare_profile
 def candidate_directory_profile(*args,**kwargs):
  result=original_directory_profile(*args,**kwargs)
  binary=Path(candidate['binary'])
  with binary.open('rb') as stream:
   if hashlib.file_digest(stream,'sha256').hexdigest()!=candidate['sha256']:
    raise ValueError('Candidate QEMU changed before launch')
  result.update(QEMU_SYSTEM_DIR=str(binary.parent),QEMU_SYSTEM_BINARY=binary.name,SEED_BACKUP='alllang')
  return result
 directory_sd_profile.prepare_profile=candidate_directory_profile
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
  receipts=list(getattr(self,'_test_input_receipts',[]))
 if threading.get_ident()==main_thread:
  info={k:state[k] for k in ('state','error','run','busy','pending','snapshot','events')}
  info['input_lifecycle']=ui_instance is not None and state.get('input_lifecycle',False)
  info['input_receipts']=receipts
  info['sd_export']=state.get('sd_export')
  info['sd_card']=state.get('sd_card')
  if ui_instance is not None and hasattr(ui_instance,'sd_action'):
   button=ui_instance.sd_action;point=button.translate_coordinates(ui_instance.window,0,0)
   if point is not None and button.get_mapped():
    info['sd_button_position']=[point[0]+button.get_allocated_width()//2,
                                point[1]+button.get_allocated_height()//2]
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
   if action=={'action':'close'}:
    if ui_instance is not None:ui_instance.window.close()
    else:self.stop()
   else:
    if action not in ({'action':'export_sd'},{'action':'snapshot'},{'action':'shutter_cycle'}):raise ValueError('unknown integration-test action')
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


def input_submission(state, previous, name, mouse, position=None):
    """Match completed host receipts only; original guest consumption stays separate."""
    events={event['id']:event for event in state.get('events',[]) if event['id']>previous}
    if not state.get('input_lifecycle'):
        submitted=name+(' '+position if position is not None else '')
        return any(event['kind']=='input' and event['message'].startswith(submitted+'：')
                   for event in events.values())
    receipts=[]
    for receipt in state.get('input_receipts',[]):
        event=events.get(receipt.get('id'))
        request=receipt.get('request',{})
        if (event is not None and event['kind']=='input' and receipt.get('type')=='camera_input'
                and receipt.get('ok') is True and request.get('action')=='camera_input'
                and event['message']==str(request.get('op'))+'：输入已提交；消费结果以固件为准'):
            receipts.append(receipt)
    if position is not None:
        expected={'action':'camera_input','op':'position','key':name,'position':position}
        return any(receipt['request']==expected for receipt in receipts)
    prefix='pointer:' if mouse else 'keyboard:'
    for receipt in receipts:
        request=receipt['request']
        if request.get('key')!=name:
            continue
        source=request.get('source','')
        if request.get('op')=='tap' and (source=='activation' if mouse else source.startswith(prefix)):
            return True
        if request.get('op')=='press' and source.startswith(prefix):
            released={'action':'camera_input','op':'release','source':source}
            if any(other['id']>receipt['id'] and other['request']==released for other in receipts):
                return True
    return False


# Reviewed Chinese controls: qzcokwhi startup/HUD, qqu0q5oe modals, xnodlttg 33M/AF-S HUD.
# shortcut: current Chinese/default-HUD glyph crops; add reviewed controls for other languages/HUD settings.
FIRSTBOOT_CONTROLS = {
    'language': ((0x12d,), (0,0,200,52), '2ee481d6d8c7ff2409bf3364fc31200f9303cf31555eab179ca3a1a5180903a0'),
    'reader': ((0x1c6,0x1e0), (60,145,580,195), '1e42f1b10248af217c47e267d9ccd67a6f5ba7f8b551d52b81820053ff9d60ff'),
    'privacy': ((0x1e0,0x1dd), (0,0,150,52), 'a9c20aad9a20b14c01234670aead4d96e4cac8dc1aa1cb2a81be63f0842a5581'),
    'setup-on-camera': ((0x1dd,0x21e), (150,428,536,479), 'e3b33a20c03542553b2bbae785e817792ec11fdec921bcaf94b0ad5da8683946'),
    'area-prompt': ((0x1c5,), (170,145,470,195), 'dfc13a0e709861b2957425a361aad5749a8d107bd397cf7be44a947db481a064'),
    'area': ((0xd1,), (0,0,150,52), '6c041e51f382eab581770c60de1c237402c3fe56803e58c9a62c49f7c6f2912e'),
    'date-format': ((0x11c,), (0,0,150,52), 'ca7d67651264ab16b49a8c78799dc4802c78b89d803c7457b59affa4ecfb88da'),
    'date-time': ((0x9d,), (0,0,170,52), '1e36eb8d67ab3eb8209c1340f967c039d03fad758472490c15f9c732e223dd10'),
    'temperature-prompt': ((0x1db,), (50,50,590,235), '09d4c5fdb9e6bca7fe575c918741cc9cc3139842436abf29cfb73575c0a059b7'),
    'temperature-cancel': ((0x431,), (170,100,460,235), 'cc18445617b5d5ac474b854fe6c41a50a20eb594a466e8d4d232266abb67ac9e'),
    'creators-guide': ((0x1f4,), (235,400,405,452), '581af34609bce4146df3f10e78a92cf7d139a14fc931c58d95afdfa1cdc50513'),
    'touch-guide': ((0x1e6,), (10,310,620,395), '0be8ce575c04091007d45b1e6ef01eb17cca90487e0e66951a1dcc11f0e7034b'),
    'shooting': ((0,), (145,0,375,34),
        ('5987f429f9018ee8f94a76a34e6dfd5544a5aeacf26d6d2ff0646194caface54',
         'bc37def4380cc8406c5018c7c3f96ca0dbac344df55b82d02e18300f0de31b18')),
    'system-error': ((0x30c,), (255,155,385,200), '7dca556027edff73436dfec590be634f56ec87cc93e5e57d4fc5e53a8f75f58b'),
}


def firstboot_frame(image, console):
    """A historical controller/factory call cannot identify the currently visible page."""
    screens=[(int(call),int(screen,0),int(count)) for call,screen,count in re.findall(
        r'CREATE_SCREEN_ARGS call=(\d+) id=(0x[0-9a-f]+|0) count=(\d+) ',console)]
    call,screen,count=screens[-1] if screens else (None,None,None)
    result={'page':'pending','screen_call':call,'screen_id':screen,'screen_count':count,
            'reason':'waiting for reviewed original page content and current screen'}
    if screen in (0x30c,0x309):
        result.update(page='failed',reason='original system error (0x30c)' if screen==0x30c else 'original shutdown (0x309)')
        return result
    if image.size!=(640,480):
        return result
    for page,(candidates,box,digest) in FIRSTBOOT_CONTROLS.items():
        glyphs=image.crop(box).convert('L').point(lambda pixel:255 if pixel>=128 else 0,'1')
        actual_digest=hashlib.sha256(glyphs.tobytes()).hexdigest()
        if actual_digest not in ((digest,) if isinstance(digest,str) else digest):
            continue
        result['content_page']=page
        if page=='system-error':
            result.update(page='failed',reason='original LCD displays 系统出错')
        elif screen in candidates:
            if page=='shooting' and (count!=565 or len(screens)<2 or screens[-2][1]!=0x343 or
                    not any(item[1]==0x347 for item in screens) or
                    not any(item[1]==0x1e6 for item in screens)):
                continue
            result.update(page=page,reason='reviewed original content matches current screen',
                          control_crop_sha256=actual_digest)
        break
    if result['page']=='pending':
        result['reason']+=f': screen={screen!r}, content={result.get("content_page","unknown")}'
    return result


def wait_lcd_settled(initial_image, refresh, wait, label, accept=lambda image:True, changed=True):
    """Only navigation which changes a page/selection uses a changed-frame requirement."""
    previous=None
    image=initial_image
    attempt=0

    def settled(_state):
        nonlocal previous,image,attempt
        image=refresh(f'{label}-{attempt:02d}')
        attempt+=1
        ui=image.get('firstboot_ui',{})
        if ui.get('page')=='failed':
            raise RuntimeError('Original UI failed: '+ui['reason'])
        fingerprint=(image['pixel_sha256'],ui.get('screen_call'))
        stable=fingerprint==previous
        previous=fingerprint
        return (not changed or image['pixel_sha256']!=initial_image['pixel_sha256']) and stable and accept(image)

    try:
        wait(settled)
    except TimeoutError as error:
        reason=image.get('firstboot_ui',{}).get('reason','no original page evidence')
        requirement='changed, stable LCD and original input evidence' if changed else 'stable original page content'
        raise TimeoutError(label+': waiting for '+requirement+'; '+reason) from error
    return image


def original_input_edges(console, name):
    code={'ENTER':0x1ac,'DOWN':0x30,'DELETE':0x1f8}[name]
    pressed=None
    for number,words in re.findall(r'INPUT_EVENT32 n=(\d+) tid=\d+ words=\[([^]\r\n]+)\]\r?\n',console):
        try:
            values=[int(word,0) for word in words.split(',')]
        except ValueError:
            continue
        if values==[code,0,1,0,0,0,0,0]:
            pressed=int(number)
        elif pressed is not None and values==[code,0,0,0,0,0,0,0] and int(number)>pressed:
            return [pressed,int(number)]
    return []


def firstboot_step(initial_image, read_console, refresh, action, wait, image_path, label):
    """One known original page at a time; unknown modals never receive a confirm."""
    def known(image):
        return image.get('firstboot_ui',{}).get('page','pending')!='pending'

    image=wait_lcd_settled(initial_image,refresh,wait,label+'-page',known,changed=False)
    ui=image['firstboot_ui']
    if ui['page']=='shooting':
        return {'ready':True,'page':ui,'lcd_stable':True,'capture_verified':False}
    submitted=[]

    def navigate(name, mouse=True):
        nonlocal image
        start=len(read_console())
        before=image
        action(name,mouse)
        image=wait_lcd_settled(before,refresh,wait,label+'-'+name.lower(),
            lambda frame:bool(original_input_edges(read_console()[start:],name)))
        submitted.append({'key':name,'input_submission_event_verified':True,
                          'original_input_edges':original_input_edges(read_console()[start:],name),
                          'lcd_changed_and_stable':True})

    selection=None
    if ui['page'] in ('reader','temperature-prompt','temperature-cancel'):
        def refresh_choice(attempt):
            nonlocal image
            image=refresh(f'{label}-choice-{attempt:02d}')
        selection=select_reader_later(image_path,refresh_choice,lambda:navigate('DOWN'),choice=ui['page'])
        if image['firstboot_ui'].get('page')!=ui['page']:
            raise RuntimeError('Firstboot choice page changed before confirm; no confirm input sent')
    navigate('DELETE',False) if ui['page']=='setup-on-camera' else navigate('ENTER')
    return {'ready':False,'page':ui,'selection':selection,'actions':submitted,
            'reason':'original page advanced; shooting readiness remains pending','capture_verified':False}


def select_simplified_chinese(initial_image, read_console, refresh, press_down, wait):
    """A submitted DOWN can precede rendering; advance only after the LCD settles."""
    font=re.compile(r'OBS RESOURCE_OPEN call=(\d+) result=(-?\d+) errno=(\d+) '
                    r'path=/tmp/images/MYingHeiC-GB18030-SJ_wIcon\.ltt\r?\n')
    image=initial_image

    def down(step):
        nonlocal image
        press_down()
        try:
            image=wait_lcd_settled(image,refresh,wait,f'language-{step:02d}')
        except TimeoutError as error:
            raise TimeoutError(f'Language DOWN {step}: original LCD did not change and settle') from error

    for step in range(41):
        opened=list(font.finditer(read_console()))
        if opened:
            selected=opened[-1]
            if int(selected[2])<=0 or int(selected[3])!=0:
                raise RuntimeError('Simplified Chinese font open failed: '+selected[0].strip())
            # This exact font is preloaded at Arabic; the next two choices are Chinese.
            down(step+1)
            down(step+2)
            return {'navigation_steps':step+2,'font_open_call':int(selected[1]),
                    'selection_frame_stable':True}
        if step==40:
            break
        down(step+1)
    raise RuntimeError('Simplified Chinese font was not selected by original language navigation')


def select_reader_later(image_path, refresh, press_down, choice='Reader later'):
    """Factory entry can precede LCD publication; never navigate an old page."""
    down_sent=False
    for attempt in range(13):
        with Image.open(image_path()) as opened:
            image=opened.convert('RGB')
            edges=((100,14),(300,14),(500,14),(30,100),(30,200),(30,300),
                   (609,100),(609,200),(609,300))
            framed=image.size==(640,480) and all(48<=r<=96 and max(r,g,b)-min(r,g,b)<=3
                for r,g,b in (image.getpixel(point) for point in edges))
            scores=[sum(r>120 and r>1.4*g and g>1.5*b for r,g,b in
                        image.crop(box).getdata())
                    for box in ((200,275,440,330),(200,340,440,395))]
        upper,lower=scores if framed else (0,0)
        if lower>1000 and lower>upper:
            return {'highlight_verified':True,'dialog_frame_verified':True,'down_sent':down_sent,'refreshes':attempt,
                    'upper_orange_pixels':upper,'lower_orange_pixels':lower}
        if attempt==12:break
        if upper>1000 and upper>lower and not down_sent:
            press_down();down_sent=True
        refresh(attempt)
    raise RuntimeError(choice+' choice not visible; no confirm input sent')


def directory_sd_argument(argv):
    flag='--host-sd-dir'
    if flag not in argv:
        if any(item.startswith(flag+'=') for item in argv):
            raise ValueError('--host-sd-dir requires a separate directory argument')
        return None
    if argv.count(flag)!=1:
        raise ValueError('--host-sd-dir must be specified once')
    index=argv.index(flag)
    if index+1>=len(argv) or argv[index+1].startswith('--'):
        raise ValueError('--host-sd-dir requires a directory argument')
    path=Path(argv[index+1])
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('--host-sd-dir must name an existing absolute directory')
    return str(path.resolve())


def candidate_build_argument(argv):
    flag='--candidate-build'
    if flag not in argv:
        if any(item.startswith(flag+'=') for item in argv):
            raise ValueError('--candidate-build requires a separate build directory argument')
        return None
    index=argv.index(flag)
    if argv.count(flag)!=1 or index+1>=len(argv) or argv[index+1].startswith('--'):
        raise ValueError('--candidate-build requires exactly one build directory')
    stage=Path(argv[index+1])
    if not stage.is_absolute() or not stage.is_dir():
        raise ValueError('--candidate-build requires an existing absolute build directory')
    stage=stage.resolve()
    receipt=json.loads((stage/'pci-hardware-build.json').read_text())
    if not isinstance(receipt,dict) or receipt.get('scope')!='default-off PCI/ATU hardware in native GTK/USB/directory-SD build':
        raise ValueError('Candidate is not a combined native build')
    binary=stage/'build/qemu-system-aarch64'
    if not binary.is_file():
        raise ValueError('Candidate QEMU binary missing')
    with binary.open('rb') as stream:
        digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=receipt.get('binary_sha256'):
        raise ValueError('Candidate QEMU build receipt does not match the binary')
    return {'build':str(stage),'binary':str(binary),'sha256':digest}


def close_launcher(child, geometry, functional_camera):
    if child.poll() is None:
        if functional_camera:
            pending = geometry.with_suffix('.action.tmp')
            pending.write_text(json.dumps({'action':'close'}))
            os.replace(pending, geometry.with_suffix('.action'))
        else:
            os.killpg(child.pid, signal.SIGTERM)
        child.wait(timeout=240)
    if functional_camera and child.returncode != 0:
        raise RuntimeError('Functional GTK launcher exited without confirmed orderly close: ' + str(child.returncode))


def main():
    directory_sd=directory_sd_argument(sys.argv)
    candidate=candidate_build_argument(sys.argv)
    new_ui='--new-ui' in sys.argv
    requested_adf=os.environ.get('A7C2_ADF_PROC_PATH','')
    if requested_adf not in ('',ADF_PROFILE) or (requested_adf and (
            not directory_sd or not new_ui or '--firstboot' not in sys.argv or '--export-sd' not in sys.argv or
            os.environ.get('A7C2_VEF_PATH')!='virtual-nomem-v1' or
            any(os.environ.get(name) for name in ADF_CONFLICTS))):
        raise ValueError('ADF source7 Idle test requires guarded VEF NoMem, new UI firstboot, directory SD and safe export')
    requested_adf_input=os.environ.get('A7C2_ADF_SET_INPUT','')
    if requested_adf_input not in ('',INPUT_PROFILE) or (requested_adf_input and requested_adf!=ADF_PROFILE):
        raise ValueError('ADF set input test requires the explicit guarded ADF source7 Idle profile')
    requested_adf_output=os.environ.get('A7C2_ADF_SET_OUTPUT','')
    if requested_adf_output not in ('',OUTPUT_PROFILE) or (requested_adf_output and requested_adf_input!=INPUT_PROFILE):
        raise ValueError('ADF set output test requires the explicit guarded ADF set input profile')
    requested_bb_set_mode=os.environ.get('A7C2_BB_SET_MODE','')
    if requested_bb_set_mode not in ('',BB_SET_MODE_PROFILE):
        raise ValueError('A7C2_BB_SET_MODE must be virtual-bb-still-target3-op0-v1 or unset')
    if requested_bb_set_mode and (
            not directory_sd or not new_ui or '--firstboot' not in sys.argv or '--export-sd' not in sys.argv or
            candidate is None or not os.environ.get('A7C2_BACKUP_BUILD') or
            Path(os.environ['A7C2_BACKUP_BUILD']).resolve()!=Path(candidate['build']).resolve() or
            (os.environ.get('A7C2_DIRECTORY_SD') and
             Path(os.environ['A7C2_DIRECTORY_SD']).resolve()!=Path(directory_sd).resolve()) or
            os.environ.get('A7C2_BACKUP_SYNC')!='virtual-primary-v1' or
            os.environ.get('A7C2_CP_BACKGROUND')!='virtual-mode3-cold-v1' or
            os.environ.get('A7C2_UDATE_DISTRIBUTION')!='virtual-roundtrip-v1' or
            os.environ.get('A7C2_TOUCH_PANEL')!='virtual-config-v1' or
            os.environ.get('A7C2_TCIN_DETECT')!='virtual-inactive-v1' or
            os.environ.get('A7C2_DFS_SELECTOR')!='virtual-selector-v1' or
            os.environ.get('A7C2_VEF_PATH')!='virtual-nomem-v1' or
            requested_adf!=ADF_PROFILE or requested_adf_input!=INPUT_PROFILE or
            requested_adf_output!=OUTPUT_PROFILE or os.environ.get('SEED_BACKUP','alllang')!='alllang' or
            os.environ.get('A7C2_HOST_SD') or os.environ.get('A7C2_SD_IMAGE') or
            os.environ.get('A7C2_SD_SPARSE') or os.environ.get('A7C2_SD_HOTPLUG') or
            os.environ.get('MENU_USB_NET') or any(os.environ.get(name) for name in BB_MODE_CONFLICTS)):
        raise ValueError('BB set mode requires public profiles, same candidate and directory SD on new UI firstboot/export')
    requested_imaging_connect=os.environ.get('A7C2_IMAGING_CONNECT','')
    if requested_imaging_connect not in ('',IMAGING_CONNECT_PROFILE) or (requested_imaging_connect and (
            requested_bb_set_mode!=BB_SET_MODE_PROFILE or '--natural-shutter' not in sys.argv)):
        raise ValueError('Imaging connection requires the exact guarded BB profile and natural shutter/export test')
    requested_imaging_control_connect=os.environ.get('A7C2_IMAGING_CONTROL_CONNECT','')
    if requested_imaging_control_connect not in ('',IMAGING_CONTROL_CONNECT_PROFILE) or (requested_imaging_control_connect and
            requested_imaging_connect!=IMAGING_CONNECT_PROFILE):
        raise ValueError('Imaging control connection requires the exact first imaging connection and natural shutter/export test')
    requested_imaging_adf_connect=os.environ.get('A7C2_IMAGING_ADF_CONNECT','')
    if requested_imaging_adf_connect not in ('',IMAGING_ADF_CONNECT_PROFILE) or (requested_imaging_adf_connect and
            requested_imaging_control_connect!=IMAGING_CONTROL_CONNECT_PROFILE):
        raise ValueError('Imaging ADF connection requires the exact second imaging control connection and natural shutter/export test')
    requested_infrabb_vef_connect=os.environ.get('A7C2_INFRABB_VEF_CONNECT','')
    if requested_infrabb_vef_connect not in ('',INFRABB_VEF_CONNECT_PROFILE) or (requested_infrabb_vef_connect and
            requested_imaging_adf_connect!=IMAGING_ADF_CONNECT_PROFILE):
        raise ValueError('InfraBB VEF connection requires the exact third imaging ADF connection and natural shutter/export test')
    requested_infrabb_vef_control_connect=os.environ.get('A7C2_INFRABB_VEF_CONTROL_CONNECT','')
    if requested_infrabb_vef_control_connect not in ('',FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE) or (requested_infrabb_vef_control_connect and
            requested_infrabb_vef_connect!=INFRABB_VEF_CONNECT_PROFILE):
        raise ValueError('InfraBB VEF control connection requires the exact fourth InfraBB VEF connection and natural shutter/export test')
    requested_vef_pinmem_input_connect=os.environ.get('A7C2_VEF_PINMEM_INPUT_CONNECT','')
    if requested_vef_pinmem_input_connect not in ('',FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE) or (requested_vef_pinmem_input_connect and
            requested_infrabb_vef_control_connect!=FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE):
        raise ValueError('VEF PinMem input connection requires the exact fifth InfraBB VEF control connection and natural shutter/export test')
    if (requested_adf_input or requested_adf_output or requested_bb_set_mode or requested_imaging_connect or
            requested_imaging_control_connect or requested_imaging_adf_connect or requested_infrabb_vef_connect or
            requested_infrabb_vef_control_connect or requested_vef_pinmem_input_connect):
        from menu_control import launcher
        launcher.profile_environment({**os.environ,'A7C2_DIRECTORY_SD':directory_sd},natural_boot=True)
    if os.environ.get('A7C2_EE_PASSIVE_AFTER_SHUTTER')=='1' and '--natural-shutter' not in sys.argv:
        raise ValueError('Post-shutter passive sampling requires --natural-shutter')
    if candidate and (not directory_sd or not new_ui or '--firstboot' not in sys.argv):
        raise ValueError('--candidate-build requires new UI firstboot and explicit directory SD')
    fn_nav_probe='--fn-nav-probe' in sys.argv
    fn_silent_enter='--fn-silent-enter' in sys.argv
    fn_silent_enable='--fn-silent-enable' in sys.argv
    format_workflow='--format-card-workflow' in sys.argv
    reviewed_prompt='--format-prompt-reviewed' in sys.argv
    if reviewed_prompt and not format_workflow:raise ValueError('Reviewed prompt action requires explicit format workflow')
    if fn_silent_enter and not fn_nav_probe:raise ValueError('--fn-silent-enter requires --fn-nav-probe')
    if fn_silent_enable and not fn_silent_enter:raise ValueError('--fn-silent-enable requires --fn-silent-enter')
    if fn_nav_probe and (not new_ui or '--firstboot' not in sys.argv or
            '--simplified-chinese' not in sys.argv or
            any(flag in sys.argv for flag in ('--natural-shutter','--controls-smoke','--mode-probe',
                                              '--switch-probe','--body-controls-probe','--focus-controls-probe','--sustain'))):
        raise ValueError('--fn-nav-probe requires isolated Simplified-Chinese new UI firstboot')
    if format_workflow and (not new_ui or '--firstboot' not in sys.argv or
            '--simplified-chinese' not in sys.argv or '--export-sd' not in sys.argv or
            os.environ.get('A7C2_HOST_SD')!='256gb' or '--natural-shutter' in sys.argv):
        raise ValueError('Format workflow requires Chinese firstboot and explicit host-backed256GB SD/export profile')
    if new_ui and '--firstboot' not in sys.argv:raise ValueError('--new-ui currently requires --firstboot')
    if '--controls-smoke' in sys.argv and not new_ui:raise ValueError('--controls-smoke requires --new-ui')
    if '--sd-hotplug-probe' in sys.argv and not (new_ui and '--firstboot' in sys.argv and '--export-sd' in sys.argv):
        raise ValueError('--sd-hotplug-probe requires new UI firstboot and safe SD export')
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
    if '--natural-shutter' in sys.argv and (not new_ui or '--firstboot' not in sys.argv or
            '--simplified-chinese' not in sys.argv or '--export-sd' not in sys.argv or
            any(flag in sys.argv for flag in ('--sustain','--body-controls-probe','--mode-probe',
                                              '--switch-probe','--mode-wheel-probe','--focus-controls-probe'))):
        raise ValueError('--natural-shutter requires isolated Simplified-Chinese new UI firstboot and SD export')
    if '--enter-still-mode' in sys.argv and '--natural-shutter' not in sys.argv:
        raise ValueError('--enter-still-mode requires --natural-shutter')
    if '--reenter-still-mode' in sys.argv and '--natural-shutter' not in sys.argv:
        raise ValueError('--reenter-still-mode requires --natural-shutter')
    if '--silent-mode-shutter' in sys.argv and ('--natural-shutter' not in sys.argv or
            '--enter-still-mode' in sys.argv or '--reenter-still-mode' in sys.argv):
        raise ValueError('--silent-mode-shutter requires isolated --natural-shutter without mode probes')
    if '--enter-still-mode' in sys.argv and '--reenter-still-mode' in sys.argv:
        raise ValueError('choose one Still-mode experiment')
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
    proof = {'ok': False, 'capture_verified':False,'automation_completed':False,'shooting_screen_created':False,
             'method': 'single QEMU window, real xdotool mouse/keyboard, public launcher', 'images': []}
    proof['requested_input_route']='infra20' if '--infra20' in sys.argv else 'app32'
    if requested_adf:proof['adf_proc_path_intent']=adf_proc_profile_fields(requested_adf)
    if requested_adf_input:proof['adf_set_input_intent']=adf_set_input_profile_fields(requested_adf_input)
    if requested_adf_output:proof['adf_set_output_intent']=adf_set_output_profile_fields(requested_adf_output)
    if requested_bb_set_mode:proof['bb_set_mode_intent']=bb_set_mode_profile_fields(requested_bb_set_mode)
    if requested_imaging_connect:proof['imaging_pin_connection_intent']=imaging_pin_connection_profile_fields(requested_imaging_connect)
    if requested_imaging_control_connect:proof['imaging_control_connection_intent']=imaging_control_connection_profile_fields(requested_imaging_control_connect)
    if requested_imaging_adf_connect:proof['imaging_adf_connection_intent']=imaging_adf_connection_profile_fields(requested_imaging_adf_connect)
    if requested_infrabb_vef_connect:proof['infrabb_vef_connection_intent']=infrabb_vef_connection_profile_fields(requested_infrabb_vef_connect)
    if requested_infrabb_vef_control_connect:proof['infrabb_vef_control_connection_intent']=infrabb_vef_control_connection_profile_fields(requested_infrabb_vef_control_connect)
    if requested_vef_pinmem_input_connect:proof['vef_pinmem_input_connection_intent']=vef_pinmem_input_connection_profile_fields(requested_vef_pinmem_input_connect)
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
        env.pop('A7C2_TEST_CANDIDATE_JSON',None)
        if candidate:
            env['A7C2_TEST_CANDIDATE_JSON']=json.dumps(candidate)
            proof['requested_candidate']=candidate
        if directory_sd:
            env['A7C2_DIRECTORY_SD']=directory_sd
            proof['requested_directory_sd']=directory_sd
        if '--sd-hotplug-probe' in sys.argv:env['A7C2_SD_HOTPLUG']='1'
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
                if candidate:
                    actual=json.loads((run/'runtime-manifest.json').read_text())
                    observed=actual.get('files',{}).get(candidate['binary'])
                    if observed!=candidate['sha256']:
                        raise RuntimeError('Actual VM did not select the requested candidate QEMU')
                    proof['candidate_admission']={**candidate,'actual_sha256':observed}
                    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                    print('CANDIDATE_QEMU_BOUND',observed,flush=True)
                requested_cp=env.get('A7C2_CP_BACKGROUND','')
                requested_udate=env.get('A7C2_UDATE_DISTRIBUTION','')
                requested_touch=env.get('A7C2_TOUCH_PANEL','')
                requested_backup=env.get('A7C2_BACKUP_SYNC','')
                requested_tcin=env.get('A7C2_TCIN_DETECT','')
                requested_dfs=env.get('A7C2_DFS_SELECTOR','')
                requested_vef=env.get('A7C2_VEF_PATH','')
                if (requested_cp or requested_udate or requested_touch or requested_backup or requested_tcin or
                        requested_dfs or requested_vef or requested_adf or requested_adf_input or
                        requested_adf_output or requested_bb_set_mode or requested_imaging_connect or
                        requested_imaging_control_connect or requested_imaging_adf_connect or
                        requested_infrabb_vef_connect or requested_infrabb_vef_control_connect or
                        requested_vef_pinmem_input_connect or directory_sd):
                    actual=json.loads((run/'runtime-manifest.json').read_text())
                    if directory_sd:
                        proof['directory_sd_admission']={
                            'requested':directory_sd,
                            'actual_profile':actual.get('directory_sd_profile'),
                            'actual_bytes':actual.get('rm_file_image_bytes')}
                        if (actual.get('directory_sd_profile')!='directory-vvfat-256gb-v1' or
                                actual.get('rm_file_image_bytes')!=256000000000):
                            raise RuntimeError('Requested host directory was not bound to the 256GB directory SD')
                        print('DIRECTORY_SD_PROFILE_BOUND',directory_sd,flush=True)
                    if requested_cp:
                        proof['cp_background_admission']={'requested':requested_cp,
                            'actual':actual.get('cp_background_profile'),
                            'asset_identity':actual.get('cp_background_asset_identity')}
                        if actual.get('cp_background_profile')!=requested_cp:
                            raise RuntimeError('Requested CP background profile not active in actual VM')
                        print('CP_BACKGROUND_PROFILE_BOUND',requested_cp,flush=True)
                    if requested_udate:
                        proof['udate_distribution_admission']={'requested':requested_udate,
                            'actual':actual.get('udate_distribution_profile'),
                            'protocol':actual.get('udate_distribution_protocol'),
                            'source_clock':actual.get('udate_distribution_source_clock'),
                            'kernel':actual.get('udate_distribution_kernel'),
                            'original_cp_executed':actual.get('udate_distribution_original_cp_executed'),
                            'hardware_ready':actual.get('udate_distribution_hardware_ready'),
                            'observer_matches_build':actual.get('selected_observer_matches_build')}
                        if (actual.get('udate_distribution_profile')!=requested_udate or
                                actual.get('udate_distribution_protocol')!='kernel-public-roundtrip-v1' or
                                not actual.get('udate_distribution_kernel') or
                                actual['udate_distribution_kernel'].get('sha256') !=
                                actual['udate_distribution_kernel'].get('receipt',{}).get('sha256') or
                                actual.get('selected_observer_matches_build') is not True):
                            raise RuntimeError('Requested UDATE distribution profile not active in actual VM')
                        wait(lambda state: 'UDATE_K_REGISTER: rc=0' in
                             (run/'console.log').read_text(errors='replace'), 30)
                        proof['udate_distribution_admission']['kernel_register_seen']=True
                        print('UDATE_DISTRIBUTION_PROFILE_BOUND',requested_udate,flush=True)
                    if requested_touch:
                        proof['touch_panel_admission']={
                            'requested':requested_touch,
                            'actual':actual.get('touch_panel_profile'),
                            'protocol':actual.get('touch_panel_protocol'),
                            'original_cp_executed':actual.get('touch_panel_original_cp_executed'),
                            'f02f_transport_verified':actual.get('touch_panel_f02f_transport_verified'),
                            'control_result_verified':actual.get('touch_panel_control_result_verified'),
                            'hardware_ready':actual.get('touch_panel_hardware_ready'),
                            'observer_matches_build':actual.get('selected_observer_matches_build')}
                        if (actual.get('touch_panel_profile')!=requested_touch or
                                actual.get('touch_panel_protocol')!='AP0146-DevPanelBody-virtual-config-v1' or
                                actual.get('selected_observer_matches_build') is not True or
                                actual.get('touch_panel_original_cp_executed') is not False or
                                actual.get('touch_panel_f02f_transport_verified') is not False or
                                actual.get('touch_panel_control_result_verified') is not False or
                                actual.get('touch_panel_hardware_ready') is not False):
                            raise RuntimeError('Requested touch-panel virtual configuration profile not active in actual VM')
                        print('TOUCH_PANEL_PROFILE_BOUND',requested_touch,flush=True)
                    if requested_tcin:
                        proof['tcin_admission']={
                            'requested':requested_tcin,'actual':actual.get('tcin_detect_profile'),
                            'protocol':actual.get('tcin_detect_protocol'),
                            'original_cp_executed':actual.get('tcin_original_cp_executed'),
                            'hardware_verified':actual.get('tcin_hardware_verified')}
                        if (actual.get('tcin_detect_profile')!=requested_tcin or
                                actual.get('tcin_detect_protocol')!='AP0429-inactive-disable-config-v1' or
                                actual.get('selected_observer_matches_build') is not True or
                                actual.get('tcin_original_cp_executed') is not False or
                                actual.get('tcin_hardware_verified') is not False or
                                actual.get('tcin_enable_and_active_disable_supported') is not False):
                            raise RuntimeError('Requested TCIN inactive subset not active in actual VM')
                        print('TCIN_PROFILE_BOUND',requested_tcin,flush=True)
                    if requested_vef:
                        if (actual.get('vef_path_profile')!=requested_vef or
                                (actual.get('backup_transport') or {}).get('vef_path_profile')!=requested_vef or
                                actual.get('vef_path_protocol')!='AP0149-path1-native-empty-v1' or
                                actual.get('selected_observer_matches_build') is not True or
                                any(actual.get(name) is not False for name in (
                                    'vef_path_original_cp_executed','vef_path_frames_verified',
                                    'vef_path_global_dmm_idle_verified','vef_path_hardware_verified',
                                    'vef_path_nonempty_release_supported'))):
                            raise RuntimeError('Requested VEF NoMem resource model not active in actual VM')
                        proof['vef_path_admission']={'profile':requested_vef,'hardware_verified':False,
                                                     'frames_verified':False,'global_dmm_idle_verified':False}
                        print('VEF_NOMEM_PROFILE_BOUND',requested_vef,flush=True)
                    if requested_adf:
                        expected_adf=adf_proc_profile_fields(requested_adf)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or source.get(name)!=value
                                    for source in (actual,transport) for name,value in expected_adf.items())):
                            raise RuntimeError('Requested ADF source7 Idle control model not active in actual VM')
                        proof['adf_proc_path_admission']=expected_adf
                        print('ADF_PROC_PATH_PROFILE_BOUND',requested_adf,flush=True)
                    if requested_adf_input:
                        expected_adf_input=adf_set_input_profile_fields(requested_adf_input)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or source.get(name)!=value
                                    for source in (actual,transport) for name,value in expected_adf_input.items())):
                            raise RuntimeError('Requested ADF set input metadata model not active in actual VM')
                        proof['adf_set_input_admission']=expected_adf_input
                        print('ADF_SET_INPUT_PROFILE_BOUND',requested_adf_input,flush=True)
                    if requested_adf_output:
                        expected_adf_output=adf_set_output_profile_fields(requested_adf_output)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or source.get(name)!=value
                                    for source in (actual,transport) for name,value in expected_adf_output.items())):
                            raise RuntimeError('Requested ADF set output no-change model not active in actual VM')
                        proof['adf_set_output_admission']=expected_adf_output
                        print('ADF_SET_OUTPUT_PROFILE_BOUND',requested_adf_output,flush=True)
                    if requested_bb_set_mode:
                        expected_bb=bb_set_mode_profile_fields(requested_bb_set_mode)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_bb.items())):
                            raise RuntimeError('Requested BB set mode intent is not typed-identical in both runtime receipts')
                        proof['bb_set_mode_admission']=expected_bb
                        print('BB_SET_MODE_PROFILE_BOUND',requested_bb_set_mode,flush=True)
                    if requested_imaging_connect:
                        expected_imaging=imaging_pin_connection_profile_fields(requested_imaging_connect)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_imaging.items())):
                            raise RuntimeError('Requested imaging connection intent is not typed-identical in both runtime receipts')
                        proof['imaging_pin_connection_admission']=expected_imaging
                        print('IMAGING_PIN_CONNECTION_PROFILE_BOUND',requested_imaging_connect,flush=True)
                    if requested_imaging_control_connect:
                        expected_imaging_control=imaging_control_connection_profile_fields(requested_imaging_control_connect)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_imaging_control.items())):
                            raise RuntimeError('Requested imaging control connection intent is not typed-identical in both runtime receipts')
                        proof['imaging_control_connection_admission']=expected_imaging_control
                        print('IMAGING_CONTROL_CONNECTION_PROFILE_BOUND',requested_imaging_control_connect,flush=True)
                    if requested_imaging_adf_connect:
                        expected_imaging_adf=imaging_adf_connection_profile_fields(requested_imaging_adf_connect)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_imaging_adf.items())):
                            raise RuntimeError('Requested imaging ADF connection intent is not typed-identical in both runtime receipts')
                        proof['imaging_adf_connection_admission']=expected_imaging_adf
                        print('IMAGING_ADF_CONNECTION_PROFILE_BOUND',requested_imaging_adf_connect,flush=True)
                    if requested_infrabb_vef_connect:
                        expected_infrabb_vef=infrabb_vef_connection_profile_fields(requested_infrabb_vef_connect)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_infrabb_vef.items())):
                            raise RuntimeError('Requested InfraBB VEF connection intent is not typed-identical in both runtime receipts')
                        proof['infrabb_vef_connection_admission']=expected_infrabb_vef
                        print('INFRABB_VEF_CONNECTION_PROFILE_BOUND',requested_infrabb_vef_connect,flush=True)
                    if requested_infrabb_vef_control_connect:
                        expected_infrabb_vef_control=infrabb_vef_control_connection_profile_fields(requested_infrabb_vef_control_connect)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(name not in source or type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_infrabb_vef_control.items())):
                            raise RuntimeError('Requested InfraBB VEF control connection intent is not typed-identical in both runtime receipts')
                        proof['infrabb_vef_control_connection_admission']=expected_infrabb_vef_control
                        print('INFRABB_VEF_CONTROL_CONNECTION_PROFILE_BOUND',requested_infrabb_vef_control_connect,flush=True)
                    if requested_vef_pinmem_input_connect:
                        expected_vef_pinmem_input=vef_pinmem_input_connection_profile_fields(requested_vef_pinmem_input_connect)
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('selected_observer_matches_build') is not True or
                                any(name not in source or type(source.get(name)) is not type(value) or
                                    json.dumps(source.get(name))!=json.dumps(value)
                                    for source in (actual,transport) for name,value in expected_vef_pinmem_input.items())):
                            raise RuntimeError('Requested VEF PinMem input connection intent is not typed-identical in both runtime receipts')
                        proof['vef_pinmem_input_connection_admission']=expected_vef_pinmem_input
                        print('VEF_PINMEM_INPUT_CONNECTION_PROFILE_BOUND',requested_vef_pinmem_input_connect,flush=True)
                    if requested_dfs:
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('dfs_selector_profile')!=requested_dfs or
                                transport.get('dfs_selector_profile')!=requested_dfs or
                                'QEMU_SONY_DFS_TEST' not in transport.get('hardware_flags',[]) or
                                actual.get('dfs_actual_clock_changes') is not False or
                                actual.get('dfs_silicon_timing_verified') is not False):
                            raise RuntimeError('Requested DFS selector not active in actual VM')
                        proof['dfs_admission']={'profile':requested_dfs,'actual_clock_changes':False,
                                                'silicon_timing_verified':False}
                        print('DFS_SELECTOR_PROFILE_BOUND',requested_dfs,flush=True)
                    if requested_backup:
                        transport=actual.get('backup_transport') or {}
                        if (actual.get('backup_sync_profile')!=requested_backup or
                                transport.get('fixture_sha256')!='a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977' or
                                transport.get('fixture_bytes')!=1419512 or
                                actual.get('backup_original_cp_executed') is not False):
                            raise RuntimeError('Requested guarded Backup profile not active in actual VM')
                        wait(lambda state:'BACKUP_K_BOUND: controller=0 channel=4' in
                             (run/'console.log').read_text(errors='replace'),30)
                        proof['backup_admission']={'profile':requested_backup,'transport':transport,
                                                   'kernel_bound_seen':True,'original_cp_executed':False,
                                                   'backup_sync_verified':False,'capture_verified':False}
                        print('BACKUP_PROFILE_BOUND',requested_backup,flush=True)
                    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
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
                    wait(lambda s: input_submission(s,previous,name,mouse,position))
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
                            'model_packets_observed_lower_bound':max(commits,default=0),
                            'firstboot_ui':firstboot_frame(image,console)})
                        proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                        print('GTK_FIRSTBOOT_CAPTURE',label,pixels,flush=True)
                        if proof['images'][-1]['firstboot_ui']['page']=='failed':
                            raise RuntimeError('Original UI failed: '+proof['images'][-1]['firstboot_ui']['reason'])
                        return proof['images'][-1]
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
                    proof['firstboot_readiness']={'ready':False,'reason':'original startup navigation pending',
                                                 'capture_verified':False}
                    if '--simplified-chinese' in sys.argv:
                        proof['language_navigation']=select_simplified_chinese(
                            proof['images'][-1],lambda:(run/'console.log').read_text(errors='replace'),
                            lambda label:capture(label,'any'),lambda:action('DOWN',True),wait)
                        capture('simplified-chinese-selected','any')
                    for step in range(1,31):
                        result=firstboot_step(proof['images'][-1],
                            lambda:(run/'console.log').read_text(errors='replace'),
                            lambda label:capture(label,'any'),action,wait,
                            lambda:run/proof['images'][-1]['image'],f'firstboot-{step:02d}')
                        proof.setdefault('firstboot_navigation',[]).append(result)
                        if result['page']['page']=='reader':
                            proof.setdefault('reader_later_selections',[]).append({'step':step,**result['selection']})
                        proof['firstboot_readiness']=result
                        proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                        if result['ready']:
                            shooting=capture('shooting-after-setup','any')
                            if shooting['firstboot_ui']['page']!='shooting':
                                proof['firstboot_readiness']={'ready':False,'reason':'shooting content changed before probes',
                                                             'capture_verified':False}
                                raise RuntimeError('Firstboot shooting readiness pending: current original HUD not confirmed')
                            if fn_nav_probe:
                                action('FN',True)
                                capture('fn-open','any')
                                proof['fn_nav_probe']={'input_submission_event_verified':True,
                                    'navigation_steps':0,'silent_mode_selected':False,
                                    'setting_write_verified':False}
                                for index in range(1,6 if fn_silent_enter else 7):
                                    action('DOWN',False)
                                    capture(f'fn-down-{index:02d}','any')
                                    proof['fn_nav_probe']['navigation_steps']=index
                                    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                                if fn_silent_enter:
                                    action('ENTER',False)
                                    capture('silent-enter','any')
                                    proof['fn_nav_probe']['silent_enter_submitted']=True
                                    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                                    if fn_silent_enable:
                                        action('UP',False)
                                        capture('silent-on-selected','any')
                                        action('ENTER',False)
                                        capture('silent-enabled','any')
                                        proof['fn_nav_probe']['silent_enable_submitted']=True
                                        proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                            if reviewed_prompt:
                                from format_prompt_review import require_reviewed_cancel,require_confirm_selected
                                reference=run/'gtk-shooting-after-setup.png'
                                require_reviewed_cancel(reference)
                                action('UP',False)
                                capture('format-prompt-selected','any')
                                selection=require_confirm_selected(reference,run/'gtk-format-prompt-selected.png')
                                proof['format_prompt_review']={**selection,'enter_submitted':False}
                                proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                                action('ENTER',False)
                                proof['format_prompt_review']['enter_submitted']=True
                                proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                                capture('format-prompt-after-enter','any')
                            if queue_probe:
                                from request_queue_watch import QueueWatch
                                queue_watch=QueueWatch(run,proof['images'][-1]['snapshot_sequence'],child.pid,
                                                       'handoff' if '--queue-handoff-probe' in sys.argv else 'counter',
                                                       autostart=False)
                                queue_watch.start()
                                print('QUEUE_WATCH_PUBLICATION_BREAKPOINT_READY',run,flush=True)
                            if '--enter-still-mode' in sys.argv:
                                action('MODE_STILL',True)
                                capture('enter-still-mode','any')
                                deadline=time.monotonic()+5
                                while time.monotonic()<deadline:idle();time.sleep(.05)
                                proof['enter_still_mode']={'input_submission_event_verified':True,
                                    'mode_transition_verified':False,'ee_start_verified':False}
                                proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                            if '--reenter-still-mode' in sys.argv:
                                action('MODE_MOVIE',True)
                                capture('reenter-movie','any')
                                deadline=time.monotonic()+5
                                while time.monotonic()<deadline:idle();time.sleep(.05)
                                action('MODE_STILL',True)
                                capture('reenter-still','any')
                                deadline=time.monotonic()+5
                                while time.monotonic()<deadline:idle();time.sleep(.05)
                                proof['reenter_still_mode']={'movie_input_submission_event_verified':True,
                                    'still_input_submission_event_verified':True,
                                    'mode_transition_verified':False,'ee_start_verified':False}
                                proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                            if '--silent-mode-shutter' in sys.argv:
                                action('FN',True)
                                for index in range(1,6):
                                    action('DOWN',False)
                                capture('silent-fn-selected','any')
                                action('ENTER',False)
                                capture('silent-enter','any')
                                action('UP',False)
                                capture('silent-on-selected','any')
                                action('ENTER',False)
                                capture('silent-enabled','any')
                                capture('silent-shooting','any')
                                proof['silent_mode_shutter']={'selection_sequence_submitted':True,
                                    'on_screen_verified':False,'setting_write_verified':False,
                                    'still_capture_verified':False}
                                proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                            if '--natural-shutter' in sys.argv:
                                wait_lcd_settled(proof['images'][-1],lambda label:capture(label,'any'),wait,
                                    'natural-shutter-ready',
                                    lambda image:image['firstboot_ui']['page']=='shooting',changed=False)
                                state=idle();previous=max(e['id'] for e in state['events'])
                                request=geometry.with_suffix('.action.tmp')
                                request.write_text(json.dumps({'action':'shutter_cycle'}))
                                os.replace(request,geometry.with_suffix('.action'))
                                wait(lambda s:any(e['id']>previous and e['kind']=='input' and
                                                  '自然快门序列已提交' in e['message'] for e in s.get('events',[])),45)
                                proof['natural_shutter']={'input_submission_event_verified':True,
                                    'consumer_verified':False,'still_capture_verified':False}
                                proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                                deadline=time.monotonic()+15
                                while time.monotonic()<deadline:idle();time.sleep(.05)
                                capture('natural-shutter-after','any')
                            if '--mode-probe' in sys.argv:
                                reenter_probe='--mode-reenter-probe' in sys.argv
                                positions=('P','A') if reenter_probe else ('P','A','S','M','AUTO')
                                if reenter_probe:print('MODE_REENTER_PROBE_SCOPE P/A only; ordinary MENU traversal after A; no additional MODE position',flush=True)
                                for index,position in enumerate(positions):
                                    previous=action('MODE',True)
                                    xdo('key',*(['Down']*index),'Return')
                                    wait(lambda s:input_submission(s,previous,'MODE',True,position))
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
                            if '--natural-shutter' not in sys.argv and not reviewed_prompt and not fn_nav_probe:
                                action('MENU',True)
                                capture('menu-after-setup','any')
                                deadline=time.monotonic()+10
                                while time.monotonic()<deadline:
                                    idle();time.sleep(.1)
                                capture('menu-stable','any')
                            if format_workflow:
                                if reviewed_prompt:capture('menu-stable','any')
                                from menu_step_request import validate
                                request_path=run/'format-step.request.json'
                                print('FORMAT_WORKFLOW_READY',run,flush=True)
                                deadline=time.monotonic()+900
                                for step in range(1,81):
                                    while not request_path.exists():
                                        if time.monotonic()>deadline:
                                            raise TimeoutError('Format menu reviewed-page navigation budget exhausted')
                                        idle();time.sleep(.1)
                                    request=json.loads(request_path.read_text())
                                    key=validate(request,step)
                                    request_path.rename(run/f'format-step-{step:02d}.request.json')
                                    if key=='FINISH':break
                                    action(key,False)
                                    capture(f'format-step-{step:02d}-{key.lower()}','any')
                                    print('FORMAT_WORKFLOW_STEP',step,key,flush=True)
                                else:raise RuntimeError('Format menu step limit reached')
                                proof['format_menu_workflow']={'completed_navigation':True,
                                    'original_format_verified':False,'review_required':True}
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
                            if '--sd-hotplug-probe' in sys.argv:
                                proof['sd_hotplug_after_setup']={'ok':False,'steps':[],
                                    'scope':'real GTK button after original Chinese setup and MENU'}
                                for present in (False,True):
                                    state=idle();before=state.get('sd_card') or {}
                                    if not before.get('ok') or before['state']!=('absent' if present else 'present'):
                                        raise RuntimeError('No confirmed SD starting state after setup: '+str(before))
                                    point=state.get('sd_button_position')
                                    if not isinstance(point,list) or len(point)!=2:
                                        raise RuntimeError('Actual SD button geometry missing')
                                    xdo('mousemove','--window',native,*point);xdo('click',1)
                                    state=wait(lambda s:(s.get('sd_card') or {}).get('sequence',0)>before['sequence'] and
                                               not s.get('busy') and not s.get('pending'),100)
                                    current=state['sd_card']
                                    proof['sd_hotplug_after_setup']['steps'].append(current)
                                    proof_path.write_text(json.dumps(proof,indent=2)+'\n')
                                    print('GTK_SD_HOTPLUG_STEP',json.dumps(current),flush=True)
                                    if not current.get('ok') or current.get('state')!=('present' if present else 'absent'):
                                        raise RuntimeError('Original SD transition after setup did not complete; no auto reversal')
                                    capture('sd-reinserted' if present else 'sd-retired','any')
                                proof['sd_hotplug_after_setup']['ok']=True
                                proof['sd_hotplug_after_setup']['read_write_after_reinsert_verified']=False
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
                                if os.environ.get('A7C2_EE_PASSIVE_AFTER_SHUTTER')=='1':
                                    late=exported.get('post_shutter_observation') or {}
                                    proof['post_shutter_observation']=late
                                    if not late.get('ok'):
                                        raise RuntimeError('Post-shutter passive observation failed: '+str(late))
                                if exported.get('initialization_observation',{}).get('observation_error'):
                                    raise RuntimeError('Initial media write observation failed: '+
                                                       exported['initialization_observation']['observation_error'])
                                if queue_watch is not None and proof['queue_watch_cleanup'].get('observation_error'):
                                    raise RuntimeError('Media predicate observation failed: '+
                                                       proof['queue_watch_cleanup']['observation_error'])
                            proof.update(ok=False,automation_completed=True,shooting_screen_created=True,
                                         menu_input_sent='--natural-shutter' not in sys.argv and not reviewed_prompt and not fn_nav_probe,
                                         images_require_main_session_review=True,full_camera_capture_implemented=False)
                            print('FIRSTBOOT_MENU_CANDIDATE',run,flush=True)
                            break
                    else:
                        raise RuntimeError('Firstboot shooting readiness pending after 30 consumed navigation steps')
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
            if 'firstboot_readiness' in proof:
                proof['firstboot_readiness'].update(ready=False,reason=str(error))
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
            if not temp_owner.retain and child is not None:
                try:
                    close_launcher(child, geometry, env.get('A7C2_FUNCTIONAL_CAMERA') == FUNCTIONAL_CAMERA_PROFILE)
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
                    retain_resources('Launcher shutdown not confirmed; own GUI/VM retained, no SIGKILL: ' + str(error))
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
