#!/usr/bin/env python3
"""Host-only install admission, immutable rollback bindings and real guard ABI."""
from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
M=runpy.run_path(str(HERE/'newp1-virtual-install.py'))
U=M['api']()


class Install(unittest.TestCase):
    def valid(self):
        return dict(mode='official',read_only=False,allow_updater_writes=True,media={'bound':1},sd={'image':1},
            module=dict(protocol=U['PROTOCOL'],build_bound=True,large_io_fix_bound=True,updater_write_eligible=True,
                        module_sha256=U['CURRENT_MODULE_SHA'],kernel_sha256=U['KERNEL_SHA'],driver={'sha256':U['CURRENT_DRIVER_SHA']}))

    def test_explicit_write_profile_preserves_every_identity_boundary(self):
        valid=self.valid();M['admit'](M['PROFILE'],**valid)
        for key,value in [('mode','virtual-dev-sd-update-v1'),('read_only',True),('read_only',0),
                          ('allow_updater_writes',False),('allow_updater_writes',1),('media',None),('sd',None)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                M['admit'](M['PROFILE'],**dict(valid,**{key:value}))
        for key in valid['module']:
            bad=copy.deepcopy(valid);bad['module'][key]=False
            with self.subTest(module=key),self.assertRaises((ValueError,AttributeError)):
                M['admit'](M['PROFILE'],**bad)
        for profile in (None,'official','original-p1-sd-readonly-v1','unknown'):
            with self.assertRaises(ValueError):M['admit'](profile,**valid)

    def test_update_write_flags_require_install_profile_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'absent'
            for kwargs in (dict(allow_updater_writes=True),dict(read_only=False),dict(install_receipt='/dev/sda'),
                dict(install_profile=M['PROFILE'],read_only=False,allow_updater_writes=True),
                dict(install_profile='unknown')):
                with self.assertRaises(ValueError):U['build']('/not-instance','/runtime',out,mode='official',**kwargs)
            self.assertFalse(out.exists())

    def fixture(self,p):
        paths=[p/n for n in ('baseline','before','clone')]
        for path in paths:
            path.mkdir();(path/'camera.emmc').write_bytes(b'current validated virtual camera bytes')
        (paths[2]/'geometry.json').write_text('{}')
        p2=p/'old-p2';p2.write_bytes(b'old p2')
        value=dict(schema=M['SCHEMA'],profile=M['PROFILE'],status='prepared',source_reseeded=False,
            physical_devices_used=False,readback_verified=True,source_instance=str(paths[0]),
            before_instance=str(paths[1]),instance=str(paths[2]),source=U['record'](paths[0]/'camera.emmc'),
            before=U['record'](paths[1]/'camera.emmc'),clone=U['record'](paths[2]/'camera.emmc'),
            expected_source_sha256=U['record'](paths[0]/'camera.emmc')['sha256'],
            geometry=U['record'](paths[2]/'geometry.json'),p2_before=U['record'](p2))
        receipt=p/'clone.json';receipt.write_text(json.dumps(value))
        return paths,value,receipt

    def test_clone_receipt_schema_source_before_hash_and_aliases(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);paths,v,receipt=self.fixture(p);digest=U['record'](receipt)['sha256']
            M['clone_contract'](paths[2],receipt,digest)
            with self.assertRaises(ValueError):M['clone_contract'](paths[0],receipt,digest)
            with self.assertRaises(ValueError):M['clone_contract'](paths[2],receipt,'0'*64)
            for key,value in [('schema','old'),('profile','original-p1-sd-readonly-v1'),('source_reseeded',True),
                              ('physical_devices_used',True),('readback_verified',False),('before_instance',str(paths[2]))]:
                bad=dict(v,**{key:value});receipt.write_text(json.dumps(bad))
                with self.subTest(key=key),self.assertRaises(ValueError):
                    M['clone_contract'](paths[2],receipt,U['record'](receipt)['sha256'])
            receipt.write_text(json.dumps(v));digest=U['record'](receipt)['sha256']
            for path in paths:
                disk=path/'camera.emmc';data=disk.read_bytes();disk.write_bytes(b'changed baseline')
                with self.assertRaisesRegex(ValueError,'identity/hash'):M['clone_contract'](paths[2],receipt,digest)
                disk.write_bytes(data)
            disk=paths[2]/'camera.emmc';disk.unlink();os.link(paths[0]/'camera.emmc',disk)
            with self.assertRaises(ValueError):M['clone_contract'](paths[2],receipt,digest)

    def test_restore_waits_for_exclusive_lease_and_clones_before_into_fresh_instance(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d=U['DISK'];paths=[]
            data=b'82462.00'+b'current version and features'.ljust(504,b'\0')
            for name in ('source','before','clone'):
                path=p/name;path.mkdir();paths.append(path)
                (path/'camera.emmc').write_bytes(data)
                (path/'geometry.json').write_text(json.dumps(dict(schema=d['SCHEMA'],backing_bytes=512)))
                (path/'instance.json').write_text(json.dumps(dict(schema=d['SCHEMA'],state='stopped',
                    geometry_sha256=hashlib.sha256((path/'geometry.json').read_bytes()).hexdigest())))
                (path/'.disk.lock').touch()
            value=dict(schema=M['SCHEMA'],profile=M['PROFILE'],instance=str(paths[2]),before_instance=str(paths[1]),
                       before=U['record'](paths[1]/'camera.emmc'),expected_source_sha256=hashlib.sha256(data).hexdigest())
            receipt=p/'receipt.json';receipt.write_text(json.dumps(value));digest=U['record'](receipt)['sha256']
            with d['lease'](paths[2]):
                with self.assertRaises(BlockingIOError):M['restore'](receipt,digest,p/'restored')
            self.assertFalse((p/'restored').exists())
            restored=M['restore'](receipt,digest,p/'restored')
            self.assertEqual((restored/'camera.emmc').read_bytes(),data)
            self.assertNotEqual((restored/'camera.emmc').stat().st_ino,(paths[1]/'camera.emmc').stat().st_ino)
            with self.assertRaises(ValueError):M['restore'](receipt,digest,p/'restored')
            for path in paths:self.assertEqual((path/'camera.emmc').read_bytes(),data)
            (paths[1]/'camera.emmc').write_bytes(b'changed before')
            with self.assertRaisesRegex(ValueError,'before identity'):M['restore'](receipt,digest,p/'bad-restore')
            self.assertFalse((p/'bad-restore').exists())

    def test_ranges_include_all_partitions_boot_gaps_and_nonzero_tail(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'disk';data=bytes(range(128));path.write_bytes(data)
            with path.open('rb') as f:
                rows=M['ranges'](f.fileno(),{'slices':[dict(id='p2',offset=16,bytes=32),dict(id='boot0',offset=64,bytes=32)]})
            self.assertEqual(sum(r['bytes'] for r in rows),128)
            self.assertEqual([r['id'] for r in rows],['gap-0','p2','gap-48','boot0','tail'])
            for row in rows:self.assertEqual(row['sha256'],hashlib.sha256(data[row['offset']:row['offset']+row['bytes']]).hexdigest())

    def test_rw_guard_real_ioctl_rejects_regular_and_physical_path_arguments(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);c=p/'guard.c';c.write_text(M['WRITE_GUARD']+'\nint main(int c,char **v){return run(c,v);}\n')
            subprocess.run(['cc','-Wall','-Wextra',str(c),'-o',str(p/'guard')],check=True,capture_output=True)
            for nodes in ([str(p/'file')]*20,['/dev/sda']*20,['/dev/'+n for n in M['NODES']]):
                rc=subprocess.run([str(p/'guard'),*nodes],env=dict(os.environ,A7C2_FILE_MEDIA_TEST='1',
                    A7C2_P1_FILE_MEDIA_PROFILE='original-sd-v1'),capture_output=True)
                self.assertEqual(rc.returncode,125)
            self.assertNotIn('0x125d',M['WRITE_GUARD'])
            self.assertIn('ro!=0',M['WRITE_GUARD'])
            self.assertIn('S_ISBLK',M['WRITE_GUARD'])
            self.assertIn('major(st.st_rdev)==ma',M['WRITE_GUARD'])

    def test_twenty_ioctl_results_and_exact_project_backend_are_consumed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            prelude=r'''
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static int selected;
static int fake_open(const char *p,int flags,...){(void)flags;const char *n=p+5;selected=0;if(!strcmp(n,"nflashaB0"))selected=64;else if(!strcmp(n,"nflashaB1"))selected=65;else if(!strncmp(n,"cnflasha",8))selected=atoi(n+8)+128;return 100;}
static int fake_close(int fd){(void)fd;return 0;}
static int fake_stat(int fd,struct stat *st){(void)fd;memset(st,0,sizeof *st);st->st_mode=S_IFBLK;st->st_rdev=makedev(getenv("BAD_ID")?255:254,selected);return 0;}
static int fake_ioctl(int fd,unsigned long request,int *ro){(void)fd;if(request!=0x125eUL)abort();*ro=atoi(getenv("TEST_RO"));return 0;}
static FILE *fake_fopen(const char *p,const char *mode){(void)mode;FILE *f=tmpfile();if(!strcmp(p,"/proc/devices"))fputs(getenv("TEST_DEVICES"),f);else if(!strcmp(p,"/proc/modules"))fputs(getenv("TEST_MODULES"),f);else {const char *n=p+11;int minor=0;if(!strncmp(n,"cnflasha",8))minor=atoi(n+8)+128;else if(!strncmp(n,"nflashaB0",9))minor=64;else if(!strncmp(n,"nflashaB1",9))minor=65;fprintf(f,"254:%d\n",minor);}rewind(f);return f;}
'''
            source=M['WRITE_GUARD']
            for a,b in [('fopen(', 'fake_fopen('),('open(', 'fake_open('),('close(', 'fake_close('),('ioctl(', 'fake_ioctl('),('fstat(', 'fake_stat(')]:
                # Replace whole function tokens; fopen/close must not alter other identifiers.
                import re
                source=re.sub(r'\b'+re.escape(a),b,source)
            c=p/'test.c';c.write_text(prelude+source+'\nint main(int c,char **v){return run(c,v);}\n')
            subprocess.run(['cc',str(c),'-o',str(p/'guard')],check=True,capture_output=True)
            argv=[str(p/'guard'),*['/dev/'+n for n in M['NODES']]]
            # Captured .186 rows: p1-sd-initialize guest/serial.log:1026,1047-1051.
            devices='Character devices:\n254 uio\n\nBlock devices:\n  1 ramdisk\n259 blkext\n  7 loop\n254 sony-persistent\n'
            modules='sony_persistent_flash 16384 0 - Live 0xffffff80004b0000 (O)\n'
            env=dict(os.environ,A7C2_FILE_MEDIA_TEST='1',A7C2_P1_FILE_MEDIA_PROFILE='original-sd-v1',TEST_RO='0',
                     TEST_DEVICES=devices,TEST_MODULES=modules)
            result=subprocess.run(argv,env=env,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual(result.stdout.count(b'get_rc=0 readonly=0 project_backend=1'),20)
            for changes in ({'TEST_RO':'1'},{'TEST_RO':'2'},{'BAD_ID':'1'},{'A7C2_P1_FILE_MEDIA_PROFILE':'unknown'},
                {'TEST_DEVICES':devices.replace('sony-persistent','sony-persistent-flash')},
                {'TEST_DEVICES':devices.replace('sony-persistent','sony-persistentX')},
                {'TEST_DEVICES':devices.replace('sony-persistent','sony-persisten')},
                {'TEST_DEVICES':devices.replace('Block devices:\n','')},
                {'TEST_DEVICES':'Character devices:\n254 sony-persistent\n\nBlock devices:\n  1 ramdisk\n'},
                {'TEST_DEVICES':devices+'254 sony-persistent\n'},
                {'TEST_DEVICES':devices.replace('254 sony-persistent','254 sony-persistent extra')},
                {'TEST_DEVICES':devices.replace('254 sony-persistent','253 sony-persistent')},
                {'TEST_MODULES':''},{'TEST_MODULES':modules.replace(' Live ',' Loading ')},
                {'TEST_MODULES':modules.replace('sony_persistent_flash','sony_persistent_flashX')},
                {'TEST_MODULES':modules+modules}):
                with self.subTest(changes=changes):
                    result=subprocess.run(argv,env=dict(env,**changes),capture_output=True)
                    self.assertEqual(result.returncode,125,(changes,result.stdout))
            collision=dict(env,TEST_DEVICES=devices.replace('254 uio','254 sony-persistent'))
            self.assertEqual(subprocess.run(argv,env=collision,capture_output=True).returncode,0)
            for nodes in ([*argv[:-1],argv[1]],[*argv[:-1],'/dev/sda']):
                self.assertEqual(subprocess.run(nodes,env=env,capture_output=True).returncode,125)

    def test_guest_recognizes_only_exact_profile_and_does_not_refresh_initial_backup(self):
        source=(HERE/'guest/update-storage-bootstrap').read_text()
        self.assertIn('original-p1-virtual-install-v1) install_guard || return 125',source)
        self.assertIn('*) return 125',source)
        self.assertIn('2390264:b863f8b61d1a979b964419a99c9a0f27169958f8f5cbb204b7a4eee3b127cdff',source)
        self.assertIn('/simulation/media-backup-query\n    rc=$?',source)
        self.assertNotIn('> /simulation/backup-file-source',source)
        self.assertNotIn('mount -o rw',source)
        subprocess.run(['/bin/sh','-n',str(HERE/'guest/update-storage-bootstrap')],check=True)

    def test_actual_checks_initial_clone_once_and_accepts_changed_target_in_postrun_evidence(self):
        execution=runpy.run_path(str(HERE/'p1-update-execution.py'))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);instance=p/'instance';instance.mkdir();work=p/'build';work.mkdir()
            disk=instance/'camera.emmc';disk.write_bytes(b'initial target')
            source=p/'baseline';source.write_bytes(b'initial target');before=p/'before';before.write_bytes(b'initial target')
            initial=U['record'](disk);fd=os.open(disk,os.O_RDWR);self.addCleanup(os.close,fd)
            update=p/'update.json';update.write_text('{}');events=[]
            manifest=dict(schema=execution['PROFILE'],status='built',mode='official',read_only=False,
                install_profile=M['PROFILE'],allow_updater_writes=True,no_install=False,instance=str(instance),output=str(work),
                qemu={'sha256':'fixed-provider'},media_resources={'bound':True},update_manifest={'path':str(update)},
                sd_cpio_readback={},inputs=[],artifacts=[],
                state=U['record'](source),geometry=U['record'](before),disk_sha256=initial['sha256'],
                disk_device=initial['device'],disk_inode=initial['inode'])
            execution['save'](work/'manifest.json',manifest)
            @contextmanager
            def lease(path):
                events.append('lease');yield dict(fd=fd,geometry={});events.append('release')
            def preflight(*args,**kwargs):
                events.append('launch-preflight')
                self.assertEqual(execution['DISK']['hashed'](fd),initial['sha256'])
            def ranges(leased_fd,geometry):
                return [dict(id='all',sha256=execution['DISK']['hashed'](leased_fd))]
            install_api=dict(preflight=preflight,ranges=ranges)
            sd_api={'QEMU_SHA':'fixed-provider','cpio_readback':lambda *args:events.append('cpio')}
            original_run_path=runpy.run_path
            def run_path(path,*args,**kwargs):
                if str(path).endswith('/newp1-virtual-install.py'):return install_api
                if str(path).endswith('/p1-sd-read-probe.py'):return sd_api
                return original_run_path(path,*args,**kwargs)
            class Process:
                pid=os.getpid();returncode=None
                def poll(self):return self.returncode
                def wait(self,timeout=None):events.append('wait');self.returncode=0
            process=Process()
            def popen(argv,**kwargs):
                events.append('write');os.pwrite(fd,b'updated target',0);os.fsync(fd)
                kwargs['stdout'].write(b'UPDATE_SD_RECEIVER_EXIT pid=123 rc=0\n');kwargs['stdout'].flush()
                return process
            def qmp(path):
                class Stream:
                    def close(self):pass
                def command(name,args=None):
                    events.append(name)
                    return {'return':{'name':'p1-update-mutable'}} if name=='query-name' else {'return':{}}
                return Stream(),Stream(),command
            observation=dict(root_verified=True,kernel_release_verified=True,module_loaded=True,p2_matches_build=True,
                original_init_executed=True,writable_targets_verified=True,original_resource_chain_loaded=True,
                media_backup_query={'original_readback_verified':True})
            with patch.dict(execution['DISK'],lease=lease),patch.object(execution['runpy'],'run_path',run_path), \
                 patch.object(execution['subprocess'],'Popen',popen),patch.object(execution['secrets'],'token_hex',return_value='mutable'), \
                 patch.dict(execution['OWNER'],qmp_connect=qmp),patch.dict(execution['actual'].__globals__,
                    launch_command=lambda *args:['host-test-only'],collect=lambda *args:dict(observation)):
                result=execution['actual'](manifest,p/'guest')
            self.assertTrue(result['verified'],result)
            self.assertEqual(events.count('launch-preflight'),1)
            self.assertLess(events.index('launch-preflight'),events.index('write'))
            self.assertLess(events.index('quit'),events.index('wait'))
            self.assertLess(events.index('wait'),events.index('release'))
            self.assertFalse(result['disk_unchanged'])
            self.assertNotEqual(result['partition_before'],result['partition_after'])
            self.assertEqual(result['disk_before_sha256'],initial['sha256'])
            for name in ('installation_verified','sdfileinput_read_verified','writer_completion_verified','upm_successor_verified'):
                self.assertFalse(result[name],name)
            self.assertEqual(source.read_bytes(),b'initial target');self.assertEqual(before.read_bytes(),b'initial target')
            self.assertEqual(manifest['disk_sha256'],initial['sha256'])
            self.assertEqual(json.loads((work/'manifest.json').read_text()),manifest)

    def test_collector_rw_proof_requires_exact_twenty_real_results(self):
        execution=runpy.run_path(str(HERE/'p1-update-execution.py'))
        tests=runpy.run_path(str(HERE/'test-p1-update-execution.py'))
        raw=tests['serial']()+''.join('UPDATE_INSTALL_TARGET node=/dev/'+n+' get_rc=0 readonly=0 project_backend=1\n'
                                    for n in M['NODES']).encode()
        self.assertTrue(execution['collect'](raw,tests['manifest']())['writable_targets_verified'])
        for changed in (raw.replace(b'readonly=0 project_backend=1',b'readonly=1 project_backend=1'),
                        raw.replace(b'project_backend=1',b'project_backend=0'),raw.replace(b'node=/dev/pnflasha get_rc=0 readonly=0',b'node=/dev/sda get_rc=0 readonly=0')):
            self.assertFalse(execution['collect'](changed,tests['manifest']())['writable_targets_verified'])
        result=execution['collect'](raw,tests['manifest']())
        self.assertFalse(result['installation_verified']);self.assertFalse(result['sdfileinput_read_verified'])


if __name__=='__main__':unittest.main()
