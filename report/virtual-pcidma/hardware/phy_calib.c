#include "phy_calib.h"
static void derive(struct sony_phy_calib *s)
{
    bool calib_ok=s->in_applied&&s->in_powerdown_cleared&&s->in_clocks;
    if(!calib_ok) {s->calib_active=false;s->calib_ticks=0;s->calibrated=false;}
    else if(!s->calibrated)s->calib_active=true;
    s->link_armed=s->calibrated&&s->in_ltssm&&s->in_peer&&s->in_clocks;
    if(!s->link_armed) {s->link=false;s->link_ticks=0;}
}
void sony_phy_calib_reset(struct sony_phy_calib *s)
{
    if(s)*s=(struct sony_phy_calib){0};
}
void sony_phy_calib_inputs(struct sony_phy_calib *s,bool applied,bool powerdown_cleared,bool clocks,bool ltssm,bool peer)
{
    if(!s)return;
    s->in_applied=applied;s->in_powerdown_cleared=powerdown_cleared;
    s->in_clocks=clocks;s->in_ltssm=ltssm;s->in_peer=peer;
    derive(s);
}
bool sony_phy_calib_tick(struct sony_phy_calib *s)
{
    if(!s)return false;
    if(s->calib_active) {
        if(++s->calib_ticks>=SONY_PHY_CALIB_TICKS) {s->calib_active=false;s->calibrated=true;derive(s);}
        return true;
    }
    if(s->link_armed&&!s->link) {
        if(++s->link_ticks>=SONY_PHY_LINK_TICKS)s->link=true;
        return true;
    }
    return false;
}
bool sony_phy_calib_busy(const struct sony_phy_calib *s)
{
    return s&&(s->calib_active||(s->link_armed&&!s->link));
}
uint32_t sony_phy_calib_lane_status(const struct sony_phy_calib *s)
{
    return s&&s->calibrated?0:15;
}
uint32_t sony_phy_calib_link_status(const struct sony_phy_calib *s)
{
    return s&&s->link?2:0;
}
