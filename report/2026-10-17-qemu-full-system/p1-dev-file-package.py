#!/usr/bin/env python3
"""One fixed diagnostic file in official 2.01 p15; offline, copied images only.

build(official, plaintext, output, *, fwtool_dir, current_version='2.01')
verify(official, derived, output, *, fwtool_dir, current_version='2.01')
contract(receipt_path, receipt_sha256, *, output_root=None) replays the complete verifier in a fresh
interpreter. The optional root must be below analysis/scratch and is also the child TMPDIR. Receipts alone never authorize a payload. No device/VM entry point.
"""
import argparse
from contextlib import ExitStack
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
SCRATCH = PROJECT / 'analysis/scratch/p1-dev-file-batch-20261106'
SCHEMA = 'a7c2-p1-dev-fixed-system-file-package-v1'
KIND = 'p15-qemu-packaged-system-check-v1'
PROFILE = 'original-p1-virtual-dev-install-v1'
MODE = 'virtual-dev-sd-update-v1'
STOCK_SHA = 'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
PLAIN_SHA = '03eee07301010ff644fae1073f7c7f6dd2d60278f18aa3e6053938d5f1426d1f'
PACKAGE_BYTES, PLAIN_BYTES, IMAGE_BYTES = 1139929560, 1135475712, 770030592
IMAGE_NAME = '0700_part_image/dev/nflasha15'
SUM_NAME = '0701_part_image_sum/part_image.sum'
MARKER = '/bin/qemu-packaged-system-check-v1'
SCRIPT = (b'#!/bin/sh\necho QEMU_PACKAGED_SYSTEM_FILE_V1\n'
          b"busybox grep -E '^(Uid|Gid):' /proc/$$/status\n")
FILE_SHA = hashlib.sha256(SCRIPT).hexdigest()
CORE = {
    '/bin/bootin.elf': dict(size=23960,
        sha256='dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2',
        elf=dict(ident_hex='7f454c46020101000000000000000000', type=2, machine=183)),
    '/lib/appFw.so': dict(size=99960744,
        sha256='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
        elf=dict(ident_hex='7f454c46020101030000000000000000', type=3, machine=183)),
}
CHUNK = 1024 ** 2
_KIT = None
_KIT_ROOT = None


def _kit(fwtool_dir):
    global _KIT, _KIT_ROOT
    fwtool_dir = Path(fwtool_dir).absolute()
    if _KIT is not None and fwtool_dir != _KIT_ROOT:
        raise ValueError('Cannot reuse another fwtool source selection in the same verifier')
    if _KIT is None:
        virtual = runpy.run_path(str(HERE / 'virtual-update.py'))
        dat, fdat = virtual['IMPORT'].vendor(fwtool_dir)
        builder = runpy.run_path(str(PROJECT / 'analysis/build_sony_info.py'))
        ext2 = importlib.import_module('fwtool.archive.ext2')
        _KIT = virtual, dat, fdat, builder, ext2
        _KIT_ROOT = fwtool_dir
    return _KIT


def _version(current):
    dev = runpy.run_path(str(HERE / 'p1-dev-install.py'))
    if dev['version']('2.02') <= dev['version'](current):
        raise ValueError('2.02 must be strictly higher than current; UUD remains enabled')


def _scratch_root(output_root=None):
    root = SCRATCH if output_root is None else Path(os.path.abspath(output_root))
    allowed = PROJECT / 'analysis/scratch'
    if root == allowed or not root.is_relative_to(allowed):
        raise ValueError('DEV verifier scratch must stay below analysis/scratch')
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise ValueError('Symlink scratch ancestor refused')
    return root


def _output(output, *, scratch=None):
    output = Path(os.path.abspath(output)); scratch = _scratch_root(scratch)
    if output == scratch or not output.is_relative_to(scratch):
        raise ValueError('All generated data must stay below ' + str(scratch))
    scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
    for parent in (scratch, *output.parents):
        if parent.is_symlink():
            raise ValueError('Symlink output ancestor refused')
    if not output.parent.is_dir():
        raise ValueError('Output parent must exist')
    required = 6 * PLAIN_BYTES + 6 * IMAGE_BYTES + 2 * PACKAGE_BYTES + 128 * CHUNK
    free = shutil.disk_usage(output.parent).free
    if free < required:
        raise ValueError(f'Insufficient host space: free={free}, required={required}')
    output.mkdir(mode=0o700)
    (output / 'host-space.json').write_text(json.dumps(dict(free=free, required=required)) + '\n')
    return output


def _save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _signature(row):
    # OpenSSL error prefixes contain process-specific thread addresses.
    return {key: row[key] for key in ('status', 'algorithm', 'returncode', 'signed_sha256',
                                      'key_der_sha256', 'stock_receiver_acceptance')}


def _record(source):
    return dict(path=str(source.path), device=source.info.st_dev, inode=source.info.st_ino,
                bytes=source.info.st_size, sha256=source.sha256)


def _run(argv, output, name, *, env=None):
    result = subprocess.run([str(x) for x in argv], capture_output=True, env=env)
    (output / (name + '.stdout')).write_bytes(result.stdout)
    (output / (name + '.stderr')).write_bytes(result.stderr)
    _save(output / (name + '.json'), dict(argv=[str(x) for x in argv], returncode=result.returncode))
    if result.returncode:
        raise ValueError(f'{name} failed: rc={result.returncode}; evidence in {output}')
    return result


def _edit_image(source, target, output, builder):
    """Deterministic replay also constrains unused blocks and all ext2 metadata."""
    shutil.copyfile(source, target)
    marker = output / 'marker.sh'
    with marker.open('xb') as stream:
        stream.write(SCRIPT)
    os.utime(marker, (1793923200, 1793923200))
    if any(c in str(marker) for c in '\n\r"\\'):
        raise ValueError('Unsupported debugfs host path')
    commands = output / 'debugfs.commands'
    commands.write_text('set_current_time 20261106000000\n'
        f'write "{marker}" {MARKER}\n'
        f'set_inode_field {MARKER} mode 0100755\n'
        f'set_inode_field {MARKER} uid 0\n'
        f'set_inode_field {MARKER} gid 0\n'
        + ''.join(f'set_inode_field {MARKER} {field} 20261106000000\n'
                  for field in ('atime', 'mtime', 'ctime')), encoding='ascii')
    env = dict(os.environ, E2FSPROGS_FAKE_TIME='1793923200')
    _run(['debugfs', '-w', '-f', commands, target], output, 'debugfs-write', env=env)
    _run(['e2fsck', '-fn', target], output, 'e2fsck')
    dumped = output / 'marker.readback'
    _run(['debugfs', '-R', f'dump {MARKER} {dumped}', target], output, 'debugfs-dump')
    status = _run(['debugfs', '-R', f'stat {MARKER}', target], output, 'debugfs-stat')
    if not dumped.is_file() or dumped.read_bytes() != SCRIPT or b'Mode:  0755' not in status.stdout:
        raise ValueError('Independent debugfs marker readback/mode differs')
    _run(['/bin/sh', '-n', dumped], output, 'shell-syntax')
    if builder['sha_file'](dumped) != FILE_SHA or target.stat().st_size != IMAGE_BYTES:
        raise ValueError('Independent file SHA/image size differs')


def _tree(image, builder, ext2):
    tree = {}
    with image.open('rb') as stream:
        for entry in ext2.readExt2(stream):
            name = entry.path or '/'
            if name in tree:
                raise ValueError('Duplicate ext2 path')
            row = dict(mode=entry.mode, uid=entry.uid, gid=entry.gid,
                       size=entry.size, mtime=entry.mtime)
            if entry.contents is not None:
                head = entry.contents.read(64)
                entry.contents.seek(0)
                row['sha256'] = builder['digest'](entry.contents)
                if head[:4] == b'\x7fELF':
                    row['elf'] = dict(ident_hex=head[:16].hex(),
                                      type=int.from_bytes(head[16:18], 'little'),
                                      machine=int.from_bytes(head[18:20], 'little'))
            tree[name] = row
    return tree


def _tree_delta(before, after):
    if set(after) - set(before) != {MARKER} or set(before) - set(after):
        raise ValueError('Only the fixed marker may be added to the complete ext2 tree')
    for name, row in before.items():
        changed = dict(after[name])
        if name == '/bin':
            changed['mtime'] = row['mtime']
        if changed != row:
            raise ValueError('Existing ext2 node changed: ' + name)
    row = after[MARKER]
    if any(row.get(k) != v for k, v in dict(mode=stat.S_IFREG | 0o755, uid=0, gid=0,
                                           size=len(SCRIPT), sha256=FILE_SHA).items()):
        raise ValueError('Marker content/type/mode/owner differs')
    core = {p: before[p] for p in CORE if p in before}
    if set(core) != set(CORE) or any(
            any(row.get(k) != v for k, v in CORE[p].items()) for p, row in core.items()):
        raise ValueError('Exact official bootin/appFw.so content or ELF identity differs')
    return dict(added=[MARKER], removed=[], existing_nodes_unchanged_except_bin_mtime=True,
                original_core_elfs=core,
                before_sha256=hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
                after_sha256=hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(),
                before_nodes=len(before), after_nodes=len(after))


def _plain_regions(virtual, before, after, ranges):
    total = os.fstat(before).st_size
    if total != PLAIN_BYTES or os.fstat(after).st_size != total:
        raise ValueError('Plaintext full length differs')
    cursor = 0
    for start, size in sorted(ranges) + [(total, 0)]:
        if start < cursor or size < 0 or start + size > total:
            raise ValueError('Overlapping/out-of-bounds approved plaintext ranges')
        if virtual['_hash'](before, cursor, start - cursor) != virtual['_hash'](after, cursor, start - cursor):
            raise ValueError('Plaintext differs outside marker image/sum/version/header CRC')
        cursor = start + size


def _tar(plain, target_image, builder, fdat, virtual):
    """Inventory, SHA and all updater .sum checks, without invoking a writer."""
    rows, observed = [], {}
    with plain.open('rb') as stream:
        info = fdat.readFdat(stream)
        with tarfile.open(fileobj=info.firmware, mode='r:') as archive:
            members = archive.getmembers()
            if len({m.name for m in members}) != len(members):
                raise ValueError('Duplicate firmware tar member')
            for member in members:
                virtual['_relative'](member.name)
                logical = virtual['_logical'](member.name)
                if logical in observed or member.sparse:
                    raise ValueError('Duplicate/sparse firmware member')
                row = builder['metadata'](member)
                row['type'] = row['type'].decode('ascii')
                if member.isfile():
                    hashed, crc, count = hashlib.sha256(), 0, 0
                    capture = logical.split('/')[0].endswith('_sum')
                    data = bytearray()
                    with archive.extractfile(member) as content:
                        while block := content.read(CHUNK):
                            hashed.update(block); crc = zlib.crc32(block, crc); count += len(block)
                            if capture:
                                if count > 16 * CHUNK: raise ValueError('Oversized sum member')
                                data.extend(block)
                    if count != member.size: raise ValueError('Truncated tar member')
                    row.update(sha256=hashed.hexdigest(), crc32=crc)
                    if member.name == IMAGE_NAME:
                        if member.size != IMAGE_BYTES: raise ValueError('Original p15 size differs')
                        with archive.extractfile(member) as content, target_image.open('xb') as destination:
                            shutil.copyfileobj(content, destination, CHUNK)
                    observed[logical] = dict(type='0', bytes=count, crc32=crc)
                    if capture:
                        virtual['_check_sum'](bytes(data), logical.split('/')[0][:-4], observed)
                    if member.name == SUM_NAME:
                        sum_data = bytes(data)
                elif member.isdir():
                    observed[logical] = dict(type='5')
                elif member.issym():
                    observed[logical] = dict(type='2', target=member.linkname)
                else:
                    raise ValueError('Unsupported firmware tar member type')
                rows.append(row)
            image_member, sum_member = archive.getmember(IMAGE_NAME), archive.getmember(SUM_NAME)
            offsets = [(info.firmware.offset + m.offset_data, m.size) for m in (image_member, sum_member)]
    return rows, sum_data, offsets


def _envelope(virtual, original, derived):
    layouts = []
    for source in (original, derived):
        with os.fdopen(os.dup(source.fd), 'rb') as stream:
            layouts.append(virtual['IMPORT'].chunks(stream))
    if layouts[0] != layouts[1] or original.info.st_size != derived.info.st_size:
        raise ValueError('Outer UFU length/chunk geometry differs')
    total, chunks = layouts[0]
    offset, size = chunks[b'FDAT']; dend = chunks[b'DEND'][0]
    for start, count in ((0, offset), (offset + size, dend - offset - size),
                         (dend + 4, total - dend - 4), (offset + size - 272, 272)):
        if count < 0 or virtual['_hash'](original.fd, start, count) != virtual['_hash'](derived.fd, start, count):
            raise ValueError('Outer metadata/IV/footer changed')
    return dict(bytes=total, chunks={k.decode('ascii'): list(v) for k, v in chunks.items()},
                outer_metadata_iv_footer_preserved=True)


def _verify(official, derived, output, fwtool_dir, current_version, kit):
    virtual, dat, fdat, builder, ext2 = kit
    with ExitStack() as stack:
        sources = [virtual['_Source'](p) for p in (official, derived)]
        for source in sources: stack.callback(source.close)
        original, changed = sources
        if (original.sha256 != STOCK_SHA or original.info.st_size != PACKAGE_BYTES
                or changed.info.st_size != PACKAGE_BYTES
                or (original.info.st_dev, original.info.st_ino) == (changed.info.st_dev, changed.info.st_ino)):
            raise ValueError('Require independent derived file and exact official 2.01 package')
        envelope = _envelope(virtual, *sources)
        decoded = []
        for name, source in zip(('official', 'derived'), sources):
            destination = output / name; destination.mkdir(mode=0o700)
            row = virtual['decode_package'](source.path, destination, fwtool_dir=Path(fwtool_dir).absolute())
            _save(destination / 'inspection.json', row)
            decoded.append(row)
        old, new = decoded
        if (old['package']['signature']['status'] != 'valid'
                or new['package']['signature']['status'] != 'invalid'
                or old['sha256'] != PLAIN_SHA or old['bytes'] != PLAIN_BYTES
                or new['bytes'] != PLAIN_BYTES or old['version'] != '2.01' or new['version'] != '2.02'
                or any((r['model'], r['region']) != (0x20030014, 0) for r in decoded)
                or any(r['block_checksums_valid'] is not True for r in decoded)):
            raise ValueError('Official identity/signatures/FDAT mode/version/model/region/length differs')
        old_plain, new_plain = Path(old['path']), Path(new['path'])
        before_image, after_image = output / 'p15.official.ext2', output / 'p15.packaged.ext2'
        rows0, sums0, ranges0 = _tar(old_plain, before_image, builder, fdat, virtual)
        rows1, sums1, ranges1 = _tar(new_plain, after_image, builder, fdat, virtual)
        if ranges0 != ranges1 or len(rows0) != len(rows1):
            raise ValueError('Firmware tar offsets/lengths differ')
        changed_members = []
        for a, b in zip(rows0, rows1):
            if a != b:
                if {k: v for k,v in a.items() if k not in ('sha256', 'crc32')} != {
                        k: v for k,v in b.items() if k not in ('sha256', 'crc32')}:
                    raise ValueError('Firmware tar member metadata/boundary differs')
                changed_members.append(a['name'])
        if changed_members != [IMAGE_NAME, SUM_NAME]:
            raise ValueError('Only p15 and its fixed checksum member may change')
        if sums1 != builder['update_sum'](sums0, builder['file_crc'](after_image), IMAGE_BYTES):
            raise ValueError('Only the existing fixed-width p15 CRC field may change')
        with old_plain.open('rb') as a, new_plain.open('rb') as b:
            if b.read(512) != bytes(builder['version_header'](a.read(512), '2.02')):
                raise ValueError('FDAT header changed beyond 2.02/version CRC')
            _plain_regions(virtual, a.fileno(), b.fileno(), [(8, 4), (32, 2)] + ranges0)
        for name, image in (('official', before_image), ('packaged', after_image)):
            _run(['e2fsck', '-fn', image], output, 'e2fsck-' + name)
        before, after = _tree(before_image, builder, ext2), _tree(after_image, builder, ext2)
        delta = _tree_delta(before, after)
        _save(output / 'tree.official.json', before); _save(output / 'tree.packaged.json', after)
        replay_dir = output / 'replay'; replay_dir.mkdir(mode=0o700)
        replay_image = replay_dir / 'p15.ext2'
        _edit_image(before_image, replay_image, replay_dir, builder)
        image_sha = builder['sha_file'](after_image)
        if builder['sha_file'](replay_image) != image_sha:
            raise ValueError('Packaged p15 differs from deterministic single-file replay, including unused blocks')
        for source in sources: source.verify()
        proof = dict(plain=dict(original_sha256=old['sha256'], sha256=new['sha256'], bytes=new['bytes'],
                    all_other_plaintext_bytes_identical=True, changed_ranges=[(8,4),(32,2)] + ranges0),
            envelope=envelope, members_before=rows0, members_after=rows1, changed_tar_members=changed_members,
            all_partition_sum_crcs_valid=True, tree=delta,
            images=dict(bytes=IMAGE_BYTES, original_sha256=builder['sha_file'](before_image), sha256=image_sha,
                        deterministic_single_file_replay_identical=True, e2fsck_original_rc=0, e2fsck_packaged_rc=0),
            file=dict(path=MARKER, guest_path='/usr' + MARKER, bytes=len(SCRIPT), sha256=FILE_SHA,
                      mode='0755', uid=0, gid=0, debugfs_readback_identical=True),
            signature=_signature(new['package']['signature']),
            original_signature=_signature(old['package']['signature']))
        result = dict(schema=SCHEMA, kind=KIND, profile=PROFILE, mode=MODE, virtual_only=True,
            original=_record(original), derived=_record(changed), fwtool_dir=str(Path(fwtool_dir).absolute()),
            original_version='2.01', new_version='2.02', current_version=current_version,
            model=0x20030014, region=0, proof=proof,
            installation_verified=False, writer_verified=False, capture_verified=False,
            guest_signature_verified=False, bypass_executed=False, physical_devices_used=False)
        # JSON tuples become lists; normalize before comparing across contract subprocesses.
        result = json.loads(json.dumps(result))
        _save(output / 'dev-file-package.json', result)
        return result


def verify(official, derived, output, *, fwtool_dir, current_version='2.01', scratch=None):
    _version(current_version)
    output = _output(output, scratch=scratch)
    try:
        return _verify(official, derived, output, fwtool_dir, current_version, _kit(fwtool_dir))
    except BaseException as error:
        _save(output / 'failure.json', dict(error=repr(error), installation_verified=False))
        raise


def build(official, plaintext, output, *, fwtool_dir, current_version='2.01', scratch=None):
    _version(current_version)
    output = _output(output, scratch=scratch)
    try:
        kit = _kit(fwtool_dir)
        virtual, dat, fdat, builder, ext2 = kit
        with ExitStack() as stack:
            sources = [virtual['_Source'](p) for p in (official, plaintext)]
            for source in sources: stack.callback(source.close)
            original, plain = sources
            if (original.sha256 != STOCK_SHA or original.info.st_size != PACKAGE_BYTES
                    or plain.sha256 != PLAIN_SHA or plain.info.st_size != PLAIN_BYTES):
                raise ValueError('Build requires exact read-only official 2.01 package and full plaintext')
            before_image, image = output / 'p15.official.ext2', output / 'p15.modified.ext2'
            rows, sums, ranges = _tar(plain.path, before_image, builder, fdat, virtual)
            tree = _tree(before_image, builder, ext2)
            if MARKER in tree: raise ValueError('Marker already exists in official source')
            _edit_image(before_image, image, output, builder)
            rebuilt = output / 'firmware.modified.fdat'
            shutil.copyfile(plain.path, rebuilt)
            with rebuilt.open('r+b') as stream:
                header = stream.read(512)
                stream.seek(0); stream.write(builder['version_header'](header, '2.02'))
                stream.seek(ranges[0][0])
                with image.open('rb') as content: shutil.copyfileobj(content, stream, CHUNK)
                stream.seek(ranges[1][0]); stream.write(builder['update_sum'](sums, builder['file_crc'](image), IMAGE_BYTES))
                stream.flush(); os.fsync(stream.fileno())
            builder['package'].__globals__.update(SOURCE=original.path, OUT=output, DAT_NAME='BODYDATA.DAT')
            builder['package'](rebuilt)
            for source in sources: source.verify()
        verification = output / 'verification'
        verification.mkdir(mode=0o700)
        result = _verify(official, output / 'BODYDATA.DAT', verification, fwtool_dir, current_version, kit)
        if builder['sha_file'](rebuilt) != result['proof']['plain']['sha256']:
            raise ValueError('Independent re-decryption differs from built complete plaintext')
        return result
    except BaseException as error:
        _save(output / 'failure.json', dict(error=repr(error), installation_verified=False))
        raise


def contract(receipt_path, receipt_sha256, *, output_root=None):
    """Recompute all proof from packages; no expected-SHA/boolean admission shortcut."""
    dev = runpy.run_path(str(HERE / 'p1-dev-install.py'))
    value, row = dev['api']()['checked_json'](receipt_path)
    if row['sha256'] != receipt_sha256 or value.get('schema') != SCHEMA or value.get('kind') != KIND:
        raise ValueError('Unknown fixed-file receipt identity/kind')
    _version(value.get('current_version'))
    root = _scratch_root(output_root)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent = Path(tempfile.mkdtemp(prefix='preflight-', dir=root))
    destination = parent / 'verification'
    result = subprocess.run([sys.executable, '-B', str(HERE / 'p1-dev-file-package.py'), 'verify',
        '--official', value['original']['path'], '--derived', value['derived']['path'],
        '--output', str(destination), '--fwtool-dir', value['fwtool_dir'],
        '--current-version', value['current_version'], '--scratch', str(parent)], capture_output=True,
        env=dict(os.environ, TMPDIR=str(parent)))
    (parent / 'verify.stdout').write_bytes(result.stdout)
    (parent / 'verify.stderr').write_bytes(result.stderr)
    _save(parent / 'verify-process.json', dict(returncode=result.returncode))
    if result.returncode:
        raise ValueError('Fixed-file full package/image/tree preflight failed: ' + str(parent))
    actual = json.loads((destination / 'dev-file-package.json').read_text())
    if actual != value:
        raise ValueError('Fixed-file receipt differs from independent complete recomputation: ' + str(parent))
    # Recheck the receipt after subprocess execution as well as its package sources.
    again, current = dev['api']()['checked_json'](receipt_path)
    if current != row or again != value:
        raise ValueError('Fixed-file receipt changed during verification')
    return dict(receipt=row, value=value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('build', 'verify'))
    for name in ('official', 'output', 'fwtool-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--plaintext', type=Path)
    parser.add_argument('--derived', type=Path)
    parser.add_argument('--current-version', default='2.01')
    parser.add_argument('--scratch', type=Path, help='explicit private analysis/scratch root for this verification')
    args = vars(parser.parse_args()); action = args.pop('action')
    irrelevant = 'derived' if action == 'build' else 'plaintext'
    if args.pop(irrelevant) is not None or args['plaintext' if action == 'build' else 'derived'] is None:
        parser.error('build requires only --plaintext; verify requires only --derived')
    os.umask(0o077)
    if args.get('scratch') is not None:
        scratch = _scratch_root(args['scratch']); scratch.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ['TMPDIR'] = str(scratch)
    print(json.dumps(globals()[action](**args), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
