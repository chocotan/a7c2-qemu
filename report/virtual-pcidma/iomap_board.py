#!/usr/bin/env python3
"""Derive five narrow TEST windows using the original iomap schema; no source writes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

HERE=Path(__file__).resolve().parent
WINDOWS=((0xf1056000,0x2000),(0xf11c0000,0x40000),(0xf7000000,0x1000),
         (0xf7300000,0x80000),(0xf7380000,0x2000))


def prepare(base,output,official,all_pcie_wrappers=False,ccf_provider=False,phy_upload=False,dma_window=False,extra_windows=(),backup_control=False):
    if backup_control and not dma_window:raise ValueError('Backup control BAR requires the DMA host window')
    if phy_upload and not ccf_provider:raise ValueError('Bounded original PHY upload requires real CCF provider input')
    if dma_window and not phy_upload:raise ValueError('DMA transfer window requires the bounded upload/SoC host input')
    spec=importlib.util.spec_from_file_location('iomap_of',HERE/'verifiers/verify_enumeration.py')
    of=importlib.util.module_from_spec(spec);spec.loader.exec_module(of)
    base,output,official=map(Path,(base,output,official))
    if output.exists() or base.resolve()==output.resolve():raise ValueError('DTB output must be new')
    raw=base.read_bytes();official_raw=official.read_bytes()
    assert hashlib.sha256(official_raw).hexdigest()=='c5735ad9c6da8c48fb24eeee0bb743d07c486a47d5db19bef13b5eaea24ad280'
    before=of.fdt_nodes(raw);official_nodes=of.fdt_nodes(official_raw);props=official_nodes['/iomem@0xf0000000']
    assert not any(p.get('device_type')==b'iomap\0' for p in before.values())
    fields={name:props[name] for name in ('device_type','phys','virt','size','memtype')}
    assert fields['device_type']==b'iomap\0'
    assert tuple(struct.unpack('>Q',fields[n])[0] for n in ('phys','virt','size'))==(0xf0000000,0xfffffffff0000000,0xe000000)
    assert fields['memtype']==struct.pack('>I',1)
    header=list(struct.unpack_from('>10I',raw));magic,total,off_struct,off_strings,off_reserve=header[:5]
    size_strings,size_struct=header[8:10]
    assert magic==0xd00dfeed and total<=len(raw) and 40<=off_reserve<off_struct<off_strings
    structure=raw[off_struct:off_struct+size_struct];strings=bytearray(raw[off_strings:off_strings+size_strings])
    assert len(structure)==size_struct and len(strings)==size_strings
    offset=depth=0;closing=None
    while offset<len(structure):
        at=offset;token=struct.unpack_from('>I',structure,offset)[0];offset+=4
        if token==1:
            offset=(structure.index(0,offset)+4)&~3;depth+=1
        elif token==2:
            depth-=1
            if depth==0:closing=at
        elif token==3:
            length=struct.unpack_from('>I',structure,offset)[0];offset+=8
            offset+=(length+3)&~3
        elif token==9:break
        elif token!=4:raise ValueError('Unsupported FDT structure token')
    assert closing is not None and depth==0 and token==9
    windows=list(WINDOWS)
    if all_pcie_wrappers:windows[1]=(0xf1100000,0x140000)
    windows.extend(extra_windows)
    added=bytearray();expected={}
    def emit(node,selected,parent='',children=()):
        path=parent+'/'+node;assert path not in before and path not in expected
        name=node.encode()+b'\0'
        added.extend(struct.pack('>I',1)+name+b'\0'*((-len(name))%4))
        expected[path]=selected
        for key,value in selected.items():
            encoded=key.encode()+b'\0';index=strings.find(encoded)
            if index<0:index=len(strings);strings.extend(encoded)
            added.extend(struct.pack('>III',3,len(value),index)+value+b'\0'*((-len(value))%4))
        for child,attributes in children:emit(child,attributes,path)
        added.extend(struct.pack('>I',2))
    for number,(physical,size) in enumerate(windows):
        selected=dict(fields,phys=struct.pack('>Q',physical),
            virt=struct.pack('>Q',0xffffffff00000000|physical),size=struct.pack('>Q',size))
        emit('sony-test-iomap-'+str(number),selected)
    handles={}
    if ccf_provider:
        u32=lambda v:struct.pack('>I',v)
        phandles=[struct.unpack('>I',p[k])[0] for p in before.values()
                  for k in ('phandle','linux,phandle') if k in p]
        first=max(phandles,default=0)+1;assert first+(3 if phy_upload else 2)<0xffffffff
        handles={'scu':first,'clock':first+1,'reset':first+2}
        source_path='/soc/scu@F1388000'
        scu=dict(official_nodes[source_path]);clock=dict(official_nodes[source_path+'/clock-controller@0'])
        reset=dict(official_nodes[source_path+'/rst@300'])
        for p in (scu,clock,reset):
            p.pop('phandle',None);p.pop('linux,phandle',None)
        # Explicit TEST parent uses real generic syscon, not another SoC driver.
        scu['compatible']=b'syscon\0simple-mfd\0';scu['phandle']=u32(handles['scu'])
        clock['phandle']=u32(handles['clock']);clock['syscon']=u32(handles['scu'])
        reset['phandle']=u32(handles['reset']);reset['syscon']=u32(handles['scu'])
        emit('sony-test-scu',scu,children=(('clock-controller@0',clock),('rst@300',reset)))
        names=('apb_pclk','dbi_aclk','slv_aclk','mstr_aclk','aux_clk','axi2avb_pcie0','axi2avb_pcie1')
        ids=(62,63,64,65,66,29,30)
        consumer={'clock-names':b''.join(name.encode()+b'\0' for name in names),
            'clocks':b''.join(u32(handles['clock'])+u32(ident) for ident in ids)}
        emit('sony-test-ccf-consumer',consumer)
        if phy_upload:
            # This enables the real original probe only for the explicitly gated
            # upload experiment; lane-ready remains unavailable in its model.
            handles['intx']=first+3
            gics=[p for p in before.values() if 'interrupt-controller' in p and
                  p.get('compatible')==b'arm,cortex-a15-gic\0']
            assert len(gics)==1
            gic=gics[0];gic_handle=struct.unpack('>I',gic['phandle'])[0]
            gic_addr_cells=struct.unpack('>I',gic['#address-cells'])[0];assert gic_addr_cells==2
            host=dict(official_nodes['/soc/pcie_i'])
            host.pop('phandle',None);host.pop('linux,phandle',None)
            host['status']=b'okay\0';host['interrupt-parent']=u32(gic_handle)
            for field,old,new in (('clocks',2,handles['clock']),('resets',3,handles['reset'])):
                cells=list(struct.unpack('>'+str(len(host[field])//4)+'I',host[field]))
                assert all(value==old for value in cells[::2])
                cells[::2]=[new]*(len(cells)//2);host[field]=b''.join(map(u32,cells))
            irqmap=list(struct.unpack('>32I',host['interrupt-map']))
            assert irqmap[:8]==[0,0,0,0,1,0,166,4]
            remap=[0,0,0,0,gic_handle]+[0]*gic_addr_cells+[0,166,4]
            for i in range(4):
                entry=irqmap[8+6*i:14+6*i];assert entry==[0,0,0,i+1,5,i]
                entry[4]=handles['intx'];remap.extend(entry)
            host['interrupt-map']=b''.join(map(u32,remap))
            intx=dict(official_nodes['/soc/pcie_i/interrupt-controller'])
            intx['phandle']=intx['linux,phandle']=u32(handles['intx'])
            bridge=dict(official_nodes['/soc/pcie_i/pcie_i_bridge'])
            if dma_window:
                # TEST-board only: official 64KiB MEM window cannot hold the
                # 16MiB TEST peer BAR. Widen to 32MiB for the transfer test;
                # official DTB stays untouched and this is not a Sony property.
                ranges=list(struct.unpack('>7I',host['ranges']))
                assert ranges[3:7]==[0,0xdffe0000,0,0x10000]
                # The additional control BAR can require a 32MiB-aligned bridge
                # allocation; 64MiB accommodates it inside the unaligned host range.
                ranges[6]=0x4000000 if backup_control else 0x2000000
                host['ranges']=b''.join(map(u32,ranges))
            emit('sony-test-pcie0',host,children=(('interrupt-controller',intx),('pcie_i_bridge',bridge)))
    structure=structure[:closing]+added+structure[closing:]
    header[3]=off_struct+len(structure);header[8]=len(strings);header[9]=len(structure)
    header[1]=header[3]+len(strings)
    derived=bytearray(raw[:off_struct]+structure+strings)
    struct.pack_into('>10I',derived,0,*header);output.write_bytes(derived)
    after=of.fdt_nodes(output.read_bytes())
    for node,selected in expected.items():assert after.pop(node)==selected
    assert after==before
    report={'base_sha256':hashlib.sha256(raw).hexdigest(),'derived_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
        'only_added_nodes':list(expected),'schema_and_memtype_from_official':True,
        'narrow_test_windows':[[hex(p),hex(n)] for p,n in windows],
        'ccf_provider_handles':handles,'ccf_test_generic_syscon_parent':ccf_provider,
        'original_controller0_probe_enabled_for_bounded_upload':phy_upload,
        'guarded_backup_control_window':backup_control,
        'driver_initcalls_changed':False,'overlap_guard_unchanged':True}
    (output.parent/'iomap-board-proof.json').write_text(json.dumps(report,indent=2)+'\n')
    return output
