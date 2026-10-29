#include "dmm-service.h"
unsigned int dmm_speech_initial_creator(const unsigned long *elf_return_pcs, unsigned int count) {
    if (!elf_return_pcs || count < 4) return DMM_CREATOR_UNKNOWN;
    return elf_return_pcs[0] == 0x35522a4UL && elf_return_pcs[1] == 0x35527b4UL &&
           elf_return_pcs[2] == 0x34d3614UL && elf_return_pcs[3] == 0x17b2c08UL
           ? DMM_CREATOR_SPEECH_INITIAL : DMM_CREATOR_UNKNOWN;
}
static unsigned int get(const unsigned char *p, unsigned int n) {
    unsigned int v = 0;
    for (unsigned int i = 0; i < n; ++i) v |= (unsigned int)p[i] << (8 * i);
    return v;
}
static void put(unsigned char *p, unsigned int v, unsigned int n) {
    for (unsigned int i = 0; i < n; ++i) p[i] = v >> (8 * i);
}
int dmm_service_reply(struct dmm_service *s, const unsigned char *q, unsigned int size, unsigned char *r) {
    if (!s || !q || !r || size < 40) return -1024;
    if (!s->memory || s->physical != DMM_TEST_PHYSICAL) return -1021;
    unsigned int op = get(q, 2), option = get(q + 22, 2), handle = get(q + 8, 4);
    if (op < 0x20 || op > 0x23) { if (op != 0x2a) return -1024; }
    for (int i = 0; i < 40; ++i) r[i] = 0;
    put(r, op | 0x8000, 2);
    put(r + 6, get(q + 20, 2), 2);
    put(r + 12, op == 0x20 ? 0xffffffffU : handle, 4);
    int raw = 0;
    unsigned int index = handle & 0x3ff;
    struct dmm_slot *slot = 0;
    if (op == 0x2a) {
        /* op2a is the original handle->physical-segments query (icdt.ko pins:
         * 40B request carries only op at +0 and handle at +8; reply 802a has
         * s16 status at +2, u16 segment count at +8, 16B records from +0x18
         * with u64 address at +0 and u32 length at +8). Same handle/generation
         * binding as ops 21..23; segment address uses the CP-side physical
         * domain already evidenced by the op20/21 reply convention. */
        if (index >= 2) raw = -0x105;
        else if (s->slots[index].handle != handle) raw = -0x205;
        else if (!s->slots[index].allocated) raw = -1;
        else {
            slot = s->slots + index;
            unsigned long long seg = s->physical - 0x400000000ULL + index * 0x80000ULL;
            put(r + 8, 1, 2);
            put(r + 0x18, (unsigned int)seg, 4);
            put(r + 0x1c, (unsigned int)(seg >> 32), 4);
            put(r + 0x20, 0x80000, 4);
        }
    } else if (op == 0x20) {
        if (option > 1) raw = -4; /* Other original options are outside this test model. */
        else if (get(q + 4, 4) != 0x63a) raw = -3;
        else {
            for (index = 0; index < 2 && s->slots[index].allocated; ++index) {}
            if (index == 2) raw = -0x201;
            else {
                if (s->allocations == ~0ULL) return -1021;
                slot = s->slots + index;
                slot->allocation_epoch = ++s->allocations;
                slot->creator_kind = DMM_CREATOR_UNKNOWN;
                /* CP C1E51E sets bit15; generations run 1..31 then 1. */
                slot->generation = slot->generation < 31 ? slot->generation + 1 : 1;
                handle = 0x8000U | (slot->generation << 10) | index;
                slot->handle = handle; slot->allocated = 1; slot->open_count = option;
                for (unsigned int i = 0; i < 0x80000; ++i) s->memory[index * 0x80000 + i] = 0;
                put(r + 12, handle, 4);
                put(r + 16, 0x63a, 4);
            }
        }
    } else {
        if (index >= 2) raw = -0x105;
        else if (s->slots[index].handle != handle) raw = -0x205;
        else if (!s->slots[index].allocated) raw = -1;
        else {
            slot = s->slots + index;
            if (op == 0x21) {
                if (option > 1) raw = -4;
                else if (slot->open_count == 255) raw = -1;
                else { ++slot->open_count; s->lifecycle_changed = 1; }
            } else if (op == 0x22) {
                if (option) raw = -4;
                else if (!slot->open_count) raw = 1;
                else { --slot->open_count; s->lifecycle_changed = 1; }
            } else {
                if (option != 0 && option != 2) raw = -4;
                else {
                    s->lifecycle_changed = 1;
                    if (option == 2 && slot->open_count) --slot->open_count;
                    raw = slot->open_count ? 3 : 0;
                    slot->open_count = 0; slot->allocated = 0;
                }
            }
        }
    }
    if (!raw && slot && ((op == 0x20 && option == 1) || op == 0x21)) {
        unsigned long long cp_address = s->physical - 0x400000000ULL + index * 0x80000;
        put(r + 8, 1, 2);
        put(r + 24, (unsigned int)cp_address, 4);
        put(r + 28, (unsigned int)(cp_address >> 32), 4);
        put(r + 32, 0x80000, 4);
    }
    int converted = raw == -0x201 ? -1 : (raw == -0x105 || raw == -0x205) ? -5 : raw;
    put(r + 10, (unsigned int)raw, 2);
    put(r + 2, (unsigned int)converted, 2);
    return 0;
}
#ifdef DMM_SERVICE_SELFTEST
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void dmm_provenance_selftest(unsigned char *memory) {
    unsigned long pcs[] = {0x35522a4UL, 0x35527b4UL, 0x34d3614UL, 0x17b2c08UL, 0x1234UL};
    assert(!dmm_speech_initial_creator(0, 4));
    for (unsigned int count = 0; count < 4; ++count)
        assert(!dmm_speech_initial_creator(pcs, count));
    assert(dmm_speech_initial_creator(pcs, 4) == DMM_CREATOR_SPEECH_INITIAL);
    assert(dmm_speech_initial_creator(pcs, 5) == DMM_CREATOR_SPEECH_INITIAL);
    for (unsigned int i = 0; i < 4; ++i) {
        pcs[i] ^= 1UL;
        assert(!dmm_speech_initial_creator(pcs, 4));
        pcs[i] ^= 1UL;
    }
    pcs[3] = 0x17b07e4UL; /* Speech reinitialization is not the initial creator. */
    assert(!dmm_speech_initial_creator(pcs, 4));

    struct dmm_service s = {.memory = memory, .physical = DMM_TEST_PHYSICAL}, before, probe;
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    assert(!s.allocations && !s.lifecycle_changed && !s.slots[0].allocation_epoch &&
           s.slots[0].creator_kind == DMM_CREATOR_UNKNOWN);
    assert(!dmm_service_reply(&s, q, sizeof q, r) && !get(r + 2, 2));
    unsigned int first = get(r + 12, 4);
    assert(s.allocations == 1 && s.slots[0].allocation_epoch == 1 &&
           s.slots[0].creator_kind == DMM_CREATOR_UNKNOWN && !s.lifecycle_changed);
    s.slots[0].creator_kind = DMM_CREATOR_SPEECH_INITIAL; /* Producer annotation fixture. */
    memcpy(&before, &s, sizeof s);
    q[0] = 0x2a; put(q + 8, first, 4);
    assert(!dmm_service_reply(&s, q, sizeof q, r) && !get(r + 2, 2));
    assert(!memcmp(&s, &before, sizeof s));
    put(q + 8, first ^ 0x400U, 4);
    assert(!dmm_service_reply(&s, q, sizeof q, r) && (short)get(r + 2, 2) == -5);
    assert(!memcmp(&s, &before, sizeof s));
    for (unsigned int op = 0x21; op <= 0x23; ++op) {
        q[0] = op; put(q + 22, 0, 2); put(q + 8, first ^ 0x400U, 4);
        assert(!dmm_service_reply(&s, q, sizeof q, r) && (short)get(r + 2, 2) == -5);
        assert(!memcmp(&s, &before, sizeof s));
        put(q + 8, first, 4); put(q + 22, 3, 2);
        assert(!dmm_service_reply(&s, q, sizeof q, r) && (short)get(r + 2, 2) == -4);
        assert(!memcmp(&s, &before, sizeof s));
    }
    q[0] = 0x20;
    assert(!dmm_service_reply(&s, q, sizeof q, r) && (short)get(r + 2, 2) == -4);
    assert(!memcmp(&s, &before, sizeof s));
    put(q + 22, 1, 2); put(q + 4, 0, 4);
    assert(!dmm_service_reply(&s, q, sizeof q, r) && (short)get(r + 2, 2) == -3);
    assert(!memcmp(&s, &before, sizeof s));

    probe = s; probe.slots[0].open_count = 255;
    memcpy(&before, &probe, sizeof probe);
    q[0] = 0x21; put(q + 8, first, 4); put(q + 22, 0, 2);
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && (short)get(r + 2, 2) == -1);
    assert(!memcmp(&probe, &before, sizeof probe));
    probe = s; probe.slots[0].open_count = 0;
    memcpy(&before, &probe, sizeof probe); q[0] = 0x22;
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && get(r + 2, 2) == 1);
    assert(!memcmp(&probe, &before, sizeof probe));
    probe = s;
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && !get(r + 2, 2));
    assert(!probe.slots[0].open_count && probe.lifecycle_changed == 1);

    probe = s; q[0] = 0x21;
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && !get(r + 2, 2));
    assert(probe.slots[0].open_count == 2 && probe.lifecycle_changed == 1);
    q[0] = 0x22;
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && !get(r + 2, 2));
    assert(probe.slots[0].open_count == 1 && probe.lifecycle_changed == 1);
    assert(probe.allocations == 1 && probe.slots[0].allocation_epoch == 1 &&
           probe.slots[0].creator_kind == DMM_CREATOR_SPEECH_INITIAL);
    probe = s; /* Existing whole-service rollback restores provenance too. */
    assert(!probe.lifecycle_changed && probe.allocations == 1 &&
           probe.slots[0].allocation_epoch == 1 && probe.slots[0].creator_kind == DMM_CREATOR_SPEECH_INITIAL);

    for (unsigned int option = 0; option <= 2; option += 2) {
        probe = s; q[0] = 0x23; put(q + 22, option, 2);
        assert(!dmm_service_reply(&probe, q, sizeof q, r) && get(r + 2, 2) == (option ? 0U : 3U));
        assert(!probe.slots[0].allocated && !probe.slots[0].open_count && probe.lifecycle_changed == 1);
        assert(probe.allocations == 1 && probe.slots[0].allocation_epoch == 1 &&
               probe.slots[0].creator_kind == DMM_CREATOR_SPEECH_INITIAL);
        memcpy(&before, &probe, sizeof probe);
        assert(!dmm_service_reply(&probe, q, sizeof q, r) && (short)get(r + 2, 2) == -1);
        assert(!memcmp(&probe, &before, sizeof probe));
        q[0] = 0x20; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
        assert(!dmm_service_reply(&probe, q, sizeof q, r) && !get(r + 2, 2));
        assert(probe.allocations == 2 && probe.slots[0].allocation_epoch == 2 &&
               probe.slots[0].creator_kind == DMM_CREATOR_UNKNOWN && probe.lifecycle_changed == 1);
    }

    q[0] = 0x20; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    assert(!dmm_service_reply(&s, q, sizeof q, r) && !get(r + 2, 2));
    assert(s.allocations == 2 && s.slots[1].allocation_epoch == 2 &&
           s.slots[1].creator_kind == DMM_CREATOR_UNKNOWN && !s.lifecycle_changed);
    memcpy(&before, &s, sizeof s);
    assert(!dmm_service_reply(&s, q, sizeof q, r) && (short)get(r + 2, 2) == -1);
    assert(!memcmp(&s, &before, sizeof s));

    probe = (struct dmm_service){.memory = memory, .physical = DMM_TEST_PHYSICAL, .allocations = ~0ULL};
    memory[0] = 0xa5; memcpy(&before, &probe, sizeof probe);
    assert(dmm_service_reply(&probe, q, sizeof q, r) == -1021);
    assert(!memcmp(&probe, &before, sizeof probe) && memory[0] == 0xa5);
    probe.allocations = ~0ULL - 1;
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && !get(r + 2, 2));
    assert(probe.allocations == ~0ULL && probe.slots[0].allocation_epoch == ~0ULL && !memory[0]);
    memory[0x80000] = 0x5a; memcpy(&before, &probe, sizeof probe);
    assert(dmm_service_reply(&probe, q, sizeof q, r) == -1021);
    assert(!memcmp(&probe, &before, sizeof probe) && memory[0x80000] == 0x5a);
    q[0] = 0x2a; put(q + 8, probe.slots[0].handle, 4);
    assert(!dmm_service_reply(&probe, q, sizeof q, r) && !get(r + 2, 2));
    assert(!memcmp(&probe, &before, sizeof probe));
    puts("DMM_PROVENANCE_SELFTEST_PASS");
}
int main(void) {
    struct dmm_service s = {.physical = DMM_TEST_PHYSICAL};
    s.memory = malloc(DMM_TEST_SIZE); assert(s.memory);
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    assert(!dmm_service_reply(&s, q, 40, r));
    unsigned int first = get(r + 12, 4);
    assert(first == 0x8400 && (first & 0x8000) && !(first >> 16));
    assert(get(r + 2, 2) == 0 && get(r + 8, 2) == 1 && get(r + 24, 4) == 0x1e000000);
    assert(get(r + 32, 4) == 0x80000 && s.slots[0].open_count == 1 && !s.memory[0]);
    assert(!dmm_service_reply(&s, q, 40, r) && get(r + 24, 4) == 0x1e080000 && get(r + 12, 4) == 0x8401);
    assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -1 && (short)get(r + 10, 2) == -0x201);
    q[0] = 0x23; put(q + 8, first, 4); put(q + 22, 2, 2);
    s.memory[0] = 0xab;
    assert(!dmm_service_reply(&s, q, 40, r) && !get(r + 2, 2) && !s.slots[0].allocated);
    assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -1);
    q[0] = 0x20; put(q + 22, 1, 2);
    assert(!dmm_service_reply(&s, q, 40, r) && get(r + 12, 4) != first && !s.memory[0]);
    unsigned int current = get(r + 12, 4);
    /* op2a: original handle->physical-segments query. Request carries only op
     * at +0 and handle at +8 (rest zero); reply 802a has s16 status at +2,
     * u16 segment count at +8, 16B records from +0x18 (u64 address at +0,
     * u32 length at +8). Read-only: must not disturb handle state. */
    q[0] = 0x2a; put(q + 8, current, 4); put(q + 22, 0, 2);
    assert(!dmm_service_reply(&s, q, 40, r) && !get(r + 2, 2) && get(r + 8, 2) == 1);
    assert(get(r + 0x18, 4) == 0x1e000000 && !get(r + 0x1c, 4) && get(r + 0x20, 4) == 0x80000);
    assert(s.slots[0].allocated && s.slots[0].open_count == 1);
    put(q + 8, first, 4); /* stale generation on the re-allocated slot 0 */
    assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -5);
    put(q + 8, 2, 4); /* index out of range */
    assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -5);
    q[0] = 0x21; put(q + 8, current, 4);
    assert(!dmm_service_reply(&s, q, 40, r) && s.slots[0].open_count == 2);
    q[0] = 0x22; put(q + 22, 0, 2);
    assert(!dmm_service_reply(&s, q, 40, r) && s.slots[0].open_count == 1);
    assert(!dmm_service_reply(&s, q, 40, r) && !s.slots[0].open_count);
    assert(!dmm_service_reply(&s, q, 40, r) && get(r + 2, 2) == 1);
    q[0] = 0x21;
    assert(!dmm_service_reply(&s, q, 40, r) && s.slots[0].open_count == 1);
    q[0] = 0x23;
    assert(!dmm_service_reply(&s, q, 40, r) && get(r + 2, 2) == 3 && !s.slots[0].allocated);
    q[0] = 0x21; put(q + 8, first, 4);
    assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -5);
    put(q + 8, 0xffffffffU, 4);
    assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -5);
    assert(dmm_service_reply(&s, q, 39, r) == -1024);
    assert(!s.slots[0].allocated && !s.slots[0].open_count);
    s.slots[0].generation = 30; /* Host fixture at the original rollover boundary. */
    for (unsigned int pass = 0; pass < 34; ++pass) {
        memset(q, 0, sizeof q);q[0] = 0x20;put(q + 4, 0x63a, 4);put(q + 22, 1, 2);
        assert(!dmm_service_reply(&s, q, 40, r) && !get(r + 2, 2));
        unsigned int generation = pass ? (pass - 1) % 31 + 1 : 31;
        unsigned int live = get(r + 12, 4);
        assert(live == (0x8000U | (generation << 10)) && generation && !(live >> 16));
        assert((live & 0x3ff) == 0 && ((live >> 10) & 31) == generation);
        assert(s.allocations == 4ULL + pass && s.slots[0].allocation_epoch == s.allocations &&
               s.slots[0].creator_kind == DMM_CREATOR_UNKNOWN && s.lifecycle_changed == 1);
        q[0] = 0x21;put(q + 8, live & ~0x8000U, 4);
        assert(!dmm_service_reply(&s, q, 40, r) && (short)get(r + 2, 2) == -5);
        assert(s.slots[0].allocated && s.slots[0].open_count == 1);
        q[0] = 0x23;put(q + 8, live, 4);put(q + 22, 2, 2);
        assert(!dmm_service_reply(&s, q, 40, r) && !get(r + 2, 2) && !s.slots[0].allocated);
    }
    dmm_provenance_selftest(s.memory);
    free(s.memory); puts("DMM_SERVICE_SELFTEST_PASS");
}
#endif
