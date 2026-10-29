#!/usr/bin/env python3
"""Verify partial native IRQ registration without promoting WARN-tainted init to PASS."""
import argparse
import hashlib
import json
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);run=p.parse_args().run
    result_raw=(run/'result.json').read_bytes();r=json.loads(result_raw)
    raw=(run/'console.log').read_bytes();console=raw.replace(b'\r',b'')
    assert r['vm_exited'] and not r.get('cleanup_error') and not r['dma_executed'] and not r['capture_verified']
    assert b'blacklisting initcall __boottime___udif_init_udif_pcie' in console
    assert b'blacklisting initcall __boottime___udif_init_pcidma' not in console
    assert re.search(rb'initcall __boottime___udif_init_pcidma\+[^\n]*returned 0 ',console)
    warnings=re.findall(rb'WARNING: CPU:[^\n]*',console)
    assert len(warnings)==5 and all(b'__xlate_proc_name' in line for line in warnings)
    for index in range(5):assert f"name 'driver/pcie/{index}/dma'".encode() in console
    assert b'pcidma_init+' in console and b'__udif_driver_init+' in console
    irqs=(run/'native-pcidma-irqs.txt').read_bytes().replace(b'\r',b'')
    for irq in (198,200,202,204,206):
        assert re.search(rb'^\s*'+str(irq).encode()+rb':\s+\d+\s+GIC-0\s+'+
            str(irq).encode()+rb'\s+Level\s+PCIeDMAC\s*$',irqs,re.M)
    for name in ('write','read'):
        text=(run/('native-engine-'+name+'.txt')).read_text()
        values=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[1]);assert len(values)==1 and int(values[0],16)==0
    token='NATIVE_PCIDMA_INIT_CPU_RESUMED_'+run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (run/'native-pcidma-init-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    review={'status':'VERIFIED_PARTIAL_NATIVE_IRQS_WITH_PROC_WARNINGS',
        'original_auto_result_preserved':True,'original_result_sha256':hashlib.sha256(result_raw).hexdigest(),
        'console_sha256':hashlib.sha256(raw).hexdigest(),'native_boottime_and_udif_worker_observed':True,
        'actual_irq_rows':[198,200,202,204,206],'engine_enables':[0,0],'warnings':5,
        'missing_proc_paths':[f'driver/pcie/{i}/dma' for i in range(5)],
        'cpu_resumed_and_owned_vm_exited':True,'clean_native_init_verified':False,
        'dma_or_capture_verified':False}
    (HERE.parent/'native-init-partial-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_VERIFIED_PARTIAL actual original boot/IRQ registrations, five proc WARNs; NOT clean initialization PASS')


if __name__=='__main__':main()
