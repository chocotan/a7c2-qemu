#!/usr/bin/env python3
"""Start an isolated original-AP diagnostic against a separately running CP.

This selects the original IPC modules, not a software CP service. It is a
headless bootin diagnostic; full official boot-chain equivalence stays false.
"""
import argparse
import os
from pathlib import Path
import runpy
import socket
import stat
import struct
import sys

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[1]


def api():
    return runpy.run_path(str(HERE/'native-link.py'))


def plan(pair, binary, seconds, virtual_upm=False, capture_diagnostic=False, control_fd=None,
         p1_spi_component=False, observer_build=None):
    if (type(virtual_upm) is not bool or type(capture_diagnostic) is not bool or
            type(p1_spi_component) is not bool):
        raise ValueError('Diagnostic selections must be boolean')
    if not capture_diagnostic and control_fd is not None:
        raise ValueError('Control socket is only accepted for capture diagnostic')
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError('AP observation seconds must be an integer in 1..3600')
    helpers = api()
    proof = helpers['admit'](pair, binary)
    observer_proof = None
    if observer_build is not None:
        observer_proof = runpy.run_path(str(HERE/'capture_initramfs.py'))['validate_observer_build'](observer_build)
    pair, binary = Path(pair).resolve(strict=True), Path(binary).resolve(strict=True)
    environment = {name:value for name,value in os.environ.items()
                   if not name.startswith(('MENU_', 'QEMU_', 'A7C2_', 'SONY_'))}
    environment.update(helpers['environment']('ap', pair))
    environment.update(QEMU_SYSTEM_DIR=str(binary.parent), QEMU_SYSTEM_BINARY=binary.name,
                       QEMU_UI_LIVE='1', QEMU_TIMEOUT_SECONDS='0', MENU_PCIE_IF='1',
                       MENU_SETTLE_SECONDS=str(seconds), MENU_DIAG_TIMEOUT='120')
    if observer_proof:
        environment['A7C2_NATIVE_OBSERVER_BUILD'] = observer_proof['build_directory']
    if virtual_upm:
        environment['MENU_VIRTUAL_UPM_PROFILE'] = 'diagnostic-v1'
    if p1_spi_component:
        environment['QEMU_NATIVE_P1_SPI_COMPONENT'] = 'virtual-p1-pl022-component-v1'
    if capture_diagnostic:
        if type(control_fd) is not int or control_fd < 3:
            raise ValueError('Capture diagnostic requires an inherited control socket')
        if not stat.S_ISSOCK(os.fstat(control_fd).st_mode) or not os.get_inheritable(control_fd):
            raise ValueError('Capture control must be an inheritable socket')
        with socket.fromfd(control_fd, socket.AF_UNIX, socket.SOCK_STREAM) as control:
            if (control.getsockopt(socket.SOL_SOCKET, socket.SO_DOMAIN) != socket.AF_UNIX or
                    control.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM):
                raise ValueError('Capture control must be a Unix stream socket')
            peer_pid, peer_uid, _ = struct.unpack('3i', control.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        if peer_uid != os.geteuid() or peer_pid != os.getppid():
            raise ValueError('Capture control peer must be the same-UID parent')
        card = pair/'capture-seed.img'
        try:
            info = card.lstat()
        except FileNotFoundError as error:
            raise ValueError('Capture diagnostic requires pair/capture-seed.img') from error
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1 or
                info.st_mode & 0o022 or info.st_size != 1024**3):
            raise ValueError('Capture diagnostic requires the owned 1GiB pair/capture-seed.img')
        environment.update(MENU_NATIVE_CAPTURE_DIAGNOSTIC='1', MENU_RM_FILE='1',
                           MENU_CONTROL_FD=str(control_fd), MENU_CONTROL_OWNER_PID=str(peer_pid),
                           MENU_LIVE_APP_INPUT='1',
                           MENU_JPEG_REQUEST_TRACE='1', A7C2_FSYS_ASYNC_OBSERVE='1',
                           A7C2_SD_IMAGE=str(card))
    command = [sys.executable, '-B', str(PRODUCT/'runtime/analysis/qemu-menu-probe.py'),
               '--initramfs', '--load-ipc', '--load-dmm', '--sony-timers', '--observe',
               '--bootin', '--bootall', '--seed-backup', '--load-kikilog', '--seed-power-on']
    return command, environment, proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair', required=True, type=Path)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--seconds', default=240, type=int)
    parser.add_argument('--virtual-upm-diagnostic', action='store_true',
                        help='Enable virtual UPM/BT diagnostic fixture; not physical behaviour')
    parser.add_argument('--capture-diagnostic', action='store_true',
                        help='Observe capture with the owned pair/capture-seed.img; no synthetic capture replies')
    parser.add_argument('--control-fd', type=int, help='Inherited parent-owned Unix stream socket')
    parser.add_argument('--p1-spi-component', action='store_true',
                        help='Expose upstream PL022 only; no SPI loader or peer is supplied')
    parser.add_argument('--observer-build', type=Path,
                        help='Opt in to a verified isolated observer below source/build; derive only inside this pair')
    args = parser.parse_args()
    os.umask(0o077)
    command, environment, _ = plan(args.pair, args.binary, args.seconds,
                                   args.virtual_upm_diagnostic, args.capture_diagnostic, args.control_fd,
                                   args.p1_spi_component, args.observer_build)
    pair = args.pair.resolve(strict=True)
    binary = args.binary.resolve(strict=True)
    if args.capture_diagnostic:
        runpy.run_path(str(HERE/'capture_initramfs.py'))['prepare'](pair, args.observer_build)
    elif args.observer_build is not None:
        runpy.run_path(str(HERE/'capture_initramfs.py'))['prepare_observer'](pair, args.observer_build)
    api()['create_ap_admission_claim'](pair, binary, command)
    # The exclusive claim now binds this PID generation before exec preserves the PID.
    os.execve(sys.executable, command, environment)


if __name__ == '__main__':
    main()
