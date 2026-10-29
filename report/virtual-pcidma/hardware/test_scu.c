#include "scu.h"

#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>

static void same_state(const struct sony_pcie_scu_state *a,
                       const struct sony_pcie_scu_state *b)
{
    assert(a->hclk == b->hclk);
    assert(a->reset == b->reset);
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        assert(a->wrapper[i] == b->wrapper[i]);
    }
}

static uint32_t read_word(struct sony_pcie_scu_state *s, uint64_t address)
{
    struct sony_pcie_scu_state before = *s;
    uint32_t value = UINT32_MAX;
    assert(sony_pcie_scu_read(s, address, 4, &value));
    same_state(s, &before);
    return value;
}

static void reject_read(struct sony_pcie_scu_state *s, uint64_t address, unsigned size)
{
    struct sony_pcie_scu_state before = *s;
    uint32_t out = UINT32_C(0xdeadbeef);
    assert(!sony_pcie_scu_read(s, address, size, &out));
    assert(out == UINT32_C(0xdeadbeef));
    same_state(s, &before);
}

static void reject_write(struct sony_pcie_scu_state *s, uint64_t address, unsigned size,
                         uint32_t value)
{
    struct sony_pcie_scu_state before = *s;
    assert(!sony_pcie_scu_write(s, address, size, value));
    same_state(s, &before);
}

static void policy_and_w1(void)
{
    struct sony_pcie_scu_state s;
    sony_pcie_scu_init(&s);
    assert(read_word(&s, SCU_HCLK_STATUS) == 0);
    assert(read_word(&s, SCU_RESET_STATUS) == UINT32_C(0x88888));
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        assert(s.wrapper[i] == 0);
    }
    const uint64_t ports[] = {
        SCU_HCLK_SET, SCU_HCLK_CLEAR, SCU_RESET_SET, SCU_RESET_CLEAR
    };
    for (unsigned i = 0; i < sizeof ports / sizeof ports[0]; ++i) {
        struct sony_pcie_scu_state before = s;
        assert(sony_pcie_scu_write(&s, ports[i], 4, 0));
        same_state(&s, &before);
        reject_read(&s, ports[i], 4);
    }
    reject_write(&s, SCU_HCLK_STATUS, 4, 0);
    reject_write(&s, SCU_RESET_STATUS, 4, 0);
    assert(sony_pcie_scu_write(&s, SCU_HCLK_SET, 4, SCU_HCLK_MASK));
    assert(sony_pcie_scu_write(&s, SCU_HCLK_SET, 4, SCU_HCLK_MASK));
    assert(read_word(&s, SCU_HCLK_STATUS) == SCU_HCLK_MASK);
    assert(sony_pcie_scu_write(&s, SCU_HCLK_CLEAR, 4, SCU_HCLK_MASK));
    assert(sony_pcie_scu_write(&s, SCU_HCLK_CLEAR, 4, SCU_HCLK_MASK));
    assert(read_word(&s, SCU_HCLK_STATUS) == 0);
    assert(sony_pcie_scu_write(&s, SCU_RESET_CLEAR, 4, SCU_APB_RESET_MASK));
    assert(sony_pcie_scu_write(&s, SCU_RESET_CLEAR, 4, SCU_APB_RESET_MASK));
    assert(read_word(&s, SCU_RESET_STATUS) == 0);
    assert(sony_pcie_scu_write(&s, SCU_RESET_SET, 4, SCU_APB_RESET_MASK));
    assert(sony_pcie_scu_write(&s, SCU_RESET_SET, 4, SCU_APB_RESET_MASK));
    assert(read_word(&s, SCU_RESET_STATUS) == SCU_APB_RESET_MASK);
}

static void controllers(void)
{
    const uint64_t expected_addresses[] = {
        UINT64_C(0xf11e0380), UINT64_C(0xf1160380), UINT64_C(0xf11a0380),
        UINT64_C(0xf1220380), UINT64_C(0xf1120380)
    };
    const unsigned reset_bits[] = { 3, 11, 7, 15, 19 };
    const unsigned hclk_bits[] = { 1, 7, 13, 19, 25 };
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        struct sony_pcie_scu_state s;
        uint32_t clock = UINT32_C(1) << hclk_bits[i];
        uint32_t reset = UINT32_C(1) << reset_bits[i];
        uint64_t wrapper = expected_addresses[i];
        assert(sony_pcie_scu_wrapper_addresses[i] == wrapper);
        assert(sony_pcie_scu_apb_reset_masks[i] == reset);
        assert(sony_pcie_scu_hclk_masks[i] == clock);
        sony_pcie_scu_init(&s);
        reject_read(&s, wrapper, 4);
        reject_write(&s, wrapper, 4, SCU_WRAPPER_REQUEST_MASK);
        assert(sony_pcie_scu_write(&s, SCU_HCLK_SET, 4, clock));
        assert(read_word(&s, SCU_HCLK_STATUS) == clock);
        reject_read(&s, wrapper, 4);
        reject_write(&s, wrapper, 4, 0);
        assert(sony_pcie_scu_write(&s, SCU_RESET_CLEAR, 4, reset));
        assert(read_word(&s, SCU_RESET_STATUS) == (SCU_APB_RESET_MASK & ~reset));
        uint32_t value = read_word(&s, wrapper);
        assert(value == 0);
        assert(sony_pcie_scu_write(&s, wrapper, 4, value | UINT32_C(0x10)));
        assert(read_word(&s, wrapper) == UINT32_C(0x10));
        assert(sony_pcie_scu_write(&s, wrapper, 4, UINT32_C(0x10)));
        assert(sony_pcie_scu_write(&s, SCU_HCLK_CLEAR, 4, clock));
        assert(read_word(&s, SCU_HCLK_STATUS) == 0);
        assert(s.wrapper[i] == UINT32_C(0x10));
        reject_read(&s, wrapper, 4);
        reject_write(&s, wrapper, 4, 0);
        assert(sony_pcie_scu_write(&s, SCU_HCLK_SET, 4, clock));
        assert(read_word(&s, wrapper) == UINT32_C(0x10));
        assert(sony_pcie_scu_write(&s, wrapper, 4, 0));
        assert(read_word(&s, wrapper) == 0);
        for (unsigned j = 0; j < SCU_WRAPPER_COUNT; ++j) {
            assert(s.wrapper[j] == 0);
            if (j != i) {
                reject_read(&s, expected_addresses[j], 4);
                reject_write(&s, expected_addresses[j], 4, UINT32_C(0x10));
            }
        }
        assert(sony_pcie_scu_write(&s, SCU_RESET_SET, 4, reset));
        assert(read_word(&s, SCU_RESET_STATUS) == SCU_APB_RESET_MASK);
        reject_read(&s, wrapper, 4);
        reject_write(&s, wrapper, 4, 0);
        assert(sony_pcie_scu_write(&s, SCU_HCLK_CLEAR, 4, clock));
        assert(sony_pcie_scu_write(&s, SCU_RESET_CLEAR, 4, reset));
        reject_read(&s, wrapper, 4); /* Reset clear alone supplies no clock. */
        reject_write(&s, wrapper, 4, 0);
    }
}

static void multi_controller_isolation(void)
{
    const unsigned hclk_bits[] = { 1, 7, 13, 19, 25 };
    struct sony_pcie_scu_state s;
    sony_pcie_scu_init(&s);
    assert(sony_pcie_scu_write(&s, SCU_HCLK_SET, 4, SCU_HCLK_MASK));
    assert(sony_pcie_scu_write(&s, SCU_RESET_CLEAR, 4, SCU_APB_RESET_MASK));
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        assert(sony_pcie_scu_write(&s, sony_pcie_scu_wrapper_addresses[i], 4,
                                   SCU_WRAPPER_REQUEST_MASK));
    }
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        uint32_t clock = UINT32_C(1) << hclk_bits[i];
        uint32_t reset = sony_pcie_scu_apb_reset_masks[i];
        assert(sony_pcie_scu_write(&s, SCU_HCLK_CLEAR, 4, clock));
        assert(read_word(&s, SCU_HCLK_STATUS) == (SCU_HCLK_MASK & ~clock));
        for (unsigned j = 0; j < SCU_WRAPPER_COUNT; ++j) {
            if (j != i) {
                assert(read_word(&s, sony_pcie_scu_wrapper_addresses[j]) ==
                       SCU_WRAPPER_REQUEST_MASK);
            }
        }
        assert(sony_pcie_scu_write(&s, SCU_HCLK_SET, 4, clock));
        assert(read_word(&s, SCU_HCLK_STATUS) == SCU_HCLK_MASK);
        assert(sony_pcie_scu_write(&s, SCU_RESET_SET, 4, reset));
        assert(read_word(&s, SCU_RESET_STATUS) == reset);
        for (unsigned j = 0; j < SCU_WRAPPER_COUNT; ++j) {
            if (j != i) {
                assert(read_word(&s, sony_pcie_scu_wrapper_addresses[j]) ==
                       SCU_WRAPPER_REQUEST_MASK);
            }
        }
        assert(sony_pcie_scu_write(&s, SCU_RESET_CLEAR, 4, reset));
        assert(read_word(&s, SCU_RESET_STATUS) == 0);
        assert(sony_pcie_scu_write(&s, sony_pcie_scu_wrapper_addresses[i], 4, 0));
        for (unsigned j = 0; j < SCU_WRAPPER_COUNT; ++j) {
            assert(read_word(&s, sony_pcie_scu_wrapper_addresses[j]) ==
                   (i == j ? 0 : SCU_WRAPPER_REQUEST_MASK));
        }
        assert(sony_pcie_scu_write(&s, sony_pcie_scu_wrapper_addresses[i], 4,
                                   SCU_WRAPPER_REQUEST_MASK));
    }
    sony_pcie_scu_init(&s);
    assert(s.hclk == 0 && s.reset == SCU_APB_RESET_MASK);
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        assert(s.wrapper[i] == 0);
    }
}

static void invalid_accesses(void)
{
    struct {
        uint32_t before;
        struct sony_pcie_scu_state state;
        uint32_t after;
    } guarded = { .before = UINT32_C(0x12345678), .after = UINT32_C(0x87654321) };
    struct sony_pcie_scu_state *s = &guarded.state;
    sony_pcie_scu_init(s);
    assert(sony_pcie_scu_write(s, SCU_HCLK_SET, 4, SCU_HCLK_MASK));
    assert(sony_pcie_scu_write(s, SCU_RESET_CLEAR, 4, SCU_APB_RESET_MASK));
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        assert(sony_pcie_scu_write(s, sony_pcie_scu_wrapper_addresses[i], 4,
                                   UINT32_C(0x10)));
    }
    const uint64_t addresses[] = {
        SCU_HCLK_STATUS, SCU_HCLK_SET, SCU_HCLK_CLEAR,
        SCU_RESET_STATUS, SCU_RESET_SET, SCU_RESET_CLEAR,
        UINT64_C(0xf11e0380), UINT64_C(0xf1160380), UINT64_C(0xf11a0380),
        UINT64_C(0xf1220380), UINT64_C(0xf1120380)
    };
    const unsigned bad_sizes[] = { 0, 1, 2, 3, 5, 8, UINT_MAX };
    for (unsigned i = 0; i < sizeof addresses / sizeof addresses[0]; ++i) {
        for (unsigned j = 0; j < sizeof bad_sizes / sizeof bad_sizes[0]; ++j) {
            reject_read(s, addresses[i], bad_sizes[j]);
            reject_write(s, addresses[i], bad_sizes[j], 0);
        }
        for (unsigned offset = 1; offset <= 3; ++offset) {
            reject_read(s, addresses[i] + offset, 4);
            reject_write(s, addresses[i] + offset, 4, 0);
        }
        struct sony_pcie_scu_state before = *s;
        assert(!sony_pcie_scu_read(s, addresses[i], 4, NULL));
        same_state(s, &before);
    }
    const uint64_t unknown[] = {
        0, UINT64_MAX, UINT64_MAX - 3, UINT64_C(0xf1388000),
        SCU_HCLK_STATUS - 4, SCU_HCLK_CLEAR + 4,
        SCU_RESET_STATUS - 4, SCU_RESET_CLEAR + 4,
        UINT64_C(0x1f1388080), UINT64_C(0x1f11e0380)
    };
    for (unsigned i = 0; i < sizeof unknown / sizeof unknown[0]; ++i) {
        reject_read(s, unknown[i], 4);
        reject_write(s, unknown[i], 4, UINT32_MAX);
    }
    for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
        reject_read(s, sony_pcie_scu_wrapper_addresses[i] - 4, 4);
        reject_read(s, sony_pcie_scu_wrapper_addresses[i] + 4, 4);
        reject_write(s, sony_pcie_scu_wrapper_addresses[i] - 4, 4, 0);
        reject_write(s, sony_pcie_scu_wrapper_addresses[i] + 4, 4, 0);
    }
    /* Each reserved bit mixed with valid bits must reject the entire write. */
    for (unsigned bit = 0; bit < 32; ++bit) {
        uint32_t mask = UINT32_C(1) << bit;
        if ((mask & SCU_HCLK_MASK) == 0) {
            reject_write(s, SCU_HCLK_SET, 4, mask | SCU_HCLK_MASK);
            reject_write(s, SCU_HCLK_CLEAR, 4, mask | SCU_HCLK_MASK);
        }
        if ((mask & SCU_APB_RESET_MASK) == 0) {
            reject_write(s, SCU_RESET_SET, 4, mask | SCU_APB_RESET_MASK);
            reject_write(s, SCU_RESET_CLEAR, 4, mask | SCU_APB_RESET_MASK);
        }
        if ((mask & SCU_WRAPPER_REQUEST_MASK) == 0) {
            for (unsigned i = 0; i < SCU_WRAPPER_COUNT; ++i) {
                reject_write(s, sony_pcie_scu_wrapper_addresses[i], 4,
                             mask | SCU_WRAPPER_REQUEST_MASK);
            }
        }
    }
    /* Opposite starting values catch partial SET and CLEAR mutations too. */
    assert(sony_pcie_scu_write(s, SCU_HCLK_CLEAR, 4, SCU_HCLK_MASK));
    assert(sony_pcie_scu_write(s, SCU_RESET_SET, 4, SCU_APB_RESET_MASK));
    for (unsigned bit = 0; bit < 32; ++bit) {
        uint32_t mask = UINT32_C(1) << bit;
        if ((mask & SCU_HCLK_MASK) == 0) {
            reject_write(s, SCU_HCLK_SET, 4, mask | SCU_HCLK_MASK);
            reject_write(s, SCU_HCLK_CLEAR, 4, mask | SCU_HCLK_MASK);
        }
        if ((mask & SCU_APB_RESET_MASK) == 0) {
            reject_write(s, SCU_RESET_SET, 4, mask | SCU_APB_RESET_MASK);
            reject_write(s, SCU_RESET_CLEAR, 4, mask | SCU_APB_RESET_MASK);
        }
    }
    uint32_t out = UINT32_C(0xdeadbeef);
    assert(!sony_pcie_scu_read(NULL, SCU_HCLK_STATUS, 4, &out));
    assert(out == UINT32_C(0xdeadbeef));
    assert(!sony_pcie_scu_read(NULL, SCU_HCLK_STATUS, 4, NULL));
    assert(!sony_pcie_scu_write(NULL, SCU_HCLK_SET, 4, 1));
    sony_pcie_scu_init(NULL);
    assert(guarded.before == UINT32_C(0x12345678));
    assert(guarded.after == UINT32_C(0x87654321));
}

int main(void)
{
    policy_and_w1();
    controllers();
    multi_controller_isolation();
    invalid_accesses();
    puts("SCU core: all tests passed");
    return 0;
}
