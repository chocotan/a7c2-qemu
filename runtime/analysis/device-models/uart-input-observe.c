/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
#include <termios.h>
#include <unistd.h>
/* Read only. Never open a TTY, read its input, or change its termios/flags. The
 * scheduler inherits the existing UART via saved fd8, before background stdin
 * redirection; the scheduler then closes its extra fd8. */
static int kernel_output,output_failures;
static void emit(const char *,...) __attribute__((format(printf,1,2)));
static void emit(const char *format,...){
    char buffer[768];va_list args;va_start(args,format);
    int bytes=vsnprintf(buffer,sizeof buffer,format,args);va_end(args);
    if(bytes<0 || (unsigned int)bytes>=sizeof buffer){output_failures++;return;}
    if(!kernel_output){if(fwrite(buffer,1,(unsigned int)bytes,stdout)!=(unsigned int)bytes)output_failures++;return;}
    /* Sony 4.9 rate-limits each open devkmsg file and returns the byte count
     * even when dropping a record. A short-lived record stream has one write;
     * no kernel logging setting is changed. Runtime still requires every END. */
    int fd=open("/dev/kmsg",O_WRONLY|O_CLOEXEC);
    if(fd<0){output_failures++;return;}
    if(write(fd,buffer,(unsigned int)bytes)!=bytes)output_failures++;
    close(fd);
}
static int numeric(const char *text){
    if(!*text)return -1;
    unsigned int n=0;
    for(;*text;text++){
        if(*text<'0' || *text>'9' || n>10000000)return -1;
        n=n*10+(unsigned int)(*text-'0');
    }
    return n<=0x7fffffff?(int)n:-1;
}
static void line_file(const char *prefix,const char *path){
    char data[512];int fd=open(path,O_RDONLY|O_CLOEXEC);
    if(fd<0){emit("%s path=%s read_error=%d\n",prefix,path,errno);return;}
    ssize_t n=read(fd,data,sizeof data-1);int error=errno;close(fd);
    if(n<0){emit("%s path=%s read_error=%d\n",prefix,path,error);return;}
    for(ssize_t i=0;i<n;i++)if((unsigned char)data[i]<32)data[i]=' ';
    data[n]=0;emit("%s path=%s bytes=%ld data=%s\n",prefix,path,(long)n,data);
}
static int tty_target(const char *path){
    return !strncmp(path,"/dev/tty",8) || !strncmp(path,"/dev/console",12) || !strncmp(path,"/dev/pts/",9);
}
static void process_fds(const char *pid){
    char path[160],target[384];snprintf(path,sizeof path,"/proc/%s/fd",pid);
    DIR *directory=opendir(path);if(!directory)return;
    int has_tty=0,has_log=0;struct dirent *entry;
    while((entry=readdir(directory))){
        if(numeric(entry->d_name)<0)continue;
        snprintf(path,sizeof path,"/proc/%s/fd/%.24s",pid,entry->d_name);
        ssize_t n=readlink(path,target,sizeof target-1);if(n<0)continue;target[n]=0;
        if(tty_target(target)){
            has_tty=1;emit("UART_FD pid=%s fd=%s target=%s\n",pid,entry->d_name,target);
            snprintf(path,sizeof path,"/proc/%s/fdinfo/%.24s",pid,entry->d_name);line_file("UART_FDINFO",path);
        }else if(strstr(target,"menu-load.log")){
            has_log=1;emit("UART_LOG_OWNER pid=%s fd=%s target=%s\n",pid,entry->d_name,target);
        }else if(!strcmp(pid,"1") && numeric(entry->d_name)<=2){
            emit("UART_DIAGNOSTIC_FD pid=1 fd=%s target=%s\n",entry->d_name,target);
        }
    }
    closedir(directory);if(!has_tty && !has_log && strcmp(pid,"1"))return;
    for(unsigned int fd=0;fd<3;fd++){
        snprintf(path,sizeof path,"/proc/%s/fd/%u",pid,fd);
        ssize_t n=readlink(path,target,sizeof target-1);
        if(n>=0){target[n]=0;emit("UART_PROCESS_STDIO pid=%s fd=%u target=%s\n",pid,fd,target);}
    }
    snprintf(path,sizeof path,"/proc/%s/ns/mnt",pid);
    ssize_t namespace_bytes=readlink(path,target,sizeof target-1);
    if(namespace_bytes>=0){target[namespace_bytes]=0;emit("UART_MOUNT_NAMESPACE pid=%s target=%s\n",pid,target);}
    int id=numeric(pid);errno=0;pid_t group=getpgid(id);int ge=errno;errno=0;pid_t session=getsid(id);int se=errno;
    emit("UART_PROCESS pid=%s pgrp=%d pgrp_errno=%d session=%d session_errno=%d\n",pid,(int)group,ge,(int)session,se);
    snprintf(path,sizeof path,"/proc/%s/comm",pid);line_file("UART_COMM",path);
    snprintf(path,sizeof path,"/proc/%s/syscall",pid);line_file("UART_THREAD_SYSCALL",path);
    emit("UART_THREAD_COVERAGE pid=%s observed=1 scope=process-leader other_threads_not_sampled=1\n",pid);
}
int main(int argc,char **argv){
    const char *phase=argc>=2?argv[1]:"single";
    if(argc>3 || (argc==3 && strcmp(argv[2],"--kernel-log")) || strlen(phase)>24)return 2;
    for(const char *p=phase;*p;p++)if(!((*p>='a'&&*p<='z')||(*p>='0'&&*p<='9')||*p=='-'||*p=='_'))return 2;
    kernel_output=argc==3;
    emit("UART_INPUT_SNAPSHOT_BEGIN phase=%s pid=%ld no_tty_open=1 no_input_read=1 no_termios_write=1\n",phase,(long)getpid());
    line_file("UART_UPTIME","/proc/uptime");
    errno=0;pid_t foreground=tcgetpgrp(0);int foreground_error=errno;
    emit("UART_FOREGROUND foreground_pgrp=%d errno=%d observer_pgrp=%d observer_session=%d\n",
        (int)foreground,foreground_error,(int)getpgrp(),(int)getsid(0));
    char target[384];ssize_t n=readlink("/proc/self/fd/0",target,sizeof target-1);
    if(n>=0){target[n]=0;emit("UART_INHERITED_FD0 target=%s\n",target);}
    struct termios attrs;memset(&attrs,0,sizeof attrs);errno=0;int rc=tcgetattr(0,&attrs);int error=errno;
    emit("UART_TERMIOS rc=%d errno=%d iflag=%#x oflag=%#x cflag=%#x lflag=%#x ispeed=%lu ospeed=%lu canonical=%u echo=%u vmin=%u vtime=%u\n",
        rc,error,(unsigned int)attrs.c_iflag,(unsigned int)attrs.c_oflag,(unsigned int)attrs.c_cflag,(unsigned int)attrs.c_lflag,
        (unsigned long)cfgetispeed(&attrs),(unsigned long)cfgetospeed(&attrs),!!(attrs.c_lflag&ICANON),!!(attrs.c_lflag&ECHO),attrs.c_cc[VMIN],attrs.c_cc[VTIME]);
    for(unsigned int i=0;i<2;i++){
        const char *path=i?"/log/qemu/menu-load.log":"/tmp/menu-load.log";
        n=readlink(path,target,sizeof target-1);
        if(n>=0){target[n]=0;emit("UART_LOG_LINK path=%s target=%s\n",path,target);}
        int fd=open(path,O_RDONLY|O_CLOEXEC);int error=errno;
        if(fd<0)emit("UART_LOG_STATUS path=%s open_error=%d\n",path,error);
        else{off_t size=lseek(fd,0,SEEK_END);emit("UART_LOG_STATUS path=%s bytes=%ld\n",path,(long)size);close(fd);}
    }
    DIR *processes=opendir("/proc");if(!processes)return 3;struct dirent *entry;
    while((entry=readdir(processes)))if(numeric(entry->d_name)>0)process_fds(entry->d_name);
    closedir(processes);emit("UART_INPUT_SNAPSHOT_END phase=%s rc=%d\n",phase,output_failures?5:0);return output_failures?5:0;
}
#if defined(__aarch64__)
extern int __libc_start_main(int (*)(int,char **),int,char **,void(*)(void),void(*)(void),void(*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(main,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
