#!/usr/bin/env python3
"""Apply guest-root overwrite/ paths to private image copies, with tree readback.

This builds emulator images, not Sony-signed update packages. Ext2 and VFAT
modifications are supported; untouched images of other types are copied
byte-for-byte. A touched unsupported filesystem fails before publication rather
than hiding an override.

VFAT work needs an explicit host mtools directory and explicit fmask/dmask: the
guest mounts /setting, /system, /cp, /tmp with posix_attr and no masks, so
conventional entries are interpreted with the observed 022 mount umask instead
of the host's umask. Sony POSIX-extended entries keep their own mode/owner.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile


def _fat_module():
    path=Path(__file__).resolve().parent/'fat_image.py'
    spec=importlib.util.spec_from_file_location('a7c2_fat_image',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def canonical(value):
    if not isinstance(value,str) or not value.startswith('/'):
        raise ValueError('Expected guest absolute path')
    parts=value.split('/')[1:]
    if value=='/':return value
    if any(not p or p in ('.','..') for p in parts):raise ValueError('Noncanonical guest path: '+value)
    quote(value)
    return value


def quote(value):
    # libss/debugfs is not a shell, but still has its own command parser.
    # Reject control/separator/escape characters rather than guessing its quoting.
    value=str(value)
    if any(ord(c)<32 or ord(c)==127 or c in '\\";:' for c in value):
        raise ValueError('Unsupported command/path characters: '+repr(value))
    return '"'+value+'"'


def ordinary(path):
    if not stat.S_ISREG(path.lstat().st_mode):raise ValueError('Expected ordinary image/file: '+str(path))
    return path


class Ext2:
    def __init__(self,path,scratch,max_file_bytes=4*1024**3):
        self.path=Path(path);self.scratch=Path(scratch);self.max_file_bytes=max_file_bytes

    def command(self,text,write=False):
        argv=['debugfs',*(['-w'] if write else []),'-R',text,str(self.path)]
        result=subprocess.run(argv,capture_output=True,text=True,timeout=120)
        errors='\n'.join(l for l in result.stderr.splitlines() if not re.match(r'^debugfs \d',l)).strip()
        if result.returncode or errors:
            raise RuntimeError(f'debugfs command failed: {text}: {errors or result.stdout}')
        return result.stdout

    def inode_stat(self,inode):
        text=self.command(f'stat <{int(inode)}>')
        flags=re.search(r'Flags:\s*(0x[0-9a-fA-F]+)',text)
        acl=re.search(r'File ACL:\s*(\d+)',text)
        if not flags or not acl:raise ValueError('Unknown debugfs inode stat format')
        return text,int(flags[1],16),int(acl[1])

    def dump(self,inode,size):
        if size<0 or size>self.max_file_bytes:raise ValueError(f'File exceeds explicit audit bound: {size}')
        if shutil.disk_usage(self.scratch).free<size+16*1024**2:
            raise OSError('Insufficient space for independent image readback')
        target=self.scratch/'inode-readback.bin';target.unlink(missing_ok=True)
        self.command(f'dump <{int(inode)}> {quote(target)}')
        ordinary(target)
        if target.stat().st_size!=size:raise ValueError('Short/oversized image readback')
        return target

    def inventory(self):
        entries={};inodes={};visited=set();pending=[('/',2)]
        root_text,root_flags,root_acl=self.inode_stat(2)
        root_meta=re.search(r'Mode:\s*([0-7]+).*?User:\s*(\d+)\s+Group:\s*(\d+)',root_text,re.S)
        if not root_meta:raise ValueError('Unknown root metadata')
        entries['/']={'kind':'dir','mode':stat.S_IFDIR|int(root_meta[1],8),'uid':int(root_meta[2]),'gid':int(root_meta[3]),'flags':root_flags,'acl':root_acl}
        while pending:
            parent,inode=pending.pop()
            if inode in visited:raise ValueError('Directory inode cycle/alias in image')
            visited.add(inode)
            for line in self.command(f'ls -p <{inode}>').splitlines():
                if not line.strip():continue
                fields=line.split('/')
                if len(fields)!=8 or fields[0] or fields[-1]:raise ValueError('Unsafe/unrecognized directory record')
                ino,mode,uid,gid,name,size=fields[1:-1]
                if int(ino)==0:continue  # Unused directory slot, common in lost+found.
                if name in ('.','..'):continue
                path=canonical(parent.rstrip('/')+'/'+name)
                if path in entries or len(entries)>=200000:raise ValueError('Duplicate/oversized image tree')
                ino,mode,uid,gid=int(ino),int(mode,8),int(uid),int(gid)
                text,flags,acl=self.inode_stat(ino)
                owner=re.search(r'User:\s*(\d+)\s+Group:\s*(\d+)',text)
                if not owner:raise ValueError('Missing full inode ownership')
                uid,gid=int(owner[1]),int(owner[2])
                node={'mode':mode,'uid':uid,'gid':gid,'flags':flags,'acl':acl}
                kind=stat.S_IFMT(mode)
                if kind==stat.S_IFDIR:
                    node['kind']='dir';pending.append((path,ino))
                elif kind==stat.S_IFREG:
                    count=int(size);readback=self.dump(ino,count)
                    node.update(kind='file',size=count,sha256=digest(readback));readback.unlink()
                elif kind==stat.S_IFLNK:
                    count=int(size)
                    if count>4096:raise ValueError('Symlink exceeds guest pathname limit')
                    fast=re.search(r'^Fast link dest: "(.*)"$',text,re.M)
                    if fast:target=fast[1]
                    else:
                        readback=self.dump(ino,count);target=readback.read_text();readback.unlink()
                    quote(target)
                    node.update(kind='symlink',target=target)
                else:
                    node['kind']='special'
                    device=next((l for l in text.splitlines() if l.startswith('Device major/minor number:')),None)
                    if device:node['device']=device
                entries[path]=node
                if kind!=stat.S_IFDIR:inodes.setdefault(ino,[]).append(path)
        links=sorted(sorted(paths) for paths in inodes.values() if len(paths)>1)
        return {'entries':entries,'hardlinks':links}

    def attributes(self,path,node):
        for field,value in (('mode','0'+format(node['mode'],'o')),('uid',node['uid']&65535),
                            ('gid',node['gid']&65535),('uid_hi',node['uid']>>16),('gid_hi',node['gid']>>16)):
            self.command(f'set_inode_field {quote(path)} {field} {value}',write=True)

    def apply(self,operation):
        path=operation['path'];before=operation['before'];after=operation['after']
        if after['kind']=='dir':
            if before:return
            self.command('mkdir '+quote(path),write=True)
        else:
            if before:self.command('rm '+quote(path),write=True)
            if after['kind']=='file':
                self.command(f'write {quote(operation["snapshot"])} {quote(path)}',write=True)
            else:self.command(f'symlink {quote(path)} {quote(after["target"])}',write=True)
        self.attributes(path,after)

    def fsck(self):
        result=subprocess.run(['e2fsck','-f','-n',str(self.path)],capture_output=True,text=True,timeout=120)
        if result.returncode:raise RuntimeError('Derived filesystem failed e2fsck: '+result.stdout+result.stderr)


class Fat:
    """Thin adapter so VFAT images satisfy the same inventory/apply/fsck shape."""

    def __init__(self,path,scratch,mtools_dir,fmask,dmask,default_uid=1000,default_gid=1000,
                 allow_zero_padding=True,rodir=False):
        if not mtools_dir:raise ValueError('VFAT backend requires an explicit mtools directory')
        module=_fat_module()
        self.image=module.FatImage(path,scratch,mtools_dir=mtools_dir,fmask=fmask,dmask=dmask,
            default_uid=default_uid,default_gid=default_gid,allow_zero_padding=allow_zero_padding,
            rodir=rodir)
        self.tools=Path(mtools_dir)

    def inventory(self):
        return self.image.inventory()

    def apply(self,operation):
        return self.image.apply(operation)

    def fsck(self):
        return self.image.fsck()

    def close(self):
        self.image.close()


def scan_overlay(root,snapshot):
    if not root.exists():return []
    if root.is_symlink() or not root.is_dir():raise ValueError('overwrite must be an ordinary directory')
    result=[];pending=[root]
    while pending:
        parent=pending.pop()
        if parent.is_symlink() or not parent.resolve().is_relative_to(root.resolve()):
            raise ValueError('Overlay directory changed into a host symlink')
        for source in sorted(parent.iterdir()):
            rel=source.relative_to(root).as_posix();canonical('/'+rel)
            info=source.lstat();item={'guest_path':'/'+rel,'source':rel,'source_mode':stat.S_IMODE(info.st_mode)}
            if stat.S_ISDIR(info.st_mode):item['kind']='dir';pending.append(source)
            elif stat.S_ISLNK(info.st_mode):
                target=os.readlink(source);quote(target)
                stack=[] if target.startswith('/') else rel.split('/')[:-1]
                for part in target.split('/'):
                    if part in ('','.'):continue
                    if part=='..':
                        if not stack:raise ValueError('Overlay symlink escapes guest root: '+rel)
                        stack.pop()
                    else:stack.append(part)
                item.update(kind='symlink',target=target)
            elif stat.S_ISREG(info.st_mode):
                copy_path=snapshot/str(len(result))
                flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
                with os.fdopen(os.open(source,flags),'rb') as reader,copy_path.open('xb') as writer:
                    before=os.fstat(reader.fileno());shutil.copyfileobj(reader,writer,1024**2);after=os.fstat(reader.fileno())
                if (before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_size,after.st_mtime_ns,after.st_ctime_ns):
                    raise ValueError('Overlay source changed while snapshotting: '+rel)
                item.update(kind='file',size=copy_path.stat().st_size,sha256=digest(copy_path),snapshot=str(copy_path))
            else:raise ValueError('Special files are forbidden in overwrite: '+rel)
            result.append(item)
    return sorted(result,key=lambda entry:(len(PurePosixPath(entry['guest_path']).parts),entry['guest_path']))


def load_config(path):
    config=json.loads(path.read_text());images={};mounts=[]
    if config.get('schema')!=1:raise ValueError('Unsupported mount manifest schema')
    for image in config['images']:
        name=image['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',name) or name in images:raise ValueError('Unsafe/duplicate image id')
        file=Path(image['file']);file=file if file.is_absolute() else path.parent/file
        ordinary(file)
        if image.get('sha256') is not None and digest(file)!=image['sha256']:
            raise ValueError('Pinned base image digest differs: '+name)
        images[name]={**image,'file':file.resolve()}
    for mount in config['mounts']:
        guest=canonical(mount['guest']);root=canonical(mount.get('root','/'))
        if mount['image'] not in images or any(m['guest']==guest for m in mounts):raise ValueError('Unknown image/duplicate mount')
        mounts.append({**mount,'guest':guest,'image':mount['image'],'root':root})
    if not mounts:raise ValueError('No guest mounts')
    return images,sorted(mounts,key=lambda m:len(m['guest']),reverse=True)


def locate(guest,mounts):
    for mount in mounts:
        prefix=mount['guest']
        if prefix=='/' or guest==prefix or guest.startswith(prefix+'/'):
            tail=guest[len(prefix):].lstrip('/')
            return mount['image'],canonical(mount['root'].rstrip('/')+'/'+tail) if tail else mount['root']
    raise ValueError('Guest path has no image mapping: '+guest)


def build(config_path,overwrite,output=None,dry_run=False,mtools_dir=None,vfat_fmask=None,
          vfat_dmask=None,vfat_uid=1000,vfat_gid=1000,vfat_allow_zero_padding=True):
    config_path=Path(config_path).resolve();overwrite=Path(overwrite).absolute()
    images,mounts=load_config(config_path)
    if not dry_run:
        output=Path(output).absolute()
        if os.path.lexists(output):raise ValueError('Output must not exist')
        parent=output.parent.resolve();parent.mkdir(parents=True,exist_ok=True)
        if parent==overwrite.resolve() or parent.is_relative_to(overwrite.resolve()):raise ValueError('Output must be outside overwrite')
        if any(output.resolve()==i['file'] or output.resolve() in i['file'].parents for i in images.values()):
            raise ValueError('Output overlaps source images')
        needed=sum(i['file'].stat().st_size for i in images.values())+32*1024**2
        if shutil.disk_usage(parent).free<needed:raise OSError('Insufficient space for independent derived images')
    else:parent=None
    with tempfile.TemporaryDirectory(prefix='a7c2-overwrite-input-') as temporary:
        scratch=Path(temporary);snapshot=scratch/'overlay';snapshot.mkdir()
        sources=scan_overlay(overwrite,snapshot)
        planned=[];seen={};touched=set()
        for source in sources:
            name,path=locate(source['guest_path'],mounts)
            if path=='/' and source['kind']=='dir':continue
            key=(name,path)
            if key in seen:
                if source['kind']==seen[key]['kind']=='dir' and source['source_mode']==seen[key]['source_mode']:continue
                raise ValueError('Alias collision between overwrite paths: '+seen[key]['guest_path']+' and '+source['guest_path'])
            item={**source,'image':name,'path':path};seen[key]=item;planned.append(item);touched.add(name)
        for name in touched:
            fs=images[name]['fs']
            if fs=='ext2':continue
            if fs!='vfat':raise ValueError('Touched filesystem backend not implemented: '+fs)
            if vfat_fmask is None or vfat_dmask is None:
                raise ValueError('Touched VFAT image requires explicit fmask/dmask: '+name)
        hashes={name:digest(image['file']) for name,image in images.items()}
        stage=None
        try:
            if not dry_run:
                stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'-',dir=parent))
                for name,image in images.items():
                    target=stage/(name+'.img');shutil.copy2(image['file'],target);target.chmod(0o600)
                    if digest(target)!=hashes[name]:raise ValueError('Source image changed while copying')
            def open_backend(name,path):
                fs=images[name]['fs']
                if fs=='ext2':return Ext2(path,scratch)
                return Fat(path,scratch,mtools_dir,vfat_fmask,vfat_dmask,vfat_uid,vfat_gid,vfat_allow_zero_padding)
            backends={name:open_backend(name,images[name]['file'] if dry_run else stage/(name+'.img')) for name in touched}
            before={name:backend.inventory() for name,backend in backends.items()}
            expected=copy.deepcopy(before)
            for item in planned:
                entries=expected[item['image']]['entries'];path=item['path'];old=entries.get(path)
                for ancestor in PurePosixPath(path).parents:
                    node=entries.get(str(ancestor))
                    if not node or node['kind']!='dir':raise ValueError('Missing/non-directory/symlink image parent: '+str(ancestor))
                if old and ((old['kind']=='dir')!=(item['kind']=='dir') or old['kind']=='special'):
                    raise ValueError('File/directory/special-node type conflict: '+item['guest_path'])
                if old and (old['acl'] or (old['flags'] and old['kind']!='dir')):
                    raise ValueError('Refusing to discard inode flags/extended attributes: '+item['guest_path'])
                perms=(old['mode']&0o7777) if old else item['source_mode']
                node={'kind':item['kind'],'uid':old['uid'] if old else 0,'gid':old['gid'] if old else 0,'flags':0,'acl':0}
                if item['kind']=='dir':node=copy.deepcopy(old) if old else {**node,'mode':stat.S_IFDIR|perms}
                elif item['kind']=='file':node.update(mode=stat.S_IFREG|perms,size=item['size'],sha256=item['sha256'])
                else:node.update(mode=stat.S_IFLNK|perms,target=item['target'])
                item.update(before=old,after=node,action='merge-directory' if old and item['kind']=='dir' else 'replace' if old else 'create')
                entries[path]=node
                if item['kind']!='dir':
                    expected[item['image']]['hardlinks']=[g for group in expected[item['image']]['hardlinks']
                        if len(g:=[p for p in group if p!=path])>1]
            report={'schema':1,'dry_run':dry_run,'signed_update_package':False,
                    'base_images':{n:{'sha256':hashes[n],'fs':i['fs']} for n,i in images.items()},
                    'operations':[{k:v for k,v in item.items() if k!='snapshot'} for item in planned],
                    'images':{}}
            if not dry_run:
                for item in planned:backends[item['image']].apply(item)
                for name,backend in backends.items():
                    backend.fsck();actual=backend.inventory()
                    if actual!=expected[name]:raise ValueError('Full image reference tree mismatch: '+name)
                for name,image in images.items():
                    if digest(image['file'])!=hashes[name]:raise ValueError('Original image changed during build: '+name)
                    target=stage/(name+'.img')
                    report['images'][name]={'file':target.name,'sha256':digest(target),
                        'full_tree_compared':name in touched,'unchanged_bytes_verified':name not in touched,
                        'tree_sha256':hashlib.sha256(json.dumps(expected[name],sort_keys=True).encode()).hexdigest() if name in touched else None}
                    with target.open('rb') as stream:os.fsync(stream.fileno())
                next_config={'schema':1,'mounts':mounts,'images':[
                    {**{k:v for k,v in image.items() if k!='file'},'file':name+'.img',
                     'sha256':report['images'][name]['sha256'],'base_sha256':hashes[name],
                     'source_class':'project_derived' if name in touched else image.get('source_class','unverified_base')}
                    for name,image in images.items()]}
                for name,data in (('overwrite-manifest.json',report),('mounts.json',next_config)):
                    with (stage/name).open('x') as stream:
                        stream.write(json.dumps(data,indent=2,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
                fd=os.open(stage,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                try:os.fsync(fd)
                finally:os.close(fd)
                stage.rename(output);stage=None
                fd=os.open(parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
                try:os.fsync(fd)
                finally:os.close(fd)
            return report
        finally:
            for backend in locals().get('backends',{}).values():
                close=getattr(backend,'close',None)
                if close:close()
            if stage is not None:shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mounts',type=Path,required=True)
    parser.add_argument('--overwrite',type=Path,default=Path('overwrite'))
    parser.add_argument('--output',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--mtools-dir',type=Path,help='host mtools bin directory for touched VFAT images')
    parser.add_argument('--vfat-fmask',type=lambda v:int(v,8),help='explicit conventional VFAT file mask, e.g. 022')
    parser.add_argument('--vfat-dmask',type=lambda v:int(v,8),help='explicit conventional VFAT directory mask, e.g. 022')
    parser.add_argument('--vfat-uid',type=int,default=1000,help='Sony non-root POSIX owner id used by one attribute bit')
    parser.add_argument('--vfat-gid',type=int,default=1000)
    parser.add_argument('--vfat-zero-padding',dest='vfat_zero_padding',action='store_true',default=True,
                        help='allow zero padding outside a BPB smaller than the partition (default: on)')
    args=parser.parse_args()
    if not args.dry_run and args.output is None:parser.error('--output is required without --dry-run')
    print(json.dumps(build(args.mounts,args.overwrite,args.output,args.dry_run,
                           mtools_dir=str(args.mtools_dir) if args.mtools_dir else None,
                           vfat_fmask=args.vfat_fmask,vfat_dmask=args.vfat_dmask,
                           vfat_uid=args.vfat_uid,vfat_gid=args.vfat_gid,
                           vfat_allow_zero_padding=args.vfat_zero_padding),indent=2))


if __name__=='__main__':main()
