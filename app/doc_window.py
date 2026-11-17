"""接口文档窗口：把一次请求 + 响应渲染成一份可以交付的文档。

排版参考 ApiFox 的接口文档页，但更克制：
- 顶部一条「请求名片」：方法、名称、地址，右侧是状态 / 耗时 / 体积三枚指标；
- 左侧章节大纲跟着滚动高亮，点一下跳到对应段落；
- 中间是原生控件渲染的 Markdown 正文（参数表、代码块、引用各自成型）；
- 底部是十种语言的代码示例，带语法高亮，随时复制。

内容全部由 `share.to_markdown` 生成，窗口只负责排版，不重复拼装文案。
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetricsF, QGuiApplication, QPainter
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from .codegen import LANGUAGES
from .dialogs import GlassDialog
from .markdown_view import CodeBlock, MarkdownView
from .share import redact_text, to_markdown
from .theme import C, font, method_color, theme
from .widgets import Button, Divider, ElideLabel, HBox, Label, Pill, SegmentedTabs, Switch

_STATUS_TOKEN = {2: "success", 3: "info", 4: "warning", 5: "danger"}


class OutlineItem(QWidget):
    """大纲的一行：左侧一条细指示条 + 标题，悬停变亮，滚动时高亮当前章节。"""

    clicked = pyqtSignal(int)

    def __init__(self, index: int, level: int, text: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.level = level
        self.text = text
        self._hover = False
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(25)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_active(self, on: bool) -> None:
        if on != self._active:
            self._active = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._active or self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.selected if self._active else t.hover))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 1, -2, -1), 5, 5)
            p.setBrush(C(t.accent_dim if self._active else t.text_faint))
            p.drawRoundedRect(QRectF(2, self.height() / 2 - 5, 2, 10), 1, 1)
        f = font(11.6 if self.level <= 2 else 11.0,
                 QFont.Weight.Medium if self.level <= 2 else QFont.Weight.Normal)
        p.setFont(f)
        fm = QFontMetricsF(f)
        if self._active:
            ink = t.text
        elif self.level <= 2:
            ink = t.text_dim
        else:
            ink = t.text_faint
        p.setPen(C(ink))
        left = 13 + (self.level - 1) * 9
        p.drawText(QPointF(left, self.height() / 2 + (fm.ascent() - fm.descent()) / 2),
                   fm.elidedText(self.text, Qt.TextElideMode.ElideRight,
                                 self.width() - left - 8))
        p.end()


class DocDialog(GlassDialog):
    """接口文档查看器：渲染 / 大纲 / 代码示例 / 复制 / 保存。"""

    def __init__(self, store, request: Dict[str, Any], response: Optional[Any] = None,
                 parent=None):
        super().__init__(parent, 1080, 764, "接口文档")
        self.store = store
        self.request = request or {}
        self.response = response
        self._redact = True
        self._markdown = ""
        self._lang = "curl"
        self._code_blocks: List[QWidget] = []
        self._outline_items: List[OutlineItem] = []
        self._code_cache: Dict[str, str] = {}
        self._active_outline = -1

        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_hero())
        body.addWidget(Divider())

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        split.addWidget(self._build_outline())
        split.addWidget(self._build_content())
        split.setSizes([206, 860])
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        body.addWidget(split, 1)

        body.addWidget(Divider())
        body.addWidget(self._build_code_panel())

        self._render()

    # -------------------------------------------------- 顶部名片
    def _build_hero(self) -> QWidget:
        t = theme()
        bar = QWidget()
        bar.setFixedHeight(88)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(22, 10, 16, 10)
        lay.setSpacing(14)

        method = (self.request.get("method") or "GET").upper()
        self.method_pill = Pill(method, method_color(method, t), font_size=11.0,
                                pad=11, height=26, radius=7)
        lay.addWidget(self.method_pill, 0, Qt.AlignmentFlag.AlignVCenter)

        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        self.name_label = Label(self.request.get("name") or "未命名请求", 15.5,
                                t.text, weight=QFont.Weight.DemiBold, spacing=-0.1)
        self.url_label = ElideLabel("", 10.8, t.text_faint, mono_font=True)
        self.url_label.setMinimumWidth(160)
        box.addWidget(self.name_label)
        box.addWidget(self.url_label)
        lay.addLayout(box, 1)

        # 三枚指标：状态 / 耗时 / 体积，只用语义色，不做彩色块
        self.metrics = QWidget()
        ml = QHBoxLayout(self.metrics)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(16)
        lay.addWidget(self.metrics, 0, Qt.AlignmentFlag.AlignVCenter)

        lay.addWidget(VLine())
        self.redact_switch = Switch(True)
        self.redact_switch.toggled.connect(self._on_redact)
        lay.addWidget(HBox(Label("打码", 11.2, t.text_dim), self.redact_switch, spacing=7),
                      0, Qt.AlignmentFlag.AlignVCenter)

        self.copy_btn = Button("复制", "copy", kind="subtle", height=30, padding=10,
                               font_size=12, icon_size=13)
        self.copy_btn.clicked.connect(self._copy)
        self.save_btn = Button("保存 .md", "download", kind="primary", height=30, padding=12,
                               font_size=12, icon_size=13)
        self.save_btn.clicked.connect(self._save)
        self.status = Label("", 10.4, t.text_faint)
        lay.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.copy_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self._toolbar_status = self.status
        return bar

    def _build_metrics(self) -> None:
        t = theme()
        lay = self.metrics.layout()
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        resp = self.response
        if resp is None:
            lay.addWidget(Label("草稿 · 尚未发送", 10.8, t.text_faint, mono_font=True))
            return
        status = int(getattr(resp, "status", 0) or 0)
        token = _STATUS_TOKEN.get(status // 100, "text_faint")
        for caption, value in (
            ("状态", f"{status} {getattr(resp, 'reason', '') or ''}".strip()),
            ("耗时", f"{int(getattr(resp, 'elapsed', 0) or 0)} ms"),
            ("体积", _human_size(int(getattr(resp, "size", 0) or 0))),
        ):
            cell = QWidget()
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            v.addWidget(Label(caption, 9.2, t.text_faint, weight=QFont.Weight.DemiBold,
                              spacing=0.6))
            color = getattr(t, token) if caption == "状态" else t.text_dim
            v.addWidget(Label(value, 11.6, color, mono_font=True,
                              weight=QFont.Weight.Medium))
            lay.addWidget(cell)

    # -------------------------------------------------- 大纲
    def _build_outline(self) -> QWidget:
        t = theme()
        host = QWidget()
        host.setMinimumWidth(168)
        host.setMaximumWidth(260)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 16, 8, 12)
        lay.setSpacing(1)
        lay.addWidget(Label("目录", 9.4, t.text_faint,
                            weight=QFont.Weight.DemiBold, spacing=0.9))
        lay.addSpacing(7)
        self._outline_box = QVBoxLayout()
        self._outline_box.setContentsMargins(0, 0, 0, 0)
        self._outline_box.setSpacing(1)
        lay.addLayout(self._outline_box)
        lay.addStretch(1)
        lay.addWidget(Divider())
        lay.addSpacing(6)
        self._outline_status = Label("", 10.4, t.text_faint, mono_font=True)
        self._outline_status.setWordWrap(True)
        lay.addWidget(self._outline_status)
        return host

    def _rebuild_outline(self, headings: List[tuple]) -> None:
        while self._outline_box.count():
            item = self._outline_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._outline_items.clear()
        for i, (level, text) in enumerate(headings):
            item = OutlineItem(i, level, text)
            item.clicked.connect(self.view.scroll_to_heading)
            self._outline_items.append(item)
            self._outline_box.addWidget(item)
        if not headings:
            self._outline_box.addWidget(Label("（无章节）", 10.6, theme().text_faint))
        self._active_outline = -1
        # 布局还没跑完时所有子控件的 y 都是 0，直接同步会误点亮最后一节
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, self._sync_outline)

    def _sync_outline(self) -> None:
        """按当前滚动位置点亮最近的一节，滚到哪读到哪，不用回头看目录。"""
        if not self._outline_items:
            return
        bar = self.view.verticalScrollBar()
        if bar is None:
            return
        pos = bar.value() + 12
        index = 0
        for i, (_lvl, _text, widget) in enumerate(self.view._headings):
            if widget.y() <= pos:
                index = i
            else:
                break
        if index != self._active_outline:
            for i, item in enumerate(self._outline_items):
                item.set_active(i == index)
            self._active_outline = index

    # -------------------------------------------------- 正文
    def _build_content(self) -> QWidget:
        self.view = MarkdownView()
        self.view.headingsChanged.connect(self._rebuild_outline)
        self.view.setStyleSheet(f"background: {theme().panel};")
        bar = self.view.verticalScrollBar()
        if bar is not None:
            bar.valueChanged.connect(lambda _v: self._sync_outline())
        return self.view

    # -------------------------------------------------- 代码示例
    def _build_code_panel(self) -> QWidget:
        t = theme()
        host = QWidget()
        # 高度跟着代码块走：短示例不留一大片空白，长示例到上限就内部滚动
        host.setMinimumHeight(168)
        host.setMaximumHeight(300)
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        lay = QVBoxLayout(host)
        lay.setContentsMargins(22, 10, 22, 12)
        lay.setSpacing(9)

        items = [(key, name) for key, name, _fn, _l in LANGUAGES]
        self.lang_tabs = SegmentedTabs(items, style="underline", current=self._lang,
                                       height=26, pad_h=6, font_size=11.0)
        self.lang_tabs.changed.connect(self._on_lang)
        lay.addWidget(HBox(Label("代码示例", 11.4, t.text_dim,
                                 weight=QFont.Weight.DemiBold),
                           1, self.lang_tabs, spacing=8))

        self._code_host = QWidget()
        self._code_lay = QVBoxLayout(self._code_host)
        self._code_lay.setContentsMargins(0, 0, 0, 0)
        self._code_lay.setSpacing(0)
        lay.addWidget(self._code_host, 1)
        return host

    def _code_for(self, entry) -> str:
        """生成代码并按语言 + 打码状态缓存：来回切语言不再重复拼字符串。

        打码开关打开时，代码示例里的 token / Cookie 一起打码 —— 否则文档正文打好了码，
        底下的 cURL 却把密钥原样带着，截图发出去一样漏。
        """
        key = f"{entry[0]}|{'r' if self._redact else 'p'}"
        if key in self._code_cache:
            return self._code_cache[key]
        try:
            code = entry[2](self.request, self.store.env_vars() if self.store else {},
                            self.store.settings if self.store else None)
        except Exception as exc:      # noqa: BLE001 — 生成失败不能把整个文档窗口带崩
            code = "// " + i18n.trf("生成失败：{err}", err=exc)
        if self._redact:
            code = redact_text(code)
        self._code_cache[key] = code
        return code

    def _show_code(self) -> None:
        while self._code_lay.count():
            item = self._code_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        entry = next((x for x in LANGUAGES if x[0] == self._lang), LANGUAGES[0])
        # 代码块自己贴顶，剩余高度留给下面的空白：之前没有 stretch，Qt 会把
        # 固定高的代码视图在剩余空间里居中，看起来就像「代码悬在半空」
        block = CodeBlock(self._code_for(entry), entry[3], max_height=182)
        block.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._code_lay.addWidget(block)
        self._code_lay.addStretch(1)

    # -------------------------------------------------- 渲染 / 交互
    def _render(self) -> None:
        env = self.store.env_vars() if self.store else {}
        self._markdown = to_markdown(self.request, self.response, env, redact=self._redact)
        # 窗口顶部已经有「方法 + 名称 + 地址」名片，正文里再排一遍就是重复。
        # 复制 / 保存出来的 Markdown 仍然是完整的（含标题），只是窗口里省掉。
        self.view.set_markdown(_strip_head(self._markdown))
        self._show_code()
        self._build_metrics()
        self.url_label.setText(self.request.get("url") or "")
        if self.response is not None:
            # 目录底部这行原来只有「200 OK」，看着像飘出来的一段文字；加个前缀说明它是什么
            self._outline_status.setText(
                i18n.trf("状态 {code} {reason}", code=self.response.status,
                              reason=self.response.reason).strip())
        else:
            self._outline_status.setText(i18n.tr("草稿"))

    def _on_redact(self, on: bool) -> None:
        if on == self._redact:
            return
        self._redact = on
        self._render()

    def _on_lang(self, key: str) -> None:
        self._lang = key
        self._show_code()

    def _flash(self, text: str) -> None:
        self._toolbar_status.setText(text)
        t = theme()
        self._toolbar_status.setStyleSheet(
            f"color: {t.text_faint}; background: transparent;")

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._markdown)
        self._flash("已复制")

    def _save(self) -> None:
        slug = re.sub(r"[^\w一-龥-]+", "-", (self.request.get("name") or "api-doc")).strip("-")
        target, _ = QFileDialog.getSaveFileName(self, "保存接口文档",
                                               f"{slug or 'api-doc'}.md",
                                               "Markdown (*.md);;所有文件 (*)")
        if not target:
            return
        if not os.path.splitext(target)[1]:
            target += ".md"
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(self._markdown)
            self._flash(i18n.trf("已保存 {name}", name=os.path.basename(target)))
        except OSError as exc:
            t = theme()
            self._flash(i18n.tr("保存失败"))
            self._toolbar_status.setStyleSheet(
                f"color: {t.danger}; background: transparent;")
            self._toolbar_status.setToolTip(str(exc))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)


class VLine(QWidget):
    """1px 竖向分隔线（比一张 Divider 省事，也不会被拉宽）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(1)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setPen(C(t.border))
        p.drawLine(0, 8, 0, self.height() - 8)
        p.end()


def _strip_head(md: str) -> str:
    """去掉正文开头的 # 标题与「`METHOD` url」行，避免和顶部名片重复。"""
    text = (md or "").lstrip("\n")
    lines = text.split("\n")
    while lines and (lines[0].startswith("# ") or lines[0].startswith("`")):
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return "\n".join(lines)


def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"
