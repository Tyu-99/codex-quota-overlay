#!/usr/bin/env python3
"""Small Ubuntu overlay for ChatGPT/Codex plan rate limits."""

from __future__ import annotations

import argparse
import json
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox
from typing import Any


APP_NAME = "Codex Quota Overlay"
VERSION = "0.1.0"
DEFAULT_INTERVAL = 30
MIN_INTERVAL = 10
INITIAL_REFRESH_DELAY_MS = 1_000
INITIAL_RETRY_DELAY_MS = 1_000
MAX_INITIAL_REFRESH_ATTEMPTS = 3
WEEKLY_WINDOW_MINUTES = 7 * 24 * 60
DEFAULT_TOPMOST = True
DEFAULT_OPACITY = 96
MIN_OPACITY = 30
MAX_OPACITY = 100
CONFIG_PATH = Path.home() / ".config" / "codex-quota-overlay" / "config.json"

BG = "#151922"
PANEL = "#202633"
TEXT = "#f3f4f6"
MUTED = "#9aa4b2"
GREEN = "#45d483"
YELLOW = "#f5bd4f"
RED = "#f06b6b"
TRACK = "#353e4c"


@dataclass(frozen=True)
class QuotaRow:
    label: str
    used_percent: float
    window_minutes: int | None
    resets_at: float | None


def as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_window_minutes(value: Any) -> int | None:
    number = as_number(value)
    return int(number) if number is not None and number > 0 else None


def load_settings() -> dict[str, Any]:
    try:
        settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def format_window(minutes: int | None) -> str:
    if not minutes:
        return "window"
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)} days"
    if minutes % 60 == 0:
        return f"{minutes // 60} hours"
    return f"{minutes} minutes"


def format_countdown(resets_at: float | None, now: float | None = None) -> str:
    if resets_at is None:
        return "Reset time unknown"

    seconds = int(resets_at - (time.time() if now is None else now))
    if seconds <= 0:
        return "Resetting soon"

    days, seconds = divmod(seconds, 24 * 60 * 60)
    hours, seconds = divmod(seconds, 60 * 60)
    minutes, _ = divmod(seconds, 60)
    if days:
        return f"Resets in {days}d {hours}h"
    if hours:
        return f"Resets in {hours}h {minutes}m"
    return f"Resets in {max(1, minutes)}m"


def extract_rows(payload: dict[str, Any]) -> list[QuotaRow]:
    buckets = payload.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict):
        single = payload.get("rateLimits")
        buckets = {"codex": single} if isinstance(single, dict) else {}

    rows: list[QuotaRow] = []
    for limit_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue

        bucket_name = bucket.get("limitName") or ("" if limit_id == "codex" else str(limit_id))
        for slot in ("primary", "secondary"):
            window = bucket.get(slot)
            if not isinstance(window, dict):
                continue

            used = as_number(window.get("usedPercent"))
            if used is None:
                continue
            used = max(0.0, min(100.0, used))
            minutes = as_window_minutes(window.get("windowDurationMins"))
            window_name = format_window(minutes)
            label = f"{bucket_name} · {window_name}" if bucket_name else window_name
            rows.append(
                QuotaRow(
                    label=label,
                    used_percent=used,
                    window_minutes=minutes,
                    resets_at=as_number(window.get("resetsAt")),
                )
            )
    return rows


def has_weekly_window(rows: list[QuotaRow]) -> bool:
    return any((row.window_minutes or 0) >= WEEKLY_WINDOW_MINUTES for row in rows)


def plan_name(account: dict[str, Any], limits: dict[str, Any]) -> str:
    account_data = account.get("account")
    if isinstance(account_data, dict) and account_data.get("planType"):
        return str(account_data["planType"]).replace("_", " ").title()

    limit_data = limits.get("rateLimits")
    if isinstance(limit_data, dict) and limit_data.get("planType"):
        return str(limit_data["planType"]).replace("_", " ").title()
    return "Unknown plan"


class AppServerClient:
    """Small JSONL client for the local Codex app-server process."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._pending_lock = threading.Lock()
        self._next_id = 0

    @staticmethod
    def _find_codex() -> str:
        path = shutil.which("codex")
        if path:
            return path
        for candidate in ("/usr/lib/chatgpt/resources/codex", "/usr/local/bin/codex"):
            if shutil.which(candidate):
                return candidate
        raise RuntimeError(
            "codex command not found. Install Codex CLI or the ChatGPT desktop app first"
        )

    def start(self) -> None:
        self.process = subprocess.Popen(
            [self._find_codex(), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()
        self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_quota_overlay",
                    "title": APP_NAME,
                    "version": VERSION,
                }
            },
            timeout=20,
        )
        self.notify("initialized", {})

    def _read_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            message_id = message.get("id")
            if isinstance(message_id, int):
                with self._pending_lock:
                    waiter = self._pending.get(message_id)
                if waiter is not None:
                    waiter.put(message)

    def _send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.poll() is not None or self.process.stdin is None:
            raise RuntimeError("codex app-server has exited")
        with self._write_lock:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def request(self, method: str, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
        with self._pending_lock:
            self._next_id += 1
            request_id = self._next_id
            waiter: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = waiter

        try:
            self._send({"method": method, "id": request_id, "params": params})
            response = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError(f"Timed out waiting for {method} response") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

        if "error" in response:
            error = response["error"]
            message = error.get("message", "Request failed") if isinstance(error, dict) else str(error)
            raise RuntimeError(message)
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def close(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                if self.process.stdin is not None:
                    self.process.stdin.close()
            except OSError:
                pass
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None


class QuotaService:
    def __init__(self, events: queue.Queue[tuple[str, Any]], interval: int) -> None:
        self.events = events
        self.interval = interval
        self.client: AppServerClient | None = None
        self._refreshing = False
        self._lock = threading.Lock()

    def refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh_worker, daemon=True).start()

    def _refresh_worker(self) -> None:
        try:
            if self.client is None:
                self.client = AppServerClient()
                self.client.start()
            account = self.client.request("account/read", {"refreshToken": False})
            limits = self.client.request("account/rateLimits/read", {})
            self.events.put(("data", (plan_name(account, limits), extract_rows(limits))))
        except Exception as exc:  # noqa: BLE001 - the message is shown in the overlay.
            if self.client is not None:
                self.client.close()
                self.client = None
            self.events.put(("error", str(exc)))
        finally:
            with self._lock:
                self._refreshing = False

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None


class Overlay:
    def __init__(
        self,
        interval: int,
        demo: bool = False,
        always_on_top: bool = DEFAULT_TOPMOST,
        opacity: int = DEFAULT_OPACITY,
    ) -> None:
        self.interval = interval
        self.demo = demo
        self.always_on_top = always_on_top
        self.opacity = opacity
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.service = None if demo else QuotaService(self.events, interval)
        self.rows: list[QuotaRow] = []
        self.reset_labels: list[tk.Label] = []
        self.row_widgets: list[tuple[tk.Label, tk.Label, tk.Canvas, int, int, tk.Label]] = []
        self.initial_refresh_attempts = 0
        self.refresh_job: str | None = None
        self.settings_window: tk.Toplevel | None = None
        self.moved = False
        self.drag_offset = (0, 0)

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.overrideredirect(True)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", self.always_on_top)
        try:
            self.root.attributes("-alpha", self.opacity / 100)
        except tk.TclError:
            pass

        self._build()
        self._place(190)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(250, self._drain_events)
        self.root.after(1000, self._update_countdowns)
        self._schedule_refresh()
        if demo:
            self._show_demo()
        else:
            self.root.after(INITIAL_REFRESH_DELAY_MS, self._initial_refresh)

    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=BG, padx=14, pady=12)
        outer.pack(fill="both", expand=True)
        outer.bind("<ButtonPress-1>", self._start_drag)
        outer.bind("<B1-Motion>", self._drag)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        header.bind("<ButtonPress-1>", self._start_drag)
        header.bind("<B1-Motion>", self._drag)

        title = tk.Label(header, text="Codex Usage", bg=BG, fg=TEXT, font=("TkDefaultFont", 11, "bold"))
        title.pack(side="left")
        title.bind("<ButtonPress-1>", self._start_drag)
        title.bind("<B1-Motion>", self._drag)

        self.plan_label = tk.Label(header, text="Connecting…", bg=BG, fg=MUTED, font=("TkDefaultFont", 9))
        self.plan_label.pack(side="left", padx=(8, 0))

        refresh = tk.Label(header, text="↻", bg=BG, fg=MUTED, cursor="hand2", font=("TkDefaultFont", 13))
        refresh.pack(side="right", padx=(8, 0))
        refresh.bind("<Button-1>", lambda _event: self.refresh())

        settings = tk.Label(header, text="⚙", bg=BG, fg=MUTED, cursor="hand2", font=("TkDefaultFont", 12))
        settings.pack(side="right", padx=(8, 0))
        settings.bind("<Button-1>", lambda _event: self.open_settings())

        close = tk.Label(header, text="×", bg=BG, fg=MUTED, cursor="hand2", font=("TkDefaultFont", 14))
        close.pack(side="right")
        close.bind("<Button-1>", lambda _event: self.close())

        self.rows_frame = tk.Frame(outer, bg=BG)
        self.rows_frame.pack(fill="x", pady=(10, 0))
        self.rows_frame.bind("<ButtonPress-1>", self._start_drag)
        self.rows_frame.bind("<B1-Motion>", self._drag)

        self.status_label = tk.Label(outer, text="Reading plan quota…", bg=BG, fg=MUTED, anchor="w", font=("TkDefaultFont", 8))
        self.status_label.pack(fill="x", pady=(10, 0))

    def _place(self, height: int) -> None:
        if self.moved:
            return
        width = 320
        screen_width = self.root.winfo_screenwidth()
        self.root.geometry(f"{width}x{height}+{screen_width - width - 22}+28")

    def _start_drag(self, event: tk.Event[tk.Misc]) -> None:
        self.moved = True
        self.drag_offset = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag(self, event: tk.Event[tk.Misc]) -> None:
        x = event.x_root - self.drag_offset[0]
        y = event.y_root - self.drag_offset[1]
        self.root.geometry(f"+{x}+{y}")

    def refresh(self) -> None:
        if self.demo or self.service is None:
            return
        self.status_label.configure(text="Refreshing…", fg=MUTED)
        self.service.refresh()

    def _initial_refresh(self) -> None:
        self.initial_refresh_attempts += 1
        self.refresh()

    def _check_initial_refresh(self, rows: list[QuotaRow] | None = None) -> None:
        if not self.initial_refresh_attempts:
            return
        if rows is not None and has_weekly_window(rows):
            self.initial_refresh_attempts = 0
            return
        if self.initial_refresh_attempts >= MAX_INITIAL_REFRESH_ATTEMPTS:
            self.initial_refresh_attempts = 0
            return
        self.status_label.configure(text="Waiting for complete quota data…", fg=MUTED)
        self.root.after(INITIAL_RETRY_DELAY_MS, self._initial_refresh)

    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self.settings_window = dialog
        dialog.title("Settings")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        body = tk.Frame(dialog, bg=BG, padx=18, pady=16)
        body.pack(fill="both", expand=True)

        interval_var = tk.StringVar(value=str(self.interval))
        topmost_var = tk.BooleanVar(value=self.always_on_top)
        opacity_var = tk.IntVar(value=self.opacity)

        tk.Label(body, text="Refresh interval (seconds)", bg=BG, fg=TEXT).grid(
            row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 10)
        )
        interval_spinbox = tk.Spinbox(
            body,
            from_=MIN_INTERVAL,
            to=3600,
            textvariable=interval_var,
            width=8,
        )
        interval_spinbox.grid(row=0, column=1, sticky="e", pady=(0, 10))

        tk.Label(body, text="Opacity (%)", bg=BG, fg=TEXT).grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=(0, 10)
        )
        tk.Scale(
            body,
            from_=MIN_OPACITY,
            to=MAX_OPACITY,
            orient="horizontal",
            variable=opacity_var,
            length=130,
            bg=BG,
            fg=TEXT,
            troughcolor=TRACK,
            highlightthickness=0,
        ).grid(row=1, column=1, sticky="e", pady=(0, 10))

        tk.Checkbutton(
            body,
            text="Keep overlay on top",
            variable=topmost_var,
            bg=BG,
            fg=TEXT,
            activebackground=BG,
            activeforeground=TEXT,
            selectcolor=PANEL,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 14))

        buttons = tk.Frame(body, bg=BG)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e")

        def close_dialog() -> None:
            dialog.grab_release()
            dialog.destroy()
            self.settings_window = None

        def save() -> None:
            try:
                interval = int(interval_var.get())
            except ValueError:
                messagebox.showerror("Invalid setting", "Refresh interval must be a whole number.", parent=dialog)
                return
            if interval < MIN_INTERVAL:
                messagebox.showerror(
                    "Invalid setting",
                    f"Refresh interval must be at least {MIN_INTERVAL} seconds.",
                    parent=dialog,
                )
                return

            always_on_top = bool(topmost_var.get())
            opacity = int(opacity_var.get())
            try:
                save_settings(
                    {
                        "interval": interval,
                        "always_on_top": always_on_top,
                        "opacity": opacity,
                    }
                )
            except OSError as exc:
                messagebox.showerror("Unable to save settings", str(exc), parent=dialog)
                return

            self.interval = interval
            self.always_on_top = always_on_top
            self.opacity = opacity
            self.root.attributes("-topmost", self.always_on_top)
            try:
                self.root.attributes("-alpha", self.opacity / 100)
            except tk.TclError:
                pass
            self.status_label.configure(
                text=f"Refreshes every {self.interval} seconds · {time.strftime('%H:%M:%S')}",
                fg=MUTED,
            )
            self._restart_refresh_timer()
            close_dialog()

        tk.Button(buttons, text="Cancel", command=close_dialog, padx=10).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="Save", command=save, padx=10).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.bind("<Return>", lambda _event: save())
        dialog.bind("<Escape>", lambda _event: close_dialog())
        dialog.grab_set()
        interval_spinbox.focus_set()

    def _schedule_refresh(self) -> None:
        self.refresh_job = self.root.after(self.interval * 1000, self._scheduled_refresh)

    def _restart_refresh_timer(self) -> None:
        if self.refresh_job is not None:
            self.root.after_cancel(self.refresh_job)
        self._schedule_refresh()

    def _scheduled_refresh(self) -> None:
        self.refresh()
        self._schedule_refresh()

    def _show_demo(self) -> None:
        now = time.time()
        self._render(
            "Plus",
            [
                QuotaRow("5 hours", 33, 300, now + 2 * 60 * 60),
                QuotaRow("7 days", 10, 10080, now + 5 * 24 * 60 * 60),
            ],
        )

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "data":
                plan, rows = payload
                self._render(plan, rows)
                self._check_initial_refresh(rows)
            elif kind == "error":
                self.status_label.configure(text=f"Read failed: {payload}", fg=RED)
                self._check_initial_refresh()
        self.root.after(250, self._drain_events)

    def _render(self, plan: str, rows: list[QuotaRow]) -> None:
        self.rows = rows
        self.plan_label.configure(text=plan, fg=MUTED)
        self.status_label.configure(text=f"Refreshes every {self.interval} seconds · {time.strftime('%H:%M:%S')}", fg=MUTED)

        if len(self.row_widgets) != len(rows) or not self.rows_frame.winfo_children():
            for child in self.rows_frame.winfo_children():
                child.destroy()
            self.reset_labels = []
            self.row_widgets = []

            for _row in rows:
                card = tk.Frame(self.rows_frame, bg=PANEL, padx=10, pady=7)
                card.pack(fill="x", pady=(0, 6))

                top = tk.Frame(card, bg=PANEL)
                top.pack(fill="x")
                title = tk.Label(top, bg=PANEL, fg=TEXT, anchor="w", font=("TkDefaultFont", 9, "bold"))
                title.pack(side="left")
                remaining = tk.Label(top, bg=PANEL, anchor="e", font=("TkDefaultFont", 9))
                remaining.pack(side="right")

                bar = tk.Canvas(card, height=7, bg=PANEL, highlightthickness=0, bd=0)
                bar.pack(fill="x", pady=(6, 4))
                bar.update_idletasks()
                width = max(1, bar.winfo_width())
                track_id = bar.create_rectangle(0, 0, width, 7, fill=TRACK, outline="")
                used_id = bar.create_rectangle(0, 0, 0, 7, outline="")

                reset = tk.Label(card, bg=PANEL, fg=MUTED, anchor="w", font=("TkDefaultFont", 8))
                reset.pack(fill="x")
                self.reset_labels.append(reset)
                self.row_widgets.append((title, remaining, bar, track_id, used_id, reset))

            if not rows:
                tk.Label(self.rows_frame, text="No quota windows available", bg=BG, fg=MUTED).pack(anchor="w")

            self.root.update_idletasks()
            self._place(max(170, 112 + len(rows) * 67))
            self.root.after_idle(self._sync_bar_geometry)

        for row, (title, remaining_label, bar, track_id, used_id, _reset) in zip(rows, self.row_widgets):
            remaining = 100.0 - row.used_percent
            color = GREEN if remaining >= 40 else YELLOW if remaining >= 15 else RED
            title.configure(text=row.label)
            remaining_label.configure(text=f"Remaining {remaining:.0f}%", fg=color)
            width = max(1, bar.winfo_width())
            bar.coords(track_id, 0, 0, width, 7)
            bar.coords(used_id, 0, 0, width * row.used_percent / 100, 7)
            bar.itemconfigure(used_id, fill=color)

    def _sync_bar_geometry(self) -> None:
        for row, (_title, _remaining_label, bar, track_id, used_id, _reset) in zip(self.rows, self.row_widgets):
            width = max(1, bar.winfo_width())
            bar.coords(track_id, 0, 0, width, 7)
            bar.coords(used_id, 0, 0, width * row.used_percent / 100, 7)

    def _update_countdowns(self) -> None:
        for label, row in zip(self.reset_labels, self.rows):
            label.configure(text=f"{format_countdown(row.resets_at)} · Used {row.used_percent:.0f}%")
        self.root.after(1000, self._update_countdowns)

    def close(self) -> None:
        if self.service is not None:
            self.service.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def self_check() -> None:
    assert format_window(300) == "5 hours"
    assert format_window(10080) == "7 days"
    assert format_countdown(1_000, now=0) == "Resets in 16m"
    rows = extract_rows(
        {
            "rateLimitsByLimitId": {
                "codex": {
                    "primary": {"usedPercent": 25, "windowDurationMins": 300, "resetsAt": 1_000},
                    "secondary": {"usedPercent": 42, "windowDurationMins": 10080, "resetsAt": 2_000},
                }
            }
        }
    )
    assert [row.label for row in rows] == ["5 hours", "7 days"]
    assert rows[0].used_percent == 25
    assert has_weekly_window(rows)
    print("self-check: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--interval", type=int, default=None, help="Override the saved refresh interval")
    parser.add_argument("--demo", action="store_true", help="Open the window with simulated data")
    parser.add_argument("--self-check", action="store_true", help="Run the offline self-check")
    args = parser.parse_args()

    if args.self_check:
        self_check()
        return 0

    settings = load_settings()
    if args.interval is None:
        try:
            interval = int(settings.get("interval", DEFAULT_INTERVAL))
        except (TypeError, ValueError):
            interval = DEFAULT_INTERVAL
        if interval < MIN_INTERVAL:
            interval = DEFAULT_INTERVAL
    else:
        interval = args.interval
    if interval < MIN_INTERVAL:
        parser.error(f"--interval must be at least {MIN_INTERVAL} seconds")

    always_on_top = settings.get("always_on_top", DEFAULT_TOPMOST)
    if not isinstance(always_on_top, bool):
        always_on_top = DEFAULT_TOPMOST

    try:
        opacity = int(settings.get("opacity", DEFAULT_OPACITY))
    except (TypeError, ValueError):
        opacity = DEFAULT_OPACITY
    if not MIN_OPACITY <= opacity <= MAX_OPACITY:
        opacity = DEFAULT_OPACITY

    try:
        Overlay(
            interval,
            demo=args.demo,
            always_on_top=always_on_top,
            opacity=opacity,
        ).run()
    except tk.TclError as exc:
        print(f"Unable to open desktop window: {exc}", file=sys.stderr)
        print("Run this script in a graphical Ubuntu session.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
