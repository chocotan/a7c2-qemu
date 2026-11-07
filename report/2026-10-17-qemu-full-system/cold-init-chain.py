#!/usr/bin/env python3
"""Build an isolated raw-ext2 RAM0 which runs the original Sony init/pivot chain.

build(runtime_analysis, output_dir, *, ram0_bytes=None) never edits the prepared
runtime. Only manifest.json publishes a successful build; failures retain work/
and failure.json. Running the guest and judging its evidence belong to the caller.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROFILE = 'ram0-loop-v1'
MIB = 1024**2
ORIGINAL_RAMROOT_SHA = 'b249308ff1a42f8f441cedbd6244e8ffa0b4c88b984b2d5e71a436d09ab86529'
ORIGINAL_RAMROOT_BYTES = 5218304
BOOTIN_SHA = 'dab3ce4b6c28a6c9ffd9f0b893dce1d08f3ee7302a09df87e518409e728be2f2'
KERNEL_SHA = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
# Sony ILCE-7CM2 2.01 /bin/im.elf; independently read from original dump p15.
IM_SHA = '5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91'
IM_VERSION = 'ILCE-7CM2-2.01'
IM_BYTES = 40920
BOOTIN_WRAPPER_SOURCE = HERE/'guest/bootin-wrapper'
HELPERS = {
    'fstab': '3936e6508ba89a025fc998c824434562c2d16234db96e179ec3f3a90a5a1d6f0',
    'fstab.ext': 'a77bdfb7bf15d3a1240bdefc4edb4469672f3258d6d8dba7dd4164e3fd2d51c3',
    'fstab.root': 'c77d93236b89349bcc24853756f960bb49411e922c9430ede70b5b2cb8b6a4b2',
    'insmod_drv1': '22f29d06d7776fe5e8362c17049beabfd3e3bebffd222e51276e3704d483a591',
    'insmod_drv2': '19757bdd450061f861e2da44a6a93be2525668e3f7edc64e5a99a25bde56564e',
    'setup_console': '9411360fdfe60c7b7a09fa9e931e4ae9ec9c062e480b620e4c313c31f9139dd0',
    'setup_nflash': '055cb3db7a40084aef8aaa89a7357921b514bf0af89690f920b608d9f3734cdc',
    'setup_shielding': 'd54f7a0ebfa3db37fe329463bdbf60c8b6fd14c3cb95dc658c244e8bf61ead1f',
    'setup_rootfs': 'ee84d317484d8cb4a0f1e39d665f1f04f18bf4d193a36a6e9bf63f8666a6a34d',
}
RAM_SCRIPTS = {'/sbin/init': 'c83de1abeeb779f7473181b51face32ecfedfa3bd5c0fc346ae0c628f1b0ac5e',
               **{'/sbin/initrc/'+name: sha for name, sha in HELPERS.items()}}
P7_SCRIPTS = {'/sbin/init2': '45d3b907e6ef96c9a930cd3e6f919db700bffb5f18c386abfdb655f4d9954aeb',
              **{'/sbin/initrc/'+name: sha for name, sha in HELPERS.items()}}
PARTS = ('1','2','3','4','5','6','7','8','10','11','12','13','15','18','22','23','30','B0','B1')
NAMES = {part: {'7':'a7c2-rootfs.img','15':'a7c2-usr.img'}.get(part,'nflasha'+part+'.img') for part in PARTS}

INSMOD = '''#!/bin/busybox sh
# This profile replaces physical storage with verified Linux loop devices.
case "$1" in
    /kmod/crypt-emmc.ko|/kmod/emmc.ko)
        echo "COLD_MODULE_UNSUPPORTED module=$1 storage=linux-loop result=78"
        exit 78;;
    /usr/kmod/*)
        if [ ! -e /dev/qemu-simulation/cold-init2-observed ]; then
            /bin/busybox touch /dev/qemu-simulation/cold-init2-observed
            echo "COLD_INIT2_PROCESS parent=$PPID"
            /bin/busybox cat /proc/$PPID/cmdline /proc/$PPID/status /proc/1/mountinfo
            echo "COLD_EXPECTED_IM version=@IM_VERSION@ sha256=@IM_SHA@"
            /bin/busybox ls -l /dev/nflasha7 /dev/qemu-partitions
        fi;;
esac
exec /dev/qemu-simulation/cold-house-insmod "$@"
'''.replace('@IM_VERSION@',IM_VERSION).replace('@IM_SHA@',IM_SHA)
FREERAM_OBSERVE = '''#!/bin/busybox sh
# Execute the original BusyBox applet, then read back the released RAM disk prefix.
exec /dev/qemu-simulation/cold-start-audit release "$@"
'''
P15_WRAPPER = '''#!/bin/busybox sh
/bin/busybox mkdir -p /log/qemu || exit 1
# Keep this experiment's large observer logs off the shared 12 MiB volume.
for name in menu-load.log gpe-requests.bin im.log; do
    /bin/busybox rm -f "/tmp/$name" || exit 1
    /bin/busybox ln -s "/log/qemu/$name" "/tmp/$name" || exit 1
done
echo "COLD_BOOTIN_ENTRY pid=$$"
/bin/busybox cat /proc/$$/cmdline /proc/$$/status /proc/1/mountinfo
exec /simulation/bootin-wrapper --original-elf /usr/bin/bootin-original "$@"
'''


def expected_im():
    return dict(schema=1, version=IM_VERSION, bytes=IM_BYTES, sha256=IM_SHA)


def verify_im_identity(row):
    if row.get('sha256') != IM_SHA or row.get('bytes') != IM_BYTES:
        raise ValueError('Original 2.01 IM identity differs; explicit new baseline required')


def plain(path, directory=False):
    path = Path(os.path.abspath(path))
    for parent in reversed((path, *path.parents)):
        if parent.is_symlink():
            raise ValueError('Host symlink refused: '+str(parent))
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ValueError('Expected ordinary '+('directory: ' if directory else 'file: ')+str(path))
    return path


def digest(path):
    path = plain(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        result = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
    if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != \
       (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('Source changed during hash: '+str(path))
    return result


def binding(path, role):
    path = plain(path)
    info = path.stat()
    return {'path':str(path), 'role':role, 'bytes':info.st_size,
            'sha256':digest(path), 'mode':stat.S_IMODE(info.st_mode),
            'device':info.st_dev, 'inode':info.st_ino}


def recheck(rows):
    for row in rows:
        now = binding(row['path'], row['role'])
        if now != row:
            raise ValueError('Source changed: '+row['path'])


def clone(source, target, expected):
    plain(source)
    if os.path.lexists(target):
        raise ValueError('Copy destination exists: '+str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cp','--reflink=auto','--sparse=always','--',str(source),str(target)], check=True)
    plain(target)
    if os.path.samestat(source.stat(), target.stat()):
        raise ValueError('Independent source copy aliases original inode: '+str(source))
    target.chmod(0o600)
    if digest(target) != expected:
        raise ValueError('Independent source copy differs: '+str(source))


def scripts(tree, wanted):
    result = {}
    for name, expected in wanted.items():
        node = tree['entries'].get(name, {})
        if node.get('kind') != 'file' or node.get('sha256') != expected:
            raise ValueError('Original script identity differs: '+name)
        result[name] = expected
    return result


def _extract_initrd(image, target):
    # Reuse the same pinned FAT reader as the full-system preparation route.
    read_fat = runpy.run_path(str(HERE/'prepare-full-system.py'))['readFat']
    found = False
    with image.open('rb') as stream:
        for count, entry in enumerate(read_fat(stream)):
            if count > 100000:
                raise ValueError('Oversized FAT directory inventory')
            if entry.path.lstrip('/') != 'initrd.img':
                continue
            if found or not stat.S_ISREG(entry.mode) or entry.size != ORIGINAL_RAMROOT_BYTES:
                raise ValueError('Invalid/duplicate original initrd.img')
            found = True
            data = entry.contents.read(entry.size+1)
            if len(data) != ORIGINAL_RAMROOT_BYTES or hashlib.sha256(data).hexdigest() != ORIGINAL_RAMROOT_SHA:
                raise ValueError('Original p3 RAM root SHA256 differs')
            target.write_bytes(data)
    if not found:
        raise ValueError('Original p3 lacks initrd.img; no cross-source fallback')


def validate_bootin_wrapper(path):
    text = plain(path).read_text()
    for required in ('--original-elf)', 'fullsystem.bootin-handoff=p15-wrapper',
                     '/usr/bin/bootin-original|/log/a7c2/bootin-original)',
                     'original_elf_sha256='+BOOTIN_SHA, 'FULLSYSTEM_BOOTIN_HANDOFF_FAILED sha256',
                     'exec "$original_elf" "$@"'):
        if required not in text:
            raise ValueError('Authoritative bootin wrapper lacks verified original-ELF handoff: '+required)
    subprocess.run(['sh','-n',str(path)],check=True,capture_output=True,text=True)


def _compile_audit(source, libc, target):
    result = subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu',
                    '-fuse-ld=lld','-nostdlib','-O2','-fno-stack-protector','-Wl,--no-undefined','-Wl,-e,_start',
                    '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',str(source),str(libc),
                    '-o',str(target)], capture_output=True, text=True)
    (target.parent/'cold-audit-build.log').write_text(result.stdout+result.stderr)
    if result.returncode:
        raise RuntimeError('Cold audit cross-link failed: '+result.stderr)
    target.chmod(0o755)


def _edit_image(image, scratch, changes, overlay):
    fs = overlay['Ext2'](image, scratch)
    before = fs.inventory()
    expected = copy.deepcopy(before)
    touched = set(changes)
    for name in sorted(changes, key=lambda value:(value.count('/'),value)):
        node, source = changes[name]
        old = expected['entries'].get(name)
        if old and old['kind'] == 'dir' and node['kind'] == 'dir':
            continue
        if old and old['kind'] == 'dir' and node['kind'] != 'dir':
            if any(path.startswith(name+'/') for path in expected['entries']):
                raise ValueError('Refusing to replace a populated guest directory: '+name)
            fs.command('rmdir '+overlay['quote'](name), write=True)
            old = None
        fs.apply({'path':name,'before':old,'after':node,'snapshot':str(source) if source else None})
        expected['entries'][name] = node
    expected['hardlinks'] = sorted(group for paths in before['hardlinks']
                                  if len(group := sorted(set(paths)-touched)) > 1)
    fs.fsck()
    after = fs.inventory()
    if after != expected:
        raise ValueError('Derived ext2 full-tree readback differs: '+image.name)
    return before, after


def _file(path, mode=0o755):
    return {'kind':'file','mode':stat.S_IFREG|mode,'uid':0,'gid':0,'flags':0,'acl':0,
            'size':path.stat().st_size,'sha256':digest(path)}, path


def _link(target):
    return {'kind':'symlink','mode':stat.S_IFLNK|0o777,'uid':0,'gid':0,'flags':0,'acl':0,'target':target}, None


def _directory():
    return {'kind':'dir','mode':stat.S_IFDIR|0o755,'uid':0,'gid':0,'flags':0,'acl':0}, None


def _parents(changes, path):
    for parent in reversed(Path(path).parents):
        if str(parent) != '/':
            changes.setdefault(str(parent), _directory())


def build(runtime_analysis, output_dir, *, ram0_bytes=None):
    runtime = plain(runtime_analysis, directory=True)
    output = Path(os.path.abspath(output_dir))
    if output.is_relative_to(runtime) or runtime.is_relative_to(output):
        raise ValueError('Output must be separate from the input runtime')
    plain(output.parent, directory=True)
    if os.path.lexists(output):
        raise ValueError('Output must be a new directory')
    manifest_path = plain(runtime/'full-system.json')
    original = json.loads(manifest_path.read_text())
    if type(original.get('schema')) is not int or original['schema'] != 1 or original.get('source') not in ('private-device-dump','official-bodydata-derived'):
        raise ValueError('Unsupported full-system source/profile')
    if original.get('cold_init_chain') or original.get('bootin_wrapper_experiment'):
        raise ValueError('Already adapted profile/loop18 SD experiment refused')
    records = original.get('images', [])
    if len(records) != 19 or {row.get('name') for row in records} != set(NAMES.values()):
        raise ValueError('Expected complete 19-partition source inventory; SD extras refused')
    by_name = {row['name']:row for row in records}
    partitions = plain(runtime/'root/partitions', directory=True)
    if {p.name for p in partitions.iterdir()} != set(NAMES.values()):
        raise ValueError('Unexpected partition input/loop18 SD conflict')
    inputs = [binding(manifest_path,'full-system-manifest')]
    volume_inputs = {}
    for part in PARTS:
        name = NAMES[part]
        row = binding(partitions/name,'partition-'+part)
        expected = by_name[name]
        if type(expected.get('bytes')) is not int or not 512 <= expected['bytes'] <= 0x80000000 or \
           row['bytes'] != expected['bytes'] or row['sha256'] != expected.get('sha256'):
            raise ValueError('Partition identity/size differs: '+name)
        volume_inputs[part] = row
        inputs.append(row)
    source_sim = plain(runtime/'root/simulation', directory=True)
    sim_inputs = {}
    for parent, dirs, files in os.walk(source_sim, followlinks=False):
        for name in dirs:
            plain(Path(parent)/name, directory=True)
        for name in files:
            path = Path(parent)/name
            relative = path.relative_to(source_sim).as_posix()
            if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',relative) or any(x in ('.','..') for x in relative.split('/')):
                raise ValueError('Unsupported simulation path')
            sim_inputs[relative] = binding(path,'simulation')
            inputs.append(sim_inputs[relative])
    for name in ('attach-loop','bootin-wrapper','ramfb-viewer','menu-observe.so','seed-power-on'):
        if name not in sim_inputs:
            raise ValueError('Missing prepared simulation helper: '+name)
    for name in ('cold-house-insmod','cold-start-audit','p15-wrapper-source'):
        if name in sim_inputs:
            raise ValueError('Cold profile simulation name already exists: '+name)
    wrapper = binding(BOOTIN_WRAPPER_SOURCE,'cold-source')
    validate_bootin_wrapper(BOOTIN_WRAPPER_SOURCE)
    inputs.append(wrapper)
    insmod = binding(runtime/'root/sbin/insmod','house-insmod')
    if insmod['sha256'] != original.get('derived_files',{}).get('sbin/insmod'):
        raise ValueError('Prepared insmod source identity differs')
    inputs.append(insmod)
    libc = binding(runtime/'root/lib/libc-2.25.so','guest-libc')
    if libc['sha256'] != original.get('derived_files',{}).get('lib/libc-2.25.so'):
        raise ValueError('Prepared guest libc source identity differs')
    inputs.append(libc)
    for path in (HERE/'guest/cold-storage-bootstrap',HERE/'guest/cold-start-audit.c',Path(__file__)):
        inputs.append(binding(path,'cold-source'))
    sim_bytes = sum(row['bytes'] for row in sim_inputs.values())-sim_inputs['bootin-wrapper']['bytes']+wrapper['bytes']+insmod['bytes']+MIB
    payload_bytes = sum(row['bytes'] for row in volume_inputs.values())+sim_bytes
    minimum_ram0 = ((ORIGINAL_RAMROOT_BYTES+payload_bytes+96*MIB+MIB-1)//MIB)*MIB
    if ram0_bytes is None:
        ram0_bytes = minimum_ram0
    if type(ram0_bytes) is not int or ram0_bytes % 4096 or not minimum_ram0 <= ram0_bytes <= 4*1024**3:
        raise ValueError('RAM0 size is unaligned, too small or exceeds the 4 GiB profile bound')
    disk_required = 2*(payload_bytes+ram0_bytes)+512*MIB
    if shutil.disk_usage(output.parent).free < disk_required:
        raise OSError('Insufficient space for cold-chain copies and full-tree readbacks')
    for program in ('cp','clang','debugfs','e2fsck','resize2fs'):
        if not shutil.which(program):
            raise ValueError('Missing host tool: '+program)
    output.mkdir(mode=0o700)
    work = output/'work'
    work.mkdir()
    try:
        overlay = runpy.run_path(str(HERE/'overwrite-images.py'))
        scratch = work/'readback'
        scratch.mkdir()
        volumes = work/'volumes'
        volumes.mkdir()
        for part, row in volume_inputs.items():
            clone(Path(row['path']),volumes/NAMES[part],row['sha256'])
        simulation = work/'simulation'
        simulation.mkdir()
        for name, row in sim_inputs.items():
            selected = wrapper if name=='bootin-wrapper' else row
            clone(Path(selected['path']),simulation/name,selected['sha256'])
            (simulation/name).chmod(0o755 if name=='bootin-wrapper' else row['mode'])
        validate_bootin_wrapper(simulation/'bootin-wrapper')
        clone(Path(insmod['path']),simulation/'cold-house-insmod',insmod['sha256'])
        (simulation/'cold-house-insmod').chmod(0o755)
        audit = work/'cold-start-audit'
        _compile_audit(HERE/'guest/cold-start-audit.c',Path(libc['path']),audit)
        shutil.copyfile(audit,simulation/'cold-start-audit')
        (simulation/'cold-start-audit').chmod(0o755)
        shim = work/'cold-insmod'
        shim.write_text(INSMOD,encoding='ascii')
        release = work/'cold-freeramdisk'
        release.write_text(FREERAM_OBSERVE,encoding='ascii')
        p15_wrapper = simulation/'p15-wrapper-source'
        p15_wrapper.write_text(P15_WRAPPER,encoding='ascii')
        p15_wrapper.chmod(0o755)
        p7 = volumes/NAMES['7']
        p7_before = overlay['Ext2'](p7,scratch).inventory()
        p7_identity = scripts(p7_before,P7_SCRIPTS)
        _, p7_after = _edit_image(p7,scratch,{'/simulation':_link('/dev/qemu-simulation'),
                                            '/sbin/insmod':_file(shim),
                                            '/sbin/freeramdisk':_file(release)},overlay)
        scripts(p7_after,P7_SCRIPTS)
        p15 = volumes/NAMES['15']
        fs = overlay['Ext2'](p15,scratch)
        p15_before = fs.inventory()
        im = p15_before['entries'].get('/bin/im.elf',{})
        if im.get('kind') != 'file':raise ValueError('Original p15 IM must be a regular file')
        verify_im_identity(dict(bytes=im.get('size'),sha256=im.get('sha256')))
        bootin = p15_before['entries'].get('/bin/bootin.elf',{})
        if bootin.get('kind') != 'file' or bootin.get('sha256') != BOOTIN_SHA or '/bin/bootin-original' in p15_before['entries']:
            raise ValueError('Original p15 bootin identity/path differs')
        info = fs.command('stat /bin/bootin.elf')
        inode = int(re.search(r'Inode:\s*(\d+)',info)[1])
        saved = work/'bootin-original'
        shutil.copyfile(fs.dump(inode,bootin['size']),saved)
        _edit_image(p15,scratch,{'/bin/bootin.elf':_file(p15_wrapper),
                                '/bin/bootin-original':(copy.deepcopy(bootin),saved)},overlay)
        ram0 = work/'ram0.ext2'
        _extract_initrd(volumes/NAMES['3'],ram0)
        if digest(ram0) != ORIGINAL_RAMROOT_SHA:
            raise ValueError('Extracted original RAM0 identity differs')
        ram_fs = overlay['Ext2'](ram0,scratch)
        ram_before = ram_fs.inventory()
        ram_identity = scripts(ram_before,RAM_SCRIPTS)
        with ram0.open('r+b') as stream:
            stream.truncate(ram0_bytes)
        resized = subprocess.run(['resize2fs',str(ram0)],capture_output=True,text=True,timeout=180)
        (work/'ram0-resize.log').write_text(resized.stdout+resized.stderr)
        if resized.returncode:
            raise RuntimeError('Cannot resize derived RAM0; see retained log')
        final_volumes = []
        lines = []
        for index, part in enumerate(PARTS):
            path = volumes/NAMES[part]
            row = {'part':part,'name':path.name,'loop':index,'access':'ro' if part in ('7','15') else 'rw',
                   'bytes':path.stat().st_size,'sha256':digest(path),'source_sha256':volume_inputs[part]['sha256'],
                   'changes':(['/simulation -> /dev/qemu-simulation','/sbin/insmod explicit adapter'] if part=='7' else
                              ['/bin/bootin.elf wrapper','/bin/bootin-original preserved ELF'] if part=='15' else [])}
            row['byte_identical_to_source'] = row['sha256']==row['source_sha256']
            final_volumes.append(row)
            lines.append(f"{index} {part} {path.name} {row['bytes']} {row['sha256']} {row['access']}\n")
        volume_list = work/'volume-list'
        volume_list.write_text(''.join(lines),encoding='ascii')
        sim_rows = []
        for path in sorted(simulation.rglob('*')):
            if path.is_file():
                sim_rows.append((path.relative_to(simulation).as_posix(),path.stat().st_size,digest(path),stat.S_IMODE(path.stat().st_mode)))
        simulation_list = work/'simulation-list'
        simulation_list.write_text(''.join(f'{name} {size} {sha} {mode:o}\n' for name,size,sha,mode in sim_rows),encoding='ascii')
        copy_bytes = sum(row['bytes'] for row in final_volumes)+sum(row[1] for row in sim_rows)
        memory = {'copy_bytes':copy_bytes,'devtmpfs_limit_bytes':copy_bytes+64*MIB,
                  'minimum_managed_ram_bytes':ram0_bytes+copy_bytes+512*MIB,
                  'minimum_available_ram_bytes':copy_bytes+256*MIB}
        config = work/'cold.conf'
        config.write_text(f"COLD_COPY_BYTES={copy_bytes+16*MIB}\nCOLD_DEV_BYTES={memory['devtmpfs_limit_bytes']}\n"
                          f"COLD_MANAGED_KIB={(memory['minimum_managed_ram_bytes']+1023)//1024}\n"
                          f"COLD_AVAILABLE_KIB={(memory['minimum_available_ram_bytes']+1023)//1024}\n",encoding='ascii')
        changes = {'/partitions':_link('/dev/qemu-partitions'),'/simulation':_link('/dev/qemu-simulation'),
                   '/sbin/insmod':_file(shim),'/sbin/cold-storage-bootstrap':_file(HERE/'guest/cold-storage-bootstrap'),
                   '/qemu/cold-start-audit':_file(audit),'/qemu/cold.conf':_file(config,0o600),
                   '/qemu/volume-list':_file(volume_list,0o600),'/qemu/simulation-list':_file(simulation_list,0o600)}
        for row in final_volumes:
            changes['/qemu-input/partitions/'+row['name']] = _file(volumes/row['name'],0o600)
        for name, size, sha, mode in sim_rows:
            changes['/qemu-input/simulation/'+name] = _file(simulation/name,mode)
        for path in list(changes):
            _parents(changes,path)
        _, ram_after = _edit_image(ram0,scratch,changes,overlay)
        scripts(ram_after,RAM_SCRIPTS)
        for path,node in ram_before['entries'].items():
            if path not in changes and ram_after['entries'].get(path) != node:
                raise ValueError('Original RAM0 path changed outside overlay: '+path)
        recheck(inputs)
        if {p.relative_to(source_sim).as_posix() for p in source_sim.rglob('*') if not p.is_dir()} != set(sim_inputs):
            raise ValueError('Source simulation inventory changed')
        if {p.name for p in partitions.iterdir()} != set(NAMES.values()):
            raise ValueError('Source partition inventory changed')
        artifact = output/'artifacts'
        for row in final_volumes:
            row['path'] = str(artifact/'volumes'/row['name'])
        command = f'root=/dev/ram0 rootfstype=ext2 rw noatime init=/sbin/cold-storage-bootstrap ramdisk_size={(ram0_bytes+1023)//1024} coldchain.profile={PROFILE} fullsystem.bootin-handoff=p15-wrapper'
        result = {'schema':1,'profile':PROFILE,'source':original['source'],'expected_im':expected_im(),
                  'ram0_image':str(artifact/'ram0.ext2'),'ram0_bytes':ram0_bytes,'ram0_sha256':digest(ram0),
                  'cold_cmdline':command,'inputs':inputs,'derived_volumes':final_volumes,
                  'simulation_dir':str(artifact/'simulation'),'script_identity':{'ram0':ram_identity,'p7':p7_identity},
                  'helper_selection':{'bootin-wrapper':{'prepared_source':sim_inputs['bootin-wrapper'],
                      'selected_source':wrapper,'selected_sha256':digest(simulation/'bootin-wrapper'),
                      'policy':'authoritative guest/bootin-wrapper with verified --original-elf protocol',
                      'prepared_copy_replaced':wrapper['sha256']!=sim_inputs['bootin-wrapper']['sha256']}},
                  'simulation_identity':{name:{'bytes':size,'sha256':sha,'mode':mode} for name,size,sha,mode in sim_rows},
                  'original_ram0':{'source_partition':'3','source_path':'/initrd.img',
                      'bytes':ORIGINAL_RAMROOT_BYTES,'sha256':ORIGINAL_RAMROOT_SHA},
                  'insmod_adapter':{'sha256':digest(shim),'house_sha256':insmod['sha256'],
                      'explicit_storage_refusals':['/kmod/crypt-emmc.ko','/kmod/emmc.ko'],'unsupported_returncode':78},
                  'failure_exits':{'bootstrap':'diagnostic shell, original init not executed',
                      'original_scripts':'original no-set-e continuation semantics preserved',
                      'unsupported_modules':'nonzero 78; never an empty success ACK'},
                  'memory':memory,'host_disk_required_bytes':disk_required,
                  'bootin_wrapper_experiment':{'schema':1,'case':'plain','virtual_sd_present':False,
                      'wrapper_sha256':digest(p15_wrapper),'original_elf_sha256':BOOTIN_SHA,
                      'derived_usr_sha256':digest(p15),'source_usr_sha256':volume_inputs['15']['sha256']},
                  'adaptations':['explicit kernel init bootstrap','temporary bootstrap proc mount',
                      'devtmpfs size limit and verified ordinary-file loop backing',
                      'original RAM init interpreted by busybox sh -x in PID1',
                      'explicit insmod refusal/house policy in RAM0 and p7',
                      'p7 simulation symlink','original BusyBox freeramdisk result and released-prefix observer',
                      'p15 wrapper and saved original ELF',
                      'authoritative house bootin wrapper replaces prepared helper copy; SHA256 protocol checked',
                      'existing observer models; large logs routed to /log/qemu'],
                  'coverage_expected':['original-init-script','p7-root-mount','original-pivot-and-chroot',
                      'devtmpfs-moved-with-loop-backing','old-initrd-unmounted','ram0-release-result',
                      'original-init2-process','bootin-im-appfw-identities'],
                  'guest_evidence':{key:None for key in ('original_init','pivot_chroot','old_root_unmounted',
                      'ram0_released','init2','bootin','im','appfw')},
                  'capture_verified':False,'wbi_resume_verified':False,'build_verified':True,
                  'launch_requirements':['raw ext2; remove rdinit=/init and old init/root overrides',
                      'apply existing high-DDR, GIC, timer and memrsv adapters explicitly',
                      'managed RAM must satisfy memory.minimum_managed_ram_bytes',
                      'exclusive runtime, QMP and owner; no loop18 SD handoff; no host init2 command']}
        if not any(scratch.iterdir()):
            scratch.rmdir()
        work.rename(artifact)
        with (output/'manifest.json').open('x') as stream:
            json.dump(result,stream,indent=2);stream.write('\n')
        return result
    except Exception as error:
        with (output/'failure.json').open('x') as stream:
            json.dump({'schema':1,'profile':PROFILE,'build_verified':False,
                       'error':type(error).__name__+': '+str(error),'work':str(work)},stream,indent=2)
            stream.write('\n')
        raise


def launch_script(text, coldmanifest):
    """Adapt a captured full-system board script; never write or launch it here.

    The caller owns QMP quit, serial collection and the isolated output directory.
    No -S pause is introduced. Unsupported template revisions fail explicitly.
    """
    if coldmanifest.get('schema') != 1 or coldmanifest.get('profile') != PROFILE or coldmanifest.get('build_verified') is not True:
        raise ValueError('Expected a completed cold-chain build manifest')
    paused = any(not text[:match.start()].rstrip().endswith(('[[','['))
                 for match in re.finditer(r'(^|[\s(])-S(?=[\s)]|$)',text))
    if '# COLD_INIT_CHAIN_RAW_EXT2' in text or paused:
        raise ValueError('Already adapted or paused QEMU template refused')
    command = coldmanifest['cold_cmdline']
    if not re.fullmatch(r'[A-Za-z0-9_./=,:+ -]+',command) or 'coldchain.profile='+PROFILE not in command.split() or 'rdinit=' in command or 'ro' in command.split():
        raise ValueError('Invalid cold kernel command line')
    # Old build artifacts also need the original kemco RAM-root mount policy.
    for parameter in ('rw','noatime'):
        if parameter not in command.split():
            command += ' '+parameter
    def replace(old, new):
        nonlocal text
        if text.count(old) != 1:
            raise ValueError('Unsupported raw-ext2 board template anchor: '+old[:90])
        text = text.replace(old,new,1)
    guard = '''# COLD_INIT_CHAIN_RAW_EXT2: explicit owner; timeout TERM/KILL is not cleanup.
[[ "${QEMU_UI_LIVE:-0}" == 1 && "${QEMU_OUTPUT_DIR:-}" == /* ]] || {
  echo 'Cold chain requires an owned QMP run and absolute QEMU_OUTPUT_DIR' >&2; exit 2;
}
for cold_parameter in ${QEMU_EXTRA_CMDLINE:-}; do
  case "$cold_parameter" in
    ro|rw|noatime|root=*|rootfstype=*|init=*|rdinit=*|ramdisk_size=*|mem=*|initrd=*|coldchain.profile=*|fullsystem.bootin-handoff=*|fullsystem.attach-sd=*|fullsystem.bootin-sd=*)
      echo 'Conflicting cold-chain kernel/profile override' >&2; exit 2;;
  esac
done
'''
    replace('set -euo pipefail\n','set -euo pipefail\n'+guard)
    replace("cmdline='console=ttyAMA0 earlycon=pl011,0x09000000 loglevel=8 root=/dev/ram0 init=/bin/sh'",
            'cmdline='+shlex.quote('console=ttyAMA0 earlycon=pl011,0x09000000 loglevel=8 '+command))
    replace('test_initrd="${5:-$bootfs/initrd.img}"',
            'test_initrd="${5:-$bootfs/initrd.img}"\n[[ "$test_initrd" == '+shlex.quote(coldmanifest['ram0_image'])+' ]] || { echo "Cold RAM0 path differs" >&2; exit 2; }')
    replace('[[ "$test_initrd" != *.cpio && "$test_initrd" != *.cpio.gz ]]',
            '[[ "$test_initrd" != *.ext2 ]]')
    replace('Native ramfb requires high-DDR boot memory and cpio initramfs',
            'Native ramfb requires high-DDR boot memory and cold ext2 RAM0')
    replace('    cmdline+=" ramdisk_size=$image_kib"\n','')
    replace('if [[ "$test_initrd" == *.cpio || "$test_initrd" == *.cpio.gz ]]; then',
            'if [[ "$high_ddr" == 1 ]]; then')
    replace("      cmdline+=' rdinit=/init'\n",'')
    replace('if [[ "${QEMU_PREPARE_ONLY:-0}" == 1 ]]; then',
            'printf \'%s\\n\' "$cmdline" > "$output_dir/cold-cmdline.txt"\nif [[ "${QEMU_PREPARE_ONLY:-0}" == 1 ]]; then')
    # Preserve the tested DDR/physical mapping; bootstrap checks managed capacity.
    replace('ddr_size = 0x200000000  # explicit full-dump experiment: 8 GiB guest DDR',
            'ddr_size = 0x200000000  # explicit full-dump experiment: 8 GiB guest DDR')
    replace('memory_config=24576','memory_config=24576')
    # ARM's default -initrd path stores size in int; generic raw loader uses ssize_t.
    replace('-kernel /kernel.img -initrd /initrd.img','-kernel /kernel.img')
    return text


def prepare_launch(runtime_analysis, manifest, launch_output):
    """Prepare a private raw-ext2 launch and DTB; return command/env, never a VM.

    QEMU sources/tools are shared read-only through the existing bwrap contract.
    The caller must collect serial/QMP evidence and finish this owner with QMP quit.
    """
    runtime = plain(runtime_analysis,directory=True)
    output = Path(os.path.abspath(launch_output))
    plain(output.parent,directory=True)
    if output.is_relative_to(runtime) or runtime.is_relative_to(output) or os.path.lexists(output):
        raise ValueError('Launch output must be a new separate directory')
    source_manifest = json.loads(plain(runtime/'full-system.json').read_text())
    if source_manifest.get('source') != manifest.get('source'):
        raise ValueError('Launch source class differs from cold build')
    if digest(manifest['ram0_image']) != manifest['ram0_sha256']:
        raise ValueError('Built RAM0 SHA256 differs before launch')
    # Build-source hashes are historical provenance; RAM0 SHA binds their result.
    recheck([row for row in manifest['inputs'] if row['role'] != 'cold-source'])
    template = plain(runtime/'qemu-kernel-probe.sh')
    text = launch_script(template.read_text(),manifest)
    sources = (runtime.parent/'sources').resolve(strict=True)
    plain(sources,directory=True)
    assets = ['boot-handoff.bin','boards/virt-four.dtb',
              'unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin',
              'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt']
    bound = [binding(template,'board-script'),*[binding(runtime/name,'launch-asset') for name in assets]]
    kernel = next(row for row in bound if row['path'].endswith('/vmlinux.bin'))
    if kernel['sha256'] != KERNEL_SHA:
        raise ValueError('Original 2.01 kernel SHA256 differs')
    output.mkdir(mode=0o700)
    try:
        analysis = output/'runtime/analysis'
        analysis.mkdir(parents=True)
        (analysis.parent/'sources').symlink_to(sources,target_is_directory=True)
        for name in assets:
            row = next(row for row in bound if row['path']==str(runtime/name))
            clone(runtime/name,analysis/name,row['sha256'])
        script = analysis/'qemu-kernel-cold.sh'
        script.write_text(text)
        script.chmod(0o700)
        command = ['bash',str(script),'4096',str(analysis/'boards/virt-four.dtb'),'1','1',manifest['ram0_image']]
        env = {'PATH':os.defpath,'LC_ALL':'C','PYTHONDONTWRITEBYTECODE':'1',
               'QEMU_UI_LIVE':'1','QEMU_OUTPUT_DIR':str(output/'run'),'QEMU_TIMEOUT_SECONDS':'0',
               'QEMU_FULL_BOOT_SHIM':'1','QEMU_FULL_SMP':'4','QEMU_ARCH_CNTFRQ':'2000000',
               'QEMU_FULL_USB_INIT':'original',
               'QEMU_TCG_THREAD':'single','SONY_TIMER_MODEL':'1','SONY_DMM_SERVICE':'1',
               'MENU_NATIVE_WINDOW':'1','QEMU_NATIVE_DISPLAY':'none','QEMU_FULL_ADAPTER_DIR':str(HERE),
               'QEMU_TRACE_FLAGS':'guest_errors,unimp'}
        with (output/'prepare.stdout').open('x') as out,(output/'prepare.stderr').open('x') as err:
            prepared = subprocess.run(command,env={**env,'QEMU_PREPARE_ONLY':'1'},stdin=subprocess.DEVNULL,
                                      stdout=out,stderr=err,timeout=60)
        if prepared.returncode:
            raise RuntimeError('Cold board preparation failed; inspect prepare.stderr')
        recheck(bound)
        result = {'schema':1,'profile':PROFILE,'source':manifest['source'],'command':command,'env':env,
                  'runtime_analysis':str(analysis),'script':str(script),'script_sha256':digest(script),
                  'dtb':str(output/'run/virt.dtb'),'dtb_sha256':digest(output/'run/virt.dtb'),
                  'cold_cmdline':manifest['cold_cmdline'],
                  'cmdline':(output/'run/cold-cmdline.txt').read_text().strip(),
                  'cmdline_file':str(output/'run/cold-cmdline.txt'),'template_inputs':bound,'guest_ddr_bytes':0x200000000,
                  'qmp_socket':str(output/'run/qmp.sock'),'qmp_parent':str(output/'run'),
                  'qmp_connect_hint':'open qmp_parent, connect /proc/self/fd/<dirfd>/qmp.sock; long AF_UNIX paths need this',
                  'launch_adaptations':{'sony_physical_loader_executed':False,'gic_boot_shim':True,
                      'boot_entry':0x400010000,'kernel_load_address':0x400080000,'fixed_dtb_address':0x400002000,
                      'initrd_load_address':0x440000000,'default_arm_initrd_parser_used':False,
                      'ram0_root_flags':['rw','noatime'],'p7_root_flags':'original fstab.root ro,nodiratime,noatime,sync',
                      'cpu':'cortex-a35','cpus':4,'counter_hz':2000000,
                      'kernelargs_policy':'explicit cold command plus kemco memrsv excluding tmonitor; other kemco arguments omitted',
                      'original_kemco':str(analysis/assets[-1]),
                      'original_kemco_sha256':digest(analysis/assets[-1]),
                      'initcall_blacklist':[word.split('=',1)[1].split(',') for word in (output/'run/cold-cmdline.txt').read_text().split() if word.startswith('initcall_blacklist=')],
                      'ramfb':'generic virtual display with explicit reserved RAM; physical display not verified'},
                  'guest_started':False,'qemu_initially_paused':False,
                  'owner_policy':'caller owns serial/QMP, bounded observation and normal QMP quit; no timeout signals'}
        (output/'launch.json').write_text(json.dumps(result,indent=2)+'\n')
        return result
    except Exception as error:
        (output/'failure.json').write_text(json.dumps({'guest_started':False,'error':str(error)},indent=2)+'\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-analysis',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ram0-bytes',type=int)
    args = parser.parse_args()
    print(json.dumps(build(args.runtime_analysis,args.output,ram0_bytes=args.ram0_bytes),indent=2))


if __name__ == '__main__':
    main()
