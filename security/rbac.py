"""
security/rbac.py — Role-Based Access Control

Roles
─────
  USER   — standard Telegram user, can only access their own data
  ADMIN  — bot operator (Telegram user_id listed in ADMIN_USER_IDS env var)
            can call admin-only functions and view aggregate stats

Admin user IDs are set via the ADMIN_USER_IDS environment variable:
  ADMIN_USER_IDS=123456789,987654321   (comma-separated Telegram user IDs)

Usage
─────
  from security.rbac import require_ownership, require_admin, get_role, Role

  # In a tool or DB function — raises OwnershipError if user_id != resource owner
  require_ownership(requesting_user_id, resource_owner_id, "transaction #42")

  # Guard an admin-only path
  require_admin(user_id)

  # Check role without raising
  if get_role(user_id) == Role.ADMIN:
      ...
"""

import os
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Role(str, Enum):
    USER  = "user"
    ADMIN = "admin"


class OwnershipError(PermissionError):
    """Raised when a user attempts to access a resource they do not own."""


class AdminRequiredError(PermissionError):
    """Raised when a non-admin user attempts an admin-only action."""


# ── Admin set ─────────────────────────────────────────────────────────────────
def _load_admin_ids() -> frozenset:
    raw = os.getenv("ADMIN_USER_IDS", "")
    ids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return frozenset(ids)


# Loaded once at import time; changing ADMIN_USER_IDS requires a restart.
_ADMIN_IDS: frozenset = _load_admin_ids()


# ── Public API ────────────────────────────────────────────────────────────────

def get_role(user_id: int) -> Role:
    """Return the role for a given Telegram user_id."""
    return Role.ADMIN if user_id in _ADMIN_IDS else Role.USER


def is_admin(user_id: int) -> bool:
    return user_id in _ADMIN_IDS


def require_admin(user_id: int) -> None:
    """
    Raise AdminRequiredError if user_id is not an admin.
    Call at the top of any admin-only function.
    """
    if not is_admin(user_id):
        logger.warning("Admin access denied for user_id=%d", user_id)
        raise AdminRequiredError(
            f"This action requires admin privileges. user_id={user_id} is not an admin."
        )


def require_ownership(
    requesting_user_id: int,
    resource_owner_id: int,
    resource_label: str = "resource",
) -> None:
    """
    Raise OwnershipError if requesting_user_id != resource_owner_id.

    Call this before any read/modify/delete operation on a resource
    that was fetched by its raw ID (IDOR guard).

    Args:
        requesting_user_id:  The authenticated user making the request.
        resource_owner_id:   The user_id stored on the resource in the DB.
        resource_label:      Human-readable label used in the error message.
    """
    if requesting_user_id != resource_owner_id:
        logger.warning(
            "IDOR attempt: user=%d tried to access %s owned by user=%d",
            requesting_user_id, resource_label, resource_owner_id,
        )
        from security.audit_log import log_suspicious_activity
        log_suspicious_activity(
            requesting_user_id,
            f"IDOR: attempted access to {resource_label} owned by user {resource_owner_id}",
        )
        raise OwnershipError(
            f"Access denied: {resource_label} does not belong to you."
        )


def assert_self(requesting_user_id: int, target_user_id: int) -> None:
    """
    Convenience alias — verify a user is only querying their own user record.
    Admins are allowed to query any user's profile.
    """
    if requesting_user_id == target_user_id:
        return
    if is_admin(requesting_user_id):
        return
    require_ownership(requesting_user_id, target_user_id, f"user profile {target_user_id}")
