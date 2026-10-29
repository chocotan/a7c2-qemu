/* SPDX-License-Identifier: MIT */
#include "adf-set-input-cold-owners.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static unsigned int cases;
struct hotshoe_context { struct full_adf_hotshoe_owner *owner; unsigned int calls, action; };
struct glee_context {
    struct full_adf_glee_input_owner *owner;
    struct full_adf_glee_input_owner physical_before;
    unsigned int calls, action;
};
static void hotshoe_callback(void *, unsigned int);
static void glee_callback(void *, unsigned int);
static void hotshoe_fresh(struct full_adf_hotshoe_owner *s)
{
    memset(s, 0, sizeof *s);
    assert(!full_adf_hotshoe_owner_init(s));
}
static void glee_fresh(struct full_adf_glee_input_owner *s)
{
    memset(s, 0, sizeof *s);
    assert(!full_adf_glee_input_owner_init(s));
}
static void same_physical(const struct full_adf_glee_input_owner *a,
                          const struct full_adf_glee_input_owner *b)
{
    assert(a->input_type == b->input_type && a->input_source == b->input_source);
    assert(a->input_callback_field == b->input_callback_field);
    assert(a->driver_parameter == b->driver_parameter && a->driver_callback == b->driver_callback);
    assert(a->driver_sentinel == b->driver_sentinel && a->kind_cache == b->kind_cache);
    assert(a->ring_read == b->ring_read && a->ring_write == b->ring_write && a->ring_count == b->ring_count);
    assert(!memcmp(a->ring, b->ring, sizeof a->ring));
    assert(!memcmp(&a->power, &b->power, sizeof a->power));
}
static void hotshoe_callback(void *opaque, unsigned int status)
{
    struct hotshoe_context *ctx = opaque;
    struct full_adf_hotshoe_owner *s = ctx->owner;
    assert(!status && s->busy == 1 && s->request == 1 && s->callback_active == 1);
    assert(s->fifo_read == 1 && s->fifo_write == 1 && !s->fifo_count && s->popped == 1);
    for (unsigned int i = 0; i < FULL_ADF_HOTSHOE_CALLBACK_CAPACITY; i++)
        assert(!s->fifo[i].callback && !s->fifo[i].context && !s->fifo[i].generation);
    assert(!s->current_type && !s->type_commits && !s->callbacks_returned && !s->complete);
    assert(s->callbacks_started == 1 && !ctx->calls);
    ctx->calls++;
    if (ctx->action == 1)
        assert(full_adf_hotshoe_set_type(s, 1, 0) == -1021);
    if (ctx->action == 2)
        assert(full_adf_hotshoe_register(s, 1, hotshoe_callback, ctx) == -1021);
    if (ctx->action == 3) s->field_c = 99;
    if (ctx->action == 4) s->current_type = 0x80;
    if (ctx->action == 5) s->generation = 2;
    if (ctx->action == 6) s->fifo[9].callback = hotshoe_callback;
}
static void glee_callback(void *opaque, unsigned int status)
{
    struct glee_context *ctx = opaque;
    struct full_adf_glee_input_owner *s = ctx->owner;
    assert(!status && s->request == 1 && s->callback_active == 1 && s->submitted == glee_callback);
    assert(s->context == ctx && s->callbacks_started == 1 && !s->callbacks_returned && !s->complete);
    assert(s->control30_notes == 1 && s->control30_complete == 1 && s->power.field_14 == 2);
    same_physical(s, &ctx->physical_before);
    unsigned int type = 99, source = 99, callback = 99;
    assert(!full_adf_glee_input_control1(s, &type, &source, &callback));
    assert(!type && source == 1 && !callback && !ctx->calls);
    ctx->calls++;
    if (ctx->action == 1)
        assert(full_adf_glee_input_control0(s, 1, 0, 0, 1, glee_callback, ctx) == -1021);
    if (ctx->action == 2)
        assert(full_adf_glee_input_note_control30(s, 1, 0, 0, 1) == -1021);
    if (ctx->action == 3) s->kind_cache = 1;
    if (ctx->action == 4) s->power.flag_22 = 1;
    if (ctx->action == 5) s->generation = 2;
    if (ctx->action == 6) s->ring[49][5] = 1;
}
static void bad_hotshoe_register(struct full_adf_hotshoe_owner *s, struct hotshoe_context *ctx,
                                 unsigned long long generation, full_adf_hotshoe_callback callback)
{
    struct full_adf_hotshoe_owner expected;
    memcpy(&expected, s, sizeof expected);
    expected.fault = 1;
    unsigned int calls = ctx->calls;
    assert(full_adf_hotshoe_register(s, generation, callback, ctx) == -1021);
    assert(!memcmp(s, &expected, sizeof expected) && ctx->calls == calls);
    cases++;
}
static void bad_hotshoe_set(struct full_adf_hotshoe_owner *s, struct hotshoe_context *ctx,
                            unsigned long long generation, unsigned int type)
{
    struct full_adf_hotshoe_owner expected;
    memcpy(&expected, s, sizeof expected);
    expected.fault = 1;
    unsigned int calls = ctx->calls;
    assert(full_adf_hotshoe_set_type(s, generation, type) == -1021);
    assert(!memcmp(s, &expected, sizeof expected) && ctx->calls == calls);
    cases++;
}
static void bad_glee_note(struct full_adf_glee_input_owner *s, unsigned long long generation,
                          unsigned int parameter, full_adf_glee_input_callback callback,
                          unsigned int complete)
{
    struct full_adf_glee_input_owner expected;
    memcpy(&expected, s, sizeof expected);
    expected.fault = 1;
    assert(full_adf_glee_input_note_control30(s, generation, parameter, callback, complete) == -1021);
    assert(!memcmp(s, &expected, sizeof expected));
    cases++;
}
static void bad_glee_control(struct full_adf_glee_input_owner *s, struct glee_context *ctx,
                             unsigned long long generation, unsigned int kind, unsigned int type,
                             unsigned int source, full_adf_glee_input_callback callback)
{
    struct full_adf_glee_input_owner expected;
    memcpy(&expected, s, sizeof expected);
    expected.fault = 1;
    unsigned int calls = ctx->calls;
    assert(full_adf_glee_input_control0(s, generation, kind, type, source, callback, ctx) == -1021);
    assert(!memcmp(s, &expected, sizeof expected) && ctx->calls == calls);
    cases++;
}
int main(void)
{
    struct full_adf_hotshoe_owner h, hcopy;
    struct full_adf_glee_input_owner g, gcopy;
    struct hotshoe_context hc = {&h, 0, 0};
    struct glee_context gc;
    memset(&gc, 0, sizeof gc);
    gc.owner = &g;
    hotshoe_fresh(&h);
    glee_fresh(&g);
    assert(g.input_type == 0 && g.input_source == 1 && !g.input_callback_field);
    assert(g.driver_sentinel == 0xff && g.power.field_14 == 2);
    assert(!full_adf_hotshoe_register(&h, 1, hotshoe_callback, &hc));
    assert(!hc.calls && h.fifo_read == 0 && h.fifo_write == 1 && h.fifo_count == 1);
    memcpy(&hcopy, &h, sizeof hcopy);
    assert(full_adf_hotshoe_owner_init(&h) == -1021 && !memcmp(&h, &hcopy, sizeof h));
    assert(!full_adf_hotshoe_set_type(&h, 1, 0));
    assert(hc.calls == 1 && !h.fault && h.complete == 1 && h.type_commits == 1);
    assert(!h.busy && !h.request && !h.callback_active && h.callbacks_returned == 1);
    assert(!h.current_type && !h.field_c && !h.field_10 && !h.field_14);
    cases++;
    bad_hotshoe_set(&h, &hc, 1, 0);
    bad_hotshoe_register(&h, &hc, 1, hotshoe_callback);
    puts("ADF_COLD_HOTSHOE_REAL_POP_CALLBACK_COMMIT_PASS");

    for (unsigned int n = 0; n < 16; n++) {
        hotshoe_fresh(&h); hc.calls = 0;
        if (n == 0) h.known = 0;
        if (n == 1) h.current_type = 0x80;
        if (n == 2) h.current_type = 8;
        if (n == 3) h.busy = 1;
        if (n == 4) h.field_c = 7;
        if (n == 5) h.field_8 = 1;
        if (n == 6) h.fifo_count = FULL_ADF_HOTSHOE_CALLBACK_CAPACITY;
        if (n == 7) h.fifo[9].callback = hotshoe_callback;
        if (n == 8) h.fault = 1;
        if (n == 9) h.generation = 1;
        if (n == 10) h.fifo[9].context = &hc;
        if (n == 11) h.fifo[9].generation = 1;
        if (n == 12) h.identity = 0;
        bad_hotshoe_register(&h, &hc, n == 13 ? 0 : n == 14 ? 2 : 1,
                              n == 15 ? 0 : hotshoe_callback);
    }
    for (unsigned int n = 0; n < 18; n++) {
        hotshoe_fresh(&h); hc.calls = 0;
        assert(!full_adf_hotshoe_register(&h, 1, hotshoe_callback, &hc));
        if (n == 0) h.current_type = 0x80;
        if (n == 1) h.current_type = 8;
        if (n == 2) h.fifo[0].callback = 0;
        if (n == 3) h.fifo[0].generation = 2;
        if (n == 4) h.fifo_count = 2;
        if (n == 5) h.fifo_read = 1;
        if (n == 6) h.fifo_write = 2;
        if (n == 7) h.fifo[9].callback = hotshoe_callback;
        if (n == 8) h.busy = 1;
        if (n == 9) h.field_10 = 4;
        if (n == 10) h.field_14 = 4;
        if (n == 11) h.known = 0;
        if (n == 12) h.request = 0;
        if (n == 13) h.popped = 1;
        if (n == 14) h.registered = 0;
        bad_hotshoe_set(&h, &hc, n == 15 ? 0 : n == 16 ? 2 : 1, n == 17 ? 1 : 0);
    }
    hotshoe_fresh(&h); hc.calls = 0;
    assert(!full_adf_hotshoe_register(&h, 1, hotshoe_callback, &hc));
    memcpy(&hcopy, &h, sizeof hcopy);
    bad_hotshoe_set(&hcopy, &hc, 1, 0);
    assert(!h.fault && h.fifo_count == 1 && !h.popped);
    for (unsigned int action = 1; action <= 6; action++) {
        hotshoe_fresh(&h); hc.calls = 0; hc.action = action;
        assert(!full_adf_hotshoe_register(&h, 1, hotshoe_callback, &hc));
        assert(full_adf_hotshoe_set_type(&h, 1, 0) == -1021);
        assert(hc.calls == 1 && h.fault && !h.complete && !h.type_commits);
        assert(h.busy == 1 && h.request == 1 && h.callback_active == 1 && !h.callbacks_returned);
        assert(h.popped == 1 && h.fifo_read == 1 && !h.fifo_count);
        if (action == 3) assert(h.field_c == 99);
        if (action == 4) assert(h.current_type == 0x80);
        if (action == 5) assert(h.generation == 2);
        if (action == 6) assert(h.fifo[9].callback == hotshoe_callback);
        cases++;
    }
    puts("ADF_COLD_HOTSHOE_STALE_FOREIGN_ASYNC_REENTRY_RETAINED_PASS");

    glee_fresh(&g);
    memcpy(&gc.physical_before, &g, sizeof g);
    assert(!full_adf_glee_input_note_control30(&g, 1, 0, 0, 1));
    same_physical(&g, &gc.physical_before);
    memcpy(&gcopy, &g, sizeof gcopy);
    assert(full_adf_glee_input_owner_init(&g) == -1021 && !memcmp(&g, &gcopy, sizeof g));
    assert(!full_adf_glee_input_control0(&g, 1, 0, 0, 1, glee_callback, &gc));
    assert(gc.calls == 1 && g.complete == 1 && !g.fault && g.callbacks_returned == 1);
    assert(!g.request && !g.submitted && !g.context && !g.callback_active);
    same_physical(&g, &gc.physical_before);
    unsigned int type = 99, source = 99, callback = 99;
    assert(!full_adf_glee_input_control1(&g, &type, &source, &callback));
    assert(!type && source == 1 && !callback);
    memcpy(&gcopy, &g, sizeof gcopy);
    assert(full_adf_glee_input_control1(&g, 0, &source, &callback) == -1021);
    assert(full_adf_glee_input_control1(&g, &type, 0, &callback) == -1021);
    assert(full_adf_glee_input_control1(&g, &type, &source, 0) == -1021);
    assert(!memcmp(&g, &gcopy, sizeof g));
    cases++;
    bad_glee_control(&g, &gc, 1, 0, 0, 1, glee_callback);
    bad_glee_note(&g, 1, 0, 0, 1);
    puts("ADF_COLD_GLEE_REAL_CALLBACK_NO_JOBS_NO_CACHE_POWER_WRITES_PASS");

    for (unsigned int n = 0; n < 12; n++) {
        glee_fresh(&g);
        if (n == 0) g.power.field_14 = 0;
        if (n == 1) g.kind_cache = 1;
        if (n == 2) g.ring[49][5] = 1;
        if (n == 3) g.known = 0;
        if (n == 4) g.control30_notes = 1;
        if (n == 5) g.fault = 1;
        bad_glee_note(&g, n == 6 ? 0 : n == 7 ? 2 : 1,
                         n == 8 ? 1 : 0, n == 9 ? glee_callback : 0,
                         n == 10 ? 0 : n == 11 ? 2 : 1);
    }
    for (unsigned int n = 0; n < 32; n++) {
        glee_fresh(&g); gc.calls = 0;
        if (n != 0) assert(!full_adf_glee_input_note_control30(&g, 1, 0, 0, 1));
        if (n == 1) g.power.flag_20 = 1;
        if (n == 2) g.power.flag_21 = 1;
        if (n == 3) g.power.flag_22 = 1;
        if (n == 4) g.power.field_14 = 0;
        if (n == 5) g.power.queue_count = 1;
        if (n == 6) g.power.field_c = 1;
        if (n == 7) g.power.field_10 = 1;
        if (n == 8) g.ring_count = 1;
        if (n == 9) g.ring_write = 1;
        if (n == 10) g.ring[49][5] = 1;
        if (n == 11) g.kind_cache = 1;
        if (n == 12) g.input_type = 1;
        if (n == 13) g.input_source = 2;
        if (n == 14) g.input_callback_field = 1;
        if (n == 15) g.driver_parameter = 1;
        if (n == 16) g.driver_callback = glee_callback;
        if (n == 17) g.driver_sentinel = 0;
        if (n == 18) g.control30_generation = 2;
        if (n == 19) g.control30_complete = 0;
        if (n == 20) g.control30_notes = 2;
        if (n == 21) g.generation = 1;
        if (n == 22) g.known = 0;
        if (n == 23) g.fault = 1;
        if (n == 24) g.identity = 0;
        bad_glee_control(&g, &gc, n == 25 ? 0 : n == 26 ? 2 : 1,
                         n == 27 ? 1 : 0, n == 28 ? 1 : 0,
                         n == 29 ? 0 : n == 30 ? 2 : 1, n == 31 ? 0 : glee_callback);
    }
    glee_fresh(&g); gc.calls = 0;
    assert(!full_adf_glee_input_note_control30(&g, 1, 0, 0, 1));
    memcpy(&gcopy, &g, sizeof gcopy);
    bad_glee_control(&gcopy, &gc, 1, 0, 0, 1, glee_callback);
    assert(!g.fault && !g.request && !g.generation);
    for (unsigned int action = 1; action <= 6; action++) {
        glee_fresh(&g); gc.calls = 0; gc.action = action;
        memcpy(&gc.physical_before, &g, sizeof g);
        assert(!full_adf_glee_input_note_control30(&g, 1, 0, 0, 1));
        assert(full_adf_glee_input_control0(&g, 1, 0, 0, 1, glee_callback, &gc) == -1021);
        assert(gc.calls == 1 && g.fault && !g.complete && !g.callbacks_returned);
        assert(g.request == 1 && g.callback_active == 1 && g.submitted == glee_callback && g.context == &gc);
        if (action == 3) assert(g.kind_cache == 1);
        if (action == 4) assert(g.power.flag_22 == 1);
        if (action == 5) assert(g.generation == 2);
        if (action == 6) assert(g.ring[49][5] == 1);
        type = source = callback = 99;
        assert(full_adf_glee_input_control1(&g, &type, &source, &callback) == -1021);
        assert(type == 99 && source == 99 && callback == 99);
        cases++;
    }
    puts("ADF_COLD_GLEE_MISSING_HISTORY_MUTATION_REENTRY_RETAINED_PASS");

    memset(&h, 0, sizeof h);
    memset(&g, 0, sizeof g);
    h.field_8 = 1; g.ring[49][5] = 1;
    memcpy(&hcopy, &h, sizeof hcopy); memcpy(&gcopy, &g, sizeof gcopy);
    assert(full_adf_hotshoe_owner_init(&h) == -1021 && !memcmp(&h, &hcopy, sizeof h));
    assert(full_adf_glee_input_owner_init(&g) == -1021 && !memcmp(&g, &gcopy, sizeof g));
    assert(full_adf_hotshoe_owner_init(0) == -1021);
    assert(full_adf_glee_input_owner_init(0) == -1021);
    assert(full_adf_hotshoe_register(0, 1, hotshoe_callback, &hc) == -1021);
    assert(full_adf_hotshoe_set_type(0, 1, 0) == -1021);
    assert(full_adf_glee_input_note_control30(0, 1, 0, 0, 1) == -1021);
    assert(full_adf_glee_input_control0(0, 1, 0, 0, 1, glee_callback, &gc) == -1021);
    assert(full_adf_glee_input_control1(0, &type, &source, &callback) == -1021);
    memset(&h, 0, sizeof h); memset(&g, 0, sizeof g);
    hc.calls = gc.calls = 0;
    bad_hotshoe_register(&h, &hc, 1, hotshoe_callback);
    bad_glee_note(&g, 1, 0, 0, 1);
    cases++;
    printf("ADF_SET_INPUT_COLD_OWNERS_CASES=%u\n", cases);
    return 0;
}
