import os
from database.manager import get_config
from dotenv import load_dotenv

load_dotenv()

def get_secret(key_name: str, default: str = None):
    """
    Fetches a sensitive key/setting.
    Priority:
    1. Supabase 'config' table (allows remote dashboard updates)
    2. Environment Variable (.env or Render dashboard)
    3. Default value
    """
    try:
        # 1. Try Supabase
        cloud_val = get_config(key_name)
        if cloud_val:
            return cloud_val
    except Exception:
        # If DB connection fails or table not ready, fallback immediately
        pass
        
    # 2. Try Environment Variable
    env_val = os.getenv(key_name)
    if env_val:
        return env_val
        
    # 3. Fallback to default
    return default
