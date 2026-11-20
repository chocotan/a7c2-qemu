"""Observation candidate for an ALREADY owned, stopped GDB session; no attach/run API."""
PROFILE = 'virtual-model17c-runtime-ro-v1'
ASSET_SHA256 = '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
STATIC = {'current17c_u32': (0x7e5d570, 4), 'descriptor0_u32': (0x7e5d578, 4),
          'descriptor8_u64': (0x7e5d580, 8), 'descriptor10_u32': (0x7e5d588, 4),
          'snapshot_u32': (0x835f8d0, 4), 'unresolved_boot_setting_u32': (0x7e6a7c8, 4)}


def value(read, address, size):
    try:
        if address <= 0 or address + size > 0x800000000000:
            raise ValueError('unadmitted userspace address')
        raw = bytes(read(address, size))
        if len(raw) != size:
            raise ValueError('short memory read')
        return dict(address=address, size=size, value=int.from_bytes(raw, 'little'), bytes=raw.hex())
    except Exception as error:
        return dict(address=address, size=size, value=None, error=str(error))


class Observer:
    def __init__(self, base, pins, read, emit, task, mm, pgd, symbols, abi, cpu):
        if (type(base) is not int or base <= 0 or base & 0xfff or
                any(type(value) is not int or value <= 0 for value in (task, mm, pgd)) or
                type(symbols) is not dict or set(symbols) != {'__entry_task', '__per_cpu_offset'} or
                abi != {'task_mm': 0x2d8, 'mm_pgd': 0x40} or
                type(cpu) is not int or not 0 <= cpu < 64 or
                base + 0x835f8d4 >= 0x800000000000 or pins['asset_sha256'] != ASSET_SHA256):
            raise ValueError('unverified load bias/asset/task address-space identity')
        self.base, self.pins, self.read, self.emit = base, pins['points'], read, emit
        self.task, self.mm, self.pgd = task, mm, pgd
        self.symbols, self.abi, self.cpu = symbols, abi, cpu
        self._setter_hex = pins['setter_full_hex']
        self.counts, self.pending, self.sequence = {}, {}, 0

    def current(self):
        """Actual per-cpu __entry_task; this gdbstub cannot read SP_EL0 by name."""
        base = int.from_bytes(bytes(self.read(self.symbols['__per_cpu_offset'] + 8 * self.cpu, 8)), 'little')
        task = int.from_bytes(bytes(self.read((self.symbols['__entry_task'] + base) & (2**64 - 1), 8)), 'little')
        if task <= 0:
            raise ValueError('actual per-cpu __entry_task is empty')
        return task

    def bound_task(self, task):
        """Admit any thread of the bound AP process: the mapping thread and
        the gate/executing threads are distinct task_structs sharing mm.
        A foreign/unreadable task is simply not bound."""
        if not task:
            return False
        try:
            mm = int.from_bytes(bytes(self.read(task + self.abi['task_mm'], 8)), 'little')
            if mm != self.mm:
                return False
            return int.from_bytes(bytes(self.read(mm + self.abi['mm_pgd'], 8)), 'little') == self.pgd
        except Exception:
            return False

    def check(self):
        for name, pin in self.pins.items():
            expected = bytes.fromhex(pin['original_hex'])
            if len(expected) != 16 or bytes(self.read(self.base + pin['va'], 16)) != expected:
                raise ValueError('original instruction pin mismatch: ' + name)
        if bytes(self.read(self.base + 0x267b698, 0x78)) != bytes.fromhex(self._setter_hex):
            raise ValueError('full setter body mismatch')

    def observe(self, site, registers):
        regs = dict(registers)
        task = regs.get('kernel_task')
        if site in ('inhibit_setter', 'capture_seq_run', 'capture_seq_slot', 'capture_model_ctor'):
            # these run on sequence/EE threads; the bound-task filter would eat them
            if site == 'inhibit_setter':
                island = regs['x1'] & 0xffffffff
                if island not in (0x8b5, 0x996, 0x995, 0x997):
                    return
            if self.counts.get(site, 0) >= 16:
                return
            self.sequence += 1
            self.counts[site] = self.counts.get(site, 0) + 1
            self.emit(dict(kind='model17c_runtime_observation', site=site, sequence=self.sequence,
                           registers=regs, kernel_task=task, base=self.base, static_reads={},
                           observation_only=True, minimal=True,
                           island=regs['x1'] & 0xffffffff,
                           value=regs['x2'] & 0xffffffff, caller_x30=regs['x30'],
                           model_this=regs['x19'], slot_w0=regs['x0'] & 0xff))
            return
        if task is None or not self.bound_task(task):
            # Foreign task/address space: same skip the old TTBR0 filter performed.
            return
        if regs['pc'] != self.base + self.pins[site]['va']:
            raise ValueError('PC differs from observation site')
        if self.counts.get(site, 0) >= 16:
            return
        if site in ('raw_setter_store', 'raw_setter_after', 'inhibit_setter', 'capture_seq_run', 'capture_seq_slot'):
            # shortcut: static reads inside the hit handler crashed embedded GDB (c163); emit registers only
            island = regs['x1'] & 0xffffffff
            if site in ('capture_seq_run', 'capture_seq_slot') or island in (0x8b5, 0x996, 0x995, 0x997):
                self.sequence += 1
                self.counts[site] = self.counts.get(site, 0) + 1
                self.emit(dict(kind='model17c_runtime_observation', site=site, sequence=self.sequence,
                               registers=regs, kernel_task=task, base=self.base, static_reads={},
                               observation_only=True, minimal=True,
                               stored_w0=regs['x0'] & 0xffffffff, island=island,
                               value=regs['x2'] & 0xffffffff, caller_x30=regs['x30'],
                               model_this=regs['x19'], slot_w0=regs['x0'] & 0xff))
            return
        key = (task, regs['tpidr'], regs['sp'])
        txn = None
        if site in ('snapshot_dispatch', 'restore_dispatch') and regs['x0'] & 0xffffffff != 0x17c:
            return
        if site == 'setter_entry':
            pointer = regs['x0']
            txn = {name: value(self.read, pointer + offset, size) for name, offset, size in
                   [('current_ptr', 0, 8), ('descriptor_ptr', 8, 8), ('model_id', 0x10, 4), ('scope', 0x18, 8)]}
            if txn['model_id']['value'] != 0x17c or txn['current_ptr']['value'] != self.base + 0x7e5d570:
                n = self.counts.get('setter_filtered', 0)
                if n < 16:
                    self.counts['setter_filtered'] = n + 1
                    self.emit(dict(kind='model17c_setter_filtered', pc=regs['pc'], registers=regs,
                                   transaction=txn, identity_confirmed=False))
                return
            if key in self.pending or len(self.pending) >= 16:
                raise ValueError('ambiguous or over-budget setter frame')
            self.pending[key] = dict(transaction=pointer, input_w1=regs['x1'] & 0xffffffff,
                                     caller=regs['x30'], entry_sequence=self.sequence + 1)
        pending = self.pending.get(key)
        if site in ('setter_exit', 'setter_wrapper_return'):
            if pending is None:
                return
            if site == 'setter_wrapper_return' and pending['caller'] != regs['pc']:
                raise ValueError('setter return caller mismatch')
            if site == 'setter_exit' and pending['caller'] != regs['x30']:
                raise ValueError('setter exit LR mismatch')
        self.sequence += 1
        self.counts[site] = self.counts.get(site, 0) + 1
        event = dict(kind='model17c_runtime_observation', site=site, sequence=self.sequence,
                     registers=regs, kernel_task=task, base=self.base, static_reads={name: value(self.read, self.base + off, size)
                        for name, (off, size) in STATIC.items()}, observation_only=True,
                     atomic_snapshot=False, original_return_observed=site == 'setter_wrapper_return')
        if site == 'date_gate':
            event['date_time_set_status'] = value(self.read, regs['x29'] + 0x8c, 4)
            event['clock_force_settled_w28'] = regs['x28'] & 0xffffffff
        if site == 'helper_return':
            event['original_helper_result_u8'] = regs['x0'] & 0xff
        if site in ('setting_gate', 'current_gate'):
            event['original_read_w0'] = regs['x0'] & 0xffffffff
        if site == 'clear_call':
            event.update(original_target_va=0x267b7a8, input_w1=regs['x1'] & 0xffffffff)
        if site == 'setter_entry':
            event.update(transaction=txn, input_w1=regs['x1'] & 0xffffffff)
        if site in ('setter_exit', 'setter_wrapper_return'):
            event.update(pair=pending.copy(), original_x0=regs['x0'],
                         return_pointer_matches_transaction=regs['x0'] == pending['transaction'],
                         ret_instruction_executed=site == 'setter_wrapper_return')
            if site == 'setter_wrapper_return' or pending['caller'] != self.base + self.pins['setter_wrapper_return']['va']:
                del self.pending[key]
        if site == 'clear_return':
            event.update(original_x0_raw=regs['x0'], wrapper_return_type='void; no success interpretation')
        self.emit(event)


def install(gdb, base, pins, emit, *, profile=None, asset_sha256=None, task=None, mm=None, pgd=None,
            symbols=None, abi=None, cpu=None):
    """Caller supplies verified maps/ELF/task address-space identity inside the existing owner window.

    No target connection, continue, detach, guest function call, or guest write occurs here.
    The owner must stop and remove this observer before handing the socket to the broker.
    """
    if profile is None or profile == '':
        return None
    if profile != PROFILE or asset_sha256 != ASSET_SHA256:
        raise ValueError('profile/asset not admitted')
    if gdb.parameter('may-write-memory') or gdb.parameter('may-write-registers'):
        raise ValueError('read-only GDB policy required before install')
    inferior = gdb.selected_inferior()
    observer = Observer(base, pins, inferior.read_memory, emit, task, mm, pgd, symbols, abi, cpu)
    observer.check()  # Fail before creating any breakpoint on differing original bytes.
    breakpoints = []

    class Probe(gdb.Breakpoint):
        def __init__(self, site):
            self.site = site
            super().__init__('*' + hex(base + pins['points'][site]['va']),
                             type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)

        def stop(self):
            try:
                frame = gdb.selected_frame()
                regs = {}
                for name in [f'x{i}' for i in range(31)] + ['sp', 'pc', 'cpsr', 'tpidr']:
                    try:
                        regs[name] = int(frame.read_register(name))
                    except BaseException as error:
                        raise ValueError('register ' + name + ': ' + str(error)) from error
                regs['kernel_task'] = observer.current()
                observer.observe(self.site, regs)
                return False
            except Exception as error:
                emit(dict(kind='model17c_observer_error', site=self.site, error=str(error),
                          must_remain_stopped=True))
                return True

    try:
        for site in pins['points']:
            bp = Probe(site)
            breakpoints.append(bp)
            if bp.type != gdb.BP_HARDWARE_BREAKPOINT:
                raise ValueError('software breakpoint fallback refused')
    except BaseException:
        for bp in breakpoints:
            bp.delete()
        raise
    # Owner forces hardware insertion and publishes readiness using its existing policy.
    return observer, breakpoints
