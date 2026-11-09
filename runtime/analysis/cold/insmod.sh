#!/bin/busybox sh
module=$1
name=${module##*/}; name=${name%.ko}
shift
case "$module" in
    /usr/kmod/*)
        if [ ! -e /dev/qemu-simulation/init2-observed ]; then
            [ ! -e /dev/qemu-simulation/init2-attempted ] || { echo PRODUCT_COLD_INIT2_PREVIOUS_ATTEMPT_FAILED; exit 78; }
            /bin/busybox touch /dev/qemu-simulation/init2-attempted || exit 1
            echo "PRODUCT_COLD_INIT2 parent=$PPID"
            /bin/busybox cat /proc/$PPID/cmdline /proc/$PPID/status /proc/1/mountinfo
            /bin/busybox mkdir -p /tmp/images /log/qemu || exit 1
            /simulation/persistent-apply-test || exit 78
            /simulation/install-settings.sh || exit 79
            /usr/bin/openssl dgst -sha256 /sbin/init2 /sbin/initrc/setup_rootfs /usr/bin/bootin.elf /usr/bin/im.elf /usr/lib/appFw.so || exit 1
            /bin/busybox sh /simulation/verify-originals.sh || exit 78
            digest=$(/usr/bin/openssl dgst -sha256 /usr/bin/bootin.elf) || exit 1
            case "$digest" in
                'SHA256(/usr/bin/bootin.elf)= dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2'|'SHA2-256(/usr/bin/bootin.elf)= dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2') ;;
                *) echo PRODUCT_COLD_ORIGINAL_BOOTIN_IDENTITY_FAILED; exit 78;;
            esac
            /bin/busybox mount --bind /usr/bin/bootin.elf /simulation/bootin-original || exit 1
            /bin/busybox mount --bind /simulation/bootin-wrapper /usr/bin/bootin.elf || exit 1
            /simulation/audit space /tmp 2097152 || exit 1
            . /simulation/environment.sh || exit 1
            if [ "${PRODUCT_USB_MSC:-}" = 1 ]; then
                /bin/busybox mount --bind /simulation/libIMDB-msc.so /usr/lib/libIMDB.so || exit 1
                echo "[cold] MSC libIMDB restores only UsbCmn/UsbControl init" >&2
            else
                /bin/busybox mount --bind /simulation/libIMDB.so /usr/lib/libIMDB.so || exit 1
            fi
            /bin/busybox mount --bind /simulation/start-bt-virtual.sh /usr/bin/startBTCore.sh || exit 1
            if [ "${PRODUCT_USB_SENSER:-}" = original-init2-v1 ]; then
                read -r expected < /simulation/sen-sha256 || exit 78
                digest=$(/usr/bin/openssl dgst -sha256 /usr/bin/sen.elf) || exit 78
                case "$digest" in "SHA256(/usr/bin/sen.elf)= $expected"|"SHA2-256(/usr/bin/sen.elf)= $expected") ;; *) exit 78;; esac
                /bin/busybox mount --bind /usr/bin/sen.elf /simulation/sen-original || exit 78
                /bin/busybox mount --bind /simulation/sen-wrapper /usr/bin/sen.elf || exit 78
                /simulation/usb-senser-mode prepare || exit 78
            fi
            /bin/busybox mkdir -p /tmp/images /log/qemu || exit 1
            /bin/busybox sh /simulation/install-fonts.sh || exit 1
            /bin/busybox sh /simulation/install-sd.sh || exit 1
            for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do
                /bin/busybox mkdir -p /dev/cgroup/$group || exit 1
                echo 0 > /dev/cgroup/$group/cpuset.mems || exit 1
                echo 0 > /dev/cgroup/$group/cpuset.cpus || exit 1
            done
            /bin/busybox touch /dev/qemu-simulation/init2-observed || exit 1
        fi;;
esac
case "$name" in
    devno|dma330|osal_utm|osal_uipc|utimer|osal_ulogio|ioexp|indctr|udate|stream|stream2|dmm|kikilog|upm|grm_ma)
        /bin/busybox insmod "$module" "$@"; rc=$?;;
    usb_portMonitor|usbg_sen|usb_extcmd)
        [ -r /simulation/environment.sh ] || exit 78
        . /simulation/environment.sh
        [ "${PRODUCT_SONY_USB_DEVICE:-}" = 1 ] || { echo "PRODUCT_COLD_MODULE_REFUSED name=$name reason=usb-device-disabled result=78"; exit 78; }
        case "$name" in
            usb_portMonitor) expected=792cbc38576efba8e33faf730514f9ac694883b2668019ced0581abeb4b6f73d;;
            usbg_sen) expected=cd85574e2cfa8dce40d61fde0f46c892df1c39203677cea51770d1963d6fa148;;
            usb_extcmd) expected=63554be9f7bf7cbba3d9de16ce3d8675e3b60a323be1fa92839fa9eec0caa8c2;;
        esac
        [ "$module" = "/usr/kmod/$name.ko" ] || exit 78
        digest=$(/usr/bin/openssl dgst -sha256 "$module") || exit 78
        case "$digest" in "SHA256($module)= $expected"|"SHA2-256($module)= $expected") ;; *) echo PRODUCT_COLD_USB_MODULE_IDENTITY_FAILED; exit 78;; esac
        /bin/busybox insmod "$module" "$@"; rc=$?;;
    backup)
        /bin/busybox insmod "$module" Backup_load=1 Backup_save=0; rc=$?
        if [ "$rc" = 0 ]; then /simulation/seed-power-on 1 || exit 1; fi;;
    *)
        echo "PRODUCT_COLD_MODULE_REFUSED name=$name module=$module reason=unmodeled-hardware result=78"
        exit 78;;
esac
echo "PRODUCT_COLD_MODULE_RESULT name=$name rc=$rc"
exit "$rc"
