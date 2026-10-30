/* SPDX-License-Identifier: MIT */
#include "functional-face-registry.h"
#include <errno.h>
#include <stdatomic.h>
#ifdef FULL_IMAGING_GUEST
/* AArch64 guest libc 2.25; avoid host libc redirects. */
extern int getpid(void);
extern int pthread_mutex_trylock(void *);
extern int pthread_mutex_unlock(void *);
static unsigned long face_registry_mutex[6];
#define REGISTRY_LOCK() pthread_mutex_trylock(face_registry_mutex)
#define REGISTRY_UNLOCK() ((void)pthread_mutex_unlock(face_registry_mutex))
#else
#include <pthread.h>
#include <unistd.h>
static pthread_mutex_t face_registry_mutex = PTHREAD_MUTEX_INITIALIZER;
#define REGISTRY_LOCK() pthread_mutex_trylock(&face_registry_mutex)
#define REGISTRY_UNLOCK() ((void)pthread_mutex_unlock(&face_registry_mutex))
#endif

struct face_registry_entry {
    struct functional_face_registry_inspection spans;
    uint64_t last_epoch;
};
static struct face_registry_entry face_registry_entries[FUNCTIONAL_FACE_DMM_UNITS];
static _Atomic int face_registry_pid;
static uint64_t face_registry_registration;
static const size_t face_registry_sizes[FUNCTIONAL_FACE_DMM_UNITS] = {0x64000, 0xc800, 0xd100};

static int face_registry_enter(void) {
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong_explicit(&face_registry_pid, &expected, pid,
        memory_order_acq_rel, memory_order_acquire);
    if (atomic_load_explicit(&face_registry_pid, memory_order_acquire) != pid) return -ECHILD;
    int rc = REGISTRY_LOCK();
    return rc ? -rc : 0;
}
static int face_registry_index(const struct functional_face_dmm_descriptor *d) {
    return d && d->unit >= 0x1d9 && d->unit <= 0x1db ? (int)(d->unit - 0x1d9) : -1;
}
static int face_registry_equal(const struct functional_face_dmm_descriptor *a,
    const struct functional_face_dmm_descriptor *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->reference == b->reference &&
        a->logical == b->logical && a->registration == b->registration &&
        a->host_view == b->host_view && a->bytes == b->bytes && a->mapped_bytes == b->mapped_bytes;
}
static int face_registry_overlap(uint64_t a, uint64_t an, uint64_t b, uint64_t bn) {
    return a < b + bn && b < a + an;
}
static int face_registry_shape(const struct functional_face_dmm_descriptor *d, int index) {
    if (index < 0 || d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || !d->epoch || !d->owner ||
        d->reference || d->logical || d->registration || !d->host_view ||
        d->host_view % FUNCTIONAL_FACE_DMM_PAGE) return -EINVAL;
    unsigned int generation = (d->handle >> 10) & 31u;
    if (!generation || d->handle != (0x8000u | (generation << 10) | ((unsigned int)index + 2)))
        return -EINVAL;
    size_t bytes = face_registry_sizes[index];
    size_t mapped = (bytes + FUNCTIONAL_FACE_DMM_PAGE - 1) /
        FUNCTIONAL_FACE_DMM_PAGE * FUNCTIONAL_FACE_DMM_PAGE;
    if (d->bytes != bytes || d->mapped_bytes != mapped) return -EMSGSIZE;
    if (d->mapped_bytes > UINTPTR_MAX - d->host_view) return -EOVERFLOW;
    /* IOVAs and AP reservations are not dereferenceable host views. */
    if (face_registry_overlap(d->host_view, d->mapped_bytes, UINT64_C(0x1e000000),
        UINT64_C(0xa00000)) ||
        face_registry_overlap(d->host_view, d->mapped_bytes, UINT64_C(0x41e000000), UINT64_C(0xa00000)) ||
        face_registry_overlap(d->host_view, d->mapped_bytes, FUNCTIONAL_FACE_REGISTRY_IOVA,
            FUNCTIONAL_FACE_DMM_UNITS * FUNCTIONAL_FACE_REGISTRY_WINDOW)) return -EADDRINUSE;
    return 0;
}
static int face_registry_current(const struct functional_face_dmm_descriptor *d) {
    int index = face_registry_index(d);
    return index >= 0 && face_registry_entries[index].spans.current.registration &&
        face_registry_equal(d, &face_registry_entries[index].spans.current) ? index : -ESTALE;
}
static int face_registry_register(void *context, struct functional_face_dmm_descriptor *d) {
    int rc = face_registry_enter();
    if (rc) return rc;
    int index = face_registry_index(d);
    if (context != face_registry_entries) rc = -EINVAL;
    else rc = face_registry_shape(d, index);
    if (!rc && face_registry_entries[index].spans.current.registration) rc = -EEXIST;
    if (!rc && d->epoch <= face_registry_entries[index].last_epoch) rc = -ESTALE;
    if (!rc && face_registry_registration == UINT64_MAX) rc = -EOVERFLOW;
    for (unsigned int i = 0; !rc && i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
        const struct functional_face_dmm_descriptor *other = &face_registry_entries[i].spans.current;
        if (other->registration && face_registry_overlap(d->host_view, d->mapped_bytes,
            other->host_view, other->mapped_bytes)) rc = -EADDRINUSE;
    }
    if (!rc) {
        struct functional_face_dmm_descriptor current = *d;
        current.logical = FUNCTIONAL_FACE_REGISTRY_IOVA + (unsigned int)index * FUNCTIONAL_FACE_REGISTRY_WINDOW;
        current.registration = ++face_registry_registration;
        struct face_registry_entry *entry = &face_registry_entries[index];
        entry->spans.original = *d;
        entry->spans.current = current;
        entry->last_epoch = d->epoch;
        d->logical = current.logical;
        d->registration = current.registration;
    }
    REGISTRY_UNLOCK();
    return rc;
}
static int face_registry_validate(void *context, const struct functional_face_dmm_descriptor *d) {
    int rc = face_registry_enter();
    if (rc) return rc;
    if (context != face_registry_entries) rc = -EINVAL;
    else { int index = face_registry_current(d); rc = index < 0 ? index : 0; }
    REGISTRY_UNLOCK();
    return rc;
}
static int face_registry_unregister(void *context, const struct functional_face_dmm_descriptor *d) {
    int rc = face_registry_enter();
    if (rc) return rc;
    if (context != face_registry_entries) rc = -EINVAL;
    else {
        int index = face_registry_current(d);
        if (index < 0) rc = index;
        else face_registry_entries[index].spans = (struct functional_face_registry_inspection){0};
    }
    REGISTRY_UNLOCK();
    return rc;
}
int functional_face_registry_callbacks(struct functional_face_dmm_registry *out) {
    int rc = face_registry_enter();
    if (rc) return rc;
    if (!out) rc = -EINVAL;
    else *out = (struct functional_face_dmm_registry){face_registry_entries,
        face_registry_register, face_registry_validate, face_registry_unregister};
    REGISTRY_UNLOCK();
    return rc;
}
int functional_face_registry_inspect_span(const struct functional_face_dmm_descriptor *saved,
    struct functional_face_registry_inspection *out) {
    int rc = face_registry_enter();
    if (rc) return rc;
    if (!out) rc = -EINVAL;
    else {
        int index = face_registry_current(saved);
        if (index < 0) rc = index;
        else *out = face_registry_entries[index].spans;
    }
    REGISTRY_UNLOCK();
    return rc;
}
