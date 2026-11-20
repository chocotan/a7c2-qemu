"""Sole H GDB owner: original appFw mmap -> original pre-gate -> H, read-only."""
import hashlib
import json
import time
from pathlib import Path
import struct

PROFILE = 'virtual-model17c-runtime-ro-v1'
GATE = 0x209ec38


def metadata(raw, base):
    import hdmi_upm_watch as h
    rows = [line.split() for line in raw.decode('ascii').splitlines()]
    def one(tag, name):
        values = [row[2] for row in rows if len(row) == 3 and row[:2] == [tag, name]]
        h.require(len(values) == 1, 'Missing/ambiguous actual startup identity: ' + name)
        return int(values[0], 16)
    symbols = {name: one('MODEL17C_SYMBOL', name) for name in
               ('_text', 'vm_mmap_pgoff', 'memstart_addr', '__entry_task', '__per_cpu_offset')}
    texts = {name: one('MODEL17C_MODULE', name) for name in ('upm', 'osal_uipc')}
    h.context(texts)
    h.require(all(h.kernel(value) for value in symbols.values()), 'Actual kernel/percpu symbols unavailable')
    import model17c_runtime_observer as model
    shas = [row[0] for row in rows if len(row) == 2 and row[1] == '/usr/lib/appFw.so']
    h.require(shas == [model.ASSET_SHA256], 'Actual guest appFw digest differs')
    manifest_sha = hashlib.sha256(h.checked_read(
        base.parents[1] / 'source/persistent-flash/abi-manifest.json', 256 * 1024)).hexdigest()
    built = []
    for receipt_path in sorted(base.glob('persistent-flash-types/*/result.json')):
        receipt = h.parse_json(h.checked_read(receipt_path, 64 * 1024))
        carrier = receipt_path.parent / 'a7c2-kernel-types.elf'
        h.require(type(receipt.get('types')) is dict and 'sha256' in receipt['types'], 'Invalid type carrier receipt')
        if (receipt.get('source_manifest_sha256') == manifest_sha and receipt.get('kernel_release') == '4.9.337-scel+' and
                receipt.get('all_header_source_hashes_verified') is True and
                receipt.get('task_offsets') == {'pid': 0x388, 'tgid': 0x38c} and
                hashlib.sha256(h.checked_read(carrier, 16 * 1024 * 1024)).hexdigest() == receipt['types']['sha256']):
            built.append((carrier, receipt['types']['sha256']))
    h.require(len(built) == 1, 'No unique kernel type carrier built from the current kernel ABI manifest; no implicit build')
    types, types_sha = built[0]
    return dict(profile=PROFILE, symbols=symbols, module_texts=texts,
                types=str(types), types_sha256=types_sha)


def elf_bytes(raw, va, size):
    from hdmi_upm_watch import require
    require(raw[:6] == b'\x7fELF\x02\x01', 'Original AArch64 ELF required')
    phoff = struct.unpack_from('<Q', raw, 32)[0]
    entsize, count = struct.unpack_from('<HH', raw, 54)
    require(entsize == 56 and count < 1024, 'Invalid ELF program headers')
    matches = []
    for index in range(count):
        kind, flags, offset, address, _, filesz, _, _ = struct.unpack_from('<II6Q', raw, phoff + index * entsize)
        if kind == 1 and flags & 1 and address <= va and va + size <= address + filesz:
            matches.append(raw[offset + va - address:offset + va - address + size])
    require(len(matches) == 1 and len(matches[0]) == size, 'Original gate not uniquely file backed')
    return matches[0]


def revalidate_attached(config):
    """The empty-listener attach guard must not reject this owner's existing connection."""
    import os
    import socket
    import stat
    import hdmi_upm_watch as h
    root, info = h.validate_run(config['run'])
    h.require((info.st_dev, info.st_ino) == (config['run_device'], config['run_inode']), 'Startup run replaced')
    for kind in ('owner', 'qemu'):
        live = h.process_identity(config[kind + '_pid'])
        h.require(live['starttime'] == config[kind + '_starttime'] and live['exe'] == config[kind + '_exe'],
                  'Startup process generation changed')
    roots = h.socket_transport.endpoint_roots(root, **{key: config[key] for key in h.SOCKET_FIELDS if key in config})
    directory = root if roots is None else roots.sockets
    mount = '/out' if roots is None else '/sockets'
    proc = Path('/proc') / str(config['qemu_pid'])
    mounted = (proc / ('root' + mount)).stat()
    actual = directory.stat()
    h.require((mounted.st_dev, mounted.st_ino) == (actual.st_dev, actual.st_ino), 'Startup endpoint mount changed')
    sock = directory / h.SOCKET
    if roots is not None:
        roots.endpoint(sock)
    identity = sock.lstat()
    h.require(stat.S_ISSOCK(identity.st_mode) and identity.st_uid == os.getuid() and
              stat.S_IMODE(identity.st_mode) == 0o600 and
              (identity.st_dev, identity.st_ino) == (config['socket_device'], config['socket_inode']),
              'Startup GDB endpoint replaced')
    names = (str(sock), mount + '/' + h.SOCKET)
    rows = [line.split() for line in (proc / 'net/unix').read_text().splitlines()[1:]]
    listeners = [row for row in rows if len(row) == 8 and row[7] in names and
                 int(row[3], 16) & 0x10000 and row[4:6] == ['0001', '01']]
    links = {os.readlink(fd) for fd in (proc / 'fd').iterdir() if fd.exists()}
    h.require(len(listeners) == 1 and 'socket:[' + listeners[0][6] + ']' in links and
              ('gdb_endpoint' not in config or int(listeners[0][6]) == config['gdb_endpoint']['listener_inode']),
              'Startup QEMU listener ownership changed')
    # socket.fromfd leaks one descriptor per call on Python 3.14; wrap the
    # existing fd without dup or close instead (detach keeps it owned by us).
    matches = []
    for fd in Path('/proc/self/fd').iterdir():
        client = None
        try:
            client = socket.socket(fileno=int(fd.name))
            if client.family == socket.AF_UNIX and client.type == socket.SOCK_STREAM:
                peer = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if client.getpeername() in names and peer[:2] == (config['qemu_pid'], os.getuid()):
                    matches.append(int(fd.name))
        except OSError:
            pass
        finally:
            if client is not None:
                client.detach()
    h.require(len(matches) == 1, 'No unique same-owner GDB connection to bound QEMU')
    if 'qmp_endpoint' in config:
        h.require(h.socket_transport.checked_socket(root, Path(config['qmp_endpoint']['path']),
            config['qemu_pid'], socket_roots=roots) == config['qmp_endpoint'], 'Startup QMP endpoint changed')
    return config


def gdb_main(config_path, startup, config_sha256):
    import time as _t
    def _beat(phase):
        import json as _j
        try:
            (root / 'watch-heartbeat.json').write_text(_j.dumps(dict(phase=phase, ts=_t.strftime('%H:%M:%S'))) + '\n')
        except Exception:
            pass
    _beat('startup-enter')
    import gdb
    import hdmi_upm_watch as h
    owned, attached, detached = [], False, False
    failed_register = None
    root = Path(config_path).parent
    try:
        config = h.read_config(config_path, config_sha256=config_sha256)
        h.revalidate(config)
        h.require(startup['profile'] == PROFILE and config.get('mailbox') is None and
                  config['context']['module_texts'] == startup['module_texts'], 'Startup profile/context differs')
        types = Path(startup['types'])
        h.require(hashlib.sha256(h.checked_read(types, 16 * 1024 * 1024)).hexdigest() == startup['types_sha256'],
                  'Kernel type artifact changed')
        gdb.execute('set may-write-memory off', to_string=True)
        gdb.execute('set may-write-registers off', to_string=True)
        gdb.execute('symbol-file ' + json.dumps(str(types)), to_string=True)
        _beat('symbol-file-done')
        task_type = gdb.lookup_type('struct task_struct')
        h.require({f.name: f.bitpos // 8 for f in task_type.fields() if f.name in ('pid', 'tgid')} ==
                  {'pid': 0x388, 'tgid': 0x38c}, 'Kernel task ABI differs from H')
        abi = {'task_mm': {f.name: f.bitpos // 8 for f in task_type.fields()}['mm'],
               'mm_pgd': {f.name: f.bitpos // 8 for f in gdb.lookup_type('struct mm_struct').fields()}['pgd']}
        h.require(abi == {'task_mm': 0x2d8, 'mm_pgd': 0x40}, 'Kernel mm ABI differs from H')
        per_cpu = {name: startup['symbols'][name] for name in ('__entry_task', '__per_cpu_offset')}
        _beat('pre-attach')
        with h.debugger_endpoint(config) as address:
            attached = True
            gdb.execute('target remote ' + address, to_string=True)
        _beat('attached')
        inferior = gdb.selected_inferior()
        def reg(name):
            nonlocal failed_register
            try:
                # GDB hands raw registers back as signed longs; kernel pointers
                # like 0xffffff80... would turn negative and fail every
                # kernel-range check. Always mask to unsigned 64-bit.
                return int(gdb.selected_frame().read_register(name)) & 0xffffffffffffffff
            except BaseException as error:
                failed_register = name
                raise ValueError('register ' + name + ': ' + str(error)) from error
        def typed(kind, pointer):
            h.require(h.kernel(pointer), 'Non-kernel structure address: ' + kind)
            return gdb.Value(pointer).cast(gdb.lookup_type('struct ' + kind).pointer()).dereference()
        def number(value):
            return int(value)
        def string(pointer):
            address = number(pointer)
            data = bytearray()
            for index in range(4096):
                byte = bytes(inferior.read_memory(address + index, 1))[0]
                if not byte:
                    return data.decode('ascii')
                data.append(byte)
            raise ValueError('Unbounded kernel pathname')
        def path(file, task):
            fp = file['f_path']
            # /usr is a submount: file->mnt legitimately differs from the root
            # mount. This guest has a single mount namespace, so the strict
            # '/usr/lib/appFw.so' walk below (plus app_maps' path re-check)
            # carries the identity; here only require a real fs_struct.
            h.require(h.kernel(number(task['fs'])), 'Task fs_struct missing')
            node = fp['dentry']
            parts, seen = [], set()
            for _ in range(128):
                address = number(node)
                h.require(address not in seen, 'Cyclic appFw dentry path')
                seen.add(address)
                entry = node.dereference()
                if number(entry['d_parent']) == address:
                    return '/' + '/'.join(reversed(parts))
                parts.append(string(entry['d_name']['name']))
                node = entry['d_parent']
            raise ValueError('Unbounded appFw dentry path')
        def is_appfw_path(walked):
            # /usr is a submount: the dentry walk stops at its mount root, so
            # the mount-relative form 'lib/appFw.so' is the same file as the
            # canonical '/usr/lib/appFw.so' on the root mount.
            return walked in ('/usr/lib/appFw.so', '/lib/appFw.so')
        def app_maps(task_address):
            task = typed('task_struct', task_address)
            mm = task['mm'].dereference()
            rows, bases, seen = [], set(), set()
            node = mm['mmap']
            for _ in range(8192):
                address = number(node)
                if not address:
                    h.require(rows and len(bases) == 1, 'No unique actual appFw load bias')
                    return task, mm, ''.join(rows), bases.pop()
                h.require(address not in seen, 'Cyclic VMA chain')
                seen.add(address)
                vma = node.dereference()
                h.require(number(vma['vm_mm']) == number(task['mm']), 'Foreign mm in VMA chain')
                if number(vma['vm_file']):
                    file = vma['vm_file'].dereference()
                    if string(file['f_path']['dentry'].dereference()['d_name']['name']) == 'appFw.so':
                        h.require(is_appfw_path(path(file, task)), 'Unexpected appFw path')
                        start, end = number(vma['vm_start']), number(vma['vm_end'])
                        flags, offset = number(vma['vm_flags']), number(vma['vm_pgoff']) << 12
                        h.require(0 < start < end < 0x800000000000, 'Invalid actual appFw VMA')
                        if offset == 0:
                            bases.add(start)
                        inode = file['f_inode'].dereference()
                        dev = number(inode['i_sb'].dereference()['s_dev'])
                        perms = ''.join(c if flags & bit else '-' for c, bit in zip('rwx', (1, 2, 4)))
                        perms += 's' if flags & 8 else 'p'
                        rows.append(f'{start:x}-{end:x} {perms} {offset:08x} {dev >> 20:02x}:{dev & 0xfffff:02x} '
                                    f'{number(inode["i_ino"])} /usr/lib/appFw.so\n')
                node = vma['vm_next']
            raise ValueError('Unbounded VMA chain')
        def breakpoint(pc, condition=None):
            bp = gdb.Breakpoint('*' + hex(pc), type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
            owned.append(bp)
            if condition:
                bp.condition = condition
            gdb.execute('set breakpoint always-inserted on', to_string=True)
            h.require(bp.is_valid() and not bp.pending and bp.type == gdb.BP_HARDWARE_BREAKPOINT,
                      'Early hardware breakpoint insertion failed')
            return bp
        def delete(bp):
            bp.delete()
            h.require(not bp.is_valid(), 'Early hardware breakpoint deletion failed')
            owned.remove(bp)
        def resume_to(pc):
            revalidate_attached(config)
            gdb.execute('continue', to_string=True)
            h.require(reg('pc') == pc, 'Unexpected early stop/signal; resume refused')
        startup_symbols = {name: startup['symbols'][name] for name in ('__entry_task', '__per_cpu_offset')}
        symbols = dict(startup_symbols)
        symbols.update({name: startup['symbols'][name] for name in
                        ('_text', 'vm_mmap_pgoff', 'memstart_addr') if name in startup['symbols']})
        h.require({'_text', 'vm_mmap_pgoff', 'memstart_addr'} <= set(symbols),
                  'Startup symbols lack the early kernel anchors')
        kernel_path = Path('/proc') / str(config['qemu_pid']) / 'root/kernel.img'
        # Read the actual QEMU sandbox input, never a historical symbol address or opcode guess.
        kernel = kernel_path.read_bytes()
        mmap_pc = symbols['vm_mmap_pgoff']
        offset = mmap_pc - symbols['_text']
        h.require(0 <= offset <= len(kernel) - 16 and
                  bytes(inferior.read_memory(mmap_pc, 16)) == kernel[offset:offset + 16],
                  'Actual vm_mmap_pgoff bytes differ from original running kernel input')
        # ld.so maps appFw's initial span read-only and mprotects segments to
        # r-x afterwards, so filtering on PROT_EXEC here never catches it; stop
        # on every file-backed mmap and match by dentry name instead.
        _beat('mmap-bp-armed')
        entry = breakpoint(mmap_pc, '$x0 != 0')
        h.publish_json(root, 'model17c-startup-armed.json', dict(armed=True, profile=PROFILE,
            owner_pid=config['owner_pid'], qemu_pid=config['qemu_pid'], startup=startup,
            kernel_sha256=hashlib.sha256(kernel).hexdigest()))
        mmap_deadline = time.monotonic() + 300  # Bounded appFw mmap wait; no unbounded hang.
        mmap_names = []
        for _ in range(4096):
            h.require(time.monotonic() < mmap_deadline,
                      'Actual appFw executable mmap was not observed within the bounded startup window')
            resume_to(mmap_pc)
            cpu = gdb.selected_thread().num - 1
            h.require(0 <= cpu < 64, 'Invalid actual vCPU index')
            task_address = h.per_cpu_current(inferior, per_cpu, cpu)
            task = typed('task_struct', task_address)
            stack_base = number(task['stack'])
            h.require(reg('cpsr') & 15 >= 4 and stack_base <= reg('sp') < stack_base + h.THREAD_SIZE,
                      'Actual current task does not own this kernel stack')
            file_arg = reg('x0')
            if not h.kernel(file_arg):
                # Transient PC match (interrupt/branch target) is not a vm_mmap_pgoff
                # call frame; keep waiting for the actual appFw mmap.
                continue
            file = typed('file', file_arg)
            name = string(file['f_path']['dentry'].dereference()['d_name']['name'])
            if len(mmap_names) < 512:
                mmap_names.append(name)
                (root / 'model17c-mmap-names.txt').write_text('\n'.join(mmap_names) + '\n')
            if name != 'appFw.so':
                continue
            h.require(is_appfw_path(path(file, task)), 'Foreign appFw file')
            pid = number(task['tgid'])
            mm_address = number(task['mm'])
            pgd = number(task['mm'].dereference()['pgd'])
            memstart = int.from_bytes(bytes(inferior.read_memory(symbols['memstart_addr'], 8)), 'little')
            ttbr0 = h.derived_ttbr0(pgd, memstart)
            h.require(h.task_mm_pgd(inferior, task_address, abi) == (mm_address, pgd),
                      'Actual task mm->pgd binding differs')
            return_pc = reg('x30')
            return_offset = return_pc - symbols['_text']
            h.require(0 <= return_offset <= len(kernel) - 16 and not return_pc & 3 and
                      bytes(inferior.read_memory(return_pc, 16)) == kernel[return_offset:return_offset + 16],
                      'Original mmap return-site bytes differ')
            delete(entry)
            # The current task's kernel stack identifies the same task without reading SP_EL0.
            returning = breakpoint(return_pc, f'$sp >= {stack_base} && $sp < {stack_base + h.THREAD_SIZE}')
            resume_to(return_pc)
            h.require(0 < reg('x0') < 0x800000000000, 'Original appFw mmap failed')
            delete(returning)
            h.require(bytes(inferior.read_memory(return_pc, 16)) == kernel[return_offset:return_offset + 16],
                      'Temporary mmap return breakpoint changed original bytes')
            _, _, _, base = app_maps(task_address)
            gate = breakpoint(base + GATE)
            resume_to(base + GATE)
            h.require(gdb.selected_thread().num - 1 == cpu, 'Selected vCPU changed at the AP pre-gate stop')
            actual_task_address = h.per_cpu_current(inferior, per_cpu, cpu)
            actual_mm, actual_pgd = h.task_mm_pgd(inferior, actual_task_address, abi)
            actual_task, mm, maps, actual_base = app_maps(task_address)
            # The mapping thread (ld.so) and the gate-executing thread are
            # distinct task_structs of the same AP process: identity is the
            # address space (tgid/mm/pgd/bias), not the thread pointer.
            h.require(actual_mm == mm_address and
                      actual_pgd == pgd and actual_base == base and
                      number(actual_task['tgid']) == pid and
                      reg('cpsr') & 15 == 0,
                      'Actual pre-gate AP identity/address space changed')
            asset = h.checked_read(h.BASE / 'menu-root/usr/lib/appFw.so', 128 * 1024 * 1024, owner=False)
            env_start, env_end = number(mm['env_start']), number(mm['env_end'])
            h.require(0 < env_start < env_end and env_end - env_start <= 256 * 1024 and
                      ('MENU_MODEL17C_RUNTIME_OBSERVE=' + PROFILE).encode() in
                      bytes(inferior.read_memory(env_start, env_end - env_start)).split(b'\0'),
                      'Actual AP environment does not exclude inline model17c hooks')
            original = elf_bytes(asset, GATE, 16)
            h.require(bytes(inferior.read_memory(base + GATE, 16)) == original,
                      'Original AP pre-gate bytes changed')
            delete(gate)
            h.require(not gdb.parameter('may-write-memory') and not gdb.parameter('may-write-registers'),
                      'Early read-only debugger policy changed')
            h.require(bytes(inferior.read_memory(mmap_pc, 16)) == kernel[offset:offset + 16],
                      'Early kernel breakpoint bytes changed')
            binding = dict(profile=PROFILE, inline_profile=PROFILE, pid=pid, base=base, ttbr0=ttbr0, maps=maps,
                           task=actual_task_address, mm=mm_address, pgd=pgd, memstart=memstart, cpu=cpu,
                           symbols=per_cpu, abi=abi)
            revalidate_attached(config)
            h.require(hashlib.sha256((Path('/proc') / str(config['qemu_pid']) / 'exe').read_bytes()).hexdigest() ==
                      config['running_QEMU_sha256'], 'Actual running QEMU bytes changed')
            if config.get('readonly_scope_observer') is not None:
                h.require(h.scope_binding(root, config['scope_build_receipt'], config['running_QEMU_sha256']) ==
                          config['readonly_scope_observer'], 'Startup scope binding changed')
            runtime_binding = h.model17c_binding(binding, None)
            gate_snapshot = {}
            for field, offset, size in (
                    ('date_time_set_status', 0x7e5df40, 4),
                    ('clock_force_settled', 0x7eda8d0, 1),
                    ('unresolved_boot_setting', 0x7e6a7c8, 4),
                    ('unresolved_boot_setting_mirror', 0x7e6a7d0, 4),
                    ('current17c', 0x7e5d570, 4),
                    ('current17c_mirror', 0x7e5d578, 4),
                    ('helper_k', 0x7e739a8, 4)):
                address = base + offset
                raw = bytes(inferior.read_memory(address, size))
                gate_snapshot[field] = dict(address=address, bytes=raw.hex(),
                                            value=int.from_bytes(raw, 'little'))
            h.publish_json(root, 'model17c-startup-gate-snapshot.json', dict(
                schema='a7c2-model17c-pre-gate-snapshot-v1', pc=reg('pc'), base=base,
                future_gate=base + 0x209ee20, fields=gate_snapshot,
                observation_only=True, memory_or_registers_written=False))
            h.require(not owned, 'Early breakpoints remain before separate-process handoff')
            h.publish_json(root, 'model17c-startup-stop.json', dict(
                schema='a7c2-model17c-startup-stop-v2', binding=binding, runtime_binding=runtime_binding,
                task=actual_task_address, mapping_task=task_address,
                pgd=pgd, ttbr0_derived=ttbr0, ttbr0_source='task->mm->pgd + memstart_addr (no TTBR0_EL1 read)',
                maps_source='actual task->mm->mmap, appFw file mappings only',
                original_gate_hex=original.hex(), early_breakpoints_deleted=True,
                handoff='separate-gdb-process-v1'))
            # Never recurse into hdmi_upm_watch.gdb_main here: GDB 15 + embedded
            # Python 3.14 deadlocked on the GIL at that recursive call. Detach
            # and exit this short-lived process; the runner starts a fresh GDB.
            gdb.execute('detach', to_string=True)
            detached = True
            _beat('startup-detached')
            h.publish_json(root, 'model17c-startup-result.json', dict(
                schema='a7c2-model17c-startup-detached-v1', detached=True,
                separate_process_handoff=True, early_breakpoints_remaining=[],
                runtime_binding_sha256=hashlib.sha256(
                    json.dumps(runtime_binding, sort_keys=True).encode('ascii')).hexdigest()))
            return
        raise ValueError('Original appFw executable mapping not observed')
    except BaseException as error:
        for bp in owned:
            try:
                bp.delete()
            except BaseException:
                pass
        try:
            h.publish_json(root, 'model17c-startup-error.json', dict(error=type(error).__name__ + ': ' + str(error),
                register=failed_register,
                attached=attached, must_remain_stopped=attached and not detached, detached=detached,
                early_breakpoints_remaining=[bp.number for bp in owned if bp.is_valid()]))
        finally:
            if attached and not detached:
                h.retain_model17c_stop()
            raise
