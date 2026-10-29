/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef SONY_ATU_CORE_H
#define SONY_ATU_CORE_H
#include <stddef.h>
#include <stdint.h>
struct sony_atu { uint32_t words[8][128]; };
typedef int (*sony_pci_transfer)(void *opaque, uint64_t target, void *bytes,
                                 size_t length, int write);
void sony_atu_reset(struct sony_atu *state);
int sony_atu_register(struct sony_atu *state, unsigned offset, uint32_t *value, int write);
int sony_atu_translate(const struct sony_atu *state, uint64_t local, size_t length,
                       uint64_t *target, unsigned *slot);
int sony_atu_transfer(const struct sony_atu *state, uint64_t local, void *bytes,
                      size_t length, int write, sony_pci_transfer transfer, void *opaque);
#endif
