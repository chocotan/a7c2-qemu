#include <assert.h>
#include <stdio.h>
#include <string.h>
#define FULL_CLOCK_TEST
#define sleep clock_test_sleep
#include "init-clock.c"
#undef sleep
static int scenario,initialized,sets,elapsed;
static unsigned char local[16];
unsigned int clock_test_sleep(unsigned int n) { if(scenario!=6) elapsed+=n;return 0; }
int osal_snd_sync_direct(unsigned int sid,void *request) {
    struct message *m=request; unsigned char *p=b(m);
    assert(sid==0x90013d && m->q[0]==48);
    unsigned int op=u16(p+16);
    if(scenario==4) return -1020;
    put16(p+18,0);
    if(op==2) {
        if(!initialized) p[32]=scenario==5?2:3;
        else { memcpy(p+20,local,16);p[26]+=elapsed; }
    } else if(op==3) {
        memcpy(p+20,local,16);
        put16(p+36,scenario==1||scenario==3||scenario==7?480:scenario==2?-300:0);
        put16(p+38,scenario==3?60:0);
    } else {
        assert(op==0 && p[32]==1 && u16(p+44)==4);
        sets++;
        if(scenario==1||scenario==3) {
            assert(u16(p+20)==2022 && p[22]==12 && p[23]==31);
            assert(p[24]==(scenario==3?15:16));
        } else if(scenario==2) {
            assert(u16(p+20)==2023 && p[22]==1 && p[23]==1 && p[24]==5);
        } else {
            assert(u16(p+20)==2023 && p[22]==1 && p[23]==1 && p[24]==0);
        }
        initialized=1;
    }
    return 0;
}
static void reset(int n) {
    scenario=n;initialized=sets=elapsed=0;memset(local,0,sizeof local);
    put16(local,n==7?2000:2023);local[2]=local[3]=1;
}
int main(void) {
    for(int n=0;n<=3;n++) { reset(n);assert(full_clock_init()==0 && sets==1 && elapsed==2); }
    for(int n=4;n<=7;n++) { reset(n);assert(full_clock_init()!=0); }
    reset(0);initialized=1;assert(full_clock_init()==0 && sets==0);
    struct message m={{48,0,0,0,0,0}};
    put16(b(&m)+20,2024);b(&m)[22]=3;b(&m)[23]=1;
    long time=seconds(&m);assert(set_seconds(&m,time-3600)==0);
    assert(u16(b(&m)+20)==2024 && b(&m)[22]==2 && b(&m)[23]==29 && b(&m)[24]==23);
    puts("FULL_CLOCK_TEST_PASS: UTC offsets, day/year/leap boundaries, preservation, failures and advancement");
    return 0;
}
