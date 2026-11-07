#!/usr/bin/env python3
"""Owned prepared-runtime before/after probe; never attaches an existing VM.

Measures atomic input publication -> original receive -> semantic LCD file pixels.
It does not measure a GTK/Rust window's compositor presentation.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import signal
import statistics
import subprocess
import sys
import time

from PIL import Image, ImageChops, ImageStat

HERE=Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def save(path,value):
    temporary=path.with_suffix(path.suffix+'.next')
    temporary.write_text(json.dumps(value,indent=2)+'\n')
    temporary.replace(path)


def clone(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['cp','-a','--reflink=auto','--sparse=always',str(source),str(target)],check=True,timeout=55)


def prepare(source,output,baseline):
    if output.exists():raise ValueError('Refusing to overwrite an experiment')
    output.mkdir(parents=True)
    capacity=os.statvfs(output)
    if capacity.f_bavail*capacity.f_frsize<8*1024**3:raise RuntimeError('Need 8 GiB available for isolated copies')
    pin=json.loads((source/'runtime/native-input.json').read_text())['id']
    manifest={'source':str(source),'baseline_sha256':digest(baseline),'variants':{},
              'capture_verified':False,'physical_devices':False}
    relatives=['analysis/full-system.cpio','analysis/full-system.json','analysis/qemu-kernel-probe.sh',
        'analysis/boot-handoff.bin','analysis/boards/virt-four.dtb','analysis/qemu-virt-board/virt-packed.dtb',
        'analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin',
        'analysis/unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt','analysis/root/simulation',
        'native-input.json','native-source-snapshots/'+pin,'usb-qemu/qemu-system-aarch64','usb-qemu/manifest.json']
    for label in ('before','after'):
        code=output/label
        code.mkdir()
        for path in source.iterdir():
            if path.is_file() and path.suffix in ('.py','.c','.h','.inc','.S','.json','.ld'):
                shutil.copy2(path,code/path.name)
        if label=='before':shutil.copy2(baseline,code/'run-full-system.py')
        for name in relatives:clone(source/'runtime'/name,code/'runtime'/name)
        fdt='sources/qemu-tools/usr/lib/libfdt.so.1'
        (code/'runtime'/fdt).parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/'runtime'/fdt,code/'runtime'/fdt)
        (code/'input').mkdir(mode=0o700)
        probe=source.parent/'2026-11-06-ui-latency/ui_latency.py'
        shutil.copy2(probe,code/'latency_probe.py')
        manifest['variants'][label]={'runner_sha256':digest(code/'run-full-system.py'),
            'initrd_sha256':digest(code/'runtime/analysis/full-system.cpio'),
            'qemu_sha256':digest(code/'runtime/usb-qemu/qemu-system-aarch64'),
            'native_snapshot':pin,'source_files':{p.name:digest(p) for p in code.iterdir() if p.is_file()}}
        save(output/'identities.json',manifest)
    a,b=(manifest['variants'][label] for label in ('before','after'))
    if (a['initrd_sha256'],a['qemu_sha256'],a['native_snapshot'])!=(b['initrd_sha256'],b['qemu_sha256'],b['native_snapshot']):
        raise RuntimeError('Before/after assets differ')


def worker(code):
    # Per-process hooks only; copied sources and runtime retain their original guards.
    sys.path.insert(0,str(code))
    api=runpy.run_path(str(code/'run-full-system.py'))
    target=api['main'].__globals__
    probe=runpy.run_path(str(code/'latency_probe.py'))
    with (code/'trace.jsonl').open('x') as output:
        trace=probe['Trace'](output)
        probe['install_full_system'](api,trace)
        original_finish=target['finish_owned_run']
        def finish(process,result,out):
            if process is not None and process.poll() is None:
                identity=json.loads((out/'inputs.json').read_text())
                if identity['host_runner_pid']!=os.getpid() or not out.resolve().is_relative_to(code/'runtime/analysis/runs'):
                    raise RuntimeError('Foreign VM owner refused')
                sock,stream,call=target['qmp_open'](out/'qmp.sock')
                try:call('quit')
                finally:stream.close();sock.close()
                result['latency_probe_qmp_quit']=True
                result['latency_probe_vm_returncode']=process.wait(timeout=10)
            return original_finish(process,result,out)
        target['finish_owned_run']=finish
        # Original terminal checks remain; a normal QMP quit needs no VM signals.
        target['terminate_owned']=lambda process:process.wait(timeout=10)
        profile=json.loads((code/'profile.json').read_text())
        arguments=[]
        for key,value in profile.items():
            if value is None or value is False:continue
            arguments.append('--'+key.replace('_','-'))
            if value is not True:arguments.append(str(value))
        sys.argv=[str(code/'run-full-system.py'),*arguments]
        rc=api['main']()
        if trace.error:raise RuntimeError('Trace output failed: '+trace.error)
        return rc


def signature(path):
    data=path.read_bytes()
    with Image.open(io.BytesIO(data)) as source:
        if source.format!='PPM' or source.size!=(640,480):raise ValueError('Not an original QMP 640x480 PPM')
        image=source.convert('RGB')
    crop=image.crop((100,70,610,420))
    red,green,blue=crop.split()
    mask=ImageChops.multiply(red.point(lambda x:255 if x>160 else 0),green.point(lambda x:255 if x<120 else 0))
    mask=ImageChops.multiply(mask,blue.point(lambda x:255 if x<70 else 0))
    rows=[ImageStat.Stat(mask.crop((0,y,mask.width,y+1))).sum[0]/255 for y in range(mask.height)]
    count=sum(rows)
    return {'rgb_sha256':hashlib.sha256(image.tobytes()).hexdigest(),
        'crop_sha256':hashlib.sha256(crop.tobytes()).hexdigest(),
        'orange_pixels':count,'orange_y':sum((y+70)*n for y,n in enumerate(rows))/count if count else None},image


def run_variant(code,samples):
    profile=json.loads((code/'camera-profile.json').read_text())['experiment']
    profile.update(seconds=70,serial_diagnostic_seconds=30,observe_input=True,
        capture_osd_frames=False,live_frame_seconds=.4,stall_seconds=0,
        runtime=str(code/'runtime'),input_queue_dir=str(code/'input'))
    save(code/'profile.json',profile)
    result={'label':code.name,'samples':[],'state':'failed','load_before':list(os.getloadavg()),
            'logical_cpus':os.cpu_count(),'window_presentation_verified':False,'capture_verified':False}
    save(code/'measurements.json',result)
    process=None;run=None
    try:
        with (code/'launcher.log').open('xb') as log:
            process=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--worker',str(code)],
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        result['worker_pid']=process.pid
        def wait(predicate,seconds,what):
            deadline=time.monotonic()+seconds
            while time.monotonic()<deadline:
                value=predicate()
                if value:return value
                if process.poll() is not None:raise RuntimeError('Owned runner ended while waiting for '+what)
                time.sleep(.005)
            raise TimeoutError(what)
        def find_run():
            found=re.search(r'^FULLSYSTEM_RUN (.+)$',(code/'launcher.log').read_text(errors='replace'),re.M)
            return Path(found[1]) if found else None
        run=wait(find_run,45,'private run creation')
        if not run.resolve().is_relative_to(code/'runtime/analysis/runs'):raise ValueError('Foreign run path')
        result['run']=str(run);save(code/'measurements.json',result)
        console=run/'console.log';frame=run/'live-frame.ppm'
        def ready():
            if not frame.exists() or not console.exists():return None
            text=console.read_text(errors='replace')
            if not re.search(r'CREATE_SCREEN_ARGS .* id=0 count=565 ',text):return None
            state,image=signature(frame)
            return (state,image) if len(image.getcolors(307200) or [])>10 else None
        initial,_=wait(ready,85,'original shooting main screen and nonuniform frame')
        result['initial']=initial
        counter=0
        def submit(command):
            nonlocal counter
            counter+=1
            temporary=code/'input'/f'latency-{counter:04d}.tmp'
            temporary.write_text(command+'\n')
            submitted=time.monotonic_ns()
            request=temporary.with_suffix('.cmd');temporary.replace(request)
            published=time.monotonic_ns()
            return request.with_suffix('.out'),submitted,published
        def receipt(path):
            if not path.exists():return None
            raw=path.read_text(errors='replace')
            if not re.search(r'^MENU_DIAG_COMMAND_DONE_[^:\r\n]+:0\s*$',raw,re.M):
                raise RuntimeError('Original command receipt failed: '+raw[-1200:])
            return raw
        def epoch():
            path,_,_=submit('cat /tmp/ramfb-viewer.status')
            raw=wait(lambda:receipt(path),35,'original ramfb status receipt')
            values=re.findall(r'RAMFB_(SUBMITTED|RETAINED) [^\r\n]* seq=(\d+) pixel_source=(\d+) ',raw)
            if len(values)!=1:raise RuntimeError('Missing or ambiguous ramfb epoch: '+raw[-1200:])
            return {'event':values[0][0],'sequence':int(values[0][1]),'pixel_source':int(values[0][2])}
        previous_epoch=epoch()
        rust=(code/'camera-ui-rs-source.txt').read_text()
        command_format=re.search(r'fn input_command\([^\n]+\n\s*format!\("([^"\n]+)",status as u32\)',rust)[1]
        tap_format=json.loads('"'+re.search(r'fn send_key\([^\n]+\n\s*let command = format!\("((?:[^"\\]|\\.)*)",',rust)[1]+'"')
        keys=[('MENU',0x1ab),('DOWN',0x30),('UP',0x3),('DOWN',0x30),('UP',0x3),('MENU',0x1ab)][:samples]
        for index,(name,code_value) in enumerate(keys):
            before,_=signature(frame)
            text_before=console.read_text(errors='replace')
            offset=len(text_before)
            command=tap_format.format(command_format.format(1,code=code_value),command_format.format(0,code=code_value)).strip()
            response,started,published=submit(command)
            observation={'key':name,'submitted_ns':started,'published_ns':published,'before':before,
                'epoch_before':previous_epoch,'load':list(os.getloadavg())}
            on=off=target_at=None;target=None;image=None
            seen_mtime=None
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Runner ended during input sample')
                available=time.monotonic_ns()
                new=console.read_text(errors='replace')[offset:]
                for status in (1,0):
                    matched=re.search(rf'FULL_INPUT_RECEIVE [^\r\n]* code={code_value:#x} status={status} ',new)
                    if matched:
                        if status and on is None:on=available;observation['original_receive_on']=matched[0]
                        if not status and off is None:off=available;observation['original_receive_off']=matched[0]
                modified=frame.stat().st_mtime_ns
                if modified!=seen_mtime:
                    seen_mtime=modified
                    candidate,candidate_image=signature(frame)
                    changed=candidate['crop_sha256']!=before['crop_sha256']
                    if name=='MENU':semantic=(candidate['orange_pixels']>1000)!=(before['orange_pixels']>1000)
                    else:
                        direction=1 if name=='DOWN' else -1
                        semantic=(candidate['orange_pixels']>1000 and before['orange_pixels']>1000
                            and direction*(candidate['orange_y']-before['orange_y'])>1)
                    if on is not None and changed and semantic and target_at is None:
                        target_at=time.monotonic_ns();target=candidate;image=candidate_image
                if on is not None and off is not None and target_at is not None and receipt(response):break
                time.sleep(.005)
            else:
                observation.update(error='original receive/release or semantic new LCD frame missing',
                    on_observed_ns=on,off_observed_ns=off,target_observed_ns=target_at)
                result['samples'].append(observation);save(code/'measurements.json',result)
                raise TimeoutError(observation['error']+' for '+name)
            image.save(code/f'sample-{index:02d}-{name}.png')
            after_epoch=epoch()
            if after_epoch['pixel_source']<=previous_epoch['pixel_source']:
                raise RuntimeError('Original ramfb pixel epoch did not advance')
            records=[json.loads(line) for line in (code/'trace.jsonl').read_text().splitlines()]
            active=[r for r in records if r['host_ns']>=started]
            begin=next(r['host_ns'] for r in active if r['stage']=='input.serial.begin')
            end=next(r['host_ns'] for r in active if r['stage']=='input.serial.end')
            dumps=[r for r in active if r['stage']=='qmp.screendump.end' and r['host_ns']<=target_at]
            if not dumps:raise RuntimeError('Target frame has no new owned QMP completion')
            observation.update(target=target,epoch_after=after_epoch,
                on_observed_ns=on,off_observed_ns=off,target_observed_ns=target_at,
                queue_ms=(begin-published)/1e6,serial_ms=(end-begin)/1e6,
                publish_to_receive_observed_ms=(on-published)/1e6,
                publish_to_target_ms=(target_at-published)/1e6,
                receive_log_to_target_ms=(target_at-on)/1e6,
                command_receipt_verified=True,original_on_off_verified=True,
                pixel_change_and_semantic_target_verified=True,pixel_epoch_advanced=True)
            result['samples'].append(observation);previous_epoch=after_epoch
            save(code/'measurements.json',result)
            print(code.name,name,'publish_to_target_ms',observation['publish_to_target_ms'],flush=True)
            time.sleep(.15)
        result['state']='samples-completed'
        save(code/'measurements.json',result)
        process.wait(timeout=100)
        result['worker_returncode']=process.returncode
        terminal=json.loads((run/'result.json').read_text())
        result['terminal']=terminal
        if process.returncode or not terminal.get('latency_probe_qmp_quit') or terminal.get('latency_probe_vm_returncode')!=0:
            raise RuntimeError('Owned normal QMP exit/terminal checks failed')
        result['state']='passed'
    except BaseException as error:
        result['error']=f'{type(error).__name__}: {error}'
        if process is not None and process.poll() is None:
            # Interrupt the Python owner, whose copied cleanup sends normal QMP quit.
            process.send_signal(signal.SIGINT)
            try:process.wait(timeout=25)
            except subprocess.TimeoutExpired:result['owner_cleanup_pending']=True
        raise
    finally:
        result['load_after']=list(os.getloadavg())
        save(code/'measurements.json',result)
    return result


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--worker':return worker(Path(sys.argv[2]).resolve(strict=True))
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--samples',type=int,choices=(3,6),default=6)
    args=parser.parse_args()
    source=HERE.resolve()
    permitted=source.parents[3]/'analysis/scratch/a7c2-ui-latency-20261106'
    output=args.output.resolve()
    if not output.is_relative_to(permitted.resolve()):parser.error('Output must belong to the dedicated UI latency scratch directory')
    prepare(source,output,args.baseline.resolve(strict=True))
    rust=(source/'camera-ui-rs/src/main.rs').read_text()
    for label in ('before','after'):(output/label/'camera-ui-rs-source.txt').write_text(rust)
    results=[]
    for label in ('before','after'):
        try:results.append(run_variant(output/label,args.samples))
        except BaseException as error:
            save(output/'failure.json',{'variant':label,'error':f'{type(error).__name__}: {error}'})
            return 1
    summary={'scope':'Atomic command publication to original AP receive and semantic original QMP LCD file pixels',
        'window_presentation_verified':False,'capture_verified':False,'variants':{}}
    for result in results:
        values={}
        for metric in ['queue_ms','serial_ms','publish_to_receive_observed_ms','publish_to_target_ms','receive_log_to_target_ms']:
            data=sorted(sample[metric] for sample in result['samples'])
            values[metric]={'n':len(data),'median_ms':statistics.median(data),'p95_ms':data[-1]}
        summary['variants'][result['label']]=values
    summary['initial_crop_equal']=results[0]['initial']['crop_sha256']==results[1]['initial']['crop_sha256']
    save(output/'comparison.json',summary)
    print(json.dumps(summary,indent=2),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
