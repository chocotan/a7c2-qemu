#!/usr/bin/env python3
"""One paired device regression: real QEMU transactions, no original AP/CP software."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import struct
import time
import traceback

HERE=Path(__file__).resolve().parent
QtestTransportError=runpy.run_path(str(HERE/'check-notify-qemu.py'))['QtestTransportError']
AP_DDR=0x400000000
CP_GIC=0xf13a1000
AP_GIC=0x08000000
KEY_LAYOUT=((6,3),(6,4),(7,18),(7,19),(7,20),(11,20),(17,9),(17,12),(17,18),
            (7,17),(11,9),(11,18),(11,27))


def need(value,message):
    if not value:raise ValueError(message)


def blob(machine,address,data):
    need(0<len(data)<=256,'Bounded component write')
    machine.qtest(f'write {address:#x} {len(data):#x} 0x{data.hex()}')


def bytes_at(machine,address,length):
    need(0<length<=256,'Bounded component read')
    response=machine.qtest(f'read {address:#x} {length:#x}')
    if (not isinstance(response,list) or len(response)!=1 or not isinstance(response[0],str) or
            not re.fullmatch(r'0x[0-9a-fA-F]{'+str(2*length)+'}',response[0])):
        raise QtestTransportError('Malformed qtest byte response: '+repr(response))
    return bytes.fromhex(response[0][2:])


def word64(machine,address,value):
    machine.write(address,value&0xffffffff);machine.write(address+4,value>>32)


def irq(machine,number):
    base=AP_GIC if machine.side=='ap' else CP_GIC
    return bool(machine.read(base+0x200+4*(number//32))&(1<<(number%32)))


def clear_irq(machine,number):
    base=AP_GIC if machine.side=='ap' else CP_GIC
    machine.write(base+0x280+4*(number//32),1<<(number%32))


def setup_irq(machine,number,edge=False):
    base=AP_GIC if machine.side=='ap' else CP_GIC
    machine.write(base,1)
    machine.qtest(f'writeb {base+0x800+number:#x} 0x1')
    address=base+0xc00+(number//16)*4;shift=2*(number%16)
    value=machine.read(address)&~(3<<shift)
    machine.write(address,value|((2 if edge else 0)<<shift))
    machine.write(base+0x100+4*(number//32),1<<(number%32))
    clear_irq(machine,number)


def wait_value(machine,address,expected,mask=0xffffffff):
    deadline=time.monotonic()+5
    while True:
        if machine.read(address)&mask==expected&mask:return
        need(time.monotonic()<deadline,'Peer output was not consumed')
        time.sleep(.01)


def rejected(machine,address,marker):
    logfile=machine.out/(machine.side+'.stderr');offset=logfile.stat().st_size
    machine.read(address)
    text=logfile.read_bytes()[offset:].decode(errors='replace')
    need(marker in text and re.search(r'result=[1-9][0-9]*|result=-[1-9][0-9]*',text),
         'No actual rejected MMIO evidence: '+text[-2000:])
    return dict(address=hex(address),raw_log=text)


def connected(ap,cp):
    deadline=time.monotonic()+5
    while True:
        if all('op=receive ' in (m.out/(m.side+'.stderr')).read_text(errors='replace') for m in (ap,cp)):return
        need(time.monotonic()<deadline,'Both valid peer snapshots were not received')
        ap.command('query-status');cp.command('query-status');time.sleep(.01)


def gpio(ap,cp):
    output_pins=(1<<9)|(1<<8)
    initial_out=ap.read(0xf102f010);initial_wdata=ap.read(0xf102f040)
    need(initial_out&output_pins==initial_wdata&output_pins,'Native AP output RDATA must follow its own local WDATA latch')
    rows=[]
    for m,n in ((ap,92),(ap,91),(cp,290),(cp,289)):
        setup_irq(m,n,True);need(not irq(m,n),'Initial snapshot manufactured a doorbell')
    cases=((ap,cp,9,0xf102e010,4,290),(ap,cp,8,0xf102d010,4,289),
           (cp,ap,3,0xf102e010,16,92),(cp,ap,2,0xf102e010,8,91))
    for sender,receiver,pin,address,value,number in cases:
        for high in (True,False):
            clear_irq(receiver,number)
            sender.write(0xf102f044 if high else 0xf102f048,1<<pin)
            wait_value(receiver,address,value if high else 0,mask=value)
            deadline=time.monotonic()+5
            while not irq(receiver,number):
                need(time.monotonic()<deadline,'Real GPIO transition did not reach GIC pending')
                receiver.command('query-status');time.sleep(.01)
            if sender.side=='ap':
                rdata=sender.read(0xf102f010);wdata=sender.read(0xf102f040)
                need(rdata&output_pins==wdata&output_pins,'AP native output readback diverged from its own latch')
            rows.append(dict(source=sender.side,pin=pin,high=high,intid=number,input_value=value if high else 0,
                             input_mask=value,input_word=receiver.read(address)))
            clear_irq(receiver,number)
    cp.write(0xf102e028,4)
    denial=rejected(cp,0xf102e010,'AP_CP_GPIO')
    ap.write(0xf102f044,1<<9);time.sleep(.02)
    need(not irq(cp,290),'Input-disabled wire manufactured IRQ')
    cp.write(0xf102e024,4);wait_value(cp,0xf102e010,4,mask=4)
    need(not irq(cp,290),'Input re-enable manufactured a retrospective edge')
    ap.write(0xf102f048,1<<9);wait_value(cp,0xf102e010,0,mask=4);clear_irq(cp,290)
    cp.write(0xf102e004,4);direction=rejected(cp,0xf102e010,'AP_CP_GPIO');cp.write(0xf102e008,4)
    ap.write(0xf102f008,1<<9);output_readback_denial=rejected(ap,0xf102f010,'AP_CP_GPIO');ap.write(0xf102f004,1<<9)
    return dict(edges=rows,input_gating_rejected=denial,output_direction_rejected=direction,
                ap_output_readback=dict(initial_rdata=initial_out,initial_wdata=initial_wdata,
                                        gated_input_denied=output_readback_denial,known_output_mask=output_pins),
                initial_snapshot_not_edge=True,reenable_not_edge=True,physical_edge_encoding_verified=False)


def keyboard(cp):
    bases={port:0xf101d000+port*0x1000 for port in (6,7,11,17)}
    masks={port:sum(1<<pin for p,pin in KEY_LAYOUT if p==port) for port in bases}
    baseline={port:cp.read(base+0x10) for port,base in bases.items()}
    need(all(baseline[p]&masks[p]==masks[p] for p in bases),'Virtual key producer did not drive released-high snapshot')
    rows=[]
    cp.command('cont')
    try:
        need(cp.command('query-status').get('running') is True,'Qtest run state did not allow real key events')
        for index,(port,pin) in enumerate(KEY_LAYOUT,1):
            qcode='f'+str(index);base=bases[port];bit=1<<pin
            for down in (True,False):
                cp.command('input-send-event',{'events':[{'type':'key','data':{'down':down,'key':{'type':'qcode','data':qcode}}}]})
                expected=baseline[port]&~bit if down else baseline[port]
                wait_value(cp,base+0x10,expected)
                actual=cp.read(base+0x10)
                need(actual==expected,'Virtual key changed unrelated GPIO input bits')
                need(not irq(cp,290) and not irq(cp,289),'Key input manufactured an AP/CP doorbell')
                rows.append(dict(qcode=qcode,port=port,pin=pin,down=down,input_word=actual))
    finally:
        cp.command('stop')
    need(cp.command('query-status').get('running') is False,'Qtest key fixture did not stop')
    base=bases[6];bit=1<<3
    need(not cp.read(base+0x40)&bit and cp.read(base+0x10)&bit,'RDATA was aliased to WDATA')
    denials={}
    for name,off in (('input_disabled',0x20),('peripheral_selected',0x30)):
        cp.write(base+off+8,bit);denials[name]=rejected(cp,base+0x10,'CP_KEY_GPIO');cp.write(base+off+4,bit)
    cp.write(base+4,bit);denials['output_direction']=rejected(cp,base+0x10,'CP_KEY_GPIO');cp.write(base+8,bit)
    # Pin6 has no input producer; enabling it cannot invent a level.
    cp.write(base+0x24,1<<6);cp.write(base+0x34,1<<6)
    denials['unconnected_pin']=rejected(cp,base+0x10,'CP_KEY_GPIO')
    cp.write(base+0x28,1<<6);cp.write(base+0x38,1<<6)
    denials['unknown_register']=rejected(cp,base+0x0c,'CP_KEY_GPIO')
    need(cp.read(base+0x10)==baseline[6],'GPIO key configuration did not restore')
    return dict(profile='virtual-cp-key-gpio-v1',transitions=rows,denials=denials,
                auxiliary_virtual_switches=4,physical_key_names_verified=False,physical_polarity_verified=False,
                rdata_not_wdata=True,irq_generated=False)


def keyboard_reset(cp):
    address=0xf102e010;bit=1<<9
    before=cp.read(address)
    need(before&bit,'Virtual F7 source must be released before reset regression')
    cp.command('cont')
    try:
        cp.command('input-send-event',{'events':[{'type':'key','data':{'down':True,'key':{'type':'qcode','data':'f7'}}}]})
        wait_value(cp,address,before&~bit)
        pressed=cp.read(address)
    finally:
        cp.command('stop')
    cp.command('system_reset')
    words={}
    for port in (6,7,11,17):
        mask=sum(1<<pin for p,pin in KEY_LAYOUT if p==port)
        target=0xf101d010+port*0x1000
        wait_value(cp,target,mask,mask=mask)
        words[str(port)]=cp.read(target)
    return dict(pressed_before_reset=pressed,reset_key_input_words=words,
                source_reset_policy='virtual panel resets to released; receiver alone does not clear external drive',
                cold_reset_order_independent=True,physical_reset_verified=False)


def direct(machine,direction,channel,source,target,length,*,llp=None):
    base=0xf7380000 if machine.side=='ap' else 0xf6780000
    status=0x4c if direction==0 else 0xa0
    cfg=0x200+channel*0x200+direction*0x100
    machine.write(base+status+12,0x10001<<channel)
    machine.write(base+(0xc if direction==0 else 0x2c),1)
    machine.write(base+(0x128 if direction==0 else 0x168)+channel*4,1)
    machine.write(base+status+8,0)
    machine.write(base+cfg,0x300 if llp is not None else 8)
    if llp is None:
        machine.write(base+cfg+8,length);word64(machine,base+cfg+0xc,source);word64(machine,base+cfg+0x14,target)
    else:word64(machine,base+cfg+0x1c,llp)
    machine.write(base+(0x10 if direction==0 else 0x30),channel)
    return base,status,cfg


def dma(ap,cp):
    rows=[];cp.write(0xf11e0274,0xffff)
    setup_irq(ap,198);setup_irq(cp,403)
    for group in range(4):
        offset=0x03f80000+group*0x20000
        own_ap=b'A'*32;own_cp=b'C'*32
        blob(ap,AP_DDR+offset,own_ap);blob(cp,offset,own_cp)
        need(bytes_at(ap,AP_DDR+offset,32)==own_ap and bytes_at(cp,offset,32)==own_cp,'Local rings share backing')
        for sender,receiver,source,target,source_address,target_address in (
            (ap,cp,AP_DDR+offset,AP_DDR+offset+0x2000,AP_DDR+offset,offset+0x2000),
            (cp,ap,offset,0x800000000+offset+0x2000,offset,AP_DDR+offset+0x2000)):
            payload=bytes((group*47+i*29+(sender.side=='ap'))&255 for i in range(32))
            blob(sender,source_address,payload);blob(receiver,target_address-16,b'\xa5'*64)
            base,status,cfg=direct(sender,0,group,source,target,32)
            need(sender.read(base+status)&(1<<group),'No real eDMA completion')
            need(irq(sender,198 if sender.side=='ap' else 403),'eDMA completion did not reach IRQ')
            need(bytes_at(receiver,target_address-16,64)==b'\xa5'*16+payload+b'\xa5'*16,'eDMA ring bytes/guards differ')
            need(bytes_at(sender,source_address,32)==payload,'eDMA modified source')
            sender.write(base+status+12,1<<group)
            need(not irq(sender,198 if sender.side=='ap' else 403),'eDMA IRQ did not clear with actual status')
            rows.append(dict(sender=sender.side,group=group,bytes=32,sha256=hashlib.sha256(payload).hexdigest(),guards=True))
    # Read-direction body aliases differ from the outgoing ring aliases.
    for sender,peer,remote,peer_address,local in (
        (ap,cp,0x24000,0x24000,AP_DDR+0x25000),
        (cp,ap,AP_DDR+0x26000,AP_DDR+0x26000,0x27000)):
        payload=bytes(range(64));blob(peer,peer_address,payload);blob(sender,local-16,b'\x6a'*96)
        base,status,_=direct(sender,1,7,remote,local,64)
        need(sender.read(base+status)&128,'Read-direction completion absent')
        need(bytes_at(sender,local-16,96)==b'\x6a'*16+payload+b'\x6a'*16,'Body pull/guards differ')
        sender.write(base+status+12,128)
    # Actual native-style linked-list consumer: data node then phase-changing link.
    payload=bytes(range(32))
    blob(ap,AP_DDR+0x28000,payload);blob(cp,0x29000-16,b'\x55'*64)
    descriptor=AP_DDR+0x2a000
    nodes=struct.pack('<IIQQ',9,32,AP_DDR+0x28000,AP_DDR+0x29000)+struct.pack('<IIQQ',6,0,descriptor,0)
    blob(ap,descriptor,nodes)
    base,status,_=direct(ap,0,0,0,0,0,llp=descriptor)
    need(ap.read(base+status)==1 and bytes_at(cp,0x29000,32)==payload,'LLP did not copy actual data')
    ap.write(base+status+12,1)
    # A 64-bit unassigned target must abort rather than truncate to the valid low address.
    blob(cp,0x29000,b'\x33'*32)
    base,status,_=direct(ap,0,0,AP_DDR+0x28000,0x1000400029000,32)
    need(ap.read(base+status)==0x10000,'Unassigned 64-bit target did not produce abort-only status')
    need(bytes_at(cp,0x29000,32)==b'\x33'*32,'Bad high address was truncated or modified sentinel')
    ap.write(base+status+12,0x10000)
    return dict(rings=rows,independent_local_backing=True,body_pull_both_directions=True,llp_actual_bytes=True,
                upper_address_abort_not_truncated=True,original_uipc_ack_generated=False)


def p1_spi_component(ap,cp):
    base=0xf1017000
    expected=(0x22,0x10,0x04,0x00,0x0d,0xf0,0x05,0xb1)
    ids=tuple(ap.read(base+0xfe0+4*i) for i in range(8))
    need(ids==expected, 'Pinned upstream PL022 peripheral ID differs')
    ap.write(base,0x0f);ap.write(base+4,2);ap.write(base+8,0x1234)
    need(ap.read(base+0x0c)&4, 'PL022 did not deliver receive FIFO data')
    observed=ap.read(base+8)
    need(observed==0, 'No-peer PL022 unexpectedly returned nonzero data')
    offset=0x01000000;length=24*1024*1024
    ap.qtest(f'memset {AP_DDR+offset:#x} {length:#x} 0x5a')
    cp.qtest(f'memset {offset-16:#x} {length+32:#x} 0x33')
    dma_base,status,_=direct(ap,0,0,AP_DDR+offset,AP_DDR+offset,length)
    need(ap.read(dma_base+status)&1,'P1 24MiB DMA did not complete')
    need(bytes_at(cp,offset-16,16)==b'\x33'*16 and
         bytes_at(cp,offset+length,16)==b'\x33'*16,'P1 24MiB DMA changed guard bytes')
    source_hash=hashlib.sha256();target_hash=hashlib.sha256()
    for name,position,digest in (('ap-ram.bin',15*1024**3+offset,source_hash),
                                 ('cp-ram.bin',offset,target_hash)):
        fd=os.open(ap.pair/name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            before=os.fstat(fd)
            for at in range(0,length,1024*1024):
                block=os.pread(fd,min(1024*1024,length-at),position+at)
                need(len(block)==min(1024*1024,length-at),'P1 DMA backing read was short')
                digest.update(block)
            after=os.fstat(fd)
            need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                 (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
                 'P1 DMA backing changed during readback')
        finally:os.close(fd)
    expected_hash=hashlib.sha256()
    for _ in range(24):expected_hash.update(b'\x5a'*(1024*1024))
    need(source_hash.digest()==target_hash.digest()==expected_hash.digest(),
         'P1 24MiB DMA full readback differs from the intended source')
    dma_base,status,_=direct(ap,0,0,AP_DDR+offset,AP_DDR+offset,length+1)
    need(ap.read(dma_base+status)&0x10000,'P1 DMA above 24MiB did not abort')
    need(bytes_at(cp,offset-16,16)==b'\x33'*16 and
         bytes_at(cp,offset+length,16)==b'\x33'*16,'Rejected P1 DMA changed guards')
    rejected_hash=hashlib.sha256()
    fd=os.open(ap.pair/'cp-ram.bin',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        before=os.fstat(fd)
        for at in range(0,length,1024*1024):
            block=os.pread(fd,min(1024*1024,length-at),offset+at)
            need(len(block)==min(1024*1024,length-at),'Rejected P1 DMA readback was short')
            rejected_hash.update(block)
        after=os.fstat(fd)
        need((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
             (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),
             'P1 DMA target changed during rejected-transfer readback')
    finally:os.close(fd)
    need(rejected_hash.digest()==target_hash.digest(),'Rejected P1 DMA changed target bytes')
    ap.write(dma_base+status+12,0x10001)
    return dict(profile='virtual-p1-pl022-component-v1',base=hex(base),peripheral_id=list(ids),
                no_peer_receive=observed,dma_bytes=length,dma_full_sha256=target_hash.hexdigest(),
                over_budget_aborted=True,bootrom_protocol_verified=False,
                original_driver_binding_verified=False,physical_compatible=False)


def dfs_transactions(cp):
    dfs=0xf1388f48
    cp.write(dfs+4,0x101)
    if cp.command('query-status').get('running') is not False:
        raise QtestTransportError('CP DFS fixture must start paused')
    running=False
    try:
        cp.command('cont');running=True
        if cp.command('query-status').get('running') is not True:
            raise QtestTransportError('CP DFS virtual clock did not start')
        for target in (0x102,3):
            cp.write(dfs,0x101)
            need(not (cp.read(dfs+16)&0x100),'CP DFS set busy before trigger')
            cp.write(dfs+12,target);cp.write(dfs+8,1)
            need(cp.read(dfs+16)&0x100,'CP DFS did not enter virtual busy')
            cp.qtest('clock_step 1000000')
            need(cp.read(dfs)==1 and cp.read(dfs+16)==(target&0xff),
                 'CP DFS virtual completion/readback differs')
    finally:
        if running:
            cp.command('stop')
            if cp.command('query-status').get('running') is not False:
                raise QtestTransportError('CP DFS fixture did not restore paused state')


def scu_i2c(cp):
    cp.write(0xf1388070,0x80000001);cp.write(0xf1388074,0x10);cp.write(0xf1388078,1)
    need(cp.read(0xf1388070)==0x80000010,'SCU truncated full32bit latch');cp.write(0xf1388070,0)
    rows=[]
    for bank in range(5):
        base=0xf1012000+bank*0x1000;clock=1<<(18+bank);reset=1<<(24+bank);number=429+bank
        cp.write(0xf1388054,clock)
        need(cp.read(base+0xfc)==0x44570140,'Upstream I2C component type differs')
        setup_irq(cp,number)
        cp.write(base+0x30,0);cp.write(base,0x65);cp.write(base+4,0x50)
        cp.write(base+0x6c,1);need(cp.read(base+0x9c)&1,'I2C enable not consumed')
        cp.write(base+0x30,1<<6);cp.write(base+0x10,0xab)
        need(cp.read(base+0x34)&(1<<6) and cp.read(base+0x80),'Empty I2C bus did not return actual NACK/abort')
        need(irq(cp,number),'I2C abort did not reach its real IRQ')
        cp.read(base+0x54);need(not irq(cp,number),'I2C actual clear did not release IRQ')
        cp.write(base+0x6c,0);need(cp.read(base+0x9c)==0,'I2C disable status remained enabled')
        cp.write(base+0x6c,1);cp.write(0xf1388354,reset)
        held=rejected(cp,base+0x9c,'CP_SCU');cp.write(0xf1388358,reset)
        need(cp.read(base+0x9c)==0,'I2C reset did not clear actual engine')
        cp.write(0xf1388058,clock);gated=rejected(cp,base+0xfc,'CP_SCU')
        cp.write(0xf1388054,clock)
        rows.append(dict(bank=bank,intid=number,nack=True,reset_rejection=held,clock_rejection=gated))
    dfs_transactions(cp)
    return dict(full_32bit_latch=True,banks=rows,forced_slave_ack=False,
                cp_dfs_sync_and_async_virtual=True,cp_dfs_physical_compatible=False)


def tpu_watchdog(cp):
    cp.write(0xf13883a0,1);cp.write(0xf1052004,0xff);cp.write(0xf1052000,1)
    need(cp.read(0xf1052000)==1,'Original watchdog did not enable')
    before=cp.read(0xf1052008);rows=[]
    for bank in range(6):
        base=0xf100b000+bank*0x1000;bit=1<<(20+bank)
        cp.write(0xf1388044,1<<bank)
        cp.qtest(f'writew {base+0x18:#x} {0x200+bank:#x}')
        need(cp.read(base+0x18)==0x200+bank,'TPU configuration not stored')
        cp.write(0xf1388344,bit);held=rejected(cp,base+0x18,'CP_TPU')
        need(cp.read(0xf1052000)==1 and cp.read(0xf1052004)==0xff,'TPU reset changed watchdog registers')
        cp.write(0xf1388348,bit);need(cp.read(base+0x18)==0,'TPU reset did not clear own configuration')
        cp.qtest('clock_step 1000000')
        rows.append(dict(bank=bank,reset_rejection=held))
    after=cp.read(0xf1052008)
    need(0<after<before,'TPU reset stopped or reset the original watchdog counter')
    cp.qtest('writew 0xf100b02c 0x1');runtime=rejected(cp,0xf100b010,'CP_TPU')
    cp.write(0xf1388344,1<<18)
    need(cp.read(0xf1052000)==0 and cp.read(0xf1052004)==0,'Original WDT reset bit18 was not delegated')
    cp.write(0xf1388348,1<<18);need(cp.read(0xf13883a0)==1,'WDT_MISC original state was shadowed')
    return dict(tpu=rows,watchdog_count_before=before,watchdog_count_after=after,
                watchdog_semantics_preserved=True,active_tpu_status_rejected=runtime,tpu_runtime_supported=False)


def pl080(cp):
    rows=[]
    for controller in range(2):
        base=0xf1058000+controller*0x1000
        cp.write(base+0x30,1);cp.write(base+0x34,0)
        for channel in range(8):
            source=0x40000+controller*0x4000+channel*0x100;destination=source+0x8000
            payload=bytes((i*17+controller*41+channel)&255 for i in range(64))
            blob(cp,source,payload);blob(cp,destination-16,b'\x9a'*96)
            number=378+controller*8+channel;setup_irq(cp,number)
            c=base+0x100+channel*0x20
            cp.write(c,source);cp.write(c+4,destination);cp.write(c+8,0)
            cp.write(c+12,16|(2<<18)|(2<<21)|(1<<26)|(1<<27)|(1<<31))
            cp.write(c+16,1|(1<<14)|(1<<15))
            need(bytes_at(cp,destination-16,96)==b'\x9a'*16+payload+b'\x9a'*16,'PL080 actual bytes/guard differ')
            need(cp.read(base+4)&(1<<channel) and irq(cp,number),'PL080 per-channel TC/IRQ missing')
            cp.write(base+8,1<<channel);need(not irq(cp,number),'PL080 real TC clear did not release channel IRQ')
            rows.append(dict(controller=controller,channel=channel,intid=number,sha256=hashlib.sha256(payload).hexdigest()))
    return dict(channels=rows,scu_reset_route_verified=False,peripheral_handshake_verified=False,bus_error_irq_verified=False)


def pl330(cp):
    helper=runpy.run_path(str(HERE.parents[1]/'report/virtual-dma330/sony-pl330/test_hardware.py'))
    rows=[]
    for controller in range(2):
        base=0xf1056000+controller*0x1000;source=0x60000+controller*0x4000;destination=source+0x1000;code=source+0x2000
        payload=bytes((i*29+controller*71)&255 for i in range(256))
        for event in range(8):
            number=312+controller*33+event;setup_irq(cp,number)
            blob(cp,source,payload);blob(cp,destination-16,b'\xa5'*128);blob(cp,destination+112,b'\xa5'*128);blob(cp,destination+240,b'\xa5'*32)
            blob(cp,code,helper['microcode'](source,destination,event))
            cp.write(base+0x20,1<<event);cp.write(base+0xd08,0xa0<<16);cp.write(base+0xd0c,code);cp.write(base+0xd04,0)
            for _ in range(100):
                cp.qtest('clock_step 10000')
                if cp.read(base+0x28)&(1<<event) and cp.read(base+0x100)&15==0:break
            need(cp.read(base+0x100)&15==0 and cp.read(base+0x34)&1==0 and cp.read(base+0x40)==0 and cp.read(base+0x38)==0,
                 'PL330 program did not STOP without channel/manager fault')
            need(bytes_at(cp,source,256)==payload,'PL330 modified source bytes')
            need(bytes_at(cp,destination-16,256)==b'\xa5'*16+payload[:240] and bytes_at(cp,destination+240,32)==payload[240:]+b'\xa5'*16,
                 'PL330 actual program bytes/guards differ')
            need(cp.read(base+0x28)&(1<<event) and irq(cp,number),'PL330 program event/IRQ missing')
            cp.write(base+0x2c,1<<event)
            need(not irq(cp,number) and not cp.read(base+0x28)&(1<<event),'PL330 actual event clear did not lower status/IRQ')
            rows.append(dict(controller=controller,execution_channel=0,event=event,intid=number,bytes=256))
        reset_offsets=(0x20,0x400,0x404,0x408)
        before={hex(offset):cp.read(base+offset) for offset in reset_offsets}
        need(all(before.values()),'PL330 reset evidence requires nonzero actual configuration')
        cp.write(0xf1388334,1<<(14+controller));held=rejected(cp,base,'CP_SCU')
        cp.write(0xf1388338,1<<(14+controller))
        after={hex(offset):cp.read(base+offset) for offset in reset_offsets}
        need(not any(after.values()) and cp.read(base+0x100)&15==0,'PL330 reset did not clear actual channel/configuration')
        rows[-1].update(reset_rejection=held,reset_registers_before=before,reset_registers_after=after)
    return dict(events=rows,execution_channels=[0],abort_irq_verified=False,peripheral_handshake_verified=False,
                pending_irq_reset_verified=False)


def uart(cp,out):
    rows=[]
    for bank in range(5):
        base=0xf1000000+bank*0x1000;path=out/f'uart{bank}.log'
        cp.write(base+0x24,6);cp.write(base+0x28,32);cp.write(base+0x2c,0x70);cp.write(base+0x30,0x301)
        payload=f'CP-UART-{bank}\n'.encode('ascii')
        for value in payload:cp.write(base,value)
        cp.qtest('clock_step 100000')
        need(path.read_bytes()==payload and cp.read(base+0x18)&0x80,'PL011 data was not actually consumed')
        cp.write(base+0x30,1);cp.write(base,ord('Z'))
        # Stock PL011 warns but still writes with TXE=0; this is not physical gating.
        disabled=path.read_bytes()[len(payload):]
        need(disabled==b'Z','Stock PL011 disabled-TXE behavior differs from pinned source')
        rows.append(dict(bank=bank,bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),
                         tx_disabled_consumed_bytes=len(disabled),txe_gating_supported=False))
    return dict(banks=rows,uart_irq_verified=False,physical_clock_calibrated=False,txe_gating_supported=False)


def record_check(result,name,operation):
    try:
        result['checks'][name]=operation()
    except ValueError as error:
        # Content failures can coexist; broken transport must still stop the run.
        result.setdefault('check_errors',{})[name]=dict(error=repr(error),traceback=traceback.format_exc())


def run(binary,output,only=None):
    need(only in (None,'scu_i2c'),'Unknown component selection')
    output=Path(output).absolute();binary=Path(binary).resolve(strict=True)
    need(not str(output).startswith('/tmp/') and not output.exists(),'Use a new project output directory')
    output.mkdir(mode=0o700);pair=output/'pair';devices=output/'devices';devices.mkdir(mode=0o700)
    link=runpy.run_path(str(HERE/'native-link.py'));endpoint=runpy.run_path(str(HERE/'native-qtest.py'))['NativeEndpoint']
    result=dict(schema='a7c2-native-device-batch-v3',verified=False,selected_checks_verified=False,
                selection=only or 'all',executed_checks=[],original_ap_consumption_verified=False,
                original_cp_consumption_verified=False,physical_compatible=False,capture_verified=False,
                software='Qtest acceleration with no original software; running state only for virtual-key events and DFS clock completion',
                harness_sha256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in
                    ('check-native-qemu.py','native-qtest.py','component-gic-groups-qemu.c')},checks={},owners={})
    ap=cp=None;old=os.getcwd()
    try:
        result['admission']=link['prepare'](pair,binary)
        os.chdir(pair)
        ap=endpoint(binary,pair,devices,'ap',p1_spi_component=(only is None));cp=endpoint(binary,pair,devices,'cp')
        # Explicit diagnostic secure bus master reaches only real IGROUPR.
        # GIC security stays enabled; no pending register is exposed here.
        group_words=result['secure_gic_group_words']=[]
        for word in range(16):
            address=0x0b020000+word*4;cp.write(address,0xffffffff)
            actual=cp.read(address)
            group_words.append(dict(address=address,written=0xffffffff,readback=actual))
            need(actual==0xffffffff,'Secure GIC group setup was not consumed')
        nonsecure=cp.read(CP_GIC+0x80)
        need(nonsecure==0,'Nonsecure IGROUPR view must remain RAZ with GIC security enabled')
        result['secure_gic_setup']=dict(profile='virtual-native-component-gic-groups-v1',register_bytes=64,
            nonsecure_group_view=nonsecure,all_words_match=all(row['written']==row['readback'] for row in group_words),
            pending_or_irq_synthesized=False,group1_is_component_test_prerequisite=True)
        for name,operation in (('gpio',lambda:gpio(ap,cp)),('keyboard',lambda:keyboard(cp)),
                               ('p1_spi_component',lambda:p1_spi_component(ap,cp)),('scu_i2c',lambda:scu_i2c(cp)),
                               ('tpu_watchdog',lambda:tpu_watchdog(cp)),('dma',lambda:dma(ap,cp)),
                               ('pl080',lambda:pl080(cp)),('pl330',lambda:pl330(cp)),('uart',lambda:uart(cp,devices)),
                               ('keyboard_reset',lambda:keyboard_reset(cp))):
            if only is None or name==only:
                result['executed_checks'].append(name)
                record_check(result,name,operation)
        result['owners']['ap']=ap.close()
        if only is None:
            time.sleep(.02);result['executed_checks'].append('disconnect')
            record_check(result,'disconnect',lambda:rejected(cp,0xf102e010,'AP_CP_GPIO'))
        result['owners']['cp']=cp.close()
        need(all(owner.get('qmp_quit_confirmed') and owner.get('returncode')==0 and not owner.get('alive') for owner in result['owners'].values()),'Owners did not exit normally')
        need(not result.get('check_errors'),'Device content failures: '+', '.join(result.get('check_errors',{})))
        result['selected_checks_verified']=True
        result['verified']=only is None
    except BaseException as error:
        result['error']=repr(error);result['traceback']=traceback.format_exc()
    finally:
        for name,machine in (('cp',cp),('ap',ap)):
            if machine is not None and machine.process is not None:
                try:result['owners'][name]=machine.close()
                except BaseException as error:result.setdefault('cleanup_errors',[]).append(dict(side=name,error=repr(error)))
        for name in ('ap','cp'):
            owner_path=devices/(name+'-owner.json')
            if owner_path.is_file():
                result['owners'][name]=json.loads(owner_path.read_bytes())['shutdown']
        result['pair_lease_released']=False
        result['retention']='Synthetic RAM retained until parent verifies both owners and writes storage cleanup ledger'
        os.chdir(old)
        with (output/'result.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--binary',required=True,type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--only',choices=('scu_i2c',),help='Run only the specified component group; not full-batch acceptance')
    args=parser.parse_args();result=run(args.binary,args.output,args.only)
    print(json.dumps(dict(verified=result['verified'],selected_checks_verified=result['selected_checks_verified'],output=str(args.output),error=result.get('error'))))
    raise SystemExit(0 if result['selected_checks_verified'] else 1)
