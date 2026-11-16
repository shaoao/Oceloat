"""代码视图：行号、JSON 语法高亮、查找高亮、JSON 树形浏览。"""
from __future__ import annotations

import json
import weakref
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QSyntaxHighlighter,
    QTextFormat,
    QPainter,
)
from PyQt6.QtWidgets import (
    QPlainTextEdit,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from .theme import C, font, mono, theme

PUNCT = "#6E6E78"
JSON_KEY_DARK = "#E4EAF3"
JSON_STR_DARK = "#93C4A3"
JSON_NUM_DARK = "#DCBF86"
JSON_KW_DARK = "#8FA9C9"

JSON_KEY_LIGHT = "#2C3E50"
JSON_STR_LIGHT = "#2F6B4F"
JSON_NUM_LIGHT = "#8A5A18"
JSON_KW_LIGHT = "#2E5A8A"


def _colors():
    t = theme()
    if t.is_dark:
        return JSON_KEY_DARK, JSON_STR_DARK, JSON_NUM_DARK, JSON_KW_DARK, PUNCT, t.text_faint
    return JSON_KEY_LIGHT, JSON_STR_LIGHT, JSON_NUM_LIGHT, JSON_KW_LIGHT, "#8A8A92", t.text_faint


class JsonHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        import re

        key, string, number, keyword, punct, comment = _colors()
        # 注意顺序：后应用的规则会覆盖先前的，因此「键」必须放在「字符串」之后
        rules = [
            (re.compile(r'"(?:[^"\\]|\\.)*"'), string, QFont.Weight.Normal),
            (re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])"), number, QFont.Weight.Normal),
            (re.compile(r"\b(?:true|false|null)\b"), keyword, QFont.Weight.Medium),
            (re.compile(r"[{}\[\],:]"), punct, QFont.Weight.Normal),
            (re.compile(r'"(?:[^"\\]|\\.)*"(?=\s*:)'), key, QFont.Weight.Medium),
        ]
        for pattern, color, weight in rules:
            for m in pattern.finditer(text):
                fmt = QTextCharFormat()
                fmt.setForeground(C(color))
                fmt.setFontWeight(weight)
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class CodeHighlighter(QSyntaxHighlighter):
    """多语言通用语法高亮：关键字 / 字符串 / 数字 / 注释 / 参数 / 函数调用 / URL。

    用于代码示例与代码片段：Python / JavaScript / Go / Java / PHP / C# / Kotlin /
    PowerShell / shell（curl、HTTPie）。颜色全部取自主题，切主题时由
    CodeView.refresh_theme 重新高亮。
    """

    KEYWORDS = {
        "python": "import from as def class return if else elif for while in not and or None True False async await print lambda with try except raise yield pass",
        "javascript": "const let var function return if else for while await async new class extends this null undefined true false import export from break continue",
        "go": "package import func var const if else for range return type struct interface nil true false defer go chan select switch case map make new panic recover",
        "java": "import package public private protected class interface static final void new return if else for while throws try catch var String System true false null",
        "php": "php echo curl_setopt curl_init curl_exec curl_close CURLOPT_URL true false null public private function return if else foreach array",
        "csharp": "using var new class public private static void return if else for while async await true false null string int HttpClient Console",
        "kotlin": "import fun val var class object if else for while return when is in null true false runBlocking println",
        "powershell": "Write-Output Invoke-WebRequest Uri Method Headers Body StatusCode Content true false param",
        "shell": "curl http httpie https -X -H -d -F -k -L -s -I -v --data-raw --data-urlencode --form --header --request --location --insecure --verbose",
    }

    # PowerShell 用 # 注释、shell 也是；JS/Go/Java/C#/Kotlin/PHP 用 //
    _SLASH_COMMENT = ("javascript", "go", "java", "csharp", "kotlin", "php")

    def __init__(self, doc, language: str = "python"):
        super().__init__(doc)
        self.language = language if language in self.KEYWORDS else "python"
        self._rebuild()

    def set_language(self, language: str) -> None:
        self.language = language if language in self.KEYWORDS else "python"
        self._rebuild()
        self.rehighlight()

    def _rebuild(self) -> None:
        import re

        t = theme()
        key_col = "#9BB8E0" if t.is_dark else "#2E5A8A"
        str_col = "#9CCEAE" if t.is_dark else "#2F6B4F"
        num_col = "#D9BB86" if t.is_dark else "#8A5A18"
        fn_col = "#B4C4DC" if t.is_dark else "#3B5A7A"
        cmt_col = t.text_faint
        flag_col = "#C8B48C" if t.is_dark else "#7A5A22"
        words = self.KEYWORDS[self.language].split()

        comment = (r"(?:^|\s)//[^\n]*" if self.language in self._SLASH_COMMENT
                   else r"(?:^|\s)#[^\n]*")
        rules = [
            (comment, cmt_col, QFont.Weight.Normal),
            # 字符串：双引号 / 单引号 / 反引号
            (r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`', str_col, QFont.Weight.Normal),
            # 裸 URL 单独染色，示例里一眼看到请求打到哪
            (r"https?://[^\s'\"`\\]+", str_col, QFont.Weight.Normal),
            # 命令行参数：-X / --data-raw
            (r"(?<![\w-])--?[A-Za-z][\w-]*", flag_col, QFont.Weight.Medium),
            (r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", num_col, QFont.Weight.Normal),
            (r"\b(?:" + "|".join(re.escape(w) for w in words if not w.startswith("-"))
             + r")\b", key_col, QFont.Weight.DemiBold),
            (r"\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()", fn_col, QFont.Weight.Normal),
        ]
        self._rules = [(re.compile(pat), col, weight) for pat, col, weight in rules]

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        for pattern, color, weight in self._rules:
            for m in pattern.finditer(text):
                fmt = QTextCharFormat()
                fmt.setForeground(C(color))
                fmt.setFontWeight(weight)
                start = m.start(1) if m.lastindex else m.start()
                length = len(m.group(1)) if m.lastindex else m.end() - m.start()
                self.setFormat(start, length, fmt)


class _Gutter(QWidget):
    def __init__(self, editor: "CodeView"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):  # noqa: N802
        self.editor.paint_gutter(event)


class CodeView(QPlainTextEdit):
    """带行号与查找高亮的只读代码视图。"""

    # 全局代码字号（设置页可改，改完立刻作用于所有已打开的视图）
    DEFAULT_SIZE = 11.8
    _size = DEFAULT_SIZE
    _views: "weakref.WeakSet[CodeView]" = weakref.WeakSet()

    def __init__(self, read_only: bool = True, highlight: bool = True,
                 show_gutter: bool = True, wrap: bool = False, parent=None,
                 doc_margin: int = 10, pad: int = 6):
        super().__init__(parent)
        self._gutter = _Gutter(self)
        self._show_gutter = show_gutter
        self._pad = pad
        self._matches: List[QTextCursor] = []
        self._match_index = 0
        self._font = mono(CodeView._size)
        self.setFont(self._font)
        self.setReadOnly(read_only)
        if read_only:
            # 只读代码块不显示插入光标：文档里那根一闪一闪的竖线很像「可以编辑」
            self.setCursorWidth(0)
        self.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.WidgetWidth if wrap
            else QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setStyleSheet(f"QPlainTextEdit {{ background: transparent; border: none; }}")
        self.document().setDocumentMargin(doc_margin)
        self._hl = None
        if highlight:
            self._hl = JsonHighlighter(self.document())
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_width()
        CodeView._views.add(self)

    # -------------------------------------------------- 语法高亮开关
    def set_highlight(self, on: bool) -> None:
        """超大文档（几百 KB 起）关掉语法高亮：重新着色的开销比读内容本身还大。"""
        if on and getattr(self, "_hl", None) is None:
            self._hl = JsonHighlighter(self.document())
            self._hl.rehighlight()
        elif not on and getattr(self, "_hl", None) is not None:
            self._hl.setDocument(None)
            self._hl = None
            from PyQt6.QtGui import QBrush

            cur = QTextCursor(self.document())
            cur.select(QTextCursor.SelectionType.Document)
            fmt = QTextCharFormat()
            fmt.setForeground(QBrush(C(theme().text)))
            cur.mergeCharFormat(fmt)

    # -------------------------------------------------- 字号
    def set_code_font_size(self, size: float) -> None:
        self._font = mono(size)
        self.setFont(self._font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self._gutter.update()
        self._update_width()

    @classmethod
    def set_global_size(cls, size: float) -> None:
        """改字号：立刻作用于所有已存在的代码视图。"""
        cls._size = float(size)
        for v in list(cls._views):
            try:
                v.set_code_font_size(cls._size)
            except RuntimeError:      # 底层对象已被销毁
                pass

    # -------------------------------------------------- 行号
    def gutter_width(self) -> int:
        if not self._show_gutter:
            return self._pad
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect: QRect, dy: int):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_width()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        t = theme()
        p = QPainter(self._gutter)
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        p.setFont(mono(10))
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.setPen(C(t.text_faint))
                p.drawText(0, int(top), self._gutter.width() - 8, int(self.fontMetrics().height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
                           str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            num += 1
        p.end()

    # -------------------------------------------------- 语法语言
    def set_language(self, language: Optional[str]) -> None:
        """切换代码语言；None 恢复 JSON 高亮，其他语言用通用高亮器。"""
        hl = getattr(self, "_hl", None)
        if language is None:
            if not isinstance(hl, JsonHighlighter):
                if hl is not None:
                    hl.setDocument(None)      # type: ignore[arg-type]
                self._hl = JsonHighlighter(self.document())
            return
        if not isinstance(hl, CodeHighlighter):
            if hl is not None:
                hl.setDocument(None)          # type: ignore[arg-type]
            self._hl = CodeHighlighter(self.document(), language)
        else:
            self._hl.set_language(language)

    # -------------------------------------------------- 主题
    def refresh_theme(self) -> None:
        """切换主题后重新着色：语法高亮的颜色是写入文本格式的，必须重新高亮。"""
        hl = getattr(self, "_hl", None)
        if hl is not None:
            if isinstance(hl, CodeHighlighter):
                hl._rebuild()
            hl.rehighlight()
        self._apply_selections()
        self._gutter.update()
        self.viewport().update()

    # -------------------------------------------------- 查找
    def find_text(self, text: str, backwards: bool = False) -> Tuple[int, int]:
        self._clear_selections()
        if not text:
            self._matches = []
            return 0, 0
        matches: List[QTextCursor] = []
        cur = QTextCursor(self.document())
        while True:
            found = self.document().find(text, cur)
            if found.isNull():
                break
            matches.append(found)
            cur = found
            if len(matches) > 5000:
                break
        self._matches = matches
        if not matches:
            return 0, 0
        # 从当前光标位置向后找最近的匹配
        pos = self.textCursor().position()
        index = 0
        if backwards:
            index = len(matches) - 1
            for i, m in enumerate(matches):
                if m.selectionStart() >= pos:
                    index = max(0, i - 1)
                    break
        else:
            index = 0
            for i, m in enumerate(matches):
                if m.selectionStart() > pos:
                    index = i
                    break
        self._match_index = index
        self._apply_selections()
        return index + 1, len(matches)

    def find_next(self, text: str, backwards: bool = False) -> Tuple[int, int]:
        if not text:
            return 0, 0
        if not self._matches:
            return self.find_text(text, backwards)
        if backwards:
            self._match_index = (self._match_index - 1) % len(self._matches)
        else:
            self._match_index = (self._match_index + 1) % len(self._matches)
        self._apply_selections()
        return self._match_index + 1, len(self._matches)

    def _clear_selections(self):
        self.setExtraSelections([])

    def _apply_selections(self):
        t = theme()
        sels = []
        base = QColor(C(t.warning))
        base.setAlpha(46)
        cur_col = QColor(C(t.warning))
        cur_col.setAlpha(110)
        for i, m in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = m
            fmt = QTextCharFormat()
            fmt.setBackground(cur_col if i == self._match_index else base)
            sel.format = fmt
            sels.append(sel)
        self.setExtraSelections(sels)
        target = self._matches[self._match_index]
        cursor = QTextCursor(target)
        self.setTextCursor(cursor)
        self.centerCursor()


class JsonTree(QTreeWidget):
    """JSON 树：键/值两列，按类型着色，默认展开两层。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setIndentation(13)
        self.setUniformRowHeights(True)
        self.setAnimated(True)
        self.setExpandsOnDoubleClick(True)
        self.setFont(mono(11.5))
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.setHorizontalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QTreeWidget.ScrollMode.ScrollPerPixel)
        self._key_font = mono(11.5, QFont.Weight.Medium)
        self._data: Any = None

    def set_data(self, obj: Any, expand_depth: int = 2) -> None:
        self.clear()
        self._data = obj
        t = theme()
        if isinstance(obj, dict):
            for k, v in obj.items():
                self._add(self.invisibleRootItem(), str(k), v, expand_depth, t)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self._add(self.invisibleRootItem(), str(i), v, expand_depth, t)
        else:
            self._add(self.invisibleRootItem(), "value", obj, expand_depth, t)

    def _add(self, parent, key: str, value: Any, depth: int, t) -> None:
        item = QTreeWidgetItem(parent)
        item.setText(0, key)
        item.setFont(0, self._key_font)
        item.setForeground(0, C(t.text_dim))
        is_container = isinstance(value, (dict, list))
        if is_container:
            n = len(value)
            item.setText(1, f"{'{}' if isinstance(value, dict) else '[]'}  {n} {'keys' if isinstance(value, dict) else 'items'}")
            item.setForeground(1, C(t.text_faint))
            item.setFont(1, mono(10.5))
            for k, v in (value.items() if isinstance(value, dict) else enumerate(value)):
                self._add(item, str(k), v, depth - 1, t)
            if depth > 0:
                item.setExpanded(True)
        else:
            if isinstance(value, str):
                item.setText(1, f'"{value}"')
                item.setForeground(1, C(JSON_STR_DARK if t.is_dark else JSON_STR_LIGHT))
            elif isinstance(value, bool):
                item.setText(1, "true" if value else "false")
                item.setForeground(1, C(JSON_KW_DARK if t.is_dark else JSON_KW_LIGHT))
            elif value is None:
                item.setText(1, "null")
                item.setForeground(1, C(t.text_faint))
            else:
                item.setText(1, str(value))
                item.setForeground(1, C(JSON_NUM_DARK if t.is_dark else JSON_NUM_LIGHT))
            item.setFont(1, mono(11.5))

    def expand_all(self):
        self.expandAll()

    def collapse_all(self):
        self.collapseAll()


# ---------------------------------------------------------------- 工具函数

def pretty_json(text: str) -> Tuple[str, bool]:
    """返回 (格式化文本, 是否成功)。超大文本直接原样返回以保流畅。"""
    if not text.strip():
        return text, False
    if len(text) > 4_000_000:
        return text, False
    try:
        data = json.loads(text)
    except Exception:
        return text, False
    try:
        return json.dumps(data, indent=2, ensure_ascii=False), True
    except Exception:
        return text, False


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.2f} MB"


def human_elapsed(ms: int) -> str:
    if ms < 1000:
        return f"{ms} ms"
    if ms < 60_000:
        return f"{ms / 1000:.2f} s"
    return f"{ms // 60000}m {(ms % 60000) / 1000:.1f}s"


def ctype_label(ct: str) -> str:
    if not ct:
        return "unknown"
    base = ct.split(";")[0].strip()
    return base.replace("application/", "")
