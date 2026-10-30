/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-face-source-snapshot.h"
#include <errno.h>
#include <limits.h>
#include <fcntl.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define SNAP_PAGE 4096u
#define SNAP_FNV_SEED UINT64_C(0xcbf29ce484222325)
#define SNAP_FNV_PRIME UINT64_C(0x100000001b3)
static int64_t snap_tid(void) { return syscall(SYS_gettid); }
static uint64_t snap_le(const unsigned char *p, size_t n) {
    uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}
static void snap_put(unsigned char *p, uint64_t v, size_t n) {
    for (size_t i = 0; i < n; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static uint64_t snap_fnv(const void *data, size_t n) {
    const unsigned char *p = data; uint64_t v = SNAP_FNV_SEED;
    for (size_t i = 0; i < n; ++i) v = (v ^ p[i]) * SNAP_FNV_PRIME;
    return v;
}
static int snap_span_equal(const struct functional_face_ap_span *a, const struct functional_face_ap_span *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->bytes == b->bytes;
}
static int snap_cp_equal(const struct functional_face_dmm_descriptor *a, const struct functional_face_dmm_descriptor *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle && a->epoch == b->epoch &&
        a->owner == b->owner && a->reference == b->reference && a->logical == b->logical &&
        a->registration == b->registration && a->host_view == b->host_view && a->bytes == b->bytes &&
        a->mapped_bytes == b->mapped_bytes;
}
static int snap_birth_equal(const struct functional_face_ap_birth *a, const struct functional_face_ap_birth *b) {
    return a->unit == b->unit && a->handle == b->handle && a->observations == b->observations &&
        a->ambiguous == b->ambiguous && a->any_free_observed == b->any_free_observed &&
        a->reply_source == b->reply_source && a->observation_sequence == b->observation_sequence;
}
static int snap_birth(const struct functional_face_source_snapshot_config *c,
    const struct functional_face_ap_observer *o, int allow_own_free) {
    struct functional_face_ap_birth fact = {0};
    int rc = functional_face_ap_observed_birth(o, c->owner_tid, c->saved_source.unit, c->saved_source.handle, &fact);
    if (rc) return rc;
    if (allow_own_free) fact.any_free_observed = c->birth.any_free_observed;
    return snap_birth_equal(&fact, &c->birth) ? 0 : -ESTALE;
}
static int snap_shape(const struct functional_face_source_snapshot_config *c) {
    static const size_t sizes[3] = {0x64000, 0xc800, 0xd100};
    const struct functional_face_ap_span *a = &c->saved_source;
    const struct functional_face_dmm_descriptor *d = &c->destination;
    if (a->domain || a->unit < 0x1d9 || a->unit > 0x1db || a->handle > 0x7fff ||
        (a->handle & 0x3ffu) == 0x3ffu || !((a->handle >> 10) & 31u) || !a->epoch || !a->owner ||
        a->bytes != sizes[a->unit - 0x1d9] || !c->relation || !c->extent_id ||
        c->generation != ((a->handle >> 10) & 31u) || !c->producer_owner) return -ESTALE;
    const struct functional_face_proc_unit *born = &c->born;
    if (born->handle != a->handle || born->unit != a->unit || born->generation != c->generation ||
        born->relation != c->relation || born->extent_id != c->extent_id || born->extent_id > 0xffffu ||
        born->segments != 1 || !born->address || born->bytes != a->bytes ||
        born->bytes > UINT64_MAX - born->address || born->owners != 1 || born->opens || born->shares || born->state != 1)
        return -ESTALE;
    size_t rounded = (a->bytes + SNAP_PAGE - 1) & ~(size_t)(SNAP_PAGE - 1);
    if (d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || d->unit != a->unit || !d->epoch ||
        !((d->handle >> 10) & 31u) ||
        d->handle != (0x8000u | (((d->handle >> 10) & 31u) << 10) | (a->unit - 0x1d9 + 2)) ||
        d->owner != c->producer_owner || d->reference || !d->logical || !d->registration || !d->host_view ||
        (d->host_view & (SNAP_PAGE - 1)) || d->bytes != a->bytes || d->mapped_bytes != rounded ||
        rounded > UINTPTR_MAX - d->host_view) return -ESTALE;
    if (!c->frame || (c->frame & 15u) || c->frame > UINTPTR_MAX - FCAM_FACE_SNAPSHOT_FRAME_BYTES ||
        c->api_pointer != c->frame + 0xb8 || snap_le(c->raw_api40, 8) != c->frame + 0x68 ||
        snap_le(c->raw_api40 + 8, 8) != c->frame + 0x70 || snap_le(c->raw_api40 + 16, 4) != a->bytes ||
        snap_le(c->raw_api40 + 20, 4) != 1 || !snap_le(c->raw_api40 + 24, 8) ||
        snap_le(c->raw_api40 + 32, 8) != c->frame + 0x60 ||
        snap_le(c->ap_descriptor, 4) != a->handle || snap_le(c->ap_descriptor + 4, 4) ||
        snap_le(c->cp_descriptor, 4) != d->handle || snap_le(c->cp_descriptor + 4, 4)) return -ESTALE;
    if (!c->observer || !c->original_command || !c->read_current_metadata || c->original_caller_verified != 1) return -ENODATA;
    if (c->birth.observations != 1 || c->birth.ambiguous || c->birth.any_free_observed ||
        c->birth.unit != a->unit || c->birth.handle != a->handle || !c->birth.observation_sequence ||
        c->birth.reply_source != FUNCTIONAL_FACE_AP_DMM || c->observer->active ||
        c->observer->sequence < c->birth.observation_sequence) return -ESTALE;
    return snap_birth(c, c->observer, 0);
}
static int snap_enter(struct functional_face_source_snapshot *s) {
    if (!s || !s->initialized) return -ENODATA;
    if (s->config.owner_pid != getpid() || s->config.owner_tid != snap_tid()) return -ECHILD;
    unsigned int expected = 0;
    if (!atomic_compare_exchange_strong_explicit(&s->busy, &expected, 1, memory_order_acq_rel, memory_order_acquire)) return -EBUSY;
    if (s->faulted) { atomic_store_explicit(&s->busy, 0, memory_order_release); return -EIO; }
    return 0;
}
static int snap_leave(struct functional_face_source_snapshot *s, int rc, int saved_errno) {
    s->last_error = rc; atomic_store_explicit(&s->busy, 0, memory_order_release); errno = saved_errno; return rc;
}
static int snap_fault(struct functional_face_source_snapshot *s, int rc, int uncertain) {
    s->faulted = 1; s->uncertain |= (uint32_t)uncertain;
    s->provider_may_retain = s->uncertain || s->owner_live || s->open_live || s->owned_snapshot != NULL;
    return rc < 0 ? rc : -EPROTO;
}
/* Same complete ticket predicate as native AP, without its writer capability. */
static int snap_ticket(struct functional_face_source_snapshot *s, uint32_t op,
    const struct functional_face_ap_observer *o, int *status) {
    unsigned char expected[40] = {0};
    uint32_t unit = op == 0x21 ? s->config.saved_source.unit : 0;
    snap_put(expected, op, 2); snap_put(expected + 4, unit, 4);
    snap_put(expected + 8, s->config.saved_source.handle, 4);
    if (op == 0x24) snap_put(expected + 12, UINT32_MAX, 4);
    if (op == 0x23) snap_put(expected + 20, o->source & 0xffffu, 2);
    if (o->owner_pid != s->config.owner_pid || o->sender_tid != s->config.owner_tid || !o->sequence ||
        o->sequence <= s->last_sequence || o->active || o->dropped || o->op != op || o->unit != unit ||
        o->handle != s->config.saved_source.handle || !o->source || o->source == UINT32_MAX ||
        o->source == FUNCTIONAL_FACE_AP_DMM || !o->request || !o->reply || o->send_seen != 1 ||
        o->send_result || o->received != 1 || o->free_attempts != 1 || o->free_result ||
        o->reply_source != FUNCTIONAL_FACE_AP_DMM || o->reply_bytes != 40 ||
        memcmp(o->request_wire, expected, 40) || snap_le(o->reply_wire, 2) != (op | 0x8000u)) return -EPROTO;
    int rc = snap_birth(&s->config, o, op == 0x23);
    if (rc) return rc;
    *status = (int)(int16_t)snap_le(o->reply_wire + 2, 2);
    s->last_sequence = o->sequence;
    return 0;
}
static int snap_command(struct functional_face_source_snapshot *s, uint32_t op) {
    unsigned int i = op == 0x21 ? 0 : op == 0x24 ? 1 : op == 0x25 ? 2 : 3;
    struct functional_face_ap_observer *o = &s->operations[i]; int status = 0;
    int helper = s->config.original_command(s->config.command_context, op,
        s->config.saved_source.unit, s->config.saved_source.handle, o);
    int rc = snap_ticket(s, op, o, &status);
    if (rc) return snap_fault(s, rc, 1);
    /* Negative Open with a complete ticket has no Open lease; retain the Share
     * until one evidenced extra-owner Free. Other negative refs are uncertain. */
    if (status) {
        if (op == 0x24 && status < 0) return -EREMOTEIO;
        return snap_fault(s, -EREMOTEIO, 1);
    }
    if (helper) return snap_fault(s, helper, 1);
    return 0;
}
static int snap_metadata(struct functional_face_source_snapshot *s, unsigned int stage, uint32_t owners, uint32_t opens) {
    struct functional_face_proc_unit *current = &s->metadata[stage];
    ++s->metadata_calls;
    int rc = s->config.read_current_metadata(s->config.metadata_context,
        s->config.saved_source.unit, s->config.saved_source.handle, current);
    if (rc) return rc < 0 ? rc : -EPROTO;
    const struct functional_face_proc_unit *born = &s->config.born;
    if (stage == 0) {
        if (current->opens >= 255) return -EOVERFLOW;
        opens = current->opens;
    }
    if (current->handle != born->handle || current->unit != born->unit || current->generation != born->generation ||
        current->relation != born->relation || current->extent_id != born->extent_id ||
        current->segments != born->segments || current->address != born->address || current->bytes != born->bytes ||
        current->owners != owners || current->opens != opens || current->shares || current->state != (opens ? 2u : 1u))
        return -ESTALE;
    if (stage == 0) s->baseline_opens = opens;
    return 0;
}
static int snap_current(struct functional_face_source_snapshot *s) {
    struct functional_face_dmm_descriptor current;
    int rc = functional_face_runtime_lookup_creator(s->config.producer_owner, s->config.saved_source.unit, &current);
    if (rc) return rc;
    if (!snap_cp_equal(&current, &s->config.destination)) return -ESTALE;
    struct functional_face_registry_inspection inspected;
    struct functional_face_dmm_descriptor original = s->config.destination;
    original.logical = original.registration = 0;
    rc = functional_face_registry_inspect_span(&s->config.destination, &inspected);
    if (!rc && (!snap_cp_equal(&inspected.original, &original) ||
        !snap_cp_equal(&inspected.current, &s->config.destination))) rc = -ESTALE;
    return rc;
}
static long snap_entry(struct functional_face_source_snapshot *s, int fd, uintptr_t page, uint64_t *entry) {
    for (unsigned int tries = 0; tries < 4; ++tries) {
#ifdef FCAM_HOST_TEST
        if (s->config.read_pagemap) {
            long n = s->config.read_pagemap(s->config.test_context, page, entry);
            if (n == -EINTR) continue;
            return n;
        }
#else
        (void)s;
#endif
        uint64_t index = (uint64_t)(page / SNAP_PAGE);
        if (index > (uint64_t)INT64_MAX / 8) return -EOVERFLOW;
        ssize_t n = pread(fd, entry, 8, (off_t)(index * 8));
        if (n < 0 && errno == EINTR) continue;
        return n < 0 ? -errno : (long)n;
    }
    return -EINTR;
}
static int snap_pages(struct functional_face_source_snapshot *s, uint64_t *out) {
    int fd = -1, rc = 0;
#ifdef FCAM_HOST_TEST
    if (!s->config.read_pagemap)
#endif
    {
        for (unsigned int tries = 0; tries < 4; ++tries) {
            fd = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
            if (fd >= 0 || errno != EINTR) break;
        }
        if (fd < 0) rc = -errno;
    }
    size_t count = s->cp_count + s->sdk_count;
    for (size_t i = 0; !rc && i < count; ++i) {
        uintptr_t page = i < s->cp_count ? s->config.destination.host_view + i * SNAP_PAGE :
            (s->config.frame & ~(uintptr_t)(SNAP_PAGE - 1)) + (i - s->cp_count) * SNAP_PAGE;
        uint64_t first = 0, second = 0;
        long a = snap_entry(s, fd, page, &first), b = snap_entry(s, fd, page, &second);
        uint64_t pfn = first & ((UINT64_C(1) << 55) - 1);
        if (a != 8 || b != 8) rc = a < 0 ? (int)a : b < 0 ? (int)b : -EIO;
        else if (first != second) rc = -ESTALE;
        else if (!(first & (UINT64_C(1) << 63)) || (first & (UINT64_C(1) << 62)) || !pfn) rc = -EACCES;
        else if (pfn > (UINT64_MAX - SNAP_PAGE) / SNAP_PAGE) rc = -EOVERFLOW;
        else {
            out[i] = pfn * SNAP_PAGE;
            for (size_t j = 0; j < i; ++j) if (out[j] == out[i]) rc = -EADDRINUSE;
            if (s->physical && out[i] < s->physical + s->config.saved_source.bytes &&
                s->physical < out[i] + SNAP_PAGE) rc = -EADDRINUSE;
        }
    }
    s->pagemap_close_error = 0;
    if (fd >= 0 && close(fd)) { s->pagemap_close_error = -errno; if (!rc) rc = s->pagemap_close_error; }
    s->pagemap_error = rc;
    return rc;
}
static int snap_observe_mapping(struct functional_face_source_snapshot *s, int compare) {
    uint64_t actual[FCAM_FACE_SNAPSHOT_MAX_CP_PAGES + FCAM_FACE_SNAPSHOT_MAX_SDK_PAGES];
    int rc = snap_current(s);
    if (!rc) rc = snap_pages(s, actual);
    if (!rc && compare && (memcmp(actual, s->cp_pages, s->cp_count * 8u) ||
        memcmp(actual + s->cp_count, s->sdk_pages, s->sdk_count * 8u))) rc = -ESTALE;
    if (!rc && !compare) {
        memcpy(s->cp_pages, actual, s->cp_count * 8u);
        memcpy(s->sdk_pages, actual + s->cp_count, s->sdk_count * 8u);
    }
    return rc;
}
static void snap_packet(struct functional_face_source_snapshot *s) {
    const struct functional_face_source_snapshot_config *c = &s->config;
    unsigned char *p = s->packet;
    snap_put(p, FCAM_FACE_SNAPSHOT_VERSION, 4); snap_put(p + 4, c->saved_source.unit, 4);
    snap_put(p + 8, c->saved_source.handle, 4); snap_put(p + 12, c->destination.handle, 4);
    snap_put(p + 16, c->saved_source.bytes, 4); snap_put(p + 20, s->cp_count, 4); snap_put(p + 24, s->sdk_count, 4);
    snap_put(p + 28, FCAM_FACE_SNAPSHOT_REFERENCE_FACTS, 4); snap_put(p + 32, c->saved_source.epoch, 8);
    snap_put(p + 40, c->destination.epoch, 8); snap_put(p + 48, c->destination.registration, 8);
    snap_put(p + 56, c->producer_owner, 8); snap_put(p + 64, s->physical, 8);
    snap_put(p + 72, snap_fnv(c->raw_api40, 40), 8); snap_put(p + 80, c->birth.observation_sequence, 8);
    snap_put(p + 88, s->operations[0].sequence, 8); snap_put(p + 96, s->operations[1].sequence, 8);
    snap_put(p + 104, c->relation, 4); snap_put(p + 108, c->generation, 4); snap_put(p + 112, c->extent_id, 4);
    snap_put(p + 116, (uint32_t)c->owner_pid, 4); snap_put(p + 120, (uint32_t)c->owner_tid, 4);
    memcpy(p + 128, s->operations[0].request_wire, 40); memcpy(p + 168, s->operations[0].reply_wire, 40);
    memcpy(p + 208, s->operations[1].request_wire, 40); memcpy(p + 248, s->operations[1].reply_wire, 40);
    snap_put(p + 288, c->frame, 8); snap_put(p + 296, c->api_pointer, 8);
    memcpy(p + 304, c->raw_api40, 40); memcpy(p + 344, c->ap_descriptor, 8); memcpy(p + 352, c->cp_descriptor, 8);
    for (uint32_t i = 0; i < s->cp_count; ++i) snap_put(p + 360 + 8 * i, s->cp_pages[i], 8);
    for (uint32_t i = 0; i < s->sdk_count; ++i) snap_put(p + 360 + 8 * (s->cp_count + i), s->sdk_pages[i], 8);
    s->packet_bytes = FCAM_FACE_SNAPSHOT_BASE_BYTES + 8u * (s->cp_count + s->sdk_count);
}
static int snap_balance(struct functional_face_source_snapshot *s) {
    int rc = snap_metadata(s, 3, 2, s->baseline_opens + (s->open_live ? 1 : 0));
    if (!rc && s->open_live) {
        if (s->close_attempted) rc = -EIO;
        else {
            s->close_attempted = 1; rc = snap_command(s, 0x25);
            if (!rc) { s->open_live = 0; rc = snap_metadata(s, 4, 2, s->baseline_opens); }
        }
    }
    if (!rc && s->owner_live) {
        if (s->free_attempted) rc = -EIO;
        else {
            s->free_attempted = 1; rc = snap_command(s, 0x23);
            if (!rc) { s->owner_live = 0; rc = snap_metadata(s, 5, 1, s->baseline_opens); }
        }
    }
    s->cleanup_error = rc;
    if (rc) return snap_fault(s, rc, 1);
    free(s->owned_snapshot); s->owned_snapshot = NULL; s->snapshot_live = s->provider_may_retain = 0;
    return 0;
}
static int snap_token(const struct functional_face_source_snapshot *s, const struct functional_face_ap_borrow *b) {
    return b && s->snapshot_live && s->owner_live && s->open_live && s->bridge_complete && s->host_disjoint_verified &&
        snap_span_equal(&b->span, &s->token.span) && b->nonce && b->nonce == s->token.nonce &&
        b->offset == s->token.offset && b->bytes == s->token.bytes;
}
static int snap_acquire(void *context, const struct functional_face_ap_span *a, size_t offset, size_t bytes,
    struct functional_face_ap_borrow *out) {
    int saved_errno = errno;
    struct functional_face_source_snapshot *s = context; int rc = snap_enter(s);
    if (rc) { errno = saved_errno; return rc; }
    if (!a || !out || offset || bytes != s->config.saved_source.bytes || !snap_span_equal(a, &s->config.saved_source))
        return snap_leave(s, -ESTALE, saved_errno);
    if (s->attempted) return snap_leave(s, -EALREADY, saved_errno);
    s->attempted = s->claimed = 1;
    rc = snap_birth(&s->config, s->config.observer, 0);
    if (!rc && s->config.observer->active) rc = -EBUSY;
    if (!rc) rc = snap_observe_mapping(s, 0);
    if (!rc) rc = snap_metadata(s, 0, 1, 0);
    if (rc) return snap_leave(s, snap_fault(s, rc, 0), saved_errno);
    rc = snap_command(s, 0x21);
    if (rc) return snap_leave(s, rc, saved_errno);
    s->owner_live = s->provider_may_retain = 1;
    rc = snap_metadata(s, 1, 2, s->baseline_opens);
    if (rc) return snap_leave(s, snap_fault(s, rc, 1), saved_errno);
    rc = snap_command(s, 0x24);
    if (rc) {
        if (!s->faulted) { int cleanup = snap_balance(s); if (cleanup) rc = cleanup; else snap_fault(s, rc, 0); }
        return snap_leave(s, rc, saved_errno);
    }
    s->open_live = 1;
    const unsigned char *reply = s->operations[1].reply_wire;
    s->physical = snap_le(reply + 24, 8);
    if (snap_le(reply + 8, 2) != 1 || snap_le(reply + 12, 4) != a->handle ||
        snap_le(reply + 32, 4) != bytes || !s->physical || s->physical != s->config.born.address ||
        bytes > UINT64_MAX - s->physical)
        return snap_leave(s, snap_fault(s, -EPROTO, 1), saved_errno);
    rc = snap_metadata(s, 2, 2, s->baseline_opens + 1);
    if (rc) return snap_leave(s, snap_fault(s, rc, 1), saved_errno);
    rc = snap_observe_mapping(s, 1);
    if (!rc) {
        s->owned_snapshot = malloc(bytes);
        if (!s->owned_snapshot) rc = -ENOMEM;
    }
    if (rc) {
        int cleanup = snap_balance(s); if (cleanup) rc = cleanup; else snap_fault(s, rc, 0);
        return snap_leave(s, rc, saved_errno);
    }
    snap_packet(s);
    struct fcam_native_origin origin = {a->handle, s->config.destination.handle,
        FCAM_FACE_SNAPSHOT_COMMAND, 40, snap_fnv(s->config.raw_api40, 40)};
#ifdef FCAM_HOST_TEST
    if (s->config.bridge_call) rc = s->config.bridge_call(s->config.test_context, &origin, FCAM_OP_AP_SOURCE_SNAPSHOT,
        s->packet, s->packet_bytes, s->owned_snapshot, bytes, &s->bridge_result);
    else
#endif
    rc = fcam_bridge_call(&origin, FCAM_OP_AP_SOURCE_SNAPSHOT, s->packet, s->packet_bytes,
        s->owned_snapshot, bytes, &s->bridge_result);
    if (rc) {
        /* The legacy bridge returns the same errno for local and remote
         * failures; it provides no failure-stage/cancellation receipt. */
        return snap_leave(s, snap_fault(s, rc, 1), saved_errno);
    }
    if (s->bridge_result.used != bytes || s->bridge_result.required != bytes ||
        !s->bridge_result.model_instance || !s->bridge_result.result_token)
        return snap_leave(s, snap_fault(s, -EPROTO, 1), saved_errno);
    s->bridge_complete = s->host_disjoint_verified = 1;
    rc = snap_observe_mapping(s, 1);
    if (rc) return snap_leave(s, snap_fault(s, rc, 0), saved_errno);
    s->snapshot_digest = snap_fnv(s->owned_snapshot, bytes);
    uint64_t nonce = s->snapshot_digest ^ a->epoch ^ s->bridge_result.model_instance ^ s->bridge_result.result_token ^
        (uint64_t)(uintptr_t)s ^ s->last_sequence;
    if (!nonce) nonce = a->epoch;
    s->token = (struct functional_face_ap_borrow){.span = *a, .nonce = nonce, .offset = 0, .bytes = bytes};
    s->snapshot_live = 1; *out = s->token;
    return snap_leave(s, 0, saved_errno);
}
static long snap_read(void *context, const struct functional_face_ap_borrow *b, size_t offset, void *out, size_t bytes) {
    int saved_errno = errno; struct functional_face_source_snapshot *s = context; int rc = snap_enter(s);
    if (rc) { errno = saved_errno; return rc; }
    if (!snap_token(s, b) || !out || !bytes || bytes > LONG_MAX || offset != s->bytes_read ||
        offset > b->bytes || bytes > b->bytes - offset || bytes > UINTPTR_MAX - (uintptr_t)out)
        return snap_leave(s, -ESTALE, saved_errno);
    uintptr_t dst = (uintptr_t)out, own = (uintptr_t)s->owned_snapshot;
    if (dst < own + b->bytes && own < dst + bytes) return snap_leave(s, -EINVAL, saved_errno);
    if (snap_fnv(s->owned_snapshot, b->bytes) != s->snapshot_digest)
        return snap_leave(s, snap_fault(s, -EBADMSG, 0), saved_errno);
    memcpy(out, s->owned_snapshot + offset, bytes); s->bytes_read += bytes;
    snap_leave(s, 0, saved_errno); return (long)bytes;
}
static int snap_check(void *context, const struct functional_face_ap_borrow *b,
    const struct functional_face_dmm_descriptor *d) {
    int saved_errno = errno; struct functional_face_source_snapshot *s = context; int rc = snap_enter(s);
    if (rc) { errno = saved_errno; return rc; }
    if (!snap_token(s, b) || !d) return snap_leave(s, -ESTALE, saved_errno);
    if (!snap_cp_equal(d, &s->config.destination)) rc = -ESTALE;
    else rc = snap_observe_mapping(s, 1);
    if (rc) rc = snap_fault(s, rc, 0);
    return snap_leave(s, rc, saved_errno);
}
static int snap_release(void *context, const struct functional_face_ap_borrow *b) {
    int saved_errno = errno; struct functional_face_source_snapshot *s = context; int rc = snap_enter(s);
    if (rc) { errno = saved_errno; return rc; }
    if (!snap_token(s, b)) return snap_leave(s, -ESTALE, saved_errno);
    if (s->bytes_read != b->bytes) return snap_leave(s, snap_fault(s, -ENODATA, 0), saved_errno);
    rc = snap_balance(s);
    return snap_leave(s, rc, saved_errno);
}
int functional_face_source_snapshot_init(struct functional_face_source_snapshot *s,
    const struct functional_face_source_snapshot_config *c, struct functional_face_ap_provider *out) {
    int saved_errno = errno;
    if (!s || !c || !out) return -EINVAL;
    if ((s->initialized && (s->config.owner_pid != getpid() || s->config.owner_tid != snap_tid())) ||
        c->owner_pid != getpid() || c->owner_tid != snap_tid()) return -ECHILD;
    if (s->initialized || atomic_load_explicit(&s->busy, memory_order_acquire)) return -EALREADY;
    if (c->owner_pid <= 1 || c->owner_tid <= 0 || c->owner_tid > INT_MAX) return -EOVERFLOW;
    int rc = snap_shape(c);
    if (rc) { errno = saved_errno; return rc; }
    s->config = *c; s->last_sequence = c->observer->sequence;
    s->cp_count = (uint32_t)(c->destination.mapped_bytes / SNAP_PAGE);
    s->sdk_count = (uint32_t)(((c->frame & (SNAP_PAGE - 1)) + FCAM_FACE_SNAPSHOT_FRAME_BYTES + SNAP_PAGE - 1) / SNAP_PAGE);
    s->initialized = 1;
    *out = (struct functional_face_ap_provider){s, snap_acquire, snap_read, snap_check, snap_release};
    errno = saved_errno; return 0;
}
