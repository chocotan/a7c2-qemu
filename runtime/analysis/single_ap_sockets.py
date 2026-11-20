"""Single AP F/S routing contract; the runtime gate is fixed closed."""
import json
import os
from pathlib import Path
import stat

from diagnostic_fs_socket_roots import DIAGNOSTIC_FS_PROFILE, DiagnosticRoots, require_runtime_ready

PROFILE = DIAGNOSTIC_FS_PROFILE
PROFILE_ENV = 'A7C2_SINGLE_AP_SOCKETS'
ROOT_ENV = 'A7C2_SINGLE_AP_SOCKET_ROOT'
BINDING_NAME = 'single-ap-socket-binding.json'

# Both frontend selections and the backend settings they derive must be rejected.
EXCLUDED_ROUTES = (
    'A7C2_USB_NET', 'MENU_USB_NET', 'QEMU_SONY_USB_NET', 'A7C2_USB_NET_SELFTEST',
    'A7C2_FUNCTIONAL_CAMERA', 'MENU_FUNCTIONAL_CAMERA',
    'QEMU_NATIVE_AP_CP_LINK', 'QEMU_NATIVE_LINK_DIR',
    'QEMU_AP_CP_GPIO_LINES', 'QEMU_AP_CP_GPIO_SIDE', 'QEMU_NATIVE_P1_SPI_COMPONENT',
    'A7C2_QUEUE_WATCH', 'A7C2_MEDIA_PREDICATE_WATCH',
    'A7C2_MEDIA_INIT_WATCH', 'A7C2_RESIZE_WATCH', 'QEMU_REQUEST_QUEUE_GDB',
    'A7C2_PINMEM_HDMI_VIDEO_CONNECT', 'MENU_PINMEM_HDMI_VIDEO_CONNECT',
    'A7C2_ADF_HDMI_AUDIO_CONNECT', 'MENU_ADF_HDMI_AUDIO_CONNECT',
    'QEMU_HDMI_UPM_GDB',
    'A7C2_RAM_WINDOW', 'A7C2_RAM_RESTORE_STREAM', 'A7C2_RAM_QEMU',
    'QEMU_RAM_SESSION', 'QEMU_RAM_INCOMING',
)


def admit(environment=None):
    environment = os.environ if environment is None else environment
    if PROFILE_ENV not in environment and ROOT_ENV not in environment:
        return False
    if environment.get(PROFILE_ENV) != PROFILE or not environment.get(ROOT_ENV):
        raise ValueError('single AP sockets require exact profile and explicit S root')
    excluded = [name for name in EXCLUDED_ROUTES
                if environment.get(name, '') not in ('', '0')]
    if excluded:
        raise ValueError('single AP profile excludes unmigrated routes: ' + ', '.join(excluded))
    require_runtime_ready()
    return True


def prepare(environment, run):
    if not admit(environment):
        return {}
    roots = DiagnosticRoots(run, environment[ROOT_ENV], PROFILE)
    binding = roots.binding()
    # The future owner supplies a fresh private S; this helper never creates one.
    with (Path(run) / BINDING_NAME).open('x', encoding='utf-8') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(binding, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    if read_binding(run) != binding:
        raise ValueError('single AP binding readback differs')
    return {PROFILE_ENV: PROFILE, ROOT_ENV: str(roots.sockets)}


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate single AP binding key')
        value[key] = item
    return value


def read_binding(run):
    path = Path(run) / BINDING_NAME
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or
                not 0 < info.st_size <= 16384):
            raise ValueError('unsafe single AP binding receipt')
        raw = os.read(fd, 16385)
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('single AP binding changed while reading')
        if len(raw) != info.st_size or path.lstat() != after:
            raise ValueError('single AP binding path or size changed while reading')
    finally:
        os.close(fd)
    value = json.loads(raw, object_pairs_hook=_object)
    if (not isinstance(value, dict) or
            set(value) != {'profile', 'files', 'sockets', 'directories'} or
            value['profile'] != PROFILE or value['files'] != str(Path(run)) or
            not isinstance(value['sockets'], str) or not value['sockets'] or
            not isinstance(value['directories'], dict)):
        raise ValueError('single AP binding does not name this run')
    return value


def roots_for_run(run, environment=None):
    environment = os.environ if environment is None else environment
    selected = admit(environment)
    try:
        binding = read_binding(run)
    except FileNotFoundError:
        if not selected:
            return None
        return DiagnosticRoots(run, environment[ROOT_ENV], PROFILE)
    require_runtime_ready()
    if selected and binding['sockets'] != environment[ROOT_ENV]:
        raise ValueError('single AP binding S differs from explicit environment')
    roots = DiagnosticRoots(run, binding['sockets'], PROFILE)
    if roots.binding() != binding:
        raise ValueError('single AP F/S binding identity changed')
    return roots


if __name__ == '__main__':
    admit()
