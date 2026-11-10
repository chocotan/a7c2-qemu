"""Virtual loader route/model tests on synthetic partition images; no VM, no assets."""
from pathlib import Path
import hashlib
import io
import os
import stat
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor/fwtool-sdk'))
from fwtool.archive.fat import readFat, writeFat

import virtual_loader


class _File:
    def __init__(self, path, data):
        self.path = path
        self.mode = stat.S_IFREG | 0o644
        self.size = len(data)
        self.mtime = 0
        self.contents = io.BytesIO(data)


def _synthetic_disk(updater=None, wbi2=False, kernel=b'kernel-bytes', ram0=b'ram0-bytes'):
    p2_files = [_File('/updater/mode', updater)] if updater is not None else []
    p3_files = [_File('/vmlinux.bin', kernel), _File('/initrd.img', ram0)]
    images = []
    for files, size in ((p2_files, 512 * 1024), (p3_files, 1024 * 1024)):
        buffer = io.BytesIO()
        writeFat(files, size, buffer)
        images.append(buffer.getvalue())
    images.append((b'WBI2' + b'\0' * 508) if wbi2 else b'\0' * 512)
    offsets = []
    cursor = 0
    for image in images:
        offsets.append(cursor)
        cursor += len(image)
    blob = b''.join(images)
    fd, path = tempfile.mkstemp(prefix='virtual-loader-test-')
    os.write(fd, blob)
    os.lseek(fd, 0, os.SEEK_SET)
    geometry = dict(slices=[
        dict(id='nflasha2', offset=offsets[0], bytes=len(images[0])),
        dict(id='nflasha3', offset=offsets[1], bytes=len(images[1])),
        dict(id='nflasha5', offset=offsets[2], bytes=len(images[2])),
    ])
    return fd, path, geometry


def _close(fd, path):
    os.close(fd)
    os.unlink(path)


def test_default_disk_selects_cold_and_reads_assets():
    fd, path, geometry = _synthetic_disk()
    try:
        decision = virtual_loader.evaluate_fd(fd, geometry)
        assert decision['route'] == dict(status='selected', mode=1, event='default', missing=[])
        assert decision['resolve']['path'] == 'cold'
        assert decision['disk_inputs'] == dict(updater_mode_present=False, updater_mode_content=None,
                                               wbi2_magic=False)
        plan = virtual_loader.boot_plan.__wrapped__ if hasattr(virtual_loader.boot_plan, '__wrapped__') else None
        assets = virtual_loader.cold_boot_assets_fd(fd, geometry,
            kernel_sha256=hashlib.sha256(b'kernel-bytes').hexdigest(),
            ram0_sha256=hashlib.sha256(b'ram0-bytes').hexdigest())
        assert assets['/vmlinux.bin']['identity_matches'] and assets['/initrd.img']['identity_matches']
        assert assets['/vmlinux.bin']['bytes'] == len(b'kernel-bytes')
    finally:
        _close(fd, path)


def test_updater_mode_file_selects_mode3_and_backend_is_explicit():
    fd, path, geometry = _synthetic_disk(updater=b'1\n')
    try:
        decision = virtual_loader.evaluate_fd(fd, geometry)
        assert decision['route']['status'] == 'selected' and decision['route']['mode'] == 3
        assert decision['route']['event'] == 'updater'
        assert decision['disk_inputs']['updater_mode_present'] is True
        assert decision['disk_inputs']['updater_mode_content'] == '1'
    finally:
        _close(fd, path)


def test_wbi2_magic_selects_ssboot_route():
    fd, path, geometry = _synthetic_disk(wbi2=True)
    try:
        decision = virtual_loader.evaluate_fd(fd, geometry)
        assert decision['route']['status'] == 'selected' and decision['route']['mode'] == 11
        assert decision['route']['event'] == 'ssboot'
        assert decision['resolve']['path'] == 'wbi-resume'
        assert decision['disk_inputs']['wbi2_magic'] is True
    finally:
        _close(fd, path)


def test_cold_assets_report_mismatched_identity_after_an_update():
    fd, path, geometry = _synthetic_disk(kernel=b'new-kernel-after-update')
    try:
        assets = virtual_loader.cold_boot_assets_fd(fd, geometry,
            kernel_sha256=hashlib.sha256(b'old-kernel').hexdigest(),
            ram0_sha256=hashlib.sha256(b'ram0-bytes').hexdigest())
        assert assets['/vmlinux.bin']['identity_matches'] is False
        assert assets['/initrd.img']['identity_matches'] is True
    finally:
        _close(fd, path)


def test_receipt_roundtrip(tmp_path):
    fd, path, geometry = _synthetic_disk()
    try:
        import json
        decision = virtual_loader.evaluate_fd(fd, geometry)
        receipt = virtual_loader.save_receipt(tmp_path, decision)
        assert json.loads(receipt.read_text()) == decision
        assert decision['schema'] == 'a7c2-virtual-loader-v1'
        assert decision['profile'] == 'virtual-b0-loader-functional-v1'
        assert decision['physical_bootrom_compatible'] is False
    finally:
        _close(fd, path)
