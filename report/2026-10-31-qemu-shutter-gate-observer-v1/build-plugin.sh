#!/bin/sh
# SPDX-License-Identifier: MIT
# Build only; build-runtime.py binds the source closure and audits the result.
set -eu
umask 077
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
work=$(python3 -B - "$here" "$0" <<'PY'
from pathlib import Path
import os
import stat
import sys
import tempfile
here = Path(sys.argv[1])
script = Path(sys.argv[2]).absolute()
if (script.resolve() != script or script != here / 'build-plugin.sh' or
        (here.parent.name, here.name) != ('report', '2026-10-31-qemu-shutter-gate-observer-v1')):
    raise ValueError('Fixed canonical shutter-gate-v1 source root required')
scratch = here.parents[1] / 'runtime/analysis/scratch/functional-shutter-gate-v1-readonly-plugin'
for path in (here, scratch.parent):
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(info.st_mode) or
            info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise ValueError('Untrusted source or scratch directory')
if scratch.resolve() != scratch:
    raise ValueError('Symlink scratch refused')
scratch.mkdir(mode=0o700, exist_ok=True)
info = scratch.lstat()
if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
    raise ValueError('Untrusted scratch directory')
print(tempfile.mkdtemp(prefix='build-', dir=scratch))
PY
)
header="$here/../../source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins"
# Emit the owned work path even on failure so the parent retains its real rc.
echo "$work/scope-observer.so"
rc=0
(
    cflags=$(pkg-config --cflags glib-2.0) || exit 1
    libraries=$(pkg-config --libs glib-2.0) || exit 1
    # pkg-config provides compiler words; no eval or QEMU binary is involved.
    ${CC:-cc} -std=c11 -Wall -Wextra -Werror -pedantic -O2 \
        -fPIC -fvisibility=hidden -shared -I"$header" $cflags \
        "$here/scope-observer.c" $libraries -o "$work/scope-observer.so"
) >"$work/build.log" 2>&1 || rc=$?
(set -C; echo "$rc" >"$work/build-compile-returncode.txt")
if [ "$rc" -ne 0 ]; then
    echo "Build incomplete; rc=$rc; inspect $work/build.log" >&2
fi
exit "$rc"
