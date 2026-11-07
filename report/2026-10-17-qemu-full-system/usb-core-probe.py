#!/usr/bin/env python3
"""Read-only, paused-VM gadget-core inspection for the fixed 2.01 Image ABI."""
import re

KERNEL_SHA256='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
RAM_START=0x400000000
RAM_END=0x600000000
PAGE_OFFSET=0xffffffc000000000
# From original adrp/ldr in usb_gadgetcore_register_driver, guarded below.
CORE_GLOBAL_PHYSICAL=0x400721538
FAULT_INSTRUCTION_PHYSICAL=0x400365cd4
CONTROLLER_GLOBAL_PHYSICAL=0x400720c10
RESOURCE_GLOBAL_PHYSICAL=0x400720c48


def probe(qmp,kernel_sha256):
    if kernel_sha256!=KERNEL_SHA256:
        raise ValueError('USB readback requires the exact original 2.01 kernel ABI')

    def physical(virtual):
        value=virtual-PAGE_OFFSET+RAM_START
        if not RAM_START<=value<RAM_END:
            raise ValueError('USB core/list pointer is outside the declared direct-map RAM')
        return value

    def words(address,count,width=8):
        if not RAM_START<=address or address+count*width>RAM_END:
            raise ValueError('USB probe refuses a non-RAM physical read')
        command=f'xp /{count}{"g" if width==8 else "w"}x {address:#x}'
        text=qmp('human-monitor-command',{'command-line':command})
        values=[int(value,16) for value in re.findall(r'0x([0-9a-fA-F]+)',text)]
        if len(values)!=count:
            raise ValueError('Incomplete USB RAM readback: '+command)
        return values

    running=qmp('query-status').get('running',False)
    if running:qmp('stop')
    try:
        if words(FAULT_INSTRUCTION_PHYSICAL,1,4)!=[0xf94036f4]:
            raise ValueError('Original USB fault-instruction identity mismatch')
        pointer=words(CORE_GLOBAL_PHYSICAL,1)[0]
        controller=words(CONTROLLER_GLOBAL_PHYSICAL,1)[0]
        resource=words(RESOURCE_GLOBAL_PHYSICAL,2)
        result={'kernel_sha256':kernel_sha256,'core_global_physical':hex(CORE_GLOBAL_PHYSICAL),
                'core_pointer':hex(pointer),'core_created':bool(pointer),
                'controller_pointer':hex(controller),
                'controller_resource_start':hex(resource[0]),'controller_resource_end':hex(resource[1]),
                'camera_startup_verified':False,'usb_connection_verified':False}
        if controller:
            registers=words(physical(controller),8)
            result.update(controller_otg_regs=hex(registers[4]),controller_host_regs=hex(registers[5]),
                          controller_gadget_regs=hex(registers[6]),controller_global_regs=hex(registers[7]))
        if not pointer:return result
        core=words(physical(pointer),21)
        flags=core[0x68//8]
        head=pointer+0x88
        current,previous=core[0x88//8],head
        visited=[]
        for _ in range(16):
            if current==head:break
            if current in visited:raise ValueError('USB function-list cycle outside its head')
            following,back=words(physical(current),2)
            if back!=previous:raise ValueError('USB function-list backlink mismatch')
            visited.append(current);previous,current=current,following
        truncated=current!=head
        if not truncated and core[0x90//8]!=previous:
            raise ValueError('USB function-list head/tail mismatch')
        result.update(atomic_bitflags=hex(flags),started=bool(flags&4),
                      function_list_head=hex(head),function_entries=[hex(p) for p in visited],
                      function_list_truncated=truncated,core_structure_verified=True)
        return result
    finally:
        if running:qmp('cont')
