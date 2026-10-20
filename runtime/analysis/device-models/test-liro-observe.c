/* SPDX-License-Identifier: MIT */
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
typedef int (*backup_function)(unsigned int,void *);
int full_liro_test_backup(backup_function,unsigned int,void *,unsigned long);
int full_liro_test_format(unsigned long,char *,size_t,const char *,...);
void full_liro_test_gate(int,int);
const char *full_liro_test_line(void);
static unsigned int calls;static int result;
static int original(unsigned int key,void *out) {
    assert(key==0xfa007c || key==0x1234);calls++;
    if(!result) {const unsigned char value[8]={0,0,0,1,4,0,0,0};memcpy(out,value,8);}
    errno=EAGAIN;return result?result:8;
}
int main(void) {
    unsigned char slot[8];
    for(int gate=0;gate<3;gate++) {
        full_liro_test_gate(gate!=0,gate==2);memset(slot,0,8);result=0;calls=0;errno=0;
        assert(full_liro_test_backup(original,0xfa007c,slot,0x406178)==8 && calls==1 && errno==EAGAIN);
        assert(slot[3]==1 && slot[4]==4);
        assert((strstr(full_liro_test_line(),"FULL_LIRO_BACKUP")!=0)==(gate==2));
    }
    full_liro_test_gate(1,1);calls=0;
    assert(full_liro_test_backup(original,0x1234,slot,0x406178)==8 && calls==1 && !*full_liro_test_line());
    assert(full_liro_test_backup(original,0xfa007c,slot,0x999999)==8 && calls==2 && !*full_liro_test_line());
    result=-37;memset(slot,0xa5,8);errno=0;
    assert(full_liro_test_backup(original,0xfa007c,slot,0x406178)==-37 && errno==EAGAIN);
    for(unsigned int i=0;i<8;i++)assert(slot[i]==0xa5);
    assert(strstr(full_liro_test_line(),"original_rc=-37") && strstr(full_liro_test_line(),"captured_slot_bytes=8"));
    char expected[1024],observed[1024];
    int a=snprintf(expected,sizeof expected,"%s adr=0x%lx %s %s","",0x401000000ul,"delay=1","fn=/system/av-cam.bin load=1 debug=1");
    full_liro_test_gate(1,1);errno=EBUSY;
    int b=full_liro_test_format(0x4061c4,observed,sizeof observed,"%s adr=0x%lx %s %s","",0x401000000ul,"delay=1","fn=/system/av-cam.bin load=1 debug=1");
    assert(a==b && !strcmp(expected,observed) && errno==EBUSY);
    assert(strstr(full_liro_test_line(),"FULL_LIRO_ARGS") && strstr(full_liro_test_line(),"complete=1"));
    int written=-1;full_liro_test_gate(1,1);
    b=full_liro_test_format(0x4061c4,observed,sizeof observed,"hello%n %d %s",&written,17,"world");
    assert(b==14 && written==5 && !strcmp(observed,"hello 17 world"));
    full_liro_test_gate(1,1);b=full_liro_test_format(0x4061c4,observed,3,"abcdef");
    assert(b==6 && !strcmp(observed,"ab") && strstr(full_liro_test_line(),"complete=0"));
    char large[601];memset(large,'x',600);large[600]=0;
    full_liro_test_gate(1,1);b=full_liro_test_format(0x4061c4,observed,sizeof observed,"%s",large);
    assert(b==600 && strlen(observed)==600 && strstr(full_liro_test_line(),"captured_bytes=511 complete=0"));
    full_liro_test_gate(1,1);b=full_liro_test_format(0x4061c4,0,0,"abcdef");
    assert(b==6 && !*full_liro_test_line());
    full_liro_test_gate(0,1);b=full_liro_test_format(0x4061c4,observed,sizeof observed,"%s","off");
    assert(b==3 && !strcmp(observed,"off") && !*full_liro_test_line());
    puts("LIRO_OBSERVER_FORWARDING_GATES_ERRNO_FORMAT_BOUNDS_PASS");return 0;
}
