/* SPDX-License-Identifier: MIT */
/* Snapshot a regular file's size once. A growing writer cannot extend output. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stddef.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#ifdef __aarch64__
/* Sony4.9 arm64 uses asm-generic/stat.h and fstat syscall80. Avoid modern
 * glibc's fstat symbol redirect while asserting the actual kernel layout. */
_Static_assert(SYS_fstat==80,"unexpected arm64 fstat syscall");
_Static_assert(sizeof(struct stat)==128 && offsetof(struct stat,st_mode)==16 && offsetof(struct stat,st_size)==48,
               "unexpected arm64 kernel stat layout");
#endif
static int run(int argc,char **argv){
    if(argc!=3)return 2;
    unsigned long limit=0;
    if(!*argv[2])return 2;
    for(const unsigned char *p=(const unsigned char *)argv[2];*p;p++){
        if(*p<'0' || *p>'9' || limit>6553)return 2;
        limit=limit*10+*p-'0';if(limit>65536)return 2;
    }
    if(!limit)return 2;
    fprintf(stderr,"FULLSYSTEM_LOG_STAGE stage=open path=%s\n",argv[1]);
    int fd=open(argv[1],O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    if(fd<0){printf("FULLSYSTEM_LOG_SNAPSHOT_MISSING path=%s errno=%d\n",argv[1],errno);return 3;}
    fprintf(stderr,"FULLSYSTEM_LOG_STAGE stage=fstat path=%s\n",argv[1]);
    struct stat st;
    if(syscall(SYS_fstat,fd,&st) || !S_ISREG(st.st_mode) || st.st_size<0){
        close(fd);printf("FULLSYSTEM_LOG_SNAPSHOT_REJECTED path=%s\n",argv[1]);return 4;
    }
    size_t count=(unsigned long long)st.st_size<limit?(size_t)st.st_size:(size_t)limit;
    off_t offset=st.st_size-(off_t)count;
    printf("FULLSYSTEM_LOG_SNAPSHOT path=%s size=%llu offset=%llu count=%lu\n",argv[1],
           (unsigned long long)st.st_size,(unsigned long long)offset,(unsigned long)count);
    if(fflush(stdout)){close(fd);return 5;}
    unsigned char buffer[4096];size_t done=0;
    while(done<count){
        size_t wanted=count-done;if(wanted>sizeof buffer)wanted=sizeof buffer;
        ssize_t n=pread(fd,buffer,wanted,offset+(off_t)done);
        if(n<0 && errno==EINTR)continue;
        if(n<=0){close(fd);fprintf(stderr,"FULLSYSTEM_LOG_SNAPSHOT_SHORT expected=%lu actual=%lu\n",(unsigned long)count,(unsigned long)done);return 6;}
        size_t sent=0;
        while(sent<(size_t)n){
            ssize_t wrote=write(1,buffer+sent,(size_t)n-sent);
            if(wrote<0 && errno==EINTR)continue;
            if(wrote<=0){close(fd);return 7;}sent+=(size_t)wrote;
        }
        done+=(size_t)n;
    }
    fprintf(stderr,"FULLSYSTEM_LOG_STAGE stage=close path=%s\n",argv[1]);
    if(close(fd))return 8;
    fprintf(stderr,"FULLSYSTEM_LOG_STAGE stage=done path=%s\n",argv[1]);return 0;
}
#ifdef BOUNDED_LOG_TEST
int main(int argc,char **argv){return run(argc,argv);}
#else
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
