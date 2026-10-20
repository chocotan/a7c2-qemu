"""Bounded read-only diagnostic for original media-state and selection cells.

No API calls into the firmware and no settings/model writes. The labels refer
to shared firmware model names, never two physical A7CII card slots.
"""
import re

CELLS = (('MEDIA_MOUNT_LOGICAL_1', 0x7e80dd0), ('MEDIA_MOUNT_LOGICAL_2', 0x7e80df0),
         # Original setting metadata objects 2867680 / 28676a8, +0x10 caches.
         # Preserve existing evidence labels; these are NOT the live fields.
         ('MEDIA_SELECTION_STILL', 0x7e6e808), ('MEDIA_SELECTION_MOVIE', 0x7e6e828),
         # Actual setter and business reader fields, distinct from metadata.
         ('MEDIA_SELECTION_STILL_LIVE', 0x7e6e7f0),
         ('MEDIA_SELECTION_MOVIE_LIVE', 0x7e6e810),
         # update_product_model1797b84 reads the first and writes the second.
         # Neither value is itself a physical-slot count or a model name.
         ('FEATURE_PRODUCT_MODEL_LIVE', 0x7e504d8),
         ('FEATURE_PRODUCT_TABLE_INDEX', 0x5bc35b0))


def command(console):
    # Bind to the exact original frame-drawing task observed in THIS run,
    # instead of guessing a process by scan or borrowing an earlier PID.
    tasks = set(re.findall(rb'OBS FRAME_DRAW_ENTER call=\d+ tid=(\d+) ', console))
    if len(tasks) != 1:
        raise ValueError('No unique observed original frame task for media readback')
    task = int(next(iter(tasks)))
    if not 1 <= task <= 0x7fffffff:
        raise ValueError('Invalid original frame task')
    root = f'/proc/{task}'
    checks = f'if /bin/busybox grep -q /usr/lib/appFw.so {root}/maps; then'
    parts = [checks, f'echo MEDIA_STATE_OBSERVED_TID={task}']
    for label, address in CELLS:
        parts += [f'echo {label}_BEGIN',
                  f'/simulation/menu-readmem {root}/mem {address:#x} 4 appFw.so',
                  f'echo {label}_RC=$?']
    # BusyBox ash's interactive input line is bounded. A single eight-field
    # command plus the runner sentinel exceeded it and left an incomplete if.
    # Keep each physical line short; retain one if block and one final sentinel.
    return '\n'.join(parts+['else echo MEDIA_STATE_MAPPING_UNAVAILABLE', 'fi', 'true'])


def parse(data):
    """Keep raw evidence; no inferred present/absent, physical-slot or capture."""
    text = data.decode('ascii', errors='replace')
    result = {'scope': 'original media fields and feature product-table inputs, read only',
              'physical_card_slots': 1, 'capture_verified': False, 'reads': []}
    for label, address in CELLS:
        # Interactive multiline input is echoed before the if block executes.
        # Only standalone output labels are transaction delimiters, not
        # '> echo LABEL_BEGIN' or an echoed command suffix.
        matches = re.findall(r'^'+label+r'_BEGIN\r?\n(.*?)^'+label+r'_RC=(\d+)\r?\n',
                             text, re.S | re.M)
        if len(matches) != 1:
            raise ValueError('Missing/ambiguous media-state read: '+label)
        raw, rc = matches[0]
        result['reads'].append({'label': label, 'elf_va': hex(address),
                                'returncode': int(rc), 'raw_output': raw})
    return result
