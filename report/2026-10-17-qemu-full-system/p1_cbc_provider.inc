/* Included inside current p1-trust-key.inc, after the unchanged passive guards. */
#include "p1_cbc_stream.h"
#include <openssl/evp.h>
#include <openssl/crypto.h>
#include <stdatomic.h>
static struct {
    struct p1_ns *stream;
    int mode,pid,prepared,init_rc;
    _Atomic int fault;
    _Atomic long tid;
    uint64_t epoch,serial;
    void *message;
    unsigned bytes;
    unsigned char snapshot[1024];
    size_t snapshot_size;
} p1_fc;
static __thread void *p1_fc_native_other;
static __thread int p1_fc_other_pid,p1_fc_other_conflict;
static _Atomic unsigned p1_fc_lines;
static void p1_fc_log(const char *phase,int result) {
    if(p1_fc_lines++<32){char line[350];snprintf(line,sizeof line,
        "P1_CBC_MODEL pid=%d tid=%ld phase=%s result=%d serial=%lu capacity=%u source_class=model-owned-native-cpu-copy status_semantics=model-defined native_opaque_dereferenced=0\n",
        getpid(),passive_tid(),phase,result,(unsigned long)(p1_fc.pid==getpid() && p1_fc.tid==passive_tid()?p1_fc.serial:0),
        p1_fc.pid==getpid() && p1_fc.tid==passive_tid()?p1_fc.bytes:0);logline(line);}
}
static int p1_fc_hash_file(const char *name,unsigned long expected,const char *hex) {
    int (*op)(const char *,int,...)=next("open");
    int fd=op?op(name,0xa0000):-1;if(fd<0)return 0;
    EVP_MD_CTX *ctx=EVP_MD_CTX_new();unsigned char bytes[1024],digest[64];unsigned length=0;
    unsigned long total=0;int ok=ctx && EVP_DigestInit_ex(ctx,EVP_sha256(),0)==1;
    while(ok){long n=read(fd,bytes,sizeof bytes);if(n<0){ok=0;break;}if(!n)break;
        if(total>expected || (unsigned long)n>expected-total){ok=0;break;}
        total+=(unsigned long)n;ok=EVP_DigestUpdate(ctx,bytes,(size_t)n)==1;}
    ok=ok && total==expected && EVP_DigestFinal_ex(ctx,digest,&length)==1 && length==32;
    EVP_MD_CTX_free(ctx);close(fd);char actual[65];actual[0]=0;
    if(ok)trust_hex(actual,digest,32);OPENSSL_cleanse(bytes,sizeof bytes);OPENSSL_cleanse(digest,sizeof digest);
    return ok && !strcmp(actual,hex);
}
static int p1_fc_marker(void) {
    int (*op)(const char *,int,...)=next("open");char value[160];
    int fd=op?op("/simulation/p1-cbc-model/profile",0xa0000):-1;
    long n=fd>=0?read(fd,value,sizeof value):-1;if(fd>=0)close(fd);
    static const char exact[]=P1_NS_PROFILE "\n" P1_MODEL_MANIFEST_SHA "\n";
    return n==(long)sizeof exact-1 && !memcmp(value,exact,sizeof exact-1);
}
static void p1_fc_start(void) __attribute__((constructor));
static void p1_fc_start(void) {
    int saved=*__errno_location();const char *p=getenv("A7C2_P1_CBC_PROFILE");
    if(!p || !selected()){*__errno_location()=saved;return;}
    p1_fc.mode=-1;p1_fc.pid=getpid();p1_fc.tid=0;p1_fc.epoch=1;
    int internal=trust_internal;trust_internal=1;
    int ok=!strcmp(p,P1_NS_PROFILE) && init_identity && trust_identity && passive_identity && p1_fc_marker() &&
        p1_fc_hash_file("/simulation/p1-cbc-model/manifest",P1_MODEL_MANIFEST_BYTES,P1_MODEL_MANIFEST_SHA) &&
        p1_fc_hash_file("/simulation/p1-cbc-model/source-receipt",P1_MODEL_SOURCE_BYTES,P1_MODEL_SOURCE_SHA) &&
        p1_fc_hash_file("/simulation/p1-cbc-model/code-receipt",P1_MODEL_CODE_BYTES,P1_MODEL_CODE_SHA) &&
        p1_fc_hash_file("/usr/lib/libcrypto.so.1.1",2349584,P1_NS_CRYPTO_SHA);
    if(ok)p1_fc.mode=1; /* The original helper's first allocation claims the receiver thread. */
    p1_fc_log("constructor",p1_fc.mode);trust_internal=internal;*__errno_location()=saved;
}
static void p1_fc_stop(void) __attribute__((destructor));
static void p1_fc_stop(void) {
    int saved=*__errno_location(),internal=trust_internal;trust_internal=1;
    p1_ns_delete(p1_fc.stream);p1_fc.stream=0;OPENSSL_cleanse(p1_fc.snapshot,sizeof p1_fc.snapshot);
    trust_internal=internal;*__errno_location()=saved;
}
static int p1_fc_owner(void){return p1_fc.pid==getpid() && p1_fc.tid==passive_tid();}
static int p1_fc_site(void *caller,unsigned long va) {
    Info i={0};return dladdr(caller,&i) && i.file && !strcmp(i.file,"/usr/lib/libsdfileinputupdaterapi.so") &&
        (unsigned long)caller==(unsigned long)i.base+va;
}
static int p1_fc_bound(void *caller,unsigned long va){return init_identity && passive_identity && trust_caller(caller,va);}
static struct p1_ns_event p1_fc_event(unsigned long va,const char *source) {
    return (struct p1_ns_event){getpid(),passive_tid(),p1_fc.epoch,p1_fc.serial,P1_NS_SID,va,source};
}
static int p1_fc_reject(void){p1_fc.fault=1;p1_fc_log("reject",-1);return P1_NS_REJECT;}
static void p1_fc_allocate(unsigned sid,void **out,unsigned bytes,int wait,int rc,void *caller) {
    if(!p1_fc.mode || !p1_fc_bound(caller,0x93d0) || sid!=P1_NS_SID || wait!=1)return;
    if(bytes!=56 && bytes!=552 && bytes!=1064) {
        if(!rc){void *other=0;int error=0;
            if(passive_read(&other,out,sizeof other,&error)==(long)sizeof other && other) {
                /* shortcut: one native other lease per thread; reject overlap until a new init. */
                if(p1_fc_native_other && p1_fc_other_pid==getpid()) {
                    p1_fc_other_conflict=1;p1_fc_reject();
                } else {p1_fc_native_other=other;p1_fc_other_pid=getpid();}
            }}
        return; /* Other requests and cleanup stay native, without reading their header. */
    }
    if(rc || p1_fc.mode!=1 || p1_fc.pid!=getpid())return;
    long unclaimed=0;
    if(atomic_compare_exchange_strong(&p1_fc.tid,&unclaimed,passive_tid())) {
        p1_fc.stream=p1_ns_new();struct p1_ns_config cfg={
            P1_NS_PROFILE,P1_CBC_ASSET_SHA256,P1_NS_KEY_SHA,P1_CBC_KEY_SOURCE,P1_NS_CRYPTO_SHA,
            P1_MODEL_MANIFEST_SHA,P1_MODEL_SOURCE_SHA,P1_MODEL_CODE_SHA,1};
        if(!p1_fc.stream || p1_ns_enable(p1_fc.stream,&cfg)!=P1_NS_MODEL){p1_fc_reject();return;}
    }
    if(!p1_fc_owner() || !p1_fc.stream)return;
    if(p1_fc.message || p1_fc.serial==UINT64_MAX){p1_fc_reject();return;}
    void *message=0;int error=0;
    if(passive_read(&message,out,sizeof message,&error)!=(long)sizeof message){p1_fc_reject();return;}
    if(p1_fc_other_pid==getpid() && message==p1_fc_native_other)p1_fc_native_other=0;
    p1_fc.serial++;struct p1_ns_event e=p1_fc_event(0x93d0,"native_allocator_return");
    if(p1_ns_bind(p1_fc.stream,&e,message,bytes,rc)!=P1_NS_MODEL){p1_fc_reject();return;}
    p1_fc.message=message;p1_fc.bytes=bytes;p1_fc.prepared=0;p1_fc.snapshot_size=0;p1_fc.init_rc=-1;
    if(bytes==56){p1_fc.fault=0;p1_fc_other_conflict=0;}
}
static void p1_fc_before_copy(void *dest,const void *source,size_t n,void *caller) {
    if(p1_fc.mode!=1 || !p1_fc_owner() || !p1_fc.message || !p1_fc_site(caller,0x9428))return;
    uintptr_t m=(uintptr_t)p1_fc.message,a=(uintptr_t)source,last=UINTPTR_MAX>>1;
    if(!p1_fc_bound(caller,0x9428) || p1_fc.prepared || p1_fc.fault ||
       (uintptr_t)dest!=m+40 || n!=p1_fc.bytes-40 || n>1024 || a<4096 || a>last || n-1>last-a ||
       (a<m+p1_fc.bytes && m<a+n)){p1_fc_reject();return;}
    int error=0;if(passive_read(p1_fc.snapshot,source,n,&error)!=(long)n){p1_fc_reject();return;}
    p1_fc.snapshot_size=n;p1_fc.prepared=1;
}
static void p1_fc_after_copy(void *dest,const void *source,size_t n,void *rc,void *caller) {
    if(p1_fc.mode!=1 || !p1_fc_owner() || !p1_fc.message)return;
    if(p1_fc_site(caller,0x9428)) {
        if(!p1_fc_bound(caller,0x9428) || !p1_fc.prepared || p1_fc.fault || rc!=dest || n!=p1_fc.snapshot_size){p1_fc_reject();return;}
        struct p1_ns_event e=p1_fc_event(0x9428,"original-memcpy-source");
        if(p1_ns_input(p1_fc.stream,&e,dest,p1_fc.snapshot,n)!=P1_NS_MODEL)p1_fc_reject();
    } else if(p1_fc_site(caller,0x9460) && p1_fc.bytes==56) {
        if(!p1_fc_bound(caller,0x9460) || p1_fc.fault || rc!=dest || n!=8 ||
           (uintptr_t)source!=(uintptr_t)p1_fc.message+40){p1_fc_reject();return;}
        unsigned char opaque[8];int error=0;
        if(passive_read(opaque,dest,8,&error)!=8){p1_fc_reject();return;}
        struct p1_ns_event e=p1_fc_event(0x9460,"original-memcpy-destination");
        int result=p1_ns_observe_init(p1_fc.stream,&e,p1_fc.init_rc,opaque,8);
        if(result!=P1_NS_MODEL)p1_fc_reject();else p1_fc_log("original-init-output8",result);
    }
}
static int p1_fc_sync(unsigned sid,void *message,void *caller) {
    if(!p1_fc.mode)return P1_NS_PASS;
    if(message && message==p1_fc.message && (sid!=P1_NS_SID || !p1_fc_owner()))return p1_fc_reject();
    if(message!=p1_fc.message && message==p1_fc_native_other && p1_fc_native_other && p1_fc_other_pid==getpid())
        return p1_fc_other_conflict?p1_fc_reject():P1_NS_PASS;
    if(!p1_fc_owner())return sid==P1_NS_SID && p1_fc_site(caller,0x9434)?p1_fc_reject():P1_NS_PASS;
    if(!p1_fc_site(caller,0x9434) && message!=p1_fc.message)return P1_NS_PASS;
    if(sid!=P1_NS_SID)return P1_NS_PASS;
    if(p1_fc.mode!=1 || !p1_fc_owner() || !p1_fc_bound(caller,0x9434) ||
       message!=p1_fc.message || p1_fc.fault || !p1_fc.prepared)return p1_fc_reject();
    struct p1_ns_event e=p1_fc_event(0x9434,P1_NS_SOURCE);
    int result=p1_ns_sync(p1_fc.stream,&e,message);
    if(result==P1_NS_REJECT)p1_fc_reject();else if(result==P1_NS_MODEL)p1_fc_log("cbc-consumed",result);
    return result;
}
static void p1_fc_after_sync(unsigned sid,void *message,int rc) {
    if(p1_fc.mode==1 && p1_fc_owner() && sid==P1_NS_SID && message==p1_fc.message)p1_fc.init_rc=rc;
}
static void p1_fc_free(unsigned sid,void *message,void *caller) {
    if(p1_fc.mode && p1_fc_other_pid==getpid() && message==p1_fc_native_other)p1_fc_native_other=0;
    if(p1_fc.mode!=1 || !p1_fc_owner() || sid!=P1_NS_SID || message!=p1_fc.message)return;
    struct p1_ns_event e=p1_fc_event(p1_fc_bound(caller,0x949c)?0x949c:0,"native_free_call");
    if(p1_ns_release(p1_fc.stream,&e,message)!=P1_NS_MODEL)p1_fc_reject();
    p1_fc.message=0;p1_fc.prepared=0;p1_fc.snapshot_size=0;OPENSSL_cleanse(p1_fc.snapshot,sizeof p1_fc.snapshot);
}
