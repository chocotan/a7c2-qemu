/* Read board interrupt state in a real guest CPU context (not HMP's attrs). */
typedef unsigned long size_t;
extern int open(const char *,int,...),close(int),munmap(void *,size_t),printf(const char *,...);
extern void *mmap(void *,size_t,int,int,int,unsigned long);
extern long syscall(long,...);
extern int sched_getcpu(void);
extern unsigned int sleep(unsigned int);
extern unsigned long strtoul(const char *,char **,int);
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv) {
    unsigned int repeats=1;
    if(argc==2) { char *end; repeats=strtoul(argv[1],&end,10); if(*end||!repeats||repeats>16)return 2; }
    else if(argc!=1)return 2;
    unsigned long frequency;
    __asm__ volatile("mrs %0, cntfrq_el0":"=r"(frequency));
    printf("FULLSYSTEM_ARCH_COUNTER_HZ=%lu\n",frequency);
    int fd=open("/dev/mem",0);
    if(fd<0)return 3;
    volatile unsigned int *dist=mmap(0,4096,1,1,fd,0x8000000);
    volatile unsigned int *cpuif=mmap(0,4096,1,1,fd,0x8010000);
    if((void *)dist==(void *)-1 || (void *)cpuif==(void *)-1) { printf("BOARD_REGS_MAP_FAILED\n");return 4; }
    close(fd);
    for(unsigned int pass=0;pass<repeats;pass++) {
        for(unsigned int cpu=0;cpu<4;cpu++) {
            unsigned long mask=1UL<<cpu;
            if(syscall(122,0,sizeof mask,&mask))continue;
            /* No IAR/EOIR reads: observing must not acknowledge the interrupt. */
            printf("BOARD_IRQ pass=%u cpu=%d dctl=%x en1=%x pend1=%x active1=%x target8=%x timer_targets=%x cctl=%x pmr=%x rpr=%x hppir=%x\n",
                pass,sched_getcpu(),dist[0],dist[0x104/4],dist[0x204/4],dist[0x304/4],dist[0x820/4],
                dist[0x8e8/4],cpuif[0],cpuif[4/4],cpuif[0x14/4],cpuif[0x18/4]);
        }
        if(pass+1<repeats)sleep(50);
    }
    munmap((void *)dist,4096);munmap((void *)cpuif,4096);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
