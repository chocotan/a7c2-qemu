/* SPDX-License-Identifier: MIT */
/* Host test for 912f0335 (digital level). The request is six little-endian u32
 * without a Dataflow header; AP reads only u32[4] (+0x10) as the result, and the
 * feature-disabled path returns 0 without waiting for an angle sample. */
#define _GNU_SOURCE
#include "dig-level-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct message { unsigned int owner, source, bytes; unsigned char data[]; };
static void *live[16], *queued;
static unsigned int send_failure;

static struct message *header(void *p) { return (struct message *)((char *)p - offsetof(struct message, data)); }
static void put32(unsigned char *p, unsigned int n) { for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(n >> (8 * i)); }
static unsigned int u32(const unsigned char *p) { return p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24; }
static int allocate(unsigned int id, void **out, unsigned int n, unsigned int wait) {
    assert(wait == 1);
    struct message *m = calloc(1, sizeof *m + n); assert(m);
    m->owner = id; m->bytes = n; *out = m->data;
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
static unsigned char *request(unsigned int command) {
    void *p = 0; assert(!allocate(FULL_DIG_LEVEL_INPUT, &p, 24, 1));
    unsigned char *r = p; set_source(p, D); put32(r, command);
    return r;
}
static void reset(void) {
    full_dig_level_test_reset();
    for (unsigned int i = 0; i < 16; i++) if (live[i]) { free(header(live[i])); live[i] = 0; }
    queued = 0; send_failure = 0;
}
static struct full_dig_level_snapshot snap(void) { struct full_dig_level_snapshot s; full_dig_level_snapshot(&s); return s; }
static void finish(void) {
    assert(queued);
    const unsigned char *p = queued;
    assert(size(queued) == 24 && source(queued) == FULL_DIG_LEVEL_INPUT);
    assert(u32(p + 16) == 0);       /* +0x10 result: AP maps 0 -> model 0 */
    int rc = 123; assert(full_dig_level_release_reply(D, queued, release, record, &rc) && !rc); queued = 0;
}

int main(void) {
    reset();
    int rc = 123; unsigned char *r = request(3);
    assert(full_dig_level_dispatch(FULL_DIG_LEVEL_INPUT, r, &io, 1, &rc) == 1 && !rc);
    finish();
    struct full_dig_level_snapshot s = snap();
    assert(s.queries == 1 && s.enables == 1 && !s.disables && s.result == 0);
    assert(!s.faults && s.waiter_freed == 1 && s.live_replies == 0);
    puts("DIG_LEVEL_ENABLE_COMMAND_ZERO_RESULT_AND_WAITER_FREE_PASS");

    /* command 4 is the "off" variant and must take the same honest path. */
    r = request(4);
    assert(full_dig_level_dispatch(FULL_DIG_LEVEL_INPUT, r, &io, 1, &rc) == 1 && !rc);
    finish(); s = snap(); assert(s.queries == 2 && s.disables == 1);
    puts("DIG_LEVEL_DISABLE_COMMAND_PASS");

    /* Other commands are not this service; wrong length is not this service. */
    r = request(5); assert(!full_dig_level_dispatch(FULL_DIG_LEVEL_INPUT, r, &io, 1, &rc));
    assert(!release(FULL_DIG_LEVEL_INPUT, r));
    { void *p = 0; assert(!allocate(FULL_DIG_LEVEL_INPUT, &p, 20, 1)); set_source(p, D);
      assert(!full_dig_level_dispatch(FULL_DIG_LEVEL_INPUT, p, &io, 1, &rc));
      assert(!release(FULL_DIG_LEVEL_INPUT, p)); }

    /* Send failure must roll back and stay caller-owned. */
    send_failure = 1; r = request(3);
    assert(full_dig_level_dispatch(FULL_DIG_LEVEL_INPUT, r, &io, 1, &rc) && rc && !queued);
    s = snap(); assert(s.queries == 2 && !s.faults);
    assert(!release(FULL_DIG_LEVEL_INPUT, r));
    send_failure = 0;
    puts("DIG_LEVEL_FOREIGN_COMMAND_LENGTH_AND_SEND_FAILURE_PASS");

    /* A concurrent caller must be rejected, not interleaved: the reply lease slots
     * and the single pending marker belong to one request at a time. */
    reset();
    { struct full_dig_level_snapshot s0 = snap(); (void)s0; }
    full_dig_level_test_set_pending(1, D);
    { unsigned char *q = request(3);
      int r = 123;
      assert(full_dig_level_dispatch(FULL_DIG_LEVEL_INPUT, q, &io, 1, &r) == 1 && r == -1021 && !queued);
      assert(!release(FULL_DIG_LEVEL_INPUT, q)); }
    full_dig_level_test_set_pending(0, 0);
    puts("DIG_LEVEL_CONCURRENT_CALLER_REJECTED_PASS");
    reset(); return 0;
}
