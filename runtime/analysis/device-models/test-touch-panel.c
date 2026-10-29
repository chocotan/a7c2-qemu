/* SPDX-License-Identifier: MIT */
#include "touch-panel-device.h"
#include <assert.h>
#include <stddef.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>

#define CALLER 0x81cf61c9u
struct block { unsigned int size, source, pool; unsigned char body[64]; };
static struct block request_block, reply_block;
static int alloc_rc, send_rc, request_free_rc, reply_free_rc, alloc_null, duplicate_request;
static unsigned int alloc_calls, send_calls, request_free_calls, reply_free_calls, send_destination;
static void *sent_reply;
static char last_tag[80], last_line[640];
static pthread_mutex_t mock_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t mock_cond = PTHREAD_COND_INITIALIZER;
static int alloc_block, alloc_entered, alloc_release;

static struct block *header(void *p) { return (struct block *)((char *)p - offsetof(struct block, body)); }
static int mock_allocate(unsigned int pool, void **out, unsigned int bytes, unsigned int count) {
    assert(pool == CALLER && count == 1 && bytes == 12);alloc_calls++;
    if (alloc_block) {
        pthread_mutex_lock(&mock_mutex);alloc_entered = 1;pthread_cond_broadcast(&mock_cond);
        while (!alloc_release) pthread_cond_wait(&mock_cond, &mock_mutex);
        pthread_mutex_unlock(&mock_mutex);
    }
    if (alloc_rc) return alloc_rc;
    if (alloc_null) { *out = 0; return 0; }
    if (duplicate_request) { *out = request_block.body; return 0; }
    reply_block.size = bytes;reply_block.pool = pool;*out = reply_block.body;return 0;
}
static int mock_release(unsigned int pool, void *p) {
    if (p == request_block.body) {
        assert(pool == FULL_TOUCH_PANEL_INPUT);
        request_free_calls++;return request_free_rc;
    }
    if (p == reply_block.body) {
        assert(pool == CALLER || pool == FULL_TOUCH_PANEL_INPUT);
        reply_free_calls++;return reply_free_rc;
    }
    return -99;
}
static void mock_set_source(void *p, unsigned int source) { header(p)->source = source; }
static unsigned int mock_size(void *p) { return header(p)->size; }
static unsigned int mock_source(void *p) { return header(p)->source; }
static int mock_send(unsigned int destination, void *p) {
    send_calls++;send_destination = destination;sent_reply = p;return send_rc;
}
static void mock_record(const char *tag, const char *line) {
    pthread_mutex_lock(&mock_mutex);
    snprintf(last_tag, sizeof last_tag, "%s", tag);
    snprintf(last_line, sizeof last_line, "%s", line);
    pthread_mutex_unlock(&mock_mutex);
}
static const struct full_imaging_io io = {
    mock_allocate, mock_release, mock_set_source, mock_send, mock_size, mock_source, mock_record
};
static void *request(void) { return request_block.body; }
static void *reply(void) { return reply_block.body; }
static void make_request(unsigned int enable) {
    static const unsigned char head[8] = {0x0d,0x20,0x46,0x01,10,0,1,0x80};
    memcpy(request_block.body, head, 8);request_block.body[8] = (unsigned char)enable;request_block.body[9] = 0;
    request_block.size = 10;request_block.source = CALLER;request_block.pool = FULL_TOUCH_PANEL_INPUT;
}
static void reset_case(void) {
    memset(&request_block, 0, sizeof request_block);memset(&reply_block, 0, sizeof reply_block);
    alloc_rc = send_rc = request_free_rc = reply_free_rc = alloc_null = duplicate_request = 0;
    alloc_block = alloc_entered = alloc_release = 0;
    alloc_calls = send_calls = request_free_calls = reply_free_calls = send_destination = 0;
    sent_reply = 0;memset(last_tag, 0, sizeof last_tag);memset(last_line, 0, sizeof last_line);
    full_touch_panel_test_reset();make_request(0);
}
static void check_normal(unsigned int enable) {
    reset_case();make_request(enable);int result = 99;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == 0);
    assert(send_calls == 1 && send_destination == CALLER && sent_reply == reply());
    assert(reply_block.size == 12 && reply_block.source == FULL_TOUCH_PANEL_INPUT);
    static const unsigned char header_bytes[8] = {0x0d,0x20,0x46,0x11,12,0,1,0x80};
    assert(!memcmp(reply(), header_bytes, 8));
    assert(!memcmp(reply_block.body + 8, (unsigned char[]){0,0,0x59,0}, 4));
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.cache == enable && s.readback == enable && s.applied == 1 && s.queued == 1);
    assert(s.requests == 1 && s.request_freed == 1 && s.live_replies == 1 && s.clean_completion == 1);
    assert(s.control_submissions == 1 && s.control_result_verified == 0 && s.outer_status == 0x590000);
    static const unsigned char f02f_head[8] = {1,0x20,0x2f,0xf0,12,0,1,0};
    assert(!memcmp(s.f02f, f02f_head, 8) && s.f02f[8] == enable && !s.f02f[9] && !s.f02f[10] && !s.f02f[11]);
    assert(!memcmp(s.control, (unsigned char[]){3,0,0,0,enable,0,0,0}, 8));
    assert(request_free_calls == 1 && reply_free_calls == 0);
    int rc = 99;assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == 0);
    full_touch_panel_snapshot(&s);assert(s.live_replies == 0 && s.waiter_freed == 1 && s.native_freed == 1);
    assert(reply_free_calls == 1);
}
static void check_reuse(void) {
    reset_case();make_request(0);int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == 0);
    int rc = 0;assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == 0);
    make_request(1);assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == 0);
    assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == 0);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.requests == 2 && s.applied == 2 && s.queued == 2 && s.request_freed == 2 && s.waiter_freed == 2);
    assert(s.cache == 1 && s.readback == 1 && s.live_replies == 0);
}
static void check_invalid(void) {
    for (unsigned int kind = 0; kind < 4; kind++) {
        reset_case();
        if (kind == 0) request_block.body[8] = 2;
        if (kind == 1) request_block.body[9] = 1;
        if (kind == 2) request_block.body[4] = 9;
        if (kind == 3) request_block.source = FULL_TOUCH_PANEL_INPUT;
        int result = 0;assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == -1021);
        assert(send_calls == 0 && request_free_calls == 0);
        struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
        assert(s.applied == 0 && s.cache == 0 && s.readback == 0 && s.clean_completion == 0 && s.faults == 0);
    }
    reset_case();int result = 77;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 0, &result) == 0 && result == 77 && send_calls == 0);
}
static void check_alloc_fail(void) {
    reset_case();alloc_rc = -55;int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == -55);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.pending == 0 && s.applied == 0 && s.queued == 0 && send_calls == 0 && request_free_calls == 0);
}
static void check_send_fail(void) {
    reset_case();send_rc = -66;int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == -66);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.pending == 0 && s.applied == 0 && s.queued == 0 && s.cache == 0 && s.readback == 0 && s.clean_completion == 0);
    assert(reply_free_calls == 1 && request_free_calls == 0 && s.faults == 0);
}
static void check_request_free_fail(void) {
    reset_case();request_free_rc = -77;int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == 0);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.faults == 1 && s.retained_request == request() && s.clean_completion == 0 && s.request_freed == 0);
    int rc = 0;assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == 0);
    make_request(1);result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == -1021);
    assert(send_calls == 1);
}
static void check_reply_free_fail(void) {
    reset_case();reply_free_rc = -88;int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == 0);
    int rc = 0;assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == -88);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.live_replies == 1 && s.retained_reply == reply() && s.waiter_freed == 0);
    reply_free_rc = 0;assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == 0);
    full_touch_panel_snapshot(&s);assert(s.live_replies == 0 && s.retained_reply == 0 && s.waiter_freed == 1);
}
static void *concurrent_worker(void *unused) {
    (void)unused;int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == 0);
    return NULL;
}
static void check_concurrent(void) {
    reset_case();alloc_block = 1;pthread_t thread;
    assert(!pthread_create(&thread, NULL, concurrent_worker, NULL));
    pthread_mutex_lock(&mock_mutex);
    while (!alloc_entered) pthread_cond_wait(&mock_cond, &mock_mutex);
    pthread_mutex_unlock(&mock_mutex);
    make_request(0);int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == -1021);
    assert(send_calls == 0);
    pthread_mutex_lock(&mock_mutex);alloc_release = 1;pthread_cond_broadcast(&mock_cond);pthread_mutex_unlock(&mock_mutex);
    assert(!pthread_join(thread, NULL));
    int rc = 0;assert(full_touch_panel_release_reply(CALLER, reply(), mock_release, mock_record, &rc) == 1 && rc == 0);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.requests == 1 && s.applied == 1 && s.queued == 1 && s.pending == 0 && s.faults == 0);
    assert(s.cache == 0 && s.readback == 0 && s.clean_completion == 1 && s.live_replies == 0);
}
static void check_duplicate(void) {
    reset_case();duplicate_request = 1;int result = 0;
    assert(full_touch_panel_dispatch(FULL_TOUCH_PANEL_INPUT, request(), &io, 1, &result) == 1 && result == -1021);
    struct full_touch_panel_snapshot s;full_touch_panel_snapshot(&s);
    assert(s.faults == 1 && s.applied == 0 && send_calls == 0 && request_free_calls == 0);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "normal0")) check_normal(0);
    else if (!strcmp(argv[1], "normal1")) check_normal(1);
    else if (!strcmp(argv[1], "reuse")) check_reuse();
    else if (!strcmp(argv[1], "invalid")) check_invalid();
    else if (!strcmp(argv[1], "alloc-fail")) check_alloc_fail();
    else if (!strcmp(argv[1], "send-fail")) check_send_fail();
    else if (!strcmp(argv[1], "request-free-fail")) check_request_free_fail();
    else if (!strcmp(argv[1], "reply-free-fail")) check_reply_free_fail();
    else if (!strcmp(argv[1], "duplicate")) check_duplicate();
    else if (!strcmp(argv[1], "concurrent")) check_concurrent();
    else return 2;
    printf("TOUCH_PANEL_TEST_PASS %s\n", argv[1]);return 0;
}
