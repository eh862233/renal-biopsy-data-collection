"""讀取醫院系統產出的記事本（.txt），轉成可帶入表單的資料。

記事本依「1. Patient profile … 13. Pathology」的段落排列，內容多為文字敘述與 Markdown 表格，
格式可能因人而異，因此這裡採寬鬆的解析方式，並把無法確定的地方列成「需要確認」，
由使用者在表單中檢查後再儲存。檢驗數值一律記在切片日期。
"""
import re
from typing import Dict, List, Optional, Tuple

from . import schema
from .utils import looks_like_national_id, normalize_date, normalize_national_id

DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
MISSING = ("not provided", "not reported", "not specified", "not available", "not applicable",
           "unknown", "n/a", "na", "nil", "-", "--", "none provided")
NONE_WORDS = ("none", "no", "nil", "negative", "denied", "none reported", "no history")

SECTION_KEYS = [
    ("profile", ("patient profile", "基本資料")),
    ("cc", ("chief complaint", "主訴")),
    ("pi", ("present illness", "現病史")),
    ("med", ("medication", "用藥")),
    ("pe", ("physical exam", "理學檢查")),
    ("lab", ("lab data", "laboratory", "抽血")),
    ("urine", ("urine", "尿液")),
    ("auto", ("autoimmune",)),
    ("ig", ("immunoglobulin",)),
    ("endo", ("endocrine", "infection")),
    ("us", ("ultrasound", "sonography", "超音波")),
    ("biopsy", ("renal biopsy", "kidney biopsy", "切片")),
    ("path", ("pathology", "病理")),
]

# 檢驗名稱（去掉括號、只留英數字並轉小寫）→ (panel, 項目) 或 ("field", 欄位)
_LAB_NAMES = {
    "cbc": {"WBC": ["wbc"], "Hb": ["hb", "hgb", "hemoglobin", "haemoglobin"],
            "HCT": ["hct", "hematocrit"], "MCV": ["mcv"], "PLT": ["plt", "platelet", "platelets"],
            "INR": ["inr", "ptinr"], "PT": ["pt", "prothrombintime"], "APTT": ["aptt", "ptt"],
            "SEG": ["seg", "segment", "neutrophil", "neutrophils"],
            "LYM": ["lym", "lymphocyte", "lymphocytes"], "MONO": ["mono", "monocyte", "monocytes"],
            "EOS": ["eos", "eosinophil", "eosinophils"], "BASO": ["baso", "basophil", "basophils"],
            "Haptoglobin": ["haptoglobin"]},
    "chem": {"BUN": ["bun", "bloodun", "bloodureanitrogen", "urea"],
             "Cr": ["cr", "creatinine", "serumcreatinine", "creatinineserum"],
             "eGFR": ["egfr", "gfr"], "Na": ["na", "sodium"], "K": ["k", "potassium"],
             "Cl": ["cl", "chloride"], "Ca": ["ca", "calcium", "totalcalcium"],
             "Mg": ["mg", "magnesium"],
             "IP": ["ip", "phosphorus", "phosphate", "inorganicphosphorus", "inorganicphosphate"]},
    "liver": {"AST": ["ast", "got", "sgot"], "ALT": ["alt", "gpt", "sgpt"], "LDH": ["ldh"],
              "TP": ["tp", "totalprotein"], "Alb": ["alb", "albumin", "serumalbumin"],
              "Chol": ["chol", "cholesterol", "totalcholesterol", "tcho", "tchol"],
              "HDL": ["hdl", "hdlcholesterol", "hdlc"], "LDL": ["ldl", "ldlcholesterol", "ldlc"],
              "TG": ["tg", "triglyceride", "triglycerides"], "UA": ["ua", "uricacid"]},
    "ig": {"IgG": ["igg", "iggtotal"], "IgA": ["iga"], "IgM": ["igm"], "IgE": ["ige"], "IgD": ["igd"],
           "C3": ["c3", "c3complement", "complementc3"], "C4": ["c4", "c4complement", "complementc4"],
           "Kappa": ["kappa", "freekappa", "kappafreelightchain"],
           "Lambda": ["lambda", "lamda", "freelambda", "lambdafreelightchain"],
           "Kappa/Lambda": ["kappalambda", "kappalambdaratio", "kappalamdaratio", "flcratio",
                            "freelightchainratio"],
           "IgG4": ["igg4"]},
    "endo": {"FBS": ["fbs", "acsugar", "glucoseac", "fastingglucose", "fastingbloodsugar"],
             "HbA1c": ["hba1c", "a1c"], "fT4": ["ft4", "freet4"], "TSH": ["tsh"],
             "HIV": ["hiv", "antihiv", "hivagab", "hivagabcombo"], "HBsAg": ["hbsag"],
             "Anti-HBc": ["antihbc", "hbcab"], "Anti-HCV": ["antihcv", "hcvab", "hcv"],
             "VDRL": ["vdrl", "rpr", "rprvdrl"], "TPHA": ["tpha"], "ASLO": ["aslo", "aso"],
             "CRP": ["crp", "hscrp"]},
}
_FIELD_NAMES = {
    "ab_dsdna": ["antidsdna", "dsdna", "antidsdnaab"], "ab_ana": ["ana"],
    "ab_rf": ["rf", "rheumatoidfactor"], "ab_ro": ["antiro", "ssa", "antissa", "antirossa"],
    "ab_la": ["antila", "ssb", "antissb", "antilassb"], "ab_anca": ["anca"],
    "ab_canca": ["canca"], "ab_panca": ["panca"], "ab_mpo": ["mpo", "ancampo", "antimpo"],
    "ab_pr3": ["pr3", "ancapr3", "antipr3"], "ab_gbm": ["antigbm", "gbm", "antigbmab"],
    "ab_cryo": ["cryoglobulin"], "ab_asma": ["asma"], "ab_rnp": ["rnp", "antirnp"],
    "ab_sm": ["sm", "antism"], "ab_scl70": ["scl70", "antiscl70"],
    "ab_ribop": ["ribosomalp", "antiribosomalp"], "ab_jo1": ["jo1", "antijo1"],
    "ab_ccp": ["ccp", "anticcp"], "ab_pla2r": ["pla2r", "antipla2r", "antipla2rab"],
}
NAME_MAP: Dict[str, Tuple[str, str]] = {}
for _panel, _items in _LAB_NAMES.items():
    for _analyte, _aliases in _items.items():
        for _a in _aliases:
            NAME_MAP[_a] = (_panel, _analyte)
for _field, _aliases in _FIELD_NAMES.items():
    for _a in _aliases:
        NAME_MAP[_a] = ("field", _field)


def norm_name(name: str) -> str:
    s = name.replace("κ", "kappa").replace("λ", "lambda")
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"^\s*[-•*]\s*", "", s)
    s = re.sub(r"(?i)^\s*optional\s*:\s*", "", s)
    return re.sub(r"[^0-9a-z]", "", s.lower())


def is_missing(v: str) -> bool:
    s = (v or "").strip().lower().rstrip(".")
    return not s or any(s == m or s.startswith(m + " ") or s.startswith(m + "(") for m in MISSING)


def is_none(v: str) -> bool:
    s = (v or "").strip().lower().rstrip(".")
    return any(s == w or s.startswith(w + " ") or s.startswith(w + ",") or s.startswith(w + "(")
               for w in NONE_WORDS)


def first_date(text: str) -> Optional[str]:
    m = DATE_RE.search(text or "")
    return normalize_date(m.group(0)) if m else None


def strip_paren(v: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", v or "").strip()


def is_range(v: str) -> bool:
    return bool(re.match(r"^[<>]?\s*\d+(\.\d+)?\s*[-~–]\s*\d+(\.\d+)?", (v or "").strip()))


def lab_value(v: str) -> Optional[str]:
    """檢驗結果 → 儲存值：數字保留 < >，去掉單位；文字（Negative 等）保留。範圍值回傳 None。"""
    v = strip_paren(v)
    if is_missing(v) or is_range(v):
        return None
    m = re.match(r"^([<>]=?)?\s*(\d+(?:\.\d+)?)", v)
    if m:
        return (m.group(1) or "") + m.group(2)
    return v.split(",")[0].strip() or None


# ---------------------------------------------------------------- 文字結構
def read_text(path: str) -> str:
    raw = open(path, "rb").read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "cp950", "big5hkscs"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def split_sections(text: str) -> Dict[str, Tuple[str, List[str]]]:
    """回傳 {段落代號: (標題列, 內容行)}。"""
    out: Dict[str, Tuple[str, List[str]]] = {}
    cur = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = re.match(r"^\s*(\d{1,2})\s*[.)、]\s*(\S.*)$", line)
        if m:
            title = m.group(2).lower()
            key = next((k for k, words in SECTION_KEYS if any(w in title for w in words)), None)
            if key and key not in out:
                cur = key
                out[key] = (m.group(2).strip(), [])
                continue
        if cur:
            out[cur][1].append(line.rstrip())
    return out


def kv_lines(lines: List[str]) -> List[Tuple[str, str]]:
    out = []
    for line in lines:
        if line.strip().startswith("|"):
            continue
        m = re.match(r"^\s*[-•*]?\s*([^:：|]{1,60}?)\s*[:：]\s*(.*)$", line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def kv_get(pairs, *names) -> str:
    for k, v in pairs:
        kl = k.lower()
        if any(n in kl for n in names):
            return v
    return ""


def tables(lines: List[str]) -> List[List[List[str]]]:
    """擷取 Markdown 表格（略過分隔線）。每個表格為列的清單，第一列為標題。"""
    out, cur = [], []
    for line in lines + [""]:
        s = line.strip()
        if s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells):
                continue
            cur.append(cells)
        elif cur:
            out.append(cur)
            cur = []
    return out


def text_block(lines: List[str]) -> str:
    keep = [l.strip() for l in lines]
    while keep and not keep[0]:
        keep.pop(0)
    while keep and not keep[-1]:
        keep.pop()
    return "\n".join(keep)


def closest_row(rows: List[Tuple[str, List[str]]], biopsy_date: str):
    """rows = [(日期, 欄位)]：取切片日當天或之前最近的一列，沒有則取之後最早的一列。"""
    dated = sorted((d, r) for d, r in rows if d)
    if not dated:
        return rows[0] if rows else None
    if not biopsy_date:
        return dated[0]
    before = [x for x in dated if x[0] <= biopsy_date]
    return before[-1] if before else dated[0]


# ---------------------------------------------------------------- 主程式
class _Result:
    def __init__(self):
        self.patient: Dict[str, str] = {}
        self.data: Dict = {}
        self.labs: Dict[str, Dict[str, str]] = {}
        self.warnings: List[str] = []
        self.unmapped: List[str] = []
        self.ranges: Dict[Tuple[str, str], str] = {}  # 範圍值：最後仍沒有數值才提醒

    def set(self, key, value):
        if value not in (None, "", []) and key not in self.data:
            self.data[key] = value

    def lab(self, name: str, raw: str, where: str):
        key = norm_name(name)
        target = NAME_MAP.get(key)
        if target is None:
            m = re.match(r"^([a-z0-9]+?)(total|serum|level)$", key)
            target = NAME_MAP.get(m.group(1)) if m else None
        if target is None:
            if not is_missing(raw):
                shown = re.sub(r"(?i)^\s*(?:[-•*]\s*)?(?:optional\s*:\s*)?", "", name)
                self.unmapped.append(strip_paren(shown))
            return
        panel, item = target
        if panel == "field":
            v = strip_paren(raw)
            if not is_missing(v) and item not in self.data:
                self.data[item] = v
            return
        v = lab_value(raw)
        if v is None:
            if not is_missing(raw) and is_range(strip_paren(raw)):
                self.ranges.setdefault((panel, item), f"{where} {item}：記事本為範圍值「{raw}」")
            return
        self.labs.setdefault(panel, {}).setdefault(item, v)


def _yes_no(v: str, label: str, res: _Result) -> str:
    if is_missing(v):
        return ""
    s = v.strip().lower()
    if s.startswith("yes") or s.startswith("(+)") or s.startswith("positive"):
        return "Yes"
    if is_none(v) or s.startswith("(-)"):
        return "No"
    res.warnings.append(f"{label}：記事本為「{v}」，已設為 Yes，請確認")
    return "Yes"


def parse_notepad_text(text: str) -> Dict:
    secs = split_sections(text)
    if len(secs) < 3:
        raise ValueError("看不出記事本的段落（例如「1. Patient profile」「13. Pathology」），"
                         "請確認是醫院系統產出的檔案。")
    res = _Result()
    get = lambda k: secs.get(k, ("", []))

    # ---- 1. Patient profile ----
    _, lines = get("profile")
    pairs = kv_lines(lines)
    chart = kv_get(pairs, "chart")
    if not is_missing(chart):
        res.patient["chart_no"] = chart.split()[0]
    nid = kv_get(pairs, "national id", "身分證", "id no")
    if not is_missing(nid) and looks_like_national_id(nid.split()[0]):
        res.patient["national_id"] = normalize_national_id(nid.split()[0])
    name = kv_get(pairs, "name", "姓名")
    if not is_missing(name):
        res.patient["name"] = name
    birth = kv_get(pairs, "birth", "生日")
    if first_date(birth):
        res.patient["birth_date"] = first_date(birth)
    elif birth:
        age = re.search(r"age\s*(\d+)", birth, re.I) or re.search(r"(\d+)\s*(?:years|y/?o|歲)", birth)
        res.warnings.append("記事本未提供生日" + (f"（年齡 {age.group(1)} 歲）" if age else "")
                            + "，年齡無法自動計算，請補上生日")
    g = kv_get(pairs, "gender", "sex", "性別").lower()
    if "female" in g or "女" in g or g.strip() == "f":
        res.patient["gender"] = "Female"
    elif "male" in g or "男" in g or g.strip() == "m":
        res.patient["gender"] = "Male"
    for key, label in (("past_history", "past history"), ("operation_history", "operation")):
        v = kv_get(pairs, label)
        if not is_missing(v):
            res.patient[key] = "None" if is_none(v) and len(v) < 20 else v
    adm = first_date(kv_get(pairs, "admission"))
    if adm:
        res.set("admission_date", adm)

    # ---- 12. Renal biopsy（先取得切片日期） ----
    _, blines = get("biopsy")
    bpairs = kv_lines(blines)
    bdate = first_date(kv_get(bpairs, "date"))
    if not bdate:
        m = re.search(r"biops\w*[^.\n]{0,40}?(\d{4}[-/.]\d{1,2}[-/.]\d{1,2})", text, re.I)
        bdate = normalize_date(m.group(1)) if m else None
    if bdate:
        res.data["biopsy_date"] = bdate
    else:
        res.warnings.append("找不到切片日期，請在 Renal biopsy 頁填寫")
    bdate = bdate or ""

    # ---- 2, 3. Chief complaint / Present illness ----
    cc = text_block(get("cc")[1])
    if cc:
        low = cc.lower()
        items = []
        for opt, words in (("Renal function deteriorated", ("renal function", "kidney injury",
                                                             "creatinine", "renal failure", "aki")),
                           ("Pitting edema", ("edema", "oedema", "swelling")),
                           ("Foamy urine", ("foamy",)),
                           ("Hematuria", ("hematuria", "haematuria")),
                           ("Proteinuria", ("proteinuria", "nephrotic"))):
            if any(w in low for w in words):
                items.append(opt)
        res.set("cc_items", items)
        res.set("cc_other", cc)
    res.set("present_illness", text_block(get("pi")[1]))

    # ---- 4. Medication ----
    _, mlines = get("med")
    mpairs = kv_lines(mlines)
    for key, names, label in (("med_nsaid", ("nsaid",), "NSAID"),
                              ("med_chinese_herb", ("chinese herb", "herb"), "Chinese herb"),
                              ("med_contrast", ("contrast",), "Contrast medium"),
                              ("med_antibiotics", ("antibiotic",), "Antibiotics"),
                              ("med_diuretics", ("diuretic",), "Diuretic agents"),
                              ("med_vaccination", ("vaccin",), "Vaccination within 1 year")):
        v = kv_get(mpairs, *names)
        if v:
            res.set(key, _yes_no(v, label, res))
    med_text = [l for l in mlines if not re.match(r"(?i)^\s*use of (the )?following medications", l)]
    res.set("current_medication", text_block(med_text))

    # ---- 5. Physical examination ----
    pe_title, plines = get("pe")
    pe_date = first_date(pe_title)
    if pe_date and pe_date not in (bdate, res.data.get("admission_date")):
        res.warnings.append(f"理學檢查日期為 {pe_date}（不是入院／切片時），請確認是否適用")
    ppairs = kv_lines(plines)
    res.set("pe_consciousness", kv_get(ppairs, "conscious"))
    vit = " ".join(v for k, v in ppairs if any(w in k.lower() for w in ("vital", "bp", "blood pressure",
                                                                      "pulse", "temperature")))
    m = re.search(r"(\d{2,3})\s*/\s*(\d{2,3})\s*mm\s*hg", vit, re.I) or \
        re.search(r"bp[:\s]*(\d{2,3})\s*/\s*(\d{2,3})", vit, re.I)
    if m:
        res.set("pe_sbp", m.group(1))
        res.set("pe_dbp", m.group(2))
    for key, pat in (("pe_pr", r"(?:pr|hr|pulse)[:\s]*(\d{2,3})"),
                     ("pe_rr", r"rr[:\s]*(\d{1,2})"),
                     ("pe_bt", r"(?:bt|temp\w*)[:\s]*(\d{2}(?:\.\d)?)")):
        mm = re.search(pat, vit, re.I)
        if mm:
            res.set(key, mm.group(1))
    body = " ".join(v for k, v in ppairs if any(w in k.lower() for w in ("weight", "height", "bmi")))
    mw = re.search(r"(\d+(?:\.\d+)?)\s*kg", body, re.I)
    mh = re.search(r"(\d+(?:\.\d+)?)\s*cm", body, re.I)
    if mw:
        res.set("pe_bw", mw.group(1))
    if mh:
        res.set("pe_height", mh.group(1))
    for key, names in (("pe_heent", ("heent",)), ("pe_neck", ("neck",)), ("pe_chest", ("chest", "lung")),
                       ("pe_heart", ("heart",)), ("pe_abdomen", ("abdomen",)),
                       ("pe_extremity", ("extremit",))):
        v = kv_get(ppairs, *names)
        if v and not is_missing(v):
            res.set(key, v)

    # ---- 6, 8, 9, 10. 檢驗表格 ----
    for sec, label in (("lab", "Lab data"), ("auto", "Autoimmune"), ("ig", "Immunoglobulin"),
                       ("endo", "Endocrine")):
        _, lines = get(sec)
        for tb in tables(lines):
            head = [norm_name(h) for h in tb[0]]
            if head and head[0] == "date":
                rows = [(first_date(r[0]) or "", r) for r in tb[1:] if r]
                picked = closest_row(rows, bdate)
                if picked:
                    for name, cell in zip(tb[0][1:], picked[1][1:]):
                        res.lab(name, cell, label)
                continue
            ri = next((i for i, h in enumerate(head) if h in ("result", "results", "value")), 1)
            for r in tb[1:]:
                if len(r) <= ri or not r[0]:
                    continue
                if "," in r[ri] and not re.match(r"^[<>]?\s*\d", r[ri]):
                    pieces = [re.match(r"^\s*(.+?)\s+(negative|positive|reactive|non-reactive|"
                                       r"nonreactive|not detected|detected|[<>]?\s*\d.*)$", p, re.I)
                              for p in r[ri].split(",")]
                    if all(pieces):
                        for p in pieces:
                            res.lab(p.group(1), p.group(2), label)
                        continue
                res.lab(r[0], r[ri], label)
        for k, v in kv_lines(lines):
            res.lab(k, v, label)
    ig_text = [l for l in get("ig")[1] if l.strip() and not l.strip().startswith("|")]
    for l in ig_text:
        low = l.lower()
        if any(w in low for w in ("electrophoresis", "immunofixation", "ife", "pep")):
            res.set("electrophoresis", l.strip())

    # ---- 7. Urine ----
    _, ulines = get("urine")
    upairs = kv_lines(ulines)
    for tb in tables(ulines):
        head = [norm_name(h) for h in tb[0]]
        if not head or head[0] != "date":
            continue
        rows = [(first_date(r[0]) or "", r) for r in tb[1:] if r]
        picked = closest_row(rows, bdate)
        if not picked:
            continue
        cells = dict(zip(head, picked[1]))
        routine = []
        for h, cell in cells.items():
            if is_missing(cell):
                continue
            if "ratio" in h and "protein" in h or h == "upcr":
                res.set("upcr", lab_value(cell))
                if lab_value(cell) and float(re.sub(r"[<>=]", "", lab_value(cell))) < 100:
                    res.warnings.append(
                        f"Spot UPCR 記事本數值為 {cell}，系統單位為 mg/g（若原為 g/g 應 ×1000），請確認")
            elif ("albumin" in h and "ratio" in h) or h == "uacr":
                res.set("uacr", lab_value(cell))
            elif ("24" in h) and "protein" in h:
                res.set("urine_24hr_protein", lab_value(cell))
            elif ("24" in h) and "albumin" in h:
                res.set("urine_24hr_albumin", lab_value(cell))
            elif "rbc" in h or "wbc" in h or "protein" in h or "occult" in h or "glucose" in h:
                hdr = tb[0][head.index(h)]
                routine.append(f"{strip_paren(hdr)}: {cell}")
        if routine:
            res.set("urine_routine", f"({picked[0]}) " + "; ".join(routine))
        rbc = cells.get("urinerbc") or cells.get("rbc") or ""
        m = re.match(r"^\s*(\d+)", rbc)
        if m:
            res.set("ua_rbc", "Yes" if int(m.group(1)) >= 3 else "No")
    res.set("urine_routine", kv_get(upairs, "urine routine", "routine"))
    for key, names in (("upcr", ("upcr",)), ("uacr", ("uacr",)),
                       ("urine_24hr_protein", ("24hr urine protein", "24-hr urine protein"))):
        v = kv_get(upairs, *names)
        if v:
            res.set(key, lab_value(v))
    res.set("urine_longitudinal", text_block(ulines))

    # ---- 11. Renal ultrasound ----
    res.set("us_results", text_block(get("us")[1]))

    # ---- 12. Renal biopsy 細項 ----
    v = kv_get(bpairs, "ultrasound")
    if not is_missing(v):
        res.set("bx_us_findings", v)
    v = kv_get(bpairs, "site").lower()
    if "left" in v or "左" in v:
        res.set("bx_site", "Left kidney")
    elif "right" in v or "右" in v:
        res.set("bx_site", "Right kidney")
    v = kv_get(bpairs, "core")
    m = re.search(r"(\d+)\s*(?:cores?|pieces?|specimens?|條)", v, re.I)
    if m:
        res.set("bx_cores", m.group(1))
    elif v and not is_missing(v):
        res.warnings.append(f"Number of cores：記事本為「{v}」，無法判讀條數，請手動填寫")
    v = kv_get(bpairs, "glomerul")
    m = re.search(r"(\d+)\s*(?:glomerul|個)", v, re.I) or re.match(r"^\s*(\d+)", v)
    if m:
        res.set("bx_glomeruli", m.group(1))
    v = kv_get(bpairs, "cortex").lower()
    if v.startswith("yes") or v.startswith("有"):
        res.set("bx_cortex", "Yes")
    elif v.startswith("no") or v.startswith("無"):
        res.set("bx_cortex", "No")
    v = kv_get(bpairs, "adequa")
    if v:
        got = {}
        for clause in re.split(r"[;,]", v):
            which = [t for t in ("LM", "IF", "EM") if re.search(rf"\b{t}\b", clause, re.I)] \
                or ([] if re.search(r"\b(LM|IF|EM)\b", v, re.I) else ["LM", "IF", "EM"])
            if re.search(r"\binadequate\b", clause, re.I):
                got.update({t: "Inadequate" for t in which})
            elif re.search(r"\badequate\b", clause, re.I):
                got.update({t: "Adequate" for t in which})
        for t in ("LM", "IF", "EM"):
            if t in got:
                res.set(f"bx_adequacy_{t.lower()}", got[t])
        missing = [t for t in ("LM", "IF", "EM") if t not in got]
        if missing:
            res.warnings.append(f"Adequacy {'/'.join(missing)}：無法判讀（記事本：「{v}」），請手動選擇")
    v = kv_get(bpairs, "complication")
    if v and not is_missing(v):
        low = v.lower()
        if is_none(v) or low.startswith("no "):
            res.set("bx_complication", "None")
        elif "transfusion" in low:
            res.set("bx_complication", "Blood transfusion required")
        elif "hematoma" in low:
            res.set("bx_complication", "Perirenal hematoma")
        elif "hematuria" in low:
            res.set("bx_complication", "Gross hematuria")
        else:
            res.set("bx_complication", "Other")
            res.set("bx_complication_other", v)

    # ---- 13. Pathology ----
    blocks = {"path_lm": [], "path_if": [], "path_em": []}
    cur = None
    dx_text = ""
    for line in get("path")[1]:
        s = line.strip()
        m = re.match(r"(?i)^(light microscopy|lm|immunofluorescence|if|electron microscopy|em)"
                     r"\b[^:：]*[:：]?\s*(.*)$", s)
        if m and (s.endswith(":") or ":" in s[:40] or s.upper() in ("LM", "IF", "EM")):
            word = m.group(1).lower()
            cur = "path_lm" if word in ("light microscopy", "lm") else \
                "path_if" if word in ("immunofluorescence", "if") else "path_em"
            if m.group(2):
                blocks[cur].append(m.group(2))
            continue
        md = re.match(r"(?i)^(?:pathologic(?:al)?\s+)?diagnosis\s*[:：]\s*(.+)$", s)
        if md:
            dx_text = md.group(1)
            cur = None
            continue
        if cur:
            blocks[cur].append(s)
    for key, ls in blocks.items():
        res.set(key, text_block(ls))
    if dx_text:
        res.data["_diagnosis_text"] = dx_text

    for (panel, item), msg in res.ranges.items():
        if item not in res.labs.get(panel, {}):
            res.warnings.append(msg + "，未匯入，請手動填寫")
    if res.unmapped:
        res.warnings.append("以下檢驗沒有對應欄位，未匯入：" + "、".join(dict.fromkeys(res.unmapped)))

    labs = [{"panel": p, "lab_date": bdate, "values": v} for p, v in res.labs.items() if v]
    dx = res.data.pop("_diagnosis_text", "")
    return {"patient": res.patient, "data": res.data, "labs": labs, "warnings": res.warnings,
            "diagnosis_text": dx}


def parse_notepad(path: str) -> Dict:
    return parse_notepad_text(read_text(path))


def count_fields(parsed: Dict) -> int:
    return (len(parsed["patient"]) + len(parsed["data"])
            + sum(len(l["values"]) for l in parsed["labs"]))


def merge_into_record(rec: Dict, parsed: Dict, fill_only: bool) -> int:
    """把解析結果放進表單紀錄。fill_only=True 時只補空白（既有紀錄），否則覆蓋預設值（新紀錄）。

    回傳實際帶入的欄位數。
    """
    n = 0
    p = rec["patient"]
    for k, v in parsed["patient"].items():
        if v and not p.get(k):
            p[k] = v
            n += 1
    data = rec["biopsy"]["data"]
    for k, v in parsed["data"].items():
        if fill_only and data.get(k) not in (None, "", []):
            continue
        data[k] = v
        n += 1
    if parsed.get("diagnosis_text") and not rec["biopsy"].get("diagnosis_other") \
            and not rec["biopsy"].get("diagnoses"):
        rec["biopsy"]["diagnosis_other"] = parsed["diagnosis_text"]
        n += 1
    for lab in parsed["labs"]:
        row = next((l for l in rec["labs"]
                    if l["panel"] == lab["panel"] and l.get("lab_date") == lab["lab_date"]), None)
        if row is None:
            rec["labs"].append({"panel": lab["panel"], "lab_date": lab["lab_date"],
                                "values": dict(lab["values"])})
            n += len(lab["values"])
        else:
            for a, v in lab["values"].items():
                if not row["values"].get(a):
                    row["values"][a] = v
                    n += 1
    return n
