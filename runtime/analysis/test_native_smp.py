"""Exercise real libfdt changes; no guest execution or synthetic interrupt."""
import ctypes
from pathlib import Path
import struct
import os
import subprocess
import json

import pytest
from native_smp import configure,proof

HERE = Path(__file__).resolve().parent


def board():
    fdt=ctypes.CDLL(str(HERE/'../sources/qemu-tools/usr/lib/libfdt.so.1'))
    original=ctypes.create_string_buffer((HERE/'qemu-virt-board/virt-pcidma.dtb').read_bytes())
    buffer=ctypes.create_string_buffer(16384)
    assert fdt.fdt_open_into(original,buffer,len(buffer)) == 0
    fdt.fdt_getprop.restype=ctypes.c_void_p
    return fdt,buffer


def prop(fdt,buffer,path,name):
    length=ctypes.c_int()
    node=fdt.fdt_path_offset(buffer,path)
    assert node>=0
    pointer=fdt.fdt_getprop(buffer,node,name,ctypes.byref(length))
    assert pointer and length.value>=0
    return ctypes.string_at(pointer,length.value)


def test_smp2_preserves_board_and_declares_both_cpus():
    fdt,buffer=board()
    preserved={(p,n):prop(fdt,buffer,p,n) for p,n in (
        (b'/memory@40000000',b'reg'),(b'/chosen',b'bootargs'),
        (b'/intc@8000000',b'reg'),(b'/psci',b'method'))}
    configure(fdt,buffer)
    assert fdt.fdt_path_offset(buffer,b'/cpus/cpu-map')<0
    for cpu in (0,1):
        path=f'/cpus/cpu@{cpu}'.encode()
        assert prop(fdt,buffer,path,b'reg')==struct.pack('>I',cpu)
        assert prop(fdt,buffer,path,b'enable-method')==b'psci\0'
    assert struct.unpack('>12I',prop(fdt,buffer,b'/timer',b'interrupts'))[2::3]==(0x304,)*4
    assert struct.unpack('>3I',prop(fdt,buffer,b'/pmu',b'interrupts'))==(1,7,0x304)
    for (path,name),value in preserved.items():
        assert prop(fdt,buffer,path,name)==value
    with pytest.raises(ValueError,match='single-CPU'):
        configure(fdt,buffer)


@pytest.mark.parametrize('path,name,value',[
    (b'/psci',b'method',b'smc\0'),
    (b'/cpus',b'#address-cells',struct.pack('>I',2)),
    (b'/timer',b'interrupts',struct.pack('>3I',1,13,0x404)),
])
def test_smp2_rejects_mismatched_board_before_changes(path,name,value):
    fdt,buffer=board()
    node=fdt.fdt_path_offset(buffer,path)
    assert fdt.fdt_setprop(buffer,node,name,value,len(value))==0
    original=buffer.raw
    with pytest.raises(ValueError):
        configure(fdt,buffer)
    assert buffer.raw==original


def test_launcher_prepares_matched_cpu_count_and_fixed_dtb(tmp_path):
    initrd=tmp_path/'test.cpio';initrd.write_bytes(b'070701')
    output=tmp_path/'prepared'
    env={**os.environ,'QEMU_PREPARE_ONLY':'1','QEMU_CPU_COUNT':'2','QEMU_OUTPUT_DIR':str(output)}
    command=['bash',str(HERE/'qemu-kernel-probe.sh'),'4096',
             str(HERE/'qemu-virt-board/virt-pcidma.dtb'),'1','1',str(initrd)]
    subprocess.run(command,env=env,check=True,capture_output=True,timeout=20)
    fdt,_=board();buffer=ctypes.create_string_buffer((output/'virt.dtb').read_bytes())
    assert prop(fdt,buffer,b'/cpus/cpu@1',b'enable-method')==b'psci\0'
    assert prop(fdt,buffer,b'/chosen',b'linux,initrd-start')==struct.pack('>Q',0x440000000)
    assert prop(fdt,buffer,b'/sony-gicc-alias',b'phys')==struct.pack('>Q',0x08010000)
    assert prop(fdt,buffer,b'/sony-gicc-alias',b'virt')==struct.pack('>Q',0xfffffffff13a2000)
    assert prop(fdt,buffer,b'/sony-gicc-alias',b'size')==struct.pack('>Q',0x1000)
    env['QEMU_CPU_COUNT']='3'
    result=subprocess.run(command,env=env,capture_output=True,timeout=20)
    assert result.returncode==2 and b'must be 1 or 2' in result.stderr


def test_boot_and_target_proof_never_claims_irq_callback(tmp_path):
    fdt,buffer=board();configure(fdt,buffer)
    assert fdt.fdt_pack(buffer)==0
    (tmp_path/'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I',buffer.raw,4)[0]])
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(qemu_cpu_count=2)))
    console='[ 1.0] Brought up 2 CPUs\nNATIVE_CPU_ONLINE_BEGIN\n0-1\nNATIVE_CPU_ONLINE_END\n'
    (tmp_path/'console.log').write_text(console)
    events=[dict(kind='resize_mmio_enable',original_entry_verified=True,engine_index=i,
        gic_irq32_39_targets_hex='0101010202010101',gic_irq32_63_enable=0x18,
        gic_irq32_63_pending=0) for i in (1,2)]
    path=tmp_path/'resize-watch-events.jsonl'
    path.write_text('\n'.join(map(json.dumps,events)))
    result=proof(tmp_path)
    assert result['smp2_boot_verified'] and result['rc_gic_targets_cpu1_verified']
    assert not result['boot_serial_roundtrip_verified'] and not result['gic_loader_handoff_observed']
    (tmp_path/'boot-serial-roundtrip.log').write_text('\nMENU_DIAG_COMMAND_DONE_'+('a'*24)+':0\n')
    (tmp_path/'boot-irq-diagnostics.json').write_text(json.dumps(dict(gic=dict(state=dict(
        loader_spi_targets=True,irqs=[dict(irq=33,target=1,enabled=255)])))))
    assert proof(tmp_path)['gic_loader_handoff_observed']
    assert proof(tmp_path)['boot_uart_gic_state']['target']==1
    assert proof(tmp_path)['boot_serial_roundtrip_verified']
    (tmp_path/'rc-gic-state.json').write_text(json.dumps(dict(state=dict(schema='sony-gic-readback-v1',
        observations_only=True,irqs=[dict(irq=irq,target=2,enabled=255) for irq in (35,36)]))))
    assert proof(tmp_path)['rc_gic_targets_cpu1_verified']
    assert not result['cpu1_rc_callback_verified'] and not result['completion_verified']
    events[1]['gic_irq32_39_targets_hex']='0101010101010101'
    path.write_text('\n'.join(map(json.dumps,events)))
    (tmp_path/'rc-gic-state.json').unlink()
    assert proof(tmp_path)['smp2_boot_verified'] and not proof(tmp_path)['rc_gic_targets_cpu1_verified']
    (tmp_path/'console.log').write_text(console.replace('0-1\n','0\n'))
    assert not proof(tmp_path)['smp2_boot_verified']
