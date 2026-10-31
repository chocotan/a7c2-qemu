/* SPDX-License-Identifier: MIT */
/* Include after read_exact(); call late_translate() with observer.lock held. */
#include <inttypes.h>

#define LATE_QUOTA 16U
#define LATE_SITE_COUNT 3U

static const struct {
    const char *name;
    uint64_t offset;
} late_sites[LATE_SITE_COUNT] = {
    {"M_cmp_pre", UINT64_C(0x209ee58)},
    {"M_bne_pre", UINT64_C(0x209ee5c)},
    {"request0_bl_pre", UINT64_C(0x209ee9c)}
};
static const struct {
    uint64_t offset;
    unsigned char bytes[12];
} late_windows[2] = {
    {UINT64_C(0x209ee54), {
        0x00, 0x00, 0x40, 0xb9, 0x1f, 0x04, 0x00, 0x71,
        0x21, 0x01, 0x00, 0x54
    }},
    {UINT64_C(0x209ee94), {
        0xe0, 0x03, 0x13, 0xaa, 0x01, 0x00, 0x80, 0x52,
        0x43, 0x72, 0x17, 0x94
    }}
};
static unsigned int late_records[LATE_SITE_COUNT];
static unsigned int late_sequence;

static bool late_base(uint64_t pc, uint64_t offset, size_t span, uint64_t *base)
{
    uint64_t candidate;
    if ((pc & UINT64_C(0xfff)) != (offset & UINT64_C(0xfff)) ||
        pc < offset || pc > LOW48_MAX - (span - 1U)) {
        return false;
    }
    candidate = pc - offset;
    if (!candidate || (candidate & UINT64_C(0xfff)) != 0) {
        return false;
    }
    *base = candidate;
    return true;
}

static bool late_optional(enum reg_index reg, const char *name, char output[160])
{
    uint64_t value;
    if (!observer.regs[reg].found) {
        (void)snprintf(output, 160,
            "%s_available=0x0 %s_raw=unknown %s_read_length=0x0 %s_api_ok=unknown",
            name, name, name, name);
        return true;
    }
    if (!read_exact(reg, &value)) {
        return false;
    }
    (void)snprintf(output, 160,
        "%s_available=0x1 %s_raw=0x%016" PRIx64
        " %s_read_length=0x8 %s_api_ok=0x1", name, name, value, name, name);
    return true;
}

static void late_exec(unsigned int vcpu_index, void *userdata)
{
    uintptr_t packed = (uintptr_t)userdata;
    unsigned int site = (unsigned int)(packed & (uintptr_t)3U);
    uint64_t event_pc = (uint64_t)(packed & ~(uintptr_t)3U);
    uint64_t base;
    uint64_t values[REG_COUNT] = {0};
    char optional[3][160];
    char detail[256];
    static const enum reg_index required[] = {
        REG_PC, REG_X0, REG_X19, REG_X23, REG_X30, REG_CPSR
    };
    g_mutex_lock(&observer.lock);
    if (vcpu_index != 0) {
        observer.disabled = true;
        observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit site=late vcpu=0x%x", vcpu_index);
        goto out;
    }
    if (observer.disabled || !observer.regs_ready || observer.closed) {
        goto out;
    }
    if (site >= LATE_SITE_COUNT ||
        !late_base(event_pc, late_sites[site].offset, 4U, &base)) {
        observer.disabled = true;
        observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context site=late vcpu=0x%x", vcpu_index);
        goto out;
    }
    /* Translation order must not bind a common CMP collision to the candidate. */
    if (!observer.candidate_found || base != observer.candidate.base ||
        late_records[site] >= LATE_QUOTA) {
        goto out;
    }
    for (size_t i = 0; i < sizeof(required) / sizeof(required[0]); ++i) {
        enum reg_index r = required[i];
        if (!read_exact(r, &values[r])) {
            goto out;
        }
    }
    if (values[REG_CPSR] & UINT64_C(0x10)) {
        fault("reason=not_aarch64 site=%s cpsr_raw=0x%08" PRIx64
              " cpsr_m=0x%02" PRIx64, late_sites[site].name,
              values[REG_CPSR], values[REG_CPSR] & UINT64_C(0x1f));
        goto out;
    }
    if (site == 2U && !read_exact(REG_X1, &values[REG_X1])) {
        goto out;
    }
    if (!late_optional(REG_SP, "sp", optional[0]) ||
        !late_optional(REG_TTBR0_EL1, "ttbr0_el1", optional[1]) ||
        !late_optional(REG_TPIDR_EL0, "tpidr_el0", optional[2])) {
        goto out;
    }
    if (site == 0U) {
        /* x0 is the original LDR's result here; the CMP has not run. */
        (void)snprintf(detail, sizeof(detail),
            "loaded_M_u32=0x%08" PRIx32 " flags_phase=before_cmp",
            (uint32_t)values[REG_X0]);
    } else if (site == 1U) {
        uint64_t z = (values[REG_CPSR] >> 30U) & UINT64_C(1);
        (void)snprintf(detail, sizeof(detail),
            "loaded_M_u32=0x%08" PRIx32 " flags_phase=after_cmp_before_bne "
            "z=0x%" PRIx64 " source_next_pc=0x%016" PRIx64
            " source_next_basis=cpsr_Z",
            (uint32_t)values[REG_X0], z,
            base + (z ? UINT64_C(0x209ee60) : UINT64_C(0x209ee80)));
    } else {
        /* Preserve actual arguments and the current LR, including anomalies. */
        (void)snprintf(detail, sizeof(detail),
            "x1=0x%016" PRIx64 " w1=0x%08" PRIx32
            " x1_read_length=0x8 x1_api_ok=0x1 lr_phase=before_bl",
            values[REG_X1], (uint32_t)values[REG_X1]);
    }
    if (record("late",
        "site=%s vcpu=0x%x ordinal=0x%x late_sequence=0x%x "
        "callback_phase=before_instruction event_pc=0x%016" PRIx64
        " gdb_pc_raw=0x%016" PRIx64 " candidate_base=0x%016" PRIx64
        " anchor_length=0xc x0=0x%016" PRIx64 " x19=0x%016" PRIx64
        " x23=0x%016" PRIx64 " x30=0x%016" PRIx64
        " cpsr_raw=0x%08" PRIx64 " nzcv=0x%08" PRIx64
        " nzcv_mask=0xf0000000 cpsr_m=0x%02" PRIx64 " context_mode=%s "
        "%s %s %s %s gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 "
        "x0_read_length=0x8 x0_api_ok=0x1 x19_read_length=0x8 x19_api_ok=0x1 "
        "x23_read_length=0x8 x23_api_ok=0x1 x30_read_length=0x8 x30_api_ok=0x1 "
        "cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1",
        late_sites[site].name, vcpu_index, late_records[site] + 1U, late_sequence + 1U,
        event_pc, values[REG_PC], base, values[REG_X0], values[REG_X19],
        values[REG_X23], values[REG_X30], values[REG_CPSR],
        values[REG_CPSR] & UINT64_C(0xf0000000), values[REG_CPSR] & UINT64_C(0x1f),
        (values[REG_CPSR] & UINT64_C(0x1f)) == 0 ? "EL0t" : "other_aarch64",
        optional[0], optional[1], optional[2], detail)) {
        ++late_records[site];
        ++late_sequence;
    }
out:
    g_mutex_unlock(&observer.lock);
}

static void late_register(struct qemu_plugin_insn *insn, unsigned int site)
{
    uint64_t event_pc = qemu_plugin_insn_vaddr(insn);
    /* Low two bits carry the fixed site; this opaque value is never dereferenced. */
    qemu_plugin_register_vcpu_insn_exec_cb(insn, late_exec, QEMU_PLUGIN_CB_R_REGS,
        (void *)(uintptr_t)(event_pc | site));
}

static void late_translate(struct qemu_plugin_tb *tb)
{
    size_t count = qemu_plugin_tb_n_insns(tb);
    /* The parent holds observer.lock; no shared or heap callback metadata exists. */
    for (size_t i = 0; i < count && !observer.disabled && !observer.closed; ++i) {
        struct qemu_plugin_insn *first = qemu_plugin_tb_get_insn(tb, i);
        uint64_t entry = qemu_plugin_insn_vaddr(first);
        uint64_t base;
        size_t window;
        bool matches;
        if ((entry & UINT64_C(0xfff)) == UINT64_C(0xe54)) {
            window = 0;
        } else if ((entry & UINT64_C(0xfff)) == UINT64_C(0xe94)) {
            window = 1;
        } else {
            continue;
        }
        if (!late_base(entry, late_windows[window].offset, 12U, &base) || count - i < 3U) {
            continue;
        }
        matches = true;
        for (size_t j = 0; j < 3U && matches; ++j) {
            struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i + j);
            unsigned char bytes[4] = {0};
            matches = qemu_plugin_insn_size(insn) == 4U &&
                qemu_plugin_insn_vaddr(insn) == entry + 4U * j;
            if (matches) {
                matches = qemu_plugin_insn_data(insn, bytes, sizeof(bytes)) == 4U &&
                    memcmp(bytes, late_windows[window].bytes + 4U * j, 4U) == 0;
            }
        }
        if (!matches) {
            continue;
        }
        if (window == 0U) {
            late_register(qemu_plugin_tb_get_insn(tb, i + 1U), 0U);
            late_register(qemu_plugin_tb_get_insn(tb, i + 2U), 1U);
        } else {
            late_register(qemu_plugin_tb_get_insn(tb, i + 2U), 2U);
        }
    }
}
