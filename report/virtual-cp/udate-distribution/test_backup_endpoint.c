/* Real 40B input objects and independent 4096B replies under ASan/UBSan. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define BACKUP_ENDPOINT_TEST
static void test_release(unsigned int *);
#define __sync_lock_release(pointer) test_release(pointer)
#include "client.c"
#undef __sync_lock_release

struct backup_request_message { u32 meta[6]; u8 body[BACKUP_REQUEST_BYTES]; };
struct backup_reply_message { u32 meta[6]; u8 body[BACKUP_REPLY_BYTES]; };
static struct backup_request_message request;
static struct backup_reply_message outgoing;
static u8 primary[BACKUP_DATA_BYTES], initial[BACKUP_DATA_BYTES];
static u32 freezes, unlocks, reads, frozen, sent, request_free, reply_free;
static u32 fail_allocate, fail_send, fail_read, fail_freeze, fail_unlock;
static u32 fail_request_free, fail_reply_free, recurse;
static long read_after;
static u32 reply_id, request_id, interleave_release, interleave_seen;
static void test_release(unsigned int *pointer)
{
    __atomic_store_n(pointer, 0, __ATOMIC_RELEASE);
    if (pointer == &backup_busy && interleave_release) {
        interleave_release = 0;
        fail_allocate = 0;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0);
        assert(!freezes && !sent);
        interleave_seen = 1;
    }
}

static void frame(u32 stage, u32 queue)
{
    memset(&request, 0, sizeof(request));
    request.meta[3] = queue;
    request.meta[4] = BACKUP_REQUEST_BYTES;
    put32(request.body, 0x30);
    put32(request.body + 8, BACKUP_TARGET);
    put32(request.body + 12, queue);
    for (u32 at = 16; at <= 28; at += 4) put32(request.body + at, 1);
    put32(request.body + 32, stage);
}
static long freeze_primary(void *p)
{
    (void)p;
    ++freezes;
    primary[9] = 1;
    frozen = 1;
    if (recurse) {
        recurse = 0;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0);
    }
    return fail_freeze ? -44 : 0;
}
static long read_primary(void *p, u32 offset, void *out, u32 size)
{
    (void)p;
    assert(frozen && offset <= BACKUP_DATA_BYTES && size <= BACKUP_DATA_BYTES - offset);
    ++reads;
    if (fail_read && (long)offset >= read_after) return -55;
    memcpy(out, primary + offset, size);
    return 0;
}
static long unlock_primary(void *p)
{
    (void)p;
    assert(frozen);
    ++unlocks;
    if (fail_unlock) return -66;
    frozen = 0;
    return 0;
}
static void reset_backup(void)
{
    backup_enabled = 1;
    backup_busy = backup_faults = backup_frozen = 0;
    backup_generation = backup_readback = 0;
    memset(backup_retained, 0, sizeof(backup_retained));
    backup_backend = (struct backup_backend){NULL, freeze_primary, read_primary, unlock_primary};
    memcpy(primary, initial, sizeof(primary));
    memset(&outgoing, 0xcc, sizeof(outgoing));
    freezes = unlocks = reads = frozen = sent = request_free = reply_free = 0;
    fail_allocate = fail_send = fail_read = fail_freeze = fail_unlock = 0;
    fail_request_free = fail_reply_free = recurse = 0;
    read_after = 0;
    reply_id = request_id = interleave_release = interleave_seen = 0;
    frame(3, 0x803e0123);
}

long osal_valloc_msg_wait(u32 id, void **out, u32 size, u32 flags)
{
    assert(size == BACKUP_REPLY_BYTES && flags == 1 && id == get32(request.body + 12));
    if (fail_allocate) { *out = NULL; return -12; }
    outgoing.meta[4] = size;
    *out = outgoing.body;
    return 0;
}
long osal_snd_msg(u32 id, void *message)
{
    assert(message == outgoing.body && id == get32(request.body + 12));
    assert(osal_get_msg_src(message) == BACKUP_SOURCE);
    u8 expected[BACKUP_REQUEST_BYTES];
    memcpy(expected, request.body, sizeof(expected));
    if (get32(expected + 32) == 3) put32(expected + 32, 1);
    assert(!memcmp(expected, message, sizeof(expected)));
    for (u32 i = BACKUP_REQUEST_BYTES; i < BACKUP_REPLY_BYTES; ++i)
        assert(((u8 *)message)[i] == 0);
    if (fail_send) return -77;
    ++sent;
    reply_id = id;
    return 0;
}
long osal_free_msg(u32 id, void *message)
{
    if (message == request.body) {
        assert(id == BACKUP_TARGET && !request_free);
        request_id = id;
        if (fail_request_free) return -88;
        request_free = 1;
        return 0;
    }
    assert(message == outgoing.body && id == get32(request.body + 12) && !reply_free);
    reply_id = id;
    if (fail_reply_free) return -99;
    reply_free = 1;
    return 0;
}

void osal_set_msg_src(void *message, u32 source) { ((u32 *)message)[-3] = source; }
u32 osal_get_msg_src(void *message) { return ((u32 *)message)[-3]; }
long osal_reg_public(long slot) { (void)slot; return 0; }
long osal_dynamic_id(u32 type, u32 owner, unsigned long value)
{ (void)type; (void)owner; (void)value; assert(0); return -1; }
long osal_rcv_msg_tmo(u32 id, void **out, long timeout)
{ (void)id; (void)out; (void)timeout; assert(0); return -1; }
long osal_snd_sync_direct(u32 id, void *message)
{ (void)id; (void)message; assert(0); return -1; }
int printk(const char *format, ...) { (void)format; return 0; }

static void normal(void)
{
    assert(udate_sender(BACKUP_TARGET, request.body) == 0);
    assert(sent == 1 && request_free && !reply_free && freezes == 1 && frozen);
    assert(backup_frozen && !backup_faults && backup_generation == 1);
    assert(backup_readback == BACKUP_FROZEN_FNV64);
    assert(reads == (BACKUP_DATA_BYTES + 255) / 256);
    for (u32 i = 0; i < BACKUP_DATA_BYTES; ++i)
        assert(primary[i] == (i == 9 ? 1 : initial[i]));
    frame(0, 0x803e0456); /* unlock uses a new queue, not the stage3 queue */
    request_free = 0;
    assert(backup_sender(BACKUP_TARGET, request.body) == 0);
    assert(sent == 2 && request_free && !frozen && !backup_frozen && !backup_faults);
    assert(unlocks == 1 && reply_id == 0x803e0456 && request_id == BACKUP_TARGET);
    assert(primary[9] == 1 && !memcmp(primary + 0x20, initial + 0x20, 4));
}
static void malformed(u32 which)
{
    switch (which) {
    case 0: request.meta[4] = 39; break;
    case 1: put32(request.body, 0x31); break;
    case 2: put32(request.body + 4, 1); break;
    case 3: put32(request.body + 8, 0x803e0811); break;
    case 4: put32(request.body + 12, 0x803e0000); break;
    case 5: request.meta[3] = 0x803e0000; put32(request.body + 12, 0x803e0000); break;
    case 6: request.meta[3] = 0x803e8001; put32(request.body + 12, 0x803e8001); break;
    case 7: put32(request.body + 20, 0); break;
    case 8: put32(request.body + 32, 2); break;
    case 9: put32(request.body + 36, 1); break;
    default: assert(0);
    }
    assert(backup_sender(BACKUP_TARGET, request.body) < 0);
    assert(!freezes && !sent && !request_free && !reply_free);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    FILE *source = fopen(argv[2], "rb");
    assert(source && !fseek(source, 0xed000, SEEK_SET));
    assert(fread(initial, 1, sizeof(initial), source) == sizeof(initial));
    assert(fgetc(source) == EOF && !ferror(source));
    fclose(source);
    reset_backup();
    if (!strcmp(argv[1], "normal")) normal();
    else if (!strcmp(argv[1], "disabled")) {
        backup_enabled = 0;
        assert(backup_sender(BACKUP_TARGET, request.body) == 0 && !freezes && !sent);
    } else if (!strcmp(argv[1], "no-backend")) {
        backup_backend.read = NULL;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && !freezes && !sent);
    } else if (!strcmp(argv[1], "order")) {
        frame(0, 0x803e0123);
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && !unlocks && !sent);
    } else if (!strcmp(argv[1], "duplicate")) {
        assert(backup_sender(BACKUP_TARGET, request.body) == 0);
        request_free = 0;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && freezes == 1 && sent == 1);
    } else if (!strcmp(argv[1], "corrupt")) {
        primary[BACKUP_DATA_BYTES - 1] ^= 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && frozen && !sent && !request_free && reply_free);
    } else if (!strcmp(argv[1], "short-object")) {
        struct {u32 meta[6]; u8 body[1];} short_request = {{0}, {0}};
        short_request.meta[4] = 1;
        assert(backup_sender(BACKUP_TARGET, short_request.body) < 0 && !sent);
    } else if (!strcmp(argv[1], "allocate")) {
        fail_allocate = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && !frozen && !sent && !request_free);
    } else if (!strcmp(argv[1], "release-race")) {
        fail_allocate = interleave_release = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && interleave_seen);
        assert(backup_faults && !freezes && !sent && !request_free);
    } else if (!strcmp(argv[1], "freeze")) {
        fail_freeze = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && frozen && !sent && !request_free && reply_free);
    } else if (!strcmp(argv[1], "read")) {
        fail_read = 1; read_after = BACKUP_DATA_BYTES - 256;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && frozen && !sent && !request_free && reply_free);
    } else if (!strcmp(argv[1], "send")) {
        fail_send = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && frozen && !sent && !request_free && reply_free);
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && freezes == 1);
    } else if (!strcmp(argv[1], "request-free")) {
        fail_request_free = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) == 0 && sent && frozen && !request_free);
        assert(backup_retained[0].message == request.body && backup_retained[0].id == BACKUP_TARGET);
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && sent == 1);
    } else if (!strcmp(argv[1], "reply-free")) {
        fail_send = fail_reply_free = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && !sent && frozen && !request_free && !reply_free);
        assert(backup_retained[0].message == outgoing.body && backup_retained[0].id == 0x803e0123);
    } else if (!strcmp(argv[1], "unlock")) {
        assert(backup_sender(BACKUP_TARGET, request.body) == 0);
        frame(0, 0x803e0456); request_free = 0; fail_unlock = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && frozen && !request_free && sent == 1);
    } else if (!strcmp(argv[1], "busy")) {
        recurse = 1;
        assert(backup_sender(BACKUP_TARGET, request.body) < 0 && frozen && !sent && !request_free);
    } else malformed((u32)atoi(argv[1]));
    return 0;
}
