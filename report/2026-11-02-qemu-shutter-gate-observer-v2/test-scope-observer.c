/* SPDX-License-Identifier: MIT */
/* HOST_MOCK uses the actual API7 header and GLib; only QEMU and host I/O are mocked. */
#ifndef HOST_MOCK
#error "Compile this host-only harness with -DHOST_MOCK"
#endif
#include <qemu-plugin.h>
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static bool fail_write, fail_flush, fail_close;
static unsigned int read_calls, registrations, source_registrations, branch_registrations;
static size_t longest_line;
static size_t host_write(const void *, size_t, size_t, FILE *);
static int host_flush(FILE *);
static int host_close(FILE *);
#define fwrite host_write
#define fflush host_flush
#define fclose host_close
#include "scope-observer.c"
#undef fwrite
#undef fflush
#undef fclose

struct qemu_plugin_insn {
    uint64_t pc;
    size_t size, copied;
    unsigned char bytes[4];
    qemu_plugin_vcpu_udata_cb_t cb;
    enum qemu_plugin_cb_flags flags;
    void *data;
};
struct qemu_plugin_tb { size_t count; struct qemu_plugin_insn insns[8]; };
struct model_reg { uint64_t value; unsigned int length; bool ok, residue; };
static struct model_reg model[REG_COUNT];
static struct qemu_plugin_register *handles[REG_COUNT];
static qemu_plugin_vcpu_udata_cb_t init_cb;
static qemu_plugin_vcpu_tb_trans_cb_t trans_cb;
static qemu_plugin_udata_cb_t exit_cb;
static void *init_data, *trans_data, *exit_data;
static enum qemu_plugin_cb_flags current_flags;
static unsigned int current_cpu, list_mode;
static int missing = -1;
static bool duplicate, absent_optionals;
static const uint64_t B = UINT64_C(0x5500000000);
/* Independent input windows, not the producer's byte arrays. */
static const char *const input_hex[5] = {
    "fd7bbba9fd030091f55b02a9f603012a", "000040b980f7ff35",
    "b3230191e00313aa", "e00313aa44b12894", "5000005800021fd6"
};
static const uint64_t input_offsets[4] = {0x1af16dc,0x1af1830,0x1af1724,0x1af1838};

static size_t host_write(const void *data, size_t size, size_t count, FILE *stream)
{
    const char *line = data;
    assert(size == 1U && count > 0U && count < 2048U && line[count-1U] == '\n');
    if (count > longest_line) { longest_line = count; }
    if (fail_write) { errno = ENOSPC; return 0; }
    return fwrite(data,size,count,stream);
}
static int host_flush(FILE *stream)
{
    if (fail_flush) { errno = EIO; return EOF; }
    return fflush(stream);
}
static int host_close(FILE *stream)
{
    int rc = fclose(stream);
    if (fail_close) { errno = EIO; return EOF; }
    return rc;
}

GArray *qemu_plugin_get_registers(void)
{
    GArray *result;
    assert(current_cpu == 0U);
    if (list_mode == 1U) { return NULL; }
    result = g_array_new(false,false,sizeof(qemu_plugin_reg_descriptor));
    if (list_mode == 2U) { return result; }
    if (list_mode == 3U) { g_array_set_size(result,4097); return result; }
    for (unsigned int i = 0; i < REG_COUNT; ++i) {
        qemu_plugin_reg_descriptor d;
        if ((int)i == missing || (absent_optionals && i >= REG_SP)) { continue; }
        d = (qemu_plugin_reg_descriptor){.handle=handles[i],.name=reg_names[i],.feature=NULL,.is_readonly=false};
        g_array_append_val(result,d);
    }
    if (duplicate) {
        qemu_plugin_reg_descriptor d = {.handle=handles[REG_X0],.name="x0",.feature=NULL,.is_readonly=false};
        g_array_append_val(result,d);
    }
    return result;
}
bool qemu_plugin_read_register(struct qemu_plugin_register *handle, GByteArray *buffer)
{
    size_t r;
    assert(current_cpu == 0U && current_flags == QEMU_PLUGIN_CB_R_REGS && buffer->len == 0U);
    for (size_t i = 0; i < 8U; ++i) { assert(buffer->data[i] == 0U); }
    for (r = 0; r < REG_COUNT && handles[r] != handle; ++r) { }
    assert(r < REG_COUNT);
    ++read_calls;
    g_byte_array_set_size(buffer,model[r].length);
    for (size_t i = 0; i < buffer->len; ++i) {
        if (!model[r].residue) {
            buffer->data[i] = i < 8U ? (unsigned char)(model[r].value >> (8U*i)) : 0xa5;
        }
    }
    return model[r].ok;
}
void qemu_plugin_register_vcpu_init_cb(qemu_plugin_id_t id, qemu_plugin_vcpu_udata_cb_t cb, void *data)
{ assert(id == 1); init_cb=cb; init_data=data; }
void qemu_plugin_register_vcpu_tb_trans_cb(qemu_plugin_id_t id, qemu_plugin_vcpu_tb_trans_cb_t cb, void *data)
{ assert(id == 1); trans_cb=cb; trans_data=data; }
void qemu_plugin_register_atexit_cb(qemu_plugin_id_t id, qemu_plugin_udata_cb_t cb, void *data)
{ assert(id == 1); exit_cb=cb; exit_data=data; }
size_t qemu_plugin_tb_n_insns(const struct qemu_plugin_tb *tb) { return tb->count; }
struct qemu_plugin_insn *qemu_plugin_tb_get_insn(const struct qemu_plugin_tb *tb, size_t i)
{ assert(i < tb->count && i < 8U); return (struct qemu_plugin_insn *)&tb->insns[i]; }
uint64_t qemu_plugin_insn_vaddr(const struct qemu_plugin_insn *i) { return i->pc; }
size_t qemu_plugin_insn_size(const struct qemu_plugin_insn *i) { return i->size; }
size_t qemu_plugin_insn_data(const struct qemu_plugin_insn *i, void *dest, size_t length)
{ assert(length == 4U); memcpy(dest,i->bytes,i->copied < 4U ? i->copied : 4U); return i->copied; }
void qemu_plugin_register_vcpu_insn_exec_cb(struct qemu_plugin_insn *i,
    qemu_plugin_vcpu_udata_cb_t cb, enum qemu_plugin_cb_flags flags, void *data)
{
    uint64_t packed = (uint64_t)(uintptr_t)data;
    unsigned int site = (unsigned int)(packed & 3U) | ((packed & UINT64_C(0x2000000000000)) ? 4U : 0U);
    assert(!i->cb && flags == QEMU_PLUGIN_CB_R_REGS && cb == site_exec);
    assert(site < 5U && !(packed & ~UINT64_C(0x3ffffffffffff)));
    assert((packed & LOW48_MAX & ~UINT64_C(3)) == i->pc);
    if (site == 4U) { assert(!(packed & UINT64_C(0x1000000000000))); ++source_registrations; }
    if (site == 1U) { assert(source_registrations == branch_registrations + 1U); ++branch_registrations; }
    i->cb=cb; i->flags=flags; i->data=data; ++registrations;
}

static void make_site(struct qemu_plugin_tb *tb, unsigned int site, uint64_t base, bool stub)
{
    unsigned int window = site == 4U ? 1U : site;
    const char *hex;
    size_t length;
    assert(site < 5U && (!stub || site == 0U));
    hex = input_hex[stub ? 4U : window];
    length = strlen(hex)/2U;
    memset(tb,0,sizeof(*tb)); tb->count=length/4U;
    for (size_t j = 0; j < tb->count; ++j) {
        tb->insns[j].pc=base+input_offsets[window]+4U*j;
        tb->insns[j].size=4; tb->insns[j].copied=4;
        for (size_t b = 0; b < 4U; ++b) {
            unsigned int byte;
            assert(sscanf(hex+2U*(4U*j+b),"%2x",&byte) == 1);
            tb->insns[j].bytes[b]=(unsigned char)byte;
        }
    }
}
static void translate(struct qemu_plugin_tb *tb) { trans_cb(tb,trans_data); }
static void execute(struct qemu_plugin_tb *tb, unsigned int site)
{
    struct model_reg before[REG_COUNT];
    struct qemu_plugin_insn *i=&tb->insns[site == 1U ? 1U : 0U];
    assert(i->cb);
    model[REG_SP].value = site == 0U ? UINT64_C(0x7ffffffd00) : UINT64_C(0x7ffffffcb0);
    memcpy(before,model,sizeof(before));
    current_flags=i->flags; i->cb(current_cpu,i->data);
    assert(memcmp(before,model,sizeof(before)) == 0);
}
static void init_model(void)
{
    for (size_t r = 0; r < REG_COUNT; ++r) {
        model[r]=(struct model_reg){.value=UINT64_C(0xfedcba9800000000)+r,.length=8,.ok=true,.residue=false};
        handles[r]=(struct qemu_plugin_register *)(uintptr_t)(r+1U);
    }
    handles[REG_X0]=NULL;
    model[REG_PC].value=UINT64_C(0x123456789abcdef0);
    model[REG_X0].value=UINT64_C(0x1122334455667788);
    model[REG_X1].value=UINT64_C(0xaabbccdd80000000);
    model[REG_X2].value=UINT64_C(0x9988776655443322);
    model[REG_X3].value=UINT64_C(0x8877665544332211);
    model[REG_X19].value=UINT64_C(0x7ffffffcf8);
    model[REG_X22].value=UINT64_C(0xabcdef0180000000);
    model[REG_X23].value=UINT64_C(0x1122334455667788);
    model[REG_X29].value=UINT64_C(0x7ffffffcb0);
    model[REG_X30].value=UINT64_C(0xabcd005501af1830);
    model[REG_CPSR].value=UINT64_C(0xa00003c0); model[REG_CPSR].length=4;
    model[REG_SP].value=UINT64_C(0x7ffffffcb0);
    model[REG_TTBR0_EL1].value=UINT64_C(0x1234005500456000);
    model[REG_TPIDR_EL0].value=UINT64_C(0xfedcba9876543210);
}
static void finish(void)
{
    assert(exit_cb); exit_cb(exit_data); exit_cb(exit_data);
    assert(observer.closed && !observer.log && !observer.buffer);
}
static unsigned int reg_arg(const char *name)
{
    for (unsigned int r=0;r<REG_COUNT;++r) { if (!strcmp(name,reg_names[r])) { return r; } }
    assert(false); return 0;
}

int main(int argc, char **argv)
{
    struct qemu_plugin_tb sites[4], changed;
    qemu_info_t info={.target_name="aarch64",.version={.min=7,.cur=7},.system_emulation=true,
                      .system={.smp_vcpus=1,.max_vcpus=1}};
    const char *scenario;
    char argument[4097]; char *args[]={argument};
    bool stub;
    assert(argc >= 3); scenario=argv[1]; stub=!strcmp(scenario,"stub"); init_model();
    assert(snprintf(argument,sizeof(argument),"log=%s",argv[2]) > 0);
    if (!strcmp(scenario,"badarg")) { assert(qemu_plugin_install(1,&info,0,NULL) != 0); return 0; }
    if (!strcmp(scenario,"exclusive")) { assert(qemu_plugin_install(1,&info,1,args) != 0); return 0; }
    if (!strcmp(scenario,"target")) { info.target_name="aarch64_be"; }
    if (!strcmp(scenario,"api")) { info.version.cur=6; }
    if (!strcmp(scenario,"api_min")) { info.version.min=8; }
    if (!strcmp(scenario,"user")) { info.system_emulation=false; }
    if (!strcmp(scenario,"smp")) { info.system.smp_vcpus=2; }
    if (!strcmp(scenario,"maxcpu")) { info.system.max_vcpus=2; }
    if (qemu_plugin_install(1,&info,1,args) != 0) {
        assert(observer.closed && observer.disabled); return 0;
    }
    assert(init_cb && trans_cb && exit_cb);
    if (!strcmp(scenario,"missing")) { assert(argc == 4); missing=(int)reg_arg(argv[3]); }
    if (!strcmp(scenario,"duplicate")) { duplicate=true; }
    if (!strcmp(scenario,"absent")) { absent_optionals=true; }
    if (!strcmp(scenario,"null_list")) { list_mode=1; }
    if (!strcmp(scenario,"empty_list")) { list_mode=2; }
    if (!strcmp(scenario,"huge_list")) { list_mode=3; }
    if (!strcmp(scenario,"init_cpu")) { current_cpu=1; }
    init_cb(current_cpu,init_data); current_cpu=0;
    if (observer.disabled) { finish(); return 0; }
    assert(observer.regs[REG_X0].found && !observer.regs[REG_X0].handle);
    for (unsigned int s=0;s<4U;++s) { make_site(&sites[s],s,B,stub && s == 0U); }
    if (!strncmp(scenario,"order_",6)) {
        const char *order=scenario+6; bool seen[4]={false,false,false,false};
        assert(strlen(order) == 4U);
        for (size_t j=0;j<4U;++j) {
            unsigned int s=(unsigned int)(order[j]-'0'); assert(s<4U && !seen[s]); seen[s]=true;
            unsigned int before=read_calls; translate(&sites[s]);
            if (s == 1U) { execute(&sites[1],4); }
            execute(&sites[s],s);
            if (!observer.candidate_found) { assert(read_calls == before && observer.unbound[s] == 1U); }
        }
        for (unsigned int s=0;s<4U;++s) {
            if (s == 1U) { execute(&sites[1],4); }
            execute(&sites[s],s);
        }
        assert(!observer.disabled && observer.base == B && observer.records[4] == 2U && !observer.unbound[4]);
    } else if (!strcmp(scenario,"weak_first") || !strcmp(scenario,"weak_other") ||
               !strcmp(scenario,"weak_other_original")) {
        bool false_base = strcmp(scenario,"weak_first") != 0;
        for (unsigned int s=0;s<4U;++s) {
            if (s == 1U) { continue; }
            if (false_base) {
                make_site(&sites[s],s,B+0x100000U,s == 0U && !strcmp(scenario,"weak_other"));
            }
            translate(&sites[s]); execute(&sites[s],s);
            assert(!observer.candidate_found && !observer.disabled && read_calls == 0U && observer.unbound[s] == 1U);
        }
        translate(&sites[1]); execute(&sites[1],4); execute(&sites[1],1);
        unsigned int bound_reads = read_calls;
        for (unsigned int s=0;s<4U;++s) { if (s != 1U) { execute(&sites[s],s); } }
        if (!false_base) { assert(observer.sequence == 5U); }
        else {
            assert(observer.sequence == 2U && !observer.ambiguous && observer.unbound[0] == 2U);
            assert(read_calls == bound_reads);
        }
    } else if (!strcmp(scenario,"short_tb") || !strcmp(scenario,"mutation")) {
        for (unsigned int s=0;s<4U;++s) {
            if (!strcmp(scenario,"short_tb")) { sites[s].count=1; }
            else if (s == 1U) { sites[s].insns[1].bytes[0]^=1U; }
            translate(&sites[s]);
            if (s == 1U) { assert(!sites[1].insns[0].cb && !sites[1].insns[1].cb); }
            if (sites[s].insns[0].cb) { execute(&sites[s],s); }
        }
        assert(!observer.candidate_found && !observer.sequence && !read_calls);
    } else if (!strcmp(scenario,"address")) {
        uint64_t b=123;
        const uint64_t bad[]={0,0x1af1830,0xffff005501af1830,0xff00005501af1830,UINT64_MAX};
        for (size_t j=0;j<sizeof(bad)/sizeof(bad[0]);++j) { assert(!derive_base(bad[j],1,&b) && b == 123); }
        assert(!derive_base(B+0x1af1834,1,&b));
        assert(!derive_base(LOW48_MAX-3U,1,&b));
        assert(derive_base(B+0x1af1830,1,&b) && b == B);
        assert(derive_base(B+0x1af1830,4,&b) && b == B);
        for (unsigned int s=5;s<8U;++s) { assert(!derive_base(B+0x1af1830,s,&b) && b == B); }
        uint64_t last=(LOW48_MAX-UINT64_C(0x1af183f)) & ~UINT64_C(0xfff);
        assert(derive_base(last+0x1af1830,4,&b) && b == last);
        assert(!derive_base(last+0x1000U+0x1af1830,4,&b) && b == last);
    } else if (!strcmp(scenario,"unbound_strong")) {
        unsigned int site;
        assert(argc == 4); site=(unsigned int)strtoul(argv[3],NULL,10); assert(site == 1U || site == 4U);
        uint64_t packed=B+(site == 1U ? UINT64_C(0x1af1834) : UINT64_C(0x1af1830));
        packed|=site == 1U ? UINT64_C(1) : UINT64_C(0x2000000000000);
        current_flags=QEMU_PLUGIN_CB_R_REGS; site_exec(0,(void *)(uintptr_t)packed);
        assert(observer.disabled && !read_calls && !observer.sequence && !observer.unbound[site]);
    } else {
        translate(&sites[1]);
        assert(registrations == 2U && source_registrations == 1U && branch_registrations == 1U);
        assert(sites[1].insns[0].cb && sites[1].insns[1].cb);
        assert((uint64_t)(uintptr_t)sites[1].insns[0].data == ((B+0x1af1830U)|UINT64_C(0x2000000000000)));
        assert((uint64_t)(uintptr_t)sites[1].insns[1].data == ((B+0x1af1834U)|UINT64_C(1)));
        for (unsigned int s=0;s<4U;++s) { if (s != 1U) { translate(&sites[s]); } }
        assert(observer.candidate_found && registrations == 5U && observer.anchor_seen_mask == 0x1fU);
        if (!strcmp(scenario,"read")) {
            unsigned int r,site; const char *failure;
            assert(argc == 6); site=(unsigned int)strtoul(argv[3],NULL,10); assert(site<5U);
            r=reg_arg(argv[4]); failure=argv[5];
            if (!strcmp(failure,"false") || !strcmp(failure,"residue")) { model[r].ok=false; }
            else if (!strcmp(failure,"short")) { --model[r].length; }
            else if (!strcmp(failure,"long")) { model[r].length+=1U; }
            else if (!strcmp(failure,"empty")) { model[r].length=0U; }
            else if (!strcmp(failure,"cpsr8")) { model[r].length=8U; }
            else { assert(false); }
            model[r].residue=!strcmp(failure,"residue");
            execute(&sites[site == 4U ? 1U : site],site); assert(!observer.sequence && observer.faults == 1U);
            init_model(); execute(&sites[site == 4U ? 1U : site],site); assert(observer.sequence == 1U);
        } else if (!strcmp(scenario,"modes")) {
            const unsigned int modes[]={0,4,5,8,9,12,13};
            unsigned int site=argc == 4 ? (unsigned int)strtoul(argv[3],NULL,10) : 1U; assert(site<5U);
            for (size_t j=0;j<7U;++j) {
                model[REG_CPSR].value=0xf00003c0U|modes[j]; execute(&sites[site == 4U ? 1U : site],site);
            }
            assert(observer.sequence == 7U && !observer.faults);
        } else if (!strcmp(scenario,"a32") || !strcmp(scenario,"reserved")) {
            unsigned int site=argc == 4 ? (unsigned int)strtoul(argv[3],NULL,10) : 1U; assert(site<5U);
            model[REG_CPSR].value|=!strcmp(scenario,"a32") ? 0x10U : 2U;
            execute(&sites[site == 4U ? 1U : site],site); assert(!observer.sequence && observer.faults == 1U);
        } else if (!strcmp(scenario,"low32")) {
            const uint64_t values[]={0xfeedface00000000ULL,0xfeedface00000001ULL,
                                     0xfeedfaceffffffffULL,0xfeedface80000000ULL};
            for (size_t j=0;j<4U;++j) {
                model[REG_X0].value=values[j]; model[REG_CPSR].value=j%2U ? 0x400003c0U : 0x800003c0U;
                execute(&sites[1],1);
            }
            assert(observer.sequence == 4U);
        } else if (!strcmp(scenario,"source_pointer")) {
            const uint64_t values[]={0,UINT64_C(0x1122334455667788),UINT64_C(0xfedcba9800000000),UINT64_MAX};
            assert(observer.regs[REG_X0].found && !observer.regs[REG_X0].handle);
            for (size_t j=0;j<sizeof(values)/sizeof(values[0]);++j) {
                model[REG_X0].value=values[j]; execute(&sites[1],4);
            }
            assert(observer.records[4] == 4U && observer.sequence == 4U && !observer.records[1]);
        } else if (!strcmp(scenario,"dual_tap") || !strcmp(scenario,"duplicate_gate")) {
            struct qemu_plugin_tb *gate=&sites[1];
            if (!strcmp(scenario,"duplicate_gate")) {
                unsigned int before=registrations;
                make_site(&changed,1,B,false); changed.count=4;
                changed.insns[2]=changed.insns[0]; changed.insns[3]=changed.insns[1];
                translate(&changed);
                assert(registrations == before+2U && changed.insns[0].cb && changed.insns[1].cb);
                assert(!changed.insns[2].cb && !changed.insns[3].cb);
                gate=&changed;
            }
            execute(gate,4); model[REG_X0].value=UINT64_C(0xdeadbeef00000001); execute(gate,1);
            assert(observer.sequence == 2U && observer.records[4] == 1U && observer.records[1] == 1U);
        } else if (!strcmp(scenario,"reuse")) {
            execute(&sites[1],1); execute(&sites[0],0); execute(&sites[1],1);
            execute(&sites[0],0); execute(&sites[2],2); execute(&sites[3],3);
            assert(observer.sequence == 6U && observer.records[0] == 2U && observer.records[1] == 2U);
        } else if (!strcmp(scenario,"conflict")) {
            execute(&sites[0],0); make_site(&changed,1,B+0x100000U,false); translate(&changed);
            unsigned int reads=read_calls; execute(&sites[1],4); execute(&sites[1],1);
            assert(observer.ambiguous && observer.disabled && observer.conflicting_base == B+0x100000U && read_calls == reads);
            assert(!observer.records[4] && !changed.insns[0].cb && !changed.insns[1].cb);
        } else if (!strcmp(scenario,"changed") || !strcmp(scenario,"shape") ||
                   !strcmp(scenario,"copy_short") || !strcmp(scenario,"copy_long") ||
                   !strcmp(scenario,"noncontinuous") || !strcmp(scenario,"known_short")) {
            unsigned int s=argc == 4 ? (unsigned int)strtoul(argv[3],NULL,10) : 1U; assert(s<5U);
            make_site(&changed,s,B,false);
            if (!strcmp(scenario,"known_short")) { changed.count=1; }
            else if (!strcmp(scenario,"shape")) { changed.insns[1].size=8; }
            else if (!strcmp(scenario,"copy_short")) { changed.insns[1].copied=3; }
            else if (!strcmp(scenario,"copy_long")) { changed.insns[1].copied=5; }
            else if (!strcmp(scenario,"noncontinuous")) { changed.insns[1].pc+=4U; }
            else { changed.insns[1].bytes[0]^=1U; }
            translate(&changed);
            if (!strcmp(scenario,"known_short")) { assert(!observer.disabled && !observer.faults); }
            else { assert(observer.disabled && observer.faults == 1U); }
            if (s == 1U || s == 4U) {
                assert(!changed.insns[0].cb && !changed.insns[1].cb);
                if (strcmp(scenario,"known_short")) {
                    unsigned int before=read_calls; execute(&sites[1],4); execute(&sites[1],1);
                    assert(read_calls == before && !observer.records[4] && !observer.records[1]);
                }
            }
        } else if (!strcmp(scenario,"changed_stub2") || !strcmp(scenario,"entry_prefix2") ||
                   !strcmp(scenario,"entry_prefix3")) {
            bool prefix = strcmp(scenario,"changed_stub2") != 0;
            make_site(&changed,0,B,!prefix);
            if (prefix) {
                changed.count=!strcmp(scenario,"entry_prefix2") ? 2U : 3U;
                translate(&changed);
                assert(!observer.disabled && !observer.faults);
                execute(&sites[0],0);
                assert(observer.records[0] == 1U);
            } else {
                translate(&changed); execute(&changed,0);
                assert(observer.records[0] == 1U && !observer.faults);
                changed.insns[1].bytes[0]^=0x20U;
                translate(&changed);
                unsigned int before=read_calls; execute(&changed,0);
                assert(observer.disabled && observer.faults == 1U && read_calls == before);
            }
        } else if (!strcmp(scenario,"transition")) {
            execute(&sites[0],0); make_site(&changed,0,B,true); translate(&changed); execute(&changed,0);
            assert(!observer.disabled && observer.records[0] == 2U);
        } else if (!strcmp(scenario,"userdata")) {
            assert(argc == 4); current_flags=QEMU_PLUGIN_CB_R_REGS;
            site_exec(0,(void *)(uintptr_t)strtoull(argv[3],NULL,16));
            assert(observer.disabled && !read_calls && !observer.sequence);
        } else if (!strcmp(scenario,"exec_cpu") || !strcmp(scenario,"metadata") || !strcmp(scenario,"reinit")) {
            if (!strcmp(scenario,"reinit")) { init_cb(0,init_data); }
            else {
                if (!strcmp(scenario,"exec_cpu")) { current_cpu=1; }
                else { sites[1].insns[1].data=(void *)(uintptr_t)(B|UINT64_C(0x2000000000000000)); }
                execute(&sites[1],1); current_cpu=0;
            }
            assert(observer.disabled && !read_calls && !observer.sequence);
        } else if (!strcmp(scenario,"quotas") || !strcmp(scenario,"fault_budget") || !strcmp(scenario,"longest")) {
            if (!strcmp(scenario,"fault_budget")) {
                model[REG_X0].ok=false;
                for (unsigned int j=0;j<80U;++j) { execute(&sites[1],1); }
                assert(observer.fault_lines == 32U && observer.suppressed_faults == 48U);
                model[REG_X0].ok=true;
            }
            model[REG_CPSR].value=0xf00003cdU;
            for (unsigned int s=0;s<5U;++s) {
                for (unsigned int j=0;j<17U;++j) { execute(&sites[s == 4U ? 1U : s],s); }
                assert(observer.records[s] == 16U && observer.suppressed[s] == 1U);
            }
            unsigned int before=read_calls;
            for (unsigned int s=0;s<5U;++s) { execute(&sites[s == 4U ? 1U : s],s); }
            assert(read_calls == before && observer.sequence == 80U && longest_line > 1200U && longest_line < 2048U);
        } else if (!strcmp(scenario,"write_failure") || !strcmp(scenario,"flush_failure") || !strcmp(scenario,"format_failure")) {
            fail_write=!strcmp(scenario,"write_failure"); fail_flush=!strcmp(scenario,"flush_failure");
            if (!strcmp(scenario,"format_failure")) {
                char huge[1901]; memset(huge,'a',1900); huge[1900]='\0'; assert(!record("shutter_gate","%s",huge));
            } else {
                unsigned int site=argc == 4 ? (unsigned int)strtoul(argv[3],NULL,10) : 1U; assert(site<5U);
                execute(&sites[site == 4U ? 1U : site],site);
            }
            assert(observer.io_failed && observer.disabled && !observer.sequence);
            fail_write=false; fail_flush=false;
        } else {
            assert(!strcmp(scenario,"success") || !strcmp(scenario,"stub") || !strcmp(scenario,"absent") ||
                   !strcmp(scenario,"close_failure") || !strcmp(scenario,"duplicate_install"));
            for (unsigned int s=0;s<5U;++s) { execute(&sites[s == 4U ? 1U : s],s); }
            assert(observer.sequence == 5U && !observer.faults);
            if (!strcmp(scenario,"duplicate_install")) { assert(qemu_plugin_install(1,&info,1,args) != 0); }
        }
    }
    fail_close=!strcmp(scenario,"close_failure"); finish(); return 0;
}
