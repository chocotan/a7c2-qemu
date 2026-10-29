/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "adf-public-config.h"
#include <errno.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static const struct { unsigned long source; unsigned int destination; } aip_map[] = {
#include "adf-aip-backup-map.inc"
};

static int identity(const struct full_adf_public_config *c)
{
    if (!(c && c->known==1 && c->bytes==FULL_ADF_PUBLIC_SEED_BYTES &&
        c->fnv==FULL_ADF_PUBLIC_SEED_FNV && c->pin_immediately==1 &&
        c->system_selector==0x20 && c->output_source==1 && c->prelude_flag==1 &&
        !c->key690219 && !c->key690227 && !c->key690228 && !c->key6902a8 && !c->key6902f1)) return 0;
    unsigned long long fnv=0xcbf29ce484222325ULL;
    for (unsigned int i=0;i<FULL_ADF_AIP_BACKUP_BYTES;i++) fnv=(fnv^c->aip_values[i])*0x100000001b3ULL;
    for (unsigned int i=0;i<FULL_ADF_AIP_BACKUP_BYTES;i++) fnv=(fnv^c->aip_known[i])*0x100000001b3ULL;
    return fnv==0x5a1ab318aea2e5f8ULL;
}
static unsigned int le32(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1]<<8 | (unsigned int)p[2]<<16 | (unsigned int)p[3]<<24;
}
int full_adf_public_config_load(struct full_adf_public_config *out,int fd)
{
    if (!out) return -1021;
    const unsigned char *old=(const unsigned char *)out;
    for (unsigned long i=0;i<sizeof *out;i++) if (old[i]) return -1021;
    struct stat st;
    if (syscall(SYS_fstat,fd,&st) || !S_ISREG(st.st_mode) || st.st_size!=(off_t)FULL_ADF_PUBLIC_SEED_BYTES) return -1021;
    unsigned char buffer[4096],pin=0,prelude=0,selector[4]={0},source[4]={0};
    unsigned char input219=0xff,input227=0xff,input228=0xff,input2a8=0xff,input2f1=0xff;
    unsigned char aip_values[FULL_ADF_AIP_BACKUP_BYTES],aip_known[FULL_ADF_AIP_BACKUP_BYTES]={0};
    memset(aip_values,0xa5,sizeof aip_values);
    unsigned long offset=0,map_index=0;
    unsigned long long fnv=0xcbf29ce484222325ULL;
    /* FNV checks the guest readback; host SHA256 and both BK4 checksums remain mandatory. */
    while (offset<FULL_ADF_PUBLIC_SEED_BYTES) {
        unsigned long wanted=FULL_ADF_PUBLIC_SEED_BYTES-offset;
        if (wanted>sizeof buffer) wanted=sizeof buffer;
        ssize_t got=pread(fd,buffer,wanted,(off_t)offset);
        if (got<0 && errno==EINTR) continue;
        if (got<=0 || (unsigned long)got>wanted) return -1021;
        for (unsigned long i=0;i<(unsigned long)got;i++) {
            unsigned long at=offset+i;unsigned char byte=buffer[i];
            fnv=(fnv^byte)*0x100000001b3ULL;
            while (map_index<sizeof aip_map/sizeof *aip_map && aip_map[map_index].source==at) {
                unsigned int destination=aip_map[map_index].destination;
                if (destination>=FULL_ADF_AIP_BACKUP_BYTES || aip_known[destination]) return -1021;
                aip_values[destination]=byte;aip_known[destination]=0xff;map_index++;
            }
            if (at==0x1331d0UL) pin=byte;
            if (at==0x132f7dUL) prelude=byte;
            if (at==0x14d1b9UL) input219=byte;
            if (at==0x14d205UL) input227=byte;
            if (at==0x14d206UL) input228=byte;
            if (at==0x14d298UL) input2a8=byte;
            if (at==0x14d2e1UL) input2f1=byte;
            if (at>=0x133b50UL && at<0x133b54UL) selector[at-0x133b50UL]=byte;
            if (at>=0x152b2cUL && at<0x152b30UL) source[at-0x152b2cUL]=byte;
        }
        offset+=(unsigned long)got;
    }
    if (map_index!=362 || sizeof aip_map/sizeof *aip_map!=362) return -1021;
    unsigned char extra;
    if (syscall(SYS_fstat,fd,&st) || st.st_size!=(off_t)FULL_ADF_PUBLIC_SEED_BYTES ||
        pread(fd,&extra,1,(off_t)FULL_ADF_PUBLIC_SEED_BYTES)!=0) return -1021;
    struct full_adf_public_config next={.known=1,.pin_immediately=pin,.system_selector=le32(selector),
        .output_source=le32(source),.prelude_flag=prelude,.key690219=input219,.key690227=input227,
        .key690228=input228,.key6902a8=input2a8,.key6902f1=input2f1,.bytes=offset,.fnv=fnv};
    memcpy(next.aip_values,aip_values,sizeof aip_values);
    memcpy(next.aip_known,aip_known,sizeof aip_known);
    if (!identity(&next)) return -1021;
    *out=next;
    return 0;
}
int full_adf_public_config_read(struct full_adf_public_config *c,unsigned int key,unsigned int *out)
{
    if (!out || !identity(c) || c->queries==~0ULL) return -1021;
    unsigned int value;
    switch (key) {
    case 0x58014a:value=c->pin_immediately;break;
    case 0x5e028a:value=c->system_selector;break;
    case 0xf900d2:value=c->output_source;break;
    case 0x58007b:value=c->prelude_flag;break;
    case 0x690219:value=c->key690219;break;
    case 0x690227:value=c->key690227;break;
    case 0x690228:value=c->key690228;break;
    case 0x6902a8:value=c->key6902a8;break;
    case 0x6902f1:value=c->key6902f1;break;
    default:return -1021;
    }
    *out=value;c->queries++;
    return 0;
}
int full_adf_public_config_aip_read(struct full_adf_public_config *c,unsigned int offset,
                                    unsigned int mask,unsigned int *out)
{
    if (!out || !mask || !identity(c) || c->queries==~0ULL) return -1021;
    for (unsigned int i=0;i<4;i++) {
        if (!((mask>>(8*i))&0xff)) continue;
        if (offset>=FULL_ADF_AIP_BACKUP_BYTES || i>=FULL_ADF_AIP_BACKUP_BYTES-offset ||
            c->aip_known[offset+i]!=0xff) return -1021;
    }
    unsigned int value=0;
    for (unsigned int i=0;i<4;i++) {
        if ((mask>>(8*i))&0xff) value|=((unsigned int)c->aip_values[offset+i]<<(8*i))&mask;
    }
    *out=value;c->queries++;
    return 0;
}
