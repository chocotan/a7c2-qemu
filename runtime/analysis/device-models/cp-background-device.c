/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cp-background-device.h"
#include <stdlib.h>
#include <string.h>
/* Virtual CP profile gate: deliveries only under the admitted guest profile;
 * standalone component tests run without it and keep the zero-send invariant. */
static int virtual_cp_profile(void) {
    const char *spec=getenv("MENU_CP_BACKGROUND");
    return spec && !strcmp(spec,"virtual-mode3-cold-v1");
}
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t state_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t lease_mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Atomic unsigned int faults;
static _Atomic(native_cp_background_free_observer) free_observer;
static unsigned int sending;
static uint64_t next_ticket=1;
static struct cp_sync_resources *resources;
static struct cp_cold_control *control;
static void *retained_request;
static struct native_cp_background_parameter_snapshot parameter;
static struct native_cp_background_config_snapshot config;
static struct native_cp_background_face_snapshot face;
static struct native_cp_background_4023_snapshot parameter4023;
/* CP 0xae17d8 (0x40de) six-slot state: +0x08 transition flag, +0x0c current slot.
 * CP baseline unknown; virtual cold baseline is declared per profile, original_CP=0. */
static struct { unsigned char transition, current; } release_key={1,0};
static const struct { unsigned int destination, opcode, bytes; const char *missing; } remainder_commands[]={
    {NATIVE_CP_BACKGROUND_SID,0x4023,12,"config-gates+central8306"},
    {NATIVE_CP_BACKGROUND_SID,0x4077,12,"worker+remote92a20845+central-state"},
    {NATIVE_CP_CAPTURE_SID,0x4039,16,"capture-end-receiver"},
    {NATIVE_CP_CAPTURE_SID,0x40a5,12,"release-key-scan-notify-unmodeled"},
    {NATIVE_CP_BACKGROUND_SID,0x404e,8,"config-root+FC-cancel"},
    {NATIVE_CP_BACKGROUND_SID,0x4070,12,"worker+bracketing+AP1010"},
    {NATIVE_CP_CAPTURE_SID,0x406a,12,"PID-key-clear-receiver+key-state"},
    {NATIVE_CP_CAPTURE_SID,0x4036,16,"still-lock-kind-state+RelMgr+async-start-comp"},
    {NATIVE_CP_CAPTURE_SID,0x40de,12,"slot-pathB-4036-unmodeled"},
    {NATIVE_CP_BACKGROUND_SID,0x301a,12,"central8102+preview-mode-transition"}
};
#define REMAINDER_COUNT (sizeof remainder_commands/sizeof remainder_commands[0])
static struct native_cp_background_remainder_snapshot remainder_pending[REMAINDER_COUNT];
static _Atomic uintptr_t remainder_request[REMAINDER_COUNT];
static int remainder_owns(void *request) {
    for (unsigned int i=0;i<REMAINDER_COUNT;i++)
        if (atomic_load(&remainder_request[i])==(uintptr_t)request) return 1;
    return 0;
}
struct reply_lease { uint64_t ticket; void *pointer; unsigned int destination, sending, freed, opcode; };
static struct reply_lease leases[8];

static void note(const struct full_imaging_io *io,const char *tag,const char *text) {
    if (io && io->record) io->record(tag,text);
}
static int unsupported(const struct full_imaging_io *io,int *result,const char *why) {
    note(io,"NATIVE_CP_BACKGROUND_UNSUPPORTED ",why);*result=-1021;return 1;
}
/* Claim before the very first mutex acquisition. A fork between claim and
 * lock inherits the parent's PID and refuses, even during initialization. */
static int claim_owner(void) {
    int expected=0,pid=getpid();
    atomic_compare_exchange_strong(&owner_pid,&expected,pid);
    return !expected || expected==pid;
}
static unsigned int u32(const unsigned char *p) {
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
static void put32(unsigned char *p,unsigned int v) {
    for (unsigned int i=0;i<4;i++) p[i]=(unsigned char)(v>>(8*i));
}
/* state_mutex held. No foreign/inherited mutex is acquired by the caller. */
static int initialize(void) {
    int pid=getpid(),owner=atomic_load(&owner_pid);
    if (owner && owner!=pid) return -1;
    if (!owner) return -1;
    if (control) return 0;
    if (!resources) resources=cp_sync_create(32u*1024u*1024u);
    if (resources) control=cp_cold_create(3,resources);
    if (!control) { atomic_fetch_add(&faults,1);return -1; }
    return 0;
}
struct cp_sync_resources *native_cp_background_resources(void) {
    if (!claim_owner()) return NULL;
    pthread_mutex_lock(&state_mutex);
    struct cp_sync_resources *r=initialize()?NULL:resources;
    pthread_mutex_unlock(&state_mutex);return r;
}
int native_cp_background_bind_free_observer(native_cp_background_free_observer observer) {
    int pid=getpid(),owner=atomic_load(&owner_pid);
    if(!observer || (owner && owner!=pid))return -1021;
    native_cp_background_free_observer prior=atomic_load(&free_observer);
    if(prior==observer)return 0;
    if(prior || owner)return -1021;
    return atomic_compare_exchange_strong(&free_observer,&prior,observer) || prior==observer?0:-1021;
}
static void done_sending(void) {
    pthread_mutex_lock(&state_mutex);sending=0;pthread_mutex_unlock(&state_mutex);
}
int native_cp_background_release(unsigned int id,void *message,
                                int (*release)(unsigned int,void *),
                                void (*record)(const char *,const char *),int *result) {
    if (!message || !release || !result || !atomic_load(&owner_pid)) return 0;
    if (atomic_load(&owner_pid)!=getpid()) {
        /* The child has its own snapshot, so inspect without an inherited lock. */
        for (unsigned int i=0;i<8;i++) if (leases[i].pointer==message) { *result=-1021;return 1; }
        if (retained_request==message || face.request==(uintptr_t)message || remainder_owns(message)) { *result=-1021;return 1; }
        return 0;
    }
    pthread_mutex_lock(&state_mutex);
    int face_releasing=face.request==(uintptr_t)message && sending;
    pthread_mutex_unlock(&state_mutex);
    if (face_releasing) { *result=-1021;return 1; }
    if (remainder_owns(message)) {
        *result=-1021;
        if (record) record("NATIVE_CP_BACKGROUND_REMAINDER_FREE_REFUSED ",
            "request_retained=1 handler_executed=0 completion=0");
        return 1;
    }
    struct reply_lease saved={0};unsigned char observed[12]={0};
    pthread_mutex_lock(&lease_mutex);
    for (unsigned int i=0;i<8;i++) if (leases[i].pointer==message) {
        struct reply_lease *l=&leases[i];saved=*l;
        memcpy(observed,message,sizeof observed); /* live owned payload, before free */
        if (id!=l->destination) { *result=-1021;atomic_fetch_add(&faults,1); }
        else {
            *result=release(id,message);
            if (*result) atomic_fetch_add(&faults,1);
            else {
                l->freed=1;l->pointer=NULL; /* address can immediately be reused */
                if (!l->sending) memset(l,0,sizeof *l);
            }
        }
        break;
    }
    pthread_mutex_unlock(&lease_mutex);
    if (!saved.ticket) {
        int matched=0,can_release=0;unsigned int destination=NATIVE_CP_BACKGROUND_SID,index=REMAINDER_COUNT;
        pthread_mutex_lock(&state_mutex);
        if (retained_request==message) {
            matched=1;
            if (face.request==(uintptr_t)message) destination=NATIVE_CP_FACE_SID;
            for (unsigned int i=0;i<REMAINDER_COUNT;i++)
                if (remainder_pending[i].request==(uintptr_t)message) {
                    index=i;destination=remainder_pending[i].destination;break;
                }
            if (id!=destination || sending) *result=-1021;
            else { sending=1;can_release=1; }
        }
        pthread_mutex_unlock(&state_mutex);
        if (can_release) {
            *result=release(id,message);
            pthread_mutex_lock(&state_mutex);
            if (!*result) {
                retained_request=NULL;
                if (face.request==(uintptr_t)message) { face.request=0;face.retired++; }
                if (index<REMAINDER_COUNT) {
                    remainder_pending[index].request=0;remainder_pending[index].pending=0;
                    remainder_pending[index].retired++;
                    if (index==0) parameter4023.retired++;
                }
            }
            sending=0;
            pthread_mutex_unlock(&state_mutex);
        }
        if (matched && record) {
            char line[180];snprintf(line,sizeof line,"tid=%ld request=%p owner=%#x rc=%d",
                syscall(SYS_gettid),message,id,*result);
            record("NATIVE_CP_BACKGROUND_RETAINED_REQUEST_FREE ",line);
        }
        return matched;
    }
    native_cp_background_free_observer observer=atomic_load(&free_observer);
    if(saved.ticket && saved.opcode==0x3007 && !saved.sending && !*result && !atomic_load(&faults) && observer)observer(id,observed);
    if (saved.ticket && record) {
        char line[270],raw[25];
        for (unsigned int i=0;i<12;i++) snprintf(raw+2*i,3,"%02x",observed[i]);
        snprintf(line,sizeof line,"tid=%ld ticket=%llu destination=%#x message=%p bytes=12 wire=%s rc=%d",
            syscall(SYS_gettid),(unsigned long long)saved.ticket,id,message,raw,*result);
        record("NATIVE_CP_BACKGROUND_REPLY_FREE ",line);
    }
    return saved.ticket!=0;
}
int native_cp_background_parameter_snapshot(struct native_cp_background_parameter_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    pthread_mutex_lock(&state_mutex);
    *out=parameter;
    out->parameter170=u32(config.value+0x170);
    out->parameter_valid=config.known[0x170];
    out->apply_pending=config.apply_pending;
    pthread_mutex_unlock(&state_mutex);
    return 0;
}
int native_cp_background_config_snapshot(struct native_cp_background_config_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    pthread_mutex_lock(&state_mutex);*out=config;pthread_mutex_unlock(&state_mutex);
    return 0;
}
int native_cp_background_async_snapshot(struct native_cp_background_async_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    pthread_mutex_lock(&state_mutex);
    const struct native_cp_background_remainder_snapshot *s=&remainder_pending[4];
    memset(out,0,sizeof *out);out->request=s->request;out->source=s->source;out->opcode=s->opcode;
    out->bytes=s->bytes;out->generation=s->generation;out->pending=s->pending;
    out->retired=s->retired;out->deferred_count=s->deferred_count;
    memcpy(out->wire,s->wire,sizeof out->wire);memcpy(out->first_wire,s->first_wire,sizeof out->first_wire);
    pthread_mutex_unlock(&state_mutex);
    return 0;
}
int native_cp_background_4070_snapshot(struct native_cp_background_4070_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    pthread_mutex_lock(&state_mutex);
    const struct native_cp_background_remainder_snapshot *s=&remainder_pending[5];
    memset(out,0,sizeof *out);out->request=s->request;out->source=s->source;out->opcode=s->opcode;
    out->bytes=s->bytes;out->generation=s->generation;out->pending=s->pending;
    out->retired=s->retired;out->deferred_count=s->deferred_count;
    memcpy(out->wire,s->wire,sizeof out->wire);memcpy(out->first_wire,s->first_wire,sizeof out->first_wire);
    pthread_mutex_unlock(&state_mutex);
    return 0;
}
int native_cp_background_remainder_snapshot(unsigned int destination,unsigned int opcode,
                                           struct native_cp_background_remainder_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    for (unsigned int i=0;i<REMAINDER_COUNT;i++) {
        if (destination!=remainder_commands[i].destination || opcode!=remainder_commands[i].opcode) continue;
        pthread_mutex_lock(&state_mutex);*out=remainder_pending[i];pthread_mutex_unlock(&state_mutex);
        return 0;
    }
    return -1024;
}
/* Request lifetime is independent of the unimplemented semantic backend.
 * first/latest wire and a monotonic count are diagnostics, not an event queue. */
static int retire_slot(unsigned int index,void *request,unsigned int size,
                       const struct full_imaging_io *io,int *result) {
    if (size!=remainder_commands[index].bytes || !io->source || !io->release ||
        io->source(request)!=0x80020002u) { *result=-1020;return 1; }
    if (remainder_commands[index].opcode==0x40de && ((unsigned char *)request)[8]>=6)
        return unsupported(io,result,"release-key-index-out-of-range");
    if (!claim_owner()) return unsupported(io,result,"inherited-profile");
    pthread_mutex_lock(&state_mutex);
    struct native_cp_background_remainder_snapshot *slot=&remainder_pending[index];
    if (sending || atomic_load(&faults) || retained_request || slot->pending ||
        remainder_owns(request) || slot->generation==UINT32_MAX) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"slot-owner-busy-or-fault");
    }
    sending=1;
    slot->request=(uintptr_t)request;slot->destination=remainder_commands[index].destination;
    slot->source=0x80020002u;slot->opcode=remainder_commands[index].opcode;slot->bytes=size;
    if (!slot->generation) memcpy(slot->first_wire,request,size);
    slot->generation++;slot->deferred_count++;slot->pending=1;memcpy(slot->wire,request,size);
    if (slot->opcode==0x4028) {
        /* a49b18()->+8 is unbound: never infer gate!=1 or a CP baseline. */
        slot->signed_delta=(int)slot->wire[8]-(slot->wire[8]&0x80u?256:0);
        slot->mode=slot->wire[9];
        slot->parameter2e4=slot->wire[10]|(unsigned int)slot->wire[11]<<8;
        slot->parameter2e6=slot->wire[12]|(unsigned int)slot->wire[13]<<8;
    }
    if (slot->opcode==0x301a) slot->mode=slot->wire[8];
    atomic_store(&remainder_request[index],(uintptr_t)request);
    struct native_cp_background_remainder_snapshot saved=*slot;
    pthread_mutex_unlock(&state_mutex);
    char line[900],raw[65];
    for (unsigned int i=0;i<size;i++) snprintf(raw+2*i,3,"%02x",saved.wire[i]);
    /* Preserve the existing async diagnostics, but do not pin the request to them. */
    if (index==4 || index==5) {
        snprintf(line,sizeof line,
            "source=%#x opcode=%#x bytes=%u wire=%s generation=%u semantic_pending=%u request_retained=1 gate_known=0 handler_executed=0 worker_submitted=0 bracketing_updated=0 internal0901_delivered=0 internal1010_delivered=0 apply_completed=0 completion=0 backend_missing=%s original_CP=0 capture_verified=0",
            saved.source,saved.opcode,size,raw,saved.generation,saved.deferred_count,remainder_commands[index].missing);
        note(io,index==4?"NATIVE_CP_BACKGROUND_ASYNC_PENDING ":"NATIVE_CP_BACKGROUND_4070_PENDING ",line);
    }
    int freed=io->release(saved.destination,request);
    pthread_mutex_lock(&state_mutex);
    atomic_store(&remainder_request[index],0);
    if (freed) { retained_request=request;atomic_fetch_add(&faults,1); }
    else { slot->request=0;slot->pending=0;slot->retired++; }
    saved=*slot;sending=0;
    pthread_mutex_unlock(&state_mutex);
    snprintf(line,sizeof line,
        "destination=%#x source=%#x opcode=%#x bytes=%u wire=%s generation=%u retired=%u semantic_pending=%u signed_delta=%d mode=%u parameter2e4=%u parameter2e6=%u gate_known=0 parameter_updated=0 request_free_rc=%d request_retained=%u handler_executed=0 worker_submitted=0 bracketing_updated=0 internal0901_delivered=0 internal1010_delivered=0 apply_completed=0 completion=0 backend_missing=%s original_CP=0 capture_verified=0",
        saved.destination,saved.source,saved.opcode,size,raw,saved.generation,saved.retired,saved.deferred_count,
        saved.signed_delta,saved.mode,saved.parameter2e4,saved.parameter2e6,freed,freed!=0,remainder_commands[index].missing);
    note(io,"NATIVE_CP_BACKGROUND_SLOT_RETIRE ",line);
    if (slot->opcode==0x40de) {
        /* CP 0xae17d8: static dispatch 0xce7550=[0,1,0,0,0,1]; key 1/5 drive the slot
         * table at singleton 0x1a2332c+0x158. Value change with the transition flag
         * set makes the original CP itself send 0x4038 (token 0, byte8=value) via
         * 0x4588d4 to 0x90040193. Key 0/2/3/4 path (0x458410/0x4583d4/0x458398 ->
         * 0x4036) stays unmodeled. Virtual baseline: transition=1, current=0. */
        unsigned int key=saved.wire[8], value=saved.wire[9];
        unsigned int path_known=(key==1||key==5), state_changed=0, delivered=0;
        if (path_known) {
            pthread_mutex_lock(&state_mutex);
            if (value!=release_key.current) {
                release_key.current=(unsigned char)value;state_changed=1;
                if (release_key.transition && value) {
                    pthread_mutex_unlock(&state_mutex);
                    void *msg=NULL;
                    if (virtual_cp_profile() && !io->allocate(0x90040193u,&msg,12,1) && msg) {
                        unsigned char *m=msg;
                        memset(m,0,12);m[0]=5;m[2]=0x38;m[3]=0x40;m[8]=(unsigned char)value;
                        io->set_source(msg,NATIVE_CP_BACKGROUND_SID);
                        int send_rc=io->send(0x90040193u,msg);
                        delivered=!send_rc;
                        if (send_rc) io->release(0x90040193u,msg);
                    }
                    pthread_mutex_lock(&state_mutex);
                }
            }
            pthread_mutex_unlock(&state_mutex);
        }
        snprintf(line,sizeof line,
            "destination=%#x source=%#x opcode=0x40de token=%#x key=%u value=%u generation=%u retired=%u path_known=%u key_state_updated=%u internal4038_delivered=%u slot_baseline=virtual-cold-trans1-cur0 pathB_4036_unmodeled=1 request_free_rc=%d receiver_recorded=1 handler_executed=%u completion=0 original_CP=0 capture_verified=0",
            saved.destination,saved.source,u32(saved.wire+4),key,value,saved.generation,saved.retired,
            path_known,state_changed,delivered,freed,path_known);
        note(io,"NATIVE_CP_BACKGROUND_RELEASE_KEY ",line);
    }
    if (saved.opcode==0x4036) {
        /* Original ae18f2 records a kind/token then drives RelMgr asynchronously. */
        snprintf(line,sizeof line,
            "destination=%#x source=%#x opcode=0x4036 token=%#x kind=%u argument=%#x generation=%u retired=%u request_free_rc=%d receiver_recorded=1 kind_state_updated=0 lock_start_notified=0 lock_complete_notified=0 handler_executed=0 completion=0 original_CP=0 capture_verified=0",
            saved.destination,saved.source,u32(saved.wire+4),saved.wire[8],u32(saved.wire+12),
            saved.generation,saved.retired,freed);
        note(io,"NATIVE_CP_BACKGROUND_STILL_LOCK_PENDING ",line);
    }
    if (saved.opcode==0x301a) {
        /* CP 4b6246 copies request[8] to the central8102 event, without an AP reply.
         * shortcut: central state/preview backend unbound; bind before claiming completion. */
        snprintf(line,sizeof line,
            "destination=%#x source=%#x opcode=0x301a token=%#x preview_mode=%u internal_event=0x8102 generation=%u retired=%u request_free_rc=%d receiver_recorded=1 internal8102_delivered=0 preview_mode_applied=0 ap_reply=none handler_executed=0 completion=0 original_CP=0 capture_verified=0",
            saved.destination,saved.source,u32(saved.wire+4),saved.mode,saved.generation,saved.retired,freed);
        note(io,"NATIVE_CP_BACKGROUND_PREVIEW_PENDING ",line);
    }
    if (saved.opcode==0x4070) {
        /* CP 0x357028 submits {thunk 0x8db644, fn 0x475738, id 0x475739} to the
         * worker queue (0x50ff1c). Worker 0x475738: flag 0x1a3ab34=1, apply steps
         * 0x876e48/0xb1a820, and with arg==0 sends 12B type4/0x1010 {token 0,
         * byte8=1} via 0xb1fb5c -> 0x4b3c48 to its CP-side alias of the AP
         * param-owner queue (0x90030001). In-process that literal ID has no
         * consumer (c186 L21: zero 0x9003-family registrations all run), so the
         * cross-chip landing is emulated the same way as the proven 0x40df ACK:
         * deliver to the requesting task's SID tagged from the CP service.
         * Values stay the original wire: token 0, byte8 1. */
        unsigned int delivered1010=0;
        void *msg=NULL;
        if (virtual_cp_profile() && !io->allocate(saved.source,&msg,12,1) && msg) {
            unsigned char *m=msg;
            memset(m,0,12);m[0]=4;m[2]=0x10;m[3]=0x10;m[8]=1;
            io->set_source(msg,NATIVE_CP_BACKGROUND_SID);
            int send_rc=io->send(saved.source,msg);
            delivered1010=!send_rc;
            if (send_rc) io->release(saved.source,msg);
        }
        snprintf(line,sizeof line,
            "destination=%#x source=%#x opcode=0x4070 token=%#x generation=%u retired=%u worker_fn=0x475738 landing=%#x internal1010_delivered=%u delivery_path=cross-chip-requester apply_internals=virtual-unbound request_free_rc=%d handler_executed=1 completion=0 original_CP=0 capture_verified=0",
            saved.destination,saved.source,u32(saved.wire+4),saved.generation,saved.retired,
            saved.source,delivered1010,freed);
        note(io,"NATIVE_CP_BACKGROUND_4070_WORKER ",line);
    }
    if (saved.opcode==0x40de) {
        /* ae17d8 can synthesize 4036/4038; ingress retirement must not invent either. */
        snprintf(line,sizeof line,
            "destination=%#x source=%#x opcode=0x40de token=%#x key=%u value=%u generation=%u retired=%u request_free_rc=%d receiver_recorded=1 key_state_updated=0 internal4036_delivered=0 internal4038_delivered=0 handler_executed=0 completion=0 original_CP=0 capture_verified=0",
            saved.destination,saved.source,u32(saved.wire+4),saved.wire[8],saved.wire[9],
            saved.generation,saved.retired,freed);
        note(io,"NATIVE_CP_BACKGROUND_RELEASE_KEY_PENDING ",line);
    }
    *result=0;return 1;
}
enum parameter_kind { STORE_BYTE, STORE_BOOL, CONSTANT_ONE, FIELDS_4001, FIELDS_400F, FIELDS_4048, FIELDS_4151, DELTA_401C, COUNT_409C, COUNT_4003, PARAMS_4022, PARAMS_4028, COPY_4139, DERIVED_4080, DERIVED_40A3 };
struct parameter_command { unsigned int opcode, bytes, offset, width, apply; enum parameter_kind kind; };
/* CP table 0x10fab8c, handlers pinned in evidence/cp-pins.json. apply is the
 * inverse of the table's apply-control word, not a synthetic success reply. */
static const struct parameter_command commands[]={
    {0x4001,12,0,0,0,FIELDS_4001},
    {0x401c,12,0x2ec,4,1,DELTA_401C},
    {0x402a,12,0x160,4,0,STORE_BYTE},
    {0x4043,8,0x2bd,1,1,CONSTANT_ONE},
    {0x4051,12,0xd18,4,1,STORE_BYTE},
    {0x4084,12,0x337,1,1,STORE_BYTE},
    {0x409c,8,0xb52,1,1,COUNT_409C},
    /* CP 0x354898 (table 0x10fabb4 handler 0x354899 Thumb, checker 0x8db6a0 empty,
     * apply 1): singleton 0x173efe8->+0x34->+0x2a2 nonzero increments parameter
     * byte +0x7a6; the zero branch sends internal 0x901 {1,1} via 0x7ec50e
     * (unmodeled). The singleton is the same unbound object as DERIVED_40A3's,
     * so the gate stays unknown and the counter never mutates here. */
    {0x4003,8,0x7a6,1,1,COUNT_4003},
    /* CP 0x8daaa4 (table 0x10fae70, apply 0, checker 0x35f0bc compare-only):
     * gate [0x173efe8+0x34]+0x2db only guards the prior-value compare whose
     * mismatch zeroes param byte 0x2ba; the 16 stores and the param 0x7a6
     * increment are unconditional. 0x7a6 has no baseline, so it stays a
     * shadow counter here (same policy as COUNT_409C). */
    {0x4022,32,0x6c8,4,0,PARAMS_4022},
    /* CP 0x355b3c (table 0x10fae0c, apply 0, checker 0x35ecac compare-only):
     * singleton 0xa49b18()->+8==1 skips every store; that gate is unbound
     * (0x4023 precedent), so 0x2d8/0x2e0/0x2e4/0x2e6 are dropped to unknown. */
    {0x4028,16,0x2d8,4,0,PARAMS_4028},
    {0x40af,12,0x164,4,1,STORE_BYTE},
    {0x40b8,12,0x170,4,1,STORE_BYTE},
    {0x40c5,12,0x3a4,4,1,STORE_BYTE},
    {0x40d1,12,0xd14,4,1,STORE_BYTE},
    {0x40ed,12,0xbb2,1,1,STORE_BOOL},
    {0x40fb,12,0xaf0,4,1,STORE_BYTE},
    {0x4102,12,0xbec,4,1,STORE_BYTE},
    {0x4139,184,0x870,176,0,COPY_4139},
    {0x4177,12,0x1c4,4,1,STORE_BYTE},
    /* CP 0x359e88 stores request[8] as a word; debug logging has no state effect. */
    {0x40ee,12,0x180,4,1,STORE_BYTE},
    /* CP 0x35482c stores request[8]; mode 2 additionally calls the face backend. */
    {0x4083,12,0xbd1,1,0,STORE_BYTE},
    /* CP 0x3551a8 stores byte/word/byte, including signed bias as its raw byte. */
    {0x4048,12,0,0,1,FIELDS_4048},
    /* CP 0x35cad0 stores ISCN lock mode byte as a word; table apply-control is 0. */
    {0x4167,12,0xcfc,4,1,STORE_BYTE},
    /* CP 0x35be5c zero-extends request[8] into parameter word +0x1a0. */
    {0x414a,12,0x1a0,4,1,STORE_BYTE},
    /* CP 0x354d50 stores the EZOOM byte as a word, then two single bytes. */
    {0x400f,12,0,0,1,FIELDS_400F},
    /* CP 0x35bdec zero-extends request[8] into parameter word +0x19c. */
    {0x4147,12,0x19c,4,1,STORE_BYTE},
    /* CP 0x3597fc zero-extends request[8] into parameter word +0xb24. */
    {0x40d3,12,0xb24,4,1,STORE_BYTE},
    /* CP 0x8db508 stores seven fields with the original word/halfword widths. */
    {0x4151,24,0,0,1,FIELDS_4151},
    /* CP 0x357bd4 stores request[8] as word +0x1fc, then 0x8da97e derives
     * +0x22c/+0x230/+0x234/+0x218 from live parameters; see derive_4080. */
    {0x4080,12,0x1fc,4,1,DERIVED_4080},
    /* CP 0x358754 stores +0x2a0 (external singleton selects request[8] or 0),
     * derives byte +0x2a4 from W[0x138]/W[0x29c]/W[0x2a0], then runs 0x8da97e.
     * The 0x353fec notification-list and 0xb0de20 global helpers are unmodeled
     * and flagged in the accept line. */
    {0x40a3,12,0x2a0,4,1,DERIVED_40A3},
    /* CP 0x8db332 zero-extends request[8] into parameter word +0x750. */
    {0x40a1,12,0x750,4,1,STORE_BYTE},
    /* CP 0x358bac zero-extends request[8] into parameter word +0x780. */
    {0x40b6,12,0x780,4,1,STORE_BYTE},
    /* CP 0x358b14 zero-extends request[8] into parameter word +0x77c. */
    {0x40b4,12,0x77c,4,1,STORE_BYTE},
    /* CP 0x8dad14 zero-extends request[8] into parameter word +0x690. */
    {0x4002,12,0x690,4,1,STORE_BYTE},
    /* CP 0x354bf0 zero-extends request[8] into parameter word +0xb2c; table apply-control is 1 (apply 0). */
    {0x400a,12,0xb2c,4,0,STORE_BYTE},
    /* CP 0x354c38 zero-extends request[8] into parameter word +0xb30; table apply-control is 1 (apply 0). */
    {0x400b,12,0xb30,4,0,STORE_BYTE},
    /* CP 0x354c80 zero-extends request[8] into parameter word +0xb34; table apply-control is 1 (apply 0). */
    {0x400c,12,0xb34,4,0,STORE_BYTE},
    /* CP 0x354cc8 zero-extends request[8] into parameter word +0xb38; table apply-control is 1 (apply 0). */
    {0x400d,12,0xb38,4,0,STORE_BYTE},
    /* CP 0x354dac zero-extends request[8] into parameter word +0x2a8. */
    {0x4010,12,0x2a8,4,1,STORE_BYTE},
    /* CP 0x3555c0 zero-extends request[8] into parameter word +0xcb8; table apply-control is 1 (apply 0). */
    {0x4012,12,0xcb8,4,0,STORE_BYTE},
    /* CP 0x355608 zero-extends request[8] into parameter word +0xcbc; table apply-control is 1 (apply 0). */
    {0x4013,12,0xcbc,4,0,STORE_BYTE},
    /* CP 0x354ebc zero-extends request[8] into parameter word +0xcf8. */
    {0x4017,12,0xcf8,4,1,STORE_BYTE},
    /* CP 0x355154 zero-extends request[8] into parameter word +0x568. */
    {0x401e,12,0x568,4,1,STORE_BYTE},
    /* CP 0x356484 zero-extends request[8] into parameter word +0x964; table apply-control is 1 (apply 0). */
    {0x402f,12,0x964,4,0,STORE_BYTE},
    /* CP 0x355208 zero-extends request[8] into parameter word +0x2c8. */
    {0x403a,12,0x2c8,4,1,STORE_BYTE},
    /* CP 0x356434 zero-extends request[8] into parameter word +0x974; table apply-control is 1 (apply 0). */
    {0x4044,12,0x974,4,0,STORE_BYTE},
    /* CP 0x35690c zero-extends request[8] into parameter word +0xcc4; table apply-control is 1 (apply 0). */
    {0x4049,12,0xcc4,4,0,STORE_BYTE},
    /* CP 0x35529c zero-extends request[8] into parameter byte +0x336. */
    {0x404f,12,0x336,1,1,STORE_BYTE},
    /* CP 0x3553c0 zero-extends request[8] into parameter byte +0x2d4. */
    {0x405a,12,0x2d4,1,1,STORE_BYTE},
    /* CP 0x35540c zero-extends request[8] into parameter byte +0x2e8. */
    {0x405b,12,0x2e8,1,1,STORE_BYTE},
    /* CP 0x356cf8 zero-extends request[8] into parameter word +0x33c. */
    {0x4061,12,0x33c,4,1,STORE_BYTE},
    /* CP 0x356d40 zero-extends request[8] into parameter word +0x700. */
    {0x4064,12,0x700,4,1,STORE_BYTE},
    /* CP 0x356f68 zero-extends request[8] into parameter word +0x590. */
    {0x406e,12,0x590,4,1,STORE_BYTE},
    /* CP 0x357998 zero-extends request[8] into parameter word +0x354. */
    {0x4079,12,0x354,4,1,STORE_BYTE},
    /* CP 0x357a88 zero-extends request[8] into parameter word +0x9b8. */
    {0x407b,12,0x9b8,4,1,STORE_BYTE},
    /* CP 0x357ad8 zero-extends request[8] into parameter word +0xb48. */
    {0x407d,12,0xb48,4,1,STORE_BYTE},
    /* CP 0x357e58 zero-extends request[8] into parameter word +0x1b0. */
    {0x4088,12,0x1b0,4,1,STORE_BYTE},
    /* CP 0x356d84 zero-extends request[8] into parameter word +0x364. */
    {0x40a4,12,0x364,4,1,STORE_BYTE},
    /* CP 0x356dcc zero-extends request[8] into parameter word +0x368. */
    {0x40a9,12,0x368,4,1,STORE_BYTE},
    /* CP 0x8db39e zero-extends request[8] into parameter word +0x754. */
    {0x40b3,12,0x754,4,1,STORE_BYTE},
    /* CP 0x358970 zero-extends request[8] into parameter word +0x16c. */
    {0x40b7,12,0x16c,4,1,STORE_BYTE},
    /* CP 0x35943c zero-extends request[8] into parameter byte +0xb53. */
    {0x40c3,12,0xb53,1,1,STORE_BYTE},
    /* CP 0x358f80 zero-extends request[8] into parameter word +0x3a0. */
    {0x40c4,12,0x3a0,4,1,STORE_BYTE},
    /* CP 0x3594d8 zero-extends request[8] into parameter word +0x788. */
    {0x40c7,12,0x788,4,1,STORE_BYTE},
    /* CP 0x3596cc zero-extends request[8] into parameter word +0x384. */
    {0x40ce,12,0x384,4,1,STORE_BYTE},
    /* CP 0x358910 zero-extends request[8] into parameter word +0x168. */
    {0x40d4,12,0x168,4,1,STORE_BYTE},
    /* CP 0x359b40 zero-extends request[8] into parameter word +0x3c4. */
    {0x40dc,12,0x3c4,4,1,STORE_BYTE},
    /* CP 0x359d44 zero-extends request[8] into parameter word +0x1b4. */
    {0x40e4,12,0x1b4,4,1,STORE_BYTE},
    /* CP 0x359da0 zero-extends request[8] into parameter word +0x3d4. */
    {0x40e6,12,0x3d4,4,1,STORE_BYTE},
    /* CP 0x35a7e0 zero-extends request[8] into parameter word +0xa04. */
    {0x40f1,12,0xa04,4,1,STORE_BYTE},
    /* CP 0x359fe8 zero-extends request[8] into parameter word +0xaf4. */
    {0x40fc,12,0xaf4,4,1,STORE_BYTE},
    /* CP 0x35a03c zero-extends request[8] into parameter word +0xbe8. */
    {0x40fd,12,0xbe8,4,1,STORE_BYTE},
    /* CP 0x35a1f0 zero-extends request[8] into parameter word +0x198. */
    {0x40fe,12,0x198,4,1,STORE_BYTE},
    /* CP 0x35a244 zero-extends request[8] into parameter word +0x7b4. */
    {0x4100,12,0x7b4,4,1,STORE_BYTE},
    /* CP 0x35a29c zero-extends request[8] into parameter word +0x3d8. */
    {0x4101,12,0x3d8,4,1,STORE_BYTE},
    /* CP 0x35a508 zero-extends request[8] into parameter word +0x7b8. */
    {0x4105,12,0x7b8,4,1,STORE_BYTE},
    /* CP 0x35ba7c zero-extends request[8] into parameter word +0xcec. */
    {0x4137,12,0xcec,4,1,STORE_BYTE},
    /* CP 0x35a788 zero-extends request[8] into parameter byte +0x558. */
    {0x4138,12,0x558,1,1,STORE_BYTE},
    /* CP 0x35a8a0 zero-extends request[8] into parameter word +0x36c. */
    {0x413a,12,0x36c,4,1,STORE_BYTE},
    /* CP 0x8db48c zero-extends request[8] into parameter word +0x58. */
    {0x413d,12,0x58,4,1,STORE_BYTE},
    /* CP 0x35a838 zero-extends request[8] into parameter word +0x5b4. */
    {0x413e,12,0x5b4,4,1,STORE_BYTE},
    /* CP 0x356340 zero-extends request[8] into parameter word +0xfc; table apply-control is 1 (apply 0). */
    {0x4141,12,0xfc,4,0,STORE_BYTE},
    /* CP 0x35aabc zero-extends request[8] into parameter word +0x300. */
    {0x4142,12,0x300,4,1,STORE_BYTE},
    /* CP 0x35becc zero-extends request[8] into parameter word +0x3dc. */
    {0x4145,12,0x3dc,4,1,STORE_BYTE},
    /* CP 0x35bf20 zero-extends request[8] into parameter word +0x3e0. */
    {0x4146,12,0x3e0,4,1,STORE_BYTE},
    /* CP 0x35c00c zero-extends request[8] into parameter word +0x7c0. */
    {0x414c,12,0x7c0,4,1,STORE_BYTE},
    /* CP 0x358a20 zero-extends request[8] into parameter word +0x174. */
    {0x414f,12,0x174,4,1,STORE_BYTE},
    /* CP 0x35c708 stores constant 1 as a word. */
    {0x415c,8,0x404,4,1,CONSTANT_ONE},
    /* CP 0x35c924 zero-extends request[8] into parameter byte +0x409. */
    {0x4161,12,0x409,1,1,STORE_BYTE},
    /* CP 0x35c9e4 zero-extends request[8] into parameter word +0xb0c. */
    {0x4163,12,0xb0c,4,1,STORE_BYTE},
    /* CP 0x35ca88 zero-extends request[8] into parameter word +0xd4. */
    {0x4166,12,0xd4,4,1,STORE_BYTE},
    /* CP 0x35cbe4 zero-extends request[8] into parameter word +0x414. */
    {0x4169,12,0x414,4,1,STORE_BYTE},
    /* CP 0x35cb90 zero-extends request[8] into parameter word +0x3ac. */
    {0x416a,12,0x3ac,4,1,STORE_BYTE},
    /* CP 0x35cc40 zero-extends request[8] into parameter word +0xba0. */
    {0x416c,12,0xba0,4,1,STORE_BYTE}
};
static void store_parameter(unsigned int offset,unsigned int width,uint32_t value) {
    for (unsigned int i=0;i<width;i++) {
        config.value[offset+i]=(unsigned char)(value>>(8*i));
        config.known[offset+i]=1;
    }
}
int native_cp_background_4023_snapshot(struct native_cp_background_4023_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    pthread_mutex_lock(&state_mutex);*out=parameter4023;pthread_mutex_unlock(&state_mutex);
    return 0;
}
static int known_word(unsigned int offset) {
    return config.known[offset] && config.known[offset+1] &&
        config.known[offset+2] && config.known[offset+3];
}
struct derived4080 { unsigned int branch_known, branch, known[4]; uint32_t value[4]; };
static void derived4080_store(unsigned int offset,unsigned int width,unsigned int known,uint32_t value) {
    for (unsigned int i=0;i<width;i++) {
        if (known) { config.value[offset+i]=(unsigned char)(value>>(8*i));config.known[offset+i]=1; }
        else config.known[offset+i]=0;
    }
}
/* CP 0x8da97e direct transcription (branch order and selects included). The
 * original overwrites all four outputs unconditionally; a store whose inputs
 * are not proven known is dropped to unknown, never a zero baseline. */
static void derive_4080(struct derived4080 *out) {
    out->branch_known=0;out->branch=0;
    for (unsigned int i=0;i<4;i++) { out->known[i]=0;out->value[i]=0; }
    if (known_word(0x21c) && u32(config.value+0x21c)==1) {
        out->branch_known=1;out->branch=1;
        out->known[0]=out->known[1]=out->known[2]=1;
        out->value[0]=out->value[1]=out->value[2]=2;
        if (known_word(0x214)) { out->known[3]=1;out->value[3]=u32(config.value+0x214)==1; }
    } else if (known_word(0x21c) && config.known[0x2a4]) {
        if (config.value[0x2a4]==2) {
            out->branch_known=1;out->branch=2;
            out->known[0]=out->known[1]=out->known[2]=out->known[3]=1;
        } else {
            out->branch_known=1;out->branch=3;
            if (known_word(0x1fc) && u32(config.value+0x1fc)==1) {
                unsigned int selected_known=0,selected=0;
                if (config.known[0x228]) {
                    if (config.value[0x228]) {
                        if (known_word(0x224)) { selected_known=1;selected=u32(config.value+0x224); }
                    } else if (known_word(0x200)) { selected_known=1;selected=u32(config.value+0x200); }
                }
                if (selected_known) { out->known[0]=1;out->value[0]=selected==1; }
            } else if (known_word(0x1fc)) { out->known[0]=1;out->value[0]=0; }
            if (known_word(0x208)) {
                if (u32(config.value+0x208)!=1) { out->known[1]=1;out->value[1]=0; }
                else if (known_word(0x204)) {
                    unsigned int mode=u32(config.value+0x204);
                    out->known[1]=1;out->value[1]=mode==2?3:mode==1?1:0;
                }
            }
            if (known_word(0x20c) && known_word(0x210)) {
                out->known[2]=out->known[3]=1;
                out->value[2]=(u32(config.value+0x20c)==1)&(u32(config.value+0x210)==1);
                out->value[3]=out->value[2];
            }
        }
    }
    derived4080_store(0x22c,4,out->known[0],out->value[0]);
    derived4080_store(0x230,4,out->known[1],out->value[1]);
    derived4080_store(0x234,4,out->known[2],out->value[2]);
    derived4080_store(0x218,1,out->known[3],out->value[3]);
}
/* 0=no event, 1=conditional (unknown inputs), 2=required. a98592 is constant 0. */
static unsigned int central4023(unsigned int value,unsigned int old,unsigned int old_known) {
    if (value==0 || value==8 || (old_known && old==value)) return 0;
    if ((known_word(0x134) && u32(config.value+0x134)) ||
        (known_word(0x198) && u32(config.value+0x198))) return 0;
    return old_known && known_word(0x134) && known_word(0x198)?2:1;
}
static int accept_4023(void *request,unsigned int size,const struct full_imaging_io *io,int *result) {
    if (size!=12 || !io->source || !io->release || io->source(request)!=0x80020002u) {
        *result=-1020;return 1;
    }
    if (!claim_owner()) return unsupported(io,result,"inherited-profile");
    pthread_mutex_lock(&state_mutex);
    if (sending || atomic_load(&faults) || retained_request || remainder_owns(request) ||
        config.generation==UINT32_MAX || parameter4023.generation==UINT32_MAX) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"4023-owner-busy-or-fault");
    }
    const unsigned char *body=request;
    unsigned int value=body[8],old=u32(config.value+0x688),old_known=known_word(0x688);
    unsigned int event=central4023(value,old,old_known);
    /* shortcut: one copied central obligation until config/actor consumers exist; never overwrite it. */
    if (event && parameter4023.central_pending) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"4023-central-backend-busy");
    }
    sending=1;
    struct native_cp_background_remainder_snapshot *slot=&remainder_pending[0];
    slot->request=(uintptr_t)request;slot->destination=NATIVE_CP_BACKGROUND_SID;
    slot->source=0x80020002u;slot->opcode=0x4023;slot->bytes=12;
    if (!slot->generation) memcpy(slot->first_wire,body,12);
    slot->generation=++parameter4023.generation;slot->pending=1;memcpy(slot->wire,body,12);
    atomic_store(&remainder_request[0],(uintptr_t)request);
    if (event) {
        parameter4023.central_pending=event;
        parameter4023.central_generation=parameter4023.generation;
        parameter4023.central_old688=old;parameter4023.central_old688_known=old_known;
        parameter4023.central_p134=u32(config.value+0x134);
        parameter4023.central_p134_known=known_word(0x134);
        parameter4023.central_p198=u32(config.value+0x198);
        parameter4023.central_p198_known=known_word(0x198);
        memcpy(parameter4023.central_request,body,12);
        memset(parameter4023.central_wire,0,32);
        parameter4023.central_wire[4]=6;parameter4023.central_wire[5]=0x83;
    }
    /* Config-root byte+2db is unbound. A changed value still proves this store;
     * an unchanged value never permits a fabricated false config gate. */
    if (old_known && old!=value) {
        store_parameter(0x2ba,1,0);parameter4023.clear2ba_pending=0;
    } else if (!config.known[0x2ba] || config.value[0x2ba]) {
        parameter4023.clear2ba_pending=1;
        config.known[0x2ba]=0;
    }
    if (value<=1) {
        if (!old_known) parameter4023.initial_transition_unknown=1;
        else if ((value==0 && old==1) || (value==1 && old==0)) {
            parameter4023.counter_delta=(unsigned char)(parameter4023.counter_delta+1u);
            if (config.known[0x7a6]) store_parameter(0x7a6,1,(unsigned char)(config.value[0x7a6]+1u));
        }
        if (!old_known) config.known[0x7a6]=0;
    }
    store_parameter(0x688,4,value);store_parameter(0x720,1,body[10]);
    config.apply_pending=1;config.generation++;config.last_opcode=0x4023;config.wire_bytes=12;
    memset(config.wire,0,sizeof config.wire);memcpy(config.wire,body,12);
    parameter4023.parameter688=value;parameter4023.parameter720=body[10];
    parameter4023.parameter_valid=1;memcpy(parameter4023.wire,body,12);
    pthread_mutex_unlock(&state_mutex);
    int freed=io->release(NATIVE_CP_BACKGROUND_SID,request);
    pthread_mutex_lock(&state_mutex);
    atomic_store(&remainder_request[0],0);
    if (freed) { retained_request=request;atomic_fetch_add(&faults,1); }
    else { slot->request=0;slot->pending=0;slot->retired++;parameter4023.retired++; }
    struct native_cp_background_4023_snapshot saved=parameter4023;
    sending=0;
    pthread_mutex_unlock(&state_mutex);
    char line[700],raw[25];
    for (unsigned int i=0;i<12;i++) snprintf(raw+2*i,3,"%02x",saved.wire[i]);
    snprintf(line,sizeof line,
        "source=0x80020002 opcode=0x4023 bytes=12 wire=%s generation=%u retired=%u parameter688=%#x parameter720=%#x counter_delta=%u initial_transition_unknown=%u clear2ba_pending=%u central_pending=%u central_generation=%u central_delivered=0 apply_pending=1 apply_completed=0 request_free_rc=%d request_retained=%u handler_complete=0 completion=0 original_CP=0 capture_verified=0",
        raw,saved.generation,saved.retired,saved.parameter688,saved.parameter720,saved.counter_delta,
        saved.initial_transition_unknown,saved.clear2ba_pending,saved.central_pending,saved.central_generation,freed,freed!=0);
    note(io,"NATIVE_CP_BACKGROUND_4023_RETIRE ",line);
    *result=0;return 1;
}
static int parameter_accept(const struct parameter_command *command,void *request,unsigned int size,
                            const struct full_imaging_io *io,int *result) {
    const unsigned char *body=request;
    if (size!=command->bytes || !io->source || !io->release) {
        *result=-1020;return 1;
    }
    unsigned int source=io->source(request);
    if (source!=0x80020002u) { *result=-1020;return 1; }
    /* shortcut: mode 2 needs CP7ec50e's face backend; reject before any mutation. */
    if (command->opcode==0x4083 && body[8]==2)
        return unsupported(io,result,"4083-mode2-face-backend-missing");
    if (!claim_owner()) return unsupported(io,result,"inherited-profile");
    pthread_mutex_lock(&state_mutex);
    if (sending || atomic_load(&faults) || retained_request || remainder_owns(request) || config.generation==UINT32_MAX ||
        (command->opcode==0x40b8 && parameter.generation==UINT32_MAX)) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"parameter-owner-busy-or-fault");
    }
    sending=1;
    struct derived4080 derived={0};
    struct { unsigned int b2a4_known,b2a4,store_known; uint32_t store_value; } derived40a3={0,0,0,0};
    unsigned int gate7a6_known=0,gate7a6=0;
    switch (command->kind) {
    case STORE_BYTE:store_parameter(command->offset,command->width,body[8]);break;
    case STORE_BOOL:store_parameter(command->offset,1,body[8]!=0);break;
    case CONSTANT_ONE:store_parameter(command->offset,command->width,1);break;
    case FIELDS_4001:
        store_parameter(0x69c,4,body[8]);store_parameter(0x698,1,body[9]);
        store_parameter(0x6a0,4,body[10]);store_parameter(0x6a4,1,body[11]);break;
    case FIELDS_400F:
        store_parameter(0xb10,4,body[8]);store_parameter(0xb14,1,body[9]);
        store_parameter(0xb15,1,body[10]);break;
    case FIELDS_4048:
        store_parameter(0x2c0,1,body[8]);store_parameter(0x2c4,4,body[9]);
        store_parameter(0x2bf,1,body[10]);break;
    case FIELDS_4151:
        store_parameter(0x3e8,4,u32(body+8));
        store_parameter(0x3ec,2,body[12]|(unsigned int)body[13]<<8);
        store_parameter(0x3f0,4,body[14]);store_parameter(0x3f4,4,u32(body+16));
        store_parameter(0x3f8,2,body[20]|(unsigned int)body[21]<<8);
        store_parameter(0x3fc,4,body[22]);store_parameter(0x400,4,body[23]);break;
    case DELTA_401C:
        /* Preserve modular signed-byte addition without inventing a CP baseline. */
        config.delta2ec+=(uint32_t)(body[8]<128?(int)body[8]:(int)body[8]-256);
        store_parameter(0x2f4,4,body[9]);break;
    case COUNT_409C:config.deltab52=(unsigned char)(config.deltab52+1u);break;
    case COUNT_4003:
        /* gate [0x173efe8+0x34]+0x2a2 is unbound (same singleton as 40a3); no mutation. */
        gate7a6_known=config.known[0x7a6];gate7a6=config.value[0x7a6];
        break;
    case PARAMS_4022: {
        unsigned int half6ac=body[10]|(unsigned int)body[11]<<8;
        unsigned int half6ae=body[12]|(unsigned int)body[13]<<8;
        unsigned int half6cc=body[14]|(unsigned int)body[15]<<8;
        unsigned int half6ce=body[16]|(unsigned int)body[17]<<8;
        unsigned int half6d0=body[20]|(unsigned int)body[21]<<8;
        unsigned int half6d2=body[18]|(unsigned int)body[19]<<8;
        unsigned int half778=body[28]|(unsigned int)body[29]<<8;
        unsigned int half77a=body[30]|(unsigned int)body[31]<<8;
        store_parameter(0x6c8,4,body[8]);
        store_parameter(0x6ac,2,half6ac);store_parameter(0x6ae,2,half6ae);
        store_parameter(0x6cc,2,half6cc);store_parameter(0x6ce,2,half6ce);
        store_parameter(0x6d0,2,half6d0);store_parameter(0x6d2,2,half6d2);
        store_parameter(0x774,4,body[22]);store_parameter(0x784,4,body[23]);
        store_parameter(0x6d4,4,body[24]);store_parameter(0x6d8,4,body[25]);
        store_parameter(0x6dc,4,body[26]);store_parameter(0x6e0,4,body[27]);
        store_parameter(0x778,2,half778);store_parameter(0x77a,2,half77a);
        config.count7a6=(unsigned char)(config.count7a6+1u);
        break;
    }
    case PARAMS_4028:
        config.known[0x2d8]=0;config.known[0x2e0]=0;
        config.known[0x2e4]=0;config.known[0x2e6]=0;
        break;
    case COPY_4139:
        memcpy(config.value+0x870,body+8,176);memset(config.known+0x870,1,176);
        store_parameter(0x86f,1,1);break;
    case DERIVED_4080:
        store_parameter(0x1fc,4,body[8]);derive_4080(&derived);break;
    case DERIVED_40A3: {
        /* 0x358754: singleton 0x173efe8->+0xc->+0x950 null selects request[8]
         * (else 0); unknown singleton means the store is known only when both
         * branches agree (request[8]==0). */
        if (body[8]==0) store_parameter(0x2a0,4,0);
        else derived4080_store(0x2a0,4,0,0);
        derived40a3.store_known=known_word(0x2a0);derived40a3.store_value=u32(config.value+0x2a0);
        unsigned int b2a4_known=0,b2a4=0;
        if (known_word(0x138) && u32(config.value+0x138)==0x20) { b2a4_known=1;b2a4=2; }
        else if (known_word(0x138) && u32(config.value+0x138)==0x1f) b2a4_known=0;
        else if (known_word(0x138) && known_word(0x29c)) {
            if (u32(config.value+0x29c)==2) { b2a4_known=1;b2a4=1; }
            else if (u32(config.value+0x29c)==1) {
                if (known_word(0x2a0)) { b2a4_known=1;b2a4=u32(config.value+0x2a0)==1; }
            } else { b2a4_known=1;b2a4=0; }
        }
        derived4080_store(0x2a4,1,b2a4_known,b2a4);
        derived40a3.b2a4_known=b2a4_known;derived40a3.b2a4=b2a4;
        derive_4080(&derived);
        break;
    }
    }
    config.apply_pending|=command->apply;
    config.generation++;config.last_opcode=command->opcode;config.wire_bytes=size;
    memset(config.wire,0,sizeof config.wire);memcpy(config.wire,body,size);
    if (command->opcode==0x40b8) {
        parameter.generation++;memcpy(parameter.wire,body,12);
    }
    unsigned int generation=config.generation,pending=config.apply_pending;
    unsigned int value=command->width==4?u32(config.value+command->offset):
        command->width==1?config.value[command->offset]:0;
    unsigned int relative=command->kind==DELTA_401C || command->kind==COUNT_409C;
    unsigned int known=command->width<=4?config.known[command->offset]:1;
    pthread_mutex_unlock(&state_mutex);
    /* shortcut: preserve CP996fec's dirty flag; attach the periodic apply backend before claiming applied. */
    int freed=io->release(NATIVE_CP_BACKGROUND_SID,request);
    pthread_mutex_lock(&state_mutex);
    if (freed) { retained_request=request;atomic_fetch_add(&faults,1); }
    sending=0;
    pthread_mutex_unlock(&state_mutex);
    char line[600];snprintf(line,sizeof line,
        "tid=%ld source=%#x generation=%u opcode=%#x bytes=%u parameter_offset=%#x parameter_bytes=%u value=%#x value_known=%u apply_flag=%#x apply_marked=%u apply_pending=%u apply_completed=0 relative_only=%u request_free_rc=%d handler_executed=1 completion=0 original_CP=0 capture_verified=0",
        syscall(SYS_gettid),source,generation,command->opcode,size,command->offset,command->width,value,known,
        command->apply?0x1b16058:0,command->apply,pending,relative,freed);
    note(io,"NATIVE_CP_BACKGROUND_PARAMETER_ACCEPT ",line);
    if (command->kind==DERIVED_4080) {
        char derived_line[420];
        snprintf(derived_line,sizeof derived_line,
            "tid=%ld opcode=0x4080 branch_known=%u branch=%u derived22c_known=%u derived22c=%#x derived230_known=%u derived230=%#x derived234_known=%u derived234=%#x derived218_known=%u derived218=%#x unknown_predecessors_dropped=%u helper=0x8da97e apply_completed=0 completion=0 original_CP=0 capture_verified=0",
            syscall(SYS_gettid),derived.branch_known,derived.branch,
            derived.known[0],derived.value[0],derived.known[1],derived.value[1],
            derived.known[2],derived.value[2],derived.known[3],derived.value[3],
            4u-(derived.known[0]+derived.known[1]+derived.known[2]+derived.known[3]));
        note(io,"NATIVE_CP_BACKGROUND_4080_DERIVED ",derived_line);
    }
    if (command->kind==DERIVED_40A3) {
        char derived_line[512];
        snprintf(derived_line,sizeof derived_line,
            "tid=%ld opcode=0x40a3 chain_branch_known=0 store2a0_known=%u store2a0=%#x byte2a4_known=%u byte2a4=%#x derived22c_known=%u derived22c=%#x derived230_known=%u derived230=%#x derived234_known=%u derived234=%#x derived218_known=%u derived218=%#x unmodeled_helpers=0x353fec+0xb0de20 recalc=0x8da97e apply_completed=0 completion=0 original_CP=0 capture_verified=0",
            syscall(SYS_gettid),derived40a3.store_known,derived40a3.store_value,
            derived40a3.b2a4_known,derived40a3.b2a4,
            derived.known[0],derived.value[0],derived.known[1],derived.value[1],
            derived.known[2],derived.value[2],derived.known[3],derived.value[3]);
        note(io,"NATIVE_CP_BACKGROUND_40A3_DERIVED ",derived_line);
    }
    if (command->kind==COUNT_4003) {
        char gate_line[360];
        snprintf(gate_line,sizeof gate_line,
            "tid=%ld opcode=0x4003 gate_singleton=0x173efe8 gate_known=0 parameter7a6_known=%u parameter7a6=%#x internal0901_delivered=0 unmodeled_helpers=0x7ec50e apply_completed=0 completion=0 original_CP=0 capture_verified=0",
            syscall(SYS_gettid),gate7a6_known,gate7a6);
        note(io,"NATIVE_CP_BACKGROUND_4003_GATE ",gate_line);
    }
    /* Successful supported parameter handlers do not emit independent ACKs. */
    *result=0;return 1;
}
/* CP7e9e78 stores the recipient/mask; CP7ec468 overwrites 7 of 16 shared bytes. */
int native_cp_background_face_snapshot(struct native_cp_background_face_snapshot *out) {
    if (!out) return -1024;
    if (!claim_owner()) return -1021;
    pthread_mutex_lock(&state_mutex);*out=face;pthread_mutex_unlock(&state_mutex);
    return 0;
}
static int face_accept(void *request,unsigned int size,const struct full_imaging_io *io,int *result) {
    if (size!=12 || !io->source || !io->release || io->source(request)!=0x80020002u) {
        *result=-1020;return 1;
    }
    if (!claim_owner()) return unsupported(io,result,"inherited-profile");
    pthread_mutex_lock(&state_mutex);
    if (sending || atomic_load(&faults) || retained_request || remainder_owns(request) || face.generation==UINT32_MAX) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"face-owner-busy-or-fault");
    }
    sending=1;face.request=(uintptr_t)request;face.generation++;
    memcpy(face.wire,request,12);
    face.enabled=1;face.recipient=u32(face.wire+4);face.mask=face.wire[8]|(unsigned int)face.wire[9]<<8;
    face.shared_value[4]=1;face.shared_known[4]=1;
    memcpy(face.shared_value+6,face.wire+8,2);memset(face.shared_known+6,1,2);
    memcpy(face.shared_value+8,face.wire+4,4);memset(face.shared_known+8,1,4);
    /* shortcut: retain unknown shared bytes; bind the real settings consumer before claiming hardware apply. */
    struct native_cp_background_face_snapshot saved=face;
    pthread_mutex_unlock(&state_mutex);
    int freed=io->release(NATIVE_CP_FACE_SID,request);
    pthread_mutex_lock(&state_mutex);
    if (freed) { retained_request=request;atomic_fetch_add(&faults,1); }
    else { face.request=0;face.retired++; }
    saved.retired=face.retired;sending=0;
    pthread_mutex_unlock(&state_mutex);
    char line[600],raw[25];
    for (unsigned int i=0;i<12;i++) snprintf(raw+2*i,3,"%02x",saved.wire[i]);
    snprintf(line,sizeof line,
        "destination=%#x source=0x80020002 type=2 index=7 bytes=12 wire=%s generation=%u retired=%u enabled=%u recipient=%#x mask=%#x shared_key=0x6000c shared_bytes=16 shared_known_bytes=7 shared_updated=1 handler_executed=1 apply_completed=0 request_free_rc=%d request_retained=%u result_emitted=0 completion=0 original_CP=0 capture_verified=0",
        NATIVE_CP_FACE_SID,raw,saved.generation,saved.retired,saved.enabled,saved.recipient,saved.mask,freed,freed!=0);
    note(io,"NATIVE_CP_FACE_RESULT_RECEIVER_ACCEPT ",line);
    *result=0;return 1;
}
int native_cp_background_dispatch(unsigned int destination,void *request,
                                 const struct full_imaging_io *io,int enabled,int *result) {
    if (!enabled || (destination!=NATIVE_CP_BACKGROUND_SID && destination!=NATIVE_CP_CAPTURE_SID && destination!=NATIVE_CP_FACE_SID) || !result) return 0;
    if (!request || !io || !io->size) {
        if (destination==NATIVE_CP_CAPTURE_SID) return 0;
        return unsupported(io,result,"missing-transport");
    }
    if (remainder_owns(request)) return unsupported(io,result,"remainder-owned-pointer");
    unsigned int size=io->size(request);
    const unsigned char *body=request;
    if (destination==NATIVE_CP_FACE_SID) {
        if (size>=2 && body[0]==2 && body[1]==7) return face_accept(request,size,io,result);
        return 0;
    }
    /* A control overlay, not replacement of every CP channel. Returning
     * unhandled delegates to the original transport without inventing its
     * return value, accepting its packet or claiming a peripheral effect. */
    unsigned int opcode=size>=4?(unsigned int)body[2]|(unsigned int)body[3]<<8:0;
    if (size>=4) {
        if (body[0]==5 && destination==NATIVE_CP_BACKGROUND_SID && opcode==0x4023)
            return accept_4023(request,size,io,result);
        for (unsigned int i=0;i<REMAINDER_COUNT;i++)
            if (body[0]==(remainder_commands[i].opcode==0x301a?0:5) &&
                destination==remainder_commands[i].destination && opcode==remainder_commands[i].opcode)
                return retire_slot(i,request,size,io,result);
    }
    if (destination==NATIVE_CP_CAPTURE_SID) return 0;
    if (size>=4 && body[0]==5) {
        for (unsigned int i=0;i<sizeof commands/sizeof commands[0];i++)
            if (opcode==commands[i].opcode) return parameter_accept(&commands[i],request,size,io,result);
    }
    int push_mr=size>=4 && body[0]==5 && opcode==0x40df;
    if (!push_mr && (size<4 || body[0] || opcode!=0x3007)) {
        /* Observation only: record what the original AP really addressed here
         * (for example a 4000-series lens batch) and delegate untouched. No
         * reply, lease, allocation or ownership change happens on this path. */
        if (io->record) {
            char line[220];
            snprintf(line,sizeof line,"tid=%ld destination=%#x source=%#x type=%u opcode=%#x size=%u delegated=1",
                     syscall(SYS_gettid),destination,io->source?io->source(request):0,
                     size?body[0]:0,opcode,size);
            io->record("NATIVE_CP_BACKGROUND_UNHANDLED ",line);
        }
        return 0;
    }
    if (!io->allocate || !io->release || !io->send || !io->set_source || !io->source)
        return unsupported(io,result,"missing-transport");
    if (atomic_load(&owner_pid) && atomic_load(&owner_pid)!=getpid())
        return unsupported(io,result,"inherited-profile");
    unsigned int source=io->source(request);
    if (push_mr) {
        if (size!=16 || source!=0x80020002u) { *result=-1020;return 1; }
    } else if (size!=24 || !source || source==NATIVE_CP_BACKGROUND_SID)
        return unsupported(io,result,"only-type0-24B-3007-supported");
    /* Original libObj writes type and command only; byte1 and +8..23 are
     * uninitialized. The original 3007 receiver copies opaque/source into a
     * zeroed internal event and does not consume these bytes as arguments. */
    unsigned int opaque=u32(body+4);
    if (!claim_owner()) return unsupported(io,result,"inherited-profile");
    pthread_mutex_lock(&state_mutex);
    if ((!push_mr && initialize()) || sending || atomic_load(&faults) || !next_ticket ||
        (push_mr && (retained_request || remainder_owns(request) || config.generation==UINT32_MAX))) {
        pthread_mutex_unlock(&state_mutex);return unsupported(io,result,"busy-fault-or-initialization");
    }
    unsigned int slot=8;
    pthread_mutex_lock(&lease_mutex);
    for (unsigned int i=0;i<8;i++) if (!leases[i].ticket) { slot=i;break; }
    if (slot==8) {
        pthread_mutex_unlock(&lease_mutex);pthread_mutex_unlock(&state_mutex);
        return unsupported(io,result,"reply-leases-full");
    }
    uint64_t ticket=next_ticket++;
    leases[slot]=(struct reply_lease){.ticket=ticket,.destination=source,.sending=1,.opcode=opcode};
    sending=1;
    pthread_mutex_unlock(&lease_mutex);pthread_mutex_unlock(&state_mutex);

    /* Allocation may wait for the receiver to free older packets. No model
     * mutex is held, and the original request remains caller-owned on error. */
    void *reply=NULL;
    int rc=io->allocate(source,&reply,12,1);
    if (rc || !reply) {
        pthread_mutex_lock(&lease_mutex);memset(&leases[slot],0,sizeof leases[slot]);pthread_mutex_unlock(&lease_mutex);
        done_sending();*result=rc?rc:-1021;return 1;
    }
    pthread_mutex_lock(&lease_mutex);leases[slot].pointer=reply;pthread_mutex_unlock(&lease_mutex);
    struct cp_cold_snapshot state={0};unsigned int generation=0;
    if (push_mr) {
        /* CP359bf8: five exact stores precede the synchronous 40df/f000 ACK.
         * Byte11 and parameter+3cf are padding; preserve their unknown state. */
        pthread_mutex_lock(&state_mutex);
        store_parameter(0x3cc,1,body[8]);store_parameter(0x3cd,1,body[9]);
        store_parameter(0x3ce,1,body[10]);
        store_parameter(0x3d0,2,body[12]|(unsigned int)body[13]<<8);
        store_parameter(0x3d2,2,body[14]|(unsigned int)body[15]<<8);
        generation=++config.generation;config.last_opcode=opcode;config.wire_bytes=size;
        memset(config.wire,0,sizeof config.wire);memcpy(config.wire,body,size);
        pthread_mutex_unlock(&state_mutex);
    } else {
        rc=cp_cold_begin(control,0x3007);
        for (unsigned int i=0;!rc && i<8;i++) {
            int tick=cp_cold_tick(control);
            if (tick==1) { rc=1;break; }
            if (tick<0) { rc=tick;break; }
        }
        unsigned int command=0;
        if (rc==1 && !cp_cold_take_end(control,&command) && command==0x3007 &&
            !cp_cold_observe_end(control,command) && !cp_cold_snapshot(control,&state)) rc=0;
        else { atomic_fetch_add(&faults,1);rc=-1021; }
    }
    if (!rc) {
        unsigned char *out=reply;
        memset(out,0,12);out[0]=1;out[2]=(unsigned char)opcode;out[3]=(unsigned char)(opcode>>8);
        put32(out+4,opaque);put32(out+8,0xf000);
        io->set_source(reply,NATIVE_CP_BACKGROUND_SID);
        char line[500];
        snprintf(line,sizeof line,"tid=%ld ticket=%llu model_mode=%u request_mode=0 generation=%u current=%#x group=%u slot0=%#x pending_modules=%#x parameter_valid=%u partial_state_generation=%u observer_a=%u observer_b=%u exec_active=%u exec_last_event=%#x destination=%#x opaque=%#x hardware_ready=0",
            syscall(SYS_gettid),(unsigned long long)ticket,state.model_mode,state.generation,state.current,state.group,
            state.observed[0],state.pending_modules,state.parameter_valid,state.state_record_generation,
            state.observer_a_index,state.observer_b_index,state.exec_active,state.exec_last_event,source,opaque);
        if (!push_mr) note(io,"NATIVE_CP_BACKGROUND_CONTROL ",line);
        else {
            snprintf(line,sizeof line,
                "tid=%ld ticket=%llu source=%#x opcode=0x40df bytes=16 generation=%u handler_executed=1 ack_status=0xf000 ack_queued=0 apply_completed=0 completion=0 original_CP=0 capture_verified=0",
                syscall(SYS_gettid),(unsigned long long)ticket,source,generation);
            note(io,"NATIVE_CP_BACKGROUND_PUSH_MR_STORE ",line);
        }
        /* No lock across send: a receiver may free the reply before it returns. */
        rc=io->send(source,reply);
    }
    if (push_mr) {
        /* Table10fbba4 apply-control=0: common35d080 marks dirty after the ACK helper. */
        pthread_mutex_lock(&state_mutex);config.apply_pending=1;pthread_mutex_unlock(&state_mutex);
    }
    pthread_mutex_lock(&lease_mutex);
    struct reply_lease *lease=&leases[slot];
    if (lease->ticket!=ticket) { atomic_fetch_add(&faults,1);rc=-1021; }
    else {
        lease->sending=0;
        if (rc && !lease->freed) {
            int freed=io->release(source,reply);
            if (freed) atomic_fetch_add(&faults,1);
            else { lease->pointer=NULL;lease->freed=1; }
        }
        if (lease->freed) memset(lease,0,sizeof *lease);
    }
    pthread_mutex_unlock(&lease_mutex);
    if (rc) { atomic_fetch_add(&faults,1);done_sending();*result=rc;return 1; }
    /* Successful queue transfer consumes exactly the original request. */
    int freed=io->release(NATIVE_CP_BACKGROUND_SID,request);
    if (freed) {
        atomic_fetch_add(&faults,1);
        pthread_mutex_lock(&state_mutex);retained_request=request;pthread_mutex_unlock(&state_mutex);
    }
    char line[400];snprintf(line,sizeof line,"tid=%ld ticket=%llu source=%#x request=%p reply_queue_rc=0 request_free_rc=%d camera_recovery_verified=0",
        syscall(SYS_gettid),(unsigned long long)ticket,source,request,freed);
    if (!push_mr) note(io,"NATIVE_CP_BACKGROUND_ACCEPT ",line);
    else {
        snprintf(line,sizeof line,
            "tid=%ld ticket=%llu source=%#x opcode=0x40df generation=%u ack_queued=1 ack_status=0xf000 request_free_rc=%d handler_executed=1 apply_pending=1 apply_completed=0 completion=0 original_CP=0 capture_verified=0",
            syscall(SYS_gettid),(unsigned long long)ticket,source,generation,freed);
        note(io,"NATIVE_CP_BACKGROUND_PUSH_MR_ACCEPT ",line);
    }
    done_sending();*result=0;return 1;
}
