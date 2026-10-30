/* SPDX-License-Identifier: MIT */
#include "functional-face-ap-observer.h"
#include "functional-face-proc.h"

#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define RAW_CAPACITY ((size_t)2 * 1024 * 1024)
#define TID INT64_C(17)
#define QUEUE UINT32_C(0x00610041)
#define SAVED_ERRNO EILSEQ

static int functional_camera_enabled = 1;
static _Thread_local struct functional_face_ap_observer functional_face_ap_state;

enum io_mode { IO_NORMAL, IO_OPEN_ERROR, IO_READ_ERROR, IO_OVERSIZE,
               IO_NO_EOF, IO_CAPACITY, IO_CLOSE_ERROR };
struct document { char text[8192]; size_t bytes; };
struct io_plan {
    struct document doc;
    enum io_mode mode;
    unsigned reads, close_error;
    size_t cursor, chunk;
};
struct log_line { char prefix[80], text[1024]; };
static struct io_plan plans[2];
static struct log_line logs[128];
static unsigned log_count, opens, reads, closes, allocations, deallocations;
static unsigned events[6], collect_on_free;
static unsigned char request_wire[40], reply_wire[40];
static const unsigned sizes[] = {0x64000, 0xc800, 0xd100, 0xe220};
static unsigned subcases;

static void append(struct document *d, const char *format, ...)
{
    va_list args;
    int n;
    va_start(args, format);
    n = vsnprintf(d->text + d->bytes, sizeof(d->text) - d->bytes, format, args);
    va_end(args);
    assert(n >= 0 && (size_t)n < sizeof(d->text) - d->bytes);
    d->bytes += (size_t)n;
}

/* Header, 138 dashes and column widths copied from the real parser's fixture. */
static void start(struct document *d)
{
    unsigned i;
    d->bytes = 0;
    append(d, "Information on Units.\n");
    append(d, "handle   type      status  alloc  open  rdv  serial  relation   "
              "address    size      extent\n");
    for (i = 0; i < 138; ++i)
        append(d, "-");
    append(d, "\n");
}

static void row(struct document *d, unsigned handle, unsigned unit,
                unsigned state, unsigned owners, unsigned open_count,
                unsigned shares, unsigned generation, unsigned relation,
                unsigned long long address, unsigned bytes, unsigned id)
{
    append(d, "%04x     %08x  %04x    %02x     %02x    %02x    %02x      "
              "%08x  %09llx  %08x  %04x\n", handle, unit, state, owners,
           open_count, shares, generation, relation, address, bytes, id);
}

static void normal(struct document *d, unsigned index)
{
    start(d);
    row(d, 0x42d + index, 0x1d9 + index, 1, 1, 0, 0, 1,
        0x89abcdef + index, 0x100004000ULL + index * 0x100000ULL,
        sizes[index], 0xf1 + index);
}

static int host_open(const char *path, int flags, ...)
{
    unsigned pass = opens++;
    assert(strcmp(path, "/proc/udm/dmm_units") == 0 && flags == 0);
    assert(pass < 2);
    if (plans[pass].mode == IO_OPEN_ERROR) {
        errno = EACCES;
        return -1;
    }
    errno = EOVERFLOW;
    return 100 + (int)pass;
}

static long host_read(int fd, void *buffer, size_t capacity)
{
    struct io_plan *p;
    size_t n;
    assert(fd >= 100 && fd < 102 && capacity > 0 && capacity <= RAW_CAPACITY);
    p = &plans[(unsigned)(fd - 100)];
    ++reads;
    ++p->reads;
    errno = EOVERFLOW;
    if (p->mode == IO_READ_ERROR) {
        errno = EIO;
        return -1;
    }
    if (p->mode == IO_OVERSIZE)
        return (long)capacity + 1;
    if (p->mode == IO_CAPACITY) {
        assert(p->reads == 1 && capacity == RAW_CAPACITY);
        memset(buffer, '\n', capacity);
        memcpy(buffer, p->doc.text, p->doc.bytes);
        return (long)capacity;
    }
    if (p->cursor == p->doc.bytes) {
        if (p->mode == IO_NO_EOF) {
            *(unsigned char *)buffer = '\n';
            return 1;
        }
        return 0;
    }
    n = p->doc.bytes - p->cursor;
    if (p->chunk && n > p->chunk)
        n = p->chunk;
    assert(n <= capacity);
    memcpy(buffer, p->doc.text + p->cursor, n);
    p->cursor += n;
    return (long)n;
}

static int host_close(int fd)
{
    assert(fd >= 100 && fd < 102);
    ++closes;
    errno = EOVERFLOW;
    if (plans[(unsigned)(fd - 100)].mode == IO_CLOSE_ERROR ||
        plans[(unsigned)(fd - 100)].close_error) {
        errno = EBADF;
        return -1;
    }
    return 0;
}

static long host_syscall(long number, ...)
{
    assert(number == 178);
    return (long)TID;
}

static void *counted_malloc(size_t n)
{
    void *p;
    assert(n == RAW_CAPACITY);
    p = malloc(n);
    assert(p != NULL);
    ++allocations;
    errno = EOVERFLOW;
    return p;
}

static void counted_free(void *p)
{
    assert(p != NULL && deallocations < allocations);
    ++deallocations;
    free(p);
    errno = EINTR;
}

static void record(const char *prefix, const char *text)
{
    int n;
    assert(log_count < sizeof(logs) / sizeof(logs[0]));
    n = snprintf(logs[log_count].prefix, sizeof(logs[log_count].prefix), "%s", prefix);
    assert(n >= 0 && (size_t)n < sizeof(logs[log_count].prefix));
    n = snprintf(logs[log_count].text, sizeof(logs[log_count].text), "%s", text);
    assert(n >= 0 && (size_t)n < sizeof(logs[log_count].text));
    ++log_count;
    errno = ENOTTY;
}

#define open host_open
#define read host_read
#define close host_close
#define syscall host_syscall
#define malloc counted_malloc
#define free counted_free
/* ACTUAL_PROC_BIRTH */
#undef open
#undef read
#undef close
#undef syscall
#undef malloc
#undef free

static void event_record(enum functional_face_ap_event event,
                         const struct functional_face_ap_observer *s)
{
    assert(event >= FACE_AP_SUBMIT && event <= FACE_AP_RETAINED);
    ++events[event];
    if (collect_on_free && event == FACE_AP_FREE_RETURN)
        functional_face_native_birth_observe(s);
}

static void put32(unsigned char *p, uint32_t value)
{
    unsigned i;
    for (i = 0; i < 4; ++i)
        p[i] = (unsigned char)(value >> (8 * i));
}

static void reset(unsigned index)
{
    unsigned pass;
    functional_face_ap_state = (struct functional_face_ap_observer){0};
    memset(functional_face_native_proc_births, 0, sizeof(functional_face_native_proc_births));
    functional_face_native_proc_busy = 0;
    functional_face_native_allocation_serial = 0;
    functional_camera_enabled = 1;
    collect_on_free = 1;
    memset(plans, 0, sizeof(plans));
    memset(events, 0, sizeof(events));
    memset(logs, 0, sizeof(logs));
    log_count = opens = reads = closes = allocations = deallocations = 0;
    for (pass = 0; pass < 2; ++pass)
        normal(&plans[pass].doc, index);
    errno = SAVED_ERRNO;
}

static void begin(unsigned index, unsigned op)
{
    memset(request_wire, 0, sizeof(request_wire));
    memset(reply_wire, 0xa5, sizeof(reply_wire));
    put32(request_wire, op);
    put32(request_wire + 4, 0x1d9 + index);
    put32(request_wire + 8, op == 0x20 ? 0 : 0x42d + index);
    put32(reply_wire, op | 0x8000u);
    put32(reply_wire + 12, 0x42d + index);
    assert(functional_face_ap_begin(&functional_face_ap_state, 1, 1, TID,
                                   FUNCTIONAL_FACE_AP_DMM, QUEUE, request_wire,
                                   sizeof(request_wire), event_record) == 1);
}

static void receive_and_free(uint32_t source, unsigned status, int free_result)
{
    reply_wire[2] = (unsigned char)status;
    reply_wire[3] = (unsigned char)(status >> 8);
    functional_face_ap_sent(&functional_face_ap_state, TID, 0, event_record);
    functional_face_ap_received(&functional_face_ap_state, TID, QUEUE, source,
                                reply_wire, sizeof(reply_wire), 0, event_record);
    functional_face_ap_freed(&functional_face_ap_state, TID, QUEUE, reply_wire,
                             free_result, event_record);
}

static void birth(unsigned index)
{
    begin(index, 0x20);
    receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
}

static void observe(void)
{
    errno = SAVED_ERRNO;
    functional_face_native_birth_observe(&functional_face_ap_state);
    assert(errno == SAVED_ERRNO);
}

static struct functional_face_native_proc_birth *saved(unsigned index)
{
    return &functional_face_native_proc_births[index];
}

static void no_io(unsigned index)
{
    assert(opens == 0 && reads == 0 && closes == 0 && allocations == 0);
    assert(deallocations == 0 && log_count == 0);
    assert(!saved(index)->attempted && saved(index)->row.handle == 0);
    assert(errno == SAVED_ERRNO);
    ++subcases;
}

static void failed(unsigned index, int expected, unsigned attempts)
{
    struct functional_face_native_proc_birth *b = saved(index);
    assert(b->attempted == 1 && b->error == expected && !b->allocation_token);
    assert(b->owner_pid == getpid() && b->owner_tid == TID);
    assert(b->observation == functional_face_ap_state.sequence);
    assert(b->row.handle == 0 && b->row.address == 0 && b->row.bytes == 0);
    assert(opens == attempts && allocations == attempts && deallocations == attempts);
    assert(functional_face_native_proc_busy == 0 && errno == SAVED_ERRNO);
    ++subcases;
}

static void success(unsigned index)
{
    const struct functional_face_native_proc_birth *b = saved(index);
    const struct functional_face_proc_unit *r = &b->row;
    assert(b->attempted == 1 && b->error == 0);
    assert((b->allocation_token >> 48) == UINT64_C(0xface) &&
           (b->allocation_token & UINT64_C(0x0000ffffffffffff)) == functional_face_native_allocation_serial &&
           b->allocation_token != b->observation);
    assert(b->owner_pid == getpid() && b->owner_tid == TID && b->observation == 1);
    assert(r->handle == 0x42d + index && r->unit == 0x1d9 + index);
    assert(r->state == 1 && r->owners == 1 && r->opens == 0 && r->shares == 0);
    assert(r->generation == 1 && r->relation == 0x89abcdef + index);
    assert(r->address == 0x100004000ULL + index * 0x100000ULL);
    assert(r->bytes == sizes[index] && r->extent_id == 0xf1 + index && r->segments == 1);
    assert(opens == 2 && closes == 2 && allocations == 2 && deallocations == 2);
    assert(functional_face_native_proc_busy == 0 && errno == SAVED_ERRNO);
    assert(events[FACE_AP_SUBMIT] == 1 && events[FACE_AP_SEND_RETURN] == 1);
    assert(events[FACE_AP_RECEIVE] == 1 && events[FACE_AP_FREE_RETURN] == 1);
    ++subcases;
}

static uint64_t field(const char *text, const char *key)
{
    const char *at = strstr(text, key);
    char *end;
    unsigned long long value;
    assert(at != NULL);
    at += strlen(key);
    value = strtoull(at, &end, 0);
    assert(end != at && (*end == ' ' || *end == '\0'));
    return (uint64_t)value;
}

static void four_units(void)
{
    unsigned i;
    for (i = 0; i < 4; ++i) {
        reset(i);
        birth(i);
        success(i);
        /* AP20 address/length bytes deliberately retain 0xa5, never proc metadata. */
        assert(reply_wire[16] == 0xa5 && reply_wire[24] == 0xa5);
        assert(saved(i)->row.address != UINT64_C(0xa5a5a5a5a5a5a5a5));
    }
}

static void repeat_sticky(void)
{
    struct functional_face_native_proc_birth original;
    unsigned original_logs;
    reset(0);
    birth(0);
    success(0);
    original = *saved(0);
    original_logs = log_count;
    functional_face_ap_freed(&functional_face_ap_state, TID, QUEUE, reply_wire, 0, event_record);
    observe();
    assert(opens == 2 && log_count == original_logs);
    assert(saved(0)->observation == original.observation && saved(0)->row.address == original.row.address);
    begin(1, 0x20);
    collect_on_free = 0;
    receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
    functional_face_ap_state.unit = 0x1d9;
    put32(functional_face_ap_state.reply_wire + 12, 0x42d);
    observe();
    assert(!saved(1)->attempted && opens == 2);
    ++subcases;
    reset(0);
    plans[0].mode = IO_OPEN_ERROR;
    birth(0);
    failed(0, -EACCES, 1);
    original_logs = log_count;
    plans[0].mode = IO_NORMAL;
    observe();
    assert(opens == 1 && log_count == original_logs && saved(0)->error == -EACCES);
    collect_on_free = 1;
    birth(0);
    assert(opens == 1 && saved(0)->error == -EACCES && saved(0)->observation == 1);
    ++subcases;
}

static void pre_io_gates(void)
{
    unsigned i;
    for (i = 0; i < 12; ++i) {
        struct functional_face_ap_observer other;
        reset(0);
        collect_on_free = 0;
        birth(0);
        switch (i) {
        case 0: functional_camera_enabled = 0; break;
        case 1: functional_face_ap_state.owner_pid = getpid() + 1; break;
        case 2: functional_face_ap_state.sender_tid = TID + 1; break;
        case 3: functional_face_ap_state.op = 0x21; break;
        case 4: functional_face_ap_state.op = 0x23; break;
        case 5: functional_face_ap_state.unit = 0x1d8; break;
        case 6: functional_face_ap_state.unit = 0x1dd; break;
        case 7: functional_face_ap_state.active = 1; break;
        case 8: functional_face_ap_state.free_attempts = 0; break;
        case 9: functional_face_ap_state.free_attempts = 2; break;
        case 10: functional_face_ap_state.free_result = -EIO; break;
        default:
            other = functional_face_ap_state;
            functional_face_native_birth_observe(&other);
            no_io(0);
            continue;
        }
        observe();
        no_io(0);
    }
}

static void birth_facts(void)
{
    unsigned i;
    for (i = 0; i < 9; ++i) {
        reset(0);
        collect_on_free = 0;
        begin(0, 0x20);
        if (i == 0) {
            functional_face_ap_sent(&functional_face_ap_state, TID, -EIO, event_record);
        } else if (i == 1) {
            receive_and_free(FUNCTIONAL_FACE_AP_DMM, 1, 0);
        } else if (i == 2) {
            receive_and_free(FUNCTIONAL_FACE_AP_DMM + 1, 0, 0);
        } else if (i == 3) {
            receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, -EIO);
        } else if (i == 4) {
            functional_face_ap_sent(&functional_face_ap_state, TID, 0, event_record);
            functional_face_ap_received(&functional_face_ap_state, TID, QUEUE,
                FUNCTIONAL_FACE_AP_DMM, reply_wire, sizeof(reply_wire), 0, event_record);
        } else {
            receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
            if (i == 5) {
                begin(0, 0x23);
                receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
                begin(0, 0x20);
                receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
            } else if (i == 6) {
                birth(0); /* Real second birth makes the saved handle ambiguous. */
            } else if (i == 7) {
                begin(1, 0x20);
                receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
                functional_face_ap_state.unit = 0x1d9;
                put32(functional_face_ap_state.reply_wire + 12, 0x42d);
            } else {
                put32(functional_face_ap_state.reply_wire + 12, 0x42e);
            }
        }
        observe();
        no_io(0);
    }
    reset(0);
    collect_on_free = 0;
    birth(0);
    begin(0, 0x23);
    receive_and_free(FUNCTIONAL_FACE_AP_DMM, 0, 0);
    assert(functional_face_ap_state.births[0].any_free_observed == 1);
    /* Isolate the collector's any-free gate on real core facts. */
    functional_face_ap_state.op = 0x20;
    functional_face_ap_state.sequence = functional_face_ap_state.births[0].observation_sequence;
    put32(functional_face_ap_state.reply_wire + 12, 0x42d);
    observe();
    no_io(0);
}

static void fork_owner(void)
{
    unsigned busy;
    for (busy = 0; busy <= 1; ++busy) {
        pid_t child;
        int status;
        reset(0);
        collect_on_free = 0;
        birth(0);
        functional_face_native_proc_busy = busy;
        child = fork();
        assert(child >= 0);
        if (child == 0) {
            observe();
            no_io(0);
            assert(functional_face_native_proc_busy == busy);
            exit(0);
        }
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
        assert(!saved(0)->attempted && functional_face_native_proc_busy == busy);
        ++subcases;
    }
}

static void open_error(void)
{
    unsigned pass;
    for (pass = 0; pass < 2; ++pass) {
        reset(0);
        plans[pass].mode = IO_OPEN_ERROR;
        birth(0);
        failed(0, -EACCES, pass + 1);
        assert(closes == pass && reads == 2 * pass);
    }
}

static void read_errors(void)
{
    unsigned pass;
    for (pass = 0; pass < 2; ++pass) {
        reset(0);
        plans[pass].mode = IO_READ_ERROR;
        birth(0);
        failed(0, -EIO, pass + 1);
        assert(closes == pass + 1 && reads == 2 * pass + 1);
        reset(0);
        plans[pass].mode = IO_OVERSIZE;
        birth(0);
        failed(0, -EIO, pass + 1);
        assert(closes == pass + 1 && reads == 2 * pass + 1);
    }
}

static void read_bounds(void)
{
    unsigned pass;
    for (pass = 0; pass < 2; ++pass) {
        reset(0);
        plans[pass].mode = IO_NO_EOF;
        birth(0);
        failed(0, -EIO, pass + 1);
        assert(plans[pass].reads == 32 && closes == pass + 1);
        reset(0);
        plans[pass].mode = IO_CAPACITY;
        birth(0);
        failed(0, -E2BIG, pass + 1);
        assert(plans[pass].reads == 1 && closes == pass + 1);
    }
    reset(0);
    plans[0].chunk = 37;
    plans[1].chunk = 47;
    birth(0);
    success(0);
    assert(plans[0].reads > 2 && plans[1].reads > 2);
}

static void close_error(void)
{
    unsigned pass;
    for (pass = 0; pass < 2; ++pass) {
        reset(0);
        plans[pass].mode = IO_CLOSE_ERROR;
        birth(0);
        failed(0, -EBADF, pass + 1);
        assert(closes == pass + 1 && reads == 2 * (pass + 1));
    }
    reset(0);
    plans[0].mode = IO_READ_ERROR;
    plans[0].close_error = 1;
    birth(0);
    failed(0, -EIO, 1);
}

static void invalid_table(void)
{
    unsigned pass, kind;
    for (pass = 0; pass < 2; ++pass) {
        for (kind = 0; kind < 5; ++kind) {
            struct document *d;
            reset(0);
            d = &plans[pass].doc;
            if (kind == 0)
                d->text[0] = 'i';
            else if (kind == 1)
                --d->bytes;
            else if (kind == 2)
                row(d, 0x42d, 0x1d9, 1, 1, 0, 0, 1, 0x89abcdef,
                    0x100004000ULL, sizes[0], 0xf1);
            else if (kind == 3)
                append(d, "garbage\n");
            else {
                start(d);
                row(d, 0x42e, 0x1da, 1, 1, 0, 0, 1, 0x89abcdef,
                    0x100004000ULL, sizes[1], 0xf1);
            }
            birth(0);
            failed(0, kind == 4 ? -ENODATA : -EPROTO, pass + 1);
            assert(closes == pass + 1);
        }
    }
}

static void changed_second(void)
{
    unsigned kind;
    for (kind = 0; kind < 9; ++kind) {
        unsigned state = 1, owners = 1, open_count = 0, shares = 0, gen = 1;
        unsigned relation = 0x89abcdef, bytes = sizes[0], id = 0xf1;
        unsigned long long address = 0x100004000ULL;
        reset(0);
        switch (kind) {
        case 0: owners = 2; break;
        case 1: gen = 2; break;
        case 2: ++relation; break;
        case 3: address += 0x1000; break;
        case 4: ++id; break;
        case 5: state = 2; break;
        case 6: open_count = 1; break;
        case 7: shares = 1; break;
        default: --bytes; break;
        }
        start(&plans[1].doc);
        row(&plans[1].doc, 0x42d, 0x1d9, state, owners, open_count, shares,
            gen, relation, address, bytes, id);
        birth(0);
        failed(0, kind == 8 ? -EPROTO : -ESTALE, 2);
    }
}

static void offset_only(void)
{
    reset(0);
    start(&plans[1].doc);
    row(&plans[1].doc, 0x421, 0x123, 2, 1, 0, 0, 1, 2,
        0x100104000ULL, 1, 2);
    row(&plans[1].doc, 0x42d, 0x1d9, 1, 1, 0, 0, 1, 0x89abcdef,
        0x100004000ULL, sizes[0], 0xf1);
    birth(0);
    success(0);
    {
        struct functional_face_proc_unit second;
        assert(functional_face_proc_unit_parse(plans[1].doc.text, plans[1].doc.bytes,
            0x1d9, 0x42d, &second) == 0);
        assert(saved(0)->row.row_offset != second.row_offset);
        assert(functional_face_native_proc_same(&saved(0)->row, &second));
    }
}

static void birth_counters(void)
{
    unsigned kind;
    for (kind = 0; kind < 4; ++kind) {
        unsigned pass;
        reset(0);
        for (pass = 0; pass < 2; ++pass) {
            start(&plans[pass].doc);
            row(&plans[pass].doc, 0x42d, 0x1d9, kind == 2 ? 2 : 1,
                kind == 0 ? 2 : 1, kind == 1 ? 1 : 0, kind == 3 ? 1 : 0,
                1, 0x89abcdef, 0x100004000ULL, sizes[0], 0xf1);
        }
        birth(0);
        failed(0, -ESTALE, 2);
    }
}

static void busy_errno(void)
{
    unsigned old_logs;
    reset(0);
    functional_face_native_proc_busy = 1;
    birth(0);
    assert(saved(0)->attempted == 1 && saved(0)->error == -EBUSY);
    assert(saved(0)->owner_pid == getpid() && saved(0)->owner_tid == TID);
    assert(saved(0)->observation == 1 && saved(0)->row.handle == 0);
    assert(opens == 0 && allocations == 0 && deallocations == 0);
    assert(functional_face_native_proc_busy == 1 && errno == SAVED_ERRNO);
    old_logs = log_count;
    functional_face_native_proc_busy = 0;
    observe();
    assert(opens == 0 && log_count == old_logs && saved(0)->error == -EBUSY);
    ++subcases;
    reset(0);
    plans[0].mode = IO_READ_ERROR;
    birth(0);
    failed(0, -EIO, 1);
    assert(functional_face_native_proc_busy == 0);
    reset(0);
    birth(0);
    success(0);
}

static uint64_t fnv(const struct document *d)
{
    uint64_t digest = UINT64_C(14695981039346656037);
    size_t i;
    for (i = 0; i < d->bytes; ++i) {
        digest ^= (unsigned char)d->text[i];
        digest *= UINT64_C(1099511628211);
    }
    return digest;
}

static void raw_evidence(void)
{
    unsigned pass, i, reads_logged = 0, birth_logged = 0;
    char reconstructed[2][2048];
    size_t reconstructed_bytes[2] = {0, 0};
    reset(0);
    for (pass = 0; pass < 2; ++pass) {
        --plans[pass].doc.bytes;
        for (i = 0; i < 32; ++i)
            append(&plans[pass].doc, " < %04x", i);
        append(&plans[pass].doc, "\n");
    }
    birth(0);
    success(0);
    for (i = 0; i < log_count; ++i) {
        const char *text = logs[i].text;
        assert(strstr(text, "diagnostic_only=1") != NULL);
        if (strcmp(logs[i].prefix, "FUNCTIONAL_FACE_DMM_PROC_READ ") == 0) {
            pass = (unsigned)field(text, "pass=") - 1;
            assert(pass < 2);
            assert(field(text, "table_bytes=") == plans[pass].doc.bytes);
            assert(field(text, "table_fnv=") == fnv(&plans[pass].doc));
            assert(field(text, "eof=") == 1 && field(text, "parse_rc=") == 0);
            assert(strstr(text, "atomic_snapshot_verified=0") != NULL);
            assert(strstr(text, "competing_readers_excluded=0") != NULL);
            assert(strstr(text, "allocation_pin_verified=0") != NULL);
            assert(strstr(text, "capture_verified=0") != NULL);
            ++reads_logged;
        } else if (strcmp(logs[i].prefix, "FUNCTIONAL_FACE_DMM_PROC_ROW ") == 0) {
            size_t n, j;
            const char *hex = strstr(text, "raw=");
            pass = (unsigned)field(text, "pass=") - 1;
            assert(pass < 2 && hex != NULL);
            hex += 4;
            n = (size_t)field(text, "chunk_bytes=");
            assert(n > 0 && n <= 128);
            assert(field(text, "chunk_offset=") == reconstructed_bytes[pass]);
            assert(field(text, "row_bytes=") == saved(0)->row.row_bytes);
            assert(field(text, "row_offset=") == saved(0)->row.row_offset);
            assert(reconstructed_bytes[pass] + n <= sizeof(reconstructed[pass]));
            for (j = 0; j < n; ++j) {
                unsigned value;
                assert(sscanf(hex + 2 * j, "%2x", &value) == 1 && value <= 255);
                reconstructed[pass][reconstructed_bytes[pass]++] = (char)value;
            }
            assert(hex[2 * n] == ' ');
        } else {
            assert(strcmp(logs[i].prefix, "FUNCTIONAL_FACE_DMM_PROC_BIRTH ") == 0);
            assert(field(text, "capture_rc=") == 0);
            assert(field(text, "relation=") == 0x89abcdef);
            assert(field(text, "generation=") == 1);
            assert(strstr(text, "native_birth_complete=0") != NULL);
            assert(strstr(text, "source_memory_ready=0") != NULL);
            assert(strstr(text, "allocation_pin_verified=0") != NULL);
            assert(strstr(text, "physical_verified=0") != NULL);
            assert(strstr(text, "capture_verified=0") != NULL);
            ++birth_logged;
        }
    }
    assert(reads_logged == 2 && birth_logged == 1 && saved(0)->row.row_bytes > 256);
    for (pass = 0; pass < 2; ++pass) {
        assert(reconstructed_bytes[pass] == saved(0)->row.row_bytes);
        assert(memcmp(reconstructed[pass], plans[pass].doc.text + saved(0)->row.row_offset,
                      reconstructed_bytes[pass]) == 0);
    }
    ++subcases;
}

static void semantic_fields(void)
{
    struct functional_face_proc_unit a = {
        .handle = 0x42d, .unit = 0x1d9, .state = 1, .owners = 1,
        .opens = 0, .shares = 0, .generation = 1, .relation = 0x89abcdef,
        .extent_id = 0xf1, .segments = 1, .address = 0x100004000ULL,
        .bytes = 0x64000, .row_offset = 250, .row_bytes = 100
    };
    struct functional_face_proc_unit b;
    unsigned i;
    for (i = 0; i < 12; ++i) {
        b = a;
        switch (i) {
        case 0: ++b.handle; break;
        case 1: ++b.unit; break;
        case 2: ++b.state; break;
        case 3: ++b.owners; break;
        case 4: ++b.opens; break;
        case 5: ++b.shares; break;
        case 6: ++b.generation; break;
        case 7: ++b.relation; break;
        case 8: ++b.extent_id; break;
        case 9: ++b.segments; break;
        case 10: ++b.address; break;
        default: ++b.bytes; break;
        }
        assert(!functional_face_native_proc_same(&a, &b));
        ++subcases;
    }
    b = a;
    ++b.row_offset;
    ++b.row_bytes;
    assert(functional_face_native_proc_same(&a, &b));
    ++subcases;
}

static void allocation_tokens(void)
{
    uint64_t prior = 0;
    for (unsigned i = 0; i < 4; ++i) {
        reset(i);
        functional_face_native_allocation_serial = prior;
        birth(i);
        success(i);
        assert(saved(i)->allocation_token == (UINT64_C(0xface000000000000) | (prior + 1)));
        uint64_t token = saved(i)->allocation_token;
        observe();
        assert(saved(i)->allocation_token == token && functional_face_native_allocation_serial == prior + 1);
        prior = functional_face_native_allocation_serial;
    }
    reset(0);
    functional_face_native_allocation_serial = UINT64_C(0x0000ffffffffffff);
    birth(0);
    failed(0, -EOVERFLOW, 2);
    assert(functional_face_native_allocation_serial == UINT64_C(0x0000ffffffffffff));
    unsigned old_opens = opens;
    observe();
    assert(opens == old_opens && !saved(0)->allocation_token);
}

static void current_metadata(void)
{
    struct functional_face_proc_unit out, sentinel;
    for (unsigned mode = 0; mode < 7; ++mode) {
        reset(0);
        birth(0);
        struct functional_face_native_proc_birth original = *saved(0);
        memset(&out, 0x5a, sizeof out);
        sentinel = out;
        opens = reads = closes = allocations = deallocations = log_count = 0;
        for (unsigned pass = 0; pass < 2; ++pass) {
            plans[pass].cursor = plans[pass].reads = 0;
            start(&plans[pass].doc);
            row(&plans[pass].doc, 0x42d, 0x1d9, 2, 2, 1, 0, 1,
                UINT32_C(0x89abcdef) + (mode == 1 || (mode == 2 && pass == 1)),
                UINT64_C(0x100004000), 0x64000, 0xf1);
        }
        if (mode == 3) plans[0].mode = IO_OPEN_ERROR;
        if (mode == 4) functional_face_native_proc_busy = 1;
        if (mode == 5) ++saved(0)->observation;
        if (mode == 6) saved(0)->allocation_token = 0;
        errno = SAVED_ERRNO;
        int rc = functional_face_source_current_metadata(NULL, 0x1d9, 0x42d, &out);
        assert(errno == SAVED_ERRNO && functional_face_native_allocation_serial == 1);
        if (mode < 2) {
            assert(!rc && out.owners == 2 && out.opens == 1 && out.state == 2);
            assert(out.relation == UINT32_C(0x89abcdef) + mode);
            assert(!memcmp(saved(0), &original, sizeof original));
        } else {
            assert(rc == (mode == 3 ? -EACCES : mode == 4 ? -EBUSY : -ESTALE));
            assert(!memcmp(&out, &sentinel, sizeof out));
        }
        if (mode >= 4) assert(!opens && !reads && !allocations);
        assert(functional_face_native_proc_busy == (unsigned)(mode == 4));
        assert(allocations == deallocations);
        ++subcases;
    }
}

int main(int argc, char **argv)
{
    static const struct { const char *name; void (*run)(void); } scenarios[] = {
        {"four-units", four_units}, {"repeat-sticky", repeat_sticky},
        {"pre-io-gates", pre_io_gates}, {"birth-facts", birth_facts},
        {"fork-owner", fork_owner}, {"open-error", open_error},
        {"read-errors", read_errors}, {"read-bounds", read_bounds},
        {"close-error", close_error}, {"invalid-table", invalid_table},
        {"changed-second", changed_second}, {"offset-only", offset_only},
        {"birth-counters", birth_counters}, {"busy-errno", busy_errno},
        {"raw-evidence", raw_evidence}, {"semantic-fields", semantic_fields},
        {"allocation-tokens", allocation_tokens}, {"current-metadata", current_metadata}
    };
    size_t i;
    assert(argc == 2);
    for (i = 0; i < sizeof(scenarios) / sizeof(scenarios[0]); ++i) {
        if (strcmp(argv[1], scenarios[i].name) != 0)
            continue;
        scenarios[i].run();
        assert(allocations == deallocations);
        printf("PROC_BIRTH_HOSTTEST_PASS scenario=%s subcases=%u "
               "actual_observer=1 actual_parser=1 host_proc_reads=0 "
               "diagnostic_only=1 native_birth_complete=0 source_memory_ready=0 "
               "allocation_pin_verified=0 competing_readers_excluded=0 native_operations=0\n",
               argv[1], subcases);
        return 0;
    }
    fprintf(stderr, "unknown scenario: %s\n", argv[1]);
    return 2;
}
