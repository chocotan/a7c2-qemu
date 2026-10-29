"""Host-generated component fixtures only: none is firmware capture evidence."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PIL import Image

_spec = importlib.util.spec_from_file_location('native_card_writeback', Path(__file__).with_name('check_writeback.py'))
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return f'{value:016x}'


def jpeg():
    output = io.BytesIO()
    Image.new('RGB', (24, 16), (19, 103, 211)).save(output, 'JPEG')
    return output.getvalue()


def mp4(frames=4):
    # Encodes a tiny in-memory HOST TEST fixture, never an alleged camera output.
    return subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=blue:size=32x24:rate=4', '-frames:v', str(frames), '-threads', '1',
        '-c:v', 'mpeg4', '-movflags', 'frag_keyframe+empty_moov', '-f', 'mp4', 'pipe:1'],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15).stdout


def trace(data, path, areas=None, token=1, inline=False):
    areas = areas or [(0, len(data))]
    prefix = f'pid=77 token={token}'
    request = (f'FSYS_WRITE_REQUEST {prefix} cookie=0x{token:x} bytes=1288 '
               f'request_fnv1a64={fnv(bytes(1288))} areas={len(areas)} observation_rc=0 '
               f'path_hex={("A:/" + path).encode().hex()} payload_complete=1 '
               f'expected_bytes={len(data)} address_mode=1 media_origin_verified=0')
    ranges = [f'FSYS_WRITE_AREA {prefix} index={i} offset={offset} bytes={length} '
              f'data_fnv1a64={fnv(data[offset:offset + length])} readable=1 '
              f'submitted_bytes={max(4096, (length + 4095) // 4096 * 4096)}'
              for i, (offset, length) in enumerate(areas)]
    submit = f'FSYS_WRITE_SUBMIT {prefix} rc=0 callback_seen={int(inline)}'
    callback = (f'MPR_WRITE_CALLBACK {prefix} cookie=0x{token:x} rc=0 result_copied=1 '
                f'result_fnv1a64={fnv(bytes(0x4d8))} result_bytes=1240 capacity_metric=4294967295')
    finished = f'MPR_WRITE_FINISHED {prefix} cookie=0x{token:x} rc=0 input_copied=1 returned=1'
    returned = f'MPR_WRITE_CALLBACK_RETURN {prefix} returned=1'
    native = (f'FSYS_WRITE_NATIVE_READBACK {prefix} cookie=0x{token:x} rc=0 bytes={len(data)} '
              f'fnv1a64={fnv(data)} eof=1 close_rc=0')
    stages = [callback, finished, returned, submit] if inline else [submit, callback, finished, returned]
    coverage = 'FSYS_WRITE_READBACK_COVERAGE pid=77 records=1 rc=0'
    return '\n'.join([request, *ranges, *stages, native, coverage]) + '\n'


def save_exports(run, export):
    (run / 'SD/export.json').write_text(json.dumps(export))
    first = copy.deepcopy(export)
    first['sequence'] = first['quiesce']['sequence'] = first['flush_lifecycle']['sequence'] = 1
    (run / 'gtk-input-proof.json').write_text(json.dumps({'sd_export': first}))


def make_run(tmp_path, data=None, path='DCIM/HOST-TEST.JPG', areas=None, inline=False):
    data = jpeg() if data is None else data
    run = tmp_path / 'run'
    (run / 'SD').mkdir(parents=True)
    card = run / 'host-sd'
    media = card / path
    media.parent.mkdir(parents=True)
    media.write_bytes(data)
    files = []
    for name, payload in [('INPUT.BIN', b'host test input'),
                          ('private/database/database.bin', b'host test metadata'),
                          ('private/m4root/mediapro.xml', b'<host-test/>'), (path, data)]:
        target = card / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        files.append({'path': name, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()})
    export = {'ok': True, 'bytes': checker.CARD_BYTES, 'host_directory': str(card),
        'host_directory_verified': True, 'original_mount_verified': True,
        'guest_block_sync_confirmed': True, 'original_capture_verified': False,
        'sequence': 2, 'file_count': len(files), 'files': files,
        'quiesce': {'owner_stopped': True, 'original_Fsys_FlushVolume_rc': 0, 'sequence': 2, 'pid': 77, 'drive': 65},
        'flush_lifecycle': {'ok': True, 'resumed': True, 'status': 'resumed', 'sequence': 2, 'pid': 77},
        'directory_commit_status': {'available': True, 'pending': False, 'closed_pending': False}}
    save_exports(run, export)
    (run / 'console.log').write_text(trace(data, path, areas, inline=inline))
    return run, media, export


def edit_log(run, old, new):
    path = run / 'console.log'
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def rejected(result):
    assert not result['writeback_verified'], result
    assert not result['independent_decoded'], result
    assert result['capture_verified'] is False


def test_real_jpeg_unicode_zero_tail_and_inline_completion(tmp_path):
    data = jpeg()
    run, _, _ = make_run(tmp_path, data, 'DCIM/测试.JPG', [(0, len(data)), (4096, 0)], inline=True)
    # Optional OBS prefix is accepted; unrelated legacy records cannot replace new evidence.
    log = run / 'console.log'
    log.write_text('FSYS_ASYNC_WRITE rc=0\n' + ''.join('OBS ' + line + '\n' for line in log.read_text().splitlines()))
    result = checker.inspect(run)
    assert all(result[k] for k in ('range_matches', 'readback_verified', 'native_readback_verified',
                                   'whole_file_verified', 'writeback_verified', 'independent_decoded')), result
    decoded = result['items'][0]['decode']
    with Image.open(io.BytesIO(data)) as image:
        pixels = image.convert('RGB').tobytes()
    assert decoded['pixel_sha256'] == hashlib.sha256(pixels).hexdigest()
    assert (decoded['width'], decoded['height'], decoded['frame_count']) == (24, 16, 1)
    assert result['capture_verified'] is False
    assert result['items'][0]['capture_verified'] is False


def test_original_callback_can_return_before_async_worker_finishes(tmp_path):
    run, _, _ = make_run(tmp_path)
    log = run / 'console.log'
    lines = log.read_text().splitlines()
    finished = next(i for i, line in enumerate(lines) if line.startswith('MPR_WRITE_FINISHED '))
    returned = next(i for i, line in enumerate(lines) if line.startswith('MPR_WRITE_CALLBACK_RETURN '))
    lines[finished], lines[returned] = lines[returned], lines[finished]
    log.write_text('\n'.join(lines) + '\n')
    result = checker.inspect(run)
    assert result['writeback_verified'] and result['independent_decoded'], result
    assert result['capture_verified'] is False


def test_real_mp4_requires_actual_frames_and_null_decode(tmp_path):
    run, _, _ = make_run(tmp_path, mp4(), 'PRIVATE/M4ROOT/CLIP/HOST-TEST.MP4')
    result = checker.inspect(run)
    assert result['writeback_verified'] and result['independent_decoded'], result
    decoded = result['items'][0]['decode']
    assert decoded['frame_count'] == 4 and decoded['duration_seconds'] > 0
    assert (decoded['width'], decoded['height'], decoded['ffmpeg_null_rc']) == (32, 24, 0)
    assert result['capture_verified'] is False


@pytest.mark.parametrize('damage', ['corrupt', 'truncate', 'trailing', 'source-hash'])
def test_readback_corruption_and_length_rejected(tmp_path, damage):
    run, media, export = make_run(tmp_path)
    data = media.read_bytes()
    if damage == 'source-hash':
        edit_log(run, f'data_fnv1a64={fnv(data)}', 'data_fnv1a64=0000000000000000')
    else:
        changed = bytes([data[0] ^ 1]) + data[1:] if damage == 'corrupt' else (
            data[:-1] if damage == 'truncate' else data + b'extra')
        media.write_bytes(changed)
        if damage == 'trailing':
            export['files'][-1].update(bytes=len(changed), sha256=hashlib.sha256(changed).hexdigest())
            save_exports(run, export)
    result = checker.inspect(run)
    rejected(result)
    assert not any(item.get('decode') for item in result['items'])


@pytest.mark.parametrize(('old', 'new'), [
    ('MPR_WRITE_CALLBACK', 'IGNORED_CALLBACK'), ('MPR_WRITE_FINISHED', 'IGNORED_FINISHED'),
    ('rc=0 callback_seen', 'rc=-1 callback_seen'), ('rc=0 result_copied', 'rc=-1 result_copied'),
    ('rc=0 input_copied', 'rc=-1 input_copied'), ('result_copied=1', 'result_copied=0'),
    ('returned=1', 'returned=0'), ('input_copied=1', 'input_copied=0'),
    ('observation_rc=0', 'observation_rc=-14'), ('payload_complete=1', 'payload_complete=0'),
    ('cookie=0x1 rc=0 result', 'cookie=0x2 rc=0 result'), ('readable=1', 'readable=0')])
def test_original_lifecycle_failures_never_decode(tmp_path, old, new):
    run, _, _ = make_run(tmp_path)
    edit_log(run, old, new)
    result = checker.inspect(run)
    rejected(result)
    assert not any(item.get('decode') for item in result['items'])


@pytest.mark.parametrize('where', ['file', 'intermediate', 'host-root', 'run-root', 'hardlink'])
def test_no_symlink_or_hardlink_evidence(tmp_path, where):
    run, media, _ = make_run(tmp_path)
    if where == 'hardlink':
        os.link(media, tmp_path / 'second-link')
    else:
        target = {'file': media, 'intermediate': media.parent,
                  'host-root': run / 'host-sd', 'run-root': run}[where]
        moved = target.with_name(target.name + '-real')
        target.rename(moved)
        target.symlink_to(moved, target_is_directory=moved.is_dir())
    rejected(checker.inspect(run))


@pytest.mark.parametrize('path', [b'A:/../outside.JPG', b'A://DCIM/x.JPG', b'/tmp/x.JPG',
    b'Z:/DCIM/x.JPG', b'a:/DCIM/x.JPG', b'A:/DCIM/\x1b[31mx.JPG', b'A:/DCIM/\xff.JPG', b'A:/DCIM\\x.JPG'])
def test_native_path_escape_unknown_drive_and_invalid_utf8(tmp_path, path):
    run, _, _ = make_run(tmp_path)
    old = ('A:/DCIM/HOST-TEST.JPG').encode().hex()
    edit_log(run, old, path.hex())
    rejected(checker.inspect(run))
    rejected(checker.inspect(run, '../outside.JPG'))
    rejected(checker.inspect(run, '/outside.JPG'))


@pytest.mark.parametrize(('old', 'new'), [('areas=1', 'areas=2'), ('areas=1', 'areas=9'),
    ('index=0', 'index=8'), ('bytes=1288', 'bytes=01288'), ('offset=0', 'offset=18446744073709551616'),
    ('expected_bytes=', 'expected_bytes=0'), ('index=0', 'index=00')])
def test_unknown_areas_numeric_bounds_and_noncanonical_fields(tmp_path, old, new):
    run, _, _ = make_run(tmp_path)
    edit_log(run, old, new)
    rejected(checker.inspect(run))


def test_both_export_sha256_records_must_bind_actual_bytes(tmp_path):
    run, _, export = make_run(tmp_path)
    export['files'][-1]['sha256'] = '0' * 64
    save_exports(run, export)
    result = checker.inspect(run)
    rejected(result)
    assert 'SHA256' in result['items'][0]['error']


def test_holes_only_establish_range_matches(tmp_path):
    data = jpeg()
    run, _, _ = make_run(tmp_path, data, areas=[(0, 20), (30, len(data) - 30)])
    result = checker.inspect(run)
    rejected(result)
    assert not result['whole_file_verified']
    assert 'sequential' in result['error']


@pytest.mark.parametrize('duplicate', [False, True])
def test_overlapping_or_duplicate_extents_rejected(tmp_path, duplicate):
    data = jpeg()
    areas = [(0, len(data)), (0 if duplicate else 10, 20)]
    run, _, _ = make_run(tmp_path, data, areas=areas)
    rejected(checker.inspect(run))


@pytest.mark.parametrize('ambiguity', ['same-path', 'duplicate-callback', 'zero-token', 'orphan', 'reused-cookie'])
def test_ambiguous_tokens_or_duplicate_callbacks_rejected(tmp_path, ambiguity):
    run, media, _ = make_run(tmp_path)
    log = run / 'console.log'
    lines = log.read_text().splitlines()
    if ambiguity == 'same-path':
        log.write_text(log.read_text() + trace(media.read_bytes(), 'DCIM/HOST-TEST.JPG', token=2))
    elif ambiguity == 'duplicate-callback':
        log.write_text(log.read_text() + next(line for line in lines if line.startswith('MPR_WRITE_CALLBACK')) + '\n')
    elif ambiguity == 'zero-token':
        edit_log(run, 'token=1', 'token=0')
    elif ambiguity == 'orphan':
        log.write_text(log.read_text() + 'FSYS_WRITE_SUBMIT pid=77 token=2 rc=0 callback_seen=0\n')
    else:
        other = trace(media.read_bytes(), 'DCIM/OTHER.JPG', token=2).replace('cookie=0x2', 'cookie=0x1')
        log.write_text(log.read_text() + other)
    rejected(checker.inspect(run))


@pytest.mark.parametrize('damage', ['rc', 'stopped', 'resumed', 'pending', 'sequence', 'owner', 'bool-rc', 'first-sha', 'root'])
def test_two_original_exports_and_clean_quiesce_required(tmp_path, damage):
    run, _, export = make_run(tmp_path)
    if damage == 'rc':
        export['quiesce']['original_Fsys_FlushVolume_rc'] = -1
    elif damage == 'stopped':
        export['quiesce']['owner_stopped'] = False
    elif damage == 'resumed':
        export['flush_lifecycle']['resumed'] = False
    elif damage == 'pending':
        export['directory_commit_status']['pending'] = True
    elif damage == 'sequence':
        export['flush_lifecycle']['sequence'] = 8
    elif damage == 'owner':
        export['quiesce']['pid'] = export['flush_lifecycle']['pid'] = 78
    elif damage == 'bool-rc':
        export['quiesce']['original_Fsys_FlushVolume_rc'] = False
    elif damage == 'root':
        export['host_directory'] = str(tmp_path)
    save_exports(run, export)
    if damage == 'first-sha':
        first_path = run / 'gtk-input-proof.json'
        first = json.loads(first_path.read_text())
        first['sd_export']['files'][-1]['sha256'] = '0' * 64
        first_path.write_text(json.dumps(first))
    rejected(checker.inspect(run))


@pytest.mark.parametrize(('old', 'new'), [
    ('FSYS_WRITE_NATIVE_READBACK', 'IGNORED_NATIVE_READBACK'),
    ('MPR_WRITE_CALLBACK_RETURN', 'IGNORED_CALLBACK_RETURN'),
    ('eof=1', 'eof=0'), ('close_rc=0', 'close_rc=-5'),
    ('returned=1\nFSYS_WRITE_NATIVE_READBACK', 'returned=0\nFSYS_WRITE_NATIVE_READBACK'),
    ('result_bytes=1240', 'result_bytes=1096'), ('address_mode=1', 'address_mode=2'),
    ('submitted_bytes=4096', 'submitted_bytes=4095')])
def test_native_readback_callback_return_and_virtual_mode_required(tmp_path, old, new):
    run, _, _ = make_run(tmp_path)
    edit_log(run, old, new)
    rejected(checker.inspect(run))


@pytest.mark.parametrize('damage', ['bytes', 'hash', 'read-error'])
def test_native_cross_channel_readback_must_match(tmp_path, damage):
    run, _, _ = make_run(tmp_path)
    log = run / 'console.log'
    lines = log.read_text().splitlines()
    native = lines[-2]
    assert native.startswith('FSYS_WRITE_NATIVE_READBACK')
    if damage == 'bytes':
        native = native.replace(f'bytes={len(jpeg())}', f'bytes={len(jpeg()) - 1}')
    elif damage == 'hash':
        native = native.replace(f'fnv1a64={fnv(jpeg())}', 'fnv1a64=0000000000000000')
    else:
        native = native.replace('rc=0 bytes=', 'rc=-5 bytes=')
    log.write_text('\n'.join([*lines[:-2], native, lines[-1]]) + '\n')
    result = checker.inspect(run)
    rejected(result)
    if damage == 'hash':
        assert result['readback_verified'] and result['range_matches']
        assert not result['native_readback_verified']


def test_incomplete_observation_or_unselected_pending_token_refuses_all(tmp_path):
    run, media, _ = make_run(tmp_path)
    log = run / 'console.log'
    original = log.read_text()
    log.write_text(original + 'FSYS_WRITE_COVERAGE_INCOMPLETE pid=77 missed=1\n')
    rejected(checker.inspect(run))
    pending = trace(media.read_bytes(), 'private/PENDING.BIN', token=2).splitlines()
    log.write_text(original + '\n'.join(pending[:2]) + '\n')
    rejected(checker.inspect(run, 'DCIM/HOST-TEST.JPG'))


@pytest.mark.parametrize('damage', ['missing', 'count', 'rc', 'owner', 'duplicate-native'])
def test_readback_coverage_is_required_and_must_close_exact_token_set(tmp_path, damage):
    run, _, _ = make_run(tmp_path)
    log = run / 'console.log'
    text = log.read_text()
    if damage == 'missing':
        text = text[:text.index('FSYS_WRITE_READBACK_COVERAGE')]
    elif damage == 'count':
        text = text.replace('records=1 rc=0', 'records=2 rc=0')
    elif damage == 'rc':
        text = text.replace('records=1 rc=0', 'records=1 rc=-11')
    elif damage == 'owner':
        text = text.replace('COVERAGE pid=77', 'COVERAGE pid=78')
    else:
        lines = text.splitlines()
        text = '\n'.join([*lines[:-1], lines[-2], lines[-1]]) + '\n'
    log.write_text(text)
    rejected(checker.inspect(run))


def test_repeated_native_readback_requires_separate_complete_coverage_batch(tmp_path):
    run, _, _ = make_run(tmp_path)
    log = run / 'console.log'
    lines = log.read_text().splitlines()
    log.write_text(log.read_text() + '\n'.join(lines[-2:]) + '\n')
    result = checker.inspect(run)
    assert result['writeback_verified'] and result['independent_decoded'], result
    assert len(result['native_readback_coverage']) == 2
    assert len(result['items'][0]['native_readbacks']) == 2


def test_submitted_padding_is_file_content_until_original_truncate(tmp_path):
    data = b'first' + bytes(4096 - 5) + b'second'
    run, media, export = make_run(tmp_path, data, areas=[(0, 4096), (4096, 6), (8192, 0)])
    result = checker.inspect(run)
    assert result['writeback_verified'] and result['native_readback_verified'], result
    assert not result['independent_decoded'] and not result['capture_verified']
    assert [a['bytes'] for a in result['items'][0]['areas']] == [4096, 6, 0]
    # Removing middle padding is not how the original sequential writer behaves.
    media.write_bytes(b'firstsecond')
    export['files'][-1].update(bytes=11, sha256=hashlib.sha256(b'firstsecond').hexdigest())
    save_exports(run, export)
    rejected(checker.inspect(run))


def test_zero_contribution_tail_requires_empty_hash_and_expected_offset(tmp_path):
    data = jpeg()
    run, _, _ = make_run(tmp_path, data, areas=[(0, len(data)), (4096, 0)])
    edit_log(run, f'data_fnv1a64={fnv(b"")}', 'data_fnv1a64=0000000000000000')
    rejected(checker.inspect(run))


def test_legacy_ack_host_file_and_origin_booleans_are_not_capture(tmp_path):
    run, _, export = make_run(tmp_path)
    edit_log(run, 'media_origin_verified=0', 'media_origin_verified=1')
    export['original_capture_verified'] = True
    save_exports(run, export)
    result = checker.inspect(run)
    assert result['writeback_verified'] and result['capture_verified'] is False
    (run / 'console.log').write_text('OBS FSYS_ASYNC_WRITE rc=0 media_origin_verified=1\n')
    rejected(checker.inspect(run))


@pytest.mark.parametrize('data', [b'\xff\xd8not entropy\xff\xd9', jpeg()[:-10]])
def test_real_jpeg_decode_rejects_markers_and_truncation_after_valid_hashes(tmp_path, data):
    run, _, _ = make_run(tmp_path, data)
    result = checker.inspect(run)
    assert result['writeback_verified'] and not result['independent_decoded'], result
    assert result['capture_verified'] is False
    assert 'decoder' in result['items'][0]['error']


def test_mp4_metadata_without_frames_cannot_pass_decode(tmp_path):
    run, _, _ = make_run(tmp_path, mp4(frames=0), 'DCIM/HOST-TEST.MP4')
    result = checker.inspect(run)
    assert result['writeback_verified'] and not result['independent_decoded'], result
    assert result['capture_verified'] is False


def test_read_bounds_large_offset_partial_and_cli(tmp_path):
    run, media, export = make_run(tmp_path)
    cli = subprocess.run([sys.executable, str(Path(checker.__file__)), str(run),
                          '--mediafile', 'DCIM/HOST-TEST.JPG'], capture_output=True, text=True, timeout=15)
    assert cli.returncode == 0 and json.loads(cli.stdout)['capture_verified'] is False, cli.stderr
    offset = checker.MAX_SOURCE + 4096
    with media.open('r+b') as stream:
        stream.seek(offset)
        stream.write(b'test')
    export['files'][-1].update(bytes=offset + 4, sha256='0' * 64)
    save_exports(run, export)
    log = trace(b'test', 'DCIM/HOST-TEST.JPG')
    log = log.replace('offset=0', f'offset={offset}').replace('expected_bytes=4', f'expected_bytes={offset + 4}')
    (run / 'console.log').write_text(log)
    result = checker.inspect(run)
    rejected(result)
    assert not result['readback_verified'], result
    with (run / 'console.log').open('wb') as stream:
        stream.truncate(checker.MAX_LOG + 1)
    rejected(checker.inspect(run))
