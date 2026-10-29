#ifndef SONY_PHY_CLEAR_JOB_H
#define SONY_PHY_CLEAR_JOB_H
#include "phy_sram.h"
/* Explicit functional TEST-board policy, NOT a recovered silicon producer:
 * cold powerup-reset observation, all five gates, four resets released,
 * external SRAM selected, and actual bounded storage clearing. */
enum sony_clear_phase {SONY_CLEAR_WAIT,SONY_CLEAR_RUNNING,SONY_CLEAR_DONE};
struct sony_phy_clear_job {
    struct sony_phy_sram storage;
    enum sony_clear_phase phase;
    unsigned cleared;
    bool reset_seen,in_reset;
};
void sony_phy_clear_reset(struct sony_phy_clear_job *);
void sony_phy_clear_inputs(struct sony_phy_clear_job *,uint32_t clock,uint32_t reset,bool external);
bool sony_phy_clear_step(struct sony_phy_clear_job *,unsigned budget);
bool sony_phy_clear_complete(const struct sony_phy_clear_job *);
#endif
