#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
cc -std=c11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
  -fno-omit-frame-pointer -o test-adapter test_adapter.c
ASAN_OPTIONS=detect_leaks=1 ./test-adapter
aarch64-linux-gnu-gcc -c adapter.c -o adapter.o -O2 -Wall -Wextra -Werror \
  -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
  -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
  -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
  -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o descriptor.o
aarch64-linux-gnu-ld -r -o sony_dma_map.ko adapter.o descriptor.o
aarch64-linux-gnu-readelf -hSWrs sony_dma_map.ko > module-elf.txt
aarch64-linux-gnu-objdump -dr sony_dma_map.ko > module-disassembly.txt
python3 -B check_adapter.py > verification.json
