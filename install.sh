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
  echo "Removed the Codex Quota Overlay launcher"
  exit 0
fi

"$python_bin" "$app_dir/codex_quota_overlay.py" --self-check

mkdir -p "$applications_dir"

{
  printf '%s\n' '[Desktop Entry]'
  printf '%s\n' 'Type=Application'
  printf '%s\n' 'Name=ChatGPT/Codex with Quota'
  printf '%s\n' 'Comment=Launch ChatGPT/Codex with the quota overlay'
  printf 'Exec=%s %%U\n' "$app_dir/start_codex_with_quota.sh"
  printf 'TryExec=%s\n' "$app_dir/start_codex_with_quota.sh"
  printf '%s\n' 'Terminal=false'
  printf '%s\n' 'Categories=Utility;Development;'
} > "$desktop_file"

echo "Installed the ChatGPT/Codex with Quota launcher"
echo "Use the new application menu entry or run: $app_dir/start_codex_with_quota.sh"
