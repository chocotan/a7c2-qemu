/* SPDX-License-Identifier: MIT */
#include "cp-cold-control.h"
#include <assert.h>
#include <errno.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void) {
    struct cp_sync_resources *resources=cp_sync_create(1024);assert(resources);
    assert(!cp_cold_create(1,resources));
    struct cp_cold_control *control=cp_cold_create(3,resources);assert(control);
    struct cp_cold_snapshot v;
    unsigned int command=99;
    assert(!cp_cold_snapshot(control,&v) && !v.busy && !v.state_record_valid &&
           v.model_mode==3 && v.exec_active==1 && v.exec_last_event==0xf00);
    assert(cp_cold_observe_end(control,0x3007)==-ENOENT);
    assert(!cp_cold_take_end(control,&command) && !command);
    assert(cp_cold_begin(control,0x4073)==-ENOTSUP);
    /* An actual live alias/backing must block the selected 0108 boundary. */
    uint64_t lease,alias;
    assert(!cp_sync_allocate(resources,0,64,&lease));
    assert(!cp_sync_alias(resources,60,lease,&alias));
    assert(!cp_cold_begin(control,0x3007));
    assert(cp_cold_begin(control,0x3007)==-EBUSY);
    assert(cp_cold_destroy(control)==-EBUSY);
    assert(cp_cold_tick(control)==0); /* 8000: no selected returned slot */
    assert(!cp_cold_snapshot(control,&v) && v.group==1 && !v.observed[0]);
    assert(cp_cold_tick(control)==0); /* 8001: actual backing still active */
    assert(!cp_cold_snapshot(control,&v) && v.busy && v.group==1 && v.requested[0]==0x108);
    assert(!cp_sync_release(resources,lease) && !cp_sync_release(resources,alias));
    assert(cp_cold_tick(control)==0); /* zero refs alone do not free backing */
    assert(!cp_cold_snapshot(control,&v) && !v.observed[0] && v.group==1);
    assert(!cp_sync_free(resources,60,lease));
    assert(cp_cold_tick(control)==0);
    assert(!cp_cold_snapshot(control,&v));
    assert(v.current==0x57 && v.path==1 && v.observed[0]==0x108);
    assert(v.state_record_valid && v.state_record_generation && v.state_record_value==0xc06);
    assert(v.policy_flags_valid && !v.observed[10] && !v.observed[11]);
    for (unsigned int i=0;i<13;i++) assert(!v.policy_flags[i]);
    assert(cp_cold_tick(control)==1);
    assert(!cp_cold_snapshot(control,&v));
    assert(!v.busy && !v.current && v.observed[0]==0x100 && v.ended_command==0x3007);
    assert(v.pending_modules && !v.observed[1] && !v.observed[10] && !v.observed[11]);
    /* Ended transition does not turn unsupported modules into completed ones. */
    assert(cp_cold_tick(control)==-ENOENT);
    assert(cp_cold_destroy(control)==-EBUSY);
    assert(!cp_cold_take_end(control,&command) && command==0x3007);
    assert(cp_cold_begin(control,0x3007)==-EBUSY);
    assert(cp_cold_destroy(control)==-EBUSY);
    assert(cp_cold_observe_end(control,0x300a)==-ENOENT);
    assert(!cp_cold_observe_end(control,0x3007));
    assert(!cp_cold_snapshot(control,&v) && v.observer_a_index==8 && v.observer_b_index==5 &&
           !v.observer_a_state && !v.observer_b_state && v.observer_notifications==4 &&
           v.exec_active==1 && v.exec_last_event==4 && !v.busy_mirror && !v.completion_event_pending);
    assert(cp_cold_observe_end(control,0x3007)==-ENOENT);
    assert(!cp_cold_take_end(control,&command) && !command);
    assert(!cp_cold_begin(control,0x3007));
    assert(cp_cold_tick(control)==0 && cp_cold_tick(control)==0 && cp_cold_tick(control)==1);
    assert(!cp_cold_snapshot(control,&v) && v.generation==2);
    pid_t pid=fork();assert(pid>=0);
    if (!pid) _exit(cp_cold_tick(control)==-ECHILD && cp_cold_destroy(control)==-ECHILD?0:1);
    int status;assert(waitpid(pid,&status,0)==pid && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!cp_cold_take_end(control,&command) && command==0x3007);
    assert(!cp_cold_observe_end(control,command));
    assert(!cp_cold_destroy(control));
    assert(!cp_sync_destroy(resources));
    return 0;
}
