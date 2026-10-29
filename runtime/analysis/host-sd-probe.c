/* Helper-only virtual USB disk test, not a camera formatter or capture service. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <string.h>
#include <errno.h>
#define TOTAL UINT64_C(256000000000)
extern int __fxstat(int,int,struct stat *);
_Static_assert(sizeof(off_t)==8 && sizeof(struct stat)==128,"original AArch64 stat ABI");
static int run(int argc,char **argv) {
    int sync_only=argc==2 && !strcmp(argv[1],"sync");
    int raw_test=argc==2 && !strcmp(argv[1],"raw-test");
    if(!raw_test && !sync_only)return 2;
    int fd=open("/dev/sda",O_RDWR|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
    struct stat st;uint64_t bytes=0;unsigned int sector=0;
    if(fd<0 || __fxstat(0,fd,&st) || !S_ISBLK(st.st_mode) ||
       ioctl(fd,0x80081272UL,&bytes) || ioctl(fd,0x1268UL,&sector) ||
       bytes!=TOTAL || sector!=512) {
        printf("HOST_SD_PROBE_ERROR stage=identity errno=%d bytes=%llu sector=%u\n",errno,(unsigned long long)bytes,sector);
        if(fd>=0)close(fd);return 3;
    }
    printf("HOST_SD_PROBE_ID bytes=%llu sectors=%llu logical_sector=%u rdev=%llu\n",
           (unsigned long long)bytes,(unsigned long long)(bytes/512),sector,(unsigned long long)st.st_rdev);
    if(sync_only) {
        int rc=fsync(fd),error=errno;
        if(close(fd))rc=-1;
        printf("HOST_SD_BLOCK_SYNC bytes=%llu fsync_rc=%d errno=%d no_data_writes=1\n",
               (unsigned long long)bytes,rc,error);fflush(0);
        return rc?6:0;
    }
    const uint64_t offsets[3]={0,UINT64_C(4294967296)+512,TOTAL-512};
    unsigned char before[512],expected[512],actual[512];
    /* Refuse existing data: this helper is only allowed on its own empty test image. */
    for(unsigned int n=0;n<3;n++) {
        if(pread(fd,before,sizeof before,(off_t)offsets[n])!=sizeof before)goto fail;
        for(unsigned int i=0;i<sizeof before;i++)if(before[i])goto fail;
    }
    for(unsigned int n=0;n<3;n++) {
        for(unsigned int i=0;i<sizeof expected;i++)expected[i]=(unsigned char)(0x31+n*37+i*13);
        if(pwrite(fd,expected,sizeof expected,(off_t)offsets[n])!=sizeof expected || fsync(fd) ||
           pread(fd,actual,sizeof actual,(off_t)offsets[n])!=sizeof actual ||
           memcmp(actual,expected,sizeof actual))goto fail;
        printf("HOST_SD_PROBE_WRITE offset=%llu bytes=512 fsync=0 readback=equal\n",(unsigned long long)offsets[n]);
    }
    if(close(fd))return 5;
    printf("HOST_SD_PROBE_PASS scope=raw_virtual_USB_transport_not_original_Fsys_or_capture\n");
    fflush(0);return 0;
fail:
    printf("HOST_SD_PROBE_ERROR stage=io errno=%d\n",errno);close(fd);fflush(0);return 4;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,
                            void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
