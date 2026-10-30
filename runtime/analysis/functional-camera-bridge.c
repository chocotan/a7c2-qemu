/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-camera-bridge.h"
#include "functional-vdf-path-abi.h"
#include "functional-bb-startup-abi.h"
#include "functional-face-source-snapshot-abi.h"
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define FNV_SEED UINT64_C(0xcbf29ce484222325)
#define FNV_PRIME UINT64_C(0x100000001b3)
#define RAM_FIRST UINT64_C(0x400000000)
#define RAM_END UINT64_C(0x540000000)
#if defined(FCAM_HOST_TEST) && defined(FCAM_TEST_WAIT_NS)
#define WAIT_NS FCAM_TEST_WAIT_NS
#else
#define WAIT_NS UINT64_C(30000000000)
#endif

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static int owner_pid;
static _Thread_local int entered;
static unsigned char *mailbox;
static uint64_t pages[FCAM_MAILBOX_PAGES], nonce, sequence;
static int poisoned, retired;
static void (*record_event)(const char *, const char *);

#ifdef FCAM_HOST_TEST
extern int fcam_test_mlock(const void *, size_t);
extern int fcam_test_munlock(const void *, size_t);
extern int fcam_test_pagemap(const void *, uint64_t *);
extern int fcam_test_random(uint64_t *);
extern void fcam_test_after_copy(void *, size_t);
#define pin fcam_test_mlock
#define unpin fcam_test_munlock
unsigned char *fcam_test_mailbox(void) { return mailbox; }
#else
#define pin mlock
#define unpin munlock
#endif

static uint32_t get32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const unsigned char *p) { return get32(p) | (uint64_t)get32(p + 4) << 32; }
static void put32(unsigned char *p, uint32_t v) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static void put64(unsigned char *p, uint64_t v) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static uint64_t fnv_more(uint64_t value, const void *data, size_t size) {
    const unsigned char *p = data;
    for (size_t i = 0; i < size; ++i) value = (value ^ p[i]) * FNV_PRIME;
    return value;
}
static uint64_t fnv(const void *p, size_t n) { return fnv_more(FNV_SEED, p, n); }
static uint64_t destination_fnv(const void *data, size_t size) {
    const volatile unsigned char *p = data;
    uint64_t value = FNV_SEED;
    for (size_t i = 0; i < size; ++i) value = (value ^ p[i]) * FNV_PRIME;
    return value;
}
/* Only the aligned publication word is atomic; all wire encoding is explicit. */
static void status_store(uint32_t status) {
    unsigned char raw[4]; uint32_t native;
    put32(raw, status); memcpy(&native, raw, 4);
    __atomic_store_n((uint32_t *)(void *)(mailbox + FCAM_H_STATUS), native, __ATOMIC_RELEASE);
}
static uint32_t status_load(void) {
    uint32_t native = __atomic_load_n((uint32_t *)(void *)(mailbox + FCAM_H_STATUS), __ATOMIC_ACQUIRE);
    unsigned char raw[4]; memcpy(raw, &native, 4); return get32(raw);
}
static void snapshot(unsigned char *dst, size_t offset, size_t n) {
    const volatile unsigned char *p = mailbox + offset;
    for (size_t i = 0; i < n; ++i) dst[i] = p[i];
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
}
static int enter(void) {
    int pid = (int)getpid(), expected = 0;
    if (pid <= 1) return -EPERM;
    __atomic_compare_exchange_n(&owner_pid, &expected, pid, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    if (__atomic_load_n(&owner_pid, __ATOMIC_ACQUIRE) != pid) return -ECHILD;
    if (entered) return -EDEADLK;
    entered = 1;
    int rc = pthread_mutex_lock(&mutex);
    if (rc) { entered = 0; return -rc; }
    return 0;
}
static int leave(int rc, int saved_errno) {
    pthread_mutex_unlock(&mutex); entered = 0; errno = saved_errno; return rc;
}
static int fail_early(int rc, int saved_errno) { errno = saved_errno; return rc; }
static int valid_span(const void *p, size_t n) {
    return !n || (p && (uintptr_t)p <= UINTPTR_MAX - n);
}
static int overlaps(const void *a, size_t an, const void *b, size_t bn) {
    return an && bn && (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static void note(const char *tag, const char *text) {
    if (record_event) record_event(tag, text);
}
static int physical_pages(uint64_t *out) {
#ifdef FCAM_HOST_TEST
    if (fcam_test_pagemap(mailbox, out)) return -errno;
#else
    int fd = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -errno;
    int rc = 0;
    for (unsigned i = 0; i < FCAM_MAILBOX_PAGES; ++i) {
        uint64_t entry = 0, va = (uint64_t)(uintptr_t)(mailbox + i * FCAM_PAGE_BYTES);
        ssize_t n;
        do { n = pread(fd, &entry, sizeof entry, (off_t)((va / FCAM_PAGE_BYTES) * 8)); } while (n < 0 && errno == EINTR);
        uint64_t pfn = entry & ((UINT64_C(1) << 55) - 1);
        if (n != 8 || !(entry & (UINT64_C(1) << 63)) || (entry & (UINT64_C(1) << 62)) ||
            !pfn || pfn > UINT64_MAX / FCAM_PAGE_BYTES) { rc = n < 0 ? -errno : -EACCES; break; }
        out[i] = pfn * FCAM_PAGE_BYTES;
    }
    if (close(fd) && !rc) rc = -errno;
    if (rc) return rc;
#endif
    for (unsigned i = 0; i < FCAM_MAILBOX_PAGES; ++i) {
        if (out[i] < RAM_FIRST || out[i] > RAM_END - FCAM_PAGE_BYTES || (out[i] & (FCAM_PAGE_BYTES - 1))) return -ERANGE;
        for (unsigned j = 0; j < i; ++j) if (out[i] == out[j]) return -EINVAL;
    }
    return 0;
}
static int same_physical_pages(void) {
    uint64_t actual[FCAM_MAILBOX_PAGES];
    int rc = physical_pages(actual);
    if (!rc && memcmp(actual, pages, sizeof pages)) rc = -ESTALE;
    if (rc) poisoned = 1;
    return rc;
}
static int random_nonce(void) {
#ifdef FCAM_HOST_TEST
    if (fcam_test_random(&nonce)) return -errno;
#else
    int fd = open("/dev/urandom", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return -errno;
    unsigned char raw[8]; size_t used = 0; int rc = 0;
    while (used < sizeof raw) {
        ssize_t n = read(fd, raw + used, sizeof raw - used);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { rc = n < 0 ? -errno : -EIO; break; }
        used += (size_t)n;
    }
    if (close(fd) && !rc) rc = -errno;
    if (rc) return rc;
    nonce = get64(raw);
#endif
    return nonce ? 0 : -EIO;
}
static int deadline_start(uint64_t *deadline) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return -errno;
    *deadline = (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec + WAIT_NS;
    return 0;
}
static int wait_status(uint32_t want, uint32_t before, uint64_t deadline) {
    const struct timespec pause = {0, 1000000};
    for (;;) {
        uint32_t status = status_load();
        if (status == want) return 0;
        if (status != before) return -EPROTO;
        struct timespec t;
        if (clock_gettime(CLOCK_MONOTONIC, &t)) return -errno;
        if ((uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec >= deadline) return -ETIMEDOUT;
        if (nanosleep(&pause, NULL) && errno != EINTR) return -errno;
    }
}
static int binding(const unsigned char *h) {
    if (get32(h + FCAM_H_MAGIC) != FCAM_MAGIC || get32(h + FCAM_H_VERSION) != FCAM_ABI_VERSION ||
        get32(h + FCAM_H_PID) != (uint32_t)owner_pid || get64(h + FCAM_H_NONCE) != nonce) return -EPROTO;
    for (unsigned i = 0; i < FCAM_MAILBOX_PAGES; ++i)
        if (get64(h + FCAM_H_PAGES + 8 * i) != pages[i]) return -EPROTO;
    uint32_t flags = get32(h + FCAM_H_FLAGS), op = get32(h + FCAM_H_OPCODE);
    if (flags && (flags != FCAM_ORIGIN_API40_SOURCE_SNAPSHOT ||
        (op != FCAM_OP_AP_SOURCE_SNAPSHOT && op != FCAM_OP_READ_RESULT && op != FCAM_OP_RELEASE_RESULT && op != FCAM_OP_CANCEL) ||
        get32(h + FCAM_H_NATIVE_COMMAND) != FCAM_FACE_SNAPSHOT_COMMAND || get32(h + FCAM_H_NATIVE_BYTES) != 40 ||
        !get32(h + FCAM_H_NATIVE_SOURCE) || !get32(h + FCAM_H_NATIVE_DESTINATION))) return -EPROTO;
    for (unsigned i = 256; i < FCAM_HEADER_BYTES; ++i) if (h[i]) return -EPROTO;
    return 0;
}
int fcam_bridge_init(void (*record)(const char *, const char *)) {
    int saved_errno = errno, rc = enter();
    if (rc) return fail_early(rc, saved_errno);
    if (!record) return leave(-EINVAL, saved_errno);
    if (retired || poisoned) return leave(-ESHUTDOWN, saved_errno);
    if (mailbox) return leave(record == record_event ? 0 : -EBUSY, saved_errno);
    record_event = record;
    if (sysconf(_SC_PAGESIZE) != FCAM_PAGE_BYTES) rc = -ENOTSUP;
    else {
        mailbox = mmap(NULL, FCAM_MAILBOX_BYTES, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (mailbox == MAP_FAILED) { mailbox = NULL; rc = -errno; }
    }
    int pinned = 0;
    if (!rc && madvise(mailbox, FCAM_MAILBOX_BYTES, MADV_DONTFORK)) rc = -errno;
    if (!rc) {
        /* DONTFORK also prevents parent-side COW from changing advertised PFNs. */
        memset(mailbox, 0, FCAM_MAILBOX_BYTES); /* Commit every anonymous page before pagemap. */
        if (pin(mailbox, FCAM_MAILBOX_BYTES)) rc = -errno;
        else pinned = 1;
    }
    if (!rc) rc = physical_pages(pages);
    if (!rc) rc = random_nonce();
    if (rc) {
        int cleanup_error = 0;
        if (mailbox) {
            if (pinned && unpin(mailbox, FCAM_MAILBOX_BYTES)) cleanup_error = -errno;
            if (!munmap(mailbox, FCAM_MAILBOX_BYTES)) mailbox = NULL;
            else { cleanup_error = -errno; poisoned = 1; }
        }
        char text[160]; snprintf(text, sizeof text, "pid=%d error=%d pinned=%d mapping_retained=%d cleanup_error=%d",
                                 owner_pid, rc, pinned, mailbox != NULL, cleanup_error);
        note("FUNCTIONAL_CAMERA_MAILBOX_FAILED ", text);
        return leave(rc, saved_errno);
    }
    put32(mailbox + FCAM_H_MAGIC, FCAM_MAGIC); put32(mailbox + FCAM_H_VERSION, FCAM_ABI_VERSION);
    put32(mailbox + FCAM_H_PID, (uint32_t)owner_pid); put64(mailbox + FCAM_H_NONCE, nonce);
    for (unsigned i = 0; i < FCAM_MAILBOX_PAGES; ++i) put64(mailbox + FCAM_H_PAGES + 8 * i, pages[i]);
    status_store(FCAM_STATUS_IDLE);
    char text[768];
    int n = snprintf(text, sizeof text, "phys0=%#" PRIx64 " nonce=%#" PRIx64 " pid=%d ABI=%s version=%u pages=",
                     pages[0], nonce, owner_pid, FCAM_PROFILE, FCAM_ABI_VERSION);
    for (unsigned i = 0; i < FCAM_MAILBOX_PAGES && n > 0 && (size_t)n < sizeof text; ++i)
        n += snprintf(text + n, sizeof text - (size_t)n, "%s%#" PRIx64, i ? "," : "", pages[i]);
    note("FUNCTIONAL_CAMERA_MAILBOX ", text);
    return leave(0, saved_errno);
}

struct reply { unsigned char data[FCAM_DATA_BYTES]; size_t used; uint64_t token, total, offset; };
/* Transactions already hold mutex; do not consume a firmware worker's stack. */
static struct reply reply_storage;
static unsigned char destination_readback[FCAM_DATA_BYTES];
static int zero_bytes(const unsigned char *p, size_t n) {
    for (size_t i = 0; i < n; ++i) if (p[i]) return 0;
    return 1;
}
static int bit_width_reply_valid(const unsigned char *p, const void *input) {
    const uint64_t before_frame = get64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION);
    const uint64_t before_config = get64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION);
    const unsigned char *route = p + FCAM_VDF_R_CONFIG;
    return get32(p + FCAM_VDF_R_CLASS) == FCAM_BIT_WIDTH_CLASS &&
        get64(p + FCAM_VDF_R_INPUT_FNV) == fnv(input, FCAM_BIT_WIDTH_INPUT_BYTES) &&
        !memcmp(p + FCAM_BIT_WIDTH_R_CONFIG, input, FCAM_BIT_WIDTH_INPUT_BYTES) &&
        fcam_bit_width_input_valid(p + FCAM_BIT_WIDTH_R_CONFIG) &&
        before_frame != UINT64_MAX && before_config != UINT64_MAX &&
        get64(p + FCAM_VDF_R_FRAME_GENERATION) == before_frame + 1 &&
        get64(p + FCAM_VDF_R_CONFIG_GENERATION) == before_config + 1 &&
        get64(p + FCAM_VDF_R_LEASE_GENERATION) &&
        get64(p + FCAM_VDF_R_SOURCE_FNV) == get64(p + FCAM_VDF_R_SINK_FNV) &&
        get64(p + FCAM_VDF_R_ACTIVE_BYTES) == UINT64_C(640) * 480u * 3u &&
        get32(p + FCAM_VDF_R_WIDTH) == 640 && get32(p + FCAM_VDF_R_HEIGHT) == 480 &&
        get32(p + FCAM_VDF_R_STRIDE) == 1920 && get32(p + FCAM_VDF_R_ENDPOINT) == FCAM_VDF_ENDPOINT &&
        get32(p + FCAM_VDF_R_SELECTED_MASK) == FCAM_VDF_MASK &&
        get32(p + FCAM_VDF_R_COMPLETED_MASK) == FCAM_VDF_MASK &&
        get32(p + FCAM_VDF_R_ENABLED) == 1 && get32(p + FCAM_VDF_R_CONFIG_READBACK) == 1 &&
        get32(p + FCAM_VDF_R_COMMITTED) == 1 && get32(p + FCAM_VDF_R_FRAME_CONSUMED) == 1 &&
        get32(p + FCAM_VDF_R_RETIRED) == 1 && route[0] == 1 && route[1] == 5 && route[2] == 5 &&
        route[4] <= 2 && zero_bytes(route + 13, 3);
}
static int variable_field(unsigned i) {
    return (i >= FCAM_H_STATUS && i < FCAM_H_STATUS + 4) ||
        (i >= FCAM_H_RESPONSE_BYTES && i < FCAM_H_ERROR + 4) ||
        (i >= FCAM_H_RESPONSE_FNV && i < FCAM_H_PRODUCER_TID);
}
static int exchange(const struct fcam_native_origin *origin, uint32_t flags, uint32_t op,
                    const void *input, size_t input_bytes, struct reply *r, uint64_t deadline) {
    if (sequence == UINT64_MAX) return -EOVERFLOW;
    int rc = same_physical_pages();
    if (rc) return rc;
    unsigned char expected[FCAM_HEADER_BYTES];
    snapshot(expected, 0, sizeof expected);
    if (binding(expected) || (status_load() != FCAM_STATUS_IDLE && status_load() != FCAM_STATUS_RESPONSE)) return -EPROTO;
    memset(expected + FCAM_H_SEQUENCE, 0, FCAM_H_PAGES - FCAM_H_SEQUENCE);
    put64(expected + FCAM_H_SEQUENCE, ++sequence); put32(expected + FCAM_H_OPCODE, op);
    put32(expected + FCAM_H_REQUEST_BYTES, (uint32_t)input_bytes);
    put32(expected + FCAM_H_RESPONSE_CAPACITY, FCAM_DATA_BYTES); put32(expected + FCAM_H_FLAGS, flags);
    put64(expected + FCAM_H_REQUEST_FNV, fnv(input, input_bytes));
    long tid = syscall(SYS_gettid);
    if (tid <= 0 || tid > INT_MAX) return -EOVERFLOW;
    put32(expected + FCAM_H_PRODUCER_TID, (uint32_t)tid);
    put32(expected + FCAM_H_NATIVE_SOURCE, origin->source); put32(expected + FCAM_H_NATIVE_DESTINATION, origin->destination);
    put32(expected + FCAM_H_NATIVE_COMMAND, origin->command); put32(expected + FCAM_H_NATIVE_BYTES, origin->bytes);
    put64(expected + FCAM_H_NATIVE_FNV, origin->wire_fnv1a64);
    /* Status stays private/old until both data and metadata are present. */
    if (input_bytes) memcpy(mailbox + FCAM_HEADER_BYTES, input, input_bytes);
    memcpy(mailbox + FCAM_H_SEQUENCE, expected + FCAM_H_SEQUENCE, FCAM_H_PAGES - FCAM_H_SEQUENCE);
    status_store(FCAM_STATUS_REQUEST);
    rc = wait_status(FCAM_STATUS_RESPONSE, FCAM_STATUS_REQUEST, deadline);
    if (rc) return rc;
    rc = same_physical_pages();
    if (rc) return rc;
    unsigned char actual[FCAM_HEADER_BYTES]; snapshot(actual, 0, sizeof actual);
    if (binding(actual) || get32(actual + FCAM_H_STATUS) != FCAM_STATUS_RESPONSE) return -EPROTO;
    for (unsigned i = 0; i < FCAM_HEADER_BYTES; ++i)
        if (!variable_field(i) && actual[i] != expected[i]) return -EPROTO;
    int32_t error = (int32_t)get32(actual + FCAM_H_ERROR);
    r->used = get32(actual + FCAM_H_RESPONSE_BYTES); r->token = get64(actual + FCAM_H_RESULT_TOKEN);
    r->total = get64(actual + FCAM_H_RESULT_TOTAL); r->offset = get64(actual + FCAM_H_RESULT_OFFSET);
    if (error > 0 || error < -4095 || r->used > FCAM_DATA_BYTES || r->total > FCAM_MAX_RESULT_BYTES ||
        r->offset > r->total || (r->token ? (!r->total || r->used > r->total - r->offset || !r->used) : (r->total || r->offset)) ||
        (error && (r->used || r->total || r->offset || r->token))) return -EPROTO;
    snapshot(r->data, FCAM_HEADER_BYTES, r->used);
    if (status_load() != FCAM_STATUS_RESPONSE || fnv(r->data, r->used) != get64(actual + FCAM_H_RESPONSE_FNV)) return -EBADMSG;
    if (r->token && r->used != (r->total - r->offset < FCAM_DATA_BYTES ? r->total - r->offset : FCAM_DATA_BYTES)) return -EPROTO;
    if (error) return error;
    if ((op == FCAM_OP_INIT || op == FCAM_OP_STATE || op == FCAM_OP_CONFIGURE || op == FCAM_OP_VIDEO_BEGIN || op == FCAM_OP_CANCEL) &&
        (r->used != FCAM_STATE_BYTES || r->token || get32(r->data + FCAM_S_ABI) != FCAM_ABI_VERSION ||
         get64(r->data + FCAM_S_INSTANCE) != nonce || !zero_bytes(r->data + 120, 8))) return -EPROTO;
    if (op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA || op == FCAM_OP_VDF_LAYOUT ||
        op == FCAM_OP_VDF_DISPLAY_CONFIG || op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM ||
        op == FCAM_OP_VDF_BIT_WIDTH) {
        const unsigned int bytes = op == FCAM_OP_VDF_BIT_WIDTH ? FCAM_BIT_WIDTH_RESULT_BYTES :
            op == FCAM_OP_VDF_PATH ? FCAM_VDF_RESULT_BYTES :
            op == FCAM_OP_VDF_ZEBRA ? FCAM_ZEBRA_RESULT_BYTES :
            op == FCAM_OP_VDF_LAYOUT ? FCAM_LAYOUT_RESULT_BYTES :
            op == FCAM_OP_BB_STARTUP_CONFIG ? FCAM_BB_RESULT_BYTES :
            op == FCAM_OP_HISTOGRAM ? FCAM_HIST_RESULT_BYTES : FCAM_DISPLAY_RESULT_BYTES;
        if (r->used != bytes || r->token || get32(r->data + FCAM_VDF_R_ABI) != FCAM_ABI_VERSION ||
            get32(r->data + FCAM_VDF_R_BYTES) != bytes || get64(r->data + FCAM_VDF_R_INSTANCE) != nonce ||
            !zero_bytes(r->data + FCAM_VDF_R_STATUS, 8) ||
            (op == FCAM_OP_BB_STARTUP_CONFIG && get32(r->data + FCAM_VDF_R_CLASS) != FCAM_BB_CLASS) ||
            (op == FCAM_OP_HISTOGRAM && get32(r->data + FCAM_VDF_R_CLASS) != FCAM_HIST_CLASS) ||
            (op == FCAM_OP_VDF_BIT_WIDTH && !bit_width_reply_valid(r->data, input))) return -EPROTO;
    }
    if (op == FCAM_OP_AUTOFOCUS && (r->used != FCAM_AF_BYTES || r->token || !zero_bytes(r->data + 24, 8))) return -EPROTO;
    if (op == FCAM_OP_RELEASE_RESULT && (r->used || r->token)) return -EPROTO;
    if (op == FCAM_OP_STILL && !r->token) return -EPROTO;
    if (op == FCAM_OP_AP_SOURCE_SNAPSHOT && (!r->token ||
        r->total != get32((const unsigned char *)input + FCAM_FACE_SNAPSHOT_BYTES_AT))) return -EPROTO;
    if ((op == FCAM_OP_VIDEO_FRAME || op == FCAM_OP_VIDEO_END) && r->used && !r->token) return -EPROTO;
    return 0;
}
static int public_op(uint32_t op, const void *input, size_t n) {
    switch (op) {
    case FCAM_OP_INIT: return n == 0 || n == FCAM_CONFIG_BYTES;
    case FCAM_OP_STATE: case FCAM_OP_VIDEO_FRAME: case FCAM_OP_VIDEO_END: case FCAM_OP_CANCEL: return n == 0;
    case FCAM_OP_CONFIGURE: case FCAM_OP_VIDEO_BEGIN: return n == FCAM_CONFIG_BYTES;
    case FCAM_OP_VDF_PATH: return n == FCAM_VDF_INPUT_BYTES;
    case FCAM_OP_VDF_ZEBRA: return n == FCAM_ZEBRA_INPUT_BYTES;
    case FCAM_OP_VDF_LAYOUT: return n == FCAM_LAYOUT_INPUT_BYTES;
    case FCAM_OP_VDF_DISPLAY_CONFIG: return n == FCAM_DISPLAY_INPUT_BYTES;
    case FCAM_OP_BB_STARTUP_CONFIG: return n == FCAM_BB_INPUT_BYTES;
    case FCAM_OP_HISTOGRAM: return n == FCAM_HIST_INPUT_BYTES;
    case FCAM_OP_VDF_BIT_WIDTH: return n == FCAM_BIT_WIDTH_INPUT_BYTES;
    case FCAM_OP_AUTOFOCUS: return n == FCAM_AF_BYTES;
    case FCAM_OP_STILL: return n == 16 || n == 144;
    case FCAM_OP_AP_SOURCE_SNAPSHOT: {
        if (n < FCAM_FACE_SNAPSHOT_BASE_BYTES || n > FCAM_FACE_SNAPSHOT_MAX_INPUT_BYTES) return 0;
        const unsigned char *p = input;
        uint32_t cp = get32(p + FCAM_FACE_SNAPSHOT_CP_COUNT_AT), sdk = get32(p + FCAM_FACE_SNAPSHOT_SDK_COUNT_AT);
        uint32_t unit = get32(p + FCAM_FACE_SNAPSHOT_UNIT_AT), bytes = get32(p + FCAM_FACE_SNAPSHOT_BYTES_AT);
        static const uint32_t sizes[3] = {0x64000, 0xc800, 0xd100};
        return get32(p) == FCAM_FACE_SNAPSHOT_VERSION && unit >= 0x1d9 && unit <= 0x1db &&
            bytes == sizes[unit - 0x1d9] && cp == (bytes + FCAM_PAGE_BYTES - 1) / FCAM_PAGE_BYTES &&
            cp <= FCAM_FACE_SNAPSHOT_MAX_CP_PAGES && sdk && sdk <= FCAM_FACE_SNAPSHOT_MAX_SDK_PAGES &&
            n == FCAM_FACE_SNAPSHOT_BASE_BYTES + 8u * (cp + sdk);
    }
    default: return 0;
    }
}
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op,
    const void *input, size_t input_bytes, void *output, size_t capacity, struct fcam_bridge_result *result) {
    int saved_errno = errno, rc = enter();
    if (rc) return fail_early(rc, saved_errno);
    if (!mailbox || retired || poisoned) return leave(-ESHUTDOWN, saved_errno);
    if (!origin || !result || !valid_span(origin, sizeof *origin) || !valid_span(result, sizeof *result) ||
        !valid_span(input, input_bytes) || !valid_span(output, capacity) || input_bytes > FCAM_DATA_BYTES ||
        !public_op(op, input, input_bytes) ||
        overlaps(input, input_bytes, output, capacity) || overlaps(origin, sizeof *origin, output, capacity) ||
        overlaps(result, sizeof *result, output, capacity) || overlaps(result, sizeof *result, input, input_bytes) ||
        overlaps(result, sizeof *result, origin, sizeof *origin) ||
        overlaps(mailbox, FCAM_MAILBOX_BYTES, input, input_bytes) || overlaps(mailbox, FCAM_MAILBOX_BYTES, output, capacity) ||
        overlaps(mailbox, FCAM_MAILBOX_BYTES, result, sizeof *result) || overlaps(mailbox, FCAM_MAILBOX_BYTES, origin, sizeof *origin))
        return leave(-EINVAL, saved_errno);
    if ((op == FCAM_OP_BB_STARTUP_CONFIG && capacity < FCAM_BB_RESULT_BYTES) ||
        (op == FCAM_OP_HISTOGRAM && capacity < FCAM_HIST_RESULT_BYTES) ||
        (op == FCAM_OP_VDF_BIT_WIDTH && capacity < FCAM_BIT_WIDTH_RESULT_BYTES))
        return leave(-ENOSPC, saved_errno);
    const struct fcam_native_origin native = *origin;
    if (!native.source || !native.destination || !native.bytes) return leave(-EINVAL, saved_errno);
    if (op == FCAM_OP_VDF_BIT_WIDTH) {
        const unsigned char *p = input;
        if (!zero_bytes(p + 1, FCAM_BIT_WIDTH_INPUT_BYTES - 1) ||
            native.command != 0x015eu || native.bytes != 10) return leave(-EINVAL, saved_errno);
        if (p[0] != FCAM_BIT_WIDTH_SOFTWARE_RGB888_SELECTOR) return leave(-ENOTSUP, saved_errno);
    }
    const uint32_t flags = op == FCAM_OP_AP_SOURCE_SNAPSHOT ? FCAM_ORIGIN_API40_SOURCE_SNAPSHOT : 0;
    if (flags) {
        const unsigned char *p = input;
        if (native.source != get32(p + FCAM_FACE_SNAPSHOT_AP_HANDLE_AT) ||
            native.destination != get32(p + FCAM_FACE_SNAPSHOT_CP_HANDLE_AT) ||
            native.command != FCAM_FACE_SNAPSHOT_COMMAND || native.bytes != 40 ||
            native.wire_fnv1a64 != get64(p + FCAM_FACE_SNAPSHOT_API_FNV_AT) ||
            native.wire_fnv1a64 != fnv(p + FCAM_FACE_SNAPSHOT_API40_AT, 40)) return leave(-EINVAL, saved_errno);
    }
    struct fcam_bridge_result value = {0, 0, nonce, 0};
    uint64_t deadline = 0;
    rc = deadline_start(&deadline);
    if (rc) return leave(rc, saved_errno);
    struct reply *r = &reply_storage;
    rc = exchange(&native, flags, op, input, input_bytes, r, deadline);
    size_t copied = 0, written = 0; uint64_t whole = FNV_SEED, token = 0, total = 0, first_seq = sequence;
    if (!rc) {
        token = r->token; total = token ? r->total : r->used;
        value.required = (size_t)total; value.result_token = token;
        if (r->offset) rc = -EPROTO;
        else if (total > capacity) rc = -ENOSPC;
        else {
            for (;;) {
                if (r->token != token || (token && r->total != total) || r->offset != (token ? copied : 0) ||
                    r->used > total - copied || (copied < total && !r->used)) { rc = -EPROTO; break; }
                if (r->used) {
                    unsigned char *destination = (unsigned char *)output + copied;
                    memcpy(destination, r->data, r->used);
                    written = copied + r->used;
#ifdef FCAM_HOST_TEST
                    fcam_test_after_copy(destination, r->used);
#endif
                    __atomic_thread_fence(__ATOMIC_SEQ_CST);
                    const volatile unsigned char *actual = destination;
                    for (size_t i = 0; i < r->used; ++i) destination_readback[i] = actual[i];
                    if (memcmp(destination_readback, r->data, r->used) || fnv(destination_readback, r->used) != fnv(r->data, r->used)) { rc = -EIO; break; }
                    whole = fnv_more(whole, destination_readback, r->used); copied += r->used;
                }
                if (copied == total) break;
                unsigned char request[24] = {0}; put64(request, token); put64(request + 8, copied);
                put32(request + 16, FCAM_DATA_BYTES);
                rc = exchange(&native, flags, FCAM_OP_READ_RESULT, request, sizeof request, r, deadline);
                if (rc) break;
            }
            if (!rc && (copied != total || destination_fnv(output, copied) != whole)) rc = -EIO;
            if (!rc && token) {
                unsigned char release[16]; put64(release, token); put64(release + 8, whole);
                rc = exchange(&native, flags, FCAM_OP_RELEASE_RESULT, release, sizeof release, r, deadline);
            }
            if (!rc && destination_fnv(output, copied) != whole) rc = -EIO;
        }
    }
    if (rc && token && status_load() == FCAM_STATUS_RESPONSE) {
        int cancel_rc = exchange(&native, flags, FCAM_OP_CANCEL, NULL, 0, r, deadline);
        if (cancel_rc) { poisoned = 1; note("FUNCTIONAL_CAMERA_CANCEL_FAILED ", "retained-result-not-confirmed-cancelled"); }
    }
    if (rc == -ETIMEDOUT || rc == -EPROTO || rc == -EBADMSG || status_load() == FCAM_STATUS_REQUEST) poisoned = 1;
    char text[768];
    snprintf(text, sizeof text, "seq=%" PRIu64 "..%" PRIu64 " op=%u source=%#x destination=%#x command=%#x bytes=%u native_fnv=%#" PRIx64
        " request_bytes=%zu request_fnv=%#" PRIx64 " returned_bytes=%zu returned_fnv=%#" PRIx64 " required=%" PRIu64
        " destination_written_bytes=%zu destination_fnv=%#" PRIx64
        " model_instance=%#" PRIx64 " token=%#" PRIx64 " readback_closed=%d error=%d origin_kind=%s",
        first_seq, sequence, op, native.source, native.destination, native.command, native.bytes, native.wire_fnv1a64,
        input_bytes, fnv(input, input_bytes), copied, whole, total, written, destination_fnv(output, written), nonce, token, rc == 0, rc,
        flags ? "api40-source-snapshot" : "native-osal");
    note("FUNCTIONAL_CAMERA_TRANSFER ", text);
    if (!rc) { value.used = copied; *result = value; }
    else if (rc == -ENOSPC) *result = value;
    return leave(rc, saved_errno);
}
int fcam_bridge_bb_startup_config(const struct fcam_native_origin *origin,
    const unsigned char input[FCAM_BB_INPUT_BYTES], unsigned char output[FCAM_BB_RESULT_BYTES],
    struct fcam_bridge_result *result) {
    return fcam_bridge_call(origin, FCAM_OP_BB_STARTUP_CONFIG, input, FCAM_BB_INPUT_BYTES,
                           output, FCAM_BB_RESULT_BYTES, result);
}
int fcam_bridge_histogram(const struct fcam_native_origin *origin,
    const unsigned char input[FCAM_HIST_INPUT_BYTES], unsigned char output[FCAM_HIST_RESULT_BYTES],
    struct fcam_bridge_result *result) {
    return fcam_bridge_call(origin, FCAM_OP_HISTOGRAM, input, FCAM_HIST_INPUT_BYTES,
                           output, FCAM_HIST_RESULT_BYTES, result);
}
int fcam_bridge_close(void) {
    int saved_errno = errno, rc = enter();
    if (rc) return fail_early(rc, saved_errno);
    if (!mailbox) { retired = 1; return leave(0, saved_errno); }
    poisoned = 1; /* A timed-out close retains storage, not permission for new requests. */
    uint64_t deadline = 0;
    rc = deadline_start(&deadline);
    unsigned char before[FCAM_HEADER_BYTES], after[FCAM_HEADER_BYTES]; snapshot(before, 0, sizeof before);
    if (!rc) rc = same_physical_pages();
    if (!rc) rc = binding(before);
    uint32_t status = status_load();
    if (!rc && status != FCAM_STATUS_CLOSED && status != FCAM_STATUS_DETACHED) status_store(FCAM_STATUS_CLOSED);
    if (!rc) rc = wait_status(FCAM_STATUS_DETACHED, FCAM_STATUS_CLOSED, deadline);
    if (!rc) {
        snapshot(after, 0, sizeof after);
        if (binding(after) || get32(after + FCAM_H_STATUS) != FCAM_STATUS_DETACHED) rc = -EPROTO;
        for (unsigned i = 0; !rc && i < FCAM_HEADER_BYTES; ++i)
            if (!(i >= FCAM_H_STATUS && i < FCAM_H_STATUS + 4) && before[i] != after[i]) rc = -EPROTO;
    }
    if (!rc) {
        if (unpin(mailbox, FCAM_MAILBOX_BYTES)) rc = -errno;
        else if (munmap(mailbox, FCAM_MAILBOX_BYTES)) rc = -errno;
        else { mailbox = NULL; retired = 1; }
    }
    char text[128]; snprintf(text, sizeof text, "pid=%d detached=%d mapping_retained=%d error=%d", owner_pid, rc == 0, mailbox != NULL, rc);
    note("FUNCTIONAL_CAMERA_CLEANUP ", text);
    return leave(rc, saved_errno);
}
