import html

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import theme


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    hh.setHighlightSections(False)
    return t


class SearchPage(QWidget):
    search_requested = Signal(str)
    patient_selected = Signal(int)
    open_requested = Signal(int)
    new_biopsy_requested = Signal()
    delete_requested = Signal(int)

    def __init__(self, is_admin: bool, parent=None):
        super().__init__(parent)
        self.term = ""
        self.patient = None
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(14)

        title = QLabel("病人查詢")
        title.setObjectName("H1")
        root.addWidget(title)
        sub = QLabel("輸入病歷號、身分證字號或姓名（姓名可只輸入部分）")
        sub.setObjectName("Muted")
        root.addWidget(sub)

        h = QHBoxLayout()
        h.setSpacing(10)
        self.edit = QLineEdit()
        self.edit.setObjectName("SearchBox")
        self.edit.setPlaceholderText("病歷號 / 身分證字號 / 姓名")
        self.edit.setClearButtonEnabled(True)
        btn = QPushButton("查詢")
        btn.setObjectName("Primary")
        btn.setMinimumSize(110, 46)
        btn.setStyleSheet("border-radius:22px;font-size:16px;")
        btn.setCursor(Qt.PointingHandCursor)
        h.addWidget(self.edit, 1)
        h.addWidget(btn)
        root.addLayout(h)
        btn.clicked.connect(self._search)
        self.edit.returnPressed.connect(self._search)

        # ---- 多位符合的病人（姓名查詢） ----
        self.match_box = QFrame()
        self.match_box.setObjectName("Card")
        mb = QVBoxLayout(self.match_box)
        mb.setContentsMargins(16, 12, 16, 12)
        self.match_title = QLabel()
        self.match_title.setObjectName("H2")
        mb.addWidget(self.match_title)
        self.matches = _table(["姓名", "病歷號", "身分證字號", "性別", "生日"])
        self.matches.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.matches.setMaximumHeight(220)
        self.matches.itemSelectionChanged.connect(self._pick_patient)
        mb.addWidget(self.matches)
        root.addWidget(self.match_box)

        # ---- 病人資料與切片紀錄 ----
        card = QFrame()
        card.setObjectName("Card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 14, 18, 14)
        cv.setSpacing(10)
        top = QHBoxLayout()
        self.info_name = QLabel()
        self.info_name.setObjectName("H2")
        top.addWidget(self.info_name)
        self.info_chips = QHBoxLayout()
        self.info_chips.setSpacing(6)
        top.addLayout(self.info_chips)
        top.addStretch()
        cv.addLayout(top)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        cv.addWidget(self.info)

        self.table = _table(["切片日期", "病理診斷", "最後修改時間", "修改者"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._open)
        cv.addWidget(self.table, 1)

        bh = QHBoxLayout()
        self.btn_open = QPushButton("開啟／修改選取的紀錄")
        self.btn_open.setObjectName("Primary")
        self.btn_new = QPushButton("＋ 新增一次切片紀錄")
        self.btn_del = QPushButton("刪除選取的紀錄")
        self.btn_del.setObjectName("Danger")
        self.btn_del.setVisible(is_admin)
        for b in (self.btn_open, self.btn_new, self.btn_del):
            b.setCursor(Qt.PointingHandCursor)
        self.btn_open.clicked.connect(self._open)
        self.btn_new.clicked.connect(self.new_biopsy_requested)
        self.btn_del.clicked.connect(self._delete)
        bh.addWidget(self.btn_open)
        bh.addWidget(self.btn_new)
        bh.addStretch()
        bh.addWidget(self.btn_del)
        cv.addLayout(bh)
        root.addWidget(card, 1)
        self.show_result(None, None, [])

    # ------------------------------------------------------------------
    def _search(self):
        term = self.edit.text().strip()
        if term:
            self.search_requested.emit(term)

    def _selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.table.item(rows[0].row(), 0).data(Qt.UserRole)

    def _open(self, *_):
        bid = self._selected_id()
        if bid is not None:
            self.open_requested.emit(bid)

    def _delete(self):
        bid = self._selected_id()
        if bid is not None:
            self.delete_requested.emit(bid)

    def _pick_patient(self):
        rows = self.matches.selectionModel().selectedRows()
        if rows:
            self.patient_selected.emit(self.matches.item(rows[0].row(), 0).data(Qt.UserRole))

    def show_matches(self, term, patients):
        """姓名查詢有多位符合時，列出讓使用者選擇。"""
        self.matches.blockSignals(True)
        self.matches.setRowCount(0)
        for p in patients:
            r = self.matches.rowCount()
            self.matches.insertRow(r)
            vals = [p.get("name"), p.get("chart_no"), p.get("national_id"), p.get("gender"),
                    p.get("birth_date")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v or "—")
                if c == 0:
                    it.setData(Qt.UserRole, p["id"])
                self.matches.setItem(r, c, it)
        self.matches.clearSelection()
        self.matches.blockSignals(False)
        self.match_title.setText(f"「{term}」共有 {len(patients)} 位病人符合，請選擇：")
        self.match_box.show()
        self.show_result(term, None, [], keep_matches=True)
        self.info_name.setText("請選擇病人")
        self.info.setText(f"<span style='color:{theme.MUTED}'>點選上方清單中的一位病人。</span>")

    def _clear_chips(self):
        while self.info_chips.count():
            w = self.info_chips.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _chip(self, text, gold=False):
        lbl = QLabel(text)
        lbl.setObjectName("ChipGold" if gold else "Chip")
        self.info_chips.addWidget(lbl)

    def show_result(self, term, patient, biopsies, keep_matches=False):
        self.term = term or ""
        self.patient = patient
        if not keep_matches:
            self.match_box.hide()
        self.table.setRowCount(0)
        self._clear_chips()
        has = bool(patient)
        for w in (self.table, self.btn_open, self.btn_new, self.btn_del):
            w.setEnabled(has)
        if term is None:
            self.info_name.setText("尚未查詢")
            self.info.setText(f"<span style='color:{theme.MUTED}'>在上方輸入號碼或姓名開始查詢。</span>")
            return
        if not has:
            self.info_name.setText("查無資料")
            self.info.setText(f"<span style='color:{theme.MUTED}'>「{html.escape(term)}」"
                              "沒有符合的病人。</span>")
            return
        e = lambda k: html.escape(patient.get(k) or "—")
        self.info_name.setText(patient.get("name") or "（未填姓名）")
        if patient.get("chart_no"):
            self._chip(f"病歷號 {patient['chart_no']}")
        if patient.get("national_id"):
            self._chip(f"ID {patient['national_id']}")
        self._chip(f"{len(biopsies)} 次切片", gold=True)
        self.info.setText(f"<span style='color:{theme.MUTED}'>性別</span> {e('gender')}　　"
                          f"<span style='color:{theme.MUTED}'>生日</span> {e('birth_date')}　　"
                          f"<span style='color:{theme.MUTED}'>雙擊紀錄即可開啟</span>")
        for b in biopsies:
            r = self.table.rowCount()
            self.table.insertRow(r)
            it = QTableWidgetItem(b["biopsy_date"] or "（未填）")
            it.setData(Qt.UserRole, b["id"])
            self.table.setItem(r, 0, it)
            dx = list(b["diagnoses"]) + ([b["diagnosis_other"]] if b.get("diagnosis_other") else [])
            self.table.setItem(r, 1, QTableWidgetItem("; ".join(dx)))
            self.table.setItem(r, 2, QTableWidgetItem(b.get("updated_at") or ""))
            self.table.setItem(r, 3, QTableWidgetItem(b.get("updated_by") or ""))
        if biopsies:
            self.table.selectRow(self.table.rowCount() - 1)
