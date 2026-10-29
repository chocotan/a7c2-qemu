import fcntl
import os
from pathlib import Path
import subprocess

import pytest

from directory_sd import directory_lease, TOTAL, TOTAL_SECTORS
from directory_sd_profile import prepare_profile

BASE = Path(__file__).resolve().parent


def test_pinned_directory_profile_and_real_sandbox_binding(tmp_path):
    card = tmp_path/'card'
    with directory_lease(card) as lease:
        assert lease['bytes'] == TOTAL == 256000000000 and lease['total_sectors'] == TOTAL_SECTORS
        assert os.fstat(lease['fd']).st_mode & 0o022 == 0
        with pytest.raises(BlockingIOError):
            with directory_lease(card):
                pass
        profile = prepare_profile(BASE, lease, tmp_path/'profiles')
        script = Path(profile['MENU_KERNEL_SCRIPT'])
        text = script.read_text()
        assert f'--bind-fd {lease["fd"]} /sd' in text
        assert 'driver=vvfat' in text and 'total-sectors=500000000' in text
        assert 'fat-type=32' in text and 'rw=on' in text and 'usb-host' not in text
        assert str(card) not in text and profile['A7C2_DIRECTORY_SD_PROFILE'] == 'directory-vvfat-256gb-v1'
        subprocess.run(['bash','-n',str(script)],check=True)
        (card/'input.bin').write_bytes(b'host-directory-input')
        result = subprocess.run(['bwrap','--unshare-all','--die-with-parent',
            '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64',
            '--proc','/proc','--dev','/dev','--dir','/sd','--bind-fd',str(lease['fd']),'/sd',
            '--','/usr/bin/cat','/sd/input.bin'],pass_fds=(lease['fd'],),capture_output=True,timeout=10)
        assert result.returncode == 0 and result.stdout == b'host-directory-input'
        with pytest.raises(ValueError,match='pinned'):
            prepare_profile(BASE,{**lease,'inode':lease['inode']+1},tmp_path/'bad')


def test_symlink_and_foreign_directory_are_rejected(tmp_path):
    target = tmp_path/'target';target.mkdir()
    link = tmp_path/'link';link.symlink_to(target, target_is_directory=True)
    with pytest.raises((OSError,ValueError)):
        with directory_lease(link):
            pass
    root = tmp_path/'foreign';root.mkdir()
    root.chmod(0o777)
    with pytest.raises(ValueError,match='owned'):
        with directory_lease(root):
            pass


def test_patch_is_pinned_to_original_vvfat_and_explicit_256gb():
    import hashlib,json,tarfile
    native = BASE.parents[1]
    manifest = json.loads((native/'source/qemu-directory-sd.json').read_text())
    patch = native/'source/qemu-directory-sd.patch'
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == manifest['patch_sha256']
    assert manifest['fixed_profile'] == {'fat_type':32,'total_sectors':500000000,
                                       'bytes':256000000000,'logical_sector_bytes':512}
    with tarfile.open(native/'source/vendor/qemu-11.1.2.tar.xz') as archive:
        original = archive.extractfile('qemu-11.1.2/block/vvfat.c').read()
        original_qapi = archive.extractfile('qemu-11.1.2/qapi/block-core.json').read()
    assert hashlib.sha256(original).hexdigest() == manifest['source_files']['block/vvfat.c']['before']
    assert hashlib.sha256(original_qapi).hexdigest() == manifest['source_files']['qapi/block-core.json']['before']
    work = native/'source'/manifest['work_file']
    assert hashlib.sha256(work.read_bytes()).hexdigest() == manifest['source_files']['block/vvfat.c']['after']
    text = patch.read_text()
    for required in ('total-sectors','first_cluster_of_root_dir','vvfat_co_flush_to_disk',
                     'check_directory_consistency','g_utf8_validate','lstat','ftruncate',
                     'array_insert does not initialize','array_insert leaves the new range',
                     'unreferenced_page_padding','strict allocated prefix',
                     'DLOG(warn_report("vvfat: consistency still','host directory commit pending'):
        assert required in text
    assert 'usb-host' not in text
    build = (native/'build-qemu.sh').read_text()
    assert '--enable-vvfat --enable-qcow1' in build
