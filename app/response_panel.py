"""响应面板：状态胶囊、耗时/体积、美化 / 树形 / 原始 / 响应头 / Cookies / 预览。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import i18n, icons
from .code_editor import CodeView, JsonTree, ctype_label, human_elapsed, human_size, pretty_json
from .http_client import Response
from .theme import C, font, mono, status_color, theme
from .widgets import (
    Button,
    Card,
    Divider,
    EmptyState,
    FadeStack,
    FindBar,
    HBox,
    Label,
    Menu,
    Pill,
    SegmentedTabs,
    Shimmer,
    Spinner,
    VBox,
    icon_button,
    ChoiceMenu,
)

BINARY_KINDS = ("image", "audio", "video", "pdf", "binary")

# 显示编码：用户可切换；auto 之外的项强制按该编码解释响应字节。
ENCODINGS = [
    ("utf8", "UTF-8"), ("gbk", "GBK"), ("gb2312", "GB2312"),
    ("gb18030", "GB18030"), ("iso-8859-1", "ISO-8859-1"),
    ("iso-8859-16", "ISO-8859-16"), ("ascii", "ASCII"),
    ("utf-16", "UTF-16"), ("utf-32", "UTF-32"),
    ("base64", "Base64"), ("binary", "Binary (hex)"),
]
FORMATS = [("auto", "Auto"), ("json", "JSON"), ("xml", "XML"),
           ("html", "HTML"), ("text", "Text")]


def decode_body(data: bytes, enc: str) -> str:
    """按指定编码把字节解成文本。base64 / binary 走特殊分支。"""
    if not data:
        return ""
    if enc == "base64":
        import base64
        return base64.b64encode(data).decode("ascii")
    if enc == "binary":
        return _hexdump(data)
    codec = {
        "utf8": "utf-8", "gbk": "gbk", "gb2312": "gb2312", "gb18030": "gb18030",
        "iso-8859-1": "iso-8859-1", "iso-8859-16": "iso-8859-16",
        "ascii": "ascii", "utf-16": "utf-16", "utf-32": "utf-32",
    }.get(enc, "utf-8")
    try:
        return data.decode(codec)
    except (UnicodeDecodeError, LookupError):
        # UTF-8 解不开时回退 GB18030（中文站点常见），仍失败才用替换字符
        if codec == "utf-8":
            try:
                return data.decode("gb18030")
            except Exception:  # noqa: BLE001
                pass
        return data.decode(codec, errors="replace")


def _hexdump(data: bytes, limit: int = 4096) -> str:
    rows = []
    for i in range(0, min(len(data), limit), 16):
        chunk = data[i:i + 16]
        h = " ".join(f"{b:02X}" for b in chunk)
        a = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{i:08X}  {h:<47}  {a}")
    if len(data) > limit:
        rows.append(i18n.trf("... 仅显示前 {n} 字节，共 {m} 字节", n=limit, m=len(data)))
    return "\n".join(rows) or i18n.tr("响应体为空")


class HeaderRows(QWidget):
    """响应头 / Cookie 的键值列表。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[Any] = []
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 8, 12, 12)
        self.lay.setSpacing(0)
        self.lay.addStretch(1)

    def clear(self) -> None:
        while self.lay.count() > 1:
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()

    def add(self, key: str, value: str, highlight: bool = False, meta: str = "") -> None:
        row = QWidget()
        row.setMinimumHeight(26)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(12)
        k = Label(key, 11.5, theme().text_dim, mono_font=True)
        k.setFixedWidth(198)
        k.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        v = Label(value, 11.5, theme().success if highlight else theme().text, mono_font=True)
        v.setWordWrap(True)
        v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(v)
        if meta:
            m = Label(meta, 10, theme().text_faint, mono_font=True)
            m.setWordWrap(True)
            box.addWidget(m)
        lay.addWidget(k, 0)
        lay.addLayout(box, 1)
        self.lay.insertWidget(self.lay.count() - 1, row)
        self._rows.append(row)


VIEW_LIMIT = 600_000      # 单个响应在代码区里最多渲染 600KB，超出部分截断并说明


# ---------------------------------------------------------------- 控制台
LEVEL_META = {
    "log": ("dot", "text_dim"),
    "info": ("dot", "info"),
    "debug": ("dot", "text_faint"),
    "warn": ("alert", "warning"),
    "error": ("alert", "danger"),
    "ok": ("check", "success"),
}


class StaleBar(QWidget):
    """「请求已修改」细提示条：不清屏，只在结果上方提醒这是上一次的响应。"""

    resend = pyqtSignal()
    dismissed = pyqtSignal()
    never = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(7)
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        self.text = Label("请求已修改 · 下面是上一次的响应", 10.8, theme().text_dim)
        self.never_btn = Button("不再提醒", None, kind="ghost", height=20,
                                padding=7, font_size=10.6)
        self.never_btn.setToolTip("以后不再显示这条提醒，仍可在设置里打开")
        self.never_btn.clicked.connect(self._on_never)
        self.resend_btn = Button("重新发送", None, kind="ghost", height=20,
                                 padding=8, font_size=10.8)
        self.resend_btn.setToolTip("用修改后的请求再发一次  ⌘↵")
        self.resend_btn.clicked.connect(self.resend.emit)
        self.close_btn = icon_button("close", i18n.tr("关闭提醒"), 20, 10)
        self.close_btn.clicked.connect(self._on_close)
        lay.addWidget(self.dot, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.text, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        lay.addWidget(self.never_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.resend_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.hide()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        self.dot.setPixmap(icons.pixmap("alert", theme().warning, 11, 1.5))

    def _on_close(self) -> None:
        self.hide()
        self.dismissed.emit()

    def _on_never(self) -> None:
        self.hide()
        self.never.emit()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bg = QColor(C(t.warning))
        bg.setAlpha(26)
        p.fillRect(self.rect(), bg)
        sep = QColor(C(t.warning))
        sep.setAlpha(70)
        p.setPen(QPen(sep, 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class ConsoleLog(QWidget):
    """控制台：脚本的 console.* / test() 输出，按级别配色并带阶段标签。

    和响应体分开渲染 —— 只有几行文本，用 Label 排而不是塞进代码编辑器，
    这样换行、选中复制、长文本折行都更自然，也不会被语法高亮染色。
    """

    MAX_ROWS = 200

    def __init__(self, parent=None, compact: bool = False):
        super().__init__(parent)
        self.entries: List[Dict[str, str]] = []
        self._rows: List[QWidget] = []
        # compact：嵌在错误页里时用。不要自己那套 14px 内缩（会和错误页的 24px
        # 叠成两层），按钮也压低一号，免得两颗小按钮抢了报错的注意力。
        self._compact = compact

        self.host = QWidget()
        self.lay = QVBoxLayout(self.host)
        self.lay.setContentsMargins(0 if compact else 14, 10 if compact else 12,
                                    0 if compact else 14, 12)
        self.lay.setSpacing(6)
        self.lay.addStretch(1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(self.host)

        # 空状态：没有输出时也别是一片空白
        self.empty = Label("脚本里用 console.log() 打印的内容会显示在这里",
                           11.5, theme().text_faint)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.tools = QWidget()
        tl = QHBoxLayout(self.tools)
        tl.setContentsMargins(*((0, 0, 0, 2) if compact else (14, 8, 14, 0)))
        tl.setSpacing(6 if compact else 8)
        self.summary = Label("", 10.5, theme().text_faint, mono_font=True)
        size = (20, 7, 10.8) if compact else (22, 8, 11)
        self.clear_btn = Button("清空", None, kind="ghost", height=size[0],
                                padding=size[1], font_size=size[2])
        self.clear_btn.clicked.connect(self.clear)
        self.copy_btn = Button("复制全部", "copy", kind="ghost", height=size[0],
                               padding=size[1], font_size=size[2])
        self.copy_btn.clicked.connect(self.copy_all)
        tl.addWidget(self.summary, 1)
        tl.addWidget(self.clear_btn)
        tl.addWidget(self.copy_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.tools)
        lay.addWidget(self.empty, 1)
        lay.addWidget(self.scroll, 1)
        self.scroll.hide()

    # -------------------------------------------------- 数据
    def set_entries(self, entries: List[Dict[str, str]]) -> None:
        self.entries = [dict(e) for e in (entries or [])][-self.MAX_ROWS:]
        self._rebuild()

    def clear(self) -> None:
        self.entries = []
        self._rebuild()

    def has_entries(self) -> bool:
        return bool(self.entries)

    def _rebuild(self) -> None:
        while self.lay.count() > 1:
            item = self.lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows = []
        t = theme()
        for entry in self.entries:
            level = str(entry.get("level") or "log")
            icon_name, token = LEVEL_META.get(level, ("dot", "text_dim"))
            color = getattr(t, token, t.text_dim)
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(0, 0, 0, 0)
            rl.setSpacing(8)
            badge = QLabel()
            badge.setFixedSize(14, 14)
            badge.setPixmap(icons.pixmap(icon_name, color, 12, 1.4))
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rl.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            phase = str(entry.get("phase") or "")
            if phase in ("pre", "post"):
                chip = Pill("前置" if phase == "pre" else "后置", t.text_faint, font_size=9.5)
                rl.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
            text = Label(str(entry.get("text") or ""), 11.5,
                         color if level in ("error", "warn", "ok") else t.text_dim,
                         mono_font=True)
            text.setWordWrap(True)
            text.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            rl.addWidget(text, 1)
            self.lay.insertWidget(self.lay.count() - 1, row)
            self._rows.append(row)

        n = len(self.entries)
        warns = sum(1 for e in self.entries if e.get("level") in ("warn", "error"))
        self.empty.setVisible(n == 0)
        self.scroll.setVisible(n > 0)
        self.summary.setText(
            i18n.trf("{n} 条输出", n=n) + (i18n.trf(" · {w} 条警告", w=warns) if warns else "")
            if n else "")
        self.clear_btn.setVisible(n > 0)
        self.copy_btn.setVisible(n > 0)

    def copy_all(self) -> None:
        if not self.entries:
            return
        QApplication.clipboard().setText(
            "\n".join(self._line(e) for e in self.entries))

    @staticmethod
    def _line(entry: Dict[str, str]) -> str:
        phase = str(entry.get("phase") or "")
        prefix = f"[{phase}] " if phase else ""
        return prefix + str(entry.get("text") or "")

    def refresh_theme(self) -> None:
        self.empty.setStyleSheet(f"color: {theme().text_faint}; background: transparent;")
        self._rebuild()


class ResponsePanel(QWidget):
    requestSaveBody = pyqtSignal(bytes, str)
    resendRequested = pyqtSignal()          # 提示条上的「重新发送」
    saveVariable = pyqtSignal(str, str)      # 名字, 值：把提取结果存进环境变量
    pickVariableRequested = pyqtSignal(str)  # 响应体：从 JSON 里挑字段存成变量
    docRequested = pyqtSignal()              # 打开接口文档窗口
    wsActionRequested = pyqtSignal(str)      # WS 更多菜单：connect / disconnect
    aiExplainRequested = pyqtSignal()        # 用 AI 解释当前失败/异常响应

    def __init__(self, parent=None):
        super().__init__(parent)
        self.response: Optional[Response] = None
        self._find_visible = False
        self._body_text = ""
        self._elapsed_value = 0
        self._prev: Optional[Dict[str, Any]] = None
        self._extracted: Any = None
        self._fmt = "auto"      # auto / json / xml / html / text
        self._enc = "utf8"      # 见 ENCODINGS
        self._detail = None

        # ---------- 头部
        self.pill = Pill("—", theme().text_faint, font_size=10.5, pad=10, dot=True)
        self.time_label = Label("", 11, theme().text_dim, mono_font=True)
        self.size_label = Label("", 11, theme().text_faint, mono_font=True)
        self.type_label = Label("", 11, theme().text_faint, mono_font=True)
        # 最终请求地址不再占头部一行（地址栏里本来就有）：它一长就把
        # 状态码/耗时挤成一团。改为挂在状态胶囊的悬浮提示上，信息不丢。
        self._resp_url = ""

        self.find_btn = icon_button("search", "在响应中查找  ⌘F", 26, 14)
        self.find_btn.clicked.connect(self.toggle_find)
        self.copy_btn = icon_button("copy", "复制响应体", 26, 14)
        self.copy_btn.clicked.connect(self.copy_body)
        self.save_btn = icon_button("download", "另存为…", 26, 14)
        self.save_btn.clicked.connect(self.save_body)
        self.more_btn = icon_button("more", "更多：生成接口文档 / 脱敏复制", 26, 14)
        self.more_btn.clicked.connect(self._show_more_menu)

        # 指标条：没响应时整条隐藏，避免出现空胶囊和孤零零的分隔点
        self.meta = QWidget()
        ml = QHBoxLayout(self.meta)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)
        self._meta_layout = ml
        ml.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        ml.addSpacing(2)
        ml.addWidget(self.time_label)
        self.dot1 = self._dot()
        self.dot2 = self._dot()
        ml.addWidget(self.dot1)
        ml.addWidget(self.size_label)
        ml.addWidget(self.dot2)
        ml.addWidget(self.type_label)
        self.dot3 = self._dot()
        self.node_label = Label("", 10.5, theme().text_faint, mono_font=True)
        ml.addWidget(self.dot3)
        ml.addWidget(self.node_label)

        head = QWidget()
        head.setFixedHeight(46)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 0, 12, 0)
        hl.setSpacing(8)
        hl.addWidget(self.meta, 0, Qt.AlignmentFlag.AlignVCenter)
        hl.addStretch(1)
        hl.addWidget(self.find_btn)
        hl.addWidget(self.copy_btn)
        hl.addWidget(self.save_btn)
        hl.addWidget(self.more_btn)
        self.head = head

        # ---------- 标签
        self.tabs = SegmentedTabs(
            [("pretty", "美化"), ("tree", "树形"), ("raw", "原始"),
             ("headers", "响应头"), ("cookies", "Cookies"), ("console", "控制台"),
             ("preview", "预览"),
             ("diff", "对比"), ("extract", "提取"), ("timeline", "时间线"),
             ("contract", "契约")],
            style="underline", height=30, pad_h=9, font_size=12, adaptive=True)
        self.tabs.changed.connect(self._on_tab)
        self.tabs.more_clicked.connect(self._on_tabs_more)
        self._tabs_menu: Optional[ChoiceMenu] = None
        self.tree_tools = HBox(1)
        self.expand_btn = Button("全部展开", None, kind="ghost", height=22, padding=7, font_size=11)
        self.collapse_btn = Button("全部折叠", None, kind="ghost", height=22, padding=7, font_size=11)
        self.expand_btn.clicked.connect(lambda: self.json_tree.expandAll())
        self.collapse_btn.clicked.connect(lambda: self.json_tree.collapseAll())
        self.tree_tools.layout().addWidget(self.expand_btn)
        self.tree_tools.layout().addWidget(self.collapse_btn)
        self.wrap_btn = Button("自动换行", None, kind="ghost", height=22, padding=7, font_size=11)
        self.wrap_btn.clicked.connect(self._toggle_wrap)
        self.tabs_row = QWidget()
        tl = QHBoxLayout(self.tabs_row)
        tl.setContentsMargins(6, 0, 12, 0)
        tl.setSpacing(0)
        # 标签行必须吃掉整行的剩余宽度：之前给了 0 伸缩 + 末尾 addStretch，
        # 自适应标签只能拿 sizeHint（160px），明明放得下也会立刻折叠成「…」。
        tl.addWidget(self.tabs, 1)
        # 格式 / 编码切换：与主题其他小按钮同一套自绘样式；只在「美化」页出现。
        # 去掉胶囊边框和填充，只留文字 + 箭头，和其余工具行保持同一套扁平语言。
        self.fmt_btn = Button("Auto", "chevron_down", kind="ghost", height=24,
                              padding=8, icon_size=11, gap=4, font_size=11.5,
                              tooltip="响应格式：Auto / JSON / XML / HTML / Text")
        self.enc_btn = Button("UTF-8", "chevron_down", kind="ghost", height=24,
                              padding=8, icon_size=11, gap=4, font_size=11.5,
                              tooltip="显示编码：UTF-8 / GBK / Base64 等")
        self.fmt_btn.clicked.connect(self._choose_format)
        self.enc_btn.clicked.connect(self._choose_encoding)
        self._fmt_menu: Optional[ChoiceMenu] = None
        self._enc_menu: Optional[ChoiceMenu] = None
        # 树形展开/折叠按钮：选中树节点时不应冒出来干扰，统一隐藏。
        self.tree_tools.setVisible(False)
        self.tree_tools.hide()
        self.fmt_btn.hide()
        self.enc_btn.hide()
        # 每个响应页都能就地唤起 AI：提示词按当前页签切换，不用钻「更多」菜单
        self.ai_tab_btn = icon_button("spark", i18n.tr("用 AI 分析当前页"), 26, 14)
        self.ai_tab_btn.clicked.connect(self.aiExplainRequested.emit)
        tl.addWidget(self.fmt_btn)
        tl.addWidget(self.enc_btn)
        tl.addWidget(self.wrap_btn)
        tl.addWidget(self.ai_tab_btn)

        # ---------- 页面
        self.pretty = CodeView(read_only=True, highlight=True, show_gutter=False)
        # 原始视图同样走统一高亮，切页时按内容自动识别 JSON / XML / 纯文本
        self.raw = CodeView(read_only=True, highlight=True, show_gutter=False, wrap=False)
        self.tree_host = QWidget()
        th = QVBoxLayout(self.tree_host)
        th.setContentsMargins(8, 4, 8, 8)
        self.json_tree = JsonTree()
        th.addWidget(self.json_tree)
        self.headers_host = HeaderRows()
        self.cookies_host = HeaderRows()
        self.console_host = ConsoleLog()
        self.preview_host = QWidget()
        self.preview_lay = QVBoxLayout(self.preview_host)
        self.preview_lay.setContentsMargins(16, 16, 16, 16)
        self.preview_lay.setSpacing(0)

        # ---------- 对比（与上一次同地址响应比较）
        self.diff_view = CodeView(read_only=True, highlight=True, show_gutter=True)
        self.diff_note = Label("", 10.5, theme().text_faint, mono_font=True)
        self.diff_base_btn = Button("设为基准", None, kind="ghost", height=22, padding=7, font_size=11)
        self.diff_base_btn.setToolTip("把当前响应保存为对比基准")
        self.diff_base_btn.clicked.connect(self._set_diff_base)
        diff_host = QWidget()
        dl = QVBoxLayout(diff_host)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        top = HBox(self.diff_note, 1, self.diff_base_btn, spacing=8, margins=(12, 6, 12, 6))
        dl.addWidget(top)
        dl.addWidget(Divider())
        dl.addWidget(self.diff_view, 1)

        # ---------- 提取（简易 JSON 路径）
        from PyQt6.QtWidgets import QLineEdit

        self.path_edit = QLineEdit()
        self.path_edit.setObjectName("Field")
        self.path_edit.setFont(mono(11.8))
        self.path_edit.setFixedHeight(28)
        i18n.placeholder(self.path_edit, "输入路径，例如 data.items[0].name  或  args.*")
        self.path_edit.textChanged.connect(lambda _t: self._run_extract())
        self.extract_status = Label("", 10.5, theme().text_faint, mono_font=True)
        self.extract_copy = Button("复制值", "copy", kind="ghost", height=24, padding=8, font_size=11.5)
        self.extract_copy.clicked.connect(self._copy_extract)
        self.extract_save = Button("存为变量", "plus", kind="subtle", height=24, padding=8, font_size=11.5)
        self.extract_save.setToolTip("把提取到的值写进当前环境变量，之后用 {{名字}} 引用")
        self.extract_save.clicked.connect(self._save_extract_var)
        self.extract_save.setEnabled(False)
        self.extract_view = CodeView(read_only=True, highlight=True, show_gutter=False)
        ext_host = QWidget()
        xl = QVBoxLayout(ext_host)
        xl.setContentsMargins(12, 8, 12, 8)
        xl.setSpacing(8)
        xl.addWidget(HBox(self.path_edit, 1, self.extract_copy, self.extract_save, spacing=8))
        xl.addWidget(self.extract_status)
        xl.addWidget(self.extract_view, 1)

        from .timeline import TimelineView

        self.timeline = TimelineView()
        from .contract_view import ContractView

        self.contract = ContractView()
        self.body_stack = FadeStack()
        self.body_stack.add("pretty", self._scrollable(self.pretty))
        self.body_stack.add("tree", self.tree_host)
        self.body_stack.add("raw", self._scrollable(self.raw))
        self.body_stack.add("headers", self._scrollable(self.headers_host))
        self.body_stack.add("cookies", self._scrollable(self.cookies_host))
        self.body_stack.add("console", self.console_host)
        self.body_stack.add("preview", self.preview_host)
        self.body_stack.add("diff", diff_host)
        self.body_stack.add("extract", ext_host)
        self.body_stack.add("timeline", self.timeline)
        self.body_stack.add("contract", self.contract)

        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.tabs_row)
        cl.addWidget(Divider())
        cl.addWidget(self.body_stack, 1)

        # ---------- 空 / 加载 / 错误
        self.empty = EmptyState("send", "准备就绪", "填写请求地址后发送，响应会显示在这里",
                                "⌘ ↵ 发送", brand_mark=True)
        self.loading = QWidget()
        ll = QVBoxLayout(self.loading)
        ll.setContentsMargins(24, 24, 24, 24)
        ll.setSpacing(10)
        self.spinner = Spinner(16)
        top = HBox(self.spinner, Label("正在等待响应…", 11.5, theme().text_dim), 1, spacing=8)
        ll.addWidget(top)
        self.shimmer = Shimmer()
        ll.addWidget(self.shimmer, 1)

        self.error = QWidget()
        el = QVBoxLayout(self.error)
        el.setContentsMargins(24, 24, 24, 24)
        el.setSpacing(6)
        self.error_title = Label("请求失败", 13, theme().danger, weight=font(13).weight())
        self.error_msg = Label("", 11.5, theme().text_dim)
        self.error_msg.setWordWrap(True)
        el.addWidget(self.error_title)
        el.addWidget(self.error_msg)
        # AI 解释：把「请求失败」从一句报错变成原因 + 修法
        self.ai_explain_btn = Button("用 AI 解释", "spark", kind="subtle", height=26,
                                     padding=11, font_size=11.5, icon_size=12)
        self.ai_explain_btn.clicked.connect(self.aiExplainRequested.emit)
        el.addWidget(HBox(self.ai_explain_btn, 1, spacing=8))
        # 请求失败时前置脚本的日志同样要看得到（不然报错只能靠猜）
        self.error_console = ConsoleLog(compact=True)
        self.error_console.hide()
        el.addWidget(self.error_console)
        el.addStretch(1)

        self.center = QStackedWidget()
        self.center.addWidget(self.empty)
        self.center.addWidget(self.loading)
        self.center.addWidget(self.error)
        self.center.addWidget(self.content)
        from .ws_panel import WsLogView
        from .sio_panel import SioLogView
        from .sse_panel import SseLogView

        self.ws_view = WsLogView()
        self.center.addWidget(self.ws_view)
        self.sio_view = SioLogView()
        self.center.addWidget(self.sio_view)
        self.sse_view = SseLogView()
        self.center.addWidget(self.sse_view)
        # SSE 控制条（握手结果 / 速率）并入头部第一行，不再单独占一条：
        # 把 strip 从视图里 take 出来塞进 meta。
        # 播放/暂停按钮则归到头部右侧那组工具按钮里（和「更多」挨着），
        # 不跟状态文字挤在一起。
        self.sse_view.layout().removeWidget(self.sse_view.strip)
        self.sse_view.strip_div.hide()
        self.sse_view.dot.hide()          # 顶部胶囊左侧的灯已经指示状态，别亮两颗
        _strip_lay = self.sse_view.strip.layout()
        _strip_lay.removeWidget(self.sse_view.pause_btn)
        hl.insertWidget(hl.indexOf(self.more_btn), self.sse_view.pause_btn)
        self._meta_layout.addWidget(self.sse_view.strip)
        self.sse_view.strip.hide()
        self.sse_view.pause_btn.hide()
        self._is_ws = False
        self._realtime_kind = "ws"
        self._stale_notice = True

        self.find_bar = FindBar()
        self.find_bar.hide()
        self.find_bar.search.connect(self._do_find)
        self.find_bar.textChanged.connect(lambda t: self._do_find(t, False, reset=True))
        self.find_bar.closed.connect(self._on_find_closed)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(head)
        # head 下的分隔线要跟着 head 一起隐藏：head 藏起来时这条线会跟
        # 分割手柄的线叠在一起，看着像多了一套横线。
        self.head_divider = Divider()
        lay.addWidget(self.head_divider)
        self.stale_bar = StaleBar()
        self.stale_bar.resend.connect(self.resendRequested.emit)
        lay.addWidget(self.stale_bar)
        lay.addWidget(self.center, 1)
        lay.addWidget(self.find_bar)

        self.tabs_row.hide()
        self._set_actions_enabled(False)

        from .response_detail import DetailController

        self._detail = DetailController(self)
        self._detail.bind(self.time_label, self._timing_card)
        self._detail.bind(self.size_label, self._size_card)

    def _set_head_visible(self, visible: bool) -> None:
        """指标条与其下的分隔线一起显隐，避免空态时多出一条孤零零的横线。"""
        self.head.setVisible(visible)
        div = getattr(self, "head_divider", None)
        if div is not None:
            div.setVisible(visible)

    def _dot(self) -> QLabel:
        lbl = Label("·", 12, theme().text_faint)
        lbl.setFixedWidth(6)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def _scrollable(self, inner: QWidget) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        inner.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        area.setWidget(inner)
        return area

    def set_history(self, entries: List[Dict[str, Any]]) -> None:
        """喂给时间线：同一地址最近若干次的 status / elapsed / ts。"""
        self.timeline.set_entries(entries)
        self.tabs.set_badge("timeline", len(entries))

    # -------------------------------------------------- 格式 / 编码切换
    def _choose_format(self) -> None:
        items = [(k, label, None, "默认" if k == "auto" else None) for k, label in FORMATS]
        if self._fmt_menu is None:
            self._fmt_menu = ChoiceMenu(items, self._fmt, self, width=178)
            self._fmt_menu.picked.connect(self._set_format)
        self._fmt_menu.set_current(self._fmt)
        self._fmt_menu.popup(self.fmt_btn.mapToGlobal(QPoint(0, self.fmt_btn.height())))

    def _choose_encoding(self) -> None:
        items = [(k, label, None, None) for k, label in ENCODINGS]
        if self._enc_menu is None:
            self._enc_menu = ChoiceMenu(items, self._enc, self, width=168)
            self._enc_menu.picked.connect(self._set_encoding)
        self._enc_menu.set_current(self._enc)
        self._enc_menu.popup(self.enc_btn.mapToGlobal(QPoint(0, self.enc_btn.height())))

    def _set_format(self, key: str) -> None:
        self._fmt = key
        self.fmt_btn.setText(dict(FORMATS).get(key, "Auto"))
        self.fmt_btn.set_checked(key != "auto")
        self._rerender_body()

    def _set_encoding(self, key: str) -> None:
        self._enc = key
        self.enc_btn.setText(dict(ENCODINGS).get(key, key))
        self.enc_btn.set_checked(key != "utf8")
        self._rerender_body()

    # -------------------------------------------------- 每个标签独立的视图状态
    def view_state(self) -> dict:
        """供主窗口把响应页状态存回标签，切回来时原样恢复。"""
        return {"fmt": self._fmt, "enc": self._enc,
                "tab": self.tabs.current() if self.response is not None else None}

    def restore_state(self, state: Optional[dict]) -> None:
        """恢复格式 / 编码 / 当前响应子页；只改按钮与页面，不重新解码。"""
        state = state or {}
        self._fmt = state.get("fmt", "auto")
        self._enc = state.get("enc", "utf8")
        self.fmt_btn.setText(dict(FORMATS).get(self._fmt, "Auto"))
        self.enc_btn.setText(dict(ENCODINGS).get(self._enc, self._enc))
        self.fmt_btn.set_checked(self._fmt != "auto")
        self.enc_btn.set_checked(self._enc != "utf8")
        key = state.get("tab")
        if key in {"pretty", "tree", "raw", "headers", "cookies", "console",
                   "preview", "diff", "extract", "timeline", "contract"}:
            self.tabs.set_current(key, emit=False)
            if key == "raw" and getattr(self, "_raw_pending", False):
                self._flush_raw()
            if key == "tree" and not getattr(self, "_tree_ready", True):
                self._flush_tree()
            self.body_stack.set_current(key)

    def _sync_view_tools(self) -> None:
        """格式 / 编码只在有文本响应的「美化」页出现。"""
        show = (self.center.currentWidget() is self.content
                and self.response is not None and not self.response.error
                and self.response.kind not in BINARY_KINDS
                and self.tabs.current() == "pretty")
        self.fmt_btn.setVisible(show)
        self.enc_btn.setVisible(show)

    def _decode_current(self) -> str:
        if self.response is None:
            return ""
        return decode_body(self.response.body, self._enc)

    def _rerender_body(self) -> None:
        """格式或编码变了：重算美化 / 原始 / 树 / 对比 / 提取，不重新发请求。"""
        resp = self.response
        if resp is None:
            return
        if resp.kind in BINARY_KINDS:
            return                      # 二进制以预览为准，避免塞回乱码
        body = self._decode_current()
        self._body_text = body
        # 格式选择只影响「美化」页怎么排版；树 / 提取只认真正能解析的 JSON。
        as_json = self._fmt == "json" or (self._fmt == "auto" and resp.is_json)
        as_markup = self._fmt in ("xml", "html") or (
            self._fmt == "auto" and not resp.is_json and body.lstrip().startswith("<"))
        if as_json:
            pretty, _json_ok = pretty_json(body)
        elif as_markup:
            pretty = self._format_markup(body)
        else:
            pretty = body
        self.pretty.setPlainText(pretty)
        self.raw.setPlainText(body)
        ok = False
        try:
            data = json.loads(body)
            ok = isinstance(data, (dict, list))
        except Exception:  # noqa: BLE001
            pass
        if ok:
            self.json_tree.set_data(data, expand_depth=2)
        self.tabs.set_badge("tree", 1 if ok else 0)
        self.tabs.set_badge("extract", 1 if ok else 0)
        self._render_diff(body)
        self._run_extract()
        self._prev = {"url": resp.url, "body": body, "status": resp.status,
                      "elapsed": resp.elapsed}

    def _wants(self, kind: str) -> bool:
        if self._fmt == kind:
            return True
        if self._fmt == "auto":
            return False
        return False

    # HTML / XML 美化的词法元素：void 元素不压栈、行内元素整行输出、
    # script/style/textarea 内容原样保留。漏写闭合标签时按栈容错，不会楼梯状漂移。
    _VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr", "path", "circle", "rect", "line",
        "polyline", "polygon", "ellipse", "use", "stop", "animate", "set", "keygen",
    }
    _INLINE_TAGS = {
        "title", "h1", "h2", "h3", "h4", "h5", "h6", "p", "a", "span", "li", "td",
        "th", "option", "button", "label", "strong", "em", "b", "i", "u", "code",
        "small", "legend", "caption", "dt", "dd", "figcaption", "summary", "q",
        "cite", "abbr", "sub", "sup", "mark", "time", "output", "font",
    }
    _RAW_TAGS = {"script", "style", "textarea"}
    _TAG_TOKEN = re.compile(
        r"(?P<comment><!--.*?-->)"
        r"|(?P<cdata><!\[CDATA\[.*?\]\]>)"
        r"|(?P<doctype><!DOCTYPE[^>]*>)"
        r"|(?P<pi><\?.*?\?>)"
        r"|(?P<close></\s*(?P<cname>[A-Za-z][\w:.\-]*)\s*>)"
        r"|(?P<open><\s*(?P<oname>[A-Za-z][\w:.\-]*)"
        r"(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(?P<self>/?)>)",
        re.S | re.I,
    )

    @classmethod
    def _format_markup(cls, text: str) -> str:
        """按标签栈重排 XML / HTML：每个块级标签独占一行，行内元素保持一行。

        旧实现逐行 strip 后按「是否以 < 开头」加减缩进，把 <meta>、<title>x</title>
        这类**不产生嵌套**的标签也当成开标签，缩进逐行越踩越深，美化页变成楼梯状
        （用户截图 bug）。这里改用词法扫描 + 标签栈，void / 行内 / 原始文本分别处理。
        """
        if not text.lstrip().startswith("<"):
            return text
        out: List[str] = []
        stack: List[str] = []
        buf: List[str] = []            # 行内元素缓冲，配平后整行输出
        depth: List[str] = []          # 行内元素的嵌套栈
        raw: Optional[str] = None      # script/style/textarea 内容原样保留

        def emit(line: str) -> None:
            out.append("  " * len(stack) + line)

        def flush() -> None:
            if buf:
                out.append("  " * len(stack) + "".join(buf))
                buf.clear()
                depth.clear()

        pos = 0
        for m in cls._TAG_TOKEN.finditer(text):
            raw_pre = text[pos:m.start()]
            pos = m.end()
            pre = " ".join(raw_pre.split())
            if pre:
                if raw is not None:
                    emit(pre)
                elif buf:
                    # 行内文本：折叠空白但保留与标签相邻的单个空格，避免 hello<b> 粘一起
                    if raw_pre[:1].isspace() and not buf[-1][-1:].isspace():
                        buf.append(" ")
                    buf.append(pre)
                    if raw_pre[-1:].isspace():
                        buf.append(" ")
                else:
                    emit(pre)
            if m.group("comment") is not None or m.group("cdata") is not None \
                    or m.group("doctype") is not None or m.group("pi") is not None:
                if buf:
                    buf.append(m.group(0))
                else:
                    emit(m.group(0))
                continue
            if m.group("close") is not None:
                name = m.group("cname").lower()
                if raw is not None:
                    if name == raw:
                        stack.pop()
                        emit(m.group(0))
                        raw = None
                    else:
                        emit(m.group(0))
                    continue
                if depth and depth[-1] == name:
                    buf.append(m.group(0))
                    depth.pop()
                    if not depth:
                        flush()
                    continue
                flush()
                if name in stack:                      # 容错：弹到匹配的祖先
                    while stack and stack[-1] != name:
                        stack.pop()
                    if stack:
                        stack.pop()
                emit(m.group(0))
                continue
            # 开标签
            name = m.group("oname").lower()
            tag = m.group(0)
            if raw is not None:
                emit(tag)
                continue
            if name in cls._RAW_TAGS:
                flush()
                emit(tag)
                stack.append(name)
                raw = name
                continue
            if not m.group("self") and name in cls._INLINE_TAGS:
                if not buf:
                    buf.append(tag)
                    depth.append(name)
                else:
                    buf.append(tag)
                    depth.append(name)
                continue
            flush()
            emit(tag)
            if not m.group("self") and name not in cls._VOID_TAGS:
                stack.append(name)

        tail = " ".join(text[pos:].split())
        if tail:
            if raw is not None or not buf:
                emit(tail)
            else:
                buf.append(tail)
        flush()
        return "\n".join(out) or text

    # -------------------------------------------------- 悬浮详情卡
    @staticmethod
    def _ms(v) -> str:
        return f"{int(v)}ms" if v else "—"

    @staticmethod
    def _bytes(v) -> str:
        return human_size(int(v)) if v else "—"

    def _timing_card(self):
        from .response_detail import DetailCard

        resp = self.response
        # 请求失败时既没有真实耗时也没有响应体：任何「9 ms」都是假的，直接不给卡
        if resp is None or resp.error or self._is_ws:
            return None
        tm = resp.timing or {}
        total = resp.elapsed
        rows = [
            ("准备", self._ms(tm.get("prepare")), tm.get("prepare", 0) / max(total, 1)),
            ("Socket 初始化", self._ms(tm.get("dns")), tm.get("dns", 0) / max(total, 1)),
            ("DNS 查询", self._ms(tm.get("dns")), tm.get("dns", 0) / max(total, 1)),
            ("TCP 握手", self._ms(tm.get("tcp")), tm.get("tcp", 0) / max(total, 1)),
        ]
        if resp.url.startswith("https"):
            rows.append(("SSL 握手", self._ms(tm.get("ssl")), tm.get("ssl", 0) / max(total, 1)))
        rows += [
            ("等待中 (TTFB)", self._ms(tm.get("ttfb")), tm.get("ttfb", 0) / max(total, 1)),
            ("下载内容", self._ms(tm.get("download")), tm.get("download", 0) / max(total, 1)),
            ("处理", self._ms(tm.get("process")), 0.0),
        ]
        return DetailCard("响应时间", human_elapsed(total), rows, bars=True,
                          head_icon="clock",
                          note="准备 / DNS / TCP / SSL 为按 TTFB 比例估算")

    def _size_card(self):
        from .response_detail import DetailCard

        resp = self.response
        if resp is None or resp.error or self._is_ws:
            return None
        hs = resp.header_size or 0
        bs = max(0, resp.size - hs)
        total = max(1, resp.size)
        rows = [
            ("Header", self._bytes(hs), hs / total),
            ("Body", self._bytes(bs), bs / total),
        ]
        # 请求大小：用真正发出去的字节数，不再靠猜
        rh = getattr(resp, "request_header_size", 0) or 0
        rb = getattr(resp, "request_size", 0) or 0
        req_total = max(1, rh + rb)
        sections = []
        if rh or rb:
            sections.append((i18n.tr("Request Size"), human_size(rh + rb), [
                ("Header", self._bytes(rh), rh / req_total),
                ("Body", self._bytes(rb), rb / req_total),
            ]))
        return DetailCard("响应大小", human_size(resp.size), rows, bars=False,
                          head_icon="layers", split=True,
                          note=i18n.tr("Header 含状态行 · Body 为正文"),
                          sections=sections)

    # -------------------------------------------------- WebSocket 会话
    WS_STATE_TEXT = {"idle": "未连接", "connecting": "连接中", "open": "已连接",
                     "closing": "断开中", "closed": "已断开"}

    def show_ws(self, session: Optional[dict], url: str = "", kind: str = "ws") -> None:
        """切到实时协议视图：顶部状态胶囊 + 帧日志，不参与 HTTP 的响应逻辑。"""
        self.stale_bar.hide()
        self.shimmer.stop()
        if getattr(self, "spinner", None) is not None:
            self.spinner.stop()
        self.response = None
        self._is_ws = True
        self._realtime_kind = kind if kind in ("sio", "sse") else "ws"
        view = (self.sse_view if self._realtime_kind == "sse"
                else self.sio_view if self._realtime_kind == "sio" else self.ws_view)
        self.center.setCurrentWidget(view)
        self.tabs_row.hide()
        self._set_head_visible(True)
        self.meta.show()
        self.sse_view.strip.setVisible(self._realtime_kind == "sse")
        self.sse_view.pause_btn.setVisible(self._realtime_kind == "sse")
        self._set_actions_enabled(False)
        self._set_resp_url(url or "")
        session = session or {}
        view.set_frames(session.get("log") or [])
        self.ws_set_state(session.get("state", "idle"),
                          {"bytes_in": sum(f.size for f in (session.get("log") or [])
                                           if getattr(f, "dir", "") == "in"),
                           "uptime": session.get("uptime", 0)})

    def ws_set_state(self, state: str, stats: Optional[dict] = None) -> None:
        if not self._is_ws:
            return
        self._ws_state = state
        t = theme()
        label = self.WS_STATE_TEXT.get(state, state)
        self.pill.set_text(label)
        self.pill.set_color({"open": t.success, "connecting": t.info,
                             "closing": t.warning, "closed": t.text_faint}.get(state, t.text_faint))
        stats = stats or {}
        up = float(stats.get("uptime") or 0)
        self.time_label.animate_number(
            up * 1000, lambda ms: human_elapsed(int(ms)) if ms >= 50 else "")
        self.size_label.animate_number(
            int(stats.get("bytes_in") or 0), lambda b: human_size(int(b)))
        self.type_label.setText({"sio": "Socket.IO", "sse": "SSE"}.get(
            self._realtime_kind, "WebSocket"))
        self._set_metrics_visible(bool(up >= 0.05))
        self._set_dots(True)
        self.dot3.hide()
        if self._realtime_kind == "sse":
            self.sse_view.set_state(state)
            if state == "open":
                self.sse_view.set_stream(
                    int(getattr(self, "_sse_status", 0) or 0),
                    getattr(self, "_sse_ctype", ""),
                    getattr(self, "_sse_headers", {}))

    # -------------------------------------------------- SSE 握手信息
    def sse_stream(self, status: int, ctype: str, headers: Optional[dict] = None) -> None:
        """把 SSE 的 HTTP 状态码 / Content-Type / 响应头交给 SSE 视图。

        这几个字段是 SSE 唯一能看出「为什么没有事件」的证据：401 是没带上
        token，200 但 Content-Type 是 text/html 多半是被登录页或代理拦截了。
        """
        self._sse_status = int(status or 0)
        self._sse_ctype = ctype or ""
        self._sse_headers = dict(headers or {})
        self.sse_view.set_stream(self._sse_status, self._sse_ctype, self._sse_headers)
        self.sse_view.set_state(getattr(self, "_ws_state", "idle") or "idle")

    def sse_retry(self, attempt: int, delay_ms: int) -> None:
        self.sse_view.set_retry(attempt, delay_ms)
        self.sse_view.set_state("connecting")

    def _active_realtime_view(self):
        if self._realtime_kind == "sse":
            return self.sse_view
        return self.sio_view if self._realtime_kind == "sio" else self.ws_view

    def ws_add_frame(self, frame) -> None:
        view = self._active_realtime_view()
        if self.center.currentWidget() is view:
            view.add_frame(frame)

    def ws_clear(self) -> None:
        self._active_realtime_view().clear()

    def is_ws_view(self) -> bool:
        return self._is_ws

    # -------------------------------------------------- 状态
    def _set_actions_enabled(self, on: bool) -> None:
        for b in (self.find_btn, self.copy_btn, self.save_btn):
            b.setEnabled(on)
            b.setVisible(on)
        self.fmt_btn.setEnabled(on)
        self.enc_btn.setEnabled(on)
        if not on:
            self.fmt_btn.hide()
            self.enc_btn.hide()

    def _fit_head(self) -> None:
        """按头部实际宽度取舍指标，窄面板下绝不把文字叠在一起。

        状态码胶囊与耗时是必看项；「大小 / 类型」是可选项，空间不够就先收起来
        （「更多」菜单里仍能拿到完整信息），而不是让 QHBoxLayout 把标签挤重叠。

        这里用各控件自己的 sizeHint 逐项累加来算，不能读 meta.sizeHint() ——
        刚 setVisible 的那一刻布局缓存还没刷新，会少算掉整组宽度。
        """
        if not self.head.isVisible():
            return
        has = self.response is not None
        # 四个图标按钮始终按「会出现」来占位：它们和响应一起显示/隐藏
        buttons = sum(b.sizeHint().width() + 8 for b in
                      (self.find_btn, self.copy_btn, self.save_btn, self.more_btn))
        avail = (self.width() or self.head.width()) - buttons - 34
        # 胶囊宽度取实际钉死的宽度：刚 set_text 过 sizeHint 可能还是旧值
        # 耗时在 set_response 里是后写入的，这里按「一定放得下」的宽度预留，
        # 不能读当下可能还是空字符串的 sizeHint。
        time_w = max(self.time_label.sizeHint().width(), 78)
        base = max(self.pill.width(), self.pill.sizeHint().width()) + 22 + time_w
        need_size = self.size_label.sizeHint().width() + 26
        need_type = self.type_label.sizeHint().width() + 26

        self.size_label.setVisible(has)
        self.type_label.setVisible(has)
        self.dot1.setVisible(has)
        self.dot2.setVisible(has)
        if has and base + need_size + need_type > avail:
            self.type_label.hide()
            self.dot2.hide()
        if has and base + need_size > avail:
            self.size_label.hide()
            self.dot1.hide()
        self.dot3.setVisible(self.type_label.isVisible() and bool(self.node_label.text()))

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._fit_head()

    def _set_resp_url(self, url: str) -> None:
        """记住最终请求地址（重定向 / Mock 后用得上），只做状态胶囊的悬浮提示。"""
        self._resp_url = url or ""
        self.pill.setToolTip(self._resp_url)

    def _set_dots(self, on: bool) -> None:
        self.dot1.setVisible(on)
        self.dot2.setVisible(on)
        self.dot3.setVisible(on and bool(self.node_label.text()))

    def _set_metrics_visible(self, on: bool) -> None:
        """失败时连「响应时间 / 大小 / 类型」一起收起来。

        以前只在失败时把文字清空，标签还占着位置：鼠标悬停会弹出「9 ms」的
        详情卡，看着像请求成功过一样（用户截图反馈）。既然失败没有响应体和
        耗时可看，就整组藏掉，只留状态胶囊说明原因。
        """
        for w in (self.time_label, self.size_label, self.type_label):
            w.setVisible(on)
        self.dot1.setVisible(on)
        self.dot2.setVisible(on and bool(self.type_label.text()))


    def set_node(self, node: dict) -> None:
        """在指标条上标出这次请求走的是哪个节点（本地直连不显示，免得噪音）。"""
        name = (node or {}).get("name", "")
        local = (node or {}).get("kind") == "local"
        self.node_label.setText("" if local else i18n.trf("节点 {name}", name=name))
        self.dot3.setVisible(self.meta.isVisible() and bool(self.node_label.text()))

    def show_empty(self) -> None:
        self.stale_bar.hide()
        self.response = None
        self._is_ws = False
        self._body_text = ""
        self.console_host.clear()
        self.error_console.clear()
        self.error_console.hide()
        self.tabs.set_badge("console", 0)
        if getattr(self, "spinner", None) is not None:
            self.spinner.stop()
        self.empty.set_text("准备就绪", "填写请求地址后发送，响应会显示在这里", "⌘ ↵ 发送")
        self.center.setCurrentWidget(self.empty)
        self.tabs_row.hide()
        self.meta.hide()
        self._set_head_visible(False)
        self.time_label.setText("")
        self.size_label.setText("")
        self.type_label.setText("")
        self._set_resp_url("")
        self._set_metrics_visible(False)
        self.dot3.hide()
        self._set_actions_enabled(False)
        self.find_bar.hide()

    def mark_stale(self) -> None:
        """请求已改动：保留上一次的响应（很多人只是改个方式想对照结果），
        在顶部挂一条提示说明「这是上一次的结果」，不清空、不误导。"""
        if getattr(self, "spinner", None) is not None:
            self.spinner.stop()
        self.shimmer.stop()
        if self.response is None and self.center.currentWidget() is not self.content:
            self.center.setCurrentWidget(self.empty)
            self.empty.set_text("请求已修改", "发送后这里会显示本次请求的新响应", "⌘ ↵ 发送")
            self.tabs_row.hide()
            self.meta.hide()
            self._set_head_visible(False)
            self._set_actions_enabled(False)
            self._sync_view_tools()
            self.find_bar.hide()
            return
        if getattr(self, "_stale_notice", True):
            self.stale_bar.show()
        self._set_actions_enabled(True)

    def set_stale_notice(self, on: bool) -> None:
        self._stale_notice = bool(on)
        if not on:
            self.stale_bar.hide()

    def show_loading(self) -> None:
        self.stale_bar.hide()
        self.center.setCurrentWidget(self.loading)
        self.tabs_row.hide()
        self.spinner.start()          # 关键：不启动定时器就只是一个静止的弧线
        self.shimmer.start()
        self._set_head_visible(True)
        self.meta.show()
        self.pill.set_text("请求中")
        self.pill.set_color(theme().info)
        self.time_label.setText("")
        self.size_label.setText("")
        self.type_label.setText("")
        self._set_resp_url("")
        self._set_metrics_visible(False)
        self._set_dots(False)
        self._set_actions_enabled(False)

    def show_error(self, message: str) -> None:
        self.stale_bar.hide()
        self.shimmer.stop()
        if getattr(self, 'spinner', None) is not None:
            self.spinner.stop()
        self.center.setCurrentWidget(self.error)
        self.tabs_row.hide()
        self.error_msg.setText(message)
        self._set_head_visible(True)
        self.meta.show()
        self.pill.set_text("失败")
        self.pill.set_color(theme().danger)
        self.time_label.setText("")
        self.size_label.setText("")
        self.type_label.setText("")
        self._set_resp_url("")
        self._set_metrics_visible(False)
        self._set_dots(False)
        self._set_actions_enabled(False)
        detail = getattr(self, "_detail", None)
        if detail is not None:
            detail.hide()

    # -------------------------------------------------- AI 分析上下文
    TAB_LABELS = {
        "pretty": "美化", "tree": "树形", "raw": "原始", "headers": "响应头",
        "cookies": "Cookies", "console": "控制台", "preview": "预览",
        "diff": "对比", "extract": "提取", "timeline": "时间线", "error": "请求失败",
    }

    def ai_context(self, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """把「当前页 + 请求 + 响应」打包给 AI：不同页签喂不同证据。"""
        resp = self.response
        failed = resp is None or bool(resp.error) or self.center.currentWidget() is self.error
        tab = "error" if failed else (self.tabs.current() or "pretty")
        ctx: Dict[str, Any] = {
            "tab": tab,
            "tab_label": self.TAB_LABELS.get(tab, tab),
            "status": 0 if failed else int(resp.status or 0),
            "reason": "" if failed else (resp.reason or ""),
            "elapsed_ms": 0 if failed else int(resp.elapsed or 0),
            "size": 0 if failed else int(resp.size or 0),
            "content_type": "" if failed else (resp.content_type or ""),
            "request": request or {},
            "body": "" if failed else (self._body_text or ""),
        }
        if failed:
            ctx["error"] = self.error_msg.text() or (resp.error if resp else "")
        else:
            ctx["headers"] = [f"{k}: {v}" for k, v in (resp.headers or [])]
            ctx["cookies"] = list(resp.cookies or [])
            ctx["console"] = list(self.console_host.entries)
            if tab == "diff":
                ctx["diff"] = self.diff_view.toPlainText()
            elif tab == "extract":
                ctx["extract"] = {
                    "path": self.path_edit.text().strip(),
                    "value": self._extracted,
                    "status": self.extract_status.text(),
                }
            elif tab == "timeline":
                ctx["timeline"] = list(self.timeline.entries)
            elif tab == "preview":
                ctx["preview"] = f"内容类型：{resp.content_type or '未知'}；体积：{resp.size} B"
        return ctx

    def set_response(self, resp: Response) -> None:
        self.stale_bar.hide()
        self.shimmer.stop()
        if getattr(self, 'spinner', None) is not None:
            self.spinner.stop()
        self.response = resp
        self._is_ws = False
        if resp.error:
            self.show_error(resp.error)
            return
        self.center.setCurrentWidget(self.content)
        self.tabs_row.show()
        # content 里可能挂着原生视频视图（QVideoWidget）；给它套
        # QGraphicsOpacityEffect 会在 macOS 上触发 Qt 渲染层 SIGBUS。
        # 图片/文本用淡入，音视频响应直接跳过特效保证稳定。
        if resp.kind not in ("audio", "video"):
            from .widgets import fade_in as _fade

            _fade(self.content, 170)
        self._set_actions_enabled(True)
        self._set_head_visible(True)
        self.meta.show()
        self.sse_view.strip.hide()
        self.sse_view.pause_btn.hide()
        self._set_metrics_visible(True)
        self._set_dots(True)

        code = resp.status
        self.pill.set_text(f"{code} {resp.reason}".strip())
        self.pill.set_color(status_color(code))
        self.size_label.setText(human_size(resp.size))
        self.type_label.setText(ctype_label(resp.content_type))
        self._set_resp_url(resp.url or "")
        self._fit_head()
        QTimer.singleShot(0, self._fit_head)

        body = self._decode_current()
        self._body_text = body
        try:
            from . import contract as _contract

            self.contract.set_data(
                _contract.key_for(str(getattr(resp, "request_method", "") or ""), resp.url),
                resp.body, resp.content_type, resp.timing or {}, {
                    "status": getattr(resp, "status", 0),
                    "elapsed": getattr(resp, "elapsed", 0),
                    "size": getattr(resp, "size", 0),
                    "header_size": getattr(resp, "header_size", 0),
                    "request_size": getattr(resp, "request_size", 0),
                    "request_header_size": getattr(resp, "request_header_size", 0),
                    "content_type": resp.content_type,
                })
        except Exception:       # noqa: BLE001
            pass
        if resp.kind in BINARY_KINDS:
            # 二进制直接 utf-8 解码会变成一排问号，别再往代码区里塞了
            self.pretty.setPlainText(
                i18n.trf("这是二进制内容（{type} · {size}）。\n"
                         "请切换到「预览」查看；「原始」页里是十六进制内容。",
                         type=ctype_label(resp.content_type), size=human_size(resp.size)))
            self.raw.setPlainText(_hexdump(resp.body))
            ok = False
        else:
            as_json = self._fmt == "json" or (self._fmt == "auto" and resp.is_json)
            as_markup = self._fmt in ("xml", "html") or (
                self._fmt == "auto" and not resp.is_json and body.lstrip().startswith("<"))
            truncated = len(body) > VIEW_LIMIT
            if truncated:
                # 超大响应：直接截断，避免一次 setPlainText 就卡住一两秒
                note = i18n.trf("\n\n⋯（共 {total}，此处只预览前 {shown}；"
                                "完整内容请用「另存为」或「复制」）",
                                total=human_size(len(body)), shown=human_size(VIEW_LIMIT))
                pretty_text = body[:VIEW_LIMIT] + note
            elif as_json:
                pretty_text, _ok = pretty_json(body)
            elif as_markup:
                pretty_text = self._format_markup(body)
            else:
                pretty_text = body
            # 大响应（200KB 起）重新上色比读内容还慢 —— 必须在 setPlainText
            # 之前关掉，否则会先按高亮渲染一遍，白等 1 秒。
            self.pretty.set_highlight(len(pretty_text) <= 180_000)
            self.pretty.setPlainText(pretty_text)
            # 美化页按内容类型切高亮语言：JSON 用 JSON 规则，XML/HTML 用通用规则。
            # 大文档高亮已关，此时不要再 set_language（会触发全文档重新着色）。
            if len(pretty_text) <= 180_000:
                self.pretty.set_language("xml" if as_markup else None)
            # 「原始」页按需填充：绝大多数人只看美化页，没必要每次都解析两遍
            if truncated:
                self._raw_text = body[:VIEW_LIMIT] + i18n.trf(
                    "\n\n⋯（共 {total}，仅显示前 {shown}）",
                    total=human_size(len(body)), shown=human_size(VIEW_LIMIT))
            else:
                self._raw_text = body
            self._raw_pending = True
            if self.body_stack.current() == "raw":
                self._flush_raw()
            ok = False

        # JSON 树：只认真正解析成功的内容，格式切换不会制造假节点。
        if resp.kind not in BINARY_KINDS:
            try:
                data = json.loads(body)
                ok = isinstance(data, (dict, list))
            except Exception:
                pass
        self.tabs.set_badge("tree", 0)
        # 建树很贵（几十万节点要几百毫秒），等用户真的点「树形」再建
        self._tree_data = data if ok else None
        self._tree_skip = len(body) > VIEW_LIMIT
        self._tree_ready = False
        if ok and self.body_stack.current() == "tree":
            self._flush_tree()

        # 响应头
        self.headers_host.clear()
        for k, v in resp.headers:
            self.headers_host.add(k, v, highlight=k.lower() in ("content-type", "content-length", "server"))
        if not resp.headers:
            self.headers_host.add("—", "无响应头")
        self.tabs.set_badge("headers", len(resp.headers))

        # Cookies
        self.cookies_host.clear()
        for c in resp.cookies:
            flags = " · ".join(filter(None, [
                "Secure" if c.get("secure") else "",
                "HttpOnly" if c.get("http_only") else "",
                i18n.trf("过期 {when}", when=c.get("expires")) if c.get("expires") else "",
                f"domain={c.get('domain')}" if c.get("domain") else "",
                f"path={c.get('path')}" if c.get("path") else "",
            ]))
            self.cookies_host.add(c.get("name", ""), c.get("value", ""), True, meta=flags)
        if not resp.cookies:
            self.cookies_host.add("—", i18n.tr("本次响应未设置 Cookie"))
        self.tabs.set_badge("cookies", len(resp.cookies))

        # 预览
        self._build_preview(resp)
        self.tabs.set_badge("preview", 1 if resp.kind in ("image", "audio", "video") else 0)

        # 对比 + 提取
        self._render_diff(body)
        self._run_extract()
        self.tabs.set_badge("extract", 1 if ok else 0)
        self._prev = {"url": resp.url, "body": body, "status": resp.status,
                      "elapsed": resp.elapsed}

        # 耗时数字滚动
        self._animate_meta(resp.elapsed)

        # 默认页
        default = "pretty"
        if resp.kind in BINARY_KINDS:
            default = "preview"
        elif not body.strip():
            default = "headers"
        self.tabs.set_current(default, emit=False)
        self.body_stack.set_current(default)
        self.wrap_btn.setVisible(default == "raw")
        self._sync_view_tools()

    # -------------------------------------------------- 对比
    # -------------------------------------------------- 控制台
    def set_console(self, entries: Optional[List[Dict[str, str]]]) -> None:
        """喂入本次请求的脚本控制台输出（前置 + 后置）。

        有输出时「控制台」页带条数徽标；请求失败时错误页里也内联一份，
        这样前置脚本的报错不会因为「没有响应」而看不到。
        """
        items = list(entries or [])
        self.console_host.set_entries(items)
        n = len(items)
        self.tabs.set_badge("console", n)
        if self.center.currentWidget() is self.error:
            self.error_console.set_entries(items)
            self.error_console.setVisible(bool(items))
        else:
            self.error_console.clear()
            self.error_console.hide()

    def _set_diff_base(self) -> None:
        if self.response is None:
            return
        self._prev = {"url": self.response.url, "body": self._body_text,
                      "status": self.response.status, "elapsed": self.response.elapsed}
        self.diff_note.setText("已把当前响应设为基准，下次发送后即可对比")
        self.tabs.set_badge("diff", 1)

    def _render_diff(self, body: str) -> None:
        import difflib

        from PyQt6.QtGui import QTextCharFormat, QTextCursor

        t = theme()
        view = self.diff_view
        view.setPlainText("")
        prev = self._prev
        cur_url = self.response.url if self.response else ""
        if not prev or prev.get("url") != cur_url:
            self.tabs.set_badge("diff", 0)
            self.diff_note.setText("还没有可对比的上一次响应 · 同地址请求一次后再看这里")
            cur = QTextCursor(view.document())
            fmt = QTextCharFormat()
            fmt.setForeground(C(t.text_faint))
            cur.insertText(i18n.tr("（同一地址的第二次响应会自动与上一次逐行对比）"), fmt)
            return

        prev_lines = (prev.get("body") or "").splitlines()
        cur_lines = (body or "").splitlines()
        diff = list(difflib.unified_diff(prev_lines, cur_lines,
                                         fromfile=i18n.tr("上一次"), tofile=i18n.tr("本次"),
                                         lineterm="", n=2))
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        self.tabs.set_badge("diff", 1 if diff else 0)
        self.diff_note.setText(i18n.trf(
            "较上一次：+{added} 行 / -{removed} 行 · 状态 {was} → {now} · 耗时 {t0}ms → {t1}ms",
            added=added, removed=removed, was=prev.get("status"),
            now=self.response.status if self.response else 0,
            t0=prev.get("elapsed"),
            t1=self.response.elapsed if self.response else 0))
        cur = QTextCursor(view.document())
        cur.beginEditBlock()
        for line in diff:
            fmt = QTextCharFormat()
            if line.startswith("+") and not line.startswith("+++"):
                fmt.setForeground(C(t.success))
            elif line.startswith("-") and not line.startswith("---"):
                fmt.setForeground(C(t.danger))
            elif line.startswith("@@"):
                fmt.setForeground(C(t.info))
            elif line.startswith(("+++", "---")):
                fmt.setForeground(C(t.text_faint))
                fmt.setFontWeight(600)
            else:
                fmt.setForeground(C(t.text_dim))
            cur.insertText(line + "\n", fmt)
        cur.endEditBlock()

    # -------------------------------------------------- 提取
    @staticmethod
    def _json_path_get(data: Any, path: str) -> Any:
        """支持 a.b[0].c 与 a.* 的简易路径取值。"""
        token = ""
        parts: List[Any] = []
        i = 0
        while i < len(path):
            ch = path[i]
            if ch == ".":
                if token:
                    parts.append(token)
                    token = ""
            elif ch == "[":
                if token:
                    parts.append(token)
                    token = ""
                j = path.find("]", i)
                if j < 0:
                    raise ValueError("缺少 ]")
                inner = path[i + 1:j].strip().strip("'\"")
                parts.append(int(inner) if inner.lstrip("-").isdigit() else inner)
                i = j
            else:
                token += ch
            i += 1
        if token:
            parts.append(token)

        cur = data
        for p in parts:
            if p == "*":
                if isinstance(cur, dict):
                    return cur
                if isinstance(cur, list):
                    return cur
                raise KeyError("* 只能用于对象或数组")
            if isinstance(p, int):
                cur = cur[p]
            elif isinstance(cur, dict):
                cur = cur[p]
            else:
                cur = cur[int(p)] if str(p).lstrip("-").isdigit() else cur[p]
        return cur

    def _run_extract(self) -> None:
        t = theme()
        if self.response is None:
            return
        if not self.response.is_json:
            self.extract_status.setText("当前响应不是 JSON，无法用路径提取")
            self.extract_status.setStyleSheet(f"color: {t.text_faint}; background: transparent;")
            self.extract_view.setPlainText("")
            self._extracted = None
            self.extract_save.setEnabled(False)
            return
        try:
            data = json.loads(self._body_text)
        except Exception:
            self.extract_status.setText("响应体不是合法 JSON")
            self.extract_status.setStyleSheet(f"color: {t.danger}; background: transparent;")
            return
        path = self.path_edit.text().strip()
        if not path:
            if isinstance(data, dict):
                keys = "、".join(list(data.keys())[:8])
                self.extract_status.setText(i18n.trf("可用的顶层字段：{keys}", keys=keys))
            else:
                self.extract_status.setText(i18n.tr("响应是数组，试试 [0] 或 [0].字段名"))
            self.extract_status.setStyleSheet(f"color: {t.text_faint}; background: transparent;")
            self.extract_view.setPlainText("")
            self._extracted = None
            self.extract_save.setEnabled(False)
            return
        try:
            value = self._json_path_get(data, path)
        except Exception as exc:  # noqa: BLE001
            self.extract_status.setText(i18n.trf("路径无效：{kind} · {msg}",
                                             kind=exc.__class__.__name__, msg=exc))
            self.extract_status.setStyleSheet(f"color: {t.danger}; background: transparent;")
            self.extract_view.setPlainText("")
            self._extracted = None
            self.extract_save.setEnabled(False)
            return
        self._extracted = value
        self.extract_save.setEnabled(True)
        kind = type(value).__name__
        self.extract_status.setText(i18n.trf("命中 {kind} · 路径 {path}", kind=kind, path=path))
        self.extract_status.setStyleSheet(f"color: {t.success}; background: transparent;")
        if isinstance(value, (dict, list)):
            self.extract_view.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            self.extract_view.setPlainText(json.dumps(value, ensure_ascii=False)
                                           if not isinstance(value, str) else value)

    def _save_extract_var(self) -> None:
        """把提取结果写进当前环境变量（Postman / Bruno 里最常用的一步）。"""
        if self._extracted is None:
            return
        from .dialogs import PromptDialog

        path = self.path_edit.text().strip()
        guess = ""
        if path:
            tail = path.rstrip("]").split(".")[-1].split("[")[0]
            guess = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in tail)
        value = self._extracted
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        dlg = PromptDialog("存为环境变量", "变量名（用 {{名字}} 引用）", guess or "", self)
        if dlg.exec():
            name = dlg.value().strip()
            if name:
                self.saveVariable.emit(name, value)

    def _copy_extract(self) -> None:
        if self._extracted is None:
            return
        value = self._extracted
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        QApplication.clipboard().setText(text)
        self.requestSaveBody.emit(b"", "copied")

    def _animate_meta(self, elapsed: int) -> None:
        self._elapsed_value = 0
        anim = QVariantAnimation(self)
        anim.setStartValue(0)
        anim.setEndValue(max(elapsed, 1))
        anim.setDuration(420)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: self.time_label.setText(human_elapsed(int(v))))
        anim.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _build_preview(self, resp: Response) -> None:
        from .media_preview import build_preview

        build_preview(resp, self.preview_host, self.preview_lay)

    # -------------------------------------------------- 标签切换
    def _flush_raw(self) -> None:
        self._raw_pending = False
        text = getattr(self, "_raw_text", "")
        self.raw.setPlainText(text)
        self.raw.set_highlight(len(text) <= 180_000)
        if len(text) <= 180_000:
            # 按首个非空字符识别 JSON / XML，让原始页也用统一高亮
            stripped = text.lstrip()
            self.raw.set_language("xml" if stripped.startswith("<") else None)

    def _flush_tree(self) -> None:
        data = getattr(self, "_tree_data", None)
        self._tree_ready = True
        self.json_tree.clear()
        if getattr(self, "_tree_skip", False):
            # 几十万个节点建一遍要几百毫秒，得不偿失：给个说明，让人用「提取」定向取值
            from PyQt6.QtWidgets import QTreeWidgetItem

            item = QTreeWidgetItem(self.json_tree)
            item.setText(0, "内容过大，已跳过树形视图")
            item.setText(1, "用「提取」按路径取值更快")
            item.setForeground(0, C(theme().text_faint))
            item.setForeground(1, C(theme().text_faint))
            return
        if data is not None:
            self.json_tree.set_data(data, expand_depth=2)

    def _on_tab(self, key: str) -> None:
        if self.tabs.current() != key:
            self.tabs.set_current(key, emit=False)
        if key == "raw" and getattr(self, "_raw_pending", False):
            self._flush_raw()
        if key == "tree" and not getattr(self, "_tree_ready", True):
            self._flush_tree()
        self.body_stack.set_current(key)
        self.wrap_btn.setVisible(key == "raw")
        self._sync_view_tools()
        if key not in ("pretty", "raw"):
            self.find_bar.hide()
            self._find_visible = False

    def _on_tabs_more(self, global_pos) -> None:
        """标签被折叠时，「更多」按钮弹出完整列表（含徽标计数）。"""
        items = []
        for key, label, badge in self.tabs.hidden_items():
            shown = i18n.tr(label) + (f"  {badge}" if badge else "")
            items.append((key, shown, None, None))
        if not items:
            return
        if self._tabs_menu is None:
            self._tabs_menu = ChoiceMenu(items, self.tabs.current(), self, width=176)
            self._tabs_menu.picked.connect(self._on_tab)
        else:
            self._tabs_menu._items = [list(it) for it in items]
            self._tabs_menu._src_items = [tuple(it) for it in items]
            self._tabs_menu.set_current(self.tabs.current())
        self._tabs_menu.popup(global_pos if isinstance(global_pos, QPoint)
                              else QPoint(int(global_pos.x()), int(global_pos.y())))

    def _toggle_wrap(self) -> None:
        from PyQt6.QtWidgets import QPlainTextEdit

        mode = self.raw.lineWrapMode()
        self.raw.setLineWrapMode(
            QPlainTextEdit.LineWrapMode.NoWrap
            if mode == QPlainTextEdit.LineWrapMode.WidgetWidth
            else QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.wrap_btn.setText("自动换行" if mode == QPlainTextEdit.LineWrapMode.WidgetWidth else "关闭换行")

    # -------------------------------------------------- 查找
    def toggle_find(self) -> None:
        if self.response is None:
            return
        if self._find_visible:
            self.find_bar.hide()
            self._find_visible = False
            return
        self._find_visible = True
        self.find_bar.show()
        self.find_bar.focus()

    def _on_find_closed(self) -> None:
        self._find_visible = False

    def _do_find(self, text: str, backwards: bool = False, reset: bool = False) -> None:
        if not self._find_visible:
            return
        view = self.pretty if self.body_stack.current() == "pretty" else self.raw
        if reset or view._matches == []:
            cur, total = view.find_text(text, backwards)
        else:
            cur, total = view.find_next(text, backwards)
        self.find_bar.set_count(cur, total)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._find_visible:
            self.find_bar.hide()
            self._find_visible = False
            return
        super().keyPressEvent(e)

    # -------------------------------------------------- 实时会话更多菜单
    def _show_ws_menu(self) -> None:
        """WS / Socket.IO 会话的「…」菜单：连接操作、日志处理、地址与统计复制。

        文案按当前实时协议区分——Socket.IO 视图不再误显示「复制 WebSocket 地址 /
        导出消息日志」，而是对应的 Socket.IO / 事件日志，避免让用户以为串了页面。
        """
        t = theme()
        sio = getattr(self, "_realtime_kind", "ws") == "sio"
        menu = Menu(self)
        connected = getattr(self, "_ws_state", "idle") in ("open", "connecting")
        a_toggle = menu.addAction(
            icons.icon("stop" if connected else "link", t.text, 13),
            i18n.tr("断开连接") if connected else i18n.tr("建立连接"))
        menu.addSeparator()
        a_copy_url = menu.addAction(
            icons.icon("link", t.text, 13),
            i18n.tr("复制 Socket.IO 地址") if sio else i18n.tr("复制 WebSocket 地址"))
        a_copy_stats = menu.addAction(i18n.tr("复制会话统计"))
        a_export = menu.addAction(
            icons.icon("download", t.text, 13),
            i18n.tr("导出事件日志…") if sio else i18n.tr("导出消息日志…"))
        a_clear = menu.addAction(
            icons.icon("trash", t.text, 13),
            i18n.tr("清空事件日志") if sio else i18n.tr("清空消息日志"))
        pos = self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height() + 4))
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is a_toggle:
            self.wsActionRequested.emit("disconnect" if connected else "connect")
        elif chosen is a_copy_url:
            url = self._resp_url
            if url:
                QApplication.clipboard().setText(url)
                self.requestSaveBody.emit(b"", "copied")
        elif chosen is a_copy_stats:
            QApplication.clipboard().setText(self.stats.text())
            self.requestSaveBody.emit(b"", "copied")
        elif chosen is a_export:
            self._active_realtime_view()._export()
        elif chosen is a_clear:
            self._active_realtime_view().clear()

    # -------------------------------------------------- 更多（分享 / 脱敏）
    def _show_more_menu(self) -> None:
        """把「生成文档 / 脱敏复制」收在一颗按钮里，头部不至于挤成一排图标。"""
        if self._is_ws:
            self._show_ws_menu()
            return
        if self.response is None:
            return
        t = theme()
        menu = Menu(self)
        a_doc = menu.addAction(icons.icon("file", t.text, 13), "查看接口文档…")
        menu.addSeparator()
        a_var = menu.addAction(icons.icon("layers", t.text, 13), "把响应字段存为变量…")
        a_ai = menu.addAction(icons.icon("spark", t.text, 13), i18n.tr("用 AI 分析这个响应"))
        a_body_safe = menu.addAction(icons.icon("lock", t.text, 13), "脱敏复制响应体")
        a_headers = menu.addAction("复制响应头")
        a_status = menu.addAction("复制状态行")
        pos = self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height() + 4))
        chosen = menu.exec(pos)
        if chosen is None:
            return
        if chosen is a_doc:
            self.docRequested.emit()
        elif chosen is a_var:
            self.pickVariableRequested.emit(self._body_text)
        elif chosen is a_ai:
            self.aiExplainRequested.emit()
        elif chosen is a_body_safe:
            self._copy_redacted_body()
        elif chosen is a_headers:
            self._copy_response_headers()
        elif chosen is a_status:
            self._copy_status_line()

    def _copy_redacted_body(self) -> None:
        from .share import redact_text

        if self.response is None:
            return
        QApplication.clipboard().setText(redact_text(self._body_text))
        self.requestSaveBody.emit(b"", "redacted")

    def _copy_response_headers(self) -> None:
        from .share import redact_headers

        if self.response is None:
            return
        lines = [f"{k}: {v}" for k, v in redact_headers(self.response.headers)]
        QApplication.clipboard().setText("\n".join(lines))
        self.requestSaveBody.emit(b"", "copied")

    def _copy_status_line(self) -> None:
        if self.response is None:
            return
        r = self.response
        QApplication.clipboard().setText(
            f"{r.status} {r.reason} · {human_elapsed(r.elapsed)} · {human_size(r.size)} · {r.url}")
        self.requestSaveBody.emit(b"", "copied")

    # -------------------------------------------------- 复制 / 保存
    def copy_body(self) -> None:
        if self.response is None:
            return
        QApplication.clipboard().setText(self._body_text)
        self.requestSaveBody.emit(self.response.body, "copied")

    def save_body(self) -> None:
        if self.response is None:
            return
        from urllib.parse import urlparse

        path = urlparse(self.response.url).path.strip("/").replace("/", "_") or "response"
        ext = ".json" if self.response.is_json else (".txt" if "text" in self.response.content_type else ".bin")
        target, _ = QFileDialog.getSaveFileName(self, "保存响应", path + ext, "所有文件 (*)")
        if not target:
            return
        try:
            with open(target, "wb") as fh:
                fh.write(self.response.body)
            self.requestSaveBody.emit(self.response.body, target)
        except Exception as exc:
            print(f"[Ocelot] 保存响应失败: {exc}")
