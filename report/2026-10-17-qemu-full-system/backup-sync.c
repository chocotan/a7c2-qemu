/* Explicit original Backup sync diagnostic; no model writes or substitute replies. */
extern int printf(const char *,...);
extern int fflush(void *);
extern int strcmp(const char *,const char *);
extern int Backup_sync_subsystem(unsigned int);
extern int Backup_sync_all(void);

static int subsystem_number(const char *text,unsigned *number) {
    unsigned base=10,value=0;
    if (!text || !*text)return 0;
    if (text[0]=='0' && text[1]=='x') {base=16;text+=2;if (!*text)return 0;}
    for (;*text;text++) {
        unsigned digit;
        if (*text>='0' && *text<='9')digit=(unsigned)(*text-'0');
        else if (*text>='a' && *text<='f')digit=(unsigned)(*text-'a')+10;
        else if (*text>='A' && *text<='F')digit=(unsigned)(*text-'A')+10;
        else return 0;
        if (digit>=base || value>(65535U-digit)/base)return 0;
        value=value*base+digit;
    }
    *number=value;return 1;
}

static int run(int argc,char **argv) {
    unsigned subsystem=0;int all=argc==2 && !strcmp(argv[1],"--all");
    if (!all && (argc!=3 || strcmp(argv[1],"--subsystem") ||
                 !subsystem_number(argv[2],&subsystem)))return 2;
    printf("BACKUP_SYNC_BEGIN scope=%s subsystem=%u\n",all?"all":"subsystem",subsystem);
    fflush(0);
    int result=all?Backup_sync_all():Backup_sync_subsystem(subsystem);
    printf("BACKUP_SYNC_END scope=%s subsystem=%u result=%d\n",
           all?"all":"subsystem",subsystem,result);
    fflush(0);
    return result==0?0:1;
}

#ifndef BACKUP_SYNC_TEST
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
