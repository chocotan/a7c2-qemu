import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import media_predicate_watch as media
import request_queue_watch as queue


def run_fake(tmp_path, monkeypatch, *, bad_code=False, read_error=False, rounds=1, policy=False):
    base = 0x7f00000000
    config = dict(run=str(tmp_path), app_base=base, socket='owned-test-socket',
                  trace_mode='media-policy' if policy else 'media')
    monkeypatch.setattr(queue, 'revalidate_gdb_config',
                        lambda supplied: (os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY), config))
    points, commands = [], []
    registers = {}

    class Breakpoint:
        def __init__(self, spec, type, internal):
            assert type == 7 and internal
            self.type, self.enabled = type, True
            points.append(self)

        def delete(self):
            self.enabled = False

    def read(address, size):
        if policy:
            if address == base+0x37766b0:
                return media.TABLE_COUNT.to_bytes(8, 'little')
            if address == base+0x5ba52f8:
                return (base+media.TABLE_VA).to_bytes(8, 'little')
            if size == 0x58:
                import struct
                data = bytearray(0x58)
                struct.pack_into('<Q', data, 0x10, base+0x1875c9c)
                struct.pack_into('<Q', data, 0x38, base+0x377ebf8)
                struct.pack_into('<Q', data, 0x40, base+0x18826e0)
                struct.pack_into('<Q', data, 0x48, base+0x377c168)
                struct.pack_into('<Q', data, 0x50, base+0x186d690)
                return data
            if address == base+0x377ebf8:
                return (0x0200a1a8).to_bytes(4, 'little')
            if address == base+0x377c168:
                return (0x0200a04a).to_bytes(4, 'little')
        if size == 8:
            return b'bad code' if bad_code else (media.POLICY_PREFIX if policy else media.ENTRY_PREFIX)
        if read_error:
            raise RuntimeError('Cannot read original field')
        assert address in [base+v for v in
                           {**media.FIELDS, **media.CAPACITY_FIELDS, **media.MEDIA_STATE_FIELDS,
                            **media.MEDIA_BASE_FIELDS, **media.UNRESOLVED_FIELDS,
                            **media.UNRESOLVED_BASE_FIELDS}.values()]
        if address-base in {**media.MEDIA_BASE_FIELDS, **media.UNRESOLVED_BASE_FIELDS}.values():
            return (2).to_bytes(4, 'little')
        return (1).to_bytes(4, 'little')

    def execute(command, to_string):
        commands.append(command)
        if command == 'continue':
            for _ in range(rounds):
                for point in points:
                    if not point.enabled:
                        continue
                    registers.update(sp=0x5000-((0x70 if policy else 0x30) if point.returning else 0),
                                     x30=base+0x1234, w0=0x171 if policy else 1)
                    if point.stop():
                        return
            raise KeyboardInterrupt

    fake = SimpleNamespace(Breakpoint=Breakpoint, BP_HARDWARE_BREAKPOINT=7,
                           events=SimpleNamespace(stop=SimpleNamespace(connect=lambda fn: None,
                                                                      disconnect=lambda fn: None)),
                           parse_and_eval=lambda name: registers[name[1:]],
                           selected_inferior=lambda: SimpleNamespace(read_memory=read), execute=execute)
    monkeypatch.setitem(sys.modules, 'gdb', fake)
    media.gdb_main(config)
    return (json.loads((tmp_path/'media-predicate-result.json').read_text()),
            [json.loads(v) for v in (tmp_path/'media-predicate-events.jsonl').read_text().splitlines()],
            commands, points)


def test_actual_callback_pairs_original_returns_and_detaches(tmp_path, monkeypatch):
    result, events, commands, points = run_fake(tmp_path, monkeypatch)
    assert result['error'] is None and result['unreturned_entries'] == 0
    assert [v['kind'] for v in events] == ['entry', 'return', 'entry', 'return']
    assert all(v['matched_entry'] and v['original_w0'] == 1 for v in events if v['kind'] == 'return')
    assert events[0]['caller_va'] == '0x1234'
    assert commands[-1] == 'detach' and all(not p.enabled for p in points)
    assert not any('set ' in c or 'call ' in c for c in commands)


@pytest.mark.parametrize('fault', ['bad_code', 'read_error'])
def test_runtime_mismatch_or_read_failure_records_error_and_detaches(tmp_path, monkeypatch, fault):
    result, _, commands, points = run_fake(tmp_path, monkeypatch, **{fault: True})
    assert result['error']
    assert commands[-1] == 'detach' and all(not p.enabled for p in points)
    if fault == 'bad_code':
        assert 'continue' not in commands
        assert not (tmp_path/'queue-watch-ready.json').exists()


def test_trace_limit_disables_points_without_stopping_guest(tmp_path, monkeypatch):
    result, events, commands, points = run_fake(tmp_path, monkeypatch, rounds=40)
    assert result['limit_reached'] and events[-1]['kind'] == 'limit'
    assert len(events) == 129 and all(not p.enabled for p in points)
    assert result['error'] is None and commands[-1] == 'detach'


def test_policy_original_return_resolves_bounded_message_record(tmp_path, monkeypatch):
    result, events, commands, points = run_fake(tmp_path, monkeypatch, policy=True)
    assert result['error'] is None and result['unreturned_entries'] == 0
    assert len(points) == 2 and commands[-1] == 'detach'
    assert events[1]['matched_entry'] and events[1]['original_w0'] == 0x171
    selected = events[1]['selected_record']
    assert selected['record_va'] == '0x58fea48'
    assert selected['first_message_id'] == 0x0200a1a8
    assert selected['predicate_va'] == '0x1875c9c'
    assert selected['alternate_first_message_id'] == 0x0200a04a
    assert selected['alternate_message_list_va'] == '0x377c168'
    assert selected['message_selector_va'] == '0x18826e0'
    assert all(events[0]['fields'][name] == 1
               for name in {**media.CAPACITY_FIELDS, **media.MEDIA_STATE_FIELDS})
    assert all(events[0]['fields'][name] == 2 for name in media.MEDIA_BASE_FIELDS)
    assert result['media_observation_revision'] == 2
    assert all(event['media_observation_revision'] == 2 for event in events)
    assert events[1]['host_monotonic_ns'] >= events[0]['host_monotonic_ns']
    assert media.selected_record(None, 0, 0xffff) is None
    with pytest.raises(ValueError, match='bounds'):
        media.selected_record(None, 0, media.TABLE_COUNT)


def test_original_function_and_return_pins():
    import hashlib
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original public AP optional')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == queue.AP_SHA
    for entry, ret in media.POINTS:
        assert raw[entry:entry+8] == media.ENTRY_PREFIX
        assert raw[ret-4:ret] == bytes.fromhex('e003132a')  # MOV w0,w19
        assert raw[ret:ret+4] == bytes.fromhex('f35341a9')  # original restore begins
    for va, expected in ((0x286cfc8, '20af029000601391008c409100600a91c0035fd6'),
                          (0x2879804, 'a0ae02f00060139100c4409100601891c0035fd6')):
        assert raw[va:va+20] == bytes.fromhex(expected)
    entry, ret = media.POLICY_POINT
    assert raw[entry:entry+8] == media.POLICY_PREFIX
    assert raw[ret-4:ret] == bytes.fromhex('e003132a')
    assert int.from_bytes(raw[0x37766b0:0x37766b8], 'little') == media.TABLE_COUNT


def test_original_record_key_matches_selected_message_and_chinese_text():
    import hashlib
    import struct
    root = Path(__file__).parent/'menu-root'
    library = root/'usr/lib/libObj.so'
    strings = root/'usr/share/app/string_simplifiedchinese_horizontal.uxc'
    if not library.is_file() or not strings.is_file():
        pytest.skip('Original public resource assets optional')
    obj, uxc = library.read_bytes(), strings.read_bytes()
    assert hashlib.sha256(obj).hexdigest() == 'c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc'
    assert hashlib.sha256(obj[0x123e3c:0x123e90]).hexdigest() == '52b44e391d26ab4231de2ae5dba5dd227f77c51fb9a0c4206039545720625aee'
    # Original RecordPtr::getResID delegates to123e3c, whose mask strips type
    # bits. For this key kind2 the subsequent kind3 bank insertion is bypassed.
    assert obj[0x123e50:0x123e54] == bytes.fromhex('73660012')
    assert hashlib.sha256(uxc).hexdigest() == 'f136388b71e9431313002aee23f9c972b56e92602123b76b4786e0d3d872fb33'
    header = struct.unpack_from('<I', uxc, 0x5564)[0]
    assert header & 0x03ffffff == 0x0200a1a8
    assert header >> 26 & 31 == 7
    end = uxc.index(b'\0', 0x5568, 0x5700)
    assert uxc[0x5568:end].decode() == '无存储卡。\n无法拍摄动态影像。\n插槽2'


def test_capacity_observation_fields_follow_original_address_getters():
    import struct
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original public AP optional')
    raw = path.read_bytes()
    for label, expected in media.CAPACITY_FIELDS.items():
        va = int(label.split('_')[1], 16)
        # These particular original getters are in LOAD0 (file == VA).
        words = struct.unpack_from('<5I', raw, va)
        first = words[0]
        assert first & 0x9f00001f == 0x90000000  # ADRP x0
        immediate = ((first >> 5 & 0x7ffff) << 2) | (first >> 29 & 3)
        if immediate & (1 << 20):
            immediate -= 1 << 21
        address = (va & ~0xfff) + (immediate << 12)
        for word in words[1:4]:
            assert word & 0xff8003ff == 0x91000000  # ADD x0,x0,#imm[,LSL12]
            address += (word >> 10 & 0xfff) << (12 if word >> 22 & 1 else 0)
        assert words[4] == 0xd65f03c0  # RET
        assert address == expected, label


def _load_segments(raw):
    """Minimal ELF64 PT_LOAD map; the AP's second segment has VA = file + 0x10000."""
    import struct
    assert raw[:4] == b'\x7fELF' and raw[4] == 2
    phoff = struct.unpack_from('<Q', raw, 0x20)[0]
    entsize, count = struct.unpack_from('<HH', raw, 0x36)
    segments = []
    for index in range(count):
        header = phoff+index*entsize
        p_type = struct.unpack_from('<I', raw, header)[0]
        if p_type != 1:
            continue
        offset, vaddr = struct.unpack_from('<QQ', raw, header+8)
        filesz = struct.unpack_from('<Q', raw, header+0x20)[0]
        segments.append((vaddr, offset, filesz))
    return segments

def _va_to_offset(segments, va, size=1):
    for vaddr, offset, filesz in segments:
        if vaddr <= va and va+size <= vaddr+filesz:
            return offset+(va-vaddr)
    raise ValueError(f'{va:#x} outside PT_LOAD segments')

@pytest.mark.parametrize('getter_slot,fields', [(0x20, media.MEDIA_STATE_FIELDS),
                                             (0x08, media.MEDIA_BASE_FIELDS)])
def test_media_state_fields_follow_original_dispatch_getters(getter_slot, fields):
    """Keep the value read API and reset/base accessor separately bound."""
    import struct
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original public AP optional')
    raw = path.read_bytes()
    segments = _load_segments(raw)
    dispatch_base, stride = 0x5584c38, 0x30
    assert raw[_va_to_offset(segments, 0x28bb0c0, 8):][:8] == bytes.fromhex('000440f900001fd6')
    assert raw[_va_to_offset(segments, 0x28bb0dc, 8):][:8] == bytes.fromhex('001040f900001fd6')
    assert fields
    for label, expected in fields.items():
        pid = int(label.split('_')[1], 16)
        row = _va_to_offset(segments, dispatch_base+pid*stride, stride)
        getter = struct.unpack_from('<Q', raw, row+getter_slot)[0]
        assert getter, label
        start = _va_to_offset(segments, getter, 4)
        first = struct.unpack_from('<I', raw, start)[0]
        assert first & 0x9f000000 == 0x90000000, label           # ADRP x0
        immediate = ((first >> 5 & 0x7ffff) << 2) | (first >> 29 & 3)
        if immediate & (1 << 20):
            immediate -= 1 << 21
        address = (getter & ~0xfff) + (immediate << 12)
        for slot in range(1, 8):
            word = struct.unpack_from('<I', raw, start+4*slot)[0]
            if word & 0xff8003e0 == 0x91000000:                   # ADD x0,x0,#imm[,lsl12]
                address += (word >> 10 & 0xfff) << (12 if word >> 22 & 1 else 0)
                continue
            assert word & 0xffc003ff == 0xb9400000, label          # LDR w0,[x0,#imm]
            assert address+(word >> 10 & 0xfff)*4 == expected, label
            assert struct.unpack_from('<I', raw, start+4*(slot+1))[0] == 0xd65f03c0, label
            break
        else:
            pytest.fail(f'{label}: no bounded scalar return')


def test_capacity_like_dispatch_key_is_not_a_media_field():
    """0x1052 must stay unresolved: its validators allow only -15..15."""
    import struct
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original public AP optional')
    raw = path.read_bytes()
    segments = _load_segments(raw)
    assert not any('1052' in name for name in media.MEDIA_STATE_FIELDS)
    assert set(media.UNRESOLVED_FIELDS) == {'dispatch_1052_unresolved_value'}
    for table in (0x56dc8c8, 0x56dc6b8):
        record = _va_to_offset(segments, table, 16)
        range_pointer = struct.unpack_from('<Q', raw, record+8)[0]
        low, high, step = struct.unpack('<iii', raw[_va_to_offset(segments, range_pointer, 12):][:12])
        assert (low, high, step) == (-15, 15, 1)
    relay = _va_to_offset(segments, 0x4b93828, 24)
    assert struct.unpack_from('<6I', raw, relay) == (0x103c, 0x103c, 0x1047, 0x1052, 1, 8)


def test_host_refuses_missing_failed_or_abnormal_trace(tmp_path):
    assert media.observation_error(tmp_path, 0)
    p = tmp_path/'media-predicate-result.json'
    p.write_text(json.dumps({'connected': True, 'error': None, 'cleanup_errors': []}))
    assert media.observation_error(tmp_path, 0) is None
    assert media.observation_error(tmp_path, -15)
    p.write_text(json.dumps({'connected': True, 'error': 'read failed', 'cleanup_errors': []}))
    assert media.observation_error(tmp_path, 0)


@pytest.mark.parametrize('mode', [None, 'media', 'media-policy'])
def test_actual_driver_body_loop_arms_only_before_rec(monkeypatch, mode, tmp_path):
    import ast
    source = Path(__file__).parent/'check-natural-gtk-input.py'
    tree = ast.parse(source.read_text())
    loops = [node for node in ast.walk(tree) if isinstance(node, ast.For)
             and isinstance(node.target, ast.Name) and node.target.id == 'name'
             and isinstance(node.iter, ast.Tuple)
             and [getattr(item, 'value', None) for item in node.iter.elts] ==
                 ['C1', 'SHUTTER_HALF', 'SHUTTER', 'REC']]
    assert len(loops) == 1
    actions = []

    class Watch:
        def __init__(self, run, sequence, owner, trace_mode, autostart):
            assert not autostart and trace_mode == mode

        def start(self):
            actions.append('watch-start')

    class Clock:
        value = 0

        def monotonic(self):
            self.value += 3
            return self.value

        def monotonic_ns(self):
            return 12345

    proof = {'images': [{'snapshot_sequence': 1}]}
    monkeypatch.setattr(queue, 'QueueWatch', Watch)
    monkeypatch.setattr(sys, 'argv', ['probe', '--media-policy-probe'] if mode == 'media-policy' else ['probe'])
    scope = dict(media_probe=mode is not None, sys=sys, run=tmp_path,
                 proof=proof, child=SimpleNamespace(pid=12), queue_watch=None,
                 time=Clock(), idle=lambda: None,
                 action=lambda name, wait: actions.append(name),
                 capture=lambda label, kind: actions.append(label))
    exec(compile(ast.fix_missing_locations(ast.Module(body=loops, type_ignores=[])), str(source), 'exec'), scope)
    assert [name for name in actions if name in ('C1', 'SHUTTER_HALF', 'SHUTTER', 'REC')] == [
        'C1', 'SHUTTER_HALF', 'SHUTTER', 'REC']
    if mode is None:
        assert 'watch-start' not in actions and 'media_rec_submit_host_monotonic_ns' not in proof
    else:
        assert actions.index('SHUTTER') < actions.index('watch-start') < actions.index('REC')
        assert actions.count('watch-start') == 1
