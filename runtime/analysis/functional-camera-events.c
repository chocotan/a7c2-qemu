/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-camera-events.h"
#include "device-models/functional-camera-control.h"
#include <pthread.h>
#include <stdatomic.h>
#include <sys/syscall.h>
#include <unistd.h>

struct receive_event {
    void *pointer;
    unsigned int destination, pending;
    uint64_t cycle;
    int pid;
    long free_tid;
};
static _Atomic int ledger_pid;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static struct receive_event events[FUNCTIONAL_CAMERA_CONTROL_LEASES];

static int observe_receive(unsigned int destination, void *pointer,
                           unsigned int source, unsigned int bytes) {
    const int pid = (int)getpid(), owner = atomic_load(&ledger_pid);
    if (owner && owner != pid) return -EXDEV;
    struct native_functional_camera_control_snapshot s;
    /* The component guards its own inherited mutex, even before our first event. */
    native_functional_camera_control_snapshot(&s);
    if (s.owner_pid && s.owner_pid != pid) return -EXDEV;
    if (!s.initialized || s.owner_pid != pid || !pointer) return 0;
    const struct native_cp_state_publication_lease *lease = NULL;
    uint64_t cycle = 0;
    for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++)
        if (s.leases[i].pointer == pointer) { lease = &s.leases[i]; cycle = s.lease_cycle_id[i]; break; }
    if (!lease) return 0;
    if (lease->destination != destination || lease->source != source || lease->bytes != bytes) return -EPROTO;
    int expected = 0;
    atomic_compare_exchange_strong(&ledger_pid, &expected, s.owner_pid);
    if (atomic_load(&ledger_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&mutex);
    unsigned int slot = FUNCTIONAL_CAMERA_CONTROL_LEASES;
    for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++) {
        if (events[i].pointer == pointer) { pthread_mutex_unlock(&mutex); return -EALREADY; }
        if (!events[i].pointer && slot == FUNCTIONAL_CAMERA_CONTROL_LEASES) slot = i;
    }
    if (slot == FUNCTIONAL_CAMERA_CONTROL_LEASES) { pthread_mutex_unlock(&mutex); return -ENOSPC; }
    /* Original AP ACKs cross the imaging worker's promise; notices free on
     * their actual receiver. Neither path may borrow a ticket at free time. */
    events[slot] = (struct receive_event){.pointer = pointer, .destination = destination,
        .pending = 1, .cycle = cycle, .pid = pid, .free_tid = lease->role == 2 ? lease->sender_tid : syscall(SYS_gettid)};
    pthread_mutex_unlock(&mutex);
    const int handled = native_functional_camera_control_observe_receive_cycle(
        destination, pointer, source, bytes, cycle);
    pthread_mutex_lock(&mutex);
    if (handled == 1) events[slot].pending = 0;
    else events[slot] = (struct receive_event){0};
    pthread_mutex_unlock(&mutex);
    return handled;
}

int functional_camera_events_observe_receive(unsigned int destination, void *pointer,
                                            unsigned int source, unsigned int bytes) {
    const int saved_errno = errno;
    const int handled = observe_receive(destination, pointer, source, bytes);
    errno = saved_errno;
    return handled;
}

int functional_camera_events_release(unsigned int destination, void *pointer,
    int (*real_free)(unsigned int, void *),
    void (*record)(const char *, const char *), int *result) {
    const int pid = (int)getpid(), owner = atomic_load(&ledger_pid);
    if (owner && owner != pid) {
        if (!pointer || !real_free || !result) return 0;
        *result = -EXDEV; return 1;
    }
    /* No snapshot at free: an old event must never borrow a current cycle. */
    if (owner) {
        const long current = syscall(SYS_gettid);
        pthread_mutex_lock(&mutex);
        for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++) {
            const struct receive_event event = events[i];
            if (!pointer || event.pointer != pointer || event.destination != destination ||
                event.pid != pid || event.free_tid != current || event.pending) continue;
            pthread_mutex_unlock(&mutex);
            const int handled = native_functional_camera_control_release_cycle(
                destination, pointer, real_free, record, result, event.cycle);
            if (handled == 1 && *result == 0) {
                pthread_mutex_lock(&mutex);
                events[i] = (struct receive_event){0};
                pthread_mutex_unlock(&mutex);
            }
            return handled;
        }
        pthread_mutex_unlock(&mutex);
    }
    /* Foreign threads and legacy ACKs keep the backend's unqualified policy. */
    return native_functional_camera_control_release(destination, pointer, real_free, record, result);
}
