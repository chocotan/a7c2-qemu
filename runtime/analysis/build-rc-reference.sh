#!/usr/bin/env bash
# Build the explicitly experimental unity backend in the existing PCI DMA candidate.
set -euo pipefail
analysis_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ $# -gt 1 ]]; then
  echo 'Usage: build-rc-reference.sh [EXISTING_REFERENCE_BUILD_DIRECTORY]' >&2; exit 2
fi
stage="$(python3 - "$analysis_dir/../.." "${1:-}" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
if sys.argv[2]:
    stage=Path(sys.argv[2]).resolve(strict=True)
else:
    receipt=root/'source/pci-hardware-build.json'
    if not receipt.is_file():
        raise SystemExit('No installed package build receipt; pass an existing PCI DMA reference build directory explicitly')
    relative=Path(json.loads(receipt.read_text()).get('build_directory',''))
    if relative.is_absolute() or not relative.parts or '..' in relative.parts:
        raise SystemExit('Package build receipt has no valid relative build directory; rebuild or pass a reference directory')
    stage=(root/relative).resolve(strict=True)
    if not stage.is_relative_to(root/'source/build'):
        raise SystemExit('Default reference build must stay inside the package source/build directory')
required=('build/build.ninja','qemu-11.1.2/hw/arm/virt.c','qemu-11.1.2/hw/misc/meson.build',
          'qemu-11.1.2/hw/intc/arm_gic_common.c','qemu-11.1.2/include/hw/intc/arm_gic_common.h',
          'qemu-11.1.2/hw/misc/sony-pcidma/sony_regfile.c')
for name in required:
    path=stage/name
    if path.is_symlink() or not path.is_file():
        raise SystemExit('PCI DMA reference source/build prerequisite missing: '+name+'; pass a prepared reference build directory')
print(stage)
PY
)"
src="$stage/qemu-11.1.2"
exec 9>>"$analysis_dir/.menu-probe.lock"
flock 9
for name in rc-board rc-data gic-readback gic-loader-handoff cp-config-page sa-trace regfile-trace-only sa-data-only sa-reference-complete; do
  patch_file="$analysis_dir/device-models/$name.patch"
  if ! patch --batch --force --dry-run --reverse --fuzz=0 -p1 -d "$src" < "$patch_file" >/dev/null 2>&1; then
    patch --batch --dry-run --forward --fuzz=0 -p1 -d "$src" < "$patch_file"
    patch --batch --forward --fuzz=0 -p1 -d "$src" < "$patch_file"
  fi
done
install -m 0644 "$analysis_dir/device-models/sony-gic-readback.inc" "$src/hw/intc/sony-gic-readback.inc"
for file in sony_rc.c rc-reference.c rc-reference.h rc-identity.c rc-identity.h \
  sony_sa_data.c sa-nv12-job.c sa-nv12-job.h nv12-reference.c nv12-reference.h; do
  install -m 0644 "$analysis_dir/device-models/$file" "$src/hw/misc/sony-pcidma/$file"
done
mkdir -p "$stage/tmp" "$stage/cache"
bwrap --unshare-net --die-with-parent --clearenv --ro-bind / / --bind "$stage" "$stage" \
  --dev /dev --proc /proc --chdir "$stage/build" --setenv PATH /usr/bin:/bin \
  --setenv LC_ALL C --setenv TMPDIR "$stage/tmp" --setenv XDG_CACHE_HOME "$stage/cache" \
  --setenv PYTHONDONTWRITEBYTECODE 1 --setenv PIP_NO_INDEX 1 --setenv PIP_NO_CACHE_DIR 1 \
  /usr/bin/ninja -j8 qemu-system-aarch64
python3 - "$analysis_dir" "$stage" <<'PY'
from pathlib import Path
import hashlib,json,runpy,sys
analysis,stage=map(Path,sys.argv[1:])
binary=stage/'build/qemu-system-aarch64'
runpy.run_path(str(analysis/'native_rc_board.py'))['require_binary'](binary,reference=True)
def sha(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()
names=('sony_rc.c','rc-reference.c','rc-reference.h','rc-identity.c','rc-identity.h','rc-board.patch','rc-data.patch',
       'sony-gic-readback.inc','gic-readback.patch','gic-loader-handoff.patch','cp-config-page.patch','sa-trace.patch',
       'regfile-trace-only.patch','sony_sa_data.c','sa-nv12-job.c','sa-nv12-job.h',
       'nv12-reference.c','nv12-reference.h','sa-data-only.patch','sa-reference-complete.patch')
for name in (name for name in names if name.endswith(('.c','.h'))):
    if sha(analysis/'device-models'/name)!=sha(stage/'qemu-11.1.2/hw/misc/sony-pcidma'/name):
        raise SystemExit('Source changed during RC build; candidate rejected: '+name)
if sha(analysis/'device-models/sony-gic-readback.inc')!=sha(stage/'qemu-11.1.2/hw/intc/sony-gic-readback.inc'):
    raise SystemExit('GIC readback source changed during build')
proof=dict(model='lane-preserving-unity-v1',silicon_packing_verified=False,
    optional_sa_backend='YUYV-vmean-half-up; data-only or explicit virtual group0-bit0 completion; silicon unverified',
    binary_sha256=sha(binary),sources={name:sha(analysis/'device-models'/name) for name in names})
(stage/'rc-reference-build.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
PY
