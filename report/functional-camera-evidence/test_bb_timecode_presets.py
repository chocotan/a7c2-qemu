"""Synthetic HOST_TEST sources only; parent runs after grouped integration.

Reuse the old lifecycle/resource fixture and real old reader. No positive
content helper or verification result is mocked. Sparse identity is not an ELF.
"""
import copy
import importlib.util
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest import mock


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    exec(compile(spec.loader.get_source(spec.name), spec.origin, 'exec'), module.__dict__)
    return module


checker = load('preset_evidence_host_test', 'check_evidence.py')
legacy = load('preset_old_tc_fixture', 'test_bb_timecode.py')
old = checker.bb_timecode_module()
helper = checker.bb_timecode_presets_module()


def fixture(root, inline=False, raw4=b'\x00\xff\x80\x13', selector=0):
    """Three real checked old TC transactions, then explicit preset golden states."""
    args = list(legacy.fixture(root, commands=((0x401, 0, 0x81cf61c7),
        (0x402, 1, 0x81cf61d1), (0x400, 1, 0x81cf61c7)), inline=inline))
    manifest, rows = args[1], args[2]
    baseline = next(row['fields'] for row in reversed(rows) if row['tag'] == old.FAMILY + 'EVENT')
    template_root = root / 'preset-template'
    template_root.mkdir(exist_ok=True)
    template = legacy.fixture(template_root, commands=((0x400, 1, 0x81cf61df),
        (0x401, 0, 0x81cf61e3)), inline=inline)[2]
    raw_word = int.from_bytes(raw4, 'little')
    states = [struct.pack('<4IQ4IQ', 1, 48, 77, 0, 0, 0, 0, 0, 0, 0),
              struct.pack('<4IQ4IQ', 1, 48, 77, 1, 1, raw_word, 0, 0, 0, 1),
              struct.pack('<4IQ4IQ', 1, 48, 77, 3, 2, raw_word, selector, 0, 0, 2)]
    for row in template:
        if row['tag'] != old.AUDIT and not row['tag'].startswith(old.FAMILY):
            continue
        f = dict(row['fields'])
        if row['tag'] == old.AUDIT or row['tag'] in (old.FAMILY + 'EVENT', old.FAMILY + 'BYTES'):
            ordinal = int(f['sequence']) - 100 if row['tag'] == old.AUDIT else int(f['transaction'])
            command = (0x40a, 0x409)[ordinal - 1]
            packet = struct.pack('<4H', 0x200d, command, (12, 10)[ordinal - 1], 0x8001) + (
                raw4 if ordinal == 1 else struct.pack('<H', selector))
            reply = struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0)
            objects = dict(request=packet, state_before=states[ordinal - 1], state_after=states[ordinal], reply=reply)
            for key in ('pointer', 'request_pointer', 'reply_pointer'):
                if key in f and int(f[key], 16):
                    f[key] = hex(int(f[key], 16) + 0x1000000)
            f['command'] = hex(command) if row['tag'] == old.AUDIT else f'0x{command:04x}'
            if row['tag'] == old.AUDIT:
                f.update(sequence=str(103 + ordinal), bytes=str(len(packet)), raw=packet.hex(),
                         fnv1a64=f'{checker.fnv(packet):016x}')
            else:
                f['transaction'] = str(3 + ordinal)
            if row['tag'] == old.FAMILY + 'BYTES':
                data = objects[f['kind']]
                f.update(total=str(len(data)), bytes=str(len(data)), raw=data.hex(), whole_fnv=f'{checker.fnv(data):016x}')
            elif row['tag'] == old.FAMILY + 'EVENT':
                name = f['event']
                current = struct.unpack('<4IQ4IQ', states[ordinal - 1 if name == 'BEGIN' else ordinal])
                f.update({key: baseline[key] for key in ('generation', 'known_mask', 'tcmode', 'dfmode', 'run',
                    'command_generation0', 'command_generation1', 'command_generation2', 'applications')})
                for key in ('requests', 'request_free_count', 'reply_free_count'):
                    f[key] = str(int(f[key]) + 3)
                provisional = reply[:8] + struct.pack('<I', 2**32 - 115)
                f.update(input_fnv=f'{checker.fnv(packet):016x}', result='-115' if name in ('BEGIN', 'STATE_WRITTEN') else '0',
                    reply_fnv='0000000000000000' if name == 'BEGIN' else
                        f'{checker.fnv(provisional if name == "STATE_WRITTEN" else reply):016x}',
                    state_fnv=f'{checker.fnv(states[ordinal - 1 if name in ("BEGIN", "STATE_WRITTEN") else ordinal]):016x}',
                    preset_generation=str(current[4]), preset_known_mask=str(current[3]),
                    preset_raw4=f'0x{current[5]:08x}', ubmode_wire=str(current[6]),
                    preset_command_generation0=str(0 if ordinal == 1 and name == 'BEGIN' else 1),
                    preset_command_generation1=str(2 if ordinal == 2 and name != 'BEGIN' else 0),
                    preset_applications=str(current[9]))
        tag = helper.AUDIT if row['tag'] == old.AUDIT else helper.FAMILY + row['tag'][len(old.FAMILY):]
        rows.append(dict(tag=tag, fields=f, line=len(rows) + 1))
    for target in (manifest, manifest['backup_transport']):
        target.update({'functional_camera_' + key: copy.deepcopy(value) for key, value in helper.POLICY.items()})
    for relative in helper.DEPENDENCIES:
        path = root / 'source-lab' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((checker.NATIVE / relative).read_bytes())
        manifest['files'][str(path)] = checker.sha(path.read_bytes())
    return args


class BbTimecodePresetsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.args = fixture(Path(temp.name))

    def check(self, args=None, validate_old=True):
        run, manifest, rows, source_transport = args or self.args
        transport = copy.deepcopy(source_transport)
        native = run / 'source-lab'
        public = {'usr/lib/appFw.so': manifest['selected_initramfs_verified_files']['usr/lib/appFw.so']}
        with mock.patch.multiple(checker, NATIVE=native, RUNTIME=native / 'runtime/analysis', PUBLIC_LIBRARIES=public):
            if validate_old:
                tc_rows = [row for row in rows if not row['tag'].startswith((helper.FAMILY, helper.AUDIT_FAMILY))]
                transport['bb_timecode_control'] = checker.check_bb_timecode_control(run, manifest, tc_rows, transport)
            return checker.check_bb_timecode_presets(run, manifest, rows, transport)

    def row(self, suffix, event=None, transaction='4', args=None, kind=None):
        return next(row for row in (args or self.args)[2] if row['tag'] == helper.FAMILY + suffix and
            row['fields'].get('transaction') == transaction and
            (event is None or row['fields'].get('event') == event) and
            (kind is None or row['fields'].get('kind') == kind))

    def rejects(self, change):
        args = copy.deepcopy(self.args)
        change(args)
        with self.assertRaises((ValueError, checker.MissingEvidence)):
            self.check(args)

    def mutate_object(self, args, kind, offset, value=None, transaction='4'):
        row = self.row('BYTES', args=args, kind=kind, transaction=transaction)
        raw = bytearray.fromhex(row['fields']['raw'])
        raw[offset] = raw[offset] ^ 1 if value is None else value
        digest = f'{checker.fnv(raw):016x}'
        row['fields'].update(raw=raw.hex(), whole_fnv=digest)
        for event in args[2]:
            if event['tag'] != helper.FAMILY + 'EVENT' or event['fields']['transaction'] != transaction:
                continue
            f, name = event['fields'], event['fields']['event']
            if kind == 'request':
                f['input_fnv'] = digest
            if kind == 'reply' and name != 'BEGIN':
                f['reply_fnv'] = digest
            if kind == 'state_before' and name in ('BEGIN', 'STATE_WRITTEN') or (
                    kind == 'state_after' and name not in ('BEGIN', 'STATE_WRITTEN')):
                f['state_fnv'] = digest
        if kind == 'request':
            audit = next(row for row in args[2] if row['tag'] == helper.AUDIT and
                         row['fields']['pointer'] == self.row('EVENT', 'BEGIN', transaction, args)['fields']['request_pointer'])
            audit['fields'].update(raw=raw.hex(), fnv1a64=digest)

    def test_two_commands_actual_three_TC_prerequisite_dynamic_sources_and_independent_state(self):
        result = self.check()
        self.assertIs(result['verified'], True)
        self.assertIs(result['all_two_complete'], True)
        self.assertEqual([tx['transaction'] for tx in result['transactions']], [4, 5])
        self.assertEqual([tx['command'] for tx in result['transactions']], [0x40a, 0x409])
        self.assertEqual([tx['preset_generation'] for tx in result['transactions']], [1, 2])
        self.assertEqual([tx['preset_known_mask'] for tx in result['transactions']], [1, 3])
        self.assertEqual(len({tx['source'] for tx in result['transactions']}), 2)
        self.assertTrue(all(tx['old_TC_generation'] == 3 for tx in result['transactions']))
        for key in ('frame_consumed', 'capture_verified', 'physical_asic_compatibility_verified',
                    'original_CP_executed', 'original_CP_RAM_verified', 'original_RTOS_verified',
                    'original_fifo_identity_verified'):
            self.assertIs(result[key], False)

    def test_preset_audit_counter_is_independent_of_three_prior_TC_audits(self):
        audits = [row for row in self.args[2] if row['tag'] == helper.AUDIT]
        for sequence, row in enumerate(audits, 1):
            row['fields']['sequence'] = str(sequence)
        result = self.check()
        self.assertIs(result['verified'], True)
        self.assertEqual([tx['source_audit_sequence'] for tx in result['transactions']], [1, 2])

    def test_inline_receive_and_free_before_send_return_preserves_partial_order(self):
        result = self.check(fixture(self.args[0], inline=True))
        self.assertIs(result['verified'], True)
        self.assertTrue(all(tx['inline_free'] for tx in result['transactions']))

    def test_all256_values_in_each_raw_byte_and_both_wire_selectors_are_legal(self):
        for value in range(256):
            with self.subTest(value=value):
                raw = bytes((value, value ^ 0xff, (value + 127) & 0xff, value ^ 0x80))
                self.assertTrue(self.check(fixture(self.args[0], raw4=raw, selector=value & 1))['verified'])

    def test_all48_state_bytes_are_checked_even_when_every_logged_hash_matches_mutant(self):
        for kind in ('state_before', 'state_after'):
            for transaction in ('4', '5'):
                for offset in range(48):
                    with self.subTest(kind=kind, transaction=transaction, offset=offset):
                        self.rejects(lambda args: self.mutate_object(args, kind, offset, transaction=transaction))

    def test_full_request_headers_and_all_reply_bytes_not_just_result_or_fnv(self):
        for transaction in ('4', '5'):
            for kind, offsets in (('request', range(8)), ('reply', range(12))):
                for offset in offsets:
                    with self.subTest(transaction=transaction, kind=kind, offset=offset):
                        self.rejects(lambda args: self.mutate_object(args, kind, offset, transaction=transaction))
        self.rejects(lambda args: self.mutate_object(args, 'request', 8, 2, transaction='5'))
        self.rejects(lambda args: self.mutate_object(args, 'request', 9, 1, transaction='5'))
        for offset in range(8, 12):
            self.rejects(lambda args: self.mutate_object(args, 'request', offset))

    def test_request12_or10_is_never_confused_with_reply12(self):
        for tag, transaction, size in ((helper.AUDIT, '4', '10'), (helper.AUDIT, '5', '12'),
                (helper.FAMILY + 'BYTES', '4', '10'), (helper.FAMILY + 'BYTES', '5', '12')):
            with self.subTest(tag=tag, transaction=transaction):
                def change(args):
                    row = next(row for row in args[2] if row['tag'] == tag and
                        (row['fields'].get('transaction') == transaction if tag != helper.AUDIT else
                         row['fields']['sequence'] == str(100 + int(transaction))) and
                        row['fields'].get('kind', 'request') == 'request')
                    row['fields']['bytes'] = size
                    if 'total' in row['fields']:
                        row['fields']['total'] = size
                self.rejects(change)

    def test_audit_SID_source_command_and_original_direct_sender_not_leaf_return(self):
        for key, value in (('destination', '0x92840748'), ('source', '0x81cf61c7'), ('command', '0x409'),
                ('caller_raw', '0x34eee18'), ('caller_raw', '0x34ef2b0'), ('producer_return', '0x7f034e56e4'),
                ('appfw_base', '0x7f00001000'), ('tid', '91'), ('original_sender_bound', '0'),
                ('consumed', '1'), ('state_verified', '1'), ('diagnostic_only', '0'), ('fnv1a64', '0' * 16)):
            with self.subTest(key=key, value=value):
                self.rejects(lambda args: next(row for row in args[2] if row['tag'] == helper.AUDIT)[
                    'fields'].__setitem__(key, value))

    def test_each_of_eight_stages_required_and_no_duplicate_reorder_or_refusal_laundering(self):
        for name in old.EVENTS:
            with self.subTest(missing=name):
                self.rejects(lambda args: args[2].remove(self.row('EVENT', name, args=args)))
            with self.subTest(duplicate=name):
                def duplicate(args):
                    row = copy.deepcopy(self.row('EVENT', name, args=args))
                    row['line'] = max(row['line'] for row in args[2]) + 1
                    args[2].append(row)
                self.rejects(duplicate)
        for name in ('REFUSED', 'FAULT'):
            self.rejects(lambda args: self.row('EVENT', 'COMMIT', args=args)['fields'].__setitem__('event', name))
        for a, b in (('STATE_WRITTEN', 'STATE_READBACK'), ('REQUEST_FREE', 'RECEIVE'), ('REPLY_FREE', 'COMMIT')):
            def reorder(args):
                first, second = self.row('EVENT', a, args=args), self.row('EVENT', b, args=args)
                first['line'], second['line'] = second['line'], first['line']
                args[2].sort(key=lambda row: row['line'])
            self.rejects(reorder)

    def test_sequence_missing_duplicate_replay_and_cross_transaction_bytes(self):
        for value in ('0', '-1', '105'):
            self.rejects(lambda args: next(row for row in args[2] if row['tag'] == helper.AUDIT)[
                'fields'].__setitem__('sequence', value))
        self.rejects(lambda args: self.row('BYTES', args=args)['fields'].__setitem__('transaction', '5'))
        self.rejects(lambda args: args[2].remove(next(row for row in args[2] if row['tag'] == helper.AUDIT)))

    def test_wrong_AP_tid_free_RC_alias_guards_and_preset_counters(self):
        for event, key, value in (('RECEIVE', 'receiver_tid', '91'), ('REPLY_FREE', 'tid', '91'),
                ('REQUEST_FREE', 'request_free_rc', '-5'), ('REPLY_FREE', 'reply_free_rc', '-5'),
                ('REPLY_QUEUED', 'send_rc', '-5'), ('STATE_WRITTEN', 'allocate_rc', '-12'),
                ('COMMIT', 'cleanup_rc', '0'), ('RECEIVE', 'guard_held', '1'),
                ('BEGIN', 'result', '0'), ('STATE_WRITTEN', 'result', '0'), ('STATE_READBACK', 'result', '-115'),
                ('BEGIN', 'source', '0x90000001'), ('BEGIN', 'command', '0x040b'),
                ('STATE_WRITTEN', 'reply_fnv', '0000000000000000'),
                ('COMMIT', 'preset_generation', '4'), ('COMMIT', 'generation', '4'),
                ('COMMIT', 'applications', '4'), ('COMMIT', 'preset_applications', '4'),
                ('COMMIT', 'preset_command_generation1', '1'), ('BEGIN', 'preset_known_mask', '7'),
                ('BEGIN', 'preset_generation', '3'), ('BEGIN', 'preset_raw4', '0x00000001'),
                ('BEGIN', 'ubmode_wire', '1'), ('COMMIT', 'retained_reply', '1'), ('COMMIT', 'ap_consumed', '0')):
            with self.subTest(event=event, key=key):
                self.rejects(lambda args: self.row('EVENT', event, args=args)['fields'].__setitem__(key, value))
        def alias(args):
            request = int(self.row('EVENT', 'BEGIN', args=args)['fields']['request_pointer'], 16)
            for row in args[2]:
                if row['tag'] in (helper.FAMILY + 'EVENT', helper.FAMILY + 'BYTES') and row['fields']['transaction'] == '4':
                    if row['fields']['reply_pointer'] != '0x0':
                        row['fields']['reply_pointer'] = hex(request + 8)
        self.rejects(alias)

    def test_scope_bits_bool_ranges_and_software_model_cannot_promote_physical_or_media(self):
        for key in old.SCOPE:
            value = '1' if old.SCOPE[key] == '0' else '0'
            self.rejects(lambda args: self.row('EVENT', 'COMMIT', args=args)['fields'].__setitem__(key, value))
        for key, value in (('busy', '2'), ('preset_known_mask', str(2**32)), ('ubmode_wire', str(2**32)),
                           ('preset_generation', str(2**64)), ('preset_raw4', '0x1')):
            self.rejects(lambda args: self.row('EVENT', 'COMMIT', args=args)['fields'].__setitem__(key, value))

    def test_typed_actual_resources_all_three_tags_required_no_borrowing_from_old_TC(self):
        for suffix in old.RESOURCE_SUFFIXES:
            self.rejects(lambda args: args[2].remove(next(row for row in args[2] if row['tag'] == helper.FAMILY + suffix)))
        for suffix, key, value in (('RESOURCE_DEPENDENCIES', 'accepted', '0'),
                ('RESOURCE_DEPENDENCIES', 'output_faults', '1'), ('RESOURCES_TTS_TABLE', 'raw_after', '00' * 144),
                ('RESOURCES_TTS_TABLE', 'ownership_verified', '1'), ('RESOURCES_RESERVED', 'dmm_domain', '1'),
                ('RESOURCES_RESERVED', 'data_frozen', '1'), ('RESOURCES_RESERVED', 'vef_live', '1'),
                ('RESOURCES_RESERVED', 'pinmem_retained', '1'), ('RESOURCES_RESERVED', 'control_faults', '1'),
                ('RESOURCES_RESERVED', 'releases', '3'), ('RESOURCES_RESERVED', 'accepted', '2')):
            with self.subTest(suffix=suffix, key=key):
                self.rejects(lambda args: next(row for row in args[2] if row['tag'] == helper.FAMILY + suffix)[
                    'fields'].__setitem__(key, value))
        def orphan(args):
            row = copy.deepcopy(next(row for row in args[2] if row['tag'] == helper.FAMILY + old.RESOURCE_SUFFIXES[0]))
            row['line'] = max(row['line'] for row in args[2]) + 1
            args[2].append(row)
        self.rejects(orphan)
        def duplicate(args):
            row = copy.deepcopy(next(row for row in args[2] if row['tag'] == helper.FAMILY + old.RESOURCE_SUFFIXES[0]))
            index = args[2].index(next(item for item in args[2] if item['tag'] == helper.FAMILY + 'RESOURCES_TTS_TABLE'))
            args[2].insert(index, row)
            for number, item in enumerate(args[2], 1):
                item['line'] = number
        self.rejects(duplicate)

    def test_0409_first_is_refused_even_with_coherent_empty_and_written_preset_states(self):
        def change(args):
            before = struct.pack('<4IQ4IQ', 1, 48, 77, 0, 0, 0, 0, 0, 0, 0)
            after = struct.pack('<4IQ4IQ', 1, 48, 77, 2, 1, 0, 1, 0, 0, 1)
            packet = bytes.fromhex('0d2009040a0001800100')
            reply = bytes.fromhex('0d2009140c00018000000000')
            provisional = reply[:8] + struct.pack('<I', 2**32 - 115)
            for row in args[2]:
                f = row['fields']
                if row['tag'] == helper.AUDIT and f['sequence'] == '104':
                    f.update(command='0x409', bytes='10', raw=packet.hex(), fnv1a64=f'{checker.fnv(packet):016x}')
                elif row['tag'] in (helper.FAMILY + 'EVENT', helper.FAMILY + 'BYTES') and f['transaction'] == '4':
                    f['command'] = '0x0409'
                    if row['tag'] == helper.FAMILY + 'BYTES':
                        data = dict(request=packet, state_before=before, state_after=after, reply=reply)[f['kind']]
                        f.update(total=str(len(data)), bytes=str(len(data)), raw=data.hex(), whole_fnv=f'{checker.fnv(data):016x}')
                    else:
                        name = f['event']
                        f.update(input_fnv=f'{checker.fnv(packet):016x}', preset_raw4='0x00000000',
                            preset_known_mask='0' if name == 'BEGIN' else '2', ubmode_wire='0' if name == 'BEGIN' else '1',
                            preset_command_generation0='0', preset_command_generation1='0' if name == 'BEGIN' else '1',
                            state_fnv=f'{checker.fnv(before if name in ("BEGIN", "STATE_WRITTEN") else after):016x}',
                            reply_fnv='0000000000000000' if name == 'BEGIN' else
                                f'{checker.fnv(provisional if name == "STATE_WRITTEN" else reply):016x}')
        self.rejects(change)

    def test_old_TC_precondition_failures_are_kept_and_new_tags_never_enter_old_receipt_census(self):
        self.assertTrue(self.check()['verified'])
        self.rejects(lambda args: args[2].remove(next(row for row in args[2] if row['tag'] == old.FAMILY + 'EVENT' and
            row['fields']['event'] == 'COMMIT' and row['fields']['command'] == '0x0402')))
        def old_refused(args):
            row = copy.deepcopy(next(row for row in args[2] if row['tag'] == old.FAMILY + 'EVENT'))
            row['fields'].update(event='REFUSED', tid='262', rc='-114')
            row['line'] = max(row['line'] for row in args[2]) + 1
            args[2].append(row)
        self.rejects(old_refused)
        with self.assertRaises(ValueError):
            self.check(validate_old=False)
        args = copy.deepcopy(self.args)
        args[3]['bb_timecode_control'] = dict(verified=False, all_three_complete=True, transactions=[])
        with self.assertRaises(ValueError):
            self.check(args, validate_old=False)
        args = copy.deepcopy(self.args)
        args[2] = [row for row in args[2] if not (row['tag'].startswith((helper.FAMILY, helper.AUDIT_FAMILY)) and
            row['fields'].get('transaction', '4' if row['fields'].get('sequence') == '104' else '5') == '4')]
        with self.assertRaises(ValueError):
            self.check(args)

    def test_true_old_TC_state_cannot_be_used_as_preset_initial_state(self):
        def borrow(args):
            old_after = next(row['fields']['raw'] for row in reversed(args[2]) if row['tag'] == old.FAMILY + 'BYTES' and
                             row['fields']['kind'] == 'state_after')
            row = self.row('BYTES', args=args, kind='state_before')
            row['fields'].update(raw=old_after, whole_fnv=f'{checker.fnv(bytes.fromhex(old_after)):016x}')
        self.rejects(borrow)

    def test_absence_selected_none_and_exact_typed_profile(self):
        self.assertIs(checker.check_bb_timecode_presets(None, {}, [], {})['verified'], False)
        self.assertIs(checker.check_bb_timecode_presets_policy({}), False)
        self.assertIs(helper.policy({'functional_camera_bb_timecode_preset_policy': None}, checker), False)
        for dest in ('top', 'backup'):
            for key, value in (('frame_production_supported', 0), ('physical_semantics_verified', True),
                    ('native_commands', [1034, True]), ('request_sizes', {'0x040a': 12, '0x0409': True}),
                    ('native_CP_verified', True), ('state_bytes', True), ('extra', False)):
                def change(args):
                    target = args[1] if dest == 'top' else args[1]['backup_transport']
                    target['functional_camera_bb_timecode_preset_' + key] = value
                self.rejects(change)

    def test_source_reader_dependencies_index_and_frozen_closure(self):
        native = self.args[0] / 'source-lab'
        api = types.SimpleNamespace(**checker.__dict__)
        api.NATIVE, api.RUNTIME = native, native / 'runtime/analysis'
        api.PUBLIC_LIBRARIES = {'usr/lib/appFw.so': self.args[1]['selected_initramfs_verified_files']['usr/lib/appFw.so']}
        frozen = {str(native / relative): checker.sha((native / relative).read_bytes())
                  for relative in old.DEPENDENCIES + helper.DEPENDENCIES}
        self.assertGreater(helper.source_bindings(self.args[1], api, frozen), 0x34e56e8)
        for relative in helper.DEPENDENCIES:
            with self.subTest(relative=relative):
                args = copy.deepcopy(self.args)
                args[1]['files'].pop(str(native / relative))
                with self.assertRaises(ValueError):
                    helper.source_bindings(args[1], api, frozen)
                wrong = dict(frozen); wrong.pop(str(native / relative))
                with self.assertRaises(ValueError):
                    helper.source_bindings(self.args[1], api, wrong)

    def test_parser_requires_exact_complete_new_grammar_and_correct_namespace(self):
        self.assertEqual(len(old.AUDIT_ORDER), 20)
        self.assertEqual(len(old.EVENT_ORDER) + len(helper.PRESET_ORDER), 66)
        self.assertEqual(len(old.BYTES_ORDER), 16)
        parsed = checker.parse_console(legacy.console(self.args[2]))
        self.assertEqual([row['tag'] for row in parsed], [row['tag'] for row in self.args[2]])
        args = copy.deepcopy(self.args); args[2] = parsed
        self.assertTrue(self.check(args)['verified'])
        payload = legacy.console([self.row('EVENT', 'BEGIN')])
        for raw in (payload.replace(b' preset_raw4=0x00000000', b' preset_raw4=0x0'),
                payload.replace(b' preset_generation=0', b''), payload.replace(b' pid=77 ', b' pid=077 '),
                payload.replace(b'PRESET_EVENT', b'PRESET_UNKNOWN'), payload.replace(b' event=BEGIN ', b' junk event=BEGIN ')):
            with self.subTest(raw=raw[:100]):
                records = checker.parse_console(raw)
                self.assertTrue(records and 'diagnostic' in records[0])
                self.assertEqual(records[0]['fields'], {})
        with self.assertRaises(ValueError):
            checker.parse_console(payload[:-2])
        with self.assertRaises(ValueError):
            checker.parse_console(payload.replace(b' pid=77 ', b' pid=77 pid=77 '))

    def test_preset_input_preserves_BB0110_context_but_legacy_absence_stays_absent(self):
        legacy_rows = [row for row in self.args[2] if row['tag'].startswith('FULL_BB_SET_MODE_')]
        self.assertEqual(checker.parse_console(legacy.console(legacy_rows)), [])
        audit = next(row for row in self.args[2] if row['tag'] == helper.AUDIT)
        parsed = checker.parse_console(legacy.console(legacy_rows + [audit]))
        self.assertEqual([row['tag'] for row in parsed], [row['tag'] for row in legacy_rows] + [helper.AUDIT])

    def test_only_mature_exact_kernel_trailers_frame_complete_new_producers(self):
        trailers = (b'[ 12.000001] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                    b'[ 12.000002] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1')
        for row in self.args[2]:
            if not row['tag'].startswith((helper.FAMILY, helper.AUDIT_FAMILY)):
                continue
            clean = legacy.console([row])[:-2]
            for trailer in trailers:
                parsed = checker.parse_console(clean + trailer + b'\r\n')
                self.assertEqual(parsed[0]['fields'], row['fields'])
                self.assertIn('kernel_diagnostic', parsed[0])
        clean = legacy.console([self.row('EVENT', 'BEGIN')])[:-2]
        for trailer in (b'[ 1.000001] junk', trailers[0].replace(b'-1022', b'-1021'), trailers[1] + trailers[1]):
            self.assertIsNone(checker.frame_console_kernel(clean[4:] + trailer + b'\r\n', 0, 1)[1])


if __name__ == '__main__':
    unittest.main()
