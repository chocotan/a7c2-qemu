/* SPDX-License-Identifier: MIT */
/* Host test for 92840747/032a (AdfSystemSoundPath). The request/reply shapes come
 * from the original bytes: request `0d 20 2a 03 0a 00 01 80 pp 00` and the outer
 * reply `0d 20 2a 13 0c 00 01 80 00 00 58 00`, where the bridge forwards only the
 * low three bits of request+8 and a non-zero path with those bits clear is e002. */
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
static void put16(unsigned char *p, unsigned int n) { p[0] = (unsigned char)n; p[1] = (unsigned char)(n >> 8); }
static void put16at(unsigned char *p, unsigned int at, unsigned int n) { put16(p + at, n); }

static unsigned int u32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (unsigned int)p[3] << 24; }
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
static void record(const char *kind, const char *line) {
    fprintf(stderr,"EV %s%s\n",kind,line);
    if (!strcmp(kind,"FULL_AUDIO_UNSUPPORTED ")) fprintf(stderr,"   -> reason: %s\n",line);
}
static const struct full_imaging_io io = { allocate, release, set_source, send, size, source, record };

static const unsigned int D = 0x81cf61c2;
static unsigned char *request(unsigned int path) {
    void *p = 0; assert(!allocate(FULL_AUDIO_INPUT, &p, 10, 1)); unsigned char *r = p;
    set_source(p, D);
    /* Original wire carries no destination: 0d20 / 2a03 / 0a00 / 0180 / pp00. */
    put16at(r, 0, 0x200d); put16at(r, 2, 0x032a); put16at(r, 4, 0x000a);
    put16at(r, 6, 0x8001); put16at(r, 8, path);
    return r;
}
static void reset(void) {
    full_audio_test_reset();
    for (unsigned int i = 0; i < 32; i++) if (live[i]) { free(header(live[i])); live[i] = 0; }
    queued = 0; send_failure = 0;
}
static struct full_audio_snapshot snap(void) { struct full_audio_snapshot s; full_audio_snapshot(&s); return s; }
static void finish(unsigned int expected_status) {
    assert(queued);
    const unsigned char *p = queued;
    assert(size(queued) == 12 && source(queued) == FULL_AUDIO_INPUT);
    assert(p[0] == 0x0d && p[1] == 0x20 && p[2] == 0x2a && p[3] == 0x13);
    assert(p[4] == 0x0c && p[5] == 0 && p[6] == 1 && p[7] == 0x80);
    assert(u32(p + 8) == (0x580000u | expected_status));
    int rc = 123; assert(full_audio_release_reply(D, queued, release, record, &rc) && !rc); queued = 0;
}

int main(void) {
    reset();
    /* A non-zero path applies and is remembered; the first 0->non-zero edge needs 0127. */
    int rc = 123; unsigned char *r = request(4);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) == 1 && !rc);
    finish(0);
    struct full_audio_snapshot s = snap();
    assert(s.sound_path == 4 && s.sound_path_applied == 1 && s.sound_path_applied_count == 1 && !s.sound_path_rejected);
    /* The dispatcher already freed the request on the successful path. */

    /* A second non-zero path just updates the route (no new 0127 edge). */
    r = request(5); assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) == 1 && !rc);
    finish(0); s = snap(); assert(s.sound_path == 5 && s.sound_path_applied_count == 2);

    /* Low three bits all zero is the original e002 rejection, not a success. */
    r = request(8); assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) == 1 && !rc);
    finish(0xe002); s = snap(); assert(s.sound_path == 5 && s.sound_path_rejected == 1);
    puts("SOUND_PATH_032A_APPLY_REJECT_AND_ROUTE_STATE_PASS");

    /* Wrong length and a send failure must stay caller-owned with a real rollback. */
    reset(); { void *p = 0; assert(!allocate(FULL_AUDIO_INPUT, &p, 12, 1)); unsigned char *q = p; set_source(p, D);
        put16at(q, 0, 0x200d); put16at(q, 2, 0x032a); put16at(q, 4, 0x000a);
        put16at(q, 6, 0x8001); put16at(q, 8, 4);
        assert(full_audio_dispatch(FULL_AUDIO_INPUT, q, &io, FULL_AUDIO_BOOT, &rc) && rc == -1021 && !queued);
        assert(!release(FULL_AUDIO_INPUT, q)); }
    reset(); send_failure = 1; r = request(4);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT, r, &io, FULL_AUDIO_BOOT, &rc) && rc && !queued);
    s = snap(); /* send failure rolls back the state; it is not an ownership fault. */
    assert(!s.sound_path && !s.sound_path_applied_count);
    assert(!release(FULL_AUDIO_INPUT, r));
    puts("SOUND_PATH_032A_LENGTH_AND_SEND_FAILURE_CALLER_OWNERSHIP_PASS");
    reset(); return 0;
}
