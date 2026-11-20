/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-capture-raw.h"
#include "raw-template.h"
#include <dlfcn.h>
#include <errno.h>
#include <malloc.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

extern int raw_legacy_sscanf(const char *,const char *,...) __asm__("__isoc99_sscanf");

/* One current capture owns the shadow table until its native destructor. */
static struct raw_template_lease lease;
static struct {
    struct capture_output_memory *output;
    uint64_t job,generation;
    uintptr_t base;
    void *raw;
    pid_t pid;
    int armed,failed,prepared,completed,tearing_down;
    uintptr_t original_vptr;
    uintptr_t shadow[18]; /* two ABI prefix words and sixteen libarw slots */
} writer;
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static _Atomic uintptr_t hooked_base;
static _Thread_local int resolving;
static void *(*real_set)(void *,int,size_t);
static void *(*real_factory)(int);
static int (*real_record)(const void *,void *);
int raw_record(const void *,void *) __asm__("_ZN3mpr11RecordStillERKNS_18recordStillInParamEPNS_19recordStillOutParamE");
void *raw_factory(int) __asm__("_ZN9stillutil7createrEN3mpr9StillTypeE");
static uint64_t read64(const void *p){uint64_t v;memcpy(&v,p,8);return v;}
static int mapped(const void *p,size_t bytes,int writing){
    uintptr_t start=(uintptr_t)p;if(!p || bytes>UINTPTR_MAX-start)return 0;
    FILE *f=fopen("/proc/self/maps","r");if(!f)return 0;
    char line[512],mode[5];unsigned long a,b;int ok=0;
    while(fgets(line,sizeof line,f))if(raw_legacy_sscanf(line,"%lx-%lx %4s",&a,&b,mode)==3 &&
        start>=a && start+bytes<=b && mode[0]=='r' && (!writing || mode[1]=='w')){ok=1;break;}
    fclose(f);return ok;
}
static int writable(void *p,size_t bytes){return mapped(p,bytes,1);}
static int current(void){
    uint64_t serial=0,generation=0;uintptr_t base=0;
    int rc=functional_capture_raw_writer_current(writer.output,&serial,&base,&generation);
    return rc?rc:writer.pid!=getpid() || serial!=writer.job || generation!=writer.generation || base!=writer.base?-ESTALE:0;
}
static int owns(void *context,uint64_t serial,void *raw,void *app){
    (void)context;
    if(!writer.armed || (writer.failed && !writer.tearing_down) || serial!=writer.job || raw!=writer.raw || current())return 0;
    /* Objects originate in the pinned factory/prepare path, not arbitrary DMM addresses. */
    if(!writable(raw,0x14d8) || !writable(app,0x26e0) ||
       (read64(raw)!=writer.base+0x2fb6e0 && read64(raw)!=(uintptr_t)&writer.shadow[2]) ||
       read64((char *)raw+0x1488)!=(uintptr_t)app)return 0;
    return malloc_usable_size(raw)>=0x14d8 && malloc_usable_size(app)>=0x26e0;
}
static void resolve_memset(void) __attribute__((constructor));
static void resolve_memset(void){
    if(real_set || resolving)return;
    resolving=1;
    void *symbol=dlsym(RTLD_NEXT,"memset");
    memcpy(&real_set,&symbol,sizeof symbol);
    resolving=0;
}
static int resolve(void){
    if(real_set && real_factory)return 0;
    if(resolving)return -EDEADLK;
    resolving=1;
    void *a=dlsym(RTLD_NEXT,"memset"),*b=dlsym(RTLD_NEXT,"_ZN9stillutil7createrEN3mpr9StillTypeE");
    memcpy(&real_set,&a,sizeof a);memcpy(&real_factory,&b,sizeof b);resolving=0;
    return real_set && real_factory?0:-ENOSYS;
}
static int resolve_record(void){
    if(real_record)return 0;
    void *symbol=dlsym(RTLD_NEXT,"_ZN3mpr11RecordStillERKNS_18recordStillInParamEPNS_19recordStillOutParamE");
    memcpy(&real_record,&symbol,sizeof symbol);
    return real_record?0:-ENOSYS;
}
int functional_capture_raw_native_writer_arm(struct capture_output_memory *output){
    int rc=resolve();if(rc)return rc;
    rc=resolve_record();if(rc)return rc;
    uint64_t serial,generation;uintptr_t base;
    rc=functional_capture_raw_writer_current(output,&serial,&base,&generation);if(rc)return rc;
    Dl_info info;if(!dladdr((void *)real_factory,&info) || (uintptr_t)info.dli_fbase!=base ||
       (uintptr_t)real_factory!=base+0xc4de0 ||
       !dladdr((void *)real_record,&info) || (uintptr_t)info.dli_fbase!=base ||
       (uintptr_t)real_record!=base+0xeb260)return -ELIBBAD;
    static const unsigned char pin[16]={0xe0,0x03,0x14,0xaa,0x02,0x41,0x81,0xd2,0x01,0x00,0x80,0x52,0x6f,0x15,0xf8,0x97};
    if(memcmp((void *)(base+0x277c58),pin,sizeof pin) ||
       read64((void *)(base+0x2fb6e0))!=base+0x2671c8 ||
       read64((void *)(base+0x2fb6e8))!=base+0x2672c0 ||
       read64((void *)(base+0x2fb758))!=base+0x267188 ||
       read64((void *)(base+0x2fb6f8))!=base+0x268f5c ||
       read64((void *)(base+0x2fbd30))!=base+0x277b7c ||
       read64((void *)(base+0x2fbd38))!=base+0x278af0)return -ELIBBAD;
    if(dlsym(RTLD_DEFAULT,"memset")!=(void *)memset ||
       dlsym(RTLD_DEFAULT,"_ZN9stillutil7createrEN3mpr9StillTypeE")!=(void *)raw_factory ||
       dlsym(RTLD_DEFAULT,"_ZN3mpr11RecordStillERKNS_18recordStillInParamEPNS_19recordStillOutParamE")!=(void *)raw_record)return -ELIBBAD;
    uint8_t raw_info[CAPTURE_RAW_INFO_BYTES];rc=capture_output_memory_raw_info(output,raw_info);if(rc)return rc;
    pthread_mutex_lock(&lock);
    if(writer.armed || lease.active)rc=-EBUSY;
    else{writer.output=output;writer.job=serial;writer.generation=generation;writer.base=base;
         writer.raw=NULL;writer.failed=writer.prepared=writer.completed=writer.tearing_down=0;
         writer.pid=getpid();writer.armed=1;atomic_store(&hooked_base,base);}
    pthread_mutex_unlock(&lock);return rc;
}
int raw_record(const void *input,void *output){
    int saved=errno;
    if(resolve_record()){errno=ENOSYS;return -ENOSYS;}
    struct capture_output_memory *owned=NULL;
    uint64_t serial=0,generation=0;uintptr_t base=0;
    pthread_mutex_lock(&lock);
    if(writer.armed && !writer.failed &&
       (uintptr_t)real_record==writer.base+0xeb260 && !current() && mapped(input,0x20,0)){
        uint8_t expected[CAPTURE_RAW_INFO_BYTES];
        const void *raw_info=(const void *)(uintptr_t)read64((const char *)input+0x18);
        if(mapped(raw_info,sizeof expected,0) && !capture_output_memory_raw_info(writer.output,expected) &&
           !memcmp(raw_info,expected,sizeof expected)){
            owned=writer.output;serial=writer.job;generation=writer.generation;base=writer.base;
        }
    }
    pthread_mutex_unlock(&lock);
    if(owned)functional_capture_raw_native_event(owned,serial,base,generation,0,0);
    errno=saved;
    int result=real_record(input,output);
    saved=errno;
    /* The factory destructor can disarm writer while RecordStill is executing. */
    if(owned)functional_capture_raw_native_event(owned,serial,base,generation,1,result);
    errno=saved;return result;
}
int functional_capture_raw_native_writer_ready(struct capture_output_memory *output){
    pthread_mutex_lock(&lock);
    int rc=writer.output!=output?-ESTALE:current();
    if(!rc)rc=writer.failed?writer.failed:!writer.prepared?-ENODATA:0;
    pthread_mutex_unlock(&lock);return rc;
}
static int serialized_short14(void){
    lease.serialized_short14=0;
    void *app=lease.app_object;
    if(!owns(&writer,writer.job,writer.raw,app))return -ESTALE;
    uintptr_t ifd=read64((char *)app+0x1850);
    if(!writable((void *)ifd,0x1c8) || malloc_usable_size((void *)ifd)<0x1c8)return -ELIBBAD;
    struct capture_output_span header;
    int rc=capture_output_memory_span(writer.output,CAPTURE_OUT_HEADER,&header);if(rc)return rc;
    uintptr_t start=read64((void *)(ifd+56));
    uint32_t offset;memcpy(&offset,(void *)(ifd+72),sizeof offset);
    /* @26c260 walks 24-byte entries; @26c444 publishes inline value at +8. */
    for(unsigned i=0;i<3;++i){
        const unsigned char *entry=(const unsigned char *)app+0x19f0+24*i;
        uint32_t tag,count;memcpy(&tag,entry,4);memcpy(&count,entry+8,4);
        if(count && (tag&0xffff)!=0xffff){if(offset>UINT32_MAX-12)return -EOVERFLOW;offset+=12;}
    }
    if(start<header.cpu || start-header.cpu>header.capacity ||
       offset>header.capacity-(start-header.cpu) ||
       header.capacity-(start-header.cpu)-offset<12)return -ERANGE;
    const unsigned char *entry=(const unsigned char *)(start+offset);
    static const unsigned char inline14[12]={2,1,3,0,1,0,0,0,14,0,0,0};
    if(!mapped(entry,sizeof inline14,0) || memcmp(entry,inline14,sizeof inline14))return -EPROTO;
    lease.serialized_short14=(uintptr_t)(entry+8);
    return 0;
}
static void raw_destroy(void *object,unsigned slot){
    void (*destroy)(void *)=NULL;
    pthread_mutex_lock(&lock);
    int rc=object!=writer.raw || !writer.armed?-ESTALE:current();
    if(!rc && (!writable(object,0x14d8) || read64(object)!=(uintptr_t)&writer.shadow[2]))rc=-ELIBBAD;
    if(!rc){
        uintptr_t address=writer.original_vptr;
        memcpy(object,&address,sizeof address);
        writer.tearing_down=1;
        if(lease.active){
            /* Early failure can leave the original lease pointer unconsumed. */
            if(!owns(&writer,writer.job,writer.raw,lease.app_object))rc=-ESTALE;
            else if(read64((char *)lease.app_object+0x1a48)!=(uintptr_t)lease.short14)rc=serialized_short14();
            if(!rc)rc=raw_template_restore(&lease,&lease.scope);
        }
        writer.tearing_down=0;
        if(rc){address=(uintptr_t)&writer.shadow[2];memcpy(object,&address,sizeof address);}
        else{
            address=read64((void *)(writer.original_vptr+slot*sizeof(uintptr_t)));
            memcpy(&destroy,&address,sizeof destroy);
            writer.completed=writer.prepared;
            writer.raw=NULL;writer.armed=0;atomic_store(&hooked_base,0);
        }
    }
    if(rc)writer.failed=rc;
    pthread_mutex_unlock(&lock);
    /* Failed restore must retain the object, never free a static template pointer. */
    if(rc){functional_capture_raw_writer_fault(rc);return;}
    destroy(object);
}
static void raw_destroy_complete(void *object){raw_destroy(object,0);}
static void raw_destroy_delete(void *object){raw_destroy(object,1);}
static int install_shadow(void *object){
    writer.original_vptr=read64(object);
    memcpy(writer.shadow,(void *)(writer.original_vptr-2*sizeof(uintptr_t)),sizeof writer.shadow);
    writer.shadow[2]=(uintptr_t)raw_destroy_complete;
    writer.shadow[3]=(uintptr_t)raw_destroy_delete;
    uintptr_t address=(uintptr_t)&writer.shadow[2];
    lease.raw_vtable=address;
    memcpy(object,&address,sizeof address);
    return read64(object)==address?0:-EIO;
}
void *raw_factory(int type){
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    if(resolve())return NULL;
    void *object=real_factory(type);
    uintptr_t base=atomic_load(&hooked_base);
    if(type!=2 || !base || caller!=base+0xe8aec)return object;
    pthread_mutex_lock(&lock);int rc=current();
    if(!rc && (writer.raw || !object || !writable(object,0x14d8) ||
       read64(object)!=base+0x2fb6e0 || malloc_usable_size(object)<0x14d8))rc=-ELIBBAD;
    if(!rc){writer.raw=object;rc=install_shadow(object);}
    if(rc)writer.failed=rc;
    pthread_mutex_unlock(&lock);
    if(rc)functional_capture_raw_writer_fault(rc);
    return object;
}
void *memset(void *destination,int value,size_t bytes){
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    /* Loader-time dlsym recursion still has the exact libc return/value ABI. */
    void *result=destination;
    if(real_set)result=real_set(destination,value,bytes);
    else{volatile unsigned char *p=destination;for(size_t i=0;i<bytes;++i)p[i]=(unsigned char)value;}
    uintptr_t base=atomic_load(&hooked_base);
    if(!base || caller!=base+0x277c68)return result;
    int saved=errno;pthread_mutex_lock(&lock);
    struct raw_template_scope scope={.libmpr_base=base,.job=writer.job,.raw_object=writer.raw,
        .pid=writer.pid,.owns=owns,.context=&writer};
    int rc=raw_template_after_memset(&lease,&scope,destination,value,bytes,caller);
    if(rc)writer.failed=rc;else writer.prepared=1;
    pthread_mutex_unlock(&lock);
    if(rc)functional_capture_raw_writer_fault(rc);
    errno=saved;return result;
}
