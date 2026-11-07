#!/usr/bin/env python3
"""Explicit Sony USB platform-resource description, independently of MMIO."""
import ctypes
import struct


def add_nodes(fdt,buffer,mode,controller='off'):
    if mode=='off':return
    if mode not in ('regs','full') or (mode=='full' and controller!='upstream-host'):
        raise ValueError('Extcon description requires the verified explicit upstream DWC3 host model')
    root=fdt.fdt_path_offset(buffer,b'/')

    def prop(node,name):
        length=ctypes.c_int()
        pointer=fdt.fdt_getprop(buffer,node,name,ctypes.byref(length))
        return ctypes.string_at(pointer,length.value) if pointer and length.value>=0 else None

    if prop(root,b'compatible')!=b'linux,dummy-virt\0':
        raise ValueError('USB platform experiment requires the declared generic-virt board')
    if any(prop(root,name)!=struct.pack('>I',2) for name in (b'#address-cells',b'#size-cells')):
        raise ValueError('USB platform experiment requires two-cell root addresses/sizes')
    name=b'fusb_dwc3regs@f10c0000'
    node=fdt.fdt_path_offset(buffer,b'/'+name)
    if node>=0:raise ValueError('Unexpected preexisting USB resource-provider node')
    node=fdt.fdt_add_subnode(buffer,root,name)
    if node<0:raise ValueError('Cannot add USB platform resource node: '+str(node))
    values={b'compatible':b'snps,fusb_dwc3regs\0',
            b'reg':struct.pack('>QQ',0xf10c0000,0x11000),b'status':b'okay\0'}
    for key,value in values.items():
        if fdt.fdt_setprop(buffer,node,key,value,len(value))<0:
            raise ValueError('Cannot set USB platform resource '+key.decode())
    if mode=='full':
        node=fdt.fdt_add_subnode(buffer,root,b'fusb_otg')
        if node<0:raise ValueError('Cannot add original USB extcon platform node')
        for key,value in ((b'compatible',b'linux,extcon-fusb_otg\0'),(b'status',b'okay\0')):
            if fdt.fdt_setprop(buffer,node,key,value,len(value))<0:
                raise ValueError('Cannot set original USB extcon platform property')
    # A platform node and host capability model are not gadget/connection proof.


def adapt_script(text):
    if 'FULLSYSTEM_USB_PLATFORM_NODES' in text:
        old='"$analysis_dir/../../usb-platform.py" <<\'PY\''
        if old in text:text=text.replace(old,'"$analysis_dir/../../usb-platform.py" "${QEMU_FULL_USB_CONTROLLER:-off}" <<\'PY\'',1)
        text=text.replace('["add_nodes"](fdt,buffer,sys.argv[6])',
                          '["add_nodes"](fdt,buffer,sys.argv[6],sys.argv[8])',1)
        return text
    before='"$cmdline" "$test_initrd" "$high_ddr" <<\'PY\''
    after='"$cmdline" "$test_initrd" "$high_ddr" "${QEMU_FULL_USB_PLATFORM:-off}" "$analysis_dir/../../usb-platform.py" "${QEMU_FULL_USB_CONTROLLER:-off}" <<\'PY\''
    if text.count(before)!=1:raise ValueError('Ambiguous USB DTB adapter arguments')
    text=text.replace(before,after,1)
    anchor='# Reject overlapping static virtual mappings before booting the unmodified kernel.'
    if text.count(anchor)!=1:raise ValueError('Ambiguous USB DTB adapter insertion')
    code=('# FULLSYSTEM_USB_PLATFORM_NODES: resource description only, never fake MMIO.\n'
          'import runpy\n'
          'runpy.run_path(sys.argv[7])["add_nodes"](fdt,buffer,sys.argv[6],sys.argv[8])\n')
    return text.replace(anchor,code+anchor,1)
