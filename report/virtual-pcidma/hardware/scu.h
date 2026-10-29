#ifndef TEST_BOARD_SCU_H
#define TEST_BOARD_SCU_H

#include <stdbool.h>
#include <stdint.h>

#define SCU_HCLK_STATUS UINT64_C(0xf1388080)
#define SCU_HCLK_SET    UINT64_C(0xf1388084)
#define SCU_HCLK_CLEAR  UINT64_C(0xf1388088)
#define SCU_RESET_STATUS UINT64_C(0xf1388310)
#define SCU_RESET_SET    UINT64_C(0xf1388314)
#define SCU_RESET_CLEAR  UINT64_C(0xf1388318)

#define SCU_HCLK_MASK UINT32_C(0x02082082)
#define SCU_APB_RESET_MASK UINT32_C(0x88888)
#define SCU_WRAPPER_REQUEST_MASK UINT32_C(0x10)
#define SCU_ACCESS_SIZE 4u
#define SCU_WRAPPER_COUNT 5u

/* HCLK bit numbers in native controller order: 1, 7, 13, 19, 25. */
extern const uint64_t sony_pcie_scu_wrapper_addresses[SCU_WRAPPER_COUNT];
extern const uint32_t sony_pcie_scu_hclk_masks[SCU_WRAPPER_COUNT];
extern const uint32_t sony_pcie_scu_apb_reset_masks[SCU_WRAPPER_COUNT];

struct sony_pcie_scu_state {
    uint32_t hclk;
    uint32_t reset;
    uint32_t wrapper[SCU_WRAPPER_COUNT];
};

/* Explicit TEST-board policy; no silicon power-on-reset claim. NULL is a no-op. */
void sony_pcie_scu_init(struct sony_pcie_scu_state *state);
/* false means rejected access: state and (for reads) *out remain unchanged. */
bool sony_pcie_scu_read(struct sony_pcie_scu_state *state, uint64_t physical,
                        unsigned size, uint32_t *out);
bool sony_pcie_scu_write(struct sony_pcie_scu_state *state, uint64_t physical,
                         unsigned size, uint32_t value);

#endif
