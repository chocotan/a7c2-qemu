#!/usr/bin/env bash
# Build/run only this internal component; no kernel, camera program or devices.
set -euo pipefail
if [[ $# != 2 ]]; then
  echo 'Usage: verify_guest_abi.sh ORIGINAL_MENU_ROOT QEMU_AARCH64_USER_BINARY' >&2
  exit 2
fi
root=$(realpath -- "$1")
qemu_user=$(realpath -- "$2")
python3 - "$root" <<'PY'
import hashlib
import sys
from pathlib import Path
root = Path(sys.argv[1])/'lib'
pins = {
    'libc-2.25.so': 'f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9',
    'libm-2.25.so': 'dfffde29fdbf16430c5c27587253323eb94b4b551235a8839478ff3a1cfd1871',
    'ld-2.25.so': '90b4fe734ba7faa08d4591b1363bff478e7bde399a821fc0b2d021c062a58a9a',
}
for name, expected in pins.items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
        raise SystemExit('Original guest library identity mismatch: '+name)
print('ORIGINAL_GUEST_LIBRARY_IDENTITIES_PASS')
PY
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
mkdir -p .build
clang --target=aarch64-linux-gnu -fuse-ld=lld -nostdlib -O2 \
  -mno-outline-atomics -isystem /usr/aarch64-linux-gnu/include \
  -Wl,--no-undefined -Wl,-e,_start \
  -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  optics.c test_optics.c guest_entry.c \
  "$root/lib/libm-2.25.so" "$root/lib/libc-2.25.so" "$root/lib/ld-2.25.so" \
  -o .build/test_optics_aarch64
python3 - <<'PY'
from elftools.elf.elffile import ELFFile
with open('.build/test_optics_aarch64', 'rb') as stream:
    elf = ELFFile(stream)
    if elf['e_machine'] != 'EM_AARCH64':
        raise SystemExit('Not an AArch64 executable')
    needed = {tag.needed for tag in elf.get_section_by_name('.dynamic').iter_tags()
              if tag.entry.d_tag == 'DT_NEEDED'}
    versions = [item.name for _, items in elf.get_section_by_name('.gnu.version_r').iter_versions()
                for item in items]
    if needed != {'libm.so.6', 'libc.so.6', 'ld-linux-aarch64.so.1'}:
        raise SystemExit('Unexpected guest dynamic dependencies: '+repr(needed))
    if not versions or any(v != 'GLIBC_2.17' for v in versions):
        raise SystemExit('Unexpected guest symbol version: '+repr(versions))
print('AARCH64_GLIBC_2_17_DEPENDENCIES_PASS')
PY
env -u LD_PRELOAD -u LD_LIBRARY_PATH -u LD_AUDIT \
  -u QEMU_LD_PREFIX -u QEMU_SET_ENV -u QEMU_UNSET_ENV \
  "$qemu_user" -L "$root" .build/test_optics_aarch64
