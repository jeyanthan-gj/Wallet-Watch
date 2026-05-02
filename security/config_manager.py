"""
Secure secret management.

Priority chain (highest → lowest):
  1. Environment variable (.env / Render env vars) — plaintext, OS-protected
  2. Supabase 'config' table — AES-256 encrypted with ENCRYPTION_KEY env var
  3. Supabase backup slots (key_name_2, key_name_3 …)

Secrets are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) before
being written to Supabase, and decrypted on read.  The ENCRYPTION_KEY
itself lives ONLY in environment variables, never in the database.

If ENCRYPTION_KEY is not set, cloud secrets are still read but treated
as plaintext (backwards-compatible with existing un-encrypted rows).
A warning is emitted so operators know to rotate.
"""

import os
import base64
import logging
from database.manager import get_config
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Encryption setup ──────────────────────────────────────────────────────────
_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")   # 32-byte URL-safe base64 key
_fernet = None

if _ENCRYPTION_KEY:
    try:
        from cryptography.fernet import Fernet
        # Fernet requires a 32-byte URL-safe base64 key; generate with:
        #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
        _fernet = Fernet(_ENCRYPTION_KEY.encode())
    except Exception as exc:
        logger.error(
            "ENCRYPTION_KEY is set but Fernet initialisation failed: %s. "
            "Cloud secrets will be read as plaintext.", exc
        )
else:
    logger.warning(
        "ENCRYPTION_KEY not set. Cloud-stored secrets are read as plaintext. "
        "Generate a key and set ENCRYPTION_KEY to enable encryption at rest."
    )


def _decrypt(value: str) -> str:
    """Decrypt a Fernet-encrypted value, or return as-is if not encrypted."""
    if not _fernet or not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        # Value was stored before encryption was enabled — return plaintext
        return value


def _encrypt(value: str) -> str:
    """Encrypt a value for storage in Supabase."""
    if not _fernet or not value:
        return value
    return _fernet.encrypt(value.encode()).decode()


# ── Public API ────────────────────────────────────────────────────────────────

def get_secret(key_name: str, default: str = None) -> str:
    """Return the primary (highest-priority) value for key_name."""
    options = get_secrets_list(key_name)
    return options[0] if options else default


def get_secrets_list(key_name: str) -> list:
    """
    Return all available values for key_name, decrypted, deduplicated.

    Used for key-rotation: caller can try index 0, fall back to 1, etc.
    """
    keys: list[str] = []

    # 1. Environment variable — highest trust, no encryption needed
    env_val = os.getenv(key_name)
    if env_val:
        keys.append(env_val)

    # 2. Primary slot in Supabase (encrypted)
    try:
        cloud_val = _decrypt(get_config(key_name) or "")
        if cloud_val and cloud_val not in keys:
            keys.append(cloud_val)
    except Exception as exc:
        logger.debug("Could not read cloud config '%s': %s", key_name, exc)

    # 3. Backup slots
    for i in range(2, 6):
        try:
            backup_key = f"{key_name}_{i}"
            val = _decrypt(get_config(backup_key) or "")
            if val and val not in keys:
                keys.append(val)
        except Exception:
            break

    return keys


def set_secret(key_name: str, value: str) -> None:
    """
    Write a secret to Supabase, encrypted.
    Never call this from a code path reachable by users.
    """
    from database.manager import set_config
    set_config(key_name, _encrypt(value))
