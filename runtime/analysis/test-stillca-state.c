/* SPDX-License-Identifier: MIT */
#include "stillca-state.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static void put(FILE *f,long address,const void *p,unsigned long size){
    assert(!fseek(f,address,SEEK_SET) && fwrite(p,size,1,f)==1 && !fflush(f));
}
int main(void){
    FILE *f=tmpfile();assert(f);unsigned long fp=0x100,base=0x10000000,object=0x10000;
    unsigned long mutex=object+0x2a0,vtable=base+0x5b47d38;
    unsigned char fields[11]={1,0,1,2,0,0,0,0,0,0,0},initialized=0;
    put(f,fp+0x70,&object,8);put(f,fp+0x80,&mutex,8);put(f,object,&vtable,8);
    put(f,object+0x3cc,&initialized,1);put(f,object+0x425,fields,sizeof fields);
    struct stillca_state s;assert(read_stillca_state(f,fp,base,&s));
    assert(s.object==object && !s.initialized && s.initial_arrived==1 && s.completion0==1 && !s.completion1 && s.slot0==2 && !s.slot1);
    mutex++;put(f,fp+0x80,&mutex,8);assert(!read_stillca_state(f,fp,base,&s));
    mutex--;put(f,fp+0x80,&mutex,8);vtable++;put(f,object,&vtable,8);
    assert(!read_stillca_state(f,fp,base,&s));vtable--;put(f,object,&vtable,8);
    assert(!read_stillca_state(f,fp,0,&s));assert(!read_stillca_state(f,~0UL,base,&s));
    fclose(f);f=tmpfile();assert(f);assert(!read_stillca_state(f,fp,base,&s));fclose(f);
    puts("STILLCA_READ_ONLY_OBJECT_MUTEX_VTABLE_AND_TRUNCATION_CHECKS_PASS");return 0;
}
