#!/usr/bin/env python3
"""Read-only classification of observed original P1 SPI/PCIDMA prerequisites.

This does not invoke an updater, touch a device, infer a missing event, or verify installation.
"""
import argparse
import json
import os
from pathlib import Path
import stat

MAX_LOG = 64*1024**2
PATTERNS = (
    ('spi_open_failure', 'ERROR: open /dev/spidev0.0 failed.'),
    ('pcidma_module_rejected', 'module=/usr/kmod/pciedma.ko'),
    ('pcidma_open_failure', 'pcidma open error'),
    ('cp_updater_start', 'LOAD CP UPDATER START.'),
    ('link_failure_text', 'link up ng'),
    ('nor_loader_error', 'nor_loader_writer.sh'),
)


def analyze(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_LOG:
        raise ValueError('P1 serial log must be bounded bytes')
    events = []
    for line_number, line in enumerate(raw.decode('utf-8', 'replace').splitlines(), 1):
        for kind, needle in PATTERNS:
            if needle.lower() in line.lower():
                if kind == 'pcidma_module_rejected' and 'UPDATE_MODULE_REJECT' not in line:
                    continue
                if len(events) >= 1024:
                    raise ValueError('P1 event budget exceeded')
                events.append(dict(kind=kind, line=line_number, text=line[:512]))
    kinds = {row['kind'] for row in events}
    return dict(schema='a7c2-p1-transport-frontier-v1', events=events,
                spi_open_failed='spi_open_failure' in kinds,
                pcidma_module_rejected='pcidma_module_rejected' in kinds,
                pcidma_open_failed='pcidma_open_failure' in kinds,
                link_failure_text_observed='link_failure_text' in kinds,
                readiness_query_verified=False, cp_loader_execution_verified=False,
                installation_verified=False, capture_verified=False,
                scope='Observed text only; absence and causal relationships are not inferred')


def read_serial(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Serial log requires an absolute non-symlink path')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                before.st_nlink != 1 or before.st_size > MAX_LOG):
            raise ValueError('Serial log requires an owned single-link bounded regular file')
        data = bytearray()
        while len(data) < before.st_size:
            block = os.read(fd, min(1024**2, before.st_size-len(data)))
            if not block:
                raise ValueError('Serial log truncated during read')
            data.extend(block)
        after = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(named):
            raise ValueError('Serial log changed during read')
        return bytes(data)
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('serial_log', type=Path, help='absolute owned original updater serial log')
    args = parser.parse_args()
    print(json.dumps(analyze(read_serial(args.serial_log)), indent=2))


if __name__ == '__main__':
    main()
