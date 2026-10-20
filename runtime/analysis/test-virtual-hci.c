#define VHCI_CORE_TEST
#include "virtual-hci.c"
#include <assert.h>
#include <stdio.h>

struct capture {
    uint8_t event[258];
    size_t length;
    unsigned emits, logs, entropy_calls;
    int emit_failure, entropy_failure;
};
static int capture_emit(void *v, const uint8_t *p, size_t n) {
    struct capture *c=v;
    assert(n<=sizeof c->event);
    memcpy(c->event,p,n); c->length=n; ++c->emits;
    return c->emit_failure;
}
/* Explicit test stub; production uses guest SYS_getrandom, never this sequence. */
static int capture_entropy(void *v, uint8_t *p, size_t n) {
    struct capture *c=v;
    ++c->entropy_calls;
    for (size_t i=0;i<n;++i) p[i]=(uint8_t)(i+c->entropy_calls);
    return c->entropy_failure;
}
static void capture_log(void *v, const struct vhci *s, uint16_t op,
                        const uint8_t *p, size_t n, const uint8_t *e, size_t en) {
    (void)s; (void)op; (void)p; (void)n;
    assert(en>=7 && e[0]==4 && e[1]==0x0e);
    ++((struct capture *)v)->logs;
}
static uint8_t send_cmd(struct vhci *s, struct capture *c, uint16_t op,
                        const uint8_t *p, size_t n) {
    struct vhci_io io={c,capture_emit,capture_entropy,capture_log};
    uint8_t frame[259]={1,(uint8_t)op,(uint8_t)(op>>8),(uint8_t)n};
    assert(n<=255);
    if (n) memcpy(frame+4,p,n);
    unsigned before=c->emits;
    assert(vhci_feed(s,&io,frame,n+4)==0);
    assert(c->emits==before+1 && c->logs==c->emits);
    assert(c->length==(size_t)c->event[2]+3);
    assert(c->event[3]==1 && le16(c->event+4)==op);
    return c->event[6];
}
static void reset(struct vhci *s, struct capture *c) {
    vhci_init(s); memset(c,0,sizeof *c);
    assert(send_cmd(s,c,0x0c03,0,0)==0 && s->powered==1);
}
static void test_framing(void) {
    const uint8_t sequence[]={1,3,12,0, 1,9,16,0, 1,1,12,8,1,2,3,4,5,6,7,8};
    for (size_t split=0;split<=sizeof sequence;++split) {
        struct vhci s; struct capture c={0}; vhci_init(&s);
        struct vhci_io io={&c,capture_emit,capture_entropy,capture_log};
        assert(vhci_feed(&s,&io,sequence,split)==0);
        assert(vhci_feed(&s,&io,sequence+split,sizeof sequence-split)==0);
        assert(c.emits==3 && s.used==0 && !memcmp(s.event_mask,sequence+12,8));
    }
    struct vhci s; struct capture c={0}; vhci_init(&s);
    struct vhci_io io={&c,capture_emit,capture_entropy,capture_log};
    for (size_t i=0;i<sizeof sequence;++i) assert(!vhci_feed(&s,&io,sequence+i,1));
    assert(c.emits==3);
    /* Full 255-byte unknown payload containing 0x01 must not become new commands. */
    uint8_t huge[259]; memset(huge,1,sizeof huge); huge[1]=255; huge[2]=255; huge[3]=255;
    for (size_t i=0;i<sizeof huge;++i) assert(!vhci_feed(&s,&io,huge+i,1));
    assert(c.emits==4 && c.event[6]==1 && !s.used);
    uint8_t bad=2;
    assert(vhci_feed(&s,&io,&bad,1)==-1 && s.failed && s.bad_type==bad);
    assert(vhci_feed(&s,&io,sequence,4)==-1 && c.emits==4);
    reset(&s,&c); c.emit_failure=1;
    assert(vhci_feed(&s,&io,sequence,4)==-1 && s.failed);
}
static void test_diag_disable_no_reply(void) {
    const uint8_t diag[]={7,0xf0,0};
    for(size_t split=0;split<=3;split++) {
        struct vhci s;struct capture c={0};vhci_init(&s);
        struct vhci_io io={&c,capture_emit,capture_entropy,capture_log};
        s.diag_enabled=1;
        assert(!vhci_feed(&s,&io,diag,split));assert(!vhci_feed(&s,&io,diag+split,3-split));
        assert(!s.used && !s.diag_enabled && s.diag_requests==1 && !c.emits);
        assert(!memcmp(s.last_diag,diag,3));assert(!vhci_feed(&s,&io,diag,3));
        assert(s.diag_requests==2 && !c.emits);
        assert(!send_cmd(&s,&c,0x0c03,0,0));assert(s.diag_requests==2);
    }
    for(unsigned char bad=0;bad<2;bad++) {
        struct vhci s;struct capture c={0};vhci_init(&s);
        struct vhci_io io={&c,capture_emit,capture_entropy,capture_log};
        uint8_t invalid[]={7,bad?0xf0:0xf1,bad?1:0};
        assert(vhci_feed(&s,&io,invalid,3)==-1 && s.failed && !c.emits && !s.diag_requests);
    }
}
static void test_identity_and_capabilities(void) {
    struct vhci s; struct capture c={0}; vhci_init(&s);
    assert(send_cmd(&s,&c,0x1009,0,0)==0x0c);
    reset(&s,&c);
    assert(send_cmd(&s,&c,0x1001,0,0)==0 && c.length==15 && c.event[7]==9);
    assert(send_cmd(&s,&c,0x1009,0,0)==0 && c.length==13);
    assert(!memcmp(c.event+7,(uint8_t[]){1,2,0x7c,0,0,2},6));
    assert(send_cmd(&s,&c,0x1002,0,0)==0 && c.length==71);
    uint8_t supported[64]; memcpy(supported,c.event+7,64);
    assert((supported[20]&0x10)!=0); /* BSA's observed startup gate. */
    assert(!(supported[27]&0x40)); /* No LE Encrypt claim. */
    assert(!(supported[26]&0x10)); /* No LE connection creation claim. */
    unsigned bits=0;
    for (size_t i=0;i<64;++i) for (unsigned b=0;b<8;++b) bits+=(supported[i]>>b)&1;
    assert(bits==sizeof commands/sizeof commands[0]-1);
    assert(send_cmd(&s,&c,0x1003,0,0)==0 && c.length==15);
    assert(c.event[11]==0x60 && c.event[14]==0x80);
    assert(send_cmd(&s,&c,0x2003,0,0)==0);
    assert(!memcmp(c.event+7,(uint8_t[8]){0},8));
    assert(send_cmd(&s,&c,0x1005,0,0)==0 && c.length==14);
    assert(send_cmd(&s,&c,0x2002,0,0)==0 && c.length==10);
    assert(send_cmd(&s,&c,0x201c,0,0)==0 && c.event[7]==0x11);
    assert(send_cmd(&s,&c,0x1408,(uint8_t[]){1,0},2)==2 && c.length==10);
    assert(c.event[7]==1 && c.event[8]==0 && c.event[9]==0);
    assert(send_cmd(&s,&c,0x1408,(uint8_t[]){255,255},2)==0x12);
    assert(send_cmd(&s,&c,0xfc4c,(uint8_t[]){0,0,0,0,1},5)==1);
    assert(send_cmd(&s,&c,0xfc2e,0,0)==1);
    assert(send_cmd(&s,&c,0xffff,0,0)==1);
    assert(send_cmd(&s,&c,0x0c03,(uint8_t[]){0},1)==0x12);
}
static void test_backing_and_validation(void) {
    struct vhci s; struct capture c; reset(&s,&c);
    const uint8_t mask[]={0,1,2,3,4,5,6,7};
    assert(!send_cmd(&s,&c,0x0c01,mask,8) && !memcmp(s.event_mask,mask,8));
    assert(!send_cmd(&s,&c,0x2001,mask,8) && !memcmp(s.le_event_mask,mask,8));
    assert(!send_cmd(&s,&c,0x0c63,mask,8) && !memcmp(s.event_mask2,mask,8));
    assert(!send_cmd(&s,&c,0x0c6d,(uint8_t[]){1,0},2) && s.host_le==1);
    assert(!send_cmd(&s,&c,0x0c6c,0,0) && c.event[7]==1 && c.event[8]==0);
    assert(!send_cmd(&s,&c,0x1004,(uint8_t[]){1},1) && c.event[9]==2);
    assert(send_cmd(&s,&c,0x1004,(uint8_t[]){2},1)==0x12);
    assert(send_cmd(&s,&c,0x0c6d,(uint8_t[]){1,1},2)==0x11 && s.host_le==1);
    assert(send_cmd(&s,&c,0x0c1a,(uint8_t[]){1},1)==0x11);
    assert(!send_cmd(&s,&c,0x0c19,0,0) && c.event[7]==0);
    uint8_t name[248]; memset(name,'A',sizeof name);
    assert(!send_cmd(&s,&c,0x0c13,name,248));
    assert(!send_cmd(&s,&c,0x0c14,0,0) && c.length==255 && !memcmp(c.event+7,name,248));
    assert(!send_cmd(&s,&c,0x0c24,(uint8_t[]){1,2,3},3));
    assert(!send_cmd(&s,&c,0x0c23,0,0) && !memcmp(c.event+7,(uint8_t[]){1,2,3},3));
    uint8_t adv[15]={0xa0,0,0xb0,0,3,0,0,0,0,0,0,0,0,7,0};
    assert(!send_cmd(&s,&c,0x2006,adv,15) && !memcmp(s.adv_params,adv,15));
    adv[4]=0; assert(send_cmd(&s,&c,0x2006,adv,15)==0x11 && s.adv_params[4]==3);
    adv[4]=3; adv[13]=8; assert(send_cmd(&s,&c,0x2006,adv,15)==0x12);
    adv[13]=7; adv[0]=0x1f; assert(send_cmd(&s,&c,0x2006,adv,15)==0x12);
    adv[0]=0x20;adv[2]=0x20;
    assert(!send_cmd(&s,&c,0x2006,adv,15) && le16(s.adv_params)==0x20 && le16(s.adv_params+2)==0x20);
    const uint8_t address[]={0xfe,0xff,0xff,0xff,0xff,0xff};
    assert(!send_cmd(&s,&c,0xfc01,address,6));
    assert(!send_cmd(&s,&c,0x1009,0,0) && !memcmp(c.event+7,address,6));
    uint8_t data[32]={3,1,2,3};
    assert(!send_cmd(&s,&c,0x2008,data,32) && !memcmp(s.adv_data,data,32));
    assert(!send_cmd(&s,&c,0x2009,data,32) && !memcmp(s.scan_response,data,32));
    data[0]=32; assert(send_cmd(&s,&c,0x2008,data,32)==0x12 && s.adv_data[0]==3);
    data[0]=1; data[1]=9; assert(!send_cmd(&s,&c,0x2008,data,32));
    assert(s.adv_data[0]==1 && s.adv_data[1]==9 && s.adv_data[2]==0);
    assert(!send_cmd(&s,&c,0x200a,(uint8_t[]){1},1) && s.advertising);
    assert(send_cmd(&s,&c,0x2006,s.adv_params,15)==0x0c);
    assert(send_cmd(&s,&c,0x200c,(uint8_t[]){1,1},2)==0x0c && !s.scanning);
    assert(!send_cmd(&s,&c,0x200a,(uint8_t[]){0},1) && !s.advertising);
    uint8_t scan[7]={0,0x20,0,0x10,0,0,0};
    assert(!send_cmd(&s,&c,0x200b,scan,7) && !memcmp(s.scan_params,scan,7));
    scan[0]=1; assert(send_cmd(&s,&c,0x200b,scan,7)==0x11);
    scan[0]=0; scan[3]=0x30; assert(send_cmd(&s,&c,0x200b,scan,7)==0x12);
    assert(!send_cmd(&s,&c,0x200c,(uint8_t[]){1,1},2) && s.scanning && s.duplicate_filter);
    assert(send_cmd(&s,&c,0x200b,s.scan_params,7)==0x0c);
    assert(send_cmd(&s,&c,0x200a,(uint8_t[]){1},1)==0x0c && !s.advertising);
    assert(send_cmd(&s,&c,0x200c,(uint8_t[]){1,2},2)==0x12 && s.scanning);
    assert(!send_cmd(&s,&c,0x0c03,0,0));
    assert(!s.advertising && !s.scanning && !s.host_le && s.adv_data[0]==0 && s.resets==2);
}
static void test_entropy_and_lengths(void) {
    struct vhci s; struct capture c; reset(&s,&c);
    assert(!send_cmd(&s,&c,0x2018,0,0) && c.length==15 && c.entropy_calls==1);
    uint8_t first[8]; memcpy(first,c.event+7,8);
    assert(!send_cmd(&s,&c,0x2018,0,0) && memcmp(first,c.event+7,8));
    c.entropy_failure=1;
    assert(send_cmd(&s,&c,0x2018,0,0)==3 && !memcmp(c.event+7,(uint8_t[8]){0},8));
    for (size_t i=0;i<sizeof commands/sizeof commands[0];++i) {
        struct vhci before=s;
        uint8_t p[255]={0};
        size_t bad=commands[i].length ? commands[i].length-1 : 1;
        assert(send_cmd(&s,&c,commands[i].opcode,p,bad)==0x12);
        assert(!memcmp(&s,&before,offsetof(struct vhci,frame)));
    }
    /* Exhaust all opcodes: unknowns must never mutate state or report success. */
    for (unsigned op=0;op<=65535;++op) {
        int known=0;
        for (size_t i=0;i<sizeof commands/sizeof commands[0];++i)
            known|=commands[i].opcode==op;
        if (!known) {
            struct vhci before=s;
            assert(send_cmd(&s,&c,(uint16_t)op,0,0)==1);
            assert(!memcmp(&s,&before,offsetof(struct vhci,frame)));
        }
    }
}
int main(void) {
    assert(vhci_log_due(1) && vhci_log_due(1024) && !vhci_log_due(1025) && vhci_log_due(2048));
    test_diag_disable_no_reply();
    test_framing(); test_identity_and_capabilities();
    test_backing_and_validation(); test_entropy_and_lengths();
    puts("PASS: H4 splits/bytes/255-byte payload, full opcode rejection, state, capabilities, errors, entropy stub");
    return 0;
}
