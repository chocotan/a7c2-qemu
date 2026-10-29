/* SPDX-License-Identifier: MIT */
#include "cp-parameter-view.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define N CP_PARAMETER_VIEW_OVERRIDE_BYTES
#define C CP_PARAMETER_VIEW_CONFIG_BYTES
struct fixture {
    struct cp_parameter_state source;
    struct cp_parameter_view view;
    struct cp_start_state_guard guard;
    unsigned char bytes[N + 16], known[N + 16];
    unsigned char config[C + 16], config_known[C + 16];
    struct cp_parameter_view_flagb_readback flagb;
};

static void sequence(struct fixture *f, uint64_t n)
{
    f->guard.sequence_before = n;
    f->guard.sequence_after = n;
}

static void fresh(struct fixture *f)
{
    memset(f, 0xa5, sizeof(*f));
    assert(cp_parameter_state_init(&f->source, true) == 0);
    /* Unknown storage deliberately differs from zero; its contents are opaque. */
    memset(f->source.bytes, 0xa5, sizeof(f->source.bytes));
    assert(cp_parameter_view_init(&f->view) == 0);
    memset(&f->guard, 0, sizeof(f->guard));
    f->guard.owner_pid = (uint32_t)getpid();
    f->guard.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    f->guard.quiescent = 1;
    sequence(f, 4);
    assert(f->view.source_origin == CP_START_STATE_ORIGIN_NONE);
    assert(f->view.source_sequence == 0 && !f->view.copy_consumed);
    assert(!f->view.config_source_known && !f->view.config_word_known);
    assert(!f->view.bank3_bound && !f->view.bank3_invalidated && !f->view.flagb_known);
    assert(f->view.config_source_word == 0 && f->view.config_word == 0);
    assert(f->view.config_copy_event == CP_PARAMETER_VIEW_CONFIG_COPY_NONE);
    assert(f->view.config_copy_input == CP_PARAMETER_VIEW_CONFIG_INPUT_NONE);
    assert(f->view.constructor_store_sequence == 0 && f->view.config_copy_sequence == 0);
    assert(f->view.bank3_sequence == 0 && f->view.flagb_store_sequence == 0);
    memset(f->config_known, 0, sizeof(f->config_known));
    for (size_t i = 0; i < sizeof(f->view.known_mask); ++i)
        assert(f->view.known_mask[i] == 0);
}

static void copy(struct fixture *f)
{
    struct cp_parameter_state before = f->source;
    assert(cp_parameter_view_consume_initial_copy(&f->view, &f->guard,
                                                  &f->source) == 0);
    assert(memcmp(&before, &f->source, sizeof(before)) == 0);
    assert(memcmp(f->view.bytes, f->source.bytes, sizeof(f->view.bytes)) == 0);
    assert(memcmp(f->view.known_mask, f->source.known_mask,
                  sizeof(f->view.known_mask)) == 0);
    assert(f->view.copy_consumed == 1 && !f->view.bank0_bound);
    assert(f->view.copy_sequence == 4 && f->view.source_sequence == 4);
    assert(f->view.source_origin == f->guard.source_origin);
}

static void bind(struct fixture *f)
{
    sequence(f, 6);
    assert(cp_parameter_view_consume_bank0_binding(&f->view, &f->guard,
                   CP_PARAMETER_VIEW_PUBLISHED_VA) == 0);
    assert(f->view.bank0_bound == 1 && f->view.bank_sequence == 6);
    assert(f->view.source_sequence == 6 && f->view.copy_sequence == 4);
}

static int output(struct fixture *f)
{
    return cp_parameter_view_copy_override_span(&f->view, &f->guard,
        f->bytes, sizeof(f->bytes), f->known, sizeof(f->known));
}

static void verify_output(struct fixture *f)
{
    struct cp_parameter_view before = f->view;
    memset(f->bytes, 0x73, sizeof(f->bytes));
    memset(f->known, 0xfe, sizeof(f->known));
    assert(output(f) == 0);
    assert(memcmp(&before, &f->view, sizeof(before)) == 0);
    assert(memcmp(f->bytes, f->view.bytes, N) == 0);
    for (size_t i = 0; i < N; ++i) {
        unsigned char bit = (unsigned char)((f->view.known_mask[i / 8u] >>
                                             (i % 8u)) & 1u);
        assert(f->known[i] == bit && f->known[i] <= 1);
    }
    for (size_t i = N; i < sizeof(f->bytes); ++i) {
        assert(f->bytes[i] == 0x73);
        assert(f->known[i] == 0xfe);
    }
}

static struct cp_start_state_span config_span(struct fixture *f)
{
    struct cp_start_state_span s = {f->config, f->config_known, C, sizeof(f->config_known)};
    return s;
}

static void config_word(struct fixture *f, uint32_t word)
{
    memset(f->config_known, 0, sizeof(f->config_known));
    for (size_t i = 0; i < 4; ++i) {
        f->config[CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET + i] = (unsigned char)(word >> (8u * i));
        f->config_known[CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET + i] = 1;
    }
}

static void config_initial(struct fixture *f, uint64_t start)
{
    sequence(f, start);
    assert(cp_parameter_view_consume_config_constructor_store(&f->view, &f->guard) == 0);
    sequence(f, start + 2);
    assert(cp_parameter_view_consume_config_copy(&f->view, &f->guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, NULL) == 0);
    sequence(f, start + 4);
    assert(cp_parameter_view_consume_bank3_binding(&f->view, &f->guard,
               CP_PARAMETER_VIEW_BANK3_VA) == 0);
    sequence(f, start + 6);
    assert(cp_parameter_view_consume_flagb_store(&f->view, &f->guard) == 0);
    assert(cp_parameter_view_copy_flagb(&f->view, &f->guard, &f->flagb) == 0);
    assert(f->flagb.flagb == 0 && f->flagb.config_word == 2);
}

static void test_copy_events(void)
{
    struct fixture f;
    struct cp_parameter_view before;
    size_t count = 0;
    fresh(&f);
    before = f.view;
    assert(output(&f) == -ENODATA);
    assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_PUBLISHED_VA) == -ENODATA);
    assert(cp_parameter_view_invalidate(&f.view, &f.guard) == -ENODATA);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    assert(cp_parameter_state_consume_common_stores(&f.source) == 0);
    for (size_t i = 0; i < CP_PARAMETER_STATE_IMAGE_BYTES; ++i)
        count += (f.source.known_mask[i / 8u] >> (i % 8u)) & 1u;
    assert(count == CP_PARAMETER_STATE_COMMON_LOCAL_BYTES && count == 694);
    copy(&f);
    before = f.view;
    assert(output(&f) == -ENODATA);
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                  &f.source) == -EBUSY);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    bind(&f);
    verify_output(&f);
    assert(f.known[0x1c8] == 1 && f.bytes[0x1c8] == 0);
    assert(f.known[0] == 0 && f.bytes[0] == 0xa5);
    before = f.view;
    assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_PUBLISHED_VA) == -EBUSY);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    /* Later guarded reads observe the original copy, not the new mutable P. */
    assert(cp_parameter_state_init(&f.source, true) == 0);
    sequence(&f, 8);
    verify_output(&f);
    assert(f.known[0x1c8] == 1 && f.bytes[0x1c8] == 0);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    assert(f.view.source_sequence == 6);
}

static void test_unknown_and_padding(void)
{
    struct fixture f;
    fresh(&f);
    /* Unused high bits of the packed mask are opaque, not extra image bytes. */
    f.source.known_mask[CP_PARAMETER_STATE_KNOWN_BYTES - 1] = 0xf0;
    copy(&f);
    bind(&f);
    verify_output(&f);
    for (size_t i = 0; i < N; ++i)
        assert(f.known[i] == 0 && f.bytes[i] == 0xa5);
    assert(f.view.known_mask[CP_PARAMETER_STATE_KNOWN_BYTES - 1] == 0xf0);
    fresh(&f);
    assert(cp_parameter_state_consume_reset_store(&f.source) == 0);
    copy(&f);
    bind(&f);
    verify_output(&f);
    for (size_t i = 0; i < N; ++i)
        assert(f.known[i] == (i == 0x1c8 ? 1 : 0));
}

static void test_host_values_and_lifetime(void)
{
    struct fixture f;
    for (unsigned value = 0; value < 256; ++value) {
        fresh(&f);
        f.guard.source_origin = CP_START_STATE_ORIGIN_HOST_TEST;
        assert(cp_parameter_state_consume_reset_store(&f.source) == 0);
        /* HOST_TEST fixture injection only; no unmodeled source setter claim. */
        f.source.bytes[0x1c8] = (unsigned char)value;
        copy(&f);
        bind(&f);
        f.source.bytes[0x1c8] = (unsigned char)(value ^ 0xffu);
        assert(cp_parameter_state_init(&f.source, true) == 0);
        verify_output(&f);
        assert(f.bytes[0x1c8] == value && f.known[0x1c8] == 1);
        assert(f.view.source_origin == CP_START_STATE_ORIGIN_HOST_TEST);
    }
    {
        struct cp_parameter_state *source = malloc(sizeof(*source));
        assert(source != NULL);
        fresh(&f);
        assert(cp_parameter_state_init(source, true) == 0);
        assert(cp_parameter_state_consume_reset_store(source) == 0);
        assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard, source) == 0);
        free(source);
        bind(&f);
        verify_output(&f);
        assert(f.bytes[0x1c8] == 0 && f.known[0x1c8] == 1);
    }
}

static void test_rebind_revokes(void)
{
    struct fixture f;
    struct cp_parameter_view before;
    fresh(&f);
    copy(&f);
    bind(&f);
    before = f.view;
    sequence(&f, 8);
    assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard,
                   CP_PARAMETER_STATE_SOURCE_VA) == -ENOTSUP);
    assert(f.view.invalidated && !f.view.bank0_bound);
    assert(f.view.source_sequence == 8 && f.view.bank_sequence == 6);
    assert(memcmp(before.bytes, f.view.bytes, sizeof(before.bytes)) == 0);
    assert(memcmp(before.known_mask, f.view.known_mask, sizeof(before.known_mask)) == 0);
    assert(output(&f) == -ESTALE);
    before = f.view;
    assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_PUBLISHED_VA) == -ESTALE);
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                  &f.source) == -EBUSY);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    fresh(&f);
    copy(&f);
    bind(&f);
    sequence(&f, 8);
    assert(cp_parameter_view_invalidate(&f.view, &f.guard) == 0);
    assert(output(&f) == -ESTALE);
    assert(f.view.copy_sequence == 4 && f.view.bank_sequence == 6);
    fresh(&f);
    copy(&f);
    assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard, 0) == -ENOTSUP);
    assert(f.view.invalidated && !f.view.bank0_bound);
}

static void test_guard_failures(void)
{
    struct fixture f;
    struct cp_parameter_view before;
    struct cp_start_state_guard good;
    fresh(&f);
    copy(&f);
    bind(&f);
    before = f.view;
    good = f.guard;
    for (unsigned i = 0; i < 8; ++i) {
        int expected;
        f.guard = good;
        switch (i) {
        case 0: f.guard.owner_pid++; expected = -EXDEV; break;
        case 1: f.guard.source_origin = CP_START_STATE_ORIGIN_HOST_TEST;
                expected = -EXDEV; break;
        case 2: f.guard.source_origin = CP_START_STATE_ORIGIN_NONE;
                expected = -EINVAL; break;
        case 3: f.guard.quiescent = 0; expected = -EAGAIN; break;
        case 4: f.guard.quiescent = 2; expected = -EAGAIN; break;
        case 5: f.guard.sequence_after = 8; expected = -EAGAIN; break;
        case 6: sequence(&f, 7); expected = -EAGAIN; break;
        default: sequence(&f, 4); expected = -ESTALE; break;
        }
        assert(output(&f) == expected);
        assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                      &f.source) == expected);
        assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard, 0) == expected);
        assert(cp_parameter_view_invalidate(&f.view, &f.guard) == expected);
        assert(cp_parameter_view_consume_config_constructor_store(&f.view, &f.guard) == expected);
        assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, NULL) == expected);
        assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard, 0) == expected);
        assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == expected);
        assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == expected);
        assert(memcmp(&before, &f.view, sizeof(before)) == 0);
        for (size_t j = 0; j < sizeof(f.flagb); ++j)
            assert(((unsigned char *)(void *)&f.flagb)[j] == 0xa5);
        for (size_t j = 0; j < sizeof(f.bytes); ++j) {
            assert(f.bytes[j] == 0xa5 && f.known[j] == 0xa5);
        }
    }
    f.guard = good;
    sequence(&f, UINT64_MAX - 1);
    verify_output(&f);
    assert(cp_parameter_view_invalidate(&f.view, &f.guard) == 0);
    assert(f.view.source_sequence == UINT64_MAX - 1);
    sequence(&f, 6);
    assert(output(&f) == -ESTALE);
}

static void test_source_validation(void)
{
    struct fixture f;
    struct cp_parameter_view before;
    fresh(&f);
    before = f.view;
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard, NULL) == -EINVAL);
    assert(cp_parameter_state_init(&f.source, false) == 0);
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                  &f.source) == -EACCES);
    assert(cp_parameter_state_init(&f.source, true) == 0);
    f.source.magic = 0;
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                  &f.source) == -EINVAL);
    assert(cp_parameter_state_init(&f.source, true) == 0);
    f.source.batch.owner_pid++;
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                  &f.source) == -ECHILD);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
}

static void test_alias_and_capacity(void)
{
    struct fixture f, before;
    union aligned {
        max_align_t alignment;
        unsigned char raw[sizeof(struct fixture) + 32];
    } storage;
    struct cp_start_state_guard *bad_guard;
    struct cp_parameter_state *bad_source;
    struct cp_parameter_view *bad_view;
    union shared_source_guard {
        struct cp_parameter_state source;
        struct cp_start_state_guard guard;
    } shared;
    fresh(&f);
    before = f;
    bad_source = (struct cp_parameter_state *)(void *)&f.view;
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard, bad_source) == -EINVAL);
    bad_guard = (struct cp_start_state_guard *)(void *)&f.source;
    assert(cp_parameter_view_consume_initial_copy(&f.view, bad_guard, &f.source) < 0);
    bad_guard = (struct cp_start_state_guard *)(void *)&f.view;
    assert(cp_parameter_view_consume_initial_copy(&f.view, bad_guard, &f.source) == -EINVAL);
    assert(memcmp(&before, &f, sizeof(before)) == 0);
    shared.guard = f.guard;
    /* A fully valid guard still cannot reside in the source being copied. */
    assert(cp_parameter_view_consume_initial_copy(&f.view, &shared.guard,
                                                  &shared.source) == -EINVAL);
    assert(memcmp(&before.view, &f.view, sizeof(f.view)) == 0);
    bad_source = (struct cp_parameter_state *)(void *)(storage.raw + 1);
    assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard, bad_source) == -EINVAL);
    bad_guard = (struct cp_start_state_guard *)(void *)(storage.raw + 1);
    assert(cp_parameter_view_consume_initial_copy(&f.view, bad_guard, &f.source) == -EINVAL);
    bad_view = (struct cp_parameter_view *)(void *)(storage.raw + 1);
    assert(cp_parameter_view_init(bad_view) == -EINVAL);
    assert(cp_parameter_view_consume_initial_copy(bad_view, &f.guard, &f.source) == -EINVAL);
    assert(cp_parameter_view_init(NULL) == -EINVAL);
    assert(cp_parameter_view_consume_initial_copy(NULL, &f.guard, &f.source) == -EINVAL);
    assert(cp_parameter_view_consume_initial_copy(&f.view, NULL, &f.source) == -EINVAL);
    copy(&f);
    bind(&f);
    before = f;
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, NULL, N,
                                                f.known, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N,
                                                NULL, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N - 1,
                                                f.known, N) == -EMSGSIZE);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N,
                                                f.known, N - 1) == -EMSGSIZE);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, 0,
                                                f.known, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, SIZE_MAX,
                                                f.known, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N,
                                                f.known, SIZE_MAX) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.view.bytes, N,
                                                f.known, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N,
                                                f.view.bytes, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard,
             (unsigned char *)(void *)&f.guard, N, f.known, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N,
             (unsigned char *)(void *)&f.guard, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes, N,
                                                f.bytes, N) == -EINVAL);
    /* Only the declared tail overlaps: logical N-byte spans alone are disjoint. */
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.bytes,
             sizeof(f.bytes) + 1, f.known, N) == -EINVAL);
    assert(cp_parameter_view_copy_override_span(&f.view, &f.guard, f.known, N,
             f.bytes, sizeof(f.bytes) + 1) == -EINVAL);
    assert(memcmp(&before, &f, sizeof(before)) == 0);
    {
        struct {
            unsigned char prefix[N + 16];
            struct cp_parameter_view view;
            struct cp_start_state_guard guard;
            unsigned char known[N];
        } adjacent;
        memset(&adjacent, 0, sizeof(adjacent));
        assert(cp_parameter_view_init(&adjacent.view) == 0);
        adjacent.guard = f.guard;
        assert(cp_parameter_view_copy_override_span(&adjacent.view, &adjacent.guard,
             adjacent.prefix, sizeof(adjacent), adjacent.known, N) == -EINVAL);
    }
}

static void test_fork(void)
{
    struct fixture f;
    int status;
    pid_t pid;
    fresh(&f);
    assert(cp_parameter_state_consume_reset_store(&f.source) == 0);
    copy(&f);
    bind(&f);
    config_initial(&f, 8);
    pid = fork();
    assert(pid >= 0);
    if (pid == 0) {
        assert(output(&f) == -EXDEV);
        assert(cp_parameter_view_consume_bank0_binding(&f.view, &f.guard, 0) == -EXDEV);
        assert(cp_parameter_view_invalidate(&f.view, &f.guard) == -EXDEV);
        assert(cp_parameter_view_consume_config_constructor_store(&f.view, &f.guard) == -EXDEV);
        assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, NULL) == -EXDEV);
        assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard, 0) == -EXDEV);
        assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -EXDEV);
        assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -EXDEV);
        assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                      &f.source) == -EXDEV);
        assert(cp_parameter_view_init(&f.view) == 0);
        f.guard.owner_pid = (uint32_t)getpid();
        assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                      &f.source) == -ECHILD);
        assert(cp_parameter_state_init(&f.source, true) == 0);
        assert(cp_parameter_view_consume_initial_copy(&f.view, &f.guard,
                                                      &f.source) == 0);
        _exit(0);
    }
    assert(waitpid(pid, &status, 0) == pid);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    verify_output(&f);
}

static void test_real_lif_consumer(void)
{
    struct fixture f;
    struct cp_start_state_data data, before;
    struct cp_start_state_readback rb;
    unsigned char lif[CP_START_STATE_LIF_BYTES] = {0};
    unsigned char mask[CP_START_STATE_LIF_BYTES] = {0};
    struct cp_start_state_span ls = {lif, mask, sizeof(lif), sizeof(mask)};
    struct cp_start_state_span bs = {f.bytes, f.known, N, N};
    fresh(&f);
    assert(cp_parameter_state_consume_common_stores(&f.source) == 0);
    copy(&f);
    bind(&f);
    verify_output(&f);
    assert(cp_start_state_data_init(&data) == 0);
    before = data;
    assert(cp_start_state_data_consume_lif(&data, &f.guard, &ls, &bs, NULL) == -ENODATA);
    assert(memcmp(&before, &data, sizeof(before)) == 0);
    lif[0x81] = 0x62; lif[0x82] = 1; lif[0x83] = 0x32;
    lif[0x84] = 0x22; lif[0x128] = 1;
    for (size_t i = 0x81; i <= 0x87; ++i) mask[i] = 1;
    mask[0x128] = 1;
    assert(cp_start_state_data_consume_lif(&data, &f.guard, &ls, &bs, NULL) == 0);
    assert(cp_start_state_data_snapshot(&data, &f.guard, &rb) == 0);
    assert(rb.known_mask == 7 && rb.data[0] == 1 && rb.data[1] == 1);
    assert(rb.lif_consumed == 1 && rb.source_origin == CP_START_STATE_ORIGIN_VIRTUAL_SOURCE);
    assert(!rb.data_ready && !rb.business_ready && !rb.configuration_ready);
    assert(!rb.published && !rb.ap_applied && rb.publication_generation == 0);
    before = data;
    f.known[0] = 2;
    assert(cp_start_state_data_consume_lif(&data, &f.guard, &ls, &bs, NULL) == -EINVAL);
    assert(memcmp(&before, &data, sizeof(before)) == 0);
    /* The same actual LIF inputs cannot turn an unknown copied mode into zero. */
    fresh(&f);
    copy(&f);
    bind(&f);
    verify_output(&f);
    assert(cp_start_state_data_init(&data) == 0);
    before = data;
    assert(cp_start_state_data_consume_lif(&data, &f.guard, &ls, &bs, NULL) == -ENODATA);
    assert(memcmp(&before, &data, sizeof(before)) == 0);
}

static void test_config_events(void)
{
    struct fixture f;
    struct cp_parameter_view before;
    struct cp_parameter_view_flagb_readback old_output;
    struct cp_start_state_span s;
    fresh(&f);
    s = config_span(&f);
    before = f.view;
    old_output = f.flagb;
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ENODATA);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -ENODATA);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, NULL) == -ENODATA);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, &s) == -ENODATA);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_BANK3_VA) == -ENODATA);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    assert(memcmp(&old_output, &f.flagb, sizeof(old_output)) == 0);
    copy(&f);
    bind(&f);
    before = f.view;
    sequence(&f, 8);
    assert(cp_parameter_view_consume_config_constructor_store(&f.view, &f.guard) == 0);
    assert(f.view.config_source_known == 1 && f.view.config_source_word == 2);
    assert(!f.view.config_word_known && !f.view.flagb_known && !f.view.bank3_bound);
    assert(cp_parameter_view_consume_config_constructor_store(&f.view, &f.guard) == -EBUSY);
    sequence(&f, 10);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, NULL) == 0);
    assert(f.view.config_word_known == 1 && f.view.config_word == 2);
    assert(!f.view.bank3_bound && !f.view.flagb_known);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -ENODATA);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, NULL) == -EBUSY);
    assert(cp_parameter_view_consume_config_constructor_store(&f.view, &f.guard) == -EBUSY);
    sequence(&f, 12);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_BANK3_VA) == 0);
    assert(f.view.bank3_bound == 1 && !f.view.flagb_known);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ENODATA);
    assert(memcmp(&old_output, &f.flagb, sizeof(old_output)) == 0);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_BANK3_VA) == -EBUSY);
    sequence(&f, 14);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == 0);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == 0);
    assert(f.flagb.flagb == 0 && f.flagb.config_word == 2);
    assert(f.flagb.owner_pid == (uint32_t)getpid());
    assert(f.flagb.source_origin == CP_START_STATE_ORIGIN_VIRTUAL_SOURCE);
    assert(f.flagb.config_copy_event == CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL);
    assert(f.flagb.config_copy_input == CP_PARAMETER_VIEW_CONFIG_INPUT_CONSTRUCTOR);
    assert(f.flagb.constructor_store_sequence == 8 && f.flagb.config_copy_sequence == 10);
    assert(f.flagb.bank3_sequence == 12 && f.flagb.flagb_store_sequence == 14);
    assert(f.flagb.source_sequence == 14);
    assert(f.view.copy_sequence == before.copy_sequence && f.view.bank_sequence == before.bank_sequence);
    assert(f.view.copy_consumed && f.view.bank0_bound && !f.view.invalidated);
    assert(memcmp(before.bytes, f.view.bytes, sizeof(before.bytes)) == 0);
    assert(memcmp(before.known_mask, f.view.known_mask, sizeof(before.known_mask)) == 0);
    verify_output(&f);
    before = f.view;
    old_output = f.flagb;
    sequence(&f, 16);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ESTALE);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    assert(memcmp(&old_output, &f.flagb, sizeof(old_output)) == 0);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == 0);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == 0);
    assert(f.flagb.flagb_store_sequence == 16 && f.flagb.config_copy_sequence == 10);
}

static void test_config_recopies(void)
{
    struct fixture f;
    struct cp_start_state_span s;
    struct cp_parameter_view before;
    struct cp_parameter_view_flagb_readback old_output;
    static const uint32_t values[] = {0, 1, 2, 0x100, 0x1000000, UINT32_MAX};
    fresh(&f);
    f.guard.source_origin = CP_START_STATE_ORIGIN_HOST_TEST;
    config_initial(&f, 4);
    s = config_span(&f);
    old_output = f.flagb;
    config_word(&f, 0);
    f.config_known[CP_PARAMETER_VIEW_CONFIG_WORD_OFFSET + 3] = 0;
    sequence(&f, 12);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, &s) == 0);
    assert(!f.view.config_source_known && !f.view.config_word_known);
    assert(!f.view.flagb_known && f.view.bank3_bound);
    assert(f.view.flagb_store_sequence == 10 && f.view.config_copy_sequence == 12);
    before = f.view;
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -ENODATA);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ENODATA);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    assert(memcmp(&old_output, &f.flagb, sizeof(old_output)) == 0); /* Old zero refused. */
    for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        config_word(&f, values[i]);
        f.config_known[C] = 2; /* Capacity tail is not a logical mask byte. */
        sequence(&f, 14 + 4 * i);
        assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, &s) == 0);
        assert(f.view.config_word_known && f.view.config_word == values[i]);
        assert(f.view.config_source_known && f.view.config_source_word == values[i]);
        assert(!f.view.flagb_known);
        assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ENODATA);
        sequence(&f, 16 + 4 * i);
        assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == 0);
        assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == 0);
        assert(f.flagb.config_word == values[i] && f.flagb.flagb == (values[i] == 0));
        assert(f.flagb.source_origin == CP_START_STATE_ORIGIN_HOST_TEST);
        assert(f.flagb.config_copy_input == CP_PARAMETER_VIEW_CONFIG_INPUT_SPAN);
        assert(f.flagb.config_copy_event == CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY);
        assert(f.flagb.config_copy_sequence == 14 + 4 * i);
        assert(f.flagb.flagb_store_sequence == 16 + 4 * i);
        assert(f.flagb.constructor_store_sequence == 4 && f.flagb.bank3_sequence == 8);
        memset(f.config, 0xff, sizeof(f.config));
        assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == 0);
        assert(f.flagb.config_word == values[i]);
    }
    /* Same guard and equal known word still require a fresh getter/store. */
    config_word(&f, UINT32_MAX);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, &s) == 0);
    assert(!f.view.flagb_known);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ENODATA);
    assert(!f.view.copy_consumed && !f.view.bank0_bound);
    fresh(&f);
    s = config_span(&f);
    /* A real unknown initial span is allowed; zero storage is never a value. */
    memset(f.config, 0, sizeof(f.config));
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, &s) == 0);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_BANK3_VA) == 0);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -ENODATA);
    assert(!f.view.config_source_known && !f.view.config_word_known);
    fresh(&f);
    s = config_span(&f);
    config_word(&f, 0);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, &s) == 0);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_BANK3_VA) == 0);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == 0);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == 0);
    assert(f.flagb.flagb == 1 && f.flagb.constructor_store_sequence == 0);
    assert(f.flagb.config_copy_input == CP_PARAMETER_VIEW_CONFIG_INPUT_SPAN);
}

static void test_bank3_wrong_root_preserves_bank0(void)
{
    struct fixture f;
    struct cp_parameter_view before;
    struct cp_parameter_view_flagb_readback old_output;
    fresh(&f);
    copy(&f);
    bind(&f);
    config_initial(&f, 8);
    before = f.view;
    old_output = f.flagb;
    sequence(&f, 16);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_PUBLISHED_VA) == -ENOTSUP);
    assert(f.view.bank3_invalidated && !f.view.bank3_bound && !f.view.flagb_known);
    assert(f.view.bank0_bound && !f.view.invalidated && f.view.copy_consumed);
    assert(f.view.copy_sequence == 4 && f.view.bank_sequence == 6);
    assert(f.view.config_copy_sequence == 10 && f.view.bank3_sequence == 12);
    assert(f.view.flagb_store_sequence == 14 && f.view.source_sequence == 16);
    assert(memcmp(before.bytes, f.view.bytes, sizeof(before.bytes)) == 0);
    assert(memcmp(before.known_mask, f.view.known_mask, sizeof(before.known_mask)) == 0);
    verify_output(&f);
    before = f.view;
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, &f.flagb) == -ESTALE);
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -ESTALE);
    assert(cp_parameter_view_consume_bank3_binding(&f.view, &f.guard,
               CP_PARAMETER_VIEW_BANK3_VA) == -ESTALE);
    assert(memcmp(&before, &f.view, sizeof(before)) == 0);
    assert(memcmp(&old_output, &f.flagb, sizeof(old_output)) == 0);
}

static void test_config_alias_and_atomic_errors(void)
{
    struct fixture f, before;
    struct cp_start_state_span s, good;
    union { max_align_t alignment; unsigned char raw[sizeof(struct fixture)]; } storage;
    struct {
        unsigned char known[C];
        struct cp_parameter_view view;
        struct cp_start_state_guard guard;
    } adjacent;
    fresh(&f);
    copy(&f);
    bind(&f);
    config_initial(&f, 8);
    config_word(&f, 0);
    good = config_span(&f);
    before = f;
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_NONE, &good) == -ENOTSUP);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, NULL) == -EINVAL);
    for (unsigned i = 0; i < 13; ++i) {
        int expected = -EINVAL;
        s = good;
        switch (i) {
        case 0: s.size--; expected = -EMSGSIZE; break;
        case 1: s.known_size = C - 1; expected = -EMSGSIZE; break;
        case 2: s.bytes = NULL; break;
        case 3: s.known = NULL; break;
        case 4: s.bytes = (const unsigned char *)(uintptr_t)(UINTPTR_MAX - 16); break;
        case 5: s.known_size = SIZE_MAX; break;
        case 6: s.bytes = f.view.bytes; break;
        case 7: s.known = f.view.bytes; break;
        case 8: s.bytes = (const unsigned char *)(const void *)&f.guard; break;
        case 9: s.known = (const unsigned char *)(const void *)&f.guard; break;
        case 10: s.bytes = s.known; break;
        case 11: s.bytes = (const unsigned char *)(const void *)&s; break;
        default: s.known = (const unsigned char *)(const void *)&s; break;
        }
        assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
                   CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, &s) == expected);
    }
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY,
               (const struct cp_start_state_span *)(const void *)&f.view) == -EINVAL);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY,
               (const struct cp_start_state_span *)(const void *)&f.guard) == -EINVAL);
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY,
               (const struct cp_start_state_span *)(const void *)(storage.raw + 1)) == -EINVAL);
    f.config_known[C - 1] = 2;
    assert(cp_parameter_view_consume_config_copy(&f.view, &f.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY, &good) == -EINVAL);
    f.config_known[C - 1] = 0;
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard, NULL) == -EINVAL);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard,
               (struct cp_parameter_view_flagb_readback *)(void *)&f.view) == -EINVAL);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard,
               (struct cp_parameter_view_flagb_readback *)(void *)&f.guard) == -EINVAL);
    assert(cp_parameter_view_copy_flagb(&f.view, &f.guard,
               (struct cp_parameter_view_flagb_readback *)(void *)(storage.raw + 1)) == -EINVAL);
    assert(memcmp(&before, &f, sizeof(before)) == 0);
    memset(&adjacent, 0, sizeof(adjacent));
    assert(cp_parameter_view_init(&adjacent.view) == 0);
    adjacent.guard = f.guard;
    s = good;
    s.known = adjacent.known;
    s.known_size = sizeof(adjacent.known) + sizeof(adjacent.view);
    assert(cp_parameter_view_consume_config_copy(&adjacent.view, &adjacent.guard,
               CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, &s) == -EINVAL);
    assert(adjacent.view.source_origin == CP_START_STATE_ORIGIN_NONE);
    assert(!adjacent.view.config_copy_event && !adjacent.view.config_word_known);
    /* A malformed owned known byte is not treated as a truthy value. */
    f.view.config_word_known = 2;
    assert(cp_parameter_view_consume_flagb_store(&f.view, &f.guard) == -EINVAL);
    f.view.config_word_known = 1;
    assert(memcmp(&before, &f, sizeof(before)) == 0);
}

int main(void)
{
    test_copy_events();
    test_unknown_and_padding();
    test_host_values_and_lifetime();
    test_rebind_revokes();
    test_guard_failures();
    test_source_validation();
    test_alias_and_capacity();
    test_fork();
    test_real_lif_consumer();
    test_config_events();
    test_config_recopies();
    test_bank3_wrong_root_preserves_bank0();
    test_config_alias_and_atomic_errors();
    return 0;
}
