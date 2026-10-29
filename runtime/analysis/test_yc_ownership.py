"""Host-only tests of the original op28 wire contract; never retire a lease."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess

import pytest

from yc_ownership_evidence import verify, verify_build


def test_op28_decoder_rejects_wrong_identity_without_output(tmp_path):
    include = Path(__file__).resolve().parents[2]/'report/virtual-cp/yc-inject'
    source = r'''
#include <assert.h>
#include <string.h>
#include "unit-info.h"
static unsigned char reply[40];
static void put16(unsigned off, unsigned n) { reply[off]=n; reply[off+1]=n>>8; }
static void put32(unsigned off, unsigned n) { put16(off,n); put16(off+2,n>>16); }
static int decode(unsigned long len, unsigned src, unsigned tag, struct yc_unit_info *out) {
    return yc_info_decode(reply,len,src,tag,0x431,0x500000,out);
}
int main(void) {
    put16(0,0x8028); put16(6,0x4c01); put16(8,1); put16(10,3); put16(12,2);
    put32(16,0x500000); put32(20,0x431);
    struct yc_unit_info info;
    assert(decode(40,0x61003c,0x4c01,&info)==0);
    assert(info.references==3 && info.opens==2 && info.bytes==0x500000 && info.type==0x431);
    assert(decode(40,0x8061003c,0x4c01,&info)==0);
    struct yc_unit_info before=info;
    assert(decode(39,0x61003c,0x4c01,&info)==-1);
    assert(decode(41,0x61003c,0x4c01,&info)==-1);
    assert(decode(216,0x61003c,0x4c01,&info)==-1);
    assert(decode(40,0x61003d,0x4c01,&info)==-1);
    assert(decode(40,0x61003c,0x4c02,&info)==-1);
    assert(decode(40,0x61003c,0,&info)==-1);
    for (unsigned off=0;off<=20;off+=2) {
        if (off==4 || off==14) continue; /* fields not used as identity */
        unsigned char saved[40]; memcpy(saved,reply,40);
        put16(off,0xffff);
        assert(decode(40,0x61003c,0x4c01,&info)==-1);
        assert(memcmp(&before,&info,sizeof info)==0);
        memcpy(reply,saved,40);
    }
    return 0;
}
'''
    test = tmp_path/'op28.c'
    test.write_text(source)
    binary = tmp_path/'op28'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-no-pie', '-I', str(include),
                    str(test), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)


def ownership_log(refs=1, opens=0):
    text = 'YCIN_DMM: type=0x431 handle=0x415 addr=0x425558000 len=0x500000\n'
    for tag in (0x4c01, 0x4c02):
        raw = bytearray(40)
        struct.pack_into('<Hh2xH3H', raw, 0, 0x8028, 0, tag, 1, refs, opens)
        struct.pack_into('<II', raw, 16, 0x500000, 0x431)
        identity = f'tag={tag:#x} handle=0x415 addr=0x425558000 capacity=0x500000 type=0x431'
        text += 'YCIN_OWNERSHIP_REQUEST: '+identity+'\n'
        text += ('YCIN_OWNERSHIP: '+identity+
                 f' extents=1 refs={refs} opens={opens} source=0x61003c bytes=40 raw={raw.hex()} retirement_verified=0\n')
    return text


def test_count_observations_never_authorize_overwrite(tmp_path):
    for refs, opens in ((3, 2), (1, 0)):
        (tmp_path/'console.log').write_text(ownership_log(refs, opens))
        result = verify(tmp_path)
        assert result['verified'] and len(result['snapshots']) == 2
        assert result['snapshots'][1]['references'] == refs
        assert not result['retirement_verified'] and not result['overwrite_authorized']


def test_incomplete_stale_corrupt_or_misbound_logs_reject(tmp_path):
    original = ownership_log()
    bad_logs = [
        original.rsplit('YCIN_OWNERSHIP:', 1)[0],
        original.replace('tag=0x4c02', 'tag=0x4c01'),
        original.replace('refs=1', 'refs=2'),
        original.replace('source=0x61003c', 'source=0x61003d'),
        original.replace('bytes=40', 'bytes=216'),
        original.replace('len=0x500000', 'len=0x400000'),
        original+'YCIN_OWNERSHIP_FAILED: timeout\n',
        original+original,
    ]
    for text in bad_logs:
        (tmp_path/'console.log').write_text(text)
        result = verify(tmp_path)
        assert not result['verified'] and result['error']
        assert not result['retirement_verified'] and not result['overwrite_authorized']


def test_old_module_or_changed_sources_rejected_before_run(tmp_path):
    names = ('yc_inject.c','unit-info.h','descriptor.S','build.sh','check_module.py')
    for name in names:
        (tmp_path/name).write_text(name)
    module = tmp_path/'yc_inject.ko'
    module.write_bytes(b'host-test fixture; not an ELF or firmware proof')
    receipt = dict(sha256=hashlib.sha256(module.read_bytes()).hexdigest(),
                   sources_sha256={name:hashlib.sha256((tmp_path/name).read_bytes()).hexdigest() for name in names})
    (tmp_path/'verification.json').write_text(json.dumps(receipt))
    assert verify_build(tmp_path, module) == receipt
    module.write_bytes(b'stale module')
    with pytest.raises(ValueError, match='Rebuild'):
        verify_build(tmp_path, module)
    receipt['sha256'] = hashlib.sha256(module.read_bytes()).hexdigest()
    (tmp_path/'verification.json').write_text(json.dumps(receipt))
    (tmp_path/'unit-info.h').write_text('changed source')
    with pytest.raises(ValueError, match='Rebuild'):
        verify_build(tmp_path, module)
