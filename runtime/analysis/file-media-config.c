/* Select the firmware's existing file backend, only in an explicit standalone test. */
extern void *dlvsym(void *, const char *, const char *);
extern char *getenv(const char *);
extern int printf(const char *, ...);
extern int fflush(void *);
extern void _exit(int);
static unsigned calls;
static unsigned int mounted_media_drive;
static int mounted_media_owner;
static unsigned int busy;
static unsigned long long previous,cancel_pending,cancel_failures;
extern int snprintf(char *,unsigned long,const char *,...);
extern int open(const char *,int,...),close(int);
extern long write(int,const void *,unsigned long);
extern long read(int,void *,unsigned long);
extern int sscanf(const char *,const char *,...),strcmp(const char *,const char *);
extern int fsync(int),rename(const char *,const char *),getpid(void),kill(int,int);
extern int *__errno_location(void);

static void *original_fsys(const char *name) {
    void *(*lookup)(void *,const char *)=dlvsym((void *)-1,"dlsym","GLIBC_2.17");
    void *function=lookup?lookup((void *)-1,name):0;
    if(!function){printf("FSYS_TRACE_RESOLVE_FAILED %s\n",name);fflush(0);_exit(126);}
    return function;
}
static void fsys_trace(const char *operation,const char *path,unsigned long long handle,unsigned int flags,int result) {
    const char *enabled=getenv("A7C2_FILE_MEDIA_TEST");
    if(!enabled || enabled[0]!='1' || enabled[1])return;
    char line[420];
    int n=snprintf(line,sizeof line,"FSYS_FILE_TRACE op=%s path=%.220s handle=%llx flags=%#x result=%d hex=%#x\n",
                   operation,path?path:"-",handle,flags,result,(unsigned int)result);
    if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
}
int Fsys_Mount(const char *path,unsigned int flags,char *drive,const void *extra) {
    int (*function)(const char *,unsigned int,char *,const void *)=original_fsys("Fsys_Mount");
    int rc=function(path,flags,drive,extra);
    if(!rc && drive && path && (!strcmp(path,"/nondev/rm2") || !strcmp(path,"/dev/mmca"))) {
        __atomic_store_n(&mounted_media_owner,getpid(),__ATOMIC_RELEASE);
        __atomic_store_n(&mounted_media_drive,(unsigned char)*drive,__ATOMIC_RELEASE);
    }
    fsys_trace("Mount",path,!rc&&drive?(unsigned char)*drive:0,flags,rc);return rc;
}
/* Observe the original completion; never initiate an unmount for hotplug. */
int Fsys_Unmount(unsigned char drive,unsigned int flags) {
    int (*function)(unsigned char,unsigned int)=original_fsys("Fsys_Unmount");
    int rc=function(drive,flags);
    fsys_trace("Unmount",0,drive,flags,rc);return rc;
}
int Fsys_Mkdir(const char *path) {
    int (*function)(const char *)=original_fsys("Fsys_Mkdir");
    int rc=function(path);fsys_trace("Mkdir",path,0,0,rc);return rc;
}
int Fsys_Open(const char *path,unsigned long long *handle,unsigned int flags) {
    int (*function)(const char *,unsigned long long *,unsigned int)=original_fsys("Fsys_Open");
    int rc=function(path,handle,flags);fsys_trace("Open",path,!rc&&handle?*handle:0,flags,rc);return rc;
}
int Fsys_Write(unsigned long long handle,const void *data,int count) {
    int (*function)(unsigned long long,const void *,int)=original_fsys("Fsys_Write");
    int rc=function(handle,data,count);if(rc<0 || rc!=count)fsys_trace("Write",0,handle,(unsigned int)count,rc);return rc;
}
/* Original Fsys_FTruncate entry saves x0/x1 and overwrites x2 before use. */
int Fsys_FTruncate(unsigned long long handle,unsigned long long bytes) {
    int (*function)(unsigned long long,unsigned long long)=original_fsys("Fsys_FTruncate");
    int rc=function(handle,bytes);
    char size[40];snprintf(size,sizeof size,"bytes=%llu",bytes);
    fsys_trace("FTruncate",size,handle,0,rc);return rc;
}
int Fsys_WriteAndFlush(unsigned long long handle,const void *data,int count) {
    int (*function)(unsigned long long,const void *,int)=original_fsys("Fsys_WriteAndFlush");
    int rc=function(handle,data,count);fsys_trace("WriteAndFlush",0,handle,(unsigned int)count,rc);return rc;
}
int Fsys_WriteFile(const char *path,void *parameters) {
    int (*function)(const char *,void *)=original_fsys("Fsys_WriteFile");
    int rc=function(path,parameters);fsys_trace("WriteFile",path,0,0,rc);return rc;
}
int Fsys_Seek(unsigned long long handle,long long offset,unsigned int origin,void *result) {
    int (*function)(unsigned long long,long long,unsigned int,void *)=original_fsys("Fsys_Seek");
    int rc=function(handle,offset,origin,result);char text[48];snprintf(text,sizeof text,"offset=%lld",offset);
    fsys_trace("Seek",text,handle,origin,rc);return rc;
}
int Fsys_GetFreeSpace(unsigned char drive,void *output) {
    int (*function)(unsigned char,void *)=original_fsys("Fsys_GetFreeSpace");
    int rc=function(drive,output);
    /* The original caller derives its quantities from words 3..7 of this struct,
       not from word 0, so record the whole bounded struct instead of one word. */
    {
        const char *enabled=getenv("A7C2_FILE_MEDIA_TEST");
        if(enabled && enabled[0]=='1' && !enabled[1]){
            char line[300];int n=0;unsigned int i;
            n+=snprintf(line+n,sizeof line-n,"FSYS_FREE_STRUCT drive=%u result=%d words=",(unsigned int)drive,rc);
            for(i=0;i<8 && n>0 && n<(int)sizeof line-12;i++){
                unsigned int word=0;
                if(!rc && output)word=((const unsigned int *)output)[i];
                n+=snprintf(line+n,sizeof line-n,"%s%08x",i?",":"",word);
            }
            n+=snprintf(line+n,sizeof line-n,"\n");
            if(n>0 && n<(int)sizeof line){int fd=open("/dev/console",1);if(fd>=0){write(fd,line,(unsigned long)n);close(fd);}}
        }
    }
    fsys_trace("GetFreeSpace",0,!rc&&output?*(unsigned int *)output:0,drive,rc);return rc;
}

static int flush_store(const char *path,const char *text,int length,int flags) {
    char temporary[120];
    int n=snprintf(temporary,sizeof temporary,"%s.new",path);
    if(length<=0 || n<=0 || n>=(int)sizeof temporary)return 0;
    int fd=open(temporary,flags,0600);
    int stored=fd>=0 && write(fd,text,(unsigned long)length)==length && !fsync(fd);
    if(fd>=0 && close(fd))stored=0;
    return stored && !rename(temporary,path);
}

static int flush_store_cancelled(unsigned long long sequence) {
    char path[96],reply[180];
    snprintf(path,sizeof path,"/tmp/sd-flush.%llu.cancelled",sequence);
    int length=snprintf(reply,sizeof reply,"SD_FSYS_CANCELLED seq=%llu pid=%d\n",sequence,getpid());
    /* Failed attempts can leave .new behind; only this acknowledgement is retried. */
    if(flush_store(path,reply,length,0x8241)){cancel_failures=0;return 1;}
    int error=*__errno_location();
    if(cancel_failures!=~0ULL)cancel_failures++;
    if(cancel_failures<=8 || !(cancel_failures&(cancel_failures-1))) {
        printf("SD_FSYS_CANCELLED_FAILED seq=%llu errno=%d\n",sequence,error);fflush(0);
    }
    *__errno_location()=error;
    return 0;
}

static int flush_enter(void) {
    if(__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE) &&
       __atomic_load_n(&mounted_media_owner,__ATOMIC_ACQUIRE)!=getpid())return 0;
    unsigned int expected=0;
    return __atomic_compare_exchange_n(&busy,&expected,1,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
}

void file_media_flush_cancel_retry(void) {
    if(!flush_enter())return;
    if(cancel_pending && flush_store_cancelled(cancel_pending))cancel_pending=0;
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);
}

/* Reply rename precedes cancel lookup; host publishes cancel before reading this seq's reply. */
void file_media_flush_pending(void) {
    if(!flush_enter())return;
    /* A failed acknowledgement must settle before a newer request can replace it. */
    if(cancel_pending) {
        if(!flush_store_cancelled(cancel_pending))goto done;
        cancel_pending=0;
    }
    int fd=open("/tmp/sd-flush.request",0x8000);
    char request[96];long n=fd>=0?read(fd,request,sizeof request-1):-1;
    if(fd>=0)close(fd);
    if(n>0) {
        request[n]=0;unsigned long long sequence=0;char extra;
        if(sscanf(request,"%llu %c",&sequence,&extra)==1 && sequence>previous) {
            previous=sequence;
            unsigned int drive=__atomic_load_n(&mounted_media_drive,__ATOMIC_ACQUIRE);
            int (*flush)(unsigned char)=original_fsys("Fsys_FlushVolume");
            int rc=drive?flush((unsigned char)drive):-1021;
            char path[96],reply[180];
            int length=snprintf(reply,sizeof reply,"SD_FSYS_FLUSH seq=%llu pid=%d drive=%u rc=%d\n",sequence,getpid(),drive,rc);
            snprintf(path,sizeof path,"/tmp/sd-flush.%llu.reply",sequence);
            if(length<(int)sizeof reply && flush_store(path,reply,length,0x80c1) && !rc) {
                snprintf(path,sizeof path,"/tmp/sd-flush.%llu.cancel",sequence);
                fd=open(path,0x8000);
                int cancelled=fd>=0 || *__errno_location()!=2;
                if(fd>=0)close(fd);
                if(!cancelled && kill(getpid(),19)) {
                    int error=*__errno_location();
                    printf("SD_FSYS_STOP_FAILED seq=%llu errno=%d\n",sequence,error);fflush(0);
                }
                /* A self-SIGSTOP returns only after CONT: persist completion even if the host loses its reply. */
                cancel_pending=sequence;
                if(flush_store_cancelled(sequence))cancel_pending=0;
            }
        }
    }
done:
    __atomic_store_n(&busy,0,__ATOMIC_RELEASE);
}

unsigned file_media_configured(void) { return calls; }

void mcmn_param_init(void) {
    void *(*lookup)(void *, const char *) = dlvsym((void *)-1, "dlsym", "GLIBC_2.17");
    void (*original)(void) = lookup ? lookup((void *)-1, "mcmn_param_init") : 0;
    unsigned (*get)(int) = lookup ? lookup((void *)-1, "mcmn_param_getul") : 0;
    void (*set)(int, unsigned) = lookup ? lookup((void *)-1, "mcmn_param_setul") : 0;
    if (!original || original == mcmn_param_init || !get || !set) {
        printf("FILE_MEDIA_CONFIG_RESOLVE_FAILED\n"); fflush(0); _exit(126);
    }
    original();
    const char *enabled = getenv("A7C2_FILE_MEDIA_TEST");
    if (enabled && enabled[0] == '1' && !enabled[1]) {
        unsigned before = get(0x69);
        set(0x69, 0);
        calls++;
        printf("FILE_MEDIA_CONFIG call=%u EXISTMEDIADRIVER=%u->%u OMIT_WRITE=%u\n",
               calls, before, get(0x69), get(0xf9));
        fflush(0);
    }
}
