"""Exact logical wire for the product-owned single virtual eMMC container."""
import hashlib
import re
import struct
from pathlib import Path
PARTS=(1,2,3,4,5,6,7,8,10,11,12,13,15,18,22,23,30)
CAPACITY=1954545664
BOOT_BYTES=4194304
def image_name(number):
    return {7:'a7c2-rootfs.img',15:'a7c2-usr.img'}.get(number,'nflasha'+str(number)+'.img')
def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

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
