/* SPDX-License-Identifier: MIT */
#include "cp-slot1-metadata.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>

/* Only the pinned original I3 sender. No registry/receiver, CP ACK, source
 * rewrite, cache preset or hardware-ready notification is provided here. */
struct cp_slot1_metadata {
    pid_t owner;
    pthread_mutex_t mutex;
    struct cp_meta_view view;
    struct cp_meta_io io;
    void *context;
    struct cp_meta_packet retained;
};
static int lock(struct cp_slot1_metadata *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD;
    int rc=pthread_mutex_lock(&s->mutex);return rc?-rc:0;
}
static int unlock(struct cp_slot1_metadata *s,int rc) {
    pthread_mutex_unlock(&s->mutex);return rc;
}
static uint16_t normalized(const struct cp_meta_inputs *in) {
    uint32_t value=in->t91==1?(uint32_t)(3u*in->t20):in->t20;
    uint64_t product=(uint64_t)value*UINT32_C(0xcccccccd);
    return (uint16_t)(product>>(in->t91==1?36:35));
}
static void put16(unsigned char *out,uint32_t value) {
    out[0]=(unsigned char)value;out[1]=(unsigned char)(value>>8);
}
static void put32(unsigned char *out,uint32_t value) {
    for (unsigned int i=0;i<4;i++) out[i]=(unsigned char)(value>>(8*i));
}
int cp_meta_format(const struct cp_meta_inputs *input,enum cp_meta_form form,
    unsigned char *out,size_t size) {
    static const unsigned int primary[]={4,2,0,2,1,15,3,15,5};
    static const unsigned int alternate[]={4,2,2,2,2,15,2,15,5};
    static const unsigned int map_y[]={0,2,15,3,3,3,15,3,1,2,15,1,4};
    if (!input || !out || size!=CP_META_BYTES) return -EINVAL;
    if (input->input_I!=3 || (unsigned int)form>CP_META_ALTERNATE) return -ENOTSUP;
    struct cp_meta_inputs in=*input;
    unsigned int p=in.x<9?primary[in.x]:15;
    unsigned int a=in.x<9?alternate[in.x]:15;
    unsigned int y=in.y<13?map_y[in.y]:15;
    unsigned int rate=(in.y==3 || in.y==5 || in.y==7) && in.w<=2?in.w+1:0;
    unsigned int qmode=in.q==1 || in.q==2;
    uint32_t packed=y | p<<4 | (uint32_t)(in.z==1)<<8 | rate<<10 |
        qmode<<13 | (uint32_t)normalized(&in)<<16;
    unsigned int use_alternate=form==CP_META_ALTERNATE || (form==CP_META_MODE && in.alternate);
    if (use_alternate) packed=(packed&~UINT32_C(0x3f0)) | a<<4;
    put16(out,form==CP_META_MODE?0x0d:3);
    put16(out+2,form==CP_META_MODE?8:form==CP_META_PRIMARY?0x20:0x21);
    put16(out+4,0);put16(out+6,form==CP_META_MODE?0x10:0);
    put16(out+8,form==CP_META_MODE?0x8000:0x8100);
    put32(out+10,packed);put32(out+14,use_alternate && in.a==1?1:0);
    return 0;
}
struct cp_slot1_metadata *cp_meta_create(const struct cp_meta_cache *cache,
    const struct cp_meta_io *io,void *context) {
    if (!cache || !io || !io->allocate || !io->send || !io->release) { errno=EINVAL;return NULL; }
    struct cp_slot1_metadata *s=calloc(1,sizeof *s);if (!s) return NULL;
    s->owner=getpid();
    int rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    s->view.cache=*cache;s->io=*io;s->context=context;return s;
}
int cp_meta_destroy(struct cp_slot1_metadata *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy || s->view.retained) return unlock(s,-EBUSY);
    unlock(s,0);pthread_mutex_destroy(&s->mutex);free(s);return 0;
}
static void note_error(struct cp_meta_result *r,int rc) {
    if (!r->first_io_error) r->first_io_error=rc;
}
static int release_owned(struct cp_slot1_metadata *s,const struct cp_meta_packet *packet,
    struct cp_meta_result *r) {
    int rc=s->io.release(s->context,CP_META_SID,packet);
    if (!rc) return 0;
    r->cleanup_failures++;note_error(r,rc);
    int guard=lock(s);if (guard) return guard;
    s->retained=*packet;s->view.retained=1;s->view.fault=1;
    return unlock(s,rc<0?rc:-EIO);
}
static int attempt(struct cp_slot1_metadata *s,const struct cp_meta_inputs *in,
    enum cp_meta_form form,struct cp_meta_result *r) {
    struct cp_meta_packet packet={0};r->attempted++;
    int rc=s->io.allocate(s->context,CP_META_SID,CP_META_BYTES,&packet);
    if (rc) { r->allocation_failures++;note_error(r,rc);return 0; }
    r->allocated++;
    if (!packet.payload || packet.size!=CP_META_BYTES || packet.source!=CP_META_SOURCE) {
        /* An invalid successful allocator is not an ordinary original failure.
         * Preserve its lease if retirement fails; never dereference bad bytes. */
        note_error(r,-EPROTO);
        rc=release_owned(s,&packet,r);if (rc) return rc;
        return -EPROTO;
    }
    rc=cp_meta_format(in,form,packet.payload,packet.size);if (rc) return rc;
    rc=s->io.send(s->context,CP_META_SID,&packet);
    if (!rc) { r->submitted++;return 0; } /* packet may already be retired */
    r->send_failures++;note_error(r,rc);
    return release_owned(s,&packet,r);
}
int cp_meta_publish(struct cp_slot1_metadata *s,const struct cp_meta_inputs *input,
    struct cp_meta_result *out) {
    int rc=lock(s);if (rc) return rc;
    if (!input || !out) return unlock(s,-EINVAL);
    if (s->view.busy) return unlock(s,-EBUSY);
    if (s->view.fault) return unlock(s,-EIO);
    if (input->input_I!=3) return unlock(s,-ENOTSUP);
    struct cp_meta_inputs in=*input;
    struct cp_meta_cache old=s->view.cache;
    struct cp_meta_cache next={in.x,in.y,in.z,in.w,in.q,in.a,normalized(&in)};
    struct cp_meta_result result={0};
    int changed=old.x!=next.x || old.y!=next.y || old.z!=next.z || old.w!=next.w ||
        old.q!=next.q || old.a!=next.a || old.n16!=next.n16;
    s->view.busy=1;unlock(s,0);
    if (old.x!=in.x) rc=attempt(s,&in,CP_META_MODE,&result);
    if (!rc && changed) rc=attempt(s,&in,CP_META_PRIMARY,&result);
    if (!rc && changed) rc=attempt(s,&in,CP_META_ALTERNATE,&result);
    int guard=lock(s);if (guard) return guard;
    if (rc) s->view.fault=1;
    else if (changed) { s->view.cache=next;result.cache_committed=1; }
    s->view.busy=0;*out=result;return unlock(s,rc);
}
int cp_meta_retry_release(struct cp_slot1_metadata *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy) return unlock(s,-EBUSY);
    if (!s->view.retained) return unlock(s,-ENOENT);
    struct cp_meta_packet packet=s->retained;s->view.busy=1;unlock(s,0);
    rc=s->io.release(s->context,CP_META_SID,&packet);
    int guard=lock(s);if (guard) return guard;
    if (!rc) { s->view.retained=0;s->retained=(struct cp_meta_packet){0}; }
    s->view.busy=0;return unlock(s,rc);
}
int cp_meta_snapshot(struct cp_slot1_metadata *s,struct cp_meta_view *out) {
    int rc=lock(s);if (rc) return rc;
    if (!out) return unlock(s,-EINVAL);
    *out=s->view;return unlock(s,0);
}
