/* SPDX-License-Identifier: MIT */
#include "pmbp-libc.h"
#include "pmbp-broker.h"
#include "pmbp-pins.h"
#include <dlfcn.h>
#include <errno.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#define CALLER ((uintptr_t)__builtin_extract_return_addr(__builtin_return_address(0)))
static struct pmbp_libc_io real;
static int (*real_open)(const char *,int,...);
static int (*real_ioctl)(int,unsigned long,...);
static atomic_int resolved;
static _Thread_local int resolving;
void *pmbp_next(const char *name) {
 void *(*lookup)(void *,const char *)=dlvsym(RTLD_NEXT,"dlsym",PMBP_DL_VERSION);
 return lookup ? lookup(RTLD_NEXT,name) : NULL;
}
static int op(const char *p,int f,mode_t m){return real_open(p,f,m);}
static int ioc(int f,unsigned long r,void *p){return real_ioctl(f,r,p);}
static int pin(int f){return real.fcntl(f,F_DUPFD_CLOEXEC,3);}
const struct pmbp_libc_io *pmbp_native_io(void) {
 int saved=errno;
 if(atomic_load_explicit(&resolved,memory_order_acquire)!=2) {
  if(resolving) _exit(126);
  int expected=0;
  if(atomic_compare_exchange_strong(&resolved,&expected,1)) {
   resolving=1;
#define RESOLVE(field,name) do { void *p=pmbp_next(name); if(!p) _exit(126); memcpy(&(field),&p,sizeof(p)); } while(0)
   RESOLVE(real_open,"open64"); RESOLVE(real.stat,"__fxstat64");
   RESOLVE(real.close,"close"); RESOLVE(real.write,"write");
   RESOLVE(real.pwrite,"pwrite64"); RESOLVE(real.pread,"pread64");
   RESOLVE(real_ioctl,"ioctl"); RESOLVE(real.read,"read"); RESOLVE(real.seek,"lseek64");
   RESOLVE(real.dup,"dup"); RESOLVE(real.dup2,"dup2"); RESOLVE(real.dup3,"dup3");
   RESOLVE(real.fcntl,"fcntl"); RESOLVE(real.pwritev,"pwritev64"); RESOLVE(real.fsync,"fsync");
#undef RESOLVE
   real.open=op; real.ioctl=ioc; real.duplicate=pin;
   resolving=0; atomic_store_explicit(&resolved,2,memory_order_release);
  } else {
   while(atomic_load_explicit(&resolved,memory_order_acquire)!=2) (void)syscall(SYS_sched_yield);
  }
 }
 errno=saved; return &real;
}
int pmbp_libc_identity(void) {
 (void)pmbp_native_io();
 const char *names[]={"open64","__fxstat64","close","write","pwrite64","pread64","ioctl","read","lseek64","dup","dup2","dup3","fcntl","pwritev64","fsync"};
 for(size_t i=0;i<sizeof(names)/sizeof(names[0]);i++)
  if(!pmbp_broker_native(names[i],pmbp_next(names[i]))) return 0;
 return 1;
}
/* Capture LR in this exported frame, then pass it explicitly through every layer. */
int open64(const char *p,int f,...) {
 uintptr_t caller=CALLER; mode_t m=0;
 if((f&O_CREAT)||((f&O_TMPFILE)==O_TMPFILE)){va_list a;va_start(a,f);m=(mode_t)va_arg(a,int);va_end(a);}
 (void)pmbp_native_io(); return pmbp_open64_at(p,f,m,caller);
}
int open(const char *,int,...) __attribute__((alias("open64")));
int __open64(const char *,int,...) __attribute__((alias("open64"),nonnull(1)));
int __open(const char *,int,...) __attribute__((alias("open64"),nonnull(1)));
int __open64_2(const char *p,int f){
 uintptr_t c=CALLER;
 if((f&O_CREAT)||((f&O_TMPFILE)==O_TMPFILE)) {
  int (*fn)(const char *,int)=NULL;void *q=pmbp_next("__open64_2");memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);return fn(p,f);
 }
 (void)pmbp_native_io();return pmbp_open64_at(p,f,0,c);
}
int __open_2(const char *,int) __attribute__((alias("__open64_2")));
int __fxstat64(int v,int f,struct stat *s){uintptr_t c=CALLER;(void)pmbp_native_io();int rc=pmbp_fxstat64_at(v,f,s,c),e=errno;pmbp_checkpoint("fstat",c,(uintptr_t)v,(uintptr_t)f,(uintptr_t)s,0,0,0,rc,e,0,0);errno=e;return rc;}
ssize_t write(int f,const void *p,size_t n){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_write_at(f,p,n,c);}
ssize_t pwrite64(int f,const void *p,size_t n,off_t o){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_pwrite64_at(f,p,n,o,c);}
ssize_t read(int f,void *p,size_t n){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_read_at(f,p,n,c);}
ssize_t pread64(int f,void *p,size_t n,off_t o){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_pread64_at(f,p,n,o,c);}
off_t lseek64(int f,off_t o,int w){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_lseek64_at(f,o,w,c);}
int close(int f){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_close_at(f,c);}
ssize_t pwritev64(int f,const struct iovec *v,int n,off_t o){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_pwritev64_at(f,v,n,o,c);}
int fsync(int f){uintptr_t c=CALLER;(void)pmbp_native_io();return pmbp_fsync_at(f,c);}
int ioctl(int fd,unsigned long request,...){
 uintptr_t c=CALLER;va_list a;va_start(a,request);
 /* Sony's fixed MediaCommon callsites pass an X2 argument for every ioctl. */
 void *arg=va_arg(a,void *);va_end(a);(void)pmbp_native_io();
 return pmbp_ioctl_at(fd,request,arg,c);
}
/* Unsupported owned-fd mappings cannot bypass write readback. */
void *mmap64(void *address,size_t bytes,int prot,int flags,int fd,off_t offset) {
 int incoming=errno;
 if(pmbp_reject_owned_mmap(fd))return MAP_FAILED;
 void *(*fn)(void *,size_t,int,int,int,off_t)=NULL;
 void *q=pmbp_next("mmap64");memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 errno=incoming;return fn(address,bytes,prot,flags,fd,offset);
}
void *mmap(void *,size_t,int,int,int,off_t) __attribute__((alias("mmap64")));
/* FILE ownership has no per-write witness, so owned fdopen is refused. */
FILE *fdopen(int fd,const char *mode) {
 int incoming=errno;
 if(pmbp_reject_owned_stdio(fd))return NULL;
 FILE *(*fn)(int,const char *)=NULL;
 void *q=pmbp_next("fdopen");memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 errno=incoming;return fn(fd,mode);
}
int dup(int f){(void)pmbp_native_io();return pmbp_dup(f);}
int dup2(int f,int t){(void)pmbp_native_io();return pmbp_dup2(f,t);}
int dup3(int f,int t,int flags){(void)pmbp_native_io();return pmbp_dup3(f,t,flags);}
static int fcntl_at(int fd,int cmd,va_list a) {
 const struct pmbp_libc_io *r=pmbp_native_io();
 switch(cmd) {
 case F_GETFD:case F_GETFL:case F_GETOWN:case F_GETSIG:case F_GETLEASE:case F_GETPIPE_SZ:case F_GET_SEALS:
  return r->fcntl(fd,cmd);
 case F_DUPFD:case F_DUPFD_CLOEXEC: return pmbp_fcntl_dup(fd,cmd,va_arg(a,int));
 case F_SETFD:case F_SETFL:case F_SETOWN:case F_SETSIG:case F_SETLEASE:case F_NOTIFY:case F_SETPIPE_SZ:case F_ADD_SEALS: {
  int value=va_arg(a,int);
  if(fd>=0 && fd==pmbp_status().owned_fd && cmd!=F_GETFD && cmd!=F_SETFD){errno=EPERM;return -1;}
  return r->fcntl(fd,cmd,value);
 }
 case F_GETLK:case F_SETLK:case F_SETLKW:case F_OFD_GETLK:case F_OFD_SETLK:case F_OFD_SETLKW:case F_GETOWN_EX:case F_SETOWN_EX:
#ifdef F_GET_RW_HINT
 case F_GET_RW_HINT:case F_SET_RW_HINT:case F_GET_FILE_RW_HINT:case F_SET_FILE_RW_HINT:
#endif
  return r->fcntl(fd,cmd,va_arg(a,void *));
 default: return r->fcntl(fd,cmd); /* Linux rejects unknown commands without reading arg. */
 }
}
int fcntl(int fd,int cmd,...){va_list a;va_start(a,cmd);int rc=fcntl_at(fd,cmd,a);va_end(a);return rc;}
int fcntl64(int fd,int cmd,...) __attribute__((alias("fcntl")));
/* Passive wrappers have exactly six machine arguments; NativeCtx stays opaque. */
typedef uint32_t (*native6)(uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t);
uint32_t pmbp_native6_at(const char *name,uintptr_t caller,uintptr_t frame,uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e,uintptr_t f) {
 int before=errno;void *q=pmbp_next(name);native6 fn=NULL;memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 int format=!strcmp(name,"Fsys_Format");
 if(format)(void)pmbp_format_scope(1,caller);
 errno=before;uint32_t rc=fn(a,b,c,d,e,f);int saved=errno;
 uint32_t word=0;unsigned valid=0;
 if(!strcmp(name,"mcmn_drv_getinfo")) valid=(unsigned)pmbp_copy_info(caller,frame,b,rc,&word);
 pmbp_checkpoint(name,caller,a,b,c,d,e,f,(long)rc,saved,valid,word);
 if(format)(void)pmbp_format_scope(0,caller);
 errno=saved;return rc;
}
#define SIX(name) uint32_t name(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e,uintptr_t f) { \
 uintptr_t caller=CALLER;uintptr_t frame=*(uintptr_t *)__builtin_frame_address(0); \
 return pmbp_native6_at(#name,caller,frame,a,b,c,d,e,f); }
SIX(Fsys_Format)
SIX(mcmn_drv_open)
SIX(mcmn_drv_getinfo)
SIX(mcmn_drv_dummy_open)
SIX(mcmn_init)
void fsysDep_LockDevice(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e,uintptr_t f) {
 int before=errno;void *q=pmbp_next("fsysDep_LockDevice");void (*fn)(uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t)=NULL;memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 (void)pmbp_mutex_scope(1,(int)a);errno=before;fn(a,b,c,d,e,f);int saved=errno;(void)pmbp_mutex_scope(2,(int)a);errno=saved;
}
void fsysDep_UnlockDevice(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e,uintptr_t f) {
 int before=errno;void *q=pmbp_next("fsysDep_UnlockDevice");void (*fn)(uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t)=NULL;memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 (void)pmbp_mutex_scope(0,(int)a);errno=before;fn(a,b,c,d,e,f);int saved=errno;errno=saved;
}
int pthread_mutex_lock(void *m) {
 uintptr_t caller=CALLER;int before=errno;void *q=pmbp_next("pthread_mutex_lock");int (*fn)(void *)=NULL;memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 errno=before;int rc=fn(m),saved=errno;pmbp_mutex_result(caller,m,rc,0);errno=saved;return rc;
}
int pthread_mutex_unlock(void *m) {
 uintptr_t caller=CALLER;int before=errno;void *q=pmbp_next("pthread_mutex_unlock");int (*fn)(void *)=NULL;memcpy(&fn,&q,sizeof(q));if(!fn)_exit(126);
 pmbp_mutex_result(caller,m,0,1);errno=before;return fn(m);
}
