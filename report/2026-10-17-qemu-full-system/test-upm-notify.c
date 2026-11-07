/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <string.h>
#include <stdio.h>
int upm_notify_check(void);
static unsigned int pool[4],allocations,sends,frees,transferred;
static int allocate_failure,send_failure,bad_size,free_failure;
int osal_valloc_msg_wait(unsigned int d,void **p,unsigned int n,int wait){
    assert(d==0x80920572 && n==16 && wait==1);allocations++;
    if(allocate_failure==1)return -12;
    *p=pool;return allocate_failure==2?-12:0;
}
unsigned int osal_msg_size(void *p){assert(p==pool);return bad_size?12:16;}
unsigned int osal_get_msg_src(void *p){assert(p==pool);return 0x12345678;}
int osal_snd_msg(unsigned int d,void *p){
    assert(d==0x80920572 && p==pool);
    const unsigned int expected[4]={0x920117,sends?2:0,0x9a0000,0};
    assert(!memcmp(pool,expected,16));sends++;
    if(send_failure)return -7;
    transferred++;return 0;
}
int osal_free_msg(unsigned int d,void *p){assert(d==0x80920572 && p==pool);frees++;return free_failure?-8:0;}
static void reset(void){allocations=sends=frees=transferred=0;allocate_failure=send_failure=bad_size=free_failure=0;}
int main(void){
    assert(!upm_notify_check() && allocations==2 && sends==2 && transferred==2 && !frees);
    reset();allocate_failure=1;assert(upm_notify_check()==3 && allocations==1 && !sends && !frees);
    reset();allocate_failure=2;assert(upm_notify_check()==3 && frees==1 && !sends);
    reset();bad_size=1;assert(upm_notify_check()==4 && frees==1 && !sends);
    reset();send_failure=1;assert(upm_notify_check()==5 && sends==1 && frees==1 && !transferred);
    reset();send_failure=free_failure=1;assert(upm_notify_check()==5 && sends==1 && frees==1 && !transferred);
    puts("UPM_DIAGNOSTIC_REAL_API_OWNERSHIP_BRANCHES_PASS");return 0;
}
