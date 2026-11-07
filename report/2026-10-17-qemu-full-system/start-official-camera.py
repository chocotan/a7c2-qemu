#!/usr/bin/env python3
"""Import bodydata/, apply overwrite/, prepare a separate official runtime, start UI.

Never falls back to a private-device dump. Explicit --attach-sd snapshots SD/ and
publishes a guest export only after its original flush/stop/recovery protocol.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
IMPORT=runpy.run_path(str(HERE/'import-bodydata.py'))
OVERWRITE=runpy.run_path(str(HERE/'overwrite-images.py'))
FACTORY=runpy.run_path(str(HERE/'factory-images.py'))


def verify_factory(path):
    if path.is_symlink():raise ValueError('Factory cache cannot be a link')
    manifest=json.loads(IMPORT['ordinary'](path/'manifest.json').read_text())
    if manifest.get('source')!='official-bodydata-derived' or manifest.get('bodydata_sha256')!=IMPORT['INPUT_SHA'] or \
       manifest.get('private_device_data_used') is not False or not manifest.get('factory_pp_unchanged'):
        raise ValueError('Factory provenance differs')
    names={FACTORY['image_name'](n) for n in (*FACTORY['PARTS'],'B0','B1')}
    if {r['name'] for r in manifest['images']}!=names or len(manifest['images'])!=19:raise ValueError('Incomplete factory cache')
    for row in manifest['images']:
        file=IMPORT['ordinary'](path/row['name'])
        if file.stat().st_size!=row['bytes'] or IMPORT['digest'](file)!=row['sha256']:raise ValueError('Factory cache image changed')
    if (path/'FACTORY-IMAGES-COMPLETE').read_text().strip()!=IMPORT['digest'](path/'manifest.json'):
        raise ValueError('Factory cache incomplete')
    return manifest


# Verified against the signed 2.01 factory images: the original 20B input frontend
# walks the whole first-setup wizard and then the shooting menu. Only real keys are
# sent; the auto-power-off window is ~60s after a screen is created, so the menu
# steps are packed into one window (see report/2026-10-19-official-first-setup).
FIRST_SETUP_WALK = [
    (70, 'ENTER'), (100, 'ENTER'), (130, 'ENTER'),
    # The camera-setup branch is the DELETE (trash) softkey, not a focus move.
    (160, 'DELETE'),
    (195, 'ENTER'), (235, 'ENTER'), (275, 'ENTER'), (315, 'ENTER'),
    # Auto-power-off temperature prompt defaults to "set"; choose "later" instead.
    (340, 'DOWN'), (365, 'ENTER'), (405, 'ENTER'), (445, 'ENTER'),
    # Shooting main screen reached. Everything below stays inside one 60s window.
    (452, 'MENU'), (455, 'DOWN'), (458, 'DOWN'), (461, 'DOWN'),
    (464, 'ENTER'), (468, 'MENU'), (476, 'MENU'),
]
KEY_CODES = {'ENTER': 0x1ac, 'DOWN': 0x30, 'UP': 0x3, 'MENU': 0x1ab,
             'RIGHT': 0x1af, 'LEFT': 0x15, 'DELETE': 0x1f8}


def desktop_storage_arguments(workspace, attach_sd):
    arguments = ['--config-workspace', str(workspace)]
    if attach_sd:
        arguments += ['--attach-sd', '--workspace', str(workspace)]
    return arguments


def first_setup_plan():
    plan = []
    for at, name in FIRST_SETUP_WALK:
        code = KEY_CODES[name]
        press = (f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 0x1 0x0 1 --pulse-ms 50')
        # ex_info is not the previous status; libObj computes previous itself.
        release = (f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 0x0 0x0 1')
        plan.append('%s:%s' % (at, press))
        # Pulse key-up happens in the guest after 50 ms; keep a redundant explicit
        # release for recovery, without relying on serial RTT to control the hold.
        plan.append('%s:%s' % (at + .5, release))
    return ';'.join(plan)


def find_mtools():
    """Locate an mtools bin directory already prepared under this runtime tree."""
    root=HERE/'runtime/analysis'
    for candidate in sorted(root.glob('mtools-*/extracted/usr/bin')):
        if (candidate/'mcopy').is_file() and (candidate/'mdel').is_file():return candidate
    return None


def find_factory_cache(root,builder_sha256):
    """Automatic reuse is limited to candidates built by the current builder."""
    for candidate in sorted(root.glob('candidate-*'),reverse=True):
        manifest=candidate/'manifest.json'
        if not manifest.is_file():continue
        if json.loads(IMPORT['ordinary'](manifest).read_text()).get('builder_source_sha256')==builder_sha256:
            return candidate
    return None


def apply_overwrite(factory,folder,output):
    if not any(folder.iterdir()):return factory
    # VM adapter files would otherwise be replaced again during preparation.
    for item in ('init','simulation','sbin/insmod'):
        if os.path.lexists(folder/item):raise ValueError('Overwrite collides with VM adapter path: /'+item)
    result=OVERWRITE['build'](factory/'mounts.json',folder,output=output,
        mtools_dir=str(find_mtools()) if find_mtools() else None,
        vfat_fmask=0o022,vfat_dmask=0o022)
    manifest=verify_factory(factory)
    records=[]
    for row in manifest['images']:
        modified=result['images'][row['image_id']]
        records.append({**row,'file':modified['file'],'sha256':modified['sha256'],
                        'bytes':(output/modified['file']).stat().st_size})
    manifest={**manifest,'images':records,'user_overwrite':{'manifest_sha256':IMPORT['digest'](output/'overwrite-manifest.json'),
               'operations':len(result['operations']),'signed_update_package':False,
               'files':[{'path':op['guest_path'],'sha256':op['after']['sha256']} for op in result['operations'] if op['after']['kind']=='file']},
               'camera_startup_verified':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return output


def sd_run_arguments(queue,seconds,plan):
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    # The explicit CP-equivalent publisher is a virtual input, not a mount ACK.
    steps=plan.split(';')
    steps.append('520.0:/simulation/cp-rm-notify 2 0 0 7 0 2 0')
    steps.sort(key=lambda step:float(step.partition(':')[0]))
    result=configure(queue,seconds,True,official=True,key_plan=';'.join(steps))
    if '--insmod-policy' in result:result[result.index('--insmod-policy')+1]='media-rm'
    else:result+=['--insmod-policy','media-rm']
    return [*result,'--bluetooth-policy','original','--file-media','card',
            '--card-export-at','600','--card-export-flush']


def run_with_sd(runtime,session,workspace,seconds,plan):
    sd=runpy.run_path(str(HERE/'sd-directory.py'))
    seed=session/'sd-input.fat'
    baseline=sd['pack'](workspace/'SD',seed)
    (session/'sd-baseline.json').write_text(json.dumps(baseline,indent=2)+'\n')
    subprocess.run([sys.executable,'-B',str(HERE/'build-full-system.py'),
                    '--runtime',str(runtime),'--card-seed',str(seed)],check=True)
    queue=session/'input';queue.mkdir()
    command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
             *sd_run_arguments(queue,seconds,plan)]
    run=None
    with (session/'sd-runner.log').open('w') as output:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            for line in process.stdout:
                output.write(line);output.flush();print(line,end='',flush=True)
                if line.startswith('FULLSYSTEM_RUN '):run=Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
            rc=process.wait()
        except BaseException:
            process.terminate();process.wait(timeout=30);raise
        finally:process.stdout.close()
    if rc:raise RuntimeError('SD guest run failed; original SD/ retained; see '+str(session/'sd-runner.log'))
    if run is None or run.parent.resolve()!=(runtime/'analysis/runs').resolve():
        raise ValueError('Missing or foreign SD guest run path')
    evidence=json.loads((run/'result.json').read_text())
    sync=sd['restore'](run/'card-image.bin',workspace/'SD',baseline,evidence)
    sync.update(source_run=str(run),terminal_console_sha256=evidence['terminal_console_sha256'],
                card_flush_lifecycle_verified=evidence['card_flush_lifecycle_verified'],
                capture_verified=False,card_persistence_verified=False)
    (session/'sd-sync.json').write_text(json.dumps(sync,indent=2)+'\n')
    session_manifest=json.loads((session/'session.json').read_text())
    session_manifest.update(sd_attached=True,sd_directory_sync_verified=True,
                            card_persistence_verified=False)
    (session/'session.json').write_text(json.dumps(session_manifest,indent=2)+'\n')
    print('SD_DIRECTORY_SYNC_VERIFIED '+str(session/'sd-sync.json'),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=Path.cwd())
    parser.add_argument('--input-dir',type=Path,help='Defaults to workspace/bodydata')
    parser.add_argument('--cache-dir',type=Path,help='Optional existing verified official cache; no private dump accepted')
    parser.add_argument('--factory-dir',type=Path,help='Optional completed official factory cache, verified before use')
    parser.add_argument('--fwtool',type=Path,default=HERE/'vendor/fwtool',help='Pinned fwtool source checkout (bundled in a release)')
    parser.add_argument('--import-python',type=Path,help='Python with pycryptodomex; default current interpreter')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--manage-settings',action='store_true',
                        help='open the stopped-camera Rust configuration manager, without starting a VM')
    parser.add_argument('--headless',action='store_true',help='Owned diagnostic run with real live PPM and private input queue, without desktop window')
    parser.add_argument('--attach-sd',action='store_true',
                        help='explicit virtual card from workspace/SD with original flush before directory export')
    parser.add_argument('--walk-first-setup',action='store_true',
                        help='Inject the verified first-setup walk plus a menu round-trip with real keys')
    parser.add_argument('--seconds',type=int,default=600)
    parser.add_argument('--key-plan',default='',
                        help='headless SECONDS:ACTION;... plan for an owned diagnostic instead of the first-setup walk')
    args=parser.parse_args()
    if args.manage_settings and (args.prepare_only or args.headless or args.attach_sd or args.walk_first_setup or args.key_plan):
        parser.error('--manage-settings is an offline UI mode and excludes guest-run options')
    if args.attach_sd and args.headless and (not args.walk_first_setup or args.seconds<650):
        parser.error('Headless --attach-sd requires --walk-first-setup --seconds >= 650')
    if args.attach_sd and args.prepare_only:
        parser.error('--attach-sd performs a guest export and cannot be combined with --prepare-only')
    if args.walk_first_setup and args.key_plan:
        parser.error('--walk-first-setup and --key-plan are mutually exclusive')
    if args.key_plan and not args.headless:
        parser.error('--key-plan requires --headless')
    if args.walk_first_setup and not args.headless:
        parser.error('--walk-first-setup currently requires --headless')
    if args.walk_first_setup and args.seconds<500:
        parser.error('--walk-first-setup requires --seconds >= 500')
    workspace=args.workspace.resolve();workspace.mkdir(parents=True,exist_ok=True)
    config=runpy.run_path(str(HERE/'workspace-config.py'))
    with config['locked'](workspace) as store:
        prepared=start_owned(args,workspace,store)
    if args.manage_settings:
        ui=HERE/'camera-ui-rs/target/release/camera-ui-rs'
        if not ui.is_file():raise RuntimeError('Build the Rust UI before managing settings')
        env={**os.environ,'CAMUI_CONFIG_WORKSPACE':str(workspace),
             'CAMUI_WORKSPACE_CONFIG_SCRIPT':str(HERE/'workspace-config.py'),
             'CAMUI_RESET_RUNTIME':str(prepared),
             'CAMUI_RESET_SCRIPT':str(HERE/'reset-derived-state.py')}
        # The prepare lease has ended; the UI backend reacquires both leases.
        manager=subprocess.Popen([str(ui),'--managed-close-on-eof'],env=env,stdin=subprocess.PIPE)
        print('WORKSPACE_SETTINGS_UI '+json.dumps({'ui_pid':manager.pid,'workspace':str(workspace),
              'runtime':str(prepared),'mode':'offline-settings'}),flush=True)
        try:
            rc=manager.wait()
            if rc:raise subprocess.CalledProcessError(rc,[str(ui)])
        finally:
            if manager.stdin is not None:manager.stdin.close()
            if manager.poll() is None:
                print('WORKSPACE_SETTINGS_CLOSE_PENDING: waiting for owned UI/backend completion',flush=True)
                while manager.poll() is None:
                    try:manager.wait(timeout=1)
                    except subprocess.TimeoutExpired:pass
                    except KeyboardInterrupt:pass
                print('WORKSPACE_SETTINGS_CLOSED ui_rc='+str(manager.returncode),flush=True)
    return prepared


def start_owned(args,workspace,store):
    state=workspace/'.a7c2';state.mkdir(exist_ok=True)
    sd_lock=None
    if args.attach_sd and args.headless:
        sd_lock=(state/'sd.lock').open('a')
        fcntl.flock(sd_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    for name in ('bodydata','overwrite','SD'):
        path=workspace/name
        if path.is_symlink():raise ValueError('Workspace directory cannot be a symlink: '+name)
        path.mkdir(exist_ok=True)
    shared_cache=HERE/'runtime/bodydata'/IMPORT['INPUT_SHA']
    cache=args.cache_dir.resolve() if args.cache_dir else (
        shared_cache if shared_cache.is_dir() else state/'official'/IMPORT['INPUT_SHA'])
    if cache.exists():IMPORT['verify_cache'](cache)
    else:
        print('CAMERA_PREPARE official-bodydata-import',flush=True)
        subprocess.run([str(args.import_python or sys.executable),'-I','-B',str(HERE/'import-bodydata.py'),
            '--input-dir',str((args.input_dir or workspace/'bodydata').resolve()),'--fwtool',str(args.fwtool.resolve()),
            '--output',str(cache)],check=True)
    if args.factory_dir:
        factory=args.factory_dir.resolve()
    else:
        builder_sha=hashlib.sha256((HERE/'factory-images.py').read_bytes()).hexdigest()
        factory=find_factory_cache(HERE/'runtime/factory-images',builder_sha) or state/'factory'/builder_sha[:16]
    if args.factory_dir and not factory.is_dir():raise ValueError('Explicit factory cache is not complete/present')
    if factory.exists():verify_factory(factory)
    else:
        print('CAMERA_PREPARE official-factory-images',flush=True)
        subprocess.run([sys.executable,'-I','-B',str(HERE/'factory-images.py'),'--cache',str(cache),
                        '--fwtool',str(args.fwtool.resolve()),'--output',str(factory)],check=True)
    sessions=state/'sessions';sessions.mkdir(exist_ok=True)
    session=Path(tempfile.mkdtemp(prefix='session-',dir=sessions))
    source=apply_overwrite(factory,workspace/'overwrite',session/'modified-images')
    runtime=session/'runtime'
    print('CAMERA_PREPARE runtime source=official-bodydata-derived',flush=True)
    subprocess.run([sys.executable,'-B',str(HERE/'prepare-full-system.py'),'--dump',str(source),
                    '--runtime',str(runtime),'--source-class','official-bodydata-derived'],check=True)
    manifest=json.loads((runtime/'analysis/full-system.json').read_text())
    if manifest['source']!='official-bodydata-derived' or manifest.get('bodydata_sha256')!=IMPORT['INPUT_SHA']:
        raise ValueError('Refusing a runtime without official-source provenance')
    (session/'session.json').write_text(json.dumps({'runtime':str(runtime),'source':str(source),
        'workspace':str(workspace),'sd_attached':False,'sd_bridge_requested':args.attach_sd,
        'camera_startup_verified':False},indent=2)+'\n')
    print('OFFICIAL_CAMERA_RUNTIME '+str(runtime),flush=True)
    if not args.attach_sd:print('SD_BRIDGE_PENDING: SD/ is not yet attached to this guest',flush=True)
    # Reload only the workspace generation saved by a completed original sync/export.
    # A corrupt or unverifiable generation refuses the start instead of silently
    # booting the factory defaults and looking like "settings were reset".
    identity=store.load_into(runtime)
    (session/'config-load.json').write_text(json.dumps({'generation':identity},indent=2)+'\n')
    print('WORKSPACE_CONFIG_LOADED '+(identity or 'factory-default'),flush=True)
    if args.manage_settings:
        print('WORKSPACE_SETTINGS_MANAGER '+str(runtime),flush=True)
        return runtime
    if not args.prepare_only:
        if args.attach_sd and args.headless:
            run_with_sd(runtime,session,workspace,args.seconds,first_setup_plan())
        elif args.headless:
            queue=session/'input';queue.mkdir()
            configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
            plan=first_setup_plan() if args.walk_first_setup else args.key_plan
            subprocess.run([sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
                            *configure(queue,args.seconds,True,official=True,key_plan=plan),
                            '--bluetooth-policy','original'],check=True)
        else:
            subprocess.run([sys.executable,'-B',str(HERE/'run-camera.py'),'--runtime',str(runtime),'--seconds',str(args.seconds),
                            '--official','--bluetooth-policy','original',
                            *desktop_storage_arguments(workspace,args.attach_sd),
                            '--workspace-lock-fd',str(store.fd)],
                           pass_fds=(store.fd,),check=True)


if __name__=='__main__':main()
