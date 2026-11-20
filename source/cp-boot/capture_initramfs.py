#!/usr/bin/env python3
"""Build one private native-pair initramfs with its owned virtual SD seed.

The complete cpio must fit the fixed loader reservation [0x504000000,
0x580000000). A JPEG-filled 1GiB card may not compress enough; reject that
seed instead of enlarging the window or assuming gzip always makes it fit.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import resource
import stat
import subprocess
import sys
import tarfile
from contextlib import ExitStack, contextmanager

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[1]
ANALYSIS = PRODUCT/'runtime/analysis'
sys.path.insert(0, str(ANALYSIS))
from firmware_overlay import build_overlay_initramfs, _parent, _check_anchors
from initramfs_identity import verify_image
from sd_transport import card_source, digest_fd, identity

CARD_BYTES = 1024**3
RESERVE = 64*1024**3
RAM_PEAK = 24*1024**3 + 128*1024**2 + 0x101000
LOG_PEAK = 2*1024**3
INITRD_WINDOW = 0x580000000 - 0x504000000


def _ordinary(path):
    path = Path(path)
    if (not path.is_absolute() or str(path) != os.path.normpath(str(path)) or
            any(p.is_symlink() for p in (path, *path.parents))):
        raise ValueError('Expected canonical non-symlink observer path')
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
            info.st_nlink != 1 or info.st_mode & 0o022):
        raise ValueError('Observer input must be an owned single-link ordinary file')
    return info


@contextmanager
def _read(path):
    before = _ordinary(path)
    with ExitStack() as stack:
        _, parent, name, anchors = _parent(stack, path)
        fd = os.open(name, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC, dir_fd=parent)
        stack.callback(os.close, fd)
        if identity(before) != identity(os.fstat(fd)):
            raise ValueError('Observer input changed while opening')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            yield stream
        after = _ordinary(path)
        if (identity(before) != identity(after) or identity(before) != identity(os.fstat(fd)) or
                (before.st_mtime_ns, before.st_ctime_ns) != (after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('Observer input changed during readback')
        _check_anchors(anchors)


def _hash(path):
    with _read(path) as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class _PinnedImage:
    def __init__(self, stream):
        self.stream = stream

    def open(self, mode):
        if mode != 'rb':
            raise ValueError('Observer base initramfs is read-only')
        self.stream.seek(0)
        return os.fdopen(os.dup(self.stream.fileno()), mode)

    def stat(self):
        return os.fstat(self.stream.fileno())


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate observer receipt key')
        result[key] = value
    return result


def _json(path):
    if _ordinary(path).st_size > 8*1024**2:
        raise ValueError('Observer receipt exceeds size limit')
    with _read(path) as stream:
        raw = stream.read(8*1024**2+1)
    if len(raw) > 8*1024**2:
        raise ValueError('Observer receipt exceeds size limit')
    digest = hashlib.sha256(raw).hexdigest()
    value = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(value, dict):
        raise ValueError('Observer receipt is not an object')
    return value, digest


def _observer_sources():
    snapshot = runpy.run_path(str(ANALYSIS/'snapshot-observer-sources.py'))
    return snapshot['source_paths'](ANALYSIS)


def validate_observer_build(directory):
    """Admit an explicitly selected build, never the shared observer output."""
    directory = Path(directory)
    root = PRODUCT/'source/build'
    if (not directory.is_absolute() or str(directory) != os.path.normpath(str(directory)) or
            root not in directory.parents or any(p.is_symlink() for p in (directory, *directory.parents))):
        raise ValueError('Isolated observer build must be canonical and below source/build')
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Isolated observer build directory must be owned and private')
    directory_identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
    receipt, receipt_sha = _json(directory/'diagnostic-build.json')
    inputs, inputs_sha = _json(directory/'observer-build-inputs.json')
    observer = directory/'menu-observe.so'
    archive = directory/'observer-build-sources.tar.gz'
    observer_sha, archive_sha = _hash(observer), _hash(archive)
    if (receipt.get('schema') != 'a7c2-isolated-observer-build-v2' or
            receipt.get('observer_only') is not True or receipt.get('original_runtime_untouched') is not True or
            receipt.get('physical_compatible') is not False or
            receipt.get('observer_sha256') != observer_sha or inputs.get('observer_sha256') != observer_sha or
            receipt.get('source_archive_sha256') != archive_sha or inputs.get('source_archive_sha256') != archive_sha or
            receipt.get('source_receipt_sha256') != inputs_sha):
        raise ValueError('Isolated observer build artifacts differ from receipt')
    sources = inputs.get('sources')
    if (not isinstance(sources, dict) or not sources or
            set(sources) != {str(path) for path in _observer_sources()}):
        raise ValueError('Observer source snapshot is missing or incomplete')
    archived, archived_sizes = {}, {}
    for name, entry in sources.items():
        path = Path(name)
        member = PurePosixPath(entry['archive_path'])
        digest = entry['sha256']
        if (PRODUCT not in path.parents or member.is_absolute() or '..' in member.parts or
                str(member) != entry['archive_path'] or str(member) in archived or
                not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest) or
                _hash(path) != digest):
            raise ValueError('Observer source identity differs: '+name)
        archived[str(member)] = digest
        archived_sizes[str(member)] = _ordinary(path).st_size
    recipe = sources.get(str(ANALYSIS/'build-observers.sh'))
    if (recipe is None or recipe['sha256'] != _hash(ANALYSIS/'build-observers.sh') or
            receipt.get('recipe_sha256') != _hash(HERE/'build-observer-diagnostic.sh') or
            receipt.get('private_input_recipe_sha256') != _hash(HERE/'observer_private_inputs.py')):
        raise ValueError('Observer recipe differs from reviewed source snapshot')
    # No extraction: every regular tar member must be declared and fully hashed.
    found = set()
    with _read(archive) as archive_stream, tarfile.open(fileobj=archive_stream, mode='r|gz') as snapshot:
        for member in snapshot:
            if len(found) > len(archived)*8+64:
                raise ValueError('Observer source archive has too many members')
            name = str(PurePosixPath(member.name))
            if (PurePosixPath(member.name).is_absolute() or '..' in PurePosixPath(member.name).parts or
                    name != member.name.rstrip('/') or name in found):
                raise ValueError('Ambiguous observer source archive member')
            found.add(name)
            if member.isdir():
                continue
            if not member.isfile() or name not in {*archived, 'source-inputs.json'}:
                raise ValueError('Undeclared observer source archive member')
            stream = snapshot.extractfile(member)
            if name == 'source-inputs.json':
                if member.size > 8*1024**2 or json.loads(stream.read(), object_pairs_hook=_unique_object) != sources:
                    raise ValueError('Archived observer source receipt differs')
            elif (member.size != archived_sizes[name] or
                  hashlib.file_digest(stream, 'sha256').hexdigest() != archived[name]):
                raise ValueError('Archived observer source differs: '+name)
    if not {*archived, 'source-inputs.json'} <= found or _hash(archive) != archive_sha:
        raise ValueError('Observer source archive is incomplete or changed')
    library_manifest = directory/'library-sha256sums'
    if receipt.get('libraries_sha256') != _hash(library_manifest):
        raise ValueError('Observer library provenance differs')
    with _read(library_manifest) as stream:
        raw_libraries = stream.read(8193)
    if len(raw_libraries) > 8192:
        raise ValueError('Observer library provenance exceeds size limit')
    checked_libraries = {}
    for line in raw_libraries.decode('ascii').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise ValueError('Malformed observer library provenance')
        digest, name = match.groups()
        path = Path(name)
        if not path.is_absolute() or path.parent != directory/'lib' or _hash(path) != digest:
            raise ValueError('Observer library provenance differs: '+name)
        if path in checked_libraries:
            raise ValueError('Duplicate observer link-library provenance')
        checked_libraries[path] = digest
    if set(checked_libraries) != {directory/'lib'/name for name in
                             ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')}:
        raise ValueError('Observer link-library provenance is incomplete')
    private_inputs, private_sha = _json(directory/'library-inputs.json')
    if (receipt.get('private_input_receipt_sha256') != private_sha or
            private_inputs.get('schema') != 'a7c2-observer-private-libraries-v1' or
            private_inputs.get('physical_compatible') is not False):
        raise ValueError('Observer private library receipt differs')
    library_rows = private_inputs.get('libraries')
    expected_libraries = {'lib/'+path.name: digest for path,digest in checked_libraries.items()}
    if not isinstance(library_rows,dict) or set(library_rows)!=set(expected_libraries):
        raise ValueError('Observer private library inventory differs')
    for name,digest in expected_libraries.items():
        row=library_rows[name]
        if (not isinstance(row,dict) or row.get('sha256')!=digest or
                row.get('source')!=str(ANALYSIS/'menu-root'/name) or
                row.get('snapshot')!=str(directory/name)):
            raise ValueError('Observer private library identity differs: '+name)
    base = ANALYSIS/'menu-initramfs.cpio'
    with _read(base) as base_stream:
        base_sha = hashlib.file_digest(base_stream,'sha256').hexdigest()
        if private_inputs.get('base_initramfs_sha256') != base_sha:
            raise ValueError('Observer base initramfs changed')
        verify_image(_PinnedImage(base_stream),expected_libraries)
        base_stream.seek(0)
        if hashlib.file_digest(base_stream,'sha256').hexdigest()!=base_sha:
            raise ValueError('Observer base initramfs changed during verification')
    helpers = Path(receipt.get('helpers_reused_from', ''))
    if helpers != ANALYSIS/'menu-root/simulation':
        raise ValueError('Observer helpers must name the authoritative simulation directory')
    for key, name in (('pin_control_probe_sha256', 'pin-control-probe'),
                      ('system_sound_owner_sha256', 'system-sound-owner')):
        if inputs.get(key) != _hash(helpers/name):
            raise ValueError('Observer reused helper differs: '+name)
    final_info = directory.stat(follow_symlinks=False)
    if ((final_info.st_dev, final_info.st_ino, final_info.st_mode, final_info.st_uid) != directory_identity or
            _hash(observer) != observer_sha or _json(directory/'diagnostic-build.json')[1] != receipt_sha or
            _json(directory/'observer-build-inputs.json')[1] != inputs_sha):
        raise ValueError('Isolated observer build changed during validation')
    return dict(build_directory=str(directory), receipt_sha256=receipt_sha,
                source_receipt_sha256=inputs_sha, source_archive_sha256=archive_sha,
                observer_sha256=observer_sha, observer=str(observer), inputs=inputs,
                libraries_sha256=expected_libraries)


def _pair(pair):
    pair = Path(pair)
    if not pair.is_absolute() or '..' in pair.parts or any(p.is_symlink() for p in (pair, *pair.parents)):
        raise ValueError('Native pair must be a canonical non-symlink directory')
    info = pair.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('Native pair must be owned and mode 0700')
    return pair


def _write_receipt(path, result):
    raw = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False)+'\n').encode()
    with ExitStack() as stack:
        _, parent, name, anchors = _parent(stack, path)
        fd = os.open(name, os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600, dir_fd=parent)
        stack.callback(os.close, fd)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError('Short derivative receipt write')
            view = view[written:]
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(fd), 'rb') as stream:
            if stream.read(len(raw)+1) != raw:
                raise ValueError('Derived initramfs receipt readback differs')
        if identity(os.fstat(fd)) != identity(os.stat(name, dir_fd=parent, follow_symlinks=False)):
            raise ValueError('Derived initramfs receipt identity changed')
        _check_anchors(anchors)
        os.fsync(parent)


def _stage_observer(stage, proof):
    source = Path(proof['observer'])
    target = stage/'simulation/menu-observe.so'
    with _read(source) as stream, target.open('xb') as output:
        while block := stream.read(1024**2):
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    if _hash(target) != proof['observer_sha256'] or _hash(source) != proof['observer_sha256']:
        raise ValueError('Staged isolated observer differs')


def prepare_observer(pair, observer_build):
    pair = _pair(pair)
    proof = validate_observer_build(observer_build)
    base = ANALYSIS/'menu-initramfs.cpio'
    base_info = _ordinary(base)
    observer_bytes = _ordinary(Path(proof['observer'])).st_size
    if base_info.st_size+observer_bytes+4096 > INITRD_WINDOW:
        raise ValueError('Derived observer initramfs exceeds the native memory window')
    verify_image(base, {}, forbidden=('simulation/sd-card.fat', 'simulation/sd-card.fat.gz'))
    stage, output, receipt = (pair/name for name in
                             ('observer-overlay', 'observer-initramfs.cpio', 'observer-initramfs.json'))
    if any(os.path.lexists(path) for path in (stage, output, receipt)):
        raise FileExistsError('Observer initramfs artifacts already exist; use a fresh pair')
    available = os.statvfs(pair)
    required = RESERVE+RAM_PEAK+LOG_PEAK+base_info.st_size+2*observer_bytes+4096
    if available.f_frsize <= 0 or available.f_bavail*available.f_frsize < required:
        raise ValueError('Insufficient space for observer initramfs, runtime peak and 64GiB reserve')
    stage.mkdir(mode=0o700)
    (stage/'simulation').mkdir(mode=0o700)
    _stage_observer(stage, proof)
    manifest = build_overlay_initramfs(base, stage, output, space_floor=RESERVE+RAM_PEAK+LOG_PEAK)
    if manifest['output_cpio_bytes'] > INITRD_WINDOW:
        raise ValueError('Derived observer initramfs exceeds the native memory window')
    verify_image(output, {'simulation/menu-observe.so': proof['observer_sha256'], **proof['libraries_sha256']},
                 forbidden=('simulation/sd-card.fat', 'simulation/sd-card.fat.gz'))
    if validate_observer_build(observer_build) != proof:
        raise ValueError('Isolated observer build changed during derivation')
    result = dict(schema='a7c2-native-observer-initramfs-v1', output=str(output),
                  output_sha256=manifest['output_cpio_sha256'], output_bytes=manifest['output_cpio_bytes'],
                  base_sha256=manifest['base_cpio_sha256'], observer_build=proof,
                  original_image_modified=False, physical_devices_used=False,
                  storage_required_bytes=required, storage_available_bytes=available.f_bavail*available.f_frsize)
    _write_receipt(receipt, result)
    return result


def verify_observer_derivative(pair, image, proof, *, capture=False):
    pair = _pair(pair)
    stem = 'capture' if capture else 'observer'
    expected_image = pair/(stem+'-initramfs.cpio')
    if Path(image) != expected_image:
        raise ValueError('Isolated observer requires its pair-owned initramfs')
    receipt, receipt_sha = _json(pair/(stem+'-initramfs.json'))
    if stat.S_IMODE((pair/(stem+'-initramfs.json')).stat().st_mode) != 0o600:
        raise ValueError('Derived observer receipt must have mode 0600')
    info = _ordinary(expected_image)
    schema = 'a7c2-native-capture-initramfs-v2' if capture else 'a7c2-native-observer-initramfs-v1'
    if (receipt.get('schema') != schema or receipt.get('output') != str(expected_image) or
            receipt.get('output_bytes') != info.st_size or info.st_size > INITRD_WINDOW or
            receipt.get('output_sha256') != _hash(expected_image) or
            receipt.get('base_sha256') != _hash(ANALYSIS/'menu-initramfs.cpio') or
            receipt.get('observer_build') != proof or receipt.get('original_image_modified') is not False or
            receipt.get('physical_devices_used') is not False):
        raise ValueError('Derived observer initramfs receipt differs')
    verify_image(expected_image, {'simulation/menu-observe.so': proof['observer_sha256'], **proof['libraries_sha256']},
                 forbidden=() if capture else ('simulation/sd-card.fat', 'simulation/sd-card.fat.gz'))
    return dict(receipt_sha256=receipt_sha, **receipt)


def guest_seed_command(seed_sha256):
    if not isinstance(seed_sha256, str) or not re.fullmatch('[0-9a-f]{64}', seed_sha256):
        raise ValueError('Invalid capture seed digest')
    return ("/bin/busybox gzip -dc /simulation/sd-card.fat.gz > /image_mmca && "
            "test \"$(/bin/busybox wc -c < /image_mmca)\" -eq 1073741824 && "
            "digest=$(/usr/bin/openssl dgst -sha256 /image_mmca) && "
            f"case \"$digest\" in 'SHA256(/image_mmca)= {seed_sha256}'|'SHA2-256(/image_mmca)= {seed_sha256}') "
            f"echo NATIVE_CAPTURE_SEED_READY bytes=1073741824 sha256={seed_sha256}; "
            "echo ready > /tmp/native-capture-seed.ready;; *) false;; esac")


def verify_guest_seed_result(raw, seed_sha256):
    guest_seed_command(seed_sha256)
    if not isinstance(raw, bytes):
        raise ValueError('Guest seed evidence must be bytes')
    marker = f'NATIVE_CAPTURE_SEED_READY bytes=1073741824 sha256={seed_sha256}'.encode()
    if len(re.findall(rb'(?m)^'+re.escape(marker)+rb'\r?$', raw)) != 1:
        raise ValueError('Guest capture seed digest/length marker missing or ambiguous')


def guest_app_ready_command():
    return ('found=0; for c in /proc/[0-9]*/task/[0-9]*/comm; do '
            '[ "$(/bin/busybox cat "$c" 2>/dev/null)" = AppFw ] || continue; '
            'p=${c%/task/*}; /bin/busybox grep -q /usr/lib/appFw.so "$p/maps" 2>/dev/null || continue; '
            'echo NATIVE_CAPTURE_APPFW_PID=${p##*/} TID=${c%/comm}; found=1; done; test "$found" = 1')


def verify_guest_app_ready_result(raw):
    if not isinstance(raw, bytes) or not re.search(
            rb'(?m)^NATIVE_CAPTURE_APPFW_PID=([1-9][0-9]*) TID=/proc/\1/task/[1-9][0-9]*\r?$', raw):
        raise ValueError('Original AppFw process and thread were not observed')


def _fsck_limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (8*1024**2, 8*1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def prepare(pair, observer_build=None):
    pair = _pair(pair)
    observer_proof = validate_observer_build(observer_build) if observer_build is not None else None
    base = ANALYSIS/'menu-initramfs.cpio'
    base_info = base.stat(follow_symlinks=False)
    if not stat.S_ISREG(base_info.st_mode) or base.is_symlink():
        raise ValueError('Original menu initramfs must be an ordinary file')
    verify_image(base, {}, forbidden=('simulation/sd-card.fat', 'simulation/sd-card.fat.gz'))
    available = os.statvfs(pair)
    observer_bytes = _ordinary(Path(observer_proof['observer'])).st_size if observer_proof else 0
    required = RESERVE + RAM_PEAK + LOG_PEAK + base_info.st_size + 2*CARD_BYTES + 2*observer_bytes + 4096
    if available.f_frsize <= 0 or available.f_bavail*available.f_frsize < required:
        raise ValueError('Insufficient space for capture initramfs, runtime peak and 64GiB reserve')
    stage = pair/'capture-overlay'
    output = pair/'capture-initramfs.cpio'
    receipt = pair/'capture-initramfs.json'
    fsck_out, fsck_err = pair/'capture-seed-fsck.stdout.raw', pair/'capture-seed-fsck.stderr.raw'
    if any(os.path.lexists(path) for path in (stage, output, receipt, fsck_out, fsck_err)):
        raise FileExistsError('Capture initramfs artifacts already exist; use a fresh pair')
    source = pair/'capture-seed.img'
    with card_source(source) as fd:
        before = os.fstat(fd)
        if before.st_size != CARD_BYTES or before.st_nlink != 1 or before.st_mode & 0o022:
            raise ValueError('Capture seed must be an owned single-link private 1GiB image')
        reader_path = PRODUCT/'report/capture-evidence/check_evidence.py'
        spec = importlib.util.spec_from_file_location('native_capture_fat16', reader_path)
        reader = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reader)
        with os.fdopen(os.dup(fd), 'rb') as source_image:
            reader.Fat16(source_image, CARD_BYTES)
        source_hash = digest_fd(fd)
        try:
            with fsck_out.open('xb') as out, fsck_err.open('xb') as err:
                checked = subprocess.run(['fsck.fat', '-n', f'/proc/self/fd/{fd}'], pass_fds=(fd,),
                                         stdout=out, stderr=err, timeout=60, check=False,
                                         preexec_fn=_fsck_limits)
                out.flush(); err.flush()
                os.fsync(out.fileno()); os.fsync(err.fileno())
        except subprocess.TimeoutExpired as error:
            raise ValueError('Capture seed fsck.fat timed out; raw logs retained') from error
        fsck_hashes = {}
        for path in (fsck_out, fsck_err):
            with path.open('rb') as log:
                if os.fstat(log.fileno()).st_size > 8*1024**2:
                    raise ValueError('Capture seed fsck output exceeded limit')
                fsck_hashes[path.name] = hashlib.file_digest(log, 'sha256').hexdigest()
        if checked.returncode != 0:
            raise ValueError('Capture seed fsck.fat -n failed')
        stage.mkdir(mode=0o700)
        simulation = stage/'simulation'
        simulation.mkdir(mode=0o700)
        if observer_proof:
            _stage_observer(stage, observer_proof)
        dest = simulation/'sd-card.fat.gz'
        output_fd = os.open(dest, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(os.dup(output_fd), 'wb') as raw_output:
                with gzip.GzipFile(filename='', mode='wb', fileobj=raw_output, compresslevel=1, mtime=0) as compressed:
                    offset = 0
                    while offset < CARD_BYTES:
                        block = os.pread(fd, min(1024**2, CARD_BYTES-offset), offset)
                        if not block:
                            raise ValueError('Capture seed truncated during compression')
                        compressed.write(block)
                        offset += len(block)
                        if offset % (64*1024**2) == 0:
                            remaining = CARD_BYTES-offset + base_info.st_size + CARD_BYTES + observer_bytes + 4096
                            free = os.statvfs(pair)
                            if free.f_frsize <= 0 or free.f_bavail*free.f_frsize < RESERVE+RAM_PEAK+LOG_PEAK+remaining:
                                raise ValueError('Capture seed staging exceeded reserved space budget')
                raw_output.flush()
            os.fsync(output_fd)
        finally:
            os.close(output_fd)
        if identity(before) != identity(os.fstat(fd)) or identity(before) != identity(source.stat(follow_symlinks=False)):
            raise ValueError('Capture seed changed during staging')
        compressed_before = dest.stat(follow_symlinks=False)
        compressed_size = compressed_before.st_size
        compressed_seed_budget = INITRD_WINDOW-base_info.st_size-observer_bytes-4096
        if compressed_size > compressed_seed_budget:
            raise ValueError(
                'Compressed capture seed cannot fit the fixed native initrd memory window: '
                f'gzip_bytes={compressed_size}, seed_budget_bytes={compressed_seed_budget}, '
                f'window_bytes={INITRD_WINDOW}; JPEG-filled cards may be incompressible; '
                'window expansion is forbidden')
        compressed_fd = os.open(dest, os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
        try:
            compressed_info = os.fstat(compressed_fd)
            if (identity(compressed_info) != identity(compressed_before) or
                    not stat.S_ISREG(compressed_info.st_mode) or compressed_info.st_uid != os.geteuid() or
                    compressed_info.st_nlink != 1 or compressed_info.st_mode & 0o022):
                raise ValueError('Compressed capture seed identity differs')
            with os.fdopen(os.dup(compressed_fd), 'rb') as compressed:
                compressed_hash = hashlib.file_digest(compressed, 'sha256').hexdigest()
                compressed.seek(0)
                restored_hash = hashlib.sha256()
                restored_size = 0
                with gzip.GzipFile(fileobj=compressed, mode='rb') as staged:
                    while block := staged.read(1024**2):
                        restored_size += len(block)
                        if restored_size > CARD_BYTES:
                            raise ValueError('Capture seed decompression exceeds expected size')
                        restored_hash.update(block)
            if (identity(compressed_info) != identity(os.fstat(compressed_fd)) or
                    identity(compressed_info) != identity(dest.stat(follow_symlinks=False))):
                raise ValueError('Compressed capture seed changed during readback')
        finally:
            os.close(compressed_fd)
        if restored_size != CARD_BYTES or restored_hash.hexdigest() != source_hash:
            raise ValueError('Compressed capture seed readback differs')
        manifest = build_overlay_initramfs(base, stage, output, space_floor=RESERVE+RAM_PEAK+LOG_PEAK)
        if manifest['output_cpio_bytes'] > INITRD_WINDOW:
            raise ValueError('Derived capture initramfs exceeds the native memory window')
        expected = {'simulation/sd-card.fat.gz': compressed_hash}
        if observer_proof:
            expected['simulation/menu-observe.so'] = observer_proof['observer_sha256']
            expected.update(observer_proof['libraries_sha256'])
            if validate_observer_build(observer_build) != observer_proof:
                raise ValueError('Isolated observer build changed during capture derivation')
        verify_image(output, expected)
        if digest_fd(fd) != source_hash:
            raise ValueError('Capture seed changed during initramfs build')
    result = dict(schema='a7c2-native-capture-initramfs-v2', profile='virtual-native-capture-diagnostic-v1',
                  seed_bytes=CARD_BYTES, seed_sha256=source_hash,
                  compressed_seed_sha256=compressed_hash, compressed_seed_bytes=compressed_size,
                  compressed_seed_budget_bytes=compressed_seed_budget,
                  initrd_window_bytes=INITRD_WINDOW,
                  output=str(output), output_sha256=manifest['output_cpio_sha256'],
                  output_bytes=manifest['output_cpio_bytes'], original_image_modified=False,
                  physical_devices_used=False, capture_verified=False, seed_fsck_rc=checked.returncode,
                  seed_fsck_log_sha256=fsck_hashes,
                  storage_required_bytes=required, storage_available_bytes=available.f_bavail*available.f_frsize,
                  base_sha256=manifest['base_cpio_sha256'], observer_build=observer_proof)
    _write_receipt(receipt, result)
    return result
