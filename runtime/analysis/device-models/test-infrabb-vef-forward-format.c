/* SPDX-License-Identifier: MIT */
/* Real fourth-edge owner and byte-array backing; no VM evidence. */
#define FULL_INFRABB_VEF_CONNECTION_TEST_MAIN fourth_edge_prerequisite_main
#include "test-infrabb-vef-connection.c"
#undef FULL_INFRABB_VEF_CONNECTION_TEST_MAIN
#include "pin-format.h"
static unsigned int forward_logs;
static unsigned int forward_handle;
static unsigned long long forward_hash(const unsigned char *p,unsigned int n){
    unsigned long long value=0xcbf29ce484222325ULL;for(unsigned int i=0;i<n;i++)value=(value^p[i])*0x100000001b3ULL;return value;
}
static void forward_record(const char *tag,const char *text){
    struct full_infrabb_vef_connection_snapshot s=iv_snapshot();int changed=91;
    if(!strcmp(tag,"FULL_INFRABB_VEF_FORWARD_VEF_FORMAT_CONSUMED ")){
        assert(s.forwarded_vef_formats==1 && !s.forwarded_bb_formats);
        assert(full_infrabb_vef_connection_accept_forwarded_vef_format(forward_handle,0)==-1021);
    }else{
        assert(!strcmp(tag,"FULL_INFRABB_VEF_FORWARD_BB_FORMAT_CONSUMED "));
        assert(s.forwarded_bb_formats==1);
        assert(full_infrabb_vef_connection_accept_forwarded_bb_format(forward_handle,0,&changed)==-1021 && !changed);
    }
    assert(strstr(text,"mapped_backing_read=1") && strstr(text,"capture_verified=0"));
    forward_logs++;fprintf(stdout,"%s%s\n",tag,text);
}
static const struct full_imaging_io forward_io={.record=forward_record};
static struct pin_control_lease forward_allocate(const unsigned char *packet){
    struct pin_control_lease l={0},opened={0};assert(!pin_control_allocate(PIN_CONTROL_UNIT,&l));
    assert(!pin_control_write_payload(l.handle,packet,80,0));assert(!pin_control_close_creator(l.handle));
    assert(!pin_control_transfer_creator(l.handle,PIN_CONTROL_UNIT));assert(!pin_control_open_consumer(l.handle,PIN_CONTROL_UNIT,&opened));
    assert(l.handle==opened.handle && l.physical==opened.physical);return l;
}
static void forward_unchanged(const struct full_infrabb_vef_connection_snapshot *before,unsigned long long reads){
    struct full_infrabb_vef_connection_snapshot after=iv_snapshot();assert(!memcmp(before,&after,sizeof after));
    struct pin_control_snapshot pool;pin_control_snapshot(&pool);assert(pool.consumer_reads==reads);
}
static void forward_history(const struct full_infrabb_vef_connection_snapshot *before){
    struct full_infrabb_vef_connection_snapshot after=iv_snapshot();
    memcpy(after.format.current,before->format.current,20);memcpy(after.format.expected,before->format.expected,16);
    after.format.current_fnv=before->format.current_fnv;
    after.format.forwarded_vef_payload_fnv=before->format.forwarded_vef_payload_fnv;
    after.format.forwarded_bb_payload_fnv=before->format.forwarded_bb_payload_fnv;
    after.forwarded_vef_formats=before->forwarded_vef_formats;after.forwarded_bb_formats=before->forwarded_bb_formats;
    after.forwarded_format_handle=before->forwarded_format_handle;
    assert(!memcmp(&after,before,sizeof after));iv_preserved();
}
int main(int argc,char **argv){
    assert(argc==3);const char *name=argv[1];host_pid=getpid();alarm(30);
    if(!strcmp(name,"no-prior")){
        assert(!full_infrabb_vef_connection_owner_init());struct full_infrabb_vef_connection_snapshot before=iv_snapshot();
        int changed=91;assert(full_infrabb_vef_connection_accept_forwarded_vef_format(0,&forward_io)==-1021);
        assert(full_infrabb_vef_connection_accept_forwarded_bb_format(0,&forward_io,&changed)==-1021 && !changed);
        struct full_infrabb_vef_connection_snapshot after=iv_snapshot();assert(!memcmp(&before,&after,sizeof after) && !forward_logs);
        puts("INFRABB_VEF_FORWARD_HOST_TEST_PASS");return 0;
    }
    char *old[]={"fourth",!strcmp(name,"prior-fault")?"request-free-fail":"normal",argv[2],0};
    assert(!fourth_edge_prerequisite_main(3,old));alarm(30);
    struct full_infrabb_vef_connection_snapshot before=iv_snapshot();
    if(!strcmp(name,"prior-fault")){
        int changed=91;assert(before.faults && !before.clean_completion);
        assert(full_infrabb_vef_connection_accept_forwarded_vef_format(0,&forward_io)==-1021);
        assert(full_infrabb_vef_connection_accept_forwarded_bb_format(0,&forward_io,&changed)==-1021 && !changed);
        struct full_infrabb_vef_connection_snapshot after=iv_snapshot();assert(!memcmp(&before,&after,sizeof after));
        puts("INFRABB_VEF_FORWARD_HOST_TEST_PASS");return 0;
    }
    assert(before.clean_completion && before.ap_consumed && before.format.matches==1 && before.buffer_freed);
    struct pin_yc_parameters values={.raw_flags=3,.width=1920,.height=1080,.code=1,.component=1};
    if(!strcmp(name,"same")){values.raw_flags=0;values.component=0;}
    unsigned char packet[80];assert(!pin_yc_build(&values,packet,sizeof packet));
    struct pin_control_lease lease=forward_allocate(packet);forward_handle=lease.handle;assert(lease.handle!=before.buffer_handle);
    volatile unsigned char *actual=connect_memory+lease.slot*PIN_CONTROL_SLOT_BYTES;
    struct pin_control_snapshot pool;pin_control_snapshot(&pool);unsigned long long reads=pool.consumer_reads;
    struct pin_control_references refs_before,refs_after;assert(!pin_control_references(lease.handle,&refs_before));
    int changed=91;
    assert(full_infrabb_vef_connection_accept_forwarded_bb_format(lease.handle,&forward_io,&changed)==-1021 && !changed);
    forward_unchanged(&before,reads);
    assert(full_infrabb_vef_connection_accept_forwarded_bb_format(lease.handle,&forward_io,0)==-1021);forward_unchanged(&before,reads);
    if(!strcmp(name,"fork")){
        pid_t child=fork();assert(child>=0);if(!child){alarm(2);
            assert(full_infrabb_vef_connection_accept_forwarded_vef_format(lease.handle,&forward_io)==-1021);
            changed=91;assert(full_infrabb_vef_connection_accept_forwarded_bb_format(lease.handle,&forward_io,&changed)==-1021 && !changed);
            assert(!iv_snapshot().initialized && !forward_logs);_exit(0);
        }int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));forward_unchanged(&before,reads);
    }
    if(!strcmp(name,"closed")){
        assert(!pin_control_close_consumer(lease.handle));assert(full_infrabb_vef_connection_accept_forwarded_vef_format(lease.handle,&forward_io)==-1021);
        forward_unchanged(&before,reads);struct pin_control_lease opened;assert(!pin_control_open_consumer(lease.handle,PIN_CONTROL_UNIT,&opened));
    }
    if(!strcmp(name,"freed")){
        assert(!pin_control_release_consumer(lease.handle));assert(full_infrabb_vef_connection_accept_forwarded_vef_format(lease.handle,&forward_io)==-1021);
        forward_unchanged(&before,reads);puts("INFRABB_VEF_FORWARD_HOST_TEST_PASS");return 0;
    }
    if(!strcmp(name,"bad-packets")){
        for(unsigned int i=0;i<80;i++){
            if(i>=64 && i!=67 && (i<68 || i>=72))continue;
            actual[i]^=1;assert(full_infrabb_vef_connection_accept_forwarded_vef_format(lease.handle,&forward_io)==-1021);
            actual[i]^=1;forward_unchanged(&before,++reads);
        }
    }
    if(!strcmp(name,"creator-live")){
        struct pin_control_lease second,opened;assert(!pin_control_allocate(PIN_CONTROL_UNIT,&second));
        assert(!pin_control_write_payload(second.handle,packet,80,0));assert(!pin_control_share(second.handle,PIN_CONTROL_UNIT));
        assert(!pin_control_open_consumer(second.handle,PIN_CONTROL_UNIT,&opened));
        assert(full_infrabb_vef_connection_accept_forwarded_vef_format(second.handle,&forward_io)==-1021);
        forward_unchanged(&before,reads);assert(!pin_control_release_consumer(second.handle));assert(!pin_control_release(second.handle));
    }
    assert(!full_infrabb_vef_connection_accept_forwarded_vef_format(lease.handle,&forward_io));reads++;
    struct full_infrabb_vef_connection_snapshot vef=iv_snapshot();
    assert(vef.forwarded_vef_formats==1 && !vef.forwarded_bb_formats && vef.forwarded_format_handle==lease.handle);
    assert(!memcmp(vef.format.current,before.format.current,8) && !memcmp(vef.format.current+8,packet+64,4) && !memcmp(vef.format.current+12,packet+72,8));
    assert(!memcmp(vef.format.expected,before.format.expected,16) && vef.format.forwarded_vef_payload_fnv==forward_hash(packet+64,16) && !vef.format.forwarded_bb_payload_fnv);
    assert(vef.format.current_fnv==forward_hash(vef.format.current,20));
    forward_history(&before);forward_unchanged(&vef,reads);
    assert(full_infrabb_vef_connection_accept_forwarded_vef_format(lease.handle,&forward_io)==-1021);forward_unchanged(&vef,reads);
    if(!strcmp(name,"wrong-handle")){
        struct pin_control_lease other=forward_allocate(packet);changed=91;
        assert(full_infrabb_vef_connection_accept_forwarded_bb_format(other.handle,&forward_io,&changed)==-1021 && !changed);
        forward_unchanged(&vef,reads);assert(!pin_control_release_consumer(other.handle));
    }
    if(!strcmp(name,"changed-after-vef")){
        for(unsigned int i=0;i<80;i++){
            if(i>=64 && i!=65 && i!=67 && (i<68 || i>=72))continue;
            actual[i]^=i==65?3:1;changed=91;
            assert(full_infrabb_vef_connection_accept_forwarded_bb_format(lease.handle,&forward_io,&changed)==-1021 && !changed);
            actual[i]^=i==65?3:1;forward_unchanged(&vef,++reads);
        }
    }
    assert(!full_infrabb_vef_connection_accept_forwarded_bb_format(lease.handle,&forward_io,&changed));reads++;
    assert(changed==(strcmp(name,"same")!=0));
    struct full_infrabb_vef_connection_snapshot bb=iv_snapshot();
    assert(bb.forwarded_bb_formats==1 && bb.forwarded_vef_formats==1 && bb.format.forwarded_bb_payload_fnv==bb.format.forwarded_vef_payload_fnv);
    assert(!memcmp(bb.format.expected,packet+64,16));forward_history(&before);forward_unchanged(&bb,reads);
    assert(full_infrabb_vef_connection_accept_forwarded_bb_format(lease.handle,&forward_io,&changed)==-1021 && !changed);forward_unchanged(&bb,reads);
    assert(!pin_control_references(lease.handle,&refs_after) && !memcmp(&refs_before,&refs_after,sizeof refs_before));
    assert(forward_logs==2);assert(!pin_control_release_consumer(lease.handle));
    pin_control_snapshot(&pool);assert(!pool.live && pool.allocations==pool.releases && !pool.faults);
    puts("INFRABB_VEF_FORWARD_HOST_TEST_PASS");return 0;
}
