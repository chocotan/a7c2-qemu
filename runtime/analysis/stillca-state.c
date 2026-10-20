/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "stillca-state.h"
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include <unistd.h>
static int read_at(FILE *mem,unsigned long address,void *out,unsigned long bytes){
    return address<=LONG_MAX && pread(fileno(mem),out,bytes,(long)address)==(ssize_t)bytes;
}
static int once(FILE *mem,unsigned long fp,unsigned long base,struct stillca_state *s){
    unsigned long mutex,vtable;unsigned char fields[11];
    memset(s,0,sizeof *s);
    if(fp>LONG_MAX-0x88 || !read_at(mem,fp+0x70,&s->object,8) ||
       !read_at(mem,fp+0x80,&mutex,8) || s->object<0x10000 || s->object>LONG_MAX-0x430 ||
       mutex!=s->object+0x2a0 || !read_at(mem,s->object,&vtable,8) ||
       vtable!=base+0x5b47d38UL || !read_at(mem,s->object+0x3cc,&s->initialized,1) ||
       !read_at(mem,s->object+0x425,fields,sizeof fields))return 0;
    s->completion0=fields[0];s->completion1=fields[1];s->initial_arrived=fields[2];
    memcpy(&s->slot0,fields+3,4);memcpy(&s->slot1,fields+7,4);return 1;
}
int read_stillca_state(void *mem,unsigned long fp,unsigned long base,struct stillca_state *out){
    struct stillca_state a,b;
    if(!mem || !out || !base || base>ULONG_MAX-0x5b47d38UL ||
       !once(mem,fp,base,&a) || !once(mem,fp,base,&b) || memcmp(&a,&b,sizeof a))return 0;
    *out=a;return 1;
}
