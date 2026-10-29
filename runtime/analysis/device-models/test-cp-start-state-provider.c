/* SPDX-License-Identifier: MIT */
#include "cp-start-state-provider.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

enum { SECTIONS = 0x126, PROPERTIES = 7,
       DATA = 0x100 + SECTIONS * 6 + PROPERTIES * 6,
       BANK_BYTES = DATA + 2 + CP_START_STATE_PROPERTY_CONTEXT_BYTES };
static void put16(unsigned char *b, unsigned v)
{ b[0] = (unsigned char)v; b[1] = (unsigned char)(v >> 8); }
static void put32(unsigned char *b, uint32_t v)
{ put16(b, v); put16(b + 2, v >> 16); }
static void checksum(unsigned char *b, size_t n)
{
    uint32_t sum = 0;
    for (size_t i = 0; i < n; ++i) if (i < 0x20 || i >= 0x24) sum += b[i];
    put32(b + 0x20, sum);
}
static void fixture(unsigned char *b, unsigned profile)
{
    memset(b, 0, BANK_BYTES);
    memcpy(b + 12, "BK4\0", 4);
    put32(b + 16, SECTIONS); put32(b + 20, PROPERTIES);
    put32(b + 24, DATA); put32(b + 28, BANK_BYTES - DATA);
    put16(b + 0x100 + 0x125 * 6, PROPERTIES);
    put32(b + 0x100 + SECTIONS * 6 + 6 * 6 + 2,
          UINT32_C(0xff000000) | DATA);
    put16(b + DATA, CP_START_STATE_PROPERTY_CONTEXT_BYTES);
    for (unsigned i = 0; i < CP_START_STATE_PROPERTY_CONTEXT_BYTES; ++i)
        b[DATA + 2 + i] = (unsigned char)(i * 17u + 3u);
    b[DATA + 6] = (unsigned char)profile;
    checksum(b, BANK_BYTES);
}
static struct cp_start_state_guard guard(void)
{
    struct cp_start_state_guard g = {(uint32_t)getpid(), 2, 2,
        CP_START_STATE_ORIGIN_HOST_TEST, 1};
    return g;
}
static void blocked(struct cp_start_state_provider *p,
                    const struct cp_start_state_guard *g)
{
    unsigned char out[16], before[16];
    struct cp_start_state_provider_readback r;
    memset(out, 0xa5, sizeof(out)); memcpy(before, out, sizeof(out));
    assert(cp_start_state_provider_snapshot(p, g, &r) == 0);
    assert(r.data.known_mask == 0 && r.data.predicate_known_mask == 1);
    assert(r.data.source_origin == g->source_origin && r.data.property_consumed);
    assert(!r.data.lif_consumed && !r.data.adj_consumed && !r.data.data_ready);
    assert(!r.data.published && !r.data.ap_applied && !r.data.business_ready);
    assert(cp_start_state_data_build_reply(&p->data, g, 0x3003, 0x80000027,
                                         out, sizeof(out)) == -ENODATA);
    assert(memcmp(out, before, sizeof(out)) == 0);
}
#define FAIL(call, error) do { \
    struct cp_start_state_provider saved = p; \
    assert((call) == (error)); \
    assert(memcmp(&p, &saved, sizeof(p)) == 0); \
} while (0)
static void matrix(void)
{
    unsigned char b[BANK_BYTES], payload[256], known[260];
    struct cp_start_state_provider p;
    struct cp_start_state_guard g = guard(), bad;
    struct cp_start_state_span s = {payload, known, 256, sizeof(known)};
    struct cp_start_state_provider_readback r, saved_r;
    assert(cp_start_state_provider_init(NULL) == -EINVAL);
    assert(cp_start_state_provider_init(&p) == 0);
    assert(!p.data.known_mask && !p.data.predicate_known_mask);
    for (unsigned v = 0; v < 256; ++v) {
        assert(cp_start_state_provider_init(&p) == 0); fixture(b, v);
        assert(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)) == 0);
        assert(p.data.profile == v && p.prefetch_result == 256);
        assert(p.property_bootstrapped && !p.property_delivered);
        assert(memcmp(p.context, b + DATA + 2, 256) == 0);
        blocked(&p, &g);
        FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EALREADY);
    }
    assert(cp_start_state_provider_init(&p) == 0); fixture(b, 3);
    bad = g; bad.sequence_after += 2;
    FAIL(cp_start_state_provider_bootstrap_property(&p, &bad, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EAGAIN);
    bad = g; bad.quiescent = 0;
    FAIL(cp_start_state_provider_bootstrap_property(&p, &bad, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EAGAIN);
    bad = g; bad.owner_pid++;
    FAIL(cp_start_state_provider_bootstrap_property(&p, &bad, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EXDEV);
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, NULL, 0), -EINVAL);
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, 16), -EMSGSIZE);
    b[12] = 'X';
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EPROTO);
    fixture(b, 3); b[DATA + 4] ^= 1;
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EILSEQ);
    fixture(b, 3); put32(b + 24, UINT32_MAX);
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EINVAL);
    fixture(b, 3); put16(b + DATA, 255); checksum(b, sizeof(b));
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -ENOTSUP);
    fixture(b, 3); put16(b + DATA, 257); checksum(b, sizeof(b));
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EINVAL);
    fixture(b, 3); put32(b + 0x100 + 0x125 * 6 + 2, UINT32_MAX);
    checksum(b, sizeof(b));
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -EINVAL);
    fixture(b, 3);
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g,
        (enum cp_start_state_repository)0, b, sizeof(b)), -ENOTSUP);
    put32(b + 0x100 + SECTIONS * 6 + 6 * 6 + 2, UINT32_MAX);
    checksum(b, sizeof(b));
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g,
        CP_START_STATE_REPOSITORY_PRIMARY, b, sizeof(b)), -ENODATA);
    fixture(b, 3); put32(b + 0x100 + SECTIONS * 6 + 6 * 6 + 2,
        UINT32_C(0x05000000) | DATA); checksum(b, sizeof(b));
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g,
        CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)), -ENOTSUP);
    {
        unsigned char variable[BANK_BYTES + 2];
        fixture(b, 0x73); memcpy(variable, b, sizeof(b));
        memmove(variable + DATA + 4, variable + DATA + 2, 256);
        put16(variable + DATA + 2, 256);
        put32(variable + 28, sizeof(variable) - DATA);
        put32(variable + 0x100 + SECTIONS * 6 + 6 * 6 + 2, DATA);
        checksum(variable, sizeof(variable));
        assert(cp_start_state_provider_bootstrap_property(&p, &g,
            CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, variable, sizeof(variable)) == 0);
        assert(p.data.profile == 0x73 && !memcmp(p.context, variable + DATA + 4, 256));
        assert(cp_start_state_provider_init(&p) == 0);
        put16(variable + DATA + 2, 255); checksum(variable, sizeof(variable));
        FAIL(cp_start_state_provider_bootstrap_property(&p, &g,
            CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, variable, sizeof(variable)), -EINVAL);
    }
    fixture(b, 3); put16(b + 0x100 + 0x125 * 6, 0); checksum(b, sizeof(b));
    FAIL(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_PRIMARY, b, sizeof(b)), -ENODATA);
    assert(!p.data.predicate_known_mask && !p.property_bootstrapped);
    fixture(b, 0);
    assert(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)) == 0);
    memset(payload, 0x59, sizeof(payload)); memset(known, 1, sizeof(known));
    payload[4] = 2;
    bad = g; bad.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    FAIL(cp_start_state_provider_deliver_property(&p, &bad, CP_START_STATE_PROPERTY_ID, &s), -EXDEV);
    FAIL(cp_start_state_provider_deliver_property(&p, &g, 0x250006, &s), -ENOTSUP);
    known[255] = 0;
    FAIL(cp_start_state_provider_deliver_property(&p, &g, CP_START_STATE_PROPERTY_ID, &s), -ENODATA);
    known[255] = 2;
    FAIL(cp_start_state_provider_deliver_property(&p, &g, CP_START_STATE_PROPERTY_ID, &s), -EINVAL);
    known[255] = 1; s.size = 255;
    FAIL(cp_start_state_provider_deliver_property(&p, &g, CP_START_STATE_PROPERTY_ID, &s), -EMSGSIZE);
    s.size = 256;
    assert(cp_start_state_provider_deliver_property(&p, &g, CP_START_STATE_PROPERTY_ID, &s) == 0);
    assert(p.property_delivered && p.data.profile == 2 && !memcmp(p.context, payload, 256));
    blocked(&p, &g);
    bad = g; bad.sequence_before = bad.sequence_after = 0;
    FAIL(cp_start_state_provider_deliver_property(&p, &bad, CP_START_STATE_PROPERTY_ID, &s), -ESTALE);
    s.bytes = p.context;
    FAIL(cp_start_state_provider_deliver_property(&p, &g, CP_START_STATE_PROPERTY_ID, &s), -EINVAL);
    s.bytes = payload; s.known = (const unsigned char *)&p; s.known_size = sizeof(p);
    FAIL(cp_start_state_provider_deliver_property(&p, &g, CP_START_STATE_PROPERTY_ID, &s), -EINVAL);
    memset(&r, 0xa5, sizeof(r)); saved_r = r;
    assert(cp_start_state_provider_snapshot(&p, &bad, &r) == -ESTALE);
    assert(!memcmp(&r, &saved_r, sizeof(r)));
    assert(cp_start_state_provider_snapshot(&p, &g,
        (struct cp_start_state_provider_readback *)(void *)&p) == -EINVAL);
    {
        pid_t child = fork(); int status;
        assert(child >= 0);
        if (!child) {
            assert(cp_start_state_provider_snapshot(&p, &g, &r) == -EXDEV);
            _exit(0);
        }
        assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
    assert(cp_start_state_provider_init(&p) == 0); fixture(b, 0);
    g.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    assert(cp_start_state_provider_bootstrap_property(&p, &g, CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, sizeof(b)) == 0);
    blocked(&p, &g);
}
static void real_bank(const char *path, int primary)
{
    FILE *f = fopen(path, "rb"); long n;
    unsigned char *b;
    struct cp_start_state_provider p;
    struct cp_start_state_guard g = guard();
    assert(f && fseek(f, 0, SEEK_END) == 0 && (n = ftell(f)) > 0 && n < 2000000);
    rewind(f); b = malloc((size_t)n); assert(b);
    assert(fread(b, 1, (size_t)n, f) == (size_t)n && fclose(f) == 0);
    assert(cp_start_state_provider_init(&p) == 0);
    if (primary) {
        assert(cp_start_state_provider_bootstrap_property(&p, &g,
            CP_START_STATE_REPOSITORY_PRIMARY, b, (size_t)n) == -ENODATA);
        assert(!p.data.predicate_known_mask && !p.property_bootstrapped);
        puts("primary property absent: ENODATA, profile unknown, no fallback");
        free(b); return;
    }
    assert(cp_start_state_provider_bootstrap_property(&p, &g,
        CP_START_STATE_REPOSITORY_SECONDARY_VIRTUAL, b, (size_t)n) == 0);
    blocked(&p, &g);
    printf("prefetch=%d profile=%u context=", p.prefetch_result, p.data.profile);
    for (size_t i = 0; i < sizeof(p.context); ++i) printf("%02x", p.context[i]);
    puts(""); free(b);
}
int main(int argc, char **argv)
{
    matrix();
    if (argc == 3) real_bank(argv[1], strcmp(argv[2], "primary") == 0);
    else assert(argc == 1);
    puts("PASS cp-start-state-provider: property source only; reply blocked");
    return 0;
}
