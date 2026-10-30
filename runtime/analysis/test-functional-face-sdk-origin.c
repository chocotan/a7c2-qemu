/* SPDX-License-Identifier: MIT */
/* Host ABI boundaries only; production decoder, AP observer and CP ledger run. */
#define main sdk_origin_runtime_fixture_main
#include "test-functional-face-runtime.c"
#undef main
#include <dlfcn.h>
#include <limits.h>
#include <stdarg.h>
#include "functional-face-transfer.h"
#include "functional-face-ap-observer.h"
#include "functional-face-proc.h"

#define APP_BASE UINT64_C(0x400000000)
#define FRAME UINT64_C(0x600000000)
#define CALL_OFFSET UINT64_C(0x35150c8)
#define CALLBACK_OFFSET UINT64_C(0x3514c88)
#define SOURCE_HANDLE UINT32_C(0x42d)
#define MEM_FD 57

struct functional_face_native_proc_birth {
    int owner_pid, error;
    int64_t owner_tid;
    uint64_t observation, allocation_token;
    unsigned int attempted;
    struct functional_face_proc_unit row;
};
static _Thread_local struct functional_face_native_proc_birth functional_face_native_proc_births[4];
static _Thread_local struct functional_face_ap_observer functional_face_ap_state;
static int functional_camera_enabled;
static uintptr_t appfw_base, logical_caller;
static int64_t logical_tid;
static int (*real_dladdr)(void *, Dl_info *);
typedef int (*host_sdk_sender)(const void *);
/* ISO C host boundary: the resolver returns the exact function type, avoiding
 * POSIX object/function-pointer conversion diagnostics in the extracted body. */
static host_sdk_sender (*real_dlsym)(void *, const char *);
static uint64_t functional_face_producer_owner(void) {
    return ((uint64_t)(unsigned int)getpid() << 32) | UINT64_C(0x46414345);
}

enum memory_slot { CALL_CODE, CALLBACK_CODE, API40, SOURCE_DESC, DEST_DESC, CONTEXT, SLOT_COUNT };
struct memory_region {
    uintptr_t address;
    size_t bytes;
    unsigned char wire[40];
    unsigned int reads, short_read, change_read, fail_read;
};
static struct memory_region regions[SLOT_COUNT];
static unsigned int open_calls, close_calls, forbidden_reads, dladdr_calls, resolver_calls;
static unsigned int sdk_calls, origin_logs, return_logs;
static unsigned int dladdr_failure, open_failure, resolver_mode;
static const char *module_name;
static uintptr_t module_base;
static int original_result, original_entry_errno;
static const void *expected_original_api, *actual_original_api;
static char last_origin_log[1000], last_return_log[1000];
int interchip_transfer_async(const void *);
struct functional_face_sdk_origin;
/* This fixture tests origin/fallback only; full HLE runs in source-main tests. */
static unsigned int source_route_handled, source_route_calls;
static int functional_face_try_source_snapshot(const struct functional_face_sdk_origin *origin,int *result) {
    assert(origin && result);
    ++source_route_calls;
    if(source_route_handled)*result=0;
    errno=E2BIG;
    return (int)source_route_handled;
}

static int logical_open(const char *path, int flags) {
    assert(!strcmp(path, "/proc/self/mem") && !flags);
    ++open_calls; errno = EACCES;
    return open_failure ? -1 : MEM_FD;
}
static long logical_pread(int fd, void *out, size_t bytes, long offset) {
    assert(fd == MEM_FD && out); errno = EIO;
    for (unsigned int i = 0; i < SLOT_COUNT; ++i) {
        struct memory_region *r = &regions[i];
        if ((uintptr_t)offset != r->address || bytes != r->bytes) continue;
        unsigned int nth = ++r->reads;
        if (nth == r->fail_read) return -EIO;
        size_t n = nth == r->short_read ? bytes - 1 : bytes;
        memcpy(out, r->wire, n);
        if (nth == r->change_read && n) ((unsigned char *)out)[0] ^= 1;
        return (long)n;
    }
    ++forbidden_reads;
    return -ERANGE;
}
static int logical_close(int fd) {
    assert(fd == MEM_FD); ++close_calls; errno = EBADF; return 0;
}
static long logical_syscall(long number, ...) {
    assert(number == 178); errno = EINTR; return (long)logical_tid;
}
static int logical_dladdr(void *address, Dl_info *info) {
    assert((uintptr_t)address == logical_caller && info);
    ++dladdr_calls; errno = EINVAL;
    *info = (Dl_info){.dli_fbase = (void *)module_base, .dli_fname = module_name};
    return !dladdr_failure;
}
static void origin_record(const char *prefix, const char *text) {
    assert(strstr(text, "provider_bound=0") && strstr(text, "source_memory_ready=0") &&
           strstr(text, "capture_verified=0"));
    if (!strcmp(prefix, "FUNCTIONAL_FACE_DMM_API40_ORIGIN ")) {
        ++origin_logs;
        assert(strstr(text, "allocation_pin_verified=0"));
        assert(snprintf(last_origin_log, sizeof last_origin_log, "%s", text) > 0);
    } else {
        assert(!strcmp(prefix, "FUNCTIONAL_FACE_DMM_API40_RETURN "));
        ++return_logs;
        assert(strstr(text, "original_sender_invoked=1") && strstr(text, "callback_invoked_by_model=0"));
        assert(snprintf(last_return_log, sizeof last_return_log, "%s", text) > 0);
    }
    printf("%s%s\n", prefix, text);
    errno = EOVERFLOW;
}
static int original_sdk(const void *api) {
    assert(api == expected_original_api && errno == original_entry_errno);
    ++sdk_calls; actual_original_api = api;
    errno = EAGAIN;
    return original_result;
}
static host_sdk_sender logical_dlsym(void *handle, const char *name) {
    assert(handle == RTLD_NEXT && !strcmp(name, "interchip_transfer_async"));
    assert(errno == original_entry_errno);
    ++resolver_calls; errno = ENOTTY;
    return resolver_mode == 1 ? NULL : resolver_mode == 2 ? interchip_transfer_async : original_sdk;
}

/* The return-PC macro is an explicit trust-boundary mock: host return addresses
 * cannot equal the logical appFw.so AArch64 caller. No Sony callee is executed. */
#define open logical_open
#define pread logical_pread
#define close logical_close
#define syscall logical_syscall
#define record origin_record
#define __builtin_return_address(depth) ((void)(depth), (void *)logical_caller)
/* ACTUAL_SDK_ORIGIN */
#undef __builtin_return_address
#undef record
#undef syscall
#undef close
#undef pread
#undef open

static struct functional_face_dmm_descriptor creators[3];
static unsigned int creator_live[3];
static const size_t unit_bytes[3] = {0x64000, 0xc800, 0xd100};

static struct functional_face_runtime_ticket cp_complete(void) {
    void *actual = NULL;
    struct functional_face_runtime_ticket ticket;
    int rc = original_receive(QUEUE, &actual);
    assert(functional_face_runtime_observe(functional_face_producer_owner(), QUEUE, actual, rc, &ticket) == 1);
    rc = 73;
    assert(functional_face_runtime_release(functional_face_producer_owner(), QUEUE, actual,
        &ticket, release, &rc) == 1 && !rc && !pending);
    return ticket;
}
static void cp_queue(unsigned int op, unsigned int index) {
    struct functional_face_runtime_caller c = {functional_face_producer_owner(), 0x1d9 + index,
        FUNCTIONAL_FACE_RUNTIME_ACCEPTED, FUNCTIONAL_FACE_RUNTIME_UNIQUE_REFERENCE};
    struct message *m = request(op, c.unit, creators[index].handle);
    int rc = 71;
    assert(functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &rc) == 1 && !rc);
}
static void cp_create(unsigned int index) {
    cp_queue(0x20, index);
    struct functional_face_runtime_ticket t = cp_complete();
    assert(!functional_face_runtime_lookup_creator(functional_face_producer_owner(), 0x1d9 + index, &creators[index]));
    assert(same_span(&creators[index], &t.actual.span));
    assert(creators[index].bytes == unit_bytes[index] && creators[index].handle == 0x8402u + index);
    creator_live[index] = 1;
}
static void cp_retire(unsigned int index) {
    cp_queue(0x23, index); (void)cp_complete(); creator_live[index] = 0;
}
static void ap_transaction(unsigned int op, unsigned int index, uint32_t handle, int status) {
    unsigned char q[40] = {0}, r[40] = {0};
    put(q, op, 2); put(q + 4, 0x1d9 + index, 4); put(q + 8, handle, 4);
    put(r, op | 0x8000u, 2); put(r + 2, (uint16_t)status, 2); put(r + 12, handle, 4);
    assert(functional_face_ap_begin(&functional_face_ap_state, 1, 1, logical_tid,
        FUNCTIONAL_FACE_AP_DMM, QUEUE, q, 40, NULL) == 1);
    functional_face_ap_sent(&functional_face_ap_state, logical_tid, 0, NULL);
    functional_face_ap_received(&functional_face_ap_state, logical_tid, QUEUE, FUNCTIONAL_FACE_AP_DMM, r, 40, 0, NULL);
    functional_face_ap_freed(&functional_face_ap_state, logical_tid, QUEUE, r, 0, NULL);
    assert(!functional_face_ap_state.active && functional_face_ap_state.free_attempts == 1);
}
static void metadata_match(unsigned int index) {
    const struct functional_face_ap_birth *fact = &functional_face_ap_state.births[index];
    functional_face_native_proc_births[index] = (struct functional_face_native_proc_birth){
        .owner_pid = getpid(), .owner_tid = logical_tid, .observation = fact->observation_sequence,
        .allocation_token = UINT64_C(0xface000000000001) + index,
        .attempted = 1, .row = {.unit = 0x1d9 + index, .handle = SOURCE_HANDLE}};
}
static void input_reset(unsigned int index) {
    functional_camera_enabled = 1; appfw_base = APP_BASE; logical_caller = APP_BASE + CALL_OFFSET;
    logical_tid = THREAD_ID(); real_dladdr = logical_dladdr; real_dlsym = logical_dlsym;
    module_name = "/native/appFw.so"; module_base = APP_BASE;
    dladdr_failure = open_failure = resolver_mode = 0;
    open_calls = close_calls = forbidden_reads = dladdr_calls = resolver_calls = 0;
    sdk_calls = origin_logs = return_logs = 0;
    source_route_handled = source_route_calls = 0;
    last_origin_log[0] = last_return_log[0] = 0;
    original_entry_errno = EDOM; original_result = 0; expected_original_api = (void *)(FRAME + 0xb8);
    actual_original_api = NULL;
    __atomic_store_n(&real_interchip_transfer_async, NULL, __ATOMIC_RELEASE);
    memset(regions, 0, sizeof regions);
    regions[CALL_CODE] = (struct memory_region){.address = APP_BASE + CALL_OFFSET - 8, .bytes = 8};
    regions[CALLBACK_CODE] = (struct memory_region){.address = APP_BASE + CALLBACK_OFFSET, .bytes = 8};
    regions[API40] = (struct memory_region){.address = FRAME + 0xb8, .bytes = 40};
    regions[SOURCE_DESC] = (struct memory_region){.address = FRAME + 0x68, .bytes = 8};
    regions[DEST_DESC] = (struct memory_region){.address = FRAME + 0x70, .bytes = 8};
    regions[CONTEXT] = (struct memory_region){.address = FRAME + 0x60, .bytes = 4};
    put(regions[CALL_CODE].wire, UINT64_C(0x978520739102e3a0), 8);
    put(regions[CALLBACK_CODE].wire, UINT64_C(0x910003fda9b97bfd), 8);
    put(regions[API40].wire, FRAME + 0x68, 8); put(regions[API40].wire + 8, FRAME + 0x70, 8);
    put(regions[API40].wire + 16, unit_bytes[index], 4); put(regions[API40].wire + 20, 1, 4);
    put(regions[API40].wire + 24, APP_BASE + CALLBACK_OFFSET, 8);
    put(regions[API40].wire + 32, FRAME + 0x60, 8);
    put(regions[SOURCE_DESC].wire, SOURCE_HANDLE, 4);
    put(regions[DEST_DESC].wire, 0x8402u + index, 4);
    put(regions[CONTEXT].wire, SOURCE_HANDLE, 4);
    memset(&functional_face_ap_state, 0, sizeof functional_face_ap_state);
    memset(functional_face_native_proc_births, 0, sizeof functional_face_native_proc_births);
    ap_transaction(0x20, index, SOURCE_HANDLE, 0);
}
static int origin_call(struct functional_face_sdk_origin *out) {
    errno = EDOM;
    int rc = functional_face_sdk_origin((void *)logical_caller, (void *)(FRAME + 0xb8), out);
    assert(errno == EDOM && !forbidden_reads && !sdk_calls && !return_logs);
    assert(open_calls == close_calls + open_failure);
    return rc;
}
static void reject_origin(void) {
    struct functional_face_sdk_origin out, before;
    memset(&out, 0xa5, sizeof out); before = out;
    int rc = origin_call(&out);
    assert(rc < 0 && !memcmp(&out, &before, sizeof out));
}
static void check_unwritten(const struct memory_region *before) {
    for (unsigned int i = 0; i < SLOT_COUNT; ++i)
        assert(!memcmp(before[i].wire, regions[i].wire, sizeof regions[i].wire));
}
static void positive(unsigned int index, unsigned int metadata) {
    input_reset(index); if (metadata) metadata_match(index);
    struct memory_region saved[SLOT_COUNT]; memcpy(saved, regions, sizeof saved);
    struct functional_face_ap_observer saved_ap = functional_face_ap_state;
    struct functional_face_native_proc_birth saved_proc[4];
    memcpy(saved_proc, functional_face_native_proc_births, sizeof saved_proc);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    uint64_t commit = diagnostic.ledger_commit, receives_before = diagnostic.actual_receive;
    struct functional_face_sdk_origin out = {0}; assert(!origin_call(&out));
    assert(out.frame == FRAME && out.input_pointer == FRAME + 0xb8 && out.unit == 0x1d9 + index);
    assert(out.request.input.source_handle == SOURCE_HANDLE && out.request.input.destination_handle == creators[index].handle);
    assert(out.request.input.bytes == unit_bytes[index] && !out.request.input.source_offset && !out.request.input.destination_offset);
    assert(out.request.source_descriptor == FRAME + 0x68 && out.request.destination_descriptor == FRAME + 0x70);
    assert(out.request.callback == APP_BASE + CALLBACK_OFFSET && out.request.callback_context == FRAME + 0x60);
    assert(out.birth.observations == 1 && !out.birth.ambiguous && !out.birth.any_free_observed);
    assert(same_span(&out.destination, &creators[index]) && out.native_metadata_observed == metadata);
    assert(out.allocation_token == (metadata ? UINT64_C(0xface000000000001) + index : 0));
    assert(!memcmp(out.api40, regions[API40].wire, 40));
    assert(!memcmp(out.source_descriptor, regions[SOURCE_DESC].wire, 8));
    assert(!memcmp(out.destination_descriptor, regions[DEST_DESC].wire, 8));
    assert(strstr(last_origin_log, "original_caller_bound=1"));
    for (unsigned int i = 0; i < SLOT_COUNT; ++i) assert(regions[i].reads == 2);
    assert(regions[SOURCE_DESC].reads + regions[DEST_DESC].reads == 4);
    assert(!memcmp(&saved_ap, &functional_face_ap_state, sizeof saved_ap));
    assert(!memcmp(saved_proc, functional_face_native_proc_births, sizeof saved_proc));
    check_unwritten(saved);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(diagnostic.ledger_commit == commit && diagnostic.actual_receive == receives_before);
    for (unsigned int i = 0; i < 3; ++i) {
        assert(!diagnostic.model.units[i].borrows && !diagnostic.model.units[i].verified_write_bytes &&
            !diagnostic.model.units[i].verified_read_bytes);
    }
    printf("ORIGIN_UNIT unit=%x bytes=%zu native_metadata=%u descriptor_reads=4 provider_bound=0 source_memory_ready=0 capture_verified=0\n",
        out.unit, unit_bytes[index], metadata);
}
static void gates(void) {
    for (unsigned int k = 0; k < 8; ++k) {
        input_reset(0);
        struct functional_face_sdk_origin out, saved; memset(&out, 0xa5, sizeof out); saved = out;
        void *pc = (void *)logical_caller; const void *api = (void *)(FRAME + 0xb8);
        if (k == 0) functional_camera_enabled = 0;
        if (k == 1) pc = NULL;
        if (k == 2) api = NULL;
        if (k == 3) appfw_base = 0;
        if (k == 4) real_dladdr = NULL;
        if (k == 5) pc = (void *)(logical_caller + 4);
        if (k == 6) open_failure = 1;
        errno = EDOM;
        assert(functional_face_sdk_origin(pc, api, k == 7 ? NULL : &out) < 0);
        assert(errno == EDOM && !memcmp(&out, &saved, sizeof out) && !forbidden_reads);
        assert(open_calls == (k == 6) && !close_calls);
    }
}
static void modules(void) {
    const char *names[] = {NULL, "", "appFw.s", "evilappFw.so", "/x/notappFw.so", "/appFw.so.old"};
    for (unsigned int k = 0; k < sizeof names / sizeof *names + 2; ++k) {
        input_reset(0);
        if (k < sizeof names / sizeof *names) module_name = names[k];
        else if (k == sizeof names / sizeof *names) ++module_base;
        else dladdr_failure = 1;
        reject_origin(); assert(!open_calls);
    }
    input_reset(0); module_name = "appFw.so";
    struct functional_face_sdk_origin out; assert(!origin_call(&out));
}
static void code_checks(enum memory_slot slot) {
    for (unsigned int k = 0; k < 7; ++k) {
        input_reset(0);
        struct memory_region *r = &regions[slot];
        if (k == 0) r->wire[0] ^= 1;
        if (k == 1) r->short_read = 1;
        if (k == 2) r->short_read = 2;
        if (k == 3) r->change_read = 2;
        if (k == 4) r->fail_read = 1;
        if (k == 5) r->fail_read = 2;
        if (k == 6) r->wire[7] ^= 1;
        reject_origin(); assert(!regions[API40].reads && !regions[SOURCE_DESC].reads && !regions[CONTEXT].reads);
    }
}
static void api_prefix(void) {
    for (unsigned int k = 0; k < 5; ++k) {
        input_reset(0);
        if (k < 2) regions[API40].short_read = k + 1;
        if (k == 2) regions[API40].change_read = 2;
        if (k >= 3) regions[API40].fail_read = k - 2;
        reject_origin(); assert(!regions[SOURCE_DESC].reads && !regions[DEST_DESC].reads);
    }
    input_reset(0);
    unsigned char raw39[39], raw40[40];
    memcpy(raw39, regions[API40].wire, sizeof raw39); memcpy(raw40, regions[API40].wire, sizeof raw40);
    struct functional_face_sdk_frame_reader r = {MEM_FD, FRAME};
    struct functional_face_api_request out, saved; memset(&out, 0xa5, sizeof out); saved = out;
    assert(functional_face_transfer_decode_api40(raw39, sizeof raw39, functional_face_sdk_frame_read, &r, &out) == -EINVAL);
    assert(!memcmp(&out, &saved, sizeof out) && !regions[SOURCE_DESC].reads);
    assert(!functional_face_transfer_decode_api40(raw40, sizeof raw40, functional_face_sdk_frame_read, &r, &out));
    assert(regions[SOURCE_DESC].reads == 2 && regions[DEST_DESC].reads == 2 && !forbidden_reads);
}
static void descriptors(void) {
    for (unsigned int k = 0; k < 8; ++k) {
        input_reset(0);
        struct memory_region *r = &regions[k & 1u ? DEST_DESC : SOURCE_DESC];
        if (k < 4) r->short_read = k / 2 + 1;
        else if (k < 6) r->change_read = 2;
        else r->fail_read = 2;
        reject_origin();
        assert(regions[SOURCE_DESC].reads == 2 && regions[DEST_DESC].reads == 2 && !regions[CONTEXT].reads);
    }
    input_reset(0); struct functional_face_sdk_frame_reader r = {MEM_FD, FRAME}; unsigned char out[8] = {0};
    assert(functional_face_sdk_frame_read(NULL, FRAME + 0x68, out, 8) == -ERANGE);
    r.fd = -1; assert(functional_face_sdk_frame_read(&r, FRAME + 0x68, out, 8) == -ERANGE); r.fd = MEM_FD;
    assert(functional_face_sdk_frame_read(&r, FRAME + 0x68, NULL, 8) == -ERANGE);
    assert(functional_face_sdk_frame_read(&r, FRAME + 0x68, out, 7) == -ERANGE);
    assert(functional_face_sdk_frame_read(&r, FRAME + 0x60, out, 8) == -ERANGE);
    assert(functional_face_sdk_frame_read(&r, FRAME + 0x78, out, 8) == -ERANGE);
    assert(!regions[SOURCE_DESC].reads && !regions[DEST_DESC].reads && !forbidden_reads);
}
static void schema(void) {
    for (unsigned int k = 0; k < 14; ++k) {
        input_reset(0);
        if (k == 0) put(regions[API40].wire + 20, 0, 4);
        if (k == 1) put(regions[API40].wire + 20, 2, 4);
        if (k == 2) put(regions[API40].wire + 24, APP_BASE + CALLBACK_OFFSET + 4, 8);
        if (k == 3) put(regions[API40].wire + 32, FRAME + 0x64, 8);
        if (k == 4) put(regions[SOURCE_DESC].wire + 4, 1, 4);
        if (k == 5) put(regions[DEST_DESC].wire + 4, 1, 4);
        if (k == 6) put(regions[API40].wire + 16, 0x64001, 4);
        if (k == 7) put(regions[API40].wire + 16, 0xc800, 4);
        if (k == 8) put(regions[SOURCE_DESC].wire, 0, 4);
        if (k == 9) put(regions[SOURCE_DESC].wire, 0x2d, 4);
        if (k == 10) put(regions[SOURCE_DESC].wire, 0x842d, 4);
        if (k == 11) put(regions[DEST_DESC].wire, 0x402, 4);
        if (k == 12) put(regions[DEST_DESC].wire, 0x8401, 4);
        if (k == 13) put(regions[DEST_DESC].wire, 0x8405, 4);
        reject_origin();
    }
}
static void pointers(void) {
    const uintptr_t bad[] = {1, 0xb7, FRAME + 0xb9, UINTPTR_MAX, (uintptr_t)INT64_MAX - 39};
    for (unsigned int k = 0; k < sizeof bad / sizeof *bad; ++k) {
        input_reset(0); struct functional_face_sdk_origin out, saved;
        memset(&out, 0xa5, sizeof out); saved = out; errno = EDOM;
        assert(functional_face_sdk_origin((void *)logical_caller, (void *)bad[k], &out) < 0);
        assert(errno == EDOM && !memcmp(&out, &saved, sizeof out) && !open_calls && !forbidden_reads);
    }
    input_reset(0); appfw_base = UINTPTR_MAX - CALL_OFFSET + 1;
    reject_origin(); assert(!open_calls && !dladdr_calls);
    const uint64_t desc[] = {0, UINT64_MAX, FRAME + 0x60, FRAME + 0x78};
    for (unsigned int k = 0; k < sizeof desc / sizeof *desc; ++k) {
        input_reset(0); put(regions[API40].wire, desc[k], 8); reject_origin();
        assert(!regions[SOURCE_DESC].reads && !forbidden_reads);
    }
    input_reset(0); put(regions[API40].wire, FRAME + 0x70, 8); put(regions[API40].wire + 8, FRAME + 0x68, 8);
    reject_origin();
}
static void context_checks(void) {
    for (unsigned int k = 0; k < 7; ++k) {
        input_reset(0);
        if (k == 0) put(regions[CONTEXT].wire, SOURCE_HANDLE ^ 1u, 4);
        if (k == 1) regions[CONTEXT].change_read = 2;
        if (k == 2 || k == 3) regions[CONTEXT].short_read = k - 1;
        if (k == 4 || k == 5) regions[CONTEXT].fail_read = k - 3;
        if (k == 6) put(regions[CONTEXT].wire, SOURCE_HANDLE + 0x400, 4);
        reject_origin(); assert(regions[SOURCE_DESC].reads == 2 && regions[DEST_DESC].reads == 2);
    }
}
static void cp_lifetime(void) {
    input_reset(0); struct functional_face_sdk_origin out;
    assert(origin_call(&out) == -ENODATA);
    cp_queue(0x20, 0);
    input_reset(0); assert(origin_call(&out) == -ENODATA);
    (void)cp_complete();
    assert(!functional_face_runtime_lookup_creator(functional_face_producer_owner(), 0x1d9, &creators[0]));
    creator_live[0] = 1;
    input_reset(0); assert(!origin_call(&out));
    input_reset(0); put(regions[DEST_DESC].wire, creators[0].handle + 0x400, 4); reject_origin();
    /* Negative corruption of a real published ledger entry, not a fake lookup. */
    size_t capacity = state.units[0].creator.bytes;
    state.units[0].creator.bytes = capacity - 1;
    input_reset(0); reject_origin(); state.units[0].creator.bytes = capacity;
    cp_retire(0); input_reset(0); assert(origin_call(&out) == -ENODATA);
}
static void ap_facts(void) {
    for (unsigned int k = 0; k < 6; ++k) {
        input_reset(0);
        if (k == 0) { put(regions[SOURCE_DESC].wire, SOURCE_HANDLE + 0x400, 4); put(regions[CONTEXT].wire, SOURCE_HANDLE + 0x400, 4); }
        if (k == 1) ap_transaction(0x20, 0, SOURCE_HANDLE, 0);
        if (k == 2) ap_transaction(0x23, 0, SOURCE_HANDLE, 0);
        if (k == 3) ap_transaction(0x23, 0, SOURCE_HANDLE, 3);
        if (k == 4) ++functional_face_ap_state.sender_tid;
        if (k == 5) ++functional_face_ap_state.owner_pid;
        reject_origin();
    }
}
static void metadata(void) {
    for (unsigned int k = 0; k < 9; ++k) {
        input_reset(0); metadata_match(0);
        struct functional_face_native_proc_birth *b = &functional_face_native_proc_births[0];
        if (k == 0) b->attempted = 0;
        if (k == 1) b->error = -ENODATA;
        if (k == 2) ++b->owner_pid;
        if (k == 3) ++b->owner_tid;
        if (k == 4) ++b->observation;
        if (k == 5) ++b->row.handle;
        if (k == 6) ++b->row.unit;
        if (k == 7) { b->row.address = UINT64_MAX; b->row.bytes = 1; b->row.generation = UINT32_MAX; }
        struct functional_face_sdk_origin out;
        assert(!origin_call(&out) && out.native_metadata_observed == (unsigned int)(k >= 7));
        assert(strstr(last_origin_log, "allocation_pin_verified=0"));
    }
}
static void fork_pid_tid(void) {
    input_reset(0); metadata_match(0);
    pid_t child = fork(); assert(child >= 0);
    if (!child) { reject_origin(); _exit(0); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    input_reset(0); ++logical_tid; reject_origin();
}
static void wrapper_once(const void *api, int result, int origin_ok, unsigned int enabled) {
    original_result = result; original_entry_errno = EDOM; expected_original_api = api;
    struct memory_region saved[SLOT_COUNT]; memcpy(saved, regions, sizeof saved);
    struct functional_face_ap_observer ap = functional_face_ap_state;
    unsigned int calls = sdk_calls, resolved = resolver_calls, logs = return_logs;
    unsigned int needs_resolver = !__atomic_load_n(&real_interchip_transfer_async, __ATOMIC_ACQUIRE);
    errno = original_entry_errno;
    assert(interchip_transfer_async(api) == result && errno == EAGAIN);
    assert(sdk_calls == calls + 1 && actual_original_api == api);
    assert(resolver_calls == resolved + needs_resolver);
    assert(return_logs == logs + enabled);
    if (enabled) {
        char text[60]; snprintf(text, sizeof text, "actual_sdk_return=%d ", result);
        assert(strstr(last_return_log, text));
        snprintf(text, sizeof text, "actual_errno=%d ", EAGAIN); assert(strstr(last_return_log, text));
        assert((strstr(last_return_log, "origin_rc=0 ") != NULL) == origin_ok);
    }
    check_unwritten(saved); assert(!memcmp(&ap, &functional_face_ap_state, sizeof ap) && !forbidden_reads);
}
static void wrapper_returns(void) {
    const int values[] = {0, 5, -9};
    for (unsigned int k = 0; k < sizeof values / sizeof *values; ++k) {
        input_reset(k); wrapper_once((void *)(FRAME + 0xb8), values[k], 1, 1);
        wrapper_once((void *)(FRAME + 0xb8), values[k], 1, 1);
        assert(resolver_calls == 1 && sdk_calls == 2 && origin_logs == 2 && return_logs == 2);
    }
}
static void wrapper_rejections(void) {
    for (unsigned int k = 0; k < 6; ++k) {
        input_reset(0); const void *api = (void *)(FRAME + 0xb8);
        if (k == 0) functional_camera_enabled = 0;
        if (k == 1) ++logical_caller;
        if (k == 2) regions[CALL_CODE].wire[0] ^= 1;
        if (k == 3) api = NULL;
        if (k == 4) ap_transaction(0x23, 0, SOURCE_HANDLE, 0);
        if (k == 5) open_failure = 1;
        wrapper_once(api, k & 1u ? -9 : 5, 0, k != 0);
        assert(sdk_calls == 1 && resolver_calls == 1);
    }
}
static void wrapper_resolver(void) {
    for (unsigned int k = 0; k < 3; ++k) {
        input_reset(0);
        if (k == 0) real_dlsym = NULL; else resolver_mode = k;
        errno = EDOM;
        assert(interchip_transfer_async((void *)(FRAME + 0xb8)) == -ENOSYS && errno == EDOM);
        assert(!sdk_calls && !origin_logs && !return_logs && !open_calls);
        assert(resolver_calls == (k != 0) && !__atomic_load_n(&real_interchip_transfer_async, __ATOMIC_ACQUIRE));
    }
    input_reset(0); real_dlsym = NULL;
    __atomic_store_n(&real_interchip_transfer_async, original_sdk, __ATOMIC_RELEASE);
    expected_original_api = (void *)(FRAME + 0xb8); errno = EDOM;
    assert(!interchip_transfer_async(expected_original_api) && errno == EAGAIN && sdk_calls == 1 && !resolver_calls);
}
static void wrapper_handled(void) {
    for(unsigned int i=0;i<3;++i) {
        input_reset(i);metadata_match(i);source_route_handled=1;
        struct memory_region saved[SLOT_COUNT];memcpy(saved,regions,sizeof saved);
        errno=EDOM;
        assert(!interchip_transfer_async((void *)(FRAME+0xb8)) && errno==EDOM);
        assert(source_route_calls==1 && !sdk_calls && resolver_calls==1 && !return_logs && origin_logs==1);
        check_unwritten(saved);
        source_route_handled=0;
        wrapper_once((void *)(FRAME+0xb8),5,1,1);
        assert(source_route_calls==2 && sdk_calls==1);
    }
    input_reset(0);source_route_handled=1;functional_camera_enabled=0;
    wrapper_once((void *)(FRAME+0xb8),5,0,0);
    assert(!source_route_calls && sdk_calls==1);
    input_reset(0);source_route_handled=1;++logical_caller;
    wrapper_once((void *)(FRAME+0xb8),5,0,1);
    assert(!source_route_calls && sdk_calls==1);
}
int main(int argc, char **argv) {
    assert(argc == 2); const char *scenario = argv[1];
    io = (struct full_imaging_io){allocate, release, set_source, send, size, source, NULL};
    assert(!functional_face_runtime_prepare(1, functional_face_producer_owner(), &io, NULL));
    if (strcmp(scenario, "cp-lifetime")) for (unsigned int i = 0; i < 3; ++i) cp_create(i);
    if (!strcmp(scenario, "units")) for (unsigned int i = 0; i < 3; ++i) { positive(i, 0); positive(i, 1); }
    else if (!strcmp(scenario, "gates")) gates();
    else if (!strcmp(scenario, "modules")) modules();
    else if (!strcmp(scenario, "call-code")) code_checks(CALL_CODE);
    else if (!strcmp(scenario, "callback-code")) code_checks(CALLBACK_CODE);
    else if (!strcmp(scenario, "api-prefix")) api_prefix();
    else if (!strcmp(scenario, "descriptors")) descriptors();
    else if (!strcmp(scenario, "schema")) schema();
    else if (!strcmp(scenario, "pointers")) pointers();
    else if (!strcmp(scenario, "context")) context_checks();
    else if (!strcmp(scenario, "cp-lifetime")) cp_lifetime();
    else if (!strcmp(scenario, "ap-facts")) ap_facts();
    else if (!strcmp(scenario, "metadata")) metadata();
    else if (!strcmp(scenario, "fork-pid-tid")) fork_pid_tid();
    else if (!strcmp(scenario, "wrapper-returns")) wrapper_returns();
    else if (!strcmp(scenario, "wrapper-rejections")) wrapper_rejections();
    else if (!strcmp(scenario, "wrapper-resolver")) wrapper_resolver();
    else if (!strcmp(scenario, "wrapper-handled")) wrapper_handled();
    else abort();
    for (unsigned int i = 0; i < 3; ++i) if (creator_live[i]) cp_retire(i);
    assert(!functional_face_runtime_snapshot(&diagnostic) && !diagnostic.live_creators && !diagnostic.faults && !diagnostic.retained);
    assert(!functional_face_dmm_shutdown());
    for (unsigned int i = 0; i < 128; ++i) assert(!messages[i]);
    printf("SDK_ORIGIN_HOSTTEST_PASS scenario=%s actual_decoder=1 actual_ap_observer=1 actual_cp_runtime=1 provider_bound=0 capture_verified=0\n", scenario);
    return 0;
}
