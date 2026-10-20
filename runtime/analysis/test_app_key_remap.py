"""Check raw injection codes against the original 2.01 constructor's mapping table."""
import hashlib
from pathlib import Path
import struct
import pytest
from menu_live import KEY_DEFINITIONS,key_definition,key_command,control_catalog

LIB=Path(__file__).resolve().parent/'menu-root/usr/lib/appFw.so'


@pytest.mark.skipif(not LIB.is_file(),reason='optional original firmware asset not installed')
def test_original_raw_to_canonical_mapping_and_role_bindings():
    raw=LIB.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    assert raw[:6]==b'\x7fELF\x02\x01'
    phoff=struct.unpack_from('<Q',raw,32)[0];size,count=struct.unpack_from('<HH',raw,54)
    assert size==56 and 0<count<=64
    segments=[struct.unpack_from('<IIQQQQQQ',raw,phoff+i*size) for i in range(count)]
    def at(address,length):
        for kind,flags,offset,va,pa,filesize,memsize,align in segments:
            if kind==1 and va<=address and address+length<=va+filesize:
                start=offset+address-va
                assert start+length<=len(raw)
                return raw[start:start+length]
        raise AssertionError('VA is not within a file-backed PT_LOAD')
    forward=list(struct.iter_unpack('<II',at(0x3704b98,0x2300)))
    reverse=list(struct.iter_unpack('<II',at(0x3706e98,0x2300)))
    assert len(forward)==1120 and reverse==[(value,key) for key,value in forward]
    assert struct.unpack('<4I',at(0x35a3a44,16))==(0xa9b97bfd,0x528028e1,0x72a01241,0x910003fd)
    assert struct.unpack('<4I',at(0x1b23e58,16))==(0xa9b77bfd,0x910003fd,0xa90153f3,0xaa0003f4)
    assert struct.unpack('<4I',at(0x20a0bc4,16))==(0xa9b97bfd,0x910003fd,0xa90153f3,0x910103b4)
    assert struct.unpack('<4I',at(0x23a7ae4,16))==(0xa9bc7bfd,0x12800000,0x910003fd,0xa90153f3)
    assert struct.unpack('<4I',at(0x20a073c,16))==struct.unpack('<4I',at(0x20a079c,16))==(0xa9bd7bfd,0x910003fd,0xa90153f3,0x9100a3b3)
    assert struct.unpack('<4I',at(0x33dccb8,16))==(0xa9ba7bfd,0x910003fd,0xa90153f3,0xaa0003f4)
    assert struct.unpack('<4I',at(0x33dcf50,16))==(0xa9ba7bfd,0x910003fd,0xf90013f5,0xaa0003f5)
    for slot,run,name in ((0x5b3acf0,0x33dccb8,b'N5model25sequence_power_off_cancelE'),
                          (0x5b3ad40,0x33dcf50,b'N5model17sequence_power_onE')):
        assert struct.unpack('<Q',at(slot,8))[0]==run
        rtti=struct.unpack('<Q',at(slot-0x18,8))[0]
        nameptr=struct.unpack('<Q',at(rtti+8,8))[0]
        assert at(nameptr,80).split(b'\0')[0]==name
    gate=struct.unpack('<4I',at(0x24d8728,16))
    assert gate==(0x340002d7,0xaa1603e2,0x2a1503e1,0xaa1403e0)
    assert gate[0]&0xff00001f==0x34000017
    displacement=(gate[0]>>5)&0x7ffff
    if displacement&(1<<18):displacement-=1<<19
    assert 0x24d8728+4*displacement==0x24d8780
    assert struct.unpack('<4I',at(0x24cba1c,16))==(0xa9be7bfd,0x910003fd,0xa90153f3,0xaa0003f3)
    assert at(0x24cce14,4)==bytes.fromhex('9f0a00f9')
    assert at(0x24ccaa8,4)==bytes.fromhex('60c25d39')
    assert struct.unpack('<Q',at(0x5578920+0x100*8,8))[0]==0x248db58
    assert struct.unpack('<Q',at(0x5b940d0,8))[0]==0x5b3acd0
    assert at(0x31106d4,4)==bytes.fromhex('60620039')  # original byte store, not padding/u32
    assert at(0x32425b8,4)==bytes.fromhex('f71b40f9')
    assert at(0x3222b64,4)==bytes.fromhex('000a00b5')
    assert at(0x3222b5c,4)==bytes.fromhex('600000b4')
    assert at(0x3222ad0,8)==bytes.fromhex('fd7bb7a9fd030091')
    assert at(0x3222c18,4)==bytes.fromhex('58000035')
    assert at(0x3222ac4,4)==bytes.fromhex('010800f9')
    assert at(0x33dcca0,4)==bytes.fromhex('f7ffff97')  # deleting dtor calls the observed non-deleting dtor
    assert at(0x3209dd8,4)==bytes.fromhex('d40a40f9')
    assert at(0x3209e08,4)==bytes.fromhex('744600f9')  # active=ctx+88, under ctx+28 mutex
    assert at(0x3209e44,4)==bytes.fromhex('20003fd6')
    assert at(0x3209e70,4)==bytes.fromhex('ed289697')  # same group mutex before dtor/clear
    assert at(0x3209ebc,4)==bytes.fromhex('20003fd6')
    assert at(0x3209ec0,4)==bytes.fromhex('7f4600f9')
    assert struct.unpack('<4I',at(0x17eb1a4,16))==(0xa9b97bfd,0x910003fd,0x39481001,0xa90153f3)
    assert at(0x17e9a10,8)==bytes.fromhex('00600791c0035fd6')
    assert at(0x17eb1c8,4)==bytes.fromhex('011442b9')
    call=struct.unpack('<4I',at(0x17eb5ac,16))
    assert call==(0x2a0003e1,0xaa1403e0,0x12800fe2,0x97f9ced2)
    assert call[3]&0xfc000000==0x94000000
    displacement=call[3]&0x3ffffff
    if displacement&(1<<25):displacement-=1<<26
    assert 0x17eb5b8+4*displacement==0x165f100
    assert struct.unpack('<Q',at(0x5afbc18,8))[0]==0x1d2f3d4
    nameptr=struct.unpack('<Q',at(0x5af6498,8))[0]
    assert at(nameptr,64).split(b'\0')[0]==b'22scr0132_0001_presenter'
    assert all(value&0xff000000==0x02000000 for value in struct.unpack('<18I',at(0x41b23a0,72)))
    mapping={}
    for key,value in forward:mapping.setdefault(key,value)
    # 179531c skips an existing node: the original initializer keeps the first duplicate.
    assert len(mapping)==1117 and mapping[0xa7]==0xf
    for code,target in {3:2,0x30:6,0x1ab:0x13,0x1ac:0x14,0x15:4,0x1af:0x16,0x1f8:0x23}.items():
        assert mapping[code]==target
    roles={'FN':0x8d,'REC':0x1c,'AF_ON':0x2d7,'PLAYBACK':0x22,'SHUTTER':0xf,
           'SHUTTER_HALF':0x1d,'C1':0xe,
           'FRONT_LEFT':0x2f5,'REAR_LEFT':0x2ef,'CONTROL_LEFT':0x2f6,'MODE':0x2a,
           'MODE_STILL':0x1c5,'MODE_MOVIE':0x1c5,'MODE_SQ':0x1c5}
    for name,target in roles.items():
        code=key_definition(name)['code']
        assert code is not None,name+' lacks its now-identified original raw code'
        assert mapping[int(code,0)]==target,name+' must send raw App32 code, not a canonical/business event'
    # Rows are addressed by ELF VA; their file offsets are 0x10000 lower.
    for row,expected,name in ((0x58c14e0,0xe,b'UIBIZ_KEY_TACT_CUSTOM\0'),
                               (0x58c15d0,0x1d,b'UIBIZ_KEY_TACT_LOCK\0')):
        value,length,pointer=struct.unpack('<IIQ',at(row,16))
        assert value==expected and length==len(name) and at(pointer,length)==name
    # Original wire conversion is independent of the order of a names-only array.
    target_values={1:0,3:1,5:2,4:3,6:4,7:5,19:6,20:7}
    for status,expected in target_values.items():
        substatus=status if status==1 else status-1 if status<=7 else 7 if status==19 else 8
        displacement=struct.unpack('<b',at(0x3787c50+substatus-1,1))[0]
        word=struct.unpack('<I',at(0x18940f0+4*displacement,4))[0]
        assert word&0xffe0001f==0x52800000 and (word>>5)&0xffff==expected
    name_descriptor=struct.unpack('<IIIi',at(0x50481e8,16))
    assert name_descriptor[:3]==(0,0x1c75,25)
    assert at(0x5063468+name_descriptor[3],80).split(b'\0')[0]==b'shoot_mode_dial_position'
    start,count,_,_,nvalues,table=struct.unpack('<IIQQQQ',at(0x5f0fa28,40))
    assert (start,count,nvalues,table)==(0x1c75,1,9,0x5878b90)
    declared={}
    for i in range(nvalues):
        value,length,ptr=struct.unpack('<IIQ',at(table+16*i,16))
        text=at(ptr,length)
        assert text.endswith(b'\0') and text.startswith(b'SHOOT_MODE_DIAL_')
        declared[text[:-1].decode().removeprefix('SHOOT_MODE_DIAL_')]=value
    assert {name:declared[name] for name in ('AUTO','P','A','S','M')}=={'AUTO':0,'P':1,'A':2,'S':3,'M':4}
    for label,status in KEY_DEFINITIONS['MODE']['positions'].items():
        assert target_values[status]==declared[label]
    # Original Still conversion preserves the five declared numeric modes.
    for value in range(5):
        displacement=struct.unpack('<b',at(0x4b60628+value,1))[0]
        word=struct.unpack('<I',at(0x2d4e808+4*displacement,4))[0]
        assert word&0xffe0001f==0x52800000 and (word>>5)&0xffff==value
    for index,(role,label) in enumerate((('MODE_STILL','STILL'),('MODE_MOVIE','MOVIE'),('MODE_SQ','S_AND_Q'))):
        assert int(KEY_DEFINITIONS[role]['status'])==index+1
        ptr=struct.unpack('<Q',at(0x5808660+8*index,8))[0]
        assert at(ptr,120).split(b'\0')[0].endswith(('SHOOT_MODE_SWITCH_'+label).encode())


def test_custom_half_and_full_input_routes_stay_distinct_and_unverified():
    import shlex
    catalog=control_catalog()
    for name,raw in (('C1','0x66'),('SHUTTER_HALF','0x1f1'),('SHUTTER','0xa7')):
        assert catalog[name]['available'] and not catalog[name]['verified']
        for app in (False,True):
            messages=[shlex.split(part.strip()) for part in key_command(name,app_input=app).split(';')
                      if part.strip().startswith('/simulation/inject-key ')]
            assert len(messages)==2
            route=['--app','0x005503e0','0x005503e0'] if app else ['0x807a0020','0x92840747']
            for message,status in zip(messages,('1','0')):
                assert message==['/simulation/inject-key',*route,raw,'0',status,'0','0' if app else '1']
    # No unsupported exposure operation is silently bound to a generic direction.
    assert not catalog['EXPOSURE_COMP']['available']
