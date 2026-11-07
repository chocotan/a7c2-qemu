#!/usr/bin/env python3
"""Declare the Sony CXD90057 fixed IO windows in the generic-virt board DTB.

The original kernel's ``map_io()`` (arch/arm64/mm/mmu.c:925, CONFIG_ARCH_EJ) walks
DTB nodes of ``device_type = "iomap"`` and calls ``__create_pgd_mapping`` for each.
Sony's own board DTB declares three of them, which is what makes
``IO_ADDRESS(phys) == CXD900XX_IO_VA | phys`` (0xfffffffff0000000 | phys) reachable
for the proprietary drivers: ``udif_ioremap()`` sees a non-zero ``virt`` in its
UDIF_IOMEM descriptor and therefore never calls ioremap itself.

The declarations below were read from the signed 2.01 update package's own board
device tree (0800_appli/setting/cxd90057.dtb); ``read_iomap_nodes`` re-derives them
from any DTB so a test can prove they were not invented. Nothing here is device
private data - it is the platform memory map the retail board advertises.
"""
import struct

# name, phys, virt, size, memtype (arch/arm64/include/asm/memory.h: MT_DEVICE_nGnRE=1,
# MT_NORMAL_NC=3). Order follows the original DTB.
IOMAP_NODES = (
    ('iomem@0xf0000000', 0x00000000F0000000, 0xFFFFFFFFF0000000, 0x000000000E000000, 1),
    ('esram@0xfe000000', 0x00000000FE000000, 0xFFFFFFFFFE000000, 0x0000000001000000, 3),
    ('iomem2@0xf0000000', 0x00000000FF000000, 0xFFFFFFFFFF000000, 0x0000000001000000, 1),
)
IOMAP_DEVICE_TYPE = b'iomap\0'
# Only these exact adapter-created mappings may be superseded. RAM declarations
# and /chosen reservation identities are not modified.
ADAPTER_SHIMS = (
    ('sony-gic-alias', 0x08000000, 0xFFFFFFFFF13A1000, 0x1000, 1),
    ('sony-register-backing', 0xF101D000, 0xFFFFFFFFF101D000, 0x20000, 1),
    ('sony-scu-map', 0xF1388000, 0xFFFFFFFFF1388000, 0x2000, 1),
    ('sony-timer-map', 0xF1042000, 0xFFFFFFFFF1042000, 0x4000, 1),
)


def _be(value, size):
    return value.to_bytes(size, 'big')


def read_iomap_nodes(data):
    """Extract iomap declarations from a raw DTB image (independent parser)."""
    if len(data) < 40:
        raise ValueError('Not a complete flattened device tree')
    magic, total, off_struct, off_strings, _, _, _, _, size_strings, size_struct = struct.unpack_from('>10I', data, 0)
    if magic != 0xD00DFEED or total > len(data):
        raise ValueError('Not a complete flattened device tree')
    del size_strings

    def string(offset):
        end = data.index(b'\0', off_strings + offset)
        return data[off_strings + offset:end].decode('latin1')

    position = off_struct
    end = off_struct + size_struct
    path = []
    current = {}
    found = []
    while position < end:
        token, = struct.unpack_from('>I', data, position)
        position += 4
        if token == 1:
            name = data[position:data.index(b'\0', position)].decode('latin1')
            position += (len(name) // 4 + 1) * 4
            path.append(name)
        elif token == 2:
            if current.get('device_type') == IOMAP_DEVICE_TYPE and len(current) == 5:
                found.append((path[-1], current['phys'], current['virt'], current['size'], current['memtype']))
            current = {}
            path.pop()
        elif token == 3:
            length, name_offset = struct.unpack_from('>II', data, position)
            position += 8
            value = data[position:position + length]
            position += (length + 3) // 4 * 4
            name = string(name_offset)
            if name == 'device_type':
                current['device_type'] = value
            elif name in ('phys', 'virt', 'size') and length == 8:
                current[name] = int.from_bytes(value, 'big')
            elif name == 'memtype' and length == 4:
                current['memtype'] = int.from_bytes(value, 'big')
        elif token == 4:
            position += 4
        elif token == 9:
            break
        else:
            raise ValueError('Unsupported FDT structure token')
    return tuple(found)


def add_iomap_nodes(fdt, buffer, declarations=IOMAP_NODES):
    """Insert the iomap nodes into an already opened libfdt buffer.

    Idempotent: an existing node must already carry the exact expected properties,
    otherwise the board input is rejected rather than silently duplicated.
    """
    import ctypes
    fdt.fdt_getprop.restype = ctypes.c_void_p
    root = fdt.fdt_path_offset(buffer, b'/')
    if root < 0:
        raise ValueError('Board DTB has no root node')

    def prop(node,key):
        length=ctypes.c_int()
        pointer=fdt.fdt_getprop(buffer,node,key.encode(),ctypes.byref(length))
        return ctypes.string_at(pointer,length.value) if pointer and length.value>=0 else None

    # Validate all existing nodes before deleting any. Re-resolve offsets after
    # every deletion because libfdt moves subsequent structure data.
    for name,phys,virt,size,memtype in ADAPTER_SHIMS:
        node=fdt.fdt_path_offset(buffer,('/'+name).encode())
        if node<0:continue
        expected={'device_type':IOMAP_DEVICE_TYPE,'phys':_be(phys,8),'virt':_be(virt,8),
                  'size':_be(size,8),'memtype':_be(memtype,4)}
        if fdt.fdt_first_subnode(buffer,node)>=0 or any(prop(node,k)!=v for k,v in expected.items()):
            raise ValueError('Foreign or changed adapter iomap: '+name)
    for name,*_ in ADAPTER_SHIMS:
        node=fdt.fdt_path_offset(buffer,('/'+name).encode())
        if node>=0 and fdt.fdt_del_node(buffer,node)!=0:
            raise ValueError('Cannot retire superseded adapter iomap: '+name)
    added = 0
    for name, phys, virt, size, memtype in declarations:
        expected = {'device_type': IOMAP_DEVICE_TYPE,
                    'phys': _be(phys, 8), 'virt': _be(virt, 8),
                    'size': _be(size, 8), 'memtype': _be(memtype, 4)}
        node = fdt.fdt_path_offset(buffer, b'/' + name.encode())
        if node >= 0:
            for key, value in expected.items():
                length = ctypes.c_int()
                pointer = fdt.fdt_getprop(buffer, node, key.encode(), ctypes.byref(length))
                actual = ctypes.string_at(pointer, length.value) if pointer and length.value >= 0 else None
                if actual != value:
                    raise ValueError('Existing iomap node differs: %s.%s' % (name, key))
            continue
        node = fdt.fdt_add_subnode(buffer, root, name.encode())
        if node < 0:
            raise ValueError('Cannot add iomap node: ' + name)
        for key, value in expected.items():
            if fdt.fdt_setprop(buffer, node, key.encode(), value, len(value)) != 0:
                raise ValueError('Cannot describe iomap node: %s.%s' % (name, key))
        added += 1
    return added


if __name__ == '__main__':
    import sys
    print(read_iomap_nodes(open(sys.argv[1], 'rb').read()))
