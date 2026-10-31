"""Original UPM observer; only optional dedicated receipt transport writes.

Host API: start(run, owner_pid, {'upm': T, 'osal_uipc': O}, mailbox=None,
                scope_build_receipt=None).
Optional mailbox={'phys': actual_pagemap_page_pa, 'nonce': u64, 'pid': AP_pid}
uses the frozen device-models/hdmi-upm-receipt.h ABI (256 bytes). Only this
explicit transport permits writes: armed status, verified receipt, commit status.
Physical debug address mode is restored after each access. Mailbox mode resumes
automatically after native free; the default mode below uses a host ACK.
The run must be a direct menu-runs child. Its QEMU descendant must own the Unix
listener <run>/hdmi-upm-gdb.sock (startup -gdb or a host-created dynamic endpoint).
start() returns only after arming. After each published receipt, the guest stays
at the real free return until ack_receipt(run, receipt['bridge_seq']) or a bounded
20-second timeout. Acknowledge only after binding/retiring the A lease on the host.
stop() returns cleanup evidence; safe_to_close must be true before the
caller discards the VM. read_receipts(run) replays the published JSONL, including
while the watcher is running. Receipts are native allocation retirements ONLY;
the caller must separately bind U, raw16, source, bridge_seq and chronology to a
published A-console lease serial before forgetting that lease (never free again).

Module bases must come from actual guest module sections/kallsyms before the
original application starts. In particular OSAL may be built in: no guessed base.
The OSAL bridge ABI is w0=destination, x1=U, x2=fd context, NOT x0=U.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import struct
import subprocess
import sys
import threading
import time

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import scope_observer_profile

RUNS = BASE / 'menu-runs'
SOCKET = 'hdmi-upm-gdb.sock'
PREFIX = 'hdmi-upm-watch'
LIMIT = 64
SECONDS = 120
QEMU_SHA = 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
READONLY_SCOPE_QEMU_SHA = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
QUEUE = 0x80920572
SOURCE = 0x909a015a
MESSAGE = 0x00920117
MAILBOX_MAGIC = 0x4d505548
MAILBOX_RECORD = 256
MAILBOX_PROOF = 0x7f
SHAS = {'upm': 'a8b16e1484be48d32c4a401897d13378cf45e5ef6654ebdcfdef5fc593da32eb',
        'osal_uipc': 'f0eb3a32a9d339066600e012aa3e91de31419c173e3fe5c1cc44aa9188763095'}
# Only these original instructions are breakpoints. CALL26 words are relocated.
POINTS = {'task_entry': ('upm', 0xe0), 'receive_call': ('upm', 0x104),
          'receive': ('upm', 0x108), 'load': ('upm', 0x138),
          'consumer': ('upm', 0x126e8), 'branch': ('upm', 0x12908),
          'handled': ('upm', 0x140), 'free_return': ('upm', 0x14c),
          'bridge': ('osal_uipc', 0x13c0), 'send': ('osal_uipc', 0x13f4),
          'free_entry': ('osal_uipc', 0x4650),
          'vpool': ('osal_uipc', 0x4720), 'vpool_fallback': ('osal_uipc', 0x4768),
          'fblock': ('osal_uipc', 0x478c)}
CALLS = {'receive_call': ('osal_uipc', 0x4198), 'send': ('osal_uipc', 0x3bf8),
         'branch': ('upm', 0x10ce8), 'vpool': ('osal_uipc', 0x6bb8),
         'vpool_fallback': ('osal_uipc', 0x6bb8), 'fblock': ('osal_uipc', 0x67f0)}
REGS = ('pc', 'sp', 'sp_el0') + tuple('x' + str(n) for n in range(31))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def kernel(value):
    return type(value) is int and 0xffffff8000000000 <= value < 0xfffffffffffff000


def mailbox_header(config):
    require(type(config) is dict and set(config) == {'phys', 'nonce', 'pid'}, 'Exact dedicated mailbox binding required')
    require(type(config['phys']) is int and 0x400000000 <= config['phys'] < 0x540000000 and
            not config['phys'] & 4095 and type(config['pid']) is int and 1 < config['pid'] < 2**31 and
            type(config['nonce']) is int and 0 < config['nonce'] < 2**64, 'Invalid actual mailbox PFN/nonce/PID')
    return struct.pack('<IIQI', MAILBOX_MAGIC, 1, config['nonce'], config['pid'])


def mailbox_binding(config, record, order, u, raw_hex):
    require(len(record) == MAILBOX_RECORD and record[:20] == mailbox_header(config),
            'Dedicated mailbox magic/version/nonce/PID changed')
    status, serial, pointer = struct.unpack_from('<IQQ', record, 20)
    require(status == 2 and 0 < serial < 2**64 and pointer == u and record[40:56].hex() == raw_hex and
            struct.unpack_from('<I', record, 108)[0] == order - 1 and
            struct.unpack_from('<I', record, 148)[0] == 0 and record[224:] == bytes(32),
            'Mailbox request lease/U/raw/index differs')
    return serial


def mailbox_request_context(record, module_texts, producer_tid):
    require(struct.unpack_from('<I', record, 144)[0] == producer_tid and
            struct.unpack_from('<2Q4I', record, 160) ==
            (module_texts['upm'], module_texts['osal_uipc'], SOURCE, QUEUE, 16, 0x009a0000),
            'Mailbox original modules/source/actual producer TID differ')


def fnv64(raw):
    result = 0xcbf29ce484222325
    for value in raw:
        result = ((result ^ value) * 0x100000001b3) & 0xffffffffffffffff
    return result


def mailbox_payload(config, request, receipt):
    serial = mailbox_binding(config, request, receipt['order'], receipt['u'], receipt['raw_hex'])
    require(receipt.get('lease_serial') == serial and receipt.get('native_allocation_retired') is True,
            'Mailbox has no matched native retirement')
    mailbox_request_context(request, receipt['module_texts'], receipt['producer_tid'])
    result = bytearray(request)
    struct.pack_into('<I', result, 20, 3)
    result[56:72] = bytes.fromhex(receipt['effective_hex'])
    struct.pack_into('<2Q6I', result, 72, receipt['k'], receipt['task'], receipt['tid'], 0, 1, 1,
                     MAILBOX_PROOF, receipt['order'] - 1)
    struct.pack_into('<4Q2I', result, 112, receipt['module_texts']['upm'] + 0x126e8,
                     receipt['module_texts']['upm'] + 0x14c, receipt['user_pool'], receipt['kernel_pool'],
                     receipt['producer_tid'], 0)
    allocator_pc = receipt['module_texts']['osal_uipc'] + POINTS[receipt['allocator']][1]
    struct.pack_into('<2Q4I4Q', result, 160, receipt['module_texts']['upm'], receipt['module_texts']['osal_uipc'],
                     SOURCE, QUEUE, 16, 0x009a0000, allocator_pc, receipt['bridge_seq'],
                     receipt['events']['free_return'], receipt['producer_task'])
    result[224:] = bytes(32)
    struct.pack_into('<Q', result, 152, fnv64(result[:20] + result[24:152] + result[160:]))
    return bytes(result)


def physical_mailbox(gdb, inferior, config, action='read', receipt=None):
    """QEMU debug address mode only; never change guest translation registers."""
    mailbox_header(config)
    address = config['phys']
    try:
        reply = gdb.execute('maintenance packet Qqemu.PhyMemMode:1', to_string=True)
        require('received: "OK"' in reply, 'QEMU physical memory mode refused')
        raw = bytes(inferior.read_memory(address, MAILBOX_RECORD))
        require(raw[:20] == mailbox_header(config) and struct.unpack_from('<I', raw, 148)[0] == 0,
                'Dedicated physical mailbox header differs')
        if action == 'read':
            return raw
        require(action in ('arm', 'receipt'), 'Unknown dedicated mailbox operation')
        if action == 'arm':
            require(struct.unpack_from('<I', raw, 20)[0] == 0, 'Mailbox is not initially unarmed')
            payload = bytearray(raw)
            struct.pack_into('<I', payload, 20, 1)
        else:
            payload = mailbox_payload(config, raw, receipt)
        # Only transport data in this pinned page; commit status after readback.
        gdb.execute('set may-write-memory on', to_string=True)
        try:
            if action == 'receipt':
                inferior.write_memory(address + 56, bytes(payload[56:]))
                require(bytes(inferior.read_memory(address + 56, MAILBOX_RECORD - 56)) == payload[56:], 'Receipt payload readback differs')
            inferior.write_memory(address + 20, bytes(payload[20:24]))
            require(bytes(inferior.read_memory(address, MAILBOX_RECORD)) == payload, 'Mailbox commit readback differs')
        finally:
            gdb.execute('set may-write-memory off', to_string=True)
        return bytes(payload)
    finally:
        reply = gdb.execute('maintenance packet Qqemu.PhyMemMode:0', to_string=True)
        require('received: "OK"' in reply, 'QEMU virtual memory mode restoration failed')


def context(module_texts):
    require(type(module_texts) is dict and set(module_texts) == set(SHAS), 'Two actual module text bases required')
    require(all(kernel(v) and not v & 3 for v in module_texts.values()), 'Invalid module text base')
    return dict(module_texts=module_texts.copy(), module_sha256=SHAS.copy())


def original_opcodes(module_texts):
    context(module_texts)
    originals = {}
    for module, digest in SHAS.items():
        path = BASE / 'menu-root/usr/kmod' / (module + '.ko')
        raw = checked_read(path, 2 * 1024 * 1024, owner=False)
        require(hashlib.sha256(raw).hexdigest() == digest, 'Original module SHA differs: ' + module)
        require(raw[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', raw, 18)[0] == 183,
                'Original module is not AArch64 ELF')
        originals[module] = raw
    result = {}
    for kind, (module, offset) in POINTS.items():
        if kind in CALLS:
            target_module, target_offset = CALLS[kind]
            delta = module_texts[target_module] + target_offset - module_texts[module] - offset
            require(not delta & 3 and -(1 << 27) <= delta < (1 << 27), 'Original CALL26 needs an unverified veneer')
            result[kind] = struct.pack('<I', 0x94000000 | ((delta >> 2) & 0x3ffffff))
        else:
            size = 12 if kind == 'bridge' else 4
            result[kind] = originals[module][0x68 + offset:0x68 + offset + size]
    return result


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def publish_json(root, name, data):
    temporary = root / (name + '.tmp')
    with temporary.open('x', encoding='ascii') as output:
        output.write(json.dumps(data))
    os.link(temporary, root / name, follow_symlinks=False)
    temporary.unlink()


def checked_read(path, limit, owner=True):
    path = Path(path).absolute()
    require(path.resolve() == path, 'Symlink path refused: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and (not owner or info.st_uid == os.getuid()) and
                not info.st_mode & 0o022 and info.st_size <= limit, 'Untrusted file: ' + str(path))
        with os.fdopen(fd, 'rb', closefd=False) as source:
            data = source.read(limit + 1)
        require(len(data) <= limit, 'File exceeded bound')
        return data
    finally:
        os.close(fd)


def process_identity(pid):
    require(type(pid) is int and 1 < pid < 2**31, 'Invalid owner/QEMU PID')
    proc = Path('/proc') / str(pid)
    require(proc.stat().st_uid == os.getuid(), 'Process UID differs')
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    require(fields[0] != 'Z', 'Process is a zombie')
    return dict(pid=pid, starttime=int(fields[19]), ppid=int(fields[1]),
                exe=os.readlink(proc / 'exe'), cmdline=(proc / 'cmdline').read_bytes().split(b'\0')[:-1])


def validate_run(run):
    run = Path(run).absolute()
    require(run.resolve() == run and run.parent == RUNS.resolve(), 'Not a direct, nonsymlink menu run')
    info = run.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022,
            'Run directory ownership/permissions differ')
    return run, info


def scope_binding(root, receipt_value, running_qemu_sha256):
    """Bind the reviewed host build and this run's staged plugin to the owned exe."""
    require(running_qemu_sha256 == READONLY_SCOPE_QEMU_SHA,
            'Scope observer requires the exact reviewed running QEMU executable')
    manifest = parse_json(checked_read(root / 'runtime-manifest.json', 4 * 1024 * 1024))
    require(type(manifest) is dict, 'Scope observer requires the actual run manifest')
    scope, backup, files = (manifest.get(name) for name in ('readonly_scope_observer', 'backup_transport', 'files'))
    require(type(scope) is dict and type(scope.get('profile')) is str and
            scope['profile'] in scope_observer_profile.SOURCE_SETS and
            scope.get('identity_binding') == 'unverified' and scope.get('capture_verified') is False and
            scope.get('physical_asic_compatibility_verified') is False and
            scope.get('log') == str(root / 'readonly-scope-trace.log') and
            type(backup) is dict and type(backup.get('binary')) is str and type(files) is dict,
            'Scope observer manifest profile/binary/files binding missing or changed')
    receipt_path, binary = Path(receipt_value), Path(backup['binary'])
    require(receipt_path.is_absolute() and receipt_path.resolve() == receipt_path and
            scope.get('build_receipt') == str(receipt_path) and
            binary.is_absolute() and binary.resolve() == binary,
            'Scope observer requires the same canonical receipt and host candidate paths')
    # /proc/PID/exe is deliberately hashed separately, never passed as an ordinary file.
    build = scope_observer_profile.validate_build(BASE.parents[1], receipt_path, binary)
    require(build['qemu_sha256'] == running_qemu_sha256 and
            backup.get('binary_sha256') == running_qemu_sha256,
            'Scope observer candidate differs from the actual running QEMU')
    for name in ('profile', 'build_receipt', 'build_receipt_sha256', 'qemu_sha256',
                 'qemu_header_sha256', 'source_sha256', 'library_sha256'):
        require(scope.get(name) == build[name], 'Scope observer manifest build binding changed: ' + name)
    if build['profile'] in (scope_observer_profile.PROFILE_V2, scope_observer_profile.PROFILE_V3):
        for name in ('trace_schema', 'trace_schema_sha256', 'source_contract_sha256'):
            require(scope.get(name) == build[name],
                    'Scope observer ' + build['profile'][-2:] + ' manifest schema binding changed: ' + name)
        if build['profile'] == scope_observer_profile.PROFILE_V3:
            require(not {'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256',
                         'source_root', 'Source_root', 'sourceDependencyFrozen'} & scope.keys(),
                    'Scope observer v3 manifest has a schema digest/root alias')
    require(hashlib.sha256(checked_read(receipt_path, 1024 * 1024)).hexdigest() == build['build_receipt_sha256'],
            'Scope observer build receipt changed during validation')
    staged = root / 'readonly-scope-observer.so'
    require(scope.get('library') == str(staged) and
            hashlib.sha256(checked_read(staged, 16 * 1024 * 1024)).hexdigest() == build['library_sha256'],
            'Scope observer staged library differs from the reviewed build')
    source_root = scope_observer_profile.source_root(BASE.parents[1], build['profile'])
    bound_files = {str(binary): running_qemu_sha256, str(receipt_path): build['build_receipt_sha256'],
                   str(staged): build['library_sha256'],
                   **{str(source_root / name): digest for name, digest in build['source_sha256'].items()}}
    require(all(files.get(path) == digest for path, digest in bound_files.items()),
            'Scope observer manifest.files differs from the actual bound assets')
    bound = dict(build, staged_library=str(staged), qemu_binary=str(binary))
    if 'plan_binding' in scope:
        require(type(scope['plan_binding']) is dict, 'Scope observer plan binding must be an object')
        bound['plan_binding'] = scope['plan_binding']
    return bound


def owned_config(run, owner_pid, module_texts, mailbox=None, scope_build_receipt=None):
    root, info = validate_run(run)
    ctx = context(module_texts)
    if mailbox is not None:
        mailbox_header(mailbox)
    original_opcodes(module_texts)
    owner = process_identity(owner_pid)
    sock = (root / SOCKET).lstat()
    require(stat.S_ISSOCK(sock.st_mode) and sock.st_uid == os.getuid() and not sock.st_mode & 0o022,
            'Not an owned private Unix GDB socket (chmod 0600 before start)')
    candidates = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            candidate = process_identity(int(entry.name))
            if Path(candidate['exe']).name != 'qemu-system-aarch64':
                continue
            args = [v.decode('utf-8', 'strict') for v in candidate['cmdline']]
            sockets = [args[i + 1].split(',')[0] for i, arg in enumerate(args[:-1]) if arg == '-gdb']
            if sockets and sockets not in (['unix:' + str(root / SOCKET)], ['unix:/out/' + SOCKET]):
                continue
            mounted = (entry / 'root/out').stat()
            if (mounted.st_dev, mounted.st_ino) != (info.st_dev, info.st_ino):
                continue
            # QEMU lives in bwrap's network namespace, not the host's.
            matches = [line.split()[6] for line in (entry / 'net/unix').read_text().splitlines()[1:]
                       if len(line.split()) == 8 and line.split()[7] in (str(root / SOCKET), '/out/' + SOCKET) and
                       int(line.split()[3], 16) & 0x10000 and line.split()[4] == '0001']
            if len(matches) != 1:
                continue
            links = set()
            for descriptor in (entry / 'fd').iterdir():
                try:
                    links.add(os.readlink(descriptor))
                except FileNotFoundError:
                    pass
            if 'socket:[' + matches[0] + ']' not in links:
                continue
            ancestor = candidate
            for _ in range(32):
                if ancestor['ppid'] == owner_pid:
                    candidates.append(candidate)
                    break
                if ancestor['ppid'] <= 1:
                    break
                ancestor = process_identity(ancestor['ppid'])
        except (OSError, ValueError, UnicodeError):
            continue
    require(len(candidates) == 1, 'No unique owned QEMU descendant with the exact Unix GDB endpoint')
    qemu = candidates[0]
    if mailbox is not None:
        args = [v.decode('utf-8', 'strict') for v in qemu['cmdline']]
        memory = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == '-m']
        require(memory == ['24576'], 'Mailbox requires the verified 24GiB backing and 5GiB high-DDR guest window')
    exe = Path('/proc') / str(qemu['pid']) / 'exe'
    executable = exe.stat()
    require(stat.S_ISREG(executable.st_mode) and executable.st_uid == os.getuid() and
            not executable.st_mode & 0o022, 'Untrusted actual running QEMU executable')
    actual_qemu_sha256 = hashlib.sha256(exe.read_bytes()).hexdigest()
    expected_qemu_sha256 = QEMU_SHA if scope_build_receipt is None else READONLY_SCOPE_QEMU_SHA
    require(actual_qemu_sha256 == expected_qemu_sha256, 'Untrusted actual running QEMU executable')
    scope = None if scope_build_receipt is None else scope_binding(root, scope_build_receipt, actual_qemu_sha256)
    return dict(running_QEMU_sha256=actual_qemu_sha256, run=str(root), run_device=info.st_dev, run_inode=info.st_ino,
                scope_build_receipt=None if scope is None else scope['build_receipt'], readonly_scope_observer=scope,
                socket_device=sock.st_dev, socket_inode=sock.st_ino,
                owner_pid=owner_pid, owner_starttime=owner['starttime'], owner_exe=owner['exe'],
                qemu_pid=qemu['pid'], qemu_starttime=qemu['starttime'], qemu_exe=qemu['exe'],
                context=ctx, mailbox=mailbox, limit=LIMIT, seconds=SECONDS)


def revalidate(config):
    actual = owned_config(config['run'], config['owner_pid'], config['context']['module_texts'],
                          config.get('mailbox'), config.get('scope_build_receipt'))
    require(actual == config, 'Run/process/socket/module binding changed')
    return actual


def memory(event, name, address, size):
    item = event['memory'][name]
    require(type(item) is dict and set(item) == {'address', 'hex'} and item['address'] == address and
            type(item['hex']) is str and len(item['hex']) == size * 2, 'Bad memory evidence: ' + name)
    raw = bytes.fromhex(item['hex'])
    require(raw.hex() == item['hex'], 'Noncanonical memory evidence')
    return raw


def snapshot(event, pointer, expected_ref=1):
    require(kernel(pointer), 'Invalid kernel message pointer')
    header = memory(event, 'header', pointer - 24, 24)
    body = memory(event, 'body', pointer, 16)
    require(struct.unpack_from('<I', header, 12)[0] == SOURCE and
            struct.unpack_from('<I', header, 16)[0] == 16 and
            struct.unpack_from('<H', header, 10)[0] == expected_ref, 'Wrong source/length/refcount')
    words = struct.unpack('<4I', body)
    require(words[0] == MESSAGE and words[2:] == (0x009a0000, 0), 'Wrong UPM message body')
    return header, body


class Correlator:
    """Fail closed on contradictory evidence; incomplete lifetimes yield no receipt."""
    def __init__(self, module_texts, mailbox=None):
        self.mailbox = mailbox
        if mailbox is not None:
            mailbox_header(mailbox)
        self.context = context(module_texts)
        self.opcodes = original_opcodes(module_texts)
        self.sequence = 0
        self.leases = []
        self.active = {}
        self.bridges = {}
        self.pending = None
        self.receipts = []

    def feed(self, event):
        require(type(event) is dict and type(event.get('seq')) is int and event['seq'] == self.sequence + 1,
                'Missing, reordered or duplicate event')
        require(event.get('context') == self.context, 'Module context changed')
        self.sequence += 1
        require(self.sequence <= LIMIT, 'Event bound exceeded')
        kind = event.get('kind')
        if kind == 'receipt':
            require(self.pending is not None and event.get('receipt') == self.pending, 'Unproved or duplicate receipt')
            self.receipts.append(self.pending)
            self.pending = None
            return
        require(self.pending is None, 'Missing published receipt')
        require(kind in POINTS, 'Unknown observation')
        regs = event['registers']
        require(type(regs) is dict and all(type(regs.get(n)) is int and 0 <= regs[n] < 2**64 for n in REGS),
                'Incomplete raw CPU registers')
        module, offset = POINTS[kind]
        pc = self.context['module_texts'][module] + offset
        require(regs['pc'] == pc and memory(event, 'opcode', pc, len(self.opcodes[kind])) == self.opcodes[kind],
                'Original runtime opcode/PC differs')
        task = regs['sp_el0']
        require(kernel(task), 'sp_el0 is not a kernel task')
        tid = int.from_bytes(memory(event, 'task_pid', task + 0x388, 4), 'little', signed=True)
        require(0 < tid < 2**31 and event.get('kernel_tid') == tid, 'Kernel task PID evidence differs')
        key = (task, tid)
        if kind in ('task_entry', 'receive_call'):
            if kind == 'receive_call':
                require(regs['x0'] & 0xffffffff == QUEUE and regs['x1'] == regs['x29'] + 32,
                        'Wrong original receive arguments')
            return
        if kind == 'bridge':
            require(len(self.leases) < 2 and key not in self.bridges and regs['x0'] & 0xffffffff == QUEUE,
                    'Repeated bridge or wrong destination')
            u, ctx = regs['x1'], regs['x2']
            require(24 <= u < 0x800000000000 and kernel(ctx), 'Invalid U/fd context')
            userbase = int.from_bytes(memory(event, 'user_pool', ctx + 48, 8), 'little')
            literal = int.from_bytes(memory(event, 'kernel_literal', self.context['module_texts']['osal_uipc'] + 0x1400, 8), 'little')
            require(kernel(literal), 'Relocated pool slot is not kernel memory')
            kbase = int.from_bytes(memory(event, 'kernel_pool', literal + 64, 8), 'little')
            require(0 < userbase <= u and 24 <= u - userbase < 0x200000 and kernel(kbase), 'Invalid actual U/K pool mapping')
            k = kbase + u - userbase
            require(not any(p['k'] == k and p['stage'] != 'retired' for p in self.leases), 'Kernel allocation reused before final retirement')
            header, body = snapshot(event, k)
            require(memory(event, 'user_body', u, 16) == body and
                    memory(event, 'user_header', u - 24, 24)[8:] == header[8:], 'U/K aliases differ')
            require(struct.unpack_from('<I', body, 4)[0] == (0, 2)[len(self.leases)], 'Wrong selected raw ID/order')
            lease = dict(order=len(self.leases) + 1, bridge_seq=event['seq'], u=u, k=k,
                         user_pool=userbase, kernel_pool=kbase, fd_context=ctx,
                         producer_task=task, producer_tid=tid, bridge_sp=regs['sp'],
                         raw_hex=body.hex(), source=SOURCE, stage='bridge', events={'bridge': event['seq']})
            if self.mailbox is not None:
                request = memory(event, 'mailbox_record', self.mailbox['phys'], MAILBOX_RECORD)
                lease['lease_serial'] = mailbox_binding(self.mailbox, request, lease['order'], u, lease['raw_hex'])
                mailbox_request_context(request, self.context['module_texts'], tid)
                producer_pid = int.from_bytes(memory(event, 'task_tgid', task + 0x38c, 4), 'little', signed=True)
                require(producer_pid == self.mailbox['pid'], 'Mailbox owner differs from actual native producer TGID')
                require(not any(p.get('lease_serial') == lease['lease_serial'] for p in self.leases),
                        'Mailbox lease serial reused across transactions')
            self.leases.append(lease)
            self.bridges[key] = lease
            return
        if kind == 'send':
            lease = self.bridges.pop(key, None)
            require(lease is not None and regs['x0'] & 0xffffffff == QUEUE and regs['x1'] == lease['k'] and
                    regs['x29'] == lease['bridge_sp'] - 16 and regs['sp'] == regs['x29'], 'Bad bridge-to-send frame/mapping')
            _, body = snapshot(event, lease['k'])
            require(body.hex() == lease['raw_hex'], 'Raw body mutated before send')
            lease['stage'] = 'sent'
            lease['events']['send'] = event['seq']
            return
        if kind == 'receive':
            require(regs['x0'] & 0xffffffff == 0 and key not in self.active, 'Receive failed or active frame replaced')
            k = int.from_bytes(memory(event, 'receive_slot', regs['x29'] + 32, 8), 'little')
            matches = [p for p in self.leases if p['k'] == k and p['stage'] == 'sent']
            require(len(matches) == 1, 'Receive has no unique actual send mapping')
            lease = matches[0]
            _, body = snapshot(event, k)
            require(body.hex() == lease['raw_hex'] and regs['sp'] == regs['x29'], 'Receive body/frame differs')
            lease.update(task=task, tid=tid, frame=regs['x29'], stage='receive')
            self.active[key] = lease
        else:
            lease = self.active.get(key)
            require(lease is not None, 'No same-task active receive frame')
            frame = lease['frame']
            if kind == 'load':
                require(lease['stage'] == 'receive' and regs['x29'] == frame and regs['sp'] == frame and
                        int.from_bytes(memory(event, 'receive_slot', frame + 32, 8), 'little') == lease['k'],
                        'Wrong original body load')
                _, body = snapshot(event, lease['k'])
                require(body.hex() == lease['raw_hex'], 'Raw body mutated before consumer')
                lease['stage'] = 'load'
            elif kind == 'consumer':
                require(lease['stage'] == 'load' and regs['x0'] == lease['k'] and regs['x30'] == self.context['module_texts']['upm'] + 0x140 and
                        regs['x29'] == frame and regs['sp'] == frame, 'Wrong original consumer/frame/caller')
                _, body = snapshot(event, lease['k'])
                require(body.hex() == lease['raw_hex'], 'Raw body mutated at consumer entry')
                lease['stage'] = 'consumer'
            elif kind == 'branch':
                require(lease['stage'] == 'consumer' and regs['x19'] == lease['k'] and
                        regs['x29'] == frame - 144 and regs['sp'] == frame - 144, 'Wrong specific handler branch/frame')
                _, body = snapshot(event, lease['k'])
                raw = bytes.fromhex(lease['raw_hex'])
                op = struct.unpack_from('<I', body, 4)[0]
                require(body[:4] == raw[:4] and body[8:] == raw[8:] and
                        op in ((0,) if lease['order'] == 1 else (2, 3)) and
                        regs['x1'] & 0xffffffff == op and regs['x2'] & 0xffffffff == 0x009a0000,
                        'Wrong effective handler arguments/body')
                lease.update(effective_hex=body.hex(), stage='branch')
            elif kind == 'handled':
                require(lease['stage'] == 'branch' and regs['x29'] == frame and regs['sp'] == frame and
                        int.from_bytes(memory(event, 'receive_slot', frame + 32, 8), 'little') == lease['k'],
                        'Handler returned without the specific branch/same frame')
                header, body = snapshot(event, lease['k'])
                require(body.hex() == lease['effective_hex'], 'Effective body changed after branch')
                lease.update(stage='handled', final_header_hex=header.hex())
            elif kind == 'free_entry':
                require(lease['stage'] == 'handled' and regs['x0'] & 0xffffffff == QUEUE and regs['x1'] == lease['k'] and
                        regs['x30'] == self.context['module_texts']['upm'] + 0x14c and
                        regs['x29'] == frame and regs['sp'] == frame, 'Free before handler or wrong queue/frame/caller')
                header, body = snapshot(event, lease['k'])
                require(body.hex() == lease['effective_hex'] and header[8:] == bytes.fromhex(lease['final_header_hex'])[8:],
                        'Allocation changed before native free')
                lease.update(stage='free_entry', free_header_hex=header.hex())
            elif kind in ('vpool', 'vpool_fallback', 'fblock'):
                require(lease['stage'] == 'free_entry' and regs['x29'] == frame - 16 and regs['sp'] == frame - 16,
                        'Allocator is outside the same osal_free_msg frame')
                saved = memory(event, 'free_frame', frame - 16, 16)
                require(struct.unpack('<2Q', saved) == (frame, self.context['module_texts']['upm'] + 0x14c),
                        'Allocator saved caller/frame differs')
                header, body = snapshot(event, lease['k'], expected_ref=0)
                before = bytes.fromhex(lease['free_header_hex'])
                require(header[8:10] == before[8:10] and header[12:] == before[12:] and
                        body.hex() == lease['effective_hex'], 'Allocator allocation/refcount transition differs')
                units, flags = header[8], header[9]
                allocation = lease['k'] - 24 - (40 if flags & 0x40 else 0)
                if kind == 'fblock':
                    require(units == 0 and regs['x0'] == lease['k'] - 24, 'Wrong free_fblock allocation')
                else:
                    require(regs['x1'] == allocation and regs['x2'] == (units * 64 if units else 64) and
                            (kind != 'vpool_fallback' or units != 0) and kernel(regs['x0']), 'Wrong vpool allocation/size')
                lease.update(stage='allocator', allocator=kind, allocator_header_hex=header.hex())
            elif kind == 'free_return':
                # No K or header reads at/after this point: its lifetime is over.
                require(lease['stage'] == 'allocator' and regs['x0'] & 0xffffffff == 0 and
                        regs['x29'] == frame and regs['sp'] == frame and
                        set(event['memory']) == {'opcode', 'task_pid'}, 'Missing final release marker, free error or post-free read')
                lease.update(stage='retired')
                del self.active[key]
            else:
                raise ValueError('Unexpected lifetime event')
        lease['events'][kind] = event['seq']
        if lease['stage'] == 'retired':
            self.pending = {name: lease[name] for name in
                            ('order', 'bridge_seq', 'u', 'k', 'user_pool', 'kernel_pool', 'fd_context',
                             'producer_task', 'producer_tid', 'task', 'tid', 'frame', 'raw_hex',
                             'effective_hex', 'source', 'allocator', 'free_header_hex', 'allocator_header_hex', 'events')}
            # Freeze the complete receipt before any later pointer reuse.
            self.pending = json.loads(json.dumps(dict(self.pending, native_allocation_retired=True,
                                                     module_texts=self.context['module_texts'],
                                                     lease_serial=lease.get('lease_serial'),
                                                     a_lease_binding_verified=self.mailbox is not None)))
            return self.pending


def read_receipts(run):
    root, info = validate_run(run)
    config = parse_json(checked_read(root / (PREFIX + '-config.json'), 16384))
    require(config['run'] == str(root) and config['limit'] == LIMIT and
            config['run_device'] == info.st_dev and config['run_inode'] == info.st_ino,
            'Receipt run/config differs')
    raw = checked_read(root / (PREFIX + '-events.jsonl'), 1024 * 1024)
    require(not raw or raw.endswith(b'\n'), 'Incomplete published event line')
    tracker = Correlator(config['context']['module_texts'], config.get('mailbox'))
    require(config['context'] == tracker.context, 'Receipt module context differs')
    for line in raw.splitlines():
        tracker.feed(parse_json(line))
    return tracker.receipts


def acknowledgement(receipt):
    return {key: receipt[key] for key in ('bridge_seq', 'u', 'k', 'events')}


def ack_receipt(run, bridge_seq):
    require(type(bridge_seq) is int and 0 < bridge_seq <= LIMIT, 'Invalid receipt bridge sequence')
    receipts = [r for r in read_receipts(run) if r['bridge_seq'] == bridge_seq]
    require(len(receipts) == 1, 'No unique published native retirement to acknowledge')
    root, _ = validate_run(run)
    publish_json(root, PREFIX + f'-ack-{bridge_seq}.json', acknowledgement(receipts[0]))
    return receipts[0]


class Watch:
    def __init__(self, run, owner_pid, module_texts, mailbox=None, scope_build_receipt=None):
        self.config = owned_config(run, owner_pid, module_texts, mailbox, scope_build_receipt)
        self.run = Path(self.config['run'])
        self.process = self.log = None
        self.cleanup = None
        executable = shutil.which('gdb')
        require(executable is not None, 'Installed AArch64 GDB required')
        self.executable = executable
        config_path = self.run / (PREFIX + '-config.json')
        config_raw = json.dumps(self.config).encode('ascii')
        with config_path.open('xb') as output:
            output.write(config_raw)
        config_sha256 = hashlib.sha256(config_raw).hexdigest()
        script = self.run / (PREFIX + '.gdb')
        code = ('set pagination off\nset confirm off\nset architecture aarch64\nset language c\n'
                'set remotetimeout 4\npython\nimport importlib.util, sys\n'
                f'sys.path.insert(0, {str(BASE)!r})\n'
                f's=importlib.util.spec_from_file_location("hdmi_upm_watch", {str(Path(__file__).resolve())!r})\n'
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                f'm.gdb_main({str(config_path)!r}, config_sha256={config_sha256!r})\nend\n')
        with script.open('x', encoding='ascii') as output:
            output.write(code)
        try:
            revalidate(self.config)
            self.log = (self.run / (PREFIX + '-gdb.log')).open('xb')
            self.process = subprocess.Popen([executable, '-q', '-nx', '-nh', '-batch', '-x', str(script)],
                                            cwd=self.run, stdout=self.log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
            deadline = time.monotonic() + 12
            ready = self.run / (PREFIX + '-ready.json')
            while time.monotonic() < deadline:
                if ready.exists():
                    data = parse_json(checked_read(ready, 16384))
                    require(data == dict(connected=True, armed=True, context=self.config['context']), 'Unverified observer readiness')
                    if self.process.poll() is not None:
                        result = parse_json(checked_read(self.run / (PREFIX + '-result.json'), 16384))
                        require(not result.get('error') and result.get('detached') is True,
                                'HDMI debugger failed after arming; inspect its result')
                    return
                require(self.process.poll() is None, 'HDMI debugger exited; inspect its GDB log')
                time.sleep(.05)
            raise TimeoutError('HDMI kernel observer did not arm within 12 seconds')
        except BaseException as error:
            try:
                cleanup = self.stop()
            except BaseException as cleanup_error:
                cleanup = dict(debugger_stopped=False, detached=False, safe_to_close=False,
                               errors=[str(cleanup_error)])
            error.hdmi_upm_watcher = self
            error.hdmi_upm_cleanup = cleanup
            raise

    def stop(self):
        if self.cleanup and self.cleanup['safe_to_close']:
            return self.cleanup
        errors = []
        if self.process is not None and self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.cleanup = dict(debugger_stopped=False, detached=False, safe_to_close=False,
                                        errors=['Debugger still alive after SIGINT/TERM; retained without SIGKILL'])
                    return self.cleanup
        detached = False
        if self.process is not None:
            try:
                result = parse_json(checked_read(self.run / (PREFIX + '-result.json'), 16384))
                detached = result.get('detached') is True
            except (OSError, ValueError) as error:
                errors.append(str(error))
            if not detached:
                try:
                    revalidate(self.config)
                    # Reconnect only after the old GDB exited; remote detach resumes QEMU.
                    result = subprocess.run([self.executable, '-q', '-nx', '-nh', '-batch',
                                             '-ex', 'set confirm off', '-ex', 'set remotetimeout 4',
                                             '-ex', 'set may-write-memory off', '-ex', 'set may-write-registers off',
                                             '-ex', 'target remote ' + SOCKET,
                                             '-ex', 'python import gdb; gdb.execute("detach"); print("HDMI_UPM_DETACHED")'],
                                            cwd=self.run, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, check=False)
                    detached = result.returncode == 0 and b'HDMI_UPM_DETACHED' in result.stdout
                    if not detached:
                        errors.append(result.stdout.decode(errors='replace')[-2048:])
                except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                    errors.append(str(error))
        if self.log is not None:
            self.log.close()
        stopped = self.process is None or self.process.poll() is not None
        self.cleanup = dict(debugger_stopped=stopped, detached=detached,
                            safe_to_close=stopped and (self.process is None or detached), errors=errors)
        return self.cleanup


def start(run, owner_pid, module_texts, mailbox=None, scope_build_receipt=None):
    return Watch(run, owner_pid, module_texts, mailbox, scope_build_receipt)


def gdb_main(config_path, config_sha256=None):
    import gdb
    config_raw = checked_read(config_path, 16384)
    require(config_sha256 is None or hashlib.sha256(config_raw).hexdigest() == config_sha256,
            'Watcher configuration changed before GDB reload')
    config = parse_json(config_raw)
    revalidate(config)
    root = Path(config['run'])
    tracker = Correlator(config['context']['module_texts'], config.get('mailbox'))
    result = dict(connected=False, armed=False, detached=False,
                  running_QEMU_sha256=config.get('running_QEMU_sha256'),
                  readonly_scope_observer=config.get('readonly_scope_observer'),
                  observations_only=config.get('mailbox') is None,
                  dedicated_receipt_transport=config.get('mailbox') is not None, events=0)
    breakpoints, stops = {}, []
    done = threading.Event()
    events = None
    attached = False

    def watchdog():
        deadline = time.monotonic() + SECONDS
        while not done.wait(.2):
            try:
                owner = process_identity(config['owner_pid'])
                live = owner['starttime'] == config['owner_starttime'] and owner['exe'] == config['owner_exe']
            except (OSError, ValueError):
                live = False
            if not live or time.monotonic() >= deadline:
                os.kill(os.getpid(), signal.SIGINT)
                return

    def stopped(event):
        stops.append(dict(numbers=[bp.number for bp in (getattr(event, 'breakpoints', None) or ())],
                          signal=getattr(event, 'stop_signal', None)))

    def emit(event):
        event.update(seq=tracker.sequence + 1, context=tracker.context)
        events.write(json.dumps(event, separators=(',', ':')) + '\n')
        events.flush()
        result['events'] = event['seq']
        receipt = tracker.feed(event)
        if receipt:
            emit(dict(kind='receipt', receipt=receipt))
            if config.get('mailbox') is not None:
                result.setdefault('mailbox_deliveries', []).append(dict(
                    bridge_seq=receipt['bridge_seq'], lease_serial=receipt['lease_serial'],
                    record_sha256=hashlib.sha256(physical_mailbox(gdb, inferior, config['mailbox'],
                                                                'receipt', receipt)).hexdigest()))
                return
            path = root / (PREFIX + f'-ack-{receipt["bridge_seq"]}.json')
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if path.exists():
                    require(parse_json(checked_read(path, 16384)) == acknowledgement(receipt),
                            'Host acknowledgement differs from actual native retirement')
                    return
                done.wait(.05)
            raise TimeoutError('Native free observed; host did not acknowledge A-lease retirement within 20 seconds')

    try:
        events = (root / (PREFIX + '-events.jsonl')).open('x', encoding='ascii')
        gdb.execute('set may-write-memory off', to_string=True)
        gdb.execute('set may-write-registers off', to_string=True)
        attached = True  # Even a partly failed connection must take the detach path.
        gdb.execute('target remote ' + SOCKET, to_string=True)
        result['connected'] = True
        gdb.events.stop.connect(stopped)
        inferior = gdb.selected_inferior()
        for kind, (module, offset) in POINTS.items():
            pc = tracker.context['module_texts'][module] + offset
            actual_opcode = bytes(inferior.read_memory(pc, len(tracker.opcodes[kind])))
            result['last_opcode_check'] = dict(kind=kind, pc=pc, expected_hex=tracker.opcodes[kind].hex(),
                                               actual_hex=actual_opcode.hex())
            require(actual_opcode == tracker.opcodes[kind], 'Original opcode differs before arming: ' + kind)
            if kind in ('task_entry', 'receive_call'):
                continue
            bp = gdb.Breakpoint('*' + hex(pc), type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
            breakpoints[bp.number] = (bp, kind)
            require(bp.type == gdb.BP_HARDWARE_BREAKPOINT, 'Software breakpoint fallback refused')
        def select_breakpoints():
            for bp, kind in breakpoints.values():
                clauses = []
                if kind == 'bridge' and len(tracker.leases) < 2:
                    clauses = [f'(($x0 & 0xffffffff) == {QUEUE} && $x1 >= 24 && $x1 < 0x800000000000 && '
                               f'*(unsigned int*)$x1 == {MESSAGE} && *(unsigned int*)($x1-8) == 16 && '
                               f'*(unsigned int*)($x1-12) == {SOURCE})']
                elif kind == 'send':
                    clauses = [f'($sp_el0 == {p["producer_task"]} && $x1 == {p["k"]})'
                               for p in tracker.bridges.values()]
                elif kind == 'receive':
                    clauses = [f'(($x0 & 0xffffffff) == 0 && *(unsigned long long*)($x29+32) == {p["k"]})'
                               for p in tracker.leases if p['stage'] == 'sent']
                else:
                    for p in tracker.active.values():
                        binding = f'$sp_el0 == {p["task"]}'
                        if kind == 'consumer':
                            binding += f' && $x0 == {p["k"]}'
                        elif kind == 'branch':
                            binding += f' && $x19 == {p["k"]}'
                        elif kind == 'free_entry':
                            binding += f' && $x30 == {tracker.context["module_texts"]["upm"] + 0x14c}'
                        elif kind in ('vpool', 'vpool_fallback', 'fblock'):
                            if p['stage'] != 'free_entry':
                                continue
                            binding += f' && $x29 == {p["frame"] - 16}'
                        else:
                            binding += f' && $x29 == {p["frame"]}'
                        clauses.append('(' + binding + ')')
                bp.enabled = bool(clauses)
                if clauses:
                    bp.condition = ' || '.join(clauses)
        select_breakpoints()
        # Force remote hardware insertion before publishing readiness.
        gdb.execute('set breakpoint always-inserted on', to_string=True)
        if config.get('mailbox') is not None:
            physical_mailbox(gdb, inferior, config['mailbox'], 'arm')
        result['armed'] = True
        publish_json(root, PREFIX + '-ready.json', dict(connected=True, armed=True, context=tracker.context))
        threading.Thread(target=watchdog, daemon=True).start()
        for _ in range(LIMIT):
            if tracker.sequence >= LIMIT - 1:
                break
            select_breakpoints()
            stops.clear()
            gdb.execute('continue', to_string=True)
            if any(e['signal'] == 'SIGINT' for e in stops):
                raise KeyboardInterrupt()
            numbers = {n for e in stops for n in e['numbers']} & breakpoints.keys()
            require(len(numbers) == 1, 'Unexpected original-kernel stop: ' + str(stops))
            kind = breakpoints[next(iter(numbers))][1]
            regs = {}
            for name in REGS:
                try:
                    value = gdb.parse_and_eval('$' + name)
                    regs[name] = int(value) & 0xffffffffffffffff
                except Exception:
                    if name != 'sp_el0':
                        raise
                    regs[name] = int(gdb.parse_and_eval('$SP_EL0')) & 0xffffffffffffffff
            event = dict(kind=kind, registers=regs, memory={}, gdb_vcpu_thread=gdb.selected_thread().num)
            result['last_observation'] = event  # Preserve partial raw reads if validation fails.

            def read(name, address, size):
                raw = bytes(inferior.read_memory(address, size))
                event['memory'][name] = dict(address=address, hex=raw.hex())
                return raw

            pc = regs['pc']
            read('opcode', pc, len(tracker.opcodes[kind]))
            require(kernel(regs['sp_el0']), 'Cannot read actual current kernel task')
            event['kernel_tid'] = int.from_bytes(read('task_pid', regs['sp_el0'] + 0x388, 4), 'little', signed=True)
            key = (regs['sp_el0'], event['kernel_tid'])
            lease = tracker.active.get(key)
            k = None
            if kind in ('task_entry', 'receive_call'):
                # Boot worker setup is optional; selected lifetime evidence begins at the bridge.
                continue
            if kind == 'bridge':
                if regs['x0'] & 0xffffffff != QUEUE or len(tracker.leases) == 2:
                    continue
                u, ctx = regs['x1'], regs['x2']
                raw = read('user_body', u, 16)
                if struct.unpack_from('<I', raw)[0] != MESSAGE:
                    continue
                read('user_header', u - 24, 24)
                userbase = int.from_bytes(read('user_pool', ctx + 48, 8), 'little')
                literal = int.from_bytes(read('kernel_literal', tracker.context['module_texts']['osal_uipc'] + 0x1400, 8), 'little')
                require(kernel(literal), 'Invalid actual relocated pool literal')
                kbase = int.from_bytes(read('kernel_pool', literal + 64, 8), 'little')
                require(24 <= u - userbase < 0x200000 and kernel(kbase), 'Actual U/K mapping out of bounds')
                k = kbase + u - userbase
                if config.get('mailbox') is not None:
                    read('task_tgid', regs['sp_el0'] + 0x38c, 4)
                    raw_mailbox = physical_mailbox(gdb, inferior, config['mailbox'])
                    event['memory']['mailbox_record'] = dict(address=config['mailbox']['phys'], hex=raw_mailbox.hex())
            elif kind == 'send':
                if key not in tracker.bridges:
                    continue
                k = tracker.bridges[key]['k']
            elif kind == 'receive':
                if regs['x0'] & 0xffffffff:
                    continue
                k = int.from_bytes(read('receive_slot', regs['x29'] + 32, 8), 'little')
                if not any(p['k'] == k and p['stage'] == 'sent' for p in tracker.leases):
                    continue
            elif lease is None:
                continue
            elif kind in ('load', 'handled'):
                read('receive_slot', lease['frame'] + 32, 8)
                k = lease['k']
            elif kind == 'free_entry':
                # Other frees inside the handler (state-list kfree) are never selected.
                if regs['x30'] != tracker.context['module_texts']['upm'] + 0x14c:
                    continue
                k = lease['k']
            elif kind in ('vpool', 'vpool_fallback', 'fblock'):
                if lease['stage'] != 'free_entry':
                    continue
                read('free_frame', regs['x29'], 16)
                k = lease['k']
            elif kind != 'free_return':
                k = lease['k']
            if k is not None:
                require(kernel(k), 'Invalid kernel body address')
                read('header', k - 24, 24)
                read('body', k, 16)
            emit(event)
            if len(tracker.receipts) == 2:
                break
        result.update(receipts=len(tracker.receipts), capture_limit_reached=tracker.sequence >= LIMIT - 1)
    except KeyboardInterrupt:
        result['interrupted'] = True
    except BaseException as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        done.set()
        try:
            gdb.events.stop.disconnect(stopped)
        except Exception:
            pass
        for bp, _ in breakpoints.values():
            try:
                bp.delete()
            except Exception as error:
                result['breakpoint_cleanup_error'] = str(error)
        if attached:
            try:
                gdb.execute('detach', to_string=True)
                result['detached'] = True
            except Exception as error:
                result['detach_error'] = str(error)
        if events is not None:
            events.close()
        with (root / (PREFIX + '-result.json')).open('x') as output:
            json.dump(result, output, indent=2)
