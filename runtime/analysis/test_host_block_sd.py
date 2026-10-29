from pathlib import Path
import subprocess

BASE=Path(__file__).resolve().parent


def test_capacity_is_real_ioctl_and_only_selected_block_is_changed(tmp_path):
    source=tmp_path/'bridge-test.c'
    source.write_text(r'''
#define _GNU_SOURCE
#define HOST_BLOCK_SD_TEST
#define ioctl fake_ioctl
#include "host-block-sd.c"
#include <stdarg.h>
#include <string.h>
#include <assert.h>
static unsigned calls;
static uint64_t disk_size=HOST_SD_BYTES;
static unsigned sector=512;
static int failure;
int fake_ioctl(int fd,unsigned long operation,...) {
    assert(fd==7);calls++;
    if(failure)return -1;
    va_list args;va_start(args,operation);void *out=va_arg(args,void *);va_end(args);
    if(operation==0x80081272UL)*(uint64_t *)out=disk_size;
    else {assert(operation==0x1268UL);*(unsigned *)out=sector;}
    return 0;
}
int main(void) {
    struct stat selected={.st_mode=S_IFBLK|0600,.st_dev=1,.st_ino=2,.st_rdev=2048};
    struct stat out=selected,expected=selected;
    assert(truthful_capacity(7,&out,&selected)==1 && calls==2);
    expected.st_size=HOST_SD_BYTES;assert(!memcmp(&out,&expected,sizeof out));
    for(unsigned n=0;n<4;n++) {
        out=selected;
        if(n==0)out.st_mode=S_IFREG|0600;
        if(n==1)out.st_dev++;
        if(n==2)out.st_ino++;
        if(n==3)out.st_rdev++;
        expected=out;calls=0;
        assert(truthful_capacity(7,&out,&selected)==0 && !calls && !memcmp(&out,&expected,sizeof out));
    }
    out=selected;expected=out;disk_size--;
    assert(truthful_capacity(7,&out,&selected)==-1 && errno==EIO && !memcmp(&out,&expected,sizeof out));
    disk_size=HOST_SD_BYTES;sector=4096;
    assert(truthful_capacity(7,&out,&selected)==-1 && !memcmp(&out,&expected,sizeof out));
    sector=512;failure=1;
    assert(truthful_capacity(7,&out,&selected)==-1 && !memcmp(&out,&expected,sizeof out));
    return 0;
}
''')
    binary=tmp_path/'bridge-test'
    subprocess.run(['clang','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I',str(BASE),str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_variadic_trace_tailcall_preserves_registers_and_does_not_edit_format(tmp_path):
    text=(BASE/'host-block-sd.c').read_text()
    start=text.index('void capture_host_fsys_trace(')
    stop=text.index('__asm__(',start)
    capture=text[start:stop]
    source=tmp_path/'trace.c'
    source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
static void *host_fsys_trace_continue;
static int active;
static int enabled(void){return active;}
static void *lookup(const char *name) {
    assert(!strcmp(name,"fsysDepTrace_Printf"));errno=EINTR;return (void *)1;
}
''' + capture + r'''
int main(void) {
    const char format[]="error %d %s",expected[]="error %d %s";
    for(unsigned i=0;i<170;i++) {
        active=i%2;errno=EDOM;
        capture_host_fsys_trace(6,format,1,2,3,4,5,6);
        assert(errno==EDOM && !memcmp(format,expected,sizeof expected));
    }
    assert(host_fsys_trace_continue==(void *)1);return 0;
}
''')
    binary=tmp_path/'trace'
    subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
    asm=text[stop:]
    for registers,offset in [('x0, x1',0),('x2, x3',16),('x4, x5',32),('x6, x7',48),
                             ('x8, x30',64),('q0, q1',80),('q2, q3',112),
                             ('q4, q5',144),('q6, q7',176)]:
        assert f'stp {registers}, [sp, #{offset}]' in asm
        assert f'ldp {registers}, [sp, #{offset}]' in asm
    assert 'mrs x16, nzcv' in asm and 'msr nzcv, x16' in asm
    assert 'add sp, sp, #0xe0' in asm and 'br x16' in asm


def test_error_query_observes_only_the_original_call(tmp_path):
    text=(BASE/'host-block-sd.c').read_text()
    wrapper=text[text.index('static int error_query('):text.index('unsigned int PFDRV_convErrorFromPDMtoPF(')]
    program=r'''
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
static unsigned calls;
static int active;
static int original(void){assert(errno==EDOM);calls++;errno=EAGAIN;return 0x80000002;}
static int enabled(void){return active;}
static void *lookup(const char *name) {
    assert(!strcmp(name,"pf2_errnum") || !strcmp(name,"pf2_inerrnum"));errno=EINTR;return original;
}
''' + wrapper + r'''
int main(void) {
    for(unsigned i=0;i<40;i++) {
        active=i%2;errno=EDOM;
        assert((unsigned)pf2_errnum()==0x80000002 && errno==EAGAIN);
        errno=EDOM;assert((unsigned)pf2_inerrnum()==0x80000002 && errno==EAGAIN);
    }
    assert(calls==80);return 0;
}
'''
    source=tmp_path/'errors.c';source.write_text(program);binary=tmp_path/'errors'
    subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_error_conversion_observer_does_not_invent_or_repeat_conversion(tmp_path):
    text=(BASE/'host-block-sd.c').read_text()
    capture=text[text.index('unsigned int PFDRV_convErrorFromPDMtoPF('):text.index('static void stage_trace(')]
    source=tmp_path/'convert.c'
    source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
static unsigned calls;
static int active;
static unsigned original(void *volume,unsigned error) {
    assert(volume==(void *)0x1234 && errno==EDOM);calls++;errno=EAGAIN;return error^0x80000000;
}
static int enabled(void){return active;}
static void *lookup(const char *name) {
    assert(!strcmp(name,"PFDRV_convErrorFromPDMtoPF"));errno=EINTR;return original;
}
''' + capture + r'''
int main(void) {
    for(unsigned i=0;i<40;i++) {
        active=i%2;errno=EDOM;
        assert(PFDRV_convErrorFromPDMtoPF((void *)0x1234,i)==(i^0x80000000));
        assert(errno==EAGAIN);
    }
    assert(calls==40);return 0;
}
''')
    binary=tmp_path/'convert'
    subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_volume_and_cache_observers_preserve_original_calls(tmp_path):
    text=(BASE/'host-block-sd.c').read_text()
    wrapper=text[text.index('static void stage_trace('):text.index('unsigned long fsysDepLog_PrFILE2_PDM(')]
    source=tmp_path/'stages.c'
    source.write_text(r'''
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
static unsigned mounts,pages,caches,paddings;
static int enabled(void){return 1;}
static unsigned original_mount(void *v,unsigned flags) {
    assert(v==(void *)0x1234 && flags==0x60 && errno==EDOM);mounts++;errno=EAGAIN;return 0x80000002;
}
static unsigned original_page(void *v,uint64_t sector,void *out,unsigned flags) {
    assert(v==(void *)0x1234 && sector==UINT64_C(0x100000007) && out==(void *)0x5678 && !flags && errno==EDOM);
    pages++;errno=EAGAIN;return 7;
}
static unsigned original_cache(void *v) {
    assert(v==(void *)0x1234 && errno==EDOM);caches++;errno=EAGAIN;return 2;
}
static unsigned original_padding(void *address,void *size) {
    assert(address && size && errno==EDOM);paddings++;
    *(uint64_t *)address=0x12345000;*(uint64_t *)size=0x20000;errno=EAGAIN;return 0;
}
static void *lookup(const char *name) {
    errno=EINTR;
    if(!strcmp(name,"PFDRV_mount"))return original_mount;
    if(!strcmp(name,"PFCACHE_InitCaches"))return original_cache;
    if(!strcmp(name,"mcmn_buf_getforpadding"))return original_padding;
    assert(!strcmp(name,"PFCACHE_AllocateDataPage"));return original_page;
}
''' + wrapper + r'''
int main(void) {
    for(unsigned i=0;i<40;i++) {
        errno=EDOM;assert(PFDRV_mount((void *)0x1234,0x60)==0x80000002 && errno==EAGAIN);
        errno=EDOM;assert(PFCACHE_AllocateDataPage((void *)0x1234,UINT64_C(0x100000007),(void *)0x5678,0)==7 && errno==EAGAIN);
        errno=EDOM;assert(PFCACHE_InitCaches((void *)0x1234)==2 && errno==EAGAIN);
        uint64_t address=0,size=0;errno=EDOM;
        assert(!mcmn_buf_getforpadding(&address,&size) && errno==EAGAIN && address==0x12345000 && size==0x20000);
    }
    assert(mounts==40 && pages==40 && caches==40 && paddings==40);return 0;
}
''')
    binary=tmp_path/'stages'
    subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_original_capacity_callsite_and_flush_symbol():
    import struct
    image=BASE/'menu-root/usr/lib/libInfraMediaCommon.so'
    if not image.exists():
        import pytest
        pytest.skip('Original firmware is not distributed')
    raw=image.read_bytes()
    assert struct.unpack_from('<I',raw,0x28c00)[0]==0x94009e42
    assert struct.unpack_from('<4I',raw,0x50508)==(0xaa0103e2,0x2a0003e1,0x52800000,0x17ff1d67)
    assert struct.unpack_from('<2I',raw,0x24c20)==(0x52800000,0xd65f03c0)


def test_adapter_does_not_override_format_ready_or_capacity_parameters():
    text=(BASE/'host-block-sd.c').read_text()
    assert 'caller!=(uintptr_t)dummy-0x28964+0x28c04' in text
    assert 'int result=fsync(fd)' in text
    assert 'return result?0x80000004UL:0;' in text
    assert all(name not in text for name in ('mcmn_param_set','FSYS_GTEST_','SUPPORT_FORMAT','Fsys_Format'))
    program=(BASE/'fsys-file-test.c').read_text()
    assert 'host_block' in program and 'FSYS_HOST_BLOCK_TEST_PASS scope=original_Fsys_diagnostic_not_camera_format_or_photo' in program
    assert 'mcmn_param_getul(0xf9)' in program
    assert 'if(host_block)require_zero("FlushVolume",Fsys_FlushVolume' in program
    assert 'if(n>24)return;' in text and 'unsigned char bytes[64]' in text
    assert 'same_block(&current,&selected)' in text
    assert text.count('io_trace("read",fd,iov,count,offset,result,saved);errno=saved;return result;')==1
    assert text.count('io_trace("write",fd,iov,count,offset,result,saved);errno=saved;return result;')==1
    assert 'return function(object,stage,error,detail);' in text
    assert 'HOST_BLOCK_SD_PDM stage=%u error=%#x detail=%#x' in text


def test_pdm_observer_preserves_arguments_return_and_original_errno(tmp_path):
    text=(BASE/'host-block-sd.c').read_text()
    wrapper=text[text.index('unsigned long fsysDepLog_PrFILE2_PDM('):text.index('static void *host_fsys_trace_continue')]
    program=r'''
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
static unsigned calls;
static int active=1;
static unsigned long original(unsigned long object,unsigned int stage,unsigned int error,unsigned int detail) {
    assert(object==0x1234 && stage==2 && error==0x80000000 && detail==7);
    assert(errno==EDOM);calls++;errno=EAGAIN;return 0x12345678abcdefUL;
}
static void *lookup(const char *name) {
    assert(!strcmp(name,"fsysDepLog_PrFILE2_PDM"));errno=EINTR;return original;
}
static int enabled(void) {return active;}
''' + wrapper + r'''
int main(void) {
    for(unsigned i=0;i<40;i++) {
        active=i%2;errno=EDOM;
        assert(fsysDepLog_PrFILE2_PDM(0x1234,2,0x80000000,7)==0x12345678abcdefUL);
        assert(errno==EAGAIN);
    }
    assert(calls==40);return 0;
}
'''
    source=tmp_path/'pdm.c';source.write_text(program);binary=tmp_path/'pdm'
    subprocess.run(['clang','-O1','-g','-fsanitize=address,undefined',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
