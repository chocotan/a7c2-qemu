"""Read-only capture-gate readback for one owned camera run.

Every address comes from `report/2026-10-17-qemu-full-system/CAPTURE-INHIBIT-SOURCES.md`,
which traced them to original getters in the same public `appFw.so`
(sha256 2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b).

Nothing here writes the model, clears an inhibit, or reports ready: the point is
to see which original gate the guest actually hit, not to open it.

The list is split into two serial transactions because the interactive BusyBox
line buffer truncates long pastes (an earlier 26-cell readback lost characters).
"""
import re

# (label, ELF VA, note)
GATE_CELLS = (
    ('CAPTURE_INHIBIT_BYTE', 0x83337e3, 'u8 total inhibit'),
    ('CAPTURE_INHIBIT_COUNT', 0x7e1c00c, 'u32 inhibit count'),
    ('GATE_USB_STREAMING', 0x7eddbc8, 'source 0x79, 1=ON blocks'),
    ('GATE_EE_STATUS', 0x7e67700, 'source 0x7b, 0=NOT_RUNNING blocks'),
    ('GATE_NETWORK_STREAMING', 0x7e71a70, 'source 0x94, 0=ON blocks'),
    ('GATE_LENS_RETRACTED', 0x7e59cf0, 'source 0xcd, 1=IN blocks'),
    ('GATE_FOCUS_INIT_ERROR', 0x7e67478, 'source 0xda, 0=ERROR blocks'),
    ('GATE_ZOOM_INIT_ERROR', 0x7e67498, 'source 0xdb, 0=ERROR blocks'),
    ('GATE_STEADY_ERROR', 0x7e5bc18, 'source 0x5ed, 1=OCCURED blocks'),
    ('GATE_DATE_TIME', 0x7e5df40, 'source 0x806, 2=NOT_SET/3=UNKNOWN blocks'),
    ('GATE_TWO_SLOT_INHIBIT', 0x7eae2b0, 'source 0x997, 5=NO_COMMON_FOLDER blocks'),
    ('HAITA_NO_LENS_RELEASE', 0x7e35440, 'source 0xcf processed value'),
    ('HAITA_STEADY_SELFTIMER', 0x7e400d8, 'source 0x800 processed value'),
    ('HAITA_MEDIA_TARGET', 0x7e411d0, 'source 0x8b5 processed value'),
    ('HAITA_RELAY_TARGET', 0x7e426e8, 'source 0x996 processed value'),
    # Release-without-lens/card defaults are Enable on this body, so a missing
    # lens must not read as a gate by itself. Record every copy of the setting:
    # the dispatch row exposes a live cell and a shadow cell per property.
    ('RELEASE_WO_LENS_LIVE', 0x7e73740, 'PRM_setting_release_wo_lens getter cell'),
    ('RELEASE_WO_LENS_SHADOW', 0x7e73730, 'PRM_setting_release_wo_lens shadow cell'),
    ('RELEASE_WO_CARD_DOC', 0x7e6f2c8, 'release_wo_card cell listed by the full frontier'),
    ('RELEASE_WO_CARD_GETTER', 0x7e73788, 'PRM_setting_release_wo_card getter cell'),
    ('RELEASE_WO_CARD_PREDICATE', 0x7e73770, 'copy the caution predicate reads'),
    # Single-slot capability: the runtime getter indexes a 26-entry u32 table at
    # 0x370e3e8. Read neighbours too, so a wrong product index cannot masquerade
    # as "the" slot count.
    # The getter 0x1798134 indexes that table with *(int32*)0x5bc35b0, so the
    # product index itself is recorded next to the values.
    ('MEDIA_CAP_PRODUCT_INDEX', 0x5bc35b0, 'index used by 0x1798134'),
    ('MEDIA_CAP_TABLE_15', 0x370e3e8+15*4, 'capability table[15]'),
    ('MEDIA_CAP_TABLE_16', 0x370e3e8+16*4, 'capability table[16]'),
    ('MEDIA_CAP_TABLE_17', 0x370e3e8+17*4, 'capability table[17]'),
)
CHUNKS = (GATE_CELLS[:8], GATE_CELLS[8:])


def _task(console):
    tasks = set(re.findall(rb'OBS FRAME_DRAW_ENTER call=\d+ tid=(\d+) ', console))
    if len(tasks) != 1:
        raise ValueError('No unique observed original frame task for gate readback')
    task = int(next(iter(tasks)))
    if not 1 <= task <= 0x7fffffff:
        raise ValueError('Invalid original frame task')
    return task


def commands(console):
    """Two bounded serial commands; each is a single if-block with its own sentinel."""
    task = _task(console)
    root = f'/proc/{task}'
    out = []
    for chunk in CHUNKS:
        parts = [f'if /bin/busybox grep -q /usr/lib/appFw.so {root}/maps 2>/dev/null; then',
                 f'echo GATE_TID={task}']
        for label, address, _note in chunk:
            parts += [f'echo {label}_BEGIN',
                      f'/simulation/menu-readmem {root}/mem {address:#x} 4 appFw.so',
                      f'echo {label}_RC=$?']
        parts += ['else echo GATE_MAPPING_UNAVAILABLE', 'fi', 'true']
        out.append('\n'.join(parts))
    return out


def parse(parts):
    """Parse the two chunk files; no inference about cause or capture success."""
    if isinstance(parts, (list, tuple)):
        text = b'\n'.join(bytes(item) for item in parts).decode('ascii', errors='replace')
    else:
        text = bytes(parts).decode('ascii', errors='replace')
    result = {'scope': 'original capture-gate cells, read only',
              'capture_verified': False, 'reads': []}
    for label, address, note in GATE_CELLS:
        matches = re.findall(r'^'+label+r'_BEGIN\r?\n(.*?)^'+label+r'_RC=(\d+)\r?\n',
                             text, re.S | re.M)
        if len(matches) != 1:
            raise ValueError('Missing/ambiguous gate read: '+label)
        raw, rc = matches[0]
        value = None
        found = re.search(r'^[0-9a-fA-F]+:\s*((?:[0-9a-fA-F]{2} ){3}[0-9a-fA-F]{2})', raw, re.M)
        if found:
            value = int.from_bytes(bytes.fromhex(found[1].replace(' ', '')), 'little')
        result['reads'].append({'label': label, 'elf_va': hex(address), 'note': note,
                                'returncode': int(rc), 'value': value})
    return result
