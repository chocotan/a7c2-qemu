#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONDONTWRITEBYTECODE=1
# Keep helper temporaries on the package filesystem rather than the host /tmp quota.
if [[ -z "${TMPDIR:-}" || "$TMPDIR" == /tmp ]]; then
  mkdir -p "$here/runtime/tmp"
  export TMPDIR="$here/runtime/tmp"
fi
entry="$here/runtime/analysis/bodydata-launch.py"
[[ -f "$entry" ]] || { echo '运行程序尚未装配完成，请查看本目录 README 的当前状态。' >&2; exit 2; }
exec python3 "$entry" "$@"
