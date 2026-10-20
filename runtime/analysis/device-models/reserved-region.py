#!/usr/bin/env python3
"""Closed generic-virt reservation validation for explicitly owned guest RAM."""
import ctypes
import re
import struct


def validate_workspace(workspace, physical, capacity):
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError('Missing original workspace reservations')
    if capacity <= 0 or not 0x400000000 <= physical < physical + capacity <= 0x600000000:
        raise ValueError('Explicit owner is outside full-dump DDR')
    words = [word for word in workspace.split() if word.startswith('memrsv=')]
    if not words:
        raise ValueError('Original reservations were not read')
    for word in words:
        match = re.fullmatch(r'memrsv=(0[xX][0-9a-fA-F]+|[0-9]+)@(0[xX][0-9a-fA-F]+|[0-9]+)(?::[a-zA-Z]+)?', word)
        if not match:
            raise ValueError('Unrecognized memory reservation')
        size, start = (int(value, 0) for value in match.groups())
        if size <= 0 or start + size > 1 << 64:
            raise ValueError('Invalid original reservation')
        if start < physical + capacity and physical < start + size:
            raise ValueError('Original reservation overlaps explicit owner')
    for start, size in ((0x400000000, 0x1000000), (0x41d000000, 0x20000),
                        (0x41e000000, 0xa00000), (0x440000000, 0x80000000)):
        if start < physical + capacity and physical < start + size:
            raise ValueError('Explicit owner overlaps an existing adapter or boot load')


def add_reservation(fdt, buffer, command_line, *, physical, capacity, command, key):
    if capacity <= 0 or not 0x400000000 <= physical < physical + capacity <= 0x600000000 or not key.startswith(b'qemu,a7c2-'):
        raise ValueError('Invalid explicit reservation identity')
    token = re.fullmatch(r'memrsv=(0[xX][0-9a-fA-F]+|[0-9]+)@(0[xX][0-9a-fA-F]+|[0-9]+)(?::[a-zA-Z]+)?', command)
    if not token or tuple(int(value, 0) for value in token.groups()) != (capacity, physical):
        raise ValueError('Command and explicit reservation geometry differ')
    if command_line.split().count(command) != 1:
        raise ValueError('Explicit reservation command is missing or duplicated')
    fdt.fdt_getprop.restype = ctypes.c_void_p
    fdt.fdt_get_mem_rsv.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
    fdt.fdt_add_mem_rsv.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64]

    def prop(node, name):
        length = ctypes.c_int()
        pointer = fdt.fdt_getprop(buffer, node, name, ctypes.byref(length))
        return ctypes.string_at(pointer, length.value) if pointer and length.value >= 0 else None

    root = fdt.fdt_path_offset(buffer, b'/')
    chosen = fdt.fdt_path_offset(buffer, b'/chosen')
    if chosen < 0 or prop(root, b'compatible') != b'linux,dummy-virt\0':
        raise ValueError('Explicit owner requires the declared generic-virt board')
    if any(prop(root, name) != struct.pack('>I', 2) for name in (b'#address-cells', b'#size-cells')):
        raise ValueError('Explicit owner requires two-cell board memory ranges')
    covered = False
    node = fdt.fdt_next_node(buffer, -1, None)
    while node >= 0:
        if prop(node, b'device_type') == b'memory\0':
            if fdt.fdt_parent_offset(buffer, node) != root:
                raise ValueError('Nested or translated RAM is unsupported by this board profile')
            ranges = prop(node, b'reg')
            if not ranges or len(ranges) % 16:
                raise ValueError('Invalid declared board RAM')
            for offset in range(0, len(ranges), 16):
                start, size = struct.unpack_from('>QQ', ranges, offset)
                if size <= 0 or start + size > 1 << 64:
                    raise ValueError('Invalid or overflowing declared board RAM')
                covered |= start <= physical and physical + capacity <= start + size
        node = fdt.fdt_next_node(buffer, node, None)
    if not covered:
        raise ValueError('Explicit owner is outside declared board RAM')
    reserved = fdt.fdt_path_offset(buffer, b'/reserved-memory')
    if reserved >= 0:
        if prop(reserved, b'ranges') not in (None, b''):
            raise ValueError('Translated reserved-memory is unsupported')
        cells = []
        for name in (b'#address-cells', b'#size-cells'):
            value = prop(reserved, name)
            if value is None:
                value = prop(root, name)
            if not value or len(value) != 4 or int.from_bytes(value, 'big') not in (1, 2):
                raise ValueError('Unknown reserved-memory cell layout')
            cells.append(int.from_bytes(value, 'big'))
        step = 4 * sum(cells)
        child = fdt.fdt_first_subnode(buffer, reserved)
        while child >= 0:
            reg = prop(child, b'reg')
            if not reg or len(reg) % step or fdt.fdt_first_subnode(buffer, child) >= 0:
                raise ValueError('Unexplained reserved-memory declaration')
            for offset in range(0, len(reg), step):
                split = offset + 4 * cells[0]
                start = int.from_bytes(reg[offset:split], 'big')
                size = int.from_bytes(reg[split:offset + step], 'big')
                if size <= 0 or start + size > 1 << 64:
                    raise ValueError('Invalid reserved-memory range')
                if start < physical + capacity and physical < start + size:
                    raise ValueError('Reserved-memory overlaps explicit owner')
            child = fdt.fdt_next_subnode(buffer, child)
    identity = struct.pack('>QQ', physical, capacity)
    owner = prop(chosen, key)
    if owner not in (None, identity):
        raise ValueError('Existing explicit owner differs')
    count = fdt.fdt_num_mem_rsv(buffer)
    if count < 0:
        raise ValueError('Cannot read DTB reservation map')
    found = False
    for index in range(count):
        start, size = ctypes.c_uint64(), ctypes.c_uint64()
        if fdt.fdt_get_mem_rsv(buffer, index, ctypes.byref(start), ctypes.byref(size)) != 0:
            raise ValueError('Cannot read a DTB reservation')
        if start.value < physical + capacity and physical < start.value + size.value:
            if (start.value, size.value) != (physical, capacity) or owner != identity or found:
                raise ValueError('Foreign DTB reservation overlaps explicit owner')
            found = True
    if owner is not None and not found:
        raise ValueError('Owner metadata has no reservation')
    if not found:
        if fdt.fdt_add_mem_rsv(buffer, physical, capacity) != 0:
            raise ValueError('Cannot reserve owned RAM in DTB')
        chosen = fdt.fdt_path_offset(buffer, b'/chosen')
        if fdt.fdt_setprop(buffer, chosen, key, identity, len(identity)) != 0:
            raise ValueError('Cannot identify explicit reservation owner')
