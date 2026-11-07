#!/usr/bin/env python3
"""Build in a separate experiment directory; never rebuild the original kernel."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import runpy
import shutil
import subprocess
import traceback

HERE=Path(__file__).resolve().parent

# Exact upstream-host source/build used by the verified persistent production build.
USB_BASELINE = {
    'source_tree': '2f5eda55f2e7f78413370105ce742ea1cbb5c833f90a79a50202b891868aece5',
    'build_tree': 'f6b3da14cc48e0fa5c73aff3443c5131428bad9dec4473ab61ac9bb5a0157f85',
}
# Frozen shared-GPIO public implementation; original fresh3 fixture remains historical evidence.
USB_PUBLIC = {
    'usb-gadget-model.py': 'dc1e597e5fe6e1cfe6bcd56d169f1497ad0ffd3c23ad98774a07af09f8414c92',
    'usb-device-profile.py': '9c520bf67b088b1c8d680a0884ddd1680dbe90fa75c7076e423fd75f215d47db',
    'usb-gadget/sony-dwc3.c': '854abf26410b88bdaafc1ea6cc955ca66c2c4bf5ac34141a5f4a2376b568debe',
    'usb-gadget/sony-dwc3.h': 'c168020e1595aa50f99db94063f2d640cf722c9ef2652b611c456ebd0b90b072',
    'usb-gadget/sony-dwc3-bridge.c': '130d9e81e9a31d7e5ae70aab8741124555a86ac1ac9e2a55d91f94943458d8e2',
    'usb-gadget/sony-dwc3-bridge.h': 'f38c1568250bee46a15449c20a7ca84ffc3c504379bc757b8996f3e081f3eb00',
}
USB_PROVIDER_SHA256 = '0d082bb4863ec26bcc00a8515e27df36fdea23d6c3675386d68202095f014504'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(argv,cwd=None):
    print('BUILD_COMMAND '+repr([str(v) for v in argv]),flush=True)
    subprocess.run([str(v) for v in argv],cwd=cwd,check=True,
                   env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})


def tree_files(root):
    files={}
    for path in sorted(root.rglob('*')):
        relative=path.relative_to(root)
        if '.git' in relative.parts:
            continue
        if path.is_symlink():
            files[str(relative)]='symlink:'+os.readlink(path)
        elif path.is_file():
            files[str(relative)]=digest(path)
    return files


def tree_digest(files):
    return hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()


def usb_baseline(template):
    snapshots={key:tree_files(template/name) for key,name in
               (('source_tree','qemu-11.1.2'),('build_tree','build'))}
    for key,files in snapshots.items():
        if tree_digest(files)!=USB_BASELINE[key]:
            raise ValueError('Unknown USB combination baseline or identity drift: '+key)
    for name,expected in USB_PUBLIC.items():
        if digest(HERE.parent/name)!=expected:
            raise ValueError('Frozen USB implementation drift: '+name)
    return snapshots


def build_qemu(template,stage,production=False,*,usb_device=False):
    if type(usb_device) is not bool or (usb_device and not production):
        raise ValueError('usb_device must be a bool and requires production=True')
    template=template.resolve(strict=True)
    if usb_device:
        stage=stage.resolve()
        if (stage==Path('/') or stage.is_relative_to(HERE.parents[2]) or
                stage.is_relative_to(template) or template.is_relative_to(stage)):
            raise ValueError('USB combination requires a separate scratch stage')
        for name in ('qemu-11.1.2','build'):
            if (stage/name).exists() or (stage/name).is_symlink():
                raise ValueError('Fresh isolated QEMU source/build required')
        baseline=usb_baseline(template)
    for name in ('qemu-11.1.2','build'):
        if (stage/name).exists():
            raise ValueError('Fresh isolated QEMU source/build required')
        run(['cp','-a','--reflink=auto',template/name,stage/name])
    if usb_device:
        for key,name in (('source_tree','qemu-11.1.2'),('build_tree','build')):
            if tree_files(stage/name)!=baseline[key]:
                raise ValueError('USB combination clone identity drift: '+key)
        runpy.run_path(str(HERE.parent/'usb-gadget-model.py'))['patch'](stage/'qemu-11.1.2',stage)
        usb=runpy.run_path(str(HERE.parent/'usb-device-profile.py'))['patch_source'](stage/'qemu-11.1.2',stage)
        if digest(stage/'qemu-11.1.2/hw/arm/sony-usb-device-platform.inc')!=USB_PROVIDER_SHA256:
            raise ValueError('Frozen shared-GPIO provider drift')
    module=runpy.run_path(str(HERE.parent/'persistent-flash-model.py'))
    module['patch'](stage/'qemu-11.1.2',stage)
    board=stage/'qemu-11.1.2/hw/arm/virt.c'
    # Only the explicit build fixture reads -machine kernel/initrd as file paths.
    # Production parent instead supplies the same four qdev properties itself.
    text=board.read_text()
    anchor='static void machvirt_init(MachineState *machine)\n{'
    if text.count(anchor)!=1:
        raise ValueError('Unexpected virt init entrypoint')
    fixture='''
    /* Persistent flash isolated qtest fixture: properties are explicit CLI paths. */
    if (machine->firmware) {
        struct stat st;
        int fd = a7pf_open_regular(machine->firmware, O_RDWR);
        if (fd < 0 || fstat(fd, &st)) {
            error_report("persistent flash fixture backend rejected");
            exit(1);
        }
        close(fd);
        DeviceState *pf = qdev_new("sony-persistent-flash");
        qdev_prop_set_string(pf, "backend", machine->firmware);
        qdev_prop_set_string(pf, "geometry", machine->dtb);
        qdev_prop_set_uint64(pf, "expected-dev", st.st_dev);
        qdev_prop_set_uint64(pf, "expected-ino", st.st_ino);
        sysbus_realize_and_unref(SYS_BUS_DEVICE(pf), &error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(pf), 0, 0x0b000000);
        machine->firmware = NULL;
        machine->dtb = NULL;
    }
'''
    if production:
        fixture='''
    /* Explicit persistent profile; launcher whitelists only these four values. */
    const char *pf_profile=g_getenv("QEMU_A7PF_PROFILE");
    const char *pf_keys[]={"QEMU_A7PF_FD","QEMU_A7PF_DEV","QEMU_A7PF_INO"};
    uint64_t pf_values[3]={0};
    bool pf_any=pf_profile!=NULL;
    for (unsigned int i=0;i<3;i++) pf_any|=g_getenv(pf_keys[i])!=NULL;
    if (pf_any) {
        if (!pf_profile || strcmp(pf_profile,"persistent-flash-cold-v1")) {
            error_report("missing or invalid persistent flash profile"); exit(1);
        }
        for (unsigned int i=0;i<3;i++) {
            const char *value=g_getenv(pf_keys[i]);
            if (!value || !*value || strspn(value,"0123456789")!=strlen(value)) {
                error_report("invalid persistent flash numeric property"); exit(1);
            }
            errno=0; pf_values[i]=g_ascii_strtoull(value,NULL,10);
            if (errno || !pf_values[i]) {
                error_report("overflow or zero persistent flash property"); exit(1);
            }
        }
        if (pf_values[0]<3 || pf_values[0]>INT_MAX) {
            error_report("persistent flash fd must be inherited and >=3"); exit(1);
        }
        DeviceState *pf=qdev_new("sony-persistent-flash");
        qdev_prop_set_int32(pf,"backend-fd",pf_values[0]);
        qdev_prop_set_string(pf,"geometry","/instance/persistent-geometry.bin");
        qdev_prop_set_uint64(pf,"expected-dev",pf_values[1]);
        qdev_prop_set_uint64(pf,"expected-ino",pf_values[2]);
        sysbus_realize_and_unref(SYS_BUS_DEVICE(pf),&error_fatal);
        sysbus_mmio_map(SYS_BUS_DEVICE(pf),0,0x0b000000);
        fprintf(stderr,"PERSISTENT_FLASH_REALIZED base=0x0b000000 inherited_fd=%" PRIu64 "\\n",pf_values[0]);
    }
'''
    # Include must precede machvirt_init for fixture-only stat/helper use.
    text=text.replace(module['INCLUDE'],'')
    include='#include "../block/a7c2-persistent/flash-qemu.c"\n'
    anchor_include='#include "qemu/osdep.h"\n'
    if text.count(anchor_include)!=1:
        raise ValueError('Unexpected virt include anchor')
    text=text.replace(anchor_include,anchor_include+include)
    text=text.replace(anchor,anchor+fixture)
    board.write_text(text)
    ninja=(stage/'build/build.ninja').read_text().replace(str(template),str(stage))
    for old_source in set(re.findall(r'/[^\s\'\"]+/qemu-11\.1\.2(?=/|\s|$)',ninja)):
        ninja=ninja.replace(old_source,str(stage/'qemu-11.1.2'))
    lines=ninja.splitlines(True)
    header=''.join(lines[:next(i for i,l in enumerate(lines) if l.startswith('build '))])
    def block(target):
        hits=[i for i,l in enumerate(lines) if l.startswith('build '+target+':')]
        if len(hits)!=1:
            raise ValueError('Cannot freeze copied build target '+target)
        begin=hits[0];end=begin+1
        while end<len(lines) and (lines[end].startswith(' ') or not lines[end].strip()):
            end+=1
        return ''.join(lines[begin:end])
    blocks=[block('libsystem_arm.a.p/hw_arm_virt.c.o')]
    link=block('qemu-system-aarch64')
    if usb_device:
        # Reuse the known USB compiler flags; link both new objects explicitly.
        compiler=block('libsystem.a.p/hw_usb_hcd-dwc3.c.o')
        objects=[]
        for name in ('sony-dwc3','sony-dwc3-bridge'):
            obj='libsystem.a.p/hw_usb_'+name+'.c.o'
            blocks.append(compiler.replace('hw_usb_hcd-dwc3.c.o','hw_usb_'+name+'.c.o')
                          .replace('/hcd-dwc3.c','/'+name+'.c'))
            objects.append(obj)
        anchor='build qemu-system-aarch64: c_LINKER_RSP '
        if link.count(anchor)!=1 or any(obj in link for obj in objects):
            raise ValueError('Unsupported USB combination linker layout')
        link=link.replace(anchor,anchor+' '.join(objects)+' ',1)
    blocks.append(link)
    frozen=stage/'build/flash.ninja'
    frozen.write_text(header+'\n'.join(blocks))
    command=['ninja','-f','flash.ninja','-j2','qemu-system-aarch64']
    if usb_device:
        # All origin trees are read-only even through copied build symlinks.
        command=['bwrap','--unshare-all','--die-with-parent','--ro-bind','/','/',
                 '--dev-bind','/dev','/dev','--proc','/proc','--tmpfs','/tmp',
                 '--bind',str(stage),str(stage),'--chdir',str(stage/'build')]+command
    run(command,stage/'build')
    result=dict(qemu_binary_sha256=digest(stage/'build/qemu-system-aarch64'),
                test_fixture_only=not production,board_profile='persistent-flash-cold-v1' if production else 'qtest-fixture',
                binary=str(stage/'build/qemu-system-aarch64'),
                board_source_sha256=digest(board),
                source_delta_sha256=digest(stage/'persistent-flash-model-delta.json'))
    if usb_device:
        after=tree_files(stage/'qemu-11.1.2')
        before=baseline['source_tree']
        delta={name:dict(before=before.get(name),after=after.get(name))
               for name in sorted(before.keys()|after.keys()) if before.get(name)!=after.get(name)}
        for name,expected in usb['model_source_sha256'].items():
            if after.get(name)!=expected:
                raise ValueError('USB combination model drift: '+name)
        for key,name in (('source_tree','qemu-11.1.2'),('build_tree','build')):
            if tree_files(template/name)!=baseline[key]:
                raise ValueError('Original USB combination baseline changed: '+key)
        source_receipt=stage/'persistent-usb-source-delta.json'
        source_receipt.write_text(json.dumps(dict(schema='a7c2.persistent-usb-source.v1',
            baseline=str(template),baseline_identity=USB_BASELINE,
            source_tree_sha256_before=tree_digest(before),source_tree_sha256_after=tree_digest(after),
            files=delta,original_source_and_build_unchanged=True,
            patch_order=['usb-gadget-model.patch','usb-device-profile.patch_source','persistent-flash-model.patch','persistent-production-wire'],
            public_usb_sha256=USB_PUBLIC,model_source_sha256=usb['model_source_sha256'],
            provider_sha256=USB_PROVIDER_SHA256),indent=2)+'\n')
        (stage/'source-before.json').write_text(json.dumps(before,sort_keys=True)+'\n')
        (stage/'source-after.json').write_text(json.dumps(after,sort_keys=True)+'\n')
        result.update(usb_device_profile=usb['profile'],controller_selection='explicit; upstream-host default retained',
            usb_source_sha256={**usb['model_source_sha256'],
                'hw/arm/sony-usb-device-platform.inc':USB_PROVIDER_SHA256},
            source_tree_sha256_before=tree_digest(before),source_tree_sha256_after=tree_digest(after),
            source_deltas_sha256={name:digest(stage/name) for name in
                ('dwc3-model-delta.json','usb-device-source-delta.json','persistent-flash-model-delta.json','persistent-usb-source-delta.json')},
            all_source_delta_sha256=digest(source_receipt),frozen_build_sha256=digest(frozen),
            baseline_identity=USB_BASELINE,original_source_and_build_unchanged=True,
            guest_driver_verified=False,guest_descriptor_ready=False,export_allowed=False)
    return result


def build_module(kernel,stage):
    original_config=digest(kernel/'.config')
    # Sony ships .config inside its tree. A private copy is necessary because
    # upstream Kbuild rejects O= if its source already contains .config.
    src=stage/'kernel-source'; out=stage/'kernel-build'; module=stage/'module'
    if src.exists() or out.exists() or module.exists():
        raise ValueError('Fresh private kernel/module workspace required')
    run(['cp','-a','--reflink=auto',kernel,src])
    out.mkdir();module.mkdir()
    shutil.copyfile(src/'.config',out/'.config')
    (src/'.config').unlink()
    for p in ('Makefile','sony_persistent_flash.c'):
        shutil.copyfile(HERE/p,module/p)
    # The original kernel is 4.9.337-scel+; no code/config/export changes.
    args=['make','-C',src,'O='+str(out),'ARCH=arm64','CROSS_COMPILE=aarch64-linux-gnu-',
          'LOCALVERSION=+','KCFLAGS=-fno-pie']
    run(args+['olddefconfig','modules_prepare'])
    run(args+['M='+str(module),'modules'])
    ko=module/'sony_persistent_flash.ko'
    if not ko.is_file() or digest(kernel/'.config')!=original_config:
        raise ValueError('Module missing or original kernel config changed')
    result=subprocess.run(['aarch64-linux-gnu-readelf','-p','.modinfo',ko],capture_output=True,text=True,check=True)
    if 'vermagic=4.9.337-scel+ SMP preempt mod_unload aarch64' not in result.stdout:
        raise ValueError('Wrong module vermagic: '+result.stdout)
    (stage/'module-modinfo.txt').write_text(result.stdout)
    return dict(module_sha256=digest(ko),original_kernel_config_unchanged=True,
                config_before_sha256=original_config,config_after_sha256=digest(kernel/'.config'),
                guest_abi_verified=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage',required=True,type=Path)
    p.add_argument('--qemu-template',type=Path)
    p.add_argument('--kernel-source',type=Path)
    p.add_argument('--production',action='store_true',help='wire explicit persistent board profile; no qtest bios/dtb fixture')
    p.add_argument('--usb-device',action='store_true',help='add frozen Sony USB device capability to the verified production template; runtime selection remains explicit')
    a=p.parse_args()
    if a.usb_device and (not a.production or a.qemu_template is None or a.kernel_source is not None):
        p.error('--usb-device requires --production and --qemu-template, without --kernel-source')
    stage=a.stage.resolve()
    if stage==Path('/') or stage.is_relative_to(HERE.parents[2]):
        raise ValueError('Build output must be outside the delivery/source repository')
    for original in (a.qemu_template,a.kernel_source):
        if original is not None:
            original=original.resolve()
            if stage.is_relative_to(original) or original.is_relative_to(stage):
                raise ValueError('Build output must not overlap its original source/template')
    stage.mkdir(parents=True,exist_ok=True)
    report={'status':'started','physical_compatibility':False}
    try:
        if a.qemu_template:
            report.update(build_qemu(a.qemu_template,stage,a.production,usb_device=a.usb_device))
        if a.kernel_source:
            report.update(build_module(a.kernel_source.resolve(),stage))
        report['status']='compiled'
    except BaseException as e:
        report.update(status='failed',error=str(e));traceback.print_exc()
    finally:
        (stage/('module-result.json' if a.kernel_source else 'qemu-result.json')).write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if report['status']=='compiled' else 1)
