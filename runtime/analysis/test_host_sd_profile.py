import os
from pathlib import Path
import subprocess
import pytest

from host_sd import card_lease, TOTAL
from host_sd_profile import prepare_profile

BASE=Path(__file__).resolve().parent


def test_profile_binds_only_pinned_file_and_uses_virtual_storage(tmp_path):
    card=tmp_path/'card';card.mkdir(mode=0o700)
    with card_lease(card) as lease:
        profile=prepare_profile(BASE,lease,tmp_path/'profiles')
        script=Path(profile['MENU_KERNEL_SCRIPT'])
        text=script.read_text()
        assert f'--bind-fd {lease["fd"]} /sd/card.img' in text
        assert '-drive file=/sd/card.img,if=none,id=sony_sd,format=raw,cache=writeback' in text
        assert '-device usb-storage,id=sony-local-sd,drive=sony_sd,removable=on' in text
        assert 'usb-host' not in text and str(card) not in text
        subprocess.run(['bash','-n',str(script)],check=True)
        invalid={**lease,'inode':lease['inode']+1}
        with pytest.raises(ValueError,match='pinned'):
            prepare_profile(BASE,invalid,tmp_path/'bad')


def test_bwrap_accepts_inherited_pinned_regular_file_not_proc_path(tmp_path):
    with card_lease(tmp_path) as lease:
        result=subprocess.run(['bwrap','--unshare-all','--die-with-parent',
            '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib',
            '--symlink','usr/lib','/lib64','--proc','/proc','--dev','/dev',
            '--dir','/sd','--bind-fd',str(lease['fd']),'/sd/card.img',
            '--','/usr/bin/stat','-c','%s %i','/sd/card.img'],
            pass_fds=(lease['fd'],),capture_output=True,text=True,timeout=10)
        assert result.returncode==0,result.stderr
        size,inode=map(int,result.stdout.split())
        assert size==TOTAL and inode==lease['inode']
