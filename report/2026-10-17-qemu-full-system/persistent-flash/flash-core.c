/* SPDX-License-Identifier: MIT */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "flash-core.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static uint32_t le32(const uint8_t *p)
{ return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint64_t le64(const uint8_t *p)
{ return le32(p) | (uint64_t)le32(p+4)<<32; }
static int regular(int fd, struct stat *st)
{
    if (fstat(fd, st)) return errno;
    if (!S_ISREG(st->st_mode) || st->st_uid != geteuid() || st->st_nlink != 1 ||
        (st->st_mode & 022)) return EPERM;
    return 0;
}
int a7pf_open_regular(const char *path, int flags)
{
    char *copy, *next, *part;
    int dir, fd = -1, saved;
    struct stat st;
    if (!path || !*path) { errno = EINVAL; return -1; }
    dir = open(path[0]=='/' ? "/" : ".", O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if (dir < 0) return -1;
    copy = strdup(path);
    if (!copy) { close(dir); errno=ENOMEM; return -1; }
    part = strtok_r(copy, "/", &next);
    while (part) {
        char *following = strtok_r(NULL, "/", &next);
        if (!strcmp(part, "..")) { errno=EINVAL; break; }
        if (!following) {
            fd = openat(dir, part, flags|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK);
            if (fd >= 0) {
                int err = regular(fd, &st);
                if (err) { close(fd); fd=-1; errno=err; }
            }
            break;
        }
        int child = openat(dir, part, O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
        if (child < 0) break;
        close(dir); dir=child; part=following;
    }
    saved=errno; close(dir); free(copy); errno=saved;
    return fd;
}
static int backend_valid(struct a7pf *s)
{
    struct stat st;
    int err=regular(s->fd, &st);
    if (err) return err;
    if ((uint64_t)st.st_dev != s->dev || (uint64_t)st.st_ino != s->ino ||
        (uint64_t)st.st_size != s->container_bytes) return ESTALE;
    if ((fcntl(s->fd, F_GETFL) & O_ACCMODE) != O_RDWR) return EBADF;
    return 0;
}
int a7pf_init(struct a7pf *s, int backend_fd, int geometry_fd, uint64_t dev,
              uint64_t ino, a7pf_dma_fn dma, void *opaque)
{
    uint8_t wire[24+32*24];
    struct stat st;
    int err;
    memset(s, 0, sizeof(*s)); s->fd=-1;
    if (!dma || (err=regular(geometry_fd, &st))) return dma ? err : EINVAL;
    if (st.st_size < 24 || st.st_size > (off_t)sizeof(wire)) return EINVAL;
    ssize_t got=pread(geometry_fd, wire, sizeof(wire), 0);
    if (got != st.st_size) return got < 0 ? errno : EIO;
    if (memcmp(wire, "A7PFGE01", 8) || le32(wire+8)!=1) return EINVAL;
    s->entries=le32(wire+12); s->capacity=le64(wire+16);
    if (s->entries>32 || st.st_size != 24+(off_t)s->entries*24 ||
        !s->capacity || s->capacity>INT64_MAX-8388608 || (s->capacity&511)) return EINVAL;
    s->container_bytes=s->capacity;
    uint64_t end=0;
    uint32_t previous=0;
    for (uint32_t i=0; i<s->entries; i++) {
        const uint8_t *p=wire+24+i*24;
        struct a7pf_slice *sl=&s->slices[i];
        sl->number=le32(p); sl->offset=le64(p+8); sl->length=le64(p+16);
        if (le32(p+4) || sl->number<=previous || sl->number>32 ||
            !sl->length || (sl->offset&511) || (sl->length&511) || sl->offset<end)
            return EINVAL;
        if (sl->number<=30) {
            if (sl->offset>s->capacity || sl->length>s->capacity-sl->offset) return EINVAL;
            s->parts++;
        } else {
            if (sl->number!=31+s->boot_count || sl->offset!=s->capacity+s->boot_count*4194304ull ||
                sl->length!=4194304) return EINVAL;
            s->boot_count++; s->container_bytes+=4194304;
        }
        previous=sl->number; end=sl->offset+sl->length;
    }
    if (s->boot_count && s->boot_count!=2) return EINVAL;
    if (!dev || !ino) return EINVAL;
    s->fd=fcntl(backend_fd, F_DUPFD_CLOEXEC, 3);
    if (s->fd<0) return errno;
    s->dev=dev; s->ino=ino;
    err=backend_valid(s);
    if (!err) {
        struct flock lock={.l_type=F_WRLCK, .l_whence=SEEK_SET, .l_start=0, .l_len=1};
        if (fcntl(s->fd, F_OFD_SETLK, &lock)) err=errno;
    }
    if (err) { a7pf_close(s); return err; }
    s->dma=dma; s->dma_opaque=opaque;
    s->io=(struct a7pf_io){.read=pread, .write=pwrite, .sync=fdatasync};
    return 0;
}
void a7pf_close(struct a7pf *s)
{ if (s->fd>=0) close(s->fd); s->fd=-1; }
static int execute(struct a7pf *s, uint32_t op)
{
    uint64_t start=0, length=s->capacity;
    int err=backend_valid(s);
    if (err) return err;
    if (s->select) {
        uint32_t i;
        for (i=0; i<s->entries; i++) if (s->slices[i].number==s->select) break;
        if (i==s->entries) return ENODEV;
        start=s->slices[i].offset; length=s->slices[i].length;
    }
    if (op==A7PF_GEOMETRY) {
        s->geometry_size=length/512; s->geometry_start=start/512; return 0;
    }
    if (op==A7PF_FLUSH) return s->io.sync(s->fd) ? errno : 0;
    if (op!=A7PF_READ && op!=A7PF_WRITE) return EOPNOTSUPP;
    if (!s->count || s->count>A7PF_MAX_IO/512 || s->sector>length/512 ||
        s->count>length/512-s->sector) return EINVAL;
    size_t bytes=(size_t)s->count*512;
    if ((s->dma_addr&511) || s->dma_addr>UINT64_MAX-bytes) return EFAULT;
    err=s->dma(s->dma_opaque, s->dma_addr, s->bounce, bytes, op==A7PF_READ, true);
    if (err) return err;
    off_t offset=(off_t)(start+s->sector*512);
    ssize_t n;
    if (op==A7PF_WRITE) {
        err=s->dma(s->dma_opaque, s->dma_addr, s->bounce, bytes, false, false);
        if (err) return err;
        n=s->io.write(s->fd, s->bounce, bytes, offset);
        if (n!=(ssize_t)bytes) return n<0 ? errno : EIO;
        if (s->io.sync(s->fd)) return errno;
    } else {
        n=s->io.read(s->fd, s->bounce, bytes, offset);
        if (n!=(ssize_t)bytes) return n<0 ? errno : EIO;
        err=s->dma(s->dma_opaque, s->dma_addr, s->bounce, bytes, true, false);
        if (err) return err;
    }
    s->actual=bytes; return 0;
}
uint32_t a7pf_read_reg(struct a7pf *s, uint32_t off)
{
    switch (off) {
    case 0x00:return A7PF_MAGIC;
    case 0x04:return A7PF_VERSION;
    case 0x08:return A7PF_MAX_IO;
    case 0x0c:return s->parts;
    case 0x10:return s->select;
    case 0x18:return s->sector;
    case 0x1c:return s->sector>>32;
    case 0x20:return s->count;
    case 0x24:return s->dma_addr;
    case 0x28:return s->dma_addr>>32;
    case 0x2c:return s->status;
    case 0x30:return s->actual;
    case 0x34:return s->error;
    case 0x38:return s->geometry_size;
    case 0x3c:return s->geometry_size>>32;
    case 0x40:return s->geometry_start;
    case 0x44:return s->geometry_start>>32;
    case 0x48:return s->boot_count;
    default:return 0;
    }
}
void a7pf_write_reg(struct a7pf *s, uint32_t off, uint32_t value)
{
    switch (off) {
    case 0x10:s->select=value;break;
    case 0x18:s->sector=(s->sector&0xffffffff00000000ull)|value;break;
    case 0x1c:s->sector=(s->sector&0xffffffffull)|((uint64_t)value<<32);break;
    case 0x20:s->count=value;break;
    case 0x24:s->dma_addr=(s->dma_addr&0xffffffff00000000ull)|value;break;
    case 0x28:s->dma_addr=(s->dma_addr&0xffffffffull)|((uint64_t)value<<32);break;
    case 0x14:
        s->status=0; s->actual=0; s->error=0; s->geometry_size=0; s->geometry_start=0;
        s->error=execute(s, value);
        s->status=s->error ? A7PF_FAILED : A7PF_DONE;
        break;
    default:break;
    }
}
