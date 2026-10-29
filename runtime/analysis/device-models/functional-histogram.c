/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-histogram.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local unsigned int dispatching;
static struct functional_histogram_snapshot state;
static uint64_t snapshot_serial;
static struct full_imaging_io transport;
static const struct full_imaging_io *current_io;
static const struct native_cp_state_publication_guard *current_guard;
static void *borrowed_request;
static int *current_result;
static const struct {
    unsigned char request[12], ack[12], canonical[8], notification_header[10];
} wires = {
    {0x0d,0x20,0x48,0x01,0x0c,0,1,0x80,1,1,0,0},
    {0x0d,0x20,0x48,0x11,0x0c,0,1,0x80,0,0,0x59,0},
    {0x48,0x01,4,0,1,1,0,0},
    {0x0d,0x20,0x0c,0x21,0x0a,4,1,0x80,1,0}
};
static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int p = atomic_load(&owner_pid); return p && p != getpid(); }
static int span(const void *p, size_t n) { return p && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static int private_alias(const void *p, size_t n) {
    return overlap(p,n,&state,sizeof state) || overlap(p,n,&snapshot_serial,sizeof snapshot_serial) ||
        overlap(p,n,&transport,sizeof transport) ||
        overlap(p,n,&wires,sizeof wires) || overlap(p,n,&mutex,sizeof mutex) ||
        overlap(p,n,&owner_pid,sizeof owner_pid) || overlap(p,n,&dispatching,sizeof dispatching) ||
        overlap(p,n,&current_io,sizeof current_io) || overlap(p,n,&current_guard,sizeof current_guard) ||
        overlap(p,n,&borrowed_request,sizeof borrowed_request) || overlap(p,n,&current_result,sizeof current_result);
}
/* Under mutex; diagnostic addresses of retired leases deliberately do not own. */
static int live_alias(const void *p, size_t n) {
    if (private_alias(p,n) || (current_io && overlap(p,n,current_io,sizeof *current_io)) ||
        (current_guard && overlap(p,n,current_guard,sizeof *current_guard)) ||
        (current_result && overlap(p,n,current_result,sizeof *current_result)) ||
        (borrowed_request && !state.request_owned && overlap(p,n,borrowed_request,12))) return 1;
    for (unsigned int i = 0; i < FUNCTIONAL_HISTOGRAM_LEASES; i++)
        if (state.leases[i].pointer && overlap(p,n,state.leases[i].pointer,state.leases[i].bytes)) return 1;
    return 0;
}
static void fault(unsigned int role) { state.faults = state.leases[role].faults = 1; }
static void refresh(void) {
    for (unsigned int i = 1; i < FUNCTIONAL_HISTOGRAM_LEASES; i++) {
        struct native_cp_state_publication_lease *l = &state.leases[i];
        const int thread_ok = i == FUNCTIONAL_HISTOGRAM_ACK ? l->free_tid == l->sender_tid :
            l->free_tid == l->receiver_tid;
        l->consumed = l->queued && l->received && l->freed && !l->send_inflight &&
            !l->releasing && !l->faults && !l->send_rc && !l->free_rc && l->receiver_tid && thread_ok;
    }
    state.ack_consumed = state.leases[1].consumed;
    state.notification_consumed = state.leases[2].consumed;
    state.ap_consumed = state.model_complete && state.leases[0].freed && state.ack_consumed &&
        state.notification_consumed && !state.busy && !state.faults;
}
int functional_histogram_owner_init(void) {
    int p = getpid(), expected = 0;
    atomic_compare_exchange_strong(&owner_pid,&expected,p);
    if (atomic_load(&owner_pid) != p) return -EXDEV;
    pthread_mutex_lock(&mutex);
    int rc = state.initialized ? -EALREADY : 0;
    if (!rc) { state.owner_pid = p; state.initialized = state.functional_model = 1; }
    pthread_mutex_unlock(&mutex); return rc;
}
int functional_histogram_bind_queue(unsigned int source) {
    if (inherited()) return -EXDEV;
    if (!source || source == UINT_MAX || source == FUNCTIONAL_HISTOGRAM_SID) return -EINVAL;
    pthread_mutex_lock(&mutex);
    int rc = !state.initialized ? -ENODEV : state.queue_bound && source != state.queue_source ? -ESTALE :
        state.busy ? -EBUSY : state.faults ? -EPROTO : 0;
    if (!rc) { state.queue_bound = 1; state.queue_source = source; }
    pthread_mutex_unlock(&mutex); return rc;
}
void functional_histogram_snapshot(struct functional_histogram_snapshot *out) {
    if (!span(out,sizeof *out) || (uintptr_t)out % _Alignof(struct functional_histogram_snapshot) ||
        private_alias(out,sizeof *out)) return;
    if (inherited()) {
        if (!live_alias(out,sizeof *out))
            *out = (struct functional_histogram_snapshot){.owner_pid = atomic_load(&owner_pid),
                .faults = 1, .functional_model = 1};
        return;
    }
    pthread_mutex_lock(&mutex);
    if (!live_alias(out,sizeof *out)) *out = state;
    pthread_mutex_unlock(&mutex);
}
static void hex(char *out, const unsigned char *p, size_t bytes) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < bytes; i++) { out[2*i] = digits[p[i] >> 4]; out[2*i+1] = digits[p[i] & 15]; }
    out[2*bytes] = 0;
}
static void record(void (*logger)(const char *, const char *), const char *event, unsigned int event_role) {
    if (!logger || inherited()) return;
    pthread_mutex_lock(&mutex);
    if (snapshot_serial == UINT64_MAX) {
        state.faults = 1; refresh(); pthread_mutex_unlock(&mutex);
        logger("FUNCTIONAL_HISTOGRAM_RECORD_FAILED ","snapshot_id_exhausted=1"); return;
    }
    const uint64_t snapshot_id = ++snapshot_serial;
    const struct functional_histogram_snapshot s = state;
    pthread_mutex_unlock(&mutex);
    char tag[96], text[2300], raw[25], canonical[17];
    hex(raw,s.original_wire,sizeof s.original_wire); hex(canonical,s.canonical8,sizeof s.canonical8);
    snprintf(tag,sizeof tag,"FUNCTIONAL_HISTOGRAM_%s ",event);
    snprintf(text,sizeof text,
        "pid=%d tid=%ld cycle=%llu snapshot_id=%llu event_role=%u source=%#x destination=%#x command=%#x bytes=%u original_request=%p raw=%s "
        "original_fnv1a64=%016llx canonical8=%s queue_bound=%u queue_source=%#x "
        "bridge_rc=%d validation_rc=%d used=%zu required=%zu model_result_bytes=%u model_result_fnv1a64=%016llx "
        "model_instance=%llu config_generation=%llu before_config_generation=%llu "
        "frame_generation=%llu before_frame_generation=%llu lease_generation=%llu "
        "notification_bytes=1034 notification_fnv1a64=%016llx selector=%u "
        "Y_fnv1a64=%016llx R_fnv1a64=%016llx G_fnv1a64=%016llx B_fnv1a64=%016llx "
        "request_owned=%u model_complete=%u ACK_AP_consumed=%u notification_AP_consumed=%u AP_consumed=%u "
        "busy=%u guard=%u faults=%u functional_model=1 physical_ASIC_verified=0 "
        "original_CP_FIFO_verified=0 physical_CP_RTOS_verified=0 UI_applied=0 continuous_histogram=0 capture_verified=0",
        s.owner_pid,tid(),(unsigned long long)s.cycle,(unsigned long long)snapshot_id,event_role,
        s.origin.source,s.origin.destination,s.origin.command,
        s.origin.bytes,s.original_request,raw,(unsigned long long)s.origin.wire_fnv1a64,canonical,s.queue_bound,s.queue_source,
        s.bridge_rc,s.validation_rc,s.bridge_result.used,s.bridge_result.required,s.model_result_bytes,
        (unsigned long long)s.model_result_fnv1a64,(unsigned long long)s.model_instance,
        (unsigned long long)s.config_generation,(unsigned long long)s.before_config_generation,
        (unsigned long long)s.frame_generation,(unsigned long long)s.before_frame_generation,
        (unsigned long long)s.lease_generation,(unsigned long long)s.notification_fnv1a64,s.notification_selector,
        (unsigned long long)s.channel_fnv1a64[0],(unsigned long long)s.channel_fnv1a64[1],
        (unsigned long long)s.channel_fnv1a64[2],(unsigned long long)s.channel_fnv1a64[3],
        s.request_owned,s.model_complete,s.ack_consumed,s.notification_consumed,s.ap_consumed,s.busy,s.guard_held,s.faults);
    logger(tag,text);
    for (unsigned int i = 0; i < FUNCTIONAL_HISTOGRAM_LEASES; i++) {
        const struct native_cp_state_publication_lease *l = &s.leases[i];
        snprintf(text,sizeof text,
            "pid=%d cycle=%llu snapshot_id=%llu role=%u destination=%#x source=%#x bytes=%u pointer=%p retained=%u "
            "allocate_attempted=%u allocation_returned=%p allocation_alias=%u allocate_rc=%d "
            "send_started=%u send_inflight=%u queued=%u send_rc=%d received=%u "
            "sender_tid=%ld receiver_tid=%ld free_tid=%ld free_attempted=%u free_rc=%d "
            "freed=%u consumed=%u releasing=%u faults=%u wire_fnv1a64=%016llx",
            s.owner_pid,(unsigned long long)s.cycle,(unsigned long long)snapshot_id,
            l->role,l->destination,l->source,l->bytes,l->pointer,l->pointer != NULL,
            s.allocate_attempted[i],s.allocation_returned[i],s.allocation_alias[i],l->allocate_rc,
            s.send_started[i],l->send_inflight,l->queued,l->send_rc,l->received,l->sender_tid,l->receiver_tid,
            l->free_tid,s.free_attempted[i],l->free_rc,l->freed,l->consumed,l->releasing,l->faults,
            (unsigned long long)l->wire_fnv1a64);
        logger("FUNCTIONAL_HISTOGRAM_LEASE ",text);
    }
}
static int wire_valid(const struct full_imaging_io *io, void *p, unsigned int n,
    unsigned int source, const unsigned char *wire) {
    return io->size(p) == n && io->source(p) == source && !memcmp(p,wire,n);
}
static const unsigned char *lease_wire(unsigned int role) {
    return role == FUNCTIONAL_HISTOGRAM_REQUEST ? state.original_wire :
        role == FUNCTIONAL_HISTOGRAM_ACK ? wires.ack : state.notification_wire;
}
static int find_live(void *pointer) {
    for (unsigned int i = 0; i < FUNCTIONAL_HISTOGRAM_LEASES; i++)
        if (pointer && pointer == state.leases[i].pointer) return (int)i;
    return -1;
}
int functional_histogram_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket) {
    if (inherited()) return -EXDEV;
    if (!pointer) return 0;
    pthread_mutex_lock(&mutex);
    const int found = find_live(pointer);
    if (found < 0) { pthread_mutex_unlock(&mutex); return 0; }
    const unsigned int role = (unsigned int)found;
    struct native_cp_state_publication_lease *l = &state.leases[role];
    if (!span(ticket,sizeof *ticket) || (uintptr_t)ticket % _Alignof(uint64_t) || live_alias(ticket,sizeof *ticket)) {
        pthread_mutex_unlock(&mutex); return -EINVAL;
    }
    if (!role || !state.send_started[role] || (!l->queued && !l->send_inflight) ||
        destination != l->destination || source != l->source || bytes != l->bytes || l->received || state.faults) {
        fault(role); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    if (l->releasing) { pthread_mutex_unlock(&mutex); return -EBUSY; }
    const struct native_cp_state_publication_lease saved = *l;
    const struct full_imaging_io io = transport;
    const unsigned char *wire = lease_wire(role);
    l->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&io,pointer,saved.bytes,saved.source,wire);
    pthread_mutex_lock(&mutex);
    l->releasing = 0;
    if (!valid || state.faults) { fault(role); pthread_mutex_unlock(&mutex); return -EPROTO; }
    l->received = 1; l->receiver_tid = tid(); *ticket = state.cycle;
    refresh(); pthread_mutex_unlock(&mutex); record(io.record,"RECEIVE",role + 1); return 1;
}
static int release_owned(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *),
    int *result, int internal) {
    if (!pointer || !span(result,sizeof *result) || (uintptr_t)result % _Alignof(int) ||
        private_alias(result,sizeof *result)) return 0;
    if (inherited()) {
        if (live_alias(result,sizeof *result)) return 0;
        *result = -EXDEV; return 1;
    }
    pthread_mutex_lock(&mutex);
    if (live_alias(result,sizeof *result)) { pthread_mutex_unlock(&mutex); return 0; }
    const int found = find_live(pointer);
    if (found < 0) { pthread_mutex_unlock(&mutex); return 0; }
    const unsigned int role = (unsigned int)found;
    struct native_cp_state_publication_lease *l = &state.leases[role];
    int rc = 0;
    if (l->releasing) rc = -EBUSY;
    else if (state.free_attempted[role] || l->faults) rc = -EIO;
    else if (!internal && (!ticket || ticket != state.cycle)) rc = -ESTALE;
    else if (!real_free || real_free != transport.release || destination != l->destination ||
        (internal ? role != 0 : role == 0) ||
        (role == 2 ? (!l->received || tid() != l->receiver_tid) : tid() != l->sender_tid) ||
        (role && !l->received)) { fault(role); rc = -EPROTO; }
    if (rc) { pthread_mutex_unlock(&mutex); *result = rc; return 1; }
    const struct native_cp_state_publication_lease saved = *l;
    const struct full_imaging_io io = transport;
    const unsigned char *wire = lease_wire(role);
    l->releasing = 1; state.free_attempted[role] = 1;
    pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&io,pointer,saved.bytes,saved.source,wire);
    rc = valid ? real_free(destination,pointer) : -EPROTO;
    pthread_mutex_lock(&mutex);
    l->releasing = 0; l->free_rc = rc; l->free_tid = tid();
    if (rc) fault(role);
    else { l->pointer = NULL; l->freed = 1; }
    refresh(); pthread_mutex_unlock(&mutex);
    record(logger,role ? "AP_FREE" : "REQUEST_FREE",role + 1); *result = rc; return 1;
}
int functional_histogram_release_cycle(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *), int *result) {
    return release_owned(destination,pointer,ticket,real_free,logger,result,0);
}
static int validate_model(const unsigned char *p, const struct fcam_bridge_result *r) {
    const uint64_t before_config = u64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION);
    const uint64_t before_frame = u64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION);
    const unsigned char *route = p + FCAM_VDF_R_CONFIG;
    if (r->used != FCAM_HIST_RESULT_BYTES || r->required != FCAM_HIST_RESULT_BYTES || r->result_token ||
        !r->model_instance || u32(p + FCAM_VDF_R_ABI) != FCAM_ABI_VERSION ||
        u32(p + FCAM_VDF_R_BYTES) != FCAM_HIST_RESULT_BYTES ||
        u64(p + FCAM_VDF_R_INSTANCE) != r->model_instance ||
        u64(p + FCAM_VDF_R_INPUT_FNV) != fnv(wires.canonical,sizeof wires.canonical) ||
        !u64(p + FCAM_VDF_R_SOURCE_FNV) ||
        u64(p + FCAM_VDF_R_SOURCE_FNV) != u64(p + FCAM_VDF_R_SINK_FNV) ||
        u64(p + FCAM_VDF_R_ACTIVE_BYTES) != UINT64_C(921600) ||
        u32(p + FCAM_VDF_R_WIDTH) != 640 || u32(p + FCAM_VDF_R_HEIGHT) != 480 ||
        u32(p + FCAM_VDF_R_STRIDE) != 1920 || u32(p + FCAM_VDF_R_ENDPOINT) != FCAM_VDF_ENDPOINT ||
        u32(p + FCAM_VDF_R_SELECTED_MASK) != 1 || u32(p + FCAM_VDF_R_COMPLETED_MASK) != 1 ||
        u32(p + FCAM_VDF_R_CLASS) != FCAM_HIST_CLASS || u32(p + FCAM_VDF_R_ENABLED) != 1 ||
        u32(p + FCAM_VDF_R_CONFIG_READBACK) != 1 || u32(p + FCAM_VDF_R_COMMITTED) != 1 ||
        u32(p + FCAM_VDF_R_FRAME_CONSUMED) != 1 || u32(p + FCAM_VDF_R_RETIRED) != 1 ||
        u32(p + FCAM_VDF_R_STATUS) || u32(p + FCAM_VDF_R_RESERVED) ||
        route[0] != 1 || route[1] != 5 || route[2] != 5 || route[4] > 2 || route[13] || route[14] || route[15] ||
        memcmp(p + FCAM_HIST_R_CONFIG,wires.canonical,FCAM_HIST_INPUT_BYTES)) return -EPROTO;
    if (!before_config || before_config == UINT64_MAX || before_frame == UINT64_MAX ||
        u64(p + FCAM_VDF_R_CONFIG_GENERATION) != before_config + 1 ||
        u64(p + FCAM_VDF_R_FRAME_GENERATION) != before_frame + 1 ||
        !u64(p + FCAM_VDF_R_LEASE_GENERATION)) return -ESTALE;
    for (unsigned int c = 0; c < 4; c++) {
        unsigned int peak = 0;
        for (unsigned int i = 0; i < FCAM_HIST_CHANNEL_BINS; i++) {
            const unsigned int value = p[FCAM_HIST_R_BINS + c * FCAM_HIST_CHANNEL_BINS + i];
            if (value > peak) peak = value;
        }
        if (peak != 255) return -EPROTO;
    }
    return 0;
}
static int call_model(const struct fcam_native_origin *origin) {
    struct { unsigned char before[16], data[FCAM_HIST_RESULT_BYTES], after[16]; } out;
    struct { unsigned char before[16], data[FCAM_HIST_INPUT_BYTES], after[16]; } input;
    memset(&out,0xa5,sizeof out); memset(out.data,0,sizeof out.data);
    memset(&input,0xa5,sizeof input); memcpy(input.data,wires.canonical,sizeof input.data);
    struct fcam_bridge_result r = {0};
    const int bridge_rc = fcam_bridge_histogram(origin,input.data,out.data,&r);
    int rc = bridge_rc > 0 ? -EPROTO : bridge_rc;
    for (size_t i = 0; i < sizeof out.before; i++)
        if (out.before[i] != 0xa5 || out.after[i] != 0xa5 ||
            input.before[i] != 0xa5 || input.after[i] != 0xa5) rc = -EOVERFLOW;
    if (memcmp(input.data,wires.canonical,sizeof input.data)) rc = -ESTALE;
    if (!rc) rc = validate_model(out.data,&r);
    pthread_mutex_lock(&mutex);
    state.bridge_rc = bridge_rc; state.validation_rc = rc; state.bridge_result = r;
    state.model_result_bytes = (unsigned int)(r.used < sizeof out.data ? r.used : sizeof out.data);
    memcpy(state.model_result,out.data,sizeof out.data);
    state.model_result_fnv1a64 = fnv(out.data,state.model_result_bytes);
    if (rc) fault(0);
    else {
        state.model_complete = 1; state.model_instance = r.model_instance;
        state.config_generation = u64(out.data + FCAM_VDF_R_CONFIG_GENERATION);
        state.frame_generation = u64(out.data + FCAM_VDF_R_FRAME_GENERATION);
        state.lease_generation = u64(out.data + FCAM_VDF_R_LEASE_GENERATION);
        state.before_config_generation = u64(out.data + FCAM_VDF_R_BEFORE_CONFIG_GENERATION);
        state.before_frame_generation = u64(out.data + FCAM_VDF_R_BEFORE_FRAME_GENERATION);
        memcpy(state.notification_wire,wires.notification_header,sizeof wires.notification_header);
        memcpy(state.notification_wire + 10,out.data + FCAM_HIST_R_BINS,FCAM_HIST_BINS_BYTES);
        state.notification_selector = 1; /* Explicit software four-channel policy, not request-selection semantics. */
        state.notification_fnv1a64 = fnv(state.notification_wire,sizeof state.notification_wire);
        for (unsigned int c = 0; c < 4; c++)
            state.channel_fnv1a64[c] = fnv(out.data + FCAM_HIST_R_BINS + c * 256u,256);
    }
    pthread_mutex_unlock(&mutex); return rc;
}
static int allocate_output(unsigned int role, const struct full_imaging_io *io) {
    pthread_mutex_lock(&mutex);
    const unsigned int bytes = state.leases[role].bytes, destination = state.leases[role].destination;
    state.allocate_attempted[role] = 1;
    pthread_mutex_unlock(&mutex);
    void *p = NULL; const int rc = io->allocate(destination,&p,bytes,1);
    pthread_mutex_lock(&mutex);
    const int alias = p && (!span(p,bytes) || live_alias(p,bytes));
    struct native_cp_state_publication_lease *l = &state.leases[role];
    l->allocate_rc = rc; state.allocation_returned[role] = p; state.allocation_alias[role] = (unsigned int)alias;
    if (p && !alias) l->pointer = p;
    int valid = !rc && p && !alias;
    l->releasing = (unsigned int)valid;
    const unsigned char *wire = lease_wire(role);
    if (!valid) fault(role);
    pthread_mutex_unlock(&mutex);
    if (valid) {
        valid = io->size(p) == bytes;
        if (valid) {
            memcpy(p,wire,bytes); io->set_source(p,FUNCTIONAL_HISTOGRAM_SID);
            valid = wire_valid(io,p,bytes,FUNCTIONAL_HISTOGRAM_SID,wire);
        }
        pthread_mutex_lock(&mutex); l->releasing = 0; if (!valid) fault(role); pthread_mutex_unlock(&mutex);
    }
    return valid ? 0 : rc < 0 ? rc : -EPROTO;
}
static int send_output(unsigned int role, const struct full_imaging_io *io) {
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[role];
    const struct native_cp_state_publication_lease saved = *l;
    if (!l->pointer || l->releasing || state.faults || !state.leases[0].freed ||
        (role == 2 && !state.leases[1].queued)) {
        fault(role); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    const unsigned char *wire = lease_wire(role);
    l->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(io,saved.pointer,saved.bytes,saved.source,wire);
    pthread_mutex_lock(&mutex); l->releasing = 0;
    if (!valid || state.faults) { fault(role); pthread_mutex_unlock(&mutex); return -EPROTO; }
    state.send_started[role] = l->send_inflight = 1; pthread_mutex_unlock(&mutex);
    const int rc = io->send(saved.destination,saved.pointer);
    /* Inline original receive/free may already have destroyed this allocation. */
    pthread_mutex_lock(&mutex);
    l->send_inflight = 0; l->send_rc = rc;
    if (rc) fault(role); else l->queued = 1;
    refresh(); pthread_mutex_unlock(&mutex); record(io->record,"SEND",role + 1); return rc;
}
static void finish(const struct native_cp_state_publication_guard *guard) {
    pthread_mutex_lock(&mutex); const unsigned int held = state.guard_held; state.guard_held = 0;
    pthread_mutex_unlock(&mutex);
    if (held) guard->release();
    pthread_mutex_lock(&mutex);
    state.busy = 0; current_io = NULL; current_guard = NULL; borrowed_request = NULL; current_result = NULL; refresh();
    pthread_mutex_unlock(&mutex);
}
static int dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int *result) {
    const unsigned int bytes = io->size(request);
    if (bytes < 4 || !span(request,bytes) || overlap(result,sizeof *result,request,bytes)) return 0;
    const unsigned char *p = request;
    if (memcmp(p,wires.request,4)) return 0;
    *result = -EINVAL;
    if (bytes != 12) { *result = -EMSGSIZE; return 1; }
    if (!span(guard,sizeof *guard) || (uintptr_t)guard % _Alignof(struct native_cp_state_publication_guard) ||
        overlap(request,bytes,io,sizeof *io) || overlap(request,bytes,guard,sizeof *guard) ||
        overlap(io,sizeof *io,guard,sizeof *guard) || private_alias(request,bytes) || private_alias(io,sizeof *io) ||
        private_alias(guard,sizeof *guard) || !io->source || !io->allocate || !io->release || !io->set_source ||
        !io->send || !guard->reserve || !guard->release || !guard->predecessor_ready) return 1;
    if (memcmp(p,wires.request,12)) { *result = -ENOTSUP; return 1; }
    unsigned char saved[12]; memcpy(saved,request,sizeof saved);
    const unsigned int source = io->source(request);
    pthread_mutex_lock(&mutex);
    int rc = !state.initialized ? -ENODEV : !state.queue_bound ? -ENODATA : source != state.queue_source ? -EPERM :
        state.faults ? -EIO : state.busy ? -EBUSY : state.requests ? -EALREADY : live_alias(request,bytes) ? -EINVAL : 0;
    if (!rc) {
        state.busy = 1; current_io = io; current_guard = guard; borrowed_request = request; current_result = result;
    }
    pthread_mutex_unlock(&mutex);
    if (rc) { *result = rc; return 1; }
    rc = guard->reserve();
    if (rc) { finish(guard); *result = rc < 0 ? rc : -EPROTO; return 1; }
    pthread_mutex_lock(&mutex); state.guard_held = 1; pthread_mutex_unlock(&mutex);
    if (guard->predecessor_ready() != 1) { finish(guard); *result = -ENODATA; return 1; }
    const struct fcam_native_origin origin = {source,destination,FCAM_HIST_COMMAND,bytes,fnv(saved,bytes)};
    pthread_mutex_lock(&mutex);
    state.cycle = 1; state.origin = origin; state.original_request = request;
    memcpy(state.original_wire,saved,sizeof saved); memcpy(state.canonical8,wires.canonical,sizeof wires.canonical);
    transport = *io; pthread_mutex_unlock(&mutex);
    rc = call_model(&origin);
    if (!rc && (guard->predecessor_ready() != 1 || !wire_valid(io,request,bytes,source,saved))) {
        rc = -ESTALE; pthread_mutex_lock(&mutex); state.validation_rc = rc; fault(0); pthread_mutex_unlock(&mutex);
    }
    if (rc) { finish(guard); record(io->record,"REFUSED",0); *result = rc; return 1; }
    pthread_mutex_lock(&mutex);
    state.requests = state.request_owned = 1;
    for (unsigned int i = 0; i < FUNCTIONAL_HISTOGRAM_LEASES; i++) {
        state.leases[i] = (struct native_cp_state_publication_lease){.role = i + 1,
            .bytes = i == 2 ? FUNCTIONAL_HISTOGRAM_NOTIFICATION_BYTES : 12,
            .destination = i ? source : destination, .source = i ? FUNCTIONAL_HISTOGRAM_SID : source,
            .sender_tid = tid(), .pointer = i ? NULL : request,
            .wire_fnv1a64 = fnv(lease_wire(i),i == 2 ? FUNCTIONAL_HISTOGRAM_NOTIFICATION_BYTES : 12)};
    }
    pthread_mutex_unlock(&mutex);
    int free_rc = -EPROTO;
    release_owned(destination,request,0,io->release,io->record,&free_rc,1); rc = free_rc;
    if (!rc) rc = allocate_output(1,io);
    if (!rc) rc = allocate_output(2,io);
    if (!rc) rc = send_output(1,io);
    if (!rc) rc = send_output(2,io);
    finish(guard); record(io->record,rc ? "FAULT" : "COMPLETE",0); *result = 0; return 1;
}
int functional_histogram_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_HISTOGRAM_SID || !span(request,12) ||
        !span(io,sizeof *io) || (uintptr_t)io % _Alignof(struct full_imaging_io) || private_alias(io,sizeof *io) || !io->size ||
        !span(result,sizeof *result) || (uintptr_t)result % _Alignof(int) || private_alias(result,sizeof *result) ||
        overlap(result,sizeof *result,request,12) || overlap(result,sizeof *result,io,sizeof *io) ||
        (guard && (!span(guard,sizeof *guard) || overlap(result,sizeof *result,guard,sizeof *guard)))) return 0;
    if (inherited()) {
        if (live_alias(result,sizeof *result)) return 0;
        *result = -EXDEV; return 1;
    }
    pthread_mutex_lock(&mutex);
    if (live_alias(result,sizeof *result)) { pthread_mutex_unlock(&mutex); return 0; }
    const int owned = find_live(request) >= 0;
    pthread_mutex_unlock(&mutex);
    if (owned) { *result = -EALREADY; return 1; }
    if (dispatching) { *result = -EBUSY; return 1; }
    dispatching = 1; const int handled = dispatch(destination,request,io,guard,result); dispatching = 0; return handled;
}
#ifdef HOST_TEST
void functional_histogram_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void functional_histogram_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
void *functional_histogram_test_state_address(void) { return &state; }
const void *functional_histogram_test_constant_address(void) { return &wires; }
void *functional_histogram_test_serial_address(void) { return &snapshot_serial; }
void functional_histogram_test_exhaust_serial(void) {
    pthread_mutex_lock(&mutex); snapshot_serial = UINT64_MAX; pthread_mutex_unlock(&mutex);
}
#endif
