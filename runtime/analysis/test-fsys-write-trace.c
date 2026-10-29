#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

static char logs[262144];
static size_t log_size;
static unsigned partial_read, native_opens, native_reads, native_closes;
static _Atomic unsigned memory_reads;
static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t barrier;
static int mode, fork_during_capture;
static unsigned current_file;
static unsigned char disk[8192], payload[8192];
static size_t disk_size, disk_position;
static const uint64_t handle = 0x123456789abcdef0ull, generation = 7;
static const struct fsys_sync_context context = {0x118ef0, 0xdead, 0xbeef};
extern int __real_open(const char *, int, ...), __real_close(int);
extern ssize_t __real_write(int, const void *, size_t);
extern ssize_t __real_pread(int, void *, size_t, off_t);
extern long __real_syscall(long, ...);
long __wrap_syscall(long number, ...) {
    assert(number == SYS_gettid);
    if (mode == 56) { errno = 99; return -1; }
    return __real_syscall(number);
}
int __wrap_open(const char *path, int flags, ...) {
    if (!strcmp(path, "/dev/console")) return 10000;
    return __real_open(path, flags);
}
int __wrap_close(int fd) { return fd == 10000 ? 0 : __real_close(fd); }
ssize_t __wrap_write(int fd, const void *data, size_t bytes) {
    if (fd != 10000) return __real_write(fd, data, bytes);
    assert(!pthread_mutex_lock(&log_lock));
    assert(bytes < sizeof logs - log_size);
    memcpy(logs + log_size, data, bytes); log_size += bytes; logs[log_size] = 0;
    assert(!pthread_mutex_unlock(&log_lock));
    errno = 91;
    return (ssize_t)bytes;
}
ssize_t __wrap_pread(int fd, void *out, size_t bytes, off_t offset) {
    memory_reads++;
    if (fork_during_capture) {
        fork_during_capture = 0;
        pid_t child = fork(); assert(child >= 0);
        if (!child) {
            errno = 97;
            assert(!fsys_sync_trace_file(handle, generation));
            assert(fsys_sync_trace_readback_all(generation, 0, 0, NULL) == -ESTALE && errno == 97);
            _exit(0);
        }
        int status = 0;
        assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
    if (partial_read && bytes > 1) return __real_pread(fd, out, bytes - 1, offset);
    return __real_pread(fd, out, bytes, offset);
}
static struct fsys_sync_source source(const void *data, uint64_t bytes) {
    struct fsys_sync_source s = {(uint64_t)(uintptr_t)data, bytes, 1, FSYS_SYNC_VIRTUAL};
    return s;
}
static unsigned open_file(uint64_t h, uint64_t g, const char *path, unsigned known) {
    errno = 31;
    unsigned file = fsys_sync_trace_open(path, strlen(path), h, g, 0x206, 0, 47,
                                       known, 0, mode != 42, 0, context);
    assert(file && errno == 31);
    return file;
}
static unsigned begin(struct fsys_sync_source s, int requested, unsigned flush) {
    errno = 31;
    unsigned ticket = fsys_sync_trace_write_begin(current_file, handle, generation, s, requested, flush, context);
    assert(ticket && errno == 31);
    return ticket;
}
static int end(unsigned ticket, int actual) {
    errno = 53;
    int rc = fsys_sync_trace_write_end(ticket, handle, generation, actual, 53);
    assert(errno == 53);
    return rc;
}
static int native_open(const char *path, unsigned long long *out, unsigned flags) {
    assert(!strcmp(path, "A:/PRIVATE/M4ROOT/CLIP/C0001.MP4") && flags == 1);
    if (mode == 56) assert(errno == 79);
    native_opens++; disk_position = 0; errno = 61;
    if (mode == 20) return -17;
    *out = 0x9876543210ull;
    return 0;
}
static int native_read(unsigned long long h, void *out, int want) {
    assert(h == 0x9876543210ull && want > 0 && want <= 4096);
    if (mode == 56) assert(errno == (native_reads ? 67 : 61));
    native_reads++; errno = 67;
    if (mode == 21) return -23;
    if (mode == 22) return want + 1;
    if (mode == 23 && disk_position >= 17) return 0;
    if (disk_position == disk_size) return mode == 24 ? 1 : 0;
    size_t n = disk_size - disk_position;
    if (n > (size_t)want) n = (unsigned)want;
    if (n > 997) n = 997;
    memcpy(out, disk + disk_position, n); disk_position += n;
    if (mode == 25) ((unsigned char *)out)[0] ^= 1;
    if (mode == 26) assert(fsys_sync_trace_invalidate(current_file, handle, generation, -77) < 0);
    return (int)n;
}
static int native_close(unsigned long long h) {
    assert(h == 0x9876543210ull);
    if (mode == 56) assert(errno == 67);
    native_closes++; errno = 71;
    return mode == 27 ? -31 : 0;
}
static const struct fsys_native_read_ops ops = {native_open, native_read, native_close};
static int readback(void) {
    errno = 79;
    int rc = fsys_sync_trace_readback(current_file, handle, generation, mode == 40 ? -43 : 0, 83, &ops);
    assert(errno == 79);
    return rc;
}
static void close_file(int original_rc) {
    errno = 73;
    int expected = original_rc || mode == 19 ? -EIO : 0;
    assert(fsys_sync_trace_close(current_file, handle, generation, original_rc, 73, context) == expected);
    assert(errno == 73);
}
static void invalid_sources(void) {
    struct fsys_sync_source s = source(payload, 4096);
    int expected = -ENODATA, count = 4096;
    unsigned before = memory_reads;
    if (mode == 3) s.extent_known = 0;
    else if (mode == 4) s.extent = 4095;
    else if (mode == 5) { s.domain = FSYS_SYNC_LOGICAL; expected = -ENOTSUP; }
    else if (mode == 6) { s.domain = FSYS_SYNC_PHYSICAL; expected = -ENOTSUP; }
    else if (mode == 7) { s.address = 0; expected = -EOVERFLOW; }
    else if (mode == 8) { s.address = INT64_MAX - 10; expected = -EOVERFLOW; }
    else if (mode == 9) { s.address = 1; expected = -EFAULT; }
    else if (mode == 10) { partial_read = 1; expected = -EFAULT; }
    else if (mode == 11) { count = -1; expected = -EINVAL; }
    else if (mode == 12) { count = FSYS_WRITE_OBSERVATION_LIMIT + 1; s.extent = (unsigned)count; expected = -E2BIG; }
    else assert(0);
    unsigned ticket = begin(s, count, 0);
    partial_read = 0;
    assert(end(ticket, count < 0 ? -1 : count) == (count < 0 ? -EIO : expected));
    if (mode != 3 && mode != 9 && mode != 10) assert(before == memory_reads);
    close_file(0);
    assert(readback() < 0 && !native_opens);
    if (mode == 3) {
        assert(memory_reads > before && strstr(logs, "extent_known=0"));
        assert(strstr(logs, "source_complete=1 full_write=0") && strstr(logs, "observation_rc=-61"));
        char hash[80]; snprintf(hash, sizeof hash, "data_fnv1a64=%016llx",
            (unsigned long long)fsys_write_fnv1a64(payload, 4096));
        assert(strstr(logs, hash));
    } else assert(!strstr(logs, "source_complete=1"));
    assert(!strstr(logs, "content_verified=1"));
}
struct thread_input { unsigned file; uint64_t handle; };
static void *thread_write(void *arg) {
    const struct thread_input *input = arg;
    for (unsigned i = 0; i < (mode == 55 ? 1u : 16u); i++) {
        errno = 41;
        unsigned ticket = fsys_sync_trace_write_begin(input->file, input->handle, generation,
                                                      source(payload, 4096), 4096, 0, context);
        assert(ticket && errno == 41);
        if (mode == 55) {
            int rc = pthread_barrier_wait(&barrier);
            assert(!rc || rc == PTHREAD_BARRIER_SERIAL_THREAD);
        }
        errno = 47;
        assert(!fsys_sync_trace_write_end(ticket, input->handle, generation, 4096, 47) && errno == 47);
    }
    return NULL;
}
int main(int argc, char **argv) {
    assert(argc == 2); mode = atoi(argv[1]);
    for (unsigned i = 0; i < sizeof payload; i++) payload[i] = (unsigned char)(i * 19 + 7);
    current_file = open_file(handle, generation, "A:/PRIVATE/M4ROOT/CLIP/C0001.MP4", mode != 13);
    if (mode >= 3 && mode <= 12) { invalid_sources(); return 0; }
    if (mode == 54 || mode == 55) {
        pthread_t threads[8]; struct thread_input inputs[8];
        unsigned n = mode == 55 ? 2u : 8u;
        if (mode == 55) assert(!pthread_barrier_init(&barrier, NULL, n));
        for (unsigned i = 0; i < n; i++) {
            char path[80]; snprintf(path, sizeof path, "A:/THREAD/C%04u.MP4", i);
            inputs[i].handle = mode == 55 ? handle : handle + i + 1;
            inputs[i].file = mode == 55 ? current_file : open_file(inputs[i].handle, generation, path, 1);
            assert(!pthread_create(&threads[i], NULL, thread_write, &inputs[i]));
        }
        for (unsigned i = 0; i < n; i++) assert(!pthread_join(threads[i], NULL));
        if (mode == 55) {
            assert(!pthread_barrier_destroy(&barrier)); close_file(0);
            assert(readback() < 0 && !native_opens);
        } else for (unsigned i = 0; i < n; i++)
            assert(!fsys_sync_trace_close(inputs[i].file, inputs[i].handle, generation, 0, 47, context));
        assert(strstr(logs, "FSYS_SYNC_WRITE pid=") && strstr(logs, "source_complete=1 full_write=1"));
        return 0;
    }
    if (mode == 31) {
        errno = 37;
        assert(!fsys_sync_trace_open((void *)1, 10, handle, generation, 0, 0, 0, 1, 0, 1, 0, context));
        assert(!fsys_sync_trace_open(NULL, 0, 0, 0, 0, -33, 0, 0, 0, 0, 0, context));
        assert(errno == 37 && strstr(logs, "result=-33"));
        return 0;
    }
    if (mode == 43) {
        close_file(0);
        unsigned previous = current_file;
        current_file = open_file(handle, generation, "A:/PRIVATE/M4ROOT/CLIP/C0001.MP4", 1);
        assert(previous != current_file && fsys_sync_trace_file(handle, generation) == current_file);
    } else if (mode == 44) {
        current_file = open_file(handle, generation, "A:/PRIVATE/M4ROOT/CLIP/C0001.MP4", 1);
        assert(!fsys_sync_trace_file(handle, generation));
    } else if (mode == 45) {
        for (unsigned i = 1; i < FSYS_SYNC_FILES; i++) {
            char path[80]; snprintf(path, sizeof path, "A:/CLIP/C%04u.MP4", i);
            open_file(handle + i, generation, path, 1);
        }
        assert(!fsys_sync_trace_open("A:/OVERFLOW.MP4", 15, handle + 99, generation, 0, 0, 0, 1, 0, 1, 0, context));
        assert(strstr(logs, "observation_rc=-28"));
        return 0;
    } else if (mode == 50) {
        close_file(0);
        assert(readback() == -ENODATA && !native_opens);
        return 0;
    } else if (mode == 51) {
        unsigned char *mapping = mmap(NULL, 8192, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(mapping != MAP_FAILED && !munmap(mapping + 4096, 4096));
        unsigned crossing = begin(source(mapping + 4090, 20), 20, 0);
        assert(end(crossing, 20) == -EFAULT);
        assert(!munmap(mapping, 4096)); close_file(0);
        assert(readback() < 0 && !native_opens && !strstr(logs, "source_complete=1"));
        return 0;
    } else if (mode == 53) {
        unsigned char *large = mmap(NULL, FSYS_WRITE_OBSERVATION_LIMIT, PROT_READ | PROT_WRITE,
                                   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(large != MAP_FAILED);
        unsigned full = begin(source(large, FSYS_WRITE_OBSERVATION_LIMIT), FSYS_WRITE_OBSERVATION_LIMIT, 0);
        assert(!end(full, FSYS_WRITE_OBSERVATION_LIMIT));
        unsigned before = memory_reads;
        unsigned excess = begin(source(payload, 1), 1, 0);
        assert(memory_reads == before && end(excess, 1) == -E2BIG);
        assert(!munmap(large, FSYS_WRITE_OBSERVATION_LIMIT)); close_file(0);
        assert(readback() < 0 && !native_opens);
        return 0;
    }
    assert(fsys_sync_trace_file(handle + 999, generation) == 0);
    struct fsys_sync_source input = source(payload, 4101);
    unsigned char *released = NULL;
    if (mode == 41) input.extent = UINT64_MAX;
    if (mode == 52) {
        released = mmap(NULL, 8192, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        assert(released != MAP_FAILED); memcpy(released, payload, 4101); input = source(released, 4101);
    }
    if (mode == 61) fork_during_capture = 1;
    unsigned ticket = begin(input, 4101, mode == 1);
    memcpy(disk, payload, 4101); disk_size = 4101;
    if (released) assert(!munmap(released, 8192));
    memset(payload, 0x99, 4101); /* The original can consume/release/change its input. */
    if (mode == 2) {
        assert(end(ticket, 17) == -EIO);
        char hash[96]; snprintf(hash, sizeof hash, "data_fnv1a64=%016llx",
            (unsigned long long)fsys_write_fnv1a64(disk, 17));
        assert(strstr(logs, "actual=17") && strstr(logs, hash) && strstr(logs, "full_write=0"));
    } else if (mode == 14) assert(end(ticket, -37) == -EIO);
    else if (mode == 15) assert(end(ticket, 4102) == -ERANGE);
    else if (mode == 16) {
        assert(fsys_sync_trace_write_end(ticket, handle, generation + 1, 4101, 53) == -ESTALE);
    } else if (mode == 17) {
        assert(fsys_sync_trace_write_end(ticket, handle + 1, generation, 4101, 53) == -ESTALE);
    } else if (mode == 18) {
        unsigned concurrent = begin(source(disk, 1), 1, 1);
        assert(!end(ticket, 4101)); assert(!end(concurrent, 1));
    } else if (mode == 41) assert(end(ticket, 4101) == -EOVERFLOW);
    else if (mode != 19) assert(!end(ticket, 4101));
    if (mode == 28) {
        assert(fsys_sync_trace_position(current_file, handle, generation, 0, 47, 1, 3, context) == 0);
        unsigned replacement = begin(source(payload, 7), 7, 1);
        memcpy(disk + 3, payload, 7); memset(payload, 0, 7);
        assert(!end(replacement, 7));
    } else if (mode == 29) {
        assert(!fsys_sync_trace_position(current_file, handle, generation, 0, 47, 1, 5000, context));
        unsigned hole = begin(source(payload, 1), 1, 0);
        assert(!end(hole, 1)); disk_size = 5001;
    } else if (mode == 30) {
        assert(fsys_sync_trace_position(current_file, handle, generation, 0, 47, 0, 0, context) == -ENODATA);
    } else if (mode == 32) {
        assert(end(ticket, 4101) == -EALREADY);
    } else if (mode == 33) {
        assert(fsys_sync_trace_invalidate(current_file, handle, generation, -45) == -ENODATA);
    } else if (mode == 34) {
        assert(readback() == -EAGAIN && !native_opens);
    } else if (mode == 35) {
        for (unsigned i = 1; i < FSYS_SYNC_WRITES; i++) {
            unsigned empty = begin(source(payload, 0), 0, 0); assert(!end(empty, 0));
            log_size = 0; logs[0] = 0;
        }
        unsigned reads_before = memory_reads;
        assert(!fsys_sync_trace_write_begin(current_file, handle, generation, source(payload, 1), 1, 0, context));
        assert(memory_reads == reads_before && strstr(logs, "FSYS_SYNC_INCOMPLETE"));
    } else if (mode == 36) {
        current_file = open_file(handle + 1, generation, "A:/PRIVATE/M4ROOT/CLIP/C0002.MP4", 1);
        assert(fsys_sync_trace_write_end(0, handle, generation, 1, 0) == -EINVAL);
        assert(fsys_sync_trace_close(current_file - 1, handle + 1, generation, 0, 0, context) == -ESTALE);
        return 0;
    } else if (mode == 46) {
        assert(fsys_sync_trace_invalidate(0, 0, generation, -57) == -ENODATA);
    } else if (mode == 48) {
        assert(!fsys_sync_trace_write_begin(999, handle, generation, source(payload, 1), 1, 0, context));
    } else if (mode == 49) {
        assert(fsys_sync_trace_readback(current_file, handle, generation, 0, 0, NULL) == -EINVAL);
    }
    close_file(mode == 37 ? -41 : 0);
    if (mode == 47) assert(fsys_sync_trace_close(current_file, handle, generation, 0, 0, context) == -ESTALE);
    if (mode == 19) {
        assert(end(ticket, 4101) == -ESTALE);
    } else if (mode == 38) {
        unsigned reopened = open_file(handle, generation + 1, "A:/PRIVATE/M4ROOT/CLIP/C0001.MP4", 1);
        assert(reopened != current_file);
    } else if (mode == 39) {
        assert(fsys_sync_trace_readback(current_file, handle, generation + 1, 0, 0, &ops) == -ESTALE);
    }
    int rc;
    if (mode >= 57 && mode <= 60) {
        errno = 79;
        rc = fsys_sync_trace_readback_all(mode == 60 ? 0 : generation + (mode == 58),
                                          mode == 59 ? -43 : 0, 83, &ops);
        assert(errno == 79);
    } else rc = readback();
    if (mode == 0 || mode == 1 || mode == 28 || mode == 34 || mode == 43 || mode == 49 || mode == 52 || mode == 56 || mode == 57 || mode == 61) {
        assert(!rc && native_opens == 1 && native_closes == 1 && native_reads > 1);
        char hash[96]; snprintf(hash, sizeof hash, "fnv1a64=%016llx eof=1 close_rc=0 content_verified=1",
            (unsigned long long)fsys_write_fnv1a64(disk, disk_size));
        assert(strstr(logs, hash) && strstr(logs, "capture_verified=0 media_origin_verified=0"));
        assert(strstr(logs, "result=4101 errno=53 actual=4101"));
        assert(strstr(logs, "caller=118ef0 context=dead producer=beef"));
        assert(strstr(logs, "FSYS_SYNC_CLOSE") && strstr(logs, "FSYS_SYNC_NATIVE_CHUNK"));
        if (mode == 28) {
            assert(strstr(logs, "contributions=3"));
            assert(strstr(logs, "ticket=2 offset=3 bytes=7 source_offset=0"));
            assert(strstr(logs, "ticket=1 offset=10 bytes=4086 source_offset=10"));
        }
    } else {
        assert(rc < 0 && !strstr(logs, "content_verified=1"));
        if (mode == 20) assert(rc == -17 && native_opens == 1 && !native_closes);
        else if (mode == 21) assert(rc == -23 && native_closes == 1);
        else if (mode == 22 || mode == 23) assert(rc == -EIO && native_closes == 1);
        else if (mode == 24) assert(rc == -EFBIG && native_closes == 1);
        else if (mode == 25) assert(rc == -EBADMSG && native_closes == 1);
        else if (mode == 26) assert(rc == -ESTALE && native_closes == 1);
        else if (mode == 27) assert(rc == -31 && native_closes == 1);
        else if (mode == 29) assert(rc == -ENODATA && native_closes == 1);
        else assert(!native_opens && !native_closes);
    }
    return 0;
}
