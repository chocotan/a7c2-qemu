"""Exec fixture: retain one inherited regular-file OFD until CLOSE, EOF or deadline."""
import fcntl
import os
import select
import stat
import sys
import time


def main():
    if len(sys.argv) != 3:
        return 2
    fd = int(sys.argv[1])
    seconds = int(sys.argv[2])
    if fd <= 2 or not 1 <= seconds <= 10:
        return 2
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or os.pread(fd, 8, 0) != b'82462.00':
            return 2
        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
            return 2
        os.set_blocking(0, False)
        os.set_blocking(1, False)
        deadline = time.monotonic() + seconds
        os.write(1, b'R')
        remaining = max(0, deadline - time.monotonic())
        readable, _, _ = select.select([0], [], [], remaining)
        if not readable:
            os.write(2, b'ofd child protocol deadline expired\n')
            return 124
        if os.read(0, 1) not in (b'C', b''):
            return 2
    finally:
        os.close(fd)
    os.write(1, b'C')
    return 0


if __name__ == '__main__':
    sys.exit(main())
