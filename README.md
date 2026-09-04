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

Start ChatGPT/Codex and the quota overlay together:

```bash
chmod +x start_codex_with_quota.sh
./start_codex_with_quota.sh
```

Use this shell launcher instead of the original ChatGPT/Codex menu entry. It
starts the overlay in the background and then launches the desktop app.

To add a `ChatGPT/Codex with Quota` entry to the current user's application
menu, run:

```bash
./install.sh
```

Remove that menu entry with:

```bash
./install.sh --uninstall
```

This installer does not enable login autostart; the combined shell launcher is
the intended way to start both programs.

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
