#!/usr/bin/env python3
"""Snapshot SD/ into a private FAT16 image; restore only a verified guest export."""
import hashlib
from contextlib import nullcontext
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import uuid

from fat_image import FatImage, component, secure_open

HERE=Path(__file__).resolve().parent
TEMPLATE=runpy.run_path(str(HERE/'file-media-template.py'))
MAX_BYTES=127*1024**2
MAX_ENTRIES=8192


def identity(info):
    return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns


def directory_tree(directory,snapshots=None):
    """Audit ordinary directories/files; optionally snapshot stable file bytes."""
    directory=Path(os.path.abspath(directory))
    root_fd=secure_open(directory,directory=True)
    try:
        root_info=os.fstat(root_fd)
        tree={};total=0
        def fail(error):raise error
        for parent,dirs,files in os.walk(directory,followlinks=False,onerror=fail):
            names={}
            for name in sorted(dirs+files):
                component(name)
                if name.casefold() in names:raise ValueError('Case-insensitive SD name collision')
                names[name.casefold()]=name
                path=Path(parent)/name;relative=path.relative_to(directory).as_posix()
                is_dir=name in dirs
                fd=secure_open(path,directory=is_dir)
                try:
                    before=os.fstat(fd)
                    if is_dir:tree[relative]={'kind':'dir'}
                    else:
                        total+=before.st_size
                        if total>MAX_BYTES:raise ValueError('SD input exceeds virtual card capacity')
                        target=snapshots/str(len(tree)) if snapshots is not None else None
                        with os.fdopen(os.dup(fd),'rb') as stream, \
                             (target.open('xb') if target else nullcontext()) as output:
                            hashed=hashlib.sha256();left=before.st_size
                            while data:=stream.read(min(1024*1024,left+1)):
                                if len(data)>left:raise ValueError('SD file grew while snapshotting')
                                left-=len(data);hashed.update(data)
                                if output is not None:output.write(data)
                            if left:raise ValueError('SD file shrank while snapshotting')
                            sha=hashed.hexdigest()
                        if identity(before)!=identity(os.fstat(fd)):
                            raise ValueError('SD file changed while snapshotting')
                        tree[relative]={'kind':'file','size':before.st_size,'sha256':sha}
                    if len(tree)>MAX_ENTRIES:raise ValueError('SD tree exceeds entry bound')
                finally:os.close(fd)
        named_fd=secure_open(directory,directory=True)
        try:
            if identity(root_info)!=identity(os.fstat(named_fd)):
                raise ValueError('SD directory changed while snapshotting')
        finally:os.close(named_fd)
        return tree
    finally:os.close(root_fd)


def normalized(tree):
    return {path.lstrip('/'):{key:value for key,value in node.items()
            if key in ('kind','size','sha256')} for path,node in tree.items() if path!='/'}


def fat(image,scratch):
    return FatImage(image,scratch,mtools_dir=TEMPLATE['mtools_bin'](),fmask=0o022,dmask=0o022,
                    max_entries=MAX_ENTRIES,max_total_bytes=MAX_BYTES,max_image_bytes=128*1024**2)


def pack(directory,destination):
    """Create exclusively; the input directory and any previous image are preserved."""
    destination=Path(os.path.abspath(destination));directory=Path(os.path.abspath(directory))
    parent_fd=secure_open(destination.parent,directory=True)
    try:
        with tempfile.TemporaryDirectory(prefix='.sd-pack-',dir=destination.parent) as temporary:
            scratch=Path(temporary);snapshots=scratch/'snapshots';snapshots.mkdir()
            tree=directory_tree(directory,snapshots)
            image=TEMPLATE['create'](scratch/'card.fat');tools=TEMPLATE['mtools_bin']()
            env={'PATH':'/usr/bin:/bin','MTOOLSRC':'/dev/null','LC_ALL':'C.UTF-8','TZ':'UTC'}
            def command(name,*args):
                subprocess.run([str(tools/name),'-i',str(image),*args],env=env,
                               capture_output=True,check=True,timeout=120)
            command('mdel','::/'+TEMPLATE['SEED_NAME'])
            for index,(path,node) in enumerate(tree.items()):
                if node['kind']=='dir':command('mmd','::/'+path)
                else:command('mcopy',str(snapshots/str(index)),'::/'+path)
            with fat(image,scratch) as volume:
                volume.fsck()
                if normalized(volume.inventory()['entries'])!=tree:
                    raise ValueError('FAT readback differs from input SD tree')
            if directory_tree(directory)!=tree:raise ValueError('SD changed during image construction')
            with image.open('rb') as stream:
                sha=hashlib.file_digest(stream,'sha256').hexdigest();os.fsync(stream.fileno())
            os.link(image,destination.name,dst_dir_fd=parent_fd,follow_symlinks=False)
            os.fsync(parent_fd)
        return {'schema':'sd-directory-v1','directory':str(directory),'image_sha256':sha,'tree':tree}
    finally:os.close(parent_fd)


def restore(image,directory,baseline,evidence):
    """Publish an audited export after flush/recovery, retaining the previous SD tree."""
    if evidence.get('schema') == 'sd-terminal-receipt-v1':
        receipts=runpy.run_path(str(HERE/'save-evidence.py'))
        if receipts['load_card_receipt'](Path(image).parent) != evidence:
            raise ValueError('Card receipt does not match the closed guest run')
        accepted=evidence.get('state')=='card-save-completed'
    else:
        accepted=evidence.get('state')=='observation-completed'
    if not (evidence.get('card_snapshot_integrity_verified') is True and
            evidence.get('card_flush_lifecycle_verified') is True and
            accepted):
        raise ValueError('Guest snapshot/flush/stop/recovery evidence is incomplete')
    directory=Path(os.path.abspath(directory));image=Path(os.path.abspath(image))
    parent_fd=secure_open(directory.parent,directory=True)
    stage_name='.SD-export-'+uuid.uuid4().hex;backup_name='.SD-previous-'+uuid.uuid4().hex
    try:
        os.mkdir(stage_name,0o700,dir_fd=parent_fd)
        stage=directory.parent/stage_name
        with tempfile.TemporaryDirectory(prefix='.sd-audit-',dir=directory.parent) as temporary:
            with fat(image,Path(temporary)) as volume:
                with os.fdopen(os.dup(volume.fd),'rb') as stream:
                    sha=hashlib.file_digest(stream,'sha256').hexdigest()
                if sha!=evidence.get('card_image_sha256'):raise ValueError('Export SHA differs from guest run')
                volume.fsck();tree=normalized(volume.inventory()['entries'])
                # Start the second traversal after inventory audited all ownership.
                volume.used.clear()
                for path,node in sorted(tree.items(),key=lambda item:(item[0].count('/'),item[0])):
                    target=stage/path
                    if node['kind']=='dir':target.mkdir()
                    elif node['kind']=='file':
                        raw=volume.locations['/'+path][1]
                        cluster=int.from_bytes(raw[26:28],'little')
                        if volume.bits==32:cluster|=int.from_bytes(raw[20:22],'little')<<16
                        left=node['size']
                        with target.open('xb') as output:
                            for value in volume.chain(cluster,'/'+path):
                                data=volume.read(volume.cluster_offset(value),min(left,volume.cluster_bytes))
                                output.write(data);left-=len(data)
                            output.flush();os.fsync(output.fileno())
                        if left:raise ValueError('Short exported file')
                    else:raise ValueError('Unsupported node in exported SD')
                if identity(volume.identity)!=identity(os.fstat(volume.fd)):
                    raise ValueError('Export changed during directory extraction')
        if directory_tree(stage)!=tree:raise ValueError('Extracted SD hashes differ')
        # File fsync does not persist directory entries; sync children before parents.
        directories=[stage/path for path,node in tree.items() if node['kind']=='dir']
        for path in sorted(directories,key=lambda path:len(path.parts),reverse=True)+[stage]:
            fd=secure_open(path,directory=True)
            try:os.fsync(fd)
            finally:os.close(fd)
        if directory_tree(directory)!=baseline['tree']:raise ValueError('Host SD changed; export retained at '+str(stage))
        os.rename(directory.name,backup_name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
        try:
            if directory_tree(directory.parent/backup_name)!=baseline['tree']:
                raise ValueError('Host SD changed before publication')
            os.rename(stage_name,directory.name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd)
        except BaseException:
            os.rename(backup_name,directory.name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd);raise
        os.fsync(parent_fd)
        return {'image_sha256':sha,'files':len(tree),'previous_directory':str(directory.parent/backup_name)}
    finally:os.close(parent_fd)
