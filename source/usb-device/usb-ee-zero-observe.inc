/* Passive 2.01 EE observation: no publication API; opaque objects stay in registers. */
#include <time.h>
#include "usb-ee-native-got.h"
#ifndef USB_OBSERVE_HOST_TEST
#include USB_EE_NATIVE_INPUT
#endif
#define EE_QUEUE UINT32_C(0x80020002)
static uintptr_t ee_uipc_base;
static unsigned ee_records,ee_essential,ee_capped,ee_first_wait,ee_installed;
static unsigned ee_console_records,ee_console_essential,ee_foreign_queue_calls;
static int32_t (*ee_real_queue)(uint32_t,uintptr_t,uintptr_t,uintptr_t);
static int32_t (*ee_real_recv)(uint32_t,uintptr_t,int32_t);
static int32_t (*ee_real_free)(uint32_t,uintptr_t),(*ee_real_size)(uintptr_t);
static uint32_t (*ee_real_source)(uintptr_t);
struct ee_pair {uintptr_t x0,x1;};
static struct ee_pair (*ee_real_register)(uintptr_t,uintptr_t);
static uintptr_t (*ee_real_wait)(uintptr_t);
/* The preload contract resolves this TLS slot before native AP threads exist. */
static __thread struct {uintptr_t map,key,caller;struct ee_pair result;unsigned valid;} ee_registration __attribute__((tls_model("initial-exec")));
static __thread struct {uintptr_t msg;uint32_t source;int32_t size;unsigned have_source,have_size;} ee_received __attribute__((tls_model("initial-exec")));

#ifdef USB_EE_NORMAL_COLD
#define EE_ESSENTIAL_LIMIT 32u
#else
#define EE_ESSENTIAL_LIMIT 16u
#endif
/* Separate bounded log budget keeps USB trace saturation from hiding the first wait. */
static int ee_emit(unsigned essential,const char *event,const char *format,...) {
    int saved=errno;char line[1024];struct timespec ts={0};
    unsigned n=__atomic_fetch_add(essential?&ee_essential:&ee_records,1,__ATOMIC_RELAXED);
    if(n>=(essential?EE_ESSENTIAL_LIMIT:384u)) {
        if(!__atomic_exchange_n(&ee_capped,1,__ATOMIC_RELAXED)&&logfd>=0)
            syscall(SYS_write,logfd,"USB_EE CAP bounded=1\n",sizeof("USB_EE CAP bounded=1\n")-1);
        errno=saved;return 0;
    }
    int clock_ok=clock_gettime(CLOCK_MONOTONIC,&ts)==0;
    int prefix=snprintf(line,sizeof line,"USB_EE %s tid=%ld mono=%ld.%09ld clock_ok=%d pid=%ld ",event,syscall(SYS_gettid),ts.tv_sec,ts.tv_nsec,clock_ok,(long)getpid());
    va_list args;va_start(args,format);vsnprintf(line+prefix,sizeof line-(size_t)prefix-2,format,args);va_end(args);
    size_t size=strlen(line);line[size++]='\n';
    int acknowledged=logfd>=0 && syscall(SYS_write,logfd,line,size)==(ssize_t)size;
#if defined(USB_EE_ZERO_OBSERVER) || defined(USB_EE_NORMAL_COLD)
    /* Eight detail records cannot consume the queue/first-wait/functional reserve. */
    if(essential||!strcmp(event,"RECV_ENTER")||!strcmp(event,"RECV_RETURN")||!strcmp(event,"SOURCE")||!strcmp(event,"SIZE")||!strcmp(event,"FREE_ENTER")||!strcmp(event,"FREE_RETURN")||!strcmp(event,"WAIT_RETURN")) {
        unsigned limit=essential?EE_ESSENTIAL_LIMIT-8u:8u;
        unsigned count=__atomic_fetch_add(essential?&ee_console_essential:&ee_console_records,1,__ATOMIC_RELAXED);
        if(count<limit)syscall(SYS_write,STDERR_FILENO,line,size);
    }
#endif
    errno=saved;return acknowledged;
}
static int32_t ee_queue(uint32_t id,uintptr_t handle,uintptr_t callback,uintptr_t argument) {
    int saved=errno;uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    unsigned target=id==EE_QUEUE,observe=target;
    if(!target){
        unsigned n=__atomic_load_n(&ee_foreign_queue_calls,__ATOMIC_RELAXED);
        while(n<8u&&!__atomic_compare_exchange_n(&ee_foreign_queue_calls,&n,n+1,0,__ATOMIC_RELAXED,__ATOMIC_RELAXED)){}
        observe=n<8u; /* Saturation keeps foreign diagnostics bounded even after counter wrap. */
    }
    if(observe)ee_emit(target,"QUEUE_ENTER","queue=%#x handle_out=%#lx callback=%#lx context=%#lx caller=%#lx",id,handle,callback,argument,caller);
    errno=saved;int32_t r=ee_real_queue(id,handle,callback,argument);int e=errno;
    if(observe){uintptr_t value=0;int ok=r==0&&readmem(handle,&value,sizeof value);
        ee_emit(target,"QUEUE_RETURN","queue=%#x handle_out=%#lx handle=%#lx handle_read=%d callback=%#lx context=%#lx caller=%#lx rc=%d errno=%d",id,handle,value,ok,callback,argument,caller,r,e);
#ifdef USB_EE_NORMAL_COLD
        if(target)ee_cold_queue(value,callback,argument,r==0&&(!handle||ok));
#endif
    }
    errno=e;return r;
}
static int32_t ee_recv(uint32_t id,uintptr_t output,int32_t timeout) {
    int saved=errno;uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    if(id==EE_QUEUE){memset(&ee_received,0,sizeof ee_received);ee_emit(0,"RECV_ENTER","queue=%#x output=%#lx timeout=%d caller=%#lx",id,output,timeout,caller);
#ifdef USB_EE_NORMAL_COLD
        ee_cold_recv_enter();
#endif
    }
    errno=saved;int32_t r=ee_real_recv(id,output,timeout);int e=errno;
    if(id==EE_QUEUE){uintptr_t msg=0;int ok=r==0&&readmem(output,&msg,sizeof msg);if(ok)ee_received.msg=msg;
#ifdef USB_EE_NORMAL_COLD
        if(ok)ee_cold_recv_return(msg,r);
#endif
        ee_emit(0,"RECV_RETURN","queue=%#x output=%#lx message=%#lx message_read=%d caller=%#lx rc=%d errno=%d",id,output,msg,ok,caller,r,e);}
    errno=e;return r;
}
static uint32_t ee_source(uintptr_t msg) {
    uint32_t r=ee_real_source(msg);int e=errno;
    if(msg&&msg==ee_received.msg){ee_received.source=r;ee_received.have_source=1;ee_emit(0,"SOURCE","queue=%#x message=%#lx source=%#x caller=%p",EE_QUEUE,msg,r,__builtin_return_address(0));}
#ifdef USB_EE_NORMAL_COLD
    ee_cold_metadata(msg,0,r);ee_cold_receive(msg);
#endif
    errno=e;return r;
}
static int ee_copy12(uintptr_t msg,unsigned char out[12]) {
    return msg&&msg==ee_received.msg&&ee_received.have_source&&ee_received.have_size&&ee_received.size>=12&&readmem(msg,out,12);
}
static int32_t ee_size(uintptr_t msg) {
    int32_t r=ee_real_size(msg);int e=errno;
    if(msg&&msg==ee_received.msg){
        ee_received.size=r;ee_received.have_size=1;unsigned char bytes[12];char hex[25]="";int ok=ee_copy12(msg,bytes);
        if(ok)for(unsigned i=0;i<12;i++)snprintf(hex+2*i,3,"%02x",bytes[i]);
        ee_emit(0,"SIZE","queue=%#x message=%#lx source=%#x source_known=%u size=%d copy12=%d raw=%s caller=%p",EE_QUEUE,msg,ee_received.source,ee_received.have_source,r,ok,ok?hex:"unavailable",__builtin_return_address(0));
    }
#ifdef USB_EE_NORMAL_COLD
    ee_cold_metadata(msg,1,(uint32_t)r);ee_cold_receive(msg);
#endif
    errno=e;return r;
}
static int32_t ee_free(uint32_t owner,uintptr_t msg) {
    int saved=errno;uintptr_t caller=(uintptr_t)__builtin_return_address(0);
    unsigned matched=msg&&msg==ee_received.msg,relevant=owner==EE_QUEUE||matched;
    __typeof__(ee_received) previous=ee_received;
#ifdef USB_RESOURCE_OBSERVE
    struct resource_rpc_ticket rpc_ticket=resource_rpc_free_enter(owner,msg,caller,app_base);
#endif
    if(relevant)ee_emit(0,"FREE_ENTER","owner=%#x message=%#lx recv_match=%u source=%#x source_known=%u size=%d size_known=%u caller=%#lx",owner,msg,matched,previous.source,matched&&previous.have_source,previous.size,matched&&previous.have_size,caller);
#ifdef USB_EE_NORMAL_COLD
    struct ee_cold_ticket ticket=ee_cold_free_enter(owner,msg);
#endif
    errno=saved;int32_t r=ee_real_free(owner,msg);int e=errno;
#ifdef USB_RESOURCE_OBSERVE
    resource_rpc_free_return(rpc_ticket,r,e);
#endif
    if(relevant)ee_emit(0,"FREE_RETURN","owner=%#x message=%#lx recv_match=%u caller=%#lx rc=%d errno=%d",owner,msg,matched,caller,r,e);
#ifdef USB_EE_NORMAL_COLD
    ee_cold_free(ticket,r);
#endif
    if(matched)memset(&ee_received,0,sizeof ee_received); /* Even failed free ends this observation lease. */
    errno=e;return r;
}
static void ee_remember_register(uintptr_t map,uintptr_t key,uintptr_t caller,struct ee_pair result) {
    if(caller==app_base+0x35492bc){ee_registration.map=map;ee_registration.key=key;ee_registration.caller=caller;ee_registration.result=result;ee_registration.valid=1;}
}
static struct ee_pair ee_register(uintptr_t map,uintptr_t key) {
    /* The original caller holds its mutex here: stores only, no reads, logging or syscalls. */
    struct ee_pair r=ee_real_register(map,key);
    ee_remember_register(map,key,(uintptr_t)__builtin_return_address(0),r);return r;
}
static int ee_wait_enter(uintptr_t caller,uintptr_t future) {
    if(caller!=app_base+0x35492cc)return 0;
    unsigned first=!__atomic_exchange_n(&ee_first_wait,1,__ATOMIC_RELAXED);
#ifdef USB_EE_NORMAL_COLD
    ee_cold_wait(future);
#endif
    if(ee_registration.valid){ee_emit(first,"PROMISE_REGISTER","id=0x20a3 id_source=guarded_caller map=%#lx key=%#lx caller=%#lx return_x0=%#lx return_x1=%#lx deferred_until_unlock=1",ee_registration.map,ee_registration.key,ee_registration.caller,ee_registration.result.x0,ee_registration.result.x1);ee_registration.valid=0;}
    ee_emit(first,"WAIT_ENTER","id=0x20a3 future=%#lx caller=%#lx first=%u after_original_unlock=1",future,caller,first);return 1;
}
static uintptr_t ee_wait(uintptr_t future) {
    int saved=errno;uintptr_t caller=(uintptr_t)__builtin_return_address(0);int relevant=ee_wait_enter(caller,future);errno=saved;
    uintptr_t r=ee_real_wait(future);int e=errno;
#ifdef USB_EE_NORMAL_COLD
    if(relevant)ee_cold_wait_return(future);
#endif
    if(relevant)ee_emit(0,"WAIT_RETURN","id=0x20a3 future=%#lx caller=%#lx return_x0=%#lx errno=%d",future,caller,r,e);
    errno=e;return r;
}
#ifndef USB_OBSERVE_HOST_TEST
static void ee_guard_api(const char *kind,const char *name,uintptr_t slot,uintptr_t expected,uintptr_t actual) {
    Dl_info info={0};char reason[256];int mapped=actual&&dladdr((void *)actual,&info);
    snprintf(reason,sizeof reason,"EE %s api=%s slot=%#lx expected=%#lx actual=%#lx path=%s",kind,name,slot,expected,actual,mapped&&info.dli_fname?info.dli_fname:"unmapped");fatal(reason);
}
static void ee_install(uintptr_t base) {
    const char *path="/usr/lib/libosal_uipc.so";Dl_info info;
    void *target=lookup(RTLD_NEXT,"osal_reg_msg_queue_cb");
    if(!target)ee_guard_api("lookup","osal_reg_msg_queue_cb",0,0,0);
    if(!dladdr(target,&info)||strcmp(info.dli_fname,path))ee_guard_api("lookup-path","osal_reg_msg_queue_cb expected=/usr/lib/libosal_uipc.so+6b78",0,0,(uintptr_t)target);
    uintptr_t expected_queue=(uintptr_t)info.dli_fbase+0x6b78;
    if((uintptr_t)target!=expected_queue)ee_guard_api("lookup-entry","osal_reg_msg_queue_cb",0,expected_queue,(uintptr_t)target);
    if(!identity(path,43752,"09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3"))fatal("EE UIPC original path/size/SHA256");
    ee_uipc_base=(uintptr_t)info.dli_fbase;
    struct entry queue_entries[]={
        {0x6b78,{0xa9ac7bfd,0xf100005f,0xfa401824,0x910003fd},ee_queue,(void **)&ee_real_queue},
        {0x6468,{0xa9a77bfd,0x72003805,0x910003fd,0xa90153f3},ee_recv,(void **)&ee_real_recv}};
    struct {unsigned slot,offset;uint32_t bytes[4];const char *name;void *wrapper;void **original;} imports[]={
        {0x5bc2398,0x7e28,{0xb85f4000,0xd65f03c0,0xa9ba7bfd,0x910003fd},"osal_get_msg_src",ee_source,(void **)&ee_real_source},
        {0x5bc1bc0,0x7e08,{0xb4000060,0xb85f8000,0xd65f03c0,0x12807fe0},"osal_msg_size",ee_size,(void **)&ee_real_size},
        {0x5bc29b0,0x6970,{0x72003804,0x54000121,0xf0000080,0xf947cc00},"osal_free_msg",ee_free,(void **)&ee_real_free}};
    /* Verify every original callee and jump slot before the first EE patch. */
    for(unsigned i=0;i<sizeof queue_entries/sizeof *queue_entries;i++)if(memcmp((void *)(ee_uipc_base+queue_entries[i].offset),queue_entries[i].bytes,16))fatal("EE UIPC entry bytes");
    void *old_slots[3],*originals[3];
    for(unsigned i=0;i<sizeof imports/sizeof *imports;i++){
        void *expected=(void *)(ee_uipc_base+imports[i].offset);
        void *actual=lookup(RTLD_NEXT,imports[i].name),*slot=*(void **)(base+imports[i].slot);
        if(actual!=expected)ee_guard_api("lookup",imports[i].name,base+imports[i].slot,(uintptr_t)expected,(uintptr_t)actual);
        if(!ee_code_identity(path,43752,"09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3",ee_uipc_base,imports[i].offset,imports[i].bytes)){char name[96];snprintf(name,sizeof name,"%s word_expected=%08x word_actual=%08x",imports[i].name,imports[i].bytes[0],word((uintptr_t)expected));ee_guard_api("bytes",name,base+imports[i].slot,(uintptr_t)expected,(uintptr_t)actual);}
        old_slots[i]=slot;originals[i]=ee_slot_original(base,slot,expected,0x165cfd0,imports[i].name,&ee_native_pins);
        if(!originals[i])ee_guard_api("GOT-slot",imports[i].name,base+imports[i].slot,(uintptr_t)expected,(uintptr_t)slot);
    }
    struct entry promises[]={
        {0x3531118,{0xa9bc7bfd,0x910003fd,0xa90153f3,0xaa0103f4},ee_register,(void **)&ee_real_register},
        {0x3531300,{0xa9be7bfd,0x910003fd,0xf9000bf3,0xaa0003f3},ee_wait,(void **)&ee_real_wait}};
    for(unsigned i=0;i<sizeof promises/sizeof *promises;i++)if(memcmp((void *)(base+promises[i].offset),promises[i].bytes,16))fatal("EE promise entry bytes");
#ifdef USB_EE_NORMAL_COLD
    ee_cold_check(base);
#endif
    for(unsigned i=0;i<sizeof imports/sizeof *imports;i++) {
        ee_got(base,imports[i].slot,imports[i].name,imports[i].wrapper,imports[i].original,old_slots[i],originals[i]);
        void *raw=(void *)(ee_uipc_base+imports[i].offset);
        /* A non-raw selection already proved the exact native code, SHA and cached raw pointer. */
        if(!strcmp(imports[i].name,"osal_free_msg")&&originals[i]!=raw)
            ee_emit(1,"GOT_ARMED","slot=%#lx name=%s old=%p chosen=%p raw=%p verified_cached_pointer=%p native_sha256=%s",base+imports[i].slot,imports[i].name,old_slots[i],originals[i],raw,raw,ee_native_pins.sha256);
    }
    for(unsigned i=0;i<sizeof promises/sizeof *promises;i++)entry_install(base,promises+i);
    for(unsigned i=0;i<sizeof queue_entries/sizeof *queue_entries;i++)entry_install(ee_uipc_base,queue_entries+i);
#ifdef USB_EE_NORMAL_COLD
    ee_cold_install(base);
#endif
    ee_installed=1;
}
static void ee_preinit(void) {
    if(!ee_installed)fatal("EE taps absent before Init resolution");
#ifdef USB_EE_NORMAL_COLD
    ee_emit(1,"PREINIT","app_base=%#lx uipc_base=%#lx installed=8 ee_can_publish=0 functional_model=1 mode=ee-normal-wake-cold-functional-v1 native_allocation_log_commit_required=1 native_allocation_log_commit_version=1",app_base,ee_uipc_base);
#else
    ee_emit(1,"PREINIT","app_base=%#lx uipc_base=%#lx installed=7 ee_can_publish=0 mode=ee-zero-publication-passive-v1",app_base,ee_uipc_base);
#endif
}
#endif
