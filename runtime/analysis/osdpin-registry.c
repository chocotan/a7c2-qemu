/* SPDX-License-Identifier: MIT */
/* CP raw469b06/583582: sole cold pin; raw46a840 Get has own outer replySID.
 * shortcut: only observed 130 keys, add fixed canonical selection if other keys are needed. */
#include "osdpin-registry.h"
#include "device-models/pin-registry-core.h"
static const unsigned int keys[1][3]={{1,3,0}};
static struct pin_registry_owner registry={
    .source=NATIVE_OSDPIN_CP,.count=1,.name="OSDPIN",.keys=keys,
    .full_key_match=1,.reply_sid=NATIVE_OSDPIN_CP
};
int native_osdpin_dispatch(unsigned int id,void *request,const struct full_imaging_io *io,int enabled,int *rc){
    int handled=pin_registry_dispatch(&registry,id,request,io,enabled,rc);
    if(handled && !*rc && io->record)
        io->record("FULL_OSDPIN_SCOPE ","metadata_get_only=1 original_graphics_event=0x80000001 event_destination=0x008f013a event_payload_bytes=200 event_emitted=0 event_consumer_verified=0 osd_initialized=0 pixels_consumed=0 camera_startup_verified=0");
    return handled;
}
int native_osdpin_release_reply(unsigned int id,void *reply,int (*release)(unsigned int,void *),
                               void (*record)(const char *,const char *),int *rc){
    return pin_registry_release(&registry,id,reply,release,record,rc);
}
void native_osdpin_snapshot(struct full_vef_snapshot *out){pin_registry_snapshot(&registry,out);}
