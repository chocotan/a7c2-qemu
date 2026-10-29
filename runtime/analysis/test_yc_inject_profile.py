"""Profile validation for the YC injection experiment (no guest boot)."""
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def test_yc_inject_profile_validation():
    for values, error in (
        ({'MENU_YC_INJECT': 'yes'}, 'MENU_YC_INJECT must be 1 or unset'),
        ({'MENU_YC_INJECT': '1'}, 'MENU_YC_INJECT requires --initramfs --load-ipc --load-dmm'),
        ({'MENU_YC_INJECT': '1', 'MENU_YC_INJECT_DELAY': 'abc'}, 'MENU_YC_INJECT_DELAY must be an integer'),
        ({'MENU_YC_INJECT': '1', 'MENU_YC_INJECT_DELAY': '601'}, 'MENU_YC_INJECT_DELAY must be within 0..600'),
        ({'MENU_YC_UNCOMPRESSED':'yes'}, 'MENU_YC_UNCOMPRESSED must be 1 or unset'),
        ({'MENU_YC_UNCOMPRESSED':'1'}, 'requires YC injection without PNG/raw input'),
        ({'MENU_YC_UNCOMPRESSED':'1','MENU_YC_INJECT':'1','MENU_YC_INPUT_PNG':'input.png'},
         'requires YC injection without PNG/raw input'),
        ({'A7C2_YC_OWNERSHIP_OBSERVE':'yes'}, 'A7C2_YC_OWNERSHIP_OBSERVE must be 1 or unset'),
        ({'A7C2_YC_OWNERSHIP_OBSERVE':'1'}, 'requires the uncompressed diagnostic source'),
    ):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'A7C2_'))}
        result = subprocess.run(['python3', str(HERE / 'qemu-menu-probe.py')],
                                env=dict(env, **values), capture_output=True, text=True, timeout=10)
        assert result.returncode == 2 and error in result.stderr, (values, result.stderr)


def test_module_built_with_pinned_abi():
    module = HERE.parents[1] / 'report/virtual-cp/yc-inject/yc_inject.ko'
    proof = module.with_name('verification.json')
    assert module.exists() and proof.exists(), 'run report/virtual-cp/yc-inject/build.sh first'
    import json
    data = json.loads(proof.read_text())
    assert 'not a real CMOS' in data['scope'] and 'osal_reg_msg_queue_cb' in data['imports']


def test_uncompressed_unit_is_not_the_same_numbered_extent():
    import hashlib
    import struct
    import pytest
    path=HERE/'menu-root/seed-setting/DmmCfg.bin'
    if not path.exists():pytest.skip('Original firmware is not distributed')
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='6c37baddaa60b6756340f77b051eed948978cea28d04f499f91263c9d270d962'
    assert struct.unpack_from('<4I',raw,0xfc60)==(0x626,0,0x6d7,0xffffffff)
    assert struct.unpack_from('<5I',raw,0x488)==(0,0xc,0x6d7,0x400000,0x10f)
    assert struct.unpack_from('<IHHIII',raw,0x50)==(0x24000000,20,4,0x1d,0x5b00000,1)
    assert struct.unpack_from('<4I',raw,0xfda0)==(0x644,0,0x70d,0xffffffff)
    assert struct.unpack_from('<5I',raw,0x71c)==(0,0xc,0x70d,0x200000,0x10f)
    assert struct.unpack_from('<4I',raw,0xf2d0)==(0x431,0,0x561,0xffffffff)
    assert struct.unpack_from('<5I',raw,0x4b0)==(0,0xc,0x561,0x500000,0x10f)


def test_actual_metadata_builder_neutral_uncompressed_source(tmp_path):
    module=HERE.parents[1]/'report/virtual-cp/yc-inject/yc_inject.c'
    source=module.read_text()
    start=source.index('static void build_metadata_and_frame(')
    end=source.index('/* PIN_CONNECT',start)
    harness=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long u64;
typedef unsigned short u16;
#define FRAME_W 1920u
#define FRAME_H 1080u
static int uncompressed_input,input_loaded,neutral_initialized;
#define ACTIVE_PIXEL_TYPE (uncompressed_input?0x431u:0x643u)
#define FRAME_BYTES (FRAME_W*FRAME_H*(uncompressed_input?5u:2u)/2u)
static u8 *meta_va[3],*pix_va;
static u32 pix_h=17,pix_len=0x500000;
static u64 pix_addr=0x428800000;
static void put16(u8*p,u16 v){memcpy(p,&v,2);}
static void put32(u8*p,u32 v){memcpy(p,&v,4);}
static void put64(u8*p,u64 v){memcpy(p,&v,8);}
static u64 input_digest(const u8*p,u32 n){(void)p;return n;}
static int printk(const char*fmt,...){(void)fmt;return 0;}
'''
    main=r'''
int main(void){
 meta_va[0]=calloc(1,0xf80);pix_va=malloc(1920*1080*5/2+16);
 assert(meta_va[0]&&pix_va);memset(pix_va,0xa5,1920*1080*5/2+16);
 uncompressed_input=1;build_metadata_and_frame(0);
 assert(meta_va[0][0x120]==0);u32 type;memcpy(&type,meta_va[0]+0x100,4);assert(type==0x431);
 for(u32 i=0;i<FRAME_BYTES;i++)assert(pix_va[i]==128);
 for(u32 i=FRAME_BYTES;i<FRAME_BYTES+16;i++)assert(pix_va[i]==0xa5);
 uncompressed_input=0;input_loaded=1;memset(pix_va,0x55,1920*1080*2);
 build_metadata_and_frame(0);assert(meta_va[0][0x120]==2);
 memcpy(&type,meta_va[0]+0x100,4);assert(type==0x643);
 for(u32 i=0;i<1920*1080*2;i++)assert(pix_va[i]==0x55);
 free(meta_va[0]);free(pix_va);return 0;
}
'''
    path=tmp_path/'metadata.c';path.write_text(harness+source[start:end]+main)
    binary=tmp_path/'metadata'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-no-pie',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_original_rdimg_storage_is_larger_than_format_zero_rc_rectangle():
    import hashlib
    import struct
    from pathlib import Path
    raw=(Path(__file__).resolve().parent/'menu-root/system/av-cam.bin').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
    assert struct.unpack_from('<8I',raw,0x3242f0)==(10,5,4,5,4,5,6,8)
    assert struct.unpack_from('<9I',raw,0x1c6440)==(
        0x710006bf,0x321d03e9,0x5280014a,0x1b147e6b,0x1a890149,
        0x1b097d6a,0x5302794a,0x1b0a7d08,0x1ac90900)
    for bit_width in (8,10):
        needed=(10*((1920*1080*bit_width)>>2))//bit_width
        assert needed==5184000 and needed>0x400000 and needed<=0x500000
    assert 1920*1080*2==4147200


def test_actual_format_request_keeps_default_and_selects_fhd_for_identity(tmp_path):
    source=(HERE.parents[1]/'report/virtual-cp/yc-inject/yc_inject.c').read_text()
    start=source.index('static long yc_send_set_format(void)\n{')
    end=source.index('/* Frame-sync notification:',start)
    harness=r'''
#include <assert.h>
#include <string.h>
typedef unsigned char u8;typedef unsigned short u16;typedef unsigned int u32;
#define VDT_FMT_NV12_FHD 0x10u
#define VDT_FMT_NV12_720 0x11u
static int uncompressed_input;
static u32 q_reply=0x8aa50751;
static void put16(u8*p,u16 value){memcpy(p,&value,2);}
static void put32(u8*p,u32 value){memcpy(p,&value,4);}
static int printk(const char*fmt,...){(void)fmt;return 0;}
static long vdt_send_enveloped(const u8 *bytes,u32 count){
 assert(count==0x28&&bytes[0]==0x0b&&bytes[1]==0x20&&bytes[2]==4&&bytes[3]==3);
 assert(bytes[0xd]==(uncompressed_input?0x10:0x11));
 u32 reply;memcpy(&reply,bytes+8,4);assert(reply==q_reply);return -7;
}
'''
    main='int main(void){assert(yc_send_set_format()==-7);uncompressed_input=1;assert(yc_send_set_format()==-7);return 0;}\n'
    path=tmp_path/'format.c';path.write_text(harness+source[start:end]+main)
    binary=tmp_path/'format'
    subprocess.run(['cc','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-no-pie',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)


def test_actual_bounded_sensor_clock_tail_does_not_publish_completion(tmp_path):
    source=(Path(__file__).resolve().parents[2]/'report/virtual-cp/yc-inject/yc_inject.c').read_text()
    begin=source.index('    if (uncompressed_input) {\n        /* Sensor timing')
    end=source.index('    printk("\\0016YCIN_INIT_DONE:',begin)
    block=source[begin:end]
    harness=r'''
#include <assert.h>
#define N_FRAMES 3u
static unsigned ticks,waits,fail_at;
static int printk(const char *format,...){(void)format;return 0;}
static void msleep(unsigned milliseconds){assert(milliseconds==40);waits++;}
static void vfc_tick(unsigned value){assert(value==N_FRAMES+ticks+1);ticks++;}
static long yc_send_frame_sync(void){return fail_at==ticks?-17:0;}
static void observe_ownership(unsigned tag){assert(tag==0x4c02);}
static int start_tail(int uncompressed_input){unsigned idx;long rc;
BLOCK
return 0;}
int main(void){assert(!start_tail(0)&&!ticks&&!waits);
 assert(!start_tail(1)&&ticks==8&&waits==8);
 ticks=waits=0;fail_at=3;assert(start_tail(1)==-17&&ticks==3&&waits==3);return 0;}
'''.replace('BLOCK',block)
    path=tmp_path/'clock.c';path.write_text(harness);binary=tmp_path/'clock'
    subprocess.run(['cc','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
