/* SPDX-License-Identifier: MIT */
#include "capture-input.c"
#include <assert.h>
#include <signal.h>
#include <stdio.h>
#include <sys/wait.h>

int main(int argc, char **argv) {
    assert(argc==2);
    FILE *f=fopen(argv[1],"rb");assert(f);
    assert(!fseek(f,0,SEEK_END));long count=ftell(f);assert(count>96);
    rewind(f);uint8_t *frame=malloc((size_t)count);assert(frame);
    assert(fread(frame,1,(size_t)count,f)==(size_t)count);assert(!fclose(f));
    uint8_t request[16]={5,0,0x38,0x40,29,0,0,0,2};
    uint8_t parameters[128];memset(parameters,0xa5,sizeof parameters);parameters[0x63]=8;
    struct capture_input *c=NULL,*other=NULL;
    assert(capture_input_create(frame,(size_t)count,request,parameters,&c)==0);
    struct capture_input_info info;assert(capture_input_info(c,&info)==0);
    assert(info.request_fnv1a64==fnv(request,16) && info.request_fnv1a64==get64(frame+88) &&
        info.request_cookie==get32(request+4) && info.request_trigger==request[8]);
    assert(info.metadata_alias!=info.metadata_cpu && info.pixel_alias!=info.pixel_cpu &&
        info.pixel_bytes==(size_t)count-96 && info.source_fnv1a64==fnv(frame+96,info.pixel_bytes) &&
        !memcmp((const void *)info.pixel_cpu,frame+96,info.pixel_bytes));
    assert(capture_input_create(frame,(size_t)count,request,parameters,&other)==0);
    struct capture_input_info other_info;assert(capture_input_info(other,&other_info)==0);
    assert(info.metadata_unit!=other_info.metadata_unit && info.pixel_unit!=other_info.pixel_unit &&
        info.metadata_alias!=other_info.metadata_alias);
    const uint8_t *p=(const void *)info.parameter_cpu;
    assert(get32(p+8)==0 && get32(p+12)==info.metadata_unit && get64(p+0x18)==info.metadata_alias &&
        !get64(p+0x20) && get32(p+0x30)==0 && get32(p+0x34)==info.pixel_unit && !get64(p+0x48));
    for(unsigned i=0;i<128;++i)
        if(!((i>=8 && i<16) || (i>=0x18 && i<0x28) || (i>=0x30 && i<0x38) ||
             (i>=0x48 && i<0x50) || (i>=0x54 && i<0x60))) assert(p[i]==parameters[i]);
    struct capture_input_mapping metadata, pixels, attachment;
    assert(capture_input_hold(c,&attachment)==0);
    assert(capture_input_destroy(c)==-EBUSY);
    assert(capture_input_metadata_read(c,info.metadata_unit,0,1024,&metadata)==-ENODATA);
    assert(capture_input_map(c,info.metadata_alias,1024,1,0x29,&metadata)==-ENOTSUP);
    assert(capture_input_map(c,info.metadata_alias,1024,0,29,&metadata)==-ENOTSUP);
    assert(capture_input_map(c,info.metadata_alias+1,1024,0,0x29,&metadata)==-ERANGE);
    assert(capture_input_map(c,info.metadata_cpu,1024,0,0x29,&metadata)==-ERANGE);
    assert(capture_input_map(c,info.metadata_alias,1024,0,0x29,&metadata)==0);
    memset((void *)metadata.address,0x3c,metadata.bytes);
    for(size_t i=0;i<metadata.bytes;++i)assert(((uint8_t *)info.metadata_cpu)[i]==0x3c);
    assert(capture_input_pixels(c,info.pixel_unit,0,info.pixel_bytes,&pixels)==0);
    assert(capture_input_destroy(c)==-EBUSY);
    assert(capture_input_unmap(other,&metadata)==-ESTALE);
    assert(capture_input_unmap(c,&pixels)==-ESTALE);
    assert(capture_input_release_pixels(c,&metadata)==-ESTALE);
    assert(capture_input_unmap(c,&metadata)==0);
    assert(capture_input_unmap(c,&metadata)==-ESTALE);
    assert(capture_input_destroy(c)==-EBUSY);
    assert(!memcmp((const void *)pixels.address,frame+96,pixels.bytes));
    assert(capture_input_release_pixels(c,&pixels)==0);
    assert(capture_input_seal_metadata(c)==0);
    assert(capture_input_metadata_read(c,info.metadata_unit,0,1024,&metadata)==0);
    assert(capture_input_seal_metadata(c)==-EBUSY);
    assert(capture_input_map(c,info.metadata_alias,1024,0,0x29,&pixels)==-EBUSY);
    assert(capture_input_unmap(c,&metadata)==-ESTALE);
    assert(capture_input_release_metadata(c,&metadata)==0);
    assert(capture_input_release_metadata(c,&metadata)==-ESTALE);
    assert(capture_input_pixels(c,info.pixel_unit,0,info.pixel_bytes,&pixels)==0);
    assert(capture_input_map(c,info.metadata_alias,1024,0,0x29,&metadata)==-EBUSY);
    assert(capture_input_release_pixels(c,&pixels)==0);
    struct capture_input_mapping slots[SLOTS-1];
    for(unsigned i=0;i<SLOTS-1;++i)assert(capture_input_map(c,info.metadata_alias,1024,0,0x29,&slots[i])==0);
    assert(capture_input_map(c,info.metadata_alias,1024,0,0x29,&metadata)==-ENOSPC);
    for(unsigned i=0;i<SLOTS-1;++i)assert(capture_input_unmap(c,&slots[i])==0);
    pid_t child=fork();assert(child>=0);
    if(!child) {
        struct capture_input_info fork_info;
        _exit(capture_input_info(c,&fork_info)==-ECHILD && capture_input_destroy(c)==-ECHILD?0:1);
    }
    int status;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));
    FILE *maps=fopen("/proc/self/maps","r");assert(maps);char line[512],perms[5];int found=0;
    while(fgets(line,sizeof line,maps)) {
        unsigned long lo,hi;
        if(sscanf(line,"%lx-%lx %4s",&lo,&hi,perms)==3) {
            unsigned matched=(info.pixel_cpu>=lo && info.pixel_cpu<hi ? 1u : 0u) |
                (info.parameter_cpu>=lo && info.parameter_cpu<hi ? 2u : 0u);
            if(matched) { assert(perms[0]=='r' && perms[1]=='-');found|=(int)matched; }
        }
    }
    assert(!fclose(maps) && found==3);
    assert(capture_input_drop(c,&attachment)==0);
    assert(capture_input_drop(c,&attachment)==-ESTALE);
    assert(capture_input_destroy(c)==0);c=NULL;
    frame[96]^=1;
    assert(capture_input_create(frame,(size_t)count,request,parameters,&c)==-EBADMSG && !c);
    frame[96]^=1;
    parameters[0x63]=0;
    assert(capture_input_create(frame,(size_t)count,request,parameters,&c)==-ENOTSUP && !c);
    assert(capture_input_destroy(other)==0);
    free(frame);puts("PASS actual-model17-RGB native-input-owner mapping-and-lifetime");return 0;
}
