/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-cp-zoom.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local int active;
static struct functional_cp_zoom_snapshot state;
static struct cp_parameter_state *parameters;

static int span(const void *p, size_t n) { return p && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlaps(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static int inherited(void) { int p = atomic_load(&owner_pid); return p && p != getpid(); }
static int same_guard(const struct cp_start_state_guard *a, const struct cp_start_state_guard *b) {
    return a->owner_pid == b->owner_pid && a->sequence_before == b->sequence_before &&
        a->sequence_after == b->sequence_after && a->source_origin == b->source_origin && a->quiescent == b->quiescent;
}
static long tid(void) { return syscall(SYS_gettid); }
static uint64_t hash(const unsigned char *p) {
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < CP_PARAMETER_ZOOM_BYTES; i++) { h ^= p[i]; h *= UINT64_C(1099511628211); }
    return h;
}
static void hex(const unsigned char *p, size_t n, char *out) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) { out[2*i] = digits[p[i] >> 4]; out[2*i+1] = digits[p[i] & 15]; }
    out[2*n] = 0;
}
int functional_cp_zoom_owner_init(struct cp_parameter_state *owner) {
    unsigned char byte;
    int rc = cp_parameter_state_read(owner, 0, &byte, 1);
    if (rc && rc != -ENODATA) return rc;
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&owner_pid, &expected, pid);
    if (atomic_load(&owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&mutex);
    if (state.initialized) rc = -EALREADY;
    else { parameters = owner; state.owner_pid = pid; state.initialized = 1; rc = 0; }
    pthread_mutex_unlock(&mutex); return rc;
}
void functional_cp_zoom_snapshot(struct functional_cp_zoom_snapshot *out) {
    if (!span(out, sizeof(*out)) || (uintptr_t)out % _Alignof(struct functional_cp_zoom_snapshot)) return;
    if (inherited()) {
        *out = (struct functional_cp_zoom_snapshot){.owner_pid = atomic_load(&owner_pid), .faults = 1};
        return;
    }
    pthread_mutex_lock(&mutex);
    if (!parameters || !overlaps(out, sizeof(*out), parameters, sizeof(*parameters))) *out = state;
    pthread_mutex_unlock(&mutex);
}
static void record(void (*logger)(const char *, const char *)) {
    if (!logger) return;
    struct functional_cp_zoom_snapshot s = {0}; functional_cp_zoom_snapshot(&s);
    char wire[25], fields[21], text[1400]; hex(s.wire, 12, wire); hex(s.data.fields, 10, fields);
    snprintf(text, sizeof text,
        "pid=%d tid=%ld sender_tid=%ld free_tid=%ld source=%#x destination=%#x caller=%#x bytes=12 raw=%s "
        "wire_fnv1a=%016llx body=%02x,%02x,%02x,%02x "
        "image_offsets=69c,698,6a0,6a4 widths=4,1,4,1 readback=%s knownmask=%#x "
        "count=%llu source_sequence=%llu source_origin=%u config_consumed=%u oneway_consumed=%u "
        "data_rc=%d original_free_attempted=%u original_free_rc=%d original_freed=%u "
        "original_request=%p retained_request=%p busy=%u guard_held=%u faults=%u "
        "provenance=public-CP354768 functional_model=1 original_CP=0 physical_zoom_verified=0 "
        "applied=0 published=0 generation=0 capture=0 ack_allocated=0 ack_sent=0",
        s.owner_pid, tid(), s.sender_tid, s.free_tid, s.metadata_source, s.destination, s.caller, wire,
        (unsigned long long)s.wire_fnv1a64, s.wire[8], s.wire[9], s.wire[10], s.wire[11], fields,
        (unsigned int)s.data.known_mask, (unsigned long long)s.data.count,
        (unsigned long long)s.data.source_sequence, (unsigned int)s.data.source_origin,
        s.config_consumed, s.oneway_consumed, s.data_rc, s.free_attempted, s.free_rc, s.request_freed,
        s.original_request, s.retained_request, s.busy, s.guard_held, s.faults);
    logger("FUNCTIONAL_CP_ZOOM ", text);
}
static void finish(const struct native_cp_state_publication_guard *guard) {
    pthread_mutex_lock(&mutex); unsigned int held = state.guard_held; state.guard_held = 0;
    pthread_mutex_unlock(&mutex);
    if (held) guard->release();
    pthread_mutex_lock(&mutex); state.busy = 0; pthread_mutex_unlock(&mutex); active = 0;
}
int functional_cp_zoom_release(unsigned int destination, void *request, int (*release)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result) {
    (void)release; (void)logger;
    if (!span(result, sizeof(*result)) || (uintptr_t)result % _Alignof(int) || !request ||
        overlaps(result, sizeof(*result), request, CP_PARAMETER_ZOOM_BYTES)) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&mutex);
    int owned = state.retained_request == request;
    if (parameters && overlaps(result, sizeof(*result), parameters, sizeof(*parameters))) {
        pthread_mutex_unlock(&mutex); return 0;
    }
    if (owned) *result = destination != state.destination ? -EPROTO : state.busy ? -EBUSY :
        state.faults ? -EIO : -EALREADY;
    pthread_mutex_unlock(&mutex); return owned;
}
int functional_cp_zoom_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, const struct cp_start_state_guard *data_guard,
    int enabled, int *result) {
    if (enabled != 1 || destination != CP_PARAMETER_BATCH_TARGET || !span(request, 12) ||
        !span(io, sizeof(*io)) || (uintptr_t)io % _Alignof(struct full_imaging_io) ||
        !span(result, sizeof(*result)) || (uintptr_t)result % _Alignof(int) ||
        overlaps(result, sizeof(*result), request, 12) || overlaps(result, sizeof(*result), io, sizeof(*io)) ||
        (guard && overlaps(result, sizeof(*result), guard, sizeof(*guard))) ||
        (data_guard && overlaps(result, sizeof(*result), data_guard, sizeof(*data_guard))) ||
        (guard && overlaps(io, sizeof(*io), guard, sizeof(*guard))) ||
        (data_guard && overlaps(io, sizeof(*io), data_guard, sizeof(*data_guard))) ||
        (guard && data_guard && overlaps(guard, sizeof(*guard), data_guard, sizeof(*data_guard)))) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&mutex);
    int duplicate = state.retained_request == request;
    struct cp_parameter_state *owner = parameters;
    pthread_mutex_unlock(&mutex);
    if (owner && overlaps(result, sizeof(*result), owner, sizeof(*owner))) return 0;
    if (active) { *result = -EBUSY; return 1; }
    if (duplicate) { *result = 0; return 1; } /* The still-owned original must not be consumed twice. */
    if (!io->size) return 0;
    active = 1;
    unsigned int bytes = io->size(request);
    if (bytes < 4 || !span(request, bytes)) { active = 0; return 0; }
    const unsigned char *p = request;
    if (p[0] != 5 || p[2] != 1 || p[3] != 0x40) { active = 0; return 0; }
    *result = -EINVAL;
    if (bytes != CP_PARAMETER_ZOOM_BYTES) { *result = -EMSGSIZE; active = 0; return 1; }
    if (!owner || !span(guard, sizeof(*guard)) || !span(data_guard, sizeof(*data_guard)) ||
        (uintptr_t)guard % _Alignof(struct native_cp_state_publication_guard) ||
        (uintptr_t)data_guard % _Alignof(struct cp_start_state_guard) ||
        !guard->reserve || !guard->release || !guard->predecessor_ready || !io->source || !io->release ||
        overlaps(request, bytes, owner, sizeof(*owner)) || overlaps(request, bytes, io, sizeof(*io)) ||
        overlaps(request, bytes, guard, sizeof(*guard)) || overlaps(request, bytes, data_guard, sizeof(*data_guard)) ||
        overlaps(owner, sizeof(*owner), data_guard, sizeof(*data_guard)) ||
        overlaps(owner, sizeof(*owner), guard, sizeof(*guard)) || overlaps(owner, sizeof(*owner), io, sizeof(*io))) {
        active = 0; return 1;
    }
    unsigned char saved[CP_PARAMETER_ZOOM_BYTES]; memcpy(saved, request, sizeof saved);
    if (saved[8] || saved[10]) { *result = -ENOTSUP; active = 0; return 1; }
    unsigned int source = io->source(request);
    if (source != CP_PARAMETER_BATCH_SOURCE) { *result = -EPERM; active = 0; return 1; }
    pthread_mutex_lock(&mutex);
    int rc = !state.initialized ? -ENODATA : state.faults ? -EIO : state.busy ? -EBUSY :
        state.requests == UINT_MAX ? -EOVERFLOW : 0;
    if (!rc) state.busy = 1;
    pthread_mutex_unlock(&mutex);
    if (rc) { *result = rc; active = 0; return 1; }
    rc = guard->reserve();
    if (rc) { finish(guard); *result = rc; return 1; }
    pthread_mutex_lock(&mutex); state.guard_held = 1; pthread_mutex_unlock(&mutex);
    struct cp_start_state_guard g = *data_guard;
    if (guard->predecessor_ready() != 1) rc = -ENODATA;
    if (!rc && (io->size(request) != bytes || io->source(request) != source ||
        memcmp(request, saved, bytes) || !same_guard(data_guard, &g) || guard->predecessor_ready() != 1)) rc = -ESTALE;
    struct cp_parameter_zoom_readback data = {0}, readback = {0};
    if (!rc) rc = cp_parameter_state_consume_zoom(owner, data_guard, source, destination, saved, bytes, &data);
    pthread_mutex_lock(&mutex); state.data_rc = rc; pthread_mutex_unlock(&mutex);
    if (rc) { finish(guard); *result = rc; return 1; }
    pthread_mutex_lock(&mutex);
    state = (struct functional_cp_zoom_snapshot){.owner_pid = getpid(), .initialized = 1,
        .busy = 1, .guard_held = 1, .requests = state.requests + 1, .config_consumed = 1,
        .metadata_source = source, .destination = destination, .caller = data.caller,
        .sender_tid = tid(), .data = data, .original_request = request, .retained_request = request,
        .wire_fnv1a64 = hash(saved)};
    memcpy(state.wire, saved, sizeof saved); pthread_mutex_unlock(&mutex);
    rc = cp_parameter_state_read_zoom(owner, data_guard, &readback);
    if (!rc && (memcmp(data.fields, readback.fields, sizeof data.fields) || data.count != readback.count ||
        data.known_mask != readback.known_mask || io->size(request) != bytes ||
        io->source(request) != source || memcmp(request, saved, bytes) ||
        !same_guard(data_guard, &g) || guard->predecessor_ready() != 1)) rc = -ESTALE;
    pthread_mutex_lock(&mutex); state.data_rc = rc;
    if (rc) state.faults = 1;
    else state.free_attempted = 1;
    pthread_mutex_unlock(&mutex);
    if (!rc) {
        rc = io->release(destination, request);
        pthread_mutex_lock(&mutex); state.free_rc = rc; state.free_tid = tid();
        if (rc) state.faults = 1;
        else { state.retained_request = NULL; state.request_freed = state.oneway_consumed = 1; }
        pthread_mutex_unlock(&mutex);
    }
    finish(guard); record(io->record); *result = 0; return 1;
}
