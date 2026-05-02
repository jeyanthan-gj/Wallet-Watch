"""
Rate limiter for Telegram bot messages.

Uses a sliding-window token-bucket per user_id stored in memory.
All state is in-process; on Render free tier there is one process,
so this is sufficient. For multi-instance deployments, back this
with Redis.

Limits (tunable via env):
  RATE_LIMIT_MESSAGES  — max messages per window (default 20)
  RATE_LIMIT_WINDOW    — window in seconds        (default 60)
  RATE_LIMIT_BURST     — short burst cap           (default 5 per 10 s)
"""

import os
import time
import asyncio
from collections import defaultdict, deque
from typing import Deque, Dict

# ── Config ────────────────────────────────────────────────────────────────────
_WINDOW     = int(os.getenv("RATE_LIMIT_WINDOW",   "60"))   # seconds
_MAX_MSGS   = int(os.getenv("RATE_LIMIT_MESSAGES", "20"))   # per window
_BURST_WIN  = 10                                             # seconds
_BURST_MAX  = int(os.getenv("RATE_LIMIT_BURST",   "5"))    # per burst window

# ── State (in-process) ────────────────────────────────────────────────────────
# deque of timestamps for each user_id
_timestamps: Dict[int, Deque[float]] = defaultdict(deque)
_lock = asyncio.Lock()


async def check_rate_limit(user_id: int) -> tuple[bool, str]:
    """
    Returns (allowed: bool, reason: str).
    Call before processing each message.
    """
    async with _lock:
        now = time.monotonic()
        ts = _timestamps[user_id]

        # Evict timestamps outside the main window
        while ts and ts[0] < now - _WINDOW:
            ts.popleft()

        # --- Burst check (short window) ---
        burst_count = sum(1 for t in ts if t >= now - _BURST_WIN)
        if burst_count >= _BURST_MAX:
            wait = int(_BURST_WIN - (now - ts[-_BURST_MAX]) + 1)
            return False, (
                f"⏳ Slow down! You sent {_BURST_MAX} messages in {_BURST_WIN}s. "
                f"Please wait ~{wait}s."
            )

        # --- Main window check ---
        if len(ts) >= _MAX_MSGS:
            oldest = ts[0]
            wait = int(_WINDOW - (now - oldest) + 1)
            return False, (
                f"⏳ You've reached the limit of {_MAX_MSGS} messages per minute. "
                f"Please wait ~{wait}s."
            )

        ts.append(now)
        return True, ""


def reset_rate_limit(user_id: int) -> None:
    """Clear rate-limit state for a user (e.g. after a ban is lifted)."""
    _timestamps.pop(user_id, None)
