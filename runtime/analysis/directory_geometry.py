"""Independent arithmetic/BPB checks for the directory FAT32 profile."""
import struct

TOTAL_SECTORS = 500_000_000
SECTOR = 512
BOOT = 63
RESERVED = 32
SPC = 64


def layout():
    partition_sectors = TOTAL_SECTORS - BOOT
    divisor = 1 + SPC * SECTOR * 8 // 32
    sectors_per_fat = (partition_sectors + divisor) // divisor
    offset_fat = BOOT + RESERVED
    offset_root = offset_fat + 2 * sectors_per_fat
    clusters = (partition_sectors - offset_root) // SPC + 2
    bpb_sectors = offset_root + SPC * (clusters - 2)
    assert sectors_per_fat * (SECTOR // 4) >= clusters
    assert clusters > 65525 and bpb_sectors <= partition_sectors
    return dict(total_sectors=TOTAL_SECTORS, partition_sectors=partition_sectors,
                sectors_per_fat=sectors_per_fat, offset_fat=offset_fat,
                offset_root=offset_root, cluster_one_past=clusters,
                bpb_sectors=bpb_sectors, root_cluster=2, sectors_per_cluster=SPC,
                reserved_sectors=RESERVED)


def check_boot(mbr, boot, fsinfo):
    expected = layout()
    if len(mbr) != 512 or len(boot) != 512 or len(fsinfo) != 512:
        raise ValueError('FAT metadata must be complete sectors')
    if mbr[510:512] != b'\x55\xaa' or boot[510:512] != b'\x55\xaa':
        raise ValueError('Missing MBR/BPB signature')
    partition = mbr[446:462]
    if partition[4] != 0x0c or struct.unpack_from('<I', partition, 8)[0] != BOOT:
        raise ValueError('Directory FAT32 partition identity mismatch')
    if struct.unpack_from('<I', partition, 12)[0] != expected['partition_sectors']:
        raise ValueError('Partition length mismatch')
    if struct.unpack_from('<H', boot, 11)[0] != SECTOR or boot[13] != SPC:
        raise ValueError('Sector/cluster geometry mismatch')
    if struct.unpack_from('<H', boot, 14)[0] != RESERVED or boot[16] != 2:
        raise ValueError('FAT32 reserved/FAT count mismatch')
    if struct.unpack_from('<H', boot, 17)[0] != 0 or struct.unpack_from('<H', boot, 22)[0] != 0:
        raise ValueError('FAT16 fields were not cleared')
    if struct.unpack_from('<I', boot, 32)[0] != expected['partition_sectors']:
        raise ValueError('BPB total does not match the containing partition')
    if struct.unpack_from('<I', boot, 36)[0] != expected['sectors_per_fat']:
        raise ValueError('FAT size mismatch')
    if struct.unpack_from('<H', boot, 40)[0] != 0 or boot[42:44] != b'\0\0':
        raise ValueError('FAT32 flags/version contaminated')
    if struct.unpack_from('<I', boot, 44)[0] != 2:
        raise ValueError('FAT32 root cluster mismatch')
    if struct.unpack_from('<H', boot, 48)[0] != 1 or struct.unpack_from('<H', boot, 50)[0] != 6:
        raise ValueError('FSInfo/backup sector mismatch')
    if boot[82:90] != b'FAT32   ':
        raise ValueError('FAT32 type label mismatch')
    if (struct.unpack_from('<I', fsinfo, 0)[0] != 0x41615252 or
            struct.unpack_from('<I', fsinfo, 484)[0] != 0x61417272 or
            struct.unpack_from('<I', fsinfo, 488)[0] != 0xffffffff or
            struct.unpack_from('<I', fsinfo, 492)[0] != 2 or fsinfo[508:512] != b'\x00\x00\x55\xaa'):
        raise ValueError('FSInfo content mismatch')
    return expected
