/* SPDX-License-Identifier: MIT */
#include <qemu-plugin.h>
#include <errno.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#if QEMU_PLUGIN_VERSION != 7
#error "This observer requires the reviewed QEMU plugin API 7 header"
#endif

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;

#define CALLEE_OFFSET UINT64_C(0x2e068cc)
#define POWERON_OFFSET UINT64_C(0x1951844)
#define PRODUCER_OFFSET UINT64_C(0x276e710)
#define M_OFFSET UINT64_C(0x7e6a7c8)
#define PRODUCER_QUOTA 16U
#define LOW48_MAX UINT64_C(0x0000ffffffffffff)
#define LR_QUOTA 16U
#define POWERON_QUOTA 16U
#define FAULT_QUOTA 32U
#define MAX_DESCRIPTORS 4096U
#define LINE_LIMIT 2048U

static const uint64_t lr_offsets[2] = {
    UINT64_C(0x209ee80), UINT64_C(0x209ee88)
};
static const unsigned char head24[24] = {
    0xfd, 0x7b, 0xb9, 0xa9, 0x81, 0xd1, 0x02, 0xd0,
    0x21, 0xe0, 0x17, 0x91, 0xfd, 0x03, 0x00, 0x91,
    0xf7, 0x63, 0x03, 0xa9, 0xb7, 0x83, 0x01, 0x91
};

/* Low-48 PCs travel as opaque userdata values, never dereferenced pointers. */
_Static_assert(UINTPTR_MAX == UINT64_MAX, "Poweron userdata requires a 64-bit host");
static const unsigned char poweron_head8[8] = {
    0x50, 0x00, 0x00, 0x58, 0x00, 0x02, 0x1f, 0xd6
};

static const unsigned char producer_head24[24] = {
    0x01, 0xb7, 0x02, 0xd0, 0x21, 0x60, 0x13, 0x91,
    0x21, 0x68, 0x40, 0x91, 0x20, 0xf0, 0x02, 0xb9,
    0x20, 0xf8, 0x02, 0xb9, 0xc0, 0x03, 0x5f, 0xd6
};
static const char *const producer_sites[2] = {"entry", "pre_M_store"};

enum reg_index {
    REG_PC, REG_X0, REG_X19, REG_X20, REG_X21, REG_X23, REG_X24,
    REG_X29, REG_X30, REG_CPSR, REG_SP, REG_TTBR0_EL1, REG_TPIDR_EL0,
    REG_X2, REG_X1, REG_COUNT
};
static const char *const reg_names[REG_COUNT] = {
    "pc", "x0", "x19", "x20", "x21", "x23", "x24", "x29", "x30", "cpsr", "sp",
    "TTBR0_EL1", "TPIDR_EL0", "x2", "x1"
};
struct reg_ref {
    struct qemu_plugin_register *handle;
    bool found;
};
struct candidate {
    uint64_t entry;
    uint64_t base;
};
static struct {
    GMutex lock;
    FILE *log;
    GByteArray *buffer;
    struct reg_ref regs[REG_COUNT];
    struct candidate candidate;
    struct candidate producer;
    uint64_t producer_conflicting_base;
    unsigned int producer_records[2];
    unsigned int producer_sequence;
    bool producer_anchor_found;
    uint64_t conflicting_base;
    uint64_t faults;
    uint64_t suppressed_faults;
    uint64_t other_lr;
    unsigned int fault_lines;
    unsigned int records[2];
    unsigned int poweron_records;
    bool install_called;
    bool vcpu_initialized;
    bool regs_ready;
    bool candidate_found;
    bool ambiguous;
    bool disabled;
    bool io_failed;
    bool io_reported;
    bool closed;
    const char *stop;
} observer;

static void increment(uint64_t *value)
{
    if (*value != UINT64_MAX) {
        ++*value;
    }
}

static void io_failure(const char *stage)
{
    int saved_errno = errno;
    observer.io_failed = true;
    observer.disabled = true;
    observer.stop = "host_io_failure";
    if (!observer.io_reported) {
        observer.io_reported = true;
        (void)fprintf(stderr,
            "scope_observer_host_error stage=%s errno=0x%x "
            "status=native_unverified identity=unknown capture=0x0 physical=0x0\n",
            stage, (unsigned int)saved_errno);
    }
}

static bool record_v(const char *kind, const char *format, va_list args)
{
    char body[1536];
    char line[LINE_LIMIT];
    int body_length;
    int length;
    if (!observer.log || observer.io_failed || observer.closed) {
        return false;
    }
    body_length = vsnprintf(body, sizeof(body), format, args);
    if (body_length < 0 || (size_t)body_length >= sizeof(body) ||
        strchr(body, '\n') || strchr(body, '\r')) {
        errno = EINVAL;
        io_failure("format");
        return false;
    }
    length = snprintf(line, sizeof(line),
        "kind=%s %s status=native_unverified identity=unknown binding=unbound "
        "pid=unknown tid=unknown capture=0x0 physical=0x0\n", kind, body);
    if (length < 0 || (size_t)length >= sizeof(line)) {
        errno = EINVAL;
        io_failure("line_limit");
        return false;
    }
    errno = 0;
    if (fwrite(line, 1, (size_t)length, observer.log) != (size_t)length) {
        io_failure("write");
        return false;
    }
    if (fflush(observer.log) != 0 || ferror(observer.log)) {
        io_failure("flush");
        return false;
    }
    return true;
}

static bool record(const char *kind, const char *format, ...)
{
    va_list args;
    bool result;
    va_start(args, format);
    result = record_v(kind, format, args);
    va_end(args);
    return result;
}

static void fault(const char *format, ...)
{
    va_list args;
    increment(&observer.faults);
    if (observer.fault_lines >= FAULT_QUOTA) {
        increment(&observer.suppressed_faults);
        return;
    }
    va_start(args, format);
    if (record_v("fault", format, args)) {
        ++observer.fault_lines;
    }
    va_end(args);
}

/* Only untagged, zero-extended low-48 addresses are in this observer's scope. */
static bool derive_base(uint64_t entry, uint64_t *base)
{
    uint64_t candidate;
    if ((entry & UINT64_C(0xfff)) != UINT64_C(0x8cc) ||
        entry < CALLEE_OFFSET || entry > LOW48_MAX - (sizeof(head24) - 1)) {
        return false;
    }
    candidate = entry - CALLEE_OFFSET;
    if (!candidate || (candidate & UINT64_C(0xfff)) != 0) {
        return false;
    }
    *base = candidate;
    return true;
}

static bool derive_poweron_base(uint64_t entry, uint64_t *base)
{
    uint64_t candidate;
    if ((entry & UINT64_C(0xfff)) != UINT64_C(0x844) ||
        entry < POWERON_OFFSET || entry > LOW48_MAX - (sizeof(poweron_head8) - 1)) {
        return false;
    }
    candidate = entry - POWERON_OFFSET;
    if (!candidate || (candidate & UINT64_C(0xfff)) != 0) {
        return false;
    }
    *base = candidate;
    return true;
}

static bool read_exact(enum reg_index index, uint64_t *value)
{
    size_t required = index == REG_CPSR ? 4U : 8U;
    bool ok;
    if (!observer.regs[index].found) {
        fault("reason=unknown_register reg=%s required_length=0x%zx "
              "read_attempted=0x0 read_length=0x0 api_ok=0x0",
              reg_names[index], required);
        return false;
    }
    /* GDB access appends: clear both storage and length before every call. */
    g_byte_array_set_size(observer.buffer, 8);
    memset(observer.buffer->data, 0, 8);
    g_byte_array_set_size(observer.buffer, 0);
    ok = qemu_plugin_read_register(observer.regs[index].handle, observer.buffer);
    if (!ok || observer.buffer->len != required) {
        fault("reason=register_read reg=%s required_length=0x%zx "
              "read_attempted=0x1 read_length=0x%x api_ok=0x%x",
              reg_names[index], required, observer.buffer->len, ok ? 1U : 0U);
        return false;
    }
    *value = 0;
    for (size_t i = 0; i < required; ++i) {
        *value |= (uint64_t)observer.buffer->data[i] << (8U * i);
    }
    return true;
}

#include "late-sites.inc"

static bool derive_producer_base(uint64_t entry, uint64_t *base)
{
    uint64_t candidate;
    if (!late_base(entry, PRODUCER_OFFSET, sizeof(producer_head24), &candidate) ||
        candidate > LOW48_MAX - (M_OFFSET + 11U)) {
        return false;
    }
    /* Include both original u32 destinations in the checked low-48 envelope. */
    *base = candidate;
    return true;
}

static void producer_conflict(const char *cause, uint64_t conflicting_base)
{
    observer.producer_conflicting_base = conflicting_base;
    observer.ambiguous = true;
    observer.disabled = true;
    observer.stop = "producer_base_conflict";
    fault("reason=producer_base_conflict cause=%s producer_base=0x%016" PRIx64
          " candidate_base=0x%016" PRIx64 " conflicting_base=0x%016" PRIx64,
          cause, observer.producer.base, observer.candidate.base, conflicting_base);
}

static void producer_exec(unsigned int vcpu_index, void *userdata)
{
    uintptr_t packed = (uintptr_t)userdata;
    unsigned int site = (unsigned int)(packed & (uintptr_t)3U);
    uint64_t event_pc = (uint64_t)(packed & ~(uintptr_t)3U);
    uint64_t base;
    uint64_t values[REG_COUNT] = {0};
    char optional[3][160];
    char detail[256];
    static const enum reg_index required[] = {REG_PC, REG_X0, REG_X30, REG_CPSR};
    g_mutex_lock(&observer.lock);
    if (vcpu_index != 0) {
        observer.disabled = true;
        observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit site=M_producer vcpu=0x%x", vcpu_index);
        goto out;
    }
    if (observer.disabled || !observer.regs_ready || observer.closed) {
        goto out;
    }
    if (site >= 2U || event_pc < (site ? 12U : 0U) ||
        !derive_producer_base(event_pc - (site ? 12U : 0U), &base) ||
        !observer.producer_anchor_found || base != observer.producer.base) {
        observer.disabled = true;
        observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context site=M_producer vcpu=0x%x", vcpu_index);
        goto out;
    }
    if (observer.producer_records[site] >= PRODUCER_QUOTA) {
        goto out;
    }
    for (size_t i = 0; i < sizeof(required) / sizeof(required[0]); ++i) {
        enum reg_index r = required[i];
        if (!read_exact(r, &values[r])) {
            goto out;
        }
    }
    switch (values[REG_CPSR] & UINT64_C(0x1f)) {
    case 0: case 4: case 5: case 8: case 9: case 12: case 13:
        break;
    default:
        fault("reason=not_aarch64 site=%s cpsr_raw=0x%08" PRIx64
              " cpsr_m=0x%02" PRIx64, producer_sites[site],
              values[REG_CPSR], values[REG_CPSR] & UINT64_C(0x1f));
        goto out;
    }
    if (site == 1U) {
        uint64_t destination;
        if (!read_exact(REG_X1, &values[REG_X1])) {
            goto out;
        }
        if (values[REG_X1] > UINT64_MAX - UINT64_C(0x2f0)) {
            fault("reason=producer_destination_overflow site=pre_M_store "
                  "x1_raw=0x%016" PRIx64 " candidate_base=0x%016" PRIx64,
                  values[REG_X1], base);
            goto out;
        }
        destination = values[REG_X1] + UINT64_C(0x2f0);
        if (destination != base + M_OFFSET) {
            fault("reason=producer_destination_mismatch site=pre_M_store "
                  "x1_raw=0x%016" PRIx64 " effective_destination_raw=0x%016" PRIx64
                  " expected_destination_raw=0x%016" PRIx64,
                  values[REG_X1], destination, base + M_OFFSET);
            goto out;
        }
        (void)snprintf(detail, sizeof(detail),
            "proposed_u32=0x%08" PRIx32 " x1_raw=0x%016" PRIx64
            " x1_read_length=0x8 x1_api_ok=0x1 effective_destination_raw=0x%016" PRIx64
            " destination_match=0x1", (uint32_t)values[REG_X0], values[REG_X1], destination);
    } else {
        (void)snprintf(detail, sizeof(detail), "proposed_u32=unknown");
    }
    if (!late_optional(REG_SP, "sp", optional[0]) ||
        !late_optional(REG_TTBR0_EL1, "ttbr0_el1", optional[1]) ||
        !late_optional(REG_TPIDR_EL0, "tpidr_el0", optional[2])) {
        goto out;
    }
    /* GDB PC can be lazy; the immutable translated event PC selects the tap. */
    if (record("M_producer",
        "site=%s vcpu=0x%x ordinal=0x%x producer_sequence=0x%x "
        "callback_phase=before_instruction event_pc=0x%016" PRIx64
        " gdb_pc_raw=0x%016" PRIx64 " candidate_base=0x%016" PRIx64
        " scope_anchor_seen=0x%x anchor_length=0x18 input_kind=u32_value "
        "x0_raw=0x%016" PRIx64 " raw_input_u32=0x%08" PRIx32
        " x30_raw=0x%016" PRIx64 " caller_raw=0x%016" PRIx64
        " cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64 " context_mode=%s "
        "nzcv=0x%08" PRIx64 " nzcv_mask=0xf0000000 %s %s %s %s "
        "gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 x0_read_length=0x8 x0_api_ok=0x1 "
        "x30_read_length=0x8 x30_api_ok=0x1 cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1",
        producer_sites[site], vcpu_index, observer.producer_records[site] + 1U,
        observer.producer_sequence + 1U, event_pc, values[REG_PC], base,
        observer.candidate_found ? 1U : 0U, values[REG_X0], (uint32_t)values[REG_X0],
        values[REG_X30], values[REG_X30], values[REG_CPSR],
        values[REG_CPSR] & UINT64_C(0x1f),
        (values[REG_CPSR] & UINT64_C(0x1f)) == 0 ? "EL0t" : "other_aarch64",
        values[REG_CPSR] & UINT64_C(0xf0000000), optional[0], optional[1], optional[2],
        detail)) {
        ++observer.producer_records[site];
        ++observer.producer_sequence;
    }
out:
    g_mutex_unlock(&observer.lock);
}

static void entry_exec(unsigned int vcpu_index, void *userdata)
{
    const struct candidate *candidate = userdata;
    uint64_t values[REG_COUNT] = {0};
    unsigned int slot;
    char sp[64];
    char tokens[2][112];
    static const char *const token_fields[2] = {"ttbr0_el1", "tpidr_el0"};
    g_mutex_lock(&observer.lock);
    if (vcpu_index != 0) {
        observer.disabled = true;
        observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit vcpu=0x%x", vcpu_index);
        goto out;
    }
    if (observer.disabled || !observer.regs_ready || observer.closed ||
        (observer.records[0] == LR_QUOTA && observer.records[1] == LR_QUOTA)) {
        goto out;
    }
    if (candidate != &observer.candidate || !observer.candidate_found) {
        observer.disabled = true;
        observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context vcpu=0x%x", vcpu_index);
        goto out;
    }
    if (!read_exact(REG_PC, &values[REG_PC])) {
        goto out;
    }
    if (values[REG_PC] != candidate->entry) {
        fault("reason=pc_mismatch vcpu=0x%x actual_pc=0x%016" PRIx64
              " translated_entry_pc=0x%016" PRIx64,
              vcpu_index, values[REG_PC], candidate->entry);
        goto out;
    }
    if (!read_exact(REG_X30, &values[REG_X30])) {
        goto out;
    }
    if (values[REG_X30] == candidate->base + lr_offsets[0]) {
        slot = 0;
    } else if (values[REG_X30] == candidate->base + lr_offsets[1]) {
        slot = 1;
    } else {
        increment(&observer.other_lr);
        goto out;
    }
    if (observer.records[slot] >= LR_QUOTA) {
        goto out;
    }
    for (enum reg_index i = REG_X0; i < REG_X2; ++i) {
        if (i == REG_X30 || (i >= REG_SP && !observer.regs[i].found)) {
            continue;
        }
        if (!read_exact(i, &values[i])) {
            goto out;
        }
    }
    if (values[REG_CPSR] & UINT64_C(0x10)) {
        fault("reason=not_aarch64 cpsr_raw=0x%08" PRIx64, values[REG_CPSR]);
        goto out;
    }
    if (observer.regs[REG_SP].found) {
        (void)snprintf(sp, sizeof(sp), "sp=0x%016" PRIx64 " sp_read_length=0x8",
                       values[REG_SP]);
    } else {
        (void)snprintf(sp, sizeof(sp), "sp=unknown sp_read_length=0x0");
    }
    for (size_t t = 0; t < 2; ++t) {
        enum reg_index r = t == 0 ? REG_TTBR0_EL1 : REG_TPIDR_EL0;
        if (observer.regs[r].found) {
            (void)snprintf(tokens[t], sizeof(tokens[t]),
                "%s_available=0x1 %s_raw=0x%016" PRIx64 " %s_read_length=0x8",
                token_fields[t], token_fields[t], values[r], token_fields[t]);
        } else {
            (void)snprintf(tokens[t], sizeof(tokens[t]),
                "%s_available=0x0 %s_raw=unknown %s_read_length=0x0",
                token_fields[t], token_fields[t], token_fields[t]);
        }
    }
    if (record("entry",
        "vcpu=0x%x lr_slot=0x%x ordinal=0x%x actual_pc=0x%016" PRIx64
        " translated_entry_pc=0x%016" PRIx64 " candidate_base=0x%016" PRIx64
        " lr=0x%016" PRIx64 " x0=0x%016" PRIx64 " x19=0x%016" PRIx64
        " x20=0x%016" PRIx64 " x21=0x%016" PRIx64 " x23=0x%016" PRIx64
        " x24=0x%016" PRIx64 " x29=0x%016" PRIx64 " x30=0x%016" PRIx64
        " cpsr_raw=0x%08" PRIx64 " nzcv=0x%08" PRIx64 " nzcv_mask=0xf0000000 "
        "cpsr_m=0x%02" PRIx64 " context_mode=%s "
        "%s %s %s pc_read_length=0x8 lr_read_length=0x8 x0_read_length=0x8 "
        "x19_read_length=0x8 x20_read_length=0x8 x21_read_length=0x8 "
        "x23_read_length=0x8 x24_read_length=0x8 x29_read_length=0x8 "
        "x30_read_length=0x8 cpsr_read_length=0x4 api_ok=0x1",
        vcpu_index, slot, observer.records[slot] + 1U,
        values[REG_PC], candidate->entry, candidate->base,
        values[REG_X30], values[REG_X0], values[REG_X19], values[REG_X20],
        values[REG_X21], values[REG_X23], values[REG_X24], values[REG_X29],
        values[REG_X30], values[REG_CPSR], values[REG_CPSR] & UINT64_C(0xf0000000),
        values[REG_CPSR] & UINT64_C(0x1f),
        (values[REG_CPSR] & UINT64_C(0x1f)) == 0 ? "EL0t" : "other_aarch64",
        sp, tokens[0], tokens[1])) {
        ++observer.records[slot];
    }
out:
    g_mutex_unlock(&observer.lock);
}

static void poweron_exec(unsigned int vcpu_index, void *userdata)
{
    uint64_t entry = (uint64_t)(uintptr_t)userdata;
    uint64_t base;
    uint64_t pc, controller, raw, caller, cpsr;
    char tokens[2][160];
    static const char *const token_fields[2] = {"ttbr0_el1", "tpidr_el0"};
    g_mutex_lock(&observer.lock);
    if (vcpu_index != 0) {
        observer.disabled = true;
        observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit site=dispatch vcpu=0x%x", vcpu_index);
        goto out;
    }
    if (observer.disabled || !observer.regs_ready || observer.closed ||
        observer.poweron_records >= POWERON_QUOTA) {
        goto out;
    }
    if (!derive_poweron_base(entry, &base)) {
        observer.disabled = true;
        observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context site=dispatch vcpu=0x%x", vcpu_index);
        goto out;
    }
    /* Filter w2 first so unrelated dispatch values spend no log or fault quota. */
    if (!read_exact(REG_X2, &raw) ||
        ((uint32_t)raw & UINT32_C(0xff000fff)) != UINT32_C(0x01000090)) {
        goto out;
    }
    if (!read_exact(REG_PC, &pc)) {
        goto out;
    }
    if (pc != entry) {
        fault("reason=pc_mismatch site=dispatch vcpu=0x%x actual_pc=0x%016" PRIx64
              " translated_entry_pc=0x%016" PRIx64, vcpu_index, pc, entry);
        goto out;
    }
    if (!read_exact(REG_CPSR, &cpsr)) {
        goto out;
    }
    if (cpsr & UINT64_C(0x10)) {
        fault("reason=not_aarch64 site=dispatch cpsr_raw=0x%08" PRIx64
              " cpsr_m=0x%02" PRIx64, cpsr, cpsr & UINT64_C(0x1f));
        goto out;
    }
    if ((cpsr & UINT64_C(0x1f)) != 0) {
        fault("reason=poweron_not_el0t site=dispatch cpsr_raw=0x%08" PRIx64
              " cpsr_m=0x%02" PRIx64 " context_mode=other_aarch64",
              cpsr, cpsr & UINT64_C(0x1f));
        goto out;
    }
    if (!read_exact(REG_X0, &controller) || !read_exact(REG_X30, &caller)) {
        goto out;
    }
    for (size_t t = 0; t < 2; ++t) {
        enum reg_index r = t == 0 ? REG_TTBR0_EL1 : REG_TPIDR_EL0;
        uint64_t value;
        if (observer.regs[r].found) {
            if (!read_exact(r, &value)) {
                goto out;
            }
            (void)snprintf(tokens[t], sizeof(tokens[t]),
                "%s_available=0x1 %s_raw=0x%016" PRIx64
                " %s_read_length=0x8 %s_api_ok=0x1",
                token_fields[t], token_fields[t], value, token_fields[t], token_fields[t]);
        } else {
            (void)snprintf(tokens[t], sizeof(tokens[t]),
                "%s_available=0x0 %s_raw=unknown %s_read_length=0x0 %s_api_ok=unknown",
                token_fields[t], token_fields[t], token_fields[t], token_fields[t]);
        }
    }
    if (record("poweron_context",
        "site=dispatch vcpu=0x%x ordinal=0x%x actual_pc=0x%016" PRIx64
        " translated_entry_pc=0x%016" PRIx64 " candidate_base=0x%016" PRIx64
        " anchor_length=0x8 controller=0x%016" PRIx64 " raw_x2=0x%016" PRIx64
        " raw_u32=0x%08" PRIx32 " caller_raw=0x%016" PRIx64
        " cpsr_raw=0x%08" PRIx64 " nzcv=0x%08" PRIx64
        " nzcv_mask=0xf0000000 cpsr_m=0x%02" PRIx64 " context_mode=EL0t "
        "%s %s pc_read_length=0x8 x0_read_length=0x8 x2_read_length=0x8 "
        "x30_read_length=0x8 cpsr_read_length=0x4 api_ok=0x1",
        vcpu_index, observer.poweron_records + 1U, pc, entry, base,
        controller, raw, (uint32_t)raw, caller, cpsr, cpsr & UINT64_C(0xf0000000),
        cpsr & UINT64_C(0x1f), tokens[0], tokens[1])) {
        ++observer.poweron_records;
    }
out:
    g_mutex_unlock(&observer.lock);
}

static void tb_trans(struct qemu_plugin_tb *tb, void *userdata)
{
    size_t count = qemu_plugin_tb_n_insns(tb);
    (void)userdata;
    g_mutex_lock(&observer.lock);
    late_translate(tb);
    for (size_t i = 0; i < count && !observer.disabled && !observer.closed; ++i) {
        struct qemu_plugin_insn *first = qemu_plugin_tb_get_insn(tb, i);
        uint64_t entry = qemu_plugin_insn_vaddr(first);
        uint64_t base;
        const char *change = NULL;
        size_t inspected = 0;
        size_t copied = 0;
        if (derive_producer_base(entry, &base)) {
            if (count - i < 6U) {
                change = "partial_tb";
            } else {
                for (size_t j = 0; j < 6U; ++j) {
                    struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i + j);
                    unsigned char bytes[4] = {0};
                    inspected = j;
                    copied = 0;
                    if (qemu_plugin_insn_size(insn) != 4U ||
                        qemu_plugin_insn_vaddr(insn) != entry + 4U * j) {
                        change = "insn_shape";
                        break;
                    }
                    copied = qemu_plugin_insn_data(insn, bytes, sizeof(bytes));
                    if (copied != sizeof(bytes) ||
                        memcmp(bytes, producer_head24 + 4U * j, 4U) != 0) {
                        change = "insn_bytes";
                        break;
                    }
                }
            }
            if (change) {
                if (observer.producer_anchor_found && entry == observer.producer.entry) {
                    observer.disabled = true;
                    observer.stop = "producer_anchor_changed";
                    fault("reason=producer_anchor_changed cause=%s translated_pc=0x%016" PRIx64
                          " insn_index=0x%zx read_length=0x%zx remaining_insns=0x%zx",
                          change, entry, inspected, copied, count - i);
                }
                continue;
            }
            if (observer.producer_anchor_found && observer.producer.base != base) {
                producer_conflict("producer_vs_producer", base);
                break;
            }
            if (!observer.producer_anchor_found) {
                observer.producer = (struct candidate){.entry = entry, .base = base};
                observer.producer_anchor_found = true;
            }
            if (observer.candidate_found && observer.candidate.base != base) {
                producer_conflict("producer_vs_scope", observer.candidate.base);
                break;
            }
            for (unsigned int site = 0; site < 2U; ++site) {
                struct qemu_plugin_insn *insn =
                    qemu_plugin_tb_get_insn(tb, i + (site ? 3U : 0U));
                uint64_t event_pc = qemu_plugin_insn_vaddr(insn);
                qemu_plugin_register_vcpu_insn_exec_cb(insn, producer_exec,
                    QEMU_PLUGIN_CB_R_REGS, (void *)(uintptr_t)(event_pc | site));
            }
            continue;
        }
        if (derive_poweron_base(entry, &base)) {
            bool matches = count - i >= 2U;
            for (size_t j = 0; j < 2U && matches; ++j) {
                struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i + j);
                unsigned char bytes[4] = {0};
                matches = qemu_plugin_insn_size(insn) == 4 &&
                    qemu_plugin_insn_vaddr(insn) == entry + 4U * j;
                if (matches) {
                    matches = qemu_plugin_insn_data(insn, bytes, sizeof(bytes)) == 4 &&
                        memcmp(bytes, poweron_head8 + j * 4U, 4) == 0;
                }
            }
            if (matches) {
                qemu_plugin_register_vcpu_insn_exec_cb(first, poweron_exec,
                    QEMU_PLUGIN_CB_R_REGS, (void *)(uintptr_t)entry);
            }
            continue;
        }
        if (!derive_base(entry, &base)) {
            continue;
        }
        if (count - i < 6U) {
            change = "partial_tb";
        } else {
            for (size_t j = 0; j < 6; ++j) {
                struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i + j);
                unsigned char bytes[4] = {0};
                inspected = j;
                copied = 0;
                if (qemu_plugin_insn_size(insn) != 4 ||
                    qemu_plugin_insn_vaddr(insn) != entry + 4U * j) {
                    change = "insn_shape";
                    break;
                }
                copied = qemu_plugin_insn_data(insn, bytes, sizeof(bytes));
                if (copied != sizeof(bytes) || memcmp(bytes, head24 + j * 4U, 4) != 0) {
                    change = "insn_bytes";
                    break;
                }
            }
        }
        if (change) {
            if (observer.candidate_found && entry == observer.candidate.entry) {
                observer.disabled = true;
                observer.stop = "anchor_changed";
                fault("reason=anchor_changed cause=%s translated_pc=0x%016" PRIx64
                      " insn_index=0x%zx read_length=0x%zx remaining_insns=0x%zx",
                      change, entry, inspected, copied, count - i);
            }
            continue;
        }
        if (observer.candidate_found && observer.candidate.base != base) {
            observer.ambiguous = true;
            observer.disabled = true;
            observer.stop = "ambiguous_base";
            observer.conflicting_base = base;
            fault("reason=ambiguous_base candidate_base=0x%016" PRIx64
                  " conflicting_base=0x%016" PRIx64, observer.candidate.base, base);
            break;
        }
        if (!observer.candidate_found) {
            observer.candidate.entry = entry;
            observer.candidate.base = base;
            observer.candidate_found = true;
            if (!record("candidate", "candidate_base=0x%016" PRIx64
                        " translated_entry_pc=0x%016" PRIx64 " anchor_length=0x18",
                        base, entry)) {
                break;
            }
        }
        if (observer.producer_anchor_found && observer.producer.base != base) {
            producer_conflict("scope_vs_producer", base);
            break;
        }
        qemu_plugin_register_vcpu_insn_exec_cb(first, entry_exec,
                                               QEMU_PLUGIN_CB_R_REGS,
                                               &observer.candidate);
    }
    g_mutex_unlock(&observer.lock);
}

static void vcpu_init(unsigned int vcpu_index, void *userdata)
{
    GArray *descriptors;
    (void)userdata;
    g_mutex_lock(&observer.lock);
    if (observer.disabled || observer.closed) {
        goto out;
    }
    if (vcpu_index != 0 || observer.vcpu_initialized) {
        observer.disabled = true;
        observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit vcpu=0x%x reinitialized=0x%x",
              vcpu_index, observer.vcpu_initialized ? 1U : 0U);
        goto out;
    }
    observer.vcpu_initialized = true;
    descriptors = qemu_plugin_get_registers();
    if (!descriptors || !descriptors->len || descriptors->len > MAX_DESCRIPTORS) {
        observer.disabled = true;
        observer.stop = "register_list";
        fault("reason=register_list descriptor_count=0x%x",
              descriptors ? descriptors->len : 0U);
    } else {
        for (guint i = 0; i < descriptors->len; ++i) {
            const qemu_plugin_reg_descriptor *desc =
                &g_array_index(descriptors, qemu_plugin_reg_descriptor, i);
            for (size_t r = 0; r < REG_COUNT; ++r) {
                if (desc->name && strcmp(desc->name, reg_names[r]) == 0) {
                    if (observer.regs[r].found) {
                        observer.disabled = true;
                        observer.stop = "duplicate_register";
                        fault("reason=duplicate_register reg=%s", reg_names[r]);
                    }
                    /* x0's valid handle is NULL in QEMU's GDB index encoding. */
                    observer.regs[r].handle = desc->handle;
                    observer.regs[r].found = true;
                }
            }
        }
        for (size_t r = 0; r < REG_SP; ++r) {
            if (!observer.regs[r].found) {
                observer.disabled = true;
                observer.stop = "unknown_register";
                fault("reason=unknown_register reg=%s read_attempted=0x0 "
                      "read_length=0x0", reg_names[r]);
            }
        }
        observer.regs_ready = !observer.disabled;
    }
    if (descriptors) {
        g_array_unref(descriptors);
    }
out:
    g_mutex_unlock(&observer.lock);
}

static void plugin_exit(void *userdata)
{
    (void)userdata;
    g_mutex_lock(&observer.lock);
    if (!observer.closed) {
        (void)record("end", "stop=%s ambiguous=0x%x candidate_found=0x%x "
            "candidate_base=0x%016" PRIx64 " conflicting_base=0x%016" PRIx64
            " lr0_records=0x%x lr1_records=0x%x poweron_records=0x%x fault_lines=0x%x "
            "faults=0x%016" PRIx64 " suppressed_faults=0x%016" PRIx64
            " other_lr=0x%016" PRIx64 " late0_records=0x%x late1_records=0x%x "
            "late2_records=0x%x late_sequence=0x%x producer_anchor_found=0x%x "
            "producer_base=0x%016" PRIx64 " producer_conflicting_base=0x%016" PRIx64
            " producer0_records=0x%x producer1_records=0x%x producer_sequence=0x%x "
            "close_result=unknown",
            observer.stop ? observer.stop : "none", observer.ambiguous ? 1U : 0U,
            observer.candidate_found ? 1U : 0U, observer.candidate.base,
            observer.conflicting_base, observer.records[0], observer.records[1],
            observer.poweron_records, observer.fault_lines, observer.faults,
            observer.suppressed_faults, observer.other_lr,
            late_records[0], late_records[1], late_records[2], late_sequence,
            observer.producer_anchor_found ? 1U : 0U, observer.producer.base,
            observer.producer_conflicting_base, observer.producer_records[0],
            observer.producer_records[1], observer.producer_sequence);
        observer.closed = true;
        observer.disabled = true;
        if (observer.log && fclose(observer.log) != 0) {
            io_failure("close");
        }
        observer.log = NULL;
        if (observer.buffer) {
            g_byte_array_unref(observer.buffer);
            observer.buffer = NULL;
        }
    }
    g_mutex_unlock(&observer.lock);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id,
    const qemu_info_t *info, int argc, char **argv)
{
    const char *reason = NULL;
    if (observer.install_called) {
        (void)fprintf(stderr, "scope_observer_host_error reason=duplicate_install\n");
        return 1;
    }
    observer.install_called = true;
    if (argc != 1 || !argv || !argv[0] || strncmp(argv[0], "log=/", 5) != 0 ||
        strlen(argv[0]) > 4096 || strchr(argv[0], '\n') || strchr(argv[0], '\r')) {
        (void)fprintf(stderr, "scope_observer_host_error reason=one_absolute_host_log_required\n");
        return 1;
    }
    observer.log = fopen(argv[0] + 4, "wx");
    if (!observer.log) {
        io_failure("exclusive_open");
        return 1;
    }
    if (!record("begin", "schema=readonly_scope_v2 plugin_api=0x%x "
                "max_vcpus=0x1 lr_quota=0x%x fault_quota=0x%x "
                "identity_limit=raw_context_only_no_pid_tid_module_identity "
                "register_byte_order=little anchor_length=0x18 "
                "poweron_quota=0x%x poweron_anchor_length=0x8 "
                "producer_sites=0x2 producer_quota=0x%x producer_anchor_length=0x18",
                QEMU_PLUGIN_VERSION, LR_QUOTA, FAULT_QUOTA, POWERON_QUOTA,
                PRODUCER_QUOTA)) {
        plugin_exit(NULL);
        return 1;
    }
    if (!info || !info->target_name || strcmp(info->target_name, "aarch64") != 0) {
        reason = "target_requires_aarch64_little_endian";
    } else if (info->version.min > QEMU_PLUGIN_VERSION ||
               info->version.cur < QEMU_PLUGIN_VERSION) {
        reason = "plugin_api_range";
    } else if (!info->system_emulation) {
        reason = "system_emulation_required";
    } else if (info->system.smp_vcpus != 1 || info->system.max_vcpus != 1) {
        reason = "single_vcpu_required";
    }
    if (reason) {
        observer.disabled = true;
        observer.stop = reason;
        fault("reason=%s", reason);
        plugin_exit(NULL);
        return 1;
    }
    observer.buffer = g_byte_array_sized_new(8);
    qemu_plugin_register_vcpu_init_cb(id, vcpu_init, NULL);
    qemu_plugin_register_vcpu_tb_trans_cb(id, tb_trans, NULL);
    qemu_plugin_register_atexit_cb(id, plugin_exit, NULL);
    return 0;
}
