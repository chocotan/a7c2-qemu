/* SPDX-License-Identifier: MIT */
#ifndef HOST_MOCK
#error "This is an isolated host-only test"
#endif
#include <assert.h>
#include <stdlib.h>
#include "scope-observer.c"

struct qemu_plugin_insn {
    uint64_t pc; size_t size,copied; unsigned char bytes[4];
    qemu_plugin_vcpu_udata_cb_t cb; enum qemu_plugin_cb_flags flags; void *data;
};
struct qemu_plugin_tb { size_t count; struct qemu_plugin_insn insns[9]; };
struct model_reg { uint64_t value; unsigned int length; bool ok; };
static struct model_reg model[REG_COUNT];
static struct qemu_plugin_register *handles[REG_COUNT];
static qemu_plugin_vcpu_udata_cb_t init_cb;
static qemu_plugin_vcpu_tb_trans_cb_t trans_cb;
static qemu_plugin_udata_cb_t exit_cb;
static void *init_data,*trans_data,*exit_data;
static enum qemu_plugin_cb_flags active_flags;
static unsigned int registrations,read_calls,scenario;
static const uint64_t B=UINT64_C(0x5500000000);

GArray *qemu_plugin_get_registers(void)
{
    GArray *array=g_array_new(false,false,sizeof(qemu_plugin_reg_descriptor));
    for (unsigned int r=0;r<REG_COUNT;++r) {
        qemu_plugin_reg_descriptor d={.handle=handles[r],.name=reg_names[r],.feature=NULL,.is_readonly=false};
        if ((scenario==22U && r==REG_X0) || (scenario==24U && r>=REG_SP) ||
            ((scenario==102U || scenario==149U) && r>=REG_SP && r<REG_X2)) { continue; }
        if ((scenario==258U && r==REG_X20) || (scenario==259U && r==REG_X21)) { continue; }
        g_array_append_val(array,d);
    }
    if (scenario==23U) {
        qemu_plugin_reg_descriptor d={.handle=handles[REG_X0],.name="x0",.feature=NULL,.is_readonly=false};
        g_array_append_val(array,d);
    }
    return array;
}
bool qemu_plugin_read_register(struct qemu_plugin_register *handle,GByteArray *buffer)
{
    size_t r;
    assert(active_flags==QEMU_PLUGIN_CB_R_REGS && buffer->len==0U);
    for (size_t i=0;i<8U;++i) { assert(buffer->data[i]==0U); }
    for (r=0;r<REG_COUNT && handles[r]!=handle;++r) { }
    assert(r<REG_COUNT);++read_calls;
    g_byte_array_set_size(buffer,model[r].length);
    for (size_t i=0;i<buffer->len;++i) { buffer->data[i]=i<8U ? (unsigned char)(model[r].value>>(i*8U)) : 0xa5; }
    return model[r].ok;
}
void qemu_plugin_register_vcpu_init_cb(qemu_plugin_id_t id,qemu_plugin_vcpu_udata_cb_t cb,void *data)
{ assert(id==1);init_cb=cb;init_data=data; }
void qemu_plugin_register_vcpu_tb_trans_cb(qemu_plugin_id_t id,qemu_plugin_vcpu_tb_trans_cb_t cb,void *data)
{ assert(id==1);trans_cb=cb;trans_data=data; }
void qemu_plugin_register_atexit_cb(qemu_plugin_id_t id,qemu_plugin_udata_cb_t cb,void *data)
{ assert(id==1);exit_cb=cb;exit_data=data; }
size_t qemu_plugin_tb_n_insns(const struct qemu_plugin_tb *tb) { return tb->count; }
struct qemu_plugin_insn *qemu_plugin_tb_get_insn(const struct qemu_plugin_tb *tb,size_t i)
{ assert(i<tb->count && i<9U);return (struct qemu_plugin_insn *)&tb->insns[i]; }
uint64_t qemu_plugin_insn_vaddr(const struct qemu_plugin_insn *i) { return i->pc; }
size_t qemu_plugin_insn_size(const struct qemu_plugin_insn *i) { return i->size; }
size_t qemu_plugin_insn_data(const struct qemu_plugin_insn *i,void *dest,size_t length)
{ assert(length==4U);memcpy(dest,i->bytes,i->copied<4U ? i->copied : 4U);return i->copied; }
void qemu_plugin_register_vcpu_insn_exec_cb(struct qemu_plugin_insn *i,qemu_plugin_vcpu_udata_cb_t cb,
    enum qemu_plugin_cb_flags flags,void *data)
{
    uint64_t packed=(uint64_t)(uintptr_t)data;
    assert(!i->cb && flags==QEMU_PLUGIN_CB_R_REGS && (cb==site_exec || cb==origin_exec || cb==record_exec || cb==descriptor_exec || cb==pointer_exec));
    assert((packed&3U)<(cb==site_exec ? SITE_COUNT : ORIGIN_COUNT) && (packed&~UINT64_C(3))==i->pc);
    i->cb=cb;i->flags=flags;i->data=data;++registrations;
}
static void make_body(struct qemu_plugin_tb *tb,uint64_t base)
{
    static const unsigned char body[12]={0xa1,0xb7,0x02,0xd0,0x20,0x70,0x05,0xb9,0xc0,0x03,0x5f,0xd6};
    memset(tb,0,sizeof(*tb));tb->count=3;
    for (size_t j=0;j<3U;++j) {
        tb->insns[j].pc=base+UINT64_C(0x2767978)+4U*j;tb->insns[j].size=4;tb->insns[j].copied=4;
        memcpy(tb->insns[j].bytes,body+j*4U,4);
    }
}
static void execute(struct qemu_plugin_tb *tb,unsigned int site,unsigned int cpu)
{
    struct model_reg before[REG_COUNT];struct qemu_plugin_insn *i=&tb->insns[site];assert(i->cb);
    model[REG_PC].value=i->pc;
    model[REG_X1].value=site ? B+UINT64_C(0x7e5d000) : UINT64_C(0x12345678);
    if (scenario==19U && site) { ++model[REG_X1].value; }
    memcpy(before,model,sizeof(before));active_flags=i->flags;i->cb(cpu,i->data);
    assert(memcmp(before,model,sizeof(before))==0);
}
static void make_origin(struct qemu_plugin_tb *tb, unsigned int site, uint64_t base)
{
    memset(tb, 0, sizeof(*tb)); tb->count = origin_lengths[site] / 4U;
    for (size_t j = 0; j < tb->count; ++j) {
        tb->insns[j].pc = base + origin_offsets[site] + 4U * j;
        tb->insns[j].size = tb->insns[j].copied = 4U;
        memcpy(tb->insns[j].bytes, origin_anchors[site] + 4U * j, 4U);
    }
}
static void execute_origin(struct qemu_plugin_tb *tb, unsigned int cpu, uint32_t selector)
{
    struct model_reg before[REG_COUNT]; struct qemu_plugin_insn *i = &tb->insns[0];
    assert(i->cb == origin_exec);
    model[REG_PC].value = i->pc; model[REG_X0].value = UINT64_C(0x1234567800000000) | selector;
    model[REG_X1].value = UINT64_C(0x1122334400000001);
    memcpy(before, model, sizeof(before)); active_flags = i->flags; i->cb(cpu, i->data);
    assert(memcmp(before, model, sizeof(before)) == 0);
}
static void execute_upstream(struct qemu_plugin_tb *tb, unsigned int cpu, uint64_t x0, uint64_t selector, uint64_t value, uint64_t flag)
{
    struct model_reg before[REG_COUNT]; struct qemu_plugin_insn *i = &tb->insns[0];
    assert(i->cb == origin_exec);
    model[REG_PC].value = i->pc; model[REG_X0].value = x0;
    model[REG_X1].value = selector; model[REG_X2].value = value; model[REG_X3].value = flag;
    memcpy(before, model, sizeof(before)); active_flags = i->flags; i->cb(cpu, i->data);
    assert(memcmp(before, model, sizeof(before)) == 0);
}
static void make_record(struct qemu_plugin_tb *tb, uint64_t base)
{
    memset(tb, 0, sizeof(*tb)); tb->count = sizeof(record36)/4U;
    for (size_t j=0;j<tb->count;++j) {
        tb->insns[j].pc=base+RECORD_BLOCK+4U*j;
        tb->insns[j].size=tb->insns[j].copied=4U;
        memcpy(tb->insns[j].bytes,record36+4U*j,4U);
    }
}
static void execute_record(struct qemu_plugin_tb *tb, unsigned int site)
{
    struct model_reg before[REG_COUNT]; struct qemu_plugin_insn *i=&tb->insns[record_indexes[site]];
    assert(i->cb==record_exec);
    model[REG_PC].value=scenario==264U ? B+RECORD_BLOCK : i->pc;
    if (scenario==252U) { model[REG_PC].value+=4U; }
    model[REG_X1].value=site ? B+RECORD_DEST : UINT64_C(0x12345678);
    if (scenario==238U && site==1U) { ++model[REG_X1].value; }
    model[REG_X0].value=site==2U ? 1U : UINT64_C(0xdeadbeef00000001);
    if (scenario==239U && site==2U) { model[REG_X0].value=0U; }
    memcpy(before,model,sizeof(before));active_flags=i->flags;i->cb(scenario==253U ? 1U : 0U,i->data);
    assert(memcmp(before,model,sizeof(before))==0);
}
static void make_descriptor(struct qemu_plugin_tb *tb,uint64_t base)
{
    memset(tb,0,sizeof(*tb));tb->count=3U;
    for(size_t j=0;j<3U;++j){tb->insns[j].pc=base+DESCRIPTOR_ENTRY+4U*j;tb->insns[j].size=tb->insns[j].copied=4U;memcpy(tb->insns[j].bytes,descriptor12+4U*j,4U);}
}
static void execute_descriptor(struct qemu_plugin_tb *tb,unsigned int site)
{
    struct model_reg before[REG_COUNT];struct qemu_plugin_insn *i=&tb->insns[site];assert(i->cb==descriptor_exec);
    model[REG_PC].value=scenario==333U?B+DESCRIPTOR_ENTRY:i->pc;
    if(scenario==315U){++model[REG_PC].value;}
    model[REG_X0].value=scenario==334U?UINT64_MAX:scenario==335U?UINT64_C(0):UINT64_C(0x1234567800000001);
    model[REG_X1].value=site?B+UINT64_C(0x7e5d000):UINT64_C(0x11223344);
    if(scenario==314U && site){++model[REG_X1].value;}
    memcpy(before,model,sizeof(before));active_flags=i->flags;i->cb(scenario==322U?1U:0U,i->data);assert(!memcmp(before,model,sizeof(before)));
}
static void make_pointer(struct qemu_plugin_tb *tb,unsigned int site,uint64_t base)
{
    memset(tb,0,sizeof(*tb));tb->count=pointer_lengths[site]/4U;
    for(size_t j=0;j<tb->count;++j){tb->insns[j].pc=base+pointer_starts[site]+4U*j;tb->insns[j].size=tb->insns[j].copied=4U;memcpy(tb->insns[j].bytes,pointer_bytes[site]+4U*j,4U);}
}
static void execute_pointer(struct qemu_plugin_tb *tb,unsigned int site,unsigned int variant)
{
    struct model_reg before[REG_COUNT];struct qemu_plugin_insn *i=&tb->insns[(pointer_stores[site]-pointer_starts[site])/4U];assert(i->cb==pointer_exec);
    model[REG_PC].value=variant==29U?B+pointer_starts[site]:i->pc;
    model[REG_X0].value=variant==18U?B+UINT64_C(0x7e5d570):B+UINT64_C(0x7e5d578);
    model[pointer_regs[site]].value=variant==28U?UINT64_MAX:UINT64_C(0x1234567800000001);
    if(variant==19U){++model[REG_PC].value;}
    memcpy(before,model,sizeof(before));active_flags=i->flags;i->cb(variant==31U?1U:0U,i->data);assert(!memcmp(before,model,sizeof(before)));
}
int main(int argc,char **argv)
{
    struct qemu_plugin_tb tb,other;
    qemu_info_t info={.target_name="aarch64",.version={.min=7,.cur=7},.system_emulation=true,
        .system={.smp_vcpus=1,.max_vcpus=1}};
    char arg[4097];char *args[]={arg};assert(argc==3);scenario=(unsigned int)strtoul(argv[1],NULL,10);assert(scenario<700U);
    for (size_t r=0;r<REG_COUNT;++r) {
        handles[r]=(struct qemu_plugin_register *)(uintptr_t)(r+1U);
        model[r]=(struct model_reg){.value=UINT64_C(0x1122334455667788)+r,.length=8,.ok=true};
    }
    model[REG_CPSR]=(struct model_reg){.value=UINT64_C(0x80000000),.length=4,.ok=true};
    model[REG_X0].value=UINT64_C(0x1234567800000001);model[REG_X30].value=B+UINT64_C(0x209eea0);
    assert(snprintf(arg,sizeof(arg),"log=%s",argv[2])>0);
    assert(qemu_plugin_install(1,&info,1,args)==0);init_cb(0,init_data);
    if (scenario==22U || scenario==23U) { assert(observer.disabled && observer.faults);goto done; }
    if(scenario>=400U){
        unsigned int site=(scenario-400U)/100U,variant=(scenario-400U)%100U;
        assert(site<3U && variant<=33U);
        make_pointer(&tb,site,B);
        if(variant>=1U && variant<=16U){unsigned int byte=(variant-1U)%(unsigned int)pointer_lengths[site];tb.insns[byte/4U].bytes[byte%4U]^=1U;}
        if(variant==17U){--tb.count;}
        trans_cb(&tb,trans_data);
        if((variant>=1U && variant<=17U)){assert(!observer.pointer_anchor_mask && registrations==0U && read_calls==0U);goto done;}
        assert(observer.pointer_anchor_mask==(1U<<site) && registrations==1U);
        if(variant==20U){model[REG_PC].length=1U;}
        if(variant==21U){model[pointer_regs[site]].length=1U;}
        if(variant==22U){model[REG_X30].ok=false;}
        if(variant==23U){model[REG_CPSR].value=1U;}
        if(variant==30U){observer.regs[REG_SP].found=false;}
        if(variant==24U || variant==32U){
            for(unsigned int j=0;j<18U;++j){execute_pointer(&tb,site,0U);}
            assert(observer.pointer_records[site]==16U && observer.pointer_suppressed[site]==2U);
            if(variant==32U){execute_pointer(&tb,site,18U);assert(observer.pointer_filtered[site]==1U);}
            goto done;
        }
        if(variant==25U){make_descriptor(&other,B+0x1000U);trans_cb(&other,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(variant==26U){make_body(&other,B);trans_cb(&other,trans_data);make_pointer(&tb,site,B+0x1000U);trans_cb(&tb,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(variant==27U){make_pointer(&other,site,B);other.insns[0].bytes[0]^=1U;trans_cb(&other,trans_data);assert(observer.disabled && !strcmp(observer.stop,"pointer_anchor_changed"));goto done;}
        execute_pointer(&tb,site,variant);
        if(variant==18U){assert(observer.pointer_filtered[site]==1U && observer.pointer_sequence==0U);goto done;}
        if((variant>=19U && variant<=23U)||variant==31U){assert(observer.faults);goto done;}
        assert(observer.pointer_sequence==1U && !observer.faults);
        if(variant==33U){
            make_descriptor(&other,B);trans_cb(&other,trans_data);for(unsigned int j=0;j<3U;++j){execute_descriptor(&other,j);}
            make_record(&other,B);trans_cb(&other,trans_data);model[REG_X19].value=0xa24U;model[REG_X21].value=1U;
            for(unsigned int j=0;j<3U;++j){execute_record(&other,j);}
            make_origin(&other,2U,B);trans_cb(&other,trans_data);execute_upstream(&other,0U,0x99U,0x17cU,1U,0U);
            make_origin(&other,0U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
            make_origin(&other,1U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
            make_body(&other,B);trans_cb(&other,trans_data);for(unsigned int j=0;j<3U;++j){execute(&other,j,0U);}
            assert(observer.observation_sequence==13U && !observer.faults);
        }
        goto done;
    }
    if(scenario>=300U){
        make_descriptor(&tb,B);
        if(scenario>=301U && scenario<=312U){unsigned int byte=scenario-301U;tb.insns[byte/4U].bytes[byte%4U]^=1U;}
        if(scenario==313U){tb.count=2U;}
        if(scenario==336U){tb.insns[1].pc+=4U;}
        if(scenario==337U){tb.insns[1].copied=3U;}
        trans_cb(&tb,trans_data);
        if((scenario>=301U && scenario<=313U)||scenario==336U||scenario==337U){assert(!observer.descriptor_anchor_seen && registrations==0U && read_calls==0U);goto done;}
        assert(observer.descriptor_anchor_seen && registrations==3U);
        if(scenario>=316U && scenario<=319U){static const enum reg_index regs[]={REG_X0,REG_X30,REG_X1,REG_CPSR};model[regs[scenario-316U]].length=1U;}
        if(scenario==320U){model[REG_CPSR].value=1U;}
        if(scenario==321U){model[REG_SP].ok=false;}
        if(scenario==323U){for(unsigned int n=0;n<18U;++n){for(unsigned int j=0;j<3U;++j){execute_descriptor(&tb,j);}}assert(observer.descriptor_sequence==48U);for(unsigned int j=0;j<3U;++j){assert(observer.descriptor_suppressed[j]==2U);}goto done;}
        if(scenario==324U){make_body(&other,B+0x1000U);trans_cb(&other,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(scenario==325U){make_record(&other,B+0x1000U);trans_cb(&other,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(scenario==326U){make_descriptor(&other,B+0x1000U);trans_cb(&other,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(scenario==327U){make_origin(&other,2U,B+0x1000U);trans_cb(&other,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(scenario==328U){make_origin(&other,2U,B);trans_cb(&other,trans_data);make_descriptor(&tb,B+0x1000U);trans_cb(&tb,trans_data);assert(observer.disabled && observer.ambiguous);goto done;}
        if(scenario==329U){make_descriptor(&other,B);other.insns[0].bytes[0]^=1U;trans_cb(&other,trans_data);assert(observer.disabled && !strcmp(observer.stop,"descriptor_anchor_changed"));goto done;}
        if(scenario==331U){model[REG_PC].ok=false;}
        if(scenario==332U){model[REG_X0].ok=false;}
        for(unsigned int j=0;j<3U && !observer.disabled;++j){execute_descriptor(&tb,j);}
        if((scenario>=314U && scenario<=322U)||scenario==331U||scenario==332U){assert(observer.faults);goto done;}
        assert(observer.descriptor_sequence==3U && !observer.faults);
        if(scenario==330U){
            make_record(&other,B);trans_cb(&other,trans_data);model[REG_X19].value=0xa24U;model[REG_X21].value=1U;
            for(unsigned int j=0;j<3U;++j){execute_record(&other,j);}
            make_origin(&other,2U,B);trans_cb(&other,trans_data);execute_upstream(&other,0U,0x99U,0x17cU,1U,0U);
            make_origin(&other,0U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
            make_origin(&other,1U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
            make_body(&other,B);trans_cb(&other,trans_data);for(unsigned int j=0;j<3U;++j){execute(&other,j,0U);}
            assert(observer.observation_sequence==12U && !observer.faults);
        }
        goto done;
    }
    if (scenario>=200U) {
        make_record(&tb,B);
        if (scenario>=201U && scenario<=236U) { unsigned int byte=scenario-201U;tb.insns[byte/4U].bytes[byte%4U]^=1U; }
        if (scenario==237U) { --tb.count; }
        if (scenario==261U) { tb.insns[1].pc+=4U; }
        if (scenario==262U) { tb.insns[4].copied=3U; }
        trans_cb(&tb,trans_data);
        if ((scenario>=201U && scenario<=237U) || scenario==261U || scenario==262U) {
            assert(!observer.record_anchor_seen && registrations==0U && read_calls==0U);goto done;
        }
        assert(observer.record_anchor_seen && observer.record_base==B && registrations==3U);
        model[REG_X19].value=scenario==240U ? UINT64_C(0x100000a24) : UINT64_C(0xa24);
        model[REG_X20].value=UINT64_C(0x1234567887654321);model[REG_X21].value=UINT64_C(0x8765432100000001);
        if (scenario>=244U && scenario<=251U) {
            static const enum reg_index required[]={REG_PC,REG_X0,REG_X1,REG_X19,REG_X20,REG_X21,REG_X30,REG_CPSR};
            model[required[scenario-244U]].length=1U;
        }
        if (scenario==254U) { model[REG_SP].ok=false; }
        if (scenario==260U) { model[REG_CPSR].value=1U; }
        if (scenario==241U) {
            for(unsigned int j=0;j<SITE_QUOTA+2U;++j){for(unsigned int site=0;site<3U;++site){execute_record(&tb,site);}}
            for(unsigned int site=0;site<3U;++site){assert(observer.record_records[site]==16U && observer.record_suppressed[site]==2U);}
            assert(observer.record_sequence==48U && observer.observation_sequence==48U);goto done;
        }
        if (scenario==242U) {
            make_origin(&other,2U,B+0x1000U);trans_cb(&other,trans_data);
            assert(observer.disabled && observer.ambiguous);goto done;
        }
        if (scenario==243U) {
            make_body(&other,B+0x1000U);trans_cb(&other,trans_data);
            assert(observer.disabled && observer.ambiguous);goto done;
        }
        if (scenario==255U) {
            make_record(&other,B);other.insns[7].bytes[0]^=1U;trans_cb(&other,trans_data);
            assert(observer.disabled && !strcmp(observer.stop,"record_anchor_changed"));goto done;
        }
        if (scenario==263U) {
            make_record(&other,B+0x1000U);trans_cb(&other,trans_data);
            assert(observer.disabled && observer.ambiguous);goto done;
        }
        for(unsigned int site=0;site<3U && !observer.disabled;++site){execute_record(&tb,site);}
        if (scenario==240U) {
            assert(observer.record_sequence==0U && !observer.faults);
            for(unsigned int site=0;site<3U;++site){assert(observer.record_skipped[site]==1U);}goto done;
        }
        if (scenario==238U || scenario==239U || (scenario>=244U && scenario<=254U) ||
            scenario==258U || scenario==259U || scenario==260U) { assert(observer.faults);goto done; }
        assert(observer.record_sequence==3U && observer.observation_sequence==3U && !observer.faults);
        if (scenario==256U) {
            make_origin(&other,2U,B);trans_cb(&other,trans_data);execute_upstream(&other,0U,0x99U,0x17cU,1U,0U);
            make_origin(&other,0U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
            make_origin(&other,1U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
            make_body(&other,B);trans_cb(&other,trans_data);for(unsigned int site=0;site<3U;++site){execute(&other,site,0U);}
            assert(observer.observation_sequence==9U && !observer.faults);
        }
        if (scenario==257U) {
            make_record(&other,B);trans_cb(&other,trans_data);model[REG_X19].value=0xa25U;
            for(unsigned int site=0;site<3U;++site){execute_record(&other,site);}
            assert(observer.record_sequence==3U);
        }
        goto done;
    }
    if (scenario>=105U) {
        make_origin(&tb, 2U, B);
        if (scenario>=106U && scenario<=137U) {
            unsigned int byte=scenario-106U;
            tb.insns[byte/4U].bytes[byte%4U]^=1U;
        }
        if (scenario==138U) { --tb.count; }
        trans_cb(&tb, trans_data);
        if (scenario>=106U && scenario<=138U) {
            assert(observer.origin_anchor_mask==0U && registrations==0U && read_calls==0U);goto done;
        }
        assert(observer.origin_anchor_mask==4U && registrations==1U);
        if (scenario==144U) {
            make_origin(&other, 0U, B+0x1000U);trans_cb(&other,trans_data);
            assert(observer.disabled && observer.ambiguous && !strcmp(observer.stop,"origin_base_conflict"));goto done;
        }
        if (scenario==145U) {
            make_origin(&other, 2U, B);other.insns[0].bytes[0]^=1U;trans_cb(&other,trans_data);
            assert(observer.disabled && !strcmp(observer.stop,"origin_anchor_changed"));goto done;
        }
        if (scenario==140U) {
            execute_upstream(&tb,0U,0x17cU,0x17dU,0U,0U);
            assert(observer.origin_skipped[2]==1U && observer.origin_records[2]==0U);goto done;
        }
        if (scenario==141U) {model[REG_X1].length=7U;}
        if (scenario==142U) {model[REG_X1].ok=false;}
        if (scenario==147U) {model[REG_CPSR].value=1U;}
        if (scenario==148U) {model[REG_X0].length=7U;}
        if (scenario==151U) {model[REG_X2].ok=false;}
        if (scenario==143U) {
            for(unsigned int j=0;j<SITE_QUOTA+2U;++j){execute_upstream(&tb,0U,0x123U,0x17cU,j,0U);}
            assert(observer.origin_records[2]==SITE_QUOTA && observer.origin_suppressed[2]==2U);goto done;
        }
        execute_upstream(&tb,scenario==146U ? 1U : 0U,scenario==139U ? 0x99U : UINT64_C(0xabcdef0012345678),
            UINT64_C(0x112233440000017c),UINT64_C(0x9988776600000001),scenario==152U ? UINT64_MAX : 0U);
        if (scenario==141U || scenario==142U || scenario==146U || scenario==147U || scenario==148U || scenario==151U) {
            assert(observer.faults && observer.origin_records[2]==0U);goto done;
        }
        assert(observer.origin_records[2]==1U && observer.observation_sequence==1U);
        if (scenario==153U) {
            execute_upstream(&tb,0U,0U,0x17cU,0U,1U);
            assert(observer.origin_records[2]==2U && observer.observation_sequence==2U);goto done;
        }
        if (scenario!=105U) {goto done;}
        make_origin(&other,0U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
        make_origin(&other,1U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
        make_body(&tb,B);trans_cb(&tb,trans_data);
        for(unsigned int site=0;site<3U;++site){execute(&tb,site,0U);}
        assert(observer.origin_sequence==3U && observer.observation_sequence==6U && !observer.faults);goto done;
    }
    if (scenario>=28U) {
        unsigned int selected = scenario>=65U && scenario<=96U ? 1U : 0U;
        make_origin(&tb, selected, B);
        if (scenario>=29U && scenario<=96U) {
            unsigned int byte = scenario-29U-(selected ? 36U : 0U);
            assert(byte<origin_lengths[selected]);tb.insns[byte/4U].bytes[byte%4U]^=1U;
        }
        if (scenario==97U) { --tb.count; }
        trans_cb(&tb,trans_data);
        if (scenario>=29U && scenario<=97U) {
            assert(!observer.origin_anchor_mask && registrations==0U && read_calls==0U);goto done;
        }
        assert(observer.origin_anchor_mask==1U && registrations==1U);
        if (scenario==98U) {
            make_origin(&other,1U,B+0x1000U);trans_cb(&other,trans_data);
            assert(observer.disabled && observer.ambiguous && !strcmp(observer.stop,"origin_base_conflict"));goto done;
        }
        if (scenario==99U) { model[REG_X2].length=7U;execute_origin(&tb,0U,0x17cU);assert(observer.faults && !observer.origin_sequence);goto done; }
        if (scenario==100U) { execute_origin(&tb,0U,0x17dU);assert(observer.origin_skipped[0]==1U && !observer.origin_sequence);goto done; }
        if (scenario==101U) {
            for(unsigned int j=0;j<SITE_QUOTA+2U;++j){execute_origin(&tb,0U,0x17cU);}
            assert(observer.origin_records[0]==SITE_QUOTA && observer.origin_suppressed[0]==2U);goto done;
        }
        if (scenario==103U) {execute_origin(&tb,1U,0x17cU);assert(observer.disabled && !strcmp(observer.stop,"invalid_origin_context"));goto done;}
        if (scenario==104U) {model[REG_CPSR].value=1U;execute_origin(&tb,0U,0x17cU);assert(observer.faults && !observer.origin_sequence);goto done;}
        execute_origin(&tb,0U,0x17cU);assert(observer.origin_records[0]==1U);
        make_origin(&other,1U,B);trans_cb(&other,trans_data);execute_origin(&other,0U,0x17cU);
        assert(observer.origin_records[1]==1U && observer.origin_sequence==2U);
        make_body(&tb,B);trans_cb(&tb,trans_data);
        for(unsigned int site=0;site<3U;++site){execute(&tb,site,0);}
        assert(observer.sequence==3U && observer.observation_sequence==5U && !observer.faults);goto done;
    }
    make_body(&tb,B);
    if (scenario>=1U && scenario<=12U) { tb.insns[(scenario-1U)/4U].bytes[(scenario-1U)%4U]^=1U; }
    if (scenario==13U) { tb.count=2; }
    if (scenario==14U) { tb.insns[1].pc+=4U; }
    if (scenario==15U) { tb.insns[1].size=8; }
    if (scenario==16U) { tb.insns[1].copied=3; }
    trans_cb(&tb,trans_data);
    if (scenario>=1U && scenario<=16U) { assert(!observer.candidate_found && registrations==0 && read_calls==0);goto done; }
    assert(observer.candidate_found && registrations==3);
    if (scenario==17U) {
        make_body(&other,B+0x1000U);trans_cb(&other,trans_data);assert(observer.disabled && observer.ambiguous && !strcmp(observer.stop,"base_conflict"));goto done;
    }
    if (scenario==18U) {
        make_body(&other,B);other.insns[1].bytes[0]^=1;trans_cb(&other,trans_data);assert(observer.disabled && !strcmp(observer.stop,"anchor_changed"));goto done;
    }
    if (scenario==20U) { model[REG_X0].length=7; }
    if (scenario==21U) { model[REG_X0].ok=false; }
    if (scenario==26U) { model[REG_CPSR].value=1; }
    if (scenario==25U) { execute(&tb,0,1);assert(observer.disabled && !strcmp(observer.stop,"vcpu_limit"));goto done; }
    if (scenario==19U) { execute(&tb,1,0);assert(observer.disabled && !strcmp(observer.stop,"destination_base_mismatch"));goto done; }
    if (scenario==20U || scenario==21U || scenario==26U) {
        execute(&tb,0,0);assert(observer.faults && !observer.records[0]);goto done;
    }
    if (scenario==27U) {
        for (unsigned int j=0;j<SITE_QUOTA+2U;++j) { execute(&tb,0,0); }
        assert(observer.records[0]==SITE_QUOTA && observer.suppressed[0]==2U);goto done;
    }
    for (unsigned int site=0;site<3U;++site) { execute(&tb,site,0);assert(observer.records[site]==1); }
    assert(observer.sequence==3 && !observer.disabled && !observer.faults && observer.anchor_seen_mask==7);
done:
    exit_cb(exit_data);exit_cb(exit_data);assert(observer.closed && !observer.log && !observer.buffer);
    return 0;
}
