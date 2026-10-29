#!/usr/bin/env python3
"""Explicit TEST timed SRAM clear job, not silicon producer recovery or calibrated PHY."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from test_phy_sram_hardware import HERE,PRODUCT,idle_lock,machine_module,IMAGE_SHA,RAW_SHA,STREAM_SHA

DATA=0xf11d8000;CTRL=0xf11e00ac;OWNER='/machine/sony-pcie-scu-test'

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('candidate',type=Path);a=p.parse_args()
    candidate=a.candidate.resolve();binary=candidate/'build/qemu-system-aarch64';proof=json.loads((candidate/'build-proof.json').read_text())
    digest=hashlib.sha256(binary.read_bytes()).hexdigest();assert digest==proof['binary_sha256'] and 'qemu_phy_init.c' in proof['model_source_sha256']
    for name,sha in proof['model_source_sha256'].items():assert hashlib.sha256((HERE/'hardware'/name).read_bytes()).hexdigest()==sha
    image=(PRODUCT/'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin').read_bytes()
    assert hashlib.sha256(image).hexdigest()==IMAGE_SHA
    raw=image[0x4601c0:0x4621c0];assert hashlib.sha256(raw).hexdigest()==RAW_SHA
    stream=b''.join(struct.pack('<I',v) for v in struct.unpack('<4096H',raw));assert hashlib.sha256(stream).hexdigest()==STREAM_SHA
    run=Path(tempfile.mkdtemp(prefix='phy-init-qtest-',dir='/var/tmp'));print('PHY_INIT_QTEST_RUN',run,flush=True)
    result={'scope':'Explicit TEST SRAM clearing policy only, no recovered silicon producer/lane/link/native host','verified':False,'binary_sha256':digest}
    with idle_lock(PRODUCT/'runtime/analysis/.menu-probe.lock'):
        for enabled in (False,True):
            root=run/('enabled' if enabled else 'disabled');root.mkdir()
            m=machine_module.Machine(binary,root,True,pci_peer_test=True,scu_test=enabled,ccf_test=enabled,phy_init_test=enabled)
            try:
                m.connect();tree=m.qmp('human-monitor-command',{'command-line':'info qtree'});(root/'qtree.txt').write_text(tree)
                if not enabled:assert 'dev: a7c2-test-scu-phy-init,' not in tree;continue
                assert 'dev: a7c2-test-scu-phy-init,' in tree
                # Shared Machine uses -S. qtest dummy vCPUs execute no guest code,
                # but resume is needed to enable QEMU_CLOCK_VIRTUAL timers.
                m.qmp('cont');assert m.qmp('query-status')['running']
                m.qmp('trace-event-set-state',{'name':'memory_region_ops_write','enable':True})
                m.qmp('trace-event-set-state',{'name':'memory_region_ops_read','enable':True})
                def prop(key):return m.qmp('qom-get',{'path':OWNER,'property':key})
                def step(n=1):
                    for _ in range(n):m.qtest('clock_step 1000')
                def start():
                    m.writel(0xf1388084,0x3e);m.writel(0xf1388318,8);m.writel(CTRL,0)
                    assert m.readl(CTRL)==0
                    m.writel(0xf1388318,7)
                assert prop('reset1')==0x8888f and not prop('completed-clear-jobs')
                start();m.writel(CTRL,4);assert m.readl(CTRL)==0 # readonly bit2 echo cannot force completion
                assert m.readl(DATA)==0xffff
                step();assert m.read(DATA,256)==bytes(256) and m.readl(DATA+256)==0xffff and not m.readl(CTRL)&4
                (root/'partial-clear.bin').write_bytes(m.read(DATA,16384))
                step(62);assert not m.readl(CTRL)&4 and prop('completed-clear-jobs')==0
                step();assert m.readl(CTRL)==4 and prop('completed-clear-jobs')==1 and prop('last-cleared-words')==4096
                assert m.read(DATA,16384)==bytes(16384)
                (root/'full-clear.bin').write_bytes(m.read(DATA,16384))
                m.write(DATA,stream);m.writel(CTRL,6)
                assert prop('last-accepted-words')==4096 and prop('last-image-matches')==1 and prop('last-input-sha256')==RAW_SHA
                assert m.read(0x602000000,8192)==raw
                (root/'uploaded-raw-readback.bin').write_bytes(m.read(0x602000000,8192))
                values={key:prop(key) for key in ('completed-clear-jobs','last-cleared-words','last-accepted-words','last-image-matches','last-input-sha256','ready-read-before-upload','apply-after-upload')}
                assert values['ready-read-before-upload']==1 and values['apply-after-upload']==1
                (root/'positive-properties.json').write_text(json.dumps(values,indent=2)+'\n')
                m.writel(0xf11e0380,0x1f0003);assert m.readl(0xf11e038c)==15 and m.readl(0xf11e01b8)==0
                # Original dw_pcie_set_Mode(RC): W+201ac keeps ~0xf0 and sets 4<<4; bit8 rejected.
                m.writel(0xf11e01ac,0x40);assert m.readl(0xf11e01ac)==0x40
                m.writel(0xf11e01ac,0x100);assert m.readl(0xf11e01ac)==0x40
                (root/'not-ready.json').write_text(json.dumps({'lane_status':m.readl(0xf11e038c),'link_status':m.readl(0xf11e01b8)})+'\n')
                # Explicit TEST calibration: authentic applied payload + IDDQ cleared + inputs held.
                step(100);assert m.readl(0xf11e038c)==15 and m.readl(0xf11e01b8)==0 # powerdown still set
                m.writel(0xf11e0018,0) # original IDDQ/PHY_POWERDOWN clear
                step(15);assert m.readl(0xf11e038c)==15 and m.readl(0xf11e01b8)==0
                step();assert m.readl(0xf11e038c)==0 and m.readl(0xf11e01b8)==0 # no link without LTSSM
                m.writel(0xf11e01ac,0x44) # RC mode field + LTSSM enable; TEST peer present in profile
                step(7);assert m.readl(0xf11e01b8)==0
                step();assert m.readl(0xf11e01b8)==2 and prop('lane-status')==0 and prop('link-status')==2
                (root/'calibrated.json').write_text(json.dumps({'lane_status':0,'link_status':2,'core_control':m.readl(0xf11e01ac)})+'\n')
                # Real DBI window: root-port config alias under original RO-write license.
                assert m.read(0xf7000000,4)==struct.pack('<I',0x000c1b36) # real GPEX root port IDs
                m.write(0xf7000000,struct.pack('<H',0x104d))
                assert m.read(0xf7000000,4)==struct.pack('<I',0x000c1b36) # locked: unchanged
                w0=m.readl(0xf11e0380);m.writel(0xf11e0380,w0&~0x40) # wrapper bit6 clear
                m.writel(0xf70008bc,1) # DBI RO-write enable
                m.write(0xf7000000,struct.pack('<H',0x104d));m.write(0xf7000002,struct.pack('<H',0x911d))
                assert m.read(0xf7000000,4)==struct.pack('<I',0x911d104d)
                m.writel(0xf70008bc,0);m.writel(0xf11e0380,w0) # original ro_wr_dis order
                m.writel(0xf7000104,0xffffffff);assert m.readl(0xf7000104)==0 # AER W1C clear/check
                # Viewport region1 type4 -> real peer config; absent BDF reads all-ones.
                for off,val in ((0x900,1),(0x90c,0xdffc0000),(0x910,0),(0x914,0xdffcffff),
                                (0x918,0x01000000),(0x91c,0),(0x904,4),(0x908,0x80000000)):
                    m.writel(0xf7000000+off,val)
                assert m.readl(0xf7000908)&0x80000000
                assert m.read(0xdffc0000,4)==struct.pack('<I',0x00051b36)
                m.writel(0xf7000918,0x01100000) # bus1 dev2 fn0: absent
                assert m.read(0xdffc0000,4)==b'\xff\xff\xff\xff'
                assert m.readl(0xf11e01b8)==2 # config traffic never disturbs link
                # Sideband interrupt enables: pinned masks, clear-reread-set helpers.
                m.writel(0xf11e0274,0x78ffff);assert m.readl(0xf11e0274)==0x78ffff
                m.writel(0xf11e0278,0x04000000);assert m.readl(0xf11e0278)==0x04000000
                m.writel(0xf11e0274,0x10000);assert m.readl(0xf11e0274)==0x78ffff # outside-mask bit rejected
                # Sideband status: no event source modeled, reads 0, clear-back stores 0.
                assert m.readl(0xf11e026c)==0 and m.readl(0xf11e0270)==0
                m.writel(0xf11e026c,0);m.writel(0xf11e0270,0)
                assert m.readl(0xf11e026c)==0 and m.readl(0xf11e0270)==0
                # MSI INT0 enable/mask/status: no MSI source, all read 0, clear-back stores.
                for off in (0x828,0x82c,0x830):
                    assert m.readl(0xf7000000+off)==0
                    m.writel(0xf7000000+off,0);assert m.readl(0xf7000000+off)==0
                # Port Logic RMW storage: lane-mode/width+speed/L1-timeout fields.
                m.writel(0xf7000710,0x70000);assert m.readl(0xf7000710)==0x70000
                m.writel(0xf7000710,0x400000);assert m.readl(0xf7000710)==0x70000 # bit22 outside mask rejected
                m.writel(0xf700080c,0x400);assert m.readl(0xf700080c)==0x400
                m.writel(0xf700080c,0);m.writel(0xf700080c,0x20000);assert m.readl(0xf700080c)==0x20000
                m.writel(0xf7000890,0);assert m.readl(0xf7000890)==0
                m.writel(0xf7000890,2);assert m.readl(0xf7000890)==0 # bit1 rejected
                (root/'dbi.json').write_text(json.dumps({'root_ids':'0x911d104d','peer_ids':'0x00051b36','absent_read':'0xffffffff','aer_status_after_clear':0})+'\n')
                # Failure/suspend can reset SRAM; the separate readonly history keeps only actual accepted data.
                m.writel(0xf1388314,1);assert not m.readl(CTRL)&4 and m.read(0x602000000,8192)==raw
                assert m.readl(0xf11e038c)==15 and m.readl(0xf11e01b8)==0 # calibration/link drop with power
                m.qmp('system_reset');start();step();m.writel(0xf1388088,0x20);step(100)
                assert not m.readl(CTRL)&4 and prop('completed-clear-jobs')==0
                (root/'clock-loss.json').write_text(json.dumps({'control':m.readl(CTRL),'completed_jobs':prop('completed-clear-jobs')})+'\n')
                m.writel(0xf1388084,0x20);step(100);assert not m.readl(CTRL)&4 # needs a fresh cold reset after loss
                m.writel(0xf1388314,1);m.writel(0xf1388318,1);step(64);assert m.readl(CTRL)==4
                for change in ('bypass','apb-reset'):
                    m.qmp('system_reset');start();step()
                    if change=='bypass':m.writel(CTRL,1)
                    else:m.writel(0xf1388314,8)
                    step(100);assert not m.readl(CTRL)&4 and not prop('completed-clear-jobs')
                    if change=='bypass':m.writel(CTRL,0)
                    else:m.writel(0xf1388318,8)
                    step(100);assert not m.readl(CTRL)&4 and not prop('completed-clear-jobs')
                    (root/('midway-'+change+'.json')).write_text(json.dumps({'control':m.readl(CTRL),'completed_jobs':prop('completed-clear-jobs')})+'\n')
                m.qmp('system_reset');start();step();m.qmp('system_reset');step(100)
                assert prop('completed-clear-jobs')==0 and prop('last-cleared-words')==0
                (root/'reset-pending.json').write_text(json.dumps({'completed_jobs':prop('completed-clear-jobs'),'last_cleared':prop('last-cleared-words')})+'\n')
                m.qmp('system_reset');start();m.writel(CTRL,2);step(64)
                assert m.readl(CTRL)==6 and prop('last-image-matches')==0 and prop('last-accepted-words')==0
                m.writel(DATA,1);m.writel(CTRL,6)
                assert prop('last-image-matches')==0 and prop('last-accepted-words')==0
                (root/'early-apply.json').write_text(json.dumps({'completed_jobs':prop('completed-clear-jobs'),'last_match':prop('last-image-matches'),'last_count':prop('last-accepted-words'),'last_sha':prop('last-input-sha256')})+'\n')
                m.qmp('system_reset');m.writel(0xf1388084,0x3e);m.writel(0xf1388318,15) # bypass remains selected
                step(100);assert not m.readl(CTRL)&4 and not prop('completed-clear-jobs')
                (root/'bypass.json').write_text(json.dumps({'control':m.readl(CTRL),'completed_jobs':prop('completed-clear-jobs')})+'\n')
                rejected=prop('rejected-accesses');m.readl(0xf7000920);m.readl(0xf7300000)
                assert prop('rejected-accesses')==rejected+2 # unknown core offsets/unrolled iATU still reject
                result.update(verified=True,real_bounded_clear_and_negative_controls=True,actual_uploaded_word_count=4096,
                    raw_sha256=RAW_SHA,readback_snapshot_survives_suspend_reset=True,lane_calibrated=False,link_up=False,
                    test_functional_lane_link_verified=True,dbi_model_verified=True,
                    original_silicon_producer_known=False,native_probe_executed=False)
            finally:m.close()
    (run/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
