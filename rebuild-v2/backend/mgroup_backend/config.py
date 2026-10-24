from dataclasses import dataclass
import os
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv('MGROUP_DB_PATH', str(Path(__file__).resolve().parents[2] / 'var' / 'mgroup-v2.sqlite3'))
    admin_token: str = os.getenv('MGROUP_ADMIN_TOKEN', '')
    device_key_pepper: str = os.getenv('MGROUP_DEVICE_KEY_PEPPER', '')

settings = Settings()
