/* SPDX-License-Identifier: MIT */
/* Select the firmware's OWN file-backed media driver, only in an explicit mode.
 *
 * Provenance: this mechanism comes from the sibling deliverable
 * `report/2026-10-17-qemu-native-camera` (`runtime/analysis/file-media-config.c`,
 * STORAGE-PROOF.md / report/native-sd-persistence.md). It is re-implemented here
 * for this report's runtime; the point is the same:
 *
 *   `libInfraMediaCommon.so` already contains a file-type dummy media driver.
 *   The firmware only refuses to use it because the configuration item
 *   `EXISTMEDIADRIVER (0x69)` says a real driver exists. After the original
 *   `mcmn_param_init` runs, this preload sets 0x69 to 0, so the original
 *   `mcmn_init` picks the file backend that is already there.
 *
 * Nothing is faked: the original Fsys/Mount/Open/Write/Read/Flush code still runs,
 *   `DBG_DRV_DUMMY_OMIT_WRITE` must be 0 so writes really happen. The P1 library
 *   uses 0xf6; the older GUI library uses 0xf9. P1 selection is identity guarded.
 *   The card backing is the guest regular file `/image_mmca`.
 *
 * Enabled only when A7C2_FILE_MEDIA_TEST=1 (exactly that string), so an ordinary
 * GUI session is unaffected.
 */
typedef unsigned long size_t;
#include <sys/syscall.h>
#include <pthread.h>
extern void *dlvsym(void *, const char *, const char *);
extern char *getenv(const char *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern void _exit(int);
extern int snprintf(char *, unsigned long, const char *, ...);
extern int open(const char *, int, ...);
extern int close(int);
extern long write(int, const void *, unsigned long);
extern int strcmp(const char *, const char *);
extern int getpid(void);
extern long read(int,void *,unsigned long);
extern int sscanf(const char *,const char *,...);
extern int fsync(int),rename(const char *,const char *),kill(int,int);
extern int *__errno_location(void);
extern long syscall(long,...);

/* SHA implementation reused from guest/cold-start-audit.c; no crypto DSO added. */
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;
static const u32 rounds[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
};
struct sha { u32 h[8]; u64 count; u8 block[64]; unsigned used; };
static u32 rotr(u32 x,unsigned n) { return (x>>n)|(x<<(32-n)); }
static void transform(struct sha *s) {
    u32 w[64],a=s->h[0],b=s->h[1],c=s->h[2],d=s->h[3];
    u32 e=s->h[4],f=s->h[5],g=s->h[6],h=s->h[7];
    for (unsigned i=0;i<16;i++) w[i]=(u32)s->block[4*i]<<24|(u32)s->block[4*i+1]<<16|(u32)s->block[4*i+2]<<8|s->block[4*i+3];
    for (unsigned i=16;i<64;i++) w[i]=w[i-16]+(rotr(w[i-15],7)^rotr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rotr(w[i-2],17)^rotr(w[i-2],19)^(w[i-2]>>10));
    for (unsigned i=0;i<64;i++) {
        u32 t=h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+rounds[i]+w[i];
        u32 q=(rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c));
        h=g;g=f;f=e;e=d+t;d=c;c=b;b=a;a=t+q;
    }
    s->h[0]+=a;s->h[1]+=b;s->h[2]+=c;s->h[3]+=d;s->h[4]+=e;s->h[5]+=f;s->h[6]+=g;s->h[7]+=h;
}
static void start(struct sha *s) {
    const u32 initial[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    for (unsigned i=0;i<8;i++) s->h[i]=initial[i];
    s->count=0;s->used=0;
}
static void update(struct sha *s,const u8 *p,size_t n) {
    s->count+=n;
    while (n--) { s->block[s->used++]=*p++;if(s->used==64){transform(s);s->used=0;} }
}
static void finish(struct sha *s,char result[65]) {
    u64 bits=s->count*8;u8 one=128,zero=0,length[8];update(s,&one,1);
    while (s->used!=56) update(s,&zero,1);
    for(unsigned i=0;i<8;i++) length[7-i]=(u8)(bits>>(8*i));
    update(s,length,8);const char *hex="0123456789abcdef";
    for(unsigned i=0;i<32;i++){u8 b=(u8)(s->h[i/4]>>(24-8*(i%4)));result[2*i]=hex[b>>4];result[2*i+1]=hex[b&15];}
    result[64]=0;
}
struct media_dl_info { const char *name;void *base;const char *symbol;void *address; };
extern int dladdr(const void *,struct media_dl_info *);
static int p1_body_owner;
static void *p1_common_base,*p1_fsys_base;
static unsigned p1_body_receipts;
static int hash_file(const char *path,size_t expected,const char *digest) {
    /* /proc/self/exe is deliberately a symlink; DSO paths must not be. */
    int fd=open(path,!strcmp(path,"/proc/self/exe")?0:0x20000);
    if(fd<0) return 0;
    struct sha s;char actual[65];u8 buffer[4096];size_t total=0;start(&s);int ok=1;
    for(;;){long n=read(fd,buffer,sizeof buffer);if(n<0 && *__errno_location()==4)continue;
        if(n<0){ok=0;break;}if(!n)break;
        if((size_t)n>expected-total){ok=0;break;}total+=(size_t)n;update(&s,buffer,(size_t)n);}
    if(close(fd))ok=0;
    finish(&s,actual);return ok && total==expected && !strcmp(actual,digest);
}
static int p1_symbol(void *function,unsigned long offset,size_t file_size,const char *file_sha,
                     size_t text_size,const char *text_sha,void **base) {
    struct media_dl_info info;
    if(!function || !dladdr(function,&info) || !info.name || !info.base ||
       (unsigned long)function-(unsigned long)info.base!=offset ||
       !hash_file(info.name,file_size,file_sha)) return 0;
    struct sha s;char actual[65];start(&s);update(&s,function,text_size);finish(&s,actual);
    if(strcmp(actual,text_sha))return 0;
    if(base)*base=info.base;
    return 1;
}
static int p1_profile(void) {
    const char *p=getenv("A7C2_P1_FILE_MEDIA_PROFILE");
    return p && !strcmp(p,"original-sd-v1");
}
static int body_enabled(void) { return p1_profile() && p1_body_owner==getpid(); }
static int body_actor(void *caller,unsigned long low,unsigned long high) {
    unsigned long pc=(unsigned long)caller-(unsigned long)p1_common_base;
    return p1_common_base && low<=pc && pc<high;
}

#define PARAM_EXISTMEDIADRIVER 0x69u
#define PARAM_DBG_OMIT_WRITE   0xf9u
#define P1_PARAM_DBG_OMIT_WRITE 0xf6u

static unsigned configured_calls;
static unsigned int mounted_media_drive, busy;
static int mounted_media_owner;
static unsigned long long previous, cancel_pending, cancel_failures;

/* Observe only the two old-card files. A concurrent operation invalidates this
 * handle generation; original Fsys calls are never serialized by this mutex. */
struct read_file { unsigned long long handle,generation,offset; unsigned active;
    int file,used,known,conflict; };
struct read_token { unsigned long long handle,generation,offset; int slot,file,known; };
static struct read_file read_files[16];
static unsigned long long read_generation;
static unsigned read_receipts;
static int read_owner;
static pthread_mutex_t read_lock=PTHREAD_MUTEX_INITIALIZER;

static int read_owned(void) {
    int pid=getpid(),expected=0;
    __atomic_compare_exchange_n(&read_owner,&expected,pid,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
    return __atomic_load_n(&read_owner,__ATOMIC_ACQUIRE)==pid;
}

static int observed_path(const char *path) {
    if (!path || path[0]<'A' || path[0]>'Z' || path[1]!=':') return 0;
    if (!strcmp(path+2,"/PRIVATE/DATABASE/DATABASE.BIN")) return 1;
    if (!strcmp(path+2,"/PRIVATE/M4ROOT/MEDIAPRO.XML")) return 2;
    if (body_enabled() && !strcmp(path+2,"/BODYDATA.DAT")) return 3;
    return 0;
}

static void read_opened(unsigned long long handle,int file) {
    if (!read_owned()) return;
    pthread_mutex_lock(&read_lock);
    int empty=-1;
    for (int i=0;i<16;i++) {
        if (read_files[i].used && read_files[i].handle==handle) {
            if (read_files[i].active) { read_files[i].conflict=1; file=0; }
            read_files[i].used=0;
        }
        if (!read_files[i].used && !read_files[i].active && empty<0) empty=i;
    }
    if (file && empty>=0) read_files[empty]=(struct read_file){
        .handle=handle,.generation=++read_generation,.file=file,.used=1,.known=1};
    pthread_mutex_unlock(&read_lock);
}

static struct read_token read_begin(unsigned long long handle) {
    struct read_token token={.slot=-1};
    if (!read_owned()) return token;
    pthread_mutex_lock(&read_lock);
    for (int i=0;i<16;i++) if (read_files[i].used && read_files[i].handle==handle) {
        struct read_file *entry=&read_files[i];
        if (entry->active) entry->conflict=1;
        entry->active++;
        token=(struct read_token){.handle=handle,.generation=entry->generation,
            .offset=entry->offset,.slot=i,.file=entry->file,.known=entry->known};
        break;
    }
    pthread_mutex_unlock(&read_lock);
    return token;
}

static int read_end(struct read_token token,int operation,int result,long long offset,unsigned origin) {
    if (token.slot<0) return 0;
    pthread_mutex_lock(&read_lock);
    struct read_file *entry=&read_files[token.slot];
    int valid=entry->used && entry->generation==token.generation && !entry->conflict;
    entry->active--;
    if (valid) {
        if (operation==0 && result>=0) entry->offset+=(unsigned)result;
        else if (operation==1 && !result && origin==0 && offset>=0) {
            entry->offset=(unsigned long long)offset;entry->known=1;
        } else entry->known=0;
    }
    if (operation==2) entry->used=0;
    pthread_mutex_unlock(&read_lock);
    return valid && token.known;
}

static const char *test_mode(void) {
    const char *enabled = getenv("A7C2_FILE_MEDIA_TEST");
    if (!enabled || enabled[0] != '1' || enabled[1]) return 0;
    return enabled;
}

static void console_line(const char *text) {
    char line[240];
    int length = snprintf(line, sizeof line, "%s\n", text);
    if (length <= 0 || length >= (int)sizeof line) return;
    int fd = open("/dev/console", 1);
    if (fd < 0) return;
    write(fd, line, (unsigned long)length);
    close(fd);
}

static void *original_fsys(const char *name) {
    void *(*lookup)(void *, const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    void *function=lookup?lookup((void *)-1,name):0;
    if (!function) { console_line("FILE_MEDIA_FSYS_RESOLVE_FAILED"); _exit(126); }
    return function;
}

/* Wrapped only so a run can show that the ORIGINAL mount path really ran; the
 * result and every argument are passed through unchanged. */
int Fsys_Mount(const char *path, unsigned int flags, char *drive, const void *extra) {
    int (*function)(const char *, unsigned int, char *, const void *) =
        original_fsys("Fsys_Mount");
    int rc = function(path, flags, drive, extra);
    int saved_errno=*__errno_location();
    if (!rc && drive && path && (!strcmp(path,"/nondev/rm2") || !strcmp(path,"/dev/mmca"))) {
        __atomic_store_n(&mounted_media_owner,getpid(),__ATOMIC_RELEASE);
        __atomic_store_n(&mounted_media_drive,(unsigned char)*drive,__ATOMIC_RELEASE);
    }
    if (test_mode()) {
        char line[220];
        snprintf(line, sizeof line, "FILE_MEDIA_FSYS op=Mount path=%s flags=%#x drive=%u result=%d",
                 path ? path : "-", flags, (!rc && drive) ? (unsigned char)*drive : 0u, rc);
        console_line(line);
    }
    *__errno_location()=saved_errno;
    return rc;
}

/* Ported from native/file-media-config.c: publish reply before checking cancellation. */
static int flush_store(const char *path,const char *text,int length,int flags) {
    char temporary[120];
    int n=snprintf(temporary,sizeof temporary,"%s.new",path);
    if (length<=0 || n<=0 || n>=(int)sizeof temporary) return 0;
    int fd=open(temporary,flags,0600);
    int stored=fd>=0 && write(fd,text,(unsigned long)length)==length && !fsync(fd);
    if (fd>=0 && close(fd)) stored=0;
    return stored && !rename(temporary,path);
}

static int flush_store_cancelled(unsigned long long sequence) {
    char path[96],reply[180];
    snprintf(path,sizeof path,"/tmp/sd-flush.%llu.cancelled",sequence);
    int length=snprintf(reply,sizeof reply,"SD_FSYS_CANCELLED seq=%llu pid=%d\n",sequence,getpid());
    if (flush_store(path,reply,length,0x8241)) { cancel_failures=0; return 1; }
    int error=*__errno_location();
    if (cancel_failures!=~0ULL) cancel_failures++;
    if (cancel_failures<=8 || !(cancel_failures&(cancel_failures-1))) {
        printf("SD_FSYS_CANCELLED_FAILED seq=%llu errno=%d\n",sequence,error); fflush(0);
    }
    *__errno_location()=error;
    return 0;
}

static int flush_enter(void) {
    if (__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE) &&
        __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)!=getpid()) return 0;
    unsigned int expected=0;
    return __atomic_compare_exchange_n(&busy,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
}

void file_media_flush_cancel_retry(void) {
    if (!flush_enter()) return;
    if (cancel_pending && flush_store_cancelled(cancel_pending)) cancel_pending=0;
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);
}

/* Called only in the original model sender thread, never in the retry thread. */
void file_media_flush_pending(void) {
    if (!flush_enter()) return;
    if (cancel_pending) {
        if (!flush_store_cancelled(cancel_pending)) goto done;
        cancel_pending=0;
    }
    int fd=open("/tmp/sd-flush.request",0x8000);
    char request[96];
    long n=fd>=0?read(fd,request,sizeof request-1):-1;
    if (fd>=0) close(fd);
    if (n>0) {
        request[n]=0;
        unsigned long long sequence=0; char extra;
        if (sscanf(request,"%llu %c",&sequence,&extra)==1 && sequence>previous) {
            previous=sequence;
            unsigned int drive=__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE);
            int (*flush)(unsigned char)=original_fsys("Fsys_FlushVolume");
            int rc=drive?flush((unsigned char)drive):-1021;
            char path[96],reply[180];
            int length=snprintf(reply,sizeof reply,"SD_FSYS_FLUSH seq=%llu pid=%d drive=%u rc=%d\n",
                                sequence,getpid(),drive,rc);
            snprintf(path,sizeof path,"/tmp/sd-flush.%llu.reply",sequence);
            if (length<(int)sizeof reply && flush_store(path,reply,length,0x80c1) && !rc) {
                snprintf(path,sizeof path,"/tmp/sd-flush.%llu.cancel",sequence);
                fd=open(path,0x8000);
                int cancelled=fd>=0 || *__errno_location()!=2;
                if (fd>=0) close(fd);
                /* Target this sender: its ACK must only run after its STOP/CONT,
                 * not before a different thread eventually handles group SIGSTOP. */
                if (!cancelled && syscall(SYS_tgkill,getpid(),syscall(SYS_gettid),19)) {
                    printf("SD_FSYS_STOP_FAILED seq=%llu errno=%d\n",sequence,*__errno_location()); fflush(0);
                }
                cancel_pending=sequence;
                if (flush_store_cancelled(sequence)) cancel_pending=0;
            }
        }
    }
done:
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);
}

/* Same public ABI as the native deliverable; only the original result is logged. */
int Fsys_Open(const char *path, unsigned long long *handle, unsigned int flags) {
    int (*function)(const char *,unsigned long long *,unsigned int)=original_fsys("Fsys_Open");
    int rc=function(path,handle,flags);
    int saved_errno=*__errno_location();
    if (test_mode() && !rc && handle) {
        int file=observed_path(path);read_opened(*handle,file);
        if(file==3 && (!body_actor(__builtin_return_address(0),0x8d9c,0x8e08) ||
           function!=(void *)((unsigned long)p1_fsys_base+0x2ea78))) {
            struct read_token token=read_begin(*handle);read_end(token,3,-1,0,0);
        }
    }
    if (test_mode()) {
        char line[220];
        snprintf(line,sizeof line,"FILE_MEDIA_FSYS op=Open path=%.120s flags=%#x handle=%llx result=%d",
                 path?path:"-",flags,(!rc&&handle)?*handle:0,rc);
        console_line(line);
    }
    *__errno_location()=saved_errno;
    return rc;
}

int Fsys_Seek(unsigned long long handle, long long offset, unsigned int origin, void *output) {
    int (*function)(unsigned long long,long long,unsigned int,void *)=original_fsys("Fsys_Seek");
    struct read_token token=test_mode()?read_begin(handle):(struct read_token){.slot=-1};
    int rc=function(handle,offset,origin,output);
    int saved_errno=*__errno_location();
    unsigned long long position=~0ULL;
    if(!rc && token.slot>=0 && output)__builtin_memcpy(&position,output,sizeof position);
    else if(!rc && !origin && !offset)position=0;
    int associated=token.file!=3 || (body_actor(__builtin_return_address(0),0x8fe4,0x9094) &&
        function==(void *)((unsigned long)p1_fsys_base+0x2f8b0));
    if(associated && position<=0x7fffffffffffffffULL)
        read_end(token,1,rc,(long long)position,0);
    else read_end(token,3,-1,0,0);
    if (test_mode()) {
        char line[220];
        snprintf(line,sizeof line,"FILE_MEDIA_FSYS op=Seek handle=%llx offset=%lld origin=%u result=%d",
                 handle,offset,origin,rc);
        console_line(line);
    }
    *__errno_location()=saved_errno;
    return rc;
}

int Fsys_Unmount(unsigned char drive,unsigned int flags) {
    int (*function)(unsigned char,unsigned int)=original_fsys("Fsys_Unmount");
    int rc=function(drive,flags);
    int saved_errno=*__errno_location();
    if (test_mode()) {
        char line[160];
        snprintf(line,sizeof line,"FILE_MEDIA_FSYS op=Unmount drive=%u flags=%#x result=%d",
                 (unsigned)drive,flags,rc);
        console_line(line);
    }
    *__errno_location()=saved_errno;
    return rc;
}

int Fsys_Read(unsigned long long handle,void *buffer,int requested) {
    int (*function)(unsigned long long,void *,int)=original_fsys("Fsys_Read");
    struct read_token token=test_mode()?read_begin(handle):(struct read_token){.slot=-1};
    int rc=function(handle,buffer,requested);
    int saved_errno=*__errno_location();
    int result=rc;
    if(token.file==3 && (requested<0 || rc>requested || (rc>0 && !buffer) ||
       !body_actor(__builtin_return_address(0),0x8f2c,0x8fe4) ||
       function!=(void *)((unsigned long)p1_fsys_base+0x2edc0))) result=-1;
    int valid=read_end(token,0,result,0,0) && result==rc;
    if (token.file==3 && body_enabled() &&
        __atomic_fetch_add(&p1_body_receipts,1,__ATOMIC_RELAXED)<512) {
        unsigned count=valid && buffer && requested>0 && rc>0 && rc<=requested?(unsigned)rc:0;
        if(count>65536u)count=65536u;
        char digest[65]="-",line[320];
        if(count){struct sha s;start(&s);update(&s,buffer,count);finish(&s,digest);}
        int n=snprintf(line,sizeof line,"P1_BODY_READ pid=%d handle=%llx generation=%llu offset=%llu requested=%d actual=%d hashed=%u known=%d actor=%d sha256=%s",
            getpid(),handle,token.generation,token.offset,requested,rc,count,valid,
            body_actor(__builtin_return_address(0),0x8f2c,0x8fe4),digest);
        if (n>0 && n<(int)sizeof line-1) {
            int fd=open("/dev/console",1);
            if(fd>=0){line[n++]='\n';write(fd,line,(unsigned)n);close(fd);}
        }
    }
    /* Bound work and never inspect an error result or bytes beyond the real read. */
    if (token.file!=3 && valid && buffer && requested>0 && rc>0 && rc<=requested &&
        __atomic_fetch_add(&read_receipts,1,__ATOMIC_RELAXED)<64) {
        unsigned count=(unsigned)rc<65536u?(unsigned)rc:65536u;
        unsigned long long hash=0xcbf29ce484222325ULL;
        const unsigned char *bytes=buffer;
        for (unsigned i=0;i<count;i++) hash=(hash^bytes[i])*0x100000001b3ULL;
        char line[240];
        snprintf(line,sizeof line,"FILE_MEDIA_READ pid=%d file=%d handle=%llx generation=%llu offset=%llu requested=%d actual=%d hashed=%u fnv64=%016llx",
            getpid(),token.file,handle,token.generation,token.offset,requested,rc,count,hash);
        console_line(line);
    }
    *__errno_location()=saved_errno;
    return rc;
}

int Fsys_Close(unsigned long long handle) {
    int (*function)(unsigned long long)=original_fsys("Fsys_Close");
    struct read_token token=test_mode()?read_begin(handle):(struct read_token){.slot=-1};
    int rc=function(handle);
    int saved_errno=*__errno_location();
    read_end(token,2,rc,0,0);
    *__errno_location()=saved_errno;
    return rc;
}

/* Defined by rm-file.so (both are in LD_PRELOAD). Weak so the file-media preload
 * still works when the RM provider is not loaded at all. */
extern void rm_file_start_lazy(void) __attribute__((weak));

void mcmn_param_init(void) {
    void *(*lookup)(void *, const char *) = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    void (*original)(void) = lookup ? lookup((void *)-1, "mcmn_param_init") : 0;
    unsigned (*get)(int) = lookup ? lookup((void *)-1, "mcmn_param_getul") : 0;
    void (*set)(int, unsigned) = lookup ? lookup((void *)-1, "mcmn_param_setul") : 0;
    if (!original || original == mcmn_param_init || !get || !set) {
        console_line("FILE_MEDIA_CONFIG_RESOLVE_FAILED");
        _exit(126);
    }
    original();
    int saved_errno=*__errno_location();
    if (!test_mode()) { *__errno_location()=saved_errno; return; }
    struct media_dl_info info;
    int p1=dladdr(original,&info) &&
        (unsigned long)original-(unsigned long)info.base==0x418b4;
    if(p1 && (!p1_symbol(original,0x418b4,488280,
        "efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec",564,
        "0565daadc6a5ac9a77e806fbeeed26dce4b29006be92182369c758693d465288",0) ||
        !p1_symbol(get,0x40d4c,488280,
        "efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec",160,
        "972929856ffdac8e0b43bcc09e312e955f529291a7b5accd2d6e2ab3d372addf",0) ||
        !p1_symbol(set,0x41088,488280,
        "efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec",140,
        "9ae6f72273b80759fe34a147a6d101241b5ce74f530e9a6083ea6f3ab7d28236",0))) {
        console_line("P1_FILE_MEDIA_IDENTITY_FAILED");_exit(126);
    }
    if(p1_profile()) {
        if(!p1 || !hash_file("/proc/self/exe",10304,
            "c369699a8bbd8919e7951295c8f17d2229327b69484d5875f81e571f03d773af") ||
           !p1_symbol(lookup((void *)-1,"_ZN7Updater13SDFileManager10InitializeEv"),0xa758,60600,
            "1a6a3226993ce7c25659bd58e20871d91869083b31440650eec555a06d592d2f",236,
            "18b3689b0fc5973c5a82aa5fb510ac03178dda5f1ee469bef3f0e7f506d03249",0) ||
           !p1_symbol(lookup((void *)-1,"_ZN7Updater15FsysFileHandler4ReadEPvm"),0x8f2c,60152,
            "b601bf34b09ca34b74d9ee99f0de0b83d34fab30e3d2648468ab479a0bf6eb05",184,
            "e2b3e4b85d454397a4e11279a0a00ab32090c1a32e54fc051be441671697fa09",&p1_common_base) ||
           !p1_symbol(lookup((void *)-1,"Fsys_Read"),0x2edc0,638528,
            "ba0467674b056b3389a34ba974b1f0bbe99f4189d8aa36ad509843596ccacb62",16,
            "aa486af301553e45ed3a2fc0cea20c16e19494ae30974c6eec72294032ad8745",&p1_fsys_base)) {
            console_line("P1_BODY_IDENTITY_FAILED");_exit(126);
        }
        p1_body_owner=getpid();
    }
    unsigned omit_id=p1?P1_PARAM_DBG_OMIT_WRITE:PARAM_DBG_OMIT_WRITE;
    unsigned before = get((int)PARAM_EXISTMEDIADRIVER);
    set((int)PARAM_EXISTMEDIADRIVER, 0);
    unsigned after=get((int)PARAM_EXISTMEDIADRIVER),omit=get((int)omit_id);
    if(p1 && (after || omit)){console_line("P1_FILE_MEDIA_READBACK_FAILED");_exit(126);}
    if(p1)console_line("P1_FILE_MEDIA_BIND source_class=functional-adapter init=418b4 omit_id=f6 readback=1");
    configured_calls++;
    char line[200];
    snprintf(line, sizeof line,
             "FILE_MEDIA_CONFIG call=%u pid=%d EXISTMEDIADRIVER=%u->%u OMIT_WRITE=%u",
             configured_calls, getpid(), before, after, omit);
    console_line(line);
    fflush(0);
    /* The verified init hook is the right moment: osal is loaded by now, so the RM
     * provider can resolve its entry points (a constructor could not). */
    if (getenv("MENU_RM_FILE_IMAGE") && rm_file_start_lazy) rm_file_start_lazy();
    *__errno_location()=saved_errno;
}

unsigned file_media_configured(void) { return configured_calls; }
