from typing import Dict, List

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..utils import normalize_date


class CheckGroup(QWidget):
    """多選勾選框。"""
    changed = Signal()

    def __init__(self, options: List[str], columns: int = 2, parent=None):
        super().__init__(parent)
        lay = QGridLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.boxes: Dict[str, QCheckBox] = {}
        for i, opt in enumerate(options):
            cb = QCheckBox(opt)
            cb.toggled.connect(self.changed)
            lay.addWidget(cb, i // columns, i % columns)
            self.boxes[opt] = cb

    def value(self) -> List[str]:
        return [o for o, cb in self.boxes.items() if cb.isChecked()]

    def set_value(self, values):
        values = set(values or [])
        for o, cb in self.boxes.items():
            cb.setChecked(o in values)

    def set_read_only(self, ro: bool):
        for cb in self.boxes.values():
            cb.setEnabled(not ro)


class LabTable(QWidget):
    """一個抽血 panel：第一欄日期，其餘為各檢驗項目，可新增多個日期。"""
    changed = Signal()

    def __init__(self, panel_key: str, title: str, analytes: List[str], parent=None):
        super().__init__(parent)
        self.panel_key = panel_key
        self.analytes = analytes
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        lbl = QLabel(f"<b>{title}</b>")
        head.addWidget(lbl)
        head.addStretch()
        self.btn_add = QPushButton("＋ 新增日期")
        self.btn_del = QPushButton("－ 刪除選取列")
        self.btn_add.clicked.connect(self.add_row)
        self.btn_del.clicked.connect(self.delete_rows)
        head.addWidget(self.btn_add)
        head.addWidget(self.btn_del)
        lay.addLayout(head)

        self.table = QTableWidget(0, len(analytes) + 1)
        self.table.setHorizontalHeaderLabels(["日期"] + analytes)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setColumnWidth(0, 100)
        for i in range(1, len(analytes) + 1):
            self.table.setColumnWidth(i, 70)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(lambda *_: self.changed.emit())
        lay.addWidget(self.table)
        self._fit_height()

    def _fit_height(self):
        rows = max(self.table.rowCount(), 1)
        h = self.table.horizontalHeader().height() + rows * 30 + 24
        self.table.setMinimumHeight(min(h, 260))
        self.table.setMaximumHeight(max(h, 90))

    def add_row(self, lab_date: str = "", values: Dict = None):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(lab_date or ""))
        for i, a in enumerate(self.analytes, 1):
            self.table.setItem(r, i, QTableWidgetItem(str((values or {}).get(a, ""))))
        self._fit_height()
        self.changed.emit()

    def delete_rows(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)
        self._fit_height()
        if rows:
            self.changed.emit()

    def set_rows(self, labs: List[Dict]):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        for lab in labs:
            self.add_row(lab.get("lab_date", ""), lab.get("values", {}))

    def rows(self) -> List[Dict]:
        """回傳資料列；日期格式錯誤時丟出 ValueError。"""
        out = []
        for r in range(self.table.rowCount()):
            def txt(c):
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            values = {a: txt(i) for i, a in enumerate(self.analytes, 1) if txt(i)}
            raw_date = txt(0)
            if not values and not raw_date:
                continue
            d = normalize_date(raw_date)
            if d is None:
                raise ValueError(f"抽血日期格式錯誤：「{raw_date}」（請用 YYYY-MM-DD）")
            out.append({"panel": self.panel_key, "lab_date": d, "values": values})
        return out

    def set_read_only(self, ro: bool):
        self.btn_add.setEnabled(not ro)
        self.btn_del.setEnabled(not ro)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers if ro else
                                   QTableWidget.AllEditTriggers)


def image_to_png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


class ImageList(QWidget):
    """超音波圖片：可加入圖片檔或從剪貼簿貼上，雙擊放大檢視。"""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.images: List[Dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        btns = QHBoxLayout()
        self.btn_file = QPushButton("加入圖片檔…")
        self.btn_paste = QPushButton("從剪貼簿貼上")
        self.btn_del = QPushButton("刪除選取圖片")
        self.btn_save = QPushButton("另存圖片…")
        for b in (self.btn_file, self.btn_paste, self.btn_del, self.btn_save):
            btns.addWidget(b)
        btns.addStretch()
        lay.addLayout(btns)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QPixmap(180, 140).size())
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMinimumHeight(200)
        lay.addWidget(self.list)
        self.btn_file.clicked.connect(self.add_files)
        self.btn_paste.clicked.connect(self.paste)
        self.btn_del.clicked.connect(self.delete_selected)
        self.btn_save.clicked.connect(self.save_selected)
        self.list.itemDoubleClicked.connect(self.view)

    def set_images(self, images: List[Dict]):
        self.images = [dict(i) for i in images]
        self._refresh()

    def value(self) -> List[Dict]:
        return self.images

    def _refresh(self):
        self.list.clear()
        for idx, img in enumerate(self.images):
            pm = QPixmap()
            pm.loadFromData(img["data"])
            it = QListWidgetItem(QIcon(pm), img.get("filename") or f"image {idx + 1}")
            it.setData(Qt.UserRole, idx)
            self.list.addItem(it)

    def _add(self, data: bytes, name: str):
        self.images.append({"id": None, "filename": name, "data": data})
        self._refresh()
        self.changed.emit()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇圖片", "",
                                                "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        import os
        for p in paths:
            img = QImage(p)
            if img.isNull():
                QMessageBox.warning(self, "無法讀取", f"無法讀取圖片：{p}")
                continue
            self._add(image_to_png_bytes(img), os.path.basename(p))

    def paste(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            QMessageBox.information(self, "剪貼簿", "剪貼簿中沒有圖片。")
            return
        self._add(image_to_png_bytes(img), f"pasted_{len(self.images) + 1}.png")

    def delete_selected(self):
        idxs = sorted((it.data(Qt.UserRole) for it in self.list.selectedItems()), reverse=True)
        for i in idxs:
            del self.images[i]
        if idxs:
            self._refresh()
            self.changed.emit()

    def save_selected(self):
        items = self.list.selectedItems()
        if not items:
            return
        img = self.images[items[0].data(Qt.UserRole)]
        path, _ = QFileDialog.getSaveFileName(self, "另存圖片", img.get("filename") or "image.png",
                                              "PNG (*.png)")
        if path:
            with open(path, "wb") as f:
                f.write(img["data"])

    def view(self, item):
        img = self.images[item.data(Qt.UserRole)]
        dlg = QDialog(self)
        dlg.setWindowTitle(img.get("filename") or "image")
        lay = QVBoxLayout(dlg)
        sa = QScrollArea()
        lbl = QLabel()
        pm = QPixmap()
        pm.loadFromData(img["data"])
        lbl.setPixmap(pm)
        sa.setWidget(lbl)
        lay.addWidget(sa)
        dlg.resize(min(pm.width() + 40, 1200), min(pm.height() + 40, 900))
        dlg.exec()

    def set_read_only(self, ro: bool):
        for b in (self.btn_file, self.btn_paste, self.btn_del):
            b.setEnabled(not ro)
