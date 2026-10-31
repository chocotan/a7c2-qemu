"""Deferred host checks for the actual read-only model17c callback and installer."""
from pathlib import Path
import re
import struct
import subprocess

import pytest


BASE = Path(__file__).resolve().parent
SOURCE = (BASE / 'menu-observe.c').read_text()
FIRST16 = bytes.fromhex('fd7bbda9840080d2fd030091f35301a9')
RESTORE_FIRST16 = bytes.fromhex('fd7bbea9fd030091f30b00f973c502f0')
PUBLISH_FIRST16 = bytes.fromhex('fd7bb9a9fd030091f35301a9f30300aa')


def _extracted_model17c():
    start = SOURCE.index('static unsigned int model17c_observer_enabled,')
    callback = SOURCE[start:SOURCE.index('__asm__(', start)]
    match = re.search(r'static int arm_entry_probe\([^;]+?\) \{', SOURCE, re.S)
    assert match
    start = match.start()
    arm = SOURCE[start:SOURCE.index('/* Original request objects', start)]
    start = SOURCE.index('static int model17c_arm_readonly_entry(')
    install = SOURCE[start:SOURCE.index('/* Read-only shutter detail probes.', start)]
    assert not re.search(r'\b(?:pwrite|memcpy|memset|mprotect|osal_\w+)\s*\(', callback)
    return arm, callback, install


def test_model17c_entry_replay_and_existing_flow_gate():
    start = SOURCE.index('model17c_setter_trampoline:\\n')
    trampoline = SOURCE[start:SOURCE.index('br x16\\n', start)]
    words = [int(word, 16) for word in re.findall(r'\.inst (0x[0-9a-f]+)', trampoline)]
    assert struct.pack('<4I', *words) == FIRST16
    assert trampoline.count('PROBE_SAVE_ARGS') == trampoline.count('PROBE_RESTORE_ARGS') == 1
    assert trampoline.index('mov x2, x30') < trampoline.index('bl capture_model17c_setter')
    assert trampoline.index('PROBE_RESTORE_ARGS') < trampoline.index('.inst')
    assert 'model17c_setter_continue = (void *)(base + 0x267b6a8UL);' in SOURCE
    start = SOURCE.index('static void install_shutter_detail_trace(unsigned long base) {')
    install = SOURCE[start:SOURCE.index('/* Natural startup frontier:', start)]
    assert install.index('if (!mode) return;') < install.index('if (flows) install_model17c_observer(base);')
    assert 'int flows = all || same_name(mode, "flow");' in install
    assert 'if (flows) enable_sequence_queue_observer(base);' in install
    assert 'getenv("MENU_INPUT_ROUTE_TRACE") && !getenv("MENU_OBSERVE_SELFTEST")' in SOURCE
    assert not re.search(r'getenv\("[^"\n]*MODEL17', SOURCE)
    assert '"SHUTTER_DETAIL_"' in SOURCE
    start = SOURCE.index('model17c_restore_trampoline:\\n')
    restore = SOURCE[start:SOURCE.index('br x16\\n', start)]
    words = [int(word, 16) for word in re.findall(r'\.inst (0x[0-9a-f]+)', restore)]
    assert struct.pack('<3I', *words) == RESTORE_FIRST16[:12]
    assert '.inst 0xf002c573' not in restore
    assert restore.count('PROBE_SAVE_ARGS') == restore.count('PROBE_RESTORE_ARGS') == 1
    assert restore.index('mov x0, x30') < restore.index('bl capture_model17c_restore')
    assert restore.index('PROBE_RESTORE_ARGS') < restore.index('.inst')
    assert 'ldr x19, [x16, #:lo12:model17c_restore_adrp_page]' in restore
    assert 'model17c_restore_continue = (void *)(base + 0x2aa31ccUL);' in SOURCE
    assert 'model17c_restore_adrp_page = decoded_page;' in SOURCE
    assert 'static void *model17c_restore_continue __attribute__((used));' in SOURCE
    assert 'restore_adrp_replay_not_implemented' not in SOURCE
    start = SOURCE.index('static void install_model17c_observer(unsigned long base) {')
    install = SOURCE[start:SOURCE.index('/* Read-only shutter detail probes.', start)]
    assert install.index('model17c_observe_values(base, 0, 0, 1, 0);') < install.index('arm_entry_probe(')
    assert install.index('model17c_observe_values(base, 0, 0, 1, 0);') < install.index('install_model17c_restore_observer(base);')
    assert 'saved_source=descriptor0_via_2aa319c alias_unproven=1' in SOURCE
    assert 'quota=%s observation_only=1 atomic_snapshot=0 phase=%s original_store_observed=0' in SOURCE
    start = SOURCE.index('model17c_publish_trampoline:\\n')
    publish = SOURCE[start:SOURCE.index('br x16\\n', start)]
    words = [int(word, 16) for word in re.findall(r'\.inst (0x[0-9a-f]+)', publish)]
    assert struct.pack('<4I', *words) == PUBLISH_FIRST16
    assert publish.count('PROBE_SAVE_ARGS') == publish.count('PROBE_RESTORE_ARGS') == 1
    assert publish.index('mov x1, x30') < publish.index('bl capture_model17c_publish')
    assert 'model17c_publish_continue = (void *)(base + 0x2aeff6cUL);' in SOURCE
    assert 'base + 0x2767978' not in SOURCE  # A 12B function must not receive a 16B stub.


def test_model17c_restore_opcode_anchor_and_independent_original_pc_decode():
    opcode = int.from_bytes(RESTORE_FIRST16[12:16], 'little')
    assert opcode == 0xf002c573
    assert opcode & 0x9f00001f == 0x90000013  # ADRP, destination x19.
    imm21 = ((opcode >> 29) & 3) | (((opcode >> 5) & 0x7ffff) << 2)
    displacement = (imm21 - (1 << 21) if imm21 & (1 << 20) else imm21) << 12
    assert imm21 == 0x58af and displacement == 0x58af000
    assert (0x2aa31c8 & ~0xfff) + displacement == 0x8352000
    assert 0x8352000 + 0x830 + 0xd000 + 0xa0 == 0x835f8d0
    for base in (0x1000, 0x7f574ab000, 0x400000000, 0x10000000000):
        assert ((base + 0x2aa31c8) & ~0xfff) + displacement == base + 0x8352000
    # These copies at a trampoline PC preserve opcode bytes but produce a different address.
    assert (0x1000 & ~0xfff) + displacement != 0x8352000
    assert int.from_bytes(RESTORE_FIRST16[12:16], 'big') != opcode
    for changed in (opcode ^ 1, opcode ^ (1 << 5), opcode ^ (1 << 29), opcode & ~0x80000000):
        assert changed != opcode
    start = SOURCE.index('static int model17c_restore_page(')
    decoder = SOURCE[start:SOURCE.index('static unsigned int model17c_publish_enabled,', start)]
    assert 'opcode != 0xf002c573u' in decoder and '0x2aa31c8UL & ~0xfffUL' in decoder
    assert '(base + 0x2aa31c8UL) & ~0xfffUL' in decoder
    assert 'runtime_page != base + original_page' in decoder


def test_model17c_actual_callback_and_install_refusals(tmp_path):
    arm, callback, install = _extracted_model17c()
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
static unsigned long appfw_base=0x100000UL;
static unsigned callbacks,open_calls,read_calls,protect_calls,cache_calls;
static int fail_open,fail_read,partial_read,fail_protect;
static char last[2048],probe[1024],restore_probe[1024];
static void record(const char *prefix,const char *text) {
    if(!strcmp(prefix,"SHUTTER_DETAIL_MODEL17C ")) {
        callbacks++;snprintf(last,sizeof last,"%s",text);
    } else if(!strcmp(prefix,"SHUTTER_DETAIL_MODEL17C_PROBE ")) {
        char *out=strstr(text,"site=setter")?probe:restore_probe;
        snprintf(out,1024,"%s",text);
    } else if(!strcmp(prefix,"SHUTTER_DETAIL_MODEL17C_BASELINE ")) {
        assert(strstr(text,"phase=install_before_arm") && strstr(text,"original_store_observed=0"));
    } else assert(!strncmp(prefix,"ENTRY_PROBE_",12));
    errno=ENOTTY; /* Log side effects must not replace a captured failure or caller errno. */
}
static int observe_open(const char *path,int flags) {
    assert(!strcmp(path,"/proc/self/mem") && flags==0);open_calls++;
    if(fail_open){errno=EACCES;return -1;}
    return open(path,flags);
}
static long observe_pread(int fd,void *out,unsigned long size,long offset) {
    read_calls++;assert(size==4 || size==8 || size==16);
    if(fail_read){errno=EIO;return -1;}
    return pread(fd,out,partial_read?size/2:size,offset);
}
static int observe_mprotect(void *page,unsigned long size,int protection) {
    (void)page;assert(size==4096 && (protection==7 || protection==5));
    protect_calls++;
    if((int)protect_calls==fail_protect){errno=EPERM;return -1;}
    return 0; /* Observe the real installer's patch as data; never execute it. */
}
static void clear_cache_range(void *address,unsigned long size) {
    (void)address;assert(size==16);cache_calls++;
}
static long observe_syscall(long number) {
    assert(number==178);return syscall(SYS_gettid);
}
static void model17c_setter_trampoline(void) {}
static void model17c_restore_trampoline(void) {}
static void model17c_publish_trampoline(void) {}
#define open observe_open
#define pread observe_pread
#define mprotect observe_mprotect
#define syscall observe_syscall
''' + arm + callback + install + r'''
#undef open
#undef pread
#undef mprotect
#undef syscall
struct transaction {
    unsigned long current,descriptor;
    unsigned int id,flags;
    unsigned long scope;
};
static void expect_probe(int rc) {
    char expected[80];snprintf(expected,sizeof expected,"rc=%d errno=%d",rc,rc<0?-rc:0);
    assert(strstr(probe,expected));
    /* This setter fixture has no mapped restore entry, so it must remain unarmed. */
    assert(strstr(restore_probe,"arm_attempted=0") && strstr(restore_probe,"original_store_observed=0"));
    assert(errno==EDOM);
}
int main(void) {
    _Static_assert(sizeof(struct transaction)==32,"original transaction width");
    long page_size=sysconf(_SC_PAGESIZE);assert(page_size==4096);
    unsigned char *page=mmap(NULL,(size_t)page_size*2,PROT_READ|PROT_WRITE,
                             MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(page!=MAP_FAILED && munmap(page+page_size,(size_t)page_size)==0);
    /* Exactly four readable current bytes at a page edge; the next page is absent. */
    unsigned int *current=(unsigned int *)(page+page_size-4);*current=0x81;
    unsigned long descriptor[3]={0,0xabcdef00UL,0x80000011UL};
    struct transaction txn={(unsigned long)current,(unsigned long)descriptor,0x17c,0x5555,0x12345678};
    struct transaction before=txn;
    unsigned long descriptor_before[3];memcpy(descriptor_before,descriptor,sizeof descriptor);
    unsigned long caller=appfw_base+0x267b768UL;
    errno=EDOM;
    capture_model17c_setter((unsigned long)&txn,0xffffffffU,caller);
    assert(!callbacks && !open_calls && errno==EDOM);
    model17c_observer_enabled=1;
    txn.id=0x123;
    for(unsigned i=0;i<80;i++)capture_model17c_setter((unsigned long)&txn,7,caller);
    assert(!callbacks && model17c_observer_seen==0 && errno==EDOM);
    txn=before;
    capture_model17c_setter((unsigned long)&txn,0xffffffffU,caller);
    assert(callbacks==1 && errno==EDOM && strstr(last,"n=1 "));
    assert(strstr(last,"w1=0xffffffff") && strstr(last,"model_id=0x17c"));
    assert(strstr(last,"scope=0x12345678") && strstr(last,"descriptor8=0xabcdef00"));
    assert(strstr(last,"descriptor10=0x80000011") && strstr(last,"current_before=0x81"));
    assert(strstr(last,"reads=8/8/4/8/8/4/4") && strstr(last,"read_errno=0/0/0/0/0/0/0"));
    assert(strstr(last,"caller_app=0x267b768") && strstr(last,"identity=model_id"));
    char identity[96];snprintf(identity,sizeof identity,"caller_raw=%#lx",caller);assert(strstr(last,identity));
    snprintf(identity,sizeof identity,"pid=%d tid=%ld",getpid(),syscall(SYS_gettid));assert(strstr(last,identity));
    assert(strstr(last,"atomic_snapshot=0 phase=before_store original_store_observed=0"));
    assert(strstr(last,"return_not_observed=1 original_return_observed=0"));
    assert(*current==0x81 && !memcmp(&txn,&before,sizeof txn));
    assert(!memcmp(descriptor_before,descriptor,sizeof descriptor));
    partial_read=1;capture_model17c_setter((unsigned long)&txn,0,caller);partial_read=0;
    assert(callbacks==2 && strstr(last,"reads=4/4/2/4/-1/-1/-1") && errno==EDOM);
    assert(strstr(last,"identity=unresolved"));
    capture_model17c_setter(1,0,caller);
    assert(callbacks==3 && strstr(last,"identity=unresolved") && errno==EDOM);
    assert(strstr(last,"reads=-1/-1/-1/-1/-1/-1/-1"));
    fail_open=1;capture_model17c_setter((unsigned long)&txn,0,caller);fail_open=0;
    snprintf(identity,sizeof identity,"open_rc=-1 open_errno=%d",EACCES);
    assert(callbacks==4 && strstr(last,identity) && errno==EDOM);
    txn.descriptor=(unsigned long)-1;
    capture_model17c_setter((unsigned long)&txn,0,caller);txn=before;
    snprintf(identity,sizeof identity,"read_errno=0/0/0/0/%d/%d/0",EOVERFLOW,EOVERFLOW);
    assert(callbacks==5 && strstr(last,identity) && errno==EDOM);
    txn.current=0;
    capture_model17c_setter((unsigned long)&txn,0,caller);txn=before;
    snprintf(identity,sizeof identity,"read_errno=0/0/0/0/0/0/%d",EFAULT);
    assert(callbacks==6 && strstr(last,identity) && errno==EDOM);
    for(unsigned i=0;i<30;i++)capture_model17c_setter((unsigned long)&txn,i,caller);
    assert(callbacks==16 && model17c_observer_seen==16 && errno==EDOM);
    unsigned opens=open_calls,reads=read_calls;
    capture_model17c_setter(1,0,caller);
    assert(callbacks==16 && open_calls==opens && read_calls==reads && errno==EDOM);
    assert(*current==0x81 && !memcmp(&txn,&before,sizeof txn));
    assert(!memcmp(descriptor_before,descriptor,sizeof descriptor));
    unsigned long base=(unsigned long)page-0x267b698UL;
    /* Each original word must match; even the last-word mismatch forbids all patch writes. */
    for(unsigned i=0;i<4;i++) {
        memcpy(page,model17c_setter_expected,16);((unsigned int *)page)[i]^=1;
        unsigned char saved[16];memcpy(saved,page,16);
        install_model17c_observer(base);expect_probe(-EILSEQ);
        assert(!protect_calls && !cache_calls && !memcmp(page,saved,16));
    }
    memcpy(page,model17c_setter_expected,16);
    fail_read=1;install_model17c_observer(base);fail_read=0;expect_probe(-EIO);
    assert(!protect_calls && strstr(probe,"read_rc=-1"));
    partial_read=1;install_model17c_observer(base);partial_read=0;expect_probe(-EIO);
    assert(!protect_calls && strstr(probe,"read_rc=8 read_errno=0"));
    fail_open=1;install_model17c_observer(base);fail_open=0;expect_probe(-EACCES);
    snprintf(identity,sizeof identity,"open_rc=-1 open_errno=%d",EACCES);assert(strstr(probe,identity));
    assert(!protect_calls && !memcmp(page,model17c_setter_expected,16));
    fail_protect=1;install_model17c_observer(base);expect_probe(-EPERM);
    assert(protect_calls==1 && !cache_calls && !memcmp(page,model17c_setter_expected,16));
    /* Exercise the shared check too, independently of the model-specific preflight. */
    ((unsigned int *)page)[3]^=1;
    assert(arm_entry_probe((unsigned long)page,model17c_setter_expected,
        model17c_setter_trampoline,NULL,"negative")==-EILSEQ);
    assert(protect_calls==1);
    memcpy(page,model17c_setter_expected,16);protect_calls=0;fail_protect=2;errno=EDOM;
    install_model17c_observer(base);expect_probe(-EPERM);
    assert(protect_calls==2 && cache_calls==1);
    assert(((unsigned int *)page)[0]==0x58000050 && ((unsigned int *)page)[1]==0xd61f0200);
    memcpy(page,model17c_setter_expected,16);protect_calls=0;cache_calls=0;fail_protect=0;
    install_model17c_observer(base);expect_probe(0);
    assert(protect_calls==2 && cache_calls==1 && model17c_observer_enabled==1);
    assert(model17c_setter_continue==page+16);
    assert(*(unsigned long *)(page+8)==(unsigned long)model17c_setter_trampoline);
    assert(!model17c_restore_continue && !model17c_publish_continue);
    assert(*current==0x81 && munmap(page,(size_t)page_size)==0);
    return 0;
}
'''
    source = tmp_path / 'model17c-observation.c'
    source.write_text(harness)
    binary = tmp_path / 'model17c-observation'
    subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(source),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)


def test_model17c_actual_restore_callback_literal_and_install_refusals(tmp_path):
    arm, callback, install = _extracted_model17c()
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
static unsigned long appfw_base,test_base,literal_address;
static unsigned callbacks,publish_callbacks,baselines,opens,reads,protects,caches,entry_reads;
static unsigned fail_open,fail_close,fail_protect,read_mode;
static long offsets[32];
static unsigned long sizes[32];
static char last[2048],published[2048],baseline[2048],probe[1024],setter_probe[1024],publish_probe[1024];
static void record(const char *prefix,const char *text) {
    assert(strlen(text)<2048);
    if(!strcmp(prefix,"SHUTTER_DETAIL_MODEL17C ")) {
        if(strstr(text,"site=restore")){callbacks++;snprintf(last,sizeof last,"%s",text);}
        else {assert(strstr(text,"site=publish"));publish_callbacks++;snprintf(published,sizeof published,"%s",text);}
    } else if(!strcmp(prefix,"SHUTTER_DETAIL_MODEL17C_BASELINE ")) {
        assert(!protects);baselines++;snprintf(baseline,sizeof baseline,"%s",text);
    } else if(!strcmp(prefix,"SHUTTER_DETAIL_MODEL17C_PROBE ")) {
        snprintf(strstr(text,"site=setter")?setter_probe:strstr(text,"site=publish")?publish_probe:probe,1024,"%s",text);
    } else assert(!strncmp(prefix,"ENTRY_PROBE_",12));
    errno=ENOTTY;
}
static int observe_open(const char *path,int flags) {
    assert(!strcmp(path,"/proc/self/mem") && flags==0);opens++;
    if(fail_open){errno=EACCES;return -1;}
    return open(path,flags);
}
static int observe_close(int fd) {
    int rc=close(fd);
    if(fail_close){errno=EIO;return -1;}
    return rc;
}
static long observe_pread(int fd,void *out,unsigned long size,long offset) {
    assert(size==4 || size==8 || size==16);
    if(reads<32){offsets[reads]=offset;sizes[reads]=size;}reads++;
    unsigned mode=0;
    if((unsigned long)offset==test_base+0x2aa31bcUL) {
        assert(size==16);entry_reads++;
        if(entry_reads==1 && (read_mode==1 || read_mode==2))mode=read_mode;
        if(entry_reads==2 && read_mode>=6 && read_mode<=8)mode=read_mode;
    } else if((unsigned long)offset==literal_address) {
        assert(size==8);if(read_mode>=3 && read_mode<=5)mode=read_mode;
    } else if((unsigned long)offset==test_base+0x7e5d570UL) {
        assert(size==4);if(read_mode==9 || read_mode==10)mode=read_mode;
    } else if((unsigned long)offset==test_base+0x835f8d0UL) {
        assert(size==4);if(read_mode==11 || read_mode==12)mode=read_mode;
    } else if((unsigned long)offset==test_base+0x7e5d578UL ||
              (unsigned long)offset==test_base+0x7e5d588UL) {assert(size==4);}
    else if((unsigned long)offset==test_base+0x7e5d580UL) {assert(size==8);}
    else if((unsigned long)offset==test_base+0x2aeff5cUL) {assert(size==16);}
    else if((unsigned long)offset==test_base+0x835f8d4UL) {assert(size==4);}
    else assert((unsigned long)offset==test_base+0x267b698UL && size==16);
    if(mode==1 || mode==6 || mode==9 || mode==11){errno=EIO;return -1;}
    if(mode==3){errno=EFAULT;return -1;}
    long rc=pread(fd,out,mode==2 || mode==4 || mode==7 || mode==10 || mode==12?size/2:size,offset);
    if((mode==5 || mode==8) && rc==(long)size)((unsigned char *)out)[0]^=1;
    return rc;
}
static int observe_mprotect(void *page,unsigned long size,int protection) {
    assert(size==4096 && (protection==7 || protection==5));
    assert((unsigned long)page==((test_base+0x2aa31bcUL)&~0xfffUL) ||
           (unsigned long)page==((test_base+0x267b698UL)&~0xfffUL) ||
           (unsigned long)page==((test_base+0x2aeff5cUL)&~0xfffUL));
    protects++;
    if(protects==fail_protect){errno=EPERM;return -1;}
    return 0; /* The actual AArch64 entry stub is data and is never executed here. */
}
static void clear_cache_range(void *address,unsigned long size) {
    assert(size==16 && ((unsigned long)address==test_base+0x2aa31bcUL ||
                       (unsigned long)address==test_base+0x267b698UL ||
                       (unsigned long)address==test_base+0x2aeff5cUL));caches++;
}
static long observe_syscall(long number) {
    assert(number==178);return syscall(SYS_gettid);
}
static void model17c_setter_trampoline(void) {}
static void model17c_restore_trampoline(void) {}
static void model17c_publish_trampoline(void) {}
#define open observe_open
#define close observe_close
#define pread observe_pread
#define mprotect observe_mprotect
#define syscall observe_syscall
''' + arm + callback + install + r'''
#undef open
#undef close
#undef pread
#undef mprotect
#undef syscall
static void reset_probe(unsigned long base) {
    appfw_base=test_base=base;
    model17c_restore_base=model17c_restore_adrp_page=0;
    model17c_restore_continue=NULL;
    model17c_restore_enabled=model17c_restore_seen=0;
    model17c_publish_enabled=model17c_publish_seen=0;
    model17c_publish_base=0;model17c_publish_continue=NULL;
    literal_address=(unsigned long)&model17c_restore_adrp_page;
    opens=reads=protects=caches=entry_reads=0;
    callbacks=publish_callbacks=baselines=0;
    fail_open=fail_close=fail_protect=read_mode=0;
    probe[0]=setter_probe[0]=publish_probe[0]=published[0]=baseline[0]=last[0]=0;
    memcpy((void *)(base+0x2aa31bcUL),model17c_restore_expected,16);
    memcpy((void *)(base+0x2aeff5cUL),model17c_publish_expected,16);
    errno=EDOM;
}
static void expect_rc(int rc,unsigned attempted) {
    char expected[80];snprintf(expected,sizeof expected,"rc=%d errno=%d",rc,rc<0?-rc:0);
    assert(strstr(probe,expected));
    snprintf(expected,sizeof expected,"arm_attempted=%u",attempted);assert(strstr(probe,expected));
    assert(strstr(probe,"original_store_observed=0 return_not_observed=1") && errno==EDOM);
}
static void expect_values(const char *text) {
    assert(strstr(text,"model_id=0x17c") && strstr(text,"current_before=0x1 saved_u32=0x7"));
    assert(strstr(text,"descriptor0=0x9 descriptor8=0x12345678 descriptor10=0xb"));
    assert(strstr(text,"saved_source=descriptor0_via_2aa319c alias_unproven=1"));
    assert(strstr(text,"read_order=current_u32/saved_u32/descriptor0_u32/descriptor8_u64/descriptor10_u32"));
    assert(strstr(text,"reads=4/4/4/8/4"));
    assert(strstr(text,"read_errno=0/0/0/0/0"));
    assert(strstr(text,"atomic_snapshot=0") && strstr(text,"original_store_observed=0"));
    assert(strstr(text,"return_not_observed=1 original_return_observed=0 return_unknown=1"));
}
int main(void) {
    long page_size=sysconf(_SC_PAGESIZE);assert(page_size==4096);
    unsigned long length=0x8360000UL;
    void *image=mmap(NULL,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    void *image2=mmap(NULL,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(image!=MAP_FAILED && image2!=MAP_FAILED && image!=image2);
    unsigned long base=(unsigned long)image,base2=(unsigned long)image2;
    unsigned int *current=(unsigned int *)(base+0x7e5d570UL);
    unsigned int *saved=(unsigned int *)(base+0x835f8d0UL);
    *current=1;*saved=7;
    *(unsigned int *)(base+0x7e5d578UL)=9;
    *(unsigned long *)(base+0x7e5d580UL)=0x12345678;
    *(unsigned int *)(base+0x7e5d588UL)=11;
    reset_probe(base);
    unsigned long caller=base+0x2aa3190UL;
    capture_model17c_restore(caller);
    assert(!callbacks && !opens && !reads && errno==EDOM);
    unsigned long page=0xdeadbeefUL;
    assert(model17c_restore_page(base,0xf002c573u,&page)==0 && page==base+0x8352000UL);
    assert(model17c_restore_page(base2,0xf002c573u,&page)==0 && page==base2+0x8352000UL);
    const unsigned int invalid_opcodes[]={0xf002c572u,0xf002c553u,0xd002c573u,0x7002c573u,0x73c502f0u};
    for(unsigned i=0;i<sizeof invalid_opcodes/sizeof *invalid_opcodes;i++) {
        page=0xdeadbeefUL;
        assert(model17c_restore_page(base,invalid_opcodes[i],&page)==-ENOTSUP && page==0xdeadbeefUL);
    }
    assert(model17c_restore_page(base,0xf002c573u,NULL)==-EFAULT);
    page=0xdeadbeefUL;
    assert(model17c_restore_page(0,0xf002c573u,&page)==-EFAULT && page==0xdeadbeefUL);
    assert(model17c_restore_page(base+1,0xf002c573u,&page)==-ENOTSUP && page==0xdeadbeefUL);
    assert(model17c_restore_page(~0xfffUL,0xf002c573u,&page)==-EOVERFLOW && page==0xdeadbeefUL);
    assert(model17c_restore_page(0x7ffffffff8000000UL,0xf002c573u,&page)==-EOVERFLOW);
    model17c_restore_base=base;model17c_restore_enabled=1;model17c_observer_seen=16;
    capture_model17c_restore(caller);expect_values(last);
    assert(callbacks==1 && model17c_restore_seen==1 && errno==EDOM);
    assert(reads==5 && offsets[0]==(long)(base+0x7e5d570UL) && sizes[0]==4);
    assert(offsets[1]==(long)(base+0x835f8d0UL) && sizes[1]==4);
    assert(strstr(last,"site=restore n=1") && strstr(last,"quota=model17c_restore16"));
    assert(strstr(last,"phase=before_store") && strstr(last,"caller_app=0x2aa3190"));
    char field[96];snprintf(field,sizeof field,"caller_raw=%#lx",caller);assert(strstr(last,field));
    snprintf(field,sizeof field,"pid=%d tid=%ld",getpid(),syscall(SYS_gettid));assert(strstr(last,field));
    read_mode=10;capture_model17c_restore(caller);assert(strstr(last,"reads=2/4/4/8/4"));
    read_mode=12;capture_model17c_restore(caller);assert(strstr(last,"reads=4/2/4/8/4"));
    read_mode=9;capture_model17c_restore(caller);assert(strstr(last,"reads=-1/4/4/8/4"));
    snprintf(field,sizeof field,"read_errno=%d/0/",EIO);assert(strstr(last,field));
    read_mode=11;capture_model17c_restore(caller);assert(strstr(last,"reads=4/-1/4/8/4"));
    snprintf(field,sizeof field,"read_errno=0/%d/",EIO);assert(strstr(last,field));
    read_mode=0;fail_open=1;capture_model17c_restore(caller);fail_open=0;
    snprintf(field,sizeof field,"open_rc=-1 open_errno=%d",EACCES);assert(strstr(last,field));
    assert(strstr(last,"reads=-1/-1/-1/-1/-1"));
    fail_close=1;capture_model17c_restore(caller);fail_close=0;
    snprintf(field,sizeof field,"close_rc=-1 close_errno=%d",EIO);assert(strstr(last,field));
    model17c_restore_base=0;capture_model17c_restore(caller);
    snprintf(field,sizeof field,"read_errno=%d/%d/",EFAULT,EFAULT);assert(strstr(last,field));
    model17c_restore_base=~0xfffUL;capture_model17c_restore(caller);
    snprintf(field,sizeof field,"read_errno=%d/%d/",EOVERFLOW,EOVERFLOW);assert(strstr(last,field));
    model17c_restore_base=base;
    for(unsigned i=0;i<30;i++)capture_model17c_restore(caller);
    assert(callbacks==16 && model17c_restore_seen==16 && model17c_observer_seen==16 && errno==EDOM);
    unsigned old_opens=opens,old_reads=reads;
    capture_model17c_restore(caller);assert(opens==old_opens && reads==old_reads && callbacks==16);
    model17c_observe_values(base,0,0,1,0);expect_values(baseline);
    assert(baselines==1 && reads==old_reads+5 && model17c_restore_seen==16);
    assert(strstr(baseline,"site=baseline n=0") && strstr(baseline,"phase=install_before_arm"));
    assert(*current==1 && *saved==7 && errno==EDOM);
    for(unsigned i=0;i<4;i++) {
        reset_probe(base);((unsigned int *)(base+0x2aa31bcUL))[i]^=1;
        unsigned char before[16];memcpy(before,(void *)(base+0x2aa31bcUL),16);
        install_model17c_restore_observer(base);expect_rc(-EILSEQ,0);
        assert(!protects && !caches && !model17c_restore_adrp_page);
        assert(!memcmp(before,(void *)(base+0x2aa31bcUL),16));
    }
    reset_probe(base);read_mode=1;install_model17c_restore_observer(base);expect_rc(-EIO,0);
    assert(!protects && strstr(probe,"read_rc=-1"));
    reset_probe(base);read_mode=2;install_model17c_restore_observer(base);expect_rc(-EIO,0);
    assert(!protects && strstr(probe,"read_rc=8 read_errno=0"));
    reset_probe(base);fail_open=1;install_model17c_restore_observer(base);expect_rc(-EACCES,0);
    assert(!protects && !reads);
    for(unsigned mode=3;mode<=5;mode++) {
        reset_probe(base);read_mode=mode;install_model17c_restore_observer(base);
        expect_rc(mode==3?-EFAULT:mode==4?-EIO:-EILSEQ,0);
        assert(!protects && !caches && !model17c_restore_enabled);
        assert(!memcmp((void *)(base+0x2aa31bcUL),model17c_restore_expected,16));
        if(mode==3)assert(strstr(probe,"literal_read_rc=-1"));
        if(mode==4)assert(strstr(probe,"literal_read_rc=4 literal_read_errno=0"));
        if(mode==5)assert(strstr(probe,"literal_read_rc=8 literal_read_errno=0"));
    }
    reset_probe(base);fail_protect=1;install_model17c_restore_observer(base);expect_rc(-EPERM,1);
    assert(protects==1 && !caches && !memcmp((void *)(base+0x2aa31bcUL),model17c_restore_expected,16));
    reset_probe(base);fail_protect=2;install_model17c_restore_observer(base);expect_rc(-EPERM,1);
    assert(protects==2 && caches==1);
    assert(((unsigned int *)(base+0x2aa31bcUL))[0]==0x58000050u);
    assert(((unsigned int *)(base+0x2aa31bcUL))[1]==0xd61f0200u);
    for(unsigned mode=6;mode<=8;mode++) {
        reset_probe(base);read_mode=mode;install_model17c_restore_observer(base);
        expect_rc(mode==8?-EILSEQ:-EIO,1);assert(protects==2 && caches==1);
        if(mode==6)assert(strstr(probe,"patch_read_rc=-1"));
        if(mode==7)assert(strstr(probe,"patch_read_rc=8 patch_read_errno=0"));
    }
    reset_probe(base);fail_protect=2;read_mode=6;
    install_model17c_restore_observer(base);expect_rc(-EPERM,1);
    snprintf(field,sizeof field,"arm_rc=%d arm_errno=%d",-EPERM,EPERM);assert(strstr(probe,field));
    assert(strstr(probe,"patch_read_rc=-1"));
    reset_probe(base);fail_close=1;install_model17c_restore_observer(base);expect_rc(0,1);
    snprintf(field,sizeof field,"close_rc=-1 close_errno=%d",EIO);assert(strstr(probe,field));
    fail_close=0;
    assert(protects==2 && caches==1 && model17c_restore_enabled==1);
    assert(model17c_restore_adrp_page==base+0x8352000UL && model17c_restore_base==base);
    assert(model17c_restore_continue==(void *)(base+0x2aa31ccUL));
    unsigned long stub_literal=0;
    memcpy(&stub_literal,(void *)(base+0x2aa31c4UL),8);
    assert(stub_literal==(unsigned long)model17c_restore_trampoline);
    assert(strstr(probe,"literal_read_rc=8 literal_read_errno=0") && strstr(probe,"patch_read_rc=16"));
    /* An armed/possibly armed literal belongs to one original image base for its lifetime. */
    memcpy((void *)(base2+0x2aa31bcUL),model17c_restore_expected,16);
    test_base=base2;entry_reads=0;
    install_model17c_restore_observer(base2);expect_rc(-ENOTSUP,0);
    assert(protects==2 && caches==1 && model17c_restore_base==base);
    assert(model17c_restore_adrp_page==base+0x8352000UL);
    assert(!memcmp((void *)(base2+0x2aa31bcUL),model17c_restore_expected,16));
    reset_probe(base2);install_model17c_restore_observer(base2);expect_rc(0,1);
    assert(model17c_restore_adrp_page==base2+0x8352000UL && model17c_restore_base==base2);
    assert(model17c_restore_continue==(void *)(base2+0x2aa31ccUL));
    reset_probe(base);test_base=base+1;
    memcpy((void *)(test_base+0x2aa31bcUL),model17c_restore_expected,16);
    install_model17c_restore_observer(test_base);expect_rc(-ENOTSUP,0);assert(!protects && !caches);
    reset_probe(base);install_model17c_restore_observer(0);expect_rc(-EFAULT,0);
    assert(!protects && !reads);
    reset_probe(base);install_model17c_restore_observer(~0xfffUL);expect_rc(-EOVERFLOW,0);
    assert(!protects && !reads);
    reset_probe(base);memcpy((void *)(base+0x267b698UL),model17c_setter_expected,16);
    install_model17c_observer(base);expect_rc(0,1);expect_values(baseline);
    assert(baselines==1 && !callbacks && !model17c_restore_seen);
    assert(offsets[0]==(long)(base+0x7e5d570UL) && offsets[1]==(long)(base+0x835f8d0UL));
    assert(sizes[0]==4 && sizes[1]==4 && protects==6 && caches==3);
    assert(model17c_observer_enabled==1 && strstr(setter_probe,"rc=0 errno=0"));
    assert(model17c_setter_continue==(void *)(base+0x267b6a8UL));
    assert(model17c_restore_continue==(void *)(base+0x2aa31ccUL));
    assert(model17c_publish_continue==(void *)(base+0x2aeff6cUL) && model17c_publish_enabled);
    unsigned int *input=(unsigned int *)(base+0x835f8d4UL);*input=0xfeedbeef;
    capture_model17c_publish((unsigned long)input,caller);expect_values(published);
    assert(strstr(published,"site=publish n=1") && strstr(published,"input_u32=0xfeedbeef input_rc=4 input_errno=0"));
    assert(strstr(published,"quota=model17c_publish16") && model17c_publish_seen==1 && *input==0xfeedbeef);
    for(unsigned i=0;i<30;i++)capture_model17c_publish((unsigned long)input,caller);
    assert(publish_callbacks==16 && model17c_publish_seen==16 && errno==EDOM);
    old_opens=opens;capture_model17c_publish(0,caller);assert(opens==old_opens);
    model17c_publish_seen=0;capture_model17c_publish(0,caller);
    snprintf(field,sizeof field,"input_rc=-1 input_errno=%d",EFAULT);assert(strstr(published,field));
    assert(*current==1 && *saved==7 && errno==EDOM);
    for(unsigned i=0;i<4;i++) {
        reset_probe(base);((unsigned int *)(base+0x2aeff5cUL))[i]^=1;
        unsigned char before[16];memcpy(before,(void *)(base+0x2aeff5cUL),16);
        install_model17c_publish_observer(base);
        assert(strstr(publish_probe,"rc=-84") && strstr(publish_probe,"arm_attempted=0"));
        assert(!protects && !caches && !memcmp(before,(void *)(base+0x2aeff5cUL),16));
    }
    reset_probe(base);fail_protect=1;install_model17c_publish_observer(base);
    assert(strstr(publish_probe,"rc=-1 errno=1") && protects==1 && !caches);
    reset_probe(base);install_model17c_publish_observer(base);
    assert(strstr(publish_probe,"rc=0 errno=0") && model17c_publish_enabled && protects==2 && caches==1);
    assert(munmap(image,length)==0 && munmap(image2,length)==0);
    return 0;
}
'''
    source = tmp_path / 'model17c-restore-observation.c'
    source.write_text(harness)
    binary = tmp_path / 'model17c-restore-observation'
    subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(source),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)
