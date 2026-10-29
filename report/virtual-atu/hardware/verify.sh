#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
cc -std=c11 -O1 -g -Wall -Wextra -Werror -fsanitize=address,undefined \
  -fno-omit-frame-pointer atu_core.c test_atu_core.c -o test-atu-core
ASAN_OPTIONS=detect_leaks=1 ./test-atu-core
