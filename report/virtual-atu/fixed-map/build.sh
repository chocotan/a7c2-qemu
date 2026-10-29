#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
cc -std=c11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
  -fno-omit-frame-pointer -o test-client test_client.c
ASAN_OPTIONS=detect_leaks=1 ./test-client
aarch64-linux-gnu-gcc -c client.c -o client.o -O2 -Wall -Wextra -Werror \
  -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
  -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
  -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
  -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o descriptor.o
aarch64-linux-gnu-ld -r -o sony_fixed_io.ko client.o descriptor.o
aarch64-linux-gnu-readelf -hSWrs sony_fixed_io.ko > module-elf.txt
aarch64-linux-gnu-objdump -dr sony_fixed_io.ko > module-disassembly.txt
python3 -B check_client.py > verification.json
cc -std=c11 -O1 -g -Wall -Wextra -Werror -DFIXED_ATU_PROFILE -fsanitize=address,undefined \
  -fno-omit-frame-pointer -o test-client-atu test_client.c
ASAN_OPTIONS=detect_leaks=1 ./test-client-atu
aarch64-linux-gnu-gcc -c client.c -o atu_client.o -DFIXED_ATU_PROFILE -O2 -Wall -Wextra -Werror \
  -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
  -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
  -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
  -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o atu_descriptor.o -DFIXED_ATU_PROFILE
aarch64-linux-gnu-ld -r -o sony_atu_map.ko atu_client.o atu_descriptor.o
python3 -B check_client.py --atu > verification-atu.json
