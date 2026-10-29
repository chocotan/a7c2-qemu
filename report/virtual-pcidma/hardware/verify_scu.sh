#!/bin/sh
set -eu
cd "$(dirname "$0")"
binary=$(mktemp "${TMPDIR:-/tmp}/scu-reset-core.XXXXXXXX")
trap 'rm -f "$binary"' EXIT HUP INT TERM
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -pedantic -g -O1 \
    -fsanitize=address,undefined -fno-omit-frame-pointer \
    scu.c test_scu.c -o "$binary"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 "$binary"
