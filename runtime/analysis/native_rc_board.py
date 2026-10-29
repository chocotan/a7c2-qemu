"""Reserve original RC/SA IRQs and map one configuration page in the private DTB."""
import ctypes
import mmap
import os
import stat
import struct


def require_binary(binary,reference=False,handoff=False,sa_data=False,sa_complete=False):
    with binary.open('rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('RC board requires a regular QEMU executable')
        with mmap.mmap(source.fileno(),0,access=mmap.ACCESS_READ) as image:
            if image.find(b'SONY_RC_BOARD_V2 gpex_spi_base=244')<0:
                raise ValueError('Selected QEMU lacks the RC board mapping; rebuild with rc-board.patch')
            if reference and image.find(b'SONY_RC_REFERENCE_V1 packing=unverified engines=B,C')<0:
                raise ValueError('Selected QEMU lacks the experimental RC data backend')
            if handoff and image.find(b'SONY_GIC_HANDOFF_V1 spi-default=cpu0')<0:
                raise ValueError('Selected QEMU lacks the GIC loader handoff')
            if sa_data and image.find(b'SONY_SA_DATA_ONLY_V1 no-completion-irq')<0:
                raise ValueError('Selected QEMU lacks the optional SA data-only backend')
            if sa_complete and image.find(b'SONY_SA_REFERENCE_COMPLETE_V1 virtual-group0-bit0')<0:
                raise ValueError('Selected QEMU lacks the explicit SA reference completion backend')


def configure(fdt, buffer):
    fdt.fdt_getprop.restype=ctypes.c_void_p
    pcie=fdt.fdt_path_offset(buffer,b'/pcie@10000000')
    gic=fdt.fdt_path_offset(buffer,b'/intc@8000000')
    if pcie<0 or gic<0:
        raise ValueError('RC board requires the known GPEX/GICv2 nodes')

    def get(node,name):
        length=ctypes.c_int()
        pointer=fdt.fdt_getprop(buffer,node,name,ctypes.byref(length))
        if not pointer or length.value<0:
            raise ValueError('Missing RC board interrupt property')
        return ctypes.string_at(pointer,length.value)

    raw=get(pcie,b'interrupt-map')
    if len(raw)!=16*10*4 or get(pcie,b'interrupt-map-mask')!=struct.pack('>4I',0x1800,0,0,7):
        raise ValueError('Unexpected GPEX interrupt-map shape')
    phandle=struct.unpack('>I',get(gic,b'phandle'))[0]
    words=list(struct.unpack('>160I',raw));seen=set()
    for start in range(0,len(words),10):
        entry=words[start:start+10]
        slot,pin=entry[0]>>11,entry[3]
        if (slot not in range(4) or pin not in range(1,5) or
                entry!=[slot<<11,0,0,pin,phandle,0,0,0,3+(slot+pin-1)%4,4] or
                (slot,pin) in seen):
            raise ValueError('Unexpected GPEX slot/pin/parent/SPI mapping')
        seen.add((slot,pin))
        words[start+8]=244+(slot+pin-1)%4
    mapped=struct.pack('>160I',*words)
    if fdt.fdt_setprop(buffer,pcie,b'interrupt-map',mapped,len(mapped)):
        raise ValueError('Cannot set relocated GPEX interrupt-map')


def add_control_map(fdt,buffer):
    node=fdt.fdt_add_subnode(buffer,0,b'sony-f280-control')
    if node<0:raise ValueError('Cannot add bounded CP configuration mapping')
    for name,value in {b'device_type':b'iomap\0',b'phys':struct.pack('>Q',0xf2800000),
            b'virt':struct.pack('>Q',0xfffffffff2800000),b'size':struct.pack('>Q',0x1000),
            b'memtype':struct.pack('>I',1)}.items():
        if fdt.fdt_setprop(buffer,node,name,value,len(value)):
            raise ValueError('Cannot set CP configuration mapping')


def reserve_sa_irq(fdt,buffer):
    node=fdt.fdt_path_offset(buffer,b'/virtio_mmio@a000000')
    if node<0:raise ValueError('Missing virtio transport sharing the SA2 interrupt')
    fdt.fdt_getprop.restype=ctypes.c_void_p
    size=ctypes.c_int()
    pointer=fdt.fdt_getprop(buffer,node,b'interrupts',ctypes.byref(size))
    if not pointer or size.value!=12 or ctypes.string_at(pointer,12)!=struct.pack('>3I',0,16,1):
        raise ValueError('Unexpected first virtio interrupt mapping')
    if fdt.fdt_setprop(buffer,node,b'status',b'disabled\0',9):
        raise ValueError('Cannot disable virtio transport sharing SA2 IRQ')
