import copy
import struct
from pathlib import Path
import hashlib

import pytest

from rc_dma_evidence import correlate
from resize_mmio_watch import KERNEL_BASE, KERNEL_SHA


def fixture():
    base=0xf30b0000
    context=KERNEL_BASE+0xb1ffb0
    p=bytearray(0x1b4)
    struct.pack_into('<Q',p,0x18,0x4287aa000)
    struct.pack_into('<Q',p,0xa0,0x4f8500000)
    struct.pack_into('<I',p,0x84,1)
    struct.pack_into('<I',p,0x178,1)
    events=[dict(kind='resize_submit',original_entry_verified=True,
                 input_address=0x4287aa000,output_address=0x4f8500000,
                 input_geometry=[1920,1080],output_geometry=[1280,720],
                 input_bytes=0x200000,output_bytes=0x1518000),
            dict(kind='resize_enable_gate',original_entry_verified=True,setup_status=0,
                 enable_mode=1,context_pointer=hex(context),parameter_hex=p.hex()),
            dict(kind='resize_mmio_enable',original_entry_verified=True,
                 bank0_physical=base,bank1_physical=base+0x2000,expected_context=context)]
    regs={base+0x1008:0xff,base+0x2028:1920<<16|1080,base+0x202c:1280<<16|720}
    for ch,pa,row,rows in ((0x1200,0x287aa000,1920,1080),(0x1280,0xf8500000,2560,720)):
        regs.update({base+ch:3,base+ch+0x18:0,base+ch+0x20:pa,
                     base+ch+0x24:row,base+ch+0x28:0,base+ch+0x2c:rows-1,
                     base+ch+0x30:0,base+ch+0x34:0})
    regs[base+0x2000]=1
    console='\n'.join(f'REGFILE_WR {address:#x} = {value:#x}' for address,value in regs.items())
    return events,console


def test_correlates_real_start_without_claiming_pixels():
    events,console=fixture()
    result=correlate(events,console)
    assert result['rc_enable_and_dma_configuration_verified']
    assert result['pixel_processing_verified'] is result['completion_verified'] is False
    assert result['operations'][0]['channels']['output']['rectangle_bytes']==1843200


def test_reference_model_trace_does_not_imply_pixel_fidelity():
    events,console=fixture()
    result=correlate(events,console.replace('REGFILE_WR','SONY_RC_MMIO_WR'))
    assert result['rc_enable_and_dma_configuration_verified']
    assert not result['operations'][0]['identity_operation_verified']
    assert not result['pixel_processing_verified'] and not result['completion_verified']


def test_uncompressed_row_contract_is_not_pixel_or_identity_proof():
    events,console=fixture()
    p=bytearray.fromhex(events[1]['parameter_hex'])
    struct.pack_into('<I',p,0x84,0)
    events[1]['parameter_hex']=p.hex()
    events[0]['input_bytes']=0x400000
    events[0]['output_geometry']=[1920,1080]
    for address,value in ((0xf30b202c,0x7800438),(0xf30b1224,0xf00),
                          (0xf30b12a4,0xf00),(0xf30b12ac,0x437)):
        lines=console.splitlines()
        console='\n'.join(f'REGFILE_WR {address:#x} = {value:#x}'
                          if line.startswith(f'REGFILE_WR {address:#x} = ') else line
                          for line in lines)
    result=correlate(events,console)
    operation=result['operations'][0]
    assert operation['channels']['input']['rectangle_bytes']==4147200
    assert operation['same_format_and_canvas_observed']
    assert not operation['identity_operation_verified'] and not result['pixel_processing_verified']
    with pytest.raises(ValueError):correlate(events,console.replace('0xf00','0x780',1))


def test_dma_bus_mapping_and_pixel_bit_width_tables_match_original():
    image=Path(__file__).with_name('menu-root')/'system/av-cam.bin'
    if not image.exists():pytest.skip('Original firmware is not distributed')
    raw=image.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==KERNEL_SHA
    assert struct.unpack_from('<4Q',raw,0x3320d8)==(0x400000000,0,0,0x100000000)
    assert struct.unpack_from('<4Q',raw,0x3320f8)==(0x500000000,0,0x100000000,0x100000000)
    assert struct.unpack_from('<4I',raw,0x3ef2d4)==(8,10,12,16)
    assert struct.unpack_from('<2Q',raw,0x387ca8)==(KERNEL_BASE+0x2cd4dc,KERNEL_BASE+0x2cd4ac)
    assert struct.unpack_from('<2Q',raw,0x387e58)==(KERNEL_BASE+0x2cdf44,KERNEL_BASE+0x2cdf14)
    for index,handler in enumerate((0x2c89f0,0x2c8a90,0x2c8b38,0x2c8be0,0x2c8c88,0x2c8d30)):
        assert struct.unpack_from('<4Q',raw,0xbd7298+index*0x20)==(34+index,0,KERNEL_BASE+handler,1)
    for offset,word in ((0x2d910c,0x121f0ac8),(0x2d919c,0x121f0a88),(0x20d958,0xb9000109)):
        assert struct.unpack_from('<I',raw,offset)[0]==word


@pytest.mark.parametrize('fault',['missing_write','wrong_address','bad_pitch','short_capacity','bad_gate','no_entry','format','extra_write'])
def test_refuses_unmatched_or_unsupported_evidence(fault):
    events,console=fixture();events=copy.deepcopy(events)
    if fault=='missing_write':console=console.rsplit('\n',1)[0]
    elif fault=='wrong_address':console=console.replace('0x287aa000','0x287ab000')
    elif fault=='bad_pitch':console=console.replace('0xa00','0x500')
    elif fault=='short_capacity':events[0]['input_bytes']=1
    elif fault=='bad_gate':events[1]['setup_status']=3
    elif fault=='no_entry':events.pop()
    elif fault=='format':
        p=bytearray.fromhex(events[1]['parameter_hex']);struct.pack_into('<I',p,0x84,8)
        events[1]['parameter_hex']=p.hex()
    else:console+='\nREGFILE_WR 0xf30c2000 = 0x1'
    with pytest.raises(ValueError):correlate(events,console)
