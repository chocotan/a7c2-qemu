/* SPDX-License-Identifier: MIT */
#include "cp-sync-resources.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

struct backing {
    unsigned char *data;
    size_t bytes;
    unsigned int references, frozen;
    uint64_t identity;
};
struct reference { uint64_t token; unsigned int id; };
struct cp_sync_resources {
    pid_t owner;
    pthread_mutex_t mutex;
    size_t budget, bytes;
    struct backing buffers[CP_SYNC_RESOURCE_COUNT];
    unsigned int binding[CP_SYNC_RESOURCE_COUNT]; /* buffer index+1, zero unbound */
    struct reference leases[CP_SYNC_LEASE_COUNT];
};
static _Atomic uint64_t next_token=1;

static int lock(struct cp_sync_resources *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD; /* before possibly inherited mutex */
    int rc=pthread_mutex_lock(&s->mutex);
    return rc?-rc:0;
}
static int unlock(struct cp_sync_resources *s,int rc) {
    pthread_mutex_unlock(&s->mutex);return rc;
}
static struct reference *reference(struct cp_sync_resources *s,uint64_t token) {
    if (token) for (unsigned int i=0;i<CP_SYNC_LEASE_COUNT;i++)
        if (s->leases[i].token==token) return &s->leases[i];
    return NULL;
}
static int issue(struct cp_sync_resources *s,unsigned int id,uint64_t *out) {
    if (!out || id>=CP_SYNC_RESOURCE_COUNT || !s->binding[id]) return -EINVAL;
    for (unsigned int i=0;i<CP_SYNC_LEASE_COUNT;i++) if (!s->leases[i].token) {
        uint64_t token=atomic_load(&next_token);
        for (;;) {
            if (!token) return -EOVERFLOW;
            uint64_t next=token==UINT64_MAX?0:token+1;
            if (atomic_compare_exchange_weak(&next_token,&token,next)) break;
        }
        s->leases[i]=(struct reference){token,id};
        s->buffers[s->binding[id]-1].references++;
        *out=s->leases[i].token;return 0;
    }
    return -ENOSPC;
}
struct cp_sync_resources *cp_sync_create(size_t budget) {
    if (!budget) { errno=EINVAL;return NULL; }
    struct cp_sync_resources *s=calloc(1,sizeof *s);
    if (!s) return NULL;
    int rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    s->owner=getpid();s->budget=budget;return s;
}
int cp_sync_destroy(struct cp_sync_resources *s) {
    int rc=lock(s);if (rc) return rc;
    for (unsigned int i=0;i<CP_SYNC_RESOURCE_COUNT;i++)
        if (s->buffers[i].data) return unlock(s,-EBUSY);
    unlock(s,0);pthread_mutex_destroy(&s->mutex);free(s);return 0;
}
int cp_sync_allocate(struct cp_sync_resources *s,unsigned int id,size_t bytes,uint64_t *out) {
    int rc=lock(s);if (rc) return rc;
    if (id>=CP_SYNC_RESOURCE_COUNT || !bytes || !out) return unlock(s,-EINVAL);
    if (s->binding[id]) return unlock(s,-EBUSY);
    if (bytes>s->budget-s->bytes) return unlock(s,-ENOSPC);
    unsigned int index=0;
    while (index<CP_SYNC_RESOURCE_COUNT && s->buffers[index].data) index++;
    if (index==CP_SYNC_RESOURCE_COUNT) return unlock(s,-ENOSPC);
    unsigned char *data=calloc(1,bytes);
    if (!data) return unlock(s,-ENOMEM);
    s->buffers[index]=(struct backing){.data=data,.bytes=bytes};s->binding[id]=index+1;
    rc=issue(s,id,out);
    if (rc) { free(data);memset(&s->buffers[index],0,sizeof s->buffers[index]);s->binding[id]=0; }
    else { s->bytes+=bytes;s->buffers[index].identity=*out; }
    return unlock(s,rc);
}
int cp_sync_alias(struct cp_sync_resources *s,unsigned int id,uint64_t source,uint64_t *out) {
    int rc=lock(s);if (rc) return rc;
    if (id>=CP_SYNC_RESOURCE_COUNT || !out) return unlock(s,-EINVAL);
    struct reference *from=reference(s,source);
    if (!from) return unlock(s,-ESTALE);
    if (s->binding[id]) return unlock(s,-EBUSY);
    s->binding[id]=s->binding[from->id];
    rc=issue(s,id,out);
    if (rc) s->binding[id]=0;
    else s->buffers[s->binding[id]-1].frozen=1;
    return unlock(s,rc);
}
int cp_sync_acquire(struct cp_sync_resources *s,unsigned int id,uint64_t *out) {
    int rc=lock(s);if (rc) return rc;
    rc=issue(s,id,out);
    if (!rc) s->buffers[s->binding[id]-1].frozen=1;
    return unlock(s,rc);
}
int cp_sync_release(struct cp_sync_resources *s,uint64_t token) {
    int rc=lock(s);if (rc) return rc;
    struct reference *r=reference(s,token);
    if (!r) return unlock(s,-ESTALE);
    s->buffers[s->binding[r->id]-1].references--;r->token=0;
    return unlock(s,0);
}
int cp_sync_free(struct cp_sync_resources *s,unsigned int id,uint64_t allocation) {
    int rc=lock(s);if (rc) return rc;
    if (id>=CP_SYNC_RESOURCE_COUNT) return unlock(s,-EINVAL);
    unsigned int binding=s->binding[id];
    if (!binding) return unlock(s,-ENOENT);
    struct backing *b=&s->buffers[binding-1];
    if (!allocation || b->identity!=allocation) return unlock(s,-ESTALE);
    if (b->references) return unlock(s,-EBUSY);
    free(b->data);s->bytes-=b->bytes;memset(b,0,sizeof *b);
    for (unsigned int i=0;i<CP_SYNC_RESOURCE_COUNT;i++)
        if (s->binding[i]==binding) s->binding[i]=0;
    return unlock(s,0);
}
static int copy(struct cp_sync_resources *s,uint64_t token,size_t offset,void *data,size_t size,int write) {
    int rc=lock(s);if (rc) return rc;
    struct reference *r=reference(s,token);
    if (!r) return unlock(s,-ESTALE);
    struct backing *b=&s->buffers[s->binding[r->id]-1];
    if (!size || !data || offset>b->bytes || size>b->bytes-offset) return unlock(s,-EINVAL);
    /* Publication freezes this allocation until free, even after refs drop. */
    if (write) {
        if (b->frozen || b->references!=1) return unlock(s,-EBUSY);
        for (unsigned int i=0;i<CP_SYNC_RESOURCE_COUNT;i++)
            if (i!=r->id && s->binding[i]==s->binding[r->id]) return unlock(s,-EBUSY);
        memcpy(b->data+offset,data,size);
    } else memcpy(data,b->data+offset,size);
    return unlock(s,0);
}
int cp_sync_write(struct cp_sync_resources *s,uint64_t token,size_t offset,const void *data,size_t size) {
    return copy(s,token,offset,(void *)data,size,1);
}
int cp_sync_read(struct cp_sync_resources *s,uint64_t token,size_t offset,void *data,size_t size) {
    return copy(s,token,offset,data,size,0);
}
int cp_sync_snapshot(struct cp_sync_resources *s,struct cp_sync_snapshot *out) {
    int rc=lock(s);if (rc) return rc;
    if (!out) return unlock(s,-EINVAL);
    *out=(struct cp_sync_snapshot){.bytes=s->bytes,.idle=1};
    for (unsigned int i=0;i<CP_SYNC_RESOURCE_COUNT;i++) {
        if (s->buffers[i].data) out->backing_groups++;
        if (s->binding[i]) { out->bound_resources++;if (i!=12) out->idle=0; }
    }
    for (unsigned int i=0;i<CP_SYNC_LEASE_COUNT;i++) if (s->leases[i].token) out->references++;
    return unlock(s,0);
}
