/* SPDX-License-Identifier: MIT */
#include "adf-input-state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
struct context { struct full_adf_input_state *state; unsigned int calls,corrupt; };
static void fresh(struct full_adf_input_state *s)
{
    memset(s,0,sizeof *s); /* Test fixtures only; production init cannot reset work. */
    assert(!full_adf_input_init(s));
}
static void listener(void *opaque,unsigned int status)
{
    struct context *ctx=opaque;struct full_adf_input_state *s=ctx->state;
    assert(!status && s->pending==1 && s->submitted && s->registered && s->request==1);
    assert(s->jobs[0].active==1 && s->scheduler_consumed==1 && !s->complete);
    assert(!s->driver_callback && !s->listeners[0].callback && !s->listeners[0].context);
    assert(s->callback_pending && s->callback_submitted && s->callback_driver_empty);
    assert(s->controls==1 && s->callbacks==1 && s->listeners_removed==1);
    unsigned int parameter=99;full_adf_input_completion callback=0;
    assert(!full_adf_input_readback(s,&parameter,&callback) && !parameter && !callback);
    ctx->calls++;
    if(ctx->corrupt==1)s->pending=0;
    if(ctx->corrupt==2)s->driver_parameter=1;
    if(ctx->corrupt==3)s->generation=2;
    if(ctx->corrupt==4)s->registered(s,0);
}
static void bad_begin(struct full_adf_input_state *s,struct context *ctx,unsigned long long generation)
{
    struct full_adf_input_state expected=*s;expected.fault=1;
    assert(full_adf_input_begin(s,generation,listener,ctx)==-1021);
    assert(!memcmp(s,&expected,sizeof expected) && !ctx->calls);
}
static void bad_pump(struct full_adf_input_state *s,struct context *ctx,unsigned long long generation)
{
    struct full_adf_input_state expected=*s;expected.fault=1;
    assert(full_adf_input_pump(s,generation)==-1021);
    assert(!memcmp(s,&expected,sizeof expected) && !ctx->calls);
}
int main(void)
{
    struct full_adf_input_state s;struct context ctx={&s,0,0};
    fresh(&s);
    assert(!full_adf_input_begin(&s,1,listener,&ctx));
    full_adf_input_completion saved=s.registered;
    assert(s.scheduler_registered==1 && !s.scheduler_consumed && s.request==1);
    assert(!s.pending && !s.complete && !s.controls && !ctx.calls);
    struct full_adf_input_state before=s;
    assert(full_adf_input_init(&s)==-1021 && !memcmp(&s,&before,sizeof s));
    assert(!full_adf_input_pump(&s,1));
    assert(ctx.calls==1 && s.complete && !s.fault && !s.request && !s.pending);
    assert(!s.registered && !s.submitted && !s.driver_callback && !s.driver_parameter);
    assert(s.scheduler_consumed==1 && s.controls==1 && s.readbacks==1 && s.callbacks==1);
    for(unsigned int i=0;i<32;i++)assert(!s.jobs[i].active && !s.jobs[i].generation && !s.jobs[i].priority);
    for(unsigned int i=0;i<5;i++)assert(!s.listeners[i].callback && !s.listeners[i].context && !s.listeners[i].generation);
    before=s;before.fault=1;
    saved(&s,0);
    assert(!memcmp(&s,&before,sizeof s) && ctx.calls==1);
    assert(full_adf_input_pump(&s,1)==-1021 && ctx.calls==1);
    assert(full_adf_input_begin(&s,1,listener,&ctx)==-1021 && ctx.calls==1);
    puts("ADF_INPUT_SCHEDULE_CONTROL_CALLBACK_DRAIN_PASS");

    for(unsigned int n=0;n<9;n++) {
        fresh(&s);ctx.calls=0;
        if(n==0)s.known=0;
        if(n==1)s.pending=1;
        if(n==2)s.generation=33;
        if(n==3)s.jobs[31].active=1;
        if(n==4)s.listeners[4].callback=listener;
        if(n==5)s.controls=1;
        if(n==6)s.driver_parameter=1;
        bad_begin(&s,&ctx,n==7?0:n==8?2:1);
    }
    fresh(&s);assert(full_adf_input_begin(&s,1,0,&ctx)==-1021 && !s.request);
    assert(full_adf_input_init(0)==-1021);
    assert(full_adf_input_begin(0,1,listener,&ctx)==-1021);
    assert(full_adf_input_pump(0,1)==-1021);
    unsigned int parameter;full_adf_input_completion callback;
    assert(full_adf_input_readback(0,&parameter,&callback)==-1021);
    fresh(&s);assert(full_adf_input_readback(&s,0,&callback)==-1021);
    assert(full_adf_input_readback(&s,&parameter,0)==-1021);
    for(unsigned int n=0;n<7;n++) {
        fresh(&s);ctx.calls=0;
        assert(!full_adf_input_begin(&s,1,listener,&ctx));
        if(n==0)s.jobs[0].priority=1;
        if(n==1)s.jobs[0].generation=33;
        if(n==2)s.jobs[31].active=1;
        if(n==3)s.listeners[1].callback=listener;
        if(n==4)s.pending=1;
        if(n==5)s.known=0;
        bad_pump(&s,&ctx,n==6?2:1);
    }
    puts("ADF_INPUT_UNKNOWN_DUPLICATE_STALE_REENTRY_PASS");
    for(unsigned int n=0;n<2;n++) {
        fresh(&s);ctx.calls=0;
        assert(!full_adf_input_begin(&s,1,listener,&ctx));
        before=s;before.fault=1;
        s.registered(&s,n);
        assert(!ctx.calls && !memcmp(&s,&before,sizeof s));
    }
    for(unsigned int n=1;n<=4;n++) {
        fresh(&s);ctx.calls=0;ctx.corrupt=n;
        assert(!full_adf_input_begin(&s,1,listener,&ctx));
        assert(full_adf_input_pump(&s,1)==-1021);
        assert(s.fault && !s.complete && ctx.calls==1 && s.submitted);
        assert(s.request==1 && s.jobs[0].active==1);
        if(n!=1)assert(s.pending==1);
    }
    puts("ADF_INPUT_PREMATURE_RECURSIVE_DUPLICATE_FANOUT_REJECTED");
    puts("ADF_INPUT_PREMATURE_CLEAR_BAD_READBACK_CROSS_GENERATION_PASS");
    return 0;
}
