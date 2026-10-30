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


if __name__ == '__main__':
    unittest.main()
