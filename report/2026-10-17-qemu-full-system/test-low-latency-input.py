#!/usr/bin/env python3
import argparse
import hashlib
import io
import json
import mmap
import os
from pathlib import Path
import runpy
import secrets
import socket
import struct
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'low-latency-input.py'))
Client=API['LowLatencyInput']


def raw(code,status):
    return f'/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {status:#x} 0 1'


def tap(code):
    return raw(code,1)+'; pressed=$?; sleep 0.05; '+raw(code,0)+'; released=$?; test "$pressed" = 0 && test "$released" = 0'


class PacketTest(unittest.TestCase):
    def test_actual_ui_tap_preserves_raw_route_and_guest_50ms_release(self):
        fields=struct.unpack('<8I',API['parse_command'](tap(0x1ab)))
        self.assertEqual(fields[:7],(2,0x1ab,1,50,32,0,0))
        self.assertEqual(fields[7],API['checksum'](struct.pack('<7I',*fields[:7])))

    def test_exact_rust_shutter_is_a_fixed_four_stage_command(self):
        command=''.join(f'{raw(code,status)}; step{index}=$?; sleep 0.05; '
            for index,(code,status) in enumerate(((0x1f1,1),(0xa7,1),(0xa7,0),(0x1f1,0))))
        command+='test "$step0" = 0 && test "$step1" = 0 && test "$step2" = 0 && test "$step3" = 0\n'
        self.assertEqual(struct.unpack('<8I',API['parse_command'](command))[:4],(5,0,0,50))
        for changed in [command+'echo hidden',command.replace('sleep 0.05','sleep 0.01',1),
                        command.replace(raw(0xa7,0),raw(0x1f1,0)),command.replace('"$step3" = 0','true')]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):API['parse_command'](changed)
        with self.assertRaises(ValueError):API['packet'](5,0,0,10)

    def test_signed_coalesced_wheel_delta_is_preserved_not_reordered_or_dropped(self):
        for status in [1024,(-1024)&0xffffffff,(-24)&0xffffffff,24]:
            self.assertEqual(struct.unpack('<8I',API['parse_command'](raw(0x1000001d,status)))[2],status)

    def test_bad_key_status_and_pulse_domains_fail_before_publication(self):
        for values in [(1,0xdeadbeef,1,0),(1,0x1ab,2,0),(2,0x1ab,1,0),(2,0x10000013,1,50),
                       (1,0x7025,2,0),(1,0x71c9,0,0),(1,0x10000013,32769,0),(3,1,0,0)]:
            with self.subTest(values=values),self.assertRaises(ValueError):API['packet'](*values)

    def test_other_serial_diagnostics_have_an_explicit_non_input_result(self):
        self.assertIsNone(API['parse_command']('cat /tmp/ramfb-viewer.status'))
        self.assertIsNone(API['parse_command']('echo '+('x'*5000)))

    def test_foreign_queue_app_callback_and_shell_suffix_do_not_fall_back_to_uart(self):
        for text in [raw(0x1ab,1).replace('0x807a0020','0x005503e0'),
                     '/simulation/inject-event 0x5503e0 0x5503e0 '+'00'*32,
                     raw(0x1ab,1)+'; echo hidden',tap(0x1ab).replace(raw(0x1ab,0),raw(0x30,0))]:
            with self.subTest(text=text),self.assertRaises(ValueError):API['parse_command'](text)

    def test_oversize_text_and_non_u32_are_refused(self):
        with self.assertRaises(ValueError):API['parse_command'](raw(0x1ab,1)+'x'*4097)
        for value in [-1,1<<32,True]:
            with self.assertRaises(ValueError):API['packet'](1,0x1ab,value)


class Buffer(bytearray):
    def flush(self):pass
    def close(self):self.was_closed=True


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.client=Client.__new__(Client)
        self.client.run=Path(self.temporary.name)
        self.client.owner=os.getpid();self.client.cookie=b'C'*16
        self.client.mapping=Buffer(4096)
        self.client.mapping[:24]=struct.pack('<Q',API['MAGIC'])+self.client.cookie
        struct.pack_into('<II',self.client.mapping,32,1,1234)
        self.client.pid=1234;self.client.sequence=0;self.client.fault='';self.client.closed=False
        self.client.failed_result=self.client.failed_sequence=self.client.quiesced_after_fault=None
        self.client.fd=self.client.lease=None;self.client.lock=threading.Lock()

    def ack_thread(self,count=1,failure=0):
        mapping=self.client.mapping;seen=[];stop=threading.Event()
        def guest():
            previous=0
            while not stop.is_set():
                sequence=struct.unpack_from('<Q',mapping,40)[0]
                if sequence!=previous:
                    words=struct.unpack_from('<8I',mapping,64)
                    seen.append((sequence,words))
                    struct.pack_into('<I',mapping,56,failure)
                    struct.pack_into('<Q',mapping,48,sequence)
                    if words[0]==4:struct.pack_into('<I',mapping,32,2)
                    previous=sequence
                    if len(seen)>=count:return
                time.sleep(.0001)
        thread=threading.Thread(target=guest);thread.start()
        self.addCleanup(lambda:(stop.set(),thread.join(timeout=1)))
        return seen

    def test_sequence_and_order_preserve_each_tick_and_pulse(self):
        seen=self.ack_thread(3)
        commands=[API['packet'](1,0x1000001d,24),API['packet'](1,0x1000001d,(-24)&0xffffffff),API['packet'](2,0x1ab,1,50)]
        for command in commands:
            receipt=self.client.submit(command)
            self.assertIn(b'LOW_INPUT_DONE profile=mailbox-v1',receipt)
            self.assertNotIn(b'MENU_DIAG_COMMAND_DONE',receipt)
        self.assertEqual([s for s,_ in seen],[1,2,3])
        self.assertEqual([struct.pack('<8I',*words) for _,words in seen],commands)
        records=[json.loads(line) for line in (self.client.run/'low-input.jsonl').read_text().splitlines()]
        self.assertEqual([r['event'] for r in records],['publish','ack']*3)

    def test_publish_log_failure_does_not_commit_an_input_or_skip_sequence(self):
        with mock.patch.object(self.client,'_journal',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):
                self.client.submit(API['packet'](2,0x1ab,1,50))
        self.assertEqual(self.client._u64(40),0)
        self.assertEqual(self.client.sequence,0)

    def test_timeout_retains_original_sequence_and_blocks_new_input(self):
        with self.assertRaisesRegex(TimeoutError,'ownership uncertain'):
            self.client.submit(API['packet'](2,0x1ab,1,50),timeout=.005)
        sequence=self.client._u64(40)
        with self.assertRaisesRegex(RuntimeError,'ACK missing'):
            self.client.submit(API['packet'](2,0x30,1,50))
        self.assertEqual(self.client._u64(40),sequence)
        self.assertIn('ownership uncertain',self.client.fault)

    def test_daemon_send_failure_is_not_success_or_uart_retry(self):
        self.ack_thread(failure=12)
        with self.assertRaisesRegex(RuntimeError,'rc=12'):
            self.client.submit(API['packet'](2,0x1ab,1,50))
        self.assertIn('rc=12',self.client.fault)

    def test_daemon_death_and_cookie_change_are_refused(self):
        struct.pack_into('<I',self.client.mapping,32,3)
        with self.assertRaisesRegex(RuntimeError,'daemon state=3'):self.client.check()
        self.client.fault='';struct.pack_into('<I',self.client.mapping,32,1)
        self.client.mapping[8]=ord('X')
        with self.assertRaisesRegex(RuntimeError,'identity changed'):self.client.check()

    def test_foreign_process_sender_is_refused(self):
        self.client.owner+=1
        with self.assertRaisesRegex(ValueError,'process owner'):self.client.submit(API['packet'](3))
        self.assertEqual(self.client._u64(40),0)

    def test_oversize_and_corrupt_packet_leave_original_slot_untouched(self):
        for body in [b'x'*4097,b'\0'*32,API['packet'](3)[:-1]+b'x']:
            with self.assertRaises(ValueError):self.client.submit(body)
        self.assertEqual(self.client._u64(40),0)

    def test_cancel_and_stop_are_ordered_and_confirm_no_held_contacts(self):
        seen=self.ack_thread(2)
        self.client.cancel();self.client.close()
        self.assertEqual([words[0] for _,words in seen],[3,4])
        self.assertTrue(self.client.closed)
        self.assertIsNone(self.client.mapping)

    def fault_exit(self,result=10):
        self.client.sequence=1
        self.client.fault=f'Original low-input send failed rc={result}, held=0'
        self.client.failed_sequence=1;self.client.failed_result=result
        struct.pack_into('<I',self.client.mapping,32,3)
        struct.pack_into('<QQII',self.client.mapping,40,1,1,result,0)

    def test_allocation_fault_exit_can_release_host_resources_without_success(self):
        self.fault_exit()
        original=self.client.fault
        with mock.patch.object(self.client,'submit') as submit:self.client.close()
        submit.assert_not_called()
        self.assertTrue(self.client.closed)
        self.assertEqual(self.client.fault,original)
        self.assertEqual(self.client.quiesced_after_fault,dict(original_fault=original,result=10,
            sequence=1,guest_state=3,confirmed_no_held=True))
        self.assertIsNone(self.client.mapping)
        records=[json.loads(line) for line in (self.client.run/'low-input.jsonl').read_text().splitlines()]
        self.assertEqual([row['event'] for row in records],['quiesced_after_fault'])
        self.assertNotIn('ack',[row['event'] for row in records])

    def test_source_fault_exit_preserves_original_result(self):
        self.fault_exit(11)
        self.client.close()
        self.assertEqual(self.client.quiesced_after_fault['result'],11)
        self.assertIn('rc=11',self.client.fault)

    def test_fault_close_rejects_wrong_identity_held_sequence_result_or_state(self):
        cases=[('cookie',lambda m:m.__setitem__(8,ord('X'))),
            ('magic',lambda m:m.__setitem__(0,0)),
            ('pid',lambda m:struct.pack_into('<I',m,36,9999)),
            ('held',lambda m:struct.pack_into('<I',m,60,1)),
            ('missing_ack',lambda m:struct.pack_into('<Q',m,48,0)),
            ('foreign_submit',lambda m:struct.pack_into('<Q',m,40,2)),
            ('different_result',lambda m:struct.pack_into('<I',m,56,11)),
            ('normal_stop_is_not_fault_cleanup',lambda m:struct.pack_into('<I',m,32,2)),
            ('not_exited',lambda m:struct.pack_into('<I',m,32,1))]
        original=bytes(self.client.mapping)
        for name,change in cases:
            with self.subTest(name=name):
                self.client.mapping=Buffer(original);self.client.closed=False
                self.client.quiesced_after_fault=None;self.fault_exit();change(self.client.mapping)
                with self.assertRaises((ValueError,RuntimeError)):self.client.close()
                self.assertFalse(self.client.closed)
                self.assertIsNone(self.client.quiesced_after_fault)

    def test_send_failure_and_late_ack_after_timeout_cannot_confirm_quiescence(self):
        self.fault_exit(12)
        with self.assertRaises(RuntimeError):self.client.close()
        self.assertFalse(self.client.closed)
        self.client.mapping=Buffer(4096)
        self.client.mapping[:24]=struct.pack('<Q',API['MAGIC'])+self.client.cookie
        struct.pack_into('<II',self.client.mapping,32,3,1234)
        self.fault_exit(10)
        self.client.fault='Guest low-input ACK missing; release/ownership uncertain'
        self.client.failed_result=self.client.failed_sequence=None
        with self.assertRaises(RuntimeError):self.client.close()
        self.assertFalse(self.client.closed)

    def test_fault_close_refuses_another_process_owner(self):
        self.fault_exit();self.client.owner+=1
        with self.assertRaisesRegex(ValueError,'process owner'):self.client.close()
        self.assertFalse(self.client.closed)

    def test_unacknowledged_previous_owner_is_not_overwritten(self):
        struct.pack_into('<Q',self.client.mapping,40,99)
        with self.assertRaisesRegex(RuntimeError,'unacknowledged owner'):self.client.submit(API['packet'](3))
        self.assertEqual(self.client._u64(40),99)

    def test_foreign_run_is_refused_before_opening_backend(self):
        (self.client.run/'inputs.json').write_text(json.dumps({'host_runner_pid':os.getpid()+1,'low_latency_input':{'profile':'mailbox-v1'}}))
        with self.assertRaisesRegex(ValueError,'Foreign run'):Client(self.client.run,None,None)

    def test_preparation_refuses_production_or_ordinary_foreign_runtime(self):
        with self.assertRaisesRegex(ValueError,'independent low-input runtime'):API['prepare'](self.client.run)


class RuntimeIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.run=self.root/'run';self.run.mkdir()
        self.meta={'profile':'mailbox-v1','physical':API['PHYSICAL'],'capacity':API['CAPACITY'],
                   'ram_base':API['RAM_BASE'],'ram_bytes':API['RAM_BYTES']}
        self.inputs={'host_runner_pid':os.getpid(),'low_latency_input':self.meta,
                     'experiment':{'low_latency_input':'mailbox-v1'}}

    def write_inputs(self):
        (self.run/'inputs.json').write_text(json.dumps(self.inputs))

    def test_mailbox_runtime_never_silently_selects_uart(self):
        analysis=self.root/'analysis';analysis.mkdir()
        (analysis/'full-system.json').write_text(json.dumps({'low_latency_input':self.meta}))
        with self.assertRaisesRegex(ValueError,'not the UART profile'):API['validate_runtime'](self.root,'uart')
        (analysis/'full-system.json').write_text('{}')
        API['validate_runtime'](self.root,'uart')
        with self.assertRaisesRegex(ValueError,'independently prepared'):API['validate_runtime'](self.root,'mailbox-v1')

    def test_wrong_physical_mapping_fails_before_any_qmp_command(self):
        self.meta['physical']+=4096;self.write_inputs()
        with self.assertRaisesRegex(ValueError,'mapping identity'):Client(self.run,None,None)

    def test_flag_must_match_prepared_profile(self):
        self.inputs['experiment']['low_latency_input']='uart';self.write_inputs()
        with self.assertRaisesRegex(ValueError,'did not select'):Client(self.run,None,None)

    def test_second_sender_cannot_acquire_same_run_lease(self):
        import fcntl
        self.write_inputs()
        with (self.run/'low-input.lease').open('a') as lease:
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):Client(self.run,None,None)

    def test_symlink_and_oversize_ram_backend_are_refused(self):
        self.write_inputs()
        backend=self.run/'low-input-ram.bin'
        target=self.root/'foreign';target.write_bytes(b'x')
        backend.symlink_to(target)
        with self.assertRaises(OSError):Client(self.run,None,None)
        backend.unlink();backend.write_bytes(b'x'*4096)
        with self.assertRaisesRegex(ValueError,'exact-size'):Client(self.run,None,None)

    def test_foreign_qmp_mapping_readback_is_refused_before_daemon_start(self):
        self.write_inputs()
        backend=self.run/'low-input-ram.bin'
        with backend.open('wb') as out:out.truncate(API['RAM_BYTES'])
        def qmp(name,arguments):
            self.assertEqual(name,'pmemsave')
            (self.run/'low-input-map-readback.bin').write_bytes(b'foreign')
        serial=mock.Mock()
        with self.assertRaisesRegex(ValueError,'physical readback'):Client(self.run,qmp,serial)
        serial.assert_not_called()


class RamCapacityTest(unittest.TestCase):
    def adapter(self):
        return ('memory_config="$ram_mb"\nif [[ "$boot_memory" == 1 ]]; then\n  memory_config=16384\nfi\n'
            'if [[ "$high_ddr" == 1 ]]; then\n  memory_config=24576\nfi\n'
            '-accel tcg,thread="${QEMU_TCG_THREAD:-single}" -machine virt,secure=off -cpu cortex-a35 -m "$memory_config"\n')

    def test_backend_and_machine_share_the_exact_24gib_capacity(self):
        self.assertEqual(API['RAM_BYTES'],24*1024**3)
        wired=API['ram_backend_adapter'](self.adapter())
        self.assertIn('size=25769803776,',wired)
        self.assertNotIn('size=16G',wired)
        self.assertEqual(API['ram_backend_adapter'](wired,prepared=True),wired)

    def test_changed_dynamic_duplicate_or_unknown_final_ram_is_refused(self):
        original=self.adapter()
        variants=[original.replace('24576','16384'),original.replace('24576','32768'),
                  original.replace('24576','"$ram_mb"'),original+'memory_config=24576\n',
                  original.replace('  memory_config=16384','  memory_config=24576'),
                  original.replace('-m "$memory_config"','-m 24576')]
        for variant in variants:
            with self.subTest(variant=variant),self.assertRaises(ValueError):API['ram_backend_adapter'](variant)

    def test_16g_prepared_backend_is_refused_despite_a_24g_machine(self):
        wired=API['ram_backend_adapter'](self.adapter())
        with self.assertRaisesRegex(ValueError,'backend size/wiring'):
            API['ram_backend_adapter'](wired.replace('size=25769803776','size=16G'),prepared=True)

    def test_runtime_binds_actual_adapter_to_both_manifest_and_input_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Path(directory);analysis=runtime/'analysis';analysis.mkdir()
            adapter=analysis/'qemu-kernel-probe.sh'
            adapter.write_text(API['ram_backend_adapter'](self.adapter()))
            actual=API['digest'](adapter)
            metadata={'profile':'mailbox-v1','physical':API['PHYSICAL'],'capacity':API['CAPACITY'],
                'ram_base':API['RAM_BASE'],'ram_bytes':API['RAM_BYTES'],'machine_ram_mib':24576,
                'board_adapter_sha256':actual,'host_source_sha256':API['digest'](HERE/'low-latency-input.py'),
                'source_sha256':API['digest'](HERE/'guest/low-latency-input.c'),'helper_sha256':'helper'}
            manifest={'board_adapter_sha256':actual,'low_latency_input':metadata}
            path=analysis/'full-system.json';path.write_text(json.dumps(manifest))
            def digest(path):
                if str(path).endswith('/root/simulation/low-latency-input'):return 'helper'
                with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()
            with mock.patch.dict(API['validate_runtime'].__globals__,digest=digest):
                API['validate_runtime'](runtime,'mailbox-v1')
                adapter.write_text(adapter.read_text()+'# changed after preparation\n')
                with self.assertRaisesRegex(ValueError,'adapter identity'):API['validate_runtime'](runtime,'mailbox-v1')
                manifest['board_adapter_sha256']=digest(adapter);path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError,'adapter identity'):API['validate_runtime'](runtime,'mailbox-v1')
                metadata['board_adapter_sha256']=manifest['board_adapter_sha256'];metadata['ram_bytes']=16*1024**3
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError,'geometry'):API['validate_runtime'](runtime,'mailbox-v1')


def qemu_ram_smoke(binary,evidence):
    binary=Path(binary).resolve(strict=True);evidence=Path(evidence).resolve()
    permitted=HERE.parents[1]/'analysis/scratch/a7c2-ui-latency-20261106/low-input'
    if not evidence.is_relative_to(permitted.resolve()):raise ValueError('Smoke evidence must belong to dedicated low-input scratch')
    evidence.mkdir(parents=True,exist_ok=False)
    backend=evidence/'ram.bin'
    with backend.open('xb') as output:output.truncate(API['RAM_BYTES'])
    backend.chmod(0o600)
    command=[str(binary),'-accel','tcg,thread=single','-machine','virt,secure=off,memory-backend=lowinputram',
        '-cpu','cortex-a35','-m',str(API['RAM_BYTES']//1024**2),'-object',
        f'memory-backend-file,id=lowinputram,size={API["RAM_BYTES"]},mem-path=ram.bin,share=on',
        '-S','-display','none','-nodefaults','-monitor','none','-serial','none','-nic','none',
        '-qmp','unix:qmp.sock,server=on,wait=off','-sandbox','on']
    result={'command':command,'qemu_sha256':API['digest'](binary),'ram_bytes':API['RAM_BYTES'],
        'machine_mib':24576,'kernel_loaded':False,'ap_started':False,'vm_signals_sent':[],'checks':[],'state':'starting'}
    process=sock=stream=None
    def call(name,arguments=None):
        request={'execute':name}
        if arguments is not None:request['arguments']=arguments
        stream.write(json.dumps(request).encode()+b'\n');stream.flush()
        while True:
            line=stream.readline()
            if not line:raise RuntimeError('Owned smoke QMP closed before reply')
            reply=json.loads(line)
            if 'event' in reply:continue
            if 'return' not in reply:raise RuntimeError(str(reply))
            return reply['return']
    try:
        with (evidence/'qemu.log').open('xb') as log:
            process=subprocess.Popen(command,cwd=evidence,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        result['qemu_pid']=process.pid
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Owned smoke QEMU exited before QMP')
            candidate=socket.socket(socket.AF_UNIX);candidate.settimeout(3)
            directory=os.open(evidence,os.O_RDONLY|os.O_DIRECTORY)
            try:
                candidate.connect(f'/proc/self/fd/{directory}/qmp.sock');sock=candidate;break
            except (FileNotFoundError,ConnectionRefusedError):candidate.close();time.sleep(.01)
            finally:os.close(directory)
        if sock is None:raise TimeoutError('Owned smoke QMP listener missing')
        peer=struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if peer[0]!=process.pid or peer[1]!=os.getuid():raise RuntimeError('Foreign smoke QMP owner')
        result['qmp_peer_pid']=peer[0]
        stream=sock.makefile('rwb')
        if 'QMP' not in json.loads(stream.readline()):raise RuntimeError('Bad smoke QMP greeting')
        call('qmp_capabilities')
        result['memory_summary']=call('query-memory-size-summary')
        if result['memory_summary']['base-memory']!=API['RAM_BYTES']:raise AssertionError('Actual QEMU RAM differs from backend')
        with backend.open('r+b') as ram:
            for label,offset in [('mailbox',API['OFFSET']),('last_page',API['RAM_BYTES']-API['CAPACITY'])]:
                expected=secrets.token_bytes(256)
                with mmap.mmap(ram.fileno(),API['CAPACITY'],offset=offset) as mapped:
                    mapped[:len(expected)]=expected;mapped.flush()
                    target=evidence/(label+'-readback.bin')
                    call('pmemsave',{'val':API['RAM_BASE']+offset,'size':len(expected),'filename':str(target)})
                    actual=target.read_bytes()
                    if actual!=expected:raise AssertionError('QMP physical readback differs from host mmap: '+label)
                (evidence/(label+'-expected.bin')).write_bytes(expected)
                result['checks'].append({'label':label,'physical':hex(API['RAM_BASE']+offset),
                    'host_offset':offset,'bytes':len(expected),'sha256':hashlib.sha256(actual).hexdigest(),'matched':True})
        result['state']='verified'
    except BaseException as error:
        result['state']='failed';result['error']=f'{type(error).__name__}: {error}'
        raise
    finally:
        try:
            if process is not None and process.poll() is None:
                if stream is None:raise RuntimeError('No verified QMP connection for signal-free cleanup')
                call('quit');result['qmp_quit']=True
            if process is not None:
                result['returncode']=process.wait(timeout=10)
                if result['returncode']!=0:raise RuntimeError('Owned smoke QEMU returned nonzero')
                result['owner_reaped']=True
        except BaseException as error:
            result['state']='failed';result['cleanup_error']=f'{type(error).__name__}: {error}'
            raise
        finally:
            if stream is not None:stream.close()
            if sock is not None:sock.close()
            result['backend_logical_bytes']=backend.stat().st_size
            result['backend_allocated_bytes']=backend.stat().st_blocks*512
            (evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


class OriginalGuestApiTest(unittest.TestCase):
    def test_compiled_consumer_order_release_failure_source_and_message_ownership(self):
        source=str(HERE/'guest/low-latency-input.c')
        harness=r'''
#define LOW_INPUT_TEST
#include "SOURCE_FILE"
#include <assert.h>
static unsigned buffer[5],observed[64][2],sends,freed,allocated,source_value;
static int fail_send,bad_source,fail_alloc;
int osal_valloc_msg_wait(unsigned queue,void **message,unsigned bytes,int wait){
 assert(queue==QUEUE && bytes==20 && wait==1);allocated++;
 if(fail_alloc){*message=0;errno=EIO;return -73;}*message=buffer;return 0;
}
void osal_set_msg_src(void *message,unsigned source){assert(message==buffer);source_value=source;}
unsigned osal_get_msg_src(void *message){assert(message==buffer);return bad_source?0:source_value;}
int osal_snd_msg(unsigned queue,void *message){
 assert(queue==QUEUE && message==buffer && source_value==SOURCE);
 assert(buffer[1]==0 && buffer[3]==0 && buffer[4]==1);
 observed[sends][0]=buffer[0];observed[sends++][1]=buffer[2];
 memset(buffer,0xa5,sizeof buffer); /* Poison ownership after snd. */
 return fail_send;
}
int osal_free_msg(unsigned queue,void *message){assert(queue==QUEUE && message==buffer);freed++;return 0;}
static int command(unsigned op,unsigned code,unsigned status,unsigned pulse){
 uint32_t words[8]={op,code,status,pulse,32,0,0,0};words[7]=checksum(words);return execute(words,7);
}
int main(void){
 fail_alloc=1;
 assert(command(2,0x1ab,1,50)==10 && !held && sends==0 && allocated==1);
 assert(release_all(1)==0 && allocated==1 && sends==0);
 fail_alloc=0;bad_source=1;
 assert(command(2,0x1ab,1,50)==11 && !held && sends==0 && allocated==2 && freed==1);
 bad_source=0;freed=0;allocated=0;
 assert(command(2,0x1ab,1,50)==0);
 assert(sends==2 && observed[0][1]==1 && observed[1][1]==0 && !held && !freed);
 assert(command(1,0x1f1,1,0)==0 && command(1,0xa7,1,0)==0);
 assert(command(3,0,0,0)==0 && !held);
 assert(observed[4][0]==0xa7 && observed[5][0]==0x1f1);
 unsigned before=sends;
 assert(command(2,0xdeadbeef,1,50)==2 && command(2,0x1ab,1,0)==2 && sends==before);
 assert(command(1,0x1000001d,(unsigned)-24,0)==0 && observed[sends-1][1]==(unsigned)-24);
 fail_send=17;
 assert(command(2,0x1ab,1,50)==12 && held && freed==2);
 fail_send=0;assert(release_all(8)==0 && !held);
 bad_source=1;before=sends;
 assert(command(1,0x1ab,1,0)==11 && sends==before && !held);
 bad_source=0;assert(release_all(9)==0 && !held);
 uint32_t oversized[8]={2,0x1ab,1,50,4096,0,0,0};oversized[7]=checksum(oversized);
 before=sends;assert(execute(oversized,10)==2 && sends==before);
 assert(command(5,0,0,50)==0 && !held && sends==before+4);
 assert(observed[before][0]==0x1f1 && observed[before][1]==1);
 assert(observed[before+1][0]==0xa7 && observed[before+1][1]==1);
 assert(observed[before+2][0]==0xa7 && observed[before+2][1]==0);
 assert(observed[before+3][0]==0x1f1 && observed[before+3][1]==0);
 before=sends;assert(command(5,0,0,10)==2 && sends==before);
 fail_send=17;assert(command(5,0,0,50)==12 && held);
 fail_send=0;assert(release_all(11)==0 && !held);
 assert(command(1,0x1ab,1,0)==0 && held);
 before=sends;unsigned owned=held;fail_alloc=1;
 assert(command(1,0x1ab,0,0)==10 && held==owned && sends==before);
 assert(release_all(12)==10 && held==owned && sends==before);
 fail_alloc=0;assert(release_all(13)==0 && !held);
 puts("LOW_INPUT_ORIGINAL_API_TEST_OK");return 0;
}
'''.replace('SOURCE_FILE',source)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'harness.c').write_text(harness)
            subprocess.run(['cc','-std=c11','-D_POSIX_C_SOURCE=200809L','-O2','-Wall','-Wextra',str(path/'harness.c'),'-o',str(path/'test')],check=True,capture_output=True,timeout=20)
            result=subprocess.run([str(path/'test')],check=True,capture_output=True,timeout=5)
            self.assertIn(b'LOW_INPUT_ORIGINAL_API_TEST_OK',result.stdout)
            self.assertIn(b'alloc_rc=-73 errno=5 message=(nil) held=0',result.stdout)


if __name__=='__main__':
    if '--qemu-ram-smoke' in sys.argv:
        parser=argparse.ArgumentParser(description='Real owned 24GiB RAM smoke; no kernel or AP')
        parser.add_argument('--qemu-ram-smoke',type=Path,required=True)
        parser.add_argument('--evidence-dir',type=Path,required=True)
        args=parser.parse_args()
        print(json.dumps(qemu_ram_smoke(args.qemu_ram_smoke,args.evidence_dir),indent=2))
    else:unittest.main()
