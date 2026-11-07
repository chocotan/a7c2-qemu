#!/usr/bin/env python3
"""Install the functional DWC3 device into an explicitly isolated QEMU source.

This changes no board, running binary, physical USB device or host driver.
Main's board layer must instantiate sony-dwc3-gadget, map MMIO at 0xf10c0000,
and connect IRQ[0] to the original DTS GIC SPI 184. Controller VBUS alone does
not implement the original Sony PHY/clock/extcon path. See usb-gadget/BRIDGE.md.
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-functional-dwc3-device-v1'
MESON_LINE = "system_ss.add(when: 'CONFIG_USB', if_true: files('sony-dwc3.c', 'sony-dwc3-bridge.c'))\n"
OLD_MESON_LINE = "system_ss.add(when: 'CONFIG_USB', if_true: files('sony-dwc3.c'))\n"
BOARD_FRAGMENT = '''/* Instantiate only in the isolated full-system gadget profile. */
DeviceState *usb = qdev_new("sony-dwc3-gadget");
SysBusDevice *sbd = SYS_BUS_DEVICE(usb);
/* Optional explicit parent binding. The launcher must whitelist these four
 * values through bwrap --clearenv; no guessed token or getpid comparison. */
if (g_getenv("QEMU_SONY_USB_BACKEND_SOCKET")) {
    const char *run_id = g_getenv("QEMU_SONY_USB_RUN_ID");
    const char *lease = g_getenv("QEMU_SONY_USB_LEASE");
    const char *qmp_host = g_getenv("QEMU_SONY_USB_QMP_HOST_PATH");
    if (!run_id || !lease || !qmp_host) {
        error_report("DWC3 bridge requires explicit run/lease/host-QMP identity");
        exit(EXIT_FAILURE);
    }
    qdev_prop_set_string(usb, "bridge-run-id", run_id);
    qdev_prop_set_string(usb, "bridge-lease", lease);
    qdev_prop_set_string(usb, "bridge-qmp-host-path", qmp_host);
    qdev_prop_set_string(usb, "bridge-socket", g_getenv("QEMU_SONY_USB_BACKEND_SOCKET"));
}
sysbus_realize_and_unref(sbd, &error_fatal);
sysbus_connect_irq(sbd, 0, qdev_get_gpio_in(vms->gic, 184));
memory_region_add_subregion_overlap(sysmem, 0xf10c0000,
                                     sysbus_mmio_get_region(sbd, 0), 4);
/* Hold usb for sony_dwc3_qemu_core(usb); apply controller-side GPIO vbus
 * AND the original guest extcon/VBUS signal. Neither is AP mode injection. */
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def patch(source, scratch_root):
    source, scratch_root = Path(source).resolve(), Path(scratch_root).resolve()
    if not source.is_relative_to(scratch_root) or source == scratch_root:
        raise ValueError('QEMU source must be a child of the explicit scratch root')
    if scratch_root == Path('/') or scratch_root.is_relative_to(HERE):
        raise ValueError('scratch root must be a separate local experiment directory')
    for relative in ('hw/usb/meson.build', 'hw/arm/virt.c', 'configure'):
        path = source / relative
        if not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(f'not a standalone QEMU source: {relative}')
    meson = source / 'hw/usb/meson.build'
    old_meson = meson.read_bytes()
    if b"files('hcd-dwc3.c')" not in old_meson:
        raise ValueError('unrecognized QEMU USB meson layout')
    meson_text = old_meson.replace(OLD_MESON_LINE.encode(), b'')
    generated = {
        'hw/usb/sony-dwc3-bridge.c': (HERE / 'usb-gadget/sony-dwc3-bridge.c').read_bytes(),
        'hw/usb/sony-dwc3-bridge.h': (HERE / 'usb-gadget/sony-dwc3-bridge.h').read_bytes(),
        'hw/usb/sony-dwc3.c': b'#define SONY_DWC3_QEMU 1\n' +
            (HERE / 'usb-gadget/sony-dwc3.c').read_bytes(),
        'hw/usb/sony-dwc3.h': (HERE / 'usb-gadget/sony-dwc3.h').read_bytes(),
        'hw/usb/meson.build': meson_text if MESON_LINE.encode() in meson_text else
            meson_text + b'\n# Isolated full-system functional device model\n' + MESON_LINE.encode(),
    }
    receipt_path = source.parent / 'dwc3-model-delta.json'
    previous = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    prior_files = previous.get('files', {}) if previous.get('profile') == PROFILE else {}
    records = {}
    # Validate every target before writing any file; never overwrite a different model.
    for relative, data in generated.items():
        target = source / relative
        if target.is_symlink() or not target.parent.resolve().is_relative_to(source):
            raise ValueError(f'source delta target escaped isolated source: {relative}')
        before = target.read_bytes() if target.exists() else None
        prior = prior_files.get(relative, {})
        owned = before is not None and digest(before) == prior.get('after')
        if relative != 'hw/usb/meson.build' and before is not None and before != data and not owned:
            raise ValueError(f'existing model differs; use a fresh isolated source: {relative}')
        records[relative] = {'before': prior.get('before') if owned else
                             (None if before is None else digest(before)),
                             'after': digest(data)}
    for relative, data in generated.items():
        (source / relative).write_bytes(data)
    manifest = {
        'schema': 'a7c2.dwc3-model-delta.v1', 'profile': PROFILE,
        'physical_asic_verified': False, 'original_driver_enumerated': False,
        'jiritsu_authenticated': False, 'guest_root_verified': False,
        'backend_listener_implemented': True, 'board_wired': False,
        'bridge_properties': ['bridge-run-id', 'bridge-lease', 'bridge-qmp-host-path', 'bridge-socket'],
        'vbus_board_output': 'vbus-request[0] (must connect original extcon/VBUS)',
        'device_type': 'sony-dwc3-gadget', 'mmio_base': '0xf10c0000',
        'mmio_size': 65536, 'irq': {'type': 'GIC_SPI', 'number': 184},
        'guest_descriptor_template': False, 'files': records,
        'bridge_contract_sha256': digest((HERE / 'usb-gadget/BRIDGE.md').read_bytes()),
        'blockers': ['Original board/IRQ/VBUS integration and parent identity provisioning remain separate steps',
                     'Original Sony PHY, clocks, UDM and extcon/VBUS path unverified',
                     'No original Sony enumeration, authentication or guest-root evidence'],
    }
    receipt_path.write_text(json.dumps(manifest, indent=2) + '\n')
    (source.parent / 'dwc3-board-fragment.c.txt').write_text(BOARD_FRAGMENT)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='independent QEMU source copy')
    parser.add_argument('--scratch-root', required=True, type=Path,
                        help='explicit owned local experiment directory containing source')
    args = parser.parse_args()
    result = patch(args.source, args.scratch_root)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
