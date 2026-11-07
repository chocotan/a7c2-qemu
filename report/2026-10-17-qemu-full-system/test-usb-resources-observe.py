#!/usr/bin/env python3
"""Public host checks for opt-in observations; no QEMU, USB, or sockets."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent

C = r'''
#define USB_OBSERVE_HOST_TEST 1
#define USB_RESOURCE_OBSERVE 1
#include "usb-start-observe.c"
#include <assert.h>
static uintptr_t args[5];
static uint32_t fake4(uintptr_t a,uintptr_t b,uintptr_t c,uintptr_t d) {
    assert(errno==31);args[0]=a;args[1]=b;args[2]=c;args[3]=d;errno=43;return 0x80000009;
}
static uint32_t fake5(uintptr_t a,uint32_t b,int32_t c,int32_t d,int32_t e) {
    assert(errno==31);args[0]=a;args[1]=b;args[2]=(uint32_t)c;args[3]=(uint32_t)d;args[4]=(uint32_t)e;errno=44;return 0x80000007;
}
int main(int argc,char **argv) {
    assert(argc==2);logfd=open(argv[1],O_CREAT|O_TRUNC|O_RDWR,0600);assert(logfd>=0);
    memfd=open("/proc/self/mem",O_RDONLY);assert(memfd>=0);
    static unsigned char object[0x30a70];control_base=(uintptr_t)object;
    real_storage_create=fake4;real_sen_create=fake4;real_sync_startstop=fake5;
    errno=31;assert(u_storage_create(0xffff000012345678UL,2,3,0xfedcba9876543210UL)==0x80000009);
    assert(errno==43 && args[0]==0xffff000012345678UL && args[3]==0xfedcba9876543210UL);
    errno=31;assert(u_sen_create(1,2,3,4)==0x80000009 && errno==43 && args[3]==4);
    errno=31;assert(u_sync_startstop(1,2,-3,4,-5)==0x80000007);
    assert(errno==44 && (int32_t)args[2]==-3 && (int32_t)args[4]==-5);
    records=10000;resource_records=0;
    errno=31;resource_ioctl(logfd,0x4070e000,0x1234,0,0,31);assert(errno==31 && resource_records==2);
    errno=31;resource_ioctl(-1,0x4070e000,0,1,-1,9);assert(errno==31);
    for(unsigned i=0;i<1000;i++)resource_emit("NOISE","n=%u",i);
    off_t n=lseek(logfd,0,SEEK_END);char text[40000]={0};assert(n>0 && n<(off_t)sizeof text);
    assert(pread(logfd,text,n,0)==n);
    unsigned count=0;for(char *p=text;(p=strstr(p,"USB_START RESOURCE_"));p++)count++;
    assert(count==71 && strstr(text,"USB_START RESOURCE_CAP records=64\n"));
    char *enter=strstr(text,"RESOURCE_IOCTL_ENTER");assert(enter);char *end=strchr(enter,'\n');assert(end);*end=0;
    assert(!strstr(enter," rc=")&&!strstr(enter," errno="));*end='\n';
    assert(strstr(text,"path=unknown")&&strstr(text,"rc=-1 errno=9"));
    assert(records==10000 && resource_records==64);
    control_base=1;errno=31;assert(u_sync_startstop(1,2,-3,4,-5)==0x80000007&&errno==44);
    assert(resource_records==64);close(memfd);close(logfd);return 0;
}
'''


class ResourceObservations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.start = runpy.run_path(str(HERE / 'usb-start-observe.py'))
        cls.device = runpy.run_path(str(HERE / 'usb-device-profile.py'))

    def test_typed_private_selection(self):
        enabled = self.start['resource_observer_enabled']
        for value in (None, {}, {'diagnostic_checkpoints': False}):
            self.assertFalse(enabled(value))
        self.assertTrue(enabled({'diagnostic_checkpoints': True}))
        for value in (0, 1, None, 'true', [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                enabled({'diagnostic_checkpoints': value})

    def test_prepared_generation_selection_and_default(self):
        text = '''#!/bin/bash
display_args=()
timer_environment=()
python3 - <<'PY'
runpy.run_path(sys.argv[7])["add_nodes"](fdt,buffer,sys.argv[6],sys.argv[8])
PY
bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"
'''
        adapt = self.device['adapt_script']
        default = adapt(text)
        self.assertEqual(adapt(default), default)
        self.assertNotIn('generation-observe', default)
        selected = adapt(text, observe_generation=True)
        self.assertEqual(selected.count('-global sony-dwc3-gadget.generation-observe=on'), 1)
        self.assertEqual(adapt(selected, observe_generation=True), selected)
        for value in (0, 1, None, 'true'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapt(text, observe_generation=value)
        with self.assertRaises(ValueError):
            adapt(selected)
        with self.assertRaises(ValueError):
            adapt(default, observe_generation=True)
        for script in (default, selected):
            subprocess.run(['bash', '-n'], input=script, text=True, check=True, capture_output=True)

    def test_default_preprocessor_has_no_new_hooks(self):
        command = ['cc', '-E', '-P', '-DUSB_OBSERVE_HOST_TEST=1', '-I', str(HERE),
                   str(HERE / 'usb-start-observe.c')]
        default = subprocess.run(command, check=True, capture_output=True, text=True).stdout
        self.assertNotIn('USB_START RESOURCE_', default)
        self.assertNotIn('u_storage_create', default)
        self.assertNotIn('u_sync_startstop', default)
        selected = subprocess.run([*command[:-1], '-DUSB_RESOURCE_OBSERVE=1', command[-1]],
                                  check=True, capture_output=True, text=True).stdout
        self.assertIn('USB_START RESOURCE_', selected)
        for name in ('osal_dynamic_id', 'osal_rcv_msg_tmo', 'osal_free_msg'):
            self.assertNotRegex(selected, r'got\(base,0x(?:30478|302c0|30800),"' + name + '"')
        bad = subprocess.run([*command[:-1], '-DUSB_RESOURCE_OBSERVE=0', command[-1]],
                             capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)

    def test_release_contract_rejects_changed_source_and_scope(self):
        module = HERE / 'usb-generation-build.py'
        original = json.loads((HERE / 'usb-generation-source-contract.json').read_text())
        with tempfile.TemporaryDirectory(prefix='usb-release-') as directory:
            root = Path(directory)
            names = ('usb-generation-build.py', 'usb-generation-source-contract.json', 'persistent-flash/build.py',
                     *original['build_public_sha256'], *original['persistent_model_sha256'])
            for name in names:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(HERE / name, target)
            api = runpy.run_path(str(root / module.name))
            self.assertEqual(api['source_contract'](), original)
            source = root / 'usb-gadget/sony-dwc3.c'
            before = source.read_bytes()
            source.write_bytes(before + b'\n')
            with self.assertRaises(ValueError):
                api['source_contract']()
            source.write_bytes(before)
            for broken in (dict(original, build_public_sha256={**original['build_public_sha256'], '../outside': '0' * 64}),
                           dict(original, baseline_identity={**original['baseline_identity'], 'source_tree': '0' * 64})):
                (root / 'usb-generation-source-contract.json').write_text(json.dumps(broken))
                with self.assertRaises(ValueError):
                    api['source_contract']()

    def test_original_calls_errno_and_independent_budget(self):
        with tempfile.TemporaryDirectory(prefix='usb-resource-') as directory:
            root = Path(directory)
            source = root / 'check.c'
            source.write_text(C)
            binary = root / 'check'
            subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-function', '-Wno-unused-variable',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            '-I', str(HERE), str(source), '-ldl', '-o', str(binary)],
                           check=True, capture_output=True, text=True)
            subprocess.run([str(binary), str(root / 'resource.log')], check=True,
                           capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
