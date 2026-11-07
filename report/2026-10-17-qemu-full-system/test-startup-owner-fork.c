/* Test copied startup owners while their real send path holds the owner lock. */
#include "dmm-device.h"
#include "dig-level-device.h"
#include "audio-device.h"
#include <assert.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/wait.h>

struct message {unsigned int owner,source,bytes;unsigned char data[];};
static int context;static void *queued;
static const unsigned int D=0x81cf61c3;
static const struct full_imaging_io io;
static struct message *head(void *p){return (struct message *)((unsigned char *)p-sizeof(struct message));}
static int allocate(unsigned int id,void **out,unsigned int n,unsigned int wait){
    assert(wait==1);struct message *m=calloc(1,sizeof *m+n);assert(m);m->owner=id;m->bytes=n;*out=m->data;return 0;
}
static int release(unsigned int id,void *p){assert(head(p)->owner==id);free(head(p));return 0;}
static unsigned int size(void *p){return head(p)->bytes;}
static unsigned int source(void *p){return head(p)->source;}
static void set_source(void *p,unsigned int id){head(p)->source=id;}
static unsigned int destination(void){return context==0?FULL_DMM_CP:context==1?FULL_DIG_LEVEL_INPUT:FULL_AUDIO_INPUT;}
static int invoke(void *p,int *rc){
    if(context==0)return full_dmm_dispatch(destination(),p,&io,1,rc);
    if(context==1)return full_dig_level_dispatch(destination(),p,&io,1,rc);
    return full_audio_dispatch(destination(),p,&io,FULL_AUDIO_BOOT,rc);
}
static int release_reply(void *p,int *rc){
    if(context==0)return full_dmm_release_reply(D,p,release,0,rc);
    if(context==1)return full_dig_level_release_reply(D,p,release,0,rc);
    return full_audio_release_reply(D,p,release,0,rc);
}
static int send(unsigned int id,void *p){
    assert(id==D && head(p)->owner==D && !queued);
    pid_t child=fork();assert(child>=0);
    if(!child){
        alarm(2);int rc=0;
        assert(invoke(p,&rc)==1 && rc==-1021);
        assert(release_reply(p,&rc)==1 && rc==-1021);
        if(context==0){struct full_dmm_snapshot s;full_dmm_snapshot(&s);assert(!s.queries && !s.live_replies);}
        else if(context==1){struct full_dig_level_snapshot s;full_dig_level_snapshot(&s);assert(!s.queries && !s.live_replies);}
        else {struct full_audio_snapshot s;full_audio_snapshot(&s);assert(!s.queued && !s.live_replies);unsigned int level=17;assert(full_audio_replay_config(&level)==-1021 && level==17);}
        _exit(0);
    }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && WEXITSTATUS(status)==0);
    queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
int main(void){
    full_dmm_test_reset();full_dig_level_test_reset();full_audio_test_reset();
    for(context=0;context<3;context++){
        unsigned int bytes=context==0?40:context==1?24:10;void *request=0;assert(!allocate(destination(),&request,bytes,1));
        unsigned char *p=request;set_source(p,D);
        if(context==0){p[0]=0x18;p[4]=0x58;p[5]=0x0b;p[6]=5;}
        else if(context==1)p[0]=3;
        else {p[0]=0x0d;p[1]=0x20;p[2]=0x2a;p[3]=3;p[4]=10;p[6]=1;p[7]=0x80;p[8]=7;}
        int rc=-1;assert(invoke(request,&rc)==1 && !rc && queued);
        assert(release_reply(queued,&rc)==1 && !rc);queued=0;
    }
    puts("DS_STARTUP_OWNERS_REAL_LOCKED_FORK_DISPATCH_RELEASE_SNAPSHOT_PASS");return 0;
}
