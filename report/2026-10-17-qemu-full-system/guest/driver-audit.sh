#!/bin/busybox sh
echo FULLSYSTEM_PRE_DRIVERS
insmod /kmod/devno.ko || exit 1
# Original setup_shielding expects four real CPUs. This board has one guest CPU.
mkdir -p /dev/cgroup
mount -t cgroup -o cpuset nodev /dev/cgroup
for group in cpu0 cpu1 cpu2 cpu3rt cpu0_1 cpu0_1_2 cpu0_1_2_3rt; do
    mkdir -p "/dev/cgroup/$group"
    echo 0 > "/dev/cgroup/$group/cpuset.mems"
    echo 0 > "/dev/cgroup/$group/cpuset.cpus"
done
echo set > /proc/udm/drivers
INITRC_DIR=/sbin/initrc
. /sbin/initrc/insmod_drv2
echo FULLSYSTEM_DRIVERS_DONE
cat /proc/modules
