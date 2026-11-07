/* SPDX-License-Identifier: MIT */
/* 9061003c / dmm_get_unit_size, from appFw 0x3552d80:
 *   request 40 B: +0 u16 = 0x0018, +4 u32 = input field, +20 u16 = 0
 *   caller blocks on osal_rcv_msg_tmo(source, out, -1)
 *   reply: +2 i16 ret_code (<=0 is OK), +0x10 u32 unit size */
#define _GNU_SOURCE
#include "dmm-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct message { unsigned int owner, source, bytes; unsigned char data[]; };
static void *live[16], *queued;
static unsigned int send_failure,bad_reply_size;
static struct message *header(void *p) { return (struct message *)((char *)p - offsetof(struct message, data)); }
static void put16at(unsigned char *p, unsigned int at, unsigned int n) { p[at] = (unsigned char)n; p[at + 1] = (unsigned char)(n >> 8); }
static void put32at(unsigned char *p, unsigned int at, unsigned int n) { for (unsigned int i = 0; i < 4; i++) p[at + i] = (unsigned char)(n >> (8 * i)); }
static unsigned int u32(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24; }
static int allocate(unsigned int id, void **out, unsigned int n, unsigned int wait) {
    assert(wait == 1);
    struct message *m = calloc(1, sizeof *m + n); assert(m);
    m->owner = id; m->bytes = bad_reply_size?n-1:n; *out = m->data;
    for (unsigned int i = 0; i < 16; i++) if (!live[i]) { live[i] = *out; return 0; }
    abort();
}
static int release(unsigned int id, void *p) {
    assert(p && header(p)->owner == id);
    for (unsigned int i = 0; i < 16; i++) if (live[i] == p) { live[i] = 0; memset(p, 0xde, header(p)->bytes); free(header(p)); return 0; }
    abort();
}
static unsigned int size(void *p) { return header(p)->bytes; }
static unsigned int source(void *p) { return header(p)->source; }
static void set_source(void *p, unsigned int id) { header(p)->source = id; }
static int send(unsigned int id, void *p) { assert(header(p)->owner == id && !queued); if (send_failure) return -77; queued = p; return 0; }
static void record(const char *kind, const char *line) { (void)kind; (void)line; }
static const struct full_imaging_io io = { allocate, release, set_source, send, size, source, record };
static const unsigned int D = 0x81cf61c3;
static unsigned char *request(unsigned int input) {
    void *p = 0; assert(!allocate(FULL_DMM_CP, &p, 40, 1));
    unsigned char *r = p; set_source(p, D);
    put16at(r, 0, 0x0018); put32at(r, 4, input); put16at(r, 20, 0);
    return r;
}
static void reset(void) {
    full_dmm_test_reset();
    for (unsigned int i = 0; i < 16; i++) if (live[i]) { free(header(live[i])); live[i] = 0; }
    queued = 0; send_failure = 0;bad_reply_size=0;
}
static struct full_dmm_snapshot snap(void) { struct full_dmm_snapshot s; full_dmm_snapshot(&s); return s; }

int main(void) {
    reset();
    int rc = 123; unsigned char *r = request(0x50b58);
    assert(full_dmm_dispatch(FULL_DMM_CP, r, &io, 1, &rc) == 1 && !rc);
    assert(queued && size(queued) == 40 && source(queued) == FULL_DMM_CP);
    const unsigned char *q = queued;
    assert((q[0] | q[1] << 8) == 0x0018);
    assert((short)(q[2] | q[3] << 8) <= 0);        /* ret_code <= 0 is success */
    /* unit is derived from the caller's byte count, page-aligned: 0x50b58 -> 0x51000 */
    assert(u32(q + 16) == 0x51000);
    struct full_dmm_snapshot s = snap();
    assert(s.queries == 1 && s.answered == 1 && s.last_input == 0x50b58 && s.last_reported_size==0x51000 && !s.faults);
    int frc = 123; assert(full_dmm_release_reply(D, queued, release, record, &frc) && !frc); queued = 0;
    assert(snap().waiter_freed == 1 && !snap().live_replies);
    puts("DMM_UNIT_SIZE_FRAME_0018_RET0_AND_WAITER_FREE_PASS");

    /* The owner answers from the state it actually holds. */
    full_dmm_test_set_unit_size(512);
    r = request(0);                        /* no byte count -> owner state */
    assert(full_dmm_dispatch(FULL_DMM_CP, r, &io, 1, &rc) == 1 && !rc);
    assert(u32((unsigned char *)queued + 16) == 512);
    assert(full_dmm_release_reply(D, queued, release, record, &frc) && !frc); queued = 0;
    puts("DMM_UNIT_SIZE_FALLBACK_AND_DERIVED_FROM_INPUT_PASS");

    /* Foreign frame, wrong length, and a send failure. */
    reset(); { void *p = 0; assert(!allocate(FULL_DMM_CP, &p, 40, 1)); set_source(p, D); put16at((unsigned char *)p, 0, 0x0019);
        assert(!full_dmm_dispatch(FULL_DMM_CP, p, &io, 1, &rc)); assert(!release(FULL_DMM_CP, p)); }
    reset(); { void *p = 0; assert(!allocate(FULL_DMM_CP, &p, 24, 1)); set_source(p, D); put16at((unsigned char *)p, 0, 0x0018);
        assert(!full_dmm_dispatch(FULL_DMM_CP, p, &io, 1, &rc)); assert(!release(FULL_DMM_CP, p)); }
    reset(); send_failure = 1; r = request(0x50b58);
    assert(full_dmm_dispatch(FULL_DMM_CP, r, &io, 1, &rc) && rc && !queued);
    s = snap(); /* send failure rolls the whole snapshot back; it is not an ownership fault. */
    assert(!s.faults && s.queries == 0 && s.answered == 0);
    assert(!release(FULL_DMM_CP, r));
    puts("DMM_UNIT_SIZE_FOREIGN_FRAME_LENGTH_AND_SEND_FAILURE_PASS");
    reset();r=request(0x1000u);
    assert(full_dmm_dispatch(FULL_DMM_CP,r,&io,1,&rc) && rc==-1021 && !queued && !snap().queries);
    assert(!release(FULL_DMM_CP,r));
    reset();r=request(0xfffff001u);
    assert(full_dmm_dispatch(FULL_DMM_CP,r,&io,1,&rc) && rc==-1021 && !queued && !snap().queries);
    assert(!release(FULL_DMM_CP,r));
    reset();r=request(0x50b58);bad_reply_size=1;
    assert(full_dmm_dispatch(FULL_DMM_CP,r,&io,1,&rc) && rc==-1021 && !queued && !snap().queries);
    assert(!release(FULL_DMM_CP,r));
    puts("DMM_OVERFLOW_AND_ALLOCATOR_WRONG_REPLY_SIZE_REJECTED_PASS");
    reset(); return 0;
}
