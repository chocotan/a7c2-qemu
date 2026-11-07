/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-camera-control.h"
#include "cp-parameter-batch.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

enum { START_REQUEST, START_ACK, MODE_REQUEST, MODE_ACK, FULL_NOTICE };
enum { REQUEST_ROLE = 1, ACK_ROLE, NOTICE_ROLE };
enum { PUBLIC_FREE, REQUEST_FREE, CLEANUP_FREE };
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local unsigned int inspecting;
static struct native_functional_camera_control_snapshot state;
static struct full_imaging_io transport;
static unsigned char wires[FUNCTIONAL_CAMERA_CONTROL_LEASES][CP_STATE_SNAPSHOT_BYTES];
static unsigned int started[FUNCTIONAL_CAMERA_CONTROL_LEASES];
static uint64_t completed_cycle;

/* The lock pins these slots across all external callbacks, including real free. */
static int mode_retired(void) {
    if (state.mode_cycle_id && !state.mode_complete) return 0;
    for (unsigned int i = MODE_REQUEST; i <= FULL_NOTICE; i++)
        if (state.leases[i].pointer || state.leases[i].releasing || state.leases[i].send_inflight || state.leases[i].faults) return 0;
    return 1;
}
static int same_lease(unsigned int index, const struct native_cp_state_publication_lease *l, uint64_t cycle) {
    const struct native_cp_state_publication_lease *current = &state.leases[index];
    return state.lease_cycle_id[index] == cycle && current->role == l->role && current->bytes == l->bytes &&
        current->wire_fnv1a64 == l->wire_fnv1a64 && current->pointer == l->pointer;
}

static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int p = atomic_load(&owner_pid); return p && p != getpid(); }
static unsigned int u16(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8; }
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static int mode_wire_matches(void) {
    return state.mode_selector <= 1 && u32(wires[MODE_REQUEST] + 8) == state.mode_selector;
}
static void put16(unsigned char *p, unsigned int v) { p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); }
static void put32(unsigned char *p, uint32_t v) {
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(v >> (8u * i));
}
static int span(const void *p, size_t n) { return p && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlaps(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static uint64_t hash(const void *p, size_t n) {
    const unsigned char *b = p; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; i++) { h ^= b[i]; h *= UINT64_C(1099511628211); }
    return h;
}
static void fault(unsigned int index) {
    state.faults = state.leases[index].faults = 1;
    state.start_complete = state.mode1_complete = state.mode0_complete = state.mode_complete = state.business_ready = 0;
    state.phase = FUNCTIONAL_CAMERA_CONTROL_FAULT;
}
static void refresh(void) {
    struct native_cp_state_publication_lease *s = state.leases;
    for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++) {
        s[i].consumed = s[i].role != REQUEST_ROLE && s[i].queued && s[i].freed &&
            !s[i].faults && !s[i].send_inflight && !s[i].releasing && !s[i].send_rc && !s[i].free_rc &&
            (s[i].role == ACK_ROLE ? s[i].free_tid == s[i].sender_tid :
             s[i].received && s[i].free_tid == s[i].receiver_tid);
    }
    state.start_complete = state.start_requests && s[START_REQUEST].freed &&
        s[START_ACK].consumed && !state.faults && !state.busy;
    const int ack_only = state.mode_selector == 1 && state.mode1_ack_only;
    state.mode_complete = state.mode_cycle_id && s[MODE_REQUEST].freed &&
        s[MODE_ACK].consumed && (ack_only || s[FULL_NOTICE].consumed) && !state.faults && !state.busy;
    if (state.mode_cycle_id) {
        if (state.mode_selector == 1) state.mode1_complete = state.mode_complete;
        else state.mode0_complete = state.mode_complete;
    }
    if (state.mode_complete && completed_cycle != state.mode_cycle_id) {
        completed_cycle = state.mode_cycle_id;
        if (state.mode_selector == 1) {
            state.mode1_cycles_completed++;
            if (ack_only) state.mode1_ack_only_completed++;
        } else state.mode0_cycles_completed++;
    }
    if (s[FULL_NOTICE].consumed && !state.notification_ap_consumed) state.full_notifications_consumed++;
    state.notification_queued = s[FULL_NOTICE].queued;
    state.notification_received = s[FULL_NOTICE].received;
    state.notification_ap_consumed = s[FULL_NOTICE].consumed;
    if (state.faults) return;
    if (s[FULL_NOTICE].consumed) state.shadow_generation = state.published_generation;
    if (ack_only && state.mode_complete) state.phase = FUNCTIONAL_CAMERA_CONTROL_MODE_ACK_CONSUMED;
    else if (s[FULL_NOTICE].consumed) {
        state.phase = FUNCTIONAL_CAMERA_CONTROL_NOTICE_CONSUMED;
    } else if (s[FULL_NOTICE].received) state.phase = FUNCTIONAL_CAMERA_CONTROL_NOTICE_RECEIVED;
    else if (s[FULL_NOTICE].queued) state.phase = FUNCTIONAL_CAMERA_CONTROL_NOTICE_QUEUED;
    else if (state.publication_copied) state.phase = FUNCTIONAL_CAMERA_CONTROL_PUBLICATION_COPIED;
    else if (state.start_complete) state.phase = FUNCTIONAL_CAMERA_CONTROL_START_CONSUMED;
    else if (s[START_ACK].queued) state.phase = FUNCTIONAL_CAMERA_CONTROL_START_QUEUED;
}
int native_functional_camera_control_owner_init(void) {
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&owner_pid, &expected, pid);
    if (atomic_load(&owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&mutex);
    if (state.initialized) { pthread_mutex_unlock(&mutex); return -EALREADY; }
    state.owner_pid = pid; state.initialized = state.functional_model = 1;
    state.phase = FUNCTIONAL_CAMERA_CONTROL_UNKNOWN;
    pthread_mutex_unlock(&mutex); return 0;
}
void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *out) {
    if (!out) return;
    if (inherited()) {
        *out = (struct native_functional_camera_control_snapshot){.owner_pid = atomic_load(&owner_pid),
            .faults = 1, .functional_model = 1, .phase = FUNCTIONAL_CAMERA_CONTROL_FAULT};
        return;
    }
    pthread_mutex_lock(&mutex); *out = state; pthread_mutex_unlock(&mutex);
}
static void record(void (*logger)(const char *, const char *), const char *event, unsigned int index) {
    if (!logger) return;
    struct native_functional_camera_control_snapshot s;
    native_functional_camera_control_snapshot(&s);
    const struct native_cp_state_publication_lease l = s.leases[index];
    char tag[96], text[2560];
    snprintf(tag, sizeof tag, "FUNCTIONAL_CAMERA_CONTROL_%s ", event);
    snprintf(text, sizeof text,
        "pid=%d tid=%ld phase=%u index=%u role=%u bytes=%u destination=%#x source=%#x "
        "wire_fnv1a=%016llx queued=%u received=%u freed=%u consumed=%u send_inflight=%u releasing=%u lease_cycle_id=%llu sender_tid=%ld receiver_tid=%ld "
        "free_tid=%ld allocate_rc=%d send_rc=%d free_rc=%d retained=%p faults=%u busy=%u guard=%u "
        "probe_run_id=%llu init_run_id=%llu state_run_id=%llu bridge_rc=%d probe_rc=%d "
        "native_source=%#x native_destination=%#x native_command=%#x native_bytes=%u native_fnv1a=%016llx "
        "model_initialized=%u probe_attempts=%u probe_successes=%u probe_refusals=%u "
        "model_instance=%llu config_generation=%llu rendered=%llu frame_generation=%llu "
        "start_complete=%u mode1_complete=%u defined_mask=%u full_layout_copied=%u model_defined=%u "
        "defined_blocks=%u projected_blocks=%u zero_policy_blocks=%u publication_copied=%u "
        "xsync_defined=%u xsync_source_fps=%u xsync_word=%u xsync_half=%u xsync_source_generation=%llu "
        "published_generation=%u shadow_generation=%u notification_queued=%u notification_received=%u notification_AP_consumed=%u "
        "cycle_id=%llu cycle_generation=%u ack_only=%u mode1_requests=%u cycles_completed=%u "
        "ack_only_requests=%u ack_only_completed=%u full_queued=%u full_consumed=%u notification_mode=%u "
        "mode_selector=%u mode_complete=%u mode0_requests=%u mode0_complete=%u mode0_cycles_completed=%u "
        "mode1_cycle_id=%llu mode1_cycle_generation=%u selector_policy=opaque-state-refresh-v1 "
        "business_ready=%u functional_model=1 original_CP=0 physical_ASIC_verified=0 "
        "fixed_optics_policy=integrated-noneLIF LIF_tuple=0,0,0 cache4=0 "
        "original_getters_executed=0 original_source_proof=0 EE=0 frame=0 capture=0",
        s.owner_pid, tid(), s.phase, index, l.role, l.bytes, l.destination, l.source,
        (unsigned long long)l.wire_fnv1a64, l.queued, l.received, l.freed, l.consumed,
        l.send_inflight, l.releasing, (unsigned long long)s.lease_cycle_id[index],
        l.sender_tid, l.receiver_tid, l.free_tid, l.allocate_rc, l.send_rc, l.free_rc, l.pointer,
        s.faults, s.busy, s.guard_held, (unsigned long long)s.probe_run_id,
        (unsigned long long)s.init_run_id, (unsigned long long)s.state_run_id, s.bridge_rc, s.probe_rc,
        s.last_origin.source, s.last_origin.destination, s.last_origin.command, s.last_origin.bytes,
        (unsigned long long)s.last_origin.wire_fnv1a64, s.model_initialized, s.probe_attempts, s.probe_successes, s.probe_refusals,
        (unsigned long long)s.model_instance, (unsigned long long)s.config_generation,
        (unsigned long long)s.rendered, (unsigned long long)s.frame_generation,
        s.start_complete, s.mode1_complete, s.start_defined_mask, s.full_layout_copied, s.full_model_defined,
        s.defined_blocks, s.projected_blocks, s.zero_policy_blocks, s.publication_copied,
        s.xsync_defined, s.xsync_source_fps, s.xsync_word, s.xsync_half, (unsigned long long)s.xsync_source_generation,
        s.published_generation, s.shadow_generation, s.notification_queued, s.notification_received, s.notification_ap_consumed,
        (unsigned long long)s.mode_cycle_id, s.mode_cycle_generation, s.mode_selector == 1 ? s.mode1_ack_only : 0u, s.mode1_requests, s.mode1_cycles_completed,
        s.mode1_ack_only_requests, s.mode1_ack_only_completed, s.full_notifications_queued, s.full_notifications_consumed,
        s.notification_mode, s.mode_selector, s.mode_complete, s.mode0_requests, s.mode0_complete, s.mode0_cycles_completed,
        (unsigned long long)s.mode1_cycle_id, s.mode1_cycle_generation, s.business_ready);
    logger(tag, text);
}
static int release_owned(unsigned int destination, void *pointer, int (*release)(unsigned int, void *),
                         void (*logger)(const char *, const char *), int *result, int internal, uint64_t event_cycle) {
    if (!pointer || !release || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&mutex);
    unsigned int index;
    for (index = 0; index < FUNCTIONAL_CAMERA_CONTROL_LEASES; index++)
        if (state.leases[index].pointer == pointer) break;
    if (index == FUNCTIONAL_CAMERA_CONTROL_LEASES) { pthread_mutex_unlock(&mutex); return 0; }
    if (!internal && index >= MODE_REQUEST &&
        (event_cycle ? event_cycle != state.lease_cycle_id[index] : state.lease_cycle_id[index] > 1)) {
        pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1;
    }
    const struct native_cp_state_publication_lease l = state.leases[index];
    const uint64_t cycle = state.lease_cycle_id[index];
    unsigned char expected[CP_STATE_SNAPSHOT_BYTES]; memcpy(expected, wires[index], l.bytes);
    const struct full_imaging_io io = transport;
    const long current = tid();
    int permitted = destination == l.destination && !l.releasing &&
        (internal || (l.role == ACK_ROLE && started[index] && current == l.sender_tid) ||
         (l.role == NOTICE_ROLE && started[index] && l.received && current == l.receiver_tid));
    if (!permitted) { fault(index); pthread_mutex_unlock(&mutex); *result = -EPROTO; return 1; }
    state.leases[index].releasing = 1; pthread_mutex_unlock(&mutex);
    int valid = internal == CLEANUP_FREE || (io.size && io.source &&
        io.size(pointer) == l.bytes && io.source(pointer) == l.source && !memcmp(pointer, expected, l.bytes));
    const int rc = valid ? release(destination, pointer) : -EPROTO;
    pthread_mutex_lock(&mutex);
    if (!same_lease(index, &l, cycle) || !state.leases[index].releasing) {
        fault(index); pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1;
    }
    state.leases[index].releasing = 0; state.leases[index].free_rc = rc;
    if (rc) fault(index);
    else {
        state.leases[index].pointer = NULL; state.leases[index].freed = 1;
        state.leases[index].free_tid = current;
    }
    refresh(); pthread_mutex_unlock(&mutex);
    record(logger, internal ? "OWNED_FREE" : "AP_FREE", index); *result = rc; return 1;
}
int native_functional_camera_control_release(unsigned int destination, void *pointer,
    int (*release)(unsigned int, void *), void (*logger)(const char *, const char *), int *result) {
    return release_owned(destination, pointer, release, logger, result, PUBLIC_FREE, 0);
}
int native_functional_camera_control_release_cycle(unsigned int destination, void *pointer,
    int (*release)(unsigned int, void *), void (*logger)(const char *, const char *), int *result, uint64_t event_cycle) {
    return release_owned(destination, pointer, release, logger, result, PUBLIC_FREE, event_cycle);
}
static void record_receive(const struct full_imaging_io *io, unsigned int index,
    const struct native_cp_state_publication_lease *lease, uint64_t cycle, uint64_t event_cycle,
    unsigned int destination, void *pointer, unsigned int source, unsigned int bytes,
    unsigned int was_started, const char *reason, int result, unsigned int envelope_checked,
    unsigned int actual_source, unsigned int actual_bytes, uint64_t actual_hash, const char *ack_wire) {
    if (!io->record) return;
    char text[1100];
    snprintf(text, sizeof text,
        "pid=%d tid=%ld index=%u role=%u result=%d reason=%s pointer=%p destination=%#x source=%#x bytes=%u "
        "event_cycle=%llu lease_cycle=%llu started=%u send_inflight=%u queued=%u received_before=%u releasing_before=%u "
        "sender_tid=%ld receiver_tid_before=%ld expected_destination=%#x expected_source=%#x expected_bytes=%u "
        "expected_fnv1a=%016llx envelope_checked=%u actual_source=%#x actual_bytes=%u wire_checked=%u wire_fnv1a=%016llx ack_wire=%s "
        "functional_model=1 original_CP=0 physical_ASIC_verified=0 capture=0",
        getpid(), tid(), index, lease->role, result, reason, pointer, destination, source, bytes,
        (unsigned long long)event_cycle, (unsigned long long)cycle, was_started, lease->send_inflight,
        lease->queued, lease->received, lease->releasing, lease->sender_tid, lease->receiver_tid,
        lease->destination, lease->source, lease->bytes, (unsigned long long)lease->wire_fnv1a64,
        envelope_checked, actual_source, actual_bytes, envelope_checked && actual_bytes == lease->bytes,
        (unsigned long long)actual_hash, ack_wire);
    io->record("FUNCTIONAL_CAMERA_CONTROL_RECEIVE ", text);
}
int native_functional_camera_control_observe_receive_cycle(unsigned int destination, void *pointer,
                                                           unsigned int source, unsigned int bytes, uint64_t event_cycle) {
    if (inherited()) return -EXDEV;
    pthread_mutex_lock(&mutex);
    unsigned int index;
    for(index=0;index<FUNCTIONAL_CAMERA_CONTROL_LEASES;index++)
        if(state.leases[index].pointer==pointer &&
           (state.leases[index].role==ACK_ROLE || state.leases[index].role==NOTICE_ROLE))break;
    if(!pointer || index==FUNCTIONAL_CAMERA_CONTROL_LEASES){pthread_mutex_unlock(&mutex);return 0;}
    const struct native_cp_state_publication_lease l=state.leases[index];
    const uint64_t cycle=state.lease_cycle_id[index];
    if(event_cycle ? event_cycle!=cycle : cycle>1){pthread_mutex_unlock(&mutex);return -ESTALE;}
    unsigned char expected[CP_STATE_SNAPSHOT_BYTES];memcpy(expected,wires[index],l.bytes);
    const struct full_imaging_io io=transport;
    const unsigned int was_started=started[index];
    /* The original imaging worker receives ACKs, then gives the pointer to the
     * requester's future. Only that original sender may perform the ACK free. */
    const char *reason = !was_started ? "not_started" : destination!=l.destination ? "destination" :
        source!=l.source ? "source" : bytes!=l.bytes ? "bytes" : l.releasing ? "releasing" : l.received ? "duplicate" : NULL;
    if(reason){
        fault(index);pthread_mutex_unlock(&mutex);
        record_receive(&io,index,&l,cycle,event_cycle,destination,pointer,source,bytes,was_started,reason,-EPROTO,0,0,0,0,"unchecked");
        return -EPROTO;
    }
    state.leases[index].releasing=1;pthread_mutex_unlock(&mutex);
    unsigned int actual_bytes=0,actual_source=0,envelope_checked=io.size && io.source;
    uint64_t actual_hash=0;char ack_wire[33]="unchecked";
    if(envelope_checked){actual_bytes=io.size(pointer);actual_source=io.source(pointer);}
    if(envelope_checked && actual_bytes==l.bytes){
        actual_hash=hash(pointer,l.bytes);
        if(l.role==ACK_ROLE){
            static const char hex[]="0123456789abcdef";const unsigned char *p=pointer;
            for(unsigned int i=0;i<l.bytes;i++){ack_wire[2*i]=hex[p[i]>>4];ack_wire[2*i+1]=hex[p[i]&15];}
            ack_wire[2*l.bytes]=0;
        }
    }
    reason = !envelope_checked ? "missing_accessor" : actual_bytes!=bytes ? "envelope_bytes" :
        actual_source!=source ? "envelope_source" : memcmp(pointer,expected,bytes) ? "wire" : NULL;
    int valid=!reason;
    pthread_mutex_lock(&mutex);
    if(!same_lease(index,&l,cycle) || !state.leases[index].releasing){
        fault(index);pthread_mutex_unlock(&mutex);return -ESTALE;
    }
    state.leases[index].releasing=0;
    if(valid && !state.faults){
        state.leases[index].received=1;state.leases[index].receiver_tid=tid();
    }else{fault(index);if(!reason)reason="existing_fault";valid=0;}
    refresh();pthread_mutex_unlock(&mutex);
    record_receive(&io,index,&l,cycle,event_cycle,destination,pointer,source,bytes,was_started,
        reason?reason:"accepted",valid?1:-EPROTO,envelope_checked,actual_source,actual_bytes,actual_hash,ack_wire);
    return valid?1:-EPROTO;
}
int native_functional_camera_control_observe_receive(unsigned int destination, void *pointer,
                                                     unsigned int source, unsigned int bytes) {
    return native_functional_camera_control_observe_receive_cycle(destination, pointer, source, bytes, 0);
}
static void finish(const struct native_cp_state_publication_guard *guard) {
    pthread_mutex_lock(&mutex); const unsigned int held = state.guard_held;
    state.guard_held = 0; pthread_mutex_unlock(&mutex);
    if (held) guard->release();
    pthread_mutex_lock(&mutex); state.busy = 0; refresh(); pthread_mutex_unlock(&mutex);
}
static int validate_state(const unsigned char *p, const struct fcam_bridge_result *r,
                          const struct native_functional_camera_control_snapshot *before, int start) {
    if (r->used != FCAM_STATE_BYTES || r->required != FCAM_STATE_BYTES || r->result_token) return -EPROTO;
    if (u32(p + FCAM_S_ABI) != FCAM_ABI_VERSION) return -EPROTO;
    if (u32(p + FCAM_S_CAPS) != FCAM_CAPABILITIES) return -ENOTSUP;
    uint64_t instance = u64(p + FCAM_S_INSTANCE), generation = u64(p + FCAM_S_GENERATION);
    if (!instance || instance != r->model_instance) return -ESTALE;
    if (!generation || generation > UINT32_MAX) return -EOVERFLOW;
    if (!u32(p + FCAM_S_WIDTH) || u32(p + FCAM_S_WIDTH) > FCAM_MAX_STILL_WIDTH ||
        !u32(p + FCAM_S_HEIGHT) || u32(p + FCAM_S_HEIGHT) > FCAM_MAX_STILL_HEIGHT ||
        !u32(p + FCAM_S_FPS) || u32(p + FCAM_S_FPS) > 120 ||
        !u32(p + FCAM_S_QUALITY) || u32(p + FCAM_S_QUALITY) > 100 || !u32(p + FCAM_S_ISO) ||
        !u64(p + FCAM_S_SHUTTER) || (u64(p + FCAM_S_FOCUS) != UINT64_MAX && u64(p + FCAM_S_FOCUS) < 100000))
        return -ERANGE;
    unsigned int aperture = u32(p + FCAM_S_FNUMBER);
    if (aperture != 400 && aperture != 800 && aperture != 1600) return -ERANGE;
    if (!u64(p + FCAM_S_RENDERED) || !u64(p + FCAM_S_FRAME_GENERATION)) return -ENODATA;
    if (u64(p + FCAM_S_CONSUMED) > u64(p + FCAM_S_RENDERED) ||
        u64(p + FCAM_S_JPEG_ENCODED) > u64(p + FCAM_S_CONSUMED) ||
        u64(p + FCAM_S_VIDEO_ENCODED) > u64(p + FCAM_S_CONSUMED) || u64(p + 120)) return -EPROTO;
    if (u32(p + FCAM_S_STREAM_STATE) == 3) return -EIO;
    if (u32(p + FCAM_S_PENDING_RESULTS) || u32(p + FCAM_S_STREAM_STATE)) return -EBUSY;
    if (!start) {
        if (instance != before->model_instance || generation < before->config_generation ||
            generation < before->shadow_generation) return -ESTALE;
        if (generation == before->config_generation && memcmp(p, before->model_state, FCAM_S_INSTANCE)) return -ESTALE;
        static const unsigned char counters[] = {FCAM_S_RENDERED, FCAM_S_CONSUMED, FCAM_S_JPEG_ENCODED,
            FCAM_S_VIDEO_ENCODED, FCAM_S_RESULT_READ, FCAM_S_FRAME_GENERATION};
        for (size_t i = 0; i < sizeof counters; i++)
            if (u64(p + counters[i]) < u64(before->model_state + counters[i])) return -ESTALE;
    }
    return 0;
}
static int probe(const struct fcam_native_origin *origin, int start, void (*logger)(const char *, const char *)) {
    struct { unsigned char before[16], bytes[FCAM_STATE_BYTES], after[16]; } output;
    memset(&output, 0xa5, sizeof output); memset(output.bytes, 0, sizeof output.bytes);
    struct fcam_bridge_result result = {0};
    struct native_functional_camera_control_snapshot before;
    pthread_mutex_lock(&mutex);
    if (state.probe_run_id == UINT64_MAX || state.probe_attempts == UINT_MAX ||
        state.probe_successes == UINT_MAX || state.probe_refusals == UINT_MAX) {
        state.probe_rc = -EOVERFLOW; pthread_mutex_unlock(&mutex); return -EOVERFLOW;
    }
    state.probe_attempts++; state.probe_run_id++; state.last_origin = *origin;
    state.phase = start ? FUNCTIONAL_CAMERA_CONTROL_PROBING : FUNCTIONAL_CAMERA_CONTROL_STATE_PROBING;
    before = state; pthread_mutex_unlock(&mutex);
    int bridge_rc = fcam_bridge_call(origin, start ? FCAM_OP_INIT : FCAM_OP_STATE,
        NULL, 0, output.bytes, sizeof output.bytes, &result);
    int rc = bridge_rc > 0 ? -EPROTO : bridge_rc, overflow = 0;
    for (size_t i = 0; i < sizeof output.before; i++)
        if (output.before[i] != 0xa5 || output.after[i] != 0xa5) { rc = -EOVERFLOW; overflow = 1; }
    if (!rc) rc = validate_state(output.bytes, &result, &before, start);
    pthread_mutex_lock(&mutex); state.bridge_rc = bridge_rc; state.probe_rc = rc;
    if (rc) {
        state.probe_refusals++; state.business_ready = 0;
        if (overflow) fault(start ? START_REQUEST : MODE_REQUEST);
        if (!state.faults) state.phase = state.model_initialized ? FUNCTIONAL_CAMERA_CONTROL_INITIALIZED : FUNCTIONAL_CAMERA_CONTROL_UNKNOWN;
    } else {
        state.probe_successes++;
        if (start) { state.init_run_id = state.probe_run_id; state.model_initialized = 1; }
        else state.state_run_id = state.probe_run_id;
        memcpy(state.model_state, output.bytes, sizeof output.bytes);
        state.model_instance = u64(output.bytes + FCAM_S_INSTANCE);
        state.config_generation = u64(output.bytes + FCAM_S_GENERATION);
        state.rendered = u64(output.bytes + FCAM_S_RENDERED);
        state.frame_generation = u64(output.bytes + FCAM_S_FRAME_GENERATION);
        state.business_ready = state.model_initialized && !state.faults;
        if (!state.faults) state.phase = FUNCTIONAL_CAMERA_CONTROL_INITIALIZED;
    }
    pthread_mutex_unlock(&mutex); record(logger, rc ? "PROBE_REFUSED" : "PROBE", start ? START_REQUEST : MODE_REQUEST);
    return rc;
}
struct xsync_capability { unsigned int source_fps, word, half; uint64_t source_generation; };
static int xsync_project(const struct native_functional_camera_control_snapshot *s, struct xsync_capability *out) {
    /* One current model frame is the virtual CMOS readout/sync budget; exposure is independent. */
    static const unsigned char canonical_fps[] = {1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 45, 50, 60, 80, 90, 100};
    const unsigned int fps = u32(s->model_state + FCAM_S_FPS);
    if (!s->model_initialized || !s->business_ready || s->faults) return -ENODATA;
    if (!s->model_instance || s->model_instance != u64(s->model_state + FCAM_S_INSTANCE) ||
        !s->config_generation || s->config_generation > UINT32_MAX ||
        s->config_generation != u64(s->model_state + FCAM_S_GENERATION)) return -ESTALE;
    for (size_t i = 0; i < sizeof canonical_fps; i++) if (fps == canonical_fps[i]) {
        *out = (struct xsync_capability){fps, fps, 1, s->config_generation}; return 0;
    }
    return -ENOTSUP;
}
static int full_snapshot(struct cp_state_snapshot *out, struct xsync_capability *xsync) {
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    struct xsync_capability capability;
    int rc = xsync_project(&s, &capability);
    if (rc) return rc;
    unsigned char bytes[CP_STATE_SNAPSHOT_BYTES] = {0}, known[CP_STATE_SNAPSHOT_BYTES];
    struct cp_state_snapshot_input fragments[CP_FULL_STATE_SNAPSHOT_BLOCKS];
    const struct cp_state_snapshot_generation generation = {CP_STATE_SNAPSHOT_PUBLISHED_BYTES,
        (uint32_t)s.config_generation, (uint32_t)s.config_generation, s.shadow_generation};
    memset(known, 1, sizeof known);
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        const struct cp_full_state_snapshot_block b = cp_full_state_snapshot_blocks[i];
        unsigned char *p = bytes + b.offset; p[0] = 6; put16(p + 2, b.command);
        /* Every remaining byte belongs to this explicit software model policy. */
        if (b.command == 0x2012) {
            static const unsigned char constant[12] = {6, 0, 0x12, 0x20, 0, 0, 0, 0, 0, 0, 0x77, 0};
            memcpy(p, constant, sizeof constant);
        } else if (b.command == 0x201b) put16(p + 8, u32(s.model_state + FCAM_S_FNUMBER));
        else if (b.command == 0x20a6) {
            put32(p + 8, capability.word); put16(p + 12, capability.half);
        } else if (b.command == 0x2044) {
            static const char name[] = "Virtual functional fixed optics";
            p[8] = 1; /* Declared integrated virtual optics; no serial E-mount/LIF bus. */
            put32(p + 0x18, 10); put32(p + 0x20, 10);
            put32(p + 0x24, 0x40); put32(p + 0x28, 10);
            put32(p + 0x2c, 0x160); put32(p + 0x30, 10);
            memcpy(p + 0x34, name, sizeof name);
        }
        fragments[i] = (struct cp_state_snapshot_input){p, known + b.offset, b.bytes, b.bytes, generation};
    }
    struct cp_state_snapshot assembled;
    rc = cp_full_state_snapshot_assemble(fragments, CP_FULL_STATE_SNAPSHOT_BLOCKS, &generation, &assembled);
    if (rc) return rc;
    const unsigned char *p = assembled.bytes + 0x664;
    if (p[0] != 6 || p[1] || u16(p + 2) != 0x20a6 || u32(p + 4) ||
        u32(p + 8) != capability.word || u16(p + 12) != capability.half || u16(p + 14) ||
        assembled.generation.published_generation != capability.source_generation) return -EPROTO;
    for (size_t i = 0; i < 16; i++) if (assembled.known[0x664 + i] != 1) return -ENODATA;
    *out = assembled; *xsync = capability; return 0;
}
static int allocate_message(unsigned int index, unsigned int bytes, const struct full_imaging_io *io) {
    void *p = NULL; int rc = io->allocate(FUNCTIONAL_CAMERA_CONTROL_AP, &p, bytes, 1);
    int valid = !rc && span(p, bytes), alias = 0;
    pthread_mutex_lock(&mutex);
    if (p) for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++) {
        const struct native_cp_state_publication_lease *other = &state.leases[i];
        if (!other->pointer) continue;
        if (!span(other->pointer, other->bytes)) valid = 0;
        else if (span(p, bytes) && overlaps(p, bytes, other->pointer, other->bytes)) { valid = 0; alias = 1; }
    }
    struct native_cp_state_publication_lease *l = &state.leases[index];
    l->role = index == FULL_NOTICE ? NOTICE_ROLE : ACK_ROLE; l->bytes = bytes;
    l->destination = FUNCTIONAL_CAMERA_CONTROL_AP; l->source = FUNCTIONAL_CAMERA_CONTROL_SID;
    l->sender_tid = tid(); l->allocate_rc = rc; l->wire_fnv1a64 = hash(wires[index], bytes);
    if (p && !alias) l->pointer = p;
    if (!valid) fault(index);
    pthread_mutex_unlock(&mutex);
    if (valid) {
        valid = io->size(p) == bytes;
        if (valid) {
            memcpy(p, wires[index], bytes); io->set_source(p, FUNCTIONAL_CAMERA_CONTROL_SID);
            valid = io->size(p) == bytes && io->source(p) == FUNCTIONAL_CAMERA_CONTROL_SID && !memcmp(p, wires[index], bytes);
        }
        if (!valid) { pthread_mutex_lock(&mutex); fault(index); pthread_mutex_unlock(&mutex); }
    }
    return valid ? 0 : rc ? rc : -EPROTO;
}
static int send_message(unsigned int index, const struct full_imaging_io *io) {
    pthread_mutex_lock(&mutex); const struct native_cp_state_publication_lease l = state.leases[index];
    const uint64_t cycle = state.lease_cycle_id[index];
    unsigned char expected[CP_STATE_SNAPSHOT_BYTES]; memcpy(expected, wires[index], l.bytes);
    int valid = l.pointer && !state.faults && (index < MODE_REQUEST || mode_wire_matches());
    pthread_mutex_unlock(&mutex);
    if (valid) valid = io->size(l.pointer) == l.bytes && io->source(l.pointer) == l.source && !memcmp(l.pointer, expected, l.bytes);
    pthread_mutex_lock(&mutex);
    valid = valid && same_lease(index, &l, cycle) && !state.leases[index].releasing && !started[index] &&
        (index < MODE_REQUEST || mode_wire_matches());
    if (!valid) fault(index);
    valid = valid && !state.faults;
    if (valid) { started[index] = 1; state.leases[index].send_inflight = 1; }
    pthread_mutex_unlock(&mutex); if (!valid) return -EPROTO;
    const int rc = io->send(l.destination, l.pointer);
    pthread_mutex_lock(&mutex);
    if (state.lease_cycle_id[index] != cycle || !state.leases[index].send_inflight ||
        (state.leases[index].pointer != l.pointer && !state.leases[index].freed)) {
        fault(index); pthread_mutex_unlock(&mutex); return -ESTALE;
    }
    state.leases[index].send_inflight = 0; state.leases[index].send_rc = rc;
    if (rc) fault(index);
    else {
        state.leases[index].queued = 1;
        if (index == FULL_NOTICE) state.full_notifications_queued++;
    }
    refresh(); pthread_mutex_unlock(&mutex); record(io->record, "SENT", index); return rc;
}
static void cleanup_messages(unsigned int first, const struct full_imaging_io *io) {
    for (unsigned int i = first; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++) {
        pthread_mutex_lock(&mutex); const struct native_cp_state_publication_lease l = state.leases[i];
        pthread_mutex_unlock(&mutex);
        if (l.pointer && !l.queued && !l.releasing) {
            int rc; release_owned(l.destination, l.pointer, io->release, io->record, &rc, CLEANUP_FREE, 0);
        }
    }
}
int native_functional_camera_control_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_CAMERA_CONTROL_SID || !request || !io || !io->size || !result) return 0;
    if (inherited() || inspecting) { *result = -EXDEV; return 1; }
    inspecting = 1; unsigned int bytes = io->size(request); inspecting = 0;
    if (bytes < 4 || !span(request, bytes)) return 0;
    const unsigned char *p = request; const unsigned int command = u16(p + 2);
    int start = p[0] == 0 && (command == 0x3003 || command == 0x3000);
    int mode = p[0] == 5 && command == 0x4073;
    if (!start && !mode) return 0;
    unsigned int selector = 1;
    if (mode && bytes == 12) {
        selector = u32(p + 8);
        if (selector > 1) return 0;
        if (!selector) {
            pthread_mutex_lock(&mutex);
            const int started_here = state.start_requests || state.busy || state.mode_cycle_id;
            pthread_mutex_unlock(&mutex);
            if (!started_here) return 0; /* The first boot selector0 belongs to the finite native owner. */
        }
    }
    *result = FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    if (bytes != (start ? 24u : 12u) || !io->source || !io->allocate || !io->set_source || !io->send || !io->release ||
        !guard || !guard->reserve || !guard->release || !guard->predecessor_ready) return 1;
    for (unsigned int i = 8; start && i < 24; i++) if (p[i]) return 1;
    inspecting = 1; unsigned int caller = io->source(request); inspecting = 0;
    if (caller != FUNCTIONAL_CAMERA_CONTROL_AP) return 1;
    unsigned char saved[24]; memcpy(saved, request, bytes);
    pthread_mutex_lock(&mutex);
    int blocked_busy = state.busy || (mode && !mode_retired());
    int ready = state.initialized && !blocked_busy && !state.faults &&
        (start ? !state.start_requests : state.start_complete && state.model_initialized &&
         (selector || (state.mode1_complete && state.mode1_cycles_completed && state.notification_ap_consumed)));
    if (ready && mode && (state.mode_cycle_id == UINT64_MAX ||
        state.full_notifications_queued == UINT_MAX || state.full_notifications_consumed == UINT_MAX ||
        (selector ? state.mode1_requests == UINT_MAX || state.mode1_cycles_completed == UINT_MAX ||
         state.mode1_ack_only_requests == UINT_MAX || state.mode1_ack_only_completed == UINT_MAX :
         state.mode0_requests == UINT_MAX || state.mode0_cycles_completed == UINT_MAX))) {
        pthread_mutex_unlock(&mutex); *result = -EOVERFLOW; return 1;
    }
    if (ready) state.busy = 1;
    pthread_mutex_unlock(&mutex);
    if (!ready) { if (blocked_busy) *result = -EBUSY; return 1; }
    int rc = guard->reserve();
    if (rc) { finish(guard); *result = rc; return 1; }
    pthread_mutex_lock(&mutex); state.guard_held = 1; pthread_mutex_unlock(&mutex);
    if (guard->predecessor_ready() != 1) { finish(guard); return 1; }
    const struct fcam_native_origin origin = {caller, destination, command, bytes, hash(saved, bytes)};
    rc = probe(&origin, start, io->record);
    struct cp_state_snapshot full = {0};
    struct xsync_capability xsync = {0};
    int publish = mode;
    if (!rc && mode) {
        pthread_mutex_lock(&mutex);
        publish = state.config_generation != state.shadow_generation;
        if (!selector && !publish) rc = -ESTALE;
        else if (!publish && (!state.notification_ap_consumed || !state.leases[FULL_NOTICE].consumed ||
            state.published_generation != state.shadow_generation)) rc = -ESTALE;
        pthread_mutex_unlock(&mutex);
        if (!rc && publish) rc = full_snapshot(&full, &xsync);
    }
    if (rc || guard->predecessor_ready() != 1 || io->size(request) != bytes ||
        io->source(request) != caller || memcmp(request, saved, bytes)) {
        if (!rc) rc = FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
        pthread_mutex_lock(&mutex); state.probe_rc = rc; pthread_mutex_unlock(&mutex);
        record(io->record, "REFUSED", start ? START_REQUEST : MODE_REQUEST);
        finish(guard); *result = rc; return 1;
    }
    unsigned char reply[16] = {1, 0, 0, 0, 0, 0, 0, 0, 0, 0xf0, 0, 0, 0, 0, 0, 0};
    put16(reply + 2, command); memcpy(reply + 4, saved + 4, 4);
    const unsigned int req = start ? START_REQUEST : MODE_REQUEST, ack = req + 1;
    pthread_mutex_lock(&mutex);
    ready = state.busy && state.guard_held && !state.faults && state.model_initialized && state.business_ready &&
        (start ? !state.start_requests : state.start_complete && mode_retired() &&
         (selector || (state.mode1_complete && state.mode1_cycles_completed && state.notification_ap_consumed)) &&
         (publish ? full.generation.published_generation == state.config_generation &&
                    state.config_generation > state.shadow_generation :
          state.config_generation == state.shadow_generation && state.notification_ap_consumed));
    if (!ready) { pthread_mutex_unlock(&mutex); finish(guard); *result = -ESTALE; return 1; }
    if (mode) {
        state.mode_cycle_id++; state.mode_cycle_generation = (unsigned int)state.config_generation;
        state.mode_selector = selector; state.mode_complete = 0;
        if (selector) {
            state.mode1_cycle_id = state.mode_cycle_id; state.mode1_cycle_generation = state.mode_cycle_generation;
            state.mode1_ack_only = !publish; state.mode1_complete = 0;
        } else state.mode0_complete = 0;
        for (unsigned int i = MODE_REQUEST; i <= (publish ? FULL_NOTICE : MODE_ACK); i++) {
            memset(&state.leases[i], 0, sizeof state.leases[i]);
            memset(wires[i], 0, sizeof wires[i]); started[i] = 0;
            state.lease_cycle_id[i] = state.mode_cycle_id;
        }
        if (publish) state.notification_queued = state.notification_received = state.notification_ap_consumed = 0;
    }
    transport = *io;
    state.leases[req] = (struct native_cp_state_publication_lease){.role = REQUEST_ROLE, .bytes = bytes,
        .destination = destination, .source = caller, .sender_tid = tid(), .pointer = request,
        .wire_fnv1a64 = origin.wire_fnv1a64};
    memcpy(wires[req], saved, bytes); memcpy(wires[ack], reply, start ? 16u : 12u);
    if (publish) {
        memcpy(wires[FULL_NOTICE], full.bytes, CP_STATE_SNAPSHOT_BYTES);
        state.full_layout_copied = state.full_model_defined = state.publication_copied = 1;
        state.defined_blocks = CP_FULL_STATE_SNAPSHOT_BLOCKS; state.projected_blocks = 3;
        state.zero_policy_blocks = CP_FULL_STATE_SNAPSHOT_BLOCKS - 4;
        state.xsync_defined = 1; state.xsync_source_fps = xsync.source_fps;
        state.xsync_word = xsync.word; state.xsync_half = xsync.half;
        state.xsync_source_generation = xsync.source_generation;
        memset(state.block_defined, 1, sizeof state.block_defined);
        for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++)
            state.block_projected[i] = cp_full_state_snapshot_blocks[i].command == 0x201b ||
                cp_full_state_snapshot_blocks[i].command == 0x2044 || cp_full_state_snapshot_blocks[i].command == 0x20a6;
        state.published_generation = full.generation.published_generation;
        state.phase = FUNCTIONAL_CAMERA_CONTROL_PUBLICATION_COPIED;
    }
    pthread_mutex_unlock(&mutex);
    rc = allocate_message(ack, start ? 16u : 12u, io);
    if (!rc && publish) rc = allocate_message(FULL_NOTICE, CP_STATE_SNAPSHOT_BYTES, io);
    if (rc) {
        pthread_mutex_lock(&mutex); state.leases[req].pointer = NULL; pthread_mutex_unlock(&mutex);
        cleanup_messages(ack, io); finish(guard); *result = rc; return 1;
    }
    pthread_mutex_lock(&mutex);
    if (start) { state.start_requests = 1; state.start_defined_mask = 15; }
    else if (selector) {
        state.mode1_requests++; state.notification_mode = 1;
        if (!publish) state.mode1_ack_only_requests++;
    } else state.mode0_requests++;
    pthread_mutex_unlock(&mutex);
    rc = send_message(ack, io);
    if (!rc && publish) rc = send_message(FULL_NOTICE, io);
    if (!rc) { int freed; release_owned(destination, request, io->release, io->record, &freed, REQUEST_FREE, 0); }
    else cleanup_messages(ack, io);
    finish(guard); record(io->record, rc ? "FAULT" : "COMMIT", ack); *result = 0; return 1;
}
/* Post-initialization software bank; never writes the original control owner. */
_Static_assert(FCAM_CP_PARAMETER_BANK_BYTES == CP_PARAMETER_BATCH_BYTES, "complete parameter input");
_Static_assert(FCAM_CP_PARAMETER_BANK_SLOTS == CP_PARAMETER_BATCH_SLOTS, "fixed slot table");
_Static_assert(FCAM_CP_PARAMETER_BANK_STATE_OFFSET + FCAM_STATE_BYTES == FCAM_CP_PARAMETER_BANK_READBACK_OFFSET,
    "complete bank State128");
_Static_assert(FCAM_CP_PARAMETER_BANK_READBACK_OFFSET + FCAM_CP_PARAMETER_BANK_BYTES == FCAM_CP_PARAMETER_BANK_RESULT_BYTES,
    "complete bank readback");
static pthread_mutex_t parameter_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int parameter_owner_pid;
static _Thread_local unsigned int parameter_inspecting;
static struct native_functional_camera_parameter_snapshot parameter_state;
static struct full_imaging_io parameter_transport;
static int parameter_inherited(void) {
    int pid = atomic_load(&parameter_owner_pid);
    return (pid && pid != getpid()) || inherited();
}
int native_functional_camera_parameter_owner_init(void) {
    if (parameter_inherited()) return -EXDEV;
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&parameter_owner_pid, &expected, pid);
    if (atomic_load(&parameter_owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&parameter_mutex);
    if (parameter_state.initialized) { pthread_mutex_unlock(&parameter_mutex); return -EALREADY; }
    parameter_state.owner_pid = pid; parameter_state.initialized = 1;
    pthread_mutex_unlock(&parameter_mutex); return 0;
}
void native_functional_camera_parameter_snapshot(struct native_functional_camera_parameter_snapshot *out) {
    if (!out) return;
    if (parameter_inherited()) {
        *out = (struct native_functional_camera_parameter_snapshot){.owner_pid = atomic_load(&parameter_owner_pid), .faults = 1};
        return;
    }
    pthread_mutex_lock(&parameter_mutex); *out = parameter_state; pthread_mutex_unlock(&parameter_mutex);
}
static void parameter_record(void (*logger)(const char *, const char *), const char *event, const char *kind) {
    if (!logger) return;
    struct native_functional_camera_parameter_snapshot s; native_functional_camera_parameter_snapshot(&s);
    char text[2200];
    snprintf(text, sizeof text,
        "event=%s pid=%d tid=%ld transaction=%llu sender_tid=%ld source=%#x destination=%#x command=%#x bytes=%u "
        "native_fnv1a=%016llx cookie=%#x busy=%u guard=%u faults=%u error=%d model_rc=%d model_called=%u "
        "model_committed=%u verified=%u owned=%u retained=%p releasing=%u request_freed=%u free_rc=%d free_tid=%ld "
        "commits=%llu released=%llu model_instance=%llu bank_generation=%llu before_config_generation=%llu config_generation=%llu fps=%u "
        "before_used=%lu before_required=%lu before_token=%llu before_instance=%llu bank_used=%lu bank_required=%lu bank_token=%llu bank_instance=%llu "
        "after_used=%lu after_required=%lu after_token=%llu after_instance=%llu policy=%s oneway=1 ACK_sent=0 notification_sent=0 "
        "functional_model=1 original_CP=0 physical_ASIC_verified=0 capture_verified=0",
        event, s.owner_pid, tid(), (unsigned long long)s.transaction, s.sender_tid,
        s.origin.source, s.origin.destination, s.origin.command, s.origin.bytes,
        (unsigned long long)s.origin.wire_fnv1a64, u32(s.request + 4), s.busy, s.guard_held, s.faults,
        s.error, s.model_rc, s.model_called, s.model_committed, s.verified, s.owned, s.retained_request, s.releasing,
        s.request_freed, s.free_rc, s.free_tid, (unsigned long long)s.commits, (unsigned long long)s.released,
        (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation,
        (unsigned long long)s.before_config_generation, (unsigned long long)s.config_generation, s.fps,
        (unsigned long)s.before_result.used, (unsigned long)s.before_result.required, (unsigned long long)s.before_result.result_token,
        (unsigned long long)s.before_result.model_instance,
        (unsigned long)s.bank_result.used, (unsigned long)s.bank_result.required, (unsigned long long)s.bank_result.result_token,
        (unsigned long long)s.bank_result.model_instance,
        (unsigned long)s.after_result.used, (unsigned long)s.after_result.required, (unsigned long long)s.after_result.result_token,
        (unsigned long long)s.after_result.model_instance, FUNCTIONAL_CAMERA_PARAMETER_POLICY);
    logger("FUNCTIONAL_CP_PARAMETER_BANK_EVENT ", text);
    const unsigned char *raw = NULL; size_t bytes = 0;
    if (kind && !strcmp(kind, "request")) { raw = s.request; bytes = sizeof s.request; }
    else if (kind && !strcmp(kind, "before_state")) { raw = s.before_state; bytes = sizeof s.before_state; }
    else if (kind && !strcmp(kind, "receipt")) { raw = s.receipt; bytes = sizeof s.receipt; }
    else if (kind && !strcmp(kind, "after_state")) { raw = s.after_state; bytes = sizeof s.after_state; }
    for (size_t offset = 0; offset < bytes; offset += 128) {
        size_t n = bytes - offset; if (n > 128) n = 128;
        char hex[257]; static const char digits[] = "0123456789abcdef";
        for (size_t i = 0; i < n; i++) { hex[2*i] = digits[raw[offset+i] >> 4]; hex[2*i+1] = digits[raw[offset+i] & 15]; }
        hex[2*n] = 0;
        snprintf(text, sizeof text,
            "pid=%d tid=%ld transaction=%llu kind=%s total=%lu offset=%lu bytes=%lu raw=%s native_fnv1a=%016llx "
            "model_instance=%llu bank_generation=%llu capture_verified=0",
            s.owner_pid, tid(), (unsigned long long)s.transaction, kind, (unsigned long)bytes, (unsigned long)offset,
            (unsigned long)n, hex, (unsigned long long)s.origin.wire_fnv1a64,
            (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation);
        logger("FUNCTIONAL_CP_PARAMETER_BANK_BYTES ", text);
    }
}
static int parameter_control_ready(const struct native_functional_camera_control_snapshot *s) {
    if (s->owner_pid != getpid() || !s->initialized || !s->functional_model || !s->model_initialized ||
        !s->business_ready || !s->model_instance || !s->start_complete || !s->mode1_complete ||
        !s->mode1_cycles_completed || !s->mode_complete || !s->notification_ap_consumed ||
        s->busy || s->guard_held || s->faults || s->leases[MODE_REQUEST].sender_tid != tid()) return 0;
    for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++)
        if (s->leases[i].pointer || !s->leases[i].freed || s->leases[i].releasing ||
            s->leases[i].send_inflight || s->leases[i].faults || s->leases[i].free_rc || s->leases[i].send_rc) return 0;
    return s->leases[START_ACK].consumed && s->leases[MODE_ACK].consumed && s->leases[FULL_NOTICE].consumed;
}
static int parameter_request_matches(const struct full_imaging_io *io, void *request, const unsigned char *expected) {
    parameter_inspecting = 1;
    unsigned int bytes = io->size(request), source = io->source(request);
    parameter_inspecting = 0;
    return bytes == FCAM_CP_PARAMETER_BANK_BYTES && source == FUNCTIONAL_CAMERA_CONTROL_AP &&
        !memcmp(request, expected, FCAM_CP_PARAMETER_BANK_BYTES);
}
static int parameter_context_matches(const struct native_functional_camera_control_snapshot *before,
    const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard,
    void *request, const unsigned char *input) {
    if (guard->predecessor_ready() != 1) return FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    struct native_functional_camera_control_snapshot current = {0}; native_functional_camera_control_snapshot(&current);
    if (!parameter_control_ready(&current) || memcmp(before, &current, sizeof current)) return -ESTALE;
    if (!parameter_request_matches(io, request, parameter_state.request) ||
        memcmp(input, parameter_state.request, FCAM_CP_PARAMETER_BANK_BYTES)) return -EPROTO;
    return 0;
}
static int parameter_validate_live(const unsigned char *p, const struct fcam_bridge_result *r, uint64_t instance) {
    if (r->used != FCAM_STATE_BYTES || r->required != FCAM_STATE_BYTES || r->result_token ||
        u32(p + FCAM_S_ABI) != FCAM_ABI_VERSION || u32(p + FCAM_S_CAPS) != FCAM_CAPABILITIES ||
        !instance || r->model_instance != instance || u64(p + FCAM_S_INSTANCE) != instance || u64(p + 120)) return -EPROTO;
    if (!u64(p + FCAM_S_GENERATION)) return -ESTALE;
    if (!u32(p + FCAM_S_WIDTH) || u32(p + FCAM_S_WIDTH) > FCAM_MAX_STILL_WIDTH ||
        !u32(p + FCAM_S_HEIGHT) || u32(p + FCAM_S_HEIGHT) > FCAM_MAX_STILL_HEIGHT ||
        !u32(p + FCAM_S_FPS) || u32(p + FCAM_S_FPS) > 120 ||
        !u32(p + FCAM_S_QUALITY) || u32(p + FCAM_S_QUALITY) > 100 || !u32(p + FCAM_S_ISO) ||
        !u64(p + FCAM_S_SHUTTER) || (u64(p + FCAM_S_FOCUS) != UINT64_MAX && u64(p + FCAM_S_FOCUS) < 100000)) return -ERANGE;
    unsigned int aperture = u32(p + FCAM_S_FNUMBER);
    if (aperture != 400 && aperture != 800 && aperture != 1600) return -ERANGE;
    if (!u64(p + FCAM_S_RENDERED) || !u64(p + FCAM_S_FRAME_GENERATION) ||
        u64(p + FCAM_S_CONSUMED) > u64(p + FCAM_S_RENDERED) ||
        u64(p + FCAM_S_JPEG_ENCODED) > u64(p + FCAM_S_CONSUMED) ||
        u64(p + FCAM_S_VIDEO_ENCODED) > u64(p + FCAM_S_CONSUMED)) return -EPROTO;
    if (u32(p + FCAM_S_STREAM_STATE) == 3) return -EIO;
    if (u32(p + FCAM_S_PENDING_RESULTS) || u32(p + FCAM_S_STREAM_STATE)) return -EBUSY;
    return 0;
}
static int parameter_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    unsigned char *output, size_t bytes, struct fcam_bridge_result *result) {
    unsigned char guarded[16 + FCAM_CP_PARAMETER_BANK_RESULT_BYTES + 16];
    memset(guarded, 0xa5, sizeof guarded); memset(guarded + 16, 0, bytes);
    struct fcam_native_origin actual_origin = *origin;
    int rc = fcam_bridge_call(&actual_origin, opcode, input, input_bytes, guarded + 16, bytes, result);
    memcpy(output, guarded + 16, bytes);
    pthread_mutex_lock(&parameter_mutex); parameter_state.model_rc = rc; pthread_mutex_unlock(&parameter_mutex);
    if (memcmp(&actual_origin, origin, sizeof actual_origin)) return -EPROTO;
    for (size_t i = 0; i < sizeof guarded; i++)
        if ((i < 16 || i >= 16 + bytes) && guarded[i] != 0xa5) return -EOVERFLOW;
    return rc > 0 ? -EPROTO : rc;
}
static int parameter_validate_receipt(uint64_t last_bank_generation) {
    const unsigned char *p = parameter_state.receipt, *before = parameter_state.before_state;
    unsigned char expected[FCAM_STATE_BYTES]; memcpy(expected, before, sizeof expected);
    const uint64_t generation = u64(before + FCAM_S_GENERATION);
    const uint32_t fps = u32(parameter_state.request + 0x86c);
    if (generation == UINT64_MAX || last_bank_generation == UINT64_MAX) return -EOVERFLOW;
    put32(expected + FCAM_S_FPS, fps);
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)((generation + 1) >> (8*i));
    const struct fcam_bridge_result *r = &parameter_state.bank_result;
    if (r->used != FCAM_CP_PARAMETER_BANK_RESULT_BYTES || r->required != FCAM_CP_PARAMETER_BANK_RESULT_BYTES || r->result_token ||
        r->model_instance != parameter_state.model_instance || u32(p) != 1 || u32(p+4) != FCAM_CP_PARAMETER_BANK_RESULT_BYTES ||
        u64(p+8) != parameter_state.model_instance || u64(p+16) != last_bank_generation + 1 ||
        u64(p+24) != generation || u64(p+32) != generation + 1 || u64(p+40) != parameter_state.origin.wire_fnv1a64 ||
        u32(p+48) != fps || u32(p+52) != FCAM_CP_PARAMETER_BANK_SLOTS || u32(p+56) != FCAM_CP_PARAMETER_BANK_BYTES || u32(p+60) ||
        memcmp(p + FCAM_CP_PARAMETER_BANK_STATE_OFFSET, expected, sizeof expected) ||
        memcmp(p + FCAM_CP_PARAMETER_BANK_READBACK_OFFSET, parameter_state.request, FCAM_CP_PARAMETER_BANK_BYTES)) return -EPROTO;
    return 0;
}
int native_functional_camera_parameter_release(unsigned int destination, void *request, int (*release)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t transaction) {
    if (!request || !release || !result) return 0;
    if (parameter_inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&parameter_mutex);
    if (parameter_state.owned && parameter_state.request_freed && parameter_state.request_pointer == request && transaction) {
        pthread_mutex_unlock(&parameter_mutex); *result = -ESTALE; return 1;
    }
    if (!parameter_state.owned || parameter_state.retained_request != request) { pthread_mutex_unlock(&parameter_mutex); return 0; }
    if (!transaction || transaction != parameter_state.transaction) { pthread_mutex_unlock(&parameter_mutex); *result = -ESTALE; return 1; }
    if (parameter_state.releasing) { pthread_mutex_unlock(&parameter_mutex); *result = -EBUSY; return 1; }
    if (destination != FUNCTIONAL_CAMERA_CONTROL_SID || parameter_state.sender_tid != tid()) {
        pthread_mutex_unlock(&parameter_mutex); *result = -EPERM; return 1;
    }
    const struct full_imaging_io io = parameter_transport;
    parameter_state.releasing = 1; pthread_mutex_unlock(&parameter_mutex);
    int rc = parameter_request_matches(&io, request, parameter_state.request) ? release(destination, request) : -EPROTO;
    pthread_mutex_lock(&parameter_mutex);
    if (parameter_state.transaction != transaction || parameter_state.retained_request != request || !parameter_state.releasing) rc = -ESTALE;
    parameter_state.releasing = 0; parameter_state.free_rc = rc;
    if (rc) parameter_state.faults = 1;
    else {
        parameter_state.retained_request = NULL; parameter_state.request_freed = 1;
        parameter_state.free_tid = tid(); parameter_state.released++;
    }
    pthread_mutex_unlock(&parameter_mutex);
    parameter_record(logger, "OWNED_FREE", NULL); *result = rc; return 1;
}
static void parameter_finish(const struct native_cp_state_publication_guard *guard,
    void (*logger)(const char *, const char *), int rc, int latch_fault) {
    pthread_mutex_lock(&parameter_mutex);
    parameter_state.error = rc;
    if (latch_fault) parameter_state.faults = 1;
    unsigned int held = parameter_state.guard_held; parameter_state.guard_held = 0;
    pthread_mutex_unlock(&parameter_mutex);
    if (held) guard->release();
    parameter_record(logger, rc ? "REFUSED" : "COMMIT", NULL);
    pthread_mutex_lock(&parameter_mutex); parameter_state.busy = 0; pthread_mutex_unlock(&parameter_mutex);
}
int native_functional_camera_parameter_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_CAMERA_CONTROL_SID || !request || !io || !io->size || !result) return 0;
    if (parameter_inherited()) { *result = -EXDEV; return 1; }
    if (parameter_inspecting) { *result = -EBUSY; return 1; }
    parameter_inspecting = 1; unsigned int bytes = io->size(request); parameter_inspecting = 0;
    if (bytes < 4 || !span(request, bytes)) return 0;
    const unsigned char *p = request;
    if (p[0] != 5 || u16(p+2) != 0x4063) return 0;
    struct native_functional_camera_control_snapshot control = {0}; native_functional_camera_control_snapshot(&control);
    if (!control.start_requests) return 0;
    *result = FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    if (bytes != FCAM_CP_PARAMETER_BANK_BYTES) { *result = -EMSGSIZE; return 1; }
    if (!io->source || !io->release || !guard || !guard->reserve || !guard->release || !guard->predecessor_ready) return 1;
    parameter_inspecting = 1; unsigned int caller = io->source(request); parameter_inspecting = 0;
    if (caller != FUNCTIONAL_CAMERA_CONTROL_AP) { *result = -EPERM; return 1; }
    if (!parameter_control_ready(&control)) return 1;
    struct cp_parameter_batch validated;
    int rc = cp_parameter_batch_init(&validated, true);
    if (!rc) rc = cp_parameter_batch_stage(&validated, caller, destination, request, bytes);
    if (rc != CP_PARAMETER_BATCH_STAGED) { *result = rc; return 1; }
    const uint32_t fps = u32(validated.bytes + 0x86c);
    if (!fps || fps > 120) { *result = -ERANGE; return 1; }
    pthread_mutex_lock(&parameter_mutex);
    if (parameter_state.busy || parameter_state.releasing || parameter_state.retained_request) {
        pthread_mutex_unlock(&parameter_mutex); *result = -EBUSY; return 1;
    }
    if (!parameter_state.initialized || parameter_state.owner_pid != getpid() || parameter_state.faults ||
        (parameter_state.sender_tid && parameter_state.sender_tid != tid())) { pthread_mutex_unlock(&parameter_mutex); return 1; }
    if (parameter_state.transaction == UINT64_MAX || parameter_state.commits == UINT64_MAX ||
        parameter_state.released == UINT64_MAX || parameter_state.last_bank_generation == UINT64_MAX) {
        pthread_mutex_unlock(&parameter_mutex); *result = -EOVERFLOW; return 1;
    }
    const uint64_t transaction = parameter_state.transaction + 1, commits = parameter_state.commits;
    const uint64_t released = parameter_state.released, last_bank = parameter_state.last_bank_generation;
    parameter_state = (struct native_functional_camera_parameter_snapshot){.owner_pid = getpid(), .initialized = 1,
        .busy = 1, .sender_tid = tid(), .transaction = transaction, .commits = commits, .released = released,
        .last_bank_generation = last_bank, .model_instance = control.model_instance, .fps = fps, .request_pointer = request,
        .origin = {caller, destination, 0x4063, bytes, hash(validated.bytes, bytes)}};
    memcpy(parameter_state.request, validated.bytes, bytes);
    pthread_mutex_unlock(&parameter_mutex);
    parameter_record(io->record, "BEGIN", "request");
    rc = guard->reserve();
    if (rc) { parameter_finish(guard, io->record, rc, 0); *result = rc; return 1; }
    pthread_mutex_lock(&parameter_mutex); parameter_state.guard_held = 1; pthread_mutex_unlock(&parameter_mutex);
    unsigned char live[FCAM_STATE_BYTES], receipt[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
    struct fcam_bridge_result bridge_result = {0};
    rc = parameter_context_matches(&control, io, guard, request, validated.bytes);
    if (!rc) {
        rc = parameter_call(&parameter_state.origin, FCAM_OP_STATE, NULL, 0,
            live, sizeof live, &bridge_result);
        if (!rc) rc = parameter_validate_live(live, &bridge_result, control.model_instance);
        pthread_mutex_lock(&parameter_mutex);
        memcpy(parameter_state.before_state, live, sizeof live); parameter_state.before_result = bridge_result;
        parameter_state.before_config_generation = u64(live + FCAM_S_GENERATION);
        pthread_mutex_unlock(&parameter_mutex);
        parameter_record(io->record, "BEFORE", "before_state");
    }
    if (!rc && parameter_state.before_config_generation == UINT64_MAX) rc = -EOVERFLOW;
    if (!rc) rc = parameter_context_matches(&control, io, guard, request, validated.bytes);
    if (rc) { parameter_finish(guard, io->record, rc, rc == -EPROTO || rc == -EOVERFLOW); *result = rc; return 1; }
    pthread_mutex_lock(&parameter_mutex); parameter_state.model_called = 1; pthread_mutex_unlock(&parameter_mutex);
    bridge_result = (struct fcam_bridge_result){0};
    rc = parameter_call(&parameter_state.origin, FCAM_OP_CP_PARAMETER_BANK, validated.bytes, bytes,
        receipt, sizeof receipt, &bridge_result);
    pthread_mutex_lock(&parameter_mutex);
    memcpy(parameter_state.receipt, receipt, sizeof receipt); parameter_state.bank_result = bridge_result;
    parameter_state.model_committed = parameter_state.model_rc == 0;
    pthread_mutex_unlock(&parameter_mutex);
    if (!rc) rc = parameter_validate_receipt(last_bank);
    pthread_mutex_lock(&parameter_mutex);
    parameter_state.bank_generation = u64(parameter_state.receipt + 16);
    parameter_state.config_generation = u64(parameter_state.receipt + 32);
    pthread_mutex_unlock(&parameter_mutex);
    parameter_record(io->record, "MODEL", "receipt");
    if (!rc) rc = parameter_context_matches(&control, io, guard, request, validated.bytes);
    if (!rc) {
        bridge_result = (struct fcam_bridge_result){0};
        rc = parameter_call(&parameter_state.origin, FCAM_OP_STATE, NULL, 0,
            live, sizeof live, &bridge_result);
        if (!rc) rc = parameter_validate_live(live, &bridge_result, control.model_instance);
        if (!rc && memcmp(live, parameter_state.receipt + FCAM_CP_PARAMETER_BANK_STATE_OFFSET, sizeof live)) rc = -ESTALE;
        pthread_mutex_lock(&parameter_mutex);
        memcpy(parameter_state.after_state, live, sizeof live); parameter_state.after_result = bridge_result;
        pthread_mutex_unlock(&parameter_mutex);
        parameter_record(io->record, "AFTER", "after_state");
    }
    if (!rc) rc = parameter_context_matches(&control, io, guard, request, validated.bytes);
    if (rc) { parameter_finish(guard, io->record, rc, 1); *result = rc; return 1; }
    pthread_mutex_lock(&parameter_mutex);
    parameter_state.verified = parameter_state.owned = 1; parameter_state.retained_request = request;
    parameter_state.last_bank_generation = parameter_state.bank_generation; parameter_state.commits++;
    parameter_transport = *io;
    pthread_mutex_unlock(&parameter_mutex);
    parameter_record(io->record, "VERIFIED", NULL);
    int freed = -EPROTO;
    native_functional_camera_parameter_release(destination, request, io->release, io->record, &freed, transaction);
    parameter_finish(guard, io->record, freed, freed != 0); *result = 0; return 1;
}
/* Independent post-bank mode0; the strict diagnostic and old owners are read-only. */
_Static_assert(FCAM_OP_CP_CRANK_CONTROL == 21u, "finite crank opcode");
_Static_assert(FUNCTIONAL_CAMERA_CRANK_RESULT_BYTES == 208u, "complete crank receipt");
static pthread_mutex_t crank_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int crank_owner_pid;
static _Thread_local unsigned int crank_inspecting, crank_request_free_allowed;
static struct native_functional_camera_crank_snapshot crank_state;
static struct full_imaging_io crank_transport;
static uint64_t crank_completed_transaction;
static int crank_inherited(void) {
    int pid = atomic_load(&crank_owner_pid);
    return (pid && pid != getpid()) || parameter_inherited();
}
static void crank_refresh(void) {
    crank_state.reply_consumed = crank_state.reply_queued && crank_state.reply_received && crank_state.reply_freed &&
        !crank_state.send_inflight && !crank_state.reply_releasing && !crank_state.reply_inspecting &&
        !crank_state.send_rc && !crank_state.reply_free_rc && !crank_state.receive_rc && !crank_state.faults &&
        crank_state.receiver_tid > 0 && crank_state.reply_free_tid == crank_state.sender_tid;
    crank_state.complete = crank_state.owned && crank_state.verified && crank_state.request_freed &&
        crank_state.reply_consumed && !crank_state.busy && !crank_state.guard_held && !crank_state.faults &&
        !crank_state.retained_request && !crank_state.retained_reply && !crank_state.request_releasing;
    if (crank_state.complete && crank_completed_transaction != crank_state.transaction) {
        crank_completed_transaction = crank_state.transaction; crank_state.completions++;
    }
}
static void crank_fault(int rc) {
    crank_state.faults = 1;
    if (!crank_state.error) crank_state.error = rc;
    crank_refresh();
}
int native_functional_camera_crank_owner_init(void) {
    if (crank_inherited()) return -EXDEV;
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&crank_owner_pid, &expected, pid);
    if (atomic_load(&crank_owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&crank_mutex);
    if (crank_state.initialized) { pthread_mutex_unlock(&crank_mutex); return -EALREADY; }
    crank_state.owner_pid = pid; crank_state.initialized = 1;
    pthread_mutex_unlock(&crank_mutex); return 0;
}
void native_functional_camera_crank_snapshot(struct native_functional_camera_crank_snapshot *out) {
    if (!out) return;
    if (crank_inherited()) {
        *out = (struct native_functional_camera_crank_snapshot){.owner_pid = atomic_load(&crank_owner_pid), .faults = 1};
        return;
    }
    pthread_mutex_lock(&crank_mutex); *out = crank_state; pthread_mutex_unlock(&crank_mutex);
}
static void crank_record(void (*logger)(const char *, const char *), const char *event, const char *kind,
    const struct native_functional_camera_crank_snapshot *observed) {
    if (!logger) return;
    struct native_functional_camera_crank_snapshot s;
    if (observed) s = *observed; else native_functional_camera_crank_snapshot(&s);
    char text[4096];
    snprintf(text, sizeof text,
        "event=%s pid=%d tid=%ld transaction=%llu sender_tid=%ld receiver_tid=%ld source=%#x destination=%#x command=%#x bytes=%u "
        "native_fnv1a=%016llx cookie=%#x busy=%u guard=%u faults=%u error=%d before_rc=%d model_rc=%d after_rc=%d model_called=%u "
        "model_committed=%u verified=%u owned=%u complete=%u retained_request=%p retained_reply=%p request_pointer=%p reply_pointer=%p allocation_pointer=%p "
        "request_releasing=%u request_freed=%u request_free_rc=%d request_free_tid=%ld reply_releasing=%u reply_inspecting=%u "
        "reply_allocated=%u reply_valid=%u reply_alias=%u allocate_rc=%d send_started=%u send_inflight=%u send_rc=%d ACK_sent=%u "
        "reply_received=%u receive_rc=%d reply_freed=%u reply_cleanup_freed=%u reply_free_rc=%d reply_free_tid=%ld reply_consumed=%u "
        "requests=%llu commits=%llu verified_commits=%llu completions=%llu model_instance=%llu bank_generation=%llu crank_generation=%llu "
        "last_bank_generation=%llu last_crank_generation=%llu before_config_generation=%llu config_generation=%llu frame_generation=%llu mode=%u fps=%u "
        "bank_transaction=%llu bank_commits=%llu bank_released=%llu bank_source=%#x bank_destination=%#x bank_command=%#x bank_bytes=%u bank_native_fnv1a=%016llx "
        "receipt_fnv1a=%016llx reply_fnv1a=%016llx before_used=%lu before_required=%lu before_token=%llu before_instance=%llu "
        "crank_used=%lu crank_required=%lu crank_token=%llu crank_instance=%llu after_used=%lu after_required=%lu after_token=%llu after_instance=%llu "
        "policy=%s functional_model=1 original_CP=0 physical_ASIC_verified=0 EE=0 frame=0 capture=0 capture_verified=0",
        event, s.owner_pid, tid(), (unsigned long long)s.transaction, s.sender_tid, s.receiver_tid,
        s.origin.source, s.origin.destination, s.origin.command, s.origin.bytes, (unsigned long long)s.origin.wire_fnv1a64,
        u32(s.request + 4), s.busy, s.guard_held, s.faults, s.error, s.before_rc, s.model_rc, s.after_rc, s.model_called,
        s.model_committed, s.verified, s.owned, s.complete, s.retained_request, s.retained_reply,
        s.request_pointer, s.reply_pointer, s.allocation_pointer, s.request_releasing, s.request_freed, s.request_free_rc,
        s.request_free_tid, s.reply_releasing, s.reply_inspecting, s.reply_allocated, s.reply_valid, s.reply_alias, s.allocate_rc,
        s.reply_send_started, s.send_inflight, s.send_rc, s.reply_queued, s.reply_received, s.receive_rc,
        s.reply_freed, s.reply_cleanup_freed, s.reply_free_rc, s.reply_free_tid, s.reply_consumed,
        (unsigned long long)s.requests, (unsigned long long)s.commits, (unsigned long long)s.verified_commits,
        (unsigned long long)s.completions, (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation,
        (unsigned long long)s.crank_generation, (unsigned long long)s.last_bank_generation, (unsigned long long)s.last_crank_generation,
        (unsigned long long)s.before_config_generation, (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation,
        s.mode, s.fps, (unsigned long long)s.bank_transaction, (unsigned long long)s.bank_commits, (unsigned long long)s.bank_released,
        s.bank_origin.source, s.bank_origin.destination, s.bank_origin.command, s.bank_origin.bytes,
        (unsigned long long)s.bank_origin.wire_fnv1a64, (unsigned long long)s.receipt_fnv1a64, (unsigned long long)s.reply_fnv1a64,
        (unsigned long)s.before_result.used, (unsigned long)s.before_result.required, (unsigned long long)s.before_result.result_token,
        (unsigned long long)s.before_result.model_instance, (unsigned long)s.crank_result.used, (unsigned long)s.crank_result.required,
        (unsigned long long)s.crank_result.result_token, (unsigned long long)s.crank_result.model_instance,
        (unsigned long)s.after_result.used, (unsigned long)s.after_result.required, (unsigned long long)s.after_result.result_token,
        (unsigned long long)s.after_result.model_instance, FUNCTIONAL_CAMERA_CRANK_POLICY);
    logger("FUNCTIONAL_CP_CRANK_CONTROL_EVENT ", text);
    const unsigned char *raw = NULL; size_t bytes = 0;
    if (kind && !strcmp(kind, "request")) { raw = s.request; bytes = sizeof s.request; }
    else if (kind && !strcmp(kind, "before_state")) { raw = s.before_state; bytes = sizeof s.before_state; }
    else if (kind && !strcmp(kind, "receipt")) { raw = s.receipt; bytes = sizeof s.receipt; }
    else if (kind && !strcmp(kind, "after_state")) { raw = s.after_state; bytes = sizeof s.after_state; }
    else if (kind && !strcmp(kind, "reply")) { raw = s.reply; bytes = sizeof s.reply; }
    for (size_t offset = 0; offset < bytes; offset += 128) {
        size_t n = bytes - offset; if (n > 128) n = 128;
        char hex[257]; static const char digits[] = "0123456789abcdef";
        for (size_t i = 0; i < n; i++) { hex[2*i] = digits[raw[offset+i] >> 4]; hex[2*i+1] = digits[raw[offset+i] & 15]; }
        hex[2*n] = 0;
        snprintf(text, sizeof text,
            "event=%s pid=%d tid=%ld transaction=%llu kind=%s total=%lu offset=%lu bytes=%lu raw=%s native_fnv1a=%016llx content_fnv1a=%016llx "
            "model_instance=%llu bank_generation=%llu crank_generation=%llu functional_model=1 original_CP=0 physical_ASIC_verified=0 capture_verified=0",
            event, s.owner_pid, tid(), (unsigned long long)s.transaction, kind, (unsigned long)bytes, (unsigned long)offset,
            (unsigned long)n, hex, (unsigned long long)s.origin.wire_fnv1a64, (unsigned long long)hash(raw, bytes),
            (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation, (unsigned long long)s.crank_generation);
        logger("FUNCTIONAL_CP_CRANK_CONTROL_BYTES ", text);
    }
}
static int crank_control_ready(const struct native_functional_camera_control_snapshot *s) {
    if (s->owner_pid != getpid() || !s->initialized || !s->functional_model || !s->model_initialized ||
        !s->business_ready || !s->model_instance || !s->start_complete || !s->mode1_complete ||
        !s->mode1_cycles_completed || !s->mode_complete || !s->notification_ap_consumed || s->busy || s->guard_held || s->faults) return 0;
    for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++)
        if (s->leases[i].pointer || !s->leases[i].freed || s->leases[i].releasing || s->leases[i].send_inflight ||
            s->leases[i].faults || s->leases[i].free_rc || s->leases[i].send_rc) return 0;
    return s->leases[START_ACK].consumed && s->leases[MODE_ACK].consumed && s->leases[FULL_NOTICE].consumed;
}
static int crank_bank_ready(const struct native_functional_camera_parameter_snapshot *s, uint64_t instance) {
    if (s->owner_pid != getpid() || !s->initialized || s->busy || s->guard_held || s->faults || s->error || s->free_rc ||
        !s->model_called || !s->model_committed || !s->verified || !s->owned || !s->request_freed || s->releasing || s->retained_request ||
        !s->request_pointer || !s->sender_tid || s->free_tid != s->sender_tid ||
        !s->transaction || !s->commits || s->released != s->commits || !s->bank_generation || s->last_bank_generation != s->bank_generation ||
        s->model_instance != instance || s->origin.source != FUNCTIONAL_CAMERA_CONTROL_AP ||
        s->origin.destination != FUNCTIONAL_CAMERA_CONTROL_SID || s->origin.command != 0x4063 || s->origin.bytes != sizeof s->request ||
        s->origin.wire_fnv1a64 != hash(s->request, sizeof s->request) ||
        parameter_validate_live(s->before_state, &s->before_result, instance) ||
        parameter_validate_live(s->after_state, &s->after_result, instance)) return 0;
    const unsigned char *p = s->receipt;
    unsigned char expected[FCAM_STATE_BYTES]; memcpy(expected, s->before_state, sizeof expected);
    if (s->before_config_generation == UINT64_MAX || u64(expected + FCAM_S_GENERATION) != s->before_config_generation ||
        s->config_generation != s->before_config_generation + 1 || s->fps != u32(s->request + FCAM_CP_PARAMETER_FPS_AT)) return 0;
    put32(expected + FCAM_S_FPS, s->fps);
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(s->config_generation >> (8*i));
    return s->bank_result.used == sizeof s->receipt && s->bank_result.required == sizeof s->receipt && !s->bank_result.result_token &&
        s->bank_result.model_instance == instance && u32(p) == 1 && u32(p+4) == sizeof s->receipt && u64(p+8) == instance &&
        u64(p+16) == s->bank_generation && u64(p+24) == s->before_config_generation && u64(p+32) == s->config_generation &&
        u64(p+40) == s->origin.wire_fnv1a64 && u32(p+48) == s->fps && u32(p+52) == FCAM_CP_PARAMETER_BANK_SLOTS &&
        u32(p+56) == sizeof s->request && !u32(p+60) && !memcmp(p+64, expected, sizeof expected) &&
        !memcmp(p+64, s->after_state, sizeof s->after_state) && !memcmp(p+192, s->request, sizeof s->request);
}
static int crank_wire_matches(const struct full_imaging_io *io, void *pointer, unsigned int source, const unsigned char expected[12]) {
    crank_inspecting++;
    unsigned int bytes = io->size(pointer), actual_source = io->source(pointer);
    crank_inspecting--;
    return bytes == 12 && actual_source == source && !memcmp(pointer, expected, 12);
}
static int crank_context_matches(const struct native_functional_camera_control_snapshot *control,
    const struct native_functional_camera_parameter_snapshot *bank, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, void *request, const unsigned char expected[12]) {
    if (guard->predecessor_ready() != 1) return FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    struct native_functional_camera_control_snapshot c; native_functional_camera_control_snapshot(&c);
    struct native_functional_camera_parameter_snapshot b; native_functional_camera_parameter_snapshot(&b);
    if (!crank_control_ready(&c) || !crank_bank_ready(&b, c.model_instance) ||
        memcmp(control, &c, sizeof c) || memcmp(bank, &b, sizeof b)) return -ESTALE;
    return crank_wire_matches(io, request, FUNCTIONAL_CAMERA_CONTROL_AP, expected) ? 0 : -EPROTO;
}
static int crank_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    unsigned char *output, size_t bytes, struct fcam_bridge_result *result, int *actual_rc) {
    unsigned char guarded[16 + FUNCTIONAL_CAMERA_CRANK_RESULT_BYTES + 16];
    memset(guarded, 0xa5, sizeof guarded); memset(guarded + 16, 0, bytes);
    struct fcam_native_origin actual_origin = *origin;
    int rc = fcam_bridge_call(&actual_origin, opcode, input, input_bytes, guarded + 16, bytes, result);
    *actual_rc = rc; memcpy(output, guarded + 16, bytes);
    if (memcmp(origin, &actual_origin, sizeof actual_origin)) return -EPROTO;
    for (size_t i = 0; i < sizeof guarded; i++)
        if ((i < 16 || i >= 16 + bytes) && guarded[i] != 0xa5) return -EOVERFLOW;
    return rc > 0 ? -EPROTO : rc;
}
static int crank_validate_receipt(const struct native_functional_camera_crank_snapshot *s, uint64_t last_crank) {
    const unsigned char *p = s->receipt;
    const struct fcam_bridge_result *r = &s->crank_result;
    if (s->before_config_generation == UINT64_MAX || last_crank == UINT64_MAX) return -EOVERFLOW;
    unsigned char expected[FCAM_STATE_BYTES]; memcpy(expected, s->before_state, sizeof expected);
    uint64_t generation = s->before_config_generation + 1;
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(generation >> (8*i));
    if (r->used != sizeof s->receipt || r->required != sizeof s->receipt || r->result_token || r->model_instance != s->model_instance ||
        u32(p) != 1 || u32(p+4) != sizeof s->receipt || u64(p+8) != s->model_instance || u64(p+16) != last_crank + 1 ||
        u64(p+24) != s->bank_generation || u64(p+32) != s->before_config_generation || u64(p+40) != generation ||
        u64(p+48) != s->origin.wire_fnv1a64 || u32(p+56) || u32(p+60) != s->fps ||
        memcmp(p+64, expected, sizeof expected) || memcmp(p+192, s->request, sizeof s->request) || u32(p+204)) return -EPROTO;
    return 0;
}
int native_functional_camera_crank_release(unsigned int destination, void *pointer, int (*release)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t transaction,
    const struct native_functional_camera_crank_receive *event) {
    if (!pointer || !result || (!event && !release)) return 0;
    if (crank_inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&crank_mutex);
    int request = crank_state.owned && crank_state.retained_request == pointer;
    int reply = crank_state.owned && crank_state.retained_reply == pointer;
    if (!request && !reply) {
        int rc = transaction ? (transaction != crank_state.transaction || pointer == crank_state.request_pointer ||
            pointer == crank_state.reply_pointer || pointer == crank_state.allocation_pointer ? -ESTALE : -EPERM) : 0;
        pthread_mutex_unlock(&crank_mutex); if (rc) { *result = rc; return 1; } return 0;
    }
    if (!transaction || transaction != crank_state.transaction) { pthread_mutex_unlock(&crank_mutex); *result = -ESTALE; return 1; }
    if ((request && crank_state.request_releasing) || (reply && (crank_state.reply_releasing || crank_state.reply_inspecting)) ||
        (request && crank_state.busy && !crank_request_free_allowed)) {
        pthread_mutex_unlock(&crank_mutex); *result = -EBUSY; return 1;
    }
    const long current_tid = tid();
    int rc = 0, cleanup = !event && reply && !crank_state.reply_send_started;
    if (destination != (request ? FUNCTIONAL_CAMERA_CONTROL_SID : FUNCTIONAL_CAMERA_CONTROL_AP) ||
        (!event && current_tid != crank_state.sender_tid)) rc = -EPERM;
    else if (event && (!reply || !crank_state.reply_send_started || !crank_state.reply_valid || crank_state.reply_received || crank_state.faults ||
        current_tid <= 0 || event->source != FUNCTIONAL_CAMERA_CONTROL_SID || event->bytes != 12)) rc = -EPROTO;
    else if (!event && reply && (cleanup ? !crank_state.faults : !crank_state.reply_received || crank_state.receiver_tid <= 0)) rc = -EPROTO;
    if (rc) {
        if (event) crank_state.receive_rc = rc;
        else if (request) crank_state.request_free_rc = rc;
        else crank_state.reply_free_rc = rc;
        crank_fault(rc); pthread_mutex_unlock(&crank_mutex);
        crank_record(logger, event ? "RECEIVE" : request ? "REQUEST_FREE" : "REPLY_FREE", NULL, NULL); *result = rc; return 1;
    }
    const struct full_imaging_io io = crank_transport;
    unsigned char expected[12]; memcpy(expected, request ? crank_state.request : crank_state.reply, sizeof expected);
    if (event) crank_state.reply_inspecting = 1;
    else if (request) crank_state.request_releasing = 1;
    else crank_state.reply_releasing = 1;
    pthread_mutex_unlock(&crank_mutex);
    int valid = cleanup || crank_wire_matches(&io, pointer, request ? FUNCTIONAL_CAMERA_CONTROL_AP : FUNCTIONAL_CAMERA_CONTROL_SID, expected);
    rc = valid ? event ? 0 : release(destination, pointer) : -EPROTO;
    pthread_mutex_lock(&crank_mutex);
    if (crank_state.transaction != transaction || (request ? crank_state.retained_request : crank_state.retained_reply) != pointer) rc = -ESTALE;
    if (event) {
        crank_state.reply_inspecting = 0; crank_state.receive_rc = rc;
        if (!rc) { crank_state.reply_received = 1; crank_state.receiver_tid = current_tid; }
    } else if (request) {
        crank_state.request_releasing = 0; crank_state.request_free_rc = rc;
        if (!rc) { crank_state.retained_request = NULL; crank_state.request_freed = 1; crank_state.request_free_tid = tid(); }
    } else {
        crank_state.reply_releasing = 0; crank_state.reply_free_rc = rc;
        if (!rc) {
            crank_state.retained_reply = NULL; crank_state.reply_free_tid = tid();
            if (cleanup) crank_state.reply_cleanup_freed = 1; else crank_state.reply_freed = 1;
        }
    }
    if (rc) crank_fault(rc > 0 ? -EPROTO : rc);
    crank_refresh();
    const struct native_functional_camera_crank_snapshot observed = crank_state;
    pthread_mutex_unlock(&crank_mutex);
    crank_record(logger, event ? "RECEIVE" : request ? "REQUEST_FREE" : cleanup ? "CLEANUP_FREE" : "REPLY_FREE", NULL, &observed);
    *result = rc > 0 ? -EPROTO : rc; return 1;
}
static void crank_finish(const struct native_cp_state_publication_guard *guard, void (*logger)(const char *, const char *), int rc, int latch_fault) {
    pthread_mutex_lock(&crank_mutex);
    if (rc && !crank_state.error) crank_state.error = rc;
    if (latch_fault) crank_fault(rc);
    unsigned int held = crank_state.guard_held; crank_state.guard_held = 0;
    pthread_mutex_unlock(&crank_mutex);
    if (held) guard->release();
    pthread_mutex_lock(&crank_mutex); crank_state.busy = 0; crank_refresh();
    const char *event = crank_state.faults ? crank_state.owned ? "FAULT" : "REFUSED" : rc ? "REFUSED" : "COMMIT";
    const struct native_functional_camera_crank_snapshot observed = crank_state;
    pthread_mutex_unlock(&crank_mutex); crank_record(logger, event, NULL, &observed);
}
static int crank_allocate(const struct full_imaging_io *io, void *request, const unsigned char reply[12]) {
    void *p = NULL; int actual_rc = io->allocate(FUNCTIONAL_CAMERA_CONTROL_AP, &p, 12, 1);
    int accessible = span(p, 12);
    int alias = accessible && (overlaps(p, 12, request, 12) || overlaps(p, 12, &crank_state, sizeof crank_state) ||
        overlaps(p, 12, &state, sizeof state) || overlaps(p, 12, &parameter_state, sizeof parameter_state));
    pthread_mutex_lock(&crank_mutex);
    crank_state.allocate_rc = actual_rc; crank_state.allocation_pointer = crank_state.reply_pointer = p;
    crank_state.reply_alias = alias; crank_state.reply_allocated = !actual_rc && accessible && !alias;
    if (accessible && !alias) crank_state.retained_reply = p;
    int rc = actual_rc > 0 ? -EPROTO : actual_rc;
    if (!rc && (!accessible || alias)) rc = -EPROTO;
    if (rc) crank_fault(rc);
    else crank_state.reply_inspecting = 1;
    pthread_mutex_unlock(&crank_mutex);
    if (!rc) {
        crank_inspecting++;
        int valid = io->size(p) == 12;
        if (valid) { memcpy(p, reply, 12); io->set_source(p, FUNCTIONAL_CAMERA_CONTROL_SID); }
        crank_inspecting--;
        if (!valid || !crank_wire_matches(io, p, FUNCTIONAL_CAMERA_CONTROL_SID, reply)) rc = -EPROTO;
        pthread_mutex_lock(&crank_mutex); crank_state.reply_inspecting = 0;
        if (rc) crank_fault(rc); else if (!crank_state.faults) crank_state.reply_valid = 1;
        if (!rc && crank_state.faults) rc = crank_state.error;
        pthread_mutex_unlock(&crank_mutex);
    }
    crank_record(io->record, "ALLOCATED", NULL, NULL); return rc;
}
static int crank_send(const struct full_imaging_io *io) {
    pthread_mutex_lock(&crank_mutex);
    void *p = crank_state.retained_reply; const uint64_t transaction = crank_state.transaction;
    unsigned char expected[12]; memcpy(expected, crank_state.reply, sizeof expected);
    int valid = p && crank_state.reply_valid && !crank_state.faults && !crank_state.reply_send_started;
    if (valid) crank_state.reply_inspecting = 1;
    pthread_mutex_unlock(&crank_mutex);
    if (!valid) return -EPROTO;
    valid = crank_wire_matches(io, p, FUNCTIONAL_CAMERA_CONTROL_SID, expected);
    pthread_mutex_lock(&crank_mutex); crank_state.reply_inspecting = 0;
    valid = valid && crank_state.transaction == transaction && crank_state.retained_reply == p && !crank_state.faults;
    if (!valid) crank_fault(-EPROTO);
    else { crank_state.reply_send_started = 1; crank_state.send_inflight = 1; }
    pthread_mutex_unlock(&crank_mutex);
    if (!valid) return -EPROTO;
    int actual_rc = io->send(FUNCTIONAL_CAMERA_CONTROL_AP, p);
    pthread_mutex_lock(&crank_mutex);
    int rc = actual_rc > 0 ? -EPROTO : actual_rc;
    if (crank_state.transaction != transaction || !crank_state.send_inflight ||
        (crank_state.retained_reply != p && !crank_state.reply_freed)) rc = -ESTALE;
    crank_state.send_rc = actual_rc; crank_state.send_inflight = 0;
    if (!actual_rc) crank_state.reply_queued = 1;
    if (rc) crank_fault(rc);
    if (!rc && crank_state.faults) rc = crank_state.error;
    crank_refresh(); pthread_mutex_unlock(&crank_mutex);
    crank_record(io->record, "SENT", NULL, NULL); return rc;
}
int native_functional_camera_crank_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_CAMERA_CONTROL_SID || !request || !io || !io->size || !result) return 0;
    if (crank_inherited()) { *result = -EXDEV; return 1; }
    if (crank_inspecting) { *result = -EBUSY; return 1; }
    crank_inspecting++; unsigned int bytes = io->size(request); crank_inspecting--;
    if (bytes < 4 || !span(request, bytes)) return 0;
    const unsigned char *p = request;
    if (p[0] != 5 || u16(p+2) != 0x409d) return 0;
    struct native_functional_camera_control_snapshot control; native_functional_camera_control_snapshot(&control);
    struct native_functional_camera_parameter_snapshot bank; native_functional_camera_parameter_snapshot(&bank);
    if (!bank.transaction && !bank.commits) return 0;
    *result = FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    if (bytes != 12) { *result = -EMSGSIZE; return 1; }
    if (u32(p+8)) { *result = -ENOTSUP; return 1; }
    if (!io->source || !io->allocate || !io->release || !io->set_source || !io->send || !guard ||
        !guard->reserve || !guard->release || !guard->predecessor_ready) return 1;
    crank_inspecting++; unsigned int source = io->source(request); crank_inspecting--;
    if (source != FUNCTIONAL_CAMERA_CONTROL_AP) { *result = -EPERM; return 1; }
    if (!crank_control_ready(&control) || !crank_bank_ready(&bank, control.model_instance)) return 1;
    unsigned char saved[12]; memcpy(saved, request, sizeof saved);
    pthread_mutex_lock(&crank_mutex);
    if (crank_state.busy || crank_state.guard_held || crank_state.retained_request || crank_state.retained_reply ||
        crank_state.request_releasing || crank_state.reply_releasing || crank_state.reply_inspecting || crank_state.send_inflight) {
        pthread_mutex_unlock(&crank_mutex); *result = -EBUSY; return 1;
    }
    if (!crank_state.initialized || crank_state.owner_pid != getpid() || crank_state.faults ||
        (crank_state.owned && !crank_state.complete)) { pthread_mutex_unlock(&crank_mutex); return 1; }
    if (bank.bank_generation <= crank_state.last_bank_generation) { pthread_mutex_unlock(&crank_mutex); *result = -ESTALE; return 1; }
    if (crank_state.transaction == UINT64_MAX || crank_state.requests == UINT64_MAX || crank_state.commits == UINT64_MAX ||
        crank_state.verified_commits == UINT64_MAX || crank_state.completions == UINT64_MAX || crank_state.last_crank_generation == UINT64_MAX) {
        pthread_mutex_unlock(&crank_mutex); *result = -EOVERFLOW; return 1;
    }
    struct native_functional_camera_crank_snapshot old = crank_state;
    crank_state = (struct native_functional_camera_crank_snapshot){.owner_pid = getpid(), .initialized = 1, .busy = 1,
        .before_rc = -ENODATA, .model_rc = -ENODATA, .after_rc = -ENODATA, .allocate_rc = -ENODATA, .send_rc = -ENODATA,
        .request_free_rc = -ENODATA, .reply_free_rc = -ENODATA, .receive_rc = -ENODATA, .sender_tid = tid(),
        .request_pointer = request, .transaction = old.transaction+1, .requests = old.requests+1, .commits = old.commits,
        .verified_commits = old.verified_commits, .completions = old.completions, .last_bank_generation = old.last_bank_generation,
        .last_crank_generation = old.last_crank_generation, .model_instance = bank.model_instance, .bank_generation = bank.bank_generation,
        .bank_transaction = bank.transaction, .bank_commits = bank.commits, .bank_released = bank.released, .bank_origin = bank.origin,
        .origin = {source, destination, 0x409d, bytes, hash(saved, sizeof saved)}};
    memcpy(crank_state.request, saved, sizeof saved);
    const uint64_t transaction = crank_state.transaction;
    const struct fcam_native_origin origin = crank_state.origin;
    pthread_mutex_unlock(&crank_mutex);
    crank_record(io->record, "BEGIN", "request", NULL);
    int rc = guard->reserve();
    if (rc) { crank_finish(guard, io->record, rc, 0); *result = rc; return 1; }
    pthread_mutex_lock(&crank_mutex); crank_state.guard_held = 1; pthread_mutex_unlock(&crank_mutex);
    rc = crank_context_matches(&control, &bank, io, guard, request, saved);
    unsigned char live[FCAM_STATE_BYTES] = {0}, receipt[FUNCTIONAL_CAMERA_CRANK_RESULT_BYTES] = {0};
    struct fcam_bridge_result r = {0}; int actual_rc = -ENODATA;
    if (!rc) {
        rc = crank_call(&origin, FCAM_OP_STATE, NULL, 0, live, sizeof live, &r, &actual_rc);
        if (!rc) rc = parameter_validate_live(live, &r, bank.model_instance);
        if (!rc && memcmp(live, bank.after_state, sizeof live)) rc = -ESTALE;
        pthread_mutex_lock(&crank_mutex);
        crank_state.before_rc = actual_rc; crank_state.before_result = r; memcpy(crank_state.before_state, live, sizeof live);
        crank_state.before_config_generation = u64(live + FCAM_S_GENERATION);
        crank_state.frame_generation = u64(live + FCAM_S_FRAME_GENERATION); crank_state.fps = u32(live + FCAM_S_FPS);
        pthread_mutex_unlock(&crank_mutex); crank_record(io->record, "BEFORE", "before_state", NULL);
    }
    if (!rc && u64(live + FCAM_S_GENERATION) == UINT64_MAX) rc = -EOVERFLOW;
    if (!rc) rc = crank_context_matches(&control, &bank, io, guard, request, saved);
    if (rc) { crank_finish(guard, io->record, rc, rc == -EPROTO || rc == -EOVERFLOW); *result = rc; return 1; }
    pthread_mutex_lock(&crank_mutex); crank_state.model_called = 1; pthread_mutex_unlock(&crank_mutex);
    unsigned char input[12]; memcpy(input, saved, sizeof input);
    r = (struct fcam_bridge_result){0}; actual_rc = -ENODATA;
    rc = crank_call(&origin, FCAM_OP_CP_CRANK_CONTROL, input, sizeof input, receipt, sizeof receipt, &r, &actual_rc);
    if (!rc && memcmp(input, saved, sizeof input)) rc = -EPROTO;
    pthread_mutex_lock(&crank_mutex);
    crank_state.model_rc = actual_rc; crank_state.model_committed = actual_rc == 0;
    if (crank_state.model_committed) crank_state.commits++;
    crank_state.crank_result = r; memcpy(crank_state.receipt, receipt, sizeof receipt);
    crank_state.receipt_fnv1a64 = hash(receipt, sizeof receipt);
    crank_state.crank_generation = u64(receipt+16); crank_state.config_generation = u64(receipt+40);
    struct native_functional_camera_crank_snapshot committed = crank_state;
    pthread_mutex_unlock(&crank_mutex);
    if (!rc) rc = crank_validate_receipt(&committed, old.last_crank_generation);
    crank_record(io->record, "MODEL", "receipt", NULL);
    if (!rc) rc = crank_context_matches(&control, &bank, io, guard, request, saved);
    if (!rc) {
        r = (struct fcam_bridge_result){0}; actual_rc = -ENODATA;
        rc = crank_call(&origin, FCAM_OP_STATE, NULL, 0, live, sizeof live, &r, &actual_rc);
        if (!rc) rc = parameter_validate_live(live, &r, bank.model_instance);
        if (!rc && memcmp(live, receipt+64, sizeof live)) rc = -ESTALE;
        pthread_mutex_lock(&crank_mutex);
        crank_state.after_rc = actual_rc; crank_state.after_result = r; memcpy(crank_state.after_state, live, sizeof live);
        pthread_mutex_unlock(&crank_mutex); crank_record(io->record, "AFTER", "after_state", NULL);
    }
    if (!rc) rc = crank_context_matches(&control, &bank, io, guard, request, saved);
    if (rc) { crank_finish(guard, io->record, rc, 1); *result = rc; return 1; }
    pthread_mutex_lock(&crank_mutex);
    crank_state.verified = crank_state.owned = 1; crank_state.retained_request = request; crank_state.verified_commits++;
    crank_state.last_bank_generation = bank.bank_generation; crank_state.last_crank_generation = crank_state.crank_generation;
    crank_transport = *io;
    pthread_mutex_unlock(&crank_mutex); crank_record(io->record, "VERIFIED", NULL, NULL);
    unsigned char reply[12] = {1, 0, 0x9d, 0x40}; memcpy(reply+4, saved+4, 4); put16(reply+8, 0xf000);
    pthread_mutex_lock(&crank_mutex); memcpy(crank_state.reply, reply, sizeof reply); crank_state.reply_fnv1a64 = hash(reply, sizeof reply);
    pthread_mutex_unlock(&crank_mutex); crank_record(io->record, "REPLY", "reply", NULL);
    rc = crank_context_matches(&control, &bank, io, guard, request, saved);
    if (!rc) rc = crank_allocate(io, request, reply);
    if (!rc) rc = crank_context_matches(&control, &bank, io, guard, request, saved);
    if (!rc) rc = crank_send(io);
    if (!rc) {
        int freed = -EPROTO; crank_request_free_allowed = 1;
        native_functional_camera_crank_release(destination, request, io->release, io->record, &freed, transaction, NULL);
        crank_request_free_allowed = 0; rc = freed;
    }
    crank_finish(guard, io->record, rc, rc != 0); *result = 0; return 1;
}
#ifdef HOST_TEST
void native_functional_camera_control_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_functional_camera_control_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
/* Independent late movie-format owner; old diagnostic and functional owners stay read-only. */
_Static_assert(FCAM_OP_CP_MOVIE_FORMAT == 22u, "finite movie-format opcode");
_Static_assert(FCAM_CP_MOVIE_FORMAT_INPUT_BYTES == FUNCTIONAL_CAMERA_MOVIE_FORMAT_REQUEST_BYTES, "complete movie-format input");
_Static_assert(FCAM_CP_MOVIE_FORMAT_RESULT_BYTES == FUNCTIONAL_CAMERA_MOVIE_FORMAT_RESULT_BYTES, "shared movie-format result");
_Static_assert(FCAM_CP_MOVIE_FORMAT_VERSION == 1u && FCAM_CP_MOVIE_FORMAT_SOFTWARE_CODEC_H264 == 1u, "declared movie software mapping");
_Static_assert(FUNCTIONAL_CAMERA_MOVIE_FORMAT_RESULT_BYTES == 240u, "complete movie-format receipt");
static pthread_mutex_t movie_format_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int movie_format_owner_pid;
static _Thread_local unsigned int movie_format_inspecting, movie_format_request_free_allowed;
static struct native_functional_camera_movie_format_snapshot movie_format_state;
static struct full_imaging_io movie_format_transport;
static uint64_t movie_format_completed_transaction;
static int movie_format_inherited(void) {
    int pid = atomic_load(&movie_format_owner_pid);
    return (pid && pid != getpid()) || crank_inherited();
}
static void movie_format_refresh(void) {
    movie_format_state.reply_consumed = movie_format_state.reply_queued && movie_format_state.reply_received && movie_format_state.reply_freed &&
        !movie_format_state.send_inflight && !movie_format_state.reply_releasing && !movie_format_state.reply_inspecting &&
        !movie_format_state.send_rc && !movie_format_state.reply_free_rc && !movie_format_state.receive_rc && !movie_format_state.faults &&
        movie_format_state.receiver_tid > 0 && movie_format_state.reply_free_tid == movie_format_state.sender_tid;
    movie_format_state.complete = movie_format_state.owned && movie_format_state.verified && movie_format_state.request_freed &&
        movie_format_state.reply_consumed && !movie_format_state.busy && !movie_format_state.guard_held && !movie_format_state.faults &&
        !movie_format_state.retained_request && !movie_format_state.retained_reply && !movie_format_state.request_releasing;
    if (movie_format_state.complete && movie_format_completed_transaction != movie_format_state.transaction) {
        movie_format_completed_transaction = movie_format_state.transaction; movie_format_state.completions++;
    }
}
static void movie_format_fault(int rc) {
    movie_format_state.faults = 1;
    if (!movie_format_state.error) movie_format_state.error = rc;
    movie_format_refresh();
}
int native_functional_camera_movie_format_owner_init(void) {
    if (movie_format_inherited()) return -EXDEV;
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&movie_format_owner_pid, &expected, pid);
    if (atomic_load(&movie_format_owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&movie_format_mutex);
    if (movie_format_state.initialized) { pthread_mutex_unlock(&movie_format_mutex); return -EALREADY; }
    movie_format_state.owner_pid = pid; movie_format_state.initialized = 1;
    pthread_mutex_unlock(&movie_format_mutex); return 0;
}
void native_functional_camera_movie_format_snapshot(struct native_functional_camera_movie_format_snapshot *out) {
    if (!out) return;
    if (movie_format_inherited()) {
        *out = (struct native_functional_camera_movie_format_snapshot){.owner_pid = atomic_load(&movie_format_owner_pid), .faults = 1};
        return;
    }
    pthread_mutex_lock(&movie_format_mutex); *out = movie_format_state; pthread_mutex_unlock(&movie_format_mutex);
}
static void movie_format_record(void (*logger)(const char *, const char *), const char *event, const char *kind,
    const struct native_functional_camera_movie_format_snapshot *observed) {
    if (!logger || !observed) return;
    const struct native_functional_camera_movie_format_snapshot s = *observed;
    char text[4608];
    snprintf(text, sizeof text,
        "event=%s pid=%d tid=%ld transaction=%llu sender_tid=%ld receiver_tid=%ld source=%#x destination=%#x command=%#x bytes=%u "
        "native_fnv1a=%016llx cookie=%#x busy=%u guard=%u faults=%u error=%d before_rc=%d model_rc=%d after_rc=%d validation_rc=%d model_called=%u "
        "model_committed=%u verified=%u owned=%u complete=%u retained_request=%p retained_reply=%p request_pointer=%p reply_pointer=%p allocation_pointer=%p "
        "request_releasing=%u request_freed=%u request_free_rc=%d request_free_tid=%ld reply_releasing=%u reply_inspecting=%u "
        "reply_allocated=%u reply_valid=%u reply_alias=%u allocate_rc=%d send_started=%u send_inflight=%u send_rc=%d ACK_sent=%u "
        "reply_received=%u receive_rc=%d reply_freed=%u reply_cleanup_freed=%u reply_free_rc=%d reply_free_tid=%ld reply_consumed=%u "
        "requests=%llu commits=%llu verified_commits=%llu completions=%llu model_instance=%llu bank_generation=%llu crank_generation=%llu movie_generation=%llu "
        "last_bank_generation=%llu last_crank_generation=%llu last_movie_generation=%llu before_config_generation=%llu config_generation=%llu frame_generation=%llu "
        "software_format=%u software_rate_index=%u fps=%u software_codec=%u "
        "bank_transaction=%llu bank_commits=%llu bank_released=%llu bank_source=%#x bank_destination=%#x bank_command=%#x bank_bytes=%u bank_native_fnv1a=%016llx "
        "crank_transaction=%llu crank_completions=%llu crank_source=%#x crank_destination=%#x crank_command=%#x crank_bytes=%u crank_native_fnv1a=%016llx "
        "receipt_fnv1a=%016llx reply_fnv1a=%016llx before_used=%lu before_required=%lu before_token=%llu before_instance=%llu "
        "movie_used=%lu movie_required=%lu movie_token=%llu movie_instance=%llu after_used=%lu after_required=%lu after_token=%llu after_instance=%llu "
        "policy=%s functional_model=1 original_CP=0 physical_ASIC_verified=0 EE=0 frame=0 capture=0 capture_verified=0",
        event, s.owner_pid, tid(), (unsigned long long)s.transaction, s.sender_tid, s.receiver_tid,
        s.origin.source, s.origin.destination, s.origin.command, s.origin.bytes, (unsigned long long)s.origin.wire_fnv1a64,
        u32(s.request+4), s.busy, s.guard_held, s.faults, s.error, s.before_rc, s.model_rc, s.after_rc, s.validation_rc, s.model_called,
        s.model_committed, s.verified, s.owned, s.complete, s.retained_request, s.retained_reply,
        s.request_pointer, s.reply_pointer, s.allocation_pointer, s.request_releasing, s.request_freed, s.request_free_rc,
        s.request_free_tid, s.reply_releasing, s.reply_inspecting, s.reply_allocated, s.reply_valid, s.reply_alias, s.allocate_rc,
        s.reply_send_started, s.send_inflight, s.send_rc, s.reply_queued, s.reply_received, s.receive_rc,
        s.reply_freed, s.reply_cleanup_freed, s.reply_free_rc, s.reply_free_tid, s.reply_consumed,
        (unsigned long long)s.requests, (unsigned long long)s.commits, (unsigned long long)s.verified_commits,
        (unsigned long long)s.completions, (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation,
        (unsigned long long)s.crank_generation, (unsigned long long)s.movie_generation, (unsigned long long)s.last_bank_generation,
        (unsigned long long)s.last_crank_generation, (unsigned long long)s.last_movie_generation,
        (unsigned long long)s.before_config_generation, (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation,
        s.software_format, s.software_rate_index, s.fps, s.software_codec,
        (unsigned long long)s.bank_transaction, (unsigned long long)s.bank_commits, (unsigned long long)s.bank_released,
        s.bank_origin.source, s.bank_origin.destination, s.bank_origin.command, s.bank_origin.bytes, (unsigned long long)s.bank_origin.wire_fnv1a64,
        (unsigned long long)s.crank_transaction, (unsigned long long)s.crank_completions, s.crank_origin.source,
        s.crank_origin.destination, s.crank_origin.command, s.crank_origin.bytes, (unsigned long long)s.crank_origin.wire_fnv1a64,
        (unsigned long long)s.receipt_fnv1a64, (unsigned long long)s.reply_fnv1a64,
        (unsigned long)s.before_result.used, (unsigned long)s.before_result.required, (unsigned long long)s.before_result.result_token,
        (unsigned long long)s.before_result.model_instance, (unsigned long)s.movie_result.used, (unsigned long)s.movie_result.required,
        (unsigned long long)s.movie_result.result_token, (unsigned long long)s.movie_result.model_instance,
        (unsigned long)s.after_result.used, (unsigned long)s.after_result.required, (unsigned long long)s.after_result.result_token,
        (unsigned long long)s.after_result.model_instance, FUNCTIONAL_CAMERA_MOVIE_FORMAT_POLICY);
    logger("FUNCTIONAL_CP_MOVIE_FORMAT_EVENT ", text);
    const unsigned char *raw = NULL; size_t bytes = 0;
    if (kind && !strcmp(kind, "request")) { raw = s.request; bytes = sizeof s.request; }
    else if (kind && !strcmp(kind, "before_state")) { raw = s.before_state; bytes = sizeof s.before_state; }
    else if (kind && !strcmp(kind, "receipt")) { raw = s.receipt; bytes = sizeof s.receipt; }
    else if (kind && !strcmp(kind, "after_state")) { raw = s.after_state; bytes = sizeof s.after_state; }
    else if (kind && !strcmp(kind, "reply")) { raw = s.reply; bytes = sizeof s.reply; }
    for (size_t offset = 0; offset < bytes; offset += 128) {
        size_t n = bytes-offset; if (n > 128) n = 128;
        char hex[257]; static const char digits[] = "0123456789abcdef";
        for (size_t i = 0; i < n; i++) { hex[2*i] = digits[raw[offset+i] >> 4]; hex[2*i+1] = digits[raw[offset+i] & 15]; }
        hex[2*n] = 0;
        snprintf(text, sizeof text,
            "event=%s pid=%d tid=%ld transaction=%llu kind=%s total=%lu offset=%lu bytes=%lu raw=%s native_fnv1a=%016llx content_fnv1a=%016llx "
            "model_instance=%llu bank_generation=%llu crank_generation=%llu movie_generation=%llu functional_model=1 original_CP=0 physical_ASIC_verified=0 capture_verified=0",
            event, s.owner_pid, tid(), (unsigned long long)s.transaction, kind, (unsigned long)bytes, (unsigned long)offset,
            (unsigned long)n, hex, (unsigned long long)s.origin.wire_fnv1a64, (unsigned long long)hash(raw, bytes),
            (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation, (unsigned long long)s.crank_generation,
            (unsigned long long)s.movie_generation);
        logger("FUNCTIONAL_CP_MOVIE_FORMAT_BYTES ", text);
    }
}
static int movie_format_crank_ready(const struct native_functional_camera_crank_snapshot *s,
    const struct native_functional_camera_movie_format_context *context) {
    if (s->owner_pid != getpid() || !s->initialized || s->busy || s->guard_held || s->faults || s->error ||
        !s->owned || !s->verified || !s->complete || !s->model_called || !s->model_committed || s->model_rc ||
        !s->request_freed || !s->reply_allocated || !s->reply_valid || s->reply_alias || !s->reply_send_started ||
        !s->reply_queued || !s->reply_received || !s->reply_freed || !s->reply_consumed || s->reply_cleanup_freed ||
        s->retained_request || s->retained_reply || s->request_releasing || s->reply_releasing || s->reply_inspecting || s->send_inflight ||
        s->before_rc || s->after_rc || s->allocate_rc || s->send_rc || s->request_free_rc || s->reply_free_rc || s->receive_rc ||
        s->sender_tid <= 0 || s->receiver_tid <= 0 || s->request_free_tid != s->sender_tid || s->reply_free_tid != s->sender_tid ||
        !s->request_pointer || !s->reply_pointer || s->request_pointer == s->reply_pointer || s->allocation_pointer != s->reply_pointer ||
        !s->transaction || !s->commits || s->verified_commits != s->commits || s->completions != s->commits ||
        s->model_instance != context->model_instance || s->bank_generation != context->bank_generation ||
        s->crank_generation != context->crank_generation || !s->crank_generation || s->last_bank_generation != s->bank_generation ||
        s->last_crank_generation != s->crank_generation || s->mode || s->fps != u32(s->before_state+FCAM_S_FPS) ||
        s->origin.source != FUNCTIONAL_CAMERA_CONTROL_AP || s->origin.destination != FUNCTIONAL_CAMERA_CONTROL_SID ||
        s->origin.command != 0x409d || s->origin.bytes != sizeof s->request || s->origin.wire_fnv1a64 != hash(s->request, sizeof s->request) ||
        s->request[0] != 5 || u16(s->request+2) != 0x409d || u32(s->request+8) ||
        parameter_validate_live(s->before_state, &s->before_result, context->model_instance) ||
        parameter_validate_live(s->after_state, &s->after_result, context->model_instance) ||
        s->before_config_generation != u64(s->before_state+FCAM_S_GENERATION) ||
        s->config_generation != u64(s->after_state+FCAM_S_GENERATION) ||
        s->frame_generation != u64(s->before_state+FCAM_S_FRAME_GENERATION) ||
        crank_validate_receipt(s, s->crank_generation-1) || memcmp(s->after_state, s->receipt+64, sizeof s->after_state) ||
        s->receipt_fnv1a64 != hash(s->receipt, sizeof s->receipt) || s->reply_fnv1a64 != hash(s->reply, sizeof s->reply)) return 0;
    unsigned char expected[12] = {1, 0, 0x9d, 0x40, 0, 0, 0, 0, 0, 0xf0}; memcpy(expected+4, s->request+4, 4);
    return !memcmp(s->reply, expected, sizeof expected);
}
static int movie_format_wire_matches(const struct full_imaging_io *io, void *pointer, unsigned int source,
    const unsigned char *expected, unsigned int bytes) {
    movie_format_inspecting++;
    unsigned int actual_bytes = io->size(pointer), actual_source = io->source(pointer);
    movie_format_inspecting--;
    return actual_bytes == bytes && actual_source == source && !memcmp(pointer, expected, bytes);
}
static int movie_format_context_matches(const struct native_functional_camera_control_snapshot *control,
    const struct native_functional_camera_parameter_snapshot *bank, const struct native_functional_camera_crank_snapshot *crank,
    const struct native_functional_camera_movie_format_context *context, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, void *request, const unsigned char expected[20]) {
    if (guard->predecessor_ready() != 1) return FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    struct native_functional_camera_control_snapshot c; native_functional_camera_control_snapshot(&c);
    struct native_functional_camera_parameter_snapshot b; native_functional_camera_parameter_snapshot(&b);
    struct native_functional_camera_crank_snapshot k; native_functional_camera_crank_snapshot(&k);
    if (!crank_control_ready(&c) || !crank_bank_ready(&b, context->model_instance) || !movie_format_crank_ready(&k, context) ||
        c.model_instance != context->model_instance || b.bank_generation != context->bank_generation ||
        k.bank_transaction != b.transaction || k.bank_commits != b.commits || k.bank_released != b.released ||
        memcmp(&k.bank_origin, &b.origin, sizeof b.origin) || k.fps != b.fps ||
        memcmp(control, &c, sizeof c) || memcmp(bank, &b, sizeof b) || memcmp(crank, &k, sizeof k)) return -ESTALE;
    return movie_format_wire_matches(io, request, FUNCTIONAL_CAMERA_CONTROL_AP, expected, 20) ? 0 : -EPROTO;
}
static int movie_format_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    unsigned char *output, size_t bytes, struct fcam_bridge_result *result, int *actual_rc) {
    unsigned char guarded[16+FUNCTIONAL_CAMERA_MOVIE_FORMAT_RESULT_BYTES+16];
    memset(guarded, 0xa5, sizeof guarded); memset(guarded+16, 0, bytes);
    struct fcam_native_origin actual_origin = *origin;
    int rc = fcam_bridge_call(&actual_origin, opcode, input, input_bytes, guarded+16, bytes, result);
    *actual_rc = rc; memcpy(output, guarded+16, bytes);
    if (memcmp(origin, &actual_origin, sizeof actual_origin)) return -EPROTO;
    for (size_t i = 0; i < sizeof guarded; i++)
        if ((i < 16 || i >= 16+bytes) && guarded[i] != 0xa5) return -EOVERFLOW;
    return rc > 0 ? -EPROTO : rc;
}
static int movie_format_validate_receipt(const struct native_functional_camera_movie_format_snapshot *s, uint64_t last_movie) {
    const unsigned char *p = s->receipt; const struct fcam_bridge_result *r = &s->movie_result;
    if (s->before_config_generation == UINT64_MAX || last_movie == UINT64_MAX) return -EOVERFLOW;
    unsigned char expected[FCAM_STATE_BYTES]; memcpy(expected, s->before_state, sizeof expected);
    uint64_t generation = s->before_config_generation+1;
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(generation >> (8*i));
    if (r->used != sizeof s->receipt || r->required != sizeof s->receipt || r->result_token || r->model_instance != s->model_instance ||
        u32(p) != 1 || u32(p+4) != sizeof s->receipt || u64(p+8) != s->model_instance || u64(p+16) != last_movie+1 ||
        u64(p+24) != s->bank_generation || u64(p+32) != s->crank_generation || u64(p+40) != s->before_config_generation ||
        u64(p+48) != generation || u64(p+56) != s->origin.wire_fnv1a64 || u32(p+64) != 5 || u32(p+68) ||
        u32(p+72) != s->fps || u32(p+76) != 1 || memcmp(p+80, expected, sizeof expected) ||
        memcmp(p+208, s->request, sizeof s->request) || u32(p+228) || u32(p+232) || u32(p+236)) return -EPROTO;
    return 0;
}
int native_functional_camera_movie_format_release(unsigned int destination, void *pointer, int (*release)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t transaction,
    const struct native_functional_camera_movie_format_receive *event) {
    if (!pointer || !result || (!event && !release)) return 0;
    if (movie_format_inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&movie_format_mutex);
    int request = movie_format_state.owned && movie_format_state.retained_request == pointer;
    int reply = movie_format_state.owned && movie_format_state.retained_reply == pointer;
    if (!request && !reply) {
        int rc = transaction ? (transaction != movie_format_state.transaction || pointer == movie_format_state.request_pointer ||
            pointer == movie_format_state.reply_pointer || pointer == movie_format_state.allocation_pointer ? -ESTALE : -EPERM) : 0;
        pthread_mutex_unlock(&movie_format_mutex); if (rc) { *result = rc; return 1; } return 0;
    }
    if (!transaction || transaction != movie_format_state.transaction) { pthread_mutex_unlock(&movie_format_mutex); *result = -ESTALE; return 1; }
    if ((request && movie_format_state.request_releasing) || (reply && (movie_format_state.reply_releasing || movie_format_state.reply_inspecting)) ||
        (request && movie_format_state.busy && !movie_format_request_free_allowed)) {
        pthread_mutex_unlock(&movie_format_mutex); *result = -EBUSY; return 1;
    }
    const long current_tid = tid();
    int rc = 0, cleanup = !event && reply && !movie_format_state.reply_send_started;
    if (destination != (request ? FUNCTIONAL_CAMERA_CONTROL_SID : FUNCTIONAL_CAMERA_CONTROL_AP) ||
        (!event && current_tid != movie_format_state.sender_tid)) rc = -EPERM;
    else if (event && (!reply || !movie_format_state.reply_send_started || !movie_format_state.reply_valid || movie_format_state.reply_received || movie_format_state.faults ||
        current_tid <= 0 || event->source != FUNCTIONAL_CAMERA_CONTROL_SID || event->bytes != 12)) rc = -EPROTO;
    else if (!event && reply && (cleanup ? !movie_format_state.faults : !movie_format_state.reply_received || movie_format_state.receiver_tid <= 0)) rc = -EPROTO;
    if (rc) {
        if (event) movie_format_state.receive_rc = rc;
        else if (request) movie_format_state.request_free_rc = rc;
        else movie_format_state.reply_free_rc = rc;
        movie_format_fault(rc);
        const struct native_functional_camera_movie_format_snapshot observed = movie_format_state;
        pthread_mutex_unlock(&movie_format_mutex);
        movie_format_record(logger, event ? "RECEIVE" : request ? "REQUEST_FREE" : "REPLY_FREE", NULL, &observed); *result = rc; return 1;
    }
    const struct full_imaging_io io = movie_format_transport;
    unsigned char expected[20]; unsigned int bytes = request ? 20 : 12;
    memcpy(expected, request ? movie_format_state.request : movie_format_state.reply, bytes);
    if (event) movie_format_state.reply_inspecting = 1;
    else if (request) movie_format_state.request_releasing = 1;
    else movie_format_state.reply_releasing = 1;
    pthread_mutex_unlock(&movie_format_mutex);
    int valid = cleanup || movie_format_wire_matches(&io, pointer, request ? FUNCTIONAL_CAMERA_CONTROL_AP : FUNCTIONAL_CAMERA_CONTROL_SID, expected, bytes);
    rc = valid ? event ? 0 : release(destination, pointer) : -EPROTO;
    const int actual_rc = rc;
    pthread_mutex_lock(&movie_format_mutex);
    if (movie_format_state.transaction != transaction || (request ? movie_format_state.retained_request : movie_format_state.retained_reply) != pointer) rc = -ESTALE;
    if (event) {
        movie_format_state.reply_inspecting = 0; movie_format_state.receive_rc = actual_rc;
        if (!rc) { movie_format_state.reply_received = 1; movie_format_state.receiver_tid = current_tid; }
    } else if (request) {
        movie_format_state.request_releasing = 0; movie_format_state.request_free_rc = actual_rc;
        if (!rc) { movie_format_state.retained_request = NULL; movie_format_state.request_freed = 1; movie_format_state.request_free_tid = current_tid; }
    } else {
        movie_format_state.reply_releasing = 0; movie_format_state.reply_free_rc = actual_rc;
        if (!rc) {
            movie_format_state.retained_reply = NULL; movie_format_state.reply_free_tid = current_tid;
            if (cleanup) movie_format_state.reply_cleanup_freed = 1; else movie_format_state.reply_freed = 1;
        }
    }
    if (rc) movie_format_fault(rc > 0 ? -EPROTO : rc);
    movie_format_refresh();
    const struct native_functional_camera_movie_format_snapshot observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex);
    movie_format_record(logger, event ? "RECEIVE" : request ? "REQUEST_FREE" : cleanup ? "CLEANUP_FREE" : "REPLY_FREE", NULL, &observed);
    *result = rc > 0 ? -EPROTO : rc; return 1;
}
static void movie_format_finish(const struct native_cp_state_publication_guard *guard, void (*logger)(const char *, const char *), int rc, int latch_fault) {
    pthread_mutex_lock(&movie_format_mutex);
    if (rc && !movie_format_state.error) movie_format_state.error = rc;
    if (latch_fault) movie_format_fault(rc);
    unsigned int held = movie_format_state.guard_held; movie_format_state.guard_held = 0;
    pthread_mutex_unlock(&movie_format_mutex);
    if (held) guard->release();
    pthread_mutex_lock(&movie_format_mutex); movie_format_state.busy = 0; movie_format_refresh();
    const char *event = movie_format_state.faults ? movie_format_state.owned ? "FAULT" : "REFUSED" : rc ? "REFUSED" : "COMMIT";
    const struct native_functional_camera_movie_format_snapshot observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(logger, event, NULL, &observed);
}
static int movie_format_allocate(const struct full_imaging_io *io, void *request, const unsigned char reply[12]) {
    void *p = NULL; int actual_rc = io->allocate(FUNCTIONAL_CAMERA_CONTROL_AP, &p, 12, 1);
    int accessible = span(p, 12);
    int alias = accessible && (overlaps(p, 12, request, 20) || overlaps(p, 12, &movie_format_state, sizeof movie_format_state) ||
        overlaps(p, 12, &state, sizeof state) || overlaps(p, 12, &parameter_state, sizeof parameter_state) ||
        overlaps(p, 12, &crank_state, sizeof crank_state));
    pthread_mutex_lock(&movie_format_mutex);
    movie_format_state.allocate_rc = actual_rc; movie_format_state.allocation_pointer = movie_format_state.reply_pointer = p;
    movie_format_state.reply_alias = alias; movie_format_state.reply_allocated = !actual_rc && accessible && !alias;
    if (accessible && !alias) movie_format_state.retained_reply = p;
    int rc = actual_rc > 0 ? -EPROTO : actual_rc;
    if (!rc && (!accessible || alias)) rc = -EPROTO;
    if (rc) movie_format_fault(rc);
    else movie_format_state.reply_inspecting = 1;
    pthread_mutex_unlock(&movie_format_mutex);
    if (!rc) {
        movie_format_inspecting++;
        int valid = io->size(p) == 12;
        if (valid) { memcpy(p, reply, 12); io->set_source(p, FUNCTIONAL_CAMERA_CONTROL_SID); }
        movie_format_inspecting--;
        if (!valid || !movie_format_wire_matches(io, p, FUNCTIONAL_CAMERA_CONTROL_SID, reply, 12)) rc = -EPROTO;
        pthread_mutex_lock(&movie_format_mutex); movie_format_state.reply_inspecting = 0;
        if (rc) movie_format_fault(rc); else if (!movie_format_state.faults) movie_format_state.reply_valid = 1;
        if (!rc && movie_format_state.faults) rc = movie_format_state.error;
        pthread_mutex_unlock(&movie_format_mutex);
    }
    pthread_mutex_lock(&movie_format_mutex);
    const struct native_functional_camera_movie_format_snapshot observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "ALLOCATED", NULL, &observed); return rc;
}
static int movie_format_send(const struct full_imaging_io *io) {
    pthread_mutex_lock(&movie_format_mutex);
    void *p = movie_format_state.retained_reply; const uint64_t transaction = movie_format_state.transaction;
    unsigned char expected[12]; memcpy(expected, movie_format_state.reply, sizeof expected);
    int valid = p && movie_format_state.reply_valid && !movie_format_state.faults && !movie_format_state.reply_send_started;
    if (valid) movie_format_state.reply_inspecting = 1;
    pthread_mutex_unlock(&movie_format_mutex);
    if (!valid) return -EPROTO;
    valid = movie_format_wire_matches(io, p, FUNCTIONAL_CAMERA_CONTROL_SID, expected, 12);
    pthread_mutex_lock(&movie_format_mutex); movie_format_state.reply_inspecting = 0;
    valid = valid && movie_format_state.transaction == transaction && movie_format_state.retained_reply == p && !movie_format_state.faults;
    if (!valid) movie_format_fault(-EPROTO);
    else { movie_format_state.reply_send_started = 1; movie_format_state.send_inflight = 1; }
    pthread_mutex_unlock(&movie_format_mutex);
    if (!valid) return -EPROTO;
    int actual_rc = io->send(FUNCTIONAL_CAMERA_CONTROL_AP, p);
    pthread_mutex_lock(&movie_format_mutex);
    int rc = actual_rc > 0 ? -EPROTO : actual_rc;
    if (movie_format_state.transaction != transaction || !movie_format_state.send_inflight ||
        (movie_format_state.retained_reply != p && !movie_format_state.reply_freed)) rc = -ESTALE;
    movie_format_state.send_rc = actual_rc; movie_format_state.send_inflight = 0;
    if (!actual_rc) movie_format_state.reply_queued = 1;
    if (rc) movie_format_fault(rc);
    if (!rc && movie_format_state.faults) rc = movie_format_state.error;
    movie_format_refresh();
    const struct native_functional_camera_movie_format_snapshot observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "SENT", NULL, &observed); return rc;
}
int native_functional_camera_movie_format_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, const struct native_functional_camera_movie_format_context *context,
    int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_CAMERA_CONTROL_SID || !request || !io || !io->size || !result) return 0;
    if (movie_format_inherited()) { *result = -EXDEV; return 1; }
    if (movie_format_inspecting) { *result = -EBUSY; return 1; }
    movie_format_inspecting++; unsigned int bytes = io->size(request); movie_format_inspecting--;
    if (bytes < 4 || !span(request, bytes)) return 0;
    const unsigned char *p = request;
    if (p[0] != 5 || u16(p+2) != 0x4000) return 0;
    struct native_functional_camera_control_snapshot control; native_functional_camera_control_snapshot(&control);
    struct native_functional_camera_parameter_snapshot bank; native_functional_camera_parameter_snapshot(&bank);
    struct native_functional_camera_crank_snapshot crank; native_functional_camera_crank_snapshot(&crank);
    if (!bank.transaction && !bank.commits && !crank.transaction && !crank.commits) return 0;
    *result = FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    if (bytes != 20) { *result = -EMSGSIZE; return 1; }
    if (p[8] != 5 || p[9] != 1 || p[10] || u32(p+12) || p[16] || p[17] || p[18] != 1) { *result = -ENOTSUP; return 1; }
    if (!io->source || !io->allocate || !io->release || !io->set_source || !io->send || !io->record || !guard ||
        !guard->reserve || !guard->release || !guard->predecessor_ready || !context) return 1;
    const struct native_functional_camera_movie_format_context operation = *context;
    movie_format_inspecting++; unsigned int source = io->source(request); movie_format_inspecting--;
    if (source != FUNCTIONAL_CAMERA_CONTROL_AP) { *result = -EPERM; return 1; }
    if (!operation.model_instance || !operation.bank_generation || !operation.crank_generation ||
        !crank_control_ready(&control) || control.model_instance != operation.model_instance ||
        !crank_bank_ready(&bank, operation.model_instance) || bank.bank_generation != operation.bank_generation ||
        !movie_format_crank_ready(&crank, &operation) || crank.bank_transaction != bank.transaction ||
        crank.bank_commits != bank.commits || crank.bank_released != bank.released ||
        memcmp(&crank.bank_origin, &bank.origin, sizeof bank.origin) || crank.fps != bank.fps) return 1;
    unsigned char saved[20]; memcpy(saved, request, sizeof saved);
    pthread_mutex_lock(&movie_format_mutex);
    if (movie_format_state.busy || movie_format_state.guard_held || movie_format_state.retained_request || movie_format_state.retained_reply ||
        movie_format_state.request_releasing || movie_format_state.reply_releasing || movie_format_state.reply_inspecting || movie_format_state.send_inflight) {
        pthread_mutex_unlock(&movie_format_mutex); *result = -EBUSY; return 1;
    }
    if (!movie_format_state.initialized || movie_format_state.owner_pid != getpid() || movie_format_state.faults ||
        (movie_format_state.owned && !movie_format_state.complete)) { pthread_mutex_unlock(&movie_format_mutex); return 1; }
    if (operation.bank_generation < movie_format_state.last_bank_generation || operation.crank_generation < movie_format_state.last_crank_generation ||
        (operation.bank_generation == movie_format_state.last_bank_generation && operation.crank_generation == movie_format_state.last_crank_generation)) {
        pthread_mutex_unlock(&movie_format_mutex); *result = -ESTALE; return 1;
    }
    if (movie_format_state.transaction == UINT64_MAX || movie_format_state.requests == UINT64_MAX || movie_format_state.commits == UINT64_MAX ||
        movie_format_state.verified_commits == UINT64_MAX || movie_format_state.completions == UINT64_MAX || movie_format_state.last_movie_generation == UINT64_MAX) {
        pthread_mutex_unlock(&movie_format_mutex); *result = -EOVERFLOW; return 1;
    }
    const struct native_functional_camera_movie_format_snapshot old = movie_format_state;
    movie_format_state = (struct native_functional_camera_movie_format_snapshot){.owner_pid = getpid(), .initialized = 1, .busy = 1,
        .before_rc = -ENODATA, .model_rc = -ENODATA, .after_rc = -ENODATA, .validation_rc = -ENODATA, .allocate_rc = -ENODATA, .send_rc = -ENODATA,
        .request_free_rc = -ENODATA, .reply_free_rc = -ENODATA, .receive_rc = -ENODATA, .sender_tid = tid(),
        .request_pointer = request, .transaction = old.transaction+1, .requests = old.requests+1, .commits = old.commits,
        .verified_commits = old.verified_commits, .completions = old.completions, .last_bank_generation = old.last_bank_generation,
        .last_crank_generation = old.last_crank_generation, .last_movie_generation = old.last_movie_generation,
        .model_instance = operation.model_instance, .bank_generation = operation.bank_generation, .crank_generation = operation.crank_generation,
        .bank_transaction = bank.transaction, .bank_commits = bank.commits, .bank_released = bank.released, .bank_origin = bank.origin,
        .crank_transaction = crank.transaction, .crank_completions = crank.completions, .crank_origin = crank.origin,
        .origin = {source, destination, 0x4000, bytes, hash(saved, sizeof saved)}};
    memcpy(movie_format_state.request, saved, sizeof saved);
    const uint64_t transaction = movie_format_state.transaction;
    const struct fcam_native_origin origin = movie_format_state.origin;
    struct native_functional_camera_movie_format_snapshot observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "BEGIN", "request", &observed);
    int rc = guard->reserve();
    if (rc) { movie_format_finish(guard, io->record, rc, 0); *result = rc; return 1; }
    pthread_mutex_lock(&movie_format_mutex); movie_format_state.guard_held = 1; pthread_mutex_unlock(&movie_format_mutex);
    rc = movie_format_context_matches(&control, &bank, &crank, &operation, io, guard, request, saved);
    unsigned char live[FCAM_STATE_BYTES] = {0}, receipt[FUNCTIONAL_CAMERA_MOVIE_FORMAT_RESULT_BYTES] = {0};
    struct fcam_bridge_result r = {0}; int actual_rc = -ENODATA;
    if (!rc) {
        rc = movie_format_call(&origin, FCAM_OP_STATE, NULL, 0, live, sizeof live, &r, &actual_rc);
        if (!rc) rc = parameter_validate_live(live, &r, operation.model_instance);
        if (!rc && (u64(live+FCAM_S_GENERATION) < crank.config_generation || u32(live+FCAM_S_FPS) != bank.fps)) rc = -ESTALE;
        pthread_mutex_lock(&movie_format_mutex);
        movie_format_state.before_rc = actual_rc; movie_format_state.before_result = r; memcpy(movie_format_state.before_state, live, sizeof live);
        movie_format_state.before_config_generation = u64(live+FCAM_S_GENERATION);
        movie_format_state.frame_generation = u64(live+FCAM_S_FRAME_GENERATION); movie_format_state.fps = u32(live+FCAM_S_FPS);
        observed = movie_format_state;
        pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "BEFORE", "before_state", &observed);
    }
    if (!rc && u64(live+FCAM_S_GENERATION) == UINT64_MAX) rc = -EOVERFLOW;
    if (!rc) rc = movie_format_context_matches(&control, &bank, &crank, &operation, io, guard, request, saved);
    if (rc) { movie_format_finish(guard, io->record, rc, rc == -EPROTO || rc == -EOVERFLOW); *result = rc; return 1; }
    pthread_mutex_lock(&movie_format_mutex); movie_format_state.model_called = 1; pthread_mutex_unlock(&movie_format_mutex);
    unsigned char input[20]; memcpy(input, saved, sizeof input);
    r = (struct fcam_bridge_result){0}; actual_rc = -ENODATA;
    rc = movie_format_call(&origin, FCAM_OP_CP_MOVIE_FORMAT, input, sizeof input, receipt, sizeof receipt, &r, &actual_rc);
    if (!rc && memcmp(input, saved, sizeof input)) rc = -EPROTO;
    pthread_mutex_lock(&movie_format_mutex);
    movie_format_state.model_rc = actual_rc; movie_format_state.model_committed = actual_rc == 0;
    if (movie_format_state.model_committed) movie_format_state.commits++;
    movie_format_state.movie_result = r; memcpy(movie_format_state.receipt, receipt, sizeof receipt);
    movie_format_state.receipt_fnv1a64 = hash(receipt, sizeof receipt);
    movie_format_state.movie_generation = u64(receipt+16); movie_format_state.config_generation = u64(receipt+48);
    movie_format_state.software_format = u32(receipt+64); movie_format_state.software_rate_index = u32(receipt+68);
    movie_format_state.software_codec = u32(receipt+76);
    observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex);
    if (!rc) rc = movie_format_validate_receipt(&observed, old.last_movie_generation);
    pthread_mutex_lock(&movie_format_mutex); movie_format_state.validation_rc = rc; observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "MODEL", "receipt", &observed);
    if (!rc) rc = movie_format_context_matches(&control, &bank, &crank, &operation, io, guard, request, saved);
    if (!rc) {
        r = (struct fcam_bridge_result){0}; actual_rc = -ENODATA;
        rc = movie_format_call(&origin, FCAM_OP_STATE, NULL, 0, live, sizeof live, &r, &actual_rc);
        if (!rc) rc = parameter_validate_live(live, &r, operation.model_instance);
        if (!rc && memcmp(live, receipt+80, sizeof live)) rc = -ESTALE;
        pthread_mutex_lock(&movie_format_mutex);
        movie_format_state.after_rc = actual_rc; movie_format_state.after_result = r; memcpy(movie_format_state.after_state, live, sizeof live);
        movie_format_state.validation_rc = rc; observed = movie_format_state;
        pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "AFTER", "after_state", &observed);
    }
    if (!rc) rc = movie_format_context_matches(&control, &bank, &crank, &operation, io, guard, request, saved);
    if (rc) {
        pthread_mutex_lock(&movie_format_mutex); movie_format_state.validation_rc = rc; pthread_mutex_unlock(&movie_format_mutex);
        movie_format_finish(guard, io->record, rc, 1); *result = rc; return 1;
    }
    pthread_mutex_lock(&movie_format_mutex);
    movie_format_state.verified = movie_format_state.owned = 1; movie_format_state.retained_request = request; movie_format_state.verified_commits++;
    movie_format_state.last_bank_generation = operation.bank_generation; movie_format_state.last_crank_generation = operation.crank_generation;
    movie_format_state.last_movie_generation = movie_format_state.movie_generation; movie_format_transport = *io;
    observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "VERIFIED", NULL, &observed);
    unsigned char reply[12] = {1, 0, 0, 0x40}; memcpy(reply+4, saved+4, 4); put16(reply+8, 0xf000);
    pthread_mutex_lock(&movie_format_mutex); memcpy(movie_format_state.reply, reply, sizeof reply); movie_format_state.reply_fnv1a64 = hash(reply, sizeof reply);
    observed = movie_format_state;
    pthread_mutex_unlock(&movie_format_mutex); movie_format_record(io->record, "REPLY", "reply", &observed);
    rc = movie_format_context_matches(&control, &bank, &crank, &operation, io, guard, request, saved);
    if (!rc) rc = movie_format_allocate(io, request, reply);
    if (!rc) rc = movie_format_context_matches(&control, &bank, &crank, &operation, io, guard, request, saved);
    if (!rc) rc = movie_format_send(io);
    if (!rc) {
        int freed = -EPROTO; movie_format_request_free_allowed = 1;
        native_functional_camera_movie_format_release(destination, request, io->release, io->record, &freed, transaction, NULL);
        movie_format_request_free_allowed = 0; rc = freed;
    }
    movie_format_finish(guard, io->record, rc, rc != 0); *result = 0; return 1;
}
/* Independent late OU mode0; every earlier owner/function above is unchanged. */
#include "functional-startup-control.h"
_Static_assert(FCAM_OP_CP_OU_CRANK_CONTROL == 23u, "finite OU crank opcode");
_Static_assert(FCAM_CP_OU_CRANK_INPUT_BYTES == FUNCTIONAL_CAMERA_OU_CRANK_REQUEST_BYTES, "complete OU input");
_Static_assert(FCAM_CP_OU_CRANK_RESULT_BYTES == FUNCTIONAL_CAMERA_OU_CRANK_RESULT_BYTES, "complete OU receipt");
_Static_assert(FCAM_CP_OU_CRANK_R_OU_GENERATION == 16u && FCAM_CP_OU_CRANK_STATE_OFFSET == 80u &&
    FCAM_CP_OU_CRANK_READBACK_OFFSET == 208u, "fixed shared OU layout");
static pthread_mutex_t ou_crank_mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int ou_crank_owner_pid;
static _Thread_local unsigned int ou_crank_inspecting, ou_crank_request_free_allowed;
static struct native_functional_camera_ou_crank_snapshot ou_crank_state;
static struct full_imaging_io ou_crank_transport;
static uint64_t ou_crank_completed_transaction;
struct ou_crank_predecessors {
    struct native_functional_camera_control_snapshot control;
    struct native_functional_camera_parameter_snapshot bank;
    struct native_functional_camera_crank_snapshot crank;
    struct native_functional_camera_movie_format_snapshot movie;
    struct functional_startup_control_snapshot startup;
};
static int ou_crank_inherited(void) {
    int pid = atomic_load(&ou_crank_owner_pid);
    return (pid && pid != getpid()) || movie_format_inherited();
}
static int ou_crank_private_alias(const void *p, size_t n) {
    return overlaps(p, n, &state, sizeof state) || overlaps(p, n, &parameter_state, sizeof parameter_state) ||
        overlaps(p, n, &crank_state, sizeof crank_state) || overlaps(p, n, &movie_format_state, sizeof movie_format_state) ||
        overlaps(p, n, &ou_crank_state, sizeof ou_crank_state) || overlaps(p, n, &transport, sizeof transport) ||
        overlaps(p, n, &parameter_transport, sizeof parameter_transport) || overlaps(p, n, &crank_transport, sizeof crank_transport) ||
        overlaps(p, n, &movie_format_transport, sizeof movie_format_transport) || overlaps(p, n, &ou_crank_transport, sizeof ou_crank_transport) ||
        overlaps(p, n, &mutex, sizeof mutex) || overlaps(p, n, &parameter_mutex, sizeof parameter_mutex) ||
        overlaps(p, n, &crank_mutex, sizeof crank_mutex) || overlaps(p, n, &movie_format_mutex, sizeof movie_format_mutex) ||
        overlaps(p, n, &owner_pid, sizeof owner_pid) || overlaps(p, n, &parameter_owner_pid, sizeof parameter_owner_pid) ||
        overlaps(p, n, &crank_owner_pid, sizeof crank_owner_pid) || overlaps(p, n, &movie_format_owner_pid, sizeof movie_format_owner_pid) ||
        overlaps(p, n, wires, sizeof wires) || overlaps(p, n, started, sizeof started) || overlaps(p, n, &completed_cycle, sizeof completed_cycle) ||
        overlaps(p, n, &crank_completed_transaction, sizeof crank_completed_transaction) ||
        overlaps(p, n, &movie_format_completed_transaction, sizeof movie_format_completed_transaction) ||
        overlaps(p, n, &ou_crank_completed_transaction, sizeof ou_crank_completed_transaction) ||
        overlaps(p, n, &ou_crank_mutex, sizeof ou_crank_mutex) || overlaps(p, n, &ou_crank_owner_pid, sizeof ou_crank_owner_pid);
}
static void ou_crank_refresh(void) {
    ou_crank_state.complete = ou_crank_state.owned && ou_crank_state.verified && ou_crank_state.model_committed &&
        ou_crank_state.request_freed && !ou_crank_state.free_rc && ou_crank_state.free_tid == ou_crank_state.sender_tid &&
        ou_crank_state.sender_tid > 0 && !ou_crank_state.busy && !ou_crank_state.guard_held && !ou_crank_state.releasing &&
        !ou_crank_state.retained_request && !ou_crank_state.faults && !ou_crank_state.guard_fault && !ou_crank_state.error;
    if (ou_crank_state.complete && ou_crank_completed_transaction != ou_crank_state.transaction) {
        ou_crank_completed_transaction = ou_crank_state.transaction; ou_crank_state.completions++;
    }
}
static void ou_crank_fault(int rc) {
    ou_crank_state.faults = 1;
    if (!ou_crank_state.error) ou_crank_state.error = rc;
    ou_crank_refresh();
}
int native_functional_camera_ou_crank_owner_init(void) {
    if (ou_crank_inherited()) return -EXDEV;
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&ou_crank_owner_pid, &expected, pid);
    if (atomic_load(&ou_crank_owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&ou_crank_mutex);
    if (ou_crank_state.initialized) { pthread_mutex_unlock(&ou_crank_mutex); return -EALREADY; }
    ou_crank_state.owner_pid = pid; ou_crank_state.initialized = 1;
    pthread_mutex_unlock(&ou_crank_mutex); return 0;
}
void native_functional_camera_ou_crank_snapshot(struct native_functional_camera_ou_crank_snapshot *out) {
    if (!span(out, sizeof *out) || ou_crank_private_alias(out, sizeof *out)) return;
    if (ou_crank_inherited()) {
        *out = (struct native_functional_camera_ou_crank_snapshot){.owner_pid = atomic_load(&ou_crank_owner_pid), .faults = 1}; return;
    }
    pthread_mutex_lock(&ou_crank_mutex); *out = ou_crank_state; pthread_mutex_unlock(&ou_crank_mutex);
}
static void ou_crank_record(void (*logger)(const char *, const char *), const char *event, const char *kind,
    const struct native_functional_camera_ou_crank_snapshot *observed) {
    if (!logger || !observed) return;
    const struct native_functional_camera_ou_crank_snapshot s = *observed;
    char text[8192];
    snprintf(text, sizeof text,
        "event=%s pid=%d tid=%ld transaction=%llu sender_tid=%ld source=%#x destination=%#x command=%#x bytes=%u "
        "native_fnv1a=%016llx cookie=%#x busy=%u guard=%u guard_fault=%u faults=%u error=%d before_rc=%d model_rc=%d after_rc=%d validation_rc=%d "
        "model_called=%u model_committed=%u verified=%u owned=%u complete=%u retained_request=%p request_pointer=%p "
        "releasing=%u request_freed=%u free_rc=%d free_tid=%ld requests=%llu commits=%llu verified_commits=%llu completions=%llu released=%llu "
        "model_instance=%llu bank_generation=%llu crank_generation=%llu movie_generation=%llu ou_generation=%llu "
        "last_bank_generation=%llu last_crank_generation=%llu last_movie_generation=%llu last_ou_generation=%llu "
        "before_config_generation=%llu config_generation=%llu frame_generation=%llu mode=%u fps=%u "
        "bank_transaction=%llu bank_commits=%llu bank_released=%llu bank_source=%#x bank_destination=%#x bank_command=%#x bank_bytes=%u bank_native_fnv1a=%016llx "
        "crank_transaction=%llu crank_completions=%llu crank_source=%#x crank_destination=%#x crank_command=%#x crank_bytes=%u crank_native_fnv1a=%016llx "
        "movie_transaction=%llu movie_completions=%llu movie_source=%#x movie_destination=%#x movie_command=%#x movie_bytes=%u movie_native_fnv1a=%016llx "
        "startup_cycle=%llu startup_completed_cycles=%u startup_config_generation=%llu startup_frame_generation=%llu startup_lease_generation=%llu "
        "startup_result_fnv1a=%016llx startup_config40_fnv1a=%016llx startup_source=%#x startup_destination=%#x startup_command=%#x startup_bytes=%u startup_native_fnv1a=%016llx "
        "receipt_fnv1a=%016llx before_used=%lu before_required=%lu before_token=%llu before_instance=%llu "
        "ou_used=%lu ou_required=%lu ou_token=%llu ou_instance=%llu after_used=%lu after_required=%lu after_token=%llu after_instance=%llu "
        "resource=36 policy=%s oneway=1 ACK_sent=0 notification_sent=0 functional_model=1 original_CP=0 physical_ASIC_verified=0 EE=0 frame=0 capture=0 capture_verified=0",
        event, s.owner_pid, tid(), (unsigned long long)s.transaction, s.sender_tid,
        s.origin.source, s.origin.destination, s.origin.command, s.origin.bytes, (unsigned long long)s.origin.wire_fnv1a64,
        u32(s.request+4), s.busy, s.guard_held, s.guard_fault, s.faults, s.error, s.before_rc, s.model_rc, s.after_rc, s.validation_rc,
        s.model_called, s.model_committed, s.verified, s.owned, s.complete, s.retained_request, s.request_pointer,
        s.releasing, s.request_freed, s.free_rc, s.free_tid, (unsigned long long)s.requests, (unsigned long long)s.commits,
        (unsigned long long)s.verified_commits, (unsigned long long)s.completions, (unsigned long long)s.released,
        (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation, (unsigned long long)s.crank_generation,
        (unsigned long long)s.movie_generation, (unsigned long long)s.ou_generation, (unsigned long long)s.last_bank_generation,
        (unsigned long long)s.last_crank_generation, (unsigned long long)s.last_movie_generation, (unsigned long long)s.last_ou_generation,
        (unsigned long long)s.before_config_generation, (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation, s.mode, s.fps,
        (unsigned long long)s.bank_transaction, (unsigned long long)s.bank_commits, (unsigned long long)s.bank_released,
        s.bank_origin.source, s.bank_origin.destination, s.bank_origin.command, s.bank_origin.bytes, (unsigned long long)s.bank_origin.wire_fnv1a64,
        (unsigned long long)s.crank_transaction, (unsigned long long)s.crank_completions,
        s.crank_origin.source, s.crank_origin.destination, s.crank_origin.command, s.crank_origin.bytes, (unsigned long long)s.crank_origin.wire_fnv1a64,
        (unsigned long long)s.movie_transaction, (unsigned long long)s.movie_completions,
        s.movie_origin.source, s.movie_origin.destination, s.movie_origin.command, s.movie_origin.bytes, (unsigned long long)s.movie_origin.wire_fnv1a64,
        (unsigned long long)s.startup_cycle, s.startup_completed_cycles, (unsigned long long)s.startup_config_generation,
        (unsigned long long)s.startup_frame_generation, (unsigned long long)s.startup_lease_generation,
        (unsigned long long)s.startup_result_fnv1a64, (unsigned long long)s.startup_config40_fnv1a64,
        s.startup_origin.source, s.startup_origin.destination, s.startup_origin.command, s.startup_origin.bytes, (unsigned long long)s.startup_origin.wire_fnv1a64,
        (unsigned long long)s.receipt_fnv1a64,
        (unsigned long)s.before_result.used, (unsigned long)s.before_result.required, (unsigned long long)s.before_result.result_token, (unsigned long long)s.before_result.model_instance,
        (unsigned long)s.ou_result.used, (unsigned long)s.ou_result.required, (unsigned long long)s.ou_result.result_token, (unsigned long long)s.ou_result.model_instance,
        (unsigned long)s.after_result.used, (unsigned long)s.after_result.required, (unsigned long long)s.after_result.result_token, (unsigned long long)s.after_result.model_instance,
        FUNCTIONAL_CAMERA_OU_CRANK_POLICY);
    logger("FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT ", text);
    const unsigned char *raw = NULL; size_t bytes = 0;
    if (kind && !strcmp(kind, "request")) { raw = s.request; bytes = sizeof s.request; }
    else if (kind && !strcmp(kind, "before_state")) { raw = s.before_state; bytes = sizeof s.before_state; }
    else if (kind && !strcmp(kind, "receipt")) { raw = s.receipt; bytes = sizeof s.receipt; }
    else if (kind && !strcmp(kind, "after_state")) { raw = s.after_state; bytes = sizeof s.after_state; }
    for (size_t offset = 0; offset < bytes; offset += 128) {
        size_t n = bytes-offset; if (n > 128) n = 128;
        char hex[257]; static const char digits[] = "0123456789abcdef";
        for (size_t i = 0; i < n; i++) { hex[2*i] = digits[raw[offset+i] >> 4]; hex[2*i+1] = digits[raw[offset+i] & 15]; }
        hex[2*n] = 0;
        snprintf(text, sizeof text,
            "event=%s pid=%d tid=%ld transaction=%llu kind=%s total=%lu offset=%lu bytes=%lu raw=%s native_fnv1a=%016llx content_fnv1a=%016llx "
            "model_instance=%llu bank_generation=%llu crank_generation=%llu movie_generation=%llu ou_generation=%llu "
            "functional_model=1 original_CP=0 physical_ASIC_verified=0 capture_verified=0",
            event, s.owner_pid, tid(), (unsigned long long)s.transaction, kind, (unsigned long)bytes, (unsigned long)offset,
            (unsigned long)n, hex, (unsigned long long)s.origin.wire_fnv1a64, (unsigned long long)hash(raw, bytes),
            (unsigned long long)s.model_instance, (unsigned long long)s.bank_generation, (unsigned long long)s.crank_generation,
            (unsigned long long)s.movie_generation, (unsigned long long)s.ou_generation);
        logger("FUNCTIONAL_CP_OU_CRANK_CONTROL_BYTES ", text);
    }
}
static int ou_crank_movie_ready(const struct native_functional_camera_movie_format_snapshot *s,
    const struct native_functional_camera_ou_crank_context *context) {
    if (s->owner_pid != getpid() || !s->initialized || s->busy || s->guard_held || s->faults || s->error ||
        !s->model_called || !s->model_committed || !s->verified || !s->owned || !s->complete ||
        s->model_rc || s->validation_rc || s->before_rc || s->after_rc || s->allocate_rc || s->send_rc || s->receive_rc || s->request_free_rc || s->reply_free_rc ||
        !s->request_freed || !s->reply_allocated || !s->reply_valid || s->reply_alias || !s->reply_send_started || !s->reply_queued ||
        !s->reply_received || !s->reply_freed || !s->reply_consumed || s->reply_cleanup_freed || s->retained_request || s->retained_reply ||
        s->request_releasing || s->reply_releasing || s->reply_inspecting || s->send_inflight ||
        s->sender_tid <= 0 || s->receiver_tid <= 0 || s->request_free_tid != s->sender_tid || s->reply_free_tid != s->sender_tid ||
        !s->request_pointer || !s->reply_pointer || s->request_pointer == s->reply_pointer || s->allocation_pointer != s->reply_pointer ||
        !s->transaction || !s->requests || !s->commits || s->verified_commits != s->commits || s->completions != s->commits ||
        s->model_instance != context->model_instance || s->bank_generation != context->bank_generation ||
        s->crank_generation != context->crank_generation || s->movie_generation != context->movie_generation ||
        s->last_bank_generation != s->bank_generation || s->last_crank_generation != s->crank_generation || s->last_movie_generation != s->movie_generation ||
        s->software_format != 5 || s->software_rate_index || s->software_codec != 1 || s->fps != u32(s->before_state+FCAM_S_FPS) ||
        s->origin.source != FUNCTIONAL_CAMERA_CONTROL_AP || s->origin.destination != FUNCTIONAL_CAMERA_CONTROL_SID ||
        s->origin.command != 0x4000 || s->origin.bytes != sizeof s->request || s->origin.wire_fnv1a64 != hash(s->request, sizeof s->request) ||
        s->request[0] != 5 || u16(s->request+2) != 0x4000 || s->request[8] != 5 || s->request[9] != 1 || s->request[10] ||
        u32(s->request+12) || s->request[16] || s->request[17] || s->request[18] != 1 ||
        parameter_validate_live(s->before_state, &s->before_result, context->model_instance) ||
        parameter_validate_live(s->after_state, &s->after_result, context->model_instance) ||
        s->before_config_generation != u64(s->before_state+FCAM_S_GENERATION) || s->config_generation != u64(s->after_state+FCAM_S_GENERATION) ||
        s->frame_generation != u64(s->before_state+FCAM_S_FRAME_GENERATION) || movie_format_validate_receipt(s, s->movie_generation-1) ||
        memcmp(s->after_state, s->receipt+80, sizeof s->after_state) || s->receipt_fnv1a64 != hash(s->receipt, sizeof s->receipt) ||
        s->reply_fnv1a64 != hash(s->reply, sizeof s->reply)) return 0;
    unsigned char expected[12] = {1, 0, 0, 0x40, 0, 0, 0, 0, 0, 0xf0}; memcpy(expected+4, s->request+4, 4);
    return !memcmp(expected, s->reply, sizeof expected);
}
static int ou_crank_startup_ready(const struct functional_startup_control_snapshot *s, uint64_t instance) {
    if (s->owner_pid != getpid() || !s->initialized || !s->functional_only || s->busy || s->guard_held || s->faults || s->retained ||
        !s->state_valid || !s->operation_attempted || !s->model_complete || !s->mode_applied || !s->request_owned || !s->ap_consumed ||
        s->command != FCAM_STARTUP_CONTROL_CMD_SETTINGS || s->original_wire_bytes != 12 || s->model_instance != instance ||
        !s->cycle || !s->requests || s->completed_cycles != s->requests || s->cycle != s->requests ||
        !s->command_completed[0] || !s->command_completed[1] || s->command_requests[0] != s->command_completed[0] ||
        s->command_requests[1] != s->command_completed[1] ||
        (uint64_t)s->command_completed[0] + s->command_completed[1] != s->completed_cycles ||
        s->state_bridge_rc || s->state_validation_rc || s->bridge_rc || s->validation_rc || s->transport_rc ||
        s->original_ap_verified || s->original_cp || s->physical_asic_verified || s->physical_cp_rtos_verified ||
        s->original_selector_verified || s->capture_verified || s->source_dependencies_closed || s->native_cp || s->ee ||
        s->origin.source != FUNCTIONAL_CAMERA_CONTROL_AP || s->origin.destination != FUNCTIONAL_CAMERA_CONTROL_SID ||
        s->origin.command != 0x4057 || s->origin.bytes != 12 || s->origin.wire_fnv1a64 != hash(s->original_wire, 12) ||
        s->actual_origin_fnv != s->origin.wire_fnv1a64 || s->original_wire[0] != 5 || u16(s->original_wire+2) != 0x4057 || u32(s->original_wire+8) ||
        parameter_validate_live(s->model_state, &s->state_response, instance) ||
        s->before_config_generation == UINT64_MAX || s->before_frame_generation == UINT64_MAX ||
        s->before_config_generation != u64(s->model_state+FCAM_S_GENERATION) ||
        s->before_frame_generation != u64(s->model_state+FCAM_S_FRAME_GENERATION) ||
        s->config_generation != s->before_config_generation+1 || s->frame_generation != s->before_frame_generation+1 ||
        s->current_config40_fnv != hash(s->model_state+8, 40) || s->result_fnv != hash(s->model_result, sizeof s->model_result)) return 0;
    unsigned char canonical[32] = {0x57, 0x40, 4}, reply[12] = {1, 0, 0x57, 0x40, 0, 0, 0, 0, 0, 0xf0};
    for (unsigned int i = 0; i < 8; i++) canonical[24+i] = (unsigned char)(s->current_config40_fnv >> (8*i));
    memcpy(reply+4, s->original_wire+4, 4);
    if (memcmp(canonical, s->canonical32, sizeof canonical) || memcmp(reply, s->reply_wire, sizeof reply)) return 0;
    const unsigned char *p = s->model_result; const struct fcam_bridge_result *r = &s->control_response;
    if (r->used != 192 || r->required != 192 || r->result_token || r->model_instance != instance ||
        u32(p) != FCAM_ABI_VERSION || u32(p+4) != 192 || u64(p+8) != instance || u64(p+16) != s->config_generation ||
        u64(p+24) != s->frame_generation || u64(p+32) != s->lease_generation || u64(p+40) != hash(canonical, sizeof canonical) ||
        !s->lease_generation || s->lease_generation <= s->before_lease_generation ||
        u64(s->model_state+FCAM_S_RENDERED) == UINT64_MAX || s->lease_generation <= u64(s->model_state+FCAM_S_RENDERED) ||
        s->lease_generation < s->frame_generation || !u64(p+48) || u64(p+48) != u64(p+56) || u64(p+64) != UINT64_C(921600) ||
        u32(p+72) != 640 || u32(p+76) != 480 || u32(p+80) != 1920 || u32(p+84) != FCAM_VDF_ENDPOINT ||
        u32(p+88) != 1 || u32(p+92) != 1 || u32(p+96) != FCAM_STARTUP_CONTROL_CLASS || u32(p+100) != 1 ||
        u32(p+104) != 1 || u32(p+108) != 1 || u32(p+112) != 1 || u32(p+116) != 1 || u32(p+120) || u32(p+124) ||
        p[128] != 1 || p[129] != 5 || p[130] != 5 || p[132] > 2 || p[141] || p[142] || p[143] ||
        u64(p+144) != s->before_frame_generation || u64(p+152) != s->before_config_generation || memcmp(p+160, canonical, sizeof canonical)) return 0;
    for (unsigned int i = 0; i < 2; i++) {
        const struct native_cp_state_publication_lease *l = &s->leases[i];
        if (l->role != i+1 || l->bytes != 12 || l->source != (i ? FUNCTIONAL_CAMERA_CONTROL_SID : FUNCTIONAL_CAMERA_CONTROL_AP) ||
            l->destination != (i ? FUNCTIONAL_CAMERA_CONTROL_AP : FUNCTIONAL_CAMERA_CONTROL_SID) ||
            l->pointer || !l->freed || l->releasing || l->send_inflight || l->faults || l->allocate_rc || l->send_rc || l->free_rc ||
            l->sender_tid <= 0 || l->free_tid != l->sender_tid ||
            l->wire_fnv1a64 != hash(i ? s->reply_wire : s->original_wire, 12) ||
            (i && (!l->queued || !l->received || !l->consumed || l->receiver_tid <= 0 || l->sender_tid != s->leases[0].sender_tid))) return 0;
    }
    return 1;
}
static void ou_crank_read_predecessors(struct ou_crank_predecessors *p) {
    memset(p, 0, sizeof *p);
    native_functional_camera_control_snapshot(&p->control);
    native_functional_camera_parameter_snapshot(&p->bank);
    native_functional_camera_crank_snapshot(&p->crank);
    native_functional_camera_movie_format_snapshot(&p->movie);
    functional_startup_control_snapshot(&p->startup);
}
static int ou_crank_predecessors_ready(const struct ou_crank_predecessors *p,
    const struct native_functional_camera_ou_crank_context *context) {
    const struct native_functional_camera_movie_format_context crank_context = {
        context->model_instance, context->bank_generation, context->crank_generation};
    return context->model_instance && context->bank_generation && context->crank_generation && context->movie_generation &&
        crank_control_ready(&p->control) && p->control.model_instance == context->model_instance &&
        crank_bank_ready(&p->bank, context->model_instance) && !p->bank.model_rc && p->bank.bank_generation == context->bank_generation &&
        movie_format_crank_ready(&p->crank, &crank_context) && ou_crank_movie_ready(&p->movie, context) &&
        ou_crank_startup_ready(&p->startup, context->model_instance) &&
        p->crank.bank_transaction == p->bank.transaction && p->crank.bank_commits == p->bank.commits && p->crank.bank_released == p->bank.released &&
        !memcmp(&p->crank.bank_origin, &p->bank.origin, sizeof p->bank.origin) && p->crank.fps == p->bank.fps &&
        p->movie.bank_transaction == p->bank.transaction && p->movie.bank_commits == p->bank.commits && p->movie.bank_released == p->bank.released &&
        !memcmp(&p->movie.bank_origin, &p->bank.origin, sizeof p->bank.origin) && p->movie.fps == p->bank.fps &&
        p->movie.crank_transaction == p->crank.transaction && p->movie.crank_completions == p->crank.completions &&
        !memcmp(&p->movie.crank_origin, &p->crank.origin, sizeof p->crank.origin) &&
        p->movie.before_config_generation >= p->crank.config_generation && p->startup.before_config_generation >= p->movie.config_generation &&
        u32(p->startup.model_state+FCAM_S_FPS) == p->bank.fps;
}
static int ou_crank_wire_matches(const struct full_imaging_io *io, void *pointer, const unsigned char expected[12]) {
    ou_crank_inspecting++;
    unsigned int bytes = io->size(pointer), source = io->source(pointer);
    int valid = bytes == 12 && source == FUNCTIONAL_CAMERA_CONTROL_AP && !memcmp(pointer, expected, 12);
    ou_crank_inspecting--; return valid;
}
static int ou_crank_context_matches(const struct ou_crank_predecessors *before,
    const struct native_functional_camera_ou_crank_context *context, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, void *request, const unsigned char expected[12]) {
    struct ou_crank_predecessors current; ou_crank_read_predecessors(&current);
    int ready = guard->predecessor_ready();
    if (ready != 1) {
        pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.guard_fault = 1; pthread_mutex_unlock(&ou_crank_mutex);
        return FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    }
    ou_crank_read_predecessors(&current);
    if (!ou_crank_predecessors_ready(&current, context) || memcmp(before, &current, sizeof current)) return -ESTALE;
    return ou_crank_wire_matches(io, request, expected) ? 0 : -EPROTO;
}
static int ou_crank_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    unsigned char *output, size_t bytes, struct fcam_bridge_result *result, int *actual_rc) {
    unsigned char guarded[16+FUNCTIONAL_CAMERA_OU_CRANK_RESULT_BYTES+16];
    memset(guarded, 0xa5, sizeof guarded); memset(guarded+16, 0, bytes);
    struct fcam_native_origin actual_origin = *origin;
    int rc = fcam_bridge_call(&actual_origin, opcode, input, input_bytes, guarded+16, bytes, result);
    *actual_rc = rc; memcpy(output, guarded+16, bytes);
    if (memcmp(origin, &actual_origin, sizeof actual_origin)) return -EPROTO;
    for (size_t i = 0; i < sizeof guarded; i++)
        if ((i < 16 || i >= 16+bytes) && guarded[i] != 0xa5) return -EOVERFLOW;
    return rc > 0 ? -EPROTO : rc;
}
static int ou_crank_validate_receipt(const struct native_functional_camera_ou_crank_snapshot *s, uint64_t last_ou) {
    const unsigned char *p = s->receipt; const struct fcam_bridge_result *r = &s->ou_result;
    if (s->before_config_generation == UINT64_MAX || last_ou == UINT64_MAX) return -EOVERFLOW;
    unsigned char expected[FCAM_STATE_BYTES]; memcpy(expected, s->before_state, sizeof expected);
    const uint64_t generation = s->before_config_generation+1;
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(generation >> (8*i));
    if (r->used != sizeof s->receipt || r->required != sizeof s->receipt || r->result_token || r->model_instance != s->model_instance ||
        u32(p+FCAM_CP_OU_CRANK_R_VERSION) != FCAM_CP_OU_CRANK_VERSION || u32(p+FCAM_CP_OU_CRANK_R_BYTES) != sizeof s->receipt ||
        u64(p+FCAM_CP_OU_CRANK_R_INSTANCE) != s->model_instance || u64(p+FCAM_CP_OU_CRANK_R_OU_GENERATION) != last_ou+1 ||
        u64(p+FCAM_CP_OU_CRANK_R_BANK_GENERATION) != s->bank_generation || u64(p+FCAM_CP_OU_CRANK_R_CRANK_GENERATION) != s->crank_generation ||
        u64(p+FCAM_CP_OU_CRANK_R_MOVIE_GENERATION) != s->movie_generation ||
        u64(p+FCAM_CP_OU_CRANK_R_BEFORE_CONFIG_GENERATION) != s->before_config_generation ||
        u64(p+FCAM_CP_OU_CRANK_R_CONFIG_GENERATION) != generation || u64(p+FCAM_CP_OU_CRANK_R_INPUT_FNV) != s->origin.wire_fnv1a64 ||
        u32(p+FCAM_CP_OU_CRANK_R_MODE) || u32(p+FCAM_CP_OU_CRANK_R_FPS) != s->fps ||
        memcmp(p+FCAM_CP_OU_CRANK_STATE_OFFSET, expected, sizeof expected) ||
        memcmp(p+FCAM_CP_OU_CRANK_READBACK_OFFSET, s->request, sizeof s->request) ||
        u32(p+FCAM_CP_OU_CRANK_READBACK_OFFSET+FUNCTIONAL_CAMERA_OU_CRANK_REQUEST_BYTES)) return -EPROTO;
    return 0;
}
int native_functional_camera_ou_crank_release(unsigned int destination, void *pointer, int (*release)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t transaction) {
    if (!pointer || !release || !span(pointer, 12) || !span(result, sizeof *result) || ou_crank_private_alias(result, sizeof *result) ||
        overlaps(pointer, 12, result, sizeof *result)) return 0;
    if (ou_crank_inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&ou_crank_mutex);
    if (!ou_crank_state.owned || ou_crank_state.retained_request != pointer) {
        pthread_mutex_unlock(&ou_crank_mutex); if (transaction) { *result = -ESTALE; return 1; } return 0;
    }
    if (!transaction || transaction != ou_crank_state.transaction) { pthread_mutex_unlock(&ou_crank_mutex); *result = -ESTALE; return 1; }
    if (ou_crank_state.releasing || (ou_crank_state.busy && !ou_crank_request_free_allowed)) {
        pthread_mutex_unlock(&ou_crank_mutex); *result = -EBUSY; return 1;
    }
    if (!span(pointer, 12) || ou_crank_private_alias(pointer, 12) || overlaps(pointer, 12, result, sizeof *result)) {
        pthread_mutex_unlock(&ou_crank_mutex); *result = -EINVAL; return 1;
    }
    const long current_tid = tid();
    if (destination != FUNCTIONAL_CAMERA_CONTROL_SID || current_tid != ou_crank_state.sender_tid) {
        ou_crank_fault(-EPERM); const struct native_functional_camera_ou_crank_snapshot observed = ou_crank_state;
        pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(logger, "REQUEST_FREE", NULL, &observed); *result = -EPERM; return 1;
    }
    const struct full_imaging_io io = ou_crank_transport;
    unsigned char expected[12]; memcpy(expected, ou_crank_state.request, sizeof expected);
    ou_crank_state.releasing = 1; pthread_mutex_unlock(&ou_crank_mutex);
    const int actual_rc = ou_crank_wire_matches(&io, pointer, expected) ? release(destination, pointer) : -EPROTO;
    int rc = actual_rc > 0 ? -EPROTO : actual_rc;
    pthread_mutex_lock(&ou_crank_mutex);
    if (ou_crank_state.transaction != transaction || ou_crank_state.retained_request != pointer || !ou_crank_state.releasing) rc = -ESTALE;
    ou_crank_state.releasing = 0; ou_crank_state.free_rc = actual_rc;
    if (!rc) {
        ou_crank_state.retained_request = NULL; ou_crank_state.request_freed = 1; ou_crank_state.free_tid = current_tid; ou_crank_state.released++;
    } else ou_crank_fault(rc);
    ou_crank_refresh(); const struct native_functional_camera_ou_crank_snapshot observed = ou_crank_state;
    pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(logger, "REQUEST_FREE", NULL, &observed); *result = rc; return 1;
}
static void ou_crank_finish(const struct native_cp_state_publication_guard *guard, void (*logger)(const char *, const char *), int rc, int latch_fault) {
    pthread_mutex_lock(&ou_crank_mutex);
    if (rc && !ou_crank_state.error) ou_crank_state.error = rc;
    if (latch_fault) ou_crank_fault(rc);
    unsigned int held = ou_crank_state.guard_held; ou_crank_state.guard_held = 0;
    pthread_mutex_unlock(&ou_crank_mutex);
    if (held) guard->release();
    pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.busy = 0; ou_crank_refresh();
    const char *event = ou_crank_state.faults ? ou_crank_state.owned ? "FAULT" : "REFUSED" : rc ? "REFUSED" : "COMMIT";
    const struct native_functional_camera_ou_crank_snapshot observed = ou_crank_state;
    pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(logger, event, NULL, &observed);
}
int native_functional_camera_ou_crank_dispatch(unsigned int destination, void *request, const struct full_imaging_io *provided,
    const struct native_cp_state_publication_guard *provided_guard, const struct native_functional_camera_ou_crank_context *context,
    int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_CAMERA_CONTROL_SID || !span(request, 4) || !span(provided, sizeof *provided) ||
        !span(result, sizeof *result) || ou_crank_private_alias(request, 4) || ou_crank_private_alias(result, sizeof *result) ||
        ou_crank_private_alias(provided, sizeof *provided) || overlaps(result, sizeof *result, provided, sizeof *provided) ||
        overlaps(request, 4, result, sizeof *result) || overlaps(request, 4, provided, sizeof *provided)) return 0;
    if (ou_crank_inherited()) { *result = -EXDEV; return 1; }
    if (ou_crank_inspecting) { *result = -EBUSY; return 1; }
    if ((context && (!span(context, sizeof *context) || ou_crank_private_alias(context, sizeof *context) ||
        overlaps(request, 4, context, sizeof *context) || overlaps(result, sizeof *result, context, sizeof *context))) ||
        (provided_guard && (!span(provided_guard, sizeof *provided_guard) || ou_crank_private_alias(provided_guard, sizeof *provided_guard) ||
        overlaps(request, 4, provided_guard, sizeof *provided_guard) || overlaps(result, sizeof *result, provided_guard, sizeof *provided_guard)))) return 0;
    const struct full_imaging_io io = *provided;
    const struct native_cp_state_publication_guard guard = provided_guard ? *provided_guard : (struct native_cp_state_publication_guard){0};
    const struct native_functional_camera_ou_crank_context operation = context ? *context : (struct native_functional_camera_ou_crank_context){0};
    if (!io.size) return 0;
    ou_crank_inspecting++; unsigned int bytes = io.size(request); ou_crank_inspecting--;
    if (bytes < 4 || !span(request, bytes) || ou_crank_private_alias(request, bytes) || overlaps(request, bytes, result, sizeof *result) ||
        overlaps(request, bytes, provided, sizeof *provided) || (context && overlaps(request, bytes, context, sizeof *context)) ||
        (provided_guard && overlaps(request, bytes, provided_guard, sizeof *provided_guard))) return 0;
    const unsigned char *p = request;
    if (p[0] != 5 || u16(p+2) != FCAM_CP_OU_CRANK_COMMAND) return 0;
    struct ou_crank_predecessors predecessors; ou_crank_read_predecessors(&predecessors);
    if (!predecessors.bank.transaction && !predecessors.bank.commits && !predecessors.crank.transaction && !predecessors.crank.commits &&
        !predecessors.movie.transaction && !predecessors.movie.commits) return 0;
    *result = FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
    if (bytes != 12) { *result = -EMSGSIZE; return 1; }
    if (u32(p+8)) { *result = -ENOTSUP; return 1; }
    if (!io.source || !io.release || !io.record || !guard.reserve || !guard.release || !guard.predecessor_ready || !context) return 1;
    unsigned char saved[12]; memcpy(saved, request, sizeof saved);
    ou_crank_inspecting++; unsigned int source = io.source(request); ou_crank_inspecting--;
    if (source != FUNCTIONAL_CAMERA_CONTROL_AP) { *result = -EPERM; return 1; }
    if (!ou_crank_predecessors_ready(&predecessors, &operation)) { *result = -ESTALE; return 1; }
    pthread_mutex_lock(&ou_crank_mutex);
    if (ou_crank_state.busy || ou_crank_state.guard_held || ou_crank_state.retained_request || ou_crank_state.releasing) {
        pthread_mutex_unlock(&ou_crank_mutex); *result = -EBUSY; return 1;
    }
    if (!ou_crank_state.initialized || ou_crank_state.owner_pid != getpid() || ou_crank_state.faults ||
        (ou_crank_state.owned && !ou_crank_state.complete)) { pthread_mutex_unlock(&ou_crank_mutex); return 1; }
    if (operation.bank_generation < ou_crank_state.last_bank_generation || operation.crank_generation < ou_crank_state.last_crank_generation ||
        operation.movie_generation < ou_crank_state.last_movie_generation ||
        (operation.bank_generation == ou_crank_state.last_bank_generation && operation.crank_generation == ou_crank_state.last_crank_generation &&
        operation.movie_generation == ou_crank_state.last_movie_generation)) { pthread_mutex_unlock(&ou_crank_mutex); *result = -ESTALE; return 1; }
    if (ou_crank_state.transaction == UINT64_MAX || ou_crank_state.requests == UINT64_MAX || ou_crank_state.commits == UINT64_MAX ||
        ou_crank_state.verified_commits == UINT64_MAX || ou_crank_state.completions == UINT64_MAX || ou_crank_state.released == UINT64_MAX ||
        ou_crank_state.last_ou_generation == UINT64_MAX) { pthread_mutex_unlock(&ou_crank_mutex); *result = -EOVERFLOW; return 1; }
    const struct native_functional_camera_ou_crank_snapshot old = ou_crank_state;
    ou_crank_state = (struct native_functional_camera_ou_crank_snapshot){.owner_pid = getpid(), .initialized = 1, .busy = 1,
        .before_rc = -ENODATA, .model_rc = -ENODATA, .after_rc = -ENODATA, .validation_rc = -ENODATA, .free_rc = -ENODATA,
        .sender_tid = tid(), .request_pointer = request, .transaction = old.transaction+1, .requests = old.requests+1,
        .commits = old.commits, .verified_commits = old.verified_commits, .completions = old.completions, .released = old.released,
        .last_bank_generation = old.last_bank_generation, .last_crank_generation = old.last_crank_generation,
        .last_movie_generation = old.last_movie_generation, .last_ou_generation = old.last_ou_generation,
        .model_instance = operation.model_instance, .bank_generation = operation.bank_generation,
        .crank_generation = operation.crank_generation, .movie_generation = operation.movie_generation,
        .bank_transaction = predecessors.bank.transaction, .bank_commits = predecessors.bank.commits, .bank_released = predecessors.bank.released,
        .crank_transaction = predecessors.crank.transaction, .crank_completions = predecessors.crank.completions,
        .movie_transaction = predecessors.movie.transaction, .movie_completions = predecessors.movie.completions,
        .startup_cycle = predecessors.startup.cycle, .startup_completed_cycles = predecessors.startup.completed_cycles,
        .startup_config_generation = predecessors.startup.config_generation, .startup_frame_generation = predecessors.startup.frame_generation,
        .startup_lease_generation = predecessors.startup.lease_generation, .startup_result_fnv1a64 = predecessors.startup.result_fnv,
        .startup_config40_fnv1a64 = predecessors.startup.current_config40_fnv,
        .bank_origin = predecessors.bank.origin, .crank_origin = predecessors.crank.origin,
        .movie_origin = predecessors.movie.origin, .startup_origin = predecessors.startup.origin,
        .origin = {source, destination, FCAM_CP_OU_CRANK_COMMAND, bytes, hash(saved, sizeof saved)}};
    memcpy(ou_crank_state.request, saved, sizeof saved);
    const uint64_t transaction = ou_crank_state.transaction;
    const struct fcam_native_origin origin = ou_crank_state.origin;
    struct native_functional_camera_ou_crank_snapshot observed = ou_crank_state;
    pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(io.record, "BEGIN", "request", &observed);
    int rc = guard.reserve();
    if (rc) { ou_crank_finish(&guard, io.record, rc > 0 ? -EPROTO : rc, 0); *result = rc > 0 ? -EPROTO : rc; return 1; }
    pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.guard_held = 1; pthread_mutex_unlock(&ou_crank_mutex);
    rc = ou_crank_context_matches(&predecessors, &operation, &io, &guard, request, saved);
    unsigned char live[FCAM_STATE_BYTES] = {0}, receipt[FUNCTIONAL_CAMERA_OU_CRANK_RESULT_BYTES] = {0};
    struct fcam_bridge_result r = {0}; int actual_rc = -ENODATA;
    if (!rc) {
        rc = ou_crank_call(&origin, FCAM_OP_STATE, NULL, 0, live, sizeof live, &r, &actual_rc);
        if (!rc) rc = parameter_validate_live(live, &r, operation.model_instance);
        if (!rc && (u64(live+FCAM_S_GENERATION) != predecessors.startup.config_generation ||
            u64(live+FCAM_S_FRAME_GENERATION) != predecessors.startup.frame_generation || u32(live+FCAM_S_FPS) != predecessors.bank.fps ||
            memcmp(live+8, predecessors.startup.model_state+8, 40) || u64(live+FCAM_S_RENDERED) < predecessors.startup.lease_generation)) rc = -ESTALE;
        if (!rc && u64(live+FCAM_S_GENERATION) == UINT64_MAX) rc = -EOVERFLOW;
        pthread_mutex_lock(&ou_crank_mutex);
        ou_crank_state.before_rc = actual_rc; ou_crank_state.before_result = r; memcpy(ou_crank_state.before_state, live, sizeof live);
        ou_crank_state.before_config_generation = u64(live+FCAM_S_GENERATION); ou_crank_state.frame_generation = u64(live+FCAM_S_FRAME_GENERATION);
        ou_crank_state.fps = u32(live+FCAM_S_FPS); observed = ou_crank_state;
        pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(io.record, "BEFORE", "before_state", &observed);
    }
    if (!rc) rc = ou_crank_context_matches(&predecessors, &operation, &io, &guard, request, saved);
    if (rc) { ou_crank_finish(&guard, io.record, rc, rc == -EPROTO || rc == -EOVERFLOW); *result = rc; return 1; }
    pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.model_called = 1; pthread_mutex_unlock(&ou_crank_mutex);
    unsigned char input[12]; memcpy(input, saved, sizeof input); r = (struct fcam_bridge_result){0}; actual_rc = -ENODATA;
    rc = ou_crank_call(&origin, FCAM_OP_CP_OU_CRANK_CONTROL, input, sizeof input, receipt, sizeof receipt, &r, &actual_rc);
    if (!rc && memcmp(input, saved, sizeof input)) rc = -EPROTO;
    pthread_mutex_lock(&ou_crank_mutex);
    ou_crank_state.model_rc = actual_rc; ou_crank_state.model_committed = actual_rc == 0;
    if (ou_crank_state.model_committed) ou_crank_state.commits++;
    ou_crank_state.ou_result = r; memcpy(ou_crank_state.receipt, receipt, sizeof receipt); ou_crank_state.receipt_fnv1a64 = hash(receipt, sizeof receipt);
    ou_crank_state.ou_generation = u64(receipt+FCAM_CP_OU_CRANK_R_OU_GENERATION);
    ou_crank_state.config_generation = u64(receipt+FCAM_CP_OU_CRANK_R_CONFIG_GENERATION); ou_crank_state.mode = u32(receipt+FCAM_CP_OU_CRANK_R_MODE);
    observed = ou_crank_state; pthread_mutex_unlock(&ou_crank_mutex);
    if (!rc) rc = ou_crank_validate_receipt(&observed, old.last_ou_generation);
    pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.validation_rc = rc; observed = ou_crank_state;
    pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(io.record, "MODEL", "receipt", &observed);
    if (!rc) rc = ou_crank_context_matches(&predecessors, &operation, &io, &guard, request, saved);
    if (!rc) {
        r = (struct fcam_bridge_result){0}; actual_rc = -ENODATA;
        rc = ou_crank_call(&origin, FCAM_OP_STATE, NULL, 0, live, sizeof live, &r, &actual_rc);
        if (!rc) rc = parameter_validate_live(live, &r, operation.model_instance);
        if (!rc && memcmp(live, receipt+FCAM_CP_OU_CRANK_STATE_OFFSET, sizeof live)) rc = -ESTALE;
        pthread_mutex_lock(&ou_crank_mutex);
        ou_crank_state.after_rc = actual_rc; ou_crank_state.after_result = r; memcpy(ou_crank_state.after_state, live, sizeof live);
        ou_crank_state.validation_rc = rc; observed = ou_crank_state;
        pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(io.record, "AFTER", "after_state", &observed);
    }
    if (!rc) rc = ou_crank_context_matches(&predecessors, &operation, &io, &guard, request, saved);
    if (rc) {
        pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.validation_rc = rc; pthread_mutex_unlock(&ou_crank_mutex);
        ou_crank_finish(&guard, io.record, rc, 1); *result = rc; return 1;
    }
    pthread_mutex_lock(&ou_crank_mutex);
    ou_crank_state.verified = ou_crank_state.owned = 1; ou_crank_state.retained_request = request; ou_crank_state.verified_commits++;
    ou_crank_state.last_bank_generation = operation.bank_generation; ou_crank_state.last_crank_generation = operation.crank_generation;
    ou_crank_state.last_movie_generation = operation.movie_generation; ou_crank_state.last_ou_generation = ou_crank_state.ou_generation;
    ou_crank_transport = io; observed = ou_crank_state;
    pthread_mutex_unlock(&ou_crank_mutex); ou_crank_record(io.record, "VERIFIED", NULL, &observed);
    rc = ou_crank_context_matches(&predecessors, &operation, &io, &guard, request, saved);
    if (rc) {
        pthread_mutex_lock(&ou_crank_mutex); ou_crank_state.validation_rc = rc; pthread_mutex_unlock(&ou_crank_mutex);
    } else {
        int freed = -EPROTO; ou_crank_request_free_allowed = 1;
        native_functional_camera_ou_crank_release(destination, request, io.release, io.record, &freed, transaction);
        ou_crank_request_free_allowed = 0; rc = freed;
    }
    ou_crank_finish(&guard, io.record, rc, rc != 0); *result = 0; return 1;
}
