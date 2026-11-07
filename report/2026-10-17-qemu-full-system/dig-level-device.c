/* SPDX-License-Identifier: MIT */
/* Digital level service 912f0335. The request has no 200d Dataflow header: it is
 * six little-endian u32, and AP reads only u32[4] (+0x10) as the result.
 * This owner declares the feature disabled (enable byte 0 -> the original returns
 * 0 immediately) and therefore never claims to produce real angle samples. */
#define _GNU_SOURCE
#include "dig-level-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#define FULL_DIG_LEVEL_BYTES 24u
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static int current_process(void){int pid=(int)getpid(),expected=0;atomic_compare_exchange_strong(&process_pid,&expected,pid);return atomic_load(&process_pid)==pid;}
static struct full_dig_level_snapshot state;
static struct lease { void *pointer; unsigned int destination; long sender; unsigned long long serial; } replies[4];
static unsigned int u32(const unsigned char *p) {
    return p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}
static void put32(unsigned char *p, unsigned int n) {
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(n >> (8 * i));
}
static void log_event(const struct full_imaging_io *io, const char *tag, const char *line) {
    if (io->record) io->record(tag, line);
}
static int reject(const struct full_imaging_io *io, int *result, const char *reason) {
    log_event(io, "FULL_DIG_LEVEL_UNSUPPORTED ", reason); *result = -1021; return 1;
}
static int cleanup(const struct full_imaging_io *io, unsigned int dst, void *reply) {
    int rc = io->release(dst, reply);
    if (rc) {
        state.faults++; state.retained_reply = reply;
        char line[180];
        snprintf(line, sizeof line, "tid=%ld phase=temporary-reply-free destination=%#x reply=%p rc=%d",
                 syscall(SYS_gettid), dst, reply, rc);
        log_event(io, "FULL_DIG_LEVEL_FAULT ", line);
    }
    return rc;
}
int full_dig_level_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
                            int enabled, int *result) {
    if (enabled != 1 || destination != FULL_DIG_LEVEL_INPUT || !request || !io || !result || !io->size)
        return 0;
    if(!current_process()){*result=-1021;return 1;}
    if (io->size(request) != FULL_DIG_LEVEL_BYTES) return 0;
    if (!io->source || !io->allocate || !io->release || !io->set_source || !io->send)
        return reject(io, result, "missing-transport");
    const unsigned char *in = request;
    unsigned int command = u32(in);
    /* Boot passes 3, the "off" variant passes 4; the original only forwards those
     * two into the angle-notification control and returns 0 when disabled. */
    if (command != 3 && command != 4) return 0;
    unsigned int dst = io->source(request);
    if ((dst >> 28) != 8 || !(dst & 0x0fffffff)) return reject(io, result, "nonlocal-reply-destination");
    char line[320], raw[49];
    for (unsigned int i = 0; i < FULL_DIG_LEVEL_BYTES; i++) snprintf(raw + 2 * i, 3, "%02x", in[i]);
    snprintf(line, sizeof line, "tid=%ld source=%#x destination=%#x command=%u bytes=%u raw=%s",
             syscall(SYS_gettid), dst, destination, command, FULL_DIG_LEVEL_BYTES, raw);
    log_event(io, "FULL_DIG_LEVEL_REQUEST ", line);
    pthread_mutex_lock(&lock);
    if (state.faults || state.pending) {
        pthread_mutex_unlock(&lock);
        return reject(io, result, state.faults ? "ownership-fault-gate" : "concurrent-caller");
    }
    state.pending = 1; state.pending_destination = dst;
    pthread_mutex_unlock(&lock);
    void *reply = 0; int rc = io->allocate(dst, &reply, FULL_DIG_LEVEL_BYTES, 1);
    pthread_mutex_lock(&lock);
    struct lease *slot = 0; int duplicate = reply && reply == request;
    for (unsigned int i = 0; i < 4; i++) {
        if (reply && replies[i].pointer == reply) duplicate = 1;
        if (!replies[i].pointer && !slot) slot = &replies[i];
    }
    if (duplicate) {
        state.faults++; state.pending = 0; log_event(io, "FULL_DIG_LEVEL_FAULT ", "allocator-returned-live-message");
        pthread_mutex_unlock(&lock); return reject(io, result, "duplicate-message-ownership");
    }
    if (rc || !reply || !slot || io->size(reply)!=FULL_DIG_LEVEL_BYTES) {
        if (reply) cleanup(io, dst, reply);
        state.pending = 0;
        pthread_mutex_unlock(&lock); *result = rc ? rc : -1021; return 1;
    }
    struct full_dig_level_snapshot before = state;
    /* Feature-disabled virtual owner: enable byte 0 makes the original return 0
     * without waiting for any angle sample. u32[4] (+0x10) carries that result. */
    state.queries++;
    if (command == 3) state.enables++; else state.disables++;
    state.enabled = 0; state.result = 0;
    unsigned char completed[FULL_DIG_LEVEL_BYTES] = {0};
    put32(completed + 0, command);
    put32(completed + 16, 0);  /* +0x10 result: 0 -> AP model 0 */
    memcpy(reply, completed, sizeof completed);
    io->set_source(reply, FULL_DIG_LEVEL_INPUT);
    unsigned long long serial = ++state.next_lease;
    *slot = (struct lease){ reply, dst, syscall(SYS_gettid), serial };
    state.live_replies++;
    rc = io->send(dst, reply);
    if (rc) {
        state = before; state.pending = 0; memset(slot, 0, sizeof *slot); cleanup(io, dst, reply);
        snprintf(line, sizeof line, "phase=send destination=%#x reply=%p rc=%d caller_owned=1 rollback=1", dst, reply, rc);
        log_event(io, "FULL_DIG_LEVEL_TRANSPORT_FAILURE ", line);
        pthread_mutex_unlock(&lock); *result = rc; return 1;
    }
    state.queued++;
    snprintf(line, sizeof line, "tid=%ld destination=%#x source=%#x command=%u level_enabled=0 model_result=0 "
             "angle_samples=0 reply=%p lease=%llu dig_level_verified=0 camera_startup_verified=0",
             syscall(SYS_gettid), dst, FULL_DIG_LEVEL_INPUT, command, reply, serial);
    log_event(io, "FULL_DIG_LEVEL_REPLY_QUEUED ", line);
    state.pending = 0;
    int freed = io->release(FULL_DIG_LEVEL_INPUT, request);
    if (freed) { state.faults++; state.retained_request = request; } else state.request_freed++;
    pthread_mutex_unlock(&lock); *result = 0;
    return 1;
}
int full_dig_level_release_reply(unsigned int destination, void *reply, int (*release)(unsigned int, void *),
                                 void (*record)(const char *, const char *), int *result) {
    if (!reply || !release || !result) return 0;
    if(!current_process()){
        for(unsigned int i=0;i<4;i++)if(replies[i].pointer==reply){*result=-1021;return 1;}
        return 0;
    }
    pthread_mutex_lock(&lock);
    struct lease found = {0};
    unsigned int index = 0;
    for (unsigned int i = 0; i < 4; i++) if (replies[i].pointer == reply) { found = replies[i]; index = i; break; }
    if (!found.pointer) { pthread_mutex_unlock(&lock); return 0; }
    void *pointer = found.pointer;
    *result = destination == found.destination ? release(destination, reply) : -1021;
    if (*result) state.faults++;
    else {
        memset(&replies[index], 0, sizeof replies[index]);
        state.live_replies--; state.native_freed++;
        if (found.sender == syscall(SYS_gettid)) state.waiter_freed++;
    }
    if (record) {
        char line[240];
        snprintf(line, sizeof line, "tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p lease=%llu rc=%d",
                 syscall(SYS_gettid), found.sender, found.sender == syscall(SYS_gettid), destination,
                 found.destination, pointer, found.serial, *result);
        record(*result ? "FULL_DIG_LEVEL_FAULT " : "FULL_DIG_LEVEL_NATIVE_REPLY_FREE ", line);
    }
    pthread_mutex_unlock(&lock);
    return 1;
}
void full_dig_level_snapshot(struct full_dig_level_snapshot *out) {
    if (!out) return;
    if(!current_process()){*out=(struct full_dig_level_snapshot){0};return;}
    pthread_mutex_lock(&lock); *out = state; pthread_mutex_unlock(&lock);
}
#ifdef FULL_DIG_LEVEL_TEST
void full_dig_level_test_set_pending(unsigned int pending, unsigned int destination) {
    pthread_mutex_lock(&lock); state.pending = pending; state.pending_destination = destination;
    pthread_mutex_unlock(&lock);
}
void full_dig_level_test_reset(void) {
    pthread_mutex_lock(&lock);
    atomic_store(&process_pid,(int)getpid());
    state = (struct full_dig_level_snapshot){0};
    memset(replies, 0, sizeof replies);
    pthread_mutex_unlock(&lock);
}
#endif
