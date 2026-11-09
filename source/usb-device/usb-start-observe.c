/* Passive, exact-identity USB tracing for the isolated 2.01 persistent profile. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <dlfcn.h>
#include <link.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/stat.h>
#include <sys/ioctl.h>

static int memfd=-1, logfd=-1;
static unsigned records, errors, capped;
static uintptr_t infra_base, control_base;
static void *(*next_dlopen)(const char *,int);
static void *(*lookup)(void *,const char *),*(*next_dlsym)(void *,const char *);
static __thread struct { uintptr_t self,msg; unsigned source,category; } context __attribute__((tls_model("initial-exec")));

/* Error reserve preserves the first real failures after the normal trace budget. */
static void emit(int error,const char *kind,const char *format,...) {
    int saved=errno; char line[1024];
    unsigned n=__atomic_fetch_add(error?&errors:&records,1,__ATOMIC_RELAXED);
    if(n>=(error?64u:768u)) {
        if(!__atomic_exchange_n(&capped,1,__ATOMIC_RELAXED) && logfd>=0)
            syscall(SYS_write,logfd,"USB_START CAP bounded=1\n",sizeof("USB_START CAP bounded=1\n")-1);
        errno=saved;return;
    }
    int prefix=snprintf(line,sizeof line,"USB_START %s tid=%ld ",kind,syscall(SYS_gettid));
    va_list args;va_start(args,format);
    vsnprintf(line+prefix,sizeof line-(size_t)prefix-2,format,args);va_end(args);
    size_t size=strlen(line);line[size++]='\n';
    if(logfd>=0)syscall(SYS_write,logfd,line,size);
    errno=saved;
}
static int readmem(uintptr_t p,void *out,size_t n) {
    int saved=errno;
    int ok=p && memfd>=0 && pread(memfd,out,n,(off_t)p)==(ssize_t)n;
    errno=saved;return ok;
}
static uint32_t word(uintptr_t p) {uint32_t v=0xffffffff;readmem(p,&v,4);return v;}
static uintptr_t pointer(uintptr_t p) {uintptr_t v=0;readmem(p,&v,8);return v;}
static int cstring(const char *p,char *out,size_t n) {
    for(size_t i=0;i<n;i++) {if(!readmem((uintptr_t)p+i,out+i,1))return 0;if(!out[i])return 1;}
    out[n-1]=0;return 0;
}
static void blob(const char *kind,uintptr_t p,size_t bytes) {
    unsigned char b[64];char hex[129];
    for(size_t off=0;off<bytes;off+=sizeof b) {
        size_t n=bytes-off;if(n>sizeof b)n=sizeof b;
        if(!readmem(p+off,b,n)){emit(1,"READ_FAILED","kind=%s ptr=%#lx offset=%zu bytes=%zu",kind,(unsigned long)p,off,n);return;}
        for(size_t i=0;i<n;i++)snprintf(hex+2*i,3,"%02x",b[i]);
        emit(0,kind,"ptr=%#lx offset=%zu bytes=%zu raw=%s",(unsigned long)p,off,n,hex);
    }
}
/* Linux 4.9 Sony LP64 ABI, bounded traversal of the actual START pointer tree. */
static void start_tree(uintptr_t p) {
    static unsigned seen;
    if(__atomic_fetch_add(&seen,1,__ATOMIC_RELAXED)>=4)return;
    unsigned char start[24],root[160];
    blob("START24",p,24);
    if(!readmem(p,start,sizeof start))return;
    uintptr_t table,serial;memcpy(&table,start,8);memcpy(&serial,start+8,8);
    blob("START_SERIAL",serial,start[16]);blob("DESC_ROOT",table,sizeof root);
    if(!readmem(table,root,sizeof root))return;
    for(unsigned speed=0;speed<3;speed++) {
        uintptr_t cfg;memcpy(&cfg,root+speed*24+8,8);
        unsigned count=root[speed*24+5];if(count>2){emit(1,"DESC_LIMIT","speed=%u configs=%u",speed,count);continue;}
        for(unsigned c=0;c<count;c++) {
            unsigned char config[48];uintptr_t cp=cfg+c*48,interfaces;
            blob("DESC_CONFIG",cp,48);if(!readmem(cp,config,48))continue;
            memcpy(&interfaces,config+8,8);unsigned nc=config[2];if(nc>4)continue;
            for(unsigned i=0;i<nc;i++) {
                unsigned char iface[16];uintptr_t ip=interfaces+i*16,tables;
                blob("DESC_INTERFACE",ip,16);if(!readmem(ip,iface,16))continue;
                memcpy(&tables,iface+8,8);unsigned nt=iface[1];if(nt>2)continue;
                for(unsigned t=0;t<nt;t++) {
                    unsigned char alt[40];uintptr_t ap=tables+t*40,eps;
                    blob("DESC_ALT",ap,40);if(!readmem(ap,alt,40))continue;
                    memcpy(&eps,alt+8,8);if(alt[1]<=6)blob("DESC_EP",eps,alt[1]*32u);
                }
            }
        }
    }
    uintptr_t langs;memcpy(&langs,root+88,8);unsigned nl=root[82];if(nl>4)return;
    for(unsigned l=0;l<nl;l++) {
        unsigned char lang[16];uintptr_t lp=langs+l*16,strings;
        blob("DESC_LANG",lp,16);if(!readmem(lp,lang,16))continue;
        memcpy(&strings,lang+8,8);if(lang[2]>16)continue;
        for(unsigned i=0;i<lang[2];i++) {
            unsigned char str[16];uintptr_t sp=strings+i*16,data;
            blob("DESC_STRING",sp,16);if(!readmem(sp,str,16))continue;
            memcpy(&data,str+8,8);blob("DESC_UTF16",data,str[1]);
        }
    }
}
static void *(*real_fopen)(const char *,const char *);
static int (*real_fputs)(const char *,void *),(*real_fclose)(void *);
static int (*real_open)(const char *,int,...),(*real_ioctl)(int,unsigned long,...);
static uintptr_t (*real_trace)(uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t);
#ifdef USB_RESOURCE_OBSERVE
#if USB_RESOURCE_OBSERVE != 1
#error "USB resource observations require explicit =1"
#endif
#include "usb-resources-observe.inc"
#endif
static int usbpath(const char *p) {return !strncmp(p,"/dev/usb/",9)||!strncmp(p,"/sys/devices/platform/soc/f1080000.usbs/",sizeof("/sys/devices/platform/soc/f1080000.usbs/")-1);}
static void *u_fopen(const char *p,const char *mode) {
    int saved=errno;char path[256],m[16]={0};int relevant=cstring(p,path,sizeof path)&&usbpath(path);
    cstring(mode,m,sizeof m);errno=saved;void *r=real_fopen(p,mode);int e=errno;
    if(relevant)emit(!r,"FOPEN","path=%s mode=%s lr=%p rc=%p errno=%d",path,m,__builtin_return_address(0),r,e);
    errno=e;return r;
}
static int u_fputs(const char *s,void *f) {
    int saved=errno;char text[16];int relevant=cstring(s,text,sizeof text)&&(!strcmp(text,"auto")||!strcmp(text,"on"));
    errno=saved;int r=real_fputs(s,f),e=errno;
    if(relevant)emit(r<0,"FPUTS","text=%s stream=%p lr=%p rc=%d errno=%d",text,f,__builtin_return_address(0),r,e);
    errno=e;return r;
}
static int u_fclose(void *f) {int r=real_fclose(f),e=errno;emit(r<0,"FCLOSE","stream=%p lr=%p rc=%d errno=%d",f,__builtin_return_address(0),r,e);errno=e;return r;}
static int u_open(const char *p,int flags,...) {
    int saved=errno;mode_t mode=0;int hasmode=(flags&O_CREAT)||((flags&O_TMPFILE)==O_TMPFILE);
    if(hasmode){va_list a;va_start(a,flags);mode=(mode_t)va_arg(a,int);va_end(a);}
    char path[256];int relevant=cstring(p,path,sizeof path)&&usbpath(path);errno=saved;
    int r=hasmode?real_open(p,flags,mode):real_open(p,flags),e=errno;
    if(relevant)emit(r<0,"OPEN","path=%s flags=%#x mode=%#x lr=%p rc=%d errno=%d",path,flags,mode,__builtin_return_address(0),r,e);
    errno=e;return r;
}
static int u_ioctl(int fd,unsigned long req,...) {
    int saved=errno;uintptr_t arg=0;
    /* Sony _IO requests carry no third machine argument. Never va_arg them. */
    int hasarg=_IOC_DIR(req)!=_IOC_NONE || _IOC_SIZE(req)!=0;
    if(hasarg){va_list a;va_start(a,req);arg=va_arg(a,uintptr_t);va_end(a);}
    int relevant=((req>>8)&255)>=0xe0&&((req>>8)&255)<=0xef;
    if(relevant){
#ifdef USB_RESOURCE_OBSERVE
        resource_ioctl(fd,req,arg,0,0,saved);
#endif
        emit(0,"IOCTL_ENTER","fd=%d req=%#lx hasarg=%d arg=%#lx lr=%p",fd,req,hasarg,(unsigned long)arg,__builtin_return_address(0));if(req==0x4018e203)start_tree(arg);
    }
    errno=saved;int r=hasarg?real_ioctl(fd,req,arg):real_ioctl(fd,req),e=errno;
    if(relevant){
#ifdef USB_RESOURCE_OBSERVE
        resource_ioctl(fd,req,arg,1,r,e);
#endif
        emit(r<0,"IOCTL_RETURN","fd=%d req=%#lx rc=%d errno=%d",fd,req,r,e);
    }
    errno=e;return r;
}
static uintptr_t u_trace(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e) {
    int saved=errno;
    if(a==0x21||a==0x22||a==0x23||a==0x27)emit(0,"TRACE","token=%#lx a1=%#lx a2=%#lx a3=%#lx a4=%#lx lr=%p",a,b,c,d,e,__builtin_return_address(0));
    errno=saved;return real_trace(a,b,c,d,e);
}
static uint32_t (*real_openSvc)(uintptr_t);
static uintptr_t (*real_infra)(uintptr_t,uint32_t,uintptr_t),(*real_create)(uintptr_t);
static uint32_t (*real_start)(uintptr_t,uint32_t,uintptr_t,uint32_t,uintptr_t);
static uintptr_t (*real_process)(uintptr_t,uint32_t,uintptr_t),(*real_complete)(uint32_t,uintptr_t,int32_t);
static uint32_t (*real_mid)(uintptr_t),(*real_category)(uintptr_t);
static uint32_t u_openSvc(uintptr_t svc) {
    int saved=errno;emit(0,"OPEN_SVC_ENTER","svc=%#lx state=%u",svc,word(svc+0xe4));errno=saved;
    uint32_t r=real_openSvc(svc);int e=errno;emit(r!=0,"OPEN_SVC_RETURN","svc=%#lx state=%u rc=%u errno=%d",svc,word(svc+0xe4),r,e);errno=e;return r;
}
static uintptr_t u_infra(uintptr_t ops,uint32_t did,uintptr_t cb) {
    int saved=errno;emit(0,"INFRA_ENTER","ops=%#lx did=%u callback=%#lx",ops,did,cb);errno=saved;
    uintptr_t r=real_infra(ops,did,cb);int e=errno;emit(r!=0,"INFRA_RETURN","did=%u rc=%#lx errno=%d",did,r,e);errno=e;return r;
}
static uint32_t u_start(uintptr_t svc,uint32_t did,uintptr_t arg,uint32_t len,uintptr_t cb) {
    int saved=errno;emit(0,"SVC_START_ENTER","svc=%#lx state=%u did=%u cbarg=%#lx length=%u callback=%#lx",svc,word(svc+0xe4),did,arg,len,cb);errno=saved;
    uint32_t r=real_start(svc,did,arg,len,cb);int e=errno;emit(r!=0,"SVC_START_RETURN","svc=%#lx state=%u rc=%u errno=%d",svc,word(svc+0xe4),r,e);errno=e;return r;
}
static uintptr_t u_create(uintptr_t msg) {
    int saved=errno;uintptr_t svc=pointer(msg);
    emit(0,"CREATE_ENTER","message=%#lx svc=%#lx state=%u",msg,svc,word(svc+0xe4));blob("CREATE_MESSAGE",msg,32);errno=saved;
    uintptr_t r=real_create(msg);int e=errno;emit(r!=0,"CREATE_RETURN","message=%#lx svc=%#lx state=%u rc=%#lx errno=%d",msg,svc,word(svc+0xe4),r,e);errno=e;return r;
}
static uintptr_t u_process(uintptr_t self,uint32_t source,uintptr_t msg) {
    int saved=errno;__typeof__(context) previous=context;
    context.self=self;context.source=source;context.msg=msg;context.category=0;
    emit(0,"PROCESS_ENTER","self=%#lx source=%#x msg=%#lx mask108=%#x mask10c=%#x",self,source,msg,word(self+0x108),word(self+0x10c));errno=saved;
    uintptr_t r=real_process(self,source,msg);int e=errno;context=previous;errno=e;return r;
}
static uint32_t u_category(uintptr_t msg) {uint32_t r=real_category(msg);int e=errno;if(context.msg==msg)context.category=r;errno=e;return r;}
static uint32_t u_mid(uintptr_t msg) {
    uint32_t r=real_mid(msg);int e=errno;
    if(context.msg==msg)emit(0,"MESSAGE_ID","self=%#lx source=%#x msg=%#lx category=%#x id=%#x mask108=%#x mask10c=%#x",context.self,context.source,msg,context.category,r,word(context.self+0x108),word(context.self+0x10c));
    errno=e;return r;
}
static uintptr_t u_complete(uint32_t event,uintptr_t arg,int32_t status) {
    int saved=errno;emit(status!=0,"COMPLETE_ENTER","event=%#x arg=%#lx status=%d",event,arg,status);
#ifdef USB_RESOURCE_OBSERVE
    if(resource_live())resource_emit("COMPLETE_ENTER","event=%#x argument=%#lx status=%d qid_raw=%#x",event,arg,status,control_base?word(control_base+0x30a68):UINT32_MAX);
#endif
    errno=saved;
    uintptr_t r=real_complete(event,arg,status);int e=errno;emit(0,"COMPLETE_RETURN","event=%#x rc=%#lx errno=%d",event,r,e);errno=e;return r;
}

#include "usb-msc-sender.inc"

/* Compact SHA-256 keeps verification inside the process, before installing hooks. */
static uint32_t rr(uint32_t x,unsigned n){return(x>>n)|(x<<(32-n));}
static const uint32_t k[64]={
0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
static int identity(const char *path,size_t size,const char *expected) {
    int fd=(int)syscall(SYS_openat,AT_FDCWD,path,O_RDONLY|O_NOFOLLOW,0);if(fd<0)return 0;
    struct stat st;int ok=!syscall(SYS_fstat,fd,&st)&&S_ISREG(st.st_mode)&&(size_t)st.st_size==size;
    unsigned char *data=malloc(size+128);if(!data){close(fd);return 0;}
    size_t got=0;while(ok&&got<size){ssize_t n=read(fd,data+got,size-got);if(n<=0)ok=0;else got+=(size_t)n;}close(fd);
    if(!ok){free(data);return 0;}
    uint32_t h[8]={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    size_t total=(size+9+63)&~63UL;memset(data+size,0,total-size);data[size]=0x80;
    for(unsigned i=0;i<8;i++)data[total-1-i]=(unsigned char)(((uint64_t)size*8)>>(i*8));
    for(size_t off=0;off<total;off+=64){uint32_t w[64],v[8];memcpy(v,h,32);
        for(unsigned i=0;i<16;i++)w[i]=((uint32_t)data[off+4*i]<<24)|((uint32_t)data[off+4*i+1]<<16)|((uint32_t)data[off+4*i+2]<<8)|data[off+4*i+3];
        for(unsigned i=16;i<64;i++)w[i]=w[i-16]+(rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3))+w[i-7]+(rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10));
        for(unsigned i=0;i<64;i++){uint32_t a=v[7]+(rr(v[4],6)^rr(v[4],11)^rr(v[4],25))+((v[4]&v[5])^(~v[4]&v[6]))+k[i]+w[i];uint32_t b=(rr(v[0],2)^rr(v[0],13)^rr(v[0],22))+((v[0]&v[1])^(v[0]&v[2])^(v[1]&v[2]));for(unsigned j=7;j;j--)v[j]=v[j-1];v[4]+=a;v[0]=a+b;}
        for(unsigned i=0;i<8;i++)h[i]+=v[i];
    }
    char hex[65];for(unsigned i=0;i<8;i++)snprintf(hex+i*8,9,"%08x",h[i]);free(data);return ok&&!strcmp(hex,expected);
}
#define USB_APP_BYTES 99960744
static int slot_matches(uintptr_t base,void *old,void *target,unsigned plt0) {
    return old==target || old==(void *)(base+plt0);
}
static void fatal(const char *why){
    emit(1,"GUARD_FAILED","reason=%s",why);
    char line[320];int n=snprintf(line,sizeof line,"USB_START_GUARD_FAILED reason=%s\n",why);
    if(n>0)syscall(SYS_write,2,line,(size_t)n<sizeof line?(size_t)n:sizeof line-1);
    syscall(SYS_exit_group,79);__builtin_unreachable();
}
#if defined(USB_EE_ZERO_OBSERVER) && defined(USB_EE_NORMAL_COLD)
#error "EE zero and functional modes are mutually exclusive"
#endif
#if defined(USB_EE_ZERO_OBSERVER) || defined(USB_EE_NORMAL_COLD)
#define USB_EE_OBSERVER 1
#endif
#ifdef USB_EE_NORMAL_COLD
#include "ee-normal-wake-cold.h"
struct ee_cold_slot {
    pid_t pid;uint64_t epoch,serial;uintptr_t message,receiver;
    unsigned state,have_source,have_size,model,observed;uint32_t source;int32_t size;
    struct ee_nwc_lease lease;
};
struct ee_cold_ticket { struct ee_cold_slot slot; unsigned valid,index,owner; uintptr_t actor; };
static void ee_cold_queue(uintptr_t,uintptr_t,uintptr_t,int);
static void ee_cold_recv_enter(void);
static void ee_cold_wait(uintptr_t);
static void ee_cold_wait_return(uintptr_t);
static void ee_cold_receive(uintptr_t);
static void ee_cold_recv_return(uintptr_t,int);
static void ee_cold_metadata(uintptr_t,int,uint32_t);
static struct ee_cold_ticket ee_cold_free_enter(uint32_t,uintptr_t);
static void ee_cold_free(struct ee_cold_ticket,int32_t);
#ifndef USB_OBSERVE_HOST_TEST
static void ee_cold_check(uintptr_t);
static void ee_cold_install(uintptr_t);
#endif
#endif
#ifndef USB_OBSERVE_HOST_TEST
static void cache(void *p,size_t n) {
#ifdef __aarch64__
    uintptr_t a=(uintptr_t)p&~63UL,end=(uintptr_t)p+n;
    for(;a<end;a+=64)__asm__ volatile("dc cvau,%0"::"r"(a):"memory");
    __asm__ volatile("dsb ish":::"memory");
    for(a=(uintptr_t)p&~63UL;a<end;a+=64)__asm__ volatile("ic ivau,%0"::"r"(a):"memory");
    __asm__ volatile("dsb ish;isb":::"memory");
#else
    (void)p;(void)n;
#endif
}
struct entry {unsigned offset;uint32_t bytes[4];void *wrapper;void **original;};
static void entry_install(uintptr_t base,struct entry *e) {
    uint32_t *p=(void *)(base+e->offset);
    if(memcmp(p,e->bytes,16))fatal("entry bytes drift");
    blob("ENTRY_ORIGINAL_WINDOW",(uintptr_t)p,64);
    unsigned char *tr=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(tr==MAP_FAILED)fatal("trampoline allocation");memcpy(tr,p,16);
    /* Only createGadget's verified ADRP occurs in these copied prologues. */
    if(e->offset==0x155fc){((uint32_t *)tr)[1]=0x580000e1;*(uintptr_t *)(tr+32)=base+0x1d000;}
#ifdef USB_RESOURCE_OBSERVE
    /* doSyncStartStop uses X20's exact original page at copied instruction +12. */
    if(e->offset==0x18bb0){((uint32_t *)tr)[3]=0x580000b4;*(uintptr_t *)(tr+32)=base+0x30000;}
#endif
#ifdef USB_EE_NORMAL_COLD
    /* Exact reader ADRP X0 at +4; literal +32 preserves the original page. */
    if(e->offset==0x3549218){((uint32_t *)tr)[1]=0x580000e0;*(uintptr_t *)(tr+32)=base+0x9116000;}
#endif
    /* ProcessMsg starts with CBNZ X2 to original +20; the fallthrough resumes at +16. */
    if(e->offset==0x5d70){((uint32_t *)tr)[0]=0xb5000142;((uint32_t *)tr)[10]=0x58000050;((uint32_t *)tr)[11]=0xd61f0200;*(uintptr_t *)(tr+48)=base+0x5d84;}
    ((uint32_t *)tr)[4]=0x58000050;((uint32_t *)tr)[5]=0xd61f0200;*(uintptr_t *)(tr+24)=(uintptr_t)p+16;
    cache(tr,56);if(mprotect(tr,4096,PROT_READ|PROT_EXEC))fatal("trampoline protect");*e->original=tr;
    uintptr_t page=(uintptr_t)p&~4095UL;if(mprotect((void *)page,4096,7))fatal("entry writable");
    p[0]=0x58000050;p[1]=0xd61f0200;memcpy(p+2,&e->wrapper,8);cache(p,16);
    if(mprotect((void *)page,4096,5))fatal("entry restore protection");
    emit(0,"ENTRY_ARMED","base=%#lx offset=%#x original=%p trampoline=%p wrapper=%p",base,e->offset,(void *)p,tr,e->wrapper);
}
static void got(uintptr_t base,unsigned offset,const char *name,void *wrapper,void **original) {
    void **slot=(void *)(base+offset);void *old=*slot,*target=lookup(RTLD_NEXT,name);Dl_info info;
    if(!target && !strcmp(name,"usb_trace_out"))target=(void *)(base+0x18ae8);
    if(base==msc_base && offset==0x1f290)target=(void *)(base+0x6434);
    if(base==msc_base && offset==0x1f218)target=(void *)(base+0x855c);
    if(!target||!dladdr(old,&info))fatal("GOT original mapping");
    /* Lazy slots must still point into this DSO; resolved slots must match scope. */
    unsigned plt0=base==msc_base ? 0x5090 : (base==infra_base || offset>=0x34000 ? 0xdf80 : 0xa680);
#ifdef USB_EE_OBSERVER
    if(base==app_base)plt0=0x165cfd0;
#endif
    if(!slot_matches(base,old,target,plt0))fatal("GOT original slot drift");
    *original=old==target?old:target;
    uintptr_t page=(uintptr_t)slot&~4095UL;if(mprotect((void *)page,4096,3))fatal("GOT writable");*slot=wrapper;
    /* These original jump slots are in the writable .got.plt PT_LOAD. */
    emit(0,"GOT_ARMED","base=%#lx offset=%#x name=%s old=%p target=%p wrapper=%p",base,offset,name,old,*original,wrapper);
}
#endif
#ifdef USB_EE_OBSERVER
#include "usb-ee-zero-observe.inc"
#endif
#ifdef USB_EE_NORMAL_COLD
#include "usb-ee-normal-cold.inc"
#endif
#ifndef USB_OBSERVE_HOST_TEST
static int find_dso(struct dl_phdr_info *info,size_t size,void *arg) {
    (void)size;(void)arg;const char *leaf=strrchr(info->dlpi_name,'/');leaf=leaf?leaf+1:info->dlpi_name;
    int app=!strcmp(leaf,"appFw.so"),msc=!strcmp(leaf,"libInfraMscServer.so");
    int infra=!strcmp(leaf,"libInfraUsbCmn.so"),control=!strcmp(leaf,"libUsbControl.so");
    if(!infra&&!control&&!msc&&!app)return 0;uintptr_t base=info->dlpi_addr;
    if((infra&&infra_base)||(control&&control_base)||(msc&&msc_base)||(app&&app_base))return 0;
    const char *sha=app?"2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b":msc?"3802b00e6cd5961e703f03c2b6f2e3f08a35323dc019921f73f29b8f9c813938":infra?"6caefd0677ee01cc6cdd54555f4422b03a86d12304c60f5372de18315bdd4396":"2baa5ad90a468751e5a7c8e7db3221ac39b53427ed4360c35dce80ec3520c39c";
    size_t bytes=app?USB_APP_BYTES:msc?64456:infra?159504:135424;
    char path[256];snprintf(path,sizeof path,"/usr/lib/%s",leaf);
    if(strcmp(path,info->dlpi_name)||!identity(path,bytes,sha))fatal("DSO path/SHA256");
    Dl_info mapped;if(!dladdr((void *)(base+(app?0x34796b0:msc?0x6478:infra?0x134c8:0x14a90)),&mapped)||(uintptr_t)mapped.dli_fbase!=base||strcmp(mapped.dli_fname,info->dlpi_name))fatal("DSO mapping identity");
    emit(0,"DSO_IDENTITY","path=%s map=%s base=%#lx bytes=%zu sha256=%s pid=%ld",path,info->dlpi_name,base,bytes,sha,(long)getpid());
    if(app){
        struct entry entries[]={
#ifdef USB_RESOURCE_OBSERVE
            {0x34e552c,{0xa9b87bfd,0x910003fd,0xa9025bf5,0x9101c3b6},u_resource_rpc,(void **)&real_resource_rpc},
#endif
            {0x34796b0,{0xa9b27bfd,0x52800001,0x910003fd,0xa90153f3},u_ap_run,(void **)&real_ap_run},
            {0x354db04,{0xa9b87bfd,0x52820062,0x52874001,0x910003fd},u_ap_send,(void **)&real_ap_send}};
        for(unsigned i=0;i<sizeof entries/sizeof *entries;i++)entry_install(base,entries+i);
        app_base=base;
#ifdef USB_EE_OBSERVER
        ee_install(base);
#endif
    }else if(msc){
        struct entry entries[]={
            {0x5d70,{0xb50000a2,0x52800041,0x52805042,0x2a0103e0},u_msc_process,(void **)&real_msc_process},
            {0x6478,{0xa9b77bfd,0x52860062,0x72a00102,0x910003fd},u_configure,(void **)&real_configure},
            {0xa0c4,{0xa9bc7bfd,0x528002a1,0x528000e0,0x910003fd},u_connect,(void **)&real_connect},
            {0x9efc,{0xa9b87bfd,0x910003fd,0xa90153f3,0xa9025bf5},u_lower,(void **)&real_lower}};
        for(unsigned i=0;i<4;i++)entry_install(base,entries+i);
        msc_base=base;
        got(base,0x1f018,"_ZNK3MWF6ObjMsg12GetMessageIdEv",u_msc_mid,(void **)&real_msc_mid);
        got(base,0x1f180,"_ZNK3MWF6ObjMsg13GetCategoryIdEv",u_msc_category,(void **)&real_msc_category);
        got(base,0x1f290,"_ZN17MassStorageServer29ParamCheck_CONFIGURE_FUNC_CMDEPN3MWF6ObjMsgE",u_check,(void **)&real_check);
        got(base,0x1f0f0,"_ZN3UFW9MsgSender22SendAsyncCmdAndWaitCmpEPN3MWF6ObjMsgES3_PFNS1_5ErrCdEPvS3_ES5_",u_async_wait,(void **)&real_async_wait);
        got(base,0x1f218,"_ZN17MassStorageServer17SndMsgToUpperSyncEPS_PN3MWF6ObjMsgEj",u_upper,(void **)&real_upper);
        got(base,0x1f208,"_ZN3UFW9MsgSender7SendCmdEPN3MWF6ObjMsgES3_",u_sendcmd,(void **)&real_sendcmd);
    }else if(infra){
        struct entry entries[]={
#ifdef USB_RESOURCE_OBSERVE
            {0x1040c,{0xa9bc7bfd,0x910003fd,0xa90153f3,0xaa0003f3},u_gadget_create,(void **)&real_gadget_create},
            {0x11d14,{0xa9bc7bfd,0x910003fd,0xa90153f3,0xaa0003f4},u_svc_notify,(void **)&real_svc_notify},
            {0x11d7c,{0x53001c21,0xa9b97bfd,0x7100143f,0x910003fd},u_gadget_event,(void **)&real_gadget_event},
            {0x14120,{0xa9b57bfd,0xaa0103e0,0x52800001,0x910003fd},u_ko_insmod,(void **)&real_ko_insmod},
            {0x18cb4,{0xa9b57bfd,0x52800041,0x910003fd,0xa90153f3},u_sen_create,(void **)&real_sen_create},
            {0x19cbc,{0xa9b47bfd,0x910003fd,0xa90153f3,0xaa0003f3},u_storage_create,(void **)&real_storage_create},
#endif
            {0x134c8,{0xa9b47bfd,0x910003fd,0xa9025bf5,0xb940e415},u_openSvc,(void **)&real_openSvc},
            {0x139b8,{0xa9bc7bfd,0x910003fd,0xa9025bf5,0x53001c75},u_start,(void **)&real_start},
            {0x155fc,{0xa9b37bfd,0x90000041,0x91067021,0x910003fd},u_create,(void **)&real_create},
            {0x17620,{0xa9bb7bfd,0x2a0103e4,0x52800003,0x910003fd},u_infra,(void **)&real_infra}};
        for(unsigned i=0;i<sizeof entries/sizeof *entries;i++)entry_install(base,entries+i);
        got(base,0x34530,"fopen",u_fopen,(void **)&real_fopen);got(base,0x34038,"fputs",u_fputs,(void **)&real_fputs);
        got(base,0x341c0,"fclose",u_fclose,(void **)&real_fclose);got(base,0x34180,"open",u_open,(void **)&real_open);
        got(base,0x34310,"ioctl",u_ioctl,(void **)&real_ioctl);got(base,0x34230,"usb_trace_out",u_trace,(void **)&real_trace);
        infra_base=base;
    } else {
        struct entry entries[]={
#ifdef USB_RESOURCE_OBSERVE
            {0x166d4,{0xa9bd7bfd,0x910003fd,0xf9401000,0xa90153f3},u_control_start,(void **)&real_control_start},
            {0x16810,{0xa9ba7bfd,0x910003fd,0xf9401000,0xa90153f3},u_control_configure,(void **)&real_control_configure},
            {0x16a94,{0xa9be7bfd,0x910003fd,0xf9000bf3,0xaa0203f3},u_control_start_entry,(void **)&real_control_start_entry},
            {0x18150,{0xa9bd7bfd,0x7100103f,0x910003fd,0xb9403004},u_wrapper_start,(void **)&real_wrapper_start},
            {0x18a64,{0xa9bb7bfd,0x7100dc3f,0x910003fd,0xa90363f7},u_do_start,(void **)&real_do_start},
            {0x18bb0,{0xa9bb7bfd,0x910003fd,0xa90153f3,0x900000d4},u_sync_startstop,(void **)&real_sync_startstop},
#endif
            {0x14a90,{0xa9b87bfd,0x910003fd,0xa90153f3,0xaa0003f3},u_process,(void **)&real_process},
            {0x188a4,{0xa9bd7bfd,0x7140401f,0x910003fd,0xa90153f3},u_complete,(void **)&real_complete}};
        for(unsigned i=0;i<sizeof entries/sizeof *entries;i++)entry_install(base,entries+i);
        got(base,0x30078,"_ZNK3MWF6ObjMsg12GetMessageIdEv",u_mid,(void **)&real_mid);
        got(base,0x30398,"_ZNK3MWF6ObjMsg13GetCategoryIdEv",u_category,(void **)&real_category);
        control_base=base;
    }
    emit(0,"INSTALLED","dso=%s before_init=1",leaf);return 0;
}
__attribute__((constructor)) static void initialize(void) {
    int saved=errno;lookup=dlvsym(RTLD_NEXT,"dlsym","GLIBC_2.17");if(!lookup)syscall(SYS_exit_group,79);
    next_dlopen=lookup(RTLD_NEXT,"dlopen");next_dlsym=lookup(RTLD_NEXT,"dlsym");
    logfd=(int)syscall(SYS_openat,AT_FDCWD,"/dev/qemu-simulation/usb-start-observe.log",O_WRONLY|O_APPEND|O_CREAT|O_CLOEXEC,0600);
    memfd=(int)syscall(SYS_openat,AT_FDCWD,"/proc/self/mem",O_RDONLY|O_CLOEXEC,0);
    if(!next_dlopen||!next_dlsym||logfd<0||memfd<0)fatal("observer setup");
#ifdef USB_EE_NORMAL_COLD
    emit(0,"INITIALIZED","pid=%ld passive=0 functional_model=1 mode=ee-normal-wake-cold-functional-v1",(long)getpid());
#else
    emit(0,"INITIALIZED","pid=%ld passive=1",(long)getpid());
#endif
    errno=saved;
}
static void *usb_loader_dlopen(const char *name,int flags) {
    if(!next_dlopen)initialize();
    void *handle=next_dlopen(name,flags);int saved=errno;
    if(handle)dl_iterate_phdr(find_dso,0);errno=saved;return handle;
}
static void *usb_loader_dlsym(void *handle,const char *name) {
    if(!lookup)initialize();
    /* Native caches both loaders through this resolver; local addresses cannot bind back to native. */
    if(handle==RTLD_NEXT) {
        if(!strcmp(name,"dlopen"))return usb_loader_dlopen;
        if(!strcmp(name,"dlsym"))return usb_loader_dlsym;
    }
    void *result=next_dlsym(handle,name);int saved=errno;
    if(result&&!strcmp(name,"Application_System_Init")) {
        dl_iterate_phdr(find_dso,0);
        if(!app_base)fatal("AP taps absent before Init resolution");
#ifdef USB_EE_OBSERVER
        ee_preinit();
#endif
        emit(0,"AP_PREINIT_CONFIRMED","pid=%ld base=%#lx resolved=%p both_entries=1",(long)getpid(),app_base,result);
    }
    errno=saved;return result;
}
void *dlopen(const char *,int) __attribute__((alias("usb_loader_dlopen")));
void *dlsym(void *,const char *) __attribute__((alias("usb_loader_dlsym")));
#endif
