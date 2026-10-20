/* SPDX-License-Identifier: MIT */
#include "cp-slot1-metadata.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

struct slot { unsigned char *bytes;unsigned int owned; };
struct fixture {
    struct cp_slot1_metadata *model;
    struct cp_meta_inputs in;
    struct cp_meta_io io;
    struct slot slots[8];
    unsigned char wires[8][CP_META_BYTES];
    unsigned int allocations,sends,releases,captured,retired;
    unsigned int fail_alloc,fail_send,fail_release,retain_send,mutate_input,bad_source;
};
static const char *golden[]={
    "0d000800000010000080232c0c0001000000a1b2",
    "03002000000000000081132d0c0000000000a1b2",
    "03002100000000000081232c0c0001000000a1b2"
};
static struct cp_meta_view view(struct fixture *f) {
    struct cp_meta_view v;assert(!cp_meta_snapshot(f->model,&v));return v;
}
static void check_wire(const unsigned char *wire,const char *hex) {
    for (unsigned int i=0;i<CP_META_BYTES;i++) {
        unsigned int v;assert(sscanf(hex+i*2,"%2x",&v)==1);assert(wire[i]==v);
    }
}
static int allocate(void *arg,uint32_t sid,size_t size,struct cp_meta_packet *out) {
    struct fixture *f=arg;unsigned int call=f->allocations++;
    assert(sid==CP_META_SID && size==CP_META_BYTES && view(f).busy);
    struct cp_meta_result recursive;
    assert(cp_meta_publish(f->model,&f->in,&recursive)==-EBUSY);
    assert(cp_meta_destroy(f->model)==-EBUSY && cp_meta_retry_release(f->model)==-EBUSY);
    if (f->fail_alloc&(1u<<call)) return -ENOMEM;
    assert(call<8);struct slot *slot=&f->slots[call];
    slot->bytes=malloc(size);assert(slot->bytes);slot->owned=1;
    memset(slot->bytes,0xdd,size);slot->bytes[18]=0xa1;slot->bytes[19]=0xb2;
    *out=(struct cp_meta_packet){slot->bytes,size,f->bad_source?0:CP_META_SOURCE,slot};
    if (f->mutate_input) { f->in.x=8;f->in.input_I=1;f->io.send=NULL; }
    return 0;
}
static void retire(struct fixture *f,struct slot *slot) {
    assert(slot->bytes && slot->owned);slot->owned=0;free(slot->bytes);slot->bytes=NULL;f->retired++;
}
static int send_packet(void *arg,uint32_t sid,const struct cp_meta_packet *packet) {
    struct fixture *f=arg;unsigned int call=f->sends++;
    struct slot *slot=packet->lease;
    assert(sid==CP_META_SID && packet->source==CP_META_SOURCE && packet->size==CP_META_BYTES);
    assert(slot && slot->bytes==packet->payload && slot->owned && view(f).busy);
    memcpy(f->wires[f->captured++],packet->payload,CP_META_BYTES);
    if (f->fail_send&(1u<<call)) return -EAGAIN;
    if (!f->retain_send) retire(f,slot); /* real inline retirement */
    return 0;
}
static int release_packet(void *arg,uint32_t sid,const struct cp_meta_packet *packet) {
    struct fixture *f=arg;f->releases++;struct slot *slot=packet->lease;
    /* This asserts the explicit safe payload repair, not original &slot ABI. */
    assert(sid==CP_META_SID && slot && slot->bytes==packet->payload && slot->owned);
    assert(view(f).busy);
    if (f->fail_release) return -EIO;
    retire(f,slot);return 0;
}
static void init(struct fixture *f,struct cp_meta_cache seed) {
    memset(f,0,sizeof *f);
    f->in=(struct cp_meta_inputs){.x=4,.y=3,.z=1,.w=2,.q=1,.a=1,
        .alternate=1,.t20=125,.t91=0,.input_I=3};
    f->io=(struct cp_meta_io){allocate,send_packet,release_packet};
    f->model=cp_meta_create(&seed,&f->io,f);assert(f->model);
}
static void done(struct fixture *f) {
    assert(!cp_meta_destroy(f->model));
    for (unsigned int i=0;i<8;i++) assert(!f->slots[i].owned);
}
static void formats(void) {
    struct fixture f;init(&f,(struct cp_meta_cache){0});
    for (unsigned int i=0;i<3;i++) {
        unsigned char bytes[20];memset(bytes,0xee,sizeof bytes);bytes[18]=0xa1;bytes[19]=0xb2;
        assert(!cp_meta_format(&f.in,(enum cp_meta_form)i,bytes,sizeof bytes));check_wire(bytes,golden[i]);
    }
    f.in.alternate=0;
    unsigned char bytes[20]={0};bytes[18]=0xa1;bytes[19]=0xb2;
    assert(!cp_meta_format(&f.in,CP_META_MODE,bytes,sizeof bytes));
    check_wire(bytes,"0d000800000010000080132d0c0000000000a1b2");
    f.in.t20=UINT32_MAX;f.in.t91=1;f.in.x=UINT32_MAX;f.in.y=UINT32_MAX;
    f.in.w=UINT32_MAX;f.in.z=2;f.in.a=2;f.in.q=255;
    assert(!cp_meta_format(&f.in,CP_META_ALTERNATE,bytes,sizeof bytes));
    assert(bytes[10]==0xff && bytes[11]==0 && bytes[12]==0xcc && bytes[13]==0xcc && !bytes[14]);
    f.in.t91=2;assert(!cp_meta_format(&f.in,CP_META_PRIMARY,bytes,sizeof bytes));
    assert(bytes[12]==0x99 && bytes[13]==0x99);
    assert(cp_meta_format(&f.in,(enum cp_meta_form)-1,bytes,sizeof bytes)==-ENOTSUP);
    assert(cp_meta_format(&f.in,CP_META_PRIMARY,bytes,19)==-EINVAL);
    f.in.input_I=1;assert(cp_meta_format(&f.in,CP_META_PRIMARY,bytes,sizeof bytes)==-ENOTSUP);
    done(&f);
}
static void normal(const char *which) {
    struct fixture f;init(&f,(struct cp_meta_cache){0});struct cp_meta_result r;
    if (!strcmp(which,"copied-input-io")) f.mutate_input=1;
    if (!strcmp(which,"receiver-owns")) f.retain_send=1;
    assert(!cp_meta_publish(f.model,&f.in,&r));
    assert(r.attempted==3 && r.allocated==3 && r.submitted==3 && r.cache_committed);
    assert(!r.first_io_error && !r.send_failures && !f.releases);
    for (unsigned int i=0;i<3;i++) check_wire(f.wires[i],golden[i]);
    assert(view(&f).cache.x==4 && view(&f).cache.n16==12);
    if (f.retain_send) {
        assert(!f.retired);
        /* Emitter owns none after successful send; actual receiver retires. */
        for (unsigned int i=0;i<3;i++) retire(&f,&f.slots[i]);
    }
    done(&f);
}
static void cache_cases(void) {
    struct fixture f;init(&f,(struct cp_meta_cache){4,3,1,2,1,1,12});struct cp_meta_result r;
    assert(!cp_meta_publish(f.model,&f.in,&r));assert(!r.attempted && !r.cache_committed);
    f.in.alternate=0;assert(!cp_meta_publish(f.model,&f.in,&r));assert(!r.attempted);
    f.in.a=2;assert(!cp_meta_publish(f.model,&f.in,&r));
    assert(r.attempted==2 && r.submitted==2 && r.cache_committed);
    assert(f.wires[0][2]==0x20 && f.wires[1][2]==0x21 && !f.wires[1][14]);
    assert(view(&f).cache.a==2);done(&f);
}
static void failures(const char *which) {
    struct fixture f;init(&f,(struct cp_meta_cache){0});struct cp_meta_result r;
    if (!strcmp(which,"allocation-failures")) f.fail_alloc=7;
    else if (!strcmp(which,"send-failures")) f.fail_send=7;
    else { f.fail_alloc=1;f.fail_send=1; }
    assert(!cp_meta_publish(f.model,&f.in,&r));assert(r.attempted==3 && r.cache_committed);
    if (f.fail_alloc==7) assert(r.allocation_failures==3 && !f.sends && !f.releases);
    else if (f.fail_send==7) assert(r.send_failures==3 && f.releases==3 && !r.submitted);
    else assert(r.allocation_failures==1 && r.send_failures==1 && r.submitted==1 && f.releases==1);
    unsigned int calls=f.allocations;
    assert(!cp_meta_publish(f.model,&f.in,&r));assert(!r.attempted && f.allocations==calls);
    done(&f);
}
static void retirement_failure(void) {
    struct fixture f;init(&f,(struct cp_meta_cache){0});f.fail_send=1;f.fail_release=1;
    struct cp_meta_result r;assert(cp_meta_publish(f.model,&f.in,&r)==-EIO);
    assert(r.attempted==1 && r.cleanup_failures==1 && !r.cache_committed && !f.retired);
    assert(view(&f).fault && view(&f).retained && !view(&f).cache.x);
    assert(cp_meta_destroy(f.model)==-EBUSY);assert(cp_meta_retry_release(f.model)==-EIO);
    f.fail_release=0;assert(!cp_meta_retry_release(f.model));assert(!view(&f).retained && view(&f).fault);
    assert(cp_meta_publish(f.model,&f.in,&r)==-EIO);assert(cp_meta_retry_release(f.model)==-ENOENT);
    done(&f);
}
static void invalid_source(void) {
    struct fixture f;init(&f,(struct cp_meta_cache){0});f.bad_source=1;struct cp_meta_result r;
    assert(cp_meta_publish(f.model,&f.in,&r)==-EPROTO);
    assert(r.attempted==1 && !r.cache_committed && f.releases==1 && !f.sends && view(&f).fault);
    done(&f);
}
static void child(void) {
    struct fixture f;init(&f,(struct cp_meta_cache){0});pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        struct cp_meta_result r;struct cp_meta_view v;
        assert(cp_meta_snapshot(f.model,&v)==-ECHILD);
        assert(cp_meta_publish(f.model,&f.in,&r)==-ECHILD);assert(cp_meta_destroy(f.model)==-ECHILD);_exit(0);
    }
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);done(&f);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"formats")) formats();
    else if (!strcmp(argv[1],"cache")) cache_cases();
    else if (!strcmp(argv[1],"retirement-failure")) retirement_failure();
    else if (!strcmp(argv[1],"invalid-source")) invalid_source();
    else if (!strcmp(argv[1],"fork")) child();
    else if (strstr(argv[1],"failures")) failures(argv[1]);
    else normal(argv[1]);
    puts("SLOT1_METADATA_SENDER_PASS");return 0;
}
