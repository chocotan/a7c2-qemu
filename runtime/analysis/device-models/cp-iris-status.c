/* SPDX-License-Identifier: MIT */
#include "cp-iris-status.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

struct cp_iris_status {
    pid_t owner;
    pthread_mutex_t mutex;
    struct cp_iris_status_view view;
};
static int lock(struct cp_iris_status *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD;
    int rc=pthread_mutex_lock(&s->mutex);return rc?-rc:0;
}
static int unlock(struct cp_iris_status *s,int rc) {
    pthread_mutex_unlock(&s->mutex);return rc;
}
static int valid_span(const void *p,size_t n) {
    return p && n && (uintptr_t)p<=UINTPTR_MAX-(n-1);
}
static int private_overlap(const struct cp_iris_status *s,const void *p,size_t n) {
    if (!valid_span(p,n)) return 1;
    uintptr_t a=(uintptr_t)s,b=(uintptr_t)p;
    return a<=b?b-a<sizeof *s:a-b<n;
}
static int packet_valid(const unsigned char *p,size_t n,const unsigned char *k,size_t kn) {
    if (n!=CP_IRIS_BANK_BYTES || kn!=CP_IRIS_BANK_BYTES ||
        !valid_span(p,n) || !valid_span(k,kn)) return -EINVAL;
    for (size_t i=0;i<kn;i++) if (k[i]>1) return -EINVAL;
    return 0;
}
static unsigned int current(const struct cp_iris_status *s) {
    /* Source getter does not wrap. Only validated owned operations set index. */
    return s->view.profile==2?s->view.current_index:0;
}
static unsigned int next(const struct cp_iris_status *s) {
    return s->view.profile==2?(s->view.current_index+1)%CP_IRIS_BANK_COUNT:0;
}
static void publish_index(struct cp_iris_status *s,unsigned int i) {
    s->view.current_index=i;s->view.index_publications++;
    s->view.last_index_publication_sequence=++s->view.sequence;
}
static void copy_bank(struct cp_iris_status *s,unsigned int to,
                      const unsigned char *p,const unsigned char *k) {
    memcpy(s->view.banks[to],p,CP_IRIS_BANK_BYTES);
    memcpy(s->view.known[to],k,CP_IRIS_BANK_BYTES);
    size_t count=0;
    for (size_t i=0;i<CP_IRIS_BANK_BYTES;i++) count+=k[i];
    s->view.known_bytes[to]=count;s->view.copies++;
    s->view.last_copy_sequence=++s->view.sequence;
}
static int room(const struct cp_iris_status *s,unsigned int publications,unsigned int copies) {
    if (s->view.generation==UINT64_MAX ||
        s->view.index_publications>UINT64_MAX-publications ||
        s->view.copies>UINT64_MAX-copies ||
        s->view.sequence>UINT64_MAX-publications-copies) return -EOVERFLOW;
    return 0;
}
struct cp_iris_status *cp_iris_status_create(uint32_t profile,unsigned int profile_known,
    const unsigned char *h0,size_t size,const unsigned char *known,size_t known_size) {
    int rc=packet_valid(h0,size,known,known_size);
    if (!rc && profile_known!=1) rc=profile_known==0?-ENODATA:-EINVAL;
    if (rc) { errno=-rc;return NULL; }
    struct cp_iris_status *s=calloc(1,sizeof *s);if (!s) return NULL;
    s->owner=getpid();rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    s->view.profile=profile;s->view.profile_known=1;
    memcpy(s->view.banks[0],h0,CP_IRIS_BANK_BYTES);
    memcpy(s->view.known[0],known,CP_IRIS_BANK_BYTES);
    memset(s->view.banks[0],0,8);memset(s->view.known[0],1,8);
    s->view.known_bytes[0]=8;
    for (size_t i=8;i<CP_IRIS_BANK_BYTES;i++) s->view.known_bytes[0]+=known[i];
    s->view.constructor_zero_writes=8;
    s->view.constructor_copy_bytes=2*CP_IRIS_BANK_BYTES;
    copy_bank(s,1,s->view.banks[0],s->view.known[0]);
    copy_bank(s,2,s->view.banks[0],s->view.known[0]);
    publish_index(s,0);s->view.generation=1;return s;
}
int cp_iris_next_bank(struct cp_iris_status *s,unsigned int *index) {
    int rc=lock(s);if (rc) return rc;
    if (private_overlap(s,index,sizeof *index)) return unlock(s,-EINVAL);
    *index=next(s);return unlock(s,0);
}
int cp_iris_copy_current_to_next(struct cp_iris_status *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.profile!=2) return unlock(s,0);
    rc=room(s,0,1);if (rc) return unlock(s,rc);
    unsigned int from=current(s);
    copy_bank(s,next(s),s->view.banks[from],s->view.known[from]);
    s->view.generation++;return unlock(s,0);
}
int cp_iris_publish_next(struct cp_iris_status *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.profile!=2) return unlock(s,0);
    rc=room(s,1,1);if (rc) return unlock(s,rc);
    publish_index(s,next(s));
    unsigned int from=current(s);
    copy_bank(s,next(s),s->view.banks[from],s->view.known[from]);
    s->view.generation++;return unlock(s,0);
}
int cp_iris_publish_initial_source(struct cp_iris_status *s,const unsigned char *source,
    size_t size,const unsigned char *known,size_t known_size) {
    int rc=lock(s);if (rc) return rc;
    if (size!=CP_IRIS_BANK_BYTES || known_size!=CP_IRIS_BANK_BYTES ||
        private_overlap(s,source,size) || private_overlap(s,known,known_size))
        return unlock(s,-EINVAL);
    rc=packet_valid(source,size,known,known_size);if (rc) return unlock(s,rc);
    if (s->view.source_copy_count) return unlock(s,-EALREADY);
    rc=room(s,1,1);if (rc) return unlock(s,rc);
    publish_index(s,0);copy_bank(s,0,source,known);
    s->view.source_copy_count++;s->view.generation++;return unlock(s,0);
}
int cp_iris_sample_init_complete(struct cp_iris_status *s,unsigned char *value) {
    int rc=lock(s);if (rc) return rc;
    if (private_overlap(s,value,sizeof *value)) return unlock(s,-EINVAL);
    unsigned int from=current(s);
    if (!s->view.known[from][CP_IRIS_INIT_COMPLETE_OFFSET]) return unlock(s,-ENODATA);
    *value=s->view.banks[from][CP_IRIS_INIT_COMPLETE_OFFSET];return unlock(s,0);
}
int cp_iris_status_snapshot(struct cp_iris_status *s,struct cp_iris_status_view *out) {
    int rc=lock(s);if (rc) return rc;
    if (private_overlap(s,out,sizeof *out)) return unlock(s,-EINVAL);
    *out=s->view;return unlock(s,0);
}
int cp_iris_status_destroy(struct cp_iris_status *s) {
    int rc=lock(s);if (rc) return rc;
    unlock(s,0);rc=pthread_mutex_destroy(&s->mutex);if (rc) return -rc;
    free(s);return 0;
}
