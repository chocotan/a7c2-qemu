/* Explicit storage diagnostic, never a camera capture or synthetic completion. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned started;
static void *lookup(void *scope,const char *name){
    void *(*resolve)(void *,const char *)=dlvsym(RTLD_NEXT,"dlsym","GLIBC_2.17");
    return resolve?resolve(scope,name):0;
}
static void report(const char *step,int rc,const char *path,unsigned long long hash){
    char text[280];int n=snprintf(text,sizeof text,
        "FSYS_REINSERT_DIAG step=%s rc=%d path=%s bytes=4096 fnv1a64=%016llx scope=explicit_storage_test_not_capture\n",
        step,rc,path?path:"-",hash);
    if(n>0 && n<(int)sizeof text){int fd=open("/dev/console",O_WRONLY|O_CLOEXEC);
        if(fd>=0){(void)write(fd,text,(unsigned)n);(void)close(fd);}}
}
static unsigned long long fnv(const unsigned char *data,unsigned size){
    unsigned long long result=14695981039346656037ull;
    for(unsigned i=0;i<size;i++){result^=data[i];result*=1099511628211ull;}return result;
}
static void diagnostic(void){
    const char *enabled=getenv("A7C2_FSYS_REINSERT_SMOKE"),*name=getenv("A7C2_FSYS_DIAG_NAME");
    if(!enabled || strcmp(enabled,"1") || !name || strlen(name)!=8)return;
    for(unsigned i=0;i<8;i++)if(!((name[i]>='0' && name[i]<='9') || (name[i]>='A' && name[i]<='F')))return;
    unsigned long long (*generation)(void)=lookup(RTLD_DEFAULT,"native_rm_file_media_generation");
    if(!generation || generation()!=3 || __atomic_exchange_n(&started,1,__ATOMIC_ACQ_REL))return;
    unsigned (*mask)(void)=lookup(RTLD_NEXT,"Fsys_GetMountDrives");
    int (*op)(const char *,unsigned long long *,unsigned)=lookup(RTLD_NEXT,"Fsys_Open");
    int (*put)(unsigned long long,const void *,int)=lookup(RTLD_NEXT,"Fsys_Write");
    int (*get)(unsigned long long,void *,int)=lookup(RTLD_NEXT,"Fsys_Read");
    int (*flush)(unsigned long long)=lookup(RTLD_NEXT,"Fsys_Flush");
    int (*shut)(unsigned long long)=lookup(RTLD_NEXT,"Fsys_Close");
    if(!mask || !op || !put || !get || !flush || !shut){report("DONE",-1,0,0);return;}
    unsigned mounts=mask(),index=0;
    if(!mounts || (mounts&(mounts-1))){report("DONE",-2,0,0);return;}
    while(!(mounts&(1u<<index)) && index<26)index++;
    if(index>=26){report("DONE",-2,0,0);return;}
    char path[32];snprintf(path,sizeof path,"%c:/%.8s.BIN",'A'+index,name);
    unsigned long long handle=0;int rc=op(path,&handle,1);
    if(!rc){(void)shut(handle);report("DONE",-3,path,0);return;}
    unsigned char expected[4096],actual[4096];
    for(unsigned i=0;i<sizeof expected;i++)expected[i]=(unsigned char)(i*37+11);
    const char label[]="A7C2 original Fsys reinsert storage diagnostic; not a photo or video\n";
    memcpy(expected,label,sizeof label-1);
    rc=op(path,&handle,0xf);report("OpenWrite",rc,path,0);
    if(rc){report("DONE",-4,path,0);return;}
    rc=put(handle,expected,sizeof expected);report("Write",rc,path,fnv(expected,sizeof expected));
    if(rc!=(int)sizeof expected){(void)shut(handle);report("DONE",-5,path,0);return;}
    rc=flush(handle);report("Flush",rc,path,0);
    if(rc){(void)shut(handle);report("DONE",-6,path,0);return;}
    rc=shut(handle);report("CloseWrite",rc,path,0);
    if(rc){report("DONE",-7,path,0);return;}
    rc=op(path,&handle,1);report("OpenRead",rc,path,0);
    if(rc){report("DONE",-8,path,0);return;}
    rc=get(handle,actual,sizeof actual);report("Read",rc,path,rc==(int)sizeof actual?fnv(actual,sizeof actual):0);
    int closed=shut(handle);report("CloseRead",closed,path,0);
    if(rc!=(int)sizeof actual || memcmp(actual,expected,sizeof actual)){report("DONE",-9,path,0);return;}
    if(closed || generation()!=3 || mask()!=mounts){report("DONE",-10,path,0);return;}
    report("DONE",0,path,fnv(actual,sizeof actual));
    /* The named artifact deliberately remains for independent QMP/card readback. */
}
int Fsys_Read(unsigned long long handle,void *data,int count){
    int (*function)(unsigned long long,void *,int)=lookup(RTLD_NEXT,"Fsys_Read");
    if(!function)_exit(126);
    int result=function(handle,data,count),saved=errno;
    if(result>0 && result<=count)diagnostic();
    errno=saved;return result;
}
