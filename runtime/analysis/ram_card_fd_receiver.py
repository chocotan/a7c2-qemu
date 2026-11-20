#!/usr/bin/env python3
"""Take the leased internal disk descriptor inside the sandbox and start QEMU.

The descriptor arrives over SCM_RIGHTS, so it keeps the owner's open file
description: same inode, same whole-file OFD lock, same lease, same writer.
A bind mount reopens the inode as a different OFD (measured on bwrap 0.13:
independent offset, EAGAIN on the owner's OFD lock, lease break) and is not used.

LOCK is the owner's exact lock from persistent_disk.lease: offset 0, length 1,
which fdinfo reports as "0 0". Re-applying it on the same OFD is a no-op; any
other OFD gets EAGAIN and a whole-file lock would rewrite the owner's claim.
"""
import fcntl
import os
import socket
import stat
import struct
import sys

# struct flock: l_type@0 l_whence@2 l_start@8 l_len@16 l_pid@24, 32 bytes.
LOCK = struct.pack('hh4xqqi4x', fcntl.F_WRLCK, os.SEEK_SET, 0, 1, 0)
if len(LOCK) != 32:
    raise SystemExit('unsupported OFD lock ABI')


def fail(message):
    print('internal disk handoff refused: ' + message, file=sys.stderr)
    raise SystemExit(2)


def receive(endpoint):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    try:
        client.connect(endpoint)
        _, ancillary, _, _ = client.recvmsg(1, socket.CMSG_SPACE(4 * 4))
        client.send(b'1')
    except OSError as error:
        fail('descriptor broker unreachable: ' + str(error))
    finally:
        client.close()
    received = [struct.unpack('%di' % (len(data) // 4), data)
                for level, kind, data in ancillary
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS]
    if len(received) != 1 or len(received[0]) != 1:
        fail('handoff must carry exactly one descriptor')
    return received[0][0]


def main(arguments):
    if len(arguments) < 7 or arguments[5] != '--':
        fail('usage: <socket> <fd> <dev> <ino> <library-path> -- <command...>')
    endpoint, number, device, inode, library_path = arguments[:5]
    for value in (number, device, inode):
        if not value.isascii() or not value.isdigit():
            fail('numeric handoff argument expected')
    target = int(number)
    if target < 3:
        fail('internal disk descriptor must be inherited and >=3')
    fd = receive(endpoint)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (int(device), int(inode)):
        fail('received descriptor is not the leased internal disk')
    if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
        fail('received descriptor is not the leased read/write disk')
    try:
        # Only the owner's own OFD can re-apply this exact lock without conflict.
        fcntl.fcntl(fd, fcntl.F_OFD_SETLK, LOCK)
    except OSError:
        fail('received descriptor does not hold the owner OFD lock')
    if fd != target:
        os.dup2(fd, target)
        os.close(fd)
    os.set_inheritable(target, True)
    if library_path:
        os.environ['LD_LIBRARY_PATH'] = library_path
    else:  # Never hand QEMU an empty search entry, which means the current directory.
        os.environ.pop('LD_LIBRARY_PATH', None)
    os.execv(arguments[6], arguments[6:])


if __name__ == '__main__':
    main(sys.argv[1:])
