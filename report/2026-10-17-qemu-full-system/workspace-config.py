#!/usr/bin/env python3
"""Private immutable configuration generations and an atomic workspace pointer."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import shutil
import stat
import tempfile

HERE = Path(__file__).resolve().parent
STATE = runpy.run_path(str(HERE / 'config-state.py'))
PUBLISH = runpy.run_path(str(HERE / 'publish-config.py'))
BODYDATA_SHA = 'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
FORMAT = b'A7C2_WORKSPACE_CONFIG_V1\n'


class Conflict(ValueError):
    pass


class PublicationUncertain(OSError):
    """Pointer changed but directory durability is unknown: reload before retry."""


def write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


@contextmanager
def locked(workspace, inherited_fd=None):
    workspace = Path(workspace).resolve(strict=True)
    state = STATE['owned'](workspace, '.a7c2', directory=True, missing=True)
    state.mkdir(mode=0o700, exist_ok=True)
    path = STATE['owned'](workspace, '.a7c2/config.lock', missing=True)
    fd = (os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
          if inherited_fd is None else os.dup(inherited_fd))
    store = None
    try:
        info = os.fstat(fd)
        expected = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or (info.st_dev, info.st_ino) != (expected.st_dev, expected.st_ino)):
            raise ValueError('workspace lock descriptor does not name its private lock file')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('workspace configuration is busy') from error
        store = Store(workspace, fd)
        yield store
    finally:
        if store is not None:
            store.active = False
        # Do not LOCK_UN: a launcher child may share the parent's file description.
        os.close(fd)


class Store:
    def __init__(self, workspace, fd):
        self.workspace, self.fd, self.active = Path(workspace), fd, True
        self.owner_pid = os.getpid()
        info = self.workspace.lstat()
        self.directory_identity = (info.st_dev, info.st_ino)

    def path(self, name, *, directory=False, missing=False):
        if not self.active or self.owner_pid != os.getpid():
            raise RuntimeError('workspace operation outside its lock lifetime')
        info = self.workspace.lstat()
        if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != self.directory_identity:
            raise ValueError('workspace directory identity changed')
        lock = STATE['owned'](self.workspace, '.a7c2/config.lock')
        held, current = os.fstat(self.fd), lock.lstat()
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError('workspace lock identity changed')
        return STATE['owned'](self.workspace, '.a7c2/' + name, directory=directory, missing=missing)

    def root(self, create=False):
        root = self.path('config', directory=True, missing=True)
        if not root.exists() and not create:
            return None
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('workspace configuration requires an owned private 0700 directory')
        marker = self.path('config/format', missing=True)
        if not marker.exists() and not any(root.iterdir()):
            if not create:
                return None
            write_private(marker, FORMAT)
        if STATE['read_regular'](marker, limit=128) != FORMAT:
            raise ValueError('unrecognised workspace configuration directory')
        generations = self.path('config/generations', directory=True, missing=True)
        if create:
            generations.mkdir(mode=0o700, exist_ok=True)
        return root

    def require_space(self, required):
        root = self.root(create=True)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstatvfs(fd)
        except OSError as error:
            raise ValueError('workspace free space unknown') from error
        finally:
            os.close(fd)
        if (type(info.f_bavail) is not int or type(info.f_frsize) is not int
                or info.f_bavail < 0 or info.f_frsize <= 0):
            raise ValueError('workspace free space unknown')
        if info.f_bavail * info.f_frsize < required + 1024**2:
            raise ValueError('insufficient workspace free space')

    @staticmethod
    def identity(pair):
        hashed = hashlib.sha256()
        for name in ('BACKUP.BIN', 'BACKUP.BAK'):
            hashed.update(pair[name])
        return 'gen-' + hashed.hexdigest()

    def generation(self, name, reference):
        if not re.fullmatch(r'gen-[0-9a-f]{64}', name):
            raise ValueError('invalid workspace generation name')
        directory = self.path('config/generations/' + name, directory=True)
        reset_path = self.path('config/generations/' + name + '/reset.json', missing=True)
        if reset_path.exists():
            if {p.name for p in directory.iterdir()} != {'reset.json'}:
                raise ValueError('mixed reset and backup generation')
            raw = STATE['read_regular'](reset_path, limit=8192)
            record = json.loads(raw)
            if (set(record) != {'schema', 'state', 'bodydata_sha256', 'parent_generation', 'token'}
                    or record['schema'] != 'workspace-config-reset-v1' or record['state'] != 'reset'
                    or record['bodydata_sha256'] != BODYDATA_SHA
                    or not isinstance(record['parent_generation'], str)
                    or re.fullmatch(r'gen-[0-9a-f]{64}', record['parent_generation']) is None
                    or not isinstance(record['token'], str)
                    or re.fullmatch(r'[0-9a-f]{32}', record['token']) is None
                    or 'gen-' + hashlib.sha256(raw).hexdigest() != name):
                raise ValueError('invalid reset generation')
            return {'identity': name, 'directory': directory, 'state': 'reset',
                    'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'files': None}
        manifest_path = self.path('config/generations/' + name + '/config-persistence.json')
        raw = STATE['read_regular'](manifest_path)
        verdict = json.loads(raw)
        if verdict.get('source') != 'official-bodydata-derived' or verdict.get('bodydata_sha256') != BODYDATA_SHA:
            raise ValueError('stored configuration has no official BODYDATA provenance')
        for local in ('Backup.bin', 'Backup.bak'):
            self.path('config/generations/' + name + '/' + local)
        pair = PUBLISH['verified_pair'](directory, verdict, reference)
        payload_identity = self.identity(pair)
        token = verdict.get('workspace_generation')
        if token is None:
            if payload_identity != name:
                raise ValueError('legacy workspace generation content differs from its identity')
        elif token != name or verdict.get('payload_identity') != payload_identity:
            raise ValueError('workspace generation token or content digest differs')
        return {'identity': name, 'directory': directory, 'state': 'backup', 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
                'payload_identity': payload_identity, 'files': pair}

    def current(self, reference):
        if self.root() is None:
            return None
        path = self.path('config/current.json', missing=True)
        if not path.exists():
            generations = self.path('config/generations', directory=True, missing=True)
            if generations.exists() and any(p.name.startswith('gen-') for p in generations.iterdir()):
                raise ValueError('missing current pointer in a nonempty configuration store')
            return None
        pointer = json.loads(STATE['read_regular'](path, limit=8192))
        if pointer.get('schema') != 'workspace-config-pointer-v1':
            raise ValueError('unsupported workspace configuration pointer')
        generation = self.generation(pointer['generation'], reference)
        if generation['manifest_sha256'] != pointer.get('manifest_sha256'):
            raise ValueError('workspace manifest differs from the committed pointer')
        return generation

    def checked_current(self, reference, expected_generation):
        if expected_generation is not None and (not isinstance(expected_generation, str)
                or re.fullmatch(r'gen-[0-9a-f]{64}', expected_generation) is None):
            raise ValueError('invalid expected workspace generation')
        current = self.current(reference)
        actual = current['identity'] if current is not None else None
        if actual != expected_generation:
            raise Conflict('workspace configuration generation changed')
        return current

    def save_run(self, run, reference, expected_generation=None):
        run = Path(run).resolve(strict=True)
        result = json.loads(STATE['read_regular'](run / 'result.json'))
        inputs = json.loads(STATE['read_regular'](run / 'inputs.json'))
        if (inputs.get('source') != 'official-bodydata-derived' or inputs.get('bodydata_sha256') != BODYDATA_SHA):
            raise ValueError('workspace configuration requires the verified official BODYDATA route')
        if (result.get('state') != 'observation-completed' or not result.get('input_producer_stopped_verified')
                or result.get('config_sync') != {'subsystem': 0x2cf, 'verified': True}
                or result.get('config_export', {}).get('verified') is not True
                or result.get('config_export_trigger') not in ('observation-deadline', 'owned-ui-close-request')):
            raise ValueError('run did not complete the original stop/sync/export lifecycle')
        console_sha = hashlib.sha256(STATE['read_regular'](run / 'console.log', limit=64 * 1024**2)).hexdigest()
        if console_sha != result.get('terminal_console_sha256'):
            raise ValueError('source console differs from the closed run')
        verdict = {'export_verified': True, 'files': [], 'source_run': str(run),
                   'source': inputs['source'], 'bodydata_sha256': BODYDATA_SHA,
                   'console_sha256': console_sha, 'sync_receipt': result['config_sync']}
        for item in result['config_export'].get('files', []):
            verdict['files'].append({**item, 'valid': True})
        pair = PUBLISH['verified_pair'](run, verdict, reference)
        self.checked_current(reference, expected_generation)
        root = self.root(create=True)
        self.require_space(sum(len(data) for data in pair.values()) + 16384)
        # Unique commit tokens, as in native, prevent ABA across reset/re-save of identical bytes.
        name = 'gen-' + secrets.token_hex(32)
        verdict['workspace_generation'] = name
        verdict['payload_identity'] = self.identity(pair)
        destination = self.path('config/generations/' + name, directory=True, missing=True)
        if not destination.exists():
            staged = Path(tempfile.mkdtemp(prefix='.pending-', dir=root / 'generations'))
            try:
                for local, remote in PUBLISH['TARGETS']:
                    write_private(staged / local, pair[remote])
                write_private(staged / 'config-persistence.json', encode(verdict))
                STATE['sync_directory'](staged)
                os.rename(staged, destination)
                STATE['sync_directory'](destination.parent)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
        generation = self.generation(name, reference)
        return self.select_generation(generation)

    def select_generation(self, generation):
        root = self.root(create=True)
        pointer = {'schema': 'workspace-config-pointer-v1', 'generation': generation['identity'],
                   'manifest_sha256': generation['manifest_sha256']}
        self.path('config/current.json', missing=True)
        fd, temporary = tempfile.mkstemp(prefix='.current-', dir=root)
        temporary = Path(temporary)
        try:
            payload = encode(pointer)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if STATE['read_regular'](temporary, limit=8192) != payload:
                raise ValueError('workspace pointer readback differs')
            STATE['sync_directory'](root)
            os.replace(temporary, root / 'current.json')
            try:
                STATE['sync_directory'](root)
            except OSError as error:
                raise PublicationUncertain('workspace pointer renamed; durability unknown, reload before retry') from error
        finally:
            temporary.unlink(missing_ok=True)
        # shortcut: retain old immutable generations for recovery; add retention after lifecycle validation.
        return pointer

    def reset(self, reference, expected_generation, *, confirmed):
        if confirmed is not True:
            raise ValueError('explicit reset confirmation required')
        current = self.checked_current(reference, expected_generation)
        if current is None:
            raise ValueError('no saved configuration generation to reset')
        root = self.root()
        self.require_space(16384)
        record = {'schema': 'workspace-config-reset-v1', 'state': 'reset',
                  'bodydata_sha256': BODYDATA_SHA, 'parent_generation': current['identity'],
                  'token': secrets.token_hex(16)}
        raw = encode(record)
        name = 'gen-' + hashlib.sha256(raw).hexdigest()
        destination = self.path('config/generations/' + name, directory=True, missing=True)
        staged = Path(tempfile.mkdtemp(prefix='.pending-reset-', dir=root / 'generations'))
        try:
            write_private(staged / 'reset.json', raw)
            STATE['sync_directory'](staged)
            os.rename(staged, destination)
            STATE['sync_directory'](destination.parent)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        return self.select_generation(self.generation(name, reference))

    def load_into(self, runtime):
        runtime = Path(runtime).resolve(strict=True)
        with STATE['exclusive_runtime'](runtime):
            image = STATE['owned'](runtime, 'analysis/root/partitions/nflasha2.img')
            reference = STATE['extract'](image, 'BACKUP.BIN')
            if reference is None or hashlib.sha256(reference).hexdigest() != PUBLISH['BACKUP']['OFFICIAL_PP_SHA256']:
                raise ValueError('workspace reload target must start from verified official PP')
            generation = self.current(reference)
            if generation is None:
                return None
            if generation['state'] == 'reset':
                return generation['identity']  # Explicit tombstone: keep the verified factory PP.
            from types import SimpleNamespace
            PUBLISH['publish_locked'](SimpleNamespace(apply=True, force_generation=False,
                                                     keep_parent_as_bak=False, omit_bak=False),
                                      runtime, generation['directory'])
            return generation['identity']


def official_reference(runtime):
    """Use the verified parent PP, including after a runtime has loaded a generation."""
    runtime = Path(runtime).resolve(strict=True)
    cached = STATE['owned'](runtime, 'analysis/official-pp.bin', missing=True)
    if cached.exists():
        data = STATE['read_regular'](cached)
    else:
        image = STATE['owned'](runtime, 'analysis/root/partitions/nflasha2.img')
        data = STATE['extract'](image, 'BACKUP.BIN')
    if data is None or hashlib.sha256(data).hexdigest() != PUBLISH['BACKUP']['OFFICIAL_PP_SHA256']:
        raise ValueError('runtime has no verified official PP reference')
    return data


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--save-run', type=Path)
    action.add_argument('--reset', action='store_true')
    action.add_argument('--preview', action='store_true', help='validate the offline reset target without changing it')
    parser.add_argument('--expected-generation')
    parser.add_argument('--confirm', default='')
    parser.add_argument('--runtime', type=Path, required=True, help='the run owner runtime, for the PP reference')
    args = parser.parse_args()
    with locked(args.workspace) as store, STATE['exclusive_runtime'](args.runtime):
        reference = official_reference(args.runtime)
        if args.preview:
            current = store.current(reference)
            if current is None:
                print('WORKSPACE_CONFIG_EMPTY')
            else:
                print('WORKSPACE_CONFIG_PREVIEW', current['identity'], current['state'])
            return 0
        if args.reset:
            pointer = store.reset(reference, args.expected_generation, confirmed=args.confirm == 'reset')
            print('WORKSPACE_CONFIG_RESET', pointer['generation'])
            return 0
        current = store.current(reference)
        pointer = store.save_run(args.save_run, reference, current['identity'] if current else None)
    print('WORKSPACE_CONFIG_SAVED', pointer['generation'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
