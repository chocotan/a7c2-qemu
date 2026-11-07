#!/usr/bin/env python3
"""Compare explicit register levels in serial, independently owned official runs.

QMP readback proves sandbox/device wiring. Later MMIO reads, module initialization,
RM activity and media I/O remain separate evidence; no card readiness is invented.
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


def detect_reads(console):
    # stderr MMIO logs can share a line with the guest serial prompt.
    return [m.group().decode() for m in re.finditer(
        rb'SONY_MEDIA_DETECT_READ count=\d+ offset=[0-9a-f]+ size=\d+ value=0x[0-9a-f]+',console)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=90)
    parser.add_argument('--values',type=lambda value:int(value,0),nargs='+',default=[0,0x01000000])
    parser.add_argument('--query-at',type=int,help='at this host observation second, query ORIGINAL mcmn config/state')
    args=parser.parse_args()
    if not 30<=args.seconds<=600:parser.error('--seconds must be in 30..600')
    if any(not 0<=v<=0xffffffff for v in args.values):parser.error('register values must fit u32')
    if args.query_at is not None and not 5<=args.query_at<args.seconds:
        parser.error('--query-at must be between 5 and the end of this observation')
    runtime=args.runtime.resolve(strict=True)
    manifest=json.loads((runtime/'analysis/full-system.json').read_text())
    if manifest.get('source')!='official-bodydata-derived':
        parser.error('this experiment requires a separately prepared official runtime')
    if args.query_at is not None:
        if manifest.get('mcmn_query_source_sha256')!=hashlib.sha256((HERE/'mcmn-query.c').read_bytes()).hexdigest():
            raise ValueError('Rebuild the native read-only mcmn client')
        program=runtime/'analysis/root/simulation/mcmn-query'
        if manifest.get('mcmn_query_program_sha256')!=hashlib.sha256(program.read_bytes()).hexdigest():
            raise ValueError('Native mcmn client binary differs')
    parent=runtime/'analysis/media-detect-experiments';parent.mkdir(exist_ok=True)
    experiment=Path(tempfile.mkdtemp(prefix='compare-',dir=parent))
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    rows=[]
    print('MEDIA_DETECT_COMPARISON '+str(experiment),flush=True)
    for index,value in enumerate(args.values):
        queue=experiment/f'input-{index}';queue.mkdir()
        plan=f'{args.query_at}:/simulation/mcmn-query' if args.query_at is not None else ''
        command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
                 *configure(queue,args.seconds,True,official=True,key_plan=plan),'--bluetooth-policy','original',
                 '--sony-iomap','sony','--insmod-policy','media','--media-detect',hex(value)]
        run=None
        with (experiment/f'runner-{index}.log').open('w') as log:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                for line in process.stdout:
                    log.write(line);log.flush();print(line,end='',flush=True)
                    if line.startswith('FULLSYSTEM_RUN '):run=Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
                rc=process.wait()
            except BaseException:
                process.terminate();process.wait(timeout=30);raise
            finally:process.stdout.close()
        row={'requested_u32':value,'runner_rc':rc,'run':str(run) if run else None}
        if run is not None:
            # Never claim a run via directory time or the global latest-run file.
            if run.parent.resolve()!= (runtime/'analysis/runs').resolve():
                raise ValueError('runner returned a path outside its declared runtime')
            console=(run/'console.log').read_bytes()
            result=json.loads((run/'result.json').read_text())
            digest=hashlib.sha256(console).hexdigest()
            row.update(console_sha256=digest,
                terminal_bound=result.get('terminal_evidence_checked') is True and
                               result.get('terminal_console_sha256')==digest,
                qmp_readback=result.get('media_detect_readback'),
                mmio_read_records=detect_reads(console),
                mmio_read_note='includes the runner QMP preflight read; not independently firmware-attributed',
                module_init={name:bool(re.search(rb'FULLSYSTEM_MODULE_RESULT '+name.encode()+rb' result=0\b',console))
                             for name in ('mcmn_drv','ms_drv','mmc_drv')},
                native_query_entries=[m.group().decode() for m in re.finditer(
                    rb'MCMN_QUERY_ENTRY rm=\d+ flags=(?:0x[0-9a-f]+|0) mmc_target=(?:0x[0-9a-f]+|0)',console)],
                native_query_statuses=[m.group().decode() for m in re.finditer(
                    rb'MCMN_QUERY_RESULT command=\d+ target=(?:0x[0-9a-f]+|0) service_status=(?:0x[0-9a-f]+|0)',console)],
                native_insert_states=[{'target':int(m[1],16),'enum':int(m[2])} for m in re.finditer(
                    rb'MCMN_QUERY_INSERT_STATE target=(0x[0-9a-f]+) enum=(\d+) not_card_io_proof=1',console)],
                card_recognized_verified=False,media_io_verified=False)
        rows.append(row)
        (experiment/'result.json').write_text(json.dumps(rows,indent=2)+'\n')
        if rc:raise RuntimeError('owned run failed; original evidence retained: '+str(run))
        if not row.get('terminal_bound') or not (row.get('qmp_readback') or {}).get('verified'):
            raise RuntimeError('terminal evidence/readback was not verified')
    print('MEDIA_DETECT_COMPARISON_RECORDED '+str(experiment/'result.json'),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
