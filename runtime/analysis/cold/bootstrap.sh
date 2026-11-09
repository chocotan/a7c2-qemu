#!/bin/busybox sh
# Virtual devices are prepared here; the original Sony init owns the root handoff.
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
fail() { echo "PRODUCT_COLD_FAILED stage=$1"; exec /bin/busybox sh </dev/console >/dev/console 2>&1; }
[ "$$" = 1 ] || fail pid1
/bin/busybox mount -t proc proc /proc || fail proc
case " $(/bin/busybox cat /proc/cmdline) " in
    *" product.cold=original-init-v1 "*) ;;
    *) fail profile;;
esac
/bin/busybox mount -t sysfs sysfs /sys || fail sysfs
/bin/busybox grep -q ' /dev .* - devtmpfs ' /proc/self/mountinfo || /bin/busybox mount -t devtmpfs devtmpfs /dev || fail devtmpfs
[ ! -e /dev/qemu-simulation ] || fail simulation-exists
/bin/busybox mount -o remount,size=536870912 devtmpfs /dev || fail ram-capacity
read -r helper_bytes < /qemu/helper-bytes || fail ram-budget
/qemu/audit space /dev "$helper_bytes" || fail ram-space
/bin/busybox mkdir -m 700 /dev/qemu-simulation || fail simulation-directory
while read -r relative bytes digest mode; do
    parent=${relative%/*}
    [ "$parent" = "$relative" ] || /bin/busybox mkdir -p "/dev/qemu-simulation/$parent" || fail directory
    /qemu/audit copy "/qemu/simulation/$relative" "/dev/qemu-simulation/$relative" "$bytes" "$digest" "$mode" || fail helper-content
done < /qemu/helpers
/bin/busybox insmod /qemu/sony_persistent_flash.ko mmio_base=0x0b010000 || fail flash-module
while read -r node sectors; do
    dev=$(/bin/busybox cat "/sys/block/$node/dev") || fail device-number
    major=${dev%:*}; minor=${dev#*:}
    [ -b "/dev/$node" ] || /bin/busybox mknod "/dev/$node" b "$major" "$minor" || fail device-node
    actual=$(/bin/busybox cat "/sys/block/$node/size") || fail capacity-read
    [ "$actual" = "$sectors" ] || fail capacity
    echo "PRODUCT_COLD_CAPACITY node=$node sectors=$actual"
done < /qemu/capacities
/bin/busybox cat /proc/cmdline /proc/1/status /proc/1/mountinfo
/bin/busybox umount /sys || fail sysfs-release
/bin/busybox umount /proc || fail proc-release
echo PRODUCT_COLD_BEFORE_ORIGINAL_INIT
exec /bin/busybox sh -x /sbin/init
