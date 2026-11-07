#!/usr/bin/env python3
"""Use the firmware's OWN file media backend as the virtual SD card.

`libInfraMediaCommon.so` already contains a file-type media driver; the firmware
only refuses to use it because configuration item `EXISTMEDIADRIVER (0x69)` says a
real driver exists. `file-media-config.so` wraps the original `mcmn_param_init`,
lets it run, then sets 0x69 to 0 -- so the original `mcmn_init` selects the file
backend and `/dev/mmca` becomes the guest file `/image_mmca`.

The backend configuration and Front notification publisher are explicit virtual
inputs; the original Fsys/Mount/Open/Write code runs downstream.

Three evidence layers, in order:

1. the preload took effect  -> `FILE_MEDIA_CONFIG ... EXISTMEDIADRIVER=1->0 OMIT_WRITE=0`
2. the original mount used the file backend -> `FILE_MEDIA_FSYS op=Mount ... result=0`
3. the original firmware wrote to the card:
   * its own log shows `A:/...` opens, and
   * the guest's own sha256 of `/image_mmca` differs from the template we seeded
     (the card started as a known template, so a different digest means the
     firmware changed it).

Exported card images are independently checked with host fsck/mtools and the
runner's per-chunk transport checks. Flush/stop/recovery has a separate result.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent

# The original firmware's own media-path logging (not our preload).
CARD_PATH_MARKERS=('A:/PRIVATE/DATABASE','A:/PRIVATE/M4ROOT','A:/PRIVATE')
# Evidence that the file-backed RM/media provider started and was used.
RM_FILE_MARKERS=('RM_FILE_PRELOAD_START','RM_FILE_PRELOAD_FAILED','RM_FILE_PRELOAD_RESOLVE_FAILED',
                 'FULL_RM_FILE_STARTED','FULL_RM_FILE_FAILED','FULL_RM_FILE_REQUEST ', 
                 'FULL_RM_FILE_INITIAL_QUEUED ','FULL_RM_FILE_REPLY_QUEUED ')


def digest_probe_command(path='/image_mmca'):
    return f'/usr/bin/openssl dgst -sha256 {path}'


# The firmware's own directory entries. Finding these names inside the card bytes is
# something only the firmware writing FAT entries can produce -- our seed contains
# just SEED.TXT. One command, no ';' (the runner splits the plan on ';').
FIRMWARE_NAMES=('DATABASE','M4ROOT','MEDIAPRO')
SCAN_COMMAND=('busybox grep -a -o -e DATABASE -e M4ROOT -e MEDIAPRO /image_mmca '
              '| busybox sort | busybox uniq -c')


def plan_with_digest(walk, digest_at, scan_at=None):
    plan=walk.split(';')
    plan.append(f'{digest_at:.1f}:{digest_probe_command()}')
    plan.append(f'{scan_at if scan_at is not None else digest_at+6:.1f}:{SCAN_COMMAND}')
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    return plan


def card_names(text):
    """Names the firmware wrote into the card's directory entries."""
    found={}
    for name in FIRMWARE_NAMES:
        matches=re.findall(rf'^\s*(\d+)\s+{name}\s*$',text,re.M)
        if matches:found[name]=max(int(value) for value in matches)
    return found


def verified_goal(result):
    if result['returncode'] or result['vm_state']!='observation-completed':return False
    if result['seed'].get('source_unchanged') is True:
        return bool(result['preload_applied'] and result['mount_via_file_backend']
                    and result['seed'].get('source_unchanged')
                    and result['existing_database_opened'] and not result['card_changed']
                    and result['host_card_verified'] and result['card_flush_lifecycle_verified'])
    return bool(result['firmware_wrote_card'])


def existing_reads_verified(result,verified):
    return bool(result['preload_applied'] and result['mount_via_file_backend']
        and result['seed'].get('source_unchanged') is True
        and verified['matches_template'] and result['host_card_verified']
        and all(any(receipt['file']==file_id and receipt['verified']
                    for receipt in verified['read_matches']) for file_id in (1,2)))


def capture_gate_snapshots(log_path,include_sources=None,include_destination=None):
    if not log_path.is_file():
        return [{'verified':False,
                 'error':'key-plan.log not produced; guest did not reach diagnostic commands'}]
    gates=runpy.run_path(str(HERE/'capture-gates.py'))
    snapshots=[]
    for section in log_path.read_text(errors='replace').split('\n---\n'):
        if 'CAPTURE_GATE_BEGIN_system_mode' not in section:continue
        sources=include_sources if include_sources is not None else bool(
            re.search(r'^CAPTURE_GATE_BEGIN_usb_streaming_mode\r?$',section,re.M))
        destination=include_destination if include_destination is not None else bool(
            re.search(r'^CAPTURE_GATE_BEGIN_remote_still_save_destination\r?$',section,re.M))
        try:
            snapshot={'fields':gates['parse'](section,include_sources=sources,
                                            include_destination=destination),'verified':True}
            at=re.search(r'(?:^|\n)AT=([0-9.]+) CMD=',section)
            if at:snapshot['observation_seconds']=float(at[1])
            snapshots.append(snapshot)
        except ValueError as error:snapshots.append({'verified':False,'error':str(error)})
    return snapshots


HOTPLUG_UNMOUNT=re.compile(r'FILE_MEDIA_FSYS op=Unmount drive=(\d+) flags=(0x[0-9a-f]+) result=(-?\d+)')
HOTPLUG_MOUNT=re.compile(r'FILE_MEDIA_FSYS op=Mount path=(\S+) flags=(0x[0-9a-f]+) drive=(\d+) result=(-?\d+)')
HOTPLUG_READ=re.compile(r'FILE_MEDIA_READ pid=\d+ file=([12]) handle=([0-9a-f]+) generation=(\d+) '
                        r'offset=\d+ requested=\d+ actual=(\d+)')


def hotplug_verdict(text,snapshots,payloads,card_export_verified=None):
    """Did the original firmware unmount on removal and remount+re-read on reinsert?

    Every input here is a receipt the guest printed; nothing is inferred from the
    host's view of the card file. `filesystem_state_series` is reported but does
    not gate the verdict: the meaning of that model field after an unmount is not
    established, so demanding a particular transition would be a guess.
    """
    unmounts=[{'drive':int(drive),'flags':flags,'result':int(code),'at':match.start()}
              for match in HOTPLUG_UNMOUNT.finditer(text)
              for drive,flags,code in [match.groups()]]
    mounts=[{'path':m.group(1),'flags':m.group(2),'drive':int(m.group(3)),'result':int(m.group(4)),
             'at':m.start()} for m in HOTPLUG_MOUNT.finditer(text)]
    reads=[{'file':int(m.group(1)),'handle':m.group(2),'generation':int(m.group(3)),
            'actual':int(m.group(4)),'at':m.start()} for m in HOTPLUG_READ.finditer(text)]
    accepted=[entry for entry in unmounts if entry['result']==0]
    cut=accepted[0]['at'] if accepted else None
    remounts=[entry for entry in mounts if cut is not None and entry['at']>cut and entry['result']==0]
    first_remount=min((entry['at'] for entry in remounts),default=None)
    rereads=[entry for entry in reads
             if first_remount is not None and entry['at']>first_remount and entry['actual']>0]
    series=[]
    for snapshot in snapshots:
        fields=snapshot.get('fields') or {}
        if 'media_filesystem_mount_state_slot1' not in fields:continue
        series.append({'at':snapshot.get('observation_seconds'),
                       'media_state_slot1':fields['media_mount_state_slot1']['value'],
                       'filesystem_state_slot1':fields['media_filesystem_mount_state_slot1']['value'],
                       'media_state_slot2':fields['media_mount_state_slot2']['value'],
                       'filesystem_state_slot2':fields['media_filesystem_mount_state_slot2']['value']})
    verdict={'notify_payloads':payloads,
             'remove_payload_published':'02000007000000' in payloads,
             'reinsert_payload_published':'02000007000200' in payloads,
             'unmount_receipts':unmounts,'mount_receipts':mounts,
             'remounts_after_unmount':remounts,'reads_after_remount':rereads,
             'filesystem_state_observed':bool(series),'filesystem_state_series':series,
             'snapshots_verified':bool(snapshots) and all(s.get('verified') for s in snapshots)}
    verdict['card_export_verified']=card_export_verified
    verdict['hotplug_cycle_verified']=bool(
        verdict['remove_payload_published'] and verdict['reinsert_payload_published']
        and accepted and remounts and rereads and verdict['snapshots_verified']
        and card_export_verified is not False)
    return verdict


def read_receipts(text):
    pattern=(r'FILE_MEDIA_READ pid=(\d+) file=([12]) handle=([0-9a-f]+) generation=(\d+) '
             r'offset=(\d+) requested=(\d+) actual=(\d+) hashed=(\d+) fnv64=([0-9a-f]{16})')
    result=[]
    for pid,file,handle,generation,offset,requested,actual,hashed,fnv in re.findall(pattern,text):
        result.append(dict(pid=int(pid),file=int(file),handle=handle,generation=int(generation),
            offset=int(offset),requested=int(requested),actual=int(actual),hashed=int(hashed),fnv64=fnv))
    return result


def match_read(raw,receipt):
    offset,actual,count=receipt['offset'],receipt['actual'],receipt['hashed']
    if not (0<actual<=receipt['requested'] and count==min(actual,65536) and
            0<=offset<=len(raw) and offset+actual<=len(raw)):
        return False
    value=0xcbf29ce484222325
    for byte in raw[offset:offset+count]:value=((value^byte)*0x100000001b3)&0xffffffffffffffff
    return value==int(receipt['fnv64'],16)


def verify_card_image(path,template_sha256,reads=()):
    """Host-side check of the exported card: structure, contents, and whether it moved.

    A transport error would change the bytes; the seeded template is known, so an
    identical digest proves the export is faithful and the firmware wrote nothing.
    """
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    report={'sha256':sha,'bytes':path.stat().st_size,'matches_template':sha==template_sha256,
            'fsck_rc':None,'fsck_tail':None,'listing':None,'files':{},'read_matches':[]}
    fsck=shutil.which('fsck.fat') or shutil.which('fsck.vfat')
    if fsck:
        done=subprocess.run([fsck,'-n',str(path)],capture_output=True,text=True)
        report['fsck_rc']=done.returncode
        report['fsck_tail']=(done.stdout+done.stderr).strip()[-200:]
    for candidate in sorted((HERE/'runtime/analysis').glob('mtools-*/extracted/usr/bin')):
        mdir=candidate/'mdir'
        if not mdir.is_file():continue
        env={'PATH':str(candidate)+':/usr/bin','MTOOLS_SKIP_CHECK':'1'}
        done=subprocess.run([str(mdir),'-i',str(path),'::/'],capture_output=True,text=True,env=env)
        if done.returncode==0:report['listing']=done.stdout.strip()[-600:]
        with tempfile.TemporaryDirectory(prefix='card-check-') as temporary:
            for file_id,card_path in enumerate(('/PRIVATE/DATABASE/DATABASE.BIN','/PRIVATE/M4ROOT/MEDIAPRO.XML'),1):
                target=Path(temporary)/Path(card_path).name
                copied=subprocess.run([str(candidate/'mcopy'),'-i',str(path),'::'+card_path,str(target)],
                                      capture_output=True,env=env,timeout=30)
                if copied.returncode==0 and target.is_file():
                    raw=target.read_bytes()
                    report['files'][card_path]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                    for receipt in reads:
                        if receipt['file']==file_id:
                            report['read_matches'].append({**receipt,'path':card_path,
                                                          'verified':match_read(raw,receipt)})
        break
    return report


def verify_runtime(runtime):
    """Fail closed: the preload, its source and the template must be the built ones."""
    manifest=json.loads((runtime/'analysis/full-system.json').read_text())
    preload=runtime/'analysis/root/simulation/file-media-config.so'
    template=runtime/'analysis/root/simulation/media-template.fat'
    for path in (preload,template):
        if not path.is_file():raise SystemExit('Rebuild the runtime: missing '+str(path))
    if manifest.get('file_media_config_source_sha256')!=hashlib.sha256((HERE/'file-media-config.c').read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: file-media-config.c changed since it was built')
    if manifest.get('file_media_config_program_sha256')!=hashlib.sha256(preload.read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: file-media-config.so identity differs from the manifest')
    if manifest.get('file_media_template_source_sha256')!=hashlib.sha256((HERE/'file-media-template.py').read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: file-media-template.py changed since it was built')
    template_sha=hashlib.sha256(template.read_bytes()).hexdigest()
    if manifest.get('file_media_template_sha256')!=template_sha:
        raise SystemExit('Rebuild the runtime: media-template.fat identity differs from the manifest')
    return {'preload_sha256':manifest['file_media_config_program_sha256'],
            'template_sha256':template_sha,'seed':manifest.get('file_media_seed',{})}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=700)
    parser.add_argument('--digest-at',type=float,default=560)
    parser.add_argument('--packet',type=int,choices=(0,1,2),default=1,
                        help='which CP packet variant to publish when observing: '
                             '0=all-channels/no-card, 1=all-channels/RM2-card, 2=two-channels/RM2-card')
    parser.add_argument('--shutter-at',type=float,default=None,
                        help='after publishing the card packet, press the two-stage shutter at this second')
    parser.add_argument('--gates-at',type=float,nargs='+',default=[],
                        help='read original capture gate fields at these observation seconds')
    parser.add_argument('--gate-sources',action='store_true',
                        help='also read verified scalar and HAITA sources of capture inhibition')
    parser.add_argument('--gate-destination',action='store_true',
                        help='also read original recording destination, per-slot volume and HAITA inputs')
    parser.add_argument('--detect-observe',action='store_true',
                        help='also log the media-detect state machine (MediaInfo status transitions)')
    parser.add_argument('--publish-card',action='store_true',
                        help='publish the selected CP front-end packet without loading the observer')
    parser.add_argument('--query-at',type=float,default=None,
                        help='also run the read-only mcmn client (config + insert state) at this second')
    parser.add_argument('--card-export-at',type=float,default=None,
                        help='also export the whole card image to the host at this second '
                             '(enables host-side fsck/parse)')
    parser.add_argument('--card-export-flush',action='store_true',
                        help='require original Fsys flush and verified owner stop/resume during export')
    parser.add_argument('--insmod-policy',choices=('allow-list','media','media-rm','all'),default=None,
                        help='default: media-rm for card, allow-list for card-rm -- the ported RM '
                             'provider owns SID 0x80d9016e, so mcmn_drv must NOT be loaded')
    parser.add_argument('--adaptive',action='store_true',
                        help='drive first setup by recognising each screen instead of replaying the '
                             'fixed walk; the walk is fragile once a stored configuration changes it')
    parser.add_argument('--adaptive-interval',type=float,default=5.0)
    parser.add_argument('--adaptive-default',default='ENTER')
    parser.add_argument('--adaptive-default-after',type=float,default=40.0)
    parser.add_argument('--adaptive-stop-screen',default='shooting')
    parser.add_argument('--adaptive-seek',default=None,
                        help='after the startup phase, scroll the menu until this screen is recognised')
    parser.add_argument('--adaptive-seek-enter',action='store_true')
    parser.add_argument('--adaptive-seek-key',default='DOWN')
    parser.add_argument('--adaptive-seek-after',type=float,default=None)
    parser.add_argument('--command-at',action='append',default=[],
                        help='TIME:COMMAND -- run one guest command at that second (no semicolons)')
    parser.add_argument('--read-at',action='append',default=[],
                        help='TIME:HEXADDR -- read a 4-byte AppFw field at that second, e.g. 150:0x7eae168 '
                             'for the power-save state')
    parser.add_argument('--extra-keys',default='',
                        help='comma separated TIME:NAME presses injected after the startup phase, e.g. '
                             '"200:MENU,206:DOWN" -- used to reach a menu item on a live camera')
    parser.add_argument('--publish-at',type=float,default=500.0,
                        help='second at which the card packet is published. Keep it close to the '
                             'startup phase: an idle camera turns its screen off, and a dark camera '
                             'does not act on media events')
    parser.add_argument('--keep-awake-every',type=float,default=None,
                        help='open and close the menu every N seconds after the startup phase, so the '
                             'camera does not drop into power save before the card packet arrives')
    parser.add_argument('--sd-remove-at',type=float,default=None,
                        help='publish the verified no-card CP packet at this second (SD removal)')
    parser.add_argument('--sd-reinsert-at',type=float,default=None,
                        help='publish the verified rm2-card CP packet at this second (SD reinsertion)')
    parser.add_argument('--profile',choices=('card','card-rm'),default='card',
                        help='card: firmware file backend only (verified); card-rm: also load the '
                             'ported user-space RM provider (not stable yet)')
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    identity=verify_runtime(runtime)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    # The full card export supersedes the in-guest digest/scan: openssl over 128 MiB
    # inside TCG can exceed the serial command timeout (run-5ffqy5aw died that way),
    # and the exported image is stronger evidence anyway.
    if args.adaptive:
        plan=[]
    elif args.card_export_at is not None:
        plan=walk.split(';')
        plan.sort(key=lambda item:float(item.partition(':')[0]))
    else:
        plan=plan_with_digest(walk,args.digest_at)
    if args.detect_observe or args.publish_card:
        cp=runpy.run_path(str(HERE/'probe-cp-rm-notify.py'))['PACKETS']
        publish_at=args.publish_at
        if not 0 <= args.packet < len(cp):parser.error('packet index out of range')
        runpy.run_path(str(HERE/'probe-cp-rm-notify.py'))['verify_helper'](runtime)
        plan.extend(runpy.run_path(str(HERE/'probe-media-mount-action.py'))['normalize_plan'](publish_at))
        plan.append(f'{publish_at:.1f}:/simulation/cp-rm-notify '+' '.join(str(b) for b in cp[args.packet][1]))
        plan.sort(key=lambda item:float(item.partition(':')[0]))
    if args.shutter_at is not None:
        # Two-stage shutter from the body's raw->UIBIZ table: 0x1f1 half, 0xa7 full.
        for offset,(code,status) in enumerate(((0x1f1,1),(0xa7,1),(0xa7,0),(0x1f1,0))):
            plan.append(f'{args.shutter_at+offset*0.5:.1f}:/simulation/inject-key '
                        f'0x807a0020 0x92840747 {code:#x} 0 {status} 0 1')
        plan.sort(key=lambda item:float(item.partition(':')[0]))
    if args.query_at is not None:
        plan.append(f'{args.query_at:.1f}:/simulation/mcmn-query')
        plan.sort(key=lambda item:float(item.partition(':')[0]))
    hotplug=args.sd_remove_at is not None or args.sd_reinsert_at is not None
    if hotplug:
        # Removable-media state is published by the same verified CP front end the
        # single-packet probe uses, so the guest's own mcmn cache, MediaDetect and
        # mount sequence stay in charge.
        cp=runpy.run_path(str(HERE/'probe-cp-rm-notify.py'))
        cp['verify_helper'](runtime)
        for at,packet in ((args.sd_remove_at,cp['PACKETS'][0][1]),
                          (args.sd_reinsert_at,cp['PACKETS'][1][1])):
            if at is None:continue
            plan.append(f'{at:.1f}:/simulation/cp-rm-notify '+' '.join(str(byte) for byte in packet))
        plan.sort(key=lambda item:float(item.partition(':')[0]))
        if not args.gate_destination:
            parser.error('--sd-remove-at/--sd-reinsert-at need --gate-destination so the '
                         'filesystem mount state is sampled in the same run')
    gates=runpy.run_path(str(HERE/'capture-gates.py'))
    if args.gates_at:
        identity_manifest=json.loads((runtime/'analysis/full-system.json').read_text())
        for key,path in (('capture_gates_reader_source_sha256',HERE/'capture-gates-reader.c'),
                         ('capture_gates_reader_program_sha256',runtime/'analysis/root/simulation/capture-gates-reader')):
            if not path.is_file() or identity_manifest.get(key)!=hashlib.sha256(path.read_bytes()).hexdigest():
                raise RuntimeError('Rebuild the capture gate sampler before using the probe')
        if identity_manifest.get('capture_gates_fields_sha256')!=hashlib.sha256(gates['field_header']().encode()).hexdigest():
            raise RuntimeError('Rebuild the capture gate sampler field map')
    if args.extra_keys:
        codes={'ENTER':0x1ac,'DOWN':0x30,'UP':0x3,'MENU':0x1ab,'RIGHT':0x1af,'LEFT':0x15,
               'DELETE':0x1f8,'POWER':0x2}
        for entry in [item for item in args.extra_keys.split(',') if item.strip()]:
            when,_,name=entry.partition(':')
            if name.strip() not in codes:
                parser.error('unknown key name in --extra-keys: '+name)
            code=codes[name.strip()];at=float(when)
            plan.append(f'{at:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 0x1 0x0 1 --pulse-ms 50')
            plan.append(f'{at+0.5:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 0x0 0x0 1')
    for entry in args.command_at:
        when,_,command=entry.partition(':')
        if ';' in command:
            parser.error('--command-at must not contain a semicolon: '+entry)
        plan.append(f'{float(when):.1f}:{command.strip()}')
    for entry in args.read_at:
        when,_,address=entry.partition(':')
        # No ';' here: the key plan is split on it.
        plan.append(f'{float(when):.1f}:set -- $(busybox pidof im.elf) && '
                    f'/simulation/menu-readmem /proc/$1/mem {address} 4 appFw.so')
    if args.keep_awake_every:
        # An idle camera turns its screen off; a closed door does not accept media events.
        at=args.keep_awake_every
        while at < args.seconds - 10:
            plan.append(f'{at:.1f}:/simulation/inject-key 0x807a0020 0x92840747 0x1ab 0 0x1 0x0 1 --pulse-ms 50')
            plan.append(f'{at + 0.5:.1f}:/simulation/inject-key 0x807a0020 0x92840747 0x1ab 0 0x0 0x0 1')
            # Close it again quickly: a media event arriving with the menu open is
            # exactly the kind of state that made an earlier round silently ignore it.
            plan.append(f'{at + 1.5:.1f}:/simulation/inject-key 0x807a0020 0x92840747 0x1ab 0 0x1 0x0 1 --pulse-ms 50')
            plan.append(f'{at + 2.0:.1f}:/simulation/inject-key 0x807a0020 0x92840747 0x1ab 0 0x0 0x0 1')
            at += args.keep_awake_every
    for at in args.gates_at:
        plan.append(f'{at:.1f}:'+gates['command'](include_sources=args.gate_sources,
                                               include_destination=args.gate_destination))
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='file-media-',dir=runtime/'analysis'))
    policy=args.insmod_policy or ('allow-list' if args.profile=='card-rm' else 'media-rm')
    argv=configure(queue,args.seconds,True,official=True,key_plan=';'.join(plan))
    if '--insmod-policy' in argv:argv[argv.index('--insmod-policy')+1]=policy
    else:argv+=['--insmod-policy',policy]
    if args.card_export_at is not None:
        argv+=['--card-export-at',str(args.card_export_at)]
    if args.card_export_flush:argv.append('--card-export-flush')
    if args.adaptive:
        argv+=['--adaptive-first-setup','--adaptive-interval',str(args.adaptive_interval)]
        if args.adaptive_default:argv+=['--adaptive-default',args.adaptive_default]
        if args.adaptive_default_after is not None:
            argv+=['--adaptive-default-after',str(args.adaptive_default_after)]
        if args.adaptive_stop_screen:argv+=['--adaptive-stop-screen',args.adaptive_stop_screen]
        if args.adaptive_seek:
            argv+=['--adaptive-seek',args.adaptive_seek]
            argv+=['--adaptive-seek-key',args.adaptive_seek_key]
            if args.adaptive_seek_enter:argv.append('--adaptive-seek-enter')
            if args.adaptive_seek_after is not None:
                argv+=['--adaptive-seek-after',str(args.adaptive_seek_after)]
    if args.detect_observe: argv.append('--detect-observe')
    command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
             *argv,'--bluetooth-policy','original','--file-media',args.profile]
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
    result={'schema':'file-media-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),'returncode':rc,
            'backend':'firmware file media driver (EXISTMEDIADRIVER flipped after the original init)',
            'preload_sha256':identity['preload_sha256'],
            'template_sha256':identity['template_sha256'],
            'seed':identity['seed'],
            'profile_seen':False,'preload_applied':False,'rm_provider_started':False,
            'mount_via_file_backend':False,
            'card_path_markers':{},'rm_file_markers':{},'guest_card_sha256':None,'card_changed':False,
            'card_names':{},
            'firmware_wrote_card':False,'host_card_verified':False}
    result['profile']=args.profile
    result['front_notification_source']='virtual CP publisher; original CP firmware not executed'
    result['front_notification_payloads']=re.findall(
        r'CP_RM_NOTIFY_SEND destination=0x8028017c bytes=7 payload=([0-9a-f]{14})',text)
    result['capture_gate_snapshots']=[]
    if args.gates_at:
        result['capture_gate_snapshots']=capture_gate_snapshots(run/'key-plan.log',
            include_sources=args.gate_sources,include_destination=args.gate_destination)
    result['capture_context_verified']=bool(args.shutter_at is not None and args.gates_at
        and len(result['capture_gate_snapshots'])==len(args.gates_at)
        and all(gates['still_capture_context'](snapshot) for snapshot in result['capture_gate_snapshots']))
    result['insmod_policy']=policy
    result['profile_seen']='FULLSYSTEM_FILE_MEDIA_PROFILE='+args.profile in text
    applied=re.findall(r'FILE_MEDIA_CONFIG call=(\d+) pid=\d+ EXISTMEDIADRIVER=(\d+)->(\d+) OMIT_WRITE=(\d+)',text)
    result['preload_applied']=any(before!='0' and after=='0' and omit=='0'
                                 for _call,before,after,omit in applied)
    mounts=re.findall(r'FILE_MEDIA_FSYS op=Mount path=(\S+) flags=(0x[0-9a-f]+) drive=\d+ result=(-?\d+)',text)
    result['mounts']=[{'path':path,'flags':flags,'result':int(code)} for path,flags,code in mounts]
    result['mount_via_file_backend']=any(int(code)==0 for _p,_f,code in mounts)
    opened=re.findall(r'FILE_MEDIA_FSYS op=Open path=(\S+) flags=(0x[0-9a-f]+) handle=[0-9a-f]+ result=(-?\d+)',text)
    result['opened_files']=[{'path':path,'flags':flags,'result':int(code)} for path,flags,code in opened]
    result['existing_database_opened']=bool(identity['seed'].get('source_unchanged') and
        all(any(int(code)==0 and path==required for path,_flags,code in opened) for required in
            ('A:/PRIVATE/DATABASE/DATABASE.BIN','A:/PRIVATE/M4ROOT/MEDIAPRO.XML')))
    # Open alone does not prove the original application read/parsed the old bytes.
    result['existing_database_consumed']=False
    result['read_receipts']=read_receipts(text)
    for marker in CARD_PATH_MARKERS:
        count=len(re.findall(re.escape(marker),text))
        if count:result['card_path_markers'][marker]=count
    for marker in RM_FILE_MARKERS:
        count=len(re.findall(re.escape(marker),text))
        if count:result['rm_file_markers'][marker]=count
    result['rm_provider_started']='FULL_RM_FILE_STARTED' in text and 'RM_FILE_PRELOAD_FAILED' not in text
    digests=re.findall(r'SHA2?256\(([^)]*)\)=\s*([0-9a-f]{64})',text)
    guest=[value for name,value in digests if '/image_mmca' in name]
    result['guest_card_sha256']=guest[-1] if guest else None
    result['card_changed']=bool(result['guest_card_sha256']) and result['guest_card_sha256']!=result['template_sha256']
    for name in ('MCMN_QUERY_RESULT','MCMN_QUERY_INSERT_STATE','MCMN_QUERY_ENTRY','MCMN_QUERY_INCOMPLETE'):
        hits=re.findall(rf'{name}[^\r\n]{{0,110}}',text)
        if hits:result.setdefault('mcmn',{})[name]=hits[:6]
    for name in ('DETECT_OBSERVE_SND','DETECT_OBSERVE_CAPTURE_PROBE_UNRESOLVED',
                 'DETECT_OBSERVE_GETVALUE','DETECT_OBSERVE_CMD3',
                 'DETECT_OBSERVE_PARSE_RM','DETECT_OBSERVE_PARSE_RM_AFTER','DETECT_OBSERVE_PARSE_BASE',
                 'DETECT_OBSERVE_UPDATE_AFTER','DETECT_OBSERVE_START_IN_OUT',
                 'DETECT_OBSERVE_RESOLVE_FAILED','DETECT_OBSERVE_UPDATE_MISSING_ORIGINAL'):
        hits=re.findall(rf'{name}[^\r\n]{{0,220}}',text)
        if hits:result.setdefault('detect_observe',{})[name]=hits[:6]
    result['card_names']=card_names(text)
    # Layer 3: the card bytes changed AND carry the firmware's own directory names.
    # Either alone is weaker: a changed digest could be anything, and a name could be
    # left over from a previous card, so both are required.
    result['firmware_wrote_card']=bool(result['card_path_markers']) and result['card_changed'] \
        and bool(result['card_names'])
    out=run/'file-media.json'
    card_image=run/'card-image.bin'
    result['card_image_path']=str(card_image) if card_image.is_file() else None
    if card_image.is_file():
        result['card_verification']=verify_card_image(card_image,result['template_sha256'],result['read_receipts'])
    vm_result=json.loads((run/'result.json').read_text())
    result['vm_state']=vm_result.get('state')
    result['card_image_sha256_exported']=vm_result.get('card_image_sha256')
    result['snapshot_integrity_verified']=vm_result.get('card_snapshot_integrity_verified',False)
    result['card_flush_lifecycle_verified']=vm_result.get('card_flush_lifecycle_verified',False)
    result['card_flush_recovery']=vm_result.get('card_flush_recovery')
    result['card_persistence_verified']=False
    result['existing_database_read_verified']=False
    verified=result.get('card_verification',{})
    if verified:
        result['card_changed']=not verified['matches_template']
        # A FAT entry read from an exported card is stronger than a path printed in a log.
        files=verified['files']
        result['firmware_wrote_card']=bool(result['preload_applied'] and result['mount_via_file_backend']
            and result['card_changed'] and verified['fsck_rc']==0
            and all(files.get(path,{}).get('bytes',0)>0 for path in
                ('/PRIVATE/DATABASE/DATABASE.BIN','/PRIVATE/M4ROOT/MEDIAPRO.XML')))
        result['host_card_verified']=bool((result['firmware_wrote_card'] or result['existing_database_opened'])
            and result['snapshot_integrity_verified'] and verified['fsck_rc']==0
            and verified['sha256']==result['card_image_sha256_exported']
            and vm_result.get('state')=='observation-completed')
        result['existing_database_read_verified']=existing_reads_verified(result,verified)
    result['probe_goal']='seed-open-and-preserve' if result['seed'].get('source_unchanged') is True else 'fresh-card-write'
    result['probe_verified']=verified_goal(result)
    if hotplug:
        exported=None if args.card_export_at is None else bool(result.get('host_card_verified'))
        result['hotplug']=hotplug_verdict(text,result['capture_gate_snapshots'],
            result['front_notification_payloads'],exported)
        result['probe_goal']='sd-hotplug-cycle'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('FILE_MEDIA '+str(out))
    print('  profile seen:',result['profile_seen'])
    print('  preload applied (EXISTMEDIADRIVER 1->0, OMIT_WRITE=0):',result['preload_applied'])
    print('  original mount via file backend:',result['mount_via_file_backend'],result['mounts'][:3])
    print('  RM provider started:',result['rm_provider_started'],result['rm_file_markers'])
    print('  card path markers:',result['card_path_markers'])
    print('  guest card sha256:',result['guest_card_sha256'],'changed:',result['card_changed'])
    print('  card names written by the firmware:',result['card_names'])
    print('  firmware wrote the card:',result['firmware_wrote_card'])
    print('  verification goal:',result['probe_goal'],'verified:',result['probe_verified'])
    if result.get('hotplug'):
        hot=result['hotplug']
        print('  hotplug: remove_payload=%s reinsert_payload=%s unmount=%s remount=%s rereads=%s verified=%s' % (
            hot['remove_payload_published'],hot['reinsert_payload_published'],
            len(hot['unmount_receipts']),len(hot['remounts_after_unmount']),
            len(hot['reads_after_remount']),hot['hotplug_cycle_verified']))
        for row in hot['filesystem_state_series']:
            print('  hotplug fs state at',row['at'],'slot1 media=%s filesystem=%s' % (
                row['media_state_slot1'],row['filesystem_state_slot1']))
    print('  exported card image:',result['card_image_path'])
    if result.get('card_verification'):
        v=result['card_verification']
        print('  host check: sha=%s matches_template=%s fsck_rc=%s' % (v['sha256'][:16],v['matches_template'],v['fsck_rc']))
    if result.get('detect_observe'):
        for name,lines in result['detect_observe'].items():
            print('  detect',name,':',lines[0][:170])
    if not result['preload_applied']:
        print('FILE_MEDIA_INVALID preload did not take effect')
        return 2
    if rc:return rc
    if result.get('hotplug') and not result['hotplug']['hotplug_cycle_verified']:return 1
    return 0 if result['probe_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
