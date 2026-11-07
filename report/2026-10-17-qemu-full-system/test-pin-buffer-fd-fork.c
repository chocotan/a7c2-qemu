/* SPDX-License-Identifier: MIT */
/* Host-only syscall fixtures. No actual device or guest cmdline is opened. */
#define _GNU_SOURCE
#include "pin-buffer-owner.h"
#include <assert.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
static const char *lock_path;
static int decimal(const char *text){
    unsigned int n=0;assert(*text);
    for(;*text;text++){assert(*text>='0' && *text<='9' && n<=((unsigned int)INT_MAX-(unsigned int)(*text-'0'))/10);n=n*10+(unsigned int)(*text-'0');}
    return (int)n;
}
int __real_open(const char *,int,...);
void *__real_mmap(void *,size_t,int,int,int,off_t);
static int bytes_fd(const void *bytes,size_t size){
    int fd=(int)syscall(SYS_memfd_create,"host-control-fd-fixture",MFD_CLOEXEC);assert(fd>=0);
    assert(write(fd,bytes,size)==(ssize_t)size && lseek(fd,0,SEEK_SET)==0);return fd;
}
int __wrap_open(const char *path,int flags,...){
    if(!strcmp(path,"/proc/cmdline")){
        const char text[]="fullsystem.pin-control-memory=1 " PIN_CONTROL_RESERVATION;
        return bytes_fd(text,sizeof text-1);
    }
    if(!strcmp(path,"/sys/firmware/devicetree/base/chosen/qemu,a7c2-pin-control-buffer-owner")){
        const unsigned char identity[16]={0,0,0,5,0,0,0,0,0,0,0,0,0,0,0x20,0};return bytes_fd(identity,sizeof identity);
    }
    if(!strcmp(path,"/log/qemu/pin-control-owner.lock"))return __real_open(lock_path,flags,0600);
    if(!strcmp(path,"/dev/mem"))return bytes_fd("",0);
    abort();
}
void *__wrap_mmap(void *address,size_t length,int prot,int flags,int fd,off_t offset){
    assert(!address && length==PIN_CONTROL_CAPACITY && flags==MAP_SHARED && fd>=0 && offset==(off_t)PIN_CONTROL_PHYSICAL);
    return __real_mmap(0,length,prot,MAP_SHARED|MAP_ANONYMOUS,-1,0);
}
int main(int argc,char **argv){
    assert(argc==2 || argc==5);lock_path=argv[1];alarm(10);
    if(argc==2){
        assert(pin_control_open_guest(1)==1);
        int gate[2],ready[2];assert(!pipe(gate) && !pipe(ready));pid_t child=fork();assert(child>=0);
        if(!child){
            close(gate[1]);close(ready[0]);
            /* Child close must not unlock the parent's still-live OFD. */
            int fresh=__real_open(lock_path,O_RDWR|O_CLOEXEC);assert(fresh>=0 && flock(fresh,LOCK_EX|LOCK_NB)<0);close(fresh);
            assert(write(ready[1],"r",1)==1);close(ready[1]);char byte;assert(read(gate[0],&byte,1)==1);
            assert(pin_control_open_guest(1)<0);_exit(0);
        }
        close(gate[0]);close(ready[1]);char byte;assert(read(ready[0],&byte,1)==1);close(ready[0]);
        char writer[32],pid[32];snprintf(writer,sizeof writer,"%d",gate[1]);snprintf(pid,sizeof pid,"%d",(int)child);
        const char *emulator=getenv("PIN_CONTROL_TEST_QEMU"),*prefix=getenv("PIN_CONTROL_TEST_LD_PREFIX");
        if(emulator){assert(prefix);execl(emulator,emulator,"-L",prefix,argv[0],lock_path,"after-exec",writer,pid,(char *)0);}
        else execl(argv[0],argv[0],lock_path,"after-exec",writer,pid,(char *)0);
        abort();
    }
    assert(pin_control_open_guest(1)==1);
    puts("CONTROL_FORK_CHILD_CLOSES_LOCK_REF_PARENT_EXEC_REBINDS_WHILE_CHILD_ALIVE_PASS");
    assert(write(decimal(argv[3]),"x",1)==1);int status;
    assert(waitpid((pid_t)decimal(argv[4]),&status,0)>0 && WIFEXITED(status) && WEXITSTATUS(status)==0);
    puts("CONTROL_CHILD_PID_STILL_REFUSED_PARENT_LOCK_NOT_UNLOCKED_PASS");return 0;
}
