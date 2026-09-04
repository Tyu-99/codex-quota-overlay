#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin=$(command -v python3 || true)
chatgpt_bin=$(command -v chatgpt || true)

if [ -z "$python_bin" ]; then
  echo "python3 was not found" >&2
  exit 1
fi
if [ -z "$chatgpt_bin" ]; then
  echo "ChatGPT desktop launcher was not found" >&2
  exit 1
fi

runtime_dir=${XDG_RUNTIME_DIR:-/tmp}
user_id=$(id -u)
lock_file="$runtime_dir/codex-quota-overlay-$user_id.lock"

if command -v flock >/dev/null 2>&1; then
  flock -n "$lock_file" "$python_bin" "$app_dir/codex_quota_overlay.py" >/dev/null 2>&1 &
else
  "$python_bin" "$app_dir/codex_quota_overlay.py" >/dev/null 2>&1 &
fi

exec "$chatgpt_bin" "$@"
