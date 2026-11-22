#!/usr/bin/env bash
# Bounded attempt to boot the unmodified camera kernel on QEMU's generic virt board.
# No writable firmware, block disks, networking or physical devices are supplied.
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
analysis_dir="$project_dir/analysis"
socket_dir=/out
socket_bind=()
qemu_prefix=()
if [[ -v A7C2_SINGLE_AP_SOCKETS || -v A7C2_SINGLE_AP_SOCKET_ROOT ]]; then
  python3 -B "$analysis_dir/single_ap_sockets.py"
  socket_dir=/sockets
  socket_bind=(--bind "$A7C2_SINGLE_AP_SOCKET_ROOT" /sockets)
  qemu_prefix=(/usr/bin/sh -c 'umask 0177; exec "$@"' sh)
fi
if [[ -n "${A7C2_STORAGE_PROFILE:-}" ]]; then
  python3 -B - "$analysis_dir" <<'PERSISTENT_PREFLIGHT'
import os,sys
sys.path.insert(0,sys.argv[1])
from persistent_storage import inherited_fd
inherited_fd(os.environ)
PERSISTENT_PREFLIGHT
fi
# Default off: the RAM capture card and the internal settings disk are combined only
# under this one reviewed profile, and never through a relaxed storage guard.
settings_restart="${A7C2_SETTINGS_RESTART_PROFILE:-}"
if [[ -n "$settings_restart" ]]; then
  [[ "$settings_restart" == functional-ram-card-independent-internal-v1 &&
     "${A7C2_STORAGE_PROFILE:-}" == product-single-disk-v1 &&
     "${A7C2_FUNCTIONAL_RAM_CONSUMER:-}" == inherited-ram-card-fds-v1 ]] || {
    echo 'Settings-restart profile requires its exact persistent/RAM storage combination' >&2; exit 2; }
fi
if [[ -v A7C2_CAPTURE_SOCKET_PROFILE || -v A7C2_CAPTURE_SOCKET_ROOT || -v A7C2_CAPTURE_SOCKET_FD ]]; then
  [[ ! -v A7C2_SINGLE_AP_SOCKETS && ! -v A7C2_SINGLE_AP_SOCKET_ROOT &&
     "$settings_restart" == functional-ram-card-independent-internal-v1 &&
     "${A7C2_RAM_CARD_LAUNCH_PROFILE:-}" == inherited-ram-card-fds-v1 &&
     "${QEMU_HDMI_UPM_GDB:-0}" == 1 && "${QEMU_NATIVE_DISPLAY:-none}" == none &&
     "${QEMU_REQUEST_QUEUE_GDB:-0}" == 0 && "${QEMU_NATIVE_INPUT:-0}" == 0 &&
     "${QEMU_SONY_USB_DEVICE:-0}" == 0 && ! -v QEMU_NATIVE_AP_CP_LINK &&
     "${QEMU_RAM_SESSION:-0}" == 0 && "${QEMU_RAM_INCOMING:-0}" == 0 &&
     -z "${QEMU_ICOUNT_ARGS:-}" ]] || {
    echo 'Capture short sockets require the held-disk headless capture route only' >&2; exit 2; }
  python3 -B "$analysis_dir/capture_socket_roots.py"
  [[ "$(bwrap --help)" == *"--bind-fd"* ]] || {
    echo 'Capture short sockets require writable directory FD binding' >&2; exit 2; }
  socket_dir=/sockets
  socket_bind=(--bind-fd "$A7C2_CAPTURE_SOCKET_FD" /sockets)
  qemu_prefix=(/usr/bin/sh -c 'umask 0177; exec "$@"' sh)
fi
tool_root="${QEMU_SYSTEM_DIR:-$project_dir/sources/qemu-11.1.2/build-sony-ui}"
binary_relative="${QEMU_SYSTEM_BINARY:-qemu-system-aarch64}"
sandbox_library_path=/tools/usr/lib
sony_timers="${SONY_TIMER_MODEL:-0}"
native_window="${MENU_NATIVE_WINDOW:-0}"
native_display="${QEMU_NATIVE_DISPLAY:-none}"
observation_seconds="${QEMU_TIMEOUT_SECONDS:-0}"
[[ "$observation_seconds" == 0 ]] || { echo 'QEMU timeout signaling is disabled; use an owned QMP supervisor' >&2; exit 2; }
ram_session="${QEMU_RAM_SESSION:-0}"
case "$ram_session" in 0|1) ;; *) echo 'QEMU_RAM_SESSION must be 0 or 1' >&2; exit 2 ;; esac
cpu_count="${QEMU_CPU_COUNT:-1}"
case "$cpu_count" in 1|2) ;; *) echo 'QEMU_CPU_COUNT must be 1 or 2' >&2; exit 2 ;; esac
gic_handoff="${QEMU_SONY_GIC_HANDOFF:-0}"
case "$gic_handoff" in 0|1) ;; *) echo 'QEMU_SONY_GIC_HANDOFF must be 0 or 1' >&2; exit 2 ;; esac
if [[ "$gic_handoff" == 1 && ( "$cpu_count" != 2 || "${QEMU_SONY_PCIDMA:-0}" != 1 ) ]]; then
  echo 'GIC handoff requires the matched native SMP2 PCI DMA board' >&2; exit 2
fi
rc_profile="${QEMU_SONY_RC:-0}"
case "$rc_profile" in 0|1) ;; *) echo 'QEMU_SONY_RC must be 0 or 1' >&2; exit 2 ;; esac
if [[ "$rc_profile" == 1 && ( "$cpu_count" != 2 || "${QEMU_SONY_PCIDMA:-0}" != 1 ) ]]; then
  echo 'RC profile requires matched SMP2 and isolated PCI DMA board' >&2; exit 2
fi
sa_data_only="${QEMU_SONY_SA_DATA_ONLY:-0}"
case "$sa_data_only" in 0|1) ;; *) echo 'QEMU_SONY_SA_DATA_ONLY must be 0 or 1' >&2; exit 2 ;; esac
sa_reference_complete="${QEMU_SONY_SA_REFERENCE_COMPLETE:-0}"
case "$sa_reference_complete" in 0|1) ;; *) echo 'QEMU_SONY_SA_REFERENCE_COMPLETE must be 0 or 1' >&2; exit 2 ;; esac
if [[ "$sa_reference_complete" == 1 && ( "$rc_profile" != 1 || "$sa_data_only" == 1 ) ]]; then
  echo 'SA reference completion requires RC and excludes data-only mode' >&2; exit 2
fi
if [[ "$sa_data_only" == 1 && "$rc_profile" != 1 ]]; then
  echo 'SA data-only reference requires the explicit RC profile' >&2; exit 2
fi
case "$native_window" in 0|1) ;; *) echo 'MENU_NATIVE_WINDOW must be 0 or 1' >&2; exit 2 ;; esac
case "$native_display" in none|gtk|sdl) ;; *) echo 'QEMU_NATIVE_DISPLAY must be none, gtk or sdl' >&2; exit 2 ;; esac
display_args=(-display none)
display_environment=()
queue_debug="${QEMU_REQUEST_QUEUE_GDB:-0}"
case "$queue_debug" in 0|1) ;; *) echo 'Invalid queue debug flag' >&2; exit 2 ;; esac
debug_args=()
if [[ "$queue_debug" == 1 ]]; then
  if [[ "${QEMU_RESIZE_OBSERVE:-0}" == 1 ]]; then
    [[ "${QEMU_SONY_PCIDMA:-0}" == 1 ]] || { echo 'Resize observation requires the isolated PCI DMA model' >&2; exit 2; }
  else
    [[ "$native_window" == 1 && "${QEMU_UI_LIVE:-0}" == 1 ]] || { echo 'Queue debug requires an owned live native VM' >&2; exit 2; }
  fi
  # Private per-run filesystem socket only; no TCP listener or physical device.
  debug_args=(-gdb unix:/out/request-queue-gdb.sock,server=on,wait=off
              -qmp unix:/out/request-queue-control.sock,server=on,wait=off)
fi
hdmi_debug="${QEMU_HDMI_UPM_GDB:-0}"
case "$hdmi_debug" in 0|1) ;; *) echo 'Invalid HDMI debug flag' >&2; exit 2 ;; esac
if [[ "$hdmi_debug" == 1 ]]; then
  [[ "$queue_debug" == 0 && "$native_window" == 1 && "${QEMU_UI_LIVE:-0}" == 1 &&
     "${MENU_PINMEM_HDMI_VIDEO_CONNECT:-}" == virtual-pinmem-video0-hdmi-video0-initializing-v1 ]] || {
    echo 'HDMI consumer debug requires the isolated owned video profile' >&2; exit 2;
  }
  debug_args=(-gdb unix:$socket_dir/hdmi-upm-gdb.sock,server=on,wait=off
              -qmp unix:$socket_dir/hdmi-upm-control.sock,server=on,wait=off)
fi
if [[ "$native_window" == 1 ]]; then
  display_args=(-display "$native_display" -device ramfb,id=a7c2-screen)
  if [[ "$native_display" != none ]]; then
    # Only the local X11 socket and its cookie file enter the VM sandbox.
    [[ "${DISPLAY:-}" =~ ^:([0-9]+)(\.[0-9]+)?$ ]] || { echo 'Native window requires a local X11/Xwayland DISPLAY (for example :0)' >&2; exit 2; }
    x_socket="/tmp/.X11-unix/X${BASH_REMATCH[1]}"
    x_auth="${XAUTHORITY:-$HOME/.Xauthority}"
    [[ -S "$x_socket" && -r "$x_auth" ]] || { echo 'Local X11 socket or XAUTHORITY is unavailable' >&2; exit 2; }
    display_environment=(--dir /tmp/.X11-unix --ro-bind "$x_socket" "$x_socket"
      --dir /run --ro-bind "$x_auth" /run/a7c2-xauth --ro-bind /etc/fonts /etc/fonts
      --setenv DISPLAY "$DISPLAY" --setenv XAUTHORITY /run/a7c2-xauth
      --setenv GDK_BACKEND x11 --setenv SDL_VIDEODRIVER x11 --setenv NO_AT_BRIDGE 1
      --setenv XDG_CACHE_HOME /tmp/cache --setenv XDG_CONFIG_HOME /tmp/config)
    display_args=(-display "$native_display,gl=off" -device ramfb,id=a7c2-screen
      -name 'Sony A7C II - experimental menu')
  fi
  if [[ "${QEMU_NATIVE_INPUT:-0}" == 1 ]]; then
    display_args+=(-chardev socket,id=sonykeys,path=$socket_dir/native-input.sock,server=on,wait=off
      -device sony-ui-input,chardev=sonykeys,display=a7c2-screen)
  fi
elif [[ "$native_display" != none ]]; then
  echo 'Native display requires MENU_NATIVE_WINDOW=1' >&2; exit 2
fi
timer_environment=()
if [[ "$sony_timers" == 1 ]]; then
  timer_environment=(--setenv QEMU_SONY_TIMERS 1)
fi
sony_usb_device="${QEMU_SONY_USB_DEVICE:-0}"
usb_device_qmp=()
if [[ "$sony_usb_device" != 0 ]]; then
  [[ "$sony_usb_device" == 1 && "${A7C2_ORIGINAL_COLD:-}" == original-init-v1 ]] || { echo 'Sony USB device requires its explicit original cold profile' >&2; exit 2; }
  for name in QEMU_SONY_USB_DEVICE QEMU_SONY_USB_RUN_ID QEMU_SONY_USB_LEASE QEMU_SONY_USB_QMP_HOST_PATH QEMU_SONY_USB_BACKEND_SOCKET; do
    [[ -n "${!name:-}" ]] || { echo "Missing USB binding $name" >&2; exit 2; }
    timer_environment+=(--setenv "$name" "${!name}")
  done
  usb_device_qmp=(-qmp unix:$socket_dir/usb-qmp.sock,server=on,wait=off)
fi
usb_generation_args=()
if [[ "${A7C2_USB_GENERATION_OBSERVE+x}" == x ]]; then
  [[ "$A7C2_USB_GENERATION_OBSERVE" == virtual-usb-generation-observe-v1 ]] || {
    echo 'Unknown explicit USB generation observer profile' >&2; exit 2;
  }
  [[ "$sony_usb_device" == 1 && "${A7C2_ORIGINAL_COLD:-}" == original-init-v1 ]] || {
    echo 'USB generation observer requires the enabled original cold USB device' >&2; exit 2;
  }
  case ",${QEMU_TRACE_FLAGS:-in_asm,cpu_reset,guest_errors,unimp}," in
    *,guest_errors,*) ;;
    *) echo 'USB generation observer requires guest_errors trace logging' >&2; exit 2 ;;
  esac
  usb_generation_args=(-global sony-dwc3-gadget.generation-observe=on)
fi

# A7C2_BOOT_QUIET=1 (iteration runs): skip per-MMIO/-d trace logging entirely.
# The original cold product route is latency-sensitive: no -d tracing unless A7C2_COLD_TRACE=1.
if [[ "${A7C2_BOOT_QUIET:-}" == 1 || ( -n "${A7C2_ORIGINAL_COLD:-}" && "${A7C2_COLD_TRACE:-}" != 1 ) ]]; then
  trace_args=()
else
  trace_args=(-d "${QEMU_TRACE_FLAGS:-in_asm,cpu_reset,guest_errors,unimp}" -D /out/boot-trace.log)
fi
bootfs="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"
test_initrd="${5:-$bootfs/initrd.img}"
original_cold="${A7C2_ORIGINAL_COLD:-}"
if [[ -n "$original_cold" ]]; then
  [[ "$original_cold" == original-init-v1 && "${A7C2_STORAGE_PROFILE:-}" == product-single-disk-v1 && "$test_initrd" == *.ext2 ]] || { echo 'Original cold boot requires its exact profile, persistent disk and raw ext2 RAM0' >&2; exit 2; }
fi
ram_mb="${1:-1024}"
case "$ram_mb" in 1024|4096) ;; *) echo 'Use 1024 or 4096 MiB' >&2; exit 2 ;; esac
board_dtb="${2:-}"
loader_args=()
output_dir="$analysis_dir/qemu-kernel-output-$ram_mb"
if [[ -n "${QEMU_NATIVE_AP_CP_LINK:-}" ]]; then
  python3 -B - "$analysis_dir" "$tool_root/$binary_relative" <<'PY'
from pathlib import Path
import os,runpy,sys
api=runpy.run_path(str(Path(sys.argv[1]).parents[1]/'source/cp-boot/native-link.py'))
if os.environ['QEMU_NATIVE_AP_CP_LINK']!=api['PROFILE']:
    raise ValueError('Unknown native AP/CP link profile')
api['admit'](Path(os.environ['QEMU_NATIVE_LINK_DIR']),Path(sys.argv[2]))
PY
  output_dir="$QEMU_NATIVE_LINK_DIR/ap-board-$ram_mb"
fi
if [[ -n "$board_dtb" ]]; then
  output_dir="${output_dir}-dtb"
  install -D -m 0644 "$board_dtb" "$output_dir/virt.dtb"
  loader_args=(-device loader,file=/out/virt.dtb,addr=0x40002000)
fi
boot_memory="${3:-0}"
case "$boot_memory" in 0|1) ;; *) echo 'Boot memory flag must be 0 or 1' >&2; exit 2 ;; esac
memory_config="$ram_mb"
if [[ "$boot_memory" == 1 ]]; then
  if [[ "$ram_mb" != 4096 || -z "$board_dtb" ]]; then
    echo 'Boot memory experiment requires 4096 MiB and a DTB' >&2; exit 2
  fi
  original_output="$output_dir"
  output_dir="${output_dir}-bootmem"
  install -D -m 0644 "$original_output/virt.dtb" "$output_dir/virt.dtb"
  # Sparse host allocation covers the fixed boot-parameter address.
  # The supplied DTB still describes only 4 GiB to the guest kernel.
  memory_config=16384
fi
skip_hwtimer="${4:-0}"
case "$skip_hwtimer" in 0|1) ;; *) echo 'Timer flag must be 0 or 1' >&2; exit 2 ;; esac
if [[ "$native_window" == 1 ]] && { [[ "$skip_hwtimer" != 1 || "$boot_memory" != 1 ]] || [[ "$test_initrd" != *.cpio && "$test_initrd" != *.cpio.gz && -z "$original_cold" ]]; }; then
  echo 'Native ramfb requires high-DDR boot memory and a declared boot image' >&2; exit 2
fi
cmdline='console=ttyAMA0 earlycon=pl011,0x09000000 loglevel=8 root=/dev/ram0 init=/bin/sh'
if [[ -n "$original_cold" ]]; then
  cmdline='console=ttyAMA0 earlycon=pl011,0x09000000 loglevel=${A7C2_BOOT_QUIET_LOGLEVEL:-8} root=/dev/ram0 rootfstype=ext2 rw noatime init=/sbin/product-cold-bootstrap product.cold=original-init-v1'
fi
high_ddr=0
if [[ "$test_initrd" != "$bootfs/initrd.img" ]]; then
  high_ddr=1
fi
if [[ "$cpu_count" == 2 && ( "$high_ddr" != 1 || "$skip_hwtimer" != 1 || -z "$board_dtb" ) ]]; then
  echo 'SMP2 requires the native high-DDR fixed-address DTB preparation' >&2; exit 2
fi
pin_control_memory="${QEMU_PIN_CONTROL_MEMORY:-0}"
sound_owner="${QEMU_SYSTEM_SOUND_OWNER:-0}"
pcidma_enabled="${QEMU_SONY_PCIDMA:-0}"
# QEMU runs under bwrap --clearenv: the model gate must be passed as --setenv or the
# integrated devices are never created (the driver would read the bus-stub instead).
pcidma_environment=()
if [[ "$pcidma_enabled" == 1 ]]; then
  pcidma_environment=(--setenv QEMU_SONY_PCIDMA 1)
fi
if [[ "$rc_profile" == 1 ]]; then
  pcidma_environment+=(--setenv QEMU_SONY_RC 1)
fi
if [[ "$gic_handoff" == 1 ]]; then
  pcidma_environment+=(--setenv QEMU_SONY_GIC_HANDOFF 1)
fi
if [[ "$sa_data_only" == 1 ]]; then
  pcidma_environment+=(--setenv QEMU_SONY_SA_DATA_ONLY 1)
fi
if [[ "$sa_reference_complete" == 1 ]]; then
  pcidma_environment+=(--setenv QEMU_SONY_SA_REFERENCE_COMPLETE 1)
fi
case "$sound_owner" in 0|1) ;; *) echo 'Invalid sound owner flag' >&2; exit 2;; esac
if [[ "$sound_owner" == 1 ]] && { [[ "$high_ddr" != 1 || "$skip_hwtimer" != 1 ]] || [[ "$test_initrd" != *.cpio && -z "$original_cold" ]]; }; then
  echo 'Sound owner requires high-DDR raw cpio initramfs' >&2; exit 2
fi
case "$pin_control_memory" in 0|1) ;; *) echo 'Invalid pin-control memory flag' >&2; exit 2;; esac
if [[ "$pin_control_memory" == 1 ]] && { [[ "$high_ddr" != 1 || "$skip_hwtimer" != 1 ]] || [[ "$test_initrd" != *.cpio && "$test_initrd" != *.cpio.gz && -z "$original_cold" ]]; }; then
  echo 'Pin-control RAM requires high-DDR cpio initramfs' >&2; exit 2
fi
if [[ "$skip_hwtimer" == 1 ]]; then
  if [[ "$boot_memory" != 1 ]]; then
    echo 'Timer experiment requires the boot memory setup' >&2; exit 2
  fi
  original_output="$output_dir"
  output_dir="${output_dir}-skip-hwtimer"
  install -D -m 0644 "$original_output/virt.dtb" "$output_dir/virt.dtb"
  # ponytail: skip seven absent Sony devices; add CXD90057 device models for full boot.
  if [[ "$test_initrd" != "$bootfs/initrd.img" ]]; then
    original_output="$output_dir"
    output_dir="${output_dir}-menu"
    install -D -m 0644 "$original_output/virt.dtb" "$output_dir/virt.dtb"
    image_kib=$(( ($(stat -c %s "$test_initrd") + 1023) / 1024 ))
    cmdline+=" ramdisk_size=$image_kib"
    if [[ "$test_initrd" == *.cpio || "$test_initrd" == *.cpio.gz || -n "$original_cold" ]]; then
      if [[ -z "$original_cold" ]]; then cmdline+=' rdinit=/init'; fi
      workspace_parameters="$(python3 - "$analysis_dir/unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt" <<'PY'
from pathlib import Path
import sys
print(' '.join(line for line in Path(sys.argv[1]).read_text().splitlines()
               if line.startswith('memrsv=') and 'tmonitor.' not in line))
PY
)"
      cmdline+=" $workspace_parameters"
      if [[ "${SONY_DMM_SERVICE:-0}" == 1 ]]; then
        # Separate virtual CP buffers from both Linux pages and camera DMM pools.
        cmdline+=' memrsv=0x00100000@0x41e000000:uc'
        if [[ "$sound_owner" != 1 ]]; then
          cmdline+=' memrsv=0x00010000@0x41d020000:uc'
        fi
      fi
      if [[ "$native_window" == 1 ]]; then
        # Independent scanout: two 2 MiB slots, DMA/config in last page.
        if [[ "${MENU_RM_FILE:-0}" == 1 ]]; then
          # Coalesce adjacent scanout and export owners to keep Sony's 16-entry table limit.
          cmdline+=' memrsv=0x00900000@0x41e100000:uc'
        else
          cmdline+=' memrsv=0x00500000@0x41e100000:uc'
        fi
      fi
      if [[ "${MENU_MEDIA_SELFTEST:-0}" == 1 || "${MENU_RM_FILE:-0}" == 1 ]]; then
        if [[ "$native_window" != 1 || "${MENU_RM_FILE:-0}" != 1 ]]; then
          cmdline+=' memrsv=0x00400000@0x41e600000:uc'
        fi
      fi
    fi
  fi
  # The camera's own cmdline carries driver parameters (pcie.*, wdt.*, adrs_conv.*, ...) that we
  # normally drop. MENU_EXTRA_CMDLINE lets a run pass them through verbatim.
  if [[ -n "${QEMU_EXTRA_CMDLINE:-}" ]]; then
    cmdline+=" $QEMU_EXTRA_CMDLINE"
  fi
  if [[ "$pin_control_memory" == 1 ]]; then
    cmdline+=' fullsystem.pin-control-memory=1 memrsv=0x00002000@0x500000000:uc'
  fi
  if [[ "$sound_owner" == 1 ]]; then
    if [[ "${SONY_DMM_SERVICE:-0}" == 1 ]]; then
      # Adjacent owners share a reservation, keeping the original 16-entry budget.
      cmdline+=' fullsystem.sound-owner=1 memrsv=0x00030000@0x41d000000:uc'
    else
      cmdline+=' fullsystem.sound-owner=1 memrsv=0x00020000@0x41d000000:uc'
    fi
  fi
  [[ "${A7C2_BOOT_QUIET:-}" != 1 ]] && cmdline+=' initcall_debug'
cmdline+=' initcall_blacklist=__boottime___udif_init_udif_hwtimer,__boottime___udif_init_udif_wdt,__boottime___udif_init_udif_fusb_otg,__boottime___udif_init_udif_pcie,__boottime___udif_init_udif_ddrc,__boottime___udif_init_pcidma,__boottime_sony_usb_init'
  if [[ "$high_ddr" == 1 ]]; then
    # GPIO now has register backing; let the original OTG notification state initialize.
    cmdline="${cmdline/,__boottime___udif_init_udif_fusb_otg/}"
  fi
  if [[ "$sony_timers" == 1 ]]; then
    cmdline="${cmdline/__boottime___udif_init_udif_hwtimer,/}"
  fi
  if [[ "$sony_usb_device" == 1 ]]; then
    cmdline="${cmdline/,__boottime_sony_usb_init/}"
  fi
  # With the PCI DMA engine modeled (QEMU_SONY_PCIDMA=1), let the original pcidma
  # UDIF driver initialize so pcidma_transfer_async can drive the engine. Also
  # un-blacklist the UDIF pcie layer so the DW host link can come up and enable it.
  if [[ "$pcidma_enabled" == 1 ]]; then
    cmdline="${cmdline/,__boottime___udif_init_pcidma/}"
    cmdline="${cmdline/,__boottime___udif_init_udif_pcie/}"
  fi
  # This kernel uses the fixed-address DTB, so update that DTB's bootargs too.
  python3 - "$output_dir/virt.dtb" "$project_dir/sources/qemu-tools/usr/lib/libfdt.so.1" "$cmdline" "$test_initrd" "$high_ddr" "$analysis_dir" <<'PY'
from pathlib import Path
import ctypes, os, re, runpy, struct, sys
native = 'memrsv=0x00500000@0x41e100000:uc'
native_bytes=0x500000
if 'memrsv=0x00900000@0x41e100000:uc' in sys.argv[3].split():
    native='memrsv=0x00900000@0x41e100000:uc'
    native_bytes=0x900000
media = 'memrsv=0x00400000@0x41e600000:uc'
if media in sys.argv[3].split():
    reservations = re.findall(r'(?:^|\s)memrsv=(0x[0-9a-fA-F]+)@(0x[0-9a-fA-F]+)(?=[:\s]|$)', sys.argv[3])
    assert sys.argv[3].split().count(media) == 1, 'Duplicate media export reservation'
    for length, start in reservations:
        start, length = int(start, 16), int(length, 16)
        if (start, length) == (0x41e600000, 0x400000):
            continue
        if start < 0x41ea00000 and start + length > 0x41e600000:
            raise RuntimeError('Reservation overlaps media export pool')
if native in sys.argv[3].split():
    # Reject overlaps from both kemco and caller-supplied extra reservations.
    reservations = re.findall(r'(?:^|\s)memrsv=(0x[0-9a-fA-F]+)@(0x[0-9a-fA-F]+)(?=[:\s]|$)', sys.argv[3])
    assert sys.argv[3].split().count(native) == 1, 'Duplicate ramfb reservation'
    for length, start in reservations:
        start, length = int(start, 16), int(length, 16)
        if (start, length) == (0x41e100000, native_bytes):
            continue
        if start < 0x41e100000+native_bytes and start + length > 0x41e100000:
            raise RuntimeError('Reservation overlaps native ramfb pool')
path = Path(sys.argv[1])
fdt = ctypes.CDLL(str(Path(sys.argv[2]).resolve()))
source = ctypes.create_string_buffer(path.read_bytes())
buffer = ctypes.create_string_buffer(16384)
if fdt.fdt_open_into(source, buffer, len(buffer)) != 0:
    raise RuntimeError('Cannot expand board DTB')
chosen = fdt.fdt_path_offset(buffer, b'/chosen')
value = sys.argv[3].encode() + b'\0'
if chosen < 0 or fdt.fdt_setprop(buffer, chosen, b'bootargs', value, len(value)) != 0:
    raise RuntimeError('Cannot set board bootargs')
# Keep the fixed-address DTB's initrd size consistent with the selected test image.
fdt.fdt_getprop.restype = ctypes.c_void_p
length = ctypes.c_int()
ptr = fdt.fdt_getprop(buffer, chosen, b'linux,initrd-start', ctypes.byref(length))
if not ptr or length.value not in (4, 8):
    raise RuntimeError('Cannot read board initrd address')
start = int.from_bytes(ctypes.string_at(ptr, length.value), 'big')
if sys.argv[5] == '1':
    start = 0x504000000
    value = start.to_bytes(length.value, 'big')
    if fdt.fdt_setprop(buffer, chosen, b'linux,initrd-start', value, len(value)) != 0:
        raise RuntimeError('Cannot set high initrd address')
end = start + Path(sys.argv[4]).stat().st_size
# free_initrd_mem returns every initrd page to Linux; keep it outside Sony image RAM.
if sys.argv[5] == '1' and (start < 0x500002000 or end > 0x580000000):
    raise RuntimeError('Initrd must fit outside reserved Sony workspace in virtual RAM')
value = end.to_bytes(length.value, 'big')
if fdt.fdt_setprop(buffer, chosen, b'linux,initrd-end', value, len(value)) != 0:
    raise RuntimeError('Cannot set board initrd end')
# Map the actual QEMU GIC distributor at the VA expected by Sony's IRQ helpers.
node = fdt.fdt_add_subnode(buffer, 0, b'sony-gic-alias')
if node < 0:
    raise RuntimeError('Cannot add GIC alias node')
props = {
    b'device_type': b'iomap\0',
    b'phys': struct.pack('>Q', 0x08000000),
    b'virt': struct.pack('>Q', 0xfffffffff13a1000),
    b'size': struct.pack('>Q', 0x1000),
    b'memtype': struct.pack('>I', 1),
}
for name, value in props.items():
    if fdt.fdt_setprop(buffer, node, name, value, len(value)) != 0:
        raise RuntimeError('Cannot set GIC alias property')
# LIRO's original IRQ trampoline acknowledges through this CPU-interface VA.
node = fdt.fdt_add_subnode(buffer, 0, b'sony-gicc-alias')
if node < 0:
    raise RuntimeError('Cannot add GIC CPU alias node')
for name, value in {
    b'device_type': b'iomap\0',
    b'phys': struct.pack('>Q', 0x08010000),
    b'virt': struct.pack('>Q', 0xfffffffff13a2000),
    b'size': struct.pack('>Q', 0x1000),
    b'memtype': struct.pack('>I', 1),
}.items():
    if fdt.fdt_setprop(buffer, node, name, value, len(value)) != 0:
        raise RuntimeError('Cannot set GIC CPU alias property')
if sys.argv[5] == '1':
    # Minimal GPIO register backing, not a behavioral camera-device model.
    node = fdt.fdt_add_subnode(buffer, 0, b'sony-register-backing')
    if node < 0:
        raise RuntimeError('Cannot add register backing')
    for name, value in {
        b'device_type': b'iomap\0',
        b'phys': struct.pack('>Q', 0xf101d000),
        b'virt': struct.pack('>Q', 0xfffffffff101d000),
        b'size': struct.pack('>Q', 0x20000),
        b'memtype': struct.pack('>I', 1),
    }.items():
        if fdt.fdt_setprop(buffer, node, name, value, len(value)) != 0:
            raise RuntimeError('Cannot map register backing')
    node = fdt.fdt_add_subnode(buffer, 0, b'sony-scu-map')
    if node < 0:
        raise RuntimeError('Cannot add SCU register map')
    for name, value in {
        b'device_type': b'iomap\0', b'phys': struct.pack('>Q', 0xf1388000),
        b'virt': struct.pack('>Q', 0xfffffffff1388000),
        b'size': struct.pack('>Q', 0x2000), b'memtype': struct.pack('>I', 1),
    }.items():
        if fdt.fdt_setprop(buffer, node, name, value, len(value)) != 0:
            raise RuntimeError('Cannot set SCU register map')
    # Locate RAM by device_type, then move the declared DDR bank to Sony's base.
    offset = fdt.fdt_next_node(buffer, -1, None)
    while offset >= 0:
        n = ctypes.c_int()
        p = fdt.fdt_getprop(buffer, offset, b'device_type', ctypes.byref(n))
        if p and ctypes.string_at(p, n.value).rstrip(b'\0') == b'memory':
            # Extra test RAM beyond camera workspaces holds the in-memory /usr copy.
            # Functional RAM-card routes use the same verified 8GiB bank as the
            # native AP CP link: the 1.49GB derived CPIO OOMs the legacy 6GiB bank.
            ddr_size = 0x200000000 if (os.environ.get('QEMU_NATIVE_AP_CP_LINK') == 'virtual-native-ap-cp-link-v1' or
                                        os.environ.get('A7C2_RAM_CARD_LAUNCH_PROFILE')) else 0x180000000
            value = struct.pack('>QQ', 0x400000000, ddr_size)
            if fdt.fdt_setprop(buffer, offset, b'reg', value, len(value)) != 0:
                raise RuntimeError('Cannot relocate guest DDR bank')
            break
        offset = fdt.fdt_next_node(buffer, offset, None)
    else:
        raise RuntimeError('Cannot find guest DDR bank')
    # Protect original Backup storage and monitor work area from the guest allocator.
    fdt.fdt_add_mem_rsv.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64]
    for base, length in ((0x404000000, 0x400000), (0x405000000, 0x800000),
                         (0x410268000, 0x7c000)):
        if fdt.fdt_add_mem_rsv(buffer, base, length) != 0:
            raise RuntimeError('Cannot reserve Sony workspace')
if sys.argv[5] == '1':
    node = fdt.fdt_add_subnode(buffer, 0, b'sony-timer-map')
    if node < 0:
        raise RuntimeError('Cannot add timer mapping')
    for name, value in {
        b'device_type': b'iomap\0', b'phys': struct.pack('>Q', 0xf1042000),
        b'virt': struct.pack('>Q', 0xfffffffff1042000),
        b'size': struct.pack('>Q', 0x4000), b'memtype': struct.pack('>I', 1),
    }.items():
        if fdt.fdt_setprop(buffer, node, name, value, len(value)) != 0:
            raise RuntimeError('Cannot set timer map property')
if os.environ.get('QEMU_NATIVE_AP_CP_LINK') == 'virtual-native-ap-cp-link-v1':
    runpy.run_path(str(Path(sys.argv[6])/'native_pcie_board.py'))['add_iomaps'](
        fdt,buffer,os.environ['QEMU_NATIVE_AP_CP_LINK'])
if os.environ.get('QEMU_SONY_RC')=='1':
    runpy.run_path(str(Path(sys.argv[6])/'native_rc_board.py'))['add_control_map'](fdt,buffer)
# Reject overlapping static virtual mappings before booting the unmodified kernel.
mappings = []
offset = fdt.fdt_next_node(buffer, -1, None)
while offset >= 0:
    count = ctypes.c_int()
    p = fdt.fdt_getprop(buffer, offset, b'device_type', ctypes.byref(count))
    if p and ctypes.string_at(p, count.value).rstrip(b'\0') == b'iomap':
        values = []
        for field in (b'virt', b'size'):
            p = fdt.fdt_getprop(buffer, offset, field, ctypes.byref(count))
            if not p or count.value != 8:
                raise RuntimeError('Invalid iomap property')
            values.append(int.from_bytes(ctypes.string_at(p, 8), 'big'))
        mappings.append((values[0], values[0] + values[1]))
    offset = fdt.fdt_next_node(buffer, offset, None)
mappings.sort()
if any(left[1] > right[0] for left, right in zip(mappings, mappings[1:])):
    raise RuntimeError('Overlapping iomap virtual ranges')
if os.environ.get('QEMU_PIN_CONTROL_MEMORY') == '1':
    runpy.run_path(str(Path(sys.argv[6]) / 'native-pin-control-region.py'))['reserve'](fdt, buffer, sys.argv[3])
if os.environ.get('QEMU_SYSTEM_SOUND_OWNER') == '1':
    runpy.run_path(str(Path(sys.argv[6]) / 'native-sound-region.py'))['reserve'](fdt, buffer, sys.argv[3])
if os.environ.get('QEMU_CPU_COUNT') == '2':
    runpy.run_path(str(Path(sys.argv[6]) / 'native_smp.py'))['configure'](fdt, buffer)
if os.environ.get('QEMU_SONY_RC') == '1':
    runpy.run_path(str(Path(sys.argv[6]) / 'native_rc_board.py'))['configure'](fdt, buffer)
if os.environ.get('QEMU_SONY_SA_REFERENCE_COMPLETE')=='1':
    runpy.run_path(str(Path(sys.argv[6])/'native_rc_board.py'))['reserve_sa_irq'](fdt,buffer)
if os.environ.get('QEMU_SONY_USB_DEVICE') == '1':
    runpy.run_path(str(Path(sys.argv[6])/'sony_usb_board.py'))['add_nodes'](fdt,buffer)
if fdt.fdt_pack(buffer) != 0:
    raise RuntimeError('Cannot pack board DTB')
size = struct.unpack_from('>I', buffer.raw, 4)[0]
path.write_bytes(buffer.raw[:size])
PY
fi
if [[ "$high_ddr" == 1 ]]; then
  memory_config=24576
  loader_args=(-device loader,file=/out/virt.dtb,addr=0x400002000
               -device loader,file=/kernel.img,addr=0x400080000,force-raw=on
               -device loader,file=/initrd.img,addr=0x504000000,force-raw=on
               -device loader,addr=0x400080000,cpu-num=0)
fi
wbi_resume="${QEMU_WBI_RESUME:-0}"
case "$wbi_resume" in 0|1) ;; *) echo 'QEMU_WBI_RESUME must be 0 or 1' >&2; exit 2 ;; esac
wbi_bind=()
wbi_args=()
if [[ "$wbi_resume" == 1 ]]; then
  [[ "${A7C2_STORAGE_PROFILE:-}" == product-single-disk-v1 ]] || { echo 'WBI resume requires the persistent single-disk profile' >&2; exit 2; }
  [[ -f "${QEMU_WBI_RAM:-}" && ! -L "${QEMU_WBI_RAM:-}" ]] || { echo 'QEMU_WBI_RAM must be a prepared sparse DDR image' >&2; exit 2; }
  [[ "${QEMU_WBI_ENTRY:-}" =~ ^0x[0-9a-fA-F]+$ ]] || { echo 'QEMU_WBI_ENTRY must be a hex address' >&2; exit 2; }
  memory_config=24576
  wbi_bind=(--ro-bind "$QEMU_WBI_RAM" /out/wbi-ddr.bin)
  wbi_args=(-device loader,file=/out/wbi-ddr.bin,addr=0x400000000,force-raw=on
            -device loader,addr="$QEMU_WBI_ENTRY",cpu-num=0)
fi
machine_args=(-machine virt,secure=off,gic-version=2)
if [[ "$wbi_resume" == 1 ]]; then machine_args=(-machine 'virt,secure=off,gic-version=2'); fi

# Iteration profile: a large TCG translation cache avoids retranslation thrash
# while the original firmware loops; single thread matches the timing contract.
if [[ "${A7C2_BOOT_QUIET:-}" == 1 || -n "${A7C2_ORIGINAL_COLD:-}" ]]; then
  machine_args+=(-accel tcg,thread=single,tb-size=2048)
fi
boot_args=(-kernel /kernel.img -initrd /initrd.img -append "$cmdline")
if [[ "$wbi_resume" == 1 ]]; then
  boot_args=("${wbi_args[@]}")
  loader_args=()
fi
mkdir -p "$output_dir"
if [[ -n "${QEMU_OUTPUT_DIR:-}" ]]; then
  selected_output="$QEMU_OUTPUT_DIR"
  mkdir -p "$selected_output"
  [[ -f "$output_dir/virt.dtb" ]] && install -m 0644 "$output_dir/virt.dtb" "$selected_output/virt.dtb"
  output_dir="$selected_output"
fi
if [[ "${QEMU_PREPARE_ONLY:-0}" == 1 ]]; then
  printf 'Prepared board DTB: %s\n' "$output_dir/virt.dtb"
  exit 0
fi
if [[ "$rc_profile" == 1 || "$gic_handoff" == 1 ]]; then
  python3 - "$analysis_dir" "$tool_root/$binary_relative" "$rc_profile" "$gic_handoff" "$sa_data_only" "$sa_reference_complete" <<'PY'
from pathlib import Path
import runpy,sys
runpy.run_path(str(Path(sys.argv[1])/'native_rc_board.py'))['require_binary'](
    Path(sys.argv[2]),reference=sys.argv[3]=='1',handoff=sys.argv[4]=='1',sa_data=sys.argv[5]=='1',sa_complete=sys.argv[6]=='1')
PY
fi
persistent_bind=()
persistent_environment=()
persistent_fd_options=()
if [[ -n "${A7C2_STORAGE_PROFILE:-}" ]]; then
  [[ "$A7C2_STORAGE_PROFILE" == product-single-disk-v1 ]] || { echo 'Unknown internal storage profile' >&2; exit 2; }
  python3 -B - "$analysis_dir" <<'PY'
import sys,os
sys.path.insert(0,sys.argv[1])
from persistent_storage import inherited_fd
inherited_fd(os.environ)
PY
  [[ -f "$A7C2_EMMC_INSTANCE/persistent-geometry.bin" && ! -L "$A7C2_EMMC_INSTANCE/persistent-geometry.bin" ]] || { echo 'Internal disk geometry missing' >&2; exit 2; }
  persistent_bind=(--dir /instance --ro-bind "$A7C2_EMMC_INSTANCE/persistent-geometry.bin" /instance/persistent-geometry.bin)
  persistent_environment=(--setenv QEMU_A7PF_PROFILE persistent-flash-cold-v1
    --setenv QEMU_A7PF_FD "$A7C2_EMMC_FD" --setenv QEMU_A7PF_DEV "$A7C2_EMMC_DEV" --setenv QEMU_A7PF_INO "$A7C2_EMMC_INO")
  if [[ -n "${QEMU_A7PF_WRITEBACK_FLUSH:-}" ]]; then
    [[ "$QEMU_A7PF_WRITEBACK_FLUSH" == 1 ]] || { echo 'Invalid writeback-flush profile' >&2; exit 2; }
    persistent_environment+=(--setenv QEMU_A7PF_WRITEBACK_FLUSH 1)
  fi
  if [[ "$ram_session" == 1 ]]; then
    persistent_environment+=(--setenv QEMU_A7PF_RETAINED_STATE 1)
  fi
  if [[ -z "$settings_restart" ]] && bwrap --help | grep -q -- --preserve-fds; then persistent_fd_options=(--preserve-fds "$((A7C2_EMMC_FD-2))"); fi
fi
native_link_bind=()
native_link_environment=()
native_link_args=()
if [[ -n "${QEMU_NATIVE_AP_CP_LINK:-}" ]]; then
  python3 -B - "$analysis_dir" "$tool_root/$binary_relative" "$memory_config" "$output_dir" <<'PY'
from pathlib import Path
import json,os,runpy,sys
api=runpy.run_path(str(Path(sys.argv[1]).parents[1]/'source/cp-boot/native-link.py'))
proof=api['admit_ap'](Path(os.environ.get('QEMU_NATIVE_LINK_DIR','')),Path(sys.argv[2]),int(sys.argv[3]),os.environ)
args=api['ram_arguments'](Path(os.environ['QEMU_NATIVE_LINK_DIR']),'ap',sandbox=True)
with (Path(sys.argv[4])/'native-link-args.nul').open('xb') as stream:
    stream.write(b''.join(arg.encode('utf-8')+b'\0' for arg in args))
with (Path(sys.argv[4])/'native-link-admission.json').open('x') as stream:
    json.dump(proof,stream,indent=2);stream.write('\n')
PY
  mapfile -d '' -t native_link_args < "$output_dir/native-link-args.nul"
  native_link_bind=(--bind "$QEMU_NATIVE_LINK_DIR" /native-link)
  native_link_environment=(--setenv QEMU_NATIVE_AP_CP_LINK virtual-native-ap-cp-link-v1
    --setenv QEMU_AP_CP_GPIO_LINES virtual-ap-cp-gpio-lines-v1 --setenv QEMU_AP_CP_GPIO_SIDE ap
    --setenv QEMU_SONY_TIMERS 1 --setenv QEMU_SONY_PCIDMA 1)
  if [[ -n "${QEMU_NATIVE_P1_SPI_COMPONENT:-}" ]]; then
    [[ "$QEMU_NATIVE_P1_SPI_COMPONENT" == virtual-p1-pl022-component-v1 ]] || {
      echo 'Unknown P1 SPI component profile' >&2; exit 2;
    }
    native_link_environment+=(--setenv QEMU_NATIVE_P1_SPI_COMPONENT virtual-p1-pl022-component-v1)
  fi
  native_link_args+=(-chardev socket,id=notify-peer,path=/native-link/notify.sock,server=on,wait=off)
  machine_args=(-machine virt,secure=off,gic-version=2,memory-backend=native-local-ram)
fi
fast_shm_args=()
if [[ "${A7C2_FAST_SHM:-0}" == 1 && -n "${A7C2_FAST_SHM_FD:-}" && -z "${QEMU_NATIVE_AP_CP_LINK:-}" && "$ram_session" == 0 ]]; then
  [[ "$A7C2_FAST_SHM_FD" =~ ^[1-9][0-9]*$ && "$A7C2_FAST_SHM_FD" -ge 3 ]] || { echo 'Invalid A7C2_FAST_SHM_FD' >&2; exit 2; }
  machine_args=(-machine virt,secure=off,gic-version=2,memory-backend=fast-shm-ram)
  if [[ "${A7C2_BOOT_QUIET:-}" == 1 || -n "${A7C2_ORIGINAL_COLD:-}" ]]; then
    machine_args+=(-accel tcg,thread=single,tb-size=2048)
  fi
  fast_shm_args=(-object "memory-backend-file,id=fast-shm-ram,size=${memory_config}M,mem-path=/proc/self/fd/${A7C2_FAST_SHM_FD},share=on")
  if [[ -z "$settings_restart" ]] && bwrap --help | grep -q -- --preserve-fds; then
    _fast_max_fd="${A7C2_EMMC_FD:-3}"
    (( A7C2_FAST_SHM_FD > _fast_max_fd )) && _fast_max_fd="$A7C2_FAST_SHM_FD"
    persistent_fd_options=(--preserve-fds "$((_fast_max_fd-2))")
  fi
fi
scope_bind=()
scope_args=()
if [[ -n "${QEMU_SCOPE_OBSERVER_PLUGIN:-}" ]]; then
  [[ "$cpu_count" == 1 && "$native_window" == 1 && "${MENU_FUNCTIONAL_CAMERA:-}" == virtual-functional-camera-v1 &&
     "${QEMU_SCOPE_OBSERVER_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || {
    echo 'Scope observer requires its bound single-vCPU functional host profile' >&2; exit 2;
  }
  python3 - "$QEMU_SCOPE_OBSERVER_PLUGIN" "$QEMU_SCOPE_OBSERVER_SHA256" "$output_dir/readonly-scope-trace.log" <<'PY'
from pathlib import Path
import hashlib,os,stat,sys
plugin=Path(sys.argv[1])
if not plugin.is_absolute() or plugin.is_symlink() or not stat.S_ISREG(plugin.stat().st_mode):
    raise ValueError('Scope observer plugin is not an absolute ordinary file')
with plugin.open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest()!=sys.argv[2]:
        raise ValueError('Scope observer plugin changed before sandbox bind')
if os.path.lexists(sys.argv[3]):
    raise ValueError('Scope observer refuses a reused trace file')
PY
  scope_bind=(--ro-bind "$QEMU_SCOPE_OBSERVER_PLUGIN" /scope-observer.so)
  scope_args=(-plugin /scope-observer.so,log=/out/readonly-scope-trace.log)
elif [[ -n "${QEMU_SCOPE_OBSERVER_SHA256:-}" ]]; then
  echo 'Scope observer digest has no matched plugin' >&2; exit 2
fi
writer_bind=()
writer_args=()
if [[ -n "${QEMU_SHUTTER_WRITER_PLUGIN:-}" ]]; then
  [[ "$cpu_count" == 1 && "$native_window" == 1 && "${MENU_FUNCTIONAL_CAMERA:-}" == virtual-functional-camera-v1 &&
     -n "${QEMU_SCOPE_OBSERVER_PLUGIN:-}" && "${QEMU_SHUTTER_WRITER_SHA256:-}" =~ ^[0-9a-f]{64}$ ]] || {
    echo 'Writer observer requires its bound strict primary and single-vCPU functional host profile' >&2; exit 2;
  }
  python3 - "$QEMU_SHUTTER_WRITER_PLUGIN" "$QEMU_SHUTTER_WRITER_SHA256" "$output_dir/readonly-shutter-writer.log" <<'PY'
from pathlib import Path
import hashlib,os,stat,sys
plugin=Path(sys.argv[1])
if not plugin.is_absolute() or plugin.resolve(strict=True)!=plugin or any(p.is_symlink() for p in (plugin,*plugin.parents)):
    raise ValueError('Writer plugin path is not canonical')
info=plugin.stat()
if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o400:
    raise ValueError('Writer plugin must be an exclusive read-only owned regular file')
with plugin.open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest()!=sys.argv[2]:
        raise ValueError('Writer plugin changed before sandbox bind')
if os.path.lexists(sys.argv[3]):
    raise ValueError('Writer plugin refuses a reused trace')
PY
  writer_bind=(--ro-bind "$QEMU_SHUTTER_WRITER_PLUGIN" /shutter-writer.so)
  writer_args=(-plugin /shutter-writer.so,log=/out/readonly-shutter-writer.log)
elif [[ -n "${QEMU_SHUTTER_WRITER_SHA256:-}" ]]; then
  echo 'Writer observer digest has no matched plugin' >&2; exit 2
fi
incoming_args=()
if [[ "$ram_session" == 1 || "${QEMU_RAM_INCOMING:-0}" != 0 ]]; then
  [[ "$ram_session" == 1 && "${A7C2_ORIGINAL_COLD:-}" == original-init-v1 &&
     "${QEMU_UI_LIVE:-0}" == 1 && "$observation_seconds" == 0 &&
     "${QEMU_SONY_USB_DEVICE:-0}" == 0 && -z "${A7C2_HOST_SD:-}" &&
     -z "${A7C2_DIRECTORY_SD:-}" ]] || {
    echo 'RAM session requires original cold GTK without USB device or host SD' >&2; exit 2; }
fi
if [[ "${QEMU_RAM_INCOMING:-0}" != 0 ]]; then
  [[ "${QEMU_RAM_INCOMING}" == defer ]] || { echo 'QEMU_RAM_INCOMING must be defer' >&2; exit 2; }
  incoming_args=(-S -incoming defer)
fi
# The parent owns QMP shutdown; never send timeout signals to a VM.
ram_input_bind=(--ro-bind "$test_initrd" /initrd.img)
ram_fd_options=()
ram_fd_environment=()
ram_handoff_bind=()
ram_handoff_launch=()
ram_qemu_path="/tools/$binary_relative"
if [[ -n "${A7C2_RAM_CARD_LAUNCH_PROFILE:-}" ]]; then
  [[ "$A7C2_RAM_CARD_LAUNCH_PROFILE" == inherited-ram-card-fds-v1 &&
     "${A7C2_FUNCTIONAL_RAM_CONSUMER:-}" == inherited-ram-card-fds-v1 &&
     "${MENU_FUNCTIONAL_CAMERA:-}" == virtual-functional-camera-v1 &&
     ( -z "${A7C2_STORAGE_PROFILE:-}" || "$settings_restart" == functional-ram-card-independent-internal-v1 ) &&
     "$test_initrd" == *.cpio ]] || {
    echo 'Inherited RAM-card launch requires the explicit functional raw-initramfs route' >&2; exit 2;
  }
  ram_max_fd="$(python3 -B - "$analysis_dir" <<'RAM_CARD_FD_HANDOFF'
import os,sys
sys.path.insert(0,sys.argv[1])
from functional_camera_runner import verify_ram_card_inherited
print(verify_ram_card_inherited(os.environ))
RAM_CARD_FD_HANDOFF
)"
  [[ "$ram_max_fd" =~ ^[1-9][0-9]*$ && "$ram_max_fd" -ge 3 ]] || exit 2
  if [[ -n "$settings_restart" ]]; then
    # One preserve range must cover the writable internal OFD as well as the five RAM inputs.
    [[ "$A7C2_EMMC_FD" =~ ^[1-9][0-9]*$ && "$A7C2_EMMC_FD" -ge 3 ]] || { echo 'Internal settings descriptor is invalid' >&2; exit 2; }
    (( A7C2_EMMC_FD > ram_max_fd )) && ram_max_fd="$A7C2_EMMC_FD"
  fi
  ram_input_bind=(--ro-bind "/proc/self/fd/$A7C2_RAM_CARD_INITRAMFS_FD" /initrd.img
                  --ro-bind "/proc/self/fd/$A7C2_RAM_CARD_QEMU_FD" /qemu-system-aarch64)
  ram_qemu_path=/qemu-system-aarch64
  ram_bwrap_help="$(bwrap --help)"
  if grep -q -- --preserve-fds <<< "$ram_bwrap_help"; then
    ram_fd_options=(--preserve-fds "$((ram_max_fd-2))")
    for ram_fd_name in SEED DIRECTORY RECEIPT INITRAMFS QEMU; do
      ram_fd_variable="A7C2_RAM_CARD_${ram_fd_name}_FD"
      ram_fd_environment+=(--setenv "$ram_fd_variable" "${!ram_fd_variable}")
    done
    if [[ -n "$settings_restart" ]]; then
      ram_fd_environment+=(--setenv A7C2_SETTINGS_RESTART_PROFILE "$settings_restart"
                           --setenv A7C2_STORAGE_PROFILE "$A7C2_STORAGE_PROFILE"
                           --setenv A7C2_EMMC_FD "$A7C2_EMMC_FD"
                           --setenv A7C2_EMMC_DEV "$A7C2_EMMC_DEV"
                           --setenv A7C2_EMMC_INO "$A7C2_EMMC_INO"
                           --setenv A7C2_EMMC_INSTANCE "$A7C2_EMMC_INSTANCE")
    fi
  elif grep -q -- --ro-bind-fd <<< "$ram_bwrap_help"; then
    # bwrap consumes --ro-bind-fd descriptors; expose verified inodes as read-only paths.
    # No --preserve-fds here, so the read-only inputs travel as inode binds and the
    # writable internal disk keeps its owner OFD through a SCM_RIGHTS handoff: a bind
    # mount would reopen the inode as a different OFD (measurements in the task report).
    ram_input_bind=(--ro-bind-fd "$A7C2_RAM_CARD_INITRAMFS_FD" /initrd.img
                    --ro-bind-fd "$A7C2_RAM_CARD_QEMU_FD" /qemu-system-aarch64)
    ram_fd_options=(--dir /ram-card
                    --ro-bind-fd "$A7C2_RAM_CARD_SEED_FD" /ram-card/seed
                    --ro-bind-fd "$A7C2_RAM_CARD_DIRECTORY_FD" /ram-card/directory
                    --ro-bind-fd "$A7C2_RAM_CARD_RECEIPT_FD" /ram-card/receipt)
    ram_fd_environment=(--setenv A7C2_RAM_CARD_SEED_PATH /ram-card/seed
                        --setenv A7C2_RAM_CARD_DIRECTORY_PATH /ram-card/directory
                        --setenv A7C2_RAM_CARD_RECEIPT_PATH /ram-card/receipt
                        --setenv A7C2_RAM_CARD_INITRAMFS_PATH /initrd.img
                        --setenv A7C2_RAM_CARD_QEMU_PATH /qemu-system-aarch64)
    if [[ -n "$settings_restart" ]]; then
      # The sixth descriptor is the leased writable internal disk; only the owner's own
      # open file description may reach QEMU, so it is not rebound from a path.
      [[ "$A7C2_EMMC_FD" =~ ^[1-9][0-9]*$ && "$A7C2_EMMC_DEV" =~ ^[0-9]+$ &&
         "$A7C2_EMMC_INO" =~ ^[0-9]+$ ]] || { echo 'Internal settings descriptor identity is invalid' >&2; exit 2; }
      internal_handoff_dir="/run/user/$(id -u)/a7c2-internal-disk-$$"
      internal_handoff_socket="$internal_handoff_dir/internal-disk.sock"
      [[ ! -e "$internal_handoff_dir" ]] || { echo 'Internal disk handoff directory already exists' >&2; exit 2; }
      mkdir -m 0700 -- "$internal_handoff_dir" || { echo 'Internal disk handoff directory refused' >&2; exit 2; }
      python3 -B - "$internal_handoff_socket" "$A7C2_EMMC_FD" "$A7C2_EMMC_DEV" "$A7C2_EMMC_INO" <<'INTERNAL_DISK_HANDOFF' >&2 &
import fcntl,os,socket,stat,struct,sys
path,number,device,inode=sys.argv[1],int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4])
info=os.fstat(number)
if ((info.st_dev,info.st_ino)!=(device,inode) or not stat.S_ISREG(info.st_mode) or
        fcntl.fcntl(number,fcntl.F_GETFL)&os.O_ACCMODE!=os.O_RDWR):
    raise SystemExit('Internal disk broker lost the verified descriptor identity')
listener=socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET)
listener.bind(path)
os.chmod(path,0o600)
listener.listen(1)
listener.settimeout(60)
try:
    connection,_=listener.accept()
    connection.settimeout(60)
    connection.sendmsg([b'1'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,struct.pack('i',number))])
    connection.recv(1)
    connection.close()
finally:
    listener.close()
    try:os.unlink(path)
    except OSError:pass
    try:os.rmdir(os.path.dirname(path))
    except OSError:pass
INTERNAL_DISK_HANDOFF
      for _attempt in $(seq 1 500); do
        [[ -S "$internal_handoff_socket" ]] && break
        sleep 0.02
      done
      [[ -S "$internal_handoff_socket" ]] || { rmdir -- "$internal_handoff_dir" 2>/dev/null || :; echo 'Internal disk handoff broker did not publish its socket' >&2; exit 2; }
      ram_handoff_bind=(--bind "$internal_handoff_dir" /internal-disk
                        --ro-bind "$analysis_dir/ram_card_fd_receiver.py" /internal-disk-receiver.py)
      ram_handoff_launch=(/usr/bin/env -u LD_LIBRARY_PATH /usr/bin/python3 -B /internal-disk-receiver.py
                          /internal-disk/internal-disk.sock "$A7C2_EMMC_FD" "$A7C2_EMMC_DEV"
                          "$A7C2_EMMC_INO" "$sandbox_library_path" --)
      ram_fd_environment+=(--setenv A7C2_SETTINGS_RESTART_PROFILE "$settings_restart"
                           --setenv A7C2_STORAGE_PROFILE "$A7C2_STORAGE_PROFILE"
                           --setenv A7C2_EMMC_FD "$A7C2_EMMC_FD"
                           --setenv A7C2_EMMC_DEV "$A7C2_EMMC_DEV"
                           --setenv A7C2_EMMC_INO "$A7C2_EMMC_INO")
    fi
  else
    echo 'This sandbox cannot bind or preserve the exact RAM-card descriptor handoff' >&2; exit 2
  fi
  ram_fd_environment+=(--setenv A7C2_RAM_CARD_LAUNCH_PROFILE "$A7C2_RAM_CARD_LAUNCH_PROFILE")
fi
runner=(exec)
"${runner[@]}" \
  bwrap --unshare-all --die-with-parent --new-session --clearenv \
    --ro-bind /usr /usr --symlink usr/lib /lib --symlink usr/lib /lib64 \
    --proc /proc --dev /dev --tmpfs /tmp \
    --ro-bind "$tool_root" /tools \
    --ro-bind "$bootfs/vmlinux.bin" /kernel.img \
    "${ram_input_bind[@]}" \
    --bind "$output_dir" /out \
    "${socket_bind[@]}" \
    --chdir / --setenv LD_LIBRARY_PATH "$sandbox_library_path" --setenv LC_ALL C \
    "${timer_environment[@]}" \
    "${persistent_fd_options[@]}" "${persistent_bind[@]}" "${persistent_environment[@]}" \
    "${ram_fd_options[@]}" "${ram_fd_environment[@]}" "${ram_handoff_bind[@]}" \
    "${wbi_bind[@]}" \
    "${native_link_bind[@]}" "${native_link_environment[@]}" \
    "${pcidma_environment[@]}" \
    "${display_environment[@]}" \
    "${scope_bind[@]}" \
    "${writer_bind[@]}" \
    "${ram_handoff_launch[@]}" "${qemu_prefix[@]}" "$ram_qemu_path" \
      "${machine_args[@]}" -cpu cortex-a35 -smp "$cpu_count" -m "$memory_config" \
      ${QEMU_ICOUNT_ARGS:-} \
      -nodefaults "${display_args[@]}" -monitor none -serial stdio -nic none \
      -no-reboot -sandbox on -qmp unix:$socket_dir/qmp.sock,server=on,wait=off \
      -qmp unix:$socket_dir/lcd-qmp.sock,server=on,wait=off \
      "${usb_device_qmp[@]}" \
      "${usb_generation_args[@]}" \
      "${debug_args[@]}" \
      "${scope_args[@]}" \
      "${writer_args[@]}" \
      "${incoming_args[@]}" \
      "${native_link_args[@]}" \
      "${fast_shm_args[@]}" \
      "${boot_args[@]}" "${loader_args[@]}" \
      "${trace_args[@]}"
