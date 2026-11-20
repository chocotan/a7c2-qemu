/* Original run27 wire, independent VDF expectations and ownership tests. */
#define main bb_legacy_main
#include "test_bb_receiver.c"
#undef main

static const u8 observed[24]={0x0d,0x20,0x45,1,24,0,1,0x80,0,0,0,1,1,0,0,0,0x8b,0x61,0xcf,0x81,0,0,0,0};
static void *message_0145(unsigned bits,unsigned mode,u32 notify)
{
    void *m=new_message(0x145,0);meta(m)->size=24;
    memcpy(m,observed,24);
    for(unsigned i=0;i<8;i++) ((u8 *)m)[8+i]=(u8)((bits>>i)&1);
    put32((u8 *)m+16,notify);((u8 *)m)[20]=(u8)mode;
    return m;
}
static void snapshot_0145(const u8 wire[24],u32 generation,u32 source)
{
    static const u8 header[8]={1,0x20,0x12,3,24,0,1,0};
    CHECK(bb_0145_generation==generation && bb_0145_source==source && bb_0145_vdf_pending==1);
    for(unsigned i=0;i<24;i++) CHECK(bb_0145_wire[i]==wire[i]);
    for(unsigned i=0;i<8;i++) CHECK(bb_0145_vdf_request[i]==header[i]);
    for(unsigned i=8;i<21;i++) CHECK(bb_0145_vdf_request[i]==wire[i]);
    for(unsigned i=21;i<24;i++) CHECK(bb_0145_vdf_request[i]==0);
    for(unsigned i=0;i<BB_COMMANDS;i++) CHECK(!bb_generation[i]);
    CHECK(!bb_panel_busy && !bb_0159_vdf_pending && !bb_panel_pending_mask && !replies);
}
static void replay(void)
{
    u8 saved[24];void *m=message_0145(0x18,0,0x81cf618b);meta(m)->source=0x81cf61c6;
    memcpy(saved,m,24);CHECK(!memcmp(saved,observed,24));
    CHECK(!udate_sender(BB_TARGET,m) && bb_count==1 && active==1 && !bb_0145_generation);
    CHECK(bb_worker_step());snapshot_0145(saved,1,0x81cf61c6);verify_pool();
    CHECK(strstr(last_log,"BB_K_0145_CONFIG") && strstr(last_log,"notify_destination=0x81cf618b"));
    CHECK(strstr(last_log,"ap_reply=none lower_sent=0 applied=0 notifications=0 completion=0"));
    printf("{\"run27_wire\":\"0d2045011800018000000001010000008b61cf8100000000\",\"lower_record\":\"012012031800010000000001010000008b61cf8100000000\",\"lower_sent\":false}\n");
}
static void values(void)
{
    unsigned generation=0;
    for(unsigned mode=0;mode<=2;mode+=2) for(unsigned bits=0;bits<256;bits++) {
        /* +16 is an opaque notification QID, never a pointer or send destination here. */
        u8 saved[24];void *m=message_0145(bits,mode,bits*0x01010101u);
        ((u8 *)m)[21]=0xa5;((u8 *)m)[22]=0x5a;((u8 *)m)[23]=0xff;
        memcpy(saved,m,24);CHECK(!udate_sender(BB_TARGET,m));
        CHECK(bb_worker_step());snapshot_0145(saved,++generation,0x81cf61c3);verify_pool();
    }
    CHECK(bb_consumed==512 && bb_accepted==512);
}
static void invalid(void)
{
    for(unsigned n=0;n<=40;n++) if(n!=24) {
        void *m=message_0145(0x18,0,0);meta(m)->size=n;put16((u8 *)m+4,(u16)n);reject(m,-1020);
    }
    for(unsigned off=8;off<16;off++) for(unsigned v=2;v<256;v++) {
        void *m=message_0145(0x18,0,0);((u8 *)m)[off]=(u8)v;reject(m,-1020);
    }
    for(unsigned mode=0;mode<256;mode++) if(mode!=0 && mode!=2) reject(message_0145(0x18,mode,0),-1020);
    for(unsigned n=0;n<7;n++) {
        void *m=message_0145(0x18,0,0);
        switch(n) {
        case 0:put16(m,0x2001);break;
        case 1:put16((u8 *)m+4,22);break;
        case 2:put16((u8 *)m+6,2);break;
        case 3:meta(m)->source=BB_TARGET;break;
        case 4:meta(m)->source=0x80000000;break;
        case 5:meta(m)->source=0;break;
        default:meta(m)->source=0xf1234567;break;
        }
        reject(m,-1020);
    }
    CHECK(!bb_0145_generation && !bb_0145_vdf_pending);verify_pool();
}
static void all_opcodes_24(void)
{
    for(unsigned cmd=0;cmd<65536;cmd++) if(cmd!=0x145) {
        void *m=message_0145(0x18,0,0);put16((u8 *)m+2,(u16)cmd);reject(m,-1020);
    }
    CHECK(bb_rejected==65535 && !bb_0145_generation);verify_pool();
}
static void ownership(void)
{
    bb_ready=0;reject(message_0145(0,0,0),-1021);bb_ready=1;
    void *m=message_0145(0x18,0,0x81cf618b);
    CHECK(!udate_sender(BB_TARGET,m));CHECK(udate_sender(BB_TARGET,m)==-1021);
    for(unsigned n=1;n<BB_DEPTH;n++) CHECK(!udate_sender(BB_TARGET,message_0145(n,2,n)));
    reject(message_0145(1,0,0),-1021);drain();verify_pool();
    CHECK(bb_0145_generation==BB_DEPTH && bb_consumed==BB_DEPTH && !replies);
}
static void failure(void)
{
    replay();u8 old[24];for(unsigned i=0;i<24;i++) old[i]=bb_0145_wire[i];
    void *m=message_0145(0xff,2,0);CHECK(!udate_sender(BB_TARGET,m));free_failure=1;
    CHECK(!bb_worker_step() && bb_fault && bb_inflight.message==m && active==1);
    CHECK(bb_consumed==1 && failed_free==1);snapshot_0145(old,1,0x81cf61c6);
    CHECK(!bb_worker_step() && failed_free==1);free_failure=0;
    reject(message_0145(0,0,0),-1021);snapshot_0145(old,1,0x81cf61c6);
    CHECK(!osal_free_msg(BB_TARGET,m));bb_inflight.message=NULL;CHECK(!active && !replies);
}
static void reuse_0145(void)
{
    void *m=message_0145(0x18,0,0x81cf618b);u8 saved[24];memcpy(saved,m,24);
    CHECK(!udate_sender(BB_TARGET,m));recycle_once=1;
    CHECK(bb_worker_step());CHECK(recycle_address==m && !recycle_rc && bb_count==1);
    snapshot_0145(saved,1,0x81cf61c3);CHECK(bb_worker_step() && bb_generation[0]==1);verify_pool();
}
static void *producer_0145(void *unused)
{
    (void)unused;
    for(unsigned n=0;n<2500;n++) {
        CHECK(!sem_wait(&permits));CHECK(!udate_sender(BB_TARGET,message_0145(n&255,2,n)));
    }
    atomic_fetch_add(&done,1);return NULL;
}
static void concurrent_0145(void)
{
    pthread_t threads[4];concurrent_mode=1;CHECK(!sem_init(&permits,0,BB_DEPTH/2));
    for(unsigned i=0;i<4;i++) CHECK(!pthread_create(&threads[i],NULL,producer_0145,NULL));
    while(atomic_load(&done)!=4) {bb_worker_step();sched_yield();}
    for(unsigned i=0;i<4;i++) CHECK(!pthread_join(threads[i],NULL));
    drain();verify_pool();CHECK(bb_0145_generation==10000 && bb_consumed==10000 && !bb_rejected);
    CHECK(!sem_destroy(&permits));
}
int main(int argc,char **argv)
{
    CHECK(argc==2 && !init_module() && bb_ready);
    if(!strcmp(argv[1],"replay")) replay();
    else if(!strcmp(argv[1],"values")) values();
    else if(!strcmp(argv[1],"invalid")) invalid();
    else if(!strcmp(argv[1],"all-opcodes")) all_opcodes_24();
    else if(!strcmp(argv[1],"ownership")) ownership();
    else if(!strcmp(argv[1],"failure")) failure();
    else if(!strcmp(argv[1],"reuse")) reuse_0145();
    else {CHECK(!strcmp(argv[1],"concurrent"));concurrent_0145();}
    printf("{\"case\":\"%s\",\"accepted\":%u,\"freed\":%u,\"outstanding\":%u,\"replies\":%u}\n",argv[1],bb_accepted,bb_consumed,active,replies);
    return 0;
}
