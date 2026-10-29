#ifndef SONY_PHY_CALIB_H
#define SONY_PHY_CALIB_H
#include <stdbool.h>
#include <stdint.h>
/* Explicit TEST-board functional calibration/link policy. NOT silicon
 * calibration or SerDes training: it only gates on real model inputs held
 * continuously (authentic applied table, IDDQ cleared, clocks/resets,
 * LTSSM enable, peer presence). Losing any input drops lane/link again. */
#define SONY_PHY_CALIB_TICKS 16u
#define SONY_PHY_LINK_TICKS 8u
struct sony_phy_calib {
    unsigned calib_ticks,link_ticks;
    bool calib_active,calibrated,link_armed,link;
    bool in_applied,in_powerdown_cleared,in_clocks,in_ltssm,in_peer;
};
void sony_phy_calib_reset(struct sony_phy_calib *);
void sony_phy_calib_inputs(struct sony_phy_calib *,bool applied,bool powerdown_cleared,bool clocks,bool ltssm,bool peer);
bool sony_phy_calib_tick(struct sony_phy_calib *);
bool sony_phy_calib_busy(const struct sony_phy_calib *);
uint32_t sony_phy_calib_lane_status(const struct sony_phy_calib *); /* 15 uncalibrated, 0 calibrated */
uint32_t sony_phy_calib_link_status(const struct sony_phy_calib *);  /* bit1 when link, else 0 */
#endif
