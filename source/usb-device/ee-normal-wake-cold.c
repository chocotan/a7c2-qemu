/* SPDX-License-Identifier: MIT */
#include "ee-normal-wake-cold.h"
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct ee_nwc {
    pid_t pid;
    uint64_t generation;
    pthread_mutex_t lock;
    struct full_imaging_io io;
    struct ee_nwc_snapshot s;
    uint8_t object[0x111e], *rows, *state, backup[64];
    size_t rows_bytes, state_bytes;
    uint32_t policy;
    uint8_t force, be9;
};
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
int ee_nwc_init_valid(const struct ee_nwc_init *i, pid_t pid, uint64_t gen) {
    return i && i->pid==pid && i->generation==gen && i->fd>=0 &&
        i->mapping && i->mapping!=UINTPTR_MAX && i->allocator &&
        i->bytes==0x200000 && i->pool0==0x80000 && i->pool1==0x20000 && i->dynamic_id &&
        i->mapping<=UINTPTR_MAX-i->bytes && i->abi_verified==1 && i->fd_verified==1 && i->map_verified==1;
}
int ee_nwc_span(const struct ee_nwc_init *i, uintptr_t p, size_t n) {
    return i && p>=i->mapping && n<=i->bytes && p-i->mapping<=i->bytes-n;
}
static int kernel_gate(const struct ee_nwc_gate *g) {
    const struct ee_nwc_prime *p=&g->prime;
    return !g->registration_event && !g->consumer_registered && g->registration_rc==EE_NWC_UNKNOWN &&
        ee_nwc_init_valid(&g->init,g->pid,g->generation) && g->waiter_tid && g->waiter_tid!=g->consumer &&
        p->pid==g->pid && p->generation==g->generation && p->message_generation &&
        p->message && p->receiver_tid==g->consumer && p->free_actor_tid &&
        !p->receive_rc && !p->free_rc && p->source_known==1 && p->size_known==1 && p->source && p->size>0 &&
        p->free_returned==1 && p->receive_event && p->free_event>p->receive_event &&
        g->unlock_event>p->free_event && ee_nwc_span(&g->init,p->message,(size_t)p->size);
}
static int owner(struct ee_nwc *s) {
    return s && getpid()==s->pid;
}
static int reject(struct ee_nwc *s, int rc) { s->s.last_rejected=(unsigned)rc;return rc; }
static int fault(struct ee_nwc *s, int rc) {
    if (!s->s.fault) s->s.fault=(unsigned)rc;
    s->s.retired=0;s->s.pending=s->s.allocated;
    return reject(s,rc);
}
static void retire(struct ee_nwc *s) {
    s->s.retired=!s->s.fault && s->s.send_returned && !s->s.send_rc &&
        s->s.received && s->s.reader_returned && s->s.free_returned && !s->s.free_rc &&
        (s->s.gate.admission_source!=EE_NWC_KERNELDEFAULT || s->s.wait_returned);
    s->s.pending=s->s.allocated && !s->s.retired;
}
static int identity(struct ee_nwc *s, pid_t pid, uint64_t generation) {
    if (pid!=s->pid) return s->s.gate.admission_source==EE_NWC_KERNELDEFAULT ? fault(s,EE_NWC_OWNER) : reject(s,EE_NWC_OWNER);
    if (generation!=s->generation) return s->s.gate.admission_source==EE_NWC_KERNELDEFAULT ? fault(s,EE_NWC_GENERATION) : reject(s,EE_NWC_GENERATION);
    return EE_NWC_OK;
}
static int lease(struct ee_nwc *s, const struct ee_nwc_lease *l) {
    int rc=identity(s,l->pid,l->generation);
    if (rc) return rc;
    if (!s->s.send_called || !s->s.allocated || l->message!=s->s.lease.message)
        return s->s.gate.admission_source==EE_NWC_KERNELDEFAULT ? fault(s,EE_NWC_LEASE) : reject(s,EE_NWC_LEASE);
    if (l->destination!=EE_NWC_DEST || l->source!=EE_NWC_SOURCE || l->bytes!=12 ||
        l->message_generation!=s->s.lease.message_generation ||
        memcmp(l->wire,s->s.lease.wire,12)) return fault(s,EE_NWC_LEASE);
    return EE_NWC_OK;
}
int ee_nwc_create(struct ee_nwc **out, const char *profile, pid_t pid,
                  uint64_t generation, const struct full_imaging_io *io) {
    struct ee_nwc *s;
    if (!out) return EE_NWC_INVALID;
    *out=NULL;
    if (!profile || strcmp(profile,EE_NWC_PROFILE)) return EE_NWC_DISABLED;
    if (pid!=getpid()) return EE_NWC_OWNER;
    if (!generation) return EE_NWC_GENERATION;
    if (!io || !io->allocate || !io->release || !io->set_source || !io->send ||
        !io->size || !io->source) return EE_NWC_INVALID;
    s=calloc(1,sizeof(*s));
    if (!s) return EE_NWC_ALLOCATE;
    if (pthread_mutex_init(&s->lock,NULL)) { free(s);return EE_NWC_ALLOCATE; }
    s->pid=pid;s->generation=generation;s->io=*io;
    s->s.pid=pid;s->s.generation=generation;
    /* This executes the scoped model constructor; poison outside its proven range. */
    memset(s->object,0xa5,sizeof(s->object));
    memset(s->object+0x10a0,0,0x111e - 0x10a0);
    s->s.constructed=1;s->s.object_110c=le32(s->object+0x110c);
    s->s.object_10bf=s->object[0x10bf];
    *out=s;return EE_NWC_OK;
}
int ee_nwc_configure(struct ee_nwc *s, const struct ee_nwc_assets *a,
                     const struct ee_nwc_initial *in) {
    int rc=EE_NWC_OK;
    if (!owner(s)) return EE_NWC_OWNER;
    if (!a || !in) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);
    if ((rc=identity(s,a->pid,a->generation)) || (rc=identity(s,in->pid,in->generation))) goto done;
    if (s->s.configured || s->s.attempted) { rc=reject(s,EE_NWC_DUPLICATE);goto done; }
    if (in->known!=EE_NWC_INITIAL_ALL || in->model_defined!=EE_NWC_INITIAL_ALL || !a->verified) {
        rc=reject(s,EE_NWC_UNKNOWN);goto done;
    }
    if (!a->backup_sha256 || strcmp(a->backup_sha256,EE_NWC_BACKUP_SHA) ||
        !a->cp_bank_sha256 || strcmp(a->cp_bank_sha256,EE_NWC_BANK_SHA) ||
        !a->cp_sha256 || strcmp(a->cp_sha256,EE_NWC_CP_SHA) || a->cp_bank_offset!=970752 ||
        a->keymap_group!=1 || !a->rows || !a->rows_bytes || a->rows_bytes%64 ||
        a->rows_bytes/64>0x650 || !in->stable_state || in->stable_bytes!=a->rows_bytes/4 ||
        !in->provenance || !in->provenance[0] || strlen(in->provenance)>=sizeof(s->s.provenance)) {
        rc=reject(s,EE_NWC_INVALID);goto done;
    }
    s->rows=malloc(a->rows_bytes);s->state=malloc(in->stable_bytes);
    if (!s->rows || !s->state) {
        free(s->rows);free(s->state);s->rows=NULL;s->state=NULL;
        rc=fault(s,EE_NWC_ALLOCATE);goto done;
    }
    s->rows_bytes=a->rows_bytes;s->state_bytes=in->stable_bytes;
    memcpy(s->rows,a->rows,s->rows_bytes);memcpy(s->state,in->stable_state,s->state_bytes);
    memcpy(s->backup,a->backup_00030162,64);s->policy=le32(a->policy_00030a01);
    s->force=in->force_e0;s->be9=in->be9bae_byte9;
    s->s.initial_known=in->known;s->s.model_defined=in->model_defined;
    memcpy(s->s.provenance,in->provenance,strlen(in->provenance)+1);
    s->object[0x10bf]=(uint8_t)((le32(a->config_0092001c)>>2)&1u);
    s->s.object_10bf=s->object[0x10bf];s->s.configured=1;
done:
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_arm(struct ee_nwc *s, const struct ee_nwc_gate *g) {
    int rc=EE_NWC_OK;
    if (!owner(s)) return EE_NWC_OWNER;
    if (!g) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);
    if ((rc=identity(s,g->pid,g->generation))) goto done;
    if (s->s.armed || s->s.attempted) { rc=reject(s,EE_NWC_DUPLICATE);goto done; }
    unsigned admitted=g->admission_source==EE_NWC_CALLBACK ?
        (g->consumer_registered==1 && !g->registration_rc && g->registration_event && g->unlock_event>g->registration_event) :
        (g->admission_source==EE_NWC_KERNELDEFAULT && kernel_gate(g));
    if (!s->s.configured || g->observer_installed!=1 || !admitted ||
        g->wait_unlocked!=1 || g->notification_id!=0x20a3 ||
        !g->consumer || !g->promise || !g->reader) { rc=reject(s,EE_NWC_NOT_ARMED);goto done; }
    s->s.gate=*g;s->s.armed=1;
done:
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_trigger(struct ee_nwc *s, uint64_t generation,
                   const struct ee_adc_sample samples[2], uint64_t now, uint64_t max_age) {
    struct ee_normal_inputs in;
    void *message=NULL;
    int rc, native_rc;
    unsigned size, source;
    if (!owner(s)) return EE_NWC_OWNER;
    pthread_mutex_lock(&s->lock);
    if ((rc=identity(s,s->pid,generation))) goto done;
    if (s->s.fault && s->s.gate.admission_source==EE_NWC_KERNELDEFAULT) { rc=reject(s,(int)s->s.fault);goto done; }
    if (s->s.attempted) { rc=reject(s,EE_NWC_DUPLICATE);goto done; }
    if (!s->s.configured || !s->s.armed) { rc=reject(s,EE_NWC_NOT_ARMED);goto done; }
    s->s.attempted=1;s->s.first_cold=1;
    if (!samples || samples[0].generation!=generation || samples[1].generation!=generation) {
        rc=fault(s,samples ? EE_NWC_GENERATION : EE_NWC_UNKNOWN);goto done;
    }
    s->s.adc_status=(unsigned)ee_adc_consume(s->rows,s->rows_bytes,s->state,s->state_bytes,
                                          1,samples,now,max_age);
    if (s->s.adc_status!=EE_INPUT_OK) { rc=fault(s,EE_NWC_INPUT);goto done; }
    if (ee_adc_read_key(s->rows,s->rows_bytes,s->state,s->state_bytes,0x71c9,&s->s.current[0])!=EE_INPUT_OK ||
        ee_adc_read_key(s->rows,s->rows_bytes,s->state,s->state_bytes,0x71ca,&s->s.current[1])!=EE_INPUT_OK) {
        rc=fault(s,EE_NWC_INPUT);goto done;
    }
    memset(&in,0,sizeof(in));in.known=63;
    in.current[0]=s->s.current[0];in.current[1]=s->s.current[1];
    in.backup_00030162=s->backup;in.backup_bytes=64;in.policy_00030a01=s->policy;
    in.force_e0=s->force;in.be9bae_byte9=s->be9;
    in.object_110c=le32(s->object+0x110c);in.object_10bf=s->object[0x10bf];
    s->s.selection=ee_normal_select(&in);
    if (s->s.selection.decision!=EE_NORMAL_SPINAL_OFF || !s->s.selection.raw_candidate_valid ||
        s->s.selection.raw_candidate!=0) { rc=reject(s,EE_NWC_NO_DELIVERY);goto done; }
    s->s.busy=1;
    pthread_mutex_unlock(&s->lock);
    /* All native IO is outside the private lock, including synchronous callbacks. */
    native_rc=s->io.allocate(EE_NWC_DEST,&message,12,1);
    pthread_mutex_lock(&s->lock);
    s->s.allocate_rc=native_rc;s->s.allocated=(message!=NULL);s->s.pending=s->s.allocated;
    s->s.lease.pid=s->pid;s->s.lease.generation=s->generation;
    s->s.lease.message=(uintptr_t)message;s->s.lease.destination=EE_NWC_DEST;
    s->s.lease.bytes=12;s->s.lease.source=EE_NWC_SOURCE;
    s->s.lease.message_generation=s->s.gate.unlock_event;
    s->s.lease.wire[0]=6;s->s.lease.wire[2]=0xa3;s->s.lease.wire[3]=0x20;
    if (native_rc || !message || s->s.fault) { s->s.busy=0;rc=fault(s,EE_NWC_ALLOCATE);goto done; }
    if (s->s.gate.admission_source==EE_NWC_KERNELDEFAULT &&
        ((uintptr_t)message<24 || !ee_nwc_span(&s->s.gate.init,(uintptr_t)message-24,36))) {
        s->s.busy=0;rc=fault(s,EE_NWC_LEASE);goto done;
    }
    pthread_mutex_unlock(&s->lock);
    size=s->io.size(message);
    pthread_mutex_lock(&s->lock);unsigned io_valid=!s->s.fault;pthread_mutex_unlock(&s->lock);
    if (size==12 && io_valid) {
        memcpy(message,s->s.lease.wire,12);
        s->io.set_source(message,EE_NWC_SOURCE);
        source=s->io.source(message);
    } else source=0;
    pthread_mutex_lock(&s->lock);
    if (s->s.fault || size!=12 || source!=EE_NWC_SOURCE) { s->s.busy=0;rc=fault(s,EE_NWC_LEASE);goto done; }
    s->s.send_called=1;
    pthread_mutex_unlock(&s->lock);
    native_rc=s->io.send(EE_NWC_DEST,message);
    /* Receiver may already have freed message; never dereference it after send. */
    pthread_mutex_lock(&s->lock);
    s->s.send_rc=native_rc;s->s.send_returned=1;s->s.busy=0;
    if (native_rc) rc=fault(s,EE_NWC_TRANSPORT);
    else { retire(s);rc=s->s.fault ? (int)s->s.fault : EE_NWC_OK; }
done:
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_observe_receive(struct ee_nwc *s, const struct ee_nwc_receive *o) {
    int rc;
    if (!owner(s)) return EE_NWC_OWNER;
    if (!o) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);
    rc=lease(s,&o->lease);
    if (!rc && o->consumer!=s->s.gate.consumer) rc=fault(s,EE_NWC_LEASE);
    if (!rc && s->s.received) rc=fault(s,EE_NWC_DUPLICATE);
    if (!rc) { s->s.receive_observed=*o;s->s.received=1;retire(s); }
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_observe_reader(struct ee_nwc *s, const struct ee_nwc_reader *o) {
    int rc;
    if (!owner(s)) return EE_NWC_OWNER;
    if (!o) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);
    rc=identity(s,o->pid,o->generation);
    if (!rc && (!s->s.send_called || o->reader!=s->s.gate.reader ||
        o->promise!=s->s.gate.promise || o->notification_id!=0x20a3)) rc=reject(s,EE_NWC_READER);
    if (!rc && s->s.reader_returned) rc=fault(s,EE_NWC_DUPLICATE);
    if (!rc) {
        s->s.reader_observed=*o;s->s.reader_returned=o->returned;s->s.reader_output=o->output;
        if (o->returned!=1 || o->output!=1) rc=fault(s,EE_NWC_READER);
        else retire(s);
    }
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_observe_free(struct ee_nwc *s, const struct ee_nwc_free *o) {
    int rc;
    if (!owner(s)) return EE_NWC_OWNER;
    if (!o) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);
    rc=lease(s,&o->lease);
    if (!rc && s->s.free_returned) rc=fault(s,EE_NWC_DUPLICATE);
    if (!rc && s->s.gate.admission_source==EE_NWC_KERNELDEFAULT && !o->free_actor_tid) rc=fault(s,EE_NWC_FREE);
    if (!rc) {
        s->s.free_observed=*o;s->s.free_returned=1;s->s.free_owner=o->owner;s->s.free_rc=o->rc;
        s->s.free_actor_tid=o->free_actor_tid;
        if (o->owner!=EE_NWC_DEST || o->rc) rc=fault(s,EE_NWC_FREE);
        else retire(s);
    }
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_observe_wait(struct ee_nwc *s,pid_t pid,uint64_t gen,uintptr_t promise,uintptr_t tid) {
    if (!owner(s)) return EE_NWC_OWNER;
    pthread_mutex_lock(&s->lock);int rc=identity(s,pid,gen);
    if (!rc && (s->s.gate.admission_source!=EE_NWC_KERNELDEFAULT || !s->s.send_called ||
        s->s.gate.promise!=promise || s->s.gate.waiter_tid!=tid || s->s.wait_returned)) rc=fault(s,EE_NWC_READER);
    if (!rc) { s->s.wait_returned=1;retire(s); }
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_fail(struct ee_nwc *s, int reason) {
    if (!owner(s)) return EE_NWC_OWNER;
    pthread_mutex_lock(&s->lock);int rc=fault(s,reason);pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_copy_owned(struct ee_nwc *s, const struct ee_nwc_lease *l, unsigned size, uint8_t out[12]) {
    if (!owner(s)) return EE_NWC_OWNER;
    if (!l || !out) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);
    int rc=lease(s,l);
    if (!rc && (s->s.fault || s->s.gate.admission_source!=EE_NWC_KERNELDEFAULT ||
        size!=12 || s->s.free_begun || s->s.free_returned ||
        !ee_nwc_init_valid(&s->s.gate.init,s->pid,s->generation) ||
        !ee_nwc_span(&s->s.gate.init,l->message,12))) rc=fault(s,EE_NWC_LEASE);
    if (!rc) { memcpy(out,(const void *)l->message,12);s->s.owned_copy=1; }
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_free_begin(struct ee_nwc *s, const struct ee_nwc_lease *l) {
    if (!owner(s)) return EE_NWC_OWNER;
    if (!l) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);int rc=lease(s,l);
    if (!rc && (s->s.free_begun || s->s.free_returned)) rc=fault(s,EE_NWC_DUPLICATE);
    if (!rc) s->s.free_begun=1;
    pthread_mutex_unlock(&s->lock);return rc;
}
int ee_nwc_snapshot(struct ee_nwc *s, struct ee_nwc_snapshot *out) {
    if (!owner(s)) return EE_NWC_OWNER;
    if (!out) return EE_NWC_INVALID;
    pthread_mutex_lock(&s->lock);*out=s->s;pthread_mutex_unlock(&s->lock);
    return EE_NWC_OK;
}
int ee_nwc_destroy(struct ee_nwc *s, struct ee_nwc_snapshot *handoff) {
    int rc=EE_NWC_OK;
    if (!owner(s)) return EE_NWC_OWNER;
    pthread_mutex_lock(&s->lock);
    if (s->s.busy || (s->s.pending && !handoff)) rc=reject(s,EE_NWC_BUSY);
    if (!rc && handoff) *handoff=s->s;
    pthread_mutex_unlock(&s->lock);
    if (rc) return rc;
    pthread_mutex_destroy(&s->lock);free(s->rows);free(s->state);free(s);
    return EE_NWC_OK;
}
