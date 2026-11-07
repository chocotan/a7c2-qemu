/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "capture-input.h"
#include <errno.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>

#define PAGE 4096u
#define MAX_RGB (64u * 1024u * 1024u - 96u)
#define SLOTS 8u
struct borrow { struct capture_input_mapping map; int kind; };
struct capture_input {
    struct capture_input_info info;
    uint8_t *memory;
    size_t mapped_bytes;
    uint64_t next_borrow;
    pid_t owner;
    struct borrow borrows[SLOTS];
};
static _Atomic uint32_t identities;
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const uint8_t *p) { return get32(p) | (uint64_t)get32(p + 4) << 32; }
static void put32(uint8_t *p, uint32_t v) { for (unsigned i=0;i<4;++i) p[i]=(uint8_t)(v>>(8*i)); }
static void put64(uint8_t *p, uint64_t v) { for (unsigned i=0;i<8;++i) p[i]=(uint8_t)(v>>(8*i)); }
static void put16(uint8_t *p, uint32_t v) { p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8); }
static uint64_t fnv(const uint8_t *p, size_t n) {
    uint64_t h=UINT64_C(14695981039346656037);
    for (size_t i=0;i<n;++i) h=(h^p[i])*UINT64_C(1099511628211);
    return h;
}
static int guard(const struct capture_input *c) {
    return !c ? -EINVAL : c->owner!=getpid() ? -ECHILD : 0;
}
int capture_input_create(const uint8_t *frame, size_t bytes, const uint8_t request[16],
    const uint8_t parameters[128], struct capture_input **out) {
    if (!frame || !request || !parameters || !out || bytes<96 || bytes>MAX_RGB+96u ||
        bytes>UINTPTR_MAX-(uintptr_t)frame || sysconf(_SC_PAGESIZE)!=PAGE) return -EINVAL;
    const uint32_t width=get32(frame+48),height=get32(frame+52),stride=get32(frame+56);
    const uint64_t size=get64(frame+64);
    if (get32(frame)!=1 || get32(frame+4)!=96 || !get64(frame+8) || !get64(frame+16) ||
        !get64(frame+24) || !get64(frame+32) || !get64(frame+40) || !width || width>8192 ||
        !height || height>8192 || stride!=width*3u || get32(frame+60)!=1 ||
        size!=(uint64_t)stride*height || size!=bytes-96u || get64(frame+72)!=fnv(frame+96,bytes-96u) ||
        get32(request)!=UINT32_C(0x40380005) || request[9] || request[10] || request[11] ||
        !(request[8]==2 || request[8]==10 || request[8]==12 || request[8]==8 || request[8]==9 || request[8]==3) ||
        get32(frame+80)!=get32(request+4) || frame[84]!=request[8] || frame[85] || frame[86] || frame[87] ||
        get64(frame+88)!=fnv(request,16)) return -EBADMSG;
    if(parameters[0x63]!=8) return -ENOTSUP;
    struct capture_input *c=calloc(1,sizeof *c);
    if (!c) return -ENOMEM;
    const size_t pixel_capacity=(size_t)((size+PAGE-1)/PAGE)*PAGE;
    c->mapped_bytes=2u*PAGE+pixel_capacity;
    c->memory=mmap(NULL,c->mapped_bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if (c->memory==MAP_FAILED) { int rc=-errno;free(c);return rc; }
    uint32_t id=atomic_load(&identities);
    do {
        if (id==UINT32_C(0x0ffffffe)) { munmap(c->memory,c->mapped_bytes);free(c);return -EOVERFLOW; }
    } while (!atomic_compare_exchange_weak(&identities,&id,id+1));
    ++id;
    /* Distinct software alias domain; these values never address physical RAM. */
    const uint64_t alias=UINT64_C(0x1000000000000000)+(uint64_t)id*UINT64_C(0x10000000);
    c->info=(struct capture_input_info){.token=get64(frame+8),.model_instance=get64(frame+16),
        .model_lifetime=get64(frame+24),.config_generation=get64(frame+32),.frame_generation=get64(frame+40),
        .source_fnv1a64=get64(frame+72),.metadata_alias=alias,.pixel_alias=alias+2u*PAGE,
        .metadata_cpu=(uintptr_t)c->memory,.parameter_cpu=(uintptr_t)c->memory+PAGE,
        .pixel_cpu=(uintptr_t)c->memory+2u*PAGE,.pixel_bytes=(size_t)size,
        .metadata_unit=UINT32_C(0xd0000000)+id*2u,.pixel_unit=UINT32_C(0xd0000001)+id*2u,
        .width=width,.height=height,.stride=stride,.request_fnv1a64=get64(frame+88),
        .request_cookie=get32(frame+80),.request_trigger=frame[84]};
    c->owner=getpid();
    memcpy((void *)c->info.pixel_cpu,frame+96,(size_t)size);
    uint8_t *p=(void *)c->info.parameter_cpu;
    memcpy(p,parameters,128);
    put32(p+8,0);put32(p+12,c->info.metadata_unit);
    put64(p+0x18,c->info.metadata_alias);put64(p+0x20,0);
    put32(p+0x30,0);put32(p+0x34,c->info.pixel_unit);put64(p+0x48,0);
    put16(p+0x54,width);put16(p+0x56,height);put16(p+0x58,0);put16(p+0x5a,0);
    put16(p+0x5c,width);put16(p+0x5e,height);
    if (fnv((const void *)c->info.pixel_cpu,c->info.pixel_bytes)!=c->info.source_fnv1a64) {
        munmap(c->memory,c->mapped_bytes);free(c);return -EIO;
    }
    if (mprotect((void *)c->info.parameter_cpu,PAGE,PROT_READ) ||
        mprotect((void *)c->info.pixel_cpu,pixel_capacity,PROT_READ)) {
        int rc=-errno;munmap(c->memory,c->mapped_bytes);free(c);return rc;
    }
    *out=c;
    return 0;
}
int capture_input_info(const struct capture_input *c, struct capture_input_info *out) {
    int rc=guard(c);if(rc)return rc;if(!out)return -EINVAL;
    *out=c->info;return 0;
}
static int borrow(struct capture_input *c, uintptr_t address, size_t bytes, int kind,
    struct capture_input_mapping *out) {
    if (!out || !bytes) return -EINVAL;
    if (c->next_borrow==UINT64_MAX) return -EOVERFLOW;
    unsigned slot=0;for(;slot<SLOTS && c->borrows[slot].map.token;++slot) {}
    if(slot==SLOTS)return -ENOSPC;
    struct capture_input_mapping m={++c->next_borrow,address,bytes};
    c->borrows[slot]=(struct borrow){m,kind};
    if(kind==1)++c->info.pixel_references;
    else if(kind==3)++c->info.owner_references;
    else ++c->info.mapping_references;
    *out=m;return 0;
}
int capture_input_hold(struct capture_input *c,struct capture_input_mapping *out) {
    int rc=guard(c);if(rc)return rc;
    return borrow(c,c->info.parameter_cpu,128,3,out);
}
int capture_input_map(struct capture_input *c, uint64_t alias, size_t bytes,
    uint32_t cache, uint32_t caller, struct capture_input_mapping *out) {
    int rc=guard(c);if(rc)return rc;
    if(cache || caller!=0x29)return -ENOTSUP;
    if(alias<c->info.metadata_alias || alias-c->info.metadata_alias>=1024u ||
        !bytes || bytes>1024u-(size_t)(alias-c->info.metadata_alias))return -ERANGE;
    if(!out)return -EINVAL;
    if(c->info.pixel_references)return -EBUSY;
    unsigned free_slots=0;
    for(unsigned i=0;i<SLOTS;++i) {
        if(c->borrows[i].map.token && c->borrows[i].kind==2)return -EBUSY;
        if(!c->borrows[i].map.token)++free_slots;
    }
    if(!free_slots)return -ENOSPC;
    if(c->next_borrow==UINT64_MAX)return -EOVERFLOW;
    if(c->info.metadata_readonly) {
        if(mprotect((void *)c->info.metadata_cpu,PAGE,PROT_READ|PROT_WRITE))return -errno;
        c->info.metadata_readonly=0;
    }
    return borrow(c,c->info.metadata_cpu+(uintptr_t)(alias-c->info.metadata_alias),bytes,0,out);
}
int capture_input_seal_metadata(struct capture_input *c) {
    int rc=guard(c);if(rc)return rc;
    if(c->info.mapping_references || c->info.pixel_references)return -EBUSY;
    if(!c->info.metadata_readonly) {
        if(mprotect((void *)c->info.metadata_cpu,PAGE,PROT_READ))return -errno;
        c->info.metadata_readonly=1;
    }
    return 0;
}
int capture_input_metadata_read(struct capture_input *c,uint32_t unit,uint32_t offset,
    size_t bytes,struct capture_input_mapping *out) {
    int rc=guard(c);if(rc)return rc;
    if(unit!=c->info.metadata_unit)return -ESTALE;
    if(offset>=1024u || !bytes || bytes>1024u-offset)return -ERANGE;
    if(!c->info.metadata_readonly)return -ENODATA;
    return borrow(c,c->info.metadata_cpu+offset,bytes,2,out);
}
int capture_input_pixels(struct capture_input *c, uint32_t unit, uint32_t offset,
    size_t bytes, struct capture_input_mapping *out) {
    int rc=guard(c);if(rc)return rc;
    if(unit!=c->info.pixel_unit)return -ESTALE;
    if(offset>=c->info.pixel_bytes || !bytes || bytes>c->info.pixel_bytes-offset)return -ERANGE;
    if(fnv((const void *)c->info.pixel_cpu,c->info.pixel_bytes)!=c->info.source_fnv1a64)return -EBADMSG;
    return borrow(c,c->info.pixel_cpu+offset,bytes,1,out);
}
static int release(struct capture_input *c, const struct capture_input_mapping *m, int kind) {
    int rc=guard(c);if(rc)return rc;if(!m)return -EINVAL;
    for(unsigned i=0;i<SLOTS;++i) {
        struct borrow *b=&c->borrows[i];
        if(m->token && b->map.token==m->token && b->kind==kind &&
            b->map.address==m->address && b->map.bytes==m->bytes) {
            memset(b,0,sizeof *b);
            if(kind==1)--c->info.pixel_references;
            else if(kind==3)--c->info.owner_references;
            else --c->info.mapping_references;
            return 0;
        }
    }
    return -ESTALE;
}
int capture_input_drop(struct capture_input *c, const struct capture_input_mapping *m) { return release(c,m,3); }
int capture_input_unmap(struct capture_input *c, const struct capture_input_mapping *m) { return release(c,m,0); }
int capture_input_release_metadata(struct capture_input *c, const struct capture_input_mapping *m) { return release(c,m,2); }
int capture_input_release_pixels(struct capture_input *c, const struct capture_input_mapping *m) { return release(c,m,1); }
int capture_input_destroy(struct capture_input *c) {
    int rc=guard(c);if(rc)return rc;
    if(c->info.mapping_references || c->info.pixel_references || c->info.owner_references)return -EBUSY;
    if(munmap(c->memory,c->mapped_bytes))return -errno;
    memset(c,0,sizeof *c);free(c);return 0;
}
