/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-capture.h"
#include "functional-camera-bridge.h"
#include "functional-jpeg-codec.h"
#include "functional-mpr-memory.h"
#include "../../report/functional-capture-input/capture-input.h"
#include "../../report/functional-capture-output/capture-output-memory.h"
#include "../../report/functional-capture-output/capture-delivery.h"
#include "../../report/functional-capture-output/capture-save.h"
#include "../../report/functional-capture-output/capture-dma.h"
#include "../../report/functional-capture-queue/capture-resize-request.h"
#include <dlfcn.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/syscall.h>

enum { IDLE,ACCEPTED,FRAME,ENCODING,DELIVERING,WAIT_SAVE,FAULT };
struct terminal_lease {void *pointer;uint64_t fnv;long receiver_tid;int sent,received,freed,send_rc,free_rc;};
struct dmm_inflight {void *pointer;unsigned destination;uint64_t fnv;long receiver_tid;int received,freed,sending,queued;};
struct native_api {
    unsigned (*get_config)(void *);
    unsigned (*sync_send)(const uint8_t *,void *);
    void (*get_expected)(uint32_t *,void **);
    bool (*allocate)(int,uint32_t *,void *);
    void (*free_group)(int);
    uintptr_t base;
};
static struct native_api original;
extern bool capture_memory_allocate(int,uint32_t *,void *) __asm__("_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE");
extern void capture_memory_free(int) __asm__("_ZN3mpr10DmmMemInfo13FreeDmmMemoryEi");
static _Atomic int owner,enabled;
static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wake=PTHREAD_COND_INITIALIZER;
static pthread_t worker;
static int worker_live,stopping,queued,callback_entries,binding;
static _Thread_local int producing_config,producing_resize;
static struct functional_capture_snapshot state;
static struct {
    uint8_t request[16];
    struct fcam_native_origin origin;
    struct full_imaging_io io;
    struct native_cp_state_publication_guard guard;
    struct capture_input *input;
    struct capture_input_mapping queued_input;
    struct capture_output_memory *output;
    struct capture_delivery *delivery,*published_delivery;
    struct capture_save *save;
    struct functional_mpr_memory_lease open;
    struct terminal_lease completion[3],requests[2];
    void *retained_request,*retained_dmm,*retained_dmm_reply;
    uint64_t memory_generation;
    struct dmm_inflight inflight[16];
    int dmm_sending;long dmm_sender;
    uint64_t export_token;
    unsigned opened,closed;
    _Alignas(16) uint8_t table[FUNCTIONAL_MPR_MEMORY_TABLE_BYTES];
} job;
static uint16_t u16(const uint8_t *p){return (uint16_t)(p[0]|(uint16_t)p[1]<<8);}
static uint32_t u32(const uint8_t *p){return u16(p)|(uint32_t)u16(p+2)<<16;}
static uint64_t u64(const uint8_t *p){return u32(p)|(uint64_t)u32(p+4)<<32;}
static void p16(uint8_t *p,uint32_t v){p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);}
static void p32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(v>>(8*i));}
static void p64(uint8_t *p,uint64_t v){for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(v>>(8*i));}
static uint64_t fnv(const void *data,size_t bytes){const uint8_t *p=data;uint64_t h=UINT64_C(14695981039346656037);for(size_t i=0;i<bytes;++i)h=(h^p[i])*UINT64_C(1099511628211);return h;}
static int process(void){return atomic_load(&owner)!=getpid()?-ECHILD:0;}
static void note(const char *operation,int rc){
    struct functional_capture_snapshot s;pthread_mutex_lock(&mutex);s=state;pthread_mutex_unlock(&mutex);
    if(job.io.record){char text[960];snprintf(text,sizeof text,
        "operation=%s rc=%d pid=%d job=%llu phase=%d request_fnv=%016llx cookie=%u frame_token=%#llx model_instance=%#llx request_freed=%u encoded=%u frame_released=%u notification_consumed=%u write_verified=%u resources_released=%u write_token=%u write_bytes=%llu write_fnv=%016llx policy=%s original_AP_saved=0 capture_verified=0 physical_ASIC_verified=0",
        operation,rc,getpid(),(unsigned long long)s.job,s.phase,(unsigned long long)s.request_fnv,s.request_cookie,
        (unsigned long long)s.frame_token,(unsigned long long)s.model_instance,s.request_freed,s.encoded,s.frame_released,s.notification_consumed,s.write_readback_verified,s.resources_released,
        s.write_token,(unsigned long long)s.write_bytes,(unsigned long long)s.write_fnv,FUNCTIONAL_CAPTURE_POLICY);
        job.io.record("FUNCTIONAL_CAMERA_CAPTURE ",text);}
}
static void fault(int rc){pthread_mutex_lock(&mutex);if(!state.error)state.error=rc?rc:-EIO;state.phase=FAULT;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);note("fault-retained",rc);}
static struct timespec deadline(unsigned milliseconds){struct timespec t;clock_gettime(CLOCK_REALTIME,&t);t.tv_sec+=milliseconds/1000;t.tv_nsec+=(long)(milliseconds%1000)*1000000L;if(t.tv_nsec>=1000000000L){++t.tv_sec;t.tv_nsec-=1000000000L;}return t;}
static int wait_terminal(unsigned index){
    struct timespec until=deadline(60000);pthread_mutex_lock(&mutex);int rc=0;
    while(!state.error && !(job.completion[index].sent && job.completion[index].freed &&
          (index==2 || (job.requests[index].sent && job.requests[index].freed)))){
        int e=pthread_cond_timedwait(&wake,&mutex,&until);if(e){rc=-e;break;}
    }
    if(!rc)rc=state.error?state.error:job.completion[index].send_rc?job.completion[index].send_rc:job.completion[index].free_rc;
    if(!rc){job.completion[index].pointer=NULL;if(index<2)job.requests[index].pointer=NULL;}
    pthread_mutex_unlock(&mutex);return rc;
}
#define LOAD(field,name) do {void *symbol=dlsym(RTLD_NEXT,name);if(!symbol)return -ENOSYS;memcpy(&api.field,&symbol,sizeof symbol);} while(0)
static int bind_native(void){
    struct native_api api={0};
    LOAD(sync_send,"_ZN3mpr5Codec14SendMsgToAvbbcEP10PayloadMprP12PayloadCodec");
    LOAD(get_expected,"_ZN3mpr5Codec21GetExpectedCodecEventERNS0_9IntFactorEPP12PayloadCodec");
    api.allocate=capture_memory_allocate;api.free_group=capture_memory_free;
    void *writer=dlsym(RTLD_NEXT,"_ZN3mpr10DmmMemInfo9SetMemTblEjiPNS0_11BufferTableE");Dl_info info;
    if(!writer || !dladdr(writer,&info) || !info.dli_fbase)return -ELIBBAD;
    api.base=(uintptr_t)info.dli_fbase;
    if((uintptr_t)writer-api.base!=0x2b2be0 || api.base>UINTPTR_MAX-0x3d8300)return -ELIBBAD;
    void *callback=dlsym(RTLD_NEXT,"_ZN3mpr5Codec17CallbackFromAvbbcEPvS1_");
    static const uint8_t callback_pin[16]={0xfd,0x7b,0xb8,0xa9,0xfd,0x03,0x00,0x91,0xf3,0x53,0x01,0xa9,0xf4,0x03,0x00,0xaa};
    if((uintptr_t)callback!=api.base+0x283e74 || memcmp(callback,callback_pin,sizeof callback_pin))return -ELIBBAD;
    void *entry=(void *)(api.base+0xcee2c);memcpy(&api.get_config,&entry,sizeof entry);
    if(fnv(entry,0x184)!=UINT64_C(0xca74699d6f05d6e9))return -ELIBBAD;
    original=api;return 0;
}
#undef LOAD
static int current_waiter_idle(void){uint32_t factor=0;void *p=(void *)1;original.get_expected(&factor,&p);return factor==2 && !p?0:-EBUSY;}
static int finish_encoding(void){
    int rc=0;struct timespec until=deadline(60000);struct capture_output_memory *output=NULL;
    for(;;){
        uint64_t mapbase;memcpy(&mapbase,(void *)(original.base+0x3d82a0),8);
        rc=functional_jpeg_codec_capture_output(mapbase,&output);
        if(!rc)break;
        if(rc!=-ENODATA && rc!=-EBUSY)return rc;
        pthread_mutex_lock(&mutex);if(state.error){rc=state.error;pthread_mutex_unlock(&mutex);return rc;}
        struct timespec now;clock_gettime(CLOCK_REALTIME,&now);
        if(now.tv_sec>until.tv_sec || (now.tv_sec==until.tv_sec && now.tv_nsec>=until.tv_nsec)){pthread_mutex_unlock(&mutex);return -ETIMEDOUT;}
        struct timespec tick=deadline(10);(void)pthread_cond_timedwait(&wake,&mutex,&tick);pthread_mutex_unlock(&mutex);
    }
    pthread_mutex_lock(&mutex);job.output=output;rc=capture_output_memory_hold(output,&job.export_token);pthread_mutex_unlock(&mutex);if(rc)return rc;
    rc=wait_terminal(2);if(rc)return rc;
    pthread_mutex_lock(&mutex);int closed=job.opened==2 && job.closed==2 && !job.open.token && !job.dmm_sending;
    for(unsigned i=0;i<16;++i)closed=closed && !job.inflight[i].pointer;
    pthread_mutex_unlock(&mutex);
    if(!closed)return -EBUSY;
    rc=functional_jpeg_codec_attach_capture(NULL);if(rc)return rc;
    pthread_mutex_lock(&mutex);state.input_attached=0;state.encoded=1;pthread_mutex_unlock(&mutex);
    rc=capture_input_drop(job.input,&job.queued_input);if(rc)return rc;memset(&job.queued_input,0,sizeof job.queued_input);
    uint8_t release[16];p64(release,state.frame_token);p32(release+8,3);p32(release+12,0);struct fcam_bridge_result result;
    rc=fcam_bridge_call(&job.origin,FCAM_OP_FRAME_RELEASE,release,16,NULL,0,&result);if(rc)return rc;
    pthread_mutex_lock(&mutex);state.frame_released=1;pthread_mutex_unlock(&mutex);
    struct functional_mpr_memory_snapshot memory;rc=functional_mpr_memory_snapshot(&memory);if(rc)return rc;
    if(memory.leases)return -EBUSY;
    original.free_group(0x10);rc=functional_mpr_memory_snapshot(&memory);if(rc)return rc;
    return memory.active_mask?-EBUSY:0;
}
static int notification_send(unsigned destination,void *packet){
    pthread_mutex_lock(&mutex);job.published_delivery=job.delivery;pthread_mutex_unlock(&mutex);
    return job.io.send(destination,packet);
}
static int retire_notifications(void){
    struct timespec until=deadline(60000);
    for(;;){
        pthread_mutex_lock(&mutex);
        struct capture_delivery_info info;int rc=capture_delivery_info(job.delivery,&info);
        if(rc || info.first_error || state.error){if(!rc)rc=state.error?state.error:info.first_error;pthread_mutex_unlock(&mutex);return rc;}
        state.notification_consumed=info.wire_consumed;
        if(info.wire_consumed==3 && !callback_entries){job.published_delivery=NULL;pthread_mutex_unlock(&mutex);break;}
        int e=pthread_cond_timedwait(&wake,&mutex,&until);pthread_mutex_unlock(&mutex);if(e)return -e;
    }
    pthread_mutex_lock(&mutex);int rc=capture_delivery_close(job.delivery);if(!rc)job.delivery=NULL;pthread_mutex_unlock(&mutex);
    return rc;
}
void functional_capture_fsys_begin(unsigned token,const struct fsys_write_layout *layout,const uint64_t hashes[FSYS_WRITE_AREAS],const unsigned readable[FSYS_WRITE_AREAS]){
    int saved=errno;if(!atomic_load(&enabled) || process()){errno=saved;return;}
    pthread_mutex_lock(&mutex);int rc=job.save?capture_save_match(job.save,token,layout,hashes,readable):0;
    if(rc<0 && !state.error)state.error=rc;
    if(rc>0)state.write_token=token;
    if(rc)++callback_entries;
    pthread_mutex_unlock(&mutex);
    if(rc)note(rc<0?"write-source-refused":"write-source-matched",rc<0?rc:0);
    pthread_mutex_lock(&mutex);if(rc)--callback_entries;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);
    errno=saved;
}
void functional_capture_fsys_event(unsigned token,enum capture_save_event event,int actual_rc,unsigned complete,uint64_t bytes,uint64_t hash){
    int saved=errno;if(!atomic_load(&enabled) || process()){errno=saved;return;}
    pthread_mutex_lock(&mutex);int rc=job.save?capture_save_observe(job.save,token,event,actual_rc,complete,bytes,hash):0;
    if(rc<0 && !state.error)state.error=rc;
    if(rc>0){struct capture_save_info info;if(!capture_save_info(job.save,&info)){
        state.write_readback_verified=info.write_readback_verified;state.write_bytes=info.bytes;state.write_fnv=info.file_fnv;
    }}
    if(rc)++callback_entries;
    pthread_mutex_unlock(&mutex);
    if(rc)note(rc<0?"write-lifecycle-failed":"write-lifecycle",rc<0?rc:0);
    pthread_mutex_lock(&mutex);if(rc)--callback_entries;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);
    errno=saved;
}
static int retire_saved_output(void){
    pthread_mutex_lock(&mutex);
    for(;;){
        if(state.error){int rc=state.error;pthread_mutex_unlock(&mutex);return rc;}
        struct capture_save_info info;int rc=capture_save_info(job.save,&info);
        if(rc || info.first_error){pthread_mutex_unlock(&mutex);return rc?rc:info.first_error;}
        int ready=info.write_readback_verified && !job.dmm_sending && !callback_entries;
        for(unsigned i=0;i<16;++i)ready=ready && !job.inflight[i].pointer;
        struct capture_output_info output;
        if(ready){rc=capture_output_memory_info(job.output,&output);if(rc){pthread_mutex_unlock(&mutex);return rc;}ready=!output.native_references;}
        if(ready)break;
        pthread_cond_wait(&wake,&mutex);
    }
    int rc=capture_save_close(job.save);if(!rc)job.save=NULL;
    if(!rc)rc=capture_output_memory_drop(job.output,job.export_token);
    if(!rc)job.export_token=0;
    if(!rc)rc=capture_output_memory_destroy(job.output);
    if(!rc)job.output=NULL;
    if(!rc)rc=capture_input_destroy(job.input);
    if(!rc){job.input=NULL;state.resources_released=1;}
    pthread_mutex_unlock(&mutex);
    if(!rc){full_imaging_capture_end();note("write-retired",0);pthread_mutex_lock(&mutex);state.phase=IDLE;pthread_mutex_unlock(&mutex);}return rc;
}
static int execute_job(void){
    uint8_t model[FCAM_STATE_BYTES]={0};struct fcam_bridge_result result={0};
    int rc=fcam_bridge_call(&job.origin,FCAM_OP_STATE,NULL,0,model,sizeof model,&result);if(rc)return rc;
    if(result.used!=128 || result.required!=128)return -EPROTO;
    uint32_t width=u32(model+8),height=u32(model+12);
    if(u32(model)!=1 || !(u32(model+4)&FCAM_CAP_STILL) ||
       !width || width>8192 || !height || height>8192 || !u64(model+48) ||
       result.model_instance!=u64(model+48) || u32(model+104) || u32(model+108))return -ENOTSUP;
    rc=job.guard.reserve();
    if(!rc){rc=job.guard.predecessor_ready()==1?
        full_imaging_capture_begin_functional(model,sizeof model,result.model_instance,u64(model+56)):-ENODATA;
        job.guard.release();}
    if(rc)return rc;
    if(job.io.record){
        char raw[257],text[640];for(unsigned i=0;i<128;++i)snprintf(raw+2*i,3,"%02x",model[i]);
        snprintf(text,sizeof text,"pid=%d job=%llu request_fnv=%016llx model_instance=%#llx generation=%llu state_fnv=%016llx state128=%s policy=%s original_CP_D012_verified=0 capture_verified=0",
            getpid(),(unsigned long long)state.job,(unsigned long long)state.request_fnv,(unsigned long long)result.model_instance,
            (unsigned long long)u64(model+56),(unsigned long long)fnv(model,128),raw,FULL_IMAGING_FUNCTIONAL_POLICY);
        job.io.record("FUNCTIONAL_CAMERA_MODEL_ADMISSION ",text);
    }
    size_t capacity=96u+(size_t)width*height*3u;if(capacity>64u*1024u*1024u)return -E2BIG;
    uint8_t *frame=malloc(capacity);if(!frame)return -ENOMEM;
    rc=fcam_bridge_call(&job.origin,FCAM_OP_FRAME_CAPTURE,job.request,16,frame,capacity,&result);
    if(rc){free(frame);return rc;}
    pthread_mutex_lock(&mutex);state.frame_acquired=1;state.frame_token=u64(frame+8);state.model_instance=u64(frame+16);state.phase=FRAME;pthread_mutex_unlock(&mutex);
    if(result.used!=capacity || result.required!=capacity || u64(frame+16)!=u64(model+48) || u64(frame+32)!=u64(model+56)){free(frame);return -ESTALE;}
    uint8_t parameters[128]={0};parameters[0x63]=8;parameters[0x70]=2;p16(parameters+0x68,width);p16(parameters+0x6a,height);
    /* This P128 is the declared software single-JPEG policy. It does not
     * represent Sony CP settings or infer unknown ASIC packing. */
    rc=capture_input_create(frame,capacity,job.request,parameters,&job.input);free(frame);if(rc)return rc;
    rc=functional_jpeg_codec_attach_capture(job.input);if(rc)return rc;
    pthread_mutex_lock(&mutex);state.input_attached=1;state.phase=ENCODING;pthread_mutex_unlock(&mutex);
    rc=current_waiter_idle();if(rc)return rc;
    uint32_t group=0;if(!original.allocate(0x10,&group,job.table) || !group)return -EBUSY;
    struct functional_mpr_memory_snapshot memory;rc=functional_mpr_memory_snapshot(&memory);if(rc)return rc;
    pthread_mutex_lock(&mutex);state.group=group;job.memory_generation=memory.active_generation;pthread_mutex_unlock(&mutex);
    if(memory.active_group!=group || !memory.active_generation)return -ESTALE;
    producing_config=1;unsigned configured=original.get_config(job.table);producing_config=0;
    if(configured)return -EPROTO;
    rc=wait_terminal(0);if(rc)return rc;
    uint8_t q[48];rc=capture_resize_request_build(job.input,job.request,q,&job.queued_input);if(rc)return rc;
    rc=current_waiter_idle();if(rc)return rc;
    producing_resize=1;unsigned sent=original.sync_send(q,NULL);producing_resize=0;
    if(sent!=1)return -EIO;
    rc=wait_terminal(1);if(rc)return rc;
    rc=finish_encoding();if(rc)return rc;
    time_t seconds=time(NULL);struct tm t;if(seconds<0 || !gmtime_r(&seconds,&t) || t.tm_year<70 || t.tm_year>8099)return -ERANGE;
    uint8_t local[12]={0};p16(local+2,(unsigned)t.tm_year+1900);local[4]=(uint8_t)(t.tm_mon+1);local[5]=(uint8_t)t.tm_mday;
    local[6]=(uint8_t)t.tm_hour;local[7]=(uint8_t)t.tm_min;local[8]=(uint8_t)t.tm_sec;
    void *callback=dlsym(RTLD_DEFAULT,MPR_FSYS_CALLBACK_SYMBOL);if(!callback)return -ENOSYS;
    pthread_mutex_lock(&mutex);rc=capture_save_prepare(job.output,(uintptr_t)callback,&job.save);if(!rc)state.phase=DELIVERING;pthread_mutex_unlock(&mutex);if(rc)return rc;
    struct full_imaging_io delivery_io=job.io;delivery_io.send=notification_send;
    rc=capture_delivery_begin(job.output,job.request,local,&delivery_io,&job.guard,&job.delivery);
    if(rc)return rc;
    pthread_mutex_lock(&mutex);state.notification_queued=1;state.phase=WAIT_SAVE;pthread_mutex_unlock(&mutex);
    /* Keep root/export/input until actual AP/MPR/Fsys completion is proven.
     * Queue/free of the three notifications is never a saved-media signal. */
    note("notifications-queued-unsaved",0);rc=retire_notifications();if(rc)return rc;
    note("notifications-consumed-unsaved",0);return retire_saved_output();
}
static void *run(void *unused){(void)unused;
    for(;;){pthread_mutex_lock(&mutex);while(!queued && !stopping)pthread_cond_wait(&wake,&mutex);
        if(stopping){pthread_mutex_unlock(&mutex);return NULL;}queued=0;pthread_mutex_unlock(&mutex);
        int rc=execute_job();if(rc)fault(rc);
    }
}
int functional_capture_enable(void (*record)(const char *,const char *)){
    int expected=0;atomic_compare_exchange_strong(&owner,&expected,getpid());int rc=process();if(rc)return rc;
    pthread_mutex_lock(&mutex);
    if(worker_live || stopping || binding){rc=stopping?-ESHUTDOWN:binding?-EBUSY:-EALREADY;pthread_mutex_unlock(&mutex);return rc;}
    binding=1;pthread_mutex_unlock(&mutex);
    rc=bind_native();
    pthread_mutex_lock(&mutex);
    if(!rc){job.io.record=record;state.owner_pid=getpid();int e=pthread_create(&worker,NULL,run,NULL);
        if(e)rc=-e;else{worker_live=1;state.enabled=1;atomic_store(&enabled,1);}}
    binding=0;pthread_mutex_unlock(&mutex);return rc;
}
int functional_capture_dispatch(unsigned destination,void *message,const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard,int *result){
    if(!atomic_load(&enabled) || destination!=0x90040193 || !message || !io || !io->size || io->size(message)<4)return 0;
    const uint8_t *p=message;if(u16(p)!=5 || u16(p+2)!=0x4038)return 0;
    int rc=process();if(rc){if(result)*result=rc;return 1;}
    if(!result)return 0;
    if(!io->release || !io->source || !io->allocate || !io->send || !io->set_source || !guard || !guard->reserve || !guard->release || !guard->predecessor_ready){*result=-EINVAL;return 1;}
    if(io->size(message)!=16 || io->source(message)!=0x80020002 || !fcam_capture_input_valid(p,16)){*result=-ENOTSUP;return 1;}
    pthread_mutex_lock(&mutex);if(state.phase!=IDLE || stopping){pthread_mutex_unlock(&mutex);*result=-EBUSY;return 1;}
    if(state.resources_released){uint64_t serial=state.job;memset(&job,0,sizeof job);state=(struct functional_capture_snapshot){.owner_pid=getpid(),.enabled=1,.job=serial};}
    state.phase=ACCEPTED;pthread_mutex_unlock(&mutex);
    rc=guard->reserve();if(!rc){if(guard->predecessor_ready()!=1)rc=-ENODATA;guard->release();}
    if(rc){pthread_mutex_lock(&mutex);state.phase=IDLE;pthread_mutex_unlock(&mutex);*result=rc;return 1;}
    pthread_mutex_lock(&mutex);memcpy(job.request,p,16);job.io=*io;job.guard=*guard;
    state.job++;state.request_fnv=fnv(p,16);state.request_cookie=u32(p+4);
    job.origin=(struct fcam_native_origin){0x80020002,0x90040193,0x4038,16,state.request_fnv};job.retained_request=message;
    pthread_mutex_unlock(&mutex);
    rc=io->release(destination,message);
    pthread_mutex_lock(&mutex);if(!rc){job.retained_request=NULL;state.request_freed=1;}pthread_mutex_unlock(&mutex);
    if(rc)fault(rc);else{note("natural-request-owned",0);pthread_mutex_lock(&mutex);queued=1;pthread_cond_signal(&wake);pthread_mutex_unlock(&mutex);}
    *result=0;return 1;
}
int functional_capture_terminal_send(unsigned destination,void *message,const struct full_imaging_io *io,int *result){
    if(!atomic_load(&enabled) || !message || !io || !io->size || !io->source || !io->send || !result)return 0;
    int rc=process();if(rc){*result=rc;return 1;}
    if(destination==0x8055001f && (producing_config || producing_resize)){
        const uint8_t *q=message;unsigned command=producing_config?1u:2u;
        if(io->size(message)!=48 || io->source(message)!=0x80c70047 || u16(q+2)!=command ||
           u32(q+0x24)!=0x1500 || u32(q+0x10)!=(command==1?56u:128u)){*result=-EBADMSG;return 1;}
        if(command==1){
            const uint8_t *body=(const void *)(uintptr_t)u64(q+0x28);
            if(!body || u64(body)!=u64(job.table+0x2a0) || u32(body+8)!=120){*result=-EBADMSG;return 1;}
        }else{
            struct capture_input_info input;rc=capture_input_info(job.input,&input);
            if(rc || !job.queued_input.token || u64(q+0x28)!=input.parameter_cpu){*result=rc?rc:-ESTALE;return 1;}
        }
        unsigned index=command-1;pthread_mutex_lock(&mutex);
        if(job.requests[index].pointer){pthread_mutex_unlock(&mutex);*result=-EALREADY;return 1;}
        job.requests[index]=(struct terminal_lease){.pointer=message,.fnv=fnv(message,48)};pthread_mutex_unlock(&mutex);
        rc=io->send(destination,message);
        pthread_mutex_lock(&mutex);job.requests[index].send_rc=rc;job.requests[index].sent=!rc;
        if(rc && !state.error)state.error=rc;
        pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    if(destination!=0x80c70047 || io->size(message)!=44 || io->source(message)!=0x80550123)return 0;
    const uint8_t *p=message;unsigned cmd=u16(p+2),index=cmd==0x42?0:cmd==0x1002?1:cmd==0x2002?2:3;
    if(index==3 || u32(p+0x24)!=0x4e0)return 0;
    pthread_mutex_lock(&mutex);if(state.phase!=ENCODING){pthread_mutex_unlock(&mutex);return 0;}
    if(job.completion[index].pointer){pthread_mutex_unlock(&mutex);*result=-EALREADY;return 1;}
    job.completion[index]=(struct terminal_lease){.pointer=message,.fnv=fnv(message,44)};
    if(u32(p+0x14) && !state.error)state.error=-EIO;
    pthread_mutex_unlock(&mutex);
    rc=io->send(destination,message);
    pthread_mutex_lock(&mutex);job.completion[index].send_rc=rc;job.completion[index].sent=!rc;
    if(rc && !state.error)state.error=rc;
    pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
void functional_capture_observe_freed(unsigned destination,void *message,int result,uintptr_t caller){
    if(!atomic_load(&enabled) || process() || !message)return;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<16;++i){struct dmm_inflight *d=&job.inflight[i];if(d->pointer!=message || d->destination!=destination)continue;
        int checked=result?result:d->received && d->receiver_tid==syscall(SYS_gettid)?0:-EPERM;
        d->freed=!checked;if(checked && !state.error)state.error=checked;
        if(d->freed && d->queued && !d->sending)memset(d,0,sizeof *d);
        break;
    }
    if(destination!=0x80c70047 && destination!=0x8055001f){pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);return;}
    unsigned count=destination==0x80c70047?3u:2u;
    struct terminal_lease *leases=destination==0x80c70047?job.completion:job.requests;
    for(unsigned i=0;i<count;++i)if(leases[i].pointer==message){
        int origin=destination==0x80c70047?
            caller>=original.base+0x283e74 && caller<original.base+0x284058:
            leases[i].received && leases[i].receiver_tid==syscall(SYS_gettid);
        int checked=result?result:origin?0:-EPERM;
        leases[i].free_rc=checked;leases[i].freed=!checked;
        if(checked && !state.error)state.error=checked;
        pthread_cond_broadcast(&wake);break;
    }
    pthread_mutex_unlock(&mutex);
}
void functional_capture_observe_received(unsigned destination,void *message){
    if(!atomic_load(&enabled) || process())return;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<16;++i){struct dmm_inflight *d=&job.inflight[i];if(d->pointer!=message || d->destination!=destination)continue;
        if(job.io.size(message)==40 && job.io.source(message)==0x61003c && fnv(message,40)==d->fnv && !d->received){
            d->received=1;d->receiver_tid=syscall(SYS_gettid);
        }else if(!state.error)state.error=-EBADMSG;
        break;
    }
    if(destination==0x8055001f){
        for(unsigned i=0;i<2;++i)if(job.requests[i].pointer==message){
            if(job.io.size(message)==48 && job.io.source(message)==0x80c70047 && fnv(message,48)==job.requests[i].fnv && !job.requests[i].received){
                job.requests[i].received=1;job.requests[i].receiver_tid=syscall(SYS_gettid);
            }else if(!state.error)state.error=-EBADMSG;
        }
    }
    struct capture_delivery *d=job.published_delivery;if(d)++callback_entries;pthread_mutex_unlock(&mutex);
    if(d){int rc=capture_delivery_observe(d,destination,message);pthread_mutex_lock(&mutex);--callback_entries;if(rc<0 && !state.error)state.error=rc;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);}
}
int functional_capture_release_notification(unsigned destination,void *message,int *result){
    if(!atomic_load(&enabled) || process())return 0;
    pthread_mutex_lock(&mutex);struct capture_delivery *d=job.published_delivery;if(d)++callback_entries;pthread_mutex_unlock(&mutex);
    if(!d)return 0;
    int handled=capture_delivery_free(d,destination,message,result);
    struct capture_delivery_info info;int rc=capture_delivery_info(d,&info);
    pthread_mutex_lock(&mutex);--callback_entries;if(!rc)state.notification_consumed=info.wire_consumed;if(handled && *result && !state.error)state.error=*result;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);return handled;
}
int functional_capture_dmm(unsigned destination,void *message,const struct full_imaging_io *io,uintptr_t caller,int *result){
    if(!atomic_load(&enabled) || !message || !io || !io->size || !io->source || !result ||
       (destination!=0x0061003c && destination!=0x8061003c && destination!=0x9061003c) || io->size(message)!=40)return 0;
    int rc=process();if(rc){*result=rc;return 1;}
    uint8_t q[40],reply[40]={0};memcpy(q,message,40);unsigned source=io->source(message),op=u16(q),handle=u32(q+8);
    if(!io->allocate || !io->release || !io->set_source || !io->send){*result=-EINVAL;return 1;}
    pthread_mutex_lock(&mutex);
    while(job.dmm_sending){
        if(job.dmm_sender==syscall(SYS_gettid)){pthread_mutex_unlock(&mutex);*result=-EDEADLK;return 1;}
        pthread_cond_wait(&wake,&mutex);
    }
    if(state.phase==IDLE || state.phase==ACCEPTED){pthread_mutex_unlock(&mutex);return 0;}
    unsigned slot=0;while(slot<16 && job.inflight[slot].pointer)++slot;
    if(slot==16){pthread_mutex_unlock(&mutex);*result=-ENOSPC;return 1;}
    int senc=source==0x80550123 && (op==0x24 || op==0x25),owned=0;
    int output_request=job.output && ((handle&UINT32_C(0xff000000))==UINT32_C(0x68000000) ||
        (op==0x28 && (handle==0x80d61 || handle==0x27f) && job.save &&
         (state.phase==DELIVERING || state.phase==WAIT_SAVE)));
    if((job.retained_dmm || job.retained_dmm_reply) && (senc || output_request)){
        pthread_mutex_unlock(&mutex);*result=-EBUSY;return 1;
    }
    struct functional_mpr_memory_lease opened={0},closed={0};
    uint64_t mapbase=0;
    if(senc && (state.phase==ENCODING || state.phase==FAULT)){
        if(op==0x24){
            if(u32(q+12)!=UINT32_MAX){pthread_mutex_unlock(&mutex);*result=-ENOTSUP;return 1;}
            if(state.phase==FAULT){pthread_mutex_unlock(&mutex);*result=-ECANCELED;return 1;}
            if(job.open.token || job.opened>=2)rc=-EBUSY;
            else{
                struct functional_mpr_memory_lease probe={0};
                rc=functional_mpr_memory_acquire_sds(0,handle,0,1,&probe);
                if(rc==-ENODATA || rc==-ESTALE){pthread_mutex_unlock(&mutex);return 0;}
                if(!rc && (probe.span.group!=state.group || probe.span.generation!=job.memory_generation ||
                           !probe.span.capacity || probe.span.capacity>UINT32_MAX))rc=-ESTALE;
                if(!rc)rc=functional_mpr_memory_acquire_sds(0,handle,0,probe.span.capacity,&opened);
                if(probe.token){int released=functional_mpr_memory_release(probe.token);if(released && !rc)rc=released;}
                if(!rc)rc=functional_mpr_memory_validate(&opened);
            }
            owned=1;
            if(!rc){p64(reply+24,opened.address);p32(reply+32,(uint32_t)opened.bytes);}
        }else{
            if(!job.open.token || job.open.span.unit!=handle){pthread_mutex_unlock(&mutex);return 0;}
            owned=1;rc=functional_mpr_memory_validate(&job.open);
            if(!rc)rc=functional_mpr_memory_release(job.open.token);
            if(!rc){closed=job.open;memset(&job.open,0,sizeof job.open);++job.closed;}
        }
        p16(reply,op|0x8000);p32(reply+8,handle);p32(reply+12,handle);
    }else if(output_request){
        if(caller!=original.base+0x2b1f08 && caller!=original.base+0x2b2388){pthread_mutex_unlock(&mutex);*result=-EPERM;return 1;}
        if(state.phase==FAULT && op==0x21){pthread_mutex_unlock(&mutex);*result=-ECANCELED;return 1;}
        memcpy(&mapbase,(void *)(original.base+0x3d82a0),8);
        rc=capture_output_memory_reply(job.output,q,mapbase,reply);owned=1;
    }
    if(!owned){pthread_mutex_unlock(&mutex);return 0;}
    if(rc){
        if(opened.token){int released=functional_mpr_memory_release(opened.token);if(released){job.open=opened;if(!state.error)state.error=released;}}
        pthread_mutex_unlock(&mutex);*result=rc;return 1;
    }
    void *packet=NULL;int accepted=0;rc=io->allocate(source,&packet,40,1);
    if(!rc && !packet)rc=-ENOMEM;
    if(!rc){
        memcpy(packet,reply,40);io->set_source(packet,0x61003c);
        job.inflight[slot]=(struct dmm_inflight){.pointer=packet,.destination=source,.fnv=fnv(packet,40),.sending=1};
        if(opened.token){job.open=opened;++job.opened;}
        job.dmm_sending=1;job.dmm_sender=syscall(SYS_gettid);pthread_mutex_unlock(&mutex);
        rc=io->send(source,packet);accepted=!rc;
        pthread_mutex_lock(&mutex);job.inflight[slot].sending=0;job.inflight[slot].queued=accepted;
        if(accepted && job.inflight[slot].freed)memset(&job.inflight[slot],0,sizeof job.inflight[slot]);
    }
    if(!accepted){
        if(packet && (job.inflight[slot].received || job.inflight[slot].freed)){
            if(!state.error)state.error=-EPROTO;
            job.dmm_sending=0;job.dmm_sender=0;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);*result=rc;return 1;
        }
        if(packet){int released=io->release(source,packet);if(released){job.retained_dmm_reply=packet;if(!state.error)state.error=released;}else memset(&job.inflight[slot],0,sizeof job.inflight[slot]);}
        if(opened.token && job.open.token==opened.token){memset(&job.open,0,sizeof job.open);--job.opened;}
        if(opened.token){int released=functional_mpr_memory_release(opened.token);if(released){job.open=opened;if(!state.error)state.error=released;}}
        if(closed.token){struct functional_mpr_memory_lease restored={0};int undo=functional_mpr_memory_acquire_sds(0,handle,0,closed.bytes,&restored);
            if(!undo){job.open=restored;--job.closed;}else if(!state.error)state.error=undo;}
        if(!senc && (op==0x21 || op==0x23)){
            uint8_t undo[40],ignored[40];memcpy(undo,q,40);p16(undo,op==0x21?0x23:0x21);p16(undo+22,op==0x21?2:1);
            if(op==0x23)p32(undo+4,1);
            int undone=capture_output_memory_reply(job.output,undo,mapbase,ignored);if(undone && !state.error)state.error=undone;
        }
    }else{
        pthread_mutex_unlock(&mutex);int released=io->release(destination,message);pthread_mutex_lock(&mutex);
        if(released){job.retained_dmm=message;if(!rc)rc=released;}
    }
    job.dmm_sending=0;job.dmm_sender=0;
    if(rc && !state.error)state.error=rc;
    pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);
    if(rc)note("DMM-error-retained",rc);
    *result=accepted?0:rc;return 1;
}
int functional_capture_native_dma(void *,void *,uint32_t) __asm__("_ZN3mpr4dmac16memcpyThreadSafeEPvS1_j");
int functional_capture_native_dma(void *destination,void *source,uint32_t bytes){
    int saved=errno,rc=0,owned=0;char text[240]={0};void (*logger)(const char *,const char *)=NULL;
    if(atomic_load(&enabled)){
        rc=process();if(rc){errno=saved;return rc;}
        pthread_mutex_lock(&mutex);
        if(job.output){
            struct capture_output_span header,thumb;
            rc=capture_output_memory_span(job.output,CAPTURE_OUT_HEADER,&header);
            if(!rc)rc=capture_output_memory_span(job.output,CAPTURE_OUT_THUMB,&thumb);
            if(!rc)owned=(uintptr_t)source==thumb.alias || ((uintptr_t)destination>=header.alias &&
                (uintptr_t)destination-header.alias<header.capacity);
            if(owned){
                if((uintptr_t)__builtin_return_address(0)!=original.base+0x275ad4 ||
                   (state.phase!=DELIVERING && state.phase!=WAIT_SAVE) || !job.save)rc=-EPERM;
                else{uint64_t readback=0;rc=capture_dma_thumbnail(job.output,(uintptr_t)destination,(uintptr_t)source,bytes,&readback);
                    if(!rc && job.io.record){logger=job.io.record;snprintf(text,sizeof text,
                        "pid=%d job=%llu frame_token=%#llx bytes=%u readback_fnv=%016llx actual_consumed=1 physical_ASIC_verified=0 capture_verified=0",
                        getpid(),(unsigned long long)state.job,(unsigned long long)state.frame_token,bytes,(unsigned long long)readback);
                        }}

                if(rc && !state.error)state.error=rc;
            }
        }
        pthread_mutex_unlock(&mutex);
    }
    if(owned){if(logger)logger("FUNCTIONAL_CAMERA_THUMB_DMA ",text);errno=saved;return rc;}
    void *symbol=dlsym(RTLD_NEXT,"_ZN3mpr4dmac16memcpyThreadSafeEPvS1_j");int (*delegate)(void *,void *,uint32_t)=NULL;
    if(symbol)memcpy(&delegate,&symbol,sizeof symbol);
    errno=saved;return delegate?delegate(destination,source,bytes):-ENOSYS;
}
int functional_capture_snapshot(struct functional_capture_snapshot *out){int rc=process();if(rc)return rc;if(!out)return -EINVAL;pthread_mutex_lock(&mutex);*out=state;pthread_mutex_unlock(&mutex);return 0;}
int functional_capture_shutdown(void){int rc=process();if(rc)return rc;pthread_mutex_lock(&mutex);
    int replies=0;for(unsigned i=0;i<16;++i)replies|=job.inflight[i].pointer!=NULL;
    if(state.phase!=IDLE || callback_entries || queued || replies || job.dmm_sending){pthread_mutex_unlock(&mutex);return -EBUSY;}
    stopping=1;pthread_cond_signal(&wake);int join=worker_live;pthread_mutex_unlock(&mutex);
    if(join){int e=pthread_join(worker,NULL);if(e)return -e;}
    pthread_mutex_lock(&mutex);worker_live=0;state.enabled=0;atomic_store(&enabled,0);pthread_mutex_unlock(&mutex);return 0;
}
