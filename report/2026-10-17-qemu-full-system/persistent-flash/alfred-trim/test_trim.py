#!/usr/bin/env python3
"""Test the module's shared engine through real flash-core MMIO and regular files."""
import argparse
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
OUTPUT = None
BRIDGE = r'''
#define _GNU_SOURCE
#include "trim-zero.h"
#include "flash-core.h"
#include <sys/stat.h>
#include <unistd.h>
#include <errno.h>
static int fault;
struct test_ctx { struct a7pf pf; unsigned char bounce[PF_TRIM_CHUNK]; };
static ssize_t test_write(int fd, const void *p, size_t n, off_t o)
{ return pwrite(fd, p, fault==1 ? n-1 : n, o); }
static ssize_t test_read(int fd, void *p, size_t n, off_t o)
{
    ssize_t got=pread(fd, p, fault==2 ? n-1 : n, o);
    if (got>0 && fault==4) ((unsigned char *)p)[0]=1;
    return got;
}
static int test_sync(int fd)
{ if (fault==3) { errno=EIO; return -1; } return fdatasync(fd); }
static int dma(void *v, uint64_t addr, void *data, size_t n, bool to_guest, bool probe)
{
    struct test_ctx *c=v;
    if (addr!=512 || n>sizeof(c->bounce)) return EFAULT;
    if (!probe) {
        if (to_guest) memcpy(c->bounce, data, n);
        else memcpy(data, c->bounce, n);
    }
    return 0;
}
static int op(struct test_ctx *c, unsigned int cmd)
{
    a7pf_write_reg(&c->pf, 0x14, cmd);
    if (a7pf_read_reg(&c->pf, 0x2c)!=A7PF_DONE)
        return -(int)a7pf_read_reg(&c->pf, 0x34);
    return 0;
}
static int transfer_io(void *v, unsigned long long sector, unsigned int bytes, int write)
{
    struct test_ctx *c=v;
    int err;
    a7pf_write_reg(&c->pf, 0x18, sector);
    a7pf_write_reg(&c->pf, 0x1c, sector>>32);
    a7pf_write_reg(&c->pf, 0x20, bytes/512);
    a7pf_write_reg(&c->pf, 0x24, 512);
    a7pf_write_reg(&c->pf, 0x28, 0);
    err=op(c, write ? A7PF_WRITE : A7PF_READ);
    if (!err && a7pf_read_reg(&c->pf, 0x30)!=bytes) return -EIO;
    return err;
}
static int flush_io(void *v) { return op(v, A7PF_FLUSH); }
int run_trim(int fd, int geometry_fd, int enabled, unsigned int selector,
             int writable, int readonly, unsigned int cmd,
             unsigned long long capacity, const unsigned char *arg,
             unsigned int arg_bytes, int inject)
{
    struct test_ctx c;
    struct stat st;
    int rc;
    if (fstat(fd, &st)) return -errno;
    fault=inject;
    rc=a7pf_init(&c.pf, fd, geometry_fd, st.st_dev, st.st_ino, dma, &c);
    if (rc) return -rc;
    c.pf.io=(struct a7pf_io){.read=test_read,.write=test_write,.sync=test_sync};
    a7pf_write_reg(&c.pf, 0x10, selector);
    rc=pf_trim_zero(enabled, selector, writable, readonly, cmd, capacity,
                    arg, arg_bytes, c.bounce, &c, transfer_io, flush_io);
    a7pf_close(&c.pf);
    return rc;
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


class TrimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global OUTPUT
        if OUTPUT is None:
            root = HERE.parents[5] / 'analysis/scratch/p1-alfred-trim-batch-20261106'
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            OUTPUT = Path(tempfile.mkdtemp(prefix='pytest-', dir=root)) / 'run'
            prepare_output(OUTPUT)
        cls.lib = ctypes.CDLL(str(OUTPUT / 'bridge.so'))
        cls.lib.run_trim.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_ulonglong,
                                    ctypes.c_void_p, ctypes.c_uint, ctypes.c_int]
        cls.lib.run_trim.restype = ctypes.c_int
        cls.sectors = 257  # cross the real 128 KiB transfer limit
        cls.extent = cls.sectors * 512
        cls.capacity = 19 * cls.extent
        cls.offset = 3 * cls.extent
        geometry = b'A7PFGE01' + struct.pack('<IIQ', 1, 21, cls.capacity)
        for i in range(1, 20):
            geometry += struct.pack('<IIQQ', i, 0, (i-1)*cls.extent, cls.extent)
        for i in range(2):
            geometry += struct.pack('<IIQQ', 31+i, 0, cls.capacity+i*4194304, 4194304)
        path = OUTPUT / 'geometry.bin'
        path.write_bytes(geometry)
        path.chmod(0o600)
        cls.gfd = os.open(path, os.O_RDONLY)
        cls.before = b'\xa5' * (cls.capacity+8388608)
        cls.evidence = []

    @classmethod
    def tearDownClass(cls):
        os.close(cls.gfd)
        (OUTPUT / 'cases.json').write_text(json.dumps(cls.evidence, indent=2) + '\n')

    def setUp(self):
        self.path = OUTPUT / (self.id().split('.')[-1] + '.bin')
        self.path.write_bytes(self.before)
        self.path.chmod(0o600)
        self.fd = os.open(self.path, os.O_RDWR)
        self.assertTrue(stat.S_ISREG(os.fstat(self.fd).st_mode))

    def tearDown(self):
        os.close(self.fd)
        self.path.unlink()

    def invoke(self, *, enabled=1, selector=4, writable=1, readonly=0, cmd=0x40084124,
               capacity=None, wire=None, length=None, fault=0, fd=None):
        wire = struct.pack('<II', 0, self.sectors) if wire is None else wire
        arg = ctypes.create_string_buffer(wire) if wire else None
        return self.lib.run_trim(self.fd if fd is None else fd, self.gfd, enabled,
                                 selector, writable, readonly, cmd,
                                 self.sectors if capacity is None else capacity,
                                 arg, len(wire) if length is None else length, fault)

    def test_real_p4_zero_neighbors_and_boots_unchanged(self):
        self.assertNotEqual(self.before[self.offset:self.offset+self.extent], bytes(self.extent))
        self.assertEqual(self.invoke(), 0)
        # Independent file descriptor, no use of the model bounce/read cache.
        after = self.path.read_bytes()
        self.assertEqual(after[:self.offset], self.before[:self.offset])
        self.assertEqual(after[self.offset:self.offset+self.extent], bytes(self.extent))
        self.assertEqual(after[self.offset+self.extent:], self.before[self.offset+self.extent:])
        self.evidence.append(dict(case='p4-two-chunks', rc=0,
            p4_before_sha256=sha(self.before[self.offset:self.offset+self.extent]),
            p4_after_sha256=sha(after[self.offset:self.offset+self.extent]),
            expected_zero_sha256=sha(bytes(self.extent)),
            outside_before_sha256=sha(self.before[:self.offset]+self.before[self.offset+self.extent:]),
            outside_after_sha256=sha(after[:self.offset]+after[self.offset+self.extent:]),
            b0_b1_unchanged=after[self.capacity:]==self.before[self.capacity:]))

    def test_rejections_do_not_write(self):
        cases = [({'enabled':0}, errno.EOPNOTSUPP), ({'enabled':2}, errno.EOPNOTSUPP),
                 ({'selector':0}, errno.ENODEV), ({'selector':3}, errno.ENODEV),
                 ({'selector':5}, errno.ENODEV), ({'selector':31}, errno.ENODEV),
                 ({'selector':32}, errno.ENODEV), ({'writable':0}, errno.EBADF),
                 ({'readonly':1}, errno.EROFS), ({'cmd':0x1277}, errno.ENOTTY),
                 ({'cmd':0x40084125}, errno.ENOTTY), ({'wire':b''}, errno.EFAULT),
                 ({'wire':b'x'*7}, errno.EFAULT), ({'wire':b'x'*9}, errno.EFAULT),
                 ({'wire':struct.pack('<II',1,self.sectors)}, errno.EINVAL),
                 ({'wire':struct.pack('<II',0,0)}, errno.EINVAL),
                 ({'wire':struct.pack('<II',0,self.sectors-1)}, errno.EINVAL),
                 ({'wire':struct.pack('<II',0,self.sectors+1)}, errno.EINVAL),
                 ({'wire':struct.pack('<II',0xffffffff,0xffffffff)}, errno.EINVAL),
                 ({'capacity':0}, errno.EINVAL), ({'capacity':1<<32}, errno.EINVAL),
                 ({'capacity':(1<<64)-1}, errno.EINVAL)]
        for kwargs, expected in cases:
            with self.subTest(kwargs=kwargs):
                rc = self.invoke(**kwargs)
                self.assertEqual(rc, -expected)
                self.assertEqual(self.path.read_bytes(), self.before)
                self.evidence.append(dict(case=repr(kwargs), rc=rc, unchanged=True))

    def test_actual_backend_readonly(self):
        fd = os.open(self.path, os.O_RDONLY)
        try:
            self.assertEqual(self.invoke(fd=fd), -errno.EBADF)
            self.assertEqual(self.path.read_bytes(), self.before)
            self.evidence.append(dict(case='actual-readonly-fd', rc=-errno.EBADF, unchanged=True))
        finally:
            os.close(fd)

    def test_short_write_read_flush_and_readback_fail(self):
        for fault in (1, 2, 3, 4):
            with self.subTest(fault=fault):
                os.pwrite(self.fd, self.before, 0)
                rc = self.invoke(fault=fault)
                self.assertEqual(rc, -errno.EIO)
                after = self.path.read_bytes()
                self.assertEqual(after[:self.offset], self.before[:self.offset])
                self.assertEqual(after[self.offset+self.extent:], self.before[self.offset+self.extent:])
                self.evidence.append(dict(case='fault-'+str(fault), rc=rc,
                    outside_unchanged=True, rollback_claimed=False))


def prepare_output(output):
    root = HERE.parents[5] / 'analysis/scratch/p1-alfred-trim-batch-20261106'
    if not output.is_relative_to(root) or output.exists():
        raise ValueError('Fresh declared scratch test output required')
    if shutil.disk_usage(output.parent).free < 64*1024**2:
        raise ValueError('Need 64 MiB host free space')
    output.mkdir(mode=0o700)
    (output / 'bridge.c').write_text(BRIDGE)
    argv = ['cc','-shared','-fPIC','-O2','-std=c11','-Wall','-Wextra','-Werror',
            '-I'+str(HERE),'-I'+str(HERE.parent), str(output/'bridge.c'),
            str(HERE.parent/'flash-core.c'),'-o',str(output/'bridge.so')]
    compiled = subprocess.run(argv, capture_output=True, text=True)
    (output/'compile.json').write_text(json.dumps(dict(argv=argv, rc=compiled.returncode,
        stdout=compiled.stdout, stderr=compiled.stderr), indent=2)+'\n')
    if compiled.returncode:
        raise RuntimeError(compiled.stderr)


def main():
    global OUTPUT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    OUTPUT = a.output.absolute()
    prepare_output(OUTPUT)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TrimTests))
    (OUTPUT/'result.json').write_text(json.dumps(dict(status='passed' if result.wasSuccessful() else 'failed',
        tests=result.testsRun, errors=len(result.errors), failures=len(result.failures),
        shared_engine_sha256=sha((HERE/'trim-zero.h').read_bytes()),
        real_flash_core_sha256=sha((HERE.parent/'flash-core.c').read_bytes()),
        vm_executed=False, physical_compatibility=False), indent=2)+'\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
