#include "phy_clear_job.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    struct sony_phy_clear_job s,before;sony_phy_clear_reset(&s);
    assert(!sony_phy_clear_complete(&s));
    sony_phy_clear_inputs(&s,0x3e,0,true);
    assert(s.phase==SONY_CLEAR_WAIT && !sony_phy_clear_step(&s,64)); /* no reset observation */
    sony_phy_clear_inputs(&s,0,15,false);assert(s.reset_seen && s.in_reset);
    sony_phy_clear_inputs(&s,0,0,true);assert(s.phase==SONY_CLEAR_WAIT);
    sony_phy_clear_inputs(&s,0x3e,0,false);assert(s.phase==SONY_CLEAR_WAIT);
    sony_phy_clear_inputs(&s,0x3e,0,true);assert(s.phase==SONY_CLEAR_RUNNING);
    before=s;assert(!sony_phy_clear_step(&s,0) && !sony_phy_clear_step(&s,65));assert(!memcmp(&before,&s,sizeof s));
    assert(sony_phy_clear_step(&s,64) && s.cleared==64 && !sony_phy_clear_complete(&s));
    for(unsigned i=0;i<4096;i++)assert(s.storage.words[i]==(i<64?0:UINT16_MAX));
    for(unsigned i=0;i<62;i++)assert(sony_phy_clear_step(&s,64));
    assert(s.cleared==4032 && !sony_phy_clear_complete(&s));
    assert(sony_phy_clear_step(&s,64) && sony_phy_clear_complete(&s));
    for(unsigned i=0;i<4096;i++)assert(!s.storage.words[i]);
    assert(sony_phy_sram_write(&s.storage,0x18000,4,0x1234));
    assert(!sony_phy_clear_step(&s,64) && s.storage.words[0]==0x1234); /* no re-clearing firmware */
    sony_phy_clear_inputs(&s,0,0,true);assert(!sony_phy_clear_complete(&s) && !s.reset_seen);
    sony_phy_clear_inputs(&s,0x3e,0,true);assert(s.phase==SONY_CLEAR_WAIT);
    sony_phy_clear_inputs(&s,0x3e,8,true);sony_phy_clear_inputs(&s,0x3e,0,true);
    assert(s.phase==SONY_CLEAR_WAIT); /* APB-only reset is not cold powerup proof */
    sony_phy_clear_inputs(&s,0x3e,1,true);sony_phy_clear_inputs(&s,0x3e,0,true);
    assert(sony_phy_clear_step(&s,64));sony_phy_clear_inputs(&s,0x3e,1,true);
    assert(!s.cleared && !sony_phy_clear_complete(&s) && s.storage.words[0]==UINT16_MAX);
    sony_phy_clear_reset(NULL);sony_phy_clear_inputs(NULL,0,0,false);
    assert(!sony_phy_clear_step(NULL,1) && !sony_phy_clear_complete(NULL));
    puts("PASS_TEST_CLEAR_JOB_ONLY: actual bounded clearing/prerequisites/reset/clock-loss, NOT original silicon producer");
}
