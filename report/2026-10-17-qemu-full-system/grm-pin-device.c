/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include "grm-pin-device.h"
/* CP OsdPinIF raw469ace..469b06 owns one DataflowInfraPin. Get46a840
 * ignores query attributes and reads its own OSD/INOUT0 object. */
static const unsigned int keys[1][3]={{1,3,0}};
static struct pin_registry_owner registry={.source=FULL_GRM_PIN_CP,.count=1,.name="GRMPIN",
    .keys=keys,.full_key_match=1,.reply_sid=FULL_GRM_PIN_CP,.ignore_query_keys=1};
struct pin_registry_owner *full_grm_pin_registry(void){return &registry;}
int full_grm_pin_dispatch(unsigned int d,void *p,const struct full_imaging_io *io,int enabled,int *rc){return pin_registry_dispatch(&registry,d,p,io,enabled,rc);}
int full_grm_pin_release_reply(unsigned int d,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){return pin_registry_release(&registry,d,p,release,record,rc);}
void full_grm_pin_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
#ifdef FULL_VEF_TEST
void full_grm_pin_test_reset(void){pin_registry_test_reset(&registry);}
#endif
