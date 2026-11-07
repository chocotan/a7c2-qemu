/* SPDX-License-Identifier: MIT
 * Software provenance under a root-owned fixed virtual profile; not hardware attestation. */
#include "pmbp-broker.h"
#include "pmbp-libc.h"
#include "pmbp-pins.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/wait.h>
#include <unistd.h>
#include <linux/fs.h>
extern unsigned char *SHA256(const unsigned char *,size_t,unsigned char *);
#ifdef __aarch64__
/* Build headers are newer than the original 2.25 runtime. */
extern int pmbp_scan(const char *,const char *,...) __asm__("__isoc99_sscanf");
extern unsigned long long pmbp_number(const char *,char **,int) __asm__("strtoull");
#define sscanf pmbp_scan
#define strtoull pmbp_number
#endif
static struct pmbp_manifest manifest;
static struct pmbp_runtime_marker marker;
static struct pmbp_contract contract;
static struct pmbp_broker_state state;
static int rootfd=-1, initialised;
static char checked_root[PATH_MAX];
static _Thread_local int checking,format_depth,device_scope,device_locked;
static _Thread_local void *held_mutex;
static atomic_uint checkpoints, retries;
static _Atomic uint64_t tid_claim;
static int raw_stat(int fd,struct stat *st){return (int)syscall(SYS_fstat,fd,st);}
static uid_t trusted_uid(void){
#ifdef PMBP_SYNTHETIC_LAYER
 const char *test=getenv("PMBP_CASE");
 return geteuid()+(uid_t)(test&&!strcmp(test,"bad-owner"));
#else
 return 0;
#endif
}
static int uid_ok(uid_t uid){return uid==0 || uid==trusted_uid();}
static int failure(int error){
#ifdef PMBP_SYNTHETIC_LAYER
 char line[256];Dl_info here={0};void *pc=__builtin_return_address(0);(void)dladdr(pc,&here);int n=snprintf(line,sizeof(line),"SYNTHETIC_ADMISSION_REJECT errno=%d host=%u source=%u pc=%llx\n",error,state.host_provisioned,state.source_derived,(unsigned long long)((uintptr_t)pc-(uintptr_t)here.dli_fbase));if(n>0&&(size_t)n<sizeof(line))(void)syscall(SYS_write,2,line,(size_t)n);
#endif
 state.admission_errno=error;errno=error;return -1;
}
static int rawclose(int fd){return (int)syscall(SYS_close,fd);}
static int secure_absolute(const char *path,int flags,int directory) {
 if(!path || path[0]!='/' || strlen(path)>=PATH_MAX){errno=EINVAL;return -1;}
 char copy[PATH_MAX];strcpy(copy,path);
 int fd=(int)syscall(SYS_openat,AT_FDCWD,"/",O_RDONLY|O_DIRECTORY|O_CLOEXEC,0);
 if(fd<0)return -1;
 char *save=NULL,*part=strtok_r(copy,"/",&save);
 if(!part){if(directory)return fd;rawclose(fd);errno=EINVAL;return -1;}
 while(part){
  if(!strcmp(part,".")||!strcmp(part,"..")){rawclose(fd);errno=EINVAL;return -1;}
  char *following=strtok_r(NULL,"/",&save);
  int next=(int)syscall(SYS_openat,fd,part,(following?O_RDONLY|O_DIRECTORY:flags)|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK,0);
  int saved=errno;rawclose(fd);if(next<0){errno=saved;return -1;}
  struct stat st;
  if(raw_stat(next,&st)||!uid_ok(st.st_uid)||(st.st_mode&022)||((following||directory)&&!S_ISDIR(st.st_mode))){rawclose(next);errno=EPERM;return -1;}
  fd=next;part=following;
 }
 return fd;
}
static int exact_read_fd(int fd,void *out,size_t bytes) {
 size_t done=0;while(done<bytes){ssize_t n=(ssize_t)syscall(SYS_pread64,fd,(char *)out+done,bytes-done,(off_t)done);if(n<=0){errno=n<0?errno:EIO;return -1;}done+=(size_t)n;}
 unsigned char extra;ssize_t n=(ssize_t)syscall(SYS_pread64,fd,&extra,1,(off_t)bytes);
 if(n!=0){errno=EFBIG;return -1;}return 0;
}
static int fixed_file(const char *name,void *out,size_t bytes) {
 if(rootfd<0||strchr(name,'/')||!strcmp(name,".")||!strcmp(name,"..")){errno=EINVAL;return -1;}
 int fd=(int)syscall(SYS_openat,rootfd,name,O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK,0);if(fd<0)return -1;
 struct stat st;int rc=raw_stat(fd,&st);
 if(!rc && (!S_ISREG(st.st_mode)||st.st_uid!=trusted_uid()||st.st_nlink!=1||(st.st_mode&0777)!=0600||st.st_size!=(off_t)bytes)){errno=EPERM;rc=-1;}
 if(!rc)rc=exact_read_fd(fd,out,bytes);
 int saved=errno;rawclose(fd);errno=saved;return rc;
}
static int digest_fd(int fd,uint64_t bytes,unsigned char out[32]) {
 struct stat before,after;
 if(bytes>UINT64_C(16777216)||raw_stat(fd,&before)||!S_ISREG(before.st_mode)||before.st_size<0||(uint64_t)before.st_size!=bytes){errno=EFBIG;return -1;}
 unsigned char *data=malloc(bytes?(size_t)bytes:1);if(!data)return -1;
 int rc=exact_read_fd(fd,data,(size_t)bytes);
 if(!rc && !SHA256(data,(size_t)bytes,out)){errno=ENOTSUP;rc=-1;}
 if(!rc && (raw_stat(fd,&after)||before.st_dev!=after.st_dev||before.st_ino!=after.st_ino||before.st_size!=after.st_size||before.st_mtim.tv_sec!=after.st_mtim.tv_sec||before.st_mtim.tv_nsec!=after.st_mtim.tv_nsec||before.st_ctim.tv_sec!=after.st_ctim.tv_sec||before.st_ctim.tv_nsec!=after.st_ctim.tv_nsec)){errno=ESTALE;rc=-1;}
 free(data);return rc;
}
static int hash_path(const char *path,uint64_t bytes,const unsigned char expected[32],struct stat *identity) {
 int fd=secure_absolute(path,O_RDONLY,0);if(fd<0)return -1;
 struct stat st;unsigned char hash[32];int rc=raw_stat(fd,&st);
 if(!rc && (!S_ISREG(st.st_mode)||st.st_nlink!=1)){errno=EPERM;rc=-1;}
 if(!rc)rc=digest_fd(fd,bytes,hash);
 if(!rc && memcmp(hash,expected,32)){errno=EKEYREJECTED;rc=-1;}
 if(!rc && identity)*identity=st;
 int saved=errno;rawclose(fd);errno=saved;return rc;
}
static int kernel_text(const char *path,char *out,size_t capacity) {
 int fd=(int)syscall(SYS_openat,AT_FDCWD,path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW,0);if(fd<0)return -1;
 size_t done=0;int rc=0;
 while(done<capacity-1){ssize_t n=(ssize_t)syscall(SYS_read,fd,out+done,capacity-1-done);if(n<0){rc=-1;break;}if(!n)break;done+=(size_t)n;}
 int saved=errno;rawclose(fd);
 if(rc){errno=saved;return -1;}if(done==capacity-1){errno=EFBIG;return -1;}out[done]=0;return 0;
}
static int runtime_text(const char *production,const char *synthetic,char *out,size_t size) {
#ifdef PMBP_SYNTHETIC_LAYER
 (void)production;
 char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/%s",checked_root,synthetic)>=(int)sizeof(path))return -1;return kernel_text(path,out,size);
#else
 (void)synthetic;return kernel_text(production,out,size);
#endif
}
static uint64_t starttime(pid_t pid) {
 char path[64],text[4096];if(snprintf(path,sizeof(path),"/proc/%ld/stat",(long)pid)>=(int)sizeof(path)||kernel_text(path,text,sizeof(text)))return 0;
 char *p=strrchr(text,')');if(!p)return 0;p+=2;
 for(unsigned field=3;field<22;field++){p=strchr(p,' ');if(!p)return 0;p++;}
 errno=0;char *end=NULL;unsigned long long n=strtoull(p,&end,10);return errno||end==p||(*end!=' '&&*end!='\n')?0:(uint64_t)n;
}
static int selected(void) {
 if((uint64_t)getpid()!=marker.pid||starttime(getpid())!=marker.starttime||marker.lease_epoch!=manifest.lease_epoch)return 0;
 char exe[PATH_MAX],comm[128];ssize_t n=(ssize_t)syscall(SYS_readlinkat,AT_FDCWD,"/proc/self/exe",exe,sizeof(exe)-1);
 if(n<0||(size_t)n>=sizeof(exe)-1)return 0;exe[n]=0;
 if(kernel_text("/proc/self/comm",comm,sizeof(comm)))return 0;
 return !strcmp(exe,PMBP_RECEIVER_PATH)&&!strcmp(comm,PMBP_RECEIVER_COMM);
}
/* Kernel owns /proc/self/maps; never dereference a guessed private pointer. */
static int map_span(uintptr_t address,size_t bytes,dev_t dev,ino_t ino,int stack) {
 if(!address||!bytes||bytes>UINTPTR_MAX-address)return 0;
 char text[131072];if(kernel_text("/proc/self/maps",text,sizeof(text)))return 0;
 char *save=NULL,*line=strtok_r(text,"\n",&save);int good=0;
 while(line){unsigned long long a,b,off,inode;unsigned major_n,minor_n;char perm[5];int used=0;
  if(sscanf(line,"%llx-%llx %4s %llx %x:%x %llu %n",&a,&b,perm,&off,&major_n,&minor_n,&inode,&used)==7 && address>=a && address+bytes<=b){
   if(stack)good=perm[0]=='r'&&perm[1]=='w'&&perm[2]=='-'&&perm[3]=='p'&&inode==0&&off==0&&(line[used]==0||line[used]=='[');
   else good=perm[0]=='r'&&perm[1]=='-'&&perm[2]=='x'&&perm[3]=='p'&&inode==(uint64_t)ino&&makedev(major_n,minor_n)==dev;
   break;
  }line=strtok_r(NULL,"\n",&save);
 }
 return good;
}
int pmbp_regular_span(uintptr_t p,size_t n){return map_span(p,n,0,0,1);}
static int read_memory(uintptr_t p,void *out,size_t n) {
 int fd=(int)syscall(SYS_openat,AT_FDCWD,"/proc/self/mem",O_RDONLY|O_CLOEXEC|O_NOFOLLOW,0);if(fd<0)return -1;
 ssize_t got=pmbp_native_io()->pread(fd,out,n,(off_t)p);int saved=errno;rawclose(fd);errno=saved;return got==(ssize_t)n?0:-1;
}
static int trace_window(const struct pmbp_window_pin *w,const char *stage){
#ifdef PMBP_SYNTHETIC_LAYER
 char text[256];int n=snprintf(text,sizeof(text),"SYNTHETIC_PIN_REJECT symbol=%s stage=%s errno=%d\n",w->symbol,stage,errno);if(n>0&&(size_t)n<sizeof(text))(void)syscall(SYS_write,2,text,(size_t)n);
#else
 (void)w;(void)stage;
#endif
 return 0;
}
static int window(const struct pmbp_window_pin *w,uintptr_t caller,void *callee) {
 if(w->file>=sizeof(pmbp_files)/sizeof(pmbp_files[0]))return 0;
 const struct pmbp_file_pin *f=&pmbp_files[w->file];struct stat st;
 if(hash_path(f->path,f->bytes,f->sha,&st))return trace_window(w,"file");
 void *symbol=callee?callee:pmbp_next(w->symbol);
#ifdef PMBP_SYNTHETIC_LAYER
 if(!symbol)symbol=dlsym(RTLD_DEFAULT,w->symbol);
#endif
 Dl_info info={0};
 if(!symbol||!dladdr(symbol,&info)||!info.dli_fbase||!info.dli_fname||(uintptr_t)symbol<w->symbol_va)return trace_window(w,"symbol");
 /* ET_EXEC symbol values are absolute; dladdr's mapping base is not a load bias. */
 uintptr_t base=(uintptr_t)symbol-w->symbol_va,address=base+w->va;
 if(w->bytes>4096 || !map_span(address,(size_t)w->bytes,st.st_dev,st.st_ino,0))return trace_window(w,"mapping");
 if(caller && base+w->caller_va!=caller)return 0;
 unsigned char raw[4096];if(read_memory(address,raw,(size_t)w->bytes)||memcmp(raw,w->code,(size_t)w->bytes))return trace_window(w,"code");return 1;
}
int pmbp_broker_native(const char *name,void *fn) {
 for(size_t i=0;i<sizeof(pmbp_native_pins)/sizeof(pmbp_native_pins[0]);i++)if(!strcmp(name,pmbp_native_pins[i].symbol))return window(&pmbp_native_pins[i],0,fn);
 return 0;
}
static int caller_role(unsigned role,uintptr_t pc) {
 for(size_t i=0;i<sizeof(pmbp_windows)/sizeof(pmbp_windows[0]);i++)if(pmbp_windows[i].operation==role && window(&pmbp_windows[i],pc,NULL))return 1;
 return 0;
}
int pmbp_broker_caller(enum pmbp_operation op,uintptr_t pc){return caller_role((unsigned)op,pc);}
static int module_current(void) {
 char text[8192],expected[256];
 if(runtime_text("/sys/module/sony_persistent_flash/initstate","sys-state",text,sizeof(text))||strcmp(text,"live\n"))return 0;
 if(runtime_text("/sys/module/sony_persistent_flash/parameters/name","sys-name",text,sizeof(text))||strcmp(text,"nflasha\n"))return 0;
 if(runtime_text("/sys/module/sony_persistent_flash/parameters/mmio_base","sys-mmio",text,sizeof(text))||strcmp(text,"184549376\n"))return 0;
 if(runtime_text("/sys/module/sony_persistent_flash/parameters/functional_alfred_trim_zero","sys-trim",text,sizeof(text))||strcmp(text,"Y\n"))return 0;
 if(runtime_text("/proc/sys/kernel/osrelease","kernel-release",text,sizeof(text)))return 0;
 size_t n=strcspn(manifest.vermagic," ");if(n+2>sizeof(expected))return 0;memcpy(expected,manifest.vermagic,n);expected[n]='\n';expected[n+1]=0;if(strcmp(text,expected))return 0;
 if(runtime_text("/proc/modules","proc-modules",text,sizeof(text)))return 0;
 char *save=NULL,*line=strtok_r(text,"\n",&save);unsigned found=0;
 while(line){char name[96],deps[512],live[32];unsigned long long size;unsigned refs;
  if(sscanf(line,"%95s %llu %u %511s %31s",name,&size,&refs,deps,live)==5 && !strcmp(name,"sony_persistent_flash")){if(strcmp(live,"Live")||size==0)return 0;found++;}
  line=strtok_r(NULL,"\n",&save);
 }
 return found==1;
}
static int resource(struct pmbp_resource *r) {
 char text[2048];unsigned major_n,minor_n;int consumed=0;
 if(runtime_text("/sys/class/block/cnflasha23/dev","sys-dev",text,sizeof(text))||sscanf(text,"%u:%u\n%n",&major_n,&minor_n,&consumed)!=2||text[consumed]||!major_n||minor_n!=151)return 0;
 if(runtime_text("/sys/class/block/cnflasha23/uevent","sys-uevent",text,sizeof(text)))return 0;
 char expected[128];snprintf(expected,sizeof(expected),"MAJOR=%u\nMINOR=%u\nDEVNAME=cnflasha23\nDEVTYPE=disk\n",major_n,minor_n);
 if(strcmp(text,expected))return 0;
 /* Independent gendisk START=0 is deliberately never used as container offset. */
 if(!module_current()||hash_path(PMBP_MODULE_PATH,manifest.module_bytes,manifest.module_sha,NULL))return 0;
 int fd=pmbp_native_io()->open(PMBP_TARGET,O_RDONLY|O_CLOEXEC|O_NOFOLLOW,0);if(fd<0)return 0;
 struct stat st;uint64_t bytes=0;int ro=-1;
 int ok=!pmbp_native_io()->stat(0,fd,&st)&&S_ISBLK(st.st_mode)&&major(st.st_rdev)==major_n&&minor(st.st_rdev)==minor_n&&
  !pmbp_native_io()->ioctl(fd,BLKGETSIZE64,&bytes)&&!pmbp_native_io()->ioctl(fd,BLKROGET,&ro)&&bytes==PMBP_BYTES&&ro==0;
 int saved=errno;pmbp_native_io()->close(fd);errno=saved;if(!ok)return 0;
 *r=(struct pmbp_resource){.generation=manifest.generation,.lease_epoch=manifest.lease_epoch,.disk_dev=manifest.disk_dev,.disk_ino=manifest.disk_ino,
  .block_dev=(uint64_t)st.st_dev,.block_ino=(uint64_t)st.st_ino,.block_rdev=(uint64_t)st.st_rdev,.offset=PMBP_OFFSET,.bytes=bytes,.sys_major=major_n,.sys_minor=minor_n};
 memcpy(r->geometry_sha256,manifest.geometry_sha,32);memcpy(r->module_sha256,manifest.module_sha,32);memcpy(r->source_sha256,manifest.source_sha,32);
 state.runtime_blockquery=1;return 1;
}
static int load_base(const char *root,const char *name) {
 if(!root||!name||strcmp(name,"manifest.bin")||strlen(root)>=sizeof(checked_root))return failure(EINVAL);
 strcpy(checked_root,root);rootfd=secure_absolute(root,O_RDONLY|O_DIRECTORY,1);if(rootfd<0)return failure(errno);
 struct stat st;if(raw_stat(rootfd,&st)||st.st_uid!=trusted_uid()||(st.st_mode&0777)!=0700)return failure(EPERM);
 if(fixed_file(name,&manifest,sizeof(manifest)))return failure(errno);
 unsigned char hash[32];if(!SHA256((const unsigned char *)&manifest,sizeof(manifest),hash)||memcmp(hash,pmbp_manifest_sha,32))return failure(EKEYREJECTED);
 if(memcmp(manifest.magic,"PMBPBR01",8)||manifest.schema!=1||manifest.profile!=1||manifest.disk_bytes!=PMBP_DISK_BYTES||manifest.offset!=PMBP_OFFSET||manifest.bytes!=PMBP_BYTES||manifest.selector!=23||!manifest.generation||!manifest.lease_epoch||!manifest.disk_dev||!manifest.disk_ino||!manifest.parent_pid||!manifest.parent_starttime||manifest.vermagic[127])return failure(EINVAL);
 if(memcmp(manifest.source_sha,pmbp_source_sha,32)||memcmp(manifest.module_sha,pmbp_module_sha,32)||memcmp(manifest.hostcore_sha,pmbp_hostcore_sha,32)||memcmp(manifest.driver_sha,pmbp_driver_sha,32)||memcmp(manifest.bootstrap_sha,pmbp_bootstrap_sha,32))return failure(EKEYREJECTED);
 state.host_provisioned=1;state.source_derived=1;return 0;
}
int pmbp_broker_checked(const char *root,const char *name) {
 if(initialised)return state.enabled?0:-1;initialised=1;
 if(load_base(root,name))return -1;
 char profile[sizeof(PMBP_PROFILE)];if(fixed_file("profile",profile,sizeof(profile)))return failure(errno);
 if(memcmp(profile,PMBP_PROFILE "\n",sizeof(profile)))return failure(EINVAL);
 struct pmbp_runtime_marker receipt;if(fixed_file("module-load.bin",&receipt,sizeof(receipt))||memcmp(receipt.magic,"PMBPRT01",8)||memcmp(receipt.manifest_sha,pmbp_manifest_sha,32)||memcmp(receipt.source_sha,pmbp_source_sha,32)||memcmp(receipt.module_sha,pmbp_module_sha,32)||receipt.insmod_rc||receipt.reserved||receipt.pid||receipt.starttime||receipt.lease_epoch!=manifest.lease_epoch)return failure(ESTALE);
 if(fixed_file("runtime.bin",&marker,sizeof(marker)))return failure(errno);
 if(memcmp(marker.magic,"PMBPRT01",8)||memcmp(marker.manifest_sha,pmbp_manifest_sha,32)||memcmp(marker.source_sha,pmbp_source_sha,32)||memcmp(marker.module_sha,pmbp_module_sha,32)||marker.insmod_rc||marker.reserved||!selected())return failure(ESTALE);
 char source_path[PATH_MAX],code_path[PATH_MAX];
 if(snprintf(source_path,sizeof(source_path),"%s/source.bundle",root)>=(int)sizeof(source_path)||snprintf(code_path,sizeof(code_path),"%s/broker.so",root)>=(int)sizeof(code_path))return failure(ENAMETOOLONG);
 if(hash_path(source_path,PMBP_SOURCE_BYTES,pmbp_source_sha,NULL))return failure(errno);
 struct stat code_st;if((int)syscall(SYS_newfstatat,rootfd,"broker.so",&code_st,AT_SYMLINK_NOFOLLOW)||code_st.st_uid!=trusted_uid()||(code_st.st_mode&0777)!=0600||code_st.st_size<=0||hash_path(code_path,(uint64_t)code_st.st_size,marker.code_sha,&code_st))return failure(errno);
 Dl_info self={0};if(!dladdr((void *)pmbp_broker_checked,&self)||strcmp(self.dli_fname,code_path)||!map_span((uintptr_t)pmbp_broker_checked,1,code_st.st_dev,code_st.st_ino,0))return failure(EKEYREJECTED);
 if(!pmbp_libc_identity())return failure(EKEYREJECTED);
 for(size_t i=0;i<sizeof(pmbp_required)/sizeof(pmbp_required[0]);i++)if(!window(&pmbp_required[i],0,NULL))return failure(EKEYREJECTED);
 if(!resource(&contract.resource))return failure(ENOTSUP);
 contract.profile=PMBP_PROFILE;contract.schema=1;contract.marker_verified=1;contract.pid=getpid();
 state.enabled=1;state.starttime=marker.starttime;state.epoch=manifest.lease_epoch;return 0;
}
const struct pmbp_contract *pmbp_runtime_contract(void) {
 if(checking)return NULL;
 int incoming=errno;checking=1;
 if(!initialised){const char *root=getenv("PMBP_CHECKED_ROOT");if(root && *root)(void)pmbp_broker_checked(root,"manifest.bin");else initialised=1;}
 checking=0;errno=incoming;
 if(rootfd<0 && !state.admission_errno)return NULL;
 if(!state.enabled)return &contract; /* declared bad manifest reaches the checked error path */
 if(!selected()){state.enabled=0;state.admission_errno=ESTALE;contract.schema=0;return &contract;}
 pid_t tid=(pid_t)syscall(SYS_gettid);contract.tid=tid;return &contract;
}
int pmbp_attest(enum pmbp_operation op,uintptr_t pc,struct pmbp_resource *out) {
 if(!state.enabled||!selected())return failure(ESTALE);
 if(!pmbp_broker_caller(op,pc))return failure(EPERM);
 if(op==PMBP_WRITE || op==PMBP_PWRITE || op==PMBP_PWRITEV || op==PMBP_FSYNC){if(!device_locked||device_scope!=4||!held_mutex)return failure(ENOTSUP);}
 if(op==PMBP_OPEN){
  uint64_t tid=(uint64_t)syscall(SYS_gettid),expected=0;
  if(!atomic_compare_exchange_strong(&tid_claim,&expected,tid) && expected!=tid)return failure(EPERM);
  if(!expected){
   struct {uint64_t pid,start,epoch,tid;} claim={marker.pid,marker.starttime,marker.lease_epoch,tid};
   int fd=(int)syscall(SYS_openat,rootfd,"claim",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
   if(fd<0)return failure(errno);
   ssize_t n=(ssize_t)syscall(SYS_write,fd,&claim,sizeof(claim));int rc=(int)syscall(SYS_fsync,fd);rawclose(fd);
   if(n!=(ssize_t)sizeof(claim)||rc)return failure(EIO);
  }
  state.claimed_tid=tid;
 } else if(atomic_load(&tid_claim)!=(uint64_t)syscall(SYS_gettid))return failure(EPERM);
 struct pmbp_runtime_marker current;if(fixed_file("runtime.bin",&current,sizeof(current))||memcmp(&current,&marker,sizeof(marker)))return failure(ESTALE);
 struct pmbp_manifest current_manifest;if(fixed_file("manifest.bin",&current_manifest,sizeof(current_manifest))||memcmp(&current_manifest,&manifest,sizeof(manifest)))return failure(ESTALE);
 if(!resource(out))return failure(ENOTSUP);
 return 0;
}
struct pmbp_broker_state pmbp_broker_status(void){return state;}
unsigned pmbp_retry_ordinal(void){return atomic_load(&retries);}
int pmbp_format_scope(int entering,uintptr_t caller) {
 const struct pmbp_contract *c=pmbp_runtime_contract();
 if(!c||!state.enabled||!caller_role(100,caller))return 0;
 if(entering){if(format_depth)return 0;format_depth=1;atomic_fetch_add(&retries,1);}
 else {format_depth=0;device_scope=0;device_locked=0;held_mutex=NULL;}
 return 1;
}
int pmbp_mutex_scope(int entering,int device) {
 if(!format_depth||device!=4)return 0;
 if(entering==1){if(device_scope)return 0;device_scope=4;device_locked=0;}
 else if(entering==0){device_scope=0;device_locked=0;held_mutex=NULL;}
 return 1;
}
void pmbp_mutex_result(uintptr_t caller,void *mutex,int rc,int unlocking) {
#ifndef PMBP_SYNTHETIC_LAYER
 if(!pmbp_broker_native(unlocking?"pthread_mutex_unlock":"pthread_mutex_lock",pmbp_next(unlocking?"pthread_mutex_unlock":"pthread_mutex_lock")))return;
#endif
 if(unlocking){if(mutex==held_mutex){device_locked=0;held_mutex=NULL;}return;}
 if(state.enabled&&rc==0&&caller_role(101,caller)){
#ifndef PMBP_SYNTHETIC_LAYER
  /* Original direct BLs bypass fsysDep_LockDevice; its actual native LR and
   * source-defined g_fsys device4 mutex address are the witness. */
  void *base=pmbp_next("g_fsys");
  if(!base || (uintptr_t)mutex!=(uintptr_t)base+0x23a38u+4u*0x30u)return;
#else
  if(device_scope!=4)return;
#endif
  device_scope=4;device_locked=1;held_mutex=mutex;
 }
}
int pmbp_copy_info(uintptr_t caller,uintptr_t frame,uintptr_t buffer,uint32_t rc,uint32_t *word) {
 if(!state.enabled||!selected()||rc||!caller_role(102,caller)||frame>UINTPTR_MAX-240||buffer!=frame+56||!pmbp_regular_span(frame,240))return 0;
 unsigned char info[184];if(read_memory(buffer,info,sizeof(info)))return 0;
 memcpy(word,info+4,4);return 1;
}
static void pmbp_rawlog(const char *line) {
 int saved=errno;const char *profile=getenv("A7C2_P1_PMBP_PROFILE");
 if(state.enabled && selected() && profile && !strcmp(profile,PMBP_PROFILE)) {
  char raw[768];int n=snprintf(raw,sizeof(raw),"PMBP_RAW pid=%ld %s",(long)getpid(),line);
  if(n>0&&(size_t)n<sizeof(raw)) {
   int fd=(int)syscall(SYS_openat,AT_FDCWD,"/simulation/pmbp-runtime/receiver.log",O_WRONLY|O_APPEND|O_CREAT|O_NOFOLLOW|O_CLOEXEC,0600);
   if(fd>=0){(void)syscall(SYS_write,fd,raw,(size_t)n);rawclose(fd);}
  }
 }
 errno=saved;
}
void pmbp_checkpoint(const char *name,uintptr_t pc,uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d,uintptr_t e,uintptr_t f,long rc,int error,unsigned valid,uint32_t word) {
 int saved=errno;
 if(!state.enabled||!selected()||atomic_fetch_add(&checkpoints,1)>=256){errno=saved;return;}
 char line[640];int n=snprintf(line,sizeof(line),"PMBP_CHECKPOINT class=original-passive pid=%ld tid=%ld epoch=%llu retry=%u op=%s caller=%llx x0=%llx x1=%llx x2=%llx x3=%llx x4=%llx x5=%llx rc=%ld errno=%d info_valid=%u word4=%x bit1=%u\n",(long)getpid(),(long)syscall(SYS_gettid),(unsigned long long)manifest.lease_epoch,pmbp_retry_ordinal(),name,(unsigned long long)pc,(unsigned long long)a,(unsigned long long)b,(unsigned long long)c,(unsigned long long)d,(unsigned long long)e,(unsigned long long)f,rc,error,valid,word,valid?((word>>1)&1u):0u);
 if(n>0&&(size_t)n<sizeof(line)){(void)pmbp_native_io()->write(2,line,(size_t)n);pmbp_rawlog(line);}errno=saved;
}
void pmbp_event_sink(const struct pmbp_event *event) {
 int saved=errno;char line[384];
 int n=snprintf(line,sizeof(line),"PMBP_IO class=%s op=%u gen=%llu ordinal=%u offset=%llu requested=%llu observed=%llu rc=%ld errno=%d poison=%u\n",event->functional?"explicit-functional":"original-passive",(unsigned)event->operation,(unsigned long long)event->generation,event->ordinal,(unsigned long long)event->offset,(unsigned long long)event->requested,(unsigned long long)event->observed,event->native_rc,event->native_errno,(unsigned)event->poison);
 if(n>0&&(size_t)n<sizeof(line)){(void)pmbp_native_io()->write(2,line,(size_t)n);pmbp_rawlog(line);}errno=saved;
}
static int create_file(const char *name,const void *data,size_t bytes) {
 int fd=(int)syscall(SYS_openat,rootfd,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);if(fd<0)return -1;
 ssize_t n=(ssize_t)syscall(SYS_write,fd,data,bytes);int rc=(int)syscall(SYS_fsync,fd);rawclose(fd);return n==(ssize_t)bytes&&!rc?0:-1;
}
int pmbp_bootstrap(int argc,char **argv) {
 if(argc<4||load_base(argv[1],argv[2]))return 125;
 if(!strcmp(argv[3],"module-load")){
  if(argc!=4||hash_path(PMBP_MODULE_PATH,manifest.module_bytes,manifest.module_sha,NULL))return 125;
  pid_t child=fork();if(child<0)return 125;
  if(!child){execl("/bin/busybox","busybox","insmod",PMBP_MODULE_PATH,"functional_alfred_trim_zero=1",(char *)NULL);_exit(127);}
  int status;if(waitpid(child,&status,0)!=child||!WIFEXITED(status))return 125;
  int module_rc=WEXITSTATUS(status);
  if(module_rc)return module_rc;
  if(!module_current())return 125;
  struct pmbp_runtime_marker r={0};memcpy(r.magic,"PMBPRT01",8);memcpy(r.manifest_sha,pmbp_manifest_sha,32);memcpy(r.module_sha,manifest.module_sha,32);memcpy(r.source_sha,pmbp_source_sha,32);r.lease_epoch=manifest.lease_epoch;
  return create_file("module-load.bin",&r,sizeof(r))?125:0;
 }
 if(strcmp(argv[3],"receiver")||argc<5||strcmp(argv[4],PMBP_RECEIVER_PATH))return 125;
 struct pmbp_runtime_marker r;if(fixed_file("module-load.bin",&r,sizeof(r))||memcmp(r.magic,"PMBPRT01",8)||memcmp(r.manifest_sha,pmbp_manifest_sha,32)||memcmp(r.source_sha,pmbp_source_sha,32)||memcmp(r.module_sha,manifest.module_sha,32)||r.insmod_rc||r.pid||r.starttime||r.reserved||r.lease_epoch!=manifest.lease_epoch||!module_current())return 125;
 char path[PATH_MAX];if(snprintf(path,sizeof(path),"%s/broker.so",argv[1])>=(int)sizeof(path))return 125;
 int fd=secure_absolute(path,O_RDONLY,0);struct stat st;if(fd<0||raw_stat(fd,&st)||st.st_size<=0||digest_fd(fd,(uint64_t)st.st_size,r.code_sha)){if(fd>=0)rawclose(fd);return 125;}rawclose(fd);
 r.pid=(uint64_t)getpid();r.starttime=starttime(getpid());if(!r.starttime||create_file("runtime.bin",&r,sizeof(r))||setenv("PMBP_CHECKED_ROOT",argv[1],1))return 125;
 execv(PMBP_RECEIVER_PATH,argv+4);return 125;
}
