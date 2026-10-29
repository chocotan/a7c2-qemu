/* SPDX-License-Identifier: MIT */
#include "cp-slot2-work.h"
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

/* shortcut: 8c736a business effects and G+40 -> G+10 refresh are unimplemented;
 * replace the external executor only after those byte consumers are closed. */
struct cp_slot2_work {
    pid_t owner;
    pthread_mutex_t mutex;
    struct cp_slot2_view view;
    struct cp_slot2_io io;
    void *context;
    struct cp_slot2_borrowed borrowed;
};
static const unsigned char done_record[20]={0x75,0x70,0x63,0,0,0,0,0,0x91,0xe1,0x4d,0,0,0,0,0,0,0,0,0};
static const unsigned char queue_record[20]={0x7b,0xca,0x74,0,0,0,0,0,0x87,0x6d,0x8c,0,0,0,0,0,0,0,0,0};
static int lock(struct cp_slot2_work *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD;
    int rc=pthread_mutex_lock(&s->mutex);return rc?-rc:0;
}
static int unlock(struct cp_slot2_work *s,int rc) {
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
static int mask(const unsigned char *p,size_t n,unsigned int required) {
    for (size_t i=0;i<n;i++) if (p[i]>1 || (required && p[i]!=1)) return 0;
    return 1;
}
static int fault(struct cp_slot2_work *s,int rc) {
    s->view.fault=rc<0?rc:-EIO;s->view.stage=CP_SLOT2_FAULT;
    return unlock(s,s->view.fault);
}
/* Caller holds an in-flight state, but NOT the mutex. No CP32 host casts. */
static int borrowed_check(struct cp_slot2_work *s) {
    int rc=s->io.valid(s->context,&s->borrowed);if (rc) return rc;
    uint32_t root=get32(s->view.owned_work+4);
    if (!root || root>UINT32_MAX-7) return -EFAULT;
    unsigned char bytes[2]={0xa5,0xa5},known[2]={0,0};
    rc=s->io.read(s->context,&s->borrowed,root+6,bytes,known,2);
    if (rc) return rc;
    if (!mask(known,2,1)) return -EAGAIN;
    return (bytes[0] | (uint32_t)bytes[1]<<8)==s->view.requested?0:-ESTALE;
}
static int complete(struct cp_slot2_work *s) {
    unsigned char record[20];memcpy(record,s->view.owned_work+0xcc,20);
    int rc=s->io.valid(s->context,&s->borrowed);
    if (!rc) rc=s->io.complete(s->context,&s->borrowed,record,2);
    int guard=lock(s);if (guard) return guard;
    s->view.completion_attempts++;
    if (rc) return fault(s,rc);
    /* Host analogue of 637074 -> 4de190(2), not normal observed publication. */
    atomic_thread_fence(memory_order_seq_cst);
    s->view.callbacks++;s->view.busy=0;s->view.stage=CP_SLOT2_IDLE;
    if (s->view.bank_generation[s->view.selector]==s->view.generation)
        s->view.completed_generation=s->view.generation;
    return unlock(s,0);
}
struct cp_slot2_work *cp_slot2_create(unsigned int selector,const unsigned char *banks,
    const unsigned char *known,size_t size) {
    if (selector>1 || !banks || !known || size!=2*CP_SLOT2_BANK_BYTES || !mask(known,size,0)) {
        errno=EINVAL;return NULL;
    }
    struct cp_slot2_work *s=calloc(1,sizeof *s);if (!s) return NULL;
    s->owner=getpid();int rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    s->view.selector=selector;
    memcpy(s->view.banks,banks,size);memcpy(s->view.bank_known,known,size);
    return s;
}
int cp_slot2_destroy(struct cp_slot2_work *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy) return unlock(s,-EBUSY);
    unlock(s,0);pthread_mutex_destroy(&s->mutex);free(s);return 0;
}
int cp_slot2_bind(struct cp_slot2_work *s,const struct cp_slot2_io *io,void *context) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy) return unlock(s,-EBUSY);
    if (!io || !io->valid || !io->read || !io->enqueue || !io->complete)
        return unlock(s,-EINVAL);
    s->io=*io;s->context=context;return unlock(s,0);
}
int cp_slot2_begin(struct cp_slot2_work *s,const struct cp_slot2_input *input) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy) return unlock(s,-EBUSY);
    if (!input || !input->view || !input->known || !input->completion_record ||
        input->view_size!=200 || input->known_size!=200 || input->record_size!=20)
        return unlock(s,-EINVAL);
    if (input->module!=2 || input->requested_known!=1 || input->mode_known!=1 ||
        (input->requested!=0x323 && input->requested!=0x32c && input->requested!=0x302) ||
        !input->borrowed.generation || memcmp(input->completion_record,done_record,20))
        return unlock(s,-ENOTSUP);
    if (!mask(input->known,200,1)) return unlock(s,-EAGAIN);
    if (!s->io.valid) return unlock(s,-ENOSYS);
    if (s->view.generation==UINT64_MAX || s->view.callbacks==UINT_MAX ||
        s->view.publications==UINT_MAX || s->view.completion_attempts==UINT_MAX)
        return unlock(s,-EOVERFLOW);
    s->borrowed=input->borrowed;s->view.borrowed_generation=s->borrowed.generation;
    s->view.mode=s->borrowed.mode;s->view.requested=input->requested;
    s->view.owned_work[0]=2;
    memset(s->view.owned_work+1,0,3);
    memcpy(s->view.owned_work+4,input->view,200);
    memcpy(s->view.view_known,input->known,200);
    memcpy(s->view.owned_work+0xcc,input->completion_record,20);
    memcpy(s->view.queue_record,queue_record,20);
    s->view.source_fnv=fnv(s->view.owned_work+4,200);
    s->view.generation++;s->view.busy=1;s->view.stage=CP_SLOT2_VALIDATING;
    unlock(s,0);
    rc=borrowed_check(s);
    if (!rc) rc=s->io.enqueue(s->context,CP_SLOT2_QUEUE_TOKEN,s->view.queue_record,s->view.owned_work);
    else { int guard=lock(s);if (guard) return guard;return fault(s,rc); }
    int guard=lock(s);if (guard) return guard;
    if (rc<0) return fault(s,rc);
    s->view.stage=rc?CP_SLOT2_QUEUED:CP_SLOT2_COMPLETING;
    unlock(s,0);
    return rc?0:complete(s);
}
int cp_slot2_tick(struct cp_slot2_work *s) {
    int rc=lock(s);if (rc) return rc;
    if (!s->view.busy) return unlock(s,-ENOENT);
    if (s->view.stage==CP_SLOT2_FAULT) return unlock(s,s->view.fault);
    if (s->view.stage!=CP_SLOT2_QUEUED) return unlock(s,-EBUSY);
    if (!s->io.execute_8c736a) return unlock(s,-ENOSYS);
    unsigned int alternate=s->view.selector^1;
    struct cp_slot2_bank bank;
    bank.token=CP_SLOT2_BANK_BASE+alternate*CP_SLOT2_BANK_BYTES;
    memcpy(bank.bytes,s->view.banks+alternate*CP_SLOT2_BANK_BYTES,CP_SLOT2_BANK_BYTES);
    memcpy(bank.known,s->view.bank_known+alternate*CP_SLOT2_BANK_BYTES,CP_SLOT2_BANK_BYTES);
    bank.known_size=CP_SLOT2_BANK_BYTES;bank.fully_consumed=0;
    struct cp_slot2_pointer_view view={s->view.owned_work+4,s->view.view_known,200,200,s->view.source_fnv};
    s->view.stage=CP_SLOT2_EXECUTING;unlock(s,0);
    rc=borrowed_check(s);
    int executed=!rc;
    if (executed) rc=s->io.execute_8c736a(s->context,&view,&s->borrowed,&bank);
    if (!rc) rc=borrowed_check(s);
    int guard=lock(s);if (guard) return guard;
    if (executed) {
        /* Keep partial/unpublished writes as evidence even when execution faults. */
        memcpy(s->view.banks+alternate*CP_SLOT2_BANK_BYTES,bank.bytes,CP_SLOT2_BANK_BYTES);
        for (size_t i=0;i<CP_SLOT2_BANK_BYTES;i++)
            s->view.bank_known[alternate*CP_SLOT2_BANK_BYTES+i]=(i<bank.known_size && bank.known[i]==1);
    }
    if (rc) return fault(s,rc);
    if (bank.token!=CP_SLOT2_BANK_BASE+alternate*CP_SLOT2_BANK_BYTES || bank.fully_consumed!=1 ||
        bank.known_size!=CP_SLOT2_BANK_BYTES || !mask(bank.known,CP_SLOT2_BANK_BYTES,0))
        return fault(s,-EAGAIN);
    s->view.bank_generation[alternate]=s->view.generation;
    s->view.selector=alternate;s->view.publications++;
    s->view.stage=CP_SLOT2_COMPLETING;unlock(s,0);
    return complete(s);
}
int cp_slot2_snapshot(struct cp_slot2_work *s,struct cp_slot2_view *out) {
    int rc=lock(s);if (rc) return rc;
    if (!out) return unlock(s,-EINVAL);
    *out=s->view;return unlock(s,0);
}
