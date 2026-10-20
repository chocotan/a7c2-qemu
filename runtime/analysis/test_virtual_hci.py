"""Pure H4 core and newly allocated host PTY only; no guest or existing TTY opened."""
from pathlib import Path
import subprocess

BASE=Path(__file__).resolve().parent


def test_core_and_owned_pty(tmp_path):
    for name in ('test-virtual-hci','test-owned-pty'):
        binary=tmp_path/name
        subprocess.run(['clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                        str(BASE/(name+'.c')),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True,timeout=30,capture_output=True)


def test_no_host_executable(tmp_path):
    result=subprocess.run(['clang','-c',str(BASE/'virtual-hci.c'),'-o',str(tmp_path/'bad.o')],capture_output=True)
    assert result.returncode and b'Guest-only executable' in result.stderr
