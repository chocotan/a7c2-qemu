"""Exercise the production freeze state machine; native acceptance tests the real ABI."""
from pathlib import Path
import subprocess


def test_freeze_rollback_and_handle_lifetime(tmp_path):
    source=Path(__file__).with_name('sony_persistent_flash.c').read_text()
    functions=source[source.index('static int thaw_disks(void)'):source.index('static const struct kernel_param_ops freeze_ops')]
    harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define PAGE_SIZE 4096
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
struct kernel_param { int unused; };
struct super_block { int index; };
struct block_device { int index; };
struct pf_disk { void *disk; unsigned selector; struct block_device *held; struct super_block *frozen; };
static struct pf_disk disks[4];
static struct block_device devices[4];
static struct super_block superblocks[4];
static unsigned disk_count=4, frozen_state, frozen_count;
static void *regs;
static int freeze_lock, references, freezes, thaws, fail_freeze, fail_thaw;
static void mutex_lock(int *lock) { assert(!*lock); *lock=1; }
static void mutex_unlock(int *lock) { assert(*lock); *lock=0; }
static struct block_device *bdget_disk(void *disk,int part) { assert(!part); references++; return disk; }
static void bdput(struct block_device *dev) { assert(dev && references>0); references--; }
static struct super_block *freeze_bdev(struct block_device *dev) {
    freezes++;
    return dev->index==fail_freeze ? (void *)(intptr_t)-EIO : dev->index==3 ? 0 : &superblocks[dev->index];
}
static int thaw_bdev(struct block_device *dev,struct super_block *sb) {
    assert(sb==(dev->index==3 ? 0 : &superblocks[dev->index])); thaws++;
    return dev->index==fail_thaw ? -EBUSY : 0;
}
'''+functions+r'''
int main(void) {
    char state[64]; fail_freeze=fail_thaw=-1;
    for(int i=0;i<4;i++) { devices[i].index=i; disks[i].disk=&devices[i]; disks[i].selector=i; }
    assert(freeze_set("1",0)==-ENODEV && references==0);
    regs=(void *)1;
    assert(freeze_set("yes",0)==-EINVAL && references==0);
    assert(!freeze_set("1\n",0) && frozen_state==1 && frozen_count==3 && references==3);
    assert(freezes==3 && !freeze_set("1",0) && freezes==3);
    assert(freeze_get(state,0)>0 && !strcmp(state,"1 3\n"));
    fail_thaw=2;
    assert(freeze_set("0",0)==-EBUSY && frozen_state==1 && frozen_count==1 && references==1);
    assert(disks[2].held && disks[2].frozen);
    fail_thaw=-1;
    assert(!freeze_set("0\n",0) && !frozen_state && !frozen_count && !references);
    fail_freeze=2;
    assert(freeze_set("1",0)==-EIO && !frozen_state && !frozen_count && !references);
    for(int i=0;i<4;i++) assert(!disks[i].held && !disks[i].frozen);
    fail_freeze=-1;
    assert(!freeze_set("1",0) && frozen_count==3 && references==3);
    assert(!freeze_set("0",0) && !references);
    puts("PASS production freeze, rollback, idempotency and reference lifetime");
}
'''
    path=tmp_path/'freeze.c';path.write_text(harness);binary=tmp_path/'freeze'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-parameter','-Werror',str(path),'-o',str(binary)],check=True,capture_output=True,timeout=30)
    result=subprocess.run([str(binary)],check=True,capture_output=True,timeout=10)
    assert result.stdout==b'PASS production freeze, rollback, idempotency and reference lifetime\n' and not result.stderr
