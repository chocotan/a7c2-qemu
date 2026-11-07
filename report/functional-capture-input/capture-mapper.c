/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "capture-mapper.h"
#include <dlfcn.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#define SDK_SHA "676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5"
#define CTOR "_ZN12AvbbcPhycMemC1EmjNS_10CACHE_MODEEj"
#define DTOR "_ZN12AvbbcPhycMemD1Ev"
#define GETTER "_ZN12AvbbcPhycMem10GetLogAddrEv"
#define MAKE "_ZN26ExecCmd_SDF_EncodeJpegMain18MakeInputYcStdDataEPN17StillEncoderParam23RESIZEENC_PARAM_PAYLOADE"
#define VTABLE "_ZTV12AvbbcPhycMem"
#define BORROWED_FD UINT32_C(0xfffffffe)
#define DESTROYED_FD UINT32_C(0xfffffffd)
static pid_t mapper_owner;
static uintptr_t sdk_base, mapper_vptr;
static _Thread_local struct capture_mapper_scope *current_scope;
static void (*original_ctor)(void *, uint64_t, uint32_t, uint32_t, uint32_t);
static void (*original_dtor)(void *);
static uint32_t read32(const uint8_t *p) { uint32_t v;memcpy(&v,p,sizeof v);return v; }
static uint64_t read64(const uint8_t *p) { uint64_t v;memcpy(&v,p,sizeof v);return v; }
static void store32(uint8_t *p,uint32_t v) { memcpy(p,&v,sizeof v); }
static void store64(uint8_t *p,uint64_t v) { memcpy(p,&v,sizeof v); }
static uint64_t fingerprint(const uint8_t *p,size_t n) {
    uint64_t h=UINT64_C(14695981039346656037);
    for(size_t i=0;i<n;++i)h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
static void *next(const char *name) { return dlsym(RTLD_NEXT,name); }
int capture_mapper_bind(const char *sha256) {
    if(mapper_owner && mapper_owner!=getpid())return -ECHILD;
    if(current_scope)return -EBUSY;
    if(!sha256 || strcmp(sha256,SDK_SHA))return -ELIBBAD;
    void *ctor=next(CTOR),*dtor=next(DTOR),*getter=next(GETTER),*make=next(MAKE),*vtable=next(VTABLE);
    Dl_info info;
    if(!ctor || !dtor || !getter || !make || !vtable || !dladdr(ctor,&info) || !info.dli_fbase)return -ENOSYS;
    const uintptr_t base=(uintptr_t)info.dli_fbase;
    if(base>UINTPTR_MAX-0x1b2a98 || (uintptr_t)ctor!=base+0x1401a8 ||
        (uintptr_t)dtor!=base+0x13ff54 || (uintptr_t)getter!=base+0x13ff4c ||
        (uintptr_t)make!=base+0x1218a8 || (uintptr_t)vtable!=base+0x1b2a60)return -ELIBBAD;
    const struct { uintptr_t address;size_t bytes;uint64_t fnv; } pins[]={
        {0x1401a8,392,UINT64_C(0xa015a4ef3dbab46d)},
        {0x13ff54,164,UINT64_C(0x9b1ead69601c135b)},
        {0x13ff4c,8,UINT64_C(0xe1e31c9f2ec1cc42)},
        {0x1218a8,760,UINT64_C(0x5adb961d7ebe054b)}};
    for(size_t i=0;i<sizeof pins/sizeof pins[0];++i)
        if(fingerprint((const void *)(base+pins[i].address),pins[i].bytes)!=pins[i].fnv)return -ELIBBAD;
    if(mapper_owner && sdk_base!=base)return -ESTALE;
    _Static_assert(sizeof original_ctor==sizeof ctor,"POSIX function pointer ABI");
    memcpy(&original_ctor,&ctor,sizeof ctor);memcpy(&original_dtor,&dtor,sizeof dtor);
    sdk_base=base;mapper_vptr=(uintptr_t)vtable+16;mapper_owner=getpid();return 0;
}
int capture_mapper_begin(struct capture_input *input,struct capture_mapper_scope *scope) {
    if(!mapper_owner)return -ENODEV;
    if(mapper_owner!=getpid())return -ECHILD;
    if(!input || !scope)return -EINVAL;
    if(current_scope)return -EBUSY;
    struct capture_mapper_scope candidate={0};candidate.input=input;
    int rc=capture_input_info(input,&candidate.info);if(rc)return rc;
    rc=capture_input_map(input,candidate.info.metadata_alias,1024,0,0x29,&candidate.mapping);
    if(rc)return rc;
    *scope=candidate;current_scope=scope;return 0;
}
int capture_mapper_end(struct capture_mapper_scope *scope) {
    if(!mapper_owner)return -ENODEV;
    if(mapper_owner!=getpid())return -ECHILD;
    if(!scope || current_scope!=scope)return -EINVAL;
    if(scope->objects)return -EBUSY;
    int rc=capture_input_unmap(scope->input,&scope->mapping);
    if(rc)return rc;
    int sealed=capture_input_seal_metadata(scope->input);
    rc=scope->error?scope->error:sealed;
    current_scope=NULL;memset(scope,0,sizeof *scope);return rc;
}
static void construct(void *object,uint64_t alias,uint32_t bytes,uint32_t cache,uint32_t caller,uintptr_t pc) {
    if(!current_scope) {
        void (*delegate)(void *,uint64_t,uint32_t,uint32_t,uint32_t)=original_ctor;
        if(!delegate) { void *p=next(CTOR);memcpy(&delegate,&p,sizeof p); }
        if(!delegate)abort();
        delegate(object,alias,bytes,cache,caller);return;
    }
    if(mapper_owner!=getpid() || !object || current_scope->objects==UINT32_MAX)abort();
    struct capture_mapper_scope *scope=current_scope;
    const int valid=pc==sdk_base+0x121a24 && alias==scope->info.metadata_alias &&
        bytes==1024 && !cache && caller==0x29 && !scope->objects && !scope->error;
    if(!valid)scope->error=-EPROTO;
    uint8_t *p=object;memset(p,0,0x34);store64(p,mapper_vptr);store32(p+8,BORROWED_FD);
    store64(p+0x10,valid?scope->mapping.address:(uintptr_t)scope->failed_metadata);
    store64(p+0x18,(uintptr_t)scope);store64(p+0x20,alias);
    store32(p+0x28,1024);store32(p+0x2c,bytes);store32(p+0x30,caller);
    ++scope->objects;
}
static void destruct(void *object) {
    if(!object)abort();
    uint8_t *p=object;const uint32_t fd=read32(p+8);
    if(fd==BORROWED_FD || fd==DESTROYED_FD) {
        if(mapper_owner!=getpid() || !current_scope || read64(p)!=mapper_vptr ||
            read64(p+0x18)!=(uintptr_t)current_scope)abort();
        if(fd==DESTROYED_FD) { current_scope->error=-ESTALE;return; }
        if(!current_scope->objects)abort();
        --current_scope->objects;store32(p+8,DESTROYED_FD);return;
    }
    void (*delegate)(void *)=original_dtor;
    if(!delegate) { void *symbol=next(DTOR);memcpy(&delegate,&symbol,sizeof symbol); }
    if(!delegate)abort();delegate(object);
}
void capture_mapper_ctor1(void *,uint64_t,uint32_t,uint32_t,uint32_t) __asm__(CTOR);
void capture_mapper_ctor2(void *,uint64_t,uint32_t,uint32_t,uint32_t) __asm__("_ZN12AvbbcPhycMemC2EmjNS_10CACHE_MODEEj");
void capture_mapper_dtor1(void *) __asm__(DTOR);
void capture_mapper_dtor2(void *) __asm__("_ZN12AvbbcPhycMemD2Ev");
void capture_mapper_ctor1(void *object,uint64_t alias,uint32_t bytes,uint32_t cache,uint32_t caller) {
    construct(object,alias,bytes,cache,caller,(uintptr_t)__builtin_return_address(0));
}
void capture_mapper_ctor2(void *object,uint64_t alias,uint32_t bytes,uint32_t cache,uint32_t caller) {
    construct(object,alias,bytes,cache,caller,(uintptr_t)__builtin_return_address(0));
}
void capture_mapper_dtor1(void *object) { destruct(object); }
void capture_mapper_dtor2(void *object) { destruct(object); }
