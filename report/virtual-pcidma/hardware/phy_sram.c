#include "phy_sram.h"
void sony_phy_sram_reset(struct sony_phy_sram *s)
{
    if(s)*s=(struct sony_phy_sram){0};
}
bool sony_phy_sram_clear_storage(struct sony_phy_sram *s)
{
    if(!s)return false;
    sony_phy_sram_reset(s);s->initialized=true;return true;
}
bool sony_phy_sram_write(struct sony_phy_sram *s,uint32_t offset,unsigned size,uint32_t value)
{
    if(!s)return false;
    if(!s->initialized || s->failed || s->apply_seen || s->count>=SONY_PHY_SRAM_WORDS ||
       size!=4 || value>UINT16_MAX || offset!=SONY_PHY_SRAM_OFFSET+4u*s->count) {
        s->failed=true;return false;
    }
    s->words[s->count++]=(uint16_t)value;return true;
}
bool sony_phy_sram_apply_requested(struct sony_phy_sram *s)
{
    if(!s)return false;
    s->apply_seen=true;
    return s->initialized && !s->failed && s->count==SONY_PHY_SRAM_WORDS;
}
bool sony_phy_sram_export_le(const struct sony_phy_sram *s,uint8_t *out,size_t size)
{
    if(!s || !out || size<SONY_PHY_SRAM_BYTES || !s->initialized || s->failed ||
       !s->apply_seen || s->count!=SONY_PHY_SRAM_WORDS)return false;
    for(size_t i=0;i<SONY_PHY_SRAM_WORDS;i++) {
        out[2*i]=(uint8_t)s->words[i];out[2*i+1]=(uint8_t)(s->words[i]>>8);
    }
    return true;
}
