/* SPDX-License-Identifier: GPL-2.0-or-later
 * Explicit virtual ATU contract. Register addresses come from the original
 * pciatu provider; reset-disabled/overlap-rejection are virtual-board policy,
 * not claims about Sony silicon reset/security bits. No success/data stubs.
 */
#include "atu_core.h"
#include <string.h>

void sony_atu_reset(struct sony_atu *state)
{
    memset(state, 0, sizeof *state);
}

int sony_atu_register(struct sony_atu *state, unsigned offset, uint32_t *value, int write)
{
    unsigned word;
    if (!state || !value || offset >= 4096 || (offset & 3)) return -1;
    word = (offset & 511)/4;
    if (word != 1 && word != 2 && word != 3 && word != 4
        && word != 5 && word != 6 && word != 8) return -1;
    if (write) state->words[offset/512][word] = *value;
    else *value = state->words[offset/512][word];
    return 0;
}

static uint64_t pair(const uint32_t *words, unsigned low, unsigned high)
{
    return (uint64_t)words[low] | ((uint64_t)words[high] << 32);
}

int sony_atu_translate(const struct sony_atu *state, uint64_t local, size_t length,
                       uint64_t *target, unsigned *slot)
{
    unsigned index, matches = 0, selected = 0;
    uint64_t translated = 0;
    if (!state || !target || !slot || !length || local < 0xc0000000UL
        || local >= 0xe0000000UL || length > 0xe0000000UL-local) return -1;
    for (index = 0; index < 8; index++) {
        const uint32_t *words = state->words[index];
        uint64_t start, end, pci, offset;
        if (!(words[1] & 0x80000000U)) continue;
        start = pair(words, 2, 3); end = pair(words, 4, 8); pci = pair(words, 5, 6);
        if (start < 0xc0000000UL || end >= 0xe0000000UL || end < start) continue;
        if (local < start || local > end || length-1 > end-local) continue;
        offset = local-start;
        if (pci > UINT64_MAX-offset || length-1 > UINT64_MAX-(pci+offset)) return -1;
        translated = pci+offset; selected = index; matches++;
    }
    /* Real overlap priority is unproven. Never silently select an ambiguous
     * window or expose the underlying generic virt RAM behind the aperture.
     */
    if (matches != 1) return -1;
    *target = translated; *slot = selected;
    return 0;
}

int sony_atu_transfer(const struct sony_atu *state, uint64_t local, void *bytes,
                      size_t length, int write, sony_pci_transfer transfer, void *opaque)
{
    uint64_t target;
    unsigned slot;
    if (!bytes || !transfer || (write != 0 && write != 1)
        || sony_atu_translate(state, local, length, &target, &slot)) return -1;
    return transfer(opaque, target, bytes, length, write);
}
