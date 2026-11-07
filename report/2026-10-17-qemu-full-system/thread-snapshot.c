/* SPDX-License-Identifier: MIT */
/* Explicit diagnostic: SEIZE/INTERRUPT, capture frames while stopped, detach,
 * then print. Ptrace can still perturb timing; final behavior needs a control
 * run without tracing. Never inject SIGSTOP or modify target registers. */
typedef unsigned long size_t;
struct iovec { void *base; size_t length; };
struct regs { unsigned long x[31],sp,pc,pstate; };
struct frame { unsigned long address,previous,lr; };
struct timespec { long seconds,nanoseconds; };
extern int printf(const char *,...);
extern int snprintf(char *,size_t,const char *,...);
extern unsigned long strtoul(const char *,char **,int);
extern int strcmp(const char *,const char *);
extern long syscall(long,...);
extern int *__errno_location(void);
extern void *fopen(const char *,const char *);
extern int fseek(void *,long,int);
extern size_t fread(void *,size_t,size_t,void *);
extern int fclose(void *);
extern int fork(void);
extern int kill(int,int);
extern int waitpid(int,int *,int);
extern int nanosleep(const struct timespec *,struct timespec *);
extern unsigned int alarm(unsigned int);
extern void (*signal(int,void (*)(int)))(int);
extern void _exit(int);
extern int __libc_start_main(int (*)(int,char **),int,char **,
                            void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int traced;
static void timeout(int number) {
    (void)number;
    if (traced) syscall(117,17,traced,0,0);
    _exit(6); /* Tracer exit also detaches; EXITKILL is never requested. */
}
static int snapshot(int tid) {
    struct regs regs;
    struct frame frames[32];
    unsigned int count=0;
    unsigned long stack_top[2]={0,0};
    int stack_top_valid=0;
    signal(14,timeout);alarm(3);
    if (syscall(117,0x4206,tid,0,0)<0) { alarm(0);return 3; } /* SEIZE */
    traced=tid;
    int status=0,result=5;
    if (syscall(117,0x4207,tid,0,0)<0) goto detached; /* INTERRUPT */
    if (syscall(260,tid,&status,0x40000000,0)!=tid || (status&255)!=127) goto detached;
    struct iovec vector={&regs,sizeof regs};
    if (syscall(117,0x4204,tid,1,&vector)<0 || vector.length!=sizeof regs) goto detached;
    char path[64];snprintf(path,sizeof path,"/proc/%d/mem",tid);
    void *memory=fopen(path,"rb");
    if (!memory) goto detached;
    /* Capture only two raw words while stopped. Leaf/cancellation wrappers
     * may save LR at SP without establishing an FP frame. Interpret these
     * words only after verifying the original instructions at the sampled PC. */
    if (!(regs.sp%16) && !fseek(memory,regs.sp,0) &&
        fread(stack_top,sizeof stack_top,1,memory)==1)stack_top_valid=1;
    unsigned long fp=regs.x[29];
    while (count<32 && fp>=regs.sp && fp-regs.sp<=1048576 && !(fp%16)) {
        unsigned long values[2];
        if (fseek(memory,fp,0) || fread(values,sizeof values,1,memory)!=1) break;
        frames[count++]=(struct frame){fp,values[0],values[1]};
        if (values[0]<=fp) break;
        fp=values[0];
    }
    fclose(memory);result=0;
detached:;
    int error=*__errno_location();
    long released=syscall(117,17,tid,0,0);
    traced=0;alarm(0);
    if (result || released<0) {
        printf("REGS_ERROR tid=%d status=%d errno=%d detach=%ld seize=1\n",tid,status,error,released);
        return 5;
    }
    printf("REGS tid=%d pc=%lx lr=%lx sp=%lx fp=%lx seize=1 frozen_frames=1\n",
           tid,regs.pc,regs.x[30],regs.sp,regs.x[29]);
    printf("REGS_CALL_CONTEXT tid=%d x0=%lx x8=%lx stack_top_valid=%d word0=%lx word1=%lx frozen=1\n",
           tid,regs.x[0],regs.x[8],stack_top_valid,stack_top[0],stack_top[1]);
    for (unsigned int i=0;i<count;i++)
        printf("FRAME tid=%d fp=%lx savedfp=%lx lr=%lx\n",tid,frames[i].address,frames[i].previous,frames[i].lr);
    return 0;
}
static int run(int argc,char **argv) {
    if (argc!=2) return 2;
    if (!strcmp(argv[1],"--selftest")) {
        int child=fork(),status=0;
        if (child<0) return 3;
        if (!child) {
            struct timespec delay={2,0};
            _exit(nanosleep(&delay,0)?7:0);
        }
        struct timespec settle={0,50000000};nanosleep(&settle,0);
        int result=snapshot(child);
        if (result) kill(child,9);
        waitpid(child,&status,0);
        if (result || status) return 5;
        printf("REGS_SEIZE_SELFTEST_PASS interrupted_sleep=0\n");return 0;
    }
    char *end;unsigned long tid=strtoul(argv[1],&end,10);
    if (*end || !tid || tid>2147483647UL) return 2;
    return snapshot((int)tid);
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);
    __builtin_trap();
}
