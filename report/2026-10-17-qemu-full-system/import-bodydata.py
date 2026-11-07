#!/usr/bin/env python3
"""Validate and safely extract a pinned official BODYDATA into a private cache.

No extracted code is executed. Symlinks are metadata, not host filesystem links.
This is the official-package import phase; it does not claim camera startup.
"""
import argparse
import binascii
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import sys
import tarfile
import tempfile

HERE=Path(__file__).resolve().parent
MAGIC=b'\x89UFU\r\n\x1a\n'
INPUT_SHA='eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'
PLAIN_SHA='03eee07301010ff644fae1073f7c7f6dd2d60278f18aa3e6053938d5f1426d1f'
HEADER_SHA='ee176eb36cadf11d0f9d02f0829121352fa9d5804932a33831764618c23e8c5e'
KEY_DER_SHA='be79b3323d7d92dff52175fc6d12825d73cfc68c32e4fcbca5c7d36fc04bdf10'
VENDOR_SHA='0d4f3b72a0360f5b61124064bd939ba2201563520368eec3798c0b19834fa9b2'
ASSETS_SHA='de1bf7a985dcad90f58e11f874732af1a0594f6a34daae21fe89d9d953da1c61'
UPDATER_SHA='788db9cdfb38edc171686b07635efea397279c303cef49308d8303601d0dcf0e'
UPDATER_BYTES=1253376
INPUT_BYTES=1139929560
DIGEST_INFO=bytes.fromhex('3031300d060960864801650304020105000420')
_vendor_stage=None


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def canonical_json(data):return json.dumps(data,sort_keys=True,separators=(',',':')).encode()


def ordinary(path):
    if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('Expected ordinary file: '+str(path))
    return path


def cache_path(root,name):
    path=root
    for part in relative(name).split('/'):
        path=path/part
        if path.is_symlink():raise ValueError('Host symlink in original cache path: '+name)
    return path


def readonly_mounts(rows):
    inventory={r['path']:r for r in rows}
    image_names=(('rootfs','nflasha7','ext2','/'),('usr','nflasha15','ext2','/usr'),
                 ('system','nflasha3','fat','/system'),('cp','nflasha8','fat','/cp'))
    images=[];mounts=[]
    for label,part,fs,guest in image_names:
        name='0700_part_image/dev/'+part
        images.append({'id':label,'file':'firmware/'+name,'fs':fs,'sha256':inventory[name]['sha256'],
                       'source_class':'sony_official','read_only':True})
        mounts.append({'guest':guest,'image':label,'read_only':True})
    return {'schema':1,'scope':'readonly input filesystems; writable runtime volumes still required',
            'images':images,'mounts':mounts}


def relative(name):
    if not isinstance(name,str) or not name or name.startswith('/') or '\\' in name:
        raise ValueError('Unsafe payload path: '+repr(name))
    name.encode('utf-8')
    if any(p in ('','.','..') or ':' in p or any(ord(c)<32 or ord(c)==127 for c in p) for p in name.split('/')):
        raise ValueError('Unsafe payload components: '+repr(name))
    return name


def discover(directory):
    if directory.is_symlink() or not directory.is_dir():raise ValueError('Input directory must be an ordinary directory')
    candidates=[]
    for path in sorted(directory.iterdir()):
        if not stat.S_ISREG(path.lstat().st_mode):continue
        with path.open('rb') as stream:
            if stream.read(8)==MAGIC:candidates.append(path)
    if len(candidates)!=1:raise ValueError(f'Expected one ordinary UFU BODYDATA file, found {len(candidates)}')
    return candidates[0]


def chunks(source):
    source.seek(0,2);total=source.tell();source.seek(0)
    if source.read(8)!=MAGIC:raise ValueError('Not a Sony UFU container')
    result={};offset=8
    while offset<total and len(result)<64:
        source.seek(offset);raw=source.read(8)
        if len(raw)!=8:raise ValueError('Truncated UFU chunk header')
        size,kind=struct.unpack('>I4s',raw);start=offset+8;end=start+size
        if kind in result or end>total:raise ValueError('Duplicate/out-of-bounds UFU chunk')
        result[kind]=(start,size);offset=end
        if kind==b'DEND':break
    if set(result)!={b'DATV',b'PROV',b'UDID',b'FDAT',b'DEND'} or offset!=total or result[b'DEND'][1]!=4:
        raise ValueError('Unsupported or incomplete UFU chunk layout')
    for kind in (b'DATV',b'PROV'):
        if result[kind][1]!=4:raise ValueError('Invalid UFU version chunk')
    source.seek(result[b'DATV'][0]);version,lens=struct.unpack('>HH',source.read(4))
    source.seek(result[b'PROV'][0]);protocol=struct.unpack('>H',source.read(2))[0]
    if (version,lens,protocol)!=(0x100,0,0x100):raise ValueError('Unsupported body/update protocol')
    start,size=result[b'UDID'];source.seek(start);count=struct.unpack('>I',source.read(4))[0]
    if count>4096 or size!=4+8*count:raise ValueError('Invalid USB descriptor list')
    return total,result


def public_key():
    try:RSA=importlib.import_module('Cryptodome.PublicKey.RSA')
    except ImportError:
        try:RSA=importlib.import_module('Crypto.PublicKey.RSA')
        except ImportError as error:raise RuntimeError('Install pycryptodomex in the isolated application Python environment') from error
    key=RSA.import_key((HERE/'keys/sony-update-public.pem').read_bytes())
    if key.has_private() or key.size_in_bits()!=2048 or key.e!=65537 or hashlib.sha256(key.export_key(format='DER')).hexdigest()!=KEY_DER_SHA:
        raise ValueError('Pinned Sony public verification key differs')
    return key


def verify_rsa(key,hashed,signature):
    size=key.size_in_bytes()
    if len(hashed)!=32 or len(signature)!=size or int.from_bytes(signature,'big')>=key.n:return False
    encoded=pow(int.from_bytes(signature,'big'),key.e,key.n).to_bytes(size,'big')
    info=DIGEST_INFO+hashed
    return encoded==b'\0\x01'+b'\xff'*(size-len(info)-3)+b'\0'+info


def inspect(source,key):
    total,parts=chunks(source);fd_offset,fd_bytes=parts[b'FDAT']
    if fd_bytes<272 or (fd_bytes-272)%1024:raise ValueError('Unsupported encrypted FDAT/IV/signature geometry')
    signed_end=fd_offset+fd_bytes-256;crc_end=parts[b'DEND'][0]-8
    full=hashlib.sha256();signed=hashlib.sha256();crc=0;offset=0;source.seek(0)
    while data:=source.read(8*1024**2):
        full.update(data)
        lo=max(0,fd_offset-offset);hi=min(len(data),signed_end-offset)
        if lo<hi:signed.update(data[lo:hi])
        count=min(len(data),max(0,crc_end-offset))
        if count:crc=binascii.crc32(data[:count],crc)
        offset+=len(data)
    source.seek(parts[b'DEND'][0]);expected=struct.unpack('>I',source.read(4))[0]
    if crc&0xffffffff!=expected:raise ValueError('UFU outer CRC mismatch')
    source.seek(signed_end);signature=source.read(256)
    if not verify_rsa(key,signed.digest(),signature):raise ValueError('Sony RSA-SHA256 signature invalid')
    if total!=INPUT_BYTES or full.hexdigest()!=INPUT_SHA:
        raise ValueError('Signed payload is not the supported ILCE-7CM2 2.01 package; do not use unvalidated runtime offsets')
    return {'bytes':total,'sha256':full.hexdigest(),'outer_crc_valid':True,'rsa_sha256_valid':True,
            'key_der_sha256':KEY_DER_SHA,'signed_sha256':signed.hexdigest()}


def vendor(root,modules=('fwtool.sony.dat','fwtool.sony.fdat')):
    global _vendor_stage
    if _vendor_stage is not None:
        return tuple(importlib.import_module(name) for name in modules)
    package=root/'fwtool'
    files={}
    for path in sorted(package.rglob('*.py')):
        ordinary(path)
        if any(parent.is_symlink() for parent in path.parents if parent==root or parent.is_relative_to(root)):
            raise ValueError('Symlink in supplied fwtool sources')
        files[path.relative_to(root).as_posix()]=digest(path)
    if hashlib.sha256(canonical_json(files)).hexdigest()!=VENDOR_SHA:raise ValueError('Expected the pinned complete fwtool source tree')
    if any(name=='fwtool' or name.startswith('fwtool.') for name in sys.modules):raise ValueError('Another fwtool is already imported')
    _vendor_stage=tempfile.TemporaryDirectory(prefix='a7c2-verified-fwtool-')
    copied=Path(_vendor_stage.name)
    # Import verified .py sources only: no untrusted pyc/native module beside them.
    for name,expected in files.items():
        destination=copied/name;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(root/name,destination)
        if digest(destination)!=expected:raise ValueError('fwtool source changed during snapshot')
    sys.path.insert(0,str(copied));sys.dont_write_bytecode=True
    return tuple(importlib.import_module(name) for name in modules)


def copy_bounded(source,target,limit):
    hashed=hashlib.sha256();count=0
    with target.open('xb') as output:
        while block:=source.read(1024**2):
            count+=len(block)
            if count>limit:raise ValueError('Decrypted/payload stream exceeds its declared bound')
            output.write(block);hashed.update(block)
        output.flush();os.fsync(output.fileno())
    return count,hashed.hexdigest()


def extract_tar(filepart,destination,expected_inventory_sha=ASSETS_SHA):
    rows=[];seen=set();links=set();total=0
    with tarfile.open(fileobj=filepart,mode='r|') as archive:
        for entry in archive:
            name=relative(entry.name)
            if name in seen or len(seen)>=100000:raise ValueError('Duplicate/oversized payload inventory')
            if any(str(p) in links for p in PurePosixPath(name).parents):raise ValueError('Payload descends through a guest symlink')
            seen.add(name)
            if entry.isdir():kind='dir'
            elif entry.isfile() and not entry.sparse:kind='file'
            elif entry.issym():kind='symlink'
            else:raise ValueError('Unsupported link/special/sparse tar member: '+name)
            if entry.size<0 or entry.size>2*1024**3:raise ValueError('Oversized tar member')
            total+=entry.size
            if total>2*1024**3:raise ValueError('Payload exceeds explicit extraction budget')
            row={'path':name,'type':kind,'size':entry.size,'mode':entry.mode,'uid':entry.uid,'gid':entry.gid,'mtime':int(entry.mtime)}
            target=destination/name
            if kind=='dir':target.mkdir(parents=True,exist_ok=True)
            elif kind=='file':
                target.parent.mkdir(parents=True,exist_ok=True)
                actual,hashed=copy_bounded(archive.extractfile(entry),target,entry.size)
                if actual!=entry.size:raise ValueError('Truncated tar member: '+name)
                row['sha256']=hashed
            else:
                if len(entry.linkname.encode())>4096 or '\0' in entry.linkname:raise ValueError('Invalid guest symlink target')
                links.add(name);row['target']=entry.linkname
            rows.append(row)
    rows.sort(key=lambda row:row['path'])
    if hashlib.sha256(canonical_json(rows)).hexdigest()!=expected_inventory_sha:raise ValueError('Complete Sony payload inventory does not match supported package')
    return rows


def verify_cache(output):
    if output.is_symlink():raise ValueError('Cache must not be a symlink')
    report=json.loads(ordinary(output/'bodydata-manifest.json').read_text())
    if (report.get('schema'),report.get('model'),report.get('version'),report.get('region'))!=(1,'ILCE-7CM2','2.01',0) or \
       report.get('input',{}).get('sha256')!=INPUT_SHA or not report['input'].get('rsa_sha256_valid') or \
       report['input'].get('key_der_sha256')!=KEY_DER_SHA:
        raise ValueError('Unsupported cache provenance')
    rows=report['assets']
    if hashlib.sha256(canonical_json(rows)).hexdigest()!=ASSETS_SHA:raise ValueError('Cache inventory changed')
    for row in rows:
        name=relative(row['path']);path=cache_path(output,'firmware/'+name)
        if row['type']=='file':
            ordinary(path)
            if path.stat().st_size!=row['size'] or digest(path)!=row['sha256']:raise ValueError('Cached original changed: '+name)
        elif row['type']=='symlink' and os.path.lexists(path):raise ValueError('Guest link was materialized on host')
        elif row['type']=='dir' and not path.is_dir():raise ValueError('Cached directory missing: '+name)
    if digest(ordinary(output/'firmware.fdat'))!=PLAIN_SHA:raise ValueError('Cached FDAT changed')
    updater=ordinary(output/'updater.squashfs')
    if updater.stat().st_size!=UPDATER_BYTES or digest(updater)!=UPDATER_SHA:raise ValueError('Cached updater changed')
    if json.loads(ordinary(output/'mounts-readonly.json').read_text())!=readonly_mounts(rows):raise ValueError('Original mount inventory changed')
    allowed={'firmware.fdat','updater.squashfs','bodydata-manifest.json','mounts-readonly.json','IMPORT-COMPLETE'}|{
        'firmware/'+r['path'] for r in rows if r['type']=='file'}
    allowed_dirs={'firmware'}|{'firmware/'+r['path'] for r in rows if r['type']=='dir'}
    for name in allowed:
        allowed_dirs.update(str(p) for p in PurePosixPath(name).parents if str(p)!='.')
    for parent,dirs,files in os.walk(output,followlinks=False):
        if any((Path(parent)/name).is_symlink() for name in dirs+files):raise ValueError('Unexpected host link in cache')
        if any((Path(parent)/name).relative_to(output).as_posix() not in allowed_dirs for name in dirs):
            raise ValueError('Unexpected directory contaminates original cache')
        for name in files:
            if (Path(parent)/name).relative_to(output).as_posix() not in allowed:raise ValueError('Unexpected file contaminates original cache')
    ready=ordinary(output/'IMPORT-COMPLETE').read_text().strip()
    if ready!=digest(output/'bodydata-manifest.json'):raise ValueError('Incomplete cache commit')
    return report


def import_package(source_path,output,fwtool):
    ordinary(source_path);key=public_key()
    print('BODYDATA_IMPORT_PHASE verify-input',flush=True)
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
    with os.fdopen(os.open(source_path,flags),'rb') as source:
        before=os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode):raise ValueError('BODYDATA must be an ordinary file')
        verified=inspect(source,key)
        if output.exists():return verify_cache(output)
        output.parent.mkdir(parents=True,exist_ok=True)
        if shutil.disk_usage(output.parent).free<3*verified['bytes']+64*1024**2:raise OSError('Insufficient import staging space')
        dat,fdat=vendor(fwtool)
        stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'-',dir=output.parent))
        try:
            container=dat.readDat(source)
            print('BODYDATA_IMPORT_PHASE decrypt-verified-payload',flush=True)
            name,plaintext=fdat.decryptFdat(container.firmwareData)
            if name!='CXD90057_k8':raise ValueError('Unexpected platform decrypter: '+name)
            count,hashed=copy_bounded(plaintext,stage/'firmware.fdat',2*verified['bytes'])
            if hashed!=PLAIN_SHA:raise ValueError('Decrypted FDAT bytes differ from supported package')
            with (stage/'firmware.fdat').open('rb') as clear:
                header=clear.read(512)
                if hashlib.sha256(header).hexdigest()!=HEADER_SHA:raise ValueError('FDAT identity header mismatch')
                parts=fdat.readFdat(clear)
                if (parts.model,parts.region,parts.version)!=(0x20030014,0,'2.01'):raise ValueError('Wrong model/region/version')
                for part in (parts.fs,parts.firmware):
                    if part.offset<512 or part.offset+part.size>count:raise ValueError('FDAT section outside plaintext')
                if max(parts.fs.offset,parts.firmware.offset)<min(parts.fs.offset+parts.fs.size,parts.firmware.offset+parts.firmware.size):
                    raise ValueError('Overlapping FDAT sections')
                updater_size,updater_sha=copy_bounded(parts.fs,stage/'updater.squashfs',parts.fs.size)
                if updater_size!=UPDATER_BYTES or updater_sha!=UPDATER_SHA:raise ValueError('Updater section mismatch')
                (stage/'firmware').mkdir();rows=extract_tar(parts.firmware,stage/'firmware')
            print('BODYDATA_IMPORT_PHASE verify-full-asset-inventory',flush=True)
            after=os.fstat(source.fileno())
            if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                raise ValueError('BODYDATA changed during import')
            report={'schema':1,'model':'ILCE-7CM2','version':'2.01','region':0,'input':verified,
                    'fdat':{'size':count,'sha256':hashed,'header_sha256':HEADER_SHA,'decrypter':name,'block_checksums_valid':True,'header_crc_valid':True},
                    'updater':{'size':updater_size,'sha256':updater_sha},'assets':rows,'asset_inventory_sha256':ASSETS_SHA,
                    'guest_links_materialized_on_host':False,'camera_startup_verified':False,'vendor_source_sha256':VENDOR_SHA,
                    'importer_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
            for filename,data in (('bodydata-manifest.json',report),('mounts-readonly.json',readonly_mounts(rows))):
                with (stage/filename).open('x') as stream:
                    stream.write(json.dumps(data,indent=2,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
            with (stage/'IMPORT-COMPLETE').open('x') as stream:
                stream.write(digest(stage/'bodydata-manifest.json')+'\n');stream.flush();os.fsync(stream.fileno())
            verify_cache(stage)  # Independent filesystem readback before publication.
            for parent,dirs,files in os.walk(stage):
                for filename in files:(Path(parent)/filename).chmod(0o400)
            fd=os.open(stage,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(fd)
            finally:os.close(fd)
            if os.path.lexists(output):raise ValueError('Refusing concurrently created output')
            stage.rename(output);stage=None
            fd=os.open(output.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(fd)
            finally:os.close(fd)
            print('BODYDATA_IMPORT_PHASE imported-not-yet-booted',flush=True)
            return report
        except Exception as error:
            # Keep failure artifacts local, with no success marker.
            if stage is not None:
                (stage/'IMPORT-COMPLETE').unlink(missing_ok=True)
                (stage/'import-failure.json').write_text(json.dumps({'error':str(error),'input':verified},indent=2)+'\n')
                print('BODYDATA_IMPORT_FAILED_STAGING',stage,file=sys.stderr,flush=True)
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,default=Path('bodydata'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--fwtool',type=Path,default=HERE/'runtime/vendor/fwtool')
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    if args.check:
        if args.output is None:parser.error('--check requires --output')
        report=verify_cache(args.output)
    else:
        source=discover(args.input_dir)
        output=args.output or HERE/'runtime/bodydata'/INPUT_SHA
        report=import_package(source,output,args.fwtool.resolve())
    print(json.dumps({'model':report['model'],'version':report['version'],'input_sha256':report['input']['sha256'],
                      'rsa_valid':report['input']['rsa_sha256_valid'],'assets':len(report['assets']),
                      'camera_startup_verified':False},indent=2))


if __name__=='__main__':main()
