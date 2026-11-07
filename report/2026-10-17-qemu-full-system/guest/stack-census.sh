#!/bin/busybox sh
# Explicit diagnostic only: briefly stop/read/detach each selected guest thread.
if [ "$#" = 2 ]; then
    pid=$1
    base=$2
else
    pid=$(busybox sed -n '/^OBSERVER_READY pid=/{s/.*pid=\([0-9]*\) .*/\1/;p;q;}' /tmp/menu-load.log)
    base=$(busybox sed -n '/^OBSERVER_READY pid=/{s/.*base=\(0x[0-9a-f]*\) .*/\1/;p;q;}' /tmp/menu-load.log)
fi
case "$pid" in ''|*[!0-9]*) echo FULLSYSTEM_APP_NOT_MAPPED; exit 3;; esac
case "$base" in 0x*) ;; *) echo FULLSYSTEM_APP_BASE_MISSING; exit 3;; esac
digits=${base#0x}
case "$digits" in ''|*[!0-9a-fA-F]*) echo FULLSYSTEM_APP_BASE_INVALID; exit 3;; esac
[ -d "/proc/$pid/task" ] || { echo FULLSYSTEM_APP_EXITED; exit 3; }
echo "FULLSYSTEM_APP_PID=$pid"
echo FULLSYSTEM_MAPS_BEGIN
cat "/proc/$pid/maps"
echo FULLSYSTEM_MAPS_END
echo FULLSYSTEM_GROUP_GLOBALS_BEGIN
for field in 0x910a428:24 0x910a4a0:8 0x910a548:24 0x910a5c0:8; do
    offset=${field%:*}
    address=$((base + offset))
    /simulation/menu-readmem "/proc/$pid/mem" "$address" "${field#*:}"
done
# The full-system reader's '-' module marker follows an absolute pointer
# without walking smaps again. No application memory is written.
echo FULLSYSTEM_GROUP0_CURRENT
/simulation/menu-readmem "/proc/$pid/mem" "$((base + 0x910a4a0))" 128 - follow
echo "FULLSYSTEM_GROUP0_FOLLOW_RC=$?"
count=0
failures=0
common=
echo FULLSYSTEM_STACK_SCOPE=boot-imaging-critical
for task in /proc/$pid/task/[0-9]*; do
    tid=${task##*/}
    IFS= read -r name < "$task/comm" || {
        echo "FULLSYSTEM_THREAD_NAME_READ_FAILED tid=$tid"
        continue
    }
    echo "FULLSYSTEM_THREAD tid=$tid name=$name"
    case "$name" in
        SeqQueueCommon) common=$tid;;
    esac
    case "$name" in
        AppFw|SeqQueueCommon|SeqThreadPool*|IWrapperImaging|IWrapperUPM) ;;
        *) continue;;
    esac
    if [ "$count" -ge 192 ]; then
        echo FULLSYSTEM_STACK_CENSUS_TRUNCATED
        continue
    fi
    /simulation/thread-snapshot "$tid"
    snapshot_rc=$?
    echo "FULLSYSTEM_THREAD_STACK_RC=$snapshot_rc tid=$tid"
    [ "$snapshot_rc" = 0 ] || failures=$((failures + 1))
    count=$((count + 1))
done
if [ "$count" = 0 ] || [ -z "$common" ]; then
    failures=$((failures + 1))
fi
echo "FULLSYSTEM_STACK_CENSUS_DONE count=$count failures=$failures"
echo FULLSYSTEM_COMMON_TRANSPORT_BEGIN
[ -z "$common" ] || busybox grep -a "tid=$common " /tmp/menu-load.log
echo FULLSYSTEM_COMMON_TRANSPORT_END
exit "$failures"
