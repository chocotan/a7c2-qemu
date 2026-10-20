/* Explicit generic-virt loader handoff for a kernel built to take over GIC state.
 * Restore only missing SPI targets. Never change enables, priorities, IAR or EOIR.
 */
typedef unsigned long size_t;
extern int open(const char *,int,...),close(int),munmap(void *,size_t),printf(const char *,...);
extern long read(int,void *,size_t),syscall(long,...);
extern int strcmp(const char *,const char *);
extern void *mmap(void *,size_t,int,int,int,unsigned long);
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv) {
    (void)argv;
    if(argc!=1)return 2;
    char model[64]={0};
    int fd=open("/proc/device-tree/model",0);
    if(fd<0)return 3;
    long n=read(fd,model,sizeof model-1);close(fd);
    if(n<=0 || strcmp(model,"linux,dummy-virt"))return 3;
    unsigned long affinity=0;
    if(syscall(123,0,sizeof affinity,&affinity)<0 || !(affinity&1))return 4;
    if((affinity&(affinity-1))==0) {
        printf("FULLSYSTEM_GIC_HANDOFF_SINGLE_CPU no-target-write\n");return 0;
    }
    unsigned long cpu0=1;
    if(syscall(122,0,sizeof cpu0,&cpu0))return 4;
    fd=open("/dev/mem",2);
    if(fd<0)return 5;
    volatile unsigned int *dist=mmap(0,4096,3,1,fd,0x8000000);
    close(fd);
    if((void *)dist==(void *)-1)return 6;
    unsigned int irqs=((dist[1]&31)+1)*32;
    if(irqs>1020)irqs=1020;
    if(irqs<64)return 7;
    volatile unsigned char *targets=(volatile unsigned char *)dist+0x800;
    unsigned int added=0,kept=0;
    for(unsigned int irq=32;irq<irqs;irq++) {
        if(targets[irq])kept++;
        else { targets[irq]=1;added++; }
    }
    __asm__ volatile("dsb sy\nisb":::"memory");
    for(unsigned int irq=32;irq<irqs;irq++) {
        if(!targets[irq]) { printf("FULLSYSTEM_GIC_HANDOFF_FAILED irq=%u\n",irq);return 8; }
    }
    printf("FULLSYSTEM_GIC_TARGETS_READY added=%u kept=%u spi_count=%u target_cpu=0\n",added,kept,irqs-32);
    munmap((void *)dist,4096);
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
