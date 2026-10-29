#include "phy_sram.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint16_t word(size_t i) {return i>=SONY_PHY_SRAM_WORDS-900?0:(uint16_t)((i*37u)^0xa5a5u);}
static void feed(struct sony_phy_sram *s,size_t end)
{
    for(size_t i=s->count;i<end;i++)assert(sony_phy_sram_write(s,SONY_PHY_SRAM_OFFSET+(uint32_t)(4*i),4,word(i)));
}
int main(void)
{
    struct sony_phy_sram s;uint8_t out[SONY_PHY_SRAM_BYTES+2];memset(out,0xa5,sizeof out);
    sony_phy_sram_reset(&s);
    assert(!sony_phy_sram_apply_requested(&s));
    assert(!sony_phy_sram_export_le(&s,out+1,SONY_PHY_SRAM_BYTES));
    for(size_t i=0;i<sizeof out;i++)assert(out[i]==0xa5);
    assert(sony_phy_sram_clear_storage(&s));
    for(size_t i=0;i<SONY_PHY_SRAM_WORDS;i++)assert(s.words[i]==0);
    feed(&s,SONY_PHY_SRAM_WORDS);
    assert(s.count==4096 && sony_phy_sram_apply_requested(&s));
    assert(sony_phy_sram_export_le(&s,out+1,SONY_PHY_SRAM_BYTES));
    assert(out[0]==0xa5 && out[sizeof out-1]==0xa5);
    for(size_t i=0;i<SONY_PHY_SRAM_WORDS;i++)assert(out[1+2*i]==(uint8_t)word(i) && out[2+2*i]==(uint8_t)(word(i)>>8));
    /* An early apply cannot be rescued by later writes, including all-zero tails. */
    assert(sony_phy_sram_clear_storage(&s));feed(&s,4095);
    assert(!sony_phy_sram_apply_requested(&s));
    assert(!sony_phy_sram_write(&s,0x1bffc,4,0) && s.count==4095 && s.failed);
    assert(!sony_phy_sram_export_le(&s,out,sizeof out));
    const uint32_t offsets[]={0x18004,0x17ffc,0x1c000,0x18001,UINT32_MAX};
    for(size_t i=0;i<sizeof offsets/sizeof offsets[0];i++) {
        assert(sony_phy_sram_clear_storage(&s));
        assert(!sony_phy_sram_write(&s,offsets[i],4,1) && !s.count && s.failed);
    }
    assert(sony_phy_sram_clear_storage(&s));feed(&s,1);
    assert(!sony_phy_sram_write(&s,0x18000,4,7) && s.count==1 && s.words[0]==word(0));
    assert(sony_phy_sram_clear_storage(&s));assert(!sony_phy_sram_write(&s,0x18000,4,0x10000));
    for(unsigned size=0;size<=8;size++)if(size!=4) {
        assert(sony_phy_sram_clear_storage(&s));assert(!sony_phy_sram_write(&s,0x18000,size,0));
    }
    assert(sony_phy_sram_clear_storage(&s));feed(&s,4096);
    assert(!sony_phy_sram_write(&s,0x1c000,4,0));assert(!sony_phy_sram_apply_requested(&s));
    sony_phy_sram_reset(&s);assert(!s.initialized && !s.failed && !s.apply_seen && !s.count);
    assert(!sony_phy_sram_clear_storage(NULL) && !sony_phy_sram_apply_requested(NULL));
    assert(!sony_phy_sram_write(NULL,0x18000,4,0));assert(!sony_phy_sram_export_le(NULL,out,sizeof out));
    sony_phy_sram_reset(NULL);
    puts("PASS_PHY_SRAM_STORAGE_ONLY: ordered 4096 halfwords/900 zero tail, prefix/failure/apply/export guards; no hash/ready claim");
}
