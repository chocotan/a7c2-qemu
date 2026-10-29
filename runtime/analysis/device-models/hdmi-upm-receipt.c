/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "hdmi-upm-receipt.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>
#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "UPM diagnostic mailbox requires a little-endian guest"
#endif

static pthread_mutex_t mutex=PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Atomic unsigned int completed;
static struct full_hdmi_upm_mailbox *mailbox, expected;
static uint64_t physical, previous_lease, previous_free;
static int pending, failed;
static uint32_t le32(const unsigned char *p) {
    return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
}
static int kernel(uint64_t p) {
    return p>=UINT64_C(0xffffff8000000000) && p<UINT64_C(0xfffffffffffff000) && !(p&7);
}
static int user(uint64_t p) {return p>=0x10000 && p<UINT64_C(0x800000000000) && !(p&7);}
static int texts(uint64_t upm,uint64_t osal) {
    return kernel(upm) && kernel(osal) && upm<UINT64_C(0xfffffffffffff000)-0x126e8 &&
        osal<UINT64_C(0xfffffffffffff000)-0x478c;
}
static int bodies(const unsigned char *raw,const unsigned char *effective,unsigned int index) {
    return raw && effective && index<2 && le32(raw)==0x00920117 && le32(raw+4)==index*2 &&
        le32(raw+8)==0x009a0000 && !le32(raw+12) && !memcmp(raw,effective,4) &&
        le32(effective+4)==index*3 && !memcmp(raw+8,effective+8,8);
}
static uint64_t digest(const unsigned char *p) {
    uint64_t hash=UINT64_C(0xcbf29ce484222325);
    for(size_t i=0;i<FULL_HDMI_UPM_MAILBOX_BYTES;i++)
        if(!(i>=20 && i<24) && !(i>=152 && i<160))hash=(hash^p[i])*UINT64_C(0x100000001b3);
    return hash;
}
/* Host TEST snapshots exercise only this reader, never mailbox publication. */
static int validate_receipt(const void *snapshot,size_t bytes,const struct full_hdmi_upm_mailbox *e) {
    struct full_hdmi_upm_mailbox r;
    if(!snapshot || bytes!=sizeof r || !e)return FULL_HDMI_UPM_RECEIPT_ERROR;
    memcpy(&r,snapshot,sizeof r);
    if(e->magic!=FULL_HDMI_UPM_MAILBOX_MAGIC || e->version!=1 || !e->nonce ||
       e->owner_pid<=1 || e->owner_pid>INT_MAX || !e->lease || !user(e->user_pointer) ||
       !texts(e->upm_text,e->osal_text) || !bodies(e->raw,e->effective,e->index) ||
       !e->native_producer_tid || e->native_producer_tid>INT_MAX)return FULL_HDMI_UPM_RECEIPT_ERROR;
    if(r.magic!=e->magic || r.version!=e->version || r.status!=FULL_HDMI_UPM_RECEIPT ||
       r.nonce!=e->nonce || r.owner_pid!=e->owner_pid || r.lease!=e->lease ||
       r.user_pointer!=e->user_pointer || r.index!=e->index || memcmp(r.raw,e->raw,16) ||
       memcmp(r.effective,e->effective,16) || r.upm_text!=e->upm_text || r.osal_text!=e->osal_text ||
       r.native_producer_tid!=e->native_producer_tid || r.source!=0x909a015a ||
       r.queue!=0x80920572 || r.message_bytes!=16 || r.body_source!=0x009a0000 ||
       r.free_rc || r.ref_before!=1 || r.allocator_seen!=1 || r.stage_mask!=FULL_HDMI_UPM_MAILBOX_PROOF ||
       !kernel(r.receiver_task) || !kernel(r.producer_task) || r.receiver_task==r.producer_task ||
       !r.receiver_tid || r.receiver_tid>INT_MAX || r.receiver_tid==r.native_producer_tid ||
       r.consumer_pc!=e->upm_text+0x126e8 || r.free_return_pc!=e->upm_text+0x14c ||
       (r.allocator_pc!=e->osal_text+0x4720 && r.allocator_pc!=e->osal_text+0x4768 &&
        r.allocator_pc!=e->osal_text+0x478c) || !r.bridge_seq || r.free_seq<=r.bridge_seq ||
       !user(r.mapping_user_base) || r.mapping_user_base>r.user_pointer ||
       r.user_pointer-r.mapping_user_base<24 || r.user_pointer-r.mapping_user_base>0x200000-16 ||
       !kernel(r.mapping_kernel_base) || !kernel(r.kernel_pointer) ||
       r.kernel_pointer<r.mapping_kernel_base ||
       r.user_pointer-r.mapping_user_base!=r.kernel_pointer-r.mapping_kernel_base || r.reserved0)
        return FULL_HDMI_UPM_RECEIPT_ERROR;
    for(size_t i=0;i<sizeof r.reserved;i++)if(r.reserved[i])return FULL_HDMI_UPM_RECEIPT_ERROR;
    return r.digest==digest((const unsigned char *)&r)?0:FULL_HDMI_UPM_RECEIPT_ERROR;
}
#ifdef FULL_HDMI_UPM_RECEIPT_TEST
int full_hdmi_upm_receipt_validate(const void *snapshot,size_t bytes,const struct full_hdmi_upm_mailbox *e) {
    return validate_receipt(snapshot,bytes,e);
}
#endif

static int module_text(const char *path,uint64_t *base) {
    char buf[32];int fd=open(path,O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return -1;
    ssize_t n=read(fd,buf,sizeof buf);int rc=close(fd);
    if(rc || n<3 || n>19 || buf[0]!='0' || buf[1]!='x')return -1;
    if(buf[n-1]=='\n')n--;
    if(n<3 || n>18)return -1;
    uint64_t value=0;
    for(ssize_t i=2;i<n;i++) {
        unsigned char c=(unsigned char)buf[i];unsigned int d;
        if(c>='0' && c<='9')d=c-'0';
        else if(c>='a' && c<='f')d=c-'a'+10;
        else if(c>='A' && c<='F')d=c-'A'+10;
        else return -1;
        value=(value<<4)|d;
    }
    *base=value;return 0;
}
static int page_physical(uint64_t *result) {
    uint64_t entry=0,va=(uint64_t)(uintptr_t)mailbox;
    int fd=open("/proc/self/pagemap",O_RDONLY|O_CLOEXEC|O_NOFOLLOW);
    if(fd<0)return -1;
    ssize_t n=pread(fd,&entry,sizeof entry,(off_t)((va/4096)*8));int rc=close(fd);
    uint64_t pfn=entry&((UINT64_C(1)<<55)-1);
    if(rc || n!=8 || !(entry&(UINT64_C(1)<<63)) || (entry&(UINT64_C(1)<<62)) ||
       !pfn || pfn>(UINT64_MAX>>12) || (va&4095))return -1;
    *result=pfn<<12;return 0;
}
static int initialize(void) {
    if(sysconf(_SC_PAGESIZE)!=4096 || geteuid()!=0 ||
       module_text("/sys/module/upm/sections/.text",&expected.upm_text) ||
       module_text("/sys/module/osal_uipc/sections/.text",&expected.osal_text) ||
       !texts(expected.upm_text,expected.osal_text) ||
       syscall(SYS_getrandom,&expected.nonce,sizeof expected.nonce,1)!=8 || !expected.nonce)return -1;
    void *p=mmap(NULL,FULL_HDMI_UPM_MAILBOX_PAGE,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    if(p==MAP_FAILED)return -1;
    mailbox=p;memset(mailbox,0,FULL_HDMI_UPM_MAILBOX_PAGE);
    /* Retain this mapping even on failure; this owner can never reinitialize. */
    if(mlock(mailbox,FULL_HDMI_UPM_MAILBOX_PAGE) || page_physical(&physical))return -1;
    expected.magic=FULL_HDMI_UPM_MAILBOX_MAGIC;expected.version=1;
    expected.owner_pid=(uint32_t)getpid();return 0;
}
static void snapshot(struct full_hdmi_upm_mailbox *out) {
    volatile const unsigned char *p=(volatile const unsigned char *)mailbox;
    for(size_t i=0;i<sizeof *out;i++)((unsigned char *)out)[i]=p[i];
    atomic_thread_fence(memory_order_acquire);
}
static int wait_status(uint32_t want,uint32_t before,struct full_hdmi_upm_mailbox *out) {
    struct timespec start,now,pause={0,10000000};
    if(clock_gettime(CLOCK_MONOTONIC,&start))return -1;
    for(unsigned int i=0;i<1000;i++) {
        uint32_t status=__atomic_load_n(&mailbox->status,__ATOMIC_ACQUIRE);
        if(status==want) {
            snapshot(out);
            return out->status==want && __atomic_load_n(&mailbox->status,__ATOMIC_ACQUIRE)==want?0:-1;
        }
        if(status!=before || clock_gettime(CLOCK_MONOTONIC,&now) ||
           now.tv_sec-start.tv_sec>10 ||
           (now.tv_sec-start.tv_sec==10 && now.tv_nsec>=start.tv_nsec))return -1;
        if(nanosleep(&pause,NULL) && errno!=EINTR)return -1;
    }
    return -1;
}
static void note(void (*record)(const char *,const char *),const char *tag) {
    char raw[33],effective[33],line[640];
    for(unsigned int i=0;i<16;i++) {
        snprintf(raw+2*i,3,"%02x",expected.raw[i]);snprintf(effective+2*i,3,"%02x",expected.effective[i]);
    }
    snprintf(line,sizeof line,"pid=%u tid=%ld user_va=%#" PRIxPTR " physical=%#" PRIx64
        " bytes=4096 nonce=%#" PRIx64 " upm_text=%#" PRIx64 " osal_text=%#" PRIx64
        " version=1 record_bytes=256 lease=%" PRIu64 " U=%#" PRIx64 " index=%u raw=%s effective=%s",
        expected.owner_pid,syscall(SYS_gettid),(uintptr_t)mailbox,physical,expected.nonce,
        expected.upm_text,expected.osal_text,expected.lease,expected.user_pointer,expected.index,raw,effective);
    record(tag,line);
}
int full_hdmi_upm_receipt(unsigned int stage,unsigned long long lease,void *pointer,
    const unsigned char raw[16],const unsigned char effective[16],void (*record)(const char *,const char *)) {
    int pid=(int)getpid(),unowned=0;long tid=syscall(SYS_gettid);
    unsigned int index=raw && le32(raw+4)==2?1:0;
    if(stage>1 || !record || !lease || !user((uint64_t)(uintptr_t)pointer) ||
       !bodies(raw,effective,index) || pid<=1 || tid<=0 || tid>INT_MAX ||
       atomic_load(&completed)>=2)return FULL_HDMI_UPM_RECEIPT_ERROR;
    atomic_compare_exchange_strong(&owner_pid,&unowned,pid);
    if(atomic_load(&owner_pid)!=pid)return FULL_HDMI_UPM_RECEIPT_ERROR; /* Refuse fork before mutex. */
    pthread_mutex_lock(&mutex);
    const char *error=NULL;
    struct full_hdmi_upm_mailbox received;
    uint64_t actual_physical=0;
    if(failed)error="prior-fault";
    else if(index!=atomic_load(&completed))error="transaction-order";
    else if(!stage) {
        if(pending || lease<=previous_lease)error="duplicate-or-old-prepare";
        else if(!mailbox && initialize())error="mailbox-init-unavailable";
        else {
            uint64_t nonce=expected.nonce,upm=expected.upm_text,osal=expected.osal_text;
            expected=(struct full_hdmi_upm_mailbox){.magic=FULL_HDMI_UPM_MAILBOX_MAGIC,.version=1,
                .nonce=nonce,.owner_pid=(uint32_t)pid,.lease=lease,.user_pointer=(uint64_t)(uintptr_t)pointer,
                .index=index,.native_producer_tid=(uint32_t)tid,.upm_text=upm,.osal_text=osal,
                .source=0x909a015a,.queue=0x80920572,.message_bytes=16,.body_source=0x009a0000};
            memcpy(expected.raw,raw,16);memcpy(expected.effective,effective,16);
            /* Preserve host arming across the one permitted second transaction. */
            expected.status=index?FULL_HDMI_UPM_ARMED:FULL_HDMI_UPM_UNARMED;
            memcpy(mailbox,&expected,sizeof expected);
            atomic_thread_fence(memory_order_release);
            note(record,index?"FULL_HDMI_UPM_MAILBOX_PREPARE ":"FULL_HDMI_UPM_MAILBOX_INIT ");
            if(wait_status(FULL_HDMI_UPM_ARMED,expected.status,&received))error="arming-timeout-or-status";
            else {
                received.status=expected.status;
                if(memcmp(&received,&expected,sizeof expected))error="arming-identity-changed";
                else if(page_physical(&actual_physical) || actual_physical!=physical)error="physical-page-changed";
                else {pending=1;__atomic_store_n(&mailbox->status,FULL_HDMI_UPM_REQUEST,__ATOMIC_RELEASE);}
            }
        }
    } else if(!pending || expected.lease!=lease || expected.user_pointer!=(uint64_t)(uintptr_t)pointer ||
              memcmp(raw,expected.raw,16) || memcmp(effective,expected.effective,16) ||
              expected.native_producer_tid!=(uint32_t)tid)error="receipt-request-mismatch";
    else if(wait_status(FULL_HDMI_UPM_RECEIPT,FULL_HDMI_UPM_REQUEST,&received))error="receipt-timeout-or-status";
    else if(validate_receipt(&received,sizeof received,&expected) || received.bridge_seq<=previous_free)
        error="invalid-native-receipt";
    else if(page_physical(&actual_physical) || actual_physical!=physical)error="physical-page-changed";
    else {
        previous_lease=lease;previous_free=received.free_seq;pending=0;atomic_fetch_add(&completed,1);
        note(record,"FULL_HDMI_UPM_MAILBOX_CONSUMED ");
    }
    if(error) {failed=1;record("FULL_HDMI_UPM_MAILBOX_REJECT ",error);}
    pthread_mutex_unlock(&mutex);
    return error?FULL_HDMI_UPM_RECEIPT_ERROR:0;
}
