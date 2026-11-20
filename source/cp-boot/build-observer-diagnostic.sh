#!/usr/bin/env bash
# Build only the observer into a new private build directory; never modify the runtime root.
set -euo pipefail
umask 077
product="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
analysis="$product/runtime/analysis"
build_parent="$product/source/build"
[[ $# == 1 && "$1" == /* && "$(dirname -- "$1")" == "$build_parent" && ! -e "$1" && ! -L "$1" ]] || {
  echo 'Usage: build-observer-diagnostic.sh ABSOLUTE_NEW_CHILD_OF_SOURCE_BUILD' >&2; exit 2;
}
[[ "$(sha256sum "$analysis/build-observers.sh" | cut -d ' ' -f1)" == b7e7a39891345fc4d60eda0fc7fde0f4aa2ca940fd219f1f701da597403dd944 ]] || {
  echo 'Reviewed upstream observer recipe changed; inspect and update this isolated recipe' >&2; exit 1;
}
out="$1"
recipe_sha="$(sha256sum "${BASH_SOURCE[0]}" | cut -d ' ' -f1)"
private_recipe="$product/source/cp-boot/observer_private_inputs.py"
private_recipe_sha="$(sha256sum "$private_recipe" | cut -d ' ' -f1)"
mkdir -m 700 "$out"
mkdir -m 700 "$out/tmp" "$out/snapshot" "$out/objects"
mkdir -p -m 700 "$out/menu-root/simulation"
export TMPDIR="$out/tmp" PYTHONDONTWRITEBYTECODE=1
python3 -B "$analysis/snapshot-observer-sources.py" "$analysis" "$out/snapshot"
source_dir="$out/snapshot/report/2026-10-17-qemu-native-camera/runtime/analysis"
vdf_dir="$source_dir/device-models"
objects="$out/objects"
python3 -B "$private_recipe" --analysis "$analysis" --output "$out"
lib="$out/lib"
libraries=("$lib/libc-2.25.so" "$lib/libdl-2.25.so" "$lib/libpthread-2.25.so" "$lib/ld-2.25.so")
sha256sum -- "${libraries[@]}" > "$out/library-sha256sums"
for helper in pin-control-probe system-sound-owner; do
  cp -- "$analysis/menu-root/simulation/$helper" "$out/menu-root/simulation/$helper"
  cmp -- "$analysis/menu-root/simulation/$helper" "$out/menu-root/simulation/$helper"
done
for device in vdf-device touch-panel-device tcin-device imaging-device vef-path-device vef-resource-guard \
 adf-proc-device adf-set-input-device adf-set-output-device bb-set-mode-device bb-timecode-control bb-mode-config bb-mode-work-queue imaging-pin-connection imaging-control-connection imaging-adf-connection infrabb-vef-connection infrabb-vef-control-connection vef-pinmem-input-connection vef-pinmem-control-connection scalar-connection adf-connection pinmem-drawinfo-connection adf-hdmi-audio-connection infrabb-vef-format infraimaging-format adf-public-config adf-input-state adf-set-input-cold-owners adf-hdmi-monitor adf-idle-resources adf-aip-input-config adf-aip-coefficients adf-aip-gates adf-aip-disable adf-aip-commands adf-avio-output adf-source7-clock \
 hdmi-public-backup hdmi-upm-receipt hdmi-video-state pinmem-hdmi-video-connection osd-buffer-owner osd-pin-format pinmem-osd-connection \
 hdmi-device hdmi-pin-device audio-device audio-capabilities sound-table vef-device pinmem-device scalar-device adf-device pin-registry-core \
 pin-connection pin-buffer-owner pin-buffer-guest pin-buffer-wire pin-format \
 cp-sync-resources cp-cold-control cp-background-device cp302c-no-transition cp-notification-control cp-parameter-batch cp-capture-format cp-output-policy cp-startup-controls-diagnostic cp-ee-controls-diagnostic cp-movie-format-diagnostic \
 cp-state-snapshot cp-full-state-snapshot cp-start-state-data cp-start-state-provider cp-property-stage cp-property-stage-file \
 cp-parameter-state cp-parameter-import cp-parameter-view cp-lif-frame cp-lif-bitmap cp-state-publication functional-camera-control functional-still-format functional-startup-control functional-vdf-path functional-vdf-layout-stage functional-cp-zoom functional-histogram functional-background-start; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -isystem /usr/aarch64-linux-gnu/include -c "$vdf_dir/$device.c" -o "$objects/$device.o"
done
clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -DSYSTEM_SOUND_OWNER_LIBRARY -isystem /usr/aarch64-linux-gnu/include -c "$vdf_dir/system-sound-owner.c" -o "$objects/system-sound-owner.o"
for owner in infrabb-registry osdpin-registry dig-level-device cp-periodic-service dmm-unit-config rm-file-device sd-state sd-hotplug-runtime gui-model-wire gui-model-store functional-camera-bridge functional-camera-events functional-mpr-codec functional-mpr-memory functional-jpeg-codec functional-capture functional-capture-raw-blobs functional-capture-raw-writer raw-template functional-face-dmm functional-face-registry functional-face-runtime functional-face-transfer functional-face-ap-observer functional-face-native-ap functional-face-proc functional-face-sdk functional-face-source-snapshot; do
  owner_flags=()
  case "$owner" in functional-face-*) owner_flags=(-DFULL_IMAGING_GUEST);; esac
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics "${owner_flags[@]}" -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/$owner.c" -o "$objects/$owner.o"
done
for capture in capture-input capture-mapper capture-jpeg-input; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/../../report/functional-capture-input/$capture.c" -o "$objects/$capture.o"
done
for capture in capture-output-memory capture-notifications capture-delivery capture-save capture-dma; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -isystem /usr/aarch64-linux-gnu/include -I"$source_dir/../../report/functional-capture-input" -c "$source_dir/../../report/functional-capture-output/$capture.c" -o "$objects/$capture.o"
done
clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/../../report/functional-capture-queue/capture-resize-request.c" -o "$objects/capture-resize-request.o"
clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/../../report/virtual-sensor/sensor-core.c" -o "$objects/sensor-core.o"
for parser in native-video-binding/native-video native-video-paramsets/native-paramsets native-video-au-contract/native-au native-video-length-format/native-lengths; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics -fvisibility=hidden -ffunction-sections -fdata-sections -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/../../report/$parser.c" -o "$objects/${parser##*/}.o"
done
python3 -B "$private_recipe" --analysis "$analysis" --output "$out" --link \
  "$source_dir/menu-observe.c" "$source_dir/capid-service.c" "$source_dir/sa-address-service.c" \
  "$source_dir/hdmi-format-service.c" "$source_dir/dmm-service.c" "$source_dir/gpe-raster.c" "$source_dir/gpe-sprite.c" "$source_dir/sony-lz77.c" "$source_dir/headless-osd.c" \
  "$objects/"*.o
python3 -B - "$out/snapshot/source-inputs.json" <<'PY'
import hashlib, json, pathlib, sys
for path, item in json.loads(pathlib.Path(sys.argv[1]).read_text()).items():
    with open(path, 'rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != item['sha256']:
        raise SystemExit('Observer source changed during isolated build: '+path)
PY
for helper in pin-control-probe system-sound-owner; do
  cmp -- "$analysis/menu-root/simulation/$helper" "$out/menu-root/simulation/$helper"
done
sha256sum --check "$out/library-sha256sums"
[[ "$(sha256sum "$analysis/build-observers.sh" | cut -d ' ' -f1)" == b7e7a39891345fc4d60eda0fc7fde0f4aa2ca940fd219f1f701da597403dd944 ]]
python3 -B "$analysis/snapshot-observer-sources.py" "$out" "$out/snapshot" --finish
python3 -B - "$out" "$analysis" "${BASH_SOURCE[0]}" "$recipe_sha" "$private_recipe" "$private_recipe_sha" <<'PY'
import hashlib, json, os, pathlib, sys, tarfile
out, analysis, recipe = map(pathlib.Path, sys.argv[1:4])
recipe_expected, private_recipe, private_recipe_expected = sys.argv[4], pathlib.Path(sys.argv[5]), sys.argv[6]
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
receipt = json.loads((out/'observer-build-inputs.json').read_text())
with tarfile.open(out/'observer-build-sources.tar.gz', 'r:gz') as archive:
    for item in receipt['sources'].values():
        stream = archive.extractfile(item['archive_path'])
        if stream is None or hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
            raise SystemExit('Observer source archive readback differs')
if (receipt['source_archive_sha256'] != sha(out/'observer-build-sources.tar.gz') or
        receipt['observer_sha256'] != sha(out/'menu-observe.so')):
    raise SystemExit('Observer build receipt readback differs')
if sha(recipe) != recipe_expected or sha(private_recipe) != private_recipe_expected:
    raise SystemExit('Observer build recipe changed during compilation')
proof = dict(schema='a7c2-isolated-observer-build-v2', observer_only=True,
             original_runtime_untouched=True, physical_compatible=False,
             recipe_sha256=recipe_expected, private_input_recipe_sha256=private_recipe_expected,
             private_input_receipt_sha256=sha(out/'library-inputs.json'),
             source_receipt_sha256=sha(out/'observer-build-inputs.json'),
             source_archive_sha256=receipt['source_archive_sha256'], observer_sha256=receipt['observer_sha256'],
             libraries_sha256=sha(out/'library-sha256sums'), helpers_reused_from=str(analysis/'menu-root/simulation'),
             next_consumer='Isolated native AP/CP diagnostic initramfs')
raw = (json.dumps(proof, indent=2, sort_keys=True)+'\n').encode()
with (out/'diagnostic-build.json').open('xb') as stream:
    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
if (out/'diagnostic-build.json').read_bytes() != raw:
    raise SystemExit('Observer diagnostic receipt readback differs')
PY
printf 'Isolated observer: %s\n' "$out/menu-observe.so"
