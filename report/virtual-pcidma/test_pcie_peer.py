#!/usr/bin/env python3
"""Real PCIe config/BAR/bridge consumption on a TEST function, not Sony PHY."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from test_hardware import hardware, idle_lock, prepare, check_irq, address
from test_hardware import AP_SOURCE, AP_DEST, B, PEER, GIC, IRQ, BIT

HERE=Path(__file__).resolve().parent
ECAM=0x3f000000
PORT=ECAM+0x8000
ENDPOINT=ECAM+0x100000
BAR=0x10000000
DBI=0xf7000000
WRAPPER=0xf11c0000


def check_dbi(m):
    pointer=m.readl(PORT+0x34)&255;seen=set();cap=0
    while pointer and len(seen)<48:
        assert pointer not in seen;seen.add(pointer)
        header=m.readl(PORT+pointer)
        if header&255==0x10:cap=pointer;break
        pointer=header>>8&255
    assert cap
    slot=cap+0x14
    old=m.readl(PORT+slot);different=old^(1<<19)
    assert m.readl(DBI)==m.readl(PORT)
    assert m.readl(DBI+0x8bc)==0 and m.readl(WRAPPER+0x20380)==0x40
    m.writel(DBI+slot,different);assert m.readl(PORT+slot)==old
    m.writel(DBI+0x8bc,1)
    m.writel(DBI+slot,different);assert m.readl(PORT+slot)==old
    m.writel(WRAPPER+0x20380,0)
    m.writel(DBI+slot,different);assert m.readl(PORT+slot)==different
    flags=m.read(PORT+cap+2,2)
    changed=(int.from_bytes(flags,'little')^0x100).to_bytes(2,'little')
    m.write(DBI+cap+2,changed);assert m.read(PORT+cap+2,2)==changed
    m.write(DBI+cap+2,flags);m.writel(DBI+slot,old)
    m.writel(DBI+0x8bc,0);m.writel(WRAPPER+0x20380,0x40)
    m.writel(DBI+slot,different);assert m.readl(PORT+slot)==old
    assert m.read(PORT+cap+2,2)==flags
    return {'capability':hex(cap),'actual_slot_flags_and_caps_changed':True,
            'locked_or_control_disabled_prevents_ro_write':True,'restored_and_relocked':True}


def transfer(m,read=False):
    status,c=prepare(m,int(read),0)
    m.writel(B+c+8,256)
    address(m,c+0xc,BAR+16 if read else AP_SOURCE)
    address(m,c+0x14,AP_DEST+16 if read else BAR+16)
    m.writel(B+(0x30 if read else 0x10),0)
    return status


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('candidate',type=Path)
    parser.add_argument('--dbi',action='store_true',help='test explicit bounded Root DBI RO-write compatibility window')
    args=parser.parse_args(); binary=args.candidate.resolve()/'build/qemu-system-aarch64'
    receipt=args.candidate/'pci-hardware-build.json'
    if not receipt.is_file():receipt=args.candidate/'build-proof.json'
    proof=json.loads(receipt.read_text())
    assert hashlib.sha256(binary.read_bytes()).hexdigest()==proof['binary_sha256']
    output=Path(tempfile.mkdtemp(prefix='pcie-peer-qtest-',dir='/var/tmp'))
    print('PCIE_PEER_OUTPUT',output,flush=True)
    result={'scope':'actual QEMU GPEX/rootport/RAM BAR TEST peer; no original Sony PHY or kernel API/CP',
            'binary_sha256':proof['binary_sha256'],'hardware_verified':False,'capture_verified':False}
    try:
        with idle_lock(HERE.parents[1]/'runtime/analysis/.menu-probe.lock'):
            for enabled in (False,True):
                run=output/('enabled' if enabled else 'disabled');run.mkdir()
                m=hardware.Machine(binary,run,False,pci_peer_test=enabled,low_ecam=True,dbi_test=args.dbi and enabled)
                try:
                    m.connect()
                    tree=m.qmp('human-monitor-command',{'command-line':'info qtree'})
                    (run/'qtree.txt').write_text(tree)
                    assert ('dev: a7c2-test-pcie-peer,' in tree)==enabled
                    assert ('dev: a7c2-test-root-dbi,' in tree)==(args.dbi and enabled)
                    if not enabled:continue
                    m.writel(GIC,1);m.writel(GIC+0x100+4*(IRQ//32),BIT)
                    assert m.readl(PORT)&0xffff==0x1b36
                    if args.dbi:result['dbi_compatibility']=check_dbi(m)
                    m.writel(PORT+0x18,0x00010100) # real secondary/subordinate bus config
                    m.writel(PORT+0x20,0x10f01000) # real 10000000..10ffffff bridge window
                    m.writel(PORT+4,6)
                    identity=m.readl(ENDPOINT)
                    assert identity==0x00051b36
                    cap=m.readl(ENDPOINT+0x34)&255
                    assert cap==0x70 and m.readl(ENDPOINT+cap)&255==0x10
                    m.writel(ENDPOINT+0x10,0xffffffff)
                    mask=m.readl(ENDPOINT+0x10)&0xfffffff0
                    assert mask==0xff000000
                    m.writel(ENDPOINT+0x10,BAR)
                    result.update(identity=hex(identity),capability=hex(cap),bar_mask=hex(mask))
                    payload=bytes((i*31+17)&255 for i in range(256))
                    m.write(AP_SOURCE,payload);m.write(PEER,b'\xa5'*4096)
                    # Config-visible function alone must NOT make its BAR decode.
                    status=transfer(m)
                    assert m.read(PEER,4096)==b'\xa5'*4096
                    check_irq(m,status,0,abort=True)
                    result['disabled_bar_aborts']=True
                    m.writel(ENDPOINT+4,6)
                    status=transfer(m)
                    expected=b'\xa5'*16+payload+b'\xa5'*(4096-272)
                    assert m.read(PEER,4096)==expected and m.read(BAR,4096)==expected
                    check_irq(m,status,0)
                    result['actual_bar_write_and_cpu_read']=True
                    other=bytes((i*47+29)&255 for i in range(256))
                    m.write(BAR+16,other);m.write(AP_DEST,b'\xa5'*288)
                    status=transfer(m,read=True)
                    assert m.read(AP_DEST,288)==b'\xa5'*16+other+b'\xa5'*16
                    assert m.read(PEER+16,256)==other
                    check_irq(m,status,0)
                    result['cpu_bar_write_and_actual_dma_read']=True
                    before=m.read(PEER,4096)
                    m.writel(ENDPOINT+4,0)
                    status=transfer(m)
                    assert m.read(PEER,4096)==before
                    check_irq(m,status,0,abort=True)
                    result['disable_command_rejects_data']=True
                    m.writel(ENDPOINT+4,6)
                    m.writel(PORT+0x20,0x0000fff0) # empty bridge memory window
                    status=transfer(m)
                    assert m.read(PEER,4096)==before
                    check_irq(m,status,0,abort=True)
                    result['closed_bridge_rejects_data']=True
                    result['peer_page_sha256']=hashlib.sha256(before).hexdigest()
                finally:m.close()
        result['hardware_verified']=True
        print('PCIE_PEER_PASS: actual ECAM/BAR size/commands/bridge gates, bidirectional DMA+GIC/guards; NO original kernel/Sony PHY/CP',flush=True)
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error);raise
    finally:(output/'result.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
