/* Select the firmware's existing file backend, only in an explicit standalone test. */
#include "fsys-write-trace.h"
extern void *dlvsym(void *, const char *, const char *);
extern char *getenv(const char *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern void _exit(int);
static unsigned calls;
static unsigned int mounted_media_drive;
static unsigned int retired_media_drive;
static int mounted_media_owner;
static unsigned int busy;
static unsigned int hotplug_io;
static unsigned long long previous,cancel_pending,cancel_failures;
extern int snprintf(char *,unsigned long,const char *,...);
extern int open(const char *,int,...),close(int);
extern long write(int,const void *,unsigned long);
extern long read(int,void *,unsigned long);
extern long pread(int,void *,unsigned long,long);
extern int sscanf(const char *,const char *,...),strcmp(const char *,const char *);
extern void *memcpy(void *,const void *,unsigned long);
extern int fsync(int),rename(const char *,const char *),getpid(void),kill(int,int);
extern long syscall(long,...);
extern int *__errno_location(void);
extern void *malloc(unsigned long);
extern void free(void *);

/* No constructor: only actual opted-in Fsys calls establish this observer. */
static int sync_observer_pid;
static unsigned long long observed_mount_generation;
static int fsys_sync_enabled(void) {
    const char *value=getenv("A7C2_FSYS_ASYNC_OBSERVE");
    if(!value || value[0]!='1' || value[1])return 0;
    int pid=getpid(),expected=0;
    __atomic_compare_exchange_n(&sync_observer_pid,&expected,pid,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
    return __atomic_load_n(&sync_observer_pid,__ATOMIC_ACQUIRE)==pid;
}
static int fsys_snapshot(const void *source,void *target,unsigned long bytes) {
    uintptr_t address=(uintptr_t)source;
    if(!address || address>INT64_MAX || bytes>(uint64_t)INT64_MAX-address)return 0;
    int fd=open("/proc/self/mem",0);
    int copied=fd>=0 && pread(fd,target,bytes,(long)address)==(long)bytes;
    if(fd>=0)close(fd);
    return copied;
}
static unsigned fsys_path_snapshot(const char *path,char frozen[FSYS_WRITE_PATH_BYTES]) {
    const char *test=getenv("A7C2_FILE_MEDIA_TEST"),*hotplug=getenv("A7C2_SD_HOTPLUG");
    if(!fsys_sync_enabled() && (!test || test[0]!='1' || test[1]) &&
       (!hotplug || hotplug[0]!='1' || hotplug[1]))return 0;
    uintptr_t address=(uintptr_t)path;
    if(!address || address>(uint64_t)INT64_MAX-FSYS_WRITE_PATH_BYTES)return 0;
    int fd=open("/proc/self/mem",0);unsigned bytes=0;
    if(fd>=0) {
        for(unsigned i=0;i<FSYS_WRITE_PATH_BYTES;i++) {
            if(pread(fd,frozen+i,1,(long)(address+i))!=1)break;
            if(!frozen[i]){bytes=i;break;}
        }
        close(fd);
    }
    if(!bytes)frozen[0]=0;
    return bytes;
}

static void *original_fsys(const char *name) {
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    void *function=lookup?lookup((void *)-1,name):0;
    if(!function){printf("FSYS_TRACE_RESOLVE_FAILED %s\n",name);fflush(0);_exit(126);}
    return function;
}
static int hotplug_enabled(void) {
    const char *value=getenv("A7C2_SD_HOTPLUG");return value && value[0]=='1' && !value[1];
}
static unsigned long long hotplug_generation(void) {
    if(!hotplug_enabled())return 0;
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    unsigned long long (*generation)(void)=lookup?lookup(0,"native_rm_file_media_generation"):0;
    return generation?generation():0;
}
static void hotplug_observed(unsigned long long generation,unsigned int kind,const char *path,unsigned int drive,int rc,unsigned int before,unsigned int after) {
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    void (*observe)(unsigned long long,unsigned int,unsigned int,int,unsigned int,unsigned int,int)=
        lookup?lookup(0,"native_rm_file_fsys_observed"):0;
    int validated=path && (!strcmp(path,"/nondev/rm2") || !strcmp(path,"/dev/mmca"));
    if(observe)observe(generation,kind,drive,rc,before,after,validated);
}
static unsigned long long fsys_sync_generation(void) {
    if(__atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)!=getpid() ||
       !__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE))return 0;
    /* native_rm_file_media_generation is hotplug-only; do not fabricate its epoch. */
    return hotplug_enabled()?hotplug_generation():__atomic_load_n(&observed_mount_generation,__ATOMIC_ACQUIRE);
}
struct fsys_sync_call {
    int enabled;
    unsigned file;
    unsigned long long generation;
    struct fsys_sync_context context;
};
static struct fsys_sync_call fsys_sync_before(unsigned long long handle,void *caller) {
    struct fsys_sync_call call={0,0,0,{(uint64_t)(uintptr_t)caller,0,0}};
    call.enabled=fsys_sync_enabled();
    if(call.enabled) {
        call.generation=fsys_sync_generation();
        call.file=fsys_sync_trace_file(handle,call.generation);
    }
    return call;
}
static void fsys_sync_media(const char *operation,int result,int error) {
    if(!fsys_sync_enabled())return;
    char line[280];int n=snprintf(line,sizeof line,
        "FSYS_SYNC_MEDIA pid=%d domain=%s event=%s generation=%llu drive=%u result=%d errno=%d\n",
        getpid(),hotplug_enabled()?"native_hotplug":"observed_mount",operation,fsys_sync_generation(),
        __atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE),result,error);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
}
static void fsys_sync_mutation(struct fsys_sync_call call,unsigned long long handle,int reason) {
    if(call.enabled)fsys_sync_trace_invalidate(call.file,handle,call.generation,reason);
}
static void fsys_sync_mutation_end(struct fsys_sync_call call,unsigned long long handle,int reason,
                                   const char *operation,int result,int error) {
    if(!call.enabled)return;
    fsys_sync_mutation(call,handle,reason);
    char line[300];int n=snprintf(line,sizeof line,
        "FSYS_SYNC_MUTATION pid=%d op=%s file=%u handle=%llx generation=%llu result=%d errno=%d reason=%d caller=%llx\n",
        getpid(),operation,call.file,handle,call.generation,result,error,reason,(unsigned long long)call.context.caller);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
}
static void fsys_trace(const char *operation,const char *path,unsigned long long handle,unsigned int flags,int result) {
    const char *enabled=getenv("A7C2_FILE_MEDIA_TEST");
    if(!enabled || enabled[0]!='1' || enabled[1])return;
    int error=*__errno_location();
    char line[420];
    int n=snprintf(line,sizeof line,"FSYS_FILE_TRACE op=%s path=%.220s handle=%llx flags=%#x result=%d hex=%#x\n",
                   operation,path?path:"-",handle,flags,result,(unsigned int)result);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
    *__errno_location()=error;
}
/* Passthrough-only observation of the native MPR still writer's 0x508-byte
 * request.  It never edits or adds a request; normal file-media behavior
 * remains unchanged when the flag is absent. */
static void async_write_trace(const unsigned char *request, int result) {
    const unsigned char *p=request;char path[128];unsigned int areas=0;unsigned long long cb=0,cookie=0;
    unsigned long long hash=14695981039346656037ull;
    for(unsigned int i=0;i<0x508;i++){hash^=p[i];hash*=1099511628211ull;}
    memcpy(path,p,127);path[127]=0;
    memcpy(&areas,p+0x4f0,4);memcpy(&cb,p+0x4f8,8);memcpy(&cookie,p+0x500,8);
    char line[420];int n=snprintf(line,sizeof line,
        "FSYS_ASYNC_WRITE pid=%d result=%d path=%.127s areas=%u callback=%llx cookie=%llx request_fnv1a64=%016llx\n",
        getpid(),result,path,areas,cb,cookie,hash);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
}
int Fsys_WriteDirectFileAsyncV2(void *request) {
    int incoming_error=*__errno_location();
    int (*function)(void *)=original_fsys("Fsys_WriteDirectFileAsyncV2");
    unsigned char snapshot[0x508];int captured=0;
    const char *enabled=getenv("A7C2_FSYS_ASYNC_OBSERVE");
    static unsigned int records;
    /* The original API queues the request asynchronously; its caller owns the
     * stack object, so never inspect it after the passthrough returns. */
    if(enabled && enabled[0]=='1' && !enabled[1] && request){
        unsigned int n=__atomic_load_n(&records,__ATOMIC_RELAXED);
        while(n<32 && !__atomic_compare_exchange_n(&records,&n,n+1,0,__ATOMIC_RELAXED,__ATOMIC_RELAXED)){}
        if(n<32 && (unsigned long)request<=0x7ffffffffffffaf7UL){
            int fd=open("/proc/self/mem",0);
            if(fd>=0){captured=pread(fd,snapshot,sizeof snapshot,(long)request)==sizeof snapshot;close(fd);}
        }
    }
    int sync_observing=enabled && enabled[0]=='1' && !enabled[1];
    if(sync_observing)fsys_sync_trace_invalidate(0,0,0,-2010);
    unsigned token=captured?fsys_write_trace_begin(snapshot):0;
    if(!captured)fsys_write_trace_unobserved();
    *__errno_location()=incoming_error;
    int rc=function(request);int error=*__errno_location();
    if(sync_observing)fsys_sync_trace_invalidate(0,0,0,-2010);
    if(captured)async_write_trace(snapshot,rc);
    fsys_write_trace_submit(token,rc);
    *__errno_location()=error;return rc;
}
/* The original MPR loads these exported callbacks through its GOT.  Observe
 * their real invocations without replacing either field in the request. */
void native_mpr_fsys_callback(void *,int,const void *) __asm__(MPR_FSYS_CALLBACK_SYMBOL);
void native_mpr_fsys_callback(void *cookie,int rc,const void *result) {
    int incoming_error=*__errno_location();
    void (*function)(void *,int,const void *)=original_fsys(MPR_FSYS_CALLBACK_SYMBOL);
    void (*self)(void *,int,const void *)=native_mpr_fsys_callback;
    unsigned long long address=0;
    _Static_assert(sizeof self==sizeof address,"64-bit original callback ABI required");
    memcpy(&address,&self,sizeof address);
    *__errno_location()=incoming_error;
    unsigned token=fsys_write_trace_callback(cookie,rc,result,address);
    *__errno_location()=incoming_error;
    function(cookie,rc,result);
    int error=*__errno_location();
    fsys_write_trace_callback_return(token);
    *__errno_location()=error;
}
void native_mpr_write_finished(void *) __asm__(MPR_WRITE_FINISHED_SYMBOL);
void native_mpr_write_finished(void *input) {
    int incoming_error=*__errno_location();
    void (*function)(void *)=original_fsys(MPR_WRITE_FINISHED_SYMBOL);
    struct fsys_write_finished captured=fsys_write_trace_finished_begin(input);
    *__errno_location()=incoming_error;
    function(input);
    int error=*__errno_location();
    fsys_write_trace_finished_return(captured);
    *__errno_location()=error;
}
/* Optional content observation of actual original calls after a reinsert.
 * Writes use a pre-call snapshot; reads copy their output through self/mem. */
static void *fsys_content_snapshot(unsigned long long generation,const void *data,int count) {
    const char *enabled=getenv("A7C2_FSYS_CONTENT_OBSERVE");
    static unsigned records;
    if(!enabled || enabled[0]!='1' || enabled[1] || generation<3 || count<=0 ||
       (unsigned)count>FSYS_WRITE_OBSERVATION_LIMIT)return 0;
    if(__atomic_fetch_add(&records,1,__ATOMIC_RELAXED)>=256)return 0;
    void *snapshot=malloc((unsigned)count);
    if(snapshot && !fsys_snapshot(data,snapshot,(unsigned)count)){free(snapshot);snapshot=0;}
    return snapshot;
}
static void fsys_content_trace(const char *operation,unsigned long long generation,unsigned long long handle,
                               const void *snapshot,int count,int result) {
    if(!snapshot || result<=0 || result>count)return;
    int error=*__errno_location();
    unsigned long long hash=fsys_write_fnv1a64(snapshot,(unsigned)result);
    char line[250];int n=snprintf(line,sizeof line,
        "FSYS_CONTENT op=%s pid=%d generation=%llu handle=%llx requested=%d actual=%d fnv1a64=%016llx\n",
        operation,getpid(),generation,handle,count,result,hash);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
    *__errno_location()=error;
}
int Fsys_Mount(const char *path,unsigned int flags,char *drive,const void *extra) {
    int incoming_error=*__errno_location();
    unsigned long long generation=hotplug_generation();
    int (*function)(const char *,unsigned int,char *,const void *)=original_fsys("Fsys_Mount");
    int observing=fsys_sync_enabled();char frozen[FSYS_WRITE_PATH_BYTES]={0};
    fsys_path_snapshot(path,frozen);
    if(observing)fsys_sync_trace_invalidate(0,0,fsys_sync_generation(),-2001);
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(path,flags,drive,extra);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    unsigned char actual_drive=0;
    int drive_known=!rc && (observing || frozen[0]) && fsys_snapshot(drive,&actual_drive,1);
    if(!rc && drive_known && actual_drive>='A' && actual_drive<='Z' &&
       (!strcmp(frozen,"/nondev/rm2") || !strcmp(frozen,"/dev/mmca"))) {
        __atomic_store_n(&mounted_media_owner,getpid(),__ATOMIC_RELEASE);
        __atomic_store_n(&mounted_media_drive,actual_drive,__ATOMIC_RELEASE);
        __atomic_store_n(&retired_media_drive,0,__ATOMIC_RELEASE);
        if(observing && !hotplug_enabled())__atomic_add_fetch(&observed_mount_generation,1,__ATOMIC_ACQ_REL);
    }
    /* Default mode has no observation probes, but retains its original mount bookkeeping. */
    if(!observing && !frozen[0] && !rc && drive && path &&
       (!strcmp(path,"/nondev/rm2") || !strcmp(path,"/dev/mmca"))) {
        __atomic_store_n(&mounted_media_owner,getpid(),__ATOMIC_RELEASE);
        __atomic_store_n(&mounted_media_drive,(unsigned char)*drive,__ATOMIC_RELEASE);
        __atomic_store_n(&retired_media_drive,0,__ATOMIC_RELEASE);
    }
    fsys_trace("Mount",frozen,actual_drive,flags,rc);
    if(hotplug_enabled() && !rc && drive){
        unsigned int (*mask)(void)=original_fsys("Fsys_GetMountDrives");
        unsigned int after=mask();
        hotplug_observed(generation,0,frozen[0]?frozen:path,drive_known?actual_drive:(unsigned char)*drive,rc,0,after);
    }
    if(observing)fsys_sync_media("Mount",rc,error);
    *__errno_location()=error;return rc;
}
/* Observe the original completion; never initiate an unmount for hotplug. */
int Fsys_Unmount(unsigned char drive,unsigned int flags) {
    int incoming_error=*__errno_location();
    unsigned long long generation=hotplug_generation();
    struct fsys_sync_call call=fsys_sync_before(0,__builtin_return_address(0));
    fsys_sync_mutation(call,0,-2002);
    int (*function)(unsigned char,unsigned int)=original_fsys("Fsys_Unmount");
    int enabled=hotplug_enabled();unsigned int (*mask)(void)=enabled?original_fsys("Fsys_GetMountDrives"):0;
    unsigned int before=mask?mask():0;
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(drive,flags);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    if(enabled){
        unsigned int after=mask();
        if(!rc && drive>='A' && drive<='Z' && !(after&(1u<<(drive-'A'))) &&
           __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)==getpid() &&
           __atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE)==drive){
            __atomic_store_n(&mounted_media_drive,0,__ATOMIC_RELEASE);
            __atomic_store_n(&retired_media_drive,drive,__ATOMIC_RELEASE);
        }
        hotplug_observed(generation,1,0,drive,rc,before,after);
    } else if(call.enabled && !rc && __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)==getpid() &&
              __atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE)==drive) {
        __atomic_store_n(&mounted_media_drive,0,__ATOMIC_RELEASE);
        __atomic_add_fetch(&observed_mount_generation,1,__ATOMIC_ACQ_REL);
    }
    fsys_trace("Unmount",0,drive,flags,rc);
    if(call.enabled)fsys_sync_media("Unmount",rc,error);
    *__errno_location()=error;return rc;
}
int Fsys_Mkdir(const char *path) {
    int incoming_error=*__errno_location();char frozen[FSYS_WRITE_PATH_BYTES]={0};
    fsys_path_snapshot(path,frozen);
    int (*function)(const char *)=original_fsys("Fsys_Mkdir");
    *__errno_location()=incoming_error;
    int rc=function(path);int error=*__errno_location();
    fsys_trace("Mkdir",frozen,0,0,rc);*__errno_location()=error;return rc;
}
int Fsys_Open(const char *path,unsigned long long *handle,unsigned int flags) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(0,__builtin_return_address(0));
    unsigned drive_before=call.enabled?__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE):0;
    char frozen[FSYS_WRITE_PATH_BYTES]={0};unsigned bytes=fsys_path_snapshot(path,frozen);
    int (*function)(const char *,unsigned long long *,unsigned int)=original_fsys("Fsys_Open");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(path,handle,flags);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    unsigned long long actual_handle=0;
    if(!rc && (call.enabled || frozen[0]))fsys_snapshot(handle,&actual_handle,sizeof actual_handle);
    if(call.enabled) {
        unsigned long long after=fsys_sync_generation();
        if(after!=call.generation)fsys_sync_trace_invalidate(0,0,after,-2003);
        /* shortcut: flags->backend truncation/initial cursor is not source-closed;
         * keep both unknown until original metadata/Seek supplies evidence. */
        fsys_sync_trace_open(frozen,bytes,actual_handle,
                             after==call.generation && (unsigned char)frozen[0]==drive_before?after:0,
                             flags,rc,error,0,0,0,0,call.context);
    }
    fsys_trace("Open",frozen,actual_handle,flags,rc);*__errno_location()=error;return rc;
}
int Fsys_Write(unsigned long long handle,const void *data,int count) {
    int incoming_error=*__errno_location();
    unsigned long long generation=hotplug_generation();
    struct fsys_sync_call call=fsys_sync_before(handle,__builtin_return_address(0));
    int (*function)(unsigned long long,const void *,int)=original_fsys("Fsys_Write");
    struct fsys_sync_source source={(uint64_t)(uintptr_t)data,0,0,FSYS_SYNC_VIRTUAL};
    unsigned ticket=call.enabled?fsys_sync_trace_write_begin(call.file,handle,call.generation,source,count,0,call.context):0;
    void *snapshot=fsys_content_snapshot(generation,data,count);
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(handle,data,count);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    if(call.enabled)fsys_sync_trace_write_end(ticket,handle,fsys_sync_generation(),rc,error);
    fsys_content_trace("Write",generation,handle,snapshot,count,rc);free(snapshot);
    if(rc<0 || rc!=count)fsys_trace("Write",0,handle,(unsigned int)count,rc);
    *__errno_location()=error;return rc;
}
int Fsys_Read(unsigned long long handle,void *data,int count) {
    int incoming_error=*__errno_location();
    unsigned long long generation=hotplug_generation();
    struct fsys_sync_call call=fsys_sync_before(handle,__builtin_return_address(0));
    /* Ordinary Read advances a writer's cursor; no extra Seek may be inserted. */
    fsys_sync_mutation(call,handle,-2004);
    int (*function)(unsigned long long,void *,int)=original_fsys("Fsys_Read");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(handle,data,count);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    void *snapshot=rc>0 && rc<=count?fsys_content_snapshot(generation,data,rc):0;
    fsys_content_trace("Read",generation,handle,snapshot,count,rc);free(snapshot);
    *__errno_location()=error;return rc;
}
int Fsys_Close(unsigned long long handle) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(handle,__builtin_return_address(0));
    int (*function)(unsigned long long)=original_fsys("Fsys_Close");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(handle);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    if(call.enabled)fsys_sync_trace_close(call.file,handle,fsys_sync_generation(),rc,error,call.context);
    *__errno_location()=error;return rc;
}
/* Original Fsys_FTruncate entry saves x0/x1 and overwrites x2 before use. */
int Fsys_FTruncate(unsigned long long handle,unsigned long long bytes) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(handle,__builtin_return_address(0));
    fsys_sync_mutation(call,handle,-2005);
    int (*function)(unsigned long long,unsigned long long)=original_fsys("Fsys_FTruncate");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(handle,bytes);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    fsys_sync_mutation_end(call,handle,-2005,"FTruncate",rc,error);
    char size[40];snprintf(size,sizeof size,"bytes=%llu",bytes);
    fsys_trace("FTruncate",size,handle,0,rc);*__errno_location()=error;return rc;
}
int Fsys_WriteAndFlush(unsigned long long handle,const void *data,int count) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(handle,__builtin_return_address(0));
    int (*function)(unsigned long long,const void *,int)=original_fsys("Fsys_WriteAndFlush");
    struct fsys_sync_source source={(uint64_t)(uintptr_t)data,0,0,FSYS_SYNC_VIRTUAL};
    unsigned ticket=call.enabled?fsys_sync_trace_write_begin(call.file,handle,call.generation,source,count,1,call.context):0;
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(handle,data,count);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    if(call.enabled)fsys_sync_trace_write_end(ticket,handle,fsys_sync_generation(),rc,error);
    fsys_trace("WriteAndFlush",0,handle,(unsigned int)count,rc);*__errno_location()=error;return rc;
}
int Fsys_WriteFile(const char *path,void *parameters) {
    int incoming_error=*__errno_location();char frozen[FSYS_WRITE_PATH_BYTES]={0};
    struct fsys_sync_call call=fsys_sync_before(0,__builtin_return_address(0));
    fsys_sync_mutation(call,0,-2006);fsys_path_snapshot(path,frozen);
    int (*function)(const char *,void *)=original_fsys("Fsys_WriteFile");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);
    *__errno_location()=incoming_error;
    int rc=function(path,parameters);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    fsys_sync_mutation_end(call,0,-2006,"WriteFile",rc,error);
    fsys_trace("WriteFile",frozen,0,0,rc);*__errno_location()=error;return rc;
}
int Fsys_Seek(unsigned long long handle,long long offset,unsigned int origin,void *result) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(handle,__builtin_return_address(0));
    int (*function)(unsigned long long,long long,unsigned int,void *)=original_fsys("Fsys_Seek");
    *__errno_location()=incoming_error;
    int rc=function(handle,offset,origin,result);int error=*__errno_location();
    uint64_t position=0;unsigned known=call.enabled && !rc && fsys_snapshot(result,&position,sizeof position);
    if(call.enabled)fsys_sync_trace_position(call.file,handle,fsys_sync_generation(),rc,error,known,position,call.context);
    char text[48];snprintf(text,sizeof text,"offset=%lld",offset);
    fsys_trace("Seek",text,handle,origin,rc);*__errno_location()=error;return rc;
}
/* Public ELF Combine saves only x0/x1, supplies w2=0 to its lower helper.
 * Rename and Remove likewise consume two paths and one path respectively. */
int Fsys_Combine(const char *first,const char *second) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(0,__builtin_return_address(0));
    fsys_sync_mutation(call,0,-2007);
    int (*function)(const char *,const char *)=original_fsys("Fsys_Combine");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);*__errno_location()=incoming_error;
    int rc=function(first,second);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    fsys_sync_mutation_end(call,0,-2007,"Combine",rc,error);
    *__errno_location()=error;return rc;
}
int Fsys_Rename(const char *first,const char *second) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(0,__builtin_return_address(0));
    fsys_sync_mutation(call,0,-2008);
    int (*function)(const char *,const char *)=original_fsys("Fsys_Rename");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);*__errno_location()=incoming_error;
    int rc=function(first,second);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    fsys_sync_mutation_end(call,0,-2008,"Rename",rc,error);
    *__errno_location()=error;return rc;
}
int Fsys_Remove(const char *path) {
    int incoming_error=*__errno_location();
    struct fsys_sync_call call=fsys_sync_before(0,__builtin_return_address(0));
    fsys_sync_mutation(call,0,-2009);
    int (*function)(const char *)=original_fsys("Fsys_Remove");
    __atomic_fetch_add(&hotplug_io,1,__ATOMIC_ACQ_REL);*__errno_location()=incoming_error;
    int rc=function(path);int error=*__errno_location();
    __atomic_fetch_sub(&hotplug_io,1,__ATOMIC_ACQ_REL);
    fsys_sync_mutation_end(call,0,-2009,"Remove",rc,error);
    *__errno_location()=error;return rc;
}
int Fsys_GetFreeSpace(unsigned char drive,void *output) {
    int (*function)(unsigned char,void *)=original_fsys("Fsys_GetFreeSpace");
    int rc=function(drive,output);
    /* The original caller derives its quantities from words 3..7 of this struct,
       not from word 0, so record the whole bounded struct instead of one word. */
    {
        const char *enabled=getenv("A7C2_FILE_MEDIA_TEST");
        if(enabled && enabled[0]=='1' && !enabled[1]){
            char line[300];int n=0;unsigned int i;
            n+=snprintf(line+n,sizeof line-n,"FSYS_FREE_STRUCT drive=%u result=%d words=",(unsigned int)drive,rc);
            for(i=0;i<8 && n>0 && n<(int)sizeof line-12;i++){
                unsigned int word=0;
                if(!rc && output)word=((const unsigned int *)output)[i];
                n+=snprintf(line+n,sizeof line-n,"%s%08x",i?",":"",word);
            }
            n+=snprintf(line+n,sizeof line-n,"\n");
            if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
        }
    }
    fsys_trace("GetFreeSpace",0,!rc&&output?*(unsigned int *)output:0,drive,rc);return rc;
}

static int flush_store(const char *path,const char *text,int length,int flags) {
    char temporary[120];
    int n=snprintf(temporary,sizeof temporary,"%s.new",path);
    if(length<=0 || n<=0 || n>=(int)sizeof temporary)return 0;
    int fd=open(temporary,flags,0600);
    int stored=fd>=0 && write(fd,text,(unsigned long)length)==length && !fsync(fd);
    if(fd>=0 && close(fd))stored=0;
    return stored && !rename(temporary,path);
}

static int flush_store_cancelled(unsigned long long sequence) {
    char path[96],reply[180];
    snprintf(path,sizeof path,"/tmp/sd-flush.%llu.cancelled",sequence);
    int length=snprintf(reply,sizeof reply,"SD_FSYS_CANCELLED seq=%llu pid=%d\n",sequence,getpid());
    /* Failed attempts can leave .new behind; only this acknowledgement is retried. */
    if(flush_store(path,reply,length,0x8241)){cancel_failures=0;return 1;}
    int error=*__errno_location();
    if(cancel_failures!=~0ULL)cancel_failures++;
    if(cancel_failures<=8 || !(cancel_failures&(cancel_failures-1))) {
        printf("SD_FSYS_CANCELLED_FAILED seq=%llu errno=%d\n",sequence,error);fflush(0);
    }
    *__errno_location()=error;
    return 0;
}

static int flush_enter(void) {
    if(__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE) &&
       __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)!=getpid())return 0;
    unsigned int expected=0;
    return __atomic_compare_exchange_n(&busy,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
}

static int fsys_native_write_readback(unsigned long long generation,int flush_rc,int flush_errno) {
    int incoming_error=*__errno_location();
    const char *enabled=getenv("A7C2_FSYS_ASYNC_OBSERVE");
    if(!enabled || enabled[0]!='1' || enabled[1]){*__errno_location()=incoming_error;return 0;}
    struct fsys_native_read_ops ops;
    ops.open=original_fsys("Fsys_Open");
    ops.read=original_fsys("Fsys_Read");
    ops.close=original_fsys("Fsys_Close");
    *__errno_location()=incoming_error;
    fsys_write_trace_readback(&ops);
    if(fsys_sync_enabled()) {
        int stable=generation && generation==fsys_sync_generation() && !__atomic_load_n(&hotplug_io,__ATOMIC_ACQUIRE);
        *__errno_location()=incoming_error;
        if(!stable)fsys_sync_trace_invalidate(0,0,generation,-2011);
        else fsys_sync_trace_readback_all(generation,flush_rc,flush_errno,&ops);
    }
    *__errno_location()=incoming_error;
    return 1;
}
/* Same-process real flush without STOP: the original removal consumer must run. */
int file_media_hotplug_flush(unsigned long long generation,unsigned int drive) {
    if(!hotplug_enabled() || !generation || !drive ||
       __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)!=getpid() ||
       __atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE)!=drive || !flush_enter())return -1021;
    int rc=-1021,result_error=*__errno_location();
    if(!cancel_pending && !__atomic_load_n(&hotplug_io,__ATOMIC_ACQUIRE)){
        int (*flush)(unsigned char)=original_fsys("Fsys_FlushVolume");
        int incoming_error=*__errno_location();
        unsigned long long observed_generation=fsys_sync_enabled()?fsys_sync_generation():0;
        *__errno_location()=incoming_error;
        rc=flush((unsigned char)drive);int error=*__errno_location();result_error=error;
        if(!rc && (__atomic_load_n(&hotplug_io,__ATOMIC_ACQUIRE) ||
                   __atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE)!=drive))rc=-1021;
        if(!rc)fsys_native_write_readback(observed_generation,rc,error);
        *__errno_location()=error;
    }
    char line[180];int n=snprintf(line,sizeof line,
        "SD_HOTPLUG_FLUSH generation=%llu pid=%d drive=%u rc=%d inflight=%u\n",
        generation,getpid(),drive,rc,__atomic_load_n(&hotplug_io,__ATOMIC_ACQUIRE));
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);*__errno_location()=result_error;return rc;
}

void file_media_flush_cancel_retry(void) {
    if(!flush_enter())return;
    if(cancel_pending && flush_store_cancelled(cancel_pending))cancel_pending=0;
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);
}

static void flush_stage_trace(const char *stage,unsigned long long sequence,unsigned int drive,const char *field,int result) {
    int error=*__errno_location();char line[240];
    int n=snprintf(line,sizeof line,"SD_FSYS_FLUSH_STAGE stage=%s seq=%llu pid=%d tid=%ld drive=%u %s=%d errno=%d\n",
                   stage,sequence,getpid(),syscall(178),drive,field,result,error);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
    *__errno_location()=error;
}

/* Reply rename precedes cancel lookup; host publishes cancel before reading this seq's reply. */
void file_media_flush_pending(void) {
    if(!flush_enter()) {
        static unsigned int reported;
        int error=*__errno_location();
        /* Polling must not read the request or flood the console while another owner holds busy. */
        if(!__atomic_exchange_n(&reported,1,__ATOMIC_RELAXED)) {
            char line[180];int n=snprintf(line,sizeof line,
                "SD_FSYS_FLUSH_ADMISSION_BLOCKED pid=%d tid=%ld mounted_owner_pid=%d busy=%u\n",
                getpid(),syscall(178),__atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE),
                __atomic_load_n(&busy,__ATOMIC_ACQUIRE));
            if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
        }
        *__errno_location()=error;return;
    }
    /* A failed acknowledgement must settle before a newer request can replace it. */
    if(cancel_pending) {
        if(!flush_store_cancelled(cancel_pending))goto done;
        cancel_pending=0;
    }
    int fd=open("/tmp/sd-flush.request",0x8000);
    char request[96];long n=fd>=0?read(fd,request,sizeof request-1):-1;
    if(fd>=0)close(fd);
    if(n>0) {
        request[n]=0;unsigned long long sequence=0;char extra;
        if(sscanf(request,"%llu %c",&sequence,&extra)==1 && sequence>previous) {
            previous=sequence;
            unsigned int drive=__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE);
            flush_stage_trace("accepted",sequence,drive,"admitted",1);
            int (*flush)(unsigned char)=original_fsys("Fsys_FlushVolume");
            int rc=-1021;
            if(drive) {
                flush_stage_trace("before",sequence,drive,"calling",1);
                int incoming_error=*__errno_location();
                unsigned long long generation=fsys_sync_enabled()?fsys_sync_generation():0;
                *__errno_location()=incoming_error;
                rc=flush((unsigned char)drive);int error=*__errno_location();
                flush_stage_trace("after",sequence,drive,"rc",rc);
                if(!rc && __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)==getpid() &&
                   fsys_native_write_readback(generation,rc,error)){
                    rc=flush((unsigned char)drive);
                    flush_stage_trace("after_readback",sequence,drive,"rc",rc);
                }
            }
            unsigned int retired=0,retired_mask=0;
            if(!drive && hotplug_enabled() && !__atomic_load_n(&hotplug_io,__ATOMIC_ACQUIRE)){
                void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
                int (*confirmed)(void)=lookup?lookup(0,"native_rm_file_media_retired"):0;
                unsigned int old=__atomic_load_n(&retired_media_drive,__ATOMIC_ACQUIRE);
                if(confirmed && confirmed() && old>='A' && old<='Z'){
                    unsigned int (*mask)(void)=original_fsys("Fsys_GetMountDrives");
                    retired_mask=mask();
                    if(!(retired_mask&(1u<<(old-'A')))){retired=old;rc=0;}
                }
            }
            char path[96],reply[180];
            int length=retired?snprintf(reply,sizeof reply,
                "SD_FSYS_RETIRED seq=%llu pid=%d drive=%u mask=%u unmount_rc=0\n",
                sequence,getpid(),retired,retired_mask):
                snprintf(reply,sizeof reply,"SD_FSYS_FLUSH seq=%llu pid=%d drive=%u rc=%d\n",sequence,getpid(),drive,rc);
            snprintf(path,sizeof path,"/tmp/sd-flush.%llu.reply",sequence);
            int stored=length<(int)sizeof reply && flush_store(path,reply,length,0x80c1);
            flush_stage_trace("reply",sequence,drive,"stored",stored);
            if(stored && !rc) {
                snprintf(path,sizeof path,"/tmp/sd-flush.%llu.cancel",sequence);
                fd=open(path,0x8000);
                int cancelled=fd>=0 || *__errno_location()!=2;
                if(fd>=0)close(fd);
                if(!cancelled && kill(getpid(),19)) {
                    int error=*__errno_location();
                    printf("SD_FSYS_STOP_FAILED seq=%llu errno=%d\n",sequence,error);fflush(0);
                }
                /* A self-SIGSTOP returns only after CONT: persist completion even if the host loses its reply. */
                cancel_pending=sequence;
                if(flush_store_cancelled(sequence))cancel_pending=0;
            }
        }
    }
done:
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);
}

unsigned file_media_configured(void) { return calls; }

void mcmn_param_init(void) {
    void *(*lookup)(void *, const char *) = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    void (*original)(void) = lookup ? lookup((void *)-1, "mcmn_param_init") : 0;
    unsigned (*get)(int) = lookup ? lookup((void *)-1, "mcmn_param_getul") : 0;
    void (*set)(int, unsigned) = lookup ? lookup((void *)-1, "mcmn_param_setul") : 0;
    if (!original || original == mcmn_param_init || !get || !set) {
        printf("FILE_MEDIA_CONFIG_RESOLVE_FAILED\n"); fflush(0); _exit(126);
    }
    original();
    const char *enabled = getenv("A7C2_FILE_MEDIA_TEST");
    if (enabled && enabled[0] == '1' && !enabled[1]) {
        unsigned before = get(0x69);
        set(0x69, 0);
        calls++;
        printf("FILE_MEDIA_CONFIG call=%u EXISTMEDIADRIVER=%u->%u OMIT_WRITE=%u\n",
               calls, before, get(0x69), get(0xf9));
        fflush(0);
    }
}
