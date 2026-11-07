/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include "drawinfo-device.h"
/* CP raw c0053c/c00548, constructor 532800..53285a. Independent virtual
 * objects, not numeric DRAWINFO model8/9 and not a RAW image endpoint. */
static const unsigned int keys[2][3]={{0,1,0},{6,1,0}};
static struct pin_registry_owner registry={.source=FULL_DRAWINFO_CP,.count=2,.name="DRAWINFO",
    .keys=keys,.full_key_match=1,.reply_sid=0};
struct pin_registry_owner *full_drawinfo_registry(void){return &registry;}
int full_drawinfo_dispatch(unsigned int d,void *p,const struct full_imaging_io *io,int enabled,int *rc){return pin_registry_dispatch(&registry,d,p,io,enabled,rc);}
int full_drawinfo_release_reply(unsigned int d,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){return pin_registry_release(&registry,d,p,release,record,rc);}
void full_drawinfo_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
#ifdef FULL_VEF_TEST
void full_drawinfo_test_reset(void){pin_registry_test_reset(&registry);}
#endif
