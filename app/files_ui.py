"""集合文件界面：`.oce` 的保存 / 打开对话框，以及「集合文件」管理窗口。

设计取向和回收站一致：纯黑卡片、明暗层次、只在悬停时露出操作按钮，
没有渐变和彩色描边。列表里一眼能看出三件事——哪个集合、存在哪、
文件跟内存里的内容是否一致。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QPainter
from PyQt6.QtWidgets import (QFileDialog, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from . import i18n, oce
from .dialogs import GlassDialog
from .store import Store
from .theme import C, font, mono, px, theme
from .widgets import Button, HBox, Label, icon_button

ROW_H = 62


# ---------------------------------------------------------------- 文件选择

def _start_dir(store: Optional[Store] = None) -> str:
    """默认落点：上次用过的目录 → 文稿目录。"""
    remembered = ""
    if store is not None:
        remembered = str(store.settings.get("oce_last_dir") or "")
    if remembered and Path(remembered).is_dir():
        return remembered
    docs = Path.home() / "Documents"
    return str(docs if docs.is_dir() else Path.home())


def _remember(store: Optional[Store], path: Path) -> None:
    if store is None:
        return
    store.settings["oce_last_dir"] = str(Path(path).expanduser().parent)
    store.save()


def choose_save_path(parent, name: str, store: Optional[Store] = None) -> Optional[Path]:
    """选一个 .oce 落点；用户没写后缀就自动补上。"""
    default = str(oce.suggest_path(name, Path(_start_dir(store))))
    path, _flt = QFileDialog.getSaveFileName(
        parent, i18n.tr("保存为集合文件"), default, oce.SUFFIX_FILTER)
    if not path:
        return None
    target = Path(path)
    if target.suffix.lower() != oce.EXT:
        target = target.with_name(target.name + oce.EXT)
    _remember(store, target)
    return target


def choose_open_path(parent, store: Optional[Store] = None) -> Optional[Path]:
    path, _flt = QFileDialog.getOpenFileName(
        parent, i18n.tr("打开集合文件"), _start_dir(store),
        f"{i18n.tr('集合文件')} (*{oce.EXT} *.json);;{i18n.tr('所有文件')} (*)")
    if not path:
        return None
    _remember(store, Path(path))
    return Path(path)


# ---------------------------------------------------------------- 单行

class FileRow(QWidget):
    """一行：名字 + 路径 + 同步状态，悬停露出「显示 / 写回 / 取消关联」。"""

    action = pyqtSignal(str, str)          # (action, collection_id)

    def __init__(self, store: Store, collection_id: str, parent=None):
        super().__init__(parent)
        self.store = store
        self.cid = collection_id
        self._hover = False
        self.setFixedHeight(px(ROW_H))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # 状态只在建行时算一次（要 dump 整棵树比指纹，重绘时不算）
        self._status = store.file_status(collection_id)

        self.btns: Dict[str, Any] = {}
        for key, icon_name, tip in (("reveal", "external", "在 Finder 中显示"),
                                    ("write", "sync", "立即写回文件"),
                                    ("unlink", "close", "取消关联")):
            btn = icon_button(icon_name, i18n.tr(tip), 24, 12, parent=self)
            btn.setVisible(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self.action.emit(k, self.cid))
            self.btns[key] = btn

    # -------------------------------------------------- 数据
    @property
    def node(self) -> Dict[str, Any]:
        return self.store.find(self.cid) or {}

    def status(self) -> str:
        return self._status

    def path(self) -> Optional[Path]:
        return self.store.link_path(self.cid)

    # -------------------------------------------------- 交互
    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        for btn in self.btns.values():
            btn.setVisible(True)
        self._place_buttons()
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        for btn in self.btns.values():
            btn.setVisible(False)
        self.update()
        super().leaveEvent(e)

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.action.emit("reveal", self.cid)
        super().mouseDoubleClickEvent(e)

    def resizeEvent(self, e):  # noqa: N802
        self._place_buttons()
        super().resizeEvent(e)

    def _button_span(self) -> float:
        """悬停时右侧按钮占掉多宽（按真实按钮位置算，别拍脑袋估）。"""
        if not self._hover:
            return 0.0
        lefts = [b.x() for b in self.btns.values()]
        if not lefts:
            return 0.0
        return max(0.0, self.width() - min(lefts)) + px(6)

    def _place_buttons(self) -> None:
        x = self.width() - px(10)
        for key in ("unlink", "write", "reveal"):     # 从右往左摆
            btn = self.btns[key]
            x -= btn.width()
            btn.move(int(x), (self.height() - btn.height()) // 2)
            x -= px(2)

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        rect = QRectF(self.rect()).adjusted(0, 1, 0, -1)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(rect, 8, 8)

        status = self.status()
        x = px(6)
        # 两行文字整体垂直居中（名字 19 + 路径 17 ≈ 36）
        top = rect.top() + max(px(7), (rect.height() - px(36)) / 2 - px(1))

        # 状态先算：名字要让位给右边那行字，否则长名字会直接压过去
        meta = self.store.file_map().get(self.cid) or {}
        if status == "synced":
            at = float(meta.get("at") or 0)
            dot_col = t.success
            label = (i18n.trf("已同步 · {when}", when=oce.ago(at)) if at
                     else i18n.tr("已同步"))
        elif status == "pending":
            dot_col, label = t.accent, i18n.tr("有改动未写回")
        elif status == "missing":
            dot_col, label = t.danger, i18n.tr("文件不在了")
        else:
            dot_col, label = t.text_faint, i18n.tr("未关联")
        fm = QFontMetricsF(font(10.8))
        w = fm.horizontalAdvance(label)
        right = rect.right() - px(8) - self._button_span()

        # 名字
        p.setFont(font(12.8, QFont.Weight.DemiBold))
        name = str(self.node.get("name") or "—")
        avail = max(px(40), right - w - px(16) - x)
        name = QFontMetricsF(p.font()).elidedText(name, Qt.TextElideMode.ElideRight, avail)
        p.setPen(C(t.text))
        p.drawText(QRectF(x, top, avail, px(19)),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)

        # 状态：一个 6px 的点 + 一句话
        p.setFont(font(10.8))
        p.setPen(C(t.text_faint) if status == "synced" else C(dot_col))
        p.drawText(QRectF(right - w, top, w, px(19)),
                   int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), label)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(dot_col))
        p.drawEllipse(QPointF(right - w - px(8), top + px(9.5)), 2.6, 2.6)

        # 路径
        path = self.path()
        p.setFont(mono(10.2))
        p.setPen(C(t.text_faint))
        shown = str(path) if path else i18n.tr("还没有关联文件")
        fm2 = QFontMetricsF(p.font())
        shown = fm2.elidedText(shown, Qt.TextElideMode.ElideMiddle, rect.width() - px(26))
        p.drawText(QRectF(x, top + px(20), rect.width() - px(20), px(17)),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), shown)


# ---------------------------------------------------------------- 窗口

class FilesDialog(GlassDialog):
    """集合文件管理：看状态、重新读取、取消关联、批量写回。"""

    changed = pyqtSignal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent, 760, 540, i18n.tr("集合文件"))
        self.store = store
        self.setMinimumSize(620, 420)
        self._rows: List[FileRow] = []
        self._build()
        self.refresh()

    # -------------------------------------------------- 构建
    def _build(self) -> None:
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        intro = Label(
            i18n.tr("集合可以存成一个 .oce 文件：能读、能改、能进 Git。"
                    "在这里改过的内容会自动写回文件，文件被外部改过时会问你用哪一版。"),
            11.4, theme().text_faint)
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                                  "QScrollArea > QWidget > QWidget { background: transparent; }")
        self.host = QWidget()
        self.host.setStyleSheet("background: transparent;")
        self.rows_lay = QVBoxLayout(self.host)
        self.rows_lay.setContentsMargins(0, 4, 0, 0)
        self.rows_lay.setSpacing(0)
        self.rows_lay.addStretch(1)
        self.scroll.setWidget(self.host)
        lay.addWidget(self.scroll, 1)

        self.empty = Label(
            i18n.tr("还没有关联文件的集合。右键任意集合选「保存为 .oce 文件」，"
                    "或者直接把 .oce 拖进来。"), 11.8, theme().text_faint)
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.hide()
        lay.addWidget(self.empty, 1)

        # 出错时在底部给一句话（不弹模态，免得挡住刚点的按钮）
        self.note = Label("", 11.2, theme().danger)
        self.note.hide()
        lay.addWidget(self.note)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self.note.hide)

        open_btn = Button(i18n.tr("打开 .oce 文件…"), "folder", kind="ghost",
                          height=30, padding=12, font_size=12)
        open_btn.clicked.connect(self._open)
        self.write_all = Button(i18n.tr("全部写回"), "sync", kind="subtle",
                                height=30, padding=12, font_size=12)
        self.write_all.clicked.connect(self._write_all)
        done = Button(i18n.tr("完成"), None, kind="primary", height=30,
                      padding=18, font_size=12)
        done.clicked.connect(self.accept)
        lay.addWidget(HBox(open_btn, self.write_all, 1, done, spacing=8))

    # -------------------------------------------------- 数据
    def refresh(self) -> None:
        for row in self._rows:
            self.rows_lay.removeWidget(row)
            row.deleteLater()
        self._rows = []
        table = self.store.file_map()
        ids = [cid for cid in table if self.store.find(cid) is not None]
        # 最近写过的排前面：通常就是刚在改的那个集合
        ids.sort(key=lambda c: float((table.get(c) or {}).get("at") or 0), reverse=True)
        for cid in ids:
            row = FileRow(self.store, cid, self.host)
            row.action.connect(self._on_action)
            self.rows_lay.insertWidget(self.rows_lay.count() - 1, row)
            self._rows.append(row)
        has = bool(self._rows)
        self.scroll.setVisible(has)
        self.empty.setVisible(not has)
        self.write_all.setEnabled(has)

    # -------------------------------------------------- 动作
    def _on_action(self, key: str, cid: str) -> None:
        if key == "reveal":
            reveal_in_finder(self.store.link_path(cid))
        elif key == "write":
            ok, err = self.store.write_back(cid)
            self.changed.emit()
            self.refresh()
            if not ok:
                self._flash(err)
        elif key == "unlink":
            self.store.unlink_collection(cid)
            self.changed.emit()
            self.refresh()

    def _flash(self, text: str) -> None:
        self.note.setText(text)
        self.note.show()
        self._note_timer.start(4200)

    def _write_all(self) -> None:
        for cid in list(self.store.file_map()):
            self.store.write_back(cid)
        self.changed.emit()
        self.refresh()

    def _open(self) -> None:
        path = choose_open_path(self, self.store)
        if path is None:
            return
        node, err = self.store.adopt_file(path)
        if node is None:
            self._flash(err)
            return
        self.changed.emit()
        self.refresh()


def reveal_in_finder(path: Optional[Path]) -> None:
    """在 Finder 里选中这个文件；没有这个文件就打开它所在的目录。"""
    import subprocess
    import sys

    if path is None:
        return
    target = Path(path)
    try:
        if sys.platform == "darwin":
            if target.exists():
                subprocess.Popen(["open", "-R", str(target)])
            elif target.parent.is_dir():
                subprocess.Popen(["open", str(target.parent)])
        elif sys.platform.startswith("win"):
            if target.exists():
                subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target.parent if target.exists() else target)])
    except Exception:                        # noqa: BLE001 — 打不开目录不算错误
        pass
