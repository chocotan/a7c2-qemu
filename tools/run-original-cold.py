#!/usr/bin/env python3
"""Run the isolated original RAM0/init/pivot route; no physical devices."""
import argparse
from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import runpy
import socket
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
ANALYSIS=ROOT/'runtime/analysis'
sys.path.insert(0,str(ANALYSIS))
from original_cold_boot import prepare,need,sha,verify_root_observation,original_menu_pixels,chinese_language_rows,verify_chain_log,product_input_bindings
import persistent_storage as storage
from menu_live import connect_in_run,serial_command,key_command


def navigate_main_menu(process,runtime,qmp):
    from PIL import Image
    checker=runpy.run_path(str(ANALYSIS/'check-natural-gtk-input.py'))
    directory=runtime/'navigation';directory.mkdir();latest=directory/'current.png';counter=0
    def console():return (runtime/'console.log').read_text(errors='replace')
    def refresh(label):
        nonlocal counter
        counter+=1;qmp('screendump',dict(filename='/out/navigation/current.ppm'))
        with Image.open(directory/'current.ppm') as opened:image=opened.convert('RGB')
        need(image.size==(640,480),'Wrong navigation LCD geometry');image.save(latest);image.save(directory/(str(counter).zfill(4)+'-'+label+'.png'))
        ui=checker['firstboot_frame'](image,console())
        if ui.get('content_page')=='shooting' and ui.get('screen_id')==0 and ui.get('screen_count')==565:
            screens=re.findall(r'CREATE_SCREEN_ARGS call=(\d+) id=(0x[0-9a-f]+|0) count=(\d+)',console())
            if len(screens)>=2 and int(screens[-2][1],0)==0x343 and any(int(row[1],0)==0x347 for row in screens):
                ui=dict(ui,page='shooting',reason='reviewed HUD pixels/current565/preceding343/actual347; optional tutorial variant')
        return dict(pixel_sha256=hashlib.sha256(image.tobytes()).hexdigest(),firstboot_ui=ui,original_menu_control_pixels=original_menu_pixels(image),language_rows=chinese_language_rows(image))
    def action(name,mouse=True):
        need(name in ('DOWN','UP','ENTER','DELETE','MENU'),'Unreviewed cold navigation input')
        data=serial_command(process,runtime/'console.log',key_command(name,True),timeout=30)
        with (directory/'submitted.raw').open('ab') as stream:stream.write(data)
    def wait(predicate,seconds=20):
        deadline=time.monotonic()+seconds
        while not predicate(None):
            need(process.poll() is None,'Original cold owner exited while navigating')
            if time.monotonic()>deadline:raise TimeoutError('Original cold page/input did not settle')
            time.sleep(.04)
    image=refresh('initial');language=None
    if image['firstboot_ui'].get('screen_id')==0x12d:
        navigation=[]
        for index in range(41):
            rows=image['language_rows']
            if rows['target'] is not None and rows['target']==rows['selected']:
                stable=refresh('chinese-selected-stable')
                if stable['pixel_sha256']==image['pixel_sha256'] and stable['language_rows']==rows:
                    language=dict(actual_simplified_chinese_glyphs_verified=True,actual_highlight_verified=True,direction_inputs=navigation);image=stable;break
                image=stable;continue
            need(index<40,'Original Chinese language selection budget exhausted')
            direction='UP' if rows['target'] is not None and rows['selected'] is not None and rows['target']<rows['selected'] else 'DOWN'
            code=0x3 if direction=='UP' else 0x30;offset=len(console());before=image;action(direction)
            def consumed(frame):
                current=console()[offset:]
                pressed='words=['+hex(code)+',0,0x1,0,0,0,0,0]'
                released='words=['+hex(code)+',0,0,0,0,0,0,0]'
                return pressed in current and released in current
            image=checker['wait_lcd_settled'](before,refresh,wait,'language-'+str(index),consumed)
            navigation.append(direction)
        need(language is not None,'Original Chinese glyph/highlight was not verified')
    steps=[]
    for index in range(24):
        step=checker['firstboot_step'](image,console,refresh,action,wait,lambda:latest,'setup-'+str(index));steps.append(step)
        (directory/'steps.json').write_text(json.dumps(steps,indent=2)+'\n')
        if step.get('ready'):break
        image=refresh('after-'+str(index))
    else:raise RuntimeError('Original cold setup step budget exhausted')
    hud=refresh('hud');shutil_copy=latest.read_bytes();(runtime/'shooting-hud.png').write_bytes(shutil_copy)
    offset=len(console());action('MENU');observed={}
    def menu_seen(_):
        image=refresh('menu');text=console()[offset:];previous=observed.get('image');observed['image']=image
        if image['firstboot_ui'].get('page')=='failed':raise RuntimeError('Original cold UI failure after MENU')
        screen=image['firstboot_ui'].get('screen_id')
        return image['original_menu_control_pixels'] and screen is not None and (screen in (0x2ca,0x2cb) or 0x500<=screen<=0x6ff) and previous is not None and previous['pixel_sha256']==image['pixel_sha256'] and bool(re.search(r'INPUT_EVENT32[^\n]+words=\[0x1ab,0,0,0,0,0,0,0\]',text))
    wait(menu_seen);(runtime/'original-menu.png').write_bytes(latest.read_bytes());menu_pixels=observed['image']['pixel_sha256'];offset=len(console());action('MENU');observed.clear()
    def hud_returned(_):
        image=refresh('menu-return');previous=observed.get('image');observed['image']=image
        return image['firstboot_ui'].get('page')=='shooting' and not image['original_menu_control_pixels'] and previous is not None and previous['pixel_sha256']==image['pixel_sha256'] and bool(re.search(r'INPUT_EVENT32[^\n]+words=\[0x1ab,0,0,0,0,0,0,0\]',console()[offset:]))
    wait(hud_returned);(runtime/'menu-return.png').write_bytes(latest.read_bytes())
    return dict(original_shooting_hud_verified=True,original_menu_enter_return_verified=True,original_menu_control_pixels_verified=True,stable_original_menu_pixels_sha256=menu_pixels,stable_original_hud_return_pixels_sha256=observed['image']['pixel_sha256'],language_navigation=language,firstsetup_steps=len(steps),normal_input_and_actual_lcd_required=True,capture_verified=False)


def cold_environment(live=False):
    environment=dict(os.environ) if live else runpy.run_path(str(ANALYSIS/'start-menu.py'))['profile_environment']({},natural_boot=True)
    environment.update(SONY_TIMER_MODEL='1',SONY_DMM_SERVICE='1',QEMU_SYSTEM_SOUND_OWNER='1',QEMU_PIN_CONTROL_MEMORY='1',MENU_RM_FILE='1',MENU_NATIVE_WINDOW='1',QEMU_NATIVE_DISPLAY='none',QEMU_UI_LIVE='1',QEMU_TIMEOUT_SECONDS='0',QEMU_TRACE_FLAGS='guest_errors,unimp',A7C2_ORIGINAL_COLD='original-init-v1')
    return environment


def bind_ram_qemu(environment):
    value=os.environ.get('A7C2_RAM_QEMU')
    if not value:return
    candidate=Path(value)
    need(candidate.is_absolute() and candidate.is_file() and not candidate.is_symlink(),'RAM QEMU candidate must be an absolute regular file')
    environment.update(QEMU_SYSTEM_DIR=str(candidate.parent),QEMU_SYSTEM_BINARY=candidate.name)


def usb_msc_environment(environment):
    environment['A7C2_USB_MSC']='1'
    for name in ('A7C2_SONY_USB_DEVICE','A7C2_USB_DEVICE_BUILD'):
        need(os.environ.get(name),'USB MSC requires explicit device profile and candidate receipt: '+name)
        environment[name]=os.environ[name]


def run(instance,output,seconds,*,live=False,ram_capture=None,ram_restore=None,built=None,leased=None,usb_msc=False,ram_session=False):
    need(not (ram_capture and ram_restore) and not (live and (ram_capture or usb_msc)),'RAM/MSC probes require their declared original-cold action')
    need(not (live and ram_restore) or ram_session,'Live RAM restore requires the explicit window mode')
    ram_session=bool(ram_session or ram_capture or ram_restore)
    need(not (usb_msc and (ram_capture or ram_restore)),'USB MSC excludes RAM migration')
    runtime=output if live else output/'run'
    environment=cold_environment(live)
    if usb_msc:usb_msc_environment(environment)
    if ram_session:
        from sony_usb_device import selected
        need(not selected(environment),'Sony USB device migration is not audited; disconnect and use a RAM-only session')
        environment['QEMU_RAM_SESSION']='1';bind_ram_qemu(environment)
    environment['QEMU_OUTPUT_DIR']=str(runtime)
    if built is None:built=prepare(instance,output/'build',environment)
    build_result=Path(built['ram0']).parent/'result.json'
    if not live:runtime.mkdir(mode=0o700)
    process=None;stream=None;connection=None;quit_attempted=False
    result=dict(schema='a7c2-product-original-init-cold-actual-v1',verified=False,guest_started=False,full_boot_verified=False,physical_devices_used=False,capture_verified=False,ram_capture_verified=False,ram_restore_verified=False,sony_wbi_resume_executed=False,build_result_sha256=sha(build_result))
    def save():
        temporary=output/'result.new';temporary.write_text(json.dumps(result,indent=2)+'\n');os.replace(temporary,output/'result.json')
    def qmp(command,arguments=None,pass_fd=None):
        nonlocal quit_attempted
        if command=='quit':
            need(not quit_attempted,'Quit already attempted');quit_attempted=True
        message=dict(execute=command)
        if arguments is not None:message['arguments']=arguments
        encoded=(json.dumps(message)+'\n').encode()
        if pass_fd is None:
            stream.write(encoded);stream.flush()
        else:
            need(command=='getfd' and type(pass_fd) is int and pass_fd>=0,'QMP descriptor passing is limited to getfd')
            connection.sendmsg([encoded],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,struct.pack('i',pass_fd))])
        while True:
            raw=stream.readline(65537);need(raw and len(raw)<65537,'Incomplete original-cold QMP reply');reply=json.loads(raw)
            if 'error' in reply:raise RuntimeError(str(reply['error']))
            if 'return' in reply:return reply
    with (storage.instance_lease(instance) if leased is None else nullcontext(leased)) as leased:
        selected_qemu=Path(environment.get('QEMU_SYSTEM_DIR',str(ANALYSIS.parent/'sources/qemu-11.1.2/build-sony-ui')))/environment.get('QEMU_SYSTEM_BINARY','qemu-system-aarch64')
        environment.update(storage.inherited_environment(leased,binary=selected_qemu if ram_session else None,
                                                           ram_state=ram_session))
        qemu_digest=sha(Path(environment['QEMU_SYSTEM_DIR'])/environment['QEMU_SYSTEM_BINARY'])
        restore_contract=None
        if ram_restore:
            from original_ram_restore import load_capture
            restore_contract=load_capture(ram_restore,leased,built,qemu_digest)
        else:
            need(storage.disk.hashed(leased['fd'])==built['derived_disk_sha256'],'Disk changed between original-cold preparation and the launch lease')
        need(sha(Path(built['ram0']))==built['ram0_sha256'],'Prepared original RAM0 changed before launch')
        need(sha(ANALYSIS/'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin')==built['kernel_sha256'],'Actual launcher kernel differs from the current disk p3 kernel')
        from sony_usb_device import environment as usb_environment,publish_context
        environment.update(usb_environment(environment,runtime))
        if ram_restore:environment['QEMU_RAM_INCOMING']='defer'
        else:environment.pop('QEMU_RAM_INCOMING',None)
        command=['bash',str(ANALYSIS/'qemu-kernel-probe.sh'),'4096',str(ANALYSIS/'qemu-virt-board/virt-packed.dtb'),'1','1',built['ram0']]
        with (runtime/'console.log').open('xb') as console,(runtime/'stderr.log').open('xb') as stderr:
            try:
                clean_environment={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','MENU_','SONY_','A7C2_','LD_'))}
                process=subprocess.Popen(command,cwd=ANALYSIS,env={**clean_environment,**environment},stdin=subprocess.PIPE,stdout=console,stderr=stderr,start_new_session=True,pass_fds=(leased['fd'],))
                result.update(guest_started=True,owner_pid=process.pid,command=command);save();print('ORIGINAL_COLD_STARTED',process.pid,output,flush=True)
                connection=socket.socket(socket.AF_UNIX);connection.settimeout(15);deadline=time.monotonic()+30
                while True:
                    try:connect_in_run(connection,runtime,'qmp.sock');break
                    except (FileNotFoundError,ConnectionRefusedError):
                        need(process.poll() is None and time.monotonic()<deadline,'Original cold QMP not available');time.sleep(.1)
                peer,uid,_=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                from continuous_lcd import ContinuousLCD
                need(uid==os.geteuid() and ContinuousLCD._descendant(peer,process.pid),'Original-cold QMP peer is not the owned QEMU descendant')
                result['qmp_peer_pid']=peer
                publish_context(environment,runtime,peer)
                stream=connection.makefile('rwb');need('QMP' in json.loads(stream.readline()),'Missing QMP greeting');qmp('qmp_capabilities')
                if ram_restore:
                    from original_ram_restore import restore,verify_restored,_disk
                    def restored_serial(command):
                        return serial_command(process,runtime/'console.log',command,timeout=30)
                    restored=restore(qmp,ram_restore,leased,restore_contract)
                    continued=verify_restored(qmp,process,runtime,restored_serial,restore_contract)
                    if live:
                        from original_cold_live import live_session
                        os.environ.update(environment)
                        result['live_session']=live_session(process,runtime,qmp,built,leased=leased,ram_enabled=True,build_result=build_result,restored=continued)
                        internal=result['live_session']['internal_storage']
                    else:internal=storage.prepare_shutdown(restored_serial,runtime)
                    resumed_disk=_disk(leased)
                    need(all(resumed_disk[key]==restore_contract['disk'][key] for key in ('dev','ino','bytes')),'Restored persistent disk identity changed')
                    result.update(ram_restore=restored,restored_continuation=continued,main_menu=continued,internal_storage=internal,
                                  resumed_disk=resumed_disk,resumed_disk_content_changed=resumed_disk['sha256']!=restore_contract['disk']['sha256'],
                                  ram_restore_verified=True,ram_capture_verified=bool(result.get('live_session',{}).get('ram_capture')),p7_root_observed=True,original_ap_draw_observed=True,verified=True)
                    return result
                deadline=time.monotonic()+seconds;observed=b''
                while time.monotonic()<deadline:
                    observed=(runtime/'console.log').read_bytes()
                    if b'Exception> ' in observed or b'Kernel panic' in observed:raise RuntimeError('Original cold firmware/kernel exception; raw log preserved')
                    if b'PRODUCT_COLD_BOOTIN_PREPARATION_MISSING' in observed or b'PRODUCT_COLD_INIT2_PREVIOUS_ATTEMPT_FAILED' in observed:
                        raise RuntimeError('Original init2 adapter preparation failed; AP was not admitted')
                    if b'PRODUCT_COLD_BOOTIN pid=' in observed and b'OBS FRAME_DRAW_RETURN' in observed:break
                    need(process.poll() is None,'Original cold owner exited during boot');time.sleep(.2)
                need(b'PRODUCT_COLD_BOOTIN pid=' in observed and b'OBS FRAME_DRAW_RETURN' in observed,'Original cold AP did not reach observed draw within budget')
                result['handoff_order']=verify_chain_log(observed)
                time.sleep(2)
                data=serial_command(process,runtime/'console.log',"echo PRODUCT_COLD_PROC_BEGIN; /bin/busybox cat /proc/1/cmdline /proc/1/mountinfo /proc/cmdline; /bin/busybox grep -E '^(Uid|Gid):' /proc/$$/status; echo PRODUCT_COLD_PROC_END",timeout=30)
                (runtime/'guest-root.raw').write_bytes(data)
                need(b'PRODUCT_COLD_PROC_END' in data,'Original root observation incomplete')
                result['root_observation']=verify_root_observation(data)
                need(b'COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512' in observed,'Original freeramdisk readback missing')
                from PIL import Image
                display_deadline=deadline
                while True:
                    qmp('screendump',dict(filename='/out/original-lcd.ppm'))
                    with Image.open(runtime/'original-lcd.ppm') as image:
                        need(image.size==(640,480),'Wrong original LCD geometry');rgb=image.convert('RGB')
                    if len(rgb.getcolors(640*480) or [])>5:break
                    need(time.monotonic()<display_deadline,'Original LCD has no meaningful color content');time.sleep(.2)
                rgb.save(runtime/'original-lcd.png');result['lcd_pixels_sha256']=hashlib.sha256(rgb.tobytes()).hexdigest()
                if live:
                    from original_cold_live import live_session
                    os.environ.update(environment)
                    result['live_session']=live_session(process,runtime,qmp,built,leased=leased,ram_enabled=ram_session,build_result=build_result)
                    result.update(original_ram_init_observed=True,original_init2_observed=True,p7_root_observed=True,original_ram0_release_verified=True,original_ap_draw_observed=True,ram_capture_verified=bool(result['live_session'].get('ram_capture')),internal_storage=result['live_session']['internal_storage'],verified=True)
                    return result
                result['original_input']=[]
                previous_pixels=result['lcd_pixels_sha256']
                for name,code in (('DOWN',0x30),('UP',0x3)):
                    offset=(runtime/'console.log').stat().st_size
                    raw=serial_command(process,runtime/'console.log',key_command(name,True),timeout=30)
                    (runtime/('input-'+name+'.raw')).write_bytes(raw)
                    deadline=time.monotonic()+5;edge_numbers=[]
                    while time.monotonic()<deadline:
                        text=(runtime/'console.log').read_bytes()[offset:].decode(errors='replace');events=[]
                        for number,words in re.findall(r'INPUT_EVENT32 n=(\d+) tid=\d+ words=\[([^]\r\n]+)\]',text):
                            try:values=[int(value,0) for value in words.split(',')]
                            except ValueError:continue
                            if values in ([code,0,1,0,0,0,0,0],[code,0,0,0,0,0,0,0]):events.append((int(number),values[2]))
                        if len(events)==2 and [value for _,value in events]==[1,0]:edge_numbers=[number for number,_ in events];break
                        time.sleep(.05)
                    need(len(edge_numbers)==2,'Original AP did not consume both input edges: '+name)
                    focus_deadline=time.monotonic()+10;last_pixels=None
                    while True:
                        qmp('screendump',dict(filename='/out/input-'+name+'.ppm'))
                        with Image.open(runtime/('input-'+name+'.ppm')) as frame:
                            pixels=hashlib.sha256(frame.convert('RGB').tobytes()).hexdigest();frame.save(runtime/('input-'+name+'.png'))
                        if pixels!=previous_pixels and pixels==last_pixels:break
                        need(time.monotonic()<focus_deadline,'Original input received but stable changed LCD focus missing: '+name)
                        last_pixels=pixels;time.sleep(.1)
                    result['original_input'].append(dict(key=name,original_received_edges=edge_numbers,lcd_pixels_sha256=pixels,changed=True,stable_changed_focus_verified=True));previous_pixels=pixels
                need(any(row['changed'] for row in result['original_input']),'Original input edges consumed but no LCD focus change')
                result['main_menu']=navigate_main_menu(process,runtime,qmp)
                if usb_msc:
                    from usb_msc import probe
                    result['usb_msc']=probe(process,runtime,qmp)
                result['internal_storage']=storage.prepare_shutdown(lambda command:serial_command(process,runtime/'console.log',command,timeout=30),runtime)
                result.update(original_ram_init_observed=b'PRODUCT_COLD_BEFORE_ORIGINAL_INIT' in observed,original_init2_observed=b'PRODUCT_COLD_INIT2 parent=' in observed,p7_root_observed=True,original_ram0_release_verified=True,original_ap_draw_observed=True,
                              verified=bool(not usb_msc or result['usb_msc'].get('msc_verified')))
                if ram_capture:
                    from original_ram_restore import capture,receipt_path
                    captured=capture(qmp,ram_capture,runtime,leased,lambda command:serial_command(process,runtime/'console.log',command,timeout=30),built,qemu_digest)
                    storage._save(receipt_path(ram_capture),captured)
                    result.update(ram_capture=captured,ram_capture_verified=True)
            except BaseException as error:
                result.update(verified=False,error=type(error).__name__+': '+str(error));print('ORIGINAL_COLD_ERROR',result['error'],flush=True)
            finally:
                from original_cold_live import saved_for_close
                if process is not None and process.poll() is None and stream is not None and (not live or saved_for_close(runtime)):
                    try:
                        reply=qmp('quit');process.wait(timeout=30);result['qmp_exit']=dict(qmp_quit_confirmed=True,reply=reply,returncode=process.returncode,signals_sent=[])
                    except BaseException as error:result['close_error']=type(error).__name__+': '+str(error)
                if stream is not None:stream.close()
                if connection is not None:connection.close()
                if process is not None:
                    if process.poll() is None:
                        result.update(owner_retained=True,verified=False);save()
                        print('ORIGINAL_COLD_OWNER_RETAINED lease-held no-signals',process.pid,flush=True)
                        while process.poll() is None:time.sleep(.5)
                    while True:
                        try:os.killpg(process.pid,0)
                        except ProcessLookupError:result['owner_group_exited']=True;break
                        if not result.get('descendants_retained'):
                            result.update(descendants_retained=True,verified=False);save()
                            print('ORIGINAL_COLD_DESCENDANTS_RETAINED lease-held no-signals',process.pid,flush=True)
                        time.sleep(.5)
                result['verified']=bool(result['verified'] and result.get('qmp_exit',{}).get('returncode')==0 and result.get('owner_group_exited'))
                save();print('ORIGINAL_COLD_RESULT',result['verified'],output,flush=True)
    return result


def ram_roundtrip(instance,output,seconds):
    """One source/target pair under one disk lease; no cold fallback."""
    from original_ram_restore import receipt_path
    output=Path(output).absolute();stream=output/'snapshot.qevm'
    environment=cold_environment();environment['QEMU_RAM_SESSION']='1';bind_ram_qemu(environment)
    built=prepare(instance,output/'build',environment)
    summary=dict(schema='a7c2-product-original-ram-roundtrip-v1',actual_ram_roundtrip_verified=False,
                 same_persistent_disk_lease=True,sony_wbi_resume_executed=False,full_boot_verified=False,capture_verified=False)
    def save():storage._save(output/'result.json',summary)
    save()
    with storage.instance_lease(instance) as leased:
        (output/'source').mkdir(mode=0o700)
        source=run(instance,output/'source',seconds,built=built,leased=leased,ram_capture=stream)
        summary.update(source_result_sha256=sha(output/'source/result.json'),source_verified=source['verified'])
        save()
        if not source['verified']:return summary
        (output/'target').mkdir(mode=0o700)
        target=run(instance,output/'target',seconds,built=built,leased=leased,ram_restore=stream)
        summary.update(target_result_sha256=sha(output/'target/result.json'),target_verified=target['verified'],
                       capture_receipt_sha256=sha(receipt_path(stream)))
        summary['actual_ram_roundtrip_verified']=bool(source['verified'] and target['verified'] and target.get('ram_restore_verified'))
        summary['status']='PASS_ORIGINAL_AP_RAM_ROUNDTRIP' if summary['actual_ram_roundtrip_verified'] else 'FAILED_PRESERVED'
        save()
    return summary


def main():
    parser=argparse.ArgumentParser();selection=parser.add_mutually_exclusive_group(required=True);selection.add_argument('--instance',type=Path);selection.add_argument('--new-instance',action='store_true',help='create an independent disk from this product official BODYDATA cache');parser.add_argument('--output',type=Path,required=True);parser.add_argument('--seconds',type=int,default=120);parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--ram-roundtrip',action='store_true',help='save original AP RAM, normally exit, restore on the same disk, and verify original MENU/LCD');parser.add_argument('--usb-msc',action='store_true',help='use the ordinary original AP USB cable and ENTER, then preserve actual MSC evidence');args=parser.parse_args()
    need(15<=args.seconds<=300,'Original-cold observation must be15..300 seconds');need(not args.output.exists(),'Fresh output required');need(not (args.prepare_only and (args.ram_roundtrip or args.usb_msc)),'RAM/MSC probes and prepare-only are exclusive');need(not (args.ram_roundtrip and args.usb_msc),'RAM roundtrip and USB MSC are exclusive')
    descriptor=os.open(ANALYSIS/'.menu-probe.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Another product session owns the build/run assets; no cold guest started') from None
        product_input_bindings()
        args.output=args.output.absolute();args.output.mkdir(mode=0o700,parents=True)
        if args.new_instance:args.instance=storage.ensure_instance(args.output/'storage')
        if args.prepare_only:
            env=runpy.run_path(str(ANALYSIS/'start-menu.py'))['profile_environment']({},natural_boot=True);prepare(args.instance,args.output/'build',env);print('ORIGINAL_COLD_PREPARED',args.output,flush=True);return 0
        if args.ram_roundtrip:
            return 0 if ram_roundtrip(args.instance,args.output,args.seconds)['actual_ram_roundtrip_verified'] else 1
        outcome=run(args.instance,args.output,args.seconds,**({'usb_msc':True} if args.usb_msc else {}))
        return 0 if outcome['verified'] else 1
    finally:os.close(descriptor)


if __name__=='__main__':raise SystemExit(main())
