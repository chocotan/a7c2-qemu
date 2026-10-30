/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-face-runtime.h"
#include <errno.h>
#include <stdatomic.h>
#ifdef FULL_IMAGING_GUEST
/* AArch64 guest libc 2.25: keep declarations independent of host redirects. */
extern int getpid(void);
extern long syscall(long, ...);
extern void *memcpy(void *, const void *, size_t);
extern void *memset(void *, int, size_t);
extern int memcmp(const void *, const void *, size_t);
extern void *malloc(size_t);
extern void free(void *);
extern int pthread_mutex_lock(void *);
extern int pthread_mutex_unlock(void *);
static unsigned long runtime_mutex[6];
#define LOCK() ((void)pthread_mutex_lock(runtime_mutex))
#define UNLOCK() ((void)pthread_mutex_unlock(runtime_mutex))
#define THREAD_ID() syscall(178L)
#else
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
static pthread_mutex_t runtime_mutex = PTHREAD_MUTEX_INITIALIZER;
#define LOCK() ((void)pthread_mutex_lock(&runtime_mutex))
#define UNLOCK() ((void)pthread_mutex_unlock(&runtime_mutex))
#define THREAD_ID() syscall(SYS_gettid)
#endif

static _Atomic int runtime_pid;
static struct functional_face_runtime_snapshot state;
static functional_face_runtime_record recorder;
static int selected_reference[FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS];
static unsigned char observing[FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS];
static uint64_t next_transaction = 1;
static _Thread_local int dispatch_slot = -1;

static int process_guard(void) {
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong_explicit(&runtime_pid, &expected, pid,
        memory_order_acq_rel, memory_order_acquire);
    return atomic_load_explicit(&runtime_pid, memory_order_acquire) == pid ? 0 : -ECHILD;
}
static int unit_index(uint32_t unit) {
    return unit >= 0x1d9 && unit <= 0x1db ? (int)(unit - 0x1d9) : -1;
}
static uint32_t get(const unsigned char *p, unsigned int bytes) {
    uint32_t v = 0;
    for (unsigned int i = 0; i < bytes; ++i) v |= (uint32_t)p[i] << (8 * i);
    return v;
}
static int io_equal(const struct full_imaging_io *a, const struct full_imaging_io *b) {
    return a && b && a->allocate == b->allocate && a->release == b->release &&
        a->set_source == b->set_source && a->send == b->send && a->size == b->size &&
        a->source == b->source && a->record == b->record;
}
static int io_valid(const struct full_imaging_io *io) {
    return io && io->allocate && io->release && io->set_source && io->send && io->size && io->source;
}
static int same_span(const struct functional_face_dmm_descriptor *a,
                     const struct functional_face_dmm_descriptor *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->reference == b->reference &&
        a->logical == b->logical && a->registration == b->registration &&
        a->host_view == b->host_view && a->bytes == b->bytes && a->mapped_bytes == b->mapped_bytes;
}
static int owner_locked(uint64_t owner) {
    if (!state.enabled) return -ENODEV;
    if (!owner || owner != state.producer_owner) return -EPERM;
    if (state.faults) return -EIO;
    return 0;
}
static void fault_locked(struct functional_face_runtime_transaction *tx) {
    if (!tx->faulted) { tx->faulted = 1; ++state.faults; }
}
static int find_reply_locked(void *message) {
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS; ++i)
        if (state.transactions[i].active && !state.transactions[i].reply_freed &&
            state.transactions[i].reply == (uintptr_t)message) return (int)i;
    return -1;
}
static void clear_reservation_locked(unsigned int slot) {
    struct functional_face_runtime_transaction *tx = &state.transactions[slot];
    int ref = selected_reference[slot], index = unit_index(tx->unit);
    if (index >= 0 && ref >= 0) state.units[index].references[ref].pending = 0;
}
static void finish_locked(unsigned int slot) {
    struct functional_face_runtime_transaction *tx = &state.transactions[slot];
    if (tx->faulted || !tx->dispatch_returned || tx->dispatch_result || !tx->request_freed ||
        !tx->observed || !tx->reply_freed) return;
    struct functional_face_runtime_unit *u = &state.units[unit_index(tx->unit)];
    const struct functional_face_dmm_descriptor *d = &tx->receipt.actual.span;
    if (!get(tx->receipt.actual.wire + 2, 2)) {
        struct functional_face_dmm_descriptor base = *d;
        base.reference = tx->binding.reference;
        if (d->owner != state.producer_owner || d->unit != tx->unit ||
            d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || !d->epoch || !d->registration ||
            !d->host_view || !d->bytes || (tx->op != 0x20 && !same_span(&base, &tx->binding))) {
            fault_locked(tx); return;
        }
        int ref = selected_reference[slot];
        if (tx->op == 0x20) {
            if (u->live_creator || u->retired || d->reference) { fault_locked(tx); return; }
            u->live_creator = 1; u->creator = *d; u->creator_tid = tx->sender_tid;
            u->receipt = tx->receipt;
        } else if (tx->op == 0x21 || tx->op == 0x24) {
            if (ref < 0 || !d->reference || u->references[ref].live) { fault_locked(tx); return; }
            u->references[ref] = (struct functional_face_runtime_reference){
                .live = 1, .kind = tx->op, .sender_tid = tx->sender_tid,
                .span = *d, .receipt = tx->receipt
            };
        } else if (tx->op == 0x25) {
            if (ref < 0 || !u->references[ref].live ||
                !same_span(&u->references[ref].span, &tx->binding)) { fault_locked(tx); return; }
            memset(&u->references[ref], 0, sizeof u->references[ref]);
        } else if (tx->op == 0x23) {
            if (!u->live_creator || !same_span(&u->creator, &tx->binding) || d->reference) {
                fault_locked(tx); return;
            }
            u->live_creator = 0; u->retired = 1; u->retirement = tx->receipt;
        }
        ++state.ledger_commit;
    }
    clear_reservation_locked(slot);
    state.last_completed = *tx;
    memset(tx, 0, sizeof *tx);
    selected_reference[slot] = -1;
}

int functional_face_runtime_snapshot(struct functional_face_runtime_snapshot *out) {
    int rc = process_guard();
    if (rc) return rc;
    if (!out) return -EINVAL;
    LOCK();
    if (state.snapshot_id == UINT64_MAX) { UNLOCK(); return -EOVERFLOW; }
    ++state.snapshot_id;
    memcpy(out, &state, sizeof *out);
    out->owner_pid = getpid();
    out->live_creators = out->opens = out->shares = out->tickets = out->retained = 0;
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
        out->live_creators += out->units[i].live_creator;
        for (unsigned int j = 0; j < FUNCTIONAL_FACE_RUNTIME_REFERENCES; ++j) {
            const struct functional_face_runtime_reference *ref = &out->units[i].references[j];
            if (ref->live && ref->kind == 0x24) ++out->opens;
            if (ref->live && ref->kind == 0x21) ++out->shares;
        }
    }
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS; ++i) {
        const struct functional_face_runtime_transaction *tx = &out->transactions[i];
        if (tx->active && tx->observed) ++out->tickets;
        if (tx->active && tx->faulted) ++out->retained;
    }
    /* Model snapshot has no callbacks. Holding our lock makes the ledger and
     * model read coherent; callback reentry reports its real -EBUSY instead. */
    out->model_snapshot_result = functional_face_dmm_snapshot(&out->model);
    UNLOCK();
    return 0;
}
static void emit(const char *prefix) {
    LOCK(); functional_face_runtime_record record = recorder; UNLOCK();
    if (!record) return;
    struct functional_face_runtime_snapshot *s = malloc(sizeof *s);
    if (!s) { LOCK(); ++state.log_dropped; UNLOCK(); return; }
    if (!functional_face_runtime_snapshot(s)) record(prefix, s);
    free(s);
}
int functional_face_runtime_prepare(int explicit_enabled, uint64_t owner,
    const struct full_imaging_io *io, functional_face_runtime_record record) {
    int rc = process_guard();
    if (rc) return rc;
    if (explicit_enabled != 1) return -ENODEV;
    if (!owner || !io_valid(io)) return -EINVAL;
    LOCK();
    if (state.preparing) rc = -EBUSY;
    else if (state.enabled) rc = owner == state.producer_owner && io_equal(io, &state.io_identity) &&
        record == recorder ? (state.faults ? -EIO : 0) : -EPERM;
    else if (state.faults) rc = -EIO;
    else state.preparing = 1;
    int prepare = !rc && state.preparing;
    UNLOCK();
    if (!prepare) return rc;
    struct functional_face_dmm_registry callbacks;
    rc = functional_face_registry_callbacks(&callbacks);
    if (!rc) rc = functional_face_dmm_enable(&callbacks);
    LOCK();
    state.preparing = 0;
    if (!rc) {
        state.enabled = 1; state.producer_owner = owner; state.io_identity = *io; recorder = record;
        for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS; ++i) selected_reference[i] = -1;
    } else ++state.faults;
    UNLOCK();
    emit(rc ? "FUNCTIONAL_FACE_DMM_FAULT" : "FUNCTIONAL_FACE_DMM_PREPARED");
    return rc;
}

/* Only allocation and release need adaptation: every original IO argument and
 * result is preserved. Source, size, send and set_source remain original. */
static int allocate_reply(unsigned int queue, void **out, unsigned int bytes, unsigned int wait) {
    int slot = dispatch_slot;
    if (slot < 0) return -EIO;
    LOCK(); int (*allocate)(unsigned int, void **, unsigned int, unsigned int) = state.io_identity.allocate; UNLOCK();
    int rc = allocate(queue, out, bytes, wait);
    LOCK(); state.transactions[slot].reply = (uintptr_t)*out; UNLOCK();
    return rc;
}
static int release_actual(unsigned int queue, void *message) {
    LOCK();
    int slot = dispatch_slot;
    if (slot < 0 || !state.transactions[slot].active ||
        (state.transactions[slot].request != (uintptr_t)message &&
         state.transactions[slot].reply != (uintptr_t)message)) slot = find_reply_locked(message);
    if (slot < 0) { UNLOCK(); return -ESTALE; }
    struct functional_face_runtime_transaction *tx = &state.transactions[slot];
    int request = tx->request == (uintptr_t)message;
    int (*release)(unsigned int, void *) = state.io_identity.release;
    UNLOCK();
    int rc = release(queue, message);
    LOCK();
    if (request) {
        tx->request_free_result = rc;
        if (!rc) { tx->request_freed = 1; ++state.actual_request_free; }
    } else {
        tx->reply_free_result = rc;
        if (!rc) { tx->reply_freed = 1; ++state.actual_reply_free; }
    }
    if (rc) fault_locked(tx);
    UNLOCK();
    return rc;
}
static int request_shape(const unsigned char *q, uint32_t source, uint32_t unit) {
    unsigned int op = get(q, 2);
    if (get(q + 0x0c, 4) != (op == 0x20 || op == 0x24 ? UINT32_MAX : 0) ||
        get(q + 0x14, 2) != (op == 0x23 ? source & 0xffffu : 0) || get(q + 0x16, 2)) return 0;
    for (unsigned int i = 2; i < 40; ++i) {
        if ((i >= 4 && i < 0x10) || (i >= 0x14 && i < 0x16)) continue;
        if (q[i]) return 0;
    }
    if (op == 0x20) return get(q + 4, 4) == unit && !get(q + 8, 4);
    return get(q + 4, 4) == (op == 0x21 ? unit : 0);
}
static int bind_locked(unsigned int op, uint32_t unit, uint32_t handle, int64_t sender,
    enum functional_face_runtime_reference_kind kind,
    struct functional_face_dmm_descriptor *binding, int *reference) {
    struct functional_face_runtime_unit *u = &state.units[unit_index(unit)];
    *reference = -1;
    if (op == 0x20) {
        /* shortcut: startup-only, one creator lifecycle per unit; a reusable
         * wire protocol needs an original caller generation identity first. */
        if (u->retired) return -ESTALE;
        if (u->live_creator) return -EEXIST;
        for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS; ++i)
            if (state.transactions[i].active && state.transactions[i].unit == unit &&
                state.transactions[i].op == 0x20) return -EBUSY;
        *binding = (struct functional_face_dmm_descriptor){
            .domain = FUNCTIONAL_FACE_DMM_DOMAIN, .unit = unit, .owner = state.producer_owner
        };
        return 0;
    }
    if (!u->live_creator) return -ENODATA;
    if (handle != u->creator.handle) return -ESTALE;
    *binding = u->creator;
    if (op == 0x21 || op == 0x24) {
        for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_REFERENCES; ++i)
            if (!u->references[i].live && !u->references[i].pending) { *reference = (int)i; return 0; }
        return -ENOSPC;
    }
    if (op == 0x23) return sender == u->creator_tid ? 0 : -EPERM;
    if (kind != FUNCTIONAL_FACE_RUNTIME_UNIQUE_REFERENCE && kind != FUNCTIONAL_FACE_RUNTIME_OPEN &&
        kind != FUNCTIONAL_FACE_RUNTIME_SHARE) return -EINVAL;
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_REFERENCES; ++i) {
        const struct functional_face_runtime_reference *r = &u->references[i];
        if (!r->live || r->sender_tid != sender || (kind && r->kind != (uint32_t)kind)) continue;
        if (*reference >= 0) return -ENODATA;
        *reference = (int)i;
    }
    if (*reference < 0) return -ENODATA;
    if (u->references[*reference].pending) return -EBUSY;
    *binding = u->references[*reference].span;
    return 0;
}
int functional_face_runtime_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, int explicit_enabled,
    const struct functional_face_runtime_caller *caller, int *result) {
    if (destination != FUNCTIONAL_FACE_DMM_CP || explicit_enabled != 1 || !caller ||
        caller->trust == FUNCTIONAL_FACE_RUNTIME_UNTRUSTED || !result) return 0;
    int rc = process_guard();
    if (rc) { *result = rc; return 1; }
    if (caller->trust != FUNCTIONAL_FACE_RUNTIME_ACCEPTED) { *result = -EPROTO; return 1; }
    if (!request || !io_valid(io)) { *result = -EINVAL; return 1; }
    LOCK();
    rc = owner_locked(caller->producer_owner);
    if (!rc && !io_equal(io, &state.io_identity)) rc = -EPERM;
    if (!rc && state.busy) rc = -EBUSY;
    if (!rc && unit_index(caller->unit) < 0) rc = -ENODATA;
    if (!rc) state.busy = 1;
    UNLOCK();
    if (rc) {
        if ((rc == -EBUSY || rc == -EIO) && io->size(request) == 40) {
            unsigned int other = get(request, 2);
            if (other != 0x20 && other != 0x21 && other != 0x23 && other != 0x24 && other != 0x25) return 0;
        }
        *result = rc; return 1;
    }
    unsigned char q[40];
    unsigned int bytes = io->size(request), source = io->source(request), op = 0;
    if (bytes != 40) rc = -EMSGSIZE;
    else { memcpy(q, request, 40); op = get(q, 2); }
    if (!rc && op != 0x20 && op != 0x21 && op != 0x23 && op != 0x24 && op != 0x25) {
        LOCK(); state.busy = 0; UNLOCK(); return 0;
    }
    if (!rc && ((source >> 28) != 8 || !(source & 0x0fffffffu) ||
        !request_shape(q, source, caller->unit))) rc = -EPROTO;
    int slot = -1, ref = -1;
    struct functional_face_dmm_descriptor binding = {0};
    int64_t sender = THREAD_ID();
    LOCK();
    if (!rc) rc = bind_locked(op, caller->unit, get(q + 8, 4), sender, caller->close_kind, &binding, &ref);
    for (unsigned int i = 0; !rc && i < FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS; ++i) {
        struct functional_face_runtime_transaction *tx = &state.transactions[i];
        if (!tx->active && slot < 0) slot = (int)i;
        if (tx->active && ((!tx->request_freed && tx->request == (uintptr_t)request) ||
            (!tx->reply_freed && tx->reply == (uintptr_t)request))) rc = -EALREADY;
    }
    if (!rc && slot < 0) rc = -ENOSPC;
    if (!rc && next_transaction == UINT64_MAX) rc = -EOVERFLOW;
    if (!rc) {
        struct functional_face_runtime_transaction *tx = &state.transactions[slot];
        memset(tx, 0, sizeof *tx);
        tx->id = next_transaction++; tx->active = tx->dispatching = 1;
        tx->op = op; tx->unit = caller->unit; tx->sender_tid = sender;
        tx->request = (uintptr_t)request; tx->request_source = source; tx->binding = binding;
        memcpy(tx->request_wire, q, 40);
        selected_reference[slot] = ref;
        if (ref >= 0) state.units[unit_index(caller->unit)].references[ref].pending = 1;
    }
    if (rc) state.busy = 0;
    UNLOCK();
    if (rc) { *result = rc; return 1; }
    struct full_imaging_io adapted = *io;
    adapted.allocate = allocate_reply; adapted.release = release_actual;
    int previous = dispatch_slot;
    dispatch_slot = slot;
    int transport = -EPROTO;
    int handled = functional_face_dmm_dispatch(destination, request, &adapted, 1, &binding, &transport);
    dispatch_slot = previous;
    if (!handled) transport = -EPROTO;
    struct functional_face_dmm_snapshot model;
    int model_rc = functional_face_dmm_snapshot(&model);
    LOCK();
    struct functional_face_runtime_transaction *tx = &state.transactions[slot];
    tx->dispatching = 0; tx->dispatch_returned = 1; tx->dispatch_result = transport;
    if ((!model_rc && model.faults) || (transport && tx->observed) || (!transport && !tx->request_freed))
        fault_locked(tx);
    uint64_t before = state.ledger_commit;
    finish_locked((unsigned int)slot);
    int fault = tx->faulted;
    int committed = state.ledger_commit != before;
    if (transport && !tx->observed && !tx->faulted) {
        clear_reservation_locked((unsigned int)slot);
        state.last_completed = *tx;
        memset(tx, 0, sizeof *tx); selected_reference[slot] = -1;
    }
    state.busy = 0;
    UNLOCK();
    *result = transport ? transport : fault ? -EIO : 0;
    emit(fault ? "FUNCTIONAL_FACE_DMM_FAULT" : committed ? "FUNCTIONAL_FACE_DMM_LEDGER_COMMIT" :
        "FUNCTIONAL_FACE_DMM_DISPATCH");
    return 1;
}

int functional_face_runtime_observe(uint64_t owner, unsigned int queue, void *message,
    int original_receive_result, struct functional_face_runtime_ticket *out) {
    int rc = process_guard();
    if (rc) return rc;
    if (!message) return 0;
    LOCK();
    int slot = find_reply_locked(message);
    if (slot < 0) { UNLOCK(); return 0; }
    struct functional_face_runtime_transaction *tx = &state.transactions[slot];
    rc = owner_locked(owner);
    if (!rc && original_receive_result) rc = -EIO;
    if (!rc && (!out || tx->sender_tid != THREAD_ID() || queue != tx->request_source ||
        tx->observed || observing[slot] || tx->release_attempted)) rc = -ESTALE;
    if (!rc && state.busy && !tx->dispatching) rc = -EBUSY;
    if (!rc) observing[slot] = 1;
    UNLOCK();
    if (rc) return rc;
    struct functional_face_dmm_ticket actual;
    rc = functional_face_dmm_receive(queue, message, &actual);
    LOCK();
    observing[slot] = 0;
    if (!rc) {
        memset(&tx->receipt, 0, sizeof tx->receipt);
        tx->receipt.transaction = tx->id; tx->receipt.producer_owner = owner;
        tx->receipt.sender_tid = tx->sender_tid; tx->receipt.request = tx->request;
        tx->receipt.op = tx->op; tx->receipt.request_source = tx->request_source;
        memcpy(&tx->receipt.actual, &actual, sizeof actual);
        tx->observed = 1; ++state.actual_receive; memcpy(out, &tx->receipt, sizeof *out);
    }
    UNLOCK();
    if (!rc) emit("FUNCTIONAL_FACE_DMM_RECEIVE");
    return rc ? rc : 1;
}
int functional_face_runtime_release(uint64_t owner, unsigned int queue, void *message,
    const struct functional_face_runtime_ticket *ticket,
    int (*original_release)(unsigned int, void *), int *result) {
    int rc = process_guard();
    if (rc) { if (result) *result = rc; return message && result ? 1 : 0; }
    if (!message || !result) return 0;
    LOCK();
    int slot = find_reply_locked(message);
    if (slot < 0) {
        for (unsigned int i = 0; i < FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS; ++i) {
            const struct functional_face_runtime_transaction *held = &state.transactions[i];
            if (held->active && held->faulted && held->dispatch_returned && !held->dispatch_result &&
                !held->request_freed && held->request == (uintptr_t)message) {
                UNLOCK(); *result = -EIO; return 1;
            }
        }
        UNLOCK(); return 0;
    }
    struct functional_face_runtime_transaction *tx = &state.transactions[slot];
    rc = owner_locked(owner);
    if (!rc && (!ticket || !original_release || original_release != state.io_identity.release ||
        tx->observed != 1 || tx->release_attempted || tx->sender_tid != THREAD_ID() ||
        queue != tx->request_source || memcmp(ticket, &tx->receipt, sizeof *ticket))) rc = -ESTALE;
    if (!rc && state.busy && !tx->dispatching) rc = -EBUSY;
    if (!rc) tx->release_attempted = 1;
    UNLOCK();
    if (rc) { *result = rc; return 1; }
    int actual_result = -ESTALE;
    int handled = functional_face_dmm_release_reply(queue, message, &ticket->actual, release_actual, &actual_result);
    LOCK();
    if (!handled || actual_result || !tx->reply_freed) fault_locked(tx);
    uint64_t before = state.ledger_commit;
    finish_locked((unsigned int)slot);
    int committed = state.ledger_commit != before, fault = tx->faulted;
    UNLOCK();
    *result = fault ? (actual_result ? actual_result : -EIO) : actual_result;
    emit(fault ? "FUNCTIONAL_FACE_DMM_FAULT" : committed ? "FUNCTIONAL_FACE_DMM_LEDGER_COMMIT" :
        "FUNCTIONAL_FACE_DMM_RELEASE");
    return 1;
}
int functional_face_runtime_lookup_creator(uint64_t owner, uint32_t unit,
    struct functional_face_dmm_descriptor *out) {
    int rc = process_guard();
    if (rc) return rc;
    if (!out || unit_index(unit) < 0) return -EINVAL;
    LOCK();
    rc = owner_locked(owner);
    if (!rc && state.busy) rc = -EBUSY;
    const struct functional_face_runtime_unit *u = &state.units[unit_index(unit)];
    if (!rc && !u->live_creator) rc = -ENODATA;
    if (!rc) memcpy(out, &u->creator, sizeof *out);
    UNLOCK();
    return rc;
}
int functional_face_runtime_borrow_destination(uint64_t owner, uint32_t unit, uint32_t handle,
    const struct functional_face_dmm_descriptor *saved, size_t offset, size_t bytes,
    unsigned int access, struct functional_face_dmm_borrow *out) {
    int rc = process_guard();
    if (rc) return rc;
    if (!saved || !out || unit_index(unit) < 0) return -EINVAL;
    struct functional_face_dmm_descriptor creator;
    LOCK();
    rc = owner_locked(owner);
    const struct functional_face_runtime_unit *u = &state.units[unit_index(unit)];
    if (!rc && state.busy) rc = -EBUSY;
    if (!rc && !u->live_creator) rc = -ENODATA;
    if (!rc && (handle != u->creator.handle || !same_span(saved, &u->creator))) rc = -ESTALE;
    if (!rc) { creator = u->creator; state.busy = 1; }
    UNLOCK();
    if (rc) return rc;
    rc = functional_face_dmm_borrowed_span(&creator, offset, bytes, access, out);
    LOCK(); state.busy = 0; UNLOCK();
    if (!rc) emit("FUNCTIONAL_FACE_DMM_BORROW");
    return rc;
}
