#!/usr/bin/env python3
"""Import official BODYDATA with fwtool, then open the existing native window.

Supported runtime: pinned ILCE-7CM2 2.01 ALLLANG only. No capture claim.
"""
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
        raise ValueError(f'Expected exactly one BODYDATA.DAT; found {len(candidates)} in {roots}. Set A7C2_BODYDATA in a7c2.env or environment.')
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


def _save_quick_cache(cache, package, package_sha):
    st = regular(package).stat()
    meta = {'package': str(package.resolve()), 'size': st.st_size,
            'mtime_ns': st.st_mtime_ns, 'package_sha256': package_sha}
    tmp = cache / f'.quick-cache.{os.getpid()}.tmp'
    tmp.unlink(missing_ok=True)
    write_json(tmp, meta)
    tmp.replace(cache / 'quick-cache.json')


def cache_package(package, cache, sdk, unpacker=unpack, *, verify_sha=True):
    package, cache, sdk = regular(package), safe_path(cache), safe_path(sdk)
    cache.parent.mkdir(parents=True, exist_ok=True)
    if not cache.exists():
        cache.mkdir(mode=0o700)
        write_json(cache/'owner.json', {'tool': 'bodydata-launch', 'schema': SCHEMA})
    if json.loads(regular(cache/'owner.json').read_text()) != {'tool': 'bodydata-launch', 'schema': SCHEMA}:
        raise ValueError(f'Unknown cache directory: {cache}')
    # Lock the ownership marker, without creating or truncating another file.
    with regular(cache/'owner.json').open('rb') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not verify_sha:
            quick_file = cache / 'quick-cache.json'
            if quick_file.is_file() and not quick_file.is_symlink():
                try:
                    quick = json.loads(quick_file.read_text())
                    st = package.stat()
                    cand = cache / quick.get('package_sha256', '')
                    if (quick.get('package') == str(package.resolve()) and
                            quick.get('size') == st.st_size and
                            quick.get('mtime_ns') == st.st_mtime_ns and
                            (cand / 'success.json').is_file() and
                            (cand / 'firmware.fdat').is_file() and
                            (cand / 'firmware-root').is_dir()):
                        print(f'CACHE_FASTPATH {cand}', flush=True)
                        return cand
                except (OSError, json.JSONDecodeError, ValueError):
                    pass
        sha = digest(package)
        target = cache/sha
        if os.path.lexists(target):
            if verify_sha:
                verify_cache(target, sha)
                print(f'CACHE_VERIFIED {target}', flush=True)
            else:
                regular(target / 'success.json')
                print(f'CACHE_FASTPATH {target}', flush=True)
            _save_quick_cache(cache, package, sha)
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
            _save_quick_cache(cache, package, sha)
            return target
        except Exception as exc:
            # A failed stage is never published and never retains a success marker.
            marker = stage/'success.json'
            if marker.is_file() and not marker.is_symlink():
                marker.unlink()
            write_json(stage/'failure.json', {'error': str(exc)})
            print(f'UNPACK_FAILED preserved {stage}', file=sys.stderr)
            raise


def _fonts_present(analysis):
    fonts_dir = analysis / 'menu-root/simulation/language-fonts'
    return fonts_dir.is_dir() and sum(1 for p in fonts_dir.iterdir() if p.is_file()) == 3


def prepare(entry, runtime, kit, runner=subprocess.run, *, verify_sha=True):
    runtime, kit = safe_path(runtime), safe_path(kit)
    analysis = runtime/'analysis'
    if not analysis.is_dir():
        raise ValueError('Runtime must already contain the main startup scripts and guest overlay')
    fast_stamp = analysis / '.prepare-fast.json'
    if not verify_sha and (analysis / 'native-assets.json').is_file() and _fonts_present(analysis) and fast_stamp.is_file():
        try:
            recorded = json.loads(fast_stamp.read_text())
            if recorded.get('entry') == entry.name:
                return
        except (OSError, json.JSONDecodeError):
            pass
    script = regular(kit/'prepare-assets.py')
    common = [sys.executable, str(script), '--runtime', str(runtime)]
    source = ['--firmware-root', str(entry/'firmware-root')]
    if verify_sha:
        runner(common+source+['--fdat',str(entry/'firmware.fdat'),'--verify-inputs'],check=True)
    # Verify the selected package even when an older runtime is already installed.
    if os.path.lexists(analysis/'native-assets.json'):
        if verify_sha:
            runner(common+['--check-runtime'], check=True)
    else:
        space(analysis, 2*1024**3)
        runner(common+source+['--fdat', str(entry/'firmware.fdat')], check=True)
    if verify_sha or not _fonts_present(analysis):
        runner(common+source+['--install-language-fonts'], check=True)
    if verify_sha:
        runner(common+['--check-runtime'], check=True)
    if (analysis / 'native-assets.json').is_file() and _fonts_present(analysis):
        try:
            tmp = analysis / f'.prepare-fast.{os.getpid()}.tmp'
            tmp.unlink(missing_ok=True)
            write_json(tmp, {'entry': entry.name})
            tmp.replace(fast_stamp)
        except OSError:
            pass


def _parse_bool_env(name, default):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return bool(default)
    normalized = str(raw).strip().lower()
    if normalized in ('1', 'true', 'yes', 'on'):
        return True
    if normalized in ('0', 'false', 'no', 'off'):
        return False
    raise ValueError(f'Unknown {name} value: {raw}')


def _env_path(name, default=None):
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return Path(str(raw).strip())


def _resolve_cold_flag():
    value = os.environ.get('A7C2_COLD_FLAG')
    if value is None or not str(value).strip():
        return 'force'
    normalized = str(value).strip().lower()
    if normalized in ('1', 'force'):
        return 'force'
    if normalized in ('0', 'strict'):
        return 'strict'
    if normalized == 'clear':
        return 'clear'
    raise ValueError(f'Unknown A7C2_COLD_FLAG mode: {value}')


def _resolve_verify_sha():
    return _parse_bool_env('A7C2_VERIFY_SHA', False)


def _resolve_boot_profile():
    raw = os.environ.get('A7C2_BOOT_PROFILE')
    profile = str(raw).strip() if raw is not None and str(raw).strip() else 'original-init-cold'
    if profile not in ('original-init-cold', 'direct-bootin'):
        raise ValueError(f'Unknown A7C2_BOOT_PROFILE: {profile} (expected original-init-cold or direct-bootin)')
    return profile


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if args:
        print('bodydata-launch.py 不接受命令行参数；请编辑 a7c2.env 或通过环境变量配置（例如 A7C2_BODYDATA、A7C2_BOOT_PROFILE、A7C2_VERIFY_SHA、A7C2_COLD_FLAG 等）。',
              file=sys.stderr)
        return 2
    try:
        cold_flag = _resolve_cold_flag()
        verify_sha = _resolve_verify_sha()
        boot_profile = _resolve_boot_profile()
        prepare_only = _parse_bool_env('A7C2_PREPARE_ONLY', False)
        persistent_storage = _parse_bool_env('A7C2_USE_PERSISTENT_STORAGE', True)
        enable_usb_device = _parse_bool_env('A7C2_ENABLE_USB_DEVICE', True)
        ram_mode = _parse_bool_env('A7C2_RAM_MODE', False)
        auto_wake = _parse_bool_env('A7C2_AUTO_WAKE', True)
        virtual_lens_hud = _parse_bool_env('A7C2_VIRTUAL_LENS_HUD', True)
        bodydata = _env_path('A7C2_BODYDATA')
        cache = _env_path('A7C2_CACHE_DIR', KIT.parent / 'bodydata-cache')
        fwtool = _env_path('A7C2_FWTOOL_DIR', KIT / 'vendor/fwtool-sdk')
        runtime = _env_path('A7C2_RUNTIME_DIR', KIT.parent)
        runtime_analysis = _env_path('A7C2_RUNTIME_ANALYSIS_DIR', KIT)
        overwrite_dir = _env_path('A7C2_OVERWRITE_DIR')
        sd_image = _env_path('A7C2_SD_IMAGE')
        if 'A7C2_SINGLE_AP_SOCKETS' in os.environ or 'A7C2_SINGLE_AP_SOCKET_ROOT' in os.environ:
            from single_ap_sockets import admit
            admit()
        if not prepare_only and safe_path(runtime_analysis).parent != safe_path(runtime):
            raise ValueError('Native entry uses its adjacent runtime; A7C2_RUNTIME_ANALYSIS_DIR must be A7C2_RUNTIME_DIR/analysis')
        package = discover(bodydata)
        print(f'BODYDATA {package}', flush=True)
        entry = cache_package(package, cache, fwtool, verify_sha=verify_sha)
        prepare(entry, runtime, runtime_analysis, verify_sha=verify_sha)
        print('BODYDATA_PREPARED ILCE-7CM2 2.01 ALLLANG', flush=True)
        if not prepare_only:
            launch_env = dict(os.environ)
            launch_env['A7C2_BOOT_PROFILE'] = boot_profile
            launch_env['A7C2_COLD_FLAG'] = cold_flag
            launch_env['A7C2_VERIFY_SHA'] = '1' if verify_sha else '0'
            launch_env['A7C2_USE_PERSISTENT_STORAGE'] = '1' if (persistent_storage or boot_profile == 'original-init-cold') else '0'
            launch_env['A7C2_ENABLE_USB_DEVICE'] = '1' if enable_usb_device else '0'
            launch_env['A7C2_RAM_MODE'] = '1' if ram_mode else '0'
            launch_env['A7C2_AUTO_WAKE'] = '1' if auto_wake else '0'
            launch_env['A7C2_VIRTUAL_LENS_HUD'] = '1' if virtual_lens_hud else '0'
            launch_env.setdefault('A7C2_VIRTUAL_HCI', 'virtual-rom-v1')
            if overwrite_dir is not None:
                launch_env['A7C2_OVERWRITE_DIR'] = str(safe_path(overwrite_dir))
            else:
                launch_env.pop('A7C2_OVERWRITE_DIR', None)
            if sd_image is not None:
                launch_env['A7C2_SD_IMAGE'] = str(regular(sd_image))
            else:
                launch_env.pop('A7C2_SD_IMAGE', None)
            return subprocess.run([sys.executable, str(regular(runtime_analysis / 'camera_ui.py'))],
                                  check=False, env=launch_env).returncode
        return 0
    except Exception as exc:
        print(f'BODYDATA launch failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
