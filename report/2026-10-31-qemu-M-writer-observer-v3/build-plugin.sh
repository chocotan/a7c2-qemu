#!/bin/sh
# SPDX-License-Identifier: MIT
# Draft qemu-readonly-scope-v3 build entry; no QEMU run or plugin loading.
# Source root: report/2026-10-31-qemu-M-writer-observer-v3 beside the base component.
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=$(CDPATH= cd -- "$here/../.." && pwd)
scratch="$project/runtime/analysis/scratch/functional-M-writer-v3-readonly-scope-plugin"
header="$here/../../source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins"
mkdir -p "$scratch"
work=$(mktemp -d "$scratch/build-XXXXXXXX")
if ! (
    cflags=$(pkg-config --cflags glib-2.0) || exit 1
    libraries=$(pkg-config --libs glib-2.0) || exit 1
    # pkg-config provides compiler words; no eval or QEMU binary is involved.
    ${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
        -fPIC -fvisibility=hidden -shared -I"$header" $cflags \
        "$here/scope-observer.c" $libraries -o "$work/scope-observer.so"
) >"$work/build.log" 2>&1; then
    echo "Build incomplete; inspect $work/build.log" >&2
    exit 1
fi
echo "$work/scope-observer.so"
