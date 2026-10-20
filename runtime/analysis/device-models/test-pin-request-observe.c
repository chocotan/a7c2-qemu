/* SPDX-License-Identifier: MIT */
#include "pin-request-observe.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(void){
    unsigned char byte=0;
    assert(!full_pin_request_visible(0x9000003f,0,64));
    assert(!full_pin_request_visible(0x9000003f,&byte,1));
    assert(full_pin_request_visible(0x90590818,&byte,1));
    for(unsigned int n=48;n<=64;n+=16){
        unsigned char p[64]={0},original[64];
        p[4]=p[5]=p[6]=p[7]=0xa0;p[8]=1;p[10]=(unsigned char)n;p[12]=24;p[16]=(unsigned char)n;
        p[25]=0x10;p[26]=n==48?0:1;p[28]=(unsigned char)(n-24);p[30]=2;memcpy(original,p,64);
        assert(full_pin_request_visible(0x9000003f,p,n));assert(!memcmp(p,original,64));
        const unsigned int offsets[]={4,8,10,12,16,24,26,28,30};
        for(unsigned int i=0;i<sizeof offsets/sizeof offsets[0];i++){
            p[offsets[i]]^=0x40;assert(!full_pin_request_visible(0x9000003f,p,n));p[offsets[i]]^=0x40;
        }
        assert(!full_pin_request_visible(0x9000003f,p,n-1));
    }
    puts("READONLY_UNKNOWN_PIN_EXACT_ENVELOPE_CAPTURE_AND_SHORT_BUFFER_REFUSAL_PASS");return 0;
}
