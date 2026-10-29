#ifndef SONY_EDMA_REGISTERS_H
#define SONY_EDMA_REGISTERS_H
#include "lli.h"
struct sony_edma_registers {
    uint32_t enabled[2], status[2], mask[2], list_errors[2];
    uint32_t error_status[3]; /* DMAWR_ERR 0x5c, DMARD_ERR_L 0xb4, DMARD_ERR_H 0xb8 */
    uint32_t first_word[2][8], channel[2][8][9];
    struct sony_edma_outcome last[2][8];
    unsigned max_steps;
    uint64_t max_bytes;
};
/* Direction index0 is write/local->PCI, index1 read/PCI->local. */
void sony_edma_reset(struct sony_edma_registers *, unsigned max_steps, uint64_t max_bytes);
int sony_edma_irq(const struct sony_edma_registers *);
int sony_edma_register(struct sony_edma_registers *, const struct sony_edma_bus *,
                        uint32_t offset, uint32_t *value, unsigned write);
#endif
