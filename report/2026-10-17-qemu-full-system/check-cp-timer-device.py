#!/usr/bin/env python3
"""Deterministic qtest checks of the private timer device, without any firmware.

These synthetic register writes are device tests, never evidence of camera work.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import tempfile
import time

HERE=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--watchdog',action='store_true',help='test the separate limited reset-mode watchdog at nominal4MHz')
    mode.add_argument('--edma-gate',action='store_true',help='test only the EDMA interrupt-enable gate, not a DMA engine')
    mode.add_argument('--edma-direct',action='store_true',help='test actual doorbell-driven RAM transfer and bounded unsupported modes')
    args=parser.parse_args()
    binary=HERE.parents[1]/'analysis/cp-boot-probe/qemu-cp-src/build-cp/qemu-system-aarch64'
    out=Path(tempfile.mkdtemp(prefix='cp-edma-direct-qtest-' if args.edma_direct else ('cp-edma-gate-qtest-' if args.edma_gate else ('cp-watchdog-qtest-' if args.watchdog else 'cp-timer-qtest-')),dir=HERE/'runtime/analysis'))
    commands=[];expected={}
    def add(command,value=None):
        if value is not None:expected[len(commands)]=value
        commands.append(command)
    add('irq_intercept_in @gic@')
    add('readl 0xf1042000',0)
    add('writel 0xf1042010 0x64')
    add('writel 0xf1042000 0x1022')
    add('clock_step 1000000')
    add('readl 0xf104200c',1100)
    add('writel 0xf1042000 0x22')
    add('clock_step 2000000')
    add('readl 0xf104200c',1100)
    add('writel 0xf1042004 0x10')
    add('readl 0xf104200c',0)
    add('writel 0xf1042000 0x10022')  # Unsupported capture bit must not change control.
    add('readl 0xf1042000',0x22)
    add('readl 0xf1043000',0)  # Another channel must remain independent.
    add('writel 0xf1042008 0xa')
    add('writel 0xf1042000 0x1112')
    add('clock_step 10000')
    add('readl 0xf1042000',0x112)  # One-shot comparator actually stops.
    add('readl 0xf104200c',10)
    add('writel 0xf1042004 0x1')
    add('readl 0xf1042000',0x112)
    if args.watchdog:
        commands.clear();expected.clear()
        add('readl 0xf1052000',0)
        add('writel 0xf1388344 0x40000')
        add('readl 0xf1388340',0x40000)
        add('writel 0xf1052000 1')  # Held-reset writes cannot enable the device.
        add('readl 0xf1052000',0)
        add('writel 0xf1388348 0x40000')
        add('readl 0xf1388340',0)
        add('writel 0xf1052004 0x11')
        add('writel 0xf1052000 1')
        add('readl 0xf1052008',131072)
        add('clock_step 1000000')
        add('readl 0xf1052008',127072)
        add('writel 0xf1052000 0')  # EN is sticky, not a fake stop.
        add('readl 0xf1052000',1)
        add('writel 0xf1052000 3')  # Unsupported IRQ mode cannot mutate CR.
        add('readl 0xf1052000',1)
        add('writel 0xf105200c 0x75')
        add('readl 0xf1052008',127072)
        add('writel 0xf105200c 0x76')
        add('readl 0xf1052008',131072)
        add('writel 0xf1052004 0x22')
        add('readl 0xf1052008',131072)  # TORR alone does not reload.
        add('writel 0xf1052004 0x100')
        add('readl 0xf1052004',0x22)
        add('writel 0xf1388344 0x40000')
        add('readl 0xf1052000',0)
        add('readl 0xf1052004',0)
        add('clock_step 5000000')
        add('readl 0xf1052000',0)
        add('writel 0xf1388348 0x40000')
        add('writel 0xf1052000 1')
        add('clock_step 16384000')  # Output gate0 suppresses the reset output only.
        add('readl 0xf1052000',1)
        add('readl 0xf1052008',65536)
        add('writel 0xf13883a0 2')
        add('readl 0xf13883a0',0)
        add('writel 0xf13883a0 1')
        add('writel 0xf105200c 0x76')
        add('clock_step 16384000')  # A real watchdog action must now be observable.
    if args.edma_gate:
        commands.clear();expected.clear()
        add('irq_intercept_in @gic@')
        add('readl 0xf11e0274',0)
        add('writel 0xf11e0274 0xffff')  # Enable alone must not invent an interrupt.
        add('readl 0xf11e0274',0xffff)
        add('writel 0xf11e0274 0')
        add('set_irq_in @gate@ edma 3 1')  # Masked source does not reach the GIC.
        add('writel 0xf11e0274 8')
        add('readl 0xf11e0274',8)
        add('writel 0xf11e0274 0x80')
        add('readl 0xf11e0274',0x80)
        add('set_irq_in @gate@ edma 7 1')
        add('set_irq_in @gate@ edma 3 0')
        add('writel 0xf11e0274 0x10000')  # Unsupported high fields must not mutate enable.
        add('readl 0xf11e0274',0x80)
        add('set_irq_in @gate@ edma 7 0')
        add('writel 0xf11e0274 0xffff')
        add('readl 0xf11e0274',0xffff)
        add('set_irq_in @gate@ edma 15 1')
        add('writel 0xf11e0274 0x7fff')
        add('set_irq_in @gate@ edma 15 0')
        add('readl 0xf11e0274',0x7fff)
    if args.edma_direct:
        commands.clear();expected.clear()
        payload=bytes((i*37+i//251+11)&255 for i in range(8193))
        add('irq_intercept_in @gic@')
        add('writel 0xf11e0274 0xffff')
        add('write 0x200000 8193 0x'+payload.hex())
        add('memset 0x20fffc 8205 0xa5')
        add('writel 0xf678000c 1')
        add('writel 0xf6780128 1')
        for offset,value in ((0x200,8),(0x208,8193),(0x20c,0x200000),(0x210,0),
                             (0x214,0x210000),(0x218,0)):
            add(f'writel {0xf6780000+offset:#x} {value:#x}')
        add('writel 0xf6780200 0x28')  # Software cannot create a running channel.
        add('readl 0xf6780200',8)
        add('writel 0xf6780010 0')
        add('readl 0xf6780200',0x28)
        add('readl 0xf678004c',0)
        add('clock_step 1')
        add('readl 0xf6780208',4097)
        add('readl 0xf678004c',0)
        add('clock_step 1')
        add('readl 0xf6780208',1)
        add('clock_step 1')
        add('readl 0xf6780200',0x68)
        add('readl 0xf6780208',0)
        add('readl 0xf678004c',1)
        add('read 0x210000 8193',payload)
        add('read 0x200000 8193',payload)
        add('readl 0x20fffc',0xa5a5a5a5)
        add('read 0x212001 8',b'\xa5'*8)
        add('writel 0xf6780054 0')  # Pending is real but masked until this write.
        add('writel 0xf6780058 1')
        add('readl 0xf678004c',0)
        add('writel 0xf6780210 8')  # Complete64-bit address must not alias lowRAM.
        add('writel 0xf6780208 8193')
        add('memset 0x210000 8193 0x6b')
        add('writel 0xf6780010 0')
        add('clock_step 10')
        add('readl 0xf678004c',0)
        add('readl 0xf6780200',0x68)
        add('read 0x210000 8193',b'\x6b'*8193)
        add('writel 0xf6780210 0')
        add('writel 0xf6780200 0x300')  # LLP unsupported: no fabricated completion.
        add('writel 0xf6780010 0')
        add('clock_step 10')
        add('readl 0xf678004c',0)
        add('readl 0xf6780200',0x360)
        add('read 0x210000 8193',b'\x6b'*8193)
        add('writel 0xf6780200 8')
        add('writel 0xf6780208 0')  # Zero-length request is not a completed frame.
        add('writel 0xf6780010 0')
        add('clock_step 10')
        add('readl 0xf678004c',0)
        add('readl 0xf6780200',0x68)
        add('writel 0xf6780208 32')
        add('writel 0xf6780214 0x200001')  # Overlap has no modeled ordering.
        add('writel 0xf6780010 0')
        add('clock_step 10')
        add('read 0x200000 8193',payload)
        add('readl 0xf678004c',0)
        add('readl 0xf6780200',0x68)
        add('writel 0xf678002c 1')
        add('writel 0xf6780184 1')  # RD channel7, independent direction/channel.
        for offset,value in ((0x1100,8),(0x1108,32),(0x110c,0x200000),(0x1110,0),
                             (0x1114,0x220000),(0x1118,0)):
            add(f'writel {0xf6780000+offset:#x} {value:#x}')
        add('writel 0xf67800a8 0')
        add('writel 0xf6780030 7')
        add('clock_step 1')
        add('read 0x220000 32',payload[:32])
        add('readl 0xf67800a0',0x80)
        add('readl 0xf678004c',0)
        add('writel 0xf67800ac 0x80')
        add('readl 0xf67800a0',0)
    command=[str(binary),'-M','none','-cpu','cortex-a53','-smp','4','-m','64M',
             '-display','none','-nodefaults','-nic','none','-audio','none','-accel','qtest',
             '-qtest','stdio']
    result={'schema':'cp-edma-direct-qtest-v1' if args.edma_direct else ('cp-edma-gate-qtest-v1' if args.edma_gate else ('cp-watchdog-qtest-v1' if args.watchdog else 'cp-timer-qtest-v1')),'verified':False,'scope':'synthetic device tests, direct-mode test uses actual DMA bus copies; no firmware loaded',
            'qemu_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'command':command,'commands':commands}
    monitor,child_monitor=socket.socketpair();monitor.settimeout(5)
    command+=['-chardev',f'socket,id=unit-qmp,fd={child_monitor.fileno()}',
              '-mon','chardev=unit-qmp,mode=control']
    process=None;stdout=bytearray();qmp=monitor.makefile('rwb',buffering=0);events=[]
    def qmp_command(name,**arguments):
        qmp.write(json.dumps({'execute':name,'arguments':arguments}).encode()+b'\n')
        while True:
            message=json.loads(qmp.readline())
            if 'event' in message:events.append(message);continue
            if 'error' in message:raise RuntimeError(message)
            if 'return' in message:return message['return']
    try:
        with (out/'stderr.log').open('wb') as log:
            env={k:v for k,v in os.environ.items() if not k.startswith('QEMU_CP_')}
            env.update(QEMU_CP_GIC='1')
            env['QEMU_CP_EDMA_GATE' if args.edma_gate or args.edma_direct else ('QEMU_CP_WATCHDOG' if args.watchdog else 'QEMU_CP_TIMERS')]='1'
            if args.edma_direct:env['QEMU_CP_EDMA_DIRECT']='1'
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,
                                     pass_fds=(child_monitor.fileno(),),
                                     env=env)
        child_monitor.close();assert 'QMP' in json.loads(qmp.readline());qmp_command('qmp_capabilities')
        if args.watchdog:
            qmp_command('set-action',watchdog='pause')  # Test observer; never claimed as firmware reset execution.
            result['test_watchdog_action']='pause'
        else:
            devices=qmp_command('qom-list',path='/machine/unattached')
            gics=[d['name'] for d in devices if d['type']=='child<arm_gic>'];assert len(gics)==1
            gic='/machine/unattached/'+gics[0];result['gic_path']=gic
            commands[:]=[c.replace('@gic@',gic) for c in commands]
            if args.edma_gate:
                gates=[d['name'] for d in devices if d['type']=='child<sony-cp-edma-gate>'];assert len(gates)==1
                gate='/machine/unattached/'+gates[0];result['gate_path']=gate
                commands[:]=[c.replace('@gate@',gate) for c in commands]
        process.stdin.write(('\n'.join(commands)+'\n').encode());process.stdin.flush()
        deadline=time.monotonic()+5
        while sum(line.startswith(b'OK') for line in stdout.splitlines())<len(commands):
            left=deadline-time.monotonic()
            if left<=0 or not select.select([process.stdout],[],[],left)[0]:raise TimeoutError('qtest response deadline')
            data=os.read(process.stdout.fileno(),4096)
            if not data:raise EOFError('qtest ended before all responses')
            stdout.extend(data)
        if args.watchdog:
            result['final_status']=qmp_command('query-status')
            watchdog_events=[e for e in events if e['event']=='WATCHDOG']
            assert len(watchdog_events)==1 and watchdog_events[0]['data']['action']=='pause'
            assert result['final_status']['running'] is False
        qmp_command('quit');process.wait(timeout=5);result['qemu_rc']=process.returncode
        assert process.returncode==0
        all_lines=stdout.decode().splitlines();lines=[line for line in all_lines if line.startswith('OK')]
        assert len(lines)==len(commands)
        edges=[line for line in all_lines if line.startswith('IRQ ')]
        if not args.watchdog:
            if args.edma_direct:
                assert edges==['IRQ raise 371','IRQ lower 371']*2,edges
            elif args.edma_gate:
                assert edges==['IRQ raise 371','IRQ lower 371']*3,edges
            else:
                assert 'IRQ raise 381' in edges and 'IRQ lower 381' in edges
                assert edges.index('IRQ raise 381')<edges.index('IRQ lower 381')
        for index,value in expected.items():
            assert lines[index].startswith('OK ')
            actual=bytes.fromhex(lines[index].split()[1].removeprefix('0x')) if isinstance(value,bytes) else int(lines[index].split()[1],0)
            assert actual==value,(commands[index],actual,value)
        assert all(line=='OK' or line.startswith('OK ') for line in lines)
        result.update(verified=True,checks=len(expected),responses=lines,irq_edges=edges,qmp_events=events,
                      irq_scope='actual doorbell-driven disjointRAM copies and gatedDONE, no AP/CP endpoint or original firmware packet' if args.edma_direct else ('GPIO-source/enable gate reaches GICinput371(INTID403), no DMA engine/packet' if args.edma_gate else ('watchdog reset-mode event, IRQ mode unsupported' if args.watchdog else 'timer output reaches GIC input381 (INTID413) and is cleared; no synthetic ACK or full guest interrupt claim')),
                      transport_ok_not_device_ack=('qtest OK is transport only; rejected direct requests checked for no DONE, unchanged CTRL and sampled memory, not every internal field' if args.edma_direct else 'qtest OK on unsupported write is not called success; unchanged control proves no mutation'))
    except BaseException as error:
        result['error']=repr(error)
        if isinstance(error,subprocess.TimeoutExpired):
            (out/'stdout.log').write_bytes(error.output or b'')
            (out/'stderr.log').write_bytes(error.stderr or b'')
        raise
    finally:
        (out/'stdout.log').write_bytes(stdout)
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        qmp.close();monitor.close();child_monitor.close()
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('CP_TIMER_DEVICE_CHECK',out,flush=True)


if __name__=='__main__':main()
