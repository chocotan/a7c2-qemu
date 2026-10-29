/* SPDX-License-Identifier: MIT */
#include "udate-distribution.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#define SID NATIVE_UDATE_DISTRIBUTION_SID
#define DEST NATIVE_UDATE_DISTRIBUTION_TARGET1_SID
struct mock {
    unsigned char original[44],query[44],response[44],done[44];
    unsigned int original_source,original_size,response_size,query_source,done_source;
    unsigned int query_destination,done_destination,response_destination;
    unsigned int allocate_ids[2],original_release_id,query_release_id,response_release_id,done_release_id;
    int original_freed,query_freed,response_freed,done_freed;
    int original_release_calls,done_sent,done_reason,query_type;
    int dynamic_create,dynamic_create_rc,dynamic_owner,queue_freed,queue_free_rc;
    int sync_calls,sync_fail_at,receive_calls,receive_rc;
    int send_calls,send_fail_type,original_release_rc;
    int alloc_calls,alloc_fail_at;
    int invalid_response_status,response_free_rc,response_ready;
    int nested_busy,nested_rejected,last_result,last_handled;
    void *short_message;
};
static struct mock *current;
static void put16(unsigned char *p,unsigned int v){p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);}
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned int u32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static unsigned int u16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static void call(struct mock *,unsigned int);
static void init_mock(struct mock *m) {
    memset(m,0,sizeof *m);current=m;
    m->original_source=SID;m->original_size=44;m->response_size=44;
    put32(m->original,1);put16(m->original+0x28,1);
    put32(m->response,2);put16(m->response+0x10,2026);m->response[0x12]=10;m->response[0x13]=25;
    m->response[0x14]=12;m->response[0x15]=34;m->response[0x16]=56;
    put16(m->response+0x20,(unsigned short)-60);put16(m->response+0x22,0);
}
static void setup(struct mock *m) { native_udate_test_reset();init_mock(m); }
static int io_allocate(unsigned int id,void **out,unsigned int size,unsigned int count) {
    (void)id;(void)count;struct mock *m=current;
    m->alloc_calls++;
    if (m->alloc_calls<=2) m->allocate_ids[m->alloc_calls-1]=id;
    if (m->alloc_fail_at==m->alloc_calls) { *out=NULL;return -12; }
    if (size!=44) { *out=NULL;return -13; }
    *out=m->alloc_calls==1?m->query:m->done;return 0;
}
static int io_release(unsigned int id,void *message) {
    (void)id;struct mock *m=current;
    if (message==m->original) {
        m->original_release_id=id;m->original_release_calls++;
        if (m->original_release_calls==1 && m->original_release_rc) return m->original_release_rc;
        if (m->original_freed) return -99;
        m->original_freed=1;return 0;
    }
    if (message==m->query) {
        m->query_release_id=id;
        if (m->query_freed) return -99;
        m->query_freed=1;return 0;
    }
    if (message==m->done) {
        m->done_release_id=id;
        if (m->done_freed) return -99;
        m->done_freed=1;return 0;
    }
    if (message==m->response) {
        m->response_release_id=id;
        if (m->response_free_rc) return m->response_free_rc;
        if (m->response_freed) return -99;
        m->response_freed=1;return 0;
    }
    return -98;
}
static void io_set_source(void *message,unsigned int source) {
    if (message==current->query) current->query_source=source;
    else if (message==current->done) current->done_source=source;
    else assert(0);
}
static int io_send(unsigned int id,void *message) {
    struct mock *m=current;m->send_calls++;
    if (message==m->query) {
        m->query_destination=id;m->query_type=(int)u32(m->query);
        assert(id==SID && m->query_source==SID);
        if (m->send_fail_type==2) return -55;
        m->response_destination=u32(m->query+0x0c);
        memcpy(m->response+0x0c,m->query+0x0c,4); /* original reply wrapper copies the body */
        m->query_freed=1;m->response_ready=1;return 0;
    }
    if (message==m->done) {
        m->done_destination=id;assert(id==SID);
        if (m->send_fail_type==4) return -66;
        m->done_sent=1;m->done_reason=(int)u16(m->done+0x28);m->done_freed=1;return 0;
    }
    return -97;
}
static unsigned int io_size(void *message) {
    if (message==current->original || message==current->short_message) return current->original_size;
    if (message==current->response) return current->response_size;
    return 44;
}
static unsigned int io_source(void *message) {
    if (message==current->original || message==current->short_message) return current->original_source;
    if (message==current->query) return current->query_source;
    if (message==current->done) return current->done_source;
    return SID;
}
static void io_record(const char *tag,const char *line) {(void)tag;(void)line;}
static int io_dynamic(unsigned int type,unsigned int owner,unsigned long value) {
    struct mock *m=current;
    if (type==0x2a) {
        m->dynamic_create++;m->dynamic_owner=(int)owner;
        if (m->dynamic_create_rc) return m->dynamic_create_rc;
        *(unsigned int *)value=0x90000123U;return 0;
    }
    if (type==0x4a) { if (m->queue_free_rc) return m->queue_free_rc;m->queue_freed++;return 0; }
    return -96;
}
static int io_receive(unsigned int id,void **out,long timeout) {
    (void)timeout;struct mock *m=current;m->receive_calls++;
    if (m->nested_busy) {
        m->nested_busy=0;struct mock other;init_mock(&other);call(&other,DEST);
        if (other.last_handled==1 && other.last_result<0 && !other.done_sent) m->nested_rejected=1;
        current=m;
    }
    if (m->receive_rc) return m->receive_rc;
    if (!m->response_ready || id!=m->response_destination) return -55;
    *out=m->response;return 0;
}
static int io_sync(unsigned int id,void *message) {
    (void)id;struct mock *m=current;m->sync_calls++;
    if (m->sync_fail_at==m->sync_calls) return -33;
    unsigned char *p=message;unsigned long long timer=m->sync_calls==1?1000:1600;
    for (unsigned int i=0;i<8;i++) p[0x18+i]=(unsigned char)(timer>>(8*i));
    return 0;
}
static struct native_udate_io ops={
    io_allocate,io_release,io_set_source,io_send,io_size,io_source,io_record,
    io_dynamic,io_receive,io_sync
};
static void call(struct mock *m,unsigned int destination) {
    current=m;
    m->last_handled=native_udate_distribution_dispatch(destination,m->original,&ops,1,&m->last_result);
}
static void check_normal(void) {
    struct mock m;setup(&m);call(&m,DEST);
    assert(m.last_handled==1 && m.last_result==0);
    assert(m.done_sent && m.done_reason==1 && m.done_source==DEST);
    assert(m.original_freed && m.query_freed && m.done_freed && m.response_freed);
    assert(m.query_type==2 && m.query_source==SID && m.done_destination==SID &&
           m.query_destination==SID && m.response_destination==(0x90000123U|0x80000000U) &&
           u32(m.query+0x0c)==(0x90000123U|0x80000000U) &&
           u32(m.response+0x0c)==(0x90000123U|0x80000000U));
    assert(m.dynamic_create==1 && m.dynamic_owner==0x90 && m.queue_freed==1 &&
           m.sync_calls==2 && m.receive_calls==1);
    assert(m.allocate_ids[0]==SID && m.allocate_ids[1]==SID && m.original_release_id==DEST &&
           m.response_release_id==(0x90000123U|0x80000000U));
    struct native_udate_snapshot s;native_udate_test_snapshot(&s);
    assert(s.valid && s.done_sent && s.generation==1 && s.elapsed==300 && !s.faults && !s.busy && !s.retained);
    assert(u16(s.date)==2026 && s.date[2]==10 && s.date[3]==25 && (short)u16(s.timezone)==-60);
}
static void check_unsupported(void) {
    struct mock m;setup(&m);call(&m,SID);assert(!m.last_handled && !m.send_calls);
    setup(&m);m.original_source=DEST;call(&m,DEST);assert(!m.last_handled && !m.send_calls);
    setup(&m);put32(m.original,2);call(&m,DEST);assert(!m.last_handled && !m.send_calls);
    setup(&m);put16(m.original+0x28,4);call(&m,DEST);assert(!m.last_handled && !m.send_calls);
    setup(&m);m.original_size=40;call(&m,DEST);assert(!m.last_handled && !m.send_calls);
    setup(&m);put32(m.original+8,1);put32(m.original+0x0c,0x90000123U);call(&m,DEST);
    assert(!m.last_handled && !m.send_calls && !m.dynamic_create && !m.original_freed);
    setup(&m);unsigned char *tiny=malloc(1);assert(tiny);m.short_message=tiny;m.original_size=1;
    int result=-1;assert(native_udate_distribution_dispatch(DEST,tiny,&ops,1,&result)==0 && result==-1);
    free(tiny);m.short_message=NULL;
}
static void check_failure(int which) {
    struct mock m;setup(&m);
    switch(which) {
    case 1:m.sync_fail_at=1;break;
    case 2:m.dynamic_create_rc=-21;break;
    case 3:m.alloc_fail_at=1;break;
    case 4:m.send_fail_type=2;break;
    case 5:m.receive_rc=-55;break;
    case 6:put16(m.response+4,(unsigned short)-7);break;
    case 7:m.response[0x12]=13;break;
    case 8:put16(m.response+0x20,2000);break;
    case 9:m.response_size=40;break;
    case 10:m.response_free_rc=-88;break;
    case 11:m.queue_free_rc=-44;break;
    case 12:m.sync_fail_at=2;break;
    case 13:m.alloc_fail_at=2;break;
    case 14:m.send_fail_type=4;break;
    case 15:put32(m.response+4,0x00010000);break; /* high half must not be accepted as zero */
    default:assert(0);
    }
    call(&m,DEST);
    assert(m.last_handled==1 && m.last_result<0 && !m.done_sent && !m.original_freed);
    struct native_udate_snapshot s;native_udate_test_snapshot(&s);assert(s.faults && !s.done_sent && !s.busy);
    if (which==4) assert(m.query_release_id==SID);
    if (which==14) assert(m.done_release_id==SID);
    if (which==5) assert(!m.queue_freed);
    if (which==10) {
        assert(m.response_release_id==(0x90000123U|0x80000000U));
        assert(m.queue_freed==1);m.response_free_rc=0;int rc=0;
        assert(native_udate_distribution_release(0x90000123U|0x80000000U,m.response,io_release,io_record,&rc)==1);
        assert(rc==0 && m.response_freed);
        assert(native_udate_distribution_release(0x90000123U|0x80000000U,m.response,
            io_release,io_record,&rc)==0); /* successful retry removes retained ownership */
    }
}
static void check_original_retry(void) {
    struct mock m;setup(&m);m.original_release_rc=-77;call(&m,DEST);
    assert(m.last_handled==1 && m.last_result==0 && m.done_sent && !m.original_freed);
    struct native_udate_snapshot s;native_udate_test_snapshot(&s);assert(s.retained && s.faults);
    int rc=0;
    assert(native_udate_distribution_release(SID,m.original,io_release,io_record,&rc)==1 && rc<0);
    assert(native_udate_distribution_release(DEST,m.original,io_release,io_record,&rc)==1 && rc==0 && m.original_freed);
    m.send_calls=0;call(&m,DEST);assert(m.last_handled==1 && m.last_result<0 && !m.send_calls);
}
static void check_busy(void) {
    struct mock m;setup(&m);m.nested_busy=1;call(&m,DEST);
    assert(m.last_result==0 && m.done_sent && m.nested_rejected);
}
static void check_fork(void) {
    struct mock m;setup(&m);call(&m,DEST);assert(m.last_result==0);
    pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        struct mock child;memcpy(&child,&m,sizeof child);
        child.done_sent=0;child.send_calls=0;call(&child,DEST);
        _exit(child.last_handled==1 && child.last_result<0 && !child.send_calls?0:1);
    }
    int status=0;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
}
static void check_fork_release(void) {
    struct mock m;setup(&m);m.original_release_rc=-77;call(&m,DEST);
    assert(m.last_result==0 && !m.original_freed);
    native_udate_test_lock_state(); /* emulate a fork while another thread owns the mutex */
    pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        int rc=0;
        int handled=native_udate_distribution_release(DEST,m.original,io_release,io_record,&rc);
        _exit(handled==1 && rc==-1021?0:1);
    }
    int status=0;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
    native_udate_test_unlock_state();
}
int main(int argc,char **argv) {
    assert(argc==2);const char *name=argv[1];
    if (!strcmp(name,"normal")) check_normal();
    else if (!strcmp(name,"unsupported")) check_unsupported();
    else if (!strcmp(name,"original-retry")) check_original_retry();
    else if (!strcmp(name,"busy")) check_busy();
    else if (!strcmp(name,"fork")) check_fork();
    else if (!strcmp(name,"fork-release")) check_fork_release();
    else { int which=atoi(name);assert(which>=1 && which<=15);check_failure(which); }
    return 0;
}
