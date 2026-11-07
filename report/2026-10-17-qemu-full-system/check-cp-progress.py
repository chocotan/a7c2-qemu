#!/usr/bin/env python3
"""Bounded read-only register snapshots of the private four-core CP diagnostic.

This retains the existing RAM/loader alias hypothesis; it is not verified Sony
boot. Firmware stays unchanged; opt-in debugger points are removed before exit.
No guest fields, device ready replies, or firmware patches are supplied.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import re
import runpy
import socket
import struct
import subprocess
import sys
import tempfile
import time

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


class QMPObserver:
    def __init__(self,stream,record):
        self.stream,self.record=stream,record
        record.update(messages=[],requests=[],wire_bytes=0)
        if 'QMP' not in self.receive():raise ValueError('missing QMP greeting')
        self.command('qmp_capabilities')

    def receive(self):
        raw=self.stream.readline(16385)
        if not raw:raise EOFError('QMP observer disconnected')
        self.record['wire_bytes']+=len(raw)
        if len(raw)>16384 or len(self.record['messages'])>=256 or self.record['wire_bytes']>1024**2:
            self.record.update(limit_exceeded=True,rejected_raw_hex=raw.hex())
            raise ValueError('QMP observer explicit wire limit')
        row={'raw_hex':raw.hex()};self.record['messages'].append(row)
        message=json.loads(raw)
        if not isinstance(message,dict):raise ValueError('QMP message is not an object')
        row['message']=message
        return message

    def command(self,name):
        if name not in ('qmp_capabilities','query-status'):
            raise ValueError('QMP observer command is not read-only')
        request={'execute':name,'id':'observer-'+str(len(self.record['requests'])+1)}
        self.record['requests'].append(request)
        self.stream.write(json.dumps(request).encode()+b'\n')
        while True:
            message=self.receive()
            if 'event' in message:continue
            if message.get('id')!=request['id']:raise ValueError('QMP observer response ID mismatch')
            if 'error' in message:raise RuntimeError('QMP observer error: '+repr(message['error']))
            if 'return' not in message:raise ValueError('QMP observer response lacks return')
            return message['return']


def remove_debug_point(rsp,record):
    primary_failure=sys.exc_info()[0] is not None
    try:
        installed=record['install_request']
        if not installed.startswith(('Z0,','Z2,','Z3,')):
            raise ValueError('invalid original debugger installation request')
        packet='z'+installed[1:];record['remove_request']=packet
        reply=rsp.request(packet);record['remove_reply']=reply
        if reply!='OK':raise RuntimeError('cannot remove installed debugger point')
        record['removed']=True
    except BaseException as error:
        record['cleanup_error']=repr(error)
        if not primary_failure:raise


def app_task_context(rsp):
    cell=0x1b30d30+(153-1)*4
    raw=rsp.memory(cell,4);pointer=int.from_bytes(raw,'little')
    result={'task_id':153,'pointer_cell':hex(cell),'pointer_raw':raw.hex(),'tcb':hex(pointer)}
    if pointer==0:return result
    if not 0x108000<=pointer<=0x4000000-64:
        raise ValueError('task153 control block pointer is outside diagnostic RAM')
    raw=rsp.memory(pointer,64);record=int.from_bytes(raw[8:12],'little')
    result.update(raw=raw.hex(),record_pointer=hex(record),record_identity_matches=record==0xeb38b4,
                  state_byte=raw[12],saved_sp=hex(int.from_bytes(raw[24:28],'little')),
                  saved_pc=hex(int.from_bytes(raw[28:32],'little')))
    return result


def ram_window(rsp,address):
    result={'address':hex(address)}
    if not 0<=address<=0x4000000-32:
        result['error']='outside declared diagnostic RAM; not read'
        return result
    try:result['bytes']=rsp.memory(address,32).hex()
    except ValueError as error:result['error']=str(error)
    return result


def watchdog_context(rsp):
    result={}
    # EOI+14 is read-to-clear and must never be debugger-read.
    for name,address in (('control',0xf1052000),('timeout',0xf1052004),('counter',0xf1052008),
                         ('status',0xf1052010),('reset_data',0xf1388340),('output_gate',0xf13883a0)):
        result[name]={'address':hex(address)}
        try:result[name]['raw']=rsp.memory(address,4).hex()
        except ValueError as error:result[name]['error']=str(error)
    return result


def gpio_config_table_context(rsp):
    tables=[]
    for address in (0x1101fc4,0x1101ffc):
        raw=rsp.memory(address,56)
        if len(raw)!=56:raise ValueError('short GPIO configuration RAM table read')
        rows=[]
        for offset in (0,28):
            entry=raw[offset:offset+28]
            port,pin=struct.unpack_from('<II',entry)
            rows.append({'port':port,'pin':pin,'selector_u8':entry[8],
                         'direction_i32':struct.unpack_from('<i',entry,12)[0],
                         'input_enable_u8':entry[16],'pull_i32':struct.unpack_from('<i',entry,20)[0],
                         'latch_i32':struct.unpack_from('<i',entry,24)[0]})
        tables.append({'runtime_address':hex(address),'raw':raw.hex(),'entries':rows})
    return tables


def official_boot_arguments(factory):
    manifest_path=factory/'manifest.json';manifest_bytes=manifest_path.read_bytes()
    manifest=json.loads(manifest_bytes)
    if (manifest.get('source'),manifest.get('bodydata_sha256'))!=('official-bodydata-derived',
            'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'):
        raise ValueError('boot argument factory provenance mismatch')
    records=[r for r in manifest['images'] if r['name']=='nflasha8.img']
    image=factory/'nflasha8.img';expected='c9691b03e3c8b06092c9d75f7552b8e147ec63d3e635e9f4828b754db30765ce'
    if len(records)!=1 or records[0]['sha256']!=expected or records[0]['bytes']!=67108864:
        raise ValueError('official boot argument image manifest mismatch')
    if image.is_symlink() or not image.is_file() or image.stat().st_size!=67108864:
        raise ValueError('official boot argument image size/type mismatch')
    def digest():
        with image.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    if digest()!=expected:raise ValueError('official boot argument image hash mismatch')
    sys.path.insert(0,str(ROOT/'analysis/vendor/fwtool'))
    from fwtool.archive.fat import readFat
    import stat
    blobs=[]
    with image.open('rb') as stream:
        for entry in readFat(stream):
            if entry.path!='/tomco.txt':continue
            if not stat.S_ISREG(entry.mode) or entry.size!=741:raise ValueError('original tomco file size/type mismatch')
            blobs.append(entry.contents.read(entry.size+1))
    sha='02b202a9b4fbf7bdcbe93d032bfe475a21859019a3c02d1766ac133a779650d3'
    if len(blobs)!=1 or len(blobs[0])!=741 or hashlib.sha256(blobs[0]).hexdigest()!=sha:
        raise ValueError('original tomco file identity mismatch')
    if digest()!=expected or manifest_path.read_bytes()!=manifest_bytes:
        raise ValueError('official boot argument source changed while reading')
    return blobs[0],{'source_class':manifest['source'],'bodydata_sha256':manifest['bodydata_sha256'],
                     'manifest_sha256':hashlib.sha256(manifest_bytes).hexdigest(),'image_sha256':expected,
                     'original_path':'/tomco.txt','bytes':741,'sha256':sha,'bytes_modified':False,
                     'load_address':'0x100000','physical_alias_verified':False}


def step_init_filter(rsp,thread,record):
    regs=record['registers']
    if (int(regs['r15'],16),int(regs['r10'],16),int(regs['r11'],16))!=(0x6349c8,0xeb56c8,13):
        raise ValueError('stop is not the original last initialization mask read')
    if ';s' not in rsp.request('vCont?'):raise RuntimeError('thread-specific step unavailable')
    steps=record['original_filter_steps']=[]
    for expected in (0x6349cc,0x6349d0,None):
        reply=rsp.request('vCont;s:'+thread)
        stopped=re.search(r'thread:([^;]+)',reply)
        if not reply.startswith('T05') or stopped is None or stopped[1]!=thread:
            raise ValueError('unexpected thread or reply during original filter step')
        regs=rsp.regs();steps.append({'stop_reply':reply,'registers':regs})
        pc=int(regs['r15'],16)
        if expected is not None and pc!=expected:raise ValueError('original filter step PC mismatch')
    taken=bool(int(steps[1]['registers']['cpsr'],16)&(1<<30))
    expected=0x634da8 if taken else 0x6349d4
    if int(regs['r15'],16)!=expected:raise ValueError('original BEQ destination does not match original Z flag')
    record.update(original_branch_stepped=True,original_group_reject_branch_taken=taken,
                  original_branch_destination=hex(expected))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tcg-thread',choices=('single','multi'),default='single')
    parser.add_argument('--watch-seconds',type=int,default=12,
                        help='bounded-continue window (host seconds) for every memory-watch observation; '
                             'the original 12 s bound is what keeps the CP from reaching the GPIO18 read, '
                             'while the earlier recorded hits ran without a bound')
    observe=parser.add_mutually_exclusive_group()
    observe.add_argument('--watch-timer-write',action='store_true',help='stop on the first original 4-byte timer-control write; no device response added')
    observe.add_argument('--watch-app-task-table',action='store_true',help='observe the original CPU reading the SYS_EVENT_START function pointer in the task table')
    observe.add_argument('--watch-init-mask',action='store_true',help='observe the original last USER_TSK_INIT2 group-mask read')
    observe.add_argument('--watch-pcie-read',action='store_true',help='observe first original read atf11e0274; controller meaning still requires source proof')
    observe.add_argument('--watch-snapshot-boundary',action='store_true',help='observe original read atca21e00; no RAM expansion or snapshot-header injection')
    observe.add_argument('--watch-gpio18-read',action='store_true',help='observe first original read atf102f000, without sampling or setting GPIO input from debugger')
    observe.add_argument('--break-receiver',action='store_true',help='observe the original Thumb receiver entry, not an application reply')
    observe.add_argument('--break-receiver-create',action='store_true',help='observe the original receiver task creation call and descriptor')
    observe.add_argument('--break-app-start',action='store_true',help='observe the original SYS_EVENT_START-logging function entry')
    observe.add_argument('--break-app-activate',action='store_true',help='observe the original153820 call to sta_tsk(153)')
    observe.add_argument('--break-init-entry',action='store_true',help='observe original1535f4 initialization routine entry before task153 activation')
    observe.add_argument('--break-init-group',action='store_true',help='observe original A32 initialization-group filter6349cc without changing its group')
    observe.add_argument('--break-boot-parser',action='store_true',help='observe original A32 boot-argument signature comparison result at60cba8')
    observe.add_argument('--break-edma-enabled',action='store_true',help='observe original56d472 immediately after the eDMA interrupt-enable write')
    observe.add_argument('--break-edma-initialized',action='store_true',help='observe original56d4a2 after eDMA enable/mask/source configuration')
    observe.add_argument('--break-uipc-oom-initialized',action='store_true',help='observe original56366a after OOM buffer initialization; read original output, never write a header')
    parser.add_argument('--cp-timers',action='store_true',help='instantiate four clocked Sony timer channels at the original CP INTIDs413..416')
    parser.add_argument('--official-boot-arguments',action='store_true',help='load exact741-byte official factory /tomco.txt at diagnostic CP view100000; no parameter edits')
    parser.add_argument('--hypothesis-watchdog4mhz',action='store_true',help='limited reset-mode watchdog model with nominal OSS4MHz clock corroborated by CP timeout table, not physical calibration')
    parser.add_argument('--cp-edma-int-gate',action='store_true',help='model low16 EDMA_INT enable and real GPIO gating only; no DMA/link/status completion')
    parser.add_argument('--cp-edma-direct',action='store_true',help='limited direct-RAM DMA engine; unsupported LLP/STOP/remote addresses fail, no PCIe alias or link')
    parser.add_argument('--cp-uipc-ram',action='store_true',help='provide original1MiB OOM buffer atca21e00 as sparse diagnosticRAM, not a full Sony memory map')
    parser.add_argument('--observe-qmp-events',action='store_true',help='retain raw QMP events and read-only query-status fences; never change watchdog/reset behavior')
    parser.add_argument('--hypothesis-sec-timer30',action='store_true',help='DIAGNOSTIC hypothesis only: route original secure physical timer output to firmware INTID30; Sony wiring is not verified')
    parser.add_argument('--hypothesis-counter2mhz',action='store_true',help='DIAGNOSTIC frequency hypothesis from original CNTFRQ declaration, not a physical clock calibration')
    logs=parser.add_mutually_exclusive_group()
    logs.add_argument('--exception-log',action='store_true',help='bounded exception-only log; no instruction trace')
    logs.add_argument('--gic-log',action='store_true',help='observe original guest controller reads/writes/ACK; never read IAR via debugger')
    args=parser.parse_args()
    if args.cp_edma_direct and not args.cp_edma_int_gate:
        parser.error('--cp-edma-direct requires --cp-edma-int-gate')
    breakpoint_requested=any((args.break_receiver,args.break_receiver_create,args.break_app_start,
                              args.break_app_activate,args.break_init_entry,args.break_init_group,args.break_boot_parser,args.break_edma_enabled,args.break_edma_initialized,args.break_uipc_oom_initialized))
    memory_watch_requested=any((args.watch_timer_write,args.watch_app_task_table,args.watch_init_mask,args.watch_pcie_read,args.watch_snapshot_boundary,args.watch_gpio18_read))
    probe=runpy.run_path(str(ROOT/'analysis/cp-boot-probe/probe.py'))
    image=probe['CP'];data=image.read_bytes();probe['checked_layout'](data)
    binary=ROOT/'analysis/cp-boot-probe/qemu-cp-src/build-cp/qemu-system-aarch64'
    if not binary.is_file():raise FileNotFoundError(binary)
    out=Path(tempfile.mkdtemp(prefix='cp-progress-',dir=HERE/'runtime/analysis'))
    qemu_sha=hashlib.sha256(binary.read_bytes()).hexdigest()
    command=['bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv',
             '--setenv','PATH','/usr/bin','--setenv','HOME','/tmp','--setenv','QEMU_CP_GIC','1',
             '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
             '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',str(binary),'/qemu',
             '--ro-bind',str(image),'/cp.bin','--bind',str(out),'/out','--chdir','/out',
             '/qemu','-M','none','-accel','tcg,thread='+args.tcg_thread,'-cpu',
             'cortex-a53,aarch64=off'+(',cntfrq=2000000' if args.hypothesis_counter2mhz else ''),
             '-m','64M','-smp','4','-display','none','-nodefaults','-audio','none','-nic','none',
             '-monitor','none','-serial','none','-device','loader,file=/cp.bin,addr=0x108000,cpu-num=0,force-raw=on',
             *sum((['-device',f'loader,addr=0x108000,cpu-num={n}'] for n in range(1,4)),[]),
             '-S','-chardev','socket,id=dbg,path=/out/debug.sock,server=on,wait=off','-gdb','chardev:dbg']
    if args.exception_log:command+=['-d','int','-D','/out/exceptions.log']
    if args.cp_timers:
        command[command.index('--setenv') : command.index('--setenv')]=['--setenv','QEMU_CP_TIMERS','1']
    if args.hypothesis_watchdog4mhz:
        at=command.index('--setenv');command[at:at]=['--setenv','QEMU_CP_WATCHDOG','1']
    if args.cp_edma_int_gate:
        at=command.index('--setenv');command[at:at]=['--setenv','QEMU_CP_EDMA_GATE','1']
    if args.cp_edma_direct:
        at=command.index('--setenv');command[at:at]=['--setenv','QEMU_CP_EDMA_DIRECT','1']
    if args.cp_uipc_ram:
        at=command.index('--setenv');command[at:at]=['--setenv','QEMU_CP_UIPC_RAM','1']
    if args.hypothesis_sec_timer30:
        at=command.index('--setenv')
        command[at:at]=['--setenv','QEMU_CP_HYPOTHESIS_SEC_TIMER30','1']
    if args.gic_log:
        command+=['-D','/out/gic.log']  # The private build uses the QEMU log trace backend.
        for event in ('gic_cpu_read','gic_cpu_write','gic_acknowledge_irq','gic_dist_write','gic_update_set_irq',
                      'arm_gt_ctl_write','arm_gt_tval_write','arm_gt_cval_write','arm_gt_update_irq'):
            command+=['-trace','enable='+event]
    if args.observe_qmp_events:command+=['-qmp','unix:/out/qmp.sock,server=on,wait=off']
    result={'schema':'cp-register-progress-v1','verified':False,'scope':'hypothetical CP RAM/loader alias diagnostic, not verified cold boot or receiver completion',
            'command':command,'qemu_sha256':qemu_sha,'cp_sha256':probe['SHA'],
            'trace_enabled':args.exception_log or args.gic_log,
            'trace_scope':{'exceptions':args.exception_log,'gic_transactions':args.gic_log},'snapshots':[]}
    result['cp_timers']={'enabled':args.cp_timers,'channels':4,'intids':[413,414,415,416],
                         'input_clock_hz':4000000,'clock_evidence':'OSS DIV4 to1MHz; original CP startup sets DIV4; no hardware calibration claim',
                         'unsupported':'capture +0x14 or control bit16 returns bus error, not zero/ready'}
    result['secure_timer30_hypothesis']={'enabled':args.hypothesis_sec_timer30,
                                        'sony_wiring_verified':False,'cpu_security_modified':False,
                                        'counter_frequency_modified':args.hypothesis_counter2mhz,'forced_irq_or_ack':False}
    result['generic_counter_rate_hypothesis']={'enabled':args.hypothesis_counter2mhz,
                                              'hz':2000000 if args.hypothesis_counter2mhz else 'QEMU default',
                                              'original_cntfrq_declaration':2000000,'physical_clock_calibrated':False}
    result['watchdog_model']={'enabled':args.hypothesis_watchdog4mhz,'reset_mode_only':True,
                              'nominal_input_hz':4000000,'physical_clock_calibrated':False,
                              'clock_evidence':'Sony OSS rate and CP632a00 approximate timeout-ms table; not CP clock-tree proof',
                              'unsupported':'IRQ mode, RPL programming, inactiveCCVR/ID reads fail with bus error',
                              'expiry_action':'QEMU default watchdog reset; no expiry suppression'}
    result['edma_interrupt_gate']={'enabled':args.cp_edma_int_gate,'address':'0xf11e0274','mask':'0xffff',
                                   'cp_intid':'0x193','initial_model_enable':0,'physical_reset_value_measured':False,
                                   'dma_engine_connected':args.cp_edma_direct,'link_emulated':False,
                                   'external_dma_sources_connected':args.cp_edma_direct}
    result['edma_direct_model']={'enabled':args.cp_edma_direct,'address':'0xf6780000',
                                 'scope':'direct disjoint RAM buffers only, full64-bit addresses; no host camera/AP endpoint',
                                 'llp_or_stop_supported':False,'bandwidth_calibrated':False,
                                 'source_gpio_allocation':'model WR0..7/RD8..15; physical bit ordering not proved, aggregatedIRQ only tested'}
    result['uipc_oom_ram']={'enabled':args.cp_uipc_ram,'address':'0xca21e00','bytes':0x100000,
                            'page_aligned_backing_address':'0xca21000','page_aligned_backing_bytes':0x101000,
                            'page_padding_before':0xe00,'page_padding_after':0x200,
                            'source':'original56364e..65a clear and subsequent original writes',
                            'physical_alias_or_total_ram_verified':False,'extreme_oom_append_bound_verified':False,
                            'guest_payload_injected':False}
    result['qmp_observation']={'enabled':args.observe_qmp_events,
                               'scope':'unmodified QMP event timestamps; not guest clock calibration or reset causality proof'}
    process=connection=qmp_socket=qmp_stream=observer=None
    def limits():
        resource.setrlimit(resource.RLIMIT_CORE,(0,0))
        resource.setrlimit(resource.RLIMIT_FSIZE,(8*1024**2,8*1024**2))
        resource.setrlimit(resource.RLIMIT_CPU,(250,250))
    try:
        boot_arguments=None
        if args.official_boot_arguments:
            boot_arguments,evidence=official_boot_arguments(HERE/'runtime/factory-images/candidate-003')
            boot_file=out/'original-tomco.txt';boot_file.write_bytes(boot_arguments)
            if boot_file.read_bytes()!=boot_arguments:raise ValueError('boot argument staging readback mismatch')
            result['official_boot_arguments']=evidence
            at=command.index('--ro-bind');command[at:at]=['--ro-bind',str(boot_file),'/bootargs']
            command+=['-device','loader,file=/bootargs,addr=0x100000,force-raw=on']
        with (out/'stderr.log').open('wb') as log:
            process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,preexec_fn=limits)
        os.chdir(out)  # A relative connect avoids Linux's 108-byte UNIX socket path limit.
        connection=socket.socket(socket.AF_UNIX);connection.settimeout(args.watch_seconds)
        deadline=time.monotonic()+5
        while True:
            try:connection.connect('debug.sock');break
            except (FileNotFoundError,ConnectionRefusedError):
                if process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('owned QEMU failed to start')
                time.sleep(.02)
        if args.observe_qmp_events:
            qmp_socket=socket.socket(socket.AF_UNIX);qmp_socket.settimeout(5);qmp_socket.connect('qmp.sock')
            qmp_stream=qmp_socket.makefile('rwb',buffering=0)
            observer=QMPObserver(qmp_stream,result['qmp_observation'])
        def qmp_boundary(target):
            if observer is not None:
                target['qmp_status']=observer.command('query-status')
                target['qmp_received_messages']=len(result['qmp_observation']['messages'])
        rsp=probe['RSP'](connection);result['initial_stop']=rsp.request('?')
        result['initial_registers']=rsp.regs()
        assert int(result['initial_registers']['r15'],16)==0x108000
        digest=hashlib.sha256()
        for offset in range(0,len(data),32768):digest.update(rsp.memory(0x108000+offset,min(32768,len(data)-offset)))
        assert digest.hexdigest()==probe['SHA'];result['loaded_sha256']=digest.hexdigest()
        if boot_arguments is not None:
            loaded=rsp.memory(0x100000,len(boot_arguments))
            if loaded!=boot_arguments:raise ValueError('guest boot argument bytes differ from original file')
            result['official_boot_arguments']['guest_loaded_sha256']=hashlib.sha256(loaded).hexdigest()
        result['gate_bytes_diagnostic_only']=rsp.memory(0x03e42000,4).hex()
        threads=[];reply=rsp.request('qfThreadInfo')
        while reply.startswith('m'):
            threads.extend(reply[1:].split(','));reply=rsp.request('qsThreadInfo')
        assert len(threads)==4
        def snapshot(elapsed):
            frame={'active_window_seconds':elapsed,'threads':{}}
            qmp_boundary(frame)
            for thread in threads:
                assert rsp.request('Hg'+thread)=='OK'
                frame['threads'][thread]=rsp.regs()
                registers=frame['threads'][thread]
                for label,key in (('pc_bytes','r15'),('sp_bytes','r13'),('r3_bytes','r3')):
                    address=int(registers[key],16)
                    registers[label]=ram_window(rsp,address)
                # Read RAM only: reading GICC IAR would acknowledge an interrupt.
                context={'head_address':'0x1758e84','nodes':[]}
                registers['fiq_chain']=context
                try:
                    raw=rsp.memory(0x1758e84,4);context['head_raw']=raw.hex()
                    node=int.from_bytes(raw,'little');visited=set()
                    while node:
                        if node in visited or len(visited)>=16 or not 0x108000<=node<=0x4000000-12:
                            raise ValueError('FIQ chain cycle, explicit16-node limit or non-RAM node '+hex(node))
                        visited.add(node);raw=rsp.memory(node,12)
                        following,callback,argument=(int.from_bytes(raw[i:i+4],'little') for i in (0,4,8))
                        row={'address':hex(node),'raw':raw.hex(),'next':hex(following),
                             'callback':hex(callback),'argument':hex(argument)}
                        if 0x108000<=callback&~1<=0x4000000-32:
                            row['callback_bytes']=rsp.memory(callback&~1,32).hex()
                        context['nodes'].append(row);node=following
                    context['closed']=True
                    registers['fiq_registered_node_raw']=rsp.memory(0x11f7df4,12).hex()
                except ValueError as error:context['error']=str(error)
            frame['app_task153']=app_task_context(rsp)
            if args.hypothesis_watchdog4mhz:frame['watchdog_registers']=watchdog_context(rsp)
            result['snapshots'].append(frame)
            if args.cp_timers:
                frame['timer_registers']={}
                for channel in range(4):
                    address=0xf1042000+channel*0x1000
                    frame['timer_registers'][str(channel)]={}
                    for name,offset in (('control',0),('compare',8),('counter',12)):
                        frame['timer_registers'][str(channel)][name]=rsp.memory(address+offset,4).hex()
        snapshot(0)
        assert rsp.request('Hc-1')=='OK'
        if memory_watch_requested:
            address=0xf102f000 if args.watch_gpio18_read else (0xca21e00 if args.watch_snapshot_boundary else (0xf11e0274 if args.watch_pcie_read else (0xeb56d4 if args.watch_init_mask else (0xeb38bc if args.watch_app_task_table else 0xf1042000))))
            number=2 if args.watch_timer_write else 3
            kind='read' if number==3 else 'write'
            guard={'address':hex(address),'bytes':4,'kind':'GDB '+kind+' watchpoint','installed':False,'removed':False}
            key='gpio18_read_observation' if args.watch_gpio18_read else ('snapshot_boundary_observation' if args.watch_snapshot_boundary else ('controller_first_read_observation' if args.watch_pcie_read else ('init_mask_observation' if args.watch_init_mask else ('app_task_table_read_observation' if args.watch_app_task_table else 'timer_write_observation'))))
            result[key]=guard
            guard['install_request']=f'Z{number},{address:x},4'
            reply=rsp.request(guard['install_request']);guard['install_reply']=reply
            if reply!='OK':raise RuntimeError('QEMU refused original memory watchpoint')
            guard['installed']=True
            try:
                connection.sendall(b'$c#63')
                try:reason=rsp.receive()
                except socket.timeout:
                    guard['bounded_continue_timeout_seconds']=args.watch_seconds
                    connection.sendall(b'\x03');reason=rsp.receive()
                guard['stop_reply']=reason
                qmp_boundary(guard)
                watch=re.search(('rwatch' if number==3 else 'watch')+r':([0-9a-f]+);',reason)
                guard['access_hit']=reason.startswith(('T05','S05')) and watch is not None and int(watch[1],16)==address
                if not guard['access_hit'] and 'bounded_continue_timeout_seconds' not in guard:
                    raise ValueError('stop is not the exact original memory watchpoint')
                thread=re.search(r'thread:([^;]+)',reason)
                if thread is None or rsp.request('Hg'+thread[1])!='OK':raise ValueError('memory stop lacks an owned CPU thread')
                registers=rsp.regs();guard.update(thread=thread[1],registers=registers)
                if args.watch_gpio18_read:guard['gpio_config_ram_tables']=gpio_config_table_context(rsp)
                if args.hypothesis_watchdog4mhz:guard['watchdog_registers']=watchdog_context(rsp)
                pc=int(registers['r15'],16);guard['pc_window_address']=hex(pc-16)
                guard['pc_window_bytes']=rsp.memory(pc-16,64).hex()
                if args.watch_app_task_table:guard['task_record_raw']=rsp.memory(0xeb38b8,40).hex()
                if args.watch_init_mask:
                    guard['record_address']='0xeb56c8';guard['record_raw']=rsp.memory(0xeb56c8,20).hex()
                    guard['group_value_raw']=rsp.memory(0x1a9e53c,4).hex()
                    guard['app_task153']=app_task_context(rsp)
                for name in ('r0','r1','r2','r3','r7','r13','r14'):  # r7 also: the GPIO (port,bit) wrapper keeps its caller's LR at [r7+4]
                    memory_address=int(registers[name],16)&~1
                    if 0x108000<=memory_address<=0x4000000-32:
                        try:guard[name+'_memory']={'address':hex(memory_address),'bytes':rsp.memory(memory_address,32).hex()}
                        except ValueError as error:guard[name+'_memory']={'address':hex(memory_address),'error':str(error)}
            finally:
                remove_debug_point(rsp,guard)
            if args.watch_init_mask and guard['access_hit']:
                step_init_filter(rsp,guard['thread'],guard)
        if breakpoint_requested:
            if args.break_uipc_oom_initialized:address,stage,key=0x56366a,'uipc-oom-initialized','uipc_oom_observation'
            elif args.break_edma_initialized:address,stage,key=0x56d4a2,'edma-initialized','edma_initialization_observation'
            elif args.break_edma_enabled:address,stage,key=0x56d472,'edma-enable-written','edma_enable_observation'
            elif args.break_boot_parser:address,stage,key=0x60cba8,'boot-parser','boot_parser_observation'
            elif args.break_init_group:address,stage,key=0x6349cc,'init-group','init_group_observation'
            elif args.break_init_entry:address,stage,key=0x1535f4,'init-entry','init_entry_observation'
            elif args.break_app_activate:address,stage,key=0x153820,'app-activate-call','app_activate_observation'
            elif args.break_app_start:address,stage,key=0x4b6bf4,'app-start','app_start_observation'
            elif args.break_receiver_create:address,stage,key=0xb1f9ea,'create-call','receiver_create_observation'
            else:address,stage,key=0x4b3a7c,'receiver-entry','receiver_entry_observation'
            original=data[address-0x108000:address-0x108000+8]
            if rsp.memory(address,8)!=original:raise ValueError('original receiver entry bytes changed')
            width=4 if args.break_init_group or args.break_boot_parser else 2
            point={'address':hex(address),'breakpoint_size':width,'instruction_set':'A32' if width==4 else 'Thumb','original_bytes':original.hex(),
                   'installed':False,'removed':False,'entry_hit':False,'stage_hit':False,
                   'stage':stage,
                   'application_reply_verified':False}
            if width==2:point['thumb_breakpoint_size']=2
            result[key]=point
            point['install_request']=f'Z0,{address:x},{width}'
            if rsp.request(point['install_request'])!='OK':raise RuntimeError('cannot install original Thumb receiver breakpoint')
            point['installed']=True
            try:
                connection.sendall(b'$c#63')
                try:reason=rsp.receive()
                except socket.timeout:
                    point['bounded_continue_timeout_seconds']=args.watch_seconds
                    connection.sendall(b'\x03');reason=rsp.receive()
                point['stop_reply']=reason
                qmp_boundary(point)
                thread=re.search(r'thread:([^;]+)',reason)
                if thread is None or rsp.request('Hg'+thread[1])!='OK':raise ValueError('receiver stop has no owned CPU')
                registers=rsp.regs();point.update(thread=thread[1],registers=registers)
                point['descriptor_address']='0x1a52b1c'
                point['descriptor_raw']=rsp.memory(0x1a52b1c,24).hex()
                point['app_task153']=app_task_context(rsp)
                if args.hypothesis_watchdog4mhz:point['watchdog_registers']=watchdog_context(rsp)
                if args.break_edma_enabled:
                    if not args.cp_edma_int_gate:raise ValueError('sideband readback requires the explicitly enabled RW gate model')
                    point['edma_interrupt_enable_raw']=rsp.memory(0xf11e0274,4).hex()
                if args.break_edma_initialized:
                    if not args.cp_edma_direct:raise ValueError('eDMA configuration readback requires direct-model opt-in')
                    point['edma_registers']={hex(a):rsp.memory(a,4).hex() for a in
                        (0xf678000c,0xf678002c,0xf678004c,0xf6780054,0xf6780090,
                         0xf67800a0,0xf67800a8,0xf67800c4)}
                if args.break_uipc_oom_initialized:
                    if not args.cp_uipc_ram:raise ValueError('OOM readback requires explicitly supplied diagnosticRAM')
                    point['original_buffer_pointer_raw']=rsp.memory(0x120f700,4).hex()
                    point['original_oom_prefix_raw']=rsp.memory(0xca21e00,256).hex()
                    point['cleared_samples']={hex(a):rsp.memory(a,32).hex() for a in
                        (0xca21e00+0x100,0xca21e00+0x80000,0xcb21e00-32)}
                if args.break_boot_parser:
                    point['boot_arguments_address']='0x100000'
                    point['boot_arguments_prefix_raw']=rsp.memory(0x100000,128).hex()
                    point['signature_comparison_r0']=registers['r0']
                if args.break_init_group:
                    point['group_value_raw']=rsp.memory(0x1a9e53c,4).hex()
                    if reason.startswith(('T05','S05')) and int(registers['r15'],16)==address:
                        record=int(registers['r10'],16);index=int(registers['r11'],16)
                        if not 0<=index<14 or record!=0xeb55c4+index*20:
                            raise ValueError('initialization filter index/record identity mismatch')
                        point['group_filter_r2']=registers['r2'];point['record_index']=index
                        point['record_address']=hex(record);point['record_raw']=rsp.memory(record,20).hex()
                point['stage_hit']=reason.startswith(('T05','S05')) and int(registers['r15'],16)==address
                point['entry_hit']=point['stage_hit'] and args.break_receiver
                if not point['stage_hit'] and 'bounded_continue_timeout_seconds' not in point:
                    raise ValueError('unexpected stop instead of receiver entry')
            finally:
                remove_debug_point(rsp,point)
        total=0
        for seconds in (() if memory_watch_requested or breakpoint_requested else (3,12,30)):
            connection.sendall(b'$c#63')
            time.sleep(seconds);total+=seconds
            if process.poll() is not None:raise RuntimeError('owned QEMU exited during window')
            connection.sendall(b'\x03');stop=rsp.receive()
            if not stop.startswith(('S','T')):raise ValueError('no closed debugger stop: '+stop)
            snapshot(total)
            result['snapshots'][-1]['stop_reply']=stop
        assert hashlib.sha256(image.read_bytes()).hexdigest()==probe['SHA']
        assert hashlib.sha256(binary.read_bytes()).hexdigest()==qemu_sha
        result.update(observation_completed=True,source_unchanged=True,
                      interpretation='raw snapshots require independent instruction/PC comparison; no progress or receiver success inferred from survival')
    except BaseException as error:
        result['error']=repr(error);raise
    finally:
        if connection is not None:connection.close()
        result['returncode_before_observer_cleanup']=process.poll() if process is not None else None
        result['observer_termination_requested']=False
        if process is not None and process.poll() is None:
            result['observer_termination_requested']=True
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        qmp_cleanup_error=None
        for stream in (qmp_stream,qmp_socket):
            if stream is not None:
                try:stream.close()
                except OSError as error:
                    qmp_cleanup_error=error
                    result['qmp_observation']['cleanup_error']=repr(error)
                    result['observation_completed']=False
        result['qemu_returncode']=process.returncode if process is not None else None
        if args.exception_log:
            log=out/'exceptions.log'
            result['exception_log_bytes']=log.stat().st_size if log.exists() else 0
            result['exception_log_at_limit']=result['exception_log_bytes']>=8*1024**2
        if args.gic_log:
            log=out/'gic.log'
            result['gic_log_bytes']=log.stat().st_size if log.exists() else 0
            result['gic_log_at_limit']=result['gic_log_bytes']>=8*1024**2
        (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        print('CP_PROGRESS_CHECK',out,flush=True)
        if qmp_cleanup_error is not None and sys.exc_info()[0] is None:raise qmp_cleanup_error


if __name__=='__main__':main()
