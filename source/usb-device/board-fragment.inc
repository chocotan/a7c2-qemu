/* Instantiate only in the isolated full-system gadget profile. */
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
sony_usb_platform_create(sysmem, usb, vms->gic);
/* Hold usb for sony_dwc3_qemu_core(usb); apply controller-side GPIO vbus
 * AND the original guest extcon/VBUS signal. Neither is AP mode injection. */
