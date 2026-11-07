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
#define SITE_COUNT 3U
#define SITE_QUOTA 16U
#define FAULT_QUOTA 32U
#define MAX_DESCRIPTORS 4096U
#define LINE_LIMIT 2048U

static const char *const site_names[SITE_COUNT] = {"setter_entry", "store_pre", "ret_pre"};
static const unsigned char writer12[12] = {
    0xa1,0xb7,0x02,0xd0,0x20,0x70,0x05,0xb9,0xc0,0x03,0x5f,0xd6
};
#define ORIGIN_COUNT 3U
static const char *const origin_names[ORIGIN_COUNT] = {"dispatch_entry", "table_setter_entry", "upstream_entry"};
static const uint64_t origin_offsets[ORIGIN_COUNT] = {UINT64_C(0x2506220), UINT64_C(0x28bb120), UINT64_C(0x250646c)};
static const unsigned char dispatch36[36] = {
    0xfd,0x7b,0xbc,0xa9,0xfd,0x03,0x00,0x91,0xf3,0x53,0x01,0xa9,0xf3,0x03,0x00,0x2a,
    0xf5,0x5b,0x02,0xa9,0xf4,0x03,0x01,0x2a,0xf7,0x1b,0x00,0xf9,0xf5,0x03,0x05,0xaa,
    0x22,0x02,0x00,0x35
};
static const unsigned char table32[32] = {
    0x00,0x7c,0x40,0x93,0x03,0x06,0x80,0xd2,0x42,0x66,0x01,0xb0,0x42,0xe0,0x30,0x91,
    0x00,0x08,0x03,0x9b,0x02,0x0c,0x40,0xf9,0xe0,0x03,0x01,0x2a,0x40,0x00,0x1f,0xd6
};
static const unsigned char upstream32[32] = {0xfd,0x7b,0xbb,0xa9,0x7f,0x1c,0x00,0x72,0xfd,0x03,0x00,0x91,0xf5,0x5b,0x02,0xa9,0xf5,0x03,0x01,0x2a,0xf3,0x53,0x01,0xa9,0xe1,0x03,0x02,0x2a,0x00,0x03,0x00,0x54};
static const unsigned char *const origin_anchors[ORIGIN_COUNT] = {dispatch36, table32, upstream32};
static const size_t origin_lengths[ORIGIN_COUNT] = {sizeof(dispatch36), sizeof(table32), sizeof(upstream32)};
enum reg_index { REG_PC, REG_X0, REG_X1, REG_X30, REG_CPSR, REG_SP, REG_TTBR0_EL1, REG_TPIDR_EL0,
                 REG_X2, REG_X3, REG_X4, REG_X5, REG_X19, REG_X20, REG_X21, REG_COUNT };
static const char *const reg_names[REG_COUNT] = {"pc", "x0", "x1", "x30", "cpsr", "sp", "TTBR0_EL1", "TPIDR_EL0",
                                              "x2", "x3", "x4", "x5", "x19", "x20", "x21"};
struct reg_ref { struct qemu_plugin_register *handle; bool found; };
static struct {
    GMutex lock;
    FILE *log;
    GByteArray *buffer;
    struct reg_ref regs[REG_COUNT];
    uint64_t base, conflicting_base, faults, suppressed_faults;
    uint64_t suppressed[SITE_COUNT], unbound[SITE_COUNT];
    uint64_t origin_base, origin_suppressed[ORIGIN_COUNT], origin_skipped[ORIGIN_COUNT];
    unsigned int origin_records[ORIGIN_COUNT], origin_sequence, origin_anchor_mask, observation_sequence;
    unsigned int records[SITE_COUNT], sequence, fault_lines, anchor_seen_mask;
    uint64_t pointer_guard_base;unsigned int pointer_guard_mask;
    uint64_t pointer_base,pointer_suppressed[3],pointer_filtered[3];
    unsigned int pointer_records[3],pointer_sequence,pointer_anchor_mask;
    uint64_t descriptor_base,descriptor_suppressed[3];
    unsigned int descriptor_records[3],descriptor_sequence;
    bool descriptor_anchor_seen;
    uint64_t record_base, record_suppressed[3], record_skipped[3];
    unsigned int record_records[3], record_sequence;
    bool record_anchor_seen;
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

static bool derive_base(uint64_t pc, uint64_t *base)
{
    uint64_t b;
    if (pc < UINT64_C(0x2767978) || pc > LOW48_MAX - 11U) { return false; }
    b=pc-UINT64_C(0x2767978);
    if (!b || (b&UINT64_C(0xfff)) || b>LOW48_MAX-UINT64_C(0x7e5d577)) { return false; }
    *base=b;return true;
}

static bool read_exact(enum reg_index r, const char *site, uint64_t *value)
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
              site, reg_names[r], required, observer.buffer->len, ok ? 1U : 0U);
        return false;
    }
    *value = 0;
    for (size_t i = 0; i < required; ++i) {
        *value |= (uint64_t)observer.buffer->data[i] << (8U * i);
    }
    return true;
}

static bool optional(enum reg_index r, const char *site, const char *name, char out[192])
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

#include "pointer-taps.inc"
#include "descriptor-taps.inc"
#include "record-taps.inc"

static void site_exec(unsigned int vcpu, void *userdata)
{
    uint64_t packed = (uint64_t)(uintptr_t)userdata;
    unsigned int site = (unsigned int)(packed & UINT64_C(3));
    uint64_t event_pc = packed & LOW48_MAX & ~UINT64_C(3), base;
    uint64_t pc, x0, x1, lr, cpsr;
    char options[3][192];
    g_mutex_lock(&observer.lock);
    if (observer.closed || observer.disabled) { goto out; }
    if (vcpu != 0U) {
        observer.disabled = true; observer.stop = "vcpu_limit";
        fault("reason=vcpu_limit vcpu=0x%x reinitialized=0x0",vcpu); goto out;
    }
    if (site >= SITE_COUNT || packed & ~LOW48_MAX || event_pc < site * 4U ||
        !derive_base(event_pc - site * 4U, &base) || !observer.candidate_found || base != observer.base) {
        observer.disabled = true; observer.stop = "invalid_callback_context";
        fault("reason=invalid_callback_context packed_raw=0x%016" PRIx64,packed); goto out;
    }
    if (!observer.regs_ready) {
        observer.disabled = true; observer.stop = "registers_not_ready";
        fault("reason=registers_not_ready"); goto out;
    }
    if (observer.records[site] == SITE_QUOTA) { increment(&observer.suppressed[site]); goto out; }
    if (!read_exact(REG_PC,site_names[site],&pc) || !read_exact(REG_X0,site_names[site],&x0) ||
        !read_exact(REG_X1,site_names[site],&x1) || !read_exact(REG_X30,site_names[site],&lr) ||
        !read_exact(REG_CPSR,site_names[site],&cpsr)) { goto out; }
    switch (cpsr & UINT64_C(0x1f)) {
    case 0: case 4: case 5: case 8: case 9: case 12: case 13: break;
    default:
        fault("reason=invalid_mode site=%s cpsr_raw=0x%08" PRIx64,site_names[site],cpsr); goto out;
    }
    /* Store/RET taps require the ADRP result in X1; this is no memory readback. */
    if (site && x1 != base + UINT64_C(0x7e5d000)) {
        observer.disabled = true; observer.stop = "destination_base_mismatch";
        fault("reason=destination_base_mismatch site=%s x1_raw=0x%016" PRIx64
              " expected_x1=0x%016" PRIx64,site_names[site],x1,base+UINT64_C(0x7e5d000)); goto out;
    }
    if (!optional(REG_SP,site_names[site],"sp",options[0]) ||
        !optional(REG_TTBR0_EL1,site_names[site],"ttbr0_el1",options[1]) ||
        !optional(REG_TPIDR_EL0,site_names[site],"tpidr_el0",options[2])) { goto out; }
    if (record("shutter_writer",
        "site=%s vcpu=0x%x ordinal=0x%x writer_sequence=0x%x observation_sequence=0x%x callback_phase=before_instruction "
        "event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64 " candidate_base=0x%016" PRIx64
        " anchor_length=0xc x0_raw=0x%016" PRIx64 " input_w0=0x%08" PRIx32
        " x1_raw=0x%016" PRIx64 " x30_raw=0x%016" PRIx64 " cpsr_raw=0x%08" PRIx64
        " cpsr_m=0x%02" PRIx64 " context_mode=%s expected_destination=0x%016" PRIx64
        " destination_base_checked=0x%x gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 "
        "x0_read_length=0x8 x0_api_ok=0x1 x1_read_length=0x8 x1_api_ok=0x1 "
        "x30_read_length=0x8 x30_api_ok=0x1 cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1 "
        "%s %s %s store_retirement_verified=0x0 memory_readback_verified=0x0",
        site_names[site],vcpu,observer.records[site]+1U,observer.sequence+1U,observer.observation_sequence+1U,
        event_pc,pc,base,x0,(uint32_t)x0,x1,lr,cpsr,cpsr&UINT64_C(0x1f),
        (cpsr&UINT64_C(0x1f))==0U ? "EL0t" : "other_aarch64",
        base+UINT64_C(0x7e5d570),site ? 1U : 0U,options[0],options[1],options[2])) {
        ++observer.records[site]; ++observer.sequence; ++observer.observation_sequence;
        observer.anchor_seen_mask |= 1U << site;
    }
out:
    g_mutex_unlock(&observer.lock);
}

static bool origin_base(uint64_t pc, unsigned int site, uint64_t *base)
{
    uint64_t value;
    if (site >= ORIGIN_COUNT || pc < origin_offsets[site] || pc > LOW48_MAX - origin_lengths[site]) { return false; }
    value = pc - origin_offsets[site];
    if (!value || value & UINT64_C(0xfff) || value > LOW48_MAX - UINT64_C(0x7e5d577)) { return false; }
    *base = value;
    return true;
}

static void origin_exec(unsigned int vcpu, void *userdata)
{
    uint64_t packed = (uint64_t)(uintptr_t)userdata;
    unsigned int site = (unsigned int)(packed & UINT64_C(3));
    uint64_t pc = packed & LOW48_MAX & ~UINT64_C(3), base, x[6], gdb_pc, lr, cpsr;
    unsigned int selector_index = site == 2U ? 1U : 0U;
    char options[3][192];
    g_mutex_lock(&observer.lock);
    if (observer.closed || observer.disabled) { goto out; }
    if (vcpu != 0U || packed & ~LOW48_MAX || !origin_base(pc, site, &base) ||
        !(observer.origin_anchor_mask & (1U << site)) || base != observer.origin_base) {
        observer.disabled = true; observer.stop = "invalid_origin_context";
        fault("reason=invalid_origin_context packed_raw=0x%016" PRIx64, packed); goto out;
    }
    if (!observer.regs_ready || !read_exact(site == 2U ? REG_X1 : REG_X0, origin_names[site], &x[selector_index])) { goto out; }
    if ((uint32_t)x[selector_index] != UINT32_C(0x17c)) { increment(&observer.origin_skipped[site]); goto out; }
    if (observer.origin_records[site] == SITE_QUOTA) { increment(&observer.origin_suppressed[site]); goto out; }
    if (!read_exact(REG_PC, origin_names[site], &gdb_pc) ||
        !read_exact(site == 2U ? REG_X0 : REG_X1, origin_names[site], &x[site == 2U ? 0U : 1U]) ||
        !read_exact(REG_X2, origin_names[site], &x[2]) || !read_exact(REG_X3, origin_names[site], &x[3]) ||
        !read_exact(REG_X4, origin_names[site], &x[4]) || !read_exact(REG_X5, origin_names[site], &x[5]) ||
        !read_exact(REG_X30, origin_names[site], &lr) || !read_exact(REG_CPSR, origin_names[site], &cpsr)) { goto out; }
    switch (cpsr & UINT64_C(0x1f)) {
    case 0: case 4: case 5: case 8: case 9: case 12: case 13: break;
    default: fault("reason=invalid_origin_mode site=%s cpsr_raw=0x%08" PRIx64, origin_names[site], cpsr); goto out;
    }
    if (!optional(REG_SP, origin_names[site], "sp", options[0]) ||
        !optional(REG_TTBR0_EL1, origin_names[site], "ttbr0_el1", options[1]) ||
        !optional(REG_TPIDR_EL0, origin_names[site], "tpidr_el0", options[2])) { goto out; }
    if (record("writer_origin", "site=%s vcpu=0x0 ordinal=0x%x origin_sequence=0x%x observation_sequence=0x%x "
        "callback_phase=before_instruction event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64
        " candidate_base=0x%016" PRIx64 " anchor_length=0x%zx selector_u32=0x%08" PRIx32
        " x0_raw=0x%016" PRIx64 " x1_raw=0x%016" PRIx64 " x2_raw=0x%016" PRIx64
        " x3_raw=0x%016" PRIx64 " x4_raw=0x%016" PRIx64 " x5_raw=0x%016" PRIx64
        " x30_raw=0x%016" PRIx64 " cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64
        " context_mode=%s gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 "
        "x0_read_length=0x8 x0_api_ok=0x1 x1_read_length=0x8 x1_api_ok=0x1 "
        "x2_read_length=0x8 x2_api_ok=0x1 x3_read_length=0x8 x3_api_ok=0x1 "
        "x4_read_length=0x8 x4_api_ok=0x1 x5_read_length=0x8 x5_api_ok=0x1 "
        "x30_read_length=0x8 x30_api_ok=0x1 cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1 "
        "%s %s %s invocation_pairing_verified=0x0 store_retirement_verified=0x0 memory_readback_verified=0x0",
        origin_names[site], observer.origin_records[site] + 1U, observer.origin_sequence + 1U, observer.observation_sequence + 1U,
        pc, gdb_pc, base, origin_lengths[site], (uint32_t)x[selector_index], x[0], x[1], x[2], x[3], x[4], x[5], lr,
        cpsr, cpsr & UINT64_C(0x1f), (cpsr & UINT64_C(0x1f)) == 0U ? "EL0t" : "other_aarch64",
        options[0], options[1], options[2])) {
        ++observer.origin_records[site]; ++observer.origin_sequence; ++observer.observation_sequence;
    }
out:
    g_mutex_unlock(&observer.lock);
}

static int match_origin(struct qemu_plugin_tb *tb, size_t start, size_t count, uint64_t pc, unsigned int site)
{
    size_t words = origin_lengths[site] / 4U;
    if (count - start < words) { return 0; }
    for (size_t j = 0; j < words; ++j) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, start + j);
        unsigned char bytes[4] = {0};
        if (qemu_plugin_insn_size(insn) != 4U || qemu_plugin_insn_vaddr(insn) != pc + 4U * j ||
            qemu_plugin_insn_data(insn, bytes, sizeof(bytes)) != sizeof(bytes) ||
            memcmp(bytes, origin_anchors[site] + 4U * j, sizeof(bytes))) { return -1; }
    }
    return 1;
}

/* Each callback is registered only from a contiguous, exact full twelve-byte body. */
static int match_window(struct qemu_plugin_tb *tb, size_t start, size_t count, uint64_t pc)
{
    if (count - start < 3U) { return 0; }
    for (size_t j=0;j<3U;++j) {
        struct qemu_plugin_insn *insn=qemu_plugin_tb_get_insn(tb,start+j);
        unsigned char local[4]={0};
        if (qemu_plugin_insn_size(insn)!=4U || qemu_plugin_insn_vaddr(insn)!=pc+4U*j ||
            qemu_plugin_insn_data(insn,local,sizeof(local))!=sizeof(local) ||
            memcmp(local,writer12+4U*j,sizeof(local))) { return -1; }
    }
    return 1;
}

static void tb_trans(struct qemu_plugin_tb *tb, void *userdata)
{
    size_t count=qemu_plugin_tb_n_insns(tb);
    (void)userdata;
    g_mutex_lock(&observer.lock);
    for (size_t i=0;i<count && !observer.closed && !observer.disabled;++i) {
        struct qemu_plugin_insn *first=qemu_plugin_tb_get_insn(tb,i);
        uint64_t pc=qemu_plugin_insn_vaddr(first),base;
        int matched;
        pointer_generic_guard_translate(tb,i,pc);
        if(observer.disabled){break;}
        pointer_translate(tb,i,count,pc);
        if(observer.disabled){break;}
        descriptor_translate(tb,i,count,pc);
        if(observer.disabled){break;}
        record_translate(tb, i, count, pc);
        if (observer.disabled) { break; }
        for (unsigned int site = 0; site < ORIGIN_COUNT; ++site) {
            uint64_t derived;
            if (!origin_base(pc, site, &derived)) { continue; }
            matched = match_origin(tb, i, count, pc, site);
            if (matched != 1) {
                if (matched == -1 && observer.origin_base == derived && observer.origin_anchor_mask & (1U << site)) {
                    observer.disabled = true; observer.stop = "origin_anchor_changed";
                    fault("reason=origin_anchor_changed site=%s", origin_names[site]);
                }
                continue;
            }
            if ((observer.origin_base && observer.origin_base != derived) ||
                (observer.candidate_found && observer.base != derived) ||
                (observer.record_anchor_seen && observer.record_base != derived) ||
                (observer.descriptor_anchor_seen && observer.descriptor_base != derived) ||
                (observer.pointer_anchor_mask && observer.pointer_base != derived) ||
                (observer.pointer_guard_mask && observer.pointer_guard_base != derived)) {
                observer.ambiguous = true; observer.disabled = true; observer.stop = "origin_base_conflict";
                observer.conflicting_base = derived;
                fault("reason=origin_base_conflict translated_pc=0x%016" PRIx64, pc); break;
            }
            observer.origin_base = derived; observer.origin_anchor_mask |= 1U << site;
            qemu_plugin_register_vcpu_insn_exec_cb(first, origin_exec, QEMU_PLUGIN_CB_R_REGS,
                (void *)(uintptr_t)(pc + site));
        }
        if (observer.disabled || !derive_base(pc,&base)) { continue; }
        matched=match_window(tb,i,count,pc);
        if (matched!=1) {
            if (matched==-1 && observer.candidate_found && base==observer.base) {
                observer.disabled=true;observer.stop="anchor_changed";
                fault("reason=anchor_changed translated_pc=0x%016" PRIx64,pc);
            }
            continue;
        }
        if ((observer.candidate_found && observer.base!=base) ||
            (observer.origin_base && observer.origin_base != base) ||
            (observer.record_anchor_seen && observer.record_base != base) ||
            (observer.descriptor_anchor_seen && observer.descriptor_base != base) ||
                (observer.pointer_anchor_mask && observer.pointer_base != base) ||
                (observer.pointer_guard_mask && observer.pointer_guard_base != base)) {
            observer.ambiguous=true;observer.disabled=true;observer.stop="base_conflict";
            observer.conflicting_base=base;
            fault("reason=base_conflict candidate_base=0x%016" PRIx64
                  " conflicting_base=0x%016" PRIx64,observer.base,base);break;
        }
        observer.base=base;observer.candidate_found=true;
        for (unsigned int site=0;site<SITE_COUNT;++site) {
            struct qemu_plugin_insn *tap=qemu_plugin_tb_get_insn(tb,i+site);
            qemu_plugin_register_vcpu_insn_exec_cb(tap,site_exec,QEMU_PLUGIN_CB_R_REGS,
                (void *)(uintptr_t)(pc+site*4U+site));
        }
        i+=2U;
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
            "site0_records=0x%x site1_records=0x%x site2_records=0x%x writer_sequence=0x%x "
            "site0_suppressed=0x%" PRIx64 " site1_suppressed=0x%" PRIx64 " site2_suppressed=0x%" PRIx64
            " origin_base=0x%016" PRIx64 " origin_anchor_mask=0x%x origin_sequence=0x%x observation_sequence=0x%x "
            "origin0_records=0x%x origin1_records=0x%x origin2_records=0x%x origin0_suppressed=0x%" PRIx64
            " origin1_suppressed=0x%" PRIx64 " origin2_suppressed=0x%" PRIx64 " origin0_skipped=0x%" PRIx64 " origin1_skipped=0x%" PRIx64 " origin2_skipped=0x%" PRIx64
            " record_base=0x%016" PRIx64 " record_anchor_seen=0x%x record_sequence=0x%x "
            "record0_records=0x%x record1_records=0x%x record2_records=0x%x "
            "record0_skipped=0x%" PRIx64 " record1_skipped=0x%" PRIx64 " record2_skipped=0x%" PRIx64 " "
            "record0_suppressed=0x%" PRIx64 " record1_suppressed=0x%" PRIx64 " record2_suppressed=0x%" PRIx64
            " descriptor_base=0x%016" PRIx64 " descriptor_anchor_seen=0x%x descriptor_sequence=0x%x "
            "descriptor0_records=0x%x descriptor1_records=0x%x descriptor2_records=0x%x "
            "descriptor0_suppressed=0x%" PRIx64 " descriptor1_suppressed=0x%" PRIx64 " descriptor2_suppressed=0x%" PRIx64
            " pointer_guard_base=0x%016" PRIx64 " pointer_guard_mask=0x%x"
            " pointer_base=0x%016" PRIx64 " pointer_anchor_mask=0x%x pointer_sequence=0x%x "
            "pointer0_records=0x%x pointer1_records=0x%x pointer2_records=0x%x "
            "pointer0_suppressed=0x%" PRIx64 " pointer1_suppressed=0x%" PRIx64 " pointer2_suppressed=0x%" PRIx64
            " pointer0_filtered=0x%" PRIx64 " pointer1_filtered=0x%" PRIx64 " pointer2_filtered=0x%" PRIx64
            " fault_lines=0x%x faults=0x%" PRIx64 " suppressed_faults=0x%" PRIx64 " close_result=unknown",
            observer.stop ? observer.stop : "none",observer.ambiguous ? 1U : 0U,
            observer.candidate_found ? 1U : 0U,observer.base,observer.conflicting_base,observer.anchor_seen_mask,
            observer.records[0],observer.records[1],observer.records[2],observer.sequence,
            observer.suppressed[0],observer.suppressed[1],observer.suppressed[2],
            observer.origin_base, observer.origin_anchor_mask, observer.origin_sequence, observer.observation_sequence,
            observer.origin_records[0], observer.origin_records[1], observer.origin_records[2],
            observer.origin_suppressed[0], observer.origin_suppressed[1], observer.origin_suppressed[2],
            observer.origin_skipped[0], observer.origin_skipped[1], observer.origin_skipped[2],
            observer.record_base, observer.record_anchor_seen ? 1U : 0U, observer.record_sequence,
            observer.record_records[0], observer.record_records[1], observer.record_records[2],
            observer.record_skipped[0], observer.record_skipped[1], observer.record_skipped[2],
            observer.record_suppressed[0], observer.record_suppressed[1], observer.record_suppressed[2],
            observer.descriptor_base,observer.descriptor_anchor_seen?1U:0U,observer.descriptor_sequence,
            observer.descriptor_records[0],observer.descriptor_records[1],observer.descriptor_records[2],
            observer.descriptor_suppressed[0],observer.descriptor_suppressed[1],observer.descriptor_suppressed[2],
            observer.pointer_guard_base,observer.pointer_guard_mask,
            observer.pointer_base,observer.pointer_anchor_mask,observer.pointer_sequence,
            observer.pointer_records[0],observer.pointer_records[1],observer.pointer_records[2],
            observer.pointer_suppressed[0],observer.pointer_suppressed[1],observer.pointer_suppressed[2],
            observer.pointer_filtered[0],observer.pointer_filtered[1],observer.pointer_filtered[2],
            observer.fault_lines,observer.faults,observer.suppressed_faults);
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
    if (!record("begin", "schema=readonly_shutter_writer_v7 plugin_api=0x7 max_vcpus=0x1 sites=0x3 "
        "origin_sites=0x3 origin_selector=0x17c origin_quota=0x10 "
        "record_sites=0x3 record_row=0xa24 record_quota=0x10 "
        "descriptor_sites=0x3 descriptor_quota=0x10 "
        "pointer_sites=0x3 pointer_quota=0x10 "
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
