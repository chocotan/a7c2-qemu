#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export LC_ALL=C
export TMPDIR="$PWD"
gcc=aarch64-linux-gnu-gcc
ld=aarch64-linux-gnu-ld
"$gcc" -c client.c -o client.o -O2 -Wall -Wextra -Werror \
  -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
  -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
  -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
  -mcmodel=large -mpc-relative-literal-loads
"$gcc" -c descriptor.S -o descriptor.o
"$ld" -r -o dma330_abi_diag.ko client.o descriptor.o
python3 check_elf.py > verification.json
PYTHONDONTWRITEBYTECODE=1 python3 test_checker.py > checker-tests.log 2>&1
aarch64-linux-gnu-readelf -hSWr -sW -p .modinfo dma330_abi_diag.ko > built-readelf.txt
aarch64-linux-gnu-objdump -dr dma330_abi_diag.ko > built-disassembly.txt
"$gcc" --version > toolchain.txt
"$ld" --version >> toolchain.txt
