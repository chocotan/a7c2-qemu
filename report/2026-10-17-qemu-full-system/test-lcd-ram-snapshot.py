#!/usr/bin/env python3
"""Bounded source/host checks only; no VM, canonical root or physical disk writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'lcd-ram-snapshot.py'))
PIN = HERE / 'runtime/native-source-snapshots/f52bcbda4c15c2b238dc7bb88199af9ef95160b7722db9e2a0e94d006c19e441/runtime/analysis'


class Sources(unittest.TestCase):
    def test_all_pinned_inputs_reject_drift_and_links(self):
        API['validate_pinned'](PIN)
        with tempfile.TemporaryDirectory(prefix='lcd-pin-') as temporary:
            out = Path(temporary)
            names = ('headless-osd.h', 'headless-osd.c', 'ramfb-viewer.c')
            for name in names:
                shutil.copyfile(PIN / name, out / name)
            API['validate_pinned'](out)
            for name in names:
                original = (out / name).read_bytes()
                (out / name).write_bytes(original + b'\n')
                with self.assertRaises(ValueError):
                    API['validate_pinned'](out)
                (out / name).unlink()
                (out / name).symlink_to(PIN / name)
                with self.assertRaises(ValueError):
                    API['validate_pinned'](out)
                (out / name).unlink()
                (out / name).write_bytes(original)

    def test_header_rejects_unknown_and_preserves_rest(self):
        original = (PIN / 'headless-osd.h').read_text()
        derived = API['path_header'](original)
        block = API['PATH_OVERRIDE'] + '\n#ifndef LCD_RAM_SNAPSHOT_V1\n' + API['OLD_PATH_BLOCK'] + '\n#endif'
        self.assertEqual(derived.replace(block, API['OLD_PATH_BLOCK']), original)
        for bad in (original + '\n', original.replace('/tmp/', '/elsewhere/'), derived):
            with self.assertRaises(ValueError):
                API['path_header'](bad)

    def test_both_compilers_use_same_fixed_path_and_strict_stays_original(self):
        with tempfile.TemporaryDirectory(prefix='lcd-source-') as temporary:
            out = Path(temporary)
            (out / 'headless-osd.h').write_text(API['path_header']((PIN / 'headless-osd.h').read_text()))
            producer = out / 'producer.c'
            producer.write_text('#include "headless-osd.h"\n')
            viewer = out / 'viewer.c'
            original_viewer = (HERE / 'guest/lcd-ramfb-stream.c').read_text()
            viewer.write_text(API['viewer_source'](original_viewer))
            for enabled in (False, True):
                paths = []
                for source in (producer, viewer):
                    command = ['clang', '-E', '-dM', '-I' + str(PIN)]
                    if enabled:
                        command += [API['COMPILE_DEFINE'], '-DHOSD_PATH="/must-not-be-configurable"']
                    result = subprocess.run(command + [str(source)], check=True, capture_output=True, text=True)
                    paths.append(re.search(r'^#define HOSD_PATH "([^"]+)"$', result.stdout, re.M)[1])
                self.assertEqual(paths, [API['SNAPSHOT_PATH'] if enabled else '/tmp/headless-osd-frame.bin'] * 2)
            self.assertEqual(API['viewer_source'](original_viewer).replace('\n' + API['PATH_OVERRIDE'], '', 1), original_viewer)
        receipt = API['receipt']()
        self.assertEqual(receipt['producer_path_sha256'], receipt['viewer_path_sha256'])
        self.assertEqual(receipt['producer_path_sha256'], hashlib.sha256(API['SNAPSHOT_PATH'].encode()).hexdigest())
        self.assertFalse(receipt['guest_devtmpfs_verified'])
        self.assertEqual(receipt['log_actual_targets'], ['/tmp/menu-load.log', '/log/qemu/menu-load.log'])
        self.assertEqual(receipt['log_known_logical_symlink'],
                         {'logical': '/tmp/menu-load.log', 'readlink': '/log/qemu/menu-load.log'})
        self.assertIn('FULLSYSTEM_LCD_RAM_LOG_ROUTE', receipt['boot_evidence'])
        with self.assertRaises(TypeError):
            API['path_header']((PIN / 'headless-osd.h').read_text(), path='/tmp/unpaired')

    def test_wrong_viewer_wrapper_and_duplicate_adaptation_rejected(self):
        viewer = (HERE / 'guest/lcd-ramfb-stream.c').read_text()
        wrapper = (HERE / 'guest/bootin-wrapper').read_text()
        for bad in ('', viewer.replace('open(HOSD_PATH,', 'open("elsewhere",'), API['viewer_source'](viewer)):
            with self.assertRaises(ValueError):
                API['viewer_source'](bad)
        for bad in ('', wrapper.replace(API['VIEWER_LAUNCH'], ''), API['wrapper_source'](wrapper)):
            with self.assertRaises(ValueError):
                API['wrapper_source'](bad)
        derived = API['wrapper_source'](wrapper)
        self.assertEqual(derived.replace(API['BOOT_SETUP'], '', 1), wrapper)
        self.assertLess(derived.index(API['BOOT_SETUP']), derived.index(API['VIEWER_LAUNCH']))
        self.assertEqual(API['BOOT_SETUP'], '/simulation/lcd-ram-bootstrap || { echo FULLSYSTEM_LCD_RAM_FAILED=bootstrap; exit 1; }\n')
        self.assertEqual(API['receipt']()['bootstrap_program'], '/simulation/lcd-ram-bootstrap')
        self.assertTrue((HERE / API['BOOTSTRAP_SOURCE']).is_file())
        self.assertNotIn('busybox', API['BOOT_SETUP'])
        for name, key in (('headless-osd.c', 'BASE_PRODUCER_SHA256'), ('ramfb-viewer.c', 'BASE_VIEWER_SHA256')):
            self.assertEqual(hashlib.sha256((PIN / name).read_bytes()).hexdigest(), API[key])


# Proc reads and fixed log paths are redirected only by this generated header.
# Log fixture ownership is normalized for unprivileged host checks, never guest
# code; the harness calls file checks directly and cannot invoke mount or run().
PROC_FIXTURE = r'''
#include <stdarg.h>
#include <stdlib.h>
static const char *fixture_path(const char *path,char *buffer,size_t size) {
    const char *root=getenv("LCD_RAM_LOG_FIXTURE");
    if(root && (!strcmp(path,"/tmp/menu-load.log") || !strcmp(path,"/log") ||
                !strcmp(path,"/log/qemu") || !strcmp(path,"/log/qemu/menu-load.log"))) {
        int n=snprintf(buffer,size,"%s%s",root,path);
        if(n<0 || (size_t)n>=size) abort();
        return buffer;
    }
    return path;
}
static int fixture_open(const char *path,int flags,...) {
    mode_t mode=0;
    if(flags&O_CREAT) { va_list args; va_start(args,flags); mode=va_arg(args,int); va_end(args); }
    const char *fixture=getenv("LCD_RAM_PROC_FIXTURE");
    if(fixture && (!strcmp(path,"/proc/self/status") || !strcmp(path,"/proc/self/mountinfo"))) path=fixture;
    char buffer[4096],link[4096];
    const char *mapped=fixture_path(path,buffer,sizeof(buffer));
    if(mapped!=path && !strcmp(path,"/tmp/menu-load.log") && !(flags&O_NOFOLLOW)) {
        ssize_t n=readlink(mapped,link,sizeof(link));
        const char *target="/log/qemu/menu-load.log";
        if(n==(ssize_t)strlen(target) && !memcmp(link,target,(size_t)n))
            mapped=fixture_path(target,buffer,sizeof(buffer));
    }
    return open(mapped,flags,mode);
}
static int fixture_lstat(const char *path,struct stat *st) {
    char buffer[4096];
    const char *mapped=fixture_path(path,buffer,sizeof(buffer));
    int rc=lstat(mapped,st);
    if(!rc && mapped!=path) st->st_uid=st->st_gid=0;
    return rc;
}
static int fixture_fstat(int fd,struct stat *st) {
    int rc=fstat(fd,st);
    if(!rc && getenv("LCD_RAM_LOG_FIXTURE")) st->st_uid=st->st_gid=0;
    return rc;
}
static ssize_t fixture_readlink(const char *path,char *text,size_t size) {
    char buffer[4096];
    return readlink(fixture_path(path,buffer,sizeof(buffer)),text,size);
}
#define open fixture_open
#define lstat fixture_lstat
#define fstat fixture_fstat
#define readlink fixture_readlink
'''

NATIVE_TEST = r'''
#include <assert.h>
#define main bootstrap_program_main
#include "bootstrap.c"
#undef main
int main(int argc,char **argv) {
    assert(argc>=2);
    if(!strcmp(argv[1],"root")) return check_root()!=0;
    if(!strcmp(argv[1],"mount")) return check_mounts(0)!=0;
    if(!strcmp(argv[1],"bound")) return check_mounts(1)!=0;
    if(!strcmp(argv[1],"project-mount") || !strcmp(argv[1],"project-bound")) {
        log_target=project_log;
        return check_mounts(!strcmp(argv[1],"project-bound"))!=0;
    }
    if(!strcmp(argv[1],"route")) {
        assert(argc==3);
        if(choose_log_target()) return 1;
        assert(log_target==(!strcmp(argv[2],"ordinary") ? ordinary_log : project_log));
        if(!strcmp(argv[2],"changed-before-open")) {
            char buffer[4096];
            const char *path=fixture_path(OLD_LOG,buffer,sizeof(buffer));
            assert(!unlink(path) && !symlink("/log/qemu/other.log",path));
        }
        int fd=open_log_target();
        if(fd<0) return 1;
        struct stat st;
        assert(!checked_fd(fd,log_target,&st,"test-route-inode"));
        assert(!empty_log(&st,"test-route-empty") && !eof_readback(fd));
        if(!strcmp(argv[2],"changed-before-alias")) {
            char buffer[4096];
            const char *path=fixture_path(OLD_LOG,buffer,sizeof(buffer));
            assert(!unlink(path) && !symlink("/log/qemu/other.log",path));
        }
        int rc=check_log_alias(&st);
        if(!rc) printf("target=%s inode=%llu:%llu\n",log_target,
                       (unsigned long long)st.st_dev,(unsigned long long)st.st_ino);
        close(fd);
        return rc!=0;
    }
    assert(!strcmp(argv[1],"files") && argc==6);
    struct stat a,b;
    struct statfs fs;
    int fd=open(argv[2],O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW,0600); assert(fd>=0);
    assert(!fchmod(fd,0600) && !fsync(fd));
    assert(!checked_fd(fd,argv[2],&a,"test-inode") && !eof_readback(fd));
    assert(!statfs(argv[2],&fs) && (unsigned long)fs.f_type==TMPFS_MAGIC);
    assert(!lstat(argv[2],&b) && same_inode(&a,&b));
    assert(S_ISREG(a.st_mode) && (a.st_mode&07777)==0600 && a.st_nlink==1);
    int other=open(argv[3],O_RDWR|O_CREAT|O_EXCL|O_NOFOLLOW,0600); assert(other>=0);
    assert(checked_fd(fd,argv[3],&b,"test-inode")==-1);
    assert(!symlink(argv[2],argv[4]));
    assert(checked_fd(fd,argv[4],&b,"test-symlink")==-1);
    assert(write(fd,"preserve",8)==8 && !fsync(fd));
    assert(eof_readback(fd)==-1);
    assert(!fstat(fd,&a)); a.st_uid=a.st_gid=0;
    assert(empty_log(&a,"test-log")==-1);
    char bytes[8]; assert(pread(fd,bytes,8,0)==8 && !memcmp(bytes,"preserve",8));
    int dir=open(argv[5],O_RDONLY|O_DIRECTORY); assert(dir>=0);
    assert(!empty_directory(dir)); close(dir);
    dir=open(argv[2],O_RDONLY|O_DIRECTORY); assert(dir<0 && errno==ENOTDIR);
    close(other); close(fd);
    return 0;
}
'''


class NativeBootstrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='lcd-native-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.out = Path(cls.temporary.name)
        (cls.out / 'fixture.h').write_text(PROC_FIXTURE)
        shutil.copyfile(HERE / API['BOOTSTRAP_SOURCE'], cls.out / 'bootstrap.c')
        (cls.out / 'test.c').write_text(NATIVE_TEST)
        cls.program = cls.out / 'test'
        subprocess.run(['clang', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                        '-DLCD_RAM_BOOTSTRAP_HOST_TEST="fixture.h"', str(cls.out / 'test.c'),
                        '-o', str(cls.program)], check=True)

    def execute(self, command, text):
        fixture = self.out / 'proc'
        fixture.write_text(text)
        return subprocess.run([str(self.program), command], capture_output=True, text=True,
                              env={**os.environ, 'LCD_RAM_PROC_FIXTURE': str(fixture)})

    def test_native_root_exact_ids_and_real_nonroot(self):
        valid = 'Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'
        result = self.execute('root', valid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count('FULLSYSTEM_LCD_RAM_ROOT '), 2)
        for bad in (valid.replace('Uid:\t0', 'Uid:\t1'), valid.replace('Gid:', 'Gid:bad'),
                    valid.replace('Gid:\t0\t0\t0\t0', 'Gid:\t0\t0\t1\t0'),
                    valid + 'Uid: 0 0 0 0\n', 'Uid: 0 0 0 0\n', valid.replace('Gid:', 'Gid:\x00')):
            with self.subTest(bad=bad):
                self.assertNotEqual(self.execute('root', bad).returncode, 0)
        if os.getuid() or os.getgid():
            env = dict(os.environ)
            env.pop('LCD_RAM_PROC_FIXTURE', None)
            result = subprocess.run([str(self.program), 'root'], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FULLSYSTEM_LCD_RAM_FAILED=root', result.stdout)
            for line in Path('/proc/self/status').read_text().splitlines():
                if line.startswith(('Uid:', 'Gid:')):
                    self.assertIn(line, result.stdout)

    def test_native_mountinfo_exact_fields_and_bounds(self):
        dev = '11 1 0:7 / /dev rw,nosuid shared:1 - devtmpfs devtmpfs rw\n'
        log = '22 11 0:7 /qemu-lcd/menu-load.log /tmp/menu-load.log rw - devtmpfs devtmpfs rw\n'
        self.assertEqual(self.execute('mount', dev).returncode, 0)
        result = self.execute('bound', dev + log)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('FULLSYSTEM_LCD_RAM_LOG_MOUNTINFO '), 1)
        for command, bad in (('mount', dev + log), ('mount', dev + dev),
                ('mount', dev.replace('/ /dev', '/sub /dev')), ('mount', dev.replace('devtmpfs', 'vfat')),
                ('mount', dev.replace('rw,nosuid', 'rwx')), ('mount', dev.replace('rw,nosuid', 'ro,rw')),
                ('mount', dev.replace(' - ', ' ')), ('mount', dev.rstrip() + ' trailing\n'),
                ('mount', dev.replace('0:7', 'bad:7')), ('mount', dev.replace('/ /dev', '/ /dev\\057')),
                ('mount', dev + '12 11 7:0 / /dev/qemu-lcd/child rw - vfat /dev/loop0 rw\n'),
                ('bound', dev + log.replace('/qemu-lcd/menu-load.log', '/wrong')),
                ('bound', dev), ('mount', 'x' * 4097 + '\n'), ('mount', dev * 1100)):
            with self.subTest(command=command, bad=bad[:100]):
                self.assertNotEqual(self.execute(command, bad).returncode, 0)
        self.assertEqual(self.execute('mount', dev + '12 1 0:8 / /space\\040name rw - tmpfs tmpfs rw\n').returncode, 0)
        project_log = log.replace('/tmp/menu-load.log', '/log/qemu/menu-load.log')
        for prefix, target in (('', log), ('project-', project_log)):
            with self.subTest(route=prefix):
                self.assertEqual(self.execute(prefix + 'mount', dev).returncode, 0)
                self.assertEqual(self.execute(prefix + 'bound', dev + target).returncode, 0)
                for bad in (dev + target.replace('/qemu-lcd/menu-load.log', '/wrong'),
                            dev + target.replace(' rw - ', ' ro - '),
                            dev + target.replace('devtmpfs devtmpfs', 'vfat /dev/p11'),
                            dev + log + project_log,
                            dev + log.replace('/tmp/menu-load.log', '/tmp/menu-load.log/nested'),
                            dev + project_log.replace('/log/qemu/menu-load.log', '/log/qemu/menu-load.log/nested')):
                    self.assertNotEqual(self.execute(prefix + 'bound', bad).returncode, 0)
                self.assertNotEqual(self.execute(prefix + 'mount', dev + target).returncode, 0)
                self.assertNotEqual(self.execute(prefix + 'bound', dev).returncode, 0)

    def route(self, root, kind='known'):
        env = {**os.environ, 'LCD_RAM_LOG_FIXTURE': str(root)}
        env.pop('LCD_RAM_PROC_FIXTURE', None)
        return subprocess.run([str(self.program), 'route', kind], env=env,
                              capture_output=True, text=True)

    def log_fixture(self, root, known=True):
        (root / 'tmp').mkdir()
        (root / 'log/qemu').mkdir(parents=True)
        logical = root / 'tmp/menu-load.log'
        actual = root / 'log/qemu/menu-load.log' if known else logical
        if known:
            logical.symlink_to('/log/qemu/menu-load.log')
        return logical, actual

    def test_known_link_and_ordinary_targets_share_empty_inode_checks(self):
        for known in (True, False):
            for existing in (True, False):
                with self.subTest(known=known, existing=existing), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    logical, actual = self.log_fixture(root, known)
                    link_before = logical.lstat() if known else None
                    if existing:
                        actual.touch(mode=0o600)
                    result = self.route(root, 'known' if known else 'ordinary')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(actual.read_bytes(), b'')
                    self.assertEqual(stat.S_IMODE(actual.stat().st_mode), 0o600)
                    self.assertEqual(actual.stat().st_nlink, 1)
                    self.assertIn(f'inode={actual.stat().st_dev}:{actual.stat().st_ino}', result.stdout)
                    if known:
                        self.assertEqual(os.readlink(logical), '/log/qemu/menu-load.log')
                        self.assertEqual(logical.lstat(), link_before)

    def test_other_links_and_linked_parents_are_rejected(self):
        for bad in ('/tmp/other.log', '/log/qemu/menu-load.log/extra', '../log/qemu/menu-load.log',
                    '/log/qemu/menu-load.logX', 'target-link', 'parent-link'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                logical, actual = self.log_fixture(root)
                if bad == 'target-link':
                    actual.symlink_to(root / 'untouched')
                    (root / 'untouched').write_bytes(b'preserve')
                elif bad == 'parent-link':
                    (root / 'log/qemu').rmdir()
                    (root / 'other').mkdir()
                    (root / 'log/qemu').symlink_to(root / 'other')
                else:
                    logical.unlink()
                    logical.symlink_to(bad)
                link_before = logical.lstat()
                result = self.route(root)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(logical.lstat(), link_before)
                if bad == 'target-link':
                    self.assertEqual((root / 'untouched').read_bytes(), b'preserve')

    def test_nonempty_target_is_preserved_for_both_routes(self):
        for known in (True, False):
            with self.subTest(known=known), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                logical, actual = self.log_fixture(root, known)
                actual.write_bytes(b'original-v10-log\x00preserve')
                before = actual.stat()
                link_before = logical.lstat()
                result = self.route(root, 'known' if known else 'ordinary')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FULLSYSTEM_LCD_RAM_FAILED=log-nonempty-preserved', result.stdout)
                self.assertEqual(actual.read_bytes(), b'original-v10-log\x00preserve')
                self.assertEqual(actual.stat(), before)
                self.assertEqual(logical.lstat(), link_before)

    def test_link_changed_between_stages_is_rejected(self):
        for stage in ('changed-before-open', 'changed-before-alias'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                logical, actual = self.log_fixture(root)
                actual.touch(mode=0o600)
                result = self.route(root, stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stdout, r'FULLSYSTEM_LCD_RAM_FAILED=log-(route-changed|symlink)')
                self.assertEqual(actual.read_bytes(), b'')
                self.assertEqual(os.readlink(logical), '/log/qemu/other.log')
                self.assertFalse((root / 'log/qemu/other.log').exists())

    def test_native_real_tmpfs_inode_type_symlink_readback_preservation(self):
        with tempfile.TemporaryDirectory(prefix='lcd-native-data-', dir='/dev/shm') as temporary:
            root = Path(temporary)
            (root / 'empty').mkdir()
            result = subprocess.run([str(self.program), 'files', str(root / 'log'), str(root / 'other'),
                                     str(root / 'link'), str(root / 'empty')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((root / 'log').read_bytes(), b'preserve')
            self.assertEqual(stat.S_IMODE((root / 'log').stat().st_mode), 0o600)


PERSIST_TEST = r'''
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "headless-osd.h"
static unsigned long checked, written, syncs;
static int fault;
long __real_pread(int, void *, unsigned long, long);
long __real_write(int, const void *, unsigned long);
int __real_fsync(int);
long __wrap_pread(int fd, void *p, unsigned long n, long off) {
    long rc=__real_pread(fd,p,n,off);
    if (rc>0) { checked+=rc; if (fault==2) ((unsigned char *)p)[rc-1]^=1; }
    return rc;
}
long __wrap_write(int fd, const void *p, unsigned long n) {
    long rc=__real_write(fd,p,n); if(rc>0) written+=rc; return rc;
}
int __wrap_fsync(int fd) {
    syncs++; if(fault==1) { errno=EIO; return -1; }
    return __real_fsync(fd);
}
int main(int argc, char **argv) {
    assert(argc==2);
    unsigned char *bytes=malloc(HOSD_BYTES); assert(bytes);
    for(unsigned long i=0;i<HOSD_BYTES;i++) bytes[i]=(i*37+9)&255;
    assert(hosd_persist(argv[1],bytes,HOSD_BYTES)==0);
    assert(written==HOSD_BYTES && checked==HOSD_BYTES && syncs==1);
    for(fault=1; fault<=2; fault++) {
        bytes[0]^=1; assert(hosd_persist(argv[1],bytes,HOSD_BYTES)==-1); bytes[0]^=1;
        int fd=open(argv[1],O_RDONLY); assert(fd>=0);
        unsigned char *readback=malloc(HOSD_BYTES); assert(readback);
        assert(read(fd,readback,HOSD_BYTES)==HOSD_BYTES && !memcmp(bytes,readback,HOSD_BYTES));
        assert(!close(fd)); free(readback);
    }
    printf("%lu\n",(unsigned long)HOSD_BYTES); free(bytes); return 0;
}
'''


class Persistence(unittest.TestCase):
    def test_original_persist_real_tmpfs_fsync_full_readback_and_failures(self):
        with tempfile.TemporaryDirectory(prefix='lcd-persist-') as temporary:
            out = Path(temporary)
            (out / 'headless-osd.h').write_text(API['path_header']((PIN / 'headless-osd.h').read_text()))
            shutil.copyfile(PIN / 'headless-osd.c', out / 'headless-osd.c')
            (out / 'test.c').write_text(PERSIST_TEST)
            program = out / 'test'
            subprocess.run(['clang', '-O2', '-ffunction-sections', '-fdata-sections', API['COMPILE_DEFINE'],
                            '-Wl,--gc-sections', '-Wl,--wrap=fsync', '-Wl,--wrap=write', '-Wl,--wrap=pread',
                            str(out / 'headless-osd.c'), str(out / 'test.c'), '-o', str(program)], check=True)
            with tempfile.TemporaryDirectory(prefix='lcd-persist-data-', dir='/dev/shm') as data_dir:
                self.assertEqual(subprocess.check_output(['stat', '-f', '-c', '%t', data_dir], text=True).strip(), '1021994')
                path = Path(data_dir) / 'frame.bin'
                result = subprocess.run([str(program), str(path)], check=True, capture_output=True, text=True)
                length = int(result.stdout)
                expected = bytes((i*37+9)&255 for i in range(length))
                self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), hashlib.sha256(expected).digest())
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertFalse(path.with_name('frame.bin.part').exists())


if __name__ == '__main__':
    unittest.main()
