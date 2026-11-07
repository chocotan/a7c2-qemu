/* Explicit functional bridge; native publication stays in this include. */
#include <pthread.h>
/* The Sony 2.25 libc exports this default symbol; new headers redirect sscanf to C23. */
extern int ee_cold_legacy_sscanf(const char *,const char *,...) __asm__("__isoc99_sscanf");
#ifndef USB_EE_NORMAL_COLD_INPUT
#error "Functional EE requires a hash-bound private input header"
#endif
#include USB_EE_NORMAL_COLD_INPUT
#define EE_COLD_MODE "ee-normal-wake-cold-functional-v1"
#ifndef EE_COLD_DIAGNOSTICS
#define EE_COLD_DIAGNOSTICS 0
#endif
#if EE_COLD_DIAGNOSTICS != 0 && EE_COLD_DIAGNOSTICS != 1
#error "EE diagnostics must be a typed boolean"
#endif
#if EE_COLD_DIAGNOSTICS
/* Four classes, one attempt each; no functional/essential budget is consumed. */
static unsigned ee_diag_seen,ee_diag_cap,ee_diag_write_failures;
static int ee_diag_claim(unsigned kind) {
    unsigned bit=1u<<kind;
    if(__atomic_fetch_or(&ee_diag_seen,bit,__ATOMIC_RELAXED)&bit){__atomic_fetch_or(&ee_diag_cap,bit,__ATOMIC_RELAXED);return 0;}
    return 1;
}
static void ee_diag_emit(const char *event,const char *format,...) {
    int saved=errno;char line[1024];
    int prefix=snprintf(line,sizeof line,"USB_EE_DIAG %s pid=%ld tid=%ld write_failures=%u cap_mask=%u ",event,(long)getpid(),syscall(SYS_gettid),__atomic_load_n(&ee_diag_write_failures,__ATOMIC_RELAXED),__atomic_load_n(&ee_diag_cap,__ATOMIC_RELAXED));
    va_list args;va_start(args,format);int n=vsnprintf(line+prefix,sizeof line-(size_t)prefix-1,format,args);va_end(args);
    if(n<0||(size_t)n>=sizeof line-(size_t)prefix-1||logfd<0)__atomic_fetch_add(&ee_diag_write_failures,1,__ATOMIC_RELAXED);
    else {size_t size=(size_t)prefix+(size_t)n;line[size++]='\n';if(syscall(SYS_write,logfd,line,size)!=(ssize_t)size)__atomic_fetch_add(&ee_diag_write_failures,1,__ATOMIC_RELAXED);}
    errno=saved;
}
/* Same guarded pread as readmem, with errno captured before its restoration. */
static int ee_diag_readmem(uintptr_t p,void *out,size_t n,ssize_t *rc,int *error) {
    int saved=errno;*rc=-2;*error=-1;
    if(p&&memfd>=0){*rc=pread(memfd,out,n,(off_t)p);*error=errno;}
    errno=saved;return *rc==(ssize_t)n;
}
#endif
#ifndef EE_COLD_ADMISSION_SOURCE
#define EE_COLD_ADMISSION_SOURCE EE_NWC_CALLBACK
#endif
static struct ee_nwc *ee_cold_service;
static pthread_mutex_t ee_cold_lock=PTHREAD_MUTEX_INITIALIZER;
static uintptr_t ee_cold_consumer,ee_cold_handle,ee_cold_callback,ee_cold_context;
static uint64_t ee_cold_event,ee_cold_registration_event;
static unsigned ee_cold_queue_known,ee_cold_attempted,ee_cold_endpoint_conflict,ee_cold_failed;
static struct ee_nwc_init ee_cold_init;
static unsigned ee_cold_init_bound,ee_cold_abi_verified;
static pid_t ee_cold_process;
static unsigned (*ee_cold_native_size)(void *);
static unsigned (*ee_cold_native_source)(void *);
static struct ee_nwc_prime ee_cold_prime;
static struct ee_cold_slot ee_cold_slots[8];
static struct full_imaging_io ee_cold_io;
static int (*ee_cold_native_allocate)(unsigned,void **,unsigned,unsigned);
static int (*ee_cold_native_send)(unsigned,void *);
static uintptr_t (*ee_cold_real_reader)(uintptr_t,uintptr_t);
static __thread struct {unsigned active;uintptr_t promise;} ee_cold_reading __attribute__((tls_model("initial-exec")));
/* No TLS free lease: the receiver and free actor are independent original threads. */
static const char *ee_cold_source_class(void) { return EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT?"kerneldefault":"callback"; }
#if EE_COLD_DIAGNOSTICS
static const char *ee_cold_first_fault_site,*ee_cold_resource_fault;
static unsigned ee_cold_bound_diff;
static struct ee_cold_init_failure {
    unsigned known,stable_diff;
    const char *stage;
    ssize_t read_rc,read2_rc;
    int read_error,read2_error,stage_error;
} ee_cold_last_init_failure;
#define ee_cold_fail_locked(reason) ee_cold_fail_at_locked((reason),__func__)
static void ee_cold_fail_at_locked(int reason,const char *site) {
    if(!ee_cold_failed)ee_cold_first_fault_site=site;
#else
static void ee_cold_fail_locked(int reason) {
#endif
    if(!ee_cold_failed)ee_cold_failed=(unsigned)reason;
    ee_cold_endpoint_conflict=1;
    struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);
    if(s)ee_nwc_fail(s,reason);
}
static void ee_cold_record(const char *event,int rc) {
    struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);
    struct ee_nwc_snapshot snap={0};if(s)ee_nwc_snapshot(s,&snap);
    char wire[25]="";static const char hex[]="0123456789abcdef";
    if(snap.received)for(unsigned i=0;i<12;i++){wire[2*i]=hex[snap.receive_observed.lease.wire[i]>>4];wire[2*i+1]=hex[snap.receive_observed.lease.wire[i]&15];}
    ee_emit(1,event,"mode=%s source_class=%s generation=%llu rc=%d attempted=%u allocated=%u send_called=%u send_returned=%u send_rc=%d received=%u reader=%u output=%u free=%u free_rc=%d retired=%u pending=%u fault=%u strict_can_publish=%u functional_model=1 message=%#lx current=%u,%u reason=%u raw=%u actual_wire=%s actual_source=%#x actual_bytes=%u actual_consumer=%#lx free_owner=%#x free_actor_tid=%#lx owned_copy=%u wait_returned=%u message_generation=%llu lease_pid=%ld lease_generation=%llu stage_actual=0",
        EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)ee_nwc_prepared_assets.generation,rc,snap.attempted,snap.allocated,snap.send_called,snap.send_returned,snap.send_rc,snap.received,snap.reader_returned,snap.reader_output,snap.free_returned,snap.free_rc,snap.retired,snap.pending,snap.fault,snap.selection.can_publish,snap.lease.message,snap.current[0],snap.current[1],snap.selection.reason,snap.selection.raw_candidate,snap.received?wire:"unavailable",snap.receive_observed.lease.source,snap.receive_observed.lease.bytes,snap.receive_observed.consumer,snap.free_owner,snap.free_actor_tid,snap.owned_copy,snap.wait_returned,(unsigned long long)snap.lease.message_generation,(long)snap.lease.pid,(unsigned long long)snap.lease.generation);
}
/* uconf+40 is a lazy pthread array; +52 is an atomic use count, not resource identity. */
static void ee_cold_decode_init(struct ee_nwc_init *out,const unsigned char raw[56]) {
    memcpy(&out->fd,raw,4);memcpy(&out->mapping,raw+8,8);memcpy(&out->bytes,raw+16,4);
    memcpy(&out->allocator,raw+24,8);memcpy(&out->pool0,raw+32,4);memcpy(&out->pool1,raw+36,4);memcpy(&out->dynamic_id,raw+48,4);
}
/* Bit order is fd/map/bytes/allocator/pool0/pool1/dynamic_id; no padding participates. */
static unsigned ee_cold_init_diff(const struct ee_nwc_init *a,const struct ee_nwc_init *b) {
    return (a->fd!=b->fd) | ((a->mapping!=b->mapping)<<1) | ((a->bytes!=b->bytes)<<2) |
        ((a->allocator!=b->allocator)<<3) | ((a->pool0!=b->pool0)<<4) |
        ((a->pool1!=b->pool1)<<5) | ((a->dynamic_id!=b->dynamic_id)<<6);
}
#if EE_COLD_DIAGNOSTICS
static int ee_cold_read_init(struct ee_nwc_init *out) {
    int diagnostic=ee_diag_claim(0),ok=0,decoded=0,equal=-1,valid=-1;unsigned stable_diff=0;
    int read_error=-1,read2_error=-1,link_error=-1,open_error=-1,parse=-1,parse_error=-1,maps_errno=-1,stage_error=-1;
    ssize_t read_rc=-2,read2_rc=-2,link_rc=-2;unsigned maps_lines=0;FILE *f=NULL;
    unsigned char a[56],b[56];char path[64],target[64];const char *stage="abi";
    memset(out,0,sizeof *out);out->pid=getpid();out->generation=ee_nwc_prepared_assets.generation;
    if(!ee_cold_abi_verified)goto done;
    stage="read1";if(!ee_diag_readmem(ee_uipc_base+0x1b560,a,sizeof a,&read_rc,&read_error)){stage_error=read_error;goto done;}
    ee_cold_decode_init(out,a);
    decoded=1;out->abi_verified=1;snprintf(path,sizeof path,"/proc/self/fd/%d",out->fd);
    stage="readlink";link_rc=readlink(path,target,sizeof target-1);link_error=errno;if(link_rc<0){stage_error=link_error;goto done;}target[link_rc]=0;
    out->fd_verified=!strcmp(target,"/dev/uipc");
    stage="fopen";f=fopen("/proc/self/maps","r");open_error=errno;if(!f){stage_error=open_error;goto done;}char line[512];
    while(fgets(line,sizeof line,f)){
        unsigned long lo,hi,offset;unsigned dev0,dev1;unsigned long inode;int used=0;char perm[5]={0};
        parse=ee_cold_legacy_sscanf(line,"%lx-%lx %4s %lx %x:%x %lu %n",&lo,&hi,perm,&offset,&dev0,&dev1,&inode,&used);parse_error=errno;maps_lines++;
        if(parse==7&&!strcmp(perm,"rw-s")&&lo<=out->mapping&&hi>=out->mapping&&out->bytes<=hi-out->mapping&&!strcmp(line+used,"/dev/uipc\n"))out->map_verified=1;
    }
    maps_errno=errno;fclose(f);
    stage="read2";if(!ee_diag_readmem(ee_uipc_base+0x1b560,b,sizeof b,&read2_rc,&read2_error)){stage_error=read2_error;goto done;}
    stage="equality";struct ee_nwc_init second=*out;ee_cold_decode_init(&second,b);
    stable_diff=ee_cold_init_diff(out,&second);equal=!stable_diff;if(!equal)goto done;
    stage="init_valid";valid=ee_nwc_init_valid(out,getpid(),ee_nwc_prepared_assets.generation);ok=valid;
    if(ok)stage="success";else if(!out->map_verified){stage="maps_parse";stage_error=maps_errno;}
 done:
    if(!ok){
        struct ee_cold_init_failure failure={1,stable_diff,stage,read_rc,read2_rc,read_error,read2_error,stage_error};
        pthread_mutex_lock(&ee_cold_lock);ee_cold_last_init_failure=failure;pthread_mutex_unlock(&ee_cold_lock);
    }
    if(diagnostic)ee_diag_emit("READ_INIT","generation=%llu stage=%s result=%d abi_known=1 abi=%u decoded=%d read_rc=%ld read_errno=%d read2_rc=%ld read2_errno=%d readlink_rc=%ld readlink_errno=%d fopen_ok=%d fopen_errno=%d maps_lines=%u maps_parse_rc=%d maps_parse_errno=%d maps_end_errno=%d equality=%d init_valid=%d fd=%d map=%#lx bytes=%u allocator=%#lx pool0=%u pool1=%u dynamic_id=%#x fd_verified=%u map_verified=%u",
        (unsigned long long)out->generation,stage,ok,ee_cold_abi_verified,decoded,(long)read_rc,read_error,(long)read2_rc,read2_error,(long)link_rc,link_error,f!=NULL,open_error,maps_lines,parse,parse_error,maps_errno,equal,valid,out->fd,out->mapping,out->bytes,out->allocator,out->pool0,out->pool1,out->dynamic_id,out->fd_verified,out->map_verified);
    return ok;
}
#else
static int ee_cold_read_init(struct ee_nwc_init *out) {
    unsigned char a[56],b[56];char path[64],target[64];
    memset(out,0,sizeof *out);out->pid=getpid();out->generation=ee_nwc_prepared_assets.generation;
    if(!ee_cold_abi_verified || !readmem(ee_uipc_base+0x1b560,a,sizeof a))return 0;
    ee_cold_decode_init(out,a);
    out->abi_verified=1;
    snprintf(path,sizeof path,"/proc/self/fd/%d",out->fd);
    ssize_t n=readlink(path,target,sizeof target-1);if(n<0)return 0;target[n]=0;
    out->fd_verified=!strcmp(target,"/dev/uipc");
    FILE *f=fopen("/proc/self/maps","r");if(!f)return 0;char line[512];
    while(fgets(line,sizeof line,f)){
        unsigned long lo,hi,offset;unsigned dev0,dev1;unsigned long inode;int used=0;char perm[5]={0};
        if(ee_cold_legacy_sscanf(line,"%lx-%lx %4s %lx %x:%x %lu %n",&lo,&hi,perm,&offset,&dev0,&dev1,&inode,&used)==7 &&
           !strcmp(perm,"rw-s") && lo<=out->mapping && hi>=out->mapping &&
           out->bytes<=hi-out->mapping && !strcmp(line+used,"/dev/uipc\n"))out->map_verified=1;
    }
    fclose(f);
    if(!readmem(ee_uipc_base+0x1b560,b,sizeof b))return 0;
    struct ee_nwc_init second=*out;ee_cold_decode_init(&second,b);
    return !ee_cold_init_diff(out,&second)&&ee_nwc_init_valid(out,getpid(),ee_nwc_prepared_assets.generation);
}
#endif
static int ee_cold_pid_ok(void) {
    pid_t pid=getpid(),expected=0;
    __atomic_compare_exchange_n(&ee_cold_process,&expected,pid,0,__ATOMIC_RELAXED,__ATOMIC_RELAXED);
    if(__atomic_load_n(&ee_cold_process,__ATOMIC_RELAXED)==pid)return 1;
    /* A fork child cannot acquire a mutex inherited from a vanished thread. */
    __atomic_store_n(&ee_cold_failed,EE_NWC_OWNER,__ATOMIC_RELAXED);return 0;
}
static int ee_cold_resources(void) {
    if(!ee_cold_pid_ok())return 0;
    if(EE_COLD_ADMISSION_SOURCE==EE_NWC_CALLBACK)return 1;
    struct ee_nwc_init current;int ok=ee_cold_read_init(&current);
    pthread_mutex_lock(&ee_cold_lock);
    if(!ok||(ee_cold_init_bound&&memcmp(&current,&ee_cold_init,sizeof current))){
#if EE_COLD_DIAGNOSTICS
        if(!ee_cold_failed)ee_cold_resource_fault=!ok?"read_init":"bound_identity";
        if(ok&&ee_cold_init_bound)ee_cold_bound_diff=ee_cold_init_diff(&current,&ee_cold_init);
#endif
        ee_cold_fail_locked(EE_NWC_GENERATION);
    }
    else if(!ee_cold_init_bound){ee_cold_init=current;ee_cold_init_bound=1;}
    ok=ok&&!ee_cold_failed;pthread_mutex_unlock(&ee_cold_lock);return ok;
}
static int ee_cold_allocate(unsigned destination,void **message,unsigned bytes,unsigned flags) {
    int saved=errno;if(!ee_cold_resources()){errno=saved;return -1023;}
    if(!ee_emit(1,"FUNCTIONAL_ALLOCATE_ENTER","mode=%s source_class=%s generation=%llu destination=%#x bytes=%u flags=%u",EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)ee_nwc_prepared_assets.generation,destination,bytes,flags)){errno=saved;return -1023;}
    errno=saved;int rc=ee_cold_native_allocate(destination,message,bytes,flags),error=errno;
    int valid=ee_cold_resources();
    ee_emit(1,"FUNCTIONAL_ALLOCATE_RETURN","mode=%s source_class=%s generation=%llu destination=%#x message=%p rc=%d errno=%d resources_valid=%d",EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)ee_nwc_prepared_assets.generation,destination,message?*message:NULL,rc,error,valid);
    /* Preserve the native rc; the core separately records sticky resource failure. */
    errno=error;return rc;
}
static int ee_cold_send(unsigned destination,void *message) {
    int saved=errno;if(!ee_cold_resources()){errno=saved;return -1023;}
    ee_emit(1,"FUNCTIONAL_SEND_ENTER","mode=%s source_class=%s generation=%llu destination=%#x message=%p",EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)ee_nwc_prepared_assets.generation,destination,message);
    errno=saved;int rc=ee_cold_native_send(destination,message),error=errno;
    ee_emit(1,"FUNCTIONAL_SEND_RETURN","mode=%s source_class=%s generation=%llu destination=%#x message=%p rc=%d errno=%d",EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)ee_nwc_prepared_assets.generation,destination,message,rc,error);
    errno=error;return rc;
}
static unsigned ee_cold_checked_size(void *message) {
    int saved=errno;if(!ee_cold_resources()){errno=saved;return 0;}
    errno=saved;unsigned result=ee_cold_native_size(message);int error=errno;
    ee_cold_resources();errno=error;return result;
}
static unsigned ee_cold_checked_source(void *message) {
    int saved=errno;if(!ee_cold_resources()){errno=saved;return 0;}
    errno=saved;unsigned result=ee_cold_native_source(message);int error=errno;
    ee_cold_resources();errno=error;return result;
}
static void ee_cold_queue(uintptr_t handle,uintptr_t callback,uintptr_t context,int ok) {
    if(!ee_cold_pid_ok())return;
    pthread_mutex_lock(&ee_cold_lock);
    ee_cold_queue_known=ok&&!ee_cold_registration_event;
    ee_cold_handle=handle;ee_cold_callback=callback;ee_cold_context=context;
    ee_cold_registration_event=++ee_cold_event;
    if(EE_COLD_ADMISSION_SOURCE==EE_NWC_CALLBACK&&!ee_cold_queue_known)ee_cold_fail_locked(EE_NWC_NOT_ARMED);
    pthread_mutex_unlock(&ee_cold_lock);
}
static void ee_cold_recv_enter(void) {
    if(!ee_cold_pid_ok())return;
    uintptr_t tid=(uintptr_t)syscall(SYS_gettid);
    pthread_mutex_lock(&ee_cold_lock);
    if(ee_cold_consumer&&ee_cold_consumer!=tid)ee_cold_fail_locked(EE_NWC_LEASE);
    else ee_cold_consumer=tid;
    pthread_mutex_unlock(&ee_cold_lock);
}
static struct ee_cold_slot *ee_cold_find(uintptr_t msg) {
    struct ee_cold_slot *latest=NULL;
    for(unsigned i=0;i<8;i++)if(ee_cold_slots[i].message==msg&&ee_cold_slots[i].state){
        if(ee_cold_slots[i].state==1)return ee_cold_slots+i;
        if(!latest||ee_cold_slots[i].serial>latest->serial)latest=ee_cold_slots+i;
    }
    return latest;
}
static void ee_cold_recv_return(uintptr_t msg,int rc) {
#if EE_COLD_DIAGNOSTICS
    int diagnostic=ee_diag_claim(2),native_error=errno,resources=-1,slot_known=0;unsigned index=0;
    struct ee_cold_slot copied={0};const char *reason="native_result";
    if(rc||!msg)goto recv_done;
    resources=ee_cold_resources();reason="resources";if(!resources)goto recv_done;
#else
    if(rc||!msg)return;
    if(!ee_cold_resources())return;
#endif
    pthread_mutex_lock(&ee_cold_lock);
    struct ee_cold_slot *p=ee_cold_find(msg);
    if(p&&p->state!=3){
        ee_cold_fail_locked(EE_NWC_DUPLICATE);
        if(p->state!=2){pthread_mutex_unlock(&ee_cold_lock);
#if EE_COLD_DIAGNOSTICS
            reason="duplicate";goto recv_done;
#else
            return;
#endif
        }
        p=NULL; /* Preserve the freeing generation; retain the new conflicting receive separately. */
    }
    if(!p)for(unsigned i=0;i<8;i++)if(!ee_cold_slots[i].state||ee_cold_slots[i].state==3){p=ee_cold_slots+i;break;}
    if(!p||ee_cold_event==UINT64_MAX){ee_cold_fail_locked(EE_NWC_BUSY);pthread_mutex_unlock(&ee_cold_lock);
#if EE_COLD_DIAGNOSTICS
        reason="busy";goto recv_done;
#else
        return;
#endif
    }
    *p=(struct ee_cold_slot){.pid=getpid(),.epoch=ee_nwc_prepared_assets.generation,.message=msg,
        .serial=++ee_cold_event,.receiver=(uintptr_t)syscall(SYS_gettid),.state=1};
    struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);struct ee_nwc_snapshot snap;
    if(s&&!ee_nwc_snapshot(s,&snap)&&snap.send_called&&snap.lease.message==msg){
        if(snap.free_begun||snap.free_returned||snap.received)ee_cold_fail_locked(EE_NWC_DUPLICATE);
        else {p->model=1;p->lease=snap.lease;}
    }
#if EE_COLD_DIAGNOSTICS
    copied=*p;slot_known=1;index=(unsigned)(p-ee_cold_slots);reason="slot_recorded";
#endif
    pthread_mutex_unlock(&ee_cold_lock);
#if EE_COLD_DIAGNOSTICS
 recv_done:
    if(diagnostic)ee_diag_emit("RECV_SLOT","generation=%llu rc=%d errno=%d resources=%d reason=%s message=%#lx slot_known=%d slot=%u slot_pid=%ld slot_generation=%llu receive_event=%llu receiver=%#lx state=%u source_known=%u source=%#x size_known=%u size=%d model=%u",
        (unsigned long long)ee_nwc_prepared_assets.generation,rc,native_error,resources,reason,msg,slot_known,index,(long)copied.pid,(unsigned long long)copied.epoch,(unsigned long long)copied.serial,copied.receiver,copied.state,copied.have_source,copied.source,copied.have_size,copied.size,copied.model);
#endif
}
static void ee_cold_metadata(uintptr_t msg,int is_size,uint32_t value) {
    if(!ee_cold_pid_ok())return;
    pthread_mutex_lock(&ee_cold_lock);struct ee_cold_slot *p=ee_cold_find(msg);
    if(p&&p->state==1&&p->pid==getpid()&&p->epoch==ee_nwc_prepared_assets.generation){
        if(is_size){if(p->have_size&&p->size!=(int32_t)value)ee_cold_fail_locked(EE_NWC_LEASE);p->size=(int32_t)value;p->have_size=1;}
        else {if(p->have_source&&p->source!=value)ee_cold_fail_locked(EE_NWC_LEASE);p->source=value;p->have_source=1;}
    }
    pthread_mutex_unlock(&ee_cold_lock);
}
#if EE_COLD_DIAGNOSTICS
struct ee_wait_checkpoint {
    int claim,pid_ok,resources,ledger_known;unsigned active,registration;
    uintptr_t future,consumer;unsigned attempted,failed,conflict,prime,init_known,queue_known,bound_diff;
    const char *first_site,*resource_fault;
    struct ee_cold_init_failure init_failure;
};
static void ee_wait_checkpoint_locked(struct ee_wait_checkpoint *d) {
    d->ledger_known=1;d->consumer=ee_cold_consumer;d->attempted=ee_cold_attempted;d->failed=ee_cold_failed;
    d->conflict=ee_cold_endpoint_conflict;d->prime=ee_cold_prime.free_returned;d->init_known=ee_cold_init_bound;d->queue_known=ee_cold_queue_known;
    d->first_site=ee_cold_first_fault_site;d->resource_fault=ee_cold_resource_fault;d->bound_diff=ee_cold_bound_diff;d->init_failure=ee_cold_last_init_failure;
}
static void ee_wait_checkpoint_emit(struct ee_wait_checkpoint d,const char *reason) {
    if(d.claim)ee_diag_emit("WAIT_ADMISSION","generation=%llu pid_ok=%d reading_active=%u registration_valid=%u future=%#lx resources=%d reason=%s ledger_known=%d consumer=%#lx attempted=%u failed=%u conflict=%u prime_free_returned=%u init_known=%u queue_known=%u first_sticky=%u first_site=%s resource_fault=%s bound_diff=%u last_init_known=%u last_init_stage=%s last_init_errno=%d last_read_rc=%ld last_read_errno=%d last_read2_rc=%ld last_read2_errno=%d stable_diff=%u after_original_unlock=1",
        (unsigned long long)ee_nwc_prepared_assets.generation,d.pid_ok,d.active,d.registration,d.future,d.resources,reason,d.ledger_known,d.consumer,d.attempted,d.failed,d.conflict,d.prime,d.init_known,d.queue_known,
        d.failed,d.first_site?d.first_site:"unknown",d.resource_fault?d.resource_fault:"unknown",d.bound_diff,d.init_failure.known,d.init_failure.stage?d.init_failure.stage:"unknown",d.init_failure.stage_error,(long)d.init_failure.read_rc,d.init_failure.read_error,(long)d.init_failure.read2_rc,d.init_failure.read2_error,d.init_failure.stable_diff);
}
#endif
static void ee_cold_wait(uintptr_t future) {
    struct ee_nwc_gate gate={0};struct ee_nwc *s=NULL;
#if EE_COLD_DIAGNOSTICS
    struct ee_wait_checkpoint d={.claim=ee_diag_claim(1),.active=ee_cold_reading.active,.registration=ee_registration.valid,.future=future,.resources=-1};
    d.pid_ok=ee_cold_pid_ok();
    if(!d.pid_ok||!d.active||!future||!d.registration){
        if(d.pid_ok){pthread_mutex_lock(&ee_cold_lock);ee_wait_checkpoint_locked(&d);pthread_mutex_unlock(&ee_cold_lock);}
        ee_wait_checkpoint_emit(d,!d.pid_ok?"pid":!d.active?"reading_active":!future?"future":"registration_valid");return;
    }
    if(EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT){d.resources=ee_cold_resources();if(!d.resources){
        pthread_mutex_lock(&ee_cold_lock);ee_wait_checkpoint_locked(&d);pthread_mutex_unlock(&ee_cold_lock);
        ee_wait_checkpoint_emit(d,"resources");return;
    }}
    pthread_mutex_lock(&ee_cold_lock);
    int kernel=EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT;
    ee_wait_checkpoint_locked(&d);
    const char *reject=ee_cold_attempted?"attempted":ee_cold_failed?"sticky_fault":!ee_cold_consumer?"consumer":ee_cold_endpoint_conflict?"endpoint_conflict":(kernel?!ee_cold_prime.free_returned:!ee_cold_queue_known)?(kernel?"prime":"queue"):NULL;
    if(reject){pthread_mutex_unlock(&ee_cold_lock);ee_wait_checkpoint_emit(d,reject);return;}
#else
    if(!ee_cold_pid_ok()||!ee_cold_reading.active||!future||!ee_registration.valid)return;
    if(EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT&&!ee_cold_resources())return;
    pthread_mutex_lock(&ee_cold_lock);
    int kernel=EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT;
    if(ee_cold_attempted||ee_cold_failed||!ee_cold_consumer||ee_cold_endpoint_conflict||
       (kernel?!ee_cold_prime.free_returned:!ee_cold_queue_known)){pthread_mutex_unlock(&ee_cold_lock);return;}
#endif
    ee_cold_attempted=1;
    gate=(struct ee_nwc_gate){.pid=getpid(),.generation=ee_nwc_prepared_assets.generation,
        .consumer=ee_cold_consumer,.promise=future,.reader=app_base+0x3549218,
        .registration_event=ee_cold_registration_event,.unlock_event=++ee_cold_event,
        .observer_installed=ee_installed,.consumer_registered=kernel?0:1,.wait_unlocked=1,
        .notification_id=0x20a3,.registration_rc=kernel?EE_NWC_UNKNOWN:0,
        .admission_source=EE_COLD_ADMISSION_SOURCE,.waiter_tid=(uintptr_t)syscall(SYS_gettid),
        .init=ee_cold_init,.prime=ee_cold_prime};
    pthread_mutex_unlock(&ee_cold_lock);
#if EE_COLD_DIAGNOSTICS
    ee_wait_checkpoint_emit(d,"admitted");
#endif
    if(kernel){
        ee_emit(1,"FUNCTIONAL_INIT","mode=%s source_class=kerneldefault generation=%llu fd=%d map=%#lx bytes=%u allocator=%#lx pool0=%u pool1=%u dynamic_id=%#x abi_verified=%u fd_verified=%u map_verified=%u",
            EE_COLD_MODE,(unsigned long long)gate.init.generation,gate.init.fd,gate.init.mapping,gate.init.bytes,gate.init.allocator,gate.init.pool0,gate.init.pool1,gate.init.dynamic_id,gate.init.abi_verified,gate.init.fd_verified,gate.init.map_verified);
        ee_emit(1,"FUNCTIONAL_PRIME","mode=%s source_class=kerneldefault generation=%llu message=%#lx message_generation=%llu receive_event=%llu free_event=%llu receiver_tid=%#lx free_actor_tid=%#lx source=%#x size=%d source_known=%u size_known=%u receive_rc=%d free_rc=%d free_returned=%u",
            EE_COLD_MODE,(unsigned long long)gate.prime.generation,gate.prime.message,(unsigned long long)gate.prime.message_generation,(unsigned long long)gate.prime.receive_event,(unsigned long long)gate.prime.free_event,gate.prime.receiver_tid,gate.prime.free_actor_tid,gate.prime.source,gate.prime.size,gate.prime.source_known,gate.prime.size_known,gate.prime.receive_rc,gate.prime.free_rc,gate.prime.free_returned);
    }
    ee_emit(1,"FUNCTIONAL_GATE","mode=%s source_class=%s generation=%llu registration=%s handle=%#lx callback=%#lx context=%#lx receiver_tid=%#lx waiter_tid=%#lx promise=%#lx reader=%#lx registration_event=%llu unlock_event=%llu original_rc=%d original_20a3_return=%u original_wait_unlocked=%u envelope_sha256=%s model_sha256=%s",
        EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)gate.generation,kernel?"not_applicable":"callback",ee_cold_handle,ee_cold_callback,ee_cold_context,gate.consumer,gate.waiter_tid,future,gate.reader,(unsigned long long)gate.registration_event,(unsigned long long)gate.unlock_event,gate.registration_rc,ee_registration.valid,gate.wait_unlocked,ee_cold_input_sha256,ee_cold_model_sha256);
    int rc=ee_nwc_create(&s,EE_NWC_PROFILE,getpid(),gate.generation,&ee_cold_io);
    if(rc){ee_cold_record("FUNCTIONAL_CREATE",rc);return;}
    __atomic_store_n(&ee_cold_service,s,__ATOMIC_RELEASE);
    struct ee_nwc_assets assets=ee_nwc_prepared_assets;assets.pid=getpid();
    struct ee_nwc_initial initial={.pid=getpid(),.generation=gate.generation,
        .known=EE_NWC_INITIAL_ALL,.model_defined=EE_NWC_INITIAL_ALL,
        .provenance="model-defined:usb-ee-normal-cold-v1",.force_e0=ee_cold_force,
        .be9bae_byte9=ee_cold_be9,.stable_state=ee_cold_state,.stable_bytes=sizeof ee_cold_state};
    rc=ee_nwc_configure(s,&assets,&initial);if(!rc)rc=ee_nwc_arm(s,&gate);
    if(rc){ee_cold_record("FUNCTIONAL_ARM",rc);return;}
    struct timespec ts;if(clock_gettime(CLOCK_MONOTONIC,&ts)){ee_nwc_fail(s,EE_NWC_UNKNOWN);ee_cold_record("FUNCTIONAL_CLOCK",EE_NWC_UNKNOWN);return;}
    uint64_t now=(uint64_t)ts.tv_sec*UINT64_C(1000000000)+(uint64_t)ts.tv_nsec;
    struct ee_adc_sample samples[2]={{ee_cold_adc,24,now,gate.generation,0,1,1,1},{ee_cold_adc+24,24,now,gate.generation,1,1,1,1}};
    ee_cold_reading.promise=future;
    rc=ee_nwc_trigger(s,gate.generation,samples,now,0);ee_cold_record("FUNCTIONAL_TRIGGER",rc);
}
static void ee_cold_receive(uintptr_t msg) {
    struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);
    if(!s)return;
    if(!ee_cold_resources())return;
    int rc=0,report=0;const char *method="readmem";
    struct ee_cold_slot copied={0};
    pthread_mutex_lock(&ee_cold_lock);struct ee_cold_slot *p=ee_cold_find(msg);
    if(!ee_cold_failed&&p&&p->state==1&&p->model&&!p->observed&&p->have_size&&p->have_source){
        report=1;
        if(p->pid!=getpid()||p->epoch!=ee_nwc_prepared_assets.generation||p->receiver!=ee_cold_consumer||
           p->size!=12||p->source!=EE_NWC_SOURCE)rc=EE_NWC_LEASE;
        struct ee_nwc_receive received={.lease=p->lease,.consumer=p->receiver};
        if(!rc){
            if(EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT){method="model-owned-native-cpu-copy";rc=ee_nwc_copy_owned(s,&p->lease,(unsigned)p->size,received.lease.wire);}
            else if(!readmem(msg,received.lease.wire,12))rc=EE_NWC_UNKNOWN;
        }
        if(!rc)rc=ee_nwc_observe_receive(s,&received);
        if(!rc){p->observed=1;p->lease=received.lease;}
        else ee_cold_fail_locked(rc);
        copied=*p;
    }
    pthread_mutex_unlock(&ee_cold_lock);
    if(report){ee_emit(1,"FUNCTIONAL_COPY","mode=%s source_class=%s generation=%llu method=%s message=%#lx message_generation=%llu receive_event=%llu receiver_tid=%#lx source=%#x bytes=%d rc=%d",EE_COLD_MODE,ee_cold_source_class(),(unsigned long long)copied.epoch,method,copied.message,(unsigned long long)copied.lease.message_generation,(unsigned long long)copied.serial,copied.receiver,copied.source,copied.size,rc);ee_cold_record("FUNCTIONAL_RECEIVE",rc);}
}
static struct ee_cold_ticket ee_cold_free_enter(uint32_t owner,uintptr_t msg) {
    struct ee_cold_ticket ticket={0};if(!ee_cold_pid_ok())return ticket;
    ticket.owner=owner;ticket.actor=(uintptr_t)syscall(SYS_gettid);
    pthread_mutex_lock(&ee_cold_lock);struct ee_cold_slot *p=ee_cold_find(msg);
    if(p&&p->state==1&&p->pid==getpid()&&p->epoch==ee_nwc_prepared_assets.generation){
        p->state=2;ticket.slot=*p;ticket.index=(unsigned)(p-ee_cold_slots);ticket.valid=1;
        if(p->model){struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);
            if(!p->observed)ee_cold_fail_locked(EE_NWC_LEASE);
            if(s)ee_nwc_free_begin(s,&p->lease);
        }
    }else if(p&&p->state!=3)ee_cold_fail_locked(EE_NWC_DUPLICATE);
    pthread_mutex_unlock(&ee_cold_lock);
    if(ticket.valid&&ticket.slot.model&&EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT)
        ee_emit(1,"FUNCTIONAL_FREE_TICKET","mode=%s source_class=kerneldefault generation=%llu message=%#lx message_generation=%llu receive_event=%llu slot=%u owner=%#x receiver_tid=%#lx free_actor_tid=%#lx source=%#x size=%d observed=%u state=%u",
            EE_COLD_MODE,(unsigned long long)ticket.slot.epoch,ticket.slot.message,(unsigned long long)ticket.slot.lease.message_generation,(unsigned long long)ticket.slot.serial,ticket.index,ticket.owner,ticket.slot.receiver,ticket.actor,ticket.slot.source,ticket.slot.size,ticket.slot.observed,ticket.slot.state);
    return ticket;
}
static void ee_cold_free(struct ee_cold_ticket ticket,int32_t rc) {
#if EE_COLD_DIAGNOSTICS
    int diagnostic=ee_diag_claim(3),native_error=errno,resources_ok=-1;const char *reason="pid_or_ticket";
    if(!ee_cold_pid_ok()||!ticket.valid)goto free_done;
    resources_ok=ee_cold_resources();int model=ticket.slot.model;reason="returned";
#else
    if(!ee_cold_pid_ok()||!ticket.valid)return;
    int resources_ok=ee_cold_resources();int model=ticket.slot.model;
#endif
    /* All diagnostic fields come from the immutable pre-free ticket. */
    pthread_mutex_lock(&ee_cold_lock);
    struct ee_cold_slot *p=ticket.index<8?ee_cold_slots+ticket.index:NULL;
    if(!p||p->message!=ticket.slot.message||p->serial!=ticket.slot.serial||p->state!=2||p->pid!=ticket.slot.pid||p->epoch!=ticket.slot.epoch){ee_cold_fail_locked(EE_NWC_LEASE);pthread_mutex_unlock(&ee_cold_lock);
#if EE_COLD_DIAGNOSTICS
        reason="ticket_conflict";goto free_done;
#else
        return;
#endif
    }
    p->state=3;
    if(rc||ticket.owner!=EE_QUEUE||!resources_ok)ee_cold_fail_locked(EE_NWC_FREE);
    if(!model&&!ee_cold_failed&&p->have_source&&p->have_size&&p->source&&p->size>0&&p->receiver==ee_cold_consumer&&
       EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT&&ee_nwc_span(&ee_cold_init,p->message,(size_t)p->size)){
        ee_cold_prime=(struct ee_nwc_prime){.pid=p->pid,.generation=p->epoch,.message_generation=p->serial,
            .receive_event=p->serial,.free_event=++ee_cold_event,.message=p->message,.receiver_tid=p->receiver,
            .free_actor_tid=ticket.actor,.source=p->source,.size=p->size,.source_known=1,.size_known=1,.free_returned=1};
    }
    pthread_mutex_unlock(&ee_cold_lock);
    if(model&&(EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT||ticket.slot.observed)){struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);
        struct ee_nwc_free f={.lease=ticket.slot.lease,.owner=ticket.owner,.rc=rc,.free_actor_tid=ticket.actor};
        if(s)ee_cold_record("FUNCTIONAL_FREE",ee_nwc_observe_free(s,&f));
    }
#if EE_COLD_DIAGNOSTICS
 free_done:
    if(diagnostic)ee_diag_emit("FREE_RETURN","generation=%llu ticket_valid=%u slot=%u slot_pid=%ld slot_generation=%llu receive_event=%llu message_generation=%llu message=%#lx source_known=%u source=%#x size_known=%u size=%d receiver=%#lx owner=%#x free_actor=%#lx state=%u model=%u rc=%d errno=%d resources=%d reason=%s",
        (unsigned long long)ee_nwc_prepared_assets.generation,ticket.valid,ticket.index,(long)ticket.slot.pid,(unsigned long long)ticket.slot.epoch,(unsigned long long)ticket.slot.serial,(unsigned long long)ticket.slot.lease.message_generation,ticket.slot.message,ticket.slot.have_source,ticket.slot.source,ticket.slot.have_size,ticket.slot.size,ticket.slot.receiver,ticket.owner,ticket.actor,ticket.slot.state,ticket.slot.model,rc,native_error,resources_ok,reason);
#endif
}
static void ee_cold_wait_return(uintptr_t future) {
    if(EE_COLD_ADMISSION_SOURCE!=EE_NWC_KERNELDEFAULT)return;
    struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);
    if(s)ee_cold_record("FUNCTIONAL_WAIT_RETURN",ee_nwc_observe_wait(s,getpid(),ee_nwc_prepared_assets.generation,
        future,(uintptr_t)syscall(SYS_gettid)));
}
static uintptr_t ee_cold_reader(uintptr_t input,uintptr_t output) {
    int saved=errno;__typeof__(ee_cold_reading) previous=ee_cold_reading;
    ee_cold_reading.active=!!output;ee_cold_reading.promise=0;errno=saved;
    uintptr_t result=ee_cold_real_reader(input,output);int e=errno;
    struct ee_nwc *s=__atomic_load_n(&ee_cold_service,__ATOMIC_ACQUIRE);uint32_t value;
    if(s&&ee_cold_reading.promise&&readmem(output,&value,sizeof value)){
        struct ee_nwc_reader reader={.pid=getpid(),.generation=ee_nwc_prepared_assets.generation,
            .reader=app_base+0x3549218,.promise=ee_cold_reading.promise,.notification_id=0x20a3,.returned=1,.output=value};
        ee_cold_record("FUNCTIONAL_READER",ee_nwc_observe_reader(s,&reader));
    }
    ee_cold_reading=previous;errno=e;return result;
}
#ifndef USB_OBSERVE_HOST_TEST
static struct entry ee_cold_reader_entry={0x3549218,{0xd11c83ff,0xb002de60,0xa9ba7bfd,0x910003fd},ee_cold_reader,(void **)&ee_cold_real_reader};
static void ee_cold_check(uintptr_t base) {
    struct {const char *name;unsigned offset;uint32_t bytes[4];void **out;} api[]={
        {"osal_valloc_msg_wait",0x67b0,{0xa9ac7bfd,0x910003fd,0xa90153f3,0xa9025bf5},(void **)&ee_cold_native_allocate},
        {"osal_set_msg_src",0x7e20,{0xb81f4001,0xd65f03c0,0xb85f4000,0xd65f03c0},(void **)&ee_cold_io.set_source},
        {"osal_snd_msg",0x5e60,{0xa9ab7bfd,0x910003fd,0xa90363f7,0x72003817},(void **)&ee_cold_native_send}};
    uint8_t original[0x148],mapped[0x148];
    int fd=(int)syscall(SYS_openat,AT_FDCWD,"/usr/lib/appFw.so",O_RDONLY|O_NOFOLLOW|O_CLOEXEC,0);
    int original_ok=fd>=0&&pread(fd,original,0x110,0x3549218)==0x110;
    if(fd>=0)close(fd);
    if(!original_ok||!readmem(base+0x3549218,mapped,0x110)||memcmp(original,mapped,0x110))
        fatal("EE reader 3549218 complete mapped entry differs from SHA-bound original ELF");
    if(memcmp((void *)(base+ee_cold_reader_entry.offset),ee_cold_reader_entry.bytes,16))fatal("EE reader 3549218 bytes/ABI drift");
    for(unsigned i=0;i<sizeof api/sizeof *api;i++){
        uintptr_t expected=ee_uipc_base+api[i].offset,actual=(uintptr_t)lookup(RTLD_NEXT,api[i].name);
        if(actual!=expected)ee_guard_api("lookup",api[i].name,0,expected,actual);
        if(memcmp((void *)expected,api[i].bytes,16))ee_guard_api("bytes",api[i].name,0,expected,actual);
        *api[i].out=(void *)expected;
    }
    if(EE_COLD_ADMISSION_SOURCE==EE_NWC_KERNELDEFAULT){
        if((uintptr_t)lookup(RTLD_NEXT,"uconf")!=ee_uipc_base+0x1b560)fatal("EE uconf original symbol/layout");
        fd=(int)syscall(SYS_openat,AT_FDCWD,"/usr/lib/libosal_uipc.so",O_RDONLY|O_NOFOLLOW|O_CLOEXEC,0);
        const unsigned starts[]={0x33e8,0x3c60,0x7e08},sizes[]={0x148,0x78,0x28};
        int ok=fd>=0;
        for(unsigned i=0;i<3&&ok;i++)ok=pread(fd,original,sizes[i],starts[i])==(ssize_t)sizes[i]&&
            readmem(ee_uipc_base+starts[i],mapped,sizes[i])&&!memcmp(original,mapped,sizes[i]);
        if(fd>=0)close(fd);
        if(!ok)fatal("EE initialized kernel receive original fullbytes drift");
        ee_cold_abi_verified=1;
    }
    ee_cold_io.allocate=ee_cold_allocate;ee_cold_io.send=ee_cold_send;
    ee_cold_io.release=(void *)(ee_uipc_base+0x6970);
    ee_cold_native_size=(void *)(ee_uipc_base+0x7e08);ee_cold_native_source=(void *)(ee_uipc_base+0x7e28);
    ee_cold_io.size=ee_cold_checked_size;ee_cold_io.source=ee_cold_checked_source;
    if(!ee_cold_pid_ok())fatal("EE observer forked during installation");
}
static void ee_cold_install(uintptr_t base) {entry_install(base,&ee_cold_reader_entry);}
#endif
