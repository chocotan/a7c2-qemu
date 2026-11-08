/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "flash-core.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static unsigned char ram[A7PF_MAX_IO];
static int dma(void *unused, uint64_t addr, void *data, size_t bytes, bool write, bool probe)
{
    (void)unused;
    if (addr<0x40000000 || addr-0x40000000>sizeof(ram) || bytes>sizeof(ram)-(addr-0x40000000)) return EFAULT;
    if (!probe) {
        if (write) memcpy(ram+addr-0x40000000,data,bytes);
        else memcpy(data,ram+addr-0x40000000,bytes);
    }
    return 0;
}
static void put32(unsigned char *p, uint32_t x)
{ for (int i=0;i<4;i++) p[i]=x>>(8*i); }
static void put64(unsigned char *p, uint64_t x)
{ put32(p,x);put32(p+4,x>>32); }
static int fault;
static ssize_t broken_read(int fd,void *p,size_t n,off_t o)
{ if (fault==1) return n-1; errno=EIO; (void)fd;(void)p;(void)o;return -1; }
static ssize_t broken_write(int fd,const void *p,size_t n,off_t o)
{ if (fault==1) return n-1; errno=ENOSPC; (void)fd;(void)p;(void)o;return -1; }
static int broken_sync(int fd) { (void)fd;errno=EIO;return -1; }
static void op(struct a7pf *s,unsigned int op,int expected)
{
    a7pf_write_reg(s,0x14,op);
    assert(s->error==(unsigned int)expected);
    assert(s->status==(expected ? A7PF_FAILED : A7PF_DONE));
    if (expected) assert(s->actual==0 && s->geometry_size==0 && s->geometry_start==0);
}
int main(void)
{
    char directory[]="/tmp/a7pf-core-XXXXXX";assert(mkdtemp(directory));
    char disk[512],geom[512],link[512],other[512];
    snprintf(disk,sizeof(disk),"%s/disk",directory);snprintf(geom,sizeof(geom),"%s/geom",directory);
    snprintf(link,sizeof(link),"%s/link",directory);snprintf(other,sizeof(other),"%s/other",directory);
    int fd=open(disk,O_CREAT|O_EXCL|O_RDWR,0600),gf=open(geom,O_CREAT|O_EXCL|O_RDWR,0600);
    assert(fd>=0 && gf>=0);assert(!ftruncate(fd,1048576+8388608));
    unsigned char wire[24+4*24]={0};memcpy(wire,"A7PFGE01",8);put32(wire+8,1);put32(wire+12,4);put64(wire+16,1048576);
    put32(wire+24,1);put64(wire+32,65536);put64(wire+40,131072);
    put32(wire+48,7);put64(wire+56,196608);put64(wire+64,131072);
    put32(wire+72,31);put64(wire+80,1048576);put64(wire+88,4194304);
    put32(wire+96,32);put64(wire+104,1048576+4194304);put64(wire+112,4194304);
    assert(write(gf,wire,sizeof(wire))==sizeof(wire));
    struct stat st;assert(!fstat(fd,&st));struct a7pf s;
    assert(!a7pf_init(&s,fd,gf,st.st_dev,st.st_ino,dma,NULL));
    assert(a7pf_read_reg(&s,0x0c)==2 && a7pf_read_reg(&s,0x48)==2);
    op(&s,1,0);assert(s.geometry_size==2048 && !s.geometry_start);
    a7pf_write_reg(&s,0x10,7);op(&s,1,0);assert(s.geometry_size==256 && s.geometry_start==384);
    memset(ram,0x5a,sizeof(ram));a7pf_write_reg(&s,0x24,0x40000000);a7pf_write_reg(&s,0x20,256);
    op(&s,3,0);assert(s.actual==A7PF_MAX_IO);op(&s,4,0);
    unsigned char readback[512];assert(pread(fd,readback,512,196608)==512 && readback[0]==0x5a);
    a7pf_close(&s);close(fd);fd=open(disk,O_RDWR);
    assert(!a7pf_init(&s,fd,gf,st.st_dev,st.st_ino,dma,NULL));
    a7pf_write_reg(&s,0x24,0x40000000);a7pf_write_reg(&s,0x20,1);
    a7pf_write_reg(&s,0x18,384);memset(ram,0,sizeof(ram));op(&s,2,0);assert(ram[0]==0x5a && ram[511]==0x5a);
    a7pf_write_reg(&s,0x10,31);a7pf_write_reg(&s,0x18,0);memset(ram,0xb0,512);op(&s,3,0);
    a7pf_write_reg(&s,0x10,32);memset(ram,0,512);op(&s,2,0);assert(ram[0]==0);
    a7pf_write_reg(&s,0x10,0);a7pf_write_reg(&s,0x18,2048);op(&s,2,EINVAL);
    a7pf_write_reg(&s,0x10,7);a7pf_write_reg(&s,0x18,255);a7pf_write_reg(&s,0x20,2);op(&s,3,EINVAL);
    a7pf_write_reg(&s,0x10,9);op(&s,1,ENODEV);
    a7pf_write_reg(&s,0x10,0);a7pf_write_reg(&s,0x18,0);a7pf_write_reg(&s,0x20,257);op(&s,2,EINVAL);
    a7pf_write_reg(&s,0x20,0);op(&s,3,EINVAL);
    a7pf_write_reg(&s,0x20,1);a7pf_write_reg(&s,0x24,0x0b000000);op(&s,3,EFAULT);
    a7pf_write_reg(&s,0x24,0x40000001);op(&s,2,EFAULT);
    a7pf_write_reg(&s,0x24,0xfffffe00);a7pf_write_reg(&s,0x28,0xffffffff);op(&s,2,EFAULT);
    a7pf_write_reg(&s,0x24,0x40000000);a7pf_write_reg(&s,0x28,0);op(&s,99,EOPNOTSUPP);
    struct a7pf_io good=s.io;
    s.io.read=broken_read;s.io.write=broken_write;
    for (fault=1;fault<=2;fault++) { op(&s,2,fault==1 ? EIO : EIO);op(&s,3,fault==1 ? EIO : ENOSPC); }
    s.io=good;s.io.sync=broken_sync;op(&s,3,EIO);op(&s,4,EIO);s.io=good;
    assert(!ftruncate(fd,1048576));op(&s,2,ESTALE);assert(!ftruncate(fd,1048576+8388608));
    int otherfd=open(other,O_CREAT|O_EXCL|O_RDWR,0600);assert(otherfd>=0);
    assert(dup2(otherfd,s.fd)==s.fd);op(&s,2,ESTALE);a7pf_close(&s);close(otherfd);
    assert(a7pf_init(&s,fd,gf,st.st_dev,st.st_ino+1,dma,NULL)==ESTALE);
    assert(!symlink(disk,link));assert(a7pf_open_regular(link,O_RDWR)<0);
    assert(a7pf_open_regular("/dev/null",O_RDWR)<0);
    assert(!chmod(disk,0620));assert(a7pf_open_regular(disk,O_RDWR)<0);assert(!chmod(disk,0600));
    assert(!unlink(link));assert(!linkat(AT_FDCWD,disk,AT_FDCWD,link,0));
    assert(a7pf_open_regular(disk,O_RDWR)<0);assert(!unlink(link));
    /* Corrupt the slice geometry: overlaps must be rejected, never ACKed. */
    put64(wire+56,65536);assert(pwrite(gf,wire,sizeof(wire),0)==sizeof(wire));
    assert(a7pf_init(&s,fd,gf,st.st_dev,st.st_ino,dma,NULL)==EINVAL);
    close(fd);close(gf);unlink(link);unlink(other);unlink(disk);unlink(geom);assert(!rmdir(directory));
    puts("PASS durable whole/partition/boot slices; reopen readback; bounds; DMA; short/error IO; flush; inode/size/file rejection");
    return 0;
}
