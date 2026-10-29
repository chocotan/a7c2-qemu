#!/usr/bin/env python3
"""Expected-frontier evidence: original probe passes TEST lane gate, then aborts at the first unmodeled DBI read."""
import hashlib
import json
import re
import time

RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'
PC_BASE=0xffffff8008080000
DBI_READ=(0x245ea0,0x245f20)
TIMED_LOAD_PC=0x245c90  # dw_pcie_read.part.0+0x50: inner timed helper's actual `ldr w1,[x0]`

def check(qmp,run,console,result):
    raw=console.read_bytes().replace(b'\r',b'')
    assert b'PCI0: PHY ready in ' in raw,'probe did not pass the TEST lane gate'
    assert b'PCI0: PHY SRAM timeout' not in raw and b'PCI0: handover' not in raw
    assert b'Unhandled fault: synchronous external abort' in raw and b'Internal error' in raw
    m=re.search(rb'pc : \[<([0-9a-f]+)>\]',raw);assert m,'missing fault PC'
    pc=int(m.group(1),16)-PC_BASE
    fa=re.search(rb'Unhandled fault: synchronous external abort \(0x[0-9a-f]+\) at 0x([0-9a-f]+)',raw)
    assert fa,'missing fault address'
    fault_va=int(fa.group(1),16)
    (run/'native-frontier-console.txt').write_text('phy_ready=1\npc_raw=0x%x\nfault_va=0x%x\n'%(pc,fault_va))
    assert pc==TIMED_LOAD_PC or DBI_READ[0]<=pc<DBI_READ[1],'fault PC outside original DBI read path: 0x%x'%pc
    assert fault_va&0xfff==0x8bc,'fault address is not DBI+0x8bc: 0x%x'%fault_va
    trace=(run/'output/boot-trace.log').read_text(errors='replace')
    assert not re.search(r"Invalid (?:read|write)[^\n]*region 'test-phy-init-region\d+'",trace),\
        'validity-layer rejection inside PHY regions'
    qmp('stop')
    try:
        deadline=time.monotonic()+10
        while qmp('query-status')['running']:
            assert time.monotonic()<deadline,'owned VM did not pause'
            time.sleep(.05)
        props={key:qmp('qom-get',{'path':'/machine/sony-pcie-scu-test','property':key}) for key in
            ('last-accepted-words','last-image-matches','completed-clear-jobs','ready-read-before-upload',
             'apply-after-upload','dbi-accesses','rejected-accesses','lane-status','link-status')}
        (run/'native-frontier-properties.json').write_text(json.dumps(props,indent=2)+'\n')
        assert props['completed-clear-jobs']==1 and props['last-accepted-words']==4096
        assert props['last-image-matches']==1 and props['ready-read-before-upload']==1 and props['apply-after-upload']==1
        assert props['lane-status']==0,'lane must be calibrated before the DBI stage'
        assert props['link-status']==0,'LTSSM enable happens after the faulted DBI read; link must stay down'
        assert props['dbi-accesses']==1 and props['rejected-accesses']==1,'expected exactly one rejected DBI read'
        text=qmp('human-monitor-command',{'command-line':'xp /8192bx 0x602000000'})
        (run/'native-frontier-upload-hmp.txt').write_text(text)
        data=bytearray()
        for line in text.splitlines():
            if ':' in line:data.extend(int(v,16) for v in re.findall(r'0x([0-9a-fA-F]{2})\b',line.split(':',1)[1]))
        assert len(data)==8192 and hashlib.sha256(data).hexdigest()==RAW_SHA
        (run/'native-frontier-upload-raw.bin').write_bytes(data)
        engines=[]
        for offset,label in ((0xc,'write'),(0x2c,'read')):
            text=qmp('human-monitor-command',{'command-line':'xp /1wx 0x%x'%(0xf7380000+offset)})
            (run/('native-frontier-engine-'+label+'.txt')).write_text(text)
            words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(words)==1;engines.append(int(words[0],16))
        assert engines==[0,0]
    finally:
        pass  # Panicked guest: no CPU-resume claim, no cont; runner performs owned QMP quit.
    result.update(native_phy_frontier_verified=True,native_phy_ready_passed=True,
        native_frontier_fault_pc_raw=pc,native_sram_upload_verified=True,
        native_phy_sram_raw_sha256=RAW_SHA,native_phy_engines=engines,dbi_model_present=False,
        native_of_host_success=False,original_silicon_init_producer_verified=False)
