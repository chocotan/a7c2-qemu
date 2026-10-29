#include "ccf.h"

#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

enum bank_kind { GATE_BANK, MUX_BANK, RESET_BANK };

struct bank_case {
    uint32_t offset;
    uint32_t mask;
    enum bank_kind kind;
    unsigned index;
};

static const struct bank_case banks[] = {
    {0x000, 0x0001f000, GATE_BANK, 0},
    {0x010, 0x00000000, GATE_BANK, 1},
    {0x020, 0x0000030f, GATE_BANK, 2},
    {0x030, 0x002c000c, GATE_BANK, 3},
    {0x040, 0x013fffc0, GATE_BANK, 4},
    {0x050, 0x000df7c0, GATE_BANK, 5},
    {0x060, 0x00000000, GATE_BANK, 6},
    {0x070, 0x00000000, GATE_BANK, 7},
    {0x080, 0x3efbefbe, GATE_BANK, 8},
    {0x210, 0x1f000000, MUX_BANK, 0},
    {0x220, 0x00011111, MUX_BANK, 1},
    {0x230, 0x000003ff, MUX_BANK, 2},
    {0x300, UINT32_MAX, RESET_BANK, 0},
    {0x310, UINT32_MAX, RESET_BANK, 1},
    {0x320, UINT32_MAX, RESET_BANK, 2},
    {0x330, UINT32_MAX, RESET_BANK, 3},
    {0x340, UINT32_MAX, RESET_BANK, 4},
    {0x350, UINT32_MAX, RESET_BANK, 5},
    {0x360, UINT32_MAX, RESET_BANK, 6},
    {0x370, UINT32_MAX, RESET_BANK, 7}
};

static const uint32_t div_offsets[] = {0x10c, 0x110, 0x114, 0x118, 0x11c};

static void same_state(const struct sony_ccf_state *actual,
                       const struct sony_ccf_state *expected)
{
    assert(memcmp(actual->gates, expected->gates, sizeof actual->gates) == 0);
    assert(memcmp(actual->mux, expected->mux, sizeof actual->mux) == 0);
    assert(memcmp(actual->dividers, expected->dividers,
                  sizeof actual->dividers) == 0);
    assert(memcmp(actual->resets, expected->resets, sizeof actual->resets) == 0);
}

static uint32_t *bank_word(struct sony_ccf_state *state,
                           const struct bank_case *bank)
{
    switch (bank->kind) {
    case GATE_BANK: return &state->gates[bank->index];
    case MUX_BANK: return &state->mux[bank->index];
    case RESET_BANK: return &state->resets[bank->index];
    }
    assert(0);
    return NULL;
}

static void read_value(struct sony_ccf_state *state, uint64_t physical,
                       uint32_t expected)
{
    struct sony_ccf_state before = *state;
    uint32_t out = ~expected;

    assert(sony_ccf_read(state, physical, 4, &out));
    assert(out == expected);
    same_state(state, &before);
}

static void reject_read(struct sony_ccf_state *state, uint64_t physical,
                        unsigned size)
{
    struct sony_ccf_state before = *state;
    uint32_t out = UINT32_C(0xa55a1234);

    assert(!sony_ccf_read(state, physical, size, &out));
    assert(out == UINT32_C(0xa55a1234));
    same_state(state, &before);
}

static void reject_write(struct sony_ccf_state *state, uint64_t physical,
                         unsigned size, uint32_t value)
{
    struct sony_ccf_state before = *state;

    assert(!sony_ccf_write(state, physical, size, value));
    same_state(state, &before);
}

static void test_init(void)
{
    struct sony_ccf_state state;
    struct sony_ccf_state expected = {0};

    memset(&state, 0xff, sizeof state);
    expected.resets[1] = UINT32_C(0x88888);
    sony_ccf_init(&state);
    same_state(&state, &expected);
    sony_ccf_init(&state);
    same_state(&state, &expected);
    sony_ccf_init(NULL);
}

static void test_bank(const struct bank_case *bank)
{
    struct sony_ccf_state state;
    struct sony_ccf_state expected;
    uint64_t physical = SONY_CCF_SCU_BASE + bank->offset;
    uint32_t first_valid = bank->mask & (0U - bank->mask);
    unsigned bit;

    sony_ccf_init(&state);
    expected = state;
    read_value(&state, physical, *bank_word(&expected, bank));
    reject_read(&state, physical + 4U, 4);
    reject_read(&state, physical + 8U, 4);
    reject_write(&state, physical, 4, 0);
    reject_write(&state, physical, 4, UINT32_MAX);
    assert(sony_ccf_write(&state, physical + 8U, 4, bank->mask));
    *bank_word(&expected, bank) = 0;
    same_state(&state, &expected);
    read_value(&state, physical, 0);

    for (bit = 0; bit < 32; ++bit) {
        uint32_t value = UINT32_C(1) << bit;

        if ((bank->mask & value) != 0) {
            assert(sony_ccf_write(&state, physical + 4U, 4, value));
            *bank_word(&expected, bank) = value;
            same_state(&state, &expected);
            read_value(&state, physical, value);
            assert(sony_ccf_write(&state, physical + 4U, 4, value));
            assert(sony_ccf_write(&state, physical + 8U, 4, 0));
            same_state(&state, &expected);
            assert(sony_ccf_write(&state, physical + 8U, 4, value));
            *bank_word(&expected, bank) = 0;
            same_state(&state, &expected);
            read_value(&state, physical, 0);
            assert(sony_ccf_write(&state, physical + 8U, 4, value));
            same_state(&state, &expected);
        } else {
            reject_write(&state, physical + 4U, 4, value);
            reject_write(&state, physical + 8U, 4, value);
            reject_write(&state, physical + 4U, 4, value | first_valid);
            /* An invalid CLEAR must not clear an already-set valid bit. */
            assert(sony_ccf_write(&state, physical + 4U, 4, first_valid));
            reject_write(&state, physical + 8U, 4, value | first_valid);
            assert(sony_ccf_write(&state, physical + 8U, 4, first_valid));
            same_state(&state, &expected);
        }
    }
    assert(sony_ccf_write(&state, physical + 4U, 4, bank->mask));
    *bank_word(&expected, bank) = bank->mask;
    same_state(&state, &expected);
    read_value(&state, physical, bank->mask);
    assert(sony_ccf_write(&state, physical + 4U, 4, 0));
    assert(sony_ccf_write(&state, physical + 8U, 4, 0));
    same_state(&state, &expected);
    for (bit = 0; bit < 32; ++bit) {
        uint32_t value = (UINT32_C(1) << bit) & bank->mask;

        assert(sony_ccf_write(&state, physical + 8U, 4, value));
        *bank_word(&expected, bank) &= ~value;
        same_state(&state, &expected);
        read_value(&state, physical, *bank_word(&expected, bank));
    }
    for (bit = 0; bit < 32; ++bit) {
        uint32_t value = (UINT32_C(1) << bit) & bank->mask;

        assert(sony_ccf_write(&state, physical + 4U, 4, value));
        *bank_word(&expected, bank) |= value;
        same_state(&state, &expected);
        read_value(&state, physical, *bank_word(&expected, bank));
    }
    assert(sony_ccf_write(&state, physical + 8U, 4, bank->mask));
    *bank_word(&expected, bank) = 0;
    same_state(&state, &expected);
    read_value(&state, physical, 0);
}

static void test_dividers(void)
{
    size_t index;

    for (index = 0; index < sizeof div_offsets / sizeof div_offsets[0]; ++index) {
        struct sony_ccf_state state;
        struct sony_ccf_state expected;
        uint64_t physical = SONY_CCF_SCU_BASE + div_offsets[index];
        unsigned bit;

        sony_ccf_init(&state);
        expected = state;
        read_value(&state, physical, 0);
        for (bit = 0; bit < 32; ++bit) {
            uint32_t value = UINT32_C(1) << bit;

            if (bit < 8) {
                assert(sony_ccf_write(&state, physical, 4, value));
                expected.dividers[index] = value;
                same_state(&state, &expected);
                read_value(&state, physical, value);
            } else {
                reject_write(&state, physical, 4, value);
                reject_write(&state, physical, 4, value | UINT32_C(0x55));
            }
        }
        assert(sony_ccf_write(&state, physical, 4, 0xff));
        expected.dividers[index] = 0xff;
        same_state(&state, &expected);
        read_value(&state, physical, 0xff);
        assert(sony_ccf_write(&state, physical, 4, 0));
        expected.dividers[index] = 0;
        same_state(&state, &expected);
        read_value(&state, physical, 0);
    }
}

static void test_hclk_and_reset255(void)
{
    static const unsigned hclk_bits[] = {1, 7, 13, 19, 25};
    struct sony_ccf_state state;
    uint32_t combined = 0;
    size_t index;

    sony_ccf_init(&state);
    for (index = 0; index < sizeof hclk_bits / sizeof hclk_bits[0]; ++index) {
        uint32_t value = UINT32_C(1) << hclk_bits[index];

        assert(sony_ccf_write(&state, SONY_CCF_SCU_BASE + 0x84U, 4, value));
        combined |= value;
        read_value(&state, SONY_CCF_SCU_BASE + 0x80U, combined);
    }
    assert(combined == UINT32_C(0x02082082));
    reject_write(&state, SONY_CCF_SCU_BASE + 0x84U, 4, 0x1f);
    reject_write(&state, SONY_CCF_SCU_BASE + 0x88U, 4, 0x1f);
    assert(sony_ccf_write(&state, SONY_CCF_SCU_BASE + 0x374U, 4,
                          UINT32_C(0x80000000)));
    assert(state.resets[7] == UINT32_C(0x80000000));
    read_value(&state, SONY_CCF_SCU_BASE + 0x370U, UINT32_C(0x80000000));
    assert(sony_ccf_write(&state, SONY_CCF_SCU_BASE + 0x378U, 4,
                          UINT32_C(0x80000000)));
    read_value(&state, SONY_CCF_SCU_BASE + 0x370U, 0);
}

static void invalid_shapes(struct sony_ccf_state *state, uint64_t physical)
{
    static const unsigned bad_sizes[] = {0, 1, 2, 3, 5, 8, 16, UINT_MAX};
    size_t index;
    unsigned delta;

    for (index = 0; index < sizeof bad_sizes / sizeof bad_sizes[0]; ++index) {
        reject_read(state, physical, bad_sizes[index]);
        reject_write(state, physical, bad_sizes[index], UINT32_MAX);
        reject_write(state, physical, bad_sizes[index], 0);
    }
    for (delta = 1; delta <= 3; ++delta) {
        reject_read(state, physical + delta, 4);
        reject_write(state, physical + delta, 4, 0);
    }
    reject_read(state, physical + UINT64_C(0x100000000), 4);
    reject_write(state, physical + UINT64_C(0x100000000), 4, 0);
}

static void test_validation(void)
{
    static const uint64_t unknown[] = {
        0, SONY_CCF_SCU_BASE - 4U, SONY_CCF_SCU_BASE - 1U,
        SONY_CCF_SCU_BASE + 0x37cU, SONY_CCF_SCU_BASE + 0x380U,
        SONY_CCF_SCU_BASE + UINT64_C(0x1000000000),
        UINT64_MAX - 3U, UINT64_MAX
    };
    struct sony_ccf_state state;
    struct sony_ccf_state before;
    uint32_t out = UINT32_C(0x12345678);
    uint32_t offset;
    size_t index;

    sony_ccf_init(&state);
    memset(state.gates, 0x5a, sizeof state.gates);
    memset(state.mux, 0xa5, sizeof state.mux);
    memset(state.dividers, 0x3c, sizeof state.dividers);
    memset(state.resets, 0xc3, sizeof state.resets);
    before = state;
    assert(!sony_ccf_read(NULL, SONY_CCF_SCU_BASE, 4, &out));
    assert(out == UINT32_C(0x12345678));
    assert(!sony_ccf_write(NULL, SONY_CCF_SCU_BASE + 4U, 4, 1));
    assert(!sony_ccf_read(&state, SONY_CCF_SCU_BASE, 4, NULL));
    assert(!sony_ccf_read(NULL, 0, 0, NULL));
    same_state(&state, &before);
    for (index = 0; index < sizeof banks / sizeof banks[0]; ++index) {
        unsigned port;

        for (port = 0; port <= 8; port += 4) {
            invalid_shapes(&state, SONY_CCF_SCU_BASE + banks[index].offset + port);
        }
    }
    for (index = 0; index < sizeof div_offsets / sizeof div_offsets[0]; ++index) {
        invalid_shapes(&state, SONY_CCF_SCU_BASE + div_offsets[index]);
    }
    for (index = 0; index < sizeof unknown / sizeof unknown[0]; ++index) {
        reject_read(&state, unknown[index], 4);
        reject_write(&state, unknown[index], 4, 0);
    }
    /* Check every aligned hole, including each bank's reserved +0xc. */
    for (offset = 0; offset <= 0x380U; offset += 4) {
        bool known = false;

        for (index = 0; index < sizeof banks / sizeof banks[0]; ++index) {
            if (offset == banks[index].offset ||
                offset == banks[index].offset + 4U ||
                offset == banks[index].offset + 8U) {
                known = true;
            }
        }
        for (index = 0; index < sizeof div_offsets / sizeof div_offsets[0]; ++index) {
            if (offset == div_offsets[index]) {
                known = true;
            }
        }
        if (!known) {
            reject_read(&state, SONY_CCF_SCU_BASE + offset, 4);
            reject_write(&state, SONY_CCF_SCU_BASE + offset, 4, 0);
        }
    }
    same_state(&state, &before);
}

int main(void)
{
    size_t index;
    unsigned gate_count = 0;

    test_init();
    for (index = 0; index < sizeof banks / sizeof banks[0]; ++index) {
        uint32_t bits = banks[index].mask;

        test_bank(&banks[index]);
        if (banks[index].kind == GATE_BANK) {
            while (bits != 0) {
                gate_count += bits & 1U;
                bits >>= 1;
            }
        }
    }
    assert(gate_count == 70);
    test_dividers();
    test_hclk_and_reset255();
    test_validation();
    puts("sony_ccf: 20 banks, 5 dividers, 70 gates; all deterministic tests passed");
    return 0;
}
