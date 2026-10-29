#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
aarch64-linux-gnu-gcc -c client.c -o client.o -O2 -Wall -Wextra -Werror \
 -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
 -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
 -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
 -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o descriptor.o
aarch64-linux-gnu-ld -r -o sony_virtual_cp_send.ko client.o descriptor.o
python3 -B check_client.py > verification.json
cat verification.json
