import unittest
from observe_client import parse_client, verify_peer_page


def fixture():
    return b'\n'.join((b'', b'[1.0] ATU_CLIENT_BEGIN: explicit TESTPCI',
        b'[1.1] ATU_CLIENT_MAP_RC=3 phys=c0000000 bytes=100000',
        b'[1.2] ATU_CLIENT_PEER_INITIALIZED:', b'[1.3] ATU_CLIENT_APERTURE_READ_PASS:',
        b'[1.4] ATU_CLIENT_APERTURE_WRITTEN:', b'[1.5] ATU_CLIENT_DATA_PASS:',
        b'[1.6] ATU_CLIENT_UNMAP_RC=0 slot=3', b'[1.7] ATU_CLIENT_CTRL_AFTER_UNMAP=00000000 slot=3',
        b'[1.8] ATU_CLIENT_OWNER_RELEASED:', b'[1.9] ATU_CLIENT_PASS:',
        b'OWNED_ATU_CLIENT_LOAD_RC=0', b'sony_atu_client 8192 0 - Live 0xffffff80005a0000', b''))


class ObservationTests(unittest.TestCase):
    def test_valid(self):
        result = parse_client(fixture().replace(b'\n', b'\r\n'))
        self.assertTrue(result['original_atu_client_pass'])
        self.assertFalse(result['atu_owner_uncertain'])
        self.assertEqual(result['atu_slot'], 3)

    def test_missing_retirement_retains(self):
        self.assertTrue(parse_client(b'ATU_CLIENT_BEGIN:')['atu_owner_uncertain'])
        self.assertFalse(parse_client(b'ATU_CLIENT_PASS:')['original_atu_client_pass'])

    def test_refused_allocates_nothing(self):
        result = parse_client(b'ATU_CLIENT_MAP_RC=-2 phys=0 bytes=100000\nATU_CLIENT_NOT_MAPPED:')
        self.assertFalse(result['atu_owner_uncertain'])
        self.assertFalse(result['original_atu_client_pass'])

    def test_rejected_loader_allocates_nothing(self):
        self.assertFalse(parse_client(b'\nOWNED_ATU_CLIENT_LOAD_RC=1\n')['atu_owner_uncertain'])
        self.assertTrue(parse_client(b'ATU_CLIENT_BEGIN:\nOWNED_ATU_CLIENT_LOAD_RC=1\n')['atu_owner_uncertain'])

    def test_invalid_release_retains(self):
        for old, new in ((b'UNMAP_RC=0', b'UNMAP_RC=-1'),
                         (b'UNMAP_RC=0 slot=3', b'UNMAP_RC=0 slot=2'),
                         (b'CTRL_AFTER_UNMAP=00000000', b'CTRL_AFTER_UNMAP=80000000'),
                         (b'CTRL_AFTER_UNMAP=00000000 slot=3', b'CTRL_AFTER_UNMAP=00000000 slot=1')):
            with self.subTest(new=new):
                result = parse_client(fixture().replace(old, new))
                self.assertTrue(result['atu_owner_uncertain'])
                self.assertFalse(result['original_atu_client_pass'])

    def test_data_failure_does_not_invent_pending_owner(self):
        result = parse_client(fixture()+b'\nATU_CLIENT_FAIL: corrupted bytes\n')
        self.assertFalse(result['original_atu_client_pass'])
        self.assertFalse(result['atu_owner_uncertain'])

    def test_bad_physical_or_absent_rc_not_success(self):
        for old, new in ((b'phys=c0000000', b'phys=bff00000'),
                         (b'phys=c0000000', b'phys=c0001000'),
                         (b'\nOWNED_ATU_CLIENT_LOAD_RC=0\n', b'\necho OWNED_ATU_CLIENT_LOAD_RC=$?\n'),
                         (b'ATU_CLIENT_APERTURE_WRITTEN:', b'WRITTEN_MISSING:')):
            with self.subTest(new=new):
                self.assertFalse(parse_client(fixture().replace(old, new))['original_atu_client_pass'])

    def test_peer_bytes_and_all_guards(self):
        data = bytes(((i-16)*53+0x91)&255 if 16 <= i < 272 else 0xa5 for i in range(4096))
        self.assertEqual(len(verify_peer_page(data)), 64)
        for i in (0, 16, 271, 272, 4095):
            changed = bytearray(data); changed[i] ^= 1
            with self.subTest(offset=i), self.assertRaises(ValueError):
                verify_peer_page(changed)
        for incomplete in (b'', data[:-1], data+b'\0'):
            with self.assertRaises(ValueError):
                verify_peer_page(incomplete)


if __name__ == '__main__':
    unittest.main()
