#!/usr/bin/env bash
# Build guest helpers against the original firmware ABI, including its loader guard.
set -euo pipefail
analysis_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$analysis_dir/menu-root/simulation"
install -m 0755 "$analysis_dir/guest-overlay/simulation/diag.sh" "$analysis_dir/menu-root/simulation/diag.sh"
install -m 0755 "$analysis_dir/guest-overlay/simulation/input-state.sh" "$analysis_dir/menu-root/simulation/input-state.sh"
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
for device in vdf-device hdmi-device hdmi-pin-device audio-device audio-capabilities sound-table vef-device pinmem-device scalar-device adf-device pin-registry-core \
              pin-connection pin-buffer-owner pin-buffer-guest pin-buffer-wire pin-format \
              cp-sync-resources cp-cold-control cp-background-device; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics \
    -isystem /usr/aarch64-linux-gnu/include -c "$vdf_dir/$device.c" \
    -o "$device_build/$device.o"
done
clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics \
  -DSYSTEM_SOUND_OWNER_LIBRARY -isystem /usr/aarch64-linux-gnu/include \
  -c "$vdf_dir/system-sound-owner.c" -o "$device_build/system-sound-owner.o"
for owner in infrabb-registry osdpin-registry dig-level-device dmm-unit-config rm-file-device gui-model-wire gui-model-store; do
  clang --target=aarch64-linux-gnu -O2 -fPIC -mno-outline-atomics \
    -isystem /usr/aarch64-linux-gnu/include -c "$source_dir/$owner.c" \
    -o "$device_build/$owner.o"
done
clang "${common[@]}" -shared -fPIC "$source_dir/mutex-trace.c" "${libraries[@]}" \
  -o "$analysis_dir/menu-root/simulation/mutex-trace.so"
if [[ "${MENU_MEDIA_SELFTEST:-0}" == 1 || "${MENU_RM_FILE:-0}" == 1 ]]; then
  clang "${common[@]}" -shared -fPIC "$source_dir/file-media-config.c" "${libraries[@]}" \
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
  "$source_dir/virtual-hci.c" "${libraries[@]}" -o "$analysis_dir/menu-root/simulation/virtual-hci"
install -m 0755 "$source_dir/start-bt-virtual.sh" "$analysis_dir/menu-root/simulation/start-bt-virtual.sh"
clang "${common[@]}" -shared -fPIC -Wl,-soname,menu-observe.so \
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
