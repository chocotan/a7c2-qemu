#!/usr/bin/env python3
"""Closed reservation for the card-export window.

The guest copies one chunk of its card image into this window and the host reads it
back with QMP pmemsave; nothing about the card is synthesised on either side.
"""
from pathlib import Path
import runpy

PHYSICAL = 0x41eb00000
CAPACITY = 0x400000
RESERVATION = 'memrsv=0x00400000@0x41eb00000:uc'


def validate_reservation(workspace):
    """Reuses the shared closed checks, then re-verifies the exact token we emit."""
    runpy.run_path(str(Path(__file__).with_name('reserved-region.py')))[
        'validate_workspace'](workspace, PHYSICAL, CAPACITY)
    return RESERVATION


def add_dtb_reservation(fdt, buffer, command_line):
    runpy.run_path(str(Path(__file__).with_name('reserved-region.py')))['add_reservation'](
        fdt, buffer, command_line, physical=PHYSICAL, capacity=CAPACITY,
        command=RESERVATION, key=b'qemu,a7c2-card-export')
    return RESERVATION
