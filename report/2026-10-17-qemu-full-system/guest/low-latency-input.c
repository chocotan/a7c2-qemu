/* Explicit mailbox-v1 functional transport; original InfraInput 20-byte API. */
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/file.h>
extern int osal_valloc_msg_wait(unsigned,void **,unsigned,int);
extern void osal_set_msg_src(void *,unsigned);
extern unsigned osal_get_msg_src(void *);
extern int osal_snd_msg(unsigned,void *);
extern int osal_free_msg(unsigned,void *);
#define PHYSICAL UINT64_C(0x41ef00000)
#define MAGIC UINT64_C(0x31504e494c374137)
#define QUEUE 0x807a0020u
#define SOURCE 0x92840747u
struct mailbox {
    uint64_t magic,cookie[2],heartbeat;
    uint32_t ready,pid;
    uint64_t submit,ack;
    uint32_t result,held_count;
    uint32_t command[8];
};
_Static_assert(offsetof(struct mailbox,submit)==40,"submit ABI");
_Static_assert(offsetof(struct mailbox,command)==64,"command ABI");
static const unsigned contacts[]={0x1ab,0x1ac,3,0x30,0x15,0x1af,0x1f8,0x66,
    0x1f7,0x0f000004,0x7095,0x1f1,0xa7,0x1f0};
static uint32_t held;
static volatile sig_atomic_t stopping;
static void stop_signal(int sig){(void)sig;stopping=1;}
static uint32_t checksum(const uint32_t *words){
    uint32_t value=2166136261u;
    const unsigned char *bytes=(const unsigned char *)words;
    for(unsigned i=0;i<28;i++)value=(value^bytes[i])*16777619u;
    return value;
}
static int contact(unsigned code){
    for(unsigned i=0;i<sizeof contacts/sizeof *contacts;i++)if(contacts[i]==code)return (int)i;
    return -1;
}
static int valid(unsigned code,unsigned status){
    if(contact(code)>=0)return status<=1;
    if(code==0x10000013 || code==0x10000016 || code==0x1000001c || code==0x1000001d)
        return status && ((int32_t)status>=-32768 && (int32_t)status<=32768);
    if(code==0x71c9)return status>=1 && status<=3;
    if(code==0x7025)return status==1 || status==3 || status==4 || status==5 || status==6 || status==7 || status==19 || status==20;
    return 0;
}
static int send_original(unsigned code,unsigned status,uint64_t sequence){
    void *message=0;
    int index=contact(code);
    int rc=osal_valloc_msg_wait(QUEUE,&message,20,1);
    int allocation_errno=errno;
    if(rc || !message){
        printf("LOW_INPUT_ALLOC_FAILED seq=%llu code=%#x status=%d alloc_rc=%d errno=%d message=%p held=%u\n",
            (unsigned long long)sequence,code,(int32_t)status,rc,allocation_errno,message,held);
        return 10;
    }
    unsigned body[5]={code,0,status,0,1};
    memcpy(message,body,sizeof body);
    osal_set_msg_src(message,SOURCE);
    if(osal_get_msg_src(message)!=SOURCE){
        return osal_free_msg(QUEUE,message)?13:11;
    }
    /* Only snd can transfer a press; earlier failures must not invent a held contact. */
    if(index>=0 && status)held|=1u<<index;
    rc=osal_snd_msg(QUEUE,message);
    /* snd transfers ownership; neither ACK nor log reads message after this point. */
    printf("LOW_INPUT_SEND seq=%llu code=%#x status=%d result=%d bytes=20\n",
           (unsigned long long)sequence,code,(int32_t)status,rc);
    if(rc)return osal_free_msg(QUEUE,message)?13:12;
    if(index>=0 && !status)held&=~(1u<<index);
    return 0;
}
static int release_all(uint64_t sequence){
    int first=0;
    /* Full shutter leaves before half, then other contacts in reverse order. */
    const unsigned full=12;
    if(held&(1u<<full)){int rc=send_original(contacts[full],0,sequence);if(rc)first=rc;}
    for(int i=(int)(sizeof contacts/sizeof *contacts)-1;i>=0;i--){
        if((unsigned)i==full || !(held&(1u<<i)))continue;
        int rc=send_original(contacts[i],0,sequence);if(rc && !first)first=rc;
    }
    return first;
}
static int execute(const uint32_t *words,uint64_t sequence){
    unsigned op=words[0],code=words[1],status=words[2],pulse=words[3];
    if(words[4]!=32 || words[5] || words[6] || words[7]!=checksum(words))return 2;
    if(op==3 || op==4){
        if(code || status || pulse)return 2;
        int rc=release_all(sequence);
        if(op==4 && !rc)stopping=1;
        return rc;
    }
    if(op==5){
        if(code || status || pulse!=50 || held)return 2;
        const unsigned codes[4]={0x1f1,0xa7,0xa7,0x1f1},statuses[4]={1,1,0,0};
        int failure=0;
        for(unsigned i=0;i<4;i++){
            if(stopping){failure=14;break;}
            failure=send_original(codes[i],statuses[i],sequence);
            if(failure)break;
            struct timespec delay={0,50000000},remaining;
            while(nanosleep(&delay,&remaining)){
                if(errno!=EINTR || stopping){failure=14;break;}
                delay=remaining;
            }
            if(failure)break;
        }
        int cleanup=release_all(sequence);
        return cleanup?cleanup:failure;
    }
    if((op!=1 && op!=2) || !valid(code,status))return 2;
    int index=contact(code);
    if(op==2){
        if(index<0 || status!=1 || pulse!=50 || held)return 2;
        int pressed=send_original(code,1,sequence);
        int sleep_error=0;
        if(!pressed){
            struct timespec delay={0,50000000},remaining;
            while(nanosleep(&delay,&remaining)){
                if(errno!=EINTR){sleep_error=1;break;}
                if(stopping)break;
                delay=remaining;
            }
        }
        int released=(held&(1u<<index))?send_original(code,0,sequence):0;
        return released?released:pressed?pressed:sleep_error?14:0;
    }
    if(pulse)return 2;
    if(index>=0 && status && (held&(1u<<index)))return 2;
    if(index>=0 && !status && !(held&(1u<<index)))return 2;
    return send_original(code,status,sequence);
}
#ifndef LOW_INPUT_TEST
static uint64_t monotonic_ms(void){
    struct timespec now;
    if(clock_gettime(CLOCK_MONOTONIC,&now))return 0;
    return (uint64_t)now.tv_sec*1000+(uint64_t)now.tv_nsec/1000000;
}
static int run(int argc,char **argv){
    if(argc!=2 || strlen(argv[1])!=32)return 2;
    unsigned char cookie[16];
    for(unsigned i=0;i<32;i++)if(!((argv[1][i]>='0' && argv[1][i]<='9') || (argv[1][i]>='a' && argv[1][i]<='f')))return 2;
    for(unsigned i=0;i<16;i++){
        unsigned byte;
        if(sscanf(argv[1]+i*2,"%2x",&byte)!=1)return 2;
        cookie[i]=(unsigned char)byte;
    }
    int lock=open("/tmp/low-latency-input.lock",O_CREAT|O_RDWR|O_NOFOLLOW,0600);
    if(lock<0 || flock(lock,LOCK_EX|LOCK_NB))return 3;
    int fd=open("/dev/mem",O_RDWR|O_SYNC);
    if(fd<0)return 4;
    struct mailbox *box=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_SHARED,fd,PHYSICAL);
    close(fd);
    if(box==MAP_FAILED)return 4;
    if(box->magic!=MAGIC || memcmp(box->cookie,cookie,16) || box->submit || box->ack || box->ready)return 5;
    signal(SIGTERM,stop_signal);signal(SIGINT,stop_signal);signal(SIGHUP,stop_signal);
    setvbuf(stdout,0,_IOLBF,0);
    box->pid=(uint32_t)getpid();
    __atomic_store_n(&box->ready,1,__ATOMIC_RELEASE);
    uint64_t last=0,beat=box->heartbeat,changed=monotonic_ms();
    int fault=0;
    while(!stopping){
        uint64_t now=monotonic_ms();
        uint64_t current=__atomic_load_n(&box->heartbeat,__ATOMIC_ACQUIRE);
        if(current!=beat){beat=current;changed=now;}
        if(held && now-changed>1000){fault=20;break;}
        if(box->magic!=MAGIC || memcmp(box->cookie,cookie,16)){fault=21;break;}
        uint64_t sequence=__atomic_load_n(&box->submit,__ATOMIC_ACQUIRE);
        if(sequence==last){struct timespec delay={0,1000000};nanosleep(&delay,0);continue;}
        if(sequence!=last+1){fault=22;break;}
        uint32_t words[8];memcpy(words,box->command,sizeof words);
        int rc=execute(words,sequence);
        box->result=(uint32_t)rc;box->held_count=(uint32_t)__builtin_popcount(held);
        __atomic_store_n(&box->ack,sequence,__ATOMIC_RELEASE);
        last=sequence;
        if(rc){fault=rc;break;}
    }
    int cleanup=release_all(last);
    if(cleanup && !fault)fault=cleanup;
    box->held_count=(uint32_t)__builtin_popcount(held);
    if(fault)box->result=(uint32_t)fault;
    __atomic_store_n(&box->ready,fault?3:2,__ATOMIC_RELEASE);
    printf("LOW_INPUT_EXIT rc=%d held=%u last=%llu\n",fault,box->held_count,(unsigned long long)last);
    munmap(box,4096);close(lock);
    return fault?1:0;
}
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start,%function\n_start:\nmov x0,sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
#endif
