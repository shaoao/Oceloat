"""对话框与浮层：设置、环境变量、代码生成、重命名、更新内容、命令面板。"""
from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import (QEasingCurve, QPoint, QPointF, QRectF, QSize, Qt, QTimer,
                          QVariantAnimation, pyqtSignal)
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QStyledItemDelegate,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from PyQt6.QtWidgets import QFileDialog

from . import backdrop, i18n, icons, shortcuts as sc
from . import ai as ai_mod
from .brand import BrandMark
from .anim import stop as _anim_stop
from .code_editor import CodeView
from .markdown_view import AnalysisView
from .codegen import LANGUAGES
from .kv_editor import KVEditor
from .store import CHANGELOG, STATE_FILE, VERSION, Store, body_mode, uid
from .theme import ACCENTS, C, S, font, mono, px, theme
from .widgets import (
    Button,
    Card,
    Divider,
    FadeStack,
    SmoothScrollArea,
    HBox,
    KeyCap,
    Label,
    Menu,
    Pill,
    SegmentedTabs,
    Spinner,
    Switch,
    VBox,
    animate,
    fade_in,
    icon_button,
)


# ---------------------------------------------------------------- 基类


def _glass_everywhere() -> bool:
    """设置里「所有窗口模糊且固定」是否开启。"""
    from .store import Store

    store = Store.active()
    return bool(store is not None and store.settings.get("glass_all", False))


def _scale_key(value) -> str:
    """把存下来的缩放系数对回四个档位（老数据 / 手改的奇怪值也能落到最近的档）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "1.0"
    best = min(("1.0", "1.1", "1.25", "1.5"), key=lambda k: abs(float(k) - v))
    return best


class GlassDialog(QDialog):
    """无边框圆角对话框，与主窗口同一套视觉语言。

    默认：自动居中、可拖动、无背景模糊（普通小弹窗没必要挡视线）。
    需要「模糊 + 不可拖动」的对话框（设置、导入导出）把 BLUR_FIXED 设成 True；
    用户在设置里打开「所有窗口都模糊」后，所有对话框都会走这一套。
    """

    BLUR_FIXED = False

    def __init__(self, parent=None, width: int = 520, height: int = 320, title: str = ""):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self._radius = 13
        self.resize(width, height)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        self._drag_pos: Optional[QPoint] = None
        self._user_moved = False
        self._fixed_mode = False
        self._backdrop_on = False

        self.title = title
        self.header = QWidget()
        self.header.setFixedHeight(46)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(18, 0, 10, 0)
        hl.setSpacing(8)
        self._title_label = Label(title, 13, theme().text, weight=font(13).weight())
        hl.addWidget(self._title_label)
        hl.addStretch(1)
        self.close_btn = icon_button("close", "关闭  esc", 24, 12)
        self.close_btn.clicked.connect(self.reject)
        hl.addWidget(self.close_btn)
        self._root.addWidget(self.header)
        self._root.addWidget(Divider())

        self.body = QWidget()
        self._root.addWidget(self.body, 1)

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(C(t.border_strong), 1))
        p.setBrush(C(t.panel))
        p.drawRoundedRect(r, self._radius, self._radius)
        p.end()

    def mousePressEvent(self, e):
        # 默认窗口固定在父窗口正中（跟 macOS 系统弹窗一致）。只有「可拖动」的
        # 普通弹窗才允许按住标题栏拖走；设置 / 导入导出这类大窗永远不动。
        if (e.button() == Qt.MouseButton.LeftButton and not self._fixed_mode
                and self.header.geometry().contains(e.position().toPoint())):
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            self._user_moved = True
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        super().mouseReleaseEvent(e)

    def _place_center(self) -> None:
        """把窗口摆到父窗口（没有父窗口就摆到屏幕）的正中央。

        用 mapToGlobal(rect().center()) 而不是 frameGeometry：后者包含窗口边框
        与平台给的摆放偏移，在无边框透明窗口上算出来的中心会整体偏十几到上百像素。
        """
        parent = self.parentWidget()
        if parent is not None:
            win = parent.window()
            center = win.mapToGlobal(win.rect().center())
            screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        else:
            screen = QApplication.primaryScreen()
            center = screen.availableGeometry().center() if screen is not None else QPoint(0, 0)
        x = center.x() - self.width() // 2
        y = center.y() - self.height() // 2
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - self.width()))
            y = max(area.top(), min(y, area.bottom() - self.height()))
        self.move(x, y)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        # 页面切换时对话框高度会变，保持「还在正中间」
        if self.isVisible() and not self._user_moved:
            self._place_center()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        # 对话框多半是在语言切完以后才建的，这里补一次翻译，否则英文界面里会混着中文
        if i18n.current() == "en":
            i18n.apply_language(self)
            # 通用翻译只认整句词条；运行时拼接的文案要等它跑完再按模板重设，
            # 否则刚写好的英文会被 i18n_src_text 里的中文整句覆盖回去。
            fn = getattr(self, "refresh_i18n", None)
            if callable(fn):
                try:
                    fn()
                except Exception:             # noqa: BLE001
                    pass
            nav = getattr(self, "nav", None)
            if nav is not None:
                nav.sync_width()
                nav.update()
        # 模糊 + 固定：设置窗口、导入导出窗口，或用户打开了「所有窗口都模糊」
        self._fixed_mode = bool(self.BLUR_FIXED or _glass_everywhere())
        if not self._user_moved:
            self._place_center()
        if self._fixed_mode and not self._backdrop_on:
            self._backdrop_on = True
            backdrop.acquire(self)
        fade_in(self, 140)

    def _drop_backdrop(self) -> None:
        if self._backdrop_on:
            self._backdrop_on = False
            backdrop.release(self)

    def hideEvent(self, e):
        self._drop_backdrop()
        super().hideEvent(e)

    def done(self, result: int) -> None:
        self._drop_backdrop()
        super().done(result)


# ---------------------------------------------------------------- 输入框对话框


class PromptDialog(GlassDialog):
    def __init__(self, title: str, label: str, value: str = "", parent=None):
        super().__init__(parent, 420, 172, title)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 12, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(Label(label, 11.5, theme().text_faint))
        self.edit = QLineEdit(value)
        self.edit.setObjectName("Field")
        self.edit.setFixedHeight(31)
        self.edit.selectAll()
        lay.addWidget(self.edit)
        lay.addStretch(1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("确定", None, kind="primary", height=28, padding=16, font_size=12)
        ok.clicked.connect(self.accept)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        self.edit.returnPressed.connect(self.accept)

    def value(self) -> str:
        return self.edit.text()

    def showEvent(self, e):
        super().showEvent(e)
        self.edit.setFocus()


def json_paths(data: Any, prefix: str = "", depth: int = 0, out: Optional[List] = None,
               limit: int = 120) -> List[Dict[str, str]]:
    """把 JSON 摊成「路径 + 值」列表，给取变量用。

    只往下走 4 层、最多 120 条：响应可能是几万行的列表，
    全展开既慢又没法挑，够用就行。
    """
    out = [] if out is None else out
    if len(out) >= limit or depth > 4:
        return out
    if isinstance(data, dict):
        for key, value in data.items():
            if len(out) >= limit:
                break
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                json_paths(value, path, depth + 1, out, limit)
            else:
                out.append({"path": path, "value": _scalar_text(value)})
        return out
    if isinstance(data, list):
        if not data:
            return out
        if isinstance(data[0], (dict, list)):
            json_paths(data[0], f"{prefix}[0]" if prefix else "[0]", depth + 1, out, limit)
        else:
            out.append({"path": f"{prefix}[0]" if prefix else "[0]",
                        "value": _scalar_text(data[0])})
    return out


def _scalar_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class AiAnswerDialog(GlassDialog):
    """AI 响应分析弹窗：流式写入、分节排版、可复制 / 重新分析。

    只负责呈现：调用方拿 messages 起流，逐块喂 append_chunk()，结束后 set_result()；
    命中缓存时直接 set_result(..., cached=True) 秒开，不再起 AI 请求。
    """

    copyRequested = pyqtSignal()
    retryRequested = pyqtSignal()

    def __init__(self, title: str, subtitle: str = "", parent=None,
                 width: int = 800, height: int = 620):
        super().__init__(parent, width, height, i18n.tr(title))
        t = theme()
        self._buf = ""
        self._dirty = False
        self._done = False
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._flush)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 12, 18, 16)
        lay.setSpacing(10)

        # 状态条：分析对象 + 状态 + 转圈。状态文字固定不动，转圈交给 spinner，
        # 不再每收到一段就往文字后面加 / 减圆点（那会让整行字一直抖）。
        strip = Card(radius=9)
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(12, 9, 12, 9)
        sl.setSpacing(9)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("spark", t.text_dim, 13, 1.5))
        sub = Label(subtitle or "", 10.6, t.text_faint)
        sub.setWordWrap(True)
        self.spinner = Spinner(12, t.text_dim)
        self.spinner.hide()
        self.state = Label("", 10.6, t.text_faint, mono_font=True)
        self.state.setMinimumWidth(64)
        self.state.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sl.addWidget(icon)
        sl.addWidget(sub, 1)
        sl.addWidget(self.state, 0)
        sl.addWidget(self.spinner, 0)
        lay.addWidget(strip)

        # 正文：Markdown 原生控件渲染，标题 / 列表 / 引用都能成型
        paper = Card(radius=10)
        pl = QVBoxLayout(paper)
        pl.setContentsMargins(0, 0, 0, 0)
        self.view = AnalysisView()
        self.view.setStyleSheet(f"background: {t.panel};")
        pl.addWidget(self.view, 1)
        lay.addWidget(paper, 1)

        self.copy_btn = Button(i18n.tr("复制结果"), "copy", kind="subtle", height=28,
                               padding=12, font_size=11.6)
        self.retry_btn = Button(i18n.tr("重新分析"), "refresh", kind="ghost", height=28,
                                padding=12, font_size=11.6)
        close_btn = Button(i18n.tr("关闭"), None, kind="primary", height=28, padding=14,
                           font_size=11.6)
        self.copy_btn.clicked.connect(self.copyRequested.emit)
        self.retry_btn.clicked.connect(self.retryRequested.emit)
        close_btn.clicked.connect(self.accept)
        hint = Label("AI 生成 · 请结合原始响应核对", 9.8, t.text_faint)
        lay.addWidget(HBox(hint, 1, self.retry_btn, self.copy_btn, close_btn, spacing=7))
        self._state_text = ""

    def showEvent(self, e):
        super().showEvent(e)
        fade_in(self.body, 190)

    def reset(self) -> None:
        """重新分析：清掉上一轮内容与状态，不重建窗口。"""
        self._buf = ""
        self._dirty = False
        self._done = False
        self._timer.stop()
        self.view.clear()
        self.state.setText("")
        self.state.setToolTip("")
        self.state.setStyleSheet("")

    def set_busy(self, busy: bool, text: str = "") -> None:
        if busy:
            self.spinner.start()
            self._state_text = i18n.tr(text or "正在分析")
            # 状态文字写死一次，之后 render 只动 spinner —— 这是「正在分析一直抖」的根治点。
            self.state.setText(self._state_text)
            self.state.setToolTip("")
            self.state.setStyleSheet("")
        else:
            self.spinner.stop()
            self.state.setText(i18n.tr(text))

    def append_chunk(self, piece: str) -> None:
        self._buf += piece or ""
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start()

    def set_result(self, text: str, error: bool = False, cached: bool = False) -> None:
        """写入最终结果。cached=True 表示命中本地缓存，直接淡入呈现，不再跑 AI。"""
        self._buf = text or ""
        self._dirty = True
        self._done = True
        self._flush()
        self.spinner.stop()
        t = theme()
        if error:
            label, color = i18n.tr("分析失败"), t.danger
            self.state.setToolTip("")
        elif cached:
            label, color = i18n.tr("来自缓存"), t.text_faint
            minutes = max(1, ai_mod.AnalysisCache.TTL // 60)
            self.state.setToolTip(i18n.trf("缓存 {n} 分钟后自动过期；点「重新分析」可刷新",
                                           n=minutes))
        else:
            label, color = i18n.tr("分析完成"), t.success
            self.state.setToolTip("")
        self.state.setText(label)
        self.state.setStyleSheet(f"color: {color}; background: transparent;")
        if cached and self._buf:
            # 缓存秒开：正文只做一次很轻的柔化，不让它比「直接显示」慢半拍。
            fade_in(self.view, 160, start=0.55)

    def result(self) -> str:
        return self._buf.strip()

    def _flush(self) -> None:
        if not self._dirty:
            self._timer.stop()
            return
        self._dirty = False
        self.view.set_markdown(self._buf)
        bar = self.view.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())
        if self._done:
            self._timer.stop()

    def closeEvent(self, e):
        self._timer.stop()
        self.spinner.stop()
        super().closeEvent(e)


class VarPickDialog(GlassDialog):
    """从响应里挑一个字段存成变量：列表点一下、名字自动填、选全局还是环境。"""

    def __init__(self, store: Store, body: str, parent=None):
        super().__init__(parent, 560, 520, "存为变量")
        t = theme()
        self.store = store
        self._value = ""
        self._auto_name = ""
        self._rows: List[Dict[str, str]] = []
        try:
            data = json.loads(body or "")
        except Exception:  # noqa: BLE001
            data = None
        if data is not None:
            self._rows = json_paths(data)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(10)
        head = Label("选一个字段，起个名字，之后在请求里用 {{名字}} 引用。", 11.4, t.text_faint)
        head.setWordWrap(True)
        lay.addWidget(head)

        self.list = QListWidget()
        self.list.setFont(mono(11.5))
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {t.panel_alt}; border: 1px solid {S(t.border)};"
            f" border-radius: 9px; padding: 4px; }}"
            f"QListWidget::item {{ padding: 5px 6px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {t.selected}; color: {t.text}; }}")
        for row in self._rows:
            item = QListWidgetItem(f"{row['path']}  =  {row['value'][:46]}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            item.setToolTip(row["value"][:600])
            self.list.addItem(item)
        if not self._rows:
            item = QListWidgetItem("响应不是 JSON 对象，没有可提取的字段")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._on_pick)
        lay.addWidget(self.list, 1)

        self.name = QLineEdit()
        self.name.setObjectName("Field")
        self.name.setFixedHeight(29)
        self.name.setFont(mono(11.5))
        i18n.placeholder(self.name, "变量名，例如 token")
        self.name.textChanged.connect(self._sync_ok)
        lay.addWidget(self.name)

        self.scope = SegmentedTabs([("global", "全局变量"), ("env", "当前环境")],
                                   style="pill", height=26, font_size=11.4, pad_h=11)
        self.scope.set_current("global", emit=False)
        hint = Label("", 10.4, t.text_faint)
        hint.setWordWrap(True)
        env = store.active_environment()
        hint.setText(i18n.trf("全局：所有环境都能用。当前环境：{name}",
                              name=(env or {}).get("name") or i18n.tr("未选择")))
        lay.addWidget(HBox(self.scope, 1, spacing=8))
        lay.addWidget(hint)

        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        self.ok = Button("保存", "check", kind="primary", height=28, padding=16, font_size=12,
                         icon_size=12)
        self.ok.clicked.connect(self._accept)
        self.ok.setEnabled(False)
        lay.addWidget(HBox(1, cancel, self.ok, spacing=6))
        if self._rows:
            self.list.setCurrentRow(0)

    def _on_pick(self, item, _prev=None) -> None:
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole) or {}
        self._value = str(row.get("value", ""))
        path = str(row.get("path", ""))
        tail = path.rstrip("]").split(".")[-1].split("[")[0] if path else ""
        guess = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in tail)
        # 用户手动改过名字就别再抢：只有空着、或还是上一次自动填的值时才跟着换
        current = self.name.text().strip()
        if guess and (not current or current == self._auto_name):
            self.name.setText(guess)
            self._auto_name = guess
        self._sync_ok()

    def _sync_ok(self) -> None:
        self.ok.setEnabled(bool(self._value) and bool(self.name.text().strip()))

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name or not self._value:
            return
        self.store.set_var(name, self._value, "global" if self.scope.current() == "global"
                           else "env")
        self.accept()

    def result_name(self) -> str:
        return self.name.text().strip()

    def result_scope(self) -> str:
        return "global" if self.scope.current() == "global" else "env"


class ConfirmDialog(GlassDialog):
    """二次确认：删除集合 / 文件夹 / 请求 / 清空历史前都要过这一关。

    刻意做得很轻：一行标题、两行说明、右侧两颗按钮，回车=确认、esc=取消。
    """

    def __init__(self, title: str, message: str, confirm_text: str = "删除",
                 parent=None, danger: bool = True):
        super().__init__(parent, 420, 178, title)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(10)
        body = Label(message, 12, theme().text_dim)
        body.setWordWrap(True)
        lay.addWidget(body)
        lay.addStretch(1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button(confirm_text, "trash" if danger else None,
                    kind="danger" if danger else "primary", height=28, padding=14,
                    font_size=12)
        ok.clicked.connect(self.accept)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        self.ok_btn = ok
        self.cancel_btn = cancel

    @classmethod
    def ask(cls, parent, title: str, message: str, confirm_text: str = "删除") -> bool:
        """title / message / confirm_text 传最终文案（调用方自己 trf 好）。"""
        dlg = cls(title, message, confirm_text, parent)
        return bool(dlg.exec())

    def showEvent(self, e):
        super().showEvent(e)
        # 焦点默认给「取消」：手快按回车不会误删
        self.cancel_btn.setFocus()


class ScriptResultDialog(GlassDialog):
    """脚本运行结果弹窗：状态 + console 日志，一次看清，不占编辑器高度。"""

    def __init__(self, ok: bool, lines: Optional[List[str]] = None,
                 error: str = "", parent=None):
        super().__init__(parent, 560, 380, i18n.tr("运行结果"))
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 14, 18, 18)
        lay.setSpacing(10)

        status_text = i18n.tr("✓ 运行成功") if ok else "✕ " + (error or i18n.tr("运行失败"))[:200]
        head = Label(status_text, 12.5,
                     theme().success if ok else theme().danger,
                     weight=QFont.Weight.DemiBold)
        head.setWordWrap(True)
        lay.addWidget(head)
        lay.addWidget(Divider())

        self.log = CodeView(read_only=True, highlight=False, show_gutter=False, wrap=True)
        self.log.setObjectName("Field")
        self.log.setMinimumHeight(210)
        text = "\n".join(str(x) for x in (lines or []) if str(x).strip())
        self.log.setPlainText(text or i18n.tr("（脚本没有输出日志）"))
        lay.addWidget(self.log, 1)

        close = Button(i18n.tr("关闭"), None, kind="primary", height=28, padding=16, font_size=12)
        close.clicked.connect(self.accept)
        lay.addWidget(HBox(1, close, spacing=6))


# ---------------------------------------------------------------- 设置


class NavList(QWidget):
    """设置左侧竖向导航：图标 + 文字，圆角选中态，悬停淡入。"""

    changed = pyqtSignal(str)

    ROW_H = 33

    def __init__(self, items: List[tuple], parent=None):
        super().__init__(parent)
        self.items = items            # [(key, label, icon)]
        self.index = 0
        self._hover = -1
        self.row_h = px(self.ROW_H)    # 行高跟着界面字号走
        self.setFixedWidth(px(166))
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.width(), px(12) + len(self.items) * self.row_h)

    def sync_width(self) -> None:
        """按当前语言量一遍：英文条目（Environment Variables）比中文长，166px 放不下。"""
        fm = QFontMetricsF(font(12.5, QFont.Weight.Medium))
        longest = max((fm.horizontalAdvance(i18n.tr(label)) for _k, label, _i in self.items),
                      default=0)
        self.row_h = px(self.ROW_H)
        self.setFixedWidth(max(px(166), int(longest) + px(52)))
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def current_key(self) -> str:
        return self.items[self.index][0] if self.items else ""

    def set_key(self, key: str) -> None:
        for i, (k, _l, _i) in enumerate(self.items):
            if k == key:
                self.index = i
                self.update()
                return

    def _row_at(self, y: float) -> int:
        i = int((y - px(6)) // self.row_h)
        return i if 0 <= i < len(self.items) else -1

    def mouseMoveEvent(self, e):
        idx = self._row_at(e.position().y())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._row_at(e.position().y())
        if idx >= 0 and idx != self.index:
            self.index = idx
            self.update()
            self.changed.emit(self.current_key())

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(t.panel_alt))
        p.drawRoundedRect(QRectF(0, 0, self.width() - 6, self.height()), 10, 10)
        for i, (_key, label, icon_name) in enumerate(self.items):
            r = QRectF(5, px(6) + i * self.row_h, self.width() - 16, self.row_h - 2)
            selected = i == self.index
            hovered = i == self._hover
            if selected:
                p.setPen(QPen(C(t.border), 1))
                p.setBrush(C(t.elevated))
                p.drawRoundedRect(r, 7, 7)
            elif hovered:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.hover))
                p.drawRoundedRect(r, 7, 7)
            col = t.accent if selected else t.text_dim
            pm = icons.pixmap(icon_name, col, 14, 1.7)
            p.drawPixmap(QPointF(r.left() + 11, r.center().y() - 7), pm)
            p.setFont(font(12.5, QFont.Weight.Medium if selected else QFont.Weight.Normal))
            p.setPen(C(t.accent if selected else t.text_dim))
            p.drawText(QRectF(r.left() + 34, r.top(), r.width() - 40, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(label))
        p.end()


class SchemePicker(QWidget):
    """配色方案选择器：每套方案一个「迷你窗口」缩略块，选中有对号。"""

    picked = pyqtSignal(str)

    TILE_W = 116
    TILE_H = 60
    GAP = 10

    def __init__(self, current: str, parent=None):
        super().__init__(parent)
        from .theme import SCHEMES

        self.schemes = list(SCHEMES)
        self.current = "graphite" if current in ("dark", "") else current
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        cols = 3
        rows = (len(self.schemes) + cols - 1) // cols
        self.setMinimumHeight(rows * self.TILE_H + (rows - 1) * self.GAP)
        self.setMinimumWidth(cols * 96 + (cols - 1) * self.GAP)

    def resizeEvent(self, e):
        cols = 3
        self.TILE_W = max(96, int((self.width() - (cols - 1) * self.GAP) / cols))
        super().resizeEvent(e)

    def _rects(self):
        out = []
        cols = 3
        for i in range(len(self.schemes)):
            r, c = divmod(i, cols)
            out.append(QRectF(c * (self.TILE_W + self.GAP), r * (self.TILE_H + self.GAP),
                              self.TILE_W, self.TILE_H))
        return out

    def _at(self, pos):
        for i, r in enumerate(self._rects()):
            if r.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        idx = self._at(e.position())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._at(e.position())
        if idx >= 0:
            self.current = self.schemes[idx][0]
            self.update()
            self.picked.emit(self.current)

    def paintEvent(self, _e):
        from .theme import theme_by_name

        active = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        for i, (key, label) in enumerate(self.schemes):
            r = self._rects()[i]
            sch = theme_by_name(key)
            selected = key == self.current
            p.setPen(QPen(C(active.border_strong if (selected or i == self._hover)
                            else active.border), 2 if selected else 1))
            p.setBrush(C(sch.window))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
            # 迷你内容块
            card = QRectF(r.left() + 9, r.top() + 11, r.width() - 18, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(sch.card))
            p.drawRoundedRect(card, 5, 5)
            p.setBrush(C(sch.text))
            p.drawRoundedRect(QRectF(card.left() + 7, card.top() + 7, 30, 4), 2, 2)
            p.setBrush(C(sch.text_faint))
            p.drawRoundedRect(QRectF(card.left() + 42, card.top() + 7, 16, 4), 2, 2)
            p.setFont(font(11))
            p.setPen(C(sch.text if sch.is_dark else sch.text))
            p.drawText(QRectF(r.left() + 10, r.bottom() - 22, r.width() - 30, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(label))
            if selected:
                pm = icons.pixmap("check", sch.text, 12, 1.9)
                p.drawPixmap(QPointF(r.right() - 20, r.bottom() - 21), pm)
        p.end()


class AccentPicker(QWidget):
    """主题色选择器：一排色点，选中的外面套一圈，旁边显示名字。"""

    picked = pyqtSignal(str)

    DOT = 20
    GAP = 8
    RING = 4          # 选中时描边比色点多出多少（左右要留够，否则第一颗会被卡片边缘切掉）

    def __init__(self, current: str = "auto", parent=None):
        super().__init__(parent)
        from .theme import ACCENT_ORDER

        self.keys = list(ACCENT_ORDER)
        self.current = current if current in self.keys else "auto"
        self._hover = -1
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 上下各留出描边的余量，避免描边被垂直裁切
        self.setFixedHeight(self.DOT + (self.RING + 2) * 2)
        self.setMinimumWidth(int(self._x0() * 2 + (len(self.keys) - 1) * (self.DOT + self.GAP)
                                 + self.DOT))

    def _x0(self) -> float:
        # 第一颗色点的圆心位置：必须 ≥ 半径 + 描边，否则左边被切
        return self.DOT / 2 + self.RING + 2

    def _centers(self):
        y = self.height() / 2
        x0 = self._x0()
        return [QPointF(x0 + i * (self.DOT + self.GAP), y) for i in range(len(self.keys))]

    def _at(self, pos):
        for i, c in enumerate(self._centers()):
            if (pos.x() - c.x()) ** 2 + (pos.y() - c.y()) ** 2 <= (self.DOT / 2 + 5) ** 2:
                return i
        return -1

    def mouseMoveEvent(self, e):
        idx = self._at(e.position())
        if idx != self._hover:
            self._hover = idx
            self.setToolTip("")
            if idx >= 0:
                self.setToolTip(ACCENTS[self.keys[idx]][0])
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def mouseReleaseEvent(self, e):
        idx = self._at(e.position())
        if idx >= 0 and self.keys[idx] != self.current:
            self.current = self.keys[idx]
            self.update()
            self.picked.emit(self.current)

    def paintEvent(self, _e):
        from .theme import theme as _theme

        t = _theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for i, key in enumerate(self.keys):
            c = self._centers()[i]
            bg, fg = _accent_preview(key, t)
            selected = key == self.current
            # 选中：先画一圈底色描边，再画实心点；悬停给一点点亮
            if selected:
                ring = QColor(t.text)
                ring.setAlpha(90 if t.is_dark else 70)
                p.setPen(QPen(ring, 1.4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = self.DOT / 2 + 4
                p.drawEllipse(QRectF(c.x() - r, c.y() - r, r * 2, r * 2))
            p.setPen(Qt.PenStyle.NoPen)
            fill = QColor(bg)
            if i == self._hover and not selected:
                fill = fill.lighter(112) if t.is_dark else fill.darker(106)
            p.setBrush(fill)
            d = self.DOT
            p.drawEllipse(QRectF(c.x() - d / 2, c.y() - d / 2, d, d))
            if selected:
                pm = icons.pixmap("check", fg, 11, 2.0)
                p.drawPixmap(QPointF(c.x() - 5.5, c.y() - 5.5), pm)
        p.end()


def _accent_preview(key: str, t) -> tuple[str, str]:
    """设置面板里的色点取色：auto 用当前主题的反色，其余按主题明暗取。"""

    _label, d, lt = ACCENTS.get(key, ACCENTS["auto"])
    if key == "auto":
        return (t.text, t.window) if t.is_dark else (t.text, "#FFFFFF")
    return d if t.is_dark else lt


# ---------------------------------------------------------------- 快捷键录制


class ShortcutRecorder(GlassDialog):
    """录制一个组合键：按下什么就记什么，esc 放弃。"""

    def __init__(self, name: str, current: str = "", parent=None):
        super().__init__(parent, 430, 226, i18n.trf("录制快捷键 · {name}", name=name))
        t = theme()
        self.value = ""
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(24, 6, 24, 18)
        lay.setSpacing(12)

        self.cap = KeyCap(sc.display(current) if current else "按下组合键",
                          width=0, height=46)
        self.cap.setFont(font(15))
        lay.addWidget(HBox(1, self.cap, 1, spacing=0))

        self.hint = Label("直接按下新的组合键。支持 ⌘ / ⌃ / ⌥ / ⇧ 与字母、数字、"
                          "方向键、回车等。", 10.8, t.text_faint)
        self.hint.setWordWrap(True)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.hint)
        lay.addStretch(1)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        lay.addWidget(HBox(1, cancel, 1, spacing=6))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        seq = sc.from_event(e)
        if not seq:
            return
        self.value = seq
        self.cap.set_text(sc.display(seq), recording=True)
        self.accept()


class ShortcutRow(QWidget):
    """一行快捷键：名称 + 默认键位提示 + 键帽 + 清除。"""

    changed = pyqtSignal(str, str)      # (action, seq)

    def __init__(self, action: str, name: str, seq: str, shown: str, parent=None):
        super().__init__(parent)
        t = theme()
        self.action = action
        self._seq = seq
        self._name = name
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 9, 2, 9)
        h.setSpacing(10)

        default = sc.defaults().get(action, "")
        sub = (i18n.trf("默认 {keys}", keys=sc.display(default))
               if default != seq else i18n.tr("默认键位"))
        text = VBox(Label(name, 12.4, t.text), Label(sub, 10.4, t.text_faint), spacing=2)
        h.addWidget(text, 1)

        self.cap = KeyCap(shown, width=118, height=24)
        self.cap.clicked.connect(self._record)
        h.addWidget(self.cap, 0, Qt.AlignmentFlag.AlignVCenter)

        self.clear_btn = Button("清除", None, kind="ghost", height=24, padding=9,
                                font_size=11)
        self.clear_btn.clicked.connect(lambda: self.changed.emit(self.action, ""))
        self.clear_btn.setEnabled(bool(seq))
        h.addWidget(self.clear_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._record()
        super().mouseReleaseEvent(e)

    def _record(self) -> None:
        dlg = ShortcutRecorder(self._name, self._seq, self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.value:
            self.changed.emit(self.action, dlg.value)

    def set_key(self, seq: str) -> None:
        self._seq = seq
        self.cap.set_text(sc.display(seq))
        self.clear_btn.setEnabled(bool(seq))


class ModelCard(QWidget):
    """AI 模型卡片：名字 + 小徽标 + 一句说明，点一下即选中。

    自绘而不是一堆 Button，是为了选中态能同时体现「描边 + 淡底」，
    并且在两列网格里高度稳定（不会因为文字长短抖动）。
    """

    picked = pyqtSignal(str)
    HEIGHT = 62

    def __init__(self, model: Dict[str, Any], selected: bool = False, parent=None):
        super().__init__(parent)
        self.model = dict(model)
        self._selected = selected
        self._hover = False
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_selected(self, on: bool) -> None:
        if on != self._selected:
            self._selected = on
            self.update()

    def enterEvent(self, e):  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.model.get("id", ""))

    def paintEvent(self, _e):  # noqa: N802
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._selected:
            fill = QColor(C(t.accent))
            fill.setAlpha(18)
            p.setPen(QPen(C(t.accent), 1.2))
            p.setBrush(fill)
        else:
            p.setPen(QPen(C(t.border), 1))
            p.setBrush(C(t.hover if self._hover else t.panel_alt))
        p.drawRoundedRect(r, 10, 10)

        label = i18n.tr(self.model.get("label") or self.model.get("id") or "")
        badge = i18n.tr(self.model.get("badge") or "")
        p.setFont(font(12.8, QFont.Weight.DemiBold))
        p.setPen(C(t.text))
        fm = QFontMetricsF(p.font())
        p.drawText(QRectF(13, 10, r.width() - 26, 18),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        if badge:
            bw = QFontMetricsF(mono(9.2, QFont.Weight.Bold)).horizontalAdvance(badge) + 12
            bx = 13 + min(fm.horizontalAdvance(label), r.width() - 26) + 8
            if bx + bw < r.right() - 8:
                br = QRectF(bx, 12, bw, 15)
                p.setFont(mono(9.2, QFont.Weight.Bold))
                p.setPen(Qt.PenStyle.NoPen)
                chip = QColor(C(t.text_faint))
                chip.setAlpha(30)
                p.setBrush(chip)
                p.drawRoundedRect(br, 4.5, 4.5)
                p.setPen(C(t.text_dim))
                p.drawText(br, int(Qt.AlignmentFlag.AlignCenter), badge)
        p.setFont(font(10.6))
        p.setPen(C(t.text_faint))
        desc = QFontMetricsF(p.font()).elidedText(
            i18n.tr(self.model.get("desc") or ""), Qt.TextElideMode.ElideRight, r.width() - 26)
        p.drawText(QRectF(13, 32, r.width() - 26, 16),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), desc)
        p.end()


class SettingsDialog(GlassDialog):
    """统一的设置面板：通用 / 外观 / 快捷键 / 网络 / 环境变量 / 数据 / 更新内容 都在这一页。"""

    BLUR_FIXED = True       # 设置窗口永远模糊 + 固定居中

    themeChanged = pyqtSignal(str)
    accentChanged = pyqtSignal(str)
    settingsChanged = pyqtSignal()
    shortcutsChanged = pyqtSignal()
    dataReloaded = pyqtSignal()
    uiScaleChanged = pyqtSignal(float)

    NAV = [
        ("general", "通用", "sliders"),
        ("appearance", "外观", "moon"),
        ("shortcuts", "快捷键", "keyboard"),
        ("network", "网络", "globe"),
        ("ai", "AI", "spark"),
        ("cloud", "云同步", "cloud"),
        ("env", "变量", "layers"),
        ("data", "数据", "folder"),
        ("about_app", "关于 Ocelot", "book"),
    ]

    def __init__(self, store: Store, parent=None, page: str = "general"):
        super().__init__(parent, 940, 700, "设置")
        self.store = store
        s = store.settings
        # 旧入口传 "globals"：现在合并进「变量」页，别再开出一个不存在的页
        self._page = "env" if page == "globals" else page

        root = QHBoxLayout(self.body)
        root.setContentsMargins(16, 12, 18, 14)
        root.setSpacing(18)

        self.nav = NavList(self.NAV)
        self.nav.changed.connect(self._on_nav)
        root.addWidget(self.nav, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(10)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_general(s))
        self.stack.addWidget(self._page_appearance(s))
        self.stack.addWidget(self._page_shortcuts())
        self.stack.addWidget(self._page_network(s))
        self.stack.addWidget(self._page_ai(s))
        self.stack.addWidget(self._page_cloud(s))
        self.stack.addWidget(self._page_env())
        self.stack.addWidget(self._page_data())
        self.stack.addWidget(self._page_about_app())
        right.addWidget(self.stack, 1)

        done = Button("完成", None, kind="primary", height=28, padding=18, font_size=12)
        done.clicked.connect(self._done)
        foot = HBox(1, done, spacing=8)
        foot.layout().setContentsMargins(0, 0, 4, 0)
        right.addWidget(foot)
        root.addLayout(right, 1)

        keys = [k for k, _l, _i in self.NAV]
        # 显式映射，别靠 stack 下标：加页或调序时最容易造成「每页看起来都一样」
        self._page_widgets = {k: self.stack.widget(i) for i, k in enumerate(keys)}
        self.nav.set_key(page if page in keys else "general")
        self.stack.setCurrentWidget(self._page_widgets.get(self.nav.current_key())
                                    or self.stack.widget(0))
        self._apply_page_title()

    # -------------------------------------------------- 页面
    def _page_shell(self, title: str, desc: str, *blocks) -> QWidget:
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(2, 0, 10, 14)
        lay.setSpacing(16)
        # 标题与说明都要能换行：英文比中文长不少，不换行就会被裁掉半截
        head_title = Label(title, 17, theme().text, weight=QFont.Weight.DemiBold, spacing=0.2)
        head_desc = Label(desc, 11.6, theme().text_faint)
        head_desc.setWordWrap(True)
        head = VBox(head_title, head_desc, spacing=4)
        lay.addWidget(head)
        lay.addWidget(Divider())
        for b in blocks:
            if isinstance(b, QLabel):
                b.setWordWrap(True)
            lay.addWidget(b)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        return scroll

    def _card(self, *rows) -> QWidget:
        card = Card(radius=10)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 6, 12, 6)
        lay.setSpacing(0)
        for i, r in enumerate(rows):
            if i:
                lay.addWidget(Divider())
            lay.addWidget(r)
        return card

    def _page_general(self, s: Dict[str, Any]) -> QWidget:

        self.lang_seg = SegmentedTabs([("zh", "简体中文"), ("en", "English")],
                                      style="pill", height=26, font_size=11.5, pad_h=12)
        self.lang_seg.set_current(i18n.current(), emit=False)
        self.lang_seg.changed.connect(self._on_language)
        self.auto_name = Switch(s.get("auto_name", True))
        self.auto_name.toggled.connect(lambda _v: self._save())
        self.restore_session = Switch(bool(s.get("restore_session", True)))
        self.restore_session.toggled.connect(lambda _v: self._save())
        self.stale_notice = Switch(bool(s.get("stale_notice", True)))
        self.stale_notice.toggled.connect(lambda _v: self._save())
        block = self._card(
            self._row("语言", "界面显示语言，切换后立即生效。", self.lang_seg),
            self._row("自动命名请求", "按 URL 末段自动给请求命名，重命名后不再覆盖。", self.auto_name),
            self._row("记住窗口与分栏", "下次启动恢复打开的标签、侧栏与上下分栏比例。",
                      self.restore_session),
            self._row("请求已修改提醒", "改动请求后提示「下面是上一次的响应」，可随时关掉。",
                      self.stale_notice),
        )
        # 快捷键独立成页，这里只留一个入口 —— 键位表太长，塞在通用页里只会被挤扁
        jump = Button("去设置", "keyboard", kind="subtle", height=27, padding=11,
                      font_size=11.6, icon_size=12)
        jump.clicked.connect(self._goto_shortcuts)
        keys_card = self._card(
            self._row("快捷键", "发送、搜索、切换标签等键位都可以改，也能整组恢复默认。",
                      jump),
        )
        return self._page_shell("通用", "启动行为与编辑习惯。", block, keys_card)

    def _goto_shortcuts(self) -> None:
        self.nav.set_key("shortcuts")
        self._on_nav("shortcuts")

    def _section(self, title: str, *widgets) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lab = Label(title, 10, theme().text_faint, weight=QFont.Weight.DemiBold, spacing=0.8)
        lay.addWidget(lab)
        for x in widgets:
            lay.addWidget(x)
        return w

    def _page_appearance(self, s: Dict[str, Any]) -> QWidget:
        self.scheme_picker = SchemePicker(s.get("theme", "graphite"))
        self.scheme_picker.picked.connect(self._on_scheme)
        scheme_card = Card(radius=12)
        sl = QVBoxLayout(scheme_card)
        sl.setContentsMargins(16, 14, 16, 16)
        sl.setSpacing(10)
        sl.addWidget(self.scheme_picker)

        self.accent_picker = AccentPicker(s.get("accent", "auto"))
        self.accent_picker.picked.connect(self._on_accent)
        accent_card = self._card(
            self._row("主题色", "主按钮、开关、勾选框、选中态与强调文字一起换色；「自动」为黑白反色。",
                      self.accent_picker),
        )

        self.anim_switch = Switch(bool(s.get("animations", True)))
        self.anim_switch.toggled.connect(self._on_anim)
        self.glass_switch = Switch(bool(s.get("glass_all", False)))
        self.glass_switch.toggled.connect(self._on_glass)
        self.font_seg = SegmentedTabs([("10.5", "小"), ("11.8", "标准"), ("13", "大")],
                                      style="pill", height=26, font_size=11.5, pad_h=12)
        cur_size = str(s.get("code_font_size", 11.8))
        self.font_seg.set_current(cur_size if cur_size in ("10.5", "11.8", "13") else "11.8",
                                  emit=False)
        self.font_seg.changed.connect(self._on_font_size)
        # 界面文字大小：整页（含自绘控件、代码区）按比例缩放，选完立刻重建界面
        self.scale_seg = SegmentedTabs([("1.0", "100%"), ("1.1", "110%"),
                                        ("1.25", "125%"), ("1.5", "150%")],
                                       style="pill", height=26, font_size=11.5, pad_h=12)
        cur_scale = _scale_key(s.get("ui_scale", 1.0))
        self.scale_seg.set_current(cur_scale, emit=False)
        self.scale_seg.changed.connect(self._on_ui_scale)
        options = self._card(
            self._row("界面动效", "关闭后页面切换、悬停与响应到达不再播放动画。", self.anim_switch),
            self._row("所有弹窗都模糊", "开启后所有弹窗都是模糊的。", self.glass_switch),
            self._row("文字大小", "调整界面文字的整体大小，所有页面即时生效。", self.scale_seg),
            self._row("代码字号", "响应体、请求体与代码片段的等宽字体大小。", self.font_seg),
        )

        preview = Card(radius=12)
        pl = QVBoxLayout(preview)
        pl.setContentsMargins(16, 12, 16, 14)
        pl.setSpacing(10)
        pl.addWidget(Label("预览", 10, theme().text_faint, weight=QFont.Weight.DemiBold,
                           spacing=0.8))
        pl.addWidget(HBox(Button("发送", "send", kind="primary", height=28, padding=14, font_size=12),
                          Button("次按钮", None, kind="subtle", height=28, padding=14, font_size=12),
                          Button("文字按钮", None, kind="ghost", height=28, padding=10, font_size=12),
                          1, spacing=8))
        return self._page_shell(
            "外观", "配色、主题色、动效与字号，改动立即生效。",
            self._section("配色方案", scheme_card), accent_card, options, preview)

    # -------------------------------------------------- 快捷键
    def _page_shortcuts(self) -> QWidget:
        """所有快捷键集中一页：点键帽重录，右键/按钮清除，冲突会自动接管。"""
        t = theme()
        self._key_rows: List[Tuple[str, "ShortcutRow"]] = []

        tip = Card(radius=10)
        tl = QHBoxLayout(tip)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(10)
        ic = Label("", 12)
        ic.setFixedSize(15, 15)
        ic.setPixmap(icons.pixmap("keyboard", t.text_faint, 15, 1.6))
        tl.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        tip_text = Label("点键帽开始录制，按下新的组合键即可替换；按 esc 取消。"
                         "清除后该动作只在菜单里可用。同一个键位被两个动作占用时，"
                         "旧的那个会自动让位。", 11, t.text_faint)
        tip_text.setWordWrap(True)
        tl.addWidget(tip_text, 1)

        blocks: List[QWidget] = [tip]
        mapping = sc.mapping(self.store)
        for group, rows in sc.by_group(mapping):
            card = Card(radius=10)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 10, 12, 10)
            cl.setSpacing(0)
            cl.addWidget(Label(group, 9.6, t.text_faint,
                               weight=QFont.Weight.DemiBold, spacing=0.8))
            cl.addSpacing(2)
            for i, (action, name, seq) in enumerate(rows):
                if i:
                    cl.addWidget(Divider())
                row = ShortcutRow(action, name, seq, sc.display(seq), self)
                row.changed.connect(self._on_shortcut)
                self._key_rows.append((action, row))
                cl.addWidget(row)
            blocks.append(card)

        self.shortcut_note = Label("", 10.6, t.text_faint)
        reset = Button("恢复默认", "refresh", kind="ghost", height=26, padding=10,
                       font_size=11.4, icon_size=12)
        reset.clicked.connect(self._reset_shortcuts)
        foot = HBox(self.shortcut_note, 1, reset, spacing=8)
        blocks.append(foot)
        return self._page_shell("快捷键", "想怎么按就怎么按 —— 所有键位都可以改、可以清空。",
                                *blocks)

    def _on_shortcut(self, action: str, seq: str) -> None:
        if seq:
            other = sc.conflict(sc.mapping(self.store), seq, exclude=action)
            if other:
                for key, value in sc.mapping(self.store).items():
                    if key != action and value and sc.display(value) == sc.display(seq):
                        sc.set_key(self.store, key, "")
                        self._refresh_shortcut_row(key)
                self.shortcut_note.setText(i18n.trf("{keys} 原来是「{action}」的，已让位",
                                                   keys=sc.display(seq), action=other))
            else:
                self.shortcut_note.setText(i18n.trf("已改为 {keys}", keys=sc.display(seq)))
        else:
            self.shortcut_note.setText(i18n.trf("已清除 {name} 的快捷键", name=sc.label_of(action)))
        sc.set_key(self.store, action, seq)
        self._refresh_shortcut_row(action)
        self.shortcutsChanged.emit()

    def _refresh_shortcut_row(self, action: str) -> None:
        value = sc.mapping(self.store).get(action, "")
        for key, row in self._key_rows:
            if key == action:
                row.set_key(value)
                break

    def _reset_shortcuts(self) -> None:
        sc.reset(self.store)
        for action, row in self._key_rows:
            row.set_key(sc.mapping(self.store).get(action, ""))
        self.shortcut_note.setText("已恢复默认键位")
        self.shortcutsChanged.emit()

    def _page_network(self, s: Dict[str, Any]) -> QWidget:
        self.timeout = QLineEdit(str(s.get("timeout", 30)))
        self.timeout.setObjectName("Field")
        self.timeout.setFixedHeight(28)
        self.timeout.setFixedWidth(64)
        self.timeout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timeout.setFont(mono(11.5))
        self.timeout.editingFinished.connect(self._save)
        self.redirect = Switch(s.get("follow_redirects", True))
        self.redirect.toggled.connect(lambda _v: self._save())
        self.verify = Switch(s.get("verify_ssl", True))
        self.verify.toggled.connect(lambda _v: self._save())
        self.proxy_seg = SegmentedTabs([("auto", "自动"), ("system", "系统"), ("off", "直连")],
                                       style="pill", height=26, font_size=11.5, pad_h=12)
        self.proxy_seg.set_current(s.get("proxy_mode", "auto"), emit=False)
        self.proxy_seg.changed.connect(self._on_proxy)
        self.ua = QLineEdit(str(s.get("user_agent") or "Ocelot/1.0 (macOS)"))
        self.ua.setObjectName("Field")
        self.ua.setFixedHeight(28)
        self.ua.setFont(mono(11.5))
        self.ua.setFixedWidth(232)
        self.ua.editingFinished.connect(self._on_ua)
        block = self._card(
            self._row("请求超时", "单位秒，0 表示不限制。",
                      HBox(self.timeout, Label("秒", 11, theme().text_faint), spacing=6)),
            self._row("跟随重定向", "自动跟随 3xx 跳转到最终地址。", self.redirect),
            self._row("校验 SSL 证书", "关闭后可用于自签名证书的调试环境。", self.verify),
            self._row("网络代理", "自动：优先读环境变量代理，其次系统代理；本地地址始终直连。",
                      self.proxy_seg),
            self._row("默认 User-Agent", "请求没带 UA 时使用（部分接口会按 UA 限流）。", self.ua),
        )
        return self._page_shell("网络", "超时、跳转、证书与代理。", block)

    # -------------------------------------------------- AI
    def _page_ai(self, s: Dict[str, Any]) -> QWidget:
        """AI 页：开关 → Key → 模型 → 进阶（只接智谱 GLM）。

        顺序就是「能不能用 → 填 Key → 用哪个 → 细调」。整页不放彩色装饰，
        状态只用一行小字表达，避免设置页看起来比工作区还热闹。
        """
        t = theme()
        cfg = ai_mod.config(self.store)
        preset = ai_mod.PROVIDERS.get(cfg["provider"]) or ai_mod.PROVIDERS["glm"]

        # ---------- 1. 总开关（只留状态，不再重复页标题）
        self.ai_enabled = Switch(cfg["enabled"])
        self.ai_enabled.toggled.connect(self._on_ai_enabled)
        self.ai_title = Label("", 13.4, t.text, weight=QFont.Weight.DemiBold)
        self.ai_state = Label("", 10.9, t.text_faint)
        self.ai_state.setWordWrap(True)
        hero = Card(radius=12)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(18, 14, 18, 14)
        hl.setSpacing(0)
        hl.addWidget(HBox((VBox(self.ai_title, self.ai_state, spacing=3), 1),
                          self.ai_enabled, spacing=14))

        # ---------- 2. Key（只保留智谱，切服务商的入口已移除）
        self.ai_key = QLineEdit(cfg["api_key"])
        self.ai_key.setObjectName("Field")
        self.ai_key.setFixedHeight(30)
        self.ai_key.setFont(mono(11.6))
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        i18n.placeholder(self.ai_key, "粘贴 API Key")
        self.ai_key.editingFinished.connect(lambda: self._save_ai(quiet=True))
        self.ai_eye = Button("显示", None, kind="ghost", height=24, padding=8, font_size=11.4)
        self.ai_eye.clicked.connect(self._toggle_ai_key)
        self.ai_save = Button("测试连接", "check", kind="primary", height=28, padding=14,
                              font_size=12)
        self.ai_save.clicked.connect(self._save_test_ai)
        self.ai_status = Label("", 10.8, t.text_faint)
        self.ai_status.setWordWrap(True)
        self.ai_hint = Label("", 10.6, t.text_faint)
        self.ai_hint.setWordWrap(True)
        self._set_ai_hint(preset)

        conn = Card(radius=12)
        cl = QVBoxLayout(conn)
        cl.setContentsMargins(16, 10, 16, 12)
        cl.setSpacing(9)
        cl.addWidget(Label("API KEY", 9.4, t.text_faint, weight=QFont.Weight.DemiBold,
                           spacing=1.0))
        cl.addWidget(HBox((self.ai_key, 1), self.ai_eye, self.ai_save, spacing=8))
        cl.addWidget(self.ai_hint)
        cl.addWidget(self.ai_status)

        # ---------- 3. 模型
        self._ai_models = ai_mod.models_for(cfg)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self._model_cards: List[ModelCard] = []
        for i, m in enumerate(self._ai_models):
            card = ModelCard(m, selected=(m["id"] == cfg["model"]))
            card.picked.connect(self._on_model_pick)
            grid.addWidget(card, i // 2, i % 2)
            self._model_cards.append(card)
        self._model_host = QWidget()
        self._model_host.setLayout(grid)
        self.ai_model_title = Label("", 10, t.text_faint,
                                    weight=QFont.Weight.DemiBold, spacing=0.8)
        self._sync_model_title()

        # ---------- 4. 进阶
        self.ai_auto_name = Switch(bool(s.get("ai_auto_name", True)))
        self.ai_auto_name.toggled.connect(self._on_ai_auto_name)
        self.ai_custom = QLineEdit()
        self.ai_custom.setObjectName("Field")
        self.ai_custom.setFixedHeight(28)
        self.ai_custom.setFont(mono(11.5))
        i18n.placeholder(self.ai_custom, "自定义模型 ID，例如 glm-4-flash")
        self.ai_custom_add = Button("添加并使用", "plus", kind="subtle", height=28,
                                    padding=12, font_size=11.6)
        self.ai_custom_add.clicked.connect(self._add_custom_model)
        self.ai_base = QLineEdit(cfg["base"] if cfg["base"] != preset["base"] else "")
        self.ai_base.setObjectName("Field")
        self.ai_base.setFixedHeight(28)
        self.ai_base.setFont(mono(11.5))
        i18n.placeholder(self.ai_base, "留空用官方地址；中转 / 自建网关填这里")
        self.ai_base.editingFinished.connect(self._save_ai_base)
        more = self._card(
            self._row("自动起名", "发送后按内容起名；关掉只用 URL 末段。",
                      self.ai_auto_name),
            self._row_stack("自定义模型", "填上模型 ID 就能用，不用等版本更新。",
                            HBox((self.ai_custom, 1), self.ai_custom_add, spacing=8)),
            self._row_stack("服务地址", "仅在用中转或自建网关时填写。", self.ai_base),
        )

        tip = Label("Key 只保存在本机 state.json。关掉 AI 只是暂停，Key 与模型选择都不会丢。",
                    10.5, t.text_faint)
        tip.setWordWrap(True)
        self._refresh_ai_state()
        return self._page_shell("AI", "可选能力：不配也能正常调试接口，配了只是少敲几行。",
                                hero, conn, VBox(self.ai_model_title, self._model_host,
                                                 spacing=8), more, tip)

    # -------------------------------------------------- AI 状态与切服务商
    def _set_ai_hint(self, preset: Dict[str, Any]) -> None:
        self.ai_hint.setText(i18n.trf("{name} · {hint}", name=i18n.tr(preset["name"]),
                                      hint=i18n.tr(preset.get("key_hint", ""))))

    def _sync_model_title(self) -> None:
        cfg = ai_mod.config(self.store)
        self.ai_model_title.setText(
            i18n.trf("模型 · {name}（点一下切换，立即生效）", name=cfg["provider_name"]))

    def _refresh_ai_state(self) -> None:
        cfg = ai_mod.config(self.store)
        if not cfg["enabled"]:
            title, detail, color = (i18n.tr("已关闭"),
                                    i18n.tr("所有 AI 功能暂停，Key 与模型选择都还在"),
                                    theme().text_dim)
        elif not cfg["api_key"]:
            title, detail, color = (i18n.tr("未配置"),
                                    i18n.tr("填入 API Key 后即可使用，只存在本机"),
                                    theme().text_dim)
        else:
            title = i18n.tr("已就绪")
            detail = i18n.trf("{provider} · {model}",
                              provider=cfg["provider_name"], model=cfg["model"])
            color = theme().success
        self.ai_title.setText(title)
        self.ai_title.setStyleSheet(f"color: {color}; background: transparent;")
        self.ai_state.setText(detail)

    def _on_ai_enabled(self, on: bool) -> None:
        self.store.settings.setdefault("ai", {})["enabled"] = bool(on)
        self.store.save()
        self._refresh_ai_state()
        self.settingsChanged.emit()

    def _on_ai_auto_name(self, on: bool) -> None:
        self.store.settings["ai_auto_name"] = bool(on)
        self.store.save()
        self.settingsChanged.emit()

    def _toggle_ai_key(self) -> None:
        showing = self.ai_key.echoMode() == QLineEdit.EchoMode.Normal
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password if showing
                                else QLineEdit.EchoMode.Normal)
        self.ai_eye.setText(i18n.tr("显示") if showing else i18n.tr("隐藏"))

    def _ai_cfg(self) -> Dict[str, Any]:
        ai_cfg = self.store.settings.setdefault("ai", {})
        ai_cfg["api_key"] = self.ai_key.text().strip()
        return ai_mod.config(self.store)

    def _save_ai(self, quiet: bool = False) -> None:
        cfg = self._ai_cfg()
        self.store.save()
        self._refresh_ai_state()
        if not quiet:
            ok, why = ai_mod.ready(cfg)
            self.ai_status.setText(i18n.tr("已保存，可以开始用了") if ok else why)
            self.ai_status.setStyleSheet(
                f"color: {theme().success if ok else theme().text_faint}; background: transparent;")

    def _save_ai_base(self) -> None:
        self.store.settings.setdefault("ai", {})["base_url"] = self.ai_base.text().strip()
        self._save_ai(quiet=True)

    def _on_model_pick(self, model_id: str) -> None:
        if not model_id:
            return
        self.store.settings.setdefault("ai", {})["model"] = model_id
        for card in self._model_cards:
            card.set_selected(card.model.get("id") == model_id)
        self.store.save()
        self._refresh_ai_state()
        self.ai_status.setText(i18n.trf("已切换到 {model}", model=model_id))
        self.ai_status.setStyleSheet(f"color: {theme().text_faint}; background: transparent;")

    def _add_custom_model(self) -> None:
        mid = self.ai_custom.text().strip()
        if not mid:
            return
        ai_cfg = self.store.settings.setdefault("ai", {})
        items = ai_cfg.setdefault("custom_models", [])
        if not any((m or {}).get("id") == mid for m in items):
            items.append({"id": mid, "label": mid})
        ai_cfg["model"] = mid
        self.store.save()
        self.ai_custom.clear()
        self._refresh_model_grid()
        self._refresh_ai_state()

    def _refresh_model_grid(self) -> None:
        """重建模型卡片：切服务商、加过自定义模型后立刻能点选。"""
        cfg = ai_mod.config(self.store)
        host = getattr(self, "_model_host", None)
        if host is None:
            return
        grid = host.layout()
        for card in self._model_cards:
            grid.removeWidget(card)
            card.deleteLater()
        self._model_cards = []
        self._ai_models = ai_mod.models_for(cfg)
        for i, m in enumerate(self._ai_models):
            card = ModelCard(m, selected=(m["id"] == cfg["model"]))
            card.picked.connect(self._on_model_pick)
            grid.addWidget(card, i // 2, i % 2)
            self._model_cards.append(card)

    def _save_test_ai(self) -> None:
        cfg = self._ai_cfg()
        self.store.save()
        self._refresh_ai_state()
        ok, why = ai_mod.ready(cfg)
        if not ok:
            self.ai_status.setText(why)
            self.ai_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")
            return
        self.ai_save.setEnabled(False)
        self.ai_status.setText(i18n.tr("正在测试…"))
        self.ai_status.setStyleSheet(f"color: {theme().text_faint}; background: transparent;")
        msgs = [{"role": "system", "content": "只回复两个字：可用"},
                {"role": "user", "content": "连通性测试"}]
        # 200 而不是 16：GLM-4.5 / R1 这类会思考的模型先花 token 推理，给太少会「有回复但空内容」
        self._ai_test = ai_mod.start(
            msgs, cfg=cfg, max_tokens=200, temperature=0,
            on_done=lambda text: self._on_ai_tested(True, text),
            on_error=lambda err: self._on_ai_tested(False, err),
        )

    def _on_ai_tested(self, ok: bool, text: str) -> None:
        self.ai_save.setEnabled(True)
        if ok:
            self.ai_status.setText(i18n.trf("连接正常，{model} 可用", model=self._ai_cfg()["model"]))
            self.ai_status.setStyleSheet(
                f"color: {theme().success}; background: transparent;")
        else:
            self.ai_status.setText(text)
            self.ai_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")
        self._refresh_ai_state()

    # -------------------------------------------------- 云同步
    def _page_cloud(self, s: Dict[str, Any]) -> QWidget:
        self.cloud_enabled = Switch(bool(s.get("cloud_enabled", False)))
        self.cloud_enabled.toggled.connect(lambda _v: self._save_cloud())

        self.cloud_url = QLineEdit(str(s.get("turso_url", "")))
        self.cloud_url.setObjectName("Field")
        self.cloud_url.setFixedHeight(28)
        self.cloud_url.setMinimumWidth(320)
        self.cloud_url.setFont(mono(11))
        self.cloud_url.setPlaceholderText("https://ocelot-you.turso.io")
        self.cloud_url.editingFinished.connect(self._save_cloud)

        self.cloud_token = QLineEdit(str(s.get("turso_token", "")))
        self.cloud_token.setObjectName("Field")
        self.cloud_token.setFixedHeight(28)
        self.cloud_token.setMinimumWidth(320)
        self.cloud_token.setFont(mono(11))
        self.cloud_token.setEchoMode(QLineEdit.EchoMode.Password)
        i18n.placeholder(self.cloud_token, "粘贴 Turso 的 Auth Token")
        self.cloud_token.editingFinished.connect(self._save_cloud)

        test = Button("测试连接", "cloud", kind="subtle", height=26, padding=10, font_size=11.5)
        test.clicked.connect(self._test_cloud)
        self.cloud_status = Label("尚未测试", 10.5, theme().text_faint, mono_font=True)
        self.cloud_status.setMinimumWidth(150)

        up = Button("上传到云端", "download", kind="subtle", height=26, padding=10, font_size=11.5)
        up.clicked.connect(self._cloud_push)
        down = Button("从云端恢复", "refresh", kind="subtle", height=26, padding=10, font_size=11.5)
        down.clicked.connect(self._cloud_pull)

        self.cloud_auto = Switch(bool(s.get("cloud_auto", False)))
        self.cloud_auto.toggled.connect(lambda _v: self._save_cloud())

        block = self._card(
            self._row("启用云同步", "把集合、环境变量与设置存到 Turso，多台机器共用同一份数据。",
                      self.cloud_enabled),
            self._row_stack("数据库地址", "Turso 控制台里的 URL（libsql:// 开头也可以，会自动换成 https）。",
                            self.cloud_url, mono_desc=True),
            self._row_stack("Auth Token", "数据库的访问令牌，只保存在本机，上传时作为 Bearer 头。",
                            self.cloud_token, mono_desc=True),
            self._row("连通性", "先测一下再上传：只跑一条 SELECT 1，不写入任何数据。",
                      HBox(test, 4, self.cloud_status, spacing=8)),
            self._row_stack("手动同步", "上传会覆盖云端快照；恢复会先用云端覆盖本机（自动备份为 state.json.bak）。",
                            HBox(up, down, 1, spacing=6)),
            self._row("退出时自动上传", "关闭窗口时把最新数据推上去，适合固定一台机器当主库。",
                      self.cloud_auto),
        )
        tip = Label("数据表：ocelot_sync（k / v / updated_at）。同一个 Token 可见范围内只有一行快照。",
                    10.5, theme().text_faint)
        tip.setWordWrap(True)
        return self._page_shell("云同步", "用 Turso 做一份你自己的云备份 —— 不需要注册第三方账号体系。",
                                block, tip)

    def _save_cloud(self) -> None:
        from .cloud import normalize_url

        s = self.store.settings
        s["turso_url"] = normalize_url(self.cloud_url.text())
        if self.cloud_url.text().strip() and s["turso_url"] != self.cloud_url.text().strip():
            self.cloud_url.setText(s["turso_url"])
        s["turso_token"] = self.cloud_token.text().strip()
        s["cloud_enabled"] = self.cloud_enabled.isChecked()
        s["cloud_auto"] = self.cloud_auto.isChecked()
        self.store.save()

    def _cloud_busy(self, text: str) -> None:
        self.cloud_status.setText(text)
        self.cloud_status.setStyleSheet(f"color: {theme().text_dim}; background: transparent;")

    def _cloud_say(self, ok: bool, text: str) -> None:
        self.cloud_status.setText(text)
        self.cloud_status.setStyleSheet(
            f"color: {theme().success if ok else theme().danger}; background: transparent;")

    def _spawn(self, fn, cb) -> None:
        """把动作丢到后台线程，避免测试连接时整页卡住。"""
        from .cloud import CloudWorker

        worker = CloudWorker(fn, self)
        workers = getattr(self, "_workers", None)
        if workers is None:
            workers = self._workers = []
        workers.append(worker)

        def done(ok, msg, data):
            if worker in workers:
                workers.remove(worker)
            cb(ok, msg, data)

        worker.done.connect(done)
        worker.start()

    def _test_cloud(self) -> None:
        from .cloud import client_for

        self._save_cloud()
        client = client_for(self.store.settings)
        self._cloud_busy("连接中…")

        def run():
            ok, msg, _ms = client.test()
            return ok, msg, None

        def done(ok, msg, _data):
            if ok:
                self.store.settings["cloud_verified"] = True
                self.store.save()
            self._cloud_say(ok, msg)

        self._spawn(run, done)

    def _cloud_push(self) -> None:
        from .cloud import client_for

        self._save_cloud()
        client = client_for(self.store.settings)
        text = json.dumps(self.store.data, ensure_ascii=False)
        self._cloud_busy("上传中…")

        def run():
            return client.push(text)

        def done(ok, msg, _data):
            self._cloud_say(ok, msg if ok else i18n.trf("上传失败：{err}", err=msg))

        self._spawn(run, done)

    def _cloud_pull(self) -> None:
        from .cloud import client_for

        self._save_cloud()
        client = client_for(self.store.settings)
        self._cloud_busy("读取中…")

        def run():
            text, _stamp = client.pull()
            return bool(text), "云端还没有数据" if not text else "已获取快照", text

        def done(ok, msg, text):
            if not ok:
                self._cloud_say(False, i18n.trf("恢复失败：{err}", err=msg))
                return
            try:
                data = json.loads(text)
                if not isinstance(data, dict) or "collections" not in data:
                    raise ValueError("云端数据不是 Ocelot 快照")
            except Exception as exc:  # noqa: BLE001
                self._cloud_say(False, i18n.trf("数据格式不对：{err}", err=exc))
                return
            # 先备份本机快照，再整份替换；云端没带的字段（比如 token）保留本机值
            try:
                from .store import STATE_FILE

                if STATE_FILE.exists():
                    STATE_FILE.with_suffix(".json.bak").write_text(
                        STATE_FILE.read_text("utf-8"), "utf-8")
            except Exception:  # noqa: BLE001
                pass
            keep = {k: self.store.settings.get(k) for k in
                    ("turso_url", "turso_token", "cloud_enabled", "cloud_auto", "theme", "accent")}
            self.store.data.clear()
            self.store.data.update(data)
            self.store.data.setdefault("settings", {})
            self.store.settings.update({k: v for k, v in keep.items() if v is not None})
            self.store.save()
            self._cloud_say(True, "已用云端数据覆盖本机")
            self.dataReloaded.emit()

    def _page_env(self) -> QWidget:
        """变量页：环境变量 / 全局变量 用分段控件切换，不再占两个左侧导航项。

        这两件事本来就该放在一起看 —— 优先级关系（环境覆盖全局）只有并排才说得清。
        """
        t = theme()
        self.env_editor = EnvEditor(self.store)
        self.env_editor.setMinimumHeight(432)

        self.globals_editor = KVEditor("变量名", "值", empty_hint="添加全局变量",
                                       with_types=False)
        self.globals_editor.setMinimumHeight(432)
        self.globals_editor.set_rows(self.store.global_vars())
        self.globals_editor.changed.connect(self._save_globals)

        self.vars_stack = QStackedWidget()
        self.vars_stack.addWidget(self.env_editor)
        self.vars_stack.addWidget(self.globals_editor)
        self.vars_stack.setMinimumHeight(432)

        self.vars_seg = SegmentedTabs([("env", "环境变量"), ("global", "全局变量")],
                                      style="pill", height=27, font_size=11.6, pad_h=13)
        self.vars_seg.set_current("env", emit=False)
        self.vars_seg.changed.connect(self._on_vars_seg)

        self.vars_note = Label("", 10.8, t.text_faint)
        self.vars_note.setWordWrap(True)

        box = QWidget()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(HBox(self.vars_seg, 1, spacing=10))
        lay.addWidget(self.vars_note)
        lay.addWidget(self.vars_stack, 1)
        self._on_vars_seg("env")
        return self._page_shell(
            "变量", "所有请求里都用 {{名字}} 引用；同名时环境变量覆盖全局变量。", box)

    def _on_vars_seg(self, key: str) -> None:
        global_ = key == "global"
        self.vars_stack.setCurrentIndex(1 if global_ else 0)
        env = self.store.active_environment()
        if global_:
            self.vars_note.setText(i18n.tr(
                "跨环境复用的常量：公共域名、团队 Token、通用 ID。这里改了，所有环境立即生效。"))
        else:
            self.vars_note.setText(i18n.trf(
                "每种环境一套值，切换环境整套换掉。当前激活：{name}",
                name=(env or {}).get("name") or i18n.tr("未选择")))
        self.vars_note.setStyleSheet(f"color: {theme().text_faint}; background: transparent;")

    def _save_globals(self) -> None:
        self.store.data["global_vars"] = self.globals_editor.rows()
        self.store.save()
        self.settingsChanged.emit()

    def _page_data(self) -> QWidget:
        path = str(STATE_FILE.parent).replace(str(os.path.expanduser("~")), "~")
        open_dir = Button("打开数据目录", "folder", kind="ghost", height=26, padding=10, font_size=11.5)
        open_dir.clicked.connect(self._open_dir)
        clear_hist = Button("清空历史", "trash", kind="ghost", height=26, padding=10, font_size=11.5)
        clear_hist.clicked.connect(self._clear_history)
        limit = int(self.store.settings.get("history_limit", 240))
        self.limit_seg = SegmentedTabs([("100", "100 条"), ("240", "240 条"), ("500", "500 条")],
                                       style="pill", height=26, font_size=11.5, pad_h=12)
        self.limit_seg.set_current(str(limit) if str(limit) in ("100", "240", "500") else "240",
                                   emit=False)
        self.limit_seg.changed.connect(self._on_history_limit)

        # 回收站自动清理：默认开启，保留天数可切（7 / 30 / 90）。
        # 保存设置时（_save）立即按新配置清一次过期条目，不必等下次启动。
        self.trash_enabled = Switch(bool(self.store.settings.get("trash_enabled", True)))
        self.trash_enabled.toggled.connect(lambda _v: self._save())
        days = int(self.store.settings.get("trash_days", 30))
        self.trash_days_seg = SegmentedTabs(
            [("7", "7 天"), ("30", "30 天"), ("90", "90 天")],
            style="pill", height=26, font_size=11.5, pad_h=12)
        self.trash_days_seg.set_current(str(days) if str(days) in ("7", "30", "90") else "30",
                                        emit=False)
        self.trash_days_seg.changed.connect(self._on_trash_days)
        # 这条说明带运行时数字，整句不是固定词条；保存引用，切语言时用 trf 重设。
        self.history_note = Label(
            i18n.tr("当前 {n} 条，超出后自动丢弃最旧的。").format(
                n=len(self.store.history or [])), 11, theme().text_faint)
        block = self._card(
            self._row("本地数据", path, open_dir, mono_desc=True),
            self._row("历史记录上限", "", self.limit_seg, desc_label=self.history_note),
            self._row("清空历史", "只删历史记录，集合与环境变量不受影响。", clear_hist),
            self._row("回收站自动清理",
                      "开启后按保留天数清除过期条目，默认开、保留 30 天。",
                      self.trash_enabled),
            self._row("回收站保留天数", "超过天数的条目在保存设置与启动时自动彻底删除。",
                      self.trash_days_seg),
        )
        return self._page_shell("数据", "所有数据都是本地纯 JSON，可直接备份或版本管理。", block)

    def _on_trash_days(self, value: str) -> None:
        try:
            self.store.settings["trash_days"] = int(value)
        except (TypeError, ValueError):
            self.store.settings["trash_days"] = 30
        self._save()

    def _page_about_app(self) -> QWidget:
        """关于页：品牌区 + 运行环境 + 常用入口，做得像一张「应用名片」。"""
        import platform as _platform

        from .store import APP_DIR

        t = theme()
        word = Label("Ocelot", 30, t.text, weight=QFont.Weight.DemiBold, spacing=-0.4)
        tag = Label("把请求调试做得干净、安静的桌面工具。没有账号体系，没有遥测，数据只留在你的机器上。",
                    11.8, t.text_dim)
        tag.setWordWrap(True)
        pills = HBox(Pill(f"v{VERSION}", t.text_dim, font_size=10.2),
                     Pill("纯本地", t.text_faint, font_size=10.2),
                     1, spacing=6)
        # 标识：进来先自己演一遍「描边重画」，之后鼠标悬浮还能再演
        self.about_mark = BrandMark(52, token="text", hover_token="accent",
                                    autoplay=True, tooltip="Ocelot")
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(13)
        title_row.addWidget(self.about_mark, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addWidget(word, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        hero = Card(radius=12)
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(22, 20, 22, 18)
        hv.setSpacing(7)
        hv.addLayout(title_row)
        hv.addWidget(tag)
        hv.addSpacing(6)
        hv.addWidget(pills)

        # ---------- 运行环境：三列，中间一条细竖线
        def metric(caption: str, value: str) -> QWidget:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            v.addWidget(Label(caption, 9.6, t.text_faint,
                              weight=QFont.Weight.DemiBold, spacing=0.7))
            val = Label(value, 11.4, t.text_dim, mono_font=True)
            val.setWordWrap(True)
            v.addWidget(val)
            return box

        env_card = Card(radius=10)
        eh = QHBoxLayout(env_card)
        eh.setContentsMargins(18, 14, 18, 14)
        eh.setSpacing(18)
        eh.addWidget(metric("版本", f"Ocelot {VERSION}"), 2)
        line2 = QWidget()
        line2.setFixedWidth(1)
        line2.setStyleSheet(f"background: {t.border};")
        eh.addWidget(line2)
        mac_ver, _cpu, _arch = _platform.mac_ver()
        sys_text = (f"macOS {mac_ver or _platform.release()} · {_platform.machine()}")
        eh.addWidget(metric("系统", sys_text), 3)

        # ---------- 入口
        notes = Button("查看更新内容", "book", kind="subtle", height=30, padding=12, font_size=12)
        notes.clicked.connect(lambda: WhatsNewDialog(self).exec())
        folder = Button("打开数据目录", "folder", kind="subtle", height=30, padding=12, font_size=12)
        folder.clicked.connect(self._open_dir)
        copy_btn = Button("复制版本信息", "copy", kind="ghost", height=30, padding=12, font_size=12)
        copy_btn.clicked.connect(lambda: self._copy_version_info(copy_btn))
        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(8)
        al.addWidget(notes)
        al.addWidget(folder)
        al.addWidget(copy_btn)
        al.addStretch(1)

        # ---------- 为什么是 Ocelot：四条能验证的优势，不写空话
        def perk(icon_name: str, title: str, desc: str) -> QWidget:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 12, 0)
            v.setSpacing(5)
            ic = Label("", 12)
            ic.setFixedSize(16, 16)
            ic.setPixmap(icons.pixmap(icon_name, t.text_dim, 16, 1.6))
            v.addWidget(ic)
            v.addWidget(Label(title, 12.2, t.text, weight=QFont.Weight.DemiBold))
            d = Label(desc, 10.8, t.text_faint)
            d.setWordWrap(True)
            v.addWidget(d)
            return w

        grid = Card(radius=12)
        gl = QVBoxLayout(grid)
        gl.setContentsMargins(18, 16, 18, 16)
        gl.setSpacing(16)
        gl.addWidget(Label("为什么是 Ocelot", 10, t.text_faint,
                           weight=QFont.Weight.DemiBold, spacing=0.8))
        row1 = HBox(perk("lock", "数据只在你的机器上",
                         "集合、历史、环境变量都是本地 JSON。没有账号体系，没有遥测，"
                         "断网也能整理接口。"),
                    perk("send", "一条链路做完四件事",
                         "发请求 → 看响应 → 出接口文档 → 复制十种语言代码，都在一个窗口里，"
                         "不用再开浏览器和编辑器。"),
                    1, spacing=18)
        row2 = HBox(perk("layers", "原生绘制，不是套壳浏览器",
                         "界面全部由 QPainter 自绘，单进程、无 Electron，冷启动一秒内，"
                         "大响应也不会把内存吃满。"),
                    perk("code", "可以 diff 的配置",
                         "状态文件是纯文本，能进 Git、能手改、能脚本生成；"
                         "出了问题用编辑器就能查清。"),
                    1, spacing=18)
        gl.addWidget(row1)
        gl.addWidget(row2)

        # ---------- 能力清单：只说「你能用它做什么」，不摆文件名与类名
        abilities = [
            ("发请求", "参数、请求头、Cookies、表单与 JSON 请求体分开填，"
                      "改动即时生效；地址栏支持历史补全与变量替换。"),
            ("看响应", "JSON 树、格式化原文、图片 / 音视频预览、响应时间线四种视角；"
                      "几百 KB 的响应也是秒开，不卡滚动。"),
            ("出文档", "一次点击把请求与响应变成完整接口文档：概览、参数表、"
                      "状态码语义、响应示例，再加上十种语言的调用代码。"),
            ("造假数据", "在自己电脑上起一个真服务，路由、状态码、延迟、动态字段、"
                        "条件规则都能改；前端联调不用等后端排期。"),
            ("多环境", "测试 / 预发 / 线上各存一套变量，{{base_url}} 写在请求里，"
                      "切换环境整组地址一起变。"),
            ("可复用", "每次响应都进历史，能对比、能重放、能直接生成代码；"
                      "集合与配置都是纯文本，可以进 Git、可以脚本生成。"),
        ]
        grid2 = Card(radius=12)
        g2 = QVBoxLayout(grid2)
        g2.setContentsMargins(18, 16, 18, 16)
        g2.setSpacing(14)
        g2.addWidget(Label("它能做什么", 10, t.text_faint,
                           weight=QFont.Weight.DemiBold, spacing=0.8))
        for i in range(0, len(abilities), 2):
            pair = abilities[i:i + 2]
            row = HBox(*[self._ability(*a) for a in pair], 1, spacing=20)
            g2.addWidget(row)

        arch = Card(radius=12)
        al = QVBoxLayout(arch)
        al.setContentsMargins(18, 16, 18, 16)
        al.setSpacing(0)
        al.addWidget(Label("一次请求走完的流程", 10, t.text_faint,
                           weight=QFont.Weight.DemiBold, spacing=0.8))
        al.addSpacing(10)
        steps = [
            ("1", "写好请求", "填地址与参数，变量自动换成当前环境的值"),
            ("2", "发出去", "请求在后台跑，界面不冻结，随时可以取消"),
            ("3", "看结果", "状态、耗时、体积、响应头、响应体一处看完"),
            ("4", "留下来", "进历史、出文档、生代码，下次直接复用"),
        ]
        for i, (num, title, desc) in enumerate(steps):
            if i:
                al.addWidget(Divider())
            al.addWidget(HBox(
                Label(num, 10.2, t.text_faint, mono_font=True), 0,
                Label(title, 11.4, t.text, weight=QFont.Weight.Medium), 0,
                Label(desc, 10.8, t.text_faint), 1,
                spacing=12, margins=(0, 8, 0, 8)))
        al.addWidget(Divider())
        flow = Label("整个过程不离开一个窗口，也不用把参数、响应在各处复制粘贴。",
                     10.8, t.text_faint)
        flow.setWordWrap(True)
        al.addWidget(HBox(flow, 1, margins=(0, 10, 0, 0)))

        self.about_foot = Label(f"{i18n.tr('数据目录')} · {APP_DIR}", 10.4,
                                t.text_faint, mono_font=True)
        return self._page_shell("关于 Ocelot", "它是什么、能做什么、为什么这么做。",
                                hero, env_card, grid, grid2, arch, actions, self.about_foot)

    def _ability(self, title: str, desc: str) -> QWidget:
        """关于页的能力条目：一行标题 + 两行说明，宽度自适应两列。"""
        t = theme()
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(Label(title, 12.2, t.text, weight=QFont.Weight.DemiBold))
        d = Label(desc, 10.8, t.text_faint)
        d.setWordWrap(True)
        v.addWidget(d)
        return w

    def _copy_version_info(self, button: Button) -> None:
        import platform as _platform
        import sys as _sys

        from PyQt6.QtCore import QT_VERSION_STR
        from PyQt6.QtGui import QGuiApplication

        from .store import APP_DIR

        text = (f"Ocelot {VERSION}\n"
                f"Python {_sys.version.split()[0]} · PyQt6 {QT_VERSION_STR}\n"
                f"{_platform.platform()}\n"
                f"数据目录 {APP_DIR}")
        QGuiApplication.clipboard().setText(text)
        button.setText("已复制")

    # -------------------------------------------------- 行
    def _row(self, title: str, desc: str, control: QWidget, mono_desc: bool = False,
             desc_label: Optional[Label] = None) -> QWidget:
        """左右一行：左边标题+说明，右边控件。

        说明文字必须可换行 —— 窄窗口下不许把控件挤出卡片边界（云同步页的输入框
        之前就是被顶出右边界的）。
        desc_label：外部已建好的说明标签，用于保存引用、语言切换时重设动态文案。
        """
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 11, 2, 11)
        h.setSpacing(16)
        d = desc_label if desc_label is not None else Label(
            desc, 11, theme().text_faint, mono_font=mono_desc)
        d.setWordWrap(True)
        text = VBox(Label(title, 12.5, theme().text), d, spacing=3)
        text.setMaximumWidth(330)
        h.addWidget(text, 1)
        h.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return w

    def _row_stack(self, title: str, desc: str, control: QWidget,
                   mono_desc: bool = False) -> QWidget:
        """上下排：控件独占一整行。输入框 / 多按钮这类「宽控件」用这个，永远不吃边。"""
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(2, 11, 2, 13)
        v.setSpacing(8)
        d = Label(desc, 11, theme().text_faint, mono_font=mono_desc)
        d.setWordWrap(True)
        v.addWidget(VBox(Label(title, 12.5, theme().text), d, spacing=3))
        v.addWidget(control)
        return w

    def _apply_page_title(self) -> None:
        label = dict((k, l) for k, l, _i in self.NAV).get(self.nav.current_key(), "设置")
        self._title_label.setText(i18n.trf("设置 · {name}", name=label))

    def refresh_i18n(self) -> None:
        """重设运行时拼接的文案。

        AI 状态行 / Key 提示 / 模型标题、变量页说明、历史条数、关于页路径都是
        「模板 + 动态值」当场拼出来的中文整句，通用 apply_language 用 tr(整句)
        查不到词条，于是英文界面里这几处一直是中文。这里按模板重新走 trf。
        """
        try:
            preset = ai_mod.PROVIDERS["glm"]
            self._set_ai_hint(preset)
            self._sync_model_title()
            self._refresh_ai_state()
        except Exception:             # noqa: BLE001
            pass
        try:
            self._on_vars_seg(self.vars_seg.current())
        except Exception:             # noqa: BLE001
            pass
        try:
            self.history_note.setText(
                i18n.tr("当前 {n} 条，超出后自动丢弃最旧的。").format(
                    n=len(self.store.history or [])))
        except Exception:             # noqa: BLE001
            pass
        try:
            self._apply_page_title()
        except Exception:             # noqa: BLE001
            pass
        try:
            from .store import APP_DIR
            self.about_foot.setText(f"{i18n.tr('数据目录')} · {APP_DIR}")
        except Exception:             # noqa: BLE001
            pass

    # -------------------------------------------------- 事件
    def _on_nav(self, key: str) -> None:
        widget = getattr(self, "_page_widgets", {}).get(key)
        if widget is not None and widget is not self.stack.currentWidget():
            self.stack.setCurrentWidget(widget)
        self._apply_page_title()

    def _on_theme(self, name: str) -> None:
        self.store.settings["theme"] = name
        self.store.save()
        self.themeChanged.emit(name)

    def _on_scheme(self, name: str) -> None:
        self._on_theme(name)

    def _on_accent(self, key: str) -> None:
        self.store.settings["accent"] = key
        self.store.save()
        self.accentChanged.emit(key)

    def _on_language(self, value: str) -> None:

        self.store.settings["language"] = "en" if value == "en" else "zh"
        self.store.save()
        i18n.set_language(self.store.settings["language"])   # 立即刷新主界面
        # 设置窗口是独立的顶层窗口，不在主窗口的 findChildren 覆盖范围内，
        # 这里自己再翻一遍，否则右侧页面还停在旧语言。
        self._retranslate()
        self.settingsChanged.emit()

    def _retranslate(self) -> None:
        """设置窗口内部跟着语言切换刷新（标题、左侧导航宽度、右侧页面文案）。"""
        from .widgets import Button, SegmentedTabs

        i18n.apply_language(self)
        try:
            nav = getattr(self, "nav", None)
            if nav is not None:
                nav.sync_width()
                nav.update()
        except RuntimeError:  # noqa: BLE001
            pass
        for w in self.findChildren(QWidget):
            if isinstance(w, SegmentedTabs):
                w.sync_size()
            elif isinstance(w, Button):
                w.updateGeometry()
                w.update()
        # 页面标题（自绘 Label 之外的标题条）也要跟着变
        try:
            self._apply_page_title()
        except RuntimeError:  # noqa: BLE001
            pass
        self.update()

    def _on_anim(self, on: bool) -> None:
        self.store.settings["animations"] = bool(on)
        self.store.save()
        self.settingsChanged.emit()

    def _on_glass(self, on: bool) -> None:
        """所有弹窗是否都模糊 + 不可拖动（立即生效，下次弹窗就按新规则来）。"""
        self.store.settings["glass_all"] = bool(on)
        self.store.save()
        self.settingsChanged.emit()

    def _on_ui_scale(self, value: str) -> None:
        """界面文字大小：当场缩放整个界面，不关设置页。

        以前是「存下来 → 关设置页 → 重建主窗口 → 再打开设置页」，用户点下去
        什么都没看见，还以为功能坏了。现在直接按比例缩放现有控件（见 app.zoom），
        设置页本身也跟着变，边调边看。
        """
        from . import theme
        from .zoom import apply_scale

        try:
            scale = float(value)
        except (TypeError, ValueError):
            return
        old = theme.ui_scale()
        if abs(scale - old) < 1e-3:
            return
        theme.set_ui_scale(scale)
        apply_scale(scale / old)
        self.store.settings["ui_scale"] = scale
        self.store.save()
        self.uiScaleChanged.emit(scale)
        self.update()

    def _on_font_size(self, value: str) -> None:
        from .code_editor import CodeView

        try:
            size = float(value)
        except (TypeError, ValueError):
            return
        self.store.settings["code_font_size"] = size
        self.store.save()
        CodeView.set_global_size(size)

    def _on_proxy(self, mode: str) -> None:
        self.store.settings["proxy_mode"] = mode
        self.store.save()

    def _on_ua(self) -> None:
        ua = self.ua.text().strip() or "Ocelot/1.0 (macOS)"
        self.ua.setText(ua)
        self.store.settings["user_agent"] = ua
        self.store.save()

    def _on_history_limit(self, value: str) -> None:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return
        self.store.settings["history_limit"] = limit
        del self.store.history[limit:]
        self.store.save()

    def _save(self) -> None:
        s = self.store.settings
        try:
            s["timeout"] = max(0, int(self.timeout.text() or 30))
        except (ValueError, AttributeError):
            try:
                self.timeout.setText(str(s.get("timeout", 30)))
            except AttributeError:
                pass
        for attr, key in (("redirect", "follow_redirects"), ("verify", "verify_ssl"),
                          ("auto_name", "auto_name"), ("restore_session", "restore_session"),
                          ("stale_notice", "stale_notice"),
                          ("glass_switch", "glass_all"), ("trash_enabled", "trash_enabled")):
            wdg = getattr(self, attr, None)
            if wdg is not None:
                s[key] = wdg.isChecked()
        # 「默认开启，点击保存时清掉过期内容」——设置落盘前先按新配置清一次，
        # 这样改完保留天数立刻生效，不用等下次启动。
        self.store.purge_expired_trash()
        self.store.save()
        self.settingsChanged.emit()

    def _done(self) -> None:
        self._save()
        if getattr(self, "env_editor", None) is not None:
            self.env_editor.save()
        self.accept()

    def _open_dir(self) -> None:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices

        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(STATE_FILE.parent)))

    def _clear_history(self) -> None:
        self.store.clear_history()
        self.store.save()
        self.settingsChanged.emit()

    def showEvent(self, e):
        super().showEvent(e)
        if self._page == "env" and getattr(self, "env_editor", None) is not None:
            self.env_editor._fill_list()


class EnvDelegate(QStyledItemDelegate):
    """环境列表：自绘圆角选中态 + 当前环境圆点。"""

    def sizeHint(self, option, index):  # noqa: N802
        return QSize(0, 33)

    def paint(self, p, option, index):
        t = theme()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        item = index.model().itemData(index)
        name = str(item.get(Qt.ItemDataRole.DisplayRole) or "")
        active = bool(item.get(Qt.ItemDataRole.UserRole))
        rect = QRectF(option.rect).adjusted(4, 2, -4, -2)
        selected = bool(option.state & __import__("PyQt6.QtWidgets", fromlist=["QStyle"]).QStyle.StateFlag.State_Selected)
        if selected:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(t.selected))
            p.drawRoundedRect(rect, 6, 6)
        p.setFont(font(12.5, weight=QFont.Weight.Medium if selected else QFont.Weight.Normal))
        p.setPen(C(t.text) if selected else C(t.text_dim))
        p.drawText(QRectF(rect.left() + 10, rect.top(), rect.width() - 30, rect.height()),
                   int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                   QFontMetricsF(p.font()).elidedText(name, Qt.TextElideMode.ElideRight,
                                                      int(rect.width()) - 30))
        if active:
            pm = icons.pixmap("check", t.success, 11, 2.0)
            p.drawPixmap(QPointF(rect.right() - 19, rect.center().y() - 5.5), pm)
        p.restore()


# ---------------------------------------------------------------- 环境变量


class EnvEditor(QWidget):
    """环境变量编辑面板（可内嵌在设置里，不再单独弹窗）。"""

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.envs = copy.deepcopy(store.environments or [])
        self.current = store.data.get("active_env")
        self._loading = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        content = QHBoxLayout()
        content.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(6)
        self.list = QListWidget()
        self.list.setFixedWidth(184)
        self.list.setFont(font(12.5))
        self.list.setItemDelegate(EnvDelegate(self.list))
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setStyleSheet(
            f"QListWidget {{ background: {theme().panel_alt}; border: 1px solid {S(theme().border)};"
            f" border-radius: 9px; padding: 4px; }}")
        self.list.currentRowChanged.connect(self._on_select)
        self.list.itemDoubleClicked.connect(lambda _i: self._rename_env())
        left.addWidget(self.list, 1)
        row = HBox()
        add = icon_button("plus", "新建环境", 28, 15)
        add.clicked.connect(self._add_env)
        rename = icon_button("pencil", "重命名", 28, 15)
        rename.clicked.connect(self._rename_env)
        dele = icon_button("trash", "删除环境", 28, 15)
        dele.clicked.connect(self._delete_env)
        activate = Button("设为当前", None, kind="subtle", height=26, padding=9, font_size=11.5)
        activate.clicked.connect(self._activate)
        row.layout().addWidget(activate)
        row.layout().addSpacing(6)
        row.layout().addWidget(add)
        row.layout().addWidget(rename)
        row.layout().addWidget(dele)
        row.layout().addStretch(1)
        left.addWidget(row)
        content.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.right_label = Label("变量", 11, theme().text_faint)
        right.addWidget(self.right_label)
        self.vars = KVEditor("变量名", "值", empty_hint="添加变量")
        self.vars.changed.connect(self._on_vars_changed)
        right.addWidget(self.vars, 1)
        content.addLayout(right, 1)
        lay.addLayout(content, 1)

        hint = Label("变量名区分大小写；动态变量如 {{$timestamp}} 无需定义。", 10.5,
                     theme().text_faint)
        lay.addWidget(hint)
        self._fill_list()

    def _fill_list(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for env in self.envs:
            item = QListWidgetItem(env.get("name", "环境"))
            item.setData(Qt.ItemDataRole.UserRole, env.get("id") == self.current)
            self.list.addItem(item)
        self.list.blockSignals(False)
        index = next((i for i, e in enumerate(self.envs) if e.get("id") == self.current), 0)
        if self.envs:
            self.list.setCurrentRow(max(0, min(index, len(self.envs) - 1)))

    def _current_env(self) -> Optional[Dict[str, Any]]:
        row = self.list.currentRow()
        if 0 <= row < len(self.envs):
            return self.envs[row]
        return None

    def _on_select(self, _row: int) -> None:
        env = self._current_env()
        self._loading = True
        if env:
            self.vars.set_rows(env.get("vars", []))
            self.right_label.setText(i18n.trf("变量 · {name}", name=env.get("name", "")))
        else:
            self.vars.set_rows([])
        self._loading = False

    def _on_vars_changed(self) -> None:
        if self._loading:
            return
        env = self._current_env()
        if env:
            env["vars"] = self.vars.rows()

    def _add_env(self) -> None:
        env = {"id": f"env_{len(self.envs)}_{os.urandom(2).hex()}",
               "name": i18n.trf("环境 {n}", n=len(self.envs) + 1), "vars": []}
        self.envs.append(env)
        self._fill_list()
        self.list.setCurrentRow(len(self.envs) - 1)

    def _rename_env(self) -> None:
        env = self._current_env()
        if not env:
            return
        dlg = PromptDialog("重命名环境", "名称", env.get("name", ""), self)
        if dlg.exec() and dlg.value().strip():
            env["name"] = dlg.value().strip()
            self._fill_list()

    def _delete_env(self) -> None:
        env = self._current_env()
        if not env:
            return
        self.envs = [e for e in self.envs if e is not env]
        if self.current == env.get("id"):
            self.current = self.envs[0]["id"] if self.envs else None
        self._fill_list()

    def _activate(self) -> None:
        env = self._current_env()
        if env:
            self.current = env.get("id")
            self._fill_list()

    def save(self) -> None:
        self.store.data["environments"] = self.envs
        self.store.set_active_env(self.current)
        self.store.save()


class EnvDialog:
    """兼容旧入口：直接打开设置的「环境变量」页。"""

    def __init__(self, store: Store, parent=None):
        self.store = store
        self.parent_widget = parent

    def exec(self) -> int:  # noqa: N802
        return SettingsDialog(self.store, self.parent_widget, page="env").exec()


# ---------------------------------------------------------------- 代码片段


class CodeDialog(GlassDialog):
    def __init__(self, request: Dict[str, Any], env: Dict[str, str],
                 settings: Dict[str, Any], parent=None):
        super().__init__(parent, 720, 500, "代码片段")
        self.request = request
        self.env = env
        self.settings = settings

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 8, 16, 14)
        lay.setSpacing(8)

        self.tabs = SegmentedTabs([(key, label) for key, label, _fn, _lang in LANGUAGES],
                                  style="pill", height=28, font_size=11, pad_h=9, spacing=1)
        self.tabs.changed.connect(self._render)
        copy = Button("复制", "copy", kind="subtle", height=28, padding=10, font_size=12)
        copy.clicked.connect(self._copy)
        lay.addWidget(HBox(self.tabs, 1, copy, spacing=8))

        self.code = CodeView(read_only=True, highlight=True, show_gutter=True, wrap=True)
        self.code.set_language("python")
        frame = Card(radius=9)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 4, 0, 4)
        fl.addWidget(self.code)
        lay.addWidget(frame, 1)
        lay.addWidget(Label("已使用当前环境变量解析值，可直接粘贴到终端运行。", 10.5, theme().text_faint))
        self._render(self.tabs.current())

    def _render(self, key: str) -> None:
        for lang_key, _label, gen, language in LANGUAGES:
            if lang_key == key:
                self.code.set_language(language)
                self.code.setPlainText(gen(self.request, self.env, self.settings))
                return
        # 兜底：保持对话框永远有内容
        self.code.set_language("shell")
        self.code.setPlainText(LANGUAGES[0][2](self.request, self.env, self.settings))

    def _copy(self) -> None:
        QApplication.clipboard().setText(self.code.toPlainText())


# ---------------------------------------------------------------- 导入 cURL


class ImportCurlDialog(GlassDialog):
    """粘贴 cURL 命令 → 解析预览 → 新开标签。

    解析用 app/curl_import.parse_curl：方法、URL、查询参数、请求头、
    -d/--data-raw 请求体、-F multipart（含 @file）、-u Basic 认证都能还原。
    """

    def __init__(self, parent=None):
        super().__init__(parent, 640, 460, "导入 cURL")
        self.request = None
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(18, 10, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(Label("粘贴浏览器「Copy as cURL」或任意 cURL 命令，自动解析方法、请求头、请求体与认证。",
                            11, theme().text_faint))
        self.edit = QPlainTextEdit()
        self.edit.setFont(mono(11.5))
        self.edit.setPlaceholderText(
            "curl 'https://api.example.com/v1/users' \\\n"
            "  -X POST \\\n"
            "  -H 'Content-Type: application/json' \\\n"
            "  -H 'Authorization: Bearer token' \\\n"
            "  --data-raw '{\"name\": \"Ocelot\"}'")
        self.edit.setStyleSheet(
            f"QPlainTextEdit {{ background: {theme().code_bg}; border: 1px solid {S(theme().border)};"
            f" border-radius: 9px; padding: 10px; color: {theme().text}; }}")
        self.edit.textChanged.connect(self._preview)
        lay.addWidget(self.edit, 3)

        paste = Button("从剪贴板粘贴", "paste", kind="ghost", height=26, padding=10, font_size=11.5)
        paste.clicked.connect(self._paste_clip)
        lay.addWidget(HBox(1, paste, spacing=6))

        self.preview = Label("", 11, theme().text_dim, mono_font=True)
        self.preview.setWordWrap(True)
        self.preview.setMinimumHeight(46)
        lay.addWidget(self.preview)
        self.error = Label("", 10.5, theme().danger, mono_font=True)
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        cancel = Button("取消", None, kind="ghost", height=28, padding=12, font_size=12)
        cancel.clicked.connect(self.reject)
        ok = Button("解析并打开", None, kind="primary", height=28, padding=16, font_size=12)
        ok.clicked.connect(self._parse)
        lay.addWidget(HBox(1, cancel, ok, spacing=6))
        self._preview()

    def _paste_clip(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self.edit.setPlainText(text)

    def _summarize(self, req) -> str:
        bits = [f"{req['method']}  {req['url']}"]
        if req.get("params"):
            bits.append(i18n.trf("查询参数 {n} 个", n=len(req["params"])))
        if req.get("headers"):
            bits.append(i18n.trf("请求头 {n} 个", n=len(req["headers"])))
        body = req.get("body") or {}
        mode = body_mode(body)
        if mode in ("json", "html"):
            bits.append(i18n.trf("JSON 请求体 {n} 字符", n=len(body.get("raw") or "")))
        elif mode == "xml":
            bits.append(i18n.trf("XML 请求体 {n} 字符", n=len(body.get("raw") or "")))
        elif mode == "text":
            bits.append(i18n.trf("文本请求体 {n} 字符", n=len(body.get("raw") or "")))
        elif mode == "form":
            files = sum(1 for f in body.get("form", []) if f.get("type") == "file")
            bits.append(i18n.trf("multipart {n} 字段", n=len(body.get("form", [])))
                        + (i18n.trf("（含 {n} 个文件）", n=files) if files else ""))
        elif mode == "urlencoded":
            bits.append(i18n.trf("urlencoded {n} 字段", n=len(body.get("form", []))))
        if (req.get("auth") or {}).get("type") == "basic":
            bits.append(i18n.tr("Basic 认证"))
        return " · ".join(bits)

    def _preview(self) -> None:
        from .curl_import import CurlParseError, parse_curl, strip_hints

        text = self.edit.toPlainText()
        if not text.strip():
            self.preview.setText("")
            self.error.setText("")
            self.request = None
            return
        try:
            self.request = strip_hints(parse_curl(text))
        except CurlParseError as exc:
            self.request = None
            self.error.setText(str(exc))
            self.preview.setText("")
            return
        self.error.setText("")
        self.preview.setText(self._summarize(self.request))

    def _parse(self) -> None:
        self._preview()
        if self.request is None:
            if not self.error.text():
                self.error.setText("请先粘贴 cURL 命令")
            return
        self.accept()


# ---------------------------------------------------------------- 更新内容


def _group_items(items: List[str]) -> List[tuple]:
    """按条目内容分组：修复 / 改进 / 新功能，便于阅读。"""
    groups: Dict[str, List[str]] = {"新功能": [], "改进": [], "修复": []}
    for raw in items:
        text = raw.strip()
        if text.startswith("修复"):
            key = "修复"
        elif text.startswith(("新功能", "新增", "增加", "支持", "加入")):
            key = "新功能"
        else:
            key = "改进"
        groups[key].append(text)
    return [(k, v) for k, v in groups.items() if v]


class WhatsNewPanel(QWidget):
    """更新内容面板：版本分组 + 分类小标题 + 自动换行，可滚动。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        host = QWidget()
        host_lay = QVBoxLayout(host)
        host_lay.setContentsMargins(4, 2, 12, 18)
        host_lay.setSpacing(18)
        for i, entry in enumerate(CHANGELOG):
            host_lay.addWidget(self._entry(entry, latest=(i == 0)))
        host_lay.addStretch(1)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll)

    def _entry(self, entry: Dict[str, Any], latest: bool = False) -> QWidget:
        t = theme()
        card = QWidget()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        ver = Label(f"v{entry.get('version', '')}", 13.5, t.text, mono_font=True,
                    weight=QFont.Weight.DemiBold)
        date = Label(entry.get("date", ""), 10.5, t.text_faint, mono_font=True)
        head = HBox(ver, date, spacing=10)
        if latest:
            tag = Label(i18n.trf("当前版本 {v}", v=VERSION), 9.5, t.text_dim, mono_font=True)
            tag.setStyleSheet(
                f"color: {t.text_dim}; background: {S(t.hover)}; border-radius: 4px;"
                f" padding: 2px 6px;")
            head.layout().addStretch(1)
            head.layout().addWidget(tag)
        lay.addWidget(head)

        group_colors = {"新功能": t.success, "改进": t.info, "修复": t.warning}
        for name, items in _group_items(entry.get("items", [])):
            color = group_colors.get(name, t.text_faint)
            section = Label(f"{name} {len(items)}", 10, color,
                            weight=QFont.Weight.DemiBold, spacing=0.6)
            lay.addWidget(section)
            for text in items:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(8)
                dot = Label("•", 12, color)
                dot.setFixedWidth(7)
                dot.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
                rl.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
                # 分组标题已标明类别，去掉条目里重复的前缀，读起来更干净
                shown = text
                for prefix in ("新功能：", "修复：", "改进：", "新功能:", "修复:", "改进:"):
                    if shown.startswith(prefix):
                        shown = shown[len(prefix):]
                        break
                body = Label(shown, 12, t.text_dim)
                body.setWordWrap(True)
                rl.addWidget(body, 1)
                lay.addWidget(row)
        return card


class WhatsNewDialog(GlassDialog):
    def __init__(self, parent=None):
        super().__init__(parent, 620, 560, "更新内容")
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(20, 8, 14, 16)
        lay.setSpacing(10)
        lay.addWidget(WhatsNewPanel(), 1)
        ok = Button("关闭", None, kind="primary", height=28, padding=20, font_size=12)
        ok.clicked.connect(self.accept)
        foot = HBox(1, ok, spacing=8)
        foot.layout().setContentsMargins(4, 0, 6, 0)
        lay.addWidget(foot)


# ---------------------------------------------------------------- 命令面板


class PaletteList(QWidget):
    activated = pyqtSignal(int)

    HEADER_H = 24

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[Dict[str, Any]] = []
        self.index = 0
        self._hover = -1
        self._hover_v = 0.0
        self._tops: List[float] = []
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.row_h = 40

    def row_height(self, item: Dict[str, Any]) -> int:
        return self.HEADER_H if item.get("kind") == "header" else self.row_h

    def set_items(self, items: List[Dict[str, Any]]) -> None:
        self.items = items
        self.index = self.first_index()
        self._hover = -1
        self._hover_v = 0.0
        y = 4.0
        self._tops = []
        for item in items:
            self._tops.append(y)
            y += self.row_height(item)
        self.setFixedHeight(max(1, int(y + 4)))
        self.update()

    def visible_range(self) -> Tuple[int, int]:
        """当前视口内的行区间 [start, end)。

        上千条请求时整表重绘是命令面板「越用越卡」的主因：文字、图标的
        pixmap 每次都从头画一遍。这里只算可见的那几十行，滚动时再补下一屏，
        列表本身（数据、总高度、搜索）完全不变。
        """
        from .widgets import _scroll_host

        view = _scroll_host(self)
        offset = 0
        height = self.height()
        if view is not None:
            try:
                offset = view.verticalScrollBar().value()
                height = view.viewport().height()
            except RuntimeError:
                pass
        if not self._tops:
            return 0, 0
        import bisect

        start = max(0, bisect.bisect_right(self._tops, offset) - 1)
        end = min(len(self._tops), bisect.bisect_left(self._tops, offset + height) + 1)
        return start, end

    def first_index(self) -> int:
        for i, item in enumerate(self.items):
            if item.get("kind") != "header":
                return i
        return 0

    def step(self, delta: int) -> int:
        """上下键跳过小标题，只在真正的条目之间移动。"""
        i = self.index
        for _ in range(len(self.items)):
            i += delta
            if i < 0 or i >= len(self.items):
                return self.index
            if self.items[i].get("kind") != "header":
                self.index = i
                return i
        return self.index

    def _row_at(self, y: int) -> int:
        import bisect

        if not self._tops:
            return -1
        i = bisect.bisect_right(self._tops, y) - 1
        if 0 <= i < len(self.items) and self._tops[i] <= y < self._tops[i] + self.row_height(self.items[i]):
            return i
        return -1

    def mouseMoveEvent(self, e):
        if not self.rect().contains(e.position().toPoint()):
            if self._hover != -1:
                self._hover = -1
                self._hover_v = 0.0
                self.update()
            return
        idx = self._row_at(int(e.position().y()))
        if not (0 <= idx < len(self.items)):
            idx = -1
        if idx != self._hover:
            # 悬停必须零延迟跟手：不加补间动画，鼠标到哪灰层就在哪
            self._hover = idx
            self._hover_v = 1.0 if idx >= 0 else 0.0
            self.update()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        if self._hover != -1:
            self._hover = -1
            self._hover_v = 0.0
            self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        idx = self._row_at(int(e.position().y()))
        if 0 <= idx < len(self.items) and self.items[idx].get("kind") != "header":
            self.activated.emit(idx)

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if not self.items:
            p.setFont(font(12))
            p.setPen(C(t.text_faint))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter),
                       i18n.tr("没有匹配的结果"))
            p.end()
            return
        # 只画视口内的行（上下各多留一行，滚动时不会看到半截空白）
        first, last = self.visible_range()
        first = max(0, first - 1)
        last = min(len(self.items), last + 1)
        for i in range(first, last):
            item = self.items[i]
            top = self._tops[i] if i < len(self._tops) else 4 + i * self.row_h
            h = self.row_height(item)
            if item.get("kind") == "header":
                # 分组小标题：只做视觉分隔，不可点、不能选
                p.setFont(font(9.6, weight=QFont.Weight.DemiBold))
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(14, top, self.width() - 28, h),
                           int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           i18n.tr(item.get("title") or ""))
                continue
            r = QRectF(6, top, self.width() - 12, h - 2)
            active = i == self.index
            hovered = i == self._hover
            if hovered:
                # 鼠标所在行永远优先，且无延迟
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(t.selected))
                p.drawRoundedRect(r, 8, 8)
            elif active:
                # 键盘选中行：只留一圈细边，避免和鼠标灰层抢视觉
                p.setPen(QPen(C(t.border_strong), 1))
                p.setBrush(C(t.hover))
                p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            ic = item.get("icon", "dot")
            col = t.text if (active or hovered) else t.text_dim
            pm = icons.pixmap(ic, col, 14, 1.6)
            p.drawPixmap(QPointF(r.left() + 12, r.center().y() - 7), pm)
            p.setFont(font(12.5, weight=font(12.5).weight()))
            p.setPen(C(t.text) if (active or hovered) else C(t.text_dim))
            hint = item.get("hint", "")
            hint_w = 52 if hint else 8
            tw = QFontMetricsF(p.font()).horizontalAdvance(item["title"]) + 6
            title_w = min(tw, r.width() * 0.46)
            p.drawText(QRectF(r.left() + 38, r.top(), title_w, r.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       QFontMetricsF(p.font()).elidedText(item["title"], Qt.TextElideMode.ElideRight,
                                                          max(title_w, 40)))
            sub = item.get("subtitle", "")
            if sub:
                p.setFont(mono(10))
                p.setPen(C(t.text_faint))
                sub_rect = QRectF(r.left() + 38 + title_w + 12, r.top(),
                                  max(r.width() - 60 - title_w - hint_w, 30), r.height())
                p.drawText(sub_rect, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                           QFontMetricsF(p.font()).elidedText(sub, Qt.TextElideMode.ElideMiddle,
                                                              int(sub_rect.width())))
            if hint:
                p.setFont(mono(10))
                p.setPen(C(t.text_faint))
                p.drawText(QRectF(r.right() - hint_w - 6, r.top(), hint_w, r.height()),
                           int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), hint)
        p.end()


class CommandPalette(QWidget):
    """⌘K 命令面板：覆盖主窗口的浮层，可搜索请求与执行动作。"""

    execute = pyqtSignal(str, object)

    ACTIONS = [
        ("new_request", "新建请求", "plus", "⌘N"),
        ("new_ws", "新建 WebSocket 请求", "link", ""),
        ("new_sio", "新建 Socket.IO 请求", "link", ""),
        ("new_folder", "新建文件夹", "folder", ""),
        ("send", "发送当前请求", "send", "⌘↵"),
        ("save", "保存到集合", "download", "⌘S"),
        ("env", "变量…", "globe", ""),
        ("trash", "打开回收站", "trash", ""),
        ("trash_settings", "回收站自动清理设置…", "trash", ""),
        ("settings", "设置…", "sliders", "⌘,"),
        ("appearance", "外观与主题色…", "moon", ""),
        ("cloud", "云同步…", "cloud", ""),
        ("toggle_sidebar", "显示 / 隐藏侧边栏", "layers", "⌘B"),
        ("import_curl", "导入 cURL…", "code", ""),
        ("import_collection", "导入集合…", "download", ""),
        ("export_collection", "导出集合…", "file", ""),
        ("doc", "查看接口文档…", "file", ""),
        ("mock", "Mock 服务…", "grid", ""),
        ("shortcuts", "快捷键设置…", "keyboard", ""),
        ("duplicate", "复制当前请求", "copy", ""),
        ("close_tab", "关闭当前标签", "close", "⌘W"),
    ]

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.hide()
        self._opacity = 0.0
        self._slide = 0.0
        # 抓背景模糊图时把这个浮层藏起来，否则面板会被拍进模糊底图里
        self.setProperty("backdropSuppress", True)

        self.card = Card(radius=13, parent=self)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(10, 10, 10, 6)
        cl.setSpacing(6)
        self.edit = QLineEdit()
        self.edit.setObjectName("Bare")
        i18n.placeholder(self.edit, "搜索请求，或执行命令…")
        self.edit.setFont(font(15))
        self.edit.setFixedHeight(34)
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        ic = Label("", 12)
        ic.setFixedSize(15, 15)
        ic.setPixmap(icons.pixmap("search", theme().text_faint, 15, 1.7))
        row = HBox(ic, self.edit, spacing=8, margins=(10, 2, 10, 2))
        cl.addWidget(row)
        cl.addWidget(Divider())
        # 命令越多越长，超出卡片高度就滚动 —— 之前直接按条目数定死高度，
        # 结果最后几条被卡片裁掉，既看不见也滚不到。
        self.scroll = SmoothScrollArea()
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list = PaletteList()
        self.scroll.setWidget(self.list)
        cl.addWidget(self.scroll, 1)
        self.list.activated.connect(self._activate)
        self._results: List[Dict[str, Any]] = []

    # -------------------------------------------------- 打开 / 关闭
    def _area(self) -> QRectF:
        """浮层该铺的范围：宿主窗口的卡片区（去掉阴影留白），和模糊遮罩一致。"""
        parent = self.parentWidget()
        if parent is None:
            return QRectF()
        fn = getattr(parent, "card_rect", None)
        if callable(fn):
            try:
                r = fn()
                if r is not None and not r.isEmpty():
                    return QRectF(r)
            except Exception:      # noqa: BLE001
                pass
        return QRectF(parent.rect())

    def open(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        # 上一次关闭的淡出还在飞：它的 on_done 会把面板藏起来（刚打开又消失）
        _anim_stop(getattr(self, "_fade_anim", None))
        self._fade_anim = None
        area = self._area()
        self.setGeometry(area.toRect())
        self.card.setFixedWidth(min(620, int(area.width()) - 80))
        # 每次打开只收集一次（集合树可能有几百条），之后按键只做过滤。
        # 只留一份（带分组标题），过滤时不再另建一份带重复 dict 的列表。
        self._cache = self._collect(True)
        self._hay = [
            (str(i.get("title") or "") + "\u0001" + str(i.get("subtitle") or "")).lower()
            for i in self._cache
        ]
        self.edit.clear()
        # 关键：所有排版（列表高度、卡片高度、居中位置）都先算完再 show。
        # 之前是先 show 再改高度 —— 打开的那一帧卡片会先矮后高，看起来「上下卡一下」。
        self._slide = 0.0
        self._filter("")
        bar = self.scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)
        self._opacity = 0.0
        # 先铺模糊再显示浮层：反过来的话抓图会把浮层自己拍进去，背景上出现鬼影
        if not getattr(self, "_blur_on", False):
            self._blur_on = True
            backdrop.acquire(self)
        self.show()
        self.raise_()          # 遮罩是后加的兄弟控件，浮层要再抬一次
        self.edit.setFocus()
        # 入场：淡入 + 从上方 10px 落下来，和弹窗同一套手感
        self._slide = 10.0
        self.card.move(self.card.x(), self._card_y())
        animate(self, 0.0, 1.0, 120, self._set_opacity)
        animate(self, 10.0, 0.0, 160, self._set_slide)

    def _set_slide(self, v):
        self._slide = float(v)
        self.card.move(self.card.x(), self._card_y())

    def _set_opacity(self, v):
        self._opacity = float(v)
        self.update()

    def _card_y(self) -> int:
        h = self.card.height() or self.card.sizeHint().height()
        y = (self.height() - h) // 2 + int(getattr(self, "_slide", 0.0))
        return max(28, min(y, max(28, self.height() - h - 28)))

    def _layout_card(self) -> None:
        # 卡片永远摆在正中间（上下左右都居中）：以前压在 16% 高度，
        # 大屏上看着像是「贴在顶上下不来」。
        # 高度上不铺满整窗：一屏塞太多行既晃眼也没必要，留白反而更好读。
        max_h = max(180, min(px(360), self.height() - 260))
        # 卡片高度落在整行上：差几个像素就会把最后一行切掉半截。
        # 用二分查最后一整行（几千条请求时别每次按键都从头累加一遍）。
        import bisect

        tops = self.list._tops
        content_h = self.list.height()
        if tops:
            i = max(0, bisect.bisect_right(tops, max_h) - 1)
            row = self.list.row_height(self.list.items[i])
            content_h = int(tops[i] + row + 4)
        self.scroll.setFixedHeight(min(self.list.height(), max(60, content_h)))
        self.card.setFixedHeight(self.card.sizeHint().height())
        self.card.move((self.width() - self.card.width()) // 2, self._card_y())
        self._scroll_to(self.list.index)

    def _scroll_to(self, index: int) -> None:
        if not (0 <= index < len(self.list._tops)):
            return
        bar = self.scroll.verticalScrollBar()
        if bar is None:
            return
        top = self.list._tops[index]
        bottom = top + self.list.row_height(self.list.items[index])
        view = self.scroll.viewport().height()
        if top < bar.value():
            bar.setValue(int(top) - 4)
        elif bottom > bar.value() + view:
            bar.setValue(int(bottom - view) + 4)

    def close(self) -> None:
        self._fade_anim = animate(self, 1.0, 0.0, 100, self._set_opacity,
                                  on_done=self.hide)

    def hideEvent(self, e):
        self._opacity = 0.0
        if getattr(self, "_blur_on", False):
            self._blur_on = False
            backdrop.release(self)
        super().hideEvent(e)

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close()
        super().mousePressEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        elif e.key() == Qt.Key.Key_Down:
            self.list.step(1)
            self.list.update()
            self._scroll_to(self.list.index)
        elif e.key() == Qt.Key.Key_Up:
            self.list.step(-1)
            self.list.update()
            self._scroll_to(self.list.index)
        else:
            super().keyPressEvent(e)

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == event.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Escape):
                self.keyPressEvent(event)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate(self.list.index)
                return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------- 数据
    PINNED = 5

    def _hits(self) -> Dict[str, int]:
        return self.store.data.setdefault("palette_hits", {})

    def _action_item(self, action) -> Dict[str, Any]:
        key, title, icon_name, hint = action
        return {"kind": "action", "key": key, "title": i18n.tr(title),
                "icon": icon_name, "hint": hint, "subtitle": ""}

    def _pinned_actions(self) -> List[tuple]:
        """用得最多的 5 条置顶；还没用过就按默认顺序取前 5 条。"""
        hits = self._hits()
        order = {a[0]: i for i, a in enumerate(self.ACTIONS)}
        return sorted(self.ACTIONS,
                      key=lambda a: (-int(hits.get(a[0], 0)), order[a[0]]))[:self.PINNED]

    def _collect(self, with_headers: bool = True) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        pinned = self._pinned_actions()
        rest = [a for a in self.ACTIONS if a not in pinned]
        if with_headers:
            items.append({"kind": "header", "title": "常用", "icon": "", "hint": "",
                          "subtitle": ""})
        items.extend(self._action_item(a) for a in pinned)
        if with_headers and rest:
            items.append({"kind": "header", "title": "全部命令", "icon": "", "hint": "",
                          "subtitle": ""})
        items.extend(self._action_item(a) for a in rest)
        for env in self.store.environments:
            active = env.get("id") == self.store.data.get("active_env")
            items.append({
                "kind": "env", "key": env.get("id"),
                "title": i18n.trf("切换到环境 · {name}", name=env.get("name", "")),
                "icon": "globe", "hint": i18n.tr("当前") if active else "",
                "subtitle": i18n.trf("{n} 个变量", n=len(env.get("vars") or [])),
            })
        for node, _ in self.store.walk():
            if node.get("type") != "request":
                continue
            items.append({
                "kind": "request", "key": node.get("id"), "node": node,
                "title": node.get("name") or i18n.tr("请求"), "icon": "send",
                "subtitle": f"{node.get('method', 'GET')}  {node.get('url', '')}",
                "hint": "",
            })
        return items

    def _filter(self, text: str) -> None:
        query = (text or "").strip().lower()
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = self._collect(True)
            self._cache = cache
            self._hay = [
                (str(i.get("title") or "") + "\u0001" + str(i.get("subtitle") or "")).lower()
                for i in cache
            ]
        if query:
            hay = self._hay
            self._results = [cache[i] for i, h in enumerate(hay) if query in h
                             and cache[i].get("kind") != "header"]
        else:
            self._results = cache
        self.list.set_items(self._results)
        self._layout_card()
        self.update()

    def _activate(self, index: int) -> None:
        if not (0 <= index < len(self._results)):
            return
        item = self._results[index]
        if item.get("kind") == "header":
            return
        if item.get("kind") == "action":
            # 记住使用频率，「常用」那五项就会越用越准
            hits = self._hits()
            hits[item["key"]] = int(hits.get(item["key"], 0)) + 1
            self.store.save()
        self.close()
        self.execute.emit(item["kind"], item.get("node") or item["key"])

    # -------------------------------------------------- 绘制
    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(max(0.0, min(1.0, self._opacity)))
        dim = QColor(0, 0, 0, 46 if t.is_dark else 26)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 12, 12)
        p.fillPath(path, dim)
        p.end()


# ---------------------------------------------------------------- 导入 / 导出


class TransferRow(QWidget):
    """一行可点条目：图标 + 标题 + 说明 + 右箭头，悬停时底下一层浅色。"""

    clicked = pyqtSignal()

    def __init__(self, icon_name: str, title: str, subtitle: str = "",
                 parent=None, height: int = 54, danger: bool = False):
        super().__init__(parent)
        self._icon = icon_name
        self._title = title
        self._subtitle = subtitle
        self._danger = danger
        self._hover = 0.0
        self._anim: Optional[QVariantAnimation] = None
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _animate_to(self, target: float) -> None:
        from .anim import animations_on, stop as _stop

        if not animations_on():
            self._hover = target
            self.update()
            return
        if self._anim is not None:
            _stop(self._anim)
        anim = QVariantAnimation(self)
        anim.setStartValue(float(self._hover))
        anim.setEndValue(float(target))
        anim.setDuration(120)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(self._on_v)
        self._anim = anim
        anim.start()

    def _on_v(self, value) -> None:
        self._hover = float(value)
        self.update()

    def enterEvent(self, e):  # noqa: N802
        self._animate_to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._animate_to(0.0)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if not self.isEnabled():
            return
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(
                e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        r = QRectF(self.rect()).adjusted(2, 1, -2, -1)
        if self._hover > 0.01:
            bg = C(t.hover)
            bg.setAlpha(int(bg.alpha() * self._hover))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 8, 8)
        enabled = self.isEnabled()
        col = t.danger if self._danger else (t.text_dim if enabled else t.text_faint)
        pm = icons.pixmap(self._icon, col, 17, 1.5)
        p.drawPixmap(QPointF(12, (self.height() - 17) / 2), pm)
        left = 40
        if self._subtitle:
            p.setFont(font(12.6))
            p.setPen(C(t.text))
            p.drawText(QRectF(left, 9, self.width() - left - 30, 20),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(self._title))
            p.setFont(font(10.8))
            p.setPen(C(t.text_faint))
            p.drawText(QRectF(left, 28, self.width() - left - 30, 18),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(self._subtitle))
        else:
            p.setFont(font(12.6))
            p.setPen(C(t.text))
            p.drawText(QRectF(left, 0, self.width() - left - 30, self.height()),
                       int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                       i18n.tr(self._title))
        arrow = icons.pixmap("chevron_right", t.text_faint, 13, 1.6)
        p.drawPixmap(QPointF(self.width() - 22, (self.height() - 13) / 2), arrow)
        p.end()


class DropZone(QWidget):
    """虚线圈起来的投放区：既能点开系统选文件，也能把文件拖进来。"""

    dropped = pyqtSignal(str)
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(132)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self.filename = ""

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hover = True
            self.update()

    def dragLeaveEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()

    def dropEvent(self, e):  # noqa: N802
        self._hover = False
        self.update()
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path:
                self.dropped.emit(path)
                break

    def mouseReleaseEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        pen = QPen(C(t.border_strong if not self._hover else t.accent), 1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.setBrush(C(t.panel_alt if not self._hover else t.elevated))
        p.drawRoundedRect(r, 10, 10)
        pm = icons.pixmap("download" if not self.filename else "file",
                          t.text_dim if not self._hover else t.accent, 22, 1.4)
        p.drawPixmap(QPointF((self.width() - 22) / 2, 26), pm)
        p.setFont(font(12.4))
        p.setPen(C(t.text))
        title = self.filename or i18n.tr("把文件拖到这里，或点击选择")
        p.drawText(QRectF(14, 58, self.width() - 28, 22),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter), title)
        p.setFont(font(10.8))
        p.setPen(C(t.text_faint))
        p.drawText(QRectF(14, 80, self.width() - 28, 20),
                   int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                   i18n.tr("支持 .json / .yaml / .har，自动识别来源"))
        p.end()


def _short_path(path: str, keep: int = 42) -> str:
    """太长的路径中间省略，保证一行放得下（悬停能看到完整值）。"""
    if len(path) <= keep:
        return path
    head = path[: max(6, keep // 3)]
    tail = path[-max(8, keep // 2):]
    return head.rstrip("/") + "/…/" + tail.lstrip("/")


def _size_text(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


class DonePage(QWidget):
    """导入 / 导出的结果页：大对勾 + 明细清单 + 主按钮。

    比单纯一行「✓ 已导入」有用多了 —— 用户能一眼确认到底导进来了什么。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: List[QWidget] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 16)
        lay.setSpacing(0)

        self.badge = _SuccessBadge()
        # 用两侧弹簧包起来居中，比 AlignHCenter 更稳（页面宽度变化时不会偏）
        lay.addWidget(HBox(1, self.badge, 1))
        lay.addSpacing(10)

        self.title = Label("", 15, theme().text, weight=QFont.Weight.DemiBold)
        self.title.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.title)
        lay.addSpacing(4)
        self.sub = Label("", 11.3, theme().text_faint)
        self.sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)
        lay.addSpacing(16)

        self.card = QWidget()
        self.card_lay = QVBoxLayout(self.card)
        self.card_lay.setContentsMargins(14, 4, 14, 4)
        self.card_lay.setSpacing(0)
        self.card.setStyleSheet(
            f"background: {S(theme().panel_alt)}; border-radius: 10px;")
        lay.addWidget(self.card)
        lay.addStretch(1)

        self.primary = Button("完成", "check", kind="primary", height=32,
                              padding=20, font_size=12.2)
        self.secondary = Button("返回", "chevron_left", kind="ghost", height=32,
                                padding=14, font_size=12.2)
        self.secondary.hide()
        lay.addWidget(HBox(1, self.secondary, self.primary, spacing=8))

    # -------------------------------------------------- 内容
    def reset(self, title: str, subtitle: str, primary: str,
              secondary: Optional[str] = None) -> None:
        self.title.setText(title)
        self.sub.setText(subtitle)
        self.primary.setText(primary)
        if secondary:
            self.secondary.setText(secondary)
            self.secondary.show()
        else:
            self.secondary.hide()
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        self.badge.restart()

    def add_row(self, icon_name: str, name: str, value: str) -> None:
        if self._rows:
            self.card_lay.addWidget(Divider())
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(2, 7, 2, 7)
        rl.setSpacing(9)
        icon = QLabel()
        icon.setFixedSize(14, 14)
        icon.setPixmap(icons.pixmap(icon_name, theme().text_faint, 13, 1.6))
        label = Label(name, 11.8, theme().text_dim)
        value_label = Label(value, 12, theme().text, mono_font=True,
                            weight=QFont.Weight.DemiBold)
        rl.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        rl.addWidget(label, 1, Qt.AlignmentFlag.AlignVCenter)
        rl.addWidget(value_label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.card_lay.addWidget(row)
        self._rows.append(row)


class _SuccessBadge(QWidget):
    """圆形底色里的对勾：出现时缩放回落 + 一圈扩散光晕，左右严格居中。

    注意对勾必须用 icons.draw_centered 画：QPixmap.width() 是设备像素，
    手写 `width/2 - pm.width()/2` 会让对勾整体偏左十几个像素（用户看到的
    「动画 logo 错位」就是这个）。
    """

    SIZE = 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._scale = 1.0
        self._halo = 1.0
        self._anim: Optional[QVariantAnimation] = None
        self._halo_anim: Optional[QVariantAnimation] = None

    def restart(self) -> None:
        _anim_stop(self._anim)
        _anim_stop(self._halo_anim)
        pop = QVariantAnimation(self)
        pop.setStartValue(0.55)
        pop.setEndValue(1.0)
        pop.setDuration(300)
        pop.setEasingCurve(QEasingCurve.Type.OutBack)
        pop.valueChanged.connect(self._on_scale)
        self._anim = pop
        pop.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

        halo = QVariantAnimation(self)
        halo.setStartValue(0.0)
        halo.setEndValue(1.0)
        halo.setDuration(620)
        halo.setEasingCurve(QEasingCurve.Type.OutCubic)
        halo.valueChanged.connect(self._on_halo)
        self._halo_anim = halo
        halo.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_scale(self, v):
        self._scale = float(v)
        self.update()

    def _on_halo(self, v):
        self._halo = float(v)
        self.update()

    def paintEvent(self, _e):
        t = theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cx, cy = self.width() / 2, self.height() / 2
        side = 50 * max(0.4, self._scale)
        r = QRectF(cx - side / 2, cy - side / 2, side, side)
        # 扩散光晕：从本体边缘向外散开并淡出，收尾后完全消失
        if self._halo < 0.999:
            grow = 8 + 16 * self._halo
            ring = QColor(C(t.success))
            ring.setAlpha(int(90 * (1.0 - self._halo)))
            p.setPen(QPen(ring, 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(r.adjusted(-grow, -grow, grow, grow))
        fill = QColor(C(t.success))
        fill.setAlpha(28)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawEllipse(r)
        edge = QColor(C(t.success))
        edge.setAlpha(110)
        p.setPen(QPen(edge, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
        icon_size = max(12, int(25 * max(0.55, self._scale)))
        icons.draw_centered(p, icons.pixmap("check", t.success, icon_size, 2.6), cx, cy)
        p.end()


class TransferDialog(GlassDialog):
    """集合的导入 / 导出：一个对话框里完成选择来源、选文件、导出。

    头部左侧的返回箭头只在第二层出现；所有操作都在这个框里，不会一层层弹新窗口。
    """

    BLUR_FIXED = True       # 导入导出窗口永远模糊 + 固定居中

    imported = pyqtSignal(int)      # 导入的请求条数
    _urlDone = pyqtSignal(str, str)  # (下载到的文本, 错误)

    def __init__(self, store: Store, parent=None):
        from .transfer import EXPORT_TARGETS, IMPORT_SOURCES

        super().__init__(parent, 580, 660, i18n.tr("集合"))
        self.store = store
        self._source = ""
        self._pending: Optional[Tuple[List[Dict[str, Any]], str, str]] = None
        self._last_name = ""            # 最近一次导入的集合名（导出默认文件名用它）
        self._pending_name = ""
        self._urlDone.connect(self._on_url_text)
        self._import_sources = IMPORT_SOURCES
        self._export_targets = EXPORT_TARGETS
        self._done_title = "完成"
        self._done_height = 470

        # 头部：返回 + 标题
        self.back_btn = icon_button("chevron_left", "返回", 24, 13)
        self.back_btn.clicked.connect(self._go_back)
        hl = self.header.layout()
        hl.insertWidget(0, self.back_btn)
        self.back_btn.hide()

        self.stack = FadeStack()
        self.stack.setContentsMargins(0, 0, 0, 0)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.stack)
        self.stack.add("import", self._build_import())
        self.stack.add("file", self._build_file())
        self.stack.add("export", self._build_export())
        self.stack.add("done", self._build_done())
        self.stack.set_current("import", animate=False)
        self.setAcceptDrops(True)
        # 初始高度直接按来源列表的真实内容给：写死的 660 会多出一截空白
        self.resize(self.width(),
                    self.header.height() + 1
                    + self.stack._pages["import"].sizeHint().height())

    # -------------------------------------------------- 页面 1：来源列表
    def _build_import(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        self.import_rows = []
        for key, title, desc in self._import_sources:
            row = TransferRow(self._source_icon(key), title, desc)
            row.clicked.connect(lambda k=key: self._choose_source(k))
            lay.addWidget(row)
            self.import_rows.append(row)
        lay.addWidget(Divider())
        clip = TransferRow("paste", "从剪贴板导入",
                           "自动识别 JSON 集合或 cURL 命令，直接粘过来")
        clip.clicked.connect(self._import_clipboard)
        lay.addWidget(clip)
        url_row = TransferRow("link", "从 URL 导入",
                              "填一个远程 JSON / YAML 地址，自动下载并识别来源")
        url_row.clicked.connect(self._import_url)
        lay.addWidget(url_row)
        # 不给弹簧：弹簧会把「导出全部集合」顶到最下面，中间留一大条空白
        lay.addSpacing(8)
        lay.addWidget(Divider())
        export_row = TransferRow("download", "导出全部集合",
                                 "Ocelot JSON / Postman / OpenAPI / HAR")
        export_row.clicked.connect(lambda: self._show_page("export"))
        lay.addWidget(export_row)
        return page

    def _build_done(self) -> QWidget:
        self.done = DonePage()
        self.done.primary.clicked.connect(self.accept)
        self.done.secondary.clicked.connect(self._go_back)
        return self.done

    @staticmethod
    def _source_icon(key: str) -> str:
        return {"ocelot": "grid", "postman": "send", "apifox": "layers",
                "hoppscotch": "file", "insomnia": "moon", "openapi": "book",
                "har": "table"}.get(key, "file")

    # -------------------------------------------------- 页面 2：选择文件
    def _build_file(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(18, 10, 18, 16)
        lay.setSpacing(10)
        self.file_title = Label("", 13.5, theme().text, weight=QFont.Weight.DemiBold)
        self.file_desc = Label("", 11.4, theme().text_faint)
        self.file_desc.setWordWrap(True)
        lay.addWidget(self.file_title)
        lay.addWidget(self.file_desc)
        self.zone = DropZone()
        self.zone.clicked.connect(self._pick_file)
        self.zone.dropped.connect(self._load_path)
        lay.addWidget(self.zone)
        self.file_status = Label("", 11.2, theme().text_faint)
        self.file_status.setWordWrap(True)
        lay.addWidget(self.file_status)
        lay.addStretch(1)
        self.file_hint = Label(
            "导入只会新增集合，不会覆盖现有内容；重复导入会产生新的副本。",
            10.8, theme().text_faint)
        self.file_hint.setWordWrap(True)
        lay.addWidget(self.file_hint)
        back = Button("返回", "chevron_left", kind="ghost", height=30, padding=12, font_size=12)
        back.clicked.connect(self._go_back)
        self.import_btn = Button("导入", "download", kind="primary", height=30,
                                 padding=18, font_size=12)
        self.import_btn.clicked.connect(self._do_import)
        self.import_btn.setEnabled(False)
        lay.addWidget(HBox(1, back, self.import_btn, spacing=6))
        return page

    def _choose_source(self, key: str) -> None:
        titles = {k: t for k, t, _d in self._import_sources}
        descs = {k: d for k, _t, d in self._import_sources}
        self._source = key
        self._pending = None
        self.zone.filename = ""
        self.zone.update()
        self.file_title.setText(i18n.tr(titles.get(key, "导入")))
        self.file_desc.setText(i18n.tr(descs.get(key, "")))
        self.file_status.setText("")
        self.import_btn.setEnabled(False)
        self._show_zone(True)
        self._show_page("file")

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("选择要导入的文件"), "",
            "集合文件 (*.json *.yaml *.yml *.har);;所有文件 (*)")
        if path:
            self._load_path(path)

    def _load_path(self, path: str) -> None:
        from pathlib import Path

        try:
            text = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = Path(path).read_text(encoding="utf-8-sig")
            except Exception as exc:  # noqa: BLE001
                self._fail(i18n.trf("读取失败：{err}", err=exc))
                return
        except Exception as exc:  # noqa: BLE001
            self._fail(i18n.trf("读取失败：{err}", err=exc))
            return
        self._load_text(text, Path(path).name, Path(path).stem)

    def _load_text(self, text: str, display_name: str, stem: str = "") -> None:
        from .transfer import FORMAT_LABELS, environments_of, parse_text, summarize

        nodes, fmt, err = parse_text(text, fallback_name=stem)
        if err or not nodes:
            self._fail(err or i18n.tr("文件里没有可导入的请求"))
            return
        stats = summarize(nodes)
        envs = environments_of(text)
        self._pending = (nodes, fmt, text)
        self._pending_name = ""
        if len(nodes) == 1 and nodes[0].get("type") == "folder":
            self._pending_name = nodes[0].get("name") or ""
        self._show_zone(True)
        self.zone.filename = display_name
        self.zone.update()
        label = FORMAT_LABELS.get(fmt, fmt)
        bits = [i18n.trf("{n} 个请求", n=stats["requests"])]
        if stats["folders"]:
            bits.append(i18n.trf("{n} 个文件夹", n=stats["folders"]))
        for key, name in (("pre", "前置脚本"), ("post", "后置脚本"),
                          ("auth", "认证"), ("cookies", "Cookies")):
            if stats.get(key):
                bits.append(i18n.trf("{n} 个{name}", n=stats[key], name=i18n.tr(name)))
        if envs:
            bits.append(i18n.trf("{n} 套环境变量", n=len(envs)))
        if self._pending_name:
            bits.append(i18n.trf("集合名「{name}」", name=self._pending_name))
        self.file_status.setText(i18n.trf("✓ 已识别 {fmt}：{detail}",
                                          fmt=label, detail=" · ".join(bits)))
        self.file_status.setStyleSheet(f"color: {theme().success}; background: transparent;")
        self.import_btn.setEnabled(True)

    def _show_zone(self, show: bool) -> None:
        """选文件页的投放区 / 提示 / 主按钮一起显隐（URL 下载与剪贴板提示共用）。"""
        for w in (getattr(self, "zone", None), getattr(self, "file_hint", None),
                  getattr(self, "import_btn", None)):
            if w is not None:
                w.setVisible(show)

    def _import_url(self) -> None:
        """远程地址导入：填一个链接，下载后走和本地文件完全一样的识别流程。"""
        dlg = PromptDialog(i18n.tr("从 URL 导入"), i18n.tr("集合 JSON / YAML 的地址"), "", self)
        dlg.edit.setText("https://" if not QApplication.clipboard().text().startswith("http")
                         else QApplication.clipboard().text().strip())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        url = dlg.value().strip()
        if not url.lower().startswith(("http://", "https://")):
            self.toast_hint(i18n.tr("地址要以 http:// 或 https:// 开头"))
            return
        self._source = "url"
        self.file_title.setText(i18n.tr("从 URL 导入"))
        self.file_desc.setText(url)
        self.file_status.setText(i18n.tr("正在下载…"))
        self.file_status.setStyleSheet(f"color: {theme().text_faint}; background: transparent;")
        self.import_btn.setEnabled(False)
        self._show_zone(False)
        self._show_page("file")
        import threading

        def worker():
            text, error = "", ""
            try:
                import urllib.request

                req = urllib.request.Request(url, headers={"User-Agent": "Ocelot"})
                with urllib.request.urlopen(req, timeout=20) as resp:   # noqa: S310
                    raw = resp.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    error = "文件超过 8 MB，请先下载到本地再导入"
                else:
                    text = raw.decode("utf-8", "replace")
            except Exception as exc:      # noqa: BLE001
                error = str(exc)
            self._urlDone.emit(text, error)

        threading.Thread(target=worker, daemon=True).start()

    def _on_url_text(self, text: str, error: str) -> None:
        if error or not text.strip():
            self._fail(i18n.trf("下载失败：{err}", err=error or "内容为空"))
            self._show_zone(True)
            return
        stem = ""
        try:
            from urllib.parse import urlparse

            tail = urlparse(self.file_desc.text()).path.rstrip("/").split("/")[-1]
            stem = tail.rsplit(".", 1)[0] if "." in tail else tail
        except Exception:      # noqa: BLE001
            stem = ""
        self._load_text(text, stem or i18n.tr("远程集合"), stem)

    def _fail(self, message: str) -> None:
        self._pending = None
        self.import_btn.setEnabled(False)
        self.file_status.setText("✕ " + message)
        self.file_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")

    def _do_import(self) -> None:
        if self._pending is None:
            return
        from .transfer import FORMAT_LABELS, environments_of, summarize

        nodes, fmt, text = self._pending
        self.store.collections.extend(nodes)
        # 随文件带回来的环境变量一起还原（同名环境跳过，不覆盖现有配置）
        added_envs = 0
        existing = {e.get("name") for e in self.store.environments}
        for env in environments_of(text):
            if env.get("name") in existing:
                continue
            env["id"] = uid()
            self.store.environments.append(env)
            existing.add(env.get("name"))
            added_envs += 1
        self._pending = None
        self._last_name = self._pending_name
        self.store.save()
        stats = summarize(nodes)
        self.imported.emit(stats["requests"])
        self._show_import_done(stats, added_envs, FORMAT_LABELS.get(fmt, fmt),
                               collections=len(nodes))

    def _show_import_done(self, stats: Dict[str, int], envs: int, fmt_label: str,
                          collections: int = 1) -> None:
        rows = [("folder", "集合", str(collections)),
                ("grid", "请求", str(stats["requests"]))]
        if stats["folders"]:
            rows.append(("folder", "文件夹", str(stats["folders"])))
        if stats["pre"]:
            rows.append(("code", "前置脚本", str(stats["pre"])))
        if stats["post"]:
            rows.append(("code", "后置脚本", str(stats["post"])))
        if stats["auth"]:
            rows.append(("lock", "认证配置", str(stats["auth"])))
        if stats["cookies"]:
            rows.append(("grid", "Cookies", str(stats["cookies"])))
        if envs:
            rows.append(("layers", "环境变量", str(envs)))
        self._done_title = i18n.tr("导入完成")
        self._done_height = 290 + len(rows) * 30
        sub = i18n.trf("来自 {fmt} · 已追加到集合列表末尾", fmt=fmt_label)
        if self._last_name:
            sub = i18n.trf("集合「{name}」来自 {fmt}，已追加到侧栏末尾",
                           name=self._last_name, fmt=fmt_label)
        self.done.reset(i18n.trf("已导入 {n} 个请求", n=stats["requests"]), sub,
                        i18n.tr("完成"))
        self.done.secondary.hide()
        for icon_name, name, value in rows:
            self.done.add_row(icon_name, i18n.tr(name), value)
        self._show_page("done")

    def _import_clipboard(self) -> None:
        """剪贴板里的 JSON / cURL 直接导入，省掉存文件这一步。"""
        from .importer import parse_curl
        from .transfer import count_requests, parse_text

        text = QApplication.clipboard().text() or ""
        if not text.strip():
            self.toast_hint(i18n.tr("剪贴板是空的"))
            return
        if text.strip().lower().startswith("curl"):
            req, err = parse_curl(text)
            if err or req is None:
                self.toast_hint(err or i18n.tr("cURL 解析失败"))
                return
            self.store.collections.append(req)
            self.store.save()
            self.imported.emit(1)
            self.toast_hint(i18n.tr("已从剪贴板导入 1 个请求"))
            return
        nodes, _fmt, err = parse_text(text, fallback_name=i18n.tr("剪贴板集合"))
        if err or not nodes:
            self.toast_hint(err or i18n.tr("剪贴板内容不是可识别的集合"))
            return
        self._last_name = nodes[0].get("name", "") if len(nodes) == 1 else ""
        self.store.collections.extend(nodes)
        self.store.save()
        total = count_requests(nodes)
        self.imported.emit(total)
        self.toast_hint(i18n.trf("已从剪贴板导入 {n} 个请求", n=total))

    def toast_hint(self, text: str) -> None:
        """就地反馈：对话框自己太小，不弹全局 toast，直接显示在列表下方。"""
        self.file_title.setText(i18n.tr("从剪贴板导入"))
        self.file_desc.setText(text)
        self.file_status.setText("")
        self._show_page("file")
        self._show_zone(False)
        QTimer.singleShot(1200, self._restore_clipboard_page)

    def _restore_clipboard_page(self) -> None:
        try:
            self._show_zone(True)
            self._show_page("import")
        except RuntimeError:      # 对话框已经被关掉
            return

    # -------------------------------------------------- 页面 3：导出
    def _build_export(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # 顶部一行：这次会导出什么（几个集合、几个请求），心里有数再点
        self.export_summary = Label("", 11.2, theme().text_faint)
        self.export_summary.setContentsMargins(16, 8, 16, 2)
        outer.addWidget(self.export_summary)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(14, 4, 14, 12)
        lay.setSpacing(2)
        self.export_rows = []
        for key, title, desc in self._export_targets:
            row = TransferRow("grid" if key == "ocelot" else
                              ("code" if key.startswith("openapi") else "download"),
                              title, desc)
            row.clicked.connect(lambda k=key: self._do_export(k))
            lay.addWidget(row)
            self.export_rows.append(row)
        lay.addStretch(1)
        scroll = SmoothScrollArea()
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        note = QWidget()
        note.setObjectName("NoteBox")
        note.setStyleSheet(
            f"#NoteBox {{ border: 1px solid {theme().warning}; border-radius: 9px; }}")
        nl = QHBoxLayout(note)
        nl.setContentsMargins(12, 10, 12, 10)
        nl.setSpacing(10)
        icon = QLabel()
        icon.setFixedSize(16, 16)
        icon.setPixmap(icons.pixmap("alert", theme().warning, 15, 1.4))
        text = Label(
            "Ocelot JSON 与 Postman v2.1 是通用格式，别的工具可以直接导入；"
            "OpenAPI 导出会丢失脚本、认证凭据、未启用的请求项、重复路径与重复响应码。",
            10.8, theme().text_dim)
        text.setWordWrap(True)
        nl.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        nl.addWidget(text, 1)
        bottom = QWidget()
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(14, 0, 14, 14)
        bl.setSpacing(8)
        self.export_status = Label("", 10.8, theme().text_faint, mono_font=True)
        self.export_status.setWordWrap(True)
        bl.addWidget(self.export_status)
        bl.addWidget(note)
        back = Button("返回", "chevron_left", kind="ghost", height=30, padding=12, font_size=12)
        back.clicked.connect(self._go_back)
        bl.addWidget(HBox(1, back, spacing=6))
        outer.addWidget(bottom)
        return page

    def _refresh_export_summary(self) -> None:
        from .transfer import count_requests

        total = count_requests(self.store.collections)
        folders = len(self.store.collections)
        if total:
            self.export_summary.setText(i18n.trf(
                "将导出 {f} 个集合、{n} 个请求", f=folders, n=total))
            for row in getattr(self, "export_rows", []):
                row.setEnabled(True)
                row.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.export_summary.setText(i18n.tr("还没有可导出的请求：先新建或导入一个集合"))
            for row in getattr(self, "export_rows", []):
                row.setEnabled(False)
                row.setCursor(Qt.CursorShape.ArrowCursor)

    def _show_export_done(self, path: str, size: int, key: str) -> None:
        from pathlib import Path

        from .transfer import EXPORT_TARGETS

        name = Path(path).name
        target = next((t for k, t, _d in EXPORT_TARGETS if k == key), "")
        self._done_title = i18n.tr("导出完成")
        self._done_height = 396
        self.done.reset(i18n.trf("已导出 {name}", name=name),
                        i18n.trf("{target} · {size}", target=i18n.tr(target),
                                 size=_size_text(size)),
                        i18n.tr("完成"), i18n.tr("在文件夹中显示"))
        self.done.secondary.show()
        self.done.secondary.set_icon("folder")
        try:
            self.done.secondary.clicked.disconnect()
        except TypeError:
            pass
        self.done.secondary.clicked.connect(lambda: self._reveal(path))
        for icon_name, label, value in (
            ("file", i18n.tr("文件名"), name),
            ("download", i18n.tr("大小"), _size_text(size)),
            ("folder", i18n.tr("位置"), _short_path(str(Path(path).parent))),
        ):
            self.done.add_row(icon_name, label, value)
        self._show_page("done")

    def _reveal(self, path: str) -> None:
        import subprocess
        import sys

        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            elif os.name == "nt":
                subprocess.Popen(["explorer", "/select,", path])
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
        except Exception:      # noqa: BLE001
            pass

    def _export_stem(self) -> str:
        """导出默认文件名：就一个集合时用集合（目录）名，否则用最近导入的名字。"""
        import re

        names = [str(c.get("name") or "").strip() for c in self.store.collections
                 if str(c.get("name") or "").strip()]
        stem = names[0] if len(names) == 1 else (self._last_name or "")
        stem = re.sub(r'[\\/:*?"<>|\n\r\t]+', "-", stem).strip(" .-")
        return stem[:60] or "ocelot-collection"

    def _do_export(self, key: str) -> None:
        from .transfer import EXT, to_har, to_ocelot, to_openapi, to_postman, to_yaml

        default = self._export_stem() + EXT.get(key, ".json")
        suffix = "YAML (*.yaml)" if key == "openapi-yaml" else (
            "HAR (*.har)" if key == "har" else "JSON (*.json)")
        path, _ = QFileDialog.getSaveFileName(self, i18n.tr("导出集合"), default, suffix)
        if not path:
            return
        if key == "openapi-yaml" and not path.lower().endswith((".yaml", ".yml")):
            path += ".yaml"
        try:
            if key == "ocelot":
                text = json.dumps(to_ocelot(self.store), ensure_ascii=False, indent=2)
            elif key == "postman":
                text = json.dumps(to_postman(self.store), ensure_ascii=False, indent=2)
            elif key == "openapi-json":
                text = json.dumps(to_openapi(self.store), ensure_ascii=False, indent=2)
            elif key == "openapi-yaml":
                text = to_yaml(to_openapi(self.store))
            else:
                text = json.dumps(to_har(self.store), ensure_ascii=False, indent=2)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception as exc:  # noqa: BLE001
            self.export_status.setText(i18n.trf("✕ 导出失败：{err}", err=exc))
            self.export_status.setStyleSheet(f"color: {theme().danger}; background: transparent;")
            return
        self._show_export_done(path, len(text.encode("utf-8")), key)

    # -------------------------------------------------- 导航
    def _show_page(self, key: str) -> None:
        self.stack.set_current(key)
        self.back_btn.setVisible(key not in ("import", "done"))
        titles = {"import": "导入导出", "file": "导入集合", "export": "导出集合",
                  "done": self._done_title or "完成"}
        self._title_label.setText(i18n.tr(titles.get(key, "集合")))
        # 高度跟着内容走：列表页最高，选文件 / 导出页短一些，免得中间空一大块
        if key == "export":
            self._refresh_export_summary()
        height = {"import": 660, "file": 430, "export": 486,
                  "done": self._done_height}.get(key, 620)
        if key == "import":
            # 列表页按内容算高度：多出来的几十像素以前全堆成底部一条空白
            page = self.stack._pages.get("import")
            if page is not None:
                height = page.sizeHint().height() + self.header.height() + 1
        # 小屏上别让窗口比屏幕还高（矮屏笔记本 768 高度很常见）
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            height = min(height, max(360, screen.availableGeometry().height() - 80))
        if self.height() != height:
            self.resize(self.width(), height)

    def _go_back(self) -> None:
        self._show_page("import")

    # -------------------------------------------------- 拖放
    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        for url in e.mimeData().urls():
            path = url.toLocalFile()
            if path:
                if self.stack.current() != "file":
                    self._choose_source("ocelot")
                self._load_path(path)
                break

    def refresh_theme(self) -> None:
        for row in self.findChildren(TransferRow):
            row.refresh_theme()
        note = self.findChild(QWidget, "NoteBox")
        if note is not None:
            note.setStyleSheet(
                f"#NoteBox {{ border: 1px solid {theme().warning}; border-radius: 9px; }}")


def export_folder(store: Store, node: Dict[str, Any], parent=None,
                  pos=None) -> str:
    """文件夹右键 → 导出这一个文件夹（含子文件夹），返回写出的路径。

    和「导出全部集合」共用同一套格式与命名规则，只是把导出范围收窄到这一个
    节点 —— 导出的文件里仍然是一个同名文件夹，导回来结构不会散。
    """
    import json
    import re
    from pathlib import Path

    from .transfer import EXT, count_requests, to_har, to_ocelot, to_openapi, to_postman, to_yaml

    if not isinstance(node, dict):
        return ""
    total = count_requests([node])
    title = i18n.tr("导出集合")
    targets = [
        ("ocelot", i18n.tr("导出为 Ocelot JSON"), "grid"),
        ("postman", i18n.tr("导出为 Postman v2.1"), "send"),
        ("openapi-json", i18n.tr("导出为 OpenAPI 3.1 (JSON)"), "code"),
        ("openapi-yaml", i18n.tr("导出为 OpenAPI 3.1 (YAML)"), "code"),
        ("har", i18n.tr("导出为 HAR"), "download"),
    ]
    menu = Menu(parent)
    head = menu.addAction(icons.icon("folder", theme().text_faint, 13),
                          i18n.trf("{name} · {n} 个请求", name=node.get("name") or "", n=total))
    head.setEnabled(False)
    menu.addSeparator()
    acts = {}
    for key, label, icon_name in targets:
        acts[menu.addAction(icons.icon(icon_name, theme().text, 13), label)] = key
    anchor = pos if pos is not None else None
    chosen = menu.exec(anchor) if anchor is not None else menu.exec()
    key = acts.get(chosen)
    if not key:
        return ""
    stem = re.sub(r'[\\/:*?"<>|\n\r\t]+', "-", (node.get("name") or "").strip()).strip(" .-")
    default = (stem[:60] or "folder") + EXT.get(key, ".json")
    suffix = "YAML (*.yaml)" if key == "openapi-yaml" else (
        "HAR (*.har)" if key == "har" else "JSON (*.json)")
    path, _ = QFileDialog.getSaveFileName(parent, title, default, suffix)
    if not path:
        return ""
    if key == "openapi-yaml" and not path.lower().endswith((".yaml", ".yml")):
        path += ".yaml"
    try:
        if key == "ocelot":
            text = json.dumps(to_ocelot(store, stem or "folder", nodes=[node]),
                              ensure_ascii=False, indent=2)
        elif key == "postman":
            text = json.dumps(to_postman(store, stem or "folder", nodes=[node]),
                              ensure_ascii=False, indent=2)
        elif key == "openapi-json":
            text = json.dumps(to_openapi(store, stem or "folder", nodes=[node]),
                              ensure_ascii=False, indent=2)
        elif key == "openapi-yaml":
            text = to_yaml(to_openapi(store, stem or "folder", nodes=[node]))
        else:
            text = json.dumps(to_har(store, stem or "folder", nodes=[node]),
                              ensure_ascii=False, indent=2)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except Exception:  # noqa: BLE001
        return ""
    return str(Path(path))
