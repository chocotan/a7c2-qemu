/* SPDX-License-Identifier: MIT */
/* 92840747/0119 = vdf_set_panel_reverse, recovered from appFw.so 0x34e9f58:
 *   request  28 B: 0d20 / 1901 / 1c00 / 0180 / body[8]=a body[9]=b body[10]=specified
 *   reply    12 B: send_and_wait_cmp_i(0x92840747, req, 28, out, 12)
 * The wrapper's switch maps input enum 1..4 onto those three body flags. */
#define _GNU_SOURCE
#include "audio-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct message { unsigned int owner, source, bytes; unsigned char data[]; };
static void *live[32], *queued;
static unsigned int send_failure;

static struct message *header(void *p) { return (struct message *)((char *)p - offsetof(struct message, data)); }
static void put16at(unsigned char *p, unsigned int at, unsigned int n) { p[at] = (unsigned char)n; p[at + 1] = (unsigned char)(n >> 8); }
static int allocate(unsigned int id, void **out, unsigned int n, unsigned int wait) {
    assert(wait == 1);
    struct message *m = calloc(1, sizeof *m + n); assert(m);
    m->owner = id; m->bytes = n; *out = m->data;
    for (unsigned int i = 0; i < 32; i++) if (!live[i]) { live[i] = *out; return 0; }
    abort();
}
static int release(unsigned int id, void *p) {
    assert(p && header(p)->owner == id);
    for (unsigned int i = 0; i < 32; i++) if (live[i] == p) { live[i] = 0; memset(p, 0xde, header(p)->bytes); free(header(p)); return 0; }
    abort();
}
static unsigned int size(void *p) { return header(p)->bytes; }
static unsigned int source(void *p) { return header(p)->source; }
static void set_source(void *p, unsigned int id) { header(p)->source = id; }
static int send(unsigned int id, void *p) { assert(header(p)->owner == id && !queued); if (send_failure) return -77; queued = p; return 0; }
static void record(const char *kind, const char *line) { (void)kind; (void)line; }
static const struct full_imaging_io io = { allocate, release, set_source, send, size, source, record };

static const unsigned int D = 0x81cf61c1;
static unsigned char *request(unsigned int a, unsigned int b, unsigned int specified) {
    void *p = 0; assert(!allocate(FULL_AUDIO_INPUT, &p, 28, 1));
    unsigned char *r = p; set_source(p, D);
    put16at(r, 0, 0x200d); put16at(r, 2, 0x0119); put16at(r, 4, 0x001c); put16at(r, 6, 0x8001);
    r[8] = (unsigned char)a; r[9] = (unsigned char)b; r[10] = (unsigned char)specified;
    return r;
}
static void reset(void) {
    full_audio_test_reset();
    for (unsigned int i = 0; i < 32; i++) if (live[i]) { free(header(live[i])); live[i] = 0; }
    queued = 0; send_failure = 0;
}
static struct full_audio_snapshot snap(void) { struct full_audio_snapshot s; full_audio_snapshot(&s); return s; }

int main(void) {
    reset();
    int rc = 123; unsigned char *r = request(1, 0, 1);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) == 1 && !rc);
    assert(queued && size(queued) == 12 && source(queued) == FULL_AUDIO_INPUT);
    /* Reply byte 3 is (cmd>>8)|0x10 = 0x11 for the 0x01xx family. */
    static const unsigned char expected[] = {0x0d, 0x20, 0x19, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x58, 0};
    assert(!memcmp(queued, expected, sizeof expected));
    struct full_audio_snapshot s = snap();
    assert(s.panel_reverse == 1 && s.panel_reverse_applied == 1 && s.panel_reverse_count == 1);
    int frc = 123; assert(full_audio_release_reply(D, queued, release, record, &frc) && !frc); queued = 0;
    puts("PANEL_REVERSE_0119_REPLY_0D201911_AND_STATE_PASS");

    /* Second axis and both axes. */
    r = request(0, 1, 1);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) == 1 && !rc);
    assert(queued); s = snap(); assert(s.panel_reverse == 2);
    assert(full_audio_release_reply(D, queued, release, record, &frc) && !frc); queued = 0;
    r = request(1, 1, 1);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) == 1 && !rc);
    assert(queued); s = snap(); assert(s.panel_reverse == 3 && s.panel_reverse_count == 3);
    assert(full_audio_release_reply(D, queued, release, record, &frc) && !frc); queued = 0;
    puts("PANEL_REVERSE_0119_AXIS_COMBINATIONS_PASS");

    /* Wrong length is not this command; send failure rolls back and keeps caller ownership. */
    reset(); { void *p = 0; assert(!allocate(FULL_AUDIO_INPUT, &p, 10, 1)); set_source(p, D);
        put16at(p, 0, 0x200d); put16at(p, 2, 0x0119); put16at(p, 4, 0x001c); put16at(p, 6, 0x8001);
        assert(full_audio_dispatch(FULL_AUDIO_INPUT, p, &io, FULL_AUDIO_BOOT, &rc) && rc == -1021 && !queued);
        assert(!release(FULL_AUDIO_INPUT, p)); }
    reset(); send_failure = 1; r = request(1, 0, 1);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) && rc && !queued);
    s = snap(); assert(!s.panel_reverse && !s.faults);
    assert(!release(FULL_AUDIO_INPUT, r));
    puts("PANEL_REVERSE_0119_LENGTH_AND_SEND_FAILURE_PASS");
    reset(); return 0;
}
