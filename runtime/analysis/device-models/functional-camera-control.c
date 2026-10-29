/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-camera-control.h"
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
    if (state.mode1_requests && !state.mode1_complete) return 0;
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
    state.start_complete = state.mode1_complete = state.business_ready = 0;
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
    state.mode1_complete = state.mode1_requests && s[MODE_REQUEST].freed &&
        s[MODE_ACK].consumed && (state.mode1_ack_only || s[FULL_NOTICE].consumed) && !state.faults && !state.busy;
    if (state.mode1_complete && completed_cycle != state.mode1_cycle_id) {
        completed_cycle = state.mode1_cycle_id; state.mode1_cycles_completed++;
        if (state.mode1_ack_only) state.mode1_ack_only_completed++;
    }
    if (s[FULL_NOTICE].consumed && !state.notification_ap_consumed) state.full_notifications_consumed++;
    state.notification_queued = s[FULL_NOTICE].queued;
    state.notification_received = s[FULL_NOTICE].received;
    state.notification_ap_consumed = s[FULL_NOTICE].consumed;
    if (state.faults) return;
    if (s[FULL_NOTICE].consumed) state.shadow_generation = state.published_generation;
    if (state.mode1_ack_only && state.mode1_complete) state.phase = FUNCTIONAL_CAMERA_CONTROL_MODE_ACK_CONSUMED;
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
        (unsigned long long)s.mode1_cycle_id, s.mode1_cycle_generation, s.mode1_ack_only, s.mode1_requests, s.mode1_cycles_completed,
        s.mode1_ack_only_requests, s.mode1_ack_only_completed, s.full_notifications_queued, s.full_notifications_consumed,
        s.notification_mode, s.business_ready);
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
    int valid = l.pointer && !state.faults; pthread_mutex_unlock(&mutex);
    if (valid) valid = io->size(l.pointer) == l.bytes && io->source(l.pointer) == l.source && !memcmp(l.pointer, expected, l.bytes);
    pthread_mutex_lock(&mutex);
    valid = valid && same_lease(index, &l, cycle) && !state.leases[index].releasing && !started[index];
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
    if (mode && bytes == 12 && u32(p + 8) != 1) return 0;
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
        (start ? !state.start_requests : state.start_complete && state.model_initialized);
    if (ready && mode && (state.mode1_cycle_id == UINT64_MAX || state.mode1_requests == UINT_MAX ||
        state.mode1_cycles_completed == UINT_MAX || state.mode1_ack_only_requests == UINT_MAX ||
        state.mode1_ack_only_completed == UINT_MAX || state.full_notifications_queued == UINT_MAX ||
        state.full_notifications_consumed == UINT_MAX)) {
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
        if (!publish && (!state.notification_ap_consumed || !state.leases[FULL_NOTICE].consumed ||
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
         (publish ? full.generation.published_generation == state.config_generation &&
                    state.config_generation > state.shadow_generation :
          state.config_generation == state.shadow_generation && state.notification_ap_consumed));
    if (!ready) { pthread_mutex_unlock(&mutex); finish(guard); *result = -ESTALE; return 1; }
    if (mode) {
        state.mode1_cycle_id++; state.mode1_cycle_generation = (unsigned int)state.config_generation;
        state.mode1_ack_only = !publish; state.mode1_complete = 0;
        for (unsigned int i = MODE_REQUEST; i <= (publish ? FULL_NOTICE : MODE_ACK); i++) {
            memset(&state.leases[i], 0, sizeof state.leases[i]);
            memset(wires[i], 0, sizeof wires[i]); started[i] = 0;
            state.lease_cycle_id[i] = state.mode1_cycle_id;
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
    else {
        state.mode1_requests++; state.notification_mode = 1;
        if (!publish) state.mode1_ack_only_requests++;
    }
    pthread_mutex_unlock(&mutex);
    rc = send_message(ack, io);
    if (!rc && publish) rc = send_message(FULL_NOTICE, io);
    if (!rc) { int freed; release_owned(destination, request, io->release, io->record, &freed, REQUEST_FREE, 0); }
    else cleanup_messages(ack, io);
    finish(guard); record(io->record, rc ? "FAULT" : "COMMIT", ack); *result = 0; return 1;
}
#ifdef HOST_TEST
void native_functional_camera_control_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void native_functional_camera_control_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
