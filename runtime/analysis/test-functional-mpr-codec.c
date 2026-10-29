/* SPDX-License-Identifier: MIT */
/* HOST_TEST original transport/model/library fixtures; record memory is the
 * actual guarded provider. No original binary executes. */
#define FCAM_HOST_TEST 1
#include "functional-mpr-codec.c"
#include "../../report/native-video-ring-contract/native-ring.h"
#include <assert.h>
#include <stdbool.h>
#include <stdatomic.h>
#include <sys/mman.h>
#include <sys/wait.h>

#define LIB UINT64_C(0x10000000)
#define CORRECTION UINT64_C(0)
static uint64_t ES,SECONDARY,PI,READ,WRITE,FIXED,AUXILIARY;
static uint8_t library_bytes[0x400000],memory_table[0x760];
static uint8_t *es_bytes,*pi_bytes,*read_bytes,*write_bytes,*parameters;
static uint32_t memory_group;
static pthread_mutex_t memory_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t event_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t event_condition=PTHREAD_COND_INITIALIZER;
static unsigned events,event_commands[32];
static int event_errors[32];
static unsigned received_logs,free_logs;
static uint64_t close_received_sequence,close_freed_sequence;
static uint8_t request_receipts[128][48];
static unsigned request_receipt_count,es_receipt_count,pi_receipt_count,return_receipt_count,packet_receipt_count;
struct saved_publication {uint8_t info[96];uint64_t generation,slot_generation;unsigned slot,returned;};
static struct saved_publication publication_receipts[512];
static uint64_t slot_generations[65536],last_return_ticket;
static int defer_close_reply;
static _Atomic int close_reply_queued;
static void *deferred_close_reply;
static unsigned slots=8,es_extent=8192;
static int auto_consume=1,early_reply,corrupt_reply,event_bad_size,event_bad_source,event_send_error,request_free_error,event_allocate_error,event_pointer_wrap;
static _Atomic int corrupt_es,wrong_instance,short_packet,backend_error,gate_frame,frame_entered,allow_frame;
static _Atomic int gate_write,write_entered,allow_write,memory_release_error;
static _Atomic unsigned model_calls,model_frames,model_end,model_cancel,memory_writes,message_count;
static unsigned model_stream;
static uint64_t model_seq,model_gen=10;
static uint64_t last_es_address;
static unsigned consumed_normal,consumed_parameters,consumed_eos;
static const struct full_imaging_io test_io;
static const uint8_t annex_config[]={0,0,0,1,0x67,0x42,0,0x1f,0xaa,0,0,1,0x68,0xce,6,0xe2};
static const uint8_t first_packet[]={0,0,0,1,0x67,0x42,0,0x1f,0xaa,0,0,1,0x68,0xce,6,0xe2,0,0,0,1,0x65,0x88,0x84,0x21};
struct fixture_node {
    uint32_t type,group,unit,area;
    struct fixture_node *next;
    uint32_t extent_count,reserved;
    uintptr_t virtual_base;
    uint32_t size;
    uint8_t valid,padding[3];
    uintptr_t iova_base;
    uint32_t extent_size,tail;
};
_Static_assert(sizeof(struct fixture_node)==0x40,"original node fixture ABI");
static struct fixture_node *fixture_root;
static void fixture_area(uint8_t *t,unsigned at,const struct fixture_node *node,unsigned offset,unsigned bytes) {
    p64(t+at,node->virtual_base+offset);p64(t+at+8,node->iova_base+offset);
    p32(t+at+16,bytes);p64(t+at+24,node->virtual_base-node->iova_base);
}
/* Literal original default-branch table stores, not a codec-created arena. */
static void fixture_set_table(uint32_t group,int mode,void *out) {
    static const unsigned areas[][3]={
        {0x040,0x000000,0x06d000},{0x060,0x06d000,0x00e000},
        {0x140,0x07b000,0x000400},{0x160,0x07c000,0x000400},
        {0x260,0x07d000,0x200000},{0x280,0x27d000,0x001400},
        {0x2a0,0x27f000,0x000400},{0x2c0,0x280000,0x339000},
        {0x300,0x5b9000,0x006000},{0x320,0x5bf000,0x003000},
        {0x640,0x5c2000,0x003000},{0x660,0x5c5000,0x200000},
        {0x680,0x7c5000,0x001400},{0x6a0,0x7c7000,0x000400},
        {0x6c0,0x7c8000,0x003000},{0x6e0,0x7cb000,0x200000},
        {0x700,0x9cb000,0x001400},{0x720,0x9cd000,0x000400}};
    assert(mode==3);
    for(const struct fixture_node *n=fixture_root;n;n=n->next)if(n->group==group){
        assert(n->valid && n->extent_count==1 && n->size==n->extent_size);
        if(n->type==3)fixture_area(out,0,n,0,n->size);
        else if(n->type==4)fixture_area(out,0x20,n,0,n->size);
        else {assert(n->type==6);for(unsigned i=0;i<sizeof areas/sizeof areas[0];i++)
            fixture_area(out,areas[i][0],n,areas[i][1],areas[i][2]);}
    }
}
static void *fixture_select(int mode) {return mode==3?&fixture_root:NULL;}
void *fmpr_memory_test_next(const char *name) {
    void *p=NULL;
    if(!strcmp(name,"_ZN3mpr10DmmMemInfo9SetMemTblEjiPNS0_11BufferTableE")){
        void (*f)(uint32_t,int,void *)=fixture_set_table;memcpy(&p,&f,sizeof p);
    }else if(!strcmp(name,"_ZN3mpr10DmmMemInfo19UnitTypeTableSelectEi")){
        void *(*f)(int)=fixture_select;memcpy(&p,&f,sizeof p);
    }else if(!strcmp(name,"_ZN3mpr10DmmMemInfo19mp_AreaExtListStartE"))p=&fixture_root;
    else assert(!"unexpected original symbol");
    return p;
}
int fmpr_memory_test_binding(void) {return 0;}
void *fmpr_memory_test_mmap(void *hint,size_t n,int protection,int flags,int fd,off_t offset) {
    assert(!(flags&MAP_FIXED));return mmap(hint,n,protection,flags,fd,offset);
}
extern bool fmpr_memory_alloc(int,uint32_t *,void *) __asm__("_ZN3mpr10DmmMemInfo14AllocDmmMemoryEiPjPNS0_11BufferTableE");
extern char fmpr_memory_free_mask(int,unsigned) __asm__("_ZN3mpr10DmmMemInfo13FreeDmmMemoryEij");
extern void fmpr_memory_fixed(unsigned,void **,void **,uint32_t *) __asm__("_ZN3mpr6memory12GetFixedAreaENS0_13FixedAreaTypeEPPvS3_Pj");
static struct region {uint64_t base;uint8_t *data;size_t size;} regions[16];
static unsigned region_count;
static void register_table(const uint8_t table[0x760]) {
    static const unsigned offsets[]={0,0x20,0x40};
    static const unsigned capacities[]={32u<<20,8u<<20,16u<<20};
    for(unsigned i=0;i<3;i++){
        assert(region_count<16);uint64_t base=u64(table+offsets[i]);
        regions[region_count++]=(struct region){base,(uint8_t *)(uintptr_t)base,capacities[i]};
    }
}
static uint8_t *mapped(uint64_t a,size_t n) {
    if(a>=LIB && a-LIB<=sizeof library_bytes && n<=sizeof library_bytes-(size_t)(a-LIB))return library_bytes+(size_t)(a-LIB);
    for(unsigned i=0;i<region_count;i++)if(a>=regions[i].base && a-regions[i].base<=regions[i].size && n<=regions[i].size-(size_t)(a-regions[i].base))return regions[i].data+(size_t)(a-regions[i].base);
    return NULL;
}
int fmpr_test_memory_read(uint64_t a,void *out,size_t n) {
    pthread_mutex_lock(&memory_mutex);uint8_t *p=mapped(a,n);if(p)memcpy(out,p,n);pthread_mutex_unlock(&memory_mutex);return p?0:-EFAULT;
}
static void ms(unsigned n) { const struct timespec t={(time_t)(n/1000),(long)(n%1000)*1000000};nanosleep(&t,NULL); }
int __real_functional_mpr_memory_write(const struct functional_mpr_memory_lease *,size_t,const void *,size_t);
int __real_functional_mpr_memory_release(uint64_t);
int __wrap_functional_mpr_memory_write(const struct functional_mpr_memory_lease *pin,size_t offset,const void *input,size_t n) {
    int kind=pin->address==ES?1:pin->address==PI?2:pin->address==WRITE?(offset==4?3:4):0;
    if(kind && atomic_load(&gate_write)==kind){
        atomic_store(&write_entered,1);for(unsigned i=0;!atomic_load(&allow_write);i++){assert(i<5000);ms(1);}
    }
    pthread_mutex_lock(&memory_mutex);
    int rc=__real_functional_mpr_memory_write(pin,offset,input,n);
    if(!rc){
        atomic_fetch_add(&memory_writes,1);
        /* Inject a destination/readback failure at the test API boundary. */
        if(kind==1 && atomic_exchange(&corrupt_es,0)){((uint8_t *)pin->address)[offset]^=0x80;rc=-EBADMSG;}
    }
    pthread_mutex_unlock(&memory_mutex);return rc;
}
int __wrap_functional_mpr_memory_release(uint64_t token) {
    int error=atomic_load(&memory_release_error);
    return error?error:__real_functional_mpr_memory_release(token);
}
static void init_memory(void) {
    assert(!functional_mpr_memory_enable(NULL));
    assert(fmpr_memory_alloc(3,&memory_group,memory_table));register_table(memory_table);
    void *physical=NULL,*virtual_address=NULL;uint32_t bytes=0;
    fmpr_memory_fixed(2,&physical,&virtual_address,&bytes);
    assert(physical==virtual_address && virtual_address && bytes==512);
    FIXED=(uintptr_t)virtual_address;parameters=virtual_address;
    assert(region_count<16);regions[region_count++]=(struct region){FIXED,parameters,bytes};
    ES=u64(memory_table);es_bytes=(uint8_t *)(uintptr_t)ES;
    SECONDARY=u64(memory_table+0x20);PI=u64(memory_table+0x40);pi_bytes=(uint8_t *)(uintptr_t)PI;
    READ=u64(memory_table+0x140);read_bytes=(uint8_t *)(uintptr_t)READ;
    WRITE=u64(memory_table+0x160);write_bytes=(uint8_t *)(uintptr_t)WRITE;
    AUXILIARY=u64(memory_table+0x2c0);
    static const uint8_t pin[]={0xfd,0x7b,0xb8,0xa9,0xfd,0x03,0,0x91,0xf3,0x53,1,0xa9,0xf4,3,0,0xaa};
    memcpy(library_bytes+0x283e74,pin,sizeof pin);
    p64(library_bytes+0x3b7d68,ES);p64(library_bytes+0x3b7d70,es_extent);p64(library_bytes+0x3b7d78,CORRECTION);
    p64(library_bytes+0x3b7f70,PI);p64(library_bytes+0x3b80a8,PI);p32(library_bytes+0x3b80b0,slots);p64(library_bytes+0x3b80b8,CORRECTION);
    p64(library_bytes+0x3b7e58,READ);p64(library_bytes+0x3b7eb0,READ);p64(library_bytes+0x3b7ec0,CORRECTION);
    p64(library_bytes+0x3b7e68,WRITE+4);p64(library_bytes+0x3b8030,WRITE);p64(library_bytes+0x3b8040,CORRECTION);p64(library_bytes+0x3b8168,WRITE);
    p64(parameters,ES-CORRECTION);p32(parameters+8,es_extent);
    p64(parameters+0x10,SECONDARY);p32(parameters+0x18,u32(memory_table+0x30));
    p64(parameters+0x20,AUXILIARY);p16(parameters+0x28,0x4b0);
    p64(parameters+0x30,PI-CORRECTION);p16(parameters+0x38,(uint16_t)slots);
    p64(parameters+0x50,READ-CORRECTION);p64(parameters+0x58,WRITE-CORRECTION);
    p16(parameters+0x68,640);p16(parameters+0x6a,480);parameters[0x65]=3;
}
static void consume(void) {
    pthread_mutex_lock(&memory_mutex);
    uint8_t list[0x4b0*96];size_t count=0;uint32_t read=u32(read_bytes),write=u32(write_bytes+4);
    assert(nring_copy_read_list(pi_bytes,(size_t)slots*96,slots,write,read,list,sizeof list,&count)==0);
    for(size_t i=0;i<count;i++){
        const uint8_t *v=list+i*96;
        if(v[0]==4){struct nparamsets sets;
            assert(nparamsets_parse(v,96,NPARAMSETS_AVC1,CORRECTION,ES,es_bytes,es_extent,&sets,sizeof sets)==0);
            assert(sets.sps.nal_size==5 && sets.pps.nal_size==4);
            assert(!memcmp(sets.sps.nal,annex_config+4,5));assert(!memcmp(sets.pps.nal,annex_config+12,4));
            consumed_parameters++;
        }else if(v[0]==7){assert(!u32(v+0x10));consumed_eos++;}
        else {size_t nals=0;
            assert(nlength_validate(v,96,CORRECTION,ES,es_bytes,es_extent,NLENGTH_AVC1,&nals)==0);
            assert(nals==(consumed_normal?1u:3u));assert(v[0]==(consumed_normal?1:0));
            assert(u64(v+0x18)==(uint64_t)consumed_normal*3000 && u64(v+0x20)==u64(v+0x18));
            uint64_t address=u64(v+8)+CORRECTION;assert(address>last_es_address);last_es_address=address;
            const uint8_t *au=es_bytes+(size_t)(address-ES);size_t used=0;
            while(used<u32(v+0x10)){uint32_t len=(uint32_t)au[used]<<24|(uint32_t)au[used+1]<<16|(uint32_t)au[used+2]<<8|au[used+3];assert(len);used+=4+len;}
            assert(used==u32(v+0x10));consumed_normal++;
        }
    }
    struct nring_user user={7,read,3};struct nring_advance advance;
    assert(nring_advance_read(&user,1,7,count,count,slots,write,read,&advance)==0);
    atomic_thread_fence(memory_order_release);p32(read_bytes,advance.shared_read_index);
    pthread_mutex_unlock(&memory_mutex);
}
struct message {unsigned magic,size,source,owner;uint8_t data[48];};
static struct message *message(void *p) {
    struct message *m=(struct message *)((uint8_t *)p - offsetof(struct message,data));
    assert(m->magic==0x12345678);return m;
}
static int allocate(unsigned dst,void **out,unsigned n,unsigned mode) {
    assert(n==48 && mode==1);
    if(dst==FUNCTIONAL_MPR_CODEC_SOURCE && event_pointer_wrap){*out=(void *)(UINTPTR_MAX-8);return 0;}
    struct functional_mpr_codec_snapshot s;assert(functional_mpr_codec_snapshot(&s)==0);
    struct message *m=calloc(1,sizeof *m);assert(m);m->magic=0x12345678;
    m->size=(dst==FUNCTIONAL_MPR_CODEC_SOURCE && event_bad_size)?47:48;m->owner=dst;*out=m->data;
    atomic_fetch_add(&message_count,1);return dst==FUNCTIONAL_MPR_CODEC_SOURCE?event_allocate_error:0;
}
static int release(unsigned dst,void *p) {
    struct functional_mpr_codec_snapshot s;assert(functional_mpr_codec_snapshot(&s)==0);
    struct message *m=message(p);assert(m->owner==dst);
    if(dst==FUNCTIONAL_MPR_CODEC_DESTINATION && request_free_error)return request_free_error;
    m->magic=0;free(m);atomic_fetch_sub(&message_count,1);return 0;
}
static unsigned message_size(void *p) {return message(p)->size;}
static unsigned message_source(void *p) {return message(p)->source;}
static void set_source(void *p,unsigned src) {message(p)->source=event_bad_source?src^1u:src;}
static const char *receipt_field(const char *text,const char *key) {
    char field[80];assert(snprintf(field,sizeof field,"%s=",key)>0);
    const char *p=text;
    while((p=strstr(p,field))){if(p==text || p[-1]==' ')return p+strlen(field);p++;}
    assert(!"missing receipt field");return NULL;
}
static uint64_t receipt_number(const char *text,const char *key) {
    const char *p=receipt_field(text,key);char *end=NULL;uint64_t value=strtoull(p,&end,0);
    assert(end!=p && (!*end || *end==' '));return value;
}
static void receipt_hex(const char *text,const char *key,uint8_t *out,size_t bytes) {
    const char *p=receipt_field(text,key);assert(strlen(p)>=2*bytes);
    for(size_t i=0;i<bytes;i++){
        unsigned value=0;
        for(unsigned k=0;k<2;k++){char c=p[2*i+k];assert((c>='0' && c<='9') || (c>='a' && c<='f'));
            value=value*16+(unsigned)(c<='9'?c-'0':c-'a'+10);}
        out[i]=(uint8_t)value;
    }
    assert(!p[2*bytes] || p[2*bytes]==' ');
}
static void check_pi_receipt(const char *tag,const char *text) {
    uint64_t ticket=receipt_number(text,"ticket"),slot=receipt_number(text,"slot");
    assert(ticket && ticket<512 && slot<slots);
    assert(receipt_number(text,"epoch")==1 && receipt_number(text,"instance")==0x55);
    assert(receipt_number(text,"read_address")==READ && receipt_number(text,"info_address")==PI+slot*96);
    assert(receipt_number(text,"read_before")<slots && receipt_number(text,"read_after")<slots);
    assert(receipt_number(text,"read_seen")<slots && receipt_number(text,"observed_write")<slots);
    assert(receipt_number(text,"cycle")==ticket/slots);
    uint64_t call_seq=receipt_number(text,"call_request_seq");assert(call_seq && call_seq<128);
    assert(receipt_number(text,"call_native_fnv")==fnv(request_receipts[call_seq],48));
    assert(receipt_number(text,"model_token") && receipt_number(text,"result_bytes")>=96);
    assert(receipt_number(text,"pid")== (uint64_t)getpid());
    assert(receipt_number(text,"observer_tid")== (uint64_t)syscall(SYS_gettid));
    uint8_t info[96],actual[96];receipt_hex(text,"info_hex",info,sizeof info);
    assert(!fmpr_test_memory_read(PI+slot*96,actual,sizeof actual) && !memcmp(info,actual,sizeof info));
    uint64_t generation=receipt_number(text,"memory_generation");
    struct functional_mpr_memory_span memory;
    assert(!functional_mpr_memory_query((uintptr_t)PI+slot*96,96,&memory) && memory.generation==generation);
    if(info[0]!=7){
        size_t bytes=(size_t)receipt_number(text,"es_bytes"),offset=(size_t)receipt_number(text,"es_offset");
        assert(bytes==u32(info+0x10) && u64(info+8)+CORRECTION==ES+offset);
        assert(bytes<=es_extent-offset && receipt_number(text,"es_fnv")==fnv(es_bytes+offset,bytes));
    }else{
        assert(!receipt_number(text,"es_bytes") && !u32(info+0x10));
        assert(u16(request_receipts[call_seq]+2)==3 || u16(request_receipts[call_seq]+2)==4);
    }
    struct saved_publication *saved=&publication_receipts[ticket];
    if(!strcmp(tag,"FUNCTIONAL_MPR_PI_PUBLISH ")){
        assert(!saved->generation && receipt_number(text,"write_before")== (slot?slot-1:slots-1));
        assert(receipt_number(text,"write_after")==slot);
        assert(receipt_number(text,"slot_generation")==++slot_generations[slot]);
        memcpy(saved->info,info,sizeof info);saved->generation=generation;saved->slot=(unsigned)slot;
        saved->slot_generation=slot_generations[slot];pi_receipt_count++;
    }else{
        assert(ticket==++last_return_ticket && saved->generation==generation && !saved->returned);
        assert(saved->slot==slot && saved->slot_generation==receipt_number(text,"slot_generation"));
        assert(!memcmp(saved->info,info,sizeof info));saved->returned=1;return_receipt_count++;
        uint64_t before=receipt_number(text,"read_before"),after=receipt_number(text,"read_after");
        uint64_t returned=(after+slots-before)%slots;
        assert(returned && receipt_number(text,"outstanding_before")-receipt_number(text,"outstanding_after")==returned);
    }
}
static void logger(const char *tag,const char *text) {
    struct functional_mpr_codec_snapshot s;assert(functional_mpr_codec_snapshot(&s)==0);
    struct functional_mpr_memory_snapshot memory;assert(!functional_mpr_memory_snapshot(&memory));
    assert(tag && text && strlen(text)<1024 && strcmp(tag,"FUNCTIONAL_MPR_RECEIPT_ERROR "));
    if(!strcmp(tag,"FUNCTIONAL_MPR_REQUEST ")){
        uint64_t seq=receipt_number(text,"request_seq");uint8_t wire[48];assert(seq && seq<128);
        receipt_hex(text,"wire_hex",wire,sizeof wire);
        assert(receipt_number(text,"native_fnv")==fnv(wire,sizeof wire));
        assert(receipt_number(text,"command")==u16(wire+2));
        assert(receipt_number(text,"producer_tid")== (uint64_t)syscall(SYS_gettid));
        memcpy(request_receipts[seq],wire,sizeof wire);request_receipt_count++;
    }
    if(!strcmp(tag,"FUNCTIONAL_MPR_ES ")){
        uint8_t actual[256];size_t bytes=(size_t)receipt_number(text,"bytes");assert(bytes && bytes<=sizeof actual);
        uint64_t address=receipt_number(text,"address"),offset=receipt_number(text,"offset");
        assert(address==ES+offset && !fmpr_test_memory_read(address,actual,bytes));
        assert(receipt_number(text,"avcc_fnv")==fnv(actual,bytes));
        unsigned type=(unsigned)receipt_number(text,"info_type");uint64_t sequence=receipt_number(text,"packet_sequence");
        static const uint8_t config[]={0,0,0,5,0x67,0x42,0,0x1f,0xaa,0,0,0,4,0x68,0xce,6,0xe2};
        static const uint8_t first[]={0,0,0,5,0x67,0x42,0,0x1f,0xaa,0,0,0,4,0x68,0xce,6,0xe2,0,0,0,4,0x65,0x88,0x84,0x21};
        if(type==4){assert(bytes==sizeof config && !memcmp(actual,config,bytes));assert(receipt_number(text,"source_fnv")==fnv(annex_config,sizeof annex_config));}
        else if(!sequence){assert(bytes==sizeof first && !memcmp(actual,first,bytes));assert(receipt_number(text,"source_fnv")==fnv(first_packet,sizeof first_packet));}
        else {uint8_t expected[]={0,0,0,3,0x41,0x9a,(uint8_t)sequence};assert(bytes==sizeof expected && !memcmp(actual,expected,bytes));}
        assert(receipt_number(text,"model_token")==sequence+1);
        es_receipt_count++;
    }
    if(!strcmp(tag,"FUNCTIONAL_MPR_PI_PUBLISH ") || !strcmp(tag,"FUNCTIONAL_MPR_PI_RETURN "))check_pi_receipt(tag,text);
    if(!strcmp(tag,"FUNCTIONAL_MPR_PACKET ")){
        uint64_t ticket=receipt_number(text,"ticket");assert(ticket && ticket<512);
        assert(publication_receipts[ticket].generation==receipt_number(text,"memory_generation"));
        assert(receipt_number(text,"counter_after")==receipt_number(text,"counter_before")+1);
        assert(receipt_number(text,"counter_after")==receipt_number(text,"native_pts")/3000+1);
        assert(receipt_number(text,"es_address")==ES+receipt_number(text,"es_offset"));packet_receipt_count++;
    }
    int received=!strcmp(tag,"FUNCTIONAL_MPR_EVENT_RECEIVED "),freed=!strcmp(tag,"FUNCTIONAL_MPR_EVENT_FREE ");
    if(received || freed){
        uint64_t seq,hash;unsigned cmd,src,dst,observed,state,pending,owned;int rc;
        assert(sscanf(text,"seq=%" SCNu64 " command=%u wire_fnv=%" SCNx64 " src=%x dst=%x received=%u rc=%d state=%u pending=%u owned=%u",
            &seq,&cmd,&hash,&src,&dst,&observed,&rc,&state,&pending,&owned)==10);
        assert(seq && hash && src==FUNCTIONAL_MPR_CODEC_DESTINATION && dst==FUNCTIONAL_MPR_CODEC_SOURCE && rc==0);
        assert(state<=FMPR_FAULT && pending<=1 && owned<=REPLIES);
        uint8_t wire[48],request_wire[48];receipt_hex(text,"wire_hex",wire,sizeof wire);
        receipt_hex(text,"request_hex",request_wire,sizeof request_wire);
        uint64_t request_seq=receipt_number(text,"request_seq");assert(request_seq && request_seq<128);
        assert(!memcmp(request_wire,request_receipts[request_seq],sizeof request_wire));
        assert(fnv(wire,sizeof wire)==hash && receipt_number(text,"native_fnv")==fnv(request_wire,sizeof request_wire));
        assert(receipt_number(text,"instance")==0x55 && receipt_number(text,"epoch")==1);
        assert((int64_t)strtoll(receipt_field(text,"operation_error"),NULL,0)==(int32_t)u32(wire+0x14));
        assert(receipt_number(text,"observer_tid")== (uint64_t)syscall(SYS_gettid));
        if(observed)assert(receipt_number(text,"receiver_pid")== (uint64_t)getpid() && receipt_number(text,"receiver_tid"));
        else assert(!receipt_number(text,"receiver_tid"));
        pthread_mutex_lock(&event_mutex);
        if(received){assert(observed==1);received_logs++;if(cmd==4)close_received_sequence=seq;}
        if(freed){free_logs++;if(cmd==4 && observed)close_freed_sequence=seq;}
        pthread_mutex_unlock(&event_mutex);
    }
}
static void *request(unsigned cmd) {
    void *p;assert(allocate(FUNCTIONAL_MPR_CODEC_DESTINATION,&p,48,1)==0);
    message(p)->source=FUNCTIONAL_MPR_CODEC_SOURCE;uint8_t *w=p;
    p16(w+2,(uint16_t)cmd);p64(w+8,FIXED);p64(w+0x28,FIXED);
    p32(w+0x10,cmd==0?0x98:cmd==1?0x80:cmd==2?4:cmd==3?0x10:0);
    w[0x18]=0x20;w[0x1c]=0x41;p32(w+0x24,0x210);return p;
}
static void submit(unsigned cmd) {
    void *p=request(cmd);int rc=123;
    assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==0);
}
static int send_message(unsigned dst,void *p) {
    assert(dst==FUNCTIONAL_MPR_CODEC_SOURCE);
    assert(message_source(p)==FUNCTIONAL_MPR_CODEC_DESTINATION && message_size(p)==48);
    if(event_send_error)return event_send_error;
    const uint8_t *w=p;assert(u32(w+0x24)==0x4e0);
    unsigned cmd=(u16(w+2)-1u)/2u;assert(cmd==0 || cmd==1 || cmd==3 || cmd==4 || cmd==5);
    int error=(int32_t)u32(w+0x14);
    if(cmd==4 && defer_close_reply){deferred_close_reply=p;atomic_store(&close_reply_queued,1);return 0;}
    struct functional_mpr_codec_snapshot s;assert(functional_mpr_codec_snapshot(&s)==0);
    if(cmd==1 && !error){
        assert(s.backend_frames==1 && s.frames_published==1 && s.pi_published==2 && atomic_load(&model_frames)==1);
        pthread_mutex_lock(&memory_mutex);assert(u32(write_bytes)==1);pthread_mutex_unlock(&memory_mutex);
    }
    if(corrupt_reply){
        uint8_t *v=p;v[0x14]^=0x40;
        assert(functional_mpr_codec_observe_received(dst,p,&test_io)==-EBADMSG);
        int rc=0;assert(functional_mpr_codec_release_if_owned(dst,p,&test_io,&rc)==1 && rc==-EBADMSG);
        v[0x14]^=0x40;corrupt_reply=0;
    }
    assert(functional_mpr_codec_observe_received(dst,p,&test_io)==1);
    assert(functional_mpr_codec_observe_received(dst,p,&test_io)==1);
    if(auto_consume && cmd!=0)consume();
    int rc=123;assert(functional_mpr_codec_release_if_owned(dst,p,&test_io,&rc)==1 && rc==0);
    pthread_mutex_lock(&event_mutex);assert(events<32);event_commands[events]=cmd;event_errors[events]=error;events++;
    pthread_cond_broadcast(&event_condition);pthread_mutex_unlock(&event_mutex);
    if(early_reply && !error){if(cmd==1)submit(3);if(cmd==3)submit(4);}
    return 0;
}
static const struct full_imaging_io test_io={allocate,release,set_source,send_message,message_size,message_source,logger};

static void output_state(uint8_t *out) {
    memset(out,0,128);p32(out,FCAM_ABI_VERSION);p32(out+4,FCAM_CAPABILITIES);
    p32(out+8,640);p32(out+12,480);p32(out+16,30);p32(out+20,90);p32(out+24,400);p32(out+28,100);
    p64(out+32,10000);p64(out+40,2000000);p64(out+48,0x55);p64(out+56,1);p32(out+108,model_stream);
}
int fcam_bridge_call(const struct fcam_native_origin *origin,uint32_t op,const void *input,size_t n,
                     void *output,size_t capacity,struct fcam_bridge_result *result) {
    struct functional_mpr_codec_snapshot snapshot;assert(functional_mpr_codec_snapshot(&snapshot)==0);
    assert(origin && origin->source==FUNCTIONAL_MPR_CODEC_SOURCE && origin->destination==FUNCTIONAL_MPR_CODEC_DESTINATION);
    assert(origin->bytes==48 && origin->wire_fnv1a64);atomic_fetch_add(&model_calls,1);
    if(op==FCAM_OP_VIDEO_FRAME && atomic_load(&gate_frame) && model_seq){
        atomic_store(&frame_entered,1);for(unsigned i=0;!atomic_load(&allow_frame);i++){assert(i<5000);ms(1);}
    }
    if(op==FCAM_OP_VIDEO_FRAME && atomic_load(&backend_error))return atomic_load(&backend_error);
    uint8_t *out=output;struct fcam_bridge_result r={0,0,0x55,0};
    if(op==FCAM_OP_INIT || op==FCAM_OP_STATE || op==FCAM_OP_CANCEL || op==FCAM_OP_VIDEO_BEGIN){
        assert(capacity>=128);
        if(op==FCAM_OP_VIDEO_BEGIN){assert(input && n==48 && u32(input)==640 && u32((const uint8_t *)input+4)==480 && u32((const uint8_t *)input+8)==30);model_stream=1;model_seq=0;}
        else {assert(!input && !n);if(op==FCAM_OP_CANCEL){model_stream=0;atomic_fetch_add(&model_cancel,1);}}
        output_state(out);r.used=r.required=128;
    }else if(op==FCAM_OP_VIDEO_FRAME || op==FCAM_OP_VIDEO_END){
        assert(model_stream==1 && !input && !n && capacity>=256);memset(out,0,96);
        p32(out,640);p32(out+4,480);p64(out+8,model_seq);p64(out+16,model_seq);p32(out+32,1);p32(out+36,30);p32(out+68,FCAM_CODEC_AVC1);
        if(op==FCAM_OP_VIDEO_END){model_stream=2;p32(out+44,FCAM_PACKET_EOS);p64(out+56,model_gen);r.used=r.required=96;r.result_token=model_seq+1;atomic_fetch_add(&model_end,1);}
        else {
            size_t encoded=model_seq?6:sizeof first_packet;p64(out+24,1);p32(out+40,model_seq?0:1);p64(out+48,encoded);
            p64(out+56,++model_gen);p32(out+64,sizeof annex_config);memcpy(out+96,annex_config,sizeof annex_config);
            uint8_t *packet=out+96+sizeof annex_config;
            if(!model_seq)memcpy(packet,first_packet,sizeof first_packet);else {static const uint8_t prefix_bytes[]={0,0,1,0x41,0x9a};memcpy(packet,prefix_bytes,sizeof prefix_bytes);packet[5]=(uint8_t)model_seq;}
            r.used=r.required=96+sizeof annex_config+encoded;r.result_token=model_seq+1;model_seq++;atomic_fetch_add(&model_frames,1);
            if(atomic_load(&wrong_instance))r.model_instance++;
            if(atomic_load(&short_packet))r.used=95;
        }
    }else assert(!"unexpected bridge operation");
    *result=r;return 0;
}
static void wait_events(unsigned target) {
    struct timespec limit=after_ms(5000);
    pthread_mutex_lock(&event_mutex);
    while(events<target){int rc=pthread_cond_timedwait(&event_condition,&event_mutex,&limit);assert(rc==0);}
    pthread_mutex_unlock(&event_mutex);
}
static void wait_idle(void) {
    for(unsigned i=0;i<5000;i++){
        pthread_mutex_lock(&mutex);int idle=!working && !reserved && !queued;pthread_mutex_unlock(&mutex);
        if(idle)return;
        ms(1);
    }
    assert(!"worker did not become idle");
}
static struct functional_mpr_codec_snapshot snapshot(void) {
    struct functional_mpr_codec_snapshot s;assert(functional_mpr_codec_snapshot(&s)==0);return s;
}
static void wait_frames(unsigned frames) {
    for(unsigned i=0;i<5000;i++){consume();if(snapshot().backend_frames>=frames)return;ms(1);}
    assert(!"frame clock did not produce requested frames");
}
static void wait_failure(int error) {
    for(unsigned i=0;i<5000;i++){struct functional_mpr_codec_snapshot s=snapshot();if(s.state==FMPR_FAULT && s.last_error==error)return;ms(1);}
    assert(!"expected error was not preserved");
}
static void prepare(void) {
    assert(functional_mpr_codec_owner_init()==0);init_memory();
    assert(functional_mpr_codec_bind(LIB,FUNCTIONAL_MPR_CODEC_LIBRARY_SHA256)==0);
}
static void open_codec(void) {
    submit(0);wait_events(1);assert(!event_errors[0]);wait_idle();assert(snapshot().state==FMPR_OPEN);
    struct functional_mpr_memory_snapshot memory;assert(!functional_mpr_memory_snapshot(&memory));
    assert(snapshot().memory_generation==memory.active_generation && snapshot().owned_memory_leases==memory.leases);
    assert(memory.leases==6 && live.pins[PIN_CONTROL].address==WRITE && live.write==WRITE+4);
}
static void stop_close(void) {
    consume();unsigned before=events;submit(3);
    for(unsigned i=0;i<5000;i++){consume();pthread_mutex_lock(&event_mutex);int ready=events>before;pthread_mutex_unlock(&event_mutex);if(ready)break;ms(1);}
    wait_events(before+1);assert(!event_errors[before]);wait_idle();assert(snapshot().state==FMPR_DRAINED);
    assert(functional_mpr_codec_shutdown()==-EBUSY);
    unsigned writes=atomic_load(&memory_writes),frames=atomic_load(&model_frames);ms(50);
    assert(atomic_load(&memory_writes)==writes && atomic_load(&model_frames)==frames);
    submit(4);wait_events(before+2);assert(!event_errors[before+1]);wait_idle();assert(snapshot().state==FMPR_CLOSED);
    assert(close_received_sequence && close_freed_sequence==close_received_sequence);
    writes=atomic_load(&memory_writes);ms(50);assert(atomic_load(&memory_writes)==writes);
}
static void finish_memory(void) {
    struct functional_mpr_memory_snapshot s;assert(!functional_mpr_memory_snapshot(&s));assert(!s.leases);
    if(s.active_group)assert(fmpr_memory_free_mask(3,7));
    assert(!functional_mpr_memory_shutdown());assert(!fixture_root);
}
static void finish(void) {
    wait_idle();assert(functional_mpr_codec_shutdown()==0);
    struct functional_mpr_codec_snapshot s=snapshot();assert(!s.worker_live && !s.owned_memory_leases && !s.capture_verified && !s.physical_asic_verified && !s.original_cp_verified);
    assert(atomic_load(&message_count)==0);finish_memory();
}
static void lifecycle(void) {
    prepare();open_codec();submit(1);wait_events(2);assert(!event_errors[1]);
    wait_frames(4);stop_close();struct functional_mpr_codec_snapshot s=snapshot();
    assert(s.backend_frames>=4 && s.frames_published==s.backend_frames && s.pi_published==s.backend_frames+2 && s.original_slots_returned>=s.backend_frames+1);
    assert(s.events_sent==4 && s.events_received==4 && received_logs==4 && free_logs==4 && consumed_parameters==1 && consumed_eos==1);
    assert(atomic_load(&model_end)==1 && atomic_load(&model_cancel)==1);finish();
}
static void validation(void) {
    prepare();int rc=912;void *p=request(0);
    assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,0,&rc)==0 && rc==912);
    assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,2,&rc)==0 && rc==912);
    assert(functional_mpr_codec_dispatch(23,p,&test_io,1,&rc)==0);
    message(p)->source=12;assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==0);message(p)->source=FUNCTIONAL_MPR_CODEC_SOURCE;
    message(p)->size=47;assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-EMSGSIZE);message(p)->size=48;
    p32((uint8_t *)p+0x24,0x1500);assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==0);
    p32((uint8_t *)p+0x24,0x1610);assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-ENOTSUP);
    p32((uint8_t *)p+0x24,0x210);((uint8_t *)p)[0x19]=0x20;assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-ENOTSUP);((uint8_t *)p)[0x19]=0;
    p64((uint8_t *)p+0x28,0xdead);assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-ENOENT);
    assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);
    p=request(2);assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-ENOTSUP);assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);
    assert(!atomic_load(&model_calls));finish();
}
static void backpressure(void) {
    slots=5;auto_consume=0;prepare();open_codec();submit(1);wait_events(2);
    for(unsigned i=0;!snapshot().backpressure;i++){assert(i<5000);ms(1);}
    assert(snapshot().backend_frames==1);ms(75);assert(snapshot().backend_frames==1);
    consume();wait_frames(4);stop_close();assert(snapshot().original_slots_returned>=5);finish();
}
static void wrap(void) {slots=5;prepare();open_codec();submit(1);wait_events(2);wait_frames(12);stop_close();assert(consumed_normal>=12 && snapshot().es_used<es_extent);finish();}
static void es_full(void) {
    es_extent=43;prepare();open_codec();submit(1);wait_events(2);assert(!event_errors[1]);
    wait_failure(-ENOSPC);wait_events(3);wait_idle();
    assert(event_commands[2]==5 && event_errors[2]==-ENOSPC);
    assert(snapshot().pi_published==2 && snapshot().backend_frames==2 && snapshot().es_used==42);
    consume();submit(4);wait_events(4);wait_idle();assert(event_errors[3]==-ESTALE);finish();
}
static void packet_failure(const char *kind) {
    prepare();open_codec();int expected;
    if(!strcmp(kind,"corruption")){atomic_store(&corrupt_es,1);expected=-EBADMSG;}
    else if(!strcmp(kind,"instance")){atomic_store(&wrong_instance,1);expected=-ESTALE;}
    else if(!strcmp(kind,"size")){atomic_store(&short_packet,1);expected=-EMSGSIZE;}
    else {atomic_store(&backend_error,-123);expected=-123;}
    submit(1);wait_events(2);wait_idle();assert(event_errors[1]==expected && snapshot().state==FMPR_FAULT && !snapshot().pi_published);
    atomic_store(&backend_error,0);submit(4);wait_events(3);wait_idle();finish();
}
static void stop_join(void) {
    prepare();open_codec();atomic_store(&gate_frame,1);submit(1);wait_events(2);
    for(unsigned i=0;!atomic_load(&frame_entered);i++){assert(i<5000);ms(1);}
    unsigned before=events;submit(3);ms(20);pthread_mutex_lock(&event_mutex);assert(events==before);pthread_mutex_unlock(&event_mutex);
    atomic_store(&allow_frame,1);wait_events(before+1);assert(!event_errors[before]);wait_idle();assert(snapshot().state==FMPR_DRAINED);
    submit(4);wait_events(before+2);wait_idle();unsigned writes=atomic_load(&memory_writes);ms(75);assert(writes==atomic_load(&memory_writes));finish();
}
static void early(void) {
    prepare();open_codec();early_reply=1;submit(1);wait_events(4);wait_idle();
    assert(event_commands[1]==1 && event_commands[2]==3 && event_commands[3]==4);
    assert(!event_errors[1] && !event_errors[2] && !event_errors[3]);assert(snapshot().accepted==4);finish();
}
static void fork_guard(void) {
    prepare();pthread_mutex_lock(&mutex);pid_t pid=fork();assert(pid>=0);
    if(!pid){struct functional_mpr_codec_snapshot s;int rc=1;
        if(functional_mpr_codec_owner_init()!=-ECHILD || functional_mpr_codec_snapshot(&s)!=-ECHILD ||
           functional_mpr_codec_shutdown()!=-ECHILD || functional_mpr_codec_bind(LIB,FUNCTIONAL_MPR_CODEC_LIBRARY_SHA256)!=-ECHILD)_exit(2);
        if(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,(void *)1,&test_io,1,&rc)!=1 || rc!=-ECHILD)_exit(3);
        _exit(0);
    }
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));pthread_mutex_unlock(&mutex);finish();
}
static void ownership(const char *mode) {
    prepare();
    if(!strcmp(mode,"free-error")){
        void *p=request(0);request_free_error=-77;int rc;
        assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-77);
        assert(!snapshot().accepted && !snapshot().owned_memory_leases && !atomic_load(&model_calls));request_free_error=0;assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);finish();return;
    }
    if(!strcmp(mode,"allocator-error"))event_allocate_error=-ENOMEM;
    if(!strcmp(mode,"quarantine")){
        event_pointer_wrap=1;submit(0);wait_failure(-EOVERFLOW);wait_idle();
        void *p=(void *)(UINTPTR_MAX-8);int rc;
        assert(functional_mpr_codec_observe_received(FUNCTIONAL_MPR_CODEC_SOURCE,p,&test_io)==-EOVERFLOW);
        assert(functional_mpr_codec_release_if_owned(FUNCTIONAL_MPR_CODEC_SOURCE,p,&test_io,&rc)==1 && rc==-EOVERFLOW);
        assert(functional_mpr_codec_shutdown()==-EBUSY);
        assert(snapshot().owned_replies==1 && snapshot().worker_live && !snapshot().owned_memory_leases && !atomic_load(&message_count));return;
    }
    if(!strcmp(mode,"reply-corrupt"))corrupt_reply=1;
    if(!strcmp(mode,"reply-size"))event_bad_size=1;
    if(!strcmp(mode,"reply-source"))event_bad_source=1;
    if(!strcmp(mode,"send-error"))event_send_error=-71;
    submit(0);
    if(!strcmp(mode,"reply-corrupt")){wait_events(1);wait_idle();assert(snapshot().failures>=2);}
    else {wait_failure(event_allocate_error?-ENOMEM:event_bad_size?-EMSGSIZE:event_bad_source?-EBADMSG:-71);wait_idle();assert(!events && !snapshot().events_received);}
    event_allocate_error=event_bad_size=event_bad_source=event_send_error=0;
    submit(4);wait_events(!strcmp(mode,"reply-corrupt")?2:1);wait_idle();finish();
}
static void bad_binding(void) {
    prepare();assert(functional_mpr_codec_bind(LIB,"bad")==-EINVAL);
    library_bytes[0x283e74]^=1;assert(functional_mpr_codec_bind(LIB,FUNCTIONAL_MPR_CODEC_LIBRARY_SHA256)==-ELIBBAD);library_bytes[0x283e74]^=1;
    void *p=request(0);int rc;parameters[0x65]=1;
    assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-ENOTSUP);parameters[0x65]=3;
    p64(library_bytes+0x3b7e68,READ+4);
    assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-ESTALE);
    assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);finish();
}
static void reject_open(void *p,int expected) {
    int rc=123;assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==expected);
    assert(!snapshot().accepted && !snapshot().owned_memory_leases && !atomic_load(&model_calls));
    struct functional_mpr_memory_snapshot memory;assert(!functional_mpr_memory_snapshot(&memory) && !memory.leases);
}
static void secondary_buffers(void) {
    slots=0x4b0;es_extent=FUNCTIONAL_MPR_MEMORY_MAIN_BYTES;prepare();
    assert(u64(parameters+0x10)==SECONDARY && u32(parameters+0x18)==(8u<<20));
    uint64_t secondary_hash=fnv((void *)(uintptr_t)SECONDARY,8u<<20);
    open_codec();assert(live.pins[PIN_SECONDARY].bytes==(8u<<20) && live.pins[PIN_AUXILIARY].bytes==1);
    submit(1);wait_events(2);stop_close();
    assert(secondary_hash==fnv((void *)(uintptr_t)SECONDARY,8u<<20));finish();
}
static void secondary_validation(void) {
    prepare();void *p=request(0);
    parameters[0x88]=0x80;reject_open(p,-ENOTSUP);parameters[0x88]=0;
    ((uint8_t *)p)[0x19]=0x20;reject_open(p,-ENOTSUP);((uint8_t *)p)[0x19]=0;
    ((uint8_t *)p)[0x1e]=0x41;reject_open(p,-ENOTSUP);((uint8_t *)p)[0x1e]=0;
    p64(parameters+0x10,SECONDARY+(8u<<20)-4);p32(parameters+0x18,8);reject_open(p,-ENOENT);
    p32(parameters+0x18,8u<<20);p64(parameters+0x10,UINT64_MAX-4);reject_open(p,-ERANGE);
    p64(parameters+0x10,0);reject_open(p,-EINVAL);p64(parameters+0x10,SECONDARY);
    p64((uint8_t *)p+8,FIXED+1);reject_open(p,-ESTALE);p64((uint8_t *)p+8,FIXED);
    /* The auxiliary u16 is not a byte extent. */
    p16(parameters+0x28,UINT16_MAX);
    assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);
    open_codec();submit(4);wait_events(2);wait_idle();finish();
}
static void unowned_buffer(void) {
    prepare();uint8_t foreign[8192]={0};void *p=request(0);
    p64(library_bytes+0x3b7d68,(uintptr_t)foreign);p64(parameters,(uintptr_t)foreign);
    reject_open(p,-ENOENT);assert(!memcmp(foreign,(uint8_t[8192]){0},sizeof foreign));
    assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);finish();
}
static void mixed_generation(void) {
    prepare();uint64_t old_info=PI;
    assert(fmpr_memory_free_mask(3,7));assert(fmpr_memory_alloc(3,&memory_group,memory_table));register_table(memory_table);
    ES=u64(memory_table);SECONDARY=u64(memory_table+0x20);AUXILIARY=u64(memory_table+0x2c0);
    p64(library_bytes+0x3b7d68,ES);p64(parameters,ES);
    p64(parameters+0x10,SECONDARY);p64(parameters+0x20,AUXILIARY);
    void *p=request(0);reject_open(p,-ENOENT);
    assert(PI==old_info && u64(library_bytes+0x3b7f70)==old_info);
    assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);finish();
}
static void retirement_write(unsigned kind,unsigned mask) {
    auto_consume=0;prepare();open_codec();atomic_store(&gate_write,(int)kind);submit(1);
    for(unsigned i=0;!atomic_load(&write_entered);i++){assert(i<5000);ms(1);}
    uint8_t before[96];uint64_t address=kind==1?ES:kind==2?PI+96:kind==3?WRITE+4:WRITE;
    size_t n=kind<=2?96:4;memcpy(before,(void *)(uintptr_t)address,n);
    unsigned writes=atomic_load(&memory_writes);
    assert(functional_mpr_codec_shutdown()==-EBUSY);assert(fmpr_memory_free_mask(3,mask));
    atomic_store(&allow_write,1);wait_events(2);wait_idle();
    assert(event_errors[1]==-ESTALE && snapshot().state==FMPR_FAULT);
    assert(!memcmp(before,(void *)(uintptr_t)address,n) && atomic_load(&memory_writes)==writes);
    assert(snapshot().backend_frames==1 && snapshot().frames_published==(kind==4?1u:0u));
    assert(snapshot().pi_published==(kind==4?2u:0u) && !snapshot().owned_memory_leases);
    submit(4);wait_events(3);wait_idle();assert(event_errors[2]==-ESTALE && snapshot().state==FMPR_CLOSED);finish();
}
static void retirement_model(void) {
    auto_consume=0;prepare();open_codec();atomic_store(&gate_frame,1);submit(1);wait_events(2);
    for(unsigned i=0;!atomic_load(&frame_entered);i++){assert(i<5000);ms(1);}
    unsigned writes=atomic_load(&memory_writes);uint32_t cursor=u32(write_bytes+4),frames=u32(write_bytes);
    assert(fmpr_memory_free_mask(3,7));atomic_store(&allow_frame,1);
    wait_events(3);wait_idle();assert(event_commands[2]==5 && event_errors[2]==-ESTALE);
    assert(snapshot().backend_frames==2 && snapshot().frames_published==1 && snapshot().pi_published==2);
    assert(writes==atomic_load(&memory_writes) && u32(write_bytes+4)==cursor && u32(write_bytes)==frames);
    submit(4);wait_events(4);wait_idle();assert(snapshot().state==FMPR_CLOSED);finish();
}
static void release_failure(int fixed) {
    prepare();
    if(fixed){
        void *p=request(0);atomic_store(&memory_release_error,-91);int rc;
        assert(functional_mpr_codec_dispatch(FUNCTIONAL_MPR_CODEC_DESTINATION,p,&test_io,1,&rc)==1 && rc==-91);
        assert(!snapshot().accepted && snapshot().owned_memory_leases==1 && !atomic_load(&model_calls));
        atomic_store(&memory_release_error,0);assert(release(FUNCTIONAL_MPR_CODEC_DESTINATION,p)==0);finish();return;
    }
    open_codec();atomic_store(&memory_release_error,-91);submit(4);wait_events(2);wait_idle();
    assert(event_errors[1]==-91 && snapshot().state==FMPR_CLOSED && snapshot().owned_memory_leases==6);
    assert(snapshot().last_memory_release_error==-91);
    assert(functional_mpr_codec_shutdown()==-91 && snapshot().owned_memory_leases==6);
    assert(fmpr_memory_free_mask(3,7));assert(functional_mpr_memory_shutdown()==-EBUSY);
    atomic_store(&memory_release_error,0);finish();
}
static void shutdown_active(void) {
    prepare();open_codec();assert(functional_mpr_codec_shutdown()==-EBUSY);
    assert(!atomic_load(&model_cancel) && snapshot().worker_live);
    submit(1);wait_events(2);assert(functional_mpr_codec_shutdown()==-EBUSY);
    assert(!atomic_load(&model_end) && !atomic_load(&model_cancel));
    wait_frames(3);stop_close();finish();
}
static void deferred_event(void) {
    prepare();open_codec();submit(1);wait_events(2);consume();submit(3);wait_events(3);wait_idle();
    defer_close_reply=1;submit(4);
    for(unsigned i=0;!atomic_load(&close_reply_queued);i++){assert(i<5000);ms(1);}wait_idle();
    struct functional_mpr_codec_snapshot s=snapshot();
    assert(s.state==FMPR_CLOSED && s.events_sent==4 && s.events_received==3 && s.owned_replies==1);
    assert(!close_received_sequence && !close_freed_sequence && received_logs==3 && free_logs==3);
    assert(functional_mpr_codec_shutdown()==-EBUSY);
    assert(functional_mpr_codec_observe_received(FUNCTIONAL_MPR_CODEC_SOURCE,deferred_close_reply,&test_io)==1);
    assert(close_received_sequence && !close_freed_sequence);int rc=123;
    assert(functional_mpr_codec_release_if_owned(FUNCTIONAL_MPR_CODEC_SOURCE,deferred_close_reply,&test_io,&rc)==1 && !rc);
    deferred_close_reply=NULL;assert(close_freed_sequence==close_received_sequence && !snapshot().owned_replies);finish();
}
static void receipt_cases(const char *kind) {
    if(!strcmp(kind,"receipt-wire")){lifecycle();assert(request_receipt_count==4 && received_logs==4 && free_logs==4);return;}
    if(!strcmp(kind,"receipt-wrap")){wrap();assert(slot_generations[1]>=3 && last_return_ticket==pi_receipt_count);return;}
    if(!strcmp(kind,"receipt-malformed-read")){
        auto_consume=0;prepare();open_codec();atomic_store(&gate_frame,1);submit(1);wait_events(2);
        for(unsigned i=0;!atomic_load(&frame_entered);i++){assert(i<5000);ms(1);}
        pthread_mutex_lock(&memory_mutex);p32(read_bytes,slots);pthread_mutex_unlock(&memory_mutex);
        unsigned returned=return_receipt_count;atomic_store(&allow_frame,1);
        wait_events(3);wait_idle();assert(event_errors[2]==-ESTALE && !snapshot().original_slots_returned);
        assert(return_receipt_count==returned && snapshot().frames_published==1);
        submit(4);wait_events(4);wait_idle();assert(event_errors[3]==-ESTALE);finish();return;
    }
    prepare();open_codec();submit(1);wait_events(2);wait_frames(4);stop_close();
    struct functional_mpr_codec_snapshot s=snapshot();
    assert(packet_receipt_count==s.frames_published && es_receipt_count==packet_receipt_count+1);
    assert(pi_receipt_count==packet_receipt_count+2 && return_receipt_count==pi_receipt_count);
    assert(publication_receipts[pi_receipt_count].info[0]==7);
    assert(!u32(publication_receipts[pi_receipt_count].info+0x10));
    assert(publication_receipts[1].info[0]==4 && publication_receipts[2].info[0]==0);
    if(!strcmp(kind,"receipt-stop"))assert(atomic_load(&model_end)==1 && atomic_load(&model_cancel)==1);
    finish();
}
int main(int argc,char **argv) {
    assert(argc==2);
    if(!strncmp(argv[1],"receipt-",8))receipt_cases(argv[1]);
    else if(!strcmp(argv[1],"lifecycle"))lifecycle();
    else if(!strcmp(argv[1],"validation"))validation();
    else if(!strcmp(argv[1],"backpressure"))backpressure();
    else if(!strcmp(argv[1],"wrap"))wrap();
    else if(!strcmp(argv[1],"es-full"))es_full();
    else if(!strcmp(argv[1],"stop-join"))stop_join();
    else if(!strcmp(argv[1],"early-reply"))early();
    else if(!strcmp(argv[1],"fork"))fork_guard();
    else if(!strcmp(argv[1],"binding"))bad_binding();
    else if(!strcmp(argv[1],"original-secondary"))secondary_buffers();
    else if(!strcmp(argv[1],"secondary-validation"))secondary_validation();
    else if(!strcmp(argv[1],"unowned-buffer"))unowned_buffer();
    else if(!strcmp(argv[1],"mixed-generation"))mixed_generation();
    else if(!strcmp(argv[1],"retire-es"))retirement_write(1,1);
    else if(!strcmp(argv[1],"retire-info"))retirement_write(2,4);
    else if(!strcmp(argv[1],"retire-cursor"))retirement_write(3,7);
    else if(!strcmp(argv[1],"retire-counter"))retirement_write(4,7);
    else if(!strcmp(argv[1],"retire-model"))retirement_model();
    else if(!strcmp(argv[1],"memory-release-error"))release_failure(0);
    else if(!strcmp(argv[1],"fixed-release-error"))release_failure(1);
    else if(!strcmp(argv[1],"shutdown-active"))shutdown_active();
    else if(!strcmp(argv[1],"deferred-close-event"))deferred_event();
    else if(!strcmp(argv[1],"corruption") || !strcmp(argv[1],"instance") || !strcmp(argv[1],"size") || !strcmp(argv[1],"backend-error"))packet_failure(argv[1]);
    else ownership(argv[1]);
    return 0;
}
