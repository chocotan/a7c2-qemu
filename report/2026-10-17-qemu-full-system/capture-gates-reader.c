/* Read-only AppFw field sampler: one maps parse, one mem fd, context reread last. */
typedef unsigned long size_t;
extern int printf(const char *,...);
extern int snprintf(char *,size_t,const char *,...);
extern int sscanf(const char *,const char *,...);
extern char *strstr(const char *,const char *);
extern void *fopen(const char *,const char *);
extern char *fgets(char *,int,void *);
extern int fclose(void *),fflush(void *),open(const char *,int,...),close(int);
extern long pread(int,void *,size_t,long);
struct gate_field {const char *name;unsigned long address;unsigned bytes,scope;};
#include "capture-gates-fields.h"

static int decimal(const char *text,unsigned long maximum,unsigned long *value) {
    if (!text || !*text)return 0;
    *value=0;
    for (;*text;text++) {
        if (*text<'0' || *text>'9')return 0;
        unsigned digit=(unsigned)(*text-'0');
        if (*value>maximum/10 || (*value==maximum/10 && digit>maximum%10))return 0;
        *value=*value*10+digit;
    }
    return *value<=maximum;
}

static int run(int argc,char **argv) {
    unsigned long pid,scope;
    if (argc!=3 || !decimal(argv[1],2147483647UL,&pid) || !pid || !decimal(argv[2],2,&scope))return 2;
    char path[80],line[1024];
    snprintf(path,sizeof path,"/proc/%lu/maps",pid);
    void *maps=fopen(path,"r");if (!maps)return 3;
    unsigned long base=0,start,end,offset;unsigned found=0;
    while (fgets(line,sizeof line,maps)) {
        if (strstr(line,"appFw.so") && sscanf(line,"%lx-%lx %*s %lx",&start,&end,&offset)==3 && end>start && !offset) {
            base=start;found++;
        }
    }
    fclose(maps);if (found!=1 || !base)return 3;
    snprintf(path,sizeof path,"/proc/%lu/mem",pid);
    int fd=open(path,0x80000);if (fd<0)return 3;
    for (unsigned i=0;i<sizeof gate_fields/sizeof gate_fields[0];i++) {
        const struct gate_field *field=&gate_fields[i];if (field->scope>scope)continue;
        unsigned char data[4];
        if (!field->bytes || field->bytes>sizeof data || base>0x7fffffffffffffffUL-field->address) {
            close(fd);return 4;
        }
        unsigned long address=base+field->address;
        printf("CAPTURE_GATE_BEGIN_%s\n",field->name);
        long got=pread(fd,data,field->bytes,(long)address);
        if (got!=(long)field->bytes) {
            printf("CAPTURE_GATE_READ_FAILED field=%s bytes=%ld\n",field->name,got);close(fd);return 5;
        }
        printf("READMEM /proc/%lu/mem address=%lx bytes=%u\n%016lx:",pid,address,field->bytes,address);
        for (unsigned j=0;j<field->bytes;j++)printf(" %02x",data[j]);
        printf("\nCAPTURE_GATE_END_%s\n",field->name);
    }
    close(fd);fflush(0);return 0;
}

#ifndef CAPTURE_READER_TEST
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack) {
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
