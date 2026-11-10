"""Explicit product DWC3 candidate, per-run endpoint identity and safe detach."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess

ANALYSIS=Path(__file__).resolve().parent
PRODUCT=ANALYSIS.parents[1]
PROFILE='virtual-functional-sony-usb-device-v1'
EE_COLD_MODE='ee-normal-wake-cold-functional-v1'
EE_COLD_SOURCES=('ee-normal-wake-cold.c','ee-capability-input.c','ee-capability-input.h','ee-normal-wake-cold.h','imaging-device.h','usb-ee-normal-cold.inc','usb-ee-zero-observe.inc','usb-ee-native-got.h')


def sha(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def selected(environment):
    value=environment.get('A7C2_SONY_USB_DEVICE')
    if value is None:return False
    if value!=PROFILE:raise ValueError('Unknown explicit Sony USB device profile')
    return True


def candidate(receipt):
    path=Path(receipt).absolute()
    if not path.is_relative_to(PRODUCT/'source/build') or any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('USB candidate must be an ordinary product build receipt')
    proof=json.loads(path.read_bytes());binary=path.parent/'build/qemu-system-aarch64'
    if proof.get('schema')!='a7c2-product-sony-usb-device-build-v1' or proof.get('profile')!=PROFILE or proof.get('build_completed') is not True or proof.get('binary')!=str(binary) or proof.get('binary_sha256')!=sha(binary):
        raise ValueError('USB candidate binary differs from its explicit completed build')
    if set(proof['product_sources'])!={'sony-dwc3.c','sony-dwc3.h','sony-dwc3-bridge.c','sony-dwc3-bridge.h','sony-usb-platform.inc','board-fragment.inc','stage.py'}:
        raise ValueError('USB candidate source membership differs')
    for name,digest in proof['product_sources'].items():
        if sha(PRODUCT/'source/usb-device'/name)!=digest:raise ValueError('Product USB source changed: '+name)
    for name,digest in proof['source_after'].items():
        if sha(path.parent/'qemu-11.1.2'/name)!=digest:raise ValueError('Staged USB source changed: '+name)
    persistent=json.loads((path.parent/'persistent-flash-build.json').read_bytes())
    if persistent.get('binary_sha256')!=proof['binary_sha256']:raise ValueError('USB candidate lacks the same persistent flash build')
    return binary


def environment(current,run):
    if not selected(current):return {}
    if current.get('A7C2_ORIGINAL_COLD')!='original-init-v1':raise ValueError('Product Sony USB requires original init cold startup')
    run=Path(run).absolute();info=run.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022 or any(p.is_symlink() for p in (run,*run.parents)):
        raise ValueError('USB endpoint requires an owned private run')
    for name in ('usb-endpoint.sock','usb-qmp.sock','usb-context.json'):
        if os.path.lexists(run/name):raise ValueError('Fresh USB run resources required')
    binary=candidate(current['A7C2_USB_DEVICE_BUILD'])
    return dict(QEMU_SYSTEM_DIR=str(binary.parent),QEMU_SYSTEM_BINARY=binary.name,QEMU_SONY_USB_DEVICE='1',QEMU_SONY_USB_RUN_ID=run.name,QEMU_SONY_USB_LEASE=secrets.token_hex(32),QEMU_SONY_USB_QMP_HOST_PATH=str(run/'usb-qmp.sock'),QEMU_SONY_USB_BACKEND_SOCKET='/out/usb-endpoint.sock')


def ee_native_pins(payload):
    """Bind the exact reviewed product native osal_free_msg forwarder for EE slots."""
    path=ANALYSIS/'menu-observe.so';image=path.read_bytes()
    if image[:6]!=b'\x7fELF\x02\x01' or image[18:20]!=b'\xb7\x00':
        raise ValueError('EE native forwarder requires AArch64 ELF64 LE')
    phoff=struct.unpack_from('<Q',image,32)[0];phsize,phnum=struct.unpack_from('<HH',image,54)
    segments=[struct.unpack_from('<IIQQQQQQ',image,phoff+i*phsize) for i in range(phnum)]
    symbols=subprocess.run(['readelf','-Ws',str(path)],capture_output=True,text=True,check=True,timeout=10).stdout
    rows=re.findall(r'^\s*\d+:\s+([0-9a-f]+)\s+(\d+)\s+(FUNC|OBJECT)\s+(GLOBAL|LOCAL)\s+DEFAULT\s+\d+\s+(\w+)\s*$',symbols,re.M)
    found={(int(va,16),int(size)) for va,size,kind,bind,name in rows if name=='osal_free_msg' and kind=='FUNC' and bind=='GLOBAL'}
    if len(found)!=1:raise ValueError('EE native osal_free_msg export is ambiguous or missing')
    va,size=found.pop()
    caches={int(value,16) for value,count,kind,bind,name in rows if name=='real_free_msg' and kind=='OBJECT' and bind=='LOCAL' and int(count)==8}
    windows=[offset+va-start for kind,flags,offset,start,_,count,_,_ in segments if kind==1 and flags&1 and start<=va and va+16<=start+count]
    if len(caches)!=1 or len(windows)!=1 or size<16:raise ValueError('EE native export/cache/window missing')
    cached=caches.pop()
    if not any(kind==1 and flags&2 and start<=cached and cached+8<=start+memory for kind,flags,_,start,_,_,memory,_ in segments):
        raise ValueError('EE native cached original is outside writable PT_LOAD')
    code=image[windows[0]:windows[0]+16].hex()
    row='{"osal_free_msg",'+hex(va)+','+hex(cached)+',{'+','.join('0x'+code[i:i+2] for i in range(0,32,2))+'}}'
    header=Path(payload)/'usb-ee-native-pins.h'
    header.write_text('static const struct ee_native_export ee_native_exports[]={\n'+row+'\n};\n'
        'static const struct ee_native_contract ee_native_pins={"/simulation/menu-observe.so",'
        +str(path.stat().st_size)+',"'+sha(path)+'",1,ee_native_exports};\n',encoding='ascii')
    header.chmod(0o600)
    return header


def ee_normal_cold(current,payload):
    """Explicit opt-in EE NormalWake cold adapter inputs; default off, external private header only."""
    enabled=current.get('A7C2_USB_EE_NORMAL_COLD');declared=current.get('A7C2_USB_EE_NORMAL_COLD_INPUT')
    if enabled is None:
        if declared is not None:raise ValueError('EE cold private input supplied without the explicit profile')
        return None
    if enabled!='1':raise ValueError('Unknown explicit EE cold observer profile')
    if not declared:raise ValueError('EE cold profile requires an external private input header path')
    path=Path(declared).absolute()
    if path.is_symlink() or not path.is_file():raise ValueError('EE cold private input must be a regular non-symlink file')
    if path.is_relative_to(PRODUCT):raise ValueError('EE cold private input must stay outside the public product tree')
    data=path.read_bytes()
    if (b'#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1\n' not in data or b'ee_nwc_prepared_assets' not in data
            or b'ee_cold_adc' not in data or b'#define EE_COLD_ADMISSION_SOURCE ' not in data):
        raise ValueError('EE cold private input lacks the hash-bound adapter contract')
    pins=ee_native_pins(payload)
    return dict(defines=['-DUSB_EE_NORMAL_COLD=1','-D_REENTRANT','-DUSB_EE_NORMAL_COLD_INPUT="'+str(path)+'"',
                         '-DUSB_EE_NATIVE_INPUT="'+str(pins)+'"','-I',str(PRODUCT/'source/usb-device')],
                 compiled=('ee-normal-wake-cold.c','ee-capability-input.c'),sources=EE_COLD_SOURCES,
                 helpers={'usb-ee-native-pins.h':pins})


def prepare_observer(current,payload):
    if not selected(current):return {}
    source=PRODUCT/'source/usb-device';payload=Path(payload);target=payload/'usb-start-observe.so'
    cold=ee_normal_cold(current,payload)
    inputs={name:sha(source/name) for name in ('usb-start-observe.c','usb-msc-sender.inc','usb-resources-observe.inc','usb-start-observe.map',*(cold['sources'] if cold else ()))}
    libraries=[ANALYSIS/'menu-root/lib'/name for name in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')]
    command=['clang','--target=aarch64-linux-gnu','-DUSB_RESOURCE_OBSERVE=1',*(cold['defines'] if cold else ()),
             '--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2','-mno-outline-atomics','-shared','-fPIC',
             '-Wl,--no-undefined','-Wl,-z,now','-Wl,--version-script='+str(source/'usb-start-observe.map'),
             str(source/'usb-start-observe.c'),*([str(source/name) for name in cold['compiled']] if cold else []),
             *map(str,libraries),'-o',str(target)]
    result=subprocess.run(command,capture_output=True)
    (payload/'usb-observer-build.log').write_bytes(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('USB passive observer original-ABI build failed')
    if any(sha(source/name)!=digest for name,digest in inputs.items()):raise ValueError('USB observer source changed while building')
    target.chmod(0o600)
    helpers={'usb-start-observe.so':target}
    if cold:helpers.update(cold['helpers'])
    mode=current.get('A7C2_USB_SENSER')
    if mode is not None:
        if mode!='original-init2-v1':raise ValueError('Unknown explicit original Senser startup mode')
        original=ANALYSIS/'menu-root/usr/bin/sen.elf'
        script=payload/'usb-senser-mode'
        script.write_text('''#!/bin/busybox sh
set -e
state=/log/qemu/usb-senser-mode
case "$1" in
 prepare)
  [ ! -e "$state" ] || exit 78
  /simulation/audit space /setting 1048576
  /bin/busybox mkdir -p "$state"
  /simulation/audit space /tmp 4096
  [ ! -L /tmp/jiritsu ] || exit 78
  if /bin/busybox grep -q ' /tmp/jiritsu ' /proc/mounts; then exit 78; fi
  if [ -e /tmp/jiritsu ]; then
   [ -d /tmp/jiritsu ] || exit 78
  else
   /bin/busybox mkdir /tmp/jiritsu
   /bin/busybox touch "$state/jiritsu-created"
  fi
  if [ -e /setting/sen/smode ]; then
   /bin/busybox cp /setting/sen/smode "$state/before"
   /bin/busybox cmp /setting/sen/smode "$state/before"
  else
   /bin/busybox touch "$state/absent"
  fi
  /bin/busybox mkdir -p /setting/sen
  echo UU > /setting/sen/smode
  [ "$(/bin/busybox cat /setting/sen/smode)" = UU ]
  /bin/busybox sync
  echo PRODUCT_USB_SENSER_ORIGINAL_INIT2_SELECTED
  ;;
 restore)
  [ -d "$state" ] || exit 0
  [ ! -L /tmp/jiritsu ] || exit 78
  if /bin/busybox grep -q ' /tmp/jiritsu ' /proc/mounts; then
   /bin/busybox grep -q '^/dev/nflasha6 /tmp/jiritsu vfat ' /proc/mounts || exit 78
   /bin/busybox umount /tmp/jiritsu
  fi
  if [ -f "$state/jiritsu-created" ] && [ -e /tmp/jiritsu ]; then
   /bin/busybox rmdir /tmp/jiritsu
   [ ! -e /tmp/jiritsu ]
  fi
  if [ -f "$state/absent" ]; then
   /bin/busybox rm -f /setting/sen/smode
   [ ! -e /setting/sen/smode ]
  else
   /bin/busybox cp "$state/before" /setting/sen/smode
   /bin/busybox cmp "$state/before" /setting/sen/smode
  fi
  /bin/busybox sync
  echo PRODUCT_USB_SENSER_ORIGINAL_MODE_RESTORED
  ;;
 *) exit 78;;
esac
'''.replace('/log/qemu/usb-senser-mode','/log/qemu/usb-senser-mode-'+secrets.token_hex(12)),encoding='ascii');script.chmod(0o755)
        wrapper=payload/'sen-wrapper';wrapper.write_text('#!/bin/busybox sh\nexport LD_PRELOAD=/simulation/usb-start-observe.so\nexec /simulation/sen-original "$@"\n',encoding='ascii');wrapper.chmod(0o755)
        placeholder=payload/'sen-original';placeholder.write_bytes(b'');placeholder.chmod(0o755)
        identity=payload/'sen-sha256';identity.write_text(sha(original)+'\n',encoding='ascii')
        helpers.update({p.name:p for p in (script,wrapper,placeholder,identity)})
    return helpers


def publish_context(environment,run,peer):
    if not selected(environment):return
    from usb_control import UsbControl,usbip
    run=Path(run)
    context=dict(run_id=run.name,qmp_path=str(run/'usb-qmp.sock'),backend_path=str(run/'usb-endpoint.sock'),lease=environment['QEMU_SONY_USB_LEASE'],vm_pid=peer)
    control=UsbControl(run,**context);control._check_vm()
    usbip.write_owned_json(run/'usb-context.json',context)


def guest_diagnostic():
    return '''echo 'PRODUCT_USB_STATUS_BEGIN'
/bin/busybox grep -E '^(Uid|Gid):' /proc/$$/status
/bin/busybox cat /proc/modules /proc/interrupts
for p in /sys/class/udc/*; do
  [ -e "$p" ] || continue
  echo PRODUCT_USB_UDC=$p
  for f in state function current_speed maximum_speed uevent; do echo PRODUCT_USB_FIELD=$f; /bin/busybox cat "$p/$f"; done
done
for p in /sys/class/extcon/*; do
  [ -e "$p" ] || continue
  echo PRODUCT_USB_EXTCON=$p
  /bin/busybox cat "$p/name" "$p/state"
done
/bin/busybox cat /sys/devices/platform/soc/f1080000.usbs/f10c0000.usb/power/control /proc/udm/fusb
/bin/busybox ls -l /dev/usb
/bin/busybox cat /dev/qemu-simulation/usb-start-observe.log
for p in /proc/[0-9]*/fd/*; do
 target=$(/bin/busybox readlink "$p")
 case "$target" in /dev/usb/*) echo PRODUCT_USB_FD=$p:$target;; esac
done
for p in /proc/[0-9]*/maps; do /bin/busybox grep -E 'lib(UsbControl|InfraUsbCmn|InfraMscServer|Jiritsu)[.]so' "$p" && echo PRODUCT_USB_MAPS=$p; done
echo 'PRODUCT_USB_STATUS_END'
true'''


def require_disconnected(run):
    if not (Path(run)/'usb-context.json').exists():return None
    from usb_ui import action
    result=action(Path(run).absolute(),'disconnect')
    if result.get('phase')!='disconnected' or result.get('preload_recovery_required') or result.get('owned_port'):
        raise RuntimeError('USB ownership or preload recovery is pending; retain the VM: '+str(result.get('blocked_reason')))
    return result
