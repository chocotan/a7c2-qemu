/* SPDX-License-Identifier: MIT */
#include "cp-slot1-publication.h"
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

/* Finite publication primitive, NOT a 3006 service or a hardware-ready model.
 * Original evidence: report/cp3006-start; no original functions are executed.
 * Serial numbers below are host audit identities, not original CP generations. */
struct cp_slot1_publication {
    pid_t owner;
    pthread_mutex_t mutex;
    struct cp_slot1_view view;
    unsigned char banks[2 * CP_SLOT1_BANK_BYTES];
    unsigned char snapshot[CP_SLOT1_SNAPSHOT_BYTES];
};
static int lock(struct cp_slot1_publication *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD;
    int rc=pthread_mutex_lock(&s->mutex);return rc?-rc:0;
}
static int unlock(struct cp_slot1_publication *s,int rc) {
    pthread_mutex_unlock(&s->mutex);return rc;
}
static unsigned int get16(const unsigned char *p) {
    return p[0] | (unsigned int)p[1]<<8;
}
static void cleanup(struct cp_slot1_publication *s) {
    /* 637074 -> 4de190(module1): DMB SY then occupancy clear. */
    atomic_thread_fence(memory_order_seq_cst);
    s->view.busy=0;s->view.stage=CP_SLOT1_IDLE;s->view.callbacks++;
}
struct cp_slot1_publication *cp_slot1_create(unsigned int input_mode,
    const unsigned char banks[2 * CP_SLOT1_BANK_BYTES]) {
    if (!banks || input_mode!=3) { errno=EINVAL;return NULL; }
    struct cp_slot1_publication *s=calloc(1,sizeof *s);
    if (!s) return NULL;
    s->owner=getpid();
    int rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    memcpy(s->banks,banks,sizeof s->banks);
    s->view.input_mode=input_mode;
    return s;
}
int cp_slot1_destroy(struct cp_slot1_publication *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy) return unlock(s,-EBUSY);
    unlock(s,0);pthread_mutex_destroy(&s->mutex);free(s);return 0;
}
int cp_slot1_set_input_mode(struct cp_slot1_publication *s,unsigned int input_mode) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy) return unlock(s,-EBUSY);
    s->view.input_mode=input_mode;
    /* a96d5c -> 9a749e, with the pinned a548e2 leaf returning 1. */
    s->view.derived_mode=(input_mode==0 || input_mode==1)?1:0;
    return unlock(s,0);
}
int cp_slot1_enqueue(struct cp_slot1_publication *s,const void *root,size_t root_len,
    const void *record,size_t record_len) {
    int rc=lock(s);if (rc) return rc;
    if (!root || !record || root_len!=CP_SLOT1_ROOT_BYTES || record_len!=CP_SLOT1_RECORD_BYTES)
        return unlock(s,-EINVAL);
    if (s->view.busy) return unlock(s,-EBUSY);
    s->view.derived_mode=(s->view.input_mode==0 || s->view.input_mode==1)?1:0;
    if (s->view.input_mode!=3 || s->view.derived_mode) return unlock(s,-ENOTSUP);
    if (get16((const unsigned char *)root+8)!=0x201) return unlock(s,-ENOTSUP);
    if (s->view.work==UINT64_MAX || s->view.callbacks==0xffffffffu) return unlock(s,-EOVERFLOW);
    memcpy(s->snapshot,root,root_len);
    memcpy(s->snapshot+root_len,record,record_len);
    s->view.work++;s->view.requested=get16(s->snapshot+8);
    s->view.busy=1;s->view.stage=CP_SLOT1_QUEUED;
    return unlock(s,0);
}
int cp_slot1_execute(struct cp_slot1_publication *s,const struct cp_slot1_effects *effects,void *arg) {
    int rc=lock(s);if (rc) return rc;
    if (!effects || !effects->prefix || !effects->postwork) return unlock(s,-ENOTSUP);
    if (s->view.stage!=CP_SLOT1_QUEUED) return unlock(s,-ENOENT);
    /* Copy the callable record before unlocking: the caller may mutate its
     * descriptor while the prefix runs; do not later read a different hook. */
    struct cp_slot1_effects owned=*effects;
    s->view.stage=CP_SLOT1_EXECUTING;
    unlock(s,0);
    rc=owned.prefix(arg,s->snapshot,sizeof s->snapshot);
    int guard=lock(s);if (guard) return guard;
    if (rc) {
        s->view.stage=CP_SLOT1_BLOCKED_PREFIX;
        return unlock(s,rc<0?rc:-EIO);
    }
    unsigned int bank=s->view.selector^1;
    unsigned char *field=s->banks+bank*CP_SLOT1_BANK_BYTES+0x14;
    field[0]=s->snapshot[8];field[1]=s->snapshot[9];
    s->view.bank_work[bank]=s->view.work;
    s->view.selector=bank; /* publish AFTER the two actual byte writes */
    unlock(s,0);
    rc=owned.postwork(arg,s->snapshot,sizeof s->snapshot);
    guard=lock(s);if (guard) return guard;
    if (rc) {
        s->view.stage=CP_SLOT1_BLOCKED_POST;
        return unlock(s,rc<0?rc:-EIO);
    }
    s->view.completed_work=s->view.work;
    cleanup(s);return unlock(s,0);
}
int cp_slot1_abort(struct cp_slot1_publication *s) {
    int rc=lock(s);if (rc) return rc;
    if (!s->view.busy) return unlock(s,-ENOENT);
    if (s->view.stage==CP_SLOT1_EXECUTING) return unlock(s,-EBUSY);
    cleanup(s);return unlock(s,0);
}
int cp_slot1_refresh(struct cp_slot1_publication *s,unsigned int root_enabled,unsigned int query) {
    int rc=lock(s);if (rc) return rc;
    if (root_enabled && (query==1 || !s->view.busy)) s->view.alias=s->view.selector;
    return unlock(s,0);
}
int cp_slot1_snapshot(struct cp_slot1_publication *s,struct cp_slot1_view *out) {
    int rc=lock(s);if (rc) return rc;
    if (!out) return unlock(s,-EINVAL);
    *out=s->view;
    out->observed=get16(s->banks+s->view.alias*CP_SLOT1_BANK_BYTES+0x14);
    out->observation_current=s->view.work && s->view.completed_work==s->view.work &&
        s->view.bank_work[s->view.alias]==s->view.work;
    return unlock(s,0);
}
int cp_slot1_read_banks(struct cp_slot1_publication *s,unsigned char *out,size_t size) {
    int rc=lock(s);if (rc) return rc;
    if (!out || size!=sizeof s->banks) return unlock(s,-EINVAL);
    memcpy(out,s->banks,sizeof s->banks);return unlock(s,0);
}
