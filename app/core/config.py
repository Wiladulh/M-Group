from dataclasses import dataclass
from pathlib import Path
import os

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str
    port: int
    db_path: Path
    admin_token: str
    admin_username: str = ""
    admin_password_hash: str = ""

def get_settings() -> Settings:
    data_dir=Path(os.getenv("M_GROUP_DATA_DIR",str(Path.home()/".local/share/M_GROUP"))).expanduser()
    return Settings(
        data_dir,
        os.getenv("M_GROUP_HOST","127.0.0.1"),
        int(os.getenv("M_GROUP_PORT","8011")),
        Path(os.getenv("M_GROUP_DB_PATH",str(data_dir/"M_GROUP.db"))).expanduser(),
        os.getenv("M_GROUP_ADMIN_TOKEN",""),
        os.getenv("M_GROUP_ADMIN_USERNAME",""),
        os.getenv("M_GROUP_ADMIN_PASSWORD_HASH",""),
    )
