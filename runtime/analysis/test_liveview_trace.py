"""Exercise the actual bounded, non-mutating liveview census helpers."""
from pathlib import Path
import os
import re
import struct
import subprocess
import pytest

HERE = Path(__file__).resolve().parent


def test_trace_preserves_objects_errno_and_limits(tmp_path):
    source = (HERE / 'menu-observe.c').read_text()
    helper = source[source.index('static unsigned int liveview_request_count,'):]
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
static unsigned int requests,consumed,runs,invalid;
static long fake_syscall(long number){assert(number==178);return 17;}
#define syscall fake_syscall
static void record(const char *tag,const char *text){
 if(!strcmp(tag,"LIVEVIEW_REQUEST_API "))requests++;
 else if(!strcmp(tag,"LIVEVIEW_CONSUME ")){consumed++;if(strstr(text,"bytes=-1"))invalid++;}
 else {assert(!strcmp(tag,"LIVEVIEW_RUN "));runs++;}
 errno=77;
}
'''
    main = r'''
int main(void){
 unsigned int object[8]={1,2,3,4,5,6,7,8},before[8];
 memcpy(before,object,sizeof object);
 for(int i=0;i<600;i++){
  errno=31;capture_liveview_request(0,1,0,appfw_base+4);
  capture_liveview_consume((unsigned long)object);
  assert(errno==31 && !memcmp(object,before,sizeof object));
 }
 assert(requests==8 && consumed==8);
 liveview_consume_count=0;errno=31;capture_liveview_consume(1);
 assert(invalid==1 && errno==31);
 for(int i=0;i<20;i++){errno=31;capture_liveview_run((unsigned long)object);assert(errno==31);}
 assert(runs==8);
 (void)liveview_request_continue;(void)liveview_consume_continue;(void)liveview_run_continue;
 return 0;
}
'''
    path = tmp_path / 'trace.c'
    path.write_text(fixture + helper + main)
    binary = tmp_path / 'trace'
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-no-pie', str(path), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)


def test_liveview_profile_rejects_invalid_modes():
    for values, options, error in (
        ({'MENU_CP_EMULATION': '1'}, [], 'MENU_CP_EMULATION is retired'),
        ({'MENU_LIVEVIEW_TRACE': 'yes'}, [], 'MENU_LIVEVIEW_TRACE must be 1 or unset'),
        ({'MENU_LIVEVIEW_TRACE': '1'}, [], 'MENU_LIVEVIEW_TRACE requires --initramfs --observe'),
        ({'MENU_DISPLAY_SETUP_REQUEST': 'once-v1'}, [], 'MENU_DISPLAY_SETUP_REQUEST is unnecessary'),
    ):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'A7C2_'))}
        result = subprocess.run(['python3', str(HERE / 'qemu-menu-probe.py'), *options],
                                env=dict(env, **values), capture_output=True, text=True, timeout=10)
        assert result.returncode == 2 and error in result.stderr


def test_probe_replays_match_original_entries():
    image = HERE / 'menu-root/usr/lib/appFw.so'
    if not image.exists():
        pytest.skip('Original firmware is not distributed with the source')
    raw = image.read_bytes()
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', raw)
    loads = [struct.unpack_from('<IIQQQQQQ', raw, header[5]+i*header[9])
             for i in range(header[10])]
    source = (HERE / 'menu-observe.c').read_text()
    for name, address in (('request', 0x2502e24), ('consume', 0x2483188), ('run', 0x309b82c)):
        segment = next(p for p in loads if p[0] == 1 and p[3] <= address and address+16 <= p[3]+p[5])
        offset = segment[2]+address-segment[3]
        body = source.split(f'"liveview_{name}_trampoline:', 1)[1].split('"    adrp x16,', 1)[0]
        replay = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', body)]
        assert replay == list(struct.unpack_from('<4I', raw, offset))
