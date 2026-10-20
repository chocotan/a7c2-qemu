import ctypes
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest
import usb_network as profile

NATIVE = Path(__file__).resolve().parent
LIBRARY = NATIVE.parent/'sources/qemu-tools/usr/lib/libfdt.so.1'


def test_profile_is_relocatable_and_does_not_enable_the_guest_interface(tmp_path):
    source = NATIVE/'qemu-kernel-probe.sh'
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    env = profile.prepare_profile(NATIVE, tmp_path)
    script = Path(env['MENU_KERNEL_SCRIPT'])
    rendered = script.read_text()
    assert '-netdev stream,' in rendered and '-device usb-net,' in rendered
    assert '--setenv QEMU_SONY_USB_NET 1' in rendered
    assert str(NATIVE.parent) in rendered
    assert 'scratch/wifi' not in rendered and 'candidate-rt' not in rendered
    assert '10.0.0.2' not in rendered
    assert env['QEMU_SYSTEM_DIR'] == str(NATIVE.parent/'sources/qemu-11.1.2/build-sony-ui')
    subprocess.run(['bash', '-n', str(script)], check=True)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original
    metadata = json.loads((script.parent/'profile.json').read_text())
    assert metadata['link_initially_enabled'] is False
    assert metadata['guest_probe_verified'] is False


def test_generated_board_has_the_verified_xhci_geometry(tmp_path):
    env = profile.prepare_profile(NATIVE, tmp_path)
    data = Path(env['MENU_DTB']).read_bytes()
    blob = ctypes.create_string_buffer(data)
    lib = ctypes.CDLL(str(LIBRARY))
    lib.fdt_path_offset.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.fdt_getprop.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    lib.fdt_getprop.restype = ctypes.c_void_p
    node = lib.fdt_path_offset(blob, b'/usb@b000000')
    assert node >= 0

    def read(name):
        length = ctypes.c_int()
        value = lib.fdt_getprop(blob, node, name, ctypes.byref(length))
        assert value and length.value >= 0
        return ctypes.string_at(value, length.value)

    assert read(b'compatible') == b'generic-xhci\0'
    assert struct.unpack('>4I', read(b'reg')) == (0, 0x0b000000, 0, 0x4000)
    assert struct.unpack('>3I', read(b'interrupts')) == (0, 180, 4)
    with pytest.raises(ValueError, match='existing USB'):
        profile.add_usb_node(env['MENU_DTB'], tmp_path/'duplicate.dtb', LIBRARY)


def test_changed_native_launcher_is_rejected_before_profile_creation(tmp_path):
    native = tmp_path/'analysis'
    native.mkdir()
    (native/'qemu-kernel-probe.sh').write_text('unrecognized launcher\n')
    with pytest.raises(ValueError, match='anchor changed'):
        profile.prepare_profile(native, tmp_path/'profiles')
    assert not (tmp_path/'profiles').exists()
