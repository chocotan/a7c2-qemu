/* SPDX-License-Identifier: MIT */
#include "cp-cold-control.h"
#include <errno.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

/* ROM2.01 words, independently pinned by report/cp-background-contract/verify.py.
 * 8000 and 8001 are boundaries, not module completions. */
static const unsigned short to57[]={
    0x100,0x200,0x300,0x400,0x500,0x600,0x700,0x900,0xa00,0xb01,0xc06,0xd00,
    0x8000,0x108,0x8001
};
static const unsigned short to0[]={
    0x100,0x200,0x300,0x400,0x500,0x600,0x700,0x900,0xa00,0xb01,0xd00,0x8000
};
static const unsigned char parameter0[12]={0x08,0x0f,0xe6,0x18,0x20,0x80,0x12,0,0,0,0,0};
static const unsigned char parameter8[12]={0x08,0x0f,0xa6,0x18,0x20,0x80,0x12,0,0,0,0,0};
struct cp_cold_control {
    pid_t owner;
    pthread_mutex_t mutex;
    struct cp_sync_resources *resources;
    struct cp_cold_snapshot view;
    unsigned int position, loaded, boundary, fault;
    /* A limited published field, not a fully modeled 72-byte Sony snapshot.
     * All consumers here are restricted to the valid two bytes at +24(hex). */
    unsigned char state_banks[2][72];
};
static int lock(struct cp_cold_control *s) {
    if (!s) return -EINVAL;
    if (s->owner!=getpid()) return -ECHILD;
    int rc=pthread_mutex_lock(&s->mutex);return rc?-rc:0;
}
static int unlock(struct cp_cold_control *s,int rc) {
    pthread_mutex_unlock(&s->mutex);return rc;
}
struct cp_cold_control *cp_cold_create(unsigned int mode,struct cp_sync_resources *resources) {
    struct cp_sync_snapshot resource_state;
    if (mode!=3 || cp_sync_snapshot(resources,&resource_state)) { errno=EINVAL;return NULL; }
    struct cp_cold_control *s=calloc(1,sizeof *s);
    if (!s) return NULL;
    int rc=pthread_mutex_init(&s->mutex,NULL);
    if (rc) { free(s);errno=rc;return NULL; }
    s->owner=getpid();s->resources=resources;s->view.model_mode=mode;
    s->view.exec_active=1;s->view.exec_last_event=0xf00;return s;
}
int cp_cold_destroy(struct cp_cold_control *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy || s->view.ended_command || s->view.completion_event_pending) return unlock(s,-EBUSY);
    unlock(s,0);pthread_mutex_destroy(&s->mutex);free(s);return 0;
}
int cp_cold_begin(struct cp_cold_control *s,unsigned int command) {
    int rc=lock(s);if (rc) return rc;
    if (s->view.busy || s->view.ended_command || s->view.completion_event_pending) return unlock(s,-EBUSY);
    if (command!=0x3007 || s->view.current || s->fault) return unlock(s,-ENOTSUP);
    if (s->view.generation==0xffffffffu || s->view.observer_notifications>0xffffffffu-4) return unlock(s,-EOVERFLOW);
    /* Original event4 fanouts r2=0,1,3. In this fresh cold profile the exact
     * (current0,cmd3024) ROM lookup is absent, so B's start query is false but
     * copies the real owned busy value to its diagnostic mirror. All selected
     * state0 member-pairs are zero; do not reset either observer state. */
    s->view.observer_a_index=s->view.exec_active?6:4;
    s->view.busy_mirror=s->view.busy;
    s->view.observer_b_index=2;
    memset(s->view.observer_a_member,0,sizeof s->view.observer_a_member);
    memset(s->view.observer_b_member,0,sizeof s->view.observer_b_member);
    if (s->view.exec_active) s->view.exec_last_event=4;
    s->view.exec_active=0;
    s->view.observer_a_index=8;s->view.observer_b_index=5;
    s->view.observer_notifications+=3;
    s->view.generation++;s->view.busy=1;s->view.path=0;s->view.group=0;s->view.target=0x57;
    s->position=0;s->loaded=0;return unlock(s,0);
}
static int load_group(struct cp_cold_control *s) {
    const unsigned short *words=s->view.path?to0:to57;
    unsigned int count=s->view.path?sizeof to0/sizeof *to0:sizeof to57/sizeof *to57;
    while (s->position<count) {
        unsigned int word=words[s->position++];
        if (word&0x8000) { s->boundary=word;s->loaded=1;return 0; }
        unsigned int high=word>>8;
        if (!high || high>13) return -ENOTSUP;
        s->view.requested[high-1]=word;
        s->view.pending_modules|=1u<<(high-1);
    }
    return -EINVAL;
}
static int consume_known(struct cp_cold_control *s) {
    /* Mode/sync/deferred/feedback inputs are properties of this explicit fresh
     * cold profile. No API accepts a mode switch, active recovery or feedback
     * callback; such work must use another backend, not mutate this profile. */
    struct cp_sync_snapshot resources;
    int rc=cp_sync_snapshot(s->resources,&resources);if (rc) return rc;
    unsigned int request=s->view.requested[0];
    if (s->view.pending_modules&1) {
        if (request!=0x100 && request!=0x108) return -ENOTSUP;
        /* DEV6/7/8 backed recovery is unsupported, not a successful reset.
         * Overall idle below is a stronger finite cold precondition. */
        if (!resources.idle) return 0;
        memcpy(s->view.parameters,request==0x100?parameter0:parameter8,12);
        s->view.parameter_valid=1;
        s->view.observed[0]=request;s->view.pending_modules&=~1u;
    }
    if ((s->view.pending_modules&(1u<<10)) && s->view.requested[10]==0xb01) {
        /* Known mode0's 13 flags only. Descriptor/threshold consumers are not
         * modeled, so slot10 remains pending and observed is NOT filled. */
        memset(s->view.policy_flags,0,sizeof s->view.policy_flags);
        s->view.policy_flags_valid=1;
    }
    if ((s->view.pending_modules&(1u<<11)) && s->view.requested[11]==0xc06) {
        if (s->view.state_record_generation==0xffffffffu) return -EOVERFLOW;
        unsigned int bank=s->view.state_record_generation&1;
        s->state_banks[bank][0x24]=6;s->state_banks[bank][0x25]=0x0c;
        s->view.state_record_generation++;
        s->view.state_record_valid=1;
        unsigned int published=(~s->view.state_record_generation)&1;
        s->view.state_record_value=s->state_banks[published][0x24] |
            (unsigned int)s->state_banks[published][0x25]<<8;
        /* This proves the limited field's publication, not full snapshot or
         * feedback side effects. Keep slot11 pending until those are bound. */
    }
    return 0;
}
int cp_cold_tick(struct cp_cold_control *s) {
    int rc=lock(s);if (rc) return rc;
    if (s->fault) return unlock(s,-ENOTSUP);
    if (!s->view.busy) return unlock(s,-ENOENT);
    if (!s->loaded) { rc=load_group(s);if (rc) { s->fault=1;return unlock(s,rc); } }
    rc=consume_known(s);if (rc) { s->fault=1;return unlock(s,rc); }
    for (unsigned int i=0;i<13;i++) if ((s->boundary&(1u<<i)) &&
        s->view.requested[i]!=s->view.observed[i]) return unlock(s,0);
    s->loaded=0;s->view.group++;
    unsigned int end=s->view.path?sizeof to0/sizeof *to0:sizeof to57/sizeof *to57;
    if (s->position<end) return unlock(s,0);
    s->view.current=s->view.target;
    if (!s->view.path) {
        s->view.path=1;s->view.target=0;s->position=0;return unlock(s,0);
    }
    s->view.busy=0;s->view.ended_command=0x3007;return unlock(s,1);
}
int cp_cold_snapshot(struct cp_cold_control *s,struct cp_cold_snapshot *out) {
    int rc=lock(s);if (rc) return rc;
    if (!out) return unlock(s,-EINVAL);
    *out=s->view;return unlock(s,0);
}
int cp_cold_take_end(struct cp_cold_control *s,unsigned int *command) {
    int rc=lock(s);if (rc) return rc;
    if (!command) return unlock(s,-EINVAL);
    *command=s->view.ended_command;s->view.ended_command=0;
    if (*command) s->view.completion_event_pending=*command;
    return unlock(s,0);
}
int cp_cold_observe_end(struct cp_cold_control *s,unsigned int command) {
    int rc=lock(s);if (rc) return rc;
    if (command!=0x3007 || s->view.completion_event_pending!=command) return unlock(s,-ENOENT);
    if (s->view.observer_a_state>6 || s->view.observer_b_state>4) return unlock(s,-ENOTSUP);
    /* All seven A[index8] and five B[index5] entries are (0,0) in the original
     * tables. Dispatcher writes are still real effects; states stay unchanged. */
    s->view.observer_a_index=8;s->view.observer_b_index=5;
    memset(s->view.observer_a_member,0,sizeof s->view.observer_a_member);
    memset(s->view.observer_b_member,0,sizeof s->view.observer_b_member);
    s->view.observer_notifications++;
    s->view.exec_active=1; /* 0->1 does NOT overwrite the saved start event4 */
    s->view.completion_event_pending=0;
    return unlock(s,0);
}
