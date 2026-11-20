/* Include the existing kernel-ABI fixture; CHECK remains active with NDEBUG. */
#define main bb_legacy_main
#include "test_bb_receiver.c"
#undef main

static void verify_042b(u16 raw, u32 generation)
{
    static const u8 prefix[8]={0x0d,0x20,0x2b,0x04,10,0,1,0x80};
    CHECK(bb_generation[6]==generation && bb_values[6]==raw);
    CHECK(bb_042b_parameter==(u32)(u8)raw);
    for(unsigned i=0;i<8;i++) CHECK(bb_042b_wire[i]==prefix[i]);
    CHECK(bb_042b_wire[8]==(u8)raw && bb_042b_wire[9]==(u8)(raw>>8));
}
static void values_042b(void)
{
    for(unsigned value=0;value<65536;value++) {
        CHECK(!udate_sender(BB_TARGET,new_message(0x42b,(u16)value)));
        CHECK(bb_count==1 && active==1 && bb_generation[6]==value);
        CHECK(bb_worker_step());verify_042b((u16)value,value+1);verify_pool();
        CHECK(!bb_0159_vdf_pending && !bb_panel_pending_mask);
        for(unsigned i=0;i<6;i++) CHECK(!bb_generation[i]);
    }
    CHECK(bb_consumed==65536 && bb_accepted==65536);
}
static void reject_042b(void)
{
    for(unsigned i=0;i<16;i++) {
        void *m=new_message(0x42b,0xffff);
        switch(i) {
        case 0:meta(m)->size=0;break;
        case 1:meta(m)->size=9;break;
        case 2:meta(m)->size=22;put16((u8 *)m+4,22);break;
        case 3:put16(m,0x2005);break;
        case 4:put16((u8 *)m+4,9);break;
        case 5:put16((u8 *)m+6,2);break;
        case 6:meta(m)->source=0;break;
        case 7:meta(m)->source=BB_TARGET;break;
        case 8:meta(m)->source=0x80000000;break;
        case 9:meta(m)->source=0xf1234567;break;
        case 10:put16((u8 *)m+2,0x161);break;
        case 11:put16((u8 *)m+2,0x429);break;
        case 12:put16((u8 *)m+2,0x42a);break;
        case 13:put16((u8 *)m+2,0x42c);break;
        case 14:put16((u8 *)m+2,0x165);break;
        default:put16((u8 *)m+2,0x158);break;
        }
        reject(m,-1020);CHECK(!bb_generation[6]);verify_pool();
    }
    bb_ready=0;reject(new_message(0x42b,0),-1021);bb_ready=1;
    for(unsigned i=0;i<BB_DEPTH;i++) CHECK(!udate_sender(BB_TARGET,new_message(0x42b,(u16)i)));
    reject(new_message(0x42b,1),-1021);drain();verify_pool();verify_042b(BB_DEPTH-1,BB_DEPTH);
}
static void fault_042b(void)
{
    CHECK(!udate_sender(BB_TARGET,new_message(0x42b,0x55f7)));drain();verify_042b(0x55f7,1);
    void *m=new_message(0x42b,0xffff);CHECK(!udate_sender(BB_TARGET,m));free_failure=1;
    CHECK(!bb_worker_step() && bb_fault && bb_inflight.message==m && active==1);
    verify_042b(0x55f7,1);CHECK(!bb_worker_step() && failed_free==1);
    free_failure=0;reject(new_message(0x42b,0),-1021);verify_042b(0x55f7,1);
    CHECK(!osal_free_msg(BB_TARGET,m));bb_inflight.message=NULL;CHECK(!active && !replies);
}
static void reuse_042b(void)
{
    void *m=new_message(0x42b,0x55f7);CHECK(!udate_sender(BB_TARGET,m));recycle_once=1;
    CHECK(bb_worker_step());CHECK(recycle_address==m && recycle_rc==0 && bb_count==1);
    verify_042b(0x55f7,1);CHECK(bb_worker_step() && bb_generation[0]==1);verify_pool();
}
static void all_opcodes(void)
{
    for(unsigned cmd=0;cmd<65536;cmd++) {
        if(cmd==0x118 || cmd==0x11b || bb_index((u16)cmd)>=0) continue;
        reject(new_message((u16)cmd,0),-1020);
    }
    CHECK(bb_rejected==65527 && !bb_generation[6]);verify_pool();
}
static void *batch_producer(void *unused)
{
    (void)unused;
    for(unsigned i=0;i<2500;i++) {
        CHECK(!sem_wait(&permits));
        CHECK(!udate_sender(BB_TARGET,new_message(0x42b,(u16)(i*97))));
    }
    atomic_fetch_add(&done,1);return NULL;
}
static void concurrent_042b(void)
{
    pthread_t p[4];concurrent_mode=1;CHECK(!sem_init(&permits,0,BB_DEPTH/2));
    for(unsigned i=0;i<4;i++) CHECK(!pthread_create(&p[i],NULL,batch_producer,NULL));
    while(atomic_load(&done)!=4) { bb_worker_step();sched_yield(); }
    for(unsigned i=0;i<4;i++) CHECK(!pthread_join(p[i],NULL));
    drain();verify_042b(bb_values[6],10000);verify_pool();CHECK(!bb_rejected && bb_consumed==10000);
    CHECK(!sem_destroy(&permits));
}
static void mixed(void)
{
    static const u16 commands[]={0x142,0x15a,0x160,0x500,0x33b,0x159,0x42b};
    for(unsigned round=0;round<1000;round++) {
        for(unsigned n=0;n<7;n++) CHECK(!udate_sender(BB_TARGET,new_message(commands[n],n==4?0x5500:n==6?0xa5f7:1)));
        drain();verify_pool();verify_042b(0xa5f7,round+1);
        for(unsigned n=0;n<7;n++) CHECK(bb_generation[n]==round+1);
        CHECK(bb_0159_vdf_pending==1 && bb_0159_vdf_request[8]==1 && !bb_panel_pending_mask);
    }
}
int main(int argc,char **argv)
{
    CHECK(argc==2 && !init_module() && bb_ready);
    if(!strcmp(argv[1],"values")) values_042b();
    else if(!strcmp(argv[1],"reject")) reject_042b();
    else if(!strcmp(argv[1],"failure")) fault_042b();
    else if(!strcmp(argv[1],"reuse")) reuse_042b();
    else if(!strcmp(argv[1],"all-opcodes")) all_opcodes();
    else if(!strcmp(argv[1],"concurrent")) concurrent_042b();
    else {CHECK(!strcmp(argv[1],"mixed"));mixed();}
    printf("{\"case\":\"%s\",\"accepted\":%u,\"consumed\":%u,\"outstanding\":%u,\"replies\":%u}\n",argv[1],bb_accepted,bb_consumed,active,replies);
    return 0;
}
