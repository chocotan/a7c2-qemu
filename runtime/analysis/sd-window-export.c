/* Guest-only fixed-window export. SD_EXPORT_TEST excludes every real I/O path. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
#define SD_CAP 0x400000U
#define SD_PHYS UINT64_C(0x41e600000)
#define SD_RESERVATION "memrsv=0x00400000@0x41e600000:uc"
#define SD_COMBINED_RESERVATION "memrsv=0x00900000@0x41e100000:uc"

struct sd_identity {
    uint64_t dev, inode, total;
    int64_t mtime, ctime;
    uint32_t mtime_ns, ctime_ns;
};
struct sd_io {
    void *context;
    const char *cmdline;
    int (*identity)(void *, struct sd_identity *);
    unsigned char *(*window)(void *);
    long (*read_at)(void *, unsigned char *, size_t, uint64_t);
};
struct sd_result { struct sd_identity identity; uint64_t fnv; };

static int sd_number(const char *s, uint64_t *out) {
    uint64_t n = 0;
    if (!s || !*s) return -1;
    for (; *s; ++s) {
        if (*s < '0' || *s > '9' || n > ((uint64_t)INT64_MAX - (unsigned)(*s - '0')) / 10U) return -1;
        n = n * 10U + (*s - '0');
    }
    *out = n;
    return 0;
}
static int sd_space(char c) { return c == ' ' || c == '\t' || c == '\n' || c == '\r'; }
static int sd_reserved(const char *s) {
    unsigned count = 0;
    if (!s) return 0;
    while (*s) {
        while (sd_space(*s)) ++s;
        const char *start = s;
        while (*s && !sd_space(*s)) ++s;
        if ((size_t)(s-start) == sizeof SD_RESERVATION-1 &&
            !memcmp(start, SD_RESERVATION, sizeof SD_RESERVATION-1)) ++count;
        if ((size_t)(s-start) == sizeof SD_COMBINED_RESERVATION-1 &&
            !memcmp(start, SD_COMBINED_RESERVATION, sizeof SD_COMBINED_RESERVATION-1)) ++count;
    }
    return count == 1;
}
static int sd_same(const struct sd_identity *a, const struct sd_identity *b) {
    return a->dev == b->dev && a->inode == b->inode && a->total == b->total &&
        a->mtime == b->mtime && a->ctime == b->ctime &&
        a->mtime_ns == b->mtime_ns && a->ctime_ns == b->ctime_ns;
}
/* No pathname, address or shell command is provided by the caller. */
static int sd_export(const struct sd_io *io, uint64_t offset, uint64_t length,
                     uint64_t total, struct sd_result *out) {
    struct sd_identity before, after;
    if (!total || total > INT64_MAX || !length || length > SD_CAP ||
        offset > total || length > total-offset) return 2;
    if (!sd_reserved(io->cmdline)) return 3;
    if (io->identity(io->context, &before) || before.total != total) return 4;
    unsigned char *window = io->window(io->context);
    if (!window) return 5;
    uint64_t done = 0;
    while (done < length) {
        long n = io->read_at(io->context, window+done, length-done, offset+done);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0 || (uint64_t)n > length-done) return 6;
        done += n;
    }
    memset(window+length, 0, SD_CAP-length);
    uint64_t hash = UINT64_C(14695981039346656037);
    for (uint64_t i=0; i<length; ++i) hash = (hash ^ window[i]) * UINT64_C(1099511628211);
    __sync_synchronize();
    if (io->identity(io->context, &after) || !sd_same(&before, &after)) return 7;
    out->identity = after;
    out->fnv = hash;
    return 0;
}

#ifndef SD_EXPORT_TEST
#if !defined(__aarch64__)
#error "Guest only: host tests must define SD_EXPORT_TEST"
#endif
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/mman.h>
/* Firmware glibc 2.25 predates the public fstat/lstat symbols in host headers.
 * AArch64 uses stat ABI version 0, with 64-bit off_t and the 128-byte layout. */
extern int __fxstat(int, int, struct stat *);
extern int __lxstat(int, const char *, struct stat *);
_Static_assert(sizeof(off_t)==8 && sizeof(struct stat)==128, "AArch64 stat ABI");
struct guest { int file; unsigned char *mapped; };
static void stat_identity(const struct stat *s, struct sd_identity *i) {
    i->dev=s->st_dev; i->inode=s->st_ino; i->total=s->st_size;
    i->mtime=s->st_mtim.tv_sec; i->mtime_ns=s->st_mtim.tv_nsec;
    i->ctime=s->st_ctim.tv_sec; i->ctime_ns=s->st_ctim.tv_nsec;
}
static int guest_identity(void *context, struct sd_identity *out) {
    struct guest *g=context;
    struct stat fd, path;
    struct sd_identity named;
    if (__fxstat(0,g->file,&fd) || __lxstat(0,"/image_mmca",&path) ||
        !S_ISREG(fd.st_mode) || !S_ISREG(path.st_mode) || fd.st_size < 0) return -1;
    stat_identity(&fd,out); stat_identity(&path,&named);
    return sd_same(out,&named) ? 0 : -1;
}
static unsigned char *guest_window(void *context) {
    struct guest *g=context;
    int memory=open("/dev/mem",O_RDWR|O_CLOEXEC|O_NOFOLLOW);
    if (memory<0) return 0;
    void *p=mmap(0,SD_CAP,PROT_READ|PROT_WRITE,MAP_SHARED,memory,SD_PHYS);
    int rc=close(memory);
    if (p==MAP_FAILED) return 0;
    if (rc) { munmap(p,SD_CAP); return 0; }
    g->mapped=p;
    return p;
}
static long guest_read(void *context, unsigned char *buffer, size_t count, uint64_t offset) {
    return pread(((struct guest *)context)->file,buffer,count,(off_t)offset);
}
static int guest_run(int argc, char **argv) {
    uint64_t offset=0,length=0,total=0;
    int rc=2;
    struct guest g={-1,0};
    struct sd_result result;
    if (argc!=4 || sd_number(argv[1],&offset) || sd_number(argv[2],&length) ||
        sd_number(argv[3],&total) || !total || !length || length>SD_CAP ||
        offset>total || length>total-offset) goto finish;
    char cmdline[8192];
    int fd=open("/proc/cmdline",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if (fd<0) { rc=3; goto finish; }
    size_t used=0;
    for (;;) {
        ssize_t n=read(fd,cmdline+used,sizeof cmdline-1-used);
        if (n<0 && errno==EINTR) continue;
        if (n<0 || used==sizeof cmdline-1) { rc=3; break; }
        if (!n) { rc=0; break; }
        used+=n;
    }
    if (close(fd)) rc=3;
    if (rc) goto finish;
    cmdline[used]=0;
    if (memchr(cmdline,0,used) || !sd_reserved(cmdline)) { rc=3; goto finish; }
    g.file=open("/image_mmca",O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
    if (g.file<0) { rc=4; goto finish; }
    struct sd_io io={&g,cmdline,guest_identity,guest_window,guest_read};
    rc=sd_export(&io,offset,length,total,&result);
finish:
    if (g.mapped && munmap(g.mapped,SD_CAP)) rc=8;
    if (g.file>=0 && close(g.file)) rc=8;
    if (rc) { printf("SD_EXPORT_ERROR rc=%d\n",rc); fflush(0); return rc; }
    printf("SD_EXPORT_READY offset=%llu len=%llu total=%llu dev=%llu inode=%llu "
           "mtime=%lld.%09u ctime=%lld.%09u fnv64=%016llx rc=0\n",
           (unsigned long long)offset,(unsigned long long)length,(unsigned long long)total,
           (unsigned long long)result.identity.dev,(unsigned long long)result.identity.inode,
           (long long)result.identity.mtime,result.identity.mtime_ns,
           (long long)result.identity.ctime,result.identity.ctime_ns,
           (unsigned long long)result.fnv);
    fflush(0);
    return 0;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,
                            void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(guest_run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
