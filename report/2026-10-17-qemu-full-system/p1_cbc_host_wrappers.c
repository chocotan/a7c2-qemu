#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <openssl/evp.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>
#include "p1-trust-key.h"
#include "p1_cbc_runtime_binding.h"
#ifndef TEST_ASSET_DIR
#error TEST_ASSET_DIR required
#endif
#ifndef TEST_CRYPTO
#error TEST_CRYPTO required
#endif
#ifndef TEST_BAD_DIR
#error TEST_BAD_DIR required
#endif
static unsigned checks;
#define C(x) do {checks++;if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);abort();}}while(0)
typedef struct {const char *file;void *base;const char *symbol;void *address;} Info;
extern void *dlsym(void *,const char *);
static unsigned char sd[0x1e040];
static __thread unsigned long host_caller;
static int init_identity=1,host_selected,mapped=1,wrong_path;
static unsigned char *message;
static unsigned char reuse_storage[1064];
static int force_reuse;
static unsigned capacity;
static int alloc_calls,send_calls,free_calls,copy_calls,alloc_rc,send_rc,heap_fail,heap_short,damage,evp_fail;
static int ctor_opens,packet_reads,ordinary_reads,copy_noop;
static unsigned char *ordinary;
static int selected(void){return host_selected;}
static void logline(const char *s){(void)s;errno=109;}
int dladdr(const void *p,Info *i){(void)p;i->base=sd;i->file=wrong_path?"/wrong.so":"/usr/lib/libsdfileinputupdaterapi.so";return mapped;}
static void *next(const char *);
static int native_alloc(unsigned,void **,unsigned,int);
static int native_send(unsigned,void *);
static int native_free(unsigned,void *);
static void *native_copy(void *,const void *,size_t);
#define __builtin_return_address(n) ((void *)(sd+host_caller))
#define memcpy observed_memcpy
#define strncmp observed_strncmp
#define osal_valloc_msg_wait observed_allocate
#define osal_snd_sync_msg observed_send
#define osal_free_msg observed_free
#define SHA1_Final observed_SHA1_Final
#define SHA256 observed_SHA256
#define RSA_verify observed_RSA_verify
#define _ZN7Updater15DecryptorModule9verifySumEv observed_verify
#include "p1_cbc_host_generated.inc"
#undef memcpy
#undef strncmp
#undef osal_valloc_msg_wait
#undef osal_snd_sync_msg
#undef osal_free_msg
#undef SHA1_Final
#undef SHA256
#undef RSA_verify
#undef _ZN7Updater15DecryptorModule9verifySumEv
#undef __builtin_return_address
/* Include the current candidate implementation, exposing counters only for bounded-limit injection. */
#undef _POSIX_C_SOURCE
#include "p1_cbc_core.c"
#include "p1_cbc_stream.c"
int __real_EVP_DecryptUpdate(EVP_CIPHER_CTX *,unsigned char *,int *,const unsigned char *,int);
int __wrap_EVP_DecryptUpdate(EVP_CIPHER_CTX *c,unsigned char *d,int *n,const unsigned char *s,int bytes) {
    int rc=__real_EVP_DecryptUpdate(c,d,n,s,bytes);return evp_fail?0:rc;
}
static int ropen(const char *path,int flags,...) {
    if(!strcmp(path,"/proc/self/mem"))return open(path,flags);
    ctor_opens++;char target[1024];
    const char *base="/simulation/p1-cbc-model/";
    if(!strncmp(path,base,strlen(base)))snprintf(target,sizeof target,"%s/%s",TEST_ASSET_DIR,path+strlen(base));
    else if(!strcmp(path,"/usr/lib/libcrypto.so.1.1"))snprintf(target,sizeof target,"%s",TEST_CRYPTO);
    else {errno=ENOENT;return -1;}
    const char *bad=damage==1?"profile":damage==2||damage==3?"manifest":damage==4?"libcrypto.so.1.1":damage==5?"source-receipt":damage==6?"code-receipt":0;
    if(bad && strstr(path,bad)){snprintf(target,sizeof target,"%s/bad-%d",TEST_BAD_DIR,damage);}
    return open(target,flags);
}
static long rpread(int fd,void *out,unsigned long n,long long offset) {
    uintptr_t a=(uintptr_t)offset,m=(uintptr_t)message;
    if(message && a>=m && a<m+capacity){packet_reads++;errno=EIO;return -1;}
    ordinary_reads++;
    if(a==(uintptr_t)ordinary && heap_fail){errno=EIO;return -1;}
    return pread64(fd,out,a==(uintptr_t)ordinary && heap_short?n-1:n,offset);
}
static int native_alloc(unsigned sid,void **out,unsigned n,int wait) {
    (void)sid;C(errno==33 && wait==1);alloc_calls++;capacity=n;
    message=alloc_rc?NULL:force_reuse?reuse_storage:malloc(n);*out=message;errno=81;return alloc_rc;
}
static const unsigned char native_opaque[8]={0x60,0x90,0x01,0x34,0x7f,0,0,0};
static int native_send(unsigned sid,void *p) {
    C(errno==33 && sid==P1_TRUST_SID && p==message);send_calls++;
    if(capacity==56){uint64_t h[5]={7,0,0,0,8};memcpy(message,h,40);memcpy(message+40,native_opaque,8);}
    errno=82;return send_rc;
}
static int native_free(unsigned sid,void *p) {
    C(errno==33 && (sid==P1_TRUST_SID || sid==P1_TRUST_SID+1) && p==message);
    free_calls++;if(p!=reuse_storage)free(p);message=NULL;errno=83;return -9;
}
static void *native_copy(void *d,const void *s,size_t n) {
    C(errno==33);copy_calls++;if(!copy_noop)memcpy(d,s,n);errno=84;return d;
}
static void *next(const char *name) {
    if(!strcmp(name,"open"))return ropen;
    if(!strcmp(name,"pread64"))return rpread;
    if(!strcmp(name,"close"))return close;
    if(!strcmp(name,"memcpy"))return native_copy;
    if(!strcmp(name,"osal_valloc_msg_wait"))return native_alloc;
    if(!strcmp(name,"osal_snd_sync_msg"))return native_send;
    if(!strcmp(name,"osal_free_msg"))return native_free;
    return dlsym((void *)-1,name);
}
static void reset(int enabled) {
    C(!message);p1_fc_stop();memset(&p1_fc,0,sizeof p1_fc);p1_fc_lines=0;
    p1_fc_native_other=0;p1_fc_other_pid=p1_fc_other_conflict=force_reuse=0;
    memset(&passive_borrow,0,sizeof passive_borrow);memset(&trust_borrow,0,sizeof trust_borrow);
    host_selected=1;mapped=1;wrong_path=0;init_identity=trust_identity=passive_identity=1;
    damage=heap_fail=heap_short=send_rc=alloc_rc=evp_fail=copy_noop=0;ordinary=NULL;
    unsetenv("A7C2_P1_TRUST_PROFILE");unsetenv("A7C2_P1_CBC_PROFILE");
    if(enabled)setenv("A7C2_P1_CBC_PROFILE",P1_NS_PROFILE,1);
    errno=33;p1_fc_start();C(errno==33 && p1_fc.mode==(enabled?1:0));
}
static void allocate(unsigned bytes) {
    host_caller=0x93d0;void *out=NULL;errno=33;int before=alloc_calls;
    C(observed_allocate(P1_TRUST_SID,&out,bytes,1)==alloc_rc && errno==81 && out==message);
    C(alloc_calls==before+1);
}
static void cp(unsigned long site,void *d,const void *s,size_t n) {
    host_caller=site;errno=33;int before=copy_calls;
    C(observed_memcpy(d,s,n)==d && errno==84 && copy_calls==before+1);
}
static void release(void) {
    host_caller=0x949c;errno=33;int before=free_calls;
    C(observed_free(P1_TRUST_SID,message)==-9 && errno==83 && free_calls==before+1);
}
static int send_at(unsigned long site) {
    host_caller=site;errno=33;return observed_send(P1_TRUST_SID,message);
}
static void prepare(unsigned op,const unsigned char *in,size_t n) {
    allocate((unsigned)n+40);uint64_t h[5]={op,0,op==2?8:0,0,n};
    if(op==3)memcpy(h+1,native_opaque,8);memcpy(message,h,40);
    ordinary=(unsigned char *)in;cp(0x9428,message+40,in,n);ordinary=NULL;
}
static unsigned char iv[16],cipher[1024],plain[1024],out[1024];
static void init_stream(void) {
    int before=send_calls;prepare(2,iv,16);C(!send_at(0x9434) && errno==82 && send_calls==before+1);
    uint64_t status;memcpy(&status,message,8);C(status==7);
    ordinary=out;cp(0x9460,out,message+40,8);ordinary=NULL;
    C(!memcmp(out,native_opaque,8));C(p1_fc.stream->stream==1);
    C(!memcmp(p1_fc.stream->opaque,native_opaque,8));release();
}
static void unchanged_reject(unsigned long site) {
    unsigned char before[1064];memcpy(before,message,capacity);int count=send_calls;
    C(send_at(site)==-1 && errno==71 && send_calls==count);
    C(!memcmp(before,message,capacity));
}
static void *thread_reject(void *unused){(void)unused;unchanged_reject(0x9434);return NULL;}
static void *thread_init(void *unused){(void)unused;init_stream();C(p1_fc.tid==passive_tid());return NULL;}
int main(int argc,char **argv) {
    C(argc==4);FILE *f=fopen(argv[3],"rb");C(f && fread(iv,1,16,f)==16);fclose(f);
    f=fopen(argv[1],"rb");C(f && !fseek(f,512,SEEK_SET) && fread(cipher,1,1024,f)==1024);fclose(f);
    reset(0);int count=send_calls;
    for(int k=0;k<2;k++){send_rc=k?-71:0;allocate(552);memset(message,0x5a,552);
        C(send_at(0x9434)==send_rc && errno==82 && send_calls==count+k+1);release();}
    send_rc=0;
    setenv("A7C2_P1_CBC_PROFILE",P1_NS_PROFILE,1);C(p1_fc.mode==0); /* No runtime re-activation. */
    reset(1);pthread_t worker;C(!pthread_create(&worker,NULL,thread_init,NULL));C(!pthread_join(worker,NULL));
    C(p1_fc.tid!=passive_tid());reset(1);init_stream();
    count=send_calls;allocate(48);uint64_t cleanup[6]={4,0,0,0,8,0};memcpy(cleanup+5,native_opaque,8);
    memcpy(message,cleanup,48);C(!send_at(0x9434) && errno==82 && send_calls==count+1);
    C(!memcmp(message+40,native_opaque,8));release();
    f=fopen(argv[1],"rb");FILE *ref=fopen(argv[2],"rb");C(f && ref);
    C(!fseek(f,512,SEEK_SET));unsigned char block[1024];C(fread(block,1,512,ref)==512);
    size_t consumed=0,n=512;uint64_t sums=0;
    while(fread(cipher,1,n,f)==n) {
        C(fread(plain,1,n,ref)==n);int sends=send_calls;prepare(3,cipher,n);
        C(!send_at(0x9434) && errno==33 && send_calls==sends);uint64_t h[5];memcpy(h,message,40);
        C(h[0]==1 && h[4]==n);cp(0x9460,out,message+40,n);C(!memcmp(out,plain,n));
        if(!consumed)memcpy(block+512,out,512);else memcpy(block,out,1024);
        unsigned sum=0;for(unsigned j=2;j<1024;j+=2)sum=(sum+block[j]+((unsigned)block[j+1]<<8))&0xffff;
        C(sum==(unsigned)(block[0]|((unsigned)block[1]<<8)));sums+=sum;
        release();consumed+=n;n=1024;
    }
    fclose(f);fclose(ref);C(consumed>1024*1024 && p1_fc.stream->consumed==consumed);
    /* New native init frees only model state, keeps new native opaque and original output. */
    init_stream();C(p1_fc.stream->consumed==0);
    /* Explicit full-total and overflow boundaries without iterating the 1 GiB package. */
    for(int k=0;k<3;k++) {
        init_stream();p1_fc.stream->consumed=k==2?UINT64_MAX:P1_STOCK_CBC_BYTES-1024;
        p1_fc.stream->core->consumed=p1_fc.stream->consumed;prepare(3,cipher,1024);
        if(k==2)unchanged_reject(0x9434);
        else {C(!send_at(0x9434));C(p1_fc.stream->consumed==P1_STOCK_CBC_BYTES);}
        release();prepare(3,cipher,1024);unchanged_reject(0x9434);release();
    }
    for(int k=0;k<19;k++) {
        reset(1);init_stream();
        if(k==9){heap_fail=1;ordinary=cipher;}if(k==10){heap_short=1;ordinary=cipher;}
        prepare(3,cipher,512);heap_fail=heap_short=0;
        switch(k){
        case 0:((uint64_t *)message)[0]=9;break;
        case 1:message[8]^=1;break;
        case 2:((uint64_t *)message)[4]=513;break;
        case 3:((uint64_t *)message)[4]=UINT64_MAX;break;
        case 4:p1_fc.serial--;break;
        case 5:p1_fc.epoch++;break;
        case 6:p1_fc.pid++;break;
        case 7:p1_fc.tid++;break;
        case 8:passive_identity=0;break;
        case 11:cp(0x9428,message+40,cipher,512);break;
        case 12:message[40]^=1;break;
        case 13:evp_fail=1;break;
        case 14:p1_fc.stream->core->consumed=UINT64_MAX;break;
        case 15:p1_fc.stream->serial--;break;
        case 16:p1_fc.prepared=0;break;
        case 17:p1_fc.stream->stream=2;break;
        default:break;
        }
        unchanged_reject(k==18?0x9438:0x9434);
        p1_fc.pid=getpid();p1_fc.tid=passive_tid();passive_identity=1;evp_fail=0;
        /* Wrapper failures latch; next active request cannot fall back to native. */
        release();prepare(3,cipher,512);unchanged_reject(0x9434);release();
    }
    reset(1);init_stream();prepare(3,cipher,512);pthread_t t;C(!pthread_create(&t,NULL,thread_reject,NULL));C(!pthread_join(t,NULL));
    unchanged_reject(0x9434);release();init_stream();prepare(3,cipher,512);
    pid_t child=fork();C(child>=0);if(!child){unchanged_reject(0x9434);_exit(0);}int status;
    C(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    C(!send_at(0x9434));int after=send_calls;C(send_at(0x9434)==-1 && errno==71 && send_calls==after);
    void *retired=message;release();
    /* Released pointer must be refused without a CPU read or native send. */
    void *old=p1_fc.stream->packet;C(!old);host_caller=0x9434;errno=33;int reads=packet_reads;
    C(observed_send(P1_TRUST_SID,retired)==-1 && errno==71 && packet_reads==reads);
    for(int k=1;k<=6;k++){reset(0);damage=k;setenv("A7C2_P1_CBC_PROFILE",P1_NS_PROFILE,1);p1_fc_start();C(p1_fc.mode==-1);
        allocate(552);memset(message,0xa5,552);unchanged_reject(0x9434);release();}
    reset(0);setenv("A7C2_P1_CBC_PROFILE","unknown",1);p1_fc_start();C(p1_fc.mode==-1);
    allocate(552);memset(message,0,552);unchanged_reject(0x9434);release();
    reset(1);init_stream();force_reuse=1;allocate(48);void *other=message;
    C(p1_fc_native_other==other);host_caller=0x949c;errno=33;count=free_calls;
    C(observed_free(P1_TRUST_SID+1,message)==-9 && errno==83 && free_calls==count+1);
    C(!p1_fc_native_other);prepare(3,cipher,512);C(message==other && p1_fc.message==other);
    count=send_calls;C(!send_at(0x9434) && errno==33 && send_calls==count);
    C(p1_fc.stream->consumed==512);release();force_reuse=0;
    /* A second known allocation poisons the original lease without replacing it. */
    reset(1);init_stream();prepare(3,cipher,512);void *first=message;
    allocate(552);C(p1_fc.fault && p1_fc.message==first);release();
    message=first;capacity=552;unchanged_reject(0x9434);release();
    /* One outstanding other is the explicit limit; the second cannot overwrite it. */
    reset(1);init_stream();allocate(48);first=message;C(p1_fc_native_other==first);
    allocate(48);C(p1_fc_native_other==first && p1_fc_other_conflict && p1_fc.fault);
    unchanged_reject(0x9434);release();message=first;capacity=48;
    unchanged_reject(0x9434);release();C(!p1_fc_native_other);
    reset(1);alloc_rc=-17;allocate(552);C(!message && !p1_fc.message);alloc_rc=0;
    /* Init read failure and original native sync failure stay explicit, no CBC fallback. */
    for(int k=0;k<3;k++) {
        reset(1);prepare(2,iv,16);if(k==1)send_rc=-31;
        C(send_at(0x9434)==send_rc && errno==82);send_rc=0;
        ordinary=out;heap_fail=k==0;heap_short=k==2;cp(0x9460,out,message+40,8);ordinary=NULL;heap_fail=heap_short=0;
        release();prepare(3,cipher,512);unchanged_reject(0x9434);release();
    }
    /* A claimed model message must never fall through to a different native SID. */
    reset(1);init_stream();prepare(3,cipher,512);unsigned char sid_before[552];
    memcpy(sid_before,message,552);count=send_calls;host_caller=0x9434;errno=33;
    C(observed_send(P1_TRUST_SID+1,message)==-1 && errno==71 && send_calls==count);
    C(!memcmp(sid_before,message,552) && p1_fc.fault);release();
    /* Fixed receipt/config fields are checked as strings as well as actual ctor bytes. */
    reset(1);struct p1_ns_config cfg={P1_NS_PROFILE,P1_CBC_ASSET_SHA256,P1_NS_KEY_SHA,P1_CBC_KEY_SOURCE,P1_NS_CRYPTO_SHA,
        P1_MODEL_MANIFEST_SHA,P1_MODEL_SOURCE_SHA,P1_MODEL_CODE_SHA,1};
    for(int k=0;k<8;k++){struct p1_ns *s=p1_ns_new();struct p1_ns_config bad=cfg;
        switch(k){case 0:bad.profile="wrong";break;case 1:bad.body_sha256="wrong";break;case 2:bad.key_sha256="wrong";break;
        case 3:bad.key_source="wrong";break;case 4:bad.crypto_sha256="wrong";break;case 5:bad.manifest_sha256="wrong";break;
        case 6:bad.source_receipt_sha256="wrong";break;case 7:bad.code_receipt_sha256="wrong";break;}
        C(p1_ns_enable(s,&bad)==P1_NS_REJECT);p1_ns_delete(s);}
    p1_fc_stop();C(!message);
    printf("{\"passed\":true,\"checks\":%u,\"stream_bytes\":%zu,\"block_sum_accumulator\":%lu,\"alloc_calls\":%d,\"native_send_calls\":%d,\"copy_calls\":%d,\"free_calls\":%d,\"passive_header_EIO_preserved\":true,\"packet_pread_failures\":%d,\"ordinary_reads\":%d,\"ctor_asset_opens\":%d,\"guest_original\":false}\n",
        checks,consumed,(unsigned long)sums,alloc_calls,send_calls,copy_calls,free_calls,packet_reads,ordinary_reads,ctor_opens);
    return 0;
}
