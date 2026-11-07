/* SPDX-License-Identifier: MIT */
#include "hdmi-cold-settings.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static const unsigned int keys[8]={0x010d008d,0x003e0005,0x009a0001,0x010704fd,
                                  0x009a0009,0x009a000a,0x009a000b,0x009a000c};
static struct item {unsigned int size,changed_size,reads,queries,read_error;unsigned char data[32];} items[8];
static unsigned int index_of(unsigned int key){for(unsigned int i=0;i<8;i++)if(keys[i]==key)return i;assert(0);return 0;}
static unsigned int get_size(unsigned int key){struct item *v=&items[index_of(key)];v->queries++;return v->reads && v->changed_size?v->changed_size:v->size;}
static unsigned int nread(unsigned int key,void *out,int n){
    struct item *v=&items[index_of(key)];assert(n>0 && n<=32 && (unsigned int)n==v->size);v->reads++;
    if(v->read_error)return v->read_error;memcpy(out,v->data,(unsigned int)n);return (unsigned int)n;
}
static const struct hdmi_backup_api api={get_size,nread,0};
static void reset(void){
    memset(items,0,sizeof items);for(unsigned int i=0;i<8;i++)items[i].size=1;
    items[0].data[0]=2;items[1].size=16;memcpy(items[1].data,"ILCE-7CM2",9);
    items[2].size=10;for(unsigned int i=0;i<10;i++)items[2].data[i]=(unsigned char)(0x31+i);
    items[3].data[0]=1;items[5].data[0]=1;
    items[7].size=4;memcpy(items[7].data,(unsigned char[]){0xe0,0x93,4,0},4);
}
static void refused_unchanged(void){
    struct hdmi_cold_settings out;memset(&out,0xa5,sizeof out);unsigned char before[sizeof out];memcpy(before,&out,sizeof out);
    assert(hdmi_cold_settings_read(&api,0,&out)==-1 && !memcmp(before,&out,sizeof out));
}
int main(void){
    reset();struct hdmi_cold_settings out;assert(!hdmi_cold_settings_read(&api,0,&out));
    assert(out.initial[0]==6 && !memcmp(out.initial+1,"ILCE-7CM2",9) && !out.initial[17]);
    assert(out.read_mask==255 && !out.default_mask && !memcmp(out.config+8,items[2].data,10));
    for(unsigned int i=18;i<36;i++)assert(!out.config[i]);
    assert(out.key_10704fd==1 && !out.flag_9a0009 && out.flag_9a000a==1 && !out.byte_9a000b && out.delay_9a000c==300000);
    for(unsigned int i=0;i<8;i++)assert(items[i].reads==1 && items[i].queries==2);
    reset();items[2].size=0xffffffffu;refused_unchanged();
    unsigned char fallback[28];memset(fallback,0x5a,28);
    assert(!hdmi_cold_settings_read(&api,fallback,&out) && !memcmp(out.config+8,fallback,28) && (out.default_mask&4));
    reset();items[0].size=items[1].size=items[3].size=0xffffffffu;
    assert(!hdmi_cold_settings_read(&api,0,&out) && out.initial[0]==5 && !out.initial[1] && out.key_10704fd==1);
    for(unsigned int i=4;i<8;i++){reset();items[i].size=0xffffffffu;refused_unchanged();}
    reset();items[2].size=257;refused_unchanged();
    reset();items[2].changed_size=11;refused_unchanged();
    reset();items[2].read_error=9;refused_unchanged();
    reset();items[7].size=3;refused_unchanged();
    reset();items[3].size=2;assert(!hdmi_cold_settings_read(&api,0,&out) && out.key_10704fd==1 && (out.default_mask&8));
    reset();struct hdmi_backup_api writable=api;unsigned char saved[sizeof writable];memcpy(saved,&writable,sizeof writable);
    assert(hdmi_cold_settings_read(&writable,0,(struct hdmi_cold_settings *)(void *)&writable)==-1 && !memcmp(saved,&writable,sizeof writable));
    puts("HDMI_NATIVE_BACKUP_SIZE_BOUNDED_READ_FALLBACK_AND_REQUIRED_FIELDS_PASS");return 0;
}
#ifdef HDMI_HPD_ORIGINAL_ABI
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
static int abi_main(int argc,char **argv){(void)argc;(void)argv;return main();}
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl abi_entry\nbrk #0\n");
__attribute__((noreturn)) void abi_entry(unsigned long *stack){
    __libc_start_main(abi_main,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
#endif
