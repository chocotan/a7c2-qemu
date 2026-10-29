#ifndef SONY_PHY_SRAM_H
#define SONY_PHY_SRAM_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define SONY_PHY_SRAM_WORDS 4096u
#define SONY_PHY_SRAM_BYTES (SONY_PHY_SRAM_WORDS*2u)
#define SONY_PHY_SRAM_OFFSET UINT32_C(0x18000)
struct sony_phy_sram {
    uint16_t words[SONY_PHY_SRAM_WORDS];
    size_t count;
    bool initialized,failed,apply_seen;
};
/* Storage operations only: no register READY/lane/link status is produced. */
void sony_phy_sram_reset(struct sony_phy_sram *);
bool sony_phy_sram_clear_storage(struct sony_phy_sram *);
/* Bad transaction latches failure, preserving all actually accepted prefix words. */
bool sony_phy_sram_write(struct sony_phy_sram *,uint32_t offset,unsigned size,uint32_t value);
/* Latches apply even when incomplete. True means stored words can be HASHED,
 * never that a firmware image is authentic/accepted or a PHY is ready. */
bool sony_phy_sram_apply_requested(struct sony_phy_sram *);
bool sony_phy_sram_export_le(const struct sony_phy_sram *,uint8_t *,size_t);
#endif
