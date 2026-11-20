/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DRAFT, NOT RUN. Link the existing pinned cp-boot/scu.c, not a copy. */
#include "scu.h"
#include <assert.h>
int main(void)
{
    struct cp_scu s;
    uint32_t value = 0xdeadbeef;
    assert(cp_scu_init(&s, CP_SCU_PROFILE) == 0);
    assert(cp_scu_read(&s, 0x50, &value) == 0 && value == 0);
    assert(cp_scu_write(&s, 0x50, 0xa0000001) == 0);
    assert(cp_scu_write(&s, 0x54, 1u << 18) == 0);
    assert(cp_scu_read(&s, 0x50, &value) == 0 && value == 0xa0040001);
    assert(cp_scu_write(&s, 0x58, 1u << 18) == 0);
    assert(cp_scu_read(&s, 0x50, &value) == 0 && value == 0xa0000001);
    assert(cp_scu_write(&s, 0x350, 0x80000001) == 0);
    assert(cp_scu_write(&s, 0x354, 1u << 24) == 0);
    assert(cp_scu_read(&s, 0x350, &value) == 0 && value == 0x81000001);
    assert(cp_scu_write(&s, 0x358, 1u << 24) == 0);
    assert(cp_scu_read(&s, 0x350, &value) == 0 && value == 0x80000001);
    value = 0xdeadbeef;
    assert(cp_scu_read(&s, 0x54, &value) != 0 && value == 0xdeadbeef);
    assert(cp_scu_read(&s, 0x358, &value) != 0 && value == 0xdeadbeef);
    assert(cp_scu_write(&s, 0x35c, 0xffffffff) != 0);
    assert(cp_scu_write(&s, 0x340, 0xffffffff) != 0);
    assert(cp_scu_write(&s, 0x51, 1u << 18) != 0);
    return 0;
}
