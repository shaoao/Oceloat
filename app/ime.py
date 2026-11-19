"""输入法候选期间的占位文字修复（全局安装，一次解决，不再逐处打补丁）。

问题：中文输入法在 preedit（候选框还在选字）阶段，QLineEdit / QPlainTextEdit
的文档仍是空的，所以 Qt 会继续画 placeholder。候选字就叠在提示文字上，
看起来像「背景的字没去掉」。

做法：应用级事件过滤器。preedit 出现时临时清空 placeholder，候选提交 /
消失 / 失焦 / 任何按键后恢复。对后续新加的输入框也自动生效。
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit

_INPUTS = (QLineEdit, QPlainTextEdit, QTextEdit)
_PROP = "ime_hidden_placeholder"
_INSTALLED: Optional["PlaceholderFilter"] = None


class PlaceholderFilter(QObject):
    def eventFilter(self, obj, event):  # noqa: N802
        if isinstance(obj, _INPUTS):
            t = event.type()
            if t == QEvent.Type.InputMethod:
                preedit = ""
                try:
                    preedit = event.preeditString() or ""
                except Exception:  # noqa: BLE001
                    pass
                if preedit:
                    hidden = obj.property(_PROP)
                    if not hidden:
                        ph = obj.placeholderText()
                        if ph:
                            obj.setProperty(_PROP, ph)
                            obj.setPlaceholderText("")
                else:
                    self._restore(obj)
            elif t in (QEvent.Type.FocusOut, QEvent.Type.KeyPress,
                       QEvent.Type.MouseButtonPress):
                self._restore(obj)
        return False

    @staticmethod
    def _restore(widget) -> None:
        ph = widget.property(_PROP)
        if ph and widget.placeholderText() != ph:
            widget.setPlaceholderText(ph)
        widget.setProperty(_PROP, None)


def install(app) -> None:
    """全局装一次；重复调用不会叠加过滤器。"""
    global _INSTALLED
    if _INSTALLED is None:
        _INSTALLED = PlaceholderFilter()
    app.installEventFilter(_INSTALLED)
