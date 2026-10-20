/* SPDX-License-Identifier: MIT */
#include "dmm-unit-config.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct block {unsigned int size,source,pool;unsigned char data[40];};
static struct block *header(void *p){return (void *)((char *)p - offsetof(struct block,data));}
static void *queued;static int send_error;static unsigned int token,requests,replies;
static unsigned int size(void *p){return header(p)->size;}
static unsigned int source(void *p){return header(p)->source;}
static void set_source(void *p,unsigned int id){header(p)->source=id;}
static int release(unsigned int id,void *p){assert(header(p)->pool==id);if(id==NATIVE_DMM_UNIT_SID)requests++;else replies++;free(header(p));return 0;}
static int allocate(unsigned int id,void **p,unsigned int bytes,unsigned int count){
    assert(id==0x81cf61c6 && bytes==40 && count==1);struct block *b=calloc(1,sizeof *b);assert(b);b->size=40;b->pool=id;*p=b->data;return 0;
}
static int send(unsigned int id,void *p){
    unsigned char expected[40]={0x18,0x80};expected[6]=(unsigned char)token;expected[7]=(unsigned char)(token>>8);
    expected[18]=0x60;expected[19]=9;
    assert(!queued && id==0x81cf61c6 && source(p)==NATIVE_DMM_UNIT_SID && !memcmp(p,expected,40));
    if(send_error)return send_error;
    queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static void *request(void){
    struct block *b=calloc(1,sizeof *b);assert(b);b->size=40;b->pool=NATIVE_DMM_UNIT_SID;b->source=0x81cf61c6;
    b->data[0]=0x18;b->data[4]=0x58;b->data[5]=0x0b;b->data[6]=5;
    b->data[20]=(unsigned char)token;b->data[21]=(unsigned char)(token>>8);return b->data;
}
int main(int argc,char **argv){
    assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);unsigned char *data=malloc(43509);assert(data);
    assert(fread(data,1,43509,f)==43508 && !ferror(f));fclose(f);
    assert(native_dmm_unit_bind(data,43507)==-1);data[0]^=1;
    assert(native_dmm_unit_bind(data,43508)==-1);data[0]^=1;
    assert(native_dmm_unit_bind(data,43508)==0);free(data);
    int rc=123;void *p=request();assert(!native_dmm_unit_dispatch(NATIVE_DMM_UNIT_SID,p,&io,0,&rc) && rc==123);
    release(NATIVE_DMM_UNIT_SID,p);
    for(unsigned int i=0;i<2;i++){
        token=i?0x1234:0;p=request();
        assert(native_dmm_unit_dispatch(NATIVE_DMM_UNIT_SID,p,&io,1,&rc) && !rc && queued);
        assert(native_dmm_unit_release(0x81cf61c6,queued,release,0,&rc) && !rc);queued=0;
    }
    for(unsigned int kind=0;kind<4;kind++){
        p=request();if(kind==0)((unsigned char *)p)[4]=0;
        if(kind==1)((unsigned char *)p)[8]=1;
        if(kind==2)header(p)->size=39;
        if(kind==3)header(p)->source=0;
        assert(native_dmm_unit_dispatch(NATIVE_DMM_UNIT_SID,p,&io,1,&rc) && rc==-1021 && !queued);
        release(NATIVE_DMM_UNIT_SID,p);
    }
    p=request();send_error=-66;assert(native_dmm_unit_dispatch(NATIVE_DMM_UNIT_SID,p,&io,1,&rc) && rc==-66 && !queued);
    send_error=0;release(NATIVE_DMM_UNIT_SID,p);
    assert(requests==8 && replies==3);
    puts("DMM_UNIT_ORIGINAL_CONFIG_EXTENT_SIZE_TOKEN_QUERY_OWNERSHIP_NO_ALLOCATION_PASS");return 0;
}
