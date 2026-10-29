import unittest
from observe_native_init import installed_irqs,IRQS,observe,scu_sequence_verified,SCU_BASES
from types import SimpleNamespace


class ActualIRQs(unittest.TestCase):
    def test_all_real_rows(self):
        raw=b'\n'.join(f'{irq}: 0 GIC-0 {irq} Level PCIeDMAC'.encode() for irq in IRQS)
        self.assertEqual(installed_irqs(raw),list(IRQS))

    def test_echo_or_wrong_handler_rejected(self):
        self.assertEqual(installed_irqs(b'echo 198: 0 GIC-0 198 Level PCIeDMAC\n198: 0 GIC-0 198 Level other\n'),[])

    def test_wrong_hardware_irq_rejected(self):
        self.assertEqual(installed_irqs(b'198: 0 GIC-0 166 Level PCIeDMAC\n'),[])

    def test_warning_or_fault_refuses_before_observation(self):
        for raw in (b'WARNING: CPU: 0 at fs/proc/generic.c\n',b'Kernel panic\n',b'BUG: bad state\n'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                observe(None,None,None,None,SimpleNamespace(read_bytes=lambda:raw),{})

    def test_actual_scu_order_required(self):
        rows=[]
        for i,(hbit,rbit) in enumerate(zip((1,7,13,19,25),(3,11,7,15,19))):
            for address,value,region in ((0xf1388084,1<<hbit,0),(0xf1388318,1<<rbit,1),
                    (SCU_BASES[i+2],0x10,i+2),(0xf1388088,1<<hbit,0)):
                rows.append(f"memory_region_ops_write cpu 0 mr 0x100 addr 0x{address:x} value 0x{value:x} size 4 name 'test-pcie-scu-region{region}'")
        self.assertTrue(scu_sequence_verified('\n'.join(rows)))
        self.assertFalse(scu_sequence_verified('\n'.join(reversed(rows))))
        self.assertFalse(scu_sequence_verified('\n'.join(rows[:-1])))


if __name__=='__main__':unittest.main()
