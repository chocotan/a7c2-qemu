"""Actual QEMU RAM/MMIO test of the declared reference backend, no firmware capture."""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time

import pytest
from native_rc_board import require_binary
from boot_irq_diagnostics import gic_state
from rc_reference_evidence import operations


@pytest.mark.skipif(not os.environ.get('QEMU_RC_TEST_BINARY'),reason='Set QEMU_RC_TEST_BINARY to the RC candidate')
@pytest.mark.parametrize('handoff',[False,True])
@pytest.mark.parametrize('sa_mode',['off','data-only','reference-complete'])
def test_real_ram_transfer_rejection_and_w1c(tmp_path,handoff,sa_mode):
    sa_data=sa_mode!='off'
    complete=sa_mode=='reference-complete'
    binary=Path(os.environ['QEMU_RC_TEST_BINARY']).resolve()
    require_binary(binary,reference=True)
    if handoff:require_binary(binary,reference=True,handoff=True)
    if sa_data:require_binary(binary,reference=True,sa_data=not complete,sa_complete=complete)
    command=['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
        '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib','/lib64',
        '--ro-bind',str(binary),'/qemu','--bind',str(tmp_path),'/out','--proc','/proc','--dev','/dev',
        '--chdir','/','--setenv','QEMU_SONY_PCIDMA','1','--setenv','QEMU_SONY_RC','1',
        *(['--setenv','QEMU_SONY_GIC_HANDOFF','1'] if handoff else []),
        *(['--setenv','QEMU_SONY_SA_DATA_ONLY','1'] if sa_mode=='data-only' else []),
        *(['--setenv','QEMU_SONY_SA_REFERENCE_COMPLETE','1'] if complete else []),
        '/qemu','-machine','virt,secure=off,gic-version=2','-cpu','cortex-a35','-smp','2',
        '-m','24576','-nodefaults','-display','none','-serial','none','-monitor','none','-nic','none',
        '-S','-sandbox','on','-qtest','unix:/out/qtest.sock,server=on,wait=off',
        '-qmp','unix:/out/qmp.sock,server=on,wait=off','-d','guest_errors','-D','/out/boot-trace.log']
    with (tmp_path/'qemu.log').open('wb') as log:
        proc=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                deadline=time.monotonic()+15
                while True:
                    try:connection.connect(str(tmp_path/'qtest.sock'));break
                    except (FileNotFoundError,ConnectionRefusedError):
                        if proc.poll() is not None or time.monotonic()>deadline:
                            raise RuntimeError('Qtest startup failed: '+(tmp_path/'qemu.log').read_text(errors='replace')[-2000:])
                        time.sleep(.05)
                connection.settimeout(30)
                with connection.makefile('rwb') as wire:
                    def read_gic_state():
                        with socket.socket(socket.AF_UNIX) as control:
                            control.settimeout(15);control.connect(str(tmp_path/'qmp.sock'))
                            with control.makefile('rwb') as stream:
                                assert 'QMP' in json.loads(stream.readline())
                                def rpc(command,args=None):
                                    request=dict(execute=command)
                                    if args:request['arguments']=args
                                    stream.write(json.dumps(request).encode()+b'\n');stream.flush()
                                    while True:
                                        reply=json.loads(stream.readline());assert 'error' not in reply,reply
                                        if 'return' in reply:return reply
                                rpc('qmp_capabilities')
                                return gic_state(rpc)['state']
                    interrupts=[]
                    def qtest(command):
                        wire.write(command.encode()+b'\n');wire.flush()
                        while True:
                            reply=wire.readline(16*1024*1024).strip()
                            if reply.startswith(b'IRQ '):interrupts.append(reply);continue
                            break
                        assert reply==b'OK' or reply.startswith(b'OK '),reply[:200]
                        return reply[3:]

                    base=0xf30b0000;source=0x425558000;destination=0x4f8500000;size=4147200
                    qtest('irq_intercept_out /machine/sony-rc-reference-1 sysbus-irq')
                    for offset,value in ((0x4a0,0xdeadbeef),(0x4e0,0x12345678),(0x520,0x177),(0x560,0x100)):
                        assert int(qtest(f'readl {0xf2800000+offset:#x}'),16)==0
                        qtest(f'writel {0xf2800000+offset:#x} {value:#x}')
                    for offset,value in ((0x4a0,0xdeadbeef),(0x4e0,0x12345678),(0x520,0x177),(0x560,0x100)):
                        assert int(qtest(f'readl {0xf2800000+offset:#x}'),16)==value
                    assert interrupts==[]
                    pattern=bytes((i*29+i//3840*71+i%7*53)&255 for i in range(size))
                    qtest(f'write {source:#x} {size} 0x'+pattern.hex())
                    qtest(f'memset {destination:#x} {size+16} 0xa5')
                    rc=[0,0xc0050a,0,0x01000100,0x01000100,0,0x1000,0x1000,
                        0,0,0x07800438,0x07800438,1,0,0,0x07800438]+[0]*16
                    for offset,words in ((0x2000,rc),(0x1200,[3,0,0,0,0,0,0,0,0x25558000,3840,0,1079]+[0]*20),
                        (0x1280,[3,0,0,0,0,0,0,0,0xf8500000,3840,0,1079]+[0]*20),
                        (0xd100,[0]*4),(0xc100,[0,0,1,0])):
                        for i,value in enumerate(words):qtest(f'writel {base+offset+i*4:#x} {value:#x}')
                    qtest(f'writel {base+0x1008:#x} 0xff')
                    qtest(f'writel {base+0x2000:#x} 1')
                    assert interrupts==[b'IRQ raise 0']
                    actual=bytes.fromhex(qtest(f'read {destination:#x} {size}').decode()[2:])
                    assert actual==pattern
                    assert bytes.fromhex(qtest(f'read {destination+size:#x} 16').decode()[2:])==bytes([0xa5])*16
                    assert int(qtest(f'readl {base+0x1000:#x}'),16)==0x11
                    qtest(f'writel {base+0x1000:#x} 0x0f')
                    assert int(qtest(f'readl {base+0x1000:#x}'),16)==0x10
                    qtest(f'writel {base+0x1000:#x} 0xf0')
                    assert int(qtest(f'readl {base+0x1000:#x}'),16)==0
                    assert interrupts==[b'IRQ raise 0',b'IRQ lower 0']
                    if sa_data:
                        package=Path(__file__).with_name('menu-root')/'usr/sabin/sa_sabin_mp_cam_post.bin'
                        if not package.exists():pytest.skip('Original SA program is not distributed')
                        program=package.read_bytes()[0x8900:0x9d00]
                        assert hashlib.sha256(program).hexdigest()=='75c481ee17961521fd5cb2c41ab49fec79228839e47faba5d97f8ef59a5a8822'
                        parameters=[0x1564e,1920,1080,3840,1,0,0,0,0x3e140000,0x2bd95000]+[0]*118
                        table=[1,0,0x180,0x1f96f480,1,0x200,0x1518180,0x3e140000,
                               1,0x1518200,0x2a30180,0x2bd95000]+[0]*76
                        qtest('write 0x47d0e0900 5120 0x'+program.hex())
                        qtest('write 0x47e5bd200 512 0x'+struct.pack('<128I',*parameters).hex())
                        qtest('write 0x47e5bd400 352 0x'+struct.pack('<88I',*table).hex())
                        qtest('memset 0x4af654000 3110416 0xa5')
                        for offset,value in ((0x110,0x1f96f480),(0x114,0x1f96f500),(0x30,0x7d0e0900),
                            (8,0x80000000),(0x104,0xff),(0x108,0xff),(0,1),(4,1)):
                            qtest(f'writel {0xf3170000+offset:#x} {value:#x}')
                        uv=b''.join(bytes((a+b+1)//2 for a,b in zip(
                            pattern[row*3840+1:(row+1)*3840:2],
                            pattern[(row+1)*3840+1:(row+2)*3840:2])) for row in range(0,1080,2))
                        expected=pattern[::2]+uv
                        converted=bytes.fromhex(qtest('read 0x4af654000 3110400').decode()[2:])
                        assert converted==expected
                        assert bytes.fromhex(qtest('read 0x4af94b600 16').decode()[2:])==bytes([0xa5])*16
                        assert int(qtest('readl 0xf3170100'),16)==int(complete)
                        assert int(qtest('readl 0xf3170104'),16)==int(complete)
                        assert interrupts==[b'IRQ raise 0',b'IRQ lower 0']
                        irq48=lambda:next(irq for irq in read_gic_state()['irqs'] if irq['irq']==48)
                        assert bool(irq48()['level']) is complete
                        if complete:
                            # Reference completion is pending only after the verified output.
                            qtest('writel 0xf3170108 0')
                            assert irq48()['level']==0 and int(qtest('readl 0xf3170104'),16)==1
                            qtest('writel 0xf3170108 0xff')
                            assert irq48()['level']
                            qtest('writel 0xf3170104 1')
                            assert int(qtest('readl 0xf3170100'),16)==0
                            assert int(qtest('readl 0xf3170104'),16)==0
                            assert irq48()['level']==0
                        # Mutating the pinned program must reject the next launch without writing.
                        qtest('write 0x47d0e0900 1 0x00');qtest('memset 0x4af654000 3110400 0xa5')
                        qtest('writel 0xf3170000 1');qtest('writel 0xf3170004 1')
                        assert bytes.fromhex(qtest('read 0x4af654000 3110400').decode()[2:])==bytes([0xa5])*3110400
                        assert int(qtest('readl 0xf3170104'),16)==0 and interrupts==[b'IRQ raise 0',b'IRQ lower 0']
                    # A non-unity phase must not touch output or publish completion.
                    qtest(f'memset {destination:#x} {size} 0xa5')
                    qtest(f'writel {base+0x1200:#x} 3');qtest(f'writel {base+0x1280:#x} 3')
                    qtest(f'writel {base+0x2020:#x} 1');qtest(f'writel {base+0x2000:#x} 1')
                    rejected=bytes.fromhex(qtest(f'read {destination:#x} {size}').decode()[2:])
                    assert rejected==bytes([0xa5])*size and int(qtest(f'readl {base+0x1000:#x}'),16)==0
                    assert interrupts==[b'IRQ raise 0',b'IRQ lower 0']
                    print('RC_QTEST_DATA_SHA256',hashlib.sha256(actual).hexdigest())
                    # Reset must retire an outstanding real completion, including its line.
                    qtest(f'writel {base+0x2020:#x} 0')
                    qtest(f'writel {base+0x2000:#x} 1')
                    assert interrupts[-1]==b'IRQ raise 0'
                    with socket.socket(socket.AF_UNIX) as control:
                        control.settimeout(15);control.connect(str(tmp_path/'qmp.sock'))
                        with control.makefile('rwb') as qmp:
                            assert 'QMP' in json.loads(qmp.readline())
                            qmp.write(b'{"execute":"qmp_capabilities"}\n');qmp.flush()
                            assert 'return' in json.loads(qmp.readline())
                            qmp.write(b'{"execute":"system_reset"}\n');qmp.flush()
                            returned=reset=False
                            while not (returned and reset):
                                message=json.loads(qmp.readline())
                                assert 'error' not in message,message
                                returned|='return' in message
                                reset|=message.get('event')=='RESET'
                            def rpc(command,args=None):
                                request=dict(execute=command)
                                if args:request['arguments']=args
                                qmp.write(json.dumps(request).encode()+b'\n');qmp.flush()
                                while True:
                                    message=json.loads(qmp.readline())
                                    assert 'error' not in message,message
                                    if 'return' in message:return message
                            state=gic_state(rpc)['state']
                            assert state['loader_spi_targets'] is handoff
                            assert all(irq['target']==int(handoff) and irq['enabled']==0 and
                                irq['active']==0 and irq['level']==0 for irq in state['irqs'])
                    for offset in (0x1000,0x1008,0x1220,0x12a0):
                        assert int(qtest(f'readl {base+offset:#x}'),16)==0
                    qtest(f'writel {base+0x1008:#x} 0xff')
                    assert interrupts==[b'IRQ raise 0',b'IRQ lower 0',b'IRQ raise 0',b'IRQ lower 0']
        finally:
            proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
    trace=(tmp_path/'boot-trace.log').read_text(errors='replace')
    assert len(operations(trace))==2  # Valid transfers only; rejected phase emits no data receipt.
    assert trace.index('SONY_RC_MMIO_WR 0xf30b2000 = 0x1')<trace.index('SONY_RC_DATA engine=1')
    if complete:
        assert 'silicon=unverified completion_published=1' in trace
    elif sa_data:
        assert 'silicon=unverified completion_published=0' in trace
