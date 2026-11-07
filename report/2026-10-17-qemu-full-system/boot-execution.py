#!/usr/bin/env python3
"""Own a prepared original-init experiment and retain its actual stage evidence."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1] / 'runtime/analysis'
sys.path.insert(0, str(NATIVE))
from boot_flow import COLD_STAGES, evaluate, new_receipt, record_stage


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def qmp_connect(path, timeout=3):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    path = Path(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        connection.connect('/proc/self/fd/' + str(directory) + '/' + path.name)
    finally:
        os.close(directory)
    stream = connection.makefile('rwb', buffering=0)
    greeting = json.loads(stream.readline())
    if 'QMP' not in greeting:
        connection.close()
        raise ValueError('Missing QMP greeting')

    def command(name, arguments=None):
        stream.write((json.dumps({'execute': name, 'arguments': arguments or {}}) + '\n').encode())
        while True:
            data = stream.readline()
            if not data:
                raise EOFError('QMP closed before response')
            value = json.loads(data)
            if 'error' in value:
                raise RuntimeError('QMP ' + name + ': ' + str(value['error']))
            if 'return' in value:
                return value
    command('qmp_capabilities')
    return connection, stream, command


BOOTIN_SHA256='dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2'
# Fixed Sony 2.01 pin, also used by retained-camera-test.py; never inferred from a mutable disk.
IM_SHA256='5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91'
IM_VERSION='ILCE-7CM2-2.01'
APPFW_SHA256='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'


def write_console(stream, data):
    for offset in range(0,len(data),16):
        remaining=memoryview(data)[offset:offset+16]
        while remaining:
            count=stream.write(remaining)
            if not isinstance(count,int) or count<=0 or count>len(remaining):
                raise OSError('Serial input write did not complete')
            remaining=remaining[count:]
        stream.flush()
        time.sleep(.005)


def diagnostic_envelope(script, tag):
    if not re.fullmatch(r'[A-Za-z0-9_]{1,80}',tag) or tag in script.splitlines():
        raise ValueError('Invalid serial diagnostic heredoc delimiter')
    body=script.strip().replace('; ',';\n')
    if any(len(line.encode('ascii'))>512 for line in body.splitlines()):
        raise ValueError('Diagnostic line exceeds original shell input budget')
    return "busybox sh <<'"+tag+"'\n"+body+'\n'+tag+'\n'


def collect(console, receipt):
    """Prove stages from original trace plus actual post-pivot kernel state."""
    text = console.read_text(errors='replace').replace('\r', '')
    artifact = {'path': str(console), 'sha256': hashlib.sha256(console.read_bytes()).hexdigest()}
    def stage(name, kind='guest_original', **details):
        record_stage(receipt, name, execution_kind=kind, status='passed', evidence=dict(
            run=receipt['bindings']['run'], generation=receipt['generation'],
            binding_digest=receipt['binding_digest'], source='guest',
            source_class=receipt['bindings']['source_class'], artifacts=[artifact], **details))
    if 'Linux version ' in text:
        stage('kernel')
    command = re.findall(r'COLD_KERNEL_CMDLINE_BEGIN\n([^\n]+)\nCOLD_KERNEL_CMDLINE_END(?:\n|$)',text)
    if not command:command = re.findall(r'Kernel command line:\s*([^\n]+)', text)
    if command:
        stage('kernelargs', 'host_observed', cmdline=command[-1].strip())
    original_init = ('COLD_BEFORE_ORIGINAL_INIT' in text and
                     re.search(r'\+\s+(?:\.\s+)?/sbin/initrc/setup_rootfs', text))
    if original_init:
        stage('ram_init')
    # A traced attempted mount alone cannot establish the new root.
    mounts = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 10 and fields[0].isdigit() and '-' in fields:
            separator = fields.index('-')
            if separator >= 6 and len(fields) > separator + 2:
                mounts[fields[4]] = {'device': fields[2], 'fs': fields[separator + 1],
                                     'source': fields[separator + 2], 'options': fields[5].split(',')}
    root = mounts.get('/', {})
    p7_root = root.get('fs') == 'ext2' and bool(re.fullmatch(
        r'/dev/(?:nflasha7|pnflasha7|loop6)', root.get('source', ''))) and 'ro' in root.get('options', [])
    init2 = bool(re.search(r'COLD_INIT2_PROCESS parent=\d+\n[^\n]{0,500}/sbin/init2', text))
    required = ('/setting', '/system', '/cp', '/log', '/cert', '/lens', '/tmp', '/usr', '/etc', '/var')
    complete_mounts = p7_root and all(name in mounts for name in required)
    if complete_mounts and not (mounts['/tmp']['device'] == mounts['/etc']['device'] == mounts['/var']['device']):
        complete_mounts = False
    if p7_root and init2:
        if complete_mounts:
            stage('mounts')
        if re.search(r'\+\s+/sbin/pivot_root\s+\.\s+/rootfs/initrd', text):
            stage('pivot_root')
        if re.search(r'\+\s+exec\s+busybox\s+chroot\s+\.', text):
            stage('chroot')
        stage('init2')
    receipt['observed_mounts'] = mounts
    if p7_root and init2 and '/initrd' not in mounts and 'COLD_OLD_INITRD_PATH_ABSENT=0' in text:
        stage('old_root_unmounted', 'host_observed')
    if p7_root and init2 and re.search(r'(?:^|\n)COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512(?:\n|$)', text):
        stage('ram0_release', 'host_observed')
    if ('COLD_EXECUTABLE=/usr/bin/bootin-original\n' in text or
            re.search(r'(?:^|\n)COLD_NATIVE_BOOTIN pid=\d+ sha256='+BOOTIN_SHA256+r'(?:\n|$)',text)):
        stage('bootin')
    receipt['stages'] = [row for row in receipt['stages'] if row['stage'] != 'im']
    receipt['im_path_observed'] = 'COLD_EXECUTABLE=/usr/bin/im.elf\n' in text
    if 'COLD_BOOTIN_ENTRY ' in text and 'FULLSYSTEM_BOOTIN_ENTER' in text:
        # The wrapper entry alone does not prove its final exec of the original ELF.
        if re.search(r'(?:/usr/bin/bootin-original|/simulation/bootin-original)[^\n]*', text):
            receipt['bootin_wrapper_reached'] = True
    mapped=re.findall(r'(?:^|\n)COLD_AP_MAP pid=(\d+) sha256=('+APPFW_SHA256+r')(?:\n|$)',text)
    observers=re.findall(r'OBS OBSERVER_READY pid=(\d+) base=0x[1-9a-f][0-9a-f]* ',text)
    pixels=re.findall(r'OBS OSD_HEADLESS_PERSISTED seq=(\d+) pixel_source_seq=(\d+) [^\n]*geometry=640x480 bytes=614400 [^\n]*fnv1a64=[0-9a-f]{16} [^\n]*path=(?:/dev/qemu-simulation|/tmp)/headless-osd-frame.bin(?:\n|$)',text)
    if (any(pid in observers for pid,sha in mapped) and
            re.search(r'OBS CREATE_SCREEN_ARGS [^\n]* id=0 count=565 ',text) and
            any(0<int(source)<=int(sequence) for sequence,source in pixels)):
        stage('ap',mapped_original_ap_sha256=APPFW_SHA256,original_main_screen_call_observed=True)
    # Retained serial command echo is not a proc record; bind the decoded suffix first.
    process_text = text
    if re.search(r'^RETAINED_COLD_(?:META|CHUNK|END|FILE)(?: |$)', text, re.M):
        process_text = ''
        raw = console.read_bytes()
        starts = list(re.finditer(
            rb'^RETAINED_COLD_FILE nonce=([0-9a-f]{32}) '
            rb'file=(/dev/qemu-simulation/retained-cold-\1\.proof)\n', raw, re.M))
        if len(starts) == 1:
            start = starts[0]
            proof, trace = raw[start.start():], raw[:start.start()]
            identity = b' nonce='+start[1]+b' file='+start[2]
            binding = (identity+b' bytes='+str(len(proof)).encode('ascii')+b' sha256='
                       +hashlib.sha256(proof).hexdigest().encode('ascii'))
            transfers = re.findall(rb'^RETAINED_COLD_(META|END)([^\r\n]*)\r?$', trace, re.M)
            if (proof.endswith(b'RETAINED_COLD_FILE_END'+identity+b'\n')
                    and len(re.findall(rb'^RETAINED_COLD_FILE_END[^\n]*$', proof, re.M)) == 1
                    and transfers == [(b'META', binding), (b'END', binding)]):
                try:
                    process_text = proof.decode('utf-8')
                except UnicodeDecodeError:
                    pass
    expected_im = re.findall(r'^COLD_EXPECTED_IM[^\n]*$', text, re.M)
    native_im = re.findall(r'^COLD_NATIVE_IM[^\n]*$', process_text, re.M)
    actual_im = re.findall(
        r'^COLD_PROCESS pid=([1-9][0-9]*) exe=(/usr/bin/im\.elf|/bin/im\.elf)\n'
        r'(?:SHA256|SHA2-256)\(/proc/\1/exe\)= '+IM_SHA256+r'\n'
        r'COLD_NATIVE_IM pid=\1 exe=\2 sha256='+IM_SHA256+r'\n'
        r'COLD_EXECUTABLE=/usr/bin/im\.elf\n', process_text, re.M)
    identity_ok = (expected_im == ['COLD_EXPECTED_IM version='+IM_VERSION+' sha256='+IM_SHA256]
                   and len(native_im) == len(actual_im) == 1)
    if identity_ok:
        pid, executable = actual_im[0]
        identity_ok = (process_text.splitlines().count('COLD_PROCESS pid='+pid+' exe='+executable) == 1
                       and len(re.findall(r'^(?:SHA256|SHA2-256)\(/proc/'+pid+r'/exe\)= [^\n]*$', process_text, re.M)) == 1
                       and len(re.findall(r'^COLD_AP_MAP pid='+pid+r' [^\n]*$', process_text, re.M)) == 1
                       and len(re.findall(r'^COLD_AP_MAP pid='+pid+r' sha256='+APPFW_SHA256+r'$', process_text, re.M)) == 1
                       and pid in observers)
    receipt['im_identity_status'] = 'unknown'
    verified = evaluate(receipt)['stage_verified']
    if identity_ok and all(verified[name] for name in COLD_STAGES if name != 'im'):
        stage('im', actual_pid=int(pid), actual_executable=executable,
              expected_version=IM_VERSION, expected_sha256=IM_SHA256,
              actual_exe_sha256=IM_SHA256, mapped_original_ap_sha256=APPFW_SHA256)
        receipt['im_identity_status'] = 'passed'
    receipt['observed_failures'] = re.findall(
        r'[^\n]*(?:COLD_BOOTSTRAP_FAILED|PERSISTENT_BOOTSTRAP_FAILED|PERSISTENT_BOOTIN_BIND_FAILED_SHA|Kernel panic|SEQUENCE FATAL ERROR|Entering exception monitor)[^\n]*', text)
    receipt['observation_limits'] = {
        'sony_loader_executed': False, 'cp_image_executed': False,
        'wbi_resume_executed': False, 'ram_hotboot_executed': False,
        'watchdog_verified': False, 'sd_original_receiver_executed': False,
        'old_root_release_requires_separate_readback': True,
    }
    return evaluate(receipt)


def run(launch, cold, output, *, seconds=90, validation_script=None):
    output = Path(output)
    if output.exists():
        raise ValueError('Run output must be new')
    output.mkdir(mode=0o700)
    validation=None
    if validation_script is not None:
        path=Path(validation_script).absolute()
        if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
            raise ValueError('Validation script must be an ordinary explicit file')
        raw=path.read_bytes()
        if len(raw)>32768 or not raw or b'\0' in raw:
            raise ValueError('Validation script is empty, oversized or contains NUL')
        text=raw.decode('ascii')
        if any(len(line)>512 for line in text.splitlines()):raise ValueError('Validation script exceeds original shell line limit')
        validation={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'text':text}
        (output/'guest-validation.sh').write_bytes(raw)
    receipt = new_receipt('original-init-cold', bindings={
        'run': output.name, 'source_class': cold['source'],
        'ram0_sha256': cold['ram0_sha256'], 'script_identity': cold['script_identity'],
        'launch_script_sha256': launch['script_sha256'], 'dtb_sha256': launch['dtb_sha256'],
        **({'validation_script_sha256':validation['sha256']} if validation else {}),
    }, kernel_cmdline=launch['cmdline'])
    console = output / 'console.log'
    terminal = {'qmp_quit_attempted': False, 'qmp_quit_confirmed': False,
                'signals_sent': [], 'returncode': None, 'owner_pid': None}
    owner = None
    connection = stream = command = None
    nonce = secrets.token_hex(12)
    begin, end = 'COLD_SESSION_BEGIN_' + nonce, 'COLD_SESSION_END_' + nonce
    diagnostics_sent = False
    diagnostics_complete_at = None
    final_diagnostics_sent = False
    validation_sent=False
    validation_result=None
    validation_complete_at=None
    captured_labels=set()
    primary_error = None
    save(output / 'boot-flow.json', {'receipt': receipt, 'coverage': evaluate(receipt)})
    with console.open('xb') as log:
        try:
            guardian = ['/bin/bash', '-c', '"$@" <&0 & child=$!; wait "$child"',
                        'cold-boot-owner', *launch['command']]
            owner = subprocess.Popen(guardian, env=launch['env'], stdin=subprocess.PIPE,
                                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                     pass_fds=launch.get('pass_fds', ()))
            if 'children' in launch:
                launch['children'].append(owner)
            terminal['owner_pid'] = owner.pid
            save(output / 'owner-start.json', dict(terminal, command=launch['command']))
            started = time.monotonic()
            while owner.poll() is None and time.monotonic() - started < seconds:
                if command is None and Path(launch['qmp_socket']).is_socket():
                    try:
                        connection, stream, command = qmp_connect(launch['qmp_socket'])
                    except (OSError, EOFError) as error:
                        save(output / 'qmp-connect-error.json', {'error': str(error)})
                data = console.read_bytes()
                bootin_ready = any(marker in data for marker in (b'COLD_BOOTIN_ENTRY ',
                    b'PERSISTENT_BOOTIN_BIND verified=1 ', b'FULLSYSTEM_BOOTIN_ENTER'))
                final_ready = bool(re.search(rb'OBS CREATE_SCREEN_ARGS [^\r\n]* id=0 count=565 ',data))
                final_ready = final_ready and b'OBS OSD_HEADLESS_PERSISTED ' in data
                final_due = final_ready and not final_diagnostics_sent and diagnostics_complete_at is not None
                if ((not diagnostics_sent and bootin_ready) or final_due) and (b'/ #' in data or b'~ #' in data):
                    diagnostic = (f'echo {begin}; busybox grep -E "^(Uid|Gid):" /proc/$$/status; '
                        'echo COLD_KERNEL_CMDLINE_BEGIN; cat /proc/cmdline; echo COLD_KERNEL_CMDLINE_END; '
                        'cat /proc/1/cmdline /proc/1/status /proc/1/mountinfo; '
                        f'observe_im={int(final_due)}; '
                        'for p in /proc/[0-9]*; do e=$(busybox readlink "$p/exe"); case "$e" in '
                        '/usr/bin/im.elf|/bin/im.elf|/usr/bin/bootin-original|/dev/qemu-simulation/bootin-original|/usr/bin/bootin.elf) '
                        'case "$e:$observe_im" in /usr/bin/im.elf:0|/bin/im.elf:0) continue;; esac; '
                        'image_sha=$(/usr/bin/openssl dgst -sha256 "$p/exe"); '
                        'if [ "$observe_im" = 1 ]; then echo COLD_PROCESS pid=${p##*/} exe=$e; fi; '
                        'echo "$image_sha"; '
                        'if [ "$observe_im" = 1 ]; then case "$e" in /usr/bin/im.elf|/bin/im.elf) '
                        f'case "$image_sha" in *"= {IM_SHA256}") echo COLD_NATIVE_IM pid=${{p##*/}} exe=$e sha256={IM_SHA256};; esac;; esac; fi; '
                        'case "$e" in /bin/im.elf) echo COLD_EXECUTABLE=/usr/bin/im.elf;; *) echo COLD_EXECUTABLE=$e;; esac; case "$image_sha" in '
                        f'*"= {BOOTIN_SHA256}") echo COLD_NATIVE_BOOTIN pid=${{p##*/}} sha256={BOOTIN_SHA256};; esac; '
                        'if busybox grep -q /usr/lib/appFw.so "$p/maps"; then '
                        'app_sha=$(/usr/bin/openssl dgst -sha256 /usr/lib/appFw.so); echo "$app_sha"; '
                        f'case "$app_sha" in *"= {APPFW_SHA256}") echo COLD_AP_MAP pid=${{p##*/}} sha256={APPFW_SHA256};; esac; fi; '
                        'cat "$p/cmdline" "$p/status" "$p/maps";; esac; done; '
                        'ls -l /dev/nflasha7 /dev/nflasha15 /simulation; '
                        'test ! -e /initrd/sbin/init; echo COLD_OLD_INITRD_PATH_ABSENT=$?; '
                        f'echo {end}\n')
                    if final_due:
                        begin+='F';end+='F'
                        diagnostic=diagnostic.replace('COLD_SESSION_BEGIN_'+nonce,begin).replace('COLD_SESSION_END_'+nonce,end)
                    diagnostic=diagnostic_envelope(diagnostic,'COLD_DIAG_SCRIPT_'+nonce+('F' if final_due else ''))
                    (output/('final-evidence-command.txt' if final_due else 'evidence-command.txt')).write_text(diagnostic)
                    write_console(owner.stdin,diagnostic.encode('ascii'))
                    diagnostics_sent = True
                    if final_due:
                        final_diagnostics_sent=True
                        diagnostics_complete_at=None
                if diagnostics_sent and end.encode() in data.splitlines() and diagnostics_complete_at is None:
                    diagnostics_complete_at = time.monotonic()
                    first = data.rfind((begin+'\r\n').encode())
                    last = data.rfind(end.encode())
                    (output/'guest-evidence.log').write_bytes(data[max(first,0):last+len(end)])
                if final_diagnostics_sent and diagnostics_complete_at is not None and validation is not None and not validation_sent:
                    tag='COLD_VALIDATION_SCRIPT_'+nonce
                    if tag in validation['text'].splitlines():raise ValueError('Validation delimiter collides with script')
                    custom=("busybox sh <<'"+tag+"'\n"+validation['text'].rstrip()+'\n'+tag+'\n'
                        'validation_rc=$?; echo COLD_VALIDATION_RC_'+nonce+'=$validation_rc\n')
                    write_console(owner.stdin,custom.encode('ascii'));validation_sent=True
                if validation_sent and validation_result is None:
                    matched=re.search(rb'(?:^|\n)COLD_VALIDATION_RC_'+nonce.encode()+rb'=(\d+)\r?(?:\n|$)',data)
                    if matched:
                        validation_result=int(matched[1]);validation_complete_at=time.monotonic()
                        save(output/'guest-validation-result.json',{'script_sha256':validation['sha256'],'returncode':validation_result})
                if validation_sent and command is not None:
                    for label in re.findall(rb'(?:^|\n)COLD_VALIDATION_SCREENSHOT=([a-z0-9_-]{1,32})\r?(?:\n|$)',data):
                        name=label.decode('ascii')
                        if name not in captured_labels:
                            command('screendump',{'filename':'/out/validation-'+name+'.ppm'});captured_labels.add(name)
                if validation is not None:
                    if validation_complete_at is not None and time.monotonic()-validation_complete_at>=3:break
                elif final_diagnostics_sent and diagnostics_complete_at is not None and time.monotonic() - diagnostics_complete_at >= 5:
                    break
                if any(marker in data for marker in (b'Kernel panic - not syncing:',
                        b'COLD_BOOTSTRAP_FAILED ', b'PERSISTENT_BOOTSTRAP_FAILED ', b'PERSISTENT_BOOTIN_BIND_FAILED_SHA')):
                    break
                time.sleep(.2)
            if command is not None and owner.poll() is None:
                try:
                    # Paths are inside this run's /out mount in the sandbox.
                    command('screendump', {'filename': '/out/cold-display.ppm'})
                except Exception as error:
                    save(output / 'display-error.json', {'error': str(error)})
        except BaseException as error:
            primary_error = error
        finally:
            try:
                if owner is not None and owner.poll() is None:
                    if command is None and Path(launch['qmp_socket']).is_socket():
                        connection, stream, command = qmp_connect(launch['qmp_socket'])
                    if command is None:
                        raise RuntimeError('QMP unavailable; retain owner, do not signal')
                    terminal['qmp_quit_attempted'] = True
                    save(output / 'qmp-quit.json', command('quit'))
                    terminal['qmp_quit_confirmed'] = True
                    owner.wait(timeout=30)
            except Exception as error:
                terminal['cleanup_error'] = type(error).__name__ + ': ' + str(error)
                if primary_error is None:
                    primary_error = error
            finally:
                terminal['process_still_running'] = owner is not None and owner.poll() is None
                if owner is not None:
                    terminal['returncode'] = owner.returncode
                    if not terminal['process_still_running'] and owner.stdin is not None:
                        owner.stdin.close()
                if terminal['process_still_running']:
                    save(output / 'owner-retained.json', terminal)
                for handle in (stream, connection):
                    if handle is not None:
                        try:
                            handle.close()
                        except OSError as error:
                            terminal.setdefault('close_errors', []).append(str(error))
                save(output / 'owner-exit.json', terminal)
    if validation is not None and (validation_result is None or validation_result!=0):
        primary_error=primary_error or RuntimeError('Guest validation incomplete or failed: '+str(validation_result))
    coverage = collect(console, receipt)
    result = {'schema': 1, 'receipt': receipt, 'coverage': coverage, **coverage,
              'owner': terminal, 'guest_started': owner is not None,
              'reboot_cause_verified': False,
              'guest_validation':{'requested':validation is not None,'returncode':validation_result,
                                  'script_sha256':validation['sha256'] if validation else None,
                                  'captured_screenshots':sorted(captured_labels)}}
    if primary_error is not None:
        result['error'] = type(primary_error).__name__ + ': ' + str(primary_error)
    save(output / 'boot-flow.json', result)
    if primary_error is not None:
        raise RuntimeError('Cold boot failed; owner and evidence retained at ' + str(output)) from primary_error
    return result
