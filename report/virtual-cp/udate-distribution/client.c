/* Bounded virtual UDATE remote endpoint, running at the original kernel
 * public-sender boundary. The userspace LD_PRELOAD hook cannot observe the
 * type1 emitted by udate.ko, so this module is deliberately kernel-side.
 * UDATE target1/type1/reason1/async is the default. An explicit backup_model
 * parameter enables the pinned virtual PCI fixture transaction; no CP execution,
 * sequence state, image data or generic CP acknowledgements are fabricated. */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;

extern int printk(const char *, ...);
extern long osal_reg_public(long);
extern long osal_valloc_msg_wait(u32, void **, u32, u32);
extern void osal_set_msg_src(void *, u32);
extern u32 osal_get_msg_src(void *);
extern long osal_snd_msg(u32, void *);
extern long osal_free_msg(u32, void *);
extern long osal_dynamic_id(u32, u32, unsigned long);
extern long osal_rcv_msg_tmo(u32, void **, long);
extern long osal_snd_sync_direct(u32, void *);

#define UDATE_SOURCE 0x809005c5u
#define UDATE_TARGET1 0x909005c5u
#define UDATE_BYTES 44u
#define UDATE_REPLY_TIMEOUT_MS 5000L
#define RETAINED_MAX 4u

static long (*sender_handle)(u32, void *);
static u32 busy, faults, unhandled, remote_valid, done_sent;
static u8 remote_date[16], remote_timezone[8];
static u64 remote_before, remote_after, remote_elapsed, generation;
static void *retained_request;
static u32 retained_request_id;
struct retained_message { void *message; u32 id; };
static struct retained_message retained[RETAINED_MAX];

static u16 get16(const u8 *p) { return (u16)p[0] | ((u16)p[1] << 8); }
static u32 get32(const u8 *p) {
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}
static u64 get64(const u8 *p) {
    u64 v = 0;
    u32 i;
    for (i = 0; i < 8; ++i) v |= (u64)p[i] << (8 * i);
    return v;
}
static void put16(u8 *p, u16 v) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
static void put32(u8 *p, u32 v) {
    p[0] = (u8)v; p[1] = (u8)(v >> 8); p[2] = (u8)(v >> 16); p[3] = (u8)(v >> 24);
}
static void zero(void *ptr, u32 bytes) {
    u8 *p = ptr;
    u32 i;
    for (i = 0; i < bytes; ++i) p[i] = 0;
}
static void copy(void *dst, const void *src, u32 bytes) {
    u8 *d = dst;
    const u8 *s = src;
    u32 i;
    for (i = 0; i < bytes; ++i) d[i] = s[i];
}
static long fail(const char *stage, long rc)
{
    if (!rc) rc = -1021;
    ++faults;
    printk("\0016UDATE_K_ERROR: stage=%s rc=%ld faults=%u virtual_completion=0\n",
           stage, rc, faults);
    return rc;
}
static void retain(u32 id, void *message)
{
    u32 i;
    for (i = 0; i < RETAINED_MAX; ++i) {
        if (!retained[i].message) {
            retained[i].message = message;
            retained[i].id = id;
            ++faults;
            printk("\0016UDATE_K_RETAIN: id=%#x message=%p slot=%u (no unsafe unwind)\n",
                   id, message, i);
            return;
        }
    }
    ++faults;
    printk("\0016UDATE_K_RETAIN: id=%#x message=%p overflow=1 (no unsafe unwind)\n",
           id, message);
}
static long release_or_retain(u32 id, void **message)
{
    long rc;
    if (!*message) return 0;
    rc = osal_free_msg(id, *message);
    if (rc) retain(id, *message);
    *message = 0;
    return rc;
}
#include "backup-endpoint.c"
#ifndef BACKUP_ENDPOINT_TEST
#include "backup-pci.c"
#endif

static long timer_read(u64 *value)
{
    u8 request[32];
    long rc;
    zero(request, sizeof(request));
    put32(request, 32);
    rc = osal_snd_sync_direct(0x910042, request);
    if (!rc) *value = get64(request + 0x18);
    return rc;
}
static u32 leap(u32 year) { return year % 4 == 0 && (year % 100 != 0 || year % 400 == 0); }
static u32 valid_date(const u8 *p)
{
    static const u8 days[] = {31,28,31,30,31,30,31,31,30,31,30,31};
    u32 year = get16(p), month = p[2], day = p[3], limit;
    if (year < 1 || month < 1 || month > 12 || day < 1 || p[12] > 2) return 0;
    limit = days[month - 1] + (month == 2 && leap(year));
    return day <= limit;
}
static u32 valid_zone_half(u16 value)
{
    short v = (short)value;
    return v == 0x7fff || (v >= -1440 && v <= 1440);
}
static u32 valid_timezone(const u8 *p)
{
    return valid_zone_half(get16(p)) && valid_zone_half(get16(p + 2)) && get16(p + 4) == 0;
}

/* The original public path calls this with the original qid/message. Other
 * public traffic retains the original no-service default; this module never
 * claims to have consumed it. */
static long udate_sender(u32 qid, void *message)
{
    const u8 *body = message;
    u32 size, source, type, sync, reason, queue = 0, reply_queue = 0;
    u32 queue_active = 0, queue_pending = 0, response_size = 0;
    void *query = 0, *reply = 0, *done = 0;
    u8 response[UDATE_BYTES];
    u64 before = 0, after = 0;
    const char *stage = "roundtrip";
    long rc;

    if (qid == BACKUP_TARGET) return backup_sender(qid, message);
    if (qid != UDATE_TARGET1 || !message) return 0;
    size = ((u32 *)message)[-2];
    source = osal_get_msg_src(message);
    type = size >= 4 ? get32(body) : 0;
    sync = size >= 12 ? get32(body + 8) : 0;
    reason = size >= 0x2a ? get16(body + 0x28) : 0;
    if (size != UDATE_BYTES || type != 1 || sync != 0 || reason != 1 || source != UDATE_SOURCE) {
        if (unhandled++ < 16)
            printk("\0016UDATE_K_UNHANDLED: destination=%#x source=%#x size=%u type=%#x sync=%#x reason=%#x original_default=1\n",
                   qid, source, size, type, sync, reason);
        return 0;
    }
    if (__sync_lock_test_and_set(&busy, 1)) return fail("busy", -1021);
    if (faults) {
        __sync_lock_release(&busy);
        return fail("latched-fault", -1021);
    }
    printk("\0016UDATE_K_REQUEST: destination=%#x source=%#x bytes=%u reason=1 async=1\n",
           qid, source, size);

    rc = timer_read(&before);
    if (rc) { __sync_lock_release(&busy); return fail("timer-before", rc); }
    rc = osal_dynamic_id(0x2a, 0x90, (unsigned long)&queue);
    if (rc || !queue) {
        __sync_lock_release(&busy);
        return fail("queue-create", rc ? rc : -1021);
    }
    queue_active = 1;
    reply_queue = queue | 0x80000000U;

    stage = "query-allocate";
    rc = osal_valloc_msg_wait(source, &query, UDATE_BYTES, 1);
    if (rc || !query) goto cleanup;
    zero(query, UDATE_BYTES);
    put32(query, 2);
    put32((u8 *)query + 8, 1);
    /* The original 0x1b98 reply wrapper consumes body+0x0c, not OSAL source. */
    put32((u8 *)query + 0x0c, reply_queue);
    osal_set_msg_src(query, UDATE_SOURCE);
    stage = "query-send";
    rc = osal_snd_msg(source, query);
    if (rc) goto cleanup;
    query = 0;
    queue_pending = 1;
    stage = "receive";
    printk("\0016UDATE_K_QUERY: destination=%#x reply_queue=%#x timer_before=%llu\n",
           source, reply_queue, (unsigned long long)before);
    rc = osal_rcv_msg_tmo(reply_queue, &reply, UDATE_REPLY_TIMEOUT_MS);
    if (rc || !reply) goto cleanup;
    queue_pending = 0;
    response_size = ((u32 *)reply)[-2];
    if (response_size == UDATE_BYTES) copy(response, reply, UDATE_BYTES);
    stage = "response-free";
    rc = release_or_retain(reply_queue, &reply);
    if (rc) goto cleanup;
    stage = "queue-free";
    rc = osal_dynamic_id(0x4a, 0, reply_queue);
    queue_active = 0;
    if (rc) goto cleanup;
    stage = "timer-after";
    rc = timer_read(&after);
    if (rc || after < before) goto cleanup;
    stage = "response-validate";
    if (response_size != UDATE_BYTES || get32(response) != 2 || get32(response + 4) != 0 ||
        !valid_date(response + 0x10) || !valid_timezone(response + 0x20)) {
        rc = -1021;
        goto cleanup;
    }
    copy(remote_date, response + 0x10, 16);
    copy(remote_timezone, response + 0x20, 8);
    remote_before = before;
    remote_after = after;
    remote_elapsed = (after - before) >> 1;
    ++generation;
    remote_valid = 1;
    done_sent = 0;
    printk("\0016UDATE_K_RESPONSE: generation=%llu date=%04u-%02u-%02uT%02u:%02u:%02u type=%u timezone=%d/%d elapsed=%llu status=0\n",
           (unsigned long long)generation, get16(response + 0x10), response[0x12], response[0x13],
           response[0x14], response[0x15], response[0x16], response[0x1c],
           (short)get16(response + 0x20), (short)get16(response + 0x22),
           (unsigned long long)remote_elapsed);

    stage = "done-allocate";
    rc = osal_valloc_msg_wait(source, &done, UDATE_BYTES, 1);
    if (rc || !done) goto cleanup;
    zero(done, UDATE_BYTES);
    put32(done, 4);
    put16((u8 *)done + 0x28, 1);
    /* Local receive-side identity: done_notified extracts target1 from source. */
    osal_set_msg_src(done, UDATE_TARGET1);
    stage = "done-send";
    rc = osal_snd_msg(source, done);
    if (rc) goto cleanup;
    done = 0;
    done_sent = 1;
    rc = osal_free_msg(qid, message);
    if (rc) {
        retained_request = message;
        retained_request_id = qid;
        ++faults;
        printk("\0016UDATE_K_RETAIN: original request id=%#x message=%p rc=%ld\n",
               qid, message, rc);
    }
    __sync_lock_release(&busy);
    printk("\0016UDATE_K_DONE: generation=%llu target=1 done_source=%#x timer_before=%llu timer_after=%llu elapsed=%llu request_free_rc=%ld faults=%u request_retained=%u done_sent=1 virtual_completion=1 hardware_ready=0 camera_capture_verified=0\n",
           (unsigned long long)generation, UDATE_TARGET1,
           (unsigned long long)before, (unsigned long long)after,
           (unsigned long long)remote_elapsed, rc, faults, retained_request != 0);
    return 0;

cleanup:
    if (query) (void)release_or_retain(source, &query);
    if (reply) (void)release_or_retain(reply_queue, &reply);
    if (done) (void)release_or_retain(source, &done);
    if (queue_active && queue_pending) {
        ++faults;
        printk("\0016UDATE_K_QUEUE_RETAINED: queue=%#x response-pending; no normal completion\n",
               reply_queue);
    } else if (queue_active) {
        long freed = osal_dynamic_id(0x4a, 0, reply_queue);
        if (freed) ++faults;
    }
    __sync_lock_release(&busy);
    return fail(stage, rc ? rc : -1021);
}

int __attribute__((section(".init.text"))) init_module(void)
{
    long rc;
#ifndef BACKUP_ENDPOINT_TEST
    if (backup_model) {
        rc = backup_pci_prepare();
        if (rc) return (int)rc;
    }
#endif
    sender_handle = udate_sender;
    rc = osal_reg_public((long)&sender_handle);
#ifndef BACKUP_ENDPOINT_TEST
    if (backup_model) {
        if (rc) backup_pci_release();
        else backup_pci_connect();
    }
#endif
    printk("\0016UDATE_K_REGISTER: rc=%ld (%s)\n", rc,
           rc == 0 ? "bounded target1 UDATE public endpoint registered" :
                     "NOT registered - another public sender owns the slot");
    return rc == 0 ? 0 : (int)rc;
}
