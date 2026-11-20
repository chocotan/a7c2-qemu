"""Real AF_UNIX listener fixture; never starts QEMU or sends a signal."""
import json
import os
import socket
import stat
import sys


def main():
    descriptor, device, inode, uid = map(int, sys.argv[1:])
    directory = os.fstat(descriptor)
    if ((directory.st_dev, directory.st_ino, directory.st_uid) != (device, inode, uid) or
            not stat.S_ISDIR(directory.st_mode) or stat.S_IMODE(directory.st_mode) != 0o700 or
            os.geteuid() != uid):
        raise ValueError('socket fixture directory identity changed')
    os.fchdir(descriptor)
    if os.stat('.').st_ino != inode or os.stat('.').st_dev != device:
        raise ValueError('socket fixture cwd identity changed')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind('s')
        listener.listen(1)
        endpoint = os.stat('s', follow_symlinks=False)
        if not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != uid or endpoint.st_nlink != 1:
            raise ValueError('socket fixture endpoint identity changed')
        print(json.dumps([endpoint.st_dev, endpoint.st_ino, endpoint.st_uid,
                          endpoint.st_mode, endpoint.st_nlink]), flush=True)
        # The parent closes stdin to request normal closure, without a signal.
        data = sys.stdin.buffer.read()
        if data != b'':raise ValueError('socket fixture expects EOF')


if __name__ == '__main__':
    main()
