#!/usr/bin/env python3
"""Validate an explicitly owned virtual-sound reservation before VM startup."""
from pathlib import Path
import re
import runpy

PHYSICAL = 0x41d000000
CAPACITY = 0x20000
RESERVATION = 'memrsv=0x00020000@0x41d000000:uc'
LUT_RESERVATION = 'memrsv=0x00030000@0x41d000000:uc'


def reservation_layout(command_line):
    owners = [word for word in command_line.split() if word in (RESERVATION, LUT_RESERVATION)]
    if len(owners) != 1:
        raise ValueError('Sound owner reservation is missing or duplicated')
    # The DTB owns the envelope; sound consumers still map only CAPACITY bytes.
    return owners[0], 0x30000 if owners[0] == LUT_RESERVATION else CAPACITY


def validate_reservation(workspace, *, capacity=CAPACITY):
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError('Missing workspace reservation source')
    words = [word for word in workspace.split() if word.startswith('memrsv=')]
    if not words:
        raise ValueError('No original memory reservations could be read')
    for word in words:
        match = re.fullmatch(r'memrsv=(0[xX][0-9a-fA-F]+|[0-9]+)@(0[xX][0-9a-fA-F]+|[0-9]+)(?::[a-zA-Z]+)?', word)
        if not match:
            raise ValueError('Unrecognized memory reservation: ' + word)
        size, start = (int(value, 0) for value in match.groups())
        if size <= 0 or start + size > 1 << 64:
            raise ValueError('Invalid memory reservation range')
        if start < PHYSICAL + capacity and start + size > PHYSICAL:
            raise ValueError('Original or caller reservation overlaps virtual sound owner')
    # These other explicit adapters and boot loads never belong to this owner.
    for start, size in ((0x41e000000, 0xa00000), (0x440000000, 0x80000000),
                        (0x400000000, 0x1000000)):
        if start < PHYSICAL + capacity and start + size > PHYSICAL:
            raise ValueError('Virtual sound owner overlaps another adapter or boot load')
    if not 0x400000000 <= PHYSICAL < PHYSICAL + capacity <= 0x600000000:
        raise ValueError('Virtual sound owner is outside declared guest RAM')
    return RESERVATION


def add_dtb_reservation(fdt, buffer, command_line):
    """Use the same closed RAM/range checks as the finite control owner."""
    command, capacity = reservation_layout(command_line)
    runpy.run_path(str(Path(__file__).with_name('reserved-region.py')))['add_reservation'](
        fdt, buffer, command_line, physical=PHYSICAL, capacity=capacity,
        command=command, key=b'qemu,a7c2-system-sound-owner')


def validate_final_command(command_line):
    words = command_line.split()
    if [w for w in words if w.startswith('fullsystem.sound-owner=')] != ['fullsystem.sound-owner=1']:
        raise ValueError('Sound owner profile is missing, conflicting or duplicated')
    command, capacity = reservation_layout(command_line)
    if sum(w.startswith('memrsv=') for w in words) > 16:
        raise ValueError('Sound owner exceeds the original reservation table limit')
    validate_reservation(' '.join(w for w in words if w != command), capacity=capacity)


def adapt_script(text):
    if 'FULLSYSTEM_SYSTEM_SOUND_RESERVATION' in text:
        return text
    anchor = '# Reject overlapping static virtual mappings before booting the unmodified kernel.'
    if text.count(anchor) != 1:
        raise ValueError('Ambiguous virtual sound DTB adapter insertion')
    code = ('# FULLSYSTEM_SYSTEM_SOUND_RESERVATION: explicit VM-lifetime RAM owner.\n'
            'if "fullsystem.sound-owner=1" in sys.argv[3].split():\n'
            '    runpy.run_path(str(Path(sys.argv[7]).with_name("system-sound-region.py")))["add_dtb_reservation"](fdt,buffer,sys.argv[3])\n')
    return text.replace(anchor, code + anchor, 1)
