#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
binary=$(mktemp /var/tmp/sony-phy-clear-test.XXXXXXXX)
trap 'rm -f "$binary"' EXIT
cc -std=c11 -O1 -g -Wall -Wextra -Werror -Wconversion -Wshadow \
 -fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie \
 phy_clear_job.c phy_sram.c test_phy_clear_job.c -o "$binary"
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 "$binary"
