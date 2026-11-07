#define _GNU_SOURCE
#include "p1_cbc_stream.h"
#include <errno.h>
#include <openssl/crypto.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "p1_cbc_known_k8.inc"

struct p1_ns {
    pid_t pid; long tid; uint64_t epoch,serial,last_serial,consumed;
    int enabled,live,sent,input,stream;
    size_t capacity,input_size;
    unsigned char *packet;
    unsigned char input_bytes[1024],opaque[8],token[8],shadow[1064];
    struct p1_cbc *core;
};
long p1_ns_tid(void) {return syscall(SYS_gettid);}
struct p1_ns *p1_ns_new(void) {
    struct p1_ns *s=calloc(1,sizeof *s);
    if(s){s->pid=getpid();s->tid=p1_ns_tid();}return s;
}
void p1_ns_delete(struct p1_ns *s) {
    if(s){p1_cbc_delete(s->core);OPENSSL_cleanse(s,sizeof *s);free(s);}
}
static int text(const char *a,const char *b){return a && !strcmp(a,b);}
static int owner(const struct p1_ns *s){return s && s->pid==getpid() && s->tid==p1_ns_tid();}
static int reject(struct p1_ns *s){if(owner(s))s->stream=2;return P1_NS_REJECT;}
int p1_ns_enable(struct p1_ns *s,const struct p1_ns_config *c) {
    if(!owner(s) || !c || s->enabled || !c->epoch ||
       !text(c->profile,P1_NS_PROFILE) || !text(c->body_sha256,P1_CBC_ASSET_SHA256) ||
       !text(c->key_sha256,P1_NS_KEY_SHA) || !text(c->key_source,P1_CBC_KEY_SOURCE) ||
       !text(c->crypto_sha256,P1_NS_CRYPTO_SHA) || !text(c->manifest_sha256,P1_MODEL_MANIFEST_SHA) ||
       !text(c->source_receipt_sha256,P1_MODEL_SOURCE_SHA) || !text(c->code_receipt_sha256,P1_MODEL_CODE_SHA))
        return P1_NS_REJECT;
    s->epoch=c->epoch;s->enabled=1;return P1_NS_MODEL;
}
static int event(const struct p1_ns *s,const struct p1_ns_event *e,unsigned long caller,const char *source) {
    return owner(s) && e && e->pid==s->pid && e->tid==s->tid && e->epoch==s->epoch &&
        e->sid==P1_NS_SID && e->caller==caller && text(e->source_class,source);
}
static int lease(const struct p1_ns *s,const struct p1_ns_event *e,unsigned long caller,const char *source) {
    return event(s,e,caller,source) && s->live && e->serial==s->serial;
}
int p1_ns_bind(struct p1_ns *s,const struct p1_ns_event *e,void *packet,size_t capacity,int rc) {
    if(!s || !s->enabled)return P1_NS_PASS;
    if(!event(s,e,0x93d0,"native_allocator_return") || s->live || !e->serial || e->serial<=s->last_serial)
        return reject(s);
    if(rc)return P1_NS_PASS;
    uintptr_t p=(uintptr_t)packet,last=UINTPTR_MAX>>1;
    if((capacity!=56 && capacity!=552 && capacity!=1064) || p<4096 || p>last || capacity-1>last-p)
        return reject(s);
    s->packet=packet;s->capacity=capacity;s->serial=e->serial;s->last_serial=e->serial;
    s->live=1;s->sent=0;s->input=0;s->input_size=0;return P1_NS_MODEL;
}
int p1_ns_input(struct p1_ns *s,const struct p1_ns_event *e,void *payload,const void *snapshot,size_t n) {
    if(!s || !s->enabled)return P1_NS_PASS;
    if(!lease(s,e,0x9428,"original-memcpy-source") || s->sent || s->input || !snapshot ||
       payload!=s->packet+40 || n!=s->capacity-40)return reject(s);
    memcpy(s->input_bytes,snapshot,n);s->input_size=n;s->input=1;return P1_NS_MODEL;
}
static struct p1_cbc_result apply(struct p1_ns *s,unsigned op,size_t n) {
    struct p1_cbc_lease l={s->epoch,s->serial,s->shadow,40+n,n};
    struct p1_cbc_request r={.operation=op,.input_length=n};
    if(op==2)r.field16=8;else memcpy(r.context,s->token,8);
    if(p1_cbc_borrow(s->core,&l)!=P1_CBC_OK)return (struct p1_cbc_result){.error=P1_CBC_E_LEASE};
    return p1_cbc_apply(s->core,&l,&r);
}
static int sync_impl(struct p1_ns *s,const struct p1_ns_event *e,void *packet) {
    if(!s || !s->enabled)return P1_NS_PASS;
    if(!lease(s,e,0x9434,P1_NS_SOURCE) || packet!=s->packet || s->sent || !s->input)
        return reject(s);
    /* Original helper wrote header and payload before this sync; never follow opaque8. */
    uint64_t h[5];memcpy(h,s->packet,sizeof h);s->sent=1;
    if(memcmp(s->packet+40,s->input_bytes,s->input_size))return reject(s);
    if(s->capacity==56) {
        if(h[0]!=2 || h[1] || h[2]!=8 || h[3] || h[4]!=16)return reject(s);
        p1_cbc_delete(s->core);s->core=NULL;s->stream=0;s->consumed=0;
        OPENSSL_cleanse(s->opaque,8);OPENSSL_cleanse(s->token,8);
        return P1_NS_PASS;
    }
    if(s->stream!=1 || !s->core || h[0]!=3 || memcmp(h+1,s->opaque,8) || h[2] || h[3] ||
       h[4]!=s->input_size || (!s->consumed && h[4]!=512) || (s->consumed && h[4]!=1024) ||
       s->consumed>P1_STOCK_CBC_BYTES || h[4]>P1_STOCK_CBC_BYTES-s->consumed)return reject(s);
    memcpy(s->shadow+40,s->input_bytes,s->input_size);
    struct p1_cbc_result r=apply(s,3,s->input_size);
    if(r.error || r.operation_status!=1 || r.output_length!=s->input_size)return reject(s);
    uint64_t status=1,length=r.output_length; /* Explicit functional-model reply values. */
    memcpy(s->packet+40,s->shadow+40,r.output_length);
    memcpy(s->packet,&status,8);memcpy(s->packet+32,&length,8);
    s->consumed+=(uint64_t)r.output_length;return P1_NS_MODEL;
}
int p1_ns_sync(struct p1_ns *s,const struct p1_ns_event *e,void *packet) {
    int saved=errno,r=sync_impl(s,e,packet);errno=saved;return r;
}
static int init_impl(struct p1_ns *s,const struct p1_ns_event *e,int rc,const void *opaque,size_t n) {
    if(!s || !s->enabled)return P1_NS_PASS;
    if(!lease(s,e,0x9460,"original-memcpy-destination") || s->capacity!=56 || !s->sent ||
       s->stream || rc || !opaque || n!=8)return reject(s);
    uint64_t h[5];memcpy(h,s->packet,sizeof h);
    if(!h[0] || h[4]!=8 || memcmp(opaque,s->packet+40,8))return reject(s);
    struct p1_cbc_config c={P1_CBC_PROFILE,P1_CBC_ASSET_SHA256,P1_CBC_KEY_SOURCE,P1_CBC_FORMAT_SOURCE,
        s->epoch,public_known_k8,s->input_bytes,32,16};
    s->core=p1_cbc_new();
    if(!s->core || p1_cbc_configure(s->core,&c)!=P1_CBC_OK)return reject(s);
    memcpy(s->shadow+40,s->input_bytes,16);
    struct p1_cbc_result r=apply(s,2,16);
    if(r.error || r.operation_status!=1 || r.output_length!=8)return reject(s);
    memcpy(s->token,s->shadow+40,8);memcpy(s->opaque,opaque,8);s->stream=1;return P1_NS_MODEL;
}
int p1_ns_observe_init(struct p1_ns *s,const struct p1_ns_event *e,int rc,const void *opaque,size_t n) {
    int saved=errno,r=init_impl(s,e,rc,opaque,n);errno=saved;return r;
}
int p1_ns_release(struct p1_ns *s,const struct p1_ns_event *e,void *packet) {
    if(!s || !s->enabled)return P1_NS_PASS;
    if(!lease(s,e,0x949c,"native_free_call") || packet!=s->packet)return reject(s);
    s->live=0;s->packet=NULL;s->capacity=0;s->input=0;
    OPENSSL_cleanse(s->input_bytes,sizeof s->input_bytes);return P1_NS_MODEL;
}
