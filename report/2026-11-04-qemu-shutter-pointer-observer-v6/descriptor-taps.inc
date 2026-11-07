/* SPDX-License-Identifier: MIT */
#define DESCRIPTOR_ENTRY UINT64_C(0x2767990)
static const unsigned char descriptor12[12]={0xa1,0xb7,0x02,0xd0,0x20,0x78,0x05,0xb9,0xc0,0x03,0x5f,0xd6};
static const char *const descriptor_names[3]={"descriptor_setter_entry","descriptor_store_pre","descriptor_ret_pre"};

static bool descriptor_base(uint64_t pc,uint64_t *base)
{
    if(pc<DESCRIPTOR_ENTRY || pc>LOW48_MAX-11U){return false;}
    *base=pc-DESCRIPTOR_ENTRY;
    return *base && !(*base&UINT64_C(0xfff)) && *base<=LOW48_MAX-UINT64_C(0x7e5d58b);
}

static void descriptor_exec(unsigned int vcpu,void *userdata)
{
    uint64_t packed=(uint64_t)(uintptr_t)userdata;
    unsigned int site=(unsigned int)(packed&UINT64_C(3));
    uint64_t pc=packed&LOW48_MAX&~UINT64_C(3),base,gdb_pc,x0,x1,lr,cpsr;
    char options[3][192];
    g_mutex_lock(&observer.lock);
    if(observer.closed || observer.disabled){goto out;}
    if(vcpu!=0U || site>=3U || packed&~LOW48_MAX || pc<site*4U ||
       !descriptor_base(pc-site*4U,&base) || !observer.descriptor_anchor_seen || base!=observer.descriptor_base){
        observer.disabled=true;observer.stop="invalid_descriptor_context";
        fault("reason=invalid_descriptor_context packed_raw=0x%016" PRIx64,packed);goto out;
    }
    if(observer.descriptor_records[site]==SITE_QUOTA){increment(&observer.descriptor_suppressed[site]);goto out;}
    if(!observer.regs_ready || !read_exact(REG_PC,descriptor_names[site],&gdb_pc) ||
       !read_exact(REG_X0,descriptor_names[site],&x0) || !read_exact(REG_X1,descriptor_names[site],&x1) ||
       !read_exact(REG_X30,descriptor_names[site],&lr) || !read_exact(REG_CPSR,descriptor_names[site],&cpsr)){goto out;}
    if((gdb_pc!=base+DESCRIPTOR_ENTRY && gdb_pc!=pc) ||
       (site && x1!=base+UINT64_C(0x7e5d000))){
        observer.disabled=true;observer.stop="descriptor_register_contract";
        fault("reason=descriptor_register_contract site=%s event_pc=0x%016" PRIx64
              " gdb_pc_raw=0x%016" PRIx64 " x1_raw=0x%016" PRIx64,descriptor_names[site],pc,gdb_pc,x1);goto out;
    }
    switch(cpsr&UINT64_C(0x1f)){
    case 0:case 4:case 5:case 8:case 9:case 12:case 13:break;
    default:fault("reason=invalid_descriptor_mode site=%s cpsr_raw=0x%08" PRIx64,descriptor_names[site],cpsr);goto out;
    }
    if(!optional(REG_SP,descriptor_names[site],"sp",options[0]) ||
       !optional(REG_TTBR0_EL1,descriptor_names[site],"ttbr0_el1",options[1]) ||
       !optional(REG_TPIDR_EL0,descriptor_names[site],"tpidr_el0",options[2])){goto out;}
    if(record("writer_descriptor","site=%s vcpu=0x0 ordinal=0x%x descriptor_sequence=0x%x observation_sequence=0x%x "
       "callback_phase=before_instruction event_pc=0x%016" PRIx64 " gdb_pc_raw=0x%016" PRIx64
       " candidate_base=0x%016" PRIx64 " anchor_length=0xc input_w0=0x%08" PRIx32
       " x0_raw=0x%016" PRIx64 " x1_raw=0x%016" PRIx64 " x30_raw=0x%016" PRIx64
       " expected_destination=0x%016" PRIx64 " cpsr_raw=0x%08" PRIx64 " cpsr_m=0x%02" PRIx64
       " context_mode=%s gdb_pc_read_length=0x8 gdb_pc_api_ok=0x1 "
       "x0_read_length=0x8 x0_api_ok=0x1 x1_read_length=0x8 x1_api_ok=0x1 "
       "x30_read_length=0x8 x30_api_ok=0x1 cpsr_read_length=0x4 cpsr_api_ok=0x1 api_ok=0x1 "
       "%s %s %s invocation_pairing_verified=0x0 store_retirement_verified=0x0 memory_readback_verified=0x0",
       descriptor_names[site],observer.descriptor_records[site]+1U,observer.descriptor_sequence+1U,
       observer.observation_sequence+1U,pc,gdb_pc,base,(uint32_t)x0,x0,x1,lr,base+UINT64_C(0x7e5d578),
       cpsr,cpsr&UINT64_C(0x1f),(cpsr&UINT64_C(0x1f))==0U?"EL0t":"other_aarch64",options[0],options[1],options[2])){
        ++observer.descriptor_records[site];++observer.descriptor_sequence;++observer.observation_sequence;
    }
out:g_mutex_unlock(&observer.lock);
}

static void descriptor_translate(struct qemu_plugin_tb *tb,size_t index,size_t count,uint64_t pc)
{
    uint64_t base;
    if(!descriptor_base(pc,&base) || count-index<3U){return;}
    for(size_t j=0;j<3U;++j){
        struct qemu_plugin_insn *insn=qemu_plugin_tb_get_insn(tb,index+j);unsigned char bytes[4]={0};
        if(qemu_plugin_insn_size(insn)!=4U || qemu_plugin_insn_vaddr(insn)!=pc+4U*j ||
           qemu_plugin_insn_data(insn,bytes,sizeof(bytes))!=sizeof(bytes) || memcmp(bytes,descriptor12+4U*j,sizeof(bytes))){
            if(observer.descriptor_anchor_seen && observer.descriptor_base==base){
                observer.disabled=true;observer.stop="descriptor_anchor_changed";
                fault("reason=descriptor_anchor_changed translated_pc=0x%016" PRIx64,pc);
            }
            return;
        }
    }
    if((observer.descriptor_anchor_seen && observer.descriptor_base!=base) ||
       (observer.candidate_found && observer.base!=base) || (observer.origin_base && observer.origin_base!=base) ||
       (observer.record_anchor_seen && observer.record_base!=base) ||
        (observer.pointer_anchor_mask && observer.pointer_base!=base)){
        observer.disabled=true;observer.ambiguous=true;observer.stop="descriptor_base_conflict";observer.conflicting_base=base;
        fault("reason=descriptor_base_conflict translated_pc=0x%016" PRIx64,pc);return;
    }
    observer.descriptor_base=base;observer.descriptor_anchor_seen=true;
    for(unsigned int site=0;site<3U;++site){
        struct qemu_plugin_insn *insn=qemu_plugin_tb_get_insn(tb,index+site);
        qemu_plugin_register_vcpu_insn_exec_cb(insn,descriptor_exec,QEMU_PLUGIN_CB_R_REGS,
            (void *)(uintptr_t)(pc+4U*site+site));
    }
}
