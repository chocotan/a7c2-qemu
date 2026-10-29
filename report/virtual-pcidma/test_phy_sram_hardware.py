#!/usr/bin/env python3
"""Actual QEMU SRAM transactions/hash/readback with clock/reset gates; NO PHY-ready or native host."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

HERE=Path(__file__).resolve().parent
PRODUCT=HERE.parents[1]
DMA=HERE.parent/'virtual-dma330'
sys.path.insert(0,str(DMA))
from admission import idle_lock
spec=importlib.util.spec_from_file_location('pl330_qtest',DMA/'sony-pl330/test_hardware.py')
machine_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(machine_module)
IMAGE_SHA='620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
RAW_SHA='6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95'
STREAM_SHA='963669fdc92d57141fa41095ecd7c5a1b972162d2e699a702ebfc8b6c1ef64dc'
DATA=0xf11d8000
CTRL=0xf11e00ac
OWNER='/machine/sony-phy-sram-test'


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);a=p.parse_args()
    candidate=a.candidate.resolve();binary=candidate/'build/qemu-system-aarch64'
    proof=json.loads((candidate/'build-proof.json').read_text());digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    assert proof['binary_sha256']==digest and 'qemu_phy_sram.c' in proof['model_source_sha256']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE/'hardware'/name).read_bytes()).hexdigest()==sha
    image=(PRODUCT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert len(image)==6610952 and hashlib.sha256(image).hexdigest()==IMAGE_SHA
    raw=image[0x4601c0:0x4621c0];assert len(raw)==8192 and hashlib.sha256(raw).hexdigest()==RAW_SHA
    stream=b''.join(struct.pack('<I',v) for v in struct.unpack('<4096H',raw));assert hashlib.sha256(stream).hexdigest()==STREAM_SHA
    run=Path(tempfile.mkdtemp(prefix='phy-sram-qtest-',dir='/var/tmp'));print('PHY_SRAM_QTEST_RUN',run,flush=True)
    result={'scope':'TEST gated SRAM storage/authentication only; INIT_DONE always zero, no native host/PHY/link',
            'binary_sha256':digest,'raw_sha256':RAW_SHA,'stream_sha256':STREAM_SHA,'verified':False}
    with idle_lock(PRODUCT/'runtime/analysis/.menu-probe.lock'):
        for enabled in (False,True):
            root=run/('enabled' if enabled else 'disabled');root.mkdir()
            m=machine_module.Machine(binary,root,True,pci_peer_test=True,scu_test=enabled,ccf_test=enabled,phy_sram_test=enabled)
            try:
                m.connect();tree=m.qmp('human-monitor-command',{'command-line':'info qtree'});(root/'qtree.txt').write_text(tree)
                if not enabled:assert 'dev: a7c2-test-phy-sram,' not in tree;continue
                assert 'dev: a7c2-test-phy-sram,' in tree
                m.qmp('trace-event-set-state',{'name':'memory_region_ops_write','enable':True})
                m.qmp('trace-event-set-state',{'name':'memory_region_ops_read','enable':True})
                def prop(name):return m.qmp('qom-get',{'path':OWNER,'property':name})
                def save(name):
                    values={key:prop(key) for key in ('accepted-words','image-matches','apply-seen','input-sha256')}
                    values['control']=m.readl(CTRL);(root/(name+'-properties.json')).write_text(json.dumps(values,indent=2)+'\n')
                def restart():
                    m.qmp('system_reset');assert prop('accepted-words')==0 and prop('image-matches')==0
                    assert m.readl(CTRL)==0
                    m.writel(0xf1388084,0x3e);m.writel(0xf1388318,0xf)
                # Real closed clocks/APB reset deny data; acceptance count does not change.
                m.writel(DATA,1);assert prop('accepted-words')==0
                restart();m.writel(CTRL,2)
                assert prop('apply-seen')==1 and prop('image-matches')==0 and m.readl(CTRL)==2
                save('empty-apply')
                restart();m.write(DATA,stream);assert prop('accepted-words')==4096
                assert m.read(DATA,len(stream))==stream
                m.writel(CTRL,2);assert prop('image-matches')==1 and prop('input-sha256')==RAW_SHA
                assert m.readl(CTRL)==2 and not m.readl(CTRL)&4
                save('positive')
                (root/'positive-readback.bin').write_bytes(m.read(DATA,len(stream)))
                # Any write after apply invalidates the prior match rather than preserving stale success.
                m.writel(DATA,0);assert prop('image-matches')==0 and prop('input-sha256')==''
                save('late-write')
                restart();bad=bytearray(stream);bad[0]^=1;m.write(DATA,bad);m.writel(CTRL,2)
                assert prop('accepted-words')==4096 and prop('image-matches')==0 and prop('input-sha256')!=RAW_SHA
                save('altered')
                restart();m.write(DATA,stream[:-4]);m.writel(CTRL,2)
                assert prop('accepted-words')==4095 and prop('image-matches')==0
                save('missing-zero')
                restart();m.writel(DATA+4,0);assert prop('accepted-words')==0
                restart();m.writel(DATA,0x10000);assert prop('accepted-words')==0
                restart();m.writel(0xf1388314,1);m.writel(DATA,1);assert prop('accepted-words')==0
                restart();m.writel(0xf1388088,0x20);m.writel(DATA,1);assert prop('accepted-words')==0
                result.update(verified=True,original_table_positive=True,observed_dwords=4096,
                    altered_content_rejected=True,missing_last_zero_rejected=True,closed_clock_reset_rejected=True,
                    init_done_advertised=False,native_firmware_or_host_executed=False)
            finally:m.close()
    (run/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
