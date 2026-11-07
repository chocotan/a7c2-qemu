#!/usr/bin/env python3
"""Run an owned full-dump VM with real loop mounts and bounded observations."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
BASE = HERE / 'runtime/analysis'
sys.dont_write_bytecode = True
NATIVE_INPUT = runpy.run_path(str(HERE / 'native-input.py'))['resolve']()
MENU = NATIVE_INPUT / 'runtime/analysis'
sys.path.insert(0, str(MENU))
from menu_live import FirmwareMonitor, connect_in_run
serial_command=runpy.run_path(str(HERE/'serial-console.py'))['serial_command']
UiWakeup=runpy.run_path(str(HERE/'ui-wakeup.py'))['UiWakeup']

CARD_SAVE_REQUEST=b'A7C2_SAVE_CARD_AND_EXIT_V1\n'
CARD_INPUT_STOPPED=b'A7C2_INPUT_PRODUCER_STOPPED_V1\n'
BOOTIN_ORIGINAL_SHA256='dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2'


def validate_bootin_handoff(stage,handoff,manifest,base):
    if handoff=='simulation-bind':return None
    if handoff!='p15-wrapper' or stage!='init2':
        raise ValueError('p15-wrapper bootin handoff requires init2')
    metadata=manifest.get('bootin_wrapper_experiment')
    if not isinstance(metadata,dict) or type(metadata.get('schema')) is not int or metadata['schema']!=1:
        raise ValueError('Missing or invalid bootin_wrapper_experiment schema')
    for name in ('wrapper_sha256','original_elf_sha256','derived_usr_sha256'):
        if not isinstance(metadata.get(name),str) or not re.fullmatch('[0-9a-f]{64}',metadata[name]):
            raise ValueError('Invalid bootin_wrapper_experiment '+name)
    if metadata['original_elf_sha256']!=BOOTIN_ORIGINAL_SHA256:
        raise ValueError('Original bootin ELF identity differs')
    if type(metadata.get('virtual_sd_present')) is not bool or metadata.get('case') not in ('plain','valid-sd','absent-sd','bad-sd'):
        raise ValueError('Invalid bootin_wrapper_experiment card presence or case')
    root=Path(base)/'root'
    files=[(root/'simulation/p15-wrapper-source','wrapper_sha256'),
           (root/'partitions/a7c2-usr.img','derived_usr_sha256')]
    if metadata['virtual_sd_present']:
        expected=metadata.get('virtual_sd_sha256')
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
            raise ValueError('Invalid bootin_wrapper_experiment virtual_sd_sha256')
        files.append((root/'partitions/bootin-sd-ext2.img','virtual_sd_sha256'))
    for path,key in files:
        if any(part.is_symlink() for part in (root,path.parent,path)) or not path.is_file():
            raise ValueError('Expected an ordinary bootin handoff file: '+str(path))
        with path.open('rb') as stream:
            actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=metadata[key]:raise ValueError('Bootin handoff SHA256 differs: '+str(path))
    return metadata


def prepare_bootin_handoff(run,handoff,metadata,out):
    if handoff=='simulation-bind':
        run('cp /usr/bin/bootin.elf /simulation/bootin-original')
        run('chmod 755 /simulation/bootin-original')
        run('mount -o bind /simulation/bootin-wrapper /usr/bin/bootin.elf')
        return
    files=[('/usr/bin/bootin.elf',metadata['wrapper_sha256']),
           ('/usr/bin/bootin-original',metadata['original_elf_sha256'])]
    if metadata['virtual_sd_present']:
        files.append(('/partitions/bootin-sd-ext2.img',metadata['virtual_sd_sha256']))
    rows=[]
    for path,expected in files:
        raw=run('/usr/bin/openssl dgst -sha256 '+path,
                timeout=120 if path=='/partitions/bootin-sd-ext2.img' else 30)
        values=re.findall(rb'= ([0-9a-f]{64})\r?$',raw,re.M)
        actual=values[0].decode() if len(values)==1 else None
        rows.append({'path':path,'expected_sha256':expected,'actual_sha256':actual,
                     'verified':actual==expected,'raw_output_hex':raw.hex()})
        (out/'bootin-handoff-readback.json').write_text(json.dumps(rows,indent=2)+'\n')
        if not rows[-1]['verified']:raise RuntimeError('Guest bootin handoff SHA256 differs: '+path)
    run('[ -x /usr/bin/bootin.elf ] && [ -x /usr/bin/bootin-original ]')
    run('[ ! -e /dev/mmca2 ] && [ ! -L /dev/mmca2 ]')
    if metadata['virtual_sd_present']:
        run('[ ! -e /dev/loop18 ] && [ ! -L /dev/loop18 ]')
        run('busybox mknod /dev/loop18 b 7 18')
        run('/simulation/attach-loop 18 /partitions/bootin-sd-ext2.img ro')
        run('ln -s /dev/loop18 /dev/mmca2')
        run('[ "$(busybox readlink /dev/mmca2)" = /dev/loop18 ]')


def adaptive_phase(result, seek, seek_after, elapsed):
    """Never let the startup fallback confirm a dialog after a menu search."""
    if result.get('adaptive_seek_found'):
        return 'done'
    if not result.get('adaptive_stopped'):
        return 'startup'
    if not seek:
        return 'done'
    if seek_after is not None and elapsed < seek_after:
        return 'waiting-for-seek'
    return 'seeking'


def adaptive_seek_keys(name, target, direction, enter, steps):
    if name == target:
        return (['ENTER'] if enter else []), True
    if steps >= 16:
        raise TimeoutError('Adaptive menu search exceeded 16 moves; no confirmation sent')
    return [direction], False


def card_save_requested(directory):
    path=Path(directory)/'save-card-and-exit.request'
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return False
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size!=len(CARD_SAVE_REQUEST):
            raise ValueError('Invalid owned card-save request')
        if os.read(fd,len(CARD_SAVE_REQUEST)+1)!=CARD_SAVE_REQUEST:
            raise ValueError('Invalid owned card-save request payload')
    finally:os.close(fd)
    return not any(Path(directory).glob('*.cmd'))


def card_input_stopped(directory):
    path=Path(directory)/'input-producer-stopped'
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    except FileNotFoundError:return False
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size!=len(CARD_INPUT_STOPPED):
            raise ValueError('Invalid input-stop acknowledgement')
        if os.read(fd,len(CARD_INPUT_STOPPED)+1)!=CARD_INPUT_STOPPED:
            raise ValueError('Invalid input-stop acknowledgement payload')
    finally:os.close(fd)
    return True


def quiesce_card_inputs(directory,run,timeout=20):
    directory=Path(directory)
    (directory/'input-quiesce.request').write_bytes(b'A7C2_STOP_INPUT_V1\n')
    deadline=time.monotonic()+timeout
    while not card_input_stopped(directory):
        if time.monotonic()>=deadline:raise TimeoutError('UI input producer did not stop before card save')
        time.sleep(.05)
    # The launcher has joined its UI process; every published command is now final.
    pending=sorted(directory.glob('*.cmd'))
    if len(pending)>64:raise RuntimeError('Too many pending commands at card-save barrier')
    for request in pending:
        command=request.read_text().strip()
        output=run(command,timeout=30) if command else b''
        temporary=request.with_suffix('.out.tmp');temporary.write_bytes(output)
        temporary.replace(request.with_suffix('.out'));request.unlink()
    if any(directory.glob('*.cmd')):raise RuntimeError('Input arrived after producer-stop acknowledgement')
    return len(pending)


class FullFirmwareMonitor(FirmwareMonitor):
    def __init__(self,path):
        super().__init__(path)
        self.full_console=path
        self.fatal_probe=None
        self.shutdown_probe=None

    def check(self):
        if self.full_console.is_file() and b'FULLSYSTEM_BOOTIN_HANDOFF_FAILED ' in self.full_console.read_bytes():
            raise RuntimeError('Original bootin handoff failed; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_GRMPIN_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('GRM pin registry ownership fault')
        if self.full_console.is_file() and b'OBS FULL_DRAWINFO_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('DrawInfo pin registry ownership fault')
        if self.full_console.is_file() and b'OBS FULL_INFRABB_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('InfraBB pin registry ownership fault')
        if self.full_console.is_file() and b'OBS FULL_INFRABB_CONNECT_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('InfraBB->VEF connection ownership fault')
        if self.full_console.is_file() and b'FULLSYSTEM_BLUETOOTH_POLICY_FAILED' in self.full_console.read_bytes():
            raise RuntimeError('Original Bluetooth-Off preference write/readback failed')
        if self.full_console.is_file() and b'OBS FULL_REMOTE_STATE_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Remote state consumer failed to release original message')
        if self.full_console.is_file() and b'FULLSYSTEM_GPIO_PAD_FAILED' in self.full_console.read_bytes():
            raise RuntimeError('Virtual C1 pad initialization/readback failed')
        if self.full_console.is_file() and b'OBS FULL_GUI_MODELS_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('GUI model consumer failed to release original message')
        if self.fatal_probe:self.fatal_probe.check()
        if self.shutdown_probe:self.shutdown_probe.check()
        value=super().check()
        if self.full_console.is_file() and b'OBS FULL_IMAGING_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual imaging ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_VDF_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual VDF ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_AUDIO_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual audio ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_HDMI_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual HDMI ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_VEF_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual VEF ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_PINMEM_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual PinMemMgr ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_SCALAR_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual Scalar ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_ADF_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual ADF ownership fault; inspect the retained private console')
        if self.full_console.is_file() and b'OBS FULL_ADF_CONNECT_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual ADF connection ownership fault; inspect console.log')
        if self.full_console.is_file() and b'OBS FULL_HDMIPIN_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual HDMI pin ownership fault; inspect console.log')
        if self.full_console.is_file() and b'OBS FULL_SCALAR_CONNECT_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual Scalar connection ownership fault; inspect console.log')
        if self.full_console.is_file() and b'OBS FULL_PIN_CONNECT_FAULT ' in self.full_console.read_bytes():
            raise RuntimeError('Virtual pin connection ownership/backing fault')
        if self.full_console.is_file() and b'FULLSYSTEM_SOUND_OWNER_FAILED' in self.full_console.read_bytes():
            raise RuntimeError('Original system sound backing initialization failed')
        if self.full_console.is_file() and b'FULL_LIRO_OBSERVE_FAILURE' in self.full_console.read_bytes():
            raise RuntimeError('LIRO read-only observer failed; inspect private diagnostic evidence')
        if self.full_console.is_file() and b'FULL_PIN_CONTROL_PROBE_FAILED' in self.full_console.read_bytes():
            raise RuntimeError('Explicit pin control backing probe failed')
        return value


class PacedInput:
    """Stay below the console baud/FIFO rate, even with several guest CPUs."""
    def __init__(self, stream, journal=None):
        self.stream = stream
        self.journal = journal
        self.serial = 0

    def write(self, data):
        self.serial += 1
        if self.journal is not None:
            with self.journal.open('a') as out:
                out.write(json.dumps({'write':self.serial,'event':'begin','bytes':len(data),
                    'hex':data.hex(),'chunk_bytes':16,'chunk_delay_seconds':.005})+'\n')
        sent=0
        for offset in range(0,len(data),16):
            chunk=data[offset:offset+16]
            count=self.stream.write(chunk)
            if count!=len(chunk):
                raise RuntimeError('Short host UART pipe write; recorded serial input retained')
            sent+=count
            self.stream.flush()
            time.sleep(.005)
        if self.journal is not None:
            with self.journal.open('a') as out:
                out.write(json.dumps({'write':self.serial,'event':'complete','bytes':sent})+'\n')
        return len(data)

    def __getattr__(self, name):
        return getattr(self.stream,name)


def input_tap_command(code):
    if type(code) is not int or not 0<=code<=0xffffffff:
        raise ValueError('Input contact must be a u32 code')
    prefix=f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 '
    return (prefix+'0x1 0 1; pressed=$?; sleep 0.05; '+prefix+
            '0x0 0 1; released=$?; test "$pressed" = 0 && test "$released" = 0')


def qmp_open(path):
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(5)
    connect_in_run(sock, path.parent, path.name)
    stream = sock.makefile('rwb')
    if 'QMP' not in json.loads(stream.readline()):
        raise RuntimeError('Bad QMP greeting')

    def call(name, arguments=None):
        request = {'execute':name}
        if arguments is not None:
            request['arguments'] = arguments
        stream.write(json.dumps(request).encode() + b'\n')
        stream.flush()
        while True:
            reply = json.loads(stream.readline())
            if 'event' not in reply:
                if 'return' not in reply:
                    raise RuntimeError(str(reply))
                return reply['return']
    call('qmp_capabilities')
    return sock, stream, call


def collect_observer_result(probe, result):
    """A summary failure must not bypass debugger and owned-process cleanup."""
    if probe is None:
        return
    try:
        if probe.KIND == 'mode-write':
            result['original_mode_writer_captured'] = probe.captured
            result['original_mode_writes_observed'] = probe.writes
        elif probe.KIND == 'ee-transition':
            result['ee_transition_observed_hits'] = probe.writes
            result['ee_transition_capture_verified'] = False
        elif probe.KIND == 'system-error-source':
            result['system_error_sender_captured'] = probe.captured
            result['system_error_source_events_examined'] = probe.writes
        elif probe.KIND == 'panel-tick':
            result['controller_counter_observed_hits'] = len(probe.hits)
            result['controller_counter_armed'] = probe.armed_at is not None
            result['controller_counter_recovery_verified'] = False
        elif probe.KIND == 'upm-reload':
            result['upm_reload_send_calls_observed'] = len(probe.hits)
            result['upm_reload_probe_armed'] = probe.armed_at is not None
            result['upm_reload_kernel_effect_verified'] = False
        elif probe.KIND == 'upm-activity':
            result['upm_activity_command_reads_observed'] = len(probe.hits)
            result['upm_activity_probe_armed'] = probe.armed_at is not None
            result['upm_activity_wake_verified'] = False
        else:
            result['shutdown_factor_write_captured'] = probe.captured
            result['shutdown_factor_writes_observed'] = probe.writes
    except Exception as error:
        result['state'] = 'failed'
        result.setdefault('error', 'Diagnostic summary failed: ' + str(error))
        result['diagnostic_summary_error'] = str(error)


def preserve_owned_run(process, result, out):
    result.update(owner_retained=True,terminal_evidence_checked=False)
    record={'run':str(out),'runner_pid':os.getpid(),'owner_pid':process.pid if process is not None else None,
            'reason':result.get('error','Unreleased VM resources'),'vm_signals_sent':[]}
    raw=(json.dumps(record,indent=2)+'\n').encode()
    (out/'owner-retained.json').write_bytes(raw)
    if out.parent.name!='runs' or out.parent.parent.name!='analysis':
        raise ValueError('Retained owner requires its bound runtime/analysis/runs directory')
    guard=out.parent.parent/'.owner-retained.json'
    with guard.open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())


def wait_retained_owner(process, result, out):
    if not result.get('owner_retained') or process is None or process.poll() is not None:return
    print('FULLSYSTEM_OWNER_RETAINED',process.pid,out,flush=True)
    while process.poll() is None:
        try:process.wait(timeout=30)
        except (subprocess.TimeoutExpired,KeyboardInterrupt):continue
    result['retained_owner_observed_exit']=process.returncode
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')


def finish_owned_run(process, result, out):
    """Classify terminal evidence only after this VM can no longer write it."""
    def failure(message):
        result['state'] = 'failed'
        result.setdefault('terminal_errors', []).append(message)
        result.setdefault('error', message)

    result['terminal_evidence_checked'] = False
    result['owned_process_returncode_before_cleanup'] = process.poll() if process is not None else None
    stopped = process is None
    if process is not None:
        try:
            result['vm_signals_sent'] = []
            if process.poll() is None:
                quit_socket, quit_stream, quit_command = qmp_open(out/'qmp.sock')
                try:
                    result['qmp_quit_attempted'] = True
                    quit_command('quit')
                    result['qmp_quit_confirmed'] = True
                finally:
                    quit_stream.close()
                    quit_socket.close()
                process.wait(timeout=30)
            stopped = process.poll() is not None
            if not stopped:
                raise RuntimeError('Owned VM is still running after normal QMP quit')
        except Exception as error:
            failure('Owned VM termination failed: ' + str(error))
            result['owner_retained'] = process.poll() is None
        result['owned_process_returncode'] = process.poll()
        if stopped and result['owned_process_returncode'] != 0:
            failure('Owned VM exited with code ' + str(result['owned_process_returncode']))
        if result.get('owner_retained'):
            try:preserve_owned_run(process,result,out)
            except Exception as error:failure('Retained owner guard failed: '+str(error))
    if stopped:
        try:
            console = (out / 'console.log').read_bytes()
            result['terminal_console_sha256'] = hashlib.sha256(console).hexdigest()
            result['terminal_evidence_checked'] = True
            for marker, name in ((b'OBS FULL_REMOTE_STATE_FAULT ', 'remote state'),
                                 (b'OBS FULL_GUI_MODELS_FAULT ', 'GUI model'),
                                 (b'OBS FULL_VDF_FAULT ', 'VDF'),
                                 (b'OBS FULL_AUDIO_FAULT ', 'audio'),
                                 (b'OBS FULL_HDMI_FAULT ', 'HDMI'),
                                 (b'OBS FULL_VEF_FAULT ', 'VEF'),
                                 (b'OBS FULL_PINMEM_FAULT ', 'PinMemMgr'),
                                 (b'OBS FULL_SCALAR_FAULT ', 'Scalar'),
                                 (b'OBS FULL_INFRABB_FAULT ', 'InfraBB'),
                                 (b'OBS FULL_DRAWINFO_FAULT ', 'DrawInfo'),
                                 (b'OBS FULL_GRMPIN_FAULT ', 'GRM pin'),
                                 (b'OBS FULL_ADF_FAULT ', 'ADF'),
                                 (b'OBS FULL_ADF_CONNECT_FAULT ', 'ADF connection'),
                                 (b'OBS FULL_HDMIPIN_FAULT ', 'HDMI pin'),
                                 (b'OBS FULL_SCALAR_CONNECT_FAULT ', 'Scalar connection'),
                                 (b'OBS FULL_PIN_CONNECT_FAULT ', 'pin connection'),
                                 (b'OBS FULL_IMAGING_FAULT ', 'imaging')):
                if marker in console:
                    failure('Terminal ' + name + ' ownership fault; inspect console.log')
            if b'FULLSYSTEM_SOUND_OWNER_FAILED' in console:
                failure('Terminal system sound owner initialization failure')
            if b'FULLSYSTEM_GPIO_PAD_FAILED' in console:
                failure('Terminal virtual GPIO pad initialization failure')
            if b'FULLSYSTEM_BOOTIN_HANDOFF_FAILED ' in console:
                failure('Terminal original bootin handoff failure')
            if b'FULLSYSTEM_BLUETOOTH_POLICY_FAILED' in console:
                failure('Terminal Bluetooth preference initialization failure')
            if b'FULL_LIRO_OBSERVE_FAILURE' in console:
                failure('Terminal LIRO observation failure')
            if b'FULL_PIN_CONTROL_PROBE_FAILED' in console:
                failure('Terminal pin control backing probe failure')
            native = re.search(rb'SEQUENCE FATAL ERROR assert at ([^\r\n]+)', console)
            if native:
                result['original_model_fatal_observed'] = True
                failure('Original firmware model fatal: ' + native[1].decode(errors='replace'))
            if re.search(rb'(?:^|\n)(?:Entering exception monitor\.|Exception>)',
                         console.replace(b'\r', b'')):
                failure('Terminal original firmware exception monitor')
        except Exception as error:
            failure('Terminal console evidence unavailable: ' + str(error))
    raw = (json.dumps(result, indent=2) + '\n').encode()
    (out / 'result.json').write_bytes(raw)
    receipt = runpy.run_path(str(HERE/'save-evidence.py'))['card_receipt'](result)
    if receipt is not None:
        receipt['session_result_sha256'] = hashlib.sha256(raw).hexdigest()
        try:
            with (out/'sd-terminal-receipt.json').open('xb') as target:
                target.write((json.dumps(receipt, indent=2)+'\n').encode())
                target.flush();os.fsync(target.fileno())
        except Exception as error:
            failure('Card terminal receipt publication failed: '+str(error))
            (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')


def collect_serial_diagnostics(run,result,timeout=60):
    """Same bounded diagnostics, one RC transaction per step, one total budget."""
    result['serial_diagnostic_log_suffix_bytes']={'init2.log':4096,'im.log':4096,'menu-load.log':8192}
    steps=(
        ('modules','cat /proc/modules',None),
        ('init2-log','echo FULLSYSTEM_LOG_SUFFIX_init2_MAX_BYTES_4096; /simulation/bounded-log /log/qemu/init2.log 4096; echo LOG_SNAPSHOT_INIT2_RC=$?',b'LOG_SNAPSHOT_INIT2_RC=0'),
        ('processes','ps',None),
        ('mounts','cat /proc/mounts',None),
        ('im-log','echo FULLSYSTEM_LOG_SUFFIX_im_MAX_BYTES_4096; /simulation/bounded-log /log/qemu/im.log 4096; echo LOG_SNAPSHOT_IM_RC=$?',b'LOG_SNAPSHOT_IM_RC=0'),
        ('observer-log','echo FULLSYSTEM_OBSERVER_LOG_BEGIN; echo FULLSYSTEM_LOG_SUFFIX_menu_load_MAX_BYTES_8192; /simulation/bounded-log /log/qemu/menu-load.log 8192; echo LOG_SNAPSHOT_OBSERVER_RC=$?; echo FULLSYSTEM_OBSERVER_LOG_END',b'LOG_SNAPSHOT_OBSERVER_RC=0'),
        ('done','echo FULLSYSTEM_OBSERVATION_DONE',b'FULLSYSTEM_OBSERVATION_DONE'))
    deadline=time.monotonic()+timeout
    result['serial_diagnostic_budget_seconds']=timeout
    result['serial_diagnostic_steps']=[]
    for name,command,marker in steps:
        entry={'step':name,'completed':False};result['serial_diagnostic_steps'].append(entry)
        remaining=deadline-time.monotonic()
        entry['remaining_seconds_before']=remaining
        entry['elapsed_seconds_before']=timeout-remaining
        if remaining<=0:raise TimeoutError('Serial diagnostic total deadline reached before '+name)
        try:
            output=run(command,timeout=remaining)
            if marker and not re.search(rb'(?:^|\n)'+re.escape(marker)+rb'\r?(?:\n|$)',output):
                # The full-system route may never create this legacy menu log.
                # Its absence is also explicit in the previously passed runs.
                # Require both the reader's exact ENOENT report and its RC;
                # permission/read errors or a lost UART completion still fail.
                if (name=='im-log' and
                    re.search(rb'(?:^|\n)FULLSYSTEM_LOG_SNAPSHOT_MISSING path=/log/qemu/im\.log errno=2\r?(?:\n|$)',output) and
                    re.search(rb'(?:^|\n)LOG_SNAPSHOT_IM_RC=3\r?(?:\n|$)',output)):
                    entry.update(availability='not-created',reader_rc=3,errno=2)
                else:
                    raise RuntimeError('Required diagnostic marker missing: '+marker.decode())
        except Exception as error:
            entry['error']=str(error)
            raise RuntimeError('Serial diagnostic step '+name+' failed: '+str(error)) from error
        entry['completed']=True


def export_sound_memory(qmp, manifest, out, result):
    if result.get('system_sound_memory_exported'):
        return
    if b'FULL_SOUND_OWNER_READY ' not in (out/'console.log').read_bytes():
        raise RuntimeError('Original sound asset was not loaded and read back in guest')
    running=qmp('query-status')['running']
    try:
        if running:qmp('stop')
        qmp('pmemsave',{'val':manifest['virtual_system_sound']['physical'],
                       'size':manifest['virtual_system_sound']['capacity'],
                       'filename':'/out/system-sound-memory.bin'})
        result['system_sound_memory_exported']=True
    finally:
        if running:qmp('cont')



def capture_persisted_frames(qmp, out, seen, result):
    """Diagnostic reads of addresses from sampled PERSISTED log records.

    These addresses may already have been reused. Pausing after observing the log
    does not recover the original lease, so these raw dumps are not attributable
    immutable snapshots and cannot independently satisfy the shooting UI gate.
    """
    console=(out/'console.log').read_bytes()
    pattern=rb'OBS OSD_HEADLESS_PERSISTED [^\r\n]*?seq=(\d+) [^\r\n]*?phys=(0x[0-9a-f]+) ' \
            rb'[^\r\n]*?bytes=(\d+) [^\r\n]*?fnv1a64=([0-9a-f]{16})'
    captured=result.setdefault('osd_frames_captured',{})
    for match in re.finditer(pattern,console):
        seq=int(match.group(1))
        if seq in seen:continue
        seen.add(seq)
        address=int(match.group(2),16);length=int(match.group(3));recorded=match.group(4).decode()
        if length!=640*480*2:continue
        name='osd-frame-%03d.bin'%seq
        running=qmp('query-status')['running']
        try:
            if running:qmp('stop')
            qmp('pmemsave',{'val':address,'size':length,'filename':'/out/'+name})
        finally:
            if running:qmp('cont')
        raw=(out/name).read_bytes()
        figure=0xcbf29ce484222325
        for byte in raw:figure=((figure^byte)*0x100000001b3)&0xFFFFFFFFFFFFFFFF
        # The console hash covers the HOSDAP02 container (identity, sequence and
        # metadata plus pixels) inside the guest, while this dump is only the AP
        # pixel buffer at f.physical. The two can never be equal, so they are
        # reported separately instead of as a misleading match/mismatch flag.
        captured[str(seq)]={'file':name,'physical':hex(address),
                           'recorded_container_fnv1a64':recorded,
                           'container_scope':'HOSDAP02 identity+sequence+metadata+pixels',
                           'raw_pixels_fnv1a64':'%016x'%figure,
                           'method':'late physical pointer read after sampled console record',
                           'attribution_verified':False,
                           'container_matches_pixels':False,
                           'comparison_note':'container hash is not comparable to a raw pixel dump',
                           'nonzero_bytes':sum(1 for byte in raw if byte)}

CARD_EXPORT_CHUNK = 0x400000


CONFIG_EXPORT_TARGETS = ('/setting/Backup.bin', '/setting/Backup.bak')


def guest_file_size(run, path):
    """Ask the guest for the real size of an allowlisted file. No padding, no guessing."""
    if path not in CONFIG_EXPORT_TARGETS:
        raise ValueError('config export path is not allowlisted: ' + path)
    nonce = secrets.token_hex(12).encode('ascii')
    marker = b'CONFIG_EXPORT_SIZE_' + nonce
    # Capture wc through a pipe, away from printk on the serial TTY. Echo has %s,
    # not a number; only this command's closed content receipt supplies the size.
    command = (f'_config_size=$(busybox wc -c < {path}) && '
               f'printf "\\n{marker.decode()}:%s:END_{nonce.decode()}\\n" "$_config_size"')
    output = run(command, timeout=20)
    values = [int(value) for value in re.findall(re.escape(marker) + rb':[ \t]*([0-9]+)[ \t]*:END_' + re.escape(nonce), output)]
    if len(values) != 1 or values[0] <= 0:
        raise RuntimeError('missing or conflicting framed config size for ' + path)
    return values[0]


def export_config_file(run, qmp, manifest, out, path, name):
    """Export one allowlisted guest file through the same declared window as the card.

    The card export deliberately refuses anything but `/image_mmca`; this is the only
    other reader allowed to reuse that window, and its paths are closed too.
    """
    if path not in CONFIG_EXPORT_TARGETS:
        raise ValueError('config export path is not allowlisted: ' + path)
    geo = manifest.get('card_export')
    if not geo or geo['capacity'] < CARD_EXPORT_CHUNK:
        raise RuntimeError('config export requires the same explicit window as the card export')
    size = guest_file_size(run, path)
    if size > min(CARD_EXPORT_CHUNK, geo['capacity']):
        raise RuntimeError(f'{path} does not fit the declared export window')
    target = out / name
    if target.exists():
        raise RuntimeError('refusing to overwrite an existing config export')
    output = run(f'/simulation/card-export {path} 0 {size}', timeout=60)
    expected = card_chunk_receipt(output, 0, size, geo['physical'])
    identities = set(re.findall(rb'CARD_EXPORT_SOURCE ([^\r\n]+)', output))
    if len(identities) != 1:
        raise RuntimeError('missing or conflicting source identity for ' + path)
    running = qmp('query-status')['running']
    staged_window = out / (name + '.chunk')
    try:
        if running:
            qmp('stop')
        qmp('pmemsave', {'val': geo['physical'], 'size': size, 'filename': f'/out/{name}.chunk'})
    finally:
        if running:
            qmp('cont')
    data = staged_window.read_bytes()
    staged_window.unlink(missing_ok=True)
    if len(data) != size:
        raise RuntimeError(f'{name} readback is {len(data)} bytes, expected {size}')
    if card_chunk_hash(data) != expected:
        raise RuntimeError(f'{name} guest/host digest mismatch')
    temporary = out / (name + '.partial')
    with temporary.open('xb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    print(f'CONFIG_EXPORT_VERIFIED name={name} bytes={size} fnv64={expected:016x}', flush=True)
    return {'path': path, 'name': name, 'bytes': size, 'fnv64': f'{expected:016x}',
            'sha256': hashlib.sha256(data).hexdigest(),
            'source_identity': identities.pop().decode('ascii')}


def export_config_pair(run, qmp, manifest, out, result):
    """Export /setting/Backup.bin and its .bak so the pair can be validated host-side."""
    result['config_export'] = {'verified': False, 'files': []}
    try:
        for path, name in zip(CONFIG_EXPORT_TARGETS, ('Backup.bin', 'Backup.bak')):
            result['config_export']['files'].append(
                export_config_file(run, qmp, manifest, out, path, name))
    except Exception as error:
        result['config_export']['error'] = str(error)
        raise
    result['config_export']['verified'] = (
        len(result['config_export']['files']) == len(CONFIG_EXPORT_TARGETS))
    return result['config_export']


def sync_and_export_config(run, qmp, manifest, out, result):
    """Sync only the verified user subsystem; never retry a failed serial command."""
    result['config_sync'] = {'subsystem': 0x2cf, 'verified': False}
    try:
        output = run('/simulation/backup-sync --subsystem 0x2cf', timeout=60)
        (out / 'config-sync.log').write_bytes(output)
        codes = re.findall(rb'(?:^|\n)BACKUP_SYNC_END scope=subsystem subsystem=719 result=(-?\d+)\r?(?=\n|$)', output)
        if codes != [b'0']:
            raise RuntimeError('missing, repeated or unsuccessful original Backup sync receipt')
        result['config_sync']['verified'] = True
        return export_config_pair(run, qmp, manifest, out, result)
    except Exception as error:
        result['config_sync']['error'] = str(error)
        raise


def save_input_session(args, run, qmp, manifest, out, result, trigger):
    result['save_drained_commands'] = quiesce_card_inputs(args.input_queue_dir, run)
    if getattr(run,'quiesce_input',None) is not None:run.quiesce_input()
    result['input_producer_stopped_verified'] = True
    if args.card_export_on_request:
        result['card_save_drained_commands'] = result['save_drained_commands']
        result['card_input_producer_stopped_verified'] = True
        export_card_image(run, qmp, manifest, out, result, barrier_serial=run)
        result['card_export_trigger'] = trigger
        if any(Path(args.input_queue_dir).glob('*.cmd')):
            raise RuntimeError('Input arrived during card save')
        result['card_input_queue_empty_verified'] = True
    if args.config_export_on_request:
        try:
            sync_and_export_config(run, qmp, manifest, out, result)
        except Exception:
            if args.card_export_on_request and not any(Path(args.input_queue_dir).glob('*.cmd')):
                result['failure_scope'] = 'configuration-after-card-save'
                result['configuration_save_failed'] = True
            raise
        result['config_export_trigger'] = trigger
    if any(Path(args.input_queue_dir).glob('*.cmd')):
        raise RuntimeError('Input arrived after the save barrier; session save is not accepted')


def card_chunk_receipt(output, index, count, physical):
    records = set(re.findall(
        rb'CARD_EXPORT_CHUNK index=(\d+) offset=(\d+) bytes=(\d+) '
        rb'fnv64=([0-9a-f]{16}) window=(0x[0-9a-f]+)', output))
    if len(records) != 1:
        raise RuntimeError('missing or conflicting card chunk receipt')
    raw_index, raw_offset, raw_bytes, raw_hash, raw_window = records.pop()
    if (int(raw_index), int(raw_offset), int(raw_bytes), int(raw_window, 16)) != (
            index, index * CARD_EXPORT_CHUNK, count, physical):
        raise RuntimeError('card chunk receipt geometry differs')
    return int(raw_hash, 16)


def card_chunk_hash(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


def export_card_image(run, qmp, manifest, out, result, image='/image_mmca', size=0x8000000,
                      barrier_serial=None):
    """Export a snapshot; optionally require the original Fsys flush/STOP barrier."""
    if barrier_serial is None:
        return export_card_snapshot(run,qmp,manifest,out,result,image,size)
    if (out/'card-image.bin').exists():
        raise RuntimeError('refusing to overwrite an existing card snapshot')
    barrier=runpy.run_path(str(HERE/'sd_flush_barrier.py'))
    sequence=time.monotonic_ns()
    result['card_image_exported']=False
    result['card_flush_lifecycle_verified']=False
    exported=False
    try:
        result['card_flush']=barrier['quiesce'](barrier_serial,sequence,timeout=15)
        export_card_snapshot(run,qmp,manifest,out,result,image,size)
        exported=True
    finally:
        result['card_image_exported']=False
        try:
            result['card_flush_recovery']=barrier['cancel_resume'](barrier_serial,sequence)
            result['card_flush_lifecycle_verified']=bool(exported and result['card_flush_recovery']['ok'])
        finally:
            if not result['card_flush_lifecycle_verified'] and (out/'card-image.bin').exists():
                (out/'card-image.bin').replace(out/'card-image.bin.unrecovered')
    result['card_image_exported']=True


def export_card_snapshot(run, qmp, manifest, out, result, image='/image_mmca', size=0x8000000):
    """Ask the guest to stage one chunk of its card at a time; read each with pmemsave.

    The guest only preads its own file into a declared reserved region, so what the
    host reassembles is the real card content, not a host-side synthesis.
    """
    geo = manifest.get('card_export')
    if not geo or geo['capacity'] < CARD_EXPORT_CHUNK:
        raise RuntimeError('card export requires the explicit reservation')
    if image != '/image_mmca' or size <= 0:
        raise ValueError('invalid card snapshot source or size')
    result['card_image_exported'] = False
    result['card_snapshot_integrity_verified'] = False
    result['card_persistence_verified'] = False
    result['card_chunk_receipts'] = []
    image_path = out / 'card-image.bin'
    if image_path.exists():
        raise RuntimeError('refusing to overwrite an existing card snapshot')
    chunks = (size + CARD_EXPORT_CHUNK - 1) // CARD_EXPORT_CHUNK
    digest = hashlib.sha256()
    total = 0
    identity = None
    for index in range(chunks):
        count = min(CARD_EXPORT_CHUNK, size - total)
        output = run(f'/simulation/card-export {image} {index} {count}', timeout=60)
        expected_hash = card_chunk_receipt(output, index, count, geo['physical'])
        identities = set(re.findall(rb'CARD_EXPORT_SOURCE ([^\r\n]+)', output))
        if len(identities) != 1:
            raise RuntimeError('missing or conflicting card source identity')
        current = identities.pop().decode('ascii')
        if identity is not None and current != identity:
            raise RuntimeError('card source changed during snapshot')
        identity = current
        running = qmp('query-status')['running']
        name = f'/out/card-chunk-{index:03d}.bin'
        try:
            if running: qmp('stop')
            qmp('pmemsave', {'val': geo['physical'], 'size': count, 'filename': name})
        finally:
            if running: qmp('cont')
        data = (out / f'card-chunk-{index:03d}.bin').read_bytes()
        if len(data) != count:
            raise RuntimeError(f'chunk {index} readback is {len(data)} bytes')
        if card_chunk_hash(data) != expected_hash:
            raise RuntimeError(f'card chunk {index} guest/host digest mismatch')
        result['card_chunk_receipts'].append({'index': index, 'offset': total,
            'bytes': count, 'fnv64': f'{expected_hash:016x}', 'verified': True})
        digest.update(data)
        total += len(data)
        print(f'CARD_EXPORT_VERIFIED index={index} bytes={count}', flush=True)
    temporary = out / 'card-image.bin.partial'
    with temporary.open('xb') as handle:
        for index in range(chunks):
            handle.write((out / f'card-chunk-{index:03d}.bin').read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    if temporary.stat().st_size != size or hashlib.sha256(temporary.read_bytes()).hexdigest() != digest.hexdigest():
        raise RuntimeError('assembled card snapshot differs from verified chunks')
    temporary.replace(image_path)
    for index in range(chunks):
        (out / f'card-chunk-{index:03d}.bin').unlink()
    result['card_image_exported'] = True
    result['card_snapshot_integrity_verified'] = True
    result['card_source_identity'] = identity
    result['card_image_bytes'] = total
    result['card_image_sha256'] = digest.hexdigest()
    print('CARD_IMAGE_EXPORTED bytes=%d sha256=%s' % (total, digest.hexdigest()), flush=True)


def export_pin_control_memory(qmp, manifest, out, result):
    if result.get('pin_control_memory_exported'):
        return
    console=(out/'console.log').read_bytes()
    if not any(marker in console for marker in (b'FULL_PIN_CONTROL_PROBE_PASS ',b'OBS FULL_PIN_CONNECT_BUFFER_WRITTEN ')):
        # A boot fork can stop before the first edge ever writes the control buffer.
        # Record that honestly instead of failing a run that produced other evidence.
        result['pin_control_memory_export_skipped']='edge-not-reached'
        return
    running=qmp('query-status')['running']
    try:
        if running:qmp('stop')
        qmp('pmemsave',{'val':manifest['virtual_pin_control']['physical'],
            'size':manifest['virtual_pin_control']['capacity'],'filename':'/out/pin-control-memory.bin'})
        result['pin_control_memory_exported']=True
    finally:
        if running:qmp('cont')


def uart_rx_readback(qmp):
    # Only PL011 FR here. Four-CPU GICD debug reads dereference current_cpu in
    # this QEMU's HMP context and crash; GIC observations stay in board-regs.
    # Never read UART DR, GICC IAR or EOIR (consume data/ack interrupts).
    return {address:qmp('human-monitor-command',{'command-line':'xp /1wx '+address})
            for address in ('0x9000018',)}


def collect_failed_observation_logs(run, error, result, out):
    # A missing UART completion marker kills the VM and must never be followed
    # by another command. Only our own observation deadlines admit this read.
    if not isinstance(error, TimeoutError) or not str(error).startswith(('Original ', 'Actual ')):
        return
    raw=run('echo FULLSYSTEM_FAILURE_LOGS_BEGIN; '
            '/simulation/bounded-log /log/qemu/init2.log 4096; echo FAILURE_INIT2_SNAPSHOT_RC=$?; '
            '/simulation/bounded-log /log/qemu/im.log 4096; echo FAILURE_IM_SNAPSHOT_RC=$?; '
            '/simulation/bounded-log /log/qemu/menu-load.log 8192; echo FAILURE_OBSERVER_SNAPSHOT_RC=$?; '
            'ps; echo FULLSYSTEM_FAILURE_LOGS_END',timeout=60)
    (out/'failure-bounded-logs.log').write_bytes(raw)
    result['failure_bounded_logs_collected']=True


def sound_config_waiter_ready(console):
    """Trigger diagnostics after 25 distinct original per-kind reply frees."""
    query = re.search(rb'OBS FULL_AUDIO_REQUEST tid=(\d+) [^\r\n]*command=0x33f ', console)
    if not query:
        return False
    tid = query[1]
    leases = re.findall(rb'OBS FULL_AUDIO_NATIVE_REPLY_FREE tid=' + tid + rb' sender=' + tid +
                        rb' waiter=1 [^\r\n]* lease=(\d+) command=0x32c bytes=12 rc=0\r?$', console, re.M)
    return len(set(leases)) >= 25


def boot_config_waiters_ready(console, audio_capabilities='off', hdmi_service='off', vef_service='off', pinmem_service='off'):
    if not sound_config_waiter_ready(console):
        return False
    if audio_capabilities == 'inputless' and not re.search(
            rb'OBS FULL_AUDIO_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*command=0x327 bytes=28 rc=0(?:\r?\n|$)', console):
        return False
    if hdmi_service == 'boot' and not re.search(
            rb'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*command=0x101 bytes=12 status=0 rc=0(?:\r?\n|$)', console):
        return False
    if hdmi_service == 'boot':
        rates = re.findall(rb'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*lease=(\d+) command=0x117 bytes=12 status=0 rc=0(?:\r?\n|$)', console)
        by_caller = {}
        for caller, lease in rates:
            by_caller.setdefault(caller, set()).add(lease)
        if not any(len(leases) >= 5 for leases in by_caller.values()):
            return False
    if vef_service == 'registry' and not re.search(
            rb'OBS FULL_VEF_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*bytes=56 rc=0(?:\r?\n|$)', console):
        return False
    if pinmem_service == 'registry' and not re.search(
            rb'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*bytes=56 rc=0(?:\r?\n|$)', console):
        return False
    return True


def pin_format_block_ready(console, audio_capabilities='off'):
    if not boot_config_waiters_ready(console,audio_capabilities,'boot','registry','registry'):
        return False
    free=re.search(rb'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*bytes=56 command=0x8001 rc=0',console)
    if not free or b'OBS FULL_PIN_CONNECT_BUFFER_WRITTEN ' not in console:
        return False
    return re.search(rb'OBS FULL_PIN_CONNECT_FORMAT_BLOCKED_REQUEST tid='+free[1]+rb' [^\r\n]*destination=0x90590818 [^\r\n]*bytes=48 ',console) is not None


def pin_format_consumed_ready(console, audio_capabilities='off'):
    if not boot_config_waiters_ready(console,audio_capabilities,'boot','registry','registry'):
        return False
    commit=re.search(rb'OBS FULL_PIN_FORMAT_COMMIT tid=(\d+) [^\r\n]*buffer_released=1 format_cpu_consumed=1 ',console)
    if not commit:return False
    tid=commit[1]
    native=re.search(rb'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+
                     rb' waiter=1 [^\r\n]*bytes=56 command=0x8001 rc=0',console[commit.end():])
    if not native:return False
    tail=console[commit.end()+native.end():]
    get=re.search(rb'OBS FULL_PINMEM_COMMIT tid='+tid+rb' slot=4 type=0 dir=2 index=1 pin_state=1 owner=0x90590818 status=0 [^\r\n]*reply=([^ ]+) lease=(\d+) request_free_rc=0 ',tail)
    if not get:return False
    return re.search(rb'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+
                     rb' waiter=1 [^\r\n]*reply='+re.escape(get[1])+rb' lease='+get[2]+rb' bytes=56 rc=0',tail[get.end():]) is not None


def scalar_get_continuation(console):
    start=re.search(rb'OBS FULL_PIN_FORMAT_COMMIT tid=(\d+) [^\r\n]*format_cpu_consumed=1 ',console)
    if not start:return None
    tid=start[1]
    commit=re.search(rb'OBS FULL_SCALAR_COMMIT tid='+tid+rb' slot=4 type=0 dir=1 index=4 pin_state=1 owner=0x91670464 status=0 [^\r\n]*reply=([^ ]+) lease=(\d+) request_free_rc=0 ',console[start.end():])
    if not commit:return None
    offset=start.end()+commit.end();tail=console[offset:]
    freed=re.search(rb'OBS FULL_SCALAR_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+
        rb' waiter=1 [^\r\n]*reply='+re.escape(commit[1])+rb' lease='+commit[2]+rb' bytes=56 rc=0',tail)
    return (tid,offset+freed.end()) if freed else None


def scalar_get_ready(console):
    return scalar_get_continuation(console) is not None


def scalar_connection_continuation(console):
    previous=scalar_get_continuation(console)
    if not previous:return None
    tid,offset=previous
    free=re.search(rb'OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+rb' waiter=1 [^\r\n]*bytes=56 command=0x8001 rc=0',console[offset:])
    if not free:return None
    offset+=free.end();tail=console[offset:]
    commit=re.search(rb'OBS FULL_PINMEM_COMMIT tid='+tid+rb' slot=5 type=0 dir=2 index=2 pin_state=1 owner=0x90590818 status=0 [^\r\n]*reply=([^ ]+) lease=(\d+) request_free_rc=0 ',tail)
    if not commit:return None
    offset+=commit.end()
    freed=re.search(rb'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+rb' waiter=1 [^\r\n]*reply='+re.escape(commit[1])+rb' lease='+commit[2]+rb' bytes=56 rc=0',console[offset:])
    return (tid,offset+freed.end()) if freed else None


def scalar_connection_ready(console):
    return scalar_connection_continuation(console) is not None


def adf_get_continuation(console):
    previous=scalar_connection_continuation(console)
    if not previous:return None
    tid,offset=previous;tail=console[offset:]
    commit=re.search(rb'OBS FULL_ADF_COMMIT tid='+tid+rb' slot=0 type=0 dir=1 index=0 pin_state=1 owner=0x9058003f status=0 [^\r\n]*reply=([^ ]+) lease=(\d+) request_free_rc=0 ',tail)
    if not commit:return None
    offset+=commit.end();tail=console[offset:]
    freed=re.search(rb'OBS FULL_ADF_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+rb' waiter=1 destination=(0x[0-9a-f]+) [^\r\n]*reply='+re.escape(commit[1])+rb' lease='+commit[2]+rb' bytes=56 rc=0',tail)
    if not freed:return None
    offset+=freed.end()
    for request in re.finditer(rb'OBS FULL_PIN_REQUEST_OBSERVE tid='+tid+rb' destination=0x90590818 source='+freed[1]+rb' bytes=64 captured=64 raw=([0-9a-f]{128})',console[offset:]):
        wire=bytes.fromhex(request[1].decode())
        if (int.from_bytes(wire[:4],'little')==int(freed[1],16) and
            wire[4:20]==bytes.fromhex('a0a0a0a0010040001800000040000000') and
            wire[24:32]==bytes.fromhex('0010010028000200') and
            wire[32:]==bytes.fromhex('000000000200000002000000180859900000000001000000000000003f005890')):
            return tid,offset+request.end()
    return None


def adf_get_ready(console):
    return adf_get_continuation(console) is not None


def adf_connection_continuation(console):
    previous=adf_get_continuation(console)
    if not previous:return None
    tid,offset=previous
    free=re.search(rb'OBS FULL_ADF_CONNECT_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+rb' waiter=1 [^\r\n]*bytes=56 command=0x8001 rc=0',console[offset:])
    if not free:return None
    offset+=free.end();tail=console[offset:]
    commit=re.search(rb'OBS FULL_PINMEM_COMMIT tid='+tid+rb' slot=7 type=4 dir=2 index=0 pin_state=1 owner=0x90590818 status=0 [^\r\n]*reply=([^ ]+) lease=(\d+) request_free_rc=0 ',tail)
    if not commit:return None
    offset+=commit.end()
    freed=re.search(rb'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+rb' waiter=1 [^\r\n]*reply='+re.escape(commit[1])+rb' lease='+commit[2]+rb' bytes=56 rc=0',console[offset:])
    return (tid,offset+freed.end()) if freed else None


def adf_connection_ready(console):
    return adf_connection_continuation(console) is not None


def hdmi_pin_get_ready(console):
    previous=adf_connection_continuation(console)
    if not previous:return False
    tid,offset=previous
    commit=re.search(rb'OBS FULL_HDMIPIN_COMMIT tid='+tid+rb' slot=0 type=4 dir=1 index=0 pin_state=1 owner=0x909a015a status=0 [^\r\n]*reply=([^ ]+) lease=(\d+) request_free_rc=0 ',console[offset:])
    if not commit:return False
    offset+=commit.end()
    freed=re.search(rb'OBS FULL_HDMIPIN_NATIVE_REPLY_FREE tid='+tid+rb' sender='+tid+rb' waiter=1 destination=(0x[0-9a-f]+) [^\r\n]*reply='+re.escape(commit[1])+rb' lease='+commit[2]+rb' bytes=56 rc=0',console[offset:])
    if not freed:return False
    offset+=freed.end()
    for raw in re.findall(rb'OBS FULL_PIN_REQUEST_OBSERVE tid='+tid+rb' destination=0x90590818 source='+freed[1]+rb' bytes=64 captured=64 raw=([0-9a-f]{128})',console[offset:]):
        wire=bytes.fromhex(raw.decode())
        if (int.from_bytes(wire[:4],'little')==int(freed[1],16) and
            wire[4:20]==bytes.fromhex('a0a0a0a0010040001800000040000000') and
            wire[24:32]==bytes.fromhex('0010010028000200') and
            wire[32:]==bytes.fromhex('040000000200000000000000180859900400000001000000000000005a019a90')):return True
    return False


def post_rate_pin_request_ready(console):
    callers = {}
    for caller, lease in re.findall(rb'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*lease=(\d+) command=0x117 bytes=12 status=0 rc=0(?:\r?\n|$)', console):
        callers.setdefault(caller,set()).add(lease)
    for caller in callers:
        if len(callers[caller])>=5:
            for raw in re.findall(rb'OBS FULL_PIN_REQUEST_OBSERVE tid='+caller+
                    rb' destination=0x905a0048 [^\r\n]*bytes=48 captured=48 raw=([0-9a-f]{96})(?:\r?\n|$)',console):
                if bytes.fromhex(raw.decode())[24:32]==bytes.fromhex('0010000018000200'):
                    return True
    return False


def pin_peer_request_ready(console,audio_capabilities='off'):
    if not boot_config_waiters_ready(console,audio_capabilities,'boot','registry'):
        return False
    for caller in re.findall(rb'OBS FULL_VEF_NATIVE_REPLY_FREE tid=(\d+) sender=\1 waiter=1 [^\r\n]*bytes=56 rc=0(?:\r?\n|$)',console):
        for raw in re.findall(rb'OBS FULL_PIN_REQUEST_OBSERVE tid='+caller+
                rb' destination=0x90590818 [^\r\n]*bytes=48 captured=48 raw=([0-9a-f]{96})(?:\r?\n|$)',console):
            wire=bytes.fromhex(raw.decode())
            if wire[24:32]==bytes.fromhex('0010000018000200') and wire[32:44]==bytes.fromhex('000000000100000001000000'):
                return True
    return False


def verify_guest_overwrite(run,files,out):
    import shlex
    rows=[]
    for item in files:
        path=item['path'];expected=item['sha256']
        if not path.startswith('/') or any(c in path for c in '\r\n\0') or not re.fullmatch('[0-9a-f]{64}',expected):
            raise ValueError('Malformed overwrite readback request')
        raw=run('/usr/bin/openssl dgst -sha256 '+shlex.quote(path),timeout=30)
        values=re.findall(rb'=\s*([0-9a-fA-F]{64})\r?$',raw,re.M)
        completed=bool(re.search(rb'^MENU_DIAG_COMMAND_DONE_[^:\r\n]+:0\r?$',raw,re.M))
        actual=values[0].decode().lower() if len(values)==1 else None
        rows.append({'path':path,'expected_sha256':expected,'actual_sha256':actual,
                     'verified':completed and actual==expected,'raw_output_hex':raw.hex()})
        (out/'overwrite-guest-readback.json').write_text(json.dumps(rows,indent=2)+'\n')
        if not rows[-1]['verified']:raise RuntimeError('Guest overwrite readback differs: '+path)
    return rows


def execute_planned_command(run,at,command,log):
    header=('AT=%.1f CMD=%s\n'%(at,command)).encode()
    try:
        output=run(command,timeout=30)
    except Exception as error:
        with log.open('ab') as handle:handle.write(header+str(error).encode()+b'\n---\n')
        # The serial shell's ownership is unknown. Never send the next step.
        raise
    with log.open('ab') as handle:handle.write(header+output+b'\n---\n')
    return output


def main():
    global BASE
    def interrupted(signum,frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=None,help='Independent prepared runtime root (official and private assets must remain separate)')
    parser.add_argument('--low-latency-input',choices=('uart','mailbox-v1'),default='uart',
                        help='Explicit prepared shared-RAM input transport; no automatic UART fallback')
    parser.add_argument('--stage', choices=('mounts','drivers','init2'), default='mounts')
    parser.add_argument('--bootin-handoff',choices=('simulation-bind','p15-wrapper'),default='simulation-bind',
                        help='p15-wrapper preserves the experimental init2 entry and requires pinned experiment metadata')
    parser.add_argument('--service-profile', choices=('original','menu-filter'), default='original')
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--cpus', type=int, choices=(1,4), default=4,
                        help='default 4 matches the original cpuset shielding script')
    parser.add_argument('--stacks', action='store_true', help='explicit short ptrace snapshots of application threads')
    parser.add_argument('--census-after-vdf', action='store_true',
                        help='start host snapshots only after an original VDF waiter actually freed its reply')
    parser.add_argument('--census-after-sound-config', action='store_true',
                        help='after 25 sound, enabled capability/resolution and five original rate reply frees')
    parser.add_argument('--census-mode',choices=('host','guest','guest-proc'),default='host',
                        help='host supplies the original observer PID/base; guest retains the earlier log-polling control')
    parser.add_argument('--census-timeout',type=int,default=240,help='separate bounds for trigger wait and snapshot completion; not firmware success')
    parser.add_argument('--media-detect',type=lambda value:int(value,0),default=None,
                        help='explicit u32 value of the virtual insert-detect register; omitted disables the overlay')
    parser.add_argument('--mmc-trace',type=lambda value:int(value,0),default=None,
                        help='explicit u32 reset value of the IPSXWRP MMC trace device; omitted leaves RAM')
    parser.add_argument('--immutable-osd',choices=('off','capture'),default='off',
                        help='explicit owned HOSDAP02 snapshot saving in /log/qemu; does not change ACK')
    parser.add_argument('--sony-iomap',choices=('off','sony'),default='off',
                        help='declare the retail board fixed IO windows from the signed package DTB; no device model')
    parser.add_argument('--insmod-policy',choices=('allow-list','media','media-rm','all'),default='allow-list',
                        help='allow-list refuses modules whose hardware contract is not modeled; '
                             'all loads them anyway so the kernel log can show what really happens')
    parser.add_argument('--detect-observe',action='store_true',
                        help='interpose the media-detect state machine and log MediaInfo/RMDATAInfo '
                             'transitions (observation only, no behaviour change)')
    parser.add_argument('--card-export-at',type=float,default=None,
                        help='after this many seconds, copy the guest card image into a reserved '
                             'window in chunks and read each chunk back with QMP pmemsave')
    parser.add_argument('--card-export-on-request',action='store_true',
                        help='save on an owned input-queue close request, or at observation deadline')
    parser.add_argument('--card-export-flush',action='store_true',
                        help='require original Fsys flush, verified owner STOP and CONT around card export')
    parser.add_argument('--adaptive-first-setup',action='store_true',
                        help='instead of a fixed key plan, screenshot the running VM, recognise the '
                             'screen with screen-map.py and press the key that screen needs')
    parser.add_argument('--adaptive-interval',type=float,default=6.0)
    parser.add_argument('--adaptive-map',type=Path,default=None)
    parser.add_argument('--adaptive-seek',default=None,
                        help='scroll a menu until this screen is recognised, then optionally press ENTER. '
                             'Needed because a stored configuration also restores the menu position, so a '
                             'fixed number of DOWN presses cannot be trusted')
    parser.add_argument('--adaptive-seek-key',default='DOWN')
    parser.add_argument('--adaptive-seek-after',type=float,default=None,
                        help='only start scrolling after this many seconds, so startup keys are not disturbed')
    parser.add_argument('--adaptive-seek-enter',action='store_true')
    parser.add_argument('--adaptive-stop-screen',default=None,
                        help='stop adaptive key presses once this screen has been recognised, so a '
                             'scripted menu sequence afterwards is not disturbed')
    parser.add_argument('--adaptive-default-after',type=float,default=None,
                        help='only use --adaptive-default after this many seconds, so boot screens '
                             'are never answered blindly')
    parser.add_argument('--adaptive-default',default=None,
                        help='key to press on a screen the map does not know (once per distinct '
                             'frame). Wizard pages answer to ENTER; leave unset to never guess.')
    parser.add_argument('--config-export-at',type=float,default=None,
                        help='export the guest /setting/Backup.bin and .bak pair at this second through '
                             'the same declared window, so a configuration round trip can be validated '
                             'host-side; excludes the card export in the same run')
    parser.add_argument('--config-export-on-request', action='store_true',
                        help='after owned input-stop handshake, sync subsystem 0x2cf and export the '
                             'Backup pair on close request or observation deadline; config-only export')
    parser.add_argument('--file-media',choices=('off','card','card-rm'),default='off',
                        help='card: select the firmware own file-backed media driver so /dev/mmca is the '
                             'guest file /image_mmca seeded from the 128MiB FAT16 template; off by default')
    parser.add_argument('--key-plan',default='',
                        help='Semicolon-separated SECONDS:COMMAND entries executed once the observation '
                             'has run that long, e.g. "120:/simulation/inject-key 0x807a0020 ...". '
                             'Commands are sent verbatim to the guest shell; no value is invented here.')
    parser.add_argument('--native-display',choices=('none','gtk','sdl'),default='none',
                        help='QEMU display backend for the ramfb screen. gtk/sdl open a live '
                             'window; none keeps the run headless.')
    parser.add_argument('--key-after-marker',default='',
                        help='Fire the --key-plan commands as soon as this console marker appears, '
                             'instead of waiting for their host-second schedule. Host seconds do not '
                             'track guest time under TCG, so marker-triggered injection is the only '
                             'reliable way to hit a firmware phase.')
    parser.add_argument('--input-queue-dir',default='',
                        help='Directory polled for *.cmd files. Each file holds one guest shell '
                             'command; the runner executes it, writes the output to the matching '
                             '.out file and removes the .cmd. This is how an external UI drives '
                             'the guest without a second process talking to QEMU.')
    parser.add_argument('--observe-shutdown-write',action='store_true',help='Observe original shutdown factor stores using a QEMU data watchpoint')
    parser.add_argument('--observe-panel-tick',action='store_true',
                        help='observe screen677 controller counter entry at ELF VA 0x20acae8; '
                             'does not establish a full-camera wake-up mechanism')
    parser.add_argument('--observe-upm-reload',action='store_true',
                        help='observe the original UPM reload send at appFw+0x35a1354; '
                             'does not inject messages or imply kernel consumption')
    parser.add_argument('--observe-upm-activity',action='store_true',
                        help='observe original upm .text+0xa668 after UPM_ACTIVITY_SECTIONS; no message injection')
    parser.add_argument('--observe-system-error-source',action='store_true',help='Capture the original MODEL_SYSTEM_ERROR sender with a conditional QEMU entry probe')
    parser.add_argument('--observe-ee-transition',action='store_true',help='Bounded original EE flow execution observations; no model writes or replies')
    parser.add_argument('--observe-mode-write',action='store_true',help='Observe the original system-mode writer and call stack, without changing mode')
    parser.add_argument('--observe-input',action='store_true',help='Observe original 32-byte input receives and frees without altering dispatch')
    parser.add_argument('--gui-models',choices=('off','capture'),default='off',
                        help='Explicit bounded model capture/ownership consumer; does not implement CP model rendering')
    parser.add_argument('--gpio-c1',choices=('off','virtual'),default='off',
                        help='Model the external C1 pad in the virtual RAM-backed GPIO window')
    parser.add_argument('--remote-state',choices=('off','capture'),default='off',
                        help='Explicit finite 0x92b4086f state/ownership consumer, no CP replies')
    parser.add_argument('--bluetooth-policy',choices=('original','off'),default='original',
                        help='Use original setting or restore official Bluetooth-Off defaults through original Backup API in guest RAM')
    parser.add_argument('--live-frame-seconds',type=float,default=0.0,
                        help='While observing, dump the display to /out/live-frame.png every N seconds '
                             'so an external UI can show live pixels. 0 disables.')
    parser.add_argument('--lcd-stream-fps',type=float,default=0,
                        help='Explicit prepared LCD transport at 20..50 Hz; 0 preserves legacy frame sampling')
    parser.add_argument('--capture-osd-frames',action='store_true',
                        help='Export each persisted AP frame at the moment it is recorded, '
                             'before the firmware can recycle the buffer')
    parser.add_argument('--tcg-thread', choices=('single','multi'), default='single',
                        help='serialize unverified board models while keeping four logical guest CPUs')
    parser.add_argument('--pin-uart', action='store_true', help='explicit UART affinity-to-CPU0 experiment')
    parser.add_argument('--gic-handoff', action='store_true', help='explicit generic-virt missing SPI target initialization')
    parser.add_argument('--cntfrq', type=int, choices=(2000000,62500000), default=2000000,
                        help='Sony sched_clock/timestamp source assumes a 2 MHz architectural counter')
    parser.add_argument('--gic-boot-shim', action='store_true', help='initialize GIC targets in CPU context before the original Image')
    parser.add_argument('--imaging-service',choices=('off','release-inhibit'),default='release-inhibit',
                        help='explicit limited CP release-lock model; off preserves the unhandled RPC baseline')
    parser.add_argument('--vdf-service',choices=('off','timecode'),default='off',
                        help='finite timecode/EVF-subscription config sink; no temperature, output or camera proof')
    parser.add_argument('--system-sound-memory',action='store_true',
                        help='load original SysSound into an independently reserved VM-owned region; no audio playback')
    parser.add_argument('--audio-service',choices=('off','volume','boot'),default='off',
                        help='volume config; boot also verifies sound owner and consumes table config; no playback')
    parser.add_argument('--hdmi-service',choices=('off','definition','boot'),default='off',
                        help='shared definition config; boot adds resolution/rate configuration; no output')
    parser.add_argument('--audio-capabilities',choices=('off','inputless'),default='off',
                        help='explicit virtual P/A/Z capability owner without audio input/processing; not original configuration')
    parser.add_argument('--dig-level',choices=('off','virtual'),default='off',
                        help='explicit feature-disabled digital-level owner; no angle samples or hardware claim')
    parser.add_argument('--stall-seconds',type=int,default=0,
                        help='0 disables; else stop after this many seconds without new protocol/display records '
                             '(two consecutive quiet windows), so a dead-start fork does not burn the window')
    parser.add_argument('--osd-headless',choices=('on','off'),default='on',
                        help='on: our AP software consumer owns the OSD queue (frame container); '
                             'off: leave the queue to the original renderer so it can rasterize')
    parser.add_argument('--dmm-service',choices=('off','unit-size'),default='off',
                        help='explicit finite allocation-unit query owner; no allocation, DMA or frame transfer')
    parser.add_argument('--vef-service',choices=('off','registry'),default='off',
                        help='explicit 16-pin metadata registry/Get only; no Connect, buffers or pixels')
    parser.add_argument('--pinmem-service',choices=('off','registry'),default='off',
                        help='explicit VDF PinMemMgr 13-pin Get-only metadata owner; no allocation or Connect')
    parser.add_argument('--pin-connection',choices=('off','control'),default='off',
                        help='explicit known-edge virtual CP handshake/control backing; no format-ready or pixels')
    parser.add_argument('--infrabb-service',choices=('off','registry'),default='off',help='Explicit 21-object InfraBB GetPin registry; no connection or pixel completion')
    parser.add_argument('--drawinfo-service',choices=('off','registry'),default='off',help='Explicit 2-object DrawInfo GetPin registry, no numeric or pixel production')
    parser.add_argument('--grm-pin-service',choices=('off','registry'),default='off',help='Explicit OsdPinIF single-object Get registry; no OSD connection or pixels')
    parser.add_argument('--scalar-service',choices=('off','registry'),default='off',
                        help='explicit independent ten-pin Scalar Get-only owner; no Connect or pixel processing')
    parser.add_argument('--adf-service',choices=('off','registry'),default='off',
                        help='explicit independent ten-pin ADF found-key Get only; no Connect or pixels')
    parser.add_argument('--adf-connection',choices=('off','control'),default='off',
                        help='explicit PinMem OUT2 to ADF IN0 control handshake; no CP execution or pixels')
    parser.add_argument('--hdmi-connection',choices=('off','control'),default='off',
                        help='explicit fourth edge PinMem HDMIVIDEO OUT0 to HDMI VIDEO IN0; no HSM/HPD/driver work')
    parser.add_argument('--adf-audio-connection',choices=('off','control'),default='off',
                        help='explicit fifth edge ADF AUDIO OUT0 to HDMI AUDIO IN0; no audio hardware')
    parser.add_argument('--hdmi-pin-service',choices=('off','registry'),default='off',
                        help='explicit independent video/audio pin metadata owner; no CP diagnostics, Connect or frames')
    parser.add_argument('--scalar-connection',choices=('off','control'),default='off',
                        help='explicit PinMem OUT1 to Scalar IN4 virtual handshake; no original CP task or pixels')
    parser.add_argument('--infrabb-connection',choices=('off','control'),default='off',
                        help='explicit InfraBB YC OUT1 to VEF YC IN1 direct completion plus 80B BB format consumption; no pixels')
    parser.add_argument('--pin-format',choices=('off','cold'),default='off',
                        help='explicit new CPU-format owner with constructor defaults; no original runtime/negotiation/pixels')
    parser.add_argument('--observe-liro-loader',action='store_true',
                        help='optional independent preload records original Backup/LIRO loader arguments without changing them')
    parser.add_argument('--probe-liro-memory',action='store_true',
                        help='read-only memstart/reserved-window export after native LIRO argument observation')
    parser.add_argument('--preload-avcam',action='store_true',
                        help='explicit original-image data preload; requires loader and full-window observation')
    parser.add_argument('--pin-control-probe',action='store_true',
                        help='mounts-only new reserved control buffer backing probe; no CP task or Connect ACK')
    parser.add_argument('--usb-init',choices=('skipped','original'),default='skipped',
                        help='experimental original USB aggregate init; original removes only its initcall blacklist entry')
    parser.add_argument('--usb-platform',choices=('off','regs','full'),default='off',
                        help='single-variable original DWC3 resource-provider description; no extcon/MMIO readiness')
    parser.add_argument('--usb-controller',choices=('off','upstream-host'),default='off',
                        help='explicit verified upstream host DWC3/xHCI model, no gadget or connection proof')
    parser.add_argument('--probe-hdmi-backup',action='store_true',
                        help='explicit read-only diagnostic: report the eight original Backup unit sizes/contents; no writes or ready response')
    parser.add_argument('--probe-usb-core',action='store_true',help='read-only paused-VM USB object/resource inspection')
    parser.add_argument('--fatal-probe',action='store_true',
                        help='QEMU execution breakpoint records original boot fatal arguments; no per-thread ptrace')
    parser.add_argument('--observe-upm-notify',action='store_true',
                        help='explicit diagnostic producer and read-only original-kernel receive/API/free breakpoints; not fourth-edge acceptance')
    parser.add_argument('--until-vdf-request',action='store_true',
                        help='bounded observation ends only after an actual VDF request was captured; not camera success')
    parser.add_argument('--until-evf-subscription',action='store_true',
                        help='end after the original EVF subscription was consumed; not temperature or camera success')
    parser.add_argument('--until-pin-request',action='store_true',
                        help='capture original 48B pin request only after five original rate replies were actually freed')
    parser.add_argument('--until-pin-peer-request',action='store_true',
                        help='capture actual PinMemMgr peer request after original VEF reply release; no peer reply')
    parser.add_argument('--until-pin-format-block',action='store_true',
                        help='end only after actual AP8001 free/control write and same waiter queued at missing format consumer')
    parser.add_argument('--until-pin-format-consumed',action='store_true',
                        help='end after actual CPU format/backing consumption, last-reference release and next original Get/free')
    parser.add_argument('--until-scalar-get',action='store_true',
                        help='end after format/config checks and the same original waiter consumes Scalar Get')
    parser.add_argument('--until-scalar-connection',action='store_true',
                        help='also require second-edge original AP8001 free and natural PinMem OUT2 Get/free')
    parser.add_argument('--until-adf-get',action='store_true',
                        help='also require original ADF waiter free and subsequent OUT2 to ADF Connect request')
    parser.add_argument('--until-adf-connection',action='store_true',
                        help='require third-edge original 8001 free and subsequent PinMem type4 OUT0 Get/free')
    parser.add_argument('--until-hdmi-pin-get',action='store_true',
                        help='require original HDMI pin waiter free and next type4 PinMem-to-HDMI Connect request')
    parser.add_argument('--census-proc-delay',type=int,default=0,
                        help='explicit 0..120 guest-second delay before proc-discovered diagnostic sampling')
    parser.add_argument('--backup-log-profile',choices=('all','sampled'),default='all',
                        help='diagnostic only: sample Backup send logs (first 8 then powers of two); all transport errors retained')
    parser.add_argument('--serial-diagnostic-seconds',type=int,default=60,
                        help='declared total end-diagnostic budget, 30..180s; all completion markers remain mandatory')
    parser.add_argument('--census-proc-samples',type=int,choices=(1,2),default=1,
                        help='one or two samples of the same discovered PID; two samples have a 30 guest-second interval')
    parser.add_argument('--observe-uart-input',action='store_true',
                        help='pre-scheduled read-only fd/termios/IRQ snapshots using inherited fd0; no input read or TTY open')
    parser.add_argument('--probe-uart-rx',action='store_true',
                        help='diagnostic only: send one empty line at 60s and read safe UART/GIC flags before/after')
    parser.add_argument('--probe-uart-command',action='store_true',
                        help='diagnostic only: after the RX readback, send one harmless echo with its real RC sentinel')
    args = parser.parse_args()
    if args.bootin_handoff=='p15-wrapper' and args.stage!='init2':
        parser.error('p15-wrapper bootin handoff requires init2')
    if args.config_export_on_request and (args.stage!='init2' or not args.input_queue_dir
            or args.config_export_at is not None or args.card_export_at is not None):
        parser.error('--config-export-on-request requires init2, an input queue, and no timed exports')
    if args.card_export_on_request and (args.card_export_at is not None or not args.input_queue_dir
            or not args.card_export_flush):
        parser.error('--card-export-on-request requires an input queue and flush, and excludes timed export')
    if args.card_export_flush and (not (args.card_export_at is not None or args.card_export_on_request)
            or args.file_media!='card' or args.stage!='init2'):
        parser.error('--card-export-flush requires init2, --file-media card and a card export trigger')
    if args.config_export_at is not None and (
            args.card_export_at is not None or args.card_export_on_request):
        parser.error('--config-export-at reuses the declared export window; it cannot run with a card export')
    if args.runtime is not None:BASE=args.runtime.resolve()/'analysis'
    if not 30<=args.serial_diagnostic_seconds<=180:
        parser.error('--serial-diagnostic-seconds must be between 30 and 180')
    if not 0<=args.census_proc_delay<=120 or (args.census_proc_delay and (not args.stacks or args.census_mode!='guest-proc')):
        parser.error('Proc census delay requires guest-proc stacks and must be 0..120')
    if args.census_proc_samples!=1 and (not args.stacks or args.census_mode!='guest-proc'):
        parser.error('Repeated proc census requires guest-proc stacks')
    if args.backup_log_profile!='all' and args.stage!='init2':
        parser.error('Backup log sampling requires init2')
    if args.scalar_service!='off' and args.stage!='init2':
        parser.error('Scalar registry requires init2')
    if args.infrabb_service!='off' and args.stage!='init2':
        parser.error('InfraBB registry requires init2')
    if args.drawinfo_service!='off' and args.stage!='init2':
        parser.error('DrawInfo registry requires init2')
    if args.grm_pin_service!='off' and args.stage!='init2':
        parser.error('GRM pin registry requires init2')
    if args.adf_service!='off' and args.stage!='init2':
        parser.error('ADF registry requires init2')
    if args.hdmi_pin_service!='off' and args.stage!='init2':
        parser.error('HDMI pin registry requires init2')
    if args.until_hdmi_pin_get and (args.hdmi_pin_service!='registry' or not args.until_adf_connection):
        parser.error('HDMI pin observation requires registry and --until-adf-connection')
    if args.until_adf_get and (args.adf_service!='registry' or not args.until_scalar_connection):
        parser.error('ADF Get observation requires registry and --until-scalar-connection')
    if args.adf_connection!='off' and (args.adf_service!='registry' or args.scalar_connection!='control'):
        parser.error('ADF connection requires ADF registry and Scalar control connection')
    if args.until_adf_connection and (args.adf_connection!='control' or not args.until_adf_get):
        parser.error('ADF connection observation requires control and --until-adf-get')
    if args.until_scalar_get and (args.scalar_service!='registry' or not args.until_pin_format_consumed):
        parser.error('Scalar Get observation requires registry and --until-pin-format-consumed')
    if args.scalar_connection!='off' and (args.scalar_service!='registry' or args.pin_format!='cold' or args.pin_connection!='control'):
        parser.error('Scalar connection requires Scalar registry and the cold control-format profile')
    if args.until_scalar_connection and (args.scalar_connection!='control' or not args.until_scalar_get):
        parser.error('Scalar connection observation requires --until-scalar-get and Scalar control connection')
    if args.infrabb_connection!='off' and (args.infrabb_service!='registry' or args.vef_service!='registry'):
        parser.error('InfraBB connection requires both InfraBB and VEF registries')
    if not 1 <= args.seconds <= 1200:
        parser.error('--seconds must be between 1 and 1200')
    if args.media_detect is not None:
        if not 0 <= args.media_detect <= 0xffffffff:
            parser.error('--media-detect must fit an unsigned 32-bit register')
        if args.usb_controller != 'upstream-host' or args.sony_iomap != 'sony':
            parser.error('--media-detect requires the dedicated QEMU and --sony-iomap sony')
    if not 30<=args.census_timeout<=600:
        parser.error('--census-timeout must be between 30 and 600')
    if args.gic_boot_shim and (args.pin_uart or args.gic_handoff):
        parser.error('Boot shim and post-kernel routing experiments must be separate')
    if args.fatal_probe and (args.stacks or args.stage!='init2'):
        parser.error('The original fatal probe requires init2 without thread tracing')
    if args.adaptive_seek and (not args.adaptive_first_setup or not args.adaptive_stop_screen):
        parser.error('Adaptive menu search requires adaptive startup and an explicit startup stop screen')
    if sum((args.observe_shutdown_write,args.observe_system_error_source,args.observe_ee_transition,args.observe_mode_write,args.observe_panel_tick,args.observe_upm_reload,args.observe_upm_activity))>1:
        parser.error('Select only one original error-source debugger experiment')
    if (args.observe_shutdown_write or args.observe_system_error_source or args.observe_ee_transition or args.observe_mode_write or args.observe_panel_tick or args.observe_upm_reload or args.observe_upm_activity) and (args.stage!='init2' or args.fatal_probe or args.observe_upm_notify or args.stacks):
        parser.error('--observe-shutdown-write requires init2 without another debugger or stack capture')
    if (args.observe_shutdown_write or args.observe_system_error_source or args.observe_ee_transition or args.observe_mode_write or args.observe_panel_tick or args.observe_upm_reload or args.observe_upm_activity) and args.capture_osd_frames:
        parser.error('Shutdown write watch cannot share the observation loop with pausing OSD memory captures')
    if (args.observe_ee_transition or args.observe_mode_write) and (args.card_export_at is not None or args.card_export_on_request):
        parser.error('EE execution observation cannot share a session with pausing card exports')
    if (args.observe_panel_tick or args.observe_upm_reload or args.observe_upm_activity) and (
            args.card_export_at is not None or args.card_export_on_request or args.config_export_at is not None):
        parser.error('Execution observation cannot share a session with pausing card or config exports')
    if args.config_export_on_request and any((args.observe_shutdown_write, args.observe_system_error_source,
            args.observe_ee_transition, args.observe_mode_write, args.observe_panel_tick, args.observe_upm_reload, args.observe_upm_activity)):
        parser.error('Execution observation cannot share a session with pausing config exports')
    if args.observe_upm_notify and (args.stage!='init2' or args.stacks or args.fatal_probe or args.observe_uart_input or
            args.hdmi_pin_service!='registry' or args.adf_connection!='control' or
            any(value for name,value in vars(args).items() if name.startswith('until_'))):
        parser.error('UPM observation requires init2/HDMI pin registry/third control edge and no other tracing or until condition')
    if args.usb_platform=='full' and args.usb_controller!='upstream-host':
        parser.error('Full USB platform description requires an actual DWC3 MMIO model')
    if args.until_vdf_request and (args.stage!='init2' or args.stacks):
        parser.error('VDF request observation requires init2 without thread tracing')
    if args.until_evf_subscription and (args.stage!='init2' or args.stacks or
                                        args.vdf_service!='timecode' or args.until_vdf_request):
        parser.error('EVF subscription observation requires untraced init2/timecode and no other stop condition')
    if args.until_pin_request and (args.stage!='init2' or args.stacks or args.until_vdf_request or
                                  args.until_evf_subscription or args.until_pin_peer_request or args.hdmi_service!='boot' or args.vef_service!='off'):
        parser.error('Pin request capture requires untraced init2/HDMI boot and no other stop condition')
    if args.until_pin_peer_request and (args.stage!='init2' or args.stacks or args.until_vdf_request or
                                        args.until_evf_subscription or args.until_pin_request or
                                        args.hdmi_service!='boot' or args.vef_service!='registry' or args.audio_service!='boot' or args.pinmem_service!='off'):
        parser.error('Pin peer capture requires untraced init2, HDMI/audio boot, VEF registry and no other stop condition')
    if args.census_after_vdf and (not args.stacks or args.census_mode!='host' or
                                  args.stage!='init2' or args.vdf_service!='timecode'):
        parser.error('Post-VDF census requires init2, host stacks and the timecode profile')
    if args.census_after_sound_config and (not args.stacks or args.census_mode!='host' or
                                         args.stage!='init2' or args.audio_service!='boot' or args.census_after_vdf):
        parser.error('Post-sound census requires init2, host stacks, boot audio and no other census trigger')
    if args.system_sound_memory and args.stage!='init2':
        parser.error('System sound memory owner requires the explicit init2 boot wrapper')
    if args.audio_service=='boot' and not args.system_sound_memory:
        parser.error('Boot audio configuration requires --system-sound-memory')
    if args.hdmi_service!='off' and args.stage!='init2':
        parser.error('HDMI definition configuration requires the explicit init2 boot wrapper')
    if args.audio_capabilities!='off' and (args.stage!='init2' or args.audio_service!='boot'):
        parser.error('Audio capability owner requires init2 and --audio-service boot')
    if (args.hdmi_connection!='off' or args.adf_audio_connection!='off') and args.stage!='init2':
        parser.error('Fourth/fifth edge owners require the explicit init2 wrapper')
    if args.hdmi_connection!='off' and (args.hdmi_pin_service!='registry' or args.adf_connection!='control'):
        parser.error('Fourth edge requires HDMI pin registry and the third control edge')
    if args.adf_audio_connection!='off' and (args.hdmi_pin_service!='registry' or args.adf_connection!='control'):
        parser.error('Fifth edge requires HDMI pin registry and the third control edge')
    if (args.dig_level!='off' or args.dmm_service!='off') and args.stage!='init2':
        parser.error('Startup digital-level/DMM owners require the explicit init2 wrapper')
    if args.probe_hdmi_backup and (args.stage!='init2' or args.stacks or args.fatal_probe or
            args.observe_upm_notify or args.observe_uart_input):
        parser.error('HDMI Backup probe requires untraced init2 without other diagnostic observers')
    if args.observe_liro_loader and (args.stage!='init2' or args.service_profile!='original'):
        parser.error('LIRO loader observation requires original init2 service profile')
    if args.probe_liro_memory and not args.observe_liro_loader:
        parser.error('LIRO reserved-memory probe requires --observe-liro-loader')
    if args.preload_avcam and (args.stage!='init2' or not args.observe_liro_loader or not args.probe_liro_memory):
        parser.error('Original av-cam data preload requires init2, --observe-liro-loader and --probe-liro-memory')
    if args.pin_control_probe and (args.stage!='mounts' or args.stacks):
        parser.error('Pin control backing probe requires mounts stage without thread tracing')
    if args.observe_uart_input and args.stage!='init2':
        parser.error('UART input observation requires init2')
    if args.probe_uart_rx and (not args.observe_uart_input or args.seconds<65):
        parser.error('UART RX probe requires UART input observation and at least 65 seconds')
    if args.probe_uart_command and (not args.probe_uart_rx or args.seconds<90):
        parser.error('UART command probe requires RX observation and at least 90 seconds')
    if args.pin_connection=='control' and (args.stage!='init2' or args.stacks or args.service_profile!='original' or
                                           args.vef_service!='registry' or args.pinmem_service!='registry'):
        parser.error('Pin control connection requires original untraced init2 and both explicit pin registries')
    if args.pin_format!='off' and args.pin_connection!='control':
        parser.error('Cold CPU format owner requires --pin-connection control')
    if args.until_pin_format_block and (args.pin_connection!='control' or args.pin_format!='off' or args.audio_service!='boot' or args.hdmi_service!='boot' or
                                        args.until_vdf_request or args.until_evf_subscription or args.until_pin_request or args.until_pin_peer_request):
        parser.error('Pin format boundary requires control connection, HDMI/audio boot and no other stop condition')
    if args.until_pin_format_consumed and (args.pin_format!='cold' or args.audio_service!='boot' or args.hdmi_service!='boot' or
                                           args.until_vdf_request or args.until_evf_subscription or args.until_pin_request or args.until_pin_peer_request or args.until_pin_format_block):
        parser.error('Consumed format observation requires cold format, HDMI/audio boot and no other stop condition')
    if args.vef_service!='off' and args.stage!='init2':
        parser.error('VEF registry requires the explicit init2 wrapper')
    if args.pinmem_service!='off' and args.stage!='init2':
        parser.error('PinMemMgr registry requires the explicit init2 wrapper')
    if not (BASE/'full-system.json').is_file():
        parser.error('Prepare a private dump runtime first')
    # Separate from the official firmware runtime lock and every prior run.
    try:
        lock = runpy.run_path(str(HERE/'runtime-lock.py'))['open_runtime_lock'](BASE.parent)
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    (BASE/'runs').mkdir(exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=BASE/'runs'))
    (BASE/'latest-run.txt').write_text(out.name+'\n')
    manifest = json.loads((BASE/'full-system.json').read_text())
    lcd_api=runpy.run_path(str(HERE/'lcd-stream.py'))
    lcd_api['validate_runtime'](BASE.parent,args.lcd_stream_fps)
    if args.lcd_stream_fps and args.stage!='init2':
        raise ValueError('LCD streaming requires the original init2 boot wrapper')
    low_input_api=runpy.run_path(str(HERE/'low-latency-input.py'))
    low_input_api['validate_runtime'](BASE.parent,args.low_latency_input)
    if args.low_latency_input=='mailbox-v1' and (args.stage!='init2' or args.cpus!=4 or not args.input_queue_dir):
        raise ValueError('Mailbox input requires owned init2, four CPUs and an input directory')
    try:
        bootin_experiment=validate_bootin_handoff(args.stage,args.bootin_handoff,manifest,BASE)
    except (OSError,ValueError) as error:
        parser.error(str(error))
    manifest['host_serial_transport']={'source':'serial-console.py','sha256':hashlib.sha256((HERE/'serial-console.py').read_bytes()).hexdigest(),
                                      'completion_policy':'exact unpredictable tag from raw bytes, original RC, no log-line filtering'}
    (out/'host-serial-console.py').write_bytes((HERE/'serial-console.py').read_bytes())
    manifest['experiment'] = {name:str(value) if isinstance(value,Path) else value for name,value in vars(args).items()}
    manifest['native_dependency_snapshot'] = NATIVE_INPUT.name
    manifest['runner_source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.observe_panel_tick:
        manifest['panel_tick_probe_source_sha256']=hashlib.sha256((HERE/'panel-tick-probe.py').read_bytes()).hexdigest()
    if args.observe_upm_reload:
        manifest['upm_reload_probe_source_sha256']=hashlib.sha256((HERE/'upm-reload-probe.py').read_bytes()).hexdigest()
        manifest['upm_reload_base_source_sha256']=hashlib.sha256((HERE/'panel-tick-probe.py').read_bytes()).hexdigest()
    if args.observe_upm_activity:
        manifest['upm_activity_probe_source_sha256']=hashlib.sha256((HERE/'upm-activity-probe.py').read_bytes()).hexdigest()
        manifest['upm_activity_base_source_sha256']=hashlib.sha256((HERE/'panel-tick-probe.py').read_bytes()).hexdigest()
    if args.observe_shutdown_write:
        manifest['shutdown_watch_source_sha256']=hashlib.sha256((HERE/'shutdown-watch.py').read_bytes()).hexdigest()
    if args.observe_system_error_source:
        manifest['system_error_probe_source_sha256']=hashlib.sha256((HERE/'system-error-source.py').read_bytes()).hexdigest()
    if args.observe_ee_transition:
        manifest['ee_transition_probe_source_sha256']=hashlib.sha256((HERE/'ee-transition-probe.py').read_bytes()).hexdigest()
    if args.observe_mode_write:
        manifest['mode_write_probe_source_sha256']=hashlib.sha256((HERE/'mode-write-probe.py').read_bytes()).hexdigest()
        manifest['mode_write_base_source_sha256']=hashlib.sha256((HERE/'shutdown-watch.py').read_bytes()).hexdigest()
    manifest['host_runner_pid'] = os.getpid()
    for enabled,names in (
            (args.gui_models=='capture',('gui-models.c','gui-models.h')),
            (args.remote_state=='capture',('remote-state.c','remote-state.h')),
            (args.audio_service!='off',('audio-device.c','audio-device.h')),
            (args.dig_level!='off',('dig-level-device.c','dig-level-device.h')),
            (args.dmm_service!='off',('dmm-device.c','dmm-device.h'))):
        if enabled:
            for name in names:
                if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                    raise RuntimeError('Rebuild explicit startup owner source: '+name)
    if args.gpio_c1=='virtual':
        if manifest.get('gpio_pad_source_sha256')!=hashlib.sha256((HERE/'gpio-pad-state.c').read_bytes()).hexdigest() or \
           manifest.get('gpio_pad_program_sha256')!=hashlib.sha256((BASE/'root/simulation/gpio-pad-state').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild explicit virtual GPIO pad program')
    if args.bluetooth_policy=='off':
        if manifest.get('bluetooth_policy_source_sha256')!=hashlib.sha256((HERE/'bluetooth-policy.c').read_bytes()).hexdigest() or \
           manifest.get('bluetooth_policy_program_sha256')!=hashlib.sha256((BASE/'root/simulation/bluetooth-policy').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild original Bluetooth preference adapter')
    if args.detect_observe:
        if manifest.get('detect_observe_source_sha256')!=hashlib.sha256((HERE/'detect-observe.c').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the media-detect observer: source changed')
        if manifest.get('detect_observe_program_sha256')!=hashlib.sha256((BASE/'root/simulation/detect-observe.so').read_bytes()).hexdigest():
            raise RuntimeError('Media-detect observer program identity differs')
    if args.file_media!='off':
        # The preload flips EXISTMEDIADRIVER so the ORIGINAL mcmn_init selects the
        # file backend; a stale binary or template would silently test nothing.
        if manifest.get('file_media_config_source_sha256')!=hashlib.sha256((HERE/'file-media-config.c').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the file media backend preload: source changed')
        if manifest.get('file_media_config_program_sha256')!=hashlib.sha256((BASE/'root/simulation/file-media-config.so').read_bytes()).hexdigest():
            raise RuntimeError('File media backend preload program identity differs')
        if manifest.get('file_media_template_source_sha256')!=hashlib.sha256((HERE/'file-media-template.py').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the file media card template adapter')
        if manifest.get('file_media_template_sha256')!=hashlib.sha256((BASE/'root/simulation/media-template.fat').read_bytes()).hexdigest():
            raise RuntimeError('File media card template identity differs')
        for name in ('file-media-flush-hook.c','file-media-flush-hook.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild file media flush integration: '+name)
        # The RM/media provider is what makes the app see a card; a stale build here
        # would again produce a pristine card and look like a firmware decision.
        for key,name in (('rm_file_device','rm-file-device.c'),('rm_file_preload','rm-file-preload.c'),
                         ('rm_file_header','rm-file-device.h')):
            if manifest.get(key+'_source_sha256')!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild the file media RM provider: source changed: '+name)
        if manifest.get('rm_file_program_sha256')!=hashlib.sha256((BASE/'root/simulation/rm-file.so').read_bytes()).hexdigest():
            raise RuntimeError('File media RM provider program identity differs')
    if args.observe_upm_notify:
        for name in ('upm-message-probe.py','upm-notify-check.c','guest/upm-notify-observe.sh','boot-fatal-probe.py'):
            if manifest.get('adapter_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit UPM observation adapter: '+name)
        if manifest.get('upm_notify_program_sha256')!=hashlib.sha256((BASE/'root/simulation/upm-notify-check').read_bytes()).hexdigest():
            raise RuntimeError('UPM diagnostic producer program identity differs')
    if args.probe_hdmi_backup:
        if manifest.get('adapter_sources',{}).get('hdmi-backup-probe.c')!=hashlib.sha256((HERE/'hdmi-backup-probe.c').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the explicit HDMI Backup probe first')
        if manifest.get('hdmi_backup_probe_program_sha256')!=hashlib.sha256((BASE/'root/simulation/hdmi-backup-probe').read_bytes()).hexdigest():
            raise RuntimeError('HDMI Backup probe program identity differs')
    if args.hdmi_connection!='off' or args.adf_audio_connection!='off':
        for name in ('hdmi-connection.c','hdmi-connection.h','adf-audio-connection.c','adf-audio-connection.h',
                     'pin-peer-connection.inc','hdmi-pin-device.c','hdmi-pin-device.h','pin-registry-core.c','pin-registry-core.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit HDMI/ADF-audio connection source: '+name)
    if args.hdmi_pin_service!='off':
        for name in ('hdmi-pin-device.c','hdmi-pin-device.h','pin-registry-core.c','pin-registry-core.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit HDMI pin registry source: '+name)
    if args.adf_service!='off':
        for name in ('adf-device.c','adf-device.h','pin-registry-core.c','pin-registry-core.h','adf-connection.c','adf-connection.h','pin-peer-connection.inc','scalar-connection.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit ADF registry source: '+name)
    if args.scalar_service!='off':
        for name in ('scalar-device.c','scalar-device.h','pin-registry-core.c','pin-registry-core.h','scalar-connection.c','scalar-connection.h','pin-peer-connection.inc','adf-device.h','adf-connection.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit Scalar registry source: '+name)
    if args.infrabb_connection=='control':
        for name in ('infrabb-connection.c','infrabb-connection.h','vef-bb-post.c','vef-bb-post.h','vef-bb-format.c','vef-bb-format.h','pin-peer-connection.inc','scalar-connection.h','scalar-device.h','adf-device.h','adf-connection.h','pinmem-device.h','vef-device.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit InfraBB connection source: '+name)
    if args.infrabb_service!='off':
        for name in ('infrabb-device.c','infrabb-device.h','pin-registry-core.c','pin-registry-core.h','vef-device.c','vef-device.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit InfraBB registry source: '+name)
    if args.drawinfo_service!='off':
        for name in ('drawinfo-device.c','drawinfo-device.h','pin-registry-core.c','pin-registry-core.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit DrawInfo registry source: '+name)
    if args.grm_pin_service!='off':
        for name in ('grm-pin-device.c','grm-pin-device.h','pin-registry-core.c','pin-registry-core.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit GRM registry source: '+name)
    if args.observe_uart_input:
        if manifest.get('adapter_sources',{}).get('uart-input-observe.c')!=hashlib.sha256((HERE/'uart-input-observe.c').read_bytes()).hexdigest() or \
           manifest.get('uart_input_probe_program_sha256')!=hashlib.sha256((BASE/'root/simulation/uart-input-observe').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild explicit UART input observer before enabling it')
    if args.observe_liro_loader:
        observer=manifest.get('liro_observer',{})
        if observer.get('source_sha256')!=hashlib.sha256((HERE/'liro-observe.c').read_bytes()).hexdigest() or \
           observer.get('program_sha256')!=hashlib.sha256((BASE/'root/simulation/liro-observe.so').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the explicit LIRO observation module before enabling it')
    if args.probe_liro_memory:
        manifest['liro_memory_probe_source_sha256']=hashlib.sha256((HERE/'liro-memory-probe.py').read_bytes()).hexdigest()
    pin_control_reservation=None
    if args.pin_control_probe or args.pin_connection=='control':
        for name in ('reserved-region.py','pin-buffer-region.py','pin-buffer-owner.c','pin-buffer-owner.h','pin-buffer-guest.c','pin-buffer-probe.c'):
            if manifest.get('adapter_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild explicit pin control backing adapter: '+name)
        if args.pin_control_probe and manifest.get('pin_control_probe_program_sha256')!=hashlib.sha256((BASE/'root/simulation/pin-control-probe').read_bytes()).hexdigest():
            raise RuntimeError('Pin control backing probe program identity differs')
        if args.pin_connection=='control':
            for name in ('pin-connection.c','pin-connection.h','pin-buffer-wire.c','pin-buffer-wire.h',
                         'pin-buffer-owner.c','pin-buffer-owner.h','pin-buffer-guest.c','pin-registry-core.c','pin-registry-core.h',
                         'vef-device.c','vef-device.h','pinmem-device.c','pinmem-device.h','pin-format.c','pin-format.h','pin-request-observe.h'):
                if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                    raise RuntimeError('Rebuild explicit connection device source: '+name)
            if manifest['imaging_observer']['observer_sha256']!=hashlib.sha256((BASE/'root/simulation/menu-observe.so').read_bytes()).hexdigest():
                raise RuntimeError('Connection observer program identity differs')
        region=runpy.run_path(str(HERE/'pin-buffer-region.py'))
        workspace=(BASE/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt').read_text()
        pin_control_reservation=region['validate_reservation'](workspace)
        manifest['virtual_pin_control']={'physical':region['PHYSICAL'],'capacity':region['CAPACITY'],
            'cp_virtual':region['CP_VIRTUAL'],'slots':region['SLOTS'],'slot_bytes':region['SLOT_BYTES'],
            'original_pool_policy_verified':False,'original_CP_task_running_verified':False}
    sound_reservation=None
    if args.system_sound_memory:
        expected=manifest.get('adapter_sources',{}).get('system-sound-region.py')
        if expected!=hashlib.sha256((HERE/'system-sound-region.py').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the explicit system-sound reservation adapter before enabling it')
        sound=runpy.run_path(str(HERE/'system-sound-region.py'))
        workspace=(BASE/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt').read_text()
        sound_reservation=sound['validate_reservation'](workspace)
        manifest['virtual_system_sound']={'physical':sound['PHYSICAL'],'capacity':sound['CAPACITY'],
                                         'reservation':sound_reservation,'original_allocator_verified':False}
    card_export_reservation=None
    if args.card_export_at is not None or args.card_export_on_request or args.config_export_at is not None or args.config_export_on_request:
        expected=manifest.get('adapter_sources',{}).get('card-export-region.py')
        if expected!=hashlib.sha256((HERE/'card-export-region.py').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the explicit card-export reservation adapter before enabling it')
        if manifest.get('card_export_source_sha256')!=hashlib.sha256((HERE/'card-export.c').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the guest card-export helper: source changed')
        if manifest.get('card_export_program_sha256')!=hashlib.sha256((BASE/'root/simulation/card-export').read_bytes()).hexdigest():
            raise RuntimeError('Guest card-export helper identity differs')
        if args.card_export_flush:
            expected=manifest.get('adapter_sources',{}).get('sd_flush_barrier.py')
            if expected!=hashlib.sha256((HERE/'sd_flush_barrier.py').read_bytes()).hexdigest():
                raise RuntimeError('Rebuild the native SD flush protocol adapter')
        region=runpy.run_path(str(HERE/'card-export-region.py'))
        workspace=(BASE/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt').read_text()
        card_export_reservation=region['validate_reservation'](workspace)
        manifest['card_export']={'physical':region['PHYSICAL'],'capacity':region['CAPACITY'],
                                 'reservation':card_export_reservation}
    if args.config_export_on_request:
        for field, path in (('backup_sync_source_sha256', HERE/'backup-sync.c'),
                            ('backup_sync_program_sha256', BASE/'root/simulation/backup-sync')):
            if manifest.get(field) != hashlib.sha256(path.read_bytes()).hexdigest():
                raise RuntimeError('Rebuild original Backup sync helper: ' + field)
    if args.usb_controller=='upstream-host':
        usb_program=HERE/'runtime/usb-qemu/qemu-system-aarch64'
        usb_identity=json.loads((usb_program.parent/'manifest.json').read_text())
        if hashlib.sha256(usb_program.read_bytes()).hexdigest()!=usb_identity['program_sha256']:
            raise RuntimeError('Dedicated USB QEMU program identity differs')
        if hashlib.sha256((HERE/'usb-qemu-board.py').read_bytes()).hexdigest()!=usb_identity['board_layer_sha256']:
            raise RuntimeError('Dedicated USB QEMU source layer differs; rebuild first')
        manifest['usb_controller_program']=usb_identity
    if args.immutable_osd=='capture':
        for name in ('full-osd-snapshot.c','full-osd-snapshot.h','guest-stat-compat.h'):
            if manifest.get('imaging_observer',{}).get('device_sources',{}).get(name)!=hashlib.sha256((HERE/name).read_bytes()).hexdigest():
                raise RuntimeError('Rebuild immutable OSD source: '+name)
    if args.sony_iomap=='sony':
        if manifest.get('adapter_sources',{}).get('sony-iomap.py')!=hashlib.sha256((HERE/'sony-iomap.py').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the explicit Sony iomap adapter before enabling it')
    usb_probe=None
    if args.usb_init=='original' or args.usb_platform!='off' or args.probe_usb_core:
        usb_probe=runpy.run_path(str(HERE/'usb-core-probe.py'))['probe']
        kernel=BASE/'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        manifest['usb_probe_kernel_sha256']=hashlib.sha256(kernel.read_bytes()).hexdigest()
    with (BASE/'full-system.cpio').open('rb') as image:
        actual_initrd = hashlib.file_digest(image,'sha256').hexdigest()
    if manifest.get('initrd_sha256') != actual_initrd:
        raise RuntimeError('Private initramfs differs; rebuild its explicit adapters first')
    if hashlib.sha256((BASE/'qemu-kernel-probe.sh').read_bytes()).hexdigest()!=manifest['board_adapter_sha256']:
        raise RuntimeError('Board adapter differs from the built private manifest')
    if args.gic_boot_shim and hashlib.sha256((BASE/'boot-handoff.bin').read_bytes()).hexdigest()!=manifest['boot_handoff_sha256']:
        raise RuntimeError('Boot handoff differs from the built private manifest')
    avcam_image=None
    if args.preload_avcam:
        if manifest.get('adapter_sources',{}).get('avcam-preload.py')!=hashlib.sha256((HERE/'avcam-preload.py').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the explicit av-cam data preload adapter before enabling it')
        preload=runpy.run_path(str(HERE/'avcam-preload.py'))
        kernel=BASE/'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
        if preload['digest'](kernel)!=preload['KERNEL_SHA256']:
            raise RuntimeError('Preload requires the original Sony memrsv kernel')
        workspace=(BASE/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt').read_text()
        identity=preload['validate_plan'](workspace,[('kernel',0x400080000,kernel.stat().st_size),
            ('initrd',0x440000000,(BASE/'full-system.cpio').stat().st_size),('boot handoff',0x400010000,96)])
        avcam_image=preload['ensure_image'](BASE)
        manifest['avcam_preload']={**identity,'image':str(avcam_image),'original_module_arguments_changed':False}
    (out/'inputs.json').write_text(json.dumps(manifest,indent=2)+'\n')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('MENU_','QEMU_','SONY_'))}
    env.update(QEMU_OUTPUT_DIR=str(out), QEMU_TIMEOUT_SECONDS='0', QEMU_UI_LIVE='1',
               SONY_TIMER_MODEL='1', SONY_DMM_SERVICE='1', MENU_NATIVE_WINDOW='1', QEMU_NATIVE_DISPLAY=args.native_display,
               QEMU_TRACE_FLAGS='guest_errors,unimp', QEMU_FULL_SMP=str(args.cpus), QEMU_TCG_THREAD=args.tcg_thread,
               QEMU_ARCH_CNTFRQ=str(args.cntfrq),QEMU_FULL_USB_INIT=args.usb_init,
               QEMU_FULL_USB_PLATFORM=args.usb_platform)
    env['QEMU_FULL_USB_CONTROLLER']=args.usb_controller
    env['QEMU_FULL_ADAPTER_DIR']=str(HERE)
    if args.media_detect is not None:
        env['QEMU_SONY_MEDIA_DETECT']=f'{args.media_detect:#010x}'
    if args.mmc_trace is not None:
        if not 0 <= args.mmc_trace <= 0xffffffff:
            parser.error('--mmc-trace must be a u32')
        env['QEMU_SONY_MMC_TRACE']=f'{args.mmc_trace:#010x}'
    if args.usb_controller=='upstream-host':env['QEMU_SYSTEM_DIR']=str(usb_program.parent)
    if args.gic_boot_shim:env['QEMU_FULL_BOOT_SHIM']='1'
    if args.fatal_probe or args.observe_upm_notify or args.observe_shutdown_write or args.observe_system_error_source or args.observe_ee_transition or args.observe_mode_write or args.observe_panel_tick or args.observe_upm_reload or args.observe_upm_activity:env['QEMU_FULL_FATAL_PROBE']='1'
    if args.observe_upm_notify:env['QEMU_FULL_UPM_PROBE']='1'
    if avcam_image:
        env['QEMU_FULL_AVCAM_PRELOAD']='1'
        env['QEMU_FULL_AVCAM_IMAGE']=str(avcam_image)
    handoff=[]
    if args.bootin_handoff=='p15-wrapper':handoff.append('fullsystem.bootin-handoff=p15-wrapper')
    if args.pin_uart:handoff.append('fullsystem.uart_pin=1')
    if args.gic_handoff:handoff.append('fullsystem.gic_handoff=1')
    if args.imaging_service=='release-inhibit':handoff.append('fullsystem.imaging=release-inhibit')
    if args.vdf_service=='timecode':handoff.append('fullsystem.vdf=timecode')
    if args.audio_service in ('volume','boot'):handoff.append('fullsystem.audio='+args.audio_service)
    if args.hdmi_service in ('definition','boot'):handoff.append('fullsystem.hdmi='+args.hdmi_service)
    if args.audio_capabilities=='inputless':handoff.append('fullsystem.audio-caps=inputless')
    if args.osd_headless=='off':handoff.append('fullsystem.osd-headless=off')
    if args.dig_level=='virtual':handoff.append('fullsystem.dig-level=virtual')
    if args.dmm_service=='unit-size':handoff.append('fullsystem.dmm=unit-size')
    if args.insmod_policy=='all':handoff.append('fullsystem.insmod=all')
    if args.detect_observe:handoff.append('fullsystem.detect-observe=1')
    if args.detect_observe:
        if manifest.get('detect_observe_source_sha256')!=hashlib.sha256((HERE/'detect-observe.c').read_bytes()).hexdigest():
            raise RuntimeError('Rebuild the media-detect observer: source changed')
        if manifest.get('detect_observe_program_sha256')!=hashlib.sha256((BASE/'root/simulation/detect-observe.so').read_bytes()).hexdigest():
            raise RuntimeError('Media-detect observer program identity differs')
    if args.file_media!='off':handoff.append('fullsystem.file-media='+args.file_media)
    if args.sony_iomap=='sony':handoff.append('fullsystem.iomap=sony')
    if args.observe_liro_loader:handoff.append('fullsystem.liro-observe=1')
    if args.vef_service=='registry':handoff.append('fullsystem.vef=registry')
    if args.pinmem_service=='registry':handoff.append('fullsystem.pinmem=registry')
    if args.pin_connection=='control':handoff.append('fullsystem.pin-connect=control')
    if args.pin_format=='cold':handoff.append('fullsystem.pin-format=cold')
    if args.scalar_service=='registry':handoff.append('fullsystem.scalar=registry')
    if args.infrabb_service=='registry':handoff.append('fullsystem.infrabb=registry')
    if args.drawinfo_service=='registry':handoff.append('fullsystem.drawinfo=registry')
    if args.grm_pin_service=='registry':handoff.append('fullsystem.grmpin=registry')
    if args.adf_service=='registry':handoff.append('fullsystem.adf=registry')
    if args.adf_connection=='control':handoff.append('fullsystem.adf-connect=control')
    if args.hdmi_pin_service=='registry':handoff.append('fullsystem.hdmi-pin=registry')
    if args.hdmi_connection=='control':handoff.append('fullsystem.hdmi-connect=control')
    if args.adf_audio_connection=='control':handoff.append('fullsystem.adf-audio-connect=control')
    if args.scalar_connection=='control':handoff.append('fullsystem.scalar-connect=control')
    if args.infrabb_connection=='control':handoff.append('fullsystem.infrabb-connect=control')
    if args.backup_log_profile=='sampled':handoff.append('fullsystem.backup-log=sampled')
    if sound_reservation:handoff.extend(('fullsystem.sound-owner=1',sound_reservation))
    if card_export_reservation:handoff.append(card_export_reservation)
    if pin_control_reservation:handoff.extend(('fullsystem.pin-control-memory=1',pin_control_reservation))
    if args.observe_input:handoff.append('fullsystem.input-observe=1')
    if args.immutable_osd=='capture':handoff.append('fullsystem.osd-immutable=capture')
    if args.gui_models!='off':handoff.append('fullsystem.gui-models='+args.gui_models)
    if args.gpio_c1!='off':handoff.append('fullsystem.gpio-c1='+args.gpio_c1)
    if args.remote_state!='off':handoff.append('fullsystem.remote-state='+args.remote_state)
    if args.bluetooth_policy=='off':handoff.append('fullsystem.bluetooth=off')
    if handoff:env['QEMU_EXTRA_CMDLINE']=' '.join(handoff)
    board = BASE/('boards/virt-four.dtb' if args.cpus==4 else 'qemu-virt-board/virt-packed.dtb')
    command = ['bash',str(BASE/'qemu-kernel-probe.sh'),'4096',str(board),
               '1','1',str(BASE/'full-system.cpio')]
    process = None
    qsock = stream = None
    fatal_probe=None
    shutdown_probe=None
    input_wakeup=None
    low_input=None
    lcd_producer=None
    result = {'stage':args.stage,'state':'starting','run':out.name,'camera_startup_verified':False}
    print('FULLSYSTEM_RUN', out, flush=True)
    try:
        with (out/'console.log').open('wb') as log:
            process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,
                                       env=env,start_new_session=True)
            process.stdin = PacedInput(process.stdin,out/'serial-input.jsonl')
            monitor = FullFirmwareMonitor(out/'console.log')
            deadline = time.monotonic()+120
            while time.monotonic() < deadline:
                monitor.check()
                if process.poll() is not None:
                    raise RuntimeError('VM exited before filesystems were mounted')
                console = (out/'console.log').read_bytes().replace(b'\r',b'')
                if b'Kernel panic - not syncing:' in console:
                    raise RuntimeError('Original kernel panicked during boot; inspect the private console')
                if any(b'\n'+marker+b'\n' in console for marker in
                       (b'FULLSYSTEM_LOOP_FAILED', b'FULLSYSTEM_FSTAB_FAILED', b'FULLSYSTEM_FSTAB_EXT_FAILED')):
                    raise RuntimeError('Original filesystem setup failed; inspect the private console')
                ready = console.find(b'\nFULLSYSTEM_MOUNTS_READY\n')
                # init still prints the mount table and execs ash after the marker.
                # Wait for that new shell before its tty initialization can flush
                # an early line. Every actual command still needs a unique RC.
                if ready >= 0 and b'\n/ # ' in console[ready:]:
                    break
                time.sleep(.1)
            else:
                raise TimeoutError('Full-dump mounts did not complete; inspect the private console')
            qsock, stream, qmp = qmp_open(out/'qmp.sock')
            result['qmp_before_input'] = qmp('query-status')
            if args.media_detect is not None:
                qmp('pmemsave',{'val':0xf1388f44,'size':4,'filename':'/out/media-detect-readback.bin'})
                raw=(out/'media-detect-readback.bin').read_bytes()
                actual=int.from_bytes(raw,'little') if len(raw)==4 else None
                proof={'physical':'0xf1388f44','bytes':len(raw),'raw_hex':raw.hex(),
                       'expected_u32':args.media_detect,'actual_u32':actual,
                       'method':'QMP physical read; not evidence of firmware access',
                       'verified':actual==args.media_detect}
                (out/'media-detect-readback.json').write_text(json.dumps(proof,indent=2)+'\n')
                if not proof['verified']:
                    raise RuntimeError('Virtual media register not delivered through the QEMU sandbox')
                result['media_detect_readback']=proof
            if usb_probe:
                (out/'usb-core-before.json').write_text(json.dumps(usb_probe(qmp,manifest['usb_probe_kernel_sha256']),indent=2)+'\n')
            with (out/'board-before-input.jsonl').open('w') as diagnostic:
                for command in ('xp /16wx 0x9000018',):
                    diagnostic.write(json.dumps({'command':command,
                        'return':qmp('human-monitor-command',{'command-line':command})})+'\n')
                    diagnostic.flush()
            def serial_run(command,timeout=20,cleanup=False):
                return serial_command(process,out/'console.log',command,timeout=timeout,monitor=monitor,cleanup=cleanup)
            def start_input():
                nonlocal low_input
                if low_input is None:
                    # The original OSAL constructors need init2's loaded UIPC driver.
                    low_input=low_input_api['LowLatencyInput'](out,qmp,serial_run)
                    run.quiesce_input=low_input.cancel
                    run.input_heartbeat=low_input.check
                    result['low_latency_input_started']=True
            def run(command, timeout=20, cleanup=False):
                if args.low_latency_input=='mailbox-v1' and low_input_api['parse_command'](command) is not None:
                    start_input()
                    return low_input.execute(command,timeout=30 if timeout is None else min(timeout,30))
                return serial_run(command,timeout=timeout,cleanup=cleanup)
            run('true')
            if args.lcd_stream_fps:
                peer=lcd_api['qmp_identity'](qsock)
                stream.close();qsock.close()
                lcd_producer=lcd_api['start'](out,out/'qmp.sock',fps=args.lcd_stream_fps,
                    expected_peer=peer,source_log='console.log')
                qmp=lcd_producer.call
                result['lcd_stream_profile']={'fps':args.lcd_stream_fps,'qmp_peer':peer,
                    'stream_nonce':lcd_producer.nonce,'window_presentation_verified':False}
            if args.low_latency_input=='mailbox-v1':
                result['low_latency_input_profile']='mailbox-v1'
            if args.stacks:
                tracer_check=run('/simulation/thread-snapshot --selftest',timeout=15)
                (out/'tracer-selftest.log').write_bytes(tracer_check)
                if b'REGS_SEIZE_SELFTEST_PASS interrupted_sleep=0' not in tracer_check:
                    raise RuntimeError('SEIZE/frozen-frame diagnostic self-test did not pass')
            if args.usb_init=='original':
                symbols=run("busybox grep -E ' (the_g_core|memstart_addr|_text|usb_gcore_module_init|__boottime_sony_usb_init)$' /proc/kallsyms; echo FULLSYSTEM_USB_SYMBOLS_DONE",timeout=30)
                (out/'usb-symbols.log').write_bytes(symbols)
            # Verifies shared storage by content, then removes only this marker.
            raw = run('echo dump-volume-check > /tmp/fullsystem-volume-check')
            raw += run('busybox cmp /tmp/fullsystem-volume-check /etc/fullsystem-volume-check')
            raw += run('busybox cmp /tmp/fullsystem-volume-check /var/fullsystem-volume-check')
            raw += run('rm -f /tmp/fullsystem-volume-check')
            (out/'mount-check.log').write_bytes(raw)
            for path in ('/usr/bin/bootin.elf','/usr/lib/appFw.so','/setting/Backup.bin','/system/vmlinux.bin','/cp/cpapp-b.bin'):
                run('ls -l '+path)
            result['mounts_verified'] = True
            requested_files=(manifest.get('user_overwrite') or {}).get('files',[])
            if requested_files:
                verified=verify_guest_overwrite(run,requested_files,out)
                result['overwrite_guest_files_verified']=len(verified)
            if args.pin_control_probe:
                raw=run('/simulation/pin-control-probe; echo FULL_PIN_CONTROL_PROBE_RC=$?',timeout=30)
                (out/'pin-control-probe.log').write_bytes(raw)
                codes=re.findall(rb'(?:^|\n)FULL_PIN_CONTROL_PROBE_RC=(\d+)\r?(?:\n|$)',raw)
                if codes!=[b'0'] or b'FULL_PIN_CONTROL_PROBE_PASS ' not in raw:
                    raise RuntimeError('Pin control backing probe did not complete successfully')
                running=qmp('query-status')['running']
                try:
                    if running:qmp('stop')
                    qmp('pmemsave',{'val':manifest['virtual_pin_control']['physical'],
                        'size':manifest['virtual_pin_control']['capacity'],'filename':'/out/pin-control-memory.bin'})
                finally:
                    if running:qmp('cont')
                result['pin_control_memory_exported']=True
            # QMP stop/cont after an attached GDB continue can leave an old
            # T02 reply pending. Attach only after all pre-init2 QMP readbacks.
            if args.fatal_probe:
                probe_class=runpy.run_path(str(HERE/'boot-fatal-probe.py'))['BootFatalProbe']
                fatal_probe=probe_class(out,connect_in_run)
                monitor.fatal_probe=fatal_probe
            if args.observe_panel_tick:
                probe_class=runpy.run_path(str(HERE/'panel-tick-probe.py'))['PanelTickProbe']
                shutdown_probe=probe_class(out,connect_in_run)
                monitor.shutdown_probe=shutdown_probe
            if args.observe_upm_reload:
                probe_class=runpy.run_path(str(HERE/'upm-reload-probe.py'))['UpmReloadProbe']
                shutdown_probe=probe_class(out,connect_in_run)
                monitor.shutdown_probe=shutdown_probe
            if args.observe_upm_activity:
                probe_class=runpy.run_path(str(HERE/'upm-activity-probe.py'))['UpmActivityProbe']
                shutdown_probe=probe_class(out,connect_in_run,BASE/'upm-observer-source.ko')
                monitor.shutdown_probe=shutdown_probe
            if args.observe_shutdown_write:
                probe_class=runpy.run_path(str(HERE/'shutdown-watch.py'))['ShutdownWriteProbe']
                shutdown_probe=probe_class(out,connect_in_run)
                monitor.shutdown_probe=shutdown_probe
            if args.observe_system_error_source:
                probe_class=runpy.run_path(str(HERE/'system-error-source.py'))['SystemErrorSourceProbe']
                shutdown_probe=probe_class(out,connect_in_run)
                monitor.shutdown_probe=shutdown_probe
            if args.observe_ee_transition:
                probe_class=runpy.run_path(str(HERE/'ee-transition-probe.py'))['EeTransitionProbe']
                shutdown_probe=probe_class(out,connect_in_run)
                monitor.shutdown_probe=shutdown_probe
            if args.observe_mode_write:
                probe_class=runpy.run_path(str(HERE/'mode-write-probe.py'))['ModeWriteProbe']
                shutdown_probe=probe_class(out,connect_in_run)
                monitor.shutdown_probe=shutdown_probe
            if args.observe_upm_notify:
                probe_class=runpy.run_path(str(HERE/'upm-message-probe.py'))['UpmMessageProbe']
                fatal_probe=probe_class(out,connect_in_run,BASE/'upm-observer-source.ko')
                monitor.fatal_probe=fatal_probe
                result['upm_diagnostic_only']=True
            if args.stage == 'drivers':
                run('/simulation/driver-audit.sh; echo DRIVER_AUDIT_RC=$?')
            elif args.stage == 'init2':
                prepare_bootin_handoff(run,args.bootin_handoff,bootin_experiment,out)
                if args.service_profile == 'menu-filter':
                    run('mount -o bind /simulation/libIMDB-menu.so /usr/lib/libIMDB.so')
                # Original drv1 initializes devno before init2. Physical NAND/crypto
                # is replaced by the explicit in-memory loop storage above.
                run('touch /log/qemu/init2.log')
                if args.immutable_osd=='capture':
                    run('busybox mkdir -p /log/qemu/immutable-osd && busybox chmod 700 /log/qemu/immutable-osd')
                run('busybox tail -n +1 -f /log/qemu/init2.log & echo FULLSYSTEM_LOG_TAIL_PID=$!')
                # init2 ends in its own login-shell loop. Keep that console on a
                # private, open FIFO so two ash processes cannot split host commands.
                run('busybox mknod /simulation/init2.stdin p')
                run('exec 7<> /simulation/init2.stdin')
                if args.observe_uart_input:
                    profile='rx' if args.probe_uart_rx else 'full'
                    run('exec 8<&0; /simulation/uart-input-observe.sh '+profile+' <&8 >/log/qemu/uart-input-schedule.log 2>&1 & echo FULLSYSTEM_UART_OBSERVER_PID=$!; exec 8<&-')
                    deadline=time.monotonic()+15
                    while time.monotonic()<deadline:
                        monitor.check()
                        preflight=(out/'console.log').read_bytes()
                        end=preflight.find(b'UART_INPUT_SNAPSHOT_END phase=before rc=0')
                        if end>=0:
                            begin=preflight.rfind(b'UART_INPUT_SNAPSHOT_BEGIN phase=before',0,end)
                            observed=preflight[begin:end]
                            if begin<0 or b'UART_INHERITED_FD0 target=/dev/ttyAMA0' not in observed or b'UART_TERMIOS rc=0 ' not in observed:
                                raise RuntimeError('UART observer did not inherit the existing diagnostic TTY')
                            result['uart_observer_preflight_verified']=True
                            break
                        if process.poll() is not None:raise RuntimeError('VM exited before UART observer preflight')
                        time.sleep(.05)
                    else:
                        raise TimeoutError('UART observer preflight END record missing before init2 startup')
                if args.stacks and args.census_mode=='guest':
                    run('/simulation/delayed-census.sh & echo FULLSYSTEM_AUTO_CENSUS_PID=$!')
                if args.stacks and args.census_mode=='guest-proc':
                    run('/simulation/proc-census.sh '+str(args.census_proc_delay)+' '+str(args.census_proc_samples)+' >/log/qemu/proc-census-schedule.log 2>&1 & echo FULLSYSTEM_AUTO_CENSUS_PID=$!')
                if args.observe_upm_notify:
                    run('/simulation/upm-notify-observe.sh >/dev/console 2>&1 & echo UPM_DIAG_OBSERVER_PID=$!')
                # init2 sources its own initrc and loads modules before bootin runs,
                # so the insmod policy has to exist before it starts.
                if args.insmod_policy!='allow-list':
                    run('echo '+args.insmod_policy+' > /tmp/fullsystem-insmod-policy; '
                        'echo FULLSYSTEM_INSMOD_MARKER='+args.insmod_policy)
                run('insmod /kmod/devno.ko; '
                    '/sbin/init2 </simulation/init2.stdin >/log/qemu/init2.log 2>&1 & echo ORIGINAL_INIT2_PID=$!')
            observation_start=time.monotonic()
            until = observation_start+args.seconds
            uart_probe=None
            uart_probe_followup=None
            uart_command_attempted=False
            backup_probe_done=False
            progress={'marker':0,'at':observation_start,'consecutive':0,'stalled':None}
            captured_frames=set()
            live_frame_at=0.0
            adaptive_at=0.0
            adaptive_seen={}
            adaptive_unknown=set()
            if args.adaptive_first_setup:
                screens=runpy.run_path(str(HERE/'screen-map.py'))
                key_codes=runpy.run_path(str(HERE/'start-official-camera.py'))['KEY_CODES']
                adaptive_map=args.adaptive_map or (HERE/'screens.json')
                if not Path(adaptive_map).is_file():
                    raise RuntimeError('adaptive mode needs a screen map: '+str(adaptive_map))
                result['adaptive_actions']=[]
            input_snapshot_due=None
            input_frame_due=None
            input_snapshot_number=0
            key_plan=[]
            for entry in (args.key_plan or '').split(';'):
                entry=entry.strip()
                if not entry:continue
                when,sep,command=entry.partition(':')
                if not sep or not command.strip():raise RuntimeError('Bad --key-plan entry: '+entry)
                key_plan.append([float(when),command.strip(),False])
            key_plan_log=out/'key-plan.log'
            def note_progress():
                """Count protocol/display records only; kernel UIPC noise is not progress.
                One quiet window can be an RCU stall that recovers, so require two."""
                console=(out/'console.log').read_bytes()
                marker=len(re.findall(rb'OBS (?:FULL_\w+|OSD_HEADLESS_PERSISTED|FRAME_DRAW_\w+|CREATE_SCREEN_\w+|RESOURCE_\w+) ',console))
                now=time.monotonic()
                if marker>progress['marker']:
                    progress['marker']=marker;progress['at']=now;progress['consecutive']=0
                elif args.stall_seconds:
                    if now-progress['at']>=args.stall_seconds:
                        progress['consecutive']+=1
                        if progress['consecutive']>=2:progress['stalled']=round(now-progress['at'],1)
                        else:progress['at']=now-1e-6
                return marker
            def save_requested():
                return (args.card_export_on_request or args.config_export_on_request) and card_save_requested(args.input_queue_dir)
            def capture_live_frame(force=False):
                nonlocal live_frame_at
                if lcd_producer is not None:return
                if args.live_frame_seconds<=0:return
                now=time.monotonic()
                due=now-live_frame_at>=args.live_frame_seconds
                if not (force or due):return
                # An early post-input dump must not postpone the next periodic frame.
                if due:live_frame_at=now
                try:
                    # Running-VM QMP screen only; publication is not proof of new AP pixels.
                    qmp('screendump',{'filename':'/out/live-frame.next.ppm'})
                    (out/'live-frame.next.ppm').replace(out/'live-frame.ppm')
                    result['live_frames_dumped']=result.get('live_frames_dumped',0)+1
                except Exception as error:
                    if 'live_frame_error' not in result:
                        print('LIVE_FRAME_ERROR',error,flush=True)
                    result['live_frame_error']=str(error)
            input_wakeup=UiWakeup(args.input_queue_dir)
            while time.monotonic() < until:
                monitor.check()
                if process.poll() is not None:
                    raise RuntimeError('VM exited during observation')
                if (args.low_latency_input=='mailbox-v1' and low_input is None and
                        b'OBS OSD_HEADLESS_PERSISTED ' in (out/'console.log').read_bytes()):
                    start_input()
                if save_requested():
                    save_input_session(args,run,qmp,manifest,out,result,'owned-ui-close-request')
                    break
                if input_snapshot_due is not None and time.monotonic() >= input_snapshot_due:
                    qmp('screendump',{'filename':f'/out/input-{input_snapshot_number:03d}-after.ppm'})
                    input_snapshot_due=None
                if input_frame_due is not None and time.monotonic()>=input_frame_due:
                    capture_live_frame(force=True)
                    input_frame_due=None
                else:
                    capture_live_frame()
                adaptive_stage=adaptive_phase(result,args.adaptive_seek,args.adaptive_seek_after,
                                              time.monotonic()-observation_start)
                if args.adaptive_first_setup and adaptive_stage!='done':
                    now=time.monotonic()
                    if now-adaptive_at>=args.adaptive_interval:
                        adaptive_at=now
                        try:
                            number=len(result['adaptive_actions'])
                            qmp('screendump',{'filename':f'/out/adaptive-{number:03d}.ppm'})
                            frame=out/f'adaptive-{number:03d}.ppm'
                            name,distance=screens['classify'](frame,adaptive_map)
                            key=screens['key_for'](name,adaptive_map) if name else None
                            keys=screens['keys_for'](name,adaptive_map) if name else []
                            seeking=adaptive_stage=='seeking'
                            if adaptive_stage=='waiting-for-seek':
                                keys=[]
                            elif seeking:
                                keys,found=adaptive_seek_keys(name,args.adaptive_seek,args.adaptive_seek_key,
                                    args.adaptive_seek_enter,result.get('adaptive_seek_steps',0))
                                if found:
                                    result['adaptive_seek_found']=name
                                    result['adaptive_stopped']=name
                            elif name is None and args.adaptive_default and (
                                    args.adaptive_default_after is None
                                    or now-observation_start>=args.adaptive_default_after):
                                digest=screens['dhash'](frame)
                                if digest not in adaptive_unknown:
                                    adaptive_unknown.add(digest)
                                    keys=[args.adaptive_default]
                                else:
                                    keys=[]
                            elif name is None:
                                keys=[]
                            record={'seconds':round(now-observation_start,1),'screen':name,
                                    'distance':distance,'key':key,'phase':adaptive_stage,'planned_keys':keys}
                            usable=[item for item in keys if item in key_codes]
                            if usable and (seeking or name is None or adaptive_seen.get(name,0)<1):
                                for item in usable:
                                    code=key_codes[item]
                                    run(input_tap_command(code),timeout=20)
                                record['pressed']=usable
                                if seeking and not result.get('adaptive_seek_found'):
                                    result['adaptive_seek_steps']=result.get('adaptive_seek_steps',0)+1
                                if name:
                                    adaptive_seen[name]=adaptive_seen.get(name,0)+1
                            result['adaptive_actions'].append(record)
                            if args.adaptive_stop_screen and name==args.adaptive_stop_screen:
                                result['adaptive_stopped']=name
                        except Exception as error:
                            result['adaptive_error']=str(error)
                            raise
                if args.input_queue_dir:
                    if getattr(run,'input_heartbeat',None) is not None:run.input_heartbeat()
                    queue_dir=Path(args.input_queue_dir)
                    for request in sorted(queue_dir.glob('*.cmd'))[:4]:
                        if save_requested() or time.monotonic()>=until:break
                        try:
                            command=request.read_text().strip()
                        except OSError:
                            # A persistent unreadable request must not keep inotify readiness spinning.
                            if request.exists():raise
                            continue
                        if not command:
                            request.unlink(missing_ok=True);continue
                        try:
                            output=run(command,timeout=30)
                        except Exception as error:
                            temporary=request.with_suffix('.out.tmp')
                            temporary.write_bytes(str(error).encode())
                            temporary.replace(request.with_suffix('.out'))
                            request.unlink(missing_ok=True)
                            # A timeout leaves the serial shell's ownership unknown.
                            # Do not silently continue executing more queued commands.
                            raise
                        temporary=request.with_suffix('.out.tmp')
                        temporary.write_bytes(output)
                        temporary.replace(request.with_suffix('.out'))
                        request.unlink(missing_ok=True)
                        if not save_requested():
                            capture_live_frame(force=True)
                            # ACK can precede async AP/ramfb work; one bounded follow-up avoids a 400 ms phase miss.
                            if args.live_frame_seconds>0:input_frame_due=time.monotonic()+.1
                    if save_requested():
                        save_input_session(args,run,qmp,manifest,out,result,'owned-ui-close-request')
                        break
                marker_seen = (not args.key_after_marker) or (
                    args.key_after_marker.encode() in (out/'console.log').read_bytes())
                for step in key_plan:
                    if step[2]:continue
                    if args.key_after_marker:
                        if not marker_seen:continue
                    elif time.monotonic()-observation_start < step[0]:continue
                    step[2]=True
                    if args.observe_input:
                        input_snapshot_number+=1
                        qmp('screendump',{'filename':f'/out/input-{input_snapshot_number:03d}-before.ppm'})
                    output=execute_planned_command(run,step[0],step[1],key_plan_log)
                    if args.observe_input:input_snapshot_due=time.monotonic()+1
                    record=re.findall(rb'\n(INJECT_KEY_[A-Z]+ [^\r\n]*)',output)
                    for line in record:print(line.decode(),flush=True)
                if args.capture_osd_frames:
                    capture_persisted_frames(qmp,out,captured_frames,result)
                if note_progress() and progress['stalled']:
                    result['stalled_seconds']=progress['stalled']
                    break
                if args.observe_upm_notify:
                    producer_codes=re.findall(rb'(?:^|\n)UPM_DIAG_PRODUCER_RC=(\d+)\r?(?:\n|$)',(out/'console.log').read_bytes())
                    if producer_codes and producer_codes!=[b'0']:
                        raise RuntimeError('UPM diagnostic producer failed or ran more than once')
                    if fatal_probe.completed and producer_codes==[b'0']:
                        result['upm_original_receive_process_free_verified']=True
                        break
                if args.probe_hdmi_backup and not backup_probe_done and b'OBS OBSERVER_READY ' in (out/'console.log').read_bytes():
                    backup_probe_done=True
                    response=run('/simulation/hdmi-backup-probe --isolated-diagnostic; echo HDMI_BACKUP_PROBE_RC=$?',timeout=40)
                    (out/'hdmi-backup-probe.log').write_bytes(response)
                    if b'HDMI_BACKUP_PROBE_DONE ' not in response:
                        raise RuntimeError('HDMI Backup probe did not report its bounded result')
                    result['hdmi_backup_probe_captured']=True
                if (args.card_export_at is not None and not result.get('card_image_exported')
                        and time.monotonic()-observation_start>=args.card_export_at):
                    export_card_image(run,qmp,manifest,out,result,
                                      barrier_serial=run if args.card_export_flush else None)
                if (args.config_export_at is not None and not result.get('config_export')
                        and time.monotonic()-observation_start>=args.config_export_at):
                    result['config_export_trigger']='timed'
                    export_config_pair(run,qmp,manifest,out,result)
                if save_requested():
                    save_input_session(args,run,qmp,manifest,out,result,'owned-ui-close-request')
                    break
                if args.probe_uart_rx and uart_probe is None and time.monotonic()-observation_start>=60:
                    uart_probe={'readback_phase':'before','readback_address':'0x9000018','bytes_hex':'0a','host_elapsed_seconds':time.monotonic()-observation_start}
                    (out/'uart-rx-probe.json').write_text(json.dumps(uart_probe,indent=2)+'\n')
                    uart_probe['before']=uart_rx_readback(qmp)
                    process.stdin.write(b'\n');process.stdin.flush()
                    result['uart_rx_empty_line_probe_sent']=True
                    uart_probe_followup=time.monotonic()+1
                    (out/'uart-rx-probe.json').write_text(json.dumps(uart_probe,indent=2)+'\n')
                if uart_probe_followup is not None and time.monotonic()>=uart_probe_followup:
                    uart_probe['readback_phase']='after'
                    (out/'uart-rx-probe.json').write_text(json.dumps(uart_probe,indent=2)+'\n')
                    uart_probe['after']=uart_rx_readback(qmp)
                    (out/'uart-rx-probe.json').write_text(json.dumps(uart_probe,indent=2)+'\n')
                    uart_probe_followup=None
                if args.probe_uart_command and not uart_command_attempted and uart_probe is not None and 'after' in uart_probe:
                    uart_command_attempted=True
                    result['uart_command_probe_attempted']=True
                    response=run('echo UART_INPUT_COMMAND_PROBE',timeout=20)
                    (out/'uart-command-probe.log').write_bytes(response)
                    if b'UART_INPUT_COMMAND_PROBE' not in response:
                        raise RuntimeError('UART command probe returned without its echo')
                    result['uart_command_probe_completed']=True
                if args.until_vdf_request and any(marker in (out/'console.log').read_bytes() for marker in
                        (b'OBS FULL_IMAGING_VDF_OBSERVE ',b'OBS FULL_VDF_REQUEST ')):
                    result['vdf_request_observed']=True
                    break
                if args.until_evf_subscription and b'OBS FULL_VDF_EVF_SUBSCRIPTION ' in (out/'console.log').read_bytes():
                    result['evf_subscription_observed']=True
                    break
                if args.until_pin_request and post_rate_pin_request_ready((out/'console.log').read_bytes()):
                    result['pin_request_observed']=True
                    break
                if args.until_pin_peer_request and pin_peer_request_ready((out/'console.log').read_bytes(),args.audio_capabilities):
                    result['pin_peer_request_observed']=True
                    break
                if args.until_pin_format_block and pin_format_block_ready((out/'console.log').read_bytes(),args.audio_capabilities):
                    result['pin_format_boundary_observed']=True
                    break
                if args.until_pin_format_consumed and pin_format_consumed_ready((out/'console.log').read_bytes(),args.audio_capabilities):
                    result['pin_format_cpu_consumed_observed']=True
                    if not args.until_scalar_get or scalar_get_ready((out/'console.log').read_bytes()):
                        if args.until_scalar_get:result['scalar_get_consumed_observed']=True
                        if not args.until_scalar_connection or scalar_connection_ready((out/'console.log').read_bytes()):
                            if args.until_scalar_connection:result['scalar_connection_consumed_observed']=True
                            if not args.until_adf_get or adf_get_ready((out/'console.log').read_bytes()):
                                if args.until_adf_get:result['adf_get_consumed_observed']=True
                                if not args.until_adf_connection or adf_connection_ready((out/'console.log').read_bytes()):
                                    if args.until_adf_connection:result['adf_connection_consumed_observed']=True
                                    if not args.until_hdmi_pin_get or hdmi_pin_get_ready((out/'console.log').read_bytes()):
                                        if args.until_hdmi_pin_get:result['hdmi_pin_get_consumed_observed']=True
                                        break
                next_deadline=until
                if args.live_frame_seconds>0 and lcd_producer is None:
                    next_deadline=min(next_deadline,live_frame_at+args.live_frame_seconds)
                if input_snapshot_due is not None:
                    next_deadline=min(next_deadline,input_snapshot_due)
                if input_frame_due is not None:
                    next_deadline=min(next_deadline,input_frame_due)
                input_wakeup.wait(next_deadline)
            if ((args.card_export_on_request and not result.get('card_image_exported'))
                    or (args.config_export_on_request and not result.get('config_export',{}).get('verified'))):
                save_input_session(args,run,qmp,manifest,out,result,'observation-deadline')
            if args.observe_upm_notify and not result.get('upm_original_receive_process_free_verified'):
                raise TimeoutError('Original UPM diagnostic receive/process/free was not verified')
            if args.until_vdf_request and not result.get('vdf_request_observed'):
                raise TimeoutError('Original VDF request did not arrive within the declared observation window')
            if args.until_evf_subscription and not result.get('evf_subscription_observed'):
                raise TimeoutError('Original EVF subscription was not consumed within the declared observation window')
            if args.until_pin_request and not result.get('pin_request_observed'):
                raise TimeoutError('Original pin request did not arrive after all five original rate waiter releases')
            if args.until_pin_peer_request and not result.get('pin_peer_request_observed'):
                raise TimeoutError('Actual peer pin request did not arrive after original source GetPin release')
            if args.until_pin_format_block and not result.get('pin_format_boundary_observed'):
                raise TimeoutError('Original AP/control buffer did not reach the declared missing-format boundary')
            if args.until_pin_format_consumed and not result.get('pin_format_cpu_consumed_observed'):
                raise TimeoutError('Actual CPU format consumption/release and next original Get/free were not observed')
            if args.until_scalar_get and not result.get('scalar_get_consumed_observed'):
                raise TimeoutError('Original Scalar Get was not consumed by the format continuation waiter')
            if args.until_scalar_connection and not result.get('scalar_connection_consumed_observed'):
                raise TimeoutError('Original Scalar connection reply and OUT2 continuation were not consumed')
            if args.until_adf_get and not result.get('adf_get_consumed_observed'):
                raise TimeoutError('Original ADF Get/free and subsequent OUT2 Connect request were not observed')
            if args.until_adf_connection and not result.get('adf_connection_consumed_observed'):
                raise TimeoutError('Original ADF connection reply and type4 OUT0 Get/free were not observed')
            if args.until_hdmi_pin_get and not result.get('hdmi_pin_get_consumed_observed'):
                raise TimeoutError('Original HDMI pin Get/free and next Connect request were not observed')
            if shutdown_probe:
                shutdown_probe.end_observation()
                monitor.shutdown_probe=None
            if args.pin_connection=='control':
                export_pin_control_memory(qmp,manifest,out,result)
            if args.system_sound_memory and not args.stacks:
                export_sound_memory(qmp,manifest,out,result)
            if args.observe_liro_loader:
                observed=run('echo FULLSYSTEM_LIRO_OBSERVE_LOG_BEGIN; '
                             'cat /log/qemu/liro-observe.log; echo FULLSYSTEM_LIRO_OBSERVE_LOG_END',timeout=30)
                (out/'liro-observe.log').write_bytes(observed)
                if b'FULL_LIRO_ARGS ' not in observed or b'FULL_LIRO_BACKUP ' not in observed:
                    raise RuntimeError('Original LIRO loader observations were not captured')
                result['liro_loader_observed']=True
                if args.probe_liro_memory:
                    match=re.search(rb'FULL_LIRO_BACKUP [^\r\n]*caller=0x406178 key=0xfa007c [^\r\n]*slot_hex=([0-9a-f]{16})',observed)
                    if not match:raise RuntimeError('Native LIRO address slot was not captured')
                    address=int.from_bytes(bytes.fromhex(match[1].decode()),'little')
                    kernel=BASE/'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
                    with kernel.open('rb') as image:
                        kernel_sha=hashlib.file_digest(image,'sha256').hexdigest()
                    memory_probe=runpy.run_path(str(HERE/'liro-memory-probe.py'))['probe']
                    memory=memory_probe(qmp,kernel_sha,out,address)
                    (out/'liro-memory.json').write_text(json.dumps(memory,indent=2)+'\n')
                    result['liro_reserved_memory_observed']=True
            if args.observe_uart_input:
                console=(out/'console.log').read_bytes()
                phases=('before','after15','after45') if args.probe_uart_rx else ('before','after15','after45','after90')
                observed=[phase for phase in phases if ('UART_INPUT_SNAPSHOT_END phase='+phase+' rc=0').encode() in console]
                result['uart_input_snapshot_phases']=observed
                result['uart_input_snapshot_expected_phases']=list(phases)
                result['uart_input_observation_only']=True
                if observed!=list(phases) or b'UART_INPUT_OBSERVER_DONE' not in console:
                    result['uart_input_observation_error']='Autonomous UART snapshots incomplete at the observation deadline'
                    if not args.stacks:
                        raise RuntimeError(result['uart_input_observation_error'])
                if args.probe_uart_rx and (uart_probe is None or 'after' not in uart_probe):
                    raise RuntimeError('UART RX empty-line probe did not complete its readback')
            if args.stage != 'mounts' and not args.observe_uart_input and not (args.stacks and args.stage=='init2'):
                collect_serial_diagnostics(run,result,timeout=args.serial_diagnostic_seconds)
            if args.stacks:
                if args.stage=='init2':
                    until=time.monotonic()+args.census_timeout
                    diagnostic_ready=None
                    census_started=False
                    while time.monotonic()<until:
                        monitor.check()
                        census=(out/'console.log').read_bytes()
                        if args.census_mode=='host' and not census_started:
                            matches=re.findall(rb'OBS OBSERVER_READY pid=(\d+) base=(0x[0-9a-f]+)',census)
                            if args.census_after_sound_config:
                                ready=boot_config_waiters_ready(census,args.audio_capabilities,args.hdmi_service,args.vef_service,args.pinmem_service)
                            elif args.census_after_vdf:
                                ready=bool(re.search(rb'OBS FULL_VDF_NATIVE_REPLY_FREE [^\r\n]*waiter=1 [^\r\n]*rc=0(?:\r?\n|$)',census))
                            else:
                                ready=b'OBS CREATE_SCREEN_RETURN call=1 ' in census
                            if matches and ready:
                                if diagnostic_ready is None:diagnostic_ready=time.monotonic()
                                if time.monotonic()-diagnostic_ready>=3:
                                    pid,bias=matches[-1]
                                    run('/simulation/host-census.sh '+pid.decode()+' '+bias.decode()+
                                        ' & echo FULLSYSTEM_HOST_CENSUS_PID=$!',timeout=30)
                                    census_started=True
                                    until=time.monotonic()+args.census_timeout
                        completed=re.search(rb'(?:^|\n)(?:\[\s*\d+\.\d+\] )?FULLSYSTEM_AUTO_STACKS_DONE=(\d+)(?:\n|$)',census.replace(b'\r',b''))
                        if completed:
                            if int(completed[1]):
                                raise RuntimeError('Critical thread snapshots reported failure rc='+completed[1].decode())
                            if args.census_mode=='guest-proc':
                                samples=re.findall(rb'FULLSYSTEM_PROC_CENSUS_SAMPLE_DONE sample=(\d+) pid=(\d+) rc=0 output_rc=0(?:\r?\n|$)',census)
                                if [int(sample) for sample,pid in samples]!=list(range(1,args.census_proc_samples+1)) or len({pid for sample,pid in samples})!=1:
                                    raise RuntimeError('Requested same-process census samples are missing or inconsistent')
                                result['thread_census_samples_verified']=len(samples)
                            break
                        if re.search(rb'(?:^|\n)(?:\[\s*\d+\.\d+\] )?FULLSYSTEM_AUTO_STACKS_NO_SCREEN(?:\r?\n|$)',census):
                            raise RuntimeError('No application screen was observed before the diagnostic deadline')
                        time.sleep(.2)
                    else:
                        raise TimeoutError('Automatic guest stack census incomplete; retained partial console')
                else:
                    census = run('/simulation/stack-census.sh; echo FULLSYSTEM_STACK_CENSUS_RC=$?', timeout=120)
                (out/'stacks.log').write_bytes(census)
                result['app_mapped'] = bool(re.search(rb'(?:^|\n)(?:\[\s*\d+\.\d+\] )?FULLSYSTEM_APP_PID=\d+(?:\r?\n|$)',census))
                result['thread_census_completed']=True
            if args.system_sound_memory:
                export_sound_memory(qmp,manifest,out,result)
            # Independent diagnostics may still run after an incomplete UART
            # sample set, but do not erase the failed deadline or mark it passed.
            if result.get('uart_input_observation_error'):
                raise RuntimeError(result['uart_input_observation_error'])
            # Export the AP snapshot while the VM still owns it: the original
            # firmware may recycle the buffer during teardown.
            persisted=list(re.finditer(rb'OBS OSD_HEADLESS_PERSISTED [^\r\n]*phys=(0x[0-9a-f]+) '
                                       rb'geometry=(\d+)x(\d+) bytes=(\d+)',(out/'console.log').read_bytes()))
            if persisted:
                last=persisted[-1];address=int(last[1],16);length=int(last[4])
                if length==640*480*2:
                    running=qmp('query-status')['running']
                    try:
                        if running:qmp('stop')
                        qmp('pmemsave',{'val':address,'size':length,'filename':'/out/osd-ap-pixels.bin'})
                        result['osd_ap_pixels_exported']=True
                        result['osd_ap_pixels_physical']=hex(address)
                        recorded=re.search(rb'fnv1a64=([0-9a-f]{16})',last.group(0))
                        if recorded:result['osd_ap_pixels_recorded_fnv1a64']=recorded[1].decode()
                    finally:
                        if running:qmp('cont')
            # The AP RGBA4444 framebuffer address is stable across runs of the same
            # profile; export it unconditionally so the "headless off" experiment
            # can be judged without a PERSISTED record.
            running=qmp('query-status')['running']
            try:
                if running:qmp('stop')
                qmp('pmemsave',{'val':0x43a7b4100,'size':640*480*2,'filename':'/out/osd-fb-end.bin'})
                result['osd_framebuffer_exported']=True
            except Exception as error:
                result['osd_framebuffer_export_error']=str(error)
            finally:
                if running:qmp('cont')
            qmp('screendump',{'filename':'/out/ramfb-screen.ppm'})
            if usb_probe:
                (out/'usb-core-after.json').write_text(json.dumps(usb_probe(qmp,manifest['usb_probe_kernel_sha256']),indent=2)+'\n')
            native_fatal=re.search(rb'SEQUENCE FATAL ERROR assert at ([^\r\n]+)',(out/'console.log').read_bytes())
            if (fatal_probe and fatal_probe.captured) or native_fatal:
                result['state']='failed'
                result['original_model_fatal_observed']=True
                if fatal_probe and fatal_probe.captured:
                    captured=json.loads((out/'original-boot-fatal.json').read_text())
                    result['error']=f"Original sequence_boot fatal line={captured['source_line']} status={captured['original_error']}"
                else:
                    result['error']='Original firmware model fatal: '+native_fatal[1].decode(errors='replace')
            else:
                result['state'] = 'observation-completed'
                # Stage completion is not a claim of a working camera.
    except KeyboardInterrupt:
        result['state'],result['error']='cancelled','interrupted; cleaning this owned VM'
    except Exception as error:
        result['state'], result['error'] = 'failed',str(error)
        if not qsock and process and process.poll() is None and (out/'qmp.sock').exists():
            try:qsock,stream,qmp=qmp_open(out/'qmp.sock')
            except Exception as diagnostic_error:result['early_qmp_error']=str(diagnostic_error)
        if qsock and stream and process and process.poll() is None:
            try:
                if args.system_sound_memory and b'FULL_SOUND_OWNER_READY ' in (out/'console.log').read_bytes():
                    try:
                        export_sound_memory(qmp,manifest,out,result)
                        result['failure_read_only_sound_export']=True
                    except Exception as export_error:
                        result['failure_sound_export_error']=str(export_error)
                if args.pin_connection=='control' and b'OBS FULL_PIN_CONNECT_BUFFER_WRITTEN ' in (out/'console.log').read_bytes():
                    try:
                        export_pin_control_memory(qmp,manifest,out,result)
                        result['failure_read_only_control_export']=True
                    except Exception as export_error:
                        result['failure_control_export_error']=str(export_error)
                if result.get('mounts_verified'):
                    try:
                        collect_failed_observation_logs(run,error,result,out)
                    except Exception as log_error:
                        result['failure_log_collection_error']=str(log_error)
                with (out/'board-diagnostic.jsonl').open('w') as diagnostic:
                    diagnostic.write(json.dumps({'query-status':qmp('query-status')})+'\n')
                    diagnostic.flush()
                    if usb_probe:
                        (out/'usb-core-failed.json').write_text(json.dumps(usb_probe(qmp,manifest['usb_probe_kernel_sha256']),indent=2)+'\n')
                    for command in ('xp /16wx 0x9000018',):
                        diagnostic.write(json.dumps({'command':command,
                            'return':qmp('human-monitor-command',{'command-line':command})})+'\n')
                        diagnostic.flush()
            except Exception as diagnostic_error:
                result['diagnostic_error'] = str(diagnostic_error)
    finally:
        collect_observer_result(shutdown_probe, result)
        input_safe=low_input is None
        for resource in (low_input, input_wakeup, fatal_probe, shutdown_probe, stream, qsock):
            if resource is not None:
                try:
                    resource.close()
                    if resource is low_input:input_safe=low_input.closed is True
                except Exception as error:
                    result['state'] = 'failed'
                    result.setdefault('error', 'Diagnostic cleanup failed: ' + str(error))
                    if resource is low_input:
                        input_safe=False
                        result['vm_cleanup_blocked_by_input']=True
        lcd_safe=True
        if lcd_producer is not None:
            try:
                result['lcd_stream']=lcd_producer.stop()
                lcd_safe=result['lcd_stream']['safe_to_quit']
                if result['lcd_stream']['error']:
                    result['state']='failed'
                    result.setdefault('error','LCD producer failed: '+result['lcd_stream']['error'])
            except Exception as error:
                lcd_safe=False
                result['lcd_stream']=lcd_producer.receipt()
                result['state']='failed'
                result.setdefault('error','LCD producer has not safely stopped: '+str(error))
        if lcd_safe and input_safe:
            finish_owned_run(process, result, out)
        else:
            result['state']='failed'
            result['vm_cleanup_blocked_by_lcd']=not lcd_safe
            result['terminal_evidence_checked']=False
            result.setdefault('error','Unreleased input or outstanding LCD QMP work; owned VM preserved without quit or signals')
            try:preserve_owned_run(process,result,out)
            except Exception as error:result['owner_guard_error']=str(error)
            (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    # Keep this frame's runtime lock and bubblewrap parent alive until actual recovery.
    wait_retained_owner(process,result,out)
    if result['state'] == 'observation-completed':
        print('FULLSYSTEM_STAGE_COMPLETED', args.stage, out, flush=True)
    else:
        print('FULLSYSTEM_STAGE_FAILED', result.get('error', result['state']), out, flush=True)
    return 0 if result['state'] == 'observation-completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
