/* SPDX-License-Identifier: MIT */
/* Host-only draft: compile the actual plugin against the real QEMU header. */
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <qemu-plugin.h>

static bool fail_write;
static bool fail_flush;
static bool fail_close;
static size_t host_write(const void *data, size_t size, size_t count, FILE *stream);
static int host_flush(FILE *stream);
static int host_close(FILE *stream);
#define fwrite host_write
#define fflush host_flush
#define fclose host_close
#include "scope-observer.c"
#undef fwrite
#undef fflush
#undef fclose

struct qemu_plugin_insn {
    uint64_t pc;
    size_t size;
    size_t copied;
    unsigned char bytes[4];
    qemu_plugin_vcpu_udata_cb_t callback;
    enum qemu_plugin_cb_flags flags;
    void *userdata;
};
struct qemu_plugin_tb {
    size_t count;
    struct qemu_plugin_insn insns[10];
};
struct model_reg {
    uint64_t value;
    guint length;
    bool ok;
};
static struct model_reg model[REG_COUNT];
static struct qemu_plugin_register *handles[REG_COUNT];
static qemu_plugin_vcpu_udata_cb_t init_callback;
static qemu_plugin_vcpu_tb_trans_cb_t translate_callback;
static qemu_plugin_udata_cb_t exit_callback;
static void *init_data;
static void *translate_data;
static void *exit_data;
static enum qemu_plugin_cb_flags current_flags;
static unsigned int current_vcpu;
static unsigned int reads;
static unsigned int reg_reads[REG_COUNT];
static unsigned int instruction_reads;
static unsigned int registrations;
static unsigned int poweron_registrations;
static unsigned int producer_registrations;
static size_t longest_producer_body;
static size_t longest_producer_line;
static unsigned int live_arrays;
static unsigned int live_buffers;
static size_t missing = REG_COUNT;
static bool duplicate;
static bool tokens_absent;
static unsigned int register_list_mode;
static const uint64_t fixture_base = UINT64_C(0x0000005500000000);
static const uint64_t fixture_raw_x2 = UINT64_C(0xfedcba9801abc090);
static const uint64_t fixture_caller = UINT64_C(0xabcd005500abcdef);
static const unsigned char fixture_poweron[8] = {
    0x50, 0x00, 0x00, 0x58, 0x00, 0x02, 0x1f, 0xd6
};
static const unsigned char fixture_head[24] = {
    0xfd, 0x7b, 0xb9, 0xa9, 0x81, 0xd1, 0x02, 0xd0,
    0x21, 0xe0, 0x17, 0x91, 0xfd, 0x03, 0x00, 0x91,
    0xf7, 0x63, 0x03, 0xa9, 0xb7, 0x83, 0x01, 0x91
};

static const unsigned char fixture_producer[24] = {
    0x01, 0xb7, 0x02, 0xd0, 0x21, 0x60, 0x13, 0x91,
    0x21, 0x68, 0x40, 0x91, 0x20, 0xf0, 0x02, 0xb9,
    0x20, 0xf8, 0x02, 0xb9, 0xc0, 0x03, 0x5f, 0xd6
};

static size_t host_write(const void *data, size_t size, size_t count, FILE *stream)
{
    const char *line = data;
    assert(size == 1 && count > 0 && count < LINE_LIMIT && line[count - 1U] == '\n');
    if (strncmp(line, "kind=M_producer ", 16) == 0) {
        const char *body = strchr(line, ' ') + 1;
        const char *end = strstr(body, " status=native_unverified");
        assert(end && (size_t)(end - body) < 1536U);
        if ((size_t)(end - body) > longest_producer_body) {
            longest_producer_body = (size_t)(end - body);
        }
        if (count > longest_producer_line) { longest_producer_line = count; }
    }
    if (fail_write) {
        errno = ENOSPC;
        return 0;
    }
    return fwrite(data, size, count, stream);
}
static int host_flush(FILE *stream)
{
    if (fail_flush) {
        errno = EIO;
        return EOF;
    }
    return fflush(stream);
}
static int host_close(FILE *stream)
{
    int result = fclose(stream);
    if (fail_close) {
        errno = EIO;
        return EOF;
    }
    return result;
}

void g_mutex_lock(GMutex *mutex)
{
    assert(!mutex->locked);
    mutex->locked = true;
}
void g_mutex_unlock(GMutex *mutex)
{
    assert(mutex->locked);
    mutex->locked = false;
}
void g_array_unref(GArray *array)
{
    assert(array && live_arrays);
    free(array->data);
    free(array);
    --live_arrays;
}
GByteArray *g_byte_array_sized_new(guint reserved_size)
{
    GByteArray *array = calloc(1, sizeof(*array));
    assert(array);
    array->data = malloc(reserved_size);
    assert(array->data);
    memset(array->data, 0xa5, reserved_size);
    array->capacity = reserved_size;
    ++live_buffers;
    return array;
}
GByteArray *g_byte_array_set_size(GByteArray *array, guint length)
{
    if (length > array->capacity) {
        unsigned char *data = realloc(array->data, length);
        assert(data);
        array->data = data;
        array->capacity = length;
    }
    array->len = length;
    return array;
}
void g_byte_array_unref(GByteArray *array)
{
    assert(array && live_buffers);
    free(array->data);
    free(array);
    --live_buffers;
}

GArray *qemu_plugin_get_registers(void)
{
    GArray *array;
    qemu_plugin_reg_descriptor *descriptors;
    assert(current_vcpu == 0);
    if (register_list_mode == 1) {
        return NULL;
    }
    array = calloc(1, sizeof(*array));
    assert(array);
    ++live_arrays;
    if (register_list_mode == 2) {
        return array;
    }
    if (register_list_mode == 3) {
        array->len = MAX_DESCRIPTORS + 1U;
        return array;
    }
    descriptors = calloc(REG_COUNT + 1U, sizeof(*descriptors));
    assert(descriptors);
    array->data = (char *)(void *)descriptors;
    for (size_t r = 0; r < REG_COUNT; ++r) {
        if (r != missing && (!tokens_absent ||
            (r != REG_TTBR0_EL1 && r != REG_TPIDR_EL0))) {
            descriptors[array->len].name = reg_names[r];
            descriptors[array->len].handle = handles[r];
            ++array->len;
        }
    }
    if (duplicate) {
        descriptors[array->len] = (qemu_plugin_reg_descriptor){
            .name = "x23", .handle = handles[REG_X23]
        };
        ++array->len;
    }
    return array;
}

bool qemu_plugin_read_register(struct qemu_plugin_register *handle, GByteArray *buffer)
{
    size_t r;
    assert(current_vcpu == 0 && current_flags == QEMU_PLUGIN_CB_R_REGS);
    assert(buffer->len == 0 && buffer->capacity >= 8);
    for (size_t i = 0; i < 8; ++i) {
        assert(buffer->data[i] == 0);
    }
    for (r = 0; r < REG_COUNT && handles[r] != handle; ++r) {
        /* Resolve only opaque handles returned by this mock's register API. */
    }
    assert(r < REG_COUNT);
    ++reads;
    ++reg_reads[r];
    g_byte_array_set_size(buffer, model[r].length);
    for (size_t i = 0; i < buffer->len; ++i) {
        buffer->data[i] = i < 8 ? (unsigned char)(model[r].value >> (8U * i)) : 0;
    }
    return model[r].ok;
}

void qemu_plugin_register_vcpu_init_cb(qemu_plugin_id_t id,
    qemu_plugin_vcpu_udata_cb_t callback, void *userdata)
{
    assert(id == 1);
    init_callback = callback;
    init_data = userdata;
}
void qemu_plugin_register_vcpu_tb_trans_cb(qemu_plugin_id_t id,
    qemu_plugin_vcpu_tb_trans_cb_t callback, void *userdata)
{
    assert(id == 1);
    translate_callback = callback;
    translate_data = userdata;
}
void qemu_plugin_register_atexit_cb(qemu_plugin_id_t id,
    qemu_plugin_udata_cb_t callback, void *userdata)
{
    assert(id == 1);
    exit_callback = callback;
    exit_data = userdata;
}
size_t qemu_plugin_tb_n_insns(const struct qemu_plugin_tb *tb)
{
    return tb->count;
}
struct qemu_plugin_insn *qemu_plugin_tb_get_insn(const struct qemu_plugin_tb *tb,
    size_t index)
{
    assert(index < tb->count && index < 10);
    return (struct qemu_plugin_insn *)&tb->insns[index];
}
uint64_t qemu_plugin_insn_vaddr(const struct qemu_plugin_insn *insn)
{
    return insn->pc;
}
size_t qemu_plugin_insn_size(const struct qemu_plugin_insn *insn)
{
    return insn->size;
}
size_t qemu_plugin_insn_data(const struct qemu_plugin_insn *insn, void *dest,
    size_t length)
{
    assert(length == 4);
    ++instruction_reads;
    memcpy(dest, insn->bytes, insn->copied < 4U ? insn->copied : 4U);
    return insn->copied;
}
void qemu_plugin_register_vcpu_insn_exec_cb(struct qemu_plugin_insn *insn,
    qemu_plugin_vcpu_udata_cb_t callback, enum qemu_plugin_cb_flags flags,
    void *userdata)
{
    assert(flags == QEMU_PLUGIN_CB_R_REGS);
    if (callback == poweron_exec) {
        assert((uint64_t)(uintptr_t)userdata == insn->pc);
        ++poweron_registrations;
    } else if (callback == late_exec) {
        assert(((uintptr_t)userdata & ~(uintptr_t)3U) == insn->pc);
        assert(((uintptr_t)userdata & (uintptr_t)3U) < LATE_SITE_COUNT);
    } else if (callback == producer_exec) {
        assert(((uintptr_t)userdata & ~(uintptr_t)3U) == insn->pc);
        assert(((uintptr_t)userdata & (uintptr_t)3U) < 2U);
        ++producer_registrations;
    } else {
        assert(callback == entry_exec && userdata == &observer.candidate);
    }
    insn->callback = callback;
    insn->flags = flags;
    insn->userdata = userdata;
    ++registrations;
}

static void make_tb(struct qemu_plugin_tb *tb, uint64_t base, size_t prefix)
{
    assert(prefix <= 4);
    memset(tb, 0, sizeof(*tb));
    tb->count = prefix + 6U;
    for (size_t i = 0; i < tb->count; ++i) {
        tb->insns[i].pc = base + UINT64_C(0x2e068cc) - prefix * 4U + i * 4U;
        tb->insns[i].size = 4;
        tb->insns[i].copied = 4;
        if (i >= prefix) {
            memcpy(tb->insns[i].bytes, fixture_head + (i - prefix) * 4U, 4);
        }
    }
}
static void make_poweron_tb(struct qemu_plugin_tb *tb, uint64_t base, size_t prefix)
{
    assert(prefix <= 4);
    memset(tb, 0, sizeof(*tb));
    tb->count = prefix + 2U;
    for (size_t i = 0; i < tb->count; ++i) {
        tb->insns[i].pc = base + UINT64_C(0x1951844) - prefix * 4U + i * 4U;
        tb->insns[i].size = 4;
        tb->insns[i].copied = 4;
        if (i >= prefix) {
            memcpy(tb->insns[i].bytes, fixture_poweron + (i - prefix) * 4U, 4);
        }
    }
}
static void execute(struct qemu_plugin_insn *insn, uint64_t lr)
{
    struct model_reg before[REG_COUNT];
    assert(insn->callback);
    model[REG_X30].value = lr;
    memcpy(before, model, sizeof(before));
    current_flags = insn->flags;
    insn->callback(current_vcpu, insn->userdata);
    assert(memcmp(before, model, sizeof(before)) == 0);
}
static void execute_poweron(struct qemu_plugin_insn *insn, uint64_t raw, uint64_t caller)
{
    model[REG_PC].value = insn->pc;
    model[REG_X2].value = raw;
    execute(insn, caller);
}
static void finish(void)
{
    assert(exit_callback);
    exit_callback(exit_data);
    exit_callback(exit_data);
    assert(observer.closed && !observer.log && !observer.buffer);
    assert(!live_arrays && !live_buffers);
}
static void init_model(void)
{
    for (size_t r = 0; r < REG_COUNT; ++r) {
        model[r] = (struct model_reg){
            .value = UINT64_C(0xfedcba9800000000) | r,
            .length = r == REG_CPSR ? 4U : 8U, .ok = true
        };
        handles[r] = (struct qemu_plugin_register *)(uintptr_t)(r + 1U);
    }
    handles[REG_X0] = NULL;
    model[REG_PC].value = fixture_base + UINT64_C(0x2e068cc);
    model[REG_X0].value = UINT64_C(0x1122334455667788);
    model[REG_X23].value = UINT64_C(0xf123456789abcdef);
    model[REG_X24].value = UINT64_C(0x9988776655443322);
    model[REG_SP].value = UINT64_C(0x0000007ffffffd00);
    model[REG_CPSR].value = UINT64_C(0xa00003c0);
    model[REG_TTBR0_EL1].value = UINT64_C(0x1234005500456000);
    model[REG_TPIDR_EL0].value = UINT64_C(0xfedcba9876543210);
}

static void poweron_case(const char *scenario)
{
    struct qemu_plugin_tb poweron, scope;
    struct qemu_plugin_insn *dispatch;
    make_poweron_tb(&poweron, fixture_base, 0);
    make_tb(&scope, fixture_base, 2);
    dispatch = &poweron.insns[0];
    if (strcmp(scenario, "poweron_address") == 0) {
        uint64_t base = UINT64_C(0x123);
        assert(!derive_poweron_base(UINT64_C(0x844), &base));
        assert(!derive_poweron_base(POWERON_OFFSET, &base));
        assert(!derive_poweron_base(fixture_base + POWERON_OFFSET + 4U, &base));
        assert(!derive_poweron_base(UINT64_C(0x1000000000844), &base));
        assert(!derive_poweron_base(UINT64_C(0xffff005501951844), &base));
        assert(!derive_poweron_base(UINT64_C(0xff00005501951844), &base));
        assert(!derive_poweron_base(UINT64_MAX, &base));
        assert(base == UINT64_C(0x123));
        assert(derive_poweron_base(fixture_base + POWERON_OFFSET, &base));
        assert(base == fixture_base);
        assert(derive_poweron_base(UINT64_C(0x0000fffffffff844), &base));
        make_poweron_tb(&poweron, 0, 0);
        translate_callback(&poweron, translate_data);
        assert(!registrations && !reads && !observer.faults);
        return;
    }
    if (strcmp(scenario, "poweron_reject") == 0 ||
        strcmp(scenario, "poweron_noncandidate_after_bound") == 0) {
        bool bound = strcmp(scenario, "poweron_noncandidate_after_bound") == 0;
        if (bound) { translate_callback(&scope, translate_data); }
        for (size_t n = 0; n < 2; ++n) {
            make_poweron_tb(&poweron, fixture_base, 0);
            poweron.count = n;
            translate_callback(&poweron, translate_data);
        }
        for (size_t j = 0; j < 2; ++j) {
            make_poweron_tb(&poweron, fixture_base, 0);
            poweron.insns[j].size = j ? 8U : 2U;
            translate_callback(&poweron, translate_data);
            make_poweron_tb(&poweron, fixture_base, 0);
            poweron.insns[j].copied = 3;
            translate_callback(&poweron, translate_data);
            make_poweron_tb(&poweron, fixture_base, 0);
            poweron.insns[j].pc += 4U;
            translate_callback(&poweron, translate_data);
        }
        for (size_t j = 0; j < 8; ++j) {
            make_poweron_tb(&poweron, fixture_base, 0);
            poweron.insns[j / 4U].bytes[j % 4U] ^= 1U;
            translate_callback(&poweron, translate_data);
        }
        for (unsigned int i = 0; i < 100; ++i) {
            make_poweron_tb(&poweron, fixture_base + UINT64_C(0x100000), 0);
            poweron.insns[i % 2U].bytes[0] ^= 1U;
            translate_callback(&poweron, translate_data);
        }
        /* An isolated BR in another TB cannot supply the missing second word. */
        make_poweron_tb(&poweron, fixture_base, 0);
        poweron.insns[0] = poweron.insns[1];
        poweron.count = 1;
        translate_callback(&poweron, translate_data);
        assert(!poweron_registrations && !observer.disabled && !observer.faults);
        assert(!reads && registrations == (bound ? 1U : 0U));
        if (bound) {
            execute(&scope.insns[2], fixture_base + lr_offsets[0]);
            execute(&scope.insns[2], fixture_base + lr_offsets[1]);
            assert(observer.records[0] == 1 && observer.records[1] == 1);
        }
        return;
    }
    if (strcmp(scenario, "poweron_order_first") == 0 ||
        strcmp(scenario, "poweron_order_scope_first") == 0) {
        bool poweron_first = strcmp(scenario, "poweron_order_first") == 0;
        if (!poweron_first) {
            translate_callback(&scope, translate_data);
            execute(&scope.insns[2], fixture_base + lr_offsets[0]);
        }
        translate_callback(&poweron, translate_data);
        assert(poweron_registrations == 1);
        assert(observer.candidate_found == !poweron_first);
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        if (poweron_first) { translate_callback(&scope, translate_data); }
        model[REG_PC].value = scope.insns[2].pc;
        if (poweron_first) { execute(&scope.insns[2], fixture_base + lr_offsets[0]); }
        execute(&scope.insns[2], fixture_base + lr_offsets[1]);
        assert(observer.records[0] == 1 && observer.records[1] == 1);
        assert(observer.poweron_records == 1 && reg_reads[REG_X2] == 1);
        assert(!observer.faults);
        return;
    }
    if (strcmp(scenario, "poweron_after_scope_quotas") == 0) {
        translate_callback(&scope, translate_data);
        for (unsigned int i = 0; i < 40; ++i) {
            execute(&scope.insns[2], fixture_base + lr_offsets[i % 2U]);
        }
        assert(observer.records[0] == 16 && observer.records[1] == 16);
    }
    translate_callback(&poweron, translate_data);
    assert(dispatch->callback == poweron_exec && poweron_registrations == 1);
    if (strcmp(scenario, "poweron_exact8") == 0) {
        assert(instruction_reads == 2 && !observer.candidate_found);
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(reads == 7 && reg_reads[REG_CPSR] == 1);
    } else if (strcmp(scenario, "poweron_no_literal") == 0) {
        struct qemu_plugin_tb extra;
        make_poweron_tb(&extra, fixture_base, 2);
        extra.count += 1U;
        extra.insns[4].pc = extra.insns[2].pc + 8U;
        extra.insns[4].size = 4;
        extra.insns[4].copied = 0;
        translate_callback(&extra, translate_data);
        assert(instruction_reads == 4 && registrations == 2);
        execute_poweron(&extra.insns[2], fixture_raw_x2, fixture_caller);
    } else if (strcmp(scenario, "poweron_raw_filter") == 0) {
        static const uint32_t other[] = {0x01000091U, 0x00000090U, 0x02000090U, 0x01000010U};
        for (size_t r = 0; r < REG_COUNT; ++r) {
            if (r != REG_X2) { model[r].ok = false; model[r].length = 0; }
        }
        for (unsigned int i = 0; i < 100; ++i) {
            execute_poweron(dispatch, UINT64_C(0xfedcba9800000000) | other[i % 4U], fixture_caller);
        }
        assert(reads == 100 && reg_reads[REG_X2] == 100);
        assert(!observer.poweron_records && !observer.faults);
        init_model();
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
    } else if (strcmp(scenario, "poweron_quotas") == 0 ||
               strcmp(scenario, "poweron_fault_budget") == 0 ||
               strcmp(scenario, "poweron_after_scope_quotas") == 0) {
        bool fault_budget = strcmp(scenario, "poweron_fault_budget") == 0;
        bool scope_full = strcmp(scenario, "poweron_after_scope_quotas") == 0;
        if (!scope_full) { translate_callback(&scope, translate_data); }
        if (fault_budget) { model[REG_X2].length = 7; }
        for (unsigned int i = 0; i < (fault_budget ? 80U : 100U); ++i) {
            execute_poweron(dispatch, fault_budget ? fixture_raw_x2 : UINT64_MAX, fixture_caller);
        }
        assert(!observer.poweron_records);
        assert(observer.faults == (fault_budget ? 80U : 0U));
        model[REG_X2].length = 8;
        for (unsigned int i = 0; i < 20; ++i) {
            execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        }
        assert(observer.poweron_records == 16);
        unsigned int before_reads = reads;
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(reads == before_reads);
        unsigned int x2_reads = reg_reads[REG_X2];
        if (!scope_full) {
            assert(!observer.records[0] && !observer.records[1]);
            model[REG_PC].value = scope.insns[2].pc;
            for (unsigned int i = 0; i < 40; ++i) {
                execute(&scope.insns[2], fixture_base + lr_offsets[i % 2U]);
            }
        }
        assert(observer.records[0] == 16 && observer.records[1] == 16);
        assert(reg_reads[REG_X2] == x2_reads);
        assert(observer.fault_lines == (fault_budget ? 32U : 0U));
        assert(observer.suppressed_faults == (fault_budget ? 48U : 0U));
    } else if (strcmp(scenario, "poweron_multiple_bases") == 0 ||
               strcmp(scenario, "poweron_retranslation") == 0) {
        struct qemu_plugin_tb other;
        void *original_userdata = dispatch->userdata;
        translate_callback(&scope, translate_data);
        unsigned int repeats = strcmp(scenario, "poweron_retranslation") == 0 ? 1000U : 1U;
        for (unsigned int i = 0; i < repeats; ++i) {
            make_poweron_tb(&other, fixture_base + UINT64_C(0x100000), i % 4U);
            translate_callback(&other, translate_data);
            assert((uint64_t)(uintptr_t)other.insns[i % 4U].userdata ==
                   fixture_base + UINT64_C(0x100000) + POWERON_OFFSET);
        }
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        execute_poweron(&other.insns[(repeats - 1U) % 4U], fixture_raw_x2, fixture_caller);
        make_poweron_tb(&other, fixture_base, 0);
        other.insns[1].bytes[0] ^= 1U;
        translate_callback(&other, translate_data);
        assert(!other.insns[0].callback && dispatch->userdata == original_userdata);
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(observer.poweron_records == 3 && !observer.ambiguous && !observer.disabled);
        assert(!observer.faults && live_buffers == 1);
    } else if (strcmp(scenario, "poweron_x2_absent") == 0) {
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(!observer.poweron_records && observer.faults == 1 && !reads);
        translate_callback(&scope, translate_data);
        model[REG_PC].value = scope.insns[2].pc;
        execute(&scope.insns[2], fixture_base + lr_offsets[0]);
        execute(&scope.insns[2], fixture_base + lr_offsets[1]);
        assert(observer.records[0] == 1 && observer.records[1] == 1);
    } else if (strcmp(scenario, "poweron_tokens_absent") == 0) {
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(!reg_reads[REG_TTBR0_EL1] && !reg_reads[REG_TPIDR_EL0] && reads == 5);
    } else if (strncmp(scenario, "poweron_short_", 14) == 0 ||
               strncmp(scenario, "poweron_api_", 12) == 0 ||
               strcmp(scenario, "poweron_long_cpsr") == 0) {
        bool api = strncmp(scenario, "poweron_api_", 12) == 0;
        bool long_cpsr = strcmp(scenario, "poweron_long_cpsr") == 0;
        const char *name = long_cpsr ? "cpsr" : scenario + (api ? 12U : 14U);
        size_t r;
        for (r = 0; r < REG_COUNT && strcmp(name, reg_names[r]) != 0; ++r) {}
        assert(r < REG_COUNT);
        if (api) { model[r].ok = false; }
        else { model[r].length = long_cpsr ? 8U : model[r].length - 1U; }
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(!observer.poweron_records && observer.faults == 1);
        model[r].ok = true;
        model[r].length = r == REG_CPSR ? 4U : 8U;
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
    } else if (strcmp(scenario, "poweron_pc_mismatch") == 0 ||
               strcmp(scenario, "poweron_stale_pc") == 0) {
        model[REG_PC].value = strcmp(scenario, "poweron_stale_pc") == 0
            ? dispatch->pc - 4U : dispatch->pc + 4U;
        model[REG_X2].value = fixture_raw_x2;
        execute(dispatch, fixture_caller);
        assert(!observer.poweron_records && reads == 2 && observer.faults == 1);
    } else if (strcmp(scenario, "poweron_kernel_context") == 0 ||
               strcmp(scenario, "poweron_aarch32") == 0) {
        bool kernel = strcmp(scenario, "poweron_kernel_context") == 0;
        model[REG_CPSR].value |= kernel ? UINT64_C(0x5) : UINT64_C(0x10);
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(!observer.poweron_records && observer.faults == 1);
        if (kernel) {
            translate_callback(&scope, translate_data);
            model[REG_PC].value = scope.insns[2].pc;
            execute(&scope.insns[2], fixture_base + lr_offsets[0]);
            assert(observer.records[0] == 1);
        }
    } else if (strcmp(scenario, "poweron_vcpu_exec_limit") == 0) {
        current_vcpu = 1;
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(observer.disabled && !reads && !observer.poweron_records);
    } else {
        assert(strcmp(scenario, "poweron_write_failure") == 0 ||
               strcmp(scenario, "poweron_flush_failure") == 0);
        fail_write = strcmp(scenario, "poweron_write_failure") == 0;
        fail_flush = strcmp(scenario, "poweron_flush_failure") == 0;
        execute_poweron(dispatch, fixture_raw_x2, fixture_caller);
        assert(observer.io_failed && observer.disabled && !observer.poweron_records);
        fail_write = false;
        fail_flush = false;
        return;
    }
    if (strcmp(scenario, "poweron_pc_mismatch") != 0 &&
        strcmp(scenario, "poweron_stale_pc") != 0 &&
        strcmp(scenario, "poweron_kernel_context") != 0 &&
        strcmp(scenario, "poweron_aarch32") != 0 &&
        strcmp(scenario, "poweron_x2_absent") != 0 &&
        strcmp(scenario, "poweron_vcpu_exec_limit") != 0) {
        assert(observer.poweron_records >= 1);
    }
}

static void make_producer_tb(struct qemu_plugin_tb *tb, uint64_t base, size_t prefix)
{
    assert(prefix <= 4U);
    memset(tb, 0, sizeof(*tb));
    tb->count = prefix + 6U;
    for (size_t i = 0; i < tb->count; ++i) {
        tb->insns[i].pc = base + UINT64_C(0x276e710) - prefix * 4U + i * 4U;
        tb->insns[i].size = 4;
        tb->insns[i].copied = 4;
        if (i >= prefix) {
            memcpy(tb->insns[i].bytes, fixture_producer + (i - prefix) * 4U, 4);
        }
    }
}

static void execute_producer(struct qemu_plugin_insn *insn, uint64_t x0)
{
    model[REG_X0].value = x0;
    /* Preserve a lazy GDB PC and a full64 caller unrelated to the scope LRs. */
    execute(insn, fixture_caller);
}

static void producer_case(const char *scenario)
{
    struct qemu_plugin_tb producer, scope;
    struct qemu_plugin_insn *sites[2];
    make_producer_tb(&producer, fixture_base, 2);
    make_tb(&scope, fixture_base, 0);
    sites[0] = &producer.insns[2];
    sites[1] = &producer.insns[5];
    model[REG_X1].value = fixture_base + UINT64_C(0x7e6a4d8);
    assert(observer.regs[REG_X0].found && observer.regs[REG_X0].handle == NULL);
    if (strcmp(scenario, "producer_address") == 0) {
        uint64_t base = 123;
        static const uint64_t rejected[] = {
            0x710, 0x276e710, 0xffff00550276e710, 0xff0000550276e710,
            0x0000fffffffff710, UINT64_MAX
        };
        for (size_t i = 0; i < sizeof(rejected) / sizeof(rejected[0]); ++i) {
            assert(!derive_producer_base(rejected[i], &base) && base == 123);
        }
        assert(!derive_producer_base(fixture_base + PRODUCER_OFFSET + 4U, &base));
        assert(derive_producer_base(fixture_base + PRODUCER_OFFSET, &base));
        assert(base == fixture_base);
        base = (LOW48_MAX - (M_OFFSET + 11U)) & ~UINT64_C(0xfff);
        uint64_t highest = base;
        assert(derive_producer_base(highest + PRODUCER_OFFSET, &base) && base == highest);
        make_producer_tb(&producer, 0, 0);
        translate_callback(&producer, translate_data);
        assert(!registrations && !reads && !observer.faults);
        return;
    }
    if (strcmp(scenario, "producer_reject") == 0 ||
        strcmp(scenario, "producer_collisions_after_bound") == 0) {
        bool bound = strcmp(scenario, "producer_collisions_after_bound") == 0;
        struct qemu_plugin_tb tb;
        if (bound) {
            translate_callback(&producer, translate_data);
            translate_callback(&scope, translate_data);
        }
        uint64_t base = fixture_base + (bound ? UINT64_C(0x100000) : 0);
        unsigned int before = registrations;
        for (size_t n = 0; n < 6U; ++n) {
            make_producer_tb(&tb, base, 0);
            tb.count = n;
            translate_callback(&tb, translate_data);
        }
        for (size_t j = 0; j < 6U; ++j) {
            make_producer_tb(&tb, base, 0);
            tb.insns[j].size = j % 2U ? 2U : 8U;
            translate_callback(&tb, translate_data);
            make_producer_tb(&tb, base, 0);
            tb.insns[j].copied = 3;
            translate_callback(&tb, translate_data);
            make_producer_tb(&tb, base, 0);
            tb.insns[j].copied = 5;
            translate_callback(&tb, translate_data);
            make_producer_tb(&tb, base, 0);
            tb.insns[j].pc += 4U;
            translate_callback(&tb, translate_data);
        }
        for (size_t j = 0; j < 24U; ++j) {
            make_producer_tb(&tb, base, 0);
            tb.insns[j / 4U].bytes[j % 4U] ^= 1U;
            translate_callback(&tb, translate_data);
        }
        assert(registrations == before && !reads && !observer.faults && !observer.disabled);
        assert(observer.producer_anchor_found == bound);
        if (bound) { execute_producer(sites[0], UINT64_C(0xfeedface80000001)); }
        return;
    }
    if (strcmp(scenario, "producer_cross_tb") == 0) {
        struct qemu_plugin_tb first, tail;
        for (size_t split = 1; split < 6U; ++split) {
            make_producer_tb(&first, fixture_base, 0);
            make_producer_tb(&tail, fixture_base, 0);
            first.count = split;
            memmove(tail.insns, tail.insns + split, (6U - split) * sizeof(tail.insns[0]));
            tail.count = 6U - split;
            translate_callback(&first, translate_data);
            translate_callback(&tail, translate_data);
        }
        assert(!registrations && !reads && !observer.faults && !observer.producer_anchor_found);
        return;
    }
    if (strcmp(scenario, "producer_after_scope_conflict") == 0) {
        translate_callback(&scope, translate_data);
        make_producer_tb(&producer, fixture_base + UINT64_C(0x100000), 2);
        translate_callback(&producer, translate_data);
        assert(observer.disabled && observer.ambiguous && !producer_registrations && !reads);
        assert(observer.producer.base == fixture_base + UINT64_C(0x100000));
        assert(observer.producer_conflicting_base == fixture_base);
        return;
    }
    if (strcmp(scenario, "producer_exact") == 0 ||
        strcmp(scenario, "producer_longest") == 0 ||
        strcmp(scenario, "producer_second_base_after_scope") == 0) {
        translate_callback(&scope, translate_data);
    }
    translate_callback(&producer, translate_data);
    assert(producer_registrations == 2U);
    assert(sites[0]->callback == producer_exec && sites[1]->callback == producer_exec);
    for (size_t i = 0; i < producer.count; ++i) {
        assert((producer.insns[i].callback != NULL) == (i == 2U || i == 5U));
    }
    assert(observer.producer_anchor_found && observer.producer.base == fixture_base);
    if (strcmp(scenario, "producer_anchor_only") == 0) {
        assert(!reads && !observer.candidate_found && !observer.producer_sequence);
    } else if (strcmp(scenario, "producer_early") == 0) {
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
        assert(!observer.candidate_found && observer.producer_sequence == 2U);
        translate_callback(&scope, translate_data);
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
        assert(observer.producer_sequence == 4U && !observer.ambiguous);
    } else if (strcmp(scenario, "producer_scope_conflict") == 0 ||
               strcmp(scenario, "producer_second_base_before_scope") == 0 ||
               strcmp(scenario, "producer_second_base_after_scope") == 0) {
        struct qemu_plugin_tb other;
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        if (strcmp(scenario, "producer_scope_conflict") == 0) {
            make_tb(&other, fixture_base + UINT64_C(0x100000), 0);
        } else {
            make_producer_tb(&other, fixture_base + UINT64_C(0x100000), 0);
        }
        translate_callback(&other, translate_data);
        assert(observer.disabled && observer.ambiguous && observer.faults == 1U);
        unsigned int before = reads;
        execute_producer(sites[1], 1);
        translate_callback(&producer, translate_data);
        assert(reads == before && observer.producer_sequence == 1U);
    } else if (strcmp(scenario, "producer_scope_anchor_changed") == 0 ||
               strcmp(scenario, "producer_second_scope") == 0) {
        struct qemu_plugin_tb changed;
        bool second = strcmp(scenario, "producer_second_scope") == 0;
        translate_callback(&scope, translate_data);
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        make_tb(&changed, fixture_base + (second ? UINT64_C(0x100000) : 0), 0);
        if (!second) { changed.insns[5].bytes[0] ^= 1U; }
        translate_callback(&changed, translate_data);
        assert(observer.disabled && observer.faults == 1U);
        assert(strcmp(observer.stop, second ? "ambiguous_base" : "anchor_changed") == 0);
        unsigned int before = reads;
        execute_producer(sites[1], 1);
        assert(reads == before && observer.producer_sequence == 1U);
    } else if (strncmp(scenario, "producer_changed_", 17) == 0) {
        struct qemu_plugin_tb changed;
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        make_producer_tb(&changed, fixture_base, 0);
        const char *cause = scenario + 17;
        if (strcmp(cause, "partial") == 0) { changed.count = 5; }
        else if (strcmp(cause, "shape") == 0) { changed.insns[3].size = 8; }
        else if (strcmp(cause, "short") == 0) { changed.insns[2].copied = 3; }
        else if (strcmp(cause, "noncontinuous") == 0) { changed.insns[4].pc += 4U; }
        else {
            assert(strcmp(cause, "second_store") == 0 || strcmp(cause, "ret") == 0);
            changed.insns[strcmp(cause, "ret") == 0 ? 5U : 4U].bytes[0] ^= 1U;
        }
        translate_callback(&changed, translate_data);
        assert(observer.disabled && strcmp(observer.stop, "producer_anchor_changed") == 0);
        unsigned int before = reads;
        execute_producer(sites[1], 1);
        assert(reads == before && observer.producer_sequence == 1U);
    } else if (strcmp(scenario, "producer_retranslation") == 0) {
        struct qemu_plugin_tb other;
        void *saved[2] = {sites[0]->userdata, sites[1]->userdata};
        for (unsigned int i = 0; i < 1000U; ++i) {
            make_producer_tb(&other, fixture_base, i % 4U);
            translate_callback(&other, translate_data);
        }
        assert(!observer.candidate_found && !observer.faults && live_buffers == 1U);
        for (size_t s = 0; s < 2U; ++s) { assert(sites[s]->userdata == saved[s]); }
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
    } else if (strcmp(scenario, "producer_x1_absent") == 0) {
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        execute_producer(sites[1], 1);
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        assert(observer.producer_records[0] == 2U && !observer.producer_records[1]);
        assert(!reg_reads[REG_X1] && observer.faults == 1U && !observer.disabled);
    } else if (strncmp(scenario, "producer_entry_", 15) == 0 ||
               strncmp(scenario, "producer_pre_", 13) == 0) {
        bool entry = strncmp(scenario, "producer_entry_", 15) == 0;
        const char *detail = scenario + (entry ? 15U : 13U);
        const char *name = strchr(detail, '_');
        assert(name);
        ++name;
        bool api = strncmp(detail, "api_", 4) == 0;
        bool api_short = strncmp(detail, "false7_", 7) == 0;
        bool longer = strncmp(detail, "long_", 5) == 0;
        size_t r;
        for (r = 0; r < REG_COUNT && strcmp(reg_names[r], name) != 0; ++r) {}
        assert(r < REG_COUNT);
        if (api || api_short) { model[r].ok = false; }
        if (!api) {
            model[r].length = longer ? (r == REG_CPSR ? 8U : 9U) : model[r].length - 1U;
        }
        execute_producer(sites[entry ? 0U : 1U], UINT64_C(0xfeedface80000001));
        assert(observer.faults == 1U && !observer.producer_sequence);
        model[r].ok = true;
        model[r].length = r == REG_CPSR ? 4U : 8U;
        execute_producer(sites[entry ? 0U : 1U], UINT64_C(0xfeedface80000001));
        assert(observer.producer_sequence == 1U);
    } else if (strcmp(scenario, "producer_bad_destination") == 0 ||
               strcmp(scenario, "producer_destination_overflow") == 0) {
        model[REG_X1].value = strcmp(scenario, "producer_destination_overflow") == 0
            ? UINT64_MAX : model[REG_X1].value + 4U;
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
        assert(observer.faults == 1U && !observer.producer_sequence);
        model[REG_X1].value = fixture_base + UINT64_C(0x7e6a4d8);
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
        assert(observer.producer_records[1] == 1U);
    } else if (strcmp(scenario, "producer_aarch32") == 0 ||
               strcmp(scenario, "producer_reserved") == 0) {
        model[REG_CPSR].value |= strcmp(scenario, "producer_aarch32") == 0 ? 0x10U : 2U;
        execute_producer(sites[0], 1);
        execute_producer(sites[1], 1);
        assert(observer.faults == 2U && !observer.producer_sequence);
        model[REG_CPSR].value = UINT64_C(0xa00003c0);
        execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
    } else if (strcmp(scenario, "producer_modes") == 0) {
        static const unsigned int modes[] = {0, 4, 5, 8, 9, 12, 13};
        for (size_t i = 0; i < sizeof(modes) / sizeof(modes[0]); ++i) {
            model[REG_CPSR].value = UINT64_C(0xf00003c0) | modes[i];
            execute_producer(sites[0], UINT64_C(0xfeedface00000000) | i);
            execute_producer(sites[1], UINT64_C(0x11223344ffffffff) - i);
        }
        assert(observer.producer_sequence == 14U && !observer.faults);
    } else if (strcmp(scenario, "producer_vcpu") == 0 ||
               strcmp(scenario, "producer_invalid_metadata") == 0) {
        if (strcmp(scenario, "producer_vcpu") == 0) { current_vcpu = 1; }
        else { sites[0]->userdata = (void *)(uintptr_t)(sites[0]->pc | 3U); }
        execute_producer(sites[0], 1);
        assert(observer.disabled && !reads && !observer.producer_sequence);
        current_vcpu = 0;
    } else if (strcmp(scenario, "producer_write_failure") == 0 ||
               strcmp(scenario, "producer_flush_failure") == 0) {
        fail_write = strcmp(scenario, "producer_write_failure") == 0;
        fail_flush = strcmp(scenario, "producer_flush_failure") == 0;
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
        assert(observer.io_failed && observer.disabled && !observer.producer_sequence);
        assert(!observer.producer_records[0] && !observer.producer_records[1]);
        unsigned int before = reads;
        execute_producer(sites[0], 1);
        assert(reads == before);
        fail_write = false;
        fail_flush = false;
    } else if (strcmp(scenario, "producer_limits") == 0 ||
               strcmp(scenario, "producer_longest") == 0) {
        bool limits = strcmp(scenario, "producer_limits") == 0;
        if (limits) {
            model[REG_X0].length = 7;
            for (unsigned int i = 0; i < 80U; ++i) {
                execute_producer(sites[i % 2U], 1);
            }
            assert(observer.fault_lines == 32U && observer.suppressed_faults == 48U);
            assert(!observer.producer_sequence);
            model[REG_X0].length = 8;
        } else {
            model[REG_CPSR].value = UINT64_C(0xf00003cd);
        }
        for (size_t s = 0; s < 2U; ++s) {
            for (unsigned int n = 0; n < 17U; ++n) {
                execute_producer(sites[s], s ? UINT64_C(0x11223344cafebabe)
                                            : UINT64_C(0xfeedface80000001));
            }
            assert(observer.producer_records[s] == 16U);
        }
        assert(observer.producer_sequence == 32U);
        unsigned int before = reads;
        execute_producer(sites[0], 1);
        execute_producer(sites[1], 1);
        assert(reads == before);
        if (limits) {
            struct qemu_plugin_tb poweron, late[2];
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
            for (size_t w = 0; w < 2U; ++w) {
                memset(&late[w], 0, sizeof(late[w]));
                late[w].count = 3;
                for (size_t j = 0; j < 3U; ++j) {
                    late[w].insns[j].pc = fixture_base + late_windows[w].offset + j * 4U;
                    late[w].insns[j].size = 4;
                    late[w].insns[j].copied = 4;
                    memcpy(late[w].insns[j].bytes, late_windows[w].bytes + j * 4U, 4);
                }
                translate_callback(&late[w], translate_data);
                for (size_t j = w ? 2U : 1U; j < 3U; ++j) {
                    for (unsigned int n = 0; n < 17U; ++n) {
                        execute(&late[w].insns[j], fixture_caller);
                    }
                }
            }
            assert(observer.records[0] == 16U && observer.records[1] == 16U);
            assert(observer.poweron_records == 16U && late_sequence == 48U);
            assert(observer.fault_lines == 32U && observer.suppressed_faults == 48U);
        } else {
            assert(longest_producer_body == 1044U && longest_producer_line == 1168U);
        }
    } else {
        assert(strcmp(scenario, "producer_exact") == 0 ||
               strcmp(scenario, "producer_optional_absent") == 0 ||
               strcmp(scenario, "producer_prestore_only") == 0);
        if (strcmp(scenario, "producer_prestore_only") != 0) {
            execute_producer(sites[0], UINT64_C(0xfeedface80000001));
        }
        assert(!reg_reads[REG_X1]);
        execute_producer(sites[1], UINT64_C(0x11223344cafebabe));
        assert(observer.producer_records[1] == 1U && reg_reads[REG_X1] == 1U);
        assert(!reg_reads[REG_X19] && !reg_reads[REG_X2] && !observer.faults);
        if (strcmp(scenario, "producer_optional_absent") == 0) {
            assert(!reg_reads[REG_SP] && !reg_reads[REG_TTBR0_EL1] && !reg_reads[REG_TPIDR_EL0]);
            assert(reads == 9U);
        } else {
            assert(reads == (strcmp(scenario, "producer_prestore_only") == 0 ? 8U : 15U));
        }
    }
}

int main(int argc, char **argv)
{
    char log_argument[8192];
    char *options[] = {log_argument};
    qemu_info_t info = {
        .target_name = "aarch64", .version = {.min = 7, .cur = 7},
        .system_emulation = true, .system = {.smp_vcpus = 1, .max_vcpus = 1}
    };
    struct qemu_plugin_tb tb;
    struct qemu_plugin_insn *entry;
    const char *scenario;
    int length;
    assert(argc == 3);
    scenario = argv[1];
    length = snprintf(log_argument, sizeof(log_argument), "log=%s", argv[2]);
    assert(length > 0 && (size_t)length < sizeof(log_argument));
    assert(memcmp(fixture_head, head24, sizeof(head24)) == 0);
    assert(memcmp(fixture_poweron, poweron_head8, sizeof(poweron_head8)) == 0);
    assert(memcmp(fixture_producer, producer_head24, sizeof(producer_head24)) == 0);
    init_model();
    if (strcmp(scenario, "badarg") == 0) {
        assert(qemu_plugin_install(1, &info, 0, NULL) != 0);
        return 0;
    }
    if (strcmp(scenario, "target") == 0) { info.target_name = "aarch64_be"; }
    if (strcmp(scenario, "user_mode") == 0) { info.system_emulation = false; }
    if (strcmp(scenario, "version") == 0) { info.version.cur = 6; }
    if (strcmp(scenario, "version_min") == 0) { info.version.min = 8; }
    if (strcmp(scenario, "smp") == 0) { info.system.smp_vcpus = 2; }
    if (strcmp(scenario, "max_vcpus") == 0) { info.system.max_vcpus = 2; }
    if (strcmp(scenario, "exclusive") == 0 || strcmp(scenario, "target") == 0 ||
        strcmp(scenario, "user_mode") == 0 || strcmp(scenario, "version") == 0 ||
        strcmp(scenario, "version_min") == 0 || strcmp(scenario, "smp") == 0 ||
        strcmp(scenario, "max_vcpus") == 0) {
        assert(qemu_plugin_install(1, &info, 1, options) != 0);
        assert(!init_callback && !translate_callback && !exit_callback);
        assert(!live_arrays && !live_buffers);
        return 0;
    }
    assert(qemu_plugin_install(1, &info, 1, options) == 0);
    assert(qemu_plugin_version == 7);
    assert(init_callback && translate_callback && exit_callback);
    if (strcmp(scenario, "unknown") == 0) { missing = REG_X23; }
    if (strcmp(scenario, "sp_absent") == 0) { missing = REG_SP; }
    if (strcmp(scenario, "tokens_absent") == 0 ||
        strcmp(scenario, "poweron_tokens_absent") == 0) { tokens_absent = true; }
    if (strcmp(scenario, "poweron_x2_absent") == 0) { missing = REG_X2; }
    if (strcmp(scenario, "producer_optional_absent") == 0) {
        missing = REG_SP;
        tokens_absent = true;
    }
    if (strcmp(scenario, "producer_x1_absent") == 0) { missing = REG_X1; }
    if (strncmp(scenario, "producer_missing_", 17) == 0) {
        const char *name = scenario + 17;
        for (missing = 0; missing < REG_COUNT && strcmp(reg_names[missing], name) != 0; ++missing) {}
        assert(missing < REG_SP);
    }
    if (strcmp(scenario, "duplicate") == 0) { duplicate = true; }
    if (strcmp(scenario, "null_regs") == 0) { register_list_mode = 1; }
    if (strcmp(scenario, "empty_regs") == 0) { register_list_mode = 2; }
    if (strcmp(scenario, "many_regs") == 0) { register_list_mode = 3; }
    init_callback(strcmp(scenario, "vcpu_init_limit") == 0 ? 1U : 0U, init_data);
    if (strcmp(scenario, "vcpu_reinit") == 0) { init_callback(0, init_data); }
    make_tb(&tb, fixture_base, 2);
    if (observer.disabled || !observer.regs_ready) {
        translate_callback(&tb, translate_data);
        assert(observer.disabled && registrations == 0 && reads == 0);
        finish();
        return 0;
    }
    if (strncmp(scenario, "producer_", 9) == 0) {
        producer_case(scenario);
        finish();
        return 0;
    }
    if (strncmp(scenario, "poweron_", 8) == 0) {
        poweron_case(scenario);
        finish();
        return 0;
    }
    if (strcmp(scenario, "address") == 0) {
        uint64_t base = UINT64_C(0x123);
        assert(!derive_base(UINT64_C(0x8cc), &base));
        assert(!derive_base(CALLEE_OFFSET, &base));
        assert(!derive_base(fixture_base + CALLEE_OFFSET + 4U, &base));
        assert(!derive_base(UINT64_C(0x10000000008cc), &base));
        assert(!derive_base(UINT64_C(0xffff005502e068cc), &base));
        assert(!derive_base(UINT64_C(0xff00005502e068cc), &base));
        assert(!derive_base(UINT64_MAX, &base));
        assert(base == UINT64_C(0x123));
        assert(derive_base(fixture_base + CALLEE_OFFSET, &base));
        assert(base == fixture_base);
        assert(derive_base(UINT64_C(0x0000fffffffff8cc), &base));
        make_tb(&tb, 0, 0);
        translate_callback(&tb, translate_data);
        assert(registrations == 0 && observer.faults == 0);
        finish();
        return 0;
    }
    if (strcmp(scenario, "anchor_reject") == 0) {
        for (size_t n = 0; n < 6; ++n) {
            make_tb(&tb, fixture_base, 0);
            tb.count = n;
            translate_callback(&tb, translate_data);
        }
        for (size_t j = 0; j < 6; ++j) {
            make_tb(&tb, fixture_base, 0);
            tb.insns[j].size = j % 2U ? 2U : 8U;
            translate_callback(&tb, translate_data);
            make_tb(&tb, fixture_base, 0);
            tb.insns[j].copied = 3;
            translate_callback(&tb, translate_data);
            make_tb(&tb, fixture_base, 0);
            tb.insns[j].pc += 4;
            translate_callback(&tb, translate_data);
        }
        for (size_t j = 0; j < 24; ++j) {
            make_tb(&tb, fixture_base, 0);
            tb.insns[j / 4U].bytes[j % 4U] ^= 1U;
            translate_callback(&tb, translate_data);
        }
        assert(registrations == 0 && !observer.candidate_found && reads == 0);
        assert(observer.faults == 0 && observer.fault_lines == 0);
        finish();
        return 0;
    }
    if (strcmp(scenario, "cross_tb") == 0) {
        struct qemu_plugin_tb tail;
        make_tb(&tb, fixture_base, 0);
        make_tb(&tail, fixture_base, 0);
        tb.count = 3;
        memcpy(tail.insns, tail.insns + 3, 3U * sizeof(tail.insns[0]));
        tail.count = 3;
        translate_callback(&tb, translate_data);
        translate_callback(&tail, translate_data);
        assert(!registrations && !observer.candidate_found && observer.faults == 0);
        finish();
        return 0;
    }
    translate_callback(&tb, translate_data);
    entry = &tb.insns[2];
    assert(registrations == 1 && entry->callback && !tb.insns[0].callback);
    assert(observer.candidate.base == fixture_base);
    if (strncmp(scenario, "anchor_changed_", 15) == 0) {
        struct qemu_plugin_tb changed;
        execute(entry, fixture_base + lr_offsets[0]);
        make_tb(&changed, fixture_base, 2);
        if (strcmp(scenario, "anchor_changed_partial") == 0) {
            changed.count = 7;
        } else if (strcmp(scenario, "anchor_changed_shape") == 0) {
            changed.insns[5].size = 8;
        } else if (strcmp(scenario, "anchor_changed_short") == 0) {
            changed.insns[3].copied = 3;
        } else if (strcmp(scenario, "anchor_changed_noncontinuous") == 0) {
            changed.insns[6].pc += 4;
        } else {
            assert(strcmp(scenario, "anchor_changed_bytes") == 0);
            changed.insns[4].bytes[0] ^= 1U;
        }
        translate_callback(&changed, translate_data);
        assert(observer.disabled && strcmp(observer.stop, "anchor_changed") == 0);
        execute(entry, fixture_base + lr_offsets[1]);
        assert(registrations == 1 && observer.records[0] == 1 && !observer.records[1]);
        assert(observer.faults == 1);
    } else if (strcmp(scenario, "noncandidate_after_bound") == 0) {
        struct qemu_plugin_tb unrelated;
        for (unsigned int i = 0; i < 100; ++i) {
            make_tb(&unrelated, fixture_base + UINT64_C(0x100000), 0);
            if (i % 3U == 0) {
                unrelated.count = 5;
            } else if (i % 3U == 1) {
                unrelated.insns[3].bytes[0] ^= 1U;
            } else {
                unrelated.insns[1].size = 2;
            }
            translate_callback(&unrelated, translate_data);
        }
        assert(!observer.disabled && observer.faults == 0 && registrations == 1);
        execute(entry, fixture_base + lr_offsets[0]);
        execute(entry, fixture_base + lr_offsets[1]);
        assert(observer.records[0] == 1 && observer.records[1] == 1);
    } else if (strcmp(scenario, "quotas") == 0 || strcmp(scenario, "interleaved") == 0) {
        for (unsigned int i = 0; i < 100; ++i) {
            execute(entry, fixture_base + UINT64_C(0x209ee84));
        }
        assert(!observer.records[0] && !observer.records[1] && !observer.faults);
        for (unsigned int i = 0; i < 20; ++i) {
            execute(entry, fixture_base + lr_offsets[0]);
            if (strcmp(scenario, "interleaved") == 0) {
                execute(entry, fixture_base + lr_offsets[1]);
                execute(entry, UINT64_MAX);
            }
        }
        if (strcmp(scenario, "quotas") == 0) {
            assert(observer.records[0] == 16 && observer.records[1] == 0);
            for (unsigned int i = 0; i < 20; ++i) {
                execute(entry, fixture_base + lr_offsets[1]);
            }
        }
        assert(observer.records[0] == 16 && observer.records[1] == 16);
    } else if (strcmp(scenario, "ambiguity") == 0) {
        struct qemu_plugin_tb other;
        execute(entry, fixture_base + lr_offsets[0]);
        translate_callback(&tb, translate_data);
        assert(registrations == 2);
        make_tb(&other, fixture_base + UINT64_C(0x100000), 0);
        translate_callback(&other, translate_data);
        assert(observer.ambiguous && observer.disabled);
        assert(observer.conflicting_base == fixture_base + UINT64_C(0x100000));
        for (unsigned int i = 0; i < 100; ++i) {
            execute(entry, fixture_base + lr_offsets[0]);
            translate_callback(&other, translate_data);
        }
        assert(registrations == 2 && observer.records[0] == 1);
    } else if (strcmp(scenario, "fault_budget") == 0) {
        model[REG_X23].length = 7;
        for (unsigned int i = 0; i < 80; ++i) {
            execute(entry, fixture_base + lr_offsets[i % 2U]);
        }
        assert(!observer.records[0] && !observer.records[1]);
        assert(observer.fault_lines == 32 && observer.suppressed_faults == 48);
        model[REG_X23].length = 8;
        for (unsigned int i = 0; i < 32; ++i) {
            execute(entry, fixture_base + lr_offsets[i % 2U]);
        }
        assert(observer.records[0] == 16 && observer.records[1] == 16);
    } else if (strncmp(scenario, "short_", 6) == 0 ||
               strncmp(scenario, "api_", 4) == 0 ||
               strcmp(scenario, "long_cpsr") == 0) {
        const char *name = scenario + (scenario[0] == 's' ? 6 : 4);
        size_t r;
        if (strcmp(scenario, "long_cpsr") == 0) { name = "cpsr"; }
        for (r = 0; r < REG_COUNT && strcmp(name, reg_names[r]) != 0; ++r) {}
        assert(r < REG_COUNT);
        if (strncmp(scenario, "api_", 4) == 0) {
            model[r].ok = false;
        } else {
            model[r].length = strcmp(scenario, "long_cpsr") == 0 ? 8U : model[r].length - 1U;
        }
        execute(entry, fixture_base + lr_offsets[0]);
        assert(!observer.records[0] && !observer.records[1] && observer.faults == 1);
    } else if (strcmp(scenario, "pc_mismatch") == 0 || strcmp(scenario, "stale_pc") == 0) {
        model[REG_PC].value = strcmp(scenario, "stale_pc") == 0
            ? tb.insns[0].pc : model[REG_PC].value + 4U;
        execute(entry, fixture_base + lr_offsets[0]);
        assert(!observer.records[0] && reads == 1);
    } else if (strcmp(scenario, "aarch32") == 0) {
        model[REG_CPSR].value |= UINT64_C(0x10);
        execute(entry, fixture_base + lr_offsets[0]);
        assert(!observer.records[0] && observer.faults == 1);
    } else if (strcmp(scenario, "kernel_context") == 0) {
        model[REG_CPSR].value |= UINT64_C(0x5);
        execute(entry, fixture_base + lr_offsets[0]);
        assert(observer.records[0] == 1 && !observer.faults);
    } else if (strcmp(scenario, "vcpu_exec_limit") == 0) {
        current_vcpu = 1;
        execute(entry, fixture_base + lr_offsets[0]);
        assert(observer.disabled && !observer.records[0] && !reads);
    } else if (strcmp(scenario, "write_failure") == 0 ||
               strcmp(scenario, "flush_failure") == 0) {
        fail_write = strcmp(scenario, "write_failure") == 0;
        fail_flush = strcmp(scenario, "flush_failure") == 0;
        execute(entry, fixture_base + lr_offsets[0]);
        assert(observer.io_failed && observer.disabled && !observer.records[0]);
        execute(entry, fixture_base + lr_offsets[0]);
        fail_write = false;
        fail_flush = false;
    } else if (strcmp(scenario, "format_failure") == 0) {
        char huge[1600];
        memset(huge, 'x', sizeof(huge) - 1U);
        huge[sizeof(huge) - 1U] = '\0';
        assert(!record("fault", "%s", huge));
        assert(observer.io_failed && observer.disabled);
    } else {
        assert(strcmp(scenario, "success") == 0 || strcmp(scenario, "sp_absent") == 0 ||
               strcmp(scenario, "tokens_absent") == 0 ||
               strcmp(scenario, "close_failure") == 0 || strcmp(scenario, "duplicate_install") == 0);
        execute(entry, fixture_base + lr_offsets[0]);
        execute(entry, fixture_base + lr_offsets[1]);
        assert(observer.records[0] == 1 && observer.records[1] == 1);
        if (strcmp(scenario, "duplicate_install") == 0) {
            assert(qemu_plugin_install(1, &info, 1, options) != 0);
        }
    }
    fail_close = strcmp(scenario, "close_failure") == 0;
    finish();
    if (fail_close) { assert(observer.io_failed); }
    return 0;
}
