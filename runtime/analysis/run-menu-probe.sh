#!/bin/bash
# Run the menu probe with the standard flag set, waiting for the probe lock instead of failing on it.
#
# By default this rebuilds menu-observe.so and the initramfs first: forgetting the rebuild silently runs
# the previous observer and makes experiments look like clean negatives. Set SKIP_REBUILD=1 to skip.
# Any MENU_* environment variables exported by the caller are forwarded to the guest as before.
set -euo pipefail
analysis_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -v A7C2_SINGLE_AP_SOCKETS || -v A7C2_SINGLE_AP_SOCKET_ROOT ]]; then
    python3 -B "$analysis_dir/single_ap_sockets.py"
fi
if [[ -n "${A7C2_FUNCTIONAL_CAMERA_MEDIA:-}" ]]; then
    echo 'Functional RAM card requires an isolated initramfs producer; current runtime is preserved' >&2
    exit 2
fi
cd "$analysis_dir"
LOCK="$analysis_dir/.menu-probe.lock"
exec 9>>"$LOCK"
flock 9
export MENU_PROBE_LOCK_FD=9
if [[ -n "${A7C2_SD_IMAGE:-}" ]]; then
    python3 - "$A7C2_SD_IMAGE" <<'PY'
import sys
from sd_transport import card_source
with card_source(sys.argv[1]):pass
PY
    export MENU_SD_IMAGE="$A7C2_SD_IMAGE"
fi

export A7C2_COLD_FLAG="${A7C2_COLD_FLAG:-force}"
export A7C2_VERIFY_SHA="${A7C2_VERIFY_SHA:-0}"

if [ -f "$analysis_dir/native-assets.json" ] && [ "${A7C2_VERIFY_SHA:-0}" = "1" ]; then
    runtime_dir="$(cd -- "$analysis_dir/.." && pwd)"
    python3 "$analysis_dir/prepare-assets.py" --runtime "$runtime_dir" --check-runtime
fi

if [[ -n "${MENU_YC_INPUT_PNG:-}" ]]; then
    [[ "${MENU_YC_INJECT:-}" == 1 ]] || { echo 'MENU_YC_INPUT_PNG requires MENU_YC_INJECT=1' >&2; exit 2; }
    yc_input_stage="$(mktemp -d)"
    trap 'rm -rf -- "$yc_input_stage"' EXIT
    export MENU_YC_INPUT_RAW="$yc_input_stage/yc-input.gray"
    python3 "$analysis_dir/yc_image_input.py" "$MENU_YC_INPUT_PNG" "$MENU_YC_INPUT_RAW"
fi

if [ "${SKIP_REBUILD:-0}" != "1" ]; then
    bash "$analysis_dir/build-observers.sh" >/dev/null || { echo "observer build failed"; exit 1; }
    if [[ "${A7C2_BOOT_PROFILE:-direct-bootin}" != original-init-cold ]]; then
        bash "$analysis_dir/prepare-menu-initramfs.sh" >/dev/null || { echo "initramfs build failed"; exit 1; }
        echo "rebuilt observer + initramfs"
    else
        echo "rebuilt observer"
    fi
fi

if [[ "${A7C2_BOOT_PROFILE:-direct-bootin}" == original-init-cold ]]; then
    [[ -z "${MENU_YC_INPUT_PNG:-}" ]] || { echo 'Image preview input requires the direct-bootin route' >&2; exit 2; }
    exec python3 "$analysis_dir/original_cold_live.py"
fi

probe=(python3 "$analysis_dir/qemu-menu-probe.py" \
    --initramfs --sony-timers --load-ipc --seed-backup --load-dmm --load-power --load-kikilog \
    --no-cp-updater --capid-service --sa-address-service --hdmi-format-service --hdmi-photo-service \
    --dmm-service --software-gpe --firmware-identity --display-info-service --seed-power-on \
    --menu-target --bootin --observe)
if [[ -n "${MENU_YC_INPUT_RAW:-}" ]]; then
    "${probe[@]}"  # preserve the EXIT trap so the temporary source is removed
else
    exec "${probe[@]}"
fi
