/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "hdmi-public-backup.h"
#include "adf-public-config.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static unsigned int le16(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8;}
static unsigned int le32(const unsigned char *p){return le16(p)|le16(p+2)<<16;}
int full_hdmi_public_backup_read(int fd,unsigned int key,void *out,unsigned int capacity,unsigned int *length){
    if(length)*length=0;
    if(!length || (capacity && !out))return -1021;
    if(key!=0x009a0001 && key!=0x009a0009 && key!=0x009a000a && key!=0x009a000b &&
       key!=0x009a000c && key!=0x010704fd)return -1021;
    struct stat st;
    if(syscall(SYS_fstat,fd,&st) || !S_ISREG(st.st_mode) || st.st_size!=FULL_ADF_PUBLIC_SEED_BYTES)return -1021;
    unsigned char *blob=malloc(FULL_ADF_PUBLIC_SEED_BYTES);
    if(!blob)return -1021;
    int result=-1021;unsigned long at=0;unsigned long long hash=0xcbf29ce484222325ULL;
    while(at<FULL_ADF_PUBLIC_SEED_BYTES){
        ssize_t got=pread(fd,blob+at,FULL_ADF_PUBLIC_SEED_BYTES-at,(off_t)at);
        if(got<0 && errno==EINTR)continue;
        if(got<=0 || (unsigned long)got>FULL_ADF_PUBLIC_SEED_BYTES-at)goto done;
        for(ssize_t i=0;i<got;i++)hash=(hash^blob[at+(unsigned long)i])*0x100000001b3ULL;
        at+=(unsigned long)got;
    }
    unsigned char extra;
    if(hash!=FULL_ADF_PUBLIC_SEED_FNV || syscall(SYS_fstat,fd,&st) ||
       st.st_size!=FULL_ADF_PUBLIC_SEED_BYTES || pread(fd,&extra,1,FULL_ADF_PUBLIC_SEED_BYTES)!=0)goto done;
    const unsigned int bank=0xed000,available=FULL_ADF_PUBLIC_SEED_BYTES-bank;
    const unsigned char *r=blob+bank;
    if(available<0x100 || memcmp(r+12,"BK4\0",4))goto done;
    unsigned int sections=le32(r+16),properties=le32(r+20),data=le32(r+24),bytes=le32(r+28);
    if(data>available || bytes>available-data || sections>(available-0x100)/6)goto done;
    unsigned int size=data+bytes,table=0x100+sections*6;
    if(table>data || properties>(data-table)/6)goto done;
    unsigned int sum=0;
    for(unsigned int i=0;i<size;i++)if(i<32 || i>=36)sum+=r[i];
    if(sum!=le32(r+32))goto done;
    unsigned int section=key>>16,index=key&0xffff;
    if(section>=sections){result=1;goto done;}
    const unsigned char *entry=r+0x100+section*6;
    unsigned int count=le16(entry),first=le32(entry+2);
    if(first>properties || count>properties-first)goto done;
    if(index>=count){result=1;goto done;}
    unsigned int pointer=le32(r+table+(first+index)*6+2);
    if(pointer==0xffffffffU){result=1;goto done;}
    unsigned int offset=pointer&0xffffff,n=pointer>>24,maximum=n;
    if(offset<data || offset>=size)goto done;
    if(!n || n==255){
        unsigned int prefix=n?2:4;
        if(prefix>size-offset)goto done;
        maximum=n?le16(r+offset):le16(r+offset+2);n=le16(r+offset);offset+=prefix;
    }
    if(n>maximum || maximum>size-offset)goto done;
    if(n && capacity)memcpy(out,r+offset,n<capacity?n:capacity);
    *length=n;result=0;
done:
    free(blob);return result;
}
