#!/usr/bin/env bash
# Dependency inspection only: does not build, install, unpack firmware or start QEMU.
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
missing=0
for tool in python3 bwrap patch ninja meson cc c++ pkg-config flock make flex bison clang ld.lld \
  cpio debugfs fsck.fat sha256sum timeout; do
  if ! command -v "$tool" >/dev/null; then
    echo "MISSING command: $tool" >&2
    missing=1
  fi
done
if ! pkg-config --exists gtk+-3.0 sdl2 pixman-1 glib-2.0 libseccomp; then
  echo 'MISSING development packages: GTK3/SDL2/pixman/glib2/libseccomp' >&2
  missing=1
fi
[[ -d /usr/aarch64-linux-gnu/include ]] || {
  echo 'MISSING AArch64 glibc headers: /usr/aarch64-linux-gnu/include' >&2; missing=1;
}
if ! python3 -B - "$here" <<'PY'
from pathlib import Path
import importlib, sys
root=Path(sys.argv[1]); analysis=root/'runtime/analysis'
sys.path.insert(0,str(analysis))
local=analysis/'vendor/host-python'
if local.is_dir():
    sys.path.insert(0,str(local))
    print('LOCAL_CRYPTO_PREREQUISITE',local,'(ignored, not public source)')
assert sys.version_info >= (3,12), 'Python 3.12+ required for the offline build'
import PIL.Image
import gi
gi.require_version('Gtk','3.0')
gi.require_foreign('cairo')
from gi.repository import Gtk
try:
    import Cryptodome.Cipher.AES
except ImportError:
    import Crypto.Cipher.AES
for name in ('bodydata-launch','prepare-assets','menu_control','camera_ui','usb_network','sd_transport'):
    importlib.import_module(name)
print('HOST_IMPORTS_PASS')
PY
then missing=1; fi
if [[ "$missing" != 0 ]]; then exit 1; fi
echo 'HOST_DEPENDENCIES_FOUND (namespace permissions and desktop still require runtime validation)'
