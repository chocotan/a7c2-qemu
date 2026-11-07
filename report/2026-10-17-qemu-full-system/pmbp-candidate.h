/* SPDX-License-Identifier: MIT */
#ifndef PMBP_CANDIDATE_H
#define PMBP_CANDIDATE_H
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <stdint.h>
#include <stddef.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/uio.h>
#define PMBP_PROFILE "virtual-p1-pmbp-block-slice-v1"
#define PMBP_ALIAS "/image_nflasha23"
#define PMBP_TARGET "/dev/cnflasha23"
#define PMBP_OFFSET UINT64_C(1831862272)
#define PMBP_BYTES UINT64_C(67108864)
#define PMBP_LOG_BUDGET 256u
_Static_assert(sizeof(void *) == 8 && sizeof(off_t) == 8, "64-bit ABI required");
#if defined(__aarch64__)
_Static_assert(sizeof(struct stat)==128 && offsetof(struct stat,st_mode)==16 &&
               offsetof(struct stat,st_size)==48, "Sony guest stat ABI differs");
#endif
/* Private source integration contract, not an environment/configuration API. */
enum pmbp_operation { PMBP_OPEN, PMBP_STAT, PMBP_WRITE, PMBP_PWRITE,
    PMBP_READ, PMBP_PREAD, PMBP_SEEK, PMBP_CLOSE, PMBP_DUP,
    PMBP_PWRITEV, PMBP_FSYNC, PMBP_IOCTL };
enum pmbp_poison { PMBP_OK, PMBP_BAD_CONTRACT, PMBP_IDENTITY, PMBP_THREAD,
    PMBP_IO, PMBP_BOUNDS, PMBP_SHORT, PMBP_READBACK, PMBP_DUPLICATION,
    PMBP_CLOSE_ERROR, PMBP_REENTRY };
struct pmbp_resource {
    uint64_t generation, lease_epoch, disk_dev, disk_ino;
    uint64_t block_dev, block_ino, block_rdev, offset, bytes;
    uint32_t sys_major, sys_minor;
    unsigned char geometry_sha256[32], module_sha256[32], source_sha256[32];
};
struct pmbp_contract {
    const char *profile;
    uint32_t schema, marker_verified;
    pid_t pid, tid;
    struct pmbp_resource resource;
};
struct pmbp_event {
    enum pmbp_operation operation;
    unsigned functional, ordinal;
    uint64_t generation, offset, requested, observed;
    long native_rc;
    int native_errno;
    enum pmbp_poison poison;
};
/* Must authenticate marker/manifest, loaded original DSO and exact code/caller
 * pins, current lease/generation and project sysfs binding. No opaque deref.
 * Production weak defaults reject every functional request. */
const struct pmbp_contract *pmbp_runtime_contract(void);
int pmbp_attest(enum pmbp_operation operation, uintptr_t return_pc,
                struct pmbp_resource *observed);
void pmbp_event_sink(const struct pmbp_event *event);
int pmbp_open64_at(const char *,int,mode_t,uintptr_t);
int pmbp_fxstat64_at(int,int,struct stat *,uintptr_t);
ssize_t pmbp_write_at(int,const void *,size_t,uintptr_t);
ssize_t pmbp_pwrite64_at(int,const void *,size_t,off_t,uintptr_t);
ssize_t pmbp_read_at(int,void *,size_t,uintptr_t);
ssize_t pmbp_pread64_at(int,void *,size_t,off_t,uintptr_t);
off_t pmbp_lseek64_at(int,off_t,int,uintptr_t);
int pmbp_close_at(int,uintptr_t);
ssize_t pmbp_pwritev64_at(int,const struct iovec *,int,off_t,uintptr_t);
int pmbp_fsync_at(int,uintptr_t);
int pmbp_ioctl_at(int,unsigned long,void *,uintptr_t);
int pmbp_open64(const char *path, int flags, ...);
int pmbp_fxstat64(int version, int fd, struct stat *st);
ssize_t pmbp_write(int fd, const void *data, size_t bytes);
ssize_t pmbp_pwrite64(int fd, const void *data, size_t bytes, off_t offset);
ssize_t pmbp_read(int fd, void *data, size_t bytes);
ssize_t pmbp_pread64(int fd, void *data, size_t bytes, off_t offset);
off_t pmbp_lseek64(int fd, off_t offset, int whence);
int pmbp_close(int fd);
int pmbp_reject_owned_mmap(int);
int pmbp_reject_owned_stdio(int);
int pmbp_dup(int fd);
int pmbp_dup2(int from, int to);
int pmbp_dup3(int from, int to, int flags);
/* Called only for F_DUPFD/F_DUPFD_CLOEXEC by the enclosing fcntl adapter. */
int pmbp_fcntl_dup(int fd, int command, int minimum);
/* No formatter/installation success API: caller must inspect poison separately. */
struct pmbp_status { int owned_fd; uint64_t generation, verified_bytes;
    enum pmbp_poison poison; unsigned passive_logs, functional_logs; };
struct pmbp_status pmbp_status(void);
#ifdef PMBP_HOST_FIXTURE
/* Synthetic test seam only; never compiled into the guest candidate. */
struct pmbp_fixture_io {
    int (*open)(const char *,int,mode_t);
    int (*stat)(int,int,struct stat *);
    int (*close)(int);
    ssize_t (*write)(int,const void *,size_t);
    ssize_t (*pwrite)(int,const void *,size_t,off_t);
    ssize_t (*pread)(int,void *,size_t,off_t);
    int (*ioctl)(int,unsigned long,void *);
    int (*duplicate)(int);
    ssize_t (*read)(int,void *,size_t);
    off_t (*seek)(int,off_t,int);
    int (*dup)(int);
    int (*dup2)(int,int);
    int (*dup3)(int,int,int);
    int (*fcntl)(int,int,...);
    ssize_t (*pwritev)(int,const struct iovec *,int,off_t);
    int (*fsync)(int);
};
void pmbp_fixture_reset(const struct pmbp_fixture_io *ops);
#endif
#endif
