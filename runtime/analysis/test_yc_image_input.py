import hashlib
from pathlib import Path

import pytest
from PIL import Image

from yc_image_input import HEIGHT, WIDTH, prepare


def test_png_prepares_exact_luma_bytes(tmp_path: Path):
    source, target = tmp_path / 'picture.png', tmp_path / 'frame.gray'
    Image.new('RGB', (16, 9), (255, 0, 0)).save(source)
    digest = prepare(source, target)
    pixels = target.read_bytes()
    assert len(pixels) == WIDTH * HEIGHT
    assert set(pixels) == {76}  # Pillow's red→luma conversion
    assert hashlib.sha256(pixels).hexdigest() == digest


def test_three_to_two_photo_keeps_aspect_and_full_content(tmp_path: Path):
    source, target = tmp_path / 'still.png', tmp_path / 'frame.gray'
    Image.new('RGB', (12, 8), (255, 0, 0)).save(source)
    prepare(source, target)
    pixels = target.read_bytes()
    center = HEIGHT // 2 * WIDTH
    assert pixels[center:center + 150] == bytes(150)
    assert pixels[center + 150:center + 1770] == bytes([76]) * 1620
    assert pixels[center + 1770:center + WIDTH] == bytes(150)
    assert pixels[0:WIDTH] == bytes(150) + bytes([76]) * 1620 + bytes(150)


def test_wrong_format_rejected_without_output(tmp_path: Path):
    source, target = tmp_path / 'picture.jpg', tmp_path / 'frame.gray'
    Image.new('RGB', (8, 8), (255, 0, 0)).save(source)
    with pytest.raises(ValueError, match='PNG'):
        prepare(source, target)
    assert not target.exists()


def test_neutral_source_requires_bytes_consumption_and_uncompressed_format(tmp_path):
    import json
    from yc_image_input import uncompressed_proof
    raw=bytes([128])*(WIDTH*HEIGHT*5//2)
    value=0xcbf29ce484222325
    for byte in raw:value=((value^byte)*0x100000001b3)&0xffffffffffffffff
    console=('YCIN_UNCOMPRESSED: bytes=5184000 fnv64=%016x\n'%value)*3
    console+='YCIN_INIT_DONE: 3 frames queued\nYCIN_DMM: type=0x431 handle=0x415 addr=0x428000000 len=0x500000\n'
    console+="insmod /simulation/yc_inject.ko && echo YC_INJECT_MOD_OK || echo YC_INJECT_MOD_FAIL\n"
    path=tmp_path/'yc-pixel-readback.bin';path.write_bytes(raw)
    copies=[]
    for frame,meta in enumerate((0x416,0x417,0x418)):
        console+=f'YCIN_DMM: type=0xe0b00 handle={meta:#x} addr=0x424001000 len=0xf80\n'
        console+=f'YCIN_SEND: 1000:0102 frame={frame} meta={meta:#x} pix=0x415 rc=0\n'
        console+=f'YCIN_VDT_REPLY: OUT1 frame delivery, meta h={meta:#x}\n'
        copies.append(f'[VDT][RDIMG    ]: flow[1]CMP(0x1)in_pin(h:{meta:#x} a:0x424001000)'
                      f'image(h:0x415 a:0x428000000)->out_pin(h:{meta:#x})'
                      'image(h:0x415 a:0x428000000  type:0x487 size=5184000) diff=0')
    (tmp_path/'menu-ulogio.bin').write_bytes('\0'.join(copies).encode())
    (tmp_path/'yc-pixel-readback.json').write_text(json.dumps(dict(unit_type=0x431,handle=0x415,
        physical_address=0x428000000,bytes=len(raw))))
    p=bytearray(0x1b4)
    import struct
    struct.pack_into('<2H',p,0x58,WIDTH,HEIGHT)
    struct.pack_into('<2H',p,0xe0,WIDTH,HEIGHT)
    struct.pack_into('<Q',p,0x18,0x428000000)
    struct.pack_into('<I',p,0x20,0x500000)
    event=dict(kind='resize_enable_gate',original_entry_verified=True,parameter_hex=p.hex(),setup_status=0,enable_mode=1)
    events=tmp_path/'resize-watch-events.jsonl';events.write_text(json.dumps(event)+'\n')
    result=uncompressed_proof(tmp_path,console)
    assert result['verified'] and result['full_byte_readback_verified']
    assert not result['pixel_processing_verified'] and not result['completion_verified']
    assert result['same_format_and_canvas_observed']
    struct.pack_into('<2H',p,0xe0,1280,720)
    event['parameter_hex']=p.hex();events.write_text(json.dumps(event)+'\n')
    scaled=uncompressed_proof(tmp_path,console)
    assert scaled['verified'] and not scaled['same_format_and_canvas_observed']
    p[0x84]=1;event['parameter_hex']=p.hex();events.write_text(json.dumps(event)+'\n')
    assert not uncompressed_proof(tmp_path,console)['verified']
    p[0x84]=0;event['parameter_hex']=p.hex();events.write_text(json.dumps(event)+'\n')
    path.write_bytes(raw[:-1]+b'\0')
    assert not uncompressed_proof(tmp_path,console)['verified']
    path.write_bytes(raw)
    assert not uncompressed_proof(tmp_path,console+'YCIN_INIT_FAILED: rc=-1\n')['verified']
    initcall=console.replace('YCIN_INIT_DONE: 3 frames queued',
        'initcall init_module+0x0/0x1000 [yc_inject] returned 0 after 100 usecs')
    assert uncompressed_proof(tmp_path,initcall)['verified']
    assert not uncompressed_proof(tmp_path,initcall+'\nYCIN_INIT_FAILED: rc=-1\n')['verified']
    event['setup_status']=1;events.write_text(json.dumps(event)+'\n')
    assert not uncompressed_proof(tmp_path,console)['verified']
    event['setup_status']=0;struct.pack_into('<Q',p,0x18,0x429000000)
    event['parameter_hex']=p.hex();events.write_text(json.dumps(event)+'\n')
    assert not uncompressed_proof(tmp_path,console)['verified']
    struct.pack_into('<Q',p,0x18,0x428000000)
    event['parameter_hex']=p.hex();events.write_text(json.dumps(event)+'\n')
    assert not uncompressed_proof(tmp_path,console.replace('type=0x431','type=0x644'))['verified']
    assert not uncompressed_proof(tmp_path,console.replace('pix=0x415','pix=0x499'))['verified']
    (tmp_path/'menu-ulogio.bin').write_bytes('\0'.join(copies).replace('a:0x428000000','a:0x429000000').encode())
    assert not uncompressed_proof(tmp_path,console)['verified']
