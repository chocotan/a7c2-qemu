"""Compile the actual helper control flow with instrumented block operations."""
from pathlib import Path
import subprocess


def test_sync_only_has_no_raw_data_writes_and_rejects_unrequested_mode(tmp_path):
    source=Path(__file__).with_name('host-sd-probe.c').read_text().split('extern int __libc_start_main')[0]
    source='\n'.join(line for line in source.splitlines() if not line.startswith('_Static_assert'))
    harness=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <string.h>
#include <errno.h>
static int opens,syncs,closes,bad_capacity,fail_sync;
static int checked_open(const char *path,int flags,...) {
    assert(!strcmp(path,"/dev/sda") && (flags&O_NOFOLLOW));opens++;return 50;
}
static int checked_stat(int version,int fd,struct stat *out) {
    assert(version==0 && fd==50);memset(out,0,sizeof *out);out->st_mode=S_IFBLK;return 0;
}
static int checked_ioctl(int fd,unsigned long request,...) {
    assert(fd==50);va_list args;va_start(args,request);void *out=va_arg(args,void *);va_end(args);
    if(request==0x80081272UL)*(uint64_t *)out=bad_capacity?128:256000000000ULL;
    else {assert(request==0x1268UL);*(unsigned *)out=512;}return 0;
}
static int checked_sync(int fd) {assert(fd==50);syncs++;errno=fail_sync?EIO:0;return fail_sync?-1:0;}
static int checked_close(int fd) {assert(fd==50);closes++;return 0;}
static ssize_t no_read(int fd,void *p,size_t n,off_t o) {(void)fd;(void)p;(void)n;(void)o;assert(0);return -1;}
static ssize_t no_write(int fd,const void *p,size_t n,off_t o) {(void)fd;(void)p;(void)n;(void)o;assert(0);return -1;}
#define open checked_open
#define __fxstat checked_stat
#define ioctl checked_ioctl
#define fsync checked_sync
#define close checked_close
#define pread no_read
#define pwrite no_write
'''+source+r'''
int main(void) {
    char *sync[]={"probe","sync",0},*bare[]={"probe",0},*bad[]={"probe","unexpected",0};
    assert(run(1,bare)==2 && run(2,bad)==2 && !opens);
    assert(run(2,sync)==0 && opens==1 && syncs==1 && closes==1);
    fail_sync=1;assert(run(2,sync)==6 && syncs==2 && closes==2);
    bad_capacity=1;assert(run(2,sync)==3 && syncs==2 && closes==3);
    return 0;
}
'''
    path=tmp_path/'probe.c';binary=tmp_path/'probe';path.write_text(harness)
    subprocess.run(['clang','-Werror','-Wall','-Wextra','-fsanitize=address,undefined',
                    str(path),'-o',str(binary)],check=True,capture_output=True)
    subprocess.run([str(binary)],check=True,capture_output=True)
