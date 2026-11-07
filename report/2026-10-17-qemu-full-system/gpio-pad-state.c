/* SPDX-License-Identifier: MIT */
/* Explicit virtual C1 pad for the existing RAM-backed GPIO window. This writes
 * the simulated external input, not the driver's physical-key cache. */
typedef unsigned long size_t;
extern int open(const char *,int,...),close(int),munmap(void *,size_t),printf(const char *,...);
extern long read(int,void *,size_t);
extern int strcmp(const char *,const char *);
extern char *strstr(const char *,const char *);
extern void *mmap(void *,size_t,int,int,int,unsigned long);
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static int run(int argc,char **argv) {
    if(argc!=2 || (strcmp(argv[1],"read") && strcmp(argv[1],"release") && strcmp(argv[1],"press")))return 2;
    char model[64]={0},cmdline[8192]={0};
    int fd=open("/proc/device-tree/model",0);
    if(fd<0)return 3;
    long n=read(fd,model,sizeof model-1);close(fd);
    if(n<=0 || strcmp(model,"linux,dummy-virt"))return 3;
    fd=open("/proc/cmdline",0);if(fd<0)return 3;
    n=read(fd,cmdline,sizeof cmdline-1);close(fd);
    if(n<=0 || n==(long)sizeof cmdline-1 || !strstr(cmdline," fullsystem.gpio-c1=virtual"))return 3;
    fd=open("/dev/mem",2);if(fd<0)return 4;
    volatile unsigned int *gpio=mmap(0,4096,3,1,fd,0xf102e000UL);close(fd);
    if((void *)gpio==(void *)-1)return 5;
    unsigned int before=gpio[4],after=before,mask=0x00040000u;
    printf("FULLSYSTEM_GPIO_PAD_BEFORE port=0x11 bit=0x12 dir=%#x rdata=%#x inen=%#x portsel=%#x wdata=%#x\n",
        gpio[0],before,gpio[8],gpio[12],gpio[16]);
    if(!strcmp(argv[1],"release"))after=before|mask;
    if(!strcmp(argv[1],"press"))after=before&~mask;
    if(strcmp(argv[1],"read")) {
        gpio[4]=after;
        __asm__ volatile("dsb sy\nisb":::"memory");
    }
    unsigned int actual=gpio[4];
    int ok=actual==after;
    printf("FULLSYSTEM_GPIO_PAD_%s action=%s physical=0xf102e010 before=%#x expected=%#x readback=%#x others_preserved=%u\n",
        ok?"READBACK":"FAULT",argv[1],before,after,actual,((actual^before)&~mask)==0);
    munmap((void *)gpio,4096);return ok?0:6;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
