"""全局快捷键注册表：一张表定义所有动作、默认键位、显示与录制。

为什么单独一层：
- 主窗口只负责「把表变成 QShortcut」，设置页只负责「把表画成可录制的行」，
  两边共用同一份 `ACTIONS`，不会出现「页面里写 ⌘K、实际绑的是别的」；
- 用户改过的键位存进 `settings["shortcuts"]`，只存差异，缺的回落默认值，
  以后新增动作也不会因为旧配置缺键而失效；
- 清空键位 = 存空字符串，主窗口跳过它，等于关掉这个快捷键。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence

# (id, 名称, 分组, 默认键位)
ACTIONS: List[Tuple[str, str, str, str]] = [
    ("new_request", "新建请求", "请求", "Meta+N"),
    ("send", "发送当前请求", "请求", "Meta+Return"),
    ("save", "保存到集合", "请求", "Meta+S"),
    ("duplicate", "复制当前请求", "请求", "Meta+D"),
    ("close_tab", "关闭当前标签", "标签", "Meta+W"),
    ("next_tab", "下一个标签", "标签", "Ctrl+Tab"),
    ("prev_tab", "上一个标签", "标签", "Ctrl+Shift+Tab"),
    ("palette", "命令面板", "界面", "Meta+K"),
    ("find", "在响应中查找", "界面", "Meta+F"),
    ("toggle_sidebar", "显示 / 隐藏侧栏", "界面", "Meta+B"),
    ("code", "生成代码片段", "工具", "Meta+Shift+C"),
    ("doc", "查看接口文档", "工具", "Meta+Shift+D"),
    ("mock", "Mock 服务", "工具", "Meta+Shift+M"),
    ("env", "环境变量", "工具", "Meta+E"),
    ("run_collection", "运行整个集合", "工具", "Meta+Shift+R"),
    ("settings", "打开设置", "应用", "Meta+,"),
]

GROUP_ORDER = ["请求", "标签", "界面", "工具", "应用"]

# 修饰键（Qt 字符串）→ 展示符号
_MOD_SYMBOLS = {
    "meta": "⌘", "ctrl": "⌃", "control": "⌃", "alt": "⌥", "shift": "⇧",
}
_SPECIAL = {
    "return": "↵", "enter": "↵", "escape": "Esc", "esc": "Esc", "backspace": "⌫",
    "delete": "⌦", "tab": "⇥", "space": "Space", "pageup": "PgUp",
    "pagedown": "PgDn", "home": "Home", "end": "End",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
    "plus": "+", "minus": "-", "comma": ",", "period": ".", "slash": "/",
    "backslash": "\\", "semicolon": ";", "apostrophe": "'", "bracketleft": "[",
    "bracketright": "]", "quoteleft": "`", "equal": "=",
}


def defaults() -> Dict[str, str]:
    return {key: seq for key, _name, _group, seq in ACTIONS}


def mapping(store) -> Dict[str, str]:
    """默认值 + 用户在设置里改过的键位。"""
    out = defaults()
    saved = (store.settings or {}).get("shortcuts") if store is not None else None
    if isinstance(saved, dict):
        for key in list(out):
            if key in saved and isinstance(saved[key], str):
                out[key] = saved[key]
    return out


def set_key(store, action: str, seq: str) -> None:
    saved = store.settings.setdefault("shortcuts", {})
    if not isinstance(saved, dict):
        saved = {}
        store.settings["shortcuts"] = saved
    if defaults().get(action, "") == seq:
        saved.pop(action, None)      # 等于默认值就不用存
    else:
        saved[action] = seq
    store.save()


def reset(store) -> None:
    store.settings["shortcuts"] = {}
    store.save()


def display(seq: Optional[str]) -> str:
    """'Meta+Shift+C' → '⌘ ⇧ C'；空串显示成「未设置」。"""
    if not seq:
        return "未设置"
    parts: List[str] = []
    for token in str(seq).split("+"):
        low = token.strip().lower()
        if not low:
            continue
        sym = _MOD_SYMBOLS.get(low)
        if sym:
            parts.append(sym)
            continue
        parts.append(_SPECIAL.get(low, token.strip().upper() if len(token.strip()) == 1
                                  else token.strip()))
    return " ".join(parts)


def from_event(event: QKeyEvent) -> str:
    """把一次按键录成 Qt 键位字符串；只按修饰键时返回空串。"""
    key = event.key()
    if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
               Qt.Key.Key_unknown):
        return ""
    mods = event.modifiers()
    seq = int(key)
    if mods & Qt.KeyboardModifier.ControlModifier:
        seq |= int(Qt.KeyboardModifier.ControlModifier.value)
    if mods & Qt.KeyboardModifier.ShiftModifier:
        seq |= int(Qt.KeyboardModifier.ShiftModifier.value)
    if mods & Qt.KeyboardModifier.AltModifier:
        seq |= int(Qt.KeyboardModifier.AltModifier.value)
    if mods & Qt.KeyboardModifier.MetaModifier:
        seq |= int(Qt.KeyboardModifier.MetaModifier.value)
    return QKeySequence(seq).toString(QKeySequence.SequenceFormat.PortableText)


def conflict(mapping_: Dict[str, str], seq: str, exclude: str = "") -> Optional[str]:
    """返回占用这个键位的动作名（没有冲突返回 None）。"""
    if not seq:
        return None
    for key, value in mapping_.items():
        if key != exclude and value and QKeySequence(value) == QKeySequence(seq):
            return dict((k, n) for k, n, _g, _s in ACTIONS).get(key, key)
    return None


def by_group(mapping_: Dict[str, str]) -> List[Tuple[str, List[Tuple[str, str, str]]]]:
    """[(分组, [(id, 名称, 键位)])]，按 GROUP_ORDER 排序。"""
    out: List[Tuple[str, List[Tuple[str, str, str]]]] = []
    for group in GROUP_ORDER:
        rows = [(key, name, mapping_.get(key, "")) for key, name, g, _s in ACTIONS if g == group]
        if rows:
            out.append((group, rows))
    return out


def label_of(action: str) -> str:
    for key, name, _g, _s in ACTIONS:
        if key == action:
            return name
    return action


def valid(seq: str) -> bool:
    return bool(seq) and not QKeySequence(seq).isEmpty()


def as_dict(store) -> Dict[str, Any]:
    """给自测/调试用的快照。"""
    return mapping(store)
