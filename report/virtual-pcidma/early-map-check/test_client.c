#define FIXED_IO_HOST_TEST
#include "client.c"
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
static unsigned calls,pass,mode;
int host_translate(u64 virtual,u64 *physical)
{
    assert(calls<10 && virtual==(0xffffffff00000000UL|addresses[calls]));
    *physical=addresses[calls++];
    if(mode==1 && calls==5)return 0;
    if(mode==2 && calls==9)*physical+=4096;
    if(mode==3 && calls==10)*physical&=~4095UL;
    return 1;
}
int printk(const char *format,...)
{
    if(strstr(format,"EARLY_IOMAP_PASS:"))pass++;
    return 0;
}
int main(void)
{
    for(mode=0;mode<4;mode++) {
        calls=pass=0;int rc=init_module();
        assert((mode==0 && !rc && pass==1 && calls==10) || (mode && rc==-22 && !pass));
    }
    puts("PASS_HOST: existing mappings, missing page, wrong PA and offset loss; no mapping writes");
}
