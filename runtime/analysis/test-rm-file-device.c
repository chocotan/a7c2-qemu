#define _GNU_SOURCE
#include "rm-file-device.h"
#include <assert.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
struct buffer {unsigned int n,src,owner;unsigned char data[136];};
static void (*callback)(void *,unsigned long);
static void *sent[32],*alias;
static unsigned int destinations[32],sent_count,freed,registered,allocation_fail,send_fail,done,fork_on_free,unreg_fail,fast_free;
static void log_event(const char *,const char *);
static struct buffer *buffer(void *p){return (void *)((char *)p - offsetof(struct buffer,data));}
static unsigned int size(void *p){return buffer(p)->n;}
static void source(void *p,unsigned int src){buffer(p)->src=src;}
static int allocate(unsigned int dst,void **out,unsigned int n,unsigned int count){
    assert(dst && count==1 && n<=136);if(allocation_fail){*out=0;return -1021;}
    if(alias){*out=alias;return 0;}
    struct buffer *b=calloc(1,sizeof *b);assert(b);b->n=n;b->owner=dst;*out=b->data;return 0;
}
static int release(unsigned int dst,void *p){
    assert(dst && p && dst==buffer(p)->owner);
    if(fork_on_free){
        fork_on_free=0;pid_t child=fork();assert(child>=0);
        if(!child){
            alarm(2);assert(native_rm_file_start(0,0,0,0,0,0)==-1);
            int rc=0;assert(native_rm_file_release(dst,p,release,0,&rc)==1 && rc==-1021);_exit(0);
        }
        int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    }
    __atomic_fetch_add(&freed,1,__ATOMIC_RELAXED);free(buffer(p));return 0;
}
static int send(unsigned int dst,void *p){
    if(send_fail)return -1021;
    assert(sent_count<32);destinations[sent_count]=dst;sent[sent_count++]=p;
    if(fast_free){int rc=-1;assert(native_rm_file_release(buffer(p)->owner,p,release,log_event,&rc)==1 && !rc);}
    return 0;
}
static void log_event(const char *tag,const char *text){
    assert(tag && text);if(!strcmp(tag,"FULL_RM_FILE_REQUEST_FREE "))__atomic_fetch_add(&done,1,__ATOMIC_RELEASE);
}
static void wait_done(unsigned int n){
    for(int i=0;i<3000 && __atomic_load_n(&done,__ATOMIC_ACQUIRE)<n;i++)usleep(1000);
    assert(__atomic_load_n(&done,__ATOMIC_ACQUIRE)==n);
}
static int reg(unsigned int id,void **handle,void *cb,unsigned long arg){
    assert(id==NATIVE_RM_FILE_SID && !arg);callback=cb;*handle=(void *)0x1234;registered=1;return 0;
}
static int unreg(unsigned int id,void *handle){assert(id==NATIVE_RM_FILE_SID && handle==(void *)0x1234);if(unreg_fail)return -1021;registered=0;return 0;}
static int statq(unsigned int id,void *p){assert(id==NATIVE_RM_FILE_SID);memset(p,0,16);((unsigned int *)p)[1]=registered?(unreg_fail?2:1):0;return 0;}
static void p16(unsigned char *p,unsigned int n){p[0]=n;p[1]=n>>8;}
static void p32(unsigned char *p,unsigned int n){for(int i=0;i<4;i++)p[i]=n>>(i*8);}
static unsigned int get32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static void *request(unsigned int opcode,unsigned int payload){
    void *p=0;assert(!allocate(NATIVE_RM_FILE_SID,&p,24+payload,1));
    p32(p,opcode);p16((unsigned char *)p+4,1);p16((unsigned char *)p+6,payload);p32((unsigned char *)p+8,0x1d5e111);
    for(unsigned int i=16;i<24;i++)((unsigned char *)p)[i]=(unsigned char)i;
    return p;
}
static void free_reply(unsigned int i){int rc=-1;assert(native_rm_file_release(destinations[i],sent[i],release,log_event,&rc)==1 && !rc);}
#ifdef NATIVE_RM_FILE_TEST
extern int native_rm_file_test_emit(unsigned int,unsigned int,const unsigned char *,unsigned int);
#endif
int main(int argc,char **argv){
    assert(argc==2);unsigned char boot[512]={0};boot[510]=0x55;boot[511]=0xaa;p16(boot+11,512);boot[13]=32;p16(boot+19,8192);
    long long image_bytes=0x400000;
    if(!strcmp(argv[1],"large") || !strcmp(argv[1],"bad-geometry"))image_bytes=128LL*1024*1024;
    if(!strcmp(argv[1],"large")){p16(boot+19,0);p32(boot+32,(unsigned int)(image_bytes/512));boot[13]=4;}
    if(!strcmp(argv[1],"oversize"))image_bytes=0x80001000LL;
    int fd=open("card",O_CREAT|O_EXCL|O_RDWR,0600);assert(fd>=0 && !ftruncate(fd,image_bytes) && pwrite(fd,boot,512,0)==512);close(fd);
    if(!strcmp(argv[1],"symlink")){assert(!rename("card","real"));assert(!symlink("real","card"));}
    struct full_imaging_io io={allocate,release,source,send,size,0,log_event};
    if(!strcmp(argv[1],"unregfail"))unreg_fail=1;
    if(!strcmp(argv[1],"slot0"))setenv("MENU_RM_FILE_SLOT","0",1);
    if(!strcmp(argv[1],"slotbad"))setenv("MENU_RM_FILE_SLOT","7",1);
    int rc=native_rm_file_start("card","claim",&io,reg,unreg,statq);
    if(!strcmp(argv[1],"slotbad")){assert(rc);return 0;}
    if(!strcmp(argv[1],"symlink") || !strcmp(argv[1],"bad-geometry") || !strcmp(argv[1],"oversize")){assert(rc && !registered);return 0;}
    if(unreg_fail){
        assert(rc && registered && callback);void *bad=request(9,112);callback(bad,0);wait_done(1);
        assert(sent_count==1 && get32((unsigned char *)sent[0]+12)==0x80000004U);free_reply(0);return 0;
    }
    assert(!rc && registered && callback);
#ifdef NATIVE_RM_FILE_TEST
    if(!strncmp(argv[1],"front-",6)){
        const unsigned int owner=0x8028017c,dst=0x80af016f;
        const unsigned char pattern[7]={'O','W','N','E','R',1,2};
        allocation_fail=!strcmp(argv[1],"front-allocfail");
        send_fail=!strcmp(argv[1],"front-sendfail");
        fast_free=!strcmp(argv[1],"front-fastfree");
        rc=native_rm_file_test_emit(owner,dst,pattern,7);
        if(allocation_fail || send_fail){
            assert(rc && !sent_count && freed==(send_fail?1U:0U));return 0;
        }
        assert(!rc && sent_count==1 && destinations[0]==dst);
        if(fast_free){assert(freed==1);return 0;}
        assert(!freed && size(sent[0])==7 && buffer(sent[0])->owner==owner && buffer(sent[0])->src==owner);
        assert(!memcmp(sent[0],pattern,7));
        int released=-1;
        if(!strcmp(argv[1],"front-wrongfree")){
            assert(native_rm_file_release(dst,sent[0],release,log_event,&released)==1 && released==-1021 && !freed);
        }
        assert(native_rm_file_release(owner,sent[0],release,log_event,&released)==1 && !released && freed==1);
        return 0;
    }
#endif
    void *p=request(9,112);
    if(!strcmp(argv[1],"allocfail"))allocation_fail=1;
    if(!strcmp(argv[1],"sendfail"))send_fail=1;
    if(!strcmp(argv[1],"alias"))alias=p;
    if(!strcmp(argv[1],"fastfree"))fast_free=1;
    callback(p,0);wait_done(1);
    if(allocation_fail || send_fail || alias){assert(!sent_count && freed==(send_fail?2U:1U));return 0;}
    if(fast_free){assert(sent_count==1 && freed==2);return 0;}
    assert(sent_count==1 && freed==1 && size(sent[0])==136);
    unsigned char *out=sent[0];assert(!get32(out+12) && get32(out+24)==1);
    if(!strcmp(argv[1],"slot0")){
        /* Single physical slot reported on logical RM1: media fields on record 0 only. */
        assert(get32(out+28)==0 && get32(out+32)==1 && get32(out+36)==2 && get32(out+44)==0x20);
        assert(get32(out+64)==1 && !get32(out+68) && !get32(out+72) && !get32(out+80));
    } else assert(get32(out+64)==1 && get32(out+68)==1 && get32(out+72)==2 && get32(out+80)==0x20);
    for(unsigned int i=16;i<24;i++)assert(out[i]==i);
    if(!strcmp(argv[1],"wrongfree")){
        int bad=0;assert(native_rm_file_release(0x123,sent[0],release,log_event,&bad)==1 && bad && freed==1);
        free_reply(0);return 0;
    }
    if(!strcmp(argv[1],"fork"))fork_on_free=1;
    free_reply(0);
    p=request(2,8);p32((unsigned char *)p+24,0x102);callback(p,0);wait_done(2);assert(sent_count==2 && size(sent[1])==32 && get32((unsigned char *)sent[1]+28)==3);free_reply(1);
    p=request(3,4);p32((unsigned char *)p+24,0x80af016f);callback(p,0);wait_done(3);
    assert(sent_count==4 && destinations[3]==0x80af016f && size(sent[3])==7 && buffer(sent[3])->src==0x80af016f);
    const unsigned char initial[7]={2,0,0,2,0,2,0};assert(!memcmp(sent[3],initial,7));free_reply(2);free_reply(3);
    p=request(99,0);callback(p,0);wait_done(4);assert(size(sent[4])==24 && get32((unsigned char *)sent[4]+12)==0x80000002U);free_reply(4);
    fd=open("card",O_WRONLY);assert(fd>=0 && !ftruncate(fd,16));close(fd);
    p=request(2,8);p32((unsigned char *)p+24,0x102);callback(p,0);wait_done(5);
    assert(size(sent[5])==24 && get32((unsigned char *)sent[5]+12)==0x80010002U);free_reply(5);
    assert(freed==11);return 0;
}
