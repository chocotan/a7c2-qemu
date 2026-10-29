/* SPDX-License-Identifier: MIT */
#include "cp-property-stage.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define SOURCE CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE
static struct cp_start_state_guard guard(uint64_t sequence)
{
    struct cp_start_state_guard g;
    memset(&g, 0, sizeof(g));
    g.owner_pid = (uint32_t)getpid();
    g.sequence_before = g.sequence_after = sequence;
    g.source_origin = CP_START_STATE_ORIGIN_HOST_TEST;
    g.quiescent = 1;
    return g;
}
static void put16(unsigned char *p, uint16_t value)
{ p[0] = (unsigned char)value; p[1] = (unsigned char)(value >> 8); }
static void put32(unsigned char *p, uint32_t value)
{ put16(p, (uint16_t)value); put16(p + 2, (uint16_t)(value >> 16)); }
static void checksum(unsigned char *b)
{
    uint32_t sum = 0;
    for (size_t i = 0; i < CP_PROPERTY_STAGE_BYTES; ++i)
        if (i < 0x20 || i >= 0x24) sum += b[i];
    put32(b + 0x20, sum);
}
static unsigned char *load(const char *path, size_t *size)
{
    FILE *f = fopen(path, "rb");
    long length;
    unsigned char *b;
    assert(f && fseek(f, 0, SEEK_END) == 0);
    length = ftell(f);
    assert(length > 0 && fseek(f, 0, SEEK_SET) == 0);
    *size = (size_t)length;
    b = malloc(*size + 64);
    assert(b && fread(b, 1, *size, f) == *size && fclose(f) == 0);
    memset(b + *size, 0xa5, 64);
    return b;
}
static void reject(const unsigned char *b, size_t n, int expected)
{
    struct cp_property_stage owner, before;
    struct cp_start_state_guard g = guard(2);
    assert(cp_property_stage_init(&owner) == 0);
    before = owner;
    assert(cp_property_stage_consume(&owner, &g, SOURCE, b, n) == expected);
    assert(!memcmp(&owner, &before, sizeof(owner)));
}
static void defaults(void)
{
    struct cp_property_stage owner, before;
    struct cp_start_state_provider provider, provider_before;
    struct cp_property_stage_readback out, sentinel;
    struct cp_start_state_guard g = guard(0), bad;
    unsigned char *b = calloc(CP_PROPERTY_STAGE_BYTES, 1);
    union { max_align_t align; unsigned char bytes[sizeof(owner) + 16]; } unaligned;
    assert(b);
    assert(cp_property_stage_init(NULL) == -EINVAL);
    assert(cp_property_stage_init((struct cp_property_stage *)(void *)(unaligned.bytes + 1)) == -EINVAL);
    assert(cp_property_stage_init(&owner) == 0);
    assert(cp_property_stage_snapshot(&owner, &g, &out) == 0);
    assert(out.mode == 3 && !out.mode_property_known && !out.profile_known && !out.alh_property_known);
    for (size_t i = 0; i < sizeof(out.ALH_context); ++i) assert(out.ALH_context[i] == 0);
    assert(!out.source && !out.repository && !out.cp_base && !out.stage_fnv1a64);
    assert(out.source_origin == CP_START_STATE_ORIGIN_NONE && !out.source_sequence);
    assert(cp_start_state_provider_init(&provider) == 0);
    provider_before = provider;
    assert(cp_property_stage_deliver_profile(&owner, &g, &provider) == -ENODATA);
    assert(!memcmp(&provider, &provider_before, sizeof(provider)));
    before = owner;
    memset(&out, 0xa5, sizeof(out)); sentinel = out;
    assert(cp_property_stage_snapshot(&owner, &g, (struct cp_property_stage_readback *)(void *)&owner) == -EINVAL);
    assert(cp_property_stage_snapshot(&owner, &g, (struct cp_property_stage_readback *)(void *)&g) == -EINVAL);
    assert(cp_property_stage_snapshot(&owner, &g, NULL) == -EINVAL);
    assert(cp_property_stage_snapshot(&owner, &g, (struct cp_property_stage_readback *)(void *)(unaligned.bytes + 1)) == -EINVAL);
    assert(cp_property_stage_snapshot(&owner, &g, (struct cp_property_stage_readback *)(uintptr_t)(UINTPTR_MAX - 7)) == -EINVAL);
    assert(cp_property_stage_deliver_profile(&owner, &g, (struct cp_start_state_provider *)(void *)&owner) == -EINVAL);
    assert(cp_property_stage_consume(&owner, &g, SOURCE, (unsigned char *)&owner, CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    assert(cp_property_stage_consume(&owner, &g, SOURCE, (unsigned char *)&g, CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    assert(cp_property_stage_consume(&owner, &g, SOURCE, NULL, CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    assert(cp_property_stage_consume(&owner, &g, SOURCE, (unsigned char *)(uintptr_t)(UINTPTR_MAX - 7), CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    assert(cp_property_stage_consume(&owner, &g, (enum cp_property_stage_source)99, b, CP_PROPERTY_STAGE_BYTES) == -ENOTSUP);
    assert(cp_property_stage_consume(&owner, NULL, SOURCE, b, CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    assert(cp_property_stage_consume(NULL, &g, SOURCE, b, CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    bad = g; bad.owner_pid++;
    assert(cp_property_stage_snapshot(&owner, &bad, &out) == -EXDEV);
    bad = g; bad.source_origin = CP_START_STATE_ORIGIN_NONE;
    assert(cp_property_stage_consume(&owner, &bad, SOURCE, b, CP_PROPERTY_STAGE_BYTES) == -EINVAL);
    bad.source_origin = (enum cp_start_state_origin)99;
    assert(cp_property_stage_snapshot(&owner, &bad, &out) == -EINVAL);
    bad = g; bad.sequence_after = 2;
    assert(cp_property_stage_snapshot(&owner, &bad, &out) == -EAGAIN);
    bad = guard(1);
    assert(cp_property_stage_consume(&owner, &bad, SOURCE, b, CP_PROPERTY_STAGE_BYTES) == -EAGAIN);
    bad = g; bad.quiescent = 0;
    assert(cp_property_stage_snapshot(&owner, &bad, &out) == -EAGAIN);
    bad.quiescent = 2;
    assert(cp_property_stage_snapshot(&owner, &bad, &out) == -EAGAIN);
    bad = guard(2);
    assert(cp_property_stage_snapshot(&owner, &bad, &out) == -ESTALE);
    assert(!memcmp(&out, &sentinel, sizeof(out)));
    assert(!memcmp(&owner, &before, sizeof(owner)));
    reject(b, 0, -EMSGSIZE);
    reject(b, CP_PROPERTY_STAGE_BYTES - 1, -EMSGSIZE);
    reject(b, CP_PROPERTY_STAGE_BYTES + 1, -EMSGSIZE);
    reject(b, CP_PROPERTY_STAGE_BYTES, -EPROTO);
    memcpy(b + 12, "BK4\0", 4);
    reject(b, CP_PROPERTY_STAGE_BYTES, -EINVAL);
    put32(b + 24, 0x100); put32(b + 28, CP_PROPERTY_STAGE_BYTES - 0x100);
    checksum(b);
    reject(b, CP_PROPERTY_STAGE_BYTES, -ENODATA);
    free(b);
}
static void mutations(const unsigned char *stage)
{
    unsigned char *b = malloc(CP_PROPERTY_STAGE_BYTES);
    struct cp_property_stage owner, before;
    struct cp_start_state_guard g = guard(2);
    assert(b);
    assert(cp_property_stage_init(&owner) == 0);
    assert(cp_property_stage_consume(&owner, &g, SOURCE, stage, CP_PROPERTY_STAGE_BYTES) == 0);
    before = owner;
    memcpy(b, stage, CP_PROPERTY_STAGE_BYTES);
    b[9] = 1;
    assert(cp_property_stage_consume(&owner, &g, SOURCE, b, CP_PROPERTY_STAGE_BYTES) == -EILSEQ);
    assert(!memcmp(&owner, &before, sizeof(owner)));
#define RESET() memcpy(b, stage, CP_PROPERTY_STAGE_BYTES)
#define FAIL(code) do { \
    reject(b, CP_PROPERTY_STAGE_BYTES, (code)); \
    assert(cp_property_stage_consume(&owner, &g, SOURCE, b, CP_PROPERTY_STAGE_BYTES) == (code)); \
    assert(!memcmp(&owner, &before, sizeof(owner))); \
} while (0)
    RESET(); b[9] = 1; FAIL(-EILSEQ);
    checksum(b); FAIL(-EILSEQ);
    RESET(); b[12] ^= 1; FAIL(-EPROTO);
    RESET(); b[15] = 1; FAIL(-EPROTO);
    RESET(); b[0x20] ^= 1; FAIL(-EILSEQ);
    RESET(); b[0x74b79] ^= 1; FAIL(-EILSEQ);
    checksum(b); FAIL(-EILSEQ);
    RESET(); b[0x74f88] = 1; checksum(b); FAIL(-EILSEQ);
    RESET(); b[0] ^= 1; checksum(b); FAIL(-EILSEQ);
    RESET(); put32(b + 0x10, UINT32_MAX); FAIL(-EINVAL);
    RESET(); put32(b + 0x14, UINT32_MAX); FAIL(-EINVAL);
    RESET(); put32(b + 0x18, UINT32_MAX); FAIL(-EINVAL);
    RESET(); put32(b + 0x18, 0x100); FAIL(-EINVAL);
    RESET(); put32(b + 0x1c, UINT32_MAX); FAIL(-EINVAL);
    RESET(); put32(b + 0x7de + 2, UINT32_MAX); checksum(b); FAIL(-EINVAL);
    RESET(); put16(b + 0x7de, UINT16_MAX); checksum(b); FAIL(-EINVAL);
    RESET(); put16(b + 0x7de, 3); checksum(b); FAIL(-ENODATA);
    RESET(); put16(b + 0x7de, 6); checksum(b); FAIL(-ENODATA);
    RESET(); put16(b + 0x7d8, 12); put32(b + 0x7da, 30964);
    put16(b + 0x7de, 0); checksum(b); FAIL(-ENODATA);
    RESET(); put32(b + 0x2e9fc + 2, UINT32_MAX); checksum(b); FAIL(-ENODATA);
    RESET(); put32(b + 0x2ea0e + 2, UINT32_MAX); checksum(b); FAIL(-ENODATA);
    RESET(); put16(b + 0x2e9fc, 8); checksum(b); FAIL(-ENOTSUP);
    RESET(); put16(b + 0x2ea0e, 0); checksum(b); FAIL(-ENOTSUP);
    RESET(); put32(b + 0x2e9fc + 2, 0x01000000); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x2e9fc + 2, 0x0115a8f8); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x2ea0e + 2, 0xff15a8f8); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x2ea0e + 2, 0xff15a8f7); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x2ea0e + 2, 0xff15a8f6); put16(b + CP_PROPERTY_STAGE_BYTES - 2, 256);
    checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x2ea0e + 2, 0x0015a8f5); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x2ea0e + 2, 0x00074f82); put16(b + 0x74f82, 257);
    put16(b + 0x74f84, 256); checksum(b); FAIL(-EINVAL);
    RESET(); put16(b + 0x74f82, 255); checksum(b); FAIL(-EMSGSIZE);
    RESET(); put32(b + 0x2e9fc + 2, 0x02074b79); checksum(b); FAIL(-EMSGSIZE);
    RESET(); put16(b + 0x14e, 0x3a); checksum(b); FAIL(-ENODATA);
    RESET(); put32(b + 0x78e2 + 2, UINT32_MAX); checksum(b); FAIL(-ENODATA);
    RESET(); put16(b + 0x78e2, 0); checksum(b); FAIL(-ENOTSUP);
    RESET(); put16(b + 0x3d59a, 255); checksum(b); FAIL(-EMSGSIZE);
    RESET(); put32(b + 0x78e2 + 2, 0xff000000); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x78e2 + 2, 0xff15a8f8); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x78e2 + 2, 0xff15a8f7); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x78e2 + 2, 0xff15a8f6); put16(b + CP_PROPERTY_STAGE_BYTES - 2, 256);
    checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x78e2 + 2, 0x0015a8f5); checksum(b); FAIL(-EINVAL);
    RESET(); put32(b + 0x78e2 + 2, 0x0003d59a); put16(b + 0x3d59a, 257);
    put16(b + 0x3d59c, 256); checksum(b); FAIL(-EINVAL);
    RESET(); b[0x3d59c + 0xb8] ^= 1; checksum(b); FAIL(-EILSEQ);
#undef RESET
#undef FAIL
    free(b);
}
static void public_stage(const unsigned char *b, size_t n)
{
    struct cp_property_stage owner, before, virtual_owner;
    struct cp_start_state_guard g = guard(2), bad, initial = guard(0);
    struct cp_start_state_provider provider, provider_before;
    struct cp_start_state_provider_readback readback;
    struct { struct cp_property_stage_readback view; unsigned char tail[32]; } out;
    unsigned char reply[16], *source_copy = malloc(n);
    pid_t child;
    int status;
    assert(n == CP_PROPERTY_STAGE_BYTES && source_copy);
    memcpy(source_copy, b, n);
    assert(cp_property_stage_init(&owner) == 0);
    assert(cp_property_stage_consume(&owner, &g, SOURCE, source_copy, n) == 0);
    memset(source_copy, 0, n);
    free(source_copy);
    memset(&out, 0xa5, sizeof(out));
    assert(cp_property_stage_snapshot(&owner, &g, &out.view) == 0);
    assert(out.view.mode == 1 && out.view.mode_property == b[0x74b79]);
    assert(out.view.mode_property_known == 1 && out.view.profile_known == 1);
    assert(out.view.source == SOURCE && out.view.repository == CP_PROPERTY_STAGE_REPOSITORY_CP_PRIMARY);
    assert(out.view.cp_base == CP_PROPERTY_STAGE_BASE);
    assert(out.view.stage_fnv1a64 == CP_PROPERTY_STAGE_FNV1A64);
    assert(out.view.source_sequence == 2 && out.view.source_origin == CP_START_STATE_ORIGIN_HOST_TEST);
    assert(!memcmp(out.view.context, b + 0x74f84, sizeof(out.view.context)));
    assert(out.view.alh_property_known == 1);
    assert(!memcmp(out.view.ALH_context, b + 0x3d59c, sizeof(out.view.ALH_context)));
    assert(out.view.ALH_context[0xb8] == 0xff);
    for (size_t i = 0; i < sizeof(out.tail); ++i) assert(out.tail[i] == 0xa5);
    for (size_t i = 0; i < 64; ++i) assert(b[n + i] == 0xa5);
    before = owner;
    assert(cp_property_stage_consume(&owner, &g, SOURCE, b, n) == -EALREADY);
    assert(cp_property_stage_consume(&owner, &initial, SOURCE, b, n) == -ESTALE);
    bad = guard(4);
    assert(cp_property_stage_snapshot(&owner, &bad, &out.view) == -ESTALE);
    bad = g; bad.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    assert(cp_property_stage_snapshot(&owner, &bad, &out.view) == -EXDEV);
    assert(!memcmp(&owner, &before, sizeof(owner)));
    assert(cp_start_state_provider_init(&provider) == 0);
    provider_before = provider;
    assert(cp_property_stage_deliver_profile(&owner, &bad, &provider) == -EXDEV);
    assert(cp_property_stage_deliver_profile(&owner, &initial, &provider) == -ESTALE);
    assert(!memcmp(&provider, &provider_before, sizeof(provider)));
    assert(cp_property_stage_deliver_profile(&owner, &g, &provider) == 0);
    assert(cp_start_state_provider_snapshot(&provider, &g, &readback) == 0);
    assert(!memcmp(readback.context, out.view.context, sizeof(readback.context)));
    assert(readback.repository == 0 && readback.property_delivered == 1 && !readback.property_bootstrapped);
    assert(provider.data.profile == 0 && readback.data.property_consumed == 1);
    assert(readback.data.predicate_known_mask == 1 && !readback.data.known_mask);
    assert(!readback.data.lif_consumed && !readback.data.adj_consumed && !readback.data.source_consumed);
    assert(!readback.data.data_ready && !readback.data.business_ready && !readback.data.configuration_ready);
    assert(!readback.data.published && !readback.data.ap_applied && !readback.data.publication_generation);
    memset(reply, 0xa5, sizeof(reply));
    assert(cp_start_state_data_build_reply(&provider.data, &g, 0x3003, 0, reply, sizeof(reply)) == -ENODATA);
    for (size_t i = 0; i < sizeof(reply); ++i) assert(reply[i] == 0xa5);
    provider_before = provider;
    bad = guard(4);
    assert(cp_start_state_data_consume_property(&provider.data, &bad, CP_START_STATE_PROPERTY_ID,
        &(struct cp_start_state_span){NULL, NULL, 0, 0}) == -EMSGSIZE);
    assert(!memcmp(&provider, &provider_before, sizeof(provider)));
    provider.data.source_sequence = 4;
    provider_before = provider;
    assert(cp_property_stage_deliver_profile(&owner, &g, &provider) == -ESTALE);
    assert(!memcmp(&provider, &provider_before, sizeof(provider)));
    provider.data.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    provider_before = provider;
    assert(cp_property_stage_deliver_profile(&owner, &g, &provider) == -EXDEV);
    assert(!memcmp(&provider, &provider_before, sizeof(provider)));
    child = fork(); assert(child >= 0);
    if (!child) {
        assert(cp_property_stage_snapshot(&owner, &g, &out.view) == -EXDEV);
        assert(cp_property_stage_deliver_profile(&owner, &g, &provider) == -EXDEV);
        _exit(0);
    }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(cp_property_stage_init(&virtual_owner) == 0);
    bad = g; bad.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    assert(cp_property_stage_consume(&virtual_owner, &bad, SOURCE, b, n) == 0);
    assert(cp_property_stage_snapshot(&virtual_owner, &bad, &out.view) == 0);
    assert(out.view.source_origin == CP_START_STATE_ORIGIN_VIRTUAL_SOURCE);
    assert(cp_property_stage_snapshot(&owner, &g, &out.view) == 0);
    printf("source=CP_INITIAL_STAGE repository=CP_PRIMARY mode=%u profile=%u context=",
           out.view.mode, out.view.context[4]);
    for (size_t i = 0; i < sizeof(out.view.context); ++i) printf("%02x", out.view.context[i]);
    printf(" alh=");
    for (size_t i = 0; i < sizeof(out.view.ALH_context); ++i) printf("%02x", out.view.ALH_context[i]);
    puts(" no_ready=1 native_CP=0");
}
static void legacy_primary(const char *path)
{
    size_t n;
    unsigned char *b = load(path, &n);
    struct cp_start_state_provider provider, before;
    struct cp_start_state_guard g = guard(2);
    assert(cp_start_state_provider_init(&provider) == 0);
    before = provider;
    assert(cp_start_state_provider_bootstrap_property(&provider, &g,
        CP_START_STATE_REPOSITORY_PRIMARY, b, n) == -ENODATA);
    assert(!memcmp(&provider, &before, sizeof(provider)));
    reject(b, n, -EMSGSIZE);
    free(b);
    puts("legacy_file_zero_primary=ENODATA no_fallback=1");
}
int main(int argc, char **argv)
{
    defaults();
    if (argc > 1) {
        size_t n;
        unsigned char *b = load(argv[1], &n);
        public_stage(b, n);
        mutations(b);
        free(b);
    }
    if (argc > 2) legacy_primary(argv[2]);
    puts("PASS cp-property-stage");
    return 0;
}
