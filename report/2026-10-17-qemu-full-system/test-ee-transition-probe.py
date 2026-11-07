"""Bounded debugger fixture: preserve original instructions and refuse wrong stops."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'ee-transition-probe.py'))
Probe=API['EeTransitionProbe']


class EeObservation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'console.log').write_text('OBS OBSERVER_READY pid=445 base=0x7f00000000\n')
        self.probe=object.__new__(Probe)
        p=self.probe;p.run=self.root;p.target=None;p.finished=False;p.writes=0
        p.breakpoints={};p.pending=None;p.armed=False;p.enqueue_origins={};p.probe_source_sha256='fixture-source-digest'
        p.boot_callbacks={};p.boot_workers={};p.boot_sequences=set()
        p.local_query_sends={}
        p.points=dict(API['POINTS']);p.object_offsets={};p.libobj_base=None;p.background_objects=set()
        p.current_stop=None
        self.commands=[];self.pauses=0;self.offset=0x339fc70;self.stepped=False
        self.bad_instruction=False;self.bad_step=False;self.close_count=0
        self.reads={};self.extra_registers={}
        self.current_thread='p1.1'
        def stop():self.pauses+=1
        def request(command):
            self.commands.append(command);return 'vCont;c;C;s;S' if command=='vCont?' else 'OK'
        def send(command):
            self.commands.append(command)
            if command.startswith('vCont;s:'):self.stepped=True
        def registers():
            pc=self.offset
            if self.stepped:pc=0x338d998 if pc in (0x339fc70,0x33a5b08) else pc+4
            if self.stepped and self.offset==0x3228cbc:pc=0x3222ad0
            if self.stepped and self.offset==0x34b9524:pc=0x165e890
            if self.stepped and self.offset==0x305ea4c:pc=0x34d1988
            if self.stepped and self.offset==0x305eb84:pc=0x34d1748
            if self.stepped and self.offset==0x305eb40:pc=self.extra_registers.get('x30',0x3000)-0x7f00000000
            if self.stepped and self.offset==0x3535a64:pc=0x165ead0
            if self.stepped and self.offset==0x3535a68:pc=0x3535af8 if self.extra_registers.get('x0',0x1000)&0xffffffff==0 else pc
            obj=p.object_offsets.get(self.offset)
            if self.stepped and obj==0xeda4c:pc=p.libobj_base+0x5a730-0x7f00000000
            if self.stepped and obj==0xeda88:pc=p.libobj_base+0x5a910-0x7f00000000
            if self.stepped and obj==0xeda50 and self.extra_registers.get('x0',0x1000)&0xffffffff:
                pc=p.libobj_base+0xed9f4-0x7f00000000
            if self.bad_step and self.stepped:pc+=4
            return {'pc':0x7f00000000+pc,'x29':0,'x0':0x1000,'x1':0x2000,'x30':0x3000,
                    'x21':0x4000,'x19':0x5000,'sp':0x9090,**self.extra_registers}
        def memory(address,count):
            if (address,count) in self.reads:return self.reads[address,count]
            if address==0x7f00000000+0x7e67700:return bytes(4)
            if address==0x4308:
                self.assertEqual(count,4);return (1).to_bytes(4,'little')
            if address==0x5724:
                self.assertEqual(count,16)
                return b''.join(n.to_bytes(4,'little') for n in (2,3,0,0))
            if address==0x1000:
                self.assertEqual(count,24)
                return b''.join(n.to_bytes(4,'little') for n in (0x2f,1,0,0,1,0))
            if address==0x1770:
                self.assertEqual(count,1);return b'\1'
            if address==0x7f00000000+0x7e4e608:
                self.assertEqual(count,1);return b'\1'
            if address==0x7f00000000+0x7e4e5d0:
                self.assertEqual(count,24);return bytes(24)
            value=p.points[address-0x7f00000000][1]
            return bytes(4) if self.bad_instruction else value
        p.stop_vm=stop;p.request=request;p.send=send;p.registers=registers;p.memory=memory
        p.receive=lambda timeout:f'T05thread:{self.current_thread};' if self.stepped else None
        def close():self.close_count+=1
        p.close=close

    def hit(self,thread='p1.1'):
        self.current_thread=thread
        self.probe.pending=f'T05thread:{thread};';self.stepped=False;self.probe.check()

    def test_arm_capture_step_and_remove(self):
        p=self.probe;p.check();self.assertEqual(len(p.breakpoints),len(API['POINTS'])-1)
        self.hit()
        record=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(record['point'],'rec-still-ee-commit');self.assertEqual(record['ee_before'],0)
        self.assertEqual(len(p.breakpoints),len(API['POINTS'])-1)
        p.end_observation();self.assertFalse(p.breakpoints);self.assertEqual(self.close_count,1)
        self.assertFalse(any(c.startswith(('P','G','M','X')) for c in self.commands))

    def test_wrong_instruction_and_unexpected_stop_rejected(self):
        self.probe.check();self.bad_instruction=True
        with self.assertRaisesRegex(ValueError,'identity'):self.hit()
        self.assertEqual(self.probe.writes,0)
        self.offset=0x1234
        with self.assertRaisesRegex(RuntimeError,'away'):self.hit()

    def test_wrong_step_rejected_before_rearm(self):
        self.probe.check();self.bad_step=True
        with self.assertRaisesRegex(RuntimeError,'successor'):self.hit()
        failure=json.loads((self.root/'ee-transition-step-failure.json').read_text())
        self.assertNotEqual(failure['expected_pc'],failure['registers_after']['pc'])
        self.assertEqual(failure['step_stop'],'T05thread:p1.1;')

    def test_limit_removes_all_and_retains_noncompletion(self):
        self.probe.LIMIT=1;self.probe.check();self.hit()
        self.assertTrue(self.probe.finished);self.assertFalse(self.probe.breakpoints)
        self.assertFalse(any(c.startswith('vCont;s:') for c in self.commands))
        summary=json.loads((self.root/'ee-transition-summary.json').read_text())
        self.assertTrue(summary['limit_reached']);self.assertFalse(summary['capture_verified'])

    def test_no_hit_is_reported_as_coverage_not_success(self):
        self.probe.check();self.probe.end_observation()
        summary=json.loads((self.root/'ee-transition-summary.json').read_text())
        self.assertEqual(summary['hits'],0);self.assertTrue(summary['armed'])
        self.assertFalse(summary['capture_verified'])

    def test_entry_gate_reads_only_original_local_fields(self):
        self.offset=0x33aa9e8;self.probe.check();self.hit()
        record=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(record['entry_gate_value'],1)
        self.assertEqual(record['original_transition_words_724_to_730'],[2,3,0,0])

    def test_original_mode_request_and_batch_queue_are_read_only(self):
        self.offset=0x248ff44;self.probe.check();self.hit()
        record=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(record['request']['tag'],'0x2f')
        self.assertEqual(record['request']['accepted_byte_770'],'01')
        self.assertEqual(record['batch_collection_enabled'],1)

    def test_request_tag_must_match_dispatch_point(self):
        self.offset=0x2483104;self.probe.check()
        with self.assertRaisesRegex(ValueError,'request tag'):self.hit()

    def queue_fixture(self):
        base=0x7f00000000
        self.reads[0x2000,16]=(base+0x5b38978).to_bytes(8,'little')+(0x8000).to_bytes(8,'little')
        self.reads[0x8000,0x1b8]=bytes(0x1b8)
        self.reads[0x1320,24]=(0x1320).to_bytes(8,'little')*2+bytes(8)
        self.reads[0x1398,8]=bytes(8)

    def test_scheduler_transfer_arms_enqueue_only_after_mode_factory(self):
        self.offset=0x3228cbc;self.queue_fixture();self.probe.check()
        self.assertNotIn(0x7f00000000+0x3222c34,self.probe.breakpoints)
        self.hit()
        self.assertIn(0x7f00000000+0x3222c34,self.probe.breakpoints)
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(row['sequence']['pointer'],'0x2000')
        self.assertEqual(row['queue0']['nodes'],[])
        self.assertFalse(row['queue0']['sample_truncated'])
        self.assertIsNone(row['queue0']['active'])
        self.assertEqual(self.probe.enqueue_origins,{('p1.1',0x1000,0x9000):0x2000})

    def test_enqueue_followup_is_one_shot_and_keeps_original_descriptor(self):
        self.queue_fixture();self.probe.check();self.offset=0x3222c34
        self.probe.breakpoints[0x7f00000000+self.offset]=self.offset
        self.probe.enqueue_origins['p1.1',0x1000,0x9000]=0x2000
        self.extra_registers={'x19':0x1000,'x29':0x9000}
        self.reads[0x9064,4]=(0x2f).to_bytes(4,'little')
        self.reads[0x9068,8]=(0x2000).to_bytes(8,'little')
        self.reads[0x9000,16]=bytes(16)
        self.hit()
        self.assertNotIn(0x7f00000000+self.offset,self.probe.breakpoints)
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertNotIn('sequence',row)
        self.assertEqual(row['queue0']['nodes'],[])
        self.assertEqual(row['origin']['sequence_pointer'],'0x2000')
        self.assertFalse(any(c.startswith(('P','G','M','X')) for c in self.commands))

    def test_unrelated_enqueue_keeps_followup_without_using_hit_limit(self):
        self.probe.check();self.offset=0x3222c34
        self.probe.breakpoints[0x7f00000000+self.offset]=self.offset
        self.probe.enqueue_origins['p1.1',0x1000,0x9000]=0x2000
        self.reads[0x64,4]=(0x4df).to_bytes(4,'little')
        self.hit()
        self.assertEqual(self.probe.writes,0)
        self.assertFalse((self.root/'ee-transition-hits.jsonl').exists())
        self.assertIn(0x7f00000000+self.offset,self.probe.breakpoints)

    def test_same_tag_wrong_manager_thread_or_frame_cannot_consume_origin(self):
        self.probe.check();self.offset=0x3222c34
        self.probe.breakpoints[0x7f00000000+self.offset]=self.offset
        self.probe.enqueue_origins['p1.1',0x1000,0x9000]=0x2000
        self.reads[0x9064,4]=(0x2f).to_bytes(4,'little')
        for thread,manager,frame in [('p1.1',0x2000,0x9000),('p1.2',0x1000,0x9000),('p1.1',0x1000,0xa000)]:
            with self.subTest(thread=thread,manager=manager,frame=frame):
                self.extra_registers={'x19':manager,'x29':frame}
                self.reads[frame,16]=bytes(16);self.hit(thread)
                self.assertEqual(self.probe.writes,0)
                self.assertEqual(len(self.probe.enqueue_origins),1)
                self.assertIn(0x7f00000000+self.offset,self.probe.breakpoints)

    def test_active_dependencies_require_original_low31_ready_value(self):
        self.queue_fixture()
        descriptor=bytearray(0x1b8)
        for offset,value in ((0x1a0,0xa000),(0x1a8,0xa048),(0x1b0,0xa048)):
            descriptor[offset:offset+8]=value.to_bytes(8,'little')
        self.reads[0x8000,0x1b8]=bytes(descriptor)
        for i,status in enumerate((0x80000000,0x80000001,2)):
            state=0xb000+i*0x100
            self.reads[0xa000+i*24,24]=state.to_bytes(8,'little')+bytes(8)+(0x132+i).to_bytes(8,'little')
            self.reads[state+16,4]=status.to_bytes(4,'little')
        result=self.probe.sequence_snapshot(0x2000)
        self.assertEqual([d['ready'] for d in result['dependencies']],[False,True,False])
        self.assertFalse(result['dependencies_truncated'])

    def test_dependency_invalid_vector_is_rejected_before_dereferencing(self):
        self.queue_fixture();descriptor=bytearray(0x1b8)
        descriptor[0x1a0:0x1a8]=(0x1000).to_bytes(8,'little')
        self.reads[0x8000,0x1b8]=bytes(descriptor)
        with self.assertRaisesRegex(ValueError,'bounds'):self.probe.sequence_snapshot(0x2000)

    def test_boot_replay_page_guard_and_saved_register_readback(self):
        self.probe.check();self.offset=0x305e9c8
        self.extra_registers={'x20':0x7f00000000+0x4c14000}
        self.reads[0x7f00000000+0x305e9b8,16]=bytes.fromhex('fd7bb7a9fd030091f35301a9b4dd00d0')
        self.reads[0x90a0,16]=bytes(range(16));self.hit()
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(row['original_saved_x19_x20_hex'],bytes(range(16)).hex())
        self.assertEqual(row['original_boot_page_address'],hex(0x7f00000000+0x4c14000))
        self.assertTrue(row['boot_entry_matches_unpatched_original'])

    def test_boot_replay_wrong_page_rejected(self):
        self.probe.check();self.offset=0x305e9c8;self.extra_registers={'x20':0}
        with self.assertRaisesRegex(ValueError,'page address'):self.hit()

    def test_original_boot_callback_binds_worker_and_wait_without_reading_transferred_callback(self):
        self.probe.check();self.offset=0x305b5a0
        self.reads[0x2000,32]=b''.join(v.to_bytes(8,'little') for v in (0x7f00000000+0x5b30e48,0x6000,0x7f00000000+0x3062e3c,0))
        self.hit();self.assertEqual(self.probe.boot_callbacks,{0x2000:0x6000})
        del self.reads[0x2000,32]
        self.offset=0x34b9134;self.extra_registers={'x20':0x2000}
        self.reads[0x4000,0x28]=bytes(0x28)
        self.reads[0x1000,0x38]=bytes(0x38);self.hit()
        self.assertIn(0x1000,self.probe.boot_workers)
        self.assertNotIn(0x2000,self.probe.boot_callbacks)
        self.offset=0x34b9524;self.extra_registers={'x19':0x1000};self.hit()
        rows=[json.loads(line) for line in (self.root/'ee-transition-hits.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['boot_worker']['wait_object'],'0x1068')
        self.assertFalse(any(c.startswith(('P','G','M','X')) for c in self.commands))

    def test_unrelated_worker_and_boot_callback_are_not_attributed(self):
        self.probe.check();self.offset=0x34b9134;self.extra_registers={'x20':0x9999};self.hit()
        self.offset=0x34b9524;self.extra_registers={'x19':0x1000};self.hit()
        self.offset=0x3062e3c;self.hit()
        self.assertEqual(self.probe.writes,0)
        self.assertFalse((self.root/'ee-transition-hits.jsonl').exists())

    def test_bound_boot_callback_entry_and_changed_worker_gate(self):
        self.probe.boot_sequences.add(0x1000)
        self.probe.check();self.offset=0x3062e3c;self.hit()
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(row['boot_callback_sequence_pointer'],'0x1000')
        self.probe.boot_workers[0x5000]={};self.offset=0x34b9524
        raw=bytearray(0x38);raw[0x20]=1;self.reads[0x5000,0x38]=bytes(raw)
        with self.assertRaisesRegex(ValueError,'wait gate'):self.hit()

    def test_shared_callback_constructor_preserves_unrelated_function(self):
        self.probe.check();self.offset=0x305b5a0
        self.reads[0x2000,32]=b''.join(v.to_bytes(8,'little') for v in (0x7f00000000+0x5b30e48,0x6000,0x7f00000000+0x123456,0))
        self.hit()
        self.assertEqual(self.probe.writes,0)
        self.assertFalse(self.probe.boot_callbacks)
        self.assertFalse((self.root/'ee-transition-hits.jsonl').exists())
        self.assertIn('vCont;s:p1.1',self.commands)

    def test_directed_step_never_resumes_other_cpus(self):
        self.probe.check();self.hit()
        steps=[c for c in self.commands if c.startswith('vCont;')]
        self.assertEqual(steps,['vCont;s:p1.1'])
        self.assertNotIn('s',self.commands)
        trace=json.loads((self.root/'ee-transition-steps.jsonl').read_text())
        self.assertEqual(trace['expected_pc'],trace['registers_after']['pc'])

    def test_consumed_callback_address_reuse_cannot_bind_another_worker(self):
        self.probe.check();self.offset=0x34b9134
        self.probe.boot_callbacks[0x2000]=0x6000
        self.extra_registers={'x20':0x2000};self.reads[0x1000,0x38]=bytes(0x38);self.reads[0x4000,0x28]=bytes(0x28)
        self.hit();self.assertEqual(self.probe.writes,1)
        self.hit();self.assertEqual(self.probe.writes,1)
        self.assertEqual(len(self.probe.boot_workers),1)

    def test_completion_return_clears_worker_before_idle_or_reuse(self):
        self.probe.check();self.offset=0x34b9568
        self.probe.boot_workers[0x5000]={'callback_pointer':'0x2000','sequence_pointer':'0x6000','completion_pointer':'0x4000'}
        raw=bytearray(0x38);raw[0x28:0x30]=(0x2000).to_bytes(8,'little');raw[0x30:0x38]=(0x4000).to_bytes(8,'little')
        self.reads[0x5000,0x38]=bytes(raw);self.reads[0x4000,0x28]=bytes(0x28)
        self.hit();self.assertIn(0x5000,self.probe.boot_workers)
        self.offset=0x34b9578;self.hit();self.assertNotIn(0x5000,self.probe.boot_workers)
        self.offset=0x34b9524;self.hit();self.assertEqual(self.probe.writes,2)

    def test_boot_cap_read_branch_is_derived_from_original_fields(self):
        self.probe.check();self.offset=0x305e9f0
        raw=bytearray(28)
        for offset,value in ((0,2),(12,0),(24,0x1b)):raw[offset:offset+4]=value.to_bytes(4,'little')
        self.reads[0x5068,28]=bytes(raw);self.hit()
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertTrue(row['original_ee_cap_read_branch']['condition_matches'])

    def test_ee_cap_call_and_return_keep_raw_control_and_original_value(self):
        self.probe.check();self.offset=0x305ea4c
        self.reads[0x48,8]=bytes(range(8));self.hit()
        self.offset=0x305ea50;self.reads[0x50,4]=(3).to_bytes(4,'little');self.hit()
        rows=[json.loads(line) for line in (self.root/'ee-transition-hits.jsonl').read_text().splitlines()]
        self.assertEqual(rows[0]['ee_cap_control_hex'],bytes(range(8)).hex())
        self.assertNotIn('original_ee_cap_returned_value',rows[0])
        self.assertEqual(rows[1]['original_ee_cap_returned_value'],3)

    def test_alternate_query_value_is_read_only_after_original_return(self):
        self.probe.check();self.offset=0x305eb84;self.hit()
        self.offset=0x305eb88;self.reads[0x58,4]=(1).to_bytes(4,'little');self.hit()
        rows=[json.loads(line) for line in (self.root/'ee-transition-hits.jsonl').read_text().splitlines()]
        self.assertNotIn('original_alternate_query_value',rows[0])
        self.assertEqual(rows[1]['original_alternate_query_value'],1)

    def test_boot_return_follows_original_link_register(self):
        self.probe.check();self.offset=0x305eb40
        self.extra_registers={'x30':0x7f00000000+0x3209e48};self.hit()
        trace=json.loads((self.root/'ee-transition-steps.jsonl').read_text())
        self.assertEqual(trace['expected_pc'],hex(0x7f00000000+0x3209e48))
        self.assertEqual(trace['expected_pc'],trace['registers_after']['pc'])

    def test_local_query_send_does_not_read_request_after_handoff(self):
        self.probe.check();self.offset=0x3535a64
        self.extra_registers={'x0':0x8102021f};self.reads[0x2000,20]=bytes.fromhex('1000000020000000'+'00'*12)
        self.hit();self.assertEqual(self.probe.local_query_sends,{('p1.1',0):0x2000})
        del self.reads[0x2000,20]
        self.offset=0x3535a68;self.extra_registers={'x0':0};self.hit()
        self.assertFalse(self.probe.local_query_sends)
        rows=[json.loads(line) for line in (self.root/'ee-transition-hits.jsonl').read_text().splitlines()]
        self.assertEqual(rows[-1]['local_query']['original_send_rc'],0)
        self.assertTrue(rows[-1]['local_query']['transport_only'])

    def test_local_reply_only_records_header_without_claiming_message_size(self):
        self.probe.check();self.offset=0x3531574;self.extra_registers={'x20':0x8102021f}
        self.reads[0x5000,8]=bytes.fromhex('1100000020000000');self.hit()
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertTrue(row['local_query_reply']['key_20_type_11'])
        self.assertFalse(row['local_query_reply']['actual_message_size_verified'])

    def arm_object_points(self):
        with (self.root/'console.log').open('a') as out:out.write('OBS OSD_PROBES_ARMED libObj=0x7f10000000 set_entry=+0x27ec98\n')
        self.probe.check()

    def test_cross_image_consumer_uses_observed_library_base_and_original_state(self):
        self.arm_object_points();self.offset=0x10000000+0xee358
        self.extra_registers={'x2':0x80020002}
        self.reads[0x2000,8]=bytes.fromhex('1000000020000000');self.reads[0x1008,4]=(1).to_bytes(4,'little')
        self.hit()
        row=json.loads((self.root/'ee-transition-hits.jsonl').read_text())
        self.assertEqual(row['image'],'libObj.so');self.assertEqual(row['elf_pc'],'0xee358')
        self.assertEqual(row['camera_background']['state'],1)
        self.assertEqual(self.probe.background_objects,{0x1000})
        self.probe.end_observation();self.assertFalse(self.probe.breakpoints)

    def test_background_cp_send_and_receive_keep_handoff_and_original_sid(self):
        self.arm_object_points();self.probe.background_objects.add(0x1000)
        self.offset=0x10000000+0xeda4c
        self.extra_registers={'x0':0x90030001,'x21':0x1000,'x20':0x3007}
        self.reads[0x2000,24]=bytes.fromhex('00000730'+'00'*20)
        self.reads[0x4c,4]=(0x81cf0001).to_bytes(4,'little');self.hit()
        del self.reads[0x2000,24]
        self.offset=0x10000000+0xeda50
        self.extra_registers={'x0':0,'x21':0x1000,'x20':0x3007};self.hit()
        self.offset=0x10000000+0xeda88
        self.extra_registers={'x0':0x81cf0001,'x21':0x1000,'x20':0x3007,'x2':0xffffffff};self.hit()
        rows=[json.loads(line) for line in (self.root/'ee-transition-hits.jsonl').read_text().splitlines()]
        self.assertEqual(rows[0]['camera_background']['reply_sid'],'0x81cf0001')
        self.assertEqual(rows[1]['camera_background']['original_cp_send_rc'],0)
        self.assertEqual(rows[2]['camera_background']['receive_sid'],'0x81cf0001')
        self.assertFalse(any(c.startswith(('P','G','M','X')) for c in self.commands))

    def test_other_background_source_does_not_establish_query_ownership(self):
        self.arm_object_points();self.offset=0x10000000+0xee358
        self.extra_registers={'x2':0x90030001};self.hit()
        self.assertFalse(self.probe.background_objects);self.assertEqual(self.probe.writes,0)

    def test_failed_memory_read_preserves_address_and_stop_without_inventing_bytes(self):
        self.probe.base=0x7f00000000;self.probe.current_stop={'pc':'0x1234','reason':'T05thread:01;'}
        def rejected(command):raise RuntimeError('QEMU fatal-probe RSP error: E14')
        self.probe.request=rejected
        with self.assertRaisesRegex(RuntimeError,'E14'):Probe.memory(self.probe,0x5678,24)
        row=json.loads((self.root/'ee-transition-memory-errors.jsonl').read_text())
        self.assertEqual(row['address'],'0x5678');self.assertEqual(row['bytes'],24)
        self.assertEqual(row['last_stop']['pc'],'0x1234')
        self.assertNotIn('data',row)


if __name__=='__main__':unittest.main()
