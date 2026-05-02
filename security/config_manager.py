"""
security/config_manager.py — Secure secret management.

Priority chain (highest → lowest):
  1. Environment variable (.env / Render env vars)
  2. Supabase 'config' table — AES-256 Fernet encrypted if ENCRYPTION_KEY is set
  3. Supabase backup slots (key_name_2, key_name_3 …)

If ENCRYPTION_KEY is not set, cloud values are read as plaintext.
Warning is logged only ONCE at startup, not on every call.
"""

import os
import logging
from database.manager import get_config
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

_ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
_fernet = None
_warned = False   # FIX: warn only once, not on every get_secret() call


def _init_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return
    if _ENCRYPTION_KEY:
        try:
            from cryptography.fernet import Fernet
            _fernet = Fernet(_ENCRYPTION_KEY.encode())
        except Exception as exc:
            logger.error("ENCRYPTION_KEY set but Fernet init failed: %s", exc)
    else:
        if not _warned:
            logger.warning(
                "ENCRYPTION_KEY not set — secrets stored in Supabase are read as plaintext. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )
            _warned = True


def _decrypt(value: str) -> str:
    _init_fernet()
    if not _fernet or not value:
        return value
    try:
        return _fernet.decrypt(value.encode()).decode()
    except Exception:
        return value  # stored before encryption was enabled


def _encrypt(value: str) -> str:
    _init_fernet()
    if not _fernet or not value:
        return value
    return _fernet.encrypt(value.encode()).decode()


def get_secret(key_name: str, default: str = None) -> str:
    options = get_secrets_list(key_name)
    return options[0] if options else default


def get_secrets_list(key_name: str) -> list:
    keys: list = []

    env_val = os.getenv(key_name)
    if env_val:
        keys.append(env_val)

    try:
        cloud_val = _decrypt(get_config(key_name) or "")
        if cloud_val and cloud_val not in keys:
            keys.append(cloud_val)
    except Exception as exc:
        logger.debug("Could not read cloud config '%s': %s", key_name, exc)

    for i in range(2, 6):
        try:
            val = _decrypt(get_config(f"{key_name}_{i}") or "")
            if val and val not in keys:
                keys.append(val)
        except Exception:
            break

    return keys


def set_secret(key_name: str, value: str) -> None:
    """Write an encrypted secret to Supabase. Never call from user-facing code paths."""
    from database.manager import set_config
    set_config(key_name, _encrypt(value))
