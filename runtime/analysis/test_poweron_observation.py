"""Deferred strict host checks for production read-only power-on observations.

The two entry byte windows are inherited evidence; these checks do not read new
original ELF bytes or supply any firmware input. The parent runs this module in
its integrated batch. AArch64 trampolines are inspected and never executed here.
"""
from pathlib import Path
import re
import struct
import subprocess

import pytest


BASE = Path(__file__).resolve().parent
SOURCE = (BASE / 'menu-observe.c').read_text()
DISPATCH_FIRST16 = bytes.fromhex('fd7bbca9fd030091f35301a9f30300aa')
CALLBACK_FIRST16 = bytes.fromhex('fd7bbea901008052fd030091f30b00f9')


def _extracted_poweron():
    start = SOURCE.index('static long model17c_observe_read(')
    reader = SOURCE[start:SOURCE.index('void capture_model17c_setter(', start)]
    start = SOURCE.index('static int model17c_arm_readonly_entry(')
    arm = SOURCE[start:SOURCE.index('static void install_model17c_restore_observer(', start)]
    start = SOURCE.index('/* Read-only power-on entry observations. */')
    end = SOURCE.index('static void install_shutter_detail_trace(unsigned long base) {', start)
    block = SOURCE[start:end]
    callbacks = block[:block.index('__asm__(')]
    install = block[block.index('static void install_poweron_observers('):]
    return reader, arm, callbacks, install


@pytest.mark.parametrize('site,first16,entry', [
    ('dispatch', DISPATCH_FIRST16, 0x1951844),
    ('callback', CALLBACK_FIRST16, 0x209f300),
])
def test_poweron_inherited_first16_and_original_entry_replay(site, first16, entry):
    match = re.search(rf'poweron_{site}_expected\[4\]\s*=\s*\{{([^}}]+)\}};', SOURCE)
    assert match
    expected = [int(word, 16) for word in re.findall(r'0x[0-9a-f]+', match[1])]
    assert struct.pack('<4I', *expected) == first16
    start = SOURCE.index(f'poweron_{site}_trampoline:\\n')
    trampoline = SOURCE[start:SOURCE.index('br x16\\n', start)]
    replay = [int(word, 16) for word in re.findall(r'\.inst (0x[0-9a-f]+)', trampoline)]
    assert struct.pack('<4I', *replay) == first16
    assert trampoline.count('PROBE_SAVE_ARGS') == trampoline.count('PROBE_RESTORE_ARGS') == 1
    assert trampoline.index('PROBE_SAVE_ARGS') < trampoline.index(f'bl capture_poweron_{site}')
    assert trampoline.index(f'bl capture_poweron_{site}') < trampoline.index('PROBE_RESTORE_ARGS')
    assert trampoline.index('PROBE_RESTORE_ARGS') < trampoline.index('.inst')
    moves = ('mov w1, w2', 'mov x2, x30') if site == 'dispatch' else ('mov x1, x30',)
    for move in moves:
        assert trampoline.index(move) < trampoline.index(f'bl capture_poweron_{site}')
    if site == 'dispatch':
        assert trampoline.index('mov w1, w2') < trampoline.index('mov x2, x30')
    preparation = trampoline[trampoline.index('PROBE_SAVE_ARGS'):trampoline.index(f'bl capture_poweron_{site}')]
    assert not re.search(r'\b(?:mov|ldr|add|sub) x0,', preparation)
    assert f'adrp x16, poweron_{site}_continue' in trampoline
    assert f'ldr x16, [x16, #:lo12:poweron_{site}_continue]' in trampoline
    assert f'static void *poweron_{site}_continue __attribute__((used));' in SOURCE
    assert f'0x{entry:x}' in SOURCE
    assert '*continuations[site] = (void *)(base + offsets[site] + 16UL);' in SOURCE
    assert entry % 4 == 0
    if site == 'dispatch':
        assert entry % 8 == 4  # The inherited dispatcher entry cannot hold an aligned u64 store.
    for word in replay:
        assert word & 0x1f000000 != 0x10000000  # ADR/ADRP.
        assert word & 0x7c000000 != 0x14000000  # B/BL immediate.
        assert word & 0xff000010 != 0x54000000  # B.cond.
        assert word & 0x7e000000 not in (0x34000000, 0x36000000)  # CB/TB immediate.
        assert word & 0x3b000000 != 0x18000000  # Literal load.


def test_poweron_default_off_existing_flow_gate_and_register_contract():
    start = SOURCE.index('static void install_shutter_detail_trace(unsigned long base) {')
    install = SOURCE[start:SOURCE.index('/* Natural startup frontier:', start)]
    assert 'static unsigned int poweron_observer_enabled[2], poweron_observer_seen[2];' in SOURCE
    assert install.index('if (!mode) return;') < install.index('if (flows) install_poweron_observers(base);')
    assert 'int flows = all || same_name(mode, "flow");' in install
    assert SOURCE.count('if (flows) install_poweron_observers(base);') == 1
    assert len(re.findall(r'\binstall_poweron_observers\s*\(', SOURCE)) == 2
    start = SOURCE.index('/* Read-only power-on entry observations. */')
    assert SOURCE.index('/* Read-only shutter detail probes.') < start
    block = SOURCE[start:SOURCE.index('static void install_shutter_detail_trace(unsigned long base) {', start)]
    assert 'getenv(' not in block
    assert not re.search(r'getenv\("[^"\n]*POWERON', SOURCE, re.I)
    assert '"SHUTTER_DETAIL_POWERON "' in block
    assert '"SHUTTER_DETAIL_POWERON_PROBE "' in block
    assert '"SHUTTER_DETAIL_"' in SOURCE
    save = SOURCE[SOURCE.index('#define PROBE_SAVE_ARGS'):SOURCE.index('#define PROBE_RESTORE_ARGS')]
    restore = SOURCE[SOURCE.index('#define PROBE_RESTORE_ARGS'):SOURCE.index('void capture_manager(')]
    for left, right, offset in [('x0', 'x1', 0), ('x2', 'x3', 16), ('x4', 'x5', 32),
                                ('x6', 'x7', 48), ('x8', 'x30', 64), ('q0', 'q1', 80),
                                ('q2', 'q3', 112), ('q4', 'q5', 144), ('q6', 'q7', 176)]:
        assert f'stp {left}, {right}, [sp, #{offset}]' in save
        assert f'ldp {left}, {right}, [sp, #{offset}]' in restore
    assert 'mrs x16, nzcv' in save and 'str x16, [sp, #208]' in save
    assert 'ldr x16, [sp, #208]' in restore and 'msr nzcv, x16' in restore
    assert 'sub sp, sp, #0xe0' in save and 'add sp, sp, #0xe0' in restore


def test_poweron_callback_readonly_boundary_and_shared_unaligned_stub():
    reader, arm, callbacks, install = _extracted_poweron()
    assert not re.search(r'\b(?:pwrite|memcpy|memset|mprotect|osal_\w+|send\w*|set\w*)\s*\(', callbacks)
    assert not re.search(r'\*\s*\(\s*(?:volatile\s+)?(?:unsigned\s+)?(?:int|long|char)\s*\*', callbacks)
    assert 'model17c_observe_read(' in callbacks
    assert 'pread(' in reader and '0x7fffffffffffffffUL' in reader
    assert 'model17c_arm_readonly_entry(' in install
    assert not re.search(r'\barm_entry_probe\s*\(', install)
    assert 'code[2] = (unsigned int)address;' in arm
    assert 'code[3] = (unsigned int)(address >> 32);' in arm
    assert not re.search(r'\*\s*\(unsigned long\s*\*\)', arm)


def test_poweron_actual_callbacks_and_installer_refusals(tmp_path):
    reader, arm, callbacks, install = _extracted_poweron()
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
static const unsigned long entry_offsets[2]={0x1951844UL,0x209f300UL};
static const unsigned long field_offsets[3]={0x7e5d570UL,0x7e6a7c8UL,0x7e739a8UL};
static const unsigned long field_sizes[7]={8,2,1,1,4,4,4};
static unsigned long test_base,controller_address;
static unsigned opens,reads,closes,callbacks[2],probe_count[2],protects[2],caches[2],entry_reads[2];
static unsigned fail_open,fail_close,fail_field=7,field_mode;
static unsigned fail_entry=2,entry_occurrence,entry_mode,patch_word;
static unsigned fail_protect=2,protect_occurrence;
static unsigned long read_addresses[32],read_sizes[32];
static char last[2][2048],probe[2][1024];
static void record(const char *prefix,const char *text) {
    unsigned site=strstr(text,"site=callback")!=NULL;
    if(!strcmp(prefix,"SHUTTER_DETAIL_POWERON ")) {
        assert(strlen(text)<sizeof last[site]);callbacks[site]++;
        snprintf(last[site],sizeof last[site],"%s",text);
    } else if(!strcmp(prefix,"SHUTTER_DETAIL_POWERON_PROBE ")) {
        assert(strlen(text)<sizeof probe[site]);probe_count[site]++;
        snprintf(probe[site],sizeof probe[site],"%s",text);
    } else assert(!strcmp(prefix,"ENTRY_PROBE_ARMED "));
    errno=ENOTTY;
}
static int observe_open(const char *path,int flags) {
    assert(!strcmp(path,"/proc/self/mem") && flags==O_RDONLY);opens++;
    if(fail_open){errno=EACCES;return -1;}
    return open(path,flags);
}
static int observe_close(int fd) {
    int rc=close(fd);closes++;
    if(fail_close){errno=EIO;return -1;}
    errno=EBUSY;return rc;
}
static long observe_pread(int fd,void *out,unsigned long size,long offset) {
    unsigned mode=0;
    if(reads<32){read_addresses[reads]=(unsigned long)offset;read_sizes[reads]=size;}reads++;
    if(size==16) {
        unsigned site=(unsigned long)offset==test_base+entry_offsets[1];
        assert((unsigned long)offset==test_base+entry_offsets[site]);
        entry_reads[site]++;
        if(site==fail_entry && entry_reads[site]==entry_occurrence)mode=entry_mode;
    } else {
        const unsigned long addresses[7]={controller_address,controller_address+0x300UL,
            controller_address+0x302UL,controller_address+0x303UL,
            test_base+field_offsets[0],test_base+field_offsets[1],test_base+field_offsets[2]};
        unsigned field=0;
        while(field<7 && (addresses[field]!=(unsigned long)offset || field_sizes[field]!=size))field++;
        assert(field<7);
        if(field==fail_field)mode=field_mode;
    }
    if(mode==1){errno=EIO;return -1;}
    long rc=pread(fd,out,mode==2?size/2:size,offset);
    if(mode==3 && rc==(long)size){assert(size==16 && patch_word<4);((unsigned int *)out)[patch_word]^=1;}
    if(rc>=0)errno=ENOSPC;
    return rc;
}
static int observe_mprotect(void *page,unsigned long size,int protection) {
    unsigned site=(unsigned long)page==((test_base+entry_offsets[1])&~0xfffUL);
    assert((unsigned long)page==((test_base+entry_offsets[site])&~0xfffUL));
    assert(size==4096 && (protection==7 || protection==5));protects[site]++;
    if(site==fail_protect && protects[site]==protect_occurrence){errno=EPERM;return -1;}
    return 0; /* Entry patches are observed as data; never execute the ARM stubs on this host. */
}
static void clear_cache_range(void *address,unsigned long size) {
    unsigned site=(unsigned long)address==test_base+entry_offsets[1];
    assert((unsigned long)address==test_base+entry_offsets[site] && size==16);caches[site]++;
}
static long observe_syscall(long number) {
    assert(number==178);return syscall(SYS_gettid);
}
static void poweron_dispatch_trampoline(void) {}
static void poweron_callback_trampoline(void) {}
#define open observe_open
#define close observe_close
#define pread observe_pread
#define mprotect observe_mprotect
#define syscall observe_syscall
''' + reader + arm + callbacks + install + r'''
#undef open
#undef close
#undef pread
#undef mprotect
#undef syscall
static void reset_probe(unsigned long base) {
    test_base=base;poweron_observer_base=0;
    poweron_dispatch_continue=poweron_callback_continue=NULL;
    opens=reads=closes=0;
    fail_open=fail_close=field_mode=entry_occurrence=entry_mode=patch_word=protect_occurrence=0;
    fail_field=7;fail_entry=fail_protect=2;
    for(unsigned site=0;site<2;site++) {
        callbacks[site]=probe_count[site]=protects[site]=caches[site]=entry_reads[site]=0;
        poweron_observer_enabled[site]=poweron_observer_seen[site]=0;
        last[site][0]=probe[site][0]=0;
        memcpy((void *)(base+entry_offsets[site]),
            site?poweron_callback_expected:poweron_dispatch_expected,16);
    }
    errno=EDOM;
}
static void enable_callbacks(unsigned long base) {
    reset_probe(base);poweron_observer_base=base;
    poweron_observer_enabled[0]=poweron_observer_enabled[1]=1;
}
static void expect_observation(unsigned site) {
    const char *text=last[site];char field[96];
    assert(strstr(text,site?"site=callback ":"site=dispatch "));
    snprintf(field,sizeof field,"pid=%d tid=%ld",getpid(),syscall(SYS_gettid));assert(strstr(text,field));
    snprintf(field,sizeof field,"base=%#lx controller=%#lx",poweron_observer_base,controller_address);
    assert(strstr(text,field));
    assert(strstr(text,site?"raw_u32=0 raw_known=0 numeric_route_match=0":
                                  "raw_known=1 numeric_route_match=1"));
    assert(strstr(text,"quota=poweron_entry16 observation_only=1 atomic_snapshot=0 phase=entry"));
    assert(strstr(text,"original_branch_observed=0 original_store_observed=0 original_return_observed=0"));
    assert(strstr(text,"event_id_unverified=1 producer_unknown=1 capture_verified=0") && errno==EDOM);
}
static void expect_read_results(unsigned site,const long results[7],const int errors[7]) {
    char expected[256];
    snprintf(expected,sizeof expected,"reads=%ld/%ld/%ld/%ld/%ld/%ld/%ld read_errno=%d/%d/%d/%d/%d/%d/%d",
        results[0],results[1],results[2],results[3],results[4],results[5],results[6],
        errors[0],errors[1],errors[2],errors[3],errors[4],errors[5],errors[6]);
    assert(strstr(last[site],expected) && errno==EDOM);
}
static void expect_probe(unsigned site,int rc,unsigned attempted) {
    char field[96];
    assert(probe_count[site]==1 && strstr(probe[site],site?"site=callback ":"site=dispatch "));
    snprintf(field,sizeof field,"rc=%d errno=%d",rc,rc<0?-rc:0);assert(strstr(probe[site],field));
    snprintf(field,sizeof field,"arm_attempted=%u",attempted);assert(strstr(probe[site],field));
    assert(strstr(probe[site],"observation_only=1 original_branch_observed=0 original_store_observed=0 original_return_observed=0"));
    assert(errno==EDOM);
}
static void expect_stub(unsigned long base,unsigned site) {
    unsigned long address=(unsigned long)(site?poweron_callback_trampoline:poweron_dispatch_trampoline);
    const unsigned int stub[4]={0x58000050u,0xd61f0200u,(unsigned int)address,(unsigned int)(address>>32)};
    assert(!memcmp((void *)(base+entry_offsets[site]),stub,16));
}
int main(void) {
    _Static_assert(sizeof(unsigned long)==8 && sizeof(unsigned int)==4 && sizeof(unsigned short)==2,
                   "original scalar widths");
    assert(sysconf(_SC_PAGESIZE)==4096);
    const unsigned long length=0x7e74000UL;
    void *image=mmap(NULL,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    void *image2=mmap(NULL,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    unsigned char *controller=mmap(NULL,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
    assert(image!=MAP_FAILED && image2!=MAP_FAILED && controller!=MAP_FAILED);
    unsigned long base=(unsigned long)image,base2=(unsigned long)image2;
    controller_address=(unsigned long)controller;
    memset(controller,0x5a,4096);
    const unsigned long vptr=0x12345678abcdef00UL;
    memcpy(controller,&vptr,8);
    *(unsigned short *)(controller+0x300)=0xcdefu;controller[0x302]=0xa5;controller[0x303]=0x80;
    unsigned char controller_before[4096],globals_before[3][4096];
    memcpy(controller_before,controller,4096);
    const unsigned int values[3]={0x99aabbccu,0x11223344u,0x55667788u};
    for(unsigned i=0;i<3;i++) {
        void *page=(void *)((base+field_offsets[i])&~0xfffUL);
        memset(page,(int)(0x60+i),4096);
        *(unsigned int *)(base+field_offsets[i])=values[i];
        memcpy(globals_before[i],page,4096);
        assert(mprotect(page,4096,PROT_READ)==0);
    }
    assert(mprotect(controller,4096,PROT_READ)==0);
    const unsigned long caller=base+0x1951a10UL;
    reset_probe(base);
    capture_poweron_dispatch(controller_address,0x01000090u,caller);
    capture_poweron_callback(controller_address,caller);
    assert(!opens && !reads && !closes && !callbacks[0] && !callbacks[1] && errno==EDOM);
    assert(!poweron_observer_seen[0] && !poweron_observer_seen[1]);
    poweron_observer_base=base;poweron_observer_enabled[0]=poweron_observer_enabled[1]=1;
    for(unsigned bit=0;bit<32;bit++)if(0xff000fffu&(1u<<bit))
        for(unsigned i=0;i<4;i++)capture_poweron_dispatch(controller_address,0x01000090u^(1u<<bit),caller);
    assert(!opens && !reads && !callbacks[0] && !poweron_observer_seen[0] && errno==EDOM);
    capture_poweron_callback(controller_address,caller);expect_observation(1);
    assert(callbacks[1]==1 && poweron_observer_seen[1]==1 && !poweron_observer_seen[0]);
    assert(reads==7 && closes==1);
    const unsigned long expected_addresses[7]={controller_address,controller_address+0x300UL,
        controller_address+0x302UL,controller_address+0x303UL,
        base+field_offsets[0],base+field_offsets[1],base+field_offsets[2]};
    for(unsigned i=0;i<7;i++)assert(read_addresses[i]==expected_addresses[i] && read_sizes[i]==field_sizes[i]);
    const long good_reads[7]={8,2,1,1,4,4,4};const int good_errors[7]={0};
    expect_read_results(1,good_reads,good_errors);
    assert(strstr(last[1],"vptr=0x12345678abcdef00 field300=0xcdef field302=0xa5 field303=0x80"));
    assert(strstr(last[1],"current17c=0x99aabbcc model_m=0x11223344 model_k=0x55667788"));
    capture_poweron_dispatch(controller_address,0x01000090u,caller);expect_observation(0);
    assert(strstr(last[0],"n=1 ") && strstr(last[0],"raw_u32=0x1000090 raw_known=1"));
    char field[128];snprintf(field,sizeof field,"caller_raw=%#lx caller_app=0x1951a10",caller);
    assert(strstr(last[0],field));
    for(unsigned bit=0;bit<32;bit++)if(!(0xff000fffu&(1u<<bit))) {
        unsigned before=callbacks[0];unsigned int alias=0x01000090u|(1u<<bit);
        capture_poweron_dispatch(controller_address,alias,caller);
        assert(callbacks[0]==before+1);snprintf(field,sizeof field,"raw_u32=%#x raw_known=1",alias);
        assert(strstr(last[0],field));
    }
    capture_poweron_dispatch(controller_address,0x01fff090u,caller);
    assert(callbacks[0]==14 && callbacks[1]==1);
    for(unsigned i=0;i<40;i++)capture_poweron_dispatch(controller_address,0x01000090u,caller);
    assert(callbacks[0]==16 && poweron_observer_seen[0]==16 && poweron_observer_seen[1]==1);
    for(unsigned i=0;i<40;i++)capture_poweron_callback(controller_address,caller);
    assert(callbacks[1]==16 && poweron_observer_seen[1]==16);
    unsigned old_opens=opens,old_reads=reads,old_closes=closes;
    capture_poweron_dispatch(0,0x01000090u,caller);capture_poweron_callback(ULONG_MAX,caller);
    assert(opens==old_opens && reads==old_reads && closes==old_closes && errno==EDOM);
    for(unsigned index=0;index<7;index++)for(unsigned mode=1;mode<=2;mode++) {
        enable_callbacks(base);fail_field=index;field_mode=mode;
        capture_poweron_dispatch(controller_address,0x01000090u,caller);expect_observation(0);
        long results[7];int errors[7]={0};memcpy(results,good_reads,sizeof results);
        results[index]=mode==1?-1:(long)(field_sizes[index]/2);errors[index]=mode==1?EIO:0;
        expect_read_results(0,results,errors);assert(reads==7 && closes==1);
    }
    enable_callbacks(base);fail_open=1;capture_poweron_callback(controller_address,caller);
    expect_observation(1);snprintf(field,sizeof field,"open_rc=-1 open_errno=%d",EACCES);
    assert(strstr(last[1],field) && !reads && !closes && poweron_observer_seen[1]==1);
    const long absent_reads[7]={-1,-1,-1,-1,-1,-1,-1};
    const int bad_fd[7]={EBADF,EBADF,EBADF,EBADF,EBADF,EBADF,EBADF};
    expect_read_results(1,absent_reads,bad_fd);
    enable_callbacks(base);fail_close=1;capture_poweron_callback(controller_address,caller);
    expect_observation(1);snprintf(field,sizeof field,"close_rc=-1 close_errno=%d",EIO);
    assert(strstr(last[1],field) && reads==7 && closes==1);
    for(unsigned overflow=0;overflow<2;overflow++) {
        enable_callbacks(base);capture_poweron_callback(overflow?ULONG_MAX:0,caller);
        const long results[7]={-1,-1,-1,-1,4,4,4};int error=overflow?EOVERFLOW:EFAULT;
        const int errors[7]={error,error,error,error,0,0,0};expect_read_results(1,results,errors);
        assert(reads==3 && closes==1 && errno==EDOM);
        enable_callbacks(base);poweron_observer_base=overflow?ULONG_MAX:0;
        capture_poweron_callback(controller_address,caller);
        const long base_results[7]={8,2,1,1,-1,-1,-1};
        const int base_errors[7]={0,0,0,0,error,error,error};expect_read_results(1,base_results,base_errors);
        assert(reads==4 && closes==1 && errno==EDOM);
    }
    for(unsigned site=0;site<2;site++)for(unsigned word=0;word<4;word++) {
        reset_probe(base);((unsigned int *)(base+entry_offsets[site]))[word]^=1;
        unsigned char before[16];memcpy(before,(void *)(base+entry_offsets[site]),16);
        install_poweron_observers(base);expect_probe(site,-EILSEQ,0);expect_probe(1-site,0,1);
        assert(!protects[site] && !caches[site] && protects[1-site]==2 && caches[1-site]==1);
        assert(!poweron_observer_enabled[site] && poweron_observer_enabled[1-site]);
        assert(!memcmp(before,(void *)(base+entry_offsets[site]),16));expect_stub(base,1-site);
    }
    for(unsigned site=0;site<2;site++)for(unsigned mode=1;mode<=2;mode++) {
        reset_probe(base);fail_entry=site;entry_occurrence=1;entry_mode=mode;
        install_poweron_observers(base);expect_probe(site,-EIO,0);expect_probe(1-site,0,1);
        assert(!protects[site] && !caches[site] && !poweron_observer_enabled[site]);
        assert(strstr(probe[site],mode==1?"read_rc=-1":"read_rc=8 read_errno=0"));
        assert(!memcmp((void *)(base+entry_offsets[site]),site?poweron_callback_expected:poweron_dispatch_expected,16));
    }
    reset_probe(base);fail_open=1;install_poweron_observers(base);
    for(unsigned site=0;site<2;site++) {
        expect_probe(site,-EACCES,0);snprintf(field,sizeof field,"open_rc=-1 open_errno=%d",EACCES);
        assert(strstr(probe[site],field) && !protects[site] && !caches[site] && !poweron_observer_enabled[site]);
    }
    assert(opens==2 && !reads && !closes);
    for(unsigned site=0;site<2;site++)for(unsigned occurrence=1;occurrence<=2;occurrence++) {
        reset_probe(base);fail_protect=site;protect_occurrence=occurrence;
        install_poweron_observers(base);expect_probe(site,-EPERM,1);expect_probe(1-site,0,1);
        assert(protects[site]==occurrence && caches[site]==occurrence-1);
        assert(!poweron_observer_enabled[site] && poweron_observer_enabled[1-site]);
        if(occurrence==1)assert(!memcmp((void *)(base+entry_offsets[site]),
            site?poweron_callback_expected:poweron_dispatch_expected,16));
        else expect_stub(base,site);
    }
    for(unsigned site=0;site<2;site++)for(unsigned mode=1;mode<=3;mode++)
        for(unsigned word=0;word<(mode==3?4u:1u);word++) {
            reset_probe(base);fail_entry=site;entry_occurrence=2;entry_mode=mode;patch_word=word;
            install_poweron_observers(base);expect_probe(site,mode==3?-EILSEQ:-EIO,1);expect_probe(1-site,0,1);
            assert(protects[site]==2 && caches[site]==1 && !poweron_observer_enabled[site]);
            assert(poweron_observer_enabled[1-site]);expect_stub(base,site);expect_stub(base,1-site);
            assert(strstr(probe[site],mode==1?"patch_read_rc=-1":mode==2?
                "patch_read_rc=8 patch_read_errno=0":"patch_read_rc=16 patch_read_errno=0"));
        }
    reset_probe(base);fail_protect=0;protect_occurrence=2;fail_entry=0;entry_occurrence=2;entry_mode=1;
    install_poweron_observers(base);expect_probe(0,-EPERM,1);
    snprintf(field,sizeof field,"arm_rc=%d arm_errno=%d",-EPERM,EPERM);
    assert(strstr(probe[0],field) && strstr(probe[0],"patch_read_rc=-1"));
    const unsigned long invalid_bases[4]={0,base+1,~0xfffUL,0x7ffffffff9000000UL};
    const int invalid_errors[4]={EFAULT,ENOTSUP,EOVERFLOW,EOVERFLOW};
    for(unsigned index=0;index<4;index++) {
        reset_probe(base);install_poweron_observers(invalid_bases[index]);
        for(unsigned site=0;site<2;site++) {
            expect_probe(site,-invalid_errors[index],0);
            assert(!protects[site] && !caches[site] && !poweron_observer_enabled[site]);
            assert(!memcmp((void *)(base+entry_offsets[site]),site?poweron_callback_expected:poweron_dispatch_expected,16));
        }
        assert(!opens && !reads && !closes && !poweron_observer_base);
    }
    reset_probe(base);fail_close=1;install_poweron_observers(base);
    for(unsigned site=0;site<2;site++) {
        expect_probe(site,0,1);snprintf(field,sizeof field,"close_rc=-1 close_errno=%d",EIO);
        assert(strstr(probe[site],field) && strstr(probe[site],"patch_read_rc=16 patch_read_errno=0"));
        assert(poweron_observer_enabled[site] && protects[site]==2 && caches[site]==1);
        assert(!callbacks[site] && !poweron_observer_seen[site]);expect_stub(base,site);
    }
    assert(poweron_dispatch_continue==(void *)(base+0x1951854UL));
    assert(poweron_callback_continue==(void *)(base+0x209f310UL) && poweron_observer_base==base);
    assert(((base+entry_offsets[0])&7UL)==4);
    fail_close=0;capture_poweron_dispatch(controller_address,0x01000090u,caller);
    capture_poweron_callback(controller_address,caller);expect_observation(0);expect_observation(1);
    assert(callbacks[0]==1 && callbacks[1]==1 && poweron_observer_seen[0]==1 && poweron_observer_seen[1]==1);
    /* A base change cannot redirect continuations or patch another image after arming. */
    for(unsigned site=0;site<2;site++) {
        memcpy((void *)(base2+entry_offsets[site]),site?poweron_callback_expected:poweron_dispatch_expected,16);
        probe_count[site]=0;
    }
    test_base=base2;old_opens=opens;old_reads=reads;old_closes=closes;
    install_poweron_observers(base2);
    for(unsigned site=0;site<2;site++) {
        expect_probe(site,-ENOTSUP,0);assert(protects[site]==2 && caches[site]==1);
        assert(!memcmp((void *)(base2+entry_offsets[site]),site?poweron_callback_expected:poweron_dispatch_expected,16));
    }
    assert(poweron_observer_base==base && poweron_dispatch_continue==(void *)(base+0x1951854UL));
    assert(poweron_callback_continue==(void *)(base+0x209f310UL));
    assert(opens==old_opens && reads==old_reads && closes==old_closes);
    /* A failed preflight must also disable a previously enabled observation site. */
    reset_probe(base);install_poweron_observers(base);
    assert(poweron_observer_enabled[0] && poweron_observer_enabled[1]);
    probe_count[0]=probe_count[1]=0;old_reads=reads;
    install_poweron_observers(base);
    for(unsigned site=0;site<2;site++) {
        expect_probe(site,-EILSEQ,0);assert(!poweron_observer_enabled[site]);
        assert(protects[site]==2 && caches[site]==1);expect_stub(base,site);
    }
    assert(reads==old_reads+2);
    old_opens=opens;old_reads=reads;old_closes=closes;
    capture_poweron_dispatch(controller_address,0x01000090u,caller);
    capture_poweron_callback(controller_address,caller);
    assert(opens==old_opens && reads==old_reads && closes==old_closes);
    assert(!memcmp(controller_before,controller,4096));
    for(unsigned i=0;i<3;i++)assert(!memcmp(globals_before[i],(void *)((base+field_offsets[i])&~0xfffUL),4096));
    assert(errno==EDOM);
    assert(munmap(controller,4096)==0 && munmap(image,length)==0 && munmap(image2,length)==0);
    return 0;
}
'''
    source = tmp_path / 'poweron-observation.c'
    source.write_text(harness)
    binary = tmp_path / 'poweron-observation'
    subprocess.run(['clang', '-std=c11', '-D_GNU_SOURCE', '-O1', '-g', '-Wall', '-Wextra',
                    '-Werror', '-pedantic', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-fno-omit-frame-pointer', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=20)
