"""极简 Markdown 渲染：把一份 .md 拆成原生控件渲染，而不是塞进 QTextBrowser。

为什么不用 QTextBrowser：
- 代码块要高亮、要能单独折叠/复制，控件化才做得到；
- 表格在 QTextDocument 里只能靠 HTML table，macOS 上单元格内边距很难看；
- 我们的接口文档每段都是「标题 + 说明 + 表格 + 代码」，控件化排版更接近 ApiFox。

支持范围（够用于本项目的接口文档，也能看一般 README）：
# 标题 1~3、段落、`-`/`1.` 列表、`>` 引用、`---` 分隔线、
``` 围栏代码块（带语言）、| 表格 |、
行内的 **粗体** / `代码` / [链接](url)。
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .code_editor import CodeView
from .theme import C, font, mono, theme
from .widgets import Card, HBox, Label, Quote, icon_button

# 富文本里只能写 font-family，且必须是系统里真实存在的字体：
# 写 "SF Mono" 这种没装的字体，Qt 每次都要解析别名（一次 60ms）。
MONO_CSS = "Menlo,Consolas,monospace"

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_FENCE_RE = re.compile(r"^```([\w+#-]*)\s*$")
_LIST_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")


# ---------------------------------------------------------------- 解析


def parse_blocks(md: str) -> List[Dict[str, Any]]:
    """把 Markdown 切成块。不认识的行按段落处理，不抛异常。"""
    lines = (md or "").replace("\r\n", "\n").split("\n")
    blocks: List[Dict[str, Any]] = []
    i, n = 0, len(lines)
    para: List[str] = []

    def flush_para() -> None:
        if para:
            text = " ".join(x.strip() for x in para).strip()
            if text:
                blocks.append({"kind": "p", "text": text})
            para.clear()

    while i < n:
        line = lines[i]
        fence = _FENCE_RE.match(line.strip())
        if fence:
            flush_para()
            lang = (fence.group(1) or "").strip().lower()
            body: List[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            i += 1
            blocks.append({"kind": "code", "lang": lang, "code": "\n".join(body)})
            continue
        head = _HEADING_RE.match(line)
        if head:
            flush_para()
            blocks.append({"kind": f"h{len(head.group(1))}", "text": head.group(2).strip()})
            i += 1
            continue
        if line.strip() in ("---", "***", "___"):
            flush_para()
            blocks.append({"kind": "hr"})
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < n and set(lines[i + 1].replace("|", "")
                                                              .replace("-", "").replace(":", "")
                                                              .strip()) == set():
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: List[List[str]] = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            blocks.append({"kind": "table", "header": header, "rows": rows})
            continue
        if line.strip().startswith(">"):
            flush_para()
            quote: List[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append({"kind": "quote", "text": " ".join(quote)})
            continue
        if _LIST_RE.match(line):
            flush_para()
            items: List[str] = []
            ordered = bool(re.match(r"^\s*\d+[.)]", line))
            while i < n:
                m = _LIST_RE.match(lines[i])
                if not m:
                    break
                items.append(m.group(2).strip())
                i += 1
            blocks.append({"kind": "list", "items": items, "ordered": ordered})
            continue
        if not line.strip():
            flush_para()
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para()
    return blocks


def rich(text: str, color: str) -> str:
    """把行内文本包成带颜色的富文本。

    QLabel 一旦按 RichText 渲染，样式表里的 color 就不再生效（Qt 用文档默认色），
    所以颜色必须写进 HTML 本身，否则标题会变成几乎看不见的暗灰。
    """
    return f'<span style="color:{color};">{inline_html(text)}</span>'


def inline_html(text: str) -> str:
    """行内语法 → 富文本。先转义再替换，避免响应体里的 < > 破坏排版。"""
    t = theme()
    out = html.escape(text or "")
    code_bg = "rgba(255,255,255,0.075)" if t.is_dark else "rgba(0,0,0,0.055)"
    out = re.sub(r"`([^`]+)`",
                 lambda m: (f'<code style="background:{code_bg}; padding:1px 4px;'
                            f' border-radius:4px; font-family:{MONO_CSS};">'
                            f'{m.group(1)}</code>'), out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 r'<a href="\2" style="color:%s; text-decoration:none;">\1</a>' % t.text_dim,
                 out)
    return out


# ---------------------------------------------------------------- 代码块

# Markdown 围栏语言 → CodeHighlighter 的语法名。
# 代码生成给的是 curl / httpie / js / cs 这些写法，这里统一归一化，
# 否则十种语言里只有 JSON 会亮，其余全是白字。
_LANG_ALIAS = {
    "curl": "shell", "shell": "shell", "bash": "shell", "sh": "shell", "zsh": "shell",
    "httpie": "shell", "http": "shell", "console": "shell",
    "js": "javascript", "javascript": "javascript", "node": "javascript", "ts": "javascript",
    "typescript": "javascript", "json": "json", "jsonc": "json",
    "py": "python", "python": "python",
    "go": "go", "golang": "go",
    "java": "java",
    "php": "php",
    "cs": "csharp", "c#": "csharp", "csharp": "csharp",
    "kt": "kotlin", "kotlin": "kotlin",
    "ps": "powershell", "ps1": "powershell", "powershell": "powershell",
}


def syntax_of(lang: str) -> str:
    """围栏语言 → 'json' / 'python' / ... ；不认识的返回空串（不高亮）。"""
    return _LANG_ALIAS.get((lang or "").strip().lower(), "")


class CodeBlock(Card):
    """带语言标签与复制按钮的代码块。

    排版规矩（之前踩过的坑都在这）：
    - 代码正文必须和左上角的语言标签左对齐 —— 关掉行号槽、把文档边距归零，
      只靠外层 14px 内边距定位，文本才不会缩进成「悬空」的样子；
    - 头部固定 30px，正文紧贴头部；卡片被拉高时多余空间留在底部，
      而不是把几行代码垂直居中（这就是之前「代码悬在中间」的原因）；
    - 高度按真实行高算，滚动条只在超出上限时出现。
    """

    PAD_X = 14
    HEAD_H = 30

    def __init__(self, code: str, lang: str = "", parent=None, max_height: int = 300,
                 show_header: bool = True, fixed_height: Optional[int] = None):
        super().__init__(radius=9, parent=parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        t = theme()
        name = (lang or "text").upper()

        head = QWidget()
        head.setFixedHeight(self.HEAD_H)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(self.PAD_X, 0, 8, 0)
        hl.setSpacing(6)
        tag = Label(name, 9.2, t.text_faint, mono_font=True, spacing=0.8)
        hl.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch(1)
        copy_btn = icon_button("copy", "复制这段代码", 22, 12)
        copy_btn.clicked.connect(lambda: self._copy(code))
        hl.addWidget(copy_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        if show_header:
            lay.addWidget(head)
        else:
            head.setFixedHeight(10)
            lay.addWidget(head)

        view = CodeView(read_only=True, highlight=False, show_gutter=False, wrap=True,
                        doc_margin=0, pad=0)
        view.setFont(mono(11.2))
        view.setPlainText(code)
        key = syntax_of(lang)
        if key:
            view.set_language(None if key == "json" else key)
        # 折行之后「逻辑行数」不等于「显示行数」，高度只能问文档本身要。
        # 之前的写法按 \n 数行，长 URL 一折行就少算，代码底部于是出现滚动条。
        self._view = view
        self._code = code
        self._lh = max(1, view.fontMetrics().lineSpacing())
        self._cap = max(max_height, self._lh * 2)
        # fixed_height：所有类目共用同一个高度，切换语言时不再忽高忽低。
        # 超过的部分交给内部滚动条。
        self._fixed_height = fixed_height
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        view.setFixedHeight(self._lh * min(max(code.count("\n") + 1, 1), 12)
                            if fixed_height is None else int(fixed_height))

        pad = QWidget()
        pl = QVBoxLayout(pad)
        pl.setContentsMargins(self.PAD_X, 2 if show_header else 0, self.PAD_X, 12)
        pl.setSpacing(0)
        pl.addWidget(view, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(pad, 0)
        # 卡片被拉高时，剩余空间落在底部 —— 代码永远贴着语言标签
        lay.addStretch(1)
        QTimer.singleShot(0, self._fit_height)

    def _fit_height(self, *_args) -> None:
        """按「折行后的真实行数」设置视口高度。

        折行宽度取视口宽度：控件还没布局完时宽度是 1，这时候不能硬算，
        等 resize 事件再来一次。高度必须是行高的整数倍，否则底部会露出半行。
        """
        try:
            width = self._view.viewport().width()
        except RuntimeError:          # 控件已销毁
            return
        if width < 48:
            return
        from PyQt6.QtGui import QFontMetricsF

        if self._fixed_height is not None:
            height = int(self._fixed_height)
            if self._view.height() != height:
                self._view.setFixedHeight(height)
                self.updateGeometry()
            return

        fm = QFontMetricsF(self._view.font())
        total = 0
        for line in (self._code or "").split("\n"):
            wide = fm.horizontalAdvance(line) if line else 0
            total += max(1, -(-int(wide) // width))       # ceil
        need = max(total, 1) * self._lh
        # 不多给 2px：QPlainTextEdit 的视口正好等于行高之和时会判定「差一点」，
        # 于是冒出一条没用的滚动条
        height = need + 2 if need <= self._cap else self._cap
        if self._view.height() != height:
            self._view.setFixedHeight(height)
            self.updateGeometry()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self._fit_height)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._fit_height)

    @staticmethod
    def _copy(code: str) -> None:
        QApplication.clipboard().setText(code)


# ---------------------------------------------------------------- 表格


class _TableHead(QWidget):
    """表头：一整条淡底 + 底部 1px 分隔线，顶部两个圆角跟卡片对齐。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0, 0, 0, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.elevated))
        p.drawRoundedRect(r, 9, 9)
        # 下两个角要方：再补一条矩形盖住圆角，表头才像「栏」而不是胶囊
        p.drawRect(QRectF(r.left(), r.bottom() - 9, r.width(), 9))
        p.setPen(QPen(C(t.border), 1))
        p.drawLine(int(r.left()) + 1, self.height() - 1, int(r.right()) - 1,
                   self.height() - 1)
        p.end()


class _TableRow(QWidget):
    """一行数据：底部 1px 分隔线，不像素写死行高（内容多的时候自己长高）。"""

    def __init__(self, last: bool = False, parent=None):
        super().__init__(parent)
        self._last = last

    def paintEvent(self, _e):
        if self._last:
            return
        t = theme()
        p = QPainter(self)
        p.setPen(QPen(C(t.border), 1))
        p.drawLine(TableBlock.PAD_X, self.height() - 1,
                   self.width() - TableBlock.PAD_X, self.height() - 1)
        p.end()


class TableBlock(QWidget):
    """接口文档里的表格。

    之前每格是一个写死宽度的 QLabel，表头和数据各算各的，行高也参差不齐 ——
    结果就是「表格很丑」。现在：
    - 表头单独一条（淡底 + 34px 固定高），和数据列共用同一组列宽；
    - 每行上下 8px 内边距、行与行之间 1px 线，长内容自动换行；
    - 首列宽度按最长键名实测一次后钳在 96~210，其余列等分剩余宽度。
    """

    PAD_X = 14
    GAP = 14

    def __init__(self, header: List[str], rows: List[List[str]], parent=None):
        super().__init__(parent)
        self.header = [str(h or "") for h in header] or [""]
        self.rows = [[str(c or "") for c in r] for r in rows]
        t = theme()
        n = len(self.header)
        self.col0 = self._measure_first()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        card = Card(radius=9)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(1, 1, 1, 1)
        inner.setSpacing(0)

        head = _TableHead()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(self.PAD_X, 0, self.PAD_X, 0)
        hl.setSpacing(self.GAP)
        for i, name in enumerate(self.header):
            lab = Label(name.upper() if name.isascii() else name, 9.8, t.text_faint,
                        weight=QFont.Weight.DemiBold, spacing=0.5)
            lab.setMinimumWidth(40)
            if i == 0:
                lab.setFixedWidth(self.col0)
                hl.addWidget(lab, 0, Qt.AlignmentFlag.AlignVCenter)
            else:
                hl.addWidget(lab, 1, Qt.AlignmentFlag.AlignVCenter)
        inner.addWidget(head)

        for idx, row in enumerate(self.rows):
            inner.addWidget(self._build_row(row, idx == len(self.rows) - 1))

        if not self.rows:
            empty = Label("（无数据）", 11, t.text_faint)
            inner.addWidget(HBox(empty, 1, margins=(self.PAD_X, 10, self.PAD_X, 10)))
        lay.addWidget(card)

    # -------------------------------------------------- 内部
    def _measure_first(self) -> int:
        """首列宽度：量一遍所有键名（含表头）后钳在合理区间，避免长键名被截断。"""
        from PyQt6.QtGui import QFontMetricsF

        body = QFontMetricsF(font(11.9))
        head = QFontMetricsF(font(9.8, QFont.Weight.DemiBold))
        widest = head.horizontalAdvance(self.header[0]) if self.header else 0
        for r in self.rows:
            if r:
                widest = max(widest, body.horizontalAdvance(_plain(r[0])))
        return int(min(max(widest + 6, 96), 210))

    def _build_row(self, row: List[str], last: bool) -> QWidget:
        t = theme()
        item = _TableRow(last)
        rb = QHBoxLayout(item)
        rb.setContentsMargins(self.PAD_X, 8, self.PAD_X, 8)
        rb.setSpacing(self.GAP)
        for i in range(len(self.header)):
            cell = row[i] if i < len(row) else ""
            lab = QLabel(rich(cell, t.text if i == 0 else t.text_dim))
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            lab.setStyleSheet("background: transparent; font-size: 11.9px;")
            lab.setMinimumWidth(40)
            if i == 0:
                lab.setFixedWidth(self.col0)
                rb.addWidget(lab, 0, Qt.AlignmentFlag.AlignTop)
            else:
                rb.addWidget(lab, 1, Qt.AlignmentFlag.AlignTop)
        return item


def _plain(text: str) -> str:
    """去掉行内标记，只留字符（量宽度用，避免 ** 和反引号占位置）。"""
    return re.sub(r"[`*]|\[([^\]]+)\]\([^)]*\)", r"\1", text or "")


# ---------------------------------------------------------------- 渲染容器


class MarkdownView(QScrollArea):
    """把 Markdown 渲染成一列原生控件，并记录标题位置供大纲跳转。"""

    headingsChanged = pyqtSignal(list)      # [(level, text)]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._lay = QVBoxLayout(self._host)
        self._lay.setContentsMargins(26, 18, 26, 28)
        self._lay.setSpacing(10)
        self._lay.addStretch(1)
        self.setWidget(self._host)
        self._headings: List[Tuple[int, str, QWidget]] = []
        self.blocks: List[Dict[str, Any]] = []

    # -------------------------------------------------- API
    def set_markdown(self, md: str) -> None:
        self.clear()
        self.blocks = parse_blocks(md)
        for block in self.blocks:
            w = self._build(block)
            if w is None:
                continue
            if block["kind"] in ("h1", "h2", "h3", "h4"):
                self._headings.append((int(block["kind"][1]), block["text"], w))
            self._lay.insertWidget(self._lay.count() - 1, w)
        self.headingsChanged.emit([(lvl, text) for lvl, text, _w in self._headings])

    def clear(self) -> None:
        self._headings.clear()
        while self._lay.count() > 1:
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def scroll_to_heading(self, index: int) -> None:
        if 0 <= index < len(self._headings):
            self.ensureWidgetVisible(self._headings[index][2], 0, 24)

    # -------------------------------------------------- 单块渲染
    def _build(self, block: Dict[str, Any]) -> Optional[QWidget]:
        t = theme()
        kind = block["kind"]
        if kind == "hr":
            line = QWidget()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {t.border}; margin: 6px 0;")
            return line
        if kind == "code":
            return CodeBlock(block["code"], block["lang"])
        if kind == "table":
            return TableBlock(block["header"], block["rows"])
        if kind == "list":
            box = QWidget()
            bl = QVBoxLayout(box)
            bl.setContentsMargins(4, 0, 0, 0)
            bl.setSpacing(4)
            for i, item in enumerate(block["items"]):
                bullet = f"{i + 1}." if block.get("ordered") else "·"
                lab = QLabel(f'<span style="color:{t.text_faint};">{bullet}</span>&nbsp;&nbsp;'
                             f'<span style="color:{t.text_dim};">{inline_html(item)}</span>')
                lab.setTextFormat(Qt.TextFormat.RichText)
                lab.setWordWrap(True)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lab.setStyleSheet("background: transparent; font-size: 12px;")
                bl.addWidget(lab)
            return box
        if kind == "quote":
            return Quote(rich(block["text"], t.text_dim))
        if kind.startswith("h"):
            level = int(kind[1])
            sizes = {1: 21.0, 2: 15.0, 3: 13.0, 4: 12.2}
            weights = {1: QFont.Weight.DemiBold, 2: QFont.Weight.DemiBold,
                       3: QFont.Weight.Medium, 4: QFont.Weight.Medium}
            colors = {1: t.text, 2: t.text, 3: t.text_dim, 4: t.text_dim}
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(0, 20 if level == 1 else 14, 0, 5 if level == 1 else 3)
            wl.setSpacing(8)
            lab = QLabel(rich(block["text"], colors[level]))
            lab.setTextFormat(Qt.TextFormat.RichText)
            lab.setWordWrap(True)
            lab.setFont(font(sizes[level], weights[level], -0.15 if level == 1 else 0.0))
            lab.setStyleSheet("background: transparent;")
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            if level == 2:
                # 二级标题前面加一小截强调色竖条：层级一眼能看出来，但不用彩色
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(8)
                bar = QWidget()
                bar.setFixedSize(2, 13)
                bar.setStyleSheet(f"background: {t.accent_dim}; border-radius: 1px;")
                rl.addWidget(bar, 0, Qt.AlignmentFlag.AlignVCenter)
                rl.addWidget(lab, 1)
                wl.addWidget(row)
            else:
                wl.addWidget(lab)
            if level <= 2:
                line = QWidget()
                line.setFixedHeight(1)
                line.setStyleSheet(f"background: {t.border};")
                wl.addWidget(line)
            return wrap
        # 段落
        lab = QLabel(rich(block["text"], t.text_dim))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setWordWrap(True)
        lab.setOpenExternalLinks(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                   | Qt.TextInteractionFlag.LinksAccessibleByMouse)
        lab.setStyleSheet("background: transparent; font-size: 12.4px;")
        return lab
