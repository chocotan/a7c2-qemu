from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ALH_PINS = json.loads((HERE.parents[1]/'report/lif-enable-input-contract/source-pins.json').read_text())['public_property']


@pytest.mark.parametrize('versioned_stat', [False, True])
def test_public_stage_file_loader_actual_content_and_failures(tmp_path, versioned_stat):
    original = HERE/'menu-root/seed-backup.bin'
    seed = original.read_bytes()
    assert len(seed) == 2390264
    assert hashlib.sha256(seed).hexdigest() == '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    offset = 0xed000 + int(ALH_PINS['payload_stage_offset_hex'], 16)
    assert hashlib.sha256(seed[offset:offset + 256]).hexdigest() == ALH_PINS['payload_sha256']
    corrupt = tmp_path/'corrupt.bin'
    corrupt.write_bytes(seed[:123] + bytes([seed[123]^1]) + seed[124:])
    frozen = tmp_path/'frozen.bin'
    changed = bytearray(seed)
    changed[0xed000+9] = 1
    frozen.write_bytes(changed)
    short = tmp_path/'short.bin'
    short.write_bytes(seed[:-1])
    source = tmp_path/'stage-file.c'
    source.write_text(r'''
#define _GNU_SOURCE
#include "cp-property-stage-file.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static unsigned reads, stats;
static int mode;
extern ssize_t __real_pread(int,void *,size_t,off_t);
ssize_t __wrap_pread(int fd,void *out,size_t size,off_t offset) {
    ++reads;
    if(mode==1 && reads==1){errno=EINTR;return -1;}
    if(mode==2 && offset>0)return 0;
    if(mode==3 && offset==2390264){*(unsigned char *)out=1;return 1;}
    if((mode==1 || mode==2) && size>397)size=397;
    return __real_pread(fd,out,size,offset);
}
extern int __real_fstat(int,struct stat *);
int __wrap_fstat(int fd,struct stat *out) {
    int rc=__real_fstat(fd,out);++stats;
    if(!rc && mode==4 && stats==2)out->st_mtim.tv_nsec^=1;
    return rc;
}
int __wrap___fxstat(int version,int fd,struct stat *out) {
    assert(version==0);
    return __wrap_fstat(fd,out);
}
int main(int argc,char **argv) {
    assert(argc==4);mode=atoi(argv[2]);int expected=atoi(argv[3]);
    int fd=open(argv[1],O_RDONLY|O_CLOEXEC);assert(fd>=0);
    struct cp_property_stage stage, before;
    struct cp_start_state_provider provider;
    assert(!cp_property_stage_init(&stage));before=stage;
    assert(!cp_start_state_provider_init(&provider));
    struct cp_start_state_guard guard={(uint32_t)getpid(),2,2,CP_START_STATE_ORIGIN_HOST_TEST,1};
    struct cp_parameter_import decision,old_decision;memset(&decision,0xa5,sizeof decision);old_decision=decision;
    errno=31;
    int rc=cp_property_stage_load_public_file(&stage,&guard,fd,&decision);
    assert(errno==31);
    if(expected){assert(rc==expected && !memcmp(&stage,&before,sizeof stage));assert(!memcmp(&decision,&old_decision,sizeof decision));}
    else {
        assert(!rc);
        assert(decision.properties_consumed && decision.defaults_selected && !decision.import_selected);
        assert(!decision.header && !decision.flags && decision.source_sequence==2);
        struct cp_property_stage_readback value;
        assert(!cp_property_stage_snapshot(&stage,&guard,&value));
        assert(value.mode_property_known && value.profile_known && value.alh_property_known==1 && value.mode==1);
        unsigned char alh[CP_PROPERTY_STAGE_ALH_BYTES];
        assert(__real_pread(fd,alh,sizeof alh,CP_PROPERTY_STAGE_ALLLANG_OFFSET+0x3d59c)==(ssize_t)sizeof alh);
        assert(!memcmp(value.ALH_context,alh,sizeof alh) && value.ALH_context[0xb8]==0xff);
        assert(value.repository==CP_PROPERTY_STAGE_REPOSITORY_CP_PRIMARY && value.context[4]==0);
        assert(!cp_property_stage_deliver_profile(&stage,&guard,&provider));
        struct cp_start_state_provider_readback data;
        assert(!cp_start_state_provider_snapshot(&provider,&guard,&data));
        assert(data.property_delivered && !data.data.data_ready && !data.data.known_mask);
        assert(data.data.predicate_known_mask==1 && data.context[4]==0);
        assert(!data.data.published && !data.data.business_ready && !data.data.ap_applied);
        before=stage;
        assert(cp_property_stage_load_public_file(&stage,&guard,fd,&decision)==-EALREADY);
        assert(!memcmp(&stage,&before,sizeof stage));
    }
    assert(fcntl(fd,F_GETFD)>=0 && !close(fd));
    assert(!cp_property_stage_init(&stage));before=stage;
    errno=31;assert(cp_property_stage_load_public_file(&stage,&guard,-1,&decision)==-EINVAL && errno==31);
    assert(!memcmp(&stage,&before,sizeof stage));
    return 0;
}
''')
    binary = tmp_path/'stage-file'
    models = HERE/'device-models'
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    *(['-D__aarch64__'] if versioned_stat else []),
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-I', str(models),
                    str(source), *(str(models/name) for name in ('cp-property-stage-file.c', 'cp-property-stage.c', 'cp-parameter-import.c',
                        'cp-start-state-provider.c', 'cp-start-state-data.c')),
                    '-Wl,--wrap=pread,--wrap=fstat,--wrap=__fxstat', '-o', str(binary)], check=True)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
    import errno
    for path, mode, expected in ((original,0,0),(original,1,0),(original,2,-errno.EIO),
                                 (original,3,-errno.EILSEQ),(original,4,-errno.EILSEQ),
                                 (corrupt,0,-errno.EILSEQ),(frozen,0,-errno.EILSEQ),
                                 (short,0,-errno.EILSEQ),(tmp_path,0,-errno.EILSEQ)):
        subprocess.run([str(binary), str(path), str(mode), str(expected)], check=True, env=env, timeout=10)


def test_public_stage_file_loader_with_original_aarch64_libc(tmp_path):
    qemu = HERE.parent/'sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not shutil.which('clang') or not qemu.is_file():
        pytest.skip('original-libc execution requires clang and the prepared QEMU user binary')
    root = HERE/'menu-root'
    models = HERE/'device-models'
    source = HERE.parents[1]/'report/cp-property-repository-contract/check-original-abi.c'
    binary = tmp_path/'check-original-stage'
    libraries = [root/'lib'/name for name in (
        'libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib',
        '-O2', '-mno-outline-atomics', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-Wl,--no-undefined', '-isystem', '/usr/aarch64-linux-gnu/include', '-I', str(models),
        '-Wl,-e,_start', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(source),
        *(str(models/name) for name in ('cp-property-stage-file.c', 'cp-property-stage.c',
            'cp-parameter-import.c', 'cp-start-state-provider.c', 'cp-start-state-data.c')),
        *(str(path) for path in libraries), '-o', str(binary)],
        check=True, capture_output=True, text=True, timeout=30)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_', 'LD_'))}
    result = subprocess.run([str(qemu), '-L', str(root), str(binary), str(root/'seed-backup.bin')],
        check=True, capture_output=True, text=True, env=env, timeout=30)
    seed = (root/'seed-backup.bin').read_bytes()
    assert len(seed) == ALH_PINS['seed_bytes']
    assert hashlib.sha256(seed).hexdigest() == ALH_PINS['seed_sha256']
    alh = bytes.fromhex(re.search(r'^alh=([0-9a-f]+)$', result.stdout, re.MULTILINE)[1])
    offset = 0xed000 + int(ALH_PINS['payload_stage_offset_hex'], 16)
    assert len(alh) == ALH_PINS['payload_bytes'] == 256
    assert alh == seed[offset:offset + 256]
    assert hashlib.sha256(alh).hexdigest() == ALH_PINS['payload_sha256']
    assert result.stdout == f'alh={alh.hex()}\nPASS: original libc read public CP stage, mode/profile/ALH and defaults decision\n'
    assert not result.stderr
