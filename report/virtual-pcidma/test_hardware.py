#!/usr/bin/env python3
"""Actual bounded PCI DMA transactions/GIC on a TEST peer; no original driver."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

HERE=Path(__file__).resolve().parent
DMA=HERE.parent/'virtual-dma330'
sys.path.insert(0,str(DMA))
from admission import idle_lock
spec=importlib.util.spec_from_file_location('edma_qtest_machine',DMA/'sony-pl330/test_hardware.py')
hardware=importlib.util.module_from_spec(spec); spec.loader.exec_module(hardware)
B=0xf7380000
AP_SOURCE,AP_DEST,LIST=0x410010000,0x410020000,0x410030000
PEER=0x600000000
IRQ=198
GIC=0x08000000
PENDING=GIC+0x200+4*(IRQ//32)
BIT=1<<(IRQ%32)


def address(machine,register,value):
    machine.writel(B+register,value&0xffffffff); machine.writel(B+register+4,value>>32)


def prepare(machine,direction,ch,linked=False):
    status=0xa0 if direction else 0x4c
    channel=0x200+direction*0x100+ch*0x200
    machine.writel(B+status+12,0xffffffff)
    machine.writel(B+status+8,0xffffffff)
    machine.writel(GIC+0x280+4*(IRQ//32),BIT)
    assert not machine.readl(PENDING)&BIT, 'previous IRQ line/pending did not clear'
    machine.writel(B+(0x2c if direction else 0xc),1)
    machine.writel(B+(0x168 if direction else 0x128)+ch*4,1)
    machine.writel(B+channel,0x300 if linked else 8)
    return status,channel


def check_irq(machine,status,ch,abort=False):
    expected=1<<(ch+(16 if abort else 0))
    assert machine.readl(B+status)==expected
    assert not machine.readl(PENDING)&BIT, 'masked DMA interrupt reached GIC'
    machine.writel(B+status+8,0)
    assert machine.readl(PENDING)&BIT, 'actual GIC pending missing'
    machine.writel(B+status+12,expected)
    assert machine.readl(B+status)==0
    machine.writel(GIC+0x280+4*(IRQ//32),BIT)
    assert not machine.readl(PENDING)&BIT, 'W1C did not deassert the level IRQ'


def exercise(machine,direction,ch,linked=False):
    status,c=prepare(machine,direction,ch,linked)
    payload=bytes((i*37+ch*13+direction*71+linked*19)&255 for i in range(256))
    if direction:
        machine.write(PEER+16,payload); machine.write(AP_DEST,b'\xa5'*288)
        source,target=0x04000010,AP_DEST+16; observed=AP_DEST
    else:
        machine.write(AP_SOURCE,payload); machine.write(PEER,b'\xa5'*288)
        source,target=AP_SOURCE,0x04000010; observed=PEER
    if linked:
        program=struct.pack('<IIQQ',9,256,source,target)+struct.pack('<IIQQ',6,0,LIST,0)
        machine.write(LIST,program); address(machine,c+0x1c,LIST)
    else:
        machine.writel(B+c+8,256); address(machine,c+0xc,source); address(machine,c+0x14,target)
    machine.writel(B+(0x30 if direction else 0x10),ch)
    assert machine.read(observed,288)==b'\xa5'*16+payload+b'\xa5'*16
    assert machine.read(PEER+16 if direction else AP_SOURCE,256)==payload
    assert machine.readl(B+c)&0x60==0x60
    check_irq(machine,status,ch)
    return {'direction':direction,'channel':ch,'linked':linked,'bytes':256,
            'guards_and_source_verified':True,'gic_irq':IRQ,'mask_w1c_and_deassert_verified':True}


def fault(machine,kind):
    status,c=prepare(machine,0,0,kind=='descriptor')
    machine.write(PEER,b'\xa5'*4096); machine.write(AP_SOURCE,bytes(range(256)))
    if kind=='descriptor':
        address(machine,c+0x1c,0x7f0000000000)
    else:
        machine.writel(B+c+8,256)
        address(machine,c+0xc,0x7f0000000000 if kind=='source' else AP_SOURCE)
        address(machine,c+0x14,0x10004000000 if kind=='target' else 0x04000010)
    machine.writel(B+0x10,0)
    assert machine.read(PEER,4096)==b'\xa5'*4096, 'fault mutated/truncated to valid peer'
    check_irq(machine,status,0,abort=True)
    return {'kind':kind,'abort_not_done':True,'peer_unchanged':True,'gic_and_ack_verified':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('candidate',type=Path)
    args=parser.parse_args(); stage=args.candidate.resolve(); binary=stage/'build/qemu-system-aarch64'
    proof=json.loads((stage/'build-proof.json').read_text())
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==proof['binary_sha256']
    output=Path(tempfile.mkdtemp(prefix='pcidma-qtest-',dir='/var/tmp'))
    print('PCIDMA_HARDWARE_OUTPUT',output,flush=True)
    result={'scope':'explicit TEST peer; no PCI enumeration/link/CP/original driver/CMOS',
            'binary_sha256':proof['binary_sha256'],'hardware_verified':False,'requests':[],'faults':[]}
    try:
        with idle_lock(HERE.parents[1]/'runtime/analysis/.menu-probe.lock'):
            for enabled in (False,True):
                run=output/('enabled' if enabled else 'disabled'); run.mkdir()
                machine=hardware.Machine(binary,run,False,atu_test=True,edma_test=enabled)
                try:
                    machine.connect()
                    tree=machine.qmp('human-monitor-command',{'command-line':'info qtree'})
                    (run/'qtree.txt').write_text(tree)
                    assert ('dev: sony-virtual-pcidma,' in tree)==enabled
                    if not enabled:continue
                    machine.writel(GIC,1)
                    machine.writel(GIC+0x100+4*(IRQ//32),BIT)
                    for direction in (0,1):
                        for ch in range(8):result['requests'].append(exercise(machine,direction,ch))
                        result['requests'].append(exercise(machine,direction,0,linked=True))
                    for kind in ('descriptor','source','target'):result['faults'].append(fault(machine,kind))
                finally:
                    machine.close()
        result['hardware_verified']=True
        print('PCIDMA_HARDWARE_PASS: 16 direct + 2 LLI, actual bytes/guards/GIC, 3 faults/abort, W1C',flush=True)
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
