#!/usr/bin/env python3
"""New finite control-pool backing; capacity is not Sony's original policy."""
from pathlib import Path
import runpy

PHYSICAL = 0x500000000
CAPACITY = 0x2000
SLOT_BYTES = 0x200
SLOTS = 16
CP_VIRTUAL = 0x80000000
RESERVATION = 'memrsv=0x00002000@0x500000000:uc'
KEY = b'qemu,a7c2-pin-control-buffer-owner'
HERE = Path(__file__).resolve().parent


def validate_reservation(workspace):
    if CAPACITY != SLOTS * SLOT_BYTES or CP_VIRTUAL != 0x80000000 + PHYSICAL - 0x500000000:
        raise ValueError('Explicit control pool layout differs')
    runpy.run_path(str(HERE / 'reserved-region.py'))['validate_workspace'](workspace, PHYSICAL, CAPACITY)
    return RESERVATION


def add_dtb_reservation(fdt, buffer, command_line):
    runpy.run_path(str(HERE / 'reserved-region.py'))['add_reservation'](
        fdt, buffer, command_line, physical=PHYSICAL, capacity=CAPACITY, command=RESERVATION, key=KEY)
