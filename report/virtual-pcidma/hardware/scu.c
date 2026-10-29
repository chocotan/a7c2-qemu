#include "scu.h"

#include <stddef.h>

const uint64_t sony_pcie_scu_wrapper_addresses[SCU_WRAPPER_COUNT] = {
    UINT64_C(0xf11e0380), UINT64_C(0xf1160380), UINT64_C(0xf11a0380),
    UINT64_C(0xf1220380), UINT64_C(0xf1120380)
};

const uint32_t sony_pcie_scu_hclk_masks[SCU_WRAPPER_COUNT] = {
    UINT32_C(1) << 1, UINT32_C(1) << 7, UINT32_C(1) << 13,
    UINT32_C(1) << 19, UINT32_C(1) << 25
};

const uint32_t sony_pcie_scu_apb_reset_masks[SCU_WRAPPER_COUNT] = {
    UINT32_C(1) << 3, UINT32_C(1) << 11, UINT32_C(1) << 7,
    UINT32_C(1) << 15, UINT32_C(1) << 19
};

void sony_pcie_scu_init(struct sony_pcie_scu_state *state)
{
    if (state != NULL) {
        *state = (struct sony_pcie_scu_state){ .reset = SCU_APB_RESET_MASK };
    }
}

static bool valid_access(const struct sony_pcie_scu_state *state, uint64_t physical,
                         unsigned size)
{
    return state != NULL && size == SCU_ACCESS_SIZE && (physical & 3u) == 0;
}

static bool wrapper_available(const struct sony_pcie_scu_state *state, unsigned index)
{
    return (state->hclk & sony_pcie_scu_hclk_masks[index]) != 0 &&
           (state->reset & sony_pcie_scu_apb_reset_masks[index]) == 0;
}

bool sony_pcie_scu_read(struct sony_pcie_scu_state *state, uint64_t physical,
                        unsigned size, uint32_t *out)
{
    if (!valid_access(state, physical, size) || out == NULL) {
        return false;
    }
    if (physical == SCU_HCLK_STATUS) {
        *out = state->hclk;
        return true;
    }
    if (physical == SCU_RESET_STATUS) {
        *out = state->reset;
        return true;
    }
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        if (physical == sony_pcie_scu_wrapper_addresses[i]) {
            if (!wrapper_available(state, i)) {
                return false;
            }
            *out = state->wrapper[i];
            return true;
        }
    }
    return false;
}

bool sony_pcie_scu_write(struct sony_pcie_scu_state *state, uint64_t physical,
                         unsigned size, uint32_t value)
{
    if (!valid_access(state, physical, size)) {
        return false;
    }
    if (physical == SCU_HCLK_SET || physical == SCU_HCLK_CLEAR) {
        if ((value & ~SCU_HCLK_MASK) != 0) {
            return false;
        }
        if (physical == SCU_HCLK_SET) {
            state->hclk |= value;
        } else {
            state->hclk &= ~value;
        }
        return true;
    }
    if (physical == SCU_RESET_SET || physical == SCU_RESET_CLEAR) {
        if ((value & ~SCU_APB_RESET_MASK) != 0) {
            return false;
        }
        if (physical == SCU_RESET_SET) {
            state->reset |= value;
        } else {
            state->reset &= ~value;
        }
        return true;
    }
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        if (physical == sony_pcie_scu_wrapper_addresses[i]) {
            if ((value & ~SCU_WRAPPER_REQUEST_MASK) != 0 ||
                !wrapper_available(state, i)) {
                return false;
            }
            state->wrapper[i] = value;
            return true;
        }
    }
    return false;
}
