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
_Static_assert(UINTPTR_MAX == UINT64_MAX, "Opaque event PCs require a flat 64-bit host");
QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;

#define LOW48_MAX UINT64_C(0x0000ffffffffffff)
#define STUB_BIT UINT64_C(0x0001000000000000)
#define SITE4_BIT UINT64_C(0x0002000000000000)
#define SITE_COUNT 5U
#define SITE_QUOTA 16U
#define FAULT_QUOTA 32U
#define MAX_DESCRIPTORS 4096U
#define LINE_LIMIT 2048U

static const char *const site_names[SITE_COUNT] = {
    "final_entry", "d570_cbnz_pre", "successor_1724_pre", "successor_1838_pre", "d570_ldr_pre"
};
static const uint64_t event_offsets[SITE_COUNT] = {
    UINT64_C(0x1af16dc), UINT64_C(0x1af1834),
    UINT64_C(0x1af1724), UINT64_C(0x1af1838), UINT64_C(0x1af1830)
};
static const uint64_t anchor_offsets[SITE_COUNT] = {
    UINT64_C(0x1af16dc), UINT64_C(0x1af1830),
    UINT64_C(0x1af1724), UINT64_C(0x1af1838), UINT64_C(0x1af1830)
};
static const unsigned char original16[16] = {
    0xfd,0x7b,0xbb,0xa9,0xfd,0x03,0x00,0x91,
    0xf5,0x5b,0x02,0xa9,0xf6,0x03,0x01,0x2a
};
static const unsigned char stub8[8] = {0x50,0x00,0x00,0x58,0x00,0x02,0x1f,0xd6};
static const unsigned char gate8[8] = {0x00,0x00,0x40,0xb9,0x80,0xf7,0xff,0x35};
static const unsigned char successor1724[8] = {0xb3,0x23,0x01,0x91,0xe0,0x03,0x13,0xaa};
static const unsigned char successor1838[8] = {0xe0,0x03,0x13,0xaa,0x44,0xb1,0x28,0x94};
/* Site4 shares site1's discriminator; match the window only once. */
static const unsigned char *const anchors[] = {
    original16, gate8, successor1724, successor1838
};

enum reg_index {
    REG_PC, REG_X0, REG_X1, REG_X2, REG_X3, REG_X19, REG_X22,
    REG_X23, REG_X29, REG_X30, REG_CPSR, REG_SP, REG_TTBR0_EL1,
    REG_TPIDR_EL0, REG_COUNT
};
static const char *const reg_names[REG_COUNT] = {
    "pc", "x0", "x1", "x2", "x3", "x19", "x22", "x23", "x29", "x30",
    "cpsr", "sp", "TTBR0_EL1", "TPIDR_EL0"
};
struct reg_ref { struct qemu_plugin_register *handle; bool found; };
static struct {
    GMutex lock;
    FILE *log;
    GByteArray *buffer;
    struct reg_ref regs[REG_COUNT];
    uint64_t base, conflicting_base, faults, suppressed_faults;
    uint64_t suppressed[SITE_COUNT], unbound[SITE_COUNT];
    unsigned int records[SITE_COUNT], sequence, fault_lines, anchor_seen_mask;
    bool install_called, initialized, regs_ready, candidate_found, ambiguous;
    bool disabled, closed, io_failed, io_reported;
    const char *stop;
} observer;

static void increment(uint64_t *value)
{
    if (*value != UINT64_MAX) { ++*value; }
}

static void io_failure(const char *stage)
{
    int saved = errno;
    observer.io_failed = true;
    observer.disabled = true;
    observer.stop = "host_io_failure";
    if (!observer.io_reported) {
        observer.io_reported = true;
        (void)fprintf(stderr, "scope_observer_host_error stage=%s errno=0x%x "
            "status=native_unverified identity=unknown capture=0x0 physical=0x0 retirement=0x0\n",
            stage, (unsigned int)saved);
    }
}

static bool record_v(const char *kind, const char *format, va_list args)
{
    char body[1900], line[LINE_LIMIT];
    int body_length, length;
    if (!observer.log || observer.closed || observer.io_failed) { return false; }
    body_length = vsnprintf(body, sizeof(body), format, args);
    if (body_length < 0 || (size_t)body_length >= sizeof(body) ||
        strchr(body, '\n') || strchr(body, '\r')) {
        errno = EINVAL;
        io_failure("format");
        return false;
    }
    length = snprintf(line, sizeof(line),
        "kind=%s %s status=native_unverified identity=unknown binding=unbound "
        "pid=unknown tid=unknown capture=0x0 physical=0x0 retirement=0x0\n", kind, body);
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
    bool ok;
    va_start(args, format);
    ok = record_v(kind, format, args);
    va_end(args);
    return ok;
}

static void fault(const char *format, ...)
{
    va_list args;
    increment(&observer.faults);
    if (observer.fault_lines == FAULT_QUOTA) {
        increment(&observer.suppressed_faults);
        return;
    }
    va_start(args, format);
    if (record_v("fault", format, args)) { ++observer.fault_lines; }
    va_end(args);
}

static bool derive_base(uint64_t anchor_pc, unsigned int site, uint64_t *base)
{
    uint64_t b;
    size_t span = site == 0U ? 16U : 8U;
    if (site >= SITE_COUNT || anchor_pc < anchor_offsets[site] ||
        anchor_pc > LOW48_MAX - (span - 1U)) { return false; }
    b = anchor_pc - anchor_offsets[site];
    if (!b || (b & UINT64_C(0xfff)) || b > LOW48_MAX - UINT64_C(0x1af183f)) {
        return false;
    }
    /* The envelope includes every full anchor, event and predicted successor. */
    *base = b;
    return true;
}

static bool read_exact(enum reg_index r, unsigned int site, uint64_t *value)
{
    size_t required = r == REG_CPSR ? 4U : 8U;
    bool ok;
    if (!observer.regs[r].found) {
        fault("reason=unknown_register reg=%s required_length=0x%zx "
              "read_attempted=0x0 read_length=0x0 api_ok=0x0", reg_names[r], required);
        return false;
    }
    /* QEMU appends; clear all prior backing bytes as well as the visible length. */
    if (observer.buffer->len) { memset(observer.buffer->data, 0, observer.buffer->len); }
    g_byte_array_set_size(observer.buffer, 8);
    memset(observer.buffer->data, 0, 8);
    g_byte_array_set_size(observer.buffer, 0);
    ok = qemu_plugin_read_register(observer.regs[r].handle, observer.buffer);
    if (!ok || observer.buffer->len != required) {
        fault("reason=register_read site=%s reg=%s required_length=0x%zx "
              "read_attempted=0x1 read_length=0x%x api_ok=0x%x",
              site_names[site], reg_names[r], required, observer.buffer->len, ok ? 1U : 0U);
        return false;
    }
    *value = 0;
    for (size_t i = 0; i < required; ++i) {
        *value |= (uint64_t)observer.buffer->data[i] << (8U * i);
    }
    return true;
}

static bool optional(enum reg_index r, unsigned int site, const char *name, char out[192])
{
    uint64_t value;
    int length;
    if (observer.regs[r].found) {
        if (!read_exact(r, site, &value)) { return false; }
        length = snprintf(out, 192, "%s_available=0x1 %s_raw=0x%016" PRIx64
            " %s_read_length=0x8 %s_api_ok=0x1", name, name, value, name, name);
    } else {
        length = snprintf(out, 192, "%s_available=0x0 %s_raw=unknown "
            "%s_read_length=0x0 %s_api_ok=unknown", name, name, name, name);
    }
    if (length < 0 || length >= 192) {
        errno = EINVAL;
        io_failure("optional_format");
        return false;
    }
    return true;
}

static void site_exec(unsigned int vcpu, void *userdata)
{
    uint64_t packed = (uint64_t)(uintptr_t)userdata;
    unsigned int site = (unsigned int)(packed & 3U) | ((packed & SITE4_BIT) ? 4U : 0U);
    bool stub = (packed & STUB_BIT) != 0;
    uint64_t event_pc = packed & LOW48_MAX & ~UINT64_C(3);
    uint64_t base, values[REG_COUNT] = {0};
    char options[3][192], detail[512], prediction[192];
    int length;
    static const enum reg_index common[] = {REG_PC,REG_X0,REG_X30,REG_CPSR};
    static const enum reg_index entry[] = {REG_X1,REG_X2,REG_X3};
    static const enum reg_index internal[] = {REG_X19,REG_X22,REG_X23,REG_X29};
    g_mutex_lock(&observer.lock);
    if (observer.closed || observer.disabled) { goto out; }
    if (vcpu != 0U) {
        observer.disabled = true; observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit vcpu=0x%x reinitialized=0x0", vcpu);
        goto out;
    }
    if (site >= SITE_COUNT || (packed & ~(LOW48_MAX | STUB_BIT | SITE4_BIT)) ||
        (stub && site != 0U) ||
        event_pc < (site == 1U ? 4U : 0U) ||
        !derive_base(event_pc - (site == 1U ? 4U : 0U), site, &base)) {
        observer.disabled = true; observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context packed_raw=0x%016" PRIx64 " vcpu=0x%x", packed, vcpu);
        goto out;
    }
    if ((site == 1U || site == 4U) && (!observer.candidate_found || base != observer.base)) {
        observer.disabled = true; observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context packed_raw=0x%016" PRIx64 " vcpu=0x%x", packed, vcpu);
        goto out;
    }
    /* Weak cached callbacks must survive discovery, without making a base claim. */
    if (!observer.candidate_found || base != observer.base) {
        increment(&observer.unbound[site]);
        goto out;
    }
    observer.anchor_seen_mask |= 1U << site;
    if (!observer.regs_ready) {
        observer.disabled = true; observer.stop = "registers_not_ready";
        fault("reason=registers_not_ready");
        goto out;
    }
    if (observer.records[site] == SITE_QUOTA) {
        increment(&observer.suppressed[site]);
        goto out;
    }
    for (size_t i = 0; i < sizeof(common) / sizeof(common[0]); ++i) {
        if (!read_exact(common[i], site, &values[common[i]])) { goto out; }
    }
    switch (values[REG_CPSR] & UINT64_C(0x1f)) {
    case 0: case 4: case 5: case 8: case 9: case 12: case 13: break;
    default:
        fault("reason=invalid_mode site=%s cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64,
              site_names[site], values[REG_CPSR], values[REG_CPSR] & UINT64_C(0x1f));
        goto out;
    }
    if (site == 0U) {
        for (size_t i = 0; i < sizeof(entry) / sizeof(entry[0]); ++i) {
            if (!read_exact(entry[i], site, &values[entry[i]])) { goto out; }
        }
        length = snprintf(detail, sizeof(detail),
            "x1_raw=0x%016" PRIx64 " x1_read_length=0x8 x1_api_ok=0x1 "
            "x2_raw=0x%016" PRIx64 " x2_read_length=0x8 x2_api_ok=0x1 "
            "x3_raw=0x%016" PRIx64 " x3_read_length=0x8 x3_api_ok=0x1 trigger_low32=0x%08" PRIx32,
            values[REG_X1],values[REG_X2],values[REG_X3],(uint32_t)values[REG_X1]);
    } else {
        for (size_t i = 0; i < sizeof(internal) / sizeof(internal[0]); ++i) {
            if (!read_exact(internal[i], site, &values[internal[i]])) { goto out; }
        }
        length = snprintf(detail, sizeof(detail),
            "x19_raw=0x%016" PRIx64 " x19_read_length=0x8 x19_api_ok=0x1 "
            "x22_raw=0x%016" PRIx64 " x22_read_length=0x8 x22_api_ok=0x1 "
            "x23_raw=0x%016" PRIx64 " x23_read_length=0x8 x23_api_ok=0x1 "
            "x29_raw=0x%016" PRIx64 " x29_read_length=0x8 x29_api_ok=0x1",
            values[REG_X19],values[REG_X22],values[REG_X23],values[REG_X29]);
    }
    if (length < 0 || (size_t)length >= sizeof(detail)) {
        errno = EINVAL; io_failure("detail_format"); goto out;
    }
    prediction[0] = '\0';
    if (site == 1U) {
        uint32_t w0 = (uint32_t)values[REG_X0];
        length = snprintf(prediction, sizeof(prediction),
            " loaded_w0=0x%08" PRIx32 " source_taken_prediction=0x%x "
            "source_next_pc=0x%016" PRIx64 " source_next_basis=w0_low32",
            w0, w0 != 0U ? 1U : 0U, base + (w0 != 0U ? event_offsets[2] : event_offsets[3]));
        if (length < 0 || (size_t)length >= sizeof(prediction)) {
            errno = EINVAL; io_failure("prediction_format"); goto out;
        }
    }
    if (!optional(REG_SP, site, "sp", options[0]) ||
        !optional(REG_TTBR0_EL1, site, "ttbr0_el1", options[1]) ||
        !optional(REG_TPIDR_EL0, site, "tpidr_el0", options[2])) { goto out; }
    if (record("shutter_gate",
        "site=%s vcpu=0x%x ordinal=0x%x gate_sequence=0x%x callback_phase=before_instruction "
        "event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64 " candidate_base=0x%016" PRIx64
        " anchor_length=0x%x entry_anchor=%s x0_raw=0x%016" PRIx64 " x30_raw=0x%016" PRIx64
        " cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64 " context_mode=%s "
        "nzcv=0x%08" PRIx64 " nzcv_mask=0xf0000000 %s %s %s "
        "gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 x0_read_length=0x8 x0_api_ok=0x1 "
        "x30_read_length=0x8 x30_api_ok=0x1 cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1 %s%s",
        site_names[site],vcpu,observer.records[site]+1U,observer.sequence+1U,
        event_pc,values[REG_PC],base,site == 0U && !stub ? 16U : 8U,
        site == 0U ? (stub ? "existing_main_stub8" : "original16") : "not_applicable",
        values[REG_X0],values[REG_X30],values[REG_CPSR],values[REG_CPSR] & UINT64_C(0x1f),
        (values[REG_CPSR] & UINT64_C(0x1f)) == 0 ? "EL0t" : "other_aarch64",
        values[REG_CPSR] & UINT64_C(0xf0000000),options[0],options[1],options[2],detail,prediction)) {
        ++observer.records[site]; ++observer.sequence;
    }
out:
    g_mutex_unlock(&observer.lock);
}

/* 0 means too short, -1 a complete unsupported window, 1 an exact window. */
static int match_window(struct qemu_plugin_tb *tb, size_t start, size_t count,
                        uint64_t pc, const unsigned char *bytes, size_t length)
{
    if (count - start < length / 4U) { return 0; }
    for (size_t j = 0; j < length / 4U; ++j) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, start + j);
        unsigned char local[4] = {0};
        if (qemu_plugin_insn_size(insn) != 4U || qemu_plugin_insn_vaddr(insn) != pc + 4U*j ||
            qemu_plugin_insn_data(insn, local, sizeof(local)) != sizeof(local) ||
            memcmp(local, bytes + 4U*j, sizeof(local)) != 0) { return -1; }
    }
    return 1;
}

static void tb_trans(struct qemu_plugin_tb *tb, void *userdata)
{
    size_t count = qemu_plugin_tb_n_insns(tb);
    uint64_t registered_pc[SITE_COUNT] = {0};
    (void)userdata;
    g_mutex_lock(&observer.lock);
    for (size_t i = 0; i < count && !observer.closed && !observer.disabled; ++i) {
        struct qemu_plugin_insn *first = qemu_plugin_tb_get_insn(tb, i);
        uint64_t pc = qemu_plugin_insn_vaddr(first);
        for (unsigned int site = 0; site < sizeof(anchors) / sizeof(anchors[0]); ++site) {
            uint64_t base, event_pc;
            size_t length = site == 0U ? 16U : 8U;
            bool stub = false;
            int matched;
            struct qemu_plugin_insn *tap;
            if (!derive_base(pc, site, &base)) { continue; }
            matched = match_window(tb, i, count, pc, anchors[site], length);
            if (site == 0U && matched != 1) {
                int stub_match = match_window(tb, i, count, pc, stub8, sizeof(stub8));
                if (stub_match == 1) { matched = 1; stub = true; }
                else if (matched == 0 && stub_match == -1 &&
                         match_window(tb, i, count, pc, anchors[site], (count-i)*4U) == -1) {
                    matched = -1;
                }
            }
            if (matched != 1) {
                if (matched == -1 && observer.candidate_found && base == observer.base) {
                    observer.disabled = true; observer.stop = "anchor_changed";
                    fault("reason=anchor_changed site=%s translated_pc=0x%016" PRIx64
                          " remaining_insns=0x%zx", site_names[site],pc,count-i);
                }
                continue;
            }
            if (site == 1U) {
                if (observer.candidate_found && observer.base != base) {
                    observer.ambiguous = true; observer.disabled = true;
                    observer.conflicting_base = base; observer.stop = "base_conflict";
                    fault("reason=base_conflict candidate_base=0x%016" PRIx64
                          " conflicting_base=0x%016" PRIx64,observer.base,base);
                    break;
                }
                observer.base = base; observer.candidate_found = true;
            }
            if (observer.candidate_found && observer.base == base) {
                observer.anchor_seen_mask |= site == 1U ? 0x12U : 1U << site;
            }
            if (site == 1U && registered_pc[4] != pc) {
                registered_pc[4] = pc;
                qemu_plugin_register_vcpu_insn_exec_cb(first,site_exec,QEMU_PLUGIN_CB_R_REGS,
                    (void *)(uintptr_t)(pc | SITE4_BIT));
            }
            tap = qemu_plugin_tb_get_insn(tb, i + (site == 1U ? 1U : 0U));
            event_pc = qemu_plugin_insn_vaddr(tap);
            if (registered_pc[site] == event_pc) { break; }
            registered_pc[site] = event_pc;
            qemu_plugin_register_vcpu_insn_exec_cb(tap,site_exec,QEMU_PLUGIN_CB_R_REGS,
                (void *)(uintptr_t)(event_pc | site | (stub ? STUB_BIT : 0U)));
            /* Distinct low12 anchors; the shared gate already registered both taps. */
            break;
        }
    }
    g_mutex_unlock(&observer.lock);
}

static void vcpu_init(unsigned int vcpu, void *userdata)
{
    GArray *descriptors;
    (void)userdata;
    g_mutex_lock(&observer.lock);
    if (observer.closed || observer.disabled) { goto out; }
    if (vcpu != 0U || observer.initialized) {
        observer.disabled = true; observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit vcpu=0x%x reinitialized=0x%x",vcpu,observer.initialized ? 1U : 0U);
        goto out;
    }
    observer.initialized = true;
    descriptors = qemu_plugin_get_registers();
    if (!descriptors || !descriptors->len || descriptors->len > MAX_DESCRIPTORS) {
        observer.disabled = true; observer.stop = "register_list";
        fault("reason=register_list descriptor_count=0x%x",descriptors ? descriptors->len : 0U);
    } else {
        for (guint i = 0; i < descriptors->len; ++i) {
            const qemu_plugin_reg_descriptor *d = &g_array_index(descriptors,qemu_plugin_reg_descriptor,i);
            for (size_t r = 0; r < REG_COUNT; ++r) {
                if (d->name && strcmp(d->name,reg_names[r]) == 0) {
                    if (observer.regs[r].found) {
                        observer.disabled = true; observer.stop = "duplicate_register";
                        fault("reason=duplicate_register reg=%s",reg_names[r]);
                    }
                    observer.regs[r] = (struct reg_ref){.handle=d->handle,.found=true};
                }
            }
        }
        for (size_t r = 0; r < REG_SP; ++r) {
            if (!observer.regs[r].found) {
                observer.disabled = true; observer.stop = "unknown_register";
                fault("reason=unknown_register reg=%s required_length=0x%x "
                      "read_attempted=0x0 read_length=0x0 api_ok=0x0",
                      reg_names[r], r == REG_CPSR ? 4U : 8U);
            }
        }
        observer.regs_ready = !observer.disabled;
    }
    if (descriptors) { g_array_unref(descriptors); }
out:
    g_mutex_unlock(&observer.lock);
}

static void plugin_exit(void *userdata)
{
    (void)userdata;
    g_mutex_lock(&observer.lock);
    if (!observer.closed) {
        (void)record("end", "stop=%s ambiguous=0x%x candidate_found=0x%x "
            "candidate_base=0x%016" PRIx64 " conflicting_base=0x%016" PRIx64 " anchor_seen_mask=0x%x "
            "site0_records=0x%x site1_records=0x%x site2_records=0x%x site3_records=0x%x site4_records=0x%x "
            "gate_sequence=0x%x site0_suppressed=0x%" PRIx64 " site1_suppressed=0x%" PRIx64
            " site2_suppressed=0x%" PRIx64 " site3_suppressed=0x%" PRIx64 " site4_suppressed=0x%" PRIx64
            " fault_lines=0x%x faults=0x%" PRIx64 " suppressed_faults=0x%" PRIx64
            " close_result=unknown site0_unbound_callbacks=0x%" PRIx64
            " site1_unbound_callbacks=0x%" PRIx64 " site2_unbound_callbacks=0x%" PRIx64
            " site3_unbound_callbacks=0x%" PRIx64 " site4_unbound_callbacks=0x%" PRIx64,
            observer.stop ? observer.stop : "none",observer.ambiguous ? 1U : 0U,
            observer.candidate_found ? 1U : 0U,observer.base,observer.conflicting_base,observer.anchor_seen_mask,
            observer.records[0],observer.records[1],observer.records[2],observer.records[3],observer.records[4],observer.sequence,
            observer.suppressed[0],observer.suppressed[1],observer.suppressed[2],observer.suppressed[3],observer.suppressed[4],
            observer.fault_lines,observer.faults,observer.suppressed_faults,
            observer.unbound[0],observer.unbound[1],observer.unbound[2],observer.unbound[3],observer.unbound[4]);
        observer.closed = true; observer.disabled = true;
        if (observer.log && fclose(observer.log) != 0) { io_failure("close"); }
        observer.log = NULL;
        if (observer.buffer) { g_byte_array_unref(observer.buffer); observer.buffer = NULL; }
    }
    g_mutex_unlock(&observer.lock);
}

QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info,
                                          int argc, char **argv)
{
    const char *reason = NULL;
    if (observer.install_called) {
        (void)fprintf(stderr,"scope_observer_host_error reason=duplicate_install\n"); return 1;
    }
    observer.install_called = true;
    if (argc != 1 || !argv || !argv[0] || strncmp(argv[0],"log=/",5) || strlen(argv[0]) > 4096U ||
        strchr(argv[0],'\r') || strchr(argv[0],'\n')) {
        (void)fprintf(stderr,"scope_observer_host_error reason=one_absolute_host_log_required\n"); return 1;
    }
    observer.log = fopen(argv[0]+4,"wx");
    if (!observer.log) { io_failure("exclusive_open"); return 1; }
    if (!record("begin", "schema=readonly_shutter_gate_v2 plugin_api=0x7 max_vcpus=0x1 sites=0x5 "
        "site_quota=0x10 fault_quota=0x20 register_byte_order=little "
        "identity_limit=raw_context_only_no_pid_tid_module_identity")) {
        plugin_exit(NULL); return 1;
    }
    if (!info || !info->target_name || strcmp(info->target_name,"aarch64")) {
        reason = "target_requires_aarch64_little_endian";
    } else if (info->version.min > 7 || info->version.cur < 7) { reason = "plugin_api_range";
    } else if (!info->system_emulation) { reason = "system_emulation_required";
    } else if (info->system.smp_vcpus != 1 || info->system.max_vcpus != 1) { reason = "single_vcpu_required"; }
    if (reason) {
        observer.disabled = true; observer.stop = reason; fault("reason=%s",reason);
        plugin_exit(NULL); return 1;
    }
    observer.buffer = g_byte_array_sized_new(8);
    qemu_plugin_register_vcpu_init_cb(id,vcpu_init,NULL);
    qemu_plugin_register_vcpu_tb_trans_cb(id,tb_trans,NULL);
    qemu_plugin_register_atexit_cb(id,plugin_exit,NULL);
    return 0;
}
