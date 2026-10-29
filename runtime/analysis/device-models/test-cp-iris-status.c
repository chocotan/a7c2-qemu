/* SPDX-License-Identifier: MIT */
/* Include the implementation only for private counter-exhaustion and locked
 * fork fixtures. Python separately compiles/checks the production object's API.
 * Every supplied source below is a HOST fixture, never a real iris producer. */
#include "cp-iris-status.c"
#include <assert.h>
#include <stdio.h>
#include <sys/wait.h>

static int fail_create;
void *__real_calloc(size_t,size_t);
int __real_pthread_mutex_init(pthread_mutex_t *,const pthread_mutexattr_t *);
void *__wrap_calloc(size_t n,size_t size) {
    if (fail_create==1) { errno=ENOMEM;return NULL; }
    return __real_calloc(n,size);
}
int __wrap_pthread_mutex_init(pthread_mutex_t *mutex,const pthread_mutexattr_t *attr) {
    return fail_create==2?ENOMEM:__real_pthread_mutex_init(mutex,attr);
}
static void all(const unsigned char *p,size_t n,unsigned char value) {
    for (size_t i=0;i<n;i++) assert(p[i]==value);
}
static struct cp_iris_status *create(uint32_t profile) {
    unsigned char h0[CP_IRIS_BANK_BYTES],known[CP_IRIS_BANK_BYTES];
    memset(h0,0xa5,sizeof h0);memset(known,0,sizeof known);
    struct cp_iris_status *s=cp_iris_status_create(profile,1,h0,sizeof h0,known,sizeof known);
    assert(s);return s;
}
static struct cp_iris_status_view snap(struct cp_iris_status *s) {
    struct cp_iris_status_view v={0};assert(!cp_iris_status_snapshot(s,&v));
    assert(v.profile_known==1 && v.current_index<3);
    assert(!v.original_producer_verified && !v.source_runtime_verified);
    assert(!v.original_atomicity_verified && !v.capture_verified);
    assert(v.constructor_zero_writes==8 && v.constructor_copy_bytes==2624);
    assert(v.source_copy_count<=1 && v.generation==v.copies-1);
    assert(v.sequence==v.index_publications+v.copies);
    assert(v.last_copy_sequence<=v.sequence && v.last_index_publication_sequence<=v.sequence);
    for (size_t bank=0;bank<3;bank++) {
        size_t count=0;
        for (size_t i=0;i<CP_IRIS_BANK_BYTES;i++) {
            assert(v.known[bank][i]<=1);count+=v.known[bank][i];
        }
        assert(v.known_bytes[bank]==count);
    }
    return v;
}
static void unchanged(struct cp_iris_status *s,const struct cp_iris_status_view *before) {
    struct cp_iris_status_view after={0};assert(!cp_iris_status_snapshot(s,&after));
    assert(!memcmp(&after,before,sizeof after));
}
static void sample(struct cp_iris_status *s,unsigned char expected) {
    unsigned char value=0xe9;assert(!cp_iris_sample_init_complete(s,&value));
    assert(value==expected);
}
static void host_source(struct cp_iris_status *s,unsigned char value) {
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,value,sizeof p);memset(k,1,sizeof k);
    assert(!cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k));
    all(p,sizeof p,value);all(k,sizeof k,1);
}
static void constructor(void) {
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,0xa5,sizeof p);memset(k,0,sizeof k);
    for (size_t pass=0;pass<2;pass++) {
        if (pass) for (size_t i=8;i<sizeof k;i++) k[i]=(unsigned char)(i%2);
        struct cp_iris_status *s=cp_iris_status_create(2,1,p,sizeof p,k,sizeof k);assert(s);
        struct cp_iris_status_view v=snap(s);
        assert(v.current_index==0 && v.generation==1 && v.copies==2);
        assert(v.index_publications==1 && !v.source_copy_count && v.sequence==3);
        assert(v.last_copy_sequence==2 && v.last_index_publication_sequence==3);
        for (size_t bank=0;bank<3;bank++) {
            all(v.banks[bank],8,0);all(v.known[bank],8,1);
            all(v.banks[bank]+8,CP_IRIS_BANK_BYTES-8,0xa5);
            assert(!memcmp(v.known[bank]+8,k+8,CP_IRIS_BANK_BYTES-8));
            if (!pass) assert(v.known_bytes[bank]==8);
        }
        all(p,sizeof p,0xa5);sample(s,0);
        v.banks[0][2]=1;v.known[0][20]=1;v.current_index=2;v.original_producer_verified=1;
        sample(s,0);assert(snap(s).current_index==0 && !snap(s).original_producer_verified);
        assert(!cp_iris_status_destroy(s));
    }
    assert(CP_IRIS_BANK_BASE+CP_IRIS_BANK_BYTES==UINT32_C(0x1717a30));
    assert(CP_IRIS_BANK_BASE+2*CP_IRIS_BANK_BYTES==UINT32_C(0x1717f50));
}
static void lifecycle(void) {
    struct cp_iris_status *s=create(2);host_source(s,1);
    /* Publication copies NEW current H1 into H2; it must not copy old H0. */
    assert(!cp_iris_publish_next(s));struct cp_iris_status_view v=snap(s);
    assert(v.current_index==1);sample(s,0);all(v.banks[0],CP_IRIS_BANK_BYTES,1);
    all(v.banks[2],8,0);all(v.banks[2]+8,CP_IRIS_BANK_BYTES-8,0xa5);
    assert(v.known_bytes[2]==8 && v.last_copy_sequence==v.last_index_publication_sequence+1);
    assert(!cp_iris_publish_next(s));v=snap(s);assert(v.current_index==2);sample(s,0);
    all(v.banks[0],8,0);all(v.banks[0]+8,CP_IRIS_BANK_BYTES-8,0xa5);
    assert(!cp_iris_status_destroy(s));
    s=create(2);host_source(s,1);
    for (unsigned int step=0;step<9;step++) {
        struct cp_iris_status_view before=snap(s);unsigned int index=99;
        assert(!cp_iris_next_bank(s,&index) && index==(step+1)%3);unchanged(s,&before);
        assert(!cp_iris_copy_current_to_next(s));v=snap(s);
        assert(v.current_index==step%3 && v.copies==before.copies+1);
        assert(v.index_publications==before.index_publications && v.generation==before.generation+1);
        assert(!memcmp(v.banks[index],before.banks[before.current_index],CP_IRIS_BANK_BYTES));
        assert(!memcmp(v.known[index],before.known[before.current_index],CP_IRIS_BANK_BYTES));
        assert(!cp_iris_publish_next(s));v=snap(s);sample(s,1);
        assert(v.current_index==index && v.index_publications==before.index_publications+1);
        assert(v.last_copy_sequence==v.last_index_publication_sequence+1);
        unsigned int following=(index+1)%3;
        assert(!memcmp(v.banks[following],v.banks[index],CP_IRIS_BANK_BYTES));
        assert(!memcmp(v.known[following],v.known[index],CP_IRIS_BANK_BYTES));
    }
    assert(!cp_iris_status_destroy(s));
}
static void profiles(void) {
    const uint32_t profiles[]={0,1,3,UINT32_MAX};
    for (size_t i=0;i<sizeof profiles/sizeof *profiles;i++) {
        struct cp_iris_status *s=create(profiles[i]);struct cp_iris_status_view before=snap(s);
        unsigned int index=42;assert(!cp_iris_next_bank(s,&index) && index==0);
        assert(!cp_iris_copy_current_to_next(s) && !cp_iris_publish_next(s));unchanged(s,&before);
        host_source(s,0x83);sample(s,0x83);before=snap(s);
        assert(before.current_index==0 && before.profile==profiles[i]);
        assert(before.known_bytes[1]==8 && before.known_bytes[2]==8);
        assert(!cp_iris_copy_current_to_next(s) && !cp_iris_publish_next(s));unchanged(s,&before);
        assert(!cp_iris_status_destroy(s));
    }
}
static void source(void) {
    struct cp_iris_status *s=create(2);
    assert(!cp_iris_publish_next(s) && !cp_iris_publish_next(s));
    struct cp_iris_status_view before=snap(s);assert(before.current_index==2);
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    for (size_t i=0;i<sizeof p;i++) { p[i]=(unsigned char)(i*13+7);k[i]=(unsigned char)(i%5==0); }
    p[2]=1;k[2]=1;p[9]=0xd9;k[9]=0;
    assert(!cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k));
    struct cp_iris_status_view v=snap(s);sample(s,1);
    assert(v.current_index==0 && v.source_copy_count==1);
    assert(v.index_publications==before.index_publications+1 && v.copies==before.copies+1);
    assert(v.last_index_publication_sequence==before.sequence+1);
    assert(v.last_copy_sequence==before.sequence+2);
    assert(!memcmp(v.banks[0],p,sizeof p) && !memcmp(v.known[0],k,sizeof k));
    for (size_t bank=1;bank<3;bank++) {
        assert(!memcmp(v.banks[bank],before.banks[bank],sizeof p));
        assert(!memcmp(v.known[bank],before.known[bank],sizeof k));
    }
    assert(cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k)==-EALREADY);unchanged(s,&v);
    memset(p,0x99,sizeof p);memset(k,0,sizeof k);unchanged(s,&v);sample(s,1);
    assert(!cp_iris_copy_current_to_next(s));assert(!cp_iris_publish_next(s));
    struct cp_iris_status_view after=snap(s);sample(s,1);
    for (size_t bank=0;bank<3;bank++) {
        assert(!memcmp(after.banks[bank],v.banks[0],sizeof p));
        assert(!memcmp(after.known[bank],v.known[0],sizeof k));
    }
    assert(after.source_copy_count==1 && !after.original_producer_verified);
    assert(!cp_iris_status_destroy(s));
}
static void unknown(void) {
    struct cp_iris_status *s=create(2);
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,0xa5,sizeof p);memset(k,0,sizeof k);p[2]=0x59;k[4]=1;
    assert(!cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k));
    struct cp_iris_status_view v=snap(s);assert(v.known_bytes[0]==1);
    assert(!memcmp(v.banks[0],p,sizeof p) && !memcmp(v.known[0],k,sizeof k));
    for (size_t step=0;step<4;step++) {
        unsigned char value=0xee;
        assert(cp_iris_sample_init_complete(s,&value)==-ENODATA && value==0xee);
        assert(!cp_iris_copy_current_to_next(s) && !cp_iris_publish_next(s));
    }
    v=snap(s);
    for (size_t bank=0;bank<3;bank++) {
        assert(v.known_bytes[bank]==1 && v.banks[bank][2]==0x59 && !v.known[bank][2]);
        assert(!memcmp(v.banks[bank],p,sizeof p));
    }
    assert(!cp_iris_status_destroy(s));
}
static void invalid(void) {
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,1,sizeof p);memset(k,1,sizeof k);
    struct cp_iris_status *s=create(2);struct cp_iris_status_view before=snap(s);
    unsigned int index=99;unsigned char value=99;
    assert(cp_iris_status_snapshot(NULL,&before)==-EINVAL);
    assert(cp_iris_next_bank(NULL,&index)==-EINVAL && index==99);
    assert(cp_iris_sample_init_complete(NULL,&value)==-EINVAL && value==99);
    assert(cp_iris_copy_current_to_next(NULL)==-EINVAL && cp_iris_publish_next(NULL)==-EINVAL);
    assert(cp_iris_publish_initial_source(NULL,p,sizeof p,k,sizeof k)==-EINVAL);
    assert(cp_iris_status_destroy(NULL)==-EINVAL && cp_iris_status_snapshot(s,NULL)==-EINVAL);
    assert(cp_iris_next_bank(s,NULL)==-EINVAL && cp_iris_sample_init_complete(s,NULL)==-EINVAL);
    assert(!cp_iris_status_create(2,1,NULL,sizeof p,k,sizeof k) && errno==EINVAL);
    assert(!cp_iris_status_create(2,1,p,sizeof p,NULL,sizeof k) && errno==EINVAL);
    assert(cp_iris_publish_initial_source(s,NULL,sizeof p,k,sizeof k)==-EINVAL);
    assert(cp_iris_publish_initial_source(s,p,sizeof p,NULL,sizeof k)==-EINVAL);
    const size_t bad[]={0,CP_IRIS_BANK_BYTES-1,CP_IRIS_BANK_BYTES+1,SIZE_MAX};
    for (size_t i=0;i<sizeof bad/sizeof *bad;i++) {
        assert(!cp_iris_status_create(2,1,p,bad[i],k,sizeof k) && errno==EINVAL);
        assert(!cp_iris_status_create(2,1,p,sizeof p,k,bad[i]) && errno==EINVAL);
        assert(cp_iris_publish_initial_source(s,p,bad[i],k,sizeof k)==-EINVAL);
        assert(cp_iris_publish_initial_source(s,p,sizeof p,k,bad[i])==-EINVAL);
    }
    assert(!cp_iris_status_create(2,0,p,sizeof p,k,sizeof k) && errno==ENODATA);
    assert(!cp_iris_status_create(2,2,p,sizeof p,k,sizeof k) && errno==EINVAL);
    for (size_t i=0;i<sizeof k;i++) {
        k[i]=i%2?2:255;
        assert(!cp_iris_status_create(2,1,p,sizeof p,k,sizeof k) && errno==EINVAL);
        assert(cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k)==-EINVAL);k[i]=1;
    }
    unchanged(s,&before);all(p,sizeof p,1);all(k,sizeof k,1);
    assert(!cp_iris_status_destroy(s));
}
static void aliases(void) {
    struct cp_iris_status *s=create(2);struct cp_iris_status_view before=snap(s);
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,1,sizeof p);memset(k,1,sizeof k);
    assert(cp_iris_status_snapshot(s,(struct cp_iris_status_view *)(void *)s)==-EINVAL);
    assert(cp_iris_next_bank(s,(unsigned int *)(void *)s)==-EINVAL);
    assert(cp_iris_sample_init_complete(s,(unsigned char *)(void *)s)==-EINVAL);
    assert(cp_iris_publish_initial_source(s,s->view.banks[0],sizeof p,k,sizeof k)==-EINVAL);
    assert(cp_iris_publish_initial_source(s,p,sizeof p,s->view.known[0],sizeof k)==-EINVAL);
    unsigned char *wrapped=(unsigned char *)(uintptr_t)(UINTPTR_MAX-3);
    assert(!cp_iris_status_create(2,1,wrapped,sizeof p,k,sizeof k) && errno==EINVAL);
    assert(!cp_iris_status_create(2,1,p,sizeof p,wrapped,sizeof k) && errno==EINVAL);
    assert(cp_iris_publish_initial_source(s,wrapped,sizeof p,k,sizeof k)==-EINVAL);
    assert(cp_iris_publish_initial_source(s,p,sizeof p,wrapped,sizeof k)==-EINVAL);
    assert(cp_iris_next_bank(s,(unsigned int *)(uintptr_t)(UINTPTR_MAX-1))==-EINVAL);
    assert(cp_iris_status_snapshot(s,(struct cp_iris_status_view *)(void *)wrapped)==-EINVAL);
    unchanged(s,&before);
    /* Read-only source and mask may alias, just as other CP input spans do. */
    assert(!cp_iris_publish_initial_source(s,k,sizeof k,k,sizeof k));sample(s,1);
    all(snap(s).banks[0],CP_IRIS_BANK_BYTES,1);
    assert(!cp_iris_status_destroy(s));
}
static void overflow(void) {
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,1,sizeof p);memset(k,1,sizeof k);
    for (size_t field=0;field<5;field++) {
        struct cp_iris_status *s=create(2);
        if (field==0) s->view.generation=UINT64_MAX;
        if (field==1) s->view.copies=UINT64_MAX;
        if (field==2) s->view.sequence=UINT64_MAX;
        if (field==3) s->view.index_publications=UINT64_MAX;
        if (field==4) s->view.sequence=UINT64_MAX-1;
        struct cp_iris_status_view before={0};assert(!cp_iris_status_snapshot(s,&before));
        if (field<3) assert(cp_iris_copy_current_to_next(s)==-EOVERFLOW);
        assert(cp_iris_publish_next(s)==-EOVERFLOW);
        assert(cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k)==-EOVERFLOW);
        unchanged(s,&before);sample(s,0);
        if (field==4) {
            assert(!cp_iris_copy_current_to_next(s));
            struct cp_iris_status_view after={0};assert(!cp_iris_status_snapshot(s,&after));
            assert(after.sequence==UINT64_MAX && after.generation==before.generation+1);
            assert(cp_iris_copy_current_to_next(s)==-EOVERFLOW);unchanged(s,&after);
        }
        assert(!cp_iris_status_destroy(s));
    }
}
struct threads {
    struct cp_iris_status *s;
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    unsigned int waiting,go;
};
static void start(struct threads *t) {
    assert(!pthread_mutex_lock(&t->mutex));t->waiting++;
    assert(!pthread_cond_broadcast(&t->cond));
    while (!t->go) assert(!pthread_cond_wait(&t->cond,&t->mutex));
    assert(!pthread_mutex_unlock(&t->mutex));
}
static void *reader(void *arg) {
    struct threads *t=arg;start(t);
    for (size_t n=0;n<200;n++) {
        struct cp_iris_status_view v=snap(t->s);
        for (size_t bank=0;bank<3;bank++) {
            if (v.banks[bank][0]==0x7f) {
                all(v.banks[bank],CP_IRIS_BANK_BYTES,0x7f);all(v.known[bank],CP_IRIS_BANK_BYTES,1);
            } else {
                all(v.banks[bank],8,0);all(v.banks[bank]+8,CP_IRIS_BANK_BYTES-8,0xa5);
                all(v.known[bank],8,1);all(v.known[bank]+8,CP_IRIS_BANK_BYTES-8,0);
            }
        }
        unsigned char value=0xee;assert(!cp_iris_sample_init_complete(t->s,&value));
        assert(value==0 || value==0x7f);
    }
    return NULL;
}
static void *writer(void *arg) {
    struct threads *t=arg;start(t);host_source(t->s,0x7f);
    for (size_t n=0;n<200;n++) {
        assert(!cp_iris_copy_current_to_next(t->s));assert(!cp_iris_publish_next(t->s));
    }
    return NULL;
}
static void concurrent(void) {
    struct threads t={0};t.s=create(2);
    assert(!pthread_mutex_init(&t.mutex,NULL) && !pthread_cond_init(&t.cond,NULL));
    pthread_t threads[5];
    for (size_t i=0;i<5;i++) assert(!pthread_create(threads+i,NULL,i==4?writer:reader,&t));
    assert(!pthread_mutex_lock(&t.mutex));
    while (t.waiting!=5) assert(!pthread_cond_wait(&t.cond,&t.mutex));
    t.go=1;assert(!pthread_cond_broadcast(&t.cond));assert(!pthread_mutex_unlock(&t.mutex));
    for (size_t i=0;i<5;i++) assert(!pthread_join(threads[i],NULL));
    struct cp_iris_status_view v=snap(t.s);
    assert(v.copies==403 && v.index_publications==202 && v.generation==402 && v.sequence==605);
    assert(v.source_copy_count==1 && v.current_index==2);sample(t.s,0x7f);
    for (size_t bank=0;bank<3;bank++) all(v.banks[bank],CP_IRIS_BANK_BYTES,0x7f);
    assert(!cp_iris_status_destroy(t.s));
    assert(!pthread_cond_destroy(&t.cond) && !pthread_mutex_destroy(&t.mutex));
}
static void forked(void) {
    struct cp_iris_status *s=create(2);struct cp_iris_status_view before=snap(s);
    /* A held inherited private mutex proves ECHILD is checked before locking. */
    assert(!pthread_mutex_lock(&s->mutex));pid_t pid=fork();assert(pid>=0);
    if (!pid) {
        unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES],value=0xe9;
        memset(p,1,sizeof p);memset(k,1,sizeof k);unsigned int index=99;
        struct cp_iris_status_view out,saved;memset(&out,0xa5,sizeof out);memcpy(&saved,&out,sizeof out);
        assert(cp_iris_status_snapshot(s,&out)==-ECHILD && !memcmp(&out,&saved,sizeof out));
        assert(cp_iris_next_bank(s,&index)==-ECHILD && index==99);
        assert(cp_iris_sample_init_complete(s,&value)==-ECHILD && value==0xe9);
        assert(cp_iris_copy_current_to_next(s)==-ECHILD && cp_iris_publish_next(s)==-ECHILD);
        assert(cp_iris_publish_initial_source(s,p,sizeof p,k,sizeof k)==-ECHILD);
        all(p,sizeof p,1);all(k,sizeof k,1);assert(cp_iris_status_destroy(s)==-ECHILD);
        struct cp_iris_status *own=create(2);sample(own,0);assert(!cp_iris_status_destroy(own));_exit(0);
    }
    assert(!pthread_mutex_unlock(&s->mutex));
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
    unchanged(s,&before);assert(!cp_iris_status_destroy(s));
}
static void failures(void) {
    unsigned char p[CP_IRIS_BANK_BYTES],k[CP_IRIS_BANK_BYTES];
    memset(p,0xa5,sizeof p);memset(k,0,sizeof k);
    for (int i=1;i<=2;i++) {
        fail_create=i;errno=0;
        assert(!cp_iris_status_create(2,1,p,sizeof p,k,sizeof k) && errno==ENOMEM);
    }
    fail_create=0;struct cp_iris_status *s=create(2);sample(s,0);assert(!cp_iris_status_destroy(s));
    all(p,sizeof p,0xa5);all(k,sizeof k,0);
}
int main(int argc,char **argv) {
    assert(argc==2);
    if (!strcmp(argv[1],"constructor")) constructor();
    else if (!strcmp(argv[1],"lifecycle")) lifecycle();
    else if (!strcmp(argv[1],"profiles")) profiles();
    else if (!strcmp(argv[1],"source")) source();
    else if (!strcmp(argv[1],"unknown")) unknown();
    else if (!strcmp(argv[1],"invalid")) invalid();
    else if (!strcmp(argv[1],"aliases")) aliases();
    else if (!strcmp(argv[1],"overflow")) overflow();
    else if (!strcmp(argv[1],"concurrent")) concurrent();
    else if (!strcmp(argv[1],"fork")) forked();
    else if (!strcmp(argv[1],"create-failures")) failures();
    else assert(0);
    puts("host_test=1 original_producer=0 source_runtime=0 original_atomicity=0 capture=0");
    return 0;
}
