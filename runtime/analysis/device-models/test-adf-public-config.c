/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "adf-public-config.h"
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void aip_rejected(struct full_adf_public_config *config,unsigned int offset,unsigned int mask)
{
    struct full_adf_public_config before=*config;
    unsigned int value=0xdecafbad;
    assert(full_adf_public_config_aip_read(config,offset,mask,&value)==-1021);
    assert(value==0xdecafbad && !memcmp(config,&before,sizeof *config));
}
static void aip_view_tests(const struct full_adf_public_config *loaded)
{
    struct full_adf_public_config config=*loaded;
    const unsigned int holes[]={1,5,9,62,63,65,66,67,82,83,120,121,122,123,136,137,138,139,
        163,171,223,235,239,290,291,324,326,332,334,350,366};
    unsigned int count=0;
    for(unsigned int i=0;i<FULL_ADF_AIP_BACKUP_BYTES;i++) {
        assert(config.aip_known[i]==0 || config.aip_known[i]==0xff);
        count+=config.aip_known[i]==0xff;
    }
    assert(count==362);
    for(unsigned int i=0;i<sizeof holes/sizeof *holes;i++) {
        assert(config.aip_known[holes[i]]==0 && config.aip_values[holes[i]]==0xa5);
        aip_rejected(&config,holes[i],0xff);
        config.aip_values[holes[i]]=0;
        aip_rejected(&config,0,0xff);
        config=*loaded;
    }
    const struct {unsigned int offset,mask,value;} reads[]={
        {0,0xff,0x80},{0x40,0xff,1},{0x120,0xff,0x15},{0x188,0xff,0},
        {0,0x00ff00ff,0x80},{2,0x00ffffff,0x00800000},{0,0x7f,0},{0,0x80,0x80},
        {0,0x00ff00f0,0x80},{390,0x00ffffff,0}
    };
    for(unsigned int i=0;i<sizeof reads/sizeof *reads;i++) {
        unsigned int value=0xdecafbad;
        assert(!full_adf_public_config_aip_read(&config,reads[i].offset,reads[i].mask,&value));
        assert(value==reads[i].value && config.queries==loaded->queries+i+1);
    }
    unsigned long long queries=config.queries;
    unsigned int value=0xdecafbad;
    assert(!full_adf_public_config_read(&config,0x690227,&value) && value==0 && config.queries==queries+1);
    aip_rejected(&config,0,0);
    aip_rejected(&config,0,0x00ffffff);
    aip_rejected(&config,2,0xffffffff);
    aip_rejected(&config,392,0xffff);
    aip_rejected(&config,392,0xff000000);
    aip_rejected(&config,393,0xff);
    aip_rejected(&config,~0U,0xff);
    aip_rejected(&config,~0U-1,0xff000000);
    struct full_adf_public_config before=config;
    assert(full_adf_public_config_aip_read(&config,0,0xff,0)==-1021);
    assert(!memcmp(&config,&before,sizeof config));
    value=0xdecafbad;
    assert(full_adf_public_config_aip_read(0,0,0xff,&value)==-1021 && value==0xdecafbad);
    config.queries=~0ULL;
    aip_rejected(&config,0,0xff);
    for(unsigned int i=0;i<FULL_ADF_AIP_BACKUP_BYTES;i++) {
        config=*loaded;config.aip_values[i]^=1;
        aip_rejected(&config,0,0xff);
        value=0xdecafbad;
        assert(full_adf_public_config_read(&config,0x58014a,&value)==-1021 && value==0xdecafbad);
        config=*loaded;config.aip_known[i]^=0xff;
        aip_rejected(&config,0,0xff);
        assert(full_adf_public_config_read(&config,0x58014a,&value)==-1021 && value==0xdecafbad);
    }
    struct full_adf_public_config empty={0};
    aip_rejected(&empty,0,0xff);
    fputs("ADF_AIP_VALUES=",stdout);
    for(unsigned int i=0;i<FULL_ADF_AIP_BACKUP_BYTES;i++) printf("%02x",loaded->aip_values[i]);
    fputs("\nADF_AIP_KNOWN=",stdout);
    for(unsigned int i=0;i<FULL_ADF_AIP_BACKUP_BYTES;i++) printf("%02x",loaded->aip_known[i]);
    puts("\nADF_PUBLIC_CONFIG_AIP_MASKED_READ_TAMPER_BOUNDARIES_PASS");
}
int main(int argc,char **argv)
{
    assert(argc==3);
    int fd=open(argv[1],O_RDONLY);assert(fd>=0);
    struct full_adf_public_config config={0};
    assert(lseek(fd,17,SEEK_SET)==17);
    assert(!full_adf_public_config_load(&config,fd) && lseek(fd,0,SEEK_CUR)==17);
    unsigned int value=99;
    assert(!full_adf_public_config_read(&config,0x58014a,&value) && value==1);
    assert(!full_adf_public_config_read(&config,0x5e028a,&value) && value==0x20);
    assert(!full_adf_public_config_read(&config,0xf900d2,&value) && value==1);
    assert(!full_adf_public_config_read(&config,0x58007b,&value) && value==1 && config.queries==4);
    aip_view_tests(&config);
    assert(config.queries==4);
    const unsigned int keys[5]={0x690219,0x690227,0x690228,0x6902a8,0x6902f1};
    for(unsigned int i=0;i<5;i++) {
        value=99;
        assert(!full_adf_public_config_read(&config,keys[i],&value) && value==0);
    }
    assert(config.queries==9);
    struct full_adf_public_config before=config;
    unsigned int *input_fields[5]={&config.key690219,&config.key690227,&config.key690228,&config.key6902a8,&config.key6902f1};
    for(unsigned int i=0;i<5;i++) {
        *input_fields[i]=1;value=99;
        assert(full_adf_public_config_read(&config,keys[i],&value)==-1021 && value==99 && config.queries==9);
        aip_rejected(&config,0,0xff);
        config=before;
        assert(full_adf_public_config_read(&config,keys[i]+0x2000,&value)==-1021 && value==99);
        assert(!memcmp(&config,&before,sizeof config));
    }
    value=99;
    assert(full_adf_public_config_read(&config,0x692227,&value)==-1021 && value==99);
    assert(!memcmp(&config,&before,sizeof config));
    assert(full_adf_public_config_read(&config,0,&value)==-1021 && value==99);
    assert(full_adf_public_config_read(&config,0x58014a,0)==-1021);
    assert(full_adf_public_config_load(&config,fd)==-1021 && !memcmp(&before,&config,sizeof config));
    config.pin_immediately=0;
    assert(full_adf_public_config_read(&config,0x58014a,&value)==-1021 && value==99);
    config=before;config.queries=~0ULL;
    assert(full_adf_public_config_read(&config,0x58014a,&value)==-1021 && value==99 && config.queries==~0ULL);
    puts("ADF_PUBLIC_CONFIG_ORIGINAL_KEYS_ACTUAL_READBACK_PASS");

    int bad=open(argv[2],O_CREAT|O_EXCL|O_RDWR,0600);assert(bad>=0);
    struct full_adf_public_config empty={0};config=empty;
    config.aip_values[1]=0xa5;before=config;
    assert(full_adf_public_config_load(&config,fd)==-1021 && !memcmp(&config,&before,sizeof config));
    config=empty;
    assert(full_adf_public_config_load(&config,bad)==-1021 && !memcmp(&config,&empty,sizeof config));
    assert(full_adf_public_config_load(&config,-1)==-1021 && !memcmp(&config,&empty,sizeof config));
    assert(full_adf_public_config_load(0,fd)==-1021);
    int pipes[2];assert(!pipe(pipes));
    assert(full_adf_public_config_load(&config,pipes[0])==-1021);
    close(pipes[0]);close(pipes[1]);
    char buffer[4096];unsigned long offset=0;
    while(offset<FULL_ADF_PUBLIC_SEED_BYTES) {
        unsigned long count=FULL_ADF_PUBLIC_SEED_BYTES-offset;
        if(count>sizeof buffer)count=sizeof buffer;
        assert(pread(fd,buffer,count,(off_t)offset)==(ssize_t)count);
        assert(write(bad,buffer,count)==(ssize_t)count);offset+=count;
    }
    unsigned char byte;
    assert(pread(bad,&byte,1,3000)==1);byte^=1;
    assert(pwrite(bad,&byte,1,3000)==1);
    assert(full_adf_public_config_load(&config,bad)==-1021 && !memcmp(&config,&empty,sizeof config));
    assert(!ftruncate(bad,(off_t)FULL_ADF_PUBLIC_SEED_BYTES+1));
    assert(full_adf_public_config_load(&config,bad)==-1021 && !memcmp(&config,&empty,sizeof config));
    assert(!ftruncate(bad,(off_t)FULL_ADF_PUBLIC_SEED_BYTES));
    byte^=1;assert(pwrite(bad,&byte,1,3000)==1);
    assert(!full_adf_public_config_load(&config,bad));
    assert(config.pin_immediately==1 && config.system_selector==0x20 && config.output_source==1 && config.prelude_flag==1);
    close(fd);close(bad);assert(!unlink(argv[2]));
    puts("ADF_PUBLIC_CONFIG_WRONG_CONTENT_LENGTH_OWNER_RELOAD_REJECTED_PASS");
    return 0;
}
