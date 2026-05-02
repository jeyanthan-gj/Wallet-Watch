"""
tools/config_manager.py — Backwards-compatibility re-export.

All new code imports from security.config_manager directly.
This module exists only so any un-migrated references keep working.
The DeprecationWarning is intentionally removed to keep logs clean.
"""
from security.config_manager import get_secret, get_secrets_list, set_secret  # noqa: F401
