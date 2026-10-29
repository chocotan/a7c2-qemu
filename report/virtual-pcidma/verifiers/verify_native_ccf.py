#!/usr/bin/env python3
"""Independent original CCF provider/API rows and hardware gate effects, saved bytes only."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
from verify_enumeration import fdt_nodes

HERE=Path(__file__).resolve().parent
EXPECTED=((62,99000000),(63,396000000),(64,396000000),(65,396000000),(66,1000000),(29,0),(30,0))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path)
    a=p.parse_args();r=json.loads((a.run/'result.json').read_text());proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['candidate_binary_sha256']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    assert r['ok'] and r['vm_exited'] and not r.get('cleanup_error') and not r['retained_no_force_kill']
    assert r['native_ccf_provider_requested'] and not any(r[key] for key in ('camera_app_started','sd_attached','dma_executed','capture_verified'))
    console=(a.run/'console.log').read_bytes().replace(b'\r',b'');assert not re.search(rb'WARNING: CPU:|Kernel panic|BUG:',console)
    raw=(a.run/'native-ccf-client.txt').read_bytes().replace(b'\r',b'')
    sha=hashlib.sha256((HERE.parent/'ccf-client/sony_ccf_client.ko').read_bytes()).hexdigest()
    assert b'SHA2-256(/tmp/sony_ccf_client.ko)= '+sha.encode() in raw
    assert b'\nNATIVE_CCF_LOAD_RC=0\n' in raw and re.search(rb'^sony_ccf_client\s+\d+\s+\d+\s+.*\bLive\b',raw,re.M)
    rows=re.findall(rb'^(?:\[\s*\d+(?:\.\d+)?\]\s*)?NATIVE_CCF_CLOCK: id=(\d+) rate=(\d+) before=(\d+) enabled=(\d+) after=(\d+)\s*$',raw,re.M)
    assert [tuple(int(v) for v in row) for row in rows]==[(i,rate,0,1,0) for i,rate in EXPECTED]
    nodes=fdt_nodes((a.run/'output/virt.dtb').read_bytes());clock=nodes['/sony-test-scu/clock-controller@0'];scu=nodes['/sony-test-scu']
    assert clock['compatible']==b'cxd,900xx-clock\0' and clock['syscon']==scu['phandle']
    handle=struct.unpack('>I',clock['phandle'])[0]
    pairs=struct.unpack('>14I',nodes['/sony-test-ccf-consumer']['clocks'])
    assert pairs==tuple(v for i,_ in EXPECTED for v in (handle,i))
    trace=(a.run/'native-ccf-client-mmio.log').read_bytes();events=[]
    for m in re.finditer(rb"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-pcie-scu-region0'",trace):
        events.append(tuple(int(v,16) if n<2 else int(v) for n,v in enumerate(m.groups())))
    for ident,_ in EXPECTED:
        address,mask=(0xf1388080,1<<(ident-61)) if ident>=62 else (0xf1388030,1<<(ident-11))
        setting=(address+4,mask,4);clearing=(address+8,mask,4)
        assert setting in events and clearing in events and events.index(setting)<events.index(clearing)
    for label in ('gate30','gate80'):
        text=(a.run/('native-ccf-'+label+'.txt')).read_text();values=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[1]);assert len(values)==1 and int(values[0],16)==0
    token='NATIVE_CCF_CPU_RESUMED_'+a.run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (a.run/'native-ccf-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    review={'status':'PASS_ORIGINAL_CCF_SEVEN_PCIE_CLOCKS_ONLY','binary_sha256':digest,'client_sha256':sha,
        'original_provider_and_consumer_binding_verified':True,'original_clock_api_rows':[(i,rate,0,1,0) for i,rate in EXPECTED],
        'actual_gate_set_clear_sequences':7,'gate30_and_gate80_final_zero':True,
        'unparented_rate_api_zero_is_not_physical_frequency':True,
        'trace_sha256':hashlib.sha256(trace).hexdigest(),'cpu_resumed_and_owned_vm_exited':True,
        'soc_host_phy_link_or_dma_or_capture_verified':False}
    (HERE.parent/'native-ccf-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS original provider/7normal APIs/rates and real gate status/writes/disable; NO SoC host/PHY/DMA/frame')


if __name__=='__main__':main()
