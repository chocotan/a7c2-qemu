"""Execute the actual runtime translation unit with a fake original dispatcher.

No DSO/guest/device is built or run. The original callbacks and flush protocol
are exercised; only their I/O destinations are redirected to this test's tmpdir.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent

FIXTURE = r'''
#define _GNU_SOURCE
#include "fsys-write-trace.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
static int mode, original_calls[16], memory_reads, stops, failed_probe;
static unsigned long long epoch=7;
static unsigned char *source_mapping, *path_mapping;
static const void *expected_source;
static const char *expected_path;
static char logs[262144];static size_t log_bytes;
static const char *directory;
static unsigned char disk[16]="original";static unsigned read_position;
extern int __real_open(const char *,int,...),__real_close(int),__real_rename(const char *,const char *);
extern ssize_t __real_write(int,const void *,size_t),__real_pread(int,void *,size_t,off_t);
static const char *mapped(const char *path,char output[1024]) {
    if(strncmp(path,"/tmp/sd-flush",13))return path;
    int n=snprintf(output,1024,"%s/%s",directory,path+5);assert(n>0 && n<1024);return output;
}
int __wrap_open(const char *path,int flags,...) {
    if(!strcmp(path,"/dev/console")){errno=93;return 10000;}
    if(!strcmp(path,"/proc/self/mem") && failed_probe){errno=EACCES;return -1;}
    char output[1024];mode_t permissions=0600;
    if(flags&O_CREAT){va_list ap;va_start(ap,flags);permissions=(mode_t)va_arg(ap,int);va_end(ap);}
    return __real_open(mapped(path,output),flags,permissions);
}
int __wrap_close(int fd){if(fd==10000){errno=94;return 0;}return __real_close(fd);}
ssize_t __wrap_write(int fd,const void *data,size_t bytes) {
    if(fd!=10000)return __real_write(fd,data,bytes);
    assert(bytes<sizeof logs-log_bytes);memcpy(logs+log_bytes,data,bytes);log_bytes+=bytes;logs[log_bytes]=0;
    errno=95;return (ssize_t)bytes;
}
ssize_t __wrap_pread(int fd,void *data,size_t bytes,off_t offset) {
    memory_reads++;return __real_pread(fd,data,bytes,offset);
}
int __wrap_rename(const char *a,const char *b) {
    char first[1024],second[1024];return __real_rename(mapped(a,first),mapped(b,second));
}
int __wrap_kill(pid_t pid,int signal){assert(pid==getpid() && signal==19);stops++;return 0;}
static int original_mount(const char *,unsigned,char *,const void *);
static int original_unmount(unsigned char,unsigned);
static int original_open(const char *,unsigned long long *,unsigned);
static int original_write(unsigned long long,const void *,int);
static int original_write_flush(unsigned long long,const void *,int);
static int original_read(unsigned long long,void *,int);
static int original_close(unsigned long long);
static int original_seek(unsigned long long,long long,unsigned,void *);
static int original_truncate(unsigned long long,unsigned long long);
static int original_writefile(const char *,void *);
static int original_combine(const char *,const char *);
static int original_rename(const char *,const char *);
static int original_remove(const char *);
static int original_flush(unsigned char);
static unsigned long long get_epoch(void){errno=92;return epoch;}
static unsigned get_mask(void){errno=91;return 1;}
static void *lookup(void *handle,const char *name) {
    (void)handle;errno=90;
    if(!strcmp(name,"Fsys_Mount"))return original_mount;
    if(!strcmp(name,"Fsys_Unmount"))return original_unmount;
    if(!strcmp(name,"Fsys_Open"))return original_open;
    if(!strcmp(name,"Fsys_Write"))return original_write;
    if(!strcmp(name,"Fsys_WriteAndFlush"))return original_write_flush;
    if(!strcmp(name,"Fsys_Read"))return original_read;
    if(!strcmp(name,"Fsys_Close"))return original_close;
    if(!strcmp(name,"Fsys_Seek"))return original_seek;
    if(!strcmp(name,"Fsys_FTruncate"))return original_truncate;
    if(!strcmp(name,"Fsys_WriteFile"))return original_writefile;
    if(!strcmp(name,"Fsys_Combine"))return original_combine;
    if(!strcmp(name,"Fsys_Rename"))return original_rename;
    if(!strcmp(name,"Fsys_Remove"))return original_remove;
    if(!strcmp(name,"Fsys_FlushVolume"))return original_flush;
    if(!strcmp(name,"Fsys_GetMountDrives"))return get_mask;
    if(!strcmp(name,"native_rm_file_media_generation"))return get_epoch;
    if(!strcmp(name,"native_rm_file_fsys_observed"))return 0;
    assert(0);return 0;
}
static void *fake_dlvsym(void *handle,const char *name,const char *version) {
    (void)handle;assert(!strcmp(name,"dlsym") && !strcmp(version,"GLIBC_2.17"));return lookup;
}
static long fake_syscall(long number,...){assert(number==178);errno=96;return 123;}
#define dlvsym fake_dlvsym
#define syscall fake_syscall
#define fflush fake_fflush
static int fake_fflush(void *stream){(void)stream;return 0;}
#include "file-media-config.c"
#undef syscall
#undef fflush
static int original_mount(const char *path,unsigned flags,char *drive,const void *extra) {
    assert(errno==31 && !strcmp(path,"/nondev/rm2") && flags==0x123 && extra==(void *)0x1234);
    original_calls[0]++;*drive='A';errno=41;return 0;
}
static int original_unmount(unsigned char drive,unsigned flags) {
    assert(errno==31 && drive=='A' && flags==0x4321);original_calls[1]++;errno=42;return 0;
}
static int original_open(const char *path,unsigned long long *handle,unsigned flags) {
    original_calls[2]++;
    if(flags==1) {
        assert(mode==19 && errno==77 && !strcmp(path,"A:/SEEDED.BIN"));
        *handle=99;read_position=0;errno=81;return 0;
    }
    assert(errno==31 && path==expected_path && flags==0x206);
    if(mode==14){errno=43;return -27;}
    *handle=42;
    if(mode==1)assert(!munmap(path_mapping,4096));
    errno=43;return 0;
}
static int original_write(unsigned long long handle,const void *data,int count) {
    assert(errno==31 && handle==42 && data==expected_source);
    assert(count==((mode==5)?-1:(mode==13)?(int)FSYS_WRITE_OBSERVATION_LIMIT+1:8));
    original_calls[3]++;
    if(mode==1)assert(!munmap(source_mapping,4096));
    if(mode==9)epoch++;
    errno=44;return mode==2?3:mode==3?-37:mode==5?-9:count;
}
static int original_write_flush(unsigned long long handle,const void *data,int count) {
    assert(errno==31 && handle==42 && data==expected_source && count==8);original_calls[4]++;
    errno=45;return mode==4?-39:8;
}
static int original_read(unsigned long long handle,void *out,int count) {
    original_calls[5]++;
    if(handle==99) {
        assert(mode==19 && errno==(read_position?82:81) && count>0);
        unsigned n=8-read_position;if(n>(unsigned)count)n=(unsigned)count;
        if(n>3)n=3;
        memcpy(out,disk+read_position,n);read_position+=n;errno=82;return (int)n;
    }
    assert(errno==31 && handle==42 && count==8);memcpy(out,"read",4);errno=46;return 4;
}
static int original_close(unsigned long long handle) {
    original_calls[6]++;
    if(handle==99){assert(mode==19 && errno==82);errno=83;return 0;}
    assert(errno==31 && handle==42);errno=47;return mode==16?-19:0;
}
static int original_seek(unsigned long long handle,long long offset,unsigned origin,void *result) {
    assert(errno==31 && handle==42 && offset==-7 && origin==2);original_calls[7]++;
    if(mode!=7)*(unsigned long long *)result=9;
    errno=48;return 0;
}
static int original_truncate(unsigned long long handle,unsigned long long bytes) {
    assert(errno==31 && handle==42 && bytes==0x123456789abcdef0ull);original_calls[8]++;errno=49;return -29;
}
static int original_writefile(const char *path,void *parameters) {
    assert(errno==31 && path==expected_path && parameters==(void *)0x5678);original_calls[9]++;errno=50;return -30;
}
static int original_combine(const char *a,const char *b) {
    assert(errno==31 && a==(void *)1 && b==(void *)2);original_calls[10]++;errno=51;return -31;
}
static int original_rename(const char *a,const char *b) {
    assert(errno==31 && a==(void *)3 && b==(void *)4);original_calls[11]++;errno=52;return -32;
}
static int original_remove(const char *path) {
    assert(errno==31 && path==(void *)5);original_calls[12]++;errno=53;return -33;
}
static int original_flush(unsigned char drive) {
    assert(drive=='A');original_calls[13]++;errno=77;return mode==17?-43:0;
}
#define INVOKE(expression,result,error) do { errno=31;assert((expression)==(result));assert(errno==(error)); } while(0)
static void mount_media(void) {
    char drive=0;INVOKE(Fsys_Mount("/nondev/rm2",0x123,&drive,(void *)0x1234),0,41);assert(drive=='A');
}
static void flush_request(void) {
    int fd=open("/tmp/sd-flush.request",O_WRONLY|O_CREAT|O_TRUNC,0600);assert(fd>=0);
    assert(write(fd,"123\n",4)==4 && !close(fd));
    fd=open("/tmp/sd-flush.123.cancel",O_WRONLY|O_CREAT,0600);assert(fd>=0 && !close(fd));
    file_media_flush_pending();assert(!stops);
}
int main(int argc,char **argv) {
    assert(argc==3);mode=atoi(argv[1]);directory=argv[2];
    unsetenv("A7C2_SD_HOTPLUG");unsetenv("A7C2_FSYS_CONTENT_OBSERVE");
    unsetenv("A7C2_FILE_MEDIA_TEST");unsetenv("A7C2_FSYS_ASYNC_OBSERVE");
    assert(!memory_reads && !log_bytes && !sync_observer_pid && !observed_mount_generation);
    if(mode!=10 && mode!=22)setenv("A7C2_FSYS_ASYNC_OBSERVE","1",1);
    if(mode==1 || mode==9 || mode==21){setenv("A7C2_SD_HOTPLUG","1",1);setenv("A7C2_FSYS_CONTENT_OBSERVE","1",1);}
    if(mode==1)setenv("A7C2_FILE_MEDIA_TEST","1",1);
    mount_media();assert(original_calls[0]==1 && !hotplug_io);
    if(mode!=10 && mode!=22)assert(strstr(logs,mode==1 || mode==9 || mode==21?"domain=native_hotplug":"domain=observed_mount"));
    if(mode==22) {
        setenv("A7C2_FSYS_ASYNC_OBSERVE","1",1);
        assert(!observed_mount_generation && !fsys_sync_generation());
    }
    if(mode==20)failed_probe=1;
    expected_path=mode==23?"B:/CLIP.BIN":"A:/CLIP.BIN";
    if(mode==1) {
        path_mapping=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(path_mapping!=MAP_FAILED);
        memcpy(path_mapping,expected_path,12);expected_path=(const char *)path_mapping;
    }
    if(mode==15)expected_path=(void *)1;
    unsigned long long handle=0;
    INVOKE(Fsys_Open(expected_path,mode==14?(void *)1:&handle,0x206),mode==14?-27:0,43);
    assert(original_calls[2]==1 && !hotplug_io);
    if(mode==14){assert(!strstr(logs,"file=1 ") && strstr(logs,"result=-27 errno=43"));return 0;}
    assert(handle==42);
    if(mode==11) {
        pid_t child=fork();assert(child>=0);
        if(!child) {
            int before=memory_reads;
            INVOKE(Fsys_Close(handle),0,47);
            assert(memory_reads==before && !fsys_sync_enabled());
            errno=67;assert(fsys_sync_trace_readback_all(1,0,77,0)==-ESTALE && errno==67);
            _exit(0);
        }
        int status=0;assert(waitpid(child,&status,0)==child && WIFEXITED(status) && !WEXITSTATUS(status));return 0;
    }
    source_mapping=mmap(0,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);assert(source_mapping!=MAP_FAILED);
    memcpy(source_mapping,"original",8);expected_source=mode==6?(void *)1:source_mapping;
    int count=mode==5?-1:mode==13?(int)FSYS_WRITE_OBSERVATION_LIMIT+1:8;
    INVOKE(Fsys_Write(handle,expected_source,count),mode==2?3:mode==3?-37:mode==5?-9:count,44);
    assert(original_calls[3]==1 && !hotplug_io);
    if(mode==2) {
        char hash[80];snprintf(hash,sizeof hash,"data_fnv1a64=%016llx",
            (unsigned long long)fsys_write_fnv1a64("original",3));
        assert(strstr(logs,"actual=3") && strstr(logs,hash) && strstr(logs,"full_write=0"));
    }
    if(mode==1) {
        assert(strstr(logs,"source_complete=1 full_write=0"));
        assert(strstr(logs,"FSYS_CONTENT op=Write") && strstr(logs,"path_hex=413a2f434c49502e42494e"));
        char hash[80];snprintf(hash,sizeof hash,"data_fnv1a64=%016llx",
            (unsigned long long)fsys_write_fnv1a64("original",8));assert(strstr(logs,hash));
        return 0;
    }
    INVOKE(Fsys_WriteAndFlush(handle,expected_source,8),mode==4?-39:8,45);
    assert(original_calls[4]==1 && !hotplug_io);
    uint64_t position=0;INVOKE(Fsys_Seek(handle,-7,2,mode==7?(void *)1:&position),0,48);
    if(mode!=7)assert(position==9);
    unsigned char output[8];INVOKE(Fsys_Read(handle,output,8),4,46);assert(!memcmp(output,"read",4));
    if(mode==12) {
        INVOKE(Fsys_FTruncate(handle,0x123456789abcdef0ull),-29,49);
        INVOKE(Fsys_WriteFile(expected_path,(void *)0x5678),-30,50);
        INVOKE(Fsys_Combine((void *)1,(void *)2),-31,51);
        INVOKE(Fsys_Rename((void *)3,(void *)4),-32,52);
        INVOKE(Fsys_Remove((void *)5),-33,53);
        for(unsigned i=8;i<=12;i++)assert(original_calls[i]==1);
        for(int reason=2004;reason<=2009;reason++) {
            char text[40];snprintf(text,sizeof text,"observation_rc=-%d",reason);assert(strstr(logs,text));
        }
    }
    INVOKE(Fsys_Close(handle),mode==16?-19:0,47);assert(original_calls[6]==1 && !hotplug_io);
    if(mode==8) {
        unsigned long long before=fsys_sync_generation();INVOKE(Fsys_Unmount('A',0x4321),0,42);
        assert(!fsys_sync_generation() && !mounted_media_drive);mount_media();assert(fsys_sync_generation()>before);
        assert(fsys_sync_trace_readback_all(before,0,77,0)<0);
    }
    if(mode==19) {
        struct fsys_sync_context context={0};uint64_t gen=fsys_sync_generation();
        unsigned file=fsys_sync_trace_open("A:/SEEDED.BIN",13,88,gen,0,0,31,1,0,1,0,context);assert(file);
        struct fsys_sync_source source={(uintptr_t)disk,8,1,FSYS_SYNC_VIRTUAL};
        unsigned ticket=fsys_sync_trace_write_begin(file,88,gen,source,8,0,context);assert(ticket);
        assert(!fsys_sync_trace_write_end(ticket,88,gen,8,44));
        assert(!fsys_sync_trace_close(file,88,gen,0,47,context));
    }
    if(mode==18)hotplug_io=1;
    if(mode==21) {
        errno=31;assert(!file_media_hotplug_flush(epoch,'A') && errno==77);
        assert(original_calls[13]==1 && !busy && !hotplug_io);
    } else {flush_request();assert(original_calls[13]==(mode==10 || mode==17?1:2));}
    assert(!strstr(logs,"content_verified=1") || mode==19);
    if(mode==19){assert(strstr(logs,"content_verified=1") && original_calls[2]==2 && original_calls[6]==2);}
    if(mode==10)assert(!memory_reads && !strstr(logs,"FSYS_SYNC_") && !sync_observer_pid);
    else {
        assert(strstr(logs,"FSYS_SYNC_OPEN") && strstr(logs,"size_known=0 size=0 position_known=0"));
        assert(strstr(logs,"FSYS_SYNC_CLOSE"));
        if(mode!=15 && mode!=20 && mode!=22 && mode!=23)assert(strstr(logs,"FSYS_SYNC_WRITE"));
        else assert(strstr(logs,"FSYS_SYNC_INCOMPLETE") && !strstr(logs,"source_complete=1"));
        if(mode!=16 && mode!=17 && mode!=18 && mode!=8 && mode!=9 && mode!=15 && mode!=20 && mode!=22 && mode!=23)assert(strstr(logs,"FSYS_SYNC_NATIVE_READBACK"));
        if(mode==13)assert(strstr(logs,"observation_rc=-7"));
        if(mode==9)assert(strstr(logs,"observation_rc=-116"));
        if(mode==6 || mode==20)assert(!strstr(logs,"source_complete=1"));
    }
    if(mode!=1)assert(!munmap(source_mapping,4096));
    return 0;
}
'''


@pytest.mark.parametrize('sanitized', [False, True], ids=['strict-c11', 'asan-ubsan'])
def test_actual_runtime_sync_wrappers(tmp_path, sanitized):
    fixture = tmp_path / 'sync-wiring.c'
    fixture.write_text(FIXTURE)
    binary = tmp_path / 'sync-wiring'
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror']
    if sanitized:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie']
    subprocess.run(['cc', *flags, '-I', str(HERE), str(fixture), str(HERE / 'fsys-write-trace.c'),
                    '-Wl,--wrap=open,--wrap=close,--wrap=write,--wrap=pread,--wrap=rename,--wrap=kill',
                    '-o', str(binary)], check=True, capture_output=True, text=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('A7C2_', 'MENU_'))}
    env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
    for mode in range(24):
        files = tmp_path / f'case-{mode}'
        files.mkdir()
        result = subprocess.run([str(binary), str(mode), str(files)], capture_output=True,
                                text=True, timeout=15, env=env)
        assert result.returncode == 0, f'mode={mode}\n{result.stdout}\n{result.stderr}'


def test_mutation_supplement_pins_public_original_windows():
    from elftools.elf.elffile import ELFFile

    pins = json.loads((HERE / '../../report/native-movie-write-trace/wiring-source-pins.json').read_text())
    path = HERE / 'menu-root/usr/lib' / pins['artifact']
    raw = path.read_bytes()
    assert len(raw) == pins['bytes'] and hashlib.sha256(raw).hexdigest() == pins['sha256']
    assert pins['capture_verified'] is False and pins['media_origin_verified'] is False
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        assert elf['e_machine'] == 'EM_AARCH64' and elf.elfclass == 64 and elf.little_endian
        loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        for pin in pins['windows']:
            start, end = int(pin['start'], 16), int(pin['end'], 16)
            segments = [s for s in loads if s['p_vaddr'] <= start < end <= s['p_vaddr'] + s['p_filesz']]
            assert len(segments) == 1
            offset = segments[0]['p_offset'] + start - segments[0]['p_vaddr']
            assert hashlib.sha256(raw[offset:offset + end - start]).hexdigest() == pin['sha256']
        symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.dynsym').iter_symbols()}
        assert symbols['Fsys_Combine'] == 0x35954
        assert symbols['Fsys_Rename'] == 0x33e7c and symbols['Fsys_Remove'] == 0x33978

