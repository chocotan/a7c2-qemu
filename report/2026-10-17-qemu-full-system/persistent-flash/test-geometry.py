import copy
import json
from pathlib import Path
import runpy
import struct
import pytest

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'geometry.py'))
ROOT=next(p for p in HERE.parents if (p/'analysis/output/system-dump/manifest.json').is_file())
PARTINF=ROOT/'analysis/extracted/firmware/0300_partconf/partinf.conf'
CAPS=ROOT/'analysis/evidence/usb-service/run-20261016-021412-331831/block-devices.json'
MOUNTS=ROOT/'analysis/extracted/firmware/0100_config/mount.conf'
MANIFEST=ROOT/'analysis/output/system-dump/manifest.json'


def geometry():
    return API['from_evidence'](PARTINF,CAPS,MOUNTS,MANIFEST)


def parent_geometry():
    raw=[l.strip() for l in PARTINF.read_bytes().splitlines() if l.strip() and not l.lstrip().startswith(b'#')]
    rows=[]
    for i,line in enumerate(raw):
        start,size,kind,flags=(int(v,16) for v in line.split(b','))
        rows.append(dict(part=i+1,start_lba=start,sectors=size,type=kind,flags=flags,offset=start*512,bytes=size*512))
    user=max(r['offset']+r['bytes'] for r in rows)
    slices=[dict(id='nflasha'+str(r['part']),area='user',offset=r['offset'],bytes=r['bytes'],
                 source=API['image_name'](r['part']),source_sha256='1'*64) for r in rows if r['bytes']]
    slices += [dict(id=f'nflashaB{i}',area=f'boot{i}',offset=user+i*4194304,bytes=4194304,
                    source=f'nflashaB{i}.img',source_sha256='2'*64) for i in (0,1)]
    return dict(schema='a7c2-persistent-emmc-v1',sector_bytes=512,user_bytes=user,
                backing_bytes=user+8388608,partition_rows=rows,slices=slices)


def test_original_geometry_and_source_hashes(tmp_path):
    paths=[PARTINF,CAPS,MOUNTS,MANIFEST]
    before=[API['sha256'](p) for p in paths]
    g=geometry();assert g['capacity_bytes']==1954545664
    assert len(g['partitions'])==17
    assert [p['number'] for p in g['partitions']]==list(API['PARTS'])
    assert g['partitions'][0]['offset_bytes']==65536
    assert g['partitions'][-1]['offset_bytes']+g['partitions'][-1]['length_bytes']==1922039808
    assert next(p for p in g['partitions'] if p['number']==7)['image_name']=='a7c2-rootfs.img'
    assert next(p for p in g['partitions'] if p['number']==15)['image_name']=='a7c2-usr.img'
    wire=tmp_path/'geometry.bin';API['write_wire'](g,wire)
    header=struct.unpack_from('<8sIIQ',wire.read_bytes());assert header==(b'A7PFGE01',1,19,1954545664)
    assert len(wire.read_bytes())==480
    assert [API['sha256'](p) for p in paths]==before


@pytest.mark.parametrize('problem',['overlap','capacity','missing','boot','alias'])
def test_geometry_rejects_inexact_evidence(problem):
    g=geometry()
    if problem=='overlap':g['partitions'][1]['offset_bytes']=0
    if problem=='capacity':g['capacity_bytes']-=512
    if problem=='missing':g['partitions'].pop()
    if problem=='boot':g['boot_areas'][0]['offset_bytes']=0
    if problem=='alias':g['partitions'][6]['image_name']='nflasha7.img'
    with pytest.raises(ValueError):API['validate'](g)


def test_capacity_record_required(tmp_path):
    caps=json.loads(CAPS.read_text());del caps['block_devices_bytes']['pnflasha']
    p=tmp_path/'caps.json';p.write_text(json.dumps(caps))
    with pytest.raises(ValueError):API['from_evidence'](PARTINF,p,MOUNTS,MANIFEST)


def test_parent_single_container(tmp_path):
    g=parent_geometry();wire=tmp_path/'geometry.bin';API['write_camera_wire'](g,wire)
    data=wire.read_bytes();assert struct.unpack_from('<8sIIQ',data)==(b'A7PFGE01',1,19,1922039808)
    assert struct.unpack_from('<IIQQ',data,24+17*24)==(31,0,1922039808,4194304)
    assert struct.unpack_from('<IIQQ',data,24+18*24)==(32,0,1926234112,4194304)


@pytest.mark.parametrize('problem',['offset','length','alias','area','capacity','missing'])
def test_parent_geometry_rejects_bad_slices(tmp_path,problem):
    g=parent_geometry()
    if problem=='offset':g['slices'][0]['offset']+=512
    if problem=='length':g['slices'][0]['bytes']+=512
    if problem=='alias':g['slices'][6]['source']='nflasha7.img'
    if problem=='area':g['slices'][-1]['area']='user'
    if problem=='capacity':g['user_bytes']-=512
    if problem=='missing':g['slices'].pop()
    with pytest.raises(ValueError):API['write_camera_wire'](g,tmp_path/'geometry.bin')
