#!/usr/bin/env python3
"""Run the original media stack against the IPSXWRP access recorder.

The recorder answers one constant value and implements no card behaviour, so a
successful boot here proves nothing about SD support. Its only purpose is to let
the ORIGINAL driver tell us which register offsets it touches and in what order,
which is independent evidence for the disassembly-derived contract.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=90)
    parser.add_argument('--values',type=lambda value:int(value,0),nargs='+',default=[0])
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    if any(not 0<=value<=0xffffffff for value in args.values):parser.error('--values must be u32')
    if not (runtime/'analysis').is_dir():raise SystemExit('not a runtime: '+str(runtime))
    adapter=(runtime/'analysis/qemu-kernel-probe.sh').read_text()
    if 'FULLSYSTEM_MMC_TRACE_ENV' not in adapter:
        raise SystemExit('Rebuild this runtime: MMC trace environment passthrough is absent')
    binary=HERE/'runtime/usb-qemu/qemu-system-aarch64'
    identity=json.loads((binary.parent/'manifest.json').read_text())
    if identity.get('board_layer_sha256')!=hashlib.sha256((HERE/'usb-qemu-board.py').read_bytes()).hexdigest():
        raise SystemExit('Rebuild the dedicated QEMU: board source differs from its manifest')
    if identity.get('program_sha256')!=hashlib.sha256(binary.read_bytes()).hexdigest():
        raise SystemExit('Dedicated QEMU binary differs from its manifest')
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    parent=runtime/'analysis/mmc-trace-experiments';parent.mkdir(exist_ok=True)
    experiment=Path(tempfile.mkdtemp(prefix='compare-',dir=parent))
    results=[]
    for value in args.values:
        queue=Path(tempfile.mkdtemp(prefix='input-',dir=experiment))
        command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
                 *configure(queue,args.seconds,True,official=True,key_plan=''),
                 '--bluetooth-policy','original','--sony-iomap','sony',
                 '--insmod-policy','media','--mmc-trace',hex(value)]
        run=None
        log=queue/'runner.log'
        with log.open('w') as output:
            process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            try:
                for line in process.stdout:
                    output.write(line);output.flush()
                    if line.startswith('FULLSYSTEM_RUN '):
                        run=Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
                rc=process.wait()
            finally:
                process.stdout.close()
        record={'value':hex(value),'runner_directory':str(queue),'rc':rc,
                'run':str(run) if run else None,'probe_verified':False,'media_io_verified':False}
        if run and (run/'console.log').is_file():
            if run.parent.resolve()!=(runtime/'analysis/runs').resolve():raise ValueError('Foreign run path')
            digest=hashlib.sha256((run/'console.log').read_bytes()).hexdigest()
            terminal=json.loads((run/'result.json').read_text())
            record['console_sha256']=digest
            summary=subprocess.run([sys.executable,'-B',str(HERE/'analyze-mmc-trace.py'),
                                    str(run),'--json'],capture_output=True,text=True)
            try:
                record['trace']=json.loads(summary.stdout)
                record['probe_verified']=(rc==0 and summary.returncode==0 and
                    record['trace'].get('trace_capture_verified') is True and
                    terminal.get('terminal_evidence_checked') is True and
                    terminal.get('terminal_console_sha256')==digest and
                    all(d['reset']==value for d in record['trace'].get('devices',[])))
            except json.JSONDecodeError:record['trace_error']=summary.stdout+summary.stderr
        results.append(record)
    manifest=experiment/'result.json'
    manifest.write_text(json.dumps(results,indent=2)+'\n')
    for record in results:
        trace=record.get('trace') or {}
        print(f"value={record['value']} rc={record['rc']} "
              f"accesses={trace.get('total_accesses')} distinct={trace.get('distinct_offsets')}"
              + ('' if 'trace' in record else f" ERROR={record.get('trace_error','')[:200]}"))
    print('MANIFEST '+str(manifest))
    return 0 if all(record['probe_verified'] for record in results) else 1


if __name__=='__main__':raise SystemExit(main())
