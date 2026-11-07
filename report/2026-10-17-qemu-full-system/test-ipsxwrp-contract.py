#!/usr/bin/env python3
"""Lock in the disassembly-verified IPSXWRP contract.

These tests exist because two earlier readings were wrong in ways that would
silently produce a non-working controller model:
  * the window size was read as 0x3000 by splitting a `mov`/`movk` pair, and
  * the MMC channel window was confused with the SCU window.

They assert on real instruction encodings from the official module, so a
different module revision fails loudly instead of shifting every offset.
"""
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
MODULE = PROJECT / 'analysis/qemu-runtime/analysis/menu-root/usr/kmod/mmc_drv.ko'
MODULE_SHA = 'ba2844709411cefa95cf6c8baa77e68b0682e5ba84e79e126b0208db70b5a45c'
OTHER_SHA = 'e5f1a463e5f6d7ac6679d4001ca40d7a5a983bd0082f6f597f64154938238454'
PLATFORM_H = PROJECT / 'sources/sony-ilce7cm2-ver201/extracted/linux-kernel/drivers/udif/mach-cxd900xx/include/mach/platform.h'
PLATFORM_C = PROJECT / 'sources/sony-ilce7cm2-ver201/extracted/linux-kernel/drivers/udif/mach-cxd900xx/platform.c'
MCMN = PROJECT / 'analysis/qemu-runtime/analysis/menu-root/usr/kmod/mcmn_drv.ko'
MCMN_SHA = 'dd1106edc77fb05b49ab0b7b8c27e6c2790880415c8915c816aec945f374ad63'


def sha256(path):
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def objdump(*args):
    return subprocess.run(['aarch64-linux-gnu-objdump', *args], capture_output=True, text=True).stdout


class ContractModule(unittest.TestCase):
    def setUp(self):
        if not MODULE.is_file(): self.skipTest('official mmc_drv.ko not present')
        if not shutil.which('aarch64-linux-gnu-objdump'): self.skipTest('objdump unavailable')

    def test_official_module_hash_is_the_analysed_one(self):
        self.assertEqual(sha256(MODULE), MODULE_SHA)
        self.assertNotEqual(MODULE_SHA, OTHER_SHA)

    def test_ipsxwrp_window_is_scu_with_size_0x33000(self):
        """0x3000 was a misread of `mov x2,#0x3000` + `movk x2,#3,lsl#16`."""
        text = objdump('-d', '--start-address=0x2fa88', '--stop-address=0x2fb18', str(MODULE))
        self.assertIn('mov\tx2, #0x3000', text)
        self.assertIn('movk\tx2, #0x3, lsl #16', text)
        self.assertIn('movk\tx3, #0xf138, lsl #16', text)
        self.assertIn('movk\tx1, #0xf138, lsl #16', text)
        self.assertIn('mov\tx1, #0x30000', text)   # MIRA ES version register offset

    def test_scu_is_the_window_base_and_holds_clken_and_reset(self):
        if not PLATFORM_H.is_file(): self.skipTest('GPL platform.h not present')
        text = PLATFORM_H.read_text()
        self.assertIn('#define CXD900XX_SCU\t\tUL(0xf1388000)', text)
        self.assertIn('CXD900XX_CLKEN(ch)', text)
        self.assertIn('CXD900XX_RESET(ch)', text)

    def test_mmc_channel_windows_are_platform_devices_not_pci(self):
        if not PLATFORM_C.is_file(): self.skipTest('GPL platform.c not present')
        text = PLATFORM_C.read_text()
        for value in ('MMC_SDIF0_IO_BASE\t0xF10D2000U', 'MMC_SDIF1_IO_BASE\t0xF10D4000U',
                      'MMC_SDIF0_IO_SIZE\t0x00002000U'):
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertIn('UDIF_ID_MMC', text)

    def test_transfer_registers_have_the_verified_widths(self):
        """+0x00 block count W32, +0x04 block size W16, +0x58/+0x5c table PA W32."""
        text = objdump('-dr', '--start-address=0x28bb0', '--stop-address=0x28d30', str(MODULE))
        self.assertIn('and\tw2, w21, #0xfff', text)          # block size mask
        self.assertIn('mmc_os_write16', text)
        self.assertIn('mmc_os_write32', text)
        for offset in ('#0x0', '#0x4', '#0xc', '#0x58', '#0x5c'):
            with self.subTest(offset=offset):
                self.assertIn('mov\tx1, ' + offset, text)
        self.assertIn('lsr\tx2, x20, #32', text)             # table PA high half
        for address,offset,callee in ((0x28cd8,'#0x4','mmc_os_write16'),
                                     (0x28ce8,'#0x0','mmc_os_write32'),
                                     (0x28cf8,'#0x58','mmc_os_write32'),
                                     (0x28d08,'#0x5c','mmc_os_write32'),
                                     (0x28d18,'#0xc','mmc_os_write16')):
            with self.subTest(address=hex(address)):
                self.assertRegex(text,rf'{address:x}:[^\n]*mov\tx1, {re.escape(offset)}[^\n]*\n'
                                     rf'\s*{address+4:x}:[^\n]*bl[^\n]*<{callee}>')

    def test_ops_info_has_five_groups_and_writes_scu_masks(self):
        text = objdump('-d', '--start-address=0x2f9b8', '--stop-address=0x2fa88', str(MODULE))
        for offset in ('#0x20', '#0x148', '#0x198', '#0x1a8', '#0x1b8'):
            with self.subTest(offset=offset):
                self.assertRegex(text,r'add\tx\d+, x2, '+re.escape(offset)+r'\s')
        self.assertIn('str\tx2, [x1, #32]', text)            # fifth ops pointer
        self.assertIn('mov\tx1, #0x308', text)               # SCU RESET(0) area
        self.assertIn('mov\tx1, #0x4', text)                 # SCU CLKEN(0) area

    def test_descriptor_builder_writes_the_verified_layout(self):
        text = objdump('-d', '--start-address=0x2d940', '--stop-address=0x2d9e4', str(MODULE))
        for instruction in ('mov\tw19, #0x21','str\tw2, [x0, #4]',
                            'str\tw2, [x0, #8]','str\twzr, [x2, #12]',
                            'orr\tw0, w19, w0, lsl #16','lsl\tx0, x0, #4',
                            'orr\tw1, w1, #0x2'):
            with self.subTest(instruction=instruction):self.assertIn(instruction,text)

    def test_standard_mount_opens_hardware_before_requesting_power(self):
        """Power must not be reported as configured before the hardware open and
        the stability check have both succeeded."""
        text = objdump('-dr', '--start-address=0x720', '--stop-address=0x7d0', str(MODULE))
        order = ['do_mmc_hw_open', 'mmc_trc_open', 'mmc_hw_wrapper_wait_card_state_stable',
                 'mmc_hw_wrapper_set_max_volt', 'mmc_hw_wrapper_supply_bus_power',
                 'mmc_hwconf_get_wait_pon']
        positions = []
        for callee in order:
            marker = '<' + callee + '>'
            self.assertIn(marker, text)
            positions.append(text.index(marker))
        self.assertEqual(positions, sorted(positions), 'mount call order changed')

    def test_media_power_gate_requires_detect_result_three(self):
        if not MCMN.is_file(): self.skipTest('official mcmn_drv.ko not present')
        self.assertEqual(sha256(MCMN), MCMN_SHA)
        text = objdump('-dr', '--start-address=0x12b90', '--stop-address=0x12c00', str(MCMN))
        self.assertIn('sub\tw0, w19, #0x20', text)
        self.assertIn('cmp\tw0, #0x2', text)
        self.assertIn('cmp\tw4, #0x3', text)
        self.assertIn('b.eq\t12b54', text)

    def test_sd_card_path_doc_records_the_corrected_size(self):
        doc = (HERE / 'SD-CARD-PATH.md').read_text()
        self.assertIn('0x33000', doc)
        self.assertIn('勘误', doc)
        self.assertIn('CXD900XX_SCU', doc)

    def test_contract_doc_does_not_claim_a_pci_backend(self):
        doc = (HERE / 'IPSXWRP-CONTRACT.md').read_text()
        self.assertIn('IPSXWRP 是唯一相关后端', doc)
        self.assertIn('0x33000', doc)
        self.assertIn('SCU', doc)


if __name__ == '__main__':
    unittest.main()
