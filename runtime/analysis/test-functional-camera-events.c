/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-camera-events.h"
#include "device-models/functional-camera-control.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Bounded backend double: accepted receive/free and cycle retirement only.
 * This is transport-boundary lab evidence, not native OSAL/CP/capture proof.
 * malloc-backed slots deliberately recycle their payload addresses; actual
 * backing allocations stay live until cleanup (including under ASan). */
enum { POOL = FUNCTIONAL_CAMERA_CONTROL_LEASES + 1, WIRE_BYTES = 24 };
static unsigned char *packets[POOL];
static struct native_functional_camera_control_snapshot state;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned int snapshots, observes, qualified_frees, legacy_frees, real_frees, records;
static uint64_t observed_ticket, released_ticket;
static int receive_result = 1, free_error, pending_probe;

static void initialize(void) {
    state.owner_pid = (int)getpid(); state.initialized = state.functional_model = 1;
}
static void publish(unsigned int index, unsigned int packet, uint64_t cycle) {
    assert(index < FUNCTIONAL_CAMERA_CONTROL_LEASES && packet < POOL);
    memset(packets[packet], 0xa5, WIRE_BYTES);
    state.leases[index] = (struct native_cp_state_publication_lease){
        .role = 3, .pointer = packets[packet], .bytes = WIRE_BYTES,
        .destination = FUNCTIONAL_CAMERA_CONTROL_AP, .source = FUNCTIONAL_CAMERA_CONTROL_SID,
        .queued = 1,
    };
    state.lease_cycle_id[index] = cycle;
}
static int find_packet(void *pointer) {
    for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++)
        if (state.leases[i].pointer == pointer) return (int)i;
    return -1;
}
static int inherited(void) { return state.owner_pid && state.owner_pid != (int)getpid(); }
static int real_free(unsigned int, void *);

void native_functional_camera_control_snapshot(struct native_functional_camera_control_snapshot *out) {
    snapshots++; errno = EDOM;
    if (inherited()) {
        *out = (struct native_functional_camera_control_snapshot){.owner_pid = state.owner_pid, .faults = 1};
        return;
    }
    assert(!pthread_mutex_lock(&mutex)); *out = state; assert(!pthread_mutex_unlock(&mutex));
}
int native_functional_camera_control_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t cycle) {
    observes++; observed_ticket = cycle; errno = ERANGE;
    if (inherited()) return -EXDEV;
    if (pending_probe) {
        int result = 77; pending_probe = 0;
        assert(functional_camera_events_observe_receive(destination, pointer, source, bytes) == -EALREADY);
        assert(functional_camera_events_release(destination, pointer, real_free, NULL, &result) == 1 && result == -ESTALE);
        assert(!real_frees);
    }
    assert(!pthread_mutex_lock(&mutex));
    const int i = find_packet(pointer);
    int result = receive_result;
    if (i < 0) result = 0;
    else if (state.lease_cycle_id[i] != cycle) result = -ESTALE;
    else if (destination != state.leases[i].destination || source != state.leases[i].source ||
             bytes != state.leases[i].bytes || state.leases[i].received ||
             ((unsigned char *)pointer)[0] != 0xa5) result = -EPROTO;
    if (result == 1) { state.leases[i].received = 1; state.leases[i].receiver_tid = syscall(SYS_gettid); }
    assert(!pthread_mutex_unlock(&mutex)); return result;
}
static int real_free(unsigned int destination, void *pointer) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && pointer);
    real_frees++; errno = free_error ? EAGAIN : EOVERFLOW;
    return free_error;
}
static void record(const char *tag, const char *text) {
    assert(!strcmp(tag, "lab-free") && !strcmp(text, "lab-only")); records++;
}
static int release(unsigned int destination, void *pointer, int (*callback)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t cycle) {
    if (!pointer || !callback || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    assert(!pthread_mutex_lock(&mutex));
    const int i = find_packet(pointer);
    if (i < 0) { assert(!pthread_mutex_unlock(&mutex)); return 0; }
    if (cycle ? cycle != state.lease_cycle_id[i] : state.lease_cycle_id[i] > 1) {
        *result = -ESTALE; assert(!pthread_mutex_unlock(&mutex)); return 1;
    }
    if (destination != state.leases[i].destination ||
        (state.leases[i].role == 2 && state.leases[i].sender_tid != syscall(SYS_gettid)) ||
        (state.lease_cycle_id[i] > 1 && !state.leases[i].received) ||
        ((unsigned char *)pointer)[0] != 0xa5) {
        *result = -EPROTO; assert(!pthread_mutex_unlock(&mutex)); return 1;
    }
    assert(!pthread_mutex_unlock(&mutex));
    *result = callback(destination, pointer);
    assert(!pthread_mutex_lock(&mutex));
    if (!*result) { state.leases[i].pointer = NULL; state.leases[i].freed = 1; }
    assert(!pthread_mutex_unlock(&mutex));
    if (logger) logger("lab-free", "lab-only");
    return 1;
}
int native_functional_camera_control_release_cycle(unsigned int destination, void *pointer,
    int (*callback)(unsigned int, void *), void (*logger)(const char *, const char *),
    int *result, uint64_t cycle) {
    qualified_frees++; released_ticket = cycle;
    return release(destination, pointer, callback, logger, result, cycle);
}
int native_functional_camera_control_release(unsigned int destination, void *pointer,
    int (*callback)(unsigned int, void *), void (*logger)(const char *, const char *), int *result) {
    legacy_frees++; released_ticket = 0;
    return release(destination, pointer, callback, logger, result, 0);
}

static int receive_packet(unsigned int packet) {
    return functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP,
        packets[packet], FUNCTIONAL_CAMERA_CONTROL_SID, WIRE_BYTES);
}
static int free_packet(unsigned int packet, int *result) {
    const unsigned int before = snapshots;
    const int handled = functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP,
        packets[packet], real_free, record, result);
    assert(snapshots == before); return handled;
}
static void cleanup(void) { for (unsigned int i = 0; i < POOL; i++) free(packets[i]); }
static void *foreign_free(void *unused) {
    (void)unused; int result = 77;
    assert(free_packet(0, &result) == 1 && result == -ESTALE); return NULL;
}
static void fork_guard(int captured) {
    if (captured) assert(receive_packet(0) == 1);
    const unsigned int before = snapshots, calls = qualified_frees + legacy_frees;
    assert(!pthread_mutex_lock(&mutex));
    const pid_t child = fork(); assert(child >= 0);
    if (!child) {
        alarm(2); int result = 77;
        assert(receive_packet(0) == -EXDEV);
        assert(free_packet(0, &result) == 1 && result == -EXDEV && !real_frees);
        assert(snapshots == before + (captured ? 0u : 1u));
        assert(qualified_frees + legacy_frees == calls + (captured ? 0u : 1u));
        cleanup(); _exit(0);
    }
    int status; assert(waitpid(child, &status, 0) == child);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    assert(!pthread_mutex_unlock(&mutex));
    if (!captured) assert(receive_packet(0) == 1);
    int result = 77; assert(free_packet(0, &result) == 1 && !result);
}
static void *ack_receiver(void *wrong_free) {
    int result = 77;
    assert(receive_packet(0) == 1);
    if (wrong_free) assert(free_packet(0, &result) == 1 && result == -ESTALE && !real_frees);
    return NULL;
}
static void scenarios(const char *name) {
    int result = 77;
    /* Disabled functional setup leaves the component uninitialized. The real
     * parent's actual-handler gate is integrated and tested by the parent. */
    if (!strcmp(name, "disabled") || !strcmp(name, "uninitialized") || !strcmp(name, "uninitialized-then-init") ||
        !strcmp(name, "fork-uninitialized")) {
        assert(!receive_packet(0) && !observes);
        assert(!free_packet(0, &result) && result == 77 && !real_frees);
        if (!strcmp(name, "disabled") || !strcmp(name, "uninitialized")) return;
        if (!strcmp(name, "fork-uninitialized")) {
            const pid_t child = fork(); assert(child >= 0);
            if (!child) {
                alarm(2); initialize(); publish(0, 0, 2);
                assert(receive_packet(0) == 1 && free_packet(0, &result) == 1 && !result);
                cleanup(); _exit(0);
            }
            int status; assert(waitpid(child, &status, 0) == child);
            assert(WIFEXITED(status) && !WEXITSTATUS(status)); return;
        }
        initialize(); publish(0, 0, 2);
        assert(receive_packet(0) == 1 && free_packet(0, &result) == 1 && !result); return;
    }
    initialize(); publish(0, 0, 2);
    if (!strncmp(name, "ack-handoff", 11)) {
        state.leases[0].role = 2; state.leases[0].sender_tid = syscall(SYS_gettid);
        pthread_t receiver;
        assert(!pthread_create(&receiver, NULL, ack_receiver, !strcmp(name, "ack-handoff-wrong-free") ? &result : NULL));
        assert(!pthread_join(receiver, NULL));
        assert(state.leases[0].receiver_tid != state.leases[0].sender_tid && observes == 1 && observed_ticket == 2);
        if (!strcmp(name, "ack-handoff-duplicate")) assert(receive_packet(0) == -EALREADY && observes == 1);
        assert(free_packet(0, &result) == 1 && !result && released_ticket == 2 && qualified_frees == 1 && real_frees == 1);
        if (!strcmp(name, "ack-handoff-recycled")) {
            publish(0, 0, 3); state.leases[0].role = 2; state.leases[0].sender_tid = syscall(SYS_gettid);
            assert(free_packet(0, &result) == 1 && result == -ESTALE && !released_ticket && real_frees == 1);
            assert(!pthread_create(&receiver, NULL, ack_receiver, NULL)); assert(!pthread_join(receiver, NULL));
            assert(free_packet(0, &result) == 1 && !result && released_ticket == 3 && qualified_frees == 2 && real_frees == 2);
        }
        return;
    }
    if (!strcmp(name, "pending-ticket")) {
        pending_probe = 1;
        assert(receive_packet(0) == 1 && !pending_probe && observes == 1 && !qualified_frees);
        assert(free_packet(0, &result) == 1 && !result && released_ticket == 2 && real_frees == 1); return;
    }
    if (!strcmp(name, "unowned")) {
        assert(!receive_packet(1) && !observes);
        assert(!free_packet(1, &result) && result == 77 && !real_frees); return;
    }
    if (!strcmp(name, "legacy-first")) {
        publish(0, 0, 1);
        assert(free_packet(0, &result) == 1 && !result && !qualified_frees && legacy_frees == 1); return;
    }
    if (!strcmp(name, "wrong-source") || !strcmp(name, "wrong-size") || !strcmp(name, "wrong-destination")) {
        const unsigned int destination = FUNCTIONAL_CAMERA_CONTROL_AP ^ (unsigned int)!strcmp(name, "wrong-destination");
        const unsigned int source = FUNCTIONAL_CAMERA_CONTROL_SID ^ (unsigned int)!strcmp(name, "wrong-source");
        const unsigned int bytes = WIRE_BYTES + (unsigned int)!strcmp(name, "wrong-size");
        assert(functional_camera_events_observe_receive(destination, packets[0], source, bytes) == -EPROTO);
        assert(!observes && free_packet(0, &result) == 1 && result == -ESTALE && !real_frees);
        assert(receive_packet(0) == 1 && free_packet(0, &result) == 1 && !result); return;
    }
    if (!strcmp(name, "backend-reject") || !strcmp(name, "backend-unhandled") || !strcmp(name, "wire-reject")) {
        receive_result = !strcmp(name, "backend-unhandled") ? 0 : -EIO;
        if (!strcmp(name, "wire-reject")) { receive_result = 1; packets[0][0] ^= 1; }
        assert(receive_packet(0) == (!strcmp(name, "wire-reject") ? -EPROTO : receive_result));
        assert(free_packet(0, &result) == 1 && result == -ESTALE && !qualified_frees && !real_frees);
        receive_result = 1; packets[0][0] = 0xa5;
        assert(receive_packet(0) == 1 && free_packet(0, &result) == 1 && !result); return;
    }
    if (!strcmp(name, "fork-held-lock") || !strcmp(name, "fork-before-capture")) {
        fork_guard(!strcmp(name, "fork-held-lock")); return;
    }
    if (!strcmp(name, "ledger-bound")) {
        for (unsigned int i = 0; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++) {
            publish(i, i, 2 + i); assert(receive_packet(i) == 1);
        }
        publish(0, POOL - 1, 17);
        assert(receive_packet(POOL - 1) == -ENOSPC && observes == FUNCTIONAL_CAMERA_CONTROL_LEASES);
        for (unsigned int i = 1; i < FUNCTIONAL_CAMERA_CONTROL_LEASES; i++)
            assert(free_packet(i, &result) == 1 && !result && released_ticket == 2 + i);
        assert(receive_packet(POOL - 1) == 1 && free_packet(POOL - 1, &result) == 1 && !result);
        publish(0, 0, 2); state.leases[0].received = 1;
        assert(free_packet(0, &result) == 1 && !result && released_ticket == 2); return;
    }
    if (!strcmp(name, "errno")) {
        errno = ENOTTY; assert(receive_packet(0) == 1 && errno == ENOTTY);
    } else assert(receive_packet(0) == 1);
    assert(observed_ticket == 2 && !real_frees);
    if (!strcmp(name, "stale-ticket")) {
        /* Inject advanced backend state to prove an old event never refreshes. */
        publish(0, 0, 3);
        assert(free_packet(0, &result) == 1 && result == -ESTALE && released_ticket == 2 && !real_frees);
        assert(receive_packet(0) == -EALREADY && observes == 1);
        publish(0, 0, 2); state.leases[0].received = 1;
    } else if (!strcmp(name, "duplicate-receive")) {
        assert(receive_packet(0) == -EALREADY && observes == 1);
    } else if (!strcmp(name, "foreign-thread")) {
        pthread_t thread; assert(!pthread_create(&thread, NULL, foreign_free, NULL));
        assert(!pthread_join(thread, NULL)); assert(!real_frees && !qualified_frees && legacy_frees == 1);
    } else if (!strcmp(name, "free-fail")) {
        free_error = -EIO;
        assert(free_packet(0, &result) == 1 && result == -EIO && released_ticket == 2 && errno == EAGAIN);
        assert(real_frees == 1 && receive_packet(0) == -EALREADY && observes == 1); free_error = 0;
    } else if (!strcmp(name, "backend-unowned-free")) {
        state.leases[0].pointer = NULL;
        assert(!free_packet(0, &result) && result == 77 && released_ticket == 2 && !real_frees);
        publish(0, 0, 2); state.leases[0].received = 1;
        assert(receive_packet(0) == -EALREADY);
    } else if (!strcmp(name, "free-wrong-destination")) {
        assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP ^ 1u,
            packets[0], real_free, record, &result) == 1 && result < 0 && !real_frees);
    } else if (!strcmp(name, "null-arguments")) {
        assert(!functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, packets[0], NULL, record, &result));
        assert(!functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, packets[0], real_free, record, NULL));
        assert(!functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, NULL,
            FUNCTIONAL_CAMERA_CONTROL_SID, WIRE_BYTES));
        assert(!real_frees);
    } else assert(!strcmp(name, "address-reuse") || !strcmp(name, "repeat-free") || !strcmp(name, "errno"));
    assert(free_packet(0, &result) == 1 && !result && released_ticket == 2);
    assert(errno == EOVERFLOW && records == real_frees);
    if (!strcmp(name, "address-reuse") || !strcmp(name, "repeat-free")) {
        unsigned char *same_address = packets[0]; publish(0, 0, 3);
        assert(packets[0] == same_address);
        const unsigned int attempts = real_frees;
        assert(free_packet(0, &result) == 1 && result == -ESTALE && !released_ticket && real_frees == attempts);
        assert(receive_packet(0) == 1 && observed_ticket == 3);
        assert(free_packet(0, &result) == 1 && !result && released_ticket == 3 && real_frees == attempts + 1);
    }
}
int main(int argc, char **argv) {
    assert(argc == 2);
    for (unsigned int i = 0; i < POOL; i++) { packets[i] = malloc(WIRE_BYTES); assert(packets[i]); }
    scenarios(argv[1]); cleanup(); puts("functional camera actual-event adapter lab case passed"); return 0;
}
