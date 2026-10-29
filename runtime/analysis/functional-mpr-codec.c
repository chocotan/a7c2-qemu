/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-mpr-codec.h"
#include "functional-mpr-memory.h"
#include "functional-camera-bridge.h"
#include "../../report/native-video-binding/native-video.h"
#include "../../report/native-video-paramsets/native-paramsets.h"
#include "../../report/native-video-length-format/native-lengths.h"
#include <errno.h>
#include <inttypes.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <time.h>
#include <sys/syscall.h>

/* The guest libc predates glibc's C23 scanf exports. */
extern int fmpr_codec_scan_maps(const char *,const char *,...) __asm__("__isoc99_sscanf");

#define RESULT_CAP (8u * 1024u * 1024u)
#define REPLIES 16u
#define INFO_BYTES 96u
#define MPR_MESSAGE 0x210u
#define EVENT_MESSAGE 0x4e0u
#define VIRTUAL_FPS 30u
#define NATIVE_HZ 90000u
#define MEMORY_LEASES 64u
enum buffer_pin { PIN_ES, PIN_SECONDARY, PIN_AUXILIARY, PIN_INFO, PIN_READ, PIN_CONTROL, PIN_COUNT };
struct lease {
    struct functional_mpr_memory_lease pins[PIN_COUNT];
    uint64_t es, correction, info, read, write, counter;
    size_t capacity, used;
    uint32_t slots, cursor, read_seen, outstanding;
    uint16_t width, height;
};
struct job {
    uint8_t wire[48], parameter[0x98];
    struct full_imaging_io io;
    struct fcam_native_origin origin;
    struct lease lease;
    unsigned command;
    uint64_t request_sequence, epoch, memory_generation, instance;
    long producer_pid, producer_tid;
};
struct reply_lease {
    void *pointer;
    uint8_t wire[48], request_wire[48];
    unsigned stage, received;
    uint64_t sequence, request_sequence, epoch, memory_generation, instance;
    uint64_t native_fnv;
    long producer_pid, producer_tid, receiver_pid, receiver_tid;
    struct full_imaging_io io;
};
struct publication {
    uint8_t info[INFO_BYTES];
    uint64_t ticket, slot_generation, cycle, frame_generation, packet_index;
    uint64_t model_token, call_native_fnv, call_request_sequence;
    uint64_t es_fnv, nal_fnv, source_fnv;
    size_t es_offset, es_bytes, source_offset, source_bytes, result_bytes;
    uint32_t nal_count, slot, read_before, read_after, write_before, write_after;
    uint32_t counter_before, counter_after, outstanding_before, outstanding_after;
    int published;
};
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wake = PTHREAD_COND_INITIALIZER;
static _Atomic pid_t owner;
static uintptr_t library;
static pthread_t worker;
static int started, stopping, joining, reserved, queued, working;
static struct job pending;
static struct reply_lease replies[REPLIES];
static struct functional_mpr_codec_snapshot stats;
/* This ledger retains failed releases even after a job/open is discarded. */
static struct functional_mpr_memory_lease held_memory[MEMORY_LEASES];
/* Only the single worker accesses the open lease and retained Start origin. */
static struct lease live;
static struct job start_job;
static uint64_t frame_generation, packet_sequence, configuration_fnv;
static size_t configuration_bytes;
static uint64_t model_instance,event_sequence,request_sequence;
static struct publication *publications;
static uint64_t publication_ticket, retired_ticket;
static int stream_live, config_published;
static uint8_t *result_bytes, *avcc;
static size_t avcc_capacity;

static uint16_t u16(const uint8_t *p) { return (uint16_t)(p[0] | (uint16_t)p[1] << 8); }
static uint32_t u32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24; }
static uint64_t u64(const uint8_t *p) { return u32(p) | (uint64_t)u32(p+4)<<32; }
static void p16(uint8_t *p,uint16_t n) { p[0]=(uint8_t)n;p[1]=(uint8_t)(n>>8); }
static void p32(uint8_t *p,uint32_t n) { for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i)); }
static void p64(uint8_t *p,uint64_t n) { p32(p,(uint32_t)n);p32(p+4,(uint32_t)(n>>32)); }
static void be32(uint8_t *p,uint32_t n) { for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(24-8*i)); }
static uint64_t fnv_more(uint64_t h,const void *v,size_t n) {
    const uint8_t *p=v;
    for(size_t i=0;i<n;i++){h^=p[i];h*=UINT64_C(1099511628211);}return h;
}
static uint64_t fnv(const void *v,size_t n) {
    return fnv_more(UINT64_C(14695981039346656037),v,n);
}
static void hex_bytes(const uint8_t *p,size_t n,char *out) {
    static const char digits[]="0123456789abcdef";
    for(size_t i=0;i<n;i++){out[2*i]=digits[p[i]>>4];out[2*i+1]=digits[p[i]&15];}
    out[2*n]=0;
}
static int guard(void) {
    pid_t pid=atomic_load_explicit(&owner,memory_order_acquire);
    return !pid?-ENODEV:pid!=getpid()?-ECHILD:0;
}
static void note(const struct full_imaging_io *io,const char *tag,const char *text) {
    if(io->record)io->record(tag,text);
}
static void failed(int rc) {
    pthread_mutex_lock(&mutex);stats.last_error=rc;stats.failures++;stats.state=FMPR_FAULT;pthread_mutex_unlock(&mutex);
}
static int span(uint64_t a,size_t n) { return a && n && a<=UINTPTR_MAX && n<=UINTPTR_MAX-(uintptr_t)a; }
#ifdef FCAM_HOST_TEST
extern int fmpr_test_memory_read(uint64_t,void *,size_t);
static int memory_read(uint64_t a,void *p,size_t n) { return span(a,n)?fmpr_test_memory_read(a,p,n):-EFAULT; }
#else
static int accessible(uint64_t a,size_t n,int write) {
    if(!span(a,n))return -EFAULT;
    FILE *f=fopen("/proc/self/maps","r");if(!f)return -errno;
    char row[512],perms[5];unsigned long lo,hi;uint64_t end=a+n,next=a;
    while(next<end && fgets(row,sizeof row,f)) {
        if(fmpr_codec_scan_maps(row,"%lx-%lx %4s",&lo,&hi,perms)!=3)continue;
        if(next<lo)break;
        if(next>=hi)continue;
        if(perms[0]!='r' || (write && perms[1]!='w'))break;
        next=hi<end?hi:end;
    }
    int rc=next==end?0:-EFAULT;
    if(fclose(f) && !rc)rc=-errno;
    return rc;
}
static int memory_read(uint64_t a,void *p,size_t n) {
    int rc=accessible(a,n,0);if(rc)return rc;
    int fd=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);if(fd<0)return -errno;
    ssize_t got;do{got=pread(fd,p,n,(off_t)a);}while(got<0 && errno==EINTR);
    rc=got==(ssize_t)n?0:got<0?-errno:-EIO;
    if(close(fd) && !rc)rc=-errno;
    return rc;
}
#endif
static int read32(uint64_t a,uint32_t *out) { uint8_t b[4];int rc=memory_read(a,b,4);if(!rc)*out=u32(b);return rc; }
static int global64(uintptr_t base,unsigned off,uint64_t *out) {
    uint8_t b[8];if(base>UINTPTR_MAX-off)return -EOVERFLOW;
    int rc=memory_read(base+off,b,8);if(!rc)*out=u64(b);return rc;
}
static int disjoint(uint64_t a,size_t an,uint64_t b,size_t bn) { return a+an<=b || b+bn<=a; }
static int acquire_memory(uint64_t address,size_t bytes,struct functional_mpr_memory_lease *out) {
    if(!span(address,bytes))return -EFAULT;
    unsigned index=MEMORY_LEASES;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<MEMORY_LEASES;i++)if(!held_memory[i].token){index=i;held_memory[i].token=UINT64_MAX;break;}
    pthread_mutex_unlock(&mutex);
    if(index==MEMORY_LEASES)return -ENOSPC;
    struct functional_mpr_memory_lease pin={0};
    int rc=functional_mpr_memory_acquire((uintptr_t)address,bytes,&pin);
    pthread_mutex_lock(&mutex);
    if(rc)memset(&held_memory[index],0,sizeof held_memory[index]);
    else {held_memory[index]=pin;stats.owned_memory_leases++;*out=pin;}
    pthread_mutex_unlock(&mutex);return rc;
}
static int release_memory(struct functional_mpr_memory_lease *pin) {
    if(!pin->token)return 0;
    int rc=functional_mpr_memory_release(pin->token);
    pthread_mutex_lock(&mutex);
    if(rc)stats.last_memory_release_error=rc;
    else for(unsigned i=0;i<MEMORY_LEASES;i++)if(held_memory[i].token==pin->token){
        memset(&held_memory[i],0,sizeof held_memory[i]);stats.owned_memory_leases--;break;
    }
    pthread_mutex_unlock(&mutex);
    if(!rc)memset(pin,0,sizeof *pin);
    return rc;
}
static int release_open(struct lease *l) {
    int error=0;
    for(unsigned i=0;i<PIN_COUNT;i++){int rc=release_memory(&l->pins[i]);if(!error)error=rc;}
    return error;
}
static int logical_pointer(const struct functional_mpr_memory_lease *pin,uint64_t logical) {
    return pin->span.offset<=UINT64_MAX-pin->span.iova_base && pin->span.iova_base+pin->span.offset==logical;
}
static int acquire_buffer(struct lease *l,enum buffer_pin kind,uint64_t address,size_t bytes,uint64_t logical,unsigned type) {
    struct functional_mpr_memory_lease *pin=&l->pins[kind];
    int rc=acquire_memory(address,bytes,pin);if(rc)return rc;
    if(!pin->span.group || !pin->span.generation || pin->span.unit_type!=type || !logical_pointer(pin,logical))return -ESTALE;
    const struct functional_mpr_memory_span *es=&l->pins[PIN_ES].span;
    return pin->span.group==es->group && pin->span.generation==es->generation?0:-ESTALE;
}
static int validate_open(const struct lease *l) {
    for(unsigned i=0;i<PIN_COUNT;i++){
        if((i==PIN_SECONDARY || i==PIN_AUXILIARY) && !l->pins[i].token)continue;
        if(!l->pins[i].token || l->pins[i].span.group!=l->pins[PIN_ES].span.group ||
           l->pins[i].span.generation!=l->pins[PIN_ES].span.generation)return -ESTALE;
        int rc=functional_mpr_memory_validate(&l->pins[i]);if(rc)return rc;
    }
    return 0;
}
static int read_parameters(const struct job *j,unsigned bytes,uint8_t *out) {
    struct functional_mpr_memory_lease pin={0};
    int rc=acquire_memory(u64(j->wire+0x28),bytes,&pin);if(rc)return rc;
    if(pin.span.unit_type!=2 || pin.span.group || !logical_pointer(&pin,u64(j->wire+8)))rc=-ESTALE;
    if(!rc)rc=functional_mpr_memory_validate(&pin);
    if(!rc)rc=memory_read(pin.address,out,bytes);
    if(!rc)rc=functional_mpr_memory_validate(&pin);
    int released=release_memory(&pin);return rc?rc:released;
}
static int snapshot_open(uintptr_t base,const uint8_t wire[48],const uint8_t *a,struct lease *out) {
    struct nvideo_encopen_parameters parsed;
    enum nvideo_status status=nvideo_parse_encopen_parameters(FUNCTIONAL_MPR_CODEC_DESTINATION,
        wire,48,u64(wire+0x28),a,0x98,&parsed,sizeof parsed);
    if(status!=NVIDEO_OK)return status==NVIDEO_UNSUPPORTED?-ENOTSUP:status==NVIDEO_RANGE?-ERANGE:-EINVAL;
    struct lease l={0};uint64_t n,cap;int rc;
    if((rc=global64(base,0x3b7d68,&l.es)) || (rc=global64(base,0x3b7d70,&cap)) ||
       (rc=global64(base,0x3b7d78,&l.correction)) || (rc=global64(base,0x3b7f70,&l.info)) ||
       (rc=global64(base,0x3b7e58,&l.read)) || (rc=global64(base,0x3b7e68,&l.write)))return rc;
    if((rc=read32(base+0x3b80b0,&l.slots)))return rc;
    l.width=u16(a+0x68);l.height=u16(a+0x6a);
    if(!l.width || !l.height || l.width>FCAM_MAX_VIDEO_WIDTH || l.height>FCAM_MAX_VIDEO_HEIGHT ||
       (l.width&1) || (l.height&1))return -ERANGE;
    /* This source audio format is admissible; Audio Recording Off is a separate UI prerequisite. */
    if(a[0x65]!=3 || parsed.selection_byte)return -ENOTSUP;
    if(cap!=parsed.main_es_capacity || cap>SIZE_MAX || !cap || l.slots!=parsed.video_info_count ||
       l.slots>65535 || l.slots<5 || l.es<l.correction || l.es-l.correction!=parsed.main_es_base)return -ESTALE;
    l.capacity=(size_t)cap;n=(uint64_t)l.slots*INFO_BYTES;
    /* Original pre-conversion triples retain independent control bases. */
    uint64_t saved,correction,read_base,write_base;
    if((rc=global64(base,0x3b80a8,&saved)) || saved!=l.info ||
       (rc=global64(base,0x3b80b8,&correction)) || saved<correction || saved-correction!=parsed.video_info_base)return rc?rc:-ESTALE;
    if((rc=global64(base,0x3b7eb0,&read_base)) || read_base!=l.read ||
       (rc=global64(base,0x3b7ec0,&correction)) || read_base<correction || read_base-correction!=parsed.read_control_base)return rc?rc:-ESTALE;
    if((rc=global64(base,0x3b8030,&write_base)) || write_base>UINT64_MAX-4 || write_base+4!=l.write ||
       (rc=global64(base,0x3b8040,&correction)) || write_base<correction || write_base-correction!=parsed.write_control_base)return rc?rc:-ESTALE;
    if((rc=global64(base,0x3b8168,&l.counter)) || l.counter!=write_base)return rc?rc:-ESTALE;
    uint64_t addresses[PIN_COUNT]={l.es,parsed.secondary_es_base,parsed.auxiliary_base,l.info,l.read,write_base};
    /* Auxiliary units are opaque; own its address without inventing a byte extent. */
    size_t sizes[PIN_COUNT]={l.capacity,parsed.secondary_es_capacity,parsed.auxiliary_base?1u:0u,
        (size_t)n,parsed.read_control_declared_bytes,parsed.write_control_declared_bytes};
    uint64_t logical[PIN_COUNT]={parsed.main_es_base,parsed.secondary_es_base,parsed.auxiliary_base,
        parsed.video_info_base,parsed.read_control_base,parsed.write_control_base};
    static const unsigned types[PIN_COUNT]={3,4,6,6,6,6};
    if((!parsed.secondary_es_base)!=(!parsed.secondary_es_capacity) ||
       (!parsed.auxiliary_base && parsed.auxiliary_capacity) || (l.read&3) || (l.write&3))return -EINVAL;
    for(unsigned i=0;i<PIN_COUNT;i++)if(sizes[i]){
        if(!span(addresses[i],sizes[i]))return -EINVAL;
        for(unsigned k=0;k<i;k++)if(sizes[k] && !disjoint(addresses[i],sizes[i],addresses[k],sizes[k]))return -EINVAL;
    }
    for(unsigned i=0;i<PIN_COUNT;i++)if(sizes[i]){
        rc=acquire_buffer(&l,(enum buffer_pin)i,addresses[i],sizes[i],logical[i],types[i]);if(rc)goto error;
    }
    uint32_t frames;
    if((rc=validate_open(&l)) || (rc=read32(l.read,&l.read_seen)) || (rc=read32(l.write,&l.cursor)) ||
       (rc=read32(l.counter,&frames)))goto error;
    if(l.read_seen || l.cursor || frames){rc=-ESTALE;goto error;}
    if((rc=validate_open(&l)))goto error;
    *out=l;return 0;
error:
    (void)release_open(&l);return rc;
}
static int same_io(const struct full_imaging_io *a,const struct full_imaging_io *b) {
    return a->allocate==b->allocate && a->release==b->release && a->set_source==b->set_source &&
        a->send==b->send && a->size==b->size && a->source==b->source && a->record==b->record;
}
static int canonical(const struct full_imaging_io *io,void *p,const uint8_t *wire,unsigned src) {
    return io->size(p)==48 && io->source(p)==src && !memcmp(p,wire,48);
}
static int valid_io(const struct full_imaging_io *io) {
    return io && io->allocate && io->release && io->set_source && io->send && io->size && io->source;
}

static void event_note(const struct reply_lease *r,const char *tag,int rc) {
    struct functional_mpr_codec_snapshot s;
    pthread_mutex_lock(&mutex);s=stats;pthread_mutex_unlock(&mutex);
    char text[1024],wire_hex[97],request_hex[97];
    hex_bytes(r->wire,48,wire_hex);hex_bytes(r->request_wire,48,request_hex);
    int n=snprintf(text,sizeof text,
        "seq=%" PRIu64 " command=%u wire_fnv=%#" PRIx64 " src=%#x dst=%#x received=%u rc=%d state=%u pending=%u owned=%u"
        " pid=%ld observer_tid=%ld receiver_pid=%ld receiver_tid=%ld producer_pid=%ld producer_tid=%ld"
        " instance=%#" PRIx64 " epoch=%" PRIu64 " memory_generation=%" PRIu64
        " request_seq=%" PRIu64 " native_fnv=%#" PRIx64 " reply_address=%#" PRIxPTR
        " operation_error=%d wire_hex=%s request_hex=%s",
        r->sequence,(unsigned)(u16(r->wire+2)-1u)/2u,fnv(r->wire,48),
        FUNCTIONAL_MPR_CODEC_DESTINATION,FUNCTIONAL_MPR_CODEC_SOURCE,r->received,rc,s.state,s.pending,s.owned_replies,
        (long)getpid(),(long)syscall(SYS_gettid),r->receiver_pid,r->receiver_tid,r->producer_pid,r->producer_tid,
        r->instance,r->epoch,r->memory_generation,r->request_sequence,r->native_fnv,(uintptr_t)r->pointer,
        (int32_t)u32(r->wire+0x14),wire_hex,request_hex);
    if(n<0 || (size_t)n>=sizeof text)note(&r->io,"FUNCTIONAL_MPR_RECEIPT_ERROR ","stage=event rc=-75");
    else note(&r->io,tag,text);
}
static void request_note(const struct job *j,int rc) {
    char text[640],wire_hex[97];hex_bytes(j->wire,48,wire_hex);
    snprintf(text,sizeof text,
        "request_seq=%" PRIu64 " command=%u rc=%d pid=%ld producer_tid=%ld src=%#x dst=%#x"
        " native_bytes=48 native_fnv=%#" PRIx64 " epoch=%" PRIu64 " memory_generation=%" PRIu64
        " instance=%#" PRIx64 " wire_hex=%s",
        j->request_sequence,j->command,rc,j->producer_pid,j->producer_tid,j->origin.source,j->origin.destination,
        j->origin.wire_fnv1a64,j->epoch,j->memory_generation,j->instance,wire_hex);
    note(&j->io,"FUNCTIONAL_MPR_REQUEST ",text);
}

/* Source CallbackFromAvbbc reads command+2, error+14, codec+18/format+1c,
 * message-id+24 and copies all 48 bytes into its waiting PayloadCodec. */
static int send_event(const struct job *j,unsigned command,int error) {
    void *p=NULL;unsigned index=REPLIES;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<REPLIES;i++){
        if(replies[i].pointer && replies[i].stage==6){pthread_mutex_unlock(&mutex);return -EOVERFLOW;}
        if(!replies[i].pointer && index==REPLIES)index=i;
    }
    pthread_mutex_unlock(&mutex);
    if(index==REPLIES)return -ENOSPC;
    int allocated=j->io.allocate(FUNCTIONAL_MPR_CODEC_SOURCE,&p,48,1);
    if(!p)return allocated?allocated:-ENOMEM;
    if(!span((uintptr_t)p,48)){
        pthread_mutex_lock(&mutex);replies[index].pointer=p;replies[index].io=j->io;replies[index].stage=6;stats.owned_replies++;pthread_mutex_unlock(&mutex);
        return -EOVERFLOW;
    }
    int alias=0;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<REPLIES;i++){
        if(replies[i].pointer && !disjoint((uintptr_t)p,48,(uintptr_t)replies[i].pointer,48))alias=1;
    }
    if(!alias){
        memset(&replies[index],0,sizeof replies[index]);
        replies[index].pointer=p;replies[index].io=j->io;replies[index].stage=4;
        replies[index].sequence=++event_sequence;replies[index].request_sequence=j->request_sequence;
        replies[index].epoch=j->epoch;replies[index].memory_generation=j->memory_generation;
        replies[index].instance=model_instance;replies[index].native_fnv=j->origin.wire_fnv1a64;
        replies[index].producer_pid=j->producer_pid;replies[index].producer_tid=j->producer_tid;
        memcpy(replies[index].request_wire,j->wire,48);stats.owned_replies++;
    }
    pthread_mutex_unlock(&mutex);
    /* Never overwrite or release another in-flight allocation returned twice. */
    if(alias)return -EADDRINUSE;
    int rc=allocated;
    if(!rc && j->io.size(p)!=48)rc=-EMSGSIZE;
    uint8_t wire[48]={0};p16(wire+2,(uint16_t)(2*command+1));p32(wire+0x14,(uint32_t)error);
    wire[0x18]=j->wire[0x18];wire[0x1c]=j->wire[0x1c];p16(wire+0x1a,u16(j->wire+0x1a));p32(wire+0x24,EVENT_MESSAGE);
    if(!rc){memcpy(p,wire,48);j->io.set_source(p,FUNCTIONAL_MPR_CODEC_DESTINATION);
        if(!canonical(&j->io,p,wire,FUNCTIONAL_MPR_CODEC_DESTINATION))rc=-EBADMSG;}
    if(!rc){
        pthread_mutex_lock(&mutex);memcpy(replies[index].wire,wire,48);replies[index].stage=1;pthread_mutex_unlock(&mutex);
        rc=j->io.send(FUNCTIONAL_MPR_CODEC_SOURCE,p);
        pthread_mutex_lock(&mutex);
        if(!rc){stats.events_sent++;if(replies[index].pointer==p)replies[index].stage=2;}
        pthread_mutex_unlock(&mutex);
    }
    if(rc){
        int drop=0;int owned=functional_mpr_codec_release_if_owned(FUNCTIONAL_MPR_CODEC_SOURCE,p,&j->io,&drop);
        if(owned && drop){
            char text[128];snprintf(text,sizeof text,"primary_error=%d release_error=%d retained=1",rc,drop);
            note(&j->io,"FUNCTIONAL_MPR_RELEASE_FAILED ",text);
        }
    }
    return rc;
}
static int bridge(const struct fcam_native_origin *origin,unsigned opcode,const void *input,size_t size,
                  void *output,size_t capacity,struct fcam_bridge_result *r) {
    int rc=fcam_bridge_call(origin,opcode,input,size,output,capacity,r);
    if(rc)return rc;
    if(r->used>capacity || !r->model_instance || (model_instance && r->model_instance!=model_instance))return -ESTALE;
    if(!model_instance)model_instance=r->model_instance;
    pthread_mutex_lock(&mutex);stats.model_instance=model_instance;pthread_mutex_unlock(&mutex);return 0;
}
static int state_call(const struct fcam_native_origin *origin,unsigned opcode,const void *input,size_t n,uint8_t out[128]) {
    struct fcam_bridge_result r={0};int rc=bridge(origin,opcode,input,n,out,128,&r);
    if(rc)return rc;
    if(r.used!=128 || u32(out)!=FCAM_ABI_VERSION || u64(out+FCAM_S_INSTANCE)!=model_instance ||
       !(u32(out+FCAM_S_CAPS)&FCAM_CAP_H264))return -EPROTO;
    return 0;
}
static void pi_note(const char *tag,const struct publication *p,uint32_t read_before,uint32_t read_after,
                    uint32_t write,uint32_t counter_before,uint32_t counter_after,
                    uint32_t outstanding_before,uint32_t outstanding_after) {
    char text[1024],hex[INFO_BYTES*2+1];hex_bytes(p->info,INFO_BYTES,hex);
    int n=snprintf(text,sizeof text,
        "epoch=%" PRIu64 " instance=%#" PRIx64 " native_start_fnv=%#" PRIx64
        " memory_generation=%" PRIu64 " group=%u pi_token=%#" PRIx64 " es_token=%#" PRIx64
        " request_seq=%" PRIu64 " call_request_seq=%" PRIu64 " call_native_fnv=%#" PRIx64
        " model_token=%#" PRIx64 " result_bytes=%zu ticket=%" PRIu64 " slot=%u slot_generation=%" PRIu64 " cycle=%" PRIu64
        " frame_generation=%" PRIu64 " es_offset=%zu es_bytes=%zu es_fnv=%#" PRIx64
        " read_address=%#" PRIx64 " read_token=%#" PRIx64 " control_token=%#" PRIx64
        " read_before=%u read_after=%u read_seen=%u write_before=%u write_after=%u observed_write=%u"
        " counter_before=%u counter_after=%u outstanding_before=%u outstanding_after=%u"
        " pid=%ld observer_tid=%ld info_address=%#" PRIx64 " info_hex=%s rc=0",
        start_job.epoch,model_instance,start_job.origin.wire_fnv1a64,
        live.pins[PIN_ES].span.generation,live.pins[PIN_ES].span.group,live.pins[PIN_INFO].token,live.pins[PIN_ES].token,
        start_job.request_sequence,p->call_request_sequence,p->call_native_fnv,p->model_token,p->result_bytes,
        p->ticket,p->slot,p->slot_generation,p->cycle,p->frame_generation,p->es_offset,p->es_bytes,p->es_fnv,
        live.read,live.pins[PIN_READ].token,live.pins[PIN_CONTROL].token,
        read_before,read_after,live.read_seen,p->write_before,p->write_after,write,counter_before,counter_after,
        outstanding_before,outstanding_after,(long)getpid(),(long)syscall(SYS_gettid),
        live.info+(uint64_t)p->slot*INFO_BYTES,hex);
    if(n<0 || (size_t)n>=sizeof text)note(&start_job.io,"FUNCTIONAL_MPR_RECEIPT_ERROR ","stage=pi rc=-75");
    else note(&start_job.io,tag,text);
}
static int ring_space(unsigned needed) {
    uint32_t r,w,before,after;int rc=validate_open(&live);if(rc)return rc;
    if((rc=read32(live.read,&r)))return rc;
    atomic_thread_fence(memory_order_acquire);
    if((rc=read32(live.write,&w)) || (rc=read32(live.counter,&before)) || (rc=validate_open(&live)))return rc;
    if(r>=live.slots || w!=live.cursor || !publications)return -ESTALE;
    uint32_t returned=r>=live.read_seen?r-live.read_seen:r+live.slots-live.read_seen;
    if(returned>live.outstanding)return -ESTALE;
    /* Verify every retained ticket before acknowledging any native cursor advance. */
    uint32_t slot=live.read_seen;uint8_t actual[INFO_BYTES];
    for(uint32_t i=0;i<returned;i++){
        if(++slot==live.slots)slot=0;
        const struct publication *p=&publications[slot];
        if(!p->published || p->ticket!=retired_ticket+i+1 || p->slot!=slot)return -ESTALE;
        if((rc=memory_read(live.info+(uint64_t)slot*INFO_BYTES,actual,sizeof actual)))return rc;
        if(memcmp(actual,p->info,sizeof actual))return -EBADMSG;
    }
    if((rc=read32(live.counter,&after)) || (rc=validate_open(&live)))return rc;
    uint32_t read_before=live.read_seen,outstanding_before=live.outstanding;
    live.outstanding-=returned;live.read_seen=r;
    pthread_mutex_lock(&mutex);stats.original_slots_returned+=returned;pthread_mutex_unlock(&mutex);
    slot=read_before;
    for(uint32_t i=0;i<returned;i++){
        if(++slot==live.slots)slot=0;
        struct publication *p=&publications[slot];p->published=0;retired_ticket++;
        pi_note("FUNCTIONAL_MPR_PI_RETURN ",p,read_before,r,w,before,after,outstanding_before,live.outstanding);
    }
    if(needed>live.slots-1-live.outstanding){
        pthread_mutex_lock(&mutex);stats.backpressure++;pthread_mutex_unlock(&mutex);return -EAGAIN;
    }
    return 0;
}
static int wait_ring(unsigned needed) {
    struct timespec until,now;
    if(clock_gettime(CLOCK_MONOTONIC,&until))return -errno;
    until.tv_sec+=2;
    for(;;){
        int rc=ring_space(needed);if(rc!=-EAGAIN)return rc;
        if(clock_gettime(CLOCK_MONOTONIC,&now))return -errno;
        if(now.tv_sec>until.tv_sec || (now.tv_sec==until.tv_sec && now.tv_nsec>=until.tv_nsec))return -ETIMEDOUT;
        const struct timespec pause={0,1000000};
        if(nanosleep(&pause,NULL) && errno!=EINTR)return -errno;
    }
}
static int write_check(enum buffer_pin kind,size_t offset,const uint8_t *bytes,size_t n) {
    int rc=validate_open(&live);if(rc)return rc;
    return functional_mpr_memory_write(&live.pins[kind],offset,bytes,n);
}
static int publish_info(const uint8_t info[96],struct publication *receipt) {
    int rc=ring_space(1);if(rc)return rc;
    uint32_t next=live.cursor+1;if(next==live.slots)next=0;
    if(publications[next].published || publication_ticket==UINT64_MAX || publications[next].slot_generation==UINT64_MAX)return -ESTALE;
    struct publication p=*receipt;
    p.ticket=publication_ticket+1;p.slot=next;p.slot_generation=publications[next].slot_generation+1;
    p.cycle=p.ticket/live.slots;p.write_before=live.cursor;p.write_after=next;
    p.outstanding_before=live.outstanding;p.outstanding_after=live.outstanding+1;
    if((rc=read32(live.read,&p.read_before)) || (rc=read32(live.counter,&p.counter_before)))return rc;
    if((rc=write_check(PIN_INFO,(size_t)next*INFO_BYTES,info,INFO_BYTES)))return rc;
    if((rc=memory_read(live.info+(uint64_t)next*INFO_BYTES,p.info,INFO_BYTES)))return rc;
    if(memcmp(p.info,info,INFO_BYTES))return -EIO;
    if((rc=validate_open(&live)))return rc;
    atomic_thread_fence(memory_order_release);
#if defined(__aarch64__)
    __asm__ __volatile__("dsb sy" ::: "memory");
#endif
    uint8_t b[4];p32(b,next);if((rc=write_check(PIN_CONTROL,4,b,4)))return rc;
    /* Cursor publication is irreversible even if a following observation fails. */
    p.published=1;publications[next]=p;publication_ticket=p.ticket;live.cursor=next;live.outstanding++;
    pthread_mutex_lock(&mutex);stats.pi_published++;
    if(info[0]==0 || info[0]==1)stats.frames_published++;
    pthread_mutex_unlock(&mutex);
    uint32_t write;
    if((rc=read32(live.read,&p.read_after)) || (rc=read32(live.write,&write)) ||
       (rc=read32(live.counter,&p.counter_after)) || (rc=validate_open(&live)))return rc;
    if(write!=next || p.read_before>=live.slots || p.read_after>=live.slots)return -ESTALE;
    publications[next]=p;*receipt=p;
    pi_note("FUNCTIONAL_MPR_PI_PUBLISH ",&p,p.read_before,p.read_after,write,p.counter_before,p.counter_after,
            p.outstanding_before,p.outstanding_after);
    return 0;
}
static int prefix(const uint8_t *p,size_t n) {
    if(n>=4 && !p[0] && !p[1] && !p[2] && p[3]==1)return 4;
    return n>=3 && !p[0] && !p[1] && p[2]==1?3:0;
}
/* Preserve every NAL byte. Only Annex-B delimiters become BE32 lengths. */
static int convert(const uint8_t *p,size_t n,uint8_t *out,size_t cap,size_t *used,
                   uint16_t *sps,uint16_t *pps,int config) {
    size_t in=0,o=0;unsigned ns=0,np=0,nvcl=0;
    while(in<n){int skip=prefix(p+in,n-in);if(!skip)return -EBADMSG;
        size_t begin=in+(unsigned)skip,end=begin;
        while(end<n && !prefix(p+end,n-end))end++;
        size_t k=end-begin;if(!k || k>UINT32_MAX || (p[begin]&0x80))return -EBADMSG;
        unsigned type=p[begin]&31u;if(type==7)ns++;if(type==8)np++;if(type>=1 && type<=5)nvcl++;
        if(config && type!=7 && type!=8)return -ENOTSUP;
        if(k>cap-o || cap-o-k<4)return -ENOSPC;
        if(config && k+4>UINT16_MAX)return -E2BIG;
        be32(out+o,(uint32_t)k);memcpy(out+o+4,p+begin,k);
        if(config && type==7){if(np)return -ENOTSUP;*sps=(uint16_t)(k+4);}
        if(config && type==8)*pps=(uint16_t)(k+4);
        o+=k+4;in=end;
    }
    if(config?(ns!=1 || np!=1):!nvcl)return -ENODATA;
    *used=o;return 0;
}
static int nal_digest(const uint8_t *p,size_t n,uint32_t *count,uint64_t *digest) {
    size_t offset=0;uint32_t total=0;uint64_t value=UINT64_C(14695981039346656037);
    while(offset<n){
        if(n-offset<4 || total==UINT32_MAX)return -EBADMSG;
        uint32_t bytes=(uint32_t)p[offset]<<24|(uint32_t)p[offset+1]<<16|(uint32_t)p[offset+2]<<8|p[offset+3];
        offset+=4;if(!bytes || bytes>n-offset)return -EBADMSG;
        value=fnv_more(value,p+offset,bytes);offset+=bytes;total++;
    }
    *count=total;*digest=value;return total?0:-ENODATA;
}
static int es_readback(size_t offset,const uint8_t *expected,size_t n,uint64_t *digest) {
    uint8_t actual[4096];uint64_t value=UINT64_C(14695981039346656037);
    int rc=validate_open(&live);
    for(size_t done=0;!rc && done<n;){
        size_t bytes=n-done<sizeof actual?n-done:sizeof actual;
        rc=memory_read(live.es+offset+done,actual,bytes);
        if(!rc && memcmp(actual,expected+done,bytes))rc=-EIO;
        if(!rc)value=fnv_more(value,actual,bytes);
        done+=bytes;
    }
    if(!rc)rc=validate_open(&live);
    if(!rc)*digest=value;
    return rc;
}
static void es_note(const struct publication *p) {
    char text[896];
    snprintf(text,sizeof text,
        "epoch=%" PRIu64 " instance=%#" PRIx64 " native_start_fnv=%#" PRIx64
        " request_seq=%" PRIu64 " call_request_seq=%" PRIu64 " call_native_fnv=%#" PRIx64
        " memory_generation=%" PRIu64 " group=%u es_token=%#" PRIx64
        " address=%#" PRIx64 " offset=%zu bytes=%zu avcc_fnv=%#" PRIx64
        " nal_count=%u nal_payload_fnv=%#" PRIx64 " frame_generation=%" PRIu64 " packet_sequence=%" PRIu64
        " model_token=%#" PRIx64 " result_bytes=%zu source_offset=%zu source_bytes=%zu source_fnv=%#" PRIx64
        " info_type=%u pid=%ld observer_tid=%ld rc=0",
        start_job.epoch,model_instance,start_job.origin.wire_fnv1a64,start_job.request_sequence,
        p->call_request_sequence,p->call_native_fnv,live.pins[PIN_ES].span.generation,live.pins[PIN_ES].span.group,
        live.pins[PIN_ES].token,live.es+p->es_offset,p->es_offset,p->es_bytes,p->es_fnv,
        p->nal_count,p->nal_fnv,p->frame_generation,p->packet_index,p->model_token,p->result_bytes,
        p->source_offset,p->source_bytes,p->source_fnv,p->info[0],(long)getpid(),(long)syscall(SYS_gettid));
    note(&start_job.io,"FUNCTIONAL_MPR_ES ",text);
}
static int put_es_info(uint8_t info[96],const uint8_t *p,size_t n,struct publication *receipt) {
    /* shortcut: monotonic ES per open; reuse only with a native retirement contract. */
    if(!n || n>live.capacity-live.used)return -ENOSPC;
    int rc=nal_digest(p,n,&receipt->nal_count,&receipt->nal_fnv);if(rc)return rc;
    size_t offset=live.used;
    rc=write_check(PIN_ES,offset,p,n);if(rc)return rc;
    /* A successful serialized write reserves the extent even on a later read error. */
    live.used+=n;
    pthread_mutex_lock(&mutex);stats.es_used=live.used;pthread_mutex_unlock(&mutex);
    rc=es_readback(offset,p,n,&receipt->es_fnv);if(rc)return rc;
    receipt->es_offset=offset;receipt->es_bytes=n;memcpy(receipt->info,info,INFO_BYTES);
    p64(info+8,live.es+offset-live.correction);p32(info+0x10,(uint32_t)n);
    pthread_mutex_lock(&mutex);stats.es_bytes_readback+=n;pthread_mutex_unlock(&mutex);
    es_note(receipt);
    return publish_info(info,receipt);
}
static int packet_result(const uint8_t *p,size_t n,int draining,uint64_t token,const struct job *call) {
    size_t off=0;int saw_eos=0;
    if(!n)return -ENODATA;
    while(off<n){
        if(n-off<96)return -EMSGSIZE;
        const uint8_t *h=p+off;uint64_t count=u64(h+48),generation=u64(h+56);uint32_t config=u32(h+64),flags=u32(h+44);
        if(u32(h)!=live.width || u32(h+4)!=live.height || u32(h+32)!=1 || u32(h+36)!=VIRTUAL_FPS ||
           u32(h+68)!=FCAM_CODEC_AVC1 || u32(h+40)>1 || (flags&~FCAM_PACKET_EOS) ||
           (!draining && flags) || count>n-off-96 || config>n-off-96-(size_t)count)return -EPROTO;
        for(unsigned i=72;i<96;i++)if(h[i])return -EPROTO;
        if((flags&FCAM_PACKET_EOS) && off+96+config+(size_t)count!=n)return -EPROTO;
        if(saw_eos)return -EPROTO;
        saw_eos=(flags&FCAM_PACKET_EOS)!=0;
        if(!count){
            if(!draining || !saw_eos || config || u64(h+24) || off+96!=n)return -EPROTO;
            if(u64(h+8)!=packet_sequence || u64(h+16)!=packet_sequence || generation!=frame_generation)return -ESTALE;
            off+=96;continue;
        }
        if(config_published && (config!=configuration_bytes || fnv(h+96,config)!=configuration_fnv))return -ENOTSUP;
        if(u64(h+8)!=packet_sequence || u64(h+16)!=packet_sequence || u64(h+24)!=1 || generation<=frame_generation)return -ESTALE;
        if(packet_sequence>=UINT32_MAX || packet_sequence>UINT64_MAX/(NATIVE_HZ/VIRTUAL_FPS))return -EOVERFLOW;
        pthread_mutex_lock(&mutex);stats.backend_frames++;stats.backend_packet_bytes+=count;pthread_mutex_unlock(&mutex);
        uint64_t native_pts=packet_sequence*(NATIVE_HZ/VIRTUAL_FPS);
        /* Stop holds the original API lock: retain room for drain plus EOS. */
        unsigned needed=(config_published?1u:2u)+(draining?0u:2u);
        int rc=wait_ring(needed);if(rc)return rc;
        const uint8_t *configuration=h+96,*packet=configuration+config;
        struct publication receipt={.frame_generation=generation,.packet_index=packet_sequence,
            .model_token=token,.call_native_fnv=call->origin.wire_fnv1a64,
            .call_request_sequence=call->request_sequence,.result_bytes=n};
        size_t bytes=0;uint16_t sps=0,pps=0;
        if(!config_published){
            if(!u32(h+40) || !config)return -ENODATA;
            rc=convert(configuration,config,avcc,avcc_capacity,&bytes,&sps,&pps,1);if(rc)return rc;
            uint8_t info[96]={0};info[0]=4;info[1]=6;p16(info+0x2c,sps);info[0x2e]=1;p16(info+0x30,pps);info[0x32]=1;
            p64(info+8,0x1000);p32(info+0x10,(uint32_t)bytes);
            struct nparamsets parsed;
            rc=nparamsets_parse(info,96,NPARAMSETS_AVC1,0,0x1000,avcc,bytes,&parsed,sizeof parsed);if(rc)return rc;
            if(bytes>live.capacity-live.used)return -ENOSPC;
            /* Reserve AU capacity before publishing its parameter-set descriptor. */
            size_t normal=0;uint16_t ignored=0;
            rc=convert(packet,(size_t)count,avcc+bytes,avcc_capacity-bytes,&normal,&ignored,&ignored,0);if(rc)return rc;
            if(normal>live.capacity-live.used-bytes)return -ENOSPC;
            receipt.source_offset=off+96;receipt.source_bytes=config;receipt.source_fnv=fnv(configuration,config);
            rc=put_es_info(info,avcc,bytes,&receipt);if(rc)return rc;
            configuration_fnv=fnv(configuration,config);configuration_bytes=config;config_published=1;
            memmove(avcc,avcc+bytes,normal);bytes=normal;
        }else{rc=convert(packet,(size_t)count,avcc,avcc_capacity,&bytes,&sps,&pps,0);if(rc)return rc;}
        uint8_t info[96]={0};info[0]=u32(h+40)?0:1;p64(info+8,0x1000);p32(info+0x10,(uint32_t)bytes);
        p64(info+0x18,native_pts);p64(info+0x20,native_pts);size_t nal_count=0;
        rc=nlength_validate(info,96,0,0x1000,avcc,bytes,NLENGTH_AVC1,&nal_count);if(rc)return rc;
        receipt.source_offset=off+96+config;receipt.source_bytes=(size_t)count;receipt.source_fnv=fnv(packet,(size_t)count);
        rc=put_es_info(info,avcc,bytes,&receipt);if(rc)return rc;
        frame_generation=generation;packet_sequence++;
        uint8_t counter[4];uint32_t counter_before,counter_after,read_after,write_after;
        if((rc=read32(live.counter,&counter_before)))return rc;
        p32(counter,(uint32_t)packet_sequence);
        atomic_thread_fence(memory_order_release);
        rc=write_check(PIN_CONTROL,0,counter,sizeof counter);if(rc)return rc;
        if((rc=read32(live.counter,&counter_after)) || (rc=read32(live.read,&read_after)) ||
           (rc=read32(live.write,&write_after)) || (rc=validate_open(&live)))return rc;
        if(counter_after!=(uint32_t)packet_sequence || write_after!=live.cursor || read_after>=live.slots)return -ESTALE;
        char text[768];
        snprintf(text,sizeof text,"epoch=%" PRIu64 " instance=%#" PRIx64 " native_start_fnv=%#" PRIx64
                 " frame_generation=%" PRIu64 " packet_bytes=%" PRIu64 " avcc_bytes=%zu avcc_fnv=%#" PRIx64
                 " native_pts=%" PRIu64 " native_hz=%u es_used=%zu es_capacity=%zu"
                 " memory_generation=%" PRIu64 " request_seq=%" PRIu64 " ticket=%" PRIu64
                 " slot=%u slot_generation=%" PRIu64 " model_token=%#" PRIx64
                 " counter_before=%u counter_after=%u read_after=%u write_after=%u"
                 " es_address=%#" PRIx64 " es_offset=%zu es_token=%#" PRIx64,
                 start_job.epoch,model_instance,start_job.origin.wire_fnv1a64,generation,count,bytes,receipt.es_fnv,
                 native_pts,NATIVE_HZ,live.used,live.capacity,live.pins[PIN_ES].span.generation,
                 start_job.request_sequence,receipt.ticket,receipt.slot,receipt.slot_generation,token,
                 counter_before,counter_after,read_after,write_after,live.es+receipt.es_offset,receipt.es_offset,
                 live.pins[PIN_ES].token);
        note(&start_job.io,"FUNCTIONAL_MPR_PACKET ",text);
        off+=96+config+(size_t)count;
    }
    if(draining && !saw_eos)return -ENODATA;
    return 0;
}
static int next_frame(void) {
    int rc=ring_space(config_published?3:4);if(rc)return rc;
    struct fcam_bridge_result r={0};
    rc=bridge(&start_job.origin,FCAM_OP_VIDEO_FRAME,NULL,0,result_bytes,RESULT_CAP,&r);
    return rc?rc:packet_result(result_bytes,r.used,0,r.result_token,&start_job);
}
static int drain(const struct job *j) {
    int rc=wait_ring(2);if(rc)return rc;
    struct fcam_bridge_result r={0};rc=bridge(&j->origin,FCAM_OP_VIDEO_END,NULL,0,result_bytes,RESULT_CAP,&r);
    if(rc)return rc;
    stream_live=0;rc=packet_result(result_bytes,r.used,1,r.result_token,j);if(rc)return rc;
    uint8_t eos[96]={0};eos[0]=7;p64(eos+0x18,packet_sequence*(NATIVE_HZ/VIRTUAL_FPS));p64(eos+0x20,u64(eos+0x18));
    struct publication receipt={.frame_generation=frame_generation,.packet_index=packet_sequence,
        .model_token=r.result_token,.call_native_fnv=j->origin.wire_fnv1a64,
        .call_request_sequence=j->request_sequence,.result_bytes=r.used};
    return publish_info(eos,&receipt);
}
static int execute(const struct job *j) {
    int rc=0;uint8_t state[128];
    if(j->command==0){
        live=j->lease;frame_generation=packet_sequence=configuration_fnv=0;configuration_bytes=0;config_published=0;
        publication_ticket=retired_ticket=0;
        free(publications);publications=calloc(live.slots,sizeof *publications);
        rc=publications?validate_open(&live):-ENOMEM;
        if(!rc)rc=state_call(&j->origin,FCAM_OP_INIT,NULL,0,state);
        if(!rc)rc=validate_open(&live);
        if(!rc){
            pthread_mutex_lock(&mutex);stats.epoch++;stats.es_capacity=live.capacity;stats.es_used=0;
            stats.memory_generation=live.pins[PIN_ES].span.generation;stats.state=FMPR_OPEN;pthread_mutex_unlock(&mutex);
            char text[512];snprintf(text,sizeof text,"width=%u height=%u virtual_fps=%u audio_field=3 es_capacity=%zu pi_slots=%u P=%#" PRIx64 " V=%#" PRIx64
                " epoch=%" PRIu64 " instance=%#" PRIx64 " request_seq=%" PRIu64 " native_fnv=%#" PRIx64
                " memory_generation=%" PRIu64 " es_address=%#" PRIx64 " info_address=%#" PRIx64
                " read_address=%#" PRIx64 " write_address=%#" PRIx64 " counter_address=%#" PRIx64 " es_correction=%#" PRIx64,
                live.width,live.height,VIRTUAL_FPS,live.capacity,live.slots,u64(j->wire+8),u64(j->wire+0x28),
                j->epoch,model_instance,j->request_sequence,j->origin.wire_fnv1a64,live.pins[PIN_ES].span.generation,
                live.es,live.info,live.read,live.write,live.counter,live.correction);
            note(&j->io,"FUNCTIONAL_MPR_OPEN ",text);
        }
    }else if(j->command==1){
        uint8_t config[48]={0};
        rc=validate_open(&live);if(rc)return rc;
        rc=state_call(&j->origin,FCAM_OP_STATE,NULL,0,state);if(rc)return rc;
        p32(config,live.width);p32(config+4,live.height);p32(config+8,VIRTUAL_FPS);
        p32(config+12,u32(state+FCAM_S_QUALITY));p32(config+16,u32(state+FCAM_S_FNUMBER));p32(config+20,u32(state+FCAM_S_ISO));
        p64(config+24,u64(state+FCAM_S_SHUTTER));p64(config+32,u64(state+FCAM_S_FOCUS));
        start_job=*j;
        rc=state_call(&j->origin,FCAM_OP_VIDEO_BEGIN,config,sizeof config,state);
        if(!rc && (u32(state+FCAM_S_WIDTH)!=live.width || u32(state+FCAM_S_HEIGHT)!=live.height ||
           u32(state+FCAM_S_FPS)!=VIRTUAL_FPS || u32(state+FCAM_S_STREAM_STATE)!=1))rc=-EPROTO;
        if(!rc){stream_live=1;rc=next_frame();}
        if(!rc){pthread_mutex_lock(&mutex);stats.state=FMPR_RECORDING;stats.native_start_fnv=j->origin.wire_fnv1a64;pthread_mutex_unlock(&mutex);}
    }else if(j->command==3){
        if(stream_live)rc=drain(j);else rc=-EPIPE;
        if(!rc){pthread_mutex_lock(&mutex);stats.state=FMPR_DRAINED;pthread_mutex_unlock(&mutex);}
    }else if(j->command==4){
        if(stream_live)rc=drain(j);
        int cancelled=state_call(&j->origin,FCAM_OP_CANCEL,NULL,0,state);
        if(!cancelled && u32(state+FCAM_S_STREAM_STATE))cancelled=-EPROTO;
        if(cancelled)return rc?rc:cancelled;
        if(live.slots){int observed=ring_space(0);if(!rc)rc=observed;}
        /* Original Close may release DMM even when its event reports an error. */
        int released=release_open(&live);if(!rc)rc=released;
        stream_live=0;free(publications);publications=NULL;
        memset(&live,0,sizeof live);memset(&start_job,0,sizeof start_job);
        pthread_mutex_lock(&mutex);stats.memory_generation=0;stats.state=FMPR_CLOSED;pthread_mutex_unlock(&mutex);
    }else rc=-ENOTSUP;
    return rc;
}
static struct timespec after_ms(unsigned ms) {
    struct timespec t;clock_gettime(CLOCK_REALTIME,&t);t.tv_nsec+=(long)ms*1000000;
    t.tv_sec+=t.tv_nsec/1000000000;t.tv_nsec%=1000000000;return t;
}
static void *run(void *unused) {
    (void)unused;
    for(;;){
        pthread_mutex_lock(&mutex);
        while(!queued && !stopping){
            if(stats.state==FMPR_RECORDING){struct timespec deadline=after_ms(1000/VIRTUAL_FPS);int wait_rc=pthread_cond_timedwait(&wake,&mutex,&deadline);if(wait_rc==ETIMEDOUT)break;}
            else pthread_cond_wait(&wake,&mutex);
        }
        if(stopping){pthread_mutex_unlock(&mutex);break;}
        int have_job=queued;struct job j;
        if(have_job){j=pending;memset(&pending,0,sizeof pending);queued=0;}working=1;pthread_mutex_unlock(&mutex);
        int rc=have_job?execute(&j):next_frame();
        if(rc==-EAGAIN && !have_job)rc=0;
        if(rc){
            (void)release_open(&live);failed(rc);
            /* A completed Close can be quiescent while retaining its real drain error. */
            if(have_job && j.command==4 && !stream_live && !live.slots){
                pthread_mutex_lock(&mutex);stats.state=FMPR_CLOSED;pthread_mutex_unlock(&mutex);
            }
        }
        if(rc && !have_job){
            /* ConvertAvconEvent(4e0,0b)=1010 reaches original encode-error handling. */
            int event_rc=send_event(&start_job,5,rc);if(event_rc){(void)release_open(&live);failed(event_rc);}
        }
        if(have_job){
            /* Original receiver can wake its sender before send() returns. */
            pthread_mutex_lock(&mutex);reserved=0;stats.pending=0;pthread_mutex_unlock(&mutex);
            int event_rc=send_event(&j,j.command,rc);if(event_rc){(void)release_open(&live);failed(event_rc);}
            char text[384];snprintf(text,sizeof text,"command=%u native_fnv=%#" PRIx64 " operation_error=%d event_error=%d"
                                   " request_seq=%" PRIu64 " epoch=%" PRIu64 " memory_generation=%" PRIu64
                                   " instance=%#" PRIx64 " pid=%ld producer_tid=%ld",
                                   j.command,j.origin.wire_fnv1a64,rc,event_rc,j.request_sequence,j.epoch,j.memory_generation,
                                   model_instance,j.producer_pid,j.producer_tid);
            note(&j.io,"FUNCTIONAL_MPR_OPERATION ",text);
        }
        pthread_mutex_lock(&mutex);working=0;pthread_cond_broadcast(&wake);pthread_mutex_unlock(&mutex);
    }
    int released=release_open(&live);if(released)failed(released);
    free(publications);publications=NULL;
    memset(&live,0,sizeof live);memset(&start_job,0,sizeof start_job);
    pthread_mutex_lock(&mutex);stats.worker_live=0;stats.memory_generation=0;pthread_mutex_unlock(&mutex);return NULL;
}
int functional_mpr_codec_owner_init(void) {
    pid_t expected=0,pid=getpid();
    if(!atomic_compare_exchange_strong_explicit(&owner,&expected,pid,memory_order_acq_rel,memory_order_acquire))return expected==pid?0:-ECHILD;
    return 0;
}
int functional_mpr_codec_bind(uintptr_t base,const char *sha256) {
    int rc=guard();if(rc)return rc;
    if(!base || base>UINTPTR_MAX-0x3b8170 || !sha256 || strcmp(sha256,FUNCTIONAL_MPR_CODEC_LIBRARY_SHA256))return -EINVAL;
    /* This actual instruction pin is additional to the caller's full-file hash. */
    static const uint8_t pin[16]={0xfd,0x7b,0xb8,0xa9,0xfd,0x03,0x00,0x91,0xf3,0x53,0x01,0xa9,0xf4,0x03,0x00,0xaa};
    uint8_t bytes[16];rc=memory_read(base+0x283e74,bytes,sizeof bytes);if(rc)return rc;
    if(memcmp(pin,bytes,sizeof pin))return -ELIBBAD;
    pthread_mutex_lock(&mutex);
    if(started || reserved)rc=-EBUSY;else if(library && library!=base)rc=-EBUSY;else library=base;
    pthread_mutex_unlock(&mutex);return rc;
}
int functional_mpr_codec_dispatch(unsigned int dst,void *request,const struct full_imaging_io *io,int enabled,int *result) {
    if(enabled!=1 || dst!=FUNCTIONAL_MPR_CODEC_DESTINATION)return 0;
    if(!result)return 0;
    int rc=guard();if(rc){*result=rc;return 1;}
    if(!valid_io(io) || !request){*result=-EINVAL;return 1;}
    if(io->source(request)!=FUNCTIONAL_MPR_CODEC_SOURCE)return 0;
    if(io->size(request)!=48){*result=-EMSGSIZE;return 1;}
    struct job j={0};memcpy(j.wire,request,48);j.io=*io;j.command=u16(j.wire+2);
    unsigned message=u32(j.wire+0x24);
    if(message!=MPR_MESSAGE){if(message==0x1610){*result=-ENOTSUP;return 1;}return 0;}
    if(j.command>4)return 0;
    if(j.command==2){*result=-ENOTSUP;note(io,"FUNCTIONAL_MPR_UNSUPPORTED ","EncIPicture needs a real force-IDR model operation");return 1;}
    unsigned expected=j.command==0?0x98:j.command==1?0x80:j.command==3?0x10:0;
    if(u32(j.wire+0x10)!=expected || j.wire[0x19] || j.wire[0x1e] || u16(j.wire+0x1a) || j.wire[0x18]!=0x20 || j.wire[0x1c]==0x44){*result=-ENOTSUP;return 1;}
    j.origin=(struct fcam_native_origin){FUNCTIONAL_MPR_CODEC_SOURCE,dst,j.command,48,fnv(j.wire,48)};
    pthread_mutex_lock(&mutex);
    uintptr_t base=library;
    if(!base)rc=-ENODEV;else if(stopping)rc=-ESHUTDOWN;else if(reserved)rc=-EBUSY;
    else if(j.command==0 && stats.state!=FMPR_CLOSED)rc=-EALREADY;
    else if(j.command==1 && stats.state!=FMPR_OPEN)rc=-EPIPE;
    else if(j.command==3 && stats.state!=FMPR_RECORDING && stats.state!=FMPR_FAULT)rc=-EPIPE;
    else if(j.command==4 && stats.state==FMPR_CLOSED)rc=-EPIPE;
    else if(request_sequence==UINT64_MAX || (j.command==0 && stats.epoch==UINT64_MAX))rc=-EOVERFLOW;
    else {
        reserved=1;stats.pending=1;rc=0;
        j.request_sequence=++request_sequence;j.epoch=stats.epoch+(j.command==0);
        j.memory_generation=stats.memory_generation;j.instance=stats.model_instance;
        j.producer_pid=(long)getpid();j.producer_tid=(long)syscall(SYS_gettid);
    }
    pthread_mutex_unlock(&mutex);
    if(rc){*result=rc;return 1;}
    if(expected)rc=read_parameters(&j,expected,j.parameter);
    if(!rc && j.command==0){
        rc=snapshot_open(base,j.wire,j.parameter,&j.lease);
        if(!rc)j.memory_generation=j.lease.pins[PIN_ES].span.generation;
    }
    if(!rc && !canonical(io,request,j.wire,FUNCTIONAL_MPR_CODEC_SOURCE))rc=-EBADMSG;
    if(!rc){
        pthread_mutex_lock(&mutex);
        if(!started){result_bytes=malloc(RESULT_CAP);avcc_capacity=(size_t)RESULT_CAP*2+16;avcc=malloc(avcc_capacity);
            if(!result_bytes || !avcc)rc=-ENOMEM;
            else {int e=pthread_create(&worker,NULL,run,NULL);if(e)rc=-e;else{started=1;stats.worker_live=1;}}
            if(rc){free(result_bytes);free(avcc);result_bytes=avcc=NULL;}}
        if(!rc)pending=j;
        pthread_mutex_unlock(&mutex);
    }
    /* Scheduler owns pending's immutable copy before the original free. */
    if(!rc)rc=io->release(dst,request);
    request_note(&j,rc);
    if(rc)(void)release_open(&j.lease);
    pthread_mutex_lock(&mutex);
    if(!rc){queued=1;stats.accepted++;pthread_cond_signal(&wake);}
    else {memset(&pending,0,sizeof pending);reserved=0;stats.pending=0;stats.last_error=rc;stats.failures++;}
    pthread_mutex_unlock(&mutex);*result=rc;return 1;
}
int functional_mpr_codec_observe_received(unsigned int dst,void *p,const struct full_imaging_io *io) {
    int rc=guard();if(rc)return rc;if(dst!=FUNCTIONAL_MPR_CODEC_SOURCE || !p || !valid_io(io))return 0;
    uint8_t wire[48];unsigned index=REPLIES,stage=0;struct full_imaging_io expected_io;struct reply_lease observed;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<REPLIES;i++)if(replies[i].pointer==p){index=i;observed=replies[i];stage=observed.stage;memcpy(wire,observed.wire,48);expected_io=observed.io;break;}
    pthread_mutex_unlock(&mutex);if(index==REPLIES)return 0;
    if(stage!=1 && stage!=2)return stage==6?-EOVERFLOW:-EBUSY;
    if(!same_io(io,&expected_io) || !canonical(io,p,wire,FUNCTIONAL_MPR_CODEC_DESTINATION)){failed(-EBADMSG);return -EBADMSG;}
    int first=0;
    pthread_mutex_lock(&mutex);
    if(replies[index].pointer!=p || replies[index].sequence!=observed.sequence)rc=-ESTALE;
    else if(!replies[index].received){
        replies[index].received=1;replies[index].receiver_pid=(long)getpid();
        replies[index].receiver_tid=(long)syscall(SYS_gettid);stats.events_received++;first=1;
        observed=replies[index];
    }
    pthread_mutex_unlock(&mutex);
    if(rc)return rc;
    if(first)event_note(&observed,"FUNCTIONAL_MPR_EVENT_RECEIVED ",0);
    return 1;
}
int functional_mpr_codec_release_if_owned(unsigned int dst,void *p,const struct full_imaging_io *io,int *result) {
    int rc=guard();if(rc){if(result)*result=rc;return 1;}
    if(!p || !result || !valid_io(io))return 0;
    unsigned index=REPLIES;struct reply_lease r;
    pthread_mutex_lock(&mutex);
    for(unsigned i=0;i<REPLIES;i++)if(replies[i].pointer==p){index=i;r=replies[i];if(r.stage==3)rc=-EBUSY;else replies[i].stage=3;break;}
    pthread_mutex_unlock(&mutex);if(index==REPLIES)return 0;
    if(!rc && r.stage==6)rc=-EOVERFLOW;
    if(!rc && (dst!=FUNCTIONAL_MPR_CODEC_SOURCE || !same_io(io,&r.io)))rc=-EINVAL;
    if(!rc && r.stage!=4 && !canonical(io,p,r.wire,FUNCTIONAL_MPR_CODEC_DESTINATION))rc=-EBADMSG;
    int attempted=!rc;
    if(attempted)rc=io->release(dst,p);
    pthread_mutex_lock(&mutex);
    if(!rc){memset(&replies[index],0,sizeof replies[index]);stats.owned_replies--;}
    else {replies[index].stage=r.stage;stats.last_release_error=rc;}
    pthread_mutex_unlock(&mutex);
    if((r.stage==1 || r.stage==2) && attempted)
        event_note(&r,rc?"FUNCTIONAL_MPR_EVENT_FREE_FAILED ":"FUNCTIONAL_MPR_EVENT_FREE ",rc);
    if(rc)failed(rc);
    *result=rc;return 1;
}
int functional_mpr_codec_snapshot(struct functional_mpr_codec_snapshot *out) {
    int rc=guard();if(rc)return rc;if(!out)return -EINVAL;
    pthread_mutex_lock(&mutex);*out=stats;pthread_mutex_unlock(&mutex);return 0;
}
int functional_mpr_codec_shutdown(void) {
    int rc=guard();if(rc)return rc;
    pthread_mutex_lock(&mutex);
    if(stats.state!=FMPR_CLOSED || stats.pending || reserved || queued || working || joining){pthread_mutex_unlock(&mutex);return -EBUSY;}
    stopping=1;joining=1;pthread_cond_broadcast(&wake);int join=started;pthread_mutex_unlock(&mutex);
    if(join){int e=pthread_join(worker,NULL);if(e){pthread_mutex_lock(&mutex);joining=0;pthread_mutex_unlock(&mutex);return -e;}}
    /* No worker/request can acquire more pins while stopping/joining is set. */
    for(unsigned i=0;i<MEMORY_LEASES;i++){
        pthread_mutex_lock(&mutex);struct functional_mpr_memory_lease pin=held_memory[i];pthread_mutex_unlock(&mutex);
        int released=release_memory(&pin);if(!rc)rc=released;
    }
    pthread_mutex_lock(&mutex);started=0;joining=0;int retained=stats.owned_memory_leases!=0;
    for(unsigned i=0;i<REPLIES;i++)if(replies[i].pointer)retained=1;
    free(result_bytes);free(avcc);result_bytes=avcc=NULL;
    pthread_mutex_unlock(&mutex);return rc?rc:retained?-EBUSY:0;
}
