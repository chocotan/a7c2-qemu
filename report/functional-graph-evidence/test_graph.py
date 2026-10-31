"""HOST_TEST checks only; no VM, C build, or media output.

The complete graph orchestration uses strict mocked dependencies, never an
invented native-positive evaluate() fixture. Wire/condition negatives call the
unchanged real content functions. Actual reason literals below test parsing only.
"""
import copy
import importlib.util
import json
from pathlib import Path
import re
import struct
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).with_name('check_graph.py')
SPEC = importlib.util.spec_from_file_location('functional_graph_under_test', PATH)
v = importlib.util.module_from_spec(SPEC)
exec(compile(PATH.read_bytes(), str(PATH), 'exec'), v.__dict__)


def current_dependencies():
    return {str(v.NATIVE / name): v.sha(v.read(v.NATIVE / name)) for name in v.FROZEN_DEPENDENCIES}


def record(tag, line=1, **fields):
    fields = {key: str(value) for key, value in fields.items()}
    return {'line': line, 'tag': tag, 'fields': fields,
            'raw': 'OBS ' + tag + ' ' + ' '.join(key + '=' + value for key, value in fields.items())}


class GraphEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph, cls.hdmi, cls.osd = v.load_content_helpers(current_dependencies())
        cls.old = cls.graph.old

    def edge(self, spec, index=0):
        prefix, _, _, source, peer = spec
        pid, tid, caller = '701', '723', 0x81cf619b
        wire = self.old.frame_bytes(64, 1, 2, source + peer, caller, b'\xa7\x19\0\x5a')
        request = record(prefix + '_REQUEST', 100 + index * 20, pid=pid, tid=tid,
                         source=hex(caller), destination=hex(source[3]), bytes=64, raw=wire.hex())
        freed = record(prefix + '_REPLY_FREE', 119 + index * 20, pid=pid, tid=tid, bytes=56,
                       destination=hex(caller), rc=0, ap_consumed=1)
        return {'prefix': prefix, 'REQUEST': request, 'REPLY_FREE': freed, 'source_pin': source,
                'sink_pin': peer, 'caller': caller}

    def adf_control_fixture(self):
        """HOST_TEST source-shaped control records; no firmware execution or run replay."""
        rows = []
        zeros = ('original_cp_executed=0 hardware_verified=0 native_frequency_verified=0 '
                 'original_event_identity_verified=0 pcm_verified=0 frames_verified=0 capture_verified=0')
        def add(prefix, suffix, body, tid):
            scope = 'virtualSource7ControlOnly' if prefix == 'FULL_ADF_PROC' else 'virtualInputConfigurationS0'
            rows.append(f'OBS {prefix}_{suffix} {body} pid=701 tid={tid} scope={scope} {zeros}')
        p, s = 'FULL_ADF_PROC', 'FULL_ADF_SET_INPUT'
        add(p, 'REQUEST', 'generation=1 caller=0x81cf619b request=0x1000 bytes=12 raw=0d2023030c00018000000000 request_accepted=1 policy=virtual-source7-control-events-v1 policy_period_ns=1000000 normal_completion=0', 723)
        for event in range(1, 5):
            add(p, 'EVENT', f'generation=1 event={event} guest_timerfd_expirations=1 deadline_ns={event * 1000000} observed_ns={event * 1000000 + 10} policy_period_ns=1000000 hardware_source=7 software_source=5 hardware_counter={event} phase=0 hardware_epoch={event} fb_counter={event} fb_epoch={event} cache_counter={event} cache_epoch={event} getter_advances=0', 800)
            if event < 4:
                add(p, 'AVIO_STAGE', f'generation=1 event={event} priority=4 stage={event - 1} consumed={event} remaining={3 - event} output_finished={int(event == 3)} callbacks={int(event == 3)} source_cache=0xff source=1 shadow_writes={7 if event == 3 else 4} changed_writes={6 if event == 3 else 3} touched_writes={7 if event == 3 else 4} requested_mask=0x8 current_mask={"0x8" if event == 3 else "0"}', 800)
            if event == 3:
                add(p, 'INPUT_QUEUED', 'generation=1 event=3 after_priority=4 selector=0 input_state=1 parameter=0 priority=2 registered=1 scheduler_consumed=0 next_source5_pass_required=1', 800)
        add(p, 'INPUT_DRAINED', 'generation=1 event=4 priority=2 scheduler_consumed=1 control30_consumed=1 callback_status=0 callbacks=1 control31_parameter=0 control31_callback=0 request=0 pending=0 submitted=0 registered=0 listener_removed=1 complete=1', 800)
        add(p, 'APPLIED', 'generation=1 requested_path=0 active_path=0 mode=0 format=0 notify=0 config_commits=1 pending_config=0 global_state=2 idle_stage=7 cold_stop_phase1=1 stop_cleanups=3 start_consumed=1 notification2=1 notification0=1 inner_queued=1 inner_consumed=1 AIP_control_state=2 delay_ready_event=2 events=4 avio_stages=3 avio_callbacks=1 output_requests=1 avio_pending_mask=0 input_complete=1 AF_consumed=1 B0_consumed=1 command_sequence=2 disable_writes=14 common_guard_held=1 inner_request=042002010c00010000000000 inner_completion=042002810c00010000000000 outer_status=0x580000', 800)
        add(p, 'QUEUED', 'generation=1 destination=0x81cf619b source=0x92840747 reply=0x2000 bytes=12 raw=0d2023130c00018000005800 events=4 queued=1', 800)
        add(p, 'COMMIT', 'generation=1 request=0x1000 request_free_rc=0 retained_request=0 clean_completion=1 queued=1 ap_consumed=0 events=4 work_complete=1', 800)
        add(p, 'REPLY_FREE', 'generation=1 destination=0x81cf619b expected=0x81cf619b pointer=0x2000 kind=queued-reply rc=0 faults=0 retained=0 ap_consumed=1 events=4', 723)
        add(s, 'REQUEST', 'generation=2 caller=0x81cf619b request=0x1000 bytes=14 raw=0d2036030e000180000200000000 known_AB_failure_preserved=1 metadata_completion_only=1 normal_completion=0', 723)
        add(s, 'DEPENDENCIES', 'generation=2 original_AP0323_reply_freed=1 same_hotshoe_owner=1 same_glee_owner=1 same_command_buffer=1 same_source7_clock=1 counter_before=4 epoch_before=4 capability_word7=0 capability_word8=1 output_target=8', 801)
        add(s, 'METADATA', 'generation=2 glee_callback_status=0 owner_request_generation=1 hotshoe_callback_running=1 queued_commands=3 active_cache=00020000 completion_mask_consumed=1 digital_pending=0 config_commits=1 inner_queued=1 inner_raw=042001840c00010000000000 AIP102_queued=0 outer_published=0', 801)
        add(s, 'GLEE', 'generation=2 same_initialized_owner=1 owner_request_generation=1 control30_notes=1 control0_callbacks=1 control1_type=0 control1_source=1 control1_callback=0 input_ring=0 kind_cache=0 power20=0 power21=0 power22=0 power_state=2 synchronous_reference_branch=1', 801)
        add(s, 'CONTROL102', 'generation=2 metadata_already_committed=1 control141_queries=2 control141_value=1 selector=2 source_parameters=3/0/0/0/0/0/0/1/0/0 queued=B8/03/02/11/B6/B7 command_count=9 body_bytes=132 control110_parameter=1 existing7c=1 opcode42_queued=0', 801)
        add(s, 'HOTSHOE', 'generation=2 owner_request_generation=1 callbacks=1 callback_returned=1 fifo_popped_before_callback=1 current_type_committed_after_callback=1 current_type=0 busy=0 fifo_count=0 asynchronous_power_work=0', 801)
        for event in range(5, 9):
            add(s, 'EVENT', f'generation=2 event={event} guest_timerfd_expirations=1 deadline_ns={event * 1000000} observed_ns={event * 1000000 + 10} hardware_counter={event} epoch={event} hardware_source=7 software_source=5 subscriber=0x9058003f sender=0x928c0786 queued={event - 4} consumed={event - 4} policy_period_ns=1000000 getter_advances=0', 801)
            add(s, 'AIP_DISPATCH', f'generation=2 event={event} dispatches={event - 4} commands_interpreted=9 AB_status=1 task_rc={"0x1004" if event == 5 else "0"} snapshot_count={9 if event == 5 else 0} checked={2 if event == 5 else 0} cursor_words={6 if event == 5 else 0} first_uninspected_preserved=7 ring_read=9 ring_write=9 failure_history_preserved=1 old_tail_rechecked=0 register_writes=222 register_readbacks=222 original_error_time_verified=0', 801)
        add(s, 'APPLIED', 'generation=2 metadata_cache=00020000 config_commits=1 hotshoe_callbacks=1 glee_callbacks=1 control1_readbacks=1 selector=2 AIP_commands_interpreted=9 AIP_first_checked=2 AIP_uninspected=7 AIP_first_task_rc=0x1004 AB_status=1 AB_register_writes=0 data_config03=1 data_config02=1 inner_consumed=1 outer_status=0x580000 events=4 global_counter=8 hardware_audio_success=0', 801)
        add(s, 'QUEUED', 'generation=2 destination=0x81cf619b source=0x92840747 reply=0x2000 bytes=12 raw=0d2036130c00018000005800 AB_status=1 AIP_task_rc=0x1004 metadata_completion=1', 801)
        add(s, 'COMMIT', 'generation=2 request=0x1000 request_free_rc=0 retained_request=0 clean_completion=1 queued=1 ap_consumed=0', 801)
        add(s, 'REPLY_FREE', 'generation=2 destination=0x81cf619b expected=0x81cf619b pointer=0x2000 kind=queued-reply rc=0 faults=0 retained=0 ap_consumed=1 AB_status=1 AIP_task_rc=0x1004 metadata_completion_only=1', 723)
        edge = self.edge(self.graph.six.SPECS[0])
        rows += [edge['REQUEST']['raw'], edge['REPLY_FREE']['raw']]
        return b''.join(r.encode() + (v.WARNINGS[0] if r.startswith('OBS FULL_ADF_PROC_INPUT_QUEUED ') else
                                     v.WARNINGS[1] if r.startswith('OBS FULL_ADF_SET_INPUT_HOTSHOE ') else b'') + b'\r\n' for r in rows)

    def adf_control_context(self, raw):
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        edge = self.edge(self.graph.six.SPECS[0])
        edge['REQUEST'] = log.one(edge['REQUEST']['tag'])
        edge['REPLY_FREE'] = log.one(edge['REPLY_FREE']['tag'])
        return log, repairs, {'identity': ('701', '723'), 'edges': [edge]}

    def test_adf_effects_join_only_after_actual_content_checks(self):
        log, repairs, proof = self.adf_control_context(self.adf_control_fixture())
        self.assertEqual(len(repairs), 2)
        with self.assertRaises(v.UnjoinedRepairs):
            v.bind_repairs(proof, repairs)
        joins = v.check_repaired_adf_controls(log, repairs, proof, self.graph)
        self.assertIs(joins[0]['proc']['input_queued'], log.one('FULL_ADF_PROC_INPUT_QUEUED'))
        self.assertIs(joins[0]['set_input']['callbacks']['HOTSHOE'], log.one('FULL_ADF_SET_INPUT_HOTSHOE'))
        proof['repaired_ADF_input_control_joins'] = joins
        self.assertTrue(all(r['content_verifier_joined'] for r in v.bind_repairs(proof, repairs)))
        self.assertFalse(joins[0]['capture_verified'])
        self.assertFalse(joins[0]['physical_asic_compatibility_verified'])
        self.assertNotIn('graph_verified', joins[0])
        self.assertEqual(v.check_repaired_adf_controls(log, [], proof, self.graph), [])

    def test_adf_returned_rows_keep_exact_source_literals(self):
        log, repairs, proof = self.adf_control_context(self.adf_control_fixture())
        joins = v.check_repaired_adf_controls(log, repairs, proof, self.graph)
        for row, source in ((joins[0]['proc']['input_queued'], 'adf-proc-device.c'),
                            (joins[0]['set_input']['callbacks']['HOTSHOE'], 'adf-set-input-device.c')):
            body = row['raw'].split(' ', 2)[2].split(' pid=', 1)[0]
            self.assertIn('log_event("' + row['tag'] + ' ","' + body + '");',
                          v.read(v.RUNTIME / 'device-models' / source).decode())

    def test_adf_unconsumed_wrong_line_raw_and_same_tag_cannot_bind(self):
        log, repairs, proof = self.adf_control_context(self.adf_control_fixture())
        joins = v.check_repaired_adf_controls(log, repairs, proof, self.graph)
        for index in range(2):
            for field, value in (('parsed_line', repairs[index]['parsed_line'] + 1),
                                 ('repaired_record', repairs[index]['repaired_record'].replace('generation=', 'generation=9'))):
                altered = copy.deepcopy(repairs)
                altered[index][field] = value
                with self.subTest(index=index, field=field), self.assertRaises(ValueError):
                    v.check_repaired_adf_controls(log, altered, proof, self.graph)
                with self.assertRaises(v.UnjoinedRepairs):
                    v.bind_repairs({'joins': joins}, altered)
        for field, value in (('line', 999), ('raw', log.one('FULL_ADF_PROC_INPUT_QUEUED')['raw'] + ' extra=1')):
            borrowed = copy.deepcopy(joins)
            borrowed[0]['proc']['input_queued'][field] = value
            with self.subTest(field=field), self.assertRaises(v.UnjoinedRepairs):
                v.bind_repairs({'joins': borrowed}, copy.deepcopy(repairs))
        for container, key in ((joins[0]['proc'], 'input_queued'), (joins[0]['set_input']['callbacks'], 'HOTSHOE')):
            row = container.pop(key)
            with self.assertRaises(v.UnjoinedRepairs):
                v.bind_repairs({'joins': joins}, copy.deepcopy(repairs))
            container[key] = row

    def test_adf_unknown_suffix_duplicate_key_and_truncation_rejected(self):
        original = self.adf_control_fixture()
        for tag in (b'FULL_ADF_PROC_INPUT_QUEUED', b'FULL_ADF_SET_INPUT_HOTSHOE'):
            line = next(r for r in original.split(b'\n') if r.startswith(b'OBS ' + tag + b' '))
            for changed in (line.replace(b'qemu-system-', b' unknown_tail=1qemu-system-', 1),
                            line.replace(b'qemu-system-', b' pid=701qemu-system-', 1),
                            line.replace(b'capture_verified=0qemu', b'capture_verified=qemu', 1),
                            line.replace(b'capture_verified=0qemu', b'capture_verified=0UNKNOWNqemu', 1)):
                with self.subTest(tag=tag, changed=changed), self.assertRaises(ValueError):
                    log, repairs, proof = self.adf_control_context(original.replace(line, changed, 1))
                    v.check_repaired_adf_controls(log, repairs, proof, self.graph)
            cut = original.index(line)
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                self.adf_control_context(original[:cut] + line)

    def test_adf_missing_duplicate_wrong_wire_worker_and_order_rejected(self):
        original = self.adf_control_fixture()
        tags = ('FULL_ADF_PROC_INPUT_QUEUED', 'FULL_ADF_PROC_REQUEST', 'FULL_ADF_PROC_REPLY_FREE',
                'FULL_ADF_PROC_INPUT_DRAINED', 'FULL_ADF_SET_INPUT_HOTSHOE', 'FULL_ADF_SET_INPUT_METADATA',
                'FULL_ADF_SET_INPUT_QUEUED', 'FULL_ADF_SET_INPUT_REPLY_FREE', 'FULL_ADF_SET_INPUT_AIP_DISPATCH')
        for tag in tags:
            start = original.index(('OBS ' + tag + ' ').encode())
            end = original.index(b'\r\n', start) + 2
            for changed in (original[:start] + original[end:], original[:end] + original[start:end] + original[end:]):
                with self.subTest(tag=tag, size=len(changed)), self.assertRaises(ValueError):
                    log, repairs, proof = self.adf_control_context(changed)
                    v.check_repaired_adf_controls(log, repairs, proof, self.graph)
        for old, new in ((b'raw=0d2023030c00018000000000', b'raw=0d2023030c00018001000000'),
                         (b'raw=0d2036130c00018000005800', b'raw=0d2036130c00018000000000'),
                         (b'tid=800 ', b'tid=723 '), (b'tid=801 ', b'tid=802 '),
                         (b'expected=0x81cf619b ', b'expected=0x81cf619c '),
                         (b'pointer=0x2000 ', b'pointer=0x2001 '),
                         (b'AB_status=1 task_rc=0x1004', b'AB_status=0 task_rc=0x1004')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                log, repairs, proof = self.adf_control_context(original.replace(old, new, 1))
                v.check_repaired_adf_controls(log, repairs, proof, self.graph)
        parsed, _ = v.console_records(original)
        lines = parsed.splitlines(keepends=True)
        left = next(i for i, r in enumerate(lines) if r.startswith(b'OBS FULL_ADF_PROC_INPUT_QUEUED '))
        lines[left], lines[left + 1] = lines[left + 1], lines[left]
        swapped = b''.join(lines)
        target = next(r for r in swapped.split(b'\r\n') if r.startswith(b'OBS FULL_ADF_PROC_INPUT_QUEUED '))
        swapped = swapped.replace(target + b'\r\n', target + v.WARNINGS[0] + b'\r\n', 1)
        with self.assertRaises(ValueError):
            log, repairs, proof = self.adf_control_context(swapped)
            v.check_repaired_adf_controls(log, repairs, proof, self.graph)

    def test_original_native_roles_and_actual_free(self):
        edge = self.edge(self.graph.six.SPECS[0])
        roles = v.check_role_messages(edge, ('701', '723'))
        self.assertEqual(roles['source_pin'], [0, 2, 1, 0x90050004])
        self.assertEqual(roles['peer_pin'], [0, 1, 1, 0x9284074a])
        self.assertEqual(roles['original_caller_sid'], 0x81cf619b)
        self.assertIs(roles['actual_AP_reply_free'], edge['REPLY_FREE'])
        raw, _ = self.old.request_bytes(edge['REQUEST'], edge['source_pin'], edge['sink_pin'])
        self.assertEqual(raw[20:24], b'\xa7\x19\0\x5a')

    def test_wrong_source_sid_and_model_padding(self):
        edge = self.edge(self.graph.six.SPECS[0])
        wrong = copy.deepcopy(edge['REQUEST'])
        wrong['fields']['source'] = '0x81cf619c'
        with self.assertRaises(ValueError):
            self.old.request_bytes(wrong, edge['source_pin'], edge['sink_pin'])
        source, peer = edge['source_pin'], edge['sink_pin']
        body = self.old.frame_bytes(72, 0x8100, 1, source + peer + (0, 0))
        row = record('HOST_TEST_PEER_REPLY', source=hex(peer[3]), destination=hex(source[3]), bytes=72, raw=body.hex())
        self.old.model_frame(row, 72, 0x8100, 1, peer[3], source[3], source + peer + (0, 0))
        for offset in (20, 48, 68):
            changed = bytearray(body); changed[offset] ^= 1
            row['fields']['raw'] = changed.hex()
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.old.model_frame(row, 72, 0x8100, 1, peer[3], source[3], source + peer + (0, 0))

    def test_wrong_original_ap_tid_and_missing_56b_free(self):
        for key, value in (('tid', '724'), ('pid', '702'), ('bytes', '55'), ('rc', '-1'), ('ap_consumed', '0')):
            edge = self.edge(self.graph.six.SPECS[0])
            edge['REPLY_FREE']['fields'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                v.check_role_messages(edge, ('701', '723'))

    def test_thirteen_helper_orchestration_has_no_native_positive_claim(self):
        specs = self.graph.six.SPECS + self.graph.NEW[:-1] + (
            (self.hdmi.PREFIX, '', '', self.hdmi.S, self.hdmi.P),
            (self.osd.PREFIX, '', '', self.osd.S, self.osd.P), self.graph.NEW[-1])
        edges = [self.edge(spec, i) for i, spec in enumerate(specs)]
        identity, run = ('701', '723'), Path('/HOST_TEST/run')
        calls = []
        def added(log, spec, previous, owner, first):
            index = specs.index(spec)
            self.assertEqual((previous, owner, first), (edges[index - 1]['REPLY_FREE']['line'], identity, 100))
            calls.append(index + 1)
            return edges[index]
        def video(log, previous, owner, first, actual_run):
            self.assertEqual((previous, owner, first, actual_run), (299, identity, 100, run))
            calls.append(11)
            return edges[10]
        def osd(log, previous, owner, first, dependency):
            self.assertEqual((previous, owner, first), (319, identity, 100))
            self.assertIs(dependency, mockgraph)
            calls.append(12)
            return edges[11]
        mockgraph = types.SimpleNamespace(NEW=self.graph.NEW,
            six=types.SimpleNamespace(verify_graph=Mock(return_value=(edges[:6], identity, {}, {}))),
            verify_legacy=Mock(return_value={}), verify_new_edge=Mock(side_effect=added),
            verify_new_effects=Mock(), verify_audits=Mock(return_value=[]))
        proof = v.check_graph_content(self.graph.Log(b''), run, mockgraph,
                                     types.SimpleNamespace(verify_hdmi_edge=Mock(side_effect=video)),
                                     types.SimpleNamespace(verify_osd_edge=Mock(side_effect=osd)))
        self.assertEqual(calls, [7, 8, 9, 10, 11, 12, 13])
        self.assertEqual(len(proof['roles']), 13)
        self.assertNotIn('graph_verified', proof)
        self.assertNotIn('capture_verified', proof)
        mockgraph.verify_new_effects.assert_called_once()

    def test_late_unsupported_and_unadmitted_retained(self):
        for suffix in ('UNSUPPORTED', 'UNADMITTED', 'FAULT', 'REFUSED', 'REJECT'):
            log = self.graph.Log(('OBS FULL_PINMEM_OSD_CONNECT_' + suffix + ' reason=HOST_TEST\n').encode())
            v.check_late_failures(log, 2)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                v.check_late_failures(log, 1)

    def test_imaging_control_tag_split_literal_source_offsets_and_endings(self):
        literal = v.IMAGING_CONTROL_COMMIT
        body = literal[len(v.IMAGING_CONTROL_COMMIT_TAG):].decode()
        source = v.read(v.RUNTIME / 'device-models/imaging-control-connection.c').decode()
        self.assertIn('event(io,"COMMIT ","' + body + '");', source)
        self.assertEqual(len(body.split()), 11)
        prefix = b'boot\rprogress\r\n' + v.WARNINGS[1]
        for ending in (b'\n', b'\r\n'):
            guest = literal + ending
            self.assertEqual(v.console_records(guest), (guest, []))
            for warning in v.WARNINGS:
                for cut in range(len(b'OBS ') + 1, len(v.IMAGING_CONTROL_COMMIT_TAG)):
                    raw = prefix + guest[:cut] + warning + guest[cut:]
                    with self.subTest(ending=ending, warning=warning, cut=cut):
                        parsed, repairs = v.console_records(raw)
                        self.assertEqual(parsed, prefix + guest)
                        repair, = repairs
                        self.assertEqual(repair['kind'], 'exact-host-vvfat-diagnostic')
                        self.assertEqual(raw[repair['raw_warning_start']:repair['raw_warning_end']], warning)
                        self.assertEqual((repair['raw_record_start'], repair['raw_record_end']), (len(prefix), len(raw)))
                        self.assertEqual((repair['raw_lf_line'], repair['raw_lf_end'], repair['parsed_line']), (3, 4, 3))
                        self.assertEqual(bytes.fromhex(repair['raw_record_hex']), raw[len(prefix):])
                        self.assertEqual(repair['raw_record_sha256'], v.sha(raw[len(prefix):]))
                        self.assertEqual(repair['repaired_record'], literal.decode())
                        self.assertEqual(repair['repaired_record_sha256'], v.sha(literal))
                        self.assertEqual(repair['cause'], 'unknown')
                        self.assertTrue(repair['guest_payload_unchanged'])
                        self.assertFalse(repair['guest_bytes_invented'])
                        self.assertNotIn('content_verifier_joined', repair)

    def test_imaging_control_tag_split_refuses_nonliteral_and_unknown_warning(self):
        guest, cut = v.IMAGING_CONTROL_COMMIT + b'\r\n', len(b'OBS FULL_IMAG')
        warning = v.WARNINGS[0]
        body = v.IMAGING_CONTROL_COMMIT[len(v.IMAGING_CONTROL_COMMIT_TAG):].split()
        mutations = [v.IMAGING_CONTROL_COMMIT_TAG + b' '.join(body[:i] + body[i + 1:]) + b'\r\n'
                     for i in range(len(body))]
        mutations += [guest.replace(token, token[:-1] + (b'0' if token.endswith(b'1') else b'1'), 1)
                      for token in body]
        mutations += [guest[:-2] + b' extra=1\r\n', guest[:-2] + b' capture_verified=0\r\n',
            guest.replace(b'source_state=0 peer_state=0', b'peer_state=0 source_state=0'),
            guest.replace(b'connections=1 ', b'connections=1  '), guest[:-3] + b'\r\n',
            guest[:cut - 1] + guest[cut:], guest[:cut] + b'OBS OTHER value=1\r\n',
            guest.replace(b'CONTROL_CONNECT_COMMIT', b'CONTROL_CONNECT_COMMIT_EXTRA'),
            guest.replace(b'\r\n', b'\r\r\n')]
        for changed in mutations:
            with self.subTest(changed=changed):
                try:
                    parsed, repairs = v.console_records(changed[:cut] + warning + changed[cut:])
                except ValueError:
                    continue
                self.assertEqual(repairs, [])
                self.assertEqual(self.graph.Log(parsed).rows('FULL_IMAGING_CONTROL_CONNECT_COMMIT'), [])
        with self.assertRaises(v.SourceMissing):
            v.console_records(guest[:cut] + warning)
        for unknown in (warning.replace(b'pending', b'unknown'), warning.replace(b'warning:', b'Warning:'),
                        warning.replace(b'commit ', b'commit  '), warning[:-1] + b'\r\n'):
            raw = guest[:cut] + unknown + guest[cut:]
            with self.subTest(unknown=unknown):
                parsed, repairs = v.console_records(raw)
                self.assertEqual(parsed, raw)
                self.assertEqual(repairs, [])
                self.assertEqual(self.graph.Log(parsed).rows('FULL_IMAGING_CONTROL_CONNECT_COMMIT'), [])

    def imaging_control_edge_fixture(self):
        spec = self.old.SPECS[1]
        prefix, _, profile, source, peer = spec
        caller, pid, tid = 0x81cf619b, 701, 723
        original = self.old.frame_bytes(64, 1, 2, source + peer, caller, b'\xa7\x19\0\x5a')
        rows = [record(prefix + '_PROFILE', requested=profile, enabled=1, first_missing='none',
                       pid=pid, owner_pid=pid, initialized=1, before_any_input=1),
                record('PIN_CONTROL_REQUEST', tid=tid, source=hex(caller), destination=hex(source[3]),
                       bytes=64, raw=original.hex())]
        for tag, wire, sender, receiver, pointer in (
            ('REQUEST', original, caller, source[3], '0x1000'),
            ('PEER_REQUEST', self.old.frame_bytes(64, 0x100, 1, source + peer), source[3], peer[3], '0x2000'),
            ('PEER_REPLY', self.old.frame_bytes(72, 0x8100, 1, source + peer + (0, 0)), peer[3], source[3], '0x3000'),
            ('REPLY_QUEUED', self.old.frame_bytes(56, 0x8001, 2, source + (0, 0)), source[3], caller, '0x2000')):
            rows.append(record(prefix + '_' + tag, pid=pid, tid=tid, source=hex(sender),
                               destination=hex(receiver), pointer=pointer, bytes=len(wire), raw=wire.hex()))
        raw = b''.join(row['raw'].encode() + b'\r\n' for row in rows)
        raw += v.IMAGING_CONTROL_COMMIT + b'\r\n'
        raw += record(prefix + '_REPLY_FREE', pid=pid, tid=tid, bytes=56, rc=0, faults=0, ap_consumed=1,
                      destination=hex(caller), expected=hex(caller), pointer='0x2000')['raw'].encode() + b'\r\n'
        return raw

    def test_imaging_control_tag_repair_requires_actual_edge2_consumer(self):
        raw = self.imaging_control_edge_fixture().replace(b'OBS FULL_IMAGING_CONTROL_CONNECT_COMMIT ',
            b'OBS FULL_IMAG' + v.WARNINGS[0] + b'ING_CONTROL_CONNECT_COMMIT ')
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        edge, identity = self.old.verify_edge(log, self.old.SPECS[1], 0, ('701', '723'))
        self.assertEqual(identity, ('701', '723'))
        self.assertIs(edge['COMMIT'], log.one('FULL_IMAGING_CONTROL_CONNECT_COMMIT'))
        self.assertEqual(edge['COMMIT']['raw'], v.IMAGING_CONTROL_COMMIT.decode())
        self.old.fields_equal(edge['COMMIT'], marker_readback=1, posthook_no_format=1, prior_data_edge_preserved=1)
        with self.assertRaises(v.UnjoinedRepairs):
            v.bind_repairs({}, repairs)
        borrowed = copy.deepcopy(edge)
        borrowed['COMMIT']['line'] += 1
        with self.assertRaises(v.UnjoinedRepairs):
            v.bind_repairs({'edge': borrowed}, repairs)
        v.bind_repairs({'actual_edge2': edge}, repairs)
        self.assertTrue(repairs[0]['content_verifier_joined'])
        # This is only a HOST_TEST edge fixture, never a native-positive evaluate().
        self.assertNotIn('capture_verified', edge)

    def test_imaging_control_tag_repair_keeps_wire_owner_order_and_duplicate_checks(self):
        original = self.imaging_control_edge_fixture()
        tag = b'OBS FULL_IMAGING_CONTROL_CONNECT_COMMIT '
        mixed = original.replace(tag, b'OBS FULL_IMAG' + v.WARNINGS[0] + b'ING_CONTROL_CONNECT_COMMIT ')
        parsed, repairs = v.console_records(mixed)
        base = self.graph.Log(parsed)
        mutations = []
        for row_tag, key, value in (('REPLY_FREE', 'tid', '724'), ('REPLY_FREE', 'pid', '702'),
                                    ('REPLY_FREE', 'rc', '-1'), ('REPLY_FREE', 'pointer', '0x2001'),
                                    ('PEER_REQUEST', 'pointer', '0x1000')):
            changed = copy.deepcopy(base)
            changed.one('FULL_IMAGING_CONTROL_CONNECT_' + row_tag)['fields'][key] = value
            mutations.append(changed)
        changed = copy.deepcopy(base)
        peer = changed.one('FULL_IMAGING_CONTROL_CONNECT_PEER_REPLY')
        wire = bytearray.fromhex(peer['fields']['raw']); wire[48] ^= 1
        peer['fields']['raw'] = wire.hex(); mutations.append(changed)
        changed = copy.deepcopy(base)
        changed.one('FULL_IMAGING_CONTROL_CONNECT_COMMIT')['line'] = 1
        mutations.append(changed)
        changed = self.graph.Log(parsed + v.IMAGING_CONTROL_COMMIT + b'\r\n')
        mutations.append(changed)
        changed = copy.deepcopy(base)
        changed.records.remove(changed.one('FULL_IMAGING_CONTROL_CONNECT_REQUEST'))
        mutations.append(changed)
        for index, log in enumerate(mutations):
            with self.subTest(index=index), self.assertRaises(ValueError):
                self.old.verify_edge(log, self.old.SPECS[1], 0, ('701', '723'))
        self.assertNotIn('content_verifier_joined', repairs[0])

    def test_exact_current_warning_bytes_rejoin_content_record(self):
        intact = b'OBS FULL_IMAGING_PIN_CONNECT_REQUEST pid=701 tid=723 bytes=64 raw=0011 capture_verified=0\r\n'
        warning = v.WARNINGS[0]
        raw = intact.replace(b'raw=0011', b'raw=00' + warning + b'11')
        parsed, repairs = v.console_records(raw)
        self.assertEqual(parsed, intact)
        self.assertEqual(len(repairs), 1)
        self.assertEqual(raw[repairs[0]['raw_warning_start']:repairs[0]['raw_warning_end']], warning)
        log = self.graph.Log(parsed)
        v.bind_repairs({'HOST_TEST_record': log.records[0]}, repairs)
        self.assertTrue(repairs[0]['content_verifier_joined'])
        self.assertFalse(repairs[0]['guest_bytes_invented'])
        # This test establishes framing only; the short body cannot be a graph positive.
        with self.assertRaises(ValueError):
            self.old.raw_bytes(log.records[0], 64)

    def test_warning_requires_complete_record_and_consuming_helper(self):
        row = b'OBS FULL_PINMEM_OSD_CONNECT_COMMIT capture_verified=0\r\n'
        mixed = row.replace(b'capture_verified', b'capture_' + v.WARNINGS[1] + b'verified')
        _, repairs = v.console_records(mixed)
        with self.assertRaises(ValueError):
            v.bind_repairs({}, repairs)
        with self.assertRaises(ValueError):
            v.console_records(mixed.replace(b'commit complete\n', b'commit unknown\n'))
        with self.assertRaises(v.SourceMissing):
            v.console_records(b'OBS FULL_PINMEM_OSD_CONNECT_COMMIT capture_' + v.WARNINGS[0])

    def test_repeated_warning_offsets_and_standalone_warning_preserved(self):
        intact = b'OBS FULL_PINMEM_OSD_CONNECT_COMMIT metadata_only=1 capture_verified=0\r\n'
        mixed = intact.replace(b'metadata_only=1', b'meta' + v.WARNINGS[0] + b'data_only=1')
        mixed = mixed.replace(b'capture_verified=0', b'capture_' + v.WARNINGS[1] + b'verified=0')
        parsed, repairs = v.console_records(v.WARNINGS[0] + mixed)
        self.assertEqual(parsed, v.WARNINGS[0] + intact)
        self.assertEqual(len(repairs), 2)
        for item in repairs:
            self.assertIn((v.WARNINGS[0] + mixed)[item['raw_warning_start']:item['raw_warning_end']], v.WARNINGS)
        self.assertEqual(repairs[0]['parsed_line'], 2)

    def test_complete_dfs_join_and_unknown_host_bytes(self):
        guest = b'OBS FULL_IMAGING_PIN_CONNECT_COMMIT capture_verified=0'
        host = (b'SONY_DFS_REQUEST target=0x00000106 generation=2 readback_request=0x00000101 '
                b'readback_ckstatus=0x00000100 delay_ns=1000 virtual_selector=1 clocks_changed=0\n')
        parsed, repairs = v.console_records(guest + host)
        self.assertEqual(parsed, guest + b'\r\n' + host)
        self.assertEqual(repairs[0]['kind'], 'complete-guest-host-DFS-boundary')
        with self.assertRaises(ValueError):
            v.console_records(guest + host.replace(b'clocks_changed=0', b'clocks_changed=1'))

    def pinmem_boundary_fixture(self):
        # Verbatim complete payload/window from run-epi38kew; framing evidence only.
        guest = (b'OBS FULL_PINMEM_COMMIT tid=382 slot=8 type=1 dir=3 index=0 pin_state=1 '
                 b'owner=0x90590818 status=0 queries=15 reply=0x7f9c0bd7c0 lease=15 request_free_rc=0 '
                 b'connect_performed=0 pixels_consumed=0 camera_startup_verified=0\r\n')
        kernel = b'[ 1515.781307] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        mixed = guest.replace(b'slot=8', b'slot=' + v.WARNINGS[0] + b'8')[:-2] + kernel + b'\r\n'
        return guest, kernel, mixed

    def test_complete_pinmem_uipc_boundary_uses_original_ending_and_real_get_consumer(self):
        guest, kernel, mixed = self.pinmem_boundary_fixture()
        caller, key = 0x81cf619b, self.osd.S
        query = self.old.frame_bytes(48, 0, 2, key[:3] + (0,), caller, b'\xa7\x19\0\x5a')
        reply = self.old.frame_bytes(56, 0x8000, 2, key[:3] + (1, key[3], 0))
        rows = [record('PIN_QUERY', tid=382, destination=hex(key[3]), source=hex(caller), bytes=48, raw=query.hex()),
                record('FULL_PINMEM_REQUEST', tid=382, destination=hex(key[3]), source=hex(caller),
                       reply_destination=hex(caller), bytes=48, raw=query.hex()),
                record('FULL_PINMEM_REPLY_QUEUED', tid=382, source=hex(key[3]), destination=hex(caller),
                       reply='0x7f9c0bd7c0', lease=15, bytes=56, raw=reply.hex())]
        before = b''.join(row['raw'].encode() + b'\r\n' for row in rows)
        freed = record('FULL_PINMEM_NATIVE_REPLY_FREE', tid=382, sender=382, waiter=1,
                       destination=hex(caller), expected=hex(caller), reply='0x7f9c0bd7c0', lease=15, bytes=56, rc=0)
        raw = before + mixed + freed['raw'].encode() + b'\r\n'
        parsed, repairs = v.console_records(raw)
        self.assertEqual(parsed, before + guest + kernel + freed['raw'].encode() + b'\r\n')
        self.assertEqual(len(repairs), 2)
        transport = repairs[1]
        self.assertEqual(raw[transport['raw_kernel_start']:transport['raw_kernel_end']], kernel)
        self.assertEqual(raw[transport['raw_guest_ending_start']:transport['raw_guest_ending_end']], b'\r\n')
        self.assertEqual(transport['framing_bytes_inserted'], 0)
        # Same isolated slot extension as verify_osd_edge; unchanged real content code.
        namespace = dict(self.graph.verify_get.__globals__, SLOTS={**self.graph.SLOTS, key: 8})
        verify_get = types.FunctionType(self.graph.verify_get.__code__, namespace)
        content = verify_get(self.graph.Log(parsed), key, ('701', '382'), caller, 0, 20)
        self.assertEqual(content['commit']['raw'].encode(), guest[:-2])
        v.bind_repairs(content, repairs)
        self.assertTrue(all(r['content_verifier_joined'] and not r['guest_bytes_invented'] for r in repairs))
        # This HOST_TEST proves the Get/parser join, never native full-graph acceptance.
        with self.assertRaises(ValueError):
            verify_get(self.graph.Log(parsed.replace(b'slot=8', b'slot=7')), key, ('701', '382'), caller, 0, 20)

    def test_pinmem_uipc_boundary_requires_exact_payload_kernel_and_position(self):
        guest, kernel, mixed = self.pinmem_boundary_fixture()
        mutations = (
            mixed.replace(b'camera_startup_verified=0', b'camera_startup_verified=1'),
            mixed.replace(b'status=0 ', b''),
            mixed.replace(b'owner=0x90590818', b'owner=0x90590819'),
            mixed.replace(b'FULL_PINMEM_COMMIT', b'FULL_VEF_COMMIT'),
            mixed.replace(b'Line 100:', b'Line 101:'),
            mixed.replace(b'ret = -1022', b'ret = -1021'),
            mixed.replace(b'uipc:', b'uipx:'),
            mixed.replace(b'[ 1515.781307]', b'[01515.781307]'),
            mixed.replace(b'[ 1515.781307]', b'[18446744074.781307]'),
            mixed.replace(b'cdev_ioctl()', b'cdev_io\r\nctl()'),
            mixed.replace(kernel, kernel[:-2] + b' extra\r\n'),
            mixed.replace(kernel, kernel[:-2] + b'\n'),
            mixed.replace(b'camera_startup_verified=0' + kernel, b'camera_startup_' + kernel + b'verified=0'),
            mixed[:-2] + b'camera_startup_verified=0\r\n',
            mixed[:-2] + b'\n',
            mixed.replace(b'tid=382', b'tid=2147483648'),
            mixed.replace(b'lease=15', b'lease=18446744073709551616'),
        )
        for raw in mutations:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v.console_records(raw)
        with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
            v.console_records(mixed[:-2])
        self.assertEqual(v.console_records(kernel), (kernel, []))
        self.assertEqual(v.console_records(guest), (guest, []))
        parsed, repairs = v.console_records(guest[:-2] + kernel + b'\r\n')
        self.assertEqual(parsed, guest + kernel)
        self.assertEqual(len(repairs), 1)

    def test_non_graph_warning_bytes_are_preserved_without_repair_or_claim(self):
        raw = (b'OBS NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_REPLY_FREE pid=7' + v.WARNINGS[0] + b'01 capture=0\r\n')
        for diagnostic in (raw, raw.splitlines(keepends=True)[0]):
            with self.subTest(diagnostic=diagnostic):
                self.assertEqual(v.console_records(diagnostic), (diagnostic, []))
        broken_graph = raw.replace(b'NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_REPLY_FREE', b'FULL_PINMEM_COMMIT')
        with self.assertRaises(ValueError):
            v.console_records(broken_graph.replace(b'01 capture=0', b'01 bad-token'))

    def test_pinmem_uipc_repairs_need_the_exact_consumed_record(self):
        guest, _, mixed = self.pinmem_boundary_fixture()
        parsed, repairs = v.console_records(mixed)
        row = self.graph.Log(parsed).records[0]
        for proof in ({}, {'record': {**row, 'line': row['line'] + 1}},
                      {'record': {**row, 'raw': guest[:-2].decode().replace('lease=15', 'lease=16')}}):
            with self.subTest(proof=proof), self.assertRaisesRegex(ValueError, 'content-verifier join'):
                v.bind_repairs(proof, copy.deepcopy(repairs))

    def pin_query_boundary_fixture(self, key=(0, 1, 1, 0x9284074a), opaque=bytes(4)):
        # Actual q2w2q6v8 query/kernel bytes; surrounding Get is a HOST_TEST trace.
        caller, tid, pointer, lease = 0x81cf61c4, 382, '0x7fae0c6ac0', 3
        wire = self.old.frame_bytes(48, 0, 2, key[:3] + (0,), caller, opaque)
        guest = record('PIN_QUERY', tid=tid, destination=hex(key[3]), source=hex(caller), bytes=48, raw=wire.hex())
        guest = guest['raw'].encode() + b'\r\n'
        kernel = b'[ 1418.871426] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        owner = key[3]
        family = 'INFRABB' if owner == 0x9284074a else 'PINMEM'
        slot = v.INFRABB_GET_SLOTS.get(key, 1) if family == 'INFRABB' else self.graph.SLOTS[key]
        reply = self.old.frame_bytes(56, 0x8000, 2, key[:3] + (1, owner, 0), owner if family == 'INFRABB' else 0)
        rows = [
            record('FULL_' + family + '_REQUEST', tid=tid, destination=hex(owner), source=hex(caller),
                   reply_destination=hex(caller), bytes=48, raw=wire.hex()),
            record('FULL_' + family + '_REPLY_QUEUED', tid=tid, source=hex(owner), destination=hex(caller),
                   reply=pointer, lease=lease, bytes=56, raw=reply.hex()),
            record('FULL_' + family + '_COMMIT', tid=tid, slot=slot, type=key[0], dir=key[1],
                   index=key[2], pin_state=1, owner=hex(owner), status=0, queries=3, reply=pointer, lease=lease,
                   request_free_rc=0, connect_performed=0, pixels_consumed=0, camera_startup_verified=0),
            record('FULL_' + family + '_NATIVE_REPLY_FREE', tid=tid, sender=tid, waiter=1, destination=hex(caller),
                   expected=hex(caller), reply=pointer, lease=lease, bytes=56, rc=0)]
        tail = b''.join(row['raw'].encode() + b'\r\n' for row in rows)
        return guest, kernel, guest[:-2] + kernel + b'\r\n' + tail

    def query_content_join(self, raw):
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        proof = {'identity': ('258', '382'), 'edges': [{'REQUEST': {'line': len(log.lines) + 1}}]}
        proof['repaired_early_BB_Get_joins'] = v.check_repaired_queries(log, repairs, proof, self.graph)
        v.bind_repairs(proof, repairs)
        return parsed, repairs, proof

    def test_pin_query_grammar_matches_complete_source_printf_and_BB_slot_table(self):
        source = v.read(v.RUNTIME / 'menu-observe.c').decode()
        start = source.index('/* Observe the original destination before choosing a model;')
        producer = source[start:source.index('if (id == NATIVE_INFRABB_CP', start)]
        self.assertIn('pin_bytes == 48 || pin_bytes == 64', producer)
        self.assertIn('((const unsigned int *)message)[1] == 0xa0a0a0a0U', producer)
        self.assertIn('"tid=%ld destination=%#x source=%#x bytes=%u raw=%s",\n'
                      '                 syscall(178), id, real_get_source ? real_get_source(message) : 0, pin_bytes, raw', producer)
        self.assertIn('record(pin_bytes == 48 ? "PIN_QUERY " : "PIN_CONTROL_REQUEST ", text);', producer)
        self.assertIn('const char digits[] = "0123456789abcdef";', producer)
        self.assertIn('"OBS %s%s\\n", prefix, name ? name : ""', source)
        registry = v.read(v.RUNTIME / 'infrabb-registry.c').decode()
        table = registry[registry.index('static const unsigned int keys[21][3] = {'):registry.index('static struct pin_registry_owner registry')]
        keys = [tuple(map(int, group)) for group in re.findall(r'\{(\d+),(\d+),(\d+)\}', table)]
        self.assertEqual(v.INFRABB_GET_SLOTS, {key + (0x9284074a,): slot for slot, key in enumerate(keys)})
        self.assertIn('.full_key_match=1, .reply_sid=NATIVE_INFRABB_CP', registry)
        guest, _, _ = self.pin_query_boundary_fixture()
        self.assertEqual(guest, b'OBS PIN_QUERY tid=382 destination=0x9284074a source=0x81cf61c4 bytes=48 '
                         b'raw=c461cf81a0a0a0a001003000180000003000000000000000001000001800020000000000010000000100000000000000\r\n')
        self.assertIsNotNone(v.PIN_QUERY_GET.fullmatch(guest[:-2]))

    def test_pin_query_uipc_across_canonical_slots_with_actual_get_and_native_free(self):
        for key in ((0, 1, 1, 0x9284074a), (0, 2, 3, 0x9284074a),
                    (6, 2, 0, 0x9284074a), (8, 2, 10, 0x9284074a)):
            with self.subTest(key=key):
                guest, kernel, mixed = self.pin_query_boundary_fixture(key, b'\xa7\x19\0\x5a')
                # Exercise the existing warning move and the new boundary together.
                mixed = mixed.replace(b'raw=', b'ra' + v.WARNINGS[0] + b'w=', 1)
                parsed, repairs, proof = self.query_content_join(mixed)
                self.assertEqual(parsed, guest + kernel + mixed[mixed.index(kernel) + len(kernel) + 2:])
                self.assertEqual(len(repairs), 2)
                boundary = repairs[-1]
                self.assertEqual(boundary['kind'], 'complete-PinQuery-UIPC-boundary')
                self.assertEqual(mixed[boundary['raw_kernel_start']:boundary['raw_kernel_end']], kernel)
                self.assertEqual(mixed[boundary['raw_guest_ending_start']:boundary['raw_guest_ending_end']], b'\r\n')
                self.assertEqual(boundary['framing_bytes_inserted'], 0)
                joined = proof['repaired_early_BB_Get_joins'][0]
                self.assertEqual(joined['original_AP_query']['raw'].encode(), guest[:-2])
                self.assertEqual(joined['commit']['fields']['slot'], str(v.INFRABB_GET_SLOTS[key]))
                self.assertEqual(struct.unpack_from('<I', bytes.fromhex(joined['reply']['fields']['raw']))[0], key[3])
                self.assertTrue(all(r['content_verifier_joined'] and not r['guest_bytes_invented'] for r in repairs))

    def test_pin_query_host_warning_alone_requires_actual_get_and_native_free(self):
        guest, kernel, mixed = self.pin_query_boundary_fixture()
        tail = mixed[mixed.index(kernel) + len(kernel) + 2:]
        for warning in v.WARNINGS:
            raw = guest.replace(b'raw=', b'ra' + warning + b'w=', 1) + tail
            with self.subTest(warning=warning):
                parsed, repairs, proof = self.query_content_join(raw)
                self.assertEqual(parsed, guest + tail)
                self.assertEqual(len(repairs), 1)
                self.assertEqual(repairs[0]['kind'], 'exact-host-vvfat-diagnostic')
                self.assertTrue(repairs[0]['content_verifier_joined'])
                self.assertEqual(proof['repaired_early_BB_Get_joins'][0]['commit']['fields']['slot'], '1')
                without_free = raw[:raw.index(b'OBS FULL_INFRABB_NATIVE_REPLY_FREE ')]
                with self.assertRaises(ValueError):
                    self.query_content_join(without_free)
                with self.assertRaises(ValueError):
                    self.query_content_join(raw.replace(b'bytes=48', b'bytes=47', 1))

    def test_pin_query_other_owner_still_requires_its_actual_graph_get_consumer(self):
        key = (0, 2, 1, 0x90590818)
        _, _, mixed = self.pin_query_boundary_fixture(key)
        parsed, repairs = v.console_records(mixed)
        log = self.graph.Log(parsed)
        proof = {'identity': ('258', '382'), 'edges': [{'REQUEST': {'line': 100}}]}
        self.assertEqual(v.check_repaired_queries(log, repairs, proof, self.graph), [])
        with self.assertRaisesRegex(ValueError, 'content-verifier join'):
            v.bind_repairs(proof, repairs)
        proof['actual_graph_Get'] = self.graph.verify_get(log, key, proof['identity'], 0x81cf61c4, 0, 100)
        v.bind_repairs(proof, repairs)
        self.assertTrue(repairs[0]['content_verifier_joined'])
        self.assertEqual(proof['actual_graph_Get']['commit']['fields']['slot'], '4')

    def test_pin_query_uipc_requires_exact_fields_kernel_and_original_terminator(self):
        guest, kernel, mixed = self.pin_query_boundary_fixture()
        mutations = (
            mixed.replace(b'tid=382 ', b'tid=382 tid=382 ', 1),
            mixed.replace(b'tid=382', b'tid=2147483648', 1),
            mixed.replace(b'destination=0x9284074a ', b'', 1),
            mixed.replace(b'source=0x81cf61c4', b'source=0x181cf61c4', 1),
            mixed.replace(b'source=0x81cf61c4', b'source=0x081cf61c4', 1),
            mixed.replace(b'bytes=48', b'bytes=47', 1),
            mixed.replace(b'bytes=48', b'bytes=48 extra=1', 1),
            mixed.replace(b'raw=c', b'raw=C', 1),
            mixed.replace(b'a0a0a0a0', b'a0a0a0a1', 1),
            mixed.replace(guest[:-2], guest[:-3], 1),
            mixed.replace(b'PIN_QUERY', b'PIN_CONTROL_REQUEST', 1),
            mixed.replace(b'cdev_ioctl()', b'cdev_read()'),
            mixed.replace(b'Line 100:', b'Line 101:'),
            mixed.replace(b'uipc:', b'uipx:'),
            mixed.replace(b'ret = -1022', b'ret = -1021'),
            mixed.replace(b'[ 1418.871426]', b'[01418.871426]'),
            mixed.replace(b'[ 1418.871426]', b'[18446744074.871426]'),
            mixed.replace(kernel, kernel + kernel),
            mixed.replace(kernel, kernel[:-2] + b' extra\r\n'),
            mixed.replace(kernel, kernel[:-2] + b'\n'),
            mixed.replace(kernel + b'\r\n', kernel + b'\n'),
            mixed.replace(kernel + b'\r\n', kernel + b'bad=1\r\n'),
            mixed.replace(guest[:-2], guest[:-3] + kernel + guest[-3:-2], 1),
        )
        for raw in mutations:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v.console_records(raw)
        with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
            v.console_records(guest[:-2] + kernel)
        self.assertEqual(v.console_records(guest), (guest, []))
        self.assertEqual(v.console_records(kernel), (kernel, []))

    def test_pin_query_content_rejects_bad_wire_fields_source_or_host_only_free(self):
        _, _, mixed = self.pin_query_boundary_fixture()
        parsed, repairs = v.console_records(mixed)
        original = self.graph.Log(parsed)
        mutations = (
            ('PIN_QUERY', 'source', '0x81cf61c5'),
            ('PIN_QUERY', 'tid', '383'),
            ('FULL_INFRABB_REQUEST', 'reply_destination', '0x81cf61c5'),
            ('FULL_INFRABB_REPLY_QUEUED', 'source', '0x9284074b'),
            ('FULL_INFRABB_REPLY_QUEUED', 'destination', '0x81cf61c5'),
            ('FULL_INFRABB_COMMIT', 'slot', '2'),
            ('FULL_INFRABB_COMMIT', 'index', '2'),
            ('FULL_INFRABB_COMMIT', 'owner', '0x9284074b'),
            ('FULL_INFRABB_COMMIT', 'status', '1'),
            ('FULL_INFRABB_COMMIT', 'request_free_rc', '-1'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'tid', '383'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'sender', '383'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'waiter', '0'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'expected', '0x81cf61c5'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'bytes', '55'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'rc', '-1'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'lease', '4'),
            ('FULL_INFRABB_NATIVE_REPLY_FREE', 'reply', '0x7fae0c6ac1'),
        )
        for tag, field, value in mutations:
            with self.subTest(tag=tag, field=field, value=value):
                log = copy.deepcopy(original)
                row = log.one(tag)
                row['fields'][field] = value
                proof = {'identity': ('258', '382'), 'edges': [{'REQUEST': {'line': 100}}]}
                with self.assertRaises(ValueError):
                    v.check_repaired_queries(log, repairs, proof, self.graph)
        # Complete expected BB reply uses BB's own outer SID; zero is corruption.
        for tag, offsets in (('PIN_QUERY', (0, 8, 20, 26, 44)),
                             ('FULL_INFRABB_REQUEST', (0, 8, 26, 44)),
                             ('FULL_INFRABB_REPLY_QUEUED', (0, 20, 44, 48, 52))):
            for offset in offsets:
                log = copy.deepcopy(original)
                row = log.one(tag)
                wire = bytearray.fromhex(row['fields']['raw']); wire[offset] ^= 1
                row['fields']['raw'] = wire.hex()
                proof = {'identity': ('258', '382'), 'edges': [{'REQUEST': {'line': 100}}]}
                with self.subTest(tag=tag, offset=offset), self.assertRaises(ValueError):
                    v.check_repaired_queries(log, repairs, proof, self.graph)
        log = copy.deepcopy(original)
        row = log.one('FULL_INFRABB_REPLY_QUEUED')
        row['fields']['raw'] = '00000000' + row['fields']['raw'][8:]
        with self.assertRaises(ValueError):
            v.check_repaired_queries(log, repairs, proof, self.graph)
        log = copy.deepcopy(original)
        log.one('FULL_INFRABB_NATIVE_REPLY_FREE')['tag'] = 'FULL_INFRABB_HOST_SEND'
        log.one('FULL_INFRABB_HOST_SEND')['fields']['rc'] = '0'
        with self.assertRaises(ValueError):
            v.check_repaired_queries(log, repairs, proof, self.graph)

    def test_pin_query_no_borrowed_record_or_duplicate_get_join(self):
        guest, kernel, mixed = self.pin_query_boundary_fixture()
        parsed, repairs = v.console_records(mixed)
        log = self.graph.Log(parsed)
        row = log.one('PIN_QUERY')
        for proof in ({}, {'other': {**row, 'line': row['line'] + 1}},
                      {'other': {**row, 'raw': row['raw'].replace('tid=382', 'tid=383')}}):
            with self.subTest(proof=proof), self.assertRaisesRegex(ValueError, 'content-verifier join'):
                v.bind_repairs(proof, copy.deepcopy(repairs))
        proof = {'identity': ('258', '382'), 'edges': [{'REQUEST': {'line': 100}}]}
        for tag in ('PIN_QUERY', 'FULL_INFRABB_REQUEST', 'FULL_INFRABB_REPLY_QUEUED',
                    'FULL_INFRABB_COMMIT', 'FULL_INFRABB_NATIVE_REPLY_FREE'):
            line = log.one(tag)['raw'].encode() + b'\r\n'
            raw = mixed.replace(line, line + line, 1)
            if tag == 'PIN_QUERY':
                # A duplicate before the actual REQUEST cannot lend its consumer.
                raw = mixed.replace(kernel + b'\r\n', kernel + b'\r\n' + guest, 1)
            with self.subTest(duplicate=tag), self.assertRaises(ValueError):
                self.query_content_join(raw)
        for removed in ('FULL_INFRABB_REQUEST', 'FULL_INFRABB_REPLY_QUEUED', 'FULL_INFRABB_COMMIT', 'FULL_INFRABB_NATIVE_REPLY_FREE'):
            raw = mixed.replace(log.one(removed)['raw'].encode() + b'\r\n', b'')
            with self.subTest(missing=removed), self.assertRaises(ValueError):
                self.query_content_join(raw)
        _, _, unknown = self.pin_query_boundary_fixture((9, 1, 1, 0x9284074a))
        with self.assertRaisesRegex(ValueError, 'unsupported canonical BB key'):
            self.query_content_join(unknown)
        # Same query bytes on another line or a Get after graph start cannot satisfy this repair.
        for start in (1, log.one('FULL_INFRABB_NATIVE_REPLY_FREE')['line']):
            wrong = copy.deepcopy(proof); wrong['edges'][0]['REQUEST']['line'] = start
            with self.subTest(graph_start=start), self.assertRaises(ValueError):
                v.check_repaired_queries(log, repairs, wrong, self.graph)
        changed = copy.deepcopy(repairs); changed[0]['parsed_line'] += 1
        with self.assertRaisesRegex(ValueError, 'exact parsed record'):
            v.check_repaired_queries(log, changed, proof, self.graph)

    def test_pin_query_boundary_retains_finite_byte_and_warning_budgets(self):
        guest, kernel, mixed = self.pin_query_boundary_fixture()
        allowed = mixed.replace(b'raw=', b'raw=' + v.WARNINGS[0] * 8, 1)
        self.assertEqual(len(self.query_content_join(allowed)[1]), 9)
        excessive = mixed.replace(b'raw=', b'raw=' + v.WARNINGS[0] * 9, 1)
        with self.assertRaisesRegex(ValueError, 'budget'):
            v.console_records(excessive)
        with patch.object(v, 'MAX_LOG', len(mixed) - 1), self.assertRaisesRegex(ValueError, 'read budget'):
            v.console_records(mixed)
        with self.assertRaises(ValueError):
            v.console_records(guest[:-2] + b' extra=' + b'a' * 1024 + kernel + b'\r\n')
        # Unsupported complete graph/kernel boundaries remain strict successors.
        for guest in (b'OBS FULL_PINMEM_OSD_CONNECT_DMM_REPLY bytes=152 raw=0011 capture_verified=0',
                      b'OBS FULL_PINMEM_OSD_CONNECT_FORMAT_WRITTEN pixels=0'):
            with self.subTest(unknown=guest), self.assertRaisesRegex(ValueError, 'malformed OBS field'):
                v.console_records(guest + kernel + b'\r\n')

    def test_actual_bare_graph_reasons_retained_and_late_refusals_rejected(self):
        # Verbatim run-epi38kew records; these are graph evidence, not ignorable diagnostics.
        rows = (
            b'OBS FULL_SCALAR_CONNECT_UNADMITTED predecessor-or-new-cold-Get-free-not-ready requests=0 faults_unchanged=1\r\n',
            b'OBS FULL_ADF_CONNECT_UNADMITTED predecessor-or-new-cold-Get-free-not-ready requests=0 faults_unchanged=1\r\n',
            b'OBS FULL_PINMEM_DRAWINFO_CONNECT_UNADMITTED predecessor-or-new-cold-Get-free-not-ready requests=0 faults_unchanged=1\r\n',
            b'OBS FULL_PINMEM_HDMI_VIDEO_CONNECT_UNADMITTED predecessor-canonical-Get-or-resource-guard-unavailable\r\n',
            b'OBS FULL_PINMEM_OSD_CONNECT_UNADMITTED first10-AP-or-exact-retired-Get-or-pool-not-ready requests=0 faults_unchanged=1\r\n',
            b'OBS FULL_HDMI_VIDEO_STATE_PENDING waiting-for-actual-UPM-and-condition-receive-free\r\n',
        )
        for raw in rows:
            with self.subTest(raw=raw):
                parsed, repairs = v.console_records(raw)
                self.assertEqual((parsed, repairs), (raw, []))
                tag, fields = v.parse_record(raw)
                expected = {'requests': '0', 'faults_unchanged': '1'} if b'requests=' in raw else {}
                self.assertEqual(fields, expected)
                log = self.graph.Log(parsed)
                self.assertEqual(log.records[0]['raw'], raw.decode().rstrip('\r\n'))
                self.assertEqual(log.records[0]['fields'], expected)
                if tag.endswith('_UNADMITTED'):
                    v.check_late_failures(log, 2)
                    with self.assertRaisesRegex(ValueError, 'graph-phase failure/refusal retained'):
                        v.check_late_failures(log, 1)

    def test_unrelated_bare_reason_diagnostic_preserved(self):
        raw = (b'OBS HOST_TEST_CAPTURE_BLOCKED predecessor-or-new-cold-Get-free-not-ready '
               b'requests=0 faults_unchanged=1\r\n')
        self.assertEqual(v.console_records(raw), (raw, []))
        with self.assertRaisesRegex(ValueError, 'malformed OBS field'):
            v.parse_record(raw)

    def test_bare_reason_does_not_hide_bad_or_missing_graph_fields(self):
        raw = (b'OBS FULL_SCALAR_CONNECT_UNADMITTED predecessor-or-new-cold-Get-free-not-ready '
               b'requests=0 faults_unchanged=1\r\n')
        malformed = (
            raw.replace(b'requests=0', b'requests'),
            raw.replace(b'requests=0', b'requests=0 requests=0'),
            raw.replace(b'requests=0', b'extra-bare-token requests=0'),
            raw.replace(b'predecessor-or-new-cold-Get-free-not-ready', b'unknown-reason'),
            raw.replace(b'predecessor-or-new-cold-Get-free-not-ready ', b'')
               .replace(b'\r\n', b' predecessor-or-new-cold-Get-free-not-ready\r\n'),
            raw.replace(b'FULL_SCALAR_CONNECT_UNADMITTED', b'FULL_SCALAR_CONNECT_COMMIT'),
            raw.replace(b'\r\n', b'[ 1515.781307] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'),
            raw.rstrip(b'\r\n'),
        )
        for row in malformed:
            with self.subTest(raw=row), self.assertRaises(ValueError):
                v.console_records(row)
        for key in ('requests', 'faults_unchanged'):
            row = raw.replace((key + '=' + ('0' if key == 'requests' else '1')).encode(), b'')
            parsed, _ = v.console_records(row)
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, key):
                self.graph.verify_new_edge(self.graph.Log(parsed), self.graph.NEW[1], 2, ('701', '723'), 2)

    def test_duplicate_or_partial_graph_fields_rejected(self):
        for raw in (b'OBS FULL_PINMEM_OSD_CONNECT_COMMIT capture_verified=0 capture_verified=1\n',
                    b'OBS FULL_PINMEM_OSD_CONNECT_COMMIT capture_verified=0',
                    b'OBS FULL_PINMEM_OSD_CONNECT_COMMIT capture_veri\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                v.console_records(raw)

    def osd_source_fixture(self):
        """HOST_TEST source-format producer rows; no C build or native-positive claim."""
        h, caller, pid, tid = self.osd, 0x81cf619b, 701, 723
        rows, allocations = [], 0
        def emit(tag, **fields):
            row = record(h.PREFIX + '_' + tag, **fields)
            rows.append(row['raw'].encode() + b'\r\n')
        def pointer():
            nonlocal allocations
            allocations += 1
            return hex(0x10000 + allocations * 0x100)
        def wire(tag, source, destination, data):
            p = pointer()
            emit(tag, pid=pid, tid=tid, source=hex(source), destination=hex(destination), pointer=p,
                 bytes=len(data), raw=data.hex(), virtual_local_transport=1, original_CP_executed=0,
                 original_CP_pages_verified=0, frames_verified=0, capture_verified=0)
            return p
        def release(p):
            emit('INTERNAL_FREE', owner=hex(caller), pointer=p, rc=0, pool_references_released=0)
        emit('PROFILE', pid=pid, requested=h.PROFILE, enabled=1, first_missing='none', owner_pid=pid,
             initialized=1, before_any_input=1, original_cp_executed=0, hardware_verified=0,
             metadata_ready=0, gpe_ready=0, frames_verified=0, connection_verified=0, capture_verified=0)
        rows += [b'HOST_TEST first_graph_request\r\n', b'HOST_TEST predecessor_free\r\n']
        for key in (h.S, h.P):
            family, slot = h.OWNERS[key[3]][0], h.SLOTS[key]
            query = self.old.frame_bytes(48, 0, 2, key[:3] + (0,), caller, struct.pack('<I', key[3]))
            reply = self.old.frame_bytes(56, 0x8000, 2, key[:3] + (1, key[3], 0), key[3] if key == h.P else 0)
            p = pointer()
            gets = [record('PIN_QUERY', tid=tid, destination=hex(key[3]), source=hex(caller), bytes=48, raw=query.hex()),
                record('FULL_' + family + '_REQUEST', tid=tid, destination=hex(key[3]), source=hex(caller),
                       reply_destination=hex(caller), bytes=48, raw=query.hex()),
                record('FULL_' + family + '_REPLY_QUEUED', tid=tid, source=hex(key[3]), destination=hex(caller),
                       reply=p, lease=1, bytes=56, raw=reply.hex()),
                record('FULL_' + family + '_COMMIT', tid=tid, slot=slot, type=key[0], dir=key[1], index=key[2],
                       pin_state=1, owner=hex(key[3]), status=0, queries=1, reply=p, lease=1,
                       request_free_rc=0, connect_performed=0, pixels_consumed=0, camera_startup_verified=0),
                record('FULL_' + family + '_NATIVE_REPLY_FREE', tid=tid, sender=tid, waiter=1,
                       destination=hex(caller), expected=hex(caller), reply=p, lease=1, bytes=56, rc=0)]
            rows += [r['raw'].encode() + b'\r\n' for r in gets]
        emit('RESOURCE_DEPENDENCIES', pid=pid, tid=tid, accepted=1, proc_ap_consumed=1, input_ap_consumed=1,
             output_ap_consumed=1, output_faults=0, current_request_retained_expected=1, capture_verified=0)
        emit('RESOURCES_TTS_TABLE', pid=pid, tid=tid, table_va='0x5f66b08', bytes=144, reads='144/144', unchanged=1,
             atomic_snapshot=0, ownership_verified=0, appfw_base='0x7000000000', address=hex(0x7000000000 + 0x5f66b08),
             raw_before=bytes(144).hex(), raw_after=bytes(144).hex())
        emit('RESOURCES_RESERVED', tid=tid, accepted=1, allocations=4, releases=4, control_live=0, control_faults=0,
             control_bound=1, dmm_enabled=1, dmm_bound=1, dmm_domain=2, foreign_speech_kept=1, dmm_allocation_count=2,
             dmm_lifecycle_changed=0, dmm_slots='1/1', dmm_opens='1/1', dmm_handles='0x8400/0x8401',
             dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1', format_consumed=1, buffer_released=1,
             connection_reply_frees=1, connection_faults=0, vef_pending=0, vef_live=0, vef_retained=0, vef_faults=0,
             pinmem_pending=0, pinmem_live=0, pinmem_retained=0, pinmem_faults=0)
        resources, controls, sequence = {}, {}, 0
        for tag, key in h._plan():
            if tag == 'REQUEST':
                original = wire(tag, caller, h.S[3], self.old.frame_bytes(64, 1, 2, h.S + h.P, caller, b'\xa7\x19\0\x5a'))
            elif tag == 'DMM_REQUEST':
                bank, ordinal, op = key
                producer = h.S[3] if bank else h.P[3]
                side = (h.P[3] if bank else h.S[3]) if op == 0x24 else producer
                n = 152 if side == h.S[3] else 40
                sequence += 1
                local, token = 0x61003c + (sequence - 1) * 4, 0x4f00 + sequence
                if op == 0x20:
                    slot = len(resources)
                    resources[key[:2]] = (0xe1000010 | slot, 0x500010000 + slot * 256, 0x81000000 + slot * 256)
                handle, physical, alias = resources[key[:2]]
                data = bytearray([0xa5] * n)
                struct.pack_into('<H', data, 0, op)
                if op != 0x24:
                    struct.pack_into('<I', data, 4, h.UNIT)
                if op != 0x20:
                    struct.pack_into('<I', data, 8, handle)
                struct.pack_into('<IIHH', data, 12, 0 if op == 0x24 else 0xffffffff, local, token, int(op == 0x20))
                dmm_request = wire(tag, side, h.DMM, data)
            elif tag == 'DMM_REPLY':
                data = bytearray([0xa5] * n); data[:40] = bytes(40)
                struct.pack_into('<H', data, 0, op | 0x8000)
                struct.pack_into('<HH', data, 6, token, 1)
                struct.pack_into('<I', data, 12, handle)
                if op != 0x24:
                    struct.pack_into('<I', data, 16, h.UNIT)
                struct.pack_into('<QI', data, 24, physical, 256)
                p = wire(tag, h.DMM, local, data)
                release(dmm_request); release(p)
            elif tag == 'FORMAT_WRITTEN':
                bank, ordinal = key
                handle, physical, alias = resources[key]
                data, known, used = h._backing(bank, resources[0, ordinal][0] if bank == 1 else 0)
                emit(tag, bank=bank, ordinal=ordinal, handle=hex(handle), unit=hex(h.UNIT), extent=256,
                     physical=hex(physical), cp_alias=hex(alias), used=used, known=sum(known),
                     fnv=h._fnv(data), known_fnv=h._fnv(known), pixels=0)
            elif tag in ('PEER_REQUEST', 'PEER_REPLY'):
                reply = tag == 'PEER_REPLY'
                controls[tag] = wire(tag, h.P[3] if reply else h.S[3], h.S[3] if reply else h.P[3],
                    self.old.frame_bytes(72 if reply else 64, 0x8100 if reply else 0x100, 1,
                                         h.S + h.P + ((0, 0) if reply else ())))
            elif tag in ('PEER_NOTIFY', 'SOURCE_NOTIFY'):
                bank, ordinal = key
                producer, consumer = (h.S[3], h.P[3]) if bank else (h.P[3], h.S[3])
                notice = wire(tag, producer, consumer, self.old.frame_bytes(80, 0x102, 1,
                    (1, 3, 0, consumer, 1, 3, 0, producer, h.UNIT, resources[key][0], 0, 0), opaque=b'\xa5' * 4))
            elif tag == 'FORMAT_CONSUMED':
                emit(tag, bank=key[0], ordinal=key[1], handle=hex(resources[key][0]), actual_mapping_read=1,
                     owners=2, opens=2, creator_open=1, consumer_open=1, retained=1,
                     optional_diagnostic_does_not_gate=1, capture_verified=0)
                release(notice)
            elif tag == 'EVENT6_ENQUEUED':
                emit(tag, event=6, parameter_bytes=12, token=hex(h.TOKEN), token_policy='owned-answer-plus24-map',
                     saved_original_request_bytes=64, queue_phase=1, wait_primary=6, keep_pending=1,
                     context_kind=2, original_RTOS_scheduling_verified=0)
            elif tag == 'EVENT6_CONSUMED':
                emit(tag, parameter_bytes=12, actual_parameter_read=1, token_body_binding_verified=1,
                     saved_peer_u32_fields_verified=4, source_complete_raw='0x5839a6', source_state=0, status=0,
                     tail=0, original_RTOS_scheduling_verified=0)
            elif tag == 'SOURCE_POST':
                emit(tag, source_raw='0x5d61a2', inactive_rows=5, selected_tag100_backing_count=0, OSD_cached_count=1,
                     repeated_notice=0, extra_share=0, extra_open=0, metadata_ready=1, graphics_ready=0, GPE_ready=0,
                     optional_diagnostic_skipped=1)
                for p in controls.values():
                    release(p)
            elif tag == 'RESOURCE_READBACK':
                emit(tag, live=16, owners_each=2, opens_each=2, DMM_requests=48, DMM_replies=48, reference_readbacks=48,
                     peer_notices=4, source_notices=12, exact_backing_and_known_masks_verified=1, selected_backing_count=0,
                     cached_count=1, original_allocator_capacity_verified=0, original_CP_pages_verified=0,
                     frames_verified=0, capture_verified=0)
            elif tag == 'REPLY_QUEUED':
                final = wire(tag, h.S[3], caller, self.old.frame_bytes(56, 0x8001, 2, h.S + (0, 0)))
            elif tag == 'REQUEST_FREE':
                emit(tag, owner=hex(h.S[3]), pointer=original, bytes=64, rc=0)
            elif tag == 'COMMIT':
                emit(tag, source_state=0, peer_state=0, pending=0, metadata_only=1,
                     AP_reply_after_16_buffers_48_DMM_and_source_post=1, persistent_resources=16,
                     graphics_ready=0, GPE_ready=0, frames_verified=0, capture_verified=0)
            elif tag == 'NATIVE_REPLY_FREE':
                emit(tag, pid=pid, tid=tid, sender=tid, waiter=1, destination=hex(caller), expected=hex(caller),
                     reply=final, bytes=56, command='0x8001', rc=0, faults=0, ap_consumed=1, capture_verified=0)
            else:
                self.fail('unhandled HOST_TEST OSD plan tag: ' + tag)
        return b''.join(rows)

    def osd_content_join(self, raw):
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        proof = self.osd.verify_osd_edge(log, 3, ('701', '723'), 2, self.graph)
        v.bind_repairs(proof, repairs)
        return parsed, repairs, proof

    def test_all_osd_banks_and_complete_dmm_sizes_join_real_frozen_edge(self):
        original = self.osd_source_fixture()
        kernel = b'[ 1522.508050] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        mixed, expected, targets = [], [], 0
        for row in original.splitlines(keepends=True):
            if any(row.startswith(('OBS ' + self.osd.PREFIX + '_' + tag + ' ').encode()) for tag in
                   ('FORMAT_WRITTEN', 'DMM_REQUEST', 'DMM_REPLY')):
                targets += 1
                payload = row[:-2]
                # Both within-field and after-complete-tail vvfat placements.
                if b' pixels=0' in payload:
                    payload += v.WARNINGS[0]
                else:
                    payload = payload.replace(b'raw=', b'ra' + v.WARNINGS[1] + b'w=', 1)
                mixed.append(payload + kernel + b'\r\n')
                expected.append(row + kernel)
            else:
                mixed.append(row); expected.append(row)
        raw = b''.join(mixed)
        parsed, repairs, proof = self.osd_content_join(raw)
        self.assertEqual(parsed, b''.join(expected))
        self.assertEqual((targets, len(repairs)), (112, 224))
        self.assertEqual(len(proof['resources']), 16)
        self.assertEqual(len(proof['DMM_exchanges']), 48)
        self.assertEqual(len(proof['internal_frees']), 114)
        self.assertFalse(proof['capture_verified'])
        self.assertFalse(proof['hardware_verified'])
        self.assertEqual({(r['bank'], r['ordinal']) for r in proof['resources']},
                         {(bank, ordinal) for bank in range(4) for ordinal in range(4)})
        self.assertEqual({r['request']['fields']['bytes'] for r in proof['DMM_exchanges']}, {'40', '152'})
        for repair in repairs:
            with self.subTest(kind=repair['kind'], line=repair['parsed_line']):
                self.assertTrue(repair['content_verifier_joined'])
                self.assertFalse(repair['guest_bytes_invented'])
                if repair['kind'].endswith('UIPC-boundary'):
                    self.assertEqual(raw[repair['raw_kernel_start']:repair['raw_kernel_end']], kernel)
                    self.assertEqual(raw[repair['raw_guest_ending_start']:repair['raw_guest_ending_end']], b'\r\n')
                    self.assertEqual(repair['framing_bytes_inserted'], 0)

    def test_osd_complete_printf_grammar_is_source_bound(self):
        source = v.read(v.RUNTIME / 'device-models/pinmem-osd-connection.c').decode()
        self.assertIn('"bank=%u ordinal=%u handle=%#x unit=%#x extent=256 physical=%#llx cp_alias=%#x '
                      'used=%u known=%u fnv=%016llx known_fnv=%016llx pixels=0"', source)
        self.assertIn('"pid=%d tid=%ld source=%#x destination=%#x pointer=%p bytes=%u raw=%s '
                      'virtual_local_transport=1 original_CP_executed=0 original_CP_pages_verified=0 '
                      'frames_verified=0 capture_verified=0"', source)
        self.assertIn('wire(io,"DMM_REQUEST ",sid(side),DMM,request,bytes);', source)
        self.assertIn('wire(io,"DMM_REPLY ",DMM,local,reply,bytes);', source)
        self.assertIn('for(unsigned int bank=2;bank<4;bank++)for(unsigned int i=0;i<4;i++)', source)
        self.assertIn('for(unsigned int i=0;i<4;i++)if(create_format(io,0,i,0,0))', source)
        log = self.graph.Log(self.osd_source_fixture())
        for tag, grammar in (('FORMAT_WRITTEN', v.OSD_FORMAT_WRITTEN), ('DMM_REQUEST', v.OSD_DMM_MESSAGE),
                             ('DMM_REPLY', v.OSD_DMM_MESSAGE)):
            for row in log.rows(self.osd.PREFIX + '_' + tag):
                with self.subTest(tag=tag, line=row['line']):
                    self.assertIsNotNone(grammar.fullmatch(row['raw'].encode()))

    def test_osd_boundaries_refuse_incomplete_unknown_or_ambiguous_transport(self):
        log = self.graph.Log(self.osd_source_fixture())
        kernel = b'[ 1531.715414] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        guests = [log.rows(self.osd.PREFIX + '_' + tag)[-1]['raw'].encode() for tag in
                  ('FORMAT_WRITTEN', 'DMM_REQUEST', 'DMM_REPLY')]
        for guest in guests:
            complete = guest + kernel + b'\r\n'
            mutations = [guest[:-1] + kernel + b'\r\n', guest + b' extra=1' + kernel + b'\r\n',
                guest + b' bare' + kernel + b'\r\n', guest + kernel + b'bad=1\r\n',
                guest + kernel + b'\n', guest + kernel + kernel + b'\r\n',
                complete.replace(b'Line 100:', b'Line 101:'), complete.replace(b'ret = -1022', b'ret = -1021'),
                complete.replace(b'[ 1531.715414]', b'[01531.715414]'),
                complete.replace(b'[ 1531.715414]', b'[18446744074.715414]'),
                guest + kernel[:-2] + b'\n\r\n', guest[:50] + kernel + guest[50:] + b'\r\n',
                guest + v.WARNINGS[0] * 9 + kernel + b'\r\n', guest + b' padding=' + b'a' * 1024 + kernel + b'\r\n']
            if b'FORMAT_WRITTEN' in guest:
                mutations += [complete.replace(b'bank=3', b'bank=4'), complete.replace(b'ordinal=3', b'ordinal=04'),
                    complete.replace(b'pixels=0', b'pixels=1'), complete.replace(b'known=90', b'known=257'),
                    complete.replace(b'known_fnv=', b'unknown_fnv='), complete.replace(b'unit=0xe1700 ', b''),
                    complete.replace(b'pixels=0', b'pixels=0 pixels=0')]
            else:
                mutations += [complete.replace(b'pid=701', b'pid=2147483648'),
                    complete.replace(b'tid=723', b'tid=0723'), complete.replace(b'source=0x', b'source=0x0'),
                    complete.replace(b'pointer=0x', b'pointer=0x10000000000000000'),
                    complete.replace(b'bytes=40 ', b'bytes=152 '), complete.replace(b' raw=', b' unexpected='),
                    complete.replace(b'capture_verified=0', b'capture_verified=1')]
            for raw in mutations:
                with self.subTest(tag=guest.split()[1], raw=raw), self.assertRaises(ValueError):
                    v.console_records(raw)
            with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
                v.console_records(guest + kernel)
            self.assertEqual(v.console_records(guest + b'\r\n'), (guest + b'\r\n', []))

    def test_osd_repair_cannot_borrow_content_or_bypass_semantic_body_and_free(self):
        original = self.osd_source_fixture()
        log = self.graph.Log(original)
        kernel = b'[ 1522.508050] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        format_row = log.rows(self.osd.PREFIX + '_FORMAT_WRITTEN')[7]['raw'].encode()
        mixed = original.replace(format_row + b'\r\n', format_row + v.WARNINGS[0] + kernel + b'\r\n', 1)
        parsed, repairs, proof = self.osd_content_join(mixed)
        written = proof['resources'][7]['written']
        for content in ({}, {'other': {**written, 'line': written['line'] + 1}},
                        {'other': {**written, 'raw': written['raw'].replace('pixels=0', 'pixels=1')}}):
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, 'content-verifier join'):
                v.bind_repairs(content, copy.deepcopy(repairs))
        # All mutations below still parse; the unchanged real content code must refuse.
        cases = [('FORMAT_WRITTEN', 'fnv', '0000000000000000'),
                 ('FORMAT_WRITTEN', 'known_fnv', '0000000000000000'),
                 ('FORMAT_WRITTEN', 'handle', '0xe100001f'), ('FORMAT_WRITTEN', 'known', '127'),
                 ('DMM_REPLY', 'source', '0x9059000f'), ('DMM_REPLY', 'tid', '724'),
                 ('FORMAT_CONSUMED', 'owners', '1'), ('RESOURCE_READBACK', 'opens_each', '1'),
                 ('NATIVE_REPLY_FREE', 'tid', '724'), ('NATIVE_REPLY_FREE', 'bytes', '55'),
                 ('INTERNAL_FREE', 'owner', '0x81cf619c'), ('COMMIT', 'metadata_only', '0')]
        for tag, field, value in cases:
            changed = self.graph.Log(parsed)
            changed.rows(self.osd.PREFIX + '_' + tag)[0]['fields'][field] = value
            with self.subTest(tag=tag, field=field), self.assertRaises(ValueError):
                self.osd.verify_osd_edge(changed, 3, ('701', '723'), 2, self.graph)
        for tag in ('DMM_REQUEST', 'DMM_REPLY'):
            for offset in (0, 2, 20, 39, 40, 151):
                changed = self.graph.Log(parsed)
                row = next(r for r in changed.rows(self.osd.PREFIX + '_' + tag) if r['fields']['bytes'] == '152')
                data = bytearray.fromhex(row['fields']['raw']); data[offset] ^= 1
                row['fields']['raw'] = data.hex()
                with self.subTest(tag=tag, offset=offset), self.assertRaises(ValueError):
                    self.osd.verify_osd_edge(changed, 3, ('701', '723'), 2, self.graph)
        for tag in ('FORMAT_WRITTEN', 'DMM_REPLY', 'INTERNAL_FREE'):
            row = log.rows(self.osd.PREFIX + '_' + tag)[0]['raw'].encode() + b'\r\n'
            for replacement in (b'', row + row):
                with self.subTest(tag=tag, duplicate=bool(replacement)), self.assertRaises(ValueError):
                    self.osd_content_join(original.replace(row, replacement, 1))
        with self.assertRaisesRegex(ValueError, 'predecessor/graph bound'):
            self.osd.verify_osd_edge(self.graph.Log(parsed), 2, ('701', '723'), 3, self.graph)
        with self.assertRaisesRegex(ValueError, 'PID/TID differs'):
            self.osd.verify_osd_edge(self.graph.Log(parsed), 3, ('702', '723'), 2, self.graph)

    def vef_request_window_fixture(self):
        # Verbatim 05b0 bytes [1828511:1828788], console SHA e835b770...84d1c0.
        guest = (b'OBS FULL_VEF_REQUEST tid=383 destination=0x905a0048 source=0x81cf61c4 '
                 b'reply_destination=0x81cf61c4 bytes=48 '
                 b'raw=c461cf81a0a0a0a00100300018000000300000007f000000001000001800020000000000020000000200000000000000')
        mixed = guest.replace(b'reply_destination=', b'r' + v.WARNINGS[0] + b'eply_destination=', 1) + b'\r\n'
        self.assertEqual(len(mixed), 277)
        self.assertEqual(v.sha(mixed), '3e6f0ce81635a31477aaf03df344f17767e6ad15b8436cc0d5b6ab355d5f56ab')
        self.assertEqual(v.sha(guest), '9656388d4e83d8f5f165582d8619ff2b0cb2e4113e7ef2a2e566a1f51b0fe265')
        return guest, mixed

    def vef_request_trace_fixture(self):
        """Selected verbatim native rows; component evidence, no thirteen-edge positive."""
        _, mixed = self.vef_request_window_fixture()
        rows = [
            b'OBS FULL_INFRABB_VEF_CONTROL_CONNECT_REQUEST pid=259 tid=383 source=0x81cf61c4 destination=0x9284074a pointer=0x7fb3c81fc0 bytes=64 raw=c461cf81a0a0a0a00100400018000000400000000000000000100100280002000800000002000000000000004a07849208000000010000000000000048005a90 transport_owner=virtual-local-caller original_cp_executed=0 frames_verified=0 capture_verified=0',
            b'OBS FULL_INFRABB_VEF_CONTROL_CONNECT_REPLY_FREE pid=259 tid=383 destination=0x81cf61c4 expected=0x81cf61c4 pointer=0x7fb3dc9e80 bytes=56 rc=0 faults=0 ap_consumed=1 frames_verified=0 capture_verified=0',
            b'OBS PIN_QUERY tid=383 destination=0x905a0048 source=0x81cf61c4 bytes=48 raw=c461cf81a0a0a0a00100300018000000300000007f000000001000001800020000000000020000000200000000000000',
            mixed[:-2],
            b'OBS FULL_VEF_REPLY_QUEUED tid=383 source=0x905a0048 destination=0x81cf61c4 reply=0x7fb3dc9e80 lease=8 bytes=56 raw=00000000a0a0a0a00100380018000000380000000000000000100080200002000000000002000000020000000100000048005a9000000000',
            b'OBS FULL_VEF_COMMIT tid=383 slot=9 type=0 dir=2 index=2 pin_state=1 owner=0x905a0048 status=0 queries=8 reply=0x7fb3dc9e80 lease=8 request_free_rc=0 connect_performed=0 pixels_consumed=0 camera_startup_verified=0',
            b'OBS FULL_VEF_NATIVE_REPLY_FREE tid=383 sender=383 waiter=1 destination=0x81cf61c4 expected=0x81cf61c4 reply=0x7fb3dc9e80 lease=8 bytes=56 rc=0',
            b'OBS PIN_QUERY tid=383 destination=0x90590818 source=0x81cf61c4 bytes=48 raw=c461cf81a0a0a0a001003000180000003000000000000000001000001800020000000000010000000000000000000000',
            b'OBS FULL_VEF_PINMEM_INPUT_CONNECT_REQUEST pid=259 tid=383 source=0x81cf61c4 destination=0x905a0048 pointer=0x7fb3c32fc0 bytes=64 raw=c461cf81a0a0a0a001004000180000004000000000000000001001002800020000000000020000000200000048005a9000000000010000000000000018085990 transport_owner=virtual-local-caller canonical_padding=1 original_CP_executed=0 frames_verified=0 capture_verified=0',
            b'OBS FULL_VEF_PINMEM_INPUT_CONNECT_REPLY_FREE pid=259 tid=383 destination=0x81cf61c4 expected=0x81cf61c4 pointer=0x7fb3dc9e80 bytes=56 rc=0 faults=0 ap_consumed=1 frames_verified=0 capture_verified=0',
        ]
        return b'\r\n'.join(rows) + b'\r\n'

    def vef_request_context(self, log):
        # Connection anchors already established by check_graph_content in production.
        edges = []
        for prefix, _, _, source, peer in (self.graph.old.SPECS[-1], self.graph.six.SIXTH):
            request = log.one(prefix + '_REQUEST')
            _, caller = self.old.request_bytes(request, source, peer)
            edges.append(dict(REQUEST=request, REPLY_FREE=log.one(prefix + '_REPLY_FREE'),
                              source_pin=source, sink_pin=peer, caller=caller))
        return {'identity': ('259', '383'), 'edges': edges}

    def test_vef_request_native_window_and_complete_source_grammar(self):
        guest, mixed = self.vef_request_window_fixture()
        source = v.read(v.RUNTIME / 'device-models/pin-registry-core.c').decode()
        self.assertIn('"tid=%ld destination=%#x source=%#x reply_destination=%#x bytes=48 raw=%s",', source)
        self.assertIn('syscall(SYS_gettid),destination,source,dst,raw);event(owner,io,"REQUEST ",line);', source)
        registry = v.read(v.RUNTIME / 'device-models/vef-device.c').decode()
        keys = [tuple(map(int, values)) for values in re.findall(r'\{(\d+),(\d+),(\d+)\}', registry)]
        self.assertEqual(v.VEF_GET_SLOTS, {key + (0x905a0048,): slot for slot, key in enumerate(keys)})
        self.assertIsNotNone(v.VEF_GET_REQUEST.fullmatch(guest))
        parsed, repairs = v.console_records(mixed)
        self.assertEqual(parsed, guest + b'\r\n')
        repair, = repairs
        self.assertEqual((repair['parsed_line'], repair['raw_warning_start']), (1, 71))
        self.assertEqual(repair['repaired_record_sha256'], v.sha(guest))
        self.assertFalse(repair['guest_bytes_invented'])
        self.assertNotIn('content_verifier_joined', repair)

    def test_vef_request_joins_real_get_request_reply_commit_and_same_ap_free(self):
        parsed, repairs = v.console_records(self.vef_request_trace_fixture())
        log = self.graph.Log(parsed)
        proof = self.vef_request_context(log)
        with self.assertRaises(v.UnjoinedRepairs):
            v.bind_repairs(proof, repairs)
        slots = dict(self.graph.SLOTS)
        proof['repaired_VEF_Get_joins'] = v.check_repaired_vef_gets(log, repairs, proof, self.graph)
        content, = proof['repaired_VEF_Get_joins']
        self.assertIs(content['request'], log.one('FULL_VEF_REQUEST'))
        self.assertIs(content['original_AP_query'], log.rows('PIN_QUERY')[0])
        self.assertIs(content['reply'], log.one('FULL_VEF_REPLY_QUEUED'))
        self.assertIs(content['commit'], log.one('FULL_VEF_COMMIT'))
        self.assertIs(content['actual_same_sender_free'], log.one('FULL_VEF_NATIVE_REPLY_FREE'))
        self.assertEqual((content['key'], content['lease'], content['commit']['fields']['slot']),
                         ((0, 2, 2, 0x905a0048), '8', '9'))
        self.assertEqual(content['predecessor_AP_free_line'], proof['edges'][0]['REPLY_FREE']['line'])
        self.assertEqual(content['connection_request_line'], proof['edges'][1]['REQUEST']['line'])
        self.assertEqual(content['connection_prefix'], self.graph.six.SIXTH[0])
        self.assertEqual(self.graph.SLOTS, slots)
        self.assertNotIn(content['key'], self.graph.SLOTS)
        v.bind_repairs(proof, repairs)
        self.assertTrue(repairs[0]['content_verifier_joined'])
        self.assertNotIn('graph_verified', content)
        self.assertNotIn('capture_verified', content)

    def test_vef_request_missing_or_duplicate_get_and_edge_records_rejected(self):
        parsed, repairs = v.console_records(self.vef_request_trace_fixture())
        base = self.graph.Log(parsed)
        tags = ('FULL_VEF_REQUEST', 'FULL_VEF_REPLY_QUEUED', 'FULL_VEF_COMMIT', 'FULL_VEF_NATIVE_REPLY_FREE',
                'FULL_INFRABB_VEF_CONTROL_CONNECT_REQUEST', 'FULL_INFRABB_VEF_CONTROL_CONNECT_REPLY_FREE',
                'FULL_VEF_PINMEM_INPUT_CONNECT_REQUEST', 'FULL_VEF_PINMEM_INPUT_CONNECT_REPLY_FREE')
        for tag in ('PIN_QUERY',) + tags:
            for duplicate in (False, True):
                log = copy.deepcopy(base)
                row = log.rows(tag)[0]
                if duplicate:
                    log.records.insert(log.records.index(row), copy.deepcopy(row))
                else:
                    log.records.remove(row)
                with self.subTest(tag=tag, duplicate=duplicate), self.assertRaises(ValueError):
                    v.check_repaired_vef_gets(log, repairs, self.vef_request_context(log), self.graph)
        self.assertNotIn('content_verifier_joined', repairs[0])

    def test_vef_request_wrong_caller_key_slot_status_lease_and_free_rejected(self):
        parsed, repairs = v.console_records(self.vef_request_trace_fixture())
        base = self.graph.Log(parsed)
        cases = (('FULL_VEF_REQUEST', 'tid', '384'), ('FULL_VEF_REQUEST', 'source', '0x81cf61c5'),
                 ('FULL_VEF_REQUEST', 'reply_destination', '0x81cf61c5'),
                 ('FULL_VEF_REPLY_QUEUED', 'destination', '0x81cf61c5'), ('FULL_VEF_REPLY_QUEUED', 'lease', '9'),
                 ('FULL_VEF_COMMIT', 'slot', '8'), ('FULL_VEF_COMMIT', 'pin_state', '0'),
                 ('FULL_VEF_COMMIT', 'owner', '0x905a0049'), ('FULL_VEF_COMMIT', 'status', '1'),
                 ('FULL_VEF_COMMIT', 'request_free_rc', '-1'),
                 ('FULL_VEF_NATIVE_REPLY_FREE', 'tid', '384'), ('FULL_VEF_NATIVE_REPLY_FREE', 'sender', '384'),
                 ('FULL_VEF_NATIVE_REPLY_FREE', 'waiter', '0'), ('FULL_VEF_NATIVE_REPLY_FREE', 'expected', '0x81cf61c5'),
                 ('FULL_VEF_NATIVE_REPLY_FREE', 'reply', '0x7fb3dc9e81'), ('FULL_VEF_NATIVE_REPLY_FREE', 'lease', '9'),
                 ('FULL_VEF_NATIVE_REPLY_FREE', 'bytes', '55'), ('FULL_VEF_NATIVE_REPLY_FREE', 'rc', '-1'),
                 ('FULL_VEF_PINMEM_INPUT_CONNECT_REQUEST', 'pid', '260'),
                 ('FULL_VEF_PINMEM_INPUT_CONNECT_REPLY_FREE', 'tid', '384'),
                 ('FULL_INFRABB_VEF_CONTROL_CONNECT_REPLY_FREE', 'rc', '-1'))
        wire_cases = [(tag, 'wire', offset) for tag, offsets in (
            ('PIN_QUERY', (0, 4, 8, 20, 26, 32, 35, 39, 43, 44)),
            ('FULL_VEF_REQUEST', (0, 4, 8, 20, 26, 32, 35, 39, 43, 44)),
            ('FULL_VEF_REPLY_QUEUED', (0, 4, 8, 20, 26, 32, 35, 39, 43, 44, 48, 52))) for offset in offsets]
        for tag, field, value in list(cases) + wire_cases:
            log, changed = copy.deepcopy(base), copy.deepcopy(repairs)
            row = log.rows(tag)[0]
            if field == 'wire':
                wire = bytearray.fromhex(row['fields']['raw']); wire[value] ^= 1
                row['fields']['raw'] = wire.hex()
            else:
                row['fields'][field] = value
            row['raw'] = record(row['tag'], row['line'], **row['fields'])['raw']
            if tag == 'FULL_VEF_REQUEST':
                changed[0].update(repaired_record=row['raw'], repaired_record_sha256=v.sha(row['raw'].encode()))
            with self.subTest(tag=tag, field=field, value=value), self.assertRaises(ValueError):
                v.check_repaired_vef_gets(log, changed, self.vef_request_context(log), self.graph)

    def test_vef_request_requires_adjacent_edge_interval_and_exact_repair_identity(self):
        parsed, repairs = v.console_records(self.vef_request_trace_fixture())
        base = self.graph.Log(parsed)
        for kind in ('predecessor-bound', 'connection-bound', 'next-query-bound', 'wrong-edge-key',
                     'wrong-predecessor', 'wrong-caller', 'cross-thread', 'borrowed-line', 'borrowed-raw'):
            log, changed = copy.deepcopy(base), copy.deepcopy(repairs)
            proof = self.vef_request_context(log)
            request, free = log.one('FULL_VEF_REQUEST'), log.one('FULL_VEF_NATIVE_REPLY_FREE')
            if kind == 'predecessor-bound':
                proof['edges'][0]['REPLY_FREE']['line'] = request['line']
            elif kind == 'connection-bound':
                proof['edges'][1]['REQUEST']['line'] = free['line']
            elif kind == 'next-query-bound':
                free['line'] = log.rows('PIN_QUERY')[1]['line']
            elif kind == 'wrong-edge-key':
                proof['edges'][1]['source_pin'] = (0, 2, 1, 0x905a0048)
            elif kind == 'wrong-predecessor':
                proof['edges'][0]['REQUEST']['tag'] = self.graph.old.SPECS[2][0] + '_REQUEST'
            elif kind == 'wrong-caller':
                proof['edges'][1]['caller'] += 1
            elif kind == 'cross-thread':
                proof['identity'] = ('259', '384')
            elif kind == 'borrowed-line':
                changed[0]['parsed_line'] += 1
            else:
                changed[0]['repaired_record'] = changed[0]['repaired_record'].replace('reply_destination=0x81cf61c4',
                                                                                   'reply_destination=0x81cf61c5')
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                v.check_repaired_vef_gets(log, changed, proof, self.graph)
        # Equal copied records cannot substitute for the exact row consumed by the real verifier.
        for field in ('request', 'original_AP_query'):
            def borrowed(code, namespace):
                actual = types.FunctionType(code, namespace)
                def consume(*args):
                    result = actual(*args)
                    result[field] = copy.deepcopy(result[field])
                    return result
                return consume
            with self.subTest(field=field), patch.object(v, 'types', types.SimpleNamespace(FunctionType=borrowed)), \
                    self.assertRaisesRegex(ValueError, 'borrowed another Get'):
                v.check_repaired_vef_gets(base, repairs, self.vef_request_context(base), self.graph)
        row = base.one('FULL_VEF_REQUEST')
        for borrowed in ({**row, 'line': row['line'] + 1}, {**row, 'raw': row['raw'] + ' extra=1'}):
            with self.subTest(borrowed=borrowed), self.assertRaises(v.UnjoinedRepairs):
                v.bind_repairs({'other': borrowed}, copy.deepcopy(repairs))

    def test_vef_request_unknown_or_noncanonical_producer_fields_still_fail(self):
        raw = self.vef_request_trace_fixture()
        for old, new in ((b'FULL_VEF_REQUEST tid=383', b'FULL_VEF_REQUEST tid=0383'),
                         (b'FULL_VEF_REQUEST tid=383', b'FULL_VEF_REQUEST tid=2147483648'),
                         (b'r' + v.WARNINGS[0] + b'eply_destination=0x81cf61c4',
                          b'r' + v.WARNINGS[0] + b'eply_destination=0x081cf61c4'),
                         (b'r' + v.WARNINGS[0] + b'eply_destination=0x81cf61c4 bytes=48 raw=',
                          b'r' + v.WARNINGS[0] + b'eply_destination=0x81cf61c4 bytes=48 extra=1 raw=')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                parsed, repairs = v.console_records(raw.replace(old, new, 1))
                log = self.graph.Log(parsed)
                v.check_repaired_vef_gets(log, repairs, self.vef_request_context(log), self.graph)

    def pinmem_queued_boundary_fixture(self):
        # Verbatim 05b0 LF17756-17757, original console SHA e835b770...84d1c0.
        guest = (b'OBS FULL_PINMEM_REPLY_QUEUED tid=383 source=0x90590818 destination=0x81cf61c4 '
                 b'reply=0x7fb3dc9e80 lease=11 bytes=56 '
                 b'raw=00000000a0a0a0a0010038001800000038000000000000000010008020000200000000000200000001000000010000001808599000000000')
        kernel = b'[ 5541.379070] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        self.assertEqual(len(guest + kernel[:-1]), 301)
        self.assertEqual(v.sha(guest + kernel[:-1]), '60fda7794bb16cf3b1398062816bdee059f82345bd868d7455c562883e411080')
        raw = guest + kernel + b'\r\n'
        self.assertEqual(v.sha(raw), '3d37b93357528c7a267cd1dde037d0c8f3de5806cd77c1db3002cc0a3958a7c1')
        return guest, kernel, raw

    def pinmem_queued_trace_fixture(self):
        """Only the queued/kernel window is native; its surrounding trace is HOST_TEST."""
        guest, kernel, raw = self.pinmem_queued_boundary_fixture()
        key, caller, tid = (0, 2, 1, 0x90590818), 0x81cf61c4, 383
        query = self.old.frame_bytes(48, 0, 2, key[:3] + (0,), caller, b'\xa7\x19\0\x5a')
        rows = [record('PIN_QUERY', tid=tid, destination=hex(key[3]), source=hex(caller), bytes=48, raw=query.hex()),
            record('FULL_PINMEM_REQUEST', tid=tid, destination=hex(key[3]), source=hex(caller),
                   reply_destination=hex(caller), bytes=48, raw=query.hex())]
        prefix = b''.join(row['raw'].encode() + b'\r\n' for row in rows)
        rows = [record('FULL_PINMEM_COMMIT', tid=tid, slot=4, type=0, dir=2, index=1,
                       pin_state=1, owner=hex(key[3]), status=0, queries=11, reply='0x7fb3dc9e80', lease=11,
                       request_free_rc=0, connect_performed=0, pixels_consumed=0, camera_startup_verified=0),
            record('FULL_PINMEM_NATIVE_REPLY_FREE', tid=tid, sender=tid, waiter=1, destination=hex(caller),
                   expected=hex(caller), reply='0x7fb3dc9e80', lease=11, bytes=56, rc=0)]
        return prefix + raw + b''.join(row['raw'].encode() + b'\r\n' for row in rows)

    def pinmem_queued_content_join(self, raw):
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        content = self.graph.verify_get(log, (0, 2, 1, 0x90590818), ('259', '383'), 0x81cf61c4, 0, 100)
        v.bind_repairs(content, repairs)
        return parsed, repairs, content

    def test_pinmem_queued_complete_source_formatter_and_native_window_identity(self):
        source = v.read(v.RUNTIME / 'device-models/pin-registry-core.c').decode()
        self.assertIn('"tid=%ld source=%#x destination=%#x reply=%p lease=%llu bytes=56 raw=%s",\n'
                      '             syscall(SYS_gettid),owner->source,dst,reply,serial,raw);event(owner,io,"REPLY_QUEUED ",line);', source)
        self.assertIn('io->set_source(reply,owner->source);unsigned long long serial=++state->next_lease;', source)
        self.assertIn('state->queued++;hex(raw,out,56);', source)
        self.assertIn('rc=io->send(dst,reply);', source)
        self.assertIn('"FULL_%s_%s",owner->name,kind', source)
        owner = v.read(v.RUNTIME / 'device-models/pinmem-device.c').decode()
        self.assertIn('.source=FULL_PINMEM_CP,.count=13,.name="PINMEM",.keys=keys', owner)
        keys = [tuple(map(int, values)) for values in re.findall(r'\{(\d+),(\d+),(\d+)\}', owner)]
        self.assertEqual(keys[4], (0, 2, 1))
        self.assertIn('#define FULL_PINMEM_CP 0x90590818u', v.read(v.RUNTIME / 'device-models/pinmem-device.h').decode())
        self.assertIn('"OBS %s%s\\n", prefix, name ? name : ""', v.read(v.RUNTIME / 'menu-observe.c').decode())
        guest, kernel, raw = self.pinmem_queued_boundary_fixture()
        self.assertIsNotNone(v.PINMEM_GET_REPLY_QUEUED.fullmatch(guest))
        prefix = b'boot\rprogress\nprevious\n'
        parsed, repairs = v.console_records(prefix + raw)
        self.assertEqual(parsed, prefix + guest + b'\r\n' + kernel)
        repair, = repairs
        self.assertEqual(repair['kind'], 'complete-PinMemGetReply-UIPC-boundary')
        self.assertEqual((repair['raw_lf_line'], repair['parsed_line'], repair['raw_record_start']), (3, 3, len(prefix)))
        self.assertEqual(bytes.fromhex(repair['raw_record_hex']), guest + kernel)
        self.assertEqual(repair['raw_record_sha256'], v.sha(guest + kernel))
        self.assertEqual(bytes.fromhex(repair['kernel_raw_hex']), kernel)
        self.assertEqual(repair['kernel_sha256'], v.sha(kernel))
        self.assertEqual((prefix + raw)[repair['raw_kernel_start']:repair['raw_kernel_end']], kernel)
        self.assertEqual((prefix + raw)[repair['raw_guest_ending_start']:repair['raw_guest_ending_end']], b'\r\n')
        self.assertEqual(repair['repaired_record'], guest.decode())
        self.assertEqual(repair['repaired_record_sha256'], v.sha(guest))
        self.assertEqual(repair['cause'], 'unknown')
        self.assertEqual((repair['removed_bytes'], repair['framing_bytes_inserted']), (0, 0))
        self.assertTrue(repair['guest_payload_unchanged'])
        self.assertFalse(repair['guest_bytes_invented'])
        self.assertNotIn('content_verifier_joined', repair)
        self.assertEqual(v.console_records(guest + b'\r\n'), (guest + b'\r\n', []))
        self.assertEqual(v.console_records(kernel), (kernel, []))

    def test_pinmem_queued_repairs_join_existing_typed_get_reply_and_retirement(self):
        guest, kernel, _ = self.pinmem_queued_boundary_fixture()
        original = self.pinmem_queued_trace_fixture()
        for warning in (b'',) + v.WARNINGS:
            with self.subTest(warning=warning):
                mixed = original.replace(b'lease=11 bytes=56 raw=', b'lease=11 bytes=56 ra' + warning + b'w=', 1)
                parsed, repairs, content = self.pinmem_queued_content_join(mixed)
                self.assertEqual(content['reply']['raw'].encode(), guest)
                self.assertEqual(content['key'], (0, 2, 1, 0x90590818))
                self.assertEqual(content['commit']['fields']['slot'], '4')
                self.assertEqual(content['lease'], '11')
                self.assertEqual(content['request']['fields']['bytes'], '48')
                self.assertEqual(content['actual_same_sender_free']['fields']['sender'], '383')
                self.assertEqual(content['actual_same_sender_free']['fields']['rc'], '0')
                self.assertTrue(all(r['content_verifier_joined'] for r in repairs))
                self.assertIn(guest + b'\r\n' + kernel, parsed)
                self.assertNotIn('graph_verified', content)
                self.assertNotIn('capture_verified', content)
        parsed, repairs = v.console_records(original)
        row = self.graph.Log(parsed).rows('FULL_PINMEM_REPLY_QUEUED')[0]
        for proof in ({}, {'other': {**row, 'line': row['line'] + 1}},
                      {'other': {**row, 'raw': row['raw'].replace('lease=11', 'lease=12')}}):
            with self.subTest(proof=proof), self.assertRaises(v.UnjoinedRepairs):
                v.bind_repairs(proof, copy.deepcopy(repairs))
        # Merely parsing the queue creates no consumed Get object for bind_repairs.
        self.assertNotIn('content_verifier_joined', repairs[0])

    def test_pinmem_queued_refuses_unknown_nearby_truncated_and_noncanonical_framing(self):
        guest, kernel, raw = self.pinmem_queued_boundary_fixture()
        producer_changes = (
            (b'FULL_PINMEM_REPLY_QUEUED', b'FULL_PINMEM_REPLY_QUEUED_EXTRA'),
            (b'source=0x90590818', b'source=0x90590819'), (b'destination=0x81cf61c4', b'destination=0x80000000'),
            (b'destination=0x81cf61c4', b'destination=0x91cf61c4'), (b'destination=0x81cf61c4', b'destination=0x081cf61c4'),
            (b'tid=383 ', b''), (b'tid=383', b'tid=383 tid=383'), (b'tid=383', b'tid=0383'),
            (b'tid=383', b'tid=2147483648'), (b'lease=11', b'lease=0'), (b'lease=11', b'lease=011'),
            (b'lease=11', b'lease=18446744073709551616'), (b'reply=0x7fb3dc9e80', b'reply=0x07fb3dc9e80'),
            (b'reply=0x7fb3dc9e80', b'reply=0x10000000000000000'), (b'bytes=56', b'bytes=55'),
            (b'raw=00000000', b'raw=0000000'), (b'a0a0a0a0', b'A0a0a0a0'),
            (guest[-16:], guest[-16:] + b' extra=1'), (guest[-16:], guest[-16:] + b'junk'))
        for old, new in producer_changes:
            changed = raw.replace(old, new)
            with self.subTest(producer=old), self.assertRaises(ValueError):
                v.console_records(changed)
        for changed in (raw.replace(b'ret = -1022', b'ret = -1021'), raw.replace(b'Line 100:', b'Line 101:'),
                        raw.replace(b'[ 5541.379070]', b'[05541.379070]'), raw.replace(kernel, kernel + kernel),
                        raw.replace(kernel, kernel[:-2] + b' junk\r\n'), raw.replace(kernel, kernel[:-2] + b'\n'),
                        raw.replace(kernel, b'UNKNOWN_WARNING\r\n'), guest[:-1] + kernel + b'\r\n',
                        guest[:-1] + kernel + guest[-1:] + b'\r\n', raw[:-2] + b'junk\r\n', raw[:-2] + b'\n'):
            with self.subTest(raw=changed), self.assertRaises(ValueError):
                v.console_records(changed)
        with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
            v.console_records(raw[:-2])
        with self.assertRaisesRegex(ValueError, 'budget'):
            v.console_records(guest + v.WARNINGS[0] * 9 + kernel + b'\r\n')

    def test_pinmem_queued_content_refuses_wrong_owner_body_failed_free_and_borrowed_lease(self):
        parsed, repairs = v.console_records(self.pinmem_queued_trace_fixture())
        mutations = (
            ('PIN_QUERY', 'source', '0x81cf61c5'), ('PIN_QUERY', 'tid', '384'),
            ('FULL_PINMEM_REQUEST', 'destination', '0x90590819'), ('FULL_PINMEM_REQUEST', 'reply_destination', '0x81cf61c5'),
            ('FULL_PINMEM_REPLY_QUEUED', 'source', '0x90590819'), ('FULL_PINMEM_REPLY_QUEUED', 'destination', '0x81cf61c5'),
            ('FULL_PINMEM_REPLY_QUEUED', 'reply', '0x7fb3dc9e81'), ('FULL_PINMEM_REPLY_QUEUED', 'lease', '12'),
            ('FULL_PINMEM_COMMIT', 'slot', '5'), ('FULL_PINMEM_COMMIT', 'pin_state', '0'),
            ('FULL_PINMEM_COMMIT', 'owner', '0x90590819'), ('FULL_PINMEM_COMMIT', 'request_free_rc', '-1'),
            ('FULL_PINMEM_NATIVE_REPLY_FREE', 'tid', '384'), ('FULL_PINMEM_NATIVE_REPLY_FREE', 'sender', '384'),
            ('FULL_PINMEM_NATIVE_REPLY_FREE', 'waiter', '0'), ('FULL_PINMEM_NATIVE_REPLY_FREE', 'expected', '0x81cf61c5'),
            ('FULL_PINMEM_NATIVE_REPLY_FREE', 'reply', '0x7fb3dc9e81'), ('FULL_PINMEM_NATIVE_REPLY_FREE', 'lease', '12'),
            ('FULL_PINMEM_NATIVE_REPLY_FREE', 'bytes', '55'), ('FULL_PINMEM_NATIVE_REPLY_FREE', 'rc', '-1'))
        for tag, key, value in mutations:
            log = self.graph.Log(parsed)
            log.one(tag)['fields'][key] = value
            with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                self.graph.verify_get(log, (0, 2, 1, 0x90590818), ('259', '383'), 0x81cf61c4, 0, 100)
        for offset in (0, 4, 8, 20, 26, 32, 44, 48, 52):
            log = self.graph.Log(parsed)
            row = log.one('FULL_PINMEM_REPLY_QUEUED')
            wire = bytearray.fromhex(row['fields']['raw']); wire[offset] ^= 1
            row['fields']['raw'] = wire.hex()
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.graph.verify_get(log, (0, 2, 1, 0x90590818), ('259', '383'), 0x81cf61c4, 0, 100)
        for tag in ('PIN_QUERY', 'FULL_PINMEM_REQUEST', 'FULL_PINMEM_REPLY_QUEUED',
                    'FULL_PINMEM_COMMIT', 'FULL_PINMEM_NATIVE_REPLY_FREE'):
            for duplicate in (False, True):
                log = self.graph.Log(parsed)
                row = log.one(tag)
                log.records.append(copy.deepcopy(row)) if duplicate else log.records.remove(row)
                with self.subTest(tag=tag, duplicate=duplicate), self.assertRaises(ValueError):
                    self.graph.verify_get(log, (0, 2, 1, 0x90590818), ('259', '383'), 0x81cf61c4, 0, 100)
        self.assertNotIn('content_verifier_joined', repairs[0])

    def registry_free_boundary_fixture(self, owner=0x909a015a):
        key = (5, 1, 0, owner) if owner == 0x909a015a else (0, 2, 1, owner)
        caller, tid, p, lease = 0x81cf619b, 723, '0x7fae0c39c0', 4
        family = self.graph.OWNERS[owner][0]
        query = self.old.frame_bytes(48, 0, 2, key[:3] + (0,), caller, b'\xa7\x19\0\x5a')
        reply = self.old.frame_bytes(56, 0x8000, 2, key[:3] + (1, owner, 0))
        rows = [record('PIN_QUERY', tid=tid, destination=hex(owner), source=hex(caller), bytes=48, raw=query.hex()),
            record('FULL_' + family + '_REQUEST', tid=tid, destination=hex(owner), source=hex(caller),
                   reply_destination=hex(caller), bytes=48, raw=query.hex()),
            record('FULL_' + family + '_REPLY_QUEUED', tid=tid, source=hex(owner), destination=hex(caller),
                   reply=p, lease=lease, bytes=56, raw=reply.hex()),
            record('FULL_' + family + '_COMMIT', tid=tid, slot=self.graph.SLOTS[key], type=key[0], dir=key[1],
                   index=key[2], pin_state=1, owner=hex(owner), status=0, queries=4, reply=p, lease=lease,
                   request_free_rc=0, connect_performed=0, pixels_consumed=0, camera_startup_verified=0)]
        prefix = b''.join(r['raw'].encode() + b'\r\n' for r in rows)
        guest = record('FULL_' + family + '_NATIVE_REPLY_FREE', tid=tid, sender=tid, waiter=1,
                       destination=hex(caller), expected=hex(caller), reply=p, lease=lease, bytes=56, rc=0)['raw'].encode()
        kernel = b'[ 1535.015269] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        return key, guest, kernel, prefix + guest + v.WARNINGS[0] + kernel + b'\r\n'

    def test_registry_native_free_printf_joins_actual_same_sender_get(self):
        source = v.read(v.RUNTIME / 'device-models/pin-registry-core.c').decode()
        self.assertIn('"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu bytes=56 rc=%d"', source)
        self.assertIn('snprintf(tag,sizeof tag,"FULL_%s_%s",owner->name,*result?"FAULT ":"NATIVE_REPLY_FREE ")', source)
        for owner in (0x909a015a, 0x90590818):
            key, guest, kernel, raw = self.registry_free_boundary_fixture(owner)
            parsed, repairs = v.console_records(raw)
            proof = self.graph.verify_get(self.graph.Log(parsed), key, ('701', '723'), 0x81cf619b, 0, 100)
            v.bind_repairs(proof, repairs)
            with self.subTest(owner=owner):
                self.assertEqual(proof['actual_same_sender_free']['raw'].encode(), guest)
                self.assertTrue(parsed.endswith(guest + b'\r\n' + kernel))
                self.assertEqual(len(repairs), 2)
                self.assertTrue(all(r['content_verifier_joined'] for r in repairs))
                self.assertEqual(repairs[-1]['kind'], 'complete-RegistryGetFree-UIPC-boundary')
                self.assertEqual(raw[repairs[-1]['raw_kernel_start']:repairs[-1]['raw_kernel_end']], kernel)
                self.assertEqual(repairs[-1]['framing_bytes_inserted'], 0)
            for field, value in (('tid', '724'), ('sender', '724'), ('waiter', '0'), ('destination', '0x81cf619c'),
                                 ('expected', '0x81cf619c'), ('reply', '0x7fae0c39c1'), ('lease', '5'), ('rc', '-1')):
                log = self.graph.Log(parsed)
                log.rows('FULL_' + self.graph.OWNERS[owner][0] + '_NATIVE_REPLY_FREE')[0]['fields'][field] = value
                with self.subTest(owner=owner, field=field), self.assertRaises(ValueError):
                    self.graph.verify_get(log, key, ('701', '723'), 0x81cf619b, 0, 100)
            with self.assertRaisesRegex(ValueError, 'content-verifier join'):
                v.bind_repairs({}, repairs)

    def test_registry_free_complete_grammar_refuses_unknown_truncated_or_oversized_fields(self):
        _, guest, kernel, raw = self.registry_free_boundary_fixture()
        for changed in (raw.replace(b'sender=723', b'sender=2147483648'), raw.replace(b'waiter=1', b'waiter=2'),
                        raw.replace(b'lease=4 bytes=56 rc=0' + v.WARNINGS[0], b'lease=18446744073709551616 bytes=56 rc=0'),
                        raw.replace(b'expected=0x81cf619b ', b''), raw.replace(b'bytes=56 rc=0', b'bytes=55 rc=0'),
                        raw.replace(b'rc=0' + v.WARNINGS[0], b'rc=-1' + v.WARNINGS[0]),
                        raw.replace(b'rc=0' + v.WARNINGS[0], b'rc=0 extra=1' + v.WARNINGS[0]),
                        raw.replace(guest, guest[:-1]), raw.replace(b'FULL_HDMIPIN_NATIVE_REPLY_FREE', b'FULL_HDMI_NATIVE_REPLY_FREE'),
                        raw.replace(b'Line 100:', b'Line 101:'), raw[:-2] + b'bad=1\r\n', raw[:-2] + b'\n'):
            with self.subTest(raw=changed), self.assertRaises(ValueError):
                v.console_records(changed)
        with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
            v.console_records(raw[:-2])
        self.assertEqual(v.console_records(guest + b'\r\n'), (guest + b'\r\n', []))

    def scalar_tts_boundary_fixture(self):
        # Verbatim LF17754-17755, run-ynlb4m9v console SHA256 59d0ce96...eeaaec.
        table = (b'1a00000005040000000008000000000000802afe0400000000840000000008000000001e0000000000b033477e000000000008001d00000000b033477e00000000000800000000001b000000060400000000080000000000008032fe0400000001840000000008000000081e0000000000b02b477e000000000008001e00000000b02b477e0000000000080000000000')
        self.assertEqual(len(table), 288)
        guest = (b'OBS FULL_SCALAR_CONNECT_RESOURCES_TTS_TABLE pid=260 tid=384 appfw_base=0x7f61cf4000 '
                 b'table_va=0x5f66b08 address=0x7f67c5ab08 bytes=144 reads=144/144 unchanged=1 '
                 b'atomic_snapshot=0 raw_before=' + table + b' raw_after=' + table + b' ownership_verified=0')
        kernel = b'[ 5306.152459] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        return guest, kernel, guest + kernel + b'\r\n'

    def test_osd_tts_unknown_word_prefix_is_preserved_and_unclaimed(self):
        guest, _, _ = self.scalar_tts_boundary_fixture()
        guest = guest.replace(b'FULL_SCALAR_CONNECT_RESOURCES_TTS_TABLE',
                              b'FULL_PINMEM_OSD_CONNECT_RESOURCES_TTS_TABLE') + b'\r\n'
        tag = 'FULL_PINMEM_OSD_CONNECT_RESOURCES_TTS_TABLE'
        self.assertEqual(self.graph.Log(guest).one(tag)['fields']['reads'], '144/144')
        for prefix in (b'0', b'00', b'x', b'9', b'_', b'unknown'):
            raw = prefix + guest
            with self.subTest(prefix=prefix):
                parsed, repairs = v.console_records(raw)
                self.assertEqual(parsed, raw)
                self.assertEqual(repairs, [])
                self.assertEqual(self.graph.Log(parsed).rows(tag), [])
                with self.assertRaises(ValueError):
                    self.graph.Log(parsed).one(tag)
        path = v.RUNTIME / 'menu-runs/run-zd4qa2vi/console.log'
        if path.exists():
            raw = path.read_bytes()
            original = raw[2078483:2079287]
            self.assertEqual(v.sha(original), '30e7d86b1d3046a9fb8c1c93a842f47dbbda95fdf59a060ab793ea279fc2021e')
            self.assertTrue(original.startswith(b'0OBS '))
            self.assertEqual(v.console_records(original), (original, []))
            self.assertEqual(self.graph.Log(original).rows(tag), [])

    def test_scalar_tts_exact_actual_boundary_retains_raw_bytes_sha_and_unknown_cause(self):
        guest, kernel, raw = self.scalar_tts_boundary_fixture()
        parsed, repairs = v.console_records(raw)
        self.assertEqual(parsed, guest + b'\r\n' + kernel)
        self.assertEqual(len(repairs), 1)
        repair = repairs[0]
        self.assertEqual(repair['kind'], 'complete-ScalarTtsTable-UIPC-boundary')
        self.assertEqual(repair['cause'], 'unknown')
        self.assertEqual(repair['raw_lf_line'], 1)
        self.assertEqual(bytes.fromhex(repair['raw_record_hex']), guest + kernel)
        self.assertEqual(repair['raw_record_sha256'], v.sha(guest + kernel))
        self.assertEqual(bytes.fromhex(repair['kernel_raw_hex']), kernel)
        self.assertEqual(repair['kernel_sha256'], v.sha(kernel))
        self.assertEqual(raw[repair['raw_kernel_start']:repair['raw_kernel_end']], kernel)
        self.assertEqual(raw[repair['raw_guest_ending_start']:repair['raw_guest_ending_end']], b'\r\n')
        self.assertEqual((repair['removed_bytes'], repair['framing_bytes_inserted']), (0, 0))
        self.assertFalse(repair['guest_bytes_invented'])
        self.assertTrue(repair['guest_payload_unchanged'])
        row = self.graph.Log(parsed).records[0]
        self.assertEqual(row['raw'].encode(), guest)
        self.assertEqual(row['fields']['ownership_verified'], '0')
        self.assertEqual(row['fields']['raw_before'], row['fields']['raw_after'])
        self.assertNotIn('UDIF', json.dumps(row['fields']))
        self.assertNotIn('graph_verified', repair)
        for proof in ({}, {'other': {**row, 'line': 2}}, {'other': {**row, 'raw': row['raw'] + ' junk'}}):
            with self.subTest(proof=proof), self.assertRaisesRegex(ValueError, 'content-verifier join'):
                v.bind_repairs(proof, copy.deepcopy(repairs))
        self.assertEqual(v.console_records(guest + b'\r\n'), (guest + b'\r\n', []))
        self.assertEqual(v.console_records(kernel), (kernel, []))

    def test_scalar_tts_source_printf_bounds_and_dynamic_identity_are_exact(self):
        source = v.read(v.RUNTIME / 'menu-observe.c').decode()
        self.assertIn('"pid=%d tid=%ld appfw_base=%#lx table_va=0x5f66b08 address=%#lx bytes=144 reads=%ld/%ld '
                      'unchanged=%u atomic_snapshot=0 raw_before=%s raw_after=%s ownership_verified=0"', source)
        self.assertIn('unsigned long speech_address=appfw_base+0x5f66b08UL;', source)
        self.assertIn('appfw_base>=0x10000UL && appfw_base<0x7ff0000000UL', source)
        self.assertIn('!memcmp(resources.speech_before,resources.speech_after,sizeof resources.speech_before)', source)
        self.assertIn('snprintf(speech_hex_before+2*i,3,"%02x",resources.speech_before[i])', source)
        guest, kernel, raw = self.scalar_tts_boundary_fixture()
        self.assertIsNotNone(v.SCALAR_TTS_TABLE.fullmatch(guest))
        for pid, tid, base, stamp in ((1, 2147483647, 0x10000, b'[    0.000001]'),
                                      (2147483647, 1, 0x7fefffffff, b'[18446744073.709551]')):
            changed = raw.replace(b'pid=260', f'pid={pid}'.encode()).replace(b'tid=384', f'tid={tid}'.encode())
            changed = changed.replace(b'0x7f61cf4000', hex(base).encode())
            changed = changed.replace(b'0x7f67c5ab08', hex(base + 0x5f66b08).encode())
            changed = changed.replace(b'[ 5306.152459]', stamp)
            with self.subTest(pid=pid, base=base):
                parsed, repairs = v.console_records(changed)
                self.assertEqual(v.parse_record(parsed.split(b'\n')[0] + b'\n')[1]['pid'], str(pid))
                self.assertEqual(repairs[0]['cause'], 'unknown')
                self.assertEqual(bytes.fromhex(repairs[0]['raw_record_hex']), changed[:-2])

    def test_scalar_tts_original_lf_offsets_survive_cr_and_existing_vvfat_framing(self):
        guest, kernel, raw = self.scalar_tts_boundary_fixture()
        prefix = b'boot\rprogress\nprevious\n'
        for warning in (b'', v.WARNINGS[0]):
            mixed = prefix + raw.replace(b'raw_before=', b'raw_be' + warning + b'fore=', 1)
            parsed, repairs = v.console_records(mixed)
            self.assertEqual(parsed, prefix + guest + b'\r\n' + kernel)
            repair = repairs[-1]
            self.assertEqual(repair['raw_lf_line'], 3)
            self.assertEqual(repair['parsed_line'], 3)
            self.assertEqual(repair['raw_record_start'], len(prefix))
            self.assertEqual(bytes.fromhex(repair['raw_record_hex']), mixed[len(prefix):-2])
            self.assertEqual(mixed[repair['raw_kernel_start']:repair['raw_kernel_end']], kernel)
            self.assertEqual(repair['repaired_record'].encode(), guest)

    def test_scalar_tts_boundary_refuses_incomplete_unknown_or_ambiguous_bytes(self):
        guest, kernel, raw = self.scalar_tts_boundary_fixture()
        mutations = (
            ('other-tag', raw.replace(b'FULL_SCALAR_CONNECT_RESOURCES_TTS_TABLE', b'FULL_SCALAR_CONNECT_RESOURCES_TTS_OTHER')),
            ('other-ret', raw.replace(b'ret = -1022', b'ret = -1021')),
            ('unknown-warning', raw.replace(kernel, b'UNKNOWN_WARNING\r\n')),
            ('missing-pid', raw.replace(b'pid=260 ', b'')),
            ('missing-address', raw.replace(b'address=0x7f67c5ab08 ', b'')),
            ('missing-tail', raw.replace(b' ownership_verified=0', b'')),
            ('short-before', raw.replace(b'raw_before=1a', b'raw_before=1')),
            ('short-after', raw.replace(b'raw_after=1a', b'raw_after=1')),
            ('unequal-raw', raw.replace(b'raw_after=1a', b'raw_after=1b')),
            ('uppercase-raw', raw.replace(b'raw_before=1a', b'raw_before=1A')),
            ('duplicate-pid', raw.replace(b'pid=260', b'pid=260 pid=260')),
            ('duplicate-tail', raw.replace(b'ownership_verified=0', b'ownership_verified=0 ownership_verified=0')),
            ('ownership', raw.replace(b'ownership_verified=0', b'ownership_verified=1')),
            ('atomic', raw.replace(b'atomic_snapshot=0', b'atomic_snapshot=1')),
            ('changed', raw.replace(b'unchanged=1', b'unchanged=0')),
            ('extent', raw.replace(b'bytes=144', b'bytes=143')),
            ('short-read', raw.replace(b'reads=144/144', b'reads=143/144')),
            ('bad-read', raw.replace(b'reads=144/144', b'reads=144/145')),
            ('pid-overflow', raw.replace(b'pid=260', b'pid=2147483648')),
            ('tid-overflow', raw.replace(b'tid=384', b'tid=2147483648')),
            ('noncanonical-pid', raw.replace(b'pid=260', b'pid=0260')),
            ('signed-tid', raw.replace(b'tid=384', b'tid=-384')),
            ('low-base', raw.replace(b'0x7f61cf4000', b'0xffff')),
            ('high-base', raw.replace(b'0x7f61cf4000', b'0x7ff0000000')),
            ('base-overflow', raw.replace(b'0x7f61cf4000', b'0x10000000000000000')),
            ('noncanonical-base', raw.replace(b'0x7f61cf4000', b'0x07f61cf4000')),
            ('wrong-table', raw.replace(b'table_va=0x5f66b08', b'table_va=0x5f66b09')),
            ('wrong-address', raw.replace(b'address=0x7f67c5ab08', b'address=0x7f67c5ab09')),
            ('unknown-key', raw.replace(b'ownership_verified=0', b'ownership_verified=0 extra=1')),
            ('body-junk', raw.replace(guest, guest + b'junk')),
            ('body-spaced-junk', raw.replace(guest, guest + b' junk')),
            ('kernel-junk', raw.replace(kernel, kernel[:-2] + b' junk\r\n')),
            ('unknown-line', raw.replace(b'Line 100:', b'Line 101:')),
            ('unknown-device', raw.replace(b'uipc:', b'uipx:')),
            ('bad-timestamp', raw.replace(b'[ 5306.152459]', b'[05306.152459]')),
            ('overflow-timestamp', raw.replace(b'[ 5306.152459]', b'[18446744073.709552]')),
            ('duplicate-kernel', raw.replace(kernel, kernel + kernel)),
            ('interrupted-body', guest[:-1] + kernel + guest[-1:] + b'\r\n'),
            ('kernel-LF-only', raw.replace(kernel, kernel[:-2] + b'\n')),
            ('ending-LF-only', raw[:-2] + b'\n'),
            ('ending-junk', raw[:-2] + b'junk\r\n'),
            ('standalone-junk', guest + b'junk\r\n'),
            ('standalone-spaced-junk', guest + b' junk\r\n'),
        )
        for label, changed in mutations:
            with self.subTest(case=label), self.assertRaises(ValueError):
                v.console_records(changed)
            if label in ('pid-overflow', 'tid-overflow', 'noncanonical-pid', 'signed-tid',
                         'low-base', 'high-base', 'base-overflow', 'noncanonical-base', 'wrong-address'):
                with self.subTest(standalone=label), self.assertRaises(ValueError):
                    v.console_records(changed.replace(kernel, b''))
        with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
            v.console_records(guest + kernel)

    def hdmi_free_boundary_fixture(self):
        # Verbatim xmqjhwk4 LF2291-2292; observer-owned fields, no private firmware/config bytes.
        guest = (b'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=383 sender=383 waiter=1 destination=0x81cf61c6 '
                 b'expected=0x81cf61c6 reply=0x7fab30f400 lease=4 command=0x117 bytes=12 status=0 rc=0')
        kernel = b'[  358.762224] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
        raw = guest + kernel + b'\r\n'
        self.assertEqual(v.sha(guest + kernel), 'aad6be5f96feb72515be8d8e18d5bbcfd4d4a0000ced8cbeaca3455c4e6d60d3')
        self.assertEqual(v.sha(raw), '87ebddb88f9454f8bb1c88dcd139c803d40134b604bf7895242689ab5464eb55')
        return guest, kernel, raw

    def hdmi_free_trace_fixture(self, command=0x117):
        """HOST_TEST request/queue/commit context; only the default free window is verbatim."""
        guest, kernel, _ = self.hdmi_free_boundary_fixture()
        size = {0x10a: 12, 0x20a: 8, 0x101: 16, 0x201: 8, 0x117: 12}[command]
        reply_size = {0x20a: 16, 0x201: 20}.get(command, 12)
        status = int(command == 0x10a)
        body = {0x10a: b'\x07\0\0\0', 0x20a: b'', 0x101: bytes.fromhex('0000000006050000'),
                0x201: b'', 0x117: b'\x01\0\x01\0'}[command]
        wire = struct.pack('<4H', 0x2500, command, size, 1) + body
        returned = {0x20a: b'\x04\0\0\0', 0x201: bytes.fromhex('0000000006050000')}.get(command, b'')
        reply = struct.pack('<4HI', 0x2500, command | 0x8000, reply_size, 1, status) + returned
        guest = guest.replace(b'command=0x117 bytes=12 status=0',
                              f'command={hex(command)} bytes={reply_size} status={status}'.encode())
        common = dict(tid=383, command=hex(command), reply='0x7fab30f400', lease=4, status=status)
        effects = {
            0x10a: dict(requested=7, known_before=0, readback_before=0, known_after=1, readback=0, applied=1, queries=0),
            0x20a: dict(requested=0, known_before=1, readback_before=4, known_after=1, readback=4, applied=1, queries=1),
            0x101: dict(resolution=body[:6].hex(), resolution_known=1, applied=1, queries=0),
            0x201: dict(resolution=returned[:6].hex(), resolution_known=1, applied=1, queries=1),
            0x117: dict(selector=1, rate=0, dp_selector=1, dp_rate=0, dp_applied=0, matched=1,
                        readback=0, known_mask='0x3', rates='0000000000', requests=2),
        }[command]
        rows = [record('FULL_HDMI_REQUEST', tid=383, source='0x81cf61c6', destination='0x909a015a',
                       command=hex(command), bytes=size, raw=wire.hex()),
                record('FULL_HDMI_REPLY_QUEUED', **common, source='0x909a015a', destination='0x81cf61c6',
                       bytes=reply_size, raw=reply.hex()),
                record('FULL_HDMI_COMMIT', **common, **effects, request_free_rc=0,
                       hdmi_output_verified=0, camera_startup_verified=0)]
        return b''.join(row['raw'].encode() + b'\r\n' for row in rows) + guest + kernel + b'\r\n'

    def hdmi_free_content_join(self, raw):
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        proof = {'identity': ('259', '383'), 'edges': [{'REQUEST': {'line': len(log.lines) + 1}}]}
        proof['repaired_HDMI_reply_free_joins'] = v.check_repaired_hdmi_frees(log, repairs, proof, self.graph)
        v.bind_repairs(proof, repairs)
        return parsed, repairs, proof

    def test_hdmi_free_exact_actual_bytes_ending_offsets_and_unknown_cause(self):
        guest, kernel, raw = self.hdmi_free_boundary_fixture()
        prefix = b'boot\rprogress\nprevious\n'
        parsed, repairs = v.console_records(prefix + raw)
        self.assertEqual(parsed, prefix + guest + b'\r\n' + kernel)
        self.assertEqual(len(repairs), 1)
        repair = repairs[0]
        self.assertEqual(repair['kind'], 'complete-HdmiNativeFree-UIPC-boundary')
        self.assertEqual((repair['raw_lf_line'], repair['parsed_line']), (3, 3))
        self.assertEqual(repair['cause'], 'unknown')
        self.assertEqual(repair['raw_record_start'], len(prefix))
        self.assertEqual(bytes.fromhex(repair['raw_record_hex']), guest + kernel)
        self.assertEqual(repair['raw_record_sha256'], v.sha(guest + kernel))
        self.assertEqual(bytes.fromhex(repair['kernel_raw_hex']), kernel)
        self.assertEqual(repair['kernel_sha256'], '2edf30c61cdf11b1fbb8b15ce8b6e5da7db19c884b95867557ef200e37475fec')
        for begin, end, expected in (('raw_kernel_start', 'raw_kernel_end', kernel),
                                     ('raw_guest_ending_start', 'raw_guest_ending_end', b'\r\n')):
            self.assertEqual((prefix + raw)[repair[begin]:repair[end]], expected)
        self.assertEqual((repair['removed_bytes'], repair['framing_bytes_inserted']), (0, 0))
        self.assertTrue(repair['guest_payload_unchanged'])
        self.assertFalse(repair['guest_bytes_invented'])
        self.assertNotIn('content_verifier_joined', repair)
        self.assertEqual(v.console_records(guest + b'\r\n'), (guest + b'\r\n', []))
        self.assertEqual(v.console_records(kernel), (kernel, []))
        row = self.graph.Log(parsed).rows('FULL_HDMI_NATIVE_REPLY_FREE')[0]
        for proof in ({}, {'other': {**row, 'line': row['line'] + 1}},
                      {'other': {**row, 'raw': row['raw'] + ' junk'}}):
            with self.subTest(proof=proof), self.assertRaisesRegex(ValueError, 'content-verifier join'):
                v.bind_repairs(proof, copy.deepcopy(repairs))

    def test_hdmi_free_complete_source_grammar_and_all_five_configuration_joins(self):
        source = v.read(v.RUNTIME / 'device-models/hdmi-device.c').decode()
        for token in (
            '"tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu command=%#x bytes=%u status=%u rc=%d"',
            'record(*result?"FULL_HDMI_FAULT ":"FULL_HDMI_NATIVE_REPLY_FREE ",line);',
            'int resolution=command==0x0101 || command==0x0201;', 'int rate=command==0x0117;',
            'command!=0x010a && command!=0x020a',
            'reply_bytes=command==0x020a?16:command==0x0201?20:12;',
            'unsigned int status=command==0x010a?1:0,readback=state.definition;',
            'found.destination==destination?release(destination,reply):-1021',
            'tid,found.sender,tid==found.sender,destination,found.destination,reply,found.serial'):
            self.assertIn(token, source)
        for command in (0x10a, 0x20a, 0x101, 0x201, 0x117):
            with self.subTest(command=hex(command)):
                raw = self.hdmi_free_trace_fixture(command)
                parsed, repairs, proof = self.hdmi_free_content_join(raw)
                self.assertEqual(len(repairs), 1)
                self.assertTrue(repairs[0]['content_verifier_joined'])
                joined = proof['repaired_HDMI_reply_free_joins'][0]
                self.assertEqual(joined['actual_same_sender_free']['raw'], repairs[0]['repaired_record'])
                self.assertEqual(joined['original_request']['fields']['command'], hex(command))
                self.assertTrue(joined['configuration_only'])
                self.assertFalse(joined['hdmi_output_verified'])
                self.assertFalse(joined['capture_verified'])
                self.assertNotIn('graph_verified', joined)
                self.assertIn(b'\r\n[  358.762224]', parsed)

    def test_hdmi_free_dynamic_producer_bounds_and_vvfat_repair_offsets(self):
        guest, kernel, raw = self.hdmi_free_boundary_fixture()
        for tid, sender, waiter, stamp in ((1, 2147483647, 0, b'[    0.000000]'),
                                           (2147483647, 2147483647, 1, b'[18446744073.709551]')):
            changed = raw.replace(b'tid=383', f'tid={tid}'.encode()).replace(b'sender=383', f'sender={sender}'.encode())
            changed = changed.replace(b'waiter=1', f'waiter={waiter}'.encode()).replace(b'[  358.762224]', stamp)
            changed = changed.replace(b'lease=4 ', b'lease=18446744073709551615 ')
            changed = changed.replace(b'reply=0x7fab30f400', b'reply=0xffffffffffffffff')
            with self.subTest(tid=tid, waiter=waiter):
                _, repairs = v.console_records(changed)
                self.assertEqual(bytes.fromhex(repairs[0]['raw_record_hex']), changed[:-2])
        original = self.hdmi_free_trace_fixture()
        for warning in v.WARNINGS:
            mixed = original.replace(b'sender=383', b'send' + warning + b'er=383', 1)
            mixed = mixed.replace(b'rc=0' + kernel, b'rc=0' + warning + kernel, 1)
            parsed, repairs, proof = self.hdmi_free_content_join(mixed)
            self.assertEqual(parsed, self.hdmi_free_content_join(original)[0])
            self.assertEqual(len(repairs), 3)
            self.assertEqual(len(proof['repaired_HDMI_reply_free_joins']), 3)
            boundary = repairs[-1]
            self.assertEqual(boundary['raw_lf_line'], 4)
            self.assertEqual(bytes.fromhex(boundary['raw_record_hex']), mixed[mixed.index(guest[:40]):-2])
            self.assertEqual(mixed[boundary['raw_kernel_start']:boundary['raw_kernel_end']], kernel)
            self.assertTrue(all(repair['content_verifier_joined'] for repair in repairs))
        allowed = original.replace(b'rc=0' + kernel, b'rc=0' + v.WARNINGS[0] * 8 + kernel, 1)
        self.assertEqual(len(self.hdmi_free_content_join(allowed)[1]), 9)
        excessive = original.replace(b'rc=0' + kernel, b'rc=0' + v.WARNINGS[0] * 9 + kernel, 1)
        with self.assertRaisesRegex(ValueError, 'budget'):
            v.console_records(excessive)
        with patch.object(v, 'MAX_LOG', len(raw) - 1), self.assertRaisesRegex(ValueError, 'read budget'):
            v.console_records(raw)

    def test_hdmi_free_rejects_unknown_truncated_duplicate_and_noncanonical_framing(self):
        guest, kernel, raw = self.hdmi_free_boundary_fixture()
        changes = (
            (b'FULL_HDMI_NATIVE_REPLY_FREE', b'FULL_HDMI_FAULT'), (b'command=0x117', b'command=0x118'),
            (b'command=0x117', b'command=0x0117'), (b'command=0x117', b'command=0x10a'),
            (b'bytes=12', b'bytes=16'), (b'status=0', b'status=1'), (b'rc=0', b'rc=-1'),
            (b'tid=383 ', b''), (b'expected=0x81cf61c6 ', b''), (b'tid=383', b'tid=383 tid=383'),
            (b'rc=0', b'rc=0 rc=0'), (b'rc=0', b'rc=0 extra=1'), (b'rc=0', b'rc=0junk'),
            (b'rc=0', b'rc=0 junk'), (b'tid=383', b'tid=0383'), (b'sender=383', b'sender=-383'),
            (b'tid=383', b'tid=2147483648'), (b'sender=383', b'sender=2147483648'),
            (b'waiter=1', b'waiter=0'), (b'waiter=1', b'waiter=2'), (b'sender=383', b'sender=384'),
            (b'expected=0x81cf61c6', b'expected=0x81cf61c7'), (b'0x81cf61c6', b'0x80000000'),
            (b'0x81cf61c6', b'0x91cf61c6'), (b'0x81cf61c6', b'0x081cf61c6'),
            (b'reply=0x7fab30f400', b'reply=0x07fab30f400'), (b'reply=0x7fab30f400', b'reply=0x7faB30f400'),
            (b'reply=0x7fab30f400', b'reply=0x10000000000000000'),
            (b'lease=4', b'lease=04'), (b'lease=4', b'lease=0'), (b'lease=4', b'lease=18446744073709551616'),
            (b'ret = -1022', b'ret = -1021'), (b'Line 100:', b'Line 101:'), (b'uipc:', b'uipx:'),
            (b'[  358.762224]', b'[00358.762224]'), (b'[  358.762224]', b'[18446744073.709552]'),
            (kernel, kernel[:-2] + b' junk\r\n'), (kernel, kernel[:-2] + b'\n'), (kernel, kernel + kernel),
        )
        mutations = [raw.replace(old, new) for old, new in changes]
        mutations += [guest[:-1] + kernel + b'\r\n', guest[:-1] + kernel + guest[-1:] + b'\r\n',
                      raw[:-2] + b'\n', raw[:-2] + b'junk\r\n', raw[:-2] + b'\r',
                      guest + b' padding=' + b'a' * 1024 + kernel + b'\r\n',
                      guest + b'UNKNOWN_WARNING\r\n\r\n']
        for changed in mutations:
            with self.subTest(raw=changed), self.assertRaises(ValueError):
                v.console_records(changed)
        with self.assertRaisesRegex(v.SourceMissing, 'original guest line ending'):
            v.console_records(raw[:-2])
        for command, wrong in ((0x10a, b'status=0'), (0x20a, b'bytes=12'), (0x201, b'bytes=16')):
            trace = self.hdmi_free_trace_fixture(command)
            tail = trace[trace.index(b'OBS FULL_HDMI_NATIVE_REPLY_FREE '):]
            token = b'status=1' if command == 0x10a else (b'bytes=16' if command == 0x20a else b'bytes=20')
            with self.subTest(command=command), self.assertRaises(ValueError):
                v.console_records(tail.replace(token, wrong))

    def test_hdmi_free_content_rejects_wrong_identity_wire_effects_and_borrowed_lifetimes(self):
        original = self.hdmi_free_trace_fixture()
        parsed, repairs = v.console_records(original)
        base = self.graph.Log(parsed)
        mutations = (
            ('REQUEST', 'source', '0x81cf61c7'), ('REQUEST', 'destination', '0x909a015b'),
            ('REQUEST', 'command', '0x101'), ('REQUEST', 'bytes', '11'), ('REQUEST', 'tid', '384'),
            ('REPLY_QUEUED', 'source', '0x909a015b'), ('REPLY_QUEUED', 'destination', '0x81cf61c7'),
            ('REPLY_QUEUED', 'reply', '0x7fab30f401'), ('REPLY_QUEUED', 'lease', '5'),
            ('REPLY_QUEUED', 'status', '1'), ('REPLY_QUEUED', 'bytes', '11'),
            ('COMMIT', 'request_free_rc', '-1'), ('COMMIT', 'tid', '384'), ('COMMIT', 'command', '0x101'),
            ('COMMIT', 'reply', '0x7fab30f401'), ('COMMIT', 'lease', '5'), ('COMMIT', 'selector', '2'),
            ('COMMIT', 'rate', '7'), ('COMMIT', 'dp_selector', '2'), ('COMMIT', 'dp_rate', '7'),
            ('COMMIT', 'dp_applied', '1'), ('COMMIT', 'matched', '0'), ('COMMIT', 'readback', '7'),
            ('COMMIT', 'known_mask', '0x1'), ('COMMIT', 'known_mask', '0x03'), ('COMMIT', 'known_mask', '0x23'),
            ('COMMIT', 'rates', '0001000000'), ('COMMIT', 'rates', '00000000'),
            ('COMMIT', 'hdmi_output_verified', '1'), ('COMMIT', 'camera_startup_verified', '1'),
            ('NATIVE_REPLY_FREE', 'tid', '384'), ('NATIVE_REPLY_FREE', 'sender', '384'),
            ('NATIVE_REPLY_FREE', 'waiter', '0'), ('NATIVE_REPLY_FREE', 'expected', '0x81cf61c7'),
            ('NATIVE_REPLY_FREE', 'destination', '0x81cf61c7'), ('NATIVE_REPLY_FREE', 'reply', '0x7fab30f401'),
            ('NATIVE_REPLY_FREE', 'lease', '5'), ('NATIVE_REPLY_FREE', 'rc', '-1'),
        )
        proof = {'identity': ('259', '383'), 'edges': [{'REQUEST': {'line': 100}}]}
        for tag, field, value in mutations:
            log = copy.deepcopy(base)
            log.one('FULL_HDMI_' + tag)['fields'][field] = value
            with self.subTest(tag=tag, field=field, value=value), self.assertRaises(ValueError):
                v.check_repaired_hdmi_frees(log, repairs, proof, self.graph)
        for tag, offsets in (('REQUEST', range(12)), ('REPLY_QUEUED', range(12))):
            for offset in offsets:
                log = copy.deepcopy(base)
                row = log.one('FULL_HDMI_' + tag)
                wire = bytearray.fromhex(row['fields']['raw']); wire[offset] ^= 1
                row['fields']['raw'] = wire.hex()
                with self.subTest(tag=tag, offset=offset), self.assertRaises(ValueError):
                    v.check_repaired_hdmi_frees(log, repairs, proof, self.graph)
        for tag in ('REQUEST', 'REPLY_QUEUED', 'COMMIT', 'NATIVE_REPLY_FREE'):
            row = base.one('FULL_HDMI_' + tag)['raw'].encode() + b'\r\n'
            for replacement in (b'', row + row):
                changed = parsed.replace(row, replacement, 1)
                log = self.graph.Log(changed)
                adjusted = copy.deepcopy(repairs)
                rows = log.rows('FULL_HDMI_NATIVE_REPLY_FREE')
                if rows:
                    adjusted[0]['parsed_line'] = rows[0]['line']
                with self.subTest(tag=tag, duplicate=bool(replacement)), self.assertRaises(ValueError):
                    v.check_repaired_hdmi_frees(log, adjusted, proof, self.graph)
        for changed in (dict(proof, identity=('259', '384')),
                        dict(proof, edges=[{'REQUEST': {'line': base.one('FULL_HDMI_NATIVE_REPLY_FREE')['line']}}])):
            with self.subTest(proof=changed), self.assertRaises(ValueError):
                v.check_repaired_hdmi_frees(base, repairs, changed, self.graph)
        altered = copy.deepcopy(repairs); altered[0]['parsed_line'] += 1
        with self.assertRaisesRegex(ValueError, 'exact parsed record'):
            v.check_repaired_hdmi_frees(base, altered, proof, self.graph)
        # Host-warning-only repair still needs a full transaction and bounded lease.
        guest, kernel, _ = self.hdmi_free_boundary_fixture()
        mixed = original.replace(guest + kernel + b'\r\n', guest.replace(b'sender=', b'send' + v.WARNINGS[0] + b'er=') + b'\r\n')
        self.assertEqual(len(self.hdmi_free_content_join(mixed)[1]), 1)
        with self.assertRaises(ValueError):
            self.hdmi_free_content_join(mixed.replace(b'lease=4', b'lease=18446744073709551616'))

    def test_hdmi_free_configuration_body_readbacks_remain_required(self):
        for command, tag, field, value in (
            (0x10a, 'COMMIT', 'readback', '7'), (0x10a, 'COMMIT', 'requested', '6'),
            (0x20a, 'COMMIT', 'readback_before', '3'), (0x20a, 'COMMIT', 'known_before', '0'),
            (0x20a, 'COMMIT', 'readback', '6'), (0x101, 'COMMIT', 'resolution', '000000000604'),
            (0x201, 'COMMIT', 'resolution_known', '0')):
            raw = self.hdmi_free_trace_fixture(command)
            parsed, repairs = v.console_records(raw)
            log = self.graph.Log(parsed)
            log.one('FULL_HDMI_' + tag)['fields'][field] = value
            proof = {'identity': ('259', '383'), 'edges': [{'REQUEST': {'line': 100}}]}
            with self.subTest(command=command, field=field), self.assertRaises(ValueError):
                v.check_repaired_hdmi_frees(log, repairs, proof, self.graph)
        for command, offsets in ((0x20a, (12, 13, 15)), (0x201, (12, 17, 18, 19))):
            parsed, repairs = v.console_records(self.hdmi_free_trace_fixture(command))
            for offset in offsets:
                log = self.graph.Log(parsed)
                row = log.one('FULL_HDMI_REPLY_QUEUED')
                wire = bytearray.fromhex(row['fields']['raw']); wire[offset] ^= 1
                row['fields']['raw'] = wire.hex()
                proof = {'identity': ('259', '383'), 'edges': [{'REQUEST': {'line': 100}}]}
                with self.subTest(command=command, offset=offset), self.assertRaises(ValueError):
                    v.check_repaired_hdmi_frees(log, repairs, proof, self.graph)

    def zfq_resource_raw(self, cold_warning=False):
        """Verbatim observer windows; selected native context is not a full-graph fixture."""
        sixth, video = 'FULL_VEF_PINMEM_INPUT_CONNECT', 'FULL_PINMEM_HDMI_VIDEO_CONNECT'
        table = ('1a00000005040000000008000000000000802afe0400000000840000000008000000001e0000000000b0b4477e000000000008001d00000000b0b4477e00000000000800000000001b000000060400000000080000000000008032fe0400000001840000000008000000081e0000000000b0ac477e000000000008001e00000000b0ac477e0000000000080000000000')
        def tts(prefix, tid):
            return record(prefix + '_RESOURCES_TTS_TABLE', pid=259, tid=tid, appfw_base='0x7f62509000',
                table_va='0x5f66b08', address='0x7f6846fb08', bytes=144, reads='144/144', unchanged=1,
                atomic_snapshot=0, raw_before=table, raw_after=table, ownership_verified=0)['raw'].encode()
        def reserved(prefix, tid, allocations, pending):
            return (f'OBS {prefix}_RESOURCES_RESERVED tid={tid} accepted=1 dmm_enabled=1 dmm_bound=1 '
                'dmm_slots=1/1 dmm_opens=1/1 dmm_handles=0x8400/0x8401 dmm_generations=1/1 dmm_epochs=1/2 '
                'dmm_creators=1/1 dmm_allocation_count=2 dmm_lifecycle_changed=0 dmm_domain=2 foreign_speech_kept=1 '
                f'data_frozen=0 control_bound=1 control_live=0 control_faults=0 allocations={allocations} releases={allocations} '
                'connection_started=1 connections=1 format_pending=0 blocked=0 format_consumed=1 buffer_released=1 '
                'connection_reply_frees=1 connection_faults=0 vef_init=1 vef_owner=0x905a0048 vef_objects=16 '
                'vef_pending=0 vef_live=0 vef_retained=0 vef_faults=0 pinmem_init=1 pinmem_owner=0x90590818 '
                f'pinmem_objects=13 pinmem_pending={pending} pinmem_live=0 pinmem_retained=0 pinmem_faults=0 '
                'global_dmm_idle_verified=0 original_cp_executed=0 capture_verified=0').encode()
        def dependencies(prefix, tid):
            return record(prefix + '_RESOURCE_DEPENDENCIES', pid=259, tid=tid, accepted=1, proc_ap_consumed=1,
                input_ap_consumed=1, output_ap_consumed=1, output_faults=0,
                current_request_retained_expected=1, capture_verified=0)['raw'].encode()
        rows, windows = [], []
        def append(raw, warning=None):
            window = raw + (warning or b'') + b'\r\n'
            rows.append(window)
            if warning:
                windows.append(window)
        # Actual first Speech allocation witnesses, before the later sampled guard.
        for sample in (1, 2):
            append(record('DMM_REQUEST', tid=345, op='0x20', unit='0x63a', handle=0, option='0x1',
                source='0x81cf61c3', bytes=40, sampled=40,
                raw='200000003a06000000000000ffffffff000000000000010000000000000000000000000000000000')['raw'].encode())
            for depth, (fp, offset) in enumerate(((0x7f61c02f40, 0x35522a4), (0x7f61c02fa0, 0x35527b4),
                                                (0x7f61c03010, 0x34d3614), (0x7f61c03030, 0x17b2c08))):
                append(record('DMM_ALLOC_FRAME', sample=sample, tid=345, depth=depth, fp=hex(fp),
                    lr=hex(0x7f62509000 + offset), appFw_offset=hex(offset), in_appFw=1,
                    caller_matches=1, frame_candidate_only=1)['raw'].encode())
            append(record('DMM_ALLOC_CREATOR', sample=sample, tid=345, frames=8, caller_matches=1,
                creator_kind=1, gate_admission_unchanged=1)['raw'].encode())
            append(record('DMM_SERVICE', pid=259, tid=345, source='0x81cf61c3', op='0x20', transport=0,
                status=0, handle=hex(0x8400 + sample - 1), address=hex(0x1e000000 + (sample - 1) * 0x80000),
                size='0x80000', slots='1/0' if sample == 1 else '1/1', opens='1/0' if sample == 1 else '1/1',
                caller='/usr/lib/appFw.so+0x35522a4', caller_raw='0x7f65a5b2a4', sample=sample,
                creator_kind=1, allocation_count=sample, lifecycle_changed=0,
                slot_epochs='1/0' if sample == 1 else '1/2', slot_creators='1/0' if sample == 1 else '1/1')['raw'].encode())
        append(tts('FULL_VEF', 383)); append(reserved('FULL_VEF', 383, 1, 0))
        append(dependencies(sixth, 383)); append(tts(sixth, 383), v.WARNINGS[0])
        append(reserved(sixth, 383, 3, 0))
        append(b'OBS FULL_VEF_PINMEM_INPUT_CONNECT_REQUEST pid=259 tid=383 source=0x81cf61c4 destination=0x905a0048 pointer=0x7fb69a1fc0 bytes=64 raw=c461cf81a0a0a0a001004000180000004000000000000000001001002800020000000000020000000200000048005a9000000000010000000000000018085990 transport_owner=virtual-local-caller canonical_padding=1 original_CP_executed=0 frames_verified=0 capture_verified=0')
        append(b'OBS FULL_VEF_PINMEM_INPUT_CONNECT_REPLY_FREE pid=259 tid=383 destination=0x81cf61c4 expected=0x81cf61c4 pointer=0x7fb6b33140 bytes=56 rc=0 faults=0 ap_consumed=1 frames_verified=0 capture_verified=0')
        append(reserved('FULL_PINMEM_DRAWINFO_CONNECT', 383, 4, 0))
        append(b'OBS FULL_PINMEM_DRAWINFO_CONNECT_NATIVE_REPLY_FREE pid=259 tid=383 sender=383 waiter=1 destination=0x81cf61c4 expected=0x81cf61c4 reply=0x7fb6b33140 bytes=56 command=0x8001 rc=0 faults=0 ap_consumed=1 capture_verified=0')
        append(dependencies(video, 383)); append(tts(video, 383), v.WARNINGS[0] if cold_warning else None)
        append(reserved(video, 383, 4, 0))
        append(b'OBS FULL_PINMEM_HDMI_VIDEO_CONNECT_REQUEST pid=259 producer_tid=383 source=0x81cf61c4 destination=0x90590818 pointer=0x7fb69fd1c0 bytes=64 raw=c461cf81a0a0a0a0010040001800000040000000000000000010010028000200040000000200000000000000180859900400000001000000000000005a019a90 original_CP_executed=0 original_RTOS_scheduling_verified=0 frames_verified=0 capture_verified=0')
        append(b'OBS FULL_PINMEM_HDMI_VIDEO_CONNECT_EVENT6_ENQUEUED event=6 parameter_bytes=12 token_policy=owned-answer-plus24-map phase=1 wait_primary=6 keep_pending=1 peer_posthandler_pending=1 original_CP_event_pointer_identity_verified=0 capture_verified=0')
        for index, tid in enumerate((351, 345, 351, 345)):
            append(dependencies(video, tid)); append(tts(video, tid), v.WARNINGS[0] if index == 0 else None)
            append(reserved(video, tid, 4, 1), (v.WARNINGS[1] if index == 2 else v.WARNINGS[0]) if index else None)
        append(b'OBS FULL_PINMEM_HDMI_VIDEO_CONNECT_PEER_REPLY pid=259 producer_tid=351 source=0x909a015a destination=0x90590818 pointer=0x7fb6b33a80 bytes=72 raw=00000000a0a0a0a0010048001800000048000000000000000010008130000100040000000200000000000000180859900400000001000000000000005a019a900000000000000000 original_CP_executed=0 original_RTOS_scheduling_verified=0 frames_verified=0 capture_verified=0')
        append(b'OBS FULL_PINMEM_HDMI_VIDEO_CONNECT_NATIVE_REPLY_FREE pid=259 tid=383 sender=383 producer_tid=351 waiter=1 destination=0x81cf61c4 expected=0x81cf61c4 reply=0x7fb6b33140 bytes=56 command=0x8001 rc=0 faults=0 ap_consumed=1 capture_verified=0')
        return b''.join(rows), windows

    def zfq_resource_context(self, log):
        # Partial native context for this component, never an evaluate() positive.
        edges = [{'REQUEST': record('HOST_TEST_UNEVALUATED')} for _ in range(11)]
        for index, prefix, source, peer in ((5, self.graph.six.SIXTH[0], self.graph.six.SIXTH[3], self.graph.six.SIXTH[4]),
                                           (10, self.hdmi.PREFIX, self.hdmi.S, self.hdmi.P)):
            edges[index] = dict(REQUEST=log.one(prefix + '_REQUEST'),
                REPLY_FREE=log.one(prefix + ('_REPLY_FREE' if index == 5 else '_NATIVE_REPLY_FREE')),
                source_pin=source, sink_pin=peer, caller=0x81cf61c4)
        edges[9]['resources'] = log.one('FULL_PINMEM_DRAWINFO_CONNECT_RESOURCES_RESERVED')
        edges[10].update(EVENT6_ENQUEUED=log.one(self.hdmi.PREFIX + '_EVENT6_ENQUEUED'),
            PEER_REPLY=log.one(self.hdmi.PREFIX + '_PEER_REPLY'),
            predecessor_free_line=log.one('FULL_PINMEM_DRAWINFO_CONNECT_NATIVE_REPLY_FREE')['line'])
        return {'identity': ('259', '383'), 'edges': edges,
                'resources': {self.graph.six.SIXTH[0]: log.one(self.graph.six.SIXTH[0] + '_RESOURCES_RESERVED')},
                'legacy_histories': {'Speech': self.graph.tts.prove_initial_creation(log.raw)}}

    def test_zfq_actual_resource_windows_require_new_content_join(self):
        raw, windows = self.zfq_resource_raw()
        self.assertEqual([v.sha(window) for window in windows], [
            'f051e1bcad19d84c456136f67dd0fa26956c819f81a7e28fea77226314ff3f4d',
            '3995acb951aef76efa4fafdf0742ca4c29a9b5c9a1a934aadab94e1371c23723',
            '0471a50af51d9ed310040a871d19219b5fedf9d7210bc5fa6c352dbe4a107bcf',
            '8adff5a40ef1c844c14ecb464f16461d5404da3db5ae96203365e1619d9d687b',
            '0471a50af51d9ed310040a871d19219b5fedf9d7210bc5fa6c352dbe4a107bcf'])
        parsed, repairs = v.console_records(raw)
        log = self.graph.Log(parsed)
        proof = self.zfq_resource_context(log)
        self.assertEqual(len(repairs), 5)
        with self.assertRaises(v.UnjoinedRepairs) as caught:
            v.bind_repairs(proof, repairs)
        self.assertEqual(len(caught.exception.repairs), 5)
        self.assertTrue(all(r['parsed_line'] > 0 and len(r['repaired_record_sha256']) == 64 for r in caught.exception.repairs))
        self.assertTrue(all('content_verifier_joined' not in r for r in repairs))
        proof['repaired_resource_snapshot_joins'] = v.check_repaired_resources(log, repairs, proof, self.graph)
        v.bind_repairs(proof, repairs)
        self.assertTrue(all(r['content_verifier_joined'] for r in repairs))
        joins = proof['repaired_resource_snapshot_joins']
        self.assertEqual(len(joins), 5)
        self.assertEqual(sorted(j['reservation']['fields']['tid'] for j in joins), ['345', '345', '351', '351', '383'])
        self.assertEqual(sum(j['pending_event6'] for j in joins), 4)
        for join in joins:
            self.assertFalse(join['capture_verified'])
            self.assertFalse(join['resource_release_authorized'])
            self.assertIs(join['table_snapshot'], next(r for r in log.records if r['line'] == join['table_snapshot']['line']))
        # The cold reservation uses the same source guard, with pending=0 and original sender.
        parsed, repairs = v.console_records(self.zfq_resource_raw(cold_warning=True)[0])
        log = self.graph.Log(parsed); proof = self.zfq_resource_context(log)
        proof['joins'] = v.check_repaired_resources(log, repairs, proof, self.graph)
        v.bind_repairs(proof, repairs)
        self.assertEqual(sum(j['pending_event6'] for j in proof['joins']), 4)
        self.assertEqual(len(proof['joins']), 6)

    def test_zfq_resources_reject_changed_bytes_owner_guard_and_failed_ap_free(self):
        parsed, repairs = v.console_records(self.zfq_resource_raw()[0])
        base = self.graph.Log(parsed)
        prefix = self.hdmi.PREFIX
        cases = ((prefix + '_RESOURCE_DEPENDENCIES', 'pid', '260'),
                 (prefix + '_RESOURCE_DEPENDENCIES', 'output_faults', '1'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'pid', '260'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'tid', '352'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'appfw_base', '0x7f62509001'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'address', '0x7f6846fb09'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'ownership_verified', '1'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'reads', '143/144'),
                 (prefix + '_RESOURCES_TTS_TABLE', 'raw_before', '00' * 144),
                 (prefix + '_RESOURCES_RESERVED', 'dmm_handles', '0x8401/0x8400'),
                 (prefix + '_RESOURCES_RESERVED', 'dmm_generations', '2/1'),
                 (prefix + '_RESOURCES_RESERVED', 'dmm_epochs', '1/3'),
                 (prefix + '_RESOURCES_RESERVED', 'dmm_creators', '1/0'),
                 (prefix + '_RESOURCES_RESERVED', 'dmm_allocation_count', '3'),
                 (prefix + '_RESOURCES_RESERVED', 'dmm_lifecycle_changed', '1'),
                 (prefix + '_RESOURCES_RESERVED', 'pinmem_pending', '0'),
                 (prefix + '_RESOURCES_RESERVED', 'pinmem_live', '1'),
                 (prefix + '_RESOURCES_RESERVED', 'control_live', '1'),
                 (prefix + '_RESOURCES_RESERVED', 'releases', '3'),
                 (prefix + '_RESOURCES_RESERVED', 'capture_verified', '1'),
                 (prefix + '_NATIVE_REPLY_FREE', 'rc', '-1'),
                 (prefix + '_NATIVE_REPLY_FREE', 'pid', '260'),
                 (prefix + '_NATIVE_REPLY_FREE', 'tid', '351'),
                 (prefix + '_NATIVE_REPLY_FREE', 'bytes', '55'),
                 (prefix + '_NATIVE_REPLY_FREE', 'ap_consumed', '0'))
        for tag, field, value in cases:
            log = copy.deepcopy(base)
            row = next(r for r in log.rows(tag) if r['fields'].get('tid') == ('351' if not tag.endswith('_NATIVE_REPLY_FREE') else '383'))
            row['fields'][field] = value
            row['raw'] = record(row['tag'], row['line'], **row['fields'])['raw']
            changed = copy.deepcopy(repairs)
            for repair in changed:
                if repair['parsed_line'] == row['line']:
                    repair.update(repaired_record=row['raw'], repaired_record_sha256=v.sha(row['raw'].encode()))
            with self.subTest(tag=tag, field=field), self.assertRaises(ValueError):
                v.check_repaired_resources(log, changed, self.zfq_resource_context(log), self.graph)
        # Equal before/after bytes still must match the actual initial Speech table.
        log = copy.deepcopy(base)
        row = next(r for r in log.rows(prefix + '_RESOURCES_TTS_TABLE') if r['fields']['tid'] == '351')
        row['fields'].update(raw_before='00' * 144, raw_after='00' * 144)
        row['raw'] = record(row['tag'], row['line'], **row['fields'])['raw']
        changed = copy.deepcopy(repairs)
        for repair in changed:
            if repair['parsed_line'] == row['line']:
                repair.update(repaired_record=row['raw'], repaired_record_sha256=v.sha(row['raw'].encode()))
        with self.assertRaisesRegex(ValueError, 'original Speech bytes/address'):
            v.check_repaired_resources(log, changed, self.zfq_resource_context(log), self.graph)

    def test_zfq_resources_reject_missing_duplicate_borrowed_and_wrong_phase_joins(self):
        parsed, repairs = v.console_records(self.zfq_resource_raw()[0])
        base = self.graph.Log(parsed)
        prefix = self.hdmi.PREFIX
        for suffix in ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED', 'REQUEST', 'NATIVE_REPLY_FREE'):
            for duplicate in (False, True):
                log = copy.deepcopy(base)
                row = log.rows(prefix + '_' + suffix)[0]
                index = log.records.index(row)
                if duplicate:
                    log.records.insert(index, copy.deepcopy(row))
                else:
                    log.records.pop(index)
                with self.subTest(suffix=suffix, duplicate=duplicate), self.assertRaises(ValueError):
                    v.check_repaired_resources(log, repairs, self.zfq_resource_context(log), self.graph)
        for wrong in ('missing-edge', 'caller', 'pending-start', 'pending-end', 'no-Speech-ownership', 'borrowed-line'):
            proof = self.zfq_resource_context(base)
            changed = copy.deepcopy(repairs)
            if wrong == 'missing-edge':
                proof['edges'][10]['REQUEST'] = record('HOST_TEST_OTHER_REQUEST')
            elif wrong == 'caller':
                proof['edges'][10]['caller'] += 1
            elif wrong == 'pending-start':
                proof['edges'][10]['EVENT6_ENQUEUED'] = {'line': len(base.lines) + 1}
            elif wrong == 'pending-end':
                proof['edges'][10]['PEER_REPLY'] = {'line': 1}
            elif wrong == 'no-Speech-ownership':
                proof['legacy_histories']['Speech']['initial_speech_lifecycle_verified'] = False
            else:
                changed[1]['parsed_line'] += 1
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                v.check_repaired_resources(base, changed, proof, self.graph)
        # An unrelated record keeps a precise failure after real resource joins return.
        proof = self.zfq_resource_context(base)
        proof['joins'] = v.check_repaired_resources(base, repairs, proof, self.graph)
        extra = {'kind': 'HOST_TEST-unjoined', 'parsed_line': len(base.lines) + 1,
                 'repaired_record': 'OBS FULL_SCALAR_HOST_TEST still_unconsumed=1',
                 'repaired_record_sha256': v.sha(b'OBS FULL_SCALAR_HOST_TEST still_unconsumed=1')}
        with self.assertRaises(v.UnjoinedRepairs) as caught:
            v.bind_repairs(proof, repairs + [extra])
        self.assertEqual(caught.exception.repairs[0]['tag'], 'FULL_SCALAR_HOST_TEST')
        self.assertTrue(all('content_verifier_joined' not in r for r in repairs))

    def conditions(self):
        rows = []
        indices = tuple(range(11)) + (12,)
        for ordinal, (index, cid) in enumerate(zip(indices + tuple(i + 13 for i in indices), self.hdmi.IDS * 2)):
            body = struct.pack('<5I', 2, cid, 1, 0, 0).hex()
            common = dict(pointer=hex(0x1000 + ordinal * 32), destination=hex(self.hdmi.CONDITION_SID),
                          lease=ordinal + 1, kind=2, bytes=20, rc=0)
            published = record(self.hdmi.STATE + '_MESSAGE_PUBLISHED', ordinal * 3 + 1,
                               **common, source=hex(self.hdmi.CONDITION_SOURCE), index=index, raw=body, tid=723)
            sent = record(self.hdmi.STATE + '_MESSAGE_SENT', ordinal * 3 + 2,
                          **common, source=hex(self.hdmi.CONDITION_SOURCE), index=index, raw=body, tid=723)
            freed = record(self.hdmi.STATE + '_NATIVE_FREE', ordinal * 3 + 3,
                           **common, tid=741, sender=723, receiver=741, received=1, consumed=1)
            rows += [published, sent, freed]
        log = self.graph.Log(b''); log.records = rows
        return log

    def test_known_native_condition_body_host_fixture(self):
        result = self.hdmi.verify_conditions(self.conditions())
        self.assertEqual(len(result['messages']), 24)
        self.assertEqual(result['receiver_tid'], '741')
        self.assertFalse(result['condition_model_events_verified'])

    def test_missing_condition_wrong_source_and_wrong_receiver(self):
        for mutation in ('missing', 'source', 'receiver'):
            log = self.conditions()
            if mutation == 'missing':
                log.records.pop()
            elif mutation == 'source':
                log.records[0]['fields']['source'] = hex(self.hdmi.P[3])
            else:
                log.records[2]['fields']['receiver'] = '742'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.hdmi.verify_conditions(log)

    def test_missing_one_upm_receipt_is_never_substituted(self):
        reader = types.SimpleNamespace(read_receipts=Mock(return_value=[{'HOST_TEST': True}]))
        with patch.object(self.hdmi, '_watch', return_value=reader):
            with self.assertRaisesRegex(ValueError, 'exactly two validated native UPM receipts'):
                self.hdmi.verify_hdmi_upm(self.graph.Log(b''), Path('/HOST_TEST/no-run'))
        reader.read_receipts.assert_called_once_with(Path('/HOST_TEST/no-run'))

    def osd_negative_prefix(self):
        """Deliberately incomplete HOST_TEST prefix for exact targeted rejections."""
        h = self.osd
        rows = [record(h.PREFIX + '_' + tag, i + 1, HOST_TEST='incomplete-prefix')
                for i, (tag, _) in enumerate(h._plan())]
        log = self.graph.Log(b''); log.records = rows
        def fields(tag, **values):
            log.one(h.PREFIX + '_' + tag)['fields'] = {k: str(value) for k, value in values.items()}
        caller, pid, tid = 0x81cf619b, '701', '723'
        for tag, n, command, flags, source, destination, words in (
            ('REQUEST', 64, 1, 2, caller, h.S[3], h.S + h.P),
            ('PEER_REQUEST', 64, 0x100, 1, h.S[3], h.P[3], h.S + h.P),
            ('PEER_REPLY', 72, 0x8100, 1, h.P[3], h.S[3], h.S + h.P + (0, 0)),
            ('REPLY_QUEUED', 56, 0x8001, 2, h.S[3], caller, h.S + (0, 0))):
            fields(tag, pid=pid, tid=tid, bytes=n, source=hex(source), destination=hex(destination),
                   pointer=hex(0x1000 + n + command), raw=self.old.frame_bytes(n, command, flags, words,
                       caller if tag == 'REQUEST' else 0).hex())
        fields('REQUEST_FREE', owner=hex(h.S[3]), pointer=log.one(h.PREFIX + '_REQUEST')['fields']['pointer'], bytes=64, rc=0)
        fields('NATIVE_REPLY_FREE', pid=pid, tid=tid, sender=tid, waiter=1, destination=hex(caller),
               expected=hex(caller), reply=log.one(h.PREFIX + '_REPLY_QUEUED')['fields']['pointer'],
               bytes=56, command='0x8001', rc=0, faults=0, ap_consumed=1, capture_verified=0)
        fields('EVENT6_ENQUEUED', event=6, parameter_bytes=12, token=hex(h.TOKEN),
               token_policy='owned-answer-plus24-map', saved_original_request_bytes=64,
               queue_phase=1, wait_primary=6, keep_pending=1, context_kind=2, original_RTOS_scheduling_verified=0)
        fields('EVENT6_CONSUMED', parameter_bytes=12, actual_parameter_read=1, token_body_binding_verified=1,
               saved_peer_u32_fields_verified=4, source_complete_raw='0x5839a6', source_state=0,
               status=0, tail=0, original_RTOS_scheduling_verified=0)
        fields('SOURCE_POST', source_raw='0x5d61a2', inactive_rows=5, selected_tag100_backing_count=0,
               OSD_cached_count=1, repeated_notice=0, extra_share=0, extra_open=0, metadata_ready=1,
               graphics_ready=0, GPE_ready=0, optional_diagnostic_skipped=1)
        fields('RESOURCE_READBACK', live=16, owners_each=2, opens_each=2, DMM_requests=48,
               DMM_replies=48, reference_readbacks=48, peer_notices=4, source_notices=12,
               exact_backing_and_known_masks_verified=1, selected_backing_count=0, cached_count=1,
               original_allocator_capacity_verified=0, original_CP_pages_verified=0, frames_verified=0, capture_verified=0)
        fields('COMMIT', source_state=0, peer_state=0, pending=0, metadata_only=1,
               AP_reply_after_16_buffers_48_DMM_and_source_post=1, persistent_resources=16,
               graphics_ready=0, GPE_ready=0, frames_verified=0, capture_verified=0)
        data = bytearray([0xa5] * 40)
        struct.pack_into('<H', data, 0, 0x20)
        struct.pack_into('<I', data, 4, h.UNIT)
        struct.pack_into('<IIHH', data, 12, 0xffffffff, 0x61003c, 0x4f01, 1)
        log.rows(h.PREFIX + '_DMM_REQUEST')[0]['fields'] = dict(pid=pid, tid=tid, source=hex(h.P[3]),
            destination=hex(h.DMM), bytes='40', raw=data.hex())
        log.rows(h.PREFIX + '_DMM_REPLY')[0]['fields'] = dict(pid=pid, tid=tid, source=hex(h.DMM),
            destination='0x61003c', bytes='40', raw=data.hex())
        return log

    def test_osd_missing_persistent_reference_is_rejected(self):
        log = self.osd_negative_prefix()
        log.one(self.osd.PREFIX + '_RESOURCE_READBACK')['fields']['owners_each'] = '1'
        with self.assertRaisesRegex(ValueError, 'owners_each'):
            self.osd.verify_osd_effects(log, self.graph)

    def test_osd_dmm_request_copy_cannot_be_a_reply(self):
        with self.assertRaisesRegex(ValueError, 'complete DMM reply/result/H/mapping mismatch'):
            self.osd.verify_osd_effects(self.osd_negative_prefix(), self.graph)

    def test_osd_r_backing_changes_while_cached_count_stays_one(self):
        initial, mask, _ = self.osd._backing(2)
        final, final_mask, _ = self.osd._backing(2, final=True)
        self.assertNotEqual(self.osd._fnv(initial), self.osd._fnv(final))
        self.assertEqual(mask, final_mask)
        self.assertEqual(struct.unpack_from('<I', initial, 64)[0], 1)
        self.assertEqual(struct.unpack_from('<I', final, 64)[0], 0)
        self.assertEqual(sum(mask), 71)
        self.assertEqual(initial[68:72], b'\xa5' * 4)

    def run_binding_fixture(self, run):
        """Synthetic process receipts; no live PID/VM or evaluate() positive."""
        info = run.stat()
        raw = b'HOST_TEST completed console\n'
        result = {'detached': True, 'receipts': 2, 'HOST_TEST': True}
        build = {key: v.sha(key.encode()) for key in ('model_sha256', 'model_build_sha256', 'model_source_archive_sha256')}
        build['qemu_sha256'] = v.SELECTED_QEMU_SHA256
        owner = dict(pid=302, ppid=301, starttime=101, exe='/usr/bin/python3.14')
        qemu = dict(pid=304, ppid=303, starttime=103, exe='/tools/qemu-system-aarch64')
        gdb = dict(path=str(run / 'hdmi-upm-gdb.sock'), device=info.st_dev, inode=111, listener_inode=112)
        qmp = dict(path=str(run / 'hdmi-upm-control.sock'), device=info.st_dev, inode=221, listener_inode=222)
        mailbox = dict(pid=701, nonce=17)
        runner = {'schema': 'functional-camera-runner-v1', 'profile': 'virtual-functional-camera-v1',
                  'phase': 'closed', 'error': None, 'broker_started': True, 'owner': owner,
                  'console_sha256_at_close': v.sha(raw),
                  'cleanup': {**dict.fromkeys(('safe_to_close', 'mailbox_detached', 'debugger_stopped',
                                              'protocol_physmode_restored', 'worker_stopped'), True), 'errors': []},
                  **dict.fromkeys(('capture_verified', 'physical_ASIC_compatibility_verified',
                                   'original_CP_RAM_verified', 'standalone_host_media_write'), False),
                  'mailbox_evidence': {'mailbox': mailbox}, 'broker_receipts': str(run / v.BROKER_RECEIPTS),
                  'artifact': {'library_sha256': build['model_sha256'], 'build_receipt_sha256': build['model_build_sha256'],
                               'source_archive_sha256': build['model_source_archive_sha256'], 'qemu_sha256': build['qemu_sha256']},
                  'debugger_handoff': {'qemu_pid': qemu['pid'], 'qemu_identity': qemu, 'debugger_quiesced': True,
                                       'previous_hdmi_observer': result,
                                       'sockets': {'hdmi-upm-gdb.sock': gdb, 'hdmi-upm-control.sock': qmp}}}
        watcher = dict(run=str(run), run_device=info.st_dev, run_inode=info.st_ino,
                       running_QEMU_sha256=build['qemu_sha256'], owner_pid=301, owner_starttime=100,
                       owner_exe=owner['exe'], qemu_pid=qemu['pid'], qemu_starttime=qemu['starttime'],
                       qemu_exe=qemu['exe'], socket_device=gdb['device'], socket_inode=gdb['inode'])
        binding = copy.deepcopy({'kind': 'binding', 'event': 1, 'mailbox': mailbox, 'model_instance': mailbox['nonce'],
                   'config': {'run': str(run), 'run_identity': [info.st_dev, info.st_ino], 'owner': owner, 'qemu': qemu,
                              'qemu_sha256': build['qemu_sha256'], 'gdb': gdb, 'qmp': qmp}})
        proof = {'identity': ('701', '723'), 'edges': [{} for _ in range(10)] + [{'native_UPM': {'GDB_result': copy.deepcopy(result)}}]}
        return dict(run=run, raw=raw, runner=runner, manifest={'host_control_owner_pid': 301}, watcher=watcher,
                    binding=binding, proof=proof, build=build)

    def check_binding_fixture(self, fixture):
        run = fixture['run']
        (run / v.UPM_FILES[0]).write_text(json.dumps(fixture['watcher']))
        (run / v.BROKER_RECEIPTS).write_text(json.dumps(fixture['binding']) + '\n')
        manifest = {**fixture['manifest'], 'functional_camera_runtime': copy.deepcopy(fixture['runner'])}
        return v.check_run_binding(types.SimpleNamespace(typed_equal=v.profile_value_equal), run, manifest,
                                   fixture['runner'], fixture['raw'], fixture['proof'], fixture['build'])

    def test_host_control_parent_runner_and_shell_qemu_roles(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-graph-owner-') as name:
            fixture = self.run_binding_fixture(Path(name))
            result = self.check_binding_fixture(fixture)
            self.assertEqual(result['owner_relationship'], 'direct-child')
            self.assertNotEqual(result['host_control_identity']['pid'], result['runner_owner']['pid'])
            self.assertNotEqual(result['qemu_identity']['ppid'], result['runner_owner']['pid'])
            self.assertTrue(result['same_run_UPM_receipts_verified'])
            self.assertNotIn('graph_verified', result)
            self.assertNotIn('capture_verified', result)
            fixture['watcher'].update(owner_pid=302, owner_starttime=101)
            fixture['manifest']['host_control_owner_pid'] = 302
            self.assertEqual(self.check_binding_fixture(fixture)['owner_relationship'], 'same-process')
            fixture['watcher']['owner_starttime'] = 100
            with self.assertRaisesRegex(ValueError, 'parent or process generation'):
                self.check_binding_fixture(fixture)

    def test_new_and_legacy_selected_digest_propagates_to_all_run_bindings(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-graph-qemu-bindings-') as name:
            for selected, other in ((v.READONLY_SCOPE_QEMU_SHA256, v.SELECTED_QEMU_SHA256),
                                    (v.SELECTED_QEMU_SHA256, v.READONLY_SCOPE_QEMU_SHA256)):
                fixture = self.run_binding_fixture(Path(name))
                fixture['build']['qemu_sha256'] = fixture['runner']['artifact']['qemu_sha256'] = selected
                fixture['watcher']['running_QEMU_sha256'] = fixture['binding']['config']['qemu_sha256'] = selected
                self.assertTrue(self.check_binding_fixture(fixture)['same_run_UPM_receipts_verified'])
                fixture['binding']['config']['qemu_sha256'] = other
                with self.subTest(selected=selected, mixed='broker'), self.assertRaisesRegex(ValueError, 'actual broker'):
                    self.check_binding_fixture(fixture)
                fixture['binding']['config']['qemu_sha256'] = selected
                fixture['runner']['artifact']['qemu_sha256'] = other
                with self.subTest(selected=selected, mixed='runner'), self.assertRaisesRegex(ValueError, 'frozen batch differs'):
                    self.check_binding_fixture(fixture)
                fixture['runner']['artifact']['qemu_sha256'] = selected
                fixture['watcher']['running_QEMU_sha256'] = other
                with self.subTest(selected=selected, mixed='UPM'), self.assertRaisesRegex(ValueError, 'UPM/current run/QEMU'):
                    self.check_binding_fixture(fixture)
            fixture = self.run_binding_fixture(Path(name))
            fixture['build']['qemu_sha256'] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'not an admitted batch executable'):
                self.check_binding_fixture(fixture)

    def test_owner_qemu_generations_and_exact_broker_bindings_rejected(self):
        mutations = (
            (('runner', 'owner', 'ppid'), 999),
            (('runner', 'owner', 'pid'), 999),
            (('runner', 'owner', 'starttime'), 102),
            (('runner', 'owner', 'starttime'), 99),
            (('runner', 'owner', 'starttime'), 104),
            (('runner', 'owner', 'pid'), True),
            (('watcher', 'owner_starttime'), 102),
            (('watcher', 'owner_starttime'), 0),
            (('watcher', 'owner_starttime'), 100.0),
            (('watcher', 'owner_exe'), '/HOST_TEST/python3.14'),
            (('watcher', 'owner_pid'), 999),
            (('manifest', 'host_control_owner_pid'), 999),
            (('watcher', 'qemu_starttime'), 104),
            (('watcher', 'qemu_pid'), 999),
            (('watcher', 'qemu_exe'), '/HOST_TEST/qemu-system-aarch64'),
            (('watcher', 'run'), '/HOST_TEST/other-run'),
            (('watcher', 'run_inode'), 0),
            (('watcher', 'socket_inode'), 999),
            (('runner', 'debugger_handoff', 'qemu_pid'), 999),
            (('runner', 'debugger_handoff', 'qemu_identity', 'pid'), 999),
            (('runner', 'debugger_handoff', 'qemu_identity', 'starttime'), 104),
            (('runner', 'debugger_handoff', 'qemu_identity', 'ppid'), 301),
            (('runner', 'debugger_handoff', 'qemu_identity', 'ppid'), 999),
            (('runner', 'debugger_handoff', 'previous_hdmi_observer', 'detached'), False),
            (('runner', 'debugger_handoff', 'debugger_quiesced'), False),
            (('runner', 'broker_receipts'), '/HOST_TEST/other-receipts.jsonl'),
            (('binding', 'config', 'owner', 'starttime'), 102),
            (('binding', 'config', 'owner', 'ppid'), 999),
            (('binding', 'config', 'qemu', 'starttime'), 104),
            (('binding', 'config', 'qemu', 'pid'), 999),
            (('binding', 'config', 'qemu', 'ppid'), 999),
            (('binding', 'config', 'qemu_sha256'), '0' * 64),
            (('binding', 'config', 'run'), '/HOST_TEST/other-run'),
            (('binding', 'config', 'run_identity'), [0, 0]),
            (('binding', 'config', 'gdb', 'inode'), 999),
            (('binding', 'mailbox', 'pid'), 702),
            (('binding', 'model_instance'), 18),
            (('binding', 'event'), True),
            (('runner', 'cleanup', 'mailbox_detached'), False),
            (('runner', 'console_sha256_at_close'), '0' * 64),
        )
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-graph-owner-negative-') as name:
            for path, value in mutations:
                fixture = self.run_binding_fixture(Path(name))
                target = fixture
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                with self.subTest(path=path, value=value), self.assertRaises(ValueError):
                    self.check_binding_fixture(fixture)

    def test_missing_broker_binding_never_substituted(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-graph-owner-missing-') as name:
            fixture = self.run_binding_fixture(Path(name))
            self.check_binding_fixture(fixture)
            (fixture['run'] / v.BROKER_RECEIPTS).unlink()
            manifest = {**fixture['manifest'], 'functional_camera_runtime': fixture['runner']}
            with self.assertRaises(FileNotFoundError):
                v.check_run_binding(types.SimpleNamespace(typed_equal=v.profile_value_equal), fixture['run'], manifest,
                                    fixture['runner'], fixture['raw'], fixture['proof'], fixture['build'])

    def test_exact_dependency_closure_and_current_source_required(self):
        frozen = current_dependencies()
        self.assertEqual(len(v.check_dependency_hashes(frozen)), len(v.FROZEN_DEPENDENCIES))
        for relative in ('scratch/verify_osd_edge.py', 'scratch/test_verify_hdmi_edge.py'):
            name = str(v.RUNTIME / relative)
            wrong = dict(frozen); wrong[name] = '0' * 64
            with self.subTest(name=relative), self.assertRaisesRegex(ValueError, 'current/frozen dependency SHA differs'):
                v.check_dependency_hashes(wrong)
            del wrong[name]
            with self.subTest(name=relative), self.assertRaisesRegex(v.SourceMissing, 'missing frozen dependency'):
                v.check_dependency_hashes(wrong)

    def test_new_batch_cannot_use_old_ready_input_hash(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-graph-inputs-') as name:
            batch = Path(name)
            old = b'{"capture_verified":false,"groups":{}}'
            current = b'{"capture_verified":false,"groups":{"changed":"HOST_TEST"}}'
            (batch / 'inputs.json').write_bytes(current)
            (batch / 'ready.json').write_text(json.dumps({'capture_verified': False, 'inputs_sha256': v.sha(old)}))
            with self.assertRaisesRegex(ValueError, 'current ready/inputs SHA differs'):
                v.frozen_inputs(batch)

    def test_invalid_or_missing_input_never_graph_or_capture_passes(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST-graph-missing-') as name:
            result = v.evaluate(Path(name), Path(name))
        self.assertFalse(result['graph_verified'])
        self.assertFalse(result['all_13_graph_edges_complete'])
        self.assertFalse(result['capture_verified'])
        self.assertEqual(len(result['all_thirteen']), 13)
        self.assertTrue(all(row['verified'] is False for row in result['all_thirteen'].values()))
        self.assertTrue(result['missing'])
        json.dumps(result)

    def test_candidate_a0d_and_production_e235_are_distinct_file_joins(self):
        self.assertEqual(v.READONLY_SCOPE_QEMU_SHA256,
                         '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4')
        candidate = '/HOST_TEST/qemu-candidate'
        manifest = {'backup_transport': {'binary': candidate, 'binary_sha256': v.SELECTED_QEMU_SHA256},
                    'files': {candidate: v.SELECTED_QEMU_SHA256}}
        reader = types.SimpleNamespace(read_absolute=Mock(side_effect=[b'HOST_TEST_candidate', b'HOST_TEST_production']),
                                       digest_binding=Mock())
        result = v.check_qemu_files(reader, manifest)
        self.assertEqual(result['selected_candidate_sha256'],
                         'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02')
        self.assertEqual(result['unchanged_production_sha256'],
                         'e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d')
        self.assertEqual(reader.digest_binding.call_args_list[0].args[:2],
                         (b'HOST_TEST_candidate', v.SELECTED_QEMU_SHA256))
        self.assertEqual(reader.digest_binding.call_args_list[1].args[:2],
                         (b'HOST_TEST_production', v.PRODUCTION_QEMU_SHA256))
        self.assertEqual(reader.read_absolute.call_count, 2)
        # Mocked file-reader orchestration only, never a positive QEMU/VM proof.

    def test_production_pin_and_unmatched_actual_candidate_bytes_rejected(self):
        candidate = '/HOST_TEST/qemu-candidate'
        manifest = {'backup_transport': {'binary': candidate, 'binary_sha256': v.PRODUCTION_QEMU_SHA256},
                    'files': {candidate: v.PRODUCTION_QEMU_SHA256}}
        reader = types.SimpleNamespace(read_absolute=Mock())
        with self.assertRaisesRegex(ValueError, 'selected candidate QEMU must be a0d'):
            v.check_qemu_files(reader, manifest)
        reader.read_absolute.assert_not_called()
        manifest['backup_transport']['binary_sha256'] = manifest['files'][candidate] = v.SELECTED_QEMU_SHA256
        real_reader = v.source_module('report/functional-camera-evidence/check_evidence.py', current_dependencies())
        reader = types.SimpleNamespace(read_absolute=Mock(return_value=b'HOST_TEST_wrong_executable'),
                                       digest_binding=real_reader.digest_binding)
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            v.check_qemu_files(reader, manifest)
        self.assertEqual(reader.read_absolute.call_count, 1)

    def test_typed_false_and_path_boundaries(self):
        self.assertFalse(v.profile_value_equal(False, 0))
        self.assertFalse(v.profile_value_equal([1, False], [1, 0]))
        for path in ('relative/run', '/tmp/../etc', '/'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                v.absolute(path)
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            v.object_json(b'{"ok":false,"ok":true}')
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            v.object_json(b'{"x":NaN}')


class QemuFileAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frozen = current_dependencies()
        cls.reader = v.source_module('report/functional-camera-evidence/check_evidence.py', frozen)
        cls.fixtures = v.source_module('report/functional-camera-evidence/test_evidence.py', frozen)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='HOST_TEST_graph_qemu_admission_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        native = self.root / 'native'
        runtime = native / 'runtime/analysis'
        legacy = self.reader.sha(b'HOST_TEST legacy candidate')
        candidate = self.reader.sha(b'HOST_TEST plugin-enabled candidate')
        production = self.reader.sha(b'HOST_TEST production reference')
        for patcher in (patch.multiple(self.reader, NATIVE=native, RUNTIME=runtime,
                                      QEMU_SHA256=legacy, READONLY_SCOPE_QEMU_SHA256=candidate),
                        patch.multiple(v, RUNTIME=runtime, SELECTED_QEMU_SHA256=legacy,
                                       READONLY_SCOPE_QEMU_SHA256=candidate, PRODUCTION_QEMU_SHA256=production)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.manifest, self.frozen = self.fixtures.host_test_scope_assets(self.root, self.reader)
        self.production = runtime.parent / 'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64'
        self.production.parent.mkdir(parents=True)
        self.production.write_bytes(b'HOST_TEST production reference')

    def test_readonly_candidate_consumes_shared_asset_checker_and_actual_production(self):
        result = v.check_qemu_files(self.reader, self.manifest, self.frozen)
        self.assertEqual(result['selected_candidate_sha256'], v.READONLY_SCOPE_QEMU_SHA256)
        self.assertEqual(result['unchanged_production_sha256'], v.PRODUCTION_QEMU_SHA256)
        self.assertNotEqual(result['selected_candidate_sha256'], v.SELECTED_QEMU_SHA256)
        Path(self.manifest['readonly_scope_observer']['library']).write_bytes(b'HOST_TEST substituted plugin')
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            v.check_qemu_files(self.reader, self.manifest, self.frozen)

    def test_new_candidate_needs_exact_scope_and_source_bindings(self):
        for field, value in (('profile', 'wrong'), ('qemu_sha256', v.SELECTED_QEMU_SHA256),
                             ('source_sha256', {'scope-observer.c': '0' * 64}),
                             ('capture_verified', 0), ('physical_asic_compatibility_verified', 0)):
            manifest = copy.deepcopy(self.manifest)
            manifest['readonly_scope_observer'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                v.check_qemu_files(self.reader, manifest, self.frozen)
        manifest = copy.deepcopy(self.manifest)
        del manifest['readonly_scope_observer']
        with self.assertRaises(ValueError):
            v.check_qemu_files(self.reader, manifest, self.frozen)
        manifest = copy.deepcopy(self.manifest)
        manifest['files'][manifest['readonly_scope_observer']['library']] = '0' * 64
        with self.assertRaises(ValueError):
            v.check_qemu_files(self.reader, manifest, self.frozen)
        with self.assertRaises(ValueError):
            v.check_qemu_files(self.reader, self.manifest, {})

    def test_legacy_default_pin_is_dynamic_and_scope_mixing_is_rejected(self):
        candidate = Path(self.manifest['backup_transport']['binary'])
        candidate.write_bytes(b'HOST_TEST legacy candidate')
        self.manifest['backup_transport']['binary_sha256'] = self.manifest['files'][str(candidate)] = v.SELECTED_QEMU_SHA256
        with self.assertRaises(ValueError):
            v.check_qemu_files(self.reader, self.manifest, self.frozen)
        self.manifest['readonly_scope_observer'] = None
        result = v.check_qemu_files(self.reader, self.manifest, self.frozen)
        self.assertEqual(result['selected_candidate_sha256'], v.SELECTED_QEMU_SHA256)
        self.production.write_bytes(b'HOST_TEST replaced production reference')
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            v.check_qemu_files(self.reader, self.manifest, self.frozen)

    def test_unknown_candidate_mismatched_index_and_changed_production_fail(self):
        for digest in ('f' * 64, 'arbitrary', v.PRODUCTION_QEMU_SHA256):
            manifest = copy.deepcopy(self.manifest)
            manifest['backup_transport']['binary_sha256'] = manifest['files'][manifest['backup_transport']['binary']] = digest
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                v.check_qemu_files(self.reader, manifest, self.frozen)
        manifest = copy.deepcopy(self.manifest)
        manifest['files'][manifest['backup_transport']['binary']] = v.SELECTED_QEMU_SHA256
        with self.assertRaises(ValueError):
            v.check_qemu_files(self.reader, manifest, self.frozen)
        self.production.write_bytes(b'HOST_TEST replaced production reference')
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            v.check_qemu_files(self.reader, self.manifest, self.frozen)


if __name__ == '__main__':
    unittest.main()
