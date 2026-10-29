"""Real sparse 10GiB offsets and bounded extent enumeration; no physical devices."""
from pathlib import Path
import subprocess
import pytest
import os

from sd_sparse import parse_map, TOTAL, DATA_LIMIT

BASE = Path(__file__).resolve().parent


def test_ten_gib_sparse_offsets_and_extent_coverage(tmp_path):
    source = tmp_path/'sparse-test.c'
    source.write_text(r'''
#define SD_SPARSE_TEST
#include "sd-sparse.c"
#include <assert.h>
static uint64_t positions[]={0,(UINT64_C(2)<<30)+37,(UINT64_C(4)<<30)+53,SD_SPARSE_TOTAL-1};
static unsigned covered[4];
static int observe(void *unused,uint64_t offset,uint64_t length) {
    (void)unused;assert(length && length<=SD_SPARSE_WINDOW && offset+length<=SD_SPARSE_TOTAL);
    for(unsigned i=0;i<4;i++)if(offset<=positions[i] && positions[i]<offset+length)covered[i]++;
    return 0;
}
static int reject(void *unused,uint64_t offset,uint64_t length) {
    (void)unused;(void)offset;(void)length;return -1;
}
int main(int argc,char **argv) {
    assert(argc==2);
    int fd=open(argv[1],O_RDWR|O_CREAT|O_EXCL,0600);assert(fd>=0);
    assert(!ftruncate(fd,SD_SPARSE_TOTAL));
    struct stat before,after;assert(!fstat(fd,&before));
    assert((uint64_t)before.st_size==SD_SPARSE_TOTAL && before.st_blocks==0);
    unsigned count;uint64_t data;
    assert(!sparse_ranges(fd,SD_SPARSE_TOTAL,observe,0,&count,&data) && !count && !data);
    for(unsigned i=0;i<4;i++) {
        unsigned char byte=0xff;assert(pread(fd,&byte,1,positions[i])==1 && !byte);
        byte=(unsigned char)(0xa0+i);assert(pwrite(fd,&byte,1,positions[i])==1);
    }
    assert(!fsync(fd));
    assert(!sparse_ranges(fd,SD_SPARSE_TOTAL,observe,0,&count,&data));
    assert(count==4 && data<=4*65536);
    for(unsigned i=0;i<4;i++) {
        unsigned char byte=0;assert(covered[i]==1);
        assert(pread(fd,&byte,1,positions[i])==1 && byte==(unsigned char)(0xa0+i));
    }
    assert(!fstat(fd,&after) && after.st_blocks*512<=4*65536);
    assert(!sparse_same(&before,&after));
    assert(sparse_ranges(fd,SD_SPARSE_TOTAL,reject,0,&count,&data)==-1);
    assert(sparse_ranges(fd,8,observe,0,&count,&data)==-1);
    assert(!close(fd));return 0;
}
''')
    binary = tmp_path/'sparse-test'
    subprocess.run(['clang','-O1','-g','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-I',str(BASE),str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary),str(tmp_path/'sparse.img')],check=True,timeout=20)


def map_bytes(ranges=((0,4096),(4*1024**3,4096)), **changes):
    total=changes.get('total',TOTAL)
    rows=[f'SD_SPARSE_BEGIN total={total} dev=1 inode=2 mtime=3.000000000 ctime=4.000000000']
    rows.extend(f'SD_SPARSE_RANGE offset={a} len={b}' for a,b in ranges)
    rows.append(f'SD_SPARSE_END ranges={len(ranges)} data={sum(b for a,b in ranges)} allocated={sum(b for a,b in ranges)} rc=0')
    return ('\n'.join(rows)+'\n').encode()


def test_map_identity_and_empty_card():
    parsed=parse_map(map_bytes(),TOTAL)
    assert parsed['ranges']==[(0,4096),(4*1024**3,4096)] and parsed['data_bytes']==8192
    assert parsed['identity']==[str(TOTAL),'1','2','3.000000000','4.000000000']
    assert parse_map(map_bytes(()),TOTAL)['ranges']==[]


@pytest.mark.parametrize('raw',[
    b'', map_bytes()+b'SD_SPARSE_ERROR rc=4\n', map_bytes()+map_bytes(),
    map_bytes(((0,4096),(0,4096))), map_bytes(((0,4096),(4095,4096))),
    map_bytes(((TOTAL,4096),)), map_bytes(((0,4*1024**2+4096),)),
    map_bytes().replace(b'data=8192',b'data=1'),
    map_bytes().replace(b'ranges=2',b'ranges=3'),
    map_bytes().replace(b'allocated=8192',b'allocated='+str(DATA_LIMIT+4096).encode()),
    map_bytes(total=TOTAL-4096),
])
def test_map_rejects_bad_evidence(raw):
    with pytest.raises(ValueError):parse_map(raw,TOTAL)


@pytest.mark.parametrize('profile,message',[
    ('10g','must be 10g-empty'),('10g-empty','requires original RM file backend'),
])
def test_sparse_profile_fails_before_launch(profile,message):
    env={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','A7C2_','QEMU_','SONY_'))}
    result=subprocess.run(['python3',str(BASE/'qemu-menu-probe.py')],
                          env=dict(env,A7C2_SD_SPARSE=profile),text=True,capture_output=True,timeout=10)
    assert result.returncode==2 and message in result.stderr
