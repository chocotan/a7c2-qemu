"""The real bounded self-frame reader must not turn partial/unknown frames into ownership."""
from pathlib import Path
import os
import subprocess

HERE=Path(__file__).resolve().parent


def test_actual_dmm_creator_reader_bounds_and_known_chain(tmp_path):
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('static unsigned int capture_dmm_creator(')
    helper=source[start:source.index('\nstatic int dmm_send(',start)]
    fixture=r'''
#define _GNU_SOURCE
#include "dmm-service.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static unsigned long appfw_base=0x10000000;
static unsigned int frames, summaries;
static long fake_syscall(long number){assert(number==178);return 44;}
#define syscall fake_syscall
static void record(const char *tag,const char *text) {
    assert(strstr(text,"sample=1") && strstr(text,"tid=44"));
    if(!strcmp(tag,"DMM_ALLOC_FRAME ")) {
        assert(strstr(text,"frame_candidate_only=1"));frames++;
    } else {
        assert(!strcmp(tag,"DMM_ALLOC_CREATOR ") && strstr(text,"gate_admission_unchanged=1"));summaries++;
    }
    errno=77;
}
'''
    main=r'''
static unsigned long chain[9][2] __attribute__((aligned(16)));
static const unsigned long expected[4]={0x35522a4,0x35527b4,0x34d3614,0x17b2c08};
static void prepare(unsigned int count) {
    memset(chain,0,sizeof chain);frames=summaries=0;
    for(unsigned int i=0;i<count;i++) {
        chain[i][0]=i+1<count?(unsigned long)&chain[i+1]:0;
        chain[i][1]=appfw_base+(i<4?expected[i]:0x3209e48);
    }
}
static unsigned int observe(unsigned long first,unsigned long caller) {
    errno=31;unsigned int result=capture_dmm_creator(first,caller,1);
    assert(errno==31 && summaries==1);return result;
}
int main(void) {
    prepare(4);assert(observe((unsigned long)chain,appfw_base+expected[0])==1 && frames==4);
    prepare(9);assert(observe((unsigned long)chain,appfw_base+expected[0])==1 && frames==8);
    prepare(4);assert(!observe((unsigned long)chain,appfw_base+expected[0]+4) && frames==4);
    prepare(4);chain[3][1]=appfw_base+0x17b07e4;
    assert(!observe((unsigned long)chain,appfw_base+expected[0]) && frames==4);
    prepare(4);chain[2][1]=appfw_base-4;
    assert(!observe((unsigned long)chain,appfw_base+expected[0]) && frames==4);
    prepare(4);chain[0][0]=(unsigned long)chain;
    assert(!observe((unsigned long)chain,appfw_base+expected[0]) && frames==1);
    prepare(4);chain[0][0]=(unsigned long)chain+0x40010;
    assert(!observe((unsigned long)chain,appfw_base+expected[0]) && frames==1);
    prepare(4);assert(!observe((unsigned long)chain+1,0) && !frames);
    prepare(4);assert(!observe(1,0) && !frames);
    prepare(4);assert(!observe(0x10000,0) && !frames);
    prepare(4);assert(!observe(0x800000000000UL,0) && !frames);
    prepare(4);appfw_base=0;assert(!observe((unsigned long)chain,chain[0][1]) && frames==4);
    puts("DMM_CREATOR_READER_PASS real self pread, bounded monotonic FP chain, initial speech only, errno preserved");
    return 0;
}
'''
    path=tmp_path/'creator.c';path.write_text(fixture+helper+main)
    binary=tmp_path/'creator'
    built=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-g',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie','-I',str(HERE),
        str(path),str(HERE/'dmm-service.c'),'-o',str(binary)],capture_output=True,text=True,timeout=30)
    assert built.returncode==0,built.stdout+built.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10,
        env=dict(os.environ,ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode==0,result.stdout+result.stderr
    assert 'DMM_CREATOR_READER_PASS' in result.stdout
