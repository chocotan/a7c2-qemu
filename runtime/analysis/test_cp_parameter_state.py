"""Source-pinned CP4063 field consumers; no guest/VM or real-device access."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import runpy
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
MODELS = BASE / 'device-models'
REPORT = BASE.parents[1] / 'report/cp-parameter-state'
CP_HASH = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    directory = tmp_path_factory.mktemp('cp-parameter-state')
    binary = directory / 'state'
    command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
               str(MODELS / 'cp-parameter-batch.c'),
               str(MODELS / 'cp-parameter-state.c'),
               str(MODELS / 'test-cp-parameter-state.c'), '-o', str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


def run(binary, *args):
    environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                       UBSAN_OPTIONS='halt_on_error=1')
    result = subprocess.run([str(binary), *map(str, args)], env=environment,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def schema():
    return [tuple(int(v, 16) for v in row) for row in re.findall(
        r'\{(0x[0-9a-f]+),(0x[0-9a-f]+),(0x[0-9a-f]+)\}',
        (MODELS / 'cp-parameter-batch.c').read_text())]


def source_map():
    return json.loads((REPORT / 'source-map.json').read_text())


def test_c_boundaries_and_full_byte_domains(compiled):
    assert run(compiled) == ''


def test_source_common_local_stores_match_c_image(compiled, tmp_path):
    directory = BASE.parents[1] / 'report/cp-parameter-initializer'
    extractor = runpy.run_path(str(directory / 'extract_common.py'))
    trace = extractor['extract'](BASE / 'menu-root/cp/cpapp-b.bin')
    assert trace == json.loads((directory / 'common-local-stores.json').read_text())
    assert extractor['render'](trace) == (MODELS / 'cp-parameter-common-init.inc').read_text()
    assert trace['instructions'] == 195 and trace['known_bytes'] == 694
    assert not trace['initialization_complete'] and not trace['published'] and not trace['capture_verified']
    output = tmp_path / 'common.bin'
    run(compiled, 'common', output)
    raw = output.read_bytes()
    assert len(raw) == 0xd64 + (0xd64 + 7)//8
    image, known = raw[:0xd64], raw[0xd64:]
    expected = bytearray([0xa5]*0xd64)
    mask = bytearray((0xd64+7)//8)
    values = bytes.fromhex(trace['data'])
    for row in trace['ranges']:
        offset, size, data = row['offset'], row['bytes'], row['data_offset']
        assert 0 <= offset < offset + size <= 0xd64 and data + size <= len(values)
        expected[offset:offset+size] = values[data:data+size]
        for index in range(offset, offset+size):
            assert not mask[index//8] & (1 << (index%8))
            mask[index//8] |= 1 << (index%8)
    assert image == expected and known == mask
    assert sum(v.bit_count() for v in known) == 694
    for offset, value in ((0x214,2),(0x344,1),(0x668,5),(0x670,5),(0x678,4),(0x67c,8),(0xd5c,1)):
        assert image[offset:offset+4] == value.to_bytes(4,'little')
    assert image[0x1c8:0x1d0] == bytes(8)
    assert not known[0] & 15  # The root header is not invented by this phase.
    wrong = tmp_path / 'not-original.bin'
    wrong.write_bytes(b'not the original CP')
    with pytest.raises(ValueError, match='not the pinned public CP image'):
        extractor['extract'](wrong)


def test_flag0_default_local_stores_match_source_projection(compiled,tmp_path):
    directory=BASE.parents[1]/'report/cp-parameter-defaults'
    trace=json.loads((directory/'default-local-stores.json').read_text())
    assert trace['instructions']==999 and trace['default_written_bytes']==2223
    assert trace['composed_known_bytes']==2913 and trace['composed_unknown_bytes']==515
    assert not trace['initialization_complete'] and not trace['published']
    common=json.loads((BASE.parents[1]/'report/cp-parameter-initializer/common-local-stores.json').read_text())
    image,mask=bytearray([0xa5]*0xd64),bytearray((0xd64+7)//8)
    for phase in (common,trace):
        values=bytes.fromhex(phase['data'])
        for row in phase['ranges']:
            offset,size,at=row['offset'],row['bytes'],row['data_offset']
            image[offset:offset+size]=values[at:at+size]
            for i in range(offset,offset+size):mask[i//8]|=1<<(i%8)
    output=tmp_path/'defaults.bin';run(compiled,'defaults',output)
    assert output.read_bytes()==image+mask
    assert sum(v.bit_count() for v in mask)==2913
    for row in trace['composed_unknown_ranges']:
        assert image[row['offset']:row['offset']+row['bytes']]==bytes([0xa5])*row['bytes']
        assert all(not mask[i//8]&(1<<(i%8)) for i in range(row['offset'],row['offset']+row['bytes']))
    assert image[0x28:0x2c]==(5).to_bytes(4,'little')
    assert image[0xd5c:0xd60]==bytes(4)


def test_classification_and_table_integrity():
    data = source_map()
    assert len(data['slots']) == len(data['pins']) == 190
    assert len(data['fields']) == 303
    assert sum(s['config_closed'] for s in data['slots']) == 170
    assert sum(s['semantic_closed'] for s in data['slots']) == 168
    assert sum(s['config_closed'] and not s['semantic_closed'] for s in data['slots']) == 6
    assert sum(not s['config_closed'] and not s['semantic_closed'] for s in data['slots']) == 16
    assert [s['slot'] for s in data['slots'] if s['noop']] == [178, 185, 186]
    slots = schema()
    for index, s in enumerate(data['slots']):
        assert s['slot'] == index and s['opcode'] == slots[index][0]
        fields = data['fields'][s['first']:s['first'] + s['count']]
        assert len(fields) == s['count'] and bool(fields) == s['config_closed']
        for f in fields:
            assert f['slot'] == index
            assert 0 <= f['image_offset'] < f['image_offset'] + f['width'] <= 0xd64
            assert f['width'] in (1, 2, 4) and f['source_width'] in (0, 1, 2, 4)
            if f['source_width']:
                assert 8 <= f['wire_offset'] < f['wire_offset'] + f['source_width'] <= slots[index][2]
            assert not f['image_offset'] <= 0x1c8 < f['image_offset'] + f['width']
    assert data['slots'][3]['config_closed'] and not data['slots'][3]['semantic_closed']
    assert data['slots'][15]['old_reads'] == [[0x1f4, 1]]


def test_all_190_raw_handlers_and_reproducible_source_proof():
    path = BASE / 'menu-root/cp/cpapp-b.bin'
    if not path.is_file():
        pytest.skip('public CP asset is prepared separately; no image is redistributed')
    cp = path.read_bytes()
    assert len(cp) == 18090880 and hashlib.sha256(cp).hexdigest() == CP_HASH
    data = source_map()
    for pin in data['pins']:
        assert 0x108000 <= pin['va'] < pin['va'] + pin['size'] <= 0x1248b80
        raw = pin['va'] - 0x108000
        assert hashlib.sha256(cp[raw:raw + pin['size']]).hexdigest() == pin['sha256']
        matches = [struct.unpack_from('<5I', cp, 0x10fab8c - 0x108000 + i * 20)
                   for i in range(0x15e)
                   if struct.unpack_from('<I', cp, 0x10fab8c - 0x108000 + i * 20)[0] == pin['opcode']]
        assert len(matches) == 1 and matches[0][1] == pin['va'] | 1
    for va, length, digest in [
        (0x8da08c, 0x8f2, '9dec451364f09aa70d660613efd32f627aa811ad09036aa0544cff7c42c3c107'),
        (0x35ce2c, 0x144, '61d05e099e3ccebc39fdc58a4f0099a4efc3413e50fb663694005ec349bfea31'),
        (0x10fab8c, 0x15e * 20, 'c9c11a7c68b25950ad8946fc35f2796a670f7eb2f0e9a5063747fa35bfe48e18'),
    ]:
        assert hashlib.sha256(cp[va - 0x108000:va - 0x108000 + length]).hexdigest() == digest
    pytest.importorskip('capstone')
    spec = importlib.util.spec_from_file_location('cp_parameter_source_generator', REPORT / 'generate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    regenerated, assembly = module.generate(cp)
    assert regenerated == data
    generated = module.render(data)
    assert generated == (REPORT / 'generated-table.inc').read_text()
    assert generated in (MODELS / 'cp-parameter-state.c').read_text()
    assert assembly == (REPORT / 'handlers.asm').read_text()


def expected(packet):
    image, known = bytearray(0xd64), bytearray((0xd64 + 7) // 8)
    data = source_map()
    slots = schema()
    for f in data['fields']:
        offset = slots[f['slot']][1]
        source = packet[offset:offset + slots[f['slot']][2]]
        if f['condition_zero'] and source[8] != 0:
            continue
        mode = f['mode']
        value = int.from_bytes(source[f['wire_offset']:f['wire_offset'] + f['source_width']],
                               'little', signed=mode == 'SIGN')
        if mode == 'CONST':
            value = f['argument']
        elif mode == 'BOOL':
            value = int(value != 0)
        elif mode == 'EQ':
            value = int(value == f['argument'])
        elif mode == 'ORBOOL':
            value = int(value != 0 or source[f['argument']] != 0)
        value &= (1 << (f['width'] * 8)) - 1
        destination = f['image_offset']
        image[destination:destination + f['width']] = value.to_bytes(f['width'], 'little')
        for index in range(destination, destination + f['width']):
            known[index // 8] |= 1 << (index % 8)
    masks = bytes(v for s in data['slots'] for v in (s['config_closed'], s['semantic_closed']))
    return bytes(image + known) + masks


def verify_packet(compiled, tmp_path, packet):
    source, output = tmp_path / 'input.bin', tmp_path / 'readback.bin'
    source.write_bytes(packet)
    assert run(compiled, 'packet', source, output) == ''
    actual = output.read_bytes()
    assert actual == expected(packet)
    return actual


@pytest.mark.parametrize('pattern', [0, 1, 0x7f, 0x80, 0xff, 0x12345678])
def test_host_payload_domains_and_opaque_headers(compiled, tmp_path, pattern):
    packet = bytearray((i * pattern + 19) & 255 for i in range(0xa04))
    for opcode, offset, _ in [(0x4063, 0, 8), *schema()]:
        packet[offset] = 5
        struct.pack_into('<H', packet, offset + 2, opcode)
    verify_packet(compiled, tmp_path, packet)


def test_actual_same_run_batch_consumption(compiled, tmp_path):
    console = BASE / 'menu-runs/run-nzx01uc3/console.log'
    if not console.is_file():
        pytest.skip('same-run console is local evidence, not a redistributed fixture')
    text = console.read_text(errors='replace')
    envelope = re.findall(r'OBS NATIVE_CP_BACKGROUND_INPUT_AUDIT pid=258 tid=381 sequence=49 .*', text)
    assert len(envelope) == 1
    assert 'destination=0x90030001 bytes=2564 source=0x80020002' in envelope[0]
    assert 'size_known=1 source_known=1 bytes_complete=1 complete=1' in envelope[0]
    chunks = re.findall(r'OBS NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES pid=258 tid=381 sequence=49 offset=(\d+) bytes=(\d+) raw=([0-9a-f]+)', text)
    assert len(chunks) == 21
    packet = bytearray()
    for offset, length, raw in chunks:
        block = bytes.fromhex(raw)
        assert int(offset) == len(packet) and int(length) == len(block)
        packet += block
    assert len(packet) == 2564
    assert packet[:8] == bytes.fromhex('0500634027000080')
    pins = json.loads((REPORT / 'actual-batch-evidence.json').read_text())
    assert hashlib.sha256(packet).hexdigest() == pins['packet_sha256']
    assert hashlib.sha256(console.read_bytes()).hexdigest() == pins['console_sha256']
    actual = verify_packet(compiled, tmp_path, packet)
    image, known = actual[:0xd64], actual[0xd64:0xd64 + (0xd64 + 7) // 8]
    assert sum(v.bit_count() for v in known) == pins['known_bytes']
    assert not known[0x1c8 // 8] & (1 << (0x1c8 % 8))
    # Independent source examples: 4006 bulk copy, LE16, zero extension,
    # boolean normalization, and a six-slot unmodeled business call boundary.
    assert image[0x934:0x938] == b'\0' * 4
    assert image[0x93a:0x93c] == b'\0\0'
    assert image[0x940] == 0x37
    assert image[0x944:0x964] == packet[0x14 + 0x14:0x14 + 0x34]
    assert image[0xb2c:0xb30] == bytes.fromhex('01000000')
    assert image[0x574] == 1 and image[0xbb8] == 0
    assert image[0x2f4:0x2fc] == b'\0' * 8
    # New explicit virtual common phase composed with this immutable historical
    # input; this does not backfill the original run's constructor/publication.
    source, output = tmp_path/'with-common-input.bin', tmp_path/'with-common-output.bin'
    source.write_bytes(packet)
    run(compiled,'packet-common',source,output)
    composed = output.read_bytes()
    stage = json.loads((BASE.parents[1]/'report/cp-parameter-initializer/common-local-stores.json').read_text())
    expected_image, expected_mask = bytearray(0xd64), bytearray((0xd64+7)//8)
    values = bytes.fromhex(stage['data'])
    for row in stage['ranges']:
        off,n,at = row['offset'],row['bytes'],row['data_offset']
        expected_image[off:off+n] = values[at:at+n]
        for index in range(off,off+n): expected_mask[index//8] |= 1 << (index%8)
    for index in range(0xd64):
        if known[index//8] & (1 << (index%8)):
            expected_image[index] = image[index]
            expected_mask[index//8] |= 1 << (index%8)
    assert composed[:0xd64] == expected_image
    assert composed[0xd64:0xd64+len(expected_mask)] == expected_mask
    assert expected_mask[0x1c8//8] & (1 << (0x1c8%8)) and expected_image[0x1c8] == 0
    assert sum(v.bit_count() for v in expected_mask) == 1544
    assert 0xd64 - 1544 == 1884  # Still partial; semantic/publication masks unchanged.
    assert composed[0xd64+len(expected_mask):] == actual[0xd64+len(expected_mask):]
    defaults=json.loads((BASE.parents[1]/'report/cp-parameter-defaults/default-local-stores.json').read_text())
    all_image,all_mask=bytearray(0xd64),bytearray((0xd64+7)//8)
    for phase in (stage,defaults):
        values=bytes.fromhex(phase['data'])
        for row in phase['ranges']:
            off,n,at=row['offset'],row['bytes'],row['data_offset']
            all_image[off:off+n]=values[at:at+n]
            for i in range(off,off+n):all_mask[i//8]|=1<<(i%8)
    for i in range(0xd64):
        if known[i//8]&(1<<(i%8)):
            all_image[i]=image[i];all_mask[i//8]|=1<<(i%8)
    run(compiled,'packet-defaults',source,output)
    with_defaults=output.read_bytes()
    assert with_defaults[:0xd64]==all_image and with_defaults[0xd64:0xd64+len(all_mask)]==all_mask
    assert sum(v.bit_count() for v in all_mask)==2973 and 0xd64-2973==455
    assert with_defaults[0xd64+len(all_mask):]==actual[0xd64+len(all_mask):]
