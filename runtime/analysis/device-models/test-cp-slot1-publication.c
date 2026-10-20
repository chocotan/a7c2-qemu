/* SPDX-License-Identifier: MIT */
#include "cp-slot1-publication.h"
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

struct fixture {
    struct cp_slot1_publication *model;
    unsigned char banks[2*CP_SLOT1_BANK_BYTES], root[CP_SLOT1_ROOT_BYTES];
    unsigned char record[CP_SLOT1_RECORD_BYTES], expected[CP_SLOT1_SNAPSHOT_BYTES];
    unsigned int prefix_calls, post_calls;
    int prefix_error, post_error, pause;
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    int arrived, release;
};
static struct cp_slot1_view view(struct fixture *f) {
    struct cp_slot1_view v;assert(!cp_slot1_snapshot(f->model,&v));return v;
}
static void init(struct fixture *f) {
    memset(f,0,sizeof *f);
    for (unsigned int i=0;i<sizeof f->banks;i++) f->banks[i]=(unsigned char)(i*17+23);
    memset(f->root,0x9a,sizeof f->root);f->root[8]=1;f->root[9]=2;
    memset(f->record,0x5b,sizeof f->record);
    memcpy(f->expected,f->root,sizeof f->root);
    memcpy(f->expected+sizeof f->root,f->record,sizeof f->record);
    f->model=cp_slot1_create(3,f->banks);assert(f->model);
    assert(!pthread_mutex_init(&f->mutex,NULL));assert(!pthread_cond_init(&f->condition,NULL));
}
static int enqueue(struct fixture *f) {
    return cp_slot1_enqueue(f->model,f->root,sizeof f->root,f->record,sizeof f->record);
}
static void done(struct fixture *f) {
    assert(!cp_slot1_destroy(f->model));
    assert(!pthread_cond_destroy(&f->condition));assert(!pthread_mutex_destroy(&f->mutex));
}
static void check_banks(struct fixture *f,int published) {
    unsigned char actual[sizeof f->banks];assert(!cp_slot1_read_banks(f->model,actual,sizeof actual));
    struct cp_slot1_view v=view(f);
    for (unsigned int i=0;i<sizeof actual;i++) {
        unsigned int at=v.selector*CP_SLOT1_BANK_BYTES+0x14;
        unsigned int expected=published && i==at?1:published && i==at+1?2:f->banks[i];
        assert(actual[i]==expected);
    }
}
static int prefix(void *arg,const unsigned char *snapshot,size_t size) {
    struct fixture *f=arg;f->prefix_calls++;
    assert(size==sizeof f->expected && !memcmp(snapshot,f->expected,size));
    struct cp_slot1_view v=view(f);assert(v.busy && v.stage==CP_SLOT1_EXECUTING);
    assert(cp_slot1_abort(f->model)==-EBUSY);
    assert(cp_slot1_destroy(f->model)==-EBUSY);
    assert(enqueue(f)==-EBUSY);
    if (f->pause) {
        assert(!pthread_mutex_lock(&f->mutex));f->arrived=1;
        assert(!pthread_cond_signal(&f->condition));
        while (!f->release) assert(!pthread_cond_wait(&f->condition,&f->mutex));
        assert(!pthread_mutex_unlock(&f->mutex));
    }
    return f->prefix_error;
}
static int postwork(void *arg,const unsigned char *snapshot,size_t size) {
    struct fixture *f=arg;f->post_calls++;
    assert(size==sizeof f->expected && !memcmp(snapshot,f->expected,size));
    struct cp_slot1_view v=view(f);
    assert(v.busy && v.bank_work[v.selector]==v.work && v.completed_work!=v.work);
    assert(!v.observation_current);
    return f->post_error;
}
static const struct cp_slot1_effects effects={prefix,postwork};
static void normal(void) {
    struct fixture f;init(&f);assert(!enqueue(&f));
    /* Queue acceptance is distinct from publication; all source bytes owned. */
    memset(f.root,0,sizeof f.root);memset(f.record,0,sizeof f.record);
    check_banks(&f,0);assert(view(&f).busy && !view(&f).observation_current);
    assert(!cp_slot1_execute(f.model,&effects,&f));
    check_banks(&f,1);assert(view(&f).selector==1 && view(&f).alias==0);
    assert(view(&f).callbacks==1 && !view(&f).observation_current);
    assert(!cp_slot1_refresh(f.model,0,1));assert(view(&f).alias==0);
    assert(!cp_slot1_refresh(f.model,1,0));
    assert(view(&f).observed==0x201 && view(&f).observation_current);
    /* Preserve both banks when publishing the repeated same request. */
    assert(!cp_slot1_read_banks(f.model,f.banks,sizeof f.banks));
    memcpy(f.root,f.expected,sizeof f.root);memcpy(f.record,f.expected+sizeof f.root,sizeof f.record);
    assert(!enqueue(&f));assert(view(&f).observed==0x201 && !view(&f).observation_current);
    assert(!cp_slot1_execute(f.model,&effects,&f));check_banks(&f,1);
    assert(view(&f).selector==0 && view(&f).alias==1 && !view(&f).observation_current);
    assert(!cp_slot1_refresh(f.model,1,0));assert(view(&f).observation_current);
    assert(f.prefix_calls==2 && f.post_calls==2 && view(&f).callbacks==2);done(&f);
}
static void failures(const char *which) {
    struct fixture f;init(&f);assert(!enqueue(&f));
    if (!strcmp(which,"missing-effects")) {
        assert(cp_slot1_execute(f.model,NULL,&f)==-ENOTSUP);
        struct cp_slot1_effects partial={prefix,NULL};
        assert(cp_slot1_execute(f.model,&partial,&f)==-ENOTSUP);
        assert(!f.prefix_calls && !f.post_calls);check_banks(&f,0);
    } else {
        int is_prefix=!strcmp(which,"prefix-failure");
        f.prefix_error=is_prefix?-EIO:0;f.post_error=is_prefix?0:-ENOTSUP;
        assert(cp_slot1_execute(f.model,&effects,&f)==(is_prefix?-EIO:-ENOTSUP));
        assert(view(&f).stage==(is_prefix?CP_SLOT1_BLOCKED_PREFIX:CP_SLOT1_BLOCKED_POST));
        assert(cp_slot1_execute(f.model,&effects,&f)==-ENOENT);
        assert(f.prefix_calls==1 && f.post_calls==(unsigned int)!is_prefix);
        check_banks(&f,!is_prefix);
        /* Primary refresh may expose bytes even while busy; not full effects. */
        assert(!cp_slot1_refresh(f.model,1,1));assert(!view(&f).observation_current);
    }
    assert(view(&f).busy && !view(&f).callbacks);
    assert(!cp_slot1_abort(f.model));assert(view(&f).callbacks==1);
    assert(!cp_slot1_refresh(f.model,1,0));assert(!view(&f).observation_current);
    assert(cp_slot1_abort(f.model)==-ENOENT);done(&f);
}
static void invalid(void) {
    struct fixture f;init(&f);
    assert(!cp_slot1_create(3,NULL));assert(!cp_slot1_create(1,f.banks));
    assert(cp_slot1_enqueue(f.model,f.root,2,f.record,sizeof f.record)==-EINVAL);
    f.root[9]=3;assert(enqueue(&f)==-ENOTSUP);f.root[9]=2;
    assert(!cp_slot1_set_input_mode(f.model,0));assert(enqueue(&f)==-ENOTSUP);
    assert(view(&f).derived_mode==1 && !view(&f).busy);
    assert(!cp_slot1_set_input_mode(f.model,2));assert(enqueue(&f)==-ENOTSUP);
    assert(view(&f).derived_mode==0); /* M0 alone is not supported-I admission. */
    assert(!cp_slot1_set_input_mode(f.model,3));assert(!enqueue(&f));
    assert(cp_slot1_set_input_mode(f.model,1)==-EBUSY);
    assert(!cp_slot1_abort(f.model));done(&f);
}
static void child(void) {
    struct fixture f;init(&f);assert(!enqueue(&f));pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        struct cp_slot1_view v;assert(cp_slot1_snapshot(f.model,&v)==-ECHILD);
        assert(cp_slot1_destroy(f.model)==-ECHILD);assert(cp_slot1_abort(f.model)==-ECHILD);_exit(0);
    }
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
    assert(!cp_slot1_execute(f.model,&effects,&f));done(&f);
}
static void *worker(void *arg) {
    struct fixture *f=arg;assert(!cp_slot1_execute(f->model,&effects,f));return NULL;
}
static void concurrent(void) {
    struct fixture f;init(&f);f.pause=1;assert(!enqueue(&f));pthread_t thread;
    assert(!pthread_create(&thread,NULL,worker,&f));assert(!pthread_mutex_lock(&f.mutex));
    while (!f.arrived) assert(!pthread_cond_wait(&f.condition,&f.mutex));
    assert(view(&f).stage==CP_SLOT1_EXECUTING);
    assert(cp_slot1_abort(f.model)==-EBUSY && cp_slot1_destroy(f.model)==-EBUSY);
    assert(cp_slot1_execute(f.model,&effects,&f)==-ENOENT);
    assert(!cp_slot1_refresh(f.model,1,0));check_banks(&f,0);
    f.release=1;assert(!pthread_cond_signal(&f.condition));assert(!pthread_mutex_unlock(&f.mutex));
    assert(!pthread_join(thread,NULL));assert(view(&f).callbacks==1);done(&f);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"normal")) normal();
    else if (!strcmp(argv[1],"invalid")) invalid();
    else if (!strcmp(argv[1],"fork")) child();
    else if (!strcmp(argv[1],"concurrent")) concurrent();
    else failures(argv[1]);
    puts("SLOT1_FINITE_PUBLICATION_PASS");return 0;
}
