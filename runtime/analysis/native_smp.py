"""Prepare a matched two-CPU PSCI DTB; never patch guest CPU/IRQ state."""
import ctypes
import json
from pathlib import Path
import re
import struct


def configure(fdt, buffer):
    fdt.fdt_getprop.restype = ctypes.c_void_p

    def node(path):
        result = fdt.fdt_path_offset(buffer, path)
        if result < 0:
            raise ValueError(f'Missing SMP DTB node {path!r}')
        return result

    def get(path, name):
        length = ctypes.c_int()
        pointer = fdt.fdt_getprop(buffer, node(path), name, ctypes.byref(length))
        if not pointer or length.value < 0:
            raise ValueError(f'Missing SMP DTB property {path!r}/{name!r}')
        return ctypes.string_at(pointer, length.value)

    def put(path, name, value):
        if fdt.fdt_setprop(buffer, node(path), name, value, len(value)):
            raise ValueError(f'Cannot set SMP DTB property {path!r}/{name!r}')

    cell = lambda value: struct.pack('>I', value)
    # Check the known GICv2, single-CPU input before mutating the private buffer.
    required = ((b'/cpus', b'#address-cells', cell(1)),
                (b'/cpus', b'#size-cells', cell(0)),
                (b'/cpus/cpu@0', b'reg', cell(0)),
                (b'/cpus/cpu@0', b'device_type', b'cpu\0'),
                (b'/cpus/cpu@0', b'compatible', b'arm,cortex-a35\0'),
                (b'/psci', b'method', b'hvc\0'),
                (b'/intc@8000000', b'compatible', b'arm,cortex-a15-gic\0'))
    for path, name, expected in required:
        if get(path, name) != expected:
            raise ValueError(f'Unsupported SMP DTB property {path!r}/{name!r}')
    children = fdt.fdt_first_subnode(buffer, node(b'/cpus'))
    cpu_count = 0
    while children >= 0:
        length = ctypes.c_int()
        pointer = fdt.fdt_getprop(buffer, children, b'device_type', ctypes.byref(length))
        cpu_count += bool(pointer and ctypes.string_at(pointer, length.value) == b'cpu\0')
        children = fdt.fdt_next_subnode(buffer, children)
    if cpu_count != 1:
        raise ValueError('SMP profile requires the original single-CPU DTB')
    interrupt_properties = ((b'/timer', struct.pack('>12I', 1,13,0x104,1,14,0x104,1,11,0x104,1,10,0x104)),
                            (b'/pmu', struct.pack('>3I', 1,7,0x104)))
    for path, expected in interrupt_properties:
        if get(path, b'interrupts') != expected:
            raise ValueError('Unsupported GICv2 PPI configuration')
    cpu_map = fdt.fdt_path_offset(buffer, b'/cpus/cpu-map')
    if cpu_map >= 0 and fdt.fdt_del_node(buffer, cpu_map):
        raise ValueError('Cannot remove unsupported optional CPU topology map')
    if fdt.fdt_add_subnode(buffer, node(b'/cpus'), b'cpu@1') < 0:
        raise ValueError('Cannot add CPU1')
    for name, value in ((b'device_type', b'cpu\0'), (b'compatible', b'arm,cortex-a35\0'), (b'reg', cell(1))):
        put(b'/cpus/cpu@1', name, value)
    for cpu in (b'/cpus/cpu@0', b'/cpus/cpu@1'):
        put(cpu, b'enable-method', b'psci\0')
    for path, original in interrupt_properties:
        values = list(struct.unpack('>'+str(len(original)//4)+'I', original))
        values[2::3] = [0x304] * (len(values)//3)
        put(path, b'interrupts', struct.pack('>'+str(len(values))+'I', *values))


def proof(run):
    """Keep boot/target evidence separate from actual original IRQ consumption."""
    run=Path(run)
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    console=(run/'console.log').read_text(errors='replace')
    fdt=ctypes.CDLL(str(Path(__file__).resolve().parent/'../sources/qemu-tools/usr/lib/libfdt.so.1'))
    fdt.fdt_getprop.restype=ctypes.c_void_p
    buffer=ctypes.create_string_buffer((run/'virt.dtb').read_bytes())

    def get(path,name):
        node=fdt.fdt_path_offset(buffer,path)
        if node<0:return None
        length=ctypes.c_int()
        pointer=fdt.fdt_getprop(buffer,node,name,ctypes.byref(length))
        return ctypes.string_at(pointer,length.value) if pointer and length.value>=0 else None

    matched=(manifest.get('qemu_cpu_count')==2 and
        get(b'/psci',b'method')==b'hvc\0' and
        all(get(f'/cpus/cpu@{cpu}'.encode(),b'enable-method')==b'psci\0' and
            get(f'/cpus/cpu@{cpu}'.encode(),b'reg')==struct.pack('>I',cpu) for cpu in (0,1)) and
        get(b'/timer',b'interrupts')==struct.pack('>12I',1,13,0x304,1,14,0x304,1,11,0x304,1,10,0x304) and
        get(b'/pmu',b'interrupts')==struct.pack('>3I',1,7,0x304))
    online=(re.search(r'^NATIVE_CPU_ONLINE_BEGIN\r?\n0-1\r?\nNATIVE_CPU_ONLINE_END\r?$',console,re.M) is not None and
            'Brought up 2 CPUs' in console)
    events=run/'resize-watch-events.jsonl'
    targets=[]
    for line in events.read_text().splitlines() if events.exists() else []:
        event=json.loads(line)
        if event.get('kind')!='resize_mmio_enable' or event.get('original_entry_verified') is not True:continue
        raw=bytes.fromhex(event.get('gic_irq32_39_targets_hex',''))
        if len(raw)==8:
            targets.append(dict(engine=event['engine_index'],irq35_cpu_mask=raw[3],irq36_cpu_mask=raw[4],
                enable=event['gic_irq32_63_enable'],pending=event['gic_irq32_63_pending']))
    routed=bool(targets) and {t['engine'] for t in targets}>={1,2} and all(
        t['irq35_cpu_mask']==t['irq36_cpu_mask']==2 and t['enable']&0x18==0x18 for t in targets)
    diagnostics=run/'boot-irq-diagnostics.json'
    readback=json.loads(diagnostics.read_text()) if diagnostics.exists() else {}
    gic=readback.get('gic',{}).get('state',{})
    uart=next((irq for irq in gic.get('irqs',[]) if irq.get('irq')==33),None)
    rc_path=run/'rc-gic-state.json'
    rc_gic=json.loads(rc_path.read_text()).get('state',{}) if rc_path.exists() else {}
    if rc_gic.get('schema')=='sony-gic-readback-v1' and rc_gic.get('observations_only') is True:
        rc_irqs=[irq for irq in rc_gic.get('irqs',[]) if irq.get('irq') in (35,36)]
        routed=bool(len(rc_irqs)==2 and all(irq['target']==2 and irq['enabled'] for irq in rc_irqs))
    roundtrip=run/'boot-serial-roundtrip.log'
    serial_verified=roundtrip.is_file() and re.search(
        rb'\nMENU_DIAG_COMMAND_DONE_[0-9a-f]{24}:0\r?\n',roundtrip.read_bytes()) is not None
    return dict(matched_smp2_dtb_verified=matched,two_cpus_online_verified=online,
        smp2_boot_verified=bool(matched and online),gic_observations=targets,
        gic_loader_handoff_requested=manifest.get('gic_loader_handoff') is True,
        gic_loader_handoff_observed=gic.get('loader_spi_targets') is True,
        boot_uart_gic_state=uart,
        rc_gic_state=rc_gic,
        boot_serial_roundtrip_verified=serial_verified,
        rc_gic_targets_cpu1_verified=bool(matched and online and routed),
        original_registration_return_verified=False,cpu1_rc_callback_verified=False,
        pixel_processing_verified=False,completion_verified=False)
