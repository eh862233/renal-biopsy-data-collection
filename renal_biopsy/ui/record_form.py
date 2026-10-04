"""病人切片資料輸入/修改畫面（依 schema 自動產生）。"""
import copy
from typing import Dict

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QScrollArea,
                               QSplitter, QStackedWidget, QVBoxLayout, QWidget)

from .. import schema
from ..db import patient_label
from ..utils import calc_age, calc_bmi, normalize_date, normalize_national_id
from . import theme
from .widgets import CheckGroup, ImageList, LabTable


class RecordForm(QWidget):
    save_requested = Signal()
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.record: Dict = {}
        self.widgets: Dict[str, QWidget] = {}
        self.lab_tables: Dict[str, LabTable] = {}
        self.read_only = False
        self.dirty = False
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 14)
        root.setSpacing(10)
        # ---- 標題列 ----
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("H1")
        top.addWidget(self.title)
        top.addStretch()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        top.addWidget(self.status)
        root.addLayout(top)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.banner.setObjectName("Banner")
        self.banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.banner_box = QScrollArea()
        self.banner_box.setWidgetResizable(True)
        self.banner_box.setFrameShape(QFrame.NoFrame)
        self.banner_box.setMaximumHeight(170)
        self.banner_box.setWidget(self.banner)
        self.banner_box.hide()
        root.addWidget(self.banner_box)

        # ---- 左側目錄 + 右側內容 ----
        split = QSplitter(Qt.Horizontal)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setMaximumWidth(250)
        self.nav.setMinimumWidth(210)
        self.pages = QStackedWidget()
        page_card = QFrame()
        page_card.setObjectName("Card")
        pc = QVBoxLayout(page_card)
        pc.setContentsMargins(18, 14, 8, 10)
        pc.addWidget(self.pages)
        split.addWidget(self.nav)
        split.addWidget(page_card)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)
        self.nav.setSpacing(1)
        for sec in schema.SECTIONS:
            self.nav.addItem(sec.title)
            self.nav.item(self.nav.count() - 1).setSizeHint(QSize(0, 34))
            self.pages.addWidget(self._build_section(sec))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        # ---- 下方按鈕 ----
        bottom = QHBoxLayout()
        self.btn_prev = QPushButton("◀ 上一頁")
        self.btn_next = QPushButton("下一頁 ▶")
        self.btn_prev.clicked.connect(lambda: self.nav.setCurrentRow(max(0, self.nav.currentRow() - 1)))
        self.btn_next.clicked.connect(
            lambda: self.nav.setCurrentRow(min(self.nav.count() - 1, self.nav.currentRow() + 1)))
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.btn_next)
        bottom.addStretch()
        self.btn_back = QPushButton("返回查詢")
        self.btn_save = QPushButton("儲存並上傳")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setMinimumWidth(140)
        self.btn_back.clicked.connect(self.back_requested)
        self.btn_save.clicked.connect(self.save_requested)
        bottom.addWidget(self.btn_back)
        bottom.addWidget(self.btn_save)
        root.addLayout(bottom)

    # ------------------------------------------------------------------ 建立畫面
    def _make_field(self, f: schema.Field) -> QWidget:
        if f.type == schema.MULTILINE:
            w = QPlainTextEdit()
            h = 200 if f.key.startswith("path_") else 60 if f.key.startswith("pe_") else 100
            w.setMinimumHeight(h)
            w.setMaximumHeight(h * 2)
            w.setTabChangesFocus(True)
            w.textChanged.connect(self._mark_dirty)
        elif f.type == schema.CHOICE:
            w = QComboBox()
            w.addItems(f.options)
            w.currentIndexChanged.connect(self._mark_dirty)
        elif f.type == schema.CHECKS:
            w = CheckGroup(f.options, columns=1 if max(map(len, f.options)) > 30 else 2)
            w.changed.connect(self._mark_dirty)
        elif f.type == schema.COMPUTED:
            w = QLineEdit()
            w.setReadOnly(True)
            w.setFrame(False)
            w.setPlaceholderText(f.hint)
        else:
            w = QLineEdit()
            if f.type == schema.DATE:
                w.setPlaceholderText("YYYY-MM-DD")
                w.setMaximumWidth(160)
                w.editingFinished.connect(lambda w=w: self._normalize_date_box(w))
            elif f.type == schema.NUMBER:
                w.setMaximumWidth(160)
            elif f.hint:
                w.setPlaceholderText(f.hint)
            w.textChanged.connect(self._mark_dirty)
        if f.hint:
            w.setToolTip(f.hint)
        self.widgets[f.key] = w
        return w

    def _row(self, form: QFormLayout, f: schema.Field):
        w = self._make_field(f)
        if f.unit and not isinstance(w, (QPlainTextEdit, CheckGroup)):
            box = QWidget()
            h = QHBoxLayout(box)
            h.setContentsMargins(0, 0, 0, 0)
            h.addWidget(w)
            h.addWidget(QLabel(f.unit))
            h.addStretch()
            form.addRow(f.label, box)
        else:
            form.addRow(f.label, w)

    def _build_section(self, sec: schema.Section) -> QWidget:
        inner = QWidget()
        lay = QVBoxLayout(inner)
        hb = QHBoxLayout()
        bar = QFrame()
        bar.setFixedSize(4, 24)
        bar.setStyleSheet(f"background:{theme.CYAN};border-radius:2px;")
        header = QLabel(sec.title)
        header.setObjectName("H2")
        hb.addWidget(bar)
        hb.addWidget(header)
        hb.addStretch()
        lay.addLayout(hb)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        if sec.key == "profile":
            for f in schema.PATIENT_FIELDS:
                self._row(form, f)
        for f in sec.fields:
            self._row(form, f)
        lay.addLayout(form)
        if sec.key == "profile":
            note = QLabel("※ 病歷號、身分證字號至少填一個。號碼、姓名、生日、性別、病史屬於病人層級資料，"
                          "同一位病人的所有切片紀錄共用。")
            note.setWordWrap(True)
            note.setObjectName("Muted")
            lay.addWidget(note)
        if sec.key == "medication":
            note = QLabel("No = (-)、Yes = (+)；留空表示未記錄。")
            note.setObjectName("Muted")
            lay.addWidget(note)
        for p in sec.lab_panels:
            title, analytes = schema.LAB_PANELS[p]
            t = LabTable(p, title, analytes)
            t.changed.connect(self._mark_dirty)
            self.lab_tables[p] = t
            lay.addWidget(t)
        if sec.images:
            gb = QGroupBox("超音波圖片")
            v = QVBoxLayout(gb)
            self.image_list = ImageList()
            self.image_list.changed.connect(self._mark_dirty)
            v.addWidget(self.image_list)
            lay.addWidget(gb)
        if sec.diagnosis:
            gb = QGroupBox("病理診斷（可複選，匯出時可依此篩選）")
            v = QVBoxLayout(gb)
            self.dx_group = CheckGroup(schema.DIAGNOSES, columns=2)
            self.dx_group.changed.connect(self._mark_dirty)
            v.addWidget(self.dx_group)
            h = QHBoxLayout()
            h.addWidget(QLabel("其他診斷："))
            self.dx_other = QLineEdit()
            self.dx_other.textChanged.connect(self._mark_dirty)
            h.addWidget(self.dx_other)
            v.addLayout(h)
            lay.addWidget(gb)
        lay.addStretch()
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(inner)
        return sa

    # ------------------------------------------------------------------ 資料讀寫
    def _normalize_date_box(self, w: QLineEdit):
        d = normalize_date(w.text())
        if d:
            w.setText(d)

    def _mark_dirty(self, *_):
        self._update_computed()
        if not self._loading:
            self.dirty = True

    def _get(self, key):
        w = self.widgets[key]
        if isinstance(w, QPlainTextEdit):
            return w.toPlainText().strip()
        if isinstance(w, QComboBox):
            return w.currentText()
        if isinstance(w, CheckGroup):
            return w.value()
        return w.text().strip()

    def _set(self, key, value):
        w = self.widgets[key]
        if isinstance(w, QPlainTextEdit):
            w.setPlainText(value or "")
        elif isinstance(w, QComboBox):
            i = w.findText(value or "")
            if i < 0 and value:
                w.addItem(value)
                i = w.findText(value)
            w.setCurrentIndex(max(i, 0))
        elif isinstance(w, CheckGroup):
            w.set_value(value or [])
        else:
            w.setText(value or "")

    def _update_computed(self):
        if "age" not in self.widgets:
            return
        ref = normalize_date(self._get("biopsy_date")) or normalize_date(self._get("admission_date"))
        self.widgets["age"].setText(calc_age(normalize_date(self._get("birth_date")) or "", ref or ""))
        self.widgets["pe_bmi"].setText(calc_bmi(self._get("pe_bw"), self._get("pe_height")))

    def load(self, record: Dict, read_only: bool = False, banner: str = "", keep_page=None):
        self._loading = True
        self.record = copy.deepcopy(record)
        p, b = self.record["patient"], self.record["biopsy"]
        for f in schema.PATIENT_FIELDS:
            self._set(f.key, p.get(f.key, ""))
        for f in schema.all_biopsy_fields():
            if f.type != schema.COMPUTED:
                self._set(f.key, b["data"].get(f.key, f.default if b.get("id") is None else ""))
        for key, t in self.lab_tables.items():
            t.set_rows([l for l in self.record["labs"] if l["panel"] == key])
        self.image_list.set_images(self.record["images"])
        self.dx_group.set_value(b.get("diagnoses", []))
        self.dx_other.setText(b.get("diagnosis_other", ""))
        self._update_computed()
        self.set_read_only(read_only)
        if banner:
            self.banner.setText(banner)
            self.banner_box.show()
        else:
            self.banner_box.hide()
        self.refresh_title()
        self.nav.setCurrentRow(keep_page if keep_page is not None else 0)
        self._loading = False
        self.dirty = False

    def refresh_title(self):
        p, b = self.record["patient"], self.record["biopsy"]
        who = patient_label(p) or "新病人"
        if b.get("id") is None:
            self.title.setText(f"新增切片紀錄 — {who}")
            self.status.setText("尚未儲存")
        else:
            self.title.setText(f"切片紀錄 — {who}"
                               f"（切片日 {b['data'].get('biopsy_date') or '未填'}）")
            if b.get("updated_at"):
                self.status.setText(f"最後修改：{b['updated_at']}  {b.get('updated_by', '')}")

    def set_read_only(self, ro: bool):
        self.read_only = ro
        for w in self.widgets.values():
            if isinstance(w, (QLineEdit, QPlainTextEdit)):
                if not (isinstance(w, QLineEdit) and w.isReadOnly() and not w.hasFrame()):
                    w.setReadOnly(ro)
            elif isinstance(w, QComboBox):
                w.setEnabled(not ro)
            elif isinstance(w, CheckGroup):
                w.set_read_only(ro)
        for t in self.lab_tables.values():
            t.set_read_only(ro)
        self.image_list.set_read_only(ro)
        self.dx_group.set_read_only(ro)
        self.dx_other.setReadOnly(ro)
        self.btn_save.setEnabled(not ro)

    def collect(self) -> Dict:
        """把畫面上的資料組成紀錄；有錯誤時丟出 ValueError（訊息會顯示給使用者）。"""
        rec = copy.deepcopy(self.record)
        p, b = rec["patient"], rec["biopsy"]
        errors = []

        def check(f: schema.Field, value):
            if f.type == schema.DATE:
                d = normalize_date(value)
                if d is None:
                    errors.append(f"{f.label}：日期格式錯誤「{value}」")
                    return value
                return d
            if f.type == schema.NUMBER and value:
                try:
                    float(value.replace(",", ""))
                except ValueError:
                    errors.append(f"{f.label}：請輸入數字（目前為「{value}」）")
            return value

        for f in schema.PATIENT_FIELDS:
            p[f.key] = check(f, self._get(f.key))
        p["national_id"] = normalize_national_id(p["national_id"])
        if not p["chart_no"] and not p["national_id"]:
            errors.insert(0, "病歷號與身分證字號至少要填一個（在「Patient profile」頁）。")
        data = {}
        for f in schema.all_biopsy_fields():
            if f.type == schema.COMPUTED:
                continue
            v = check(f, self._get(f.key))
            if v not in ("", []):
                data[f.key] = v
        b["data"] = data
        if not data.get("biopsy_date"):
            errors.insert(0, "Biopsy date（切片日期）為必填，請到「Renal biopsy」頁填寫。")
        b["diagnoses"] = self.dx_group.value()
        b["diagnosis_other"] = self.dx_other.text().strip()
        labs = []
        for t in self.lab_tables.values():
            try:
                labs += t.rows()
            except ValueError as e:
                errors.append(str(e))
        rec["labs"] = labs
        rec["images"] = self.image_list.value()
        if errors:
            raise ValueError("\n".join(errors))
        return rec
