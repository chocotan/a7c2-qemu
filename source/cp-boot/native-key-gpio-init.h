/* SPDX-License-Identifier: GPL-2.0-or-later */
/*
 * Verbatim opcode2 (32-bit) writes: official BK4 ed000, property 0x00f9014a.
 * PP SHA256: 3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47
 * Record SHA256: a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977
 * Property SHA256: 03abbbe71a874a4a3a78d3fa9ab32104756e0f6ee0d00c1ab99dd808ac23fa70
 * Comments give zero-based original item indices; original order is retained.
 * This does not establish NOR execution. Virtual reset is explicitly 0
 * elsewhere in the functional model, not a claim about physical reset.
 */
#ifndef CP_NATIVE_KEY_GPIO_INIT_H
#define CP_NATIVE_KEY_GPIO_INIT_H

#include <stdint.h>

struct cp_key_gpio_initial_write {
    uint8_t port;
    uint8_t offset;
    uint32_t value;
};

static const struct cp_key_gpio_initial_write cp_key_gpio_init[] = {
    { 6, 0x48, 0x00000022u }, /* 135: WDATA_CLR */
    { 6, 0x34, 0x0000003au }, /* 136: PORTSEL_SET */
    { 6, 0x38, 0x00000005u }, /* 137: PORTSEL_CLR */
    { 6, 0x04, 0x00000022u }, /* 138: DIR_SET */
    { 6, 0x08, 0x00000018u }, /* 139: DIR_CLR */
    { 6, 0x24, 0x00000018u }, /* 140: INEN_SET */
    { 6, 0x28, 0x00000027u }, /* 141: INEN_CLR */
    { 7, 0x34, 0x001e0000u }, /* 142: PORTSEL_SET */
    { 7, 0x08, 0x001e0000u }, /* 143: DIR_CLR */
    { 7, 0x24, 0x001e0000u }, /* 144: INEN_SET */
    { 11, 0x44, 0x00000140u }, /* 161: WDATA_SET */
    { 11, 0x48, 0x2643a0a0u }, /* 162: WDATA_CLR */
    { 11, 0x34, 0x2e57a3e0u }, /* 163: PORTSEL_SET */
    { 11, 0x38, 0x00800003u }, /* 164: PORTSEL_CLR */
    { 11, 0x04, 0x2643a1e0u }, /* 165: DIR_SET */
    { 11, 0x08, 0x08140200u }, /* 166: DIR_CLR */
    { 11, 0x24, 0x08140203u }, /* 167: INEN_SET */
    { 11, 0x28, 0x26c3a1e0u }, /* 168: INEN_CLR */
};

#endif /* CP_NATIVE_KEY_GPIO_INIT_H */
