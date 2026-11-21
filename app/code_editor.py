"""代码视图：统一高亮、行号、自动补全/缩进、查找高亮、JSON 树形浏览。

高亮方案全局统一：JSON 与九种语言共用同一套 token 配色（One Dark 风格），
深色主题下关键字粉紫、函数名蓝、字符串黄绿、数字橙、注释灰 —— 跟现代
编辑器一致，写起来更顺眼。浅色主题有对应的一套降饱和配色。
"""
from __future__ import annotations

import json
import re
import weakref
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QRect, QRectF, QSize, Qt
from PyQt6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QPalette,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QSyntaxHighlighter,
    QTextFormat,
    QPainter,
)
from PyQt6.QtWidgets import (
    QHeaderView,
    QPlainTextEdit,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from . import i18n
from .theme import C, font, mono, theme

# ---------------------------------------------------------------- 统一 token 配色
# 深色：One Dark Pro（Atom / VS Code 同款）的官方色值，逐项对齐，不做近似；
# 浅色：对应的 One Light，色相互相对应。
# 顺序：关键字 > 字面量 > 字符串 > 数字 > 参数 > 标点 > 注释
_TOKENS_DARK: Dict[str, str] = {
    "key": "#C678DD",        # def / class / import / const / function —— 紫
    "keyword": "#C678DD",    # return / if / else / for —— 紫
    "literal": "#D19A66",    # true / false / null / this —— 橙
    "string": "#98C379",     # 字符串 —— 绿
    "number": "#D19A66",     # 数字 —— 橙
    "param": "#D19A66",      # 函数参数 / flag / 属性名 —— 橙
    "func": "#61AFEF",       # 函数名 —— 蓝
    "builtin": "#56B6C2",    # 内建 / 类型 / 实体 —— 青
    "punct": "#ABB2BF",      # 标点 —— 正文灰
    "comment": "#5C6370",    # 注释 —— 灰紫
    "url": "#61AFEF",
    "property": "#E06C75",   # JSON key —— 红
    "tag": "#E06C75",        # HTML 标签名 —— 红
    "attr": "#D19A66",       # HTML 属性名 —— 橙
}

_TOKENS_LIGHT: Dict[str, str] = {
    "key": "#A626A4",
    "keyword": "#A626A4",
    "literal": "#986801",
    "string": "#50A14F",
    "number": "#986801",
    "param": "#986801",
    "func": "#4078F2",
    "builtin": "#0184BC",
    "punct": "#383A42",
    "comment": "#A0A1A7",
    "url": "#4078F2",
    "property": "#E45649",
    "tag": "#E45649",
    "attr": "#986801",
}


def tokens() -> Dict[str, str]:
    """当前主题下的一整套 token 颜色 —— 所有高亮器都从这里取，保证全局一致。"""
    return _TOKENS_DARK if theme().is_dark else _TOKENS_LIGHT


class JsonHighlighter(QSyntaxHighlighter):
    """JSON / JSONC 高亮：键、字符串、数字、字面量、标点（支持 // 注释）。"""

    def __init__(self, doc):
        super().__init__(doc)

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        c = tokens()
        # 注意顺序：后应用的规则会覆盖先前的，因此「键」必须放在「字符串」之后
        rules = [
            (re.compile(r"//[^\n]*"), c["comment"], QFont.Weight.Normal),
            (re.compile(r'"(?:[^"\\]|\\.)*"'), c["string"], QFont.Weight.Normal),
            (re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])"),
             c["number"], QFont.Weight.Normal),
            (re.compile(r"\b(?:true|false|null)\b"), c["literal"], QFont.Weight.Normal),
            (re.compile(r"[{}\[\],:]"), c["punct"], QFont.Weight.Normal),
            (re.compile(r'"(?:[^"\\]|\\.)*"(?=\s*:)'), c["property"], QFont.Weight.Normal),
        ]
        for pattern, color, weight in rules:
            for m in pattern.finditer(text):
                fmt = QTextCharFormat()
                fmt.setForeground(C(color))
                fmt.setFontWeight(weight)
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class HtmlHighlighter(QSyntaxHighlighter):
    """HTML / XML 高亮：标签名、属性名、属性值、尖括号、注释、DOCTYPE、实体，
    以及内嵌 <script> / <style> 的二级着色。

    颜色全部取自 tokens()，和 JSON / CodeHighlighter 共用同一套 One Dark 方案，
    保证「统一的高亮」。用 QSyntaxHighlighter 的 block state 在块间传递当前状态
    （文本 / 标签内 / 注释 / script / style），跨行的标签与多行注释、脚本都能
    连续着色，不会因为逐块高亮而断色。
    """

    S_TEXT, S_TAG, S_COMMENT, S_SCRIPT, S_STYLE = 0, 1, 2, 3, 4

    # 内嵌脚本 / 样式里的二级规则，按「低优先级 → 高优先级」排列：
    # setFormat 后写覆盖先写，因此注释与字符串压在关键字、数字之上。
    _JS_RULES = [
        (r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", "number"),
        (r"\b[A-Za-z_$][\w$]*(?=\s*\()", "func"),
        (r"\b(?:const|let|var|function|return|if|else|for|while|new|class|this|"
         r"null|undefined|true|false|await|async|import|export|from|of|in|"
         r"typeof|throw|try|catch|switch|case|break|continue)\b", "key"),
        (r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|`[^`]*`", "value"),
        (r"/\*.*?\*/|//[^\n]*", "comment"),
    ]
    _CSS_RULES = [
        (r"(?<![\w-])\d+(?:\.\d+)?(?:px|em|rem|%|vh|vw|s|ms|deg)?\b|"
         r"#[0-9a-fA-F]{3,8}\b", "number"),
        (r"[A-Za-z-]+(?=\s*:)", "attr"),
        (r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'", "value"),
        (r"/\*.*?\*/", "comment"),
    ]

    def __init__(self, doc):
        super().__init__(doc)
        self._js = [(re.compile(p), k) for p, k in self._JS_RULES]
        self._css = [(re.compile(p), k) for p, k in self._CSS_RULES]
        self._tag = re.compile(r"[A-Za-z][\w:.-]*")
        self._attr = re.compile(r"[A-Za-z_:][\w:.-]*")
        self._entity = re.compile(r"&[\w#]+;")
        self._rebuild()

    def _rebuild(self) -> None:
        c = tokens()
        # 语义 token → 统一配色 token 的映射
        mapping = {
            "tag": "tag",         # 标签名 —— 红
            "attr": "attr",       # 属性名 —— 橙
            "value": "string",    # 属性值 —— 绿
            "punct": "punct",     # 尖括号 / 斜杠 / 等号 —— 正文灰
            "comment": "comment", # 注释 —— 灰紫
            "decl": "keyword",    # DOCTYPE / 声明 —— 紫
            "entity": "builtin",  # &nbsp; 实体 —— 青
            "key": "key",         # 脚本关键字 —— 紫
            "number": "number",   # 数字 —— 橙
            "func": "func",       # 脚本函数名 —— 蓝
        }
        self._fmts: Dict[str, QTextCharFormat] = {}
        for semantic, color_key in mapping.items():
            fmt = QTextCharFormat()
            fmt.setForeground(C(c[color_key]))
            fmt.setFontWeight(QFont.Weight.Normal)
            self._fmts[semantic] = fmt

    def _code_spans(self, seg: str, base: int, rules):
        out = []
        for pattern, key in rules:
            for mo in pattern.finditer(seg):
                out.append((base + mo.start(), mo.end() - mo.start(), key))
        return out

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        state = self.previousBlockState()
        if state < 0:
            state = self.S_TEXT
        n = len(text)
        i = 0
        spans = []
        pending_tag = ""
        while i < n:
            if state == self.S_TEXT:
                if text.startswith("<!--", i):
                    spans.append((i, 4, "comment")); i += 4; state = self.S_COMMENT; continue
                if text.startswith("</", i):
                    spans.append((i, 2, "punct")); i += 2
                    mo = self._tag.match(text, i)
                    if mo:
                        spans.append((i, mo.end() - i, "tag")); i = mo.end()
                    state = self.S_TAG; pending_tag = ""; continue
                if text.startswith("<!", i) or text.startswith("<?", i):
                    j = text.find(">", i)
                    if j < 0:
                        spans.append((i, n - i, "decl")); i = n
                    else:
                        spans.append((i, j + 1 - i, "decl")); i = j + 1
                    continue
                if text[i] == "<":
                    spans.append((i, 1, "punct")); i += 1
                    mo = self._tag.match(text, i)
                    if mo:
                        pending_tag = mo.group().lower()
                        spans.append((i, mo.end() - i, "tag")); i = mo.end()
                    else:
                        pending_tag = ""
                    state = self.S_TAG; continue
                if text[i] == "&":
                    mo = self._entity.match(text, i)
                    if mo:
                        spans.append((i, mo.end() - i, "entity")); i = mo.end(); continue
                i += 1
            elif state == self.S_TAG:
                if text.startswith("/>", i):
                    spans.append((i, 2, "punct")); i += 2; state = self.S_TEXT; continue
                ch = text[i]
                if ch == ">":
                    spans.append((i, 1, "punct")); i += 1
                    if pending_tag == "script":
                        state = self.S_SCRIPT
                    elif pending_tag == "style":
                        state = self.S_STYLE
                    else:
                        state = self.S_TEXT
                    pending_tag = ""; continue
                if ch in "\"'":
                    j = i + 1
                    while j < n and text[j] != ch:
                        j += 1
                    if j < n:
                        j += 1
                    spans.append((i, j - i, "value")); i = j; continue
                if ch == "=":
                    spans.append((i, 1, "punct")); i += 1; continue
                mo = self._attr.match(text, i)
                if mo:
                    spans.append((i, mo.end() - i, "attr")); i = mo.end(); continue
                i += 1
            elif state == self.S_COMMENT:
                j = text.find("-->", i)
                if j < 0:
                    spans.append((i, n - i, "comment")); i = n
                else:
                    spans.append((i, j + 3 - i, "comment")); i = j + 3; state = self.S_TEXT
                continue
            else:  # S_SCRIPT / S_STYLE
                close = "</script" if state == self.S_SCRIPT else "</style"
                rules = self._js if state == self.S_SCRIPT else self._css
                j = text.lower().find(close, i)
                if j >= 0:
                    if j > i:
                        spans.extend(self._code_spans(text[i:j], i, rules))
                    i = j; state = self.S_TEXT; continue
                if i < n:
                    spans.extend(self._code_spans(text[i:n], i, rules))
                i = n
        for start, length, key in spans:
            if length > 0:
                self.setFormat(start, length,
                               self._fmts.get(key, self._fmts["punct"]))
        self.setCurrentBlockState(state)


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

    _DECL = {
        "python": "def class",
        "javascript": "function class",
        "go": "func type struct interface",
        "java": "class interface",
        "php": "function class",
        "csharp": "class interface",
        "kotlin": "fun class object",
        "powershell": "function param",
        "shell": "",
    }
    # 各语言的内建/类型名（青色）
    _BUILTINS = {
        "python": "str int float bool list dict set tuple self",
        "javascript": "console JSON Math Promise window document",
        "go": "string int bool error byte rune",
        "java": "String Integer Boolean List Map",
        "php": "array string int bool",
        "csharp": "string int bool double var object",
        "kotlin": "String Int Boolean Long Unit",
        "powershell": "string int bool",
        "shell": "",
    }

    def _rebuild(self) -> None:
        c = tokens()
        words = self.KEYWORDS[self.language].split()
        decl = self._DECL.get(self.language, "").split()
        builtins = self._BUILTINS.get(self.language, "").split()
        comment_pat = (r"//[^\n]*" if self.language in self._SLASH_COMMENT
                       else r"#[^\n]*")

        rules = [
            (comment_pat, c["comment"], QFont.Weight.Normal),
            # 字符串：双引号 / 单引号 / 反引号
            (r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`[^`]*`', c["string"], QFont.Weight.Normal),
            # 裸 URL 单独染色，示例里一眼看到请求打到哪
            (r"https?://[^\s'\"`\\]+", c["url"], QFont.Weight.Normal),
            # 命令行参数：-X / --data-raw
            (r"(?<![\w-])--?[A-Za-z][\w-]*", c["param"], QFont.Weight.Normal),
            (r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", c["number"], QFont.Weight.Normal),
            # 声明关键字（def / class / function）用粉紫，比普通关键字更醒目
            (r"\b(?:" + "|".join(decl) + r")\b" if decl else r"(?!)",
             c["key"], QFont.Weight.DemiBold),
            (r"\b(?:" + "|".join(re.escape(w) for w in words if not w.startswith("-")
                                 and w not in decl)
             + r")\b", c["keyword"], QFont.Weight.Normal),
            # 字面量单独一档：One Dark Pro 里 true/false/null 是橙色，不跟关键字同色
            (r"\b(?:true|false|null|None|True|False|undefined|NaN|nil)\b",
             c["literal"], QFont.Weight.Normal),
            (r"\b(?:" + "|".join(builtins) + r")\b" if builtins else r"(?!)",
             c["builtin"], QFont.Weight.Normal),
            # 函数调用名 —— 蓝色
            (r"\b[A-Za-z_][A-Za-z0-9_]*(?=\s*\()", c["func"], QFont.Weight.Normal),
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
        self.setObjectName("Code")
        self._apply_colors()
        self.document().setDocumentMargin(doc_margin)
        self._hl = None
        if highlight:
            self._hl = JsonHighlighter(self.document())
        self._auto_pair = not read_only   # 只有可编辑视图才做补全
        self.blockCountChanged.connect(self._update_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_width()
        CodeView._views.add(self)

    # -------------------------------------------------- 输入法 / 占位提示
    def inputMethodEvent(self, e) -> None:  # noqa: N802
        """中文输入法组词时先藏掉占位提示。

        Qt 的 placeholder 只看「文档是否为空」，拼音还在预编辑区时文档仍是空的，
        于是提示文字会透过正在输入的拼音显示出来（用户截图里 `ni'hao` 和提示
        叠成一团）。组词结束或取消后恢复，不影响普通输入。
        """
        pre = e.preeditString()
        if pre and self.placeholderText():
            self._ime_placeholder = self.placeholderText()
            super().setPlaceholderText("")
        super().inputMethodEvent(e)
        if not pre and hasattr(self, "_ime_placeholder"):
            super().setPlaceholderText(self._ime_placeholder)
            del self._ime_placeholder

    # -------------------------------------------------- 输入补全 / 智能缩进
    _PAIRS = {"{": "}", "[": "]", "(": ")", '"': '"', "'": "'"}
    _CLOSE = {"}": "{", "]": "[", ")": "("}

    def set_auto_pair(self, on: bool) -> None:
        """开关括号/引号自动补全（只读视图恒为关）。"""
        self._auto_pair = bool(on) and not self.isReadOnly()

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        """写代码的手感：括号/引号成对、回车继承缩进、Tab 缩进、退格删整对。

        只在可编辑且开启补全时接管；其余按键原样交给 QPlainTextEdit，
        查找/撤销/输入法等原生行为完全不受影响。
        """
        if not self._auto_pair or self.isReadOnly():
            super().keyPressEvent(e)
            return
        key = e.text()
        cur = self.textCursor()
        pos = cur.position()
        doc = self.document()

        # 1) 输入闭合符：右边正好是这个闭合符时「跨过去」，不重复插入
        if key in self._CLOSE and cur.atBlockEnd() is False:
            nxt = doc.characterAt(pos)
            if nxt == key:
                cur.movePosition(QTextCursor.MoveOperation.Right)
                self.setTextCursor(cur)
                return

        # 2) 输入起始符：成对插入；有选中文本时用一对符号把它包起来
        if key in self._PAIRS:
            close = self._PAIRS[key]
            if cur.hasSelection():
                start, end = cur.selectionStart(), cur.selectionEnd()
                cur.insertText(key)
                cur.setPosition(end + 1)
                cur.insertText(close)
                cur.setPosition(start + 1)
                cur.setPosition(end + 1, QTextCursor.MoveMode.KeepAnchor)
                self.setTextCursor(cur)
                return
            # 引号：后面紧跟字母/数字时不补（避免写英文缩写被打断）
            if key in ('"', "'") and doc.characterAt(pos).isalnum():
                super().keyPressEvent(e)
                return
            cur.insertText(key + close)
            cur.setPosition(pos + 1)
            self.setTextCursor(cur)
            return

        # 3) 回车：继承上一行缩进；开括号后回车多缩进一级，并把闭合符留到下一行
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            block = cur.block()
            text = block.text()
            indent = re.match(r"[ \t]*", text).group(0)
            before = text[:cur.positionInBlock()]
            opens = sum(before.count(k) - before.count(v) for k, v in (("{", "}"), ("[", "]"), ("(", ")")))
            if opens > 0:
                indent += "    "
            nxt = doc.characterAt(pos)
            cur.beginEditBlock()
            if nxt in self._CLOSE and opens > 0:
                # 先把原来的闭合符吃掉，再写到新行 —— 否则会留下两个
                cur.setPosition(pos)
                cur.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                cur.insertText("\n" + indent + "\n" + indent[:-4] + nxt)
                cur.setPosition(pos + 1 + len(indent))
            else:
                cur.insertText("\n" + indent)
            cur.endEditBlock()
            self.setTextCursor(cur)
            return

        # 4) 退格：光标夹在空的一对符号中间时一次删掉两个
        if e.key() == Qt.Key.Key_Backspace and not cur.hasSelection():
            prev = doc.characterAt(pos - 1)
            nxt = doc.characterAt(pos)
            if prev in self._PAIRS and self._PAIRS[prev] == nxt:
                cur.setPosition(pos - 1)
                cur.setPosition(pos + 1, QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                self.setTextCursor(cur)
                return

        # 5) Tab：插入四个空格而不是跳焦点
        if e.key() == Qt.Key.Key_Tab and not cur.hasSelection():
            cur.insertText("    ")
            self.setTextCursor(cur)
            return

        super().keyPressEvent(e)

    def format_code(self) -> bool:
        """格式化当前文本：JSON 走 indent=2，XML 做简单换行缩进，其余不处理。

        返回是否真的改了内容 —— 调用方据此提示「已是最新格式」。
        """
        text = self.toPlainText()
        if not text.strip():
            return False
        out: Optional[str] = None
        if text.lstrip().startswith(("{", "[")):
            formatted, ok = pretty_json(text)
            if ok:
                out = formatted
        elif text.lstrip().startswith("<"):
            out = _format_xml(text)
        if out is None or out == text:
            return False
        cur = self.textCursor()
        anchor = cur.anchor()
        position = cur.position()
        self.setPlainText(out)
        cur = self.textCursor()
        cur.setPosition(min(anchor, len(out)))
        cur.setPosition(min(position, len(out)), QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cur)
        return True

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
            fmt.setForeground(QBrush(C(theme().code_text)))
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
        """切换代码语言。

        None → JSON 高亮；xml / html → 专门的 HTML 高亮器；其他语言 → 通用高亮器。
        之前 xml 会被 CodeHighlighter 静默降级成 python，HTML 因没有 Python
        关键字而几乎不着色（用户截图里整页灰白），现在走专用规则。
        """
        hl = getattr(self, "_hl", None)
        key = (language or "").lower()
        if key in ("xml", "html", "html5", "xhtml"):
            if not isinstance(hl, HtmlHighlighter):
                if hl is not None:
                    hl.setDocument(None)      # type: ignore[arg-type]
                self._hl = HtmlHighlighter(self.document())
            return
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
    def _apply_colors(self) -> None:
        """代码区底色 / 前景取主题里的 code_bg / code_text（One Dark Pro）。"""
        t = theme()
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: {t.code_bg}; color: {t.code_text}; border: none; }}")

    def refresh_theme(self) -> None:
        """切换主题后重新着色：语法高亮的颜色是写入文本格式的，必须重新高亮。"""
        self._apply_colors()
        hl = getattr(self, "_hl", None)
        if hl is not None:
            if isinstance(hl, (CodeHighlighter, HtmlHighlighter)):
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


# 树行高：默认 16px 会让 11.5pt 的等宽字挤在一起，值也容易和下一行贴住
ROW_H = 21
# 一个容器最多铺多少个子节点：再多就只显示前 N 条，避免大数组把界面卡死
MAX_TREE_CHILDREN = 300


class JsonTree(QTreeWidget):
    """JSON 树：键/值两列，按类型着色，默认展开两层。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(2)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setUniformRowHeights(True)
        # 键列按内容给宽度，剩下的都给值列：否则 two_factor 这种键会被截成 two_fa…
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setStretchLastSection(True)
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
        self._quiet_palette()

    def _quiet_palette(self) -> None:
        """把「选中高亮」调成全透明。

        系统样式会在左边缩进那一小块上刷一层高亮底 —— 行本身是透明的，于是
        只有那 14px 宽的地方冒出一块灰方块，看着像脏点。高亮透明后条目不铺底，
        方块消失，选中文字仍走高亮前景色（保持可读）。
        """
        t = theme()
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(0, 0, 0, 0))
        pal.setColor(QPalette.ColorRole.HighlightedText, C(t.text))
        self.setPalette(pal)

    def refresh_theme(self) -> None:
        self._quiet_palette()
        self.update()

    def set_data(self, obj: Any, expand_depth: int = 2) -> None:
        self.clear()
        self._data = obj
        t = theme()
        c = tokens()
        if isinstance(obj, dict):
            for k, v in obj.items():
                self._add(self.invisibleRootItem(), str(k), v, expand_depth, t)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self._add(self.invisibleRootItem(), str(i), v, expand_depth, t)
        else:
            self._add(self.invisibleRootItem(), "value", obj, expand_depth, t)

    def _add(self, parent, key: str, value: Any, depth: int, t) -> None:
        c = tokens()
        item = QTreeWidgetItem(parent)
        item.setSizeHint(0, QSize(120, ROW_H))
        item.setText(0, key)
        item.setFont(0, self._key_font)
        item.setForeground(0, C(t.text_dim))
        is_container = isinstance(value, (dict, list))
        if is_container:
            n = len(value)
            item.setText(1, f"{'{}' if isinstance(value, dict) else '[]'}  {n} {'keys' if isinstance(value, dict) else 'items'}")
            item.setForeground(1, C(t.text_faint))
            item.setFont(1, mono(10.5))
            pairs = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
            # 两万条数据一口气铺进树里会把界面卡住；只铺前 MAX_TREE_CHILDREN 条，
            # 末尾留一行「还有 N 项」，原文视图里照样能看全。
            for k, v in pairs[:MAX_TREE_CHILDREN]:
                self._add(item, str(k), v, depth - 1, t)
            if len(pairs) > MAX_TREE_CHILDREN:
                more = QTreeWidgetItem(item)
                more.setText(0, i18n.tr("… 还有 {n} 项").format(n=len(pairs) - MAX_TREE_CHILDREN))
                more.setForeground(0, C(t.text_faint))
                more.setFont(0, mono(10.5))
                more.setSizeHint(0, QSize(120, ROW_H))
            if depth > 0:
                item.setExpanded(True)
        else:
            if isinstance(value, str):
                item.setText(1, f'"{value}"')
                item.setForeground(1, C(c["string"]))
            elif isinstance(value, bool):
                item.setText(1, "true" if value else "false")
                item.setForeground(1, C(c["keyword"]))
            elif value is None:
                item.setText(1, "null")
                item.setForeground(1, C(t.text_faint))
            else:
                item.setText(1, str(value))
                item.setForeground(1, C(c["number"]))
            item.setFont(1, mono(11.5))

    def expand_all(self):
        self.expandAll()

    def collapse_all(self):
        self.collapseAll()


# ---------------------------------------------------------------- 工具函数

def _format_xml(text: str) -> Optional[str]:
    """轻量 XML 缩进：用Qt 的 DOM 读写，失败（格式不对）就返回 None 不动原文。"""
    try:
        from PyQt6.QtXml import QDomDocument

        doc = QDomDocument()
        if not doc.setContent(text):
            return None
        return doc.toString(2)
    except Exception:
        return None


def pretty_json(text: str) -> Tuple[str, bool]:
    """返回 (格式化文本, 是否成功)。超大文本直接原样返回以保流畅。"""
    if not text.strip():
        return text, False
    if len(text) > 4_000_000:
        return text, False
    try:
        data = json.loads(text)
    except Exception:
        # JSONC（带 // 注释）先剥掉行注释再试
        stripped = re.sub(r"^\s*//[^\n]*$", "", text, flags=re.MULTILINE)
        try:
            data = json.loads(stripped)
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
