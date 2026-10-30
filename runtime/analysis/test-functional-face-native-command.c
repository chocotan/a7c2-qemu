/* SPDX-License-Identifier: MIT */
/* Host ABI execution only: dladdr/prologue/TID boundaries are explicit fakes. */
#define _GNU_SOURCE
#include <assert.h>
#include <dlfcn.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#include "functional-face-ap-observer.h"

#define UNIT UINT32_C(0x1d9)
#define HANDLE UINT32_C(0x42d) /* AP slot 0x2d, generation 1, chip 0. */
#define QUEUE UINT32_C(0x0081cf42)
#define TID INT64_C(777)
#define ADDRESS UINT64_C(0x123456789000)

enum trust_boundary {
    TRUST_OK, LOOKUP_FAIL, WRONG_BASE, NULL_NAME, WRONG_SUFFIX, FALSE_SUFFIX,
    BARE_NAME, OPEN_FAIL, FIRST_BAD, SECOND_BAD, FIRST_SHORT, SECOND_SHORT, READ_FAIL
};
enum receipt {
    COMPLETE, NO_TRANSACTION, SEND_FAILED, NO_RECEIPT, FOREIGN_TID, WRONG_OP,
    WRONG_REPLY, NO_FREE, FREE_FAILED, TWO_TRANSACTIONS
};
static int functional_camera_enabled=1;
static unsigned long appfw_base;
static _Thread_local struct functional_face_ap_observer functional_face_ap_state;
static enum trust_boundary trust;
static enum receipt receipt;
static unsigned int command_op,command_unit,command_handle;
static uintptr_t host_address;
static int helper_error,kernel_status,native_calls,lookups,opens,reads,closes,records,checks;
static int logged_error,logged_rc;
static unsigned int events[6];
static uint32_t reply_handle;
static unsigned char request_wire[40],reply_wire[40];
static char last_record[512];

static long fixture_syscall(long number) {
    assert(number==178);errno=EDOM;return TID;
}
static int fixture_dladdr(void *address,Dl_info *info) {
    assert((uintptr_t)address==host_address);++lookups;errno=EILSEQ;
    assert((uintptr_t)address==appfw_base+(command_op==0x21?0x3552b3cUL:
        command_op==0x24?0x355258cUL:command_op==0x25?0x35527c8UL:0x35523b0UL));
    if(trust==LOOKUP_FAIL)return 0;
    info->dli_fbase=(void *)(uintptr_t)(appfw_base+(trust==WRONG_BASE?8UL:0UL));
    info->dli_fname=trust==NULL_NAME?NULL:trust==WRONG_SUFFIX?"/fixture/appFw.so.old":
        trust==FALSE_SUFFIX?"/fixture/notappFw.so":trust==BARE_NAME?"appFw.so":"/fixture/appFw.so";
    return 1;
}
static int (*real_dladdr)(void *,Dl_info *)=fixture_dladdr;
static int fixture_open(const char *path,int flags) {
    assert(!strcmp(path,"/proc/self/mem") && !flags);++opens;errno=EACCES;
    return trust==OPEN_FAIL?-1:43;
}
static ssize_t fixture_pread(int fd,void *out,size_t bytes,off_t offset) {
    assert(fd==43 && out && bytes==8 && (uintptr_t)offset==host_address);
    assert(reads<2);++reads;errno=EFAULT;
    uint64_t prologue=UINT64_C(0x910003fda9ba7bfd);
    if((trust==FIRST_BAD && reads==1) || (trust==SECOND_BAD && reads==2))prologue^=1;
    memcpy(out,&prologue,8);
    if(trust==READ_FAIL)return -1;
    if((trust==FIRST_SHORT && reads==1) || (trust==SECOND_SHORT && reads==2))return 7;
    return 8;
}
static int fixture_close(int fd) {
    assert(fd==43 && reads==2);++closes;errno=EBADF;return 0;
}
static void record(const char *prefix,const char *text) {
    assert(!strcmp(prefix,"FUNCTIONAL_FACE_DMM_NATIVE_AP_COMMAND "));
    assert(native_calls==1 && strlen(text)<sizeof last_record);++records;
    strcpy(last_record,text);
    const char *error=strstr(text,"helper_error="),*capture=strstr(text,"capture_rc=");
    assert(error && capture);
    assert(sscanf(error,"helper_error=%d",&logged_error)==1);
    assert(sscanf(capture,"capture_rc=%d",&logged_rc)==1);
    assert(strstr(text,"result_storage_bytes=32") && strstr(text,"original_api_invoked=1") && strstr(text,"raw_ticket_capture_only=1"));
    assert(strstr(text,"allocation_pin_verified=0") && strstr(text,"physical_verified=0"));
    assert(strstr(text,"capture_verified=0"));errno=ERANGE;
}
#define syscall fixture_syscall
#define open fixture_open
#define pread fixture_pread
#define close fixture_close
/* ACTUAL_NATIVE_COMMAND */
#undef syscall
#undef open
#undef pread
#undef close

_Static_assert(offsetof(struct functional_face_native_dmm_input,handle)==8,"input handle at +8");
_Static_assert(offsetof(struct functional_face_native_dmm_result,address)==8,"address at +8");
_Static_assert(offsetof(struct functional_face_native_dmm_result,bytes)==16,"length at +16");
_Static_assert(offsetof(struct functional_face_native_dmm_result,reserved)==20,"reserved at +20");
_Static_assert(offsetof(struct functional_face_native_dmm_result,error)==24,"SDK error at +24");
_Static_assert(offsetof(struct functional_face_native_dmm_result,padding)==28,"guard at +28");

static void put16(unsigned char *p,uint16_t v) { p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8); }
static void put32(unsigned char *p,uint32_t v) { for(size_t i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i)); }
static void put64(unsigned char *p,uint64_t v) { for(size_t i=0;i<8;i++)p[i]=(unsigned char)(v>>(8*i)); }
static void event(enum functional_face_ap_event kind,const struct functional_face_ap_observer *s) {
    assert(kind>=FACE_AP_SUBMIT && kind<=FACE_AP_RETAINED && s==&functional_face_ap_state);
    ++events[kind];errno=ECHRNG;
}
/* The mode-0 request fields follow the saved OP40-MATRIX; reply payloads are host fixtures. */
static void transaction(unsigned int op,int status,uint32_t source,enum receipt behavior) {
    unsigned int actual_op=behavior==WRONG_OP?(op==0x24?0x25:0x24):op;
    memset(request_wire,0,sizeof request_wire);memset(reply_wire,0,sizeof reply_wire);
    put16(request_wire,(uint16_t)actual_op);
    if(actual_op==0x20 || actual_op==0x21)put32(request_wire+4,command_unit);
    if(actual_op!=0x20)put32(request_wire+8,command_handle);
    if(actual_op==0x20 || actual_op==0x24)put32(request_wire+12,UINT32_MAX);
    if(actual_op==0x23)put16(request_wire+20,(uint16_t)QUEUE);
    put16(reply_wire,(uint16_t)((actual_op|0x8000u)+(behavior==WRONG_REPLY?1u:0u)));
    put16(reply_wire+2,(uint16_t)status);put32(reply_wire+12,reply_handle);
    put64(reply_wire+24,ADDRESS);put32(reply_wire+32,8192);
    assert(functional_face_ap_begin(&functional_face_ap_state,1,1,TID,FUNCTIONAL_FACE_AP_DMM,
        QUEUE,request_wire,sizeof request_wire,event)==1);
    int64_t tid=behavior==FOREIGN_TID?TID+1:TID;
    functional_face_ap_sent(&functional_face_ap_state,tid,behavior==SEND_FAILED?-71:0,event);
    if(behavior==SEND_FAILED || behavior==NO_RECEIPT)return;
    functional_face_ap_received(&functional_face_ap_state,tid,QUEUE,source,reply_wire,sizeof reply_wire,0,event);
    if(behavior==NO_FREE)return;
    functional_face_ap_freed(&functional_face_ap_state,tid,QUEUE,reply_wire,behavior==FREE_FAILED?-17:0,event);
}
static void original_core(void) {
    assert(native_calls==0 && lookups==1 && opens==1 && reads==2 && closes==1);++native_calls;
    if(receipt!=NO_TRANSACTION) {
        transaction(command_op,kernel_status,FUNCTIONAL_FACE_AP_DMM,receipt);
        if(receipt==TWO_TRANSACTIONS)transaction(command_op,kernel_status,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
    }
    errno=EAGAIN;
}
static void descriptor(const struct functional_face_native_dmm_input *input,
    struct functional_face_native_dmm_result *output) {
    unsigned char expected[12];put32(expected,command_unit);put32(expected+4,0);put32(expected+8,command_handle);
    assert(input && output && !memcmp(input,expected,sizeof expected));
    assert(!output->unit && !output->handle && !output->address && !output->bytes);
    assert(!output->reserved && !output->error && !output->padding);
    original_core();
    output->unit=command_unit;output->handle=reply_handle;output->address=ADDRESS;
    output->bytes=8192;output->reserved=UINT32_C(0x13579bdf);
    output->error=(uint32_t)helper_error;output->padding=UINT32_C(0xa55aa55a);
}
static void host_share(const struct functional_face_native_dmm_input *input,
    struct functional_face_native_dmm_result *output) {
    assert(command_op==0x21);descriptor(input,output);
}
static void host_open(const struct functional_face_native_dmm_input *input,
    struct functional_face_native_dmm_result *output) {
    assert(command_op==0x24);descriptor(input,output);
}
static void host_close(const uint32_t *handle,int *error) {
    assert(command_op==0x25 && handle && *handle==command_handle && error && !*error);
    original_core();*error=helper_error;
}
static int host_free(uint32_t handle,unsigned int mode) {
    assert(command_op==0x23 && handle==command_handle && !mode);original_core();return helper_error;
}
static void reset(unsigned int op) {
    functional_face_ap_state=(struct functional_face_ap_observer){0};
    functional_camera_enabled=1;command_op=op;command_unit=UNIT;command_handle=HANDLE;reply_handle=HANDLE;
    trust=TRUST_OK;receipt=COMPLETE;helper_error=0;kernel_status=0;
    native_calls=0;lookups=0;opens=0;reads=0;closes=0;records=0;
    logged_error=0;logged_rc=0;memset(events,0,sizeof events);memset(last_record,0,sizeof last_record);
    real_dladdr=fixture_dladdr;
    unsigned long entry;
    switch(op) {
    case 0x21:host_address=(uintptr_t)host_share;entry=0x3552b3cUL;break;
    case 0x24:host_address=(uintptr_t)host_open;entry=0x355258cUL;break;
    case 0x25:host_address=(uintptr_t)host_close;entry=0x35527c8UL;break;
    case 0x23:host_address=(uintptr_t)host_free;entry=0x35523b0UL;break;
    default:assert(0);return;
    }
    appfw_base=(unsigned long)(host_address-entry);assert(appfw_base+entry==host_address);
}
static void seed(void) {
    transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
    struct functional_face_ap_birth birth={0};
    assert(!functional_face_ap_observed_birth(&functional_face_ap_state,TID,command_unit,command_handle,&birth));
    assert(birth.unit==command_unit && birth.handle==command_handle && birth.observations==1);
    assert(birth.observation_sequence==1 && !birth.ambiguous && !birth.any_free_observed);
    assert(birth.reply_source==FUNCTIONAL_FACE_AP_DMM);
}
static void check_command(int expected,int calls,int null_output) {
    struct functional_face_ap_observer output,untouched,before=functional_face_ap_state;
    memset(&output,0xa5,sizeof output);memcpy(&untouched,&output,sizeof output);
    memset(events,0,sizeof events);errno=EINTR;
    int result=functional_face_native_ap_command((void *)(uintptr_t)0xabcd,command_op,
        command_unit,command_handle,null_output?NULL:&output);
    assert(result==expected && errno==EINTR && native_calls==calls);++checks;
    if(!calls) {
        assert(!records && !memcmp(&output,&untouched,sizeof output));
        assert(!memcmp(&before,&functional_face_ap_state,sizeof before));return;
    }
    assert(records==1 && logged_rc==expected && logged_error==helper_error);
    assert(lookups==1 && opens==1 && reads==2 && closes==1);
    assert(!memcmp(&output,&functional_face_ap_state,sizeof output));
    assert(output.births[0].observation_sequence==before.births[0].observation_sequence);
    if(!expected) {
        assert(output.owner_pid==getpid() && output.sender_tid==TID && output.sequence==before.sequence+1);
        assert(output.op==command_op && !output.active && output.send_seen && !output.send_result);
        assert(output.received && output.free_attempts==1 && !output.free_result);
        assert(output.reply_source==FUNCTIONAL_FACE_AP_DMM && output.reply_bytes==40);
        assert(!memcmp(output.request_wire,request_wire,40) && !memcmp(output.reply_wire,reply_wire,40));
        assert(events[FACE_AP_SUBMIT]==1 && events[FACE_AP_SEND_RETURN]==1);
        assert(events[FACE_AP_RECEIVE]==1 && events[FACE_AP_FREE_RETURN]==1);
    }
}
static void success(unsigned int op) {
    for(uint32_t unit=UNIT;unit<=0x1db;unit++) {
        reset(op);command_unit=unit;seed();check_command(0,1,0);
        assert(functional_face_ap_state.sequence==2);
        assert(functional_face_ap_state.births[unit-UNIT].handle==HANDLE);
    }
}
static void gates(void) {
    for(int condition=0;condition<9;condition++) {
        reset(0x21);seed();
        switch(condition) {
        case 0:functional_camera_enabled=0;break;
        case 1:appfw_base=0;break;
        case 2:real_dladdr=NULL;break;
        case 3:command_unit=UNIT-1;break;
        case 4:command_unit=0x1dc;break;
        case 5:command_unit=UINT32_MAX;break;
        case 6:break;
        case 7:command_op=0x22;break;
        case 8:appfw_base=UINTPTR_MAX;break;
        }
        check_command(condition==8?-EOVERFLOW:condition==7?-ENOTSUP:-ENODATA,0,condition==6);
        assert(!lookups && !opens && !reads && !closes);
    }
}
static void births(void) {
    reset(0x21);check_command(-ECHILD,0,0);
    reset(0x21);seed();++command_unit;check_command(-ESTALE,0,0);
    reset(0x21);seed();++command_handle;check_command(-ESTALE,0,0);
    reset(0x21);seed();command_handle|=0x8000;check_command(-ESTALE,0,0);
    reset(0x21);seed();transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
    assert(functional_face_ap_state.births[0].ambiguous && functional_face_ap_state.births[0].observations==2);
    check_command(-ESTALE,0,0);
    reset(0x21);seed();reply_handle=HANDLE+0x400;transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
    assert(functional_face_ap_state.births[0].handle==HANDLE && functional_face_ap_state.births[0].ambiguous);
    check_command(-ESTALE,0,0);
}
static void prior(void) {
    reset(0x21);seed();transaction(0x24,0,FUNCTIONAL_FACE_AP_DMM,NO_FREE);
    assert(functional_face_ap_state.active);check_command(-EBUSY,0,0);assert(!lookups);
    reset(0x21);seed();functional_face_ap_state.sequence=UINT64_MAX;
    check_command(-EBUSY,0,0);assert(!lookups);
}
static void libraries(void) {
    const enum trust_boundary cases[]={LOOKUP_FAIL,WRONG_BASE,NULL_NAME,WRONG_SUFFIX,FALSE_SUFFIX};
    for(size_t i=0;i<sizeof cases/sizeof cases[0];i++) {
        reset(0x21);seed();trust=cases[i];check_command(-ELIBBAD,0,0);
        assert(lookups==1 && !opens && !reads && !closes);
    }
    reset(0x24);seed();trust=BARE_NAME;check_command(0,1,0);
}
static void prologues(void) {
    const enum trust_boundary cases[]={OPEN_FAIL,FIRST_BAD,SECOND_BAD,FIRST_SHORT,SECOND_SHORT,READ_FAIL};
    for(size_t i=0;i<sizeof cases/sizeof cases[0];i++) {
        reset(0x21);seed();trust=cases[i];check_command(-ELIBBAD,0,0);
        assert(lookups==1 && opens==1);
        assert(reads==(trust==OPEN_FAIL?0:2) && closes==(trust==OPEN_FAIL?0:1));
    }
}
static void helper_errors(void) {
    const unsigned int ops[]={0x21,0x24,0x25,0x23};
    for(size_t i=0;i<sizeof ops/sizeof ops[0];i++) {
        reset(ops[i]);seed();helper_error=-1023;check_command(-EIO,1,0);
        assert(functional_face_ap_state.received && !functional_face_ap_state.active);
    }
    reset(0x24);seed();helper_error=7;check_command(-EIO,1,0);
    reset(0x23);seed();helper_error=-71;receipt=SEND_FAILED;check_command(-EIO,1,0);
    assert(functional_face_ap_state.send_result==-71 && !functional_face_ap_state.received);
}
static void receipts(void) {
    const enum receipt cases[]={NO_TRANSACTION,SEND_FAILED,NO_RECEIPT,FOREIGN_TID,WRONG_OP,
        WRONG_REPLY,NO_FREE,FREE_FAILED,TWO_TRANSACTIONS};
    for(size_t i=0;i<sizeof cases/sizeof cases[0];i++) {
        reset(0x21);seed();receipt=cases[i];check_command(-ENODATA,1,0);
        if(receipt==NO_TRANSACTION)assert(functional_face_ap_state.sequence==1 && !events[FACE_AP_SUBMIT]);
        if(receipt==SEND_FAILED)assert(functional_face_ap_state.send_result==-71 && !functional_face_ap_state.received);
        if(receipt==FOREIGN_TID)assert(!functional_face_ap_state.send_seen && functional_face_ap_state.active);
        if(receipt==WRONG_OP)assert(functional_face_ap_state.op==0x24);
        if(receipt==NO_FREE)assert(functional_face_ap_state.received && !functional_face_ap_state.free_attempts);
        if(receipt==FREE_FAILED)assert(functional_face_ap_state.free_result==-17 && functional_face_ap_state.active);
        if(receipt==TWO_TRANSACTIONS)assert(functional_face_ap_state.sequence==3);
    }
}
static void raw_kernel_error(void) {
    reset(0x23);seed();kernel_status=-7;check_command(0,1,0);
    assert(functional_face_ap_state.reply_wire[2]==0xf9 && functional_face_ap_state.reply_wire[3]==0xff);
    assert(functional_face_ap_state.births[0].any_free_observed);
    assert(logged_error==0 && logged_rc==0);
    puts("RAW_KERNEL_ERROR_PRESERVED transport_rc=0 capture_rc=0 raw_status=-7 provider_status_validation_required=1 native_success_claimed=0");
}
static void birth_provenance(void) {
    for(int condition=0;condition<9;condition++) {
        reset(0x21);
        if(condition==0)transaction(0x20,-7,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
        if(condition==1)transaction(0x20,1,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
        if(condition==2)transaction(0x20,0,UINT32_C(0x8061003c),COMPLETE);
        if(condition==3)transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,FREE_FAILED);
        if(condition==4)transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,SEND_FAILED);
        if(condition==5)transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,WRONG_REPLY);
        if(condition>=6) {
            reply_handle=condition==6?0:condition==7?0x802d:0x2d;
            transaction(0x20,0,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
        }
        if(condition>=6)assert(functional_face_ap_state.births[0].observations==1 && functional_face_ap_state.births[0].ambiguous);
        else assert(!functional_face_ap_state.births[0].observations);
        check_command(-ESTALE,0,0);
    }
}
static void lifetime_facts(void) {
    reset(0x21);seed();transaction(0x23,-7,FUNCTIONAL_FACE_AP_DMM,COMPLETE);
    struct functional_face_ap_birth birth={0};
    assert(!functional_face_ap_observed_birth(&functional_face_ap_state,TID,UNIT,HANDLE,&birth));
    assert(birth.any_free_observed && birth.observation_sequence==1 && birth.observations==1);
    check_command(0,1,0);
    assert(functional_face_ap_state.sequence==3 && functional_face_ap_state.births[0].any_free_observed);
    puts("BIRTH_FACTS_PRESERVED birth_sequence=1 any_free_observed=1 allocation_epoch_claimed=0 retained_owner_claimed=0");
}
static void fork_guard(void) {
    reset(0x21);seed();pid_t child=fork();assert(child>=0);
    if(!child) { check_command(-ECHILD,0,0);assert(!lookups);_exit(0); }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!native_calls && !lookups && functional_face_ap_state.owner_pid==getpid());++checks;
}
static void sequence_edge(void) {
    reset(0x25);seed();functional_face_ap_state.sequence=UINT64_MAX-1;
    check_command(0,1,0);assert(functional_face_ap_state.sequence==UINT64_MAX);
    reset(0x21);seed();struct functional_face_ap_birth birth={0};
    assert(functional_face_ap_observed_birth(&functional_face_ap_state,TID+1,UNIT,HANDLE,&birth)==-ECHILD);
    functional_face_ap_state.sender_tid=TID+1;check_command(-ECHILD,0,0);assert(!lookups);
}
int main(int argc,char **argv) {
    assert(argc==2);const char *mode=argv[1];
    if(!strcmp(mode,"share"))success(0x21);
    else if(!strcmp(mode,"open"))success(0x24);
    else if(!strcmp(mode,"close"))success(0x25);
    else if(!strcmp(mode,"free"))success(0x23);
    else if(!strcmp(mode,"gates"))gates();
    else if(!strcmp(mode,"birth"))births();
    else if(!strcmp(mode,"prior"))prior();
    else if(!strcmp(mode,"library"))libraries();
    else if(!strcmp(mode,"prologue"))prologues();
    else if(!strcmp(mode,"helper-error"))helper_errors();
    else if(!strcmp(mode,"receipt"))receipts();
    else if(!strcmp(mode,"raw-kernel-error"))raw_kernel_error();
    else if(!strcmp(mode,"birth-provenance"))birth_provenance();
    else if(!strcmp(mode,"lifetime-facts"))lifetime_facts();
    else if(!strcmp(mode,"fork"))fork_guard();
    else if(!strcmp(mode,"sequence-edge"))sequence_edge();
    else assert(0);
    printf("NATIVE_COMMAND_HOSTTEST_PASS scenario=%s checks=%d actual_observer=1 native_pin=0 capture_verified=0\n",mode,checks);
    return 0;
}
