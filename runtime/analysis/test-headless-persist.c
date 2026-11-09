#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

extern int hosd_persist(const char *,const unsigned char *,unsigned long);
extern unsigned long hosd_hash(const unsigned char *,unsigned long);
static unsigned long reference_hash(const unsigned char *p,unsigned long n){
    unsigned long h=14695981039346656037UL;
    while(n--)h=(h^*p++)*1099511628211UL;
    return h;
}
extern ssize_t __real_pread(int,void *,size_t,off_t);
extern int __real_fsync(int);
extern int __real_rename(const char *,const char *);
static int mode;
static size_t read_bytes;
ssize_t __wrap_pread(int fd,void *out,size_t length,off_t offset) {
    if(mode==2){errno=EIO;return -1;}
    if(mode==1 && length>311)length=311;
    ssize_t n=__real_pread(fd,out,length,offset);
    if(n>0){read_bytes+=(size_t)n;if(mode==3)((unsigned char *)out)[n-1]^=1;}
    return n;
}
int __wrap_fsync(int fd){if(mode==4){errno=EIO;return -1;}return __real_fsync(fd);}
int __wrap_rename(const char *old,const char *path){if(mode==5){errno=EIO;return -1;}return __real_rename(old,path);}
int main(int argc,char **argv){
    assert(argc==2);char path[256];assert(snprintf(path,sizeof path,"%s/frame",argv[1])<(int)sizeof path);
    const size_t length=614592;unsigned char *input=malloc(length),*output=malloc(length);assert(input && output);
    for(size_t i=0;i<length;i++)input[i]=(unsigned char)(i*29+i/113);
    char stale[320];assert(snprintf(stale,sizeof stale,"%s.part.%d.0",path,getpid())<(int)sizeof stale);
    int stalefd=open(stale,O_CREAT|O_EXCL|O_WRONLY,0600);assert(stalefd>=0);assert(write(stalefd,"stale-part",10)==10);assert(!close(stalefd));
    for(size_t n=0;n<65;n++)assert(hosd_hash(input,n)==reference_hash(input,n));
    assert(hosd_hash(input,length)==reference_hash(input,length));
    for(mode=0;mode<=5;mode++){
        int fd=open(path,O_CREAT|O_TRUNC|O_WRONLY,0600);assert(fd>=0);assert(write(fd,"old-frame",9)==9);assert(!close(fd));
        read_bytes=0;int rc=hosd_persist(path,input,length);
        fd=open(path,O_RDONLY);assert(fd>=0);
        if(mode<=1){assert(!rc);assert(read_bytes==length);assert(read(fd,output,length)==(ssize_t)length);assert(!memcmp(input,output,length));}
        else{assert(rc==-1);assert(read(fd,output,length)==9);assert(!memcmp(output,"old-frame",9));}
        assert(!close(fd));
    }
    stalefd=open(stale,O_RDONLY);assert(stalefd>=0);assert(read(stalefd,output,10)==10);assert(!memcmp(output,"stale-part",10));assert(!close(stalefd));
    assert(!unlink(path));assert(!unlink(stale));free(output);free(input);puts("HOSD_COMPLETE_READBACK_AND_FAILURE_PRESERVATION_PASS");puts("HOSD_STALE_PART_SKIP_PRESERVATION_PASS");return 0;
}
