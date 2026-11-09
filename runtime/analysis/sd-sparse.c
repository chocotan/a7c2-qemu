/* Local guest ordinary sparse-card creation/map/write; never formats a filesystem. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/vfs.h>

#define SD_SPARSE_TOTAL (UINT64_C(10)*1024*1024*1024)
#define SD_SPARSE_CARD_TOTAL (UINT64_C(1)*1024*1024*1024)
#define SD_SPARSE_DATA_LIMIT (UINT64_C(512)*1024*1024)
#define SD_SPARSE_WINDOW 0x400000U
#define SD_SPARSE_RANGES 4096U
_Static_assert(sizeof(off_t)==8, "64-bit file offsets required");
extern int __fxstat(int,int,struct stat *);
extern int __lxstat(int,const char *,struct stat *);

static int sparse_same(const struct stat *a,const struct stat *b) {
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino && a->st_size==b->st_size &&
        a->st_mtim.tv_sec==b->st_mtim.tv_sec && a->st_mtim.tv_nsec==b->st_mtim.tv_nsec &&
        a->st_ctim.tv_sec==b->st_ctim.tv_sec && a->st_ctim.tv_nsec==b->st_ctim.tv_nsec;
}
/* Bound work by actual data, never silently replace unsupported SEEK_HOLE with zeros. */
static int sparse_ranges(int fd,uint64_t total,
                         int (*range)(void *,uint64_t,uint64_t),void *context,
                         unsigned int *count,uint64_t *data) {
    uint64_t cursor=0;*count=0;*data=0;
    while(cursor<total) {
        errno=0;off_t start=lseek(fd,(off_t)cursor,SEEK_DATA);
        if(start<0)return errno==ENXIO?0:-1;
        if((uint64_t)start<cursor || (uint64_t)start>=total)return -1;
        off_t end=lseek(fd,start,SEEK_HOLE);
        if(end<=start || (uint64_t)end>total)return -1;
        uint64_t bytes=(uint64_t)(end-start);
        if(bytes>SD_SPARSE_DATA_LIMIT-*data)return -1;
        *data+=bytes;
        while(start<end) {
            uint64_t length=(uint64_t)(end-start);
            if(length>SD_SPARSE_WINDOW)length=SD_SPARSE_WINDOW;
            if(++*count>SD_SPARSE_RANGES || range(context,(uint64_t)start,length))return -1;
            start+=(off_t)length;
        }
        cursor=(uint64_t)end;
    }
    return 0;
}

/* BusyBox dd in the original rootfs has no conv=notrunc. Use bounded pwrite. */
static int sparse_write(const char *card_path,const char *source_path,uint64_t offset) {
    int card=-1,source=-1,rc=5;struct stat before,after,named,input,input_after;
    card=open(card_path,O_WRONLY|O_NOFOLLOW|O_CLOEXEC);
    source=open(source_path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
    if(card<0 || source<0 || __fxstat(0,card,&before) || __fxstat(0,source,&input) ||
       !S_ISREG(before.st_mode) || !S_ISREG(input.st_mode) || before.st_size<0 ||
       (uint64_t)before.st_size>SD_SPARSE_CARD_TOTAL || input.st_size<=0 ||
       input.st_size>SD_SPARSE_WINDOW || input.st_size%4096 || offset%4096 ||
       offset>SD_SPARSE_CARD_TOTAL-(uint64_t)input.st_size)goto done;
    uint64_t end=offset+(uint64_t)input.st_size;
    uint64_t expected=(uint64_t)before.st_size>end?(uint64_t)before.st_size:end;
    char buffer[65536];uint64_t position=0;
    while(position<(uint64_t)input.st_size) {
        size_t wanted=(uint64_t)input.st_size-position>sizeof(buffer)?sizeof(buffer):(size_t)((uint64_t)input.st_size-position);
        ssize_t got=read(source,buffer,wanted);if(got<=0)goto done;
        size_t copied=0;
        while(copied<(size_t)got) {
            ssize_t put=pwrite(card,buffer+copied,(size_t)got-copied,(off_t)(offset+position+copied));
            if(put<=0)goto done;copied+=(size_t)put;
        }
        position+=(uint64_t)got;
    }
    if(__fxstat(0,card,&after) || __lxstat(0,card_path,&named) ||
       __fxstat(0,source,&input_after) || !sparse_same(&input,&input_after) ||
       !S_ISREG(after.st_mode) || !S_ISREG(named.st_mode) ||
       before.st_dev!=after.st_dev || before.st_ino!=after.st_ino ||
       after.st_dev!=named.st_dev || after.st_ino!=named.st_ino ||
       (uint64_t)after.st_size!=expected || (uint64_t)named.st_size!=expected)goto done;
    rc=0;
done:
    if(source>=0 && close(source))rc=5;
    if(card>=0 && close(card))rc=5;
    if(!rc)printf("SD_SPARSE_WRITE offset=%llu bytes=%lld rc=0\n",
                  (unsigned long long)offset,(long long)input.st_size);
    return rc;
}

#ifndef SD_SPARSE_TEST
#if !defined(__aarch64__)
#error "Guest only; host tests must define SD_SPARSE_TEST"
#endif
extern int __fxstat(int,int,struct stat *);
extern int __lxstat(int,const char *,struct stat *);
_Static_assert(sizeof(struct stat)==128,"original AArch64 stat ABI");
static int output_range(void *unused,uint64_t offset,uint64_t length) {
    (void)unused;
    return printf("SD_SPARSE_RANGE offset=%llu len=%llu\n",
                  (unsigned long long)offset,(unsigned long long)length)<0?-1:0;
}
static int sparse_create(void) {
    struct statfs filesystem;
    if(statfs("/tmp/sony-sd10g",&filesystem) || filesystem.f_type!=0x01021994 ||
       !filesystem.f_bsize || !filesystem.f_blocks ||
       (uint64_t)filesystem.f_blocks>SD_SPARSE_DATA_LIMIT/filesystem.f_bsize)return 2;
    int directory=open("/tmp/sony-sd10g",O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC);
    if(directory<0)return 2;
    int fd=openat(directory,"card.img",O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    close(directory);if(fd<0)return 2;
    struct stat st;int rc=3;
    if(!ftruncate(fd,SD_SPARSE_TOTAL) && !fsync(fd) && !__fxstat(0,fd,&st) &&
       S_ISREG(st.st_mode) && st.st_size==SD_SPARSE_TOTAL && st.st_blocks==0) {
        printf("SD_SPARSE_CREATED total=%llu dev=%llu inode=%llu allocated=0 filesystem=tmpfs unformatted=1\n",
               (unsigned long long)st.st_size,(unsigned long long)st.st_dev,(unsigned long long)st.st_ino);
        rc=0;
    }
    if(close(fd))rc=3;
    return rc;
}
static int sparse_map(void) {
    int fd=open("/image_mmca",O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC);
    if(fd<0)return 4;
    struct stat before,after,named;
    unsigned int count=0;uint64_t data=0;int rc=4;
    if(__fxstat(0,fd,&before) || __lxstat(0,"/image_mmca",&named) ||
       !S_ISREG(before.st_mode) || !S_ISREG(named.st_mode) || !sparse_same(&before,&named) ||
       (before.st_size!=SD_SPARSE_TOTAL && before.st_size!=SD_SPARSE_CARD_TOTAL) || before.st_blocks<0 ||
       (uint64_t)before.st_blocks>SD_SPARSE_DATA_LIMIT/512)goto done;
    printf("SD_SPARSE_BEGIN total=%llu dev=%llu inode=%llu mtime=%lld.%09ld ctime=%lld.%09ld\n",
           (unsigned long long)before.st_size,(unsigned long long)before.st_dev,
           (unsigned long long)before.st_ino,(long long)before.st_mtim.tv_sec,before.st_mtim.tv_nsec,
           (long long)before.st_ctim.tv_sec,before.st_ctim.tv_nsec);
    if(sparse_ranges(fd,(uint64_t)before.st_size,output_range,0,&count,&data) ||
       __fxstat(0,fd,&after) || __lxstat(0,"/image_mmca",&named) ||
       !sparse_same(&before,&after) || !sparse_same(&after,&named))goto done;
    printf("SD_SPARSE_END ranges=%u data=%llu allocated=%llu rc=0\n",count,
           (unsigned long long)data,(unsigned long long)before.st_blocks*512);
    rc=0;
done:
    if(close(fd))rc=4;
    return rc;
}
static int parse_offset(const char *text,uint64_t *value) {
    uint64_t result=0;if(!text || !*text)return -1;
    while(*text) {
        if(*text<'0' || *text>'9')return -1;
        unsigned int digit=(unsigned int)(*text++-'0');
        if(result>(UINT64_MAX-digit)/10)return -1;result=result*10+digit;
    }
    *value=result;return 0;
}
static int run(int argc,char **argv) {
    int rc=2;
    if(argc==2 && !strcmp(argv[1],"create"))rc=sparse_create();
    else if(argc==2 && !strcmp(argv[1],"map"))rc=sparse_map();
    else if(argc==5 && !strcmp(argv[1],"write")) {
        uint64_t offset=0;
        if(!parse_offset(argv[4],&offset))rc=sparse_write(argv[2],argv[3],offset);
    }
    if(rc)printf("SD_SPARSE_ERROR rc=%d errno=%d\n",rc,errno);
    fflush(0);return rc;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,
                            void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
