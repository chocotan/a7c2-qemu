#!/usr/bin/env python3
"""Actual QEMU SCU HCLK/APB-reset state changes, not Sony link/PHY readiness."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

HERE=Path(__file__).resolve().parent
HCLK=0xf1388080
RESET=0xf1388310
WRAPPERS=(0xf11e0380,0xf1160380,0xf11a0380,0xf1220380,0xf1120380)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path)
    p.add_argument('--ccf',action='store_true',help='extended real CCF gate/mux/divider/reset banks');a=p.parse_args()
    candidate=a.candidate.resolve();binary=candidate/'build/qemu-system-aarch64'
    proof=json.loads((candidate/'build-proof.json').read_text());digest=hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest==proof['binary_sha256'] and 'test_pcie_scu.c' in proof['model_source_sha256']
    if a.ccf:assert 'test_ccf_scu.c' in proof['model_source_sha256']
    spec=importlib.util.spec_from_file_location('machine',HERE.parent/'virtual-dma330/sony-pl330/test_hardware.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    spec=importlib.util.spec_from_file_location('gate',HERE.parent/'virtual-dma330/admission.py')
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    out=Path(tempfile.mkdtemp(prefix='pcie-scu-qtest-',dir='/var/tmp'));print('SCU_QTEST_RUN',out,flush=True)
    result={'scope':'TEST SCU two banks/five gated controls only; no native init/link/PHY','binary_sha256':digest,'verified':False}
    with gate.idle_lock(HERE.parents[1]/'runtime/analysis/.menu-probe.lock'):
        for enabled in (False,True):
            root=out/('enabled' if enabled else 'disabled');root.mkdir()
            machine=m.Machine(binary,root,True,pci_peer_test=True,scu_test=enabled,ccf_test=enabled and a.ccf)
            try:
                machine.connect();tree=machine.qmp('human-monitor-command',{'command-line':'info qtree'})
                (root/'qtree.txt').write_text(tree)
                if not enabled:
                    assert 'dev: a7c2-test-pcie-scu,' not in tree and 'dev: a7c2-test-scu-ccf,' not in tree;continue
                assert ('dev: a7c2-test-scu-ccf,' if a.ccf else 'dev: a7c2-test-pcie-scu,') in tree
                owner='/machine/sony-pcie-scu-test'
                def prop(name):return machine.qmp('qom-get',{'path':owner,'property':name})
                assert machine.readl(HCLK)==0 and machine.readl(RESET)==0x88888
                reset=0x88888
                for index,(hbit,rbit,wrapper) in enumerate(zip((1,7,13,19,25),(3,11,7,15,19),WRAPPERS)):
                    hmask=1<<hbit;rmask=1<<rbit
                    machine.writel(wrapper,0x10);assert prop('wrapper'+str(index))==0
                    machine.writel(HCLK+4,hmask);assert machine.readl(HCLK)==hmask
                    machine.writel(wrapper,0x10);assert prop('wrapper'+str(index))==0
                    machine.writel(RESET+8,rmask);reset&=~rmask;assert machine.readl(RESET)==reset
                    assert machine.readl(wrapper)==0
                    machine.writel(wrapper,0x10);assert machine.readl(wrapper)==0x10
                    machine.writel(wrapper,0x50);assert machine.readl(wrapper)==0x10
                    machine.writel(HCLK+8,hmask);assert machine.readl(HCLK)==0
                    machine.writel(wrapper,0);assert prop('wrapper'+str(index))==0x10
                assert prop('apb-reset')==0 and prop('hclk')==0
                for hbit,wrapper in zip((1,7,13,19,25),WRAPPERS):
                    machine.writel(HCLK+4,1<<hbit)
                    assert machine.readl(wrapper)==0x10
                    machine.writel(HCLK+8,1<<hbit)
                machine.writel(HCLK,0xffffffff);assert machine.readl(HCLK)==0
                machine.writel(HCLK+4,0x80000000);assert machine.readl(HCLK)==0
                machine.write(RESET+4,b'\x88\x88');assert machine.readl(RESET)==0
                machine.qmp('system_reset')
                assert machine.readl(HCLK)==0 and machine.readl(RESET)==0x88888
                assert all(prop('wrapper'+str(i))==0 for i in range(5))
                if a.ccf:
                    masks=(0x1f000,0,0x30f,0x2c000c,0x13fffc0,0xdf7c0,0,0,0x3efbefbe)
                    for i,mask in enumerate(masks):
                        address=0xf1388000+i*16
                        assert machine.readl(address)==0
                        machine.writel(address+4,mask);assert machine.readl(address)==mask
                        machine.writel(address+8,mask);assert machine.readl(address)==0
                        bad=next(1<<bit for bit in range(32) if not mask&(1<<bit))
                        machine.writel(address+4,mask|bad);assert machine.readl(address)==0
                    for offset,mask in ((0x210,0x1f000000),(0x220,0x11111),(0x230,0x3ff)):
                        address=0xf1388000+offset
                        assert machine.readl(address)==0
                        machine.writel(address+4,mask);assert machine.readl(address)==mask
                        machine.writel(address+8,mask);assert machine.readl(address)==0
                    for offset in (0x10c,0x110,0x114,0x118,0x11c):
                        address=0xf1388000+offset
                        assert machine.readl(address)==0
                        machine.writel(address,7);assert machine.readl(address)==7
                        machine.writel(address,0x107);assert machine.readl(address)==7
                        machine.writel(address,0);assert machine.readl(address)==0
                    for i in range(8):
                        address=0xf1388300+16*i;initial=0x88888 if i==1 else 0
                        assert machine.readl(address)==initial
                        machine.writel(address+4,0x80000000);assert machine.readl(address)==initial|0x80000000
                        machine.writel(address+8,0x80000000);assert machine.readl(address)==initial
                    result['ccf_banks_verified']=True
                    result['scope']='TEST CCF register banks plus real gated wrappers; no native provider/host/PHY'
                result['verified']=True;result['controllers']=5;result['virtual_reset_policy_only']=True
            finally:machine.close()
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)


if __name__=='__main__':main()
