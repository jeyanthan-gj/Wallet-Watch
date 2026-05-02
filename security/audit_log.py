"""
Audit logger for security-sensitive operations.

Writes structured JSON audit events to Supabase 'audit_log' table.
Falls back to stderr if Supabase is unavailable so events are never lost.

Logged events:
  - transaction.delete
  - transaction.edit
  - recurring.remove
  - rate_limit.blocked
  - auth.suspicious          (user_id injection attempt)

Schema (create in Supabase SQL editor):
  CREATE TABLE audit_log (
      id          bigserial PRIMARY KEY,
      event_type  text        NOT NULL,
      user_id     bigint      NOT NULL,
      metadata    jsonb,
      created_at  timestamptz NOT NULL DEFAULT now()
  );
  -- Index for fast per-user lookups
  CREATE INDEX ON audit_log (user_id, created_at DESC);
  -- RLS: only service role can read
  ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
  CREATE POLICY "service only" ON audit_log USING (false);
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

# Import lazily to avoid circular imports at module load time
_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is None:
        from database.supabase_client import supabase as _sb
        _supabase = _sb
    return _supabase


def _sanitise_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strip any values that look like secrets/tokens before storing.
    Keys containing these substrings get their values replaced.
    """
    _SENSITIVE = {"key", "token", "secret", "password", "api"}
    return {
        k: "***REDACTED***" if any(s in k.lower() for s in _SENSITIVE) else v
        for k, v in metadata.items()
    }


def log_event(
    event_type: str,
    user_id: int,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Fire-and-forget audit event. Never raises — audit failures must not
    break the user-facing flow.
    """
    safe_meta = _sanitise_metadata(metadata or {})
    record = {
        "event_type": event_type,
        "user_id": user_id,
        "metadata": safe_meta,
        "created_at": datetime.now(IST).isoformat(),
    }

    # Always emit to application logs (visible in Render log drain)
    logger.info("AUDIT %s user=%s meta=%s", event_type, user_id, json.dumps(safe_meta))

    # Best-effort write to Supabase
    try:
        _get_supabase().table("audit_log").insert(record).execute()
    except Exception as exc:
        logger.error("Audit write failed (%s): %s", event_type, exc)


# ── Convenience helpers ───────────────────────────────────────────────────────

def log_transaction_delete(user_id: int, transaction_id: int, amount: float, category: str) -> None:
    log_event("transaction.delete", user_id, {
        "transaction_id": transaction_id,
        "amount": amount,
        "category": category,
    })


def log_transaction_edit(user_id: int, transaction_id: int, changes: Dict[str, Any]) -> None:
    log_event("transaction.edit", user_id, {
        "transaction_id": transaction_id,
        "changes": changes,
    })


def log_rate_limit_blocked(user_id: int, reason: str) -> None:
    log_event("rate_limit.blocked", user_id, {"reason": reason})


def log_suspicious_activity(user_id: int, detail: str) -> None:
    log_event("auth.suspicious", user_id, {"detail": detail})
