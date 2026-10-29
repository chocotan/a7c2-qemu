#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export LC_ALL=C TMPDIR="$PWD" PYTHONDONTWRITEBYTECODE=1
cc -std=c11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
  -fno-omit-frame-pointer -fno-pie -no-pie -o test-client test_client.c
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./test-client > host-tests.log 2>&1
aarch64-linux-gnu-gcc -c client.c -o client.o -O2 -Wall -Wextra -Werror \
  -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
  -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
  -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
  -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o descriptor.o
aarch64-linux-gnu-ld -r -o sony_atu_client.ko client.o descriptor.o
aarch64-linux-gnu-readelf -hSWrs -p .modinfo sony_atu_client.ko > module-elf.txt
aarch64-linux-gnu-objdump -dr sony_atu_client.ko > module-disassembly.txt
python3 -B check_client.py > verification.json
python3 -B test_checker.py > checker-tests.log 2>&1
cc --version > toolchain.txt
aarch64-linux-gnu-gcc --version >> toolchain.txt
aarch64-linux-gnu-ld --version >> toolchain.txt
