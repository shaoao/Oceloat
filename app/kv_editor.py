"""键值对编辑器：Query 参数 / Headers / Form / 环境变量共用。

能力：
- 逐行启用开关、行内删除、右键菜单（上移 / 下移 / 复制 / 删除）
- 底部常驻空行，边填边加，任意数量的键值都能加
- 类型列（自动 / 文本 / 数字 / 布尔 / 空 / JSON）：为代码生成与校验提供真实类型
- 智能粘贴：`a=1&b=2`、`k: v` 多行、Tab 分隔、JSON 对象都能直接拆成行
- Header 键名自动补全、批量文本编辑模式
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .anim import running as _anim_running, stop as _anim_stop
from .theme import C, S, font, method_color, mono, theme
from .widgets import Label, Menu

COMMON_HEADERS = [
    "Accept", "Accept-Charset", "Accept-Encoding", "Accept-Language", "Authorization",
    "Cache-Control", "Connection", "Content-Disposition", "Content-Encoding",
    "Content-Length", "Content-Type", "Cookie", "Date", "Expect", "Forwarded",
    "From", "Host", "If-Match", "If-Modified-Since", "If-None-Match", "If-Range",
    "If-Unmodified-Since", "Origin", "Pragma", "Proxy-Authorization", "Range",
    "Referer", "TE", "Trailer", "Transfer-Encoding", "Upgrade", "User-Agent", "Via",
    "Warning", "X-API-Key", "X-Auth-Token", "X-CSRF-Token", "X-Forwarded-For",
    "X-Forwarded-Host", "X-Request-Id", "X-Requested-With",
]

COMMON_CONTENT_TYPES = [
    "application/json", "application/x-www-form-urlencoded", "multipart/form-data",
    "application/xml", "text/plain", "text/html", "application/octet-stream",
]

# 类型：key -> (显示名, 简称)。首字母大写，接口调试里更直观。
VALUE_TYPES = [
    ("auto", "Auto", "auto"),
    ("text", "String", "str"),
    ("number", "Number", "num"),
    ("bool", "Boolean", "bool"),
    ("null", "Null", "null"),
    ("json", "JSON", "JSON"),
    ("file", "File", "file"),
]
_TYPE_LABEL = {k: l for k, l, _ in VALUE_TYPES}

# 每种类型一个语义色：String 绿、Number 蓝、Boolean 紫、Null 灰、JSON 橙、File 青。
_TYPE_COLORS_DARK = {
    # Auto 用「暖沙」：和 Null 的中性灰、JSON 的橙都能一眼分开，也不跟其它类型撞色
    "auto": "#C9BFA9", "text": "#69C79A", "number": "#74A6DC",
    "bool": "#C296D8", "null": "#7C7C86", "json": "#D9A45F", "file": "#5FB3C9",
}
_TYPE_COLORS_LIGHT = {
    "auto": "#7B6E55", "text": "#14855C", "number": "#2E5F96",
    "bool": "#8750A4", "null": "#7A7A82", "json": "#9A6718", "file": "#1F6E82",
}


def type_color(key: str, t=None) -> str:
    t = t or theme()
    table = _TYPE_COLORS_LIGHT if not t.is_dark else _TYPE_COLORS_DARK
    return table.get(key, table["auto"])


# ---------------------------------------------------------------- 类型推断


def infer_value_type(value: str) -> str:
    """按字面量推断类型，仅用于展示提示与代码生成。"""
    v = (value or "").strip()
    if v == "":
        return "null"
    low = v.lower()
    if low in ("true", "false"):
        return "bool"
    if low in ("null", "nil", "none"):
        return "null"
    if re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", v):
        return "number"
    if v[:1] in "[{" and v[-1:] in "]}":
        try:
            json.loads(v)
            return "json"
        except Exception:
            return "text"
    return "text"


def typed_value(value: str, vtype: str = "auto") -> Any:
    """把字符串值按声明的类型转换为 Python 值（代码生成用）。"""
    v = value or ""
    t = vtype if vtype != "auto" else infer_value_type(v)
    try:
        if t == "number":
            f = float(v)
            return int(f) if f.is_integer() and "." not in v else f
        if t == "bool":
            return v.strip().lower() in ("1", "true", "yes", "on")
        if t == "null":
            return None
        if t == "json":
            return json.loads(v)
    except Exception:
        return v
    return v


# ---------------------------------------------------------------- 开关


class MiniCheck(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = True, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._v = 1.0 if checked else 0.0
        self.setFixedSize(15, 15)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_v)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, value: bool) -> None:  # noqa: N802
        if self._checked == value:
            return
        self._checked = value
        _anim_stop(self._anim)
        self._anim.setStartValue(self._v)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()

    def _on_v(self, v):
        self._v = float(v)
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, 14, 14)
        if self._v < 0.5:
            p.setPen(QPen(C(t.border_strong), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 4, 4)
        if self._v > 0.02:
            # 勾选态只画实心块，不描边：多出来那圈 1px 边会让小方框显得脏、不精致
            p.setOpacity(self._v)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.accent))
            p.drawRoundedRect(r, 4, 4)
            pen = QPen(C(t.accent_text), 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(QPointF(r.left() + 3.6, r.center().y() + 0.2),
                       QPointF(r.left() + 6.2, r.center().y() + 2.7))
            p.drawLine(QPointF(r.left() + 6.2, r.center().y() + 2.7),
                       QPointF(r.right() - 3.4, r.center().y() - 2.8))
            p.setOpacity(1.0)
        p.end()


# ---------------------------------------------------------------- 类型菜单


class TypeMenu(QWidget):
    """自绘类型下拉：类型语义色 + 当前项对号 + 悬停灰层。

    不用 QMenu 的原因：原生菜单的 checkmark 在部分 macOS 主题下会渲染成乱码小图标
    （用户截图里 JSON 前的牙签状图标），自绘后完全可控且与 MethodMenu 视觉一致。
    """

    ROW_H = 30
    PAD = 5
    picked = pyqtSignal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._current = current if current in _TYPE_LABEL else "auto"
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resize(150, self.PAD * 2 + len(VALUE_TYPES) * self.ROW_H + 4)

    def set_current(self, vtype: str) -> None:
        self._current = vtype if vtype in _TYPE_LABEL else "auto"
        self._hover = -1
        self.update()

    def popup(self, global_pos) -> None:
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = min(global_pos.x(), geo.right() - self.width() - 6)
        y = global_pos.y()
        if y + self.height() > geo.bottom():
            y = max(geo.top() + 6, geo.bottom() - self.height() - 6)
        self.move(int(x), int(y))
        self._hover = -1
        self.update()
        self.show()
        self.raise_()

    def _row_rect(self, i: int) -> QRectF:
        return QRectF(self.PAD, self.PAD + i * self.ROW_H,
                      self.width() - self.PAD * 2, self.ROW_H - 2)

    def _row_at(self, y: float) -> int:
        i = int((y - self.PAD) // self.ROW_H)
        return i if 0 <= i < len(VALUE_TYPES) else -1

    def mouseMoveEvent(self, e):
        # Popup 抓鼠标：菜单外的移动也会投递，先判断真实落点。
        if not self.rect().contains(e.position().toPoint()):
            if self._hover != -1:
                self._hover = -1
                self.update()
            return
        idx = self._row_at(e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def mouseReleaseEvent(self, e):
        idx = self._row_at(e.position().y())
        if 0 <= idx < len(VALUE_TYPES):
            self.picked.emit(VALUE_TYPES[idx][0])
            self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        for i, (key, label, _short) in enumerate(VALUE_TYPES):
            rr = self._row_rect(i)
            if i == self._hover:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(rr, 7, 7)
            p.setFont(font(12.5, QFont.Weight.Medium))
            p.setPen(C(type_color(key, t)))
            p.drawText(QRectF(rr.left() + 12, rr.top(), rr.width() - 34, rr.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
            if key == self._current:
                pm = icons.pixmap("check", t.text, 12, 1.9)
                p.drawPixmap(QPointF(rr.right() - 18, rr.center().y() - 6), pm)
        p.end()


# ---------------------------------------------------------------- 类型标签


class TypeChip(QWidget):
    changed = pyqtSignal(str)

    def __init__(self, vtype: str = "auto", parent=None):
        super().__init__(parent)
        self._type = vtype if vtype in _TYPE_LABEL else "auto"
        self._hover = False
        self._inferred = "text"
        self._menu: Optional[TypeMenu] = None
        self.setFixedSize(60, 20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("参数值类型（Auto = 按内容推断）")

    def value(self) -> str:
        return self._type

    def set_type(self, vtype: str) -> None:
        self._type = vtype if vtype in _TYPE_LABEL else "auto"
        self.update()

    def set_inferred(self, inferred: str) -> None:
        if inferred != self._inferred:
            self._inferred = inferred
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        # 菜单常驻复用，避免 Popup 关闭后再 close() 触发 RuntimeError。
        if self._menu is None:
            self._menu = TypeMenu(self._type, self)
            self._menu.picked.connect(self._pick)
        self._menu.set_current(self._type)
        self._menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

    def _pick(self, key: str) -> None:
        if key != self._type:
            self._type = key
            self.update()
            self.changed.emit(key)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        explicit = self._type != "auto"
        col = type_color(self._type, t)
        # 不再画描边：Auto 直接用它的暖沙色文字，显式类型只垫一层同色淡底，
        # 小胶囊少一圈边框会干净很多。
        if explicit:
            bg = C(col)
            bg.setAlpha(30 if self._hover else 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 5, 5)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.hover))
            p.drawRoundedRect(r, 5, 5)
        p.setFont(font(10.2, QFont.Weight.Medium))
        p.setPen(C(col))
        p.drawText(r, int(Qt.AlignmentFlag.AlignCenter), _TYPE_LABEL[self._type])
        p.end()


# ---------------------------------------------------------------- 文件取值单元


class FileCell(QWidget):
    """File 类型的值单元格：点一下选文件，显示文件名，右键清除。

    选中的路径写回行的 value，发送时按 multipart 文件 part 上传；
    查询参数里的 File 行会被跳过（URL 里带不了文件），并在 tooltip 里说明。
    """

    changed = pyqtSignal()

    def __init__(self, path: str = "", parent=None):
        super().__init__(parent)
        self._path = path or ""
        self._hover = False
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip("点击选择要上传的文件")

    def path(self) -> str:
        return self._path

    def set_path(self, path: str) -> None:
        if path != self._path:
            self._path = path
            self.update()
            self.changed.emit()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            from PyQt6.QtWidgets import QFileDialog

            start = self._path or os.path.expanduser("~")
            path, _ = QFileDialog.getOpenFileName(self, "选择要上传的文件", start, "所有文件 (*)")
            if path:
                self.set_path(path)
        elif e.button() == Qt.MouseButton.RightButton and self._path:
            self.set_path("")

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(C(t.border_strong if self._hover else t.border), 1))
        p.setBrush(C(t.hover) if self._hover else Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 5, 5)
        pm = icons.pixmap("file", type_color("file", t), 11, 1.7)
        icons.draw_centered(p, pm, 12, self.height() / 2)
        if self._path:
            name = os.path.basename(self._path) or self._path
            p.setFont(font(11.5))
            p.setPen(C(t.text))
            p.drawText(QRectF(24, 0, self.width() - 32, self.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), name)
        else:
            p.setFont(font(11.5))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(24, 0, self.width() - 32, self.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr("点击选择文件…"))
        p.end()


# ---------------------------------------------------------------- 行


class KVRow(QWidget):
    changed = pyqtSignal()
    removed = pyqtSignal(object)
    submitted = pyqtSignal()
    action = pyqtSignal(object, str)   # (row, "up"/"down"/"duplicate"/"delete")

    def __init__(self, key: str = "", value: str = "", enabled: bool = True,
                 key_ph: str = "Key", value_ph: str = "Value",
                 suggestions: Optional[Sequence[str]] = None,
                 with_types: bool = False, vtype: str = "auto", parent=None,
                 with_desc: bool = False, desc: str = "",
                 file_tooltip: str = "点击选择要上传的文件"):
        super().__init__(parent)
        self.setFixedHeight(31)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._hover = False
        self.with_types = with_types
        self.with_desc = with_desc
        self.check = MiniCheck(enabled)

        self.key_edit = QLineEdit(key)
        self.key_edit.setObjectName("Bare")
        i18n.placeholder(self.key_edit, key_ph)
        self.key_edit.setFont(mono(11.8))
        self.val_edit = QLineEdit(value)
        self.val_edit.setObjectName("Bare")
        i18n.placeholder(self.val_edit, value_ph)
        self.val_edit.setFont(mono(11.8))
        self.desc_edit = None
        if with_desc:
            self.desc_edit = QLineEdit(desc)
            self.desc_edit.setObjectName("Bare")
            i18n.placeholder(self.desc_edit, "描述（可选，不发送）")
            self.desc_edit.setFont(font(11))
        from PyQt6.QtGui import QPalette
        for e in (self.key_edit, self.val_edit, self.desc_edit):
            if e is None:
                continue
            e.setFixedHeight(24)
            pal = e.palette()
            pal.setColor(QPalette.ColorRole.PlaceholderText, C(theme().text_faint))
            e.setPalette(pal)
        if suggestions:
            comp = QCompleter(list(suggestions), self)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
            self.key_edit.setCompleter(comp)

        self.type_chip: Optional[TypeChip] = None
        self.file_cell: Optional[FileCell] = None
        if with_types:
            self.type_chip = TypeChip(vtype)
            self.type_chip.changed.connect(self._on_type)
            self.type_chip.set_inferred(infer_value_type(value))
            self.file_cell = FileCell(value)
            self.file_cell.setToolTip(file_tooltip)
            self.file_cell.changed.connect(self.changed.emit)

        self.del_btn = QWidget()
        self.del_btn.setFixedSize(20, 20)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.setToolTip("删除此行")
        self.del_btn._hover = 0.0
        self.del_btn.enterEvent = lambda e: self._btn_hover(1.0)
        self.del_btn.leaveEvent = lambda e: self._btn_hover(0.0)
        self.del_btn.paintEvent = self._paint_del
        self.del_btn.mouseReleaseEvent = lambda e: self.removed.emit(self)
        self._btn_v = 0.0

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(8)
        lay.addWidget(self.check, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.key_edit, 3)
        if self.type_chip is not None:
            lay.addWidget(self.type_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.val_edit, 4)
        if self.file_cell is not None:
            lay.addWidget(self.file_cell, 4)
            self.file_cell.hide()
        if self.desc_edit is not None:
            lay.addWidget(self.desc_edit, 3)
        lay.addWidget(self.del_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.key_edit.textChanged.connect(self.changed.emit)
        self.val_edit.textChanged.connect(self._on_value_changed)
        self.check.toggled.connect(lambda _: self.changed.emit())
        for e in (self.key_edit, self.val_edit, self.desc_edit):
            if e is not None:
                e.returnPressed.connect(self.submitted.emit)
        if self.desc_edit is not None:
            self.desc_edit.textChanged.connect(self.changed.emit)
        if self.type_chip is not None and self.type_chip.value() == "file":
            # 载入时就是 File 类型：直接进入文件选择态
            self.file_cell.set_path(value)
            self.val_edit.hide()
            self.file_cell.show()
        self._sync_enabled()

    # -------------------------------------------------- 类型 / 值
    def _on_value_changed(self) -> None:
        if self.type_chip is not None:
            self.type_chip.set_inferred(infer_value_type(self.val_edit.text()))
        self.changed.emit()

    def _on_type(self, vtype: str) -> None:
        """类型切成 File 时把值单元格换成文件选择器，其它类型换回文本框。"""
        if self.file_cell is None:
            self.changed.emit()
            return
        if vtype == "file":
            self.file_cell.set_path(self.val_edit.text().strip())
            self.val_edit.hide()
            self.file_cell.show()
        else:
            if self.file_cell.path() and not self.val_edit.text():
                self.val_edit.setText(self.file_cell.path())
            self.file_cell.hide()
            self.val_edit.show()
        self.changed.emit()

    def _btn_hover(self, v):
        self._btn_v = v
        self.del_btn.update()

    def _paint_del(self, _e):
        p = QPainter(self.del_btn)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = theme()
        if self._btn_v > 0:
            bg = C(t.hover)
            bg.setAlpha(int(bg.alpha() * self._btn_v))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(0, 0, 20, 20), 5, 5)
        col = C(t.text_dim if self._btn_v else t.text_faint)
        col.setAlpha(int(70 + 185 * self._btn_v))
        pm = icons.pixmap("close", col.name(QColor.NameFormat.HexArgb), 10, 1.8)
        p.drawPixmap(QPointF(5, 5), pm)
        p.end()

    def _sync_enabled(self):
        on = self.check.isChecked()
        for e in (self.key_edit, self.val_edit, self.desc_edit):
            if e is not None:
                e.setStyleSheet("" if on else f"color: {theme().text_faint};")
        if self.file_cell is not None:
            self.file_cell.setEnabled(on)
        self.update()

    def _menu(self, pos) -> None:
        t = theme()
        menu = Menu(self)
        a_up = menu.addAction(icons.icon("chevron_up", t.text, 13), "上移")
        a_down = menu.addAction(icons.icon("chevron_down", t.text, 13), "下移")
        a_dup = menu.addAction(icons.icon("copy", t.text, 13), "复制此行")
        menu.addSeparator()
        a_del = menu.addAction(icons.icon("trash", t.danger, 13), "删除")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is a_up:
            self.action.emit(self, "up")
        elif chosen is a_down:
            self.action.emit(self, "down")
        elif chosen is a_dup:
            self.action.emit(self, "duplicate")
        elif chosen is a_del:
            self.removed.emit(self)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._hover:
            c = C(t.hover)
            c.setAlpha(int(c.alpha() * 0.7))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(2, 1, self.width() - 4, self.height() - 2), 6, 6)
        p.setPen(QPen(C(t.border), 1))
        p.drawLine(10, self.height() - 1, self.width() - 10, self.height() - 1)
        p.end()

    def data(self) -> Dict:
        is_file = self.type_chip is not None and self.type_chip.value() == "file"
        d = {
            "key": self.key_edit.text(),
            "value": self.file_cell.path() if (is_file and self.file_cell is not None)
            else self.val_edit.text(),
            "enabled": self.check.isChecked(),
        }
        if self.type_chip is not None:
            d["type"] = self.type_chip.value()
        if self.desc_edit is not None:
            d["desc"] = self.desc_edit.text()
        return d

    def is_blank(self) -> bool:
        if self.type_chip is not None and self.type_chip.value() == "file":
            return not self.key_edit.text() and not (self.file_cell and self.file_cell.path())
        return not self.key_edit.text() and not self.val_edit.text()

    def focus_key(self) -> None:
        self.key_edit.setFocus()


# ---------------------------------------------------------------- 编辑器


class KVEditor(QWidget):
    changed = pyqtSignal()

    _COL_HINT = "直接输入即可添加 · 支持粘贴 a=1&b=2 批量导入"

    def __init__(self, key_ph: str = "Key", value_ph: str = "Value",
                 suggestions: Optional[Sequence[str]] = None,
                 empty_hint: str = "", with_types: bool = False,
                 with_desc: Optional[bool] = None,
                 file_tooltip: str = "点击选择要上传的文件", parent=None):
        super().__init__(parent)
        self._key_ph = key_ph
        self._value_ph = value_ph
        self._suggestions = suggestions
        self._with_types = with_types
        self._file_tooltip = file_tooltip
        # 类型列默认带描述列；表单场景可以只要类型列（File 上传不需要描述）
        self._with_desc = with_types if with_desc is None else with_desc
        self._rows: List[KVRow] = []
        self._bulk = False
        self._loading = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._rows_host = QWidget()
        self._rows_lay = QVBoxLayout(self._rows_host)
        self._rows_lay.setContentsMargins(0, 2, 0, 2)
        self._rows_lay.setSpacing(0)
        self._rows_lay.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._rows_host)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._bulk_edit = QPlainTextEdit()
        self._bulk_edit.setFont(mono(12))
        i18n.placeholder(self._bulk_edit, "每行一条：key: value\n以 # 开头的行为注释，可留空")
        self._bulk_edit.textChanged.connect(self._on_bulk_changed)
        self._bulk_edit.hide()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._scroll, 1)
        lay.addWidget(self._bulk_edit, 1)

        self.header = QWidget()
        self.header.setFixedHeight(21)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(10, 0, 8, 0)
        hl.setSpacing(8)
        # 勾选框占位：必须是真控件而不是 addSpacing，
        # 否则第一列会少掉 8px 的间距，整行表头相对数据行左移，看起来就是「没对齐」。
        check_gap = QWidget()
        check_gap.setFixedWidth(15)
        hl.addWidget(check_gap)
        k = Label("KEY", 9, theme().text_faint, weight=QFont.Weight.DemiBold, spacing=0.9)
        v = Label("VALUE", 9, theme().text_faint, weight=QFont.Weight.DemiBold, spacing=0.9)
        hl.addWidget(k, 3)
        if with_types:
            ty = Label("类型", 9, theme().text_faint, weight=QFont.Weight.DemiBold, spacing=0.9)
            ty.setFixedWidth(60)
            # 胶囊里的字是居中的，表头也跟着居中，两者才对得上
            ty.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(ty)
        hl.addWidget(v, 4)
        if self._with_desc:
            dsc = Label("描述（可选）", 9, theme().text_faint,
                        weight=QFont.Weight.DemiBold, spacing=0.9)
            hl.addWidget(dsc, 3)
        tail = QWidget()
        tail.setFixedWidth(20)
        hl.addWidget(tail)
        lay.insertWidget(0, self.header)

        self.empty_hint = empty_hint
        self.refresh_theme()

    # -------------------------------------------------- API
    def rows(self) -> List[Dict]:
        return [r.data() for r in self._rows if not r.is_blank()]

    def set_rows(self, rows: Sequence[Dict]) -> None:
        self._loading = True
        for r in list(self._rows):
            self._rows_lay.removeWidget(r)
            r.setParent(None)
            r.deleteLater()
        self._rows.clear()
        for row in rows or []:
            self._add_row(row.get("key", ""), row.get("value", ""), row.get("enabled", True),
                          row.get("type", "auto"), row.get("desc", ""))
        self._ensure_trailing()
        self._loading = False
        self.changed.emit()

    def add_row(self, key: str = "", value: str = "", enabled: bool = True) -> KVRow:
        self._ensure_trailing()
        row = self._rows[-1] if self._rows and self._rows[-1].is_blank() else self._add_row()
        row.key_edit.setText(key)
        row.val_edit.setText(value)
        row.check.setChecked(enabled)
        self._ensure_trailing()
        return row

    def enabled_count(self) -> int:
        return sum(1 for r in self._rows if r.check.isChecked() and r.key_edit.text())

    def clear(self) -> None:
        self.set_rows([])

    def set_bulk(self, on: bool) -> None:
        if on == self._bulk:
            return
        self._bulk = on
        if on:
            lines = []
            for r in self._rows:
                d = r.data()
                if not d["key"] and not d["value"]:
                    continue
                prefix = "" if d["enabled"] else "# "
                lines.append(f"{prefix}{d['key']}: {d['value']}")
            self._bulk_edit.setPlainText("\n".join(lines))
            self._scroll.hide()
            self.header.hide()
            self._bulk_edit.show()
            self._bulk_edit.setFocus()
        else:
            self._parse_bulk()
            self._bulk_edit.hide()
            self.header.show()
            self._scroll.show()

    def is_bulk(self) -> bool:
        return self._bulk

    def refresh_theme(self) -> None:
        t = theme()
        self._bulk_edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.code_bg}; border: 1px solid {S(t.border)};"
            f" border-radius: 8px; padding: 8px; color: {t.text}; }}")

    # -------------------------------------------------- 智能粘贴
    def paste_text(self, text: str) -> bool:
        """把粘贴的文本拆成多行：k=v&k2=v2 / 多行 k: v / Tab 分隔 / JSON 对象。

        只在内容确实像「多条键值」时接管，否则返回 False 交给输入框正常粘贴。
        """
        raw = (text or "").strip()
        if not raw:
            return False
        rows: List[Dict[str, Any]] = []

        # 1) JSON 对象
        if raw[:1] == "{" and raw[-1:] == "}":
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    for k, v in data.items():
                        val = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                        vtype = "json" if isinstance(v, (dict, list)) else "auto"
                        rows.append({"key": str(k), "value": str(val), "enabled": True, "type": vtype})
            except Exception:
                rows = []

        # 2) 单行 k=v&k2=v2 或 k=1; k2=2
        if not rows and "\n" not in raw and ("&" in raw or ";" in raw) and "=" in raw:
            from urllib.parse import unquote_plus

            for part in re.split(r"[&;]", raw):
                if not part.strip():
                    continue
                k, _, v = part.partition("=")
                rows.append({"key": unquote_plus(k.strip()), "value": unquote_plus(v.strip()),
                             "enabled": True, "type": "auto"})

        # 3) 多行：k: v / k=v / k<Tab>v / 纯行
        if not rows and "\n" in raw:
            for line in raw.splitlines():
                s = line.strip()
                if not s:
                    continue
                enabled = True
                if s.startswith("#"):
                    # 注释行：只有形如 "#Key: value" 才当成「被禁用的一行」，
                    # 纯说明文字（例如 "# 请求头"）直接丢掉，不生成空行
                    s = s[1:].strip()
                    if not any(sep in s for sep in ("\t", ":", "=")):
                        continue
                    enabled = False
                if "\t" in s:
                    k, v = s.split("\t", 1)
                elif ":" in s:
                    k, v = s.split(":", 1)
                elif "=" in s:
                    k, v = s.split("=", 1)
                else:
                    k, v = s, ""
                if not k.strip():
                    continue
                rows.append({"key": k.strip(), "value": v.strip(), "enabled": enabled, "type": "auto"})

        if not rows:
            return False
        existing = self.rows()
        self.set_rows(existing + rows)
        return True

    # -------------------------------------------------- 内部
    def _add_row(self, key="", value="", enabled=True, vtype="auto", desc="") -> KVRow:
        row = KVRow(key, value, enabled, self._key_ph, self._value_ph, self._suggestions,
                    with_types=self._with_types, vtype=vtype,
                    with_desc=self._with_desc, desc=desc,
                    file_tooltip=self._file_tooltip)
        row.changed.connect(self._on_row_changed)
        row.removed.connect(self._remove_row)
        row.submitted.connect(self._focus_next)
        row.action.connect(self._on_row_action)
        row.key_edit.installEventFilter(self)
        row.val_edit.installEventFilter(self)
        self._rows_lay.insertWidget(self._rows_lay.count() - 1, row)
        self._rows.append(row)
        return row

    def _remove_row(self, row: KVRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            self._rows_lay.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        if not self._rows:
            self._add_row()
        self._ensure_trailing()
        if not self._loading:
            self.changed.emit()

    def _ensure_trailing(self) -> None:
        if not self._rows or not self._rows[-1].is_blank():
            self._add_row()

    def _on_row_changed(self) -> None:
        if self._loading:
            return
        self._ensure_trailing()
        self.changed.emit()

    def _focus_next(self) -> None:
        self._ensure_trailing()
        focus = self.focusWidget()
        if focus is None:
            return
        if isinstance(focus, QLineEdit):
            for i, r in enumerate(self._rows):
                is_desc = r.desc_edit is not None and r.desc_edit is focus
                if r.key_edit is focus or r.val_edit is focus or is_desc:
                    if r.key_edit is focus:
                        r.val_edit.setFocus()
                    elif i + 1 < len(self._rows):
                        self._rows[i + 1].key_edit.setFocus()
                    return

    def _on_row_action(self, row: KVRow, action: str) -> None:
        if row not in self._rows:
            return
        i = self._rows.index(row)
        if action == "up" and i > 0:
            self._rows.insert(i - 1, self._rows.pop(i))
        elif action == "down" and i < len(self._rows) - 1:
            self._rows.insert(i + 1, self._rows.pop(i))
        elif action == "duplicate":
            d = row.data()
            new = self._add_row(d["key"], d["value"], d["enabled"], d.get("type", "auto"),
                                d.get("desc", ""))
            self._rows.remove(new)
            self._rows.insert(i + 1, new)
        else:
            return
        self._rebuild_layout()
        if not self._loading:
            self.changed.emit()

    def _rebuild_layout(self) -> None:
        for r in self._rows:
            self._rows_lay.removeWidget(r)
        for i, r in enumerate(self._rows):
            self._rows_lay.insertWidget(i, r)

    def _on_bulk_changed(self) -> None:
        if not self._loading:
            self.changed.emit()

    def _parse_bulk(self) -> None:
        rows = []
        for line in self._bulk_edit.toPlainText().splitlines():
            raw = line.strip()
            if not raw:
                continue
            enabled = True
            if raw.startswith("#"):
                enabled = False
                raw = raw[1:].strip()
                if ":" not in raw:
                    continue
            if ":" in raw:
                k, v = raw.split(":", 1)
            elif "=" in raw:
                k, v = raw.split("=", 1)
            else:
                k, v = raw, ""
            rows.append({"key": k.strip(), "value": v.strip(), "enabled": enabled})
        self.set_rows(rows)

    # -------------------------------------------------- 粘贴拦截
    def eventFilter(self, obj, event):
        # Ctrl/Cmd+V：内容像多条键值时整段解析，否则交给输入框正常粘贴
        if event.type() == event.Type.KeyPress and event.key() == Qt.Key.Key_V:
            mods = event.modifiers()
            if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
                clip = QGuiApplication.clipboard().text()
                if clip and self.paste_text(clip):
                    return True
        return super().eventFilter(obj, event)
