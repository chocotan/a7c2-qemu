#!/usr/bin/env python3
"""Derive a receiver for explicitly selected, isolated QEMU development updates.

    receipt = derive_receiver(source, output)

output's parent must already exist; output must not exist. Only the pinned Sony
2.01 AArch64 receiver is accepted. This changes one RSA_verify call into
``mov w0, #1`` in a fresh copy, retaining all other bytes, including the following
comparison/branch, key loading, decryption, CRC, length/bounds and other errors.
It does not change the SDK verifier, an original dump or a firmware package.

The caller may use this copy only for the UI's explicit development update test
selection ("开发更新测试"). Official start must continue to use the original.
This module neither selects a profile nor launches/contacts a VM or device.
The returned receipt is an offline manifest: bypass_executed stays False until
separate QMP/observer evidence proves execution at the patched PC. Do not infer
execution, acceptance of an update, or physical ASIC compatibility from it.

Run host checks with: python3 test-dev-update-profile.py
"""
from contextlib import ExitStack
import fcntl
import hashlib
import io
import os
from pathlib import Path
import stat

from elftools.elf.elffile import ELFFile

MODE = 'virtual-dev-sd-update-v1'
# Tests replace only these internal identity facts for synthetic ELF fixtures.
_SOURCE_FACTS = {
    'sha256': '1a6a3226993ce7c25659bd58e20871d91869083b31440650eec555a06d592d2f',
    'size': 60600,
}
_PATCH_VA = 0xae08
_PATCH_OFFSET = 0xae08
_ORIGINAL = bytes.fromhex('72f1ff97')
_REPLACEMENT = bytes.fromhex('20008052')
_FOLLOWING = bytes.fromhex('1f04007140010054')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _path(value):
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or any(p in ('.', '..') for p in raw.split('/')):
        raise ValueError('Expected a nonempty host path without dot components')
    return Path(raw).absolute()  # Never resolve away symlinks before checking.


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_nlink)


def _inode(info):
    return info.st_dev, info.st_ino


def _open_directory(path):
    """Walk directory descriptors; reject symlinks in every component."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _verify_directory(path, fd):
    current = _open_directory(path)
    try:
        if _inode(os.fstat(current)) != _inode(os.fstat(fd)):
            raise ValueError('Parent directory changed: ' + str(path))
    finally:
        os.close(current)


def _read(fd, size):
    data = bytearray()
    while len(data) < size:
        chunk = os.pread(fd, min(1024 * 1024, size - len(data)), len(data))
        if not chunk:
            raise OSError('Short receiver read')
        data.extend(chunk)
    if os.pread(fd, 1, size):
        raise ValueError('Receiver grew while reading')
    return bytes(data)


def _verify_source(path, parent, fd, original_info, expected_hash):
    _verify_directory(path.parent, parent)
    for info in (os.fstat(fd), os.stat(path.name, dir_fd=parent, follow_symlinks=False)):
        if _identity(info) != _identity(original_info):
            raise ValueError('Source identity/metadata changed')
    digest = _sha(_read(fd, original_info.st_size))
    if digest != expected_hash:
        raise ValueError('Source hash changed')
    for info in (os.fstat(fd), os.stat(path.name, dir_fd=parent, follow_symlinks=False)):
        if _identity(info) != _identity(original_info):
            raise ValueError('Source changed during verification')
    return digest


def _validate_receiver(data):
    elf = ELFFile(io.BytesIO(data))
    if (elf.elfclass != 64 or not elf.little_endian
            or elf.header['e_machine'] != 'EM_AARCH64' or elf.header['e_type'] != 'ET_DYN'):
        raise ValueError('Expected little-endian AArch64 ELF64 shared library')
    end = _PATCH_VA + len(_ORIGINAL) + len(_FOLLOWING)
    loads = []
    for index, segment in enumerate(elf.iter_segments()):
        if segment['p_type'] != 'PT_LOAD':
            continue
        offset, va = segment['p_offset'], segment['p_vaddr']
        filesz, memsz, align = segment['p_filesz'], segment['p_memsz'], segment['p_align']
        if (filesz > memsz or offset + filesz > len(data) or va + memsz > 2**64
                or (align > 1 and (align & (align - 1) or va % align != offset % align))):
            raise ValueError('Invalid PT_LOAD file/memory/alignment bounds')
        if va < end and va + memsz > _PATCH_VA:
            loads.append((index, segment))
    if len(loads) != 1:
        raise ValueError('Patch VA must map to exactly one PT_LOAD')
    index, segment = loads[0]
    va, offset, filesz = segment['p_vaddr'], segment['p_offset'], segment['p_filesz']
    if not segment['p_flags'] & 1 or not va <= _PATCH_VA or end > va + filesz:
        raise ValueError('Patch and following instructions must be file-backed executable PT_LOAD bytes')
    actual_offset = offset + _PATCH_VA - va
    if actual_offset != _PATCH_OFFSET or actual_offset % 4:
        raise ValueError('Unexpected patch VA/file offset mapping')
    if data[actual_offset:actual_offset + 4] != _ORIGINAL:
        raise ValueError('Expected original RSA_verify BL; patched/unknown receiver refused')
    if data[actual_offset + 4:actual_offset + 12] != _FOLLOWING:
        raise ValueError('Unexpected original cmp w0, #1 / b.eq instructions')
    return {'index': index, 'file_offset': offset, 'virtual_address': va,
            'file_size': filesz, 'memory_size': segment['p_memsz'], 'flags': segment['p_flags']}


def _check_diff(before, after):
    if (len(before) != len(after) or before[:_PATCH_OFFSET] != after[:_PATCH_OFFSET]
            or before[_PATCH_OFFSET + 4:] != after[_PATCH_OFFSET + 4:]
            or before[_PATCH_OFFSET:_PATCH_OFFSET + 4] != _ORIGINAL
            or after[_PATCH_OFFSET:_PATCH_OFFSET + 4] != _REPLACEMENT):
        raise ValueError('Full receiver diff must contain only the prescribed four-byte patch')


def _write(fd, data):
    view = memoryview(data)
    while view:
        count = os.write(fd, view)
        if count <= 0:
            raise OSError('Zero receiver write')
        view = view[count:]


def verify_derived_receiver(path, receipt):
    """Read back an installed copy; reconstruct and hash the exact pinned original."""
    path = _path(path)
    parent = _open_directory(path.parent)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size != _SOURCE_FACTS['size']:
                raise ValueError('Derived receiver size/type differs')
            after = _read(fd, info.st_size)
            before = after[:_PATCH_OFFSET] + _ORIGINAL + after[_PATCH_OFFSET + 4:]
            if _sha(before) != _SOURCE_FACTS['sha256']:
                raise ValueError('Derived receiver differs outside the prescribed four-byte patch')
            load = _validate_receiver(before)
            _check_diff(before, after)
            if (receipt.get('schema') != 'a7c2-dev-update-receiver-v1' or receipt.get('mode') != MODE
                    or receipt.get('virtual_only') is not True or receipt.get('bypass_configured') is not True
                    or receipt.get('bypass_executed') is not False
                    or receipt.get('source', {}).get('sha256_before') != _sha(before)
                    or receipt.get('source', {}).get('sha256_after') != _sha(before)
                    or receipt.get('source', {}).get('size') != len(before)
                    or receipt.get('source', {}).get('unchanged') is not True
                    or receipt.get('output', {}).get('sha256') != _sha(after)
                    or receipt.get('output', {}).get('size') != len(after)):
                raise ValueError('Derived receiver receipt identity/policy differs')
            patch = receipt.get('patch', {})
            for key, expected in dict(virtual_address=_PATCH_VA, file_offset=_PATCH_OFFSET, length=4,
                    original_hex=_ORIGINAL.hex(), replacement_hex=_REPLACEMENT.hex(),
                    following_original_hex=_FOLLOWING.hex(),
                    changed_file_offsets=list(range(_PATCH_OFFSET, _PATCH_OFFSET + 4)),
                    executable_load=load).items():
                if patch.get(key) != expected:
                    raise ValueError('Derived receiver patch receipt differs: ' + key)
            _verify_source(path, parent, fd, info, _sha(after))
            return dict(schema='a7c2-dev-receiver-readback-v1', mode=MODE, bytes=len(after),
                        sha256=_sha(after), original_sha256=_sha(before), patch_bytes=4,
                        all_other_bytes_identical=True, bypass_executed=False)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def derive_receiver(source, output, *, mode=MODE):
    """Return a JSON-serializable offline receipt; reject unknown/physical modes.

    Validation failures raise ValueError (or an ELF parsing error); filesystem
    failures raise OSError. Never overwrite a target. After a failed derivation,
    remove only the output inode created here, leaving any replacement untouched.
    No production argument/environment variable can supply alternate source facts.
    """
    if mode != MODE:
        raise ValueError('Only ' + MODE + ' is supported')
    source, output = _path(source), _path(output)
    if source == output:
        raise ValueError('Source/output alias refused')
    with ExitStack() as stack:
        source_parent = _open_directory(source.parent)
        stack.callback(os.close, source_parent)
        output_parent = _open_directory(output.parent)
        stack.callback(os.close, output_parent)
        initial = os.stat(source.name, dir_fd=source_parent, follow_symlinks=False)
        if not stat.S_ISREG(initial.st_mode) or initial.st_size != _SOURCE_FACTS['size']:
            raise ValueError('Expected original, nonempty regular receiver with pinned size')
        src = os.open(source.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                      dir_fd=source_parent)
        stack.callback(os.close, src)
        fcntl.flock(src, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if _identity(os.fstat(src)) != _identity(initial):
            raise ValueError('Source changed while opening')
        before = _read(src, initial.st_size)
        before_hash = _sha(before)
        if before_hash != _SOURCE_FACTS['sha256']:
            raise ValueError('Unrecognized receiver SHA-256; only the pinned original is accepted')
        executable_load = _validate_receiver(before)
        _verify_source(source, source_parent, src, initial, before_hash)
        _verify_directory(output.parent, output_parent)
        expected = before[:_PATCH_OFFSET] + _REPLACEMENT + before[_PATCH_OFFSET + 4:]
        _check_diff(before, expected)
        dst = os.open(output.name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW
                      | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=output_parent)
        stack.callback(os.close, dst)
        created = os.fstat(dst)
        try:
            if (not stat.S_ISREG(created.st_mode) or created.st_nlink != 1
                    or _inode(created) == _inode(initial)):
                raise ValueError('Output must be a fresh regular file with an independent inode')
            fcntl.flock(dst, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _write(dst, expected)
            os.fsync(dst)
            written_info = os.fstat(dst)
            actual = _read(dst, len(expected))
            _check_diff(before, actual)
            after_hash = _sha(actual)
            source_after_hash = _verify_source(source, source_parent, src, initial, before_hash)
            _verify_directory(output.parent, output_parent)
            for info in (os.fstat(dst), os.stat(output.name, dir_fd=output_parent, follow_symlinks=False)):
                if _identity(info) != _identity(written_info) or info.st_nlink != 1:
                    raise ValueError('Output changed during derivation')
            os.fsync(output_parent)
            return {
                'schema': 'a7c2-dev-update-receiver-v1', 'mode': mode,
                'virtual_only': True, 'bypass_configured': True, 'bypass_executed': False,
                'stock_signature_verification_preserved_on_original': True,
                'requires_explicit_selection': True, 'default_official_start_applies': False,
                'guest_execution_verified': False,
                'execution_evidence_required': ['QMP/observer evidence of patched PC execution'],
                'source': {'path': str(source), 'size': len(before),
                           'sha256_before': before_hash, 'sha256_after': source_after_hash,
                           'unchanged': True, 'device': initial.st_dev, 'inode': initial.st_ino},
                'output': {'path': str(output), 'size': len(actual), 'sha256': after_hash,
                           'device': written_info.st_dev, 'inode': written_info.st_ino,
                           'fresh_regular_file': True, 'independent_inode': True},
                'patch': {'virtual_address': _PATCH_VA, 'file_offset': _PATCH_OFFSET, 'length': 4,
                          'original_hex': _ORIGINAL.hex(), 'replacement_hex': _REPLACEMENT.hex(),
                          'original_instruction': 'bl RSA_verify@plt',
                          'replacement_instruction': 'mov w0, #1',
                          'following_original_hex': _FOLLOWING.hex(),
                          'changed_file_offsets': list(range(_PATCH_OFFSET, _PATCH_OFFSET + 4)),
                          'executable_load': executable_load},
                'unchanged_checks': ['key_loading', 'decryption', 'CRC', 'length', 'bounds',
                                     'all_other_error_paths'],
                'scope': 'offline derivation only; other checks preserved by exact byte comparison',
            }
        except BaseException as error:
            try:
                current = os.stat(output.name, dir_fd=output_parent, follow_symlinks=False)
                if _inode(current) == _inode(created):
                    os.unlink(output.name, dir_fd=output_parent)
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                error.add_note('Could not remove own failed output: ' + str(cleanup_error))
            raise
