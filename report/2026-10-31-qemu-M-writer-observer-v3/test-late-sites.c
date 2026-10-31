/* SPDX-License-Identifier: MIT */
/* Draft: reuse the real production include and the existing host API mock.
 * Parent prerequisite in the existing registration mock, before its final else:
 *   else if (callback == late_exec) {
 *       assert(((uintptr_t)userdata & ~(uintptr_t)3U) == insn->pc);
 *       assert(((uintptr_t)userdata & (uintptr_t)3U) < LATE_SITE_COUNT);
 *   }
 * No replacement matcher, register decoder, logger, or QEMU mock lives here.
 */
#define main scope_observer_existing_test_main
#include "test-scope-observer.c"
#undef main

static const unsigned char late_fixture[2][12] = {
    {0x00, 0x00, 0x40, 0xb9, 0x1f, 0x04, 0x00, 0x71, 0x21, 0x01, 0x00, 0x54},
    {0xe0, 0x03, 0x13, 0xaa, 0x01, 0x00, 0x80, 0x52, 0x43, 0x72, 0x17, 0x94}
};
static const uint64_t late_fixture_offsets[2] = {
    UINT64_C(0x209ee54), UINT64_C(0x209ee94)
};

static void make_late_tb(struct qemu_plugin_tb *tb, uint64_t base,
                         size_t window, size_t prefix)
{
    assert(window < 2U && prefix <= 4U);
    memset(tb, 0, sizeof(*tb));
    tb->count = prefix + 3U;
    for (size_t i = 0; i < tb->count; ++i) {
        tb->insns[i].pc = base + late_fixture_offsets[window] - prefix * 4U + i * 4U;
        tb->insns[i].size = 4;
        tb->insns[i].copied = 4;
        if (i >= prefix) {
            memcpy(tb->insns[i].bytes, late_fixture[window] + (i - prefix) * 4U, 4);
        }
    }
}

static void bind_late_candidate(void)
{
    struct qemu_plugin_tb scope;
    make_tb(&scope, fixture_base, 2);
    translate_callback(&scope, translate_data);
    assert(observer.candidate_found && observer.candidate.base == fixture_base);
}

static void execute_late(struct qemu_plugin_insn *insn, uint64_t x0, uint64_t cpsr)
{
    model[REG_X0].value = x0;
    model[REG_CPSR].value = cpsr;
    /* Deliberately leave the readable GDB PC stale at the old callee entry. */
    execute(insn, fixture_caller);
}

static void late_cases(const char *scenario)
{
    struct qemu_plugin_tb load, request;
    struct qemu_plugin_insn *sites[3];
    make_late_tb(&load, fixture_base, 0, 2);
    make_late_tb(&request, fixture_base, 1, 1);
    sites[0] = &load.insns[3];
    sites[1] = &load.insns[4];
    sites[2] = &request.insns[3];
    if (strcmp(scenario, "late_reject") == 0) {
        struct qemu_plugin_tb tb, tail;
        bind_late_candidate();
        unsigned int before = registrations;
        for (size_t window = 0; window < 2U; ++window) {
            for (size_t n = 0; n < 3U; ++n) {
                make_late_tb(&tb, fixture_base, window, 0);
                tb.count = n;
                translate_callback(&tb, translate_data);
            }
            for (size_t j = 0; j < 3U; ++j) {
                make_late_tb(&tb, fixture_base, window, 0);
                tb.insns[j].size = j ? 8U : 2U;
                translate_callback(&tb, translate_data);
                make_late_tb(&tb, fixture_base, window, 0);
                tb.insns[j].copied = 3;
                translate_callback(&tb, translate_data);
                make_late_tb(&tb, fixture_base, window, 0);
                tb.insns[j].pc += 4U;
                translate_callback(&tb, translate_data);
            }
            for (size_t j = 0; j < 12U; ++j) {
                make_late_tb(&tb, fixture_base, window, 0);
                tb.insns[j / 4U].bytes[j % 4U] ^= 1U;
                translate_callback(&tb, translate_data);
            }
            for (size_t split = 1; split < 3U; ++split) {
                make_late_tb(&tb, fixture_base, window, 0);
                make_late_tb(&tail, fixture_base, window, 0);
                tb.count = split;
                memmove(tail.insns, tail.insns + split,
                        (3U - split) * sizeof(tail.insns[0]));
                tail.count = 3U - split;
                translate_callback(&tb, translate_data);
                translate_callback(&tail, translate_data);
            }
            for (unsigned int j = 0; j < 100U; ++j) {
                make_late_tb(&tb, fixture_base + UINT64_C(0x100000), window, 0);
                tb.insns[j % 3U].bytes[0] ^= 1U;
                translate_callback(&tb, translate_data);
            }
            static const uint64_t bad_bases[] = {
                0, 1, UINT64_C(0x1000000000000), UINT64_C(0xffff000000000000)
            };
            for (size_t j = 0; j < sizeof(bad_bases) / sizeof(bad_bases[0]); ++j) {
                make_late_tb(&tb, bad_bases[j], window, 0);
                translate_callback(&tb, translate_data);
            }
            make_late_tb(&tb, 0, window, 0);
            for (size_t j = 0; j < 3U; ++j) {
                tb.insns[j].pc = (late_fixture_offsets[window] & UINT64_C(0xfff)) + j * 4U;
            }
            translate_callback(&tb, translate_data);
        }
        assert(registrations == before && !reads && !observer.disabled && !observer.faults);
        assert(!late_sequence);
        return;
    }
    if (strcmp(scenario, "late_order_and_userdata") == 0) {
        struct qemu_plugin_tb other;
        void *saved[3];
        translate_callback(&load, translate_data);
        translate_callback(&request, translate_data);
        assert(!observer.candidate_found && registrations == 3U);
        model[REG_PC].ok = false;
        for (size_t s = 0; s < 3U; ++s) {
            saved[s] = sites[s]->userdata;
            for (unsigned int n = 0; n < 20U; ++n) {
                execute_late(sites[s], 1, UINT64_C(0xa00003c0));
            }
        }
        assert(!reads && !observer.faults && !late_sequence);
        bind_late_candidate();
        for (unsigned int n = 0; n < 1000U; ++n) {
            size_t w = n % 2U;
            make_late_tb(&other, fixture_base + UINT64_C(0x100000), w, 0);
            translate_callback(&other, translate_data);
            execute_late(&other.insns[w ? 2U : 1U], 1, UINT64_C(0xa00003c0));
            if (!w) {
                execute_late(&other.insns[2], 1, UINT64_C(0xa00003c0));
            }
        }
        assert(!reads && !observer.faults && !late_sequence && !observer.ambiguous);
        model[REG_PC].ok = true;
        for (size_t s = 0; s < 3U; ++s) {
            assert(sites[s]->userdata == saved[s]);
            execute_late(sites[s], 1, UINT64_C(0xa00003c0));
            assert(late_records[s] == 1U);
        }
        assert(late_sequence == 3U && live_buffers == 1U);
        return;
    }
    bind_late_candidate();
    /* A poisoned post-BL instruction must never supply bytes or be inspected. */
    request.insns[request.count].pc = request.insns[request.count - 1U].pc + 4U;
    request.insns[request.count].size = 4;
    request.insns[request.count].copied = 0;
    ++request.count;
    translate_callback(&load, translate_data);
    translate_callback(&request, translate_data);
    assert(instruction_reads == 12U && registrations == 4U);
    assert(!load.insns[2].callback && !request.insns[1].callback && !request.insns[2].callback);
    for (size_t s = 0; s < 3U; ++s) {
        assert(sites[s]->callback == late_exec);
        assert(((uintptr_t)sites[s]->userdata & ~(uintptr_t)3U) == sites[s]->pc);
        assert(((uintptr_t)sites[s]->userdata & (uintptr_t)3U) == s);
    }
    if (strcmp(scenario, "late_exact") == 0 ||
        strcmp(scenario, "late_optional_absent") == 0 ||
        strcmp(scenario, "late_kernel") == 0) {
        uint64_t mode = strcmp(scenario, "late_kernel") == 0 ? 5U : 0U;
        model[REG_X1].value = 0;
        execute_late(sites[0], UINT64_C(0x00000000fedcba98), UINT64_C(0xa00003c0) | mode);
        execute_late(sites[1], 1, UINT64_C(0x600003c0) | mode);
        execute_late(sites[2], model[REG_X19].value, UINT64_C(0x600003c0) | mode);
        assert(late_records[0] == 1 && late_records[1] == 1 && late_records[2] == 1);
        assert(late_sequence == 3U && !observer.faults && reg_reads[REG_X1] == 1U);
        assert(!reg_reads[REG_X2] && !reg_reads[REG_X20] && !reg_reads[REG_X21] &&
               !reg_reads[REG_X24] && !reg_reads[REG_X29]);
        if (strcmp(scenario, "late_optional_absent") == 0) {
            assert(!reg_reads[REG_SP] && !reg_reads[REG_TTBR0_EL1] &&
                   !reg_reads[REG_TPIDR_EL0] && reads == 19U);
        }
    } else if (strcmp(scenario, "late_raw") == 0) {
        execute_late(sites[0], UINT64_C(0xfeedface80000001), UINT64_C(0x600003c0));
        /* Keep even contradictory raw load/flags observations; never recompute Z. */
        execute_late(sites[1], 1, UINT64_C(0x200003c0));
        execute_late(sites[1], UINT64_C(0x80000001), UINT64_C(0x600003c0));
        model[REG_X1].value = UINT64_C(0xdeadbeef00000000);
        execute_late(sites[2], UINT64_C(0x123456789abcdef0), UINT64_C(0xa00003c0));
        model[REG_X1].value = UINT64_C(0x11223344cafebabe);
        execute_late(sites[2], UINT64_C(0x123456789abcdef0), UINT64_C(0xa00003c0));
        assert(late_records[0] == 1U && late_records[1] == 2U && late_records[2] == 2U);
        assert(late_sequence == 5U && !observer.faults && reg_reads[REG_X1] == 2U);
    } else if (strcmp(scenario, "late_limits") == 0) {
        struct qemu_plugin_tb scope, poweron;
        model[REG_X23].length = 7;
        for (unsigned int n = 0; n < 80U; ++n) {
            execute_late(sites[0], 1, UINT64_C(0xa00003c0));
        }
        assert(!late_sequence && observer.fault_lines == 32U && observer.suppressed_faults == 48U);
        model[REG_X23].length = 8;
        static const size_t order[3] = {0, 2, 1};
        for (size_t i = 0; i < 3U; ++i) {
            size_t s = order[i];
            assert(!late_records[s]);
            for (unsigned int n = 0; n < 20U; ++n) {
                execute_late(sites[s], 1, UINT64_C(0xa00003c0));
            }
            assert(late_records[s] == 16U && late_sequence == (i + 1U) * 16U);
        }
        unsigned int before_reads = reads;
        for (size_t s = 0; s < 3U; ++s) {
            execute_late(sites[s], 1, UINT64_C(0xa00003c0));
        }
        assert(reads == before_reads && reg_reads[REG_X1] == 16U);
        make_tb(&scope, fixture_base, 0);
        translate_callback(&scope, translate_data);
        model[REG_PC].value = scope.insns[0].pc;
        for (unsigned int n = 0; n < 32U; ++n) {
            execute(&scope.insns[0], fixture_base + lr_offsets[n % 2U]);
        }
        make_poweron_tb(&poweron, fixture_base, 0);
        translate_callback(&poweron, translate_data);
        for (unsigned int n = 0; n < 16U; ++n) {
            execute_poweron(&poweron.insns[0], fixture_raw_x2, fixture_caller);
        }
        assert(observer.records[0] == 16U && observer.records[1] == 16U);
        assert(observer.poweron_records == 16U && reg_reads[REG_X1] == 16U);
    } else if (strcmp(scenario, "late_x1_absent") == 0) {
        struct qemu_plugin_tb scope;
        assert(!observer.regs[REG_X1].found);
        execute_late(sites[2], 1, UINT64_C(0xa00003c0));
        assert(!late_sequence && observer.faults == 1U && !late_records[2]);
        model[REG_X1].ok = false;
        execute_late(sites[0], 1, UINT64_C(0xa00003c0));
        execute_late(sites[1], 1, UINT64_C(0x600003c0));
        make_tb(&scope, fixture_base, 0);
        translate_callback(&scope, translate_data);
        model[REG_PC].value = scope.insns[0].pc;
        execute(&scope.insns[0], fixture_base + lr_offsets[0]);
        execute(&scope.insns[0], fixture_base + lr_offsets[1]);
        assert(late_records[0] == 1U && late_records[1] == 1U && late_sequence == 2U);
        assert(observer.records[0] == 1U && observer.records[1] == 1U);
        assert(!observer.disabled && !reg_reads[REG_X1]);
    } else if (strncmp(scenario, "late_short_", 11) == 0 ||
               strncmp(scenario, "late_api_", 9) == 0 ||
               strncmp(scenario, "late_long_", 10) == 0) {
        bool api = strncmp(scenario, "late_api_", 9) == 0;
        bool longer = strncmp(scenario, "late_long_", 10) == 0;
        const char *name = scenario + (api ? 9U : longer ? 10U : 11U);
        size_t r;
        for (r = 0; r < REG_COUNT && strcmp(reg_names[r], name) != 0; ++r) {}
        assert(r < REG_COUNT);
        size_t s = r == REG_X1 ? 2U : 0U;
        if (api) { model[r].ok = false; }
        else { model[r].length = longer ? (r == REG_CPSR ? 8U : 9U) : model[r].length - 1U; }
        execute_late(sites[s], 1, UINT64_C(0xa00003c0));
        assert(!late_sequence && !late_records[s] && observer.faults == 1U);
        model[r].ok = true;
        model[r].length = r == REG_CPSR ? 4U : 8U;
        execute_late(sites[s], 1, UINT64_C(0xa00003c0));
        assert(late_sequence == 1U && late_records[s] == 1U);
    } else if (strcmp(scenario, "late_aarch32") == 0) {
        for (size_t s = 0; s < 3U; ++s) {
            execute_late(sites[s], 1, UINT64_C(0xa00003d0));
        }
        assert(!late_sequence && observer.faults == 3U && !reg_reads[REG_X1]);
        for (size_t s = 0; s < 3U; ++s) {
            execute_late(sites[s], 1, UINT64_C(0xa00003c0));
        }
        assert(late_sequence == 3U && !observer.disabled);
    } else if (strcmp(scenario, "late_vcpu") == 0 ||
               strcmp(scenario, "late_invalid_metadata") == 0) {
        if (strcmp(scenario, "late_vcpu") == 0) { current_vcpu = 1; }
        else { sites[0]->userdata = (void *)(uintptr_t)(sites[0]->pc | UINT64_C(3)); }
        execute_late(sites[0], 1, UINT64_C(0xa00003c0));
        assert(observer.disabled && !reads && !late_sequence && observer.faults == 1U);
        current_vcpu = 0;
        execute_late(sites[1], 1, UINT64_C(0xa00003c0));
        assert(!reads && !late_sequence);
    } else {
        assert(strcmp(scenario, "late_write_failure") == 0 ||
               strcmp(scenario, "late_flush_failure") == 0);
        fail_write = strcmp(scenario, "late_write_failure") == 0;
        fail_flush = strcmp(scenario, "late_flush_failure") == 0;
        execute_late(sites[0], 1, UINT64_C(0xa00003c0));
        assert(observer.io_failed && observer.disabled && !late_sequence && !late_records[0]);
        fail_write = false;
        fail_flush = false;
    }
}

int main(int argc, char **argv)
{
    char argument[8192];
    char *options[] = {argument};
    qemu_info_t info = {
        .target_name = "aarch64", .version = {.min = 7, .cur = 7},
        .system_emulation = true, .system = {.smp_vcpus = 1, .max_vcpus = 1}
    };
    assert(argc == 3);
    int length = snprintf(argument, sizeof(argument), "log=%s", argv[2]);
    assert(length > 0 && (size_t)length < sizeof(argument));
    init_model();
    model[REG_X19].value = UINT64_C(0x0123456789abcdef);
    if (strcmp(argv[1], "late_optional_absent") == 0) {
        missing = REG_SP;
        tokens_absent = true;
    }
    if (strcmp(argv[1], "late_x1_absent") == 0) { missing = REG_X1; }
    assert(qemu_plugin_install(1, &info, 1, options) == 0);
    init_callback(0, init_data);
    assert(observer.regs_ready && !observer.disabled);
    late_cases(argv[1]);
    finish();
    return 0;
}
