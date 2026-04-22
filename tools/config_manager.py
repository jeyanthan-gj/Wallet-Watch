import os
from database.manager import get_config
from dotenv import load_dotenv

load_dotenv()

def get_secret(key_name: str, default: str = None):
    """Fetches the primary key (Env first, then Cloud)."""
    options = get_secrets_list(key_name)
    return options[0] if options else default

def get_secrets_list(key_name: str) -> list:
    """
    Returns a unique list of available keys for rotation.
    Priority:
    1. Environment Variable (.env)
    2. Supabase 'config' table (key_name)
    3. Supabase 'config' table backups (key_name_2, key_name_3, etc.)
    """
    keys = []
    
    # 1. Primary from ENV
    env_val = os.getenv(key_name)
    if env_val:
        keys.append(env_val)
        
    # 2. Primary from Cloud
    try:
        cloud_val = get_config(key_name)
        if cloud_val and cloud_val not in keys:
            keys.append(cloud_val)
    except Exception:
        pass

    # 3. Backups from Cloud (up to 5 versions)
    for i in range(2, 6):
        try:
            backup_key = f"{key_name}_{i}"
            val = get_config(backup_key)
            if val and val not in keys:
                keys.append(val)
        except Exception:
            break
            
    return keys
