#!/usr/bin/env python3
"""Fixed upstream-host retained execution, inside retained-disk-state.transaction.

Caller starts ONE source with tx.pass_fds, immediately registers its Popen in
 tx.children, owns its negotiated FDQMP, and supplies real console sync evidence.
Use DS['transaction'] (or another load of the unchanged official disk API).
CameraExecution(tx, launch, owner, qmp, source_run=..., generation=...)
 .capture(evidence) saves RAM and normally quits/waits for the source.
 .restore(target_run=...) returns (Popen, FDQMP, receipt) while PAUSED.
 .continue_target() rechecks the binding then continues; caller observes NEW
 guest evidence using target.stdin and output/target/console.log.
Always invoke .close() in finally, inside the transaction context.

Evidence has exactly schema='a7c2-retained-guest-sync-v1',
kind='guest-console-sync', run=source_run, nonce=tx.guest_sync_nonce,
owner_pid=owner.pid, peer_pid=execution.identity['peer']['pid'], path=<0600 file>,
command="/bin/busybox sync && echo 'A7C2_RETAINED_GUEST_SYNC nonce=<nonce> sync_rc=0'".
The file must contain one whole exact marker line from that guest command;
execution and console ownership remain the caller's responsibility.

No source startup, second lease, prepare, UI, synthetic admission, cold fallback,
old AP pass or external_state='none' override is provided. The device audit is a
fixed source-v4 QOM type/count and pinned-source contract, never a caller boolean;
QMP migration success alone never proves complete hardware/firmware behavior.
The independent no-OS integration fixture uses the low-level stream helpers,
not CameraExecution.capture or a production synthetic flag. See the tests for
its separate schema and actual CPU canary. Original AP restore remains false.
"""
from collections import Counter
from contextlib import ExitStack, contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import secrets
import shutil
import socket
import stat
import struct
import subprocess
import threading
import time

HERE = Path(__file__).resolve().parent
DS = runpy.run_path(str(HERE/'retained-disk-state.py'))
R = DS['RETAINED']
LAUNCH = runpy.run_path(str(HERE/'retained-camera-launch.py'))
COLD = LAUNCH['COLD']
PROFILE = LAUNCH['UPSTREAM_PROFILE']
QEMU_SHA = LAUNCH['UPSTREAM_BINARY_SHA']
EXTERNAL = 'same-lease-persistent-flash'
AUDIT_KIND = 'same-lease-persistent-flash-upstream-host-v1'
ACTIVE = ('setup', 'active', 'device', 'wait-unplug')
# Exact source-v4 /machine subtree, independently read from its actual QOM evidence.
SOURCE_TYPES = {'PCIE': 1, 'System': 1, 'arm-gicv2m': 1, 'arm_gic': 1,
    'base-xhci': 1, 'cfi.pflash01': 2, 'clock': 1, 'container': 3,
    'cortex-a35-arm-cpu': 4, 'fw_cfg_mem': 1, 'gpex-pcihost': 1, 'gpex-root': 1,
    'gpio-key': 1, 'irq': 417, 'loader': 5, 'memory-region': 89, 'pl011': 1,
    'pl031': 1, 'pl061': 1, 'platform-bus-device': 1, 'qemu-register-array': 1,
    'ramfb': 1, 'sony-cxd-bus-stub': 1, 'sony-hwtimer': 4,
    'sony-persistent-flash': 1, 'sony-spacc-stub': 1, 'sysbus-xhci': 1,
    'usb-bus': 1, 'usb_dwc3': 1, 'virtio-mmio-bus': 32, 'virtio-mmio': 32}
SOURCE_COUNTS = {'child<'+key+'>': value for key, value in SOURCE_TYPES.items()}



def same(label, expected, actual):
    LAUNCH['equal'](label, expected, actual)


def _status(qmp, expected):
    actual = qmp('query-status')
    if actual.get('running') is not False or actual.get('status') != expected:
        raise ValueError('Actual QMP target/source must remain '+expected)
    return actual


def _live_tx(tx):
    if (type(tx).__name__ != 'DiskTransaction' or
            getattr(type(tx).__init__, '__code__', None) != DS['DiskTransaction'].__init__.__code__):
        raise ValueError('A real live DiskTransaction is required, never a boolean admission')
    tx._check_anchor()
    if tx._failed:
        raise ValueError('Failed disk transaction cannot execute')


def _disk_now(tx, binding):
    """Popen boundary: remeasure current bytes, not cold-manifest partitions."""
    _live_tx(tx)
    same('same captured transaction binding', tx._binding, binding)
    os.fdatasync(tx.fd)
    before = tx._check_anchor()
    with ExitStack() as stack:
        files = {}
        for key, name in (('geometry', 'geometry.json'), ('instance', 'instance.json'),
                          ('wire', 'persistent-geometry.bin')):
            files[key] = tx._read_file(stack, tx._leased['path']/name)
        for key in ('geometry', 'instance'):
            same('current '+key+' metadata', binding['metadata'][key], files[key][1])
        same('current wire', binding['wire']['file'], files['wire'][1])
        same('current wire bytes', binding['canonical_wire']['hex'], files['wire'][0].hex())
        same('current whole disk', binding['whole_disk_sha256'], DS['DISK']['hashed'](tx.fd))
        same('current three partitions', binding['partition_bindings'],
             DS['BOOT']['partition_bindings'](dict(tx._leased, geometry=binding['geometry'])))
        hashes = {key: DS['DISK']['hashed'](item[2]) for key, item in files.items()}
        for key, (raw, record, fd) in files.items():
            same('stable '+key, record, dict(DS['_record'](fd), sha256=hashes[key]))
            name = {'geometry': 'geometry.json', 'instance': 'instance.json', 'wire': 'persistent-geometry.bin'}[key]
            tx._check_path(tx._leased['path']/name, {k: v for k, v in record.items() if k != 'sha256'})
        same('stable disk across Popen measurement', binding['disk'], tx._check_anchor())
        same('unchanged disk stamp', before, tx._check_anchor())


def transfer(qmp, receipt, stream, *, outgoing, timeout=60):
    """Existing FDQMP/getfd/socketpair/_transfer/_wait transport, no exec URI."""
    if type(timeout) not in (int, float) or not 0 < timeout <= 3600:
        raise ValueError('Invalid transfer timeout')
    if not callable(getattr(qmp, 'getfd', None)):
        raise ValueError('Owned QMP must support SCM_RIGHTS getfd')
    local, remote = socket.socketpair()
    errors, worker = [], None
    name = 'retained-'+secrets.token_hex(12)
    try:
        qmp.getfd(name, remote.fileno())
        remote.close()
        worker = threading.Thread(target=R['_transfer'], args=(local, stream, outgoing, errors), daemon=True)
        deadline = time.monotonic()+timeout
        worker.start()
        R['_call'](qmp, receipt, 'migrate' if outgoing else 'migrate-incoming',
                   dict(uri='fd:'+name, **({} if outgoing else {'exit-on-error': False})))
        result = R['_wait'](qmp, receipt, deadline)
        worker.join(max(0, deadline-time.monotonic()))
        if worker.is_alive() or errors:
            raise RuntimeError('Incomplete actual RAM stream: '+repr(errors))
        receipt['migration'] = result
        receipt['migration_outgoing' if outgoing else 'migration_incoming'] = copy.deepcopy(result)
        return R['_hash'](stream)
    except BaseException:
        if outgoing:
            try:
                current = R['_call'](qmp, receipt, 'query-migrate')
                if current.get('status') in ACTIVE:
                    R['_call'](qmp, receipt, 'migrate_cancel')
            except Exception as error:
                receipt['cancel_error'] = str(error)
        raise
    finally:
        try:
            local.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        if worker is not None:
            worker.join(2)
            if worker.is_alive():
                # Do not close its file out from under a live writer.
                receipt['stream_worker_unjoined'] = True
                worker.join()
        local.close()
        remote.close()


def save_paused(tx, qmp, *, run, generation, evidence_path, receipt, timeout=60):
    """Disk + RAM primitive; callers must independently admit their guest schema."""
    _live_tx(tx)
    binding = tx.snapshot_disk(qmp, host_run=run, migration_generation=generation,
                               guest_sync_evidence=evidence_path)
    tx.verify(binding, qmp, phase='pre-migration', host_run=run, migration_generation=generation)
    fd = os.open('snapshot.partial', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=tx._outfd)
    with os.fdopen(fd, 'r+b') as stream:
        identity = transfer(qmp, receipt, stream, outgoing=True, timeout=timeout)
        receipt['snapshot_file_record'] = DS['_record'](stream.fileno())
    tx.verify(binding, qmp, phase='post-migration', host_run=run, migration_generation=generation)
    return binding, identity


@contextmanager
def snapshot_stream(tx, receipt):
    """Keep the exact completed 0600 stream inode, not a same-bytes replacement."""
    fd = DS['DISK']['SECURE_OPEN'](tx._output/'snapshot.partial')
    with os.fdopen(fd, 'rb') as stream:
        same('RAM stream file identity', receipt['snapshot_file_record'], DS['_record'](fd))
        yield stream
        same('RAM stream file stability', receipt['snapshot_file_record'], DS['_record'](fd))
        tx._check_path(tx._output/'snapshot.partial', receipt['snapshot_file_record'])


def load_paused(tx, qmp, binding, identity, *, run, generation, receipt, timeout=60):
    """Load only between the real inmigrate and paused disk verification phases."""
    _live_tx(tx)
    tx.verify(binding, qmp, phase='pre-restore', host_run=run, migration_generation=generation)
    with snapshot_stream(tx, receipt) as stream:
        same('stream before actual load', identity, R['_hash'](stream))
        same('stream after actual load', identity,
             transfer(qmp, receipt, stream, outgoing=False, timeout=timeout))
    tx.verify(binding, qmp, phase='post-restore', host_run=run, migration_generation=generation)
    _status(qmp, 'paused')


def _inventory(qmp):
    result, pending = [], ['/machine']
    while pending:
        path = pending.pop()
        for row in qmp('qom-list', dict(path=path)):
            if row['type'].startswith('child<'):
                full = path.rstrip('/')+'/'+row['name']
                result.append(dict(path=full, type=row['type']))
                pending.append(full)
        if len(result) > 20000:
            raise ValueError('QOM inventory budget exceeded')
    return sorted(result, key=lambda row: row['path'])


def _mtree_digest(tree):
    # HMP may enumerate shared roots/alias headers in different display order.
    sections, headers, body = [], [], []
    for line in tree.splitlines()+['']:
        if not line.strip():
            if headers or body:
                sections.append((tuple(sorted(headers)), tuple(body)))
                headers, body = [], []
        elif line[0].isspace():
            body.append(line)
        elif line.startswith(('address-space:', 'memory-region:')) and not body:
            headers.append(line)
        else:
            raise ValueError('Unknown HMP memory-tree structure')
    return R['_digest'](sorted(sections))


def topology(qmp):
    """Host controller is allowed only with no attached USB or other host device."""
    rows = _inventory(qmp)
    types = [row['type'] for row in rows]
    if types.count('child<usb_dwc3>') != 1:
        raise ValueError('Exactly one upstream DWC3 is required')
    forbidden = ('sony-dwc3', 'sony-usb', 'usb-host', 'usb-redir', 'vfio', 'vhost',
                 '9p', 'ivshmem', 'virtio-net', 'sony-ui-input')
    if any(any(word in row['type'].lower() for word in forbidden) for row in rows):
        raise ValueError('Sony bridge/host device/input peer is outside this bounded audit')
    if qmp('human-monitor-command', {'command-line': 'info usb'}).strip():
        raise ValueError('Actual USB devices are attached')
    tree = qmp('human-monitor-command', {'command-line': 'info mtree'})
    if 'sony-usb-' in tree.lower():
        raise ValueError('Sony USB provider instantiated')
    if qmp('query-block') or qmp('query-block-jobs'):
        raise ValueError('External QEMU block state is outside the same-lease flash contract')
    flashes = [r['path'] for r in rows if r['type'] == 'child<sony-persistent-flash>']
    if len(flashes) != 1 or qmp('qom-get', dict(path=flashes[0], property='retained-state')) is not True:
        raise ValueError('Actual persistent flash retained-state must be true')
    if any(c.get('state') and c.get('capability') != 'events' for c in qmp('query-migrate-capabilities')):
        raise ValueError('Only complete single-channel migration is admitted')
    return dict(objects=rows, inventory_sha256=R['_digest'](rows),
                upstream_dwc3_present=True, sony_bridge_absent=True, attached_usb_devices=[],
                input_peer='not-instantiated', mtree_sha256=_mtree_digest(tree))


def _proc_bytes(pid, name):
    return Path('/proc')/str(pid)/name


def _proc_identity(pid):
    root = Path('/proc')/str(pid)
    text = (root/'stat').read_text()
    fields = text[text.rfind(')')+2:].split()
    return dict(pid=pid, parent_pid=int(fields[1]), start_ticks=int(fields[19]),
                uid=root.stat().st_uid)


def _argv(pid):
    return [s.decode() for s in _proc_bytes(pid, 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')]


def _env(pid):
    return dict(s.decode().split('=', 1) for s in _proc_bytes(pid, 'environ').read_bytes().split(b'\0') if s)


def envelope(argv):
    """Parse only the existing launcher bwrap envelope; no arbitrary shell runner."""
    if not argv or Path(argv[0]).name != 'bwrap':
        raise ValueError('Source owner must have execed the existing bwrap launcher')
    widths = {'--unshare-all': 0, '--die-with-parent': 0, '--new-session': 0, '--clearenv': 0,
              '--bind': 2, '--ro-bind': 2, '--symlink': 2, '--setenv': 2,
              '--proc': 1, '--dev': 1, '--tmpfs': 1, '--chdir': 1, '--preserve-fds': 1}
    options, index = [], 1
    while index < len(argv) and argv[index].startswith('--'):
        option = argv[index]
        if option not in widths or index+widths[option] >= len(argv):
            raise ValueError('Unreviewed bwrap option '+option)
        end = index+widths[option]+1
        options.append(argv[index:end])
        index = end
    for flag in ('--unshare-all', '--die-with-parent', '--clearenv'):
        if options.count([flag]) != 1:
            raise ValueError('Required sandbox flag missing or duplicated: '+flag)
    if index == len(argv):
        raise ValueError('Missing direct QEMU argv')
    return options, argv[index:]


def _option(argv, name):
    if argv.count(name) != 1:
        raise ValueError('Exactly one QEMU '+name+' required')
    return argv[argv.index(name)+1]


def _validate_command(options, command):
    value_options = {'-accel', '-machine', '-cpu', '-smp', '-m', '-display', '-device',
                     '-monitor', '-serial', '-nic', '-qmp', '-kernel', '-append', '-d',
                     '-D', '-name', '-icount', '-sandbox'}
    flag_options = {'-nodefaults', '-no-reboot'}
    index = 1
    while index < len(command):
        flag = command[index]
        if flag in value_options and index+1 < len(command):
            index += 2
        elif flag in flag_options:
            index += 1
        else:
            raise ValueError('Unreviewed source command/host passthrough: '+flag)
    for flag, expected in (('-nic', 'none'), ('-monitor', 'none'), ('-display', 'none'), ('-serial', 'stdio')):
        same('source '+flag, expected, _option(command, flag))
    for index, value in enumerate(command):
        if value == '-device':
            device = command[index+1]
            if not (device.startswith('loader,') or device == 'ramfb,id=a7c2-screen'):
                raise ValueError('Unreviewed explicit device '+device)
    writable = [r for r in options if r[0] == '--bind']
    if sorted(r[2] for r in writable) != ['/instance', '/out']:
        raise ValueError('Only the leased /instance and private /out may be writable binds')
    if any(r[0] == '--ro-bind' and (r[1].startswith('/dev/') or r[2].startswith('/dev/')) for r in options):
        raise ValueError('Host device passthrough forbidden')
    for flag in ('-machine', '-cpu', '-m', '-accel'):
        _option(command, flag)


def _assets(launch):
    same('fixed retained source profile', PROFILE, launch.get('profile'))
    same('fixed retained QEMU', QEMU_SHA, launch.get('qemu_sha256'))
    same('source is prepared cold diagnostic', False, launch.get('incoming'))
    same('source launcher schema', LAUNCH['SCHEMA'], launch.get('schema'))
    same('source QEMU bytes', QEMU_SHA, COLD['digest'](launch['qemu_binary']))
    same('source script bytes', launch['script_sha256'], COLD['digest'](launch['script']))
    COLD['recheck'](launch['template_inputs']+launch['launch_inputs'])
    same('source DTB bytes', launch['dtb_sha256'], COLD['digest'](launch['dtb']))


def source_audit(launch, actual):
    """Explicit source-v4 allowlist; no global production-ready/full-audit boolean."""
    same('exact original source-v4 QOM type/count topology', SOURCE_COUNTS,
         dict(Counter(row['type'] for row in actual['objects'])))
    same('fixed reviewed source tree', LAUNCH['UPSTREAM_SOURCE_SHA'],
         launch['combo_binding']['source_tree_sha256'])
    same('fixed retained source class', 'diagnostic-derived-retained-camera', launch['source_class'])
    return dict(schema='a7c2-retained-camera-audit-v1', kind=AUDIT_KIND,
                external_state=EXTERNAL, profile=PROFILE, qemu_sha256=QEMU_SHA,
                source_tree_sha256=LAUNCH['UPSTREAM_SOURCE_SHA'],
                inventory_sha256=actual['inventory_sha256'], type_counts=SOURCE_COUNTS,
                source_class='diagnostic-derived-retained-camera',
                resource_contract='DWC3 parent regs owns register-array; no attached USB; '
                    'ramfb cfg VMState/postload; generic loaders no reset; no input/media/MMC providers',
                original_ap_restore_verified=False)


def audit_contract(review, actual, launch):
    same('fixed source-class audit', source_audit(launch, actual), review)



def _owned_identity(tx, launch, owner, qmp, *, options=None, command=None):
    _live_tx(tx)
    if owner not in tx.children or owner.poll() is not None:
        raise ValueError('Live source/target owner must be registered in this transaction')
    pid, uid, gid = struct.unpack('3i', qmp.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.getuid():
        raise ValueError('QMP peer UID differs')
    peer, parent = _proc_identity(pid), _proc_identity(owner.pid)
    cursor = pid
    for _ in range(12):
        if cursor == owner.pid:
            break
        cursor = _proc_identity(cursor)['parent_pid']
    else:
        raise ValueError('QMP peer is not descended from registered owner')
    if peer['uid'] != os.getuid() or parent['uid'] != os.getuid():
        raise ValueError('Owned process UID differs')
    with open('/proc/'+str(pid)+'/exe', 'rb') as binary:
        same('actual running QEMU executable', QEMU_SHA, hashlib.file_digest(binary, 'sha256').hexdigest())
    actual_options, actual_command = envelope(_argv(owner.pid))
    same('actual peer argv', actual_command, _argv(pid))
    if options is not None:
        same('target/source bwrap envelope', options, actual_options)
        same('target/source argv', command, actual_command)
    environment = _env(pid)
    declared = {r[1]: r[2] for r in actual_options if r[0] == '--setenv'}
    if len(declared) != sum(r[0] == '--setenv' for r in actual_options):
        raise ValueError('Duplicate sandbox environment key')
    # bubblewrap adds PWD after --clearenv, even without an explicit --chdir.
    same('sandbox generated working directory', '/', environment.get('PWD'))
    declared['PWD'] = '/'
    same('actual clearenv sandbox environment', declared, environment)
    for key, expected in dict(LAUNCH['UPSTREAM_USB'], QEMU_A7PF_PROFILE=PROFILE,
                              QEMU_A7PF_RETAINED_STATE='1', QEMU_A7PF_FD=str(tx.fd),
                              QEMU_A7PF_DEV=str(os.fstat(tx.fd).st_dev),
                              QEMU_A7PF_INO=str(os.fstat(tx.fd).st_ino)).items():
        same('actual environment '+key, expected, environment.get(key))
    for key in environment:
        if key.startswith(LAUNCH['USB_PREFIXES']) and key != 'QEMU_SONY_USB_DWC3':
            raise ValueError('Unreviewed USB environment '+key)
        if key in ('LD_PRELOAD', 'LD_AUDIT'):
            raise ValueError('Runtime code injection forbidden')
    same('same source disk bind', str(tx._leased['path']),
         next(r[1] for r in actual_options if r[0] == '--bind' and r[2] == '/instance'))
    disk = os.stat('/proc/'+str(pid)+'/fd/'+str(tx.fd))
    same('actual inherited disk FD inode', (os.fstat(tx.fd).st_dev, os.fstat(tx.fd).st_ino),
         (disk.st_dev, disk.st_ino))
    version = qmp('query-version')
    same('actual pinned QEMU version', dict(major=11, minor=1, micro=2), version['qemu'])
    return dict(owner=parent, peer=peer, qmp_name=qmp('query-name'), version=version,
                environment=environment, options=actual_options, command=actual_command,
                memory=qmp('query-memory-size-summary'))


def _quit(owner, qmp):
    result = dict(pid=owner.pid, signals_sent=[])
    if owner.poll() is None:
        result['quit_response'] = qmp('quit')
    result['returncode'] = owner.wait(timeout=30)
    if result['returncode'] != 0:
        raise RuntimeError('Owned QEMU did not exit normally: '+repr(result))
    return result


def _connect(path, owner, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_UNIX)
        sock.settimeout(timeout)
        try:
            sock.connect(str(path))
            stream = sock.makefile('rwb')
            if 'QMP' not in json.loads(stream.readline()):
                raise ValueError('Missing QMP greeting')
            qmp = R['FDQMP'](sock, stream)
            qmp('qmp_capabilities')
            return qmp
        except (FileNotFoundError, ConnectionRefusedError):
            sock.close()
            if owner.poll() is not None:
                raise RuntimeError('Incoming owner exited before QMP admission')
            time.sleep(.02)
        except BaseException:
            sock.close()
            raise
    raise TimeoutError('Incoming owned QMP did not appear')


class CameraExecution:
    """One source capture and one target, both owned by the caller's live lease."""
    def __init__(self, tx, launch, owner, qmp, *, source_run, generation, device_audit=None):
        self.tx, self.launch, self.source, self.source_qmp = tx, copy.deepcopy(launch), owner, qmp
        self.target = self.target_qmp = None
        self.captured = self.restored = self.continued = self.failed = False
        self.receipt = dict(schema='a7c2-retained-camera-execution-v1', external_state=EXTERNAL,
            profile=PROFILE, status='pending', qmp=[], stages=[], original_ap_restore_verified=False,
            whole_machine_verified=False, capture_verified=False, previous_execution_evidence_reusable=False,
            cold_fallback_allowed=False, guest_execution_verified=False, owners=[])
        _live_tx(tx)
        if type(source_run) is not str or not source_run or type(generation) is not int or generation < 0:
            raise ValueError('Unique source run and nonnegative migration generation required')
        self.run, self.generation = source_run, generation
        _assets(self.launch)
        self.identity = _owned_identity(tx, self.launch, owner, qmp)
        _validate_command(self.identity['options'], self.identity['command'])
        self._source_assets()
        self.topology = topology(qmp)
        self.review = source_audit(self.launch, self.topology)
        if device_audit is not None:
            audit_contract(device_audit, self.topology, self.launch)
        self.receipt.update(source_identity=self.identity, source_run=source_run,
                            migration_generation=generation, device_audit=self.review)

    def _source_assets(self):
        options, command = self.identity['options'], self.identity['command']
        binds = {r[2]: r[1] for r in options if r[0] in ('--bind', '--ro-bind')}
        same('source kernel option', '/kernel.img', _option(command, '-kernel'))
        kernel = next(r['path'] for r in self.launch['launch_inputs'] if r['role'] == 'installed-disk-kernel')
        same('actual source kernel asset', kernel, binds.get('/kernel.img'))
        same('actual source RAM0 asset', self.launch['command'][-1], binds.get('/initrd.img'))
        same('actual source QEMU asset', str(Path(binds.get('/tools', ''))/'qemu-system-aarch64'),
             self.launch['qemu_binary'])
        same('actual source QEMU argv', '/tools/qemu-system-aarch64', command[0])
        same('actual source output path', str(Path(self.launch['dtb']).parent), binds.get('/out'))
        same('actual source command line', self.launch['cmdline'], _option(command, '-append'))
        same('actual source machine', 'virt,secure=off', _option(command, '-machine'))
        same('source-v4 allocated RAM MiB', '24576', _option(command, '-m'))
        same('source-v4 actual base RAM', 24576*1024**2, self.identity['memory']['base-memory'])
        env = self.launch['env']
        same('actual source CPU/timer', 'cortex-a35,cntfrq='+env.get('QEMU_ARCH_CNTFRQ', '62500000'),
             _option(command, '-cpu'))
        same('actual source SMP', env.get('QEMU_FULL_SMP', '1'), _option(command, '-smp'))
        same('actual source acceleration', 'tcg,thread='+env.get('QEMU_TCG_THREAD', 'single'),
             _option(command, '-accel'))
        if '-icount' in command:
            raise ValueError('This audit does not admit icount')
        # clearenv makes all model flags visible; unknown providers need a new audit.
        allowed = {'PWD', 'LD_LIBRARY_PATH', 'LC_ALL', 'QEMU_SONY_TIMERS', *LAUNCH['UPSTREAM_USB'],
                   'QEMU_A7PF_PROFILE', 'QEMU_A7PF_RETAINED_STATE', 'QEMU_A7PF_FD',
                   'QEMU_A7PF_DEV', 'QEMU_A7PF_INO'}
        if set(self.identity['environment']) - allowed:
            raise ValueError('Unreviewed source provider/environment')
        same('actual Sony timer model', '1', self.identity['environment'].get('QEMU_SONY_TIMERS'))
        same('actual source library path', '/tools/usr/lib', self.identity['environment'].get('LD_LIBRARY_PATH'))
        same('actual source locale', 'C', self.identity['environment'].get('LC_ALL'))

    def _fail(self, error):
        self.failed = True
        self.receipt.update(status='failed', error=type(error).__name__+': '+str(error))
        self.tx._publish('execution-failure-'+secrets.token_hex(8)+'.json', self.receipt)
        # A failed operation cannot be retried/continued with partially consumed state.
        self.captured = self.restored = False

    def capture(self, guest_sync_evidence, *, timeout=120):
        try:
            if self.failed or self.captured or self.target is not None:
                raise ValueError('Execution captures only once')
            _live_tx(self.tx)
            evidence = guest_sync_evidence
            expected = dict(schema='a7c2-retained-guest-sync-v1', kind='guest-console-sync',
                run=self.run, nonce=self.tx.guest_sync_nonce, owner_pid=self.source.pid,
                peer_pid=self.identity['peer']['pid'])
            if type(evidence) is not dict or set(evidence) != set(expected) | {'path', 'command'}:
                raise ValueError('Real caller-console guest-sync evidence required; synthetic is separate')
            for key, value in expected.items():
                same('guest-sync '+key, value, evidence[key])
            marker = 'A7C2_RETAINED_GUEST_SYNC nonce='+self.tx.guest_sync_nonce+' sync_rc=0'
            same('guest-sync command', "/bin/busybox sync && echo '"+marker+"'", evidence['command'])
            self.tx._guest_sync(evidence['path'])
            _assets(self.launch)
            same('source identity before pause', self.identity,
                 _owned_identity(self.tx, self.launch, self.source, self.source_qmp))
            same('source topology before pause', self.topology, topology(self.source_qmp))
            prior = self.source_qmp('query-migrate')
            if prior.get('status', 'none') != 'none':
                raise ValueError('Fresh source migration state required')
            self.source_qmp('stop')
            _status(self.source_qmp, 'paused')
            required = self.identity['memory']['base-memory']+R['RESERVE']
            if shutil.disk_usage(self.tx._output).free < required:
                raise ValueError('Insufficient free space for RAM stream plus reserve')
            self.binding, self.stream_identity = save_paused(self.tx, self.source_qmp,
                run=self.run, generation=self.generation, evidence_path=evidence['path'],
                receipt=self.receipt, timeout=timeout)
            same('source topology after outgoing', self.topology, topology(self.source_qmp))
            self.receipt.update(status='captured-source-postmigrate', disk_binding_sha256=R['_digest'](self.binding),
                snapshot_sha256=self.stream_identity[0], snapshot_bytes=self.stream_identity[1],
                guest_sync=copy.deepcopy(evidence))
            self.capture_manifest = copy.deepcopy(self.receipt)
            self.tx._publish('capture.json', self.capture_manifest)
            with ExitStack() as stack:
                self.capture_record = self.tx._read_file(stack, self.tx._output/'capture.json')[1]
            self.receipt['owners'].append(_quit(self.source, self.source_qmp))
            self.captured = True
            return copy.deepcopy(self.receipt)
        except BaseException as error:
            self._fail(error)
            raise

    def _capture_now(self):
        with ExitStack() as stack:
            raw, record, fd = self.tx._read_file(stack, self.tx._output/'capture.json')
            same('same capture manifest file', self.capture_record, record)
            same('same capture manifest data', self.capture_manifest, json.loads(raw))

    def restore(self, *, target_run, timeout=120):
        """Start only a transaction-bound target, load it, and return while paused."""
        try:
            if self.failed or not self.captured or self.target is not None or self.source.poll() != 0:
                raise ValueError('Completed capture and normal source quit required before target')
            if type(target_run) is not str or not target_run or target_run == self.run:
                raise ValueError('Fresh target run required')
            _disk_now(self.tx, self.binding)
            _assets(self.launch)
            if self.tx._next_phase != 2:
                raise ValueError('Target admission requires completed pre/post migration disk phases')
            self._capture_now()
            with snapshot_stream(self.tx, self.receipt) as stream:
                same('RAM stream before target Popen', self.stream_identity, R['_hash'](stream))
            self.target_run = target_run
            target_dir = self.tx._output/'target'
            target_dir.mkdir(mode=0o700)
            self.target_dirfd = DS['DISK']['SECURE_OPEN'](target_dir, directory=True)
            self.target_qmp_path = Path('/proc/self/fd')/str(self.target_dirfd)/'qmp.sock'
            options = copy.deepcopy(self.identity['options'])
            for row in options:
                if row[0] == '--bind' and row[2] == '/out':
                    row[1] = str(target_dir)
            command = list(self.identity['command'])
            if '-name' in command:
                command[command.index('-name')+1] = target_run
            else:
                command += ['-name', target_run]
            command += ['-S', '-incoming', 'defer']
            # Existing DTB lives under source /out. Bind exact captured input into new /out.
            options += [['--ro-bind', self.launch['dtb'], '/out/virt.dtb']]
            qfd = DS['DISK']['SECURE_OPEN'](self.launch['qemu_binary'])
            try:
                with os.fdopen(os.dup(qfd), 'rb') as program:
                    same('sealed target QEMU bytes', QEMU_SHA, hashlib.file_digest(program, 'sha256').hexdigest())
                options += [['--ro-bind', '/proc/self/fd/'+str(qfd), command[0]]]
                argv = ['bwrap']+[item for row in options for item in row]+command
                self.tx._publish('target-admission.json', dict(schema='a7c2-retained-target-admission-v1',
                    transaction=self.binding['transaction'], disk_binding_sha256=R['_digest'](self.binding),
                    snapshot_sha256=self.stream_identity[0], migration_generation=self.generation+1,
                    disk_generation=self.binding['disk_generation'], command=argv, run=target_run,
                    external_state=EXTERNAL, audit_sha256=R['_digest'](self.review)))
                _disk_now(self.tx, self.binding)
                _assets(self.launch)
                logfd = os.open(target_dir/'console.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                self.target_log = os.fdopen(logfd, 'wb')
                self.target = subprocess.Popen(argv, env={'PATH': os.defpath, 'LC_ALL': 'C'},
                    pass_fds=self.tx.pass_fds+(qfd,), stdin=subprocess.PIPE,
                    stdout=self.target_log, stderr=subprocess.STDOUT)
                self.tx.children.append(self.target)
            finally:
                os.close(qfd)
            self.target_qmp = _connect(self.target_qmp_path, self.target)
            self.target_identity = _owned_identity(self.tx, self.launch, self.target, self.target_qmp,
                                                   options=options, command=command)
            same('new target QMP name', dict(name=target_run), self.target_identity['qmp_name'])
            same('same target environment', self.identity['environment'], self.target_identity['environment'])
            same('same target RAM size', self.identity['memory'], self.target_identity['memory'])
            same('target before incoming topology', self.topology, topology(self.target_qmp))
            load_paused(self.tx, self.target_qmp, self.binding, self.stream_identity,
                        run=target_run, generation=self.generation+1, receipt=self.receipt, timeout=timeout)
            same('target paused restored topology', self.topology, topology(self.target_qmp))
            _status(self.target_qmp, 'paused')
            self.receipt.update(status='restored-paused', target_identity=self.target_identity,
                target_run=target_run, migration_generation=self.generation+1, disk_generation=self.binding['disk_generation'],
                stages=[], previous_execution_evidence_reusable=False, guest_execution_verified=False)
            self.tx._publish('restore-paused.json', self.receipt)
            self.restored = True
            return self.target, self.target_qmp, copy.deepcopy(self.receipt)
        except BaseException as error:
            self._fail(error)
            raise

    def continue_target(self):
        try:
            if self.failed or not self.restored or self.continued:
                raise ValueError('Exactly one successfully verified paused restore is required')
            _disk_now(self.tx, self.binding)
            _status(self.target_qmp, 'paused')
            same('target topology before cont', self.topology, topology(self.target_qmp))
            self._capture_now()
            with snapshot_stream(self.tx, self.receipt) as stream:
                same('stream before cont', self.stream_identity, R['_hash'](stream))
            self.target_qmp('cont')
            same('target CPU continuation', True, self.target_qmp('query-status')['running'])
            self.continued = True
            self.receipt.update(status='continued-awaiting-new-guest-evidence', retained_cpu_resumed=True, stages=[])
            self.tx._publish('continued.json', self.receipt)
            return copy.deepcopy(self.receipt)
        except BaseException as error:
            self._fail(error)
            raise

    def close(self):
        """Caller must invoke in finally; no signals, implicit cont or timeout kill."""
        errors = []
        for owner, qmp in ((self.source, self.source_qmp), (self.target, self.target_qmp)):
            if owner is None:
                continue
            try:
                if not any(row['pid'] == owner.pid for row in self.receipt['owners']):
                    if qmp is None and owner.poll() is None:
                        qmp = _connect(self.target_qmp_path, owner)
                        self.target_qmp = qmp
                    self.receipt['owners'].append(_quit(owner, qmp))
            except BaseException as error:
                errors.append(error)
        if errors:
            self._fail(BaseExceptionGroup('Normal QMP owner cleanup failed', errors))
            raise BaseExceptionGroup('Normal QMP owner cleanup failed', errors)
        self.receipt['owners_closed'] = True
        self.tx._publish('execution-closed.json', self.receipt)
        if self.target_qmp is not None:
            self.target_qmp.stream.close()
            self.target_qmp.sock.close()
        if self.target is not None:
            self.target.stdin.close()
        if hasattr(self, 'target_log'):
            self.target_log.close()
        if hasattr(self, 'target_dirfd'):
            os.close(self.target_dirfd)
        return copy.deepcopy(self.receipt)
