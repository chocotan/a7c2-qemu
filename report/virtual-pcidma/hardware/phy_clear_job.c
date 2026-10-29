#include "phy_clear_job.h"
static void invalidate(struct sony_phy_clear_job *s,bool poison)
{
    s->phase=SONY_CLEAR_WAIT;s->cleared=0;
    s->storage.count=0;s->storage.initialized=false;s->storage.failed=false;s->storage.apply_seen=false;
    if(poison)for(size_t i=0;i<SONY_PHY_SRAM_WORDS;i++)s->storage.words[i]=UINT16_MAX;
}
void sony_phy_clear_reset(struct sony_phy_clear_job *s)
{
    if(!s)return;
    *s=(struct sony_phy_clear_job){0};invalidate(s,true);
}
void sony_phy_clear_inputs(struct sony_phy_clear_job *s,uint32_t clock,uint32_t reset,bool external)
{
    if(!s)return;
    if(reset&15) {
        if(!s->in_reset) {invalidate(s,true);s->reset_seen=false;}
        if(reset&1)s->reset_seen=true;
        s->in_reset=true;return;
    }
    s->in_reset=false;
    if((clock&0x3e)!=0x3e || !external) {
        if(s->phase!=SONY_CLEAR_WAIT) {invalidate(s,false);s->reset_seen=false;}
        return;
    }
    if(s->phase==SONY_CLEAR_WAIT && s->reset_seen)s->phase=SONY_CLEAR_RUNNING;
}
bool sony_phy_clear_step(struct sony_phy_clear_job *s,unsigned budget)
{
    if(!s || !budget || budget>64 || s->phase!=SONY_CLEAR_RUNNING)return false;
    unsigned remaining=SONY_PHY_SRAM_WORDS-s->cleared;
    if(budget>remaining)budget=remaining;
    for(unsigned i=0;i<budget;i++)s->storage.words[s->cleared+i]=0;
    s->cleared+=budget;
    if(s->cleared==SONY_PHY_SRAM_WORDS) {
        s->storage.initialized=true;s->phase=SONY_CLEAR_DONE;
    }
    return true;
}
bool sony_phy_clear_complete(const struct sony_phy_clear_job *s)
{
    return s && s->phase==SONY_CLEAR_DONE && s->cleared==SONY_PHY_SRAM_WORDS && s->storage.initialized;
}
