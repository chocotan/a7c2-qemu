#define _POSIX_C_SOURCE 200809L
#include "sd-state.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

typedef struct {
    sd_core core;
    sd_adapters adapters;
    sd_backing backing;
    bool guard_ok, backing_ok, quiescence_ok, fast_free, fast_fs, allocation_fail;
    unsigned sends, validations, quiescences;
    unsigned allocation_attempts, send_attempts;
    sd_send_result send_result;
    sd_observation queued[2];
    unsigned queued_count;
    char path[40];
    unsigned char original[4096];
    uint8_t last_payload[7];
} fixture;

static sd_observation obs(uint64_t gen, sd_observation_kind kind, uint32_t drive)
{
    return (sd_observation){ .generation = gen, .kind = kind, .drive = drive,
        .genuine = true, .path_validated = true, .owned = true };
}

static bool guarded(void *p) { return ((fixture *)p)->guard_ok; }

static bool backing_valid(void *p, const sd_backing *b)
{
    fixture *f = p;
    ++f->validations;
    struct stat st;
    unsigned char buf[sizeof(f->original)];
    return f->backing_ok && b->fd == f->backing.fd &&
        fstat(b->fd, &st) == 0 && (uint64_t)st.st_ino == b->identity &&
        (uint64_t)st.st_size == b->size && b->size == sizeof(buf) &&
        pread(b->fd, buf, sizeof(buf), 0) == (ssize_t)sizeof(buf) &&
        memcmp(buf, f->original, sizeof(buf)) == 0;
}

static bool quiescent(void *p, uint64_t gen, uint32_t drive)
{
    fixture *f = p;
    assert(gen == f->core.generation + 1);
    assert(drive == f->core.drive && drive != 0);
    assert(f->core.state == SD_PRESENT);
    ++f->quiescences;
    return f->quiescence_ok;
}

static void queue(fixture *f, sd_observation o)
{
    assert(f->queued_count < 2);
    /* Reentrant processing is rejected; the adapter retains and queues it. */
    assert(sd_observe(&f->core, o) == SD_BUSY);
    f->queued[f->queued_count++] = o;
}

static sd_send_result notify(void *p, uint64_t gen, sd_operation op,
                             const uint8_t data[7])
{
    fixture *f = p;
    assert(f->core.state == (op == SD_EJECT ? SD_EJECTING : SD_INSERTING));
    assert(f->core.present == (op == SD_INSERT));
    assert(gen == f->core.generation);
    if (op == SD_EJECT) assert(f->quiescences);
    sd_snapshot s;
    assert(sd_snapshot_read(&f->core, &s) == SD_BUSY);
    assert(sd_request_apply(&f->core, (sd_request){99, op}) == SD_BUSY);
    assert(sd_expire(&f->core, (sd_timeout){gen}) == SD_BUSY);
    memcpy(f->last_payload, data, 7);
    assert(data[0] == 2 && data[1] == 0 && data[2] == 0 && data[3] == 2 &&
        data[4] == 0 && data[6] == 0);
    assert(data[5] == ((f->core.remove_count << 4) | (op == SD_INSERT ? 2 : 0)));
    ++f->sends;
    ++f->allocation_attempts;
    if (f->allocation_fail) return (sd_send_result){SD_NOT_SENT, false};
    ++f->send_attempts;
    if (f->fast_free) queue(f, obs(gen, SD_NOTIFY_FREE, 0));
    if (f->fast_fs) queue(f, obs(gen, op == SD_EJECT ? SD_UNMOUNT : SD_MOUNT,
                               op == SD_EJECT ? f->core.drive : 8));
    sd_send_result result = f->send_result;
    result.observable_ack |= f->queued_count != 0;
    return result;
}

static void prepare(fixture *f)
{
    *f = (fixture){ .guard_ok = true, .backing_ok = true,
        .quiescence_ok = true, .send_result = {SD_SENT, false} };
    strcpy(f->path, "./sentinel-XXXXXX");
    int fd = mkstemp(f->path);
    assert(fd >= 0);
    for (size_t i = 0; i < sizeof(f->original); ++i)
        f->original[i] = (unsigned char)(i * 37 + 19);
    assert(write(fd, f->original, sizeof(f->original)) == sizeof(f->original));
    assert(lseek(fd, 123, SEEK_SET) == 123);
    struct stat st;
    assert(fstat(fd, &st) == 0);
    f->backing = (sd_backing){fd, (uint64_t)st.st_ino, sizeof(f->original)};
    f->adapters = (sd_adapters){f, guarded, backing_valid, quiescent, notify};
}

static sd_observation initial(void) { return obs(10, SD_MOUNT, 7); }

static void init(fixture *f)
{
    prepare(f);
    sd_observation mount = initial();
    assert(sd_bind(&f->core, &f->adapters, &f->backing, &mount) == SD_OK);
}

static sd_snapshot snapshot(fixture *f)
{
    sd_snapshot s;
    assert(sd_snapshot_read(&f->core, &s) == SD_OK);
    return s;
}

static void finish(fixture *f)
{
    struct stat path_st, fd_st;
    assert(stat(f->path, &path_st) == 0);
    assert(fstat(f->backing.fd, &fd_st) == 0);
    assert(path_st.st_ino == fd_st.st_ino && path_st.st_dev == fd_st.st_dev);
    assert((uint64_t)fd_st.st_ino == f->backing.identity);
    assert((uint64_t)fd_st.st_size == f->backing.size && fd_st.st_nlink == 1);
    assert(lseek(f->backing.fd, 0, SEEK_CUR) == 123);
    unsigned char buf[sizeof(f->original)];
    assert(pread(f->backing.fd, buf, sizeof(buf), 0) == (ssize_t)sizeof(buf));
    assert(memcmp(buf, f->original, sizeof(buf)) == 0);
    if (f->core.bound) {
        assert(f->core.backing.fd == f->backing.fd);
        assert(f->core.backing.identity == f->backing.identity);
        assert(f->core.backing.size == f->backing.size);
    }
    assert(close(f->backing.fd) == 0);
    assert(unlink(f->path) == 0);
}

static sd_result request(fixture *f, uint64_t seq, sd_operation op)
{ return sd_request_apply(&f->core, (sd_request){seq, op}); }

static void ack_pair(fixture *f, bool free_first)
{
    sd_core *c = &f->core;
    sd_observation fs = obs(c->generation,
        c->operation == SD_EJECT ? SD_UNMOUNT : SD_MOUNT,
        c->operation == SD_EJECT ? c->drive : 8);
    sd_observation release = obs(c->generation, SD_NOTIFY_FREE, 0);
    assert(sd_observe(c, free_first ? release : fs) == SD_PENDING);
    assert(c->state == (c->operation == SD_EJECT ? SD_EJECTING : SD_INSERTING));
    assert(sd_observe(c, free_first ? fs : release) == SD_OK);
    assert(sd_observe(c, fs) == SD_DUPLICATE);
    assert(sd_observe(c, release) == SD_DUPLICATE);
}

static void test_binding(void)
{
    fixture f;
    prepare(&f);
    sd_observation m = initial();
    sd_snapshot s;
    assert(sd_snapshot_read(&f.core, &s) == SD_UNBOUND);
    assert(sd_bind(&f.core, NULL, &f.backing, &m) == SD_INVALID);
    f.guard_ok = false;
    assert(sd_bind(&f.core, &f.adapters, &f.backing, &m) == SD_GUARD_FAILED);
    f.guard_ok = true;
    f.backing_ok = false;
    assert(sd_bind(&f.core, &f.adapters, &f.backing, &m) == SD_BACKING_FAILED);
    f.backing_ok = true;
    for (unsigned i = 0; i < 6; ++i) {
        m = initial();
        if (i == 0) m.drive = 0;
        if (i == 1) m.rc = -1;
        if (i == 2) m.genuine = false;
        if (i == 3) m.path_validated = false;
        if (i == 4) m.generation = 0;
        if (i == 5) m.kind = SD_UNMOUNT;
        assert(sd_bind(&f.core, &f.adapters, &f.backing, &m) == SD_INVALID);
        assert(sd_snapshot_read(&f.core, &s) == SD_UNBOUND);
    }
    m = initial();
    sd_adapters a = f.adapters;
    a.validate_quiescence = NULL;
    assert(sd_bind(&f.core, &a, &f.backing, &m) == SD_INVALID);
    assert(sd_bind(&f.core, &f.adapters, &f.backing, &m) == SD_OK);
    assert(sd_bind(&f.core, &f.adapters, &f.backing, &m) == SD_CONFLICT);
    const uint8_t present[7] = {2, 0, 0, 2, 0, 2, 0};
    s = snapshot(&f);
    assert(s.state == SD_PRESENT && memcmp(s.bytes, present, 7) == 0);
    finish(&f);
}

static void test_order_retry_wrap(void)
{
    fixture f;
    init(&f);
    assert(request(&f, 0, SD_EJECT) == SD_INVALID);
    assert(request(&f, 1, SD_INSERT) == SD_ALREADY);
    assert(request(&f, 2, SD_EJECT) == SD_PENDING);
    assert(request(&f, 2, SD_EJECT) == SD_DUPLICATE);
    assert(request(&f, 2, SD_INSERT) == SD_CONFLICT);
    assert(request(&f, 1, SD_EJECT) == SD_STALE);
    assert(request(&f, 3, SD_EJECT) == SD_PENDING);
    assert(request(&f, 4, SD_INSERT) == SD_BUSY);
    assert(f.sends == 1 && f.core.generation == 11);
    ack_pair(&f, true);
    assert(f.core.state == SD_ABSENT && f.core.drive == 0);
    assert(snapshot(&f).bytes[5] == 0x10);
    assert(request(&f, 5, SD_EJECT) == SD_ALREADY);
    assert(request(&f, 6, SD_INSERT) == SD_PENDING);
    ack_pair(&f, false);
    assert(f.core.state == SD_PRESENT && f.core.drive == 8);
    assert(snapshot(&f).bytes[5] == 0x12);
    uint64_t seq = 7;
    for (unsigned i = 1; i < 17; ++i) {
        assert(request(&f, seq++, SD_EJECT) == SD_PENDING);
        ack_pair(&f, i & 1);
        assert(snapshot(&f).bytes[5] == (((i + 1) & 15) << 4));
        assert(request(&f, seq++, SD_INSERT) == SD_PENDING);
        ack_pair(&f, !(i & 1));
        assert(snapshot(&f).bytes[5] == ((((i + 1) & 15) << 4) | 2));
    }
    finish(&f);
}

static void test_validation(void)
{
    fixture f;
    init(&f);
    f.guard_ok = false;
    assert(request(&f, 1, SD_EJECT) == SD_GUARD_FAILED);
    assert(sd_observe(&f.core, obs(10, SD_NOTIFY_FREE, 0)) == SD_GUARD_FAILED);
    assert(sd_expire(&f.core, (sd_timeout){10}) == SD_GUARD_FAILED);
    sd_snapshot s;
    assert(sd_snapshot_read(&f.core, &s) == SD_GUARD_FAILED);
    f.guard_ok = true;
    f.quiescence_ok = false;
    assert(request(&f, 1, SD_EJECT) == SD_QUIESCENCE_FAILED);
    assert(request(&f, 1, SD_EJECT) == SD_DUPLICATE);
    assert(f.quiescences == 1);
    assert(f.sends == 0 && f.core.generation == 10 && snapshot(&f).bytes[5] == 2);
    f.quiescence_ok = true;
    f.backing_ok = false;
    assert(request(&f, 2, SD_EJECT) == SD_BACKING_FAILED);
    assert(f.sends == 0 && f.core.state == SD_PRESENT);
    f.backing_ok = true;
    assert(request(&f, 3, SD_EJECT) == SD_PENDING);
    ack_pair(&f, false);
    f.backing_ok = false;
    assert(request(&f, 4, SD_INSERT) == SD_BACKING_FAILED);
    assert(f.sends == 1 && f.core.state == SD_ABSENT && snapshot(&f).bytes[5] == 16);
    f.backing_ok = true;
    finish(&f);
}

static void test_send_failures(void)
{
    fixture allocation;
    init(&allocation);
    allocation.allocation_fail = true;
    assert(request(&allocation, 1, SD_EJECT) == SD_ROLLED_BACK);
    assert(allocation.allocation_attempts == 1 && allocation.send_attempts == 0);
    assert(allocation.core.state == SD_PRESENT && snapshot(&allocation).bytes[5] == 2);
    allocation.allocation_fail = false;
    assert(request(&allocation, 2, SD_EJECT) == SD_PENDING);
    assert(allocation.core.generation == 12 && allocation.send_attempts == 1);
    assert(sd_observe(&allocation.core, obs(11, SD_UNMOUNT, 7)) == SD_STALE);
    ack_pair(&allocation, false);
    finish(&allocation);
    for (unsigned mode = 0; mode < 4; ++mode) {
        fixture f;
        init(&f);
        f.send_result = (sd_send_result){mode == 2 ? SD_DELIVERY_UNCERTAIN : SD_NOT_SENT,
                                       mode == 3};
        f.fast_free = mode == 1;
        assert(request(&f, 1, SD_EJECT) == (mode == 0 ? SD_ROLLED_BACK : SD_UNCERTAIN));
        assert(f.core.state == (mode == 0 ? SD_PRESENT : SD_FAILED_UNCERTAIN));
        assert(snapshot(&f).bytes[5] == (mode == 0 ? 2 : 16));
        unsigned sends = f.sends;
        assert(f.allocation_attempts == 1 && f.send_attempts == 1);
        assert(request(&f, 1, SD_EJECT) == (mode == 0 ? SD_DUPLICATE : SD_UNCERTAIN));
        assert(f.sends == sends);
        if (mode == 0) {
            /* A supposedly impossible late ack invalidates the no-transfer claim. */
            assert(sd_observe(&f.core, obs(11, SD_NOTIFY_FREE, 0)) == SD_UNCERTAIN);
            assert(snapshot(&f).bytes[5] == 2);
            assert(request(&f, 1, SD_EJECT) == SD_UNCERTAIN);
        } else {
            assert(sd_observe(&f.core, obs(11, SD_UNMOUNT, 7)) == SD_UNCERTAIN);
            assert(request(&f, 2, SD_INSERT) == SD_UNCERTAIN);
        }
        finish(&f);
    }
    fixture f;
    init(&f);
    assert(request(&f, 1, SD_EJECT) == SD_PENDING);
    ack_pair(&f, false);
    f.send_result.delivery = SD_NOT_SENT;
    assert(request(&f, 2, SD_INSERT) == SD_ROLLED_BACK);
    assert(f.core.state == SD_ABSENT && snapshot(&f).bytes[5] == 16);
    f.send_result.delivery = SD_DELIVERY_UNCERTAIN;
    assert(request(&f, 3, SD_INSERT) == SD_UNCERTAIN);
    assert(snapshot(&f).bytes[5] == 18);
    finish(&f);
}

static void test_stale_wrong_drive_fast(void)
{
    fixture f;
    init(&f);
    f.fast_free = true;
    assert(request(&f, 1, SD_EJECT) == SD_PENDING);
    assert(f.core.state == SD_EJECTING && f.queued_count == 1);
    assert(sd_observe(&f.core, f.queued[0]) == SD_PENDING);
    assert(sd_observe(&f.core, obs(10, SD_UNMOUNT, 7)) == SD_STALE);
    assert(sd_observe(&f.core, obs(12, SD_UNMOUNT, 7)) == SD_STALE);
    assert(sd_observe(&f.core, obs(11, SD_UNMOUNT, 9)) == SD_MISMATCH);
    assert(f.core.state == SD_EJECTING);
    assert(sd_observe(&f.core, obs(11, SD_UNMOUNT, 7)) == SD_OK);
    f.queued_count = 0;
    f.fast_fs = true;
    assert(request(&f, 2, SD_INSERT) == SD_PENDING);
    assert(f.core.state == SD_INSERTING && f.queued_count == 2);
    assert(sd_observe(&f.core, obs(11, SD_UNMOUNT, 7)) == SD_STALE);
    assert(sd_observe(&f.core, f.queued[1]) == SD_PENDING);
    assert(f.core.state == SD_INSERTING);
    assert(sd_observe(&f.core, f.queued[0]) == SD_OK);
    assert(f.core.state == SD_PRESENT && f.core.drive == 8);
    finish(&f);
}

static void test_observation_errors(void)
{
    for (unsigned mode = 0; mode < 7; ++mode) {
        fixture f;
        init(&f);
        assert(request(&f, 1, SD_EJECT) == SD_PENDING);
        if (mode < 4) {
            ack_pair(&f, false);
            assert(request(&f, 2, SD_INSERT) == SD_PENDING);
        }
        sd_observation o = obs(f.core.generation,
            mode < 4 ? SD_MOUNT : SD_NOTIFY_FREE, 8);
        if (mode == 0 || mode == 4) o.rc = -5;
        if (mode == 1) o.path_validated = false;
        if (mode == 2) o.drive = 0;
        if (mode == 3) o.genuine = false;
        if (mode == 5) o.owned = false;
        if (mode == 6) { o.kind = SD_UNMOUNT; o.drive = 7; o.rc = -7; }
        bool mismatch = mode == 3 || mode == 5;
        assert(sd_observe(&f.core, o) == (mismatch ? SD_MISMATCH : SD_UNCERTAIN));
        if (mismatch)
            assert(sd_expire(&f.core, (sd_timeout){f.core.generation}) == SD_UNCERTAIN);
        assert(f.core.state == SD_FAILED_UNCERTAIN);
        assert(snapshot(&f).bytes[5] == (mode < 4 ? 18 : 16));
        assert(sd_observe(&f.core, obs(f.core.generation, SD_NOTIFY_FREE, 0)) == SD_UNCERTAIN);
        finish(&f);
    }
}

static void test_deadlines_and_late_errors(void)
{
    for (unsigned mode = 0; mode < 4; ++mode) {
        fixture f;
        init(&f);
        assert(request(&f, 1, SD_EJECT) == SD_PENDING);
        if (mode == 1) assert(sd_observe(&f.core, obs(11, SD_UNMOUNT, 7)) == SD_PENDING);
        if (mode == 2) assert(sd_observe(&f.core, obs(11, SD_NOTIFY_FREE, 0)) == SD_PENDING);
        if (mode == 3) {
            ack_pair(&f, true);
            assert(request(&f, 2, SD_INSERT) == SD_PENDING);
        }
        uint64_t gen = f.core.generation;
        assert(sd_expire(&f.core, (sd_timeout){gen - 1}) == SD_STALE);
        assert(sd_expire(&f.core, (sd_timeout){gen}) == SD_UNCERTAIN);
        assert(sd_expire(&f.core, (sd_timeout){gen}) == SD_UNCERTAIN);
        assert(sd_observe(&f.core, obs(gen, mode == 3 ? SD_MOUNT : SD_UNMOUNT,
                                      mode == 3 ? 8 : 7)) == SD_UNCERTAIN);
        assert(snapshot(&f).bytes[5] == (mode == 3 ? 18 : 16));
        finish(&f);
    }
    fixture f;
    init(&f);
    assert(request(&f, 1, SD_EJECT) == SD_PENDING);
    ack_pair(&f, false);
    assert(sd_expire(&f.core, (sd_timeout){11}) == SD_ALREADY);
    sd_observation error = obs(11, SD_NOTIFY_FREE, 0);
    error.rc = -1;
    assert(sd_observe(&f.core, error) == SD_UNCERTAIN);
    assert(snapshot(&f).bytes[5] == 16);
    finish(&f);
}

static void test_exhaustion(void)
{
    fixture f;
    prepare(&f);
    sd_observation m = initial();
    m.generation = UINT64_MAX;
    assert(sd_bind(&f.core, &f.adapters, &f.backing, &m) == SD_OK);
    assert(request(&f, UINT64_MAX, SD_EJECT) == SD_EXHAUSTED);
    assert(request(&f, UINT64_MAX, SD_EJECT) == SD_DUPLICATE);
    assert(request(&f, UINT64_MAX - 1, SD_EJECT) == SD_STALE);
    assert(f.sends == 0 && f.core.state == SD_PRESENT);
    finish(&f);
    init(&f);
    assert(request(&f, UINT64_MAX, SD_EJECT) == SD_PENDING);
    ack_pair(&f, true);
    assert(request(&f, 0, SD_INSERT) == SD_INVALID);
    assert(request(&f, UINT64_MAX, SD_INSERT) == SD_CONFLICT);
    assert(request(&f, UINT64_MAX - 1, SD_INSERT) == SD_STALE);
    assert(f.sends == 1 && f.core.state == SD_ABSENT && f.core.generation == 11);
    finish(&f);
}

int main(void)
{
    test_binding();
    test_order_retry_wrap();
    test_validation();
    test_send_failures();
    test_stale_wrong_drive_fast();
    test_observation_errors();
    test_deadlines_and_late_errors();
    test_exhaustion();
    puts("PASS: 8 groups; bind, ack permutations, retries, wrap, guards, sends, stale/fast, errors, deadlines, sentinel");
    return 0;
}
