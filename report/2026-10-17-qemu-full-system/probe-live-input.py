#!/usr/bin/env python3
"""Owned F input regression; scheduled taps remain separated in host time."""
import json
import argparse
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def event(code, status, previous, layer='callback'):
    if layer=='raw':
        return f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {status & 0xffffffff:#x} 0 1'
    payload = struct.pack('<IIiiIIII', code, 0, status, previous, 0, 0, 1, 0).hex()
    return f'/simulation/inject-event 0x5503e0 0x5503e0 {payload}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stacks', action='store_true')
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--no-plan',action='store_true',help='Observe initial startup without sending navigation keys')
    parser.add_argument('--gui-models', choices=('off','capture'),default='off')
    parser.add_argument('--gpio-c1', choices=('off','virtual'),default='off')
    parser.add_argument('--remote-state', choices=('off','capture'),default='off')
    parser.add_argument('--bluetooth-policy',choices=('original','off'),default='original')
    parser.add_argument('--input-layer',choices=('raw','callback'),default='callback')
    parser.add_argument('--mode-p',action='store_true',help='Single original PP POS_MODE_DIAL status3, then read native model fields')
    parser.add_argument('--capture-osd-frames',action='store_true',help='Explicit paused buffer diagnostics; normal interaction uses running QMP screendump only')
    parser.add_argument('--pad-cycle',action='store_true')
    parser.add_argument('--error-logs',action='store_true')
    parser.add_argument('--seconds',type=int,help='Diagnostic bound; planned steps after it are explicitly reported as unrun')
    parser.add_argument('--observe-shutdown-write',action='store_true')
    parser.add_argument('--observe-system-error-source',action='store_true')
    args = parser.parse_args()
    baseline = HERE/'camera-profile.json'
    experiment = json.loads(baseline.read_text())['experiment']
    for key in list(experiment):
        if key.startswith('until_'):
            experiment[key] = False
    queue = Path(tempfile.mkdtemp(prefix='f-live-input-'))
    plan = []
    # Do not auto-open during boot. Every tap is sent after settling, and repeated
    # much later in the same process: early-only response cannot pass this probe.
    for at, code in ([] if args.no_plan else [(40, 0x1ab), (50, 0x30), (60, 0x1ac),
                     (80, 0x1ab), (100, 0x1ab), (110, 0x30), (120, 0x1ac)]):
        plan.extend([f'{at}:{event(code,1,0,args.input_layer)}', f'{at + .2}:{event(code,0,1,args.input_layer)}'])
    if args.mode_p:
        plan.append(f'30:{event(0x7025,3,0,args.input_layer)}')
        readback="""pid=$(busybox sed -n 's/^OBSERVER_READY pid=\\([0-9]*\\) base=.*/\\1/p' /tmp/menu-load.log)
echo NATIVE_MODE_P_READBACK
/simulation/menu-readmem /proc/$pid/mem 0x7ee4750 4 appFw.so
/simulation/menu-readmem /proc/$pid/mem 0x7ee4778 4 appFw.so
/simulation/menu-readmem /proc/$pid/mem 0x7ecad08 8 appFw.so
"""
        plan.append('35:'+readback)
        plan.sort(key=lambda item:float(item.partition(':')[0]))
    if args.stacks:
        plan.append("125:if [ -r /tmp/uipc_stat_kernel.txt ]\nthen\nbusybox sed -n '1,100p' /tmp/uipc_stat_kernel.txt\nelse\necho ORIGINAL_OOM_FILE_UNREADABLE_OR_ABSENT\nfi")
        plan.append('70:/simulation/stack-census.sh')
        plan.append('130:/simulation/stack-census.sh')
        plan.sort(key=lambda item: float(item.partition(':')[0]))
    if args.pad_cycle:
        if args.gpio_c1!='virtual':parser.error('--pad-cycle requires --gpio-c1 virtual')
        plan.extend(['150:/simulation/gpio-pad-state press','151:/simulation/gpio-pad-state release'])
        plan.sort(key=lambda item: float(item.partition(':')[0]))
    if args.error_logs:
        plan.extend(['35:/simulation/bounded-log /tmp/im.log 60000',
                     '37:/simulation/bounded-log /tmp/menu-load.log 60000'])
        plan.sort(key=lambda item: float(item.partition(':')[0]))
    duration=args.seconds if args.seconds is not None else 300 if args.stacks else 180 if args.pad_cycle else 140
    unrun=[entry.partition(':')[0] for entry in plan if float(entry.partition(':')[0])>=duration]
    if unrun:print('INPUT_PROBE_UNRUN_STEPS_AFTER_BOUND',','.join(unrun),flush=True)
    experiment.update(seconds=duration, stall_seconds=0, stacks=False, fatal_probe=False,
                      serial_diagnostic_seconds=30, observe_uart_input=False,
                      probe_uart_rx=False, probe_uart_command=False, observe_upm_notify=False,
                      dig_level='virtual', dmm_service='unit-size', hdmi_connection='control',
                      adf_audio_connection='control', osd_headless='on', tcg_thread='multi',
                      capture_osd_frames=args.capture_osd_frames and not (args.observe_shutdown_write or args.observe_system_error_source), insmod_policy='media-rm', native_display='none',
                      live_frame_seconds=.4, observe_input=True, key_after_marker='',
                      gui_models=args.gui_models,
                      gpio_c1=args.gpio_c1,
                      remote_state=args.remote_state,
                      bluetooth_policy=args.bluetooth_policy,
                      observe_shutdown_write=args.observe_shutdown_write,
                      observe_system_error_source=args.observe_system_error_source,
                      key_plan=';'.join(plan), input_queue_dir=str(queue))
    if args.runtime is not None:experiment['runtime']=str(args.runtime.resolve())
    argv = []
    for key, value in experiment.items():
        if value is None or value is False:
            continue
        argv += ['--'+key.replace('_','-')]
        if value is not True:
            argv += [str(value)]
    print('INPUT_QUEUE', queue, flush=True)
    return subprocess.call([sys.executable, '-B', str(HERE/'run-full-system.py'), *argv])


if __name__ == '__main__':
    raise SystemExit(main())
