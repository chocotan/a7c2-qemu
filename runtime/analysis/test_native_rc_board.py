"""Exercise all GPEX swizzles and reject unknown maps before changing the DTB."""
import ctypes
import struct
import os
import subprocess
import hashlib
import pytest

from native_rc_board import configure,require_binary,reserve_sa_irq
from test_native_smp import board,prop,HERE


def test_rc_gpex_all_sixteen_swizzles_and_other_properties_preserved():
    fdt,buffer=board()
    path=b'/pcie@10000000'
    original=prop(fdt,buffer,path,b'interrupt-map')
    preserved={key:prop(fdt,buffer,path,key) for key in (b'reg',b'interrupt-map-mask',b'ranges')}
    configure(fdt,buffer)
    mapped=struct.unpack('>160I',prop(fdt,buffer,path,b'interrupt-map'))
    old=struct.unpack('>160I',original)
    for start in range(0,160,10):
        slot,pin=mapped[start]>>11,mapped[start+3]
        assert mapped[start+8]==244+(slot+pin-1)%4
        assert mapped[start:start+8]==old[start:start+8] and mapped[start+9]==old[start+9]
    for key,value in preserved.items():
        assert prop(fdt,buffer,path,key)==value
    with pytest.raises(ValueError):configure(fdt,buffer)


@pytest.mark.parametrize('fault',['short','parent','irq','pin','duplicate'])
def test_rc_gpex_invalid_map_does_not_mutate(fault):
    fdt,buffer=board();path=b'/pcie@10000000'
    raw=bytearray(prop(fdt,buffer,path,b'interrupt-map'))
    if fault=='short':raw=raw[:-4]
    elif fault=='duplicate':raw[40:80]=raw[:40]
    else:
        cell={'parent':4,'irq':8,'pin':3}[fault]
        struct.pack_into('>I',raw,cell*4,99)
    raw=bytes(raw)
    assert fdt.fdt_setprop(buffer,fdt.fdt_path_offset(buffer,path),b'interrupt-map',raw,len(raw))==0
    original=buffer.raw
    with pytest.raises(ValueError):configure(fdt,buffer)
    assert buffer.raw==original


def test_launcher_remaps_only_selected_matched_board(tmp_path):
    initrd=tmp_path/'test.cpio';initrd.write_bytes(b'070701')
    output=tmp_path/'prepared'
    env={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','A7C2_','QEMU_','SONY_'))}
    env.update(QEMU_PREPARE_ONLY='1',QEMU_CPU_COUNT='2',QEMU_OUTPUT_DIR=str(output),QEMU_SONY_PCIDMA='1')
    command=['bash',str(HERE/'qemu-kernel-probe.sh'),'4096',
             str(HERE/'qemu-virt-board/virt-pcidma.dtb'),'1','1',str(initrd)]
    for enabled,base in (('0',3),('1',244)):
        env['QEMU_SONY_RC']=enabled
        subprocess.run(command,env=env,check=True,capture_output=True,timeout=20)
        fdt,_=board();buffer=ctypes.create_string_buffer((output/'virt.dtb').read_bytes())
        mapped=struct.unpack('>160I',prop(fdt,buffer,b'/pcie@10000000',b'interrupt-map'))
        assert set(mapped[8::10])==set(range(base,base+4))
        assert prop(fdt,buffer,b'/cpus/cpu@1',b'enable-method')==b'psci\0'
        if enabled=='1':
            assert prop(fdt,buffer,b'/sony-f280-control',b'phys')==struct.pack('>Q',0xf2800000)
            assert prop(fdt,buffer,b'/sony-f280-control',b'virt')==struct.pack('>Q',0xfffffffff2800000)
            assert prop(fdt,buffer,b'/sony-f280-control',b'size')==struct.pack('>Q',0x1000)
        else:assert fdt.fdt_path_offset(buffer,b'/sony-f280-control')<0
    env['QEMU_CPU_COUNT']='1'
    rejected=subprocess.run(command,env=env,capture_output=True,timeout=20)
    assert rejected.returncode==2 and b'requires matched SMP2' in rejected.stderr


def test_completion_mode_rejects_data_only_conflict_before_startup():
    env={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','A7C2_','QEMU_','SONY_'))}
    env.update(QEMU_CPU_COUNT='2',QEMU_SONY_PCIDMA='1',QEMU_SONY_RC='1',
        QEMU_SONY_SA_DATA_ONLY='1',QEMU_SONY_SA_REFERENCE_COMPLETE='1')
    result=subprocess.run(['bash',str(HERE/'qemu-kernel-probe.sh')],env=env,capture_output=True,timeout=10)
    assert result.returncode==2 and b'excludes data-only' in result.stderr


def test_old_binary_cannot_use_relocated_fixed_dtb(tmp_path):
    binary=tmp_path/'qemu-system-aarch64'
    binary.write_bytes(b'old QEMU_SONY_RC name alone is not the board capability')
    with pytest.raises(ValueError,match='rebuild'):require_binary(binary)
    binary.write_bytes(b'ELF\0SONY_RC_BOARD_V2 gpex_spi_base=244\n')
    require_binary(binary)
    with pytest.raises(ValueError,match='data backend'):require_binary(binary,reference=True)
    binary.write_bytes(binary.read_bytes()+b'SONY_RC_REFERENCE_V1 packing=unverified engines=B,C\0')
    require_binary(binary,reference=True)
    with pytest.raises(ValueError,match='handoff'):require_binary(binary,handoff=True)
    binary.write_bytes(binary.read_bytes()+b'SONY_GIC_HANDOFF_V1 spi-default=cpu0\0')
    require_binary(binary,reference=True,handoff=True)
    with pytest.raises(ValueError,match='data-only'):require_binary(binary,sa_data=True)
    binary.write_bytes(binary.read_bytes()+b'SONY_SA_DATA_ONLY_V1 no-completion-irq\0')
    require_binary(binary,reference=True,sa_data=True)
    with pytest.raises(ValueError,match='completion'):require_binary(binary,sa_complete=True)
    binary.write_bytes(binary.read_bytes()+b'SONY_SA_REFERENCE_COMPLETE_V1 virtual-group0-bit0\0')
    require_binary(binary,sa_complete=True)


def test_completion_profile_reserves_irq48_without_modifying_neighbor():
    fdt,buffer=board()
    neighboring=prop(fdt,buffer,b'/virtio_mmio@a000200',b'interrupts')
    reserve_sa_irq(fdt,buffer)
    assert prop(fdt,buffer,b'/virtio_mmio@a000000',b'status')==b'disabled\0'
    assert prop(fdt,buffer,b'/virtio_mmio@a000200',b'interrupts')==neighboring


def test_original_packed_config_tables_fit_exact_backed_page():
    image=HERE/'menu-root/system/av-cam.bin'
    if not image.exists():pytest.skip('Original firmware is not distributed')
    raw=image.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
    for start in (0xbd9f38,0xbda1e8):
        words=struct.unpack_from('<86Q',raw,start)
        assert all(0xfffffffff2800000<=word<=0xfffffffff2800ffc and word%4==0 for word in words)
    assert struct.unpack_from('<Q',raw,0xbda0b0)[0]==0xfffffffff28004a0
    assert struct.unpack_from('<Q',raw,0xbda1e8+47*8)[0]==0xfffffffff2800520
    assert struct.unpack_from('<I',raw,0x20df90)[0]==0xb9400109
    assert struct.unpack_from('<2I',raw,0x20e024)==(0xb9000109,0xb9400108)


def test_gpex_range_avoids_observed_original_sa_registrations():
    image=HERE/'menu-root/system/av-cam.bin'
    if not image.exists():pytest.skip('Original firmware is not distributed')
    raw=image.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
    kernel=0xffffffc001000000
    # Bounded archived registration window, not a whole-binary absence claim.
    records=[]
    for offset in range(0xbd6d38,0xbd8d38,0x20):
        irq=struct.unpack_from('<I',raw,offset)[0]
        handler,cpu=struct.unpack_from('<QI',raw,offset+16)
        if kernel<=handler<kernel+len(raw) and cpu<4 and irq<1024:records.append(irq)
    assert len(records)==58 and max(records)==265
    assert set(range(44,54))<=set(records)
    assert not set(range(276,280))&set(records)
