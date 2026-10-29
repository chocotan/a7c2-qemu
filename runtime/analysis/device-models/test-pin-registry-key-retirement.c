/* SPDX-License-Identifier: MIT */
#include "pin-registry-core.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#define SOURCE 0x90590818u
#define DESTINATION 0x81b10101u
static const unsigned int keys[2][3]={{0,2,0},{0,2,1}};
static const unsigned int hdmi_keys[2][3]={{4,1,0},{5,1,0}};
static struct pin_registry_owner owner={.source=SOURCE,.count=2,.name="KEY_TEST",.keys=keys};
struct message {unsigned int owner,source,bytes,live;unsigned char data[56];};
static struct message pool[3];
static void *queued,*attempted;
static int send_error,free_error;
static unsigned int release_calls;
static void put32(unsigned char *p,unsigned int v){for(unsigned int i=0;i<4;i++)p[i]=(unsigned char)(v>>(8*i));}
static unsigned int get32(const unsigned char *p){return p[0]|(unsigned int)p[1]<<8|(unsigned int)p[2]<<16|(unsigned int)p[3]<<24;}
static struct message *header(void *p){
    for(unsigned int i=0;i<3;i++)if(pool[i].data==p)return &pool[i];
    assert(0);return 0;
}
static int allocate(unsigned int dst,void **out,unsigned int bytes,unsigned int wait){
    assert(bytes==56 && wait==1);
    for(unsigned int i=0;i<3;i++)if(!pool[i].live){
        pool[i]=(struct message){.owner=dst,.bytes=bytes,.live=1};*out=pool[i].data;return 0;
    }
    assert(0);return -1;
}
static int release(unsigned int dst,void *p){
    struct message *m=header(p);assert(m->live && m->owner==dst);release_calls++;
    if(m->bytes==56 && free_error)return free_error;
    m->live=0;memset(m->data,0xdd,sizeof m->data);return 0;
}
static unsigned int size(void *p){assert(header(p)->live);return header(p)->bytes;}
static unsigned int source(void *p){assert(header(p)->live);return header(p)->source;}
static void set_source(void *p,unsigned int sid){assert(header(p)->live);header(p)->source=sid;}
static int send(unsigned int dst,void *p){
    assert(header(p)->live && header(p)->owner==dst && source(p)==owner.source && size(p)==56);
    attempted=p;if(send_error)return send_error;
    assert(!queued);queued=p;return 0;
}
static const struct full_imaging_io io={allocate,release,set_source,send,size,source,0};
static struct full_vef_snapshot snapshot(void){struct full_vef_snapshot s;pin_registry_snapshot(&owner,&s);return s;}
static void *request(const unsigned int key[4]){
    struct message *m=0;for(unsigned int i=0;i<3;i++)if(!pool[i].live){m=&pool[i];break;}assert(m);
    *m=(struct message){.owner=owner.source,.source=0x81b10102u,.bytes=48,.live=1};unsigned char *p=m->data;
    put32(p,DESTINATION);put32(p+4,0xa0a0a0a0);p[8]=1;p[10]=48;put32(p+12,24);put32(p+16,48);
    p[25]=0x10;p[28]=24;p[30]=2;for(unsigned int i=0;i<4;i++)put32(p+32+4*i,key[i]);return p;
}
static void query(const unsigned int key[4]){
    void *p=request(key);int rc=123;assert(!queued);
    assert(pin_registry_dispatch(&owner,owner.source,p,&io,1,&rc) && !rc && !header(p)->live && queued);
    assert(get32(queued)==owner.reply_sid && get32((unsigned char *)queued+48)==owner.source);
    assert(!get32((unsigned char *)queued+52));
}
static int retire(unsigned int dst){
    int rc=123;assert(queued && pin_registry_release(&owner,dst,queued,release,0,&rc));
    if(!rc)queued=0;
    return rc;
}
static void *foreign_free(void *unused){(void)unused;assert(!retire(DESTINATION));return 0;}
int main(int argc,char **argv){
    assert(argc==2);alarm(10);const char *name=argv[1];
    unsigned int selected[4]={0,2,0,SOURCE},other[4]={0,2,1,SOURCE};
    assert(!pin_registry_key_get_retired(&owner,selected));
    if(!strcmp(name,"selected-key")){
        for(unsigned int i=0;i<6;i++){query(other);assert(!retire(DESTINATION));}
        assert(snapshot().queries==6 && snapshot().waiter_freed==6 && pin_registry_key_get_retired(&owner,other));
        assert(!pin_registry_key_get_retired(&owner,selected));query(selected);
        assert(!pin_registry_key_get_retired(&owner,selected) && snapshot().live_replies==1);
        assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
        for(unsigned int i=0;i<4;i++){
            unsigned int wrong[4];memcpy(wrong,selected,sizeof wrong);wrong[i]^=0x10000;
            assert(!pin_registry_key_get_retired(&owner,wrong));
        }
        query(selected);assert(pin_registry_key_get_retired(&owner,selected) && snapshot().live_replies==1);
        assert(!retire(DESTINATION));
    }else if(!strcmp(name,"low-byte-alias")){
        unsigned int alias[4]={0x10000,0x20002,0x30000,SOURCE};query(alias);
        for(unsigned int i=0;i<3;i++)assert(get32((unsigned char *)queued+32+4*i)==alias[i]);
        assert(!retire(DESTINATION) && snapshot().waiter_freed==1);
        assert(!pin_registry_key_get_retired(&owner,selected) && !pin_registry_key_get_retired(&owner,alias));
        query(selected);assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"hdmi-type-only")){
        owner.source=0x909a015au;owner.keys=hdmi_keys;owner.type_only=1;
        unsigned int input[4]={5,0x12345678,0xffffffff,owner.source},canonical[4]={5,1,0,owner.source};
        query(input);for(unsigned int i=0;i<3;i++)assert(get32((unsigned char *)queued+32+4*i)==canonical[i]);
        assert(!pin_registry_key_get_retired(&owner,canonical));assert(!retire(DESTINATION));
        assert(pin_registry_key_get_retired(&owner,canonical) && !pin_registry_key_get_retired(&owner,input));
    }else if(!strcmp(name,"full-key")){
        owner.full_key_match=1;owner.reply_sid=SOURCE;
        unsigned int alias[4]={0x10000,2,0,SOURCE};void *p=request(alias);int rc=123;
        assert(pin_registry_dispatch(&owner,owner.source,p,&io,1,&rc) && rc==-1021 && !queued && header(p)->live);
        assert(!pin_registry_key_get_retired(&owner,selected));assert(!release(owner.source,p));
        query(selected);assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"wrong-destination") || !strcmp(name,"failed-free")){
        query(selected);unsigned int calls=release_calls;
        if(!strcmp(name,"failed-free")){free_error=-61;assert(retire(DESTINATION)==-61 && release_calls==calls+1);}
        else assert(retire(DESTINATION+1)==-1021 && release_calls==calls);
        assert(header(queued)->live && snapshot().faults==1 && snapshot().live_replies==1);
        assert(!pin_registry_key_get_retired(&owner,selected));free_error=0;assert(!retire(DESTINATION));
        assert(!pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"foreign-thread")){
        query(selected);pthread_t thread;assert(!pthread_create(&thread,0,foreign_free,0));assert(!pthread_join(thread,0));
        assert(snapshot().native_freed==1 && !snapshot().waiter_freed && !snapshot().faults);
        assert(!pin_registry_key_get_retired(&owner,selected));
        query(selected);assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"send-failed")){
        send_error=-60;void *p=request(selected);int rc=123;
        assert(pin_registry_dispatch(&owner,owner.source,p,&io,1,&rc) && rc==-60 && !queued && header(p)->live);
        assert(attempted && !header(attempted)->live && !snapshot().queries && !snapshot().live_replies);
        assert(!pin_registry_key_get_retired(&owner,selected));rc=123;
        assert(!pin_registry_release(&owner,DESTINATION,attempted,release,0,&rc) && rc==123);
        assert(!release(owner.source,p));send_error=0;query(selected);
        assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"reset")){
        query(selected);assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
        pin_registry_test_reset(&owner);assert(!pin_registry_key_get_retired(&owner,selected));
        query(other);assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,other));
        assert(!pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"invalid-owner")){
        assert(!pin_registry_key_get_retired(0,selected) && !pin_registry_key_get_retired(&owner,0));
        query(selected);assert(!retire(DESTINATION));
        owner.count=FULL_PIN_REGISTRY_CAPACITY+1;owner.state.registry_objects=owner.count;
        assert(!pin_registry_key_get_retired(&owner,selected));owner.count=0;owner.state.registry_objects=0;
        assert(!pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"faulted-owner")){
        query(selected);assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected));
        owner.state.faults=1;assert(!pin_registry_key_get_retired(&owner,selected));
    }else if(!strcmp(name,"wrong-registry")){
        struct pin_registry_owner foreign={.source=SOURCE,.count=2,.name="FOREIGN",.keys=keys};
        pin_registry_test_set_state(&foreign,0,1);query(selected);int rc=123;unsigned int calls=release_calls;
        assert(!pin_registry_release(&foreign,DESTINATION,queued,release,0,&rc) && rc==123 && release_calls==calls);
        assert(header(queued)->live && !pin_registry_key_get_retired(&foreign,selected) && !pin_registry_key_get_retired(&owner,selected));
        assert(!retire(DESTINATION) && pin_registry_key_get_retired(&owner,selected) && !pin_registry_key_get_retired(&foreign,selected));
    }else assert(0);
    assert(!queued);for(unsigned int i=0;i<3;i++)assert(!pool[i].live);
    puts("PIN_REGISTRY_EXACT_KEY_RETIREMENT_HOST_TEST_PASS");return 0;
}
