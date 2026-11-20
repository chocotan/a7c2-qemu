#!/usr/bin/env python3
"""Static page-table reconstruction from the exact official 2.01 NOR loader.

This does not execute the loader, emulate a physical bus, or prove BootROM boot.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import tarfile

BASE = 0xFE049000
SOURCE_BYTES = 94176
SOURCE_SHA = "5887ce4e6ca5fe1acdf6b675457f70e9798c61686f1d62c95190158855c96b22"
TAR_BYTES = 102400
TAR_SHA = "1edaab7c63196e84a941f5f2ad9595705e20d3e934735d9bcb20279b57f86d8a"
TAR_MEMBERS = {
    'loader_nor.bin': (SOURCE_BYTES, SOURCE_SHA),
    'LdrBkupList.txt': (660, 'eb2ad4f1846df54c963ee989e7adef81c497e806d1450b2f9043dcd3eb69ff80'),
    'pformat_config.txt': (1274, '21cd5b29dd165c322f5b00bb057802c377ff94af15f95881e150a32130302ece'),
    'loader_nor.md5': (152, '03035c63f5d609bfce6d960e03b6ddfb4c6c180ba389a56e1e25f501d30ff2b9'),
}
BUILDER_START, BUILDER_END = 0xFE0490D8, 0xFE049200
BUILDER_SHA = "2194d5725a345c91d60b593fa7c3f71f5a89a7198d6e9acb5f468c11ad201c76"
REGION_START, REGION_END = 0xFE049230, 0xFE049488
REGION_SHA = "df6a52a7e3869f03170ac6e6a27d8f61ce7e40bf0027b25703fcd5f771659ea7"
L2, ROOT36, ROOT32 = 0xFE180000, 0xFE200000, 0xFE202000
MEMORY_BYTES = 0x84000
BLOCK_BYTES = 0x200000
CONSTANTS = (
    (0xFE049218, ROOT36),
    (0xFE049220, ROOT32),
    (0xFE049228, L2),
    (0xFE049628, 0x122520),
    (0xFE049630, REGION_START),
    (0xFE049638, REGION_END),
    (0xFE05AF10, 0x12251C),
)


def read_at(source, va, size):
    offset = va - BASE
    if size < 0 or offset < 0 or offset > len(source) - size:
        raise ValueError("loader read outside exact raw input extent")
    return source[offset:offset + size]


def validate_source(source):
    if len(source) != SOURCE_BYTES or hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("unexpected official loader size/SHA256")
    for start, end, expected, label in (
        (BUILDER_START, BUILDER_END, BUILDER_SHA, "builder"),
        (REGION_START, REGION_END, REGION_SHA, "region table"),
    ):
        if hashlib.sha256(read_at(source, start, end - start)).hexdigest() != expected:
            raise ValueError("unexpected official " + label + " SHA256")
    validate_constants(source)


def validate_constants(source):
    for va, expected in CONSTANTS:
        if struct.unpack("<Q", read_at(source, va, 8))[0] != expected:
            raise ValueError(f"unexpected original constant at {va:#x}")


def validate_region(start, end, attrs):
    if (start < 0 or start & (BLOCK_BYTES - 1) or end & (BLOCK_BYTES - 1)
            or not start < end <= 1 << 36):
        raise ValueError("unexpected original region bounds/alignment")
    if attrs not in (0xF01, 0xF05, 0xC09, 0xF81):
        raise ValueError("unexpected original region attributes")


def store(memory, va, value):
    if (len(memory) != MEMORY_BYTES or va & 7
            or not L2 <= va <= L2 + len(memory) - 8):
        raise ValueError("table store outside original clear extents/alignment")
    if not 0 <= value < 1 << 64:
        raise ValueError("table descriptor outside unsigned 64-bit range")
    struct.pack_into("<Q", memory, va - L2, value)


def reconstruct(source):
    validate_source(source)
    memory = bytearray(MEMORY_BYTES)
    # Original clear extents are contiguous; this is synthetic table storage only.
    for index in range(64):
        table = index <= 3 or 16 <= index <= 19 or 32 <= index <= 51
        store(memory, ROOT36 + 8 * index,
              (L2 + 4096 * index) | (3 if table else 1))
    for index in range(4):
        store(memory, ROOT32 + 8 * index,
              (L2 + 4096 * index) | (3 if index == 3 else 1))
    regions = []
    for va in range(REGION_START, REGION_END, 24):
        start, end, attrs = struct.unpack("<QQQ", read_at(source, va, 24))
        validate_region(start, end, attrs)
        regions.append({"record_va": hex(va), "start": hex(start),
                        "end_exclusive": hex(end), "attributes": hex(attrs)})
        first = (start >> 21) & 0x7FFF
        last = ((end - 1) >> 21) & 0x7FFF
        if last < first:
            raise ValueError("original region wraps the 15-bit L2 index")
        for index in range(first, last + 1):
            store(memory, L2 + 8 * index,
                  (start + ((index - first) << 21)) | attrs)
    return bytes(memory), regions


def walk(memory, va, bits):
    if len(memory) != MEMORY_BYTES:
        raise ValueError("unexpected reconstructed memory extent")
    if bits not in (32, 36) or not 0 <= va < 1 << bits:
        raise ValueError("VA outside selected T0SZ range")
    root = ROOT32 if bits == 32 else ROOT36

    def load(pa):
        if pa & 7 or not L2 <= pa <= L2 + len(memory) - 8:
            raise ValueError("descriptor outside reconstructed memory/alignment")
        return struct.unpack_from("<Q", memory, pa - L2)[0]

    first_addr = root + 8 * (va >> 30)
    first = load(first_addr)
    result = {"va": hex(va), "va_bits": bits, "root_pa": hex(root),
              "l1_address": hex(first_addr), "l1_descriptor": hex(first)}
    if first & 3 != 3:
        return dict(result, status="l1_not_table_not_interpreted")
    second_addr = (first & 0xFFFFFFFFF000) + 8 * ((va >> 21) & 0x1FF)
    second = load(second_addr)
    result.update(l2_address=hex(second_addr), l2_descriptor=hex(second))
    if second & 3 != 1:
        return dict(result, status="unmapped_or_not_l2_block")
    pa = (second & 0xFFFFFFE00000) | (va & (BLOCK_BYTES - 1))
    return dict(result, status="mapped_l2_block", pa=hex(pa), identity=pa == va)


def require_identity(rows):
    if not rows or any(row.get("status") != "mapped_l2_block"
                       or row.get("identity") is not True for row in rows):
        raise ValueError("selected static walk is not an identity L2 block")


def runtime_layout(source):
    stack_top = struct.unpack('<Q', read_at(source, 0xFE049620, 8))[0]
    scatter = struct.unpack('<QQQQ', read_at(source, 0xFE05F5F8, 32))
    if stack_top != 0xFE160000 or scatter != (0xFE05FFE0, 0xFE05FFE0, 0x1B18, 0xFE04C678):
        raise ValueError('unexpected official stack or BSS initialization constants')
    return dict(stack_top_aff0_zero=hex(stack_top), stack_stride_per_aff0=hex(0x10000),
                stack_depth_verified=False, bss_start=hex(scatter[1]),
                bss_end_exclusive=hex(scatter[1] + scatter[2]), bss_clear_entry=hex(scatter[3]),
                physical_backing_verified=False)


def inspect(source):
    memory, regions = reconstruct(source)
    layout = runtime_layout(source)
    probes = (0xFE049000, 0xF102F000, 0x403E42000, 0x803E42000,
              0x800107F10, 0x804000000, 0xBFE0B0400, 0x03E42000)
    walks = [walk(memory, va, 36) for va in probes]
    initial = [walk(memory, va, 32) for va in (0xFE049000, 0xF102F000)]
    require_identity(walks)
    require_identity(initial)
    return {
        "schema": "a7c2-official-loader-page-tables-v4",
        "evidence_level": "static_reconstruction_only",
        "source_bytes": len(source), "source_sha256": hashlib.sha256(source).hexdigest(),
        "source_base": hex(BASE),
        "builder_sha256": hashlib.sha256(read_at(source, BUILDER_START, BUILDER_END - BUILDER_START)).hexdigest(),
        "region_table_sha256": hashlib.sha256(read_at(source, REGION_START, REGION_END - REGION_START)).hexdigest(),
        "table_memory_sha256": hashlib.sha256(memory).hexdigest(),
        "table_memory_extent": [hex(L2), hex(L2 + len(memory))],
        "regions": regions, "walks_36bit": walks, "walks_initial_32bit": initial,
        "runtime_layout": layout,
        "original_loader_executed": False,
        "physical_bus_alias_verified": False,
        "physical_compatible": False,
        "full_boot_verified": False,
        "bootrom_executed": False,
        "scope": "Static reconstruction; no original loader execution, physical bus alias, GPIO state or BootROM boot proved.",
        "unreviewed_l1_blocks": "Original non-table descriptors are retained verbatim, not interpreted as valid translations.",
    }


def read_archive(raw):
    if len(raw) != TAR_BYTES or hashlib.sha256(raw).hexdigest() != TAR_SHA:
        raise ValueError('unexpected official loader archive size/SHA256')
    files = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
            if archive.pax_headers:
                raise ValueError('unexpected official loader archive metadata')
            for member in archive:
                if (member.name not in TAR_MEMBERS or member.name in files or not member.isfile()
                        or member.pax_headers or member.issparse()):
                    raise ValueError('unexpected official loader archive member')
                size, expected = TAR_MEMBERS[member.name]
                if member.size != size:
                    raise ValueError('official loader archive member size differs')
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError('official loader archive member is unreadable')
                data = stream.read(size + 1)
                if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
                    raise ValueError('official loader archive member SHA256 differs')
                files[member.name] = data
    except (tarfile.TarError, EOFError) as error:
        raise ValueError('malformed official loader archive') from error
    if files.keys() != TAR_MEMBERS.keys():
        raise ValueError('official loader archive members are incomplete')
    return files['loader_nor.bin']


def read_loader(path):
    path = Path(path)
    if (not path.is_absolute() or str(path) != os.path.normpath(str(path)) or
            any(path == Path(root) or path.is_relative_to(root)
                for root in ("/tmp", "/var/tmp", "/dev", "/proc", "/sys", "/run")) or
            any(item.is_symlink() for item in (path, *path.parents))):
        raise ValueError("loader must be a canonical ordinary path outside host temporary and device roots")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("official loader input must be a regular file")
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_uid, s.st_nlink,
                          s.st_mtime_ns, s.st_ctime_ns)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOATIME
    with os.fdopen(os.open(path, flags), "rb") as stream:
        if identity(os.fstat(stream.fileno())) != identity(before):
            raise ValueError("official loader input changed while opening")
        source = stream.read(TAR_BYTES + 1)
        if identity(os.fstat(stream.fileno())) != identity(before) or identity(path.lstat()) != identity(before):
            raise ValueError("official loader input changed during read")
    if len(source) == TAR_BYTES:
        source = read_archive(source)
    validate_source(source)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("loader", type=Path, help="exact official loader_nor.bin or loader_nor.tar; no fabricated prefix")
    args = parser.parse_args()
    print(json.dumps(inspect(read_loader(args.loader)), indent=2))


if __name__ == "__main__":
    main()
