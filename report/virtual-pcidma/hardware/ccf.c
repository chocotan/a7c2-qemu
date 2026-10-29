#include "ccf.h"

#include <stddef.h>

static const uint32_t gate_masks[9] = {
    UINT32_C(0x1f000), 0, UINT32_C(0x30f), UINT32_C(0x2c000c),
    UINT32_C(0x13fffc0), UINT32_C(0xdf7c0), 0, 0, UINT32_C(0x3efbefbe)
};
static const uint32_t mux_masks[3] = {
    UINT32_C(0x1f000000), UINT32_C(0x11111), UINT32_C(0x3ff)
};

enum { STATUS = 0, SET = 4, CLEAR = 8, DIRECT = 12 };

static uint32_t *decode(struct sony_ccf_state *state, uint64_t physical,
                        unsigned size, uint32_t *mask, unsigned *port)
{
    uint32_t offset;
    unsigned index;

    if (state == NULL || size != 4 || (physical & UINT64_C(3)) != 0 ||
        physical < SONY_CCF_SCU_BASE ||
        physical - SONY_CCF_SCU_BASE > UINT64_C(0x378)) {
        return NULL;
    }
    offset = (uint32_t)(physical - SONY_CCF_SCU_BASE);
    *port = offset & 0xfU;
    if (offset <= 0x88U && *port <= CLEAR) {
        index = offset / 0x10U;
        *mask = gate_masks[index];
        return &state->gates[index];
    }
    if (offset >= 0x210U && offset <= 0x238U && *port <= CLEAR) {
        index = (offset - 0x210U) / 0x10U;
        *mask = mux_masks[index];
        return &state->mux[index];
    }
    if (offset >= 0x300U && *port <= CLEAR) {
        index = (offset - 0x300U) / 0x10U;
        *mask = UINT32_MAX;
        return &state->resets[index];
    }
    if (offset >= 0x10cU && offset <= 0x11cU) {
        index = (offset - 0x10cU) / 4U;
        *mask = UINT32_C(0xff);
        *port = DIRECT;
        return &state->dividers[index];
    }
    return NULL;
}

void sony_ccf_init(struct sony_ccf_state *state)
{
    if (state != NULL) {
        *state = (struct sony_ccf_state){0};
        state->resets[1] = UINT32_C(0x88888);
    }
}

bool sony_ccf_read(struct sony_ccf_state *state, uint64_t physical,
                   unsigned size, uint32_t *out)
{
    uint32_t mask;
    unsigned port;
    uint32_t *word;

    if (out == NULL) {
        return false;
    }
    word = decode(state, physical, size, &mask, &port);
    if (word == NULL || (port != STATUS && port != DIRECT)) {
        return false;
    }
    *out = *word & mask;
    return true;
}

bool sony_ccf_write(struct sony_ccf_state *state, uint64_t physical,
                    unsigned size, uint32_t value)
{
    uint32_t mask;
    unsigned port;
    uint32_t *word = decode(state, physical, size, &mask, &port);

    if (word == NULL || port == STATUS || (value & ~mask) != 0) {
        return false;
    }
    if (port == SET) {
        *word |= value;
    } else if (port == CLEAR) {
        *word &= ~value;
    } else {
        *word = value;
    }
    return true;
}
