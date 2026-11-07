#!/usr/bin/env python3
"""Combination build contract tests; no firmware, guest or physical devices."""
import hashlib
import inspect
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'build.py'))
BUILD=API['build_qemu']
G=BUILD.__globals__


def fixture(root):
    source=root/'qemu-11.1.2';build=root/'build'
    (source/'hw/arm').mkdir(parents=True);(source/'hw/usb').mkdir(parents=True)
    (source/'configure').write_text('# isolated fake configure\n')
    (source/'hw/arm/virt.c').write_text('''#include "qemu/osdep.h"
#include "hw/arm/virt.h"
/* layout: 0x0c000000 0x0a000000; retain timers/GIC/SPAcc/upstream-host */
static void machvirt_init(MachineState *machine)
{
    if (g_getenv("QEMU_SONY_USB_DWC3")) { /* upstream-host */ }
    create_msi_controller(vms);
}
''')
    (source/'hw/usb/meson.build').write_text("system_ss.add(files('hcd-dwc3.c'))\n")
    build.mkdir()
    (build/'build.ninja').write_text('''rule c_COMPILER
 command = cc $ARGS -c $in -o $out
rule c_LINKER_RSP
 command = cc @$out.rsp
 rspfile = $out.rsp
 rspfile_content = $in $LINK_ARGS
build libsystem_arm.a.p/hw_arm_virt.c.o: c_COMPILER ../qemu-11.1.2/hw/arm/virt.c
 ARGS = -DBOARD_FLAGS -I../qemu-11.1.2

build libsystem.a.p/hw_usb_hcd-dwc3.c.o: c_COMPILER ../qemu-11.1.2/hw/usb/hcd-dwc3.c
 DEPFILE = libsystem.a.p/hw_usb_hcd-dwc3.c.o.d
 ARGS = -DUSB_FLAGS -I../qemu-11.1.2

build qemu-system-aarch64: c_LINKER_RSP libsystem_arm.a.p/hw_arm_virt.c.o libsystem.a.p/hw_usb_hcd-dwc3.c.o | libqemuutil.a
 LINK_ARGS = -lglib-2.0

''')
    (build/'qemu-system-aarch64').write_bytes(b'baseline-binary')
    return {key:API['tree_digest'](API['tree_files'](root/name)) for key,name in
            (('source_tree','qemu-11.1.2'),('build_tree','build'))}


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='a7pf-usb-build-')
        self.root=Path(self.temp.name)
        self.template=self.root/'template'
        self.identities=fixture(self.template)
        self.commands=[]

    def tearDown(self):
        self.temp.cleanup()

    def fake_run(self,argv,cwd=None):
        argv=[str(v) for v in argv];self.commands.append(argv)
        if argv[0]=='cp':shutil.copytree(argv[-2],argv[-1],symlinks=True)
        else:(Path(cwd)/'qemu-system-aarch64').write_bytes(b'new-combination-binary')

    def build(self,**kwargs):
        stage=self.root/'stage';stage.mkdir()
        with patch.dict(G,run=self.fake_run,USB_BASELINE=self.identities):
            result=BUILD(self.template,stage,**kwargs)
        return stage,result

    def test_keyword_bool_defaults_to_false(self):
        parameter=inspect.signature(BUILD).parameters['usb_device']
        self.assertIs(parameter.default,False)
        self.assertEqual(parameter.kind,inspect.Parameter.KEYWORD_ONLY)
        for value in ('sony-device','unknown',1,None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'bool'):
                BUILD(self.template,self.root/'unused',True,usb_device=value)
        self.assertFalse((self.root/'unused').exists())

    def test_device_requires_production(self):
        with self.assertRaisesRegex(ValueError,'production'):
            BUILD(self.template,self.root/'unused',usb_device=True)
        self.assertFalse((self.root/'unused').exists())

    def assert_legacy_output(self,stage,result,label):
        expected=json.loads((HERE/'fixtures/legacy-build-identity.json').read_text())[label]
        for name,want in expected.items():
            got=API['digest'](stage/'build/flash.ninja') if name=='frozen_ninja_sha256' else result[name]
            self.assertEqual(got,want,name)

    def test_legacy_production_default_retains_two_targets(self):
        stage,result=self.build(production=True)
        self.assert_legacy_output(stage,result,'production')
        text=(stage/'qemu-11.1.2/hw/arm/virt.c').read_text()
        self.assertNotIn('SONY_USB_DEVICE_PROFILE',text)
        self.assertNotIn('usb_device_profile',result)
        self.assertFalse(result['test_fixture_only'])
        self.assertEqual(result['board_profile'],'persistent-flash-cold-v1')
        self.assertNotIn('machine->firmware',text)
        ninja=(stage/'build/flash.ninja').read_text()
        self.assertEqual(ninja.count('\nbuild '),2)
        self.assertEqual(self.commands[-1],['ninja','-f','flash.ninja','-j2','qemu-system-aarch64'])

    def test_legacy_qtest_fixture_keeps_explicit_bios_dtb(self):
        stage,result=self.build()
        self.assert_legacy_output(stage,result,'qtest')
        self.assertTrue(result['test_fixture_only'])
        self.assertIn('machine->firmware',(stage/'qemu-11.1.2/hw/arm/virt.c').read_text())

    def test_combination_order_flags_identity_and_readonly_origin(self):
        before={name:API['tree_files'](self.template/name) for name in ('qemu-11.1.2','build')}
        stage,result=self.build(production=True,usb_device=True)
        for name in before:self.assertEqual(before[name],API['tree_files'](self.template/name))
        self.assertFalse(result['test_fixture_only'])
        self.assertEqual(result['board_profile'],'persistent-flash-cold-v1')
        self.assertEqual(result['usb_device_profile'],'virtual-functional-sony-usb-device-v1')
        text=(stage/'qemu-11.1.2/hw/arm/virt.c').read_text()
        self.assertLess(text.index('flash-qemu.c'),text.index('machvirt_init'))
        self.assertIn('if (g_getenv("QEMU_SONY_USB_DEVICE"))',text)
        self.assertIn('QEMU_SONY_USB_DWC3',text)
        self.assertIn('QEMU_SONY_DWC3_CORE_TEST',text)
        self.assertIn('QEMU_A7PF_PROFILE',text)
        self.assertIn('timers/GIC/SPAcc/upstream-host',text)
        ninja=(stage/'build/flash.ninja').read_text()
        for name in ('sony-dwc3','sony-dwc3-bridge'):
            self.assertIn('build libsystem.a.p/hw_usb_'+name+'.c.o: c_COMPILER',ninja)
            self.assertIn('../qemu-11.1.2/hw/usb/'+name+'.c',ninja)
        self.assertEqual(ninja.count('ARGS = -DUSB_FLAGS'),2)
        link=next(line for line in ninja.splitlines() if line.startswith('build qemu-system-aarch64:'))
        for name in ('sony-dwc3','sony-dwc3-bridge','hcd-dwc3'):
            self.assertIn('hw_usb_'+name+'.c.o',link)
        command=self.commands[-1]
        self.assertEqual(command[:6],['bwrap','--unshare-all','--die-with-parent','--ro-bind','/','/'])
        self.assertEqual(command[command.index('--bind')+1:command.index('--bind')+3],[str(stage)]*2)
        delta=json.loads((stage/'persistent-usb-source-delta.json').read_text())
        self.assertEqual(delta['patch_order'],['usb-gadget-model.patch','usb-device-profile.patch_source','persistent-flash-model.patch','persistent-production-wire'])
        self.assertEqual(len(delta['files']),10)
        self.assertEqual(result['all_source_delta_sha256'],API['digest'](stage/'persistent-usb-source-delta.json'))
        for name,expected in result['source_deltas_sha256'].items():
            self.assertEqual(API['digest'](stage/name),expected)
        for name,expected in result['usb_source_sha256'].items():
            self.assertEqual(API['digest'](stage/'qemu-11.1.2'/name),expected)
        self.assertEqual(result['qemu_binary_sha256'],API['digest'](stage/'build/qemu-system-aarch64'))
        for key in ('guest_driver_verified','guest_descriptor_ready','export_allowed'):
            self.assertIs(result[key],False)

    def test_unknown_source_variant_and_build_drift_rejected_before_copy(self):
        for name in ('qemu-11.1.2/configure','build/qemu-system-aarch64'):
            target=self.template/name;old=target.read_bytes();target.write_bytes(old+b'drift')
            try:
                with patch.dict(G,run=self.fake_run,USB_BASELINE=self.identities):
                    with self.assertRaisesRegex(ValueError,'baseline or identity drift'):
                        BUILD(self.template,self.root/'unused',True,usb_device=True)
                self.assertEqual(self.commands,[])
            finally:target.write_bytes(old)

    def test_overlap_and_existing_workspace_rejected(self):
        for stage in (self.template,self.template/'nested'):
            with self.assertRaisesRegex(ValueError,'separate scratch'):
                BUILD(self.template,stage,True,usb_device=True)
        stage=self.root/'used';(stage/'build').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError,'Fresh isolated'):
            BUILD(self.template,stage,True,usb_device=True)
        self.assertEqual(self.commands,[])

    def test_frozen_shared_gpio_fixture_matches_public_model_and_provider(self):
        frozen=json.loads((HERE/'fixtures/usb-shared-gpio-identity.json').read_text())
        self.assertEqual(API['USB_PUBLIC'],frozen['public_sha256'])
        self.assertEqual(API['USB_BASELINE'],frozen['baseline_identity'])
        for name,expected in frozen['public_sha256'].items():
            self.assertEqual(API['digest'](HERE.parent/name),expected)
        for name,expected in frozen['source_sha256'].items():
            if name.endswith('platform.inc'):
                content=runpy.run_path(str(HERE.parent/'usb-device-profile.py'))['PLATFORM_C'].encode()
            else:
                content=(HERE.parent/'usb-gadget'/Path(name).name).read_bytes()
                if name.endswith('sony-dwc3.c'):content=b'#define SONY_DWC3_QEMU 1\n'+content
            self.assertEqual(hashlib.sha256(content).hexdigest(),expected)
        self.assertEqual(API['USB_PROVIDER_SHA256'],frozen['source_sha256']['hw/arm/sony-usb-device-platform.inc'])

    def test_frozen_public_drift_rejected(self):
        expected=dict(API['USB_PUBLIC']);expected['usb-device-profile.py']='0'*64
        with patch.dict(G,USB_BASELINE=self.identities,USB_PUBLIC=expected):
            with self.assertRaisesRegex(ValueError,'USB implementation drift'):
                API['usb_baseline'](self.template)

    def test_cli_rejects_device_without_production(self):
        result=subprocess.run(['python3','-B',str(HERE/'build.py'),'--stage',str(self.root/'unused'),'--usb-device'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertFalse((self.root/'unused').exists())


if __name__=='__main__':unittest.main()
