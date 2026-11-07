/* SPDX-License-Identifier: MIT */
/* Apply the official PP's Bluetooth-Off preference through the original Backup
 * API in a virtual guest. No error notification, product flag or code is patched. */
typedef unsigned long size_t;
extern int printf(const char *,...),strcmp(const char *,const char *),open(const char *,int,...),close(int);
extern long read(int,void *,size_t);
extern char *strstr(const char *,const char *);
extern int Backup_nread(unsigned int,void *,int);
extern int Backup_write(unsigned int,unsigned int,const void *);
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
static const unsigned int ids[2]={0x02cf03ffu,0x02cf00c7u};
static const unsigned char wanted[2]={1,0};
static int virtual_guest(void) {
    char model[64]={0},args[8192]={0};
    int fd=open("/proc/device-tree/model",0);if(fd<0)return 0;
    long n=read(fd,model,sizeof model-1);close(fd);
    if(n<=0 || strcmp(model,"linux,dummy-virt"))return 0;
    fd=open("/proc/cmdline",0);if(fd<0)return 0;
    n=read(fd,args,sizeof args-1);close(fd);
    return n>0 && n<(long)sizeof args-1 && strstr(args," fullsystem.bluetooth=off");
}
static int restore(const unsigned char old[2][4]) {
    int ok=1;
    for(unsigned int i=0;i<2;i++) {
        unsigned char check[4]={0xff,0xff,0xff,0xff};
        int w=Backup_write(0x2cf,ids[i],old[i]);
        int r=Backup_nread(ids[i],check,sizeof check);
        int same=w>=0 && r==1 && check[0]==old[i][0];ok&=same;
        printf("FULL_BLUETOOTH_POLICY_RESTORE id=%#x original=%#x write_rc=%d read_rc=%d actual=%#x matches=%d\n",ids[i],old[i][0],w,r,check[0],same);
    }
    return ok;
}
static int run(int argc,char **argv) {
    if(argc!=2 || strcmp(argv[1],"off") || !virtual_guest())return 2;
    unsigned char old[2][4]={{0xff},{0xff}};
    for(unsigned int i=0;i<2;i++) {
        int rc=Backup_nread(ids[i],old[i],sizeof old[i]);
        printf("FULL_BLUETOOTH_POLICY_BEFORE id=%#x read_rc=%d value=%#x\n",ids[i],rc,old[i][0]);
        if(rc!=1)return 3;
    }
    for(unsigned int i=0;i<2;i++) {
        int rc=old[i][0]==wanted[i]?0:Backup_write(0x2cf,ids[i],wanted+i);
        unsigned char actual[4]={0xff,0xff,0xff,0xff};int got=Backup_nread(ids[i],actual,sizeof actual);
        printf("FULL_BLUETOOTH_POLICY_READBACK id=%#x expected=%#x actual=%#x write_rc=%d read_rc=%d\n",ids[i],wanted[i],actual[0],rc,got);
        if(rc<0 || got!=1 || actual[0]!=wanted[i]) {
            int restored=restore(old);
            printf("FULL_BLUETOOTH_POLICY_FAILED restored=%d\n",restored);return 4;
        }
    }
    printf("FULL_BLUETOOTH_POLICY_OFF_VERIFIED original_api=1 patch_error=0 original_pp_default=1\n");
    return 0;
}
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
