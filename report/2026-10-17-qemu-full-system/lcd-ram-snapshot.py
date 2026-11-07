#!/usr/bin/env python3
"""ram-snapshot-v1: fixed guest-devtmpfs HOSDAP02 transport source overlays.

Main integration, only in an independent runtime/analysis scratch copy:
0. Call validate_pinned(menu) on the selected immutable native analysis directory.
1. After lcd-pipeline/common adapters, write path_header(pinned_header_text) to
   observer output/headless-osd.h. Keep derived headless-osd.c/menu-observe.c
   there; add COMPILE_DEFINE and -I<output> before -I<menu> to their build.
2. Compile viewer_source(lcd-ramfb-stream.c text), copied to the viewer build
   output, with COMPILE_DEFINE and the unchanged pinned include directory.
   An equivalent guarded block after #include "ramfb-viewer.c" is sufficient.
3. Compile BOOTSTRAP_SOURCE with the viewer's guest clang/link flags and original
   libc/loader; stage it at BOOTSTRAP_PROGRAM. Write wrapper_source(selected
   bootin-wrapper text) before rebuilding the initramfs, including both programs.
   Do not stage /dev/qemu-lcd: /dev is mounted devtmpfs at guest boot.
Record receipt() plus both compiled identities, derived wrapper/header/helper
SHA256 and final cpio readback in the main runtime manifest. A single-sided
application is invalid. This module writes nothing and cannot prepare a VM.

The original full metadata/pixel write, fsync return, complete pread comparison,
close/rename, ACK and retained-consumer FD lifecycle are untouched. Directory
setup never mounts a new filesystem, removes a snapshot or releases an active FD.
It binds a fresh RAM diagnostic file onto /tmp/menu-load.log, preserving the
project's existing exact symlink to /log/qemu/menu-load.log when present and
binding that regular target. Every other symlink is rejected; a nonempty target
is preserved and blocks this profile. Normal owner
shutdown after the real ACK remains the caller's responsibility. This changes
simulation transport storage only; no camera settings, NVRAM or SD are involved.
Source/host checks cannot prove guest mount identity or performance: retain the
boot evidence and run the main session's one actual-VM acceptance separately.
"""
import hashlib
from pathlib import Path

PROFILE = 'ram-snapshot-v1'
SNAPSHOT_PATH = '/dev/qemu-lcd/headless-osd-frame.bin'
COMPILE_DEFINE = '-DLCD_RAM_SNAPSHOT_V1=1'
BOOTSTRAP_SOURCE = 'guest/lcd-ram-bootstrap.c'
BOOTSTRAP_PROGRAM = '/simulation/lcd-ram-bootstrap'
BASE_HEADER_SHA256 = 'b408c13cfe820d72a91c98858a0ea86efbffbd5681c8ec4be04774a4c62db4a7'
BASE_PRODUCER_SHA256 = 'e1ccf70c9b903d245becfbb5b2e0dd7b802a54371e54a7f5d6d791061ec87848'
BASE_VIEWER_SHA256 = '56062eaffbf8a967ca47b5ca0d051c1605bf799a84c184cddf56f795fed6b1af'
OLD_PATH_BLOCK = '#ifndef HOSD_PATH\n#define HOSD_PATH "/tmp/headless-osd-frame.bin"\n#endif'
PATH_OVERRIDE = f'#ifdef LCD_RAM_SNAPSHOT_V1\n#undef HOSD_PATH\n#define HOSD_PATH "{SNAPSHOT_PATH}"\n#endif'
VIEWER_INCLUDE = '#include "ramfb-viewer.c"'
VIEWER_LAUNCH = '/simulation/ramfb-viewer >/log/qemu/ramfb-viewer.log 2>&1 &\n'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def validate_pinned(directory):
    """Refuse another native producer/viewer ABI before main emits any overlays."""
    directory = Path(directory)
    for name, expected in (('headless-osd.h', BASE_HEADER_SHA256),
                           ('headless-osd.c', BASE_PRODUCER_SHA256),
                           ('ramfb-viewer.c', BASE_VIEWER_SHA256)):
        path = directory / name
        if (any(parent.is_symlink() for parent in (path, *path.parents)) or
                not path.is_file() or sha256(path.read_bytes()) != expected):
            raise ValueError('ram-snapshot-v1 unknown/linked pinned source SHA256: ' + name)


def path_header(source):
    """Derive only the verified pinned header; profile path is never configurable."""
    if sha256(source.encode()) != BASE_HEADER_SHA256 or source.count(OLD_PATH_BLOCK) != 1:
        raise ValueError('ram-snapshot-v1 unknown pinned headless-osd.h SHA256')
    return source.replace(OLD_PATH_BLOCK,
                          PATH_OVERRIDE + '\n#ifndef LCD_RAM_SNAPSHOT_V1\n' + OLD_PATH_BLOCK + '\n#endif', 1)


def viewer_source(source):
    """Override after the quoted pinned include; -I cannot override that include."""
    if (source.count(VIEWER_INCLUDE) != 1 or source.count('#define RAMFB_TEST\n') != 1 or
            source.count('open(HOSD_PATH, O_RDONLY | O_NONBLOCK | O_NOFOLLOW)') != 1 or
            'LCD_RAM_SNAPSHOT_V1' in source or '#define HOSD_PATH' in source):
        raise ValueError('ram-snapshot-v1 unknown/already-derived stream source anchors')
    return source.replace(VIEWER_INCLUDE, VIEWER_INCLUDE + '\n' + PATH_OVERRIDE, 1)


# The native helper emits the detailed reason and original /proc UID/GID lines.
BOOT_SETUP = '/simulation/lcd-ram-bootstrap || { echo FULLSYSTEM_LCD_RAM_FAILED=bootstrap; exit 1; }\n'


def wrapper_source(source):
    """Insert only in the project adapter, before its existing viewer/AP launch."""
    if (not source.startswith('#!/bin/busybox sh\n') or source.count(VIEWER_LAUNCH) != 1 or
            source.count('export LD_PRELOAD=/simulation/menu-observe.so\n') != 1 or
            'echo FULLSYSTEM_BOOTIN_ENTER\n' not in source or 'ram-snapshot-v1' in source or
            BOOTSTRAP_PROGRAM in source or
            source.index(VIEWER_LAUNCH) > source.index('export LD_PRELOAD=/simulation/menu-observe.so\n')):
        raise ValueError('ram-snapshot-v1 unknown/already-derived bootin wrapper anchors')
    return source.replace(VIEWER_LAUNCH, BOOT_SETUP + VIEWER_LAUNCH, 1)


def receipt():
    """Source contract only; main must append actual build/archive/VM evidence."""
    path_sha = sha256(SNAPSHOT_PATH.encode('ascii'))
    return {
        'profile': PROFILE,
        'producer_path': SNAPSHOT_PATH, 'viewer_path': SNAPSHOT_PATH,
        'producer_path_sha256': path_sha, 'viewer_path_sha256': path_sha,
        'compile_define': COMPILE_DEFINE,
        'bootstrap_program': BOOTSTRAP_PROGRAM,
        'base_header_sha256': BASE_HEADER_SHA256,
        'base_producer_sha256': BASE_PRODUCER_SHA256,
        'base_viewer_sha256': BASE_VIEWER_SHA256,
        'guest_mount': '/dev', 'guest_fstype': 'devtmpfs', 'directory_mode': '0700',
        'boot_evidence': ['FULLSYSTEM_LCD_RAM_ROOT', 'FULLSYSTEM_LCD_RAM_MOUNTINFO',
                          'FULLSYSTEM_LCD_RAM_STAT', 'FULLSYSTEM_LCD_RAM_PROFILE',
                          'FULLSYSTEM_LCD_RAM_LOG_MOUNTINFO', 'FULLSYSTEM_LCD_RAM_LOG_INODE',
                          'FULLSYSTEM_LCD_RAM_LOG_ROUTE'],
        'log_source': '/dev/qemu-lcd/menu-load.log', 'log_target': '/tmp/menu-load.log',
        'log_actual_targets': ['/tmp/menu-load.log', '/log/qemu/menu-load.log'],
        'log_route_policy': 'ordinary logical file or preserved exact known logical symlink; '
                            'bind regular target only; root directory parents and stable readlink checked',
        'log_known_logical_symlink': {'logical': '/tmp/menu-load.log',
                                      'readlink': '/log/qemu/menu-load.log'},
        'log_policy': 'fresh-only: nonempty existing target preserved and profile blocked',
        'mount_added': True, 'diagnostic_file_bind_added': True,
        'new_filesystem_mount_added': False, 'hosdap02_changed': False, 'persist_ack_changed': False,
        'scope': 'paired guest-local simulation transport; no NVRAM or SD writes',
        'vm_executed': False, 'guest_devtmpfs_verified': False, 'performance_verified': False,
    }
