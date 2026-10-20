"""Owned pre-init hardware data watchpoint; observation only, never a setter."""
import json
import os
from pathlib import Path
import threading
import time


def guard_shutdown(watch, proc, run):
    """Never let any shutdown path outrun debugger/CPU recovery.

    An unresolved recovery retains the host owner as well as its VM. The owned
    bwrap uses die-with-parent, so returning from this guard is not safe until
    recovery is confirmed (or the VM has already independently exited).
    """
    if watch is None:
        return
    while True:
        try:
            result = watch.stop()
        except Exception as error:
            result = {'safe_to_close': False, 'error': str(error)}
        try:
            (Path(run)/'media-init-shutdown-guard.json').write_text(json.dumps(result, indent=2))
        except OSError:
            # Full host storage must not release a parent whose bwrap owns
            # a VM with unconfirmed debug recovery. Reporting is secondary.
            pass
        if result.get('safe_to_close') or proc.poll() is not None:
            return
        # No quit, terminate, kill or new guest command while recovery is unknown.
        time.sleep(1)


class EarlyWatch:
    def __init__(self, run, owner_pid, proc):
        self.run, self.owner, self.proc = Path(run), owner_pid, proc
        self.watch = None
        self.error = None
        self.cancel = threading.Event()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        try:
            deadline = time.monotonic()+180
            while not self.cancel.is_set() and time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    raise RuntimeError('VM ended before pre-init trace')
                from request_queue_watch import QueueWatch, preinit_gate
                if preinit_gate((self.run/'console.log').read_bytes()) is not None:
                    self.watch = QueueWatch(self.run, 0, self.owner, 'media-init', autostart=False)
                    self.watch.start()
                    return
                self.cancel.wait(.05)
            if not self.cancel.is_set():
                raise TimeoutError('Original pre-init gate not observed')
        except Exception as error:
            self.error = str(error)
            (self.run/'media-init-host-error.json').write_text(json.dumps({'error': self.error}))

    def stop(self):
        self.cancel.set()
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            raise RuntimeError('Early debugger setup not settled; retain VM')
        if self.watch is None:
            return {'safe_to_close': True, 'observation_error': self.error or 'Pre-init debugger never started'}
        result = self.watch.stop()
        if self.error:
            result['observation_error'] = self.error
        return result


def gdb_main(config):
    import gdb
    from request_queue_watch import revalidate_gdb_config
    fd, actual = revalidate_gdb_config(config)
    root, base = Path(actual['run']), actual['app_base']
    result = {'scope': 'original pre-init still LIVE writes', 'capture_verified': False,
              'connected': False, 'error': None, 'cleanup_errors': [], 'writes': [],
              'initial_value': None, 'first_transition_to_1_observed': False}
    point = None
    entry_point = None
    signals = []
    requested_stop = None

    def reg(name):
        return int(gdb.parse_and_eval('$'+name))

    def word():
        return int.from_bytes(bytes(gdb.selected_inferior().read_memory(base+0x7e6e7f0, 4)), 'little')

    def stopped(event):
        value = getattr(event, 'stop_signal', None)
        if value:
            signals.append(value)

    class Observe(gdb.Breakpoint):
        def stop(self):
            nonlocal requested_stop
            try:
                current = word()
                inf = gdb.selected_inferior()
                pc, lr, fp = reg('pc'), reg('x30'), reg('x29')
                frames = []
                for _ in range(6):
                    if not fp or fp & 15 or not 0 < fp < 0x800000000000:
                        break
                    data = bytes(inf.read_memory(fp, 16))
                    prev, ret = int.from_bytes(data[:8], 'little'), int.from_bytes(data[8:], 'little')
                    frames.append({'fp': hex(fp), 'return_absolute': hex(ret), 'return_minus_app_base': hex(ret-base)})
                    if prev <= fp or prev-fp > 0x100000:
                        break
                    fp = prev
                prior = result['writes'][-1]['value'] if result['writes'] else result['initial_value']
                result['writes'].append({'value': current, 'previous_observed_value': prior,
                                         'pc_absolute': hex(pc), 'pc_minus_app_base': hex(pc-base),
                                         'lr_minus_app_base': hex(lr-base), 'stack': frames})
                if current == 1 and prior != 1:
                    result['first_transition_to_1_observed'] = True
                    requested_stop = 'observed_transition_to_1'
                    return True
                if len(result['writes']) >= 16:
                    result['limit_reached'] = True
                    requested_stop = 'write_limit'
                    return True
                return False
            except Exception as error:
                result['error'] = str(error)
                return True

    try:
        gdb.execute('target remote '+actual['socket'], to_string=True)
        result['connected'] = True
        gdb.events.stop.connect(stopped)
        inf = gdb.selected_inferior()
        if int.from_bytes(bytes(inf.read_memory(actual['observer_gate_address'], 4)), 'little') != 1:
            raise ValueError('Original pre-init observer gate expired; do not arm a late watchpoint')
        result['before_init_gate_verified'] = True
        # Unexecuted original code may not yet have a guest PTE. Stop at the
        # actual original init entry, which also binds the guest address space,
        # rather than reading a cold raw-writer page while stopped in Linux.
        entry_point = gdb.Breakpoint('*'+hex(base+0x1796918),
                                     type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
        if entry_point.type != gdb.BP_HARDWARE_BREAKPOINT:
            raise RuntimeError('Hardware-only original init entry breakpoint required')
        (root/'queue-watch-ready.json').write_text(json.dumps({'connected': True, 'await_original_init_entry': True}))
        gdb.execute('continue', to_string=True)
        if reg('pc') != base+0x1796918:
            raise RuntimeError('Did not stop at original init entry; no data watch armed')
        if bytes(inf.read_memory(base+0x1796918, 12)) != bytes.fromhex('fd7bbaa9a31e02d0a2fb00d0'):
            raise ValueError('Original init entry instruction mismatch')
        result['original_init_entry_verified'] = True
        entry_point.delete()
        entry_point = None
        result['initial_value'] = word()
        result['initial_value_already_one'] = result['initial_value'] == 1
        point = Observe('*((unsigned int*)'+hex(base+0x7e6e7f0)+')',
                        type=gdb.BP_WATCHPOINT, wp_class=gdb.WP_WRITE, internal=True)
        if point.type != gdb.BP_HARDWARE_WATCHPOINT:
            raise RuntimeError('Hardware-only pre-init watchpoint required')
        gdb.execute('continue', to_string=True)
        if signals and signals[-1] == 'SIGINT':
            result['interrupted_for_cleanup'] = True
        elif requested_stop is None and result['error'] is None:
            result['error'] = 'Unexpected debugger stop outside requested watchpoint completion'
        result['watchpoint_stop_reason'] = requested_stop
    except KeyboardInterrupt:
        result['interrupted_for_cleanup'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        if result['connected']:
            try:
                gdb.events.stop.disconnect(stopped)
            except Exception as error:
                result['cleanup_errors'].append(str(error))
        if point is not None:
            try:
                point.delete()
            except Exception as error:
                result['cleanup_errors'].append(str(error))
        if entry_point is not None:
            try:
                entry_point.delete()
            except Exception as error:
                result['cleanup_errors'].append(str(error))
        if result['connected']:
            try:
                gdb.execute('detach', to_string=True)
            except Exception as error:
                result['cleanup_errors'].append(str(error))
        (root/'media-predicate-result.json').write_text(json.dumps(result, indent=2))
        os.close(fd)
