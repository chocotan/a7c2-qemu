/* Uses the existing passive_read/logline helpers; never reads an opaque object. */
/* Selected Tail emits only; mirror failures stay visible as incomplete collection. */
extern unsigned long strlen(const char *);
static void tail_rawlog(const char *line) {
    int saved=*__errno_location();
    int (*op)(const char *,int,...)=next("open");
    long (*wr)(int,const void *,unsigned long)=next("write");
    int (*cl)(int)=next("close");
    if(op && wr && cl) {
        int fd=op("/simulation/p1-tail/receiver.log",0xa0441,0600);
        if(fd>=0) { unsigned long n=strlen(line);(void)wr(fd,line,n);(void)cl(fd); }
    }
    *__errno_location()=saved;
}
#include "p1-tail-budget.h"
struct TailPin {const char *name,*path,*sha;unsigned long va;unsigned char elf[64],code[64];};
static const struct TailPin tail_pins[]={ /* __TAIL_PINS__ */ };
static struct tail_budget tail_budget;
static int tail_owner,tail_lock;
static __thread int tail_internal;
static int tail_enabled(void) {
    const char *p=getenv("A7C2_P1_TAIL_PROFILE");
    return tail_owner==getpid() && p && !strcmp(p,"original-p1-stock-tail-v1") && !tail_internal;
}
static void tail_emit(unsigned family,const char *op,const char *data,long rc,int error,void *caller) {
    int saved=*__errno_location();
    if(tail_enabled() && family<T_FAMILIES) {
        tail_internal=1;
        char line[1024];int n=snprintf(line,sizeof line,
            "P1_TAIL pid=%d family=%u op=%s %s rc=%ld errno=%d caller=%p\n",
            tail_owner,family,op,data,rc,error,caller);
        while(__atomic_test_and_set(&tail_lock,__ATOMIC_ACQUIRE)){}
        int first=tail_budget.dropped[family]==0;
        int reserved_receipt=family==T_FAILURE && strcmp(op,"receipt") && tail_budget.used[T_FAILURE]>=27;
        if(!reserved_receipt && tail_reserve(&tail_budget,family,n>0?(size_t)n:0)){logline(line);tail_rawlog(line);}
        else if(reserved_receipt){tail_budget.seen[family]++;tail_budget.dropped[family]++;}
        else if(first) {
            n=snprintf(line,sizeof line,"P1_TAIL pid=%d family=7 op=saturation saturated_family=%u rc=0 errno=0 caller=(nil)\n",tail_owner,family);
            if(tail_reserve(&tail_budget,T_FAILURE,(size_t)n)){logline(line);tail_rawlog(line);}
        }
        __atomic_clear(&tail_lock,__ATOMIC_RELEASE);tail_internal=0;
    }
    *__errno_location()=saved;
}
static int tail_pin_at(unsigned index,void *address,int exact,void **base_out) {
    int saved=*__errno_location(),ok=0,error;Info i={0};unsigned char elf[64],code[64];
    if(index<sizeof tail_pins/sizeof tail_pins[0] && address && dladdr(address,&i)) {
        const struct TailPin *p=tail_pins+index;unsigned long base=(unsigned long)i.base;
        if(i.file && !strcmp(i.file,p->path) && base<=~0ul-p->va &&
           (!exact || address==(void *)(base+p->va)) &&
           passive_read(elf,i.base,64,&error)==64 && !memcmp(elf,p->elf,64) &&
           passive_read(code,(void *)(base+p->va),64,&error)==64 && !memcmp(code,p->code,64)) {
            ok=1;if(base_out)*base_out=i.base;
        }
    }
    *__errno_location()=saved;return ok;
}
struct TailImport {unsigned long call,plt;unsigned char call_code[4],plt_code[16];};
static const struct TailImport tail_imports[]={ /* __TAIL_IMPORTS__ */ };
static int tail_import_guard(void *base,unsigned j) {
    unsigned char c[4],p[16];int e=0;const struct TailImport *i=tail_imports+j;
    return j<3 && passive_read(c,(char *)base+i->call,4,&e)==4 && !memcmp(c,i->call_code,4) &&
        passive_read(p,(char *)base+i->plt,16,&e)==16 && !memcmp(p,i->plt_code,16);
}
static int tail_site(unsigned index,void *caller,unsigned long va) {
    void *base=0;int ok=tail_enabled() && tail_pin_at(index,caller,0,&base) &&
        (unsigned long)base<=~0ul-va && caller==(char *)base+va;
    if(ok && index==0)for(unsigned j=0;j<3;j++)if(va==tail_imports[j].call+4)return tail_import_guard(base,j);
    return ok;
}
static void tail_binding(const char *phase) {
    int saved=*__errno_location();
    if(tail_enabled()) {
        void *anchor=next("_ZN7Updater21SignatureVerification9verifyKeyEPKc"),*base=0;
        if(tail_pin_at(0,anchor,1,&base)) {
            static const char *const names[]={"SHA1_Final","SHA256","RSA_verify"};
            static const unsigned long slots[]={0x1e0f8,0x1e380,0x1e190};
            for(unsigned j=0;j<3;j++) {
                if(!tail_import_guard(base,j)){tail_emit(T_ID,"binding-reject","reason=call-or-plt-bytes binding=unknown",-1,0,0);continue;}
                void *binding=0;int error=0;Info i={0};unsigned char elf[64];
                long n=passive_read(&binding,(char *)base+slots[j],sizeof binding,&error);
                int mapped=n==sizeof binding && binding && dladdr(binding,&i);
                long actual=mapped?passive_read(elf,i.base,64,&error):-1;
                char identity[129]="";if(actual==64)trust_hex(identity,elf,64);
                char data[820];snprintf(data,sizeof data,
                    "phase=%s symbol=%s required_version=OPENSSL_1_1_0 sd_base=%p got_va=%lx got=%p got_actual=%ld mapped=%d path=%.120s mapped_base=%p elf_actual=%ld elf_hex=%s crypto_entry_match=%d source_sha=%s binding_is_lookup=0",
                    phase,names[j],base,slots[j],binding,n,mapped,i.file?i.file:"unknown",i.base,actual,
                    identity,mapped && tail_pin_at(1+j,binding,1,0),tail_pins[0].sha);
                tail_emit(T_ID,"binding",data,n,error,0);
            }
        } else tail_emit(T_ID,"binding-reject","sd_identity=0 binding=unknown",-1,0,0);
    }
    *__errno_location()=saved;
}
static void tail_start(void) __attribute__((constructor));
static void tail_start(void) {
    int saved=*__errno_location();const char *p=getenv("A7C2_P1_TAIL_PROFILE");
    if(p && !strcmp(p,"original-p1-stock-tail-v1") && selected() && init_identity && trust_identity) {
        tail_owner=getpid();tail_binding("load");
    }
    *__errno_location()=saved;
}
static void tail_finish(void) __attribute__((destructor));
static void tail_finish(void) {
    int saved=*__errno_location();
    if(tail_enabled()) {
        char data[800];while(__atomic_test_and_set(&tail_lock,__ATOMIC_ACQUIRE)){}
        snprintf(data,sizeof data,
            "records=%u bytes=%u seen=%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu dropped=%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu epoch_closed=1 install_verified=0",
            tail_budget.records,tail_budget.bytes,
            tail_budget.seen[0],tail_budget.seen[1],tail_budget.seen[2],tail_budget.seen[3],tail_budget.seen[4],tail_budget.seen[5],tail_budget.seen[6],tail_budget.seen[7],
            tail_budget.dropped[0],tail_budget.dropped[1],tail_budget.dropped[2],tail_budget.dropped[3],tail_budget.dropped[4],tail_budget.dropped[5],tail_budget.dropped[6],tail_budget.dropped[7]);
        __atomic_clear(&tail_lock,__ATOMIC_RELEASE);tail_emit(T_FAILURE,"receipt",data,0,saved,0);
    }
    *__errno_location()=saved;
}
/* Public checkpoint for the separate PMBP worker; all registers/IO ownership stay there. */
void p1_tail_checkpoint(unsigned family,const char *op,const char *data,long rc,int error,void *caller) {
    tail_emit(family,op,data,rc,error,caller);
}
