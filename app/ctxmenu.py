"""统一的输入框右键菜单。

macOS 上 QLineEdit / QPlainTextEdit 会调用系统原生的文本菜单（英文、无图标、样式不搭），
这里拦截 ContextMenu 事件，换成自己的一套：中文、带图标、跟主题一致。
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTextBrowser,
    QTextEdit,
    QWidget,
)

TEXT_WIDGETS = (QLineEdit, QPlainTextEdit, QTextEdit, QTextBrowser)

from . import icons
from .theme import theme
from .widgets import Menu


def _has_selection(widget: QWidget) -> bool:
    if isinstance(widget, QLineEdit):
        return widget.hasSelectedText()
    if isinstance(widget, QLabel):
        return bool(widget.selectedText())
    if isinstance(widget, (QPlainTextEdit, QTextEdit)):
        return widget.textCursor().hasSelection()
    return False


def _label_menu(label: QLabel) -> "Menu":
    """可选中文字的 QLabel（响应头、文档正文…）也换成自己的菜单。

    macOS 上这类控件弹的是系统 NSMenu（英文 Copy / Select All 且半透明），
    所以截图里那块「透明菜单」就是它，不是我们自己的菜单。
    """
    t = theme()
    menu = Menu(label)
    sel = label.selectedText()

    def add(icon: str, text: str, slot, enabled: bool = True):
        act = menu.addAction(icons.icon(icon, t.text, 16, 1.55), text)
        act.setEnabled(enabled)
        act.triggered.connect(slot)

    add("copy", "复制所选" if sel else "复制全部",
        lambda: QApplication.clipboard().setText(sel or label.text()), True)
    if sel:
        add("copy", "复制全部", lambda: QApplication.clipboard().setText(label.text()))
    return menu


def _text_target(obj) -> Optional[QWidget]:
    """拿到真正要处理菜单的文本控件。

    滚动区域（QPlainTextEdit / QTextEdit）的右键事件落在 viewport 上，
    只按 isinstance 判断会漏掉它们，原生菜单就又冒出来了。
    """
    if isinstance(obj, TEXT_WIDGETS):
        return obj
    if isinstance(obj, QWidget):
        parent = obj.parent()
        if isinstance(parent, TEXT_WIDGETS):
            return parent
        if isinstance(obj, QLabel) and (obj.textInteractionFlags()
                                        & Qt.TextInteractionFlag.TextSelectableByMouse):
            return obj
    return None


def _menu_for(widget: QWidget) -> "Menu":
    t = theme()
    menu = Menu(widget)
    if isinstance(widget, QLabel):
        return _label_menu(widget)
    ro = isinstance(widget, TEXT_WIDGETS) and widget.isReadOnly()

    def add(icon: str, label: str, slot, enabled: bool = True, danger: bool = False):
        act = menu.addAction(icons.icon(icon, t.danger if danger else t.text, 16, 1.55), label)
        act.setEnabled(enabled)
        if slot is not None:
            act.triggered.connect(slot)
        return act

    if not ro:
        add("undo", "撤销", widget.undo, widget.isUndoAvailable()
            if isinstance(widget, QLineEdit) else widget.document().isUndoAvailable())
        add("redo", "重做", widget.redo, widget.isRedoAvailable()
            if isinstance(widget, QLineEdit) else widget.document().isRedoAvailable())
        menu.addSeparator()
    add("cut", "剪切", widget.cut, (not ro) and _has_selection(widget))
    add("copy", "复制", widget.copy, _has_selection(widget))
    add("paste", "粘贴", widget.paste, (not ro) and bool(QGuiApplication.clipboard().text()))
    if not ro:
        menu.addSeparator()
        add("close", "删除所选", lambda: _delete_selection(widget), _has_selection(widget))
    menu.addSeparator()
    add("grid", "全选", widget.selectAll, True)
    return menu


def _delete_selection(widget: QWidget) -> None:
    if isinstance(widget, QLineEdit):
        widget.del_()
        return
    cur = widget.textCursor()
    if cur.hasSelection():
        cur.removeSelectedText()


def _event_pos(ev) -> QPoint:
    """取事件发生处的屏幕坐标。

    QContextMenuEvent 在 Qt6 里只有 `globalPos()`，没有 `globalPosition`（那是 QMouseEvent 的），
    以前这里 `hasattr` 判断失败后回落到 `QApplication.cursor()` —— QApplication 根本没有
    cursor()，于是右键一点就 AttributeError 崩溃。兜底要用 QCursor.pos()。
    """
    for name in ("globalPos", "globalPosition"):
        fn = getattr(ev, name, None)
        if not callable(fn):
            continue
        try:
            value = fn()
        except Exception:      # noqa: BLE001 — 某些平台事件对象不全，别为定位蹦迪
            continue
        if value is None:
            continue
        return value.toPoint() if hasattr(value, "toPoint") else QPoint(value)
    return QCursor.pos()


class ContextMenuController(QObject):
    """拦下文本控件的原生右键菜单。"""

    _inst: Optional["ContextMenuController"] = None

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.app = app
        app.installEventFilter(self)

    @classmethod
    def install(cls, app: Optional[QApplication] = None) -> "ContextMenuController":
        if cls._inst is None:
            cls._inst = cls(app or QApplication.instance())
        return cls._inst

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.ContextMenu:
            target = _text_target(obj)
            if target is None or not target.isEnabled():
                return False
            menu = _menu_for(target)
            pos = _event_pos(ev)
            menu.exec(pos)
            menu.deleteLater()
            return True
        return False


def install(app: Optional[QApplication] = None) -> ContextMenuController:
    return ContextMenuController.install(app)
