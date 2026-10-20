"""Host test for the read-only capture-gate readback (no guest involved)."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capture_gate_readback as gate


def _synthetic(chunk, base):
    lines = []
    for index, (label, address, _note) in enumerate(chunk):
        lines += [f'{label}_BEGIN',
                  f'READMEM /proc/302/mem address={address:x} bytes=4',
                  f'{address:x}: {(base+index) & 0xff:02x} 00 00 00',
                  f'{label}_RC=0']
    return ('\n'.join(lines) + '\n').encode()


def test_commands_stay_within_the_interactive_line_limit():
    commands = gate.commands(b'OBS FRAME_DRAW_ENTER call=3 tid=302 this=0x1\n')
    assert len(commands) == 2, 'the readback must not be one huge paste'
    longest = max(len(line) for chunk in commands for line in chunk.splitlines())
    assert longest < 200, longest
    for chunk, cells in zip(commands, gate.CHUNKS):
        for label, _address, _note in cells:
            assert label + '_BEGIN' in chunk


def test_parse_pairs_every_cell_and_keeps_raw_values():
    parts = [_synthetic(gate.CHUNKS[0], 0x11), _synthetic(gate.CHUNKS[1], 0x22)]
    result = gate.parse(parts)
    assert len(result['reads']) == len(gate.GATE_CELLS)
    assert result['reads'][0]['value'] == 0x11
    assert result['reads'][-1]['value'] == (0x22 + len(gate.CHUNKS[1]) - 1) & 0xff
    assert result['capture_verified'] is False


def test_parse_rejects_missing_or_duplicated_cells():
    parts = [_synthetic(gate.CHUNKS[0], 0x11), _synthetic(gate.CHUNKS[1], 0x22)]
    broken = parts[0].replace(b'GATE_LENS_RETRACTED_BEGIN', b'GATE_LENS_RETRACTED_BEGN')
    try:
        gate.parse([broken, parts[1]])
    except ValueError as error:
        assert 'GATE_LENS_RETRACTED' in str(error)
    else:
        raise AssertionError('missing cell accepted')

    duplicated = parts[0] + parts[0]
    try:
        gate.parse([duplicated, parts[1]])
    except ValueError as error:
        assert 'ambig' in str(error).lower()
    else:
        raise AssertionError('duplicated cell accepted')


GATE_GETTERS = {
    'GATE_USB_STREAMING': (0x27ab3a0, 0x7eddbc8),
    'GATE_EE_STATUS': (0x28623f0, 0x7e67700),
    'GATE_NETWORK_STREAMING': (0x2778070, 0x7e71a70),
    'GATE_LENS_RETRACTED': (0x2765574, 0x7e59cf0),
    'GATE_FOCUS_INIT_ERROR': (0x276acc8, 0x7e67478),
    'GATE_ZOOM_INIT_ERROR': (0x276ad04, 0x7e67498),
    'GATE_STEADY_ERROR': (0x27663e8, 0x7e5bc18),
    'GATE_DATE_TIME': (0x2768200, 0x7e5df40),
    'GATE_TWO_SLOT_INHIBIT': (0x279cdf0, 0x7eae2b0),
    # Release w/o lens or card defaults to Enable on this body: the gate must not
    # treat a missing lens as blocking by itself, so both settings are recorded.
    'RELEASE_WO_LENS_LIVE': (0x2779d50, 0x7e73740),
    'RELEASE_WO_CARD_DOC': (0x2774194, 0x7e6f2c8),
    'RELEASE_WO_CARD_GETTER': (0x2779dc8, 0x7e73788),
}


def test_gate_cells_match_the_original_getters():
    """Each gate cell must equal what its original getter returns.

    The full-system frontier lists these getter/field pairs; re-deriving them from
    the public appFw bytes here keeps a wrong cell from producing misleading
    gate evidence. Both shapes occur: `adrp;add…;ldr;ret` and `adrp;add…;ret`
    (the address itself is returned in x0).
    """
    import struct
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    path = Path(__file__).resolve().parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        raise SystemExit('original appFw.so is required for the gate pin test')
    raw = path.read_bytes()
    dis = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

    def resolve(getter):
        regs = {}
        for ins in dis.disasm(raw[getter:getter+32], getter):
            if ins.mnemonic == 'adrp':
                name, _, page = ins.op_str.partition(', ')
                regs[name.strip()] = int(page.split('#')[1], 16)
            elif ins.mnemonic == 'add':
                parts = [item.strip() for item in ins.op_str.split(',')]
                if len(parts) >= 3 and parts[2].startswith('#') and parts[1] in regs:
                    shift = 12 if 'lsl #12' in ins.op_str else 0
                    regs[parts[0]] = regs[parts[1]] + (
                        int(parts[2].split('#')[1].split(',')[0], 16) << shift)
            elif ins.mnemonic in ('ldr', 'str') and '[' in ins.op_str:
                inner = ins.op_str.split('[')[1].split(']')[0].split(',')
                base = inner[0].strip()
                offset = int(inner[1].split('#')[1], 16) if len(inner) > 1 else 0
                if base in regs:
                    return regs[base] + offset
            elif ins.mnemonic == 'ret':
                return regs.get('x0')
        return None

    for label, (getter, expected) in GATE_GETTERS.items():
        assert resolve(getter) == expected, label
