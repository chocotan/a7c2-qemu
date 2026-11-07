/* SPDX-License-Identifier: MIT */
#include "pmbp-candidate.h"
#ifdef PMBP_BROKER
#include "pmbp-libc.h"
#endif
#include <errno.h>
#include <fcntl.h>
#include <linux/fs.h>
#include <limits.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>
#define CALLER ((uintptr_t)__builtin_extract_return_addr(__builtin_return_address(0)))
extern int __fxstat64(int,int,struct stat *);
#ifndef PMBP_BROKER
__attribute__((weak)) const struct pmbp_contract *pmbp_runtime_contract(void) { return NULL; }
__attribute__((weak)) int pmbp_attest(enum pmbp_operation op,uintptr_t pc,struct pmbp_resource *r)
{ (void)op; (void)pc; (void)r; errno=ENOTSUP; return -1; }
__attribute__((weak)) void pmbp_event_sink(const struct pmbp_event *e) { (void)e; }
#endif
#ifndef PMBP_BROKER
static int native_open(const char *p,int f,mode_t m) { return open64(p,f,m); }
static int native_ioctl(int fd,unsigned long request,void *out) { return ioctl(fd,request,out); }
static int native_duplicate(int fd) { return fcntl(fd,F_DUPFD_CLOEXEC,3); }
#ifdef PMBP_HOST_FIXTURE
static struct pmbp_fixture_io io;
#else
static const struct {
    int (*open)(const char *,int,mode_t);
    int (*stat)(int,int,struct stat *);
    int (*close)(int);
    ssize_t (*write)(int,const void *,size_t);
    ssize_t (*pwrite)(int,const void *,size_t,off_t);
    ssize_t (*pread)(int,void *,size_t,off_t);
    int (*ioctl)(int,unsigned long,void *);
    int (*duplicate)(int);
    ssize_t (*pwritev)(int,const struct iovec *,int,off_t);
    int (*fsync)(int);
} io={native_open,__fxstat64,close,write,pwrite64,pread64,native_ioctl,native_duplicate,pwritev64,fsync};
#endif
#endif
#ifdef PMBP_BROKER
#define io (*pmbp_native_io())
#endif
static atomic_flag busy=ATOMIC_FLAG_INIT;
static atomic_int owned=ATOMIC_VAR_INIT(-1), poisoned=ATOMIC_VAR_INIT(PMBP_OK);
static atomic_uint passive_count, functional_count;
static _Atomic uint64_t serial, verified;
static atomic_uint open_ordinal;
static atomic_int owner_pid, owner_tid;
static int is_owned(int fd) { return fd>=0 && fd==atomic_load(&owned); }
static int readback=-1;
static struct pmbp_contract active;
static struct stat identity;
static void poison(enum pmbp_poison why)
{ int expected=PMBP_OK; (void)atomic_compare_exchange_strong(&poisoned,&expected,(int)why); }
static int deny(enum pmbp_poison why,int error) { poison(why); errno=error; return -1; }
static void event(enum pmbp_operation op,unsigned functional,long rc,int error,
                  uint64_t off,size_t requested,size_t observed)
{
    int saved=errno;
    atomic_uint *budget=functional ? &functional_count : &passive_count;
    unsigned n=atomic_fetch_add(budget,1);
    if(n<PMBP_LOG_BUDGET) {
        struct pmbp_event e={op,functional,open_ordinal,serial,off,requested,observed,
            rc,error,(enum pmbp_poison)atomic_load(&poisoned)};
        pmbp_event_sink(&e);
    }
    errno=saved;
}
static int nonzero(const unsigned char *p,size_t n)
{ unsigned char v=0; for(size_t i=0;i<n;i++) v|=p[i]; return v!=0; }
static int contract_valid(const struct pmbp_contract *c)
{
    const struct pmbp_resource *r=&c->resource;
    return c->profile && !strcmp(c->profile,PMBP_PROFILE) && c->schema==1 &&
        c->marker_verified==1 && c->pid==getpid() && c->tid==(pid_t)syscall(SYS_gettid) &&
        r->generation && r->lease_epoch && r->disk_dev && r->disk_ino &&
        r->block_ino && r->block_rdev && r->offset==PMBP_OFFSET && r->bytes==PMBP_BYTES &&
        r->sys_major && nonzero(r->geometry_sha256,32) &&
        nonzero(r->module_sha256,32) && nonzero(r->source_sha256,32);
}
static int same_resource(const struct pmbp_resource *a,const struct pmbp_resource *b)
{
    return a->generation==b->generation && a->lease_epoch==b->lease_epoch &&
        a->disk_dev==b->disk_dev && a->disk_ino==b->disk_ino &&
        a->block_dev==b->block_dev && a->block_ino==b->block_ino &&
        a->block_rdev==b->block_rdev && a->offset==b->offset && a->bytes==b->bytes &&
        a->sys_major==b->sys_major && a->sys_minor==b->sys_minor &&
        !memcmp(a->geometry_sha256,b->geometry_sha256,32) &&
        !memcmp(a->module_sha256,b->module_sha256,32) &&
        !memcmp(a->source_sha256,b->source_sha256,32);
}
static int enter(void)
{
    if(atomic_load(&owner_pid)!=getpid() || atomic_load(&owner_tid)!=(pid_t)syscall(SYS_gettid))
        return deny(PMBP_THREAD,EPERM);
    if(atomic_flag_test_and_set(&busy)) return deny(PMBP_REENTRY,EBUSY);
    return 0;
}
static void leave(void) { atomic_flag_clear(&busy); }
static int attest(enum pmbp_operation op,uintptr_t pc,const struct pmbp_contract *c)
{
    struct pmbp_resource actual={0};
    if(!contract_valid(c) || pmbp_attest(op,pc,&actual) ||
       !same_resource(&actual,&c->resource)) return deny(PMBP_BAD_CONTRACT,ESTALE);
    return 0;
}
static int capacity(int fd,const struct pmbp_contract *c,const struct stat *st)
{
    uint64_t bytes=0; int readonly=-1;
    const struct pmbp_resource *r=&c->resource;
    if(!S_ISBLK(st->st_mode) || (uint64_t)st->st_dev!=r->block_dev ||
       (uint64_t)st->st_ino!=r->block_ino || (uint64_t)st->st_rdev!=r->block_rdev ||
       major(st->st_rdev)!=r->sys_major || minor(st->st_rdev)!=r->sys_minor)
        return deny(PMBP_IDENTITY,ENODEV);
    if(io.ioctl(fd,BLKGETSIZE64,&bytes) || io.ioctl(fd,BLKROGET,&readonly))
        return deny(PMBP_IO,EIO);
    if(readonly!=0) return deny(PMBP_IO,EROFS);
    if(bytes!=r->bytes || bytes!=PMBP_BYTES) return deny(PMBP_IDENTITY,ERANGE);
    return 0;
}
static int validate(int fd,enum pmbp_operation op,uintptr_t pc)
{
    struct stat st;
    if(atomic_load(&poisoned)!=PMBP_OK) { errno=EIO; return -1; }
    if(attest(op,pc,&active)) return -1;
    if(io.stat(0,fd,&st)) return deny(PMBP_IO,EIO);
    if(st.st_dev!=identity.st_dev || st.st_ino!=identity.st_ino ||
       st.st_rdev!=identity.st_rdev) return deny(PMBP_IDENTITY,ESTALE);
    return capacity(fd,&active,&st);
}
int pmbp_open64_at(const char *path,int flags,mode_t mode,uintptr_t caller)
{
    int incoming=errno, fd=io.open(path,flags,mode), saved=errno;
    const struct pmbp_contract *c=NULL;
    if(saved!=EFAULT && path && !strcmp(path,PMBP_ALIAS)) c=pmbp_runtime_contract();
    if(!c || saved==EFAULT || !path || strcmp(path,PMBP_ALIAS)) { errno=saved; return fd; }
    /* Original call is always made once, before this explicit ENOENT mapping. */
    open_ordinal++;
    event(PMBP_OPEN,0,fd,saved,0,0,0);
    if(fd>=0 || saved!=ENOENT) { errno=saved; return fd; }
    if(flags!=(O_RDWR|O_CLOEXEC)) return deny(PMBP_BAD_CONTRACT,EINVAL);
    if(!contract_valid(c)) return deny(PMBP_BAD_CONTRACT,ESTALE);
    if(atomic_flag_test_and_set(&busy)) return deny(PMBP_REENTRY,EBUSY);
    if(atomic_load(&owned)>=0 || atomic_load(&poisoned)!=PMBP_OK || serial==UINT64_MAX) {
        leave(); return deny(PMBP_BAD_CONTRACT,EBUSY);
    }
    if(attest(PMBP_OPEN,caller,c)) { leave(); return -1; }
    fd=io.open(PMBP_TARGET,O_RDWR|O_CLOEXEC|O_NOFOLLOW,0);
    saved=errno;
    if(fd<0) { poison(PMBP_IO); leave(); errno=saved; return -1; }
    struct stat st;
    int err=io.stat(0,fd,&st);
    if(err) (void)deny(PMBP_IO,EIO);
    if(err || capacity(fd,c,&st)) {
        saved=errno; (void)io.close(fd); leave(); errno=saved; return -1;
    }
    int pin=io.duplicate(fd);
    if(pin<0) {
        saved=errno; poison(PMBP_DUPLICATION); (void)io.close(fd); leave(); errno=saved; return -1;
    }
    struct stat pinned;
    if(io.stat(0,pin,&pinned) || pinned.st_dev!=st.st_dev ||
       pinned.st_ino!=st.st_ino || pinned.st_rdev!=st.st_rdev) {
        (void)io.close(pin); (void)io.close(fd); leave(); return deny(PMBP_IDENTITY,ESTALE);
    }
    active=*c; identity=st; readback=pin; serial++; verified=0;
    atomic_store(&owner_pid,c->pid); atomic_store(&owner_tid,c->tid);
    atomic_store(&owned,fd);
    event(PMBP_OPEN,1,fd,0,0,0,0);
    leave(); errno=incoming; return fd;
}
int pmbp_fxstat64_at(int version,int fd,struct stat *st,uintptr_t caller)
{
    if(!is_owned(fd)) return io.stat(version,fd,st);
    int incoming=errno;
    if(enter()) return -1;
    int rc=io.stat(version,fd,st), saved=errno;
    event(PMBP_STAT,0,rc,saved,0,0,0);
    if(!rc && version==0) {
        if(attest(PMBP_STAT,caller,&active) || capacity(fd,&active,st) ||
           atomic_load(&poisoned)!=PMBP_OK) { rc=-1; saved=EIO; }
        else { st->st_size=(off_t)active.resource.bytes; saved=incoming;
               event(PMBP_STAT,1,0,0,0,0,0); }
    }
    leave(); errno=saved; return rc;
}
static int bounds(off_t offset,size_t n)
{
    if(offset<0 || (uint64_t)offset>PMBP_BYTES || n>PMBP_BYTES-(uint64_t)offset)
        return deny(PMBP_BOUNDS,EFBIG);
    return 0;
}
static void compare_written(const void *data,ssize_t n,off_t off)
{
    unsigned char check[4096];
    size_t done=0;
    while(done<(size_t)n) {
        size_t amount=(size_t)n-done; if(amount>sizeof(check)) amount=sizeof(check);
        ssize_t got=io.pread(readback,check,amount,off+(off_t)done);
        if(got!=(ssize_t)amount || memcmp(check,(const unsigned char *)data+done,amount)) {
            poison(PMBP_READBACK); return;
        }
        done+=amount;
    }
    if(UINT64_MAX-verified<(uint64_t)n) poison(PMBP_IO);
    else verified+=(uint64_t)n;
}
static ssize_t write_owned(int fd,const void *data,size_t n,off_t off,int positioned,uintptr_t pc)
{
    int incoming=errno;
    enum pmbp_operation op=positioned ? PMBP_PWRITE : PMBP_WRITE;
    if(enter()) return -1;
    if(validate(fd,op,pc)) { leave(); return -1; }
    if(!positioned) off=io.seek(fd,0,SEEK_CUR);
    if(off<0 || bounds(off,n)) { if(off<0) poison(PMBP_IO); leave(); return -1; }
    errno=incoming;
    ssize_t rc=positioned ? io.pwrite(fd,data,n,off) : io.write(fd,data,n);
    int saved=errno;
    if(rc>0 && (uint64_t)rc<=n) {
        compare_written(data,rc,off);
        if(validate(fd,op,pc)) poison(PMBP_BAD_CONTRACT);
    }
    if(rc<0) poison(PMBP_IO);
    else if((uint64_t)rc!=n) poison(PMBP_SHORT);
    event(op,1,rc,saved,(uint64_t)off,n,rc>0 ? (size_t)rc : 0);
    leave(); errno=saved; return rc;
}
ssize_t pmbp_write_at(int fd,const void *p,size_t n,uintptr_t caller)
{ return !is_owned(fd) ? io.write(fd,p,n) : write_owned(fd,p,n,0,0,caller); }
ssize_t pmbp_pwrite64_at(int fd,const void *p,size_t n,off_t off,uintptr_t caller)
{ return !is_owned(fd) ? io.pwrite(fd,p,n,off) : write_owned(fd,p,n,off,1,caller); }
ssize_t pmbp_pwritev64_at(int fd,const struct iovec *vectors,int count,off_t off,uintptr_t caller)
{
    if(!is_owned(fd))return io.pwritev(fd,vectors,count,off);
    int incoming=errno;
    if(enter())return -1;
    if(validate(fd,PMBP_PWRITEV,caller)){leave();return -1;}
    if(count<0 || count>1024){leave();return deny(PMBP_BOUNDS,EINVAL);}
    struct iovec snapshot[1024];size_t total=0;
    struct iovec local={snapshot,(size_t)count*sizeof(*vectors)},remote={(void *)vectors,local.iov_len};
    if(count && syscall(SYS_process_vm_readv,getpid(),&local,1,&remote,1,0)!=(ssize_t)local.iov_len){leave();return deny(PMBP_IO,EFAULT);}
    for(int i=0;i<count;i++){
        if(snapshot[i].iov_len>(size_t)SSIZE_MAX-total){leave();return deny(PMBP_BOUNDS,EINVAL);}
        total+=snapshot[i].iov_len;
    }
    if(bounds(off,total)){leave();return -1;}
    errno=incoming;
    ssize_t rc=io.pwritev(fd,snapshot,count,off);int saved=errno;
    if(rc>0 && (uint64_t)rc<=total){
        size_t remaining=(size_t)rc;off_t cursor=off;
        for(int i=0;i<count && remaining;i++){
            size_t n=snapshot[i].iov_len<remaining?snapshot[i].iov_len:remaining;
            compare_written(snapshot[i].iov_base,(ssize_t)n,cursor);
            cursor+=(off_t)n;remaining-=n;
        }
        if(validate(fd,PMBP_PWRITEV,caller))poison(PMBP_BAD_CONTRACT);
    }
    if(rc<0)poison(PMBP_IO);
    else if((uint64_t)rc!=total)poison(PMBP_SHORT);
    event(PMBP_PWRITEV,1,rc,saved,(uint64_t)off,total,rc>0?(size_t)rc:0);
    leave();errno=saved;return rc;
}
int pmbp_fsync_at(int fd,uintptr_t caller)
{
    if(!is_owned(fd))return io.fsync(fd);
    int incoming=errno;
    if(enter())return -1;
    if(validate(fd,PMBP_FSYNC,caller)){leave();return -1;}
    errno=incoming;int rc=io.fsync(fd),saved=errno;
    if(rc)poison(PMBP_IO);
    event(PMBP_FSYNC,1,rc,saved,0,0,0);leave();errno=saved;return rc;
}
int pmbp_ioctl_at(int fd,unsigned long request,void *arg,uintptr_t caller)
{
    if(!is_owned(fd))return io.ioctl(fd,request,arg);
    if(enter())return -1;
    /* Capacity/RO are the only defined owned-fd requests; never invent offsets. */
    if(request!=BLKGETSIZE64 && request!=BLKROGET){leave();return deny(PMBP_BAD_CONTRACT,ENOTSUP);}
    int incoming=errno;
    if(validate(fd,PMBP_IOCTL,caller)){leave();return -1;}
    errno=incoming;int rc=io.ioctl(fd,request,arg),saved=errno;
    if(rc)poison(PMBP_IO);
    event(PMBP_IOCTL,1,rc,saved,0,0,0);leave();errno=saved;return rc;
}
ssize_t pmbp_read_at(int fd,void *p,size_t n,uintptr_t caller)
{
    if(!is_owned(fd)) return io.read(fd,p,n);
    int incoming=errno;
    if(enter()) return -1;
    if(validate(fd,PMBP_READ,caller)) { leave(); return -1; }
    errno=incoming; ssize_t rc=io.read(fd,p,n); int saved=errno;
    if(rc<0) poison(PMBP_IO);
    leave(); errno=saved; return rc;
}
ssize_t pmbp_pread64_at(int fd,void *p,size_t n,off_t off,uintptr_t caller)
{
    if(!is_owned(fd)) return io.pread(fd,p,n,off);
    int incoming=errno;
    if(enter()) return -1;
    if(validate(fd,PMBP_PREAD,caller) || bounds(off,n)) { leave(); return -1; }
    errno=incoming; ssize_t rc=io.pread(fd,p,n,off); int saved=errno;
    if(rc<0) poison(PMBP_IO);
    leave(); errno=saved; return rc;
}
off_t pmbp_lseek64_at(int fd,off_t off,int whence,uintptr_t caller)
{
    if(!is_owned(fd)) return io.seek(fd,off,whence);
    int incoming=errno;
    if(enter()) return -1;
    if(validate(fd,PMBP_SEEK,caller)) { leave(); return -1; }
    /* Keep SEEK_CUR arithmetic checked before executing the native seek. */
    off_t base=0;
    if(whence==SEEK_CUR) base=io.seek(fd,0,SEEK_CUR);
    else if(whence==SEEK_END) base=(off_t)PMBP_BYTES;
    else if(whence!=SEEK_SET) { leave(); return deny(PMBP_BOUNDS,EINVAL); }
    if(base<0 || off < -base || off > (off_t)PMBP_BYTES-base) {
        leave(); return deny(PMBP_BOUNDS,EFBIG);
    }
    errno=incoming; off_t rc=io.seek(fd,off,whence); int saved=errno;
    if(rc<0) poison(PMBP_IO);
    leave(); errno=saved; return rc;
}
int pmbp_close_at(int fd,uintptr_t caller)
{
    (void)caller;
    if(!is_owned(fd)) return io.close(fd);
    int incoming=errno;
    if(enter()) return -1;
    /* Capture this slot and generation before close; never re-look-up fd after it. */
    uint64_t closing_generation=serial; int pin=readback;
    errno=incoming; int rc=io.close(fd), saved=errno;
    if(rc) poison(PMBP_CLOSE_ERROR);
    if(serial==closing_generation) { atomic_store(&owned,-1); readback=-1; }
    if(pin>=0 && io.close(pin)) poison(PMBP_CLOSE_ERROR);
    event(PMBP_CLOSE,1,rc,saved,0,0,0);
    leave(); errno=saved; return rc;
}
static int duplication_guard(int from,int to)
{
    int fd=atomic_load(&owned);
    if(fd>=0 && (from==fd || to==fd)) return deny(PMBP_DUPLICATION,EPERM);
    return 0;
}
int pmbp_reject_owned_mmap(int fd)
{
    if(!is_owned(fd)) return 0;
    (void)deny(PMBP_BAD_CONTRACT,ENOTSUP);
    return 1;
}

int pmbp_reject_owned_stdio(int fd)
{
    if(!is_owned(fd)) return 0;
    (void)deny(PMBP_BAD_CONTRACT,ENOTSUP);
    return 1;
}

int pmbp_dup(int fd) { return duplication_guard(fd,-1) ? -1 : io.dup(fd); }
int pmbp_dup2(int from,int to) { return duplication_guard(from,to) ? -1 : io.dup2(from,to); }
int pmbp_dup3(int from,int to,int flags)
{ return duplication_guard(from,to) ? -1 : io.dup3(from,to,flags); }
int pmbp_fcntl_dup(int fd,int command,int minimum)
{
    if(command!=F_DUPFD && command!=F_DUPFD_CLOEXEC) { errno=EINVAL; return -1; }
    return duplication_guard(fd,-1) ? -1 : io.fcntl(fd,command,minimum);
}
struct pmbp_status pmbp_status(void)
{
    struct pmbp_status s={atomic_load(&owned),serial,verified,
        (enum pmbp_poison)atomic_load(&poisoned),atomic_load(&passive_count),atomic_load(&functional_count)};
    return s;
}
#ifdef PMBP_HOST_FIXTURE
void pmbp_fixture_reset(const struct pmbp_fixture_io *ops)
{
    io=*ops;
    if(!io.open) io.open=native_open;
    if(!io.stat) io.stat=__fxstat64;
    if(!io.close) io.close=close;
    if(!io.write) io.write=write;
    if(!io.pwrite) io.pwrite=pwrite64;
    if(!io.pread) io.pread=pread64;
    if(!io.ioctl) io.ioctl=native_ioctl;
    if(!io.duplicate) io.duplicate=native_duplicate;
    if(!io.read) io.read=read;
    if(!io.seek) io.seek=lseek64;
    if(!io.dup) io.dup=dup;
    if(!io.dup2) io.dup2=dup2;
    if(!io.dup3) io.dup3=dup3;
    if(!io.fcntl) io.fcntl=fcntl;
    if(!io.pwritev) io.pwritev=pwritev64;
    if(!io.fsync) io.fsync=fsync;
    atomic_store(&owned,-1); atomic_store(&poisoned,PMBP_OK);
    atomic_store(&passive_count,0); atomic_store(&functional_count,0);
    atomic_flag_clear(&busy); readback=-1; verified=0; open_ordinal=0;
    atomic_store(&owner_pid,0); atomic_store(&owner_tid,0);
    memset(&active,0,sizeof(active)); memset(&identity,0,sizeof(identity));
}
#endif

int pmbp_open64(const char *p,int f,...) {
 mode_t m=0; if((f&O_CREAT)||((f&O_TMPFILE)==O_TMPFILE)){va_list a;va_start(a,f);m=(mode_t)va_arg(a,int);va_end(a);}
 return pmbp_open64_at(p,f,m,CALLER);
}
int pmbp_fxstat64(int v,int f,struct stat *s){return pmbp_fxstat64_at(v,f,s,CALLER);}
ssize_t pmbp_write(int f,const void *p,size_t n){return pmbp_write_at(f,p,n,CALLER);}
ssize_t pmbp_pwrite64(int f,const void *p,size_t n,off_t o){return pmbp_pwrite64_at(f,p,n,o,CALLER);}
ssize_t pmbp_read(int f,void *p,size_t n){return pmbp_read_at(f,p,n,CALLER);}
ssize_t pmbp_pread64(int f,void *p,size_t n,off_t o){return pmbp_pread64_at(f,p,n,o,CALLER);}
off_t pmbp_lseek64(int f,off_t o,int w){return pmbp_lseek64_at(f,o,w,CALLER);}
int pmbp_close(int f){return pmbp_close_at(f,CALLER);}
