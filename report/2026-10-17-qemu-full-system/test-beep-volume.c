/* SPDX-License-Identifier: MIT */
/* Host-only contract/ownership test; link test-sound-path-stubs.c, not the
 * AArch64 system-sound-owner.c. No sound playback is claimed. */
#include "audio-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct message { unsigned int owner, source, bytes; unsigned char data[]; };
static void *live[32], *queued;
static int allocation_failure, send_failure;
static unsigned int allocations, request_frees, reply_frees, beep_logs;
static char beep_line[600];
static const unsigned int D=0x81cf61c2;

static struct message *header(void *p) {
    return (struct message *)((char *)p - offsetof(struct message,data));
}
static int is_live(void *p) {
    for (unsigned int i=0;i<32;i++) if (live[i]==p) return 1;
    return 0;
}
static int allocate(unsigned int id,void **out,unsigned int n,unsigned int wait) {
    assert(wait==1);allocations++;
    if (allocation_failure==1) { *out=0;return -55; }
    struct message *m=calloc(1,sizeof *m+n);assert(m);
    m->owner=id;m->bytes=n;*out=m->data;
    for (unsigned int i=0;i<32;i++) if (!live[i]) {
        live[i]=*out;return allocation_failure==2?-55:0;
    }
    abort();
}
static int release(unsigned int id,void *p) {
    assert(p && is_live(p) && header(p)->owner==id);
    for (unsigned int i=0;i<32;i++) if (live[i]==p) {
        live[i]=0;
        if (id==FULL_AUDIO_INPUT) request_frees++;else reply_frees++;
        memset(p,0xde,header(p)->bytes);free(header(p));return 0;
    }
    abort();
}
static unsigned int size(void *p) { return header(p)->bytes; }
static unsigned int source(void *p) { return header(p)->source; }
static void set_source(void *p,unsigned int id) { header(p)->source=id; }
static int send(unsigned int id,void *p) {
    assert(is_live(p) && header(p)->owner==id && !queued);
    if (send_failure) return -77;
    queued=p;return 0;
}
static void record(const char *kind,const char *line) {
    if (!strcmp(kind,"FULL_AUDIO_BEEP_VOLUME ")) {
        beep_logs++;snprintf(beep_line,sizeof beep_line,"%s",line);
    }
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,record};
static struct full_audio_snapshot snapshot(void) {
    struct full_audio_snapshot s;full_audio_snapshot(&s);return s;
}
static unsigned char *request(unsigned int volume,unsigned int bytes,unsigned int declared) {
    static const unsigned char envelope[]={0x0d,0x20,0x47,0x03,0x0a,0,1,0x80};
    void *p=0;assert(!allocate(FULL_AUDIO_INPUT,&p,bytes,1));
    unsigned char *r=p;memcpy(r,envelope,sizeof envelope);
    r[4]=(unsigned char)declared;r[8]=(unsigned char)volume;set_source(r,D);return r;
}
static void reset(void) {
    for (unsigned int i=0;i<32;i++) assert(!live[i]);
    assert(!queued);full_audio_test_reset();
    allocation_failure=send_failure=0;
    allocations=request_frees=reply_frees=beep_logs=0;beep_line[0]=0;
}
static void finish(unsigned int status,int print) {
    static const unsigned char success[]={0x0d,0x20,0x47,0x13,0x0c,0,1,0x80,0,0,0x58,0};
    static const unsigned char rejected[]={0x0d,0x20,0x47,0x13,0x0c,0,1,0x80,2,0xe0,0x58,0};
    const unsigned char *expected=status?rejected:success;
    assert(queued && is_live(queued) && size(queued)==sizeof success);
    assert(source(queued)==FULL_AUDIO_INPUT);
    assert(!memcmp(queued,expected,sizeof success));
    if (print) {
        const unsigned char *actual=queued;
        printf("BEEP_VOLUME_%s actual=",status?"E002":"SUCCESS");
        for (unsigned int i=0;i<sizeof success;i++) printf("%02x",actual[i]);
        printf(" expected=");
        for (unsigned int i=0;i<sizeof success;i++) printf("%02x",expected[i]);
        puts(" PASS");
    }
    int rc=123;assert(full_audio_release_reply(D,queued,release,record,&rc) && !rc);queued=0;
}
static void check_log(unsigned int volume,int rejected) {
    char expected[120];
    snprintf(expected,sizeof expected,"command=0x347 beep_volume=%u applied=%u rejected=%u",
             volume,(unsigned int)!rejected,(unsigned int)rejected);
    assert(strstr(beep_line,expected));
    assert(strstr(beep_line,"audio_output_verified=0 camera_startup_verified=0"));
}

int main(void) {
    reset();int rc=123;
    static const unsigned int values[]={1,2,3,4,5,9,0xfd};
    for (unsigned int i=0;i<sizeof values/sizeof values[0];i++) {
        unsigned char *r=request(values[i],10,10);
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,r,&io,FULL_AUDIO_BOOT,&rc) && !rc);
        assert(request_frees==i+1);finish(0,i==0);
        struct full_audio_snapshot s=snapshot();
        assert(s.beep_volume==(values[i]&7u) && s.beep_applied==1);
        assert(s.beep_applied_count==i+1 && !s.beep_rejected);
        assert(beep_logs==i+1);check_log(values[i]&7u,0);
    }
    const struct full_audio_snapshot applied=snapshot();
    static const unsigned int invalid[]={0,6,7,8,0xff};
    for (unsigned int i=0;i<sizeof invalid/sizeof invalid[0];i++) {
        unsigned char *r=request(invalid[i],10,10);
        unsigned int freed=request_frees,logs=beep_logs;
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,r,&io,FULL_AUDIO_BOOT,&rc) && !rc);
        assert(request_frees==freed+1);finish(0xe002,i==0);
        struct full_audio_snapshot s=snapshot();
        assert(s.beep_volume==applied.beep_volume && s.beep_applied==applied.beep_applied);
        assert(s.beep_applied_count==applied.beep_applied_count && s.beep_rejected==i+1);
        assert(beep_logs==logs+1);check_log(applied.beep_volume,1);
    }
    puts("BEEP_VOLUME_APPLY_READBACK_MASK_REJECT_AND_LOG_PASS");

    /* Both actual and declared lengths fail without transferring ownership. */
    reset();
    for (unsigned int i=0;i<3;i++) {
        unsigned char *r=request(4,i==0?9:i==1?12:10,i==2?12:10);
        unsigned int allocated=allocations;
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,r,&io,FULL_AUDIO_BOOT,&rc) && rc==-1021);
        assert(is_live(r) && !queued && !request_frees && !reply_frees && !beep_logs);
        assert(allocations==allocated && !snapshot().beep_applied_count);
        assert(!release(FULL_AUDIO_INPUT,r));request_frees=0;
    }
    /* The volume-only profile must leave this boot command to the caller. */
    unsigned char *r=request(4,10,10);rc=123;
    assert(!full_audio_dispatch(FULL_AUDIO_INPUT,r,&io,FULL_AUDIO_VOLUME,&rc) && rc==123);
    assert(is_live(r) && !queued);assert(!release(FULL_AUDIO_INPUT,r));
    puts("BEEP_VOLUME_LENGTH_AND_PROFILE_CALLER_OWNERSHIP_PASS");

    /* Preserve an existing setting and all snapshot counters on transport failure. */
    reset();r=request(3,10,10);
    assert(full_audio_dispatch(FULL_AUDIO_INPUT,r,&io,FULL_AUDIO_BOOT,&rc) && !rc);finish(0,0);
    for (unsigned int failure=0;failure<4;failure++) {
        r=request(failure==3?0:5,10,10);
        struct full_audio_snapshot before=snapshot();
        unsigned int freed=request_frees,replies_freed=reply_frees,logs=beep_logs;
        allocation_failure=failure<2?(int)failure+1:0;send_failure=failure>=2;
        assert(full_audio_dispatch(FULL_AUDIO_INPUT,r,&io,FULL_AUDIO_BOOT,&rc));
        assert(rc==(failure<2?-55:-77));
        struct full_audio_snapshot after=snapshot();
        assert(!memcmp(&before,&after,sizeof before));
        assert(is_live(r) && !queued && request_frees==freed && beep_logs==logs);
        assert(reply_frees==replies_freed+(failure!=0));
        allocation_failure=send_failure=0;assert(!release(FULL_AUDIO_INPUT,r));
    }
    puts("BEEP_VOLUME_ALLOCATION_SEND_ROLLBACK_AND_CALLER_OWNERSHIP_PASS");
    reset();puts("BEEP_VOLUME_ALL_PASS");return 0;
}
