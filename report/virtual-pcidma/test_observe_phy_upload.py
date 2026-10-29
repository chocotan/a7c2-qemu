import unittest
from observe_phy_upload import invalid_phy_access,model_mappings_verified,MAPPINGS

class AccessEvidence(unittest.TestCase):
    def test_validation_rejection_outside_callback(self):
        for reason in ('unaligned','invalid size (min:4 max:4)','rejected'):
            self.assertTrue(invalid_phy_access("Invalid write at addr 0x1, size 2, region 'test-phy-init-region7', reason: "+reason))
        self.assertFalse(invalid_phy_access("Invalid read at addr 0x1, size 2, region 'other-test', reason: unaligned"))

    def tree(self,ram=False,extra=False):
        lines=['FlatView #0',' AS "cpu-memory-0", root: system',' Root memory region: system']
        for address,index in MAPPINGS:
            kind,name=('ram','mach-virt.ram') if ram and index==0 else ('i/o','test-phy-init-region'+str(index))
            lines.append(f'  {address:016x}-{address:016x} (prio 4, {kind}): {name}')
        if extra:lines.append(lines[-1])
        return '\n'.join(lines)

    def test_explicit_cpu_flatview(self):self.assertTrue(model_mappings_verified(self.tree()))
    def test_ram_zero_is_not_device(self):self.assertFalse(model_mappings_verified(self.tree(ram=True)))
    def test_ambiguous_flatview_rejected(self):self.assertFalse(model_mappings_verified(self.tree(extra=True)))
    def test_wrong_address_space_rejected(self):self.assertFalse(model_mappings_verified(self.tree().replace('cpu-memory-0','pci-memory')))

if __name__=='__main__':unittest.main()
