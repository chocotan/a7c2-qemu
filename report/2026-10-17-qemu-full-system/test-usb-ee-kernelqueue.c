/* Host fixtures only: real C calls/threads, no Sony AP or kernel execution. */
#define USB_OBSERVE_HOST_TEST 1
#define USB_EE_NORMAL_COLD 1
#define readlink host_readlink
#define fopen host_fopen
#define pread host_pread
#include "usb-start-observe.c"
#undef readlink
#undef fopen
#undef pread
#include <assert.h>
#include <pthread.h>
#include <sys/wait.h>
/* The runner extracts the production wait body and supplies its guarded caller. */
#include "fixture-target-wait.inc"
static unsigned registrations;
static uint64_t target_registration_event;
static unsigned mode,stage,delivered,completed,allocs,sends,rcvs,sources,sizes,frees,waits;
static uintptr_t mapped,message,prime_message;static uint32_t msg_source=EE_NWC_SOURCE;
static pthread_mutex_t native_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t native_cond=PTHREAD_COND_INITIALIZER;
static unsigned char uconf_fixture[56];
static pid_t receiver_tid,free_tid;static unsigned init_reads;
static struct ee_cold_ticket captured;
ssize_t host_readlink(const char *path,char *out,size_t n){assert(!strcmp(path,"/proc/self/fd/7"));const char *value=mode==4?"/dev/other":"/dev/uipc";size_t k=strlen(value);assert(k<n);memcpy(out,value,k);errno=EINTR;return (ssize_t)k;}
FILE *host_fopen(const char *path,const char *how){assert(!strcmp(path,"/proc/self/maps")&&!strcmp(how,"r"));char line[256];int n=snprintf(line,sizeof line,"%lx-%lx %s 00000000 00:01 42 /dev/uipc\n",mapped,mapped+0x200000,mode==5?"rw-p":"rw-s");FILE *f=tmpfile();assert(f);assert(fwrite(line,1,(size_t)n,f)==(size_t)n);rewind(f);return f;}
ssize_t host_pread(int fd,void *out,size_t n,off_t off){
 if((uintptr_t)off==message||(uintptr_t)off==prime_message){errno=EFAULT;return -1;}
 ssize_t rc=(ssize_t)syscall(SYS_pread64,fd,out,n,off);
 if((uintptr_t)off==(uintptr_t)uconf_fixture&&rc==56){
  ++init_reads;unsigned char *raw=out;
  if(mode==28){raw[40]^=(unsigned char)init_reads;raw[52]^=(unsigned char)init_reads;}
  if(mode==29){raw[4]^=(unsigned char)init_reads;raw[20]^=(unsigned char)init_reads;}
  if(mode==30&&!(init_reads&1))raw[48]^=1;
 }
 return rc;
}
static int32_t native_queue(uint32_t q,uintptr_t output,uintptr_t callback,uintptr_t context){
 assert(mode==27&&q==EE_QUEUE&&output&&callback==0x3344&&context==0x5566&&errno==37);
 ++registrations;*(uintptr_t *)output=0x112233;errno=73;return 0;
}
static int32_t native_recv(uint32_t q,uintptr_t output,int32_t timeout){assert(q==EE_QUEUE&&timeout==-1&&errno==37);++rcvs;
 pthread_mutex_lock(&native_lock);while(stage<=delivered)pthread_cond_wait(&native_cond,&native_lock);
 ++delivered;*(uintptr_t *)output=delivered==1?prime_message:message;pthread_mutex_unlock(&native_lock);errno=71;return 0;}
static uint32_t native_source(uintptr_t p){assert((p==prime_message||p==message)&&errno==37);++sources;errno=71;
 return p==prime_message?(mode==2?0:0x90040193u):(mode==22?0x90040193u:msg_source);}
static int32_t native_size(uintptr_t p){assert((p==prime_message||p==message)&&errno==37);++sizes;errno=71;return p==prime_message&&mode==3?0:(p==message&&mode==10?11:12);}
static void *reuse_before_free_return(void *unused){(void)unused;ee_cold_recv_return(message,0);return NULL;}
static int32_t native_free(uint32_t q,uintptr_t p){assert(q==EE_QUEUE&&(p==prime_message||p==message)&&errno==37);++frees;
 if(p==message){
  if(mode==16){pthread_t t;assert(!pthread_create(&t,0,reuse_before_free_return,0));assert(!pthread_join(t,0));}
  memset((void *)p,0xdd,12); /* Native has reclaimed its payload; observers must use the entry ticket. */
 }
 errno=71;return mode==11?-28:0;
}
static void *freer(void *ptr){free_tid=(pid_t)syscall(SYS_gettid);errno=37;
 assert(ee_free(EE_QUEUE,(uintptr_t)ptr)==(mode==11?-28:0));assert(errno==71);return NULL;}
static void *receiver(void *unused){(void)unused;receiver_tid=(pid_t)syscall(SYS_gettid);
 for(unsigned round=0;round<2;round++){
  uintptr_t p=0;errno=37;assert(!ee_recv(EE_QUEUE,(uintptr_t)&p,-1));assert(errno==71);
  errno=37;(void)ee_source(p);assert(errno==71);errno=37;(void)ee_size(p);assert(errno==71);
  if(round==1&&ee_cold_service){
   struct ee_nwc_snapshot s;assert(!ee_nwc_snapshot(ee_cold_service,&s));unsigned char b[12];
   struct ee_nwc_lease l=s.lease;
   if(mode==9){l.message++;assert(ee_nwc_copy_owned(ee_cold_service,&l,12,b)!=0);}
   if(mode==17){l.pid++;assert(ee_nwc_copy_owned(ee_cold_service,&l,12,b)!=0);}
   if(mode==18){l.message_generation++;assert(ee_nwc_copy_owned(ee_cold_service,&l,12,b)!=0);}
   if(mode==20){struct ee_nwc_receive o=s.receive_observed;o.consumer++;assert(ee_nwc_observe_receive(ee_cold_service,&o)!=0);}
   if(mode==15)ee_cold_recv_return(p,0);
  }
  pthread_t f;assert(!pthread_create(&f,0,freer,(void *)p));assert(!pthread_join(f,0));
  pthread_mutex_lock(&native_lock);completed=round+1;pthread_cond_broadcast(&native_cond);pthread_mutex_unlock(&native_lock);
 }
 return NULL;
}
static int allocate_native(unsigned dest,void **out,unsigned n,unsigned flags){assert(dest==EE_QUEUE&&n==12&&flags==1);++allocs;*out=(void *)message;errno=71;return mode==13?-19:0;}
static int release_native(unsigned q,void *p){(void)q;(void)p;assert(0);return -1;}
static void set_source_native(void *p,unsigned source){assert((uintptr_t)p==message);msg_source=source;}
static unsigned size_io(void *p){assert((uintptr_t)p==message);return mode==12?11:12;}
static unsigned source_io(void *p){assert((uintptr_t)p==message);return msg_source;}
static int send_native(unsigned q,void *p){assert(q==EE_QUEUE&&(uintptr_t)p==message);assert(!memcmp(p,(unsigned char[12]){6,0,0xa3,0x20},12));++sends;
 pthread_mutex_lock(&native_lock);stage=2;pthread_cond_broadcast(&native_cond);pthread_mutex_unlock(&native_lock);errno=71;return mode==14?-19:0;}
static uintptr_t native_wait(uintptr_t promise){assert(promise==0x33445566);++waits;
 if(mode==27){assert(errno==37);errno=ENOMSG;return (uintptr_t)(intptr_t)-19;}
 if(sends){pthread_mutex_lock(&native_lock);while(completed<2)pthread_cond_wait(&native_cond,&native_lock);pthread_mutex_unlock(&native_lock);}errno=71;return promise;}
static uintptr_t native_reader(uintptr_t in,uintptr_t output){assert(in==0x1122);
 ee_remember_register(0x11,0x22,app_base+0x35492bc,(struct ee_pair){0x1234,1});
 if(mode==27){
  assert(ee_wait_enter(app_base+0x35492cc,0x33445566));
  struct ee_nwc_snapshot s;assert(ee_cold_service&&!ee_nwc_snapshot(ee_cold_service,&s));
  assert(s.configured&&!s.armed&&!s.attempted&&s.last_rejected==EE_NWC_NOT_ARMED&&!allocs&&!sends);
  assert(target_registration_event&&ee_cold_registration_event==target_registration_event);
  errno=37;assert(fixture_target_wait(0x33445566)==(uintptr_t)(intptr_t)-19&&errno==ENOMSG);
 }else {assert(fixture_target_wait(0x33445566)==0x33445566);
  if(mode==21)assert(ee_nwc_observe_wait(ee_cold_service,getpid(),7,0x33445566,(uintptr_t)syscall(SYS_gettid)+1)!=0);}
 *(uint32_t *)output=1;errno=71;return 0x8877;
}
static void put(void *base,unsigned off,const void *value,size_t n){memcpy((unsigned char *)base+off,value,n);}
int main(int argc,char **argv){assert(argc==3);mode=(unsigned)strtoul(argv[2],0,10);
 logfd=open(argv[1],O_RDWR|O_CREAT|O_EXCL,0600);memfd=open("/proc/self/mem",O_RDONLY);assert(logfd>=0&&memfd>=0);
 void *area=mmap(NULL,0x200000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(area!=MAP_FAILED);mapped=(uintptr_t)area;message=mapped+64;prime_message=mapped+128;
 int fd=7;uint32_t total=0x200000,pool0=0x80000,pool1=0x20000,dynamic_id=0x1234;uintptr_t allocator=mapped+1024;
 put(uconf_fixture,0,&fd,4);put(uconf_fixture,8,&mapped,8);put(uconf_fixture,16,&total,4);put(uconf_fixture,24,&allocator,8);put(uconf_fixture,32,&pool0,4);put(uconf_fixture,36,&pool1,4);put(uconf_fixture,48,&dynamic_id,4);
 ee_uipc_base=(uintptr_t)uconf_fixture-0x1b560;ee_cold_abi_verified=mode!=6;app_base=0x100000;ee_installed=1;
 ee_real_queue=native_queue;ee_real_recv=native_recv;ee_real_source=native_source;ee_real_size=native_size;ee_real_free=native_free;ee_real_wait=native_wait;
 ee_cold_real_reader=native_reader;ee_cold_native_allocate=allocate_native;ee_cold_native_send=send_native;
 ee_cold_native_size=size_io;ee_cold_native_source=source_io;
 ee_cold_io=(struct full_imaging_io){ee_cold_allocate,release_native,set_source_native,ee_cold_send,ee_cold_checked_size,ee_cold_checked_source,NULL};
 assert(ee_cold_pid_ok());
 /* HostFixture launch records bind the executed wrappers to this synthetic app base. */
 dprintf(logfd,"USB_START INITIALIZED tid=%ld pid=%ld passive=0 functional_model=1 mode=%s\n",syscall(SYS_gettid),(long)getpid(),EE_COLD_MODE);
 ee_emit(1,"PREINIT","app_base=%#lx uipc_base=%#lx installed=8 ee_can_publish=0 functional_model=1 mode=%s",app_base,ee_uipc_base,EE_COLD_MODE);
 dprintf(logfd,"USB_START AP_PREINIT_CONFIRMED tid=%ld pid=%ld base=%#lx resolved=0x300000 both_entries=1\n",syscall(SYS_gettid),(long)getpid(),app_base);
 pthread_mutex_lock(&ee_cold_lock);pid_t child=fork();assert(child>=0);
 if(!child){ee_cold_recv_enter();_exit(ee_cold_resources()==0?0:1);}
 pthread_mutex_unlock(&ee_cold_lock);int status;assert(waitpid(child,&status,0)==child&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
 pthread_t r;assert(!pthread_create(&r,0,receiver,0));pthread_mutex_lock(&native_lock);stage=1;pthread_cond_broadcast(&native_cond);while(completed<1)pthread_cond_wait(&native_cond,&native_lock);pthread_mutex_unlock(&native_lock);
 assert(receiver_tid!=free_tid);assert(!ee_cold_registration_event&&!ee_cold_queue_known);
 if(mode==27){
  assert(ee_cold_prime.free_returned&&!ee_cold_prime.free_rc&&ee_cold_prime.source_known&&ee_cold_prime.size_known);
  assert(ee_nwc_init_valid(&ee_cold_init,getpid(),7)&&ee_cold_resources()&&!ee_cold_failed);
  uintptr_t handle=0;errno=37;assert(!ee_queue(EE_QUEUE,(uintptr_t)&handle,0x3344,0x5566)&&errno==73);
  assert(handle==0x112233&&registrations==1&&ee_cold_queue_known&&!ee_cold_failed);
  target_registration_event=ee_cold_registration_event;assert(target_registration_event);
 }
 if(mode==1)ee_cold_prime.free_returned=0;
 if(mode==7)ee_cold_prime.generation++;
 if(mode==8){pthread_mutex_lock(&ee_cold_lock);ee_cold_consumer++;ee_cold_fail_locked(EE_NWC_LEASE);pthread_mutex_unlock(&ee_cold_lock);}
 if(mode==23)uconf_fixture[48]++;
 if(mode==31)ee_cold_init.pid++;
 if(mode==32)ee_cold_init.generation++;
 if(mode==33)ee_cold_init.abi_verified=0;
 if(mode==19)message=mapped+0x200000;
 if(mode==25)message=mapped;
 if(mode==26)message=mapped+0x200000-11;
 uint32_t value=0;errno=37;
 if(mode==24){ee_remember_register(1,2,app_base+0x35492bc,(struct ee_pair){1,1});ee_wait_enter(app_base+0x35492cc,0x33445566);}
 else assert(ee_cold_reader(0x1122,(uintptr_t)&value)==0x8877&&errno==71);
 if(!sends){pthread_mutex_lock(&native_lock);message=mapped+64;stage=2;pthread_cond_broadcast(&native_cond);pthread_mutex_unlock(&native_lock);}
 assert(!pthread_join(r,0));
 if(ee_cold_service){struct ee_nwc_snapshot s;assert(!ee_nwc_snapshot(ee_cold_service,&s));
  if(s.armed){
   assert(!s.selection.can_publish&&!s.gate.registration_event&&!s.gate.consumer_registered&&s.gate.registration_rc==EE_NWC_UNKNOWN);
   assert(s.gate.admission_source==EE_NWC_KERNELDEFAULT&&s.gate.consumer==(uintptr_t)receiver_tid);
  }else assert(!allocs&&!sends);
  if(mode==0||mode==28||mode==29){assert(s.retired&&!s.pending&&s.owned_copy&&s.received&&s.wait_returned&&s.reader_returned&&s.free_returned);assert(s.free_actor_tid!=(uintptr_t)receiver_tid);}
  else assert(!s.retired);
  if(mode==16){assert(s.fault&&s.pending);unsigned old=0,newer=0;for(unsigned i=0;i<8;i++)if(ee_cold_slots[i].message==message){if(ee_cold_slots[i].state==3)old++;if(ee_cold_slots[i].state==1)newer++;}assert(old==1&&newer==1);}
  unsigned char bytes[12];assert(ee_nwc_copy_owned(ee_cold_service,&s.lease,12,bytes)!=0); /* freed: no dereference */
  struct ee_nwc_snapshot handoff;assert(!ee_nwc_destroy(ee_cold_service,&handoff));ee_cold_service=NULL;
 }
 if(mode==27)assert(!allocs&&!sends&&waits==1&&registrations==1&&ee_cold_registration_event==target_registration_event);
 if(mode==0||mode==28||mode==29)assert(allocs==1&&sends==1&&rcvs==2&&sources==2&&sizes==2&&frees==2&&waits==1);
 else if(mode==9||mode==10||mode==14||mode==15||mode==16||mode==17||mode==18||mode==20||mode==21||mode==22)assert(sends==1);
 else assert(!sends);
 assert(!munmap(area,0x200000));close(memfd);close(logfd);return 0;
}
