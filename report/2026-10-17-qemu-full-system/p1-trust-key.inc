/* Included after the passive SD observer helpers. No caller-owned allocation/free. */
#include "p1-trust-key.h"
extern char *getenv(const char *);
struct TrustPin {const char *symbol,*path;unsigned long va,length;unsigned char code[928];};
static const struct TrustPin trust_pins[]={ /* __TRUST_PINS__ */ };
static int trust_identity;
static unsigned trust_lines;
static __thread struct p1_trust_borrow trust_borrow;
static __thread int trust_internal;
static int trust_marker(void) {
    int saved=*__errno_location();int (*op)(const char *,int,...)=next("open");
    char marker[64];int fd=op?op("/simulation/p1-trust-key/profile",0x20800):-1;
    long n=fd>=0?read(fd,marker,sizeof marker):-1;if(fd>=0)close(fd);
    static const char expected[]=P1_TRUST_PROFILE "\n";
    int ok=n==(long)sizeof expected-1 && !memcmp(marker,expected,sizeof expected-1);
    *__errno_location()=saved;return ok;
}
static int trust_profile(void) {
    const char *p=getenv("A7C2_P1_TRUST_PROFILE");
    return p && !strcmp(p,P1_TRUST_PROFILE) && trust_marker();
}
static int trust_caller(void *caller,unsigned long va) {
    Info info={0};
    return trust_identity && init_identity && dladdr(caller,&info) &&
        !strcmp(info.file,"/usr/lib/libsdfileinputupdaterapi.so") &&
        (char *)caller==(char *)info.base+va && selected();
}
static void trust_hex(char *out,const void *input,unsigned long n) {
    const unsigned char *p=input;static const char hex[]="0123456789abcdef";
    for(unsigned long i=0;i<n;i++){out[2*i]=hex[p[i]>>4];out[2*i+1]=hex[p[i]&15];}out[2*n]=0;
}
static void trust_log(const char *op,const char *data,long rc,int error,void *caller) {
    int saved=*__errno_location();
    if(trust_lines<64){trust_lines++;char line[1200];snprintf(line,sizeof line,
        "P1_TRUST_KEY pid=%d op=%s %s rc=%ld errno=%d caller=%p source_class=%s\n",
        getpid(),op,data,rc,error,caller,!strcmp(op,"reply")?"virtual-provisioned-trust-anchor":"original-passive");logline(line);}
    *__errno_location()=saved;
}
static void trust_check(void) __attribute__((constructor));
static void trust_check(void) {
    int saved=*__errno_location();
    if(selected()) {
        int ok=sizeof trust_pins/sizeof trust_pins[0]>=9;
        for(unsigned i=0;i<sizeof trust_pins/sizeof trust_pins[0];i++) {
            const struct TrustPin *p=trust_pins+i;void *fn=next(p->symbol);Info info={0};
            ok=ok && fn && dladdr(fn,&info) && !strcmp(info.file,p->path) &&
                (char *)fn==(char *)info.base+p->va && !memcmp(fn,p->code,p->length);
        }
        trust_identity=ok;
        trust_log("identity",ok?"bound=1":"bound=0",0,saved,0);
    }
    *__errno_location()=saved;
}
/* Passive reads never dereference native packet or object pointers in the observer. */
extern long syscall(long,...);
static long passive_tid(void) {
#ifdef __aarch64__
    return syscall(178);
#else
    return syscall(186);
#endif
}
static long passive_read(void *out,const void *in,unsigned long bytes,int *error) {
    int saved=*__errno_location();long n=-1;*error=14;
    unsigned long address=(unsigned long)in,dest=(unsigned long)out;
    const unsigned long last=~0ul>>1;
    if(!bytes || bytes>1084)*error=22;
    else if(address>=4096 && dest>=4096) {
        if(address>last || dest>last || bytes-1>last-address || bytes-1>last-dest)*error=75;
        else {
            int (*op)(const char *,int,...)=next("open");
            long (*rd)(int,void *,unsigned long,long long)=next("pread64");
            int (*cl)(int)=next("close");
            *error=38;
            if(op && rd && cl) {
                /* LP64 Linux O_RDONLY | O_CLOEXEC | O_NOFOLLOW; no retained fd or alternate backend. */
                *__errno_location()=0;int fd=op("/proc/self/mem",0xa0000);
                if(fd<0)*error=*__errno_location();
                else {
                    *__errno_location()=0;n=rd(fd,out,bytes,(long long)address);
                    *error=n<0?*__errno_location():0;cl(fd);
                }
            }
        }
    }
    *__errno_location()=saved;return n;
}
struct PassivePin {const char *symbol,*path;unsigned long symbol_va,va,length;unsigned char code[1084];};
static const struct PassivePin passive_pins[]={ /* __PASSIVE_PINS__ */ };
static int passive_identity;
static void *passive_verify_callee;
static unsigned passive_lines,passive_pin_lines;
struct PassiveBorrow {void *message;unsigned bytes,sid,operation,sends,free_calls;int pid,live;long tid;};
static __thread struct PassiveBorrow passive_borrow;
static __thread unsigned long passive_blocks;
static void passive_log(const char *op,const char *data,long rc,int error,void *caller) {
    int saved=*__errno_location();
    int diagnostic=!strcmp(op,"pin") || !strcmp(op,"identity");
    unsigned *count=diagnostic?&passive_pin_lines:&passive_lines;
    if(*count<(diagnostic?32u:96u)){(*count)++;char line[1400];snprintf(line,sizeof line,
        "P1_DECRYPT_PASSIVE pid=%d tid=%ld op=%s %s rc=%ld errno=%d caller=%p source_class=original-passive\n",
        getpid(),passive_tid(),op,data,rc,error,caller);logline(line);}
    *__errno_location()=saved;
}
static void passive_check(void) __attribute__((constructor));
static void passive_check(void) {
    int saved=*__errno_location();
    if(selected()) {
        int ok=trust_identity && init_identity && sizeof passive_pins/sizeof passive_pins[0]==4;
        for(unsigned i=0;i<sizeof passive_pins/sizeof passive_pins[0];i++) {
            const struct PassivePin *p=passive_pins+i;Info info={0};void *fn=next(p->symbol);
            unsigned char code[1084];int error=0;long actual=-1;
            int mapped=fn && dladdr(fn,&info),path_ok=mapped && info.file && !strcmp(info.file,p->path);
            unsigned long base=(unsigned long)info.base,address=0;
            int va_ok=mapped && (unsigned long)fn>=base && (unsigned long)fn-base==p->symbol_va;
            int attempted=path_ok && va_ok && p->length<=sizeof code && p->va<=~0ul-base;
            if(attempted){address=base+p->va;actual=passive_read(code,(void *)address,p->length,&error);}
            int complete=attempted && actual==(long)p->length;
            int match=complete && !memcmp(code,p->code,p->length);
            ok=ok && match;
            char data[1000];snprintf(data,sizeof data,
                "index=%u symbol=%.220s resolved=%d mapped=%d path=%.160s expected_path=%.160s path_ok=%d symbol_va=%lx expected_symbol_va=%lx va_ok=%d code_va=%lx address=%p requested=%lu read_attempted=%d actual=%ld read_errno=%d compare=%s backend=proc-self-mem-pread64",
                i,p->symbol,fn!=0,mapped,info.file?info.file:"unknown",p->path,path_ok,
                mapped?(unsigned long)fn-base:0,p->symbol_va,va_ok,p->va,(void *)address,p->length,attempted,actual,error,
                complete?(match?"match":"mismatch"):"unknown");
            passive_log("pin",data,actual,error,fn);
        }
        passive_identity=ok;
        if(ok)passive_verify_callee=next("_ZN7Updater15DecryptorModule9verifySumEv");
        passive_log("identity",ok?"bound=1 helper_args=9 helper_interposed=0 signature_coverage=unknown aes_binding=unknown backend=proc-self-mem-pread64":"bound=0 coverage=unknown backend=proc-self-mem-pread64",0,saved,0);
    }
    *__errno_location()=saved;
}
static int passive_gate(void *caller,unsigned long va) {
    return !trust_internal && passive_identity && trust_caller(caller,va);
}
static int passive_owned(unsigned sid,void *message) {
    return passive_borrow.live && passive_borrow.message==message && passive_borrow.sid==sid &&
        passive_borrow.pid==getpid() && passive_borrow.tid==passive_tid();
}
static void passive_digest(char hex[65],const unsigned char *data,unsigned long bytes) {
    unsigned char hash[32];p1_trust_hash_fn fn=next("SHA256");int internal=trust_internal;
    hex[0]=0;trust_internal=1;
    if(fn && fn(data,bytes,hash)==hash)trust_hex(hex,hash,32);
    trust_internal=internal;
}
static void passive_packet(const char *phase,long rc,int native_error,void *caller) {
    unsigned long header[5]={0};unsigned char payload[1024];char hex[65]="",first[33]="",h[81]="",line[700];int error=0;
    long actual=passive_read(header,passive_borrow.message,40,&error),payload_actual=0;
    unsigned long bytes=0;const char *bounds="header-read";
    if(actual==40) {
        trust_hex(h,header,40);unsigned long capacity=passive_borrow.bytes-40;
        bounds=(header[4]>>63)?"negative-length":header[4]>capacity?"over-capacity":"ok";
        bytes=(header[4]>>63)?0:header[4]>capacity?capacity:header[4];
        if(bytes){payload_actual=passive_read(payload,(char *)passive_borrow.message+40,bytes,&error);
            if(payload_actual==(long)bytes){passive_digest(hex,payload,bytes);trust_hex(first,payload,bytes<16?bytes:16);}}
        else if(!header[4])passive_digest(hex,payload,0);
    }
    snprintf(line,sizeof line,"phase=%s operation=%u operation_known=%d message=%p capacity=%u send_count=%u header=%s header_actual=%ld declared=%lu bounded=%lu payload_actual=%ld read_errno=%d bounds=%s sha256=%s first16=%s original_return=%d",
        phase,passive_borrow.operation,passive_borrow.operation!=0,passive_borrow.message,passive_borrow.bytes,passive_borrow.sends,h,actual,header[4],bytes,payload_actual,error,bounds,hex,first,!strcmp(phase,"after"));
    passive_log("sync",line,rc,native_error,caller);
}
int osal_valloc_msg_wait(unsigned sid,void **out,unsigned bytes,int wait) {
    int saved=*__errno_location();int (*fn)(unsigned,void **,unsigned,int)=next("osal_valloc_msg_wait");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);
    int observe=!trust_internal && trust_profile() && trust_caller(caller,P1_TRUST_ALLOC_RETURN);
    int allocation_site=passive_gate(caller,0x93d0);
    int passive=allocation_site && sid==P1_TRUST_SID && wait==1 && (bytes==56 || bytes==552 || bytes==1064);
    if(allocation_site)passive_borrow.live=0;
    *__errno_location()=saved;int rc=fn(sid,out,bytes,wait),error=*__errno_location();
    if(observe) {
        trust_borrow.live=0;
        if(!rc && out && *out && sid==P1_TRUST_SID && bytes==60 && wait==1)
            trust_borrow=(struct p1_trust_borrow){*out,bytes,sid,getpid(),P1_TRUST_ALLOC_RETURN,1};
    }
    if(passive) {
        void *message=0;int read_error=0;long actual=rc?0:passive_read(&message,out,sizeof message,&read_error);
        passive_borrow=(struct PassiveBorrow){.message=message,.bytes=bytes,.sid=sid,.pid=getpid(),.tid=passive_tid(),.live=!rc && actual==sizeof message && message};
        char data[250];snprintf(data,sizeof data,"sid=%x capacity=%u message=%p borrowed=%d pointer_actual=%ld read_errno=%d wait=%d native_alloc_called=1",sid,bytes,message,passive_borrow.live,actual,read_error,wait);
        passive_log("allocate",data,rc,error,caller);
    }
    *__errno_location()=error;return rc;
}
int osal_snd_sync_msg(unsigned sid,void *message) {
    int saved=*__errno_location();int (*fn)(unsigned,void *)=next("osal_snd_sync_msg");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int modeled=0;
    if(!trust_internal && trust_profile() && trust_caller(caller,P1_TRUST_SYNC_RETURN) && trust_borrow.live &&
       trust_borrow.message==message && trust_borrow.bytes==60 && trust_borrow.sid==sid && trust_borrow.owner_pid==getpid()) {
        unsigned char digest[20];trust_internal=1;
        if(p1_trust_key_read(P1_TRUST_PROFILE,P1_TRUST_ASSET,next("SHA1"),next("SHA256"),digest))
            modeled=p1_trust_key_reply(P1_TRUST_PROFILE,&trust_borrow,sid,message,P1_TRUST_SYNC_RETURN,digest);
        trust_internal=0;
        if(modeled){char hash[41],data[200];trust_hex(hash,digest,20);snprintf(data,sizeof data,
            "sid=025906be bytes=60 status=1 length=20 sha1=%s borrowed=1 consumed=1",hash);trust_log("reply",data,0,saved,caller);}
        else trust_log("reject","reason=asset-or-query native_passthrough=1",0,saved,caller);
        /* One observed synchronous attempt consumes the lease even on rejection. */
        trust_borrow.live=0;
    }
    int passive=passive_gate(caller,0x9434) && passive_owned(sid,message);
    if(passive) {
        unsigned long h[5];int error;
        long actual=passive_read(h,message,40,&error);
        int known=actual==40 && ((h[0]==2 && passive_borrow.bytes==56 && !h[1] && h[2]==8 && !h[3] && h[4]==16) ||
            (h[0]==3 && (passive_borrow.bytes==552 || passive_borrow.bytes==1064) && !h[2] && !h[3] && h[4]>0 && h[4]<=passive_borrow.bytes-40));
        passive_borrow.operation=known?(unsigned)h[0]:0;
        passive_borrow.sends++;
        if(!known)passive_log("request-reject",actual==40?"reason=unknown-header native_passthrough=1":"reason=short-or-refused-header native_passthrough=1",actual,error,caller);
        passive_packet("before",0,saved,caller);
    }
    *__errno_location()=saved;
    int rc=modeled?0:fn(sid,message),error=*__errno_location();
    if(passive)passive_packet("after",rc,error,caller);
    *__errno_location()=error;return rc;
}
int osal_free_msg(unsigned sid,void *message) {
    int saved=*__errno_location();int (*fn)(unsigned,void *)=next("osal_free_msg");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);
    int observe=message && trust_borrow.message==message && trust_borrow.sid==sid && trust_borrow.owner_pid==getpid();
    int owned=passive_owned(sid,message),passive=owned && passive_gate(caller,0x949c);
    if(owned){passive_borrow.free_calls++;passive_borrow.live=0;}
    if(trust_borrow.message==message)trust_borrow.live=0;
    *__errno_location()=saved;int rc=fn(sid,message),error=*__errno_location();
    if(observe){char data[150];snprintf(data,sizeof data,"sid=%x message=%p bytes=%lu borrowed=1 native_free_called=1",sid,message,(unsigned long)trust_borrow.bytes);
        trust_log("free",data,rc,error,caller);trust_borrow.message=0;}
    if(passive){char data[240];snprintf(data,sizeof data,"sid=%x message=%p capacity=%u operation=%u operation_known=%d native_free_count=%u native_free_called=1",sid,message,passive_borrow.bytes,passive_borrow.operation,passive_borrow.operation!=0,passive_borrow.free_calls);
        passive_log("free",data,rc,error,caller);passive_borrow.message=0;}
    *__errno_location()=error;return rc;
}
int strncmp(const char *left,const char *right,size_t n) {
    int saved=*__errno_location();int (*fn)(const char *,const char *,size_t)=next("strncmp");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=n==20 && !trust_internal && trust_caller(caller,0xac94);
    char a[41],b[41];if(observe){trust_hex(a,left,20);trust_hex(b,right,20);}
    *__errno_location()=saved;int rc=fn(left,right,n),error=*__errno_location();
    if(observe){char data[200];snprintf(data,sizeof data,"length=%lu left=%s right=%s original_return=1",(unsigned long)n,a,b);trust_log("strncmp",data,rc,error,caller);}
    *__errno_location()=error;return rc;
}
static void passive_copy(int output,void *dest,const void *source,size_t n,void *caller,void *rc,int native_error) {
    if(!passive_gate(caller,output?0x9460:0x9428) || !passive_owned(P1_TRUST_SID,passive_borrow.message))return;
    unsigned capacity=passive_borrow.bytes,expected=capacity==56?2:3;
    unsigned long message=(unsigned long)passive_borrow.message,ordinary=(unsigned long)(output?dest:source),last=~0ul>>1;
    if((capacity!=56 && capacity!=552 && capacity!=1064) || passive_borrow.free_calls ||
       !n || n>capacity-40 || (capacity==56 && n!=(output?8u:16u)) ||
       (passive_borrow.operation && passive_borrow.operation!=expected) || (output && !passive_borrow.sends))return;
    /* Integer ranges avoid pointer arithmetic on the unreadable native message. */
    if(message<4096 || message>last || capacity-1>last-message || ordinary<4096 || ordinary>last ||
       n-1>last-ordinary || (unsigned long)(output?source:dest)!=message+40 ||
       (ordinary<message+capacity && message<ordinary+n))return;
    unsigned char payload[1024];char hex[65]="",first[33]="",opaque[17]="",opcode[16]="unknown",line[900];int read_error=0;
    long actual=passive_read(payload,(const void *)ordinary,n,&read_error);
    if(actual==(long)n){passive_digest(hex,payload,n);trust_hex(first,payload,n<16?n:16);
        if(output && expected==2)trust_hex(opaque,payload,8);}
    if(passive_borrow.operation)snprintf(opcode,sizeof opcode,"%u",passive_borrow.operation);
    snprintf(line,sizeof line,"direction=%s phase=%s sid=%x operation=%u operation_known=%d observed_opcode=%s expected_operation=%u static_shape=checked-original-caller-allocation-and-copy length=%lu capacity=%u message=%p dest=%p source=%p payload_actual=%ld actual=%ld read_errno=%d payload_state=%s sha256=%s first16=%s opaque8=%s read_source=%s backend=proc-self-mem-pread64 original_copy_called=%d original_copy_called_next=%d",
        output?"output":"input",output?"after":"before",passive_borrow.sid,passive_borrow.operation,passive_borrow.operation!=0,opcode,expected,
        (unsigned long)n,capacity,(void *)message,dest,source,actual,actual,read_error,actual==(long)n?"observed":"unknown",hex,first,opaque,
        output?"original-memcpy-destination":"original-memcpy-source",output,!output);
    passive_log("copy",line,(long)rc,native_error,caller);
}
void *memcpy(void *dest,const void *source,size_t n) {
    int saved=*__errno_location();void *(*fn)(void *,const void *,size_t)=next("memcpy");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && trust_caller(caller,0xac18);
    char data[300],hex[121];if(observe){unsigned long count=n<60?n:60;trust_hex(hex,source,count);snprintf(data,sizeof data,
        "length=%lu recorded=%lu data=%s dest=%p source=%p",(unsigned long)n,count,hex,dest,source);}
    passive_copy(0,dest,source,n,caller,0,saved);
    *__errno_location()=saved;void *rc=fn(dest,source,n);int error=*__errno_location();
    if(observe)trust_log("memcpy",data,(long)rc,error,caller);
    passive_copy(1,dest,source,n,caller,rc,error);
    *__errno_location()=error;return rc;
}
int SHA1_Final(unsigned char *digest,void *context) {
    int saved=*__errno_location();int (*fn)(unsigned char *,void *)=next("SHA1_Final");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && trust_caller(caller,0xaba8);
    *__errno_location()=saved;int rc=fn(digest,context),error=*__errno_location();
    if(observe){char data[150],hex[41];hex[0]=0;if(rc==1 && digest)trust_hex(hex,digest,20);
        snprintf(data,sizeof data,"output=%p context=%p sha1=%s",digest,context,hex);trust_log("SHA1_Final",data,rc,error,caller);}
    *__errno_location()=error;return rc;
}
/* Passive SHA256 tap: records the original return digest, never the data bytes. */
unsigned char *SHA256(const void *data,size_t bytes,unsigned char *out) {
    int saved=*__errno_location();unsigned char *(*fn)(const void *,size_t,unsigned char *)=next("SHA256");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && trust_caller(caller,0xadf0);
    *__errno_location()=saved;unsigned char *rc=fn(data,bytes,out);int error=*__errno_location();
    if(observe){unsigned char digest[32];char hex[65],data_line[350];long actual=0;int read_error=0;hex[0]=0;
        if(rc){actual=passive_read(digest,rc,32,&read_error);if(actual==32)trust_hex(hex,digest,32);}
        snprintf(data_line,sizeof data_line,"data=%p bytes=%lu out=%p returned=%p digest=%s actual=%ld read_errno=%d backend=proc-self-mem-pread64 digest_verified=0",
            data,(unsigned long)bytes,out,rc,hex,actual,read_error);
        trust_log("SHA256",data_line,(long)rc,error,caller);}
    *__errno_location()=error;return rc;
}
int RSA_verify(int type,const unsigned char *digest,unsigned digest_length,
               const unsigned char *signature,unsigned signature_length,void *rsa) {
    int saved=*__errno_location();int (*fn)(int,const unsigned char *,unsigned,const unsigned char *,unsigned,void *)=next("RSA_verify");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && trust_caller(caller,0xae0c);
    char data[600],md[129],sig[65];md[0]=sig[0]=0;
    if(observe){trust_internal=1;
        if(digest && digest_length<=64)trust_hex(md,digest,digest_length);
        if(signature && signature_length<=4096){unsigned char hash[32];p1_trust_hash_fn hashfn=next("SHA256");if(hashfn && hashfn(signature,signature_length,hash))trust_hex(sig,hash,32);}
        trust_internal=0;snprintf(data,sizeof data,"type=%d digest=%p digest_length=%u digest_hex=%s signature=%p signature_length=%u signature_sha256=%s rsa=%p rsa_layout=opaque args=6 error_queue=unconsumed",
            type,digest,digest_length,md,signature,signature_length,sig,rsa);}
    *__errno_location()=saved;int rc=fn(type,digest,digest_length,signature,signature_length,rsa),error=*__errno_location();
    if(observe)trust_log("RSA_verify",data,rc,error,caller);
    *__errno_location()=error;return rc;
}
/* void(this); C unwind tables let the original C++ exception cross unchanged. */
void _ZN7Updater15DecryptorModule9verifySumEv(void *object) {
    int saved=*__errno_location();void (*fn)(void *)=next("_ZN7Updater15DecryptorModule9verifySumEv");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=passive_gate(caller,0x99a4) && (void *)fn==passive_verify_callee;
    if(observe){Info info={0};void *binding=0;int error;
        observe=dladdr(caller,&info) && passive_read(&binding,(char *)info.base+0x1e030,sizeof binding,&error)==sizeof binding &&
            binding==(void *)_ZN7Updater15DecryptorModule9verifySumEv;}
    if(observe){unsigned char block[1024];unsigned long progress=0,length=0;char sha[65]="",first[9]="",line[600];int error=0,pe=0,le=0;
        unsigned long address=(unsigned long)object;long actual=-1,pa=-1,la=-1;unsigned sum=0,header=0,size=0,raw_size=0;
        if(address && address<=~0ul-0x4b8){actual=passive_read(block,(void *)(address+0xb0),sizeof block,&error);
            pa=passive_read(&progress,(void *)(address+0x60),8,&pe);la=passive_read(&length,(void *)(address+0x4b0),8,&le);}
        else error=14;
        if(actual==1024){header=block[0]|((unsigned)block[1]<<8);raw_size=block[2]|((unsigned)block[3]<<8);size=raw_size&0xfff;
            for(unsigned i=2;i<1024;i+=2)sum=(sum+block[i]+((unsigned)block[i+1]<<8))&0xffff;
            passive_digest(sha,block,sizeof block);trust_hex(first,block,4);}
        snprintf(line,sizeof line,"phase=before block_index=%lu this=%p block_actual=%ld read_errno=%d sha256=%s first4=%s sum511=%u header=%u size=%u raw_size=%u size_valid=%d progress=%lu progress_actual=%ld progress_errno=%d read_length=%lu length_actual=%ld length_errno=%d callee=%p original_called_next=1",
            ++passive_blocks,object,actual,error,sha,first,sum,header,size,raw_size,size>=1 && size<=1020,progress,pa,pe,length,la,le,fn);
        passive_log("verifySum",line,0,saved,caller);}
    *__errno_location()=saved;fn(object);int error=*__errno_location();
    if(observe)passive_log("verifySum","phase=return result=void original_return=1",0,error,caller);
    *__errno_location()=error;
}

