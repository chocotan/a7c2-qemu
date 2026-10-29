#!/usr/bin/env python3
"""Read-only original-write/readback consistency check; never verifies capture."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile
import time
import unicodedata

# Import this repository's reader only, without searching sys.path or loading plugins.
NATIVE = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    'native_writeback_evidence_reader', NATIVE / 'report/capture-evidence/check_evidence.py')
_reader = importlib.util.module_from_spec(_spec)
# Executing the exact source avoids creating bytecode beside existing evidence tools.
exec(compile(_spec.loader.get_source(_spec.name), _spec.origin, 'exec'), _reader.__dict__)
require = _reader.require

CARD_BYTES = 256_000_000_000
MAX_LOG = 64 * 1024**2
MAX_JSON = 4 * 1024**2
MAX_SOURCE = 128 * 1024**2
MAX_READ = 512 * 1024**2
MAX_PIXELS = 100_000_000
MAX_TOKENS = 32
COVERAGE_TAG = 'FSYS_WRITE_READBACK_COVERAGE'
MAX_PATH = 0x40e
FNV_INIT = 14695981039346656037
FNV_PRIME = 1099511628211
TAGS = ('FSYS_WRITE_REQUEST', 'FSYS_WRITE_AREA', 'FSYS_WRITE_SUBMIT',
        'MPR_WRITE_CALLBACK', 'MPR_WRITE_FINISHED', 'MPR_WRITE_CALLBACK_RETURN',
        'FSYS_WRITE_NATIVE_READBACK')
FIELDS = {
    TAGS[0]: ('pid token cookie bytes request_fnv1a64 areas observation_rc path_hex '
              'payload_complete expected_bytes address_mode media_origin_verified').split(),
    TAGS[1]: 'pid token index offset bytes data_fnv1a64 readable submitted_bytes'.split(),
    TAGS[2]: 'pid token rc callback_seen'.split(),
    TAGS[3]: 'pid token cookie rc result_copied result_fnv1a64'.split(),
    TAGS[4]: 'pid token cookie rc input_copied returned'.split(),
    TAGS[5]: 'pid token returned'.split(),
    TAGS[6]: 'pid token cookie rc bytes fnv1a64 eof close_rc'.split(),
    COVERAGE_TAG: 'pid records rc'.split(),
}


def integer(text, maximum=(1 << 64) - 1, signed=False):
    pattern = r'(?:0|-[1-9][0-9]*|[1-9][0-9]*)' if signed else r'(?:0|[1-9][0-9]*)'
    require(isinstance(text, str) and len(text) <= 21 and re.fullmatch(pattern, text),
            'noncanonical integer')
    value = int(text)
    require((-(1 << 31) if signed else 0) <= value <= maximum, 'integer out of bounds')
    return value


def hash_hex(value, digits):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{' + str(digits) + '}', value),
            'invalid digest')
    return value.lower()


def cookie(value):
    require(isinstance(value, str) and re.fullmatch(r'0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,15})', value),
            'invalid cookie')
    return int(value, 16)


def relative_path(value):
    require(isinstance(value, str) and 0 < len(value.encode('utf-8')) <= MAX_PATH,
            'invalid relative path length')
    require(not any(unicodedata.category(c).startswith('C') for c in value) and
            '\\' not in value and ':' not in value and
            all(p not in ('', '.', '..') for p in value.split('/')),
            'unsafe relative path')
    return value


def request_path(value):
    require(isinstance(value, str) and 0 < len(value) <= MAX_PATH * 2 and len(value) % 2 == 0 and
            re.fullmatch(r'[0-9a-fA-F]+', value), 'invalid path_hex')
    raw = bytes.fromhex(value).decode('utf-8', 'strict')
    require(re.match(r'^[A-Z]:/', raw) is not None, 'unmapped native drive/path')
    return raw[0], relative_path(raw[3:])


def absolute_path(value):
    raw = os.fspath(value)
    path = Path(raw)
    require(path.is_absolute() and str(path) == raw and '..' not in path.parts and path != Path('/'),
            'explicit canonical absolute directory required')
    return path


def directory(path):
    """Validate every ancestor with O_NOFOLLOW, including the supplied root."""
    path = absolute_path(path)
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        info = os.fstat(fd)
        require(info.st_uid == os.geteuid() and not info.st_mode & 0o022,
                'evidence root must be owned and not group/world writable')
        require(os.path.realpath(path) == str(path), 'symlinked evidence root')
    finally:
        os.close(fd)
    return path


def open_file(root, relative, limit):
    relative_path(relative)
    # Starting at / makes the shared reader walk the root's ancestors as well.
    stream = _reader.open_owned('/', str(root / relative).lstrip('/'), limit)
    try:
        info = os.fstat(stream.fileno())
        require(info.st_uid == os.geteuid() and info.st_nlink == 1 and not info.st_mode & 0o022,
                'evidence file must be owned, singly linked and not group/world writable')
        return stream
    except BaseException:
        stream.close()
        raise


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def load_json(root, relative):
    with open_file(root, relative, MAX_JSON) as stream:
        data = stream.read(MAX_JSON + 1)
    require(len(data) <= MAX_JSON, 'JSON read budget exceeded')
    result = json.loads(data, object_pairs_hook=unique_object,
                        parse_constant=lambda _: require(False, 'nonfinite JSON number'))
    require(type(result) is dict, 'JSON object required')
    return result


def json_int(value, low=0, high=CARD_BYTES):
    require(type(value) is int and low <= value <= high, 'invalid JSON integer')
    return value


def exports(run):
    final = load_json(run, 'SD/export.json')
    first = load_json(run, 'gtk-input-proof.json').get('sd_export')
    require(type(first) is dict, 'missing first original SD export')
    checked = []
    for export in (first, final):
        require(export.get('ok') is True and json_int(export.get('bytes')) == CARD_BYTES and
                export.get('host_directory_verified') is True and
                export.get('original_mount_verified') is True and
                export.get('guest_block_sync_confirmed') is True, 'directory SD export incomplete')
        host = absolute_path(export.get('host_directory', ''))
        # Explicit run-local cards and the existing public runtime card workspace only.
        allowed = (run, run.parent / 'directory-sd-tests', NATIVE / 'runtime/analysis/directory-sd-tests')
        require(any(host.is_relative_to(root) and host != root for root in allowed),
                'host directory outside owned run/public directory-SD workspace')
        directory(host)
        q, life, commit = (export.get(k) for k in ('quiesce', 'flush_lifecycle', 'directory_commit_status'))
        require(all(type(v) is dict for v in (q, life, commit)), 'missing flush/commit lifecycle')
        seq = json_int(export.get('sequence'), 1, (1 << 64) - 1)
        pid = json_int(q.get('pid'), 1, (1 << 31) - 1)
        drive = json_int(q.get('drive'), ord('A'), ord('Z'))
        require(q.get('owner_stopped') is True and
                type(q.get('original_Fsys_FlushVolume_rc')) is int and q['original_Fsys_FlushVolume_rc'] == 0 and
                type(q.get('sequence')) is int and q['sequence'] == seq and
                life.get('ok') is True and life.get('resumed') is True and life.get('status') == 'resumed' and
                type(life.get('sequence')) is int and life['sequence'] == seq and
                type(life.get('pid')) is int and life['pid'] == pid, 'original flush/STOP/resume mismatch')
        require(commit.get('available') is True and commit.get('pending') is False and
                commit.get('closed_pending') is False, 'directory commit not clean')
        entries = export.get('files')
        require(type(entries) is list and 0 < len(entries) <= 4096 and
                json_int(export.get('file_count'), 1, 4096) == len(entries), 'invalid export file list')
        files = {}
        for entry in entries:
            require(type(entry) is dict, 'invalid export file record')
            path = relative_path(entry.get('path'))
            require(path not in files, 'duplicate export path')
            files[path] = {'bytes': json_int(entry.get('bytes')), 'sha256': hash_hex(entry.get('sha256'), 64)}
        checked.append({'host': host, 'pid': pid, 'drive': chr(drive), 'sequence': seq, 'files': files})
    a, b = checked
    require(a['sequence'] < b['sequence'] and all(a[k] == b[k] for k in ('host', 'pid', 'drive', 'files')),
            'two original exports disagree or reuse/reverse sequence')
    return b, {'ok': True, 'bytes': CARD_BYTES, 'host_directory': str(b['host']),
               'sequences': [a['sequence'], b['sequence']], 'pid': b['pid'], 'drive': b['drive'],
               'file_count': len(b['files']), 'two_clean_resumed_exports': True}


def parse_trace(run):
    tokens, digest, total = {}, hashlib.sha256(), 0
    coverage, pending_readbacks = [], {}
    with open_file(run, 'console.log', MAX_LOG) as stream:
        before = os.fstat(stream.fileno())
        for line_number, raw in enumerate(iter(lambda: stream.readline(8193), b''), 1):
            total += len(raw)
            require(total <= MAX_LOG and len(raw) <= 8192, 'console read/line budget exceeded')
            digest.update(raw)
            line = raw.rstrip(b'\r\n')
            if line.startswith(b'OBS '):
                line = line[4:]
            tag = line.split(b' ', 1)[0]
            require(tag != b'FSYS_WRITE_COVERAGE_INCOMPLETE', 'native write observation coverage incomplete')
            if tag not in tuple(t.encode() for t in (*TAGS, COVERAGE_TAG)):
                require(not line.startswith((b'FSYS_WRITE_', b'MPR_WRITE_')), 'unknown native write trace tag')
                continue  # Old FSYS_ASYNC_WRITE is deliberately not evidence.
            require(raw.endswith(b'\n'), 'truncated native trace line')
            text = line.decode('ascii', 'strict')
            parts = text.split(' ')
            require(all(re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*=[!-~]+', p) for p in parts[1:]),
                    'malformed native trace fields')
            fields = unique_object(p.split('=', 1) for p in parts[1:])
            tag = parts[0]
            require(all(k in fields for k in FIELDS[tag]), 'missing native trace fields')
            fields['line'] = line_number
            pid = integer(fields['pid'], (1 << 31) - 1)
            require(pid > 0, 'zero native pid')
            if tag == COVERAGE_TAG:
                require(len(coverage) < 64 and integer(fields['rc'], (1 << 31) - 1, True) == 0,
                        f'native readback coverage failed/exceeded batch bound: line={line_number} '
                        f'pid={pid} records={fields["records"]} rc={fields["rc"]}')
                count = integer(fields['records'], MAX_TOKENS)
                captured = {key[1] for key in tokens if key[0] == pid}
                batch = pending_readbacks.pop(pid, {})
                require(count == len(captured) and set(batch) == captured,
                        'native readback coverage count/token set mismatch')
                coverage.append(fields)
                continue
            token = integer(fields['token'], MAX_TOKENS)
            require(pid > 0 and token > 0, 'unmatched/zero native pid or token')
            key = pid, token
            require(key in tokens or len(tokens) < MAX_TOKENS, 'native token budget exceeded')
            record = tokens.setdefault(key, {'pid': pid, 'token': token, 'areas': {}})
            if tag == 'FSYS_WRITE_NATIVE_READBACK':
                batch = pending_readbacks.setdefault(pid, {})
                require(token not in batch, 'duplicate native readback within one coverage batch')
                batch[token] = fields
                record.setdefault('native_readbacks', []).append(fields)
                record[tag] = fields
            elif tag == 'FSYS_WRITE_AREA':
                index = integer(fields['index'], 7)
                require(index not in record['areas'], 'duplicate native area index')
                record['areas'][index] = fields
            else:
                require(tag not in record, 'duplicate native write lifecycle record')
                record[tag] = fields
        after = os.fstat(stream.fileno())
        require(identity(before) == identity(after), 'console changed during inspection')
    require(tokens, 'no native original-write evidence; host media is not capture')
    require(coverage and not pending_readbacks, 'missing/incomplete final native readback coverage')
    require(integer(coverage[-1]['records'], MAX_TOKENS) == len(tokens),
            'final native coverage does not cover every captured token')
    paths, cookies = {}, set()
    for key, record in tokens.items():
        require('FSYS_WRITE_REQUEST' in record, 'orphan native write lifecycle')
        request = record['FSYS_WRITE_REQUEST']
        record['drive'], record['path'] = request_path(request['path_hex'])
        path = record['drive'], record['path']
        require(path not in paths, 'ambiguous multiple native writes to one path')
        paths[path] = key
        value = cookie(request['cookie'])
        require((key[0], value) not in cookies, 'ambiguous reused native callback cookie')
        cookies.add((key[0], value))
    return list(tokens.values()), digest.hexdigest(), coverage


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def lifecycle(record, exported):
    request = record['FSYS_WRITE_REQUEST']
    require(record['pid'] == exported['pid'] and record['drive'] == exported['drive'],
            'write owner/drive differs from original flush owner')
    require(integer(request['bytes']) == 1288 and integer(request['observation_rc'], (1 << 31) - 1, True) == 0 and
            integer(request['payload_complete'], 1) == 1, 'source request snapshot incomplete')
    hash_hex(request['request_fnv1a64'], 16)
    integer(request['media_origin_verified'], 1)  # A Boolean origin claim is never used as proof.
    count = integer(request['areas'], 8)
    require(count > 0 and set(record['areas']) == set(range(count)), 'missing/unknown native source areas')
    expected = integer(request['expected_bytes'], (1 << 32) - 1)
    require(expected > 0 and integer(request['address_mode'], 2) == 1,
            'empty file or unsupported physical source address mode')
    ranges, aggregate, submitted = [], 0, 0
    for index in range(count):
        area = record['areas'][index]
        offset, length = integer(area['offset']), integer(area['bytes'])
        span = integer(area['submitted_bytes'])
        require(integer(area['readable'], 1) == 1 and span % 4096 == 0 and
                span <= (1 << 64) - 1 - submitted, 'unreadable/unaligned/overflowing native span')
        require(offset == submitted and length == max(0, min(span, expected - submitted)),
                'native area differs from sequential submitted span/truncate semantics')
        submitted += span
        aggregate += length
        require(aggregate <= MAX_SOURCE, 'observer aggregate exceeds 128 MiB bound')
        value = hash_hex(area['data_fnv1a64'], 16)
        require(length > 0 or value == f'{FNV_INIT:016x}', 'zero-contribution area must hash empty bytes')
        ranges.append({'index': index, 'offset': offset, 'bytes': length,
                       'submitted_bytes': span, 'fnv1a64': value, 'line': area['line']})
    require(expected <= submitted and aggregate == expected, 'native submitted spans do not cover fileSize')
    contributing = [area for area in ranges if area['bytes']]
    end, contiguous = 0, True
    for area in contributing:
        require(area['offset'] >= end, 'overlapping native source areas')
        contiguous &= area['offset'] == end
        end = area['offset'] + area['bytes']
    require(end == expected, 'native source coverage does not reach fileSize')
    require(all(tag in record for tag in TAGS[2:]), 'missing submit/callback/finished/return/native-readback evidence')
    submit, callback, finished, returned, native = (record[tag] for tag in TAGS[2:])
    for row in (submit, callback, finished):
        require(integer(row['rc'], (1 << 31) - 1, True) == 0, 'original write return/callback failed')
    integer(submit['callback_seen'], 1)  # Informational: callbacks may run inline before submit returns.
    require(cookie(callback['cookie']) == cookie(finished['cookie']) == cookie(request['cookie']),
            'native callback/finished cookie mismatch')
    require(integer(callback['result_copied'], 1) == 1 and
            integer(finished['input_copied'], 1) == 1 and integer(finished['returned'], 1) == 1,
            'callback result or finished input/return observation incomplete')
    hash_hex(callback['result_fnv1a64'], 16)  # Digest of the 0x4d8-byte result, not a byte count.
    if 'result_bytes' in callback:
        require(integer(callback['result_bytes']) == 0x4d8, 'incorrect callback result snapshot size')
    for row in (callback, finished):
        if 'duplicate' in row:
            require(integer(row['duplicate'], 1) == 0, 'native callback/finished marked duplicate')
    require(integer(returned['returned'], 1) == 1, 'original MPR callback did not return')
    for native in record['native_readbacks']:
        require(cookie(native['cookie']) == cookie(request['cookie']) and
                integer(native['rc'], (1 << 31) - 1, True) == 0 and
                integer(native['close_rc'], (1 << 31) - 1, True) == 0 and
                integer(native['bytes']) == expected and integer(native['eof'], 1) == 1,
                'original Fsys native readback/EOF/close failed or length/cookie mismatch')
        hash_hex(native['fnv1a64'], 16)
        require(native['line'] > max(submit['line'], returned['line'], finished['line']),
                'native readback precedes completed original write')
    last_area = max(a['line'] for a in ranges)
    require(request['line'] < min(a['line'] for a in ranges) and
            last_area < min(submit['line'], callback['line']) and
            callback['line'] < min(finished['line'], returned['line']) and
            native['line'] > max(submit['line'], returned['line'], finished['line']),
            'native write lifecycle order mismatch')
    return ranges, expected, contiguous


def fnv_range(stream, offset, length):
    value = FNV_INIT
    while length:
        data = os.pread(stream.fileno(), min(length, 1024**2), offset)
        require(data, 'short source-range readback')
        for byte in data:
            value = ((value ^ byte) * FNV_PRIME) & ((1 << 64) - 1)
        offset += len(data)
        length -= len(data)
    return f'{value:016x}'


JPEG_DECODER = r'''
import hashlib, json, os, sys, warnings
from PIL import Image, ImageFile
Image.MAX_IMAGE_PIXELS = 100_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = False
warnings.simplefilter('error', Image.DecompressionBombWarning)
with os.fdopen(os.dup(int(sys.argv[1])), 'rb') as f:
    f.seek(0)
    with Image.open(f) as im:
        if im.format != 'JPEG' or getattr(im, 'n_frames', 1) != 1 or not (0 < im.width * im.height <= 100_000_000):
            raise ValueError('not a bounded single JPEG')
        im.load()
        rgb = im.convert('RGB')
        digest = hashlib.sha256()
        for y in range(0, rgb.height, 128):
            digest.update(rgb.crop((0, y, rgb.width, min(y + 128, rgb.height))).tobytes())
        print(json.dumps(dict(format='JPEG', width=rgb.width, height=rgb.height,
            frame_count=1, pixel_sha256=digest.hexdigest(), pixel_mode='RGB')))
'''


def decoder_limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024**2, 1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_decoder(command, snapshot, deadline):
    remaining = deadline - time.monotonic()
    require(remaining > 0, 'independent decode timeout')
    snapshot.seek(0)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        done = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                              pass_fds=(snapshot.fileno(),), timeout=remaining,
                              preexec_fn=decoder_limits, shell=False)
        require(os.fstat(out.fileno()).st_size <= 1024**2 and os.fstat(err.fileno()).st_size <= 1024**2,
                'decoder output budget exceeded')
        out.seek(0)
        err.seek(0)
        output, errors = out.read(), err.read()
        require(done.returncode == 0, f'independent decoder rc={done.returncode}: ' +
                errors[:1024].decode('utf-8', 'replace'))
        return output


def decode(snapshot, path):
    deadline = time.monotonic() + 30
    signature = os.pread(snapshot.fileno(), 16, 0)
    suffix = Path(path).suffix.lower()
    if suffix in ('.jpg', '.jpeg'):
        require(signature.startswith(b'\xff\xd8'), 'JPEG signature missing')
        value = json.loads(run_decoder([sys.executable, '-I', '-c', JPEG_DECODER,
                                       str(snapshot.fileno())], snapshot, deadline))
        return dict(value, decoded=True)
    require(suffix == '.mp4' and signature[4:8] == b'ftyp', 'supported JPEG/MP4 signature required')
    source = ['-protocol_whitelist', 'file,pipe', '-f', 'mov', '-enable_drefs', '0',
              '-use_absolute_path', '0', '-i', f'/proc/self/fd/{snapshot.fileno()}']
    probe = json.loads(run_decoder(['ffprobe', '-v', 'error', '-threads', '1', *source,
        '-select_streams', 'v:0', '-count_frames', '-show_entries',
        'stream=codec_name,width,height,nb_read_frames,duration:format=duration', '-of', 'json'],
        snapshot, deadline))
    streams = probe.get('streams')
    require(type(streams) is list and len(streams) == 1, 'MP4 video stream missing/ambiguous')
    video = streams[0]
    width, height = json_int(video.get('width'), 1, MAX_PIXELS), json_int(video.get('height'), 1, MAX_PIXELS)
    require(width * height <= MAX_PIXELS, 'MP4 pixel bound exceeded')
    frames = integer(video.get('nb_read_frames'), 100_000)
    require(frames >= 2, 'MP4 requires at least two decoded frames')
    duration = float(video.get('duration', probe.get('format', {}).get('duration', 'nan')))
    require(math.isfinite(duration) and duration > 0, 'MP4 positive duration missing')
    progress = run_decoder(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode',
        '-threads', '1', *source, '-map', '0:v:0', '-an', '-sn', '-dn', '-fps_mode', 'passthrough',
        '-progress', 'pipe:1', '-nostats', '-f', 'null', '-'], snapshot, deadline).decode('ascii')
    counts = re.findall(r'^frame=\s*([0-9]+)$', progress, re.MULTILINE)
    require(counts and int(counts[-1]) == frames and 'progress=end\n' in progress,
            'MP4 null decode did not finish with matching positive frame count')
    return {'format': 'MP4', 'decoded': True, 'width': width, 'height': height,
            'frame_count': frames, 'duration_seconds': duration, 'codec': video.get('codec_name'),
            'ffmpeg_null_rc': 0}


def check_item(record, exported, budget):
    result = {k: record[k] for k in ('pid', 'token', 'path', 'drive')}
    result.update(range_matches=False, readback_verified=False, whole_file_verified=False,
                  writeback_verified=False, native_readback_verified=False,
                  independent_decoded=False, capture_verified=False)
    try:
        ranges, expected, contiguous = lifecycle(record, exported)
        result.update(expected_bytes=expected, contiguous_coverage=contiguous,
                      source_bytes=sum(a['bytes'] for a in ranges), areas=ranges,
                      lifecycle_verified=True, native_readbacks=record['native_readbacks'])
        entry = exported['files'].get(record['path'])
        require(entry is not None, 'native target absent from both export file lists')
        with open_file(exported['host'], record['path'], CARD_BYTES) as stream:
            before = os.fstat(stream.fileno())
            require(before.st_size == entry['bytes'] and before.st_size >= expected, 'export/readback length mismatch')
            required = min(before.st_size, MAX_SOURCE + 1) * 2 + result['source_bytes']
            require(required <= budget[0], 'aggregate readback budget exceeded')
            budget[0] -= required
            # shortcut: only 128 MiB file snapshots; extend the budget explicitly for larger movie proofs.
            if before.st_size > MAX_SOURCE:
                for area in ranges:
                    require(fnv_range(stream, area['offset'], area['bytes']) == area['fnv1a64'],
                            'source-range FNV/readback mismatch')
                require(identity(before) == identity(os.fstat(stream.fileno())), 'file changed during range readback')
                result['range_matches'] = True
                raise ValueError('file exceeds 128 MiB SHA/snapshot bound; ranges only, export SHA not checked')
            with tempfile.TemporaryFile() as snapshot:
                space = os.fstatvfs(snapshot.fileno())
                require(space.f_bavail * space.f_frsize >= before.st_size + 1024**2, 'insufficient snapshot space')
                digest, size = hashlib.sha256(), 0
                while True:
                    data = stream.read(min(1024**2, before.st_size + 1 - size))
                    if not data:
                        break
                    size += len(data)
                    require(size <= before.st_size, 'file grew during readback')
                    digest.update(data)
                    require(snapshot.write(data) == len(data), 'short anonymous snapshot write')
                require(size == before.st_size and identity(before) == identity(os.fstat(stream.fileno())),
                        'file changed/truncated during readback')
                snapshot.flush()
                sha = digest.hexdigest()
                result.update(bytes=size, sha256=sha)
                require(sha == entry['sha256'], 'export SHA256/readback mismatch')
                result['readback_verified'] = True
                for area in ranges:
                    require(fnv_range(snapshot, area['offset'], area['bytes']) == area['fnv1a64'],
                            'source-range FNV/readback mismatch')
                result['range_matches'] = True
                whole_fnv = fnv_range(snapshot, 0, size)
                result['fnv1a64'] = whole_fnv
                require(all(whole_fnv == native['fnv1a64'].lower() for native in record['native_readbacks']),
                        'original Fsys/host whole-file FNV mismatch')
                result['native_readback_verified'] = True
                require(contiguous, 'source extents have holes; ranges only')
                require(size == expected, 'whole-file readback has unobserved trailing bytes')
                result.update(whole_file_verified=True, writeback_verified=True)
                result['decode'] = decode(snapshot, record['path'])
                result['independent_decoded'] = True
    except (OSError, ValueError, TypeError, KeyError, Warning, subprocess.SubprocessError) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    return result


def inspect(run, mediafile=None):
    result = {'schema': 'native-card-writeback-v1', 'readback_verified': False,
              'range_matches': False, 'whole_file_verified': False, 'writeback_verified': False,
              'independent_decoded': False, 'native_readback_verified': False,
              'capture_verified': False, 'items': [],
              'evidence_scope': 'plaintext evidence consistency; origin is not authenticated',
              'capture_blocker': 'separate original CMOS consumption and encoder provenance evidence must be joined'}
    try:
        run = directory(run)
        if mediafile is not None:
            relative_path(mediafile)
        exported, result['exports'] = exports(run)
        records, result['console_sha256'], result['native_readback_coverage'] = parse_trace(run)
        require(all(integer(row['pid'], (1 << 31) - 1) == exported['pid']
                    for row in result['native_readback_coverage']), 'native readback coverage owner mismatch')
        issues = []
        for record in records:
            try:
                lifecycle(record, exported)
            except (ValueError, TypeError, KeyError) as error:
                issues.append({'pid': record['pid'], 'token': record['token'], 'path': record['path'],
                               'error': f'{type(error).__name__}: {error}',
                               'records': {tag: record[tag] for tag in TAGS if tag in record}})
        result['trace_issues'] = issues
        require(not issues, 'pending/failed/invalid native token prevents complete observation coverage: ' +
                (issues[0]['error'] if issues else ''))
        selected = [row for row in records if row['path'] == mediafile] if mediafile else [
            row for row in records if Path(row['path']).suffix.lower() in ('.jpg', '.jpeg', '.mp4')]
        require(selected, 'no selected native JPEG/MP4 write request; host file alone is not evidence')
        budget = [MAX_READ]
        result['items'] = [check_item(row, exported, budget) for row in selected]
        for flag in ('readback_verified', 'range_matches', 'whole_file_verified', 'writeback_verified',
                     'native_readback_verified', 'independent_decoded'):
            result[flag] = all(row[flag] for row in result['items'])
        result['read_budget_remaining'] = budget[0]
    except (OSError, ValueError, TypeError, KeyError) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', help='absolute owned evidence run directory')
    parser.add_argument('--mediafile', help='exact relative host-SD file; default: native JPEG/MP4 requests')
    args = parser.parse_args()
    result = inspect(args.run, args.mediafile)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result['writeback_verified'] and result['independent_decoded'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
