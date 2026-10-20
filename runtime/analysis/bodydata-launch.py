#!/usr/bin/env python3
"""Import official BODYDATA with fwtool, then open the existing native window.

Supported runtime: pinned ILCE-7CM2 2.01 ALLLANG only. No capture claim.
"""
import argparse
import fcntl
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True
KIT = Path(__file__).absolute().parent
if (KIT/'vendor/host-python').is_dir():
    sys.path.insert(0,str(KIT/'vendor/host-python'))
RESERVE = 1024 ** 3
SCHEMA = 1


def safe_path(path):
    path = Path(os.path.abspath(path))
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise ValueError(f'Symlink forbidden: {component}')
    return path


def regular(path):
    path = safe_path(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f'Expected regular file: {path}')
    return path


def digest(path):
    with regular(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def discover(given=None, base=KIT):
    if given is not None:
        path = safe_path(given)
        if not path.is_dir():
            return regular(path)
        roots = [path]
    else:
        roots = list(dict.fromkeys([Path.cwd()/'incoming/bodydata', base.parent.parent/'incoming/bodydata']))
    candidates = []
    for root in roots:
        safe_path(root)
        if root.exists():
            candidates.extend(p for p in root.iterdir() if p.name.lower() == 'bodydata.dat')
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise ValueError(f'Expected exactly one BODYDATA.DAT; found {len(candidates)} in {roots}. Use --bodydata PATH.')
    return regular(candidates[0])


def space(path, needed):
    free = shutil.disk_usage(path).free
    if free < needed + RESERVE:
        raise ValueError(f'Insufficient space at {path}: free={free}, need={needed}+reserve={RESERVE}')


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')


def inventory(root):
    result = {}
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = safe_path(Path(parent)/name)
            rel = path.relative_to(root).as_posix()
            if rel == 'success.json':
                continue
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                result[rel] = {'directory': True}
            elif stat.S_ISREG(mode):
                result[rel] = {'size': path.stat().st_size, 'sha256': digest(path)}
            else:
                raise ValueError(f'Special cache entry: {path}')
    return result


def verify_cache(root, sha):
    safe_path(root)
    manifest = json.loads(regular(root/'success.json').read_text())
    if (manifest.get('schema'), manifest.get('package_sha256')) != (SCHEMA, sha):
        raise ValueError(f'Unknown cache manifest: {root}')
    if inventory(root) != manifest.get('files'):
        raise ValueError(f'Changed cache content: {root}')
    return manifest


def sdk_modules(sdk):
    sdk = safe_path(sdk)
    for name in ('fwtool/sony/dat.py', 'fwtool/sony/fdat.py'):
        regular(sdk/name)
    sys.path.insert(0, str(sdk))
    dat = importlib.import_module('fwtool.sony.dat')
    fdat = importlib.import_module('fwtool.sony.fdat')
    if not Path(dat.__file__).absolute().is_relative_to(sdk):
        raise ValueError('A different fwtool is already imported')
    return dat, fdat


def supported(info):
    print(f'IDENTIFIED model={info.model:#x} version={info.version} region={info.region}', flush=True)
    if (info.model, info.version, info.region, info.isAccessory) != (0x20030014, '2.01', 0, False):
        raise ValueError('Unsupported firmware: runtime accepts only ILCE-7CM2 2.01 ALLLANG; pins unchanged')


def member_name(name):
    while name.startswith('./'):
        name = name[2:]
    name = name.rstrip('/')
    if name in ('', '.'):
        return None
    parts = name.split('/')
    if name.startswith('/') or '\\' in name or any(p in ('', '.', '..') or ':' in p or any(ord(c)<32 for c in p) for p in parts):
        raise ValueError(f'Unsafe archive path: {name!r}')
    return name


def extract_tar(stream, root, limit):
    root.mkdir()
    total, seen, skipped = 0, set(), []
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode='r:') as archive:
        for member in archive:
            name = member_name(member.name)
            if name is None:
                if not member.isdir():
                    raise ValueError('Non-directory archive root')
                continue
            if name in seen or len(seen) >= 100000:
                raise ValueError('Duplicate archive member or too many entries')
            seen.add(name)
            target = safe_path(root/name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isreg():
                if member.size < 0:
                    raise ValueError('Negative archive size')
                total += member.size
                if total > limit:
                    raise ValueError('Archive expansion exceeds space budget')
                space(root, member.size)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output, 1024*1024)
                if target.stat().st_size != member.size:
                    raise ValueError('Truncated archive member')
                target.chmod(0o444)
            else:
                # fwtool.writeFileTree also skips these; never create host links/devices.
                skipped.append({'path': name, 'type': member.type.decode('ascii'), 'link': member.linkname})
    return skipped


def unpack(package, stage, sdk, expected_sha):
    dat, fdat = sdk_modules(sdk)
    def stamp():
        s = regular(package).stat()
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    before = stamp()
    with package.open('rb') as source:
        if not dat.isDat(source):
            raise ValueError('Expected Sony BODYDATA DAT container')
        data = dat.readDat(source)
        crypter, decrypted = fdat.decryptFdat(data.firmwareData)
        print(f'Decrypting with fwtool {crypter}', flush=True)
        with (stage/'firmware.fdat').open('xb') as output:
            shutil.copyfileobj(decrypted, output, 1024*1024)
    if stamp() != before or digest(package) != expected_sha:
        raise ValueError('BODYDATA changed during read')
    with (stage/'firmware.fdat').open('rb') as stream:
        info = fdat.readFdat(stream)
        supported(info)
        skipped = extract_tar(info.firmware, stage/'firmware-root', package.stat().st_size*8)
        write_json(stage/'archive-skipped.json', skipped)
    return {'model': info.model, 'version': info.version, 'region': info.region, 'crypter': crypter}


def cache_package(package, cache, sdk, unpacker=unpack):
    cache = safe_path(cache)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        cache.mkdir(mode=0o700)
        write_json(cache/'owner.json', {'tool': 'bodydata-launch', 'schema': SCHEMA})
    if json.loads(regular(cache/'owner.json').read_text()) != {'tool': 'bodydata-launch', 'schema': SCHEMA}:
        raise ValueError(f'Unknown cache directory: {cache}')
    sha = digest(package)
    target = cache/sha
    # Lock the ownership marker, without creating or truncating another file.
    with regular(cache/'owner.json').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.path.lexists(target):
            verify_cache(target, sha)
            print(f'CACHE_VERIFIED {target}', flush=True)
            return target
        space(cache, package.stat().st_size*10)
        stage = Path(tempfile.mkdtemp(prefix=f'.{sha}.staging-', dir=cache))
        print(f'STAGING {stage}', flush=True)
        try:
            info = unpacker(package, stage, sdk, sha)
            files = inventory(stage)
            write_json(stage/'success.json', {'schema': SCHEMA, 'package_sha256': sha, 'identity': info, 'files': files})
            verify_cache(stage, sha)
            if os.path.lexists(target):
                raise ValueError(f'Refusing existing cache: {target}')
            stage.rename(target)
            return target
        except Exception as exc:
            # A failed stage is never published and never retains a success marker.
            marker = stage/'success.json'
            if marker.is_file() and not marker.is_symlink():
                marker.unlink()
            write_json(stage/'failure.json', {'error': str(exc)})
            print(f'UNPACK_FAILED preserved {stage}', file=sys.stderr)
            raise


def prepare(entry, runtime, kit, runner=subprocess.run):
    runtime, kit = safe_path(runtime), safe_path(kit)
    analysis = runtime/'analysis'
    if not analysis.is_dir():
        raise ValueError('Runtime must already contain the main startup scripts and guest overlay')
    script = regular(kit/'prepare-assets.py')
    common = [sys.executable, str(script), '--runtime', str(runtime)]
    source = ['--firmware-root', str(entry/'firmware-root')]
    runner(common+source+['--fdat',str(entry/'firmware.fdat'),'--verify-inputs'],check=True)
    # Verify the selected package even when an older runtime is already installed.
    if os.path.lexists(analysis/'native-assets.json'):
        runner(common+['--check-runtime'], check=True)
    else:
        space(analysis, 2*1024**3)
        runner(common+source+['--fdat', str(entry/'firmware.fdat')], check=True)
    runner(common+source+['--install-language-fonts'], check=True)
    runner(common+['--check-runtime'], check=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bodydata', type=Path, help='file or directory containing one BODYDATA.DAT')
    parser.add_argument('--cache', type=Path, default=KIT.parent/'bodydata-cache')
    parser.add_argument('--fwtool', type=Path, default=KIT/'vendor/fwtool-sdk', help='complete fwtool SDK root, not FAT-only subset')
    parser.add_argument('--runtime', type=Path, default=KIT.parent)
    parser.add_argument('--runtime-analysis', type=Path, default=KIT, help='integration/testing: existing native analysis scripts')
    parser.add_argument('--prepare-only', action='store_true', help='import/check assets and fonts without starting a VM')
    parser.add_argument('--overwrite-dir',type=Path,help='relative guest paths to replace in a derived initramfs; default product overwrite/')
    parser.add_argument('--sd-image',type=Path,help='regular virtual FAT image to copy into this guest; physical devices are not accepted')
    args = parser.parse_args(argv)
    try:
        if not args.prepare_only and safe_path(args.runtime_analysis).parent != safe_path(args.runtime):
            raise ValueError('Native entry uses its adjacent runtime; runtime-analysis must be RUNTIME/analysis')
        package = discover(args.bodydata)
        print(f'BODYDATA {package}', flush=True)
        entry = cache_package(package, args.cache, args.fwtool)
        prepare(entry, args.runtime, args.runtime_analysis)
        print('BODYDATA_PREPARED ILCE-7CM2 2.01 ALLLANG', flush=True)
        if not args.prepare_only:
            launch_env=dict(os.environ)
            if args.overwrite_dir is not None:
                launch_env['A7C2_OVERWRITE_DIR']=str(safe_path(args.overwrite_dir))
            if args.sd_image is not None:
                launch_env['A7C2_SD_IMAGE']=str(regular(args.sd_image))
            return subprocess.run([sys.executable, str(regular(args.runtime_analysis/'camera_ui.py'))],
                                  check=False,env=launch_env).returncode
        return 0
    except Exception as exc:
        print(f'BODYDATA launch failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
