/* SPDX-License-Identifier: MIT */
/* HOST ONLY: extracted Main, real SDK/transfer/CP; typed native IO fixtures. */
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "functional-face-source-snapshot.h"
#include "functional-face-sdk.h"
#include "dmm-service.h"

#define OWNER UINT64_C(0xfacedead1001)
#define QUEUE UINT32_C(0x81cf1234)
#define CALLBACK_OFFSET UINT64_C(0x3514c88)
static int functional_camera_enabled = 1;
static uintptr_t appfw_base;
static int (*real_dladdr)(void *, Dl_info *);
static _Thread_local struct functional_face_ap_observer functional_face_ap_state;
static uint64_t functional_face_producer_owner(void) { return OWNER; }
static long host_syscall(long number) { assert(number == 178); return syscall(SYS_gettid); }
static int host_open(const char *, int);
static int host_close(int);
static long host_pread(int, void *, size_t, long);
static int host_usleep(unsigned int);
static void host_record(const char *, const char *);
static int functional_face_source_current_metadata(void *, unsigned int, unsigned int, struct functional_face_proc_unit *);
static int functional_face_native_ap_command(void *, unsigned int, unsigned int, unsigned int, struct functional_face_ap_observer *);
static int host_snapshot_init(struct functional_face_source_snapshot *,
    const struct functional_face_source_snapshot_config *, struct functional_face_ap_provider *);

#define open host_open
#define close host_close
#define pread host_pread
#define syscall host_syscall
#define usleep host_usleep
#define record host_record
#define functional_face_source_snapshot_init host_snapshot_init
/* ACTUAL_MAIN_DECLARATIONS */
/* ACTUAL_SOURCE_MAIN */
#undef functional_face_source_snapshot_init
#undef record
#undef usleep
#undef syscall
#undef pread
#undef close
#undef open

static void put(unsigned char *p, uint64_t v, size_t n) {
    for (size_t i = 0; i < n; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static uint64_t get(const void *p, size_t n) {
    const unsigned char *q = p; uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= (uint64_t)q[i] << (8 * i);
    return v;
}
static uint64_t hash(const void *p, size_t n) {
    const unsigned char *q = p; uint64_t h = UINT64_C(0xcbf29ce484222325);
    for (size_t i = 0; i < n; ++i) h = (h ^ q[i]) * UINT64_C(0x100000001b3);
    return h;
}

/* The transport owns actual heap messages; only their CP consumer is production. */
struct message { unsigned int source, bytes; unsigned char wire[40]; };
static void *pending;
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p - offsetof(struct message, wire)); }
static int allocate(unsigned int queue, void **out, unsigned int bytes, unsigned int wait) {
    assert(queue == QUEUE && bytes == 40 && wait == 1);
    struct message *m = calloc(1, sizeof *m); assert(m); m->bytes = bytes; *out = m->wire; return 0;
}
static int release(unsigned int queue, void *p) {
    assert(queue == QUEUE || queue == FUNCTIONAL_FACE_DMM_CP);
    if (pending == p) pending = NULL;
    free(envelope(p)); return 0;
}
static void set_source(void *p, unsigned int source) { envelope(p)->source = source; }
static unsigned int msg_source(void *p) { return envelope(p)->source; }
static unsigned int msg_size(void *p) { return envelope(p)->bytes; }
static int send(unsigned int queue, void *p) {
    assert(queue == QUEUE && !pending && msg_source(p) == FUNCTIONAL_FACE_DMM_CP); pending = p; return 0;
}
static const struct full_imaging_io io = {allocate, release, set_source, send, msg_size, msg_source, NULL};
static void cp_operation(unsigned int op, unsigned int unit, unsigned int handle) {
    struct message *m = calloc(1, sizeof *m); assert(m); m->source = QUEUE; m->bytes = 40;
    put(m->wire, op, 2); if (op == 0x20) put(m->wire + 4, unit, 4);
    if (op == 0x23) { put(m->wire + 8, handle, 4); put(m->wire + 20, QUEUE & 0xffffu, 2); }
    else put(m->wire + 12, UINT32_MAX, 4);
    struct functional_face_runtime_caller c = {OWNER, unit, FUNCTIONAL_FACE_RUNTIME_ACCEPTED, FUNCTIONAL_FACE_RUNTIME_UNIQUE_REFERENCE};
    int rc = 71;
    assert(functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &rc) == 1 && !rc);
    assert(pending);
    struct functional_face_runtime_ticket t;
    assert(functional_face_runtime_observe(OWNER, QUEUE, pending, 0, &t) == 1);
    assert(get(t.actual.wire, 2) == (op | 0x8000u) && !get(t.actual.wire + 2, 2));
    assert(functional_face_runtime_release(OWNER, QUEUE, pending, &t, release, &rc) == 1 && !rc && !pending);
}

enum fault {
    OK, BRIDGE_FAIL, METADATA_DRIFT, NATIVE_SHARE, NATIVE_OPEN, CLEANUP_CLOSE, CLEANUP_FREE,
    CALLBACK_PID, CALLBACK_TID, CALLBACK_CODE, CALLBACK_CODE_SHORT, CALLBACK_CODE_DRIFT,
    CALLBACK_CONTEXT, CALLBACK_CONTEXT_SHORT, CALLBACK_CONTEXT_DRIFT, CALLBACK_EXTENT,
    CALLBACK_BASE, CALLBACK_MODULE, CALLBACK_DLADDR
};
struct fixture {
    struct functional_face_sdk_origin origin, origin_before;
    struct functional_face_native_proc_birth birthday, birthdays_before[4];
    struct functional_face_proc_unit current;
    unsigned char *mapping, *source, *expected;
    unsigned char frame_before[FCAM_FACE_SNAPSHOT_FRAME_BYTES];
    unsigned int owners, opens, baseline, commands[4], command_trace[4], command_count, metadata_calls;
    unsigned int init_calls, bridge_calls, pagemap_reads, callbacks, opened, closed, sleeps;
    unsigned int callback_code_reads, callback_context_reads, retained_records, result_records, enter_records, return_records;
    size_t snapshot_bytes, independent_bytes;
    enum fault fault;
    int open_failure, init_result;
    int *result_pointer;
};
static struct fixture f;
static jmp_buf retained_jump;
static unsigned int legacy_sdk_calls, original_sender_calls;
static const unsigned int command_order[4] = {0x21, 0x24, 0x25, 0x23};
static const size_t lengths[3] = {0x64000, 0xc800, 0xd100};
static struct functional_face_source_transaction *transaction(void) {
    return &functional_face_source_transactions[f.origin.unit - 0x1d9];
}
static void assert_frame(void) {
    assert(!memcmp((void *)f.origin.frame, f.frame_before, sizeof f.frame_before));
    assert(!memcmp(&f.origin, &f.origin_before, sizeof f.origin));
    assert(!memcmp(f.birthdays_before, functional_face_native_proc_births, sizeof f.birthdays_before));
    assert(!memcmp(&f.birthday, &functional_face_native_proc_births[f.origin.unit - 0x1d9], sizeof f.birthday));
}
static int host_open(const char *path, int flags) {
    assert(!strcmp(path, "/proc/self/mem") && !flags); ++f.opened;
    if (f.open_failure) { errno = EACCES; return -1; }
    int fd = open(path, flags); assert(fd >= 0); return fd;
}
static int host_close(int fd) { ++f.closed; return close(fd); }
static int host_dladdr(void *address, Dl_info *out) {
    assert((uintptr_t)address == f.origin.request.callback);
    *out = (Dl_info){.dli_fbase = (void *)(appfw_base + (f.fault == CALLBACK_BASE)),
        .dli_fname = f.fault == CALLBACK_MODULE ? "/evilappFw.so" : "/appFw.so"};
    return f.fault != CALLBACK_DLADDR;
}
static long host_pread(int fd, void *out, size_t bytes, long offset) {
    uintptr_t address = (uintptr_t)offset;
    if (address == f.origin.request.callback && bytes == 8) {
        unsigned int nth = ++f.callback_code_reads;
        put(out, UINT64_C(0x910003fda9b97bfd), 8);
        if (f.fault == CALLBACK_CODE || (f.fault == CALLBACK_CODE_DRIFT && nth == 2)) ((unsigned char *)out)[0] ^= 1;
        return f.fault == CALLBACK_CODE_SHORT ? 7 : 8;
    }
    assert((address == f.origin.frame + 0x68 && bytes == 8) ||
        (address == f.origin.frame + 0x70 && bytes == 8) || (address == f.origin.frame + 0x60 && bytes == 4));
    long n = (long)pread(fd, out, bytes, (off_t)offset);
    if (bytes == 4) {
        unsigned int nth = ++f.callback_context_reads;
        if (f.fault == CALLBACK_CONTEXT || (f.fault == CALLBACK_CONTEXT_DRIFT && nth == 2)) ((unsigned char *)out)[0] ^= 1;
        if (f.fault == CALLBACK_CONTEXT_SHORT) return 3;
    }
    return n;
}
static void host_record(const char *prefix, const char *text) {
    assert(strstr(text, "capture_verified=0"));
    if (!strcmp(prefix, "FUNCTIONAL_FACE_SOURCE_RETAINED_FAULT ")) ++f.retained_records;
    else if (!strcmp(prefix, "FUNCTIONAL_FACE_SOURCE_SNAPSHOT_RESULT ")) ++f.result_records;
    else if (!strcmp(prefix, "FUNCTIONAL_FACE_SOURCE_CALLBACK_ENTER ")) ++f.enter_records;
    else { assert(!strcmp(prefix, "FUNCTIONAL_FACE_SOURCE_CALLBACK_RETURN ")); ++f.return_records; }
    printf("%s%s\n", prefix, text);
}
static int host_usleep(unsigned int usec) {
    struct functional_face_source_transaction *s = transaction();
    assert(usec == 10000 && ++f.sleeps == 1 && f.retained_records == 1 && f.result_records == 1);
    assert(s->initialized && s->sdk.initialized && s->source.initialized && s->sdk.last.pending_fault);
    assert(s->reader.fd >= 0 && f.opened == 1 && !f.closed && !f.callbacks && !s->callback_invoked && !s->callback_returned);
    struct functional_face_sdk_origin expected_origin = f.origin;
    if (f.fault == CALLBACK_EXTENT) ++expected_origin.request.callback_context;
    assert(!memcmp(&s->origin, &expected_origin, sizeof expected_origin));
    assert(s->source.config.frame == f.origin.frame && s->source.config.api_pointer == f.origin.input_pointer);
    assert(s->source.config.saved_source.epoch == f.birthday.allocation_token);
    assert(s->source.config.original_command == functional_face_native_ap_command &&
        s->source.config.read_current_metadata == functional_face_source_current_metadata);
    assert(s->sdk.binding.provider.context == &s->source && s->sdk.binding.callback_context == s);
    assert(s->sdk.binding.reader_context == &s->reader && s->sdk.last.claimed && s->sdk.last.started);
    assert(!s->source.original_global_writer_verified && !s->source.kernel_atomic_snapshot_verified && !s->source.physical_asic_verified);
    assert(f.result_pointer && *f.result_pointer == 0x6137 && !legacy_sdk_calls && !original_sender_calls);
    assert_frame();
    longjmp(retained_jump, 1);
}

static void observe(unsigned int op, unsigned int unit, unsigned int handle, int status,
    struct functional_face_ap_observer *out) {
    unsigned char q[40] = {0}, r[40] = {0};
    put(q, op, 2); if (op == 0x20 || op == 0x21) put(q + 4, unit, 4);
    if (op != 0x20) put(q + 8, handle, 4);
    if (op == 0x20 || op == 0x24) put(q + 12, UINT32_MAX, 4);
    if (op == 0x23) put(q + 20, QUEUE & 0xffffu, 2);
    put(r, op | 0x8000u, 2); put(r + 2, (uint16_t)status, 2); put(r + 12, handle, 4);
    if (op == 0x24 && !status) {
        put(r + 8, 1, 2); put(r + 24, f.current.address, 8); put(r + 32, f.current.bytes, 4);
    }
    int64_t tid = syscall(SYS_gettid);
    assert(functional_face_ap_begin(&functional_face_ap_state, 1, 1, tid, FUNCTIONAL_FACE_AP_DMM, QUEUE, q, 40, NULL) == 1);
    functional_face_ap_sent(&functional_face_ap_state, tid, 0, NULL);
    functional_face_ap_received(&functional_face_ap_state, tid, QUEUE, FUNCTIONAL_FACE_AP_DMM, r, 40, 0, NULL);
    functional_face_ap_freed(&functional_face_ap_state, tid, QUEUE, r, 0, NULL);
    if (out) *out = functional_face_ap_state;
}
static int functional_face_native_ap_command(void *context, unsigned int op, unsigned int unit, unsigned int handle,
    struct functional_face_ap_observer *out) {
    assert(!context && out && unit == f.origin.unit && handle == f.origin.birth.handle);
    unsigned int index = op == 0x21 ? 0 : op == 0x24 ? 1 : op == 0x25 ? 2 : 3;
    assert(op == command_order[index] && !f.commands[index] && f.command_count < 4);
    ++f.commands[index]; f.command_trace[f.command_count++] = op;
    int status = ((f.fault == NATIVE_SHARE && op == 0x21) || (f.fault == NATIVE_OPEN && op == 0x24) ||
        (f.fault == CLEANUP_CLOSE && op == 0x25) || (f.fault == CLEANUP_FREE && op == 0x23)) ? -7 : 0;
    if (!status) {
        if (op == 0x21) ++f.owners;
        if (op == 0x24) ++f.opens;
        if (op == 0x25) { assert(f.opens > f.baseline); --f.opens; }
        if (op == 0x23) { assert(f.owners == 2); --f.owners; }
    }
    f.current.owners = f.owners; f.current.opens = f.opens; f.current.state = f.opens ? 2 : 1;
    observe(op, unit, handle, status, out); return 0;
}
static int functional_face_source_current_metadata(void *context, unsigned int unit, unsigned int handle,
    struct functional_face_proc_unit *out) {
    assert(!context && unit == f.origin.unit && handle == f.origin.birth.handle && out);
    assert(transaction()->source.metadata_calls == ++f.metadata_calls);
    *out = f.current;
    /* The current row is independent mutable state, never rebuilt from born. */
    if (f.fault == METADATA_DRIFT && f.metadata_calls == 3) ++out->extent_id;
    if (f.metadata_calls == 6) {
        if (f.fault == CALLBACK_PID) ++transaction()->source.config.owner_pid;
        if (f.fault == CALLBACK_TID) ++transaction()->source.config.owner_tid;
        if (f.fault == CALLBACK_EXTENT) ++transaction()->origin.request.callback_context;
    }
    return 0;
}
static long host_pagemap(void *context, uintptr_t page, uint64_t *out) {
    assert(context == &f); ++f.pagemap_reads;
    uintptr_t cp = f.origin.destination.host_view, sdk = f.origin.frame & ~(uintptr_t)4095;
    uint64_t physical;
    if (page >= cp && page < cp + f.origin.destination.mapped_bytes)
        physical = UINT64_C(0x420000000) + ((page - cp) / 4096) * 8192;
    else { assert(page >= sdk && page < sdk + 8192); physical = UINT64_C(0x430000000) + ((page - sdk) / 4096) * 8192; }
    *out = (UINT64_C(1) << 63) | (physical / 4096); return 8;
}
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *p, size_t bytes,
    void *out, size_t capacity, struct fcam_bridge_result *result) {
    (void)origin; (void)op; (void)p; (void)bytes; (void)out; (void)capacity; (void)result; abort();
}
static int host_bridge(void *context, const struct fcam_native_origin *origin, uint32_t op, const void *packet,
    size_t bytes, void *out, size_t capacity, struct fcam_bridge_result *result) {
    const unsigned char *p = packet; struct functional_face_source_snapshot *s = &transaction()->source;
    assert(context == &f && op == FCAM_OP_AP_SOURCE_SNAPSHOT && ++f.bridge_calls == 1);
    assert(f.owners == 2 && f.opens == f.baseline + 1 && f.metadata_calls == 3);
    assert(origin->source == f.origin.birth.handle && origin->destination == f.origin.destination.handle &&
        origin->command == FCAM_FACE_SNAPSHOT_COMMAND && origin->bytes == 40 && origin->wire_fnv1a64 == hash(f.origin.api40, 40));
    assert(get(p + 4, 4) == f.origin.unit && get(p + 8, 4) == origin->source && get(p + 12, 4) == origin->destination);
    assert(get(p + 32, 8) == f.birthday.allocation_token && get(p + 32, 8) != f.origin.birth.observation_sequence);
    assert(get(p + 40, 8) == f.origin.destination.epoch && get(p + 48, 8) == f.origin.destination.registration);
    assert(get(p + 56, 8) == OWNER && get(p + 64, 8) == f.current.address && get(p + 80, 8) == f.origin.birth.observation_sequence);
    assert(get(p + 88, 8) == s->operations[0].sequence && get(p + 96, 8) == s->operations[1].sequence);
    assert(get(p + 104, 4) == f.birthday.row.relation && get(p + 108, 4) == f.birthday.row.generation && get(p + 112, 4) == f.birthday.row.extent_id);
    assert(get(p + 116, 4) == (uint32_t)getpid() && get(p + 120, 4) == (uint32_t)syscall(SYS_gettid));
    assert(get(p + 288, 8) == f.origin.frame && get(p + 296, 8) == f.origin.input_pointer);
    assert(!memcmp(p + 304, f.origin.api40, 40) && !memcmp(p + 344, f.origin.source_descriptor, 8) && !memcmp(p + 352, f.origin.destination_descriptor, 8));
    assert(bytes == 360 + 8u * (s->cp_count + s->sdk_count) && capacity == f.origin.request.input.bytes);
    assert(out == s->owned_snapshot && out != f.source && out != f.expected && out != (void *)f.origin.destination.host_view);
    if (f.fault == BRIDGE_FAIL) return -EBADMSG;
    memcpy(out, f.source, capacity); f.snapshot_bytes += capacity;
    assert(!memcmp(out, f.expected, capacity));
    /* Prove transfer consumes the snapshot even after its original source changes. */
    memset(f.source, 0x5a, capacity);
    *result = (struct fcam_bridge_result){capacity, capacity, UINT64_C(0x1234567788), UINT64_C(0x7a0000) + f.origin.unit};
    return 0;
}
static int host_snapshot_init(struct functional_face_source_snapshot *out,
    const struct functional_face_source_snapshot_config *cfg, struct functional_face_ap_provider *provider) {
    ++f.init_calls;
    assert(cfg->saved_source.domain == 0 && cfg->saved_source.unit == f.origin.unit && cfg->saved_source.handle == f.origin.birth.handle);
    assert(cfg->saved_source.epoch == f.origin.allocation_token && cfg->saved_source.owner == (unsigned int)getpid() &&
        cfg->saved_source.bytes == f.origin.request.input.bytes);
    assert(!memcmp(&cfg->birth, &f.origin.birth, sizeof cfg->birth) && cfg->observer == &functional_face_ap_state);
    assert(cfg->relation == f.birthday.row.relation && cfg->generation == f.birthday.row.generation && cfg->extent_id == f.birthday.row.extent_id);
    assert(!memcmp(&cfg->born, &f.birthday.row, sizeof cfg->born));
    assert(!memcmp(&cfg->destination, &f.origin.destination, sizeof cfg->destination) && cfg->producer_owner == OWNER);
    assert(cfg->owner_pid == getpid() && cfg->owner_tid == syscall(SYS_gettid));
    assert(cfg->frame == f.origin.frame && cfg->api_pointer == f.origin.input_pointer && cfg->original_caller_verified == 1);
    assert(!memcmp(cfg->raw_api40, f.origin.api40, 40) && !memcmp(cfg->ap_descriptor, f.origin.source_descriptor, 8) &&
        !memcmp(cfg->cp_descriptor, f.origin.destination_descriptor, 8));
    assert(cfg->original_command == functional_face_native_ap_command && !cfg->command_context &&
        cfg->read_current_metadata == functional_face_source_current_metadata && !cfg->metadata_context);
    assert(!cfg->read_pagemap && !cfg->bridge_call && !cfg->test_context);
    struct functional_face_source_snapshot_config injected = *cfg;
    injected.read_pagemap = host_pagemap; injected.bridge_call = host_bridge; injected.test_context = &f;
    f.init_result = functional_face_source_snapshot_init(out, &injected, provider);
    return f.init_result;
}
static void independent_read(void) {
    struct functional_face_dmm_borrow borrow; struct functional_face_dmm_readback rb;
    struct functional_face_dmm_descriptor *d = &f.origin.destination;
    unsigned char *actual = malloc(d->bytes); assert(actual);
    assert(!functional_face_runtime_borrow_destination(OWNER, d->unit, d->handle, d, 0, d->bytes, FUNCTIONAL_FACE_DMM_READ, &borrow));
    assert(!functional_face_dmm_read(&borrow, 0, actual, d->bytes, &rb));
    assert(rb.verified_bytes == d->bytes && !memcmp(actual, f.expected, d->bytes));
    assert(!functional_face_dmm_release_borrow(&borrow, &rb)); f.independent_bytes += d->bytes; free(actual);
}
static void host_callback(int32_t status, void *context) {
    struct functional_face_source_transaction *s = transaction();
    assert(!status && (uintptr_t)context == f.origin.frame + 0x60 && get(context, 4) == f.origin.birth.handle);
    assert(s->callback_invoked && !s->callback_returned && !f.callbacks && f.enter_records == 1 && !f.return_records);
    assert(f.owners == 1 && f.opens == f.baseline && !s->source.owner_live && !s->source.open_live &&
        !s->source.snapshot_live && !s->source.owned_snapshot && !s->source.provider_may_retain);
    assert(s->sdk.last.copy.content_complete && s->sdk.last.copy.written == f.origin.destination.bytes &&
        s->sdk.last.copy.readback == f.origin.destination.bytes && !s->sdk.last.copy.source_release_result &&
        !s->sdk.last.copy.destination_release_result && !s->sdk.transfer.source_live && !s->sdk.transfer.destination_live);
    assert(s->sdk.last.saved_source.epoch == f.birthday.allocation_token && f.metadata_calls == 6 && f.command_count == 4);
    for (unsigned int i = 0; i < 4; ++i)
        assert(f.commands[i] == 1 && f.command_trace[i] == command_order[i] && s->source.operations[i].op == command_order[i]);
    struct functional_face_dmm_snapshot cp; assert(!functional_face_dmm_snapshot(&cp));
    assert(!cp.units[f.origin.unit - 0x1d9].borrows && !cp.units[f.origin.unit - 0x1d9].transfers);
    independent_read(); assert_frame(); ++f.callbacks;
}
static void setup_fixture(unsigned int index, unsigned int baseline, enum fault fault) {
    memset(&f, 0, sizeof f); f.baseline = baseline; f.owners = 1; f.opens = baseline; f.fault = fault;
    memset(&functional_face_ap_state, 0, sizeof functional_face_ap_state);
    f.origin.unit = 0x1d9 + index;
    assert(!functional_face_runtime_lookup_creator(OWNER, f.origin.unit, &f.origin.destination));
    assert(!transaction()->initialized);
    f.mapping = mmap(NULL, 8192, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0); assert(f.mapping != MAP_FAILED);
    f.origin.frame = (uintptr_t)f.mapping + (index == 1 ? 16 : 0xfc0); f.origin.input_pointer = f.origin.frame + 0xb8;
    f.source = malloc(lengths[index]); f.expected = malloc(lengths[index]); assert(f.source && f.expected);
    for (size_t i = 0; i < lengths[index]; ++i) f.source[i] = (unsigned char)((i * 37 + index * 53 + 11) ^ (i >> 7));
    memcpy(f.expected, f.source, lengths[index]);
    uintptr_t callback = (uintptr_t)&host_callback; assert(callback > CALLBACK_OFFSET); appfw_base = callback - CALLBACK_OFFSET; real_dladdr = host_dladdr;
    unsigned int handle = 0x92a + index;
    f.current = (struct functional_face_proc_unit){.handle = handle, .unit = f.origin.unit, .state = baseline ? 2 : 1,
        .owners = 1, .opens = baseline, .generation = handle >> 10, .relation = 0x123, .extent_id = 0x456, .segments = 1,
        .address = UINT64_C(0x410300000) + index * UINT64_C(0x100000), .bytes = lengths[index], .row_offset = 128, .row_bytes = 138};
    observe(0x20, f.origin.unit, handle, 0, NULL);
    assert(!functional_face_ap_observed_birth(&functional_face_ap_state, syscall(SYS_gettid), f.origin.unit, handle, &f.origin.birth));
    f.birthday = (struct functional_face_native_proc_birth){.owner_pid = getpid(), .owner_tid = syscall(SYS_gettid),
        .observation = f.origin.birth.observation_sequence, .allocation_token = UINT64_C(0xface000000000031) + index,
        .attempted = 1, .row = f.current};
    f.birthday.row.state = 1; f.birthday.row.opens = 0;
    functional_face_native_proc_births[index] = f.birthday;
    f.origin.allocation_token = f.birthday.allocation_token; f.origin.native_metadata_observed = 1;
    put(f.origin.api40, f.origin.frame + 0x68, 8); put(f.origin.api40 + 8, f.origin.frame + 0x70, 8);
    put(f.origin.api40 + 16, lengths[index], 4); put(f.origin.api40 + 20, 1, 4); put(f.origin.api40 + 24, callback, 8); put(f.origin.api40 + 32, f.origin.frame + 0x60, 8);
    put(f.origin.source_descriptor, handle, 4); put(f.origin.destination_descriptor, f.origin.destination.handle, 4);
    put((void *)(f.origin.frame + 0x60), handle, 4);
    memcpy((void *)(f.origin.frame + 0x68), f.origin.source_descriptor, 8);
    memcpy((void *)(f.origin.frame + 0x70), f.origin.destination_descriptor, 8);
    memcpy((void *)f.origin.input_pointer, f.origin.api40, 40);
    struct functional_face_sdk_frame_reader reader = {open("/proc/self/mem", O_RDONLY), f.origin.frame}; assert(reader.fd >= 0);
    assert(!functional_face_transfer_decode_api40(f.origin.api40, 40, functional_face_sdk_frame_read, &reader, &f.origin.request)); assert(!close(reader.fd));
    memcpy(f.frame_before, (void *)f.origin.frame, sizeof f.frame_before);
    f.origin_before = f.origin; memcpy(f.birthdays_before, functional_face_native_proc_births, sizeof f.birthdays_before);
}
static void destroy_fixture(void) {
    struct functional_face_source_transaction *s = transaction();
    /* HOST teardown only, after sticky-retention assertions; no production retry. */
    if (s->reader.fd >= 0 && s->initialized) assert(!close(s->reader.fd));
    free(s->source.owned_snapshot); *s = (struct functional_face_source_transaction){0};
    free(f.source); free(f.expected); assert(!munmap(f.mapping, 8192));
}
static void success(unsigned int index, unsigned int baseline) {
    setup_fixture(index, baseline, OK); int result = 0x6137;
    assert(functional_face_try_source_snapshot(&f.origin, &result) == 1 && !result);
    struct functional_face_source_transaction *s = transaction();
    assert(f.callbacks == 1 && s->callback_invoked && s->callback_returned && f.enter_records == 1 && f.return_records == 1);
    assert(f.init_calls == 1 && !f.init_result && f.opened == 1 && f.closed == 1 && s->reader.fd == -1);
    assert(f.callback_code_reads == 2 && f.callback_context_reads == 2);
    assert(f.snapshot_bytes == lengths[index] && f.independent_bytes == lengths[index] && !f.retained_records);
    assert(s->source.cp_count == (f.origin.destination.mapped_bytes / 4096) && s->source.sdk_count == (index == 1 ? 1u : 2u));
    assert(!s->source.original_global_writer_verified && !s->source.kernel_atomic_snapshot_verified && !s->source.physical_asic_verified);
    struct functional_face_source_transaction saved = *s; result = 0x6137;
    assert(!functional_face_try_source_snapshot(&f.origin, &result) && result == 0x6137 && !memcmp(&saved, s, sizeof saved));
    assert(f.init_calls == 1 && f.opened == 1 && f.command_count == 4 && !legacy_sdk_calls && !original_sender_calls);
    assert_frame();
    printf("MAIN_HOST_BYTES unit=%x bytes=%zu digest=%016" PRIx64 " cp_pages=%u sdk_pages=%u metadata=6 commands=21,24,25,23 baseline_opens=%u original_owner=1\n",
        f.origin.unit, lengths[index], hash(f.expected, lengths[index]), s->source.cp_count, s->source.sdk_count, baseline);
    destroy_fixture();
}
static void preflight(void) {
    for (unsigned int k = 0; k < 23; ++k) {
        setup_fixture(1, 0, OK);
        if (k == 0) functional_camera_enabled = 0;
        if (k == 1) f.origin.native_metadata_observed = 0;
        if (k == 2) f.origin.allocation_token = 0;
        if (k == 3) ++functional_face_native_proc_births[1].owner_pid;
        if (k == 4) ++functional_face_native_proc_births[1].owner_tid;
        if (k == 5) ++functional_face_native_proc_births[1].observation;
        if (k == 6) ++functional_face_native_proc_births[1].allocation_token;
        if (k == 7) functional_face_native_proc_births[1].error = -ESTALE;
        if (k == 8) ++f.origin.destination.handle;
        if (k == 9) ++f.origin.destination.host_view;
        if (k == 10) --f.origin.destination.mapped_bytes;
        if (k == 11) ++functional_face_native_proc_births[1].row.owners;
        if (k == 12) ++functional_face_native_proc_births[1].row.segments;
        if (k == 13) f.origin.source_descriptor[4] = 1;
        if (k == 14) f.origin.destination_descriptor[4] = 1;
        if (k == 15) f.origin.api40[20] = 0;
        if (k == 16) ++f.origin.api40[32];
        if (k == 17) ++f.origin.input_pointer;
        if (k == 18) f.origin.birth.ambiguous = 1;
        if (k == 19) f.origin.birth.any_free_observed = 1;
        if (k == 20) f.open_failure = 1;
        f.birthday = functional_face_native_proc_births[1];
        f.origin_before = f.origin; memcpy(f.birthdays_before, functional_face_native_proc_births, sizeof f.birthdays_before);
        struct functional_face_sdk_origin origin = f.origin; int result = 0x6137;
        assert(!functional_face_try_source_snapshot(k == 21 ? NULL : &f.origin, k == 22 ? NULL : &result));
        assert(result == 0x6137 && !memcmp(&origin, &f.origin, sizeof origin));
        assert(!transaction()->initialized && !f.callbacks && !f.command_count && !f.bridge_calls && !f.metadata_calls && !f.pagemap_reads);
        assert(f.closed == f.opened - (unsigned int)f.open_failure);
        assert_frame(); functional_camera_enabled = 1; destroy_fixture();
    }
    puts("MAIN_PREFLIGHT cases=23 unclaimed=1 output_unchanged=1 birthday_unchanged=1");
}
static void retained(enum fault fault) {
    setup_fixture(1, 1, fault);
    int result = 0x6137; f.result_pointer = &result;
    if (!setjmp(retained_jump)) { (void)functional_face_try_source_snapshot(&f.origin, &result); assert(!"retained Main returned"); }
    struct functional_face_source_transaction *s = transaction();
    assert(result == 0x6137 && f.sleeps == 1 && !f.callbacks && !s->callback_invoked && !s->callback_returned);
    if (fault == CALLBACK_EXTENT) { --s->origin.request.callback_context; }
    unsigned int commands = f.command_count, bridge = f.bridge_calls, metadata = f.metadata_calls;
    struct functional_face_source_transaction saved = *s;
    assert(!functional_face_try_source_snapshot(&f.origin, &result) && result == 0x6137);
    assert(commands == f.command_count && bridge == f.bridge_calls && metadata == f.metadata_calls && !memcmp(&saved, s, sizeof saved));
    if (fault == BRIDGE_FAIL) assert(s->source.owned_snapshot && s->source.owner_live && s->source.open_live && s->source.provider_may_retain);
    if (fault == METADATA_DRIFT) assert(s->source.metadata_calls == 3 && !f.bridge_calls && s->source.provider_may_retain);
    if (fault == NATIVE_SHARE) assert((int16_t)get(s->source.operations[0].reply_wire + 2, 2) == -7 && commands == 1);
    if (fault == NATIVE_OPEN) assert((int16_t)get(s->source.operations[1].reply_wire + 2, 2) == -7 && commands == 3 && f.owners == 1 && f.opens == 1);
    if (fault == CLEANUP_CLOSE) assert(s->source.owned_snapshot && s->source.open_live && f.commands[2] == 1 && !f.commands[3]);
    if (fault == CLEANUP_FREE) assert(s->source.owned_snapshot && !s->source.open_live && s->source.owner_live && f.commands[3] == 1);
    if (fault >= CALLBACK_PID) assert(s->sdk.last.copy.content_complete && f.metadata_calls == 6 && !s->source.owned_snapshot && f.owners == 1 && f.opens == 1);
    assert_frame();
    printf("MAIN_RETAINED fault=%u first_sleep=1 result_unchanged=1 original_frame_alive=1 context_retained=1 callback=0 retry_commands=0 native_verified=0\n", fault);
    destroy_fixture();
}
int main(int argc, char **argv) {
    assert(argc == 2); assert(!functional_face_runtime_prepare(1, OWNER, &io, NULL));
    const char *mode = argv[1]; unsigned int all = !strcmp(mode, "three-units");
    for (unsigned int i = 0; i < 3; ++i) if (all || i == 1) cp_operation(0x20, 0x1d9 + i, 0);
    if (all) {
        struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
        speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
        unsigned char q[40] = {0}, r[40]; put(q, 0x20, 2); put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
        for (unsigned int i = 0; i < 2; ++i) {
            assert(!dmm_service_reply(&speech, q, 40, r));
            speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
            assert(speech.slots[i].handle == 0x8400u + i && speech.slots[i].open_count == 1);
        }
        for (size_t i = 0; i < DMM_TEST_SIZE; ++i) speech.memory[i] = (unsigned char)(i ^ (i >> 9) ^ 0x95);
        struct dmm_service saved_speech = speech;
        unsigned char *saved_bytes = malloc(DMM_TEST_SIZE); assert(saved_bytes); memcpy(saved_bytes, speech.memory, DMM_TEST_SIZE);
        for (unsigned int i = 0; i < 3; ++i) success(i, 0);
        assert(!memcmp(&speech, &saved_speech, sizeof speech) && !memcmp(speech.memory, saved_bytes, DMM_TEST_SIZE));
        free(saved_bytes); free(speech.memory);
        puts("MAIN_HOST_COUNTS units=3 snapshot=514304 cp_write=514304 cp_readback=514304 independent_read=514304 callbacks=3 speech_bytes=1048576 speech_unchanged=1");
    } else if (!strcmp(mode, "baseline")) success(1, 1);
    else if (!strcmp(mode, "preflight")) preflight();
    else {
        static const char *names[] = {"ok", "bridge", "metadata", "native-share", "native-open", "cleanup-close", "cleanup-free",
            "callback-pid", "callback-tid", "callback-code", "callback-code-short", "callback-code-drift", "callback-context",
            "callback-context-short", "callback-context-drift", "callback-extent", "callback-base", "callback-module", "callback-dladdr"};
        unsigned int i = 1; while (i < sizeof names / sizeof *names && strcmp(mode, names[i])) ++i;
        assert(i < sizeof names / sizeof *names); retained((enum fault)i);
    }
    for (unsigned int i = 0; i < 3; ++i) if (all || i == 1) {
        struct functional_face_dmm_descriptor d; assert(!functional_face_runtime_lookup_creator(OWNER, 0x1d9 + i, &d));
        cp_operation(0x23, d.unit, d.handle);
    }
    assert(!functional_face_dmm_shutdown());
    printf("FACE_SOURCE_MAIN_HOST_PASS mode=%s actual_main=1 actual_sdk=1 actual_cp=1 host_only=1 native_verified=0 capture_verified=0 physical_verified=0\n", mode);
    return 0;
}
