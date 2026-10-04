"""SQLite 資料庫存取。

資料庫檔可放在醫院共用網路資料夾，為降低多台電腦同時使用的風險：
  * 使用 journal_mode=DELETE（WAL 模式在網路磁碟上不安全）
  * 每次寫入都在短交易 (BEGIN IMMEDIATE) 中完成
  * 編輯鎖：一筆切片紀錄同時只允許一台電腦編輯，其他人以唯讀開啟
  * 版本號：存檔時若資料已被他人修改，拒絕覆蓋 (ConflictError)

病人以內部編號 (patients.id) 識別；病歷號、身分證字號至少要有一個，且各自不可重複。
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import schema
from .utils import calc_age, normalize_national_id, now_str

LOCK_TIMEOUT_MIN = 10  # 超過此時間沒有心跳的鎖視為失效（例如程式當機）

PATIENTS_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chart_no TEXT UNIQUE,
    national_id TEXT UNIQUE,
    name TEXT DEFAULT '',
    birth_date TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    past_history TEXT DEFAULT '',
    operation_history TEXT DEFAULT '',
    created_at TEXT, created_by TEXT,
    updated_at TEXT, updated_by TEXT,
    version INTEGER NOT NULL DEFAULT 1
)"""

BIOPSIES_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id INTEGER NOT NULL REFERENCES {patients}(id) ON DELETE CASCADE,
    biopsy_date TEXT DEFAULT '',
    admission_date TEXT DEFAULT '',
    diagnoses TEXT DEFAULT '[]',
    diagnosis_other TEXT DEFAULT '',
    data TEXT DEFAULT '{{}}',
    created_at TEXT, created_by TEXT,
    updated_at TEXT, updated_by TEXT,
    version INTEGER NOT NULL DEFAULT 1
)"""

DDL = [
    PATIENTS_DDL.format(name="patients"),
    BIOPSIES_DDL.format(name="biopsies", patients="patients"),
    "CREATE INDEX IF NOT EXISTS idx_biopsies_patient ON biopsies(patient_id)",
    "CREATE INDEX IF NOT EXISTS idx_biopsies_date ON biopsies(biopsy_date)",
    """CREATE TABLE IF NOT EXISTS labs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        biopsy_id INTEGER NOT NULL REFERENCES biopsies(id) ON DELETE CASCADE,
        panel TEXT NOT NULL,
        lab_date TEXT DEFAULT '',
        "values" TEXT DEFAULT '{}'
    )""",
    "CREATE INDEX IF NOT EXISTS idx_labs_biopsy ON labs(biopsy_id)",
    """CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        biopsy_id INTEGER NOT NULL REFERENCES biopsies(id) ON DELETE CASCADE,
        filename TEXT DEFAULT '',
        data BLOB,
        created_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_images_biopsy ON images(biopsy_id)",
    """CREATE TABLE IF NOT EXISTS locks (
        biopsy_id INTEGER PRIMARY KEY,
        holder TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        heartbeat TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT, user TEXT, action TEXT, chart_no TEXT, biopsy_id INTEGER, detail TEXT
    )""",
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)",
]

PATIENT_COLS = [f.key for f in schema.PATIENT_FIELDS]


class ConflictError(Exception):
    """資料在編輯期間已被其他使用者修改。"""


class DuplicateIdentifierError(ValueError):
    """病歷號或身分證字號已屬於另一位病人。"""


def _clean_ids(p: Dict) -> Tuple[Optional[str], Optional[str]]:
    chart = (p.get("chart_no") or "").strip() or None
    nid = normalize_national_id(p.get("national_id")) or None
    return chart, nid


def patient_label(p: Dict) -> str:
    """畫面與紀錄用的病人代稱，例如「王小明 病歷號 123 / A123456789」。"""
    ids = [x for x in (p.get("chart_no"), p.get("national_id")) if x]
    return " ".join(x for x in (p.get("name"), " / ".join(ids)) if x)


class Database:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=DELETE")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def _ensure_schema(self):
        self._migrate_v1()
        with self.tx():
            for stmt in DDL:
                self.conn.execute(stmt)

    def _migrate_v1(self):
        """舊版資料庫（以病歷號為主鍵）升級為新版（病人內部編號 + 病歷號／身分證字號）。"""
        cols = [r["name"] for r in self.conn.execute("PRAGMA table_info(patients)")]
        if not cols or "id" in cols:
            return
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.tx() as c:
                c.execute(PATIENTS_DDL.format(name="patients_v2"))
                c.execute(
                    "INSERT INTO patients_v2(chart_no,birth_date,gender,past_history,operation_history,"
                    "created_at,created_by,updated_at,updated_by,version) "
                    "SELECT chart_no,birth_date,gender,past_history,operation_history,"
                    "created_at,created_by,updated_at,updated_by,version FROM patients")
                c.execute(BIOPSIES_DDL.format(name="biopsies_v2", patients="patients_v2"))
                c.execute(
                    "INSERT INTO biopsies_v2(id,patient_id,biopsy_date,admission_date,diagnoses,"
                    "diagnosis_other,data,created_at,created_by,updated_at,updated_by,version) "
                    "SELECT b.id,p.id,b.biopsy_date,b.admission_date,b.diagnoses,b.diagnosis_other,"
                    "b.data,b.created_at,b.created_by,b.updated_at,b.updated_by,b.version "
                    "FROM biopsies b JOIN patients_v2 p ON p.chart_no=b.chart_no")
                c.execute("DROP TABLE biopsies")
                c.execute("DROP TABLE patients")
                c.execute("ALTER TABLE patients_v2 RENAME TO patients")
                c.execute("ALTER TABLE biopsies_v2 RENAME TO biopsies")
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

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

    def _audit(self, user, action, patient: Optional[Dict] = None, biopsy_id=None, detail=""):
        self.conn.execute(
            "INSERT INTO audit(ts,user,action,chart_no,biopsy_id,detail) VALUES (?,?,?,?,?,?)",
            (now_str(), user, action, patient_label(patient) if patient else None, biopsy_id,
             detail))

    # ------------------------------------------------------------------ 查詢
    def find_patient(self, term: str) -> Optional[Dict]:
        """以病歷號或身分證字號（不分大小寫）找病人。"""
        term = (term or "").strip()
        if not term:
            return None
        row = self.conn.execute(
            "SELECT * FROM patients WHERE chart_no=? OR national_id=? ORDER BY chart_no=? DESC",
            (term, normalize_national_id(term), term)).fetchone()
        return dict(row) if row else None

    def get_patient(self, patient_id: int) -> Optional[Dict]:
        row = self.conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
        return dict(row) if row else None

    def list_biopsies(self, patient_id: int) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT id, biopsy_date, diagnoses, diagnosis_other, updated_at, updated_by "
            "FROM biopsies WHERE patient_id=? ORDER BY biopsy_date, id", (patient_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["diagnoses"] = json.loads(d["diagnoses"] or "[]")
            out.append(d)
        return out

    @staticmethod
    def _orig(patient: Dict) -> Dict:
        return {k: patient.get(k) or "" for k in PATIENT_COLS}

    def empty_record(self, patient: Optional[Dict] = None, **identifiers) -> Dict:
        """新切片紀錄。patient 為既有病人；新病人可用 chart_no=/national_id= 預先帶入號碼。"""
        if patient is None:
            patient = {"id": None, "version": 0, **{k: "" for k in PATIENT_COLS}}
            patient.update({k: v for k, v in identifiers.items() if k in PATIENT_COLS})
        data = {f.key: f.default for f in schema.all_biopsy_fields() if f.default}
        return {
            "patient": dict(patient),
            "patient_orig": self._orig(patient) if patient.get("id") else {},
            "biopsy": {"id": None, "version": 0, "diagnoses": [], "diagnosis_other": "",
                       "data": data},
            "labs": [],
            "images": [],
        }

    def load_record(self, biopsy_id: int) -> Dict:
        b = self.conn.execute("SELECT * FROM biopsies WHERE id=?", (biopsy_id,)).fetchone()
        if b is None:
            raise KeyError(biopsy_id)
        patient = self.get_patient(b["patient_id"])
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
            "patient_orig": self._orig(patient),
            "biopsy": {"id": b["id"], "version": b["version"],
                       "diagnoses": json.loads(b["diagnoses"] or "[]"),
                       "diagnosis_other": b["diagnosis_other"] or "",
                       "data": data,
                       "updated_at": b["updated_at"], "updated_by": b["updated_by"]},
            "labs": labs,
            "images": images,
        }

    # ------------------------------------------------------------------ 寫入
    def _check_unique(self, c, chart, nid, exclude_id):
        for col, val, label in (("chart_no", chart, "病歷號"), ("national_id", nid, "身分證字號")):
            if not val:
                continue
            row = c.execute(f"SELECT * FROM patients WHERE {col}=? AND id IS NOT ?",
                            (val, exclude_id)).fetchone()
            if row:
                raise DuplicateIdentifierError(
                    f"{label}「{val}」已經屬於另一位病人（{patient_label(dict(row))}）。\n"
                    "請確認號碼是否輸入錯誤；若是同一位病人，請返回查詢頁用該號碼開啟。")

    def _insert_patient(self, c, pvals: Dict, user: str, ts: str) -> int:
        cols = PATIENT_COLS + ["created_at", "created_by", "updated_at", "updated_by", "version"]
        vals = [pvals[k] for k in PATIENT_COLS] + [ts, user, ts, user, 1]
        return c.execute(f"INSERT INTO patients({','.join(cols)}) VALUES "
                         f"({','.join('?' * len(cols))})", vals).lastrowid

    def _update_patient(self, c, pid: int, pvals: Dict, user: str, ts: str):
        sets = ",".join(f"{k}=?" for k in PATIENT_COLS)
        c.execute(f"UPDATE patients SET {sets},updated_at=?,updated_by=?,version=version+1 "
                  "WHERE id=?", [pvals[k] for k in PATIENT_COLS] + [ts, user, pid])

    @staticmethod
    def _patient_values(p: Dict) -> Dict:
        chart, nid = _clean_ids(p)
        if not chart and not nid:
            raise ValueError("病歷號與身分證字號至少要填一個。")
        pvals = {k: (p.get(k) or "") for k in PATIENT_COLS}
        pvals["chart_no"], pvals["national_id"] = chart, nid
        return pvals

    def save_record(self, rec: Dict, user: str) -> int:
        """儲存（上傳）一筆紀錄，回傳 biopsy id。

        資料已被他人改過時丟出 ConflictError；號碼與其他病人重複時丟出 DuplicateIdentifierError。
        """
        p, b = rec["patient"], rec["biopsy"]
        pvals = self._patient_values(p)
        ts = now_str()
        data = dict(b["data"])
        biopsy_date = data.pop("biopsy_date", "") or ""
        admission_date = data.pop("admission_date", "") or ""

        with self.tx() as c:
            if p.get("id") is None:
                self._check_unique(c, pvals["chart_no"], pvals["national_id"], None)
                pid = self._insert_patient(c, pvals, user, ts)
                p["version"] = 1
            else:
                pid = p["id"]
                cur = c.execute("SELECT version FROM patients WHERE id=?", (pid,)).fetchone()
                if cur is None:
                    raise ConflictError("此病人資料已被其他使用者刪除。")
                if self._orig(pvals) != rec.get("patient_orig", {}):
                    if cur["version"] != p.get("version"):
                        raise ConflictError(
                            "此病人的基本資料（號碼、姓名、生日、性別、病史）已被其他使用者修改，"
                            "請重新載入後再編輯。")
                    self._check_unique(c, pvals["chart_no"], pvals["national_id"], pid)
                    self._update_patient(c, pid, pvals, user, ts)
                    p["version"] = cur["version"] + 1
            p["id"] = pid

            diag = json.dumps(b.get("diagnoses", []), ensure_ascii=False)
            data_json = json.dumps(data, ensure_ascii=False)
            if b.get("id") is None:
                bid = c.execute(
                    "INSERT INTO biopsies(patient_id,biopsy_date,admission_date,diagnoses,"
                    "diagnosis_other,data,created_at,created_by,updated_at,updated_by,version) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,1)",
                    (pid, biopsy_date, admission_date, diag, b.get("diagnosis_other", ""),
                     data_json, ts, user, ts, user)).lastrowid
                b["version"] = 1
                self._audit(user, "create", pvals, bid)
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
                self._audit(user, "update", pvals, bid)
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

        rec["patient_orig"] = self._orig(pvals)
        return bid

    def delete_biopsy(self, biopsy_id: int, user: str):
        with self.tx() as c:
            row = c.execute("SELECT patient_id FROM biopsies WHERE id=?", (biopsy_id,)).fetchone()
            if row is None:
                return
            pid = row["patient_id"]
            patient = dict(c.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone())
            c.execute("DELETE FROM biopsies WHERE id=?", (biopsy_id,))
            c.execute("DELETE FROM locks WHERE biopsy_id=?", (biopsy_id,))
            self._audit(user, "delete", patient, biopsy_id)
            left = c.execute("SELECT COUNT(*) FROM biopsies WHERE patient_id=?", (pid,)).fetchone()[0]
            if left == 0:
                c.execute("DELETE FROM patients WHERE id=?", (pid,))

    # ------------------------------------------------------------------ 匯入（TSN Excel）
    class _DryRun(Exception):
        pass

    def import_items(self, items: List[Dict], user: str, dry_run: bool = False) -> Dict:
        """匯入外部資料。既有病人／切片（同身分證或病歷號 + 同切片日期）只補空白欄位，不覆蓋。

        dry_run=True 時只計算會發生什麼，不寫入。回傳統計數字。
        """
        stats = {"patients_new": 0, "patients_updated": 0, "biopsies_new": 0,
                 "biopsies_updated": 0, "unchanged": 0}
        ts = now_str()
        try:
            with self.tx() as c:
                for it in items:
                    self._import_one(c, it, user, ts, stats)
                if dry_run:
                    raise Database._DryRun
        except Database._DryRun:
            pass
        return stats

    def _import_one(self, c, it: Dict, user: str, ts: str, stats: Dict):
        pin = {k: it["patient"].get(k) or "" for k in PATIENT_COLS}
        chart, nid = _clean_ids(pin)
        pin["chart_no"], pin["national_id"] = chart, nid
        row = None
        if nid:
            row = c.execute("SELECT * FROM patients WHERE national_id=?", (nid,)).fetchone()
        if row is None and chart:
            row = c.execute("SELECT * FROM patients WHERE chart_no=?", (chart,)).fetchone()
        if row is None:
            self._check_unique(c, chart, nid, None)
            pid = self._insert_patient(c, pin, user, ts)
            patient = pin
            stats["patients_new"] += 1
        else:
            patient = dict(row)
            pid = patient["id"]
            filled = {k: v for k, v in pin.items() if v and not patient.get(k)}
            if filled:
                self._check_unique(c, filled.get("chart_no"), filled.get("national_id"), pid)
                patient.update(filled)
                self._update_patient(c, pid, patient, user, ts)
                stats["patients_updated"] += 1

        bdate = it["biopsy_date"]
        brow = c.execute("SELECT * FROM biopsies WHERE patient_id=? AND biopsy_date=? ORDER BY id",
                         (pid, bdate)).fetchone()
        if brow is None:
            bid = c.execute(
                "INSERT INTO biopsies(patient_id,biopsy_date,admission_date,diagnoses,diagnosis_other,"
                "data,created_at,created_by,updated_at,updated_by,version) "
                "VALUES (?,?,'',?,?,?,?,?,?,?,1)",
                (pid, bdate, json.dumps(it["diagnoses"], ensure_ascii=False),
                 it["diagnosis_other"], json.dumps(it["data"], ensure_ascii=False),
                 ts, user, ts, user)).lastrowid
            for panel, values in it["labs"].items():
                c.execute('INSERT INTO labs(biopsy_id,panel,lab_date,"values") VALUES (?,?,?,?)',
                          (bid, panel, bdate, json.dumps(values, ensure_ascii=False)))
            self._audit(user, "import", patient, bid)
            stats["biopsies_new"] += 1
            return

        bid = brow["id"]
        changed = False
        data = json.loads(brow["data"] or "{}")
        for k, v in it["data"].items():
            if v not in ("", [], None) and data.get(k) in (None, "", []):
                data[k] = v
                changed = True
        diagnoses = json.loads(brow["diagnoses"] or "[]")
        dx_other = brow["diagnosis_other"] or ""
        if not diagnoses and it["diagnoses"]:
            diagnoses, changed = it["diagnoses"], True
        if not dx_other and it["diagnosis_other"]:
            dx_other, changed = it["diagnosis_other"], True
        for panel, values in it["labs"].items():
            lrow = c.execute('SELECT id, "values" FROM labs WHERE biopsy_id=? AND panel=? '
                             "AND lab_date=? ORDER BY id", (bid, panel, bdate)).fetchone()
            if lrow is None:
                c.execute('INSERT INTO labs(biopsy_id,panel,lab_date,"values") VALUES (?,?,?,?)',
                          (bid, panel, bdate, json.dumps(values, ensure_ascii=False)))
                changed = True
                continue
            cur = json.loads(lrow["values"] or "{}")
            add = {a: v for a, v in values.items() if not cur.get(a)}
            if add:
                cur.update(add)
                c.execute('UPDATE labs SET "values"=? WHERE id=?',
                          (json.dumps(cur, ensure_ascii=False), lrow["id"]))
                changed = True
        if changed:
            c.execute("UPDATE biopsies SET data=?,diagnoses=?,diagnosis_other=?,updated_at=?,"
                      "updated_by=?,version=version+1 WHERE id=?",
                      (json.dumps(data, ensure_ascii=False),
                       json.dumps(diagnoses, ensure_ascii=False), dx_other, ts, user, bid))
            self._audit(user, "import-update", patient, bid)
            stats["biopsies_updated"] += 1
        else:
            stats["unchanged"] += 1

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
    def query_records(self, year_from=None, year_to=None, genders=None, diagnoses=None,
                      age_min=None, age_max=None, chart_nos=None) -> List[Dict]:
        """依條件篩選，回傳完整紀錄列表（年齡在 Python 端計算）。

        chart_nos 可混合病歷號與身分證字號。
        """
        sql = "SELECT b.id FROM biopsies b JOIN patients p ON p.id=b.patient_id WHERE 1=1"
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
            q = ",".join("?" * len(chart_nos))
            sql += f" AND (p.chart_no IN ({q}) OR p.national_id IN ({q}))"
            args.extend(chart_nos)
            args.extend(normalize_national_id(x) for x in chart_nos)
        sql += " ORDER BY b.biopsy_date, p.chart_no, p.national_id, b.id"
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

    # ------------------------------------------------------------------ 備份 / 還原
    def backup_folder(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(self.path)), "backups")

    def _copy_to(self, dest: str):
        """用 SQLite 線上備份 API 複製資料庫（不需要其他人關閉程式）。"""
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        tmp = dest + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)
        bconn = sqlite3.connect(tmp)
        try:
            self.conn.backup(bconn)
        finally:
            bconn.close()
        os.replace(tmp, dest)

    def auto_backup(self, keep: int = 30) -> Optional[str]:
        """每天第一次開啟時，在資料庫旁的 backups 資料夾建立一份備份。"""
        today = datetime.now().strftime("%Y%m%d")
        row = self.conn.execute("SELECT value FROM meta WHERE key='last_backup'").fetchone()
        if row and row["value"] == today:
            return None
        folder = self.backup_folder()
        dest = os.path.join(folder, f"renal_biopsy_{today}.db")
        self._copy_to(dest)
        with self.tx() as c:
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('last_backup',?)", (today,))
        files = sorted(f for f in os.listdir(folder)
                       if f.startswith("renal_biopsy_") and f.endswith(".db"))
        for old in files[:-keep]:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
        return dest

    def backup_to(self, dest: str, user: str) -> Dict:
        """立即備份到指定檔案（例如隨身碟），完成後驗證並回傳備份內容摘要。"""
        if os.path.exists(dest) and _same_file(dest, self.path):
            raise ValueError("不能把備份存成目前正在使用的資料庫檔。")
        self._copy_to(dest)
        info = inspect_backup(dest)
        with self.tx():
            self._audit(user, "backup", detail=dest)
        return info

    def active_locks(self, exclude_holder: str = "") -> List[str]:
        """目前（未逾時）正在編輯紀錄的其他電腦。"""
        limit = (datetime.now() - timedelta(minutes=LOCK_TIMEOUT_MIN)).strftime("%Y-%m-%d %H:%M:%S")
        rows = self.conn.execute(
            "SELECT DISTINCT holder FROM locks WHERE heartbeat >= ? AND holder != ?",
            (limit, exclude_holder)).fetchall()
        return [r["holder"] for r in rows]

    def safety_copy(self, prefix: str) -> str:
        """在 backups 資料夾另存一份目前資料（還原、匯入前使用），回傳檔案路徑。"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety = os.path.join(self.backup_folder(), f"{prefix}_{stamp}.db")
        n = 1
        while os.path.exists(safety):  # 絕不覆蓋既有檔案（可能正是要還原的那個）
            n += 1
            safety = os.path.join(self.backup_folder(), f"{prefix}_{stamp}_{n}.db")
        self._copy_to(safety)
        return safety

    def restore_from(self, src: str, user: str) -> str:
        """用備份檔取代目前資料庫內容。

        還原前會先把目前的資料存一份到 backups/before_restore_*.db，
        萬一選錯備份也可以再還原回來。回傳該安全備份的路徑。
        """
        if _same_file(src, self.path):
            raise ValueError("選擇的檔案就是目前正在使用的資料庫。")
        inspect_backup(src)  # 不是有效備份時丟出 ValueError
        safety = self.safety_copy("before_restore")
        sconn = sqlite3.connect(_ro_uri(src), uri=True)
        try:
            sconn.backup(self.conn)
        finally:
            sconn.close()
        self._ensure_schema()  # 舊版備份可能缺少新資料表
        with self.tx() as c:
            c.execute("DELETE FROM locks")
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('last_backup',?)",
                      (datetime.now().strftime("%Y%m%d"),))
            self._audit(user, "restore", detail=f"from {src}; previous data saved to {safety}")
        return safety


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _ro_uri(path: str) -> str:
    return Path(os.path.abspath(path)).as_uri() + "?mode=ro"


def inspect_backup(path: str) -> Dict:
    """檢查檔案是否為本程式的有效資料庫，回傳病人數、切片數與最後修改時間。"""
    if not os.path.isfile(path):
        raise ValueError(f"找不到檔案：{path}")
    try:
        conn = sqlite3.connect(_ro_uri(path), uri=True)
    except sqlite3.Error as e:
        raise ValueError(f"無法開啟檔案：{e}")
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"patients", "biopsies"} <= tables:
            raise ValueError("這個檔案不是本程式的資料庫備份。")
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("備份檔已損壞，無法使用。")
        return {
            "patients": conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
            "biopsies": conn.execute("SELECT COUNT(*) FROM biopsies").fetchone()[0],
            "last_updated": conn.execute("SELECT MAX(updated_at) FROM biopsies").fetchone()[0] or "",
        }
    except sqlite3.DatabaseError as e:
        raise ValueError(f"這個檔案不是有效的資料庫：{e}")
    finally:
        conn.close()
