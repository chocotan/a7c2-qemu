"""Explicit product DWC3 candidate, per-run endpoint identity and safe detach."""
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import tempfile

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
    from single_ap_sockets import roots_for_run
    roots=roots_for_run(run,current)
    if roots is not None and any(current.get(name, '') not in ('', '0') for name in
                                 ('A7C2_USB_NET','MENU_USB_NET','QEMU_SONY_USB_NET','A7C2_USB_NET_SELFTEST')):
        raise ValueError('Single AP short sockets do not support USB network routes')
    if not selected(current):return {}
    if current.get('A7C2_ORIGINAL_COLD')!='original-init-v1':raise ValueError('Product Sony USB requires original init cold startup')
    run=Path(run).absolute();info=run.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022 or any(p.is_symlink() for p in (run,*run.parents)):
        raise ValueError('USB endpoint requires an owned private run')
    endpoints=run if roots is None else roots.sockets
    for path in (endpoints/'usb-endpoint.sock',endpoints/'usb-qmp.sock',run/'usb-context.json'):
        if os.path.lexists(path):raise ValueError('Fresh USB run resources required')
    binary=candidate(current['A7C2_USB_DEVICE_BUILD'])
    return dict(QEMU_SYSTEM_DIR=str(binary.parent),QEMU_SYSTEM_BINARY=binary.name,QEMU_SONY_USB_DEVICE='1',QEMU_SONY_USB_RUN_ID=run.name,QEMU_SONY_USB_LEASE=secrets.token_hex(32),QEMU_SONY_USB_QMP_HOST_PATH=str(endpoints/'usb-qmp.sock'),QEMU_SONY_USB_BACKEND_SOCKET=('/out' if roots is None else '/sockets')+'/usb-endpoint.sock')


def build_output_directory(payload):
    payload=Path(payload)
    if (not payload.is_absolute() or str(payload)!=os.path.normpath(str(payload)) or
            any(payload==Path(root) or payload.is_relative_to(root) for root in ('/tmp','/var/tmp','/dev','/proc','/sys','/run')) or
            any(parent.is_symlink() for parent in (payload,*payload.parents))):
        raise ValueError('Observer input output must be an absolute non-symlink project path')
    for parent in payload.parents:
        ancestor=parent.lstat()
        if (not stat.S_ISDIR(ancestor.st_mode) or ancestor.st_uid not in (0,os.geteuid()) or
                ancestor.st_mode&0o022):
            raise ValueError('Observer input output ancestor must be a trusted non-writable directory')
    info=payload.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or info.st_mode&0o022:
        raise ValueError('Observer input output must be an owned non-writable directory')
    return payload


def ee_native_pins(payload):
    """Bind the exact reviewed product native osal_free_msg forwarder for EE slots."""
    payload=build_output_directory(payload)
    path=ANALYSIS/'menu-observe.so'
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or before.st_mode&0o022 or
                before.st_nlink!=1 or not 0<before.st_size<=64*1024**2):
            raise ValueError('EE native forwarder requires an owned bounded single-link regular file')
        with os.fdopen(fd,'rb',closefd=False) as stream:image=stream.read(64*1024**2+1)
        after=os.fstat(fd)
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mode,s.st_uid,s.st_nlink,s.st_mtime_ns,s.st_ctime_ns)
        if identity(before)!=identity(after) or identity(after)!=identity(path.lstat()) or len(image)!=before.st_size:
            raise ValueError('EE native forwarder changed during read')
    finally:os.close(fd)
    if image[:6]!=b'\x7fELF\x02\x01' or image[18:20]!=b'\xb7\x00':
        raise ValueError('EE native forwarder requires AArch64 ELF64 LE')
    phoff=struct.unpack_from('<Q',image,32)[0];phsize,phnum=struct.unpack_from('<HH',image,54)
    segments=[struct.unpack_from('<IIQQQQQQ',image,phoff+i*phsize) for i in range(phnum)]
    descriptor=sealed_snapshot(image,'a7c2-ee-native-forwarder')
    try:
        with pinned_tool_environment(payload,'ee-pins-tmp') as (environment,temp_fd):
            symbols=subprocess.run(['readelf','-Ws','/proc/self/fd/'+str(descriptor)],capture_output=True,text=True,check=True,timeout=10,pass_fds=(descriptor,temp_fd),env=environment).stdout
    finally:os.close(descriptor)
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
    raw=('static const struct ee_native_export ee_native_exports[]={\n'+row+'\n};\n'
        'static const struct ee_native_contract ee_native_pins={"/simulation/menu-observe.so",'
        +str(len(image))+',"'+hashlib.sha256(image).hexdigest()+'",1,ee_native_exports};\n').encode('ascii')
    fd=os.open(header,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    if header.read_bytes()!=raw:raise ValueError('EE native pins readback differs')
    return header,raw


def inspect_ee_input(declared):
    """Validate and snapshot the external EE header without creating build output."""
    if not declared:raise ValueError('EE cold profile requires an external private input header path')
    path=Path(declared)
    if (not path.is_absolute() or declared!=str(path) or str(path).startswith('//') or str(path)!=os.path.normpath(str(path)) or
            any(ord(char)<32 or ord(char)==127 or char in '\\"' for char in str(path)) or
            any(path==Path(root) or path.is_relative_to(root) for root in ('/tmp','/var/tmp','/dev','/proc','/sys','/run')) or
            any(parent.is_symlink() for parent in (path,*path.parents))):
        raise ValueError('EE cold private input must be an absolute regular non-symlink project file outside host temporary paths')
    if path.is_relative_to(PRODUCT):raise ValueError('EE cold private input must stay outside the public product tree')
    ancestors=[]
    for parent in path.parents:
        info=parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022):
            raise ValueError('EE cold private input parent must be a trusted non-writable directory')
        ancestors.append((str(parent),(info.st_dev,info.st_ino,info.st_mode,info.st_uid)))
    try:fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
    except OSError as error:raise ValueError('EE cold private input must be a regular non-symlink file') from error
    try:
        before=os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or
                before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_size>1024**2):
            raise ValueError('EE cold private input must be an owned single-link 0600 regular file')
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(1024**2+1)
        after=os.fstat(fd)
        identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mode,s.st_uid,s.st_nlink,s.st_mtime_ns,s.st_ctime_ns)
        if len(data)!=before.st_size or identity(before)!=identity(after) or identity(after)!=identity(path.lstat()):
            raise ValueError('EE cold private input changed during read')
    finally:os.close(fd)
    if (b'#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1\n' not in data or b'ee_nwc_prepared_assets' not in data
            or b'ee_cold_adc' not in data or b'#define EE_COLD_ADMISSION_SOURCE ' not in data):
        raise ValueError('EE cold private input lacks the hash-bound adapter contract')
    return dict(path=str(path),identity=identity(before),ancestors=ancestors,
                sha256=hashlib.sha256(data).hexdigest(),content=data)


def ee_normal_cold(current,payload):
    """Explicit opt-in EE NormalWake cold adapter inputs; default off, external private header only."""
    enabled=current.get('A7C2_USB_EE_NORMAL_COLD');declared=current.get('A7C2_USB_EE_NORMAL_COLD_INPUT')
    if enabled is None:
        if declared is not None:raise ValueError('EE cold private input supplied without the explicit profile')
        return None
    if enabled!='1':raise ValueError('Unknown explicit EE cold observer profile')
    private_input=inspect_ee_input(declared)
    pins,pins_content=ee_native_pins(payload)
    return dict(defines=['-DUSB_EE_NORMAL_COLD=1','-D_REENTRANT','-I',str(PRODUCT/'source/usb-device')],
                 compiled=('ee-normal-wake-cold.c','ee-capability-input.c'),sources=EE_COLD_SOURCES,
                 helpers={'usb-ee-native-pins.h':pins},pins_content=pins_content,private_input=private_input)


def prepare_private_libraries(payload, *, verify_sha=True):
    """Snapshot protected link inputs once; retain the receipt and partial failures."""
    payload=build_output_directory(payload)
    if payload.is_relative_to(ANALYSIS):
        runtime=PRODUCT/'runtime';runtime_info=runtime.lstat()
        if (runtime.resolve(strict=True)!=runtime or not stat.S_ISDIR(runtime_info.st_mode) or
                runtime_info.st_uid!=os.geteuid() or runtime_info.st_mode&0o022):
            raise ValueError('USB observer runtime parent must be an owned non-writable directory')
        private_parent=runtime/'observer-private-inputs'
        private_parent.mkdir(mode=0o700,exist_ok=True)
        info=private_parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or
                stat.S_IMODE(info.st_mode)!=0o700):
            raise ValueError('USB observer private parent must be an owned mode 0700 directory')
        private=Path(tempfile.mkdtemp(prefix='build-',dir=private_parent))
    else:
        private=payload/'observer-inputs'
        private.mkdir(mode=0o700)
    intent=(json.dumps({'private':str(private),'state':'snapshot-pending'},sort_keys=True)+'\n').encode()
    fd=os.open(payload/'observer-inputs-intent.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(intent);stream.flush();os.fsync(stream.fileno())
    if (payload/'observer-inputs-intent.json').read_bytes()!=intent:
        raise ValueError('USB observer intent readback differs')
    spec=importlib.util.spec_from_file_location('usb_observer_private_inputs',PRODUCT/'source/cp-boot/observer_private_inputs.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    receipt=module.snapshot_libraries(ANALYSIS,private,verify_sha=verify_sha)
    proof={'private_input_receipt':str(private/'library-inputs.json'),
           'sha256':sha(private/'library-inputs.json'),
           'next_consumer':'cold audit and USB observer build review and reference-checked cleanup'}
    raw=(json.dumps(proof,sort_keys=True)+'\n').encode()
    fd=os.open(payload/'observer-inputs-proof.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    if (payload/'observer-inputs-proof.json').read_bytes()!=raw:
        raise ValueError('Observer input proof readback differs')
    libraries=[private/'lib'/name for name in module.LIBRARIES]
    return private,receipt,libraries,proof['sha256']


def verify_private_libraries(private_inputs):
    private,receipt,libraries,receipt_sha=private_inputs
    if type(receipt) is not dict or not isinstance(receipt.get('base_initramfs_sha256'),str):
        raise ValueError('Invalid observer private input receipt')
    info=private.lstat();library_dir=(private/'lib').lstat();proof=(private/'library-inputs.json').lstat()
    names=('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o700 or
            not stat.S_ISDIR(library_dir.st_mode) or library_dir.st_uid!=os.geteuid() or
            stat.S_IMODE(library_dir.st_mode)!=0o700 or
            not stat.S_ISREG(proof.st_mode) or proof.st_uid!=os.geteuid() or proof.st_nlink!=1 or
            stat.S_IMODE(proof.st_mode)!=0o600 or receipt.get('schema')!='a7c2-observer-private-libraries-v1' or
            receipt.get('physical_compatible') is not False or
            re.fullmatch('[0-9a-f]{64}',receipt.get('base_initramfs_sha256','')) is None or
            set(receipt.get('libraries',{}))!={'lib/'+name for name in names} or
            libraries!=[private/'lib'/name for name in names] or
            sha(private/'library-inputs.json')!=receipt_sha or
            json.loads((private/'library-inputs.json').read_bytes())!=receipt):
        raise ValueError('Observer private input receipt or directory changed')
    for path in libraries:
        info=path.lstat();expected=receipt['libraries']['lib/'+path.name]['sha256']
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or
                stat.S_IMODE(info.st_mode)!=0o600 or sha(path)!=expected):
            raise ValueError('Observer private library changed during compilation: '+path.name)


@contextmanager
def pinned_tool_environment(parent,name):
    if name not in ('ee-pins-tmp','tool-tmp'):raise ValueError('Unknown observer temporary directory')
    parent=build_output_directory(parent)
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    directory=os.open('/',flags)
    try:
        for part in parent.parts[1:]:
            child=os.open(part,flags,dir_fd=directory)
            os.close(directory);directory=child
            info=os.fstat(directory)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,os.geteuid()) or info.st_mode&0o022):
                raise ValueError('Observer tool ancestor is not trusted')
        try:os.mkdir(name,mode=0o700,dir_fd=directory)
        except FileExistsError:pass
        try:fd=os.open(name,flags,dir_fd=directory)
        except OSError as error:raise ValueError('Observer tool temporary directory is not private') from error
        try:
            info=os.fstat(fd);named=os.stat(name,dir_fd=directory,follow_symlinks=False)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.geteuid() or
                    stat.S_IMODE(info.st_mode)!=0o700 or (info.st_dev,info.st_ino)!=(named.st_dev,named.st_ino)):
                raise ValueError('Observer tool temporary directory is not private')
            temporary='/proc/self/fd/'+str(fd)
            yield {**os.environ,'TMPDIR':temporary,'TMP':temporary,'TEMP':temporary},fd
        finally:os.close(fd)
    finally:os.close(directory)


@contextmanager
def private_tool_environment(private_inputs):
    verify_private_libraries(private_inputs)
    with pinned_tool_environment(private_inputs[0],'tool-tmp') as environment:
        yield environment


def sealed_snapshot(data,name):
    if not isinstance(data,bytes):raise ValueError('Sealed input must be bytes')
    descriptor=os.memfd_create(name,os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    try:
        view=memoryview(data)
        while view:
            count=os.write(descriptor,view)
            if count<=0:raise ValueError('Sealed input snapshot write failed')
            view=view[count:]
        os.lseek(descriptor,0,os.SEEK_SET)
        if os.read(descriptor,len(data)+1)!=data:raise ValueError('Sealed input snapshot readback differs')
        seals=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
        fcntl.fcntl(descriptor,fcntl.F_ADD_SEALS,seals)
        if fcntl.fcntl(descriptor,fcntl.F_GET_SEALS)&seals!=seals:
            raise ValueError('Input snapshot was not sealed')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


@contextmanager
def sealed_link_libraries(private_inputs):
    verify_private_libraries(private_inputs)
    _private,receipt,libraries,_receipt_sha=private_inputs
    descriptors=[]
    try:
        for path in libraries:
            fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
            try:
                before=os.fstat(fd)
                if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.geteuid() or
                        before.st_nlink!=1 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_size>16*1024**2):
                    raise ValueError('Observer private library identity is unsafe: '+path.name)
                with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(16*1024**2+1)
                after=os.fstat(fd)
                identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mode,s.st_uid,s.st_nlink,s.st_mtime_ns,s.st_ctime_ns)
                if (len(data)!=before.st_size or identity(before)!=identity(after) or
                        hashlib.sha256(data).hexdigest()!=receipt['libraries']['lib/'+path.name]['sha256']):
                    raise ValueError('Observer private library changed during snapshot: '+path.name)
            finally:os.close(fd)
            descriptors.append(sealed_snapshot(data,'a7c2-observer-'+path.name))
        yield [f'/proc/self/fd/{fd}' for fd in descriptors],tuple(descriptors)
    finally:
        for fd in descriptors:os.close(fd)


def prepare_observer(current,payload,*,private_inputs=None):
    from usb_scheduler import enabled as scheduler_enabled
    scheduler=scheduler_enabled(current)
    if not selected(current):return {}
    source=PRODUCT/'source/usb-device';payload=Path(payload);target=payload/'usb-start-observe.so'
    cold=ee_normal_cold(current,payload)
    inputs={name:sha(source/name) for name in ('usb-start-observe.c','usb-msc-sender.inc','usb-resources-observe.inc','usb-start-observe.map',*(cold['sources'] if cold else ()))}
    if private_inputs is None:private_inputs=prepare_private_libraries(payload)
    verify_private_libraries(private_inputs)
    with sealed_link_libraries(private_inputs) as (link_paths,link_fds):
        command=['clang','--target=aarch64-linux-gnu','-DUSB_RESOURCE_OBSERVE=1',
                 *(['-DUSB_MSC_SCHEDULER_OBSERVE=1'] if scheduler else []),*(cold['defines'] if cold else ()),
                 '--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-O2','-mno-outline-atomics','-shared','-fPIC',
                 '-Wl,--no-undefined','-Wl,-z,now','-Wl,--version-script='+str(source/'usb-start-observe.map'),
                 str(source/'usb-start-observe.c'),*([str(source/name) for name in cold['compiled']] if cold else []),
                 *link_paths,'-o',str(target)]
        descriptor=None;pins_descriptor=None
        try:
            if cold:
                descriptor=sealed_snapshot(cold['private_input']['content'],'a7c2-ee-private-input')
                pins_descriptor=sealed_snapshot(cold['pins_content'],'a7c2-ee-native-pins')
                command.insert(1,'-DUSB_EE_NORMAL_COLD_INPUT="/proc/self/fd/'+str(descriptor)+'"')
                command.insert(1,'-DUSB_EE_NATIVE_INPUT="/proc/self/fd/'+str(pins_descriptor)+'"')
            with private_tool_environment(private_inputs) as (environment,temp_fd):
                result=subprocess.run(command,capture_output=True,
                                      pass_fds=link_fds+(temp_fd,)+(() if descriptor is None else (descriptor,pins_descriptor)),
                                      env=environment)
        finally:
            if pins_descriptor is not None:os.close(pins_descriptor)
            if descriptor is not None:os.close(descriptor)
    (payload/'usb-observer-build.log').write_bytes(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('USB passive observer original-ABI build failed')
    if cold:
        item=cold['private_input'];path=Path(item['path']);info=path.lstat()
        identity_now=(info.st_dev,info.st_ino,info.st_size,info.st_mode,info.st_uid,info.st_nlink,info.st_mtime_ns,info.st_ctime_ns)
        for parent,expected in item['ancestors']:
            ancestor=Path(parent).lstat()
            if (not stat.S_ISDIR(ancestor.st_mode) or
                    (ancestor.st_dev,ancestor.st_ino,ancestor.st_mode,ancestor.st_uid)!=expected):
                raise ValueError('EE cold private input ancestor changed during compilation')
        if identity_now!=item['identity'] or sha(path)!=item['sha256']:
            raise ValueError('EE cold private input changed during compilation')
        pins=Path(cold['helpers']['usb-ee-native-pins.h']);info=pins.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or
                stat.S_IMODE(info.st_mode)!=0o600 or sha(pins)!=hashlib.sha256(cold['pins_content']).hexdigest()):
            raise ValueError('EE native pins changed during compilation')
    verify_private_libraries(private_inputs)
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
    from single_ap_sockets import roots_for_run
    roots=roots_for_run(run,environment)
    endpoints=run if roots is None else roots.sockets
    context=dict(run_id=run.name,qmp_path=str(endpoints/'usb-qmp.sock'),backend_path=str(endpoints/'usb-endpoint.sock'),lease=environment['QEMU_SONY_USB_LEASE'],vm_pid=peer)
    if roots is not None:
        binding=roots.binding()
        context.update(socket_root=str(roots.sockets),socket_profile=binding['profile'],socket_binding=binding)
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
