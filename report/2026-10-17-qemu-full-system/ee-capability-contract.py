"""Fixed-2.01 source/asset contract for the EE input slice; no transport API."""
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import sys

CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
VA_DELTA = 0x108000
# SHA pins are filled from the independently reviewed original instruction ranges.
WINDOWS = {
    0x4245d0: (174, 'efbf076e173a7d0cd01d905b15ff626f16a230ce858437004085a6f27e7cdb39'),
    0x42467e: (418, '223a3d158faf99893f0e059fdcf341646879f9dc4d8ebf6d5f1891077a04bf2f'),
    0x42452c: (80, 'f27c1f9c27a05008182dffc22dec72ea88db039147a3511c1c2d7718fd6c4ffe'),
    0xac3a4e: (274, '57acc75374bf7c0ca6f95a182964ab9c99357d49f2d6926f62ba53009aae4afc'),
    0x424abc: (224, 'c112df4dfc9e35660c70efaa886632a19e025210158e2a23e0bf195e6e41f4ef'),
    0x424bcc: (16, 'e1fbe80a2c62fb629b758c520e49355cdc7933c5fd866521977cb29d5ea86dc6'),
    0x42506c: (140, '49513dfd38de27a554546fe1197a066c508f28ca1cf854e0cf67b3912ef25961'),
    0xbe9bae: (14, 'd12a9080b960632748984f65b655993b5232a3307ac36f0d959b45fe1a055ca7'),
    0x19fbf0: (100, '23c9592bc60c93c95e796a43c616bab8c73ef000ca59c1930df50dabfd915ac6'),
    0x19e9f4: (182, 'e1204b66e50a4898a8aae7cd8bd49e9e703174dcd93ee677a2929de373c1a864'),
    0x424b4e: (14, '70393e22e476fcc99ab4f70d2b097aedac54083228b51c8024d95dffdec1f8db'),
    0x424ef4: (10, '1384e9a885104962b0ba002fc87b6a5737e5bde4e65828bd2c910c069cc18f70'),
    0x424f28: (10, '84b0f70cf200e0c95dc6a300faf01581739515032a922be343d83a307a99b98c'),
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def verify_cp(path):
    data = Path(path).read_bytes()
    if sha(data) != CP_SHA:
        raise ValueError('Complete CP SHA256 mismatch')
    for address, (size, digest) in WINDOWS.items():
        if sha(data[address-VA_DELTA:address-VA_DELTA+size]) != digest:
            raise ValueError('CP VA/file relocation or window mismatch')
    return {'cp_sha256': CP_SHA, 'va_delta': VA_DELTA, 'windows_verified': len(WINDOWS)}

def parse_keymap(data):
    """BIN! envelope + section sizes + original 64B records, no private defaults."""
    if not 24 <= len(data) <= 0x1f98 or data[:4] != b'BIN!':
        raise ValueError('Invalid 01120000 envelope')
    count = struct.unpack_from('<I', data, 16)[0]
    if not 1 <= count <= (len(data)-20)//4:
        raise ValueError('Invalid section count')
    start = 20+4*count
    sizes = struct.unpack_from('<'+'I'*count, data, 20)
    if any(size % 64 for size in sizes) or sum(sizes) > len(data)-start:
        raise ValueError('Invalid key record size or section extent')
    # Original ac3a4e consumes only sizes[0] and starts after the entire size table.
    rows = data[start:start+sizes[0]]
    if not rows:
        raise ValueError('Empty first key table')
    groups = {}
    previous = None
    for offset in range(0, len(rows), 64):
        row = rows[offset:offset+64]
        group = struct.unpack_from('<I', row, 4)[0]
        if group in groups and previous != group:
            raise ValueError('Non-contiguous original group')
        groups.setdefault(group, bytearray()).extend(row)
        previous = group
    return {key: bytes(value) for key, value in groups.items()}

def read_backup(path, expected_sha, vendor, *, cp_bank_offset):
    """Read a caller-provided private copy; never opens a running instance."""
    data = Path(path).read_bytes()
    if len(expected_sha) != 64 or sha(data) != expected_sha:
        raise ValueError('Complete current Backup SHA256 mismatch')
    vendor = Path(vendor).resolve()
    parser = vendor/'pmca/backup/__init__.py'
    if not parser.is_file():
        raise ValueError('Explicit vendored Sony-PMCA-RE parser missing')
    # Use the project's existing checksum and property-pointer decoder.
    old = list(sys.path)
    try:
        sys.path.insert(0, str(vendor))
        from pmca.backup import BackupFile
        primary = BackupFile(io.BytesIO(data))
        if (primary.revision != 4 or type(cp_bank_offset) is not int
                or cp_bank_offset != (primary.size+4095)//4096*4096
                or not primary.size <= cp_bank_offset < len(data)
                or any(data[primary.size:cp_bank_offset])):
            raise ValueError('Explicit current-file CP bank boundary mismatch')
        backup = BackupFile(io.BytesIO(data[cp_bank_offset:]))
    finally:
        sys.path[:] = old
    if backup.revision != 4 or cp_bank_offset+backup.size != len(data):
        raise ValueError('Expected complete current AP+CP BK4 file without trailing banks')
    result = {'backup_sha256': expected_sha, 'backup_bytes': len(data),
              'cp_bank_offset': cp_bank_offset, 'cp_bank_sha256': sha(data[cp_bank_offset:]),
              'records': {}, 'unknown': []}
    for key, size in ((0x01120000, None), (0x00030162, 64), (0x00030a01, 4), (0x00030161, 4)):
        try:
            value = backup.getProperty(key).data
        except Exception as error:
            result['unknown'].append({'key': f'{key:08x}', 'reason': str(error)})
            continue
        if size is not None and len(value) != size:
            raise ValueError(f'{key:08x} record size mismatch')
        if key == 0x01120000:
            parse_keymap(value)
        result['records'][key] = value
    return result
