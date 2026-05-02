"""
tools/config_manager.py  —  DEPRECATED SHIM

This module is kept only for backwards-compatibility with any code that
still imports from 'tools.config_manager'.  All new code must import from
'security.config_manager' instead, which adds Fernet encryption for secrets
stored in Supabase.

This shim re-exports the secure versions so existing callers get the
hardened implementation transparently.
"""

import warnings
from security.config_manager import get_secret, get_secrets_list, set_secret  # noqa: F401

warnings.warn(
    "tools.config_manager is deprecated. Import from security.config_manager instead.",
    DeprecationWarning,
    stacklevel=2,
)
