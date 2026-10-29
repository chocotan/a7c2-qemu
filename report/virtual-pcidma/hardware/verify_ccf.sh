#!/bin/sh
set -eu
cd "$(dirname "$0")"
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/sony-ccf-test.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
"${CC:-cc}" -std=c11 -Wall -Wextra -Werror -Wpedantic -Wconversion \
    -Wsign-conversion -Wshadow -Wstrict-prototypes -Wmissing-prototypes \
    -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined \
    -fno-sanitize-recover=all ccf.c test_ccf.c -o "$build_dir/test_ccf"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 "$build_dir/test_ccf"
