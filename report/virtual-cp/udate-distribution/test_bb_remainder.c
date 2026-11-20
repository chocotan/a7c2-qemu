/* Source-bound 011b/0150 normalization, no-reply and ownership contracts. */
#define main bb_legacy_main
#include "test_bb_receiver.c"
#undef main

static u16 command;
static unsigned slot;
static void *request(unsigned a,unsigned b,u32 tail)
{
    void *m=new_message(command,0);unsigned size=slot?20:10;
    meta(m)->size=size;put16((u8 *)m+4,(u16)size);
    ((u8 *)m)[8]=(u8)a;((u8 *)m)[slot?12:9]=(u8)b;
    if(slot) {
        ((u8 *)m)[9]=0xa5;((u8 *)m)[10]=0x5a;((u8 *)m)[11]=0xff;
        ((u8 *)m)[13]=0xff;((u8 *)m)[14]=0x5a;((u8 *)m)[15]=0xa5;
        put32((u8 *)m+16,tail);
    }
    return m;
}
static void verify(const u8 *wire,unsigned generation,u32 source)
{
    const volatile struct bb_display_intent *d=&bb_display[slot];
    const u8 head0[8]={1,0x20,4,1,12,0,1,0};
    const u8 head1[8]={1,0x20,6,3,20,0,1,0};
    unsigned size=slot?20:10;
    CHECK(d->generation==generation && d->source==source && d->pending==1);
    for(unsigned i=0;i<20;i++)CHECK(d->wire[i]==(i<size?wire[i]:0));
    for(unsigned i=0;i<8;i++)CHECK(d->lower[i]==(slot?head1[i]:head0[i]));
    if(!slot) {
        /* Independent expected bit mapping: only 0,1,5 survive. */
        CHECK(d->lower[8]==((wire[8]&1)|(wire[8]&2)|(wire[8]&32)));
        CHECK(d->lower[9]==wire[9]);
        for(unsigned i=10;i<20;i++)CHECK(!d->lower[i]);
    } else {
        CHECK(d->lower[8]==wire[8] && d->lower[12]==wire[12]);
        for(unsigned i=9;i<16;i++)if(i!=12)CHECK(!d->lower[i]);
        for(unsigned i=16;i<20;i++)CHECK(d->lower[i]==wire[i]);
    }
    CHECK(!bb_display[1-slot].generation && !replies && !bb_panel_busy && !bb_0145_generation);
}
static void replay_new(void)
{
    void *m=request(slot?2:3,slot?0:8,0);u8 wire[20];memcpy(wire,m,slot?20:10);
    meta(m)->source=0x81cf61c6;
    CHECK(!udate_sender(BB_TARGET,m) && !bb_display[slot].generation);
    CHECK(bb_worker_step());verify(wire,1,0x81cf61c6);verify_pool();
    CHECK(strstr(last_log,"BB_K_DISPLAY_CONFIG") && strstr(last_log,"ap_reply=none lower_sent=0 applied=0 completion=0"));
    if(!slot) {
        const u8 expected[12]={1,0x20,4,1,12,0,1,0,3,8,0,0};
        for(unsigned i=0;i<12;i++)CHECK(bb_display[0].lower[i]==expected[i]);
    }
}
static void values_new(void)
{
    unsigned gen=0;
    for(unsigned n=0;n<65536;n++) {
        unsigned a=slot?n%3:n&255,b=slot?(n/3)%4:n>>8;
        u8 wire[20];void *m=request(a,b,n*0x10204081u);memcpy(wire,m,slot?20:10);
        CHECK(!udate_sender(BB_TARGET,m) && bb_worker_step());verify(wire,++gen,0x81cf61c3);verify_pool();
    }
    CHECK(bb_consumed==65536 && bb_accepted==65536);
}
static void invalid_new(void)
{
    unsigned size=slot?20:10;
    for(unsigned n=0;n<=40;n++)if(n!=size) {
        void *m=request(0,0,0);meta(m)->size=n;put16((u8 *)m+4,(u16)n);reject(m,-1020);
    }
    for(unsigned n=0;n<7;n++) {
        void *m=request(0,0,0);
        switch(n) {
        case 0:put16(m,0x2001);break;
        case 1:put16((u8 *)m+4,(u16)(size+1));break;
        case 2:put16((u8 *)m+6,2);break;
        case 3:meta(m)->source=0;break;
        case 4:meta(m)->source=0x80000000;break;
        case 5:meta(m)->source=BB_TARGET;break;
        default:meta(m)->source=0xf1234567;break;
        }
        reject(m,-1020);
    }
    if(!slot) {
        void *m=request(3,8,0);meta(m)->source=0x81b40549;reject(m,-1020);
    }
    if(slot) {
        for(unsigned n=3;n<256;n++)reject(request(n,0,0),-1020);
        for(unsigned n=4;n<256;n++)reject(request(0,n,0),-1020);
    }
    CHECK(!bb_display[slot].generation);verify_pool();
}
static void opcodes_new(void)
{
    unsigned rejected=0;
    for(unsigned cmd=0;cmd<65536;cmd++) {
        if(cmd==command || (!slot && (bb_index((u16)cmd)>=0 || cmd==0x118)))continue;
        void *m=request(0,0,0);put16((u8 *)m+2,(u16)cmd);reject(m,-1020);++rejected;
    }
    CHECK(bb_rejected==rejected && !bb_display[slot].generation);verify_pool();
}
static void ownership_new(void)
{
    bb_ready=0;reject(request(0,0,0),-1021);bb_ready=1;
    void *m=request(1,1,0);CHECK(!udate_sender(BB_TARGET,m));CHECK(udate_sender(BB_TARGET,m)==-1021);
    for(unsigned n=1;n<BB_DEPTH;n++)CHECK(!udate_sender(BB_TARGET,request(n%3,n%4,n)));
    reject(request(0,0,0),-1021);drain();verify_pool();
    CHECK(bb_display[slot].generation==BB_DEPTH && bb_consumed==BB_DEPTH);
}
static void failure_new(void)
{
    replay_new();u8 old[20];for(unsigned i=0;i<20;i++)old[i]=bb_display[slot].wire[i];
    void *m=request(0,0,0);CHECK(!udate_sender(BB_TARGET,m));free_failure=1;
    CHECK(!bb_worker_step() && bb_fault && bb_inflight.message==m && active==1 && failed_free==1);
    verify(old,1,0x81cf61c6);CHECK(!bb_worker_step() && failed_free==1);free_failure=0;
    reject(request(0,0,0),-1021);verify(old,1,0x81cf61c6);
    CHECK(!osal_free_msg(BB_TARGET,m));bb_inflight.message=NULL;CHECK(!active && !replies);
}
static void reuse_new(void)
{
    void *m=request(1,1,0xdeadbeef);u8 wire[20];memcpy(wire,m,slot?20:10);
    CHECK(!udate_sender(BB_TARGET,m));recycle_once=1;
    CHECK(bb_worker_step() && recycle_address==m && !recycle_rc && bb_count==1);
    verify(wire,1,0x81cf61c3);CHECK(bb_worker_step() && bb_generation[0]==1);verify_pool();
}
static void *producer_new(void *unused)
{
    (void)unused;
    for(unsigned n=0;n<2500;n++) {CHECK(!sem_wait(&permits));CHECK(!udate_sender(BB_TARGET,request(n%3,n%4,n)));}
    atomic_fetch_add(&done,1);return NULL;
}
static void concurrent_new(void)
{
    pthread_t p[4];concurrent_mode=1;CHECK(!sem_init(&permits,0,BB_DEPTH/2));
    for(unsigned i=0;i<4;i++)CHECK(!pthread_create(&p[i],NULL,producer_new,NULL));
    while(atomic_load(&done)!=4){bb_worker_step();sched_yield();}
    for(unsigned i=0;i<4;i++)CHECK(!pthread_join(p[i],NULL));
    drain();verify_pool();CHECK(bb_display[slot].generation==10000 && !bb_rejected);
    CHECK(!sem_destroy(&permits));
}
int main(int argc,char **argv)
{
    CHECK(argc==3 && !init_module() && bb_ready);slot=!strcmp(argv[1],"0150");
    CHECK(slot || !strcmp(argv[1],"011b"));command=slot?0x150:0x11b;
    if(!strcmp(argv[2],"replay"))replay_new();
    else if(!strcmp(argv[2],"values"))values_new();
    else if(!strcmp(argv[2],"invalid"))invalid_new();
    else if(!strcmp(argv[2],"all-opcodes"))opcodes_new();
    else if(!strcmp(argv[2],"ownership"))ownership_new();
    else if(!strcmp(argv[2],"failure"))failure_new();
    else if(!strcmp(argv[2],"reuse"))reuse_new();
    else {CHECK(!strcmp(argv[2],"concurrent"));concurrent_new();}
    printf("{\"command\":\"%s\",\"case\":\"%s\",\"accepted\":%u,\"consumed\":%u,\"outstanding\":%u,\"replies\":%u}\n",argv[1],argv[2],bb_accepted,bb_consumed,active,replies);
    return 0;
}
