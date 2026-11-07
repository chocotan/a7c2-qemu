/* SPDX-License-Identifier: MIT */
/* Isolated diagnostic producer, not the original CP HDMI task. */
#include <stdio.h>
#include <string.h>
extern int osal_valloc_msg_wait(unsigned int,void **,unsigned int,int);
extern int osal_free_msg(unsigned int,void *);
extern int osal_snd_msg(unsigned int,void *);
extern unsigned int osal_get_msg_src(void *);
extern unsigned int osal_msg_size(void *);

int upm_notify_check(void){
    const unsigned int destination=0x80920572;
    for(unsigned int selector=0;selector<=2;selector+=2){
        void *message=0;
        int rc=osal_valloc_msg_wait(destination,&message,16,1);
        if(rc || !message){
            int cleanup=message?osal_free_msg(destination,message):0;
            printf("UPM_DIAG_ALLOC selector=%u rc=%d cleanup=%d\n",selector,rc,cleanup);
            return 3;
        }
        if(osal_msg_size(message)!=16){
            int cleanup=osal_free_msg(destination,message);
            printf("UPM_DIAG_SIZE selector=%u cleanup=%d\n",selector,cleanup);return 4;
        }
        const unsigned int body[4]={0x00920117,selector,0x009a0000,0};
        memcpy(message,body,sizeof body);
        /* The original producer has no explicit set_source call. Observe the
         * real allocation's source, do not manufacture CP source metadata. */
        printf("UPM_DIAG_SEND selector=%u destination=%#x source=%#x pointer=%p raw=17019200%02x00000000009a0000000000 original_cp_task=0\n",
               selector,destination,osal_get_msg_src(message),message,selector);
        fflush(stdout);
        rc=osal_snd_msg(destination,message);
        int cleanup=rc?osal_free_msg(destination,message):0;
        printf("UPM_DIAG_SEND_RETURN selector=%u rc=%d cleanup=%d ownership_transferred=%u\n",selector,rc,cleanup,rc==0);
        fflush(stdout);
        if(rc)return 5;
    }
    return 0;
}
#ifndef UPM_NOTIFY_TEST
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
static int run(int argc,char **argv){
    if(argc!=2 || strcmp(argv[1],"--isolated-diagnostic"))return 2;
    return upm_notify_check();
}
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
