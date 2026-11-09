"""Original Sony DWC3 resources for the explicit product device profile."""
import ctypes
import struct
CONTROLLER="sony-device"
U32=lambda *v:struct.pack(">"+"I"*len(v),*v)
REG=lambda address,size:struct.pack(">QQ",address,size)

def add_nodes(fdt, buffer, mode='full', controller=CONTROLLER):
    """Compatible add_nodes API for usb-platform.py's DTB adapter call site."""
    if controller != CONTROLLER or mode != 'full':
        raise ValueError('Sony device resources require full/sony-device explicitly')
    root = fdt.fdt_path_offset(buffer, b'/')

    def prop(node, key):
        length = ctypes.c_int()
        ptr = fdt.fdt_getprop(buffer, node, key, ctypes.byref(length))
        return ctypes.string_at(ptr, length.value) if ptr and length.value >= 0 else None

    if prop(root, b'compatible') != b'linux,dummy-virt\0':
        raise ValueError('Expected explicit generic-virt board')
    if any(prop(root, key) != U32(2) for key in (b'#address-cells', b'#size-cells')):
        raise ValueError('Expected two-cell root resource addresses')
    gic = fdt.fdt_path_offset(buffer, b'/intc@8000000')
    if gic < 0 or not prop(gic, b'phandle'):
        raise ValueError('Missing explicit GIC phandle')
    # Reserve a bounded phandle range; reject collisions instead of guessing.
    handles = tuple(range(0x7f10, 0x7f14))
    for handle in handles:
        if fdt.fdt_node_offset_by_phandle(buffer, handle) >= 0:
            raise ValueError('USB profile phandle collision')
    paths = ('/sony-usb-clock', '/sony-usb-scu@f1388000', '/fusb_otg',
             '/fusb_dwc3regs@f10c0000', '/soc/usbs@f1080000')
    required = (*paths, paths[1] + '/rst@300', paths[4] + '/usb@f10c0000',
                '/sony-usb@f1080000')
    if any(fdt.fdt_path_offset(buffer, p.encode()) >= 0 for p in required):
        raise ValueError('USB resource node already exists')
    soc_values = {'compatible': b'simple-bus\0', '#address-cells': U32(2),
                  '#size-cells': U32(2), 'ranges': b''}
    soc = fdt.fdt_path_offset(buffer, b'/soc')
    if soc >= 0:
        actual_path = ctypes.create_string_buffer(256)
        if fdt.fdt_get_path(buffer, soc, actual_path, len(actual_path)) or actual_path.value != b'/soc':
            raise ValueError('Expected exact /soc bus path')
        count, cursor = 0, fdt.fdt_first_property_offset(buffer, soc)
        while cursor >= 0:
            count += 1
            cursor = fdt.fdt_next_property_offset(buffer, cursor)
        if (cursor != -1 or count != len(soc_values) or
                any(prop(soc, key.encode()) != value for key, value in soc_values.items()) or
                fdt.fdt_first_subnode(buffer, soc) != -1):
            raise ValueError('Existing /soc must be an empty exact two-cell simple-bus')
    elif soc != -1:
        raise ValueError('Cannot inspect /soc bus')

    def node(path, values):
        parent, _, name = path.rpartition('/')
        parent_node = fdt.fdt_path_offset(buffer, (parent or '/').encode())
        result = fdt.fdt_add_subnode(buffer, parent_node, name.encode())
        if result < 0:
            raise ValueError('Cannot add USB node ' + path + ': ' + str(result))
        for key, value in values.items():
            if fdt.fdt_setprop(buffer, result, key.encode(), value, len(value)) < 0:
                raise ValueError('Cannot set USB property ' + path + '/' + key)
        return result

    node(paths[0], {'compatible': b'cxd,900xx-clock\0', '#clock-cells': U32(1),
                    'reg': REG(0, 0x300), 'syscon': U32(handles[1]),
                    'phandle': U32(handles[0])})
    node(paths[1], {'compatible': b'cxd900xx,scu\0syscon\0simple-mfd\0',
                    '#address-cells': U32(2), '#size-cells': U32(2), 'ranges': b'',
                    'reg': REG(0xf1388000, 0x2000), 'phandle': U32(handles[1])})
    node(paths[1] + '/rst@300', {'compatible': b'cxd900xx,reset\0',
         'reg': REG(0x300, 0x80), '#reset-cells': U32(1),
         'syscon': U32(handles[1]), 'phandle': U32(handles[2])})
    node(paths[2], {'compatible': b'linux,extcon-fusb_otg\0',
                    'phandle': U32(handles[3]), 'status': b'okay\0'})
    node(paths[3], {'compatible': b'snps,fusb_dwc3regs\0',
                    'reg': REG(0xf10c0000, 0x11000), 'status': b'okay\0'})
    if soc < 0:
        node('/soc', soc_values)
    # OF uses translated reg + node name, with the real parent device hierarchy.
    node(paths[4], {'compatible': b'cxdchip,dwc3\0',
         'reg': REG(0xf1080000, 0x1000) + REG(0xf10a0000, 0x1c000),
         'reg-names': b'ss_usb\0phy_cr\0', '#address-cells': U32(2),
         '#size-cells': U32(2), 'ranges': b'',
         'clocks': U32(handles[0], 19, handles[0], 18, handles[0], 17, handles[0], 16),
         'clock-names': b'usb_sus_clk\0usb_axi_clk\0usb_apb_clk\0usb_refclk\0',
         'resets': U32(handles[2], 11, handles[2], 10, handles[2], 9, handles[2], 8),
         'reset-names': b'rst_u31\0rst_u2\0rst_apb\0rst_axi\0', 'status': b'okay\0'})
    # Re-read the GIC offset after every tree insertion: libfdt offsets can move.
    gic = fdt.fdt_path_offset(buffer, b'/intc@8000000')
    node(paths[4] + '/usb@f10c0000', {'compatible': b'snps,dwc3\0',
         'reg': REG(0xf10c0000, 0x11000), 'interrupt-parent': prop(gic, b'phandle'),
         'interrupts': U32(0, 184, 4), 'extcon': U32(handles[3]),
         'dr_mode': b'otg\0', 'maximum-speed': b'high-speed\0',
         'phy_type': b'utmi\0', 'status': b'okay\0'})
