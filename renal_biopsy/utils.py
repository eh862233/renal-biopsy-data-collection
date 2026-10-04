import getpass
import re
import socket
from datetime import date, datetime
from typing import Optional


def normalize_date(text: str) -> Optional[str]:
    """把 2024/1/5、20240105、2024-01-05、113/01/05（民國）等轉成 YYYY-MM-DD。

    空字串回傳 ""；無法辨識回傳 None。
    """
    s = (text or "").strip()
    if not s:
        return ""
    m = re.fullmatch(r"(\d{8})", s)
    if m:
        y, mo, d = int(s[:4]), int(s[4:6]), int(s[6:])
    else:
        m = re.fullmatch(r"(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
        if not m:
            return None
        y, mo, d = (int(g) for g in m.groups())
        if y < 1000:  # 民國年
            y += 1911
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def calc_age(birth: str, on: str) -> str:
    try:
        b = date.fromisoformat(birth)
        o = date.fromisoformat(on)
    except (TypeError, ValueError):
        return ""
    age = o.year - b.year - ((o.month, o.day) < (b.month, b.day))
    return str(age) if age >= 0 else ""


def calc_bmi(weight: str, height_cm: str) -> str:
    try:
        w = float(weight)
        h = float(height_cm) / 100
        if w <= 0 or h <= 0:
            return ""
        return f"{w / (h * h):.1f}"
    except (TypeError, ValueError):
        return ""


def to_number(value):
    """匯出 Excel 時盡量轉成數字；轉不了就保留原字串（例如 "<0.5"、"Neg"）。"""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    try:
        f = float(s.replace(",", ""))
    except ValueError:
        return s
    return int(f) if f.is_integer() and "." not in s else f


def machine_user() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return f"{user}@{socket.gethostname()}"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
