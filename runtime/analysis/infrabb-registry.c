/* SPDX-License-Identifier: MIT */
/* Virtual Get-only owner: original CP raw fe7808, ctor59b918/583582, Get cdba0.
 * Cold metadata only; no original CP task, connections, buffers or readiness. */
#include "infrabb-registry.h"
#include "drawinfo-registry.h"
#include "device-models/pin-registry-core.h"
static const unsigned int keys[21][3] = {
    {0,1,0},{0,1,1},{0,1,2},{0,1,3},{0,2,0},{0,2,1},{0,2,2},{0,2,3},
    {8,1,0},{8,2,0},{6,2,0},
    {0,1,10},{0,1,11},{0,1,12},{0,1,13},{0,2,10},{0,2,11},{0,2,12},{0,2,13},
    {8,1,10},{8,2,10}
};
static struct pin_registry_owner registry = {
    .source=NATIVE_INFRABB_CP, .count=21, .name="INFRABB", .keys=keys,
    .full_key_match=1, .reply_sid=NATIVE_INFRABB_CP
};
int native_infrabb_dispatch(unsigned int id, void *request, const struct full_imaging_io *io,
                           int enabled, int *result) {
    return pin_registry_dispatch(&registry,id,request,io,enabled,result);
}
int native_infrabb_release_reply(unsigned int id, void *reply, int (*release)(unsigned int,void *),
                                void (*record)(const char *,const char *), int *result) {
    return pin_registry_release(&registry,id,reply,release,record,result);
}
void native_infrabb_snapshot(struct full_vef_snapshot *out) {
    pin_registry_snapshot(&registry,out);
}

/* Keep native owners in the existing compiled unit used by both launchers.
 * DrawInfo: CP raw c0053c, full ctor5327d8, Get531fc0; found keys only. */
static const unsigned int draw_keys[2][3] = {{0,1,0},{6,1,0}};
static struct pin_registry_owner draw_registry = {
    .source=NATIVE_DRAWINFO_CP, .count=2, .name="DRAWINFO", .keys=draw_keys,
    .full_key_match=1, .reply_sid=0
};
int native_drawinfo_dispatch(unsigned int id, void *request, const struct full_imaging_io *io,
                            int enabled, int *result) {
    return pin_registry_dispatch(&draw_registry,id,request,io,enabled,result);
}
int native_drawinfo_release_reply(unsigned int id, void *reply, int (*release)(unsigned int,void *),
                                 void (*record)(const char *,const char *), int *result) {
    return pin_registry_release(&draw_registry,id,reply,release,record,result);
}
void native_drawinfo_snapshot(struct full_vef_snapshot *out) {
    pin_registry_snapshot(&draw_registry,out);
}
