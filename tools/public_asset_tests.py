"""Skip reads of explicitly excluded, absent original inputs in public tests only.

Present, linked or corrupt inputs still reach the original validation. Missing
ordinary source/build dependencies are not converted into skips.
"""
from pathlib import Path
import os

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = frozenset({
    'runtime/analysis/menu-root/seed-backup.bin',
    'runtime/analysis/menu-root/usr/kmod/upm.ko',
    'runtime/analysis/menu-root/usr/kmod/osal_uipc.ko',
    *{'runtime/analysis/menu-root/' + name for name in (
        'lib/libc-2.25.so', 'lib/libdl-2.25.so', 'lib/libpthread-2.25.so', 'lib/ld-2.25.so',
        'usr/lib/libmpr.so', 'usr/lib/appFw.so', 'cp/cpapp-b.bin',
        'system/av-cam.bin', 'usr/codec/vcd_firmware_imola2.bin')},
    'runtime/analysis/menu-runs/run-4gqygshc/console.log',
})


@pytest.fixture(autouse=True, scope='session')
def absent_original_inputs():
    original = Path.open
    def checked(path, mode='r', *args, **kwargs):
        if not any(flag in mode for flag in 'wax+'):
            absolute = Path(os.path.abspath(path))
            if absolute.is_relative_to(ROOT):
                name = absolute.relative_to(ROOT).as_posix()
                if name in EXTERNAL and not path.exists() and not path.is_symlink():
                    pytest.skip('excluded external input is absent: ' + name)
        return original(path, mode, *args, **kwargs)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, 'open', checked)
        yield
