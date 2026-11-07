"""Keep primary debugger failures distinct from cleanup and negative observations."""
from pathlib import Path
import runpy
import json
import struct
import tempfile
from types import SimpleNamespace
import unittest

REMOVE=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['remove_debug_point']
TASK=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['app_task_context']
STEP=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['step_init_filter']
BOOT=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['official_boot_arguments']
RAM=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['ram_window']
WDT=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['watchdog_context']
QMP=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['QMPObserver']
GPIO_TABLE=runpy.run_path(str(Path(__file__).with_name('check-cp-progress.py')))['gpio_config_table_context']


class GPIOConfigTableTests(unittest.TestCase):
    def test_fixed_ram_only_reads_keep_raw_bytes_and_signed_fields(self):
        first=struct.pack('<7I',18,3,1,0xffffffff,1,0xffffffff,0)
        second=struct.pack('<7I',0,0,0,1,0,1,1);raw=first+second;calls=[]
        def memory(address,size):calls.append((address,size));return raw
        tables=GPIO_TABLE(SimpleNamespace(memory=memory))
        self.assertEqual(calls,[(0x1101fc4,56),(0x1101ffc,56)])
        self.assertTrue(all(0x108000<=a and a+n<=0x4000000 for a,n in calls))
        self.assertEqual(tables[0]['raw'],raw.hex())
        self.assertEqual(tables[0]['entries'][0],{'port':18,'pin':3,'selector_u8':1,
                         'direction_i32':-1,'input_enable_u8':1,'pull_i32':-1,'latch_i32':0})

    def test_read_failure_is_not_an_initialized_zero_table(self):
        def memory(address,size):raise ValueError('E14')
        with self.assertRaisesRegex(ValueError,'E14'):GPIO_TABLE(SimpleNamespace(memory=memory))

    def test_short_table_is_rejected_before_decode(self):
        with self.assertRaisesRegex(ValueError,'short GPIO'):
            GPIO_TABLE(SimpleNamespace(memory=lambda address,size:bytes(55)))


class QMPObservationTests(unittest.TestCase):
    def stream(self,messages):
        incoming=iter(json.dumps(m).encode()+b'\n' for m in messages)
        sent=[]
        return SimpleNamespace(readline=lambda bound:next(incoming,b''),write=lambda raw:sent.append(json.loads(raw))),sent

    def test_events_are_retained_across_capability_and_status_replies(self):
        watchdog={'event':'WATCHDOG','data':{'action':'reset'},'timestamp':{'seconds':12,'microseconds':34}}
        reset={'event':'RESET','data':{'guest':False,'reason':'host-qmp-system-reset'}}
        stream,sent=self.stream([{'QMP':{}},watchdog,{'return':{},'id':'observer-1'},reset,
                                 {'return':{'running':False,'status':'debug'},'id':'observer-2'}])
        record={};observer=QMP(stream,record)
        self.assertEqual(observer.command('query-status'),{'running':False,'status':'debug'})
        self.assertEqual([r['message'] for r in record['messages'] if 'event' in r['message']],[watchdog,reset])
        self.assertEqual([r['execute'] for r in sent],['qmp_capabilities','query-status'])
        self.assertEqual(json.loads(bytes.fromhex(record['messages'][1]['raw_hex'])),watchdog)

    def test_reset_or_watchdog_mutation_is_rejected_before_send(self):
        stream,sent=self.stream([{'QMP':{}},{'return':{},'id':'observer-1'}]);observer=QMP(stream,{})
        for name in ('system_reset','set-action','cont','stop','quit'):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'not read-only'):observer.command(name)
        self.assertEqual(len(sent),1)

    def test_disconnect_does_not_become_an_empty_event_history(self):
        stream,_=self.stream([{'QMP':{}}]);record={}
        with self.assertRaisesRegex(EOFError,'disconnected'):QMP(stream,record)
        self.assertEqual(len(record['messages']),1)

    def test_response_errors_and_unmatched_ids_remain_failures(self):
        for reply in ({'id':'observer-1','error':{'class':'GenericError'}},
                      {'id':'wrong','return':{}},{'id':'observer-1'}):
            with self.subTest(reply=reply):
                stream,_=self.stream([{'QMP':{}},reply]);record={}
                with self.assertRaises((RuntimeError,ValueError)):QMP(stream,record)
                self.assertEqual(record['messages'][-1]['message'],reply)

    def test_explicit_event_limit_fails_instead_of_silent_truncation(self):
        stream,_=self.stream([{'QMP':{}}]+[{'event':'RESET'}]*256);record={}
        with self.assertRaisesRegex(ValueError,'wire limit'):QMP(stream,record)
        self.assertTrue(record['limit_exceeded']);self.assertEqual(len(record['messages']),256)
        self.assertEqual(json.loads(bytes.fromhex(record['rejected_raw_hex'])),{'event':'RESET'})

    def test_malformed_or_oversized_wire_is_preserved(self):
        for raw in (b'not-json\n',b'x'*16385):
            with self.subTest(raw_bytes=len(raw)):
                record={};stream=SimpleNamespace(readline=lambda bound:raw)
                with self.assertRaises(ValueError):QMP(stream,record)
                captured=record.get('rejected_raw_hex') or record['messages'][-1]['raw_hex']
                self.assertEqual(bytes.fromhex(captured),raw)


class DebuggerCleanupTests(unittest.TestCase):
    def test_secondary_cleanup_failure_preserves_the_original_disconnect(self):
        record={'removed':False,'install_request':'Z0,4b3a7c,2'}
        def broken(packet):raise BrokenPipeError('closed during cleanup')
        with self.assertRaisesRegex(EOFError,'original disconnect'):
            try:raise EOFError('original disconnect')
            finally:REMOVE(SimpleNamespace(request=broken),record)
        self.assertFalse(record['removed'])
        self.assertIn('BrokenPipeError',record['cleanup_error'])

    def test_cleanup_failure_without_a_primary_error_is_still_fatal(self):
        record={'removed':False,'install_request':'Z0,4b3a7c,2'}
        with self.assertRaises(RuntimeError):
            REMOVE(SimpleNamespace(request=lambda packet:'E22'),record)
        self.assertFalse(record['removed'])
        self.assertIn('cleanup_error',record)

    def test_actual_cleanup_receipt_is_required(self):
        record={'removed':False,'install_request':'Z0,4b3a7c,2'}
        REMOVE(SimpleNamespace(request=lambda packet:'OK'),record)
        self.assertTrue(record['removed'])
        self.assertEqual(record['remove_reply'],'OK')

    def test_cleanup_uses_original_installation_not_later_memory_addresses(self):
        for installed in ('Z0,4b3a7c,2','Z0,6349cc,4','Z2,f1042000,4','Z3,eb38bc,4'):
            with self.subTest(installed=installed):
                requests=[]
                def send(packet):requests.append(packet);return 'OK'
                record={'removed':False,'install_request':installed,
                        'last_memory_read':{'address':'0x5f58bc','bytes':'00'*32}}
                REMOVE(SimpleNamespace(request=send),record)
                self.assertEqual(requests,['z'+installed[1:]])
                self.assertTrue(record['removed'])


class TaskContextTests(unittest.TestCase):
    def test_uninitialized_pointer_does_not_trigger_a_second_read(self):
        calls=[]
        def memory(address,size):calls.append((address,size));return bytes(4)
        self.assertEqual(TASK(SimpleNamespace(memory=memory))['tcb'],'0x0')
        self.assertEqual(calls,[(0x1b30f90,4)])

    def test_invalid_pointer_is_rejected_before_any_mmio_read(self):
        calls=[]
        def memory(address,size):calls.append((address,size));return (0xf13a200c).to_bytes(4,'little')
        with self.assertRaisesRegex(ValueError,'outside diagnostic RAM'):TASK(SimpleNamespace(memory=memory))
        self.assertEqual(calls,[(0x1b30f90,4)])

    def test_real_record_identity_is_separate_from_state(self):
        raw=bytearray(64);raw[8:12]=(0xeb38b4).to_bytes(4,'little');raw[12]=0
        def memory(address,size):
            return (0x2000000).to_bytes(4,'little') if address==0x1b30f90 else bytes(raw)
        result=TASK(SimpleNamespace(memory=memory))
        self.assertTrue(result['record_identity_matches'])
        self.assertEqual(result['state_byte'],0)
        self.assertNotIn('started',result)


class OriginalInitFilterTests(unittest.TestCase):
    def test_original_zero_flag_selects_actual_branch(self):
        for reject in (True,False):
            with self.subTest(reject=reject):
                requests=[]
                frames=iter([{'r15':'0x6349cc','cpsr':'0x0'},
                             {'r15':'0x6349d0','cpsr':hex((1<<30) if reject else 0)},
                             {'r15':hex(0x634da8 if reject else 0x6349d4),'cpsr':'0x0'}])
                def send(packet):
                    requests.append(packet)
                    return 'vCont;c;s' if packet=='vCont?' else 'T05thread:02;'
                record={'registers':{'r15':'0x6349c8','r10':'0xeb56c8','r11':'0xd'}}
                STEP(SimpleNamespace(request=send,regs=lambda:next(frames)),'02',record)
                self.assertTrue(record['original_branch_stepped'])
                self.assertEqual(record['original_group_reject_branch_taken'],reject)
                self.assertEqual(requests,['vCont?']+['vCont;s:02']*3)

    def test_wrong_record_is_not_stepped(self):
        record={'registers':{'r15':'0x6349c8','r10':'0xeb55c4','r11':'0x0'}}
        with self.assertRaisesRegex(ValueError,'not the original last'):
            STEP(SimpleNamespace(),'01',record)

    def test_unexpected_step_stop_is_not_accepted(self):
        record={'registers':{'r15':'0x6349c8','r10':'0xeb56c8','r11':'0xd'}}
        def send(packet):return 'vCont;c;s' if packet=='vCont?' else 'T05thread:03;'
        with self.assertRaisesRegex(ValueError,'unexpected thread'):
            STEP(SimpleNamespace(request=send),'02',record)
        self.assertNotIn('original_branch_stepped',record)


class OfficialBootArgumentsTests(unittest.TestCase):
    def manifest(self):
        return {'source':'official-bodydata-derived',
                'bodydata_sha256':'eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31',
                'images':[{'name':'nflasha8.img','bytes':67108864,
                           'sha256':'c9691b03e3c8b06092c9d75f7552b8e147ec63d3e635e9f4828b754db30765ce'}]}

    def test_private_factory_is_not_used_as_official_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            factory=Path(directory);manifest=self.manifest();manifest['source']='private-device-dump'
            (factory/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'provenance mismatch'):BOOT(factory)

    def test_duplicate_manifest_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            factory=Path(directory);manifest=self.manifest();manifest['images']*=2
            (factory/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'manifest mismatch'):BOOT(factory)

    def test_symlink_image_is_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            factory=Path(directory);(factory/'manifest.json').write_text(json.dumps(self.manifest()))
            (factory/'nflasha8.img').symlink_to(factory/'manifest.json')
            with self.assertRaisesRegex(ValueError,'size/type mismatch'):BOOT(factory)

    def test_correct_size_image_with_wrong_contents_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            factory=Path(directory);(factory/'manifest.json').write_text(json.dumps(self.manifest()))
            with (factory/'nflasha8.img').open('wb') as image:image.truncate(67108864)
            with self.assertRaisesRegex(ValueError,'hash mismatch'):BOOT(factory)


class DiagnosticReadBoundaryTests(unittest.TestCase):
    def test_general_register_pointer_must_not_acknowledge_mmio(self):
        result=RAM(SimpleNamespace(),0xf13a200c)
        self.assertIn('not read',result['error'])
        self.assertNotIn('bytes',result)

    def test_ram_read_failure_is_not_zero_data(self):
        def memory(address,size):raise ValueError('E14')
        result=RAM(SimpleNamespace(memory=memory),0x200000)
        self.assertEqual(result['error'],'E14');self.assertNotIn('bytes',result)

    def test_watchdog_reads_exclude_read_to_clear_eoi(self):
        calls=[]
        def memory(address,size):calls.append((address,size));return bytes(size)
        result=WDT(SimpleNamespace(memory=memory))
        self.assertEqual(set(a for a,s in calls),{0xf1052000,0xf1052004,0xf1052008,0xf1052010,0xf1388340,0xf13883a0})
        self.assertNotIn((0xf1052014,4),calls)
        self.assertEqual(result['control']['raw'],'00000000')
