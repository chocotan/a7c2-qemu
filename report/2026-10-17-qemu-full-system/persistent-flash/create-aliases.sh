#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
# Run after insmod and mounting proc/sys/devtmpfs, before the unchanged Sony init.
set -eu
bb=/bin/busybox
for node in pnflasha cnflasha1 cnflasha2 cnflasha3 cnflasha4 cnflasha5 cnflasha6 cnflasha7 cnflasha8 cnflasha10 cnflasha11 cnflasha12 cnflasha13 cnflasha15 cnflasha18 cnflasha22 cnflasha23 cnflasha30 nflashaB0 nflashaB1; do
    test -r "/sys/block/$node/dev"
    pair=$($bb cat "/sys/block/$node/dev")
    major=${pair%:*}
    minor=${pair#*:}
    case "$major:$minor" in *[!0-9:]*|:*|*:) exit 1;; esac
    $bb rm -f "/dev/$node"
    $bb mknod -m 600 "/dev/$node" b "$major" "$minor"
done
$bb rm -f /dev/nflasha
$bb ln -s pnflasha /dev/nflasha
for part in 1 2 3 4 5 6 7 8 10 11 12 13 15 18 22 23 30; do
    $bb rm -f "/dev/nflasha$part"
    $bb ln -s "cnflasha$part" "/dev/nflasha$part"
done
$bb echo 'PERSISTENT_FLASH_ALIASES=20 WHOLE=pnflasha BOOT_AREAS=2 PHYSICAL_ENCRYPTION=0'
