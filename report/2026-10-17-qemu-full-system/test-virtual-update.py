#!/usr/bin/env python3
"""Small real FAT/UFU/FDAT/tar fixtures; no QEMU, physical disk or source dump."""
import binascii
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('virtual_update_tested', HERE / 'virtual-update.py')
UPDATE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(UPDATE)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fat_fixture(path, payload, bits=12):
    clusters = {12: 250, 16: 4096, 32: 65525}[bits]
    reserved, roots = (32, 0) if bits == 32 else (1, 16)
    fat_sectors = ((clusters + 2) * bits + 4095) // 4096
    root_sectors = (roots * 32 + 511) // 512
    data_sector = reserved + fat_sectors + root_sectors
    total = data_sector + clusters
    header = bytearray(512)
    header[:3] = b'\xeb\x3c\x90'
    header[3:11] = b'MSDOS5.0'
    struct.pack_into('<HBHBHHBHHHII', header, 11, 512, 1, reserved, 1, roots,
                     total if total < 65536 else 0, 0xf8,
                     fat_sectors if bits != 32 else 0, 32, 64, 0, total if total >= 65536 else 0)
    if bits == 32:
        struct.pack_into('<IHHIHH', header, 36, fat_sectors, 0, 0, 2, 1, 6)
        header[82:90] = b'FAT32   '
    else:
        header[54:62] = b'FAT12   ' if bits == 12 else b'FAT16   '
    header[510:] = b'\x55\xaa'
    table = bytearray(fat_sectors * 512)

    def put(cluster, value):
        offset = cluster * bits // 8
        if bits == 12:
            old = int.from_bytes(table[offset:offset + 2], 'little')
            value = old & 15 | value << 4 if cluster & 1 else old & 0xf000 | value
            table[offset:offset + 2] = value.to_bytes(2, 'little')
        else:
            table[offset:offset + bits // 8] = value.to_bytes(bits // 8, 'little')

    eoc = {12: 0xfff, 16: 0xffff, 32: 0xfffffff}[bits]
    put(0, eoc & ~7)
    put(1, eoc)
    start = 3 if bits == 32 else 2
    if bits == 32:
        put(2, eoc)
    count = (len(payload) + 511) // 512
    if count + start > clusters + 2:
        raise ValueError('Fixture too large')
    for i in range(count):
        put(start + i, start + i + 1 if i + 1 < count else eoc)
    entry = bytearray(32)
    entry[:11] = b'BODYDATADAT'
    entry[11] = 0x20
    struct.pack_into('<H', entry, 26, start if count else 0)
    struct.pack_into('<I', entry, 28, len(payload))
    with path.open('xb') as stream:
        stream.truncate(total * 512)
        stream.seek(0)
        stream.write(header)
        stream.seek(reserved * 512)
        stream.write(table)
        root = data_sector * 512 if bits == 32 else (reserved + fat_sectors) * 512
        stream.seek(root)
        stream.write(entry)
        stream.seek((data_sector + start - 2) * 512)
        stream.write(payload)


def tar_bytes(*, p5=True, partconf=True, oversized=False, unsafe=False, sum_bad=False):
    output = io.BytesIO()
    p5_data = b'WBI2' + b'package-WBI!' * 133
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        def add(name, data):
            member = tarfile.TarInfo(name)
            member.mode = 0o644
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))

        if unsafe:
            add('../escape', b'no')
        if partconf:
            conf = b'0x0,0x1000,0x5,0xffffffff\n' * 4 + b'0x0,0x1000,0x6,0xffffffff\n'
            add('0300_partconf/partinf.conf', conf)
            crc = binascii.crc32(conf) ^ (1 if sum_bad else 0)
            line = f'0,{crc:08x},{len(conf):08x},000001a4,0,0,root,root,-1,-1,partinf.conf,\n'.encode()
            add('0301_partconf_sum/partconf.sum', line)
        add('0700_part_image/dev/nflasha3', b'new-kernel' * 61)
        if p5:
            add('0700_part_image/dev/nflasha5', bytes(8192) if oversized else p5_data)
        data = b'new-kernel' * 61
        summary = f'0,{binascii.crc32(data):08x},{len(data):08x},0,0,0,root,root,-1,-1,dev/nflasha3,\n'
        if p5 and not oversized:
            summary += f'0,{binascii.crc32(p5_data):08x},{len(p5_data):08x},0,0,0,root,root,-1,-1,dev/nflasha5,\n'
        add('0701_part_image_sum/part_image.sum', summary.encode())
        link = tarfile.TarInfo('0800_appli/tmp/mtab')
        link.type, link.linkname = tarfile.SYMTYPE, '../proc/mounts'
        archive.addfile(link)
        add('0801_appli_sum/appli.sum', b'2,ffffffff,00000000,000001ff,0,0,root,root,-1,-1,tmp/mtab,../proc/mounts\n')
    return output.getvalue(), p5_data


def fdat_bytes(tar):
    updater = b'actual-updater-section'
    header = bytearray(512)
    header[:8] = b'UDTRFIRM'
    header[12:16] = b'0100'
    header[16], header[20], header[32], header[33] = ord('U'), ord('N'), 1, 2
    struct.pack_into('<II', header, 36, 0x20030014, 0)
    struct.pack_into('<III', header, 48, 512 + len(updater), len(tar), 1)
    struct.pack_into('<c3xII4x', header, 64, b'U', 512, len(updater))
    struct.pack_into('<I', header, 8, binascii.crc32(header[12:]))
    return bytes(header) + updater + tar


def package_bytes(clear):
    data = bytearray(UPDATE.MAGIC)
    for kind, content in ((b'DATV', struct.pack('>HH', 0x100, 0)),
                          (b'PROV', struct.pack('>HH', 0x100, 0)),
                          (b'UDID', struct.pack('>I', 0)), (b'FDAT', clear)):
        data += struct.pack('>I4s', len(content), kind) + content
    data += struct.pack('>I4sI', 4, b'DEND', binascii.crc32(data))
    return bytes(data)


def plaintext_decoder(source, destination, fwtool_dir):
    _, chunks = UPDATE.IMPORT.chunks(source)
    offset, size = chunks[b'FDAT']
    source.seek(offset)
    destination.write(source.read(size))
    return {'decrypter': 'fixture-plaintext', 'block_checksums_valid': None,
            'execution_kind': 'original', 'guest_original_install_verified': True}


class VirtualUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='virtual-update-test-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.originals = {}
        for index, name in enumerate(sorted(UPDATE.NAMES)):
            data = bytes([index + 33]) * 4096
            if name == 'nflasha5.img':
                data = b'WBI2-original' + data[13:]
            (self.source / name).write_bytes(data)
            self.originals[name] = data
        self.manifest = self.source / 'manifest.json'
        self.save_manifest()
        self.sd = self.root / 'sd.img'
        self.make_sd()
        self.out = self.root / 'installed'

    def tearDown(self):
        self.temp.cleanup()

    def save_manifest(self, source_class='private-device-dump'):
        rows = [{'name': name, 'bytes': (self.source / name).stat().st_size,
                 'sha256': sha((self.source / name).read_bytes())} for name in sorted(UPDATE.NAMES)]
        self.manifest.write_text(json.dumps({'source': source_class, 'images': rows}))

    def make_sd(self, **kwargs):
        tar, self.p5_data = tar_bytes(**kwargs)
        self.clear = fdat_bytes(tar)
        self.package = package_bytes(self.clear)
        self.sd.unlink(missing_ok=True)
        fat_fixture(self.sd, self.package)

    def install(self, **kwargs):
        return UPDATE.install_sd(self.sd, self.manifest, self.out, fwtool_dir=HERE,
                                 decoder=kwargs.pop('decoder', plaintext_decoder), **kwargs)

    def assert_source_unchanged(self):
        for name, expected in self.originals.items():
            self.assertEqual((self.source / name).read_bytes(), expected)

    def test_fat12_16_32_real_export(self):
        for bits in (12, 16, 32):
            with self.subTest(bits=bits):
                sd, out = self.root / f'fat{bits}.img', self.root / f'export{bits}'
                out.mkdir()
                fat_fixture(sd, self.package, bits)
                result = UPDATE.read_sd_package(sd, out)
                self.assertEqual(result['fat_bits'], bits)
                self.assertEqual((out / 'BODYDATA.DAT').read_bytes(), self.package)
                self.assertEqual(result['sha256'], sha(self.package))

    def test_fat_zero_padding_is_audited_and_nonzero_rejected(self):
        self.sd.write_bytes(self.sd.read_bytes() + bytes(1024))
        out = self.root / 'padding-export'
        out.mkdir()
        self.assertEqual(UPDATE.read_sd_package(self.sd, out)['sha256'], sha(self.package))
        with self.sd.open('r+b') as stream:
            stream.seek(-1, 2)
            stream.write(b'x')
        other = self.root / 'nonzero-export'
        other.mkdir()
        with self.assertRaisesRegex(ValueError, 'Nonzero trailing payload'):
            UPDATE.read_sd_package(self.sd, other)

    def test_p5_overwrites_drop_and_all_tails_stay_fixed(self):
        result = self.install()
        self.assertEqual(result['state'], 'host_partition_model_applied')
        self.assertTrue(result['partition_stream_verified'])
        self.assertEqual(result['wbi_dropped'], ['nflasha5'])
        self.assertTrue(result['p5']['drop_zero_header_overwritten'])
        self.assertTrue(result['p5']['package_payload_readback_valid'])
        image = (self.out / 'images/nflasha5.img').read_bytes()
        self.assertEqual(image, self.p5_data + self.originals['nflasha5.img'][len(self.p5_data):])
        self.assertEqual(result['final_mode'], 'unknown')
        self.assertEqual(result['poststate']['status'], 'blocked')
        self.assertFalse(result['guest_original_install_verified'])
        self.assertFalse(result['sd_receiver_executed'])
        self.assertEqual(result['execution_kind'], 'host_functional')
        self.assertEqual(result['decoded']['execution_kind'], 'host_functional')
        self.assertFalse(result['decoded']['guest_original_install_verified'])
        self.assertEqual(result['decoded']['package']['signature']['status'], 'unknown')
        self.assertEqual(len(result['retained_images']), 19)
        self.assert_source_unchanged()
        records = [json.loads(line) for line in (self.out / 'state.jsonl').read_text().splitlines()]
        states = [r['state'] for r in records]
        self.assertLess(states.index('wbi_drop_verified'), states.index('partition_image_verified'))
        self.assertEqual(records[states.index('wbi_drop_verified')]['readback_hex'], bytes(512).hex())
        self.assertEqual(len(records), result['journal_records'])
        self.assertEqual(json.loads((self.out / 'receipt.json').read_text()), result)
        for name in UPDATE.NAMES:
            self.assertNotEqual((self.source / name).stat().st_ino, (self.out / 'images' / name).stat().st_ino)
            self.assertEqual((self.out / 'images' / name).stat().st_size, 4096)

    def test_no_package_p5_leaves_zero_header_and_original_tail(self):
        self.make_sd(p5=False)
        result = self.install()
        self.assertFalse(result['p5']['package_image_written_back'])
        self.assertFalse(result['p5']['starts_with_WBI2'])
        self.assertEqual((self.out / 'images/nflasha5.img').read_bytes(), bytes(512) + self.originals['nflasha5.img'][512:])
        self.assert_source_unchanged()

    def test_no_partconf_does_not_invent_drop(self):
        self.make_sd(p5=False, partconf=False)
        result = self.install()
        self.assertEqual(result['wbi_dropped'], [])
        self.assertEqual((self.out / 'images/nflasha5.img').read_bytes(), self.originals['nflasha5.img'])

    def test_short_pwrite_is_completed_and_read_back(self):
        pwrite = os.pwrite
        def short(fd, data, offset):
            return pwrite(fd, data[:max(1, len(data) // 2)], offset)
        with patch.object(UPDATE.os, 'pwrite', side_effect=short):
            result = self.install()
        self.assertTrue(result['partition_stream_verified'])
        self.assertTrue(result['p5']['package_payload_readback_valid'])

    def test_zero_pwrite_is_error_with_original_images(self):
        with patch.object(UPDATE.os, 'pwrite', return_value=0):
            with self.assertRaises(UPDATE.InstallError) as caught:
                self.install()
        receipt = caught.exception.receipt
        self.assertIn('Zero/invalid', receipt['error']['message'])
        self.assertEqual(receipt['partition_bytes_written'], 0)
        self.assertFalse(receipt['partition_stream_verified'])
        self.assertEqual((self.out / 'images/nflasha5.img').read_bytes(), self.originals['nflasha5.img'])
        self.assert_source_unchanged()

    def test_short_then_zero_retains_partial_and_original_error(self):
        pwrite = os.pwrite
        calls = 0
        def partial(fd, data, offset):
            nonlocal calls
            calls += 1
            return pwrite(fd, data[:17], offset) if calls == 1 else 0
        with patch.object(UPDATE.os, 'pwrite', side_effect=partial):
            with self.assertRaises(UPDATE.InstallError) as caught:
                self.install()
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 17)
        self.assertEqual((self.out / 'images/nflasha5.img').read_bytes(), bytes(17) + self.originals['nflasha5.img'][17:])
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assert_source_unchanged()

    def test_failure_after_actual_write_keeps_partial_and_no_rollback(self):
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install(fail_after=513)
        receipt = caught.exception.receipt
        self.assertEqual(receipt['partition_bytes_written'], 513)
        self.assertEqual(receipt['state'], 'failed')
        self.assertFalse(receipt['automatic_rollback'])
        self.assertEqual((self.out / 'images/nflasha5.img').read_bytes()[:512], bytes(512))
        image = (self.out / 'images/nflasha3.img').read_bytes()
        self.assertEqual(image, b'n' + self.originals['nflasha3.img'][1:])
        self.assertTrue((self.out / 'receipt.json').is_file())
        self.assert_source_unchanged()

    def test_oversized_partition_refused_after_prior_writes(self):
        self.make_sd(oversized=True)
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('capacity', str(caught.exception))
        self.assertGreater(caught.exception.receipt['partition_bytes_written'], 512)
        self.assertEqual((self.out / 'images/nflasha5.img').stat().st_size, 4096)
        self.assertEqual((self.out / 'images/nflasha5.img').read_bytes()[:512], bytes(512))
        self.assert_source_unchanged()

    def test_crc_error_prevents_partition_write(self):
        damaged = bytearray(self.package)
        damaged[80] ^= 1
        self.sd.unlink()
        fat_fixture(self.sd, damaged)
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('UFU outer CRC', str(caught.exception))
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_fdat_crc_checked_independently(self):
        clear = bytearray(self.clear)
        clear[100] ^= 1
        self.sd.unlink()
        fat_fixture(self.sd, package_bytes(clear))
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('FDAT header CRC', str(caught.exception))
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_tar_file_sum_crc_checked_before_drop(self):
        self.make_sd(sum_bad=True)
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('CRC/size mismatch', str(caught.exception))
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_tar_nonzero_trailer_is_rejected_after_actual_writes(self):
        tar, _ = tar_bytes()
        self.sd.unlink()
        fat_fixture(self.sd, package_bytes(fdat_bytes(tar + b'second-archive')))
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('after tar end', str(caught.exception))
        self.assertGreater(caught.exception.receipt['partition_bytes_written'], 512)
        self.assert_source_unchanged()

    def test_zero_length_partition_image_is_rejected(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as archive:
            archive.addfile(tarfile.TarInfo('0700_part_image/dev/nflasha5'))
        self.sd.unlink()
        fat_fixture(self.sd, package_bytes(fdat_bytes(output.getvalue())))
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('Zero/out-of-capacity', str(caught.exception))
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_tar_header_checksum_is_checked(self):
        tar, _ = tar_bytes()
        tar = bytearray(tar)
        tar[99] ^= 1
        self.sd.unlink()
        fat_fixture(self.sd, package_bytes(fdat_bytes(tar)))
        with self.assertRaises(UPDATE.InstallError):
            self.install()
        self.assertEqual(json.loads((self.out / 'receipt.json').read_text())['partition_bytes_written'], 0)

    def test_unsafe_tar_path_never_materialised(self):
        self.make_sd(unsafe=True)
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install()
        self.assertIn('Unsafe tar path', str(caught.exception))
        self.assertFalse((self.root / 'escape').exists())

    def test_json_ack_cannot_replace_plaintext_or_claim_original(self):
        def ack(source, output, tools):
            return {'guest_original_install_verified': True, 'execution_kind': 'original'}
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install(decoder=ack)
        self.assertFalse(caught.exception.receipt['guest_original_install_verified'])
        self.assertIn('FDAT header', str(caught.exception))
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_source_changed_during_decode_is_detected_before_write(self):
        def mutate(source, output, tools):
            result = plaintext_decoder(source, output, tools)
            with (self.source / 'nflasha5.img').open('r+b') as victim:
                victim.write(b'changed')
            return result
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install(decoder=mutate)
        receipt = caught.exception.receipt
        self.assertFalse(receipt['source_images_unchanged'])
        self.assertTrue(receipt['source_check_errors'])
        self.assertEqual(receipt['partition_bytes_written'], 0)

    def test_original_error_survives_additional_source_change_failure(self):
        def fail(source, output, tools):
            (self.source / 'nflasha5.img').write_bytes(b'x' * 4096)
            raise RuntimeError('original decoder failure')
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install(decoder=fail)
        self.assertEqual(caught.exception.receipt['error']['message'], 'original decoder failure')
        self.assertTrue(caught.exception.receipt['source_check_errors'])
        self.assertEqual(str(caught.exception.__cause__), 'original decoder failure')

    def test_source_path_replacement_detected_even_same_bytes(self):
        def replace(source, output, tools):
            result = plaintext_decoder(source, output, tools)
            path = self.source / 'nflasha5.img'
            path.rename(path.with_suffix('.old'))
            path.write_bytes(self.originals[path.name])
            return result
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install(decoder=replace)
        self.assertIn('identity/metadata changed', str(caught.exception))
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_sd_changed_during_decode_is_detected(self):
        def mutate(source, output, tools):
            result = plaintext_decoder(source, output, tools)
            with self.sd.open('r+b') as victim:
                victim.seek(-1, 2)
                victim.write(b'x')
            return result
        with self.assertRaises(UPDATE.InstallError) as caught:
            self.install(decoder=mutate)
        self.assertFalse(caught.exception.receipt['source_images_unchanged'])
        self.assertEqual(caught.exception.receipt['partition_bytes_written'], 0)

    def test_host_symlinks_devices_and_existing_output_refused(self):
        link = self.root / 'sd-link'
        link.symlink_to(self.sd)
        for invalid in (link, Path('/dev/null')):
            with self.subTest(path=invalid):
                with self.assertRaises((ValueError, OSError)):
                    UPDATE.install_sd(invalid, self.manifest, self.out, fwtool_dir=HERE, decoder=plaintext_decoder)
                self.assertFalse(self.out.exists())
        self.out.mkdir()
        with self.assertRaisesRegex(ValueError, 'must not exist'):
            self.install()

    def test_parent_symlink_and_source_symlink_refused(self):
        link = self.root / 'source-link'
        link.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            UPDATE.install_sd(self.sd, link / 'manifest.json', self.out, fwtool_dir=HERE)
        original = self.source / 'nflasha5.img'
        other = self.source / 'p5-real'
        original.rename(other)
        original.symlink_to(other)
        with self.assertRaises((ValueError, OSError)):
            self.install()
        self.assertFalse(self.out.exists())

    def test_manifest_path_escape_and_wrong_hash_refused(self):
        data = json.loads(self.manifest.read_text())
        data['images'][0]['file'] = '../escape'
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'basename'):
            self.install()
        self.save_manifest()
        data = json.loads(self.manifest.read_text())
        data['images'][0]['sha256'] = '0' * 64
        self.manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'size/hash mismatch'):
            self.install()

    def test_aliased_source_inodes_are_rejected(self):
        first, second = self.source / 'nflashaB0.img', self.source / 'nflashaB1.img'
        second.unlink()
        os.link(first, second)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'independent inodes'):
            self.install()
        self.assertFalse(self.out.exists())

    def test_fullsystem_manifest_path_and_source_class(self):
        runtime = self.root / 'runtime/analysis'
        (runtime / 'root').mkdir(parents=True)
        shutil.copytree(self.source, runtime / 'root/partitions')
        full = runtime / 'full-system.json'
        data = json.loads(self.manifest.read_text())
        data['source'] = 'official-bodydata-derived'
        full.write_text(json.dumps(data))
        result = UPDATE.install_sd(self.sd, full, self.out, fwtool_dir=HERE, decoder=plaintext_decoder)
        self.assertEqual(result['input_source_class'], 'official-bodydata-derived')
        self.assertFalse(result['guest_original_install_verified'])

    def test_file_only_manifest_records(self):
        data = json.loads(self.manifest.read_text())
        for row in data['images']:
            row['file'] = row.pop('name')
        self.manifest.write_text(json.dumps(data))
        result = self.install()
        self.assertEqual(result['input_source_class'], 'private-device-dump')
        self.assertTrue(result['partition_stream_verified'])

    def test_space_checked_before_output_created(self):
        class NoSpace:
            f_bavail, f_frsize = 0, 4096
        with patch.object(UPDATE.os, 'fstatvfs', return_value=NoSpace()):
            with self.assertRaisesRegex(OSError, 'Insufficient space'):
                self.install()
        self.assertFalse(self.out.exists())

    def test_source_lock_is_enforced(self):
        fd = os.open(self.sd, os.O_RDONLY)
        try:
            UPDATE.fcntl.flock(fd, UPDATE.fcntl.LOCK_EX | UPDATE.fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.install()
        finally:
            os.close(fd)
        self.assertFalse(self.out.exists())

    def test_poststate_changes_real_fat_or_reports_blocked(self):
        dirs = list((HERE / 'runtime/analysis').glob('mtools-*/extracted/usr/bin'))
        if not dirs:
            self.skipTest('No prepared local mtools, blocked branch covered by install tests')
        tools = dirs[0]
        image = self.source / 'nflasha2.img'
        image.unlink()
        fat_fixture(image, b'keep-this-unrelated-file')
        empty = self.root / 'empty'
        empty.write_bytes(b'')
        env = {**os.environ, 'MTOOLSRC': '/dev/null', 'LC_ALL': 'C'}
        subprocess.run([str(tools / 'mmd'), '-i', str(image), '::/updater'], check=True, env=env, capture_output=True)
        for name in ('mode', 'mode5'):
            subprocess.run([str(tools / 'mcopy'), '-i', str(image), str(empty), '::/updater/' + name],
                           check=True, env=env, capture_output=True)
        self.originals['nflasha2.img'] = image.read_bytes()
        self.save_manifest()
        result = self.install(mtools_dir=tools)
        self.assertEqual(result['poststate']['status'], 'applied_host_subset')
        with UPDATE.FAT.FatImage(self.out / 'images/nflasha2.img', self.out, mtools_dir=tools,
                                 fmask=0o022, dmask=0o022) as fat:
            entries = fat.inventory()['entries']
        self.assertNotIn('/updater/mode5', entries)
        self.assertNotIn('/updater/mode', entries)
        self.assertEqual(result['poststate']['body_action'], 6)
        self.assertEqual(entries['/updater/comp']['size'], 0)
        self.assertEqual(entries['/BODYDATA.DAT']['sha256'], sha(b'keep-this-unrelated-file'))
        self.assert_source_unchanged()


if __name__ == '__main__':
    unittest.main(verbosity=2)
