"""UNEXECUTED, separate compiler group; invoke explicitly only in an authorized batch.

This file is deliberately outside pytest's default test_*/ *_test.py discovery.
It starts a real compiler and must never be counted with fake-only host tests.
"""
import usb_scheduler as scheduler
from sony_usb_device import PROFILE


def test_real_static_cross_build_when_integrated(tmp_path):
    profile = {'A7C2_USB_MSC_SCHEDULER': '1', 'A7C2_USB_MSC': '1', 'A7C2_SONY_USB_DEVICE': PROFILE}
    helpers = scheduler.prepare(profile, tmp_path)
    assert set(helpers) == {scheduler.BINARY, scheduler.RECEIPT}
    scheduler.static_aarch64(helpers[scheduler.BINARY].read_bytes())
