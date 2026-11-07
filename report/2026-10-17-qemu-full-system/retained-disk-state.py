#!/usr/bin/env python3
"""Same-lease external-disk binding only; no RAM loader, QMP cont or cold fallback.

Use transaction(instance, private_output) across BOTH VM owners. Pass tx.pass_fds
and register every Popen in tx.children, as in persistent-boot.leased_launch.
A fresh tx.guest_sync_nonce must be observed after real guest sync; snapshot_disk
checks the caller's private console evidence, never equates fdatasync with sync.
See RETAINED-DISK-STATE.md for the strict phase and JSON binding contract.
"""
from contextlib import ExitStack, contextmanager
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import stat
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
BOOT = runpy.run_path(str(HERE/'persistent-boot.py'))
DISK, GEOMETRY = BOOT['DISK'], BOOT['GEOMETRY']
RETAINED = runpy.run_path(str(HERE/'retained-boot.py'))
SCHEMA = 'a7c2-retained-disk-binding-v1'
PHASES = ('pre-migration', 'post-migration', 'pre-restore', 'post-restore')
STATES = ('paused', 'postmigrate', 'inmigrate', 'paused')
SOURCES = ('private-device-dump', 'official-bodydata-derived')


def _object(fields):
    return dict(type='object', properties=fields, required=list(fields), additionalProperties=False)


INT = dict(type='integer', minimum=0)
SHA = dict(type='string', pattern='^[0-9a-f]{64}$')
TEXT = dict(type='string', minLength=1)
FILE_SCHEMA = _object(dict(dev=INT, ino=INT, size=INT, uid=INT,
    mode=dict(type='integer', const=0o600), nlink=dict(type='integer', const=1),
    stamp=dict(type='array', items=INT, minItems=5, maxItems=5)))
HASHED_FILE_SCHEMA = _object(dict(FILE_SCHEMA['properties'], sha256=SHA))
GEOMETRY_SCHEMA = _object(dict(
    schema=dict(type='string', const=DISK['SCHEMA']), sector_bytes=dict(type='integer', const=512),
    backing_file=dict(type='string', const='camera.emmc'), backing_bytes=INT, user_bytes=INT,
    partition_rows=dict(type='array', minItems=30, maxItems=30, items=_object(
        {name:INT for name in ('part','start_lba','sectors','type','flags','offset','bytes')})),
    slices=dict(type='array', minItems=19, maxItems=19, items=_object(dict(
        id=TEXT, area=TEXT, offset=INT, bytes=INT, source=TEXT, source_sha256=SHA))),
    area_mapping=TEXT, user_capacity_basis=TEXT, configured_user_extent_bytes=INT,
    unused_user_tail_bytes=INT, unused_tail_initialization=TEXT, sdm2_label_sha256=SHA))
BINDING_SCHEMA = _object(dict(
    schema=dict(type='string', const=SCHEMA), phase=dict(type='string', const='disk-binding-prepared'),
    whole_machine_verified=dict(type='boolean', const=False),
    transaction=_object(dict(token=SHA, parent_pid=INT, fd=INT)),
    capture=_object(dict(host_run=TEXT, migration_generation=INT, guest_sync=_object(dict(
        path=TEXT, nonce=dict(type='string', pattern='^[0-9a-f]{32}$'), marker=TEXT,
        evidence=HASHED_FILE_SCHEMA, verification=dict(type='string', const='caller-console-marker'))))),
    disk=FILE_SCHEMA, disk_generation=INT, source_class=dict(type='string', enum=list(SOURCES)),
    source_manifest_sha256=SHA, geometry=GEOMETRY_SCHEMA,
    metadata=_object(dict(geometry=HASHED_FILE_SCHEMA, instance=HASHED_FILE_SCHEMA)),
    wire=_object(dict(file=HASHED_FILE_SCHEMA, hex=dict(type='string', pattern='^(?:[0-9a-f]{2})+$'))),
    canonical_wire=_object(dict(sha256=SHA, hex=dict(type='string', pattern='^(?:[0-9a-f]{2})+$'))),
    whole_disk_sha256=SHA,
    partition_bindings=dict(type='array', minItems=3, maxItems=3, items=_object(
        dict(id=TEXT, offset=INT, bytes=INT, sha256=SHA)))))
BINDING_SCHEMA['$schema'] = 'https://json-schema.org/draft/2020-12/schema'


def _validate(value, schema, label='binding'):
    """Validate exactly the JSON-schema subset used by this one public contract."""
    kind = schema['type']
    expected = {'object':dict, 'array':list, 'integer':int, 'string':str, 'boolean':bool}[kind]
    if type(value) is not expected:
        raise ValueError(label+': expected '+kind)
    if 'const' in schema and value != schema['const']:
        raise ValueError(label+': incorrect constant')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(label+': unknown value')
    if kind == 'object':
        if set(value) != set(schema['properties']):
            raise ValueError(label+': missing or unexpected fields')
        for name, child in schema['properties'].items():
            _validate(value[name], child, label+'.'+name)
    elif kind == 'array':
        if not schema['minItems'] <= len(value) <= schema['maxItems']:
            raise ValueError(label+': incorrect array length')
        for index, item in enumerate(value):
            _validate(item, schema['items'], label+'['+str(index)+']')
    elif kind == 'integer' and value < schema.get('minimum', 0):
        raise ValueError(label+': negative integer')
    elif kind == 'string':
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.fullmatch(schema['pattern'], value)):
            raise ValueError(label+': invalid string')


def _record(fd):
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
        raise ValueError('Expected owned, single-link, mode 0600 regular file')
    return dict(dev=info.st_dev, ino=info.st_ino, size=info.st_size, uid=info.st_uid,
                mode=stat.S_IMODE(info.st_mode), nlink=info.st_nlink, stamp=list(DISK['stamp'](fd)))


def _directory(fd):
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Expected owned, mode 0700 private directory')
    return info.st_dev, info.st_ino


def _same(label, expected, actual):
    BOOT['identical'](label, expected, actual)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


class DiskStateError(RuntimeError):
    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


class DiskTransaction:
    def __init__(self, leased, output, outfd, directory_fd, lock_fd, stack):
        self._leased, self._output, self._outfd = leased, output, outfd
        self._fd = leased['fd']
        self._anchor = os.dup(self._fd)
        stack.callback(os.close, self._anchor)
        self._parent_pid, self._token = os.getpid(), secrets.token_hex(32)
        self._directory = _directory(directory_fd)
        self._output_directory = _directory(outfd)
        self._lock = _record(lock_fd)
        current = _record(self._fd)
        self._inode = (current['dev'], current['ino'])
        self._binding, self._next_phase, self._failed, self._closed = None, 0, False, False
        self._qmp = []
        self.guest_sync_nonce = secrets.token_hex(16)
        self.children = []
        self._check_anchor()

    @property
    def fd(self):
        return self._fd

    @property
    def pass_fds(self):
        return (self._fd,)

    def _check_path(self, path, expected, *, directory=False):
        fd = DISK['SECURE_OPEN'](path, directory=directory)
        try:
            actual = _directory(fd) if directory else _record(fd)
            _same('current path '+str(path), expected, actual)
        finally:
            os.close(fd)

    def _check_anchor(self):
        if self._closed or os.getpid() != self._parent_pid:
            raise ValueError('Transaction closed or parent process changed')
        # Linux F_DUPFD_QUERY compares open file descriptions, including reused FD numbers.
        if fcntl.fcntl(self._fd, getattr(fcntl, 'F_DUPFD_QUERY', 1027), self._anchor) != 1:
            raise ValueError('Parent FD no longer shares the leased open file description')
        if fcntl.fcntl(self._fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
            raise ValueError('Leased disk FD must remain writable')
        current = _record(self._fd)
        _same('leased disk inode', self._inode, (current['dev'], current['ino']))
        self._check_path(self._leased['path'], self._directory, directory=True)
        self._check_path(self._leased['path']/'camera.emmc', current)
        self._check_path(self._leased['path']/'.disk.lock', self._lock)
        return current

    def _publish(self, name, value):
        self._check_path(self._output, self._output_directory, directory=True)
        RETAINED['_json'](self._outfd, name, value)
        self._check_path(self._output, self._output_directory, directory=True)

    def _fail(self, error, phase):
        self._failed = True
        receipt = dict(schema=1, scope='retained-external-disk-only', phase=phase, status='failed',
            whole_machine_verified=False, transaction=self._token, parent_pid=self._parent_pid,
            error=type(error).__name__+': '+str(error), qmp=copy.deepcopy(self._qmp))
        try:
            _same('private failure output', self._output_directory, _directory(self._outfd))
            RETAINED['_json'](self._outfd, 'disk-failure-'+secrets.token_hex(8)+'.json', receipt)
        except BaseException as write_error:
            raise BaseExceptionGroup('Disk failure AND failure-receipt write failure', [error, write_error])
        raise DiskStateError(str(error), receipt) from error

    @contextmanager
    def _operation(self, phase):
        self._qmp = []
        try:
            if self._failed:
                raise ValueError('Failed transaction cannot continue')
            self._check_anchor()
            yield
        except BaseException as error:
            self._fail(error, phase)

    def _status(self, qmp, expected):
        row = dict(command='query-status')
        self._qmp.append(row)
        result = qmp('query-status')
        row['response'] = copy.deepcopy(result)
        if type(result) is not dict or result.get('running') is not False or result.get('status') != expected:
            raise ValueError('Actual QMP query-status must report '+expected+' with running=false')
        if expected == 'postmigrate':
            migration = dict(command='query-migrate')
            self._qmp.append(migration)
            migration['response'] = copy.deepcopy(qmp('query-migrate'))
            if type(migration['response']) is not dict or migration['response'].get('status') != 'completed':
                raise ValueError('Outgoing migration must report completed before disk verification')

    def _read_file(self, stack, path, budget=1024**2):
        fd = DISK['SECURE_OPEN'](path)
        stack.callback(os.close, fd)
        before = _record(fd)
        if before['size'] > budget:
            raise ValueError('Metadata/evidence exceeds read budget')
        raw = os.pread(fd, before['size']+1, 0)
        if len(raw) != before['size']:
            raise ValueError('Metadata/evidence truncated or grew')
        _same('file read stamp '+str(path), before, _record(fd))
        self._check_path(path, before)
        return raw, dict(before, sha256=_sha(raw)), fd

    def _guest_sync(self, path):
        path = Path(os.path.abspath(path))
        with ExitStack() as stack:
            raw, evidence, fd = self._read_file(stack, path)
            marker = 'A7C2_RETAINED_GUEST_SYNC nonce='+self.guest_sync_nonce+' sync_rc=0'
            if raw.splitlines().count(marker.encode('ascii')) != 1:
                raise ValueError('Missing unique, fresh guest-sync nonce marker from caller console')
            _same('guest sync evidence stability', evidence, dict(_record(fd), sha256=_sha(raw)))
        return dict(path=str(path), nonce=self.guest_sync_nonce, marker=marker,
                    evidence=evidence, verification='caller-console-marker')

    def _measure(self, qmp, expected_status):
        self._status(qmp, expected_status)
        self._check_anchor()
        os.fdatasync(self._fd)
        before = self._check_anchor()
        with ExitStack() as stack:
            files = {}
            for key, name in (('geometry','geometry.json'), ('instance','instance.json'), ('wire','persistent-geometry.bin')):
                files[key] = self._read_file(stack, self._leased['path']/name)
            geometry = json.loads(files['geometry'][0])
            state = json.loads(files['instance'][0])
            _validate(geometry, GEOMETRY_SCHEMA, 'geometry')
            if type(state) is not dict or state.get('schema') != DISK['SCHEMA'] or state.get('source_class') not in SOURCES:
                raise ValueError('Unknown instance schema/source class')
            _validate(state.get('generation'), INT, 'disk generation')
            _validate(state.get('source_manifest_sha256'), SHA, 'source manifest SHA256')
            _same('metadata geometry SHA256', files['geometry'][1]['sha256'], state.get('geometry_sha256'))
            _same('disk capacity', geometry['backing_bytes'], before['size'])
            _same('SDM2 label', DISK['label_bytes'](geometry['partition_rows']).hex(), os.pread(self._fd, 512, 0).hex())
            with tempfile.TemporaryDirectory(prefix='.retained-wire-', dir='/proc/self/fd/'+str(self._outfd)) as work:
                canonical = Path(work)/'geometry.bin'
                GEOMETRY['write_camera_wire'](geometry, canonical)
                canonical_bytes = canonical.read_bytes()
            _same('current/canonical wire', canonical_bytes.hex(), files['wire'][0].hex())
            live = dict(self._leased, geometry=geometry, state=state)
            ranges = BOOT['partition_bindings'](live)
            # verify_firmware consumes current ranges/geometry; its kernel slot is not an ELF check.
            BOOT['verify_firmware'](live, dict(firmware_binding_schema=1, actual_kernel=None,
                partition_bindings=ranges, instance_generation=state['generation'],
                instance_source_manifest_sha256=state['source_manifest_sha256'],
                instance_geometry=geometry, instance_wire_sha256=_sha(canonical_bytes)))
            whole = DISK['hashed'](self._fd)
            current_hashes = {key:DISK['hashed'](item[2]) for key,item in files.items()}
            for key, name in (('geometry','geometry.json'), ('instance','instance.json'), ('wire','persistent-geometry.bin')):
                raw, record, fd = files[key]
                _same(name+' changed during binding', record, dict(_record(fd), sha256=current_hashes[key]))
                self._check_path(self._leased['path']/name, {k:v for k,v in record.items() if k != 'sha256'})
            self._status(qmp, expected_status)
            _same('disk changed during complete hash', before, self._check_anchor())
            return dict(disk=before, disk_generation=state['generation'], source_class=state['source_class'],
                source_manifest_sha256=state['source_manifest_sha256'], geometry=geometry,
                metadata={k:files[k][1] for k in ('geometry','instance')},
                wire=dict(file=files['wire'][1], hex=files['wire'][0].hex()),
                canonical_wire=dict(sha256=_sha(canonical_bytes), hex=canonical_bytes.hex()),
                whole_disk_sha256=whole, partition_bindings=ranges)

    def snapshot_disk(self, qmp, *, host_run, migration_generation, guest_sync_evidence):
        """Prepare only a disk binding; source must already be paused by its owner."""
        with self._operation('disk-binding-prepared'):
            if self._binding is not None:
                raise ValueError('A transaction captures only one disk binding')
            _validate(host_run, TEXT, 'host run')
            _validate(migration_generation, INT, 'migration generation')
            sync = self._guest_sync(guest_sync_evidence)
            measured = self._measure(qmp, 'paused')
            _same('guest sync evidence changed during capture', sync, self._guest_sync(guest_sync_evidence))
            result = dict(schema=SCHEMA, phase='disk-binding-prepared', whole_machine_verified=False,
                transaction=dict(token=self._token, parent_pid=self._parent_pid, fd=self._fd),
                capture=dict(host_run=host_run, migration_generation=migration_generation, guest_sync=sync), **measured)
            _validate(result, BINDING_SCHEMA)
            self._publish('disk-binding.json', result)
            self._binding = copy.deepcopy(result)
            return result

    def verify(self, snapshot_binding, qmp, *, phase, host_run, migration_generation):
        """Check SAME binding before/after transfer and before/after paused restore."""
        with self._operation(phase):
            _validate(snapshot_binding, BINDING_SCHEMA)
            _same('binding captured in this same transaction', self._binding, snapshot_binding)
            if self._next_phase >= len(PHASES) or phase != PHASES[self._next_phase]:
                raise ValueError('Disk phases must follow '+', '.join(PHASES))
            _validate(host_run, TEXT, 'host run')
            _validate(migration_generation, INT, 'migration generation')
            capture = snapshot_binding['capture']
            if self._next_phase < 2:
                _same('source host run', capture['host_run'], host_run)
                _same('source migration generation', capture['migration_generation'], migration_generation)
            else:
                if host_run == capture['host_run']:
                    raise ValueError('Restore requires a new host run')
                _same('target migration generation', capture['migration_generation']+1, migration_generation)
                if self._next_phase == 3:
                    _same('same restore target', self._target, (host_run, migration_generation))
            current = self._measure(qmp, STATES[self._next_phase])
            _same('same current disk binding', {key:snapshot_binding[key] for key in current}, current)
            result = dict(schema=1, scope='retained-external-disk-only', phase=phase,
                disk_binding_verified=True, whole_machine_verified=False, host_run=host_run,
                migration_generation=migration_generation, disk_generation=current['disk_generation'],
                binding_sha256=RETAINED['_digest'](snapshot_binding), qmp=copy.deepcopy(self._qmp))
            self._publish('disk-'+phase+'.json', result)
            if self._next_phase == 2:
                self._target = (host_run, migration_generation)
            self._next_phase += 1
            return result

    def _wait_children(self):
        errors = []
        for child in self.children:
            retained = False
            while child.poll() is None:
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    if not retained:
                        retained = True
                        try:
                            self._publish('owner-retained-'+secrets.token_hex(8)+'.json', dict(
                                schema=1, status='owner-live-lease-retained', parent_pid=self._parent_pid,
                                owner_pid=child.pid, command=child.args, transaction=self._token,
                                lease_held=True, vm_signals_sent=[], whole_machine_verified=False))
                        except BaseException as error:
                            errors.append(error)
                except BaseException as error:
                    errors.append(error)
        if errors:
            pending = sys.exception()
            if pending is not None:
                errors.insert(0, pending)
            self._fail(BaseExceptionGroup('Owned child wait errors (all children exited)', errors), 'owner-wait')


@contextmanager
def transaction(instance, output):
    """Retain camera-disk.lease through source and target normal owner exit.

    output must be an existing private 0700 directory, shared with caller's RAM
    artifacts. Every publication is 0600/O_EXCL/atomic; no old file is removed.
    Failure does not signal a VM, continue it, erase evidence or select cold boot.
    """
    instance, output = (Path(os.path.abspath(p)) for p in (instance, output))
    with ExitStack() as stack:
        outfd = DISK['SECURE_OPEN'](output, directory=True)
        stack.callback(os.close, outfd)
        _directory(outfd)
        tx = None
        try:
            directory_fd = DISK['SECURE_OPEN'](instance, directory=True)
            stack.callback(os.close, directory_fd)
            _directory(directory_fd)
            lock_fd = DISK['SECURE_OPEN'](instance/'.disk.lock', os.O_RDWR)
            stack.callback(os.close, lock_fd)
            lock_before = _record(lock_fd)
            with DISK['lease'](instance) as leased:
                _same('lease lock path did not change', lock_before, _record(lock_fd))
                tx = DiskTransaction(leased, output, outfd, directory_fd, lock_fd, stack)
                try:
                    yield tx
                except BaseException as error:
                    if isinstance(error, DiskStateError):
                        raise
                    tx._fail(error, 'caller-transaction')
                finally:
                    try:
                        tx._wait_children()
                    finally:
                        tx._closed = True
        except BaseException as error:
            if tx is not None or isinstance(error, DiskStateError):
                raise
            receipt = dict(schema=1, scope='retained-external-disk-only', phase='lease-admission',
                status='failed', whole_machine_verified=False, error=type(error).__name__+': '+str(error))
            try:
                RETAINED['_json'](outfd, 'disk-failure-'+secrets.token_hex(8)+'.json', receipt)
            except BaseException as write_error:
                raise BaseExceptionGroup('Lease failure AND failure-receipt write failure', [error, write_error])
            raise DiskStateError(str(error), receipt) from error
