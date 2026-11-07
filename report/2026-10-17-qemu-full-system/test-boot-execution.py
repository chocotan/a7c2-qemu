from pathlib import Path
import ast
import base64
import hashlib
import runpy
import os
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

m=runpy.run_path(str(Path(__file__).with_name('boot-execution.py')))
IM_SHA='5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91'
IM_EXPECTED='COLD_EXPECTED_IM version=ILCE-7CM2-2.01 sha256='+IM_SHA+'\n'


class BootExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.console=self.root/'console.log'

    def collect(self,text):
        self.console.write_text(text)
        receipt=m['new_receipt']('original-init-cold',bindings={'run':'cold-one','source_class':'private-device-dump'})
        result=m['collect'](self.console,receipt)
        return receipt,result

    def test_commands_only_do_not_prove_root_transition(self):
        receipt,result=self.collect('COLD_BEFORE_ORIGINAL_INIT\n+ . /sbin/initrc/setup_rootfs\n'
            '+ /sbin/pivot_root . /rootfs/initrd\n+ exec busybox chroot . /bin/ash\n')
        self.assertTrue(result['stage_verified']['ram_init'])
        for stage in ['mounts','pivot_root','chroot','init2','ap']:
            self.assertFalse(result['stage_verified'][stage])
        self.assertFalse(result['full_boot_verified'])

    def mounted(self, shared=True):
        rows=[]
        for i,(target,fs,dev) in enumerate([('/', 'ext2','7'),('/setting','vfat','2'),('/system','vfat','3'),
            ('/cp','vfat','8'),('/log','vfat','11'),('/cert','vfat','12'),('/lens','vfat','18'),
            ('/tmp','vfat','10'),('/etc','vfat','10'),('/var','vfat','10' if shared else '6'),('/usr','ext2','15')],100):
            options='ro' if target in ('/','/usr') else 'rw'
            rows.append(f'{i} 1 7:{dev} / {target} {options} - {fs} /dev/nflasha{dev} {options}')
        return '\n'.join(rows)+'\n'

    def base(self):
        return ('COLD_BEFORE_ORIGINAL_INIT\n+ . /sbin/initrc/setup_rootfs\n'
            '+ /sbin/pivot_root . /rootfs/initrd\n+ exec busybox chroot . /bin/ash\n'
            'COLD_INIT2_PROCESS parent=12\n/bin/busybox\x00sh\x00/sbin/init2\x00\n')

    def test_original_trace_plus_actual_post_root_init2_is_required(self):
        _,result=self.collect(self.base()+self.mounted())
        for stage in ['ram_init','mounts','pivot_root','chroot','init2']:
            self.assertTrue(result['stage_verified'][stage],stage)
        for stage in ['cp','loader','wbi','ram_hotboot','watchdog','ap']:
            self.assertFalse(result['stage_verified'][stage],stage)
        self.assertFalse(result['cold_guest_chain_verified'])
        self.assertFalse(result['full_boot_verified'])

    def test_original_init2_fallback_on_ram_root_is_not_a_p7_chroot(self):
        _,result=self.collect(self.base()+self.mounted().replace('ext2 /dev/nflasha7', 'ext2 /dev/ram0'))
        self.assertFalse(result['stage_verified']['chroot'])
        self.assertFalse(result['stage_verified']['mounts'])
        self.assertFalse(result['stage_verified']['init2'])

    def test_shared_tmp_etc_var_capacity_cannot_be_faked_by_three_mounts(self):
        _,result=self.collect(self.base()+self.mounted(False))
        self.assertFalse(result['stage_verified']['mounts'])

    def test_wrapper_marker_is_not_original_bootin_execution(self):
        receipt,result=self.collect('COLD_BOOTIN_ENTRY pid=20\nFULLSYSTEM_BOOTIN_ENTER\n')
        self.assertFalse(result['stage_verified']['bootin'])
        self.assertFalse(result['stage_verified']['im'])
        self.assertFalse(result['stage_verified']['ap'])

    def test_persistent_bootin_requires_actual_process_executable_hash(self):
        for digest,expected in [(m['BOOTIN_SHA256'],True),('a'*64,False)]:
            _,result=self.collect('PERSISTENT_BOOTIN_BIND verified=1 original=/dev/qemu-simulation/bootin-original\n'
                'COLD_NATIVE_BOOTIN pid=42 sha256='+digest+'\n')
            self.assertEqual(result['stage_verified']['bootin'],expected)
            self.assertFalse(result['full_boot_verified'])
        _,result=self.collect('PERSISTENT_BOOTIN_BIND verified=1 original=/dev/qemu-simulation/bootin-original\n')
        self.assertFalse(result['stage_verified']['bootin'])

    def test_proc_cmdline_can_prove_full_arguments_after_kernel_log_truncation(self):
        expected='root=/dev/ram0 '+('functional=value '*100).strip()
        receipt=m['new_receipt']('original-init-cold',bindings={'run':'one','source_class':'private-device-dump'},kernel_cmdline=expected)
        self.console.write_text('Kernel command line: root=/dev/ram0 truncated\n'
            'COLD_KERNEL_CMDLINE_BEGIN\n'+expected+'\nCOLD_KERNEL_CMDLINE_END\n')
        result=m['collect'](self.console,receipt)
        self.assertTrue(result['stage_verified']['kernelargs'])
        self.assertFalse(result['full_boot_verified'])

    def test_original_ap_stage_needs_matching_process_hash_entry_and_real_osd(self):
        lines=['COLD_AP_MAP pid=745 sha256='+m['APPFW_SHA256']+'\n',
               'OBS OBSERVER_READY pid=745 base=0x7f12340000 mode=original\n',
               'OBS CREATE_SCREEN_ARGS call=4 id=0 count=565 orientation=0\n',
               'OBS OSD_HEADLESS_PERSISTED seq=8 pixel_source_seq=7 id=0x402 phys=0x430000000 geometry=640x480 bytes=614400 fnv1a64=0123456789abcdef mode=AP-RGBA4444-experimental path=/dev/qemu-simulation/headless-osd-frame.bin\n']
        _,result=self.collect(''.join(lines));self.assertTrue(result['ap_verified'])
        for index in range(len(lines)):
            _,result=self.collect(''.join(line for i,line in enumerate(lines) if i!=index))
            self.assertFalse(result['ap_verified'])
        for original,replacement in [('pid=745 base=','pid=746 base='),('pixel_source_seq=7','pixel_source_seq=0'),
                                     ('pixel_source_seq=7','pixel_source_seq=9'),('bytes=614400','bytes=0')]:
            _,result=self.collect(''.join(lines).replace(original,replacement))
            self.assertFalse(result['ap_verified'])

    def test_long_diagnostic_uses_bounded_quoted_heredoc_lines(self):
        script='; '.join("echo 'line "+str(i)+"'" for i in range(150))+'\n'
        envelope=m['diagnostic_envelope'](script,'OWNED_DIAGNOSTIC')
        self.assertGreater(len(script),1024)
        self.assertLessEqual(max(map(len,envelope.splitlines())),512)
        self.assertTrue(envelope.startswith("busybox sh <<'OWNED_DIAGNOSTIC'\n"))
        result=subprocess.run(['/bin/sh'],input=envelope.replace('busybox sh <<','sh <<',1),capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout,''.join('line '+str(i)+'\n' for i in range(150)))
        for tag in ['bad\nmarker','bad;marker','OWNED']:
            with self.assertRaises(ValueError):m['diagnostic_envelope']('OWNED\n',tag)

    def test_serial_diagnostics_keep_fifo_pacing_and_short_writes(self):
        class Stream:
            def __init__(self):self.data=bytearray();self.flushes=0;self.requests=[]
            def write(self,data):
                self.requests.append(len(data));count=min(len(data),3);self.data.extend(data[:count]);return count
            def flush(self):self.flushes+=1
        stream=Stream();payload=bytes(range(45));sleep=[]
        with patch.object(m['write_console'].__globals__['time'],'sleep',side_effect=sleep.append):
            m['write_console'](stream,payload)
        self.assertEqual(stream.data,payload);self.assertEqual(stream.flushes,3)
        self.assertTrue(all(n<=16 for n in stream.requests));self.assertEqual(sleep,[.005]*3)
        class Broken:
            def write(self,data):return 0
        with self.assertRaisesRegex(OSError,'Serial input write'):m['write_console'](Broken(),b'x')

    def test_console_handle_alone_cannot_prove_original_ap(self):
        for value in ['0x0','0x1234','0x7f12345000']:
            _,result=self.collect(self.base()+self.mounted()+'RETURN_HANDLE Application_System_Init handle='+value+'\n')
            self.assertFalse(result['ap_verified'])
            self.assertFalse(result['cold_guest_chain_verified'])
            self.assertFalse(result['full_boot_verified'])

    def test_ram0_release_requires_original_success_and_zero_readback(self):
        for extra, expected in [('COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512\n',True),
                                ('COLD_RAM0_RELEASE original_rc=1 zero_prefix=1 bytes=512\n',False),
                                ('COLD_RAM0_RELEASE original_rc=0 zero_prefix=0 bytes=512\n',False),
                                ('freeramdisk requested\n',False)]:
            _,result=self.collect(self.base()+self.mounted()+extra)
            self.assertEqual(result['stage_verified']['ram0_release'],expected)

    def test_leased_disk_fd_reaches_owner_and_owner_is_registered(self):
        payload=self.root/'lease-payload'
        payload.write_bytes(b'owned-persistent-disk')
        fd=os.open(payload,os.O_RDONLY)
        self.addCleanup(os.close,fd)
        children=[]
        launch={'command':[sys.executable,'-c',
                'import os,sys; print(os.read(int(sys.argv[1]),64).decode())',str(fd)],
                'env':{'PATH':os.defpath},'pass_fds':(fd,),'children':children,
                'script_sha256':'a'*64,'dtb_sha256':'b'*64,'cmdline':'test-only',
                'qmp_socket':str(self.root/'absent-qmp.sock')}
        cold={'source':'test-only','ram0_sha256':'c'*64,'script_identity':{}}
        result=m['run'](launch,cold,self.root/'execution',seconds=2)
        self.assertEqual(len(children),1)
        self.assertEqual(children[0].poll(),0)
        self.assertIn(b'owned-persistent-disk',(self.root/'execution/console.log').read_bytes())
        self.assertEqual(result['owner']['owner_pid'],children[0].pid)
        self.assertFalse(result['full_boot_verified'])
        self.assertEqual(result['owner']['signals_sent'],[])

    def test_original_failure_retained(self):
        receipt,result=self.collect('COLD_BOOTSTRAP_FAILED stage=loop-attach rc=1\n')
        self.assertEqual(len(receipt['observed_failures']),1)
        self.assertFalse(result['full_boot_verified'])


    def im_trace(self):
        return ('Linux version synthetic-original-kernel\n'
            'COLD_KERNEL_CMDLINE_BEGIN\nroot=/dev/ram0\nCOLD_KERNEL_CMDLINE_END\n'+self.base()+
            self.mounted()+'COLD_OLD_INITRD_PATH_ABSENT=0\n'
            'COLD_RAM0_RELEASE original_rc=0 zero_prefix=1 bytes=512\n'
            'COLD_NATIVE_BOOTIN pid=42 sha256='+m['BOOTIN_SHA256']+'\n'+IM_EXPECTED+
            'COLD_PROCESS pid=31 exe=/usr/bin/im.elf\nSHA256(/proc/31/exe)= '+IM_SHA+'\n'
            'COLD_NATIVE_IM pid=31 exe=/usr/bin/im.elf sha256='+IM_SHA+'\n'
            'COLD_EXECUTABLE=/usr/bin/im.elf\n'
            'COLD_AP_MAP pid=31 sha256='+m['APPFW_SHA256']+'\n'
            'OBS OBSERVER_READY pid=31 base=0x7f12340000 mode=original\n'
            'OBS CREATE_SCREEN_ARGS call=4 id=0 count=565 orientation=0\n'
            'OBS OSD_HEADLESS_PERSISTED seq=8 pixel_source_seq=7 id=0x402 phys=0x430000000 '
            'geometry=640x480 bytes=614400 fnv1a64=0123456789abcdef mode=AP-RGBA4444-experimental '
            'path=/dev/qemu-simulation/headless-osd-frame.bin\n')

    def test_im_fixed_identity_and_same_pid_original_ap(self):
        for old,new in [('', ''), ('SHA256(', 'SHA2-256('),
                        ('exe=/usr/bin/im.elf','exe=/bin/im.elf')]:
            with self.subTest(alias=new):
                receipt,result=self.collect(self.im_trace().replace(old,new) if old else self.im_trace())
                self.assertTrue(result['stage_verified']['im'])
                self.assertTrue(result['ap_verified'])
                self.assertTrue(result['cold_guest_chain_verified'])
                self.assertFalse(result['full_boot_verified'])
                self.assertEqual(receipt['im_identity_status'],'passed')
                self.assertTrue(receipt['im_path_observed'])
                evidence=next(row['evidence'] for row in receipt['stages'] if row['stage']=='im')
                self.assertEqual(evidence['actual_pid'],31)
                self.assertEqual(evidence['expected_version'],'ILCE-7CM2-2.01')
                self.assertEqual(evidence['expected_sha256'],IM_SHA)
                self.assertEqual(evidence['actual_exe_sha256'],IM_SHA)

    def test_im_missing_wrong_path_only_and_duplicate_identity_rejected(self):
        good=self.im_trace()
        native='COLD_NATIVE_IM pid=31 exe=/usr/bin/im.elf sha256='+IM_SHA+'\n'
        actual=good[good.index('COLD_PROCESS '):good.index('COLD_AP_MAP ')]
        mapped='COLD_AP_MAP pid=31 sha256='+m['APPFW_SHA256']+'\n'
        variants={
            'missing-expected': (IM_EXPECTED,''),
            'wrong-expected': (IM_EXPECTED,IM_EXPECTED.replace(IM_SHA,'a'*64)),
            'wrong-version': ('ILCE-7CM2-2.01','ILCE-7CM2-9.99'),
            'missing-native': (native,''),
            'missing-process': ('COLD_PROCESS pid=31 exe=/usr/bin/im.elf\n',''),
            'wrong-process-pid': ('COLD_PROCESS pid=31','COLD_PROCESS pid=32'),
            'wrong-hash-pid': ('/proc/31/exe','/proc/32/exe'),
            'wrong-native-pid': ('COLD_NATIVE_IM pid=31','COLD_NATIVE_IM pid=32'),
            'wrong-actual-hash': ('SHA256(/proc/31/exe)= '+IM_SHA,'SHA256(/proc/31/exe)= '+'b'*64),
            'wrong-native-hash': (native,native.replace(IM_SHA,'b'*64)),
            'path-hash-only': ('/proc/31/exe','/usr/bin/im.elf'),
            'wrong-executable': ('exe=/usr/bin/im.elf','exe=/usr/bin/bootin.elf'),
            'wrong-map-pid': ('COLD_AP_MAP pid=31','COLD_AP_MAP pid=32'),
            'wrong-map-hash': (mapped,mapped.replace(m['APPFW_SHA256'],'c'*64)),
            'wrong-observer-pid': ('OBSERVER_READY pid=31','OBSERVER_READY pid=32'),
            'duplicate-expected': (IM_EXPECTED,IM_EXPECTED*2),
            'duplicate-native': (native,native*2),
            'duplicate-actual': (actual,actual*2),
            'duplicate-map': (mapped,mapped*2),
            'conflicting-map': (mapped,mapped+mapped.replace(m['APPFW_SHA256'],'c'*64)),
        }
        texts=[]
        for label,(old,new) in variants.items():
            self.assertIn(old,good,label)
            texts.append((label,good.replace(old,new)))
        texts.extend((('path-only',good.replace(IM_EXPECTED,'').replace(actual,'COLD_EXECUTABLE=/usr/bin/im.elf\n')),
                      ('return-zero','COLD_EXECUTABLE=/usr/bin/im.elf\nIM_RETURN=0\n')))
        for label,text in texts:
            with self.subTest(case=label):
                receipt,result=self.collect(text)
                self.assertFalse(result['stage_verified']['im'])
                self.assertFalse(result['cold_guest_chain_verified'])
                self.assertFalse(result['full_boot_verified'])
                self.assertEqual(receipt['im_identity_status'],'unknown')
                self.assertTrue(receipt['im_path_observed'])

    def test_im_old_receipt_stage_cannot_replace_actual_identity(self):
        receipt,result=self.collect(self.im_trace())
        self.assertTrue(result['stage_verified']['im'])
        self.console.write_text('COLD_EXECUTABLE=/usr/bin/im.elf\n')
        result=m['collect'](self.console,receipt)
        self.assertFalse(result['stage_verified']['im'])
        self.assertFalse(result['cold_guest_chain_verified'])
        self.assertFalse(result['full_boot_verified'])
        self.assertFalse(any(row['stage']=='im' for row in receipt['stages']))

    def test_im_requires_every_old_cold_and_frame_gate(self):
        good=self.im_trace()
        variants={
            'kernel': ('Linux version synthetic-original-kernel\n',''),
            'kernelargs': ('COLD_KERNEL_CMDLINE_BEGIN\nroot=/dev/ram0\nCOLD_KERNEL_CMDLINE_END\n',''),
            'ram_init': ('COLD_BEFORE_ORIGINAL_INIT','REMOVED'),
            'setup-rootfs': ('+ . /sbin/initrc/setup_rootfs','REMOVED'),
            'pivot_root': ('+ /sbin/pivot_root','REMOVED'),
            'chroot': ('+ exec busybox chroot','REMOVED'),
            'init2': ('COLD_INIT2_PROCESS','REMOVED'),
            'wrong-root': ('ext2 /dev/nflasha7','ext2 /dev/ram0'),
            'writable-root': ('/ ro - ext2','/ rw - ext2'),
            'old_root_unmounted': ('COLD_OLD_INITRD_PATH_ABSENT=0','COLD_OLD_INITRD_PATH_ABSENT=1'),
            'old-root-still-mounted': ('COLD_OLD_INITRD_PATH_ABSENT=0\n',
                'COLD_OLD_INITRD_PATH_ABSENT=0\n300 1 7:0 / /initrd rw - ext2 /dev/ram0 rw\n'),
            'ram0_release': ('original_rc=0','original_rc=1'),
            'ram0-nonzero': ('zero_prefix=1','zero_prefix=0'),
            'bootin': (m['BOOTIN_SHA256'],'d'*64),
            'ap': ('OBSERVER_READY','REMOVED'),
            'wrong-screen': (' id=0 count=565 ',' id=12 count=565 '),
            'missing-frame': ('OSD_HEADLESS_PERSISTED','REMOVED'),
            'wrong-frame': ('geometry=640x480 bytes=614400','geometry=320x240 bytes=153600'),
            'zero-frame-source': ('pixel_source_seq=7','pixel_source_seq=0'),
            'future-frame-source': ('pixel_source_seq=7','pixel_source_seq=9'),
        }
        variants.update(('missing-mount-'+target,(' '+target+' ',' /other '))
            for target in ('/setting','/system','/cp','/log','/cert','/lens','/tmp','/usr','/etc','/var'))
        variants['shared-tmp-device']=(self.mounted(),self.mounted(False))
        for label,(old,new) in variants.items():
            with self.subTest(gate=label):
                self.assertIn(old,good)
                _,result=self.collect(good.replace(old,new))
                self.assertFalse(result['stage_verified']['im'])
                self.assertFalse(result['cold_guest_chain_verified'])
                self.assertFalse(result['full_boot_verified'])

    def test_im_builder_fixed_pin_rejects_changed_missing_or_wrong_size(self):
        cold=runpy.run_path(str(Path(__file__).with_name('cold-init-chain.py')))
        self.assertEqual(cold['expected_im'](),dict(schema=1,version='ILCE-7CM2-2.01',bytes=40920,sha256=IM_SHA))
        cold['verify_im_identity'](dict(bytes=40920,sha256=IM_SHA))
        for row in ({},dict(bytes=40920),dict(sha256=IM_SHA),
                    dict(bytes=40920,sha256='a'*64),dict(bytes=40919,sha256=IM_SHA),dict(bytes=40921,sha256=IM_SHA)):
            with self.subTest(identity=row),self.assertRaises(ValueError):
                cold['verify_im_identity'](row)
        declared=cold['expected_im']()
        declared['sha256']='a'*64
        with self.assertRaises(ValueError):cold['verify_im_identity'](declared)

    def test_im_generated_producers_preserve_init2_and_bounded_final_proc_sample(self):
        cold=runpy.run_path(str(Path(__file__).with_name('cold-init-chain.py')))
        persistent=runpy.run_path(str(Path(__file__).with_name('persistent-boot.py')))
        standin=self.root/'synthetic-busybox'
        standin.write_text('#!/bin/sh\n[ "$1" = cat ] || exit 97\necho "/bin/busybox sh /sbin/init2"\n')
        standin.chmod(0o700)
        for producer in (cold['INSMOD'],persistent['INSMOD']):
            lines=producer.splitlines()
            start=next(i for i,line in enumerate(lines) if 'echo "COLD_INIT2_PROCESS ' in line)
            end=next(i for i,line in enumerate(lines) if 'echo "COLD_EXPECTED_IM ' in line)
            script='\n'.join(lines[start:end+1]).replace('/bin/busybox',str(standin))+'\n'
            produced=subprocess.run(['/bin/sh'],input=script,text=True,capture_output=True,check=True).stdout
            trace=self.im_trace().replace(IM_EXPECTED,'').replace(
                'COLD_INIT2_PROCESS parent=12\n/bin/busybox\x00sh\x00/sbin/init2\x00\n',produced)
            _,result=self.collect(trace)
            self.assertTrue(result['stage_verified']['init2'])
            self.assertTrue(result['stage_verified']['im'])
            self.assertTrue(result['cold_guest_chain_verified'])
            self.assertFalse(result['full_boot_verified'])
        tree=ast.parse(Path(m['__file__']).read_text())
        assignment=next(node for node in ast.walk(tree) if isinstance(node,ast.Assign) and
            any(isinstance(target,ast.Name) and target.id=='diagnostic' for target in node.targets))
        for final in (False,True):
            script=eval(compile(ast.Expression(assignment.value),'<diagnostic>','eval'),
                        dict(m,begin='BEGIN',end='END',final_due=final))
            self.assertIn('observe_im='+str(int(final)),script)
            self.assertIn('dgst -sha256 "$p/exe"',script)
            envelope=m['diagnostic_envelope'](script,'IM_TEST')
            self.assertLessEqual(max(map(len,envelope.splitlines())),512)
            checked=subprocess.run(['/bin/sh','-n'],input=envelope,text=True,capture_output=True)
            self.assertEqual(checked.returncode,0,checked.stderr)


class BoundColdProofTests(unittest.TestCase):
    """Synthetic host records only; the immutable decoder remains the transport gate."""
    @classmethod
    def setUpClass(cls):
        cls.retained=runpy.run_path(str(Path(__file__).with_name('retained-camera-test.py')))

    def setUp(self):
        BootExecutionTests.setUp(self)
        direct=BootExecutionTests().im_trace()
        first,last=direct.index('COLD_PROCESS '),direct.index('OBS OBSERVER_READY ')
        self.process=direct[first:last].encode('ascii')
        self.trace=(direct[:first]+direct[last:]).encode('ascii')
        self.token=b'a'*32
        self.identity=b' nonce='+self.token+b' file=/dev/qemu-simulation/retained-cold-'+self.token+b'.proof'
        status=(b'/usr/bin/im.elf\0Name:\tim.elf\nTgid:\t31\nPid:\t31\n'
                b'Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'
                b'7f12340000-7f12440000 r-xp 00000000 01:01 123 /usr/lib/appFw.so\n')
        self.proof=(b'RETAINED_COLD_FILE'+self.identity+b'\n'+self.process+status+
                    b'RETAINED_COLD_FILE_END'+self.identity+b'\n')
        self.noise=(b'COLD_NATIVE_IM pid=${p##*/}OBS TEST_NOISE lease=57\n exe=$e sha256='+
                    IM_SHA.encode('ascii')+b'\n')

    def transfer(self, proof=None, *, trace=None, noise=None):
        proof=self.proof if proof is None else proof
        trace=self.trace if trace is None else trace
        noise=self.noise if noise is None else noise
        binding=(self.identity+b' bytes='+str(len(proof)).encode('ascii')+b' sha256='+
                 hashlib.sha256(proof).hexdigest().encode('ascii')+b'\n')
        raw=trace+noise+b'RETAINED_COLD_META'+binding
        for offset in range(0,len(proof),192):
            raw+=(b'RETAINED_COLD_CHUNK nonce='+self.token+b' offset='+str(offset).encode('ascii')+
                  b' data='+base64.b64encode(proof[offset:offset+192])+b'\n')
        raw+=b'RETAINED_COLD_END'+binding
        return raw,raw+b'\n'+proof

    def collect(self, raw):
        self.console.write_bytes(raw)
        receipt=m['new_receipt']('original-init-cold',bindings={'run':'synthetic-bound-proof','source_class':'private-device-dump'})
        result=m['collect'](self.console,receipt)
        self.assertEqual(self.console.read_bytes(),raw)
        return receipt,result

    def rejected(self, raw):
        receipt,result=self.collect(raw)
        self.assertFalse(result['stage_verified']['im'])
        self.assertFalse(result['cold_guest_chain_verified'])
        self.assertFalse(result['full_boot_verified'])
        self.assertEqual(receipt['im_identity_status'],'unknown')

    def test_bound_proof_ignores_raw_echo_without_rewriting_it(self):
        native=b'COLD_NATIVE_IM pid=31 exe=/usr/bin/im.elf sha256='+IM_SHA.encode('ascii')
        for noise in (b'',self.noise,self.noise+native+b'\n'):
            with self.subTest(noise=noise):
                raw,joined=self.transfer(noise=noise)
                self.assertEqual(self.retained['decode_cold_proof'](raw,self.token.decode()),self.proof)
                receipt,result=self.collect(joined)
                self.assertTrue(result['stage_verified']['im'])
                self.assertTrue(result['ap_verified'])
                self.assertTrue(result['cold_guest_chain_verified'])
                self.assertFalse(result['full_boot_verified'])
                self.assertEqual(receipt['im_identity_status'],'passed')
                evidence=next(row['evidence'] for row in receipt['stages'] if row['stage']=='im')
                self.assertEqual(evidence['actual_pid'],31)
                self.assertEqual(evidence['actual_exe_sha256'],IM_SHA)
                self.assertEqual(evidence['artifacts'][0]['sha256'],hashlib.sha256(joined).hexdigest())

    def test_bound_proof_bad_or_duplicate_actual_identity_rejected(self):
        ap=b'COLD_AP_MAP pid=31 sha256='+m['APPFW_SHA256'].encode('ascii')+b'\n'
        native=b'COLD_NATIVE_IM pid=31 exe=/usr/bin/im.elf sha256='+IM_SHA.encode('ascii')+b'\n'
        proc_sha=b'SHA256(/proc/31/exe)= '+IM_SHA.encode('ascii')+b'\n'
        mutations={
            'wrong-proc-sha':self.proof.replace(proc_sha,proc_sha.replace(IM_SHA.encode(),b'b'*64)),
            'wrong-native-sha':self.proof.replace(native,native.replace(IM_SHA.encode(),b'b'*64)),
            'wrong-actual-elf':self.proof.replace(b'exe=/usr/bin/im.elf',b'exe=/usr/bin/bootin.elf'),
            'wrong-proc-pid':self.proof.replace(b'/proc/31/exe',b'/proc/32/exe'),
            'wrong-native-pid':self.proof.replace(b'COLD_NATIVE_IM pid=31',b'COLD_NATIVE_IM pid=32'),
            'foreign-ap-map-pid':self.proof.replace(b'COLD_AP_MAP pid=31',b'COLD_AP_MAP pid=32'),
            'wrong-map-sha':self.proof.replace(ap,ap.replace(m['APPFW_SHA256'].encode(),b'c'*64)),
            'duplicate-actual':self.proof.replace(self.process,self.process*2),
            'duplicate-proc-hash':self.proof.replace(proc_sha,proc_sha*2),
            'duplicate-native':self.proof.replace(native,native*2),
            'duplicate-map':self.proof.replace(ap,ap*2),
            'conflicting-map':self.proof.replace(ap,ap+ap.replace(m['APPFW_SHA256'].encode(),b'c'*64)),
            'extra-malformed-native-in-proof':self.proof.replace(native,native+self.noise),
            'broken-adjacency':self.proof.replace(proc_sha,proc_sha+b'unrelated\n'),
            'path-only':self.proof.replace(self.process,b'COLD_EXECUTABLE=/usr/bin/im.elf\n'),
        }
        for name,proof in mutations.items():
            with self.subTest(case=name):
                self.rejected(self.transfer(proof)[1])
        for name,proof in {'missing-process':self.proof.replace(self.process,b''),
                           'missing-map':self.proof.replace(ap,b'')}.items():
            with self.subTest(case='raw-cannot-supply-'+name):
                self.rejected(self.transfer(proof,trace=self.trace+self.process)[1])

    def test_bound_proof_observer_and_expected_identity_stay_pinned(self):
        self.assertEqual(m['IM_SHA256'],IM_SHA)
        self.assertEqual(m['IM_VERSION'],'ILCE-7CM2-2.01')
        mutations={
            'wrong-observer-pid':self.trace.replace(b'OBSERVER_READY pid=31',b'OBSERVER_READY pid=32'),
            'missing-observer':self.trace.replace(b'OBSERVER_READY',b'NO_OBSERVER'),
            'wrong-expected-sha':self.trace.replace(IM_SHA.encode(),b'b'*64),
            'wrong-expected-version':self.trace.replace(b'ILCE-7CM2-2.01',b'ILCE-7CM2-9.99'),
            'missing-expected':self.trace.replace(IM_EXPECTED.encode(),b''),
            'duplicate-expected':self.trace.replace(IM_EXPECTED.encode(),IM_EXPECTED.encode()*2),
            'fake-flag-only':b'COLD_IM_VERIFIED=1\nSOURCE_READY=1\n',
        }
        for name,trace in mutations.items():
            with self.subTest(case=name):
                self.rejected(self.transfer(trace=trace)[1])
        with self.subTest(case='guest-cannot-self-certify-new-im-hash'):
            self.rejected(self.transfer(self.proof.replace(IM_SHA.encode(),b'b'*64),
                trace=self.trace.replace(IM_SHA.encode(),b'b'*64))[1])

    def test_invalid_binding_rejected_without_direct_log_fallback(self):
        raw,joined=self.transfer(noise=b'')
        meta=next(line for line in raw.splitlines(keepends=True) if line.startswith(b'RETAINED_COLD_META '))
        end=next(line for line in raw.splitlines(keepends=True) if line.startswith(b'RETAINED_COLD_END '))
        mutations={
            'truncated-proof':joined[:-1],
            'extra-suffix':joined+b'extra\n',
            'missing-decoded-proof':raw+self.process,
            'no-transfer-binding':self.trace+b'\n'+self.proof,
            'duplicate-decoded-proof':joined+self.proof,
            'wrong-envelope-sha':joined.replace(hashlib.sha256(self.proof).hexdigest().encode(),b'0'*64),
            'duplicate-end-record':raw+end+b'\n'+self.proof,
            'duplicate-meta-record':meta+joined,
            'missing-meta':joined.replace(meta,b''),
            'missing-end':joined.replace(end,b''),
            'meta-end-reversed':joined.replace(meta,end).replace(end+b'\n',meta+b'\n'),
            'transport-marker-only':BootExecutionTests().im_trace().encode()+b'RETAINED_COLD_CHUNK \n',
        }
        fields={
            'nonce':(b' nonce='+self.token+b' ',b' nonce='+b'b'*32+b' '),
            'path':(b'.proof ',b'.other '),
            'size':(b' bytes='+str(len(self.proof)).encode()+b' ',b' bytes='+str(len(self.proof)+1).encode()+b' '),
            'sha':(b' sha256='+hashlib.sha256(self.proof).hexdigest().encode(),b' sha256='+b'0'*64),
        }
        for label,line in (('meta',meta),('end',end)):
            for field,(old,new) in fields.items():
                self.assertIn(old,line)
                mutations[label+'-wrong-'+field]=joined.replace(line,line.replace(old,new))
        for name,changed in mutations.items():
            with self.subTest(case=name):
                self.rejected(changed)
        for name,proof in {
            'file-nonce':self.proof.replace(b'RETAINED_COLD_FILE nonce='+self.token,b'RETAINED_COLD_FILE nonce='+b'b'*32),
            'file-path':self.proof.replace(b'.proof\n',b'.other\n'),
            'footer-nonce':self.proof.replace(b'RETAINED_COLD_FILE_END nonce='+self.token,b'RETAINED_COLD_FILE_END nonce='+b'b'*32),
            'duplicate-footer':self.proof+b'RETAINED_COLD_FILE_END'+self.identity+b'\n',
            'non-utf8-body':self.proof.replace(b'Name:',b'\xffName:'),
        }.items():
            with self.subTest(case=name):
                self.rejected(self.transfer(proof,noise=b'')[1])

    def test_immutable_retained_root_parser_rejects_partial_or_nonzero_ids(self):
        state=('RETAINED_STATE_BEGIN=test\nUid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'
            'RETAINED_APP_PID=31\nRETAINED_VIEWER_PID=32\n'
            '1: FLOCK ADVISORY WRITE 31 00:01:123 0 EOF\n2: FLOCK ADVISORY WRITE 32 00:01:124 0 EOF\n'
            'RETAINED_CANARY='+self.token.decode()+'\nRETAINED_BOOT_ID=12345678-1234-1234-1234-123456789abc\n'
            'RETAINED_UPTIME=40.00 20.00\nSHA256(/dev/qemu-simulation/headless-osd.claim)= '+IM_SHA+'\n'
            'RETAINED_FRAME_HEADER=AA==\nRETAINED_VIEWER_STATUS_BEGIN\nfixture\n'
            'RETAINED_VIEWER_STATUS_END\nRETAINED_STATE_END=test\n')
        self.assertEqual(self.retained['parse_state'](state,'test')['ap_pids'],['31'])
        for field in ('Uid','Gid'):
            for replacement in ('0\t0\t0','0\t0\t0\t1'):
                with self.subTest(field=field,value=replacement),self.assertRaises(ValueError):
                    self.retained['parse_state'](state.replace(field+':\t0\t0\t0\t0',field+':\t'+replacement),'test')


if __name__=='__main__':unittest.main()
