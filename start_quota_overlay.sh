#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin=$(command -v python3 || true)

if [ -z "$python_bin" ]; then
  echo "python3 was not found" >&2
  exit 1
fi

runtime_dir=${XDG_RUNTIME_DIR:-/tmp}
user_id=$(id -u)
lock_file="$runtime_dir/codex-quota-overlay-$user_id.lock"

if command -v flock >/dev/null 2>&1; then
  exec flock -n "$lock_file" "$python_bin" "$app_dir/codex_quota_overlay.py" "$@"
fi

exec "$python_bin" "$app_dir/codex_quota_overlay.py" "$@"
