"""SQLite 資料庫存取。

資料庫檔可放在醫院共用網路資料夾，為降低多台電腦同時使用的風險：
  * 使用 journal_mode=DELETE（WAL 模式在網路磁碟上不安全）
  * 每次寫入都在短交易 (BEGIN IMMEDIATE) 中完成
  * 編輯鎖：一筆切片紀錄同時只允許一台電腦編輯，其他人以唯讀開啟
  * 版本號：存檔時若資料已被他人修改，拒絕覆蓋 (ConflictError)
"""
import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from . import schema
from .utils import now_str

LOCK_TIMEOUT_MIN = 10  # 超過此時間沒有心跳的鎖視為失效（例如程式當機）

DDL = """
CREATE TABLE IF NOT EXISTS patients (
    chart_no TEXT PRIMARY KEY,
    birth_date TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    past_history TEXT DEFAULT '',
    operation_history TEXT DEFAULT '',
    created_at TEXT, created_by TEXT,
    updated_at TEXT, updated_by TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS biopsies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_no TEXT NOT NULL REFERENCES patients(chart_no) ON DELETE CASCADE,
    biopsy_date TEXT DEFAULT '',
    admission_date TEXT DEFAULT '',
    diagnoses TEXT DEFAULT '[]',
    diagnosis_other TEXT DEFAULT '',
    data TEXT DEFAULT '{}',
    created_at TEXT, created_by TEXT,
    updated_at TEXT, updated_by TEXT,
    version INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_biopsies_chart ON biopsies(chart_no);
CREATE INDEX IF NOT EXISTS idx_biopsies_date ON biopsies(biopsy_date);
CREATE TABLE IF NOT EXISTS labs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    biopsy_id INTEGER NOT NULL REFERENCES biopsies(id) ON DELETE CASCADE,
    panel TEXT NOT NULL,
    lab_date TEXT DEFAULT '',
    "values" TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_labs_biopsy ON labs(biopsy_id);
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    biopsy_id INTEGER NOT NULL REFERENCES biopsies(id) ON DELETE CASCADE,
    filename TEXT DEFAULT '',
    data BLOB,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_images_biopsy ON images(biopsy_id);
CREATE TABLE IF NOT EXISTS locks (
    biopsy_id INTEGER PRIMARY KEY,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    heartbeat TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, user TEXT, action TEXT, chart_no TEXT, biopsy_id INTEGER, detail TEXT
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class ConflictError(Exception):
    """資料在編輯期間已被其他使用者修改。"""


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self.tx():
            for stmt in DDL.strip().split(";"):
                if stmt.strip():
                    self.conn.execute(stmt)

    def close(self):
        self.conn.close()

    @contextmanager
    def tx(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def _audit(self, user, action, chart_no=None, biopsy_id=None, detail=""):
        self.conn.execute(
            "INSERT INTO audit(ts,user,action,chart_no,biopsy_id,detail) VALUES (?,?,?,?,?,?)",
            (now_str(), user, action, chart_no, biopsy_id, detail))

    # ------------------------------------------------------------------ 查詢
    def get_patient(self, chart_no: str) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM patients WHERE chart_no=?",
                                (chart_no,)).fetchone()
        return dict(row) if row else None

    def list_biopsies(self, chart_no: str) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT id, biopsy_date, diagnoses, diagnosis_other, updated_at, updated_by "
            "FROM biopsies WHERE chart_no=? ORDER BY biopsy_date, id", (chart_no,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["diagnoses"] = json.loads(d["diagnoses"] or "[]")
            out.append(d)
        return out

    def empty_record(self, chart_no: str) -> Dict:
        patient = self.get_patient(chart_no)
        if patient is None:
            patient = {"chart_no": chart_no, "version": 0,
                       **{f.key: "" for f in schema.PATIENT_FIELDS}}
        data = {f.key: f.default for f in schema.all_biopsy_fields() if f.default}
        return {
            "patient": patient,
            "patient_orig": {f.key: patient.get(f.key, "") for f in schema.PATIENT_FIELDS},
            "biopsy": {"id": None, "version": 0, "diagnoses": [], "diagnosis_other": "",
                       "data": data},
            "labs": [],
            "images": [],
        }

    def load_record(self, biopsy_id: int) -> Dict:
        b = self.conn.execute("SELECT * FROM biopsies WHERE id=?", (biopsy_id,)).fetchone()
        if b is None:
            raise KeyError(biopsy_id)
        patient = self.get_patient(b["chart_no"])
        data = json.loads(b["data"] or "{}")
        data["biopsy_date"] = b["biopsy_date"]
        data["admission_date"] = b["admission_date"]
        labs = [{"panel": r["panel"], "lab_date": r["lab_date"],
                 "values": json.loads(r["values"] or "{}")}
                for r in self.conn.execute(
                    'SELECT panel, lab_date, "values" FROM labs WHERE biopsy_id=? '
                    "ORDER BY panel, lab_date, id", (biopsy_id,))]
        images = [{"id": r["id"], "filename": r["filename"], "data": r["data"]}
                  for r in self.conn.execute(
                      "SELECT id, filename, data FROM images WHERE biopsy_id=? ORDER BY id",
                      (biopsy_id,))]
        return {
            "patient": patient,
            "patient_orig": {f.key: patient.get(f.key, "") for f in schema.PATIENT_FIELDS},
            "biopsy": {"id": b["id"], "version": b["version"],
                       "diagnoses": json.loads(b["diagnoses"] or "[]"),
                       "diagnosis_other": b["diagnosis_other"] or "",
                       "data": data,
                       "updated_at": b["updated_at"], "updated_by": b["updated_by"]},
            "labs": labs,
            "images": images,
        }

    # ------------------------------------------------------------------ 寫入
    def save_record(self, rec: Dict, user: str) -> int:
        """儲存（上傳）一筆紀錄，回傳 biopsy id。資料已被他人改過時丟出 ConflictError。"""
        p, b = rec["patient"], rec["biopsy"]
        chart_no = p["chart_no"].strip()
        ts = now_str()
        pvals = {f.key: p.get(f.key, "") or "" for f in schema.PATIENT_FIELDS}
        data = dict(b["data"])
        biopsy_date = data.pop("biopsy_date", "") or ""
        admission_date = data.pop("admission_date", "") or ""

        with self.tx() as c:
            cur = c.execute("SELECT version FROM patients WHERE chart_no=?",
                            (chart_no,)).fetchone()
            if cur is None:
                if p.get("version", 0):
                    raise ConflictError("此病人資料已被其他使用者刪除。")
                c.execute(
                    "INSERT INTO patients(chart_no,birth_date,gender,past_history,operation_history,"
                    "created_at,created_by,updated_at,updated_by,version) VALUES (?,?,?,?,?,?,?,?,?,1)",
                    (chart_no, pvals["birth_date"], pvals["gender"], pvals["past_history"],
                     pvals["operation_history"], ts, user, ts, user))
                p["version"] = 1
            elif pvals != rec.get("patient_orig", {}):
                if cur["version"] != p.get("version"):
                    raise ConflictError(
                        "此病人的基本資料（生日、性別、病史）已被其他使用者修改，請重新載入後再編輯。")
                c.execute(
                    "UPDATE patients SET birth_date=?,gender=?,past_history=?,operation_history=?,"
                    "updated_at=?,updated_by=?,version=version+1 WHERE chart_no=?",
                    (pvals["birth_date"], pvals["gender"], pvals["past_history"],
                     pvals["operation_history"], ts, user, chart_no))
                p["version"] = cur["version"] + 1

            diag = json.dumps(b.get("diagnoses", []), ensure_ascii=False)
            data_json = json.dumps(data, ensure_ascii=False)
            if b.get("id") is None:
                cur = c.execute(
                    "INSERT INTO biopsies(chart_no,biopsy_date,admission_date,diagnoses,"
                    "diagnosis_other,data,created_at,created_by,updated_at,updated_by,version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                    (chart_no, biopsy_date, admission_date, diag, b.get("diagnosis_other", ""),
                     data_json, ts, user, ts, user))
                bid = cur.lastrowid
                b["version"] = 1
                self._audit(user, "create", chart_no, bid)
            else:
                bid = b["id"]
                n = c.execute(
                    "UPDATE biopsies SET biopsy_date=?,admission_date=?,diagnoses=?,diagnosis_other=?,"
                    "data=?,updated_at=?,updated_by=?,version=version+1 WHERE id=? AND version=?",
                    (biopsy_date, admission_date, diag, b.get("diagnosis_other", ""), data_json,
                     ts, user, bid, b["version"])).rowcount
                if n == 0:
                    raise ConflictError("此筆切片紀錄已被其他使用者修改或刪除，請重新載入。")
                b["version"] += 1
                self._audit(user, "update", chart_no, bid)
            b["id"] = bid

            c.execute("DELETE FROM labs WHERE biopsy_id=?", (bid,))
            for lab in rec.get("labs", []):
                c.execute('INSERT INTO labs(biopsy_id,panel,lab_date,"values") VALUES (?,?,?,?)',
                          (bid, lab["panel"], lab.get("lab_date", ""),
                           json.dumps(lab.get("values", {}), ensure_ascii=False)))

            keep = [img["id"] for img in rec.get("images", []) if img.get("id")]
            if keep:
                c.execute(f"DELETE FROM images WHERE biopsy_id=? AND id NOT IN "
                          f"({','.join('?' * len(keep))})", (bid, *keep))
            else:
                c.execute("DELETE FROM images WHERE biopsy_id=?", (bid,))
            for img in rec.get("images", []):
                if not img.get("id"):
                    img["id"] = c.execute(
                        "INSERT INTO images(biopsy_id,filename,data,created_at) VALUES (?,?,?,?)",
                        (bid, img.get("filename", ""), img["data"], ts)).lastrowid

        rec["patient_orig"] = pvals
        return bid

    def delete_biopsy(self, biopsy_id: int, user: str):
        with self.tx() as c:
            row = c.execute("SELECT chart_no FROM biopsies WHERE id=?", (biopsy_id,)).fetchone()
            if row is None:
                return
            chart_no = row["chart_no"]
            c.execute("DELETE FROM biopsies WHERE id=?", (biopsy_id,))
            c.execute("DELETE FROM locks WHERE biopsy_id=?", (biopsy_id,))
            self._audit(user, "delete", chart_no, biopsy_id)
            left = c.execute("SELECT COUNT(*) FROM biopsies WHERE chart_no=?",
                             (chart_no,)).fetchone()[0]
            if left == 0:
                c.execute("DELETE FROM patients WHERE chart_no=?", (chart_no,))

    # ------------------------------------------------------------------ 編輯鎖
    def acquire_lock(self, biopsy_id: int, holder: str) -> Tuple[bool, str]:
        """成功回傳 (True, holder)；已被他人鎖定回傳 (False, 對方名稱)。"""
        now = datetime.now()
        with self.tx() as c:
            row = c.execute("SELECT holder, heartbeat FROM locks WHERE biopsy_id=?",
                            (biopsy_id,)).fetchone()
            if row and row["holder"] != holder:
                hb = datetime.strptime(row["heartbeat"], "%Y-%m-%d %H:%M:%S")
                if now - hb < timedelta(minutes=LOCK_TIMEOUT_MIN):
                    return False, row["holder"]
            ts = now.strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT OR REPLACE INTO locks(biopsy_id,holder,acquired_at,heartbeat) "
                      "VALUES (?,?,?,?)", (biopsy_id, holder, ts, ts))
        return True, holder

    def refresh_lock(self, biopsy_id: int, holder: str):
        with self.tx() as c:
            c.execute("UPDATE locks SET heartbeat=? WHERE biopsy_id=? AND holder=?",
                      (now_str(), biopsy_id, holder))

    def release_lock(self, biopsy_id: int, holder: str):
        with self.tx() as c:
            c.execute("DELETE FROM locks WHERE biopsy_id=? AND holder=?", (biopsy_id, holder))

    # ------------------------------------------------------------------ 匯出用
    def all_diagnoses_in_use(self) -> List[str]:
        found = set()
        for (d,) in self.conn.execute("SELECT diagnoses FROM biopsies"):
            found.update(json.loads(d or "[]"))
        return sorted(found)

    def query_records(self, year_from=None, year_to=None, genders=None, diagnoses=None,
                      age_min=None, age_max=None, chart_nos=None) -> List[Dict]:
        """依條件篩選，回傳完整紀錄列表（年齡在 Python 端計算）。"""
        from .utils import calc_age
        sql = ("SELECT b.id FROM biopsies b JOIN patients p ON p.chart_no=b.chart_no WHERE 1=1")
        args = []
        if year_from:
            sql += " AND b.biopsy_date >= ?"
            args.append(f"{int(year_from):04d}-01-01")
        if year_to:
            sql += " AND b.biopsy_date <= ?"
            args.append(f"{int(year_to):04d}-12-31")
        if genders:
            sql += f" AND p.gender IN ({','.join('?' * len(genders))})"
            args.extend(genders)
        if chart_nos:
            sql += f" AND b.chart_no IN ({','.join('?' * len(chart_nos))})"
            args.extend(chart_nos)
        sql += " ORDER BY b.biopsy_date, b.chart_no, b.id"
        out = []
        for (bid,) in self.conn.execute(sql, args).fetchall():
            rec = self.load_record(bid)
            if diagnoses:
                if not set(diagnoses) & set(rec["biopsy"]["diagnoses"]):
                    continue
            if age_min is not None or age_max is not None:
                age = calc_age(rec["patient"]["birth_date"], rec["biopsy"]["data"]["biopsy_date"])
                if age == "":
                    continue
                if age_min is not None and int(age) < age_min:
                    continue
                if age_max is not None and int(age) > age_max:
                    continue
            out.append(rec)
        return out

    # ------------------------------------------------------------------ 備份
    def auto_backup(self, keep: int = 30) -> Optional[str]:
        """每天第一次開啟時，在資料庫旁的 backups 資料夾建立一份備份。"""
        today = datetime.now().strftime("%Y%m%d")
        row = self.conn.execute("SELECT value FROM meta WHERE key='last_backup'").fetchone()
        if row and row["value"] == today:
            return None
        folder = os.path.join(os.path.dirname(os.path.abspath(self.path)), "backups")
        os.makedirs(folder, exist_ok=True)
        dest = os.path.join(folder, f"renal_biopsy_{today}.db")
        bconn = sqlite3.connect(dest)
        try:
            self.conn.backup(bconn)
        finally:
            bconn.close()
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('last_backup',?)", (today,))
        files = sorted(f for f in os.listdir(folder) if f.startswith("renal_biopsy_"))
        for old in files[:-keep]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        return dest
