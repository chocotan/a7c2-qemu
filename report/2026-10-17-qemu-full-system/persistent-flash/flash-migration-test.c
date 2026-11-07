/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#define A7PF_MIGRATION_TEST
#include "flash-qemu.c"
#include <assert.h>

static int sync_failure, read_failure, short_read, drift, checks;
static uint8_t ram[A7PF_MAX_IO];
ssize_t __real_pread(int fd, void *buf, size_t count, off_t offset);
int __real_fdatasync(int fd);
ssize_t __wrap_pread(int fd, void *buf, size_t count, off_t offset)
{
    if (read_failure) { errno = EACCES; return -1; }
    if (short_read) { short_read = 0; return 0; }
    ssize_t got = __real_pread(fd, buf, count, offset);
    if (drift) {
        struct stat st;
        struct timespec ts[2];
        assert(!fstat(fd, &st));
        uint8_t old, changed;
        assert(__real_pread(fd, &old, 1, st.st_size - 1) == 1);
        changed = old ^ 1;
        assert(pwrite(fd, &changed, 1, st.st_size - 1) == 1);
        assert(pwrite(fd, &old, 1, st.st_size - 1) == 1);
        ts[0] = st.st_atim;
        ts[1] = st.st_mtim;
        ts[1].tv_sec++;
        assert(!futimens(fd, ts));
        drift = 0;
    }
    return got;
}
int __wrap_fdatasync(int fd)
{
    if (sync_failure) { errno = ENOSPC; return -1; }
    return __real_fdatasync(fd);
}
static int dma(void *opaque, uint64_t addr, void *buf, size_t size,
               bool write, bool probe)
{
    (void)opaque;
    if (addr != 0x40001000 || size > sizeof(ram)) return EFAULT;
    if (!probe) {
        if (write) memcpy(ram, buf, size);
        else memcpy(buf, ram, size);
    }
    return 0;
}
static void init(A7PFDevice *s, int fd, int geometry)
{
    struct stat st;
    memset(s, 0, sizeof(*s));
    assert(!fstat(fd, &st));
    assert(!a7pf_init(&s->core, fd, geometry, st.st_dev, st.st_ino, dma, s));
    s->expected_dev = st.st_dev;
    s->expected_ino = st.st_ino;
    s->opened = s->retained_state = true;
}
static void expect(const char *label, int actual, int expected)
{
    printf("CHECK %s actual=%d expected=%d\n", label, actual, expected);
    assert(actual == expected);
    checks++;
}
static void reject_load(A7PFDevice *s, const char *label, int error)
{
    struct a7pf before = s->core;
    expect(label, a7pf_post_load(s, 1), error);
    assert(!memcmp(&before, &s->core, sizeof(before)));
    checks++;
}
int main(int argc, char **argv)
{
    assert(argc == 5);
    int fd = open(argv[1], O_RDWR), geo = open(argv[2], O_RDONLY);
    int wronggeo = open(argv[3], O_RDONLY), other = open(argv[4], O_RDWR);
    assert(fd >= 0 && geo >= 0 && wronggeo >= 0 && other >= 0);
    A7PFDevice *a = g_new0(A7PFDevice, 1), *b = g_new0(A7PFDevice, 1);
    init(a, fd, geo); init(b, fd, geo);
    a7pf_write_reg(&a->core, 0x10, 7);
    a7pf_write_reg(&a->core, 0x18, 3);
    a7pf_write_reg(&a->core, 0x20, 1);
    a7pf_write_reg(&a->core, 0x24, 0x40001000);
    memset(ram, 0x6d, 512);
    a7pf_write_reg(&a->core, 0x14, A7PF_WRITE);
    expect("done-status", a->core.status, A7PF_DONE);
    expect("save-done", a7pf_pre_save(a), 0);
    b->migration = a->migration;
    expect("load-done", a7pf_post_load(b, 1), 0);
    assert(b->core.status == A7PF_DONE && b->core.actual == 512 && !b->core.error);
    a7pf_write_reg(&a->core, 0x14, 99);
    expect("failed-status", a->core.status, A7PF_FAILED);
    expect("save-failed", a7pf_pre_save(a), 0);
    A7PFMigration saved = a->migration;
    b->migration = saved;
    expect("load-failed", a7pf_post_load(b, 1), 0);
    assert(b->core.status == A7PF_FAILED && !b->core.actual && b->core.error == EOPNOTSUPP);
    assert(b->core.fd != a->core.fd && b->core.dma_opaque == b);
    expect("wrong-version", a7pf_post_load(b, 2), -EOPNOTSUPP);
    a->retained_state = false;
    struct a7pf before = a->core;
    expect("default-block", a7pf_pre_save(a), -EOPNOTSUPP);
    assert(!memcmp(&before, &a->core, sizeof(before)));
    a->retained_state = true;
    b->retained_state = false;
    reject_load(b, "destination-default-block", -EOPNOTSUPP);
    b->retained_state = true;
    sync_failure = 1;
    expect("save-real-fdatasync-failure", a7pf_pre_save(a), -ENOSPC);
    sync_failure = 0;
    short_read = 1;
    expect("save-short-read", a7pf_pre_save(a), -EIO);
    short_read = 1;
    reject_load(b, "load-short-read", -EIO);
    read_failure = 1;
    expect("save-read-error", a7pf_pre_save(a), -EACCES);
    reject_load(b, "load-read-error", -EACCES);
    read_failure = 0;
    drift = 1;
    expect("save-hash-stamp-drift", a7pf_pre_save(a), -ESTALE);
    drift = 1;
    reject_load(b, "load-hash-stamp-drift", -ESTALE);
    int ro = open(argv[1], O_RDONLY), original = a->core.fd;
    a->core.fd = ro;
    expect("save-readonly-fd", a7pf_pre_save(a), -EBADF);
    a->core.fd = original;
    original = b->core.fd; b->core.fd = ro;
    reject_load(b, "load-readonly-fd", -EBADF);
    b->core.fd = original; close(ro);
    assert(!fchmod(fd, 0620));
    expect("save-unsafe-mode", a7pf_pre_save(a), -EPERM);
    reject_load(b, "load-unsafe-mode", -EPERM);
    assert(!fchmod(fd, 0600));
    struct stat st; assert(!fstat(fd, &st));
    assert(!ftruncate(fd, st.st_size - 512));
    expect("save-short-backend", a7pf_pre_save(a), -ESTALE);
    reject_load(b, "load-short-backend", -ESTALE);
    assert(!ftruncate(fd, st.st_size));
    uint8_t old, wrong;
    assert(pread(fd, &old, 1, 1048576) == 1);
    wrong = old ^ 1;
    assert(pwrite(fd, &wrong, 1, 1048576) == 1);
    reject_load(b, "one-byte-disk-mismatch", -ESTALE);
    assert(pwrite(fd, &old, 1, 1048576) == 1);
    for (int field = 0; field < 7; field++) {
        b->migration = saved;
        switch (field) {
        case 0: b->migration.dev++; break;
        case 1: b->migration.container_bytes++; break;
        case 2: b->migration.parts++; break;
        case 3: b->migration.boot_count++; break;
        case 4: b->migration.entries++; break;
        case 5: b->migration.slices[31].offset++; break;
        case 6: b->migration.disk_sha256[31] ^= 1; break;
        }
        reject_load(b, "stream-identity-tamper", -ESTALE);
    }
    b->migration = saved;
    a7pf_close(&b->core); init(b, fd, wronggeo); b->migration = saved;
    reject_load(b, "fresh-wrong-geometry", -ESTALE);
    a7pf_close(&b->core); init(b, other, geo); b->migration = saved;
    reject_load(b, "fresh-new-inode", -ESTALE);
    a->core.slices[0].length = UINT64_MAX;
    expect("range-invalid", a7pf_pre_save(a), -EINVAL);
    assert(a->core.status == A7PF_FAILED && a->core.error == EOPNOTSUPP);
    a7pf_close(&a->core); a7pf_close(&b->core);
    close(fd); close(geo); close(wronggeo); close(other);
    g_free(a); g_free(b);
    printf("RESULT checks=%d callbacks=production disk_and_syscalls=real\n", checks);
    return 0;
}
