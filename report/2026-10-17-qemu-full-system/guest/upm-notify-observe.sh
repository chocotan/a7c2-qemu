#!/bin/busybox sh
# Explicit isolated diagnostic only; no real CP task or hardware assertion.
set -f
n=0
while [ ! -r /sys/module/upm/sections/.text ]; do
    n=$((n+1))
    [ "$n" -lt 240 ] || { echo UPM_PROBE_MODULE_TIMEOUT; exit 1; }
    busybox sleep 1
done
text=$(cat /sys/module/upm/sections/.text)
bss=$(cat /sys/module/upm/sections/.bss)
data=$(cat /sys/module/upm/sections/.data)
echo "UPM_PROBE_SECTIONS text=$text bss=$bss data=$data"
# The host arms read-only QEMU breakpoints on the section announcement.
# Wait for the original fourth-request boundary, not merely module load.
n=0
while ! busybox grep -q 'FULL_HDMIPIN_NATIVE_REPLY_FREE .*rc=0' /log/qemu/menu-load.log; do
    n=$((n+1))
    [ "$n" -lt 600 ] || { echo UPM_PROBE_BOUNDARY_TIMEOUT; exit 1; }
    busybox sleep 1
done
busybox sleep 3
/simulation/upm-notify-check --isolated-diagnostic
echo "UPM_DIAG_PRODUCER_RC=$?"
