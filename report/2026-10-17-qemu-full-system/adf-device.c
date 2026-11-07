/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include "adf-device.h"
/* CP raw c0b234, loaded by 572bf0 into ten independently constructed objects.
 * 5727ee compares all three u32 query fields, unlike the low-byte registries. */
static const unsigned int keys[10][3]={
    {0,1,0},{2,1,0},{2,1,1},{2,1,2},{3,1,0},
    {5,1,0},{2,2,0},{2,2,1},{2,2,2},{5,2,0}};
static struct pin_registry_owner registry={.source=FULL_ADF_CP,.count=10,.name="ADF",.keys=keys,.full_key_match=1};
struct pin_registry_owner *full_adf_registry(void){return &registry;}
int full_adf_dispatch(unsigned int d,void *p,const struct full_imaging_io *io,int enabled,int *rc){return pin_registry_dispatch(&registry,d,p,io,enabled,rc);}
int full_adf_release_reply(unsigned int d,void *p,int (*release)(unsigned int,void *),void (*record)(const char *,const char *),int *rc){return pin_registry_release(&registry,d,p,release,record,rc);}
void full_adf_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
#ifdef FULL_VEF_TEST
void full_adf_test_reset(void){pin_registry_test_reset(&registry);}
void full_adf_test_set_state(unsigned int i,unsigned int value){pin_registry_test_set_state(&registry,i,value);}
#endif
