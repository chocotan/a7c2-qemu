/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pin-buffer-owner.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <unistd.h>
static pthread_mutex_t binding=PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t descriptor_lifetime=PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t fork_hooks=PTHREAD_ONCE_INIT;
static _Atomic int binding_pid;
/* These handles deliberately live as long as this VM/process owner. */
static int owner_fd=-1;
static int fork_hook_error=-1;
static void before_fork(void){pthread_mutex_lock(&descriptor_lifetime);}
static void parent_after_fork(void){pthread_mutex_unlock(&descriptor_lifetime);}
static void child_after_fork(void){
    /* Close this reference only: LOCK_UN would unlock the parent's shared
     * open-file-description. Do not reset PID/slots or touch inherited locks. */
    if(owner_fd>=0){close(owner_fd);owner_fd=-1;}
    pthread_mutex_unlock(&descriptor_lifetime);
}
/* Sony glibc2.25 exports __register_atfork, while pthread_atfork is supplied
 * by a nonshared link object absent from the dump. These cold-VM modules are
 * process-lifetime and cannot be hot-unloaded, so no DSO-unload cookie is used. */
extern int __register_atfork(void (*)(void),void (*)(void),void (*)(void),void *);
static void install_fork_hooks(void){fork_hook_error=__register_atfork(before_fork,parent_after_fork,child_after_fork,0);}
static int open_owner(void){
    pthread_mutex_lock(&descriptor_lifetime);
    int fd=open("/log/qemu/pin-control-owner.lock",O_RDWR|O_CREAT|O_CLOEXEC,0600);
    if(fd>=0)owner_fd=fd;
    pthread_mutex_unlock(&descriptor_lifetime);return fd;
}
static void drop_owner(int fd){
    pthread_mutex_lock(&descriptor_lifetime);
    if(owner_fd==fd)owner_fd=-1;
    close(fd);pthread_mutex_unlock(&descriptor_lifetime);
}
static long read_bounded(const char *path,unsigned char *out,unsigned long limit){
    int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return -1;
    unsigned long count=0;int failed=0;
    while(count<limit){
        long n=read(fd,out+count,limit-count);
        if(n<0){if(errno==EINTR)continue;failed=1;break;}
        if(!n)break;
        count+=(unsigned long)n;
    }
    if(count==limit){unsigned char extra;long n;do{n=read(fd,&extra,1);}while(n<0 && errno==EINTR);if(n)failed=1;}
    close(fd);return failed?-1:(long)count;
}
static int declared(void){
    unsigned char bytes[8192];long n=read_bounded("/proc/cmdline",bytes,sizeof bytes-1);
    if(n<0)return 0;
    bytes[n]=0;char *save=0;unsigned int profile=0,reservation=0;
    for(char *word=strtok_r((char *)bytes," \r\n\t",&save);word;word=strtok_r(0," \r\n\t",&save)){
        profile+=!strcmp(word,"fullsystem.pin-control-memory=1");reservation+=!strcmp(word,PIN_CONTROL_RESERVATION);
    }
    if(profile!=1 || reservation!=1)return 0;
    const char *key="/sys/firmware/devicetree/base/chosen/qemu,a7c2-pin-control-buffer-owner";
    n=read_bounded(key,bytes,16);
    if(n<0)n=read_bounded("/proc/device-tree/chosen/qemu,a7c2-pin-control-buffer-owner",bytes,16);
    if(n!=16)return 0;
    unsigned long long physical=0,capacity=0;
    for(unsigned int i=0;i<8;i++){physical=(physical<<8)|bytes[i];capacity=(capacity<<8)|bytes[8+i];}
    return physical==PIN_CONTROL_PHYSICAL && capacity==PIN_CONTROL_CAPACITY;
}
int pin_control_open_guest(int enabled){
    if(enabled!=1)return 0;
    int pid=(int)getpid(),expected=0;
    atomic_compare_exchange_strong(&binding_pid,&expected,pid);
    if(atomic_load(&binding_pid)!=pid)return -1;
    if(pthread_once(&fork_hooks,install_fork_hooks) || fork_hook_error)return -1;
    pthread_mutex_lock(&binding);
    if(owner_fd>=0){pthread_mutex_unlock(&binding);return 1;}
    if(!declared()){pthread_mutex_unlock(&binding);return -1;}
    int lock=open_owner();
    if(lock<0 || flock(lock,LOCK_EX|LOCK_NB)){
        if(lock>=0)drop_owner(lock);
        pthread_mutex_unlock(&binding);return -1;
    }
    int fd=open("/dev/mem",O_RDWR|O_SYNC|O_CLOEXEC);
    if(fd<0){drop_owner(lock);pthread_mutex_unlock(&binding);return -1;}
    void *memory=mmap(0,PIN_CONTROL_CAPACITY,PROT_READ|PROT_WRITE,MAP_SHARED,fd,PIN_CONTROL_PHYSICAL);close(fd);
    if(memory==MAP_FAILED || pin_control_bind_reserved(memory,PIN_CONTROL_CAPACITY,PIN_CONTROL_PHYSICAL)){
        if(memory!=MAP_FAILED)munmap(memory,PIN_CONTROL_CAPACITY);
        drop_owner(lock);pthread_mutex_unlock(&binding);return -1;
    }
    owner_fd=lock;pthread_mutex_unlock(&binding);return 1;
}
#ifdef PIN_CONTROL_TEST
void pin_control_test_hold_binding(void){atomic_store(&binding_pid,(int)getpid());pthread_mutex_lock(&binding);}
void pin_control_test_drop_binding(void){pthread_mutex_unlock(&binding);}
#endif
