#!/usr/bin/env python3
"""Build an isolated virtual factory candidate using only verified official assets.

The complete PP is kept unchanged. Missing writable volumes are explicitly new
virtual media; this is not a reconstruction of device manufacturing calibration.
"""
import argparse
import hashlib
import io
import json
import importlib
import sys
import os
from pathlib import Path
import runpy
import shutil
import stat
import struct
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
IMPORT=runpy.run_path(str(HERE/'bodydata-launch.py'))
from ext2_inventory import Ext2
DIGEST=IMPORT['digest']
INPUT_SHA='eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'


def verify_cache(cache):
    report=IMPORT['verify_cache'](cache,INPUT_SHA)
    if report.get('identity',{}).get('model')!=0x20030014 or report.get('identity',{}).get('version')!='2.01':
        raise ValueError('Only original 2.01 ALLLANG cache is supported')
    assets=[]
    for name,row in report['files'].items():
        if name.startswith('firmware-root/'):
            assets.append(dict(path=name.removeprefix('firmware-root/'),type='directory' if row.get('directory') else 'file'))
    skipped=json.loads((cache/'archive-skipped.json').read_bytes())
    for row in skipped:
        if row.get('type')=='2':
            assets.append(dict(path=row['path'],type='symlink',target=row['link']))
    return dict(assets=assets)


def vendor(root,names):
    root=Path(root).resolve(strict=True)
    if not (root/'fwtool/archive/fat.py').is_file():raise ValueError('Product fwtool SDK required')
    sys.path.insert(0,str(root))
    result=[]
    for name in names:
        module=importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(root):raise ValueError('Wrong fwtool SDK already imported')
        result.append(module)
    return result

PARTS=('1','2','3','4','5','6','7','8','10','11','12','13','15','18','22','23','30')
PP='0110_backup/SYSIPSX-DSLR/PP/CX89701_ALLLANG.bin'


def image_name(number):
    return {'7':'a7c2-rootfs.img','15':'a7c2-usr.img'}.get(number,'nflasha'+number+'.img')


def layout(path):
    rows={}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):continue
        device,mount,kind,size,cluster=line.split()
        if not device.startswith('/dev/nflasha'):raise ValueError('Unknown partition device')
        number=device.removeprefix('/dev/nflasha')
        if number in rows:raise ValueError('Duplicate partition layout')
        rows[number]={'number':number,'mount':mount,'kind':kind,'bytes':int(size),'cluster':int(cluster)}
    if any(n not in rows or not 0<rows[n]['bytes']<=1024**3 for n in PARTS):
        raise ValueError('Incomplete/unsupported official partition geometry')
    return rows


def check(tool,path,log):
    argv=[tool,'-f','-n',str(path)] if tool=='e2fsck' else [tool,'-n',str(path)]
    result=subprocess.run(argv,capture_output=True,text=True,timeout=180,env={**os.environ,'LC_ALL':'C'})
    log.write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError(tool+' rejected '+path.name+'; see '+str(log)+'\n'+result.stdout+result.stderr)


def normalize_fat12_aliases(path):
    """Repair fwtool's simplistic SFN aliases; retain every LFN and inode field."""
    data=bytearray(path.read_bytes())
    if data[54:62]!=b'FAT12   ' or data[510:512]!=b'\x55\xaa':raise ValueError('Expected generated FAT12')
    sector=struct.unpack_from('<H',data,11)[0];cluster=sector*data[13]
    fat=sector*struct.unpack_from('<H',data,14)[0]
    root=fat+data[16]*sector*struct.unpack_from('<H',data,22)[0]
    rootsize=32*struct.unpack_from('<H',data,17)[0];start=root+rootsize
    forbidden=set(b'"*+,./:;<=>?[\\]|')
    def valid(name):
        base,ext=name[:8].rstrip(b' '),name[8:].rstrip(b' ')
        return bool(base) and all(32<c<127 and c not in forbidden for c in base+ext)
    def offsets(first):
        result=[];seen=set()
        while 2<=first<0xff8:
            if first in seen or start+(first-1)*cluster>len(data):raise ValueError('Invalid FAT directory chain')
            seen.add(first);where=start+(first-2)*cluster
            result.extend(range(where,where+cluster,32))
            packed=struct.unpack_from('<H',data,fat+first*3//2)[0]
            first=(packed>>4 if first&1 else packed&0xfff)
            if not first:raise ValueError('Unallocated directory cluster')
        return result
    pending=[list(range(root,root+rootsize,32))];visited=set();changed=0
    while pending:
        entries=pending.pop();used=set();long_entries=[];serial=0
        for offset in entries:
            first=data[offset];attr=data[offset+11]
            if first==0:break
            if first==0xe5:long_entries=[];continue
            if attr==0x0f:long_entries.append(offset);continue
            name=bytes(data[offset:offset+11])
            if name[:8].rstrip(b' ') in (b'.',b'..') or attr&8:
                long_entries=[];continue
            if not valid(name) or name in used:
                if not long_entries:raise ValueError('Invalid short name without a recoverable long name')
                ext=b'DIR' if attr&0x10 else bytes(c for c in name[8:] if 65<=c<=90 or 48<=c<=57)[:3].ljust(3,b' ')
                while True:
                    serial+=1;replacement=f'F{serial:07d}'.encode()+ext
                    if replacement not in used:break
                data[offset:offset+11]=replacement;name=replacement
                checksum=0
                for byte in name:checksum=(((checksum&1)<<7)+(checksum>>1)+byte)&255
                for entry in long_entries:data[entry+13]=checksum
                changed+=1
            used.add(name);long_entries=[]
            if attr&0x10:
                number=struct.unpack_from('<H',data,offset+26)[0]
                if number in visited:raise ValueError('Directory alias/cycle in generated FAT')
                visited.add(number);pending.append(offsets(number))
    with path.open('r+b') as output:output.write(data)
    return changed


def fat_image(path,size,files,fat,unix):
    """Create and independently read back a small Sony FAT12 volume."""
    if size//16384>4084:raise ValueError('Explicit FAT12 size bound exceeded')
    entries=[]
    for name,node in sorted(files.items()):
        if not name.startswith('/') or any(p in ('.','..') for p in name.split('/')[1:]):raise ValueError('Unsafe FAT path')
        data=node['data'];mode=node.get('mode',stat.S_IFREG|0o644)
        entries.append(unix(name,len(data),315532800,mode,0,0,io.BytesIO(data)))
    with path.open('xb') as output:fat.writeFat(entries,size,output)
    # fwtool emits an all-spaces boot label, rejected by fsck.fat. "NO NAME"
    # is the standard unlabeled FAT12 marker; no file/directory is changed.
    with path.open('r+b') as output:output.seek(43);output.write(b'NO NAME    ')
    normalize_fat12_aliases(path)
    actual={}
    with path.open('rb') as source:
        for entry in fat.readFat(source):
            if stat.S_ISDIR(entry.mode):continue
            contents=entry.contents.read(entry.size+1)
            if len(contents)!=entry.size:raise ValueError('Short FAT readback')
            actual[entry.path]={'data':contents,'link':stat.S_ISLNK(entry.mode)}
    expected={name:{'data':node['data'],'link':stat.S_ISLNK(node.get('mode',stat.S_IFREG))} for name,node in files.items()}
    if actual!=expected:raise ValueError('FAT tree readback differs from supplied official data')
    return {name:{'sha256':hashlib.sha256(node['data']).hexdigest(),'size':len(node['data']),
                  'kind':'symlink' if node['link'] else 'file'} for name,node in actual.items()}


def generate(cache,output,fwtool):
    cache=Path(cache).resolve(strict=True);output=Path(output).absolute()
    if os.path.lexists(output):raise ValueError('Factory output must not exist')
    if output==cache or output.is_relative_to(cache):raise ValueError('Factory output must not contaminate official cache')
    report=verify_cache(cache)
    fat,unix_module=vendor(Path(fwtool),('fwtool.archive.fat','fwtool.archive'))
    assets={r['path']:r for r in report['assets']}
    rows=layout(cache/'firmware-root/0100_config/mount.conf')
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<3*sum(rows[n]['bytes'] for n in PARTS)+256*1024**2:
        raise OSError('Insufficient space for factory images, runtime copies and image audits')
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'-',dir=output.parent))
    records=[];mounts=[];image_rows=[]
    try:
        logs=stage/'checks';logs.mkdir()
        scratch=stage/'readback';scratch.mkdir()
        for number in (*PARTS,'B0','B1'):
            print('FACTORY_IMAGE_PHASE '+number,flush=True)
            row=rows[number] if number in rows else {'bytes':4*1024**2,'mount':'none','kind':'virtual-loader-area','cluster':0}
            name=image_name(number);target=stage/name
            original_name='0700_part_image/dev/nflasha'+number
            original=cache/'firmware-root'/original_name
            fs='ext2' if number in ('7','15') else row['kind']
            tree=None
            if original_name in assets:
                source_sha=DIGEST(original)
                subprocess.run(['cp','--reflink=auto','--sparse=always',str(original),str(target)],check=True)
                target.chmod(0o600)
                if target.stat().st_size>row['bytes']:raise ValueError('Official image exceeds declared partition')
                if fs=='ext2':before=Ext2(original,scratch).inventory()
                with target.open('r+b') as stream:stream.truncate(row['bytes'])
                if fs=='ext2':
                    result=subprocess.run(['resize2fs',str(target)],capture_output=True,text=True,timeout=180)
                    (logs/(name+'-resize.log')).write_text(result.stdout+result.stderr)
                    if result.returncode:raise RuntimeError('Cannot resize derived ext2 partition '+number)
                    check('e2fsck',target,logs/(name+'-fsck.log'))
                    after=Ext2(target,scratch).inventory()
                    if before!=after:raise ValueError('Resizing changed the complete original filesystem tree')
                    tree=hashlib.sha256(json.dumps(after,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                elif fs=='vfat':check('fsck.fat',target,logs/(name+'-fsck.log'))
                if DIGEST(original)!=source_sha:raise ValueError('Original changed during factory build')
                derivation={'kind':'official-image-copy-and-zero-padding','asset':original_name,'source_sha256':source_sha,
                            'ext2_resized':fs=='ext2','complete_tree_sha256':tree}
            elif fs=='vfat':
                files={}
                if number=='1':
                    # Signed FDAT model/region/version form a named virtual identity,
                    # not an original camera's private nflasha1 or serial number.
                    header=(cache/'firmware.fdat').open('rb')
                    with header:data=header.read(512)
                    files={'/DAT2':{'data':data[36:40]},'/DAT3':{'data':data[40:44]},'/DAT4':{'data':data[32:34]}}
                if number=='2':
                    files['/Backup.bin']={'data':(cache/'firmware-root'/PP).read_bytes()}
                    for path,item in assets.items():
                        if path.startswith('0800_appli/setting/') and item['type']=='file':
                            files['/'+path.removeprefix('0800_appli/setting/')]={'data':(cache/'firmware-root'/path).read_bytes()}
                    if len(files)!=7:raise ValueError('Expected complete PP and six original setting defaults')
                    # Original libInfraGetVersion::rcv_async_thread_set opens
                    # this path and requires exactly two version bytes. They
                    # come from the verified signed FDAT header, not a device.
                    with (cache/'firmware.fdat').open('rb') as stream:version=stream.read(34)[32:34]
                    if len(version)!=2:raise ValueError('Missing signed runtime version bytes')
                    files['/updater/dat4']={'data':version}
                if number=='10':
                    for path,item in assets.items():
                        if path.startswith('0800_appli/tmp/') and item['type'] in ('file','symlink'):
                            node={'data':(cache/'firmware-root'/path).read_bytes()} if item['type']=='file' else \
                                 {'data':item['target'].encode(),'mode':stat.S_IFLNK|0o777}
                            files['/'+path.removeprefix('0800_appli/tmp/')]=node
                if row['bytes']//16384<=4084:
                    tree=fat_image(target,row['bytes'],files,fat,unix_module.UnixFile)
                else:
                    if files:raise ValueError('Populated large FAT volume needs a separate writer')
                    with target.open('xb') as stream:stream.truncate(row['bytes'])
                    subprocess.run(['mkfs.fat','--invariant','-F','16','-s','32','-n','A7C2VIRTUAL',str(target)],check=True,
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    tree={}
                check('fsck.fat',target,logs/(name+'-fsck.log'))
                derivation={'kind':'new-virtual-fat-volume','files':tree,'private_device_data_used':False}
            else:
                with target.open('xb') as stream:stream.truncate(row['bytes'])
                derivation={'kind':'new-unformatted-zero-virtual-area','private_device_data_used':False,
                            'not_manufacturing_calibration':True}
                fs='unformatted'
            hashed=DIGEST(target)
            record={'name':name,'bytes':target.stat().st_size,'sha256':hashed,'image_id':'nflasha'+number,
                    'fs':fs,'derivation':derivation}
            records.append(record)
            image_rows.append({'id':'nflasha'+number,'file':name,'fs':fs,'sha256':hashed})
            if row['mount']!='none':
                mounts.append({'guest':'/' if number=='7' else row['mount'],'image':'nflasha'+number,'root':'/'})
            if number=='10':
                mounts.extend({'guest':alias,'image':'nflasha10','root':'/'} for alias in ('/etc','/var'))
        if len(records)!=19:raise ValueError('Factory partition set is incomplete')
        shutil.rmtree(scratch)
        manifest={'schema':1,'source':'official-bodydata-derived','bodydata_sha256':INPUT_SHA,
                  'images':records,'factory_pp_asset':PP,'factory_pp_unchanged':True,'private_device_data_used':False,
                  'camera_startup_verified':False,'manufacturing_calibration_verified':False,
                  'initial_setup_policy':'original language/date/first-setup flags unchanged',
                  'runtime_version_policy':'/setting/updater/dat4 from signed FDAT bytes 0x20..0x21',
                  'builder_source_sha256':DIGEST(Path(__file__))}
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (stage/'mounts.json').write_text(json.dumps({'schema':1,'images':image_rows,'mounts':mounts},indent=2)+'\n')
        verify_cache(cache)
        (stage/'FACTORY-IMAGES-COMPLETE').write_text(DIGEST(stage/'manifest.json')+'\n')
        os.rename(stage,output)
        return manifest
    except BaseException as error:
        (stage/'FACTORY-FAILED.txt').write_text(type(error).__name__+': '+str(error)+'\n')
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--fwtool',type=Path,required=True)
    args=parser.parse_args()
    generate(args.cache,args.output,args.fwtool)
    print('OFFICIAL_FACTORY_IMAGES '+str(args.output.resolve()),flush=True)


if __name__=='__main__':main()
