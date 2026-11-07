#!/usr/bin/env python3
"""Run copied startup components with real F dependencies; no DS execution."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system-sound-source',type=Path,help='private original 66368B SysSound for the full table regression')
    parser.add_argument('--qemu-user',type=Path,help='explicit qemu-aarch64 enables original-glibc AArch64 executions')
    parser.add_argument('--original-root',type=Path,default=HERE/'runtime/analysis/root')
    parser.add_argument('--output',type=Path,help='new output directory; existing evidence is never overwritten')
    args=parser.parse_args()
    if args.system_sound_source:
        if hashlib.sha256(args.system_sound_source.read_bytes()).hexdigest()!='5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a':
            parser.error('System-sound source differs from the original')
    if args.qemu_user:
        if not args.qemu_user.is_file():parser.error('Explicit qemu-user executable missing')
        for name in ('libc-2.25.so','libpthread-2.25.so','ld-2.25.so'):
            if not (args.original_root/'lib'/name).is_file():parser.error('Original runtime library missing: '+name)
    if args.output:args.output.mkdir(parents=True,exist_ok=False);out=args.output.resolve()
    else:
        parent=HERE/'runtime/analysis/startup-component-tests';parent.mkdir(parents=True,exist_ok=True)
        out=Path(tempfile.mkdtemp(prefix='check-',dir=parent))
    audio=[HERE/'audio-device.c',HERE/'sound-table.c',HERE/'audio-capabilities.c',HERE/'system-sound-owner.c']
    aflags=['FULL_AUDIO_TEST','SYSTEM_SOUND_OWNER_LIBRARY']
    cases=[('dig',['FULL_DIG_LEVEL_TEST'],[HERE/'dig-level-device.c',HERE/'test-dig-level.c'],[]),
           ('dmm',['FULL_DMM_TEST'],[HERE/'dmm-device.c',HERE/'test-dmm-unit-size.c'],[]),
           *[(n,aflags,[*audio,HERE/t],[]) for n,t in [('sound-path','test-sound-path.c'),('beep','test-beep-volume.c'),('panel','test-panel-reverse.c')]],
           ('fork',[*aflags,'FULL_DMM_TEST','FULL_DIG_LEVEL_TEST'],[*audio,HERE/'dmm-device.c',HERE/'dig-level-device.c',HERE/'test-startup-owner-fork.c'],[]),
           ('F-audio-regression',aflags,[*audio,HERE/'test-audio.c'],[str(args.system_sound_source.resolve())] if args.system_sound_source else [])]
    record={'matrix_complete':False,'checks':[],'audio_tables_checked':bool(args.system_sound_source),
            'original_glibc_executions_enabled':bool(args.qemu_user),'camera_startup_verified':False,'actual_VM_run':False}
    if not args.qemu_user:print('STARTUP_TEST_SCOPE original-ABI skipped: no --qemu-user supplied',flush=True)
    if not args.system_sound_source:print('STARTUP_TEST_SCOPE full sound-table regression skipped: no --system-sound-source supplied',flush=True)
    def save():(out/'results.json').write_text(json.dumps(record,indent=2)+'\n')
    for name,defines,sources,extra in cases:
        variants=[('plain',['-O2']),('san',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]
        if args.qemu_user:variants.append(('original-abi',[]))
        for kind,flags in variants:
            exe=out/(name+'-'+kind)
            if kind=='original-abi':
                cmd=['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib',
                     '-O2','-mno-outline-atomics','-Wl,--no-undefined','-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
                     '-I',str(HERE),*['-D'+v for v in defines],*(['-DUNIT_MAIN_ARGV'] if name=='F-audio-regression' else []),
                     *map(str,sources),str(HERE/'test-support/startup-entry.c'),
                     *[str(args.original_root/'lib'/v) for v in ('libc-2.25.so','libpthread-2.25.so','ld-2.25.so')],'-o',str(exe)]
                run=[str(args.qemu_user.resolve()),'-L',str(args.original_root.resolve()),str(exe),*extra]
            else:
                cmd=['clang','-std=c11','-Wall','-Wextra','-Werror','-pthread','-I',str(HERE),*flags,*['-D'+v for v in defines],*map(str,sources),'-o',str(exe)]
                run=[str(exe),*extra]
            compiled=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
            item={'case':name,'kind':kind,'compile_argv':cmd,'compile_rc':compiled.returncode,'compile_stderr':compiled.stderr}
            record['checks'].append(item);save()
            if compiled.returncode:print(compiled.stderr,flush=True);compiled.check_returncode()
            result=subprocess.run(run,capture_output=True,text=True,timeout=30,env=dict(os.environ,
                ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
            item.update(run_argv=run,rc=result.returncode,stdout=result.stdout,stderr=result.stderr);save()
            print('F_STARTUP_COMPONENT',name,kind,'rc',result.returncode,flush=True)
            if result.returncode:print(result.stdout,result.stderr,flush=True);result.check_returncode()
    names={p for _,_,sources,_ in cases for p in sources}|{HERE/'audio-device.h',HERE/'dmm-device.h',HERE/'dig-level-device.h',HERE/'test-support/startup-entry.c'}
    record['source_sha256']={p.relative_to(HERE).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(names)}
    record['matrix_complete']=True;save();print('F_STARTUP_COMPONENTS_PASS',out,flush=True);return 0


if __name__=='__main__':raise SystemExit(main())
