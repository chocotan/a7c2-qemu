"""Read-only complete ext2 inventory via the installed debugfs tool."""

import hashlib,os,re,shutil,stat,subprocess

from pathlib import Path

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
