/* Host-only API fault tests; not compiled into the guest. */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#define INPUT_INJECT_TEST 1
#define run key_run
#include "inject-key.c"
#undef run
#define run event_run
#include "inject-event.c"
#undef run

static int send_error,bad_source,cleanup_error,frees,sends,transfers;
static unsigned int saved_source;
int osal_valloc_msg_wait(unsigned int q,void **m,unsigned int bytes,int wait){
    (void)q;(void)wait;*m=malloc(bytes);assert(*m);return 0;
}
void osal_set_msg_src(void *m,unsigned int source){(void)m;saved_source=bad_source?0:source;}
unsigned int osal_get_msg_src(void *m){(void)m;return saved_source;}
int osal_free_msg(unsigned int q,void *m){(void)q;frees++;free(m);return cleanup_error;}
int osal_snd_msg(unsigned int q,void *m){
    (void)q;sends++;
    if(!send_error){transfers++;free(m);} /* original recipient owns success */
    return send_error;
}
static void check(int (*tool)(int,char **),int argc,char **argv){
    frees=sends=transfers=bad_source=send_error=cleanup_error=0;
    assert(tool(argc,argv)==0 && frees==0 && sends==1 && transfers==1);
    frees=sends=transfers=0;bad_source=1;
    assert(tool(argc,argv)==4 && frees==1 && sends==0);
    frees=sends=transfers=bad_source=0;send_error=-77;
    assert(tool(argc,argv)==4 && frees==1 && sends==1 && transfers==0);
    frees=sends=transfers=0;cleanup_error=-8;
    assert(tool(argc,argv)==6 && frees==1 && sends==1);
}
int main(void){
    char *key[]={"inject-key","0x807a0020","0x92840747","0x1ab","0","1","0","1"};
    char *event[]={"inject-event","0x5503e0","0x5503e0","ab01000000000000010000000000000000000000000000000100000000000000"};
    check(key_run,8,key);check(event_run,4,event);return 0;
}
