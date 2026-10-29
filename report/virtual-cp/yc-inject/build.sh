#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
aarch64-linux-gnu-gcc -c yc_inject.c -o yc_inject.o -O2 -Wall -Wextra -Werror \
 -ffreestanding -fno-builtin -fno-stack-protector -fno-pic -fno-pie \
 -fno-asynchronous-unwind-tables -fno-unwind-tables -fno-ident \
 -mgeneral-regs-only -mno-outline-atomics -mbranch-protection=none \
 -mcmodel=large -mpc-relative-literal-loads
aarch64-linux-gnu-gcc -c descriptor.S -o descriptor.o
aarch64-linux-gnu-ld -r -o yc_inject.ko yc_inject.o descriptor.o
python3 -B check_module.py > verification.json
cat verification.json
RUNTIME="$(cd ../../../runtime/analysis && pwd)"
install -m 0644 yc_inject.ko "$RUNTIME/menu-root/simulation/yc_inject.ko"
echo "installed to $RUNTIME/menu-root/simulation/yc_inject.ko"
