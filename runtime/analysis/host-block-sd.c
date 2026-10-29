/* Explicit local USB block adapter: truthful ioctl capacity and real fsync, no ready gates. */
#define _GNU_SOURCE
#include <stdint.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#define HOST_SD_BYTES UINT64_C(256000000000)

static int same_block(const struct stat *a,const struct stat *b) {
    return S_ISBLK(a->st_mode) && S_ISBLK(b->st_mode) && a->st_dev==b->st_dev &&
           a->st_ino==b->st_ino && a->st_rdev==b->st_rdev;
}
static int truthful_capacity(int fd,struct stat *output,const struct stat *selected) {
    if(!same_block(output,selected))return 0;
    uint64_t bytes=0;unsigned int sector=0;
    if(ioctl(fd,0x80081272UL,&bytes) || ioctl(fd,0x1268UL,&sector) ||
       bytes!=HOST_SD_BYTES || sector!=512) {
        errno=EIO;return -1;
    }
    output->st_size=(off_t)bytes;return 1;
}

#ifndef HOST_BLOCK_SD_TEST
#include <dlfcn.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/uio.h>
_Static_assert(sizeof(off_t)==8 && sizeof(struct stat)==128,"original AArch64 stat ABI");
static pthread_once_t init_once=PTHREAD_ONCE_INIT;
static struct stat selected;
static int selected_fd=-1,initialized;
static uintptr_t stat_caller;
static unsigned long (*original_flush)(void *);
static void *lookup(const char *name) {
    void *(*find)(void *,const char *)=dlvsym(RTLD_NEXT,"dlsym","GLIBC_2.17");
    return find?find(RTLD_NEXT,name):0;
}
static int actual_stat(int version,int fd,struct stat *out) {
    int (*function)(int,int,struct stat *)=dlvsym(RTLD_NEXT,"__fxstat64","GLIBC_2.17");
    if(!function){errno=ENOSYS;return -1;}
    return function(version,fd,out);
}
static int enabled(void) {
    const char *value=getenv("A7C2_HOST_BLOCK_SD");
    return value && !strcmp(value,"1");
}
static void trace(const char *kind,int fd,int result) {
    int saved=errno;
    char text[240];int n=snprintf(text,sizeof text,
        "HOST_BLOCK_SD_%s fd=%d result=%d bytes=%llu sector=512 state_bits_changed=0\n",
        kind,fd,result,(unsigned long long)HOST_SD_BYTES);
    int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
    if(console>=0){if(n>0 && n<(int)sizeof text)write(console,text,(size_t)n);close(console);}
    errno=saved;
}
static void initialize(void) {
    void *dummy=lookup("mcmn_drv_dummy_open");
    original_flush=lookup("mcmn_drv_default_flush");
    if(!dummy || !original_flush)return;
    stat_caller=(uintptr_t)dummy-0x28964+0x28c04;
    int candidate=open("/dev/sda",O_RDWR|O_NOFOLLOW|O_CLOEXEC);
    int named=open("/image_mmca",O_RDWR|O_NOFOLLOW|O_CLOEXEC);
    struct stat a,b,capacity;
    if(candidate<0 || named<0 || actual_stat(0,candidate,&a) || actual_stat(0,named,&b) || !same_block(&a,&b))goto fail;
    capacity=a;
    if(truthful_capacity(candidate,&capacity,&a)!=1)goto fail;
    selected=a;selected_fd=candidate;initialized=1;close(named);
    trace("BOUND",candidate,0);return;
fail:
    if(candidate>=0)close(candidate);
    if(named>=0)close(named);
    trace("REFUSED",-1,-1);
}
int __fxstat64(int version,int fd,struct stat *out) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    int result=actual_stat(version,fd,out);
    if(result || !enabled())return result;
    int saved=errno;
    void *dummy=lookup("mcmn_drv_dummy_open");
    if(!dummy || caller!=(uintptr_t)dummy-0x28964+0x28c04){errno=saved;return result;}
    pthread_once(&init_once,initialize);
    if(caller!=stat_caller){errno=saved;return result;}
    if(!initialized){errno=EIO;return -1;}
    int changed=truthful_capacity(fd,out,&selected);
    if(changed!=1){errno=EIO;return -1;}
    static unsigned int count;
    if(__atomic_add_fetch(&count,1,__ATOMIC_RELAXED)<=16)trace("CAPACITY",fd,0);
    errno=saved;return 0;
}
unsigned long mcmn_drv_default_flush(void *object) {
    if(!enabled()) {
        unsigned long (*function)(void *)=lookup("mcmn_drv_default_flush");
        return function?function(object):0x80000004UL;
    }
    pthread_once(&init_once,initialize);
    if(!initialized || !original_flush)return 0x80000004UL;
    /* The original device context stores fd at +0x98; never dereference an untrusted object. */
    int memory=open("/proc/self/mem",O_RDONLY|O_CLOEXEC),fd=-1;
    long have=memory<0?-1:pread(memory,&fd,sizeof fd,(off_t)((uintptr_t)object+0x98));
    if(memory>=0)close(memory);
    if(have!=sizeof fd)return 0x80000004UL;
    struct stat current;
    if(actual_stat(0,fd,&current))return 0x80000004UL;
    if(!same_block(&current,&selected))return original_flush(object);
    unsigned long rc=original_flush(object);
    if(rc)return rc;
    int result=fsync(fd);trace("FSYNC",fd,result);
    return result?0x80000004UL:0;
}
/* Passive selected-device I/O boundary: prefix sampling is not a whole-read digest. */
static void io_trace(const char *kind,int fd,const struct iovec *iov,int count,off_t offset,long result,int error) {
    if(!enabled() || !initialized)return;
    struct stat current;
    if(actual_stat(0,fd,&current) || !same_block(&current,&selected))return;
    unsigned int n;
    if(kind[0]=='w') {
        static unsigned int write_records;
        n=__atomic_add_fetch(&write_records,1,__ATOMIC_RELAXED);
        if(n>64)return;
    } else {
        static unsigned int records;
        n=__atomic_add_fetch(&records,1,__ATOMIC_RELAXED);
        if(n>24)return;
    }
    struct iovec first={0};unsigned char bytes[64]={0};long copied=-1;
    int memory=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);
    long have=memory<0?-1:pread(memory,&first,sizeof first,(off_t)(uintptr_t)iov);
    if(have==sizeof first && result>0 && count>0 && first.iov_len) {
        size_t size=first.iov_len<sizeof bytes?first.iov_len:sizeof bytes;
        if(size>(unsigned long)result)size=(size_t)result;
        copied=pread(memory,bytes,size,(off_t)(uintptr_t)first.iov_base);
    }
    if(memory>=0)close(memory);
    char hex[129]={0};
    if(copied>0)for(long i=0;i<copied;i++)snprintf(hex+i*2,3,"%02x",bytes[i]);
    char line[500];int length=snprintf(line,sizeof line,
        "HOST_BLOCK_SD_IO kind=%s n=%u fd=%d offset=%lld count=%d first_len=%lu result=%ld errno=%d sampled=%ld prefix=%s\n",
        kind,n,fd,(long long)offset,count,(unsigned long)first.iov_len,result,error,copied,hex);
    int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
    if(console>=0){if(length>0 && length<(int)sizeof line)write(console,line,(size_t)length);close(console);}
}
ssize_t preadv64(int fd,const struct iovec *iov,int count,off64_t offset) {
    ssize_t (*function)(int,const struct iovec *,int,off64_t)=dlvsym(RTLD_NEXT,"preadv64","GLIBC_2.17");
    if(!function){errno=ENOSYS;return -1;}
    ssize_t result=function(fd,iov,count,offset);int saved=errno;
    io_trace("read",fd,iov,count,offset,result,saved);errno=saved;return result;
}
ssize_t pwritev64(int fd,const struct iovec *iov,int count,off64_t offset) {
    ssize_t (*function)(int,const struct iovec *,int,off64_t)=dlvsym(RTLD_NEXT,"pwritev64","GLIBC_2.17");
    if(!function){errno=ENOSYS;return -1;}
    ssize_t result=function(fd,iov,count,offset);int saved=errno;
    io_trace("write",fd,iov,count,offset,result,saved);errno=saved;return result;
}
static int error_query(const char *name) {
    int incoming=errno;
    int (*function)(void)=lookup(name);
    if(!function){errno=ENOSYS;return -1;}
    errno=incoming;
    int result=function(),saved=errno;
    static unsigned int records;
    if(enabled() && __atomic_add_fetch(&records,1,__ATOMIC_RELAXED)<=32) {
        char line[180];int n=snprintf(line,sizeof line,"HOST_BLOCK_SD_PF_ERROR name=%s result=%#x\n",name,(unsigned int)result);
        int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
        if(console>=0){if(n>0 && n<(int)sizeof line)write(console,line,(size_t)n);close(console);}
    }
    errno=saved;return result;
}
int pf2_errnum(void){return error_query("pf2_errnum");}
int pf2_inerrnum(void){return error_query("pf2_inerrnum");}
unsigned int PFDRV_convErrorFromPDMtoPF(void *volume,unsigned int error) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    int incoming=errno;
    unsigned int (*function)(void *,unsigned int)=lookup("PFDRV_convErrorFromPDMtoPF");
    if(!function){errno=ENOSYS;return (unsigned int)-1;}
    errno=incoming;
    unsigned int result=function(volume,error);int saved=errno;
    static unsigned int count;
    if(enabled() && __atomic_add_fetch(&count,1,__ATOMIC_RELAXED)<=24) {
        uintptr_t base=(uintptr_t)function-0x5725c;
        char line[240];int length=snprintf(line,sizeof line,
            "HOST_BLOCK_SD_PDM_TO_PF caller=Fsys+%#lx pdm=%#x pf=%#x volume=%p\n",
            (unsigned long)(caller-base),error,result,volume);
        int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
        if(console>=0){if(length>0 && length<(int)sizeof line)write(console,line,(size_t)length);close(console);}
    }
    errno=saved;return result;
}
static void stage_trace(const char *name,uintptr_t caller,uintptr_t base,unsigned int result,
                         unsigned long a0,unsigned long a1,unsigned long a2,unsigned long a3) {
    int saved=errno;
    if(enabled()) {
        static unsigned int count;
        if(__atomic_add_fetch(&count,1,__ATOMIC_RELAXED)<=32) {
            char line[320];int length=snprintf(line,sizeof line,
                "HOST_BLOCK_SD_STAGE name=%s caller=Fsys+%#lx result=%#x args=%#lx,%#lx,%#lx,%#lx\n",
                name,(unsigned long)(caller-base),result,a0,a1,a2,a3);
            int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
            if(console>=0){if(length>0 && length<(int)sizeof line)write(console,line,(size_t)length);close(console);}
        }
    }
    errno=saved;
}
unsigned int PFDRV_mount(void *volume,unsigned int flags) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);int saved=errno;
    unsigned int (*function)(void *,unsigned int)=lookup("PFDRV_mount");
    if(!function){errno=ENOSYS;return (unsigned int)-1;}
    errno=saved;unsigned int result=function(volume,flags);
    stage_trace("PFDRV_mount",caller,(uintptr_t)function-0x57d48,result,(unsigned long)volume,flags,0,0);
    return result;
}
unsigned int PFCACHE_AllocateDataPage(void *volume,uint64_t sector,void *out,unsigned int flags) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);int saved=errno;
    unsigned int (*function)(void *,uint64_t,void *,unsigned int)=lookup("PFCACHE_AllocateDataPage");
    if(!function){errno=ENOSYS;return (unsigned int)-1;}
    errno=saved;unsigned int result=function(volume,sector,out,flags);
    stage_trace("PFCACHE_AllocateDataPage",caller,(uintptr_t)function-0x60348,result,
                (unsigned long)volume,(unsigned long)sector,(unsigned long)out,flags);
    return result;
}
unsigned int PFCACHE_InitCaches(void *volume) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);int saved=errno;
    unsigned int (*function)(void *)=lookup("PFCACHE_InitCaches");
    if(!function){errno=ENOSYS;return (unsigned int)-1;}
    errno=saved;unsigned int result=function(volume);
    stage_trace("PFCACHE_InitCaches",caller,(uintptr_t)function-0x5ea40,result,(unsigned long)volume,0,0,0);
    return result;
}
unsigned int mcmn_buf_getforpadding(void *out_address,void *out_size) {
    int incoming=errno;
    unsigned int (*function)(void *,void *)=lookup("mcmn_buf_getforpadding");
    if(!function){errno=ENOSYS;return (unsigned int)-1;}
    errno=incoming;unsigned int result=function(out_address,out_size);int saved=errno;
    if(enabled()) {
        static unsigned int count;
        if(__atomic_add_fetch(&count,1,__ATOMIC_RELAXED)<=8) {
            uint64_t address=0,size=0;
            int memory=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);
            long a=memory<0?-1:pread(memory,&address,8,(off_t)(uintptr_t)out_address);
            long b=memory<0?-1:pread(memory,&size,8,(off_t)(uintptr_t)out_size);
            if(memory>=0)close(memory);
            char line[240];int length=snprintf(line,sizeof line,
                "HOST_BLOCK_SD_PADDING result=%#x address=%#llx bytes=%llu read=%ld/%ld original_allocator=1\n",
                result,(unsigned long long)address,(unsigned long long)size,a,b);
            int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
            if(console>=0){if(length>0 && length<(int)sizeof line)write(console,line,(size_t)length);close(console);}
        }
    }
    errno=saved;return result;
}
unsigned long fsysDepLog_PrFILE2_PDM(unsigned long object,unsigned int stage,
                                     unsigned int error,unsigned int detail) {
    int saved=errno;
    unsigned long (*function)(unsigned long,unsigned int,unsigned int,unsigned int)=lookup("fsysDepLog_PrFILE2_PDM");
    if(!function){errno=ENOSYS;return (unsigned long)-1;}
    if(enabled()) {
        static unsigned int count;
        if(__atomic_add_fetch(&count,1,__ATOMIC_RELAXED)<=32) {
            char line[240];int length=snprintf(line,sizeof line,
                "HOST_BLOCK_SD_PDM stage=%u error=%#x detail=%#x object=%#lx original_return_preserved=1\n",
                stage,error,detail,object);
            int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
            if(console>=0){if(length>0 && length<(int)sizeof line)write(console,line,(size_t)length);close(console);}
        }
    }
    errno=saved;
    return function(object,stage,error,detail);
}
static void *host_fsys_trace_continue __attribute__((used));
/* Preserve the original variadic call: log raw arguments, never reformat/replace its invocation. */
void capture_host_fsys_trace(unsigned long level,const char *format,unsigned long a2,
                             unsigned long a3,unsigned long a4,unsigned long a5,
                             unsigned long a6,unsigned long a7) {
    int saved=errno;
    if(!__atomic_load_n(&host_fsys_trace_continue,__ATOMIC_ACQUIRE))
        __atomic_store_n(&host_fsys_trace_continue,lookup("fsysDepTrace_Printf"),__ATOMIC_RELEASE);
    if(!__atomic_load_n(&host_fsys_trace_continue,__ATOMIC_ACQUIRE))_exit(126);
    if(enabled()) {
        static unsigned int count;
        if(__atomic_add_fetch(&count,1,__ATOMIC_RELAXED)<=160) {
            char copy[193]={0};
            int memory=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);
            long n=memory<0?-1:pread(memory,copy,sizeof copy-1,(off_t)(uintptr_t)format);
            if(memory>=0)close(memory);
            copy[sizeof copy-1]=0;
            if(n<0)copy[0]=0;
            char line[560];int length=snprintf(line,sizeof line,
                "HOST_BLOCK_SD_FSYS_TRACE level=%lu format=%.192s args=%#lx,%#lx,%#lx,%#lx,%#lx,%#lx\n",
                level,copy,a2,a3,a4,a5,a6,a7);
            int console=open("/dev/console",O_WRONLY|O_CLOEXEC);
            if(console>=0){if(length>0 && length<(int)sizeof line)write(console,line,(size_t)length);close(console);}
        }
    }
    errno=saved;
}
__asm__(
".text\n"
".globl fsysDepTrace_Printf\n"
".type fsysDepTrace_Printf,%function\n"
"fsysDepTrace_Printf:\n"
"    sub sp, sp, #0xe0\n"
"    stp x0, x1, [sp, #0]\n"
"    stp x2, x3, [sp, #16]\n"
"    stp x4, x5, [sp, #32]\n"
"    stp x6, x7, [sp, #48]\n"
"    stp x8, x30, [sp, #64]\n"
"    stp q0, q1, [sp, #80]\n"
"    stp q2, q3, [sp, #112]\n"
"    stp q4, q5, [sp, #144]\n"
"    stp q6, q7, [sp, #176]\n"
"    mrs x16, nzcv\n"
"    str x16, [sp, #208]\n"
"    bl capture_host_fsys_trace\n"
"    ldr x16, [sp, #208]\n"
"    msr nzcv, x16\n"
"    ldp q6, q7, [sp, #176]\n"
"    ldp q4, q5, [sp, #144]\n"
"    ldp q2, q3, [sp, #112]\n"
"    ldp q0, q1, [sp, #80]\n"
"    ldp x8, x30, [sp, #64]\n"
"    ldp x6, x7, [sp, #48]\n"
"    ldp x4, x5, [sp, #32]\n"
"    ldp x2, x3, [sp, #16]\n"
"    ldp x0, x1, [sp, #0]\n"
"    add sp, sp, #0xe0\n"
"    adrp x16, host_fsys_trace_continue\n"
"    ldr x16, [x16, #:lo12:host_fsys_trace_continue]\n"
"    br x16\n"
);
#endif
