/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include "infrabb-device.h"
/* Original CP raw fe7808..fe7948. Full-u32 matching, not low-byte aliases.
 * This explicit virtual owner constructs its own cold objects. These are not
 * observations of the unexecuted CP's live state or image buffers. */
static const unsigned int keys[21][3]={
    {0,1,0},{0,1,1},{0,1,2},{0,1,3},
    {0,2,0},{0,2,1},{0,2,2},{0,2,3},
    {8,1,0},{8,2,0},{6,2,0},
    {0,1,10},{0,1,11},{0,1,12},{0,1,13},
    {0,2,10},{0,2,11},{0,2,12},{0,2,13},{8,1,10},{8,2,10}};
static struct pin_registry_owner registry={.source=FULL_INFRABB_CP,.count=21,.name="INFRABB",
    .keys=keys,.full_key_match=1,.reply_sid=FULL_INFRABB_CP};
struct pin_registry_owner *full_infrabb_registry(void){return &registry;}
int full_infrabb_dispatch(unsigned int d,void *p,const struct full_imaging_io *io,int enabled,int *rc){return pin_registry_dispatch(&registry,d,p,io,enabled,rc);}
int full_infrabb_release_reply(unsigned int d,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){return pin_registry_release(&registry,d,p,release,record,rc);}
void full_infrabb_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
#ifdef FULL_VEF_TEST
void full_infrabb_test_reset(void){pin_registry_test_reset(&registry);}
#endif
