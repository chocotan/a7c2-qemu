/* Explicit virtual identification contract; no SD/card/clock/reset protocol. */
#ifndef P1_MMC_MODEL_H
#define P1_MMC_MODEL_H
#include <stdint.h>
#define P1_MMC_ID_ADDRESS UINT64_C(0xf13b8000)
#define P1_MMC_ID_VALUE UINT32_C(0x1000)
#define P1_MMC_PROFILE "original-p1-mmc-identification-v1"
enum p1_mmc_phase { P1_MMC_RESET, P1_MMC_IDENTIFIED, P1_MMC_FAULT };
enum p1_mmc_result {
    P1_MMC_OK, P1_MMC_BAD_WIDTH, P1_MMC_UNKNOWN, P1_MMC_READ_ONLY,
    P1_MMC_LATCHED, P1_MMC_ARGUMENT
};
struct p1_mmc_model {
    uint64_t reads, rejections, first_address, first_value;
    uint32_t phase, first_error, first_width;
};
void p1_mmc_reset(struct p1_mmc_model *state);
int p1_mmc_read(struct p1_mmc_model *state, uint64_t address,
                unsigned width, uint64_t *value);
int p1_mmc_write(struct p1_mmc_model *state, uint64_t address,
                 unsigned width, uint64_t value);
#endif
