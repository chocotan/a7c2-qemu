#!/usr/bin/env python3
"""Passive original boot-init/IRQ observation. Never connects or submits work."""
import re

IRQS=(198,200,202,204,206)
SCU_BASES=(0xf1388080,0xf1388310,0xf11e0380,0xf1160380,0xf11a0380,0xf1220380,0xf1120380)


def scu_sequence_verified(trace):
    events=[]
    for m in re.finditer(r"memory_region_ops_write .*?addr 0x([0-9a-f]+) value 0x([0-9a-f]+) size (\d+) name 'test-pcie-scu-region([0-6])'",trace):
        address,value,size,index=m.groups();address=int(address,16);index=int(index)
        if address<12:address+=SCU_BASES[index]
        events.append((address,int(value,16),int(size)))
    for index,(hbit,rbit) in enumerate(zip((1,7,13,19,25),(3,11,7,15,19))):
        wanted=((0xf1388084,1<<hbit,4),(0xf1388318,1<<rbit,4),
            (SCU_BASES[index+2],0x10,4),(0xf1388088,1<<hbit,4))
        cursor=0
        for event in events:
            if event==wanted[cursor]:
                cursor+=1
                if cursor==len(wanted):break
        if cursor!=len(wanted):return False
    return True


def installed_irqs(raw):
    clean=raw.replace(b'\r',b'')
    return [irq for irq in IRQS if re.search(rb'^\s*'+str(irq).encode()+
        rb':\s+\d+\s+GIC-0\s+'+str(irq).encode()+rb'\s+(?:Level|Edge)\s+PCIeDMAC\s*$',clean,re.M)]


def observe(qmp,serial_command,run,proc,console,result):
    raw=console.read_bytes().replace(b'\r',b'')
    if re.search(rb'WARNING: CPU:|Kernel panic|BUG:',raw):
        raise ValueError('Kernel warning/fault during native initialization; preserve partial IRQ evidence')
    with_pcie=result.get('native_pcie_udif_boot_init_requested',False)
    if with_pcie:
        assert b'blacklisting initcall __boottime___udif_init_udif_pcie' not in raw
        assert re.search(rb'initcall __boottime___udif_init_udif_pcie\+[^\n]*returned 0 ',raw)
    else:assert b'blacklisting initcall __boottime___udif_init_udif_pcie' in raw
    assert b'blacklisting initcall __boottime___udif_init_pcidma' not in raw
    assert re.search(rb'calling\s+__boottime___udif_init_pcidma\+',raw)
    assert re.search(rb'initcall __boottime___udif_init_pcidma\+[^\n]*returned 0 ',raw)
    command=('if true; then\necho NATIVE_PCIDMA_IRQS_BEGIN\ncat /proc/interrupts\n'
        'echo NATIVE_PCIDMA_IRQS_END\nfi\ntrue')
    observed=serial_command(proc,console,command,timeout=15)
    (run/'native-pcidma-irqs.txt').write_bytes(observed)
    rows=installed_irqs(observed);result['native_pcidma_irq_rows']=rows
    if rows!=list(IRQS):raise ValueError('Not all five real PCIeDMAC IRQ rows installed')
    if with_pcie:
        command=('if true; then\nfor i in 0 1 2 3 4; do\n'
            'if test -d /proc/driver/pcie/$i && test -e /proc/driver/pcie/$i/dma; then\n'
            'echo PCIE_PROC_ENTRY_$i\nfi\ndone\nfi\ntrue')
        observed=serial_command(proc,console,command,timeout=15)
        (run/'native-pcie-proc-paths.txt').write_bytes(observed)
        for i in range(5):assert ('\nPCIE_PROC_ENTRY_'+str(i)+'\n').encode() in observed.replace(b'\r',b'')
        result['native_pcie_proc_paths_verified']=True
        trace=(run/'output/boot-trace.log').read_text(errors='replace')
        if not scu_sequence_verified(trace):raise ValueError('Missing actual native SCU/reset/wrapper write sequences')
        result['native_pcie_scu_sequence_verified']=True
    qmp('stop')
    try:
        assert not qmp('query-status')['running']
        values=[]
        for offset,label in ((0xc,'write'),(0x2c,'read')):
            text=qmp('human-monitor-command',{'command-line':f'xp /1wx 0x{0xf7380000+offset:x}'})
            (run/('native-engine-'+label+'.txt')).write_text(text)
            words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(words)==1
            values.append(int(words[0],16))
        result['native_pcidma_observed_engines']=values
        if values!=[0,0]:raise ValueError('Unexpected engine enable without restored host initialization')
        if with_pcie:
            state={name:qmp('qom-get',{'path':'/machine/sony-pcie-scu-test','property':name})
                for name in ('hclk','apb-reset','wrapper0','wrapper1','wrapper2','wrapper3','wrapper4')}
            if state!={'hclk':0,'apb-reset':0,**{'wrapper'+str(i):0x10 for i in range(5)}}:
                raise ValueError('Native PCIe UDIF did not complete actual SCU/wrapper transitions')
            result['native_pcie_scu_final_state']=state
    finally:qmp('cont')
    token='NATIVE_PCIDMA_INIT_CPU_RESUMED_'+run.name.replace('-','_')
    observed=serial_command(proc,console,'echo '+token,timeout=15)
    (run/'native-pcidma-init-cpu-resumed.txt').write_bytes(observed)
    assert ('\n'+token+'\n').encode() in observed.replace(b'\r',b'')
    result['native_pcidma_boot_init_verified']=True
    result['native_pcidma_init_cpu_resumed']=True
