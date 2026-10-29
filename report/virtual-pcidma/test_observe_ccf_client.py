import unittest
from observe_ccf_client import actual_rows,EXPECTED


class ClockRows(unittest.TestCase):
    def test_real_kernel_rows(self):
        raw=b'\r\n'.join(f'[   70.123] NATIVE_CCF_CLOCK: id={ident} rate={rate} before=0 enabled=1 after=0'.encode() for ident,rate in EXPECTED)
        self.assertEqual(actual_rows(raw),[(i,r,0,1,0) for i,r in EXPECTED])

    def test_echo_rejected(self):
        raw=b'/ # echo NATIVE_CCF_CLOCK: id=62 rate=99000000 before=0 enabled=1 after=0\n'
        self.assertEqual(actual_rows(raw),[])

    def test_wrong_hardware_effect_is_not_expected(self):
        row=b'NATIVE_CCF_CLOCK: id=62 rate=99000000 before=0 enabled=0 after=0\n'
        self.assertNotEqual(actual_rows(row),[(62,99000000,0,1,0)])


if __name__=='__main__':unittest.main()
