/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-face-dmm.h"
#include <errno.h>
#include <stdatomic.h>
#ifdef FULL_IMAGING_GUEST
/* AArch64 guest libc 2.25; do not inherit newer host libc redirects. */
extern int getpid(void);
extern long syscall(long, ...);
extern long sysconf(int);
extern void *mmap(void *, size_t, int, int, int, long);
extern int munmap(void *, size_t);
extern void *memcpy(void *, const void *, size_t);
extern void *memmove(void *, const void *, size_t);
extern void *memset(void *, int, size_t);
extern int memcmp(const void *, const void *, size_t);
extern int *__errno_location(void);
extern int pthread_mutex_lock(void *);
extern int pthread_mutex_unlock(void *);
static unsigned long mutex[6]; /* AArch64 glibc pthread_mutex_t: 48 B, normal. */
#define LOCK() ((void)pthread_mutex_lock(mutex))
#define UNLOCK() ((void)pthread_mutex_unlock(mutex))
#define THREAD_ID() syscall(178L)
#define PAGE_SIZE() sysconf(30)
#define MAP_FAILED ((void *)-1)
#else
#include <pthread.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
#define LOCK() ((void)pthread_mutex_lock(&mutex))
#define UNLOCK() ((void)pthread_mutex_unlock(&mutex))
#define THREAD_ID() syscall(SYS_gettid)
#define PAGE_SIZE() sysconf(_SC_PAGESIZE)
#endif

#define REF_COUNT 32u
#define BORROW_COUNT 64u
#define TX_COUNT 16u
#define NO_UNIT FUNCTIONAL_FACE_DMM_UNITS
struct reference { uint64_t nonce; unsigned int kind; };
struct unit {
    struct functional_face_dmm_unit_snapshot state;
    struct reference refs[REF_COUNT];
};
struct borrow {
    struct functional_face_dmm_borrow value;
    size_t verified;
};
struct transaction {
    void *request, *reply;
    struct full_imaging_io io;
    struct functional_face_dmm_ticket ticket;
    long sender;
    unsigned int op, unit, active, sending, sent, received, checking, releasing;
    unsigned int reply_freed, request_freed, reply_counted;
};
static _Atomic int process_owner;
static struct functional_face_dmm_registry registry;
static struct functional_face_dmm_snapshot counters;
static struct unit units[FUNCTIONAL_FACE_DMM_UNITS];
static struct borrow borrows[BORROW_COUNT];
static struct transaction transactions[TX_COUNT];
static uint64_t next_nonce = 1;
static const uint32_t capacities[FUNCTIONAL_FACE_DMM_UNITS] = {0x64000, 0xc800, 0xd100};

static int process_guard(void) {
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong_explicit(&process_owner, &expected, pid,
        memory_order_acq_rel, memory_order_acquire);
    return atomic_load_explicit(&process_owner, memory_order_acquire) == pid ? 0 : -ECHILD;
}
static int begin(void) {
    int rc = process_guard();
    if (rc) return rc;
    LOCK();
    if (!counters.enabled) rc = -ENODEV;
    else if (counters.busy) rc = -EBUSY;
    else if (counters.faults) rc = -EIO;
    else counters.busy = 1;
    UNLOCK();
    return rc;
}
static void end(void) { LOCK(); counters.busy = 0; UNLOCK(); }
static uint64_t digest(const void *data, size_t bytes) {
    const unsigned char *p = data;
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; ++i) { h ^= p[i]; h *= UINT64_C(1099511628211); }
    return h;
}
static uint32_t get(const unsigned char *p, unsigned int bytes) {
    uint32_t v = 0;
    for (unsigned int i = 0; i < bytes; ++i) v |= (uint32_t)p[i] << (i * 8);
    return v;
}
static void put(unsigned char *p, uint64_t value, unsigned int bytes) {
    for (unsigned int i = 0; i < bytes; ++i) p[i] = (unsigned char)(value >> (i * 8));
}
static int unit_index(uint32_t unit) {
    return unit >= 0x1d9 && unit <= 0x1db ? (int)(unit - 0x1d9) : -1;
}
static int same_span(const struct functional_face_dmm_descriptor *a,
                     const struct functional_face_dmm_descriptor *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->logical == b->logical &&
        a->registration == b->registration && a->host_view == b->host_view &&
        a->bytes == b->bytes && a->mapped_bytes == b->mapped_bytes;
}
static int same_descriptor(const struct functional_face_dmm_descriptor *a,
                           const struct functional_face_dmm_descriptor *b) {
    return same_span(a, b) && a->reference == b->reference;
}
static struct reference *find_reference(struct unit *u, uint64_t reference) {
    if (reference) for (unsigned int i = 0; i < REF_COUNT; ++i)
        if (u->refs[i].nonce == reference) return &u->refs[i];
    return NULL;
}
static int binding_unit(const struct functional_face_dmm_descriptor *d) {
    if (!d || d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || !d->owner || !d->epoch) return -ESTALE;
    int i = unit_index(d->unit);
    if (i < 0) return -ENODATA;
    struct unit *u = &units[i];
    if (!u->state.allocated || !same_span(d, &u->state.span) ||
        (d->reference && !find_reference(u, d->reference))) return -ESTALE;
    return i;
}
static int fresh_nonce(uint64_t *value) {
    if (next_nonce == UINT64_MAX) return -EOVERFLOW;
    *value = next_nonce++;
    return 0;
}
static int span_identity(const struct functional_face_dmm_descriptor *before,
                         const struct functional_face_dmm_descriptor *after) {
    struct functional_face_dmm_descriptor copy = *after;
    copy.logical = before->logical;
    copy.registration = before->registration;
    return same_descriptor(&copy, before);
}
static int valid_registration(const struct functional_face_dmm_descriptor *d) {
    if (!d->logical || !d->registration || d->logical % FUNCTIONAL_FACE_DMM_PAGE ||
        d->bytes > UINT64_MAX - d->logical || !d->host_view ||
        d->mapped_bytes > UINTPTR_MAX - d->host_view ||
        !(d->logical + d->bytes <= (uint64_t)d->host_view ||
          (uint64_t)d->host_view + d->mapped_bytes <= d->logical)) return 0;
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
        const struct functional_face_dmm_descriptor *other = &units[i].state.span;
        if (!other->host_view) continue;
        if (d->registration == other->registration ||
            !(d->logical + d->bytes <= other->logical ||
              other->logical + other->bytes <= d->logical) ||
            !(d->logical + d->bytes <= (uint64_t)other->host_view ||
              (uint64_t)other->host_view + other->mapped_bytes <= d->logical) ||
            !((uint64_t)d->host_view + d->mapped_bytes <= other->logical ||
              other->logical + other->bytes <= (uint64_t)d->host_view)) return 0;
    }
    return 1;
}
static int discard_backing(struct functional_face_dmm_descriptor *d, int registered) {
    int rc = registered ? registry.unregister_span(registry.context, d) : 0;
    if (!rc && munmap((void *)d->host_view, d->mapped_bytes)) rc = -errno;
    if (!rc) memset(d, 0, sizeof *d);
    return rc;
}
static int allocate_backing(unsigned int index, uint64_t owner) {
    struct unit *u = &units[index];
    if (u->state.span.host_view || u->state.allocated) return -EEXIST;
    if (counters.epochs == UINT64_MAX) return -EOVERFLOW;
    uint32_t generation = u->state.generation < 31 ? u->state.generation + 1 : 1;
    LOCK();
    uint64_t epoch = ++counters.epochs;
    UNLOCK();
    struct functional_face_dmm_descriptor d = {
        .domain = FUNCTIONAL_FACE_DMM_DOMAIN, .unit = 0x1d9u + index,
        .handle = 0x8000u | (generation << 10) | (index + 2),
        .epoch = epoch, .owner = owner, .bytes = capacities[index],
        .mapped_bytes = (capacities[index] + FUNCTIONAL_FACE_DMM_PAGE - 1) /
                        FUNCTIONAL_FACE_DMM_PAGE * FUNCTIONAL_FACE_DMM_PAGE
    };
    void *p = mmap(NULL, d.mapped_bytes, 3, 0x22, -1, 0);
    if (p == MAP_FAILED) return -errno;
    d.host_view = (uintptr_t)p;
    /* Zero initialization is solely the virtual profile's software policy. */
    memset(p, 0, d.mapped_bytes);
    struct functional_face_dmm_descriptor original = d;
    int rc = registry.register_span(registry.context, &d);
    int registered = !rc;
    if (!rc && (!span_identity(&original, &d) || !valid_registration(&d))) rc = -EPROTO;
    if (!rc) rc = registry.validate_span(registry.context, &d);
    if (rc) {
        /* Retain our real allocation even if a broken callback changed metadata. */
        original.logical = d.logical; original.registration = d.registration;
        int cleanup = discard_backing(&original, registered);
        if (cleanup) {
            u->state.span = original;
            LOCK(); ++counters.faults; ++counters.retained_cleanup; UNLOCK();
        }
        return rc;
    }
    memset(u, 0, sizeof *u);
    u->state.span = d; u->state.allocated = 1; u->state.generation = generation;
    u->state.digest = digest(p, d.bytes);
    return 0;
}
static int add_reference(struct unit *u, unsigned int kind,
                         struct functional_face_dmm_descriptor *out) {
    unsigned int i = 0;
    while (i < REF_COUNT && u->refs[i].nonce) ++i;
    if (i == REF_COUNT) return -ENOSPC;
    uint64_t nonce;
    int rc = fresh_nonce(&nonce);
    if (rc) return rc;
    u->refs[i] = (struct reference){nonce, kind};
    if (kind == 0x21) ++u->state.shares; else ++u->state.opens;
    *out = u->state.span; out->reference = nonce;
    return 0;
}
static int unit_transport_busy(unsigned int index, const struct transaction *current) {
    for (unsigned int i = 0; i < TX_COUNT; ++i)
        if (&transactions[i] != current && transactions[i].active && transactions[i].unit == index) return 1;
    return 0;
}
static int typed_operation(struct transaction *tx, const unsigned char *q,
    const struct functional_face_dmm_descriptor *binding) {
    unsigned int op = tx->op;
    int index = op == 0x20 ? unit_index(get(q + 4, 4)) : binding_unit(binding);
    if (index < 0) return index;
    tx->unit = (unsigned int)index;
    struct unit *u = &units[index];
    int rc = 0;
    if (op == 0x20) rc = allocate_backing((unsigned int)index, binding->owner);
    else if (op == 0x21 || op == 0x24) {
        rc = registry.validate_span(registry.context, &u->state.span);
        if (!rc) rc = add_reference(u, op, &tx->ticket.span);
    } else if (op == 0x25) {
        struct reference *ref = find_reference(u, binding->reference);
        if (!ref) return -ESTALE;
        if (ref->kind == 0x21) --u->state.shares; else --u->state.opens;
        memset(ref, 0, sizeof *ref);
    } else if (op == 0x23) {
        if (binding->reference || u->state.opens || u->state.shares || u->state.borrows ||
            u->state.transfers || unit_transport_busy((unsigned int)index, tx)) return -EBUSY;
        rc = registry.validate_span(registry.context, &u->state.span);
    }
    if (!rc && op != 0x21 && op != 0x24) tx->ticket.span = u->state.span;
    return rc;
}
static int raw_status(int rc) {
    if (!rc) return 0;
    if (rc == -EEXIST || rc == -ENOMEM || rc == -ENOSPC) return -0x201;
    if (rc == -ESTALE) return -0x205;
    if (rc == -ENODATA) return -3;
    return -1;
}
static void build_reply(struct transaction *tx, const unsigned char *q, int rc) {
    unsigned char *r = tx->ticket.wire;
    memset(r, 0, 40);
    int raw = raw_status(rc), converted = raw == -0x201 ? -1 : raw == -0x205 ? -5 : raw;
    /* Software policy from dmm-service, not a pinned original CP producer. */
    put(r, tx->op | 0x8000u, 2); put(r + 2, (unsigned int)converted, 2);
    put(r + 6, get(q + 20, 2), 2); put(r + 10, (unsigned int)raw, 2);
    put(r + 12, tx->op == 0x20 ? UINT32_MAX : get(q + 8, 4), 4);
    if (!rc) {
        put(r + 12, tx->ticket.span.handle, 4);
        if (tx->op == 0x20) put(r + 16, tx->ticket.span.unit, 4);
        if (tx->op == 0x21 || tx->op == 0x24) {
            put(r + 8, 1, 2); put(r + 24, tx->ticket.span.logical, 8);
            put(r + 32, tx->ticket.span.bytes, 4);
        }
    }
}
static int request_shape(const unsigned char *q, unsigned int source,
                         const struct functional_face_dmm_descriptor *b) {
    unsigned int op = get(q, 2);
    if (op != 0x20 && op != 0x21 && op != 0x23 && op != 0x24 && op != 0x25) return 0;
    if (!b || b->domain != FUNCTIONAL_FACE_DMM_DOMAIN || !b->owner ||
        get(q + 0x0c, 4) != (op == 0x20 || op == 0x24 ? UINT32_MAX : 0) ||
        get(q + 0x14, 2) != (op == 0x23 ? source & 0xffffu : 0) || get(q + 0x16, 2)) return 0;
    for (unsigned int i = 2; i < 40; ++i) {
        if ((i >= 0x04 && i < 0x10) || (i >= 0x14 && i < 0x16)) continue;
        if (q[i]) return 0;
    }
    if (op == 0x20) return unit_index(get(q + 0x04, 4)) >= 0 && !get(q + 0x08, 4) &&
        b->unit == get(q + 0x04, 4) && !b->epoch && !b->handle && !b->reference &&
        !b->logical && !b->registration && !b->host_view && !b->bytes && !b->mapped_bytes;
    uint32_t handle = get(q + 0x08, 4);
    if (handle != b->handle || (handle & 0x8000u) == 0 || (handle >> 16) ||
        (handle & 0x3ffu) < 2 || (handle & 0x3ffu) > 4 || !((handle >> 10) & 31) ||
        unit_index(b->unit) < 0) return 0;
    return op == 0x21 ? get(q + 0x04, 4) == b->unit : !get(q + 0x04, 4);
}
static struct transaction *find_reply(void *reply) {
    for (unsigned int i = 0; i < TX_COUNT; ++i)
        if (transactions[i].active && transactions[i].reply == reply) return &transactions[i];
    return NULL;
}
static int alias_pointer(void *pointer, const struct transaction *current) {
    if (!pointer) return 0;
    for (unsigned int i = 0; i < TX_COUNT; ++i) {
        const struct transaction *tx = &transactions[i];
        if (tx->active && (tx->request == pointer || (tx != current && tx->reply == pointer))) return 1;
    }
    uintptr_t p = (uintptr_t)pointer;
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
        const struct functional_face_dmm_descriptor *d = &units[i].state.span;
        if (d->host_view && p >= d->host_view && p - d->host_view < d->mapped_bytes) return 1;
    }
    return 0;
}
static int finish(struct transaction *tx) {
    if (!tx->sent || tx->sending || !tx->reply_freed || !tx->request_freed) return 0;
    unsigned int free_unit = tx->op == 0x23 && !get(tx->ticket.wire + 2, 2) ? tx->unit : NO_UNIT;
    if (tx->received && !get(tx->ticket.wire + 2, 2)) ++counters.ap_consumed;
    memset(tx, 0, sizeof *tx);
    return free_unit < NO_UNIT ? (int)free_unit + 1 : 0;
}
/* Caller holds the busy reservation, but never the private mutex here. */
static int retire_backing(unsigned int index) {
    struct functional_face_dmm_descriptor d = units[index].state.span;
    int rc = discard_backing(&d, 1);
    LOCK();
    if (rc) { ++counters.faults; ++counters.retained_cleanup; }
    else {
        uint32_t generation = units[index].state.generation;
        memset(&units[index], 0, sizeof units[index]);
        units[index].state.generation = generation;
    }
    UNLOCK();
    return rc;
}

int functional_face_dmm_enable(const struct functional_face_dmm_registry *callbacks) {
    int rc = process_guard();
    if (rc) return rc;
    if (!callbacks || !callbacks->register_span || !callbacks->validate_span || !callbacks->unregister_span)
        return -ENODATA;
    if (PAGE_SIZE() != FUNCTIONAL_FACE_DMM_PAGE) return -ENOTSUP;
    LOCK();
    if (counters.enabled) rc = -EALREADY;
    else { registry = *callbacks; counters.enabled = 1; }
    UNLOCK();
    return rc;
}
int functional_face_dmm_snapshot(struct functional_face_dmm_snapshot *out) {
    int rc = process_guard();
    if (rc) return rc;
    if (!out) return -EINVAL;
    LOCK();
    /* busy protects mutations performed around external callbacks. */
    if (counters.busy) { UNLOCK(); return -EBUSY; }
    struct functional_face_dmm_snapshot s = counters;
    s.owner_pid = getpid();
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
        s.units[i] = units[i].state;
        /* A borrowed host view may be written by its real external consumer. */
        if (s.units[i].span.host_view && !s.units[i].borrows)
            s.units[i].digest = digest((void *)s.units[i].span.host_view, s.units[i].span.bytes);
    }
    memcpy(out, &s, sizeof s);
    UNLOCK();
    return 0;
}
int functional_face_dmm_shutdown(void) {
    int rc = begin();
    if (rc) return rc;
    LOCK();
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i)
        if (units[i].state.span.host_view) rc = -EBUSY;
    if (counters.live_requests || counters.live_replies || counters.retained_cleanup) rc = -EBUSY;
    if (!rc) { counters.enabled = 0; memset(&registry, 0, sizeof registry); }
    counters.busy = 0;
    UNLOCK();
    return rc;
}

int functional_face_dmm_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, int enabled,
    const struct functional_face_dmm_descriptor *binding, int *result) {
    if (destination != FUNCTIONAL_FACE_DMM_CP || enabled != 1 || !result || !request || !io ||
        !io->allocate || !io->release || !io->size || !io->source || !io->set_source || !io->send) return 0;
    int rc = begin();
    if (rc) { *result = rc; return 1; }
    unsigned int bytes = io->size(request), source = io->source(request);
    if (bytes != 40 || (source >> 28) != 8 || !(source & 0x0fffffffu) ||
        !request_shape(request, source, binding)) { end(); return 0; }
    unsigned char q[40]; memcpy(q, request, 40);
    struct functional_face_dmm_descriptor trusted = *binding;
    struct transaction *tx = NULL;
    LOCK();
    if (alias_pointer(request, NULL)) rc = -EALREADY;
    for (unsigned int i = 0; !rc && i < TX_COUNT; ++i)
        if (!transactions[i].active) { tx = &transactions[i]; break; }
    if (!rc && !tx) rc = -ENOSPC;
    uint64_t nonce = 0;
    if (!rc) rc = fresh_nonce(&nonce);
    if (!rc) {
        memset(tx, 0, sizeof *tx);
        tx->active = 1; tx->request = request; tx->sender = THREAD_ID(); tx->io = *io;
        tx->op = get(q, 2); tx->unit = NO_UNIT; tx->ticket.nonce = nonce;
        tx->ticket.destination = source;
        ++counters.live_requests;
    }
    UNLOCK();
    if (rc) { end(); *result = rc; return 1; }
    void *reply = NULL;
    rc = io->allocate(source, &reply, 40, 1);
    LOCK();
    int alias = alias_pointer(reply, tx);
    UNLOCK();
    if (alias) {
        LOCK(); ++counters.faults; --counters.live_requests; memset(tx, 0, sizeof *tx); UNLOCK();
        end(); *result = rc ? rc : -EALREADY; return 1;
    }
    if (rc || !reply) {
        int cleanup = reply ? io->release(source, reply) : 0;
        LOCK();
        --counters.live_requests;
        if (cleanup) { tx->request = NULL; tx->reply = reply; ++counters.live_replies;
            ++counters.retained_cleanup; ++counters.faults; }
        else memset(tx, 0, sizeof *tx);
        UNLOCK(); end(); *result = rc ? rc : -ENOMEM; return 1;
    }
    if (io->size(reply) != 40) {
        rc = -EMSGSIZE;
    } else {
        LOCK();
        tx->reply = reply; tx->ticket.reply = (uintptr_t)reply;
        UNLOCK();
    }
    struct unit before = {0};
    int before_index = tx->op == 0x20 ? unit_index(get(q + 4, 4)) : unit_index(trusted.unit);
    if (before_index >= 0) before = units[before_index];
    int operation_rc = rc ? rc : typed_operation(tx, q, &trusted);
    if (!rc) {
        build_reply(tx, q, operation_rc);
        memcpy(reply, tx->ticket.wire, 40);
        io->set_source(reply, FUNCTIONAL_FACE_DMM_CP);
        if (io->source(reply) != FUNCTIONAL_FACE_DMM_CP || io->size(reply) != 40 ||
            memcmp(reply, tx->ticket.wire, 40)) rc = -EPROTO;
    }
    if (!rc) {
        LOCK(); tx->sending = 1; tx->reply_counted = 1; ++counters.live_replies; UNLOCK();
        rc = io->send(source, reply);
        LOCK(); tx->sending = 0; UNLOCK();
    }
    if (rc) {
        LOCK();
        int observed = tx->received || tx->reply_freed;
        int had_reply = tx->reply_counted;
        if (observed) { ++counters.faults; --counters.live_requests; tx->request = NULL; }
        UNLOCK();
        if (!observed) {
            if (!operation_rc && tx->unit < NO_UNIT) {
                if (tx->op == 0x20) {
                    int cleanup = retire_backing(tx->unit);
                    if (!cleanup) units[tx->unit] = before;
                } else units[tx->unit] = before;
            }
            int cleanup = io->release(source, reply);
            LOCK();
            --counters.live_requests;
            if (had_reply && counters.live_replies) --counters.live_replies;
            if (cleanup) { tx->request = NULL; tx->reply = reply;
                ++counters.live_replies; ++counters.retained_cleanup; ++counters.faults; }
            else memset(tx, 0, sizeof *tx);
            UNLOCK();
        }
        end(); *result = rc; return 1;
    }
    LOCK();
    tx->sent = 1; ++counters.queued;
    if (!operation_rc && tx->op == 0x23) units[tx->unit].state.allocated = 0;
    UNLOCK();
    int freed = io->release(FUNCTIONAL_FACE_DMM_CP, request);
    LOCK();
    if (freed) ++counters.faults;
    else { tx->request = NULL; tx->request_freed = 1; --counters.live_requests; ++counters.request_freed; }
    int retire = finish(tx);
    UNLOCK();
    if (retire) (void)retire_backing((unsigned int)retire - 1);
    end(); *result = 0; return 1;
}

int functional_face_dmm_receive(unsigned int destination, void *reply,
                                struct functional_face_dmm_ticket *out) {
    int rc = process_guard();
    if (rc) return rc;
    if (!reply || !out) return -EINVAL;
    LOCK();
    struct transaction *tx = find_reply(reply);
    if (!tx || (!tx->sending && !tx->sent) || tx->received || tx->checking || tx->releasing ||
        tx->ticket.destination != destination || tx->sender != THREAD_ID()) {
        UNLOCK(); return -ESTALE;
    }
    if (counters.busy && !tx->sending) { UNLOCK(); return -EBUSY; }
    unsigned int own_busy = !counters.busy;
    counters.busy = 1;
    tx->checking = 1;
    struct full_imaging_io io = tx->io;
    UNLOCK();
    if (io.size(reply) != 40 || io.source(reply) != FUNCTIONAL_FACE_DMM_CP ||
        memcmp(reply, tx->ticket.wire, 40)) rc = -EPROTO;
    LOCK();
    tx->checking = 0;
    if (!rc) { tx->received = 1; ++counters.received; memcpy(out, &tx->ticket, sizeof *out); }
    if (own_busy) counters.busy = 0;
    UNLOCK();
    return rc;
}
int functional_face_dmm_release_reply(unsigned int destination, void *reply,
    const struct functional_face_dmm_ticket *ticket, int (*release)(unsigned int, void *), int *result) {
    int rc = process_guard();
    if (rc) { if (result) *result = rc; return reply && result ? 1 : 0; }
    if (!reply || !result) return 0;
    LOCK();
    struct transaction *tx = find_reply(reply);
    if (!tx) { UNLOCK(); return 0; }
    if (!release || release != tx->io.release || !ticket || !tx->received || tx->releasing ||
        tx->checking || tx->sender != THREAD_ID() || destination != tx->ticket.destination ||
        memcmp(ticket, &tx->ticket, sizeof *ticket)) {
        UNLOCK(); *result = -ESTALE; return 1;
    }
    if (counters.busy && !tx->sending) { UNLOCK(); *result = -EBUSY; return 1; }
    unsigned int own_busy = !counters.busy;
    counters.busy = 1;
    tx->releasing = 1;
    UNLOCK();
    rc = release(destination, reply);
    LOCK();
    tx->releasing = 0;
    int retire = 0;
    if (rc) ++counters.faults;
    else {
        tx->reply = NULL; tx->reply_freed = 1; tx->reply_counted = 0;
        --counters.live_replies; ++counters.reply_freed;
        retire = finish(tx);
    }
    UNLOCK();
    if (retire) (void)retire_backing((unsigned int)retire - 1);
    if (own_busy) end();
    *result = rc;
    return 1;
}

static int same_borrow(const struct functional_face_dmm_borrow *a,
                       const struct functional_face_dmm_borrow *b) {
    return same_descriptor(&a->span, &b->span) && a->host_view == b->host_view &&
        a->logical == b->logical && a->nonce == b->nonce && a->before_digest == b->before_digest &&
        a->offset == b->offset && a->bytes == b->bytes && a->access == b->access;
}
static struct borrow *find_borrow(const struct functional_face_dmm_borrow *value) {
    if (value && value->nonce) for (unsigned int i = 0; i < BORROW_COUNT; ++i)
        if (borrows[i].value.nonce == value->nonce && same_borrow(value, &borrows[i].value)) return &borrows[i];
    return NULL;
}
int functional_face_dmm_borrowed_span(const struct functional_face_dmm_descriptor *d,
    size_t offset, size_t bytes, unsigned int access, struct functional_face_dmm_borrow *out) {
    if (!d || !out || !bytes || (access != FUNCTIONAL_FACE_DMM_READ && access != FUNCTIONAL_FACE_DMM_WRITE &&
        access != (FUNCTIONAL_FACE_DMM_READ | FUNCTIONAL_FACE_DMM_TRANSFER) &&
        access != (FUNCTIONAL_FACE_DMM_WRITE | FUNCTIONAL_FACE_DMM_TRANSFER))) return -EINVAL;
    int rc = begin();
    if (rc) return rc;
    int index = binding_unit(d);
    if (index < 0) rc = index;
    else if (offset >= d->bytes || bytes > d->bytes - offset) rc = -ERANGE;
    struct borrow *slot = NULL;
    if (!rc) for (unsigned int i = 0; i < BORROW_COUNT; ++i) {
        struct borrow *b = &borrows[i];
        if (!b->value.nonce && !slot) slot = b;
        if (b->value.nonce && same_span(&b->value.span, d) &&
            ((access | b->value.access) & FUNCTIONAL_FACE_DMM_WRITE)) rc = -EBUSY;
    }
    if (!rc && !slot) rc = -ENOSPC;
    if (!rc) rc = registry.validate_span(registry.context, &units[index].state.span);
    uint64_t nonce = 0;
    if (!rc) rc = fresh_nonce(&nonce);
    if (!rc) {
        struct functional_face_dmm_borrow b = {0};
        b.span = *d; b.offset = offset; b.bytes = bytes; b.access = access; b.nonce = nonce;
        b.host_view = d->host_view + offset; b.logical = d->logical + offset;
        b.before_digest = digest((void *)b.host_view, bytes);
        slot->value = b; slot->verified = 0;
        ++units[index].state.borrows;
        if (access & FUNCTIONAL_FACE_DMM_TRANSFER) ++units[index].state.transfers;
        memcpy(out, &b, sizeof b);
    }
    end();
    return rc;
}
static int host_range(uintptr_t p, size_t bytes) {
    return p && bytes && bytes <= UINTPTR_MAX - p;
}
static int overlap(uintptr_t a, size_t an, uintptr_t b, size_t bn) {
    return !(a + an <= b || b + bn <= a);
}
static int copy_bytes(const struct functional_face_dmm_borrow *value, size_t offset,
    void *data, size_t bytes, struct functional_face_dmm_readback *out, unsigned int write) {
    if (!value || !data || !out || !bytes) return -EINVAL;
    int rc = begin();
    if (rc) return rc;
    struct borrow *b = find_borrow(value);
    if (!b || !same_span(&value->span, &units[unit_index(value->span.unit)].state.span) ||
        (value->span.reference && !find_reference(&units[unit_index(value->span.unit)], value->span.reference))) rc = -ESTALE;
    else if (!(value->access & (write ? FUNCTIONAL_FACE_DMM_WRITE : FUNCTIONAL_FACE_DMM_READ))) rc = -EACCES;
    else if (offset >= value->bytes || bytes > value->bytes - offset) rc = -ERANGE;
    if (!rc && !host_range((uintptr_t)data, bytes)) rc = -EFAULT;
    if (!rc) {
        uintptr_t backing = value->host_view + offset;
        if (overlap(backing, bytes, (uintptr_t)data, bytes)) rc = -EINVAL;
        for (unsigned int i = 0; !write && !rc && i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
            const struct functional_face_dmm_descriptor *d = &units[i].state.span;
            if (d->host_view && overlap((uintptr_t)data, bytes, d->host_view, d->mapped_bytes)) rc = -EINVAL;
        }
        const struct functional_face_dmm_unit_snapshot *s = &units[unit_index(value->span.unit)].state;
        if (write ? (bytes > UINT64_MAX - s->verified_write_bytes || bytes > SIZE_MAX - b->verified) :
                    bytes > UINT64_MAX - s->verified_read_bytes) rc = -EOVERFLOW;
    }
    if (!rc) rc = registry.validate_span(registry.context, &units[unit_index(value->span.unit)].state.span);
    if (!rc) {
        void *backing = (void *)(value->host_view + offset);
        const void *source = write ? data : backing;
        void *destination = write ? backing : data;
        struct functional_face_dmm_readback r = {
            .before_digest = digest(backing, bytes), .after_digest = digest(source, bytes)
        };
        memcpy(destination, source, bytes);
        if (digest(destination, bytes) != r.after_digest || memcmp(destination, source, bytes)) rc = -EIO;
        else {
            r.verified_bytes = bytes;
            struct functional_face_dmm_unit_snapshot *s = &units[unit_index(value->span.unit)].state;
            if (write) { s->verified_write_bytes += bytes; b->verified += bytes; }
            else s->verified_read_bytes += bytes;
            s->digest = digest((void *)s->span.host_view, s->span.bytes);
            memcpy(out, &r, sizeof r);
        }
    }
    end();
    return rc;
}
int functional_face_dmm_write(const struct functional_face_dmm_borrow *b, size_t offset,
    const void *data, size_t bytes, struct functional_face_dmm_readback *out) {
    return copy_bytes(b, offset, (void *)data, bytes, out, 1);
}
int functional_face_dmm_read(const struct functional_face_dmm_borrow *b, size_t offset,
    void *data, size_t bytes, struct functional_face_dmm_readback *out) {
    return copy_bytes(b, offset, data, bytes, out, 0);
}
int functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *value,
                                      struct functional_face_dmm_readback *out) {
    if (!value || !out) return -EINVAL;
    int rc = begin();
    if (rc) return rc;
    struct borrow *b = find_borrow(value);
    if (!b) rc = -ESTALE;
    else {
        int index = unit_index(value->span.unit);
        if (index < 0 || !same_span(&value->span, &units[index].state.span)) rc = -ESTALE;
        else if ((rc = registry.validate_span(registry.context, &units[index].state.span)) == 0) {
            struct functional_face_dmm_readback r = {
                .before_digest = value->before_digest, .after_digest = digest((void *)value->host_view, value->bytes),
                .verified_bytes = b->verified
            };
            --units[index].state.borrows;
            if (value->access & FUNCTIONAL_FACE_DMM_TRANSFER) --units[index].state.transfers;
            memset(b, 0, sizeof *b);
            memcpy(out, &r, sizeof r);
        }
    }
    end();
    return rc;
}
