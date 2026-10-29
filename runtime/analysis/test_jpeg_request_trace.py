"""Bounded observation of a generic JPEG request, without changing capture state."""
from pathlib import Path
import os
import re
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent


def test_jpeg_trace_preserves_input_errno_and_bounds(tmp_path):
    source = (HERE / 'menu-observe.c').read_text()
    helper = source[source.index('static unsigned int jpeg_request_count;'):]
    helper = helper[:helper.index('__asm__(')]
    fixture = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static unsigned long appfw_base=0x10000000;
static unsigned int requests, inputs, invalid;
static long fake_syscall(long number){assert(number==178);return 17;}
#define syscall fake_syscall
static void record(const char *tag,const char *text){
 if(!strcmp(tag,"JPEG_REQUEST ")){requests++;if(strstr(text,"bytes=-1"))invalid++;}
 else {assert(!strcmp(tag,"JPEG_INPUT "));inputs++;assert(strstr(text,"n="));}
 errno=77;
}
'''
    main = r'''
int main(void){
 unsigned char object[0x90], before[0x90];
 unsigned long frame[2]={0,0x30a99f4};
 memset(object,0xa5,sizeof object);memcpy(before,object,sizeof object);
 for(int i=0;i<100;i++){
  errno=31;capture_jpeg_request((unsigned long)object,0,appfw_base+4,(unsigned long)frame);
  assert(errno==31 && !memcmp(object,before,sizeof object));
 }
 assert(requests==8 && inputs==8);
 jpeg_request_count=0;errno=31;capture_jpeg_request(1,0,0,1);
 assert(requests==9 && inputs==8 && invalid==1 && errno==31);
 (void)jpeg_request_continue;
 return 0;
}
'''
    path = tmp_path / 'trace.c'; path.write_text(fixture + helper + main)
    binary = tmp_path / 'trace'
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-no-pie', str(path), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)


def test_jpeg_probe_matches_original_prologue():
    image = HERE / 'menu-root/usr/lib/appFw.so'
    if not image.exists():pytest.skip('Original firmware is not distributed')
    raw = image.read_bytes();header = struct.unpack_from('<16sHHIQQQIHHHHHH', raw)
    loads = [struct.unpack_from('<IIQQQQQQ', raw, header[5] + i * header[9]) for i in range(header[10])]
    address = 0x34f6fd0
    segment = next(p for p in loads if p[0] == 1 and p[3] <= address and address + 16 <= p[3] + p[5])
    offset = segment[2] + address - segment[3]
    source = (HERE / 'menu-observe.c').read_text()
    body = source.split('"jpeg_request_trampoline:', 1)[1].split('"    adrp x16,', 1)[0]
    replay = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', body)]
    assert replay == list(struct.unpack_from('<4I', raw, offset))
    assert 'base + 0x34f6fe0UL' in source


def test_invalid_trace_profile_rejected():
    for values, error in (({'MENU_JPEG_REQUEST_TRACE': 'yes'}, 'must be 1 or unset'),
                          ({'MENU_JPEG_REQUEST_TRACE': '1'}, 'requires --initramfs --observe')):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'A7C2_'))}
        result = subprocess.run(['python3', str(HERE / 'qemu-menu-probe.py')],
                                env=dict(env, **values), capture_output=True, text=True, timeout=10)
        assert result.returncode == 2 and error in result.stderr
