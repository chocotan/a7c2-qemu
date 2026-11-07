/* New taps only: original primitive once; body objects and CP packets stay opaque. */
struct TailWriter {int live,fd;unsigned long calls,bytes,failures;long last;};
static struct TailWriter tail_writers[5];
long write(int fd,const void *data,unsigned long bytes) {
    void *caller=__builtin_return_address(0);
    int saved=*__errno_location();long (*fn)(int,const void *,unsigned long)=next("write");if(!fn)__builtin_trap();
    int target=-1;
    if(tail_site(4,caller,0x8a14)) {
        char name[48],path[80];snprintf(name,sizeof name,"/proc/self/fd/%d",fd);
        int n=readlink(name,path,sizeof path-1);if(n>0){path[n]=0;target=tail_raw_target(path);}
    }
    *__errno_location()=saved;long rc=fn(fd,data,bytes);int error=*__errno_location();
    if(target>=0) {
        char line[220];int first;
        while(__atomic_test_and_set(&tail_lock,__ATOMIC_ACQUIRE)){}
        struct TailWriter *w=tail_writers+target;first=!w->live || w->fd!=fd;
        if(first)*w=(struct TailWriter){.live=1,.fd=fd};
        w->calls++;if(rc>0)w->bytes+=(unsigned long)rc;if(rc<0)w->failures++;w->last=rc;
        __atomic_clear(&tail_lock,__ATOMIC_RELEASE);
        if(first || rc<0 || (unsigned long)rc!=bytes) {
            snprintf(line,sizeof line,"target=%d fd=%d requested=%lu native_calls=1 first=%d offset=unknown readback_verified=0",target,fd,bytes,first);
            tail_emit(T_WRITER,"write",line,rc,error,caller);
        }
    }
    *__errno_location()=error;return rc;
}
int close(int fd) {
    void *caller=__builtin_return_address(0);
    int saved=*__errno_location();int (*fn)(int)=next("close");if(!fn)__builtin_trap();
    int observe=tail_site(5,caller,0x8888);
    struct TailWriter copy={0};int target=-1;
    if(observe) {
        while(__atomic_test_and_set(&tail_lock,__ATOMIC_ACQUIRE)){}
        for(int i=0;i<5;i++)if(tail_writers[i].live && tail_writers[i].fd==fd){copy=tail_writers[i];tail_writers[i].live=0;target=i;break;}
        __atomic_clear(&tail_lock,__ATOMIC_RELEASE);
    }
    *__errno_location()=saved;int rc=fn(fd),error=*__errno_location();
    if(target>=0) {
        char line[280];snprintf(line,sizeof line,"target=%d fd=%d writes=%lu native_bytes=%lu failures=%lu last_write=%ld flush_observed=0 readback_verified=0",target,fd,copy.calls,copy.bytes,copy.failures,copy.last);
        tail_emit(T_WRITER,"close",line,rc,error,caller);
    }
    *__errno_location()=error;return rc;
}
static void tail_string(char *out,unsigned size,const char *p) {
    int e=0;unsigned i=0;
    for(;i+1<size;i++){char c;if(passive_read(&c,p+i,1,&e)!=1)break;if(!c)break;out[i]=(c>=32 && c<127)?c:'?';}
    out[i]=0;
}
int system(const char *command) {
    int saved=*__errno_location();int (*fn)(const char *)=next("system");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int shell=tail_site(6,caller,0x18a20),built=tail_site(7,caller,0x19314);
    char line[480];unsigned family=built?T_END:T_PLUGIN;
    if(shell || built){char text[320];tail_string(text,sizeof text,command);snprintf(line,sizeof line,"command=%s original_calls=1",text);tail_emit(family,"system-start",line,0,saved,caller);}
    *__errno_location()=saved;int rc=fn(command),error=*__errno_location();
    if(shell || built){snprintf(line,sizeof line,"wait_status=%d exited=%d exit_status=%u signaled=%d",rc,rc>=0 && !(rc&127),rc>=0?(unsigned)(rc>>8)&255:0,rc>=0 && (rc&127)!=0);tail_emit(family,"system-return",line,rc,error,caller);}
    *__errno_location()=error;return rc;
}
int pthread_join(unsigned long thread,void **value) {
    int saved=*__errno_location();int (*fn)(unsigned long,void **)=next("pthread_join");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=tail_site(9,caller,0x183c4);char line[160];
    if(observe){snprintf(line,sizeof line,"thread=%lu value=%p value_layout=opaque original_calls=1",thread,value);tail_emit(T_PLUGIN,"join-start",line,0,saved,caller);}
    *__errno_location()=saved;int rc=fn(thread,value),error=*__errno_location();
    if(observe)tail_emit(T_PLUGIN,"join-return",line,rc,error,caller);
    *__errno_location()=error;return rc;
}
void *dlopen(const char *path,int flags) {
    int saved=*__errno_location();void *(*fn)(const char *,int)=next("dlopen");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=tail_site(8,caller,0x18c9c);
    char line[400];if(observe){char p[280];tail_string(p,sizeof p,path);snprintf(line,sizeof line,"path=%s flags=%x original_calls=1 dlerror=unconsumed",p,flags);tail_emit(T_PLUGIN,"dlopen-start",line,0,saved,caller);}
    *__errno_location()=saved;void *rc=fn(path,flags);int error=*__errno_location();
    if(observe)tail_emit(T_PLUGIN,"dlopen-return",line,(long)rc,error,caller);
    *__errno_location()=error;return rc;
}
