/* SPDX-License-Identifier: MIT */
/* Implementation: gpt-6.1-sol, thinking=max; 2026-10-28 functional profile. */
#define _GNU_SOURCE
#include "functional-jpeg-codec.h"
#include "functional-camera-bridge.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#pragma weak functional_mpr_memory_acquire_sds
/* The guest libc predates glibc's C23 scanf exports. */
extern int jpeg_scan_maps(const char *, const char *, ...) __asm__("__isoc99_sscanf");
#define EXEC_SYMBOL FUNCTIONAL_JPEG_CODEC_EXEC_SYMBOL
#define RES_SYMBOL FUNCTIONAL_JPEG_CODEC_RES_SYMBOL
#define MAIN_EXEC_SYMBOL FUNCTIONAL_JPEG_CODEC_MAIN_EXEC_SYMBOL
#define MAIN_RES_SYMBOL FUNCTIONAL_JPEG_CODEC_MAIN_RES_SYMBOL
#define COMP_EXEC_SYMBOL FUNCTIONAL_JPEG_CODEC_COMP_EXEC_SYMBOL
#define COMP_RES_SYMBOL FUNCTIONAL_JPEG_CODEC_COMP_RES_SYMBOL
#define GET_POINTER_SYMBOL "_ZN14AvbbcParamCtrl16ParameterControl8GetValueEjRPv"
enum { WITHOUT_PIN, MAIN, MAIN_COMP };
#define GET_ID_SYMBOL "_ZN20InfraAvbbcMsgManager9GetOsalIdEv"
#define CID_SYMBOL "_ZN20InfraAvbbcMsgManager10ConvertCidEt"
#define MID_SYMBOL "_ZN20InfraAvbbcMsgManager13ConvertCmdMidEtt"
#define MSG_CTOR "_ZN16DataflowInfraMsgC1Ev"
#define MSG_DTOR "_ZN16DataflowInfraMsgD1Ev"
#define MSG_DATA "_ZN16DataflowInfraMsg14SetDataflowMsgEPvt"
#define MSG_SOURCE "_ZN16DataflowInfraMsg8SetSrcIdEj"
#define SENDER_CTOR "_ZN19DataflowInfraSenderC1Ev"
#define SENDER_DTOR "_ZN19DataflowInfraSenderD1Ev"
#define SENDER_SEND "_ZN19DataflowInfraSender9SendASyncEjP16DataflowInfraMsg"
#define REQUEST_BYTES 80u
#define ENVELOPE_BYTES 24u
#define PACKET_BYTES (ENVELOPE_BYTES + REQUEST_BYTES)
#define REPLY_BYTES 16u
#define SDK_MSG_BYTES 408u
#define SDK_SENDER_BYTES 8u
#define NATIVE_ERROR 0x201u
#define NATIVE_WAIT 0x200u
/* K3cdb4 maps the original range/error bit 0x10 to service status 5. */
#define SERVICE_ERROR 5u
#define PREFIX_BYTES 575u
_Static_assert(sizeof(uintptr_t) == 8, "original SDK requires the 64-bit ABI");

struct original_api {
    uint32_t (*exec)(void *, const uint8_t *);
    uint32_t (*res)(void *, const uint8_t *, uint16_t);
    uint32_t (*main_exec)(void *, const uint8_t *), (*comp_exec)(void *, const uint8_t *);
    uint32_t (*main_res)(void *, const uint8_t *, uint16_t), (*comp_res)(void *, const uint8_t *, uint16_t);
    uint32_t (*get_pointer)(void *, uint32_t, void **);
    uint32_t (*get_id)(void *);
    uint16_t (*cid)(void *, uint16_t);
    uint16_t (*mid)(void *, uint16_t, uint16_t);
    void (*msg_ctor)(void *), (*msg_dtor)(void *);
    int (*msg_data)(void *, void *, uint16_t);
    int (*msg_source)(void *, uint32_t);
    void (*sender_ctor)(void *), (*sender_dtor)(void *);
    int (*sender_send)(void *, uint32_t, void *);
    uintptr_t base;
};
struct invocation {
    void *object, *manager, *control;
    uintptr_t caller;
    uint32_t qid, context, key;
    uint16_t width, height;
    uint8_t mode, kind, selector;
    long tid;
    int dispatch_error, submitted;
};
struct reply_observation {
    uintptr_t address;
    uint8_t packet[ENVELOPE_BYTES + REPLY_BYTES];
    int free_attempted, free_result;
};
struct jpeg_job {
    struct invocation native, completion;
    void *config;
    uintptr_t ack_body_address;
    struct fcam_native_origin origin;
    struct functional_mpr_memory_lease lease;
    uint8_t request[REQUEST_BYTES], wire[PACKET_BYTES], ack[REPLY_BYTES], done[REPLY_BYTES];
    uint64_t sequence, model_instance, output_fnv, model_token, model_fnv;
    size_t output_bytes, model_bytes, model_offset;
    long ack_receiver_pid, ack_receiver_tid, done_receiver_pid, done_receiver_tid;
    struct reply_observation replies[2];
    int result_error, ready, ack_publishing, ack_received, ack_consumed;
    int done_publishing, done_received, cancelled, callback_active, comp_started;
};
static struct original_api original;
static struct functional_jpeg_codec_snapshot stats;
static struct jpeg_job pending;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wake = PTHREAD_COND_INITIALIZER;
static pthread_t worker;
static _Atomic pid_t owner;
static _Atomic int enabled;
static int stopping, starting;
static void (*record_callback)(const char *, const char *);
static _Thread_local struct invocation *current;
static _Thread_local int in_record, in_callback;
#ifdef FJPEG_HOST_TEST
void functional_jpeg_test_lock_owner(void) { pthread_mutex_lock(&lock); }
void functional_jpeg_test_unlock_owner(void) { pthread_mutex_unlock(&lock); }
#endif

uint32_t functional_jpeg_exec(void *, const uint8_t *) __asm__(EXEC_SYMBOL);
uint32_t functional_jpeg_res(void *, const uint8_t *, uint16_t) __asm__(RES_SYMBOL);
uint32_t functional_jpeg_main_exec(void *, const uint8_t *) __asm__(MAIN_EXEC_SYMBOL);
uint32_t functional_jpeg_main_res(void *, const uint8_t *, uint16_t) __asm__(MAIN_RES_SYMBOL);
uint32_t functional_jpeg_comp_exec(void *, const uint8_t *) __asm__(COMP_EXEC_SYMBOL);
uint32_t functional_jpeg_comp_res(void *, const uint8_t *, uint16_t) __asm__(COMP_RES_SYMBOL);

static size_t object_bytes(unsigned kind) { return kind == WITHOUT_PIN ? 0x30 : 0x28; }
static uintptr_t object_vtable(unsigned kind) {
    return original.base + (kind == WITHOUT_PIN ? 0x1af448 : kind == MAIN ? 0x1af7c0 : 0x1af808);
}
static uintptr_t exec_entry(unsigned kind) {
    return original.base + (kind == WITHOUT_PIN ? 0x11b654 : kind == MAIN ? 0x1226c4 : 0x122dfc);
}

static uint16_t u16(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }
static uint32_t u32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const uint8_t *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static void p16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void p32(uint8_t *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
static uint64_t hash_more(uint64_t v, const void *pointer, size_t bytes) {
    const uint8_t *p = pointer;
    for (size_t i = 0; i < bytes; ++i) { v ^= p[i]; v *= UINT64_C(1099511628211); }
    return v;
}
static uint64_t hash(const void *pointer, size_t bytes) {
    return hash_more(UINT64_C(14695981039346656037), pointer, bytes);
}
static void hex_bytes(const uint8_t *p, size_t bytes, char *out) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < bytes; ++i) { out[2*i] = digits[p[i] >> 4]; out[2*i+1] = digits[p[i] & 15]; }
    out[2*bytes] = 0;
}
static int process_guard(void) {
    pid_t pid = atomic_load_explicit(&owner, memory_order_acquire);
    return !pid ? -ENODEV : pid == getpid() ? 0 : -ECHILD;
}
static int span(uintptr_t p, size_t n) { return p && n && n <= UINTPTR_MAX - p; }
static int separate(uintptr_t a, size_t an, uintptr_t b, size_t bn) {
    return span(a, an) && span(b, bn) && (a + an <= b || b + bn <= a);
}
static int memory_access(const void *pointer, size_t bytes, int need_write) {
    uintptr_t next = (uintptr_t)pointer;
    if (!span(next, bytes)) return -EFAULT;
    FILE *f = fopen("/proc/self/maps", "r");
    if (!f) return -errno;
    uintptr_t end = next + bytes;
    unsigned long lo, hi;
    char line[512], permissions[5];
    while (next < end && fgets(line, sizeof line, f)) {
        if (jpeg_scan_maps(line, "%lx-%lx %4s", &lo, &hi, permissions) != 3) continue;
        if (next < lo) break;
        if (next >= hi) continue;
        if (permissions[0] != 'r' || (need_write && permissions[1] != 'w')) break;
        next = hi < end ? hi : end;
    }
    int rc = next == end ? 0 : -EFAULT;
    if (fclose(f) && !rc) rc = -errno;
    return rc;
}
/* /proc/self/mem bypasses PROT_NONE; check ordinary read access before bounded pread.
 * Source owners must still keep mappings alive; this check is not a lifetime pin. */
static int read_object(const void *pointer, void *out, size_t bytes) {
    uintptr_t p = (uintptr_t)pointer;
    if (!span(p, bytes) || p > INT64_MAX || bytes > INT64_MAX - p) return -EFAULT;
    int saved = errno, rc = memory_access(pointer, bytes, 0);
    if (rc) { errno = saved; return rc; }
    int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
    if (fd < 0) { rc = -errno; errno = saved; return rc; }
    ssize_t n;
    do { n = pread(fd, out, bytes, (off_t)p); } while (n < 0 && errno == EINTR);
    rc = n == (ssize_t)bytes ? 0 : n < 0 ? -errno : -EFAULT;
    if (close(fd) && !rc) rc = -errno;
    errno = saved;
    return rc;
}
static void *next_symbol(const char *name) {
    int saved = errno;
#ifdef FJPEG_HOST_TEST
    extern void *functional_jpeg_test_next(const char *);
    void *p = functional_jpeg_test_next(name);
#else
    void *p = dlsym(RTLD_NEXT, name);
#endif
    errno = saved;
    return p;
}
#define LOAD(target, symbol) do { \
    void *jpeg_symbol_ = next_symbol(symbol); \
    _Static_assert(sizeof(target) == sizeof(jpeg_symbol_), "POSIX function ABI"); \
    memcpy(&(target), &jpeg_symbol_, sizeof(target)); \
} while (0)

#ifndef FJPEG_HOST_TEST
static int function_pin(void *function, uintptr_t *base, uintptr_t va,
    size_t bytes, uint64_t expected) {
    Dl_info info;
    if (!function || !dladdr(function, &info) || !info.dli_fbase) return -ELIBBAD;
    uintptr_t b = (uintptr_t)info.dli_fbase;
    if ((*base && *base != b) || va > UINTPTR_MAX - b ||
        (uintptr_t)function != b + va) return -ELIBBAD;
    uint8_t copy[REQUEST_BYTES * 32];
    if (bytes > sizeof copy || read_object(function, copy, bytes) || hash(copy, bytes) != expected)
        return -ELIBBAD;
    *base = b;
    return 0;
}
#define PIN(member, module, va, bytes, fnv) do { \
    void *jpeg_function_ = NULL; \
    memcpy(&jpeg_function_, &a->member, sizeof jpeg_function_); \
    if ((rc = function_pin(jpeg_function_, &(module), va, bytes, UINT64_C(fnv)))) return rc; \
} while (0)
#endif
#ifndef FJPEG_HOST_TEST
static int vtable_pin(uintptr_t base, uintptr_t va,
    uint32_t (*exec)(void *, const uint8_t *), uint32_t (*res)(void *, const uint8_t *, uint16_t)) {
    uintptr_t entries[2], expected[2];
    memcpy(&expected[0], &exec, sizeof exec); memcpy(&expected[1], &res, sizeof res);
    return read_object((void *)(base + va), entries, sizeof entries) ||
        memcmp(entries, expected, sizeof entries) ? -ELIBBAD : 0;
}
#endif
static int bind_original(struct original_api *a) {
    memset(a, 0, sizeof *a);
    LOAD(a->exec, EXEC_SYMBOL); LOAD(a->res, RES_SYMBOL); LOAD(a->get_id, GET_ID_SYMBOL);
    LOAD(a->main_exec, MAIN_EXEC_SYMBOL); LOAD(a->main_res, MAIN_RES_SYMBOL);
    LOAD(a->comp_exec, COMP_EXEC_SYMBOL); LOAD(a->comp_res, COMP_RES_SYMBOL);
    LOAD(a->get_pointer, GET_POINTER_SYMBOL);
    LOAD(a->cid, CID_SYMBOL); LOAD(a->mid, MID_SYMBOL);
    LOAD(a->msg_ctor, MSG_CTOR); LOAD(a->msg_dtor, MSG_DTOR);
    LOAD(a->msg_data, MSG_DATA); LOAD(a->msg_source, MSG_SOURCE);
    LOAD(a->sender_ctor, SENDER_CTOR); LOAD(a->sender_dtor, SENDER_DTOR);
    LOAD(a->sender_send, SENDER_SEND);
    if (!a->main_exec || !a->main_res || !a->comp_exec || !a->comp_res || !a->get_pointer ||
        !a->exec || !a->res || !a->get_id || !a->cid || !a->mid || !a->msg_ctor ||
        !a->msg_dtor || !a->msg_data || !a->msg_source || !a->sender_ctor ||
        !a->sender_dtor || !a->sender_send) return -ENOSYS;
#ifdef FJPEG_HOST_TEST
    extern int functional_jpeg_test_binding(uintptr_t *);
    return functional_jpeg_test_binding(&a->base);
#else
    int rc;
    uintptr_t dataflow = 0;
    PIN(exec, a->base, 0x11b654, 0x2f4, 0x2535db6d89d94c53);
    PIN(res, a->base, 0x11a9dc, 0x25c, 0xfccb813884a3d4c0);
    PIN(main_exec, a->base, 0x1226c4, 0x444, 0x4e8508c9915d6146);
    PIN(main_res, a->base, 0x120e64, 0x60, 0x464e48ea08c2cf3a);
    PIN(comp_exec, a->base, 0x122dfc, 0x4c, 0xb3d0afdf302e393f);
    PIN(comp_res, a->base, 0x122b44, 0x2b8, 0xd26134b62e7fd103);
    PIN(get_pointer, a->base, 0xa46e4, 0xc4, 0x5f07e9e6ab435299);
    if ((rc = function_pin((void *)(a->base + 0x13b66c), &a->base, 0x13b66c,
            0xc8, UINT64_C(0x9879ebd536f27865))) ||
        (rc = function_pin((void *)(a->base + 0x13b734), &a->base, 0x13b734,
            0x104, UINT64_C(0xd3146ef860069be0)))) return rc;
    PIN(get_id, a->base, 0x138ffc, 8, 0xba87cdd4c17b5902);
    PIN(cid, a->base, 0x138ff4, 8, 0x2bd36e115f7294e9);
    PIN(mid, a->base, 0x138fec, 8, 0x455be0d904fe9ee7);
    PIN(msg_ctor, dataflow, 0x32218, 0x24, 0x6ab1de7b58b86a2a);
    PIN(msg_dtor, dataflow, 0x321ec, 4, 0x2fe42bc03800fb45);
    PIN(msg_data, dataflow, 0x32564, 0x134, 0x078c3124bf5055d2);
    PIN(msg_source, dataflow, 0x32454, 12, 0xa139fee8191d01e5);
    PIN(sender_ctor, dataflow, 0x340d4, 0x14, 0x3984a58233a62517);
    PIN(sender_dtor, dataflow, 0x340a8, 4, 0x2fe42bc03800fb45);
    PIN(sender_send, dataflow, 0x34110, 0x120, 0x3d22ab1c50df0259);
    /* Each actual relocated address point must bind its own export pair. */
    if (vtable_pin(a->base, 0x1af448, functional_jpeg_exec, functional_jpeg_res) ||
        vtable_pin(a->base, 0x1af7c0, functional_jpeg_main_exec, functional_jpeg_main_res) ||
        vtable_pin(a->base, 0x1af808, functional_jpeg_comp_exec, functional_jpeg_comp_res)) return -ELIBBAD;
    return 0;
#endif
}
static int native_caller(uintptr_t pc, int response) {
#ifdef FJPEG_HOST_TEST
    extern int functional_jpeg_test_caller(uintptr_t, int);
    return functional_jpeg_test_caller(pc, response);
#else
    return response ? pc == original.base + 0x13b788 :
        pc == original.base + 0x13b6ec || pc == original.base + 0x13b7e0;
#endif
}
static int native_comp_caller(uintptr_t pc) {
#ifdef FJPEG_HOST_TEST
    extern int functional_jpeg_test_caller(uintptr_t, int);
    return functional_jpeg_test_caller(pc, 2);
#else
    return pc == original.base + 0x13b7e0;
#endif
}
static void note_detail(const char *operation, const struct jpeg_job *j, int rc, const char *detail) {
    if (in_record) return;
    int saved = errno;
    pthread_mutex_lock(&lock);
    void (*record)(const char *, const char *) = record_callback;
    uintptr_t base = original.base;
    pthread_mutex_unlock(&lock);
    if (record) {
        char text[1024];
        int length = snprintf(text, sizeof text,
            "operation=%s rc=%d pid=%ld tid=%ld producer_tid=%ld sequence=%" PRIu64
            " original_base=%#" PRIxPTR " exec_entry=%#" PRIxPTR " caller=%#" PRIxPTR
            " object=%p manager=%p control=%p context=%u key=%#x source=%#x destination=%#x"
            " command=%#x native_bytes=%u trigger_fnv=%016" PRIx64 " response_tag=%u"
            " model_instance=%" PRIu64 " bytes=%zu output_fnv=%016" PRIx64 " stream_mode=%u"
            " kind=%s selector=%u comp_object=%p physical_asic_compatible=0 capture_verified=0%s%s",
            operation, rc, (long)getpid(), (long)syscall(SYS_gettid), j ? j->native.tid : 0,
            j ? j->sequence : 0, base, base ? exec_entry(j ? j->native.kind : WITHOUT_PIN) : 0,
            j ? j->native.caller : 0, j ? j->native.object : NULL,
            j ? j->native.manager : NULL, j ? j->native.control : NULL,
            j ? j->native.context : 0, j ? j->native.key : 0,
            j ? j->origin.source : 0, j ? j->origin.destination : 0,
            j ? j->origin.command : 0, j ? j->origin.bytes : 0,
            j ? j->origin.wire_fnv1a64 : 0, j ? u16(j->request + 0x14) : 0,
            j ? j->model_instance : 0, j ? j->output_bytes : 0, j ? j->output_fnv : 0,
            j ? j->native.mode : 0, j && j->native.kind == MAIN ? "main" : "without-pin",
            j ? j->native.selector : 0, j ? j->completion.object : NULL,
            detail ? " " : "", detail ? detail : "");
        /* Keep JPEG receipts within the adapter's existing 1024-byte budget. */
        if (length < 0 || (size_t)length >= sizeof text)
            snprintf(text, sizeof text,
                "operation=receipt-format-error rc=%d pid=%ld sequence=%" PRIu64
                " physical_asic_compatible=0 capture_verified=0 requested_operation=%s",
                -EOVERFLOW, (long)getpid(), j ? j->sequence : 0, operation);
        in_record = 1; record("FUNCTIONAL_JPEG_CODEC ", text); in_record = 0;
    }
    errno = saved;
}
static void note(const char *operation, const struct jpeg_job *j, int rc) {
    note_detail(operation, j, rc, NULL);
}
static void lease_note(const struct jpeg_job *j) {
    char detail[512];
    snprintf(detail, sizeof detail,
        "sds_type=%u sds_handle=%#x sds_offset=%u stream_position=%u lease_offset=%zu"
        " lease_address=%#" PRIxPTR " lease_capacity=%zu lease_generation=%" PRIu64
        " lease_token=%#" PRIx64 " lease_group=%u lease_unit=%u lease_area=%u lease_unit_type=%u",
        u32(j->request+0x24), u32(j->request+0x28), u32(j->request+0x2c), u32(j->request+0x38),
        j->lease.span.offset, j->lease.address, j->lease.bytes, j->lease.span.generation,
        j->lease.token, j->lease.span.group, j->lease.span.unit, j->lease.span.area, j->lease.span.unit_type);
    note_detail("original-request-lease", j, 0, detail);
}
/* The real lease pins retired mappings; validation on both sides rejects retirement. */
static int output_readback(const struct jpeg_job *j, const uint8_t *expected, size_t bytes, uint64_t *out) {
    if (!bytes || bytes > j->lease.bytes) return -EINVAL;
    int rc = functional_mpr_memory_validate(&j->lease);
    uint64_t value = UINT64_C(14695981039346656037);
    uint8_t actual[4096];
    for (size_t offset = 0; !rc && offset < bytes;) {
        size_t n = bytes - offset < sizeof actual ? bytes - offset : sizeof actual;
        rc = read_object((void *)(j->lease.address + offset), actual, n);
        if (!rc && expected && memcmp(actual, expected + offset, n)) rc = -EIO;
        if (!rc) value = hash_more(value, actual, n);
        offset += n;
    }
    if (!rc) rc = functional_mpr_memory_validate(&j->lease);
    if (!rc) *out = value;
    return rc;
}
static int envelope(const uint8_t *p, size_t size, size_t body) {
    return size == ENVELOPE_BYTES + body && u32(p + 4) == UINT32_C(0xa0a0a0a0) &&
        u16(p + 8) == 1 && u16(p + 10) == size && u32(p + 12) == ENVELOPE_BYTES &&
        u32(p + 16) == size && u16(p + ENVELOPE_BYTES + 4) == body;
}
static int valid_io(const struct full_imaging_io *io) {
    return io && io->release && io->size && io->source;
}
static void reply_body(uint8_t out[REPLY_BYTES], const uint8_t *request,
    int completion, uint32_t status, uint32_t value) {
    memset(out, 0, REPLY_BYTES);
    p16(out, u16(request + (completion ? 0x10 : 0x0c)));
    p16(out + 2, u16(request + (completion ? 0x12 : 0x0e)));
    p16(out + 4, REPLY_BYTES); p16(out + 6, u16(request + 0x14));
    p32(out + 8, status); p32(out + 12, value);
}
static int send_reply(const struct jpeg_job *j, const uint8_t *body) {
    _Alignas(16) uint8_t message[SDK_MSG_BYTES] = {0};
    _Alignas(8) uint8_t sender[SDK_SENDER_BYTES] = {0};
    original.msg_ctor(message); original.sender_ctor(sender);
    int rc = original.msg_data(message, (void *)body, REPLY_BYTES);
    if (!rc) rc = original.msg_source(message, FUNCTIONAL_JPEG_CODEC_SID);
    if (!rc) rc = original.sender_send(sender, j->native.qid, message);
    original.sender_dtor(sender); original.msg_dtor(message);
    return rc;
}
/* Service-level output: source DQT/DHT/SOF prefix plus real SOS/entropy/EOI.
 * The native kernel's 0x23d prefix writer is downstream of hardware, and is NOT
 * executed at this intercepted SDK service boundary. */
static int jpeg_shape(const uint8_t *p, size_t bytes, uint32_t width, uint32_t height) {
    static const uint8_t sos[] = {0xff,0xda,0,12,3,1,0,2,0x11,3,0x11,0,63,0};
    static const uint8_t components[] = {3,1,0x21,0,2,0x11,1,3,0x11,1};
    if (bytes <= PREFIX_BYTES + sizeof sos + 2 || p[0] != 0xff || p[1] != 0xd8 ||
        memcmp(p + 2, (const uint8_t[]){0xff,0xdb,0,0x84}, 4) || p[6] || p[71] != 1 ||
        memcmp(p + 136, (const uint8_t[]){0xff,0xc4,1,0xa2}, 4) ||
        hash(p + 140, 416) != UINT64_C(0x816e1ce1c54b3469) ||
        memcmp(p + 556, (const uint8_t[]){0xff,0xc0,0,17,8}, 5) ||
        ((uint32_t)p[561] << 8 | p[562]) != height ||
        ((uint32_t)p[563] << 8 | p[564]) != width ||
        memcmp(p + 565, components, sizeof components) ||
        memcmp(p + PREFIX_BYTES, sos, sizeof sos) ||
        p[bytes - 2] != 0xff || p[bytes - 1] != 0xd9) return -EPROTO;
    for (unsigned i = 0; i < 64; ++i) if (!p[7 + i] || !p[72 + i]) return -EPROTO;
    for (size_t i = PREFIX_BYTES + sizeof sos; i < bytes - 2; ++i) {
        if (p[i] != 0xff) continue;
        if (++i >= bytes - 2 || p[i] != 0) return -EPROTO;
    }
    return 0;
}
static int encode(struct jpeg_job *j) {
    uint8_t state[FCAM_STATE_BYTES], input[16] = {0};
    struct fcam_bridge_result result;
    int rc = fcam_bridge_call(&j->origin, FCAM_OP_STATE, NULL, 0, state, sizeof state, &result);
    if (rc) return rc;
    uint32_t width = u16(j->request + 0x40), height = u16(j->request + 0x42);
    if (j->native.kind == WITHOUT_PIN) {
        if (!width) width = u32(state + FCAM_S_WIDTH);
        if (!height) height = u32(state + FCAM_S_HEIGHT);
    }
    uint32_t quality = u32(state + FCAM_S_QUALITY);
    j->model_instance = u64(state + FCAM_S_INSTANCE);
    if (result.used != sizeof state || result.required != sizeof state ||
        result.model_instance != j->model_instance || !j->model_instance ||
        u32(state) != FCAM_ABI_VERSION || !(u32(state + FCAM_S_CAPS) & FCAM_CAP_STILL) ||
        !width || width > FCAM_MAX_STILL_WIDTH || !height || height > FCAM_MAX_STILL_HEIGHT ||
        !quality || quality > 100) return -EPROTO;
    p32(input, FCAM_STILL_FULL_JPEG); p32(input + 4, width);
    p32(input + 8, height); p32(input + 12, quality);
    size_t capacity = j->lease.bytes;
    if (capacity <= FCAM_MAX_RESULT_BYTES - 2) capacity += 2;
    if (capacity > FCAM_MAX_RESULT_BYTES) capacity = FCAM_MAX_RESULT_BYTES;
    uint8_t *encoded = malloc(capacity);
    if (!encoded) return -ENOMEM;
    rc = fcam_bridge_call(&j->origin, FCAM_OP_STILL, input, sizeof input, encoded, capacity, &result);
    if (!rc && (result.model_instance != j->model_instance || !result.result_token ||
        result.used != result.required || result.used > capacity)) rc = -EPROTO;
    if (!rc) rc = jpeg_shape(encoded, result.used, width, height);
    size_t skip = j->request[0x4b] ? 0 : 2;
    size_t bytes = !rc ? result.used - skip : 0;
    if (!rc && (!bytes || bytes > j->lease.bytes || bytes > UINT32_MAX)) rc = -ENOSPC;
    if (!rc) rc = functional_mpr_memory_write(&j->lease, 0, encoded + skip, bytes);
    if (!rc) {
#ifdef FJPEG_HOST_TEST
        extern void functional_jpeg_test_after_copy(void *, size_t);
        functional_jpeg_test_after_copy((void *)j->lease.address, bytes);
#endif
        uint64_t readback = 0;
        rc = output_readback(j, encoded + skip, bytes, &readback);
        if (!rc && readback != hash(encoded + skip, bytes)) rc = -EIO;
        if (!rc) {
            j->output_fnv = readback; j->output_bytes = bytes;
            j->model_token = result.result_token; j->model_bytes = result.used;
            j->model_fnv = hash(encoded, result.used); j->model_offset = skip;
        }
    }
    free(encoded);
    return rc;
}
static void run_job(struct jpeg_job *j) {
    int rc = encode(j);
    j->result_error = rc;
    /* ACK is delayed until real encoding/readback, never a substitute for it. */
    reply_body(j->ack, j->request, 0, rc ? SERVICE_ERROR : 0, (uint32_t)j->sequence);
    reply_body(j->done, j->request, 1, rc ? SERVICE_ERROR : 0, (uint32_t)j->output_bytes);
    pthread_mutex_lock(&lock);
    if (pending.sequence != j->sequence || pending.cancelled) {
        pthread_mutex_unlock(&lock); note("cancelled-before-publication", j, -ECANCELED); return;
    }
    pending = *j;
    pending.ready = 0;
    pending.ack_publishing = 1;
    stats.last_error = rc;
    stats.model_instance = j->model_instance;
    if (!rc) { ++stats.encoded; stats.bytes_readback += j->output_bytes; }
    pthread_mutex_unlock(&lock);
    if (rc) note("encode-failed", j, rc);
    else {
        char detail[512];
        snprintf(detail, sizeof detail,
            "lease_generation=%" PRIu64 " lease_token=%#" PRIx64 " lease_address=%#" PRIxPTR
            " lease_offset=%zu lease_capacity=%zu model_token=%#" PRIx64
            " model_bytes=%zu model_fnv=%016" PRIx64 " model_offset=%zu readback_bytes=%zu readback_fnv=%016" PRIx64,
            j->lease.span.generation, j->lease.token, j->lease.address, j->lease.span.offset, j->lease.bytes,
            j->model_token, j->model_bytes, j->model_fnv, j->model_offset, j->output_bytes, j->output_fnv);
        note_detail("output-readback", j, 0, detail);
    }
    int sent = send_reply(j, j->ack);
    pthread_mutex_lock(&lock);
    if (!sent) ++stats.queued;
    else stats.last_error = sent;
    int live = stats.pending && pending.sequence == j->sequence && !pending.cancelled;
    pthread_mutex_unlock(&lock);
    note("queued-ack", j, sent);
    if (sent || !live || (rc && j->native.kind == WITHOUT_PIN)) return;
    uint64_t readback = 0;
    if (!rc) rc = output_readback(j, NULL, j->output_bytes, &readback);
    if (!rc && readback != j->output_fnv) rc = -EIO;
    if (rc) {
        j->result_error = rc;
        reply_body(j->done, j->request, 1, SERVICE_ERROR, 0);
    }
    pthread_mutex_lock(&lock);
    live = stats.pending && pending.sequence == j->sequence && !pending.cancelled;
    if (live) {
        memcpy(pending.done, j->done, sizeof pending.done);
        pending.result_error = j->result_error;
        pending.done_publishing = 1;
        if (rc) stats.last_error = rc;
    }
    pthread_mutex_unlock(&lock);
    if (!live) return;
    sent = send_reply(j, j->done);
    pthread_mutex_lock(&lock);
    if (!sent) ++stats.queued;
    else stats.last_error = sent;
    pthread_mutex_unlock(&lock);
    note("queued-done", j, sent);
}
static void *worker_main(void *unused) {
    (void)unused;
    for (;;) {
        pthread_mutex_lock(&lock);
        while (!stopping && !pending.ready) pthread_cond_wait(&wake, &lock);
        if (stopping) { pthread_mutex_unlock(&lock); return NULL; }
        struct jpeg_job j = pending;
        pending.ready = 0; stats.working = 1;
        pthread_mutex_unlock(&lock);
        run_job(&j);
        pthread_mutex_lock(&lock);
        stats.working = 0;
        pthread_mutex_unlock(&lock);
    }
}
int functional_jpeg_codec_enable(void (*record)(const char *, const char *)) {
    if (in_record) return -EDEADLK;
    pid_t pid = getpid(), expected = 0;
    atomic_compare_exchange_strong_explicit(&owner, &expected, pid, memory_order_acq_rel, memory_order_acquire);
    int rc = process_guard();
    if (rc) return rc;
    pthread_mutex_lock(&lock);
    if (starting || stats.worker_live || atomic_load_explicit(&enabled, memory_order_relaxed)) rc = -EALREADY;
    else starting = 1;
    pthread_mutex_unlock(&lock);
    if (rc) return rc;
    struct original_api api;
    rc = functional_mpr_memory_acquire_sds ? bind_original(&api) : -ENOSYS;
    pthread_mutex_lock(&lock);
    if (!rc) {
        original = api; record_callback = record; stopping = 0;
        memset(&pending, 0, sizeof pending);
        stats.original_base = api.base; stats.original_exec = api.base + 0x11b654;
        int e = pthread_create(&worker, NULL, worker_main, NULL);
        if (e) rc = -e;
        else { stats.worker_live = stats.enabled = 1; atomic_store_explicit(&enabled, 1, memory_order_release); }
    }
    starting = 0;
    pthread_mutex_unlock(&lock);
    if (!rc) note("enable", NULL, 0);
    return rc;
}
static int rejected(int rc, int *result) {
    if (current) current->dispatch_error = rc;
    pthread_mutex_lock(&lock); ++stats.rejected; stats.last_error = rc; pthread_mutex_unlock(&lock);
    *result = rc;
    note("request-rejected", NULL, rc);
    return 1;
}
int functional_jpeg_codec_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, int *result) {
    if (!atomic_load_explicit(&enabled, memory_order_acquire) ||
        destination != FUNCTIONAL_JPEG_CODEC_SID) return 0;
    int rc = process_guard();
    if (rc) { if (result && !memory_access(result, sizeof *result, 1)) *result = rc; return 1; }
    if (!current) return 0;
    if (memory_access(result, sizeof *result, 1)) return 0;
    struct full_imaging_io transport;
    if (read_object(io, &transport, sizeof transport) || !valid_io(&transport)) return rejected(-EINVAL, result);
    uint8_t packet[PACKET_BYTES];
    if (!request || read_object(request, packet, sizeof packet) ||
        transport.size(request) != sizeof packet) return rejected(-EMSGSIZE, result);
    if (!envelope(packet, sizeof packet, REQUEST_BYTES) ||
        transport.source(request) != current->qid || u32(packet) != current->qid ||
        current->submitted) return rejected(-EPROTO, result);
    struct jpeg_job j = {.native = *current};
    memcpy(j.wire, packet, sizeof j.wire);
    memcpy(j.request, packet + ENVELOPE_BYTES, sizeof j.request);
    const uint8_t *p = j.request;
    if (u16(p) != original.cid(current->manager, 3) ||
        u16(p + 2) != original.mid(current->manager, 3, 0x304) || u16(p + 8) != 7 ||
        u16(p + 0x0e) != 0x8310 || u16(p + 0x12) != 0x8311 ||
        u16(p + 0x0c) != u16(p) || u16(p + 0x10) != u16(p) ||
        u16(p + 6) || u16(p + 0x0a) || u16(p + 0x14) || u16(p + 0x16) ||
        u32(p + 0x24) || u32(p + 0x30) ||
        u16(p + 0x40) > FCAM_MAX_STILL_WIDTH || u16(p + 0x42) > FCAM_MAX_STILL_HEIGHT ||
        p[0x48] || p[0x4c] || p[0x4d] || u16(p + 0x4e))
        return rejected(-ENOTSUP, result);
    if (current->kind == WITHOUT_PIN) {
        if (u16(p + 0x40) != current->width || u16(p + 0x42) != current->height ||
            current->mode > 1 || p[0x4b] != current->mode || p[0x49] != (current->mode ? 4 : 3))
            return rejected(-ENOTSUP, result);
    } else {
        unsigned selector = current->selector;
        uint16_t width = u16(p + 0x40), height = u16(p + 0x42);
        uint16_t primary_width = u16(p + 0x44), primary_height = u16(p + 0x46);
        if (!width || !height || !primary_width || !primary_height ||
            primary_width > FCAM_MAX_STILL_WIDTH || primary_height > FCAM_MAX_STILL_HEIGHT ||
            u32(p + 0x2c) || p[0x4b] != (selector == 1) ||
            (selector == 0 && ((p[0x49] > 2 && p[0x49] != 6) ||
                width != primary_width || height != primary_height)) ||
            (selector == 1 && (width != 160 || height != 120 || p[0x49] != 4)) ||
            (selector == 2 && p[0x49] != 3)) return rejected(-ENOTSUP, result);
        j.native.width = width; j.native.height = height; j.native.mode = p[0x4b];
    }
    uint32_t position = u32(p + 0x38), capacity = u32(p + 0x3c), offset = u32(p + 0x2c);
    if (!capacity || capacity > FCAM_MAX_RESULT_BYTES || position > UINT32_MAX - capacity ||
        u32(p + 0x34) != position + capacity || offset > UINT32_MAX - position)
        return rejected(-EOVERFLOW, result);
    j.origin = (struct fcam_native_origin){transport.source(request), destination,
        (uint32_t)u16(p) << 16 | u16(p + 2), sizeof packet, hash(packet, sizeof packet)};
    pthread_mutex_lock(&lock);
    if (stopping) rc = -ESHUTDOWN;
    else if (stats.pending) rc = -EBUSY;
    else if (stats.sequence == UINT32_MAX) rc = -EOVERFLOW;
    else { stats.pending = 1; j.sequence = ++stats.sequence; }
    pthread_mutex_unlock(&lock);
    if (rc) return rejected(rc, result);
    rc = functional_mpr_memory_acquire_sds(u32(p + 0x24), u32(p + 0x28),
        offset + position, capacity, &j.lease);
    if (!rc && (!j.lease.token || j.lease.bytes != capacity || !j.lease.span.generation ||
        j.lease.span.unit != u32(p + 0x28) || j.lease.span.offset != offset + position ||
        /* Current provider declares identity IOVA; all CPU access still uses lease.address. */
        j.lease.span.virtual_base != j.lease.span.iova_base ||
        j.lease.span.offset > j.lease.span.capacity ||
        j.lease.bytes > j.lease.span.capacity - j.lease.span.offset ||
        j.lease.span.offset > UINTPTR_MAX - j.lease.span.virtual_base ||
        j.lease.address != j.lease.span.virtual_base + j.lease.span.offset ||
        !span(j.lease.address, j.lease.bytes) || memory_access((void *)j.lease.address, j.lease.bytes, 1) ||
        !separate(j.lease.address, j.lease.bytes, (uintptr_t)request, sizeof packet) ||
        !separate(j.lease.address, j.lease.bytes, (uintptr_t)current->object, object_bytes(current->kind)) ||
        !separate(j.lease.address, j.lease.bytes, (uintptr_t)current->manager, 0x20) ||
        !separate(j.lease.address, j.lease.bytes, (uintptr_t)current->control, 0x20))) rc = -EINVAL;
    if (!rc) rc = functional_mpr_memory_validate(&j.lease);
    if (!rc) rc = transport.release(destination, request);
    if (rc) {
        int released = j.lease.token ? functional_mpr_memory_release(j.lease.token) : 0;
        pthread_mutex_lock(&lock);
        stats.pending = released != 0; stats.last_release_error = released;
        if (released) { pending = j; pending.cancelled = 1; }
        pthread_mutex_unlock(&lock);
        if (released) {
            char wire_hex[PACKET_BYTES*2+1], detail[512];
            hex_bytes(j.wire, sizeof j.wire, wire_hex);
            snprintf(detail, sizeof detail,
                "primary_rc=%d lease_generation=%" PRIu64 " lease_token=%#" PRIx64
                " lease_address=%#" PRIxPTR " lease_capacity=%zu request_hex=%s",
                rc, j.lease.span.generation, j.lease.token, j.lease.address, j.lease.bytes, wire_hex);
            note_detail("request-lease-release-failed", &j, released, detail);
        }
        return rejected(rc, result);
    }
    j.ready = 1;
    current->submitted = 1;
    char detail[sizeof j.wire * 2 + 16], wire_hex[sizeof j.wire * 2 + 1];
    hex_bytes(j.wire, sizeof j.wire, wire_hex);
    snprintf(detail, sizeof detail, "request_hex=%s", wire_hex);
    /* Receipt order precedes waking the actual encoding worker. */
    note_detail("original-request", &j, 0, detail);
    lease_note(&j);
    pthread_mutex_lock(&lock);
    pending = j; ++stats.accepted; pthread_cond_signal(&wake);
    pthread_mutex_unlock(&lock);
    *result = 0;
    return 1;
}
static int read_invocation(struct invocation *v, unsigned kind) {
    uint8_t fields[0x30], manager[0x20];
    int rc = read_object(v->object, fields, object_bytes(kind));
    if (rc) return rc;
    if (u64(fields) != object_vtable(kind)) return -ELIBBAD;
    v->kind = kind == WITHOUT_PIN ? WITHOUT_PIN : MAIN;
    v->manager = (void *)(uintptr_t)u64(fields + 0x10);
    v->control = (void *)(uintptr_t)u64(fields + 0x18);
    v->context = u32(fields + 0x0c);
    if (kind == WITHOUT_PIN) {
        v->key = u32(fields + 0x20); v->mode = fields[0x24];
        v->width = u16(fields + 0x26); v->height = u16(fields + 0x28);
    } else if ((v->selector = fields[0x20]) > 2) return -ENOTSUP;
    if (!v->control || read_object(v->manager, manager, sizeof manager)) return -EFAULT;
    v->qid = original.get_id(v->manager);
    return !v->qid || v->qid != u32(manager + 8) ? -EPROTO : 0;
}
static int same_invocation(const struct invocation *a, const struct invocation *b) {
    return a->manager == b->manager && a->control == b->control && a->context == b->context &&
        a->qid == b->qid && a->kind == b->kind && a->selector == b->selector &&
        (a->kind == MAIN || (a->key == b->key && a->mode == b->mode &&
            a->width == b->width && a->height == b->height));
}
static uint32_t invoke_exec(void *object, const uint8_t *trigger, unsigned kind, uintptr_t caller) {
    int saved = errno;
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        uint32_t (*delegate)(void *, const uint8_t *) = NULL;
        LOAD(delegate, kind == WITHOUT_PIN ? EXEC_SYMBOL : MAIN_EXEC_SYMBOL);
        if (!delegate) { errno = ENOSYS; return NATIVE_ERROR; }
        errno = saved; return delegate(object, trigger);
    }
    int rc = process_guard();
    if (rc) { errno = -rc; return NATIVE_ERROR; }
    if (current || in_record || in_callback || !native_caller(caller, 0)) {
        errno = EPROTO; return NATIVE_ERROR;
    }
    struct invocation v = {.object = object, .caller = caller, .tid = syscall(SYS_gettid)};
    rc = read_invocation(&v, kind);
    if (!rc && kind == MAIN) {
        uint8_t completion[32];
        rc = read_object(trigger, completion, 4);
        /* The failure branch never reads the success-only logging field at +0x18. */
        if (!rc && !u16(completion + 2)) rc = read_object(trigger, completion, sizeof completion);
    }
    if (rc) { errno = -rc; return NATIVE_ERROR; }
    current = &v;
    errno = saved;
    uint32_t result = kind == WITHOUT_PIN ? original.exec(object, trigger) : original.main_exec(object, trigger);
    int native_errno = errno;
    current = NULL;
    if (!result && (!v.submitted || v.dispatch_error)) {
        errno = v.dispatch_error ? -v.dispatch_error : ENOMSG; return NATIVE_ERROR;
    }
    errno = native_errno;
    return result;
}
uint32_t functional_jpeg_exec(void *object, const uint8_t *trigger) {
    return invoke_exec(object, trigger, WITHOUT_PIN, (uintptr_t)__builtin_return_address(0));
}
uint32_t functional_jpeg_main_exec(void *object, const uint8_t *trigger) {
    return invoke_exec(object, trigger, MAIN, (uintptr_t)__builtin_return_address(0));
}
static int main_config(struct jpeg_job *j) {
    uintptr_t vptr, slot, expected;
    if (read_object(j->native.control, &vptr, sizeof vptr) ||
        vptr > UINTPTR_MAX - 0xa8 || read_object((void *)(vptr + 0xa8), &slot, sizeof slot)) return -EFAULT;
    memcpy(&expected, &original.get_pointer, sizeof expected);
    if (slot != expected) return -ELIBBAD;
    void *config = NULL;
    if (original.get_pointer(j->native.control, 0x1048, &config) || !config ||
        (j->config && j->config != config) || memory_access(config, 0x78, 1) ||
        !separate((uintptr_t)config, 0x78, j->lease.address, j->lease.bytes) ||
        !separate((uintptr_t)config, 0x78, (uintptr_t)j->native.object, 0x28) ||
        !separate((uintptr_t)config, 0x78, (uintptr_t)j->completion.object, 0x28) ||
        !separate((uintptr_t)config, 0x78, (uintptr_t)j->native.manager, 0x20) ||
        !separate((uintptr_t)config, 0x78, (uintptr_t)j->native.control, 0x20)) return -EFAULT;
    uint8_t fields[12];
    unsigned offset = 0x54 + 12u * j->native.selector;
    if (read_object((uint8_t *)config + offset, fields, sizeof fields) ||
        u32(fields) != u32(j->request + 0x28) || u32(fields + 4) != u32(j->request + 0x38) ||
        u32(fields + 8) != u32(j->request + 0x3c)) return -EPROTO;
    j->config = config;
    return 0;
}
uint32_t functional_jpeg_comp_exec(void *object, const uint8_t *trigger) {
    int saved = errno;
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        uint32_t (*delegate)(void *, const uint8_t *) = NULL;
        LOAD(delegate, COMP_EXEC_SYMBOL);
        if (!delegate) { errno = ENOSYS; return NATIVE_ERROR; }
        errno = saved; return delegate(object, trigger);
    }
    int rc = process_guard();
    if (rc) { errno = -rc; return NATIVE_ERROR; }
    uintptr_t caller = (uintptr_t)__builtin_return_address(0);
    if (current || in_record || in_callback || !native_comp_caller(caller)) { errno = EPROTO; return NATIVE_ERROR; }
    struct invocation v = {.object = object, .caller = caller, .tid = syscall(SYS_gettid)};
    uint8_t previous[REPLY_BYTES];
    rc = read_invocation(&v, MAIN_COMP);
    if (!rc) rc = read_object(trigger, previous, sizeof previous);
    pthread_mutex_lock(&lock);
    struct jpeg_job j = pending;
    if (!rc && (!stats.pending || j.native.kind != MAIN || j.cancelled || j.callback_active ||
        !j.ack_consumed || j.comp_started || j.native.object == object ||
        (uintptr_t)trigger != j.ack_body_address ||
        !same_invocation(&v, &j.native) || j.ack_receiver_pid != (long)getpid() ||
        j.ack_receiver_tid != v.tid || memcmp(previous, j.ack, sizeof previous))) rc = -EPROTO;
    if (!rc) pending.callback_active = 1;
    pthread_mutex_unlock(&lock);
    if (rc) { note("maincomp-exec-rejected", &j, rc); errno = -rc; return NATIVE_ERROR; }
    j.completion = v;
    in_callback = 1;
    rc = main_config(&j);
    uint32_t result = NATIVE_ERROR;
    errno = saved;
    if (!rc) result = original.comp_exec(object, trigger);
    int native_errno = errno;
    in_callback = 0;
    if (!rc && result) rc = -EPROTO;
    pthread_mutex_lock(&lock);
    if (pending.sequence == j.sequence) {
        pending.callback_active = 0;
        if (rc) { pending.cancelled = 1; stats.last_error = rc; }
        else { pending.completion = v; pending.config = j.config; pending.comp_started = 1; }
    }
    pthread_mutex_unlock(&lock);
    char previous_hex[REPLY_BYTES*2+1], detail[256];
    hex_bytes(previous, sizeof previous, previous_hex);
    snprintf(detail, sizeof detail,
        "comp_caller=%#" PRIxPTR " comp_exec_entry=%#" PRIxPTR " previous_ack_hex=%s"
        " previous_ack_address=%#" PRIxPTR " original_result=%#x native_config=%p config_length_offset=%u",
        caller, exec_entry(MAIN_COMP), previous_hex, (uintptr_t)trigger,
        result, j.config, 0x5c + 12u*j.native.selector);
    note_detail("original-maincomp-exec", &j, rc, detail);
    errno = rc ? -rc : native_errno;
    return rc ? NATIVE_ERROR : result;
}
int functional_jpeg_codec_observe_received(unsigned int destination, void *reply,
    const struct full_imaging_io *io) {
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) return 0;
    int rc = process_guard();
    if (rc) return rc;
    struct full_imaging_io transport;
    if (read_object(io, &transport, sizeof transport) || !valid_io(&transport)) return -EINVAL;
    uint8_t packet[ENVELOPE_BYTES + REPLY_BYTES];
    if (!reply || read_object(reply, packet, sizeof packet)) return -EFAULT;
    if (transport.source(reply) != FUNCTIONAL_JPEG_CODEC_SID) return 0;
    if (transport.size(reply) != sizeof packet ||
        !envelope(packet, sizeof packet, REPLY_BYTES)) return -EPROTO;
    struct jpeg_job observed = {0};
    int completion = 0;
    long receiver_pid = (long)getpid(), receiver_tid = (long)syscall(SYS_gettid);
    pthread_mutex_lock(&lock);
    int live = stats.pending && destination == pending.native.qid;
    if (!live) rc = 0;
    else if (!pending.cancelled && pending.ack_publishing && !pending.ack_received &&
        !memcmp(packet + ENVELOPE_BYTES, pending.ack, REPLY_BYTES)) {
        pending.ack_received = 1; pending.ack_receiver_pid = receiver_pid;
        pending.ack_receiver_tid = receiver_tid; ++stats.received; rc = 1;
    } else if (!pending.cancelled && pending.done_publishing && pending.ack_consumed &&
        (pending.native.kind == WITHOUT_PIN || pending.comp_started) &&
        !pending.done_received && !memcmp(packet + ENVELOPE_BYTES, pending.done, REPLY_BYTES)) {
        pending.done_received = 1; pending.done_receiver_pid = receiver_pid;
        pending.done_receiver_tid = receiver_tid; ++stats.received; completion = 1; rc = 1;
    } else rc = -EPROTO;
    if (rc < 0) { pending.cancelled = 1; stats.last_error = rc; }
    if (rc == 1) {
        pending.replies[completion].address = (uintptr_t)reply;
        memcpy(pending.replies[completion].packet, packet, sizeof packet);
        observed = pending;
    }
    pthread_mutex_unlock(&lock);
    if (rc == 1) {
        char hex[REPLY_BYTES*2+1], packet_hex[sizeof packet*2+1], detail[512];
        hex_bytes(packet, sizeof packet, packet_hex);
        hex_bytes(packet + ENVELOPE_BYTES, REPLY_BYTES, hex);
        snprintf(detail, sizeof detail,
            "receiver_pid=%ld receiver_tid=%ld reply_address=%#" PRIxPTR " response_hex=%s reply_hex=%s"
            " response_source=%#x response_destination=%#x lease_generation=%" PRIu64 " lease_token=%#" PRIx64,
            receiver_pid, receiver_tid, (uintptr_t)reply, hex, packet_hex, FUNCTIONAL_JPEG_CODEC_SID, destination,
            observed.lease.span.generation, observed.lease.token);
        note_detail(completion ? "original-received-done" : "original-received-ack", &observed, 0, detail);
    }
    return rc;
}
int functional_jpeg_codec_observe_freed(unsigned int destination, void *pointer, int actual_rc) {
    int saved = errno, rc = 0;
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) return 0;
    rc = process_guard();
    if (rc) { errno = saved; return rc; }
    if (in_record || in_callback) { errno = saved; return -EDEADLK; }
    long pid = (long)getpid(), tid = (long)syscall(SYS_gettid);
    struct jpeg_job observed = {0};
    int completion = -1;
    pthread_mutex_lock(&lock);
    if (stats.pending && pointer && destination == pending.native.qid) {
        for (int i = 0; i < 2; ++i) {
            struct reply_observation *reply = &pending.replies[i];
            if ((i ? pending.done_received : pending.ack_received) &&
                (i ? pending.done_receiver_pid : pending.ack_receiver_pid) == pid &&
                (i ? pending.done_receiver_tid : pending.ack_receiver_tid) == tid &&
                reply->address == (uintptr_t)pointer && !reply->free_attempted) {
                reply->free_attempted = 1; reply->free_result = actual_rc;
                if (actual_rc) { pending.cancelled = 1; stats.last_error = actual_rc < 0 ? actual_rc : -EIO; }
                observed = pending; completion = i; break;
            }
        }
    }
    pthread_mutex_unlock(&lock);
    rc = 0;
    if (completion >= 0) {
        const struct reply_observation *reply = &observed.replies[completion];
        char hex[REPLY_BYTES*2+1], packet_hex[sizeof reply->packet*2+1], detail[512];
        hex_bytes(reply->packet, sizeof reply->packet, packet_hex);
        hex_bytes(reply->packet + ENVELOPE_BYTES, REPLY_BYTES, hex);
        snprintf(detail, sizeof detail,
            "receiver_pid=%ld receiver_tid=%ld reply_address=%#" PRIxPTR " response_hex=%s reply_hex=%s"
            " response_source=%#x response_destination=%#x free_rc=%d"
            " lease_generation=%" PRIu64 " lease_token=%#" PRIx64,
            pid, tid, reply->address, hex, packet_hex, FUNCTIONAL_JPEG_CODEC_SID, destination, actual_rc,
            observed.lease.span.generation, observed.lease.token);
        rc = actual_rc ? actual_rc < 0 ? actual_rc : -EIO : 1;
        note_detail(completion ? "original-freed-done" : "original-freed-ack", &observed,
            actual_rc ? rc : 0, detail);
    }
    errno = saved;
    return rc;
}
static uint32_t invoke_res(void *object, const uint8_t *response, uint16_t mid,
    unsigned kind, uintptr_t caller) {
    int saved = errno;
    uint32_t (*method)(void *, const uint8_t *, uint16_t) = kind == WITHOUT_PIN ? original.res :
        kind == MAIN ? original.main_res : original.comp_res;
    if (!atomic_load_explicit(&enabled, memory_order_acquire)) {
        LOAD(method, kind == WITHOUT_PIN ? RES_SYMBOL : kind == MAIN ? MAIN_RES_SYMBOL : COMP_RES_SYMBOL);
        if (!method) { errno = ENOSYS; return NATIVE_ERROR; }
        errno = saved; return method(object, response, mid);
    }
    int rc = process_guard();
    if (rc) { errno = -rc; return NATIVE_ERROR; }
    if (current || in_record || in_callback || !native_caller(caller, 1)) { errno = EPROTO; return NATIVE_ERROR; }
    pthread_mutex_lock(&lock);
    int ours = stats.pending && pending.native.kind == (kind == WITHOUT_PIN ? WITHOUT_PIN : MAIN) &&
        (kind == MAIN_COMP ? pending.comp_started && pending.completion.object == object : pending.native.object == object);
    struct jpeg_job j = pending;
    if (ours && !j.callback_active) pending.callback_active = 1;
    pthread_mutex_unlock(&lock);
    if (ours && j.callback_active) { errno = EBUSY; return NATIVE_ERROR; }
    if (!ours) {
        if (kind != WITHOUT_PIN) { errno = EPROTO; return NATIVE_ERROR; }
        errno = saved; return method(object, response, mid);
    }
    uint8_t body[REPLY_BYTES];
    int completion = mid == u16(j.request + 0x12);
    const struct invocation *expected_object = kind == MAIN_COMP ? &j.completion : &j.native;
    struct invocation v = {.object = object};
    rc = read_invocation(&v, kind);
    if (!rc && !same_invocation(&v, expected_object)) rc = -EPROTO;
    if (!rc) rc = read_object(response, body, sizeof body);
    if (!rc && (j.cancelled || j.callback_active ||
        (kind == MAIN && completion) || (kind == MAIN_COMP && !completion) ||
        (completion ? !j.done_received : !j.ack_received || j.ack_consumed) ||
        !j.replies[completion].free_attempted || j.replies[completion].free_result ||
        (completion ? j.done_receiver_pid : j.ack_receiver_pid) != (long)getpid() ||
        (completion ? j.done_receiver_tid : j.ack_receiver_tid) != (long)syscall(SYS_gettid) ||
        mid != u16(j.request + (completion ? 0x12 : 0x0e)) ||
        memcmp(body, completion ? j.done : j.ack, sizeof body))) rc = -EPROTO;
    if (!rc && !u32(body + 8)) rc = functional_mpr_memory_validate(&j.lease);
    uint64_t readback = 0;
    if (!rc && completion && !u32(body + 8)) {
        rc = output_readback(&j, NULL, j.output_bytes, &readback);
        if (!rc && readback != j.output_fnv) rc = -EIO;
    }
    in_callback = 1;
    if (!rc && kind == MAIN_COMP) rc = main_config(&j);
    if (rc) {
        in_callback = 0;
        pthread_mutex_lock(&lock);
        if (pending.sequence == j.sequence) { pending.cancelled = 1; pending.callback_active = 0; }
        stats.last_error = rc;
        pthread_mutex_unlock(&lock);
        note("callback-rejected", &j, rc); errno = -rc; return NATIVE_ERROR;
    }
    errno = saved;
    uint32_t result = method(object, response, mid);
    int native_errno = errno;
    in_callback = 0;
    uint32_t expected = kind == MAIN ? 0 : u32(body + 8) ? NATIVE_ERROR : completion ? 0 : NATIVE_WAIT;
    if (kind == MAIN_COMP) {
        uint8_t length[4] = {0};
        uint32_t expected_length = u32(body + 8) ? 0 : u32(body + 12);
        if (read_object((uint8_t *)j.config + 0x5c + 12u*j.native.selector, length, sizeof length) ||
            u32(length) != expected_length) rc = -EPROTO;
        char config_detail[192];
        snprintf(config_detail, sizeof config_detail,
            "native_config=%p config_length_offset=%u actual_length=%u expected_length=%u original_result=%#x",
            j.config, 0x5c + 12u*j.native.selector, u32(length), expected_length, result);
        note_detail("original-maincomp-config", &j, rc, config_detail);
    }
    int terminal = !rc && kind != MAIN && (completion || u32(body + 8)) && result == expected;
    int released = terminal ? functional_mpr_memory_release(j.lease.token) : 0;
    pthread_mutex_lock(&lock);
    if (pending.sequence == j.sequence) {
        pending.callback_active = 0;
        if (!rc && result == expected) {
            if (!completion) {
                pending.ack_consumed = 1; pending.ack_body_address = (uintptr_t)response; ++stats.native_ack;
            } else ++stats.native_done;
        }
        if (terminal && !released) { stats.pending = 0; memset(&pending, 0, sizeof pending); }
        if (released) stats.last_release_error = released;
        if (rc || result != expected) { stats.last_error = -EPROTO; pending.cancelled = 1; }
    }
    pthread_mutex_unlock(&lock);
    char hex[REPLY_BYTES*2+1], detail[512];
    hex_bytes(body, sizeof body, hex);
    snprintf(detail, sizeof detail,
        "receiver_pid=%ld receiver_tid=%ld callback_caller=%#" PRIxPTR " res_entry=%#" PRIxPTR
        " response_hex=%s response_address=%#" PRIxPTR " response_source=%#x response_destination=%#x response_mid=%#x"
        " original_result=%#x expected_result=%#x original_errno=%d"
        " lease_generation=%" PRIu64 " lease_token=%#" PRIx64 " release_rc=%d terminal=%d lease_released=%d",
        completion ? j.done_receiver_pid : j.ack_receiver_pid,
        completion ? j.done_receiver_tid : j.ack_receiver_tid,
        caller, original.base + (kind == WITHOUT_PIN ? 0x11a9dc : kind == MAIN ? 0x120e64 : 0x122b44),
        hex, (uintptr_t)response, FUNCTIONAL_JPEG_CODEC_SID, j.native.qid, mid, result, expected, native_errno,
        j.lease.span.generation, j.lease.token, released, terminal, terminal && !released);
    note_detail(completion ? "original-rescmd-done" : "original-rescmd-ack", &j,
        !rc && result == expected ? released : -EPROTO, detail);
    errno = native_errno;
    return result;
}
uint32_t functional_jpeg_res(void *object, const uint8_t *response, uint16_t mid) {
    return invoke_res(object, response, mid, WITHOUT_PIN, (uintptr_t)__builtin_return_address(0));
}
uint32_t functional_jpeg_main_res(void *object, const uint8_t *response, uint16_t mid) {
    return invoke_res(object, response, mid, MAIN, (uintptr_t)__builtin_return_address(0));
}
uint32_t functional_jpeg_comp_res(void *object, const uint8_t *response, uint16_t mid) {
    return invoke_res(object, response, mid, MAIN_COMP, (uintptr_t)__builtin_return_address(0));
}
int functional_jpeg_codec_snapshot(struct functional_jpeg_codec_snapshot *out) {
    pid_t pid = atomic_load_explicit(&owner, memory_order_acquire);
    if (pid && pid != getpid()) return -ECHILD;
    int rc = memory_access(out, sizeof *out, 1);
    if (rc) return rc;
    pthread_mutex_lock(&lock); memcpy(out, &stats, sizeof stats); pthread_mutex_unlock(&lock);
    return 0;
}
int functional_jpeg_codec_shutdown(void) {
    if (in_record) return -EDEADLK;
    int rc = process_guard();
    if (rc) return rc;
    pthread_mutex_lock(&lock);
    if (!stats.worker_live) rc = -ENODEV;
    else if (stats.pending || stats.working || starting || stopping) rc = -EBUSY;
    else { stopping = 1; pthread_cond_signal(&wake); }
    pthread_mutex_unlock(&lock);
    if (rc) return rc;
    int e = pthread_join(worker, NULL);
    if (e) return -e;
    pthread_mutex_lock(&lock);
    stats.worker_live = stats.enabled = 0;
    atomic_store_explicit(&enabled, 0, memory_order_release);
    stopping = 0;
    pthread_mutex_unlock(&lock);
    note("shutdown", NULL, 0);
    return 0;
}
