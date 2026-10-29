/* Host-only protocol/ownership tests for the kernel client; no hardware claim. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BACKUP_ENDPOINT_TEST
#include "client.c"

struct mock_message { u32 meta[6]; u8 body[UDATE_BYTES]; };
struct short_message { u32 meta[6]; u8 body[1]; };
static struct mock_message original, query, response, done;
static struct short_message tiny;
static u32 alloc_calls, alloc_fail_at, alloc_ids[2], dynamic_create, dynamic_owner;
static u32 queue_freed, sync_calls, sync_fail_at, receive_calls;
static long queue_free_rc, receive_rc;
static u32 response_ready, response_destination, response_size;
static u32 send_calls, send_fail_type, query_freed, done_freed, original_freed;
static u32 response_freed;
static long original_release_rc, response_free_rc;
static u32 original_release_id, query_release_id, response_release_id, done_release_id;
static u32 query_destination, done_destination, nested_busy, nested_rejected;
static long register_rc;

static void prepare(struct mock_message *m, u32 size, u32 source)
{
    memset(m, 0, sizeof(*m));
    m->meta[3] = source;
    m->meta[4] = size;
}
static void reset_case(void)
{
    memset(&original, 0, sizeof(original));
    memset(&query, 0, sizeof(query));
    memset(&response, 0, sizeof(response));
    memset(&done, 0, sizeof(done));
    memset(&tiny, 0, sizeof(tiny));
    busy = faults = unhandled = remote_valid = done_sent = 0;
    remote_before = remote_after = remote_elapsed = generation = 0;
    memset(remote_date, 0, sizeof(remote_date));
    memset(remote_timezone, 0, sizeof(remote_timezone));
    retained_request = 0;
    retained_request_id = 0;
    memset(retained, 0, sizeof(retained));
    alloc_calls = alloc_fail_at = dynamic_create = dynamic_owner = 0;
    queue_freed = queue_free_rc = sync_calls = sync_fail_at = receive_calls = 0;
    receive_rc = response_ready = response_destination = 0;
    response_size = UDATE_BYTES;
    send_calls = send_fail_type = query_freed = done_freed = original_freed = 0;
    response_freed = original_release_rc = response_free_rc = 0;
    original_release_id = query_release_id = response_release_id = done_release_id = 0;
    query_destination = done_destination = nested_busy = nested_rejected = 0;
    register_rc = 0;
    prepare(&original, UDATE_BYTES, UDATE_SOURCE);
    put32(original.body, 1);
    put16(original.body + 0x28, 1);
    prepare(&query, UDATE_BYTES, UDATE_SOURCE);
    prepare(&response, UDATE_BYTES, UDATE_SOURCE);
    put32(response.body, 2);
    put16(response.body + 0x10, 2026);
    response.body[0x12] = 10; response.body[0x13] = 25;
    response.body[0x14] = 12; response.body[0x15] = 34; response.body[0x16] = 56;
    put16(response.body + 0x20, (u16)-60);
    prepare(&done, UDATE_BYTES, UDATE_SOURCE);
    sender_handle = udate_sender;
}
static long call_sender(void) { return udate_sender(UDATE_TARGET1, original.body); }

long osal_reg_public(long slot)
{
    assert(slot == (long)&sender_handle && sender_handle == udate_sender);
    return register_rc;
}
long osal_valloc_msg_wait(u32 id, void **out, u32 size, u32 flags)
{
    (void)flags;
    assert(size == UDATE_BYTES);
    if (alloc_calls < 2) alloc_ids[alloc_calls] = id;
    ++alloc_calls;
    if (alloc_fail_at == alloc_calls) { *out = 0; return -12; }
    *out = alloc_calls == 1 ? query.body : done.body;
    return 0;
}
void osal_set_msg_src(void *message, u32 source)
{
    ((u32 *)message)[-3] = source;
}
u32 osal_get_msg_src(void *message) { return ((u32 *)message)[-3]; }
long osal_free_msg(u32 id, void *message)
{
    if (message == original.body) {
        original_release_id = id;
        if (original_release_rc) return original_release_rc;
        assert(!original_freed);
        original_freed = 1;
        return 0;
    }
    if (message == query.body) {
        query_release_id = id;
        assert(!query_freed);
        query_freed = 1;
        return 0;
    }
    if (message == response.body) {
        response_release_id = id;
        if (response_free_rc) return response_free_rc;
        assert(!response_freed);
        response_freed = 1;
        return 0;
    }
    if (message == done.body) {
        done_release_id = id;
        assert(!done_freed);
        done_freed = 1;
        return 0;
    }
    return -98;
}
long osal_snd_msg(u32 id, void *message)
{
    ++send_calls;
    if (message == query.body) {
        query_destination = id;
        assert(id == UDATE_SOURCE && osal_get_msg_src(query.body) == UDATE_SOURCE);
        assert(get32(query.body + 0x0c) == (0x90000123U | 0x80000000U));
        if (send_fail_type == 2) return -55;
        response_destination = get32(query.body + 0x0c);
        memcpy(response.body + 0x0c, query.body + 0x0c, 4);
        query_freed = 1; /* original receiver consumes query */
        response_ready = 1;
        return 0;
    }
    if (message == done.body) {
        done_destination = id;
        assert(id == UDATE_SOURCE && osal_get_msg_src(done.body) == UDATE_TARGET1);
        if (send_fail_type == 4) return -66;
        done_freed = 1; /* original local receiver consumes done */
        return 0;
    }
    return -97;
}
long osal_dynamic_id(u32 type, u32 owner, unsigned long value)
{
    if (type == 0x2a) {
        ++dynamic_create;
        dynamic_owner = owner;
        if (queue_free_rc == 0xdeadbeef) return -21;
        *(u32 *)value = 0x90000123U;
        return 0;
    }
    if (type == 0x4a) {
        if (queue_free_rc) return (long)queue_free_rc;
        ++queue_freed;
        return 0;
    }
    return -96;
}
long osal_rcv_msg_tmo(u32 id, void **out, long timeout)
{
    (void)timeout;
    ++receive_calls;
    if (nested_busy) {
        nested_busy = 0;
        long nested = call_sender();
        if (nested < 0) nested_rejected = 1;
    }
    if (receive_rc) return receive_rc;
    if (!response_ready || id != response_destination) return -55;
    response.meta[4] = response_size;
    *out = response.body;
    return 0;
}
long osal_snd_sync_direct(u32 id, void *message)
{
    u64 timer;
    assert(id == 0x910042 && get32(message) == 32);
    ++sync_calls;
    if (sync_fail_at == sync_calls) return -33;
    timer = sync_calls == 1 ? 1000 : 1600;
    memcpy((u8 *)message + 0x18, &timer, 8);
    return 0;
}
int printk(const char *format, ...) { (void)format; return 0; }

static void check_normal(void)
{
    long rc;
    reset_case();
    rc = call_sender();
    assert(rc == 0 && done_sent && remote_valid && generation == 1 && !faults);
    assert(remote_elapsed == 300 && !retained_request && original_freed);
    assert(query_freed && done_freed && response_freed && queue_freed == 1);
    assert(query_destination == UDATE_SOURCE && done_destination == UDATE_SOURCE);
    assert(response_destination == (0x90000123U | 0x80000000U));
    assert(get32(query.body + 0x0c) == response_destination);
    assert(get32(response.body + 0x0c) == response_destination);
    assert(alloc_ids[0] == UDATE_SOURCE && alloc_ids[1] == UDATE_SOURCE);
    assert(dynamic_create == 1 && dynamic_owner == 0x90 && sync_calls == 2 && receive_calls == 1);
    assert(original_release_id == UDATE_TARGET1 && response_release_id == response_destination);
}
static void check_unsupported(void)
{
    reset_case();
    assert(udate_sender(UDATE_SOURCE, original.body) == 0 && !send_calls && !original_freed);
    reset_case();
    put32(original.body + 8, 1);
    put32(original.body + 0x0c, 0x90000123U);
    assert(call_sender() == 0 && !send_calls && !dynamic_create && !original_freed);
    reset_case();
    original.meta[3] = UDATE_TARGET1;
    assert(call_sender() == 0 && !send_calls && !original_freed);
    reset_case();
    put32(original.body, 2);
    assert(call_sender() == 0 && !send_calls && !original_freed);
    reset_case();
    tiny.meta[3] = UDATE_SOURCE;
    tiny.meta[4] = 1;
    assert(udate_sender(UDATE_TARGET1, tiny.body) == 0 && !send_calls);
}
static void check_failure(u32 which)
{
    long rc;
    reset_case();
    switch (which) {
    case 1: receive_rc = -55; break;
    case 2: put32(response.body + 4, 0x00010000); break;
    case 3: response_free_rc = -88; break;
    case 4: queue_free_rc = -44; break;
    case 5: send_fail_type = 4; break;
    case 6: send_fail_type = 2; break;
    case 7: alloc_fail_at = 1; break;
    case 8: sync_fail_at = 1; break;
    case 9: response_size = 40; break;
    case 10: queue_free_rc = 0xdeadbeef; break;
    default: assert(0);
    }
    rc = call_sender();
    assert(rc < 0 && !done_sent && !original_freed && faults);
    if (which == 1) assert(!queue_freed);
    if (which == 2 || which == 3 || which == 9) assert(queue_freed == 1);
    if (which == 4) assert(!queue_freed);
    if (which == 3) assert(retained[0].message == response.body && retained[0].id == response_destination);
    if (which == 5) assert(done_release_id == UDATE_SOURCE && done_freed);
    if (which == 6) assert(query_release_id == UDATE_SOURCE && query_freed);
}
static void check_original_retry(void)
{
    long rc;
    reset_case();
    original_release_rc = -77;
    rc = call_sender();
    assert(rc == 0 && done_sent && retained_request == original.body && faults);
    assert(!original_freed && original_release_id == UDATE_TARGET1);
    send_calls = 0;
    rc = call_sender();
    assert(rc < 0 && !send_calls);
}
static void check_busy(void)
{
    reset_case();
    nested_busy = 1;
    assert(call_sender() == 0 && done_sent && nested_rejected);
}
static void check_register(void)
{
    reset_case();
    register_rc = -1018;
    assert(init_module() == -1018);
    reset_case();
    assert(init_module() == 0);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "normal")) check_normal();
    else if (!strcmp(argv[1], "unsupported")) check_unsupported();
    else if (!strcmp(argv[1], "original-retry")) check_original_retry();
    else if (!strcmp(argv[1], "busy")) check_busy();
    else if (!strcmp(argv[1], "register")) check_register();
    else {
        u32 which = (u32)atoi(argv[1]);
        assert(which >= 1 && which <= 10);
        check_failure(which);
    }
    return 0;
}
