"""Owned-run, read-only QEMU/GDB queue observations. Never a wake/dispatch proof."""
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import stat
import struct
import subprocess
import time

RUNS = Path(__file__).resolve().parent / 'menu-runs'
AP_SHA = '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
SOCKET = 'request-queue-gdb.sock'
CONTROL_SOCKET = 'request-queue-control.sock'


def sequence_stack_command(pid, ui_tid):
    if any(type(value) is not int or not 1 < value < 2**31 for value in (pid, ui_tid)):
        raise ValueError('Invalid observed guest process/thread binding')
    return (f'echo POWER_UI_PID={pid} POWER_UI_TID={ui_tid}; cat /proc/{pid}/maps; '
            f'for t in /proc/{pid}/task/[0-9]*; do '
            'co=$(/bin/busybox cat "$t/comm" 2>/dev/null); '
            'echo POWER_THREAD ${t##*/} "$co"; '
            'case "$co" in SeqQueueStillCa) /simulation/menu-regs "${t##*/}" --stillca;; '
            '*) /simulation/menu-regs "${t##*/}";; esac; done; true')


class RetainableTestDirectory:
    """Keep the control mailbox if a live VM cannot safely be torn down."""
    def __enter__(self):
        import tempfile
        self.path = Path(tempfile.mkdtemp(prefix='sony-natural-gtk-'))
        self.retain = False
        return self

    def __exit__(self, *unused):
        if not self.retain:
            shutil.rmtree(self.path)


def resume_owned_debug_cpu(fd):
    info = os.stat(CONTROL_SOCKET, dir_fd=fd, follow_symlinks=False)
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('Not the owned debug-cleanup QMP socket')
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(4)
        client.connect(f'/proc/self/fd/{fd}/{CONTROL_SOCKET}')
        with client.makefile('rwb') as stream:
            def receive():
                line = stream.readline(65537)
                if len(line) > 65536 or not line.endswith(b'\n'):
                    raise RuntimeError('Invalid cleanup QMP reply boundary')
                return json.loads(line)
            if 'QMP' not in receive():
                raise RuntimeError('Invalid cleanup QMP greeting')
            sequence = 0
            def qmp(command):
                nonlocal sequence
                sequence += 1
                stream.write((json.dumps(dict(execute=command, id=sequence)) + '\n').encode())
                stream.flush()
                for _ in range(32):
                    reply = receive()
                    if 'event' in reply:
                        continue
                    if reply.get('id') != sequence or 'error' in reply or 'return' not in reply:
                        raise RuntimeError('Invalid cleanup QMP command reply: ' + str(reply))
                    return reply
                raise RuntimeError('Cleanup QMP event limit reached')
            qmp('qmp_capabilities')
            return resume_debug_cpu(qmp)


def app_base(readback, lookahead=6):
    """Resolve the original AP base from a MODE_DIAL/MODE_SWITCH readback.

    Kernel UIPC warnings and OBS lines are interleaved with the transaction on
    the shared console, so the READMEM line is not necessarily adjacent to its
    label. Allow a bounded lookahead instead, and still require exactly one
    matching pair per label.
    """
    lines = [line.strip() for line in readback.splitlines() if line.strip()]
    pattern = re.compile(r'READMEM /proc/(\d+)/mem address=([0-9a-fA-F]+) bytes=4')
    found = {}
    for label, offset in (('MODE_DIAL', 0x7ee4750), ('MODE_SWITCH', 0x7ee4778)):
        hits = []
        for i, line in enumerate(lines):
            if line != label:
                continue
            # Stop at the next label: a later transaction's result must never be
            # adopted for this one, while interleaved console noise is skipped.
            window, seen = [], set()
            for follow in lines[i + 1:i + 1 + lookahead]:
                if follow in ('MODE_DIAL', 'MODE_SWITCH'):
                    break
                match = pattern.fullmatch(follow)
                if match:
                    seen.add((int(match[1]), int(match[2], 16) - offset))
            if len(seen) == 1:
                hits.append(next(iter(seen)))
        if len(hits) != 1:
            raise ValueError('Expected one original AP readback: ' + label)
        found[label] = hits[0]
    pid, base = found['MODE_DIAL']
    if found['MODE_SWITCH'] != (pid, base) or pid <= 1 or not 0x100000 <= base < 0x800000000000 or base & 4095:
        raise ValueError('Inconsistent original AP readbacks')
    return pid, base


def preinit_gate(console):
    """Exclude selftest/non-ELF identities before checking original uniqueness."""
    candidates = set()
    for pid, base, gate in re.findall(
            rb'OBS OBSERVER_READY MEDIA_INIT_GATE pid=(\d+) base=(0x[0-9a-f]+) wait_us=10000000 gate=(0x[0-9a-f]+)', console):
        pid, base, gate = int(pid), int(base, 16), int(gate, 16)
        if (pid > 1 and 0x100000 <= base < 0x800000000000 and not base & 4095 and
                0x100000 <= gate < 0x800000000000 and not gate & 3):
            candidates.add((pid, base, gate))
    if len(candidates) > 1:
        raise ValueError('No unique original pre-init gate')
    return next(iter(candidates)) if candidates else None


def owned_config(run, sequence, owner_pid, trace_mode='counter'):
    if trace_mode not in ('counter', 'handoff', 'media', 'media-policy', 'media-init', 'resize'):
        raise ValueError('Unknown owned queue observation mode')
    run = Path(run).absolute()
    info = run.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or run.parent.resolve() != RUNS.resolve():
        raise ValueError('Not an owned camera run directory')
    manifest_path = run / 'runtime-manifest.json'
    if manifest_path.is_symlink():
        raise ValueError('Manifest symlink refused')
    manifest = json.loads(manifest_path.read_text())
    if (owner_pid <= 1 or manifest.get('host_control_owner_pid') != owner_pid or manifest.get('overwrite') or
            manifest.get('selected_initramfs_verified_files', {}).get('usr/lib/appFw.so') != AP_SHA or
            not all(manifest.get(key) is True for key in
                    (('request_queue_gdb', 'resize_mmio_watch') if trace_mode == 'resize' else
                     ('request_queue_gdb', 'media_init_watch') if trace_mode == 'media-init' else
                     ('request_queue_gdb', 'mode_state_readback', 'media_predicate_observe') if trace_mode in ('media', 'media-policy')
                     else ('request_queue_gdb', 'power_notice_observe', 'apo_cancel_request_probe', 'mode_state_readback')))):
        raise ValueError('Queue observation requires the owned original-AP experiment')
    if not isinstance(sequence, int) or isinstance(sequence, bool) or not (0 if trace_mode in ('media-init','resize') else 1) <= sequence < 10000000:
        raise ValueError('Invalid validated snapshot sequence')
    if trace_mode == 'resize':
        from resize_mmio_watch import KERNEL_SHA
        if manifest.get('selected_initramfs_verified_files', {}).get('system/av-cam.bin') != KERNEL_SHA:
            raise ValueError('Resize observation requires the original verified kernel component')
        pid, base = 0, 0  # Kernel addresses do not use an AP process mapping.
    elif trace_mode == 'media-init':
        console = run/'console.log'
        if console.is_symlink():
            raise ValueError('Console symlink refused')
        gate = preinit_gate(console.read_bytes())
        if gate is None:
            raise ValueError('No unique original pre-init gate')
        pid, base, gate_address = gate
        if manifest.get('selected_observer_matches_build') is not True:
            raise ValueError('Invalid original pre-init identity')
    else:
        readback = run / f'mode-state-{sequence:04d}.txt'
        if readback.is_symlink():
            raise ValueError('Readback symlink refused')
        pid, base = app_base(readback.read_text(errors='strict'))
    fd = os.open(run, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        sock = os.stat(SOCKET, dir_fd=fd, follow_symlinks=False)
        if not stat.S_ISSOCK(sock.st_mode) or sock.st_uid != os.getuid():
            raise ValueError('Not the owned QEMU Unix debug socket')
        config = dict(owner_pid=owner_pid, sequence=sequence, app_pid=pid, app_base=base, queue=base + 0x7e4e5d0,
                        publish_pc=base + 0x24d8774, cancel_caller=base + 0x262aafc,
                        socket=f'/proc/self/fd/{fd}/{SOCKET}', run=str(run),
                        run_device=info.st_dev, run_inode=info.st_ino, limit=16, trace_mode=trace_mode)
        if trace_mode=='resize' and manifest.get('rc_board_profile') is True:
            config['limit']=64  # Three frames can now execute both completion and cleanup paths.
            config['observe_sa_mmu']=True
            config['observe_sa_completion']=manifest.get('sa_reference_completion') is True
        if trace_mode == 'media-init':
            config['observer_gate_address'] = gate_address
        return fd, config
    except BaseException:
        os.close(fd)
        raise


class QueueWatch:
    def __init__(self, run, sequence, owner_pid, trace_mode='counter', autostart=True):
        self.run = Path(run).absolute()
        self.fd = None
        self.process = None
        self.log = None
        self.cleanup = None
        self.start_arguments = (run, sequence, owner_pid, trace_mode)
        if autostart:
            self.start()

    def start(self):
        if self.process is not None:
            raise RuntimeError('Queue debugger already started')
        try:
            self.fd, config = owned_config(*self.start_arguments)
            executable = shutil.which('gdb')
            if not executable:
                raise RuntimeError('Local AArch64-capable gdb is unavailable')
            config_path = self.run / 'queue-watch-config.json'
            script = self.run / 'queue-watch.gdb'
            with config_path.open('x') as file:
                json.dump(config, file, indent=2)
            code = ('set pagination off\nset confirm off\nset architecture aarch64\nset language c\npython\n'
                    'import importlib.util\n'
                    f'import sys;sys.path.insert(0,{json.dumps(str(Path(__file__).resolve().parent))})\n'
                    f's=importlib.util.spec_from_file_location("a7c2_queue_watch", {json.dumps(str(Path(__file__).resolve()))})\n'
                    'm=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
                    f'm.gdb_main({json.dumps(str(config_path))})\nend\n')
            with script.open('x') as file:
                file.write(code)
            self.log = (self.run / 'queue-watch-gdb.log').open('xb')
            self.process = subprocess.Popen([executable, '-q', '-nx', '-nh', '-batch', '-x', str(script)],
                                            cwd=self.run, stdout=self.log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
            ready = self.run / 'queue-watch-ready.json'
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('Queue debugger exited; inspect queue-watch-gdb.log')
                if ready.exists():
                    if not json.loads(ready.read_text()).get('connected'):
                        raise RuntimeError('Queue debugger not connected')
                    return
                time.sleep(.05)
            raise TimeoutError('Queue debugger setup did not complete')
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.cleanup is not None and self.cleanup.get('safe_to_close'):
            return self.cleanup
        forced = bool(self.cleanup and self.cleanup.get('forced_termination'))
        errors = {}
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    forced = True
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
        except Exception as error:
            errors['debugger_stop_error'] = str(error)
        finally:
            if self.log is not None:
                try:
                    self.log.close()
                except OSError as error:
                    errors['log_close_error'] = str(error)
        stopped = self.process is None or self.process.poll() is not None
        cpu = dict(cpu_running_verified=False, cpu_resume_not_needed=self.process is None)
        if stopped and self.process is not None:
            try:
                cpu.update(resume_owned_debug_cpu(self.fd))
            except Exception as error:
                cpu['cpu_resume_error'] = str(error)
        safe = stopped and (cpu['cpu_running_verified'] or cpu['cpu_resume_not_needed'])
        if safe and self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.cleanup = dict(debugger_stopped=stopped, forced_termination=forced, safe_to_close=safe,
                            guest_resume_requires_export_guard=True, **cpu, **errors)
        if stopped and self.process is not None and getattr(self, 'start_arguments', (None, None, None, None))[3] in ('media', 'media-policy', 'media-init'):
            from media_predicate_watch import observation_error
            self.cleanup['observation_error'] = observation_error(self.run, self.process.poll())
        return self.cleanup

    def check_exited(self):
        if self.cleanup is not None and self.cleanup.get('safe_to_close'):
            return  # Intentional cleanup; caller handles observation status separately.
        if self.process is not None and self.process.poll() is not None:
            cleanup = self.stop()
            if not cleanup['safe_to_close']:
                raise RuntimeError('Debugger ended but CPU resume is unconfirmed; retain owned VM')
            if cleanup.get('observation_error'):
                raise RuntimeError('Media predicate observation failed: '+cleanup['observation_error'])


def owned_batch(inferior, holder):
    """Only at the original publisher call: its vector remains caller-owned."""
    def words(address, count):
        return struct.unpack('<' + 'Q' * count, bytes(inferior.read_memory(address, count * 8)))
    batch = words(holder, 1)[0]
    begin, end, capacity = words(batch, 3)
    if not begin <= end <= capacity or (end - begin) % 8 or not 0 < (end - begin) // 8 <= 16:
        raise ValueError('Unexpected original publication vector bounds')
    requests = []
    for address in words(begin, (end - begin) // 8):
        header = bytes(inferior.read_memory(address, 17))
        requests.append(dict(address=address, id=int.from_bytes(header[:4], 'little'),
                             raw4=int.from_bytes(header[4:8], 'little'), raw8=int.from_bytes(header[8:16], 'little'),
                             raw10=header[16], raw770=bytes(inferior.read_memory(address + 0x770, 1))[0]))
    return dict(batch=batch, begin=begin, end=end, requests=requests)


def resume_debug_cpu(qmp):
    """Resume emulator debug stops, never guest processes stopped by Fsys."""
    state = qmp('query-status').get('return')
    if not isinstance(state, dict):
        raise RuntimeError('Missing QEMU status reply')
    if state.get('running') is not True:
        if state.get('status') not in ('debug', 'paused'):
            raise RuntimeError('Unexpected QEMU state during debug cleanup: ' + str(state))
        qmp('cont')
        if qmp('query-status').get('return', {}).get('running') is not True:
            raise RuntimeError('QEMU CPU resume was not confirmed')
    return dict(cpu_running_verified=True, previous_status=state.get('status'))


def revalidate_gdb_config(config):
    fd, actual = owned_config(config['run'], config['sequence'], config['owner_pid'], config['trace_mode'])
    try:
        for name in actual:
            if name != 'socket' and actual[name] != config.get(name):
                raise ValueError('Queue observation configuration changed: ' + name)
        return fd, actual
    except BaseException:
        os.close(fd)
        raise


def sequence_snapshot(inferior, address, base):
    """Only at ctor-return, current manager argument, owned queue, run/dtor entry."""
    raw = bytes(inferior.read_memory(address, 0x28))
    vptr = struct.unpack_from('<Q', raw)[0]
    if vptr != base + 0x5b3ace0:
        raise ValueError('Not the pinned original power-off-cancel object')
    # The original ctor writes only a byte at +18; +19..1b are padding, not a u32 state.
    return dict(address=address, vptr=vptr, raw14=struct.unpack_from('<I', raw, 0x14)[0],
                raw18=raw[0x18], raw1c_24=list(struct.unpack_from('<3I', raw, 0x1c)))


def queued_sequence(inferior, root, target, base):
    first, last, count = struct.unpack('<3Q', bytes(inferior.read_memory(root, 24)))
    if not 0 < count <= 4096 or first == root or last == root:
        raise ValueError('Unexpected original sequence group queue bounds')
    payload = int.from_bytes(bytes(inferior.read_memory(last + 0x10, 8)), 'little')
    if payload != target:
        raise ValueError('Last group queue payload is not the same original cancel object')
    return dict(root=root, first=first, last=last, count=count, **sequence_snapshot(inferior, target, base))


def sequence_object_identity(inferior, obj, base, manager):
    """Only with a current queue/active-slot borrow under the original group lock."""
    def u64(address):
        return int.from_bytes(bytes(inferior.read_memory(address, 8)), 'little')
    vptr, metadata = struct.unpack('<2Q', bytes(inferior.read_memory(obj, 16)))
    result = dict(object=obj, vptr=vptr)
    if not base + 0x51b7718 <= vptr < base + 0x6000000 or vptr & 7:
        return dict(result, type_unresolved=True)
    rtti = u64(vptr - 8)
    if not base + 0x51b7718 <= rtti < base + 0x6000000 or rtti & 7:
        return dict(result, type_unresolved=True)
    name = u64(rtti + 8)
    if not base + 0x165cfd0 <= name < base + 0x51a6cff:
        return dict(result, type_unresolved=True)
    raw = bytes(inferior.read_memory(name, 160))
    text = raw.split(b'\0', 1)[0]
    if not text or any(value < 32 or value > 126 for value in text):
        return dict(result, type_unresolved=True)
    result.update(type_name=text.decode('ascii'), type_name_truncated=b'\0' not in raw)
    if metadata and not metadata & 7:
        raw = bytes(inferior.read_memory(metadata + 8, 32))
        identifier, token, descriptor, owner = struct.unpack('<I4x3Q', raw)
        result.update(sequence_id=identifier, raw_token=token, raw_descriptor=descriptor,
                      raw_manager=owner, metadata_manager_matches=owner == manager)
    return result


def queued_head_identity(inferior, first, base, manager):
    obj = int.from_bytes(bytes(inferior.read_memory(first + 0x10, 8)), 'little')
    return dict(node=first, queued_head_only=True, **sequence_object_identity(inferior, obj, base, manager))


def group_active_identity(inferior, root, base, manager):
    # Consumer 3209e08 sets ctx+88; dtor/clear3209ebc/ec0 hold the same ctx+28 lock.
    # root=ctx+10, so this slot can be borrowed while enqueuer holds root+18.
    slot = root + 0x78
    obj = int.from_bytes(bytes(inferior.read_memory(slot, 8)), 'little')
    if not obj:
        return dict(active_slot=slot, active_slot_empty=True)
    return dict(active_slot=slot, group_lock_borrow=True, run_PC_not_observed=True,
                **sequence_object_identity(inferior, obj, base, manager))


def sequence_handoff(gdb, config, initial, emit, result, stops, registers):
    """Original calls only: never call a guest function or follow a freed object."""
    base = config['app_base']
    target = initial['requests'][0]['address']
    inferior = gdb.selected_inferior()
    guards = []
    obj = None

    class ObservationFinished(Exception):
        pass

    def guard(offset, kind, condition):
        bp = gdb.Breakpoint('*' + hex(base + offset), type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
        bp.condition = condition
        guards.append((bp, kind))

    def check_lifetime(numbers, regs):
        for bp, kind in guards:
            if bp.number not in numbers:
                continue
            if kind == 'request_released_before_handoff' and regs['x0'] != target:
                raise RuntimeError('Request lifetime condition mismatch')
            if kind in ('same_cancel_run_entry', 'same_cancel_destructor_entry'):
                if regs['x0'] != obj:
                    raise RuntimeError('Sequence lifetime condition mismatch')
                emit(kind, request=target, registers=regs, **sequence_snapshot(inferior, obj, base))
                result['target_run_observed'] = kind == 'same_cancel_run_entry'
                result['target_destroyed_before_run'] = kind == 'same_cancel_destructor_entry'
            else:
                emit(kind, request=target, object=obj, registers=regs)
                result[kind] = True
            raise ObservationFinished()

    def at(offset, match):
        bp = gdb.Breakpoint('*' + hex(base + offset), type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
        try:
            for _ in range(8):
                stops.clear()
                gdb.execute('continue', to_string=True)
                if any(event.get('signal') == 'SIGINT' for event in stops):
                    raise KeyboardInterrupt()
                numbers = {number for event in stops for number in event['breakpoints']}
                regs = registers()
                check_lifetime(numbers, regs)
                if bp.number not in numbers:
                    raise RuntimeError('Unexpected handoff stop: ' + str(stops))
                result['hits'] += 1
                if match(regs):
                    result['last_handoff_point'] = hex(offset)
                    return regs
                emit('unrelated_handoff_call', offset=offset, registers=regs)
            raise RuntimeError('Eight unrelated handoff calls; observation stopped')
        finally:
            bp.delete()

    try:
        # Bind request lifetime before waiting for a potentially skipped dispatch gate.
        guard(0x165ec50, 'request_released_before_handoff', f'$x0 == {hex(target)}')
        guard(0x165d4e0, 'request_released_before_handoff', f'$x0 == {hex(target)}')
        regs = at(0x24ccaa8, lambda r: r['x19'] == target)
        header = bytes(inferior.read_memory(target, 0x18))
        ready = bytes(inferior.read_memory(target + 0x770, 1))[0]
        if int.from_bytes(header[:4], 'little') != 0x100:
            raise ValueError('Original target request ID changed before dispatch')
        emit('same_request_dispatch_gate', request=target, ready_byte=ready, raw_header=header.hex(), registers=regs)
        if not ready:
            result['request_not_ready_at_original_gate'] = True
            return
        regs = at(0x248db58, lambda r: r['x0'] == target)
        emit('same_request_handler', request=target, registers=regs)
        result['request100_handler_observed'] = True
        regs = at(0x3110694, lambda r: r['x1'] == target + 0x10)
        obj = regs['x0']
        emit('cancel_ctor_entry', request=target, object=obj, registers=regs, object_uninitialized=True)
        regs = at(0x32425b8, lambda r: r['x20'] == obj)
        emit('cancel_ctor_completed', request=target, registers=regs, **sequence_snapshot(inferior, obj, base))
        result['cancel_object_constructed'] = True
        for bp, _ in guards:
            bp.delete()
        guards.clear()
        # Install before entering manager, not after potentially missed branches.
        guard(0x33dccb8, 'same_cancel_run_entry', f'$x0 == {hex(obj)}')
        guard(0x33dcc7c, 'same_cancel_destructor_entry', f'$x0 == {hex(obj)}')
        manager = base + 0x910a108
        regs = at(0x3222ad0, lambda r: r['x1'] == obj and r['x2'] == 0x100)
        if regs['x0'] != manager or regs['x30'] != base + 0x24ccadc:
            raise ValueError('Unexpected original sequence manager or return site')
        frame = regs['sp'] - 0x90  # pinned STP pre-index then MOV FP,SP
        guard(0x24ccadc, 'manager_returned_before_group_handoff', f'$sp == {hex(regs["sp"])}')
        emit('same_cancel_manager_entry', request=target, manager=manager, manager_frame=frame, registers=regs,
             **sequence_snapshot(inferior, obj, base))
        # b5c is common to both hash outcomes; b64 is bypassed when the result is NULL.
        regs = at(0x3222b5c, lambda r: r['x19'] == manager and r['x21'] == obj and r['x29'] == frame)
        emit('manager_map_branch', request=target, object=obj, raw_lookup_node=regs['x0'], registers=regs,
             map_value_semantics_unproven=True)
        regs = at(0x3222c18, lambda r: r['x19'] == manager and r['x29'] == frame)
        queued = queued_sequence(inferior, regs['x21'], obj, base)
        emit('same_cancel_group_enqueue', request=target, group=regs['x24'], registers=regs, **queued)
        result['same_object_group_enqueue_observed'] = True
        try:
            emit('sequence_group_queued_head', group=regs['x24'],
                 **queued_head_identity(inferior, queued['first'], base, manager))
        except Exception as error:
            emit('sequence_group_queued_head_unreadable', error=str(error))
        try:
            emit('sequence_group_active_slot', group=regs['x24'],
                 **group_active_identity(inferior, queued['root'], base, manager))
        except Exception as error:
            emit('sequence_group_active_unreadable', error=str(error))
        bp, _ = guards.pop()  # caller return is normal after a verified ownership transfer
        bp.delete()
        for _ in range(config['limit']):
            stops.clear()
            gdb.execute('continue', to_string=True)
            if any(event.get('signal') == 'SIGINT' for event in stops):
                raise KeyboardInterrupt()
            numbers = {number for event in stops for number in event['breakpoints']}
            regs = registers()
            result['hits'] += 1
            check_lifetime(numbers, regs)
            raise RuntimeError('Unexpected original sequence run/destructor stop: ' + str(stops))
        result['capture_limit_reached'] = True
    except ObservationFinished:
        pass
    finally:
        for bp, _ in guards:
            bp.delete()


def gdb_main(config_path):
    import gdb
    initial_config = json.loads(Path(config_path).read_text())
    if initial_config.get('trace_mode') == 'resize':
        from resize_mmio_watch import gdb_main as observe_resize
        observe_resize(initial_config)
        return
    if initial_config.get('trace_mode') == 'media-init':
        from media_initial_write import gdb_main as observe_initial_write
        observe_initial_write(initial_config)
        return
    if initial_config.get('trace_mode') in ('media', 'media-policy'):
        from media_predicate_watch import gdb_main as observe_media
        observe_media(initial_config)
        return
    fd, config = revalidate_gdb_config(json.loads(Path(config_path).read_text()))
    root = Path(config['run'])
    events = (root / 'queue-watch-events.jsonl').open('x')
    pub = watch = None
    result = dict(ok=False, observations_only=True, dispatch_proven=False, hits=0)
    stops = []

    def stopped(event):
        stops.append(dict(breakpoints=[bp.number for bp in (getattr(event, 'breakpoints', None) or ())],
                          signal=getattr(event, 'stop_signal', None)))

    def emit(kind, **data):
        try:
            events.write(json.dumps(dict(kind=kind, **data)) + '\n')
            events.flush()
        except OSError as error:
            result['report_error'] = str(error)

    def registers():
        return {name: int(gdb.parse_and_eval('$' + name)) for name in
                ('pc', 'sp', 'x30', 'x0', 'x1', 'x2', 'x3', 'x4', 'x19', 'x20', 'x21', 'x24', 'x29')}

    try:
        gdb.execute('target remote ' + config['socket'], to_string=True)
        gdb.events.stop.connect(stopped)
        pub = gdb.Breakpoint('*' + hex(config['publish_pc']), type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
        (root / 'queue-watch-ready.json').write_text(json.dumps(dict(connected=True, publication_breakpoint_only=True)))
        for _ in range(8):
            stops.clear()
            gdb.execute('continue', to_string=True)
            if not any(pub.number in event['breakpoints'] for event in stops):
                raise RuntimeError('Stop was not the original publication breakpoint: ' + str(stops))
            regs = registers()
            if regs['pc'] != config['publish_pc']:
                raise RuntimeError('Unexpected stop before original publication')
            inferior = gdb.selected_inferior()
            caller = int.from_bytes(bytes(inferior.read_memory(regs['x29'] + 8, 8)), 'little')
            if caller == config['cancel_caller']:
                break
            emit('unrelated_original_publication', registers=regs, saved_caller=caller)
        else:
            raise RuntimeError('Original cancellation publication not observed in eight hits')
        if regs['x0'] != config['queue']:
            raise ValueError('Unexpected original request queue')
        initial = owned_batch(inferior, regs['x1'])
        if [r['id'] for r in initial['requests']] != [0x100]:
            raise ValueError('Expected one original request100')
        emit('original_caller_owned_publication', registers=regs, saved_caller=caller, **initial)
        pub.delete()
        pub = None
        if config['trace_mode'] == 'handoff':
            sequence_handoff(gdb, config, initial, emit, result, stops, registers)
            return
        watch = gdb.Breakpoint('*((unsigned long long*)' + hex(config['queue'] + 0x10) + ')',
                               type=gdb.BP_WATCHPOINT, wp_class=gdb.WP_WRITE, internal=True)
        if watch.type != gdb.BP_HARDWARE_WATCHPOINT:
            raise RuntimeError('Software watchpoint fallback refused')
        emit('hardware_write_watch_armed', address=config['queue'] + 0x10, limit=config['limit'],
             same_value_writes_may_not_stop=True)
        for _ in range(config['limit']):
            stops.clear()
            gdb.execute('continue', to_string=True)
            if not any(watch.number in event['breakpoints'] for event in stops):
                raise RuntimeError('Stop was not the queue write watchpoint: ' + str(stops))
            regs = registers()
            raw = bytes(inferior.read_memory(config['queue'], 24))
            queue = dict(zip(('next', 'previous', 'count'), struct.unpack('<3Q', raw)))
            emit('queue_counter_stop', registers=regs, queue=queue,
                 stop_phase_unproven=True, request_ownership_after_publication_unproven=True)
            result['hits'] += 1
        result['capture_limit_reached'] = True
    except KeyboardInterrupt:
        emit('cleanup_interrupt')
    except BaseException as error:
        result['error'] = f'{type(error).__name__}: {error}'
    finally:
        try:
            gdb.events.stop.disconnect(stopped)
        except Exception:
            pass
        for bp in (pub, watch):
            if bp is not None:
                try:
                    bp.delete()
                except Exception:
                    pass
        try:
            gdb.execute('detach', to_string=True)
            result['detached'] = True
        except Exception as error:
            result['detach_error'] = str(error)
        events.close()
        os.close(fd)
        (root / 'queue-watch-result.json').write_text(json.dumps(result, indent=2) + '\n')
