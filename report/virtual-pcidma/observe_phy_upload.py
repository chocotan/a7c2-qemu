#!/usr/bin/env python3
"""Original probe upload under explicit functional TEST SRAM-clear policy; requires failed lane gate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('phy_upload_native_helpers',Path(__file__).with_name('observe_native_init.py'))
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
installed_irqs,IRQS=helpers.installed_irqs,helpers.IRQS

RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'
MAPPINGS=((0xf1388000,0),(0xf13882fc,0),(0xf1388300,1),(0xf138837c,1),
    (0xf11c0000,7),(0xf11d8000,7),(0xf11dbffc,7),(0xf11e00ac,7),
    (0xf11e0380,2),(0xf11e0384,8),(0xf11e038c,8),(0xf11ffffc,8),
    (0xf7000000,9),(0xf7000ffc,9),(0x602000000,10),(0x602001fff,10))

def invalid_phy_access(trace):
    return bool(re.search(r"Invalid (?:read|write)[^\n]*region 'test-phy-init-region\d+'",trace))

def model_mappings_verified(tree):
    views=[block for block in tree.split('FlatView #') if 'AS "cpu-memory-0", root: system' in block]
    if len(views)!=1:return False
    ranges=[(int(a,16),int(b,16),kind,name) for a,b,kind,name in re.findall(
        r'^\s*([0-9a-fA-F]{16})-([0-9a-fA-F]{16}) \(prio -?\d+, ([^)]*)\): (\S+)',views[0],re.M)]
    for address,index in MAPPINGS:
        covering=[(kind,name) for low,high,kind,name in ranges if low<=address<=high]
        if covering!=[('i/o','test-phy-init-region'+str(index))]:return False
    return True

def observe(qmp,serial_command,run,proc,console,result):
    raw=console.read_bytes().replace(b'\r',b'')
    if re.search(rb'WARNING: CPU:|Kernel panic|BUG:|Oops:|Unable to handle kernel|Internal error:',raw):raise ValueError('Kernel warning/fault; reject bounded original upload')
    assert result['native_invalid_mem_logging_enabled']
    if invalid_phy_access((run/'output/boot-trace.log').read_text(errors='replace')):
        raise ValueError('PHY access rejected before/inside callback; reject bounded upload despite zero callback counter')
    assert b'PCI0: handover' not in raw and b'PCI0: PHY SRAM timeout' not in raw and b'PCI0: PHY ready' not in raw
    assert re.search(rb'probe of [^\n]*sony-test-pcie0 failed with error -1',raw)
    for name in ('__boottime___udif_init_pcidma','__boottime___udif_init_udif_pcie'):
        assert re.search(rb'initcall '+name.encode()+rb'\+[^\n]*returned 0 ',raw)
    observed=serial_command(proc,console,'cat /proc/interrupts\ntrue',timeout=15)
    (run/'native-phy-irqs.txt').write_bytes(observed);assert installed_irqs(observed)==list(IRQS)
    observed=serial_command(proc,console,
        'for p in /sys/bus/platform/devices/*sony-test-pcie0; do\n'
        'if test -d "$p"; then\ncat "$p/modalias"\n'
        'if test -e "$p/driver"; then echo NATIVE_PHY_BOUND=1; else echo NATIVE_PHY_BOUND=0; fi\nfi\ndone\ntrue',timeout=15)
    (run/'native-phy-platform.txt').write_bytes(observed)
    # modalias has no trailing newline: result is glued after 'Csnps,dw-pcie'.
    # Match the result at line END instead of line start; the echoed command
    # contains 'NATIVE_PHY_BOUND=1;' (semicolon), never '=1\n'.
    clean=observed.replace(b'\r',b'')
    assert b'Csnps,dw-pcie' in clean and b'NATIVE_PHY_BOUND=0\n' in clean and b'NATIVE_PHY_BOUND=1\n' not in clean
    qmp('stop')
    try:
        assert not qmp('query-status')['running']
        tree=qmp('human-monitor-command',{'command-line':'info mtree -f'})
        (run/'native-phy-mtree.txt').write_text(tree)
        assert model_mappings_verified(tree)
        props={key:qmp('qom-get',{'path':'/machine/sony-pcie-scu-test','property':key}) for key in
            ('last-accepted-words','last-image-matches','completed-clear-jobs','last-cleared-words',
             'last-input-sha256','rejected-accesses','dbi-accesses','hclk','reset1',
             'ready-read-before-upload','apply-after-upload')}
        (run/'native-phy-properties.json').write_text(json.dumps(props,indent=2)+'\n')
        assert props['last-accepted-words']==4096 and props['last-image-matches']==1 and props['last-input-sha256']==RAW_SHA
        assert props['ready-read-before-upload']==1 and props['apply-after-upload']==1
        assert props['completed-clear-jobs']==1 and props['last-cleared-words']==4096
        assert props['rejected-accesses']==props['dbi-accesses']==0
        text=qmp('human-monitor-command',{'command-line':'xp /8192bx 0x602000000'})
        (run/'native-phy-upload-hmp.txt').write_text(text)
        data=bytearray()
        for line in text.splitlines():
            if ':' in line:data.extend(int(v,16) for v in re.findall(r'0x([0-9a-fA-F]{2})\b',line.split(':',1)[1]))
        assert len(data)==8192 and hashlib.sha256(data).hexdigest()==RAW_SHA
        (run/'native-phy-upload-raw.bin').write_bytes(data)
        engines=[]
        for offset,label in ((0xc,'write'),(0x2c,'read')):
            text=qmp('human-monitor-command',{'command-line':f'xp /1wx 0x{0xf7380000+offset:x}'})
            (run/('native-phy-engine-'+label+'.txt')).write_text(text)
            words=re.findall(r'0x([0-9a-fA-F]+)',text.split(':',1)[-1]);assert len(words)==1;engines.append(int(words[0],16))
        assert engines==[0,0]
    finally:qmp('cont')
    token='NATIVE_PHY_UPLOAD_CPU_RESUMED_'+run.name.replace('-','_')
    resumed=serial_command(proc,console,'echo '+token,timeout=15);(run/'native-phy-cpu-resumed.txt').write_bytes(resumed)
    assert ('\n'+token+'\n').encode() in resumed.replace(b'\r',b'')
    result.update(native_sram_upload_verified=True,native_of_probe_expected_lane_failure=True,
        native_phy_sram_raw_sha256=RAW_SHA,native_phy_upload_cpu_resumed=True,native_phy_engines=engines,
        test_sram_clear_policy_used=True,original_silicon_init_producer_verified=False,native_of_host_success=False)
