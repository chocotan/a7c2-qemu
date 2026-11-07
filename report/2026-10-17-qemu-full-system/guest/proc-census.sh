#!/bin/busybox sh
# Explicit ptrace diagnostic. Discover the original process and ELF load base
# directly from proc; no UART input or observer-log substring is required.
echo FULLSYSTEM_PROC_CENSUS_STARTED > /dev/kmsg
samples=${2:-1}
case "$samples" in 1|2) ;; *) exit 2;; esac
case "$1" in
    ''|0) ;;
    *[!0-9]*) exit 2;;
    *) [ "$1" -le 120 ] || exit 2
       echo "FULLSYSTEM_PROC_CENSUS_DELAY_SECONDS=$1" > /dev/kmsg
       sleep "$1";;
esac
attempt=0
while [ "$attempt" -lt 150 ]; do
    for process in /proc/[0-9]*; do
        IFS= read -r name < "$process/comm" 2>/dev/null || continue
        [ "$name" = im.elf ] || continue
        pid=${process##*/}
        base=
        while read -r address perms offset device inode path; do
            [ "$path" = /usr/lib/appFw.so ] || continue
            [ "$offset" = 00000000 ] || continue
            base=0x${address%-*}
            break
        done < "$process/maps"
        [ -n "$base" ] || continue
        critical=0
        common=0
        for task in "$process"/task/[0-9]*; do
            IFS= read -r thread < "$task/comm" 2>/dev/null || continue
            case "$thread" in
                SeqQueueCommon) common=1; critical=$((critical + 1));;
                AppFw|SeqThreadPool*|IWrapperImaging|IWrapperUPM) critical=$((critical + 1));;
            esac
        done
        if [ "$common" = 1 ] && [ "$critical" -ge 8 ]; then
            echo "FULLSYSTEM_PROC_CENSUS_TARGET pid=$pid base=$base critical=$critical" > /dev/kmsg
            sample=1
            failures=0
            while [ "$sample" -le "$samples" ]; do
                echo "FULLSYSTEM_PROC_CENSUS_SAMPLE_BEGIN sample=$sample pid=$pid base=$base" > /dev/kmsg
                rcfile=/log/qemu/proc-census-$$-$sample.rc
                (
                    /simulation/host-census.sh "$pid" "$base"
                    echo "$?" > "$rcfile"
                ) 2>&1 | while IFS= read -r line; do
                    case "$line" in FULLSYSTEM_AUTO_STACKS_DONE=*) continue;; esac
                    echo "$line" > /dev/kmsg || exit 5
                done
                output_rc=$?
                sample_rc=255
                IFS= read -r sample_rc < "$rcfile" || sample_rc=255
                rm -f "$rcfile"
                case "$sample_rc" in ''|*[!0-9]*) sample_rc=255;; esac
                [ "$sample_rc" = 0 ] && [ "$output_rc" = 0 ] || failures=$((failures + 1))
                echo "FULLSYSTEM_PROC_CENSUS_SAMPLE_DONE sample=$sample pid=$pid rc=$sample_rc output_rc=$output_rc" > /dev/kmsg
                sample=$((sample + 1))
                [ "$sample" -gt "$samples" ] || sleep 30
            done
            echo "FULLSYSTEM_AUTO_STACKS_DONE=$failures" > /dev/kmsg
            exit "$failures"
        fi
    done
    attempt=$((attempt + 1))
    sleep 1
done
echo FULLSYSTEM_AUTO_STACKS_NO_SCREEN > /dev/kmsg
exit 3
