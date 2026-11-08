"""Stage reversible file tests for the existing raw-initramfs launch path."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import tempfile

from firmware_overlay import _parent, _fd, _signature, _check_anchors, _space, _copy

MAX_FILE_BYTES = 256 * 1024 * 1024


def guest_path(value):
    if (not isinstance(value, str) or not re.fullmatch(r'/(?:usr|bin|lib|etc|sbin)/[A-Za-z0-9_./+-]+', value)
            or any(part in ('.', '..') for part in value.split('/')[1:])
            or str(PurePosixPath(value)) != value):
        raise ValueError('相机目标需要 /usr、/bin、/lib、/etc 或 /sbin 下的普通文件路径')
    return value


def _workspace(base):
    base = Path(base).absolute()
    with ExitStack() as stack:
        path, parent, name, anchors = _parent(stack, base)
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        descriptor = _fd(stack, name, os.O_RDONLY | os.O_DIRECTORY, parent)
        if os.fstat(descriptor).st_uid != os.geteuid():
            raise ValueError('固件测试目录必须属于当前用户')
        _check_anchors(anchors)
    return path


def original_overlay(base):
    """An explicit empty selection also bypasses a populated default overwrite/."""
    return Path(tempfile.mkdtemp(prefix='original-', dir=_workspace(base)))


def stage_file(base, source, destination):
    destination = guest_path(destination)
    base = _workspace(base)
    with ExitStack() as stack:
        path, parent, name, anchors = _parent(stack, source)
        descriptor = _fd(stack, name, os.O_RDONLY | os.O_NONBLOCK, parent)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= MAX_FILE_BYTES:
            raise ValueError('测试源需要不超过 256 MiB 的普通文件')
        target, target_parent, _, target_anchors = _parent(stack, base / 'space-check')
        _space(target_parent, before.st_size)
        folder = Path(tempfile.mkdtemp(prefix='file-', dir=base))
        root = folder / 'root'
        output = root / destination.lstrip('/')
        output.parent.mkdir(parents=True, mode=0o755)
        digest = hashlib.sha256()
        with os.fdopen(os.dup(descriptor), 'rb') as stream, output.open('xb') as staged:
            _copy(stream, staged, before.st_size, digest)
            staged.flush()
            os.fsync(staged.fileno())
        if (_signature(os.fstat(descriptor)) != _signature(before)
                or _signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != _signature(before)):
            raise ValueError('测试源在复制期间变化；未选择本次候选')
        _check_anchors(anchors)
        _check_anchors(target_anchors)
        output.chmod(stat.S_IMODE(before.st_mode) & 0o777)
        with output.open('rb') as stream:
            readback = hashlib.file_digest(stream, 'sha256').hexdigest()
        if readback != digest.hexdigest():
            raise ValueError('暂存文件完整摘要读回不同')
        value = dict(source=str(path), guest_path=destination, bytes=before.st_size,
                     sha256=readback, overlay=str(root), staged_readback_verified=True,
                     guest_readback_verified=False)
        with (folder / 'staging.json').open('x') as stream:
            stream.write(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        return value


def validate_check(request):
    if (not isinstance(request, dict) or set(request) != {'action', 'path', 'bytes', 'sha256'}
            or request['action'] != 'firmware_readback'
            or type(request['bytes']) is not int or not 0 <= request['bytes'] <= MAX_FILE_BYTES
            or not isinstance(request['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', request['sha256'])):
        raise ValueError('无效的固件文件读回请求')
    guest_path(request['path'])
    return request


def readback_command(request):
    validate_check(request)
    path = shlex.quote(request['path'])
    return ("/bin/busybox grep -E '^(Uid|Gid):' /proc/$$/status && "
            '/usr/bin/openssl dgst -sha256 ' + path + ' && /bin/busybox wc -c < ' + path)


def parse_readback(raw, request):
    validate_check(request)
    text = raw.decode('utf-8', errors='replace').replace('\r', '')
    root = all(len(re.findall(r'^' + name + r':[^\n]*$', text, re.M)) == 1
               and re.search(r'^' + name + r':[ \t]*0[ \t]+0[ \t]+0[ \t]+0[ \t]*$', text, re.M) is not None
               for name in ('Uid', 'Gid'))
    hashes = re.findall(r'^(?:SHA256|SHA2-256)\(' + re.escape(request['path']) + r'\)=\s*([0-9a-f]{64})\s*$', text, re.M)
    lengths = re.findall(r'^\s*([0-9]+)\s*$', text, re.M)
    ok = root and hashes == [request['sha256']] and lengths == [str(request['bytes'])]
    return dict(type='firmware_readback', ok=ok, path=request['path'], bytes=request['bytes'],
                sha256=request['sha256'], guest_readback_verified=ok, root_four_zero_fields=root,
                error='' if ok else '原 guest 权限、完整文件摘要或长度读回不匹配')
