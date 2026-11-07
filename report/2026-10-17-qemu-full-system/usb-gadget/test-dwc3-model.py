#!/usr/bin/env python3
"""Delta safety checks; uses only temporary synthetic source trees."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

path = Path(__file__).resolve().parent.parent / 'usb-gadget-model.py'
spec = importlib.util.spec_from_file_location('dwc3_delta', path)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)


class DeltaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='sdwc-delta-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'qemu'
        for relative, text in {
            'hw/usb/meson.build': "system_ss.add(when: 'CONFIG_USB_DWC3', if_true: files('hcd-dwc3.c'))\n",
            'hw/arm/virt.c': 'unchanged board\n', 'configure': '# synthetic source\n',
        }.items():
            p = self.source / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

    def test_repeat_preserves_identity_and_board(self):
        first = model.patch(self.source, self.root)
        second = model.patch(self.source, self.root)
        self.assertEqual(first, second)
        self.assertFalse(second['physical_asic_verified'])
        self.assertFalse(second['original_driver_enumerated'])
        self.assertEqual((self.source / 'hw/arm/virt.c').read_text(), 'unchanged board\n')
        self.assertEqual((self.source / 'hw/usb/meson.build').read_text().count(model.MESON_LINE), 1)
        self.assertIn('qdev_get_gpio_in(vms->gic, 184)', model.BOARD_FRAGMENT)

    def test_unowned_model_rejected_before_any_mutation(self):
        target = self.source / 'hw/usb/sony-dwc3.h'
        target.write_text('someone else\n')
        meson = self.source / 'hw/usb/meson.build'
        before = meson.read_bytes()
        with self.assertRaises(ValueError):
            model.patch(self.source, self.root)
        self.assertEqual(meson.read_bytes(), before)
        self.assertFalse((self.source / 'hw/usb/sony-dwc3.c').exists())
        self.assertEqual(target.read_text(), 'someone else\n')

    def test_escape_and_symlink_rejected(self):
        with self.assertRaises(ValueError):
            model.patch(self.source, self.root / 'other')
        with self.assertRaises(ValueError):
            model.patch(self.source, Path('/'))
        target = self.source / 'hw/usb/sony-dwc3.c'
        outside = self.root / 'preserve'
        outside.write_text('preserve\n')
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            model.patch(self.source, self.root)
        self.assertEqual(outside.read_text(), 'preserve\n')


if __name__ == '__main__':
    unittest.main()
