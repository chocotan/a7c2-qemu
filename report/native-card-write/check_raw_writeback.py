#!/usr/bin/env python3
"""Verify original Fsys writeback against two owned 1GiB FAT16 card exports.

This is not a capture-origin verifier: successful file readback and decode never
prove the source came from an original sensor or encoder.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import types

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[1]


def load_module(name, path):
    if '_source_module' in globals():
        return _source_module(path)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


wb = load_module('native_raw_writeback_contract', HERE/'check_writeback.py')
sd = load_module('native_raw_sd_transport', PRODUCT/'runtime/analysis/sd_transport.py')
CARD_BYTES = 1024**3
MAX_MEDIA_BYTES = 128*1024**2


def check_fsck(run, row):
    relative = f"SD/{row['evidence']}/fsck.txt"
    with wb.open_file(run, relative, 65536) as stream:
        raw = stream.read(65537)
    wb.require(len(raw) <= 65536 and b'fsck.fat ' in raw and
               re.search(rb'[0-9]+ files, [0-9]+/[0-9]+ clusters', raw),
               'recognized raw-card fsck evidence is missing')
    return hashlib.sha256(raw).hexdigest()


def read_export_pair(run, first_sequence, second_sequence):
    wb.require(type(first_sequence) is int and type(second_sequence) is int and
               0 < first_sequence < second_sequence < 2**64,
               'export sequences must be strictly increasing uint64 values')
    first, second = (wb.load_json(run, f'SD/capture-export-{seq:020d}.json')
                     for seq in (first_sequence, second_sequence))
    for expected, row in ((first_sequence, first), (second_sequence, second)):
        sd.validate_capture_export_proof(row)
        wb.require(row['sequence'] == expected, 'proof filename/sequence mismatch')
    wb.require(second.get('expected_old_sha256') == first['sha256'],
               'second export did not bind the first published card')
    wb.require(first['evidence'] != second['evidence'], 'export evidence directory reused')
    wb.require(first['quiesce']['pid'] == second['quiesce']['pid'] and
               first['quiesce']['drive'] == second['quiesce']['drive'],
               'two Fsys exports have different owner or drive')
    wb.require(wb.load_json(run, 'SD/export.json') == second,
               'latest SD export does not match the second proof')
    return first, second


def read_card(run, relative, proof, wanted):
    wb.relative_path(relative)
    found = {}
    with wb._reader.open_owned('/', str(run/relative).lstrip('/'), CARD_BYTES) as image:
        before = os.fstat(image.fileno())
        wb.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                   not before.st_mode & 0o022 and before.st_size == CARD_BYTES,
                   'raw card must be an owned, non-writable-by-others 1GiB regular file')
        sd.validate_capture_export_proof(proof)
        digest = hashlib.sha256()
        for chunk in proof['chunks']:
            wb.require(image.tell() == chunk['offset'], 'raw-card window offset differs')
            data = image.read(chunk['len'])
            wb.require(len(data) == chunk['len'], 'short raw-card window read')
            digest.update(data)
            actual_fnv = fnv(data)
            wb.require(actual_fnv == chunk['guest_fnv64'] == chunk['actual_fnv64'],
                       'actual raw-card window FNV differs from export proof')
        wb.require(image.tell() == CARD_BYTES and image.read(1) == b'', 'raw-card window coverage differs')
        digest = digest.hexdigest()
        wb.require(digest == proof['sha256'], 'complete raw card SHA256 differs from export proof')
        image.seek(0)
        def collect(path, data):
            relative_name = path.lstrip('/')
            if relative_name in wanted:
                wb.require(relative_name not in found, 'duplicate selected raw-card path')
                wb.require(sum(len(item) for item in found.values()) + len(data) <= MAX_MEDIA_BYTES,
                           'selected media exceeds aggregate memory bound')
                found[relative_name] = data
        volume = wb._reader.Fat16(image, CARD_BYTES, on_file=collect,
                                  max_file=MAX_MEDIA_BYTES, read_budget=256*1024**2,
                                  file_filter=lambda path: path.lstrip('/') in wanted)
        volume.walk()
        wb.require(volume.lfn_skipped == 0, 'long filenames require a separately verified parser')
        wb.require(wb.identity(before) == wb.identity(os.fstat(image.fileno())),
                   'raw card changed during complete hash and FAT readback')
        return found, dict(path=relative, bytes=before.st_size, sha256=digest,
                           device=before.st_dev, inode=before.st_ino, links=before.st_nlink,
                           mtime_ns=before.st_mtime_ns, ctime_ns=before.st_ctime_ns)


def fnv(data):
    value = wb.FNV_INIT
    for byte in data:
        value = ((value ^ byte)*wb.FNV_PRIME) & ((1 << 64)-1)
    return f'{value:016x}'


def proof_digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, allow_nan=False).encode('ascii')).hexdigest()


def check_unchanged(run, storage):
    """Both complete images and original receipts must survive all content joins."""
    first, second = read_export_pair(run, *storage['export_sequences'])
    wb.require([proof_digest(first), proof_digest(second)] == storage['export_proof_sha256'] and
               [check_fsck(run, first), check_fsck(run, second)] == storage['fsck_sha256'],
               'raw export or fsck proof changed during content join')
    wanted = {item['path'] for item in storage['items']}
    for relative, proof, key in ((f"SD/{second['evidence']}/previous-card.img", first, 'first_card'),
                                 ('SD/card.img', second, 'second_card')):
        files, identity = read_card(run, relative, proof, wanted)
        wb.require(identity == storage[key] and set(files) == wanted, 'raw export image identity changed')
        for item in storage['items']:
            data = files[item['path']]
            wb.require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'],
                       'raw export JPEG changed during content join')
    wb.require(wb.parse_trace(run)[1] == storage['console_sha256'], 'raw export console changed during content join')
    return {'verified': True}


def stored_media_bytes(run, storage, item):
    """Re-read the fully hashed raw image; never trust an extracted host JPEG."""
    wb.require(storage.get('writeback_verified') is True and storage.get('independent_decoded') is True and
               item.get('writeback_verified') is True and item.get('independent_decoded') is True,
               'raw storage has not passed native writeback and decode')
    first, second = read_export_pair(run, *storage['export_sequences'])
    wb.require(first['sha256'] == storage['first_card']['sha256'] and
               second['sha256'] == storage['second_card']['sha256'], 'raw export proofs changed')
    files, identity = read_card(run, 'SD/card.img', second, {item['path']})
    wb.require(identity == storage['second_card'] and item['path'] in files,
               'raw card identity or selected path changed')
    data = files[item['path']]
    wb.require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'] and
               fnv(data) == item['fnv1a64'], 'decoded raw-card JPEG changed before content join')
    return data


def inspect(run, first_sequence, second_sequence, mediafile=None, *, jpeg_only=False):
    result = dict(schema='native-raw-card-writeback-v1', writeback_verified=False,
                  independent_decoded=False, capture_verified=False, items=[])
    try:
        run = wb.directory(run)
        wb.require(type(jpeg_only) is bool, 'jpeg_only must be an explicit boolean')
        if mediafile is not None:
            wb.relative_path(mediafile)
            wb.require(not jpeg_only or Path(mediafile).suffix.lower() in ('.jpg', '.jpeg'),
                       'JPEG-only raw evidence cannot select a movie')
        first, second = read_export_pair(run, first_sequence, second_sequence)
        result['fsck_sha256'] = [check_fsck(run, first), check_fsck(run, second)]
        records, result['console_sha256'], coverage = wb.parse_trace(run)
        owner = second['quiesce']['pid']
        drive = chr(second['quiesce']['drive'])
        wb.require(all(wb.integer(row['pid'], (1 << 31)-1) == owner for row in coverage),
                   'native readback coverage owner mismatch')
        exported = dict(pid=owner, drive=drive)
        # Every captured native write must have a complete lifecycle, even if not selected.
        parsed = [(record, *wb.lifecycle(record, exported)) for record in records]
        selected = [row for row in parsed if row[0]['path'] == mediafile] if mediafile else [
            row for row in parsed if Path(row[0]['path']).suffix.lower() in
            (('.jpg', '.jpeg') if jpeg_only else ('.jpg', '.jpeg', '.mp4'))]
        wb.require(selected, 'no selected original Fsys JPEG/MP4 write')
        wb.require(not jpeg_only or len(selected) == 1, 'JPEG-only raw evidence requires one unambiguous native JPEG')
        wanted = {row[0]['path'] for row in selected}
        before, result['first_card'] = read_card(
            run, f"SD/{second['evidence']}/previous-card.img", first, wanted)
        after, result['second_card'] = read_card(run, 'SD/card.img', second, wanted)
        wb.require(result['first_card']['inode'] != result['second_card']['inode'] or
                   result['first_card']['device'] != result['second_card']['device'],
                   'two exports unexpectedly share the same inode')
        wb.require(set(before) == set(after) == wanted, 'selected file absent from an export')
        for record, ranges, expected, contiguous in selected:
            path = record['path']
            data = after[path]
            wb.require(before[path] == data and len(data) == expected and contiguous,
                       'two exports differ or native source coverage is incomplete')
            for area in ranges:
                part = data[area['offset']:area['offset']+area['bytes']]
                wb.require(len(part) == area['bytes'] and fnv(part) == area['fnv1a64'],
                           'native source-range FNV does not match raw card')
            whole = fnv(data)
            wb.require(all(whole == row['fnv1a64'].lower() for row in record['native_readbacks']),
                       'original Fsys readback does not match raw card')
            with os.fdopen(os.memfd_create('raw-card-writeback', os.MFD_CLOEXEC), 'w+b') as snapshot:
                wb.require(snapshot.write(data) == len(data), 'short bounded media snapshot write')
                snapshot.flush()
                decoded = wb.decode(snapshot, path)
            wb.require(not jpeg_only or decoded.get('decoded') is True and decoded.get('format') == 'JPEG' and
                       decoded.get('frame_count') == 1 and type(decoded.get('width')) is int and
                       type(decoded.get('height')) is int and decoded['width'] > 0 and decoded['height'] > 0,
                       'independent single JPEG decode required')
            result['items'].append(dict(path=path, pid=record['pid'], token=record['token'], drive=drive,
                                        bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), fnv1a64=whole,
                                        areas=ranges, native_readbacks=record['native_readbacks'],
                                        original_fsys_lifecycle_verified=True, native_readback_verified=True,
                                        writeback_verified=True, independent_decoded=True, capture_verified=False,
                                        ranges_match=True, two_raw_exports_match=True,
                                        decode=decoded, independent_decode=decoded))
        wb.require(read_export_pair(run, first_sequence, second_sequence) == (first, second) and
                   [check_fsck(run, first), check_fsck(run, second)] == result['fsck_sha256'] and
                   wb.parse_trace(run)[1] == result['console_sha256'], 'raw export or console evidence changed')
        result.update(writeback_verified=True, independent_decoded=True,
                      export_sequences=[first_sequence, second_sequence],
                      export_proof_sha256=[proof_digest(first), proof_digest(second)],
                      exports=dict(pid=owner, drive=drive, storage_kind='raw-1gib', run_directory=str(run)),
                      limitation='Original sensor, encoder provenance and complete capture are not established')
    except (OSError, ValueError, TypeError, KeyError, Warning, subprocess.SubprocessError) as error:
        result['error'] = f'{type(error).__name__}: {error}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='absolute owned run directory')
    parser.add_argument('--first-sequence', required=True, type=int)
    parser.add_argument('--second-sequence', required=True, type=int)
    parser.add_argument('--mediafile', help='exact relative file name')
    parser.add_argument('--jpeg-only', action='store_true', help='explicit single-JPEG raw writeback scope; never capture acceptance')
    args = parser.parse_args()
    result = inspect(args.run, args.first_sequence, args.second_sequence, args.mediafile, jpeg_only=args.jpeg_only)
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result['writeback_verified'] and result['independent_decoded'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
