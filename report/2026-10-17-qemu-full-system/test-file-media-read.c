/* No VM: assert ABI, single original call, errno, bounded reads and stale handles. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>

static int read_calls,read_result=3,seek_during_read;
static char receipt[512];
int Fsys_Seek(unsigned long long,long long,unsigned int,void *);
static int original_open(const char *path,unsigned long long *handle,unsigned flags) {
    (void)path;assert(flags==3);*handle=1;errno=EAGAIN;return 0;
}
static int original_read(unsigned long long handle,void *buffer,int requested) {
    assert(handle==1);read_calls++;
    if(seek_during_read) {seek_during_read=0;assert(!Fsys_Seek(handle,0,0,0));}
    if(read_result>0 && read_result<=requested) memset(buffer,'x',(size_t)read_result);
    errno=EINTR;return read_result;
}
static int original_seek(unsigned long long handle,long long offset,unsigned origin,void *output) {
    (void)handle;(void)offset;(void)origin;
    if(output && output!=(void *)1)*(unsigned long long *)output=9;
    errno=ERANGE;return 0;
}
static int original_close(unsigned long long handle) {(void)handle;errno=EBUSY;return -7;}
static unsigned unmount_calls;
static int original_unmount(unsigned char drive,unsigned flags) {
    assert(drive=='B' && flags==1);unmount_calls++;errno=EIO;return -9;
}
static void *lookup(void *h,const char *name) {
    (void)h;
    if(!strcmp(name,"Fsys_Open"))return original_open;
    if(!strcmp(name,"Fsys_Read"))return original_read;
    if(!strcmp(name,"Fsys_Seek"))return original_seek;
    if(!strcmp(name,"Fsys_Close"))return original_close;
    if(!strcmp(name,"Fsys_Unmount"))return original_unmount;
    abort();
}
static void *fake_dlvsym(void *h,const char *name,const char *version) {
    (void)h;(void)name;(void)version;return lookup;
}
static int fake_open(const char *path,int flags,...) {
    (void)flags;assert(!strcmp(path,"/dev/console"));return 999;
}
static long fake_write(int fd,const void *data,unsigned long length) {
    assert(fd==999 && length<sizeof receipt);
    memcpy(receipt,data,length);receipt[length]=0;errno=ENOSPC;return (long)length;
}
static int fake_close(int fd) {assert(fd==999);return 0;}
static int fake_fflush(void *stream) {(void)stream;return 0;}
#define dlvsym fake_dlvsym
#define open fake_open
#define write fake_write
#define close fake_close
#define fflush fake_fflush
#include "file-media-config.c"

int main(void) {
    assert(!setenv("A7C2_FILE_MEDIA_TEST","1",1));
    unsigned long long handle;char bytes[70000];
    assert(!Fsys_Open("A:/PRIVATE/M4ROOT/MEDIAPRO.XML",&handle,3) && errno==EAGAIN);
    assert(Fsys_Read(handle,bytes,10)==3 && errno==EINTR && read_calls==1);
    assert(strstr(receipt,"file=2") && strstr(receipt,"offset=0 ") && strstr(receipt,"actual=3 hashed=3"));
    assert(Fsys_Read(handle,bytes,10)==3 && strstr(receipt,"offset=3 "));
    unsigned long long position=0;
    assert(!Fsys_Seek(handle,12,0,&position) && position==9 && errno==ERANGE);
    assert(Fsys_Read(handle,bytes,10)==3 && strstr(receipt,"offset=9 "));
    assert(!Fsys_Seek(handle,12,0,0) && errno==ERANGE);receipt[0]=0;
    assert(Fsys_Read(handle,bytes,10)==3 && !receipt[0]);
    assert(!Fsys_Seek(999,12,0,(void *)1) && errno==ERANGE);
    receipt[0]=0;read_result=-11;
    assert(Fsys_Read(handle,0,10)==-11 && errno==EINTR && !receipt[0]);
    assert(!Fsys_Seek(handle,0,0,0));read_result=70000;
    assert(Fsys_Read(handle,bytes,70000)==70000 && strstr(receipt,"hashed=65536 "));
    receipt[0]=0;read_result=3;seek_during_read=1;
    assert(Fsys_Read(handle,bytes,10)==3 && !strstr(receipt,"FILE_MEDIA_READ"));
    assert(Fsys_Close(handle)==-7 && errno==EBUSY);
    assert(Fsys_Read(handle,bytes,10)==3 && !strstr(receipt,"FILE_MEDIA_READ"));
    assert(!Fsys_Open("A:/PRIVATE/DATABASE/DATABASE.BIN",&handle,3));
    assert(Fsys_Read(handle,bytes,10)==3 && strstr(receipt,"file=1") && strstr(receipt,"offset=0 "));
    assert(!pthread_mutex_lock(&read_lock));
    pid_t child=fork();assert(child>=0);
    if(!child) {alarm(2);assert(read_begin(1).slot==-1);_exit(0);}
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!pthread_mutex_unlock(&read_lock));
    assert(!Fsys_Open("B:/PRIVATE/M4ROOT/MEDIAPRO.XML",&handle,3));
    assert(Fsys_Read(handle,bytes,10)==3 && strstr(receipt,"file=2") && strstr(receipt,"offset=0 "));
    assert(Fsys_Unmount('B',1)==-9 && errno==EIO && unmount_calls==1);
    assert(strstr(receipt,"op=Unmount drive=66 flags=0x1 result=-9"));
    assert(!observed_path("") && !observed_path("A") && !observed_path("a:/PRIVATE/M4ROOT/MEDIAPRO.XML"));
    return 0;
}
