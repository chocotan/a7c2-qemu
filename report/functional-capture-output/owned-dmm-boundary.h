/* Explicit component OSAL fixture; never a physical/native DMM implementation. */
struct owned_span { uint32_t handle; unsigned char *cpu; size_t capacity; uint64_t alias; unsigned refs; };
static struct owned_span owned_spans[4];
static uint64_t actual_map_base,header_alias,thumb_alias;
static unsigned native_shares,native_queries,native_frees,native_packet_releases;
struct owned_packet { uint32_t source; unsigned queued; unsigned char bytes[40]; };
static struct owned_packet *only_packet;
#define DMM_SID UINT32_C(0x0061003c)
#define REQUEST_SOURCE UINT32_C(0x80c70073)
static uint32_t read32(const void *p) { uint32_t value;memcpy(&value,p,4);return value; }
static uint16_t read16(const void *p) { uint16_t value;memcpy(&value,p,2);return value; }
static void call_from(uintptr_t caller,uintptr_t first,uintptr_t second) {
    assert(mpr_base && (caller==mpr_base+first || caller==mpr_base+second));
}
int osal_dynamic_id(uint32_t kind,uint32_t value,uintptr_t out_or_id) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    if(kind==0x2a) {
        call_from(caller,0x2b1dc4,0x2b22a8);assert(value==0xc7 && out_or_id);
        put32((void *)out_or_id,REQUEST_SOURCE);return 0;
    }
    assert(kind==0x4a && value==0 && out_or_id==REQUEST_SOURCE);
    call_from(caller,0x2b21b8,0x2b24d0);return 0;
}
int osal_valloc_msg_wait(uint32_t destination,void **out,uint32_t bytes,uint32_t wait) {
    call_from((uintptr_t)__builtin_return_address(0),0x2b1e3c,0x2b2314);
    assert(destination==DMM_SID && out && bytes==40 && wait==1 && !only_packet);
    only_packet=calloc(1,sizeof *only_packet);assert(only_packet);*out=only_packet->bytes;return 0;
}
int osal_set_msg_src(void *body,uint32_t source) {
    uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    if(!(caller==mpr_base+0x2b1ee0 || caller==mpr_base+0x2b1f8c || caller==mpr_base+0x2b2360))
        fprintf(stderr,"DMM_CALLER_REFUSED caller=%#lx base=%#lx offset=%#lx source=%#x packet_owned=%u\n",(unsigned long)caller,(unsigned long)mpr_base,(unsigned long)(caller-mpr_base),source,(unsigned)(only_packet && body==only_packet->bytes));
    assert(caller==mpr_base+0x2b1ee0 || caller==mpr_base+0x2b1f8c || caller==mpr_base+0x2b2360);
    assert(only_packet && body==only_packet->bytes && source==REQUEST_SOURCE);
    only_packet->source=source;return 0;
}
int osal_snd_msg(uint32_t destination,void *body) {
    call_from((uintptr_t)__builtin_return_address(0),0x2b1f08,0x2b2388);
    assert(only_packet && body==only_packet->bytes && !only_packet->queued);
    unsigned char q[40];memcpy(q,body,40);uint32_t handle=read32(q+8);
    unsigned index=0;while(index<4 && owned_spans[index].handle!=handle)++index;
    assert(index<4 && owned_spans[index].refs && destination==DMM_SID);
    assert(only_packet->source==REQUEST_SOURCE);
    struct owned_span *span=&owned_spans[index];uint16_t op=read16(q),option=read16(q+22);
    assert((op==0x21 && option==1 && read32(q+4)==1) ||
           (op==0x2a && option==0) || (op==0x23 && option==2));
    assert(capture_output_memory_reply(output_owner,q,actual_map_base,body)==0);
    if(op==0x21){++span->refs;++native_shares;}
    if(op==0x2a)++native_queries;
    if(op==0x23){assert(span->refs>1);--span->refs;++native_frees;}
    only_packet->queued=1;return 0;
}
int osal_rcv_msg_tmo(uint32_t source,void **out,int32_t timeout) {
    call_from((uintptr_t)__builtin_return_address(0),0x2b1fe8,0x2b23c0);
    assert(source==REQUEST_SOURCE && timeout==-1 && only_packet && only_packet->queued && out);
    *out=only_packet->bytes;return 0;
}
int osal_free_msg(uint32_t source,void *body) {
    call_from((uintptr_t)__builtin_return_address(0),0x2b20fc,0x2b2498);
    assert(source==REQUEST_SOURCE && only_packet && only_packet->queued && body==only_packet->bytes);
    free(only_packet);only_packet=NULL;++native_packet_releases;return 0;
}
static void register_owned_span(unsigned index,uint32_t handle,unsigned char *cpu,size_t capacity) {
    assert(index<4 && cpu && capacity && capacity<=UINT32_MAX && (uintptr_t)cpu>=actual_map_base);
    const uint64_t alias=(uintptr_t)cpu-actual_map_base;
    assert(alias && alias<=UINT64_MAX-capacity && !(handle&0x8000));
    owned_spans[index]=(struct owned_span){handle,cpu,capacity,alias,1};
}
static void actual_original_area_from_wire(const unsigned char area[16],void *destination) {
    unsigned index=0;while(index<4 && owned_spans[index].handle!=read32(area))++index;
    assert(index<4 && read32(area+12)==1);
    struct owned_span *span=&owned_spans[index];
    uint32_t offset=read32(area+4),bytes=read32(area+8);
    assert(bytes && offset<span->capacity && bytes<=span->capacity-offset);
    unsigned char unit[168]={0};uintptr_t address=mpr_base+0x2b2258;
    uintptr_t (*share)(uint32_t,uint32_t,void *,uint32_t,void *)=NULL;
    memcpy(&share,&address,sizeof address);assert(share(read32(area+12),span->handle,unit,1,NULL));
    assert(span->refs==2 && read16(unit)==0x8021 && read32(unit+12)==span->handle);
    address=mpr_base+0xe03a0;void (*map)(const void *,void *,uint32_t,void *)=NULL;
    memcpy(&map,&address,sizeof address);map(area,destination,1,NULL);
    assert(!memcmp(destination,area,16));
    assert(get64((unsigned char *)destination+0x10)==(uintptr_t)span->cpu+offset);
    assert(get64((unsigned char *)destination+0x18)==span->alias+offset);
}
static void actual_original_area(unsigned index,void *destination,size_t bytes) {
    assert(index<4 && bytes && bytes<=owned_spans[index].capacity);
    unsigned char area[16]={0};put32(area,owned_spans[index].handle);put32(area+8,(uint32_t)bytes);put32(area+12,1);
    actual_original_area_from_wire(area,destination);
}
static void actual_original_release_spans(void) {
    uintptr_t address=mpr_base+0x2b24f0;uint32_t (*close_and_free)(uint32_t)=NULL;
    memcpy(&close_and_free,&address,sizeof address);
    for(unsigned index=0;index<4;++index) {
        assert(owned_spans[index].refs==2);assert(close_and_free(owned_spans[index].handle)==1);
        assert(owned_spans[index].refs==1);
    }
    struct capture_output_info state;assert(capture_output_memory_info(output_owner,&state)==0 && !state.native_references);
    assert(!only_packet && native_shares==4 && native_queries==4 && native_frees==4 && native_packet_releases==12);
}
