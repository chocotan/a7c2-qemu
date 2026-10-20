"""Check the compiled gate's relocated branches without booting a guest."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent


class ObserverGateTests(unittest.TestCase):
    def test_rm_file_profile_validation(self):
        for mode,options,extra,error in (
                ('x',[],{},'MENU_RM_FILE must be 1 or unset'),
                ('1',[],{},'MENU_RM_FILE requires --initramfs --observe'),
                ('1',['--initramfs','--observe'],{'MENU_HONEST_ROUTING':'1'},'MENU_RM_FILE cannot share the experimental send-GOT hooks'),
                ('1',['--initramfs','--observe'],{'MENU_MEDIA_SELFTEST':'1'},'cannot run with MENU_MEDIA_SELFTEST')):
            with self.subTest(mode=mode,extra=extra):
                result=subprocess.run(['python3',str(BASE/'qemu-menu-probe.py'),*options],
                                      env=dict(os.environ,MENU_RM_FILE=mode,**extra),capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,2);self.assertIn(error,result.stderr)

    def test_dialog_trace_reads_bounded_frames_without_writing(self):
        source=(BASE/'menu-observe.c').read_text()
        helper=source[source.index('static unsigned long captured_dialog_presenter;'):source.index('static void *observe_create_screen(')]
        prefix='''#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static unsigned long appfw_base=0x10000000;
static unsigned int seen,unavailable,captured,values,known_index,card_error_rendered;
static long fake_syscall(long n,...){(void)n;return 123;}
#define syscall fake_syscall
static void record(const char *tag,const char *text){
  if(!strcmp(tag,"CREATE_SCREEN_DIALOG_FRAME ")){assert(strstr(text,"in_appFw=1"));seen++;}
  else if(!strcmp(tag,"RESOURCE_DIALOG_GETTER_CAPTURED ")){captured++;if(strstr(text,"index_known=1")){assert(strstr(text,"module_index=0x123"));known_index++;}}
  else if(!strcmp(tag,"RESOURCE_DIALOG_VALUE ")){assert(strstr(text,"source=original-view-string-param"));values++;}
  else {assert(!strcmp(tag,"CREATE_SCREEN_DIALOG_TRACE_UNAVAILABLE "));unavailable++;}
  errno=77;
}
'''
        suffix='''int main(void){
 _Alignas(16) unsigned long frames[6]={0};unsigned long before[6];
 frames[0]=(unsigned long)(frames+2);frames[1]=appfw_base+0x1234;
 frames[2]=(unsigned long)(frames+4);frames[3]=appfw_base+0x2222;frames[5]=appfw_base+0x3333;
 memcpy(before,frames,sizeof frames);errno=33;
 capture_dialog_frames((unsigned long)frames,3);
 assert(seen==3 && unavailable==0 && errno==33 && !memcmp(frames,before,sizeof frames));
 seen=0;frames[0]=(unsigned long)frames;capture_dialog_frames((unsigned long)frames,3);assert(seen==1);
 seen=0;frames[0]=(unsigned long)frames+0x40010;capture_dialog_frames((unsigned long)frames,3);assert(seen==1);
 capture_dialog_frames(1,3);capture_dialog_frames(0,3);assert(unavailable==2);
 unsigned char *p=calloc(1,0x2ad8),*copy=malloc(0x2ad8),*array=calloc(1,0x40),*param=calloc(1,0x38);assert(p && copy && array && param);
 unsigned long vt=appfw_base+0x59590b8,method=appfw_base+0x1234,table[1]={method},getter[3]={(unsigned long)table,0,0x123};
 _Alignas(16) unsigned long ctor[4]={0,0,(unsigned long)p,0};
 unsigned long ptr=(unsigned long)getter;memcpy(p,&vt,8);memcpy(p+0x2ac8,&ptr,8);
 unsigned int id=0x322,kind=2,resource=0x12345678;memcpy(p+0x30,&id,4);
 ptr=(unsigned long)array;memcpy(p+0x28,&ptr,8);memcpy(array+0x30,&kind,4);
 ptr=(unsigned long)param;memcpy(array+0x38,&ptr,8);memcpy(param+0x30,&resource,4);
 memcpy(copy,p,0x2ad8);int fd=open("/proc/self/mem",0);assert(fd>=0);
 capture_dialog_presenter(fd,(unsigned long)ctor,3);close(fd);assert(captured==1);
 errno=33;capture_dialog_resource();capture_dialog_resource();
 assert(values==1 && last_dialog_value==resource && errno==33 && !memcmp(p,copy,0x2ad8));
 resource=0x87654321;memcpy(param+0x30,&resource,4);capture_dialog_resource();
 assert(values==2 && last_dialog_value==resource);
 kind=1;memcpy(array+0x30,&kind,4);capture_dialog_resource();assert(values==2);
 assert(!card_error_rendered);kind=2;resource=0x0200a73b;
 memcpy(array+0x30,&kind,4);memcpy(param+0x30,&resource,4);capture_dialog_resource();
 assert(values==3 && card_error_rendered && !memcmp(p,copy,0x2ad8));
 appfw_base=(unsigned long)table-0x59128c0;vt=appfw_base+0x59590b8;memcpy(p,&vt,8);
 table[0]=appfw_base+0x1882dc8;fd=open("/proc/self/mem",0);assert(fd>=0);
 capture_dialog_presenter(fd,(unsigned long)ctor,3);close(fd);assert(known_index==1);
 free(p);free(copy);free(array);free(param);
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='dialog-frame-reader-') as temp:
            path=Path(temp);(path/'check.c').write_text(prefix+helper+suffix)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(path/'check.c'),'-o',str(path/'check')],check=True)
            subprocess.run([str(path/'check')],check=True,timeout=10)

    def test_digital_level_mode_and_bypass_validation(self):
        for mode,options,hooks,error in (
                ('1',[],{},'MENU_DIG_LEVEL must be virtual or unset'),
                ('virtual',[],{},'MENU_DIG_LEVEL requires --observe'),
                ('virtual',['--observe'],{'MENU_HONEST_ROUTING':'1'},'without experimental send-GOT hooks')):
            with self.subTest(mode=mode,options=options):
                env=dict(os.environ,MENU_DIG_LEVEL=mode,**hooks)
                result=subprocess.run(['python3',str(BASE/'qemu-menu-probe.py'),*options],
                                      env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,2)
                self.assertIn(error,result.stderr)

    def test_panel_reverse_mode_and_bypass_validation(self):
        for value,options,hook,error in (
                ('1',[],{},'MENU_PANEL_REVERSE must be virtual or unset'),
                ('virtual',[],{},'MENU_PANEL_REVERSE requires --observe'),
                ('virtual',['--observe'],{'MENU_ASYNC_SEND':'1'},'without experimental send-GOT hooks')):
            with self.subTest(value=value,options=options):
                env=dict(os.environ,MENU_PANEL_REVERSE=value,**hook)
                result=subprocess.run(['python3',str(BASE/'qemu-menu-probe.py'),*options],env=env,
                                      capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,2);self.assertIn(error,result.stderr)

    @classmethod
    def setUpClass(cls):
        binary = BASE / 'menu-observe.so'
        symbols = subprocess.check_output(
            ['aarch64-linux-gnu-nm', '-a', str(binary)], text=True)
        cls.slots = {
            int(address, 16): name
            for address, name in re.findall(
                r'^([0-9a-f]+) \w (run_i_gate_(?:continue|long))$', symbols, re.M)
        }
        disasm = subprocess.check_output(
            ['aarch64-linux-gnu-objdump', '-d',
             '--disassemble=run_i_gate_probe_trampoline', str(binary)], text=True)
        cls.code = {
            int(pc, 16): int(word, 16)
            for pc, word in re.findall(r'^\s*([0-9a-f]+):\s+([0-9a-f]{8})\s', disasm, re.M)
        }
        cls.start = next(pc for pc, word in cls.code.items() if word == 0x3947d260)

    def test_compiled_branches_preserve_original_destination_and_w0(self):
        # Interpret only the replay block, including ADRP/LDR of the destination slots.
        for a, b in ((0, 0), (0, 1), (1, 0), (1, 1), (255, 255)):
            with self.subTest(byte500=a, byte501=b):
                pc, w0, page, slot = self.start, None, None, None
                for _ in range(10):
                    word = self.code[pc]
                    if word == 0x3947d260:
                        w0 = a
                    elif word == 0x3947d660:
                        w0 = b
                    elif word & 0xff00001f == 0x35000000:  # CBNZ w0
                        imm = (word >> 5) & 0x7ffff
                        if imm & 0x40000:
                            imm -= 0x80000
                        if w0:
                            pc += imm * 4
                            continue
                    elif word & 0x9f00001f == 0x90000010:  # ADRP x16
                        imm = (((word >> 5) & 0x7ffff) << 2) | ((word >> 29) & 3)
                        if imm & 0x100000:
                            imm -= 0x200000
                        page = (pc & ~0xfff) + imm * 4096
                    elif word & 0xffc003ff == 0xf9400210:  # LDR x16,[x16,#imm]
                        slot = page + ((word >> 10) & 0xfff) * 8
                    elif word == 0xd61f0200:  # BR x16
                        break
                    else:
                        self.fail(f'unexpected replay instruction {word:08x} at {pc:x}')
                    pc += 4
                else:
                    self.fail('replay did not reach a destination')
                self.assertEqual(self.slots[slot],
                                 'run_i_gate_long' if not a and b else 'run_i_gate_continue')
                self.assertEqual(w0, a if a else b)

    def test_invalid_input_mode_rejected_before_vm_launch(self):
        for mode in ('p', 'pressx', 'press;echo invalid'):
            with self.subTest(mode=mode):
                env = dict(os.environ, MENU_INJECT_KEY=mode)
                result = subprocess.run(
                    ['python3', str(BASE / 'qemu-menu-probe.py')],
                    env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn('MENU_INJECT_KEY must be press, pressrelease, confirm-pressrelease, language-pressrelease or auto-firstboot', result.stderr)

    def test_metadata_id_cookie_and_limit(self):
        source = (BASE / 'menu-observe.c').read_text()
        start = source.index('void capture_seq_finish(')
        end = source.index('static unsigned int boot_seq_seen', start)
        harness = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
static unsigned int seq_finish_seen, captured, limits;
static unsigned long appfw_base = 0x100000;
static char last[512];
static void record(const char *prefix, const char *text) {
    if (!strcmp(prefix, "SEQ_FINISH ")) { ++captured; snprintf(last,sizeof last,"%s",text); }
    if (!strcmp(prefix, "SEQ_FINISH_LIMIT ")) ++limits;
}
''' + source[start:end] + r'''
int main(void) {
    unsigned long node[4]={0,0,0xa5a5a5a5000004bdUL,0x12345678};
    seq_finish_seen=40;
    capture_seq_finish(0x200000,(unsigned long)node,appfw_base+0x44);
    assert(captured==1 && limits==1);
    assert(strstr(last,"id=0x4bd cookie=0x12345678 caller=appFw+0x44"));
    node[2]=0xa5a5a5a500000132UL;
    capture_seq_finish(0x200000,(unsigned long)node,appfw_base+0x48);
    assert(captured==1);
    node[2]=0xa5a5a5a50000002aUL;
    capture_seq_finish(0x200000,(unsigned long)node,appfw_base+0x4c);
    assert(captured==2 && strstr(last,"id=0x2a "));
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='a7c2-metadata-test-') as temp:
            cfile, binary = Path(temp) / 'test.c', Path(temp) / 'test'
            cfile.write_text(harness)
            subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)],
                           check=True, capture_output=True, text=True, timeout=15)
            subprocess.run([str(binary)], check=True, timeout=10)

    def test_retired_null_constructor_option_rejected(self):
        env = dict(os.environ, MENU_SEQ4BD_CREATE='1')
        result = subprocess.run(['python3', str(BASE / 'qemu-menu-probe.py')],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('NULL-payload constructor call is invalid', result.stderr)

    def test_invalid_vdf_mode_rejected_before_vm_launch(self):
        env = dict(os.environ, MENU_INJECT_KEY='', MENU_VDF_CONFIG='2')
        result = subprocess.run(
            ['python3', str(BASE / 'qemu-menu-probe.py')],
            env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('MENU_VDF_CONFIG must be 1 or unset', result.stderr)

    def test_vdf_rejects_bypassing_send_hooks(self):
        for hook in ('MENU_HONEST_ROUTING', 'MENU_ASYNC_SEND', 'MENU_PIPELINE_VIRT'):
            with self.subTest(hook=hook):
                env = dict(os.environ, MENU_INJECT_KEY='', MENU_VDF_CONFIG='1', **{hook: '1'})
                result = subprocess.run(
                    ['python3', str(BASE / 'qemu-menu-probe.py')], env=env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn('cannot share the experimental send-GOT hooks', result.stderr)

    def test_hdmi_and_pin_mode_validation(self):
        for settings, error in (
                ({'MENU_DMM_UNIT_CONFIG': '2'}, 'MENU_DMM_UNIT_CONFIG must be 1 or unset'),
                ({'MENU_DMM_UNIT_CONFIG': '1', 'MENU_ASYNC_SEND': '1'}, 'cannot share the experimental send-GOT hooks'),
                ({'MENU_DMM_UNIT_CONFIG': '1'}, 'MENU_DMM_UNIT_CONFIG requires --initramfs --observe'),
                ({'MENU_AUDIO_BOOT_CONFIG': '2'}, 'MENU_AUDIO_BOOT_CONFIG must be 1 or unset'),
                ({'MENU_AUDIO_BOOT_CONFIG': '1', 'MENU_ASYNC_SEND': '1'},
                 'MENU_AUDIO_BOOT_CONFIG cannot share the experimental send-GOT hooks'),
                ({'MENU_AUDIO_BOOT_CONFIG': '1'},
                 'MENU_AUDIO_BOOT_CONFIG requires --initramfs --sony-timers --observe'),
                ({'MENU_HDMI_BOOT_CONFIG': '2'}, 'MENU_HDMI_BOOT_CONFIG must be 1 or unset'),
                ({'MENU_HDMI_BOOT_CONFIG': '1', 'MENU_ASYNC_SEND': '1'},
                 'MENU_HDMI_BOOT_CONFIG cannot share the experimental send-GOT hooks'),
                ({'MENU_PIN_REGISTRY': '2'}, 'MENU_PIN_REGISTRY must be 1 or unset'),
                ({'MENU_PIN_REGISTRY': '1', 'MENU_HONEST_ROUTING': '1'},
                 'MENU_PIN_REGISTRY cannot share the experimental send-GOT hooks')):
            with self.subTest(settings=settings):
                env = dict(os.environ, MENU_INJECT_KEY='', MENU_VDF_CONFIG='', **settings)
                result = subprocess.run(
                    ['python3', str(BASE / 'qemu-menu-probe.py')], env=env,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn(error, result.stderr)

    def test_pin_connection_requires_backing_and_excludes_standalone_probe(self):
        cases = [
            ({'MENU_PIN_CONNECTION': 'control'}, 'MENU_PIN_CONNECTION must be cold or unset'),
            ({'MENU_PIN_CONNECTION': 'cold'}, 'requires MENU_PIN_CONTROL_MEMORY and MENU_PIN_REGISTRY'),
            ({'MENU_PIN_CONNECTION': 'cold', 'MENU_PIN_CONTROL_MEMORY': '1',
              'MENU_PIN_REGISTRY': '1', 'MENU_PIN_BUFFER_SELFTEST': '1'}, 'must use separate VMs'),
        ]
        for settings, error in cases:
            with self.subTest(settings=settings):
                env = dict(os.environ)
                env.update(MENU_INJECT_KEY='', MENU_PIN_REGISTRY='', MENU_PIN_CONTROL_MEMORY='',
                           MENU_PIN_BUFFER_SELFTEST='', MENU_SEQ4BD_CREATE='')
                env.update(settings)
                result = subprocess.run(
                    ['python3', str(BASE / 'qemu-menu-probe.py'), '--initramfs', '--sony-timers'],
                    env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertIn(error, result.stderr)


if __name__ == '__main__':
    unittest.main()
