/* SPDX-License-Identifier: MIT */
/* DMM unit-size service 9061003c. Original wrapper 0x3552d80 builds a 40 B
 * request (+0 u16=0x0018, +4 u32=input, +20 u16=0) and then blocks on
 * osal_rcv_msg_tmo(source,out,-1); the reply carries ret_code at +2 (<=0 is OK)
 * and the unit size at +0x10. This owner answers the query from real state it
 * holds and records it; no DMA or transfer is modelled. */
#define _GNU_SOURCE
#include "dmm-device.h"
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#define FULL_DMM_BYTES 40u
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int process_pid;
static int current_process(void){int pid=(int)getpid(),expected=0;atomic_compare_exchange_strong(&process_pid,&expected,pid);return atomic_load(&process_pid)==pid;}
/* The owner's own unit size; a page-sized unit is the value it can actually
 * justify without claiming any DMA or media geometry. */
static struct full_dmm_snapshot state = {.unit_size = 4096};
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
    log_event(io, "FULL_DMM_UNSUPPORTED ", reason); *result = -1021; return 1;
}
static int cleanup(const struct full_imaging_io *io, unsigned int dst, void *reply) {
    int rc = io->release(dst, reply);
    if (rc) {
        state.faults++; state.retained_reply = reply;
        char line[180];
        snprintf(line, sizeof line, "tid=%ld phase=temporary-reply-free destination=%#x reply=%p rc=%d",
                 syscall(SYS_gettid), dst, reply, rc);
        log_event(io, "FULL_DMM_FAULT ", line);
    }
    return rc;
}
int full_dmm_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
                            int enabled, int *result) {
    if (enabled != 1 || destination != FULL_DMM_CP || !request || !io || !result || !io->size)
        return 0;
    if(!current_process()){*result=-1021;return 1;}
    if (io->size(request) != FULL_DMM_BYTES) return 0;
    if (!io->source || !io->allocate || !io->release || !io->set_source || !io->send)
        return reject(io, result, "missing-transport");
    const unsigned char *in = request;
    /* The wrapper zeroes the whole 40 B body, then writes u16 frame 0x0018 at +0,
     * the caller's field at +4 and zero at +20. Accept that exact envelope. */
    unsigned int frame = in[0] | (unsigned int)in[1] << 8;
    unsigned int input = u32(in + 4);
    if (frame != 0x0018) return 0;
    /* This bounded owner supports the captured boot parameter and its default
     * query only. Its declared page policy is not the original pool geometry;
     * unfamiliar parameters require a separate contract instead of a guess. */
    unsigned int derived_unit=0;
    if(input>0xfffff000u)return reject(io,result,"unit-size-overflow");
    if(input && input!=0x50b58u)return reject(io,result,"query-parameter-outside-profile");
    unsigned int dst = io->source(request);
    if ((dst >> 28) != 8 || !(dst & 0x0fffffff)) return reject(io, result, "nonlocal-reply-destination");
    char line[320], raw[2 * FULL_DMM_BYTES + 1];
    for (unsigned int i = 0; i < FULL_DMM_BYTES; i++) snprintf(raw + 2 * i, 3, "%02x", in[i]);
    snprintf(line, sizeof line, "tid=%ld source=%#x destination=%#x command=%u bytes=%u raw=%s",
             syscall(SYS_gettid), dst, destination, frame, FULL_DMM_BYTES, raw);
    log_event(io, "FULL_DMM_REQUEST ", line);
    pthread_mutex_lock(&lock);
    if (state.faults || state.pending) {
        pthread_mutex_unlock(&lock);
        return reject(io, result, state.faults ? "ownership-fault-gate" : "concurrent-caller");
    }
    derived_unit=input?(input+0xfffu)&~0xfffu:state.unit_size;
    if(!derived_unit){pthread_mutex_unlock(&lock);return reject(io,result,"unknown-unit-size");}
    state.pending = 1; state.pending_destination = dst;
    pthread_mutex_unlock(&lock);
    void *reply = 0; int rc = io->allocate(dst, &reply, FULL_DMM_BYTES, 1);
    pthread_mutex_lock(&lock);
    struct lease *slot = 0; int duplicate = reply && reply == request;
    for (unsigned int i = 0; i < 4; i++) {
        if (reply && replies[i].pointer == reply) duplicate = 1;
        if (!replies[i].pointer && !slot) slot = &replies[i];
    }
    if (duplicate) {
        state.faults++; state.pending = 0; log_event(io, "FULL_DMM_FAULT ", "allocator-returned-live-message");
        pthread_mutex_unlock(&lock); return reject(io, result, "duplicate-message-ownership");
    }
    if (rc || !reply || !slot || io->size(reply)!=FULL_DMM_BYTES) {
        if (reply) cleanup(io, dst, reply);
        state.pending = 0;
        pthread_mutex_unlock(&lock); *result = rc ? rc : -1021; return 1;
    }
    struct full_dmm_snapshot before = state;
    /* Feature-disabled virtual owner: enable byte 0 makes the original return 0
     * without waiting for any angle sample. u32[4] (+0x10) carries that result. */
    state.queries++; state.last_input = input;
    state.last_reported_size=derived_unit;
    /* ret_code lives at +2 as i16; the reader treats <=0 as success and then takes
     * the unit size from +0x10. We answer with the state this owner actually holds. */
    unsigned char completed[FULL_DMM_BYTES] = {0};
    completed[0] = 0x18;
    completed[2] = 0; completed[3] = 0;                 /* ret_code = 0 */
    put32(completed + 16, derived_unit);
    memcpy(reply, completed, sizeof completed);
    io->set_source(reply, FULL_DMM_CP);
    unsigned long long serial = ++state.next_lease;
    *slot = (struct lease){ reply, dst, syscall(SYS_gettid), serial };
    state.live_replies++;
    rc = io->send(dst, reply);
    if (rc) {
        state = before; state.pending = 0; memset(slot, 0, sizeof *slot); cleanup(io, dst, reply);
        snprintf(line, sizeof line, "phase=send destination=%#x reply=%p rc=%d caller_owned=1 rollback=1", dst, reply, rc);
        log_event(io, "FULL_DMM_TRANSPORT_FAILURE ", line);
        pthread_mutex_unlock(&lock); *result = rc; return 1;
    }
    state.answered++;
    snprintf(line, sizeof line, "tid=%ld destination=%#x source=%#x frame=0x18 input=%#x unit_size=%u "
             "ret_code=0 reply=%p lease=%llu dmm_transfer_verified=0 camera_startup_verified=0",
             syscall(SYS_gettid), dst, FULL_DMM_CP, input, derived_unit, reply, serial);
    log_event(io, "FULL_DMM_REPLY_QUEUED ", line);
    state.pending = 0;
    int freed = io->release(FULL_DMM_CP, request);
    if (freed) { state.faults++; state.retained_request = request; } else state.request_freed++;
    pthread_mutex_unlock(&lock); *result = 0;
    return 1;
}
int full_dmm_release_reply(unsigned int destination, void *reply, int (*release)(unsigned int, void *),
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
        record(*result ? "FULL_DMM_FAULT " : "FULL_DMM_NATIVE_REPLY_FREE ", line);
    }
    pthread_mutex_unlock(&lock);
    return 1;
}
void full_dmm_snapshot(struct full_dmm_snapshot *out) {
    if (!out) return;
    if(!current_process()){*out=(struct full_dmm_snapshot){0};return;}
    pthread_mutex_lock(&lock); *out = state; pthread_mutex_unlock(&lock);
}
#ifdef FULL_DMM_TEST
void full_dmm_test_set_unit_size(unsigned int bytes) {
    pthread_mutex_lock(&lock); state.unit_size = bytes; pthread_mutex_unlock(&lock);
}
void full_dmm_test_reset(void) {
    pthread_mutex_lock(&lock);
    atomic_store(&process_pid,(int)getpid());
    state = (struct full_dmm_snapshot){0};
    state.unit_size = 4096;
    memset(replies, 0, sizeof replies);
    pthread_mutex_unlock(&lock);
}
#endif
