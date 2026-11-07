#!/usr/bin/env python3
"""Start one owned F VM and connect its Rust UI to that exact run."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import queue
import runpy
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent


# The original sequence_boot walks the Dataflow pin topology before it draws the
# first-setup page, so the official route needs these explicit, Get-only owners.
# None of them produces pixels, Connect acceptances or CP state.
OFFICIAL_REGISTRIES = dict(infrabb_service='registry', drawinfo_service='registry',
                           grm_pin_service='registry', vef_service='registry',
                           pin_format='cold', pin_connection='control',
                           infrabb_connection='control')


def configuration(input_dir, seconds, observe_input=False, official=False, key_plan=''):
    experiment = json.loads((HERE/'camera-profile.json').read_text())['experiment']
    for name in list(experiment):
        if name.startswith('until_'):
            experiment[name] = False
    experiment.update(seconds=seconds, stall_seconds=0, stacks=False, fatal_probe=False,observe_input=observe_input,
                      observe_uart_input=False, probe_uart_rx=False, probe_uart_command=False,
                      observe_upm_notify=False, dig_level='virtual', dmm_service='unit-size',
                      hdmi_connection='control', adf_audio_connection='control',
                      osd_headless='on', tcg_thread='multi', capture_osd_frames=False,
                      insmod_policy='media-rm', native_display='none', live_frame_seconds=.4,
                      key_plan=key_plan, key_after_marker='', input_queue_dir=str(input_dir))
    if official:
        # Only explicit profiles so an omitted flag still means "off" elsewhere.
        experiment.update(OFFICIAL_REGISTRIES)
    argv = []
    for key, value in experiment.items():
        if value is None or value is False:
            continue
        argv.append('--'+key.replace('_','-'))
        if value is not True:
            argv.append(str(value))
    return argv


def request_card_save(input_dir):
    temporary=Path(input_dir)/'save-card-and-exit.next'
    with temporary.open('xb') as output:
        output.write(b'A7C2_SAVE_CARD_AND_EXIT_V1\n');output.flush();os.fsync(output.fileno())
    temporary.replace(Path(input_dir)/'save-card-and-exit.request')


def stop_input_producer(ui,input_dir):
    if ui.poll() is None:
        ui.terminate()
        try:ui.wait(timeout=5)
        except subprocess.TimeoutExpired:ui.kill();ui.wait(timeout=5)
    else:ui.wait(timeout=5)
    temporary=Path(input_dir)/'input-producer-stopped.next'
    with temporary.open('xb') as output:
        output.write(b'A7C2_INPUT_PRODUCER_STOPPED_V1\n');output.flush();os.fsync(output.fileno())
    temporary.replace(Path(input_dir)/'input-producer-stopped')


def wait_ui_or_save(ui,vm,input_dir,save_enabled):
    while ui.poll() is None and vm.poll() is None:
        if save_enabled and (Path(input_dir)/'input-quiesce.request').exists():
            stop_input_producer(ui,input_dir)
            return True
        time.sleep(.2)
    return False


def wait_for_card_save(vm,input_dir,timeout=180):
    if vm.poll() is None:
        if not (Path(input_dir)/'input-quiesce.request').exists():
            request_card_save(input_dir)
        print('SESSION_SAVE_PENDING: waiting for original save/export/recovery',flush=True)
        return vm.wait(timeout=timeout)
    return vm.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--runtime',type=Path,default=HERE/'runtime')
    parser.add_argument('--firmware-context',type=Path,help='explicit owned context for the persistent firmware-development instance')
    parser.add_argument('--observe-input',action='store_true',help='Read-only mirror of original receive/free-entry, bounded by native observer')
    parser.add_argument('--low-latency-input',choices=('uart','mailbox-v1'),default='uart',help='explicit prepared input transport; original firmware consumes both profiles')
    parser.add_argument('--lcd-stream-fps',type=int,choices=(0,20,25,30,50),default=0,help='owned continuous LCD transport; requires the prepared stream helper')
    parser.add_argument('--official',action='store_true',help='Use the explicit official first-setup pin profiles')
    parser.add_argument('--bluetooth-policy',choices=('original','off'),help='Override the offline research profile; original preserves supplied settings')
    parser.add_argument('--ui', type=Path, default=HERE/'camera-ui-rs/target/release/camera-ui-rs')
    parser.add_argument('--attach-sd',action='store_true',help='save workspace/SD through original flush before exit')
    parser.add_argument('--config-workspace',type=Path,
                        help='save this workspace configuration through the original sync pair on close')
    parser.add_argument('--workspace-lock-fd',type=int,
                        help='internal: inherit the official launcher lifecycle lease')
    parser.add_argument('--workspace',type=Path,default=Path.cwd())
    args = parser.parse_args()
    if not args.ui.is_file():
        parser.error('Build the UI first: cd camera-ui-rs && cargo build --release')
    sd_api=sd_baseline=sd_session=sd_lock=None
    config_api=config_lock=config_store=None
    if args.workspace_lock_fd is not None and args.config_workspace is None:
        parser.error('--workspace-lock-fd requires --config-workspace')
    if args.config_workspace:
        config_api=runpy.run_path(str(HERE/'workspace-config.py'))
        config_lock=config_api['locked'](args.config_workspace.resolve(strict=True),args.workspace_lock_fd)
        # Hold the store for the whole session; the save path must not lock again.
        config_store=config_lock.__enter__()
        config_reference=config_api['official_reference'](args.runtime.resolve())
        current=config_store.current(config_reference)
        expected_generation=current['identity'] if current else None
    if args.attach_sd:
        workspace=args.workspace.absolute();workspace.mkdir(parents=True,exist_ok=True)
        state=workspace/'.a7c2';state.mkdir(exist_ok=True)
        sd_lock=(state/'sd.lock').open('a');fcntl.flock(sd_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        (workspace/'SD').mkdir(exist_ok=True)
        sd_api=runpy.run_path(str(HERE/'sd-directory.py'))
        sd_session=Path(tempfile.mkdtemp(prefix='desktop-sd-',dir=args.runtime.resolve()/'analysis'))
        sd_baseline=sd_api['pack'](workspace/'SD',sd_session/'input.fat')
        (sd_session/'baseline.json').write_text(json.dumps(sd_baseline,indent=2)+'\n')
        subprocess.run([sys.executable,'-B',str(HERE/'build-full-system.py'),'--runtime',str(args.runtime.resolve()),
                        '--card-seed',str(sd_session/'input.fat')],check=True)
    input_dir = Path(tempfile.mkdtemp(prefix='a7c2-input-'))
    messages = queue.Queue()
    extra=['--low-latency-input',args.low_latency_input,'--lcd-stream-fps',str(args.lcd_stream_fps)]
    if args.bluetooth_policy:extra+=['--bluetooth-policy',args.bluetooth_policy]
    if config_lock is not None:extra.append('--config-export-on-request')
    key_plan=''
    if args.attach_sd:
        extra+=['--file-media','card','--card-export-on-request','--card-export-flush']
        key_plan='60.0:/simulation/cp-rm-notify 2 0 0 7 0 2 0'
    vm = subprocess.Popen([sys.executable, '-B', str(HERE/'run-full-system.py'),'--runtime',str(args.runtime.resolve()),
                           *configuration(input_dir, args.seconds,args.observe_input,official=args.official,key_plan=key_plan),*extra],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, start_new_session=True)
    ui = None
    input_closed_for_save=False
    def follow():
        for line in vm.stdout:
            print(line, end='', flush=True)
            messages.put(line)
    threading.Thread(target=follow, daemon=True).start()
    try:
        deadline = time.monotonic()+150
        run = None
        while time.monotonic() < deadline and vm.poll() is None:
            try:
                line = messages.get(timeout=.2)
            except queue.Empty:
                continue
            if line.startswith('FULLSYSTEM_RUN '):
                run = Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
                break
        if run is None:
            raise RuntimeError('VM failed to create its owned run; see launcher output')
        if run.parent.resolve()!=(args.runtime.resolve()/'analysis/runs').resolve():
            raise ValueError('Foreign VM run path')
        # Always supply BOTH channels. No static frame fallback is permitted here.
        ui_env={**os.environ,
            'CAMUI_RESET_SCRIPT':str(HERE/'reset-derived-state.py'),
            'CAMUI_RESET_RUNTIME':str(args.runtime.resolve()),
            'CAMUI_USB_CONTROL':str(HERE/'usb_ui.py'),
            'CAMUI_USB_RUN':str(run.resolve()),
            'CAMUI_FIRMWARE_BACKEND':str(HERE/'firmware-development.py'),
            'CAMUI_FIRMWARE_PYTHON':sys.executable}
        if args.firmware_context is not None:
            ui_env['CAMUI_FIRMWARE_CONTEXT']=str(args.firmware_context.absolute())
        # Bind host reset to this exact workspace; never inherit a foreign target.
        for name in ('CAMUI_CONFIG_WORKSPACE','CAMUI_WORKSPACE_CONFIG_SCRIPT'):
            ui_env.pop(name,None)
        if args.config_workspace:
            ui_env.update(CAMUI_CONFIG_WORKSPACE=str(args.config_workspace.resolve()),
                          CAMUI_WORKSPACE_CONFIG_SCRIPT=str(HERE/'workspace-config.py'))
        ui = subprocess.Popen([str(args.ui.resolve()), '--live', str(run/'live-frame.ppm'),
                               '--input-dir', str(input_dir)], env=ui_env)
        session={'ui_pid':ui.pid,'run':str(run),'input_dir':str(input_dir),'frame':str(run/'live-frame.ppm'),
                 'asset_source':json.loads((run/'inputs.json').read_text()).get('source','unknown'),
                 'ui_sha256':hashlib.sha256(args.ui.read_bytes()).hexdigest(),
                 'profile_sha256':hashlib.sha256((HERE/'camera-profile.json').read_bytes()).hexdigest()}
        (run/'camera-ui-session.json').write_text(json.dumps(session,indent=2)+'\n')
        print('CAMERA_UI_SESSION '+json.dumps(session),flush=True)
        input_closed_for_save=wait_ui_or_save(ui,vm,input_dir,args.attach_sd or config_store is not None)
        if config_lock is not None and not input_closed_for_save and vm.poll() is None and ui.poll() is not None:
            # The user closed the window: stop input, then ask the runner for the
            # original sync/export pair. Nothing is saved unless that path completes.
            stop_input_producer(ui,input_dir);input_closed_for_save=True
        if args.attach_sd or config_lock is not None:
            if not (input_dir/'input-producer-stopped').exists():stop_input_producer(ui,input_dir)
            timeout=420 if args.attach_sd and config_store is not None else 240 if config_store is not None else 180
            rc=wait_for_card_save(vm,input_dir,timeout=timeout)
        if args.attach_sd:
            evidence=json.loads((run/'result.json').read_text())
            proof=runpy.run_path(str(HERE/'save-evidence.py'))['load_card_receipt'](run)
            saved=sd_api['restore'](run/'card-image.bin',workspace/'SD',sd_baseline,proof)
            saved.update(source_run=str(run),terminal_console_sha256=evidence['terminal_console_sha256'],
                         card_flush_lifecycle_verified=True,capture_verified=False,card_persistence_verified=False,
                         session_state=evidence['state'],configuration_saved=False)
            (run/'sd-directory-sync.json').write_text(json.dumps(saved,indent=2)+'\n')
            (sd_session/'sync.json').write_text(json.dumps(saved,indent=2)+'\n')
            print('SD_DIRECTORY_SYNC_VERIFIED '+str(run/'sd-directory-sync.json'),flush=True)
        if config_lock is not None:
            if rc:raise RuntimeError('Configuration save failed; the previous workspace generation is kept; '
                                     + ('verified SD content was synchronized' if args.attach_sd else 'no SD export requested'))
            pointer=config_store.save_run(run,config_reference,expected_generation)
            (run/'workspace-config-save.json').write_text(json.dumps(pointer,indent=2)+'\n')
            print('WORKSPACE_CONFIG_SAVED '+pointer['generation'],flush=True)
            return 0
        if args.attach_sd:
            if rc:raise RuntimeError('Session failed after the independently verified SD export')
            return 0 if input_closed_for_save else ui.returncode if ui.returncode is not None else 0
        if vm.poll() is not None:
            print('VM_STOPPED: UI will mark the live channel stale.', flush=True)
            return vm.returncode
        return ui.returncode
    finally:
        # Signal only this launcher-owned runner; it tears down its own QEMU.
        if vm.poll() is None:
            vm.send_signal(signal.SIGINT)
            try:
                vm.wait(timeout=45)
            except subprocess.TimeoutExpired:
                retained={'runner_pid':vm.pid,'run':str(run) if run else None,
                          'reason':'normal owner cleanup incomplete; no VM signals sent'}
                target=run/'camera-ui-owner-retained.json' if run else input_dir/'owner-retained.json'
                target.write_text(json.dumps(retained,indent=2)+'\n')
                raise RuntimeError('VM owner retained; normal cleanup evidence: '+str(target))
        if ui is not None and ui.poll() is None:
            ui.terminate()
            try:ui.wait(timeout=5)
            except subprocess.TimeoutExpired:ui.kill();ui.wait(timeout=5)
        if config_lock is not None:
            config_lock.__exit__(None,None,None)


if __name__ == '__main__':
    raise SystemExit(main())
