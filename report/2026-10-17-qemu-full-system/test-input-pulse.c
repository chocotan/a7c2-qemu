/* Pulse ownership/order faults: send success transfers/free immediately. */
#include <assert.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#define INPUT_INJECT_TEST 1
#include "inject-key.c"

static int sends,sleeps,frees,fail_send,sleep_mode,states[4];
static unsigned source;
int osal_valloc_msg_wait(unsigned q,void **m,unsigned bytes,int wait) {
    (void)q;(void)wait;assert(bytes==20);*m=malloc(bytes);assert(*m);return 0;
}
void osal_set_msg_src(void *m,unsigned src) {(void)m;source=src;}
unsigned osal_get_msg_src(void *m) {(void)m;return source;}
int osal_free_msg(unsigned q,void *m) {(void)q;free(m);frees++;return 0;}
int osal_snd_msg(unsigned q,void *m) {
    (void)q;states[sends]=((unsigned *)m)[2];sends++;
    if (sends==fail_send)return -7;
    free(m);return 0;
}
int nanosleep(const struct input_timespec *delay,struct input_timespec *remaining) {
    assert(sends==1 && states[0]==1);sleeps++;
    assert(delay->seconds==0 && delay->nanoseconds>0 && delay->nanoseconds<=50000000L);
    if (sleep_mode==1 && sleeps==1) {
        remaining->seconds=0;remaining->nanoseconds=1000000;errno=EINTR;return -1;
    }
    if (sleep_mode==2) {errno=EINVAL;return -1;}
    return 0;
}
static void reset(void) {sends=sleeps=frees=fail_send=sleep_mode=0;}
int main(void) {
    char *args[]={"inject-key","0x807a0020","0x92840747","0x30","0","1","0","1","--pulse-ms","50"};
    reset();assert(!run(10,args) && sends==2 && sleeps==1 && states[0]==1 && states[1]==0 && !frees);
    reset();sleep_mode=1;assert(!run(10,args) && sleeps==2 && sends==2);
    reset();sleep_mode=2;assert(run(10,args)==5 && sends==2 && states[1]==0);
    reset();fail_send=1;assert(run(10,args)==4 && sends==1 && !sleeps && frees==1);
    reset();fail_send=2;assert(run(10,args)==4 && sends==2 && frees==1);
    reset();args[9]="500";assert(run(10,args)==2 && !sends);
    args[9]="";assert(run(10,args)==2 && !sends);
    args[9]="50";args[5]="0";assert(run(10,args)==2 && !sends);
    return 0;
}
