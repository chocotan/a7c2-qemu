# SPDX-License-Identifier: GPL-2.0-only
ifneq ($(KERNELRELEASE),)
obj-m := sony_persistent_flash.o
else
CC ?= cc
OUT ?= /tmp/a7c2-persistent-flash-tests
.PHONY: test
# All generated files stay outside the delivery source directory.
test:
	mkdir -p $(OUT)
	$(CC) -std=gnu11 -Wall -Wextra -Werror -g -fsanitize=address,undefined flash-core.c test-core.c -o $(OUT)/test-core
	$(OUT)/test-core
	python3 -m pytest -q test-geometry.py
endif
