#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
cc -std=c11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
 -fno-omit-frame-pointer -fno-pie -no-pie test_client.c -o test-client
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 ./test-client
aarch64-linux-gnu-gcc -c client.c -o client.o -O2 -Wall -Wextra -Werror \
 -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
 -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
 -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
 -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o descriptor.o
aarch64-linux-gnu-ld -r -o sony_ccf_client.ko client.o descriptor.o
python3 -B check_client.py > verification.json
