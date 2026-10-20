/* SPDX-License-Identifier: MIT */
#ifndef PIN_REGISTRY_CORE_H
#define PIN_REGISTRY_CORE_H
#include "vef-device.h"
#include <pthread.h>
struct pin_registry_lease {void *pointer;unsigned int destination;unsigned long long serial;long sender;};
struct pin_registry_owner {
    unsigned int source,count;
    const char *name;
    const unsigned int (*keys)[3];
    /* InfraBB compares full u32 keys and sets its own SID in the reply envelope. */
    unsigned int full_key_match, reply_sid;
    /* HDMI::PinHandler selects by complete u32 type and returns owned keys. */
    unsigned int type_only;
    /* count declares live objects; unused snapshot slots remain zero. */
    struct full_vef_snapshot state;
    struct pin_registry_lease replies[8];
};
int pin_registry_dispatch(struct pin_registry_owner *,unsigned int,void *,const struct full_imaging_io *,int,int *);
int pin_registry_release(struct pin_registry_owner *,unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void pin_registry_snapshot(struct pin_registry_owner *,struct full_vef_snapshot *);
/* Internal control consumer entry points. No state changes without an owned
 * request/peer/response being decoded by the explicit control dispatcher. */
struct pin_registry_owner *full_vef_registry(void);
struct pin_registry_owner *full_pinmem_registry(void);
struct pin_registry_owner *full_scalar_registry(void);
struct pin_registry_owner *full_adf_registry(void);
int pin_registry_connect_step(struct pin_registry_owner *,struct pin_registry_owner *,const unsigned int *,const unsigned int *,unsigned int);
void pin_registry_connect_fault(struct pin_registry_owner *,struct pin_registry_owner *);
#ifdef FULL_VEF_TEST
void pin_registry_test_reset(struct pin_registry_owner *);
void pin_registry_test_set_state(struct pin_registry_owner *,unsigned int,unsigned int);
#endif
#endif
