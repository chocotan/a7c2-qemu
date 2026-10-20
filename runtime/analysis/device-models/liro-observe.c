/* SPDX-License-Identifier: MIT */
/* Optional independent observer. It neither loads LIRO nor supplies drivers. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <unistd.h>

#define LIRO_KEY 0x00fa007cu
#define BACKUP_RETURN 0x406178ul
#define FORMAT_RETURN 0x4061c4ul
#define MAX_ARGS 511u
typedef int (*backup_function)(unsigned int,void *);
#ifdef LIRO_OBSERVER_TEST
static int test_enabled,test_target;
static char test_line[1600];
static int target_process(void) { return test_target; }
static int enabled(void) { return test_enabled; }
static int read_flags(unsigned long address,unsigned int *out) {
    *out=address==0x419738?0x3003:0x3000;return 0;
}
static void emit(const char *line) { snprintf(test_line,sizeof test_line,"%s",line); }
#else
static int target_process(void) {
    char path[256];ssize_t n=readlink("/proc/self/exe",path,sizeof path-1);
    if(n<=0 || n>=(ssize_t)sizeof path-1)return 0;
    path[n]=0;const char *name=strrchr(path,'/');return name && !strcmp(name+1,"im.elf");
}
static int enabled(void) {
    const char *value=getenv("FULLSYSTEM_LIRO_OBSERVE");return value && !strcmp(value,"1");
}
static int read_flags(unsigned long address,unsigned int *out) {
    int fd=open("/proc/self/mem",O_RDONLY|O_CLOEXEC);if(fd<0)return -1;
    ssize_t n=pread(fd,out,sizeof *out,(off_t)address);close(fd);return n==(ssize_t)sizeof *out?0:-1;
}
static void emit(const char *line) {
    int fd=open("/log/qemu/liro-observe.log",O_WRONLY|O_APPEND|O_CREAT|O_CLOEXEC,0600);
    size_t n=strlen(line);
    if(fd<0 || write(fd,line,n)!=(ssize_t)n) {
        static const char failed[]="FULL_LIRO_OBSERVE_FAILURE log-write\n";
        (void)write(2,failed,sizeof failed-1);
    }
    if(fd>=0)close(fd);
}
#endif
static void bytes_hex(char *out,const unsigned char *bytes,size_t n) {
    static const char digits[]="0123456789abcdef";
    for(size_t i=0;i<n;i++){out[2*i]=digits[bytes[i]>>4];out[2*i+1]=digits[bytes[i]&15];}
    out[2*n]=0;
}
static int should_observe(unsigned long caller,unsigned long expected) {
    return caller==expected && enabled() && target_process();
}
static int forward_backup(backup_function original,unsigned int key,void *buffer,unsigned long caller) {
    int rc=original(key,buffer),saved_errno=errno;
    if(key==LIRO_KEY && buffer && should_observe(caller,BACKUP_RETURN)) {
        unsigned char raw[8];memcpy(raw,buffer,sizeof raw);
        unsigned int flags=0,argv_flags=0;int flags_rc=read_flags(0x419738,&flags),argv_rc=read_flags(0x41970c,&argv_flags);
        char hex[17],line[512];bytes_hex(hex,raw,8);
        snprintf(line,sizeof line,"FULL_LIRO_BACKUP pid=%ld caller=%#lx key=%#x original_rc=%d slot_hex=%s captured_slot_bytes=8 flags_rc=%d flags=%#x argv_flags_rc=%d argv_flags=%#x\n",
                 (long)getpid(),caller,key,rc,hex,flags_rc,flags,argv_rc,argv_flags);emit(line);
    }
    errno=saved_errno;return rc;
}
static int forward_format(unsigned long caller,char *out,size_t capacity,const char *format,va_list ap) {
    int rc=vsnprintf(out,capacity,format,ap),saved_errno=errno;
    if(out && capacity && should_observe(caller,FORMAT_RETURN)) {
        size_t limit=capacity-1;if(limit>MAX_ARGS)limit=MAX_ARGS;
        size_t length=strnlen(out,limit);
        int complete=rc>=0 && (size_t)rc<capacity && (size_t)rc<=MAX_ARGS && length==(size_t)rc;
        unsigned int flags=0,argv_flags=0;int flags_rc=read_flags(0x419738,&flags),argv_rc=read_flags(0x41970c,&argv_flags);
        char hex[2*MAX_ARGS+1],line[1500];bytes_hex(hex,(const unsigned char *)out,length);
        /* Format a second, unrelated audit line; never evaluate the original
         * format/va_list twice (in particular any original %n side effect). */
        snprintf(line,sizeof line,"FULL_LIRO_ARGS pid=%ld caller=%#lx original_rc=%d capacity=%lu captured_bytes=%lu complete=%u flags_rc=%d flags=%#x argv_flags_rc=%d argv_flags=%#x args_hex=%s\n",
                 (long)getpid(),caller,rc,(unsigned long)capacity,(unsigned long)length,complete,flags_rc,flags,argv_rc,argv_flags,hex);emit(line);
    }
    errno=saved_errno;return rc;
}
#ifndef LIRO_OBSERVER_TEST
static pthread_once_t backup_once=PTHREAD_ONCE_INIT;
static backup_function original_backup;
static void resolve_backup(void) {
    original_backup=(backup_function)dlsym(RTLD_NEXT,"Backup_read");
    if(!original_backup) {
        emit("FULL_LIRO_OBSERVE_FAILURE real-Backup_read-not-found\n");
        __builtin_trap(); /* Never invent an original API result. */
    }
}
__attribute__((noinline)) int Backup_read(unsigned int key,void *buffer) {
    int saved_errno=errno;pthread_once(&backup_once,resolve_backup);errno=saved_errno;
    return forward_backup(original_backup,key,buffer,(unsigned long)__builtin_return_address(0));
}
__attribute__((noinline)) int snprintf(char *out,size_t capacity,const char *format,...) {
    va_list ap;va_start(ap,format);
    int rc=forward_format((unsigned long)__builtin_return_address(0),out,capacity,format,ap);
    va_end(ap);return rc;
}
#else
/* Tests compile no interposed symbols and use synthetic caller/target values. */
int full_liro_test_backup(backup_function fn,unsigned int key,void *buffer,unsigned long caller) {
    return forward_backup(fn,key,buffer,caller);
}
int full_liro_test_format(unsigned long caller,char *out,size_t capacity,const char *format,...) {
    va_list ap;va_start(ap,format);int rc=forward_format(caller,out,capacity,format,ap);va_end(ap);return rc;
}
void full_liro_test_gate(int enable,int target) { test_enabled=enable;test_target=target;test_line[0]=0; }
const char *full_liro_test_line(void) { return test_line; }
#endif
