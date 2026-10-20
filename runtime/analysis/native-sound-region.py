"""Reserve the original SysSound bytes in separately owned native guest RAM."""
from pathlib import Path
import ctypes
import runpy

API = runpy.run_path(str(Path(__file__).with_name('device-models') / 'system-sound-region.py'))
SOURCE_BYTES = 66368
SOURCE_SHA256 = '5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a'


def reserve(fdt, buffer, command_line):
    API['validate_final_command'](command_line)
    API['add_dtb_reservation'](fdt, buffer, command_line)


def verify_reservation(run, library):
    fdt = ctypes.CDLL(str(library))
    raw = (run / 'virt.dtb').read_bytes()
    if not 40 <= len(raw) <= 65536:
        raise ValueError('Sound board DTB size differs')
    source = ctypes.create_string_buffer(raw); buffer = ctypes.create_string_buffer(65536)
    fdt.fdt_check_full.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if fdt.fdt_check_full(source,len(raw)) or fdt.fdt_open_into(source,buffer,len(buffer)):
        raise ValueError('Sound board DTB is incomplete or malformed')
    fdt.fdt_getprop.restype = ctypes.c_void_p
    chosen = fdt.fdt_path_offset(buffer,b'/chosen'); length = ctypes.c_int()
    p = fdt.fdt_getprop(buffer,chosen,b'bootargs',ctypes.byref(length))
    if not p or length.value <= 0:
        raise ValueError('Sound board bootargs missing')
    command = ctypes.string_at(p,length.value).rstrip(b'\0').decode('ascii')
    before = fdt.fdt_num_mem_rsv(buffer)
    reserve(fdt,buffer,command)
    if before != fdt.fdt_num_mem_rsv(buffer):
        raise ValueError('Sound reservation was not already present in board')
    return command
