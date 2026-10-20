"""Read-only guest thread evidence for the original AP EE entry investigation."""
import json
from pathlib import Path
import re
import struct
import tempfile

from capture_gate_readback import _task

CELLS = (('EE_START_ENABLE', 0x7e5c240), ('EE_ENTRY_SOURCE', 0x7e5dd40),
         ('EE_STATUS', 0x7e67700))


def status_fields(raw):
    """Keep scheduler/tracer state separate from userspace register evidence."""
    result = {}
    for key in ('Name', 'State', 'Tgid', 'Pid', 'TracerPid'):
        values = re.findall(rb'^'+key.encode()+rb':\s*([^\r\n]+)', raw, re.M)
        if len(values) == 1:
            result[key] = values[0].decode('ascii', errors='replace').strip()
    return result


def map_base(raw):
    matches = re.findall(rb'^([0-9a-f]+)-[0-9a-f]+\s+r.x.\s+00000000\s+\S+\s+\d+\s+/usr/lib/appFw\.so\s*$', raw, re.M)
    bases = {int(value, 16) for value in matches}
    if len(bases) != 1:
        raise ValueError('No unique original AP executable mapping')
    return next(iter(bases))


def thread_list(raw):
    text = raw.replace(b'\r\n', b'\n')
    markers = re.findall(rb'^EE_THREAD=(\d+):', text, re.M)
    entries = re.findall(rb'^EE_THREAD=(\d+):([^\n]{1,64})$', text, re.M)
    if not markers or len(markers) != len(entries) or len(set(markers)) != len(markers):
        raise ValueError('Incomplete or ambiguous guest thread list')
    result = [(int(tid), name.decode('utf-8', errors='replace')) for tid, name in entries]
    if len(result) > 256 or any(not 1 < tid < 2**31 for tid, _ in result):
        raise ValueError('Guest thread list outside bounded observation contract')
    return result


def normalized_frames(raw, tid, base):
    text = raw.decode('ascii', errors='replace')
    result = []
    for line in text.splitlines():
        if not re.match(r'^(?:REGS|FRAME) tid='+str(tid)+r'\b', line):
            continue
        for register, address in re.findall(r'\b(pc|lr)=(?:0x)?([0-9a-f]+)', line):
            actual = int(address, 16)
            if base <= actual < base + 0x51a6cff:
                result.append({'register': register, 'raw': hex(actual), 'elf_va': hex(actual-base)})
    return result


def syscall_state(raw):
    """Linux proc syscall: number, six arguments, user SP and PC."""
    matches = re.findall(rb'^(\d+)((?:\s+0x[0-9a-f]+){8})\s*$', raw, re.M)
    if len(matches) != 1:
        raise ValueError('No unique stopped-in-syscall observation')
    number, fields = matches[0]
    values = [int(value, 16) for value in fields.split()]
    sp, pc = values[-2:]
    if not 0x10000 < sp < 0x800000000000 or sp & 15 or not 0x10000 < pc < 0x800000000000:
        raise ValueError('Invalid userspace syscall boundary')
    return {'number': int(number), 'arguments': [hex(value) for value in values[:6]],
            'sp': sp, 'pc': pc}


def stack_candidates(raw, expected_sp, app_base):
    """Raw stack words are candidates, not authenticated return frames."""
    header = re.findall(rb'^READMEM \S+ address=([0-9a-f]+) bytes=(\d+)\r?$', raw, re.M)
    if len(header) != 1 or int(header[0][0], 16) != expected_sp:
        raise ValueError('Stack dump identity mismatch')
    expected_bytes = int(header[0][1])
    rows = re.findall(rb'^([0-9a-f]{16}):((?: [0-9a-f]{2}){1,16})\r?$', raw, re.M)
    data = bytearray()
    for address, octets in rows:
        if int(address, 16) != expected_sp + len(data):
            raise ValueError('Stack dump is discontinuous')
        data.extend(bytes.fromhex(octets.decode()))
    if not data or len(data) != expected_bytes or len(data) > 4096:
        raise ValueError('Stack dump byte count mismatch')
    result = []
    for offset in range(0, len(data)-7, 8):
        value, = struct.unpack_from('<Q', data, offset)
        if app_base <= value < app_base+0x51a6cff and value & 3 == 0:
            result.append({'stack_address': hex(expected_sp+offset), 'raw_word': hex(value),
                           'elf_va': hex(value-app_base)})
    return {'bytes': len(data), 'candidate_ap_code_words': result,
            'unwound_stack': False, 'current_blocker_proven': False}


def collect(serial, console, run):
    """serial is the existing serialized guest channel; UI supplies no shell text."""
    run = Path(run)
    output = Path(tempfile.mkdtemp(prefix='ee-snapshot-', dir=run))
    task = _task(console)

    def read(name, command):
        if any(len(line.encode('ascii')) > 120 for line in command.splitlines()):
            raise ValueError('EE diagnostic command line too long')
        raw = serial(command)
        (output/name).write_bytes(raw)
        return raw

    identity = read('identity.txt', f'/bin/busybox grep -E "^(Name|Tgid|Uid|Gid):" /proc/{task}/status')
    pids = re.findall(rb'^Tgid:\s*(\d+)\s*$', identity, re.M)
    if len(pids) != 1 or not 1 < int(pids[0]) < 2**31:
        raise ValueError('Invalid observed AP process identity')
    pid = int(pids[0])
    maps = read('maps.txt', f'cat /proc/{pid}/maps')
    base = map_base(maps)
    listing = read('threads.txt', f'for t in /proc/{pid}/task/[0-9]*; do c=$(cat "$t/comm"); echo EE_THREAD=${{t##*/}}:$c; done; true')
    threads = thread_list(listing)
    selected = [(tid, name) for tid, name in threads
                if name in ('AppFw', 'SeqQueueCommon', 'SeqQueueStillCa',
                            'CameraBackgroun', 'THREAD_INFRA1', 'InfraNotify')
                or name.startswith('SeqThreadPool')]
    if not any(name == 'SeqQueueCommon' for _, name in selected):
        raise ValueError('No original common sequence thread in observed list')
    records = []
    for tid, name in selected:
        before = read(f'thread-{tid}-status-before.txt', f'cat /proc/{pid}/task/{tid}/status')
        before_state = status_fields(before)
        read(f'thread-{tid}-wchan.txt', f'cat /proc/{pid}/task/{tid}/wchan; echo; true')
        syscall_before = read(f'thread-{tid}-syscall-before.txt',
                              f'cat /proc/{pid}/task/{tid}/syscall; true')
        if before_state.get('TracerPid') != '0':
            records.append({'tid': tid, 'name': name, 'returncode': None,
                            'registers_observed': False, 'ap_frames': [],
                            'status_before': before_state, 'status_after': before_state,
                            'skipped_reason': 'tracer identity unavailable or already attached'})
            continue
        if name == 'SeqQueueCommon':
            # The original OSAL wait did not report a ptrace stop in two runs.
            # Preserve its existing userspace stack without another SIGSTOP.
            item = {'tid': tid, 'name': name, 'returncode': None,
                    'registers_observed': False, 'ap_frames': [],
                    'status_before': before_state, 'sample_method': 'proc-syscall-and-stack'}
            try:
                boundary = syscall_state(syscall_before)
                sp = boundary['sp']
                memory = read(f'thread-{tid}-stack.txt',
                              f'/simulation/menu-readmem /proc/{pid}/mem {sp:#x} 4096')
                item['stack_observation'] = stack_candidates(memory, sp, base)
                repeated = read(f'thread-{tid}-syscall-after.txt',
                                f'cat /proc/{pid}/task/{tid}/syscall; true')
                item['syscall_before'] = boundary
                item['syscall_after'] = syscall_state(repeated)
                item['syscall_boundary_unchanged'] = item['syscall_before'] == item['syscall_after']
            except ValueError as error:
                item['observation_error'] = str(error)
            after = read(f'thread-{tid}-status-after.txt', f'cat /proc/{pid}/task/{tid}/status')
            item['status_after'] = status_fields(after)
            item['raw_stack_collected'] = bool(item.get('syscall_boundary_unchanged') and
                                               item['status_after'].get('TracerPid') == '0')
            records.append(item)
            continue
        raw = read(f'thread-{tid}.txt',
                   f'/simulation/menu-regs {tid}; r=$?; echo EE_REG_RC_{tid}=$r; true')
        after = read(f'thread-{tid}-status-after.txt', f'cat /proc/{pid}/task/{tid}/status')
        after_state = status_fields(after)
        rc = re.findall(rb'^EE_REG_RC_'+str(tid).encode()+rb'=(\d+)\r?$', raw, re.M)
        observed = re.search(rb'^REGS tid='+str(tid).encode()+rb'\b', raw, re.M) is not None
        records.append({'tid': tid, 'name': name, 'returncode': int(rc[0]) if len(rc) == 1 else None,
                        'registers_observed': observed,
                        'status_before': before_state, 'status_after': after_state,
                        'ap_frames': normalized_frames(raw, tid, base)})
    cells = []
    for name, address in CELLS:
        raw = read(name.lower()+'.txt',
                   f'/simulation/menu-readmem /proc/{pid}/mem {address:#x} 4 appFw.so')
        match = re.search(rb'^[0-9a-fA-F]+:\s*((?:[0-9a-fA-F]{2} ){3}[0-9a-fA-F]{2})', raw, re.M)
        cells.append({'name': name, 'elf_va': hex(address),
                      'value': int.from_bytes(bytes.fromhex(match[1].decode()), 'little') if match else None})
    # Original CameraBackground dispatch object and its state word; read-only.
    read('camera-background-object.txt',
         f'/simulation/menu-readmem /proc/{pid}/mem 0x2eb8e0 64 libObj.so')
    report = {'scope': 'original AP EE fields and sequential read-only register snapshots',
              'ok': all((item['returncode'] == 0 and item['registers_observed'])
                        or item.get('raw_stack_collected') is True for item in records)
                    and all(item['status_after'].get('TracerPid') == '0' for item in records)
                    and all(item['value'] is not None for item in cells),
              'snapshot_dir': str(output), 'app_pid': pid, 'frame_tid': task,
              'app_base': hex(base), 'thread_count': len(records), 'threads': records, 'cells': cells,
              'listed_threads': len(threads),
              'skipped_threads': [{'tid': tid, 'name': name} for tid, name in threads
                                  if (tid, name) not in selected],
              'atomic_snapshot': False, 'current_blocker_proven': False, 'capture_verified': False}
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
