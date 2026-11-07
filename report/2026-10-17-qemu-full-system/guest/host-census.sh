#!/bin/busybox sh
# Explicit read-only census using the original observer identity supplied by host.
echo FULLSYSTEM_HOST_STACKS_BEGIN
/simulation/stack-census.sh "$@"
result=$?
echo "FULLSYSTEM_AUTO_STACKS_DONE=$result"
exit "$result"
