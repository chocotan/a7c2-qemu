#!/usr/bin/env python3
"""Publish the CP's own 7-byte media-state packet and watch the real mount path.

Why this is not fabrication: the packet's producer is verified. CP `cpapp-b.bin`
(Thumb) at file offset `0xb0f4a0` builds `[02 00 00, enable, rm1, rm2, rm3]` and
sends it to OSAL SID `0x8028017c`; `mcmn_drv.ko`'s worker (`.text+0xfa8`) caches
those 7 bytes and replays them byte-for-byte to subscribers on cmd3
(`.text+0x11f8`/`+0x1240`). `byte1`/`byte2` are explicitly stored zero by the
producer, so nothing here is guessed.

What is modelled is only the CP-side publisher. Everything downstream -- mcmn's
cache/replay, MediaDetect's parse, appFw's event conversion, the mount sequence,
the mmc driver, Fsys -- is the original firmware doing its own work.

`media_io_verified` stays false unless the original driver really opened the card
and the original Fsys really wrote to it.
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
normalize_plan=MENU_PROBE['normalize_plan']

# byte3 enable candidates: the verified producer ORs bit0/1/2 per channel whose
# conversion ran, which is NOT the physical slot count -- so both are tried.
PACKETS=(
    ('all-channels-no-card',   (2,0,0,0x07,0x00,0x00,0x00)),
    ('all-channels-rm2-card',  (2,0,0,0x07,0x00,0x02,0x00)),
    ('two-channels-rm2-card',  (2,0,0,0x03,0x00,0x02,0x00)),
)

MARKERS=('sequence_media_mount','exec_mount','mcmn_drv_open','do_mmc_hw_open',
         'mmc_card_open','supply_bus_power','wait_card_state_stable','mmc_hw_ipsxwrp_init',
         'MCMND_INSERTEDMEDIA','FULL_MCMN','FULL_MMC_TRACE','mcmnd_api_setmediapower',
         'Fsys_WriteDirectFileAsync','ParseInternalMessage','InfraMediaDetect')


def packet_command(packet):
    return '/simulation/cp-rm-notify '+' '.join(str(byte) for byte in packet)


def notify_plan(at,step):
    """One publish per candidate packet, spaced so the guest can react.

    Each entry is a SINGLE command: the plan is split on ';', so a command
    containing ';' (e.g. "echo label; helper ...") breaks the entry into a
    timestamp-less fragment and the runner refuses the whole plan. The helper's
    own receipt prints the payload hex, which identifies the case.
    """
    plan=[];t=at
    for _label,packet in PACKETS:
        plan.append(f'{t:.1f}:{packet_command(packet)}')
        t+=step
    return plan


def verify_helper(runtime):
    """The guest binary must be the one built from the current source. Fail closed."""
    manifest=json.loads((runtime/'analysis/full-system.json').read_text())
    program=runtime/'analysis/root/simulation/cp-rm-notify'
    if not program.is_file():
        raise SystemExit('Rebuild the runtime: /simulation/cp-rm-notify is missing from '+str(program))
    if manifest.get('cp_rm_notify_source_sha256')!=hashlib.sha256((HERE/'cp-rm-notify.c').read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: cp-rm-notify.c changed since it was built')
    if manifest.get('cp_rm_notify_program_sha256')!=hashlib.sha256(program.read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: cp-rm-notify program identity differs from the manifest')
    return manifest['cp_rm_notify_program_sha256']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=820)
    parser.add_argument('--notify-at',type=float,default=500)
    parser.add_argument('--step',type=float,default=45)
    parser.add_argument('--insmod-policy',choices=('allow-list','media','media-rm','all'),default='media-rm',
                        help='media loads mmc_drv too; media-rm (default) keeps the MMC host driver out')
    parser.add_argument('--mmc-trace',type=lambda value:int(value,0),default=None,
                        help='optional QEMU_SONY_MMC_TRACE value for the virtual IPSXWRP window')
    parser.add_argument('--sony-iomap',choices=('off','sony'),default='sony',
                        help='sony maps the SCU/IPSXWRP window the MMC driver reads; without it mmc_drv oopses')
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    helper_sha256=verify_helper(runtime)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    plan=walk.split(';')
    plan.extend(normalize_plan(args.notify_at))
    plan.extend(notify_plan(args.notify_at,args.step))
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='cp-rm-notify-',dir=runtime/'analysis'))
    argv=configure(queue,args.seconds,True,official=True,key_plan=';'.join(plan))
    if '--insmod-policy' in argv:
        argv[argv.index('--insmod-policy')+1]=args.insmod_policy
    else:
        argv+=['--insmod-policy',args.insmod_policy]
    if args.mmc_trace is not None:
        argv+=['--mmc-trace',hex(args.mmc_trace)]
    if args.sony_iomap!='off':
        argv+=['--sony-iomap',args.sony_iomap]
    command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
             *argv,'--bluetooth-policy','original']
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
    result={'schema':'cp-rm-notify-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),'returncode':rc,
            'publisher_source':'modeled (CP cpapp-b.bin 0xb0f4a0 layout; producer not executed)',
            'insmod_policy':args.insmod_policy,
            'sony_iomap':args.sony_iomap,
            'mmc_trace':None if args.mmc_trace is None else hex(args.mmc_trace),
            'cp_rm_notify_program_sha256':helper_sha256,
            'packets':[{'label':label,'bytes':list(packet)} for label,packet in PACKETS],
            'markers':{},'sent_receipts':0,'experiment_valid':False,
            'mount_path_observed':False,'media_io_verified':False}
    for marker in MARKERS:
        count=len(re.findall(re.escape(marker),text))
        if count:result['markers'][marker]=count
    sent=re.findall(r'CP_RM_NOTIFY_SENT rc=(\d+)',text)
    result['sent_receipts']=len(sent)
    result['send_failures']=len([rc for rc in sent if rc!='0'])
    rejected=len(re.findall(r'CP_RM_NOTIFY_REJECT|CP_RM_NOTIFY_BAD_ARG|CP_RM_NOTIFY_USAGE',text))
    result['rejected_invocations']=rejected
    # Valid only if every candidate was actually accepted by the guest's own OSAL.
    result['experiment_valid']=bool(sent) and not result['send_failures'] and not rejected
    mount_seen=any(name in result['markers'] for name in
                   ('sequence_media_mount','exec_mount','mcmn_drv_open','do_mmc_hw_open','mmc_card_open'))
    result['mount_path_observed']=mount_seen
    out=run/'cp-rm-notify.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('CP_RM_NOTIFY '+str(out))
    print('  publisher source:',result['publisher_source'])
    print('  insmod policy:',args.insmod_policy,'mmc trace:',result['mmc_trace'],'sony iomap:',result['sony_iomap'])
    print('  guest send receipts:',result['sent_receipts'],'failures:',result['send_failures'])
    print('  mount path observed:',mount_seen)
    print('  markers:',result['markers'])
    print('  media_io_verified: False (needs the original driver + Fsys to write)')
    if not result['experiment_valid']:
        print('CP_RM_NOTIFY_INVALID no accepted publish')
        return 2
    return 0 if mount_seen else 1


if __name__=='__main__':raise SystemExit(main())
