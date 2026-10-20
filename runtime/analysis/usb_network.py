"""Prepare an isolated USB-network profile from the shipped native launcher.

The profile creates virtual hardware only; WifiLink owns interface changes.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import shlex
import struct
import tempfile


def add_usb_node(source, destination, library):
    lib = ctypes.CDLL(str(library))
    lib.fdt_open_into.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.fdt_path_offset.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.fdt_add_subnode.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p]
    lib.fdt_setprop.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int]
    lib.fdt_getprop.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
    lib.fdt_getprop.restype = ctypes.c_void_p
    lib.fdt_pack.argtypes = [ctypes.c_void_p]
    raw = Path(source).read_bytes()
    buffer = ctypes.create_string_buffer(len(raw) + 65536)
    ctypes.memmove(buffer, raw, len(raw))
    if lib.fdt_open_into(buffer, buffer, len(buffer)):
        raise ValueError('Cannot open the native board DTB')
    for name in (b'#address-cells', b'#size-cells'):
        length = ctypes.c_int()
        value = lib.fdt_getprop(buffer, 0, name, ctypes.byref(length))
        if not value or length.value != 4 or ctypes.string_at(value, 4) != b'\0\0\0\2':
            raise ValueError('Native board root cell layout differs')
    if lib.fdt_path_offset(buffer, b'/usb@b000000') >= 0:
        raise ValueError('Refusing to replace an existing USB node')
    node = lib.fdt_add_subnode(buffer, 0, b'usb@b000000')
    if node < 0:
        raise ValueError('Cannot add the USB node')
    properties = {b'compatible': b'generic-xhci\0', b'status': b'okay\0',
                  b'reg': struct.pack('>4I', 0, 0x0b000000, 0, 0x4000),
                  b'interrupts': struct.pack('>3I', 0, 180, 4), b'dma-coherent': b''}
    for name, value in properties.items():
        if lib.fdt_setprop(buffer, node, name, value, len(value)):
            raise ValueError('Cannot set USB DT property ' + repr(name))
    if lib.fdt_pack(buffer):
        raise ValueError('Cannot pack the USB DTB')
    size = struct.unpack_from('>I', buffer.raw, 4)[0]
    Path(destination).write_bytes(buffer.raw[:size])


def prepare_profile(native, output_parent=None):
    native = Path(native).resolve()
    runtime = native.parent
    source = native/'qemu-kernel-probe.sh'
    board = native/'qemu-virt-board/virt-packed.dtb'
    script = source.read_text()
    replacements = {
        'project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"':
            'project_dir=' + shlex.quote(str(runtime)),
        '    "${timer_environment[@]}" \\\n':
            '    "${timer_environment[@]}" \\\n    --setenv QEMU_SONY_USB_NET 1 \\\n',
        '      -nodefaults "${display_args[@]}" -monitor none -serial stdio -nic none \\\n':
            '      -nodefaults "${display_args[@]}" -monitor none -serial stdio -nic none \\\n'
            '      -netdev stream,id=sony_net,addr.type=unix,addr.path=/out/ethernet.sock,server=on \\\n'
            '      -device usb-net,id=sony-usb-network,netdev=sony_net \\\n',
    }
    for old, new in replacements.items():
        if script.count(old) != 1:
            raise ValueError('Native USB launcher anchor changed: ' + repr(old))
        script = script.replace(old, new, 1)
    parent = Path(output_parent) if output_parent is not None else native/'usb-network-profiles'
    parent.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix='profile-', dir=parent))
    derived_script = output/'kernel-usb.sh'
    derived_board = output/'board-usb.dtb'
    derived_script.write_text(script)
    add_usb_node(board, derived_board, runtime/'sources/qemu-tools/usr/lib/libfdt.so.1')
    identities = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
                  (('base_script', source), ('base_board', board),
                   ('derived_script', derived_script), ('derived_board', derived_board))}
    (output/'profile.json').write_text(json.dumps(
        {'scope': 'isolated USB Ethernet launcher profile', 'files': identities,
         'link_initially_enabled': False, 'guest_probe_verified': False}, indent=2)+'\n')
    return {'MENU_USB_NET': '1', 'MENU_KERNEL_SCRIPT': str(derived_script),
            'MENU_DTB': str(derived_board),
            'QEMU_SYSTEM_DIR': str(runtime/'sources/qemu-11.1.2/build-sony-ui'),
            'QEMU_SYSTEM_BINARY': 'qemu-system-aarch64'}
