#!/usr/bin/env python3
"""Independent original PCIe-UDIF/PCIDMA lifecycle review; never a host/link/DMA claim."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from verify_enumeration import fdt_nodes

HERE=Path(__file__).resolve().parent
WRAPPERS=(0xf11e0380,0xf1160380,0xf11a0380,0xf1220380,0xf1120380)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path)
    a=p.parse_args();r=json.loads((a.run/'result.json').read_text());proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['candidate_binary_sha256']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert r['ok'] and r['vm_exited'] and not r.get('cleanup_error') and not r['retained_no_force_kill']
    assert r['native_pcie_udif_boot_init_requested'] and r['native_pcidma_boot_init_requested']
    assert not any(r[key] for key in ('camera_app_started','sd_attached','dma_executed','capture_verified'))
    raw=(a.run/'console.log').read_bytes();console=raw.replace(b'\r',b'')
    assert not re.search(rb'WARNING: CPU:|Kernel panic|BUG:',console)
    for name in ('__boottime___udif_init_udif_pcie','__boottime___udif_init_pcidma'):
        assert ('blacklisting initcall '+name).encode() not in console
        assert re.search(rb'initcall '+name.encode()+rb'\+[^\n]*returned 0 ',console)
    irqs=(a.run/'native-pcidma-irqs.txt').read_bytes().replace(b'\r',b'')
    for irq in (198,200,202,204,206):assert re.search(rb'^\s*'+str(irq).encode()+rb':\s+\d+\s+GIC-0\s+'+str(irq).encode()+rb'\s+Level\s+PCIeDMAC\s*$',irqs,re.M)
    paths=(a.run/'native-pcie-proc-paths.txt').read_bytes().replace(b'\r',b'')
    for i in range(5):assert ('\nPCIE_PROC_ENTRY_'+str(i)+'\n').encode() in paths
    for name in ('write','read'):
        text=(a.run/('native-engine-'+name+'.txt')).read_text();words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[1])
        assert len(words)==1 and int(words[0],16)==0
    trace_raw=(a.run/'output/boot-trace.log').read_bytes();events=[]
    for m in re.finditer(rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-pcie-scu-region([0-6])'",trace_raw):
        address,value,size,index=m.groups();events.append((int(address,16),int(value,16),int(size)))
    for i,(hbit,rbit) in enumerate(zip((1,7,13,19,25),(3,11,7,15,19))):
        wanted=((0xf1388084,1<<hbit,4),(0xf1388318,1<<rbit,4),(WRAPPERS[i],0x10,4),(0xf1388088,1<<hbit,4))
        cursor=0
        for event in events:
            if event==wanted[cursor]:
                cursor+=1
                if cursor==4:break
        assert cursor==4,(i,'actual SCU control sequence missing')
    assert r['native_pcie_scu_final_state']=={'hclk':0,'apb-reset':0,**{'wrapper'+str(i):16 for i in range(5)}}
    nodes=fdt_nodes((a.run/'output/virt.dtb').read_bytes());wrapper=nodes['/sony-test-iomap-1']
    assert struct.unpack('>Q',wrapper['phys'])[0]==0xf1100000 and struct.unpack('>Q',wrapper['size'])[0]==0x140000
    assert struct.unpack('>Q',nodes['/sony-gic-alias']['phys'])[0]==0x08000000
    token='NATIVE_PCIDMA_INIT_CPU_RESUMED_'+a.run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (a.run/'native-pcidma-init-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    review={'status':'PASS_ORIGINAL_PCIE_UDIF_AND_PCIDMA_LIFECYCLE_ONLY','binary_sha256':digest,
        'actual_irqs':[198,200,202,204,206],'native_proc_paths':5,'kernel_warnings':0,
        'native_scu_sequences':5,'scu_mmio_writes':len(events),'backend_state_matches_trace':True,
        'trace_sha256':hashlib.sha256(trace_raw).hexdigest(),'console_sha256':hashlib.sha256(raw).hexdigest(),
        'engines_remain_disabled':[0,0],'cpu_resumed_and_owned_vm_exited':True,
        'soc_host_link_or_original_dma_or_capture_verified':False}
    (HERE.parent/'native-udif-init-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS original two UDIF initcalls, clean proc/IRQs and five actual gated SCU sequences; NO SoC host/link/DMA/capture')


if __name__=='__main__':main()
