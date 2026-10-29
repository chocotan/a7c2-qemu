#include "phy_calib.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void)
{
    struct sony_phy_calib s,before;sony_phy_calib_reset(&s);
    assert(sony_phy_calib_lane_status(&s)==15 && sony_phy_calib_link_status(&s)==0 && !sony_phy_calib_busy(&s));
    /* Each missing input alone blocks calibration. */
    sony_phy_calib_inputs(&s,true,true,false,true,true);assert(!sony_phy_calib_busy(&s));
    sony_phy_calib_inputs(&s,true,false,true,true,true);assert(!sony_phy_calib_busy(&s));
    sony_phy_calib_inputs(&s,false,true,true,true,true);assert(!sony_phy_calib_busy(&s));
    /* All inputs: exactly 16 ticks to calibrated, LTSSM set early: 8 more to link. */
    sony_phy_calib_inputs(&s,true,true,true,true,true);
    assert(sony_phy_calib_busy(&s));
    for(unsigned i=0;i<15;i++)assert(sony_phy_calib_tick(&s) && sony_phy_calib_lane_status(&s)==15);
    assert(sony_phy_calib_tick(&s) && sony_phy_calib_lane_status(&s)==0 && sony_phy_calib_link_status(&s)==0);
    for(unsigned i=0;i<7;i++)assert(sony_phy_calib_tick(&s) && sony_phy_calib_link_status(&s)==0);
    assert(sony_phy_calib_tick(&s) && sony_phy_calib_link_status(&s)==2);
    assert(!sony_phy_calib_tick(&s) && !sony_phy_calib_busy(&s)); /* steady state */
    /* Peer/LTSSM/clock loss drops link; lane needs calib inputs. */
    sony_phy_calib_inputs(&s,true,true,true,false,true);assert(sony_phy_calib_link_status(&s)==0 && sony_phy_calib_lane_status(&s)==0);
    sony_phy_calib_inputs(&s,true,true,true,true,true);
    for(unsigned i=0;i<8;i++)sony_phy_calib_tick(&s);
    assert(sony_phy_calib_link_status(&s)==2);
    sony_phy_calib_inputs(&s,true,true,false,true,true);assert(sony_phy_calib_lane_status(&s)==15 && sony_phy_calib_link_status(&s)==0);
    /* Mid-calibration clock loss restarts from zero. */
    sony_phy_calib_inputs(&s,true,true,true,true,true);sony_phy_calib_tick(&s);
    sony_phy_calib_inputs(&s,true,true,false,true,true);assert(!sony_phy_calib_busy(&s));
    sony_phy_calib_inputs(&s,true,true,true,true,true);
    for(unsigned i=0;i<16;i++)sony_phy_calib_tick(&s);
    assert(sony_phy_calib_lane_status(&s)==0);
    /* Late table corruption (applied=false) drops calibration and link. */
    for(unsigned i=0;i<8;i++)sony_phy_calib_tick(&s);
    assert(sony_phy_calib_link_status(&s)==2);
    sony_phy_calib_inputs(&s,false,true,true,true,true);assert(sony_phy_calib_lane_status(&s)==15 && sony_phy_calib_link_status(&s)==0);
    /* No phantom progress without tick; reset is total. */
    before=s;assert(!sony_phy_calib_tick(&s));assert(!memcmp(&before,&s,sizeof s));
    sony_phy_calib_reset(&s);assert(sony_phy_calib_lane_status(&s)==15);
    sony_phy_calib_reset(NULL);sony_phy_calib_inputs(NULL,true,true,true,true,true);
    assert(!sony_phy_calib_tick(NULL) && !sony_phy_calib_busy(NULL));
    assert(sony_phy_calib_lane_status(NULL)==15 && sony_phy_calib_link_status(NULL)==0);
    puts("PASS_TEST_CALIB_POLICY_ONLY: gated 16+8 tick transitions, all input-loss paths drop lane/link; NOT silicon calibration/training");
}
