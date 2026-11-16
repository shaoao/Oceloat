"""轻量级中英双语。

设计：以「中文原文」为 key，英文译文为 value。界面里所有可见文案统一走 tr()，
没登记的字符串原样返回（中文），因此即使翻译表不全也不会出错、不会退化成乱码。
语言切换后发 languageChanged 信号，主窗口重建界面文本。
"""
from __future__ import annotations

from typing import Dict

from PyQt6.QtCore import QObject, pyqtSignal

_LANG = "zh"          # zh / en
_LISTENERS: list = []


class LanguageBus(QObject):
    languageChanged = pyqtSignal(str)


_bus = LanguageBus()


def current() -> str:
    return _LANG


def set_language(lang: str, notify: bool = True) -> None:
    global _LANG
    lang = "en" if lang in ("en", "English", "english") else "zh"
    if lang == _LANG:
        return
    _LANG = lang
    if notify:
        _bus.languageChanged.emit(lang)


def tr(text: str) -> str:
    """翻译一段界面文案。未登记时原样返回。"""
    if _LANG == "zh":
        return text
    return _EN.get(text, text)


def connect(fn) -> None:
    """注册语言切换回调（供不能接收信号的旧代码用）。"""
    _bus.languageChanged.connect(fn)


def bus() -> LanguageBus:
    return _bus


def _translate_object(obj) -> None:
    """翻译一个 QObject 上所有可显示的文本。原文记在动态属性里，方便来回切换。"""
    from PyQt6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QMenu, QToolButton

    def set_src(text_attr: str, getter, setter):
        try:
            cur = getter()
        except Exception:  # noqa: BLE001
            return
        if not isinstance(cur, str) or not cur:
            return
        # 第一次记录原文（中文）
        src = obj.property("i18n_src_" + text_attr)
        if src is None:
            if _LANG == "zh":
                obj.setProperty("i18n_src_" + text_attr, cur)
                return
            src = cur
        setter(tr(src))

    if isinstance(obj, QLabel):
        set_src("text", obj.text, obj.setText)
    elif isinstance(obj, (QAbstractButton, QToolButton)):
        set_src("text", obj.text, obj.setText)
    elif isinstance(obj, QLineEdit):
        ph = obj.placeholderText()
        if ph:
            src = obj.property("i18n_src_ph")
            if src is None:
                if _LANG == "zh":
                    obj.setProperty("i18n_src_ph", ph)
                else:
                    obj.setProperty("i18n_src_ph", ph)
                    obj.setPlaceholderText(tr(ph))
            elif _LANG == "en":
                obj.setPlaceholderText(tr(src))
            else:
                obj.setPlaceholderText(src)
    elif isinstance(obj, QMenu):
        set_src("title", obj.title, obj.setTitle)


def apply_language(root) -> None:
    """遍历控件树应用当前语言。可反复调用，来回切换不失真。"""
    from PyQt6.QtCore import QObject

    seen = set()
    stack = [root]
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        _translate_object(obj)
        try:
            for child in obj.children():
                if isinstance(child, QObject):
                    stack.append(child)
        except RuntimeError:  # noqa: BLE001
            continue


# ------------------------------------------------------------------ 英文译文
# 只列界面上真实出现的字符串；保持自然、地道的英文（不是机翻腔）。
_EN: Dict[str, str] = {
    # 通用
    "设置": "Settings", "设置…": "Settings…", "环境变量": "Environment", "环境变量…": "Environment…",
    "取消": "Cancel", "确定": "OK", "完成": "Done", "保存": "Save", "删除": "Delete",
    "关闭": "Close", "添加": "Add", "新建": "New", "打开": "Open", "复制": "Copy",
    "粘贴": "Paste", "撤销": "Undo", "重做": "Redo", "全选": "Select All",
    "全选/取消": "Select All / None", "复制值": "Copy Value", "返回": "Back",
    "导入": "Import", "导出": "Export", "刷新": "Refresh", "重命名": "Rename",
    "重试": "Retry", "更多": "More", "搜索": "Search",

    # 顶栏 / 菜单
    # 欢迎页
    "为 macOS 打造的轻量 API 调试工具": "A lightweight API debugger crafted for macOS",
    "从空白标签页开始": "Start from a blank tab", "打开命令面板": "Open Command Palette",
    "搜索请求或快速执行命令": "Search requests or run a command quickly",
    "配置环境变量": "Configure Environments", "用 {{变量}} 在环境间切换": "Switch environments with {{variables}}",
    "⌘↵ 发送   ·   ⌘S 保存   ·   ⌘B 侧边栏": "⌘↵ Send   ·   ⌘S Save   ·   ⌘B Sidebar",

    "API Client": "API Client", "导入 cURL…": "Import cURL…",
    "导入集合…": "Import Collection…", "导出集合…": "Export Collection…",
    "退出 Ocelot": "Quit Ocelot", "切换浅色 / 深色": "Switch Light / Dark",
    "隐藏侧栏  ⌘B": "Hide Sidebar  ⌘B", "显示侧栏  ⌘B": "Show Sidebar  ⌘B",
    "命令面板  ⌘K": "Command Palette  ⌘K",

    # 侧栏
    "集合": "Collections", "历史": "History", "搜索请求、URL 或方法": "Search requests, URLs or methods",
    "从本机发出": "Sent from this machine", "新建请求": "New Request", "新建文件夹": "New Folder",
    "清空历史": "Clear History",
    "清空历史": "Clear History", "无历史记录": "No history yet", "本地": "Local",
    "Untitled Request": "Untitled Request", "New Folder": "New Folder",

    # 请求编辑
    "参数": "Params", "请求头": "Headers", "请求体": "Body", "认证": "Auth",
    "Cookies": "Cookies", "Cookie 名": "Cookie name", "添加 Cookie": "Add a cookie",
    "参数名": "Key", "值": "Value", "查询参数": "Query parameters",
    "描述（可选）": "Description (optional)", "描述（可选，不发送）": "Description (optional, not sent)",
    "粘贴": "Paste", "批量编辑": "Bulk Edit", "未选择文件": "No file chosen",
    "运行集合": "Run collection", "个请求": "requests", "开始运行": "Run",
    "停止": "Stop", "再跑一次": "Run again", "重新运行": "Run again",
    "复制结果": "Copy results", "运行中": "Running", "待运行": "Pending",
    "成功": "passed", "失败": "failed", "总耗时": "total",
    "这个文件夹里还没有请求": "No requests in this folder yet",
    "主题色": "Accent color",
    "主按钮、开关、勾选框、发送键、选中态与强调文字一起换色；「自动」是黑白反色。":
        "Recolors primary buttons, switches, checkboxes, Send, selections and accented text; Auto keeps the plain inverse.",
    "云同步…": "Cloud Sync…",
    "海蓝": "Blue", "松青": "Teal", "苔绿": "Green", "陶橙": "Amber", "绯红": "Rose", "藤紫": "Violet",
    "存为变量": "Save as variable", "变量名（用 {{名字}} 引用）": "Variable name (reference it as {{name}})",
    "分栏已恢复 50 / 50": "Layout reset to 50 / 50", "运行当前请求所在的集合": "Run collection",
    "请选择要运行的集合文件夹": "Pick a collection folder to run",
    "发送": "Send", "取消": "Cancel", "保存": "Save", "发送中…": "Sending…",
    "Content-Type: JSON": "Content-Type: JSON",

    # 响应
    "美化": "Pretty", "树形": "Tree", "原始": "Raw", "响应头": "Headers",
    "预览": "Preview", "对比": "Compare", "提取": "Extract",
    "全部展开": "Expand All", "全部折叠": "Collapse All", "自动换行": "Word Wrap",
    "准备就绪": "Ready to go", "填写请求地址后发送，响应会显示在这里": "Enter a URL and send — the response will appear here",
    "⌘ ↵ 发送": "⌘ ↵ to send", "正在等待响应…": "Waiting for response…",
    "请求失败": "Request Failed", "无响应头": "No response headers",
    "本次响应未设置 Cookie": "No cookies were set in this response",
    "已复制到剪贴板": "Copied to clipboard", "复制响应体": "Copy response body",
    "另存为…": "Save As…", "在响应中查找  ⌘F": "Find in response  ⌘F",
    "设为基准": "Set as Baseline", "复制值": "Copy Value",

    # 设置页
    "通用": "General", "外观": "Appearance", "网络": "Network",
    "数据": "Data", "关于 Ocelot": "About Ocelot", "更新内容": "What's New",
    "云同步": "Cloud Sync", "启用云同步": "Enable Cloud Sync", "数据库地址": "Database URL",
    "Auth Token": "Auth Token", "连通性": "Connectivity", "测试连接": "Test Connection",
    "上传到云端": "Upload", "从云端恢复": "Restore from Cloud", "手动同步": "Manual Sync",
    "退出时自动上传": "Upload on Quit", "尚未测试": "Not tested yet",
    "用 Turso 做一份你自己的云备份 —— 不需要注册第三方账号体系。":
        "Keep your own cloud backup on Turso — no third-party account needed.",
    "从响应导入": "Import from Response", "发送时合并成 Cookie 请求头": "Merged into the Cookie header on send",
    "启动行为与编辑习惯。": "Startup behavior and editing habits.",
    "自动命名请求": "Auto-name Requests",
    "按 URL 末段自动给请求命名，重命名后不再覆盖。": "Name new requests from the last URL segment; manual renames are kept.",
    "记住窗口与分栏": "Restore Window Layout",
    "下次启动恢复打开的标签、侧栏与上下分栏比例。": "Restore open tabs, sidebar and split ratio on next launch.",
    "命令面板": "Command Palette", "发送请求": "Send Request", "保存到集合": "Save to Collection",
    "在响应中查找": "Find in Response", "切换侧栏": "Toggle Sidebar",
    "配色、主题色、动效与字号，改动立即生效。":
        "Palette, accent color, motion and font size — changes apply instantly.",
    "配色方案": "Color Scheme", "界面动效": "Animations",
    "关闭后页面切换、悬停与响应到达不再播放动画。": "Turn off to disable page, hover and response animations.",
    "代码字号": "Code Font Size", "响应体、请求体与代码片段的等宽字体大小。": "Monospace font size for responses, bodies and snippets.",
    "预览": "Preview", "次按钮": "Secondary", "文字按钮": "Text Button",
    "超时、跳转、证书与代理。": "Timeouts, redirects, certificates and proxies.",
    "请求超时": "Request Timeout", "单位秒，0 表示不限制。": "In seconds; 0 means no limit.",
    "秒": "s", "跟随重定向": "Follow Redirects", "自动跟随 3xx 跳转到最终地址。": "Automatically follow 3xx redirects.",
    "校验 SSL 证书": "Verify SSL Certificates", "关闭后可用于自签名证书的调试环境。": "Disable for debugging with self-signed certificates.",
    "网络代理": "Proxy", "自动": "Auto", "系统": "System", "直连": "Direct",
    "自动：优先读环境变量代理，其次系统代理；本地地址始终直连。": "Auto: env vars first, then system proxy; localhost always direct.",
    "默认 User-Agent": "Default User-Agent", "请求没带 UA 时使用（部分接口会按 UA 限流）。": "Used when a request has no UA (some APIs throttle by UA).",
    "环境变量": "Environment Variables",
    "{{变量}} 会按当前激活的环境替换。": "{{variables}} are replaced using the active environment.",
    "本地数据": "Local Data", "历史记录上限": "History Limit",
    "清空历史": "Clear History", "只删历史记录，集合与环境变量不受影响。": "Only removes history — collections and environments are untouched.",
    "条": "entries", "超出后自动丢弃最旧的。": "Oldest entries are dropped automatically.",
    "所有数据都是本地纯 JSON，可直接备份或版本管理。": "All data is plain local JSON — easy to back up or version.",
    "打开数据目录": "Open Data Folder",
    "语言": "Language", "界面显示语言，切换后立即生效。": "Interface language; changes apply instantly.",
    "简体中文": "简体中文", "English": "English",

    # 关于
    "一款把请求调试做得干净、安静的本地桌面工具。": "A calm, local desktop tool for debugging HTTP requests.",
    "功能与修复": "What's Changed", "按版本记录每一次界面重做、修复与新能力。": "Every redesign, fix and new capability, version by version.",
    "查看更新内容": "View What's New",
    "本地数据": "Local Data", "请求、集合与设置只保存在本机，不上传。": "Requests, collections and settings stay on this machine.",

    # Toast / 提示
    "请先填写请求地址": "Please enter a request URL first",
    "已保存到集合": "Saved to collection", "已新建文件夹": "Folder created",
    "已切换环境": "Environment switched", "环境变量已更新": "Environment variables updated",
    "请求超时": "Request timed out", "请求已取消": "Request cancelled",
    "响应已保存": "Response saved", "图片已保存": "Image saved",

    # 菜单分组
    "新功能": "Features", "改进": "Improvements", "修复": "Fixes",

    # 响应详情卡
    "响应时间": "Response Time", "响应大小": "Response Size", "请求大小": "Request Size",
    "准备": "Prepare", "Socket 初始化": "Socket Init", "DNS 查询": "DNS Lookup",
    "TCP 握手": "TCP Handshake", "SSL 握手": "SSL Handshake",
    "等待中 (TTFB)": "Waiting (TTFB)", "下载内容": "Content Download", "处理": "Processing",
    "Header": "Header", "Body": "Body",

    # 节点
    "节点": "Node", "测速": "Speed Test", "刷新节点": "Refresh Nodes", "拉取中…": "Fetching…",
    "本地直连": "Direct (Local)", "已载入": "Loaded", "个节点": "nodes",
    "仅测速": "Latency only", "超时": "Timeout", "无可测速节点": "No nodes to test",
    "速度仅供参考，不代表节点可用性与整体请求速度。": "Latency is indicative only — it does not reflect availability or overall request speed.",
}
