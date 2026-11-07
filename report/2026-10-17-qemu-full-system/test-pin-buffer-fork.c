/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pin-buffer-owner.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
static pthread_barrier_t ready,release_lock;
static int binding_case;
static void barrier(pthread_barrier_t *value){int rc=pthread_barrier_wait(value);assert(rc==0 || rc==PTHREAD_BARRIER_SERIAL_THREAD);}
static void *holder(void *unused){
    (void)unused;
    if(binding_case)pin_control_test_hold_binding();else pin_control_test_hold_lock();
    barrier(&ready);barrier(&release_lock);
    if(binding_case)pin_control_test_drop_binding();else pin_control_test_drop_lock();
    return 0;
}
static void waited(pid_t child){int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);}
int main(void){
    unsigned char *memory=mmap(0,PIN_CONTROL_CAPACITY,PROT_READ|PROT_WRITE,MAP_SHARED|MAP_ANONYMOUS,-1,0);
    assert(memory!=MAP_FAILED);pin_control_test_reset();assert(!pin_control_bind_reserved(memory,PIN_CONTROL_CAPACITY,PIN_CONTROL_PHYSICAL));
    pid_t child=fork();assert(child>=0);
    if(!child){
        alarm(2);struct pin_control_lease lease={0};struct pin_control_snapshot state;
        assert(pin_control_allocate(PIN_CONTROL_UNIT,&lease)<0);
        assert(pin_control_write_ssyn(0x8000,0)<0 && pin_control_release(0x8000)<0);
        assert(pin_control_bind_reserved(memory,PIN_CONTROL_CAPACITY,PIN_CONTROL_PHYSICAL)<0);
        pin_control_snapshot(&state);assert(!state.bound && !state.allocations);_exit(0);
    }
    waited(child);struct pin_control_lease lease;assert(!pin_control_allocate(PIN_CONTROL_UNIT,&lease));
    assert(lease.handle==0x8000 && !pin_control_write_ssyn(lease.handle,0) && !pin_control_release(lease.handle));
    puts("CONTROL_OWNER_FORKED_SHARED_BACKING_LEASE_REJECTED_PASS");
    for(binding_case=0;binding_case<2;binding_case++){
        assert(!pthread_barrier_init(&ready,0,2) && !pthread_barrier_init(&release_lock,0,2));
        pthread_t thread;assert(!pthread_create(&thread,0,holder,0));barrier(&ready);
        child=fork();assert(child>=0);
        if(!child){
            alarm(2);
            if(binding_case)assert(pin_control_open_guest(1)<0);
            else assert(pin_control_allocate(PIN_CONTROL_UNIT,&lease)<0);
            _exit(0);
        }
        waited(child);barrier(&release_lock);assert(!pthread_join(thread,0));
        assert(!pthread_barrier_destroy(&ready) && !pthread_barrier_destroy(&release_lock));
    }
    munmap(memory,PIN_CONTROL_CAPACITY);puts("CONTROL_OWNER_PID_GUARDS_BEFORE_INHERITED_POOL_AND_BINDING_LOCKS_PASS");return 0;
}
