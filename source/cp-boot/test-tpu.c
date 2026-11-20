/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Host assertions for the configuration-only TPU core; no QEMU/VM required. */
#include "tpu.h"

#include <stdio.h>
#include <string.h>

static unsigned checks;
static unsigned failures;
#define CHECK(cond) do {                                                   \
    checks++;                                                              \
    if (!(cond)) {                                                         \
        failures++;                                                        \
        fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);       \
    }                                                                      \
} while (0)

static const uint32_t writable[] = {
    0x00, 0x04, 0x08, 0x0c, 0x14, 0x18, 0x1c,
    0x20, 0x24, 0x28, 0x2c, 0x30, 0x34,
};

static void test_virtual_reset_and_disconnected_clock(void)
{
    struct tpu s;
    uint16_t value = 0xbeef;

    CHECK(tpu_init(&s) == TPU_OK);
    CHECK(!s.clock_enabled && !s.reset_held && !s.runtime_unmodeled);
    for (unsigned i = 0; i < TPU_REGISTER_COUNT; i++) {
        CHECK(s.regs[i] == 0);
        CHECK(tpu_read(&s, i * 4u, &value) == TPU_ERR_GATED);
        CHECK(value == 0xbeef);
    }
    for (unsigned i = 0; i < sizeof(writable) / sizeof(writable[0]); i++) {
        CHECK(tpu_write(&s, writable[i], 0xffff) == TPU_ERR_GATED);
        CHECK(s.regs[writable[i] / 4u] == 0);
    }
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    for (unsigned i = 0; i < TPU_REGISTER_COUNT; i++) {
        CHECK(tpu_read(&s, i * 4u, &value) == TPU_OK && value == 0);
    }
}

static void test_all_configuration_slots(void)
{
    struct tpu s;
    uint16_t value = 0, low = 0, high = 0;

    CHECK(tpu_init(&s) == TPU_OK);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    for (unsigned i = 0; i < sizeof(writable) / sizeof(writable[0]); i++) {
        /* All values have bit0 clear so +2c stays stopped. */
        CHECK(tpu_write(&s, writable[i], 0xa500u | (writable[i] << 1)) == TPU_OK);
    }
    for (unsigned i = 0; i < sizeof(writable) / sizeof(writable[0]); i++) {
        CHECK(tpu_read(&s, writable[i], &value) == TPU_OK);
        CHECK(value == (uint16_t)(0xa500u | (writable[i] << 1)));
    }
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_OK && value == 0);
    CHECK(!s.runtime_unmodeled);
    CHECK(tpu_write(&s, 0x00, 0xffff) == TPU_OK);
    CHECK(tpu_read(&s, 0x00, &value) == TPU_OK && value == 0xffff);
    CHECK(tpu_write(&s, 0x00, 0) == TPU_OK);
    CHECK(tpu_read(&s, 0x00, &value) == TPU_OK && value == 0);
    CHECK(tpu_write(&s, 0x30, 0xcdef) == TPU_OK);
    CHECK(tpu_write(&s, 0x34, 0x89ab) == TPU_OK);
    CHECK(tpu_read(&s, 0x30, &low) == TPU_OK);
    CHECK(tpu_read(&s, 0x34, &high) == TPU_OK);
    CHECK((((uint32_t)high << 16) | low) == 0x89abcdefu);

    /* Command readback neither changes configuration nor manufactures status. */
    CHECK(tpu_write(&s, TPU_REG_CLEAR, 0x3f) == TPU_OK);
    CHECK(tpu_read(&s, TPU_REG_CLEAR, &value) == TPU_OK && value == 0x3f);
    CHECK(tpu_read(&s, 0x18, &value) == TPU_OK && value == 0xa530);
    CHECK(tpu_read(&s, 0x20, &value) == TPU_OK && value == 0xa540);
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_OK && value == 0);
}

static void test_enable_and_unmodeled_runtime(void)
{
    struct tpu s;
    struct tpu before;
    uint16_t value;

    CHECK(tpu_init(&s) == TPU_OK);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    CHECK(tpu_write(&s, TPU_REG_COUNTER, 0) == TPU_OK);
    CHECK(tpu_write(&s, TPU_REG_ENABLE, 0xfff3) == TPU_OK);
    CHECK(tpu_read(&s, TPU_REG_ENABLE, &value) == TPU_OK && value == 0xfff3);
    CHECK(s.runtime_unmodeled);
    memcpy(&before, &s, sizeof(s));
    value = 0xbeef;
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_ERR_RUNTIME);
    CHECK(value == 0xbeef);
    CHECK(tpu_read(&s, TPU_REG_COUNTER, &value) == TPU_ERR_RUNTIME);
    CHECK(value == 0xbeef);
    CHECK(tpu_write(&s, TPU_REG_COUNTER, 0) == TPU_ERR_RUNTIME);
    CHECK(memcmp(&s, &before, sizeof(s)) == 0);
    CHECK(tpu_write(&s, TPU_REG_CLEAR, 0x3f) == TPU_OK);
    CHECK(tpu_read(&s, TPU_REG_CLEAR, &value) == TPU_OK && value == 0x3f);
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_ERR_RUNTIME);
    CHECK(tpu_read(&s, TPU_REG_ENABLE, &value) == TPU_OK && value == 0xfff3);
    CHECK(tpu_write(&s, TPU_REG_ENABLE, 0xfff2) == TPU_OK);
    CHECK(tpu_read(&s, TPU_REG_ENABLE, &value) == TPU_OK && value == 0xfff2);
    CHECK(tpu_write(&s, TPU_REG_CLEAR, 0xffff) == TPU_OK);
    CHECK(tpu_read(&s, TPU_REG_CLEAR, &value) == TPU_OK && value == 0xffff);
    CHECK(tpu_write(&s, TPU_REG_COUNTER, 0) == TPU_OK);
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_ERR_RUNTIME);
    CHECK(tpu_read(&s, TPU_REG_COUNTER, &value) == TPU_ERR_RUNTIME);
    CHECK(s.runtime_unmodeled);
    CHECK(tpu_set_clock(&s, false) == TPU_OK);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    CHECK(s.runtime_unmodeled);
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_ERR_RUNTIME);
    CHECK(tpu_set_reset(&s, true) == TPU_OK);
    CHECK(tpu_set_reset(&s, false) == TPU_OK);
    CHECK(!s.runtime_unmodeled);
    CHECK(tpu_read(&s, TPU_REG_STATUS, &value) == TPU_OK && value == 0);
}

static void test_clock_preservation_and_reset(void)
{
    struct tpu s, before;
    uint16_t value = 0xbeef;

    CHECK(tpu_init(&s) == TPU_OK);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    CHECK(tpu_write(&s, 0x18, 0x1234) == TPU_OK);
    CHECK(tpu_write(&s, TPU_REG_ENABLE, 1) == TPU_OK);
    CHECK(tpu_set_clock(&s, false) == TPU_OK);
    memcpy(&before, &s, sizeof(s));
    CHECK(tpu_read(&s, 0x18, &value) == TPU_ERR_GATED && value == 0xbeef);
    CHECK(tpu_write(&s, 0x18, 0x5678) == TPU_ERR_GATED);
    CHECK(tpu_write(&s, TPU_REG_ENABLE, 0) == TPU_ERR_GATED);
    CHECK(memcmp(&s, &before, sizeof(s)) == 0);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    CHECK(tpu_read(&s, 0x18, &value) == TPU_OK && value == 0x1234);
    CHECK(tpu_read(&s, TPU_REG_ENABLE, &value) == TPU_OK && value == 1);
    CHECK(tpu_set_reset(&s, true) == TPU_OK);
    CHECK(s.clock_enabled && s.reset_held && !s.runtime_unmodeled);
    for (unsigned i = 0; i < TPU_REGISTER_COUNT; i++) {
        CHECK(s.regs[i] == 0);
    }
    value = 0xbeef;
    CHECK(tpu_read(&s, 0, &value) == TPU_ERR_GATED && value == 0xbeef);
    CHECK(tpu_write(&s, 0, 1) == TPU_ERR_GATED);
    CHECK(tpu_set_clock(&s, false) == TPU_OK);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    CHECK(s.reset_held);
    CHECK(tpu_set_reset(&s, true) == TPU_OK);
    CHECK(tpu_set_reset(&s, false) == TPU_OK);
    for (unsigned i = 0; i < TPU_REGISTER_COUNT; i++) {
        CHECK(tpu_read(&s, i * 4u, &value) == TPU_OK && value == 0);
    }
    CHECK(tpu_set_clock(&s, false) == TPU_OK);
    CHECK(tpu_set_reset(&s, true) == TPU_OK);
    CHECK(tpu_set_reset(&s, false) == TPU_OK);
    CHECK(!s.clock_enabled);
    CHECK(tpu_read(&s, 0, &value) == TPU_ERR_GATED);
}

static void test_invalid_access_and_null(void)
{
    static const uint32_t bad[] = {
        1, 2, 3, 6, 0x0e, 0x12, 0x16, 0x36, 0x38, 0x3c,
        0x40, 0xffc, 0x1000, 0xfffffffcu, 0xffffffffu,
    };
    struct tpu s, before;
    uint16_t value = 0xbeef;

    CHECK(tpu_init(&s) == TPU_OK);
    CHECK(tpu_set_clock(&s, true) == TPU_OK);
    CHECK(tpu_write(&s, 0, 0x1234) == TPU_OK);
    memcpy(&before, &s, sizeof(s));
    for (unsigned i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        CHECK(tpu_read(&s, bad[i], &value) == TPU_ERR_ACCESS);
        CHECK(value == 0xbeef);
        CHECK(tpu_write(&s, bad[i], 0xffff) == TPU_ERR_ACCESS);
        CHECK(memcmp(&s, &before, sizeof(s)) == 0);
    }
    CHECK(tpu_write(&s, TPU_REG_STATUS, 0x80) == TPU_ERR_ACCESS);
    CHECK(tpu_init(NULL) == TPU_ERR_ACCESS);
    CHECK(tpu_read(NULL, 0, &value) == TPU_ERR_ACCESS && value == 0xbeef);
    CHECK(tpu_read(&s, 0, NULL) == TPU_ERR_ACCESS);
    CHECK(tpu_write(NULL, 0, 0) == TPU_ERR_ACCESS);
    CHECK(tpu_set_clock(NULL, true) == TPU_ERR_ACCESS);
    CHECK(tpu_set_reset(NULL, true) == TPU_ERR_ACCESS);
    CHECK(memcmp(&s, &before, sizeof(s)) == 0);
}

static void test_six_independent_banks(void)
{
    struct tpu banks[TPU_BANK_COUNT];
    uint16_t value = 0;

    for (unsigned i = 0; i < TPU_BANK_COUNT; i++) {
        CHECK(tpu_init(&banks[i]) == TPU_OK);
        CHECK(tpu_set_clock(&banks[i], true) == TPU_OK);
        CHECK(tpu_write(&banks[i], 0x18, 0x100u + i) == TPU_OK);
    }
    CHECK(tpu_write(&banks[2], TPU_REG_ENABLE, 1) == TPU_OK);
    CHECK(tpu_set_reset(&banks[3], true) == TPU_OK);
    CHECK(tpu_set_reset(&banks[3], false) == TPU_OK);
    for (unsigned i = 0; i < TPU_BANK_COUNT; i++) {
        CHECK(tpu_read(&banks[i], 0x18, &value) == TPU_OK);
        CHECK(value == (i == 3 ? 0 : 0x100u + i));
        CHECK(tpu_read(&banks[i], TPU_REG_ENABLE, &value) == TPU_OK);
        CHECK(value == (i == 2 ? 1 : 0));
        CHECK(banks[i].runtime_unmodeled == (i == 2));
    }
}

int main(void)
{
    test_virtual_reset_and_disconnected_clock();
    test_all_configuration_slots();
    test_enable_and_unmodeled_runtime();
    test_clock_preservation_and_reset();
    test_invalid_access_and_null();
    test_six_independent_banks();
    if (failures) {
        fprintf(stderr, "TPU core: %u/%u CHECKS FAILED\n", failures, checks);
        return 1;
    }
    printf("TPU core: ALL %u CHECKS PASSED\n", checks);
    return 0;
}
