/* Minimal harness: prove -1022 (OSAL busy) is a retryable poll, not a fatal receive. */
#include "headless-osd.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static int failures, released;
static int receive(unsigned int q,void **m,long t){(void)q;(void)t;*m=(void*)0x1234;return HOSD_TIMEOUT;}
static unsigned int size(void *m){(void)m;return 64;}
static unsigned int source(void *m){(void)m;return 0x9088076b;}
static int release(unsigned int q,void *m){(void)q;if(m==(void*)0x1234)released++;return 0;}
static int allocate(unsigned int q,void **m,unsigned int a,unsigned int b){(void)q;(void)m;(void)a;(void)b;return -1;}
static void set_source(void *m,unsigned int s){(void)m;(void)s;}
static int send(unsigned int q,void *m){(void)q;(void)m;return -1;}
static int frame(struct hosd_frame *f,unsigned char *p){(void)f;(void)p;return -1;}
static void logline(const char *k,const char *t){(void)t;if(!strncmp(k,"OSD_HEADLESS_FAILED",19))failures++;}
static const unsigned int nostop[1]={0};
int main(void){
    struct hosd_state state; memset(&state,0,sizeof state);
    struct hosd_ops ops={receive,size,source,release,allocate,set_source,send,frame,logline,nostop};
    int rc=hosd_step(&state,&ops,HOSD_PATH);
    assert(rc==0);
    assert(!state.failed);
    assert(released==1);
    assert(failures==0);
    printf("HOSD_BUSY_1022_RETRY_NOT_FATAL_PASS released=%d\n",released);
    return 0;
}
