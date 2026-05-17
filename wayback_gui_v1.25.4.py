#!/usr/bin/env python3
"""
Wayback Machine Archiver GUI
- Per-URL tracking of page, outlinks, screenshot
- All SPN2 options
- Outage detection with social media popup
- Rate limit countdown
- Granular progress checkpointing
Requires: pip install requests
"""

# ── Version ────────────────────────────────────────────────────────────────────
VERSION = "1.25.4"

# URL to check for updates — set this to a GitHub raw URL or leave blank
# to only allow local file updates.
# Example: "https://raw.githubusercontent.com/yourname/wayback/main/wayback_gui.py"
UPDATE_URL = "https://github.com/FuriosEthan/WAYBACK-ARCHIVER-AI-MADE-/releases"

GITHUB_REPO   = "FuriosEthan/WAYBACK-ARCHIVER-AI-MADE-"
GITHUB_API    = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases"

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import json
import os
import time
import webbrowser
import wave
import struct
import math
import io
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, urlunparse
from html.parser import HTMLParser
import sys

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ── Constants ─────────────────────────────────────────────────────────────────

USER_AGENT    = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
SPN2_URL      = "https://web.archive.org/save"
STATE_FILE    = "wayback_state.json"
LOG_FILE      = "wayback_archiver.log"
SETTINGS_FILE = "wayback_gui_settings.json"

# ── Per-URL status log files ──────────────────────────────────────────────────
ARCHIVED_LOG = "urls_archived.log"
PENDING_LOG  = "urls_pending.log"
ERROR_LOG    = "urls_error.log"

# Consecutive server errors before declaring an outage
OUTAGE_THRESHOLD = 3

IA_SOCIALS = [
    ("X / Twitter",  "https://x.com/internetarchive",                          "#1da1f2"),
    ("Bluesky",      "https://bsky.app/profile/archive.org",                   "#0085ff"),
    ("Mastodon",     "https://mastodon.archive.org/@internetarchive",           "#6364ff"),
    ("Facebook",     "https://www.facebook.com/internetarchive",               "#1877f2"),
    ("Blog",         "https://blog.archive.org",                                "#e85d2f"),
]

BG        = "#0f0f0f"
BG2       = "#1a1a1a"
BG3       = "#242424"
BG4       = "#2a2a2a"
BORDER    = "#2e2e2e"
ACCENT    = "#e85d2f"
ACCENT2   = "#ff7a50"
TEXT      = "#e8e8e8"
TEXT_DIM  = "#666666"
SUCCESS   = "#4caf7d"
ERROR     = "#e85d5d"
WARNING   = "#e8a83d"
SKIP      = "#5588cc"
FONT_MONO = ("Consolas", 9)
FONT_UI   = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI Semibold", 10)
FONT_SM   = ("Segoe UI", 9)

# ── State helpers ─────────────────────────────────────────────────────────────

def load_state():
    p = Path(STATE_FILE)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            if "saved" in data and "urls" not in data:
                urls = {}
                for u in data.get("saved", []):
                    urls[u] = {"page": True, "outlinks": False, "screenshot": False, "archive_url": ""}
                return {"urls": urls, "checkpoint": None}
            if "checkpoint" not in data:
                data["checkpoint"] = None
            return data
        except Exception:
            pass
    return {"urls": {}, "checkpoint": None}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def write_url_logs(state, all_urls, want_outlinks=False, want_screenshot=False):
    """
    Rebuild all three URL log files from current state.
    Called after every URL result so logs stay perfectly in sync.

    archived_urls.log  — successfully archived
    pending_urls.log   — not yet done
    urls_error.log     — failed/errored
    """
    from datetime import datetime as _dt

    archived_lines = []
    pending_lines  = []
    error_lines    = []

    now = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    header = f"# Updated: {now}\n{'─' * 72}\n"

    for url in all_urls:
        entry = state["urls"].get(url, {})
        pg    = entry.get("page",        False)
        ol    = entry.get("outlinks",    False)
        ss    = entry.get("screenshot",  False)
        arc   = entry.get("archive_url", "")
        saved = entry.get("last_saved",  "")
        err   = entry.get("error_msg",   "")
        fail  = entry.get("failed",      False)

        needs_ol = want_outlinks   and not ol
        needs_ss = want_screenshot and not ss

        if fail or err:
            # Error log — include URL, error message, and when it failed
            error_lines.append(
                f"URL:       {url}\n"
                f"Error:     {err or 'Unknown error / all retries exhausted'}\n"
                f"Attempted: {entry.get('last_attempt', 'unknown')}\n"
                + "─" * 72
            )

        elif pg and not needs_ol and not needs_ss:
            # Archived log — include archive URL, captured timestamp, what was captured
            captured = []
            if pg:  captured.append("page")
            if ol:  captured.append("outlinks")
            if ss:  captured.append("screenshot")
            archived_lines.append(
                f"URL:      {url}\n"
                f"Archive:  {arc or '(no archive URL recorded)'}\n"
                f"Saved:    {saved or 'unknown'}\n"
                f"Captured: {', '.join(captured)}\n"
                + "─" * 72
            )

        else:
            # Pending log — include what still needs to be done
            todo = []
            if not pg:      todo.append("page")
            if needs_ol:    todo.append("outlinks")
            if needs_ss:    todo.append("screenshot")
            partial = "(partial — page saved)" if pg else ""
            pending_lines.append(
                f"URL:    {url}\n"
                f"Needs:  {', '.join(todo)}  {partial}\n"
                + "─" * 72
            )

    def _write(path, title, lines, empty_msg):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n")
            f.write(header)
            if lines:
                f.write("\n".join(lines) + "\n")
            else:
                f.write(f"# {empty_msg}\n")

    _write(ARCHIVED_LOG, "ARCHIVED URLS",
           archived_lines, "No URLs archived yet.")
    _write(PENDING_LOG,  "PENDING URLS",
           pending_lines,  "No URLs pending — all done!")
    _write(ERROR_LOG,    "FAILED / ERROR URLS",
           error_lines,    "No errors.")



def url_entry(state, url):
    if url not in state["urls"]:
        state["urls"][url] = {
            "page": False, "outlinks": False, "screenshot": False,
            "archive_url": "", "last_saved": None,
            "error_msg": "", "failed": False, "last_attempt": None,
        }
    return state["urls"][url]

def write_checkpoint(state, url, step, job_id=None):
    """Save exactly where we are mid-job so we can report it on restart."""
    state["checkpoint"] = {
        "url":     url,
        "step":    step,
        "job_id":  job_id,
        "started": datetime.now().isoformat(),
    }
    save_state(state)

def clear_checkpoint(state):
    state["checkpoint"] = None
    save_state(state)

# ── IA health check ───────────────────────────────────────────────────────────

def check_ia_health(session):
    """
    Returns (status: str, detail: str)
    status: "up" | "ia_down" | "no_internet"
    
    First tests a neutral site (Google DNS) to check if internet works at all.
    If internet is fine but IA is unreachable, it's an IA outage.
    If even the neutral site fails, the user's internet is down.
    """
    # Step 1 — check if internet is up at all using a neutral fast endpoint
    neutral_targets = [
        "https://8.8.8.8",           # Google DNS — doesn't care what host header we send
        "https://1.1.1.1",           # Cloudflare DNS
        "https://www.google.com",
    ]
    internet_up = False
    for url in neutral_targets:
        try:
            r = session.head(url, timeout=6, allow_redirects=True)
            internet_up = True
            break
        except Exception:
            continue

    if not internet_up:
        return "no_internet", "Could not reach any external server (Google DNS, Cloudflare DNS, Google.com)"

    # Step 2 — internet is up, now check IA specifically
    ia_targets = [
        "https://archive.org",
        "https://web.archive.org",
    ]
    for url in ia_targets:
        try:
            r = session.head(url, timeout=10, allow_redirects=True)
            if r.status_code < 500:
                return "up", f"Reachable (HTTP {r.status_code})"
        except Exception:
            pass
    return "ia_down", "Could not reach archive.org or web.archive.org (but your internet is working)"

def is_server_error(status_code):
    return status_code in (500, 502, 503, 504, 520, 521, 522, 523, 524, 525)

def is_rate_limit(status_code):
    return status_code == 429

# ── Archive logic ─────────────────────────────────────────────────────────────

def poll_job(job_id, session, timeout, log_fn, checkpoint_fn=None):
    """
    Poll the SPN2 status endpoint until the job completes or times out.
    Returns ("success", archive_url, None) or (error_type, "", message).
    """
    status_url = f"https://web.archive.org/save/status/{job_id}"
    deadline   = time.time() + timeout
    interval   = 5
    last_status = ""

    log_fn(f"    Job ID: {job_id}  |  polling every {interval}s (max {timeout}s)…", "dim")

    while time.time() < deadline:
        try:
            r = session.get(status_url, timeout=30)

            if r.status_code == 200:
                data    = r.json()
                status  = data.get("status", "")

                # Log status changes so the user can see progress
                if status != last_status:
                    log_fn(f"    Status: {status}", "dim")
                    last_status = status

                if status == "success":
                    ts        = data.get("timestamp", "")
                    saved_url = data.get("original_url", "") or data.get("url", "")
                    outlinks  = data.get("outlinks", [])

                    if outlinks:
                        log_fn(f"    Outlinks captured: {len(outlinks)}", "dim")

                    # Validate we have both parts before building the URL
                    if not ts or not saved_url:
                        log_fn(f"    Warning: incomplete response (ts={ts!r}, url={saved_url!r})", "warning")
                        # Fall back to just the job status URL so at least something is recorded
                        return "success", f"https://web.archive.org/save/status/{job_id}", None

                    archive_url = f"https://web.archive.org/web/{ts}/{saved_url}"
                    log_fn(f"    Archive URL: {archive_url}", "dim")
                    return "success", archive_url, None

                elif status == "error":
                    msg = data.get("message", "unknown error")
                    log_fn(f"    Job failed on IA side: {msg}", "warning")
                    return "error", "", msg

                else:
                    # Still pending — log resource count as progress indicator
                    resources = data.get("resources", [])
                    if resources:
                        log_fn(f"    Capturing… ({len(resources)} resources so far)", "dim")

            elif is_server_error(r.status_code):
                log_fn(f"    Server error while polling: HTTP {r.status_code}", "warning")
                return "server_error", "", f"HTTP {r.status_code} while polling job"

            else:
                log_fn(f"    Unexpected HTTP {r.status_code} while polling", "warning")

        except requests.exceptions.ConnectionError as e:
            log_fn(f"    Connection lost while polling: {e}", "warning")
            return "server_error", "", f"Connection lost: {e}"
        except requests.exceptions.Timeout:
            log_fn(f"    Timeout while polling — will retry", "dim")
        except Exception as e:
            log_fn(f"    Polling error: {e}", "warning")

        time.sleep(interval)

    elapsed = int(timeout)
    log_fn(f"    Job timed out after {elapsed}s — IA may still be processing", "warning")
    return "timeout", "", f"Job timed out after {elapsed}s"

def do_save(url, session, options, log_fn, state, checkpoint_fn):
    """
    Submit one save job.
    Returns (result_type, archive_url, error_msg, retry_after_seconds)
    result_type: "success" | "error" | "server_error" | "rate_limit" | "failed"
    """
    retries      = options.get("retries", 4)
    backoff_base = options.get("backoff", 30)
    rl_base      = options.get("rate_limit_backoff", 60)  # rate limit base (doubles each time)
    BACKOFF_MAX  = 300

    def _backoff(attempt):
        """30s → 60s → 90s … capped at 300s."""
        return min(backoff_base * attempt, BACKOFF_MAX)

    def _rl_backoff(rl_count):
        """60s → 120s → 240s → 300s (doubles, capped at 300s)."""
        return min(rl_base * (2 ** (rl_count - 1)), BACKOFF_MAX)

    payload = {"url": url}
    if options.get("capture_all"):            payload["capture_all"]            = 1
    if options.get("capture_outlinks"):       payload["capture_outlinks"]       = 1
    if options.get("capture_screenshot"):     payload["capture_screenshot"]     = 1
    if options.get("delay_wb_availability"):  payload["delay_wb_availability"]  = 1
    if options.get("force_get"):              payload["force_get"]              = 1
    if options.get("skip_first_archive"):     payload["skip_first_archive"]     = 1
    if options.get("email_result"):           payload["email_result"]           = 1
    if_not = options.get("if_not_archived_within", 0)
    if if_not > 0:                            payload["if_not_archived_within"] = if_not
    js_t = options.get("js_behavior_timeout", 0)
    if js_t > 0:                              payload["js_behavior_timeout"]    = js_t
    cookie = options.get("capture_cookie", "").strip()
    if cookie:                                payload["capture_cookie"]         = cookie
    ua = options.get("user_agent", "").strip()
    if ua:                                    payload["user_agent"]             = ua

    rl_count = 0   # how many rate-limit hits so far for this URL

    for attempt in range(1, retries + 1):
        wait = _backoff(attempt)
        write_checkpoint(state, url, f"submitting (attempt {attempt})")
        if attempt > 1:
            log_fn(f"    Retry {attempt}/{retries}  (waiting {wait}s)…", "dim")
        try:
            log_fn(f"    Submitting to Wayback Machine…", "dim")
            r = session.post(SPN2_URL, data=payload, timeout=60)

            if is_rate_limit(r.status_code):
                rl_count += 1
                rl_wait = _rl_backoff(rl_count)
                # Use Retry-After header if provided, otherwise use doubling schedule
                server_wait = r.headers.get("Retry-After")
                retry_after = int(server_wait) if server_wait else rl_wait
                return "rate_limit", "", "Rate limited", retry_after

            if is_server_error(r.status_code):
                log_fn(f"    Server error HTTP {r.status_code} (attempt {attempt}/{retries}) — waiting {wait}s", "warning")
                time.sleep(wait)
                if attempt == retries:
                    return "server_error", "", f"HTTP {r.status_code}", 0
                continue

            if r.status_code == 200:
                # Try to parse as JSON — IA sometimes returns HTML on 200 (login/CAPTCHA)
                try:
                    data = r.json()
                except Exception:
                    # Got HTML or non-JSON on a 200 — log a snippet and retry
                    snippet = r.text[:200].replace("\n", " ").strip()
                    log_fn(f"    HTTP 200 but not JSON (attempt {attempt}/{retries}) — retrying in {wait}s", "warning")
                    log_fn(f"    Response preview: {snippet}", "dim")
                    time.sleep(wait)
                    continue

                job_id = data.get("job_id")
                if job_id:
                    log_fn(f"    Accepted — Job ID: {job_id}", "dim")
                    write_checkpoint(state, url, "polling_job", job_id)
                    poll_timeout = 240 if options.get("capture_outlinks") else 180
                    result, archive_url, err = poll_job(
                        job_id, session, poll_timeout, log_fn
                    )
                    if result == "server_error":
                        if attempt == retries:
                            return "server_error", "", err, 0
                        log_fn(f"    {err} — retrying in {wait}s…", "warning")
                        time.sleep(wait)
                        continue
                    return result, archive_url, err or "", 0

                elif "url" in data:
                    return "success", f"https://web.archive.org/web/{data.get('timestamp','')}/{data['url']}", "", 0

                elif "status" in data:
                    # IA returned a status/status_ext/message error response
                    # These are not transient — IA is explicitly rejecting the URL
                    status     = data.get("status", "")
                    status_ext = data.get("status_ext", "")
                    message    = data.get("message", "")

                    # Map known status_ext codes to human-readable explanations
                    ext_reasons = {
                        "error:blocked-url":          "URL is blocked from archiving by IA policy",
                        "error:blocked-client-ip":    "Your IP is blocked by IA",
                        "error:no-access":            "IA cannot access this URL (may require login)",
                        "error:too-many-requests":    "Too many requests — rate limited",
                        "error:browsing-timeout":     "Page took too long to load in IA's browser",
                        "error:soft-404":             "Page returned a soft 404 (appears missing)",
                        "error:user-session-limit":   "Account session limit reached — try again later",
                        "error:page-empty":           "Page returned empty content",
                        "error:robots-blocked":       "Blocked by the site's robots.txt on IA's end",
                        "error:ftp-access-denied":    "FTP URL access denied",
                        "error:not-implemented":      "URL type not supported by IA",
                    }
                    reason = ext_reasons.get(status_ext, status_ext or status or "Unknown IA error")
                    full_msg = f"IA rejected: {reason}"
                    if message:
                        full_msg += f" — {message}"

                    # Decide whether to retry based on error type
                    retryable_ext = {
                        "error:too-many-requests",
                        "error:browsing-timeout",
                        "error:user-session-limit",
                    }
                    if status_ext in retryable_ext:
                        if attempt < retries:
                            log_fn(f"    {full_msg} — retrying in {wait}s", "warning")
                            time.sleep(wait)
                            continue
                        return "failed", "", full_msg, 0
                    else:
                        # Non-retryable — don't waste retries on it
                        log_fn(f"    {full_msg}", "error")
                        if status_ext == "error:blocked-url":
                            log_fn(f"    This URL is permanently blocked from archiving on IA.", "dim")
                        elif status_ext == "error:no-access":
                            log_fn(f"    IA cannot reach this URL — it may require a login or be geo-restricted.", "dim")
                        return "failed", "", full_msg, 0

                else:
                    # JSON but completely unrecognised structure — log and retry
                    log_fn(f"    Unexpected JSON response (attempt {attempt}/{retries}) — retrying in {wait}s", "warning")
                    log_fn(f"    Keys received: {list(data.keys())}", "dim")
                    time.sleep(wait)
                    continue

            log_fn(f"    Unexpected HTTP {r.status_code} (attempt {attempt}/{retries}) — waiting {wait}s", "warning")
            time.sleep(wait)

        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as e:
            log_fn(f"    Connection error (attempt {attempt}/{retries}) — waiting {wait}s: {e}", "warning")
            time.sleep(wait)
            if attempt == retries:
                return "server_error", "", str(e), 0
        except Exception as e:
            log_fn(f"    Error (attempt {attempt}/{retries}) — waiting {wait}s: {e}", "warning")
            time.sleep(wait)

    return "failed", "", "All retries exhausted", 0

# ── Outage popup ──────────────────────────────────────────────────────────────

class OutagePopup(tk.Toplevel):
    def __init__(self, parent, detail, checkpoint, on_stop, on_retry):
        super().__init__(parent)
        self.on_stop  = on_stop
        self.on_retry = on_retry

        self.title("Internet Archive Outage Detected")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        # Center on parent
        self.update_idletasks()
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        self.geometry(f"520x520+{px - 260}+{py - 260}")

        self._build(detail, checkpoint)

    def _build(self, detail, checkpoint):
        # Warning header
        hdr = tk.Frame(self, bg="#2a0a0a", pady=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⚠  INTERNET ARCHIVE OUTAGE DETECTED",
                 bg="#2a0a0a", fg=ERROR,
                 font=("Segoe UI Semibold", 12)).pack()

        # Detail
        body = tk.Frame(self, bg=BG, padx=22)
        body.pack(fill="both", expand=True, pady=10)

        tk.Label(body, text="The archiver stopped because Internet Archive appears to be unreachable.",
                 bg=BG, fg=TEXT, font=FONT_SM, wraplength=460, justify="left").pack(anchor="w", pady=(6, 2))
        tk.Label(body, text=f"Error detail:  {detail}",
                 bg=BG, fg=TEXT_DIM, font=FONT_MONO, wraplength=460, justify="left").pack(anchor="w", pady=(0, 10))

        # Checkpoint
        if checkpoint:
            cp_frame = tk.Frame(body, bg=BG2, padx=12, pady=10)
            cp_frame.pack(fill="x", pady=(0, 10))
            tk.Label(cp_frame, text="Progress saved — will resume from:",
                     bg=BG2, fg=WARNING, font=FONT_BOLD).pack(anchor="w")
            tk.Label(cp_frame, text=f"URL:   {checkpoint.get('url', 'N/A')}",
                     bg=BG2, fg=TEXT, font=FONT_MONO, wraplength=440, justify="left").pack(anchor="w")
            tk.Label(cp_frame, text=f"Step:  {checkpoint.get('step', 'N/A')}",
                     bg=BG2, fg=TEXT, font=FONT_MONO).pack(anchor="w")
            started = checkpoint.get("started", "")
            if started:
                tk.Label(cp_frame, text=f"Started: {started[:19].replace('T', ' ')}",
                         bg=BG2, fg=TEXT_DIM, font=FONT_MONO).pack(anchor="w")

        # Status check
        status_frame = tk.Frame(body, bg=BG2, padx=12, pady=10)
        status_frame.pack(fill="x", pady=(0, 10))
        tk.Label(status_frame, text="Check for updates and return date on their socials:",
                 bg=BG2, fg=TEXT, font=FONT_BOLD).pack(anchor="w", pady=(0, 8))

        for name, url, color in IA_SOCIALS:
            btn_row = tk.Frame(status_frame, bg=BG2)
            btn_row.pack(fill="x", pady=2)
            indicator = tk.Frame(btn_row, bg=color, width=4)
            indicator.pack(side="left", fill="y", padx=(0, 8))
            tk.Button(btn_row, text=f"  {name}  →  {url}",
                      bg=BG3, fg=TEXT, relief="flat", font=FONT_SM,
                      cursor="hand2", anchor="w",
                      activebackground=BG4, activeforeground=TEXT,
                      command=lambda u=url: webbrowser.open(u)
                      ).pack(fill="x")

        # Buttons
        btn_frame = tk.Frame(self, bg=BG, padx=22, pady=14)
        btn_frame.pack(fill="x")

        tk.Button(btn_frame, text="Stop archiving",
                  bg=BG3, fg=ERROR, relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground="#2e2020",
                  padx=18, pady=9,
                  command=self._do_stop).pack(side="left")

        tk.Button(btn_frame, text="Retry now",
                  bg=ACCENT, fg="#fff", relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground=ACCENT2,
                  padx=18, pady=9,
                  command=self._do_retry).pack(side="right")

        tk.Label(btn_frame,
                 text="(Progress is saved — safe to close and restart later)",
                 bg=BG, fg=TEXT_DIM, font=("Segoe UI", 8)).pack(side="right", padx=12)

    def _do_stop(self):
        self.destroy()
        self.on_stop()

    def _do_retry(self):
        self.destroy()
        self.on_retry()

# ── Rate limit popup ──────────────────────────────────────────────────────────

class NoInternetPopup(tk.Toplevel):
    """
    Shown when the user's own internet connection drops.
    Different from OutagePopup — no IA social links, just a simple
    'wait and retry' dialog with a countdown option.
    """
    def __init__(self, parent, detail, checkpoint, on_stop, on_retry):
        super().__init__(parent)
        self.on_stop  = on_stop
        self.on_retry = on_retry
        self._countdown_job = None

        self.title("Internet Connection Lost")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        self.update_idletasks()
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        self.geometry(f"460x360+{px - 230}+{py - 180}")

        self._build(detail, checkpoint)

    def _build(self, detail, checkpoint):
        # Header — yellow/warning tone, not red like outage
        hdr = tk.Frame(self, bg="#2a2000", pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📶  YOUR INTERNET CONNECTION DROPPED",
                 bg="#2a2000", fg=WARNING,
                 font=("Segoe UI Semibold", 11)).pack()

        body = tk.Frame(self, bg=BG, padx=22)
        body.pack(fill="both", expand=True, pady=10)

        tk.Label(body,
                 text="The archiver lost connection to the internet.\n"
                      "This is not an Internet Archive outage — it's a local connection issue.",
                 bg=BG, fg=TEXT, font=FONT_SM,
                 wraplength=400, justify="left").pack(anchor="w", pady=(6, 8))

        tk.Label(body, text=f"Error:  {detail}",
                 bg=BG, fg=TEXT_DIM, font=FONT_MONO,
                 wraplength=400, justify="left").pack(anchor="w", pady=(0, 10))

        # Checkpoint info
        if checkpoint:
            cp_frame = tk.Frame(body, bg=BG2, padx=12, pady=10)
            cp_frame.pack(fill="x", pady=(0, 10))
            tk.Label(cp_frame, text="Progress saved — will resume from:",
                     bg=BG2, fg=SUCCESS, font=FONT_BOLD).pack(anchor="w")
            tk.Label(cp_frame, text=f"URL:   {checkpoint.get('url', 'N/A')}",
                     bg=BG2, fg=TEXT, font=FONT_MONO,
                     wraplength=400, justify="left").pack(anchor="w")
            tk.Label(cp_frame, text=f"Step:  {checkpoint.get('step', 'N/A')}",
                     bg=BG2, fg=TEXT, font=FONT_MONO).pack(anchor="w")

        tk.Label(body,
                 text="Check your router/WiFi, then click Retry when reconnected.",
                 bg=BG, fg=TEXT_DIM, font=FONT_SM,
                 wraplength=400, justify="left").pack(anchor="w")

        # Auto-retry countdown
        countdown_row = tk.Frame(body, bg=BG)
        countdown_row.pack(anchor="w", pady=(8, 0))
        tk.Label(countdown_row, text="Auto-retry in:", bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left")
        self._countdown_var = tk.StringVar(value="30s")
        tk.Label(countdown_row, textvariable=self._countdown_var,
                 bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 10)).pack(side="left", padx=(6, 0))
        self._remaining = 30
        self._tick()

        # Buttons
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        btn_row = tk.Frame(self, bg=BG, padx=22, pady=12)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="Stop archiving",
                  bg=BG3, fg=ERROR, relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground="#2e2020",
                  padx=16, pady=8,
                  command=self._do_stop).pack(side="left")

        tk.Button(btn_row, text="Retry now",
                  bg=ACCENT, fg="#fff", relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground=ACCENT2,
                  padx=16, pady=8,
                  command=self._do_retry).pack(side="right")

        tk.Label(btn_row, text="(Progress is safe — no data lost)",
                 bg=BG, fg=TEXT_DIM, font=("Segoe UI", 8)).pack(side="right", padx=10)

    def _tick(self):
        if self._remaining <= 0:
            self._do_retry()
            return
        self._countdown_var.set(f"{self._remaining}s")
        self._remaining -= 1
        self._countdown_job = self.after(1000, self._tick)

    def _cancel_countdown(self):
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None

    def _do_stop(self):
        self._cancel_countdown()
        self.destroy()
        self.on_stop()

    def _do_retry(self):
        self._cancel_countdown()
        self.destroy()
        self.on_retry()


class RateLimitPopup(tk.Toplevel):
    """
    Popup shown when IA rate-limits the archiver.
    Shows a countdown, explains the situation, and offers helpful options.
    Doubling schedule: 60s → 120s → 240s → 300s (capped).
    """
    def __init__(self, parent, wait_secs, rl_count, on_done, on_stop, on_slow_down):
        super().__init__(parent)
        self.on_done       = on_done
        self.on_stop       = on_stop
        self.on_slow_down  = on_slow_down
        self._remaining    = wait_secs
        self._job          = None

        self.title("Rate Limited by Internet Archive")
        self.configure(bg=BG)
        self.resizable(False, False)

        self.update_idletasks()
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        self.geometry(f"480x380+{px - 240}+{py - 190}")

        self._build(wait_secs, rl_count)

    def _build(self, wait_secs, rl_count):
        hdr = tk.Frame(self, bg="#2a2000", pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="⏳  RATE LIMITED BY INTERNET ARCHIVE",
                 bg="#2a2000", fg=WARNING,
                 font=("Segoe UI Semibold", 11)).pack()

        body = tk.Frame(self, bg=BG, padx=20, pady=12)
        body.pack(fill="both", expand=True)

        # Explanation
        hit_text = f"Rate limit hit #{rl_count}." if rl_count > 1 else "Rate limit hit."
        tk.Label(body,
                 text=f"{hit_text} Internet Archive is asking the archiver to slow down.\n"
                      "This is normal for bulk archiving — IA limits how fast you can submit.",
                 bg=BG, fg=TEXT, font=FONT_SM,
                 wraplength=430, justify="left").pack(anchor="w", pady=(4, 8))

        # Countdown
        cd_row = tk.Frame(body, bg=BG2, padx=14, pady=10)
        cd_row.pack(fill="x", pady=(0, 8))
        tk.Label(cd_row, text="Auto-resuming in:", bg=BG2, fg=TEXT_DIM,
                 font=FONT_SM).pack(side="left")
        self._cd_var = tk.StringVar(value=f"{wait_secs}s")
        tk.Label(cd_row, textvariable=self._cd_var, bg=BG2, fg=ACCENT,
                 font=("Segoe UI Semibold", 14)).pack(side="left", padx=(8, 0))
        if rl_count > 1:
            tk.Label(cd_row, text=f"  (doubled from last time)",
                     bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(side="left")

        # Options
        tk.Label(body, text="What you can do:",
                 bg=BG, fg=TEXT, font=FONT_BOLD).pack(anchor="w", pady=(4, 4))

        opts = [
            ("Wait and auto-resume",
             "The archiver will automatically continue once the timer expires.\n"
             "No action needed — this is the recommended option."),
            ("Increase delay between requests",
             "Click 'Slow down' below to increase your delay setting by 5s.\n"
             "Fewer requests per minute = fewer rate limit hits."),
            ("Reduce max pages (crawl mode)",
             "If crawling a large site, lowering max pages reduces total request volume."),
            ("Stop and retry later",
             "Progress is fully saved. You can safely stop now and resume next session."),
        ]
        for title, desc in opts:
            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=(0, 3))
            tk.Label(row, text=f"• {title}", bg=BG, fg=TEXT, font=FONT_BOLD,
                     anchor="w").pack(anchor="w")
            tk.Label(row, text=f"  {desc}", bg=BG, fg=TEXT_DIM, font=FONT_SM,
                     wraplength=430, justify="left", anchor="w").pack(anchor="w")

        # Buttons
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        btn_row = tk.Frame(self, bg=BG, padx=18, pady=10)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="Stop archiving",
                  bg=BG3, fg=ERROR, relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground="#2e2020",
                  padx=12, pady=7, command=self._do_stop).pack(side="left")

        tk.Button(btn_row, text="Slow down (+5s delay)",
                  bg=BG3, fg=WARNING, relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground=BG4,
                  padx=12, pady=7, command=self._do_slow).pack(side="left", padx=(6, 0))

        tk.Button(btn_row, text="Resume now",
                  bg=ACCENT, fg="#fff", relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground=ACCENT2,
                  padx=12, pady=7, command=self._do_done).pack(side="right")

        self._tick()

    def _tick(self):
        if self._remaining <= 0:
            self._do_done()
            return
        self._cd_var.set(f"{self._remaining}s")
        self._remaining -= 1
        self._job = self.after(1000, self._tick)

    def _cancel(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def _do_done(self):
        self._cancel(); self.destroy(); self.on_done()

    def _do_stop(self):
        self._cancel(); self.destroy(); self.on_stop()

    def _do_slow(self):
        self._cancel(); self.destroy(); self.on_slow_down(); self.on_done()


class RateLimitBanner:
    """Fallback in-log countdown (used if popup is already open)."""
    def __init__(self, root, log_fn, status_fn, seconds, on_done):
        self.root = root; self.log_fn = log_fn; self.status_fn = status_fn
        self.remaining = seconds; self.on_done = on_done
        self._tick()

    def _tick(self):
        if self.remaining <= 0:
            self.log_fn("Rate limit wait over — resuming.", "success")
            self.status_fn("Resuming..."); self.on_done(); return
        self.log_fn(f"  Rate limited — retry in {self.remaining}s", "warning")
        self.status_fn(f"Rate limited — retry in {self.remaining}s")
        self.remaining -= 5
        self.root.after(5000, self._tick)

# ── Domain helpers ────────────────────────────────────────────────────────────

def extract_registered_domain(netloc):
    """
    Strip port and leading 'www.' then return the host.
    e.g. 'www.bitbuilt.net:8080' -> 'bitbuilt.net'
    """
    host = netloc.split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    return host

def same_domain(base_netloc, url):
    """Return True if url belongs to the same registered domain as base_netloc."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return extract_registered_domain(parsed.netloc) == extract_registered_domain(base_netloc)

def normalise_url(url):
    """Remove fragment (#section) and trailing slash for deduplication."""
    p = urlparse(url)
    # Drop fragment, keep everything else
    clean = urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/",
                        p.params, p.query, ""))
    return clean


class LinkExtractor(HTMLParser):
    """Minimal HTML parser that collects href values from <a> tags."""
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)

def extract_links(html, base_url):
    """Parse HTML and return absolute URLs found in <a href> tags."""
    parser = LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    links = []
    for href in parser.links:
        try:
            abs_url = urljoin(base_url, href.strip())
            links.append(abs_url)
        except Exception:
            pass
    return links


# ── Pagination helpers ────────────────────────────────────────────────────────

import re as _page_re

# Patterns that identify a page number in a URL.
# Each is (compiled_regex, group_name_for_number, builder_fn(url, new_num))
_PAGE_PATTERNS = [
    # /page-9  /page-10
    (_page_re.compile(r'(.*[/\-])page-(\d+)(/.*)?$', _page_re.I),
     lambda m, n: (m.group(1) or "") + f"page-{n}" + (m.group(3) or "")),
    # /page/9  /page/10
    (_page_re.compile(r'(.*/)page/(\d+)(/.*)?$', _page_re.I),
     lambda m, n: m.group(1) + f"page/{n}" + (m.group(3) or "")),
    # ?page=9  &page=9
    (_page_re.compile(r'(.+[?&])page=(\d+)(.*)?$', _page_re.I),
     lambda m, n: m.group(1) + f"page={n}" + (m.group(3) or "")),
    # ?p=9  &p=9
    (_page_re.compile(r'(.+[?&])p=(\d+)(.*)?$', _page_re.I),
     lambda m, n: m.group(1) + f"p={n}" + (m.group(3) or "")),
    # /pg/9  /pg-9
    (_page_re.compile(r'(.*/)pg[/-](\d+)(/.*)?$', _page_re.I),
     lambda m, n: m.group(1) + f"pg/{n}" + (m.group(3) or "")),
    # -9  at end of path segment (e.g. /threads/name.123-4/)
    (_page_re.compile(r'(.*\.\d+)-(\d+)(/?)$'),
     lambda m, n: m.group(1) + f"-{n}" + (m.group(3) or "")),
]

def detect_pagination(url):
    """
    If url contains a page number, return (base_path, current_page_num, builder_fn)
    where builder_fn(n) returns the URL for page n.
    Returns None if no pagination pattern is found.
    """
    parsed = urlparse(url)
    # Check path + query together
    full = parsed.path + ("?" + parsed.query if parsed.query else "")
    for pattern, builder in _PAGE_PATTERNS:
        m = pattern.match(full)
        if m:
            # Extract the page number group (always group 2)
            try:
                page_num = int(m.group(2))
            except (IndexError, ValueError):
                continue

            def make_builder(parsed=parsed, m=m, builder=builder):
                def build(n):
                    new_full = builder(m, n)
                    # Split back into path and query
                    if "?" in new_full:
                        new_path, new_query = new_full.split("?", 1)
                    else:
                        new_path, new_query = new_full, ""
                    return urlunparse((parsed.scheme, parsed.netloc,
                                       new_path, "", new_query, ""))
                return build

            return page_num, make_builder()
    return None


def generate_page_run(url, direction="both", limit=2000):
    """
    Given a paginated URL, return an ordered list of URLs to crawl:
    - Goes backward from current page to page 1
    - Then forward from current page until we'd exceed limit
    So the queue is exhausted in order.
    """
    result = detect_pagination(url)
    if not result:
        return None
    current, builder = result

    pages = []
    # Pages before current (1 up to current-1), then current, then forward
    for n in range(1, current):
        pages.append(builder(n))
    pages.append(url)   # current page itself
    # We'll grow forward dynamically during crawl — just seed up to current
    return pages, current, builder



# ── Sound engine ──────────────────────────────────────────────────────────────

import tempfile, queue as _queue, atexit, platform as _platform, subprocess as _subprocess

_OS = _platform.system()   # "Windows" | "Darwin" | "Linux"

def _detect_player():
    """
    Return (backend_name, callable(tmp_path)) or ("none", None).
    Windows  -> winsound.PlaySound (SND_FILENAME, blocking)
    macOS    -> afplay (built in)
    Linux    -> first of: aplay, paplay, ffplay, sox(play)
    """
    if _OS == "Windows":
        try:
            import winsound as _ws
            def _play_win(p, _w=_ws):
                _w.PlaySound(p, _w.SND_FILENAME)
            return "winsound", _play_win
        except ImportError:
            pass

    if _OS == "Darwin":
        try:
            _subprocess.run(["afplay", "--version"], capture_output=True, timeout=3)
            def _play_mac(p):
                _subprocess.run(["afplay", p], check=True, capture_output=True, timeout=30)
            return "afplay", _play_mac
        except Exception:
            pass
        try:
            def _play_osx_beep(p):
                _subprocess.run(["osascript", "-e", "beep"], capture_output=True, timeout=5)
            return "osascript", _play_osx_beep
        except Exception:
            pass

    if _OS == "Linux":
        for cmd, args_fn in [
            ("aplay",  lambda p: ["aplay",  "-q", p]),
            ("paplay", lambda p: ["paplay", p]),
            ("ffplay", lambda p: ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", p]),
            ("play",   lambda p: ["play",   "-q", p]),
        ]:
            try:
                _subprocess.run(["which", cmd], capture_output=True, check=True, timeout=3)
                def _play_linux(p, _a=args_fn):
                    _subprocess.run(_a(p), check=True, capture_output=True, timeout=30)
                return cmd, _play_linux
            except Exception:
                continue

    return "none", None

_AUDIO_BACKEND, _AUDIO_PLAY_FN = _detect_player()
_HAS_SOUND = _AUDIO_PLAY_FN is not None


class SoundManager:
    """
    Synthesises WAV tones in pure Python (stdlib only) and plays them via the
    best available audio backend on Windows, macOS, and Linux.
    A background queue thread serialises playback so sounds never cut each other off.
    """
    SR = 44100

    SOUNDS = {
        "archiving":  {"label": "Archiving Start",  "vol": 40},
        "saved":      {"label": "Page Saved",        "vol": 75},
        "complete":   {"label": "All Done",          "vol": 85},
        "crawl_done": {"label": "Crawl Complete",    "vol": 85},
        "error":      {"label": "Error / Failed",    "vol": 90},
        "rate_limit": {"label": "Rate Limited",      "vol": 80},
        "outage":     {"label": "IA Outage Alarm",   "vol": 95},
        "skipped":    {"label": "URL Skipped",       "vol": 25},
    }

    def __init__(self):
        self.master_vol  = 80
        self.enabled     = True
        self.vols        = {k: v["vol"] for k, v in self.SOUNDS.items()}
        self._cache      = {}
        self._last_error = None
        self._q          = _queue.Queue()
        self._worker     = threading.Thread(target=self._playback_loop, daemon=True)
        self._worker.start()
        atexit.register(self._shutdown)

    def _shutdown(self):
        self._q.put(None)

    def _playback_loop(self):
        """Background thread — plays one sound at a time from the queue."""
        while True:
            item = self._q.get()
            if item is None:
                break
            tmp_path = item
            try:
                if _AUDIO_PLAY_FN:
                    _AUDIO_PLAY_FN(tmp_path)
            except Exception as e:
                self._last_error = str(e)
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass


    # ── Waveform primitives ───────────────────────────────────────────────────

    def _sine(self, freq, dur, vol=1.0, attack=0.01, release=0.08):
        n   = int(self.SR * dur)
        atk = int(self.SR * attack)
        rel = int(self.SR * release)
        out = []
        for i in range(n):
            s = math.sin(2 * math.pi * freq * i / self.SR)
            if i < atk:
                env = i / atk
            elif i >= n - rel:
                env = (n - i) / max(rel, 1)
            else:
                env = 1.0
            out.append(s * env * vol)
        return out

    def _silence(self, dur):
        return [0.0] * int(self.SR * dur)

    def _cat(self, *parts):
        out = []
        for p in parts:
            out.extend(p)
        return out

    def _mix(self, *parts):
        length = max(len(p) for p in parts)
        out    = [0.0] * length
        for p in parts:
            for i, v in enumerate(p):
                out[i] += v
        peak = max(abs(x) for x in out) if out else 1.0
        if peak > 1.0:
            out = [x / peak for x in out]
        return out

    # ── Sound definitions ─────────────────────────────────────────────────────

    def _build(self, sid):
        if sid == "archiving":
            return self._sine(1400, 0.06, vol=0.7, attack=0.004, release=0.04)

        elif sid == "skipped":
            return self._sine(900, 0.04, vol=0.5, attack=0.003, release=0.03)

        elif sid == "saved":
            a = self._sine(784,  0.20, attack=0.008, release=0.12)
            b = self._sine(988,  0.30, attack=0.008, release=0.20)
            return self._cat(a, self._silence(0.04), b)

        elif sid == "complete":
            parts = []
            for i, (f, d) in enumerate([(523, 0.18), (659, 0.18), (784, 0.18), (1047, 0.60)]):
                parts.append(self._sine(f, d, attack=0.010, release=0.12))
                if i < 3:
                    parts.append(self._silence(0.03))
            return self._cat(*parts)

        elif sid == "crawl_done":
            parts = []
            for i, (f, d) in enumerate([(523,0.16),(659,0.16),(784,0.16),(880,0.16),(1047,0.70)]):
                parts.append(self._sine(f, d, attack=0.010, release=0.10))
                if i < 4:
                    parts.append(self._silence(0.025))
            return self._cat(*parts)

        elif sid == "error":
            out = []
            for freq in [600, 420, 260]:
                body = self._sine(freq,       0.15, attack=0.005, release=0.03)
                harm = self._sine(freq * 1.5, 0.15, vol=0.4, attack=0.005, release=0.03)
                out.extend(self._mix(body, harm))
                out.extend(self._silence(0.05))
            return out

        elif sid == "rate_limit":
            beep = self._sine(520, 0.15, attack=0.010, release=0.06)
            return self._cat(beep, self._silence(0.10), beep)

        elif sid == "outage":
            hi  = self._sine(960, 0.16, attack=0.005, release=0.02)
            lo  = self._sine(440, 0.16, attack=0.005, release=0.02)
            gap = self._silence(0.025)
            out = []
            for _ in range(5):
                out.extend(hi); out.extend(gap)
                out.extend(lo); out.extend(gap)
            return out

        return self._silence(0.1)

    # ── WAV helpers ───────────────────────────────────────────────────────────

    def _to_wav_bytes(self, samples):
        """Convert float samples [-1,1] to a complete WAV bytes object."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.SR)
            clamped = [max(-32767, min(32767, int(s * 32767))) for s in samples]
            w.writeframes(struct.pack(f"<{len(clamped)}h", *clamped))
        return buf.getvalue()

    def _wav_for(self, sid):
        """Return full-volume cached WAV bytes for a sound id."""
        if sid not in self._cache:
            self._cache[sid] = self._to_wav_bytes(self._build(sid))
        return self._cache[sid]

    def _write_tmp(self, wav_bytes, vol):
        """Write volume-scaled WAV to a temp file, return its path."""
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as r:
            params = r.getparams()
            frames = r.readframes(r.getnframes())
        n       = len(frames) // 2
        samples = struct.unpack(f"<{n}h", frames)
        scaled  = [max(-32767, min(32767, int(s * vol))) for s in samples]
        out_buf = io.BytesIO()
        with wave.open(out_buf, "wb") as w:
            w.setparams(params)
            w.writeframes(struct.pack(f"<{n}h", *scaled))
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(out_buf.getvalue())
        tmp.close()
        return tmp.name

    # ── Public API ────────────────────────────────────────────────────────────

    def play(self, sid):
        """Queue a sound for playback (non-blocking, serialised)."""
        if not self.enabled or not _HAS_SOUND:
            return
        vol = (self.master_vol / 100.0) * (self.vols.get(sid, 70) / 100.0)
        if vol <= 0.001:
            return
        try:
            tmp_path = self._write_tmp(self._wav_for(sid), vol)
            self._q.put(tmp_path)
        except Exception as e:
            self._last_error = str(e)

    def preview(self, sid, individual_vol=None, master_vol=None):
        """Preview immediately via the same queue."""
        if not _HAS_SOUND:
            return
        mv  = (master_vol     if master_vol     is not None else self.master_vol) / 100.0
        iv  = (individual_vol if individual_vol is not None else self.vols.get(sid, 70)) / 100.0
        vol = mv * iv
        if vol <= 0.001:
            return
        try:
            tmp_path = self._write_tmp(self._wav_for(sid), vol)
            self._q.put(tmp_path)
        except Exception as e:
            self._last_error = str(e)

    def test_audio(self):
        """
        Cross-platform audio sanity check.
        Returns (ok: bool, detail: str).
        """
        if not _HAS_SOUND:
            return False, f"No audio backend found on {_OS}. Install 'aplay' (Linux) or check system audio."
        # Write a short 440 Hz test tone and try to play it
        try:
            tone = self._sine(440, 0.3, vol=0.5)
            wav  = self._wav_for("saved")   # use cached sound
            tmp  = self._write_tmp(wav, 0.6)
            _AUDIO_PLAY_FN(tmp)
            try:
                os.unlink(tmp)
            except Exception:
                pass
            return True, f"Audio OK  (backend: {_AUDIO_BACKEND})"
        except Exception as e:
            return False, f"Audio error ({_AUDIO_BACKEND}): {e}"

    def get_state(self):
        return {"master_vol": self.master_vol, "enabled": self.enabled, "vols": dict(self.vols)}

    def set_state(self, data):
        self.master_vol = data.get("master_vol", self.master_vol)
        self.enabled    = data.get("enabled",    self.enabled)
        for k, v in data.get("vols", {}).items():
            if k in self.vols:
                self.vols[k] = v


# ── Sound settings dialog ──────────────────────────────────────────────────────

class SoundSettingsDialog(tk.Toplevel):
    def __init__(self, parent, sound_mgr, master_var):
        super().__init__(parent)
        self.sm         = sound_mgr
        self.master_var = master_var   # shared IntVar from main window
        self.title("Sound Settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        # Center
        self.update_idletasks()
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        self.geometry(f"480x570+{px - 240}+{py - 285}")

        self._row_vars = {}   # sid -> IntVar for individual sliders
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=BG, padx=16, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔊  SOUND SETTINGS", bg=BG, fg=TEXT,
                 font=("Segoe UI Semibold", 12)).pack(side="left")

        # Enable toggle
        self._enabled_var = tk.BooleanVar(value=self.sm.enabled)
        ttk.Checkbutton(hdr, text="Enable sounds",
                        variable=self._enabled_var,
                        command=self._on_toggle).pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Master volume
        master_card = tk.Frame(self, bg=BG2, padx=16, pady=12)
        master_card.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(master_card, text="Master Volume", bg=BG2, fg=TEXT,
                 font=("Segoe UI Semibold", 10)).pack(anchor="w")
        tk.Label(master_card, text="Scales all sounds proportionally",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", pady=(0, 6))

        mv_row = tk.Frame(master_card, bg=BG2)
        mv_row.pack(fill="x")
        self._master_lbl = tk.Label(mv_row, text=f"{self.master_var.get()}%",
                                    bg=BG2, fg=ACCENT,
                                    font=("Segoe UI Semibold", 10), width=5)
        self._master_lbl.pack(side="right")
        master_slider = tk.Scale(
            mv_row, from_=0, to=100, orient="horizontal",
            variable=self.master_var,
            bg=BG2, fg=TEXT, troughcolor=BG3,
            highlightthickness=0, bd=0,
            activebackground=ACCENT, sliderrelief="flat",
            command=lambda v: self._master_lbl.config(text=f"{int(float(v))}%")
        )
        master_slider.pack(side="left", fill="x", expand=True)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(12, 0))

        # Individual sound rows
        tk.Label(self, text="INDIVIDUAL SOUNDS", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", padx=16, pady=(10, 4))

        scroll_frame = tk.Frame(self, bg=BG)
        scroll_frame.pack(fill="both", expand=True, padx=16)

        for sid, info in SoundManager.SOUNDS.items():
            self._build_sound_row(scroll_frame, sid, info["label"])

        # Close button
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))
        btn_row = tk.Frame(self, bg=BG, padx=16, pady=10)
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="Close", bg=BG3, fg=TEXT, relief="flat",
                  font=FONT_BOLD, cursor="hand2",
                  activebackground=BG4, activeforeground=TEXT,
                  padx=18, pady=8, command=self._on_close).pack(side="right")
        tk.Button(btn_row, text="Reset all to default", bg=BG3, fg=TEXT_DIM,
                  relief="flat", font=FONT_SM, cursor="hand2",
                  activebackground=BG4, activeforeground=TEXT,
                  padx=12, pady=8, command=self._reset_all).pack(side="left")
        tk.Button(btn_row, text="🔔  Test audio", bg=BG3, fg=SUCCESS,
                  relief="flat", font=FONT_SM, cursor="hand2",
                  activebackground=BG4, activeforeground=SUCCESS,
                  padx=12, pady=8, command=self._test_audio).pack(side="left", padx=(6, 0))

        # Error / status label
        self._audio_status_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self._audio_status_var,
                 bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=16, pady=(0, 4))

    def _build_sound_row(self, parent, sid, label):
        row = tk.Frame(parent, bg=BG2, pady=6, padx=10)
        row.pack(fill="x", pady=(0, 4))

        # Label
        tk.Label(row, text=label, bg=BG2, fg=TEXT,
                 font=FONT_SM, width=18, anchor="w").pack(side="left")

        # Play button
        play_btn = tk.Button(row, text="▶", bg=BG3, fg=ACCENT,
                             relief="flat", font=("Segoe UI", 9),
                             cursor="hand2", padx=6, pady=2,
                             activebackground=BG4, activeforeground=ACCENT2,
                             command=lambda s=sid: self._preview(s))
        play_btn.pack(side="left", padx=(0, 8))
        Tooltip(play_btn, f"Preview: {label}")

        # Slider
        var = tk.IntVar(value=self.sm.vols.get(sid, 70))
        self._row_vars[sid] = var

        lbl = tk.Label(row, text=f"{var.get()}%", bg=BG2, fg=TEXT_DIM,
                       font=FONT_SM, width=4, anchor="e")
        lbl.pack(side="right")

        slider = tk.Scale(
            row, from_=0, to=100, orient="horizontal",
            variable=var, bg=BG2, fg=TEXT, troughcolor=BG3,
            highlightthickness=0, bd=0,
            activebackground=ACCENT, sliderrelief="flat",
            showvalue=False,
            command=lambda v, l=lbl, s=sid: (
                l.config(text=f"{int(float(v))}%"),
                self.sm.vols.update({s: int(float(v))})
            )
        )
        slider.pack(side="left", fill="x", expand=True, padx=(0, 6))

    def _test_audio(self):
        ok, err = self.sm.test_audio()
        if ok:
            self._audio_status_var.set("✓ Audio system working — playing test beep")
            # Also queue one of our custom sounds as a second check
            self.sm.preview("saved", individual_vol=80, master_vol=self.master_var.get())
        else:
            self._audio_status_var.set(f"✗ Audio error: {err}")

    def _preview(self, sid):
        self.sm.preview(
            sid,
            individual_vol=self._row_vars[sid].get(),
            master_vol=self.master_var.get()
        )

    def _on_toggle(self):
        self.sm.enabled = self._enabled_var.get()

    def _reset_all(self):
        defaults = {k: v["vol"] for k, v in SoundManager.SOUNDS.items()}
        for sid, var in self._row_vars.items():
            var.set(defaults[sid])
            self.sm.vols[sid] = defaults[sid]
        self.master_var.set(80)
        self.sm.master_vol = 80

    def _on_close(self):
        # Sync master vol back to SoundManager from the shared var
        self.sm.master_vol = self.master_var.get()
        self.destroy()


# ── Animated progress bar ─────────────────────────────────────────────────────

class AnimatedProgressBar(tk.Canvas):
    """
    Custom canvas progress bar with:
      - Moving shimmer while archiving
      - Color transitions for success / error / warning / outage
      - Pulse animation for rate-limit and outage states
    """
    FRAME_MS     = 16    # ~60 fps
    SHIMMER_W    = 80    # shimmer stripe pixel width
    SHIMMER_STEP = 4     # pixels moved per frame

    # (fill, shimmer/pulse-highlight)
    PALETTES = {
        "idle":      ("#2e2e2e", "#3a3a3a"),
        "archiving": ("#e85d2f", "#ff9060"),
        "success":   ("#4caf7d", "#80e8ad"),
        "error":     ("#e85d5d", "#ff9090"),
        "warning":   ("#e8a83d", "#ffd080"),
        "outage":    ("#cc2222", "#ff4444"),
    }

    def __init__(self, parent, height=7, **kwargs):
        super().__init__(parent, height=height, bd=0,
                         highlightthickness=0, bg=BG, **kwargs)
        self._val      = 0
        self._maximum  = 100
        self._state    = "idle"
        self._shim_x   = 0
        self._pulse    = 0.0
        self._pulse_dir = 1
        self._job      = None
        self._flash_q  = []

        self.bind("<Configure>", lambda e: self._draw())

    # ── Public API ────────────────────────────────────────────────────────────

    def set_progress(self, val, maximum):
        self._val     = val
        self._maximum = max(maximum, 1)
        if self._job is None:
            self._draw()

    def set_bar_state(self, state):
        """
        state: "idle" | "archiving" | "success" | "error" | "warning" | "outage"
        Triggers the appropriate animation.
        """
        prev = self._state
        self._state = state

        if state == "archiving":
            self._shim_x = 0
            self._ensure_anim()

        elif state in ("success", "error"):
            # Flash white then settle on state color
            self._stop_anim()
            self._flash(["#ffffff", "#ffffff", self.PALETTES[state][0]], on_done=self._draw)

        elif state in ("warning", "outage"):
            self._pulse   = 0.0
            self._pulse_dir = 1
            self._ensure_anim()

        else:  # idle
            self._stop_anim()
            self._draw()

    # ── Animation internals ───────────────────────────────────────────────────

    def _ensure_anim(self):
        if self._job is None:
            self._tick()

    def _stop_anim(self):
        if self._job:
            self.after_cancel(self._job)
            self._job = None

    def _tick(self):
        state = self._state
        if state == "archiving":
            filled_px = self._filled_px()
            if filled_px > 0:
                self._shim_x += self.SHIMMER_STEP
                if self._shim_x - self.SHIMMER_W > filled_px:
                    self._shim_x = 0
        elif state in ("warning", "outage"):
            speed = 0.04 if state == "outage" else 0.02
            self._pulse += speed * self._pulse_dir
            if self._pulse >= 1.0:
                self._pulse = 1.0; self._pulse_dir = -1
            elif self._pulse <= 0.0:
                self._pulse = 0.0; self._pulse_dir =  1

        self._draw()

        if self._state in ("archiving", "warning", "outage"):
            self._job = self.after(self.FRAME_MS, self._tick)
        else:
            self._job = None

    def _flash(self, colors, on_done=None, idx=0):
        """Cycle through a list of colors quickly, then call on_done."""
        if idx >= len(colors):
            if on_done:
                on_done()
            return
        w = self.winfo_width()
        h = self.winfo_height()
        self.delete("all")
        # Track
        self.create_rectangle(0, 0, w, h, fill=BG3, outline="")
        # Full bar flash
        if w > 0:
            self.create_rectangle(0, 0, w, h, fill=colors[idx], outline="")
        self.after(55, lambda: self._flash(colors, on_done, idx + 1))

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _filled_px(self):
        w = self.winfo_width()
        if w < 2 or self._maximum == 0:
            return 0
        return max(0, min(w, int(w * self._val / self._maximum)))

    def _draw(self, event=None):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return

        base, hi = self.PALETTES.get(self._state, self.PALETTES["idle"])
        filled   = self._filled_px()

        # Track
        self.create_rectangle(0, 0, w, h, fill=BG3, outline="")

        if filled <= 0:
            return

        # ── Archiving: shimmer stripe ──────────────────────────────────────
        if self._state == "archiving":
            # Base fill
            self.create_rectangle(0, 0, filled, h, fill=base, outline="")
            # Shimmer — three-band gradient (dark → bright → dark)
            bands = [
                (0.0,  base),
                (0.3,  hi),
                (0.7,  hi),
                (1.0,  base),
            ]
            band_px = self.SHIMMER_W / (len(bands) - 1)
            for i in range(len(bands) - 1):
                bx0 = self._shim_x - self.SHIMMER_W + int(i * band_px)
                bx1 = self._shim_x - self.SHIMMER_W + int((i + 1) * band_px)
                # Clip to filled area
                rx0 = max(0, min(filled, bx0))
                rx1 = max(0, min(filled, bx1))
                if rx1 > rx0:
                    # Interpolate color between bands[i] and bands[i+1]
                    c = bands[i + 1][1] if i == 1 else base
                    self.create_rectangle(rx0, 0, rx1, h, fill=c, outline="")

        # ── Warning / outage: pulsing brightness ───────────────────────────
        elif self._state in ("warning", "outage"):
            # Interpolate fill color toward hi based on pulse phase
            color = self._lerp_color(base, hi, self._pulse)
            self.create_rectangle(0, 0, filled, h, fill=color, outline="")

        # ── Success / error / idle: flat fill ─────────────────────────────
        else:
            self.create_rectangle(0, 0, filled, h, fill=base, outline="")

        # Rounded end cap (subtle)
        r = min(h // 2, 4)
        if filled >= r * 2:
            self.create_oval(filled - r*2, 0, filled, h, fill=base, outline="")

    @staticmethod
    def _lerp_color(c1, c2, t):
        """Linear interpolate between two hex colors."""
        def _p(c):
            c = c.lstrip("#")
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        r1, g1, b1 = _p(c1)
        r2, g2, b2 = _p(c2)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"


# ── Updater ───────────────────────────────────────────────────────────────────

import re as _re, shutil as _shutil

def _parse_version(source):
    """Extract VERSION = "x.y.z" from script source text."""
    m = _re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', source, _re.MULTILINE)
    return m.group(1) if m else None

def _version_tuple(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)

def _this_script_path():
    return Path(__file__).resolve()


class UpdateDialog(tk.Toplevel):
    """
    Self-update dialog.
    - Checks GitHub Releases API for the latest wayback_gui.py asset
    - Or lets you browse to a locally downloaded file
    - Backs up old version, replaces script, restarts app
    """

    def __init__(self, parent, current_version, *args):
        super().__init__(parent)
        self.parent          = parent
        self.current_version = current_version
        self._new_source     = None
        self._new_version    = None
        self._release_notes  = ""

        self.title("Update Wayback Archiver")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.focus_set()

        self.update_idletasks()
        px = parent.winfo_x() + parent.winfo_width()  // 2
        py = parent.winfo_y() + parent.winfo_height() // 2
        self.geometry(f"520x500+{px - 260}+{py - 250}")

        self._build()
        # Auto-check on open
        self.after(100, self._check_github)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=BG2, padx=18, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🔄  UPDATE", bg=BG2, fg=TEXT,
                 font=("Segoe UI Semibold", 12)).pack(side="left")
        tk.Label(hdr, text=f"Installed: v{self.current_version}",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(side="right")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG, padx=18, pady=12)
        body.pack(fill="both", expand=True)

        # ── GitHub latest release ─────────────────────────────────────────────
        gh_hdr = tk.Frame(body, bg=BG)
        gh_hdr.pack(fill="x")
        tk.Label(gh_hdr, text="GitHub Releases", bg=BG, fg=TEXT,
                 font=FONT_BOLD).pack(side="left")
        gh_link = tk.Label(gh_hdr, text="Open in browser →", bg=BG, fg=ACCENT,
                           font=FONT_SM, cursor="hand2")
        gh_link.pack(side="right")
        gh_link.bind("<Button-1>", lambda e: webbrowser.open(RELEASES_PAGE))

        # Release info card
        info_card = tk.Frame(body, bg=BG2, padx=12, pady=10)
        info_card.pack(fill="x", pady=(6, 0))

        self._release_title_var = tk.StringVar(value="Checking for updates…")
        tk.Label(info_card, textvariable=self._release_title_var,
                 bg=BG2, fg=TEXT, font=FONT_BOLD, anchor="w").pack(fill="x")

        self._release_date_var = tk.StringVar(value="")
        tk.Label(info_card, textvariable=self._release_date_var,
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM, anchor="w").pack(fill="x")

        # Release notes box
        tk.Label(body, text="Release notes", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(10, 2))
        self._notes_box = scrolledtext.ScrolledText(
            body, height=7, bg=BG2, fg=TEXT_DIM, font=FONT_MONO,
            relief="flat", bd=0, wrap="word", state="disabled"
        )
        self._notes_box.pack(fill="x")

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(10, 8))

        # ── Local file fallback ───────────────────────────────────────────────
        tk.Label(body, text="Or load from a local file",
                 bg=BG, fg=TEXT, font=FONT_BOLD).pack(anchor="w")
        tk.Label(body,
                 text="Browse to a wayback_gui.py file you downloaded manually.",
                 bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", pady=(2, 6))
        tk.Button(body, text="📂  Browse…",
                  bg=BG3, fg=TEXT, relief="flat", font=FONT_BOLD,
                  cursor="hand2", activebackground=BG4,
                  padx=12, pady=6,
                  command=self._browse_file).pack(anchor="w")

        # ── Status ────────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="")
        self._status_lbl = tk.Label(body, textvariable=self._status_var,
                                    bg=BG, fg=TEXT_DIM, font=FONT_SM,
                                    wraplength=460, justify="left")
        self._status_lbl.pack(anchor="w", pady=(8, 0))

        # ── Bottom buttons ────────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        btn_row = tk.Frame(self, bg=BG, padx=18, pady=10)
        btn_row.pack(fill="x")

        tk.Button(btn_row, text="Close", bg=BG3, fg=TEXT_DIM,
                  relief="flat", font=FONT_UI, cursor="hand2",
                  activebackground=BG4, activeforeground=TEXT,
                  padx=14, pady=7, command=self.destroy).pack(side="left")

        self._check_btn = tk.Button(btn_row, text="🔄  Check again",
                                    bg=BG3, fg=TEXT, relief="flat",
                                    font=FONT_UI, cursor="hand2",
                                    activebackground=BG4, activeforeground=TEXT,
                                    padx=14, pady=7,
                                    command=self._check_github)
        self._check_btn.pack(side="left", padx=(6, 0))

        self._apply_btn = tk.Button(btn_row,
                                    text="⬇  Download & install",
                                    bg=SUCCESS, fg="#fff",
                                    relief="flat", font=FONT_BOLD,
                                    cursor="hand2",
                                    activebackground="#3a9e6a",
                                    padx=14, pady=7,
                                    state="disabled",
                                    command=self._apply)
        self._apply_btn.pack(side="right")

    # ── Logic ─────────────────────────────────────────────────────────────────

    def _set_status(self, text, color=TEXT_DIM):
        self._status_var.set(text)
        self._status_lbl.config(fg=color)
        self.update_idletasks()

    def _set_notes(self, text):
        self._notes_box.config(state="normal")
        self._notes_box.delete("1.0", "end")
        self._notes_box.insert("end", text or "(No release notes provided.)")
        self._notes_box.config(state="disabled")

    def _check_github(self):
        self._release_title_var.set("Checking GitHub…")
        self._release_date_var.set("")
        self._set_notes("")
        self._set_status("Connecting to GitHub…", TEXT_DIM)
        self._apply_btn.config(state="disabled")
        threading.Thread(target=self._fetch_github, daemon=True).start()

    def _fetch_github(self):
        try:
            import urllib.request, json as _json
            req = urllib.request.Request(
                GITHUB_API,
                headers={"User-Agent": "WaybackArchiverGUI", "Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = _json.loads(r.read().decode("utf-8"))

            tag          = data.get("tag_name", "").lstrip("v")
            name         = data.get("name", f"v{tag}")
            published    = data.get("published_at", "")[:10]
            body         = data.get("body", "")
            assets       = data.get("assets", [])
            download_url = None

            # Find wayback_gui.py asset
            for asset in assets:
                if asset.get("name", "").endswith(".py"):
                    download_url = asset.get("browser_download_url")
                    break

            self.after(0, lambda: self._on_github_result(
                tag, name, published, body, download_url))

        except Exception as e:
            self.after(0, lambda: self._on_github_error(str(e)))

    def _on_github_result(self, tag, name, published, body, download_url):
        self._release_title_var.set(f"{name}  (v{tag})")
        self._release_date_var.set(f"Released: {published}" if published else "")
        self._set_notes(body)

        cur = _version_tuple(self.current_version)
        new = _version_tuple(tag)

        if not download_url:
            self._set_status(
                "⚠  No .py asset found in this release.\n"
                "The release may not have been published with a file yet.\n"
                "You can still load a file manually using Browse below.", WARNING)
            return

        self._pending_download_url = download_url

        if new > cur:
            self._set_status(
                f"✓  v{tag} is available  —  you have v{self.current_version}", SUCCESS)
            self._apply_btn.config(state="normal",
                                   text=f"⬇  Install v{tag} & restart")
        elif new == cur:
            self._set_status(
                f"You're up to date  (v{self.current_version})", SUCCESS)
            self._apply_btn.config(state="normal",
                                   text="🔁  Reinstall current version")
        else:
            self._set_status(
                f"GitHub has v{tag} which is older than your v{self.current_version}.", WARNING)

    def _on_github_error(self, error):
        self._release_title_var.set("Could not reach GitHub")
        self._set_status(
            f"Failed to check for updates: {error}\n"
            "Check your internet connection or use Browse to load a file.", ERROR)

    def _download_and_load(self, url):
        self.after(0, lambda: self._set_status("Downloading update…", TEXT_DIM))
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as r:
                source = r.read().decode("utf-8")
            self._load_source(source, f"GitHub release asset")
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Download failed: {e}", ERROR))

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select updated wayback_gui.py",
            filetypes=[("Python files", "*.py"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            source = Path(path).read_text(encoding="utf-8")
            self._load_source(source, f"Local file: {Path(path).name}")
        except Exception as e:
            self._set_status(f"Could not read file: {e}", ERROR)

    def _load_source(self, source, source_label):
        version = _parse_version(source)
        if not version:
            self.after(0, lambda: self._set_status(
                "No VERSION found — is this a valid Wayback Archiver file?", ERROR))
            return
        self._new_source  = source
        self._new_version = version
        cur = _version_tuple(self.current_version)
        new = _version_tuple(version)

        if new > cur:
            msg   = f"✓  v{version} ready to install  (you have v{self.current_version})\n{source_label}"
            color = SUCCESS
            ok    = True
        elif new == cur:
            msg   = f"Same version (v{version}) — reinstall anyway?\n{source_label}"
            color = WARNING
            ok    = True
        else:
            msg   = f"v{version} is older than your v{self.current_version}.\n{source_label}"
            color = WARNING
            ok    = False

        def _u():
            self._set_status(msg, color)
            self._apply_btn.config(
                state="normal" if ok else "disabled",
                text=f"✓  Install v{version} & restart"
            )
        self.after(0, _u)

    def _apply(self):
        # If we have a pending GitHub download URL and no source yet, download first
        if not self._new_source and hasattr(self, "_pending_download_url"):
            self._set_status("Downloading…", TEXT_DIM)
            self._apply_btn.config(state="disabled")
            threading.Thread(target=self._download_then_apply, daemon=True).start()
            return
        self._do_apply()

    def _download_then_apply(self):
        try:
            import urllib.request
            with urllib.request.urlopen(self._pending_download_url, timeout=30) as r:
                source = r.read().decode("utf-8")
            version = _parse_version(source)
            if not version:
                self.after(0, lambda: self._set_status("Invalid file downloaded.", ERROR))
                return
            self._new_source  = source
            self._new_version = version
            self.after(0, self._do_apply)
        except Exception as e:
            self.after(0, lambda: self._set_status(f"Download failed: {e}", ERROR))
            self.after(0, lambda: self._apply_btn.config(state="normal"))

    def _do_apply(self):
        if not self._new_source:
            return
        script_path = _this_script_path()
        script_dir  = script_path.parent

        import re as _re
        clean_stem = _re.sub(r'_v[\d.]+.*$', '', script_path.stem)
        if not clean_stem:
            clean_stem = "wayback_gui"

        backup_path = script_dir / f"{clean_stem}_v{self.current_version}.bak.py"
        new_path    = script_dir / f"{clean_stem}_v{self._new_version}.py"

        try:
            # 1 — Backup current file
            _shutil.copy2(script_path, backup_path)

            # 2 — Write new version
            new_path.write_text(self._new_source, encoding="utf-8")

            # 3 — Collect old versioned files to delete
            #     Can't delete the running file now (Windows locks it),
            #     so we write a cleanup script that runs after we exit.
            to_delete = []
            new_ver_tuple = tuple(int(x) for x in self._new_version.split("."))
            for old_file in script_dir.glob(f"{clean_stem}_v*.py"):
                if old_file.resolve() == new_path.resolve():
                    continue
                if ".bak" in old_file.name:
                    continue
                m = _re.search(r'_v([\d.]+)\.py$', old_file.name)
                if not m:
                    continue
                try:
                    fver = tuple(int(x) for x in m.group(1).split("."))
                    if fver < new_ver_tuple:
                        to_delete.append(old_file)
                except Exception:
                    pass

            # Also collect malformed .bak files
            for old_bak in script_dir.glob(f"{clean_stem}_v*.bak.py"):
                if old_bak.resolve() == backup_path.resolve():
                    continue
                if _re.search(r'_v[\d.]+\.v[\d.]+', old_bak.name):
                    to_delete.append(old_bak)

            # 4 — Write a platform-specific cleanup script that runs after we exit
            if to_delete:
                import platform as _pl
                if _pl.system() == "Windows":
                    lines = ["@echo off", "timeout /t 3 /nobreak >nul"]
                    for f in to_delete:
                        lines.append(f'del /f /q "{f}"')
                    cleanup = script_dir / "_wayback_cleanup.bat"
                    cleanup.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
                    # Launch cleanup bat detached, then start new version
                    import subprocess as _sp
                    _sp.Popen(["cmd", "/c", str(cleanup)],
                              creationflags=_sp.CREATE_NO_WINDOW,
                              close_fds=True)
                else:
                    lines = ["#!/bin/sh", "sleep 3"]
                    for f in to_delete:
                        lines.append(f'rm -f "{f}"')
                    lines.append(f'rm -f "{script_dir}/_wayback_cleanup.sh"')
                    cleanup = script_dir / "_wayback_cleanup.sh"
                    cleanup.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    cleanup.chmod(0o755)
                    import subprocess as _sp
                    _sp.Popen(["/bin/sh", str(cleanup)],
                              close_fds=True, start_new_session=True)

            deleted_names = [f.name for f in to_delete if ".bak" not in f.name or
                             _re.search(r'_v[\d.]+\.v[\d.]+', f.name)]
            deleted_msg = f"\nDeleted: {', '.join(deleted_names)}" if deleted_names else ""

            self._set_status(
                f"✓  Updated to v{self._new_version}!\n"
                f"New file: {new_path.name}\n"
                f"Backup:   {backup_path.name}"
                f"{deleted_msg}\n"
                "Restarting…", SUCCESS)
            self.update_idletasks()
            self.after(900, lambda: self._restart(new_path))

        except Exception as e:
            self._set_status(f"Update failed: {e}\nYour file was not changed.", ERROR)

        except Exception as e:
            self._set_status(f"Update failed: {e}\nYour file was not changed.", ERROR)

        except Exception as e:
            self._set_status(f"Update failed: {e}\nYour file was not changed.", ERROR)

    def _restart(self, script_path):
        import subprocess
        subprocess.Popen([sys.executable, str(script_path)])
        self.parent.destroy()


# ── Tooltip ───────────────────────────────────────────────────────────────────

class Tooltip:
    """
    Small popup that appears next to the mouse cursor when hovering a widget.
    Automatically wraps text and positions itself to stay on screen.
    """
    PAD       = 8    # inner padding
    DELAY_MS  = 500  # ms before showing
    MAX_WIDTH = 280  # max pixel width before wrapping

    def __init__(self, widget, text):
        self.widget   = widget
        self.text     = text
        self.tip_win  = None
        self._job     = None
        widget.bind("<Enter>",    self._on_enter,  add="+")
        widget.bind("<Leave>",    self._on_leave,  add="+")
        widget.bind("<Button>",   self._on_leave,  add="+")
        widget.bind("<Destroy>",  self._on_leave,  add="+")

    def _on_enter(self, event):
        self._cancel()
        self._job = self.widget.after(self.DELAY_MS, lambda e=event: self._show(e))

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._job:
            self.widget.after_cancel(self._job)
            self._job = None

    def _show(self, event):
        if self.tip_win:
            return
        # Build window
        self.tip_win = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)   # no title bar / border
        tw.wm_attributes("-topmost", True)
        tw.configure(bg=BORDER)

        # Outer frame gives the 1px border effect
        outer = tk.Frame(tw, bg=BORDER, padx=1, pady=1)
        outer.pack()
        inner = tk.Frame(outer, bg="#1e1e1e")
        inner.pack()

        lbl = tk.Label(
            inner,
            text=self.text,
            bg="#1e1e1e",
            fg="#d8d8d8",
            font=("Segoe UI", 9),
            justify="left",
            wraplength=self.MAX_WIDTH,
            padx=self.PAD,
            pady=self.PAD - 2,
        )
        lbl.pack()

        # Force geometry calculation
        tw.update_idletasks()
        tip_w = tw.winfo_reqwidth()
        tip_h = tw.winfo_reqheight()

        # Position: 14px right and 14px below cursor, nudge if off screen
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()
        x = event.x_root + 14
        y = event.y_root + 14

        if x + tip_w > screen_w - 10:
            x = event.x_root - tip_w - 6
        if y + tip_h > screen_h - 10:
            y = event.y_root - tip_h - 6

        tw.wm_geometry(f"+{x}+{y}")

    def _hide(self):
        if self.tip_win:
            self.tip_win.destroy()
            self.tip_win = None


def tip(widget, text):
    """Convenience wrapper — attach a tooltip to any widget."""
    Tooltip(widget, text)


# ── GUI ───────────────────────────────────────────────────────────────────────

class WaybackGUI:
    # Braille spinner frames
    _SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _SPINNER_MS     = 90

    def __init__(self, root):
        self.root              = root
        self.running           = False
        self.stop_flag         = False
        self.thread            = None
        self.state             = load_state()
        self.all_urls          = []
        self._server_err_count = 0
        self._outage_popup     = None
        self._rate_wait_event  = threading.Event()
        self._pause_event      = threading.Event()
        self._pause_event.set()
        self._rl_hit_count     = 0   # consecutive rate limit hits for popup display
        self._spinner_url      = None
        self._spinner_idx      = 0
        self._spinner_job      = None
        self._tree_user_scrolled = False   # True when user has manually scrolled the checklist
        self.sounds            = SoundManager()
        self.master_vol_var    = tk.IntVar(value=self.sounds.master_vol)
        self._stats_counts     = {"total": 0, "archived": 0, "existing": 0,
                                  "partial": 0, "pending": 0}

        root.title("Wayback Machine Archiver")
        root.configure(bg=BG)
        root.minsize(960, 700)

        self._style()
        self._build()
        self._load_settings()
        self._check_resume_checkpoint()

    # ── Style ─────────────────────────────────────────────────────────────────

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, font=FONT_UI, borderwidth=0, relief="flat")
        s.configure("TFrame",    background=BG)
        s.configure("TLabel",    background=BG,  foreground=TEXT, font=FONT_UI)
        s.configure("TEntry",    fieldbackground=BG3, foreground=TEXT, insertcolor=TEXT,
                                 borderwidth=1, relief="flat", padding=(8, 5))
        s.configure("TCheckbutton", background=BG2, foreground=TEXT, font=FONT_UI,
                                    indicatorcolor=BG3, indicatorrelief="flat")
        s.map("TCheckbutton",
            background=[("active", BG2)],
            indicatorcolor=[("selected", ACCENT), ("!selected", BG3)]
        )
        s.configure("TSpinbox",  fieldbackground=BG3, foreground=TEXT,
                                 insertcolor=TEXT, arrowcolor=TEXT_DIM, padding=(6, 4))
        s.configure("TCombobox", fieldbackground=BG3, foreground=TEXT,
                                 selectbackground=BG3, selectforeground=TEXT,
                                 arrowcolor=TEXT_DIM, padding=(6, 4))
        s.map("TCombobox", fieldbackground=[("readonly", BG3)])
        s.configure("Start.TButton", background=ACCENT,  foreground="#fff",
                                     font=FONT_BOLD, padding=(18, 9), relief="flat")
        s.map("Start.TButton",
            background=[("active", ACCENT2), ("disabled", BG3)],
            foreground=[("disabled", TEXT_DIM)]
        )
        s.configure("Stop.TButton",  background=BG3, foreground=ERROR,
                                     font=FONT_BOLD, padding=(18, 9), relief="flat")
        s.map("Stop.TButton", background=[("active", "#2e2020")])
        s.configure("Sm.TButton",    background=BG3, foreground=TEXT_DIM,
                                     font=FONT_SM, padding=(10, 6), relief="flat")
        s.map("Sm.TButton", background=[("active", BG4)], foreground=[("active", TEXT)])
        s.configure("Treeview",      background=BG2, foreground=TEXT,
                                     fieldbackground=BG2, font=FONT_MONO,
                                     rowheight=22, borderwidth=0)
        s.configure("Treeview.Heading", background=BG3, foreground=TEXT_DIM,
                                        font=("Segoe UI Semibold", 8),
                                        relief="flat", padding=(6, 4))
        s.map("Treeview",
            background=[("selected", BG4)],
            foreground=[("selected", TEXT)]
        )

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=18, pady=(16, 0))
        tk.Label(hdr, text="WAYBACK",  font=("Segoe UI Black", 18), bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(hdr, text=" ARCHIVER", font=("Segoe UI Light", 18), bg=BG, fg=TEXT).pack(side="left")
        tk.Label(hdr, text=f" v{VERSION}", font=("Segoe UI", 9), bg=BG, fg=TEXT_DIM).pack(side="left", pady=(6, 0))
        # Header right-side buttons
        ttk.Button(hdr, text="💾  Save settings", style="Sm.TButton",
                   command=self._save_settings).pack(side="right")
        ttk.Button(hdr, text="🔄  Update", style="Sm.TButton",
                   command=self._open_update_dialog).pack(side="right", padx=(0, 6))
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=18, pady=(10, 0))

        paned = tk.PanedWindow(self.root, orient="horizontal", bg=BG,
                               sashwidth=4, sashrelief="flat", sashpad=2)
        paned.pack(fill="both", expand=True, padx=18, pady=10)

        # Left side: scrollable canvas so it never gets cut off
        left_outer = tk.Frame(paned, bg=BG)
        left_canvas = tk.Canvas(left_outer, bg=BG, highlightthickness=0, width=370)
        left_scroll = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side="right", fill="y")
        left_canvas.pack(side="left", fill="both", expand=True)
        left = tk.Frame(left_canvas, bg=BG)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")

        def _on_left_configure(e):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        def _on_canvas_resize(e):
            left_canvas.itemconfig(left_window, width=e.width)
        left.bind("<Configure>", _on_left_configure)
        left_canvas.bind("<Configure>", _on_canvas_resize)

        # Mouse wheel — only scroll the left panel when cursor is over it
        def _on_mousewheel(e):
            left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        def _bind_wheel(e):
            left_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        def _unbind_wheel(e):
            left_canvas.unbind_all("<MouseWheel>")
        left_outer.bind("<Enter>", _bind_wheel)
        left_outer.bind("<Leave>", _unbind_wheel)
        left_canvas.bind("<Enter>", _bind_wheel)
        left_canvas.bind("<Leave>", _unbind_wheel)
        left.bind("<Enter>", _bind_wheel)
        left.bind("<Leave>", _unbind_wheel)

        right = tk.Frame(paned, bg=BG)
        paned.add(left_outer, minsize=340, width=395)
        paned.add(right,      minsize=500)

        self._build_left(left)
        self._build_right(right)

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=18)
        self._build_bottom()

    def _build_left(self, parent):
        # ── URL LIST ──────────────────────────────────────────────────────────
        self._section(parent, "URL LIST")
        card = self._card(parent)
        tk.Label(card, text="Text file — one URL per line",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=10, pady=(8, 2))
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", padx=10, pady=(0, 8))
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", lambda *_: self._on_file_change())
        url_entry_w = ttk.Entry(row, textvariable=self.url_var, font=FONT_MONO)
        url_entry_w.pack(side="left", fill="x", expand=True)
        tip(url_entry_w, "Path to a plain text file containing URLs to archive,\none per line. Lines starting with # are ignored.")
        browse_btn = ttk.Button(row, text="Browse", style="Sm.TButton", command=self._browse)
        browse_btn.pack(side="right", padx=(4, 0))
        tip(browse_btn, "Open a file picker to select your URL list.")

        # ── CRAWL WEBSITE ─────────────────────────────────────────────────────
        self._section(parent, "CRAWL ENTIRE WEBSITE  (optional)")
        card = self._card(parent)

        tk.Label(card, text="Starting URL  (any page on the site)",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=10, pady=(8, 2))
        crawl_row = tk.Frame(card, bg=BG2)
        crawl_row.pack(fill="x", padx=10, pady=(0, 6))
        self.crawl_url_var = tk.StringVar()
        crawl_entry = ttk.Entry(crawl_row, textvariable=self.crawl_url_var, font=FONT_MONO)
        crawl_entry.pack(fill="x")
        tip(crawl_entry,
            "Enter any URL from the website you want to fully archive.\n"
            "The crawler finds every link on each page and archives them all.\n\n"
            "SUPPORTED URL TYPES:\n"
            "  • Regular websites (forums, blogs, wikis, etc.)\n"
            "  • Google Docs / Sheets — links extracted via export API\n"
            "  • Reddit — uses old.reddit.com for reliable link extraction\n"
            "  • GitHub Issues/PRs — uses GitHub API\n"
            "  • Twitter/X — uses Nitter mirror\n"
            "  • DeviantArt, ArtStation, Pixiv — uses oEmbed/API\n"
            "  • Paginated sites (page-1, page-2…) — auto-detected and\n"
            "    crawled in order before moving to other links\n\n"
            "TIP: You can start on any page, including a specific page\n"
            "number — the crawler will detect the pagination and start\n"
            "from page 1 automatically.\n\n"
            "Example: https://bitbuilt.net/forums/forums/console-modding-101.150/page-9\n"
            "→ archives all pages of that forum section from page 1 upward")

        # Max pages + same-path option row
        opts_row = tk.Frame(card, bg=BG2)
        opts_row.pack(fill="x", padx=10, pady=(0, 4))

        lbl_max = tk.Label(opts_row, text="Max pages", bg=BG2, fg=TEXT, font=FONT_SM)
        lbl_max.pack(side="left")
        tip(lbl_max,
            "Maximum number of pages to crawl before stopping.\n\n"
            "RECOMMENDED AMOUNTS:\n"
            "  • Small blog / profile page:    50–100\n"
            "  • Forum section / thread list:  200–500\n"
            "  • Full small site:              500–2000\n"
            "  • Large forum or wiki:          2000–10000\n\n"
            "The crawler stops when it hits this limit even if there\n"
            "are more pages to discover. Increase if pages are being\n"
            "cut off. Discovered URLs appear in the checklist in real\n"
            "time so you can watch how many are being found.")
        self.crawl_max_var = tk.IntVar(value=500)
        max_spin = ttk.Spinbox(opts_row, from_=1, to=50000,
                               textvariable=self.crawl_max_var, width=7, font=FONT_SM)
        max_spin.pack(side="left", padx=(6, 0))
        tip(max_spin,
            "Maximum number of pages to crawl before stopping.\n\n"
            "RECOMMENDED AMOUNTS:\n"
            "  • Small blog / profile page:    50–100\n"
            "  • Forum section / thread list:  200–500\n"
            "  • Full small site:              500–2000\n"
            "  • Large forum or wiki:          2000–10000\n\n"
            "The crawler stops when it hits this limit even if there\n"
            "are more pages to discover.")

        # Checkboxes
        cb_frame = tk.Frame(card, bg=BG2)
        cb_frame.pack(fill="x", padx=10, pady=(4, 0))

        self.crawl_same_path_var = tk.BooleanVar()
        same_path_cb = ttk.Checkbutton(cb_frame, text="Stay within starting path",
                                        variable=self.crawl_same_path_var)
        same_path_cb.pack(anchor="w")
        tip(same_path_cb,
            "Only archive pages whose URL path starts with the same\n"
            "folder as your starting URL. Ignores links to other\n"
            "sections of the site.\n\n"
            "EXAMPLE:\n"
            "  Starting URL: bitbuilt.net/forums/console-modding-101\n"
            "  With this ON:  only archives /forums/console-modding-101/*\n"
            "  With this OFF: archives all of bitbuilt.net\n\n"
            "RECOMMENDED: Turn ON when you only want one section of a\n"
            "site (e.g. one forum board), not the entire domain.")

        self.crawl_robots_var = tk.BooleanVar(value=True)
        robots_cb = ttk.Checkbutton(cb_frame, text="Respect robots.txt",
                                     variable=self.crawl_robots_var)
        robots_cb.pack(anchor="w", pady=(4, 0))
        tip(robots_cb,
            "Check the site's robots.txt and skip any URLs it says\n"
            "should not be crawled.\n\n"
            "If the starting URL itself is blocked by robots.txt, a\n"
            "popup will ask whether you want to proceed anyway.\n\n"
            "RECOMMENDED: Leave ON as a courtesy to site owners.\n"
            "Uncheck only if you know the content is public and the\n"
            "robots.txt restriction is overly broad.")

        self.crawl_subdomains_var = tk.BooleanVar()
        subdomains_cb = ttk.Checkbutton(cb_frame, text="Include subdomains",
                                         variable=self.crawl_subdomains_var)
        subdomains_cb.pack(anchor="w", pady=(4, 0))
        tip(subdomains_cb,
            "Follow and archive links to subdomains of the same site.\n\n"
            "EXAMPLE:\n"
            "  Archiving example.com with this ON also follows:\n"
            "  forum.example.com, wiki.example.com, cdn.example.com\n\n"
            "RECOMMENDED: Leave OFF unless the site splits content\n"
            "across subdomains you specifically want. Leaving ON on a\n"
            "large site can dramatically increase the page count.")

        # Start crawl button
        crawl_btn_row = tk.Frame(card, bg=BG2)
        crawl_btn_row.pack(fill="x", padx=10, pady=(8, 10))
        self.crawl_btn = ttk.Button(crawl_btn_row, text="🌐  START CRAWL",
                                    style="Start.TButton", command=self._start_crawl)
        self.crawl_btn.pack(side="left")
        tip(self.crawl_btn,
            "Start crawling and archiving the website from the URL above.\n\n"
            "WHAT IT DOES:\n"
            "  1. Fetches each page and extracts all links\n"
            "  2. Detects pagination (page-1, page-2…) and exhausts\n"
            "     the entire series before branching to other links\n"
            "  3. Archives each page via SPN2 using your account keys\n"
            "  4. Handles JS-heavy sites (Google Docs, Reddit, etc.)\n"
            "     via export APIs and mirrors automatically\n"
            "  5. Shows all discovered URLs in the checklist in real time\n\n"
            "RECOMMENDED DELAY for crawl mode: 10–15 seconds\n"
            "  (higher than normal mode since you're sending many more\n"
            "  requests — lower delays risk hitting rate limits quickly)\n\n"
            "Progress is fully saved. You can pause, stop, and resume\n"
            "at any time without losing work.")

        self.crawl_status_var = tk.StringVar(value="")
        tk.Label(crawl_btn_row, textvariable=self.crawl_status_var,
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(side="left", padx=(10, 0))

        tk.Frame(card, bg=BG2, height=2).pack()

        # ── ACCOUNT ───────────────────────────────────────────────────────────
        self._section(parent, "ACCOUNT")
        card = self._card(parent)
        tk.Label(card, text="Access Key", bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=10, pady=(8, 2))
        self.access_var = tk.StringVar()
        access_entry = ttk.Entry(card, textvariable=self.access_var, font=FONT_MONO)
        access_entry.pack(fill="x", padx=10, pady=(0, 6))
        tip(access_entry, "Your Internet Archive S3 Access Key.\nGet it at: archive.org/account/s3.php\n\nRequired for authenticated saves, which give you higher rate limits and priority in the save queue.")

        tk.Label(card, text="Secret Key", bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=10, pady=(0, 2))
        self.secret_var = tk.StringVar()
        secret_entry = ttk.Entry(card, textvariable=self.secret_var, font=FONT_MONO, show="•")
        secret_entry.pack(fill="x", padx=10, pady=(0, 4))
        tip(secret_entry, "Your Internet Archive S3 Secret Key.\nGet it at: archive.org/account/s3.php\n\nKept hidden. Never share this with anyone.")

        tk.Label(card, text="archive.org/account/s3.php",
                 bg=BG2, fg=TEXT_DIM, font=("Segoe UI", 8)).pack(anchor="w", padx=10, pady=(0, 8))

        # ── CAPTURE ───────────────────────────────────────────────────────────
        self._section(parent, "CAPTURE")
        card = self._card(parent)
        self.cap_all_var        = tk.BooleanVar(value=True)
        self.cap_outlinks_var   = tk.BooleanVar()
        self.cap_screenshot_var = tk.BooleanVar()

        # Refresh the checklist whenever either capture option toggles
        self.cap_outlinks_var.trace_add("write",   lambda *_: self._refresh_tree())
        self.cap_screenshot_var.trace_add("write",  lambda *_: self._refresh_tree())

        capture_tips = {
            "Capture embedded resources (CSS, images, JS)":
                "Saves the CSS, images, fonts, and JavaScript that the\n"
                "page needs to display correctly.\n\n"
                "RECOMMENDED: Always leave ON.\n"
                "Without this, archived pages will look broken — missing\n"
                "images, unstyled text, broken layouts.",
            "Capture outlinks  (archive all linked pages)":
                "Also archives every URL that is linked to on each page,\n"
                "one level deep.\n\n"
                "EXAMPLE: if archiving a forum index, each linked thread\n"
                "will also be saved automatically.\n\n"
                "WARNING: This multiplies your request count significantly.\n"
                "  • A page with 50 links = 50 extra saves\n"
                "  • Increase delay to 15–20s when using this option\n"
                "  • Increases chance of rate limiting\n\n"
                "RECOMMENDED: Use for index/hub pages where you want\n"
                "all linked content saved. Not recommended for large\n"
                "crawls — the crawler already handles link discovery.",
            "Capture screenshot":
                "Saves a visual screenshot of the page as it appears in\n"
                "a browser at capture time.\n\n"
                "Stored as a .jpg in the Wayback Machine alongside the\n"
                "full HTML archive. Useful as a quick visual record.\n\n"
                "RECOMMENDED: Optional. Adds a small amount of extra\n"
                "processing time per URL but doesn't count heavily\n"
                "against your rate limit quota.",
        }
        for label, var in [
            ("Capture embedded resources (CSS, images, JS)", self.cap_all_var),
            ("Capture outlinks  (archive all linked pages)",  self.cap_outlinks_var),
            ("Capture screenshot",                            self.cap_screenshot_var),
        ]:
            cb = ttk.Checkbutton(card, text=label, variable=var)
            cb.pack(anchor="w", padx=10, pady=(6, 0))
            tip(cb, capture_tips[label])
        tk.Frame(card, bg=BG2, height=8).pack()

        # ── ADVANCED OPTIONS ──────────────────────────────────────────────────
        self._section(parent, "ADVANCED OPTIONS")
        card = self._card(parent)
        self.force_get_var    = tk.BooleanVar()
        self.skip_first_var   = tk.BooleanVar()
        self.delay_avail_var  = tk.BooleanVar()
        self.email_result_var = tk.BooleanVar()
        self.save_errors_var  = tk.BooleanVar(value=True)

        adv_tips = {
            "Force GET request":
                "Forces the archiver to use a GET request instead of the\n"
                "default HEAD request when checking the page.\n\n"
                "WHEN TO USE: If pages are failing or not saving correctly.\n"
                "Some sites don't respond to HEAD requests properly — a\n"
                "GET forces the full page to be fetched.\n\n"
                "RECOMMENDED: Leave OFF unless you're seeing failures.",
            "Skip if this would be first archive":
                "Skips saving a URL if it has never been archived on the\n"
                "Wayback Machine before (i.e. no existing snapshots).\n\n"
                "WHEN TO USE: When you only want to update and refresh\n"
                "existing snapshots, not create first-time captures.\n\n"
                "RECOMMENDED: Leave OFF for most use cases. Turn ON\n"
                "if you're doing a maintenance pass on an already-archived\n"
                "site and don't want to create new first-time captures.",
            "Delay Wayback availability":
                "Delays the newly saved page from appearing in Wayback\n"
                "Machine search results for a short time after capture.\n\n"
                "WHEN TO USE: If you want to capture a page privately\n"
                "before it shows up in public search results.\n\n"
                "RECOMMENDED: Leave OFF unless you have a specific reason.",
            "Email me when each job completes":
                "Internet Archive sends you an email notification when\n"
                "each individual save job finishes processing.\n\n"
                "Requires a verified email address on your IA account.\n\n"
                "WARNING: With large URL lists this will flood your inbox.\n"
                "RECOMMENDED: Only enable for small targeted batches.",
            "Save error pages (4xx/5xx)":
                "If the target page returns an error response (e.g. 404\n"
                "Not Found, 500 Server Error), save that error response\n"
                "as an archive anyway.\n\n"
                "WHEN TO USE: Useful for documenting that a page existed\n"
                "at a URL but is now gone or broken — the 404 itself\n"
                "becomes a historical record.\n\n"
                "RECOMMENDED: Leave ON when archiving pages that might\n"
                "be deleted or going offline soon.",
        }
        for label, var in [
            ("Force GET request",                   self.force_get_var),
            ("Skip if this would be first archive", self.skip_first_var),
            ("Delay Wayback availability",          self.delay_avail_var),
            ("Email me when each job completes",    self.email_result_var),
            ("Save error pages (4xx/5xx)",          self.save_errors_var),
        ]:
            cb = ttk.Checkbutton(card, text=label, variable=var)
            cb.pack(anchor="w", padx=10, pady=(5, 0))
            tip(cb, adv_tips[label])
        tk.Frame(card, bg=BG2, height=4).pack()

        # If not archived within dropdown
        row = tk.Frame(card, bg=BG2)
        row.pack(fill="x", padx=10, pady=(6, 0))
        lbl_ifnot = tk.Label(row, text="Only save if not archived within",
                             bg=BG2, fg=TEXT, font=FONT_SM)
        lbl_ifnot.pack(side="left")
        tip(lbl_ifnot, "Skip saving a URL if it already has a Wayback snapshot\n"
                       "newer than this threshold.\n\n"
                       "\"Always\" means save regardless of when it was last archived.")
        self.if_not_var = tk.StringVar(value="Always")
        if_not_cb = ttk.Combobox(row, textvariable=self.if_not_var, width=10,
                                 state="readonly", font=FONT_SM,
                                 values=["Always", "1 day", "3 days", "7 days", "30 days"])
        if_not_cb.pack(side="right")
        tip(if_not_cb, "Skip saving a URL if it already has a Wayback snapshot\n"
                       "newer than this threshold.\n\n"
                       "\"Always\" means save regardless of when it was last archived.")

        # JS timeout spinner
        row2 = tk.Frame(card, bg=BG2)
        row2.pack(fill="x", padx=10, pady=(6, 0))
        lbl_js = tk.Label(row2, text="JS behaviour timeout (seconds)",
                          bg=BG2, fg=TEXT, font=FONT_SM)
        lbl_js.pack(side="left")
        tip(lbl_js, "How many seconds to wait for JavaScript to finish\n"
                    "executing on the page before taking the snapshot.\n\n"
                    "Set to 0 to use the default. Increase for heavy JS pages\n"
                    "like single-page apps or infinite scroll forums.")
        self.js_timeout_var = tk.IntVar(value=0)
        js_spin = ttk.Spinbox(row2, from_=0, to=30, textvariable=self.js_timeout_var,
                              width=5, font=FONT_SM)
        js_spin.pack(side="right")
        tip(js_spin, "How many seconds to wait for JavaScript to finish\n"
                     "executing on the page before taking the snapshot.\n\n"
                     "Set to 0 to use the default. Increase for heavy JS pages\n"
                     "like single-page apps or infinite scroll forums.")

        # Cookie entry
        tk.Label(card, text="Capture cookie (optional)",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=10, pady=(8, 2))
        self.cookie_var = tk.StringVar()
        cookie_entry = ttk.Entry(card, textvariable=self.cookie_var, font=FONT_MONO)
        cookie_entry.pack(fill="x", padx=10, pady=(0, 4))
        tip(cookie_entry, "Send a browser cookie with the capture request.\n"
                          "Use this to archive pages that require you to be\n"
                          "logged in to see the content.\n\n"
                          "Format:  name=value\n"
                          "Example: session_id=abc123")

        # User agent entry
        tk.Label(card, text="Custom user agent (optional)",
                 bg=BG2, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w", padx=10, pady=(4, 2))
        self.ua_var = tk.StringVar()
        ua_entry = ttk.Entry(card, textvariable=self.ua_var, font=FONT_MONO)
        ua_entry.pack(fill="x", padx=10, pady=(0, 8))
        tip(ua_entry, "Override the browser user-agent string sent to the\n"
                      "target website during capture. Leave blank to use\n"
                      "the Internet Archive's default.\n\n"
                      "Useful if a site blocks IA's crawler but allows browsers.")

        # ── TIMING ────────────────────────────────────────────────────────────
        self._section(parent, "TIMING")
        card = self._card(parent)
        self.delay_var             = tk.IntVar(value=8)
        self.retries_var           = tk.IntVar(value=4)
        self.backoff_var           = tk.IntVar(value=30)
        self.rate_limit_backoff_var = tk.IntVar(value=60)
        self.reset_var             = tk.BooleanVar()

        timing_tips = {
            "Delay between requests (sec)":
                "Seconds to wait between submitting each URL to Wayback Machine.\n\n"
                "RECOMMENDED:\n"
                "  • URL list mode (normal):         8–10s\n"
                "  • URL list with outlinks on:      15–20s\n"
                "  • Crawl mode (small site):        10–15s\n"
                "  • Crawl mode (large site):        15–30s\n"
                "  • If hitting rate limits often:   20–30s\n\n"
                "Lower = faster but risks rate limiting.\n"
                "Higher = slower but more reliable for large batches.\n"
                "IA's authenticated SPN2 allows faster rates than anonymous.",
            "Max retries per URL":
                "How many times to retry a URL after a failure before\n"
                "giving up and marking it as failed.\n\n"
                "RETRY SCHEDULE (backoff increases each attempt):\n"
                "  Attempt 1 → fails → wait 30s\n"
                "  Attempt 2 → fails → wait 60s\n"
                "  Attempt 3 → fails → wait 90s\n"
                "  ... capped at 300s maximum\n\n"
                "RECOMMENDED: 4–5 retries for normal use.\n"
                "Failed URLs are saved to state and retried next session.",
            "Backoff on failure (sec)":
                "Starting wait time when a URL submission fails.\n"
                "Increases by this amount with each retry attempt.\n\n"
                "SCHEDULE (default 30s):\n"
                "  Attempt 1 fails → wait 30s\n"
                "  Attempt 2 fails → wait 60s\n"
                "  Attempt 3 fails → wait 90s\n"
                "  Attempt 4 fails → wait 120s\n"
                "  ... capped at 300s maximum\n\n"
                "RECOMMENDED: 30s. Increase to 60s+ if IA is having\n"
                "repeated server errors.",
            "Rate limit wait (sec)":
                "Starting wait when IA rate-limits you. Doubles each time\n"
                "you hit a rate limit in the same session.\n\n"
                "SCHEDULE (default 60s):\n"
                "  1st rate limit hit → wait 60s\n"
                "  2nd rate limit hit → wait 120s\n"
                "  3rd rate limit hit → wait 240s\n"
                "  4th+ rate limit hit → wait 300s (max)\n\n"
                "A popup appears with options when rate limited:\n"
                "  • Auto-resume after countdown\n"
                "  • Add 5s to your delay to prevent future hits\n"
                "  • Resume now or stop\n\n"
                "RECOMMENDED: 60s. Increase to 120s if you're hitting\n"
                "rate limits very frequently.",
        }
        for label, var, lo, hi in [
            ("Delay between requests (sec)", self.delay_var,              1, 120),
            ("Max retries per URL",          self.retries_var,            1, 20),
            ("Backoff on failure (sec)",     self.backoff_var,            5, 120),
            ("Rate limit wait (sec)",        self.rate_limit_backoff_var, 10, 300),
        ]:
            r = tk.Frame(card, bg=BG2)
            r.pack(fill="x", padx=10, pady=(6, 0))
            lbl = tk.Label(r, text=label, bg=BG2, fg=TEXT, font=FONT_SM)
            lbl.pack(side="left")
            tip(lbl, timing_tips[label])
            spin = ttk.Spinbox(r, from_=lo, to=hi, textvariable=var, width=5, font=FONT_SM)
            spin.pack(side="right")
            tip(spin, timing_tips[label])

        reset_cb = ttk.Checkbutton(card, text="Reset — ignore previous progress",
                                   variable=self.reset_var)
        reset_cb.pack(anchor="w", padx=10, pady=(8, 6))
        tip(reset_cb, "Clears all saved progress and starts the entire\n"
                      "URL list from scratch on the next run.\n\n"
                      "Warning: you will lose track of which URLs were\n"
                      "already successfully archived.")

    def _build_right(self, parent):
        self._section(parent, "URL CHECKLIST")
        tree_frame = tk.Frame(parent, bg=BG2)
        tree_frame.pack(fill="both", expand=True)

        cols = ("url", "page", "outlinks", "screenshot", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("url",        text="URL")
        self.tree.heading("page",       text="Page")
        self.tree.heading("outlinks",   text="Outlinks")
        self.tree.heading("screenshot", text="Screenshot")
        self.tree.heading("status",     text="Status")
        self.tree.column("url",        width=320, anchor="w")
        self.tree.column("page",       width=55,  anchor="center")
        self.tree.column("outlinks",   width=68,  anchor="center")
        self.tree.column("screenshot", width=80,  anchor="center")
        self.tree.column("status",     width=150, anchor="w")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)

        # Wrap the vertical scrollbar command to detect user-initiated scrolling
        def _tree_vsb_command(*args):
            self._tree_user_scrolled = True
            self.tree.yview(*args)

        # Detect when user scrolls back to bottom — re-enable auto-follow
        def _tree_yview_changed(*args):
            vsb.set(*args)
            try:
                pos = self.tree.yview()
                if pos[1] >= 0.999:
                    self._tree_user_scrolled = False   # back at bottom, resume auto-follow
            except Exception:
                pass

        vsb.config(command=_tree_vsb_command)
        self.tree.configure(yscrollcommand=_tree_yview_changed, xscrollcommand=hsb.set)

        # Mouse wheel on tree also counts as user scroll
        def _tree_wheel(e):
            self._tree_user_scrolled = True
        self.tree.bind("<MouseWheel>", _tree_wheel, add="+")
        self.tree.bind("<Button-4>",   _tree_wheel, add="+")   # Linux scroll up
        self.tree.bind("<Button-5>",   _tree_wheel, add="+")   # Linux scroll down
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        for tag, color in [("saved", SUCCESS), ("failed", ERROR), ("skipped", SKIP),
                           ("active", WARNING), ("pending", TEXT_DIM), ("outage", ERROR)]:
            self.tree.tag_configure(tag, foreground=color)

        tb = tk.Frame(parent, bg=BG)
        tb.pack(fill="x", pady=(6, 0))
        ttk.Button(tb, text="Reload file",     style="Sm.TButton", command=self._reload_urls).pack(side="left")
        ttk.Button(tb, text="Clear selection", style="Sm.TButton", command=self._clear_selection).pack(side="left", padx=(4, 0))

        # Stats row — each segment is its own label for independent colouring
        stats_frame = tk.Frame(tb, bg=BG)
        stats_frame.pack(side="right")

        # ℹ button — opens the stats detail popup
        info_btn = tk.Button(stats_frame, text="?", bg=BG, fg=TEXT_DIM,
                             relief="flat", font=("Segoe UI", 10),
                             cursor="hand2", activebackground=BG,
                             activeforeground=ACCENT, bd=0,
                             command=self._open_stats_popup)
        info_btn.pack(side="left", padx=(0, 4))
        tip(info_btn, "Show detailed breakdown of URL statuses")

        # Total URLs  (dim)
        self._stat_total_var = tk.StringVar(value="")
        tk.Label(stats_frame, textvariable=self._stat_total_var,
                 bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left")

        # Separator
        tk.Label(stats_frame, text="  ·  ", bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left")

        # Archived by us  (green)
        self._stat_archived_var = tk.StringVar(value="")
        tk.Label(stats_frame, textvariable=self._stat_archived_var,
                 bg=BG, fg=SUCCESS, font=("Segoe UI Semibold", 9)).pack(side="left")

        # Already existed (blue/skip colour) — only shown when > 0
        self._stat_existing_var = tk.StringVar(value="")
        self._stat_existing_lbl = tk.Label(stats_frame, textvariable=self._stat_existing_var,
                                           bg=BG, fg=SKIP, font=("Segoe UI Semibold", 9))
        self._stat_existing_lbl.pack(side="left")

        # Separator before pending
        tk.Label(stats_frame, text="  ·  ", bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left")

        # Pending  (dim)
        self._stat_pending_var = tk.StringVar(value="")
        tk.Label(stats_frame, textvariable=self._stat_pending_var,
                 bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left")

        self._section(parent, "LOG")
        log_tb = tk.Frame(parent, bg=BG)
        log_tb.pack(fill="x")
        ttk.Button(log_tb, text="Clear log", style="Sm.TButton", command=self._clear_log).pack(side="right")

        self.log_box = scrolledtext.ScrolledText(
            parent, height=9, bg=BG2, fg=TEXT, font=FONT_MONO,
            relief="flat", bd=0, insertbackground=TEXT, wrap="word", state="disabled"
        )
        self.log_box.pack(fill="both", expand=False, pady=(4, 0))
        for tag, color in [("success", SUCCESS), ("error", ERROR),
                           ("warning", WARNING), ("dim", TEXT_DIM), ("info", TEXT)]:
            self.log_box.tag_config(tag, foreground=color)

    def _open_stats_popup(self):
        """Show a detailed breakdown of URL statuses with explanations."""
        c = self._stats_counts
        win = tk.Toplevel(self.root)
        win.title("URL Statistics")
        win.configure(bg=BG)
        win.resizable(False, False)

        win.update_idletasks()
        px = self.root.winfo_x() + self.root.winfo_width()  - 460
        py = self.root.winfo_y() + self.root.winfo_height() - 60
        win.geometry(f"450x560+{max(0, px)}+{max(0, py - 560)}")

        # Header
        hdr = tk.Frame(win, bg=BG2, padx=16, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="URL STATISTICS", bg=BG2, fg=TEXT,
                 font=("Segoe UI Semibold", 11)).pack(side="left")
        tk.Button(hdr, text="✕", bg=BG2, fg=TEXT_DIM, relief="flat",
                  font=FONT_SM, cursor="hand2",
                  activebackground=BG3, activeforeground=TEXT,
                  command=win.destroy).pack(side="right")
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(win, bg=BG, padx=16, pady=12)
        body.pack(fill="both", expand=True)

        STAT_INFO = [
            ("Total URLs",      c["total"],      BG3,
             "Every URL in your loaded text file.\n"
             "This is the full list the archiver works through."),

            ("Archived by you", c["archived"],   SUCCESS,
             "Pages this tool successfully saved during any session.\n"
             "These have a recorded archive.org URL saved in the\n"
             "state file (wayback_state.json) on your computer.\n\n"
             "✓ shown in the Page column of the checklist."),

            ("Pre-existing",    c["existing"],   SKIP,
             "Pages already on the Wayback Machine before you\n"
             "started archiving, or marked done in a previous\n"
             "session without an archive URL being recorded.\n\n"
             "These are counted as done but were not saved by\n"
             "this tool in any tracked session."),

            ("Partial",         c["partial"],    WARNING,
             "The page itself was archived, but one or more of\n"
             "the extra options you have checked (Outlinks or\n"
             "Screenshot) haven't been captured yet.\n\n"
             "Run the archiver again with those options still\n"
             "checked to complete these entries."),

            ("Pending",         c["pending"],    TEXT_DIM,
             "Pages not yet archived at all.\n"
             "These will be processed on the next run.\n\n"
             "If this number isn't decreasing during a run,\n"
             "check the log for errors on those URLs."),
        ]

        for i, (label, value, color, explanation) in enumerate(STAT_INFO):
            if i == 1:
                tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(4, 8))

            row = tk.Frame(body, bg=BG)
            row.pack(fill="x", pady=(0, 6))

            # Coloured badge
            badge = tk.Frame(row, bg=color, padx=7, pady=3)
            badge.pack(side="left", anchor="n")
            badge_fg = "#ffffff" if color != BG3 else TEXT
            tk.Label(badge, text=str(value), bg=color, fg=badge_fg,
                     font=("Segoe UI Semibold", 12)).pack()

            # Label, explanation, and ? toggle
            right = tk.Frame(row, bg=BG)
            right.pack(side="left", fill="x", expand=True, padx=(10, 0))

            top_row = tk.Frame(right, bg=BG)
            top_row.pack(fill="x")
            tk.Label(top_row, text=label, bg=BG, fg=TEXT,
                     font=FONT_BOLD).pack(side="left")

            # ? button that toggles the explanation
            exp_var  = tk.BooleanVar(value=False)
            exp_lbl  = tk.Label(right, text=explanation, bg=BG2, fg=TEXT_DIM,
                                font=("Segoe UI", 8), justify="left",
                                wraplength=340, padx=8, pady=6)

            def _toggle(v=exp_var, lbl=exp_lbl):
                if v.get():
                    lbl.pack(fill="x", pady=(3, 0))
                else:
                    lbl.pack_forget()

            q_btn = tk.Button(top_row, text="?", bg=BG3, fg=TEXT_DIM,
                              relief="flat", font=("Segoe UI", 8),
                              cursor="hand2", padx=5, pady=1,
                              activebackground=BG4, activeforeground=TEXT,
                              command=lambda v=exp_var, fn=_toggle: (v.set(not v.get()), fn()))
            q_btn.pack(side="right")
            tip(q_btn, "Click to show/hide explanation")

        tk.Frame(body, bg=BORDER, height=1).pack(fill="x", pady=(8, 6))

        # Coverage bar
        bar_frame = tk.Frame(body, bg=BG)
        bar_frame.pack(fill="x")
        tk.Label(bar_frame, text="COVERAGE", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w")

        bar_canvas = tk.Canvas(bar_frame, height=12, bg=BG3,
                               highlightthickness=0, bd=0)
        bar_canvas.pack(fill="x", pady=(3, 0))

        def draw_bar(event=None):
            bar_canvas.delete("all")
            w   = bar_canvas.winfo_width()
            tot = max(c["total"], 1)
            x   = 0
            for count, color in [(c["archived"], SUCCESS), (c["existing"], SKIP), (c["partial"], WARNING)]:
                seg_w = int(w * count / tot)
                if seg_w > 0:
                    bar_canvas.create_rectangle(x, 0, x + seg_w, 12, fill=color, outline="")
                    x += seg_w

        bar_canvas.bind("<Configure>", draw_bar)
        bar_canvas.after(50, draw_bar)

        # Pct label
        done = c["archived"] + c["existing"]
        pct  = int(done / max(c["total"], 1) * 100)
        tk.Label(body, text=f"{pct}% of URLs fully done",
                 bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(anchor="e", pady=(4, 0))

        # Close
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")
        btn_row = tk.Frame(win, bg=BG, pady=10)
        btn_row.pack()
        tk.Button(btn_row, text="Close", bg=BG3, fg=TEXT, relief="flat",
                  font=FONT_BOLD, cursor="hand2",
                  activebackground=BG4, activeforeground=TEXT,
                  padx=20, pady=7, command=win.destroy).pack()

    def _build_bottom(self):
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=18, pady=10)

        self.start_btn = ttk.Button(bar, text="▶  START", style="Start.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn  = ttk.Button(bar, text="■  STOP",  style="Stop.TButton",  command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        self.pause_btn = ttk.Button(bar, text="⏸  PAUSE", style="Sm.TButton",
                                    command=self._toggle_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=(6, 0))
        tip(self.pause_btn, "Pause after the current URL finishes.\nClick again to resume.")

        # ── Sound controls (right side, before progress) ──────────────────────
        snd_frame = tk.Frame(bar, bg=BG)
        snd_frame.pack(side="right", padx=(0, 0))

        # Sound settings button
        snd_btn = tk.Button(snd_frame, text="🔊", bg=BG, fg=TEXT_DIM,
                            relief="flat", font=("Segoe UI", 11),
                            cursor="hand2", activebackground=BG,
                            activeforeground=TEXT, bd=0,
                            command=self._open_sound_settings)
        snd_btn.pack(side="left")
        tip(snd_btn, "Open sound settings — adjust volume for each event\nor disable sounds entirely.")

        # Master volume label
        tk.Label(snd_frame, text="Vol", bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left", padx=(4, 2))

        # Master volume slider
        def _on_master(v):
            self.sounds.master_vol = int(float(v))
            self._mvol_lbl.config(text=f"{int(float(v))}%")

        self._mvol_slider = tk.Scale(
            snd_frame, from_=0, to=100, orient="horizontal",
            variable=self.master_vol_var, length=90,
            bg=BG, fg=TEXT, troughcolor=BG3,
            highlightthickness=0, bd=0,
            activebackground=ACCENT, sliderrelief="flat",
            showvalue=False, command=_on_master
        )
        self._mvol_slider.pack(side="left")
        tip(self._mvol_slider, "Master volume — scales all sounds proportionally.")

        self._mvol_lbl = tk.Label(snd_frame, text=f"{self.master_vol_var.get()}%",
                                  bg=BG, fg=TEXT_DIM, font=FONT_SM, width=4)
        self._mvol_lbl.pack(side="left")

        # Divider
        tk.Frame(snd_frame, bg=BORDER, width=1).pack(side="left", fill="y", padx=(8, 0))

        # ── Progress ──────────────────────────────────────────────────────────
        prog_frame = tk.Frame(bar, bg=BG)
        prog_frame.pack(side="right", fill="x", expand=True, padx=(12, 8))
        stat_row = tk.Frame(prog_frame, bg=BG)
        stat_row.pack(fill="x")
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(stat_row, textvariable=self.status_var, bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(side="left")
        self.count_var = tk.StringVar(value="")
        tk.Label(stat_row, textvariable=self.count_var,  bg=BG, fg=ACCENT, font=("Segoe UI Semibold", 9)).pack(side="right")
        self.progress = AnimatedProgressBar(prog_frame, height=7)
        self.progress.pack(fill="x", pady=(4, 0))

    def _open_sound_settings(self):
        SoundSettingsDialog(self.root, self.sounds, self.master_vol_var)

    def _open_update_dialog(self):
        UpdateDialog(self.root, VERSION)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, parent, text):
        tk.Label(parent, text=text, bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w", pady=(10, 2))

    def _card(self, parent):
        f = tk.Frame(parent, bg=BG2)
        f.pack(fill="x")
        return f

    def _log(self, msg, tag="info"):
        def _w():
            self.log_box.config(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"{ts}  {msg}\n", tag)
            # Only auto-scroll if the user is already near the bottom
            # (within the last 5% of content) — don't interrupt manual scrolling
            pos = self.log_box.yview()
            if pos[1] >= 0.95:
                self.log_box.see("end")
            self.log_box.config(state="disabled")
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{ts}  {msg}\n")
        self.root.after(0, _w)

    def _clear_log(self):
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select URL list",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.url_var.set(path)

    def _on_file_change(self):
        self.root.after(300, self._reload_urls)

    def _reload_urls(self):
        path = self.url_var.get().strip()
        if not path or not Path(path).exists():
            return
        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            self.all_urls = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
            self._refresh_tree()
            threading.Thread(target=self._write_url_logs, daemon=True).start()
        except Exception as e:
            self._log(f"Could not read file: {e}", "error")

    def _refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        want_outlinks   = self.cap_outlinks_var.get()
        want_screenshot = self.cap_screenshot_var.get()

        count_archived = 0   # archived by this tool (has archive_url in state)
        count_existing = 0   # already done but no archive_url (pre-existing on Wayback)
        count_partial  = 0   # page done, outlinks/screenshot still needed
        count_pending  = 0   # not yet archived at all
        count_failed   = 0   # marked as failed in state

        for url in self.all_urls:
            entry = self.state["urls"].get(url, {})
            pg = entry.get("page",       False)
            ol = entry.get("outlinks",   False)
            ss = entry.get("screenshot", False)

            page_sym = "✓" if pg else "—"
            ol_sym   = ("✓" if ol else "·") if want_outlinks   else "—"
            ss_sym   = ("✓" if ss else "·") if want_screenshot else "—"

            needs_page = not pg
            needs_ol   = want_outlinks   and not ol
            needs_ss   = want_screenshot and not ss

            if not needs_page and not needs_ol and not needs_ss:
                status = "Done"
                tag    = "saved"
                if entry.get("archive_url"):
                    count_archived += 1
                else:
                    count_existing += 1
            elif pg and (needs_ol or needs_ss):
                status = "Partial"
                tag    = "skipped"
                count_partial += 1
            else:
                status = "Pending"
                tag    = "pending"
                count_pending += 1

            short = url if len(url) <= 55 else url[:52] + "..."
            self.tree.insert("", "end", iid=url,
                             values=(short, page_sym, ol_sym, ss_sym, status), tags=(tag,))

        total = len(self.all_urls)
        # Save counts so the stats popup can read them
        self._stats_counts = {
            "total":    total,
            "archived": count_archived,
            "existing": count_existing,
            "partial":  count_partial,
            "pending":  count_pending,
        }

        self._stat_total_var.set(f"{total} URL{'s' if total != 1 else ''}")
        self._update_stat_labels(count_archived, count_existing,
                                 count_partial, count_pending)

    def _write_url_logs(self):
        """Write all three URL log files from current state. Thread-safe."""
        write_url_logs(
            self.state, self.all_urls,
            want_outlinks=self.cap_outlinks_var.get(),
            want_screenshot=self.cap_screenshot_var.get(),
        )

    def _update_stat_labels(self, archived, existing, partial, pending):
        """Update the coloured stat labels. Safe to call from any thread via root.after."""
        def _u():
            self._stats_counts.update({
                "archived": archived, "existing": existing,
                "partial": partial,   "pending":  pending,
            })
            self._stat_archived_var.set(f"{archived} archived")
            if existing > 0:
                self._stat_existing_var.set(f"  +{existing} pre-existing")
                self._stat_existing_lbl.pack(side="left")
            else:
                self._stat_existing_var.set("")
                self._stat_existing_lbl.pack_forget()
            self._stat_pending_var.set(f"{partial + pending} pending")
            self.root.update_idletasks()
        self.root.after(0, _u)

    def _increment_stat(self, key, delta=1):
        """Recompute all stats from actual state after each URL result.
        More reliable than maintaining deltas which can drift out of sync."""
        def _u():
            want_ol = self.cap_outlinks_var.get()
            want_ss = self.cap_screenshot_var.get()
            total = archived = existing = partial = pending = 0
            for url in self.all_urls:
                entry      = self.state["urls"].get(url, {})
                pg         = entry.get("page",       False)
                ol         = entry.get("outlinks",   False)
                ss         = entry.get("screenshot", False)
                needs_page = not pg
                needs_ol   = want_ol and not ol
                needs_ss   = want_ss and not ss
                total += 1
                if not needs_page and not needs_ol and not needs_ss:
                    if entry.get("archive_url"):
                        archived += 1
                    else:
                        existing += 1
                elif pg and (needs_ol or needs_ss):
                    partial += 1
                else:
                    pending += 1
            self._stats_counts = {
                "total": total, "archived": archived,
                "existing": existing, "partial": partial, "pending": pending,
            }
            self._stat_total_var.set(f"{total} URL{'s' if total != 1 else ''}")
            self._update_stat_labels(archived, existing, partial, pending)
        self.root.after(0, _u)

    def _clear_selection(self):
        self.tree.selection_remove(self.tree.selection())

    def _tree_set_status(self, url, status, tag):
        def _u():
            if self.tree.exists(url):
                vals = list(self.tree.item(url, "values"))
                vals[4] = status
                self.tree.item(url, values=vals, tags=(tag,))
                # Only scroll to the active row if user hasn't manually scrolled away
                if not self._tree_user_scrolled:
                    self.tree.see(url)
        self.root.after(0, _u)

    def _tree_set_check(self, url, col, symbol):
        col_idx = {"page": 1, "outlinks": 2, "screenshot": 3}[col]
        def _u():
            if self.tree.exists(url):
                vals = list(self.tree.item(url, "values"))
                vals[col_idx] = symbol
                self.tree.item(url, values=vals)
        self.root.after(0, _u)

    # ── Checkpoint resume notice ──────────────────────────────────────────────

    # ── Spinner ───────────────────────────────────────────────────────────────

    def _start_spinner(self, url):
        """Start animating the status cell for the given URL row."""
        self._stop_spinner_internal()
        self._spinner_url = url
        self._spinner_idx = 0
        # Set the initial frame synchronously on the tree directly
        # (not via after()) so _tick_spinner sees "active" tag immediately
        if self.tree.exists(url):
            vals = list(self.tree.item(url, "values"))
            vals[4] = f"{self._SPINNER_FRAMES[0]} Archiving"
            self.tree.item(url, values=vals, tags=("active",))
        self._tick_spinner()

    def _tick_spinner(self):
        if not self._spinner_url:
            return
        url = self._spinner_url
        if self.tree.exists(url):
            current_tag = self.tree.item(url, "tags")
            # Only stop on truly final states — not "pending" or "skipped"
            # which can appear before archiving starts
            if current_tag and current_tag[0] in ("saved", "failed", "outage"):
                self._spinner_url = None
                self._spinner_job = None
                return
            frame = self._SPINNER_FRAMES[self._spinner_idx % len(self._SPINNER_FRAMES)]
            vals = list(self.tree.item(url, "values"))
            vals[4] = f"{frame} Archiving"
            self.tree.item(url, values=vals, tags=("active",))
        self._spinner_idx += 1
        self._spinner_job = self.root.after(self._SPINNER_MS, self._tick_spinner)

    def _stop_spinner_internal(self):
        if self._spinner_job:
            self.root.after_cancel(self._spinner_job)
            self._spinner_job = None
        self._spinner_url = None

    def _stop_spinner(self, url, status, tag):
        """Stop the spinner and set a final status on the row."""
        self._stop_spinner_internal()
        self._tree_set_status(url, status, tag)


    def _check_resume_checkpoint(self):
        cp = self.state.get("checkpoint")
        if not cp:
            return
        url     = cp.get("url", "?")
        step    = cp.get("step", "?")
        started = cp.get("started", "")[:19].replace("T", " ")
        self._log(f"Previous session was interrupted!", "warning")
        self._log(f"  Last URL : {url}", "warning")
        self._log(f"  Step     : {step}", "warning")
        self._log(f"  At       : {started}", "warning")
        self._log(f"  Load your URL file and press START to resume from where it left off.", "dim")

    # ── Outage handling ───────────────────────────────────────────────────────

    def _show_outage_popup(self, detail, session):
        def _do_stop():
            self.stop_flag = True
            self._finish()

        def _do_retry():
            self._server_err_count = 0
            self._rate_wait_event.set()

        def _open():
            if self._outage_popup and self._outage_popup.winfo_exists():
                return
            cp = self.state.get("checkpoint")
            self._outage_popup = OutagePopup(
                self.root, detail, cp, _do_stop, _do_retry
            )
        self.root.after(0, _open)

    def _show_no_internet_popup(self, detail):
        """Show the no-internet popup and block until user retries or stops."""
        def _do_stop():
            self.stop_flag = True
            self._rate_wait_event.set()

        def _do_retry():
            self._server_err_count = 0
            self._rate_wait_event.set()

        def _open():
            if hasattr(self, "_no_internet_popup") and \
               self._no_internet_popup and \
               self._no_internet_popup.winfo_exists():
                return
            cp = self.state.get("checkpoint")
            self._no_internet_popup = NoInternetPopup(
                self.root, detail, cp, _do_stop, _do_retry
            )
        self.root.after(0, _open)

    def _handle_rate_limit(self, retry_after):
        """Block the worker thread, show rate limit popup + log countdown."""
        self._rl_hit_count += 1
        rl_count = self._rl_hit_count
        self._rate_wait_event.clear()

        def _do_resume():
            self._rate_wait_event.set()

        def _do_stop():
            self.stop_flag = True
            self._rate_wait_event.set()

        def _do_slow_down():
            new_delay = self.delay_var.get() + 5
            self.delay_var.set(new_delay)
            self._log(f"  Delay increased to {new_delay}s to reduce rate limit hits.", "info")

        def _open_popup():
            RateLimitPopup(
                self.root, retry_after, rl_count,
                on_done=_do_resume,
                on_stop=_do_stop,
                on_slow_down=_do_slow_down,
            )
            # Also run the log countdown in parallel so the log stays informative
            RateLimitBanner(
                self.root, self._log,
                lambda t: self.root.after(0, lambda: self.status_var.set(t)),
                retry_after,
                lambda: None,   # popup already handles resume — banner just counts down
            )
        self.root.after(0, _open_popup)
        self._rate_wait_event.wait()
        if not self.stop_flag:
            self._rl_hit_count = 0

    # ── Settings ──────────────────────────────────────────────────────────────

    _FIELDS = [
        "url_var", "access_var", "secret_var",
        "cap_all_var", "cap_outlinks_var", "cap_screenshot_var",
        "force_get_var", "skip_first_var", "delay_avail_var",
        "email_result_var", "save_errors_var",
        "if_not_var", "js_timeout_var", "cookie_var", "ua_var",
        "delay_var", "retries_var", "backoff_var", "reset_var",
        "rate_limit_backoff_var",
        "crawl_url_var", "crawl_max_var",
        "crawl_same_path_var", "crawl_robots_var", "crawl_subdomains_var",
    ]

    def _save_settings(self):
        data = {}
        for f in self._FIELDS:
            try:
                data[f] = getattr(self, f).get()
            except Exception:
                pass
        # Never save IA keys to disk — they stay in env vars or are typed each session
        data.pop("access_var", None)
        data.pop("secret_var", None)
        data["_sounds"] = self.sounds.get_state()
        Path(SETTINGS_FILE).write_text(json.dumps(data, indent=2))
        self._log("Settings saved. (IA keys are never saved to disk for security.)", "dim")

    def _load_settings(self):
        # Always try env vars first as baseline
        if os.environ.get("IA_ACCESS_KEY"):
            self.access_var.set(os.environ["IA_ACCESS_KEY"])
        if os.environ.get("IA_SECRET_KEY"):
            self.secret_var.set(os.environ["IA_SECRET_KEY"])

        # Overlay with saved settings file (overrides env vars if non-empty)
        p = Path(SETTINGS_FILE)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text())
            for f in self._FIELDS:
                if f in data and hasattr(self, f):
                    try:
                        val = data[f]
                        if f in ("access_var", "secret_var") and not val:
                            continue
                        getattr(self, f).set(val)
                    except Exception:
                        pass
            # Restore sound state
            if "_sounds" in data:
                self.sounds.set_state(data["_sounds"])
                self.master_vol_var.set(self.sounds.master_vol)
                self._mvol_lbl.config(text=f"{self.sounds.master_vol}%")
            if self.url_var.get():
                self.root.after(200, self._reload_urls)
        except Exception:
            pass

    # ── Crawl helpers ─────────────────────────────────────────────────────────

    def _set_crawl_status(self, text):
        def _u():
            self.crawl_status_var.set(text)
            self.root.update_idletasks()
        self.root.after(0, _u)

    def _add_url_to_checklist(self, url):
        """Dynamically insert a newly discovered URL into the tree, reflecting current state."""
        if url not in self.all_urls:
            self.all_urls.append(url)
        def _u():
            if self.tree.exists(url):
                return
            entry = self.state["urls"].get(url, {})
            pg    = entry.get("page",       False)
            ol    = entry.get("outlinks",   False)
            ss    = entry.get("screenshot", False)
            want_ol = self.cap_outlinks_var.get()
            want_ss = self.cap_screenshot_var.get()

            page_sym = "✓" if pg else "—"
            ol_sym   = ("✓" if ol else "·") if want_ol  else "—"
            ss_sym   = ("✓" if ss else "·") if want_ss  else "—"

            if pg and not (want_ol and not ol) and not (want_ss and not ss):
                status = "Done";    tag = "saved"
            elif pg:
                status = "Partial"; tag = "skipped"
            else:
                status = "Pending"; tag = "pending"

            short = url if len(url) <= 55 else url[:52] + "..."
            self.tree.insert("", "end", iid=url,
                             values=(short, page_sym, ol_sym, ss_sym, status),
                             tags=(tag,))
        self.root.after(0, _u)

    # ── Known JS-rendered site handlers ──────────────────────────────────────
    #
    # These sites render all content via JavaScript so a plain GET returns
    # an empty shell. Each entry maps a domain pattern to a function that
    # returns an alternative fetch URL whose response actually contains links.

    _JS_SITE_HANDLERS = [

        # ── Google Workspace ──────────────────────────────────────────────────
        # Google Docs — export as HTML gets full content + hyperlinks
        (
            _page_re.compile(r'docs\.google\.com/document/d/([^/?#]+)'),
            lambda m, url: f"https://docs.google.com/document/d/{m.group(1)}/export?format=html",
            "Google Docs (using HTML export to extract links)"
        ),
        # Google Sheets
        (
            _page_re.compile(r'docs\.google\.com/spreadsheets/d/([^/?#]+)'),
            lambda m, url: f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=html",
            "Google Sheets (using HTML export to extract links)"
        ),
        # Google Slides — no HTML export that preserves links
        (
            _page_re.compile(r'docs\.google\.com/presentation/d/([^/?#]+)'),
            lambda m, url: None,
            "Google Slides (no link extraction available for JS presentations)"
        ),

        # ── Social / profile sites ────────────────────────────────────────────
        # Refsheet.net — character profile pages
        # The /api/v2/ endpoint returns JSON with a bio_html field
        (
            _page_re.compile(r'refsheet\.net/([^/?#]+)$'),
            lambda m, url: f"https://refsheet.net/api/v2/characters/{m.group(1)}",
            "Refsheet.net (using API for link extraction)"
        ),
        # Twitter / X — no public API without auth; use nitter mirror instead
        (
            _page_re.compile(r'(?:twitter|x)\.com/([^/?#]+)(?:/status/(\d+))?'),
            lambda m, url: (
                f"https://nitter.net/{m.group(1)}/status/{m.group(2)}"
                if m.group(2) else f"https://nitter.net/{m.group(1)}"
            ),
            "Twitter/X (using Nitter mirror for link extraction)"
        ),
        # Bluesky posts
        (
            _page_re.compile(r'bsky\.app/profile/([^/?#]+)(?:/post/([^/?#]+))?'),
            lambda m, url: (
                f"https://bsky.app/profile/{m.group(1)}/post/{m.group(2)}"
                if m.group(2) else f"https://bsky.app/profile/{m.group(1)}"
            ),
            "Bluesky (standard fetch — may be partial)"
        ),

        # ── Wikis / documentation ─────────────────────────────────────────────
        # Fandom / Wikia — use ?action=raw for wiki markup, or use standard fetch
        # Fandom renders server-side so standard fetch works — no handler needed
        # GitHub — standard fetch works for most pages; API for code/issues
        # GitHub issue / PR — use API for reliable link extraction
        (
            _page_re.compile(r'github\.com/([^/]+)/([^/]+)/(?:issues|pull)/(\d+)'),
            lambda m, url: f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/issues/{m.group(3)}",
            "GitHub Issue/PR (using API for link extraction)"
        ),

        # ── Art / portfolio sites ─────────────────────────────────────────────
        # DeviantArt — JS-heavy; use oEmbed for at least the description
        (
            _page_re.compile(r'deviantart\.com/([^/]+)/art/([^/?#]+)'),
            lambda m, url: f"https://backend.deviantart.com/oembed?url={url}&format=json",
            "DeviantArt (using oEmbed — limited link extraction)"
        ),
        # ArtStation — projects page; use API
        (
            _page_re.compile(r'artstation\.com/([^/]+)$'),
            lambda m, url: f"https://www.artstation.com/users/{m.group(1)}/projects.json",
            "ArtStation (using projects API for link extraction)"
        ),
        # Pixiv — requires login for most pages; use pixiv.net/en for public
        (
            _page_re.compile(r'pixiv\.net/(?:en/)?artworks/(\d+)'),
            lambda m, url: f"https://www.pixiv.net/touch/ajax/illust/details?illust_id={m.group(1)}",
            "Pixiv (using touch API — may require login)"
        ),

        # ── Wikis — MediaWiki / Fandom ────────────────────────────────────────
        # Fandom (and any MediaWiki site) — use the MediaWiki API to extract
        # links reliably instead of scraping JS-rendered HTML.
        # API returns JSON with all internal links for the page.
        (
            _page_re.compile(r'((?:[a-z0-9-]+\.)?(?:fandom|wikia)\.com)/wiki/([^?#]+)'),
            lambda m, url: (
                f"https://{m.group(1)}/api.php?"
                f"action=query&titles={m.group(2).replace(' ','_')}"
                f"&prop=links&pllimit=max&format=json&redirects=1"
            ),
            "Fandom/Wikia wiki (using MediaWiki API for link extraction)"
        ),
        # Generic MediaWiki (/wiki/ path + /api.php endpoint)
        (
            _page_re.compile(r'((?:www\.)?(?:wikipedia|mediawiki|wikimedia)\.org(?:/\w+)?)/wiki/([^?#]+)'),
            lambda m, url: (
                f"https://{m.group(1).split('/')[0]}/w/api.php?"
                f"action=query&titles={m.group(2).replace(' ','_')}"
                f"&prop=links&pllimit=max&format=json&redirects=1"
            ),
            "MediaWiki (Wikipedia/Wikimedia — using API for link extraction)"
        ),

        # ── Forums / communities ──────────────────────────────────────────────
        # Reddit — use old.reddit.com which is server-rendered HTML
        (
            _page_re.compile(r'(?:www\.)?reddit\.com(/[^?#]*)'),
            lambda m, url: f"https://old.reddit.com{m.group(1)}",
            "Reddit (using old.reddit.com for server-rendered HTML)"
        ),
        # Tumblr — use /api/read for at least post content
        # Standard fetch works for most Tumblr pages (server-rendered)

        # ── Video sites ───────────────────────────────────────────────────────
        # YouTube — use oEmbed for title/description; no full page links available
        (
            _page_re.compile(r'youtube\.com/watch\?v=([^&\s]+)'),
            lambda m, url: f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={m.group(1)}&format=json",
            "YouTube (using oEmbed — description links only)"
        ),

        # ── Archiving / reference ─────────────────────────────────────────────
        # Linktree — use standard fetch; many Linktree pages load via JS
        # but the initial HTML contains og:tags we can scrape
        (
            _page_re.compile(r'linktr\.ee/([^/?#]+)'),
            lambda m, url: url,   # standard fetch — og tags in head
            "Linktree (standard fetch — links may be limited)"
        ),
        # Carrd — JS-rendered; no reliable alternative
        (
            _page_re.compile(r'[^.]+\.carrd\.co'),
            lambda m, url: None,
            "Carrd (JS-rendered — no link extraction available)"
        ),
    ]

    def _get_fetch_url(self, url):
        """
        Returns (fetch_url, description) — if url is a JS-rendered site we
        know how to handle, returns an alternative URL that has real HTML.
        Otherwise returns the original URL.
        """
        for pattern, builder, desc in self._JS_SITE_HANDLERS:
            m = pattern.search(url)
            if m:
                alt = builder(m, url)
                return alt, desc
        return url, None

    def _fetch_page_html(self, url, session):
        """
        Fetch a page and return its HTML text for link extraction.
        Automatically uses export/alternative URLs for known JS-rendered sites.
        For MediaWiki/Fandom sites, converts API JSON to synthetic HTML.
        Returns (html_text, fetch_note).
        """
        fetch_url, note = self._get_fetch_url(url)
        if fetch_url is None:
            return None, note
        try:
            headers = {"User-Agent": "Mozilla/5.0 WaybackArchiver/1.25"}
            r = session.get(fetch_url, timeout=20, allow_redirects=True,
                            headers=headers)
            if r.status_code != 200:
                return None, note

            ct = r.headers.get("Content-Type", "")

            # ── MediaWiki API JSON response ───────────────────────────────────
            # Fandom/Wikipedia/MediaWiki returns JSON with a "query.pages" structure
            if "json" in ct or fetch_url != url and "api.php" in fetch_url:
                try:
                    data = r.json()
                except Exception:
                    return None, note

                # MediaWiki query API: links prop
                if "query" in data and "pages" in data["query"]:
                    pages  = data["query"]["pages"]
                    # Build synthetic HTML with <a href> tags for each link
                    # Extract base (scheme + netloc) from the original URL
                    parsed    = urlparse(url)
                    wiki_base = f"{parsed.scheme}://{parsed.netloc}"
                    link_html = []
                    for page_id, page_data in pages.items():
                        for link in page_data.get("links", []):
                            if link.get("ns", -1) == 0:   # main namespace only
                                title = link["*"].replace(" ", "_")
                                link_html.append(
                                    f'<a href="{wiki_base}/wiki/{title}">'
                                    f'{title}</a>'
                                )
                    if link_html:
                        return (f"<html><body>"
                                f"{''.join(link_html)}"
                                f"</body></html>"), note
                    # No links found via API — fall back to raw HTML fetch
                    fallback = session.get(url, timeout=20, allow_redirects=True,
                                           headers=headers)
                    if fallback.status_code == 200 and "html" in fallback.headers.get("Content-Type",""):
                        return fallback.text, note
                    return None, note

                return None, note

            # ── Standard HTML response ────────────────────────────────────────
            if "html" in ct or fetch_url != url:
                return r.text, note

        except Exception:
            pass
        return None, None

    def _load_robots(self, base_url, session):
        """
        Load robots.txt for the site.
        Returns (RobotFileParser, robots_text) — robots_text is the raw content for logging.
        """
        from urllib.robotparser import RobotFileParser
        parsed_base = urlparse(base_url)
        robots_url  = f"{parsed_base.scheme}://{parsed_base.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        robots_text = ""
        try:
            r = session.get(robots_url, timeout=10)
            if r.status_code == 200:
                robots_text = r.text
                rp.parse(robots_text.splitlines())
            else:
                # No robots.txt — allow everything
                robots_text = f"(No robots.txt found — HTTP {r.status_code})"
        except Exception as e:
            robots_text = f"(Could not fetch robots.txt: {e})"
        return rp, robots_text

    def _show_robots_blocked_dialog(self, start_url, robots_text):
        """
        Show a dialog explaining that robots.txt blocks the start URL.
        Returns True if user wants to ignore robots.txt and proceed, False to stop.
        """
        result = {"proceed": False}
        event  = threading.Event()

        def _open():
            win = tk.Toplevel(self.root)
            win.title("Blocked by robots.txt")
            win.configure(bg=BG)
            win.resizable(False, False)
            win.grab_set()
            win.focus_set()

            px = self.root.winfo_x() + self.root.winfo_width()  // 2
            py = self.root.winfo_y() + self.root.winfo_height() // 2
            win.geometry(f"520x420+{px - 260}+{py - 210}")

            # Header
            hdr = tk.Frame(win, bg="#2a1a00", pady=12)
            hdr.pack(fill="x")
            tk.Label(hdr, text="⚠  robots.txt is blocking this site",
                     bg="#2a1a00", fg=WARNING,
                     font=("Segoe UI Semibold", 12)).pack()

            body = tk.Frame(win, bg=BG, padx=18)
            body.pack(fill="both", expand=True, pady=10)

            tk.Label(body,
                     text=f"The website's robots.txt file disallows crawling the starting URL:\n{start_url}",
                     bg=BG, fg=TEXT, font=FONT_SM,
                     wraplength=470, justify="left").pack(anchor="w", pady=(6, 10))

            tk.Label(body, text="robots.txt content:",
                     bg=BG, fg=TEXT_DIM, font=FONT_SM).pack(anchor="w")

            txt = scrolledtext.ScrolledText(body, height=10, bg=BG2, fg=TEXT_DIM,
                                            font=FONT_MONO, relief="flat", bd=0,
                                            state="normal", wrap="word")
            txt.insert("end", robots_text[:2000] + ("..." if len(robots_text) > 2000 else ""))
            txt.config(state="disabled")
            txt.pack(fill="x", pady=(4, 10))

            tk.Label(body,
                     text="You can ignore robots.txt and crawl anyway, or turn off\n"
                          "\"Respect robots.txt\" in the options before starting.",
                     bg=BG, fg=TEXT_DIM, font=FONT_SM,
                     wraplength=470, justify="left").pack(anchor="w")

            btn_row = tk.Frame(win, bg=BG, padx=18, pady=12)
            btn_row.pack(fill="x")

            def _ignore():
                result["proceed"] = True
                win.destroy()
                event.set()

            def _stop():
                result["proceed"] = False
                win.destroy()
                event.set()

            tk.Button(btn_row, text="Stop crawl",
                      bg=BG3, fg=ERROR, relief="flat", font=FONT_BOLD,
                      cursor="hand2", activebackground="#2e2020",
                      padx=16, pady=8, command=_stop).pack(side="left")
            tk.Button(btn_row, text="Ignore robots.txt and crawl anyway",
                      bg=ACCENT, fg="#fff", relief="flat", font=FONT_BOLD,
                      cursor="hand2", activebackground=ACCENT2,
                      padx=16, pady=8, command=_ignore).pack(side="right")

            win.protocol("WM_DELETE_WINDOW", _stop)

        self.root.after(0, _open)
        event.wait()
        return result["proceed"]

    def _start_crawl(self):
        start_url = self.crawl_url_var.get().strip()
        if not start_url:
            self._log("No starting URL entered for crawl.", "error")
            return
        if not start_url.startswith("http"):
            start_url = "https://" + start_url
            self.crawl_url_var.set(start_url)

        access = self.access_var.get().strip() or os.environ.get("IA_ACCESS_KEY", "")
        secret = self.secret_var.get().strip() or os.environ.get("IA_SECRET_KEY", "")
        if not access or not secret:
            self._log("Access key and secret key are required for crawling.", "error")
            return

        self.stop_flag         = False
        self.running           = True
        self._server_err_count = 0
        self._pause_event.set()
        self.start_btn.config(state="disabled")
        self.crawl_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.pause_btn.config(state="normal", text="⏸  PAUSE")

        self._set_bar_state("archiving")
        self.thread = threading.Thread(target=self._run_crawl,
                                       args=(start_url, access, secret), daemon=True)
        self.thread.start()

    def _run_crawl(self, start_url, access_key, secret_key):
        parsed_start = urlparse(start_url)
        base_netloc  = parsed_start.netloc
        base_domain  = extract_registered_domain(base_netloc)

        # Smart path extraction — strip the last segment if it looks like a
        # page number or specific resource (e.g. /forums/section.150/page-9
        # becomes /forums/section.150, so all pages of that section are included)
        raw_path = parsed_start.path.rstrip("/") or "/"
        path_parts = raw_path.split("/")
        last = path_parts[-1] if path_parts else ""
        # Strip trailing segment if it looks like pagination or a leaf node
        import re as _re
        if _re.match(r'^page-?\d+$|^\d+$', last, _re.IGNORECASE) and len(path_parts) > 2:
            start_path = "/".join(path_parts[:-1])
        else:
            start_path = raw_path
        max_pages    = self.crawl_max_var.get()
        same_path    = self.crawl_same_path_var.get()
        check_robots = self.crawl_robots_var.get()
        subdomains   = self.crawl_subdomains_var.get()
        delay        = self.delay_var.get()

        if_not_map = {"Always": 0, "1 day": 86400, "3 days": 259200,
                      "7 days": 604800, "30 days": 2592000}
        options = {
            "capture_all":            self.cap_all_var.get(),
            "capture_outlinks":       False,
            "capture_screenshot":     self.cap_screenshot_var.get(),
            "force_get":              self.force_get_var.get(),
            "skip_first_archive":     self.skip_first_var.get(),
            "delay_wb_availability":  self.delay_avail_var.get(),
            "email_result":           self.email_result_var.get(),
            "if_not_archived_within": if_not_map.get(self.if_not_var.get(), 0),
            "js_behavior_timeout":    self.js_timeout_var.get(),
            "capture_cookie":         self.cookie_var.get(),
            "user_agent":             self.ua_var.get(),
            "retries":                self.retries_var.get(),
            "backoff":                self.backoff_var.get(),
            "rate_limit_backoff":   self.rate_limit_backoff_var.get(),
        }

        crawl_session = requests.Session()
        crawl_session.headers.update({"User-Agent": USER_AGENT})

        archive_session = requests.Session()
        archive_session.headers.update({
            "User-Agent":    USER_AGENT,
            "Authorization": f"LOW {access_key}:{secret_key}",
            "Accept":        "application/json",
        })

        # Load and inspect robots.txt
        rp          = None
        robots_text = ""
        ignore_robs = not check_robots
        if check_robots:
            self._log(f"Loading robots.txt for {base_netloc}...", "dim")
            rp, robots_text = self._load_robots(start_url, crawl_session)
            self._log(f"  robots.txt: {robots_text[:120].splitlines()[0] if robots_text else 'empty'}", "dim")

            # Check if start URL itself is blocked
            if rp and not rp.can_fetch("*", start_url):
                self._log(f"  Start URL is blocked by robots.txt!", "warning")
                self._log(f"  Asking user whether to proceed...", "dim")
                proceed = self._show_robots_blocked_dialog(start_url, robots_text)
                if not proceed:
                    self._log("Crawl cancelled — robots.txt blocks this site.", "warning")
                    self._log("Tip: uncheck \"Respect robots.txt\" in options to ignore it.", "dim")
                    self._finish()
                    return
                else:
                    self._log("Ignoring robots.txt at user's request.", "warning")
                    ignore_robs = True
                    rp = None   # disable further robots checking

        self._log("=" * 54, "dim")
        self._log(f"CRAWL MODE  —  {datetime.now():%Y-%m-%d %H:%M}", "dim")
        self._log(f"Domain: {base_domain}  |  Max pages: {max_pages}", "dim")
        self._log(f"Same path: {'Yes ('+start_path+')' if same_path else 'No'}  |  "
                  f"Subdomains: {'Yes' if subdomains else 'No'}  |  "
                  f"Robots: {'Ignored' if ignore_robs else 'Respected'}", "dim")
        self._log("=" * 54, "dim")

        from collections import deque as _deque

        # Seed the queue — if start URL has pagination, expand it first
        pagination_builders = {}
        page_run_active     = {}

        start_norm = normalise_url(start_url)
        parsed_start = urlparse(start_url)
        wiki_base    = f"{parsed_start.scheme}://{parsed_start.netloc}"

        # ── MediaWiki / Fandom — seed ALL pages via allpages API ─────────────
        _mw_pattern = _page_re.compile(
            r'(?:[a-z0-9-]+\.)?(?:fandom|wikia|wikipedia|mediawiki)\.(?:com|org)',
            _page_re.I
        )
        mediawiki_seeded = False
        if _mw_pattern.search(parsed_start.netloc):
            # Determine the API base path (Fandom: /api.php, Wikipedia: /w/api.php)
            api_base = f"{wiki_base}/api.php"
            if "wikipedia.org" in parsed_start.netloc or "wikimedia.org" in parsed_start.netloc:
                api_base = f"{wiki_base}/w/api.php"

            self._log(f"  MediaWiki detected — fetching all pages via API…", "dim")
            all_wiki_urls = []
            ap_continue = ""
            try:
                while True:
                    params = (
                        f"action=query&list=allpages&aplimit=500"
                        f"&apnamespace=0&format=json"
                        f"{'&apcontinue=' + ap_continue if ap_continue else ''}"
                    )
                    r = crawl_session.get(
                        f"{api_base}?{params}", timeout=20,
                        headers={"User-Agent": "Mozilla/5.0 WaybackArchiver/1.25"}
                    )
                    if r.status_code != 200:
                        break
                    data = r.json()
                    pages = data.get("query", {}).get("allpages", [])
                    for p in pages:
                        title = p["title"].replace(" ", "_")
                        page_url = normalise_url(f"{wiki_base}/wiki/{title}")
                        if page_url and page_url not in all_wiki_urls:
                            all_wiki_urls.append(page_url)
                    # Stop if we've hit the max_pages cap
                    if len(all_wiki_urls) >= max_pages:
                        all_wiki_urls = all_wiki_urls[:max_pages]
                        break
                    cont = data.get("continue", {})
                    ap_continue = cont.get("apcontinue", "")
                    if not ap_continue:
                        break
            except Exception as e:
                self._log(f"  allpages API failed ({e}) — falling back to link crawl", "warning")

            if all_wiki_urls:
                self._log(f"  Seeded {len(all_wiki_urls)} wiki pages from allpages API", "dim")
                queue = _deque(all_wiki_urls)
                for u in all_wiki_urls[:200]:   # show first 200 in checklist immediately
                    self._add_url_to_checklist(u)
                if len(all_wiki_urls) > 200:
                    # Add the rest silently — checklist would get huge
                    self._log(f"  ({len(all_wiki_urls) - 200} more pages queued — showing first 200 in checklist)", "dim")
                mediawiki_seeded = True

        # ── Standard seed — pagination or single URL ──────────────────────────
        if not mediawiki_seeded:
            page_result = generate_page_run(start_url)
            if page_result:
                pages, current_page, builder = page_result
                self._log(f"  Detected pagination at page {current_page} — seeding pages 1–{current_page}", "dim")
                initial_urls = [normalise_url(p) for p in pages]
                queue = _deque(initial_urls)
                pagination_builders[start_norm] = (builder, current_page)
                for u in initial_urls:
                    self._add_url_to_checklist(u)
            else:
                queue = _deque([start_norm])
                self._add_url_to_checklist(start_norm)

        visited    = set()   # URLs whose links we have already extracted

        archived_count  = 0
        skipped_count   = 0
        failed_count    = 0
        robots_blocked  = 0   # consecutive robots blocks in a row

        self._set_progress(0, 1)

        while queue and not self.stop_flag:
            # Pause check — blocks here if paused, resumes when unpaused
            if not self._wait_if_paused():
                break

            if archived_count + skipped_count + failed_count >= max_pages:
                self._log(f"Reached max pages limit ({max_pages}). Stopping crawl.", "warning")
                break

            url = queue.popleft()
            norm = normalise_url(url)

            if norm in visited:
                continue
            visited.add(norm)

            # Domain check
            if subdomains:
                parsed_url = urlparse(url)
                url_domain = extract_registered_domain(parsed_url.netloc)
                if url_domain != base_domain:
                    continue
            else:
                if not same_domain(base_netloc, url):
                    continue

            # Path check
            if same_path:
                parsed_url = urlparse(url)
                if not parsed_url.path.startswith(start_path):
                    continue

            # Robots check
            if rp and not ignore_robs and not rp.can_fetch("*", url):
                robots_blocked += 1
                skipped_count  += 1
                # Only log first few to avoid flooding
                if robots_blocked <= 5:
                    self._log(f"  Skipped (robots.txt): {url}", "dim")
                elif robots_blocked == 6:
                    self._log(f"  (further robots.txt skips suppressed in log)", "dim")
                # If robots is blocking everything in the queue, show popup
                if robots_blocked >= 1 and archived_count == 0 and len(queue) == 0:
                    self._log(f"  robots.txt has blocked all {robots_blocked} URLs — asking user.", "warning")
                    proceed = self._show_robots_blocked_dialog(start_url, robots_text)
                    if not proceed:
                        self._log("Crawl cancelled — robots.txt blocks this site.", "warning")
                        break
                    else:
                        self._log("Ignoring robots.txt at user's request.", "warning")
                        ignore_robs = True
                        rp = None
                continue
            robots_blocked = 0   # reset consecutive count on a successful pass

            total_seen = len(visited) + len(queue)
            self._set_crawl_status(f"Crawled: {archived_count}  |  Queued: {len(queue)}")
            self._set_progress(archived_count, min(max_pages, archived_count + len(queue) + 1))

            # Add to checklist
            self._add_url_to_checklist(url)
            entry = url_entry(self.state, url)

            # Skip if already fully archived
            if entry.get("page"):
                self._log(f"  Already archived: {url}", "dim")
                self._tree_set_status(url, "Done", "saved")
                skipped_count += 1
                self._increment_stat("existing")
            else:
                self._log(f"  Archiving: {url}", "info")
                self.root.after(0, lambda u=url: self._start_spinner(u))
                self._set_status(f"Crawl: archiving page {archived_count + 1}...")
                self.sounds.play("archiving")

                write_checkpoint(self.state, url, "crawl-archiving")
                result_type, archive_url_str, error_msg, retry_after = do_save(
                    url, archive_session, options, self._log, self.state,
                    lambda u, s, j=None: write_checkpoint(self.state, u, s, j)
                )

                if result_type == "success":
                    entry["page"]        = True
                    entry["archive_url"] = archive_url_str
                    entry["last_saved"]  = datetime.now().isoformat()
                    entry["error_msg"]   = ""
                    entry["failed"]      = False
                    want_ol_now = self.cap_outlinks_var.get()
                    want_ss_now = self.cap_screenshot_var.get()
                    if want_ol_now:
                        entry["outlinks"]  = True
                    if want_ss_now:
                        entry["screenshot"] = True
                    save_state(self.state)
                    clear_checkpoint(self.state)
                    threading.Thread(target=self._write_url_logs, daemon=True).start()
                    self._log(f"  ✓ Saved → {archive_url_str}", "success")
                    def _finish_row(u=url, state=self.state,
                                    cap_ol=self.cap_outlinks_var,
                                    cap_ss=self.cap_screenshot_var):
                        self._stop_spinner_internal()
                        if self.tree.exists(u):
                            e      = state["urls"].get(u, {})
                            w_ol   = cap_ol.get()
                            w_ss   = cap_ss.get()
                            p_sym  = "✓" if e.get("page")       else "—"
                            ol_sym = ("✓" if e.get("outlinks")   else "·") if w_ol else "—"
                            ss_sym = ("✓" if e.get("screenshot") else "·") if w_ss else "—"
                            vals   = list(self.tree.item(u, "values"))
                            vals[1] = p_sym
                            vals[2] = ol_sym
                            vals[3] = ss_sym
                            vals[4] = "Saved"
                            self.tree.item(u, values=vals, tags=("saved",))
                            if not self._tree_user_scrolled:
                                self.tree.see(u)
                    self.root.after(0, _finish_row)
                    self.sounds.play("saved")
                    self._set_bar_state("archiving")
                    archived_count += 1
                    self._increment_stat("archived")

                elif result_type == "rate_limit":
                    self._log(f"  Rate limited — retry in {retry_after}s", "warning")
                    self.root.after(0, lambda u=url: self._stop_spinner(u, "Rate limited", "pending"))
                    self.sounds.play("rate_limit")
                    self._set_bar_state("warning")
                    self._handle_rate_limit(retry_after)
                    if not self.stop_flag:
                        queue.appendleft(url)
                        visited.discard(norm)
                    continue

                elif result_type == "server_error":
                    self._server_err_count += 1
                    self._log(f"  Server error: {error_msg}", "error")
                    self.root.after(0, lambda u=url: self._stop_spinner(u, "Server error", "outage"))
                    self.sounds.play("error")
                    self._set_bar_state("error")
                    if self._server_err_count >= OUTAGE_THRESHOLD:
                        self._log("  Multiple errors — checking connection...", "warning")
                        net_status, health_detail = check_ia_health(archive_session)
                        if net_status == "no_internet":
                            self._log("  Your internet is down — pausing crawl.", "warning")
                            self.sounds.play("outage")
                            self._set_bar_state("outage")
                            self._show_no_internet_popup(health_detail)
                            self._rate_wait_event.clear()
                            self._rate_wait_event.wait()
                            if self.stop_flag:
                                break
                            self._server_err_count = 0
                            queue.appendleft(url)
                            visited.discard(norm)
                            continue
                        elif net_status == "ia_down":
                            self._log("  Internet Archive appears DOWN.", "error")
                            self.sounds.play("outage")
                            self._set_bar_state("outage")
                            self._show_outage_popup(f"{error_msg}\n{health_detail}", archive_session)
                            self._rate_wait_event.clear()
                            self._rate_wait_event.wait()
                            if self.stop_flag:
                                break
                            self._server_err_count = 0
                            queue.appendleft(url)
                            visited.discard(norm)
                            continue
                    entry["error_msg"]    = error_msg or "Server error"
                    entry["failed"]       = True
                    entry["last_attempt"] = datetime.now().isoformat()
                    failed_count += 1

                else:
                    self._log(f"  ✗ Failed: {error_msg}", "error")
                    self.root.after(0, lambda u=url: self._stop_spinner(u, "Failed", "failed"))
                    self.sounds.play("error")
                    self._set_bar_state("error")
                    entry["error_msg"]    = error_msg or "All retries exhausted"
                    entry["failed"]       = True
                    entry["last_attempt"] = datetime.now().isoformat()
                    failed_count += 1

                save_state(self.state)
                threading.Thread(target=self._write_url_logs, daemon=True).start()

            # ── Crawl this page for links / pagination ─────────────────────────
            if archived_count + skipped_count + failed_count < max_pages:
                html, fetch_note = self._fetch_page_html(url, crawl_session)
                if fetch_note:
                    self._log(f"  {fetch_note}", "dim")
                if html:
                    links      = extract_links(html, url)
                    norm_links = {normalise_url(lk) for lk in links}
                    already_processed = archived_count + skipped_count + failed_count

                    # ── Pagination detection ──────────────────────────────────
                    # Check if this page itself has a pagination pattern
                    page_result = detect_pagination(url)
                    if page_result:
                        cur_page, builder = page_result
                        # Register builder if new
                        base_key = normalise_url(builder(1))
                        if base_key not in pagination_builders:
                            pagination_builders[base_key] = (builder, cur_page)

                        # Look for the next page in the extracted links
                        next_page_url  = normalise_url(builder(cur_page + 1))
                        prev_page_urls = {normalise_url(builder(n)) for n in range(1, cur_page)}

                        if next_page_url in norm_links and next_page_url not in visited:
                            # Next page exists — insert at front of queue
                            queue.appendleft(next_page_url)
                            self._add_url_to_checklist(next_page_url)
                            self._log(f"  Pagination: next page → {builder(cur_page + 1)}", "dim")
                            pagination_builders[base_key] = (builder, cur_page + 1)
                        else:
                            self._log(f"  Pagination: reached end at page {cur_page}", "dim")

                        # Also queue any earlier pages in this run we haven't visited
                        for prev in sorted(prev_page_urls - visited):
                            if already_processed + len(queue) < max_pages:
                                queue.appendleft(prev)

                    # ── Regular link discovery ────────────────────────────────
                    new_found = 0
                    pagination_norms = set()
                    # Collect all page-N variants from links so we don't double-add
                    for lk in links:
                        pr = detect_pagination(lk)
                        if pr:
                            _, b = pr
                            pagination_norms.add(normalise_url(b(1)))

                    for link in links:
                        if already_processed + len(queue) >= max_pages:
                            break
                        nl = normalise_url(link)
                        if not nl or nl in visited or nl in queue:
                            continue
                        # If this link is a paginated variant of a series
                        # we're already tracking, skip it (we handle it above)
                        pr = detect_pagination(link)
                        if pr:
                            _, b = pr
                            if normalise_url(b(1)) in pagination_builders:
                                continue
                        queue.append(nl)
                        # Show in checklist immediately as it's discovered
                        self._add_url_to_checklist(nl)
                        new_found += 1

                    if new_found:
                        self._log(f"  Found {new_found} new links (queue: {len(queue)})", "dim")
                        # Update total count in stats bar
                        total_now = len(self.all_urls)
                        self.root.after(0, lambda t=total_now: (
                            self._stat_total_var.set(f"{t} URL{'s' if t != 1 else ''}"),
                            self.root.update_idletasks()
                        ))

            if not self.stop_flag and queue:
                time.sleep(delay)

        clear_checkpoint(self.state)
        self._log("=" * 54, "dim")
        self._log(f"Crawl done  —  Archived: {archived_count}  |  "
                  f"Skipped: {skipped_count}  |  Failed: {failed_count}", "success")
        self._log("=" * 54, "dim")
        self.sounds.play("crawl_done")
        self._set_bar_state("success")
        self._set_crawl_status(f"Done — {archived_count} archived")
        self._set_status("Crawl finished")
        self._finish()

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def _wait_if_paused(self):
        """Block the worker thread while paused. Returns False if stopped during pause."""
        if not self._pause_event.is_set():
            self._pause_event.wait()   # blocks until resume or stop
        return not self.stop_flag

    def _toggle_pause(self):
        if self._pause_event.is_set():
            # Currently running — pause it
            self._pause_event.clear()
            self.pause_btn.config(text="▶  RESUME")
            self._set_status("Paused — click Resume to continue")
            self._set_bar_state("warning")
            self._log("Paused. Click Resume to continue.", "warning")
        else:
            # Currently paused — resume
            self._pause_event.set()
            self.pause_btn.config(text="⏸  PAUSE")
            self._set_status("Resuming…")
            self._set_bar_state("archiving")
            self._log("Resumed.", "info")

    def _start(self):
        if not self.all_urls:
            self._log("No URLs loaded. Select a URL file first.", "error")
            return
        access = self.access_var.get().strip() or os.environ.get("IA_ACCESS_KEY", "")
        secret = self.secret_var.get().strip() or os.environ.get("IA_SECRET_KEY", "")
        if not access or not secret:
            self._log("Access key and secret key are required.", "error")
            return
        self.stop_flag         = False
        self.running           = True
        self._server_err_count = 0
        self._pause_event.set()   # ensure not paused
        self.start_btn.config(state="disabled")
        self.crawl_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.pause_btn.config(state="normal", text="⏸  PAUSE")
        self._set_bar_state("archiving")
        if self.reset_var.get():
            self.state = {"urls": {}, "checkpoint": None}
            save_state(self.state)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _stop(self):
        self.stop_flag = True
        self._pause_event.set()   # unblock pause so the loop can see stop_flag
        self._rate_wait_event.set()
        self._set_bar_state("warning")
        self._log("Stop requested — finishing current URL...", "warning")
        self.stop_btn.config(state="disabled")
        self.pause_btn.config(state="disabled")

    def _finish(self):
        def _r():
            self.running = False
            self._pause_event.set()
            self._stop_spinner_internal()
            self.start_btn.config(state="normal")
            self.crawl_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.pause_btn.config(state="disabled", text="⏸  PAUSE")
            self._refresh_tree()
            # Write final URL logs after run completes
            threading.Thread(target=self._write_url_logs, daemon=True).start()
        self.root.after(0, _r)

    def _set_status(self, text):
        def _u():
            self.status_var.set(text)
            self.root.update_idletasks()
        self.root.after(0, _u)

    def _set_progress(self, val, total):
        def _u():
            self.progress.set_progress(val, total)
            self.count_var.set(f"{val} / {total}")
            self.root.update_idletasks()
        self.root.after(0, _u)

    def _set_bar_state(self, state):
        def _u():
            self.progress.set_bar_state(state)
            self.root.update_idletasks()
        self.root.after(0, _u)

    # ── Worker ────────────────────────────────────────────────────────────────

    def _run(self):
        access_key = self.access_var.get().strip() or os.environ.get("IA_ACCESS_KEY", "")
        secret_key = self.secret_var.get().strip() or os.environ.get("IA_SECRET_KEY", "")

        want_outlinks   = self.cap_outlinks_var.get()
        want_screenshot = self.cap_screenshot_var.get()
        delay           = self.delay_var.get()

        if_not_map = {"Always": 0, "1 day": 86400, "3 days": 259200,
                      "7 days": 604800, "30 days": 2592000}

        options = {
            "capture_all":            self.cap_all_var.get(),
            "capture_outlinks":       want_outlinks,
            "capture_screenshot":     want_screenshot,
            "force_get":              self.force_get_var.get(),
            "skip_first_archive":     self.skip_first_var.get(),
            "delay_wb_availability":  self.delay_avail_var.get(),
            "email_result":           self.email_result_var.get(),
            "if_not_archived_within": if_not_map.get(self.if_not_var.get(), 0),
            "js_behavior_timeout":    self.js_timeout_var.get(),
            "capture_cookie":         self.cookie_var.get(),
            "user_agent":             self.ua_var.get(),
            "retries":                self.retries_var.get(),
            "backoff":                self.backoff_var.get(),
            "rate_limit_backoff":   self.rate_limit_backoff_var.get(),
        }

        session = requests.Session()
        session.headers.update({
            "User-Agent":    USER_AGENT,
            "Authorization": f"LOW {access_key}:{secret_key}",
            "Accept":        "application/json",
        })

        # Build work list — preserving file order
        work = []
        for url in self.all_urls:
            entry      = url_entry(self.state, url)
            needs_page = not entry["page"]
            needs_ol   = want_outlinks   and not entry["outlinks"]
            needs_ss   = want_screenshot and not entry["screenshot"]
            if needs_page or needs_ol or needs_ss:
                work.append((url, needs_page, needs_ol, needs_ss))

        # Group by registered domain so we archive all pages from the same
        # site consecutively instead of jumping between domains.
        # Uses a stable sort — preserves original order within each domain.
        def _domain_key(item):
            try:
                return extract_registered_domain(urlparse(item[0]).netloc)
            except Exception:
                return ""
        from collections import defaultdict as _dd
        domain_groups = _dd(list)
        for item in work:
            domain_groups[_domain_key(item)].append(item)
        # Reconstruct in domain order (first-seen domain comes first)
        seen_domains = []
        for item in work:
            d = _domain_key(item)
            if d not in seen_domains:
                seen_domains.append(d)
        work = []
        for d in seen_domains:
            work.extend(domain_groups[d])

        total   = len(self.all_urls)
        pending = len(work)
        skip_n  = total - pending

        self._log("=" * 54, "dim")
        self._log(f"Wayback Archiver  —  {datetime.now():%Y-%m-%d %H:%M}", "dim")
        self._log(f"Total: {total}  |  Need archiving: {pending}  |  Already done: {skip_n}", "dim")
        self._log("=" * 54, "dim")

        if pending == 0:
            self._log("All URLs already fully archived!", "success")
            self._finish()
            return

        saved_count  = 0
        failed_count = 0
        self._set_progress(skip_n, total)

        for i, (url, needs_page, needs_ol, needs_ss) in enumerate(work, 1):
            if self.stop_flag:
                self._log("Stopped by user.", "warning")
                break

            # Pause check — blocks here until resumed or stopped
            if not self._wait_if_paused():
                self._log("Stopped during pause.", "warning")
                break

            entry    = url_entry(self.state, url)
            todo_str = " + ".join(
                p for p, b in [("page", needs_page), ("outlinks", needs_ol), ("screenshot", needs_ss)] if b
            )
            self._log(f"[{skip_n + i}/{total}]  {url}", "info")
            self._log(f"  Capturing: {todo_str}", "dim")
            self.root.after(0, lambda u=url: self._start_spinner(u))
            self._set_status(f"Archiving {skip_n + i} of {total}...")
            self.sounds.play("archiving")

            job_opts = dict(options)
            job_opts["capture_outlinks"]   = needs_ol
            job_opts["capture_screenshot"] = needs_ss

            result_type, archive_url_str, error_msg, retry_after = do_save(
                url, session, job_opts, self._log, self.state,
                lambda u, s, j=None: write_checkpoint(self.state, u, s, j)
            )

            if result_type == "success":
                # Always mark page if we just saved it
                if needs_page:
                    entry["page"]        = True
                    entry["archive_url"] = archive_url_str
                    self._tree_set_check(url, "page", "✓")
                # Mark outlinks/screenshot done whenever option is ON and job succeeded
                # (regardless of whether that was the primary reason for the job)
                if want_outlinks:
                    entry["outlinks"]   = True
                    self._tree_set_check(url, "outlinks",   "✓")
                if want_screenshot:
                    entry["screenshot"] = True
                    self._tree_set_check(url, "screenshot", "✓")
                entry["last_saved"]  = datetime.now().isoformat()
                entry["error_msg"]   = ""
                entry["failed"]      = False
                clear_checkpoint(self.state)
                self._log(f"  ✓ Saved → {archive_url_str}", "success")
                self.root.after(0, lambda u=url: self._stop_spinner(u, "Saved", "saved"))
                self.sounds.play("saved")
                self._set_bar_state("archiving")
                self._server_err_count = 0
                saved_count += 1
                self._increment_stat("archived")

            elif result_type == "rate_limit":
                self._log(f"  Rate limited — retry in {retry_after}s", "warning")
                self.root.after(0, lambda u=url: self._stop_spinner(u, "Rate limited", "pending"))
                self.sounds.play("rate_limit")
                self._set_bar_state("warning")
                self._handle_rate_limit(retry_after)
                if self.stop_flag:
                    break
                work.insert(i, (url, needs_page, needs_ol, needs_ss))
                self._set_progress(skip_n + i - 1, total)
                continue

            elif result_type == "server_error":
                self._server_err_count += 1
                self._log(f"  Server error: {error_msg}", "error")
                self.root.after(0, lambda u=url: self._stop_spinner(u, "Server error", "outage"))
                self.sounds.play("error")
                self._set_bar_state("error")

                if self._server_err_count >= OUTAGE_THRESHOLD:
                    self._log("  Multiple errors — checking connection...", "warning")
                    net_status, health_detail = check_ia_health(session)
                    if net_status == "no_internet":
                        self._log("  Your internet is down — pausing.", "warning")
                        self.sounds.play("outage")
                        self._set_bar_state("outage")
                        self._show_no_internet_popup(health_detail)
                        self._rate_wait_event.clear()
                        self._rate_wait_event.wait()
                        if self.stop_flag:
                            break
                        self._server_err_count = 0
                        work.insert(i, (url, needs_page, needs_ol, needs_ss))
                        continue
                    elif net_status == "ia_down":
                        self._log("  Internet Archive appears to be DOWN.", "error")
                        self._log("  Progress saved. Showing outage info...", "warning")
                        self.sounds.play("outage")
                        self._set_bar_state("outage")
                        self._show_outage_popup(f"{error_msg}\n{health_detail}", session)
                        self._rate_wait_event.clear()
                        self._rate_wait_event.wait()
                        if self.stop_flag:
                            break
                        self._server_err_count = 0
                        work.insert(i, (url, needs_page, needs_ol, needs_ss))
                        continue
                    else:
                        self._log(f"  IA is reachable ({health_detail}) — isolated error", "warning")
                        self._server_err_count = 0

                # Record error in state for error log
                entry["error_msg"]      = error_msg or f"Server error"
                entry["failed"]         = True
                entry["last_attempt"]   = datetime.now().isoformat()
                failed_count += 1

            else:  # "failed", "error", "timeout"
                self._log(f"  ✗ Failed: {error_msg or 'Unknown error'}", "error")
                self.root.after(0, lambda u=url: self._stop_spinner(u, "Failed", "failed"))
                self.sounds.play("error")
                self._set_bar_state("error")
                # Record error in state for error log
                entry["error_msg"]    = error_msg or "All retries exhausted"
                entry["failed"]       = True
                entry["last_attempt"] = datetime.now().isoformat()
                failed_count += 1

            save_state(self.state)
            threading.Thread(target=self._write_url_logs, daemon=True).start()
            self._set_progress(skip_n + i, total)

            if i < pending and not self.stop_flag:
                time.sleep(delay)

        clear_checkpoint(self.state)
        self._log("=" * 54, "dim")
        self._log(f"Done  —  Saved: {saved_count}  |  Failed: {failed_count}  |  Skipped: {skip_n}",
                  "success" if not failed_count else "warning")
        if failed_count:
            self._log("Re-run to automatically retry failed URLs.", "dim")
        self._log("=" * 54, "dim")
        self.sounds.play("complete")
        self._set_bar_state("success")
        self._set_status("Finished")
        self._finish()

# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os, platform, datetime as _dt, subprocess as _sp

    # ── Colour support ────────────────────────────────────────────────────────
    # Enable ANSI colours on Windows 10+ via virtual terminal processing
    _use_color = False
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        if platform.system() == "Windows":
            try:
                import ctypes
                kernel = ctypes.windll.kernel32
                kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
                _use_color = True
            except Exception:
                _use_color = False
        else:
            _use_color = True   # macOS / Linux always support ANSI

    W   = "\033[0m"
    B   = "\033[1m"
    DIM = "\033[2m"
    CY  = "\033[36m"
    GR  = "\033[32m"
    YL  = "\033[33m"
    RD  = "\033[31m"
    MG  = "\033[35m"

    def _c(code, text):
        return f"{code}{text}{W}" if _use_color else text

    def _ok(label, value=""):
        print(f"  {_c(GR,'✓')}  {_c(CY+B, f'{label:<30}')}  {_c(DIM, value)}")

    def _warn(label, value=""):
        print(f"  {_c(YL,'⚠')}  {_c(YL+B, f'{label:<30}')}  {_c(DIM, value)}")

    def _err(label, value=""):
        print(f"  {_c(RD,'✗')}  {_c(RD+B, f'{label:<30}')}  {_c(DIM, value)}")

    def _info(label, value=""):
        print(f"       {_c(DIM, f'{label:<28}')}  {_c(DIM, value)}")

    def _sep():
        print(_c(DIM, "─" * 62))

    def _section(title):
        _sep()
        print(_c(B, f"  {title}"))

    # ── OS detection ──────────────────────────────────────────────────────────
    current_os = platform.system()
    os_name    = {"Windows": "Windows", "Darwin": "macOS", "Linux": "Linux"}.get(current_os, current_os)
    script_name = os.path.basename(__file__)

    # ── Banner ────────────────────────────────────────────────────────────────
    print()
    print(_c(MG + B, "  WAYBACK ARCHIVER  ") + _c(DIM, f"v{VERSION}"))
    print(_c(DIM,    f"  Running on {os_name} {platform.release()}  |  Python {sys.version.split()[0]}"))
    _sep()

    # ── System ────────────────────────────────────────────────────────────────
    _section("System")
    _ok("Operating system",  f"{os_name} {platform.release()}  ({platform.machine()})")
    _ok("Python",            f"{sys.version.split()[0]}  ({platform.python_implementation()})")
    _ok("Script location",   os.path.abspath(__file__))
    _ok("Working directory", os.getcwd())

    # Windows-only: check if running in CMD vs PowerShell vs Windows Terminal
    if current_os == "Windows":
        term = os.environ.get("WT_SESSION")   # Windows Terminal sets this
        ps   = os.environ.get("PSModulePath")  # PowerShell sets this
        if term:
            _ok("Terminal",      "Windows Terminal  (colour support: yes)")
        elif ps:
            _ok("Terminal",      "PowerShell  (colour support: yes)")
        else:
            _ok("Terminal",      "Command Prompt  (colour support: limited)")

    # macOS-only: check if running in Terminal.app vs iTerm2 etc.
    elif current_os == "Darwin":
        term_prog = os.environ.get("TERM_PROGRAM", "unknown")
        _ok("Terminal",      term_prog)

    # Linux: show DISPLAY for X11 / WAYLAND_DISPLAY for Wayland
    elif current_os == "Linux":
        display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY", "")
        if display:
            _ok("Display",       display)
        else:
            _warn("Display",     "No DISPLAY found — GUI may fail without a desktop environment")

    # ── File checks ───────────────────────────────────────────────────────────
    _section("Files")
    cwd        = os.getcwd()
    state_path = os.path.join(cwd, STATE_FILE)
    log_path   = os.path.join(cwd, LOG_FILE)
    settings_path = os.path.join(cwd, SETTINGS_FILE)
    state_data = {}

    # State file
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state_data = json.load(f)
            url_count = len(state_data.get("urls", {}))
            saved     = sum(1 for e in state_data["urls"].values() if e.get("page"))
            cp        = state_data.get("checkpoint")
            if cp:
                _warn("State file",
                      f"{url_count} URLs  ({saved} archived)  — session was interrupted")
                _info("  Resumes from",  cp.get("url", "?")[:60])
                _info("  At step",       cp.get("step", "?"))
                _info("  Action",        "Click Start / Start Crawl to resume automatically")
            else:
                _ok("State file",   f"{url_count} URLs tracked  ({saved} archived)")
        except Exception as e:
            _warn("State file",     f"Exists but unreadable: {e}")
    else:
        _ok("State file",           "Not found — will be created on first run")

    # Settings file
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                sdata = json.load(f)
            url_file = sdata.get("url_var", "")
            _ok("Settings file",    f"Loaded  (URL list: {os.path.basename(url_file) if url_file else 'not set'})")
            # Warn if old settings contained keys (shouldn't happen now, but just in case)
            if sdata.get("access_var") or sdata.get("secret_var"):
                _warn("Security",   "Settings file contains IA keys — consider deleting it and saving fresh")
        except Exception:
            _warn("Settings file",  "Exists but unreadable")
    else:
        _ok("Settings file",        "Not found — defaults will be used")

    # Log file
    if os.path.exists(log_path):
        size = os.path.getsize(log_path)
        _ok("Log file",             f"{size:,} bytes")
    else:
        _ok("Log file",             "Will be created on first archiving run")

    # URL log files
    for log_name, log_const, label in [
        (ARCHIVED_LOG, "urls_archived.log", "Archived URLs log"),
        (PENDING_LOG,  "urls_pending.log",  "Pending URLs log"),
        (ERROR_LOG,    "urls_error.log",    "Error URLs log"),
    ]:
        lp = os.path.join(cwd, log_name)
        if os.path.exists(lp):
            size  = os.path.getsize(lp)
            lines = sum(1 for _ in open(lp, encoding="utf-8"))
            _ok(label, f"{lines} lines  ({size:,} bytes)  → {log_name}")
        else:
            _ok(label, f"Will be created on first run  → {log_name}")

    # ── Dependencies ──────────────────────────────────────────────────────────
    _section("Dependencies")

    # requests
    try:
        import requests as _rq
        _ok("requests",             _rq.__version__)
    except ImportError:
        if current_os == "Windows":
            _err("requests",        "NOT INSTALLED — open a terminal and run:\n"
                                    "       pip install requests")
        elif current_os == "Darwin":
            _err("requests",        "NOT INSTALLED — run:\n"
                                    "       pip3 install requests")
        else:
            _err("requests",        "NOT INSTALLED — run:\n"
                                    "       pip3 install requests\n"
                                    "       or: sudo apt install python3-requests")

    # tkinter
    try:
        import tkinter as _tk
        _ok("tkinter",              f"Tcl/Tk {_tk.TclVersion}")
    except Exception:
        if current_os == "Windows":
            _err("tkinter",         "Not found — reinstall Python and tick\n"
                                    "       'tcl/tk and IDLE' in the installer")
        elif current_os == "Darwin":
            _err("tkinter",         "Not found — run:\n"
                                    "       brew install python-tk\n"
                                    "       or reinstall from https://python.org")
        else:
            _err("tkinter",         "Not found — run:\n"
                                    "       sudo apt install python3-tk")

    # git — optional, only needed for publish_release.py
    try:
        _r = _sp.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        if _r.returncode == 0:
            _ok("git (optional)",   _r.stdout.strip().replace("git version ", ""))
        else:
            raise FileNotFoundError
    except Exception:
        if current_os == "Windows":
            _warn("git (optional)", "Not found — needed for publish_release.py\n"
                                    "       Install: winget install Git.Git\n"
                                    "       or: https://git-scm.com/download/win")
        elif current_os == "Darwin":
            _warn("git (optional)", "Not found — run:\n"
                                    "       xcode-select --install\n"
                                    "       or: brew install git")
        else:
            _warn("git (optional)", "Not found — run:\n"
                                    "       sudo apt install git")

    # Windows-only: check IA env vars are set
    if current_os == "Windows":
        ia_key = os.environ.get("IA_ACCESS_KEY", "")
        ia_sec = os.environ.get("IA_SECRET_KEY", "")
        if ia_key and ia_sec:
            _ok("IA env vars",      "IA_ACCESS_KEY and IA_SECRET_KEY are set")
        elif ia_key or ia_sec:
            _warn("IA env vars",    "Only one key found in environment — both are needed")
        else:
            _info("IA env vars",    "Not set — keys can be entered in the app instead")
    else:
        # macOS / Linux
        ia_key = os.environ.get("IA_ACCESS_KEY", "")
        ia_sec = os.environ.get("IA_SECRET_KEY", "")
        if ia_key and ia_sec:
            _ok("IA env vars",      "IA_ACCESS_KEY and IA_SECRET_KEY found in environment")
        else:
            _info("IA env vars",    "Not set — enter keys in the app, or add to ~/.bashrc / ~/.zshrc")

    # ── Audio ─────────────────────────────────────────────────────────────────
    _section("Audio")

    if _HAS_SOUND:
        if current_os == "Windows":
            _ok("Backend",          "winsound  (Windows built-in — no install needed)")
        elif current_os == "Darwin":
            _ok("Backend",          "afplay  (macOS built-in — no install needed)")
        elif current_os == "Linux":
            _ok("Backend",          f"{_AUDIO_BACKEND}  (detected)")
        else:
            _ok("Backend",          _AUDIO_BACKEND)
    else:
        if current_os == "Windows":
            _err("Backend",         "winsound not available — unusual on Windows\n"
                                    "       Check your Python installation")
        elif current_os == "Darwin":
            _err("Backend",         "afplay not found — unusual on macOS\n"
                                    "       Check that /usr/bin/afplay exists")
        elif current_os == "Linux":
            _warn("Backend",        "No audio player found — sounds disabled\n"
                                    "       Install one:\n"
                                    "       sudo apt install alsa-utils   # provides aplay\n"
                                    "       sudo apt install sox           # provides play\n"
                                    "       sudo apt install ffmpeg        # provides ffplay")
        else:
            _warn("Backend",        f"No audio player found on {os_name} — sounds disabled")

    # ── URL checklist ─────────────────────────────────────────────────────────
    _section("URL Checklist  (from state file)")

    if state_data.get("urls"):
        total    = len(state_data["urls"])
        archived = sum(1 for e in state_data["urls"].values() if e.get("archive_url"))
        existing = sum(1 for e in state_data["urls"].values()
                       if e.get("page") and not e.get("archive_url"))
        pending  = total - archived - existing
        _ok("Total tracked",        str(total))
        _ok("Archived by you",      _c(GR, str(archived)))
        if existing:
            _ok("Pre-existing",     _c(CY, str(existing)))
        _ok("Pending",
            _c(GR, "0  (all done!)") if pending == 0 else _c(YL, str(pending)))
    else:
        _ok("Status",               "No state file yet — load a URL list in the app to begin")

    # ── Recent log ────────────────────────────────────────────────────────────
    _section(f"Recent Log  ({LOG_FILE})")

    if os.path.exists(log_path):
        try:
            with open(log_path, encoding="utf-8") as f:
                lines = f.readlines()
            tail = [l.rstrip() for l in lines[-10:] if l.strip()]
            if tail:
                for line in tail:
                    print(_c(DIM, f"    {line}"))
            else:
                print(_c(DIM, "    (log file is empty)"))
        except Exception as e:
            print(_c(DIM, f"    Could not read log: {e}"))
    else:
        print(_c(DIM, "    No log file yet — appears here after first archiving run"))

    # ── How to run ────────────────────────────────────────────────────────────
    _section("How to run")

    if current_os == "Windows":
        _ok("Double-click",         f"{script_name}  (if .py is associated with Python)")
        _ok("Command Prompt",       f"python {script_name}")
        _ok("PowerShell",           f"python {script_name}")
    elif current_os == "Darwin":
        _ok("Terminal",             f"python3 {script_name}")
        _ok("Make executable",      f"chmod +x {script_name}  then  ./{script_name}")
    else:
        _ok("Terminal",             f"python3 {script_name}")
        _ok("Make executable",      f"chmod +x {script_name}  then  ./{script_name}")
        _ok("Desktop launcher",     f"Create a .desktop file pointing to {script_name}")

    _sep()
    print(_c(GR + B, "  ▶  Starting GUI…"))
    print()

    # ── Live terminal mirror ──────────────────────────────────────────────────
    def _terminal_mirror(msg, tag="info"):
        color = (GR  if tag == "success" else
                 RD  if tag == "error"   else
                 YL  if tag == "warning" else
                 DIM)
        ts = _dt.datetime.now().strftime("%H:%M:%S")
        print(_c(color, f"  {ts}  {msg}"))

    # ── Launch GUI ────────────────────────────────────────────────────────────
    root = tk.Tk()
    app  = WaybackGUI(root)

    _gui_log = app._log
    def _patched_log(msg, tag="info"):
        _terminal_mirror(msg, tag)
        _gui_log(msg, tag)
    app._log = _patched_log

    root.mainloop()
    print()
    print(_c(DIM, "  GUI closed."))
    print()
