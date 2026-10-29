import unittest
from observe_dw_host import parse_host,parse_controls

GOOD=(b'\nOWNED_DW_HOST_LOAD_RC=0\nsony_dw_test_host 9192 0 - Live 0xffffff8000000000\n'
      b'[ 1.23] PCI_CORE_TEST_BUS: domain=0 bus=0 reads=33 writes=4\n'
      b'[ 1.24] PCI_CORE_TEST_ENDPOINT: id=00051b36 bar0=11000000 reads=100 writes=30\n'
      b'[ 1.25] DW_TEST_HOST_ENUM_PASS: actual kernel PCI device\n')


class HostObservation(unittest.TestCase):
    def test_actual_rows(self):
        self.assertTrue(parse_host(GOOD)['dw_test_host_enum_markers_verified'])

    def test_command_echo_does_not_load(self):
        raw=GOOD.replace(b'\nOWNED_DW_HOST_LOAD_RC=0\n',b'\n/ # echo OWNED_DW_HOST_LOAD_RC=0\n')
        self.assertFalse(parse_host(raw)['dw_test_host_enum_markers_verified'])

    def test_kernel_load_failure(self):
        self.assertFalse(parse_host(GOOD.replace(b'HOST_LOAD_RC=0',b'HOST_LOAD_RC=1'))['dw_test_host_enum_markers_verified'])

    def test_wrong_domain_identity_or_bar(self):
        for old,new in ((b'domain=0',b'domain=1'),(b'00051b36',b'00041b36'),
                        (b'11000000',b'00000000'),(b'11000000',b'11001000'),
                        (b'writes=30',b'writes=0')):
            with self.subTest(new=new):
                self.assertFalse(parse_host(GOOD.replace(old,new))['dw_test_host_enum_markers_verified'])

    def test_missing_or_duplicate_endpoint(self):
        for raw in (GOOD.replace(b'PCI_CORE_TEST_ENDPOINT:',b'NOT_AN_ENDPOINT:'),GOOD+GOOD):
            self.assertFalse(parse_host(raw)['dw_test_host_enum_markers_verified'])

    def test_actual_control_sequence_required(self):
        events=[('wrapper',0x20380,0),('dbi',0x8bc,1),('dbi',0x8bc,0),('wrapper',0x20380,0x40)]
        rows=[f"memory_region_ops_write cpu 0 mr 0x100 addr 0x{a:x} value 0x{v:x} size 4 name 'test-root-{name}'" for name,a,v in events]
        self.assertTrue(parse_controls('\n'.join(rows))[0])
        self.assertFalse(parse_controls('')[0])
        self.assertFalse(parse_controls('\n'.join(reversed(rows)))[0])
        self.assertFalse(parse_controls('\n'.join(rows[2:]))[0])

    def test_absolute_cpu_addresses(self):
        rows=[]
        for name,address,value in (('wrapper',0xf11e0380,0),('dbi',0xf70008bc,1),
                                   ('dbi',0xf70008bc,0),('wrapper',0xf11e0380,0x40)):
            rows.append(f"memory_region_ops_write cpu 0 mr 0x100 addr 0x{address:x} value 0x{value:x} size 4 name 'test-root-{name}'")
        self.assertTrue(parse_controls('\n'.join(rows))[0])
        with self.assertRaises(ValueError):parse_controls(rows[0].replace('f11e0380','e11e0380'))


if __name__=='__main__':unittest.main()
