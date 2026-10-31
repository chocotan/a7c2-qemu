"""Exercise the installed passive callbacks with their original ID/caller shape."""
from pathlib import Path
import re
import subprocess


BASE = Path(__file__).resolve().parent
SOURCE = (BASE / 'menu-observe.c').read_text()


def test_s2_capture_callbacks_keep_independent_bounded_quotas(tmp_path):
    create = SOURCE[SOURCE.index('void capture_sequence_create('):
                    SOURCE.index('void capture_mode_factory(')]
    schedule = SOURCE[SOURCE.index('void capture_mode_schedule('):
                      SOURCE.index('void capture_clock_sequence(')]
    start = SOURCE.index('static unsigned int sequence_queue_observer_enabled;')
    enqueue = SOURCE[start:SOURCE.index('__asm__(', start)]
    callbacks = create + schedule + enqueue
    assert not re.search(r'\b(?:pwrite|memcpy|memset|osal_\w+)\s*\(', callbacks)
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
static unsigned create_records,enqueue_records,schedule_records;
static char last[1024];
static unsigned long appfw_base=0x100000UL;
static void record(const char *prefix,const char *text) {
    if(!strcmp(prefix,"SEQUENCE_CREATE "))create_records++;
    else if(!strcmp(prefix,"SEQUENCE_QUEUE "))enqueue_records++;
    else {assert(!strcmp(prefix,"MODE_SCHEDULE "));schedule_records++;}
    snprintf(last,sizeof last,"%s",text);
}
/* Map the existing AArch64 gettid number to the host's real gettid. */
static long observer_syscall(long number) {
    assert(number==178);return syscall(SYS_gettid);
}
#define syscall observer_syscall
''' + callbacks + r'''
#undef syscall
int main(int argc,char **argv) {
    (void)argv;
    unsigned char request[0x18]={0},request_copy[sizeof request];
    unsigned int *id=(unsigned int *)request;
    unsigned long request_slot=(unsigned long)request;
    unsigned long items=(unsigned long)&request_slot,vector=(unsigned long)&items;
    unsigned long holder=(unsigned long)&vector;
    const unsigned char *queue=(const unsigned char *)(appfw_base+0x7e4e5d0UL);
    const unsigned long producer_caller=appfw_base+0x24d2e18UL;
    /* The 7e factory tailcalls retain the create dispatch's original LR. */
    const unsigned long schedule_caller=appfw_base+0x24ccadcUL;
    char caller_text[96],tid_text[96];
    *id=0x7e;errno=EDOM;
    capture_sequence_queue_enter(queue,(const unsigned long *)holder,producer_caller);
    assert(enqueue_records==0 && errno==EDOM);
    sequence_queue_observer_enabled=1;
    if(argc>1) {
        long size=sysconf(_SC_PAGESIZE);
        unsigned char *page=mmap(NULL,(size_t)size*2,PROT_READ|PROT_WRITE,
                                 MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        assert(page!=MAP_FAILED);
        unsigned int *edge=(unsigned int *)(page+size-4);*edge=0x7e;
        assert(munmap(page+size,(size_t)size)==0);
        request_slot=(unsigned long)edge;
        capture_sequence_queue_enter(queue,(const unsigned long *)holder,producer_caller);
        assert(enqueue_records==1 && errno==EDOM && *edge==0x7e);
        assert(strstr(last,"request_id=0x7e") && strstr(last,"quota=target7e"));
        assert(strstr(last,"reads=8/8/8/4/-1/-1"));
        capture_sequence_queue_enter(queue,(const unsigned long *)-1,producer_caller);
        assert(enqueue_records==2 && strstr(last,"site=enqueue_unresolved"));
        assert(strstr(last,"reads=-1/-1/-1/-1") && errno==EDOM);
        capture_mode_schedule(1,1,0x7e,schedule_caller);
        assert(schedule_records==1 && errno==EDOM && strstr(last,"group=-1"));
        assert(strstr(last,"reads=-1/-1/-1/-1/-1/-1"));
        assert(strstr(last,"original_return_observed=0"));
        assert(munmap(page,(size_t)size)==0);
        return 0;
    }
    /* Exhaust the actual generic create callback, not a stand-in counter. */
    for(unsigned i=0;i<80;i++)capture_sequence_create(appfw_base+0x272ffa8UL);
    assert(create_records==64 && errno==EDOM);
    unsigned int original_ids[]={0x2f,0x12a,0x297,0x2b7};
    for(unsigned i=0;i<40;i++) {
        *id=original_ids[i%4];
        capture_sequence_queue_enter(queue,(const unsigned long *)holder,producer_caller);
    }
    assert(enqueue_records==32 && errno==EDOM);
    *id=0x123;
    capture_sequence_queue_enter(queue,(const unsigned long *)holder,producer_caller);
    assert(enqueue_records==32);
    *id=0x7e;request[0x10]=1;
    memcpy(request_copy,request,sizeof request);
    capture_sequence_queue_enter(queue,(const unsigned long *)holder,producer_caller);
    assert(enqueue_records==33 && errno==EDOM);
    assert(strstr(last,"site=enqueue n=1 ") && strstr(last,"request_id=0x7e"));
    assert(strstr(last,"caller_app=0x24d2e18") && strstr(last,"reads=8/8/8/4/8/1"));
    snprintf(caller_text,sizeof caller_text,"caller_raw=%#lx",producer_caller);
    snprintf(tid_text,sizeof tid_text,"producer_tid=%ld",syscall(SYS_gettid));
    assert(strstr(last,caller_text) && strstr(last,tid_text));
    assert(strstr(last,"quota=target7e") && strstr(last,"atomic_snapshot=0"));
    assert(strstr(last,"original_return_observed=0") && strstr(last,"predicate_return_observed=0"));
    for(unsigned i=0;i<40;i++)
        capture_sequence_queue_enter(queue,(const unsigned long *)holder,producer_caller);
    assert(enqueue_records==48 && errno==EDOM && !memcmp(request_copy,request,sizeof request));
    assert(request_slot==(unsigned long)request && items==(unsigned long)&request_slot);
    assert(vector==(unsigned long)&items && holder==(unsigned long)&vector);
    unsigned char manager[0x500]={0},manager_copy[sizeof manager];
    unsigned long current[2]={0},control[2]={0};
    control[1]=0x2a;current[1]=(unsigned long)control;
    *(unsigned long *)(manager+0x398)=(unsigned long)current;
    *(unsigned long *)(manager+0x330)=9;
    *(unsigned int *)(manager+0x318)=2;
    memcpy(manager_copy,manager,sizeof manager);
    unsigned int *groups=mmap((void *)(appfw_base+0x4c02000UL),0x1000,
                             PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    assert(groups!=MAP_FAILED);
    for(unsigned i=0;i<40;i++)
        capture_mode_schedule((unsigned long)manager,(unsigned long)current,0x2f,schedule_caller);
    assert(schedule_records==16 && errno==EDOM);
    capture_mode_schedule((unsigned long)manager,(unsigned long)current,0x2a,schedule_caller);
    assert(schedule_records==16);
    capture_mode_schedule((unsigned long)manager,(unsigned long)current,0x7e,schedule_caller);
    assert(schedule_records==17 && errno==EDOM && strstr(last,"n=1 tid="));
    assert(strstr(last,"sequence_id=0x7e") && strstr(last,"quota=target7e"));
    assert(strstr(last,"current_id=0x2a queued=9 stop=0x2"));
    assert(strstr(last,"caller=appFw+0x24ccadc") && strstr(last,"reads=4/8/4/8/8/4"));
    snprintf(caller_text,sizeof caller_text,"caller_raw=%#lx",schedule_caller);
    assert(strstr(last,caller_text) && strstr(last,"original_branch_observed=0"));
    assert(strstr(last,"original_return_observed=0") && strstr(last,"atomic_snapshot=0"));
    for(unsigned i=0;i<40;i++)
        capture_mode_schedule((unsigned long)manager,(unsigned long)current,0x7e,schedule_caller);
    assert(schedule_records==32 && errno==EDOM && !memcmp(manager_copy,manager,sizeof manager));
    assert(current[1]==(unsigned long)control && control[1]==0x2a);
    assert(munmap(groups,0x1000)==0);
    return 0;
}
'''
    source = tmp_path / 's2-observation.c'
    source.write_text(harness)
    binary = tmp_path / 's2-observation'
    subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(source),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)
    subprocess.run([str(binary), 'unreadable'], check=True, timeout=15)


def test_s2_capture_observation_keeps_original_opt_in_and_asm_context():
    start = SOURCE.index('static void install_shutter_detail_trace(unsigned long base) {')
    install = SOURCE[start:SOURCE.index('/* Natural startup frontier:', start)]
    assert install.index('if (!mode) return;') < install.index('arm_entry_probe(')
    assert 'int flows = all || same_name(mode, "flow");' in install
    assert 'if (flows) enable_sequence_queue_observer(base);' in install
    assert 'original bytes differ; detail probes disabled' in install
    assert 'getenv("MENU_INPUT_ROUTE_TRACE") && !getenv("MENU_OBSERVE_SELFTEST")' in SOURCE
    for name, words in (
        ('sequence_create', [0xd10343ff,0x528005e0,0xa9037bfd,0x9100c3fd]),
        ('mode_schedule', [0xa9b77bfd,0x910003fd,0xa9025bf5,0x910243b6]),
        ('power_queue', [0xa9be7bfd,0x910003fd,0xa90153f3,0xaa0003f3]),
    ):
        start = SOURCE.index(f'{name}_trampoline:\\n')
        block = SOURCE[start:SOURCE.index('br x16\\n', start)]
        assert [int(word,16) for word in re.findall(r'\.inst (0x[0-9a-f]+)', block)] == words
        assert block.count('PROBE_SAVE_ARGS') == block.count('PROBE_RESTORE_ARGS')
        assert 'PROBE_SAVE_ARGS' in block
        if name == 'mode_schedule':
            assert 'mov x3, x30' in block and 'bl capture_mode_schedule' in block
        elif name == 'power_queue':
            assert 'mov x2, x30' in block and 'bl capture_sequence_queue_enter' in block
        else:
            assert 'mov x0, x30' in block and 'bl capture_sequence_create' in block
    create = SOURCE[SOURCE.index('void capture_sequence_create('):
                    SOURCE.index('void capture_mode_factory(')]
    assert 'if (n > 64)' in create and 'request_id=' not in create
    assert 'mrs x16, nzcv' in SOURCE and 'msr nzcv, x16' in SOURCE
