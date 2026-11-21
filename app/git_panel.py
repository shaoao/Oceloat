"""Git 同步与 Diff：把集合导出到一个文件夹（可以是 git 仓库），看「这次改了什么」。

一个窗口三块：顶部是文件夹与分支；左侧集合列表带改动计数；右侧是请求级语义 diff。
底部一行提交说明 + 写入 / 提交。没有 git 也能用 —— 对比的是文件夹里的上一版。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QSyntaxHighlighter, QTextCharFormat
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QListWidget, \
    QListWidgetItem, QVBoxLayout

from . import gitsync, i18n
from .code_editor import CodeView, tokens
from .dialogs import GlassDialog
from .theme import C, theme
from .widgets import Button, Card, Divider, HBox, Label, Switch

_EMPTY_HINT = ("选一个文件夹（最好是 git 仓库），集合会以稳定格式的 JSON 存进去：\n"
               "键排序、去掉时间戳，git diff 只出现真正改过的地方。")
_KIND = {"added": ("+", "新增"), "removed": ("−", "删除"), "changed": ("~", "修改")}


class _DiffHighlighter(QSyntaxHighlighter):
    """diff 着色：增绿、删红、改黄，标题行加粗；颜色取全局 token，主题一致。"""

    def highlightBlock(self, text: str) -> None:  # noqa: N802
        t, c = theme(), tokens()
        s = text.lstrip()
        color, bold = None, False
        if text.startswith(("+ ", "− ")) and not text.startswith("    "):
            color, bold = (t.success if text[0] == "+" else t.danger), True
        elif text.startswith("~ "):
            color, bold = t.warning, True
        elif s.startswith("@@"):
            color = c["comment"]
        elif s.startswith("+"):
            color = t.success
        elif s.startswith(("-", "−")):
            color = t.danger
        elif s.startswith("~"):
            color = t.warning
        elif text.startswith("  ") and s.endswith("："):
            color = t.text_dim
        if color:
            fmt = QTextCharFormat()
            fmt.setForeground(C(color))
            if bold:
                fmt.setFontWeight(QFont.Weight.DemiBold)
            self.setFormat(0, len(text), fmt)


def _line(text: str) -> str:
    """diff 行里的固定说法翻一下；模板类（「模式 a → b」「pre 已修改」）拆开翻。"""
    tr = i18n.tr
    if text.startswith("模式 "):
        return tr("模式") + " " + text[3:]
    if text.endswith(" 已修改"):
        return text[:-4] + " " + tr("已修改")
    if "根目录" in text:
        text = text.replace("根目录", tr("根目录"))
    return tr(text)


def render(items: List[Dict[str, Any]]) -> str:
    tr = i18n.tr
    if not items:
        return tr("没有改动 —— 文件夹里的版本和当前集合一致。")
    out = []
    for it in items:
        mark, _ = _KIND[it["kind"]]
        out.append(f"{mark} {it['method']:<6} {it['path']}{it['name'] or tr('(未命名)')}")
        for ch in it["changes"]:
            out.append(f"  {tr(ch['label'])}：" if i18n.current() == "zh"
                       else f"  {tr(ch['label'])}:")
            out.extend("    " + _line(ln) for ln in ch["lines"])
        out.append("")
    return "\n".join(out).rstrip()


class GitDialog(GlassDialog):
    BLUR_FIXED = True

    def __init__(self, store, parent=None, focus_id: str = ""):
        super().__init__(parent, 860, 580, i18n.tr("Git 同步与 Diff"))
        self.store = store
        self._diffs: Dict[str, List[Dict[str, Any]]] = {}
        t = theme()

        self.dir_label = Label("", 11.5, t.text_dim, mono_font=True)
        self.branch = Label("", 10.5, t.text_faint, mono_font=True)
        pick = Button("选择文件夹", "folder", kind="subtle", height=26, padding=10, font_size=11.5)
        pick.clicked.connect(self._pick)
        self.auto = Switch(bool(self._cfg().get("auto")))
        self.auto.toggled.connect(self._toggle_auto)
        top = HBox(self.dir_label, self.branch, 1, Label("保存时自动写入", 11, t.text_faint),
                   self.auto, pick, spacing=8)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list_card = Card(radius=9)
        ll = QVBoxLayout(self.list_card)
        ll.setContentsMargins(4, 6, 4, 6)
        ll.addWidget(self.list)
        self.list_card.setFixedWidth(220)

        class _View(CodeView):
            TRANSPARENT = True

        self.view = _View(read_only=True, highlight=False, show_gutter=False, wrap=True)
        self._hl = _DiffHighlighter(self.view.document())
        frame = Card(radius=9)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(0, 6, 0, 6)
        fl.addWidget(self.view)
        mid = QHBoxLayout()
        mid.setSpacing(10)
        mid.addWidget(self.list_card)
        mid.addWidget(frame, 1)

        self.msg = QLineEdit()
        self.msg.setObjectName("Field")
        self.msg.setFixedHeight(30)
        i18n.placeholder(self.msg, "提交说明（留空自动生成）")
        self.write_btn = Button("写入文件夹", "download", kind="ghost", height=30, padding=12,
                                font_size=12, tooltip="只导出文件，不提交")
        self.write_btn.clicked.connect(lambda: self._write(commit=False))
        self.commit_btn = Button("提交", "check", kind="primary", height=30, padding=14,
                                 font_size=12)
        self.commit_btn.clicked.connect(lambda: self._write(commit=True))
        self.note = Label("", 10.5, t.text_faint)
        bottom = HBox((self.msg, 1), self.write_btn, self.commit_btn, spacing=6)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(10)
        lay.addWidget(top)
        lay.addWidget(Divider())
        lay.addLayout(mid, 1)
        lay.addWidget(bottom)
        lay.addWidget(self.note)
        self._focus = focus_id
        self.reload()

    # -------------------------------------------------- 配置
    def _cfg(self) -> Dict[str, Any]:
        return self.store.settings.setdefault("git", {})

    def folder(self) -> Optional[Path]:
        d = self._cfg().get("dir")
        return Path(d) if d else None

    def _pick(self) -> None:
        start = str(self.folder() or Path.home())
        path = QFileDialog.getExistingDirectory(self, i18n.tr("选择存放集合的文件夹"), start)
        if path:
            self._cfg()["dir"] = path
            self.store.save()
            self.reload()

    def _toggle_auto(self, on: bool) -> None:
        self._cfg()["auto"] = bool(on)
        self.store.save()

    # -------------------------------------------------- 数据
    def _baseline(self, folder: Path, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        path = gitsync.find_file(folder, node.get("id") or "")
        if path is None:
            return None
        text = gitsync.show_at(folder, "HEAD", path)
        if text is None:
            try:
                text = path.read_text("utf-8")
            except OSError:
                return None
        return gitsync.loads(text)

    def reload(self) -> None:
        folder = self.folder()
        self.list.clear()
        self._diffs.clear()
        if folder is None:
            self.dir_label.setText(i18n.tr("还没选文件夹"))
            self.branch.setText("")
            self.view.setPlainText(i18n.tr(_EMPTY_HINT))
            self.list_card.hide()
            self.msg.setEnabled(False)
            self._enable(False)
            return
        self.list_card.show()
        self.msg.setEnabled(True)
        self.dir_label.setText(str(folder).replace(str(Path.home()), "~"))
        has_git = gitsync.is_repo(folder)
        br = gitsync.branch(folder) if has_git else ""
        self.branch.setText(f"⎇ {br}" if br else i18n.tr("未初始化 git" if gitsync.git_path()
                                                          else "未检测到 git · 对比上次写入"))
        self.commit_btn.setVisible(gitsync.git_path() is not None)
        total = 0
        pick_row = 0
        for i, node in enumerate(self.store.collections):
            base = self._baseline(folder, node)
            diff = gitsync.semantic_diff(base, node) if base is not None else \
                gitsync.semantic_diff({"children": []}, node)
            self._diffs[node["id"]] = diff
            st = gitsync.stats(diff)
            n = sum(st.values())
            total += n
            tag = "  " + i18n.tr("新") if base is None else (f"  {n}" if n else "")
            item = QListWidgetItem(f"{node.get('name') or i18n.tr('集合')}{tag}")
            item.setData(Qt.ItemDataRole.UserRole, node["id"])
            item.setForeground(C(theme().text if n or base is None else theme().text_faint))
            self.list.addItem(item)
            if node.get("id") == self._focus or (not self._focus and n and not pick_row):
                pick_row = i
        if self.list.count():
            self.list.setCurrentRow(pick_row)
        self.note.setText(i18n.trf("共 {n} 处改动", n=total) if total else i18n.tr("全部已同步"))
        self._enable(True)

    def _enable(self, on: bool) -> None:
        self.write_btn.setEnabled(on)
        self.commit_btn.setEnabled(on)

    def _current_id(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _show(self) -> None:
        diff = self._diffs.get(self._current_id())
        if diff is None:
            return
        st = gitsync.stats(diff)
        head = "  ".join(f"{i18n.tr(_KIND[k][1])} {v}" for k, v in st.items() if v)
        self.view.setPlainText((head + "\n\n" if head else "") + render(diff))

    # -------------------------------------------------- 写入 / 提交
    def _auto_message(self) -> str:
        parts = []
        for node in self.store.collections:
            st = gitsync.stats(self._diffs.get(node["id"]) or [])
            bits = [f"{_KIND[k][0]}{v}" for k, v in st.items() if v]
            if bits:
                parts.append(f"{node.get('name') or 'collection'} ({' '.join(bits)})")
        return "Ocelot: " + ("; ".join(parts[:4]) if parts else "sync collections")

    def _write(self, commit: bool) -> None:
        folder = self.folder()
        if folder is None:
            return
        msg = self.msg.text().strip() or self._auto_message()
        paths = [gitsync.write(folder, node) for node in self.store.collections]
        if commit:
            ok, out = gitsync.commit(folder, paths, msg)
            self.note.setText(("✓ " if ok else "✕ ") + i18n.tr(out or msg))
            if ok:
                self.msg.clear()
        else:
            self.note.setText(i18n.trf("✓ 已写入 {n} 个文件", n=len(paths)))
        self.reload()

