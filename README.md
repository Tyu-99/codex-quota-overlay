# Codex Quota Overlay

A small Ubuntu floating window for ChatGPT/Codex plan quota. It uses the local
`codex app-server` and the existing local login session to show plan windows,
remaining/used percentages, and reset countdowns.

The project does not contain account data, tokens, cookies, or API keys.

## Quick start

Requirements:

- Ubuntu graphical desktop
- ChatGPT/Codex installed and signed in
- `python3-tk` installed (`sudo apt install python3-tk`)

Start the quota overlay manually:

```bash
chmod +x start_quota_overlay.sh
./start_quota_overlay.sh
```

This script starts only the overlay. Start ChatGPT/Codex separately using its
normal application-menu entry.

On startup, if the 7-day window is not ready yet, the overlay waits briefly
and retries automatically up to three times.

## What `install.sh` does

The installer is optional. It adds a `Codex Quota Overlay` entry to the current
user's application menu; it does not install system packages, start ChatGPT or
Codex, or enable login autostart. Run:

```bash
./install.sh
```

Remove that menu entry with:

```bash
./install.sh --uninstall
```

## Settings

Click the gear button in the overlay to configure:

- Refresh interval: 10–3600 seconds
- Opacity: 30%–100%
- Keep overlay on top

Settings are saved to `~/.config/codex-quota-overlay/config.json` and take
effect after clicking Save. Normal refreshes reuse the existing UI and update
only the progress bars, percentages, and countdowns.

## Notes

- The overlay reads plan limits through `account/rateLimits/read`; it does not
  show API billing or token costs.
- The local Codex app-server protocol may change between Codex versions. If it
  changes, the overlay reports a refresh error without exposing login data.
