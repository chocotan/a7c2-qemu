/* SPDX-License-Identifier: MIT */
static const char *const pointer_names[3]={"saved_descriptor_store_pre","generic_descriptor_mirror_pre","publish_descriptor_mirror_pre"};
static const uint64_t pointer_starts[3]={UINT64_C(0x2aa31d8),UINT64_C(0x267b6d0),UINT64_C(0x2aeffdc)};
static const uint64_t pointer_stores[3]={UINT64_C(0x2aa31dc),UINT64_C(0x267b6d8),UINT64_C(0x2aeffe4)};
static const enum reg_index pointer_regs[3]={REG_X1,REG_X20,REG_X19};
static const unsigned int pointer_regnums[3]={1U,20U,19U};
static const unsigned char pointer_bytes[3][52]={
 {0x61,0xa2,0x40,0xb9,0x01,0x00,0x00,0xb9,0xf2,0xef,0xf6,0x97},
 {0x60,0x06,0x40,0xf9,0x00,0x04,0x40,0xf9,0x14,0x00,0x00,0xb9,0x20,0x00,0x80,0x52,0x60,0x56,0x00,0x39,0x60,0x02,0x40,0xf9,0x14,0x00,0x00,0xb9,0x20,0x00,0x80,0x52,0x60,0x52,0x00,0x39,0xe0,0x03,0x13,0xaa,0xf3,0x53,0x41,0xa9,0xfd,0x7b,0xc3,0xa8,0xc0,0x03,0x5f,0xd6},
 {0xa0,0x2f,0x40,0xf9,0x00,0x04,0x40,0xf9,0x13,0x00,0x00,0xb9,0x20,0x00,0x80,0x52,0xa0,0x97,0x01,0x39,0xa0,0x2b,0x40,0xf9,0x13,0x00,0x00,0xb9,0x20,0x00,0x80,0x52,0xa0,0x93,0x01,0x39}
};
static const size_t pointer_lengths[3]={12U,52U,36U};
static bool pointer_derive(uint64_t pc,unsigned int site,uint64_t *base)
{
    if(site>=3U || pc<pointer_starts[site] || pc>LOW48_MAX-pointer_lengths[site]+1U){return false;}
    *base=pc-pointer_starts[site];
    return *base && !(*base&UINT64_C(0xfff)) && *base<=LOW48_MAX-UINT64_C(0x7e5d58b);
}
static void pointer_exec(unsigned int vcpu,void *userdata)
{
    uint64_t packed=(uint64_t)(uintptr_t)userdata;
    unsigned int site=(unsigned int)(packed&UINT64_C(3));
    uint64_t pc=packed&LOW48_MAX&~UINT64_C(3),base,rawpc,destination,value,lr,cpsr;
    char options[3][192];
    g_mutex_lock(&observer.lock);
    if(observer.closed || observer.disabled){goto out;}
    if(site>=3U || vcpu!=0U || (packed&~LOW48_MAX) || pc<pointer_stores[site] ||
       !pointer_derive(pc-(pointer_stores[site]-pointer_starts[site]),site,&base) ||
       !(observer.pointer_anchor_mask&(1U<<site)) || base!=observer.pointer_base ||
       (site>0U && (!(observer.pointer_guard_mask&(1U<<site)) || observer.pointer_guard_base!=base))){
        observer.disabled=true;observer.stop="invalid_pointer_context";
        fault("reason=invalid_pointer_context packed_raw=0x%016" PRIx64,packed);goto out;
    }
    if(!observer.regs_ready || !read_exact(REG_PC,pointer_names[site],&rawpc) ||
       !read_exact(REG_X0,pointer_names[site],&destination)){goto out;}
    if(rawpc!=pc && rawpc!=base+pointer_starts[site]){
        observer.disabled=true;observer.stop="pointer_register_contract";
        fault("reason=pointer_register_contract site=%s event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64,
              pointer_names[site],pc,rawpc);goto out;
    }
    if(destination!=base+UINT64_C(0x7e5d578)){increment(&observer.pointer_filtered[site]);goto out;}
    if(observer.pointer_records[site]==SITE_QUOTA){increment(&observer.pointer_suppressed[site]);goto out;}
    if(!read_exact(pointer_regs[site],pointer_names[site],&value) ||
       !read_exact(REG_X30,pointer_names[site],&lr) || !read_exact(REG_CPSR,pointer_names[site],&cpsr)){goto out;}
    switch(cpsr&UINT64_C(0x1f)){
    case 0:case 4:case 5:case 8:case 9:case 12:case 13:break;
    default:fault("reason=invalid_pointer_mode site=%s cpsr_raw=0x%08" PRIx64,pointer_names[site],cpsr);goto out;
    }
    if(!optional(REG_SP,pointer_names[site],"sp",options[0]) ||
       !optional(REG_TTBR0_EL1,pointer_names[site],"ttbr0_el1",options[1]) ||
       !optional(REG_TPIDR_EL0,pointer_names[site],"tpidr_el0",options[2])){goto out;}
    if(record("writer_pointer","site=%s vcpu=0x0 ordinal=0x%x pointer_sequence=0x%x observation_sequence=0x%x "
       "callback_phase=before_instruction event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64
       " candidate_base=0x%016" PRIx64 " anchor_length=0x%zx anchor_parts=0x%x value_register=0x%x value_u32=0x%08" PRIx32
       " value_raw=0x%016" PRIx64 " x0_raw=0x%016" PRIx64 " x30_raw=0x%016" PRIx64
       " expected_destination=0x%016" PRIx64 " cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64
       " context_mode=%s gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 x0_read_length=0x8 x0_api_ok=0x1 "
       "value_read_length=0x8 value_api_ok=0x1 x30_read_length=0x8 x30_api_ok=0x1 "
       "cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1 %s %s %s "
       "invocation_pairing_verified=0x0 store_retirement_verified=0x0 memory_readback_verified=0x0",
       pointer_names[site],observer.pointer_records[site]+1U,observer.pointer_sequence+1U,
       observer.observation_sequence+1U,pc,rawpc,base,pointer_lengths[site]+(site>0U?4U:0U),site>0U?2U:1U,pointer_regnums[site],
       (uint32_t)value,value,destination,lr,base+UINT64_C(0x7e5d578),cpsr,cpsr&UINT64_C(0x1f),
       (cpsr&UINT64_C(0x1f))==0U?"EL0t":"other_aarch64",options[0],options[1],options[2])){
        ++observer.pointer_records[site];++observer.pointer_sequence;++observer.observation_sequence;
    }
out:g_mutex_unlock(&observer.lock);
}
static void pointer_generic_guard_translate(struct qemu_plugin_tb *tb,size_t index,uint64_t pc)
{
    static const uint64_t offsets[3]={0,UINT64_C(0x267b6cc),UINT64_C(0x2aeffd8)};
    static const unsigned char words[3][4]={{0},{0x77,0x1e,0x40,0x94},{0x34,0x4c,0x2e,0x94}};
    for(unsigned int site=1U;site<3U;++site){
        if(pc<offsets[site]){continue;}
        uint64_t base=pc-offsets[site];unsigned char bytes[4]={0};
        if(!base || (base&UINT64_C(0xfff)) || base>LOW48_MAX-UINT64_C(0x7e5d58b)){continue;}
        struct qemu_plugin_insn *insn=qemu_plugin_tb_get_insn(tb,index);
        if(qemu_plugin_insn_size(insn)!=4U || qemu_plugin_insn_data(insn,bytes,4U)!=4U || memcmp(bytes,words[site],4U)){
            if((observer.pointer_guard_mask&(1U<<site)) && observer.pointer_guard_base==base){
                observer.disabled=true;observer.stop="pointer_generic_guard_changed";
                fault("reason=pointer_generic_guard_changed translated_pc=0x%016" PRIx64,pc);return;
            }
            continue;
        }
        if((observer.pointer_guard_mask && observer.pointer_guard_base!=base) ||
           (observer.pointer_anchor_mask && observer.pointer_base!=base) ||
           (observer.candidate_found && observer.base!=base) || (observer.origin_base && observer.origin_base!=base) ||
           (observer.record_anchor_seen && observer.record_base!=base) ||
           (observer.descriptor_anchor_seen && observer.descriptor_base!=base)){
            observer.disabled=true;observer.ambiguous=true;observer.stop="pointer_generic_guard_base_conflict";observer.conflicting_base=base;
            fault("reason=pointer_generic_guard_base_conflict translated_pc=0x%016" PRIx64,pc);return;
        }
        observer.pointer_guard_mask|=1U<<site;observer.pointer_guard_base=base;
    }
}
static void pointer_translate(struct qemu_plugin_tb *tb,size_t index,size_t count,uint64_t pc)
{
    for(unsigned int site=0;site<3U;++site){
        uint64_t base;size_t words=pointer_lengths[site]/4U;
        if(!pointer_derive(pc,site,&base) || count-index<words){continue;}
        bool match=true;
        for(size_t j=0;j<words;++j){
            struct qemu_plugin_insn *insn=qemu_plugin_tb_get_insn(tb,index+j);unsigned char bytes[4]={0};
            if(qemu_plugin_insn_size(insn)!=4U || qemu_plugin_insn_vaddr(insn)!=pc+4U*j ||
               qemu_plugin_insn_data(insn,bytes,sizeof(bytes))!=sizeof(bytes) ||
               memcmp(bytes,pointer_bytes[site]+4U*j,sizeof(bytes))){match=false;break;}
        }
        if(site>0U && (!(observer.pointer_guard_mask&(1U<<site)) || observer.pointer_guard_base!=base)){continue;}
        if(!match){
            if((observer.pointer_anchor_mask&(1U<<site)) && observer.pointer_base==base){
                observer.disabled=true;observer.stop="pointer_anchor_changed";
                fault("reason=pointer_anchor_changed translated_pc=0x%016" PRIx64,pc);return;
            }
            continue;
        }
        if((observer.pointer_anchor_mask && observer.pointer_base!=base) ||
           (observer.pointer_guard_mask && observer.pointer_guard_base!=base) ||
           (observer.candidate_found && observer.base!=base) || (observer.origin_base && observer.origin_base!=base) ||
           (observer.record_anchor_seen && observer.record_base!=base) ||
           (observer.descriptor_anchor_seen && observer.descriptor_base!=base)){
            observer.disabled=true;observer.ambiguous=true;observer.stop="pointer_base_conflict";observer.conflicting_base=base;
            fault("reason=pointer_base_conflict translated_pc=0x%016" PRIx64,pc);return;
        }
        observer.pointer_base=base;observer.pointer_anchor_mask|=1U<<site;
        qemu_plugin_register_vcpu_insn_exec_cb(qemu_plugin_tb_get_insn(tb,index+(pointer_stores[site]-pointer_starts[site])/4U),
            pointer_exec,QEMU_PLUGIN_CB_R_REGS,(void *)(uintptr_t)(base+pointer_stores[site]+site));
    }
}
