import hashlib
from pathlib import Path
import struct
import pytest
from media_state_readback import CELLS, command, parse


def test_readback_binds_only_observed_task_and_contains_no_write():
    text = b'OBS FRAME_DRAW_ENTER call=1 tid=302 this=0xff\nOBS FRAME_DRAW_ENTER call=2 tid=302 x=1\n'
    generated = command(text)
    assert '/proc/302/maps' in generated and generated.count('/proc/302/mem') == len(CELLS)
    assert generated.count('/simulation/menu-readmem') == len(CELLS)
    assert 'else echo MEDIA_STATE_MAPPING_UNAVAILABLE\nfi\ntrue' in generated
    assert max(map(len, generated.encode().splitlines())) < 200
    assert 'exit ' not in generated  # never terminate the runner's serial shell
    assert not any(item in generated for item in ('--cancel', 'Backup_write', '>', 'mount ', 'kill '))
    with pytest.raises(ValueError, match='unique'):
        command(b'')
    with pytest.raises(ValueError, match='unique'):
        command(text+b'OBS FRAME_DRAW_ENTER call=3 tid=303 x=1\n')


def test_parse_preserves_raw_bytes_and_bad_read_status():
    data = b'MEDIA_MOUNT_LOGICAL_1_BEGIN\r\nraw bytes=4\r\n02 00 00 00\r\nMEDIA_MOUNT_LOGICAL_1_RC=0\r\n'
    data += b'MEDIA_MOUNT_LOGICAL_2_BEGIN\nBad address\nMEDIA_MOUNT_LOGICAL_2_RC=1\n'
    for label, _ in CELLS[2:]:
        data += f'{label}_BEGIN\nraw selection\n{label}_RC=0\n'.encode()
    result = parse(data)
    assert [read['returncode'] for read in result['reads']] == [0, 1]+[0]*(len(CELLS)-2)
    assert '02 00 00 00' in result['reads'][0]['raw_output']
    assert result['physical_card_slots'] == 1 and result['capture_verified'] is False
    with pytest.raises(ValueError):
        parse(data+data)


def test_multiline_shell_echo_does_not_enter_field_output():
    echoed = command(b'OBS FRAME_DRAW_ENTER call=1 tid=302 x=1\n')
    data = ('\n'.join('> '+line for line in echoed.splitlines())+'\n').encode()
    for index, (label, _) in enumerate(CELLS):
        data += f'{label}_BEGIN\r\nREADMEM field={index}\r\n{label}_RC=0\r\n'.encode()
    result = parse(data)
    assert len(result['reads']) == len(CELLS)
    for index, row in enumerate(result['reads']):
        assert row['raw_output'] == f'READMEM field={index}\r\n'


def test_missing_mapping_returns_without_exiting_shell():
    import os
    import subprocess
    # /bin/busybox is a guest path; substitute only that executable on host.
    generated = command(f'OBS FRAME_DRAW_ENTER call=1 tid={os.getpid()} x=1\n'.encode())
    generated = generated.replace('/bin/busybox grep', 'grep')
    result = subprocess.run(['sh', '-c', generated+'; echo HOST_SHELL_STILL_ALIVE'],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert 'MEDIA_STATE_MAPPING_UNAVAILABLE' in result.stdout
    assert 'HOST_SHELL_STILL_ALIVE' in result.stdout


def test_original_getter_cell_arithmetic():
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original AP asset optional')
    raw = path.read_bytes()
    assert len(raw) == 99960744
    assert hashlib.sha256(raw).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    # These file-backed code VAs have identical file offsets in this pinned ELF.
    for va, expected, words in (
        (0x28787f0, CELLS[0][1], (0x9002aec0, 0x91136000, 0x9140c000, 0x9123e000, 0xd65f03c0)),
        (0x2878818, CELLS[1][1], (0x9002aec0, 0x91136000, 0x9140c000, 0x91246000, 0xd65f03c0))):
        actual = struct.unpack_from('<5I', raw, va)
        assert actual == words
        adrp = actual[0]
        displacement = ((adrp >> 5 & 0x7ffff) << 2) | (adrp >> 29 & 3)
        if displacement & (1 << 20):
            displacement -= 1 << 21
        address = (va & ~0xfff) + (displacement << 12)
        for instruction in actual[1:4]:
            address += ((instruction >> 10) & 0xfff) << (12 if instruction & (1 << 22) else 0)
        assert address == expected


def test_selection_object_getters_and_actual_value_consumers():
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original AP asset optional')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    for va, label, final_add in ((0x2867680, 'MEDIA_SELECTION_STILL', 0x910c8000),
                                 (0x28676a8, 'MEDIA_SELECTION_MOVIE', 0x910d0000)):
        words = struct.unpack_from('<5I', raw, va)
        assert words == (0xb002af40, 0x91136000, 0x91407800, final_add, 0xd65f03c0)
        adrp = words[0]
        displacement = ((adrp >> 5 & 0x7ffff) << 2) | (adrp >> 29 & 3)
        if displacement & (1 << 20):
            displacement -= 1 << 21
        address = (va & ~0xfff) + (displacement << 12)
        for instruction in words[1:4]:
            address += ((instruction >> 10) & 0xfff) << (12 if instruction & (1 << 22) else 0)
        assert address + 0x10 == dict(CELLS)[label]
    # Original still/movie consumers load w19 from getter's object+0x10.
    assert raw[0x2b13d98:0x2b13d9c] == bytes.fromhex('131040b9')
    assert raw[0x2b13e68:0x2b13e6c] == bytes.fromhex('131040b9')


def test_live_selection_is_distinct_from_metadata_and_read_by_business():
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original AP asset optional')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    for va, label, last in ((0x286766c, 'MEDIA_SELECTION_STILL_LIVE', 0x910c6000),
                            (0x2867694, 'MEDIA_SELECTION_MOVIE_LIVE', 0x910ce000)):
        words = struct.unpack_from('<5I', raw, va)
        assert words == (0xb002af40, 0x91136000, 0x91407800, last, 0xd65f03c0)
        # All these pinned getters have the same resolved ADRP base and adds.
        assert dict(CELLS)[label] == 0x7e50000+0x4d8+0x1e000+((last >> 10) & 0xfff)
    # The explicit movie setter puts getter2867694's pointer in x22, then
    # stores the input through that pointer; metadata+0x10 is a separate path.
    assert raw[0x1bf5d70:0x1bf5d78] == bytes.fromhex('49c63194f60300aa')
    assert raw[0x1bf5dc4:0x1bf5dcc] == bytes.fromhex('a02b40f9130000b9')
    # Original business predicate reads live movie selection (then CMP #1).
    assert raw[0x187599c:0x18759a8] == bytes.fromhex('3ec73f94000040b91f040071')


def test_product_model_and_feature_index_original_read_write_pins():
    path = Path(__file__).parent/'menu-root/usr/lib/appFw.so'
    if not path.is_file():
        pytest.skip('Original AP asset optional')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    # This getter is THREE instructions, not the five-instruction media form.
    assert raw[0x285be30:0x285be3c] == bytes.fromhex('a0af02b000601391c0035fd6')
    assert dict(CELLS)['FEATURE_PRODUCT_MODEL_LIVE'] == 0x7e50000+0x4d8
    # Original update reads this getter before its <=25 jump-table dispatch.
    assert raw[0x1797ba0:0x1797ba8] == bytes.fromhex('a4104394130040b9')
    # Common cases store w1 to ADRP5bc3000 +5b0; zero case stores wzr there.
    assert raw[0x1797bbc:0x1797bc0] == bytes.fromhex('60210290')
    assert raw[0x1797bd4:0x1797bd8] == bytes.fromhex('1fb005b9')
    assert raw[0x1797bec:0x1797bf0] == bytes.fromhex('01b005b9')
    assert dict(CELLS)['FEATURE_PRODUCT_TABLE_INDEX'] == 0x5bc3000+0x5b0
