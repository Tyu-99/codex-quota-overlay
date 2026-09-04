#!/bin/sh
set -eu

app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python_bin=$(command -v python3 || true)
if [ -z "$python_bin" ]; then
  echo "python3 was not found" >&2
  exit 1
fi

applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
desktop_file="$applications_dir/codex-quota-overlay.desktop"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$desktop_file"
  echo "Removed the Codex Quota Overlay application-menu entry"
  exit 0
fi

"$python_bin" "$app_dir/codex_quota_overlay.py" --self-check

mkdir -p "$applications_dir"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=Codex Quota Overlay'
  printf '%s\n' 'Comment=Show ChatGPT/Codex plan quota'
  printf 'Exec=%s\n' "$app_dir/start_quota_overlay.sh"
  printf 'TryExec=%s\n' "$app_dir/start_quota_overlay.sh"
  printf '%s\n' 'Terminal=false'
  printf '%s\n' 'Categories=Utility;Development;'
} > "$desktop_file"

echo "Installed the Codex Quota Overlay application-menu entry"
echo "Use the new application-menu entry or run: $app_dir/start_quota_overlay.sh"
