/* Local ABI self-check; HOST_TEST, not native CP execution or capture. */
#define _GNU_SOURCE
#include "cp-property-stage-file.h"
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

#define CHECK(condition) do { if (!(condition)) return __LINE__; } while (0)
int check_stage_entry(uintptr_t *stack)
{
    static const char success[] = "PASS: original libc read public CP stage, mode/profile/ALH and defaults decision\n";
    static const char hex[] = "0123456789abcdef";
    char alh_hex[4 + CP_PROPERTY_STAGE_ALH_BYTES * 2 + 1];
    struct cp_property_stage stage, before;
    struct cp_parameter_import decision, saved_decision;
    struct cp_property_stage_readback value;
    struct cp_start_state_guard guard = {
        (uint32_t)getpid(), 2, 2, CP_START_STATE_ORIGIN_HOST_TEST, 1
    };
    CHECK(stack[0] == 2);
    int fd = open((const char *)stack[2], O_RDONLY | O_CLOEXEC);
    CHECK(fd >= 0);
    CHECK(cp_property_stage_init(&stage) == 0);
    errno = EDOM;
    CHECK(cp_property_stage_load_public_file(&stage, &guard, fd, &decision) == 0);
    CHECK(errno == EDOM);
    CHECK(cp_property_stage_snapshot(&stage, &guard, &value) == 0);
    CHECK(value.mode_property_known && value.profile_known && value.alh_property_known == 1 && value.mode == 1);
    CHECK(value.ALH_context[0xb8] == 0xff);
    memcpy(alh_hex, "alh=", 4);
    for (size_t i = 0; i < sizeof(value.ALH_context); ++i) {
        alh_hex[4 + i * 2] = hex[value.ALH_context[i] >> 4];
        alh_hex[5 + i * 2] = hex[value.ALH_context[i] & 15];
    }
    alh_hex[sizeof(alh_hex) - 1] = '\n';
    CHECK(value.context[4] == 0 && value.context[0x17] == 0 && value.context[0x20] == 1);
    CHECK(value.stage_fnv1a64 == CP_PROPERTY_STAGE_FNV1A64);
    CHECK(value.source_origin == CP_START_STATE_ORIGIN_HOST_TEST && value.source_sequence == 2);
    CHECK(decision.properties_consumed && decision.defaults_selected && !decision.import_selected);
    CHECK(decision.header == 0 && decision.flags == 0);
    before = stage; saved_decision = decision;
    CHECK(cp_property_stage_load_public_file(&stage, &guard, fd, &decision) == -EALREADY);
    CHECK(memcmp(&stage, &before, sizeof(stage)) == 0);
    CHECK(memcmp(&decision, &saved_decision, sizeof(decision)) == 0);
    CHECK(cp_property_stage_load_public_file(&stage, &guard, -1, &decision) == -EINVAL);
    CHECK(errno == EDOM);
    CHECK(close(fd) == 0);
    CHECK(write(1, alh_hex, sizeof(alh_hex)) == (ssize_t)sizeof(alh_hex));
    CHECK(write(1, success, sizeof(success) - 1) == (ssize_t)(sizeof(success) - 1));
    return 0;
}
__attribute__((naked)) void _start(void)
{
    __asm__("mov x0, sp\n"
            "bl check_stage_entry\n"
            "mov x8, #93\n"
            "svc #0\n");
}
