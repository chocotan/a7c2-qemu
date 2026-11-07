#!/usr/bin/env python3
"""Read-only geometry preflight and exact binary geometry for the functional device."""
import hashlib
import json
import re
import stat
import struct
from pathlib import Path

SCHEMA = 'a7c2.persistent-flash.geometry.v1'
PARTS = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 15, 18, 22, 23, 30)
CAPACITY = 1954545664
BOOT_BYTES = 4194304


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def image_name(number):
    return {7: 'a7c2-rootfs.img', 15: 'a7c2-usr.img'}.get(number, f'nflasha{number}.img')


def validate(g):
    if g.get('schema') != SCHEMA or g.get('sector_size') != 512:
        raise ValueError('Unsupported persistent geometry schema/sector size')
    if type(g.get('capacity_bytes')) is not int or g['capacity_bytes'] != CAPACITY:
        raise ValueError('Exact ILCE-7CM2 whole-device capacity is required')
    parts = g.get('partitions', [])
    if [p.get('number') for p in parts] != list(PARTS):
        raise ValueError('Expected all 17 original nonempty partition numbers in order')
    end = 0
    for p in parts:
        off, length = p.get('offset_bytes'), p.get('length_bytes')
        if (type(off) is not int or type(length) is not int or off % 512 or length % 512
                or length <= 0 or off < end or off + length > g['capacity_bytes']
                or p.get('image_name') != image_name(p['number'])):
            raise ValueError('Invalid, overlapping or mislabeled partition slice')
        end = off + length
    if g.get('container_bytes') != CAPACITY + 2 * BOOT_BYTES:
        raise ValueError('Container must hold user area plus two separate boot slices')
    if g.get('boot_areas') != [dict(id=f'B{i}', selector=31+i, offset_bytes=CAPACITY+i*BOOT_BYTES,
                                  capacity_bytes=BOOT_BYTES, separate_address_space=True,
                                  image_name=f'nflashaB{i}.img') for i in (0, 1)]:
        raise ValueError('B0/B1 must remain independent eMMC boot address spaces')
    if g.get('adapter') != 'project-slice-table-v1' or g.get('physical_compatibility') is not False:
        raise ValueError('Functional adapter and unverified physical compatibility must be explicit')
    return g


def from_evidence(partinf, capacity_record, mount_layout, image_manifest):
    """No guessed capacity, concatenation order or inferred boot-area offsets."""
    partinf, capacity_record, mount_layout, image_manifest = map(Path,
        (partinf, capacity_record, mount_layout, image_manifest))
    raw = partinf.read_bytes().decode('ascii', errors='replace')
    expected = None
    rows = {}
    for line in raw.splitlines():
        match = re.match(r'\s*#\s*/dev/nflasha(\d+)\b', line)
        if match:
            if expected is not None:
                raise ValueError('Partition comment without a numeric row')
            expected = int(match[1])
        elif line.strip() and not line.lstrip().startswith('#'):
            m = re.fullmatch(r'\s*(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+),(0x[0-9A-Fa-f]+)\s*', line)
            if not m or expected is None or expected in rows:
                raise ValueError('Unrecognized or duplicate Sony partinf row')
            off, length, kind, flags = (int(x, 16) for x in m.groups())
            if length and flags != 0xffffffff:
                raise ValueError('Unsupported active Sony partition flags')
            rows[expected] = (off * 512, length * 512)
            expected = None
    if expected is not None or sorted(rows) != list(range(1, 31)):
        raise ValueError('Incomplete original 30-row partinf evidence')
    caps = json.loads(capacity_record.read_text())['block_devices_bytes']
    if caps.get('pnflasha') != CAPACITY or any(caps.get(f'nflashaB{i}') != BOOT_BYTES for i in (0, 1)):
        raise ValueError('Exact original whole-device / boot capacity evidence missing')
    mounts = {}
    for line in mount_layout.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        dev, mount, fs, size, cluster = line.split()
        n = int(dev.removeprefix('/dev/nflasha'))
        if n in mounts:
            raise ValueError('Duplicate mount geometry')
        mounts[n] = int(size)
    images = json.loads(image_manifest.read_text())['images']
    by_name = {r['name']: r for r in images}
    names = {image_name(n) for n in PARTS} | {'nflashaB0.img', 'nflashaB1.img'}
    if len(images) != 19 or set(by_name) != names:
        raise ValueError('Expected exact complete 19-image manifest including semantic p7/p15 names')
    partitions = []
    for n, (off, size) in sorted(rows.items()):
        if not size:
            continue
        if mounts.get(n) != size or caps.get(f'pnflasha{n}') != size or by_name[image_name(n)]['bytes'] != size:
            raise ValueError(f'Partition {n} evidence disagrees between partinf/mount/capacity/manifest')
        partitions.append(dict(number=n, offset_bytes=off, length_bytes=size, image_name=image_name(n)))
    for i in (0, 1):
        if by_name[f'nflashaB{i}.img']['bytes'] != BOOT_BYTES:
            raise ValueError('Boot area image size mismatch')
    return validate(dict(schema=SCHEMA, sector_size=512, capacity_bytes=CAPACITY,
        partitions=partitions, reserved_partitions=[n for n, (_, size) in rows.items() if not size],
        container_bytes=CAPACITY+2*BOOT_BYTES, container_kind='logical-functional-container',
        boot_areas=[dict(id=f'B{i}', selector=31+i, offset_bytes=CAPACITY+i*BOOT_BYTES,
                        capacity_bytes=BOOT_BYTES, separate_address_space=True,
                        image_name=f'nflashaB{i}.img') for i in (0, 1)],
        evidence={name:sha256(p) for name,p in [('partinf',partinf),('capacity_record',capacity_record),
                   ('mount_layout',mount_layout),('image_manifest',image_manifest)]},
        adapter='project-slice-table-v1', physical_compatibility=False,
        main_disk_prefix='virtual zero gap; no original encrypted partition header claimed'))


def write_camera_wire(camera, path):
    """Convert parent's leased a7c2-persistent-emmc-v1 geometry, no image writes."""
    if camera.get('schema') != 'a7c2-persistent-emmc-v1' or camera.get('sector_bytes') != 512:
        raise ValueError('Unknown parent camera disk schema')
    rows = camera.get('partition_rows', [])
    slices = camera.get('slices', [])
    if len(rows) != 30 or [r.get('part') for r in rows] != list(range(1,31)):
        raise ValueError('Expected original complete partition table')
    if [r['part'] for r in rows if r['bytes']] != list(PARTS):
        raise ValueError('Nonempty partition set differs')
    user = camera.get('user_bytes')
    extent = max(r['offset']+r['bytes'] for r in rows)
    if extent != 1922039808 or user not in (extent, CAPACITY):
        raise ValueError('Unknown user extent/capacity; refuse guessed geometry')
    if camera.get('backing_bytes') != user+2*BOOT_BYTES or len(slices) != 19:
        raise ValueError('Expected user+boot0+boot1 single container')
    expected = []
    end = 512
    for r in rows:
        if (type(r['offset']) is not int or type(r['bytes']) is not int or r['offset'] != r['start_lba']*512
                or r['bytes'] != r['sectors']*512 or r['offset'] < end or r['offset']+r['bytes'] > user):
            raise ValueError('Invalid original partition bounds')
        if r['bytes']:
            expected.append((f'nflasha{r["part"]}', 'user', r['offset'], r['bytes'], image_name(r['part']), r['part']))
            end = r['offset']+r['bytes']
    for i in (0,1):
        expected.append((f'nflashaB{i}',f'boot{i}',user+i*BOOT_BYTES,BOOT_BYTES,f'nflashaB{i}.img',31+i))
    wire = struct.pack('<8sIIQ', b'A7PFGE01',1,len(expected),user)
    for sl, (sid,area,off,size,source,selector) in zip(slices,expected):
        if (sl.get('id'),sl.get('area'),sl.get('offset'),sl.get('bytes'),sl.get('source')) != (sid,area,off,size,source):
            raise ValueError('Slice alias/source geometry mismatch')
        if not re.fullmatch(r'[0-9a-f]{64}',sl.get('source_sha256','')):
            raise ValueError('Missing source identity')
        wire += struct.pack('<IIQQ',selector,0,off,size)
    with Path(path).open('xb') as f:
        f.write(wire)
    Path(path).chmod(0o600)
    return sha256(path)


def write_wire(g, path):
    validate(g)
    wire = struct.pack('<8sIIQ', b'A7PFGE01', 1, len(g['partitions'])+2, g['capacity_bytes'])
    for p in g['partitions']:
        wire += struct.pack('<IIQQ', p['number'], 0, p['offset_bytes'], p['length_bytes'])
    for p in g['boot_areas']:
        wire += struct.pack('<IIQQ', p['selector'], 0, p['offset_bytes'], p['capacity_bytes'])
    with Path(path).open('xb') as f:
        f.write(wire)
    Path(path).chmod(stat.S_IRUSR | stat.S_IWUSR)
    return sha256(path)
