from pathlib import Path
import json
import runpy
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


def test_original_source_windows_and_callback_got_bindings():
    result = subprocess.run(['python3', '-B', str(HERE/'../../report/native-card-write/verify_source.py')],
                            capture_output=True, text=True, check=True, timeout=15)
    proof = json.loads(result.stdout)
    assert proof == {'source_verified': True, 'windows': 19, 'window_bytes': 34700,
                     'callback_got_bindings': 2, 'capture_verified': False}


def test_source_contract_rejects_duplicate_keys():
    verifier = runpy.run_path(str(HERE/'../../report/native-card-write/verify_source.py'))
    with pytest.raises(ValueError, match='duplicate source-contract key: mpr_builder'):
        json.loads('{"request":{"mpr_builder":1,"mpr_builder":2}}',
                   object_pairs_hook=verifier['unique_object'])


def test_source_closed_layout_and_real_callback_observation(tmp_path):
    source = r'''
#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
static char log_data[65536];
static size_t log_bytes;
static unsigned partial, memory_reads;
static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
extern int __real_open(const char *, int, ...);
extern ssize_t __real_write(int, const void *, size_t);
extern ssize_t __real_pread(int, void *, size_t, off_t);
int __wrap_open(const char *path, int flags, ...) {
    if (!strcmp(path, "/dev/console")) return 10000;
    return __real_open(path, flags);
}
ssize_t __wrap_write(int fd, const void *data, size_t bytes) {
    if (fd != 10000) return __real_write(fd, data, bytes);
    assert(!pthread_mutex_lock(&log_lock));
    assert(bytes < sizeof log_data - log_bytes);
    memcpy(log_data + log_bytes, data, bytes); log_bytes += bytes;
    log_data[log_bytes] = 0;
    assert(!pthread_mutex_unlock(&log_lock));
    errno = 77;
    return (ssize_t)bytes;
}
ssize_t __wrap_pread(int fd, void *data, size_t bytes, off_t offset) {
    memory_reads++;
    if (partial && bytes > 1) return __real_pread(fd, data, bytes - 1, offset);
    return __real_pread(fd, data, bytes, offset);
}
int __wrap_close(int fd) {
    if (fd == 10000) return 0;
    extern int __real_close(int);
    return __real_close(fd);
}
static void put64(unsigned char *p, uint64_t value) {
    for (unsigned i = 0; i < 8; i++) p[i] = (unsigned char)(value >> (i * 8));
}
static void put32(unsigned char *p, uint32_t value) {
    for (unsigned i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (i * 8));
}
_Alignas(4096) static unsigned char data[8192] = "native-byte-source";
static void request(unsigned char *p, uint64_t cookie) {
    memset(p, 0, FSYS_WRITE_REQUEST_BYTES);
    memcpy(p, "A:/DCIM/TEST.JPG", 16);
    put32(p + 0x410, 0x206); put32(p + 0x42c, 4101); put32(p + 0x4f0, 2);
    put64(p + 0x4f8, 0x4321); put64(p + 0x500, cookie);
    put64(p + 0x430, 0xdeadbeef); put64(p + 0x438, (uintptr_t)data); put64(p + 0x440, 4096);
    put64(p + 0x448, UINT64_MAX); put64(p + 0x450, (uintptr_t)(data + 4096)); put64(p + 0x458, 4096);
    p[0x414] = 0xa5; /* Time metadata is not a fictitious reserved-zero constraint. */
}
static void reset_log(void) { log_bytes = 0; log_data[0] = 0; }
static void decode_tests(void) {
    unsigned char p[FSYS_WRITE_REQUEST_BYTES];
    struct fsys_write_layout out;
    request(p, 0x1234);
    assert(!fsys_write_decode(p, sizeof p, &out));
    assert(out.count == 2 && out.cookie == 0x1234 && out.callback == 0x4321);
    assert(out.area[0].offset == 0 && out.area[0].address == (uintptr_t)data);
    assert(out.area[0].physical_address == 0xdeadbeef && out.address_mode == 1 && out.open_flags == 0x206);
    assert(out.area[0].bytes == 4096 && out.area[1].bytes == 5 && out.area[1].offset == 4096);
    assert(out.area[1].submitted_bytes == 4096 && out.expected_bytes == 4101 && out.payload_bytes == 4101);
    assert(!strcmp(out.path, "A:/DCIM/TEST.JPG"));
    assert(fsys_write_decode(p, sizeof p - 1, &out) == -EINVAL);
    assert(fsys_write_decode(NULL, sizeof p, &out) == -EINVAL);
    memset(p, 'X', FSYS_WRITE_PATH_BYTES);
    assert(fsys_write_decode(p, sizeof p, &out) == -ENAMETOOLONG);
    request(p, 0); p[0] = '/'; assert(fsys_write_decode(p, sizeof p, &out) == -EINVAL);
    request(p, 0); put32(p + 0x4f0, 9); assert(fsys_write_decode(p, sizeof p, &out) == -ENODATA);
    put32(p + 0x4f0, 0); assert(fsys_write_decode(p, sizeof p, &out) == -ENODATA);
    request(p, 0); put32(p + 0x42c, 0); assert(fsys_write_decode(p, sizeof p, &out) == -ENODATA);
    request(p, 0); put64(p + 0x438, 0); assert(fsys_write_decode(p, sizeof p, &out) == -ENOTSUP);
    request(p, 0); put64(p + 0x450, 0); assert(fsys_write_decode(p, sizeof p, &out) == -EINVAL);
    request(p, 0); put64(p + 0x438, (uintptr_t)data + 1); assert(fsys_write_decode(p, sizeof p, &out) == -EINVAL);
    request(p, 0); put64(p + 0x438, UINT64_C(0x7ffffffffffff000)); assert(fsys_write_decode(p, sizeof p, &out) == -EOVERFLOW);
    request(p, 0); put64(p + 0x440, UINT64_MAX - 4095); assert(fsys_write_decode(p, sizeof p, &out) == -EOVERFLOW);
    request(p, 0); put32(p + 0x42c, 8193); assert(fsys_write_decode(p, sizeof p, &out) == -ENODATA);
    request(p, 0); put32(p + 0x42c, FSYS_WRITE_OBSERVATION_LIMIT + 1);
    put64(p + 0x440, FSYS_WRITE_OBSERVATION_LIMIT);
    assert(fsys_write_decode(p, sizeof p, &out) == -E2BIG);
    request(p, 0); put32(p + 0x42c, 1); assert(!fsys_write_decode(p, sizeof p, &out));
    assert(out.area[0].bytes == 1 && out.area[1].bytes == 0 && out.area[1].offset == 4096);
    request(p, 0); put64(p + 0x440, 0); put32(p + 0x42c, 1);
    assert(!fsys_write_decode(p, sizeof p, &out) && !out.area[0].bytes && out.area[1].bytes == 1);
    assert(fsys_write_fnv1a64("hello", 5) == UINT64_C(0xa430d84680aabd0b));
}
static void observation_tests(void) {
    unsigned char p[FSYS_WRITE_REQUEST_BYTES], before[FSYS_WRITE_REQUEST_BYTES];
    unsigned char result[FSYS_WRITE_RESULT_BYTES] = {0};
    request(p, 0x1234); memcpy(before, p, sizeof p);
    unsetenv("A7C2_FSYS_ASYNC_OBSERVE"); errno = 31;
    assert(!fsys_write_trace_begin(p) && errno == 31 && !memory_reads && !log_bytes);
    setenv("A7C2_FSYS_ASYNC_OBSERVE", "yes", 1);
    assert(!fsys_write_trace_begin(p) && !memory_reads && !log_bytes);
    setenv("A7C2_FSYS_ASYNC_OBSERVE", "1", 1);
    unsigned token = fsys_write_trace_begin(p);
    assert(token == 1 && errno == 31 && memory_reads == 2);
    assert(!memcmp(p, before, sizeof p));
    assert(strstr(log_data, "observation_rc=0") && strstr(log_data, "payload_complete=1"));
    assert(strstr(log_data, "path_hex=413a2f4443494d2f544553542e4a5047"));
    assert(strstr(log_data, "index=0 offset=0 bytes=4096") && strstr(log_data, "index=1 offset=4096 bytes=5"));
    assert(strstr(log_data, "expected_bytes=4101 address_mode=1 open_flags=518"));
    assert(strstr(log_data, "submitted_bytes=4096"));
    fsys_write_trace_callback((void *)0x1234, 0, result, 0x4321);
    assert(errno == 31 && strstr(log_data, "token=1 cookie=0x1234 rc=0 result_copied=1"));
    fsys_write_trace_submit(token, 0); assert(strstr(log_data, "rc=0 callback_seen=1"));
    unsigned char *work = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(work != MAP_FAILED); put64(work, 0x1234); put32(work + 8, 0);
    struct fsys_write_finished finished = fsys_write_trace_finished_begin(work);
    assert(finished.token == 1 && finished.cookie == 0x1234 && finished.input_copied);
    assert(!mprotect(work, 4096, PROT_NONE)); /* Original MPR can free its input/context. */
    fsys_write_trace_finished_return(finished);
    assert(errno == 31 && strstr(log_data, "input_copied=1 returned=1 duplicate=0"));
    fsys_write_trace_callback((void *)0x1234, -7, result, 0x4321);
    assert(strstr(log_data, "rc=-7 result_copied=1") && strstr(log_data, "duplicate=1"));
    fsys_write_trace_callback((void *)0x1234, 0, result, 0x9999);
    assert(strstr(log_data, "token=0 cookie=0x1234"));
    assert(!munmap(work, 4096));
    reset_log(); request(p, 0x2234); partial = 1;
    assert(fsys_write_trace_begin(p) == 2); partial = 0;
    assert(strstr(log_data, "observation_rc=-14") && strstr(log_data, "payload_complete=0"));
    assert(strstr(log_data, "data_fnv1a64=0000000000000000 readable=0"));
    reset_log(); request(p, 0x3234); put64(p + 0x438, 4096);
    assert(fsys_write_trace_begin(p) == 3 && strstr(log_data, "payload_complete=0"));
    reset_log(); request(p, 0x1234); assert(fsys_write_trace_begin(p) == 4);
    fsys_write_trace_callback((void *)0x1234, 0, result, 0x4321);
    assert(strstr(log_data, "MPR_WRITE_CALLBACK") && strstr(log_data, "token=0 cookie=0x1234"));
    fsys_write_trace_callback((void *)0x3234, 0, (void *)1, 0x4321);
    assert(strstr(log_data, "token=3 cookie=0x3234 rc=0 result_copied=0"));
}
static unsigned tokens[40];
static void *concurrent(void *arg) {
    unsigned i = (unsigned)(uintptr_t)arg;
    unsigned char p[FSYS_WRITE_REQUEST_BYTES]; request(p, i + 0x4000);
    put32(p + 0x4f0, 0); /* no I/O/hash needed for a failing source */
    tokens[i] = fsys_write_trace_begin(p);
    return NULL;
}
int main(void) {
    decode_tests(); observation_tests();
    pthread_t threads[40];
    for (unsigned i = 0; i < 40; i++) assert(!pthread_create(&threads[i], NULL, concurrent, (void *)(uintptr_t)i));
    unsigned seen[33] = {0}, accepted = 0;
    for (unsigned i = 0; i < 40; i++) {
        assert(!pthread_join(threads[i], NULL));
        if (tokens[i]) { assert(tokens[i] <= 32 && !seen[tokens[i]]++); accepted++; }
    }
    assert(accepted == 28); /* Four prior records plus 28 unique concurrent admissions. */
    unsigned reads = memory_reads; size_t bytes = log_bytes;
    unsigned char p[FSYS_WRITE_REQUEST_BYTES]; request(p, 123);
    assert(!fsys_write_trace_begin(p) && reads == memory_reads && log_bytes > bytes);
    assert(strstr(log_data + bytes, "FSYS_WRITE_COVERAGE_INCOMPLETE"));
    return 0;
}
'''
    fixture = tmp_path / 'write-trace.c'
    fixture.write_text(source)
    binary = tmp_path / 'write-trace'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                    '-pthread', '-I', str(HERE), str(fixture), str(HERE / 'fsys-write-trace.c'),
                    '-Wl,--wrap=open,--wrap=write,--wrap=pread,--wrap=close', '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)


def test_native_readback_uses_real_read_results_and_requires_all_completions(tmp_path):
    fixture = tmp_path / 'native-readback.c'
    fixture.write_text(r'''
#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static char logs[16384]; static size_t used;
extern int __real_open(const char *, int, ...), __real_close(int);
extern ssize_t __real_write(int, const void *, size_t);
int __wrap_open(const char *path, int flags, ...) {
    return !strcmp(path, "/dev/console") ? 10000 : __real_open(path, flags);
}
int __wrap_close(int fd) { return fd == 10000 ? 0 : __real_close(fd); }
ssize_t __wrap_write(int fd, const void *data, size_t bytes) {
    if (fd != 10000) return __real_write(fd, data, bytes);
    assert(bytes < sizeof logs - used); memcpy(logs + used, data, bytes); used += bytes;
    logs[used] = 0; errno = 99; return (ssize_t)bytes;
}
_Alignas(4096) static unsigned char data[8192];
static unsigned char request[FSYS_WRITE_REQUEST_BYTES];
static int mode, opens, reads, closes; static unsigned position;
static void put64(unsigned char *p, uint64_t value) {
    for (unsigned i = 0; i < 8; i++) p[i] = (unsigned char)(value >> (i * 8));
}
static void put32(unsigned char *p, uint32_t value) {
    for (unsigned i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (i * 8));
}
static int native_open(const char *path, unsigned long long *handle, unsigned flags) {
    assert(!strcmp(path, "A:/DCIM/REAL.JPG") && flags == 1); opens++;
    if (mode == 8) return -5;
    if (mode == 12) assert(fsys_write_trace_begin(request) == 2);
    *handle = 77; errno = 81; return 0;
}
static int native_read(unsigned long long handle, void *out, int want) {
    assert(handle == 77 && want > 0 && want <= 4096); reads++;
    if (mode == 5 && position) return -7;
    if (mode == 6) return want + 1;
    unsigned size = mode == 4 ? 10u : 4101u;
    if (position >= size) return mode == 7 ? 1 : 0;
    unsigned actual = size - position;
    if (actual > (unsigned)want) actual = (unsigned)want;
    if (actual > 997) actual = 997; /* Repeated positive short reads must continue. */
    memcpy(out, data + position, actual); position += actual; errno = 82; return (int)actual;
}
static int native_close(unsigned long long handle) {
    assert(handle == 77); closes++; errno = 83; return mode == 9 ? -6 : 0;
}
int main(int argc, char **argv) {
    assert(argc == 2); mode = atoi(argv[1]);
    for (unsigned i = 0; i < sizeof data; i++) data[i] = (unsigned char)(i * 7);
    memcpy(request, "A:/DCIM/REAL.JPG", 16);
    put32(request + 0x410, 0x206); put32(request + 0x42c, 4101); put32(request + 0x4f0, 2);
    put64(request + 0x430, 0x1234000); put64(request + 0x438, (uintptr_t)data); put64(request + 0x440, 4096);
    put64(request + 0x448, 0x1235000); put64(request + 0x450, (uintptr_t)(data + 4096)); put64(request + 0x458, 4096);
    put64(request + 0x4f8, 0x4321); put64(request + 0x500, 0x1234);
    setenv("A7C2_FSYS_ASYNC_OBSERVE", "1", 1); errno = 31;
    unsigned token = fsys_write_trace_begin(request); assert(token == 1 && errno == 31);
    unsigned char result[FSYS_WRITE_RESULT_BYTES] = {0}, work[24] = {0};
    int status = mode == 3 ? -17 : 0;
    if (mode != 1) {
        assert(fsys_write_trace_callback((void *)0x1234, status, result, 0x4321) == 1);
        put64(work, 0x1234); put32(work + 8, (uint32_t)status);
        fsys_write_trace_finished_return(fsys_write_trace_finished_begin(work));
        if (mode != 2) fsys_write_trace_callback_return(token);
    }
    fsys_write_trace_submit(token, 0);
    if (mode == 10) fsys_write_trace_unobserved();
    struct fsys_native_read_ops ops = { native_open, native_read, native_close };
    errno = 31; int rc = fsys_write_trace_readback(&ops); assert(errno == 31);
    if (mode == 1 || mode == 2 || mode == 3 || mode == 10) {
        assert(rc < 0 && !opens && !reads && !closes);
    } else if (mode == 8) {
        assert(rc == -5 && opens == 1 && !reads && !closes);
    } else {
        assert(opens == 1 && closes == 1);
        if (!mode) {
            assert(!rc && reads == 6 && strstr(logs, "rc=0 bytes=4101"));
            char expected[80]; snprintf(expected, sizeof expected, "fnv1a64=%016llx eof=1 close_rc=0",
                (unsigned long long)fsys_write_fnv1a64(data, 4101));
            assert(strstr(logs, expected) && strstr(logs, "records=1 rc=0"));
        } else if (mode == 4) assert(rc == -EIO && position == 10);
        else if (mode == 5) assert(rc == -7);
        else if (mode == 6) assert(rc == -EIO);
        else if (mode == 7) assert(rc == -EFBIG);
        else if (mode == 9) assert(rc == -6);
        else if (mode == 12) assert(rc == -EAGAIN && strstr(logs, "records=1 rc=-11"));
        else assert(0);
    }
    return 0;
}
''')
    binary = tmp_path / 'native-readback'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
                    '-I', str(HERE), str(fixture), str(HERE / 'fsys-write-trace.c'),
                    '-Wl,--wrap=open,--wrap=write,--wrap=close', '-o', str(binary)], check=True)
    for mode in (*range(11), 12):
        subprocess.run([str(binary), str(mode)], check=True, timeout=10)


@pytest.mark.parametrize('sanitized', [False, True], ids=['strict-c11', 'asan-ubsan'])
def test_sync_source_freeze_lifecycle_and_native_content(tmp_path, sanitized):
    binary = tmp_path / 'sync-write-trace'
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
    if sanitized:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    subprocess.run(['cc', *flags, '-I', str(HERE), str(HERE / 'test-fsys-write-trace.c'),
                    str(HERE / 'fsys-write-trace.c'),
                    '-Wl,--wrap=open,--wrap=write,--wrap=pread,--wrap=close,--wrap=syscall', '-o', str(binary)], check=True)
    for mode in range(62):
        result = subprocess.run([str(binary), str(mode)], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0, f'mode={mode}\n{result.stdout}\n{result.stderr}'


def test_sync_public_movie_and_fsys_abi_pins():
    verifier = HERE / '../../report/native-movie-write-trace/verify_source.py'
    result = subprocess.run(['python3', '-B', str(verifier)], capture_output=True,
                            text=True, check=True, timeout=15)
    proof = json.loads(result.stdout)
    assert proof['source_verified'] and proof['capture_verified'] is False
    assert proof['windows'] == 8 and proof['sync_plt_bindings'] == 5
