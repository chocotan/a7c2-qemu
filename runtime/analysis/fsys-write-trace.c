#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

/* shortcut: 32 requests and 128 MiB per request bound observation only; raise
 * these bounds when a native recording exceeds them, never infer unread data. */
#define TRACE_REQUESTS 32u
struct write_record {
    _Atomic unsigned ready, submitted, callback_seen, callback_returned, worker_seen;
    int submit_rc, callback_rc, result_copied, worker_rc;
    uint64_t cookie, callback;
    struct fsys_write_layout layout;
    int observation_rc;
};
static struct write_record records[TRACE_REQUESTS];
static _Atomic unsigned next_record, missed_records;

static uint64_t u64(const unsigned char *p) {
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; i++) value |= (uint64_t)p[i] << (i * 8);
    return value;
}
static uint32_t u32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
uint64_t fsys_write_fnv1a64(const void *data, size_t bytes) {
    const unsigned char *p = data;
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) { hash ^= p[i]; hash *= UINT64_C(1099511628211); }
    return hash;
}
int fsys_write_decode(const unsigned char *request, size_t bytes, struct fsys_write_layout *out) {
    if (!request || !out || bytes != FSYS_WRITE_REQUEST_BYTES) return -EINVAL;
    memset(out, 0, sizeof *out);
    out->count = u32(request + 0x4f0);
    out->callback = u64(request + 0x4f8);
    out->cookie = u64(request + 0x500);
    out->open_flags = u32(request + 0x410);
    out->expected_bytes = u32(request + 0x42c);
    const unsigned char *end = memchr(request, 0, FSYS_WRITE_PATH_BYTES);
    if (!end) return -ENAMETOOLONG;
    memcpy(out->path, request, (size_t)(end - request));
    if (out->path[0] < 'A' || out->path[0] > 'Z' || out->path[1] != ':' || out->path[2] != '/') return -EINVAL;
    if (!out->count || out->count > FSYS_WRITE_AREAS || !out->expected_bytes) return -ENODATA;
    out->address_mode = u64(request + 0x438) ? 1u : 2u;
    uint64_t submitted = 0;
    for (unsigned i = 0; i < out->count; i++) {
        const unsigned char *p = request + 0x430 + i * 0x18;
        struct fsys_write_area *a = &out->area[i];
        a->physical_address = u64(p); a->address = u64(p + 8); a->submitted_bytes = u64(p + 0x10);
        a->offset = submitted;
        if (a->submitted_bytes > UINT64_MAX - submitted) return -EOVERFLOW;
        submitted += a->submitted_bytes;
        if (a->offset < out->expected_bytes) {
            uint64_t remaining = out->expected_bytes - a->offset;
            a->bytes = a->submitted_bytes < remaining ? a->submitted_bytes : remaining;
            out->payload_bytes += a->bytes;
        }
    }
    if (out->expected_bytes > submitted) return -ENODATA;
    if (out->address_mode != 1u) return -ENOTSUP;
    for (unsigned i = 0; i < out->count; i++) {
        const struct fsys_write_area *a = &out->area[i];
        if (!a->address || (a->address & 4095u) || (a->submitted_bytes & 4095u)) return -EINVAL;
        if (a->address > INT64_MAX || a->submitted_bytes > (uint64_t)INT64_MAX - a->address) return -EOVERFLOW;
    }
    if (out->payload_bytes > FSYS_WRITE_OBSERVATION_LIMIT) return -E2BIG;
    return 0;
}
static int enabled(void) {
    const char *s = getenv("A7C2_FSYS_ASYNC_OBSERVE");
    return s && s[0] == '1' && !s[1];
}
static void trace(const char *format, ...) {
    int error = errno;
    char line[3072];
    va_list args;
    va_start(args, format);
    int n = vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (n > 0 && (size_t)n < sizeof line) {
        int fd = open("/dev/console", O_WRONLY | O_CLOEXEC);
        if (fd >= 0) { (void)write(fd, line, (size_t)n); close(fd); }
    }
    errno = error;
}
static int copy_memory(int fd, uint64_t address, void *data, size_t bytes) {
    if (fd < 0 || !address || address > INT64_MAX || bytes > (uint64_t)INT64_MAX - address) return 0;
    return pread(fd, data, bytes, (off_t)address) == (ssize_t)bytes;
}
static int hash_memory(int fd, const struct fsys_write_area *a, uint64_t *hash) {
    unsigned char buffer[4096];
    uint64_t h = UINT64_C(14695981039346656037);
    for (uint64_t done = 0; done < a->bytes;) {
        size_t n = a->bytes - done > sizeof buffer ? sizeof buffer : (size_t)(a->bytes - done);
        if (!copy_memory(fd, a->address + done, buffer, n)) return 0;
        for (size_t i = 0; i < n; i++) { h ^= buffer[i]; h *= UINT64_C(1099511628211); }
        done += n;
    }
    *hash = h;
    return 1;
}
unsigned fsys_write_trace_begin(const unsigned char request[FSYS_WRITE_REQUEST_BYTES]) {
    int error = errno;
    if (!enabled() || !request) { errno = error; return 0; }
    unsigned index = atomic_load_explicit(&next_record, memory_order_relaxed);
    while (index < TRACE_REQUESTS && !atomic_compare_exchange_weak_explicit(
            &next_record, &index, index + 1, memory_order_relaxed, memory_order_relaxed)) {}
    if (index >= TRACE_REQUESTS) { fsys_write_trace_unobserved(); errno = error; return 0; }
    struct fsys_write_layout layout = {0};
    int rc = fsys_write_decode(request, FSYS_WRITE_REQUEST_BYTES, &layout);
    uint64_t hashes[FSYS_WRITE_AREAS] = {0};
    unsigned readable[FSYS_WRITE_AREAS] = {0};
    if (!rc) {
        int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
        for (unsigned i = 0; i < layout.count; i++) {
            readable[i] = (unsigned)hash_memory(fd, &layout.area[i], &hashes[i]);
            if (!readable[i]) rc = -EFAULT;
        }
        if (fd >= 0) close(fd);
    }
    char path_hex[FSYS_WRITE_PATH_BYTES * 2 + 1];
    const char hex[] = "0123456789abcdef";
    size_t length = strlen(layout.path);
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)layout.path[i];
        path_hex[i * 2] = hex[c >> 4]; path_hex[i * 2 + 1] = hex[c & 15];
    }
    path_hex[length * 2] = 0;
    records[index].cookie = layout.cookie;
    records[index].callback = layout.callback;
    records[index].layout = layout;
    records[index].observation_rc = rc;
    atomic_store_explicit(&records[index].ready, 1, memory_order_release);
    unsigned token = index + 1;
    trace("FSYS_WRITE_REQUEST pid=%d token=%u cookie=0x%llx bytes=1288 request_fnv1a64=%016llx areas=%u observation_rc=%d path_hex=%s payload_complete=%d expected_bytes=%llu address_mode=%u open_flags=%u media_origin_verified=0\n",
          getpid(), token, (unsigned long long)layout.cookie,
          (unsigned long long)fsys_write_fnv1a64(request, FSYS_WRITE_REQUEST_BYTES), layout.count, rc,
          length ? path_hex : "-", !rc, (unsigned long long)layout.expected_bytes, layout.address_mode, layout.open_flags);
    for (unsigned i = 0; i < layout.count && i < FSYS_WRITE_AREAS; i++) {
        trace("FSYS_WRITE_AREA pid=%d token=%u index=%u offset=%llu bytes=%llu data_fnv1a64=%016llx readable=%u submitted_bytes=%llu\n",
              getpid(), token, i, (unsigned long long)layout.area[i].offset,
              (unsigned long long)layout.area[i].bytes, (unsigned long long)hashes[i], readable[i],
              (unsigned long long)layout.area[i].submitted_bytes);
    }
    errno = error;
    return token;
}
void fsys_write_trace_submit(unsigned token, int rc) {
    if (!token || token > TRACE_REQUESTS) return;
    records[token - 1].submit_rc = rc;
    atomic_store_explicit(&records[token - 1].submitted, 1, memory_order_release);
    trace("FSYS_WRITE_SUBMIT pid=%d token=%u rc=%d callback_seen=%u\n", getpid(), token, rc,
          atomic_load_explicit(&records[token - 1].callback_seen, memory_order_acquire));
}
/* Reused or duplicate cookies cannot be paired by inventing a generation. */
static unsigned match(uint64_t cookie, uint64_t callback, int worker) {
    unsigned token = 0;
    for (unsigned i = 0; i < TRACE_REQUESTS; i++) {
        if (!atomic_load_explicit(&records[i].ready, memory_order_acquire) || records[i].cookie != cookie) continue;
        if (worker ? !atomic_load_explicit(&records[i].callback_seen, memory_order_acquire) : records[i].callback != callback) continue;
        if (token) return 0;
        token = i + 1;
    }
    return token;
}
unsigned fsys_write_trace_callback(void *cookie, int rc, const void *result, uint64_t callback) {
    int error = errno;
    if (!enabled()) { errno = error; return 0; }
    unsigned token = match((uint64_t)(uintptr_t)cookie, callback, 0);
    unsigned char snapshot[FSYS_WRITE_RESULT_BYTES];
    int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
    int copied = copy_memory(fd, (uint64_t)(uintptr_t)result, snapshot, sizeof snapshot);
    if (fd >= 0) close(fd);
    unsigned duplicate = 0;
    if (token) {
        duplicate = atomic_exchange_explicit(&records[token - 1].callback_seen, 1, memory_order_acq_rel);
        if (!duplicate) {
            records[token - 1].callback_rc = rc;
            records[token - 1].result_copied = copied;
        }
    }
    if (!token || duplicate) fsys_write_trace_unobserved();
    trace("MPR_WRITE_CALLBACK pid=%d token=%u cookie=0x%llx rc=%d result_copied=%d result_fnv1a64=%016llx duplicate=%u result_bytes=1240\n",
          getpid(), token, (unsigned long long)(uintptr_t)cookie, rc, copied,
          (unsigned long long)(copied ? fsys_write_fnv1a64(snapshot, sizeof snapshot) : 0), duplicate);
    errno = error;
    return duplicate ? 0 : token;
}
void fsys_write_trace_callback_return(unsigned token) {
    if (!token || token > TRACE_REQUESTS) return;
    atomic_store_explicit(&records[token - 1].callback_returned, 1, memory_order_release);
    trace("MPR_WRITE_CALLBACK_RETURN pid=%d token=%u returned=1\n", getpid(), token);
}
void fsys_write_trace_unobserved(void) {
    if (!enabled()) return;
    atomic_fetch_add_explicit(&missed_records, 1, memory_order_relaxed);
    trace("FSYS_WRITE_COVERAGE_INCOMPLETE pid=%d missed=1\n", getpid());
}
struct fsys_write_finished fsys_write_trace_finished_begin(const void *input) {
    int error = errno;
    struct fsys_write_finished out = {0};
    if (enabled()) {
        unsigned char snapshot[24];
        int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
        out.input_copied = copy_memory(fd, (uint64_t)(uintptr_t)input, snapshot, sizeof snapshot);
        if (fd >= 0) close(fd);
        if (out.input_copied) {
            out.cookie = u64(snapshot); out.rc = (int32_t)u32(snapshot + 8);
            out.token = match(out.cookie, 0, 1);
        }
    }
    errno = error;
    return out;
}
void fsys_write_trace_finished_return(struct fsys_write_finished input) {
    int error = errno;
    if (!enabled()) { errno = error; return; }
    unsigned duplicate = 0;
    if (input.token && input.token <= TRACE_REQUESTS) {
        unsigned expected = 0;
        duplicate = !atomic_compare_exchange_strong_explicit(&records[input.token - 1].worker_seen,
                         &expected, 1, memory_order_acq_rel, memory_order_acquire);
        if (!duplicate) {
            records[input.token - 1].worker_rc = input.rc;
            atomic_store_explicit(&records[input.token - 1].worker_seen, 2, memory_order_release);
        }
    }
    if (!input.token || duplicate) fsys_write_trace_unobserved();
    trace("MPR_WRITE_FINISHED pid=%d token=%u cookie=0x%llx rc=%d input_copied=%d returned=1 duplicate=%u\n",
          getpid(), input.token, (unsigned long long)input.cookie, input.rc, input.input_copied, duplicate);
    errno = error;
}

/* Called only after the mounted owner's original Fsys_FlushVolume succeeds.
 * The original Open/Read/Close functions consume the real volume; no host file
 * is injected, no completion is synthesized, and no source buffer is written. */
int fsys_write_trace_readback(const struct fsys_native_read_ops *ops) {
    int error = errno, result = 0;
    if (!enabled()) { errno = error; return 0; }
    if (!ops || !ops->open || !ops->read || !ops->close) { errno = error; return -EINVAL; }
    unsigned count = atomic_load_explicit(&next_record, memory_order_acquire);
    if (atomic_load_explicit(&missed_records, memory_order_acquire)) result = -ENODATA;
    for (unsigned i = 0; !result && i < count; i++) {
        struct write_record *r = &records[i];
        if (!atomic_load_explicit(&r->ready, memory_order_acquire) ||
            !atomic_load_explicit(&r->submitted, memory_order_acquire) ||
            !atomic_load_explicit(&r->callback_returned, memory_order_acquire) ||
            atomic_load_explicit(&r->worker_seen, memory_order_acquire) != 2) {
            result = -EAGAIN; break;
        }
        if (r->observation_rc || r->submit_rc || r->callback_rc || !r->result_copied || r->worker_rc) {
            result = -ENODATA; break;
        }
    }
    for (unsigned i = 0; !result && i < count; i++) {
        const struct write_record *r = &records[i];
        unsigned char buffer[4096];
        uint64_t bytes = 0, hash = UINT64_C(14695981039346656037);
        unsigned long long handle = 0;
        int rc = ops->open(r->layout.path, &handle, 1), opened = !rc, eof = 0, close_rc = 0;
        while (!rc && bytes < r->layout.expected_bytes) {
            uint64_t remaining = r->layout.expected_bytes - bytes;
            int want = remaining > sizeof buffer ? (int)sizeof buffer : (int)remaining;
            int actual = ops->read(handle, buffer, want);
            if (actual <= 0 || actual > want) { rc = actual < 0 ? actual : -EIO; break; }
            for (int j = 0; j < actual; j++) { hash ^= buffer[j]; hash *= UINT64_C(1099511628211); }
            bytes += (unsigned)actual;
        }
        if (!rc) {
            int actual = ops->read(handle, buffer, 1);
            eof = actual == 0;
            if (!eof) rc = actual < 0 ? actual : -EFBIG;
        }
        if (opened) {
            close_rc = ops->close(handle);
            if (!rc && close_rc) rc = close_rc;
        }
        trace("FSYS_WRITE_NATIVE_READBACK pid=%d token=%u cookie=0x%llx rc=%d bytes=%llu fnv1a64=%016llx eof=%d close_rc=%d\n",
              getpid(), i + 1, (unsigned long long)r->cookie, rc, (unsigned long long)bytes,
              (unsigned long long)hash, eof, close_rc);
        if (rc) result = rc;
    }
    if (count != atomic_load_explicit(&next_record, memory_order_acquire) ||
        atomic_load_explicit(&missed_records, memory_order_acquire)) result = -EAGAIN;
    trace("FSYS_WRITE_READBACK_COVERAGE pid=%d records=%u rc=%d\n", getpid(), count, result);
    errno = error;
    return result;
}

/* shortcut: retain at most 128 MiB/1024 frozen writes and 32 file lifetimes per
 * process; exceeding any bound invalidates coverage, never samples a prefix. */
struct sync_file {
    uint64_t handle, generation, size, position, version;
    unsigned size_known, position_known, pending, closed, tainted, failed;
    char path[FSYS_WRITE_PATH_BYTES];
};
struct sync_write {
    unsigned file, state, and_flush, position_known, source_frozen;
    int requested, observation_rc;
    uint64_t offset, active_bytes, frozen_bytes;
    struct fsys_sync_context context;
    unsigned char *snapshot;
};
static struct sync_file sync_files[FSYS_SYNC_FILES];
static struct sync_write sync_writes[FSYS_SYNC_WRITES];
static unsigned sync_file_count, sync_write_count;
static uint64_t sync_retained;
static atomic_flag sync_lock = ATOMIC_FLAG_INIT;
static _Atomic int sync_pid;

static int sync_enter(void) {
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&sync_pid, &expected, pid);
    if (atomic_load(&sync_pid) != pid) return 0;
    while (atomic_flag_test_and_set_explicit(&sync_lock, memory_order_acquire)) {}
    return 1;
}
static void sync_leave(void) { atomic_flag_clear_explicit(&sync_lock, memory_order_release); }
static long sync_tid(void) {
    int error = errno;
    long tid = syscall(SYS_gettid);
    errno = error;
    return tid;
}
static struct sync_file *sync_identity(unsigned file, uint64_t handle, uint64_t generation) {
    if (!file || file > sync_file_count) return NULL;
    struct sync_file *f = &sync_files[file - 1];
    if (f->handle == handle && f->generation == generation) return f;
    f->tainted = 1; f->version++;
    return NULL;
}
static void sync_incomplete(unsigned file, uint64_t handle, uint64_t generation, int rc) {
    trace("FSYS_SYNC_INCOMPLETE pid=%d tid=%ld file=%u handle=%llx generation=%llu observation_rc=%d capture_verified=0\n",
          getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation, rc);
}
static void sync_discard(struct sync_write *w) {
    if (w->snapshot) { free(w->snapshot); sync_retained -= w->frozen_bytes; w->snapshot = NULL; }
    w->active_bytes = 0;
}
unsigned fsys_sync_trace_open(const void *frozen_path, size_t path_bytes,
    uint64_t handle, uint64_t generation, unsigned flags, int original_rc,
    int original_errno, unsigned size_known, uint64_t initial_size,
    unsigned position_known, uint64_t initial_position, struct fsys_sync_context context) {
    int error = errno, observation_rc = 0;
    unsigned file = 0, alias = 0;
    char path[FSYS_WRITE_PATH_BYTES] = {0};
    if (original_rc) observation_rc = -EIO;
    else if (!handle || !generation || !frozen_path || path_bytes < 3 || path_bytes >= sizeof path)
        observation_rc = -EINVAL;
    else {
        int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
        if (!copy_memory(fd, (uint64_t)(uintptr_t)frozen_path, path, path_bytes)) observation_rc = -EFAULT;
        if (fd >= 0) close(fd);
        if (!observation_rc && (memchr(path, 0, path_bytes) || path[0] < 'A' || path[0] > 'Z' ||
                               path[1] != ':' || path[2] != '/')) observation_rc = -EINVAL;
    }
    if (!sync_enter()) { errno = error; return 0; }
    if (!observation_rc) {
        for (unsigned i = 0; i < sync_file_count; i++) {
            struct sync_file *old = &sync_files[i];
            if (!strcmp(old->path, path) || (!old->closed && old->handle == handle)) {
                if (!old->closed && old->generation == generation) alias = 1;
                old->tainted = 1; old->version++;
            }
        }
        if (sync_file_count == FSYS_SYNC_FILES) observation_rc = -ENOSPC;
        else {
            file = ++sync_file_count;
            struct sync_file *f = &sync_files[file - 1];
            f->handle = handle; f->generation = generation; f->size = initial_size;
            f->position = initial_position; f->size_known = !!size_known;
            f->position_known = !!position_known; f->version = 1; f->tainted = alias;
            memcpy(f->path, path, path_bytes + 1);
        }
    }
    if (!file && !original_rc) {
        /* An untracked successful open can alias any previously observed file. */
        for (unsigned i = 0; i < sync_file_count; i++) { sync_files[i].tainted = 1; sync_files[i].version++; }
    }
    sync_leave();
    char path_hex[FSYS_WRITE_PATH_BYTES * 2 + 1];
    const char hex[] = "0123456789abcdef";
    size_t length = observation_rc ? 0 : path_bytes;
    for (size_t i = 0; i < length; i++) {
        unsigned char c = (unsigned char)path[i];
        path_hex[i * 2] = hex[c >> 4]; path_hex[i * 2 + 1] = hex[c & 15];
    }
    path_hex[length * 2] = 0;
    trace("FSYS_SYNC_OPEN pid=%d tid=%ld file=%u handle=%llx generation=%llu flags=%u result=%d errno=%d observation_rc=%d size_known=%u size=%llu position_known=%u offset=%llu caller=%llx context=%llx producer=%llx path_hex=%s media_origin_verified=0\n",
          getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation, flags,
          original_rc, original_errno, observation_rc, !!size_known, (unsigned long long)initial_size,
          !!position_known, (unsigned long long)initial_position, (unsigned long long)context.caller,
          (unsigned long long)context.context, (unsigned long long)context.producer, length ? path_hex : "-");
    errno = error;
    return file;
}
unsigned fsys_sync_trace_file(uint64_t handle, uint64_t generation) {
    int error = errno;
    unsigned file = 0;
    if (!sync_enter()) { errno = error; return 0; }
    for (unsigned i = 0; i < sync_file_count; i++) {
        const struct sync_file *f = &sync_files[i];
        if (!f->closed && f->handle == handle && f->generation == generation) {
            if (file) { file = 0; break; }
            file = i + 1;
        }
    }
    sync_leave(); errno = error;
    return file;
}
unsigned fsys_sync_trace_write_begin(unsigned file, uint64_t handle,
    uint64_t generation, struct fsys_sync_source source, int requested,
    unsigned and_flush, struct fsys_sync_context context) {
    int error = errno, rc = 0;
    unsigned ticket = 0;
    if (!sync_enter()) { errno = error; return 0; }
    struct sync_file *f = sync_identity(file, handle, generation);
    if (!f || f->closed) rc = -ESTALE;
    else if (sync_write_count == FSYS_SYNC_WRITES) rc = -ENOSPC;
    else {
        ticket = ++sync_write_count;
        struct sync_write *w = &sync_writes[ticket - 1];
        if (f->pending) { f->tainted = 1; f->position_known = 0; }
        w->file = file; w->state = 1; w->requested = requested;
        w->and_flush = and_flush; w->context = context;
        w->offset = f->position; w->position_known = f->position_known;
        f->pending++; f->version++;
        if (and_flush > 1 || requested < 0) rc = -EINVAL;
        else if (source.domain != FSYS_SYNC_VIRTUAL) rc = -ENOTSUP;
        else if (source.extent_known && (uint64_t)requested > source.extent) rc = -ENODATA;
        else if (!source.address || source.address > INT64_MAX ||
                 (source.extent_known ? source.extent : (uint64_t)requested) > (uint64_t)INT64_MAX - source.address) rc = -EOVERFLOW;
        else if ((unsigned)requested > FSYS_WRITE_OBSERVATION_LIMIT ||
                 (uint64_t)requested > FSYS_WRITE_OBSERVATION_LIMIT - sync_retained) rc = -E2BIG;
        else if (w->position_known && (uint64_t)requested > UINT64_MAX - w->offset) rc = -EOVERFLOW;
        else if (requested) {
            w->snapshot = malloc((size_t)requested);
            if (!w->snapshot) rc = -ENOMEM;
            else {
                w->frozen_bytes = (unsigned)requested; sync_retained += w->frozen_bytes;
                int fd = open("/proc/self/mem", O_RDONLY | O_CLOEXEC);
                for (uint64_t done = 0; !rc && done < w->frozen_bytes;) {
                    size_t n = w->frozen_bytes - done > FSYS_SYNC_CHUNK_BYTES ?
                        FSYS_SYNC_CHUNK_BYTES : (size_t)(w->frozen_bytes - done);
                    if (!copy_memory(fd, source.address + done, w->snapshot + done, n)) rc = -EFAULT;
                    else done += n;
                }
                if (fd >= 0) close(fd);
                if (rc) sync_discard(w);
            }
        }
        w->source_frozen = !rc;
        if (!rc && !source.extent_known) rc = -ENODATA;
        w->observation_rc = rc;
        trace("FSYS_SYNC_BEGIN pid=%d tid=%ld file=%u ticket=%u handle=%llx generation=%llu op=%s requested=%d address=%llx domain=%u extent_known=%u extent=%llu position_known=%u offset=%llu frozen=%d observation_rc=%d caller=%llx context=%llx producer=%llx\n",
              getpid(), sync_tid(), file, ticket, (unsigned long long)handle, (unsigned long long)generation,
              and_flush ? "WriteAndFlush" : "Write", requested, (unsigned long long)source.address,
              (unsigned)source.domain, source.extent_known, (unsigned long long)source.extent,
              w->position_known, (unsigned long long)w->offset, w->source_frozen, rc, (unsigned long long)context.caller,
              (unsigned long long)context.context, (unsigned long long)context.producer);
    }
    if (!ticket) {
        if (f) { f->tainted = 1; f->version++; }
        else for (unsigned i = 0; i < sync_file_count; i++) { sync_files[i].tainted = 1; sync_files[i].version++; }
        sync_incomplete(file, handle, generation, rc);
    }
    sync_leave(); errno = error;
    return ticket;
}
int fsys_sync_trace_write_end(unsigned ticket, uint64_t handle,
    uint64_t generation, int original_result, int original_errno) {
    int error = errno, rc = 0, source_complete = 0;
    uint64_t hash = 0;
    if (!sync_enter()) { errno = error; return -ESTALE; }
    if (!ticket || ticket > sync_write_count) {
        rc = -EINVAL;
        for (unsigned i = 0; i < sync_file_count; i++) { sync_files[i].tainted = 1; sync_files[i].version++; }
    }
    else {
        struct sync_write *w = &sync_writes[ticket - 1];
        struct sync_file *f = sync_identity(w->file, handle, generation);
        if (w->state != 1) {
            rc = -EALREADY;
            if (f) { f->tainted = 1; f->version++; }
        } else {
            struct sync_file *owner = &sync_files[w->file - 1];
            if (owner->pending) owner->pending--;
            owner->version++;
            if (!f || f->closed) rc = -ESTALE;
            else if (original_result < 0) rc = -EIO;
            else if (w->requested < 0 || original_result > w->requested) rc = -ERANGE;
            else if (!w->source_frozen) rc = w->observation_rc;
            else {
                source_complete = 1;
                hash = fsys_write_fnv1a64(w->snapshot, (size_t)original_result);
                if (w->position_known && (uint64_t)original_result <= UINT64_MAX - w->offset) {
                    w->active_bytes = (unsigned)original_result;
                    f->position = w->offset + w->active_bytes;
                    f->position_known = !f->tainted;
                    if (f->size_known && f->position > f->size) f->size = f->position;
                } else { f->tainted = 1; f->position_known = 0; }
                rc = w->observation_rc;
                if (!rc && original_result != w->requested) rc = -EIO;
            }
            if (rc) { owner->failed = 1; owner->position_known = 0; }
            if (!source_complete) { owner->tainted = 1; sync_discard(w); }
            w->state = 2;
            trace("FSYS_SYNC_WRITE pid=%d tid=%ld file=%u ticket=%u handle=%llx generation=%llu op=%s requested=%d result=%d errno=%d actual=%llu offset=%llu position_known=%u source_complete=%d full_write=%d data_fnv1a64=%016llx observation_rc=%d caller=%llx context=%llx producer=%llx media_origin_verified=0\n",
                  getpid(), sync_tid(), w->file, ticket, (unsigned long long)handle, (unsigned long long)generation,
                  w->and_flush ? "WriteAndFlush" : "Write", w->requested, original_result, original_errno,
                  (unsigned long long)(original_result >= 0 && w->requested >= original_result ? (unsigned)original_result : 0), (unsigned long long)w->offset,
                  w->position_known, source_complete, !rc && source_complete && original_result == w->requested,
                  (unsigned long long)hash, rc, (unsigned long long)w->context.caller,
                  (unsigned long long)w->context.context, (unsigned long long)w->context.producer);
        }
    }
    if (rc) sync_incomplete(ticket && ticket <= sync_write_count ? sync_writes[ticket - 1].file : 0,
                            handle, generation, rc);
    sync_leave(); errno = error;
    return rc;
}
int fsys_sync_trace_position(unsigned file, uint64_t handle, uint64_t generation,
    int original_rc, int original_errno, unsigned position_known, uint64_t position,
    struct fsys_sync_context context) {
    int error = errno, rc = 0;
    if (!sync_enter()) { errno = error; return -ESTALE; }
    struct sync_file *f = sync_identity(file, handle, generation);
    if (!f || f->closed) { rc = -ESTALE; if (f) { f->tainted = 1; f->version++; } }
    else {
        f->version++;
        if (original_rc || !position_known || f->pending) {
            rc = -ENODATA; f->tainted = 1; f->position_known = 0;
        } else { f->position = position; f->position_known = 1; }
    }
    trace("FSYS_SYNC_POSITION pid=%d tid=%ld file=%u handle=%llx generation=%llu result=%d errno=%d position_known=%u offset=%llu observation_rc=%d caller=%llx context=%llx producer=%llx\n",
          getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation, original_rc,
          original_errno, !!position_known, (unsigned long long)position, rc, (unsigned long long)context.caller,
          (unsigned long long)context.context, (unsigned long long)context.producer);
    sync_leave(); errno = error;
    return rc;
}
int fsys_sync_trace_close(unsigned file, uint64_t handle, uint64_t generation,
    int original_rc, int original_errno, struct fsys_sync_context context) {
    int error = errno, rc = 0;
    if (!sync_enter()) { errno = error; return -ESTALE; }
    struct sync_file *f = sync_identity(file, handle, generation);
    if (!f || f->closed) { rc = -ESTALE; if (f) { f->tainted = 1; f->version++; } }
    else {
        f->version++;
        if (original_rc || f->pending) { rc = -EIO; f->tainted = 1; }
        if (!original_rc) f->closed = 1;
    }
    trace("FSYS_SYNC_CLOSE pid=%d tid=%ld file=%u handle=%llx generation=%llu result=%d errno=%d closed=%u observation_rc=%d caller=%llx context=%llx producer=%llx capture_verified=0\n",
          getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation,
          original_rc, original_errno, f ? f->closed : 0, rc, (unsigned long long)context.caller,
          (unsigned long long)context.context, (unsigned long long)context.producer);
    sync_leave(); errno = error;
    return rc;
}
int fsys_sync_trace_invalidate(unsigned file, uint64_t handle, uint64_t generation, int reason) {
    int error = errno;
    if (!sync_enter()) { errno = error; return -ESTALE; }
    struct sync_file *f = sync_identity(file, handle, generation);
    if (!file) {
        if (!sync_file_count) { sync_leave(); errno = error; return -ENODATA; }
        for (unsigned i = 0; i < sync_file_count; i++) {
            sync_files[i].tainted = 1; sync_files[i].position_known = 0; sync_files[i].version++;
        }
    } else if (f) { f->tainted = 1; f->position_known = 0; f->version++; }
    sync_incomplete(file, handle, generation, reason ? reason : -ENODATA);
    sync_leave(); errno = error;
    return f || !file ? -ENODATA : -ESTALE;
}
static int sync_expected(unsigned file, uint64_t version, uint64_t offset,
                         unsigned char *expected, size_t bytes, uint16_t owners[FSYS_SYNC_CHUNK_BYTES]) {
    _Static_assert(FSYS_SYNC_WRITES <= UINT16_MAX, "contribution identity must fit");
    memset(owners, 0, bytes * sizeof *owners);
    int rc = 0;
    if (!sync_enter()) return -ESTALE;
    struct sync_file *f = &sync_files[file - 1];
    if (f->version != version || f->tainted || f->failed) rc = -ESTALE;
    for (unsigned i = 0; !rc && i < sync_write_count; i++) {
        const struct sync_write *w = &sync_writes[i];
        if (w->state != 2 || w->file != file || !w->active_bytes) continue;
        uint64_t start = w->offset > offset ? w->offset : offset;
        uint64_t end = w->offset + w->active_bytes < offset + bytes ? w->offset + w->active_bytes : offset + bytes;
        if (start >= end) continue;
        memcpy(expected + (size_t)(start - offset), w->snapshot + (size_t)(start - w->offset), (size_t)(end - start));
        for (size_t j = (size_t)(start - offset); j < (size_t)(end - offset); j++) owners[j] = (uint16_t)(i + 1);
    }
    if (!rc) for (size_t i = 0; i < bytes; i++) if (!owners[i]) { rc = -ENODATA; break; }
    sync_leave();
    return rc;
}
int fsys_sync_trace_readback(unsigned file, uint64_t handle, uint64_t generation,
    int original_flush_rc, int original_flush_errno, const struct fsys_native_read_ops *ops) {
    int error = errno, rc = 0, opened = 0, close_rc = 0, io_errno = error, eof = 0;
    uint64_t bytes = 0, hash = UINT64_C(14695981039346656037);
    unsigned long long native_handle = 0;
    struct sync_file saved = {0};
    if (!sync_enter()) { errno = error; return -ESTALE; }
    struct sync_file *f = sync_identity(file, handle, generation);
    if (!f) rc = -ESTALE;
    else if (original_flush_rc) rc = -EIO;
    else if (!ops || !ops->open || !ops->read || !ops->close) rc = -EINVAL;
    else if (!f->closed || f->pending) rc = -EAGAIN;
    else if (f->tainted || f->failed || !f->size_known || !f->size) rc = -ENODATA;
    else if (f->size > FSYS_WRITE_OBSERVATION_LIMIT) rc = -E2BIG;
    else saved = *f;
    sync_leave();
    errno = error;
    if (!rc) { rc = ops->open(saved.path, &native_handle, 1); opened = !rc; io_errno = errno; }
    while (!rc && bytes < saved.size) {
        unsigned char expected[FSYS_SYNC_CHUNK_BYTES], actual[FSYS_SYNC_CHUNK_BYTES];
        size_t want = saved.size - bytes > sizeof actual ? sizeof actual : (size_t)(saved.size - bytes);
        unsigned contributions = 0;
        uint16_t owners[FSYS_SYNC_CHUNK_BYTES];
        rc = sync_expected(file, saved.version, bytes, expected, want, owners);
        size_t done = 0;
        while (!rc && done < want) {
            int n = ops->read(native_handle, actual + done, (int)(want - done)); io_errno = errno;
            if (n <= 0 || (size_t)n > want - done) { rc = n < 0 ? n : -EIO; break; }
            for (int i = 0; i < n; i++) { hash ^= actual[done + (size_t)i]; hash *= UINT64_C(1099511628211); }
            done += (unsigned)n;
        }
        if (!rc && memcmp(expected, actual, want)) rc = -EBADMSG;
        for (size_t start = 0; start < done;) {
            size_t end = start + 1;
            while (end < done && owners[end] == owners[start]) end++;
            const struct sync_write *w = &sync_writes[owners[start] - 1];
            trace("FSYS_SYNC_CONTRIBUTION pid=%d tid=%ld file=%u handle=%llx generation=%llu ticket=%u offset=%llu bytes=%zu source_offset=%llu source_fnv1a64=%016llx data_fnv1a64=%016llx match=%d\n",
                  getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation,
                  (unsigned)owners[start], (unsigned long long)(bytes + start), end - start,
                  (unsigned long long)(bytes + start - w->offset),
                  (unsigned long long)fsys_write_fnv1a64(expected + start, end - start),
                  (unsigned long long)fsys_write_fnv1a64(actual + start, end - start),
                  !memcmp(expected + start, actual + start, end - start));
            contributions++; start = end;
        }
        trace("FSYS_SYNC_NATIVE_CHUNK pid=%d tid=%ld file=%u handle=%llx generation=%llu offset=%llu bytes=%zu actual=%zu contributions=%u expected_fnv1a64=%016llx data_fnv1a64=%016llx match=%d observation_rc=%d\n",
              getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation,
              (unsigned long long)bytes, want, done, contributions,
              (unsigned long long)(done == want ? fsys_write_fnv1a64(expected, want) : 0),
              (unsigned long long)fsys_write_fnv1a64(actual, done), !rc, rc);
        bytes += done;
    }
    if (!rc) {
        unsigned char extra;
        int n = ops->read(native_handle, &extra, 1); io_errno = errno;
        eof = !n;
        if (n) rc = n < 0 ? n : -EFBIG;
    }
    if (opened) { close_rc = ops->close(native_handle); io_errno = errno; if (!rc && close_rc) rc = close_rc; }
    if (!sync_enter()) { errno = error; return -ESTALE; }
    if (saved.version && sync_files[file - 1].version != saved.version) rc = -ESTALE;
    sync_leave();
    trace("FSYS_SYNC_NATIVE_READBACK pid=%d tid=%ld file=%u handle=%llx generation=%llu read_handle=%llx rc=%d errno=%d bytes=%llu fnv1a64=%016llx eof=%d close_rc=%d content_verified=%d flush_rc=%d flush_errno=%d capture_verified=0 media_origin_verified=0\n",
          getpid(), sync_tid(), file, (unsigned long long)handle, (unsigned long long)generation,
          native_handle, rc, io_errno, (unsigned long long)bytes, (unsigned long long)hash, eof, close_rc, !rc,
          original_flush_rc, original_flush_errno);
    errno = error;
    return rc;
}
int fsys_sync_trace_readback_all(uint64_t generation, int original_flush_rc,
    int original_flush_errno, const struct fsys_native_read_ops *ops) {
    int error = errno, rc = !generation ? -ESTALE : original_flush_rc ? -EIO : 0;
    struct { unsigned file; uint64_t handle, generation; } pending[FSYS_SYNC_FILES];
    unsigned count = 0;
    if (!sync_enter()) { errno = error; return -ESTALE; }
    for (unsigned i = 0; i < sync_file_count; i++) {
        struct sync_file *f = &sync_files[i];
        if (!generation || f->generation != generation) {
            f->tainted = 1; f->version++; rc = -ESTALE;
        }
        if (f->closed) {
            pending[count].file = i + 1;
            pending[count].handle = f->handle;
            pending[count++].generation = f->generation;
        } else if (!rc) rc = -EAGAIN;
    }
    sync_leave();
    if (!count && !rc) rc = -ENODATA;
    for (unsigned i = 0; i < count; i++) {
        errno = error;
        int result = fsys_sync_trace_readback(pending[i].file, pending[i].handle,
            pending[i].generation, original_flush_rc, original_flush_errno, ops);
        if (result) rc = result;
    }
    errno = error;
    return rc;
}
