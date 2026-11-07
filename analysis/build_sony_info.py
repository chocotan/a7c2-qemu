#!/usr/bin/env python3
"""Build/verify an OFFLINE experimental DAT; no device or SD access.

The original unknown 256-byte footer is retained, NOT re-signed or verified.
Neither checksum consistency nor successful decryption proves installability.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import zlib

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'runtime/analysis/vendor/fwtool'))
from Cryptodome.Cipher import AES
from fwtool.sony import constants, dat, fdat
from fwtool.io import FilePart

SOURCE = ROOT.parent / 'BODYDATA.DAT'
PLAIN = ROOT / 'firmware.fdat'
SCRIPT = ROOT / 'custom/hello.sh'
OUT = ROOT / 'output/sony-info-experimental'
VERSION = '2.01'
IMAGE_NAME = '0700_part_image/dev/nflasha15'
SUM_NAME = '0701_part_image_sum/part_image.sum'
DAT_NAME = 'BODYDATA_sony-info_EXPERIMENTAL_UNVERIFIED.DAT'
ORIGINAL_SHA = 'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'


def digest(stream):
    sha = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        sha.update(chunk)
    return sha.hexdigest()


def sha_file(path):
    with path.open('rb') as stream:
        return digest(stream)


def file_crc(path):
    with path.open('rb') as stream:
        return part_crc(stream)


def part_crc(stream):
    crc = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        crc = zlib.crc32(chunk, crc)
    return crc


def update_sum(data, crc, size):
    lines = data.splitlines(keepends=True)
    changed = 0
    for index, line in enumerate(lines):
        fields = line.split(b',')
        if len(fields) > 10 and fields[0] == b'0' and fields[10] == b'dev/nflasha15':
            if int(fields[2], 16) != size:
                raise ValueError('Partition size mismatch in sum file')
            fields[1] = f'{crc:08x}'.encode()
            lines[index] = b','.join(fields)
            changed += 1
    result = b''.join(lines)
    if changed != 1 or len(result) != len(data):
        raise ValueError('Unexpected checksum list format')
    return result


def encrypt_blocks(plain, output, iv):
    ecb = AES.new(constants.key_aes, AES.MODE_ECB)
    cbc = AES.new(constants.key_cxd90057_k8, AES.MODE_CBC, iv)
    packer = fdat.BlockCrypter(1024)
    data = plain.read(1020)
    count = 0
    pending = bytearray()
    while data:
        following = plain.read(1020)
        packer.isLastBlock = not following
        block = packer.packBlock(data)
        pending += (ecb.encrypt(block[:512]) + cbc.encrypt(block[512:])
                    if count == 0 else cbc.encrypt(block))
        if len(pending) >= 1024 * 1024:
            output.write(pending)
            pending.clear()
        count += 1
        data = following
    output.write(pending)
    return count


def metadata(member):
    return {key: getattr(member, key) for key in
            ('name', 'size', 'mode', 'uid', 'gid', 'uname', 'gname', 'mtime',
             'type', 'linkname', 'pax_headers', 'offset', 'offset_data')}


def version_header(header, version):
    if len(header) != 512 or header[:8] != b'UDTRFIRM' or header[12:16] != b'0100':
        raise ValueError('Unexpected FDAT header')
    if struct.unpack_from('<I', header, 8)[0] != zlib.crc32(header[12:]):
        raise ValueError('Original header CRC mismatch')
    if version not in {'2.01', '2.02'}:
        raise ValueError('Unsupported experiment version')
    result = bytearray(header)
    result[32] = int(version.split('.')[1], 16)
    result[33] = 2
    struct.pack_into('<I', result, 8, zlib.crc32(result[12:]))
    return result


def bump_existing():
    base = ROOT / 'output/sony-info-experimental'
    record = json.loads((base / 'verification.json').read_text())
    if sha_file(base / 'BODYDATA_sony-info_EXPERIMENTAL_UNVERIFIED.DAT') != record['sha256']:
        raise ValueError('Previous experiment hash mismatch')
    OUT.mkdir(parents=True, exist_ok=False)
    for name in ['usr.modified.ext2', 'firmware.modified.fdat', 'sony-info.sh']:
        shutil.copyfile(base / name, OUT / name)
    with (OUT / 'firmware.modified.fdat').open('r+b') as plain:
        header = version_header(plain.read(512), VERSION)
        plain.seek(0)
        plain.write(header)
    with (base / 'firmware.modified.fdat').open('rb') as old, (OUT / 'firmware.modified.fdat').open('rb') as new:
        old.seek(512); new.seek(512)
        if digest(old) != digest(new):
            raise ValueError('Version bump changed payload')
    (OUT / 'NOT_VERIFIED_FOR_INSTALLATION.txt').write_text(
        'OFFLINE EXPERIMENT ONLY. Numeric upgrade version 2.02; no menu patch.\n'
        'Unknown original 256-byte footer retained, NOT newly signed or verified.\n'
        'Normal SD installation has NOT been tested.\n')
    package(OUT / 'firmware.modified.fdat')
    verify()


def build():
    if sha_file(SOURCE) != ORIGINAL_SHA:
        raise ValueError('Original DAT hash changed')
    if VERSION == '2.02':
        bump_existing()
        return
    with SOURCE.open('rb') as source:
        container = dat.readDat(source)
        _, decoded = fdat.decryptFdat(container.firmwareData)
        if digest(decoded) != sha_file(PLAIN):
            raise ValueError('Existing plaintext does not match original DAT')
    OUT.mkdir(parents=True, exist_ok=False)
    (OUT / 'NOT_VERIFIED_FOR_INSTALLATION.txt').write_text(
        'OFFLINE EXPERIMENT ONLY. Unknown 256-byte footer retained from original.\n'
        'No valid new signature has been produced. Normal SD installation has NOT been tested.\n'
        'Version remains 2.01; same-version rejection may also occur.\n')
    shutil.copyfile(SCRIPT, OUT / 'sony-info.sh')
    image = OUT / 'usr.modified.ext2'
    shutil.copyfile(ROOT / 'extracted/firmware' / IMAGE_NAME, image)
    commands = OUT / 'debugfs.commands'
    # debugfs operates on a regular copied image, never a block device.
    script_path = OUT / 'sony-info.sh'
    if any(c in str(script_path) for c in '\n\r"'):
        raise ValueError('Unsupported path characters')
    commands.write_text(f'write "{script_path}" /bin/sony-info\n'
                        'set_inode_field /bin/sony-info mode 0100755\n'
                        'set_inode_field /bin/sony-info uid 0\n'
                        'set_inode_field /bin/sony-info gid 0\n')
    result = subprocess.run(['debugfs', '-w', '-f', str(commands), str(image)],
                            capture_output=True, text=True, check=True)
    (OUT / 'debugfs.log').write_text(result.stdout + result.stderr)
    with (OUT / 'e2fsck.log').open('w') as log:
        subprocess.run(['e2fsck', '-fn', str(image)], stdout=log, stderr=subprocess.STDOUT, check=True)
    rebuilt = OUT / 'firmware.modified.fdat'
    shutil.copyfile(PLAIN, rebuilt)
    with PLAIN.open('rb') as original, rebuilt.open('r+b') as target:
        info = fdat.readFdat(original)
        with tarfile.open(fileobj=info.firmware, mode='r:') as archive:
            image_member = archive.getmember(IMAGE_NAME)
            sum_member = archive.getmember(SUM_NAME)
            if image.stat().st_size != image_member.size:
                raise ValueError('Do not resize the original partition')
            sum_data = archive.extractfile(sum_member).read()
            new_sum = update_sum(sum_data, file_crc(image), image_member.size)
            target.seek(info.firmware.offset + image_member.offset_data)
            with image.open('rb') as data:
                shutil.copyfileobj(data, target, 1024 * 1024)
            target.seek(info.firmware.offset + sum_member.offset_data)
            target.write(new_sum)
    # All tar headers/padding/order and the FDAT header are retained byte-for-byte.
    # Neither partition sizes nor internal firmware offsets need to change.
    package(rebuilt)
    verify()


def package(rebuilt):
    destination = OUT / DAT_NAME
    with SOURCE.open('rb') as original, destination.open('x+b') as output:
        chunks, total = dat.readChunks(original)
        parts = dict(chunks)
        payload = parts[b'FDAT']
        payload.seek(-0x110, 2)
        iv, footer = payload.read(16), payload.read(256)
        original.seek(0)
        output.write(original.read(payload.offset))
        with rebuilt.open('rb') as data:
            blocks = encrypt_blocks(data, output, iv)
        output.write(iv + footer)
        if output.tell() != payload.offset + payload.size:
            raise ValueError('Encrypted payload size changed')
        original.seek(payload.offset + payload.size)
        shutil.copyfileobj(original, output)
        if output.tell() != total:
            raise ValueError('DAT size changed')
        output.flush()
        crc = part_crc(FilePart(output, 0, total - 12))
        output.seek(parts[b'DEND'].offset)
        output.write(struct.pack('>I', crc))
    print(f'Built {destination} ({blocks} blocks). Starting offline verification.', flush=True)


def verify():
    destination = OUT / DAT_NAME
    if not destination.exists() and (OUT / 'BODYDATA.DAT').is_file():
        destination = OUT / 'BODYDATA.DAT'  # User renamed the local artifact for their test.
    rebuilt = OUT / 'firmware.modified.fdat'
    image = OUT / 'usr.modified.ext2'
    if sha_file(SOURCE) != ORIGINAL_SHA:
        raise ValueError('Original DAT changed')
    with SOURCE.open('rb') as source, destination.open('rb') as modified:
        original_parts, original_size = dat.readChunks(source)
        changed_parts, changed_size = dat.readChunks(modified)
        dat.readDat(modified)  # Check output outer CRC.
        if [(t, p.offset, p.size) for t, p in original_parts] != [(t, p.offset, p.size) for t, p in changed_parts]:
            raise ValueError('DAT chunk layout changed')
        if original_size != changed_size:
            raise ValueError('DAT length changed')
        for (tag, old), (_, new) in zip(original_parts, changed_parts):
            if tag not in {b'FDAT', b'DEND'} and digest(old) != digest(new):
                raise ValueError('Unexpected outer metadata change')
        old, new = dict(original_parts)[b'FDAT'], dict(changed_parts)[b'FDAT']
        old.seek(-0x110, 2); new.seek(-0x110, 2)
        if old.read() != new.read():
            raise ValueError('Original IV/unknown trailer not preserved')
        _, decoded = fdat.decryptFdat(new)
        if digest(decoded) != sha_file(rebuilt):
            raise ValueError('Re-decrypted output differs from modified plaintext')
    with PLAIN.open('rb') as before, rebuilt.open('rb') as after:
        old_info, new_info = fdat.readFdat(before), fdat.readFdat(after)
        before.seek(0); after.seek(0)
        if after.read(512) != version_header(before.read(512), VERSION) or new_info.version != VERSION:
            raise ValueError('FDAT version/header mismatch')
        if old_info.firmware.offset != new_info.firmware.offset:
            raise ValueError('Firmware section offset changed')
        if before.read(old_info.firmware.offset - 512) != after.read(new_info.firmware.offset - 512):
            raise ValueError('Updater image changed')
        with tarfile.open(fileobj=old_info.firmware, mode='r:') as original_tar, \
             tarfile.open(fileobj=new_info.firmware, mode='r:') as modified_tar:
            originals, modifieds = original_tar.getmembers(), modified_tar.getmembers()
            if [metadata(m) for m in originals] != [metadata(m) for m in modifieds]:
                raise ValueError('Tar metadata, order, or layout changed')
            for old, new in zip(originals, modifieds):
                if not old.isfile():
                    continue
                if old.name not in {IMAGE_NAME, SUM_NAME}:
                    if digest(original_tar.extractfile(old)) != digest(modified_tar.extractfile(new)):
                        raise ValueError('Unexpected payload change: ' + old.name)
            if digest(modified_tar.extractfile(IMAGE_NAME)) != sha_file(image):
                raise ValueError('Packaged partition differs from modified image')
            sums = modified_tar.extractfile(SUM_NAME).read()
            expected_sum = update_sum(original_tar.extractfile(SUM_NAME).read(),
                                      file_crc(image), image.stat().st_size)
            if sums != expected_sum:
                raise ValueError('Unexpected checksum list change')
            for line in sums.splitlines():
                fields = line.split(b',')
                if fields[0] != b'0':
                    continue
                name = '0700_part_image/' + fields[10].decode()
                member = modified_tar.getmember(name)
                if member.size != int(fields[2], 16) or part_crc(modified_tar.extractfile(member)) != int(fields[1], 16):
                    raise ValueError('Partition size/CRC mismatch: ' + name)
            changed_ranges = sorted((old_info.firmware.offset + original_tar.getmember(name).offset_data,
                                     original_tar.getmember(name).size)
                                    for name in [IMAGE_NAME, SUM_NAME])
            if VERSION != old_info.version:
                changed_ranges = [(8, 4), (32, 2)] + changed_ranges
        start = 0
        for offset, size in changed_ranges + [(PLAIN.stat().st_size, 0)]:
            if digest(FilePart(before, start, offset - start)) != digest(FilePart(after, start, offset - start)):
                raise ValueError('Unexpected change outside the allowed payload/header regions')
            start = offset + size
    with tempfile.TemporaryDirectory(prefix='sony-info-check-') as temporary:
        dumped = Path(temporary) / 'sony-info'
        subprocess.run(['debugfs', '-R', f'dump /bin/sony-info {dumped}', str(image)],
                       capture_output=True, check=True)
        if not dumped.exists() or not (dumped.read_bytes() == (OUT / 'sony-info.sh').read_bytes() == SCRIPT.read_bytes()):
            raise ValueError('Added command absent or differs')
        status = subprocess.run(['debugfs', '-R', 'stat /bin/sony-info', str(image)],
                                capture_output=True, text=True, check=True)
        if not re.search(r'Type:\s+regular\s+Mode:\s+0755', status.stdout):
            raise ValueError('Added command not executable regular file')
        (OUT / 'sony-info-inode.txt').write_text(status.stdout + status.stderr)
        subprocess.run(['sh', '-n', str(dumped)], check=True)
        subprocess.run(['sh', str(ROOT / 'custom/test_hello.sh')], check=True)
    with (OUT / 'e2fsck.log').open('w') as log:
        subprocess.run(['e2fsck', '-fn', str(image)], stdout=log, stderr=subprocess.STDOUT, check=True)
    artifact_sha = sha_file(destination)
    device_test_path = OUT / 'device-test.json'
    device_test = json.loads(device_test_path.read_text()) if device_test_path.exists() else {}
    applies = device_test.get('artifact_sha256') == artifact_sha
    report = {'artifact': str(destination.relative_to(ROOT.parent)),
              'bytes': destination.stat().st_size, 'sha256': artifact_sha,
              'original_sha256': ORIGINAL_SHA, 'original_unchanged': True,
              'feature': '/usr/bin/sony-info; manual read-only command; no autorun or menu change',
              'firmware_version': new_info.version, 'version_changed': new_info.version != old_info.version,
              'menu_display_patched': False,
              'changed_tar_members': [IMAGE_NAME, SUM_NAME],
              'all_bytes_outside_allowed_regions_identical': True,
              'tar_metadata_preserved': True, 'updater_preserved': True,
              'fdat_header_only_version_and_crc_changed': VERSION != old_info.version,
              'partition_crcs_valid': True, 'outer_crc_valid': True,
              're_decryption_and_all_block_checksums_valid': True,
              'filesystem_check_passed': True, 'command_mode': '0755',
              'command_sha256': sha_file(OUT / 'sony-info.sh'),
              'unknown_footer': 'original 256 bytes retained; not regenerated or verified',
              'signature_verified': False,
              'device_installation_tested': bool(applies and device_test.get('installation_attempted')),
              'device_installation_result': device_test.get('installation_result') if applies else 'not_tested',
              'device_installation_evidence': 'user_report' if applies else None,
              'device_execution_tested': False, 'flashable_claim': False}
    (OUT / 'verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))


def self_test():
    header = bytearray(512)
    header[:8], header[12:16], header[32:34] = b'UDTRFIRM', b'0100', b'\x01\x02'
    struct.pack_into('<I', header, 8, zlib.crc32(header[12:]))
    assert version_header(header, '2.01') == header
    changed = version_header(header, '2.02')
    assert changed[32:34] == b'\x02\x02'
    assert struct.unpack_from('<I', changed, 8)[0] == zlib.crc32(changed[12:])
    assert all(header[i] == changed[i] for i in range(512) if i not in {8, 9, 10, 11, 32, 33})
    line = b'0,12345678,00000003,000001a4,0,0,root,root,-1,-1,dev/nflasha15,\n'
    assert update_sum(line, 1, 3) == line.replace(b'12345678', b'00000001')
    try:
        update_sum(line, 1, 4)
    except ValueError:
        pass
    else:
        raise AssertionError('Size change accepted')
    iv = bytes(range(16))
    for size in [512, 1020, 1021, 4093]:
        content = bytes(i % 251 for i in range(size))
        encrypted = io.BytesIO()
        count = encrypt_blocks(io.BytesIO(content), encrypted, iv)
        assert count == (size + 1019) // 1020
        encrypted.write(iv + b'\0' * 256)
        decoded = fdat._crypters['CXD90057_k8']().decrypt(encrypted).read()
        assert decoded == content
    print('PASS: version/header CRC, fixed-width partition CRC, size rejection, CBC round-trip')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['self-test', 'build', 'verify'])
    parser.add_argument('--version', choices=['2.01', '2.02'], default='2.01')
    args = parser.parse_args()
    VERSION = args.version
    if VERSION == '2.02':
        OUT = ROOT / 'output/sony-info-v2.02-experimental'
        DAT_NAME = 'BODYDATA_v2.02_sony-info_EXPERIMENTAL_UNVERIFIED.DAT'
    {'self-test': self_test, 'build': build, 'verify': verify}[args.action]()
