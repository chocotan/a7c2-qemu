/* SPDX-License-Identifier: MIT */
#include "hdmi-cold-settings.h"
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define MAX_UNIT_BYTES 256u
static int overlaps(const void *a,unsigned long n,const void *b,unsigned long m){
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return x<=y?y-x<n:x-y<m;
}
static unsigned int u32(const unsigned char *p){
    return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;
}
/* 1: complete stable original read; 0: missing/read failure; -1: outside
 * this finite reader or a changing/partial positive result. */
static int unit(const struct hdmi_backup_api *api,unsigned int key,unsigned char out[MAX_UNIT_BYTES],unsigned int *size){
    unsigned int before=api->get_size(key),rc=0xffffffffu,after=before;int result=0;
    memset(out,0,MAX_UNIT_BYTES);*size=0;
    if(before && !(before&0x80000000u)){
        if(before>MAX_UNIT_BYTES)result=-1;
        else {
            rc=api->nread(key,out,(int)before);
            if(rc==before){after=api->get_size(key);result=after==before?1:-1;}
            else if(rc && !(rc&0x80000000u))result=-1;
        }
    }
    if(result==1)*size=before;
    if(api->record){
        char line[180];snprintf(line,sizeof line,"key=%#x size_before=%#x original_nread=%#x size_after=%#x read_result=%d",
                               key,before,rc,after,result);api->record("FULL_HDMI_COLD_BACKUP ",line);
    }
    return result;
}
int hdmi_cold_settings_read(const struct hdmi_backup_api *api,const unsigned char *fallback,struct hdmi_cold_settings *out){
    if(!api || !out || !api->get_size || !api->nread || overlaps(out,sizeof *out,api,sizeof *api) ||
       (fallback && overlaps(out,sizeof *out,fallback,28)))return -1;
    static const unsigned int keys[8]={0x010d008d,0x003e0005,0x009a0001,0x010704fd,
                                       0x009a0009,0x009a000a,0x009a000b,0x009a000c};
    struct hdmi_cold_settings next={0};next.initial[0]=5;next.key_10704fd=1;
    for(unsigned int i=0;i<8;i++){
        unsigned char bytes[MAX_UNIT_BYTES];unsigned int n=0;int rc=unit(api,keys[i],bytes,&n);
        if(rc<0)return -1;
        if(i>=4 && (rc!=1 || n!=(i==7?4u:1u)))return -1;
        if(i==3 && n!=1)rc=0; /* Original bounded 1B read fails on a larger unit. */
        if(rc==1)next.read_mask|=1u<<i;else next.default_mask|=1u<<i;
        if(i==0 && rc==1)next.initial[0]=bytes[0]==2?6:5;
        else if(i==1 && rc==1)memcpy(next.initial+1,bytes,n<16?n:16);
        else if(i==2){
            if(rc==1)memcpy(next.config+8,bytes,n<28?n:28);
            else {if(!fallback)return -1;memcpy(next.config+8,fallback,28);}
        }else if(i==3 && rc==1)next.key_10704fd=bytes[0];
        else if(i==4)next.flag_9a0009=bytes[0]!=0;
        else if(i==5)next.flag_9a000a=bytes[0]!=0;
        else if(i==6)next.byte_9a000b=bytes[0];
        else if(i==7)next.delay_9a000c=u32(bytes);
    }
    *out=next;return 0;
}
