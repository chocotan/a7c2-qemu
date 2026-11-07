/* SPDX-License-Identifier: MIT */
#define RECORD_COUNT 3U
#define RECORD_BLOCK UINT64_C(0x247088c)
#define RECORD_DEST UINT64_C(0x7e43430)
static const char *const record_names[RECORD_COUNT] = {
    "model_record_update_inputs", "model_record_value_store_pre", "model_record_flag13_store_pre"
};
static const unsigned int record_indexes[RECORD_COUNT] = {0U, 4U, 7U};
static const unsigned char record36[36] = {
    0x02,0x03,0x80,0xd2,0x21,0xce,0x02,0x90,0x21,0x40,0x03,0x91,
    0x61,0x06,0x02,0x9b,0x20,0x04,0x00,0xb9,0x20,0x00,0x80,0x52,
    0x20,0x40,0x00,0x39,0x20,0x4c,0x00,0x39,0xf0,0xff,0xff,0x17
};

static bool record_base(uint64_t pc, uint64_t *base)
{
    if (pc < RECORD_BLOCK || pc > LOW48_MAX - sizeof(record36) + 1U) { return false; }
    *base = pc - RECORD_BLOCK;
    return *base && !(*base & UINT64_C(0xfff)) && *base <= LOW48_MAX - UINT64_C(0x7e5d577);
}

static void record_exec(unsigned int vcpu, void *userdata)
{
    uint64_t packed = (uint64_t)(uintptr_t)userdata;
    unsigned int site = (unsigned int)(packed & UINT64_C(3));
    uint64_t pc = packed & LOW48_MAX & ~UINT64_C(3), base, actual_pc, x0, x1, x19, x20, x21, lr, cpsr;
    char options[3][192];
    g_mutex_lock(&observer.lock);
    if (observer.closed || observer.disabled) { goto out; }
    if (vcpu != 0U || site >= RECORD_COUNT || packed & ~LOW48_MAX ||
        pc < record_indexes[site] * 4U ||
        !record_base(pc - record_indexes[site] * 4U, &base) ||
        !observer.record_anchor_seen || base != observer.record_base) {
        observer.disabled = true; observer.stop = "invalid_record_context";
        fault("reason=invalid_record_context packed_raw=0x%016" PRIx64, packed); goto out;
    }
    if (!observer.regs_ready || !read_exact(REG_X19, record_names[site], &x19)) { goto out; }
    if (x19 != UINT64_C(0xa24)) { increment(&observer.record_skipped[site]); goto out; }
    if (observer.record_records[site] == SITE_QUOTA) { increment(&observer.record_suppressed[site]); goto out; }
    if (!read_exact(REG_PC, record_names[site], &actual_pc) ||
        !read_exact(REG_X0, record_names[site], &x0) || !read_exact(REG_X1, record_names[site], &x1) ||
        !read_exact(REG_X20, record_names[site], &x20) || !read_exact(REG_X21, record_names[site], &x21) ||
        !read_exact(REG_X30, record_names[site], &lr) || !read_exact(REG_CPSR, record_names[site], &cpsr)) { goto out; }
    /* R_REGS may expose the exact TB entry PC while event_pc identifies this instruction. */
    if ((actual_pc != pc && actual_pc != base + RECORD_BLOCK) ||
        (site && x1 != base + RECORD_DEST) || (site == 2U && (uint32_t)x0 != 1U)) {
        observer.disabled = true; observer.stop = "record_register_contract";
        fault("reason=record_register_contract site=%s event_pc=0x%016" PRIx64
              " gdb_pc_raw=0x%016" PRIx64 " x1_raw=0x%016" PRIx64 " x0_raw=0x%016" PRIx64,
              record_names[site], pc, actual_pc, x1, x0); goto out;
    }
    switch (cpsr & UINT64_C(0x1f)) {
    case 0: case 4: case 5: case 8: case 9: case 12: case 13: break;
    default: fault("reason=invalid_record_mode site=%s cpsr_raw=0x%08" PRIx64, record_names[site], cpsr); goto out;
    }
    if (!optional(REG_SP, record_names[site], "sp", options[0]) ||
        !optional(REG_TTBR0_EL1, record_names[site], "ttbr0_el1", options[1]) ||
        !optional(REG_TPIDR_EL0, record_names[site], "tpidr_el0", options[2])) { goto out; }
    if (record("writer_record", "site=%s vcpu=0x0 ordinal=0x%x record_sequence=0x%x observation_sequence=0x%x "
        "callback_phase=before_instruction event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64
        " candidate_base=0x%016" PRIx64 " anchor_length=0x24 row_u64=0x%016" PRIx64
        " x0_raw=0x%016" PRIx64 " x1_raw=0x%016" PRIx64 " x19_raw=0x%016" PRIx64
        " x20_raw=0x%016" PRIx64 " x21_raw=0x%016" PRIx64 " x30_raw=0x%016" PRIx64
        " cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64 " context_mode=%s "
        "gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 "
        "x0_read_length=0x8 x0_api_ok=0x1 x1_read_length=0x8 x1_api_ok=0x1 "
        "x19_read_length=0x8 x19_api_ok=0x1 x20_read_length=0x8 x20_api_ok=0x1 "
        "x21_read_length=0x8 x21_api_ok=0x1 x30_read_length=0x8 x30_api_ok=0x1 "
        "cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1 %s %s %s "
        "invocation_pairing_verified=0x0 store_retirement_verified=0x0 memory_readback_verified=0x0",
        record_names[site], observer.record_records[site] + 1U, observer.record_sequence + 1U,
        observer.observation_sequence + 1U, pc, actual_pc, base, x19, x0, x1, x19, x20, x21,
        lr, cpsr, cpsr & UINT64_C(0x1f), (cpsr & UINT64_C(0x1f)) == 0U ? "EL0t" : "other_aarch64",
        options[0], options[1], options[2])) {
        ++observer.record_records[site]; ++observer.record_sequence; ++observer.observation_sequence;
    }
out:
    g_mutex_unlock(&observer.lock);
}

static int match_record(struct qemu_plugin_tb *tb, size_t start, size_t count, uint64_t pc)
{
    if (count - start < sizeof(record36) / 4U) { return 0; }
    for (size_t j = 0; j < sizeof(record36) / 4U; ++j) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, start + j);
        unsigned char bytes[4] = {0};
        if (qemu_plugin_insn_size(insn) != 4U || qemu_plugin_insn_vaddr(insn) != pc + 4U * j ||
            qemu_plugin_insn_data(insn, bytes, sizeof(bytes)) != sizeof(bytes) ||
            memcmp(bytes, record36 + 4U * j, sizeof(bytes))) { return -1; }
    }
    return 1;
}

static void record_translate(struct qemu_plugin_tb *tb, size_t index, size_t count, uint64_t pc)
{
    uint64_t base;
    int matched;
    if (!record_base(pc, &base)) { return; }
    matched = match_record(tb, index, count, pc);
    if (matched != 1) {
        if (matched == -1 && observer.record_anchor_seen && observer.record_base == base) {
            observer.disabled = true; observer.stop = "record_anchor_changed";
            fault("reason=record_anchor_changed translated_pc=0x%016" PRIx64, pc);
        }
        return;
    }
    if ((observer.record_anchor_seen && observer.record_base != base) ||
        (observer.candidate_found && observer.base != base) || (observer.origin_base && observer.origin_base != base) ||
        (observer.descriptor_anchor_seen && observer.descriptor_base != base) ||
        (observer.pointer_anchor_mask && observer.pointer_base != base)) {
        observer.ambiguous = true; observer.disabled = true; observer.stop = "record_base_conflict";
        observer.conflicting_base = base;
        fault("reason=record_base_conflict translated_pc=0x%016" PRIx64, pc); return;
    }
    observer.record_base = base; observer.record_anchor_seen = true;
    for (unsigned int site = 0; site < RECORD_COUNT; ++site) {
        struct qemu_plugin_insn *tap = qemu_plugin_tb_get_insn(tb, index + record_indexes[site]);
        qemu_plugin_register_vcpu_insn_exec_cb(tap, record_exec, QEMU_PLUGIN_CB_R_REGS,
            (void *)(uintptr_t)(qemu_plugin_insn_vaddr(tap) + site));
    }
}
