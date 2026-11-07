/* Only the three reviewed App EE imports may retain a pinned native forwarder. */
struct ee_native_export {const char *name;uintptr_t va,cached_va;unsigned char code[16];};
struct ee_native_contract {const char *path;size_t bytes;const char *sha256;unsigned count;const struct ee_native_export *exports;};
static int ee_code_identity(const char *path,size_t bytes,const char *sha256,uintptr_t base,uintptr_t va,const void *code) {
    Dl_info info={0};unsigned char actual[16];void *entry=(void *)(base+va);
    return identity(path,bytes,sha256)&&dladdr(entry,&info)&&(uintptr_t)info.dli_fbase==base&&
        info.dli_fname&&!strcmp(info.dli_fname,path)&&readmem((uintptr_t)entry,actual,sizeof actual)&&!memcmp(actual,code,sizeof actual);
}
static void *ee_slot_original(uintptr_t base,void *old,void *raw,unsigned plt0,const char *name,const struct ee_native_contract *native) {
    if(strcmp(name,"osal_get_msg_src")&&strcmp(name,"osal_msg_size")&&strcmp(name,"osal_free_msg"))return 0;
    if(old==raw)return raw;
    if(slot_matches(base,old,raw,plt0)) {
        if(!lookup)return 0;
        /* An App PLT slot has not resolved the global native interposer yet. */
        old=lookup(RTLD_DEFAULT,name);
        if(old==raw)return raw;
    }
    Dl_info info={0};if(!old||!native||!dladdr(old,&info)||!info.dli_sname||strcmp(info.dli_sname,name)||info.dli_saddr!=old)return 0;
    for(unsigned i=0;i<native->count;i++) {
        const struct ee_native_export *pin=native->exports+i;uintptr_t cached=0;
        if(!strcmp(pin->name,name)&&(uintptr_t)old==(uintptr_t)info.dli_fbase+pin->va&&
                ee_code_identity(native->path,native->bytes,native->sha256,(uintptr_t)info.dli_fbase,pin->va,pin->code)&&
                readmem((uintptr_t)info.dli_fbase+pin->cached_va,&cached,sizeof cached)&&cached==(uintptr_t)raw)return old;
    }
    return 0;
}
static void ee_got(uintptr_t base,unsigned offset,const char *name,void *wrapper,void **original,void *old,void *selected) {
    void **slot=(void *)(base+offset);
    if(!selected||*slot!=old)fatal("EE GOT changed after preflight");
    uintptr_t page=(uintptr_t)slot&~4095UL;if(mprotect((void *)page,4096,3))fatal("EE GOT writable");
    *original=selected;*slot=wrapper;
    emit(0,"GOT_ARMED","base=%#lx offset=%#x name=%s old=%p target=%p wrapper=%p",base,offset,name,old,selected,wrapper);
}
