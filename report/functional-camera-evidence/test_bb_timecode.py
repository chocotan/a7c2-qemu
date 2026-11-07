"""Source-only HOST_TEST fixtures; synthetic control bytes, never camera media.

The parent collector runs these with the old evidence suite. Fixtures clone
source bytes into a private indexed lab and use a sparse non-ELF identity file;
all source digests, module bounds, rows, states and lifecycles are checked by the
real reader. No helper or positive content result is mocked.
"""
import copy
import importlib.util
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location('bb_timecode_evidence_host_test',
                                               Path(__file__).with_name('check_evidence.py'))
checker = importlib.util.module_from_spec(_spec)
exec(compile(_spec.loader.get_source(_spec.name), _spec.origin, 'exec'), checker.__dict__)
helper = checker.bb_timecode_module()


def manifest_fixture():
    fields = {'functional_camera_' + key: copy.deepcopy(value) for key, value in helper.POLICY.items()}
    fields['functional_camera_profile'] = checker.PROFILE
    return dict(fields, backup_transport=copy.deepcopy(fields))


def source_manifest_fixture(root, manifest):
    native = root / 'source-lab'
    sources, files = {}, {}
    for relative in helper.DEPENDENCIES:
        path = native / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((checker.NATIVE / relative).read_bytes())
        digest = checker.sha(path.read_bytes())
        sources[str(path)] = dict(sha256=digest)
        files[str(path)] = digest
    original = native / 'runtime/analysis/menu-root/usr/lib/appFw.so'
    original.parent.mkdir(parents=True, exist_ok=True)
    if not original.exists():
        with original.open('wb') as stream:
            stream.write(b'SYNTHETIC_NON_ELF_IDENTITY_FIXTURE')
            stream.seek(0x34e56e8 + 15)
            stream.write(b'\x00')
    manifest.update(compiled_observer=dict(sources=sources), files=files, original_libraries_unchanged=True,
        selected_initramfs_verified_files={'usr/lib/appFw.so': checker.sha(original.read_bytes())})
    return manifest


def fixture(root, commands=((0x400, 1, 0x81cf61c7), (0x401, 0, 0x81cf61d1),
                            (0x402, 1, 0x81cf61c7), (0x401, 0, 0x81cf61d1)), inline=False):
    """Mutate an owner snapshot step by step; binary files supply all four logs."""
    rows, base, pid, sender, instance = [], 0x7f00000000, 77, 90, 12345
    def emit(tag, fields):
        rows.append(dict(tag=tag, fields={key: str(value) for key, value in fields.items()}, line=len(rows) + 1))
    scope = dict(pid=pid, tid=sender, original_cp_executed=0, hardware_verified=0, native_frequency_verified=0,
                 original_event_identity_verified=0, pcm_verified=0, frames_verified=0, capture_verified=0)
    emit('FULL_BB_SET_MODE_REPLY_QUEUED', dict(generation=1, destination='0x81cf61c7', source='0x92840747',
        reply='0x200000', bytes=12, raw='0d2010110c00018000000000', target=3, operation_mode=0,
        two_internal_completions=1, unique_reply=1, **scope))
    emit('FULL_BB_SET_MODE_COMMIT', dict(generation=1, request='0x100000', request_free_rc=0,
        retained_request=0, clean_completion=1, queued=1, ap_consumed=0, **scope))
    emit('FULL_BB_SET_MODE_REPLY_FREE', dict(generation=1, destination='0x81cf61c7', expected='0x81cf61c7',
        pointer='0x200000', kind='queued-reply', rc=0, faults=0, retained=0, ap_consumed=1,
        metadata_completion_only=1, **scope))
    emit('FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT', dict(event='COMMIT', transaction=1, pid=pid,
        model_instance=instance, sender_tid=sender, free_tid=sender, model_called=1, model_committed=1,
        verified=1, owned=1, complete=1, request_freed=1, oneway=1, busy=0, guard=0, guard_fault=0,
        faults=0, error=0, before_rc=0, model_rc=0, after_rc=0, validation_rc=0, free_rc=0, releasing=0,
        ACK_sent=0, notification_sent=0, requests=1, commits=1, verified_commits=1, completions=1, released=1,
        config_generation=9, before_config_generation=8, mode=0,
        frame=0, capture=0, capture_verified=0, retained_request='(nil)'))
    emit('FUNCTIONAL_CAMERA_CONTROL_COMMIT', dict(pid=pid, model_instance=instance, start_complete=1,
        mode1_complete=1, mode_complete=1, notification_AP_consumed=1, faults=0, busy=0, guard=0))
    transport = dict(verified=True, pid=pid, model_instance=instance, transfers=[],
        ou_crank_control_content=dict(verified=True, transactions=[dict(transaction=1, complete_line=4)]))
    values, mask, generations = [0, 0, 0], 0, [0, 0, 0]
    for ordinal, (command, value, source) in enumerate(commands, 1):
        index, request, reply_pointer = command - 0x400, 0x400000 + 0x1000 * ordinal, 0x800000 + 0x1000 * ordinal
        packet = struct.pack('<4H2B', 0x200d, command, 10, 0x8001, value, 0)
        before = struct.pack('<4IQ4IQ', 1, 48, pid, mask, ordinal - 1, *values, 0, ordinal - 1)
        after_values = values.copy(); after_values[index] = value
        after = struct.pack('<4IQ4IQ', 1, 48, pid, mask | 1 << index, ordinal, *after_values, 0, ordinal)
        reply = struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0)
        binaries = {}
        for kind, data in dict(request=packet, state_before=before, state_after=after, reply=reply).items():
            path = root / (str(ordinal) + '-' + kind + '.bin')
            path.write_bytes(data)
            binaries[kind] = path.read_bytes()
        audit = dict(pid=pid, tid=sender, sequence=100 + ordinal, pointer=hex(request), source=hex(source),
            destination=hex(helper.CP), command=hex(command), bytes=10, raw=binaries['request'].hex(),
            fnv1a64=f'{checker.fnv(packet):016x}', producer_return=hex(base + 0x34e56e8), appfw_base=hex(base),
            caller_raw='0x34e56e8', original_sender_bound=1, consumed=0, state_verified=0, diagnostic_only=1,
            original_CP=0, physical_ASIC_verified=0, capture_verified=0)
        emit(helper.AUDIT, audit)
        state = dict.fromkeys(helper.EVENT_ORDER, 0)
        state.update(event='BEGIN', pid=pid, tid=sender, transaction=ordinal, command=f'0x{command:04x}',
            source=f'0x{source:08x}', request_pointer=hex(request), reply_pointer='0x0', sender_tid=sender,
            receiver_tid=0, generation=ordinal - 1, known_mask=mask, tcmode=values[0], dfmode=values[1], run=values[2],
            command_generation0=generations[0], command_generation1=generations[1], command_generation2=generations[2],
            input_fnv=f'{checker.fnv(packet):016x}', state_fnv=f'{checker.fnv(before):016x}', reply_fnv='0000000000000000',
            allocate_rc=-115, send_rc=-115, request_free_rc=-115, reply_free_rc=-115, cleanup_rc=-115,
            request_free_count=ordinal - 1, reply_free_count=ordinal - 1, requests=ordinal, applications=ordinal - 1,
            initialized=1, busy=1, **helper.SCOPE)
        def event(name):
            state['event'] = name
            emit(helper.FAMILY + 'EVENT', state)
        def byte_row(kind, name):
            data = binaries[kind]
            emit(helper.FAMILY + 'BYTES', dict(event=name, kind=kind, total=len(data), offset=0, bytes=len(data),
                raw=data.hex(), whole_fnv=f'{checker.fnv(data):016x}', pid=pid, tid=sender, transaction=ordinal,
                command=f'0x{command:04x}', source=f'0x{source:08x}', request_pointer=hex(request),
                reply_pointer='0x0' if name == 'BEGIN' else hex(reply_pointer), sender_tid=sender, receiver_tid=0))
        event('BEGIN'); byte_row('request', 'BEGIN'); byte_row('state_before', 'BEGIN')
        emit(helper.FAMILY + 'RESOURCE_DEPENDENCIES', dict(pid=pid, tid=sender, accepted=1, proc_ap_consumed=1,
            input_ap_consumed=1, output_ap_consumed=1, output_faults=0, current_request_retained_expected=1, capture_verified=0))
        speech = bytearray(144)
        for slot in range(2):
            struct.pack_into('<I', speech, 0x48 * slot, 0x1a + slot)
            struct.pack_into('<2I', speech, 0x48 * slot + 0x18, 0x8400 | slot, 0x80000)
            struct.pack_into('<Q', speech, 0x48 * slot + 0x20, 0x1e000000 + slot * 0x80000)
        emit(helper.FAMILY + 'RESOURCES_TTS_TABLE', dict(pid=pid, tid=sender, appfw_base=hex(base),
            table_va='0x5f66b08', address=hex(base + 0x5f66b08), bytes=144, reads='144/144', unchanged=1,
            atomic_snapshot=0, raw_before=speech.hex(), raw_after=speech.hex(), ownership_verified=0))
        emit(helper.FAMILY + 'RESOURCES_RESERVED', dict(tid=sender, accepted=1, dmm_enabled=1, dmm_bound=1,
            dmm_slots='1/1', dmm_opens='1/1', dmm_handles='0x8400/0x8401', dmm_generations='1/1',
            dmm_epochs='1/2', dmm_creators='1/1', dmm_allocation_count=2, dmm_lifecycle_changed=0, dmm_domain=2,
            foreign_speech_kept=1, data_frozen=0, control_bound=1, control_live=0, control_faults=0, allocations=4,
            releases=4, connection_started=1, connections=1, format_pending=0, blocked=0, format_consumed=1,
            buffer_released=1, connection_reply_frees=1, connection_faults=0, vef_init=1, vef_owner='0x905a0048',
            vef_objects=16, vef_pending=0, vef_live=0, vef_retained=0, vef_faults=0, pinmem_init=1,
            pinmem_owner='0x90590818', pinmem_objects=13, pinmem_pending=0, pinmem_live=0, pinmem_retained=0,
            pinmem_faults=0, global_dmm_idle_verified=0, original_cp_executed=0, capture_verified=0))
        state.update(reply_pointer=hex(reply_pointer), allocate_rc=0, guard_held=1, generation=ordinal,
            applications=ordinal, known_mask=mask | 1 << index, tcmode=after_values[0], dfmode=after_values[1],
            run=after_values[2], retained_request=1, retained_reply=1, reply_fnv=f'{checker.fnv(reply):016x}')
        generations[index] = ordinal
        state['command_generation' + str(index)] = ordinal
        event('STATE_WRITTEN')
        state['state_fnv'] = f'{checker.fnv(after):016x}'
        event('STATE_READBACK'); byte_row('state_after', 'STATE_READBACK'); byte_row('reply', 'STATE_READBACK')
        state.update(request_free_rc=0, request_freed=1, request_free_count=ordinal, retained_request=0)
        event('REQUEST_FREE')
        state.update(live_reply=1, inflight=1)
        if not inline:
            state.update(send_rc=0, queued=1)
            event('REPLY_QUEUED')
            state.update(guard_held=0, inflight=0)
        state.update(receiver_tid=sender, reply_received=1)
        event('RECEIVE')
        state.update(reply_free_rc=0, reply_freed=1, reply_free_count=ordinal, live_reply=0,
                     retained_reply=0, pending_commit=1)
        event('REPLY_FREE')
        if inline:
            state.update(send_rc=0, queued=1)
            event('REPLY_QUEUED')
        state.update(guard_held=0, inflight=0, pending_commit=0, ap_consumed=1, busy=0)
        event('COMMIT')
        values, mask = after_values, mask | 1 << index
    return root, source_manifest_fixture(root, manifest_fixture()), rows, transport


def console(rows):
    return b''.join(('OBS ' + row['tag'] + ' ' + ' '.join(key + '=' + value for key, value in
                   row['fields'].items()) + '\r\n').encode('ascii') for row in rows)


class BbTimecodeContentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.args = list(fixture(Path(temp.name)))

    def check(self, args=None):
        run, manifest, rows, transport = args or self.args
        native = run / 'source-lab'
        public = {'usr/lib/appFw.so': manifest['selected_initramfs_verified_files']['usr/lib/appFw.so']}
        with mock.patch.multiple(checker, NATIVE=native, RUNTIME=native / 'runtime/analysis', PUBLIC_LIBRARIES=public):
            return checker.check_bb_timecode_control(run, manifest, rows, transport)

    def row(self, rows, suffix, event=None, transaction='1'):
        return next(row for row in rows if row['tag'] == helper.FAMILY + suffix and
            row['fields'].get('transaction') == transaction and
            (event is None or row['fields'].get('event') == event))

    def rejects(self, change):
        args = copy.deepcopy(self.args)
        change(args)
        with self.assertRaises((ValueError, checker.MissingEvidence)):
            self.check(args)

    def test_three_commands_two_dynamic_callers_and_same_value_reapply(self):
        result = self.check()
        self.assertTrue(result['verified'])
        self.assertIs(result['all_three_complete'], True)
        self.assertEqual(result['commands_observed'], [0x400, 0x401, 0x402])
        self.assertEqual([item['command'] for item in result['transactions']], [0x400, 0x401, 0x402, 0x401])
        self.assertEqual([item['generation'] for item in result['transactions']], [1, 2, 3, 4])
        self.assertEqual(len({item['source'] for item in result['transactions']}), 2)
        self.assertEqual(len(list(self.args[0].glob('*.bin'))), 16)
        self.assertIs(result['capture_verified'], False)
        self.assertIs(result['frame_consumed'], False)
        self.assertIs(result['physical_asic_compatibility_verified'], False)

    def test_inline_real_receive_free_before_send_returns(self):
        result = self.check(fixture(self.args[0], inline=True))
        self.assertTrue(result['verified'])
        self.assertTrue(all(item['inline_free'] for item in result['transactions']))

    def test_partial_commands_only_verify_observed_transactions(self):
        for commands in (((0x401, 0, 0x81cf61d1),), ((0x400, 1, 0x81cf61c7), (0x402, 1, 0x81cf61d1))):
            with self.subTest(commands=commands):
                result = self.check(fixture(self.args[0], commands=commands))
                self.assertIs(result['verified'], True)
                self.assertIs(result['all_three_complete'], False)
                self.assertEqual(len(result['transactions']), len(commands))
                self.assertIs(result['capture_verified'], False)

    def test_public_policy_api_exact_signature_and_profile_error(self):
        self.assertIs(checker.check_bb_timecode_policy(manifest_fixture()), True)
        self.assertIs(checker.check_bb_timecode_policy({}, observed=False), False)
        with self.assertRaisesRegex(ValueError, 'typed functional profile drift'):
            checker.check_bb_timecode_policy({}, observed=True)
        wrong = manifest_fixture()
        wrong['functional_camera_bb_timecode_control_frame_production_supported'] = 0
        with self.assertRaisesRegex(ValueError, 'typed functional profile drift'):
            checker.check_bb_timecode_policy(wrong)

    def test_exact_parser_and_public_wrapper_receive_all_needed_tags(self):
        args = list(self.args)
        args[2] = checker.parse_console(console(args[2]))
        self.assertEqual([row['tag'] for row in args[2]], [row['tag'] for row in self.args[2]])
        self.assertTrue(self.check(args)['native_completion_verified'])

    def test_old_absence_and_selected_policy_without_transactions_stay_unverified(self):
        absent = checker.check_bb_timecode_control(None, {}, [], {})
        self.assertEqual(absent['status'], 'not_observed')
        self.assertIs(absent['required'], False)
        result = helper.check(None, manifest_fixture(), [], {}, checker)
        self.assertEqual(result['status'], 'not_observed')
        self.assertIs(result['verified'], False)
        off = {'functional_camera_bb_timecode_control_policy': None, 'backup_transport': {}}
        self.assertFalse(helper.policy(off, checker))

    def test_original_audit_mutants(self):
        for key, value in (('raw', '0d2000040a0001800000'), ('fnv1a64', '0' * 16), ('source', '0x81cf61d1'),
                ('caller_raw', '0x34e56e4'), ('appfw_base', '0x7f00001000'), ('original_sender_bound', '0'),
                ('tid', '91'), ('diagnostic_only', '0')):
            with self.subTest(key=key):
                def change(args):
                    next(row for row in args[2] if row['tag'] == helper.AUDIT)['fields'][key] = value
                self.rejects(change)

    def test_complete_request_and_reply_bytes_mutants_even_with_matching_fnv(self):
        for kind, offset, value in (('request', 0, 1), ('request', 9, 1), ('request', 8, 2), ('reply', 6, 0), ('reply', 8, 1)):
            with self.subTest(kind=kind, offset=offset):
                def change(args):
                    row = next(row for row in args[2] if row['tag'] == helper.FAMILY + 'BYTES' and
                               row['fields']['kind'] == kind)
                    raw = bytearray.fromhex(row['fields']['raw']); raw[offset] = value
                    row['fields'].update(raw=raw.hex(), whole_fnv=f'{checker.fnv(raw):016x}')
                self.rejects(change)

    def test_state48_full_schema_and_history_mutants(self):
        for offset, value in ((0, 2), (4, 47), (8, 78), (12, 7), (16, 2), (28, 1), (36, 1), (40, 2)):
            with self.subTest(offset=offset):
                def change(args):
                    row = next(row for row in args[2] if row['tag'] == helper.FAMILY + 'BYTES' and
                               row['fields']['kind'] == 'state_after')
                    raw = bytearray.fromhex(row['fields']['raw']); raw[offset] = value
                    row['fields'].update(raw=raw.hex(), whole_fnv=f'{checker.fnv(raw):016x}')
                self.rejects(change)

    def test_event_identity_generation_hash_flags_and_false_capture_mutants(self):
        for event, key, value in (('BEGIN', 'pid', '78'), ('BEGIN', 'known_mask', '1'),
                ('REPLY_QUEUED', 'ap_consumed', '1'), ('REPLY_QUEUED', 'send_rc', '-5'),
                ('STATE_READBACK', 'command_generation1', '1'),
                ('STATE_READBACK', 'state_fnv', '0' * 16), ('STATE_READBACK', 'input_fnv', '0' * 16),
                ('STATE_READBACK', 'reply_fnv', '0' * 16), ('RECEIVE', 'source', '0x81cf61d1'),
                ('RECEIVE', 'receiver_tid', '91'), ('REPLY_FREE', 'reply_free_rc', '-5'),
                ('REPLY_FREE', 'live_reply', '1'), ('COMMIT', 'retained_reply', '1'),
                ('COMMIT', 'capture_verified', '1'), ('COMMIT', 'software_model', '0'), ('COMMIT', 'frames', '1')):
            with self.subTest(event=event, key=key):
                self.rejects(lambda args: self.row(args[2], 'EVENT', event)['fields'].__setitem__(key, value))

    def test_no_observe_no_actual_free_fault_or_only_tag_never_consumed(self):
        for event in ('RECEIVE', 'REPLY_FREE', 'STATE_READBACK', 'REQUEST_FREE', 'REPLY_QUEUED'):
            with self.subTest(event=event):
                def change(args):
                    args[2].remove(self.row(args[2], 'EVENT', event))
                self.rejects(change)
        self.rejects(lambda args: self.row(args[2], 'EVENT', 'COMMIT')['fields'].__setitem__('event', 'FAULT'))
        args = copy.deepcopy(self.args)
        args[2] = [self.row(args[2], 'EVENT', 'COMMIT')]
        with self.assertRaises(ValueError):
            self.check(args)

    def test_cross_transaction_borrowing_and_delayed_free_rejected(self):
        self.rejects(lambda args: self.row(args[2], 'BYTES', transaction='2')['fields'].__setitem__('transaction', '1'))
        def delayed(args):
            freed = self.row(args[2], 'EVENT', 'REQUEST_FREE')
            queued = self.row(args[2], 'EVENT', 'REPLY_QUEUED')
            freed['line'], queued['line'] = queued['line'], freed['line']
        self.rejects(delayed)
        self.rejects(lambda args: self.row(args[2], 'EVENT', 'COMMIT')['fields'].__setitem__('reply_pointer', '0x401000'))

    def test_resource37_content_not_accepted_bit_and_old_predecessor_content(self):
        for suffix, key, value in (('RESOURCES_RESERVED', 'dmm_domain', '1'),
                ('RESOURCES_RESERVED', 'vef_live', '1'), ('RESOURCES_RESERVED', 'pinmem_retained', '1'),
                ('RESOURCES_RESERVED', 'releases', '3'), ('RESOURCES_TTS_TABLE', 'raw_after', '00' * 144)):
            with self.subTest(suffix=suffix, key=key):
                self.rejects(lambda args: next(row for row in args[2] if row['tag'] == helper.FAMILY + suffix)[
                    'fields'].__setitem__(key, value))
        self.rejects(lambda args: args[2][3]['fields'].__setitem__('request_freed', '0'))
        self.rejects(lambda args: args[2][2]['fields'].__setitem__('rc', '-5'))
        self.rejects(lambda args: args[2][4]['fields'].__setitem__('mode_complete', '0'))

    def test_observed_original_input_without_owner_and_reused_free_pointer_refuse(self):
        args = copy.deepcopy(self.args)
        args[2] = [row for row in args[2] if row['tag'] == helper.AUDIT]
        with self.assertRaises(ValueError):
            self.check(args)
        def revived(args):
            replay = copy.deepcopy(self.row(args[2], 'EVENT', 'RECEIVE'))
            replay['line'] = max(row['line'] for row in args[2]) + 1
            args[2].append(replay)
        self.rejects(revived)

    def test_actual_source_index_and_module_bound_mutants(self):
        def missing_source(args):
            args[1]['compiled_observer']['sources'].pop(str(args[0] / 'source-lab' / helper.DEPENDENCIES[2]))
        self.rejects(missing_source)
        def wrong_index(args):
            args[1]['files'][str(args[0] / 'source-lab' / helper.DEPENDENCIES[0])] = '0' * 64
        self.rejects(wrong_index)
        def short_module(args):
            path = args[0] / 'source-lab/runtime/analysis/menu-root/usr/lib/appFw.so'
            with path.open('r+b') as stream:
                stream.truncate(0x34e56e8)
            args[1]['selected_initramfs_verified_files']['usr/lib/appFw.so'] = checker.sha(path.read_bytes())
        self.rejects(short_module)

    def test_metadata_exact_typed_13_keys_and_no_extension(self):
        for target in ('top', 'backup'):
            for key, value in (('bb_timecode_control_original_fifo_identity_verified', 0),
                    ('bb_timecode_control_frame_production_supported', 1),
                    ('bb_timecode_control_native_commands', [1024, True, 1026]),
                    ('bb_timecode_control_request_bytes', True), ('bb_timecode_control_physical_semantics_verified', True),
                    ('bb_timecode_control_extra', False)):
                with self.subTest(target=target, key=key):
                    def change(args):
                        dest = args[1] if target == 'top' else args[1]['backup_transport']
                        dest['functional_camera_' + key] = value
                    self.rejects(change)
        self.rejects(lambda args: args[1].pop('functional_camera_bb_timecode_control_input_policy'))

    def test_truncated_duplicate_unknown_junk_and_noncanonical_producers_rejected(self):
        native = self.row(self.args[2], 'EVENT', 'BEGIN')
        valid = console([native])
        for raw in (valid[:-2], valid.replace(b' pid=77 ', b' pid=077 '),
                    valid.replace(b' pid=77 ', b' pid=77 pid=77 '), valid.replace(b' command=0x0400 ', b' command=0x400 '),
                    valid.replace(b'FUNCTIONAL_BB_TIMECODE_EVENT', b'FUNCTIONAL_BB_TIMECODE_UNKNOWN'),
                    valid.replace(b'FUNCTIONAL_BB_TIMECODE_EVENT', b'NATIVE_BB_TIMECODE_UNKNOWN'),
                    valid.replace(b' event=BEGIN ', b' junk event=BEGIN ')):
            with self.subTest(raw=raw[:100]):
                try:
                    parsed = checker.parse_console(raw)
                except ValueError:
                    continue
                args = copy.deepcopy(self.args)
                args[2].append(dict(parsed[0], line=max(row['line'] for row in args[2]) + 1))
                with self.assertRaises(ValueError):
                    self.check(args)

    def test_both_mature_kernel_trailers_only_exact_new_producer_payloads(self):
        trailers = (b'[ 12.000001] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                    b'[ 12.000002] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1')
        for row in self.args[2]:
            if row['tag'] != helper.AUDIT and not row['tag'].startswith(helper.FAMILY):
                continue
            clean = console([row])[:-2]
            for trailer in trailers:
                with self.subTest(tag=row['tag'], trailer=trailer):
                    parsed = checker.parse_console(clean + trailer + b'\r\n')
                    self.assertEqual(parsed[0]['fields'], row['fields'])
                    self.assertIn('kernel_diagnostic', parsed[0])
        clean = console([self.row(self.args[2], 'EVENT', 'BEGIN')])[:-2]
        self.assertIsNone(checker.frame_console_kernel(clean + b'[ 1.000001] junk\r\n', 0, 1)[1])
        for bad in (b'[ 1.000001] junk', trailers[0].replace(b'-1022', b'-1021'), trailers[1] + trailers[1]):
            args = copy.deepcopy(self.args)
            parsed = checker.parse_console(clean + bad + b'\r\n')
            args[2].append(dict(parsed[0], line=max(row['line'] for row in args[2]) + 1))
            with self.assertRaises(ValueError):
                self.check(args)


    def test_legacy_bb0110_rows_remain_absent_until_timecode_input_is_observed(self):
        legacy = [row for row in self.args[2] if row['tag'].startswith('FULL_BB_SET_MODE_')]
        self.assertEqual(len(legacy), 3)
        self.assertEqual(checker.parse_console(console(legacy)), [])
        audit = next(row for row in self.args[2] if row['tag'] == helper.AUDIT)
        parsed = checker.parse_console(console(legacy + [audit]))
        self.assertEqual([row['tag'] for row in parsed], [row['tag'] for row in legacy] + [helper.AUDIT])
        self.assertEqual([row['fields'] for row in parsed], [row['fields'] for row in legacy] + [audit['fields']])
        args = copy.deepcopy(self.args)
        args[2] = parsed
        with self.assertRaises(ValueError):
            self.check(args)


class BbTimecodeSourceClosureTests(unittest.TestCase):
    def test_actual_source_digests_index_freeze_and_selected_original_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            native = Path(temp)
            api = types.SimpleNamespace(**checker.__dict__)
            api.NATIVE, api.RUNTIME = native, native / 'runtime/analysis'
            manifest = dict(compiled_observer=dict(sources={}), files={}, original_libraries_unchanged=True,
                            selected_initramfs_verified_files={})
            frozen = {}
            for relative in helper.DEPENDENCIES:
                path = native / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(('synthetic source binding fixture ' + relative).encode('ascii'))
                digest = checker.sha(path.read_bytes()); frozen[str(path)] = digest
                manifest['files'][str(path)] = digest
                manifest['compiled_observer']['sources'][str(path)] = dict(sha256=digest)
            original = api.RUNTIME / 'menu-root/usr/lib/appFw.so'
            original.parent.mkdir(parents=True)
            original.write_bytes(b'synthetic identity fixture; no ELF and no media')
            digest = checker.sha(original.read_bytes())
            api.PUBLIC_LIBRARIES = {'usr/lib/appFw.so': digest}
            manifest['selected_initramfs_verified_files']['usr/lib/appFw.so'] = digest
            self.assertEqual(helper.source_bindings(manifest, api, frozen), original.stat().st_size)
            broken = copy.deepcopy(manifest)
            broken['selected_initramfs_verified_files']['usr/lib/appFw.so'] = '0' * 64
            with self.assertRaises(ValueError):
                helper.source_bindings(broken, api, frozen)
            path = native / helper.DEPENDENCIES[2]
            path.write_bytes(path.read_bytes() + b' changed')
            with self.assertRaises(ValueError):
                helper.source_bindings(manifest, api, frozen)


if __name__ == '__main__':
    unittest.main()
