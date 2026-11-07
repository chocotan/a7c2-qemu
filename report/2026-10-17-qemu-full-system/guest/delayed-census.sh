#!/bin/busybox sh
# Schedule read-only diagnostics before startup; no later UART command is needed.
count=0
while [ "$count" -lt 3000 ]; do
    if busybox grep -q 'CREATE_SCREEN_RETURN call=1 ' /tmp/menu-load.log 2>/dev/null; then
        sleep 20
        echo FULLSYSTEM_AUTO_STACKS_BEGIN
        /simulation/stack-census.sh
        result=$?
        echo "FULLSYSTEM_AUTO_STACKS_DONE=$result"
        exit "$result"
    fi
    count=$((count + 1))
    sleep 1
done
echo FULLSYSTEM_AUTO_STACKS_NO_SCREEN
exit 3
