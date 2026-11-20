"""Native fixed-VA aliases for the two implemented AP transport devices only."""
import struct

PROFILE='virtual-native-ap-cp-link-v1'
WINDOWS=(('sony-native-atu-alias',0xf7300000,0x1000),
         ('sony-native-edma-alias',0xf7380000,0x2000))


def add_iomaps(fdt,buffer,profile):
    if profile!=PROFILE:
        raise ValueError('Native PCIe aliases require the exact native link profile')
    for name,_,_ in WINDOWS:
        if fdt.fdt_path_offset(buffer,('/'+name).encode())>=0:
            raise ValueError('Native transport alias already exists: '+name)
    for name,physical,size in WINDOWS:
        node=fdt.fdt_add_subnode(buffer,0,name.encode())
        if node<0:raise ValueError('Cannot add native transport alias: '+name)
        properties={b'device_type':b'iomap\0',b'phys':struct.pack('>Q',physical),
                    b'virt':struct.pack('>Q',0xffffffff00000000|physical),
                    b'size':struct.pack('>Q',size),b'memtype':struct.pack('>I',1)}
        for field,value in properties.items():
            if fdt.fdt_setprop(buffer,node,field,value,len(value))!=0:
                raise ValueError('Cannot set native transport alias property: '+name)
