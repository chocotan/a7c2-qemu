"""Shared VM admission: pidfd wait, no foreign process termination."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import select
import time


def camera_pids():
    found = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            argv = (directory/'cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if argv and (b'qemu-system-aarch64' in argv[0] or any(
                item.endswith((b'/check-natural-gtk-input.py', b'/run-full-system.py'))
                for item in argv[1:3])):
            found.append(int(directory.name))
    return found


def wait_foreign():
    deadline = time.monotonic()+1800
    while True:
        pids = camera_pids()
        if not pids:
            return
        handles = []
        try:
            for pid in pids:
                try:
                    handles.append(os.pidfd_open(pid))
                except ProcessLookupError:
                    continue
            if not handles:
                continue
            print('WAIT_FOREIGN_CAMERA_VMS', len(handles), flush=True)
            poller = select.poll()
            for descriptor in handles:
                poller.register(descriptor, select.POLLIN)
            remaining = set(handles)
            while remaining:
                events = poller.poll(max(0, int((deadline-time.monotonic())*1000)))
                if not events:
                    raise TimeoutError('foreign VM still running after total30min')
                remaining.difference_update(descriptor for descriptor, _ in events)
        finally:
            for descriptor in handles:
                os.close(descriptor)


@contextmanager
def idle_lock(lock_path):
    with Path(lock_path).open('a') as lock:
        while True:
            wait_foreign()
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not camera_pids():
                break
            fcntl.flock(lock, fcntl.LOCK_UN)
        try:
            yield lock
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
