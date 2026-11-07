#ifndef P1_NATIVE_STREAM_H
#define P1_NATIVE_STREAM_H
#include "p1_cbc_core.h"
#include "p1_cbc_runtime_binding.h"
#include <sys/types.h>
#define P1_NS_PROFILE "virtual-p1-cbc-scramble-v1"
#define P1_NS_SOURCE "model-owned-native-cpu-copy"
#define P1_NS_SID 0x025906beu
#define P1_NS_CRYPTO_SHA "df69906d5f63a3afe9b7872e41cab741c346630e53ebcaadb86e457f0b803726"
#define P1_NS_KEY_SHA "b869168a196223e2866c570590f446ee35152090f55485c603d69c6a75a049a3"
/* The wrapper checks actual receipt bytes before calling enable; no boolean authority. */
struct p1_ns_config {
    const char *profile, *body_sha256, *key_sha256, *key_source, *crypto_sha256;
    const char *manifest_sha256, *source_receipt_sha256, *code_receipt_sha256;
    uint64_t epoch;
};
struct p1_ns_event {
    pid_t pid; long tid; uint64_t epoch, serial;
    unsigned sid; unsigned long caller; const char *source_class;
};
enum p1_ns_rc { P1_NS_PASS=0, P1_NS_MODEL=1, P1_NS_REJECT=-1 };
struct p1_ns;
struct p1_ns *p1_ns_new(void);
void p1_ns_delete(struct p1_ns *);
int p1_ns_enable(struct p1_ns *,const struct p1_ns_config *);
long p1_ns_tid(void);
int p1_ns_bind(struct p1_ns *,const struct p1_ns_event *,void *,size_t,int);
int p1_ns_input(struct p1_ns *,const struct p1_ns_event *,void *,const void *,size_t);
int p1_ns_sync(struct p1_ns *,const struct p1_ns_event *,void *);
int p1_ns_observe_init(struct p1_ns *,const struct p1_ns_event *,int,const void *,size_t);
int p1_ns_release(struct p1_ns *,const struct p1_ns_event *,void *);
#endif
