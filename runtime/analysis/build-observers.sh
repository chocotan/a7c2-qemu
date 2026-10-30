#!/usr/bin/env bash
# Build guest helpers against the original firmware ABI, including its loader guard.
set -euo pipefail
analysis_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$analysis_dir/menu-root/simulation"
install -m 0755 "$analysis_dir/guest-overlay/simulation/diag.sh" "$analysis_dir/menu-root/simulation/diag.sh"
install -m 0755 "$analysis_dir/guest-overlay/simulation/input-state.sh" "$analysis_dir/menu-root/simulation/input-state.sh"
bash "$analysis_dir/../../report/virtual-cp/udate-distribution/build.sh"
install -m 0644 "$analysis_dir/../../report/virtual-cp/udate-distribution/sony_udate_distribution.ko" \
  "$analysis_dir/menu-root/simulation/sony_udate_distribution.ko"
lib="$analysis_dir/menu-root/lib"
common=(--target=aarch64-linux-gnu -fuse-ld=lld -nostdlib -O2 -mno-outline-atomics -Wl,--no-undefined)
# ponytail: -mno-outline-atomics keeps __aarch64_ldadd4_relax/__clear_cache libcalls out;
# the guest root only ships the firmware's own libc/libgcc, which have no outline-atomics entry points.
libraries=("$lib/libc-2.25.so" "$lib/libdl-2.25.so" "$lib/libpthread-2.25.so" "$lib/ld-2.25.so")
# Reuse public device-model source only; no full-dump assets enter this runtime.
device_build="$(mktemp -d "$analysis_dir/.device-build.XXXXXX")"
trap 'rm -rf -- "$device_build"' EXIT
python3 "$analysis_dir/snapshot-observer-sources.py" "$analysis_dir" "$device_build"
source_dir="$device_build/report/2026-10-17-qemu-native-camera/runtime/analysis"
vdf_dir="$source_dir/device-models"
common+=("-ffile-prefix-map=$device_build=.")
clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include \
  -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$vdf_dir/pin-buffer-probe.c" "$vdf_dir/pin-buffer-owner.c" "$vdf_dir/pin-buffer-guest.c" \
  "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/pin-control-probe"
clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include \
  -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$vdf_dir/system-sound-owner.c" "${libraries[@]}" \
  -o "$analysis_dir/menu-root/simulation/system-sound-owner"
for device in vdf-device touch-panel-device tcin-device vef-path-device vef-resource-guard \
              adf-proc-device adf-set-input-device adf-set-output-device bb-set-mode-device bb-mode-config bb-mode-work-queue imaging-pin-connection imaging-control-connection imaging-adf-connection infrabb-vef-connection infrabb-vef-control-connection vef-pinmem-input-connection vef-pinmem-control-connection scalar-connection adf-connection pinmem-drawinfo-connection adf-hdmi-audio-connection infrabb-vef-format infraimaging-format adf-public-config adf-input-state adf-set-input-cold-owners adf-hdmi-monitor adf-idle-resources adf-aip-input-config adf-aip-coefficients adf-aip-gates adf-aip-disable adf-aip-commands adf-avio-output adf-source7-clock \
              hdmi-public-backup hdmi-upm-receipt hdmi-video-state pinmem-hdmi-video-connection osd-buffer-owner osd-pin-format pinmem-osd-connection \
              hdmi-device hdmi-pin-device audio-device audio-capabilities sound-table vef-device pinmem-device scalar-device adf-device pin-registry-core \
              pin-connection pin-buffer-owner pin-buffer-guest pin-buffer-wire pin-format \
              cp-sync-resources cp-cold-control cp-background-device cp302c-no-transition cp-notification-control cp-parameter-batch cp-capture-format cp-output-policy cp-startup-controls-diagnostic cp-ee-controls-diagnostic cp-movie-format-diagnostic \
              cp-state-snapshot cp-full-state-snapshot cp-start-state-data cp-start-state-provider cp-property-stage cp-property-stage-file \
              cp-parameter-state cp-parameter-import cp-parameter-view cp-lif-frame cp-lif-bitmap cp-state-publication functional-camera-control functional-vdf-path functional-vdf-layout-stage functional-cp-zoom functional-histogram functional-background-start; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics \
    -isystem /usr/aarch64-linux-gnu/include -c "$vdf_dir/$device.c" \
    -o "$device_build/$device.o"
done
clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics \
  -DSYSTEM_SOUND_OWNER_LIBRARY -isystem /usr/aarch64-linux-gnu/include \
  -c "$vdf_dir/system-sound-owner.c" -o "$device_build/system-sound-owner.o"
for owner in infrabb-registry osdpin-registry dig-level-device dmm-unit-config rm-file-device sd-state sd-hotplug-runtime gui-model-wire gui-model-store functional-camera-bridge functional-camera-events functional-mpr-codec functional-mpr-memory functional-jpeg-codec functional-face-dmm functional-face-registry functional-face-runtime functional-face-transfer functional-face-ap-observer functional-face-native-ap functional-face-proc functional-face-sdk functional-face-source-snapshot; do
  owner_flags=()
  case "$owner" in functional-face-*) owner_flags=(-DFULL_IMAGING_GUEST);; esac
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics "${owner_flags[@]}" \
    -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/$owner.c" \
    -o "$device_build/$owner.o"
done
# Hidden sections keep the reused metadata parsers without host codec entry points.
for parser in native-video-binding/native-video native-video-paramsets/native-paramsets \
              native-video-au-contract/native-au native-video-length-format/native-lengths; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics \
    -fvisibility=hidden -ffunction-sections -fdata-sections \
    -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/../../report/$parser.c" \
    -o "$device_build/${parser##*/}.o"
done
clang "${common[@]}" -shared -fPIC "$source_dir/mutex-trace.c" "${libraries[@]}" \
  -o "$analysis_dir/menu-root/simulation/mutex-trace.so"
if [[ "${MENU_MEDIA_SELFTEST:-0}" == 1 || "${MENU_RM_FILE:-0}" == 1 ]]; then
  clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include -shared -fPIC \
    "$source_dir/host-block-sd.c" "${libraries[@]}" \
    -o "$analysis_dir/menu-root/simulation/host-block-sd.so"
  clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include -shared -fPIC \
    "$source_dir/file-media-config.c" "$source_dir/fsys-write-trace.c" "${libraries[@]}" \
    -o "$analysis_dir/menu-root/simulation/file-media-config.so"
  clang "${common[@]}" --sysroot=/usr/aarch64-linux-gnu -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
    "$source_dir/fsys-file-test.c" -Wl,--no-as-needed \
    "$analysis_dir/menu-root/usr/lib/libInfraFsys.so" "$analysis_dir/menu-root/usr/lib/libInfraMediaCommon.so" \
    "$analysis_dir/menu-root/usr/lib/libMWF.so" \
    "$analysis_dir/menu-root/usr/lib/libbackup.so" "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
    "$analysis_dir/menu-root/usr/lib/libosal_utm.so" -Wl,--allow-shlib-undefined "${libraries[@]}" \
    -o "$analysis_dir/menu-root/simulation/fsys-file-test"
  python3 "$analysis_dir/make-media-fixture.py"
fi
clang "${common[@]}" --sysroot=/usr/aarch64-linux-gnu -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/ramfb-viewer.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/ramfb-viewer"
clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/sd-window-export.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/sd-window-export"
clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/sd-sparse.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/sd-sparse"
clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/host-sd-probe.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/host-sd-probe"
clang "${common[@]}" -isystem /usr/aarch64-linux-gnu/include -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/virtual-hci.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/virtual-hci"
install -m 0755 "$source_dir/start-bt-virtual.sh" "$analysis_dir/menu-root/simulation/start-bt-virtual.sh"
clang "${common[@]}" -shared -fPIC -Wl,--gc-sections -Wl,-soname,menu-observe.so \
  "$source_dir/menu-observe.c" "$source_dir/capid-service.c" "$source_dir/sa-address-service.c" \
  "$source_dir/hdmi-format-service.c" "$source_dir/dmm-service.c" "$source_dir/gpe-raster.c" "$source_dir/gpe-sprite.c" "$source_dir/sony-lz77.c" "$source_dir/headless-osd.c" \
  "$device_build/"*.o "${libraries[@]}" -o "$analysis_dir/menu-observe.so"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/headless-osd-export.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/headless-osd-export"
clang "${common[@]}" -DGUI_MODEL_EXPORT -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/headless-osd-export.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/gui-model-export"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/menu-readmem.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/menu-readmem"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/menu-regs.c" "$source_dir/stillca-state.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/menu-regs"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/input-table.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/input-table"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/menu-scanmem.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/menu-scanmem"
clang "${common[@]}" -shared -fPIC -DTEST_LIBRARY \
  "$source_dir/check-menu-observe.c" "${libraries[@]}" -o "$analysis_dir/menu-root/lib/observe-constructor.so"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/check-menu-observe.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/check-menu-observe"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/seed-date-clock.c" -Wl,--no-as-needed \
  "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
  -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/seed-date-clock"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/seed-power-on.c" "$analysis_dir/menu-root/usr/lib/libbackup.so" \
  -Wl,--no-as-needed "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
  "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
  -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/seed-power-on"
clang "${common[@]}" --sysroot=/usr/aarch64-linux-gnu \
  -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/user-settings-checkpoint.c" "$analysis_dir/menu-root/usr/lib/libbackup.so" \
  -Wl,--no-as-needed "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
  "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
  -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/user-settings-checkpoint"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/seed-indicator-config.c" "$analysis_dir/menu-root/usr/lib/libbackup.so" \
  -Wl,--no-as-needed "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
  "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
  -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/seed-indicator-config"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/inject-key.c" \
  -Wl,--no-as-needed "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
  "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
  -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/inject-key"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/inject-cp-event.c" \
  -Wl,--no-as-needed "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
  "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
  -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/inject-cp-event"
clang "${common[@]}" -Wl,-e,_start -Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1 \
  "$source_dir/backup-dump.c" "$analysis_dir/menu-root/usr/lib/libbackup.so" \
  -Wl,--no-as-needed "$analysis_dir/menu-root/usr/lib/libosal_uipc.so" \
  "$analysis_dir/menu-root/usr/lib/libosal_utm.so" \
    -Wl,--allow-shlib-undefined "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/backup-dump"
python3 "$analysis_dir/snapshot-observer-sources.py" --finish "$analysis_dir" "$device_build"
