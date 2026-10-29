/* SPDX-License-Identifier: MIT */
#include "cp-upm-hcrn.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

struct cp_upm_hcrn {
    pid_t owner;
    pthread_mutex_t mutex;
    struct cp_upm_hcrn_view view;
    void (*callback)(struct cp_upm_hcrn *, unsigned char *, unsigned char *);
};
static const unsigned char request[16]={0x62,0x01,0x92,0};
static int lock(struct cp_upm_hcrn *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD;
    int rc=pthread_mutex_lock(&s->mutex);return rc?-rc:0;
}
static int unlock(struct cp_upm_hcrn *s,int rc) {
    pthread_mutex_unlock(&s->mutex);return rc;
}
static uint32_t get32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static uint32_t fnv(const unsigned char *p,size_t n) {
    uint32_t h=UINT32_C(2166136261);
    for (size_t i=0;i<n;i++) h=(h^p[i])*UINT32_C(16777619);
    return h;
}
static int all_known(const unsigned char *p,size_t n) {
    for (size_t i=0;i<n;i++) if (p[i]!=1) return 0;
    return 1;
}
static int overlap(const unsigned char *a,const unsigned char *b) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x>UINTPTR_MAX-15 || y>UINTPTR_MAX-15 || (x<=y?y-x<16:x-y<16);
}
/* Only the recognized finite caller reaches the internal c0dd1a analogue. */
static void read_cache(struct cp_upm_hcrn *s,unsigned char *body,unsigned char *known) {
    memcpy(body,s->view.cache,16);memcpy(known,s->view.cache_known,16);
}
struct cp_upm_hcrn *cp_upm_hcrn_create(void) {
    struct cp_upm_hcrn *s=calloc(1,sizeof *s);if (!s) return NULL;
    s->owner=getpid();int rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    /* c0dc8c/90's zero initializer, never the AP image's initial tuple. */
    memset(s->view.cache_known,1,16);
    s->view.cache_fnv=fnv(s->view.cache,16);s->view.initialized_cache_only=1;
    s->callback=read_cache;s->view.virtual_registered=1;return s;
}
int cp_upm_hcrn_consume_publication(struct cp_upm_hcrn *s,uint32_t destination,
    const unsigned char *packet,size_t size,const unsigned char *known,size_t known_size) {
    int rc=lock(s);if (rc) return rc;
    if (!packet || !known || size!=20 || known_size!=20) return unlock(s,-EINVAL);
    if (destination!=CP_UPM_HCRN_DESTINATION) return unlock(s,-ENOTSUP);
    if (!all_known(known,20)) return unlock(s,-EAGAIN);
    if (get32(packet)!=CP_UPM_HCRN_PUBLICATION) return unlock(s,-ENOTSUP);
    if (s->view.serial==UINT64_MAX || s->view.generation==UINT64_MAX ||
        s->view.publications_consumed==UINT64_MAX) return unlock(s,-EOVERFLOW);
    /* 596b60 -> 596e30..46 consumes actual 20B, then copies H,C,R,N. */
    memcpy(s->view.cache,packet+4,16);memcpy(s->view.cache_known,known+4,16);
    s->view.publication_fnv=fnv(packet,20);s->view.cache_fnv=fnv(s->view.cache,16);
    s->view.serial++;s->view.generation++;s->view.publications_consumed++;
    s->view.initialized_cache_only=0;return unlock(s,0);
}
int cp_upm_hcrn_query_in_place(struct cp_upm_hcrn *s,uint32_t handle,
    unsigned char *body,size_t size,unsigned char *known,size_t known_size) {
    int rc=lock(s);if (rc) return rc;
    if (!body || !known || size!=16 || known_size!=16 || overlap(body,known))
        return unlock(s,-EINVAL);
    if (handle!=CP_UPM_HCRN_HANDLE) return unlock(s,-ENOTSUP);
    if (!all_known(known,16)) return unlock(s,-EAGAIN);
    if (memcmp(body,request,16)) return unlock(s,-ENOTSUP);
    if (s->view.serial==UINT64_MAX || s->view.queries==UINT64_MAX ||
        s->view.callbacks==UINT64_MAX) return unlock(s,-EOVERFLOW);
    s->view.request_fnv=fnv(body,16);s->view.requested=get32(body);
    s->callback(s,body,known);
    memcpy(s->view.last_readback,body,16);s->view.readback_fnv=fnv(body,16);
    s->view.last_query_generation=s->view.generation;
    s->view.serial++;s->view.queries++;s->view.callbacks++;return unlock(s,0);
}
int cp_upm_hcrn_snapshot(struct cp_upm_hcrn *s,struct cp_upm_hcrn_view *out) {
    int rc=lock(s);if (rc) return rc;
    if (!out) return unlock(s,-EINVAL);
    *out=s->view;return unlock(s,0);
}
int cp_upm_hcrn_destroy(struct cp_upm_hcrn *s) {
    int rc=lock(s);if (rc) return rc;
    unlock(s,0);rc=pthread_mutex_destroy(&s->mutex);
    if (rc) return -rc;
    free(s);return 0;
}
