#!/usr/bin/env python3
"""Create a private, separate dump runtime from verified read-only image inputs."""
import argparse
import hashlib
import importlib.util
import json
import os
import runpy
from pathlib import Path
import shutil
import stat
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
NATIVE_INPUT = runpy.run_path(str(HERE/'native-input.py'))['resolve']()
ANALYSIS = NATIVE_INPUT / 'runtime/analysis'
sys.path.insert(0, str(ANALYSIS))
spec = importlib.util.spec_from_file_location('asset_helpers', ANALYSIS / 'prepare-assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)
from fwtool.archive.fat import readFat

NAMES = {'a7c2-rootfs.img', 'a7c2-usr.img'} | {
    f'nflasha{n}.img' for n in ('1','2','3','4','5','6','8','10','11','12','13','18','22','23','30','B0','B1')}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ordinary(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected an ordinary file: ' + str(path))
    return path


def fat_extract(image, destination, wanted=None):
    seen = set()
    with image.open('rb') as stream:
        for entry in readFat(stream):
            name = entry.path.removeprefix('/')
            relative = Path(name)
            if not name or relative.is_absolute() or '..' in relative.parts or name in seen:
                raise ValueError('Unsafe/duplicate FAT path')
            seen.add(name)
            if wanted is not None and name not in wanted:
                continue
            out = destination / relative
            if stat.S_ISDIR(entry.mode):
                out.mkdir(parents=True, exist_ok=True)
            elif stat.S_ISREG(entry.mode):
                if entry.size > 128 * 1024 * 1024:
                    raise ValueError('Oversized FAT content')
                data = entry.contents.read(entry.size + 1)
                if len(data) != entry.size:
                    raise ValueError('Truncated FAT content')
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            else:
                raise ValueError('Unexpected selected FAT special file')
    if wanted is not None and not set(wanted) <= seen:
        raise ValueError('Missing required FAT content')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dump', type=Path, required=True)
    parser.add_argument('--runtime',type=Path,default=HERE/'runtime')
    parser.add_argument('--source-class',choices=('private-device-dump','official-bodydata-derived'),default='private-device-dump')
    args = parser.parse_args()
    source = args.dump.resolve(strict=True)
    runtime = args.runtime.resolve()
    if os.path.lexists(runtime/'analysis'):
        parser.error('Refusing an existing runtime; retain it as evidence and select a fresh checkout')
    source_manifest=json.loads(ordinary(source / 'manifest.json').read_text())
    if args.source_class=='official-bodydata-derived' and source_manifest.get('source')!='official-bodydata-derived':
        raise ValueError('Official runtime requires a separately generated official-source manifest')
    records = source_manifest['images']
    if {r['name'] for r in records} != NAMES or len(records) != len(NAMES):
        raise ValueError('Expected the complete 19-partition dump inventory')
    inputs={}
    for record in records:
        filename=record.get('file',record['name'])
        if not isinstance(filename,str) or Path(filename).name!=filename or filename in ('.','..'):
            raise ValueError('Partition input must be an ordinary basename')
        path = ordinary(source / filename)
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError('Dump image identity differs: ' + path.name)
        inputs[record['name']]=path
    # This experiment's observers depend on the exact original 2.01 application ABI.
    # The dump remains separate from the official-importer schema and private state.
    runtime.mkdir(parents=True,exist_ok=True)
    out = runtime / 'analysis'
    out.mkdir()
    root = out / 'root'
    root.mkdir()
    logs = out / 'preparation'
    logs.mkdir()
    result = subprocess.run(['debugfs', '-R', 'rdump / root', str(inputs['a7c2-rootfs.img'])],
                            cwd=out, capture_output=True, text=True, env={**os.environ, 'LC_ALL':'C'})
    (logs / 'root-debugfs.log').write_text(result.stdout + result.stderr)
    errors = [line for line in (result.stdout+result.stderr).splitlines() if line and
              not line.startswith(('debugfs ', 'dump_file: Operation not permitted while changing ownership of ',
                                   'rdump: Operation not permitted while changing ownership of '))]
    if result.returncode or errors:
        raise RuntimeError('Root dump extraction failed; see private preparation log')
    assets.guest_links(root)
    anchors = {
        'appFw':'2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
        'libObj':'c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc',
        'libgpe':'80fc6236379933f80c2689aa002e0cf39483da8d45e876705d2a427cd1a2a7d1',
    }
    for name, sha in anchors.items():
        target = logs/(name+'.identity.so')
        result = subprocess.run(['debugfs','-R',f'dump /lib/{name}.so preparation/{name}.identity.so',
                                 str(inputs['a7c2-usr.img'])],cwd=out,capture_output=True,text=True)
        (logs/(name+'-debugfs.log')).write_text(result.stdout+result.stderr)
        if result.returncode or digest(target) != sha:
            raise ValueError('Dump application ABI differs: '+name)
        target.unlink()  # Only the private temporary verification copy.
    for name in ('simulation','partitions','proc','sys','dev','mnt','tmp_wbshd'):
        (root/name).mkdir(exist_ok=True)
    # These are byte-identical copies, never hard links to evidence images.
    for record in records:
        subprocess.run(['cp', '--reflink=auto', '--sparse=always', str(inputs[record['name']]),
                        str(root/'partitions'/record['name'])], check=True)
        if digest(root/'partitions'/record['name']) != record['sha256']:
            raise ValueError('Copied partition differs: ' + record['name'])
    unpacked = out / 'unpacked/firmware.tar_unpacked'
    boot = unpacked / '0700_part_image/dev/nflasha3_unpacked'
    fat_extract(inputs['nflasha3.img'], boot, {'vmlinux.bin'})
    setting = unpacked / '0800_appli/setting'
    fat_extract(inputs['nflasha2.img'], setting, {'kemco.txt'})
    if digest(boot/'vmlinux.bin') != '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2':
        raise ValueError('This profile requires the verified 2.01 kernel')
    # Only project-generated helpers are copied, with a closed list and hash record.
    helpers = ('seed-power-on','seed-date-clock','menu-regs','menu-readmem','headless-osd-export','ramfb-viewer')
    for name in helpers:
        src = ordinary(ANALYSIS/'menu-root/simulation'/name)
        shutil.copy2(src, root/'simulation'/name)
        (root/'simulation'/name).chmod(0o755)
    shutil.copy2(ordinary(ANALYSIS/'menu-observe.so'), root/'simulation/menu-observe.so')
    shutil.copy2(ordinary(ANALYSIS/'libIMDB-menu.so'), root/'simulation/libIMDB-menu.so')
    # Keep the original root files alongside explicit VM adapters; no original script is edited.
    (root/'sbin/insmod').unlink()
    shutil.copy2(HERE/'guest/insmod', root/'sbin/insmod')
    shutil.copy2(HERE/'guest/bootin-wrapper', root/'simulation/bootin-wrapper')
    shutil.copy2(HERE/'guest/init', root/'init')
    shutil.copy2(HERE/'guest/driver-audit.sh', root/'simulation/driver-audit.sh')
    for path in (root/'sbin/insmod',root/'simulation/bootin-wrapper',root/'init',root/'simulation/driver-audit.sh'):
        path.chmod(0o755)
    # Existing sandbox and device-tree builder are copied, not used through the menu runtime lock.
    shutil.copy2(ANALYSIS/'qemu-kernel-probe.sh', out/'qemu-kernel-probe.sh')
    (out/'qemu-kernel-probe.sh').chmod(0o755)
    text = (out/'qemu-kernel-probe.sh').read_text()
    old = "ddr_size = 0x140000000 if sys.argv[4].endswith(('.cpio', '.cpio.gz')) else 0x100000000"
    if text.count(old) != 1:
        raise ValueError('Board adapter source changed; review the full-dump memory plan')
    text = text.replace(old, "ddr_size = 0x200000000  # explicit full-dump experiment: 8 GiB guest DDR")
    (out/'qemu-kernel-probe.sh').write_text(text)
    (out/'qemu-virt-board').mkdir()
    shutil.copy2(ANALYSIS/'qemu-virt-board/virt-packed.dtb', out/'qemu-virt-board/virt-packed.dtb')
    if runtime!=HERE/'runtime' and not os.path.lexists(runtime/'sources'):
        (runtime/'sources').symlink_to(HERE/'runtime/sources', target_is_directory=True)
    files = {}
    for path in root.rglob('*'):
        if path.is_file() and not path.is_symlink() and 'partitions' not in path.relative_to(root).parts:
            files[path.relative_to(root).as_posix()] = digest(path)
    manifest = {'schema':1, 'source':args.source_class, 'images':records,
                'bodydata_sha256':source_manifest.get('bodydata_sha256'),
                'user_overwrite':source_manifest.get('user_overwrite'),
                'helper_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip(),
                'derived_files':files, 'root_script_policy':'unchanged init2/fstab/insmod_drv2, explicit VM adapters',
                'partition_write_policy':'guest RAM copy only', 'guest_ddr_bytes':0x200000000}
    (out/'full-system.json').write_text(json.dumps(manifest,indent=2)+'\n')
    subprocess.run([sys.executable,str(HERE/'build-full-system.py'),'--runtime',str(runtime)],check=True)
    print('FULLSYSTEM_PREPARED', runtime, 'images=19', 'source='+args.source_class)
    print('CPIO_SHA256', digest(out/'full-system.cpio'))


if __name__ == '__main__':
    main()
