#!/usr/bin/env python3
"""Independent final DTB, boot log and AT/PAR-only module review; no driver-init claim."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile
from verify_enumeration import fdt_nodes

HERE=Path(__file__).resolve().parent
WINDOWS=((0xf1056000,0x2000),(0xf11c0000,0x40000),(0xf7000000,0x1000),
         (0xf7300000,0x1000),(0xf7380000,0x2000))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    run=parser.parse_args().run;r=json.loads((run/'result.json').read_text())
    assert r['ok'] and r['vm_exited'] and not r.get('cleanup_error') and not r['retained_no_force_kill']
    assert r['early_iomap_preparation_passed'] and not any(r[k] for k in ('camera_app_started','sd_attached','udif_driver_start_requested','dma_executed','capture_verified'))
    elf_raw=(HERE.parent/'early-map-check/sony_early_io_check.ko').read_bytes()
    sha=hashlib.sha256(elf_raw).hexdigest();assert sha==r['mmio_adapter_sha256']
    elf=ELFFile(io.BytesIO(elf_raw));symbols=elf.get_section_by_name('.symtab')
    assert {s.name for s in symbols.iter_symbols() if s['st_shndx']=='SHN_UNDEF' and s.name}=={'printk'}
    text=elf.get_section_by_name('.init.text').data();words=struct.unpack('<'+'I'*(len(text)//4),text)
    assert any(w&0xffffffe0==0xd5087800 for w in words) and any(w&0xffffffe0==0xd5387400 for w in words)
    dtb=(run/'output/virt.dtb').read_bytes();nodes=fdt_nodes(dtb);spans=[]
    for index,(pa,size) in enumerate(WINDOWS):
        props=nodes['/sony-test-iomap-'+str(index)]
        for key,val in (('phys',pa),('virt',0xffffffff00000000|pa),('size',size)):
            assert props[key]==struct.pack('>Q',val)
        assert props['device_type']==b'iomap\0' and props['memtype']==struct.pack('>I',1)
    for props in nodes.values():
        if props.get('device_type')==b'iomap\0':
            start=struct.unpack('>Q',props['virt'])[0];size=struct.unpack('>Q',props['size'])[0];spans.append((start,start+size))
    spans.sort();assert all(a[1]<=b[0] for a,b in zip(spans,spans[1:]))
    gic=nodes['/sony-gic-alias'];assert struct.unpack('>Q',gic['phys'])[0]==0x08000000
    assert struct.unpack('>Q',gic['virt'])[0]==0xfffffffff13a1000
    raw=(run/'console.log').read_bytes();console=raw.replace(b'\r',b'')
    for index,(pa,size) in enumerate(WINDOWS):
        row=f'sony-test-iomap-{index}: {pa:x},{0xffffffff00000000|pa:x},{size:x},1'.encode()
        assert row in console and console.index(row)<console.index(b'Kernel command line:')
    assert b'SHA2-256(/tmp/sony_dma_map.ko)= '+sha.encode() in console
    assert b'EARLY_IOMAP_PASS: ten existing translations, original boot mapping; no mapper/MMIO/DMA' in console
    assert b'\nMMIO_ADAPTER_RC=0\n' in console
    token='EARLY_IOMAP_CPU_RESUMED_'+run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (run/'early-iomap-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    assert b'blacklisting initcall __boottime___udif_init_pcidma' in console
    assert b'blacklisting initcall __boottime___udif_init_udif_pcie' in console
    review={'status':'PASS_ORIGINAL_BOOT_NARROW_IOMAP_ONLY','module_sha256':sha,
        'final_dtb_sha256':hashlib.sha256(dtb).hexdigest(),'console_sha256':hashlib.sha256(raw).hexdigest(),
        'windows':[[hex(p),hex(n)] for p,n in WINDOWS],'original_boot_map_logs_before_init':True,
        'ten_existing_translations_at_par_verified':True,'diagnostic_imports':['printk'],
        'gic_alias_and_overlap_guard_preserved':True,'cpu_resumed_and_owned_vm_exited':True,
        'native_pcidma_or_pcie_init_executed':False,'dma_or_capture_verified':False}
    (HERE.parent/'early-iomap-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS original boot iomap logs + actual final DTB/GIC + ten AT/PAR translations; NO driver init/DMA claim')


if __name__=='__main__':main()
