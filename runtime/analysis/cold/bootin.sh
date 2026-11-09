#!/bin/busybox sh
[ -f /dev/qemu-simulation/init2-observed ] || { echo PRODUCT_COLD_BOOTIN_PREPARATION_MISSING; exit 78; }
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
export LD_LIBRARY_PATH=/simulation:/usr/lib:/lib
. /simulation/environment.sh || exit 1
/simulation/seed-power-on 1 || exit 1
/simulation/seed-date-clock || exit 1
/simulation/system-sound-owner || exit 1
for name in menu-load.log gpe-requests.bin; do
    /bin/busybox rm -f /tmp/$name || exit 1
    /bin/busybox ln -s /dev/null /tmp/$name || exit 1
done
/bin/busybox sh /simulation/reset-runtime.sh || exit 1
/simulation/ramfb-viewer >/dev/null 2>&1 &
echo "PRODUCT_COLD_VIEWER pid=$!"
echo "PRODUCT_COLD_BOOTIN pid=$$"
/bin/busybox cat /proc/$$/cmdline /proc/$$/status /proc/1/mountinfo /proc/cmdline
export LD_PRELOAD=/simulation/file-media-config.so:/simulation/menu-observe.so
if [ "${PRODUCT_SONY_USB_DEVICE:-}" = 1 ]; then
    export LD_PRELOAD=$LD_PRELOAD:/simulation/usb-start-observe.so
fi
exec /simulation/bootin-original 'target=qemu ' dmode=3
