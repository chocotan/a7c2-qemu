#!/bin/busybox sh
set -e
[ ! -r /simulation/environment.sh ] || . /simulation/environment.sh || exit 1
base=/tmp/sony-sd1g
card=$base/card.img
if [ -e "$base" ]; then
    # The mountpoint directory persists on nflasha10; its tmpfs contents do not.
    /bin/busybox rmdir "$base" || exit 78
fi
/bin/busybox mkdir "$base" || exit 1
/bin/busybox mount -t tmpfs -o size=512m tmpfs "$base" || exit 1
: > "$card" || exit 1
read -r total expected < /simulation/sd-seed/identity.txt || exit 1
[ "$total" = 1073741824 ] || exit 78
case "$expected" in
    *[!0-9a-f]*|'') exit 78;;
esac
[ "${#expected}" = 64 ] || exit 78
previous_end=0
while read -r offset length name digest extra; do
    [ -z "$extra" ] || exit 78
    case "$offset:$length" in *[!0-9:]*|:*|*:) exit 78;; esac
    [ $((offset % 4096)) = 0 ] && [ $((length % 4096)) = 0 ] || exit 78
    [ "$length" -gt 0 ] && [ "$length" -le 4194304 ] || exit 78
    [ "$offset" -ge "$previous_end" ] || exit 78
    [ $((offset + length)) -le "$total" ] || exit 78
    case "$name" in chunk-??????.bin) ;; *) exit 78;; esac
    digits=${name#chunk-}; digits=${digits%.bin}
    case "$digits" in *[!0-9]*) exit 78;; esac
    case "$digest" in *[!0-9a-f]*|'') exit 78;; esac
    [ "${#digest}" = 64 ] || exit 78
    /simulation/sd-sparse write "$card" "/simulation/sd-seed/$name" "$offset" || exit 1
    if [ "${PRODUCT_COLD_SKIP_SHA:-0}" != 1 ]; then
        actual=$(/usr/bin/openssl dgst -sha256 "/simulation/sd-seed/$name") || exit 1
        case "$actual" in *"= $digest") ;; *) exit 78;; esac
    fi
    previous_end=$((offset + length))
done < /simulation/sd-seed/chunks.txt
# Allocate no zero tail; never overwrite a nonzero terminal block.
if [ "$previous_end" != "$total" ]; then
    /simulation/sd-sparse write "$card" /simulation/sd-seed/zero.bin $((total - 4096)) || exit 1
fi
if [ "${PRODUCT_COLD_SKIP_SHA:-0}" != 1 ]; then
    actual=$(/usr/bin/openssl dgst -sha256 "$card") || exit 1
    case "$actual" in *"= $expected") ;; *) echo PRODUCT_SD_FULL_READBACK_FAILED; exit 78;; esac
fi
/bin/busybox mount --bind "$card" /image_mmca || exit 1
echo "PRODUCT_SD_1G_READY bytes=$total sha256=$expected chunks=$previous_end"
/simulation/sd-sparse map || exit 1
