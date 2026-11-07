/* SPDX-License-Identifier: MIT */
/* Read-only client for ORIGINAL mcmn command9/config and command2/insert state.
 * Evidence: libInfraMediaCommon+394d0/+3abd8, mcmn_drv+1990/+1e3c.
 * This never registers a provider, sets configuration, powers media, or ACKs CP. */
typedef unsigned long size_t;
extern int printf(const char *, ...);
extern int osal_dynamic_id(unsigned int,unsigned int,unsigned long);
extern int osal_valloc_msg_wait(unsigned int,void **,unsigned int,int);
extern int osal_snd_msg(unsigned int,void *);
extern int osal_rcv_msg_tmo(unsigned int,void **,long);
extern int osal_free_msg(unsigned int,void *);
extern unsigned int osal_msg_size(void *);
extern unsigned int osal_get_msg_src(void *);
extern int strcmp(const char *,const char *);
extern int __libc_start_main(int (*)(int,char **),int,char **,
                            void (*)(void),void (*)(void),void (*)(void),void *);
#define MCMN_SID 0x80d9016eu
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int u32(const unsigned char *p){return u16(p)|u16(p+2)<<16;}
static void put16(unsigned char *p,unsigned int n){p[0]=n;p[1]=n>>8;}
static void put32(unsigned char *p,unsigned int n){for(unsigned int i=0;i<4;i++)p[i]=n>>(8*i);}
static void raw_log(const char *kind,unsigned int command,const unsigned char *p,unsigned int bytes){
    printf("MCMN_QUERY_%s command=%u bytes=%u raw=",kind,command,bytes);
    for(unsigned int i=0;i<bytes;i++)printf("%02x",p[i]);
    printf("\n");
}
static int query(unsigned int queue,unsigned int command,unsigned int target){
    unsigned int body=command==9?112:8,bytes=24+body;
    void *request=0;int rc=osal_valloc_msg_wait(MCMN_SID,&request,bytes,1);
    printf("MCMN_QUERY_ALLOC command=%u rc=%d pointer=%p\n",command,rc,request);
    if(rc || !request){
        if(request){int freed=osal_free_msg(MCMN_SID,request);printf("MCMN_QUERY_PARTIAL_ALLOC_FREE rc=%d\n",freed);}
        return 3;
    }
    unsigned char *p=request;
    for(unsigned int i=0;i<bytes;i++)p[i]=0;
    put32(p,command);put16(p+4,1);put16(p+6,body);put32(p+8,queue);
    if(command==2)put32(p+24,target);
    raw_log("REQUEST",command,p,bytes);
    rc=osal_snd_msg(MCMN_SID,request);
    printf("MCMN_QUERY_SEND command=%u destination=%#x rc=%d\n",command,MCMN_SID,rc);
    if(rc){
        int freed=osal_free_msg(MCMN_SID,request);
        printf("MCMN_QUERY_SEND_REJECT_FREE rc=%d\n",freed);return freed?6:4;
    }
    /* Ownership handed to the real driver. Never touch/free request again. The
     * original library waits forever; this diagnostic uses a bounded timeout. */
    void *reply=0;rc=osal_rcv_msg_tmo(queue,&reply,5000);
    printf("MCMN_QUERY_RECEIVE command=%u queue=%#x rc=%d reply=%p\n",command,queue,rc,reply);
    if(rc || !reply){
        if(reply){int freed=osal_free_msg(queue,reply);printf("MCMN_QUERY_ERROR_REPLY_FREE rc=%d\n",freed);}
        printf("MCMN_QUERY_INCOMPLETE command=%u sent_owner_not_reclaimed=1 late_reply_unknown=1\n",command);
        return 5;
    }
    unsigned int actual=osal_msg_size(reply),source=osal_get_msg_src(reply);
    printf("MCMN_QUERY_REPLY_ID command=%u source=%#x bytes=%u\n",command,source,actual);
    int valid=actual==bytes;
    p=reply;
    if(actual<=136)raw_log("REPLY",command,p,actual);
    if(valid)valid=u32(p)==command && u16(p+4)==1 && u16(p+6)==body && u32(p+8)==queue;
    if(valid){
        unsigned int status=u32(p+12);
        printf("MCMN_QUERY_RESULT command=%u target=%#x service_status=%#x\n",command,target,status);
        if(!status && command==9){
            for(unsigned int i=0;i<3;i++){
                const unsigned char *entry=p+24+4+i*36;
                printf("MCMN_QUERY_ENTRY rm=%u flags=%#x mmc_target=%#x\n",i+1,u32(entry+8),u32(entry+16));
            }
        }else if(command==2){
            if(!status)printf("MCMN_QUERY_INSERT_STATE target=%#x enum=%u not_card_io_proof=1\n",target,u32(p+28));
            else printf("MCMN_QUERY_SERVICE_REJECT target=%#x status=%#x\n",target,status);
        }
    }
    int freed=osal_free_msg(queue,reply);
    printf("MCMN_QUERY_REPLY_FREE command=%u rc=%d layout_valid=%d\n",command,freed,valid);
    return freed?6:valid?0:7;
}
/* cmd3: subscribe as a client and see whether the driver replays its cached 7-byte
 * front-end state packet to us. This tests the cache/replay path directly instead of
 * inferring it from "the mount did not happen". */
static int subscribe(unsigned int queue){
    unsigned int bytes=28;void *request=0;
    int rc=osal_valloc_msg_wait(MCMN_SID,&request,bytes,1);
    printf("MCMN_SUBSCRIBE_ALLOC rc=%d pointer=%p\n",rc,request);
    if(rc || !request){if(request)printf("MCMN_SUBSCRIBE_FREE rc=%d\n",osal_free_msg(MCMN_SID,request));return 3;}
    unsigned char *p=request;
    for(unsigned int i=0;i<bytes;i++)p[i]=0;
    put32(p,3);put16(p+4,1);put16(p+6,4);put32(p+8,queue);put32(p+24,queue);
    raw_log("SUBSCRIBE",3,p,bytes);
    rc=osal_snd_msg(MCMN_SID,request);
    printf("MCMN_SUBSCRIBE_SEND destination=%#x rc=%d\n",MCMN_SID,rc);
    if(rc){int freed=osal_free_msg(MCMN_SID,request);printf("MCMN_SUBSCRIBE_REJECT_FREE rc=%d\n",freed);return 4;}
    void *reply=0;rc=osal_rcv_msg_tmo(queue,&reply,5000);
    printf("MCMN_SUBSCRIBE_REPLY queue=%#x rc=%d reply=%p\n",queue,rc,reply);
    if(!rc && reply){
        unsigned int actual=osal_msg_size(reply);
        printf("MCMN_SUBSCRIBE_REPLY_SIZE bytes=%u\n",actual);
        if(actual<=136)raw_log("SUBSCRIBE_REPLY",3,reply,actual);
        printf("MCMN_SUBSCRIBE_REPLY_FREE rc=%d\n",osal_free_msg(queue,reply));
    }
    /* Now wait for the driver's replay of the cached front-end state. */
    void *state=0;rc=osal_rcv_msg_tmo(queue,&state,8000);
    printf("MCMN_SUBSCRIBE_STATE queue=%#x rc=%d message=%p\n",queue,rc,state);
    if(!rc && state){
        unsigned int actual=osal_msg_size(state);
        printf("MCMN_SUBSCRIBE_STATE_SIZE bytes=%u source=%#x\n",actual,osal_get_msg_src(state));
        raw_log("STATE",0,state,actual>24?24:actual);
        printf("MCMN_SUBSCRIBE_STATE_FREE rc=%d\n",osal_free_msg(queue,state));
    }
    return 0;
}

static int run(int argc,char **argv){
    if(argc==2 && !strcmp(argv[1],"subscribe")){
        unsigned int q=0;int rc=osal_dynamic_id(0x2a,0xd5,(unsigned long)&q);
        printf("MCMN_SUBSCRIBE_QUEUE_ALLOC rc=%d queue=%#x\n",rc,q);
        if(rc || !q)return 3;
        int result=subscribe(q);
        int closed=osal_dynamic_id(0x4a,0,q);
        printf("MCMN_SUBSCRIBE_QUEUE_RELEASE queue=%#x rc=%d subscribe_rc=%d\n",q,closed,result);
        return closed?6:result;
    }
    (void)argv;
    if(argc!=1){printf("MCMN_QUERY_USAGE no-arguments-readonly|subscribe\n");return 2;}
    unsigned int queue=0;
    int rc=osal_dynamic_id(0x2a,0xd5,(unsigned long)&queue);
    printf("MCMN_QUERY_QUEUE_ALLOC rc=%d queue=%#x\n",rc,queue);
    if(rc || !queue)return 3;
    int result=query(queue,9,0);
    for(unsigned int target=0x101;!result && target<=0x103;target++)result=query(queue,2,target);
    int closed=osal_dynamic_id(0x4a,0,queue);
    printf("MCMN_QUERY_QUEUE_RELEASE queue=%#x rc=%d query_rc=%d\n",queue,closed,result);
    return closed?6:result;
}
#ifndef MCMN_QUERY_TEST
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
