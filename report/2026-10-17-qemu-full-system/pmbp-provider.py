#!/usr/bin/env python3
"""Relocatable fixed-p23 broker provider. No VM, image IO, crypto replacement or driver edits.
The production input is the already verified current leased_launch binding; this
module never opens a disk and never accepts a target path, key or adoption fd.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from contextlib import contextmanager
import fcntl
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess

HERE=Path(__file__).resolve().parent
PROFILE='virtual-p1-pmbp-block-slice-v1'
OFFSET=1831862272
SIZE=67108864
DISK_BYTES=1962934272
MODULE_SHA='8aaea09a134293c7f5b498346abca60937c9fdffa27ff6fc579c65618a19f293'
MEDIA_SHA='efd05f06c69a29dcd6c6383e9c7fc1aec6642834ee2a9ccdaa23da662a1d57ec'
FSYS_SHA='ba0467674b056b3389a34ba974b1f0bbe99f4189d8aa36ad509843596ccacb62'
BODY_SHA='d9a4945ac5760d820b6e10a91aa95380392f81be50960510706251ca87b13de4'
NATIVES=('open64','__fxstat64','close','write','pwrite64','pread64','ioctl','read','lseek64','dup','dup2','dup3','fcntl','pwritev64','fsync')
ORIGIN={'disk':'host-provisioned: current instance + same lease/OFD + exact process/env/binary',
        'offset':'host-provisioned geometry + source-derived frozen host core selector/add-offset code',
        'node':'source-derived independent gendisk selector23/minor151 + runtime sysfs dev/uevent + owned block rdev',
        'capacity_readonly':'runtime-blockquery: BLKGETSIZE64 / BLKROGET',
        'module':'host exact artifact + actual bootstrap insmod rc + /proc/modules Live + sysfs parameters/kernel release',
        'module_memory_sha':'unknown', 'hardware_attestation':'not claimed'}

def sha(b): return hashlib.sha256(b).hexdigest()
def secure(path: Path, *, root_only=False):
    path=path.absolute()
    for p in [*reversed(path.parents),path]:
        s=p.lstat()
        if stat.S_ISLNK(s.st_mode) or s.st_mode&0o022 or s.st_uid not in (0,os.geteuid()):
            raise ValueError('Unsafe checked path: '+str(p))
    s=path.stat()
    if root_only and (s.st_uid!=os.geteuid() or stat.S_IMODE(s.st_mode)!=0o700):
        raise ValueError('Checked root must be owner-only 0700')
    return path

_STAMP=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')
_SOURCE_NAMES=('pmbp-candidate.c','pmbp-candidate.h','pmbp-libc.h','pmbp-broker.h',
    'pmbp-broker.c','pmbp-interpose.c','pmbp-bootstrap.c','pmbp-provider.py',
    'pmbp-integration.py','closure-source-check.py','pmbp-frozen-pins.json','p1-update-execution.py')


def _safe_stat(s):
    if s.st_mode&0o022 or s.st_uid not in (0,os.geteuid()):raise ValueError('Unsafe asset ownership/mode')


@contextmanager
def checked_directory(path):
    """Walk pinned directory descriptors; recheck the whole named ancestry on exit."""
    path=Path(path).absolute()
    if '..' in path.parts:raise ValueError('Parent traversal is forbidden')
    descriptors=[];links=[]
    try:
        fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);descriptors.append(fd)
        _safe_stat(os.fstat(fd))
        for name in path.parts[1:]:
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
            descriptors.append(child);s=os.fstat(child);_safe_stat(s)
            links.append((fd,name,child,s));fd=child
        yield fd
        for parent,name,child,before in links:
            current=os.fstat(child);named=os.stat(name,dir_fd=parent,follow_symlinks=False)
            _safe_stat(current);_safe_stat(named)
            if not stat.S_ISDIR(named.st_mode) or any(getattr(before,k)!=getattr(current,k) or getattr(current,k)!=getattr(named,k) for k in ('st_dev','st_ino','st_mode','st_uid','st_gid')):
                raise ValueError('Asset ancestor changed')
    finally:
        for fd in reversed(descriptors):os.close(fd)


@contextmanager
def _asset_fd(path):
    path=Path(path).absolute()
    if path.name=='camera.emmc':raise ValueError('Provider never reads instance disk data')
    with checked_directory(path.parent) as parent:
        fd=os.open(path.name,os.O_RDONLY|os.O_CLOEXEC|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
        try:
            before=os.fstat(fd);_safe_stat(before)
            if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise ValueError('Not an independent regular code asset')
            yield path,fd,before
            after=os.fstat(fd);named=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
            _safe_stat(after);_safe_stat(named)
            if not stat.S_ISREG(named.st_mode) or after.st_nlink!=1 or named.st_nlink!=1 or any(getattr(before,k)!=getattr(after,k) or getattr(after,k)!=getattr(named,k) for k in _STAMP):
                raise ValueError('Code asset changed: '+str(path))
        finally:os.close(fd)


def hash_descriptor(fd, expected, *, sink=None):
    """The procfs exe caller must authenticate dev/ino and PID separately."""
    if type(expected.get('bytes')) is not int or expected['bytes']<0 or not re.fullmatch('[0-9a-f]{64}',expected.get('sha256','')):raise ValueError('Expected artifact size/SHA required')
    before=os.fstat(fd);_safe_stat(before)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_size!=expected['bytes']:raise ValueError('Bound artifact type/size differs')
    h=hashlib.sha256();count=0
    while True:
        block=os.read(fd,256*1024)
        if not block:break
        count+=len(block)
        if count>before.st_size:raise ValueError('Artifact grew while hashing')
        h.update(block)
        if sink is not None:sink(block)
    after=os.fstat(fd)
    if count!=before.st_size or h.hexdigest()!=expected['sha256'] or after.st_nlink!=1 or any(getattr(before,k)!=getattr(after,k) for k in _STAMP):raise ValueError('Bound artifact changed')
    return before


def stream_asset(row, *, sink=None):
    with _asset_fd(row['path']) as (path,fd,before):
        verified=hash_descriptor(fd,row,sink=sink)
    return dict(path=str(path),bytes=verified.st_size,sha256=row['sha256']),verified


def original(path, expected=None):
    with _asset_fd(path) as (path,fd,before):
        if before.st_size>16*1024*1024:raise ValueError('Not a bounded independent code asset: '+str(path))
        chunks=[];remaining=before.st_size
        while remaining:
            block=os.read(fd,min(256*1024,remaining))
            if not block:raise ValueError('Short code asset')
            chunks.append(block);remaining-=len(block)
        if os.read(fd,1):raise ValueError('Code asset grew')
        data=b''.join(chunks);digest=sha(data)
        if expected and digest!=expected:raise ValueError('Asset hash differs: '+str(path))
    return dict(path=str(path),bytes=len(data),sha256=digest),data

@dataclass(frozen=True)
class Manifest:
    generation:int
    lease_epoch:int
    disk_dev:int
    disk_ino:int
    disk_bytes:int
    offset:int
    bytes:int
    selector:int
    instance_sha:str
    geometry_sha:str
    parent_profile_sha:str
    source_sha:str
    module_sha:str
    hostcore_sha:str
    driver_sha:str
    bootstrap_sha:str
    module_bytes:int
    parent_pid:int
    parent_starttime:int
    vermagic:str
    def wire(self):
        ints=(self.generation,self.lease_epoch,self.disk_dev,self.disk_ino,self.disk_bytes,self.offset,self.bytes,self.selector)
        if any(type(x) is not int or not 0<x<2**64 for x in ints): raise ValueError('Invalid typed manifest integer')
        if (self.disk_bytes,self.offset,self.bytes,self.selector)!=(DISK_BYTES,OFFSET,SIZE,23):raise ValueError('Only fixed p23 is supported')
        hashes=[self.instance_sha,self.geometry_sha,self.parent_profile_sha,self.source_sha,self.module_sha,self.hostcore_sha,self.driver_sha,self.bootstrap_sha]
        if any(not re.fullmatch('[0-9a-f]{64}',x) or x=='0'*64 for x in hashes):raise ValueError('Unknown manifest SHA')
        for x in (self.module_bytes,self.parent_pid,self.parent_starttime):
            if type(x) is not int or not 0<x<2**64:raise ValueError('Missing current parent/module identity')
        v=self.vermagic.encode('ascii')
        if not v or len(v)>=128 or b'\0' in v:raise ValueError('Invalid vermagic')
        b=struct.pack('<8sII8Q',b'PMBPBR01',1,1,*ints)+b''.join(bytes.fromhex(x) for x in hashes)+struct.pack('<3Q128s',self.module_bytes,self.parent_pid,self.parent_starttime,v)
        assert len(b)==488
        return b

@dataclass(frozen=True)
class CheckedLease:
    """Produced from canonical existing contexts, not serialized booleans."""
    manifest:Manifest
    proof:dict

def process_starttime(pid):
    text=Path(f'/proc/{pid}/stat').read_text();return int(text[text.rfind(')')+2:].split()[19])

def from_build_checked(checked_root, *, leased, lock, module_receipt, core_source,
                       driver_source, qemu, build_inputs, profile_contract, instance_wire, reviewed_sources):
    """Build from present resources only; parent fields are build provenance.

    No final root/CPIO, launch binding or future child exists at this point.
    Activation must independently reacquire and authenticate the actual lease.
    """
    reviewed=_check_reviewed_sources(reviewed_sources)
    _check_p1_lock(leased,lock)
    root=secure(Path(checked_root));fd=leased['fd'];st=os.fstat(fd)
    state=leased['state'];geometry=leased['geometry']
    rows=[r for r in geometry['slices'] if r['id']=='nflasha23']
    if len(rows)!=1 or (rows[0]['offset'],rows[0]['bytes'])!=(OFFSET,SIZE):raise ValueError('Fixed p23 lease geometry differs')
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size!=DISK_BYTES:raise ValueError('Fixed canonical disk differs')
    for name,value in [('instance.json',state),('geometry.json',geometry)]:
        row,data=original(Path(leased['path'])/name)
        if json.loads(data)!=value:raise ValueError('Canonical lease metadata differs: '+name)
        if name=='geometry.json' and row['sha256']!=state['geometry_sha256']:raise ValueError('Canonical geometry SHA differs')
    inputs={}
    for want in build_inputs:
        row,_=stream_asset(want)
        if row['path'] in inputs:raise ValueError('Duplicate build input')
        inputs[row['path']]=row
    if inputs.get(reviewed['path'])!=reviewed:raise ValueError('Reviewed source record missing from build inputs')
    code=[]
    for path in (core_source,driver_source,qemu['path'],instance_wire['path']):
        want=inputs.get(str(Path(path).absolute()))
        if want is None:raise ValueError('Present build input missing: '+str(path))
        row,_=stream_asset(want)
        code.append(row)
    if any(code[2][k]!=qemu[k] or code[3][k]!=instance_wire[k] for k in ('bytes','sha256')):raise ValueError('QEMU/wire build identity differs')
    frozen=json.loads((HERE/'pmbp-frozen-pins.json').read_text())
    if (code[0]['sha256'],code[1]['sha256'])!=(frozen['hostcore'],frozen['driver']):raise ValueError('Unreviewed core/module selector source')
    module_path=root/'simulation/sony_persistent_flash.ko';module,data=original(module_path,MODULE_SHA)
    receipt_module=module_receipt.get('module',{}).get('file',{})
    if module_receipt.get('status')!='compiled' or any(receipt_module.get(k)!=module[k] for k in ('bytes','sha256')):
        raise ValueError('Frozen canonical module build receipt differs')
    if not any(json.loads(original(r['path'])[1])==module_receipt for r in build_inputs if Path(r['path']).suffix=='.json'):
        raise ValueError('Module receipt is not one of the independently read build inputs')
    from elftools.elf.elffile import ELFFile
    with module_path.open('rb') as f:
        info=ELFFile(f).get_section_by_name('.modinfo').data()
    values=[x[9:].decode() for x in info.split(b'\0') if x.startswith(b'vermagic=')]
    if len(values)!=1:raise ValueError('Module vermagic missing')
    bundle=source_bundle();parent_pid=os.getpid();parent_start=process_starttime(parent_pid)
    material=json.dumps(dict(generation=state['generation'],source=state['source_manifest_sha256'],
        build_pid=parent_pid,build_starttime=parent_start,disk=[st.st_dev,st.st_ino,st.st_size],
        binary=code[2],inputs=list(inputs.values())),sort_keys=True,separators=(',',':')).encode()
    epoch=int.from_bytes(hashlib.sha256(material).digest()[:8],'little') or 1
    m=Manifest(state['generation'],epoch,st.st_dev,st.st_ino,st.st_size,OFFSET,SIZE,23,
        state['source_manifest_sha256'],instance_wire['sha256'],sha(json.dumps(profile_contract,sort_keys=True).encode()),
        bundle['sha256'],MODULE_SHA,code[0]['sha256'],code[1]['sha256'],original(HERE/'pmbp-bootstrap.c')[0]['sha256'],
        module['bytes'],parent_pid,parent_start,values[0])
    m.wire()
    checked=CheckedLease(m,dict(origin=ORIGIN,binary=code[2],build_inputs=list(inputs.values()),
        profile_contract=profile_contract,instance_wire=code[3],reviewed_sources=reviewed,build_provenance_only=True,image_io=False))
    _CAPABILITIES[id(checked)]=checked
    return checked


def from_prelaunch_checked(*args,**kwargs):
    raise TypeError('Use from_build_checked: final launch inputs must not authorize pre-CPIO build')


_LOCKS={}


def _flock_witness(path):
    target=Path(path).stat()
    for entry in Path('/proc/self/fd').iterdir():
        try:
            fd=int(entry.name);s=os.fstat(fd)
            if (s.st_dev,s.st_ino)!=(target.st_dev,target.st_ino):continue
            text=Path(f'/proc/self/fdinfo/{fd}').read_text()
            device=f'{os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino}'
            if any('FLOCK' in r and 'WRITE' in r and str(os.getpid()) in r and device in r and r[-2:]==['0','EOF']
                   for r in (line.split() for line in text.splitlines() if line.startswith('lock:'))):
                return fd,(s.st_dev,s.st_ino)
        except (FileNotFoundError,OSError,ValueError):continue
    raise OSError(95,'P1 canonical exclusive flock is not held by this process')


def _check_p1_lock(leased,token):
    proof=_LOCKS.get(token)
    if proof is None or proof['pid']!=(os.getpid(),process_starttime(os.getpid())):raise ValueError('Live P1 lock capability required')
    root=secure(Path(leased['path']));fd=leased['fd'];s=os.fstat(fd)
    disk=(root/'camera.emmc').stat()
    if (fd,s.st_dev,s.st_ino,s.st_size)!=proof['disk'] or (disk.st_dev,disk.st_ino)!=(s.st_dev,s.st_ino):raise ValueError('Canonical P1 descriptor changed')
    if _flock_witness(root/'.disk.lock')!=proof['flock']:raise ValueError('P1 flock ownership changed')
    ofd_receipt(fd)
    return proof


@contextmanager
def p1_ofd_lease(leased):
    """Only inside camera-disk.lease; acquire a real second lock on its same FD."""
    root=secure(Path(leased['path']));flock=_flock_witness(root/'.disk.lock')
    fd=leased['fd'];s=os.fstat(fd);disk=(root/'camera.emmc').stat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or (s.st_dev,s.st_ino)!=(disk.st_dev,disk.st_ino):raise ValueError('Not canonical leased camera.emmc')
    try:ofd_receipt(fd)
    except OSError:pass
    else:raise ValueError('Existing OFD lock has a different ownership contract')
    fcntl.fcntl(fd,fcntl.F_OFD_SETLK,struct.pack('hhqqi4x',fcntl.F_WRLCK,os.SEEK_SET,0,0,0))
    token=object();_LOCKS[token]=dict(pid=(os.getpid(),process_starttime(os.getpid())),
        disk=(fd,s.st_dev,s.st_ino,s.st_size),flock=flock)
    try:
        _check_p1_lock(leased,token)
        yield token
    finally:
        _LOCKS.pop(token,None)
        now=os.fstat(fd)
        if (now.st_dev,now.st_ino)!=(s.st_dev,s.st_ino):raise ValueError('P1 descriptor replaced before OFD release')
        fcntl.fcntl(fd,fcntl.F_OFD_SETLK,struct.pack('hhqqi4x',fcntl.F_UNLCK,os.SEEK_SET,0,0,0))

_CAPABILITIES={}
_SOURCE_CONTEXTS={}


@dataclass(frozen=True)
class ReviewedSources:
    record:dict


def source_freeze(record):
    """External reviewed row is a build input; never embed its SHA in its sources."""
    row,data=original(record['path'],record['sha256'])
    if row['bytes']!=record['bytes'] or Path(row['path']).parent==HERE:raise ValueError('Independent reviewed source record required')
    freeze=json.loads(data)
    if set(freeze)!={'schema','sources'} or freeze['schema']!='pmbp-reviewed-sources-v1' or set(freeze['sources'])!=set(_SOURCE_NAMES):raise ValueError('Fixed complete source set required')
    for name,want in freeze['sources'].items():
        if set(want)!={'bytes','sha256'}:raise ValueError('Unexpected source row fields')
        stream_asset(dict(path=str(HERE/name),**want))
    return row


def reviewed_sources(record):
    row=source_freeze(record);context=ReviewedSources(row)
    _SOURCE_CONTEXTS[id(context)]=(context,os.getpid(),process_starttime(os.getpid()))
    return context


def _check_reviewed_sources(context):
    if type(context) is not ReviewedSources or _SOURCE_CONTEXTS.get(id(context))!=(context,os.getpid(),process_starttime(os.getpid())):raise TypeError('Live explicitly reviewed source context required')
    return source_freeze(context.record)

def ofd_receipt(fd, pid=None):
    text=Path(f'/proc/{pid or os.getpid()}/fdinfo/{fd}').read_text();st=os.fstat(fd)
    device=f'{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}'
    rows=[r.split() for r in text.splitlines() if r.startswith('lock:')]
    if not any('OFDLCK' in r and 'WRITE' in r and '-1' in r and device in r and r[-2:]==['0','EOF'] for r in rows):
        raise OSError(95,'Current inherited whole-disk OFD WRITE lease unavailable')
    return text

def activation_checked(*args,**kwargs):
    raise TypeError('Use integration.prepare_actual and integration.activate_paused; build parent is provenance only')

def from_current_lease(*args,**kwargs):
    raise TypeError('Use from_prelaunch_checked before build, then activation_checked in the existing launcher')

class Elf:
    def __init__(self,path):
        from elftools.elf.elffile import ELFFile
        self.path=Path(path);self.row,self.raw=original(path)
        with self.path.open('rb') as f:
            e=ELFFile(f);self.machine=e['e_machine'];self.symbols={s.name:(s['st_value'],s['st_size']) for s in e.get_section_by_name('.dynsym').iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
            self.imports=[s.name for s in e.get_section_by_name('.dynsym').iter_symbols() if s['st_shndx']=='SHN_UNDEF' and s.name]
            self.loads=[(s['p_vaddr'],s['p_offset'],s['p_filesz']) for s in e.iter_segments() if s['p_type']=='PT_LOAD']
            self.text=e.get_section_by_name('.text');self.text_va=self.text['sh_addr'];self.text_data=self.text.data()
            self.plt={};pl=e.get_section_by_name('.plt');rel=e.get_section_by_name('.rela.plt')
            if pl and rel:
                sy=e.get_section(rel['sh_link']);stride=16
                for i,r in enumerate(rel.iter_relocations()):self.plt[pl['sh_addr']+(i+1 if self.machine=='EM_X86_64' else i+2)*stride]=sy.get_symbol(r['r_info_sym']).name
    def bytes(self,va,n):
        for base,off,size in self.loads:
            if base<=va and va+n<=base+size:return self.raw[off+va-base:off+va-base+n]
        raise ValueError('Code not file-backed')
    def calls(self):
        import capstone
        md=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_LITTLE_ENDIAN) if self.machine=='EM_AARCH64' else capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
        for x in md.disasm(self.text_data,self.text_va):
            if x.mnemonic not in ('bl','call'):continue
            try:target=int(x.op_str.lstrip('#'),16)
            except ValueError:continue
            if target in self.plt:yield x.address+x.size,self.plt[target],x.address

def source_bundle(output=None):
    """Stream the same fixed source inventory into the guest bundle and its digest."""
    h=hashlib.sha256();count=0
    def consume(block):
        nonlocal count
        count+=len(block);h.update(block)
        if output is not None:output.write(block)
    for name in _SOURCE_NAMES:
        consume(name.encode()+b'\0')
        with _asset_fd(HERE/name) as (_,fd,before):
            while True:
                block=os.read(fd,256*1024)
                if not block:break
                consume(block)
        consume(b'\0')
    return dict(bytes=count,sha256=h.hexdigest())

def pin_header(out, manifest, *, files, required, windows, natives, receiver, module, synthetic=False):
    """Only source/code/manifest compiler pins; no post-link self hash cycle."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    def array(b):return '{'+','.join(str(x) for x in b)+'}'
    def pathstr(p):return json.dumps(str(p))
    lines=['/* Generated exact code/manifest pins, recompile on every manifest change. */','/* Manifest parent_pid/starttime identify the build process, not an actual-launch lease. */','#ifndef PMBP_PINS_H','#define PMBP_PINS_H',
           '#define PMBP_DL_VERSION '+pathstr('GLIBC_2.2.5' if synthetic else 'GLIBC_2.17'),
           '#define PMBP_RECEIVER_PATH '+pathstr(receiver[0]),'#define PMBP_RECEIVER_COMM '+pathstr(receiver[1]+'\n'),
           '#define PMBP_MODULE_PATH '+pathstr(module),f'#define PMBP_SOURCE_BYTES {source_bundle()["bytes"]}u']
    for n,h in [('manifest',sha(manifest.wire())),('source',manifest.source_sha),('module',manifest.module_sha),('hostcore',manifest.hostcore_sha),('driver',manifest.driver_sha),('bootstrap',manifest.bootstrap_sha)]:
        lines.append(f'static const unsigned char pmbp_{n}_sha[32]='+array(bytes.fromhex(h))+';')
    lines.append('static const struct pmbp_file_pin pmbp_files[]={'+','.join('{'+pathstr(e.row['path'])+','+str(e.row['bytes'])+','+array(bytes.fromhex(e.row['sha256']))+'}' for e in files)+'};')
    allpins={};audit={}
    for group,rows in [('required',required),('windows',windows),('native_pins',natives)]:
        rendered=[];audit[group]=[]
        for i,(file,symbol,va,size,caller,role) in enumerate(rows):
            e=files[file];symbol_va=e.symbols[symbol][0];raw=e.bytes(va,size);name=f'pmbp_{group}_{i}'
            lines.append(f'static const unsigned char {name}[]='+array(raw)+';')
            rendered.append('{'+pathstr(symbol)+f',{file},{symbol_va},{va},{size},{caller},{role},{name}'+'}')
            audit[group].append(dict(file=e.row['path'],symbol=symbol,va=va,bytes=size,caller=caller,role=role,sha256=sha(raw),raw=raw.hex()))
        if not rendered:raise ValueError('Missing '+group+' pins')
        allpins[group]='static const struct pmbp_window_pin pmbp_'+group+'[]={'+','.join(rendered)+'};'
    lines+=list(allpins.values())+['#endif','']
    (out/'pmbp-pins.h').write_text('\n'.join(lines))
    (out/'manifest.bin').write_bytes(manifest.wire());(out/'manifest.bin').chmod(0o600)
    (out/'profile').write_text(PROFILE+'\n');(out/'profile').chmod(0o600)
    with (out/'source.bundle').open('xb') as bundle:
        if source_bundle(bundle)['sha256']!=manifest.source_sha:raise ValueError('Source bundle changed during build')
    (out/'source.bundle').chmod(0o600)
    (out/'manifest.json').write_text(json.dumps(dict(schema='pmbp-runtime-broker-v1',profile=PROFILE,**asdict(manifest),parent_identity_role='build-provenance-only-not-actual-lease-attestation',origins=ORIGIN,synthetic=synthetic),indent=2)+'\n')
    (out/'compiled-pins.json').write_text(json.dumps(dict(manifest_sha=sha(manifest.wire()),files=[e.row for e in files],**audit),indent=2)+'\n')
    return audit

def production_pins(checked_root, checked_lease:CheckedLease, output):
    root=secure(Path(checked_root));m=checked_lease.manifest
    media=Elf(root/'usr/lib/libInfraMediaCommon.so');fsys=Elf(root/'usr/lib/libInfraFsys.so');body=Elf(root/'tmp_updater/updater/bodyfs/bodylib/libupdaterbody.so')
    for e,h in zip((media,fsys,body),(MEDIA_SHA,FSYS_SHA,BODY_SHA)):
        if e.row['sha256']!=h or e.machine!='EM_AARCH64':raise ValueError('Original full-file ELF identity differs')
    # Guest absolute identities, independent of the host checkedRoot path.
    libc=Elf(root/'lib/libc-2.25.so');pthread=Elf(root/'lib/libpthread-2.25.so')
    crypto=Elf(root/'usr/lib/libcrypto.so.1.1')
    if crypto.row['sha256']!='df69906d5f63a3afe9b7872e41cab741c346630e53ebcaadb86e457f0b803726':raise ValueError('Original SHA256 provider differs')
    files=[media,fsys,body,libc,pthread,crypto]
    required=[]
    for i,n in [(5,'SHA256'),(4,'pthread_mutex_lock'),(4,'pthread_mutex_unlock'),(0,'mcmn_drv_open'),(0,'mcmn_drv_getinfo'),(0,'mcmn_drv_dummy_open'),(0,'mcmn_init'),(1,'Fsys_Format'),(1,'fsysDep_LockDevice'),(1,'fsysDep_UnlockDevice'),(1,'fsysDepMCmn_Open')]:
        va,size=files[i].symbols[n];required.append((i,n,va,size,0,0))
    fsysopen=[x for x in required if x[1]=='fsysDepMCmn_Open'][0]
    if sha(fsys.bytes(fsysopen[2],fsysopen[3]))!='9e4424e9fe0e4e512fd77d7bb16432076cddd4b05ecb0496ce24965056f78340':raise ValueError('Fsys 616B source pin differs')
    windows=[(0,'mcmn_init',0x21948,32,0x2195c,0),(0,'mcmn_init',0x219f0,40,0x21a08,1),(0,'mcmn_init',0x34eb0,32,0x34ec0,2),(1,'Fsys_Format',0x4162c,92,0x4165c,101),(1,'Fsys_Format',0x4799c,616,0x47a48,102)]
    op={'read':4,'pread64':5,'lseek64':6,'close':7,'pwritev64':9,'fsync':10,'ioctl':11}
    for pc,name,call in media.calls():
        if name in op:windows.append((0,'mcmn_init',call,4,pc,op[name]))
    for pc,name,call in body.calls():
        if name=='Fsys_Format':windows.append((2,'_ZN7Updater11FsysWrapper6FormatEPKc',0x1aec0,164,pc,100))
    natives=[(3,n,libc.symbols[n][0],min(libc.symbols[n][1],64),0,0) for n in NATIVES]
    natives += [(4,n,pthread.symbols[n][0],min(pthread.symbols[n][1],64),0,0) for n in ('pthread_mutex_lock','pthread_mutex_unlock')]
    # Preserve host audit paths while compile paths bind the original guest namespace.
    for e in files:e.row['path']='/'+str(Path(e.row['path']).relative_to(root))
    audit=pin_header(output,m,files=files,required=required,windows=windows,natives=natives,receiver=('/usr/bin/sdfileinput.elf','sdfileinput.elf'),module='/simulation/sony_persistent_flash.ko')
    coverage={e.row['path']:dict(imports=e.imports,plt_calls=[dict(pc=pc,symbol=n,call=call) for pc,n,call in e.calls()]) for e in (media,fsys,body)}
    (Path(output)/'consumer-coverage.json').write_text(json.dumps(dict(source=coverage,runtime_consumed=False,mediated=['pwritev64: once then per-positive-segment same-offset native pread','fsync: original return/errno','ioctl: owned BLKGETSIZE64/BLKROGET only; other owned requests poison ENOTSUP'],unused=['dummy callback/direct BL source reachability recorded separately','mmap/direct syscall p23 exclusion requires p23-source-coverage.json'],formatter=False,mount=False,receiver=False),indent=2)+'\n')
    return audit

def guest_build(root,output):
    """Small AA64 link against the checked original 2.25 libraries; no fixtures."""
    root=Path(root);out=Path(output)
    cc=['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fuse-ld=lld','-nostdlib','-std=c11','-D_GNU_SOURCE','-DPMBP_BROKER','-fno-builtin','-fPIC','-fno-stack-protector','-mno-outline-atomics','-fno-omit-frame-pointer','-fno-optimize-sibling-calls','-O2','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-I',str(HERE),'-I',str(out),'-Wl,--no-undefined']
    libs=[str(root/n) for n in ('lib/libc-2.25.so','lib/libdl-2.25.so','lib/ld-2.25.so','lib/libpthread-2.25.so','usr/lib/libcrypto.so.1.1')]
    commands=[cc+['-shared','-Wl,-soname,broker.so',*[str(HERE/n) for n in ('pmbp-candidate.c','pmbp-broker.c','pmbp-interpose.c')],*libs,'-o',str(out/'broker.so')],
              cc+['-Wl,-e,main','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1','-Wl,-rpath,/simulation/pmbp-runtime',str(HERE/'pmbp-bootstrap.c'),str(out/'broker.so'),*libs,'-o',str(out/'bootstrap')]]
    # Entry must initialize glibc before main; compile an explicit crt entry below.
    entry=out/'bootstrap-entry.S'
    entry.write_text('.text\n.global _start\n_start:\n mov x29,xzr\n mov x30,xzr\n mov x5,x0\n ldr x1,[sp]\n add x2,sp,#8\n mov x6,sp\n adrp x0,main\n add x0,x0,:lo12:main\n mov x3,xzr\n mov x4,xzr\n bl __libc_start_main\n bl abort\n')
    commands[1][commands[1].index('-Wl,-e,main')]='-Wl,-e,_start'
    commands[1].insert(-2,str(entry))
    for i,cmd in enumerate(commands):
        p=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (out/f'link-{i}.log').write_text(p.stdout)
        if p.returncode:raise RuntimeError('Guest 2.25 link failed: '+p.stdout[-4000:])
    (out/'broker.so').chmod(0o600);(out/'bootstrap').chmod(0o700)
    result={}
    for n in ('broker.so','bootstrap','manifest.bin','profile','source.bundle','pmbp-pins.h'):
        # Output is compiler-owned; compute its row with bounded chunks and stable fd identity.
        with _asset_fd(out/n) as (_,fd,before):
            h=hashlib.sha256();count=0
            while True:
                block=os.read(fd,256*1024)
                if not block:break
                h.update(block);count+=len(block)
            if count!=before.st_size:raise ValueError('Compiler output changed')
        result[n]=dict(bytes=count,sha256=h.hexdigest(),mode=stat.S_IMODE(before.st_mode))
    return result

def selection(profile=None):
    if profile not in (None,PROFILE):raise ValueError('Only OFF or fixed p23 profile')
    return profile

def build_candidate(checked_root,manifest:CheckedLease,output,*,profile=None):
    """Generate reviewable sources/pins, never modify checkedRoot or launch anything."""
    selection(profile)
    if profile is None:return {'profile':None,'preload':[],'functional_loaded':False}
    if type(manifest) is not CheckedLease or _CAPABILITIES.get(id(manifest)) is not manifest:raise TypeError('Live prelaunch checked lease is required')
    output=Path(output);production_pins(checked_root,manifest,output)
    assets=guest_build(checked_root,output)
    return dict(assets=assets,profile=PROFILE,preload=['/simulation/pmbp-runtime/broker.so'],runtime_root='/simulation/pmbp-runtime',manifest_sha=sha(manifest.manifest.wire()),origins=ORIGIN,applied=False,production_consumer_coverage=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--checked-root',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    # A serialized manifest alone cannot replace the live canonical lease proof.
    raise SystemExit('ENOTSUP: use build_candidate from the current canonical leased_launch context; manifest JSON alone cannot authorize the persistent resource')
