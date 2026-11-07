/* SPDX-License-Identifier: MIT */
/* Host ownership/transport fixture; no original AP, native codec, JPEG decode
 * or Fsys runs here. Existing memory provider exercises actual mmap/leases. */
#include "functional-capture.c"
#include <assert.h>
#include <sys/wait.h>
struct packet {unsigned size,source;uint8_t data[1280];};
static unsigned allocations,releases,sends,rpcs,reservations,unlocks;
static int allocate_error,send_error,release_error,reserve_error,predecessor=1,inline_receive,imaging_live,dmm_inline;
static struct packet *sent_packets[8];
static uint8_t saved_config_body[56];
static struct packet *packet(void *p){return (struct packet *)((uint8_t *)p-2*sizeof(unsigned));}
static struct packet *make_packet(unsigned bytes,unsigned source){struct packet *p=calloc(1,sizeof *p);assert(p);p->size=bytes;p->source=source;return p;}
static int alloc(unsigned destination,void **out,unsigned bytes,unsigned mode){assert(destination && out && bytes<=1280 && mode==1);++allocations;if(allocate_error)return allocate_error;*out=make_packet(bytes,0)->data;return 0;}
static int release(unsigned destination,void *p){assert(destination && p);++releases;if(release_error)return release_error;free(packet(p));return 0;}
static void set_source(void *p,unsigned source){packet(p)->source=source;}
static unsigned size(void *p){return packet(p)->size;}
static unsigned source(void *p){return packet(p)->source;}
static int send_packet(unsigned destination,void *p){
    ++sends;if(send_error)return send_error;
    if(destination==0x80c70047 || destination==0x8055001f){
        if(destination==0x8055001f)functional_capture_observe_received(destination,p);
        assert(!release(destination,p));functional_capture_observe_freed(destination,p,0,original.base+0x283e78);return 0;
    }
    if(destination==0x80550123 && dmm_inline){
        assert(source(p)==0x61003c);functional_capture_observe_received(destination,p);assert(!release(destination,p));
        functional_capture_observe_freed(destination,p,0,0);return 0;
    }
    if(destination==0x80020002 && inline_receive){
        functional_capture_observe_received(destination,p);int rc=77;assert(functional_capture_release_notification(destination,p,&rc)==1 && !rc);return 0;
    }
    assert(sends<=8);sent_packets[sends-1]=packet(p);return 0;
}
static const struct full_imaging_io io={alloc,release,set_source,send_packet,size,source,NULL};
static int reserve(void){++reservations;return reserve_error;}
static void unlock(void){++unlocks;}
static int ready(void){return predecessor;}
static const struct native_cp_state_publication_guard guard={reserve,unlock,ready};
int full_imaging_capture_begin_functional(const uint8_t *p,size_t bytes,uint64_t instance,uint64_t generation){
    (void)p;(void)bytes;(void)instance;(void)generation;assert(!"State failure fixture must not enter functional imaging");return -ENODEV;
}
void full_imaging_capture_end(void){assert(imaging_live);imaging_live=0;}
int fcam_bridge_call(const struct fcam_native_origin *origin,uint32_t op,const void *in,size_t n,void *out,size_t capacity,struct fcam_bridge_result *result){
    assert(origin && origin->command==0x4038 && op==FCAM_OP_STATE && !in && !n && out && capacity==128 && result);++rpcs;return -ENODEV;
}
int functional_jpeg_codec_attach_capture(struct capture_input *c){(void)c;assert(!"No encoding in this ownership fixture");return -ENOSYS;}
int functional_jpeg_codec_capture_output(uint64_t base,struct capture_output_memory **out){(void)base;(void)out;assert(!"No encoded image in this ownership fixture");return -ENOSYS;}
static void setup(void){atomic_store(&owner,getpid());atomic_store(&enabled,1);state.owner_pid=getpid();state.enabled=1;job.io=io;job.guard=guard;}
static void set_request(uint8_t q[16]){memset(q,0,16);p16(q,5);p16(q+2,0x4038);p32(q+4,73);q[8]=2;}
static void input_owner(void){
    uint8_t frame[96+16*16*3]={0},request[16],parameters[128]={0};set_request(request);
    p32(frame,1);p32(frame+4,96);p64(frame+8,11);p64(frame+16,22);p64(frame+24,33);p64(frame+32,44);p64(frame+40,55);
    p32(frame+48,16);p32(frame+52,16);p32(frame+56,48);p32(frame+60,1);p64(frame+64,sizeof frame-96);
    for(unsigned i=96;i<sizeof frame;++i)frame[i]=(uint8_t)i;
    p64(frame+72,fnv(frame+96,sizeof frame-96));p32(frame+80,73);frame[84]=2;p64(frame+88,fnv(request,16));parameters[0x63]=8;
    p16(parameters+0x68,16);p16(parameters+0x6a,16);
    assert(!capture_input_create(frame,sizeof frame,request,parameters,&job.input));memcpy(job.request,request,16);
    /* Markers test ownership only; these bytes are never claimed as a photo. */
    const uint8_t markers[]={255,216,255,217};assert(!capture_output_memory_create(job.input,markers,4,markers,4,0,&job.output));
    assert(!capture_output_memory_hold(job.output,&job.export_token));
    void *mapping=calloc(1,0x3d8300);assert(mapping);original.base=(uintptr_t)mapping;
}
static void destroy_output(void){assert(!capture_output_memory_drop(job.output,job.export_token));assert(!capture_output_memory_destroy(job.output));job.output=NULL;assert(!capture_input_destroy(job.input));job.input=NULL;free((void *)original.base);}
static void setup_memory(void){
    assert(!functional_mpr_memory_enable(NULL));uint32_t group=0;assert(capture_memory_allocate(0x10,&group,job.table) && group);
    struct functional_mpr_memory_snapshot memory;assert(!functional_mpr_memory_snapshot(&memory));state.group=group;job.memory_generation=memory.active_generation;state.phase=ENCODING;
}
static uint32_t main_unit(void){struct functional_mpr_memory_lease l;uintptr_t a=(uintptr_t)u64(job.table+0x2a0);assert(!functional_mpr_memory_acquire(a,1,&l));uint32_t unit=l.span.unit;assert(!functional_mpr_memory_release(l.token));return unit;}
static struct packet *dmm_packet(unsigned op,uint32_t handle){struct packet *p=make_packet(40,0x80550123);p16(p->data,op);p32(p->data+8,handle);if(op==0x24)p32(p->data+12,UINT32_MAX);return p;}
static void drain_packets(void){for(unsigned i=0;i<8;++i)if(sent_packets[i]){
    void *p=sent_packets[i]->data;unsigned destination=source(p)==0x61003c?(u16(p)==0x8024 || u16(p)==0x8025?0x80550123:0x80c70073):0;
    assert(destination);functional_capture_observe_received(destination,p);assert(!release(destination,p));functional_capture_observe_freed(destination,p,0,0);sent_packets[i]=NULL;
}}
static void memory_done(void){assert(!job.open.token);capture_memory_free(0x10);assert(!functional_mpr_memory_shutdown());drain_packets();}
static void test_reject(int kind){
    setup();struct packet *p=make_packet(16,0x80020002);set_request(p->data);int result=123;
    if(kind==0){atomic_store(&enabled,0);assert(!functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result) && result==123);}
    if(kind==1){p->source=0x80020003;assert(functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result)==1 && result==-ENOTSUP);}
    if(kind==2){p->size=15;assert(functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result)==1 && result==-ENOTSUP);}
    if(kind==3){predecessor=0;assert(functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result)==1 && result==-ENODATA && unlocks==1);}
    if(kind==4){reserve_error=-ENOSPC;assert(functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result)==1 && result==-ENOSPC && !unlocks);}
    if(kind==5){state.phase=FRAME;assert(functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result)==1 && result==-EBUSY);state.phase=IDLE;}
    assert(!allocations && !releases && !sends && !rpcs && state.phase==IDLE);free(p);
}
static void test_accept(int failed_free){
    setup();struct packet *p=make_packet(16,0x80020002);set_request(p->data);release_error=failed_free?-EIO:0;int result=1;
    assert(functional_capture_dispatch(0x90040193,p->data,&io,&guard,&result)==1 && result==0 && releases==1 && !imaging_live);
    assert(!allocations && !sends && !rpcs && state.job==1 && state.request_cookie==73);
    if(failed_free){assert(job.retained_request==p->data && state.phase==FAULT && state.error==-EIO && !queued && !state.request_freed);free(p);}
    else{assert(queued && !job.retained_request && state.request_freed && execute_job()==-ENODEV);assert(rpcs==1);fault(-ENODEV);assert(state.error==-ENODEV);}
    assert(functional_capture_shutdown()==-EBUSY && !state.saved_verified);
}
static void test_terminal(int failed_send,int error_status){
    setup();state.phase=ENCODING;struct packet *p=make_packet(44,0x80550123);p16(p->data+2,0x1002);p32(p->data+0x24,0x4e0);p32(p->data+0x14,error_status?1:0);send_error=failed_send?-ENOSPC:0;int result=1;
    job.requests[1].sent=job.requests[1].freed=1;
    assert(functional_capture_terminal_send(0x80c70047,p->data,&io,&result)==1 && result==send_error && sends==1);
    assert(job.completion[1].sent==!failed_send && job.completion[1].freed==!failed_send);
    if(failed_send){assert(state.error==-ENOSPC && !releases);free(p);}
    else if(error_status){assert(wait_terminal(1)==-EIO && state.error==-EIO);}
    else{assert(!wait_terminal(1) && !job.completion[1].pointer && !state.error);}
}
static void test_dmm(unsigned kind){
    setup();dmm_inline=kind==0;setup_memory();uint32_t handle=main_unit();struct packet *p=dmm_packet(0x24,handle);int result=1;
    if(kind==1)allocate_error=-ENOMEM;
    if(kind==2)send_error=-ENOSPC;
    if(kind==3)++job.memory_generation;
    if(kind==4)p32(p->data+12,0);
    assert(functional_capture_dmm(0x61003c,p->data,&io,0,&result)==1);
    if(kind){assert(result==(kind==1?-ENOMEM:kind==2?-ENOSPC:kind==3?-ESTALE:-ENOTSUP));free(p);assert(!job.open.token && !job.opened);}
    else{
        assert(!result && job.open.token && job.opened==1 && releases==2);
        for(unsigned i=0;i<16;++i)assert(!job.inflight[i].pointer);
        p=dmm_packet(0x25,handle);send_error=-ENOSPC;
        assert(functional_capture_dmm(0x61003c,p->data,&io,0,&result)==1 && result==-ENOSPC && job.open.token && !job.closed);free(p);
        assert(!functional_mpr_memory_validate(&job.open));send_error=0;state.phase=FAULT;
        p=dmm_packet(0x25,handle);assert(functional_capture_dmm(0x61003c,p->data,&io,0,&result)==1 && !result && !job.open.token && job.closed==1);
    }
    struct functional_mpr_memory_snapshot m;assert(!functional_mpr_memory_snapshot(&m) && !m.leases);memory_done();
}
static void test_output_dmm(void){
    setup();input_owner();state.phase=WAIT_SAVE;struct capture_output_span s;assert(!capture_output_memory_span(job.output,CAPTURE_OUT_MAIN,&s));
    struct packet *p=make_packet(40,0x80c70073);p16(p->data,0x21);p16(p->data+22,1);p32(p->data+4,1);p32(p->data+8,s.handle);int result=1;
    assert(functional_capture_dmm(0x61003c,p->data,&io,0,&result)==1 && result==-EPERM && !allocations);
    allocate_error=-ENOMEM;assert(functional_capture_dmm(0x61003c,p->data,&io,original.base+0x2b1f08,&result)==1 && result==-ENOMEM);
    struct capture_output_info info;assert(!capture_output_memory_info(job.output,&info) && !info.native_references);allocate_error=0;
    assert(functional_capture_dmm(0x61003c,p->data,&io,original.base+0x2b1f08,&result)==1 && !result);
    assert(!capture_output_memory_info(job.output,&info) && info.native_references==1);
    p=make_packet(40,0x80c70073);p16(p->data,0x23);p16(p->data+22,2);p32(p->data+8,s.handle);send_error=-ENOSPC;
    assert(functional_capture_dmm(0x61003c,p->data,&io,original.base+0x2b2388,&result)==1 && result==-ENOSPC);
    assert(!capture_output_memory_info(job.output,&info) && info.native_references==1);send_error=0;state.phase=FAULT;
    assert(functional_capture_dmm(0x61003c,p->data,&io,original.base+0x2b2388,&result)==1 && !result);
    assert(!capture_output_memory_info(job.output,&info) && !info.native_references);drain_packets();destroy_output();
}
static void *receive_notifications(void *unused){(void)unused;
    for(unsigned i=0;i<3;++i){assert(sent_packets[i]);void *p=sent_packets[i]->data;functional_capture_observe_received(0x80020002,p);int rc=1;assert(functional_capture_release_notification(0x80020002,p,&rc)==1 && !rc);sent_packets[i]=NULL;}return NULL;
}
static void test_delivery(int asynchronous){
    setup();input_owner();state.phase=DELIVERING;imaging_live=1;inline_receive=!asynchronous;
    uint8_t local[12]={0};p16(local+2,2026);local[4]=11;local[5]=3;local[6]=12;
    struct full_imaging_io delivery_io=io;delivery_io.send=notification_send;
    assert(!capture_delivery_begin(job.output,job.request,local,&delivery_io,&guard,&job.delivery));state.phase=WAIT_SAVE;
    pthread_t receiver;if(asynchronous)assert(!pthread_create(&receiver,NULL,receive_notifications,NULL));
    assert(!retire_notifications());if(asynchronous)assert(!pthread_join(receiver,NULL));
    assert(!job.delivery && !job.published_delivery && state.notification_consumed==3 && reservations==1 && unlocks==1 && imaging_live);
    assert(!state.saved_verified && !state.resources_released && functional_capture_shutdown()==-EBUSY);full_imaging_capture_end();destroy_output();
}
static void test_native_queue(unsigned variant){
    setup();state.phase=ENCODING;unsigned resize=variant/3,bad=variant%3;struct packet *p=make_packet(48,0x80c70047);
    if(resize){input_owner();assert(!capture_resize_request_build(job.input,job.request,p->data,&job.queued_input));producing_resize=1;}
    else{p16(p->data+2,1);p32(p->data+0x10,56);p32(p->data+0x24,0x1500);p64(p->data+0x28,(uintptr_t)saved_config_body);
        p64(saved_config_body,0x12345);p32(saved_config_body+8,120);p64(job.table+0x2a0,0x12345);producing_config=1;}
    if(bad==1)p->data[0x24]^=1;
    if(bad==2){if(resize)p->data[0x28]^=1;else saved_config_body[8]^=1;}
    int result=77;assert(functional_capture_terminal_send(0x8055001f,p->data,&io,&result)==1);
    if(!bad){assert(!result && sends==1 && releases==1 && job.requests[resize].sent && job.requests[resize].received && job.requests[resize].freed);}
    else{assert(result==(bad==2 && resize?-ESTALE:-EBADMSG) && !sends && !releases);free(p);}
    producing_resize=producing_config=0;
    if(resize){assert(!capture_input_drop(job.input,&job.queued_input));destroy_output();}
}
static uint32_t release_handle;
static void capture_record(const char *tag,const char *text){printf("OBS %s%s\n",tag,text);}
static void *release_native_output(void *unused){(void)unused;
    struct packet *p=make_packet(40,0x80c70073);p16(p->data,0x23);p16(p->data+22,2);p32(p->data+8,release_handle);int result=1;
    assert(functional_capture_dmm(0x61003c,p->data,&io,original.base+0x2b2388,&result)==1 && !result);drain_packets();return NULL;
}
static void test_creator_save_retirement(int native_reference){
    setup();input_owner();job.io.record=capture_record;state.job=1;state.request_freed=1;
    state.request_cookie=u32(job.request+4);state.request_fnv=fnv(job.request,16);state.phase=ACCEPTED;note("natural-request-owned",0);
    state.phase=WAIT_SAVE;state.encoded=state.frame_released=1;state.frame_token=11;state.model_instance=22;imaging_live=1;
    note("notifications-queued-unsaved",0);state.notification_consumed=3;note("notifications-consumed-unsaved",0);
    assert(!capture_save_prepare(job.output,0x4321,&job.save));
    for(unsigned i=0;i<2;++i){
        struct capture_output_span expected;assert(!capture_output_memory_span(job.output,i?CAPTURE_OUT_AUX:CAPTURE_OUT_HEADER,&expected));
        struct packet *q=make_packet(40,0x80c70073);p16(q->data,0x28);p32(q->data+8,i?0x27f:0x80d61);int result=1;
        assert(functional_capture_dmm(0x61003c,q->data,&io,0,&result)==1 && result==-EPERM);
        assert(functional_capture_dmm(0x61003c,q->data,&io,original.base+0x2b1f08,&result)==1 && !result);
        struct packet *r=sent_packets[sends-1];assert(r && u16(r->data)==0x8028 && u32(r->data+12)==expected.handle &&
            u64(r->data+24)==expected.alias && u32(r->data+32)==expected.capacity);
        drain_packets();
    }
    struct capture_output_span header,main;assert(!capture_output_memory_span(job.output,CAPTURE_OUT_HEADER,&header));assert(!capture_output_memory_span(job.output,CAPTURE_OUT_MAIN,&main));
    memset((void *)header.cpu,0,4096);((uint8_t *)header.cpu)[0]=255;((uint8_t *)header.cpu)[1]=216;
    struct fsys_write_layout layout={.count=2,.address_mode=1,.callback=0x4321,.cookie=0x1234,.expected_bytes=4096+main.bytes,.payload_bytes=4096+main.bytes};
    strcpy(layout.path,"A:/DCIM/100MSDCF/DSC00001.JPG");
    layout.area[0]=(struct fsys_write_area){.address=header.cpu,.submitted_bytes=4096,.bytes=4096};
    layout.area[1]=(struct fsys_write_area){.address=main.cpu,.submitted_bytes=main.capacity,.bytes=main.bytes,.offset=4096};
    uint64_t hashes[8]={fnv((void *)header.cpu,4096),fnv((void *)main.cpu,main.bytes)};unsigned readable[8]={1,1};
    uint8_t *combined=malloc((size_t)layout.expected_bytes);assert(combined);memcpy(combined,(void *)header.cpu,4096);memcpy(combined+4096,(void *)main.cpu,main.bytes);uint64_t digest=fnv(combined,(size_t)layout.expected_bytes);free(combined);
    functional_capture_fsys_begin(1,&layout,hashes,readable);assert(state.write_token==1 && !state.error);
    functional_capture_fsys_event(1,CAPTURE_SAVE_CALLBACK,0,1,0,0);
    functional_capture_fsys_event(1,CAPTURE_SAVE_FINISHED,0,1,0,0);
    functional_capture_fsys_event(1,CAPTURE_SAVE_CALLBACK_RETURN,0,1,0,0);
    functional_capture_fsys_event(1,CAPTURE_SAVE_SUBMIT,0,1,0,0);
    functional_capture_fsys_event(1,CAPTURE_SAVE_READBACK,0,1,layout.expected_bytes,digest);
    assert(!state.write_readback_verified && !state.resources_released);
    functional_capture_fsys_event(0,CAPTURE_SAVE_COVERAGE,0,1,1,0);
    assert(state.write_readback_verified && !state.resources_released);
    pthread_t consumer;
    if(native_reference){uint8_t q[40]={0},r[40];p16(q,0x21);p16(q+22,1);p32(q+4,1);p32(q+8,main.handle);assert(!capture_output_memory_reply(job.output,q,0,r));release_handle=main.handle;assert(!pthread_create(&consumer,NULL,release_native_output,NULL));}
    assert(!retire_saved_output());if(native_reference)assert(!pthread_join(consumer,NULL));
    assert(state.resources_released && state.phase==IDLE && !job.input && !job.output && !job.save && !imaging_live && !state.saved_verified);
    assert(!functional_capture_shutdown());free((void *)original.base);
}
static void test_fork(void){setup();pthread_mutex_lock(&mutex);pid_t child=fork();assert(child>=0);
    if(!child){struct functional_capture_snapshot s;_exit(functional_capture_snapshot(&s)==-ECHILD && functional_capture_shutdown()==-ECHILD?0:1);}
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));pthread_mutex_unlock(&mutex);
}
int main(int argc,char **argv){assert(argc==2);int mode=atoi(argv[1]);
    if(mode<6)test_reject(mode);else if(mode<8)test_accept(mode-6);else if(mode<11)test_terminal(mode==9,mode==10);
    else if(mode<16)test_dmm((unsigned)mode-11);else if(mode==16)test_output_dmm();else if(mode<19)test_delivery(mode==18);else if(mode==19)test_fork();else if(mode<26)test_native_queue((unsigned)mode-20);else test_creator_save_retirement(mode==27);
    puts("PASS HOST_ONLY capture ownership/gates/native transport/provider rollback/notification retirement; original_AP=0 original_codec=0 Fsys_saved=0 capture_verified=0");return 0;
}
