#!/usr/bin/env bash
# Separate raw cpio test root; the original kernel has no gzip initrd support.
set -euo pipefail
analysis_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
root="$analysis_dir/menu-root"
boot="$analysis_dir/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked"
output="$analysis_dir/menu-initramfs.cpio"
exclude_updater=()
if [[ "${1:-}" == --without-updater ]]; then
  output="$analysis_dir/menu-initramfs-no-updater.cpio"
  exclude_updater=(-path './usr/lib/libupdaterufp.so' -prune -o)
elif [[ $# != 0 ]]; then
  echo 'Usage: prepare-menu-initramfs.sh [--without-updater]' >&2
  exit 2
fi
for file in "$boot/"*.bin "$boot/"*.hcd; do cp -a "$file" "$root/system/"; done
# im.elf loads IMDB from a fixed /usr/lib path; only this generated test root uses the qemu-filtered copy.
chmod u+w "$root/usr/lib/libIMDB.so"
cp "$analysis_dir/libIMDB-menu.so" "$root/usr/lib/libIMDB.so"
chmod 0555 "$root/usr/lib/libIMDB.so"
mkdir -p "$root/simulation" "$root/seed-setting"
cp -f "$analysis_dir/libIMDB-menu.so" "$root/simulation/libIMDB.so"
cp "$analysis_dir/menu-observe.so" "$root/simulation/menu-observe.so"
# Only the official ALLLANG package is accepted; no adjacent research settings are read.
if [ -f "$analysis_dir/native-assets.json" ]; then
  echo 'seed: using verified installed ALLLANG assets'
else
  cp -a "$analysis_dir/unpacked/firmware.tar_unpacked/0800_appli/setting/." "$root/seed-setting/"
  cp "$analysis_dir/unpacked/firmware.tar_unpacked/0110_backup/SYSIPSX-DSLR/PP/CX89701_ALLLANG.bin" "$root/seed-backup.bin"
  echo "seed: using the update package ALLLANG Backup"
fi
printf '%s\n' '#!/bin/busybox sh' \
  '/bin/busybox mount -t devtmpfs devtmpfs /dev' \
  'exec /bin/busybox sh </dev/ttyAMA0 >/dev/ttyAMA0 2>&1' > "$root/init"
chmod 0755 "$root/init"
# PRELOAD_ALL=1 puts the observer into every dynamically linked guest process through
# /etc/ld.so.preload, so senders and queue creators outside im.elf become visible.
mkdir -p "$root/etc"
if [ "${PRELOAD_ALL:-0}" = 1 ]; then
  printf '/simulation/menu-observe.so\n' > "$root/etc/ld.so.preload"
  echo "preload: observer injected into every guest process"
else
  rm -f "$root/etc/ld.so.preload"
fi
# ponytail: speech dictionaries are excluded from this menu-only test image;
# include them if screen-reader behavior becomes part of the experiment.
pad_bytes="${CPIO_PAD_BYTES:-0}"
if [ "$pad_bytes" != "0" ]; then
  head -c "$pad_bytes" /dev/zero > "$root/simulation/.pad"
else
  rm -f "$root/simulation/.pad"
fi
(cd "$root" && find . -path './usr/share/screenreader' -prune -o "${exclude_updater[@]}" -print0 |
  cpio --null -o -H newc --quiet) > "$output"
if [[ ${MENU_SD_IMAGE+x} ]]; then
  [[ -f "$MENU_SD_IMAGE" && ! -L "$MENU_SD_IMAGE" ]] || {
    echo 'MENU_SD_IMAGE must be a regular host file' >&2; exit 1;
  }
  # Append from a temporary tree so menu-root never retains a previous run's SD.
  (
    sd_stage="$(mktemp -d)"
    trap 'rm -rf -- "$sd_stage"' EXIT
    mkdir "$sd_stage/simulation"
    python3 - "$analysis_dir" "$MENU_SD_IMAGE" "$sd_stage/simulation/sd-card.fat" <<'PY'
import os,sys,subprocess,shutil
sys.path.insert(0,sys.argv[1])
from sd_transport import card_source,RESERVE
with card_source(sys.argv[2]) as fd:
    if shutil.disk_usage(os.path.dirname(sys.argv[3])).free<os.fstat(fd).st_size+RESERVE:
        raise ValueError('Insufficient space for virtual SD seed')
    subprocess.run(['fsck.fat','-n',f'/proc/self/fd/{fd}'],pass_fds=(fd,),check=True,capture_output=True)
    os.lseek(fd,0,os.SEEK_SET)
    with open(sys.argv[3],'xb') as output:
        while block:=os.read(fd,0x400000):output.write(block)
        output.flush();os.fsync(output.fileno())
PY
    printf 'SD_IMAGE_SHA256=%s guest=/simulation/sd-card.fat\n' \
      "$(sha256sum "$sd_stage/simulation/sd-card.fat" | cut -d ' ' -f 1)"
    cd "$sd_stage"
    printf '%s\0' './simulation/sd-card.fat' |
      cpio --null -o -A -F "$output" -H newc --quiet
  )
fi
printf 'Prepared raw cpio menu test root (screen-reader speech files excluded).\n'
ls -lh "$output"
