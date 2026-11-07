/* No real host signal or /tmp mailbox: all guest paths go into argv[2]. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/syscall.h>

static const char *directory;
static int mode,stops,flushes,fail_ack=1;
static char *mapped(const char *path,char *target) {
    assert(!strncmp(path,"/tmp/",5));
    assert(snprintf(target,512,"%s/%s",directory,path+5)>0);
    return target;
}
static void cancel_request(void) {
    char path[512];mapped("/tmp/sd-flush.12.cancel",path);
    int fd=open(path,O_WRONLY|O_CREAT,0600);assert(fd>=0);close(fd);
}
static int original_mount(const char *path,unsigned int flags,char *drive,const void *extra) {
    (void)path;(void)flags;(void)extra;*drive='A';return 0;
}
static int original_flush(unsigned char drive) {
    assert(drive=='A');flushes++;
    if(mode==2)cancel_request(); /* Host cancels while the original flush is running. */
    return mode==3?-9:0;
}
static void *lookup(void *handle,const char *name) {
    (void)handle;
    if(!strcmp(name,"Fsys_Mount"))return original_mount;
    if(!strcmp(name,"Fsys_FlushVolume"))return original_flush;
    abort();
}
static void *fake_dlvsym(void *h,const char *name,const char *version) {
    (void)h;(void)name;(void)version;return lookup;
}
static int fake_open(const char *path,int flags,...) {
    char target[512];
    if(mode==4 && strstr(path,".reply.new")){errno=ENOSPC;return -1;}
    if(mode==5 && fail_ack && strstr(path,".cancelled.new")){errno=ENOSPC;return -1;}
    return open(mapped(path,target),flags,0600);
}
static int fake_rename(const char *first,const char *second) {
    char a[512],b[512];return rename(mapped(first,a),mapped(second,b));
}
static long fake_syscall(long number,...) {
    if(number==SYS_gettid)return 1234;
    assert(number==SYS_tgkill);
    va_list args;va_start(args,number);
    int pid=va_arg(args,int);long tid=va_arg(args,long);int signal=va_arg(args,int);
    va_end(args);
    assert(pid==getpid() && tid==1234 && signal==19);stops++;
    return 0; /* Simulated STOP followed by CONT; never signal a real host process. */
}
static int fake_fflush(void *stream){(void)stream;return 0;}
#define dlvsym fake_dlvsym
#define open fake_open
#define rename fake_rename
#define syscall fake_syscall
#define fflush fake_fflush
#include "file-media-config.c"
#undef open
#undef rename

int main(int argc,char **argv) {
    assert(argc==3);mode=atoi(argv[1]);directory=argv[2];unsetenv("A7C2_FILE_MEDIA_TEST");
    char drive;assert(!Fsys_Mount("/nondev/rm2",0x300,&drive,0));
    char path[512];mapped("/tmp/sd-flush.request",path);
    int fd=open(path,O_WRONLY|O_CREAT,0600);assert(fd>=0);
    assert(write(fd,"12\n",3)==3);close(fd);
    if(mode==1 || mode==5)cancel_request();
    file_media_flush_pending();
    assert(flushes==1);
    assert(stops==((mode==0)?1:0));
    if(mode==4) {
        mapped("/tmp/sd-flush.12.reply",path);assert(access(path,F_OK));
    } else {
        mapped("/tmp/sd-flush.12.reply",path);assert(!access(path,F_OK));
    }
    if(mode==5) {
        assert(cancel_pending==12);fail_ack=0;
        file_media_flush_cancel_retry();assert(cancel_pending==0 && flushes==1 && stops==0);
    }
    if(mode<3 || mode==5) {
        mapped("/tmp/sd-flush.12.cancelled",path);assert(!access(path,F_OK));
    }
    file_media_flush_pending();assert(flushes==1); /* Same sequence never flushes/stops twice. */
    return 0;
}
