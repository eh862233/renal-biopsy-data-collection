"""每台電腦各自的設定（資料庫位置），存在使用者 AppData 中。"""
import hashlib
import hmac
import json
import os
import sys

APP_NAME = "RenalBiopsyDB"
APP_TITLE = "腎臟切片資料收集系統"

ADMIN_USERNAME = "neph88099"
# 管理者密碼只存 SHA-256 雜湊，不以明碼寫在程式中
ADMIN_PASSWORD_SHA256 = "1526c98482491889c27d911980903c936a0ab381a3d91658c968775fca0fdacb"


def check_admin(username: str, password: str) -> bool:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return username == ADMIN_USERNAME and hmac.compare_digest(digest, ADMIN_PASSWORD_SHA256)


def app_dir() -> str:
    """程式所在資料夾（打包成 exe 時為 exe 所在位置）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, APP_NAME, "config.json")


def load_config() -> dict:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict):
    path = _config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def default_db_path() -> str:
    return os.path.join(app_dir(), "data", "renal_biopsy.db")


def get_db_path() -> str:
    return load_config().get("db_path") or default_db_path()


def set_db_path(path: str):
    cfg = load_config()
    cfg["db_path"] = path
    save_config(cfg)
