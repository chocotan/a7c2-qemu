#!/usr/bin/env bash
set -euo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -gt 0 ]]; then
  echo "start.sh 不接受命令行参数；请编辑 $here/a7c2.env 或通过环境变量配置（例如 A7C2_VERIFY_SHA=1 ./start.sh）。" >&2
  exit 2
fi

env_file="${A7C2_ENV_FILE:-$here/a7c2.env}"
if [[ -n "${A7C2_ENV_FILE:-}" && ! -f "$env_file" ]]; then
  echo "指定的环境变量文件不存在：$env_file" >&2
  exit 2
fi
if [[ -f "$env_file" ]]; then
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="${raw_line%$'\r'}"
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
    fi
    if [[ "$line" != *=* ]]; then
      echo "环境变量文件语法无效 ($env_file): $raw_line" >&2
      exit 2
    fi
    key="${line%%=*}"
    val="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "环境变量名无效 ($env_file): $key" >&2
      exit 2
    fi
    if [[ ${#val} -ge 2 && ( ( "${val:0:1}" == '"' && "${val: -1}" == '"' ) || ( "${val:0:1}" == "'" && "${val: -1}" == "'" ) ) ]]; then
      val="${val:1:${#val}-2}"
    fi
    # Caller-exported environment variables take precedence over a7c2.env.
    if [[ -z "${!key+x}" ]]; then
      export "$key=$val"
    fi
  done < "$env_file"
fi

export PYTHONDONTWRITEBYTECODE=1
# Keep helper temporaries on the package filesystem rather than the host /tmp quota.
case "${TMPDIR:-}" in
  ''|/tmp|/tmp/*)
    mkdir -p "$here/runtime/tmp"
    export TMPDIR="$here/runtime/tmp"
    ;;
esac
entry="$here/runtime/analysis/bodydata-launch.py"
[[ -f "$entry" ]] || { echo '运行程序尚未装配完成，请查看本目录 README 的当前状态。' >&2; exit 2; }
exec python3 "$entry"
