#!/bin/sh
# Explicit ROM controller transport; original BSA still owns its IPC and management state.
exec > /tmp/bt-launch-$$.log 2>&1
PATH=/bin:/usr/bin:/sbin:/usr/sbin
LD_LIBRARY_PATH=/usr/lib:/lib
LD_PRELOAD=
export PATH LD_LIBRARY_PATH LD_PRELOAD
echo BT_LAUNCH_PID=$$
mkdir -p /dev/pts /tmp_bt
/bin/busybox grep -q ' /dev/pts devpts ' /proc/mounts || mount -t devpts devpts /dev/pts
test -c /dev/ptmx || mknod /dev/ptmx c 5 2
# shortcut: only one Bluetooth startup per VM is validated; repeated radio restarts need owned controller teardown.
/simulation/virtual-hci --virtual-rom > /tmp/virtual-hci.pty 2> /dev/console &
echo $! > /tmp/virtual-hci.pid
i=0
while [ ! -s /tmp/virtual-hci.pty ] && [ "$i" -lt 100 ]; do sleep 0.05; i=$((i+1)); done
IFS= read -r BTDEV < /tmp/virtual-hci.pty || exit 1
echo BT_LAUNCH_TTY=$BTDEV length=${#BTDEV}
case "$BTDEV" in /dev/pts/*) number=${BTDEV#/dev/pts/};; *) echo BT_BAD_TTY_PREFIX;exit 1;; esac
case "$number" in ''|*[!0-9]*) echo BT_BAD_TTY_NUMBER;exit 1;; esac
if ! test -c "$BTDEV"; then echo BT_TTY_NOT_CHARACTER;ls -l "$BTDEV" /dev/pts;exit 1;fi
/usr/bin/bsa_server -r 14 -k /tmp_bt/ble_local_keys -u /tmp_bt/ -d "$BTDEV" -all=0 > /tmp/bsa-virtual.log 2>&1 &
echo $! > /tmp/bsa-virtual.pid
echo BT_LAUNCH_CHILD=$(cat /tmp/bsa-virtual.pid)
