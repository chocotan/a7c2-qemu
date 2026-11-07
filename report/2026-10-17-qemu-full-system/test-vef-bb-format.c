/* SPDX-License-Identifier: MIT */
#include "vef-bb-format.h"
#include <assert.h>
#include <string.h>
int main(void){
    unsigned char record[20]={1,0,0,0,0,0,0,0,1,0,0,0,0x80,7,0,0,0x38,4,0,0},buffer[80],copy[80];
    struct vef_bb_format out;
    assert(vef_bb_format_build(record,20,buffer,79)<0);
    assert(!vef_bb_format_build(record,20,buffer,80));
    assert(!memcmp(buffer,"SSYN\0\0\0\2",8) && !memcmp(buffer+32,"ETRY",4));
    assert(!vef_bb_format_decode(buffer,80,&out) && out.code==1 && out.width==1920 && out.height==1080);
    record[0]=3;record[8]=7;record[9]=2;record[10]=0x23;record[11]=0x81;record[12]=0x50;record[13]=5;
    assert(!vef_bb_format_build(record,20,buffer,80));
    assert(!vef_bb_format_decode(buffer,80,&out) && out.code==7 && out.component==2 && out.flags==0x8123 && out.width==1360);
    memcpy(copy,buffer,80);buffer[48]=15;assert(vef_bb_format_decode(buffer,80,&out)<0);
    memcpy(buffer,copy,80);buffer[4]=1;assert(vef_bb_format_decode(buffer,80,&out)<0);
    assert(vef_bb_format_decode(copy,79,&out)<0);return 0;
}
