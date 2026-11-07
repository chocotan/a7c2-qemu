#define _POSIX_C_SOURCE 200809L
#include "p1_cbc_core.h"

#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

struct p1_cbc {
    pid_t owner;
    uint32_t instance, generation;
    uint64_t epoch, last_serial;
    int configured, active, borrowed;
    uint64_t consumed;
    uint8_t key[32], iv[16], token[8];
    struct p1_cbc_lease lease;
};
static uint32_t next_instance;
static const uint8_t official_iv[16] = {
    0xe5,0x16,0x51,0x4b,0xfa,0x7c,0x61,0x03,0xf9,0x09,0xb6,0xa8,0xae,0x25,0x87,0x74
};
static const uint8_t key_digest[32] = {
    0xb8,0x69,0x16,0x8a,0x19,0x62,0x23,0xe2,0x86,0x6c,0x57,0x05,0x90,0xf4,0x46,0xee,
    0x35,0x15,0x20,0x90,0xf5,0x54,0x85,0xc6,0x03,0xd6,0x9c,0x6a,0x75,0xa0,0x49,0xa3
};
static enum p1_cbc_error owned(const struct p1_cbc *c) {
    if (!c) return P1_CBC_E_ARGUMENT;
    return c->owner == getpid() ? P1_CBC_OK : P1_CBC_E_PROCESS;
}
static struct p1_cbc_result result(enum p1_cbc_error error) {
    return (struct p1_cbc_result){.error=error};
}
static int same_lease(const struct p1_cbc_lease *a, const struct p1_cbc_lease *b) {
    return a->epoch==b->epoch && a->serial==b->serial && a->packet==b->packet &&
        a->allocation_capacity==b->allocation_capacity && a->payload_capacity==b->payload_capacity;
}
static int timestamp(uint64_t *out) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) || t.tv_sec<0) return 0;
    *out=(uint64_t)t.tv_sec*UINT64_C(1000000000)+(uint64_t)t.tv_nsec;
    return 1;
}
struct p1_cbc *p1_cbc_new(void) {
    if (next_instance==UINT32_MAX) return NULL;
    struct p1_cbc *c=calloc(1,sizeof *c);
    if (c) { c->owner=getpid(); c->instance=++next_instance; }
    return c;
}
void p1_cbc_delete(struct p1_cbc *c) {
    if (c) { OPENSSL_cleanse(c,sizeof *c); free(c); }
}
enum p1_cbc_error p1_cbc_configure(struct p1_cbc *c, const struct p1_cbc_config *cfg) {
    enum p1_cbc_error e=owned(c);
    if (e) return e;
    if (!cfg) return P1_CBC_E_ARGUMENT;
    if (c->configured || c->active || c->borrowed) return P1_CBC_E_STATE;
    if (!cfg->epoch || cfg->epoch<=c->epoch) return P1_CBC_E_EPOCH;
    if (c->generation>=P1_CBC_MAX_GENERATIONS) return P1_CBC_E_LIMIT;
    if (!cfg->profile || strcmp(cfg->profile,P1_CBC_PROFILE) ||
        !cfg->asset_sha256 || strcmp(cfg->asset_sha256,P1_CBC_ASSET_SHA256) ||
        !cfg->key_source || strcmp(cfg->key_source,P1_CBC_KEY_SOURCE) ||
        !cfg->format_source || strcmp(cfg->format_source,P1_CBC_FORMAT_SOURCE) ||
        !cfg->key || cfg->key_length!=32 || !cfg->iv || cfg->iv_length!=16 ||
        memcmp(cfg->iv,official_iv,16)) return P1_CBC_E_CONFIG;
    uint8_t digest[EVP_MAX_MD_SIZE]; unsigned length=0;
    int ok=EVP_Digest(cfg->key,32,digest,&length,EVP_sha256(),NULL);
    int match=ok==1 && length==32 && !memcmp(digest,key_digest,32);
    OPENSSL_cleanse(digest,sizeof digest);
    if (!match) return ok==1 ? P1_CBC_E_CONFIG : P1_CBC_E_CRYPTO;
    memcpy(c->key,cfg->key,32); memcpy(c->iv,cfg->iv,16);
    c->epoch=cfg->epoch; c->configured=1; c->consumed=0;
    return P1_CBC_OK;
}
enum p1_cbc_error p1_cbc_borrow(struct p1_cbc *c, const struct p1_cbc_lease *l) {
    enum p1_cbc_error e=owned(c);
    if (e) return e;
    if (!l) return P1_CBC_E_ARGUMENT;
    if (!c->configured) return P1_CBC_E_OFF;
    if (l->epoch!=c->epoch) return P1_CBC_E_EPOCH;
    if (c->borrowed || !l->serial || l->serial<=c->last_serial) return P1_CBC_E_LEASE;
    if (!l->packet || (uintptr_t)l->packet<4096 ||
        l->allocation_capacity<56 || l->allocation_capacity>40+P1_CBC_MAX_CHUNK ||
        l->payload_capacity>l->allocation_capacity-40 ||
        l->allocation_capacity-1>UINTPTR_MAX-(uintptr_t)l->packet) return P1_CBC_E_CAPACITY;
    c->lease=*l; c->borrowed=1; c->last_serial=l->serial;
    return P1_CBC_OK;
}
struct p1_cbc_result p1_cbc_apply(struct p1_cbc *c, const struct p1_cbc_lease *l,
                               const struct p1_cbc_request *request) {
    enum p1_cbc_error e=owned(c);
    if (e) return result(e);
    if (!l || !request) return result(P1_CBC_E_ARGUMENT);
    if (!c->configured) return result(P1_CBC_E_OFF);
    if (l->epoch!=c->epoch) return result(P1_CBC_E_EPOCH);
    if (!c->borrowed || !same_lease(l,&c->lease)) return result(P1_CBC_E_LEASE);
    struct p1_cbc_lease lease=*l;
    struct p1_cbc_request r=*request;
    c->borrowed=0; memset(&c->lease,0,sizeof c->lease);
    /* One matched attempt consumes only model borrow metadata, even on refusal. */
    if (r.operation!=2 && r.operation!=3) return result(P1_CBC_E_OPERATION);
    if (r.operation==2) {
        static const uint8_t zero[8];
        if (c->active) return result(P1_CBC_E_STATE);
        if (memcmp(r.context,zero,8) || r.field16!=8 || r.field24) return result(P1_CBC_E_CONTEXT);
        if (r.input_length!=16) return result(P1_CBC_E_LENGTH);
        if (lease.allocation_capacity!=56 || lease.payload_capacity!=16) return result(P1_CBC_E_CAPACITY);
        if (memcmp(lease.packet+40,c->iv,16)) return result(P1_CBC_E_CONFIG);
        uint64_t token=((uint64_t)c->instance<<32) | ++c->generation;
        for (unsigned i=0;i<8;i++) c->token[i]=(uint8_t)(token>>(i*8));
        c->active=1; memcpy(lease.packet+40,c->token,8);
        return (struct p1_cbc_result){.error=P1_CBC_OK,.operation_status=1,.output_length=8};
    }
    if (!c->active) return result(P1_CBC_E_STATE);
    if (memcmp(r.context,c->token,8) || r.field16 || r.field24) return result(P1_CBC_E_CONTEXT);
    if (!r.input_length || r.input_length>P1_CBC_MAX_CHUNK || r.input_length%16)
        return result(P1_CBC_E_LENGTH);
    size_t bytes=(size_t)r.input_length;
    if (bytes>lease.payload_capacity || bytes>lease.allocation_capacity-40) return result(P1_CBC_E_CAPACITY);
    if (c->consumed>P1_CBC_MAX_STREAM || (uint64_t)bytes>P1_CBC_MAX_STREAM-c->consumed)
        return result(P1_CBC_E_LIMIT);
    uint64_t start,end;
    if (!timestamp(&start)) return result(P1_CBC_E_CLOCK);
    uint8_t output[P1_CBC_MAX_CHUNK],final_block[16],next_iv[16];
    memcpy(next_iv,lease.packet+40+bytes-16,16);
    EVP_CIPHER_CTX *evp=EVP_CIPHER_CTX_new();
    int produced=0,final_bytes=0;
    int ok=evp && EVP_DecryptInit_ex(evp,EVP_aes_256_cbc(),NULL,c->key,c->iv)==1 &&
        EVP_CIPHER_CTX_set_padding(evp,0)==1 &&
        EVP_DecryptUpdate(evp,output,&produced,lease.packet+40,(int)bytes)==1 &&
        produced==(int)bytes && EVP_DecryptFinal_ex(evp,final_block,&final_bytes)==1 && final_bytes==0;
    EVP_CIPHER_CTX_free(evp);
    struct p1_cbc_result out=result(ok ? P1_CBC_OK : P1_CBC_E_CRYPTO);
    if (!timestamp(&end) || end<start) out.error=P1_CBC_E_CLOCK;
    else {
        out.elapsed_ns=end-start;
        if (out.elapsed_ns>P1_CBC_MAX_OPERATION_NS) out.error=P1_CBC_E_TIMEOUT;
    }
    if (out.error==P1_CBC_OK) {
        memcpy(lease.packet+40,output,bytes); memcpy(c->iv,next_iv,16); c->consumed+=bytes;
        out.operation_status=1; out.output_length=bytes;
    }
    OPENSSL_cleanse(output,sizeof output); OPENSSL_cleanse(final_block,sizeof final_block);
    OPENSSL_cleanse(next_iv,sizeof next_iv);
    return out;
}
enum p1_cbc_error p1_cbc_retire(struct p1_cbc *c, uint64_t epoch, const uint8_t token[8]) {
    enum p1_cbc_error e=owned(c);
    if (e) return e;
    if (!token) return P1_CBC_E_ARGUMENT;
    if (epoch!=c->epoch) return P1_CBC_E_EPOCH;
    if (!c->active) return P1_CBC_E_STATE;
    if (memcmp(token,c->token,8)) return P1_CBC_E_CONTEXT;
    OPENSSL_cleanse(c->key,sizeof c->key); OPENSSL_cleanse(c->iv,sizeof c->iv);
    OPENSSL_cleanse(c->token,sizeof c->token); memset(&c->lease,0,sizeof c->lease);
    c->configured=0; c->active=0; c->borrowed=0; c->consumed=0;
    return P1_CBC_OK;
}
