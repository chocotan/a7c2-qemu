#!/usr/bin/env python3
"""Independent replay of the original PCI DMA transfer run: data/IRQ/callback/engines."""
import argparse
import hashlib
import json
from pathlib import Path
import re
HERE=Path(__file__).resolve().parent
PATTERN=bytes((i*29+7)&0xff for i in range(256))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);p.add_argument('run',type=Path);a=p.parse_args()
    r=json.loads((a.run/'result.json').read_text());proof=json.loads((a.candidate/'build-proof.json').read_text())
    digest=hashlib.sha256((a.candidate/'build/qemu-system-aarch64').read_bytes()).hexdigest()
    assert digest==proof['binary_sha256']==r['candidate_binary_sha256']
    assert r['ok'] and r['vm_exited'] and not r['retained_no_force_kill'] and not r.get('cleanup_error')
    assert r['native_pcidma_transfer_verified'] and r['dma_executed'] and not r['capture_verified']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE.parent/'hardware'/name).read_bytes()).hexdigest()==sha
    console=(a.run/'console.log').read_bytes().replace(b'\r',b'')
    assert not re.search(rb'WARNING: CPU:|Kernel panic|BUG:|Oops:|Unable to handle kernel|Internal error:',console)
    client=(a.run/'native-pcidma-client.txt').read_bytes().replace(b'\r',b'')
    rows=re.findall(rb'^(?:\[\s*\d+(?:\.\d+)?\]\s*)?NATIVE_PCIDMA_(CONNECT|CALLBACK|WRITE_DONE|PASS):([^\n]*)$',client,re.M)
    assert [x[0] for x in rows]==[b'CONNECT',b'CALLBACK',b'WRITE_DONE',b'CALLBACK',b'PASS']
    assert b'status=0' in rows[1][1] and b'status=0' in rows[3][1]
    m=re.search(rb'peer_bar=(\d+)',rows[0][1]);assert m and hex(int(m.group(1)))==r['native_pcidma_peer_bar0']
    peer=(a.run/'native-pcidma-peer-ram.txt').read_text()
    words=[int(v,16) for v in re.findall(r'0x([0-9a-fA-F]{8})',peer)]
    assert len(words)==64 and b''.join(w.to_bytes(4,'little') for w in words)==PATTERN
    counts=r['native_pcidma_irq198_counts'];assert counts[1]>=counts[0]+2
    assert r['native_pcidma_engine_state']==[1,1,0,0]
    trace=(a.run/'native-pcidma-mmio.log').read_bytes()
    # Original driver programmed channel context and rang the doorbell on the real engine.
    writes=re.findall(rb"memory_region_ops_write .*?addr 0x(f7380[0-9a-f]{3}) value 0x([0-9a-f]+) size 4 name 'sony-edma-registers'",trace)
    assert writes,'no engine register writes by original driver in trace slice'
    doorbells=[v for v in writes if v[0] in (b'f7380010',b'f7380030')]
    assert doorbells,'no doorbell write (write +0x10 / read +0x30) in trace'
    assert not re.search(rb"Invalid (?:read|write)[^\n]*region 'sony-edma-registers'",trace)
    token='NATIVE_PCIDMA_CPU_RESUMED_'+a.run.name.replace('-','_')
    assert ('\n'+token+'\n').encode() in (a.run/'native-pcidma-cpu-resumed.txt').read_bytes().replace(b'\r',b'')
    review={'status':'PASS_ORIGINAL_PCI_DMA_WRITE_READBACK_256B','binary_sha256':digest,
        'client_sha256':r['native_pcidma_client_sha256'],'peer_bar0':r['native_pcidma_peer_bar0'],
        'irq198_counts':counts,'engine_state_enabled_idle_status_cleared':[1,1,0,0],
        'peer_ram_pattern_verified':True,'guest_roundtrip_verified':True,
        'engine_writes_in_trace':len(writes),'doorbell_writes':len(doorbells),
        'lli_or_concurrent_or_large_frame_or_camera_path_verified':False}
    (HERE.parent/'native-pcidma-transfer-validation.json').write_text(json.dumps(review,indent=2)+'\n')
    print('MAIN_PASS original pcidma_connect+transfer_async 256B write+read-back, real IRQ/callback, data verified guest+QEMU; NO camera/LLI claim')

if __name__=='__main__':main()
