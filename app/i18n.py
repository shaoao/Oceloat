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


def trf(template: str, **kwargs) -> str:
    """带占位的文案：模板与参数分别翻译，再拼起来。

    像「设置 · 环境变量」「默认 ⌘N」这种由两段拼成的界面文字，整句没有词条，
    直接把拼接结果丢进 tr() 会原样返回中文。用模板走词条、参数各自翻译最稳。
    模板里有字面量花括号（{{变量}}）时不要用这个函数。
    """
    tpl = tr(template) if "{" in template else template
    try:
        return tpl.format(**{k: (tr(v) if isinstance(v, str) else v) for k, v in kwargs.items()})
    except (KeyError, IndexError, ValueError):
        return template



def placeholder(widget, text: str) -> None:
    """给输入框设置「可跟着语言切换」的占位文字。

    直接把 tr() 的结果塞进去，切回中文时原文就丢了（英文没法反查回中文）；
    这里把中文原文记在属性上，apply_language 之后就能来回切。
    """
    widget.setProperty("i18n_src_ph", text)
    widget.setPlaceholderText(tr(text))


def connect(fn) -> None:
    """注册语言切换回调（供不能接收信号的旧代码用）。"""
    _bus.languageChanged.connect(fn)


def bus() -> LanguageBus:
    return _bus


def _translate_object(obj) -> None:
    """翻译一个 QObject 上所有可显示的文本。原文记在动态属性里，方便来回切换。"""
    from PyQt6.QtWidgets import (
        QAbstractButton,
        QLabel,
        QLineEdit,
        QMenu,
        QPlainTextEdit,
        QTextEdit,
        QToolButton,
        QWidget,
    )

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
    elif isinstance(obj, (QPlainTextEdit, QTextEdit)):
        ph = obj.placeholderText()
        if ph:
            src = obj.property("i18n_src_ph")
            if src is None:
                obj.setProperty("i18n_src_ph", ph)
                src = ph
            obj.setPlaceholderText(tr(src))

    # 悬浮提示不在这里改：tooltip.py 画之前会过一遍 tr()，
    # 这样「语言切完才建出来的控件」也不会漏，来回切还不会把原文覆盖成英文。


def apply_language(root, visit=None) -> list:
    """遍历控件树应用当前语言。可反复调用，来回切换不失真。

    优先用 findChildren 递归拿控件 —— 自己顺着 children() 走会漏掉「后来才挂进布局」
    的那一支（比如堆叠页里的滚动内容），表现就是同一页一半英文一半中文。

    visit(widget) 可选：翻译每个控件后顺手做自绘刷新，让调用方只需遍历一次控件树。
    返回被翻译的控件列表，供调用方复用（原来主窗口要 findChildren 两遍）。
    """
    from PyQt6.QtCore import QObject
    from PyQt6.QtWidgets import QWidget

    def one(obj):
        try:
            _translate_object(obj)
            if visit is not None:
                visit(obj)
        except RuntimeError:      # 控件已经被销毁
            pass

    one(root)
    widgets = []
    if isinstance(root, QWidget):
        try:
            widgets = root.findChildren(QWidget)
        except RuntimeError:  # noqa: BLE001
            widgets = []
    if not widgets:
        seen = set()
        stack = [root]
        while stack:
            obj = stack.pop()
            if id(obj) in seen:
                continue
            seen.add(id(obj))
            one(obj)
            try:
                for child in obj.children():
                    if isinstance(child, QObject):
                        stack.append(child)
            except RuntimeError:  # noqa: BLE001
                continue
        return []
    for w in widgets:
        one(w)
    return widgets


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
    "时间线": "Timeline",
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

# 第二轮清扫：按界面逐处对照补的漏网条目（术语对齐 Postman：
# Params / Headers / Cookies / Environments / Mock Server / Collection 等保持原词）
_EN.update({
    # 顶栏 / 工具提示
    "设置与更多  ⌘,": "Settings and more  ⌘,",
    "上一个": "Previous", "下一个": "Next",
    "上一个标签": "Previous tab", "下一个标签": "Next tab",
    "关闭当前标签": "Close tab",
    "切换环境变量": "Switch environment",
    "从本机直接发出": "Sent directly from this machine",
    "保存到集合  ⌘S": "Save to collection  ⌘S",
    "发送请求  ⌘↵": "Send request  ⌘↵",
    "生成代码片段  ⌘⇧C": "Generate code snippet  ⌘⇧C",
    "更多操作": "More actions",
    "更多：生成接口文档 / 脱敏复制": "More: API docs / copy redacted",
    "响应格式：Auto / JSON / XML / HTML / Text": "Response format: Auto / JSON / XML / HTML / Text",
    "显示编码：UTF-8 / GBK / Base64 等": "Encoding: UTF-8 / GBK / Base64…",
    "从剪贴板批量导入：a=1&b=2 / 多行 key: value / JSON":
        "Bulk paste from clipboard: a=1&b=2 · lines of key: value · JSON",
    "拖动调整高度 · 双击恢复 50 / 50": "Drag to resize · double-click to reset 50 / 50",
    "最终发送的完整地址": "The full URL that will be sent",
    "选择请求方法": "Choose request method",
    "在响应中查找…": "Find in response…",
    "搜索请求，或执行命令…": "Search requests or run a command…",

    # 认证页
    "无认证": "No Auth",
    "该请求不携带任何认证凭据。": "This request is sent without any credentials.",
    "请求将以 Authorization: Bearer <token> 发送。":
        "Sent with an Authorization: Bearer <token> header.",
    "用户名与密码将进行 Base64 编码后放入 Authorization。":
        "Username and password are Base64-encoded into the Authorization header.",
    "选择一个位置注入密钥。": "Choose where the key goes.",
    "密钥值": "Key value",
    "粘贴 Bearer Token，例如 eyJhbGciOi…": "Paste a bearer token, e.g. eyJhbGciOi…",
    "类型选 File 点击即可选文件上传 · 值以 @ 开头也会按文件发送":
        "Set the type to File to pick one · values starting with @ are sent as files",

    # 响应区
    "把上一次响应里的 Set-Cookie 收进这张表":
        "Pull Set-Cookie from the last response into this table",
    "把当前响应保存为对比基准": "Use the current response as the baseline",
    "把提取到的值写进当前环境变量，之后用 {{名字}} 引用":
        "Save the extracted value into an environment variable, then reference it as {{name}}",
    "查找": "Find",
    "类型": "Type",

    # 地址栏
    "输入请求地址，例如 https://httpbin.org/get": "Enter a request URL, e.g. https://httpbin.org/get",
    "输入路径，例如 data.items[0].name  或  args.*":
        "JSON path, e.g. data.items[0].name  or  args.*",

    # 设置 · 通用
    "快捷键": "Shortcuts", "请求": "Request", "发送当前请求": "Send request",
    "复制当前请求": "Copy request", "切换侧栏": "Toggle sidebar",
    "显示 / 隐藏侧栏": "Show / hide sidebar", "打开设置": "Open settings",
    "关闭当前标签": "Close tab", "生成代码片段": "Generate code snippet",
    "查看接口文档": "View API docs", "运行整个集合": "Run collection",
    "标签": "Tabs", "界面": "Interface", "工具": "Tools", "应用": "App",
    "Mock 服务": "Mock Server",
    "默认键位": "Default shortcuts",
    "发送、搜索、切换标签等键位都可以改，也能整组恢复默认。":
        "Send, search, switch tabs and more are all rebindable — reset the whole set anytime.",
    "想怎么按就怎么按 —— 所有键位都可以改、可以清空。":
        "Bind it however you like — every shortcut can be changed or cleared.",
    "点键帽开始录制，按下新的组合键即可替换；按 esc 取消。清除后该动作只在菜单里可用。"
    "同一个键位被两个动作占用时，旧的那个会自动让位。":
        "Click a keycap and press the new combo. Esc cancels. Clearing a shortcut leaves it "
        "available only from the menu. If two actions share a combo, the older one gives way.",

    # 设置 · 外观 / 网络 / 云同步 / 数据
    "配色方案": "Color Scheme",
    "主按钮、开关、勾选框、选中态与强调文字一起换色；「自动」为黑白反色。":
        "Recolors primary buttons, switches, checkboxes, selections and accented text. "
        "Auto keeps the plain inverse.",
    "数据表：ocelot_sync（k / v / updated_at）。同一个 Token 可见范围内只有一行快照。":
        "Table: ocelot_sync (k / v / updated_at) — one snapshot row per token scope.",
    "数据库的访问令牌，只保存在本机，上传时作为 Bearer 头。":
        "Database access token. Kept locally; sent as a Bearer header on upload.",
    "Turso 控制台里的 URL（libsql:// 开头也可以，会自动换成 https）。":
        "The URL from your Turso dashboard (libsql:// works too — converted to https).",
    "把集合、环境变量与设置存到 Turso，多台机器共用同一份数据。":
        "Keep collections, environments and settings in Turso and share them across machines.",
    "先测一下再上传：只跑一条 SELECT 1，不写入任何数据。":
        "Test before uploading: runs a single SELECT 1 and writes nothing.",
    "上传会覆盖云端快照；恢复会先用云端覆盖本机（自动备份为 state.json.bak）。":
        "Upload overwrites the cloud snapshot; restore overwrites this machine first "
        "(auto-backed up to state.json.bak).",
    "关闭窗口时把最新数据推上去，适合固定一台机器当主库。":
        "Push the latest data on quit — handy when one machine is the primary.",
    "粘贴 Turso 的 Auth Token": "Paste your Turso auth token",
    "变量名区分大小写；动态变量如 {{$timestamp}} 无需定义。":
        "Variable names are case-sensitive; dynamic ones like {{$timestamp}} need no definition.",
    "激活的环境会用于替换 {{变量}}": "The active environment resolves {{variables}}",
    "变量 · Demo": "Variables · Demo",
    "每行一条：key: value\n以 # 开头的行为注释，可留空":
        "One per line: key: value\nLines starting with # are comments, blanks are fine",

    # 设置 · 关于
    "它是什么、能做什么、为什么这么做。": "What it is, what it does, and why it's built this way.",
    "把请求调试做得干净、安静的桌面工具。没有账号体系，没有遥测，数据只留在你的机器上。":
        "A calm, quiet desktop tool for debugging HTTP requests. No accounts, no telemetry — "
        "your data stays on your machine.",
    "为什么是 Ocelot": "Why Ocelot",
    "数据只在你的机器上": "Your data stays local",
    "集合、历史、环境变量都是本地 JSON。没有账号体系，没有遥测，断网也能整理接口。":
        "Collections, history and environments are plain local JSON. No account, no telemetry — "
        "works offline too.",
    "原生绘制，不是套壳浏览器": "Native rendering, not a browser shell",
    "界面全部由 QPainter 自绘，单进程、无 Electron，冷启动一秒内，大响应也不会把内存吃满。":
        "The whole UI is painted with QPainter — one process, no Electron. Cold start in under a "
        "second, and big responses don't eat your memory.",
    "一条链路做完四件事": "One request, four things done",
    "发请求 → 看响应 → 出接口文档 → 复制十种语言代码，都在一个窗口里，不用再开浏览器和编辑器。":
        "Send → read the response → generate docs → copy code in ten languages, all in one window.",
    "可以 diff 的配置": "Config you can diff",
    "状态文件是纯文本，能进 Git、能手改、能脚本生成；出了问题用编辑器就能查清。":
        "The state file is plain text: versionable, hand-editable, scriptable — readable when "
        "something goes wrong.",
    "版本": "Version", "数据目录": "Data folder",
    "数据目录 · {path}": "Data folder · {path}",
    "它能做什么": "What it does",
    "一次请求走完的流程": "How one request flows",
    "写好请求": "Write the request", "填地址与参数，变量自动换成当前环境的值":
        "Enter the URL and params; variables resolve from the active environment",
    "发请求": "Send", "发出去": "Send it",
    "看响应": "Read the response", "状态、耗时、体积、响应头、响应体一处看完":
        "Status, timing, size, headers and body in one place",
    "出文档": "Generate docs",
    "一次点击把请求与响应变成完整接口文档：概览、参数表、状态码语义、响应示例，再加上十种语言的调用代码。":
        "One click turns the request and response into full API docs: overview, parameter tables, "
        "status code meanings, examples, plus call snippets in ten languages.",
    "留下来": "Keep it", "进历史、出文档、生代码，下次直接复用":
        "History, docs and snippets — ready to reuse",
    "每次响应都进历史，能对比、能重放、能直接生成代码；集合与配置都是纯文本，可以进 Git、可以脚本生成。":
        "Every response lands in history: compare, replay, generate code. Collections and settings "
        "are plain text, so they work with Git and scripts.",
    "参数、请求头、Cookies、表单与 JSON 请求体分开填，改动即时生效；地址栏支持历史补全与变量替换。":
        "Params, headers, cookies, forms and JSON bodies each have their own tab and apply as you "
        "type. The URL bar completes from history and substitutes variables.",
    "多环境": "Environments",
    "测试 / 预发 / 线上各存一套变量，{{base_url}} 写在请求里，切换环境整组地址一起变。":
        "One variable set per environment. Write {{base_url}} in your requests and switch "
        "environments to move everything at once.",
    "可复用": "Reusable",
    "在自己电脑上起一个真服务，路由、状态码、延迟、动态字段、条件规则都能改；前端联调不用等后端排期。":
        "Run a real server locally: routes, status codes, delays, dynamic fields and conditional "
        "rules are all editable. Front-end work doesn't wait on backend scheduling.",
    "造假数据": "Generate fake data",
    "看结果": "See results",
    "整个过程不离开一个窗口，也不用把参数、响应在各处复制粘贴。":
        "The whole flow stays in one window — nothing to copy between tools.",
    "JSON 树、格式化原文、图片 / 音视频预览、响应时间线四种视角；几百 KB 的响应也是秒开，不卡滚动。":
        "Four views — JSON tree, formatted raw, image/audio/video preview and timeline. Even a few "
        "hundred KB opens instantly and scrolls smoothly.",
    "请求在后台跑，界面不冻结，随时可以取消":
        "Requests run in the background — the UI never freezes, and you can cancel anytime",

    # 设置 · 数据
    "当前 {n} 条，超出后自动丢弃最旧的。": "{n} entries right now; the oldest are dropped "
                                          "automatically once you go over the limit.",

    # Mock 中心
    "Mock 中心": "Mock Center",
    "本地 Mock 服务": "Local Mock Server",
    "启动后：请求发到 http://127.0.0.1:<端口>/<路径>，本机的浏览器、脚本、别的设备都能连。":
        "Once running, point requests at http://127.0.0.1:<port>/<path> — browsers, scripts and "
        "other devices on your network can reach it.",
    "路径末尾写 * 做前缀匹配（/api/users/*）；没匹配上的请求返回 404，并列出当前全部可用路由。"
    "响应体支持动态占位符与条件规则。":
        "End a path with * for prefix matching (/api/users/*). Unmatched requests get a 404 that "
        "lists every available route. Response bodies support dynamic placeholders and rules.",
    "端口": "Port",
    "随应用启动": "Start with the app",
    "无匹配时回显请求": "Echo the request when nothing matches",
    "搜索接口、域名或用途，例如 登录 / json / 图片":
        "Search by endpoint, domain or purpose — e.g. login / json / image",
    "还没有路由。点下面的「新建路由」，写个 /api/hello 试试。":
        "No routes yet. Hit New Route below and try /api/hello.",
    "还没有请求": "No requests yet",
    "还没有请求。启动本地服务后，任何打到它的请求都会出现在这里 —— 包括方法、路径、状态码、耗时，"
    "以及命中了哪条规则。":
        "No requests yet. Once the server is running, everything that hits it shows up here — "
        "method, path, status, duration, and which rule matched.",
    "{n} 条路由": "{n} routes",
    "编辑": "Edit", "删除": "Delete",
    "复制完整地址": "Copy full URL",
    "用这条路由新建请求": "New request from this route",
    "新建环境": "New environment", "删除环境": "Delete environment",
    "… 还有 {n} 项": "… {n} more", "共": "total", "次": "hits", "平均": "avg", "最近一条": "last",
    "次数": "Count", "成功率": "Success", "最慢": "Slowest", "关闭换行": "No Wrap",
    "cURL 命令已复制到剪贴板": "cURL command copied to clipboard",
    "先打开一条请求": "Open a request first",
    "先选中一个集合文件夹，或打开集合里的请求":
        "Select a collection folder, or open a request first",
    "历史已清空": "History cleared",
    "已从 cURL 导入，⌘S 可保存到集合": "Imported from cURL — ⌘S to save it into a collection",
    "已创建副本": "Duplicate created",
    "已创建请求": "Request created",
    "已填入 Mock 请求，按 ⌘↵ 发送": "Mock request filled in — press ⌘↵ to send",
    "已复制 cURL 命令": "cURL command copied",
    "已复制为新标签": "Copied into a new tab",
    "已复制标签": "Tab copied",
    "已载入云端数据": "Cloud data loaded",
    "已连上本地 Mock 路由": "Connected to the local mock route",
    "这条请求还没有响应，文档里只会有请求部分":
        "This request has no response yet — the doc will only cover the request side",
})

# 第三轮清扫：把自绘控件、菜单项、设置页拼接串也纳进来（这些不经过 QLabel，
# 之前整片漏在中文里）。术语继续对齐 Postman：Send / Params / Headers / Body /
# Auth / Collections / Environments / Mock Server。
_EN.update({
    # ---------------------------------------------------------- 菜单 / QAction
    "Mock 服务…": "Mock Server…",
    "管理环境…": "Manage Environments…",
    "无环境": "No environment",
    "关闭其他": "Close Others", "关闭全部": "Close All",
    "复制标签": "Duplicate Tab", "复制为 cURL": "Copy as cURL",
    "查看接口文档…": "View API Docs…",
    "生成代码片段": "Generate Code Snippet",
    "Mock 数据…": "Mock Data…",
    "复制请求": "Duplicate Request", "删除请求": "Delete Request",
    "创建副本": "Duplicate", "重命名…": "Rename…",
    "上移": "Move Up", "下移": "Move Down",
    "复制此行": "Duplicate Row", "删除此行": "Delete Row",
    "关闭  esc": "Close  esc",

    # ---------------------------------------------------------- 请求编辑
    "无": "None", "文本": "Text", "表单": "Form",
    "URL 编码": "URL Encoded", "文件": "File",
    "添加查询参数": "Add a query param", "添加请求头": "Add a header",
    "添加表单字段": "Add a form field", "添加变量": "Add a variable",
    "变量": "Variables", "变量名": "Variable name",
    "选择文件": "Choose File", "选择请求体文件": "Choose Body File",
    "点击选择要上传的文件": "Click to choose a file",
    "点击选择文件…": "Choose a file…", "选择要上传的文件": "Choose a file to upload",
    "所有文件 (*)": "All Files (*)",
    "参数值类型（Auto = 按内容推断）": "Value type (Auto infers from content)",
    "添加为请求头": "Add as Header", "添加为查询参数": "Add as Query Param",

    # ---------------------------------------------------------- 设置 · 通用
    "清除": "Clear", "小": "Small", "标准": "Default", "大": "Large",
    "100 条": "100", "240 条": "240", "500 条": "500",
    "复制版本信息": "Copy version info", "去设置": "Open Settings",
    "恢复默认": "Reset", "已恢复默认键位": "Shortcuts reset to defaults",
    "设置 · {name}": "Settings · {name}",
    "变量 · {name}": "Variables · {name}",
    "环境 {n}": "Environment {n}",
    "默认 {keys}": "Default {keys}",
    "按下组合键": "Press a key combo",
    "录制快捷键 · ": "Recording… ",
    "设为当前": "Set Active", "重命名环境": "Rename Environment",
    "名称": "Name", "代码片段": "Code Snippets",
    "外观与主题色…": "Appearance…", "显示 / 隐藏侧边栏": "Show / Hide Sidebar",
    "快捷键设置…": "Shortcuts…",
    "已复制": "Copied", "已用云端数据覆盖本机": "Restored from the cloud",
    "纯本地": "Local only", "云端还没有数据": "Nothing in the cloud yet",
    "已获取快照": "Snapshot fetched",
    "连接中…": "Connecting…", "上传中…": "Uploading…", "读取中…": "Loading…",
    "上传失败：": "Upload failed: ", "恢复失败：": "Restore failed: ",
    "数据格式不对：": "Unexpected data: ",
    "云端数据不是 Ocelot 快照": "The cloud data is not an Ocelot snapshot",
    "已上传到云端": "Uploaded to the cloud",

    # ---------------------------------------------------------- 配色方案名
    "石墨": "Graphite", "岩蓝": "Slate", "暖灰": "Warm Ash",
    "松绿": "Moss", "墨黑": "Ink", "浅色": "Light",

    # ---------------------------------------------------------- 导入 cURL
    "导入 cURL": "Import cURL",
    "从剪贴板粘贴": "Paste from Clipboard", "解析并打开": "Parse and Open",
    "粘贴浏览器「Copy as cURL」或任意 cURL 命令，自动解析方法、请求头、请求体与认证。":
        "Paste a browser's “Copy as cURL” output or any cURL command — method, "
        "headers, body and auth are parsed automatically.",
    "已使用当前环境变量解析值，可直接粘贴到终端运行。":
        "Variables are already resolved — paste it straight into a terminal.",
    "查询参数 {n} 个": "{n} query params",
    "请求头 {n} 个": "{n} headers",
    "JSON 请求体 {n} 字符": "JSON body · {n} chars",
    "XML 请求体 {n} 字符": "XML body · {n} chars",
    "文本请求体 {n} 字符": "text body · {n} chars",
    "multipart {n} 字段": "multipart · {n} fields",
    "（含 {n} 个文件）": " ({n} files)",
    "urlencoded {n} 字段": "urlencoded · {n} fields",
    "Basic 认证": "Basic auth",
    "请先粘贴 cURL 命令": "Paste a cURL command first",

    # ---------------------------------------------------------- 命令面板 / 浮层
    "没有匹配的结果": "No matches",
    "切换到环境 · {name}": "Switch to environment · {name}",
    "当前": "Active", "{n} 个变量": "{n} variables",

    # ---------------------------------------------------------- Mock 中心
    "本地 Mock": "Local Mock", "公开接口": "Public Endpoints", "请求日志": "Request Log",
    "启动服务": "Start Server", "停止服务": "Stop Server",
    "新建路由": "New Route", "复制地址": "Copy URL",
    "未启动": "Stopped", "全部": "All",
    "回显调试": "Echo", "假数据": "Fake Data",
    "用户与登录": "Users & Auth", "图片与文本": "Images & Text",
    "清空": "Clear",
    "{n} 个公开接口 · 点一行新建请求":
        "{n} public endpoints · click a row to start a request",
    "例如：带 token 返回 VIP 数据": "e.g. VIP payload when a token is present",
    "body 支持 a.b.c 取嵌套字段": "Nested keys work: a.b.c",
    "要比对的值": "Value to match",
    "条件规则": "Rules", "添加规则": "Add Rule",

    # ---------------------------------------------------------- 文档 / 预览
    "接口文档": "API Docs", "保存 .md": "Save .md",
    "保存接口文档": "Save API Docs", "未命名请求": "Untitled Request",
    "草稿": "Draft", "草稿 · 尚未发送": "Draft · not sent yet",
    "状态": "Status", "耗时": "Time", "体积": "Size",
    "目录": "Contents", "打码": "Redact", "代码示例": "Code Samples",
    "（无章节）": "(no sections)", "保存失败": "Save failed",
    "保存到本地": "Save to Disk", "播放": "Play", "暂停": "Pause",
    "适应窗口": "Fit to Window", "放大": "Zoom In", "缩小": "Zoom Out",
    "PDF 响应": "PDF response", "保存后用系统阅读器打开":
        "Save it and open with your system reader",
    "没有可预览的内容": "Nothing to preview",
    "这个响应不是图片 / 音频 / 视频，切到「美化」看正文":
        "This response isn't an image, audio or video — switch to Pretty to read it.",
    "无法解码这张图片": "Couldn't decode this image",
    "无法在应用内播放": "Can't play this in-app",
    "缺少 QtMultimedia 模块，可另存为后用系统播放器打开":
        "QtMultimedia is missing — save it and open with your system player",
    "把这张图片保存到本地": "Save this image to disk",
    "二进制内容 · ": "Binary · ", " 字节 · 仅显示前 8 KB": " bytes · first 8 KB only",
    "复制这段代码": "Copy this code", "（无数据）": "(no data)",

    # ---------------------------------------------------------- 导入 / 导出
    "读取失败：": "Read failed: ", "无法识别的集合文件格式":
        "Unrecognized collection file format",
    "已导入 {n} 个集合节点": "Imported {n} collection nodes",
    "已导出 {n} 个集合": "Exported {n} collections",
    "导出失败：": "Export failed: ",
    "本地 Mock 服务运行在 {url}": "Local mock server is running at {url}",
    "本地 Mock 服务已在 {port} 运行": "Local mock server is already running on {port}",
    "已保存变量 {{{name}}}": "Saved variable {{{name}}}",

    # ---------------------------------------------------------- 节点面板
    "搜索地区 / 运营商，如 上海、电信":
        "Search by region or carrier — e.g. Shanghai, China Telecom",
})

# 第四轮：Mock 中心的示例数据。路由名与公开接口说明都写在数据里，
# 显示时统一过 tr()，所以词条要跟数据里的字符串一模一样。
_EN.update({
    "字段": "Field", "未命名": "Untitled", "回显": "echo", "条规则": "rules",
    "延迟 {ms}ms": "delay {ms}ms", "{n} 条规则": "{n} rules", "{n} 次": "{n} hits",
    "示例 · 用户信息（动态）": "Sample · User profile (dynamic)",
    "示例 · 鉴权规则": "Sample · Auth rule",
    "示例 · 回显请求": "Sample · Echo request",
    "示例 · 慢接口 2s": "Sample · Slow endpoint 2s",
    "示例 · 服务异常": "Sample · Server error",

    "回显请求头与查询参数，最稳的调试靶子":
        "Echoes headers and query params — the most reliable practice target",
    "回显 JSON 请求体": "Echoes the JSON body",
    "指定状态码，用来测错误分支与配色":
        "Forces a status code — good for testing error states and colors",
    "延迟 2 秒返回，看 loading 与超时设置":
        "Responds after 2s — watch the loading state and timeout setting",
    "2KB 随机字节，测二进制 / 十六进制预览":
        "2 KB of random bytes — tests the binary and hex preview",
    "两次 302 跳转，验证跟随重定向开关":
        "Two 302 hops — verifies the follow-redirects switch",
    "服务端种 Cookie，用来测 Cookies 页与「从响应导入」":
        "Sets a cookie server-side — tests the Cookies tab and Import from Response",
    "逐行输出 8 条 JSON，测流式响应":
        "Streams eight JSON objects — tests streamed responses",
    "任意路径都会原样回显，适合乱试":
        "Echoes anything back — handy for poking around",
    "100 条文章，列表渲染的标准素材":
        "100 posts — the classic fixture for list rendering",
    "单条文章，字段少、结构清晰": "A single post — few fields, clean shape",
    "带查询参数的评论列表": "Comment list with a query param",
    "创建资源（返回 201）": "Creates a resource (201)",
    "电商商品列表，字段更接近真实业务":
        "Product list — fields closer to a real business payload",
    "单个商品，含图片数组": "A single product with an image array",
    "购物车，嵌套结构，适合测树形视图":
        "A cart with nested structures — good for the tree view",
    "带搜索的列表，测参数联动": "Search-backed list — tests parameter wiring",
    "强制 500，测失败提示": "Forces a 500 — tests the failure state",
    "分页用户列表（需带 x-api-key: reqres-free-v1）":
        "Paged user list (needs x-api-key: reqres-free-v1)",
    "登录成功返回 token": "Successful login returns a token",
    "缺字段 → 400，测参数校验": "Missing field → 400, tests validation",
    "创建用户（201）": "Creates a user (201)",
    "随机一个人，含头像地址": "A random person, avatar URL included",
    "10 个用户，含地址与公司": "Ten users with address and company",
    "随机狗图（返回图片直链）": "Random dog photo (direct image URL)",
    "随机图片，直接测图片预览": "Random image — tests the image preview",
    "一句猫知识，纯文本 JSON": "A cat fact in plain JSON",
    "GitHub 仓库信息，字段多、层级深":
        "GitHub repo info — many fields, deep nesting",
})

# 第五轮：对话框、错误提示与应用内文案（这些多由 Label / Button 直接构造，
# 显示前会走一次 tr()，补齐词条即可）。
_EN.update({
    # 通用操作
    "剪切": "Cut", "复制所选": "Copy Selection", "复制全部": "Copy All",
    "删除所选": "Delete Selection", "知道了": "Got it",
    "格式化": "Format", "压缩": "Minify", "格式化 JSON": "Format JSON",
    "预览随机数据": "Preview Random Data", "动态数据预览": "Dynamic Data Preview",
    "发送请求后会自动记录在这里": "Requests you send land here automatically",
    "⌘↵ 发送": "⌘↵ to send", "暂无历史记录": "No history yet",
    "这个地址还没有足够的历史记录\n再发几次，就能看到耗时趋势了":
        "Not enough history for this URL yet\nSend a few more and the trend shows up here",

    # 请求编辑
    "用户名": "Username", "密码": "Password", "Key 名称": "Key name",
    "留空表示沿用路由的默认响应体，只改状态码 / 延迟；同样支持 {{@name}} 之类的动态占位符。":
        "Leave empty to keep the route's default body and only override status / delay. "
        "Dynamic placeholders like {{@name}} work here too.",
    "回显模式：服务会把收到的请求（方法 / 路径 / 头 / 请求体）原样返回，下面的响应体不会生效。":
        "Echo mode: the server returns the request it received (method, path, headers, body). "
        "The body below is ignored.",

    # 响应区
    "请求已修改": "Request changed",
    "发送后这里会显示本次请求的新响应":
        "Send it again — the new response shows up here",
    "请求中": "In flight",
    "已把当前响应设为基准，下次发送后即可对比":
        "Current response set as baseline — send again to compare",
    "还没有可对比的上一次响应 · 同地址请求一次后再看这里":
        "No previous response to compare yet — send to this URL again",
    "（同一地址的第二次响应会自动与上一次逐行对比）":
        "(The second response from the same URL is diffed automatically)",
    "上一次": "Before", "本次": "After",
    "当前响应不是 JSON，无法用路径提取":
        "This response isn't JSON — path extraction isn't available",
    "内容过大，已跳过树形视图": "Too large — tree view skipped",
    "用「提取」按路径取值更快": "Use Extract to pull a value by path",
    "响应体不是合法 JSON": "The response body isn't valid JSON",
    "响应是数组，试试 [0] 或 [0].字段名":
        "The response is an array — try [0] or [0].field",
    "* 只能用于对象或数组": "* only works on objects and arrays",
    "缺少 ]": "Missing ]",
    "脱敏复制响应体": "Copy Response Body (redacted)",
    "复制响应头": "Copy Response Headers",
    "复制状态行": "Copy Status Line",
    "保存响应": "Save Response",
    "准备 / DNS / TCP / SSL 为按 TTFB 比例估算":
        "Prepare / DNS / TCP / SSL are estimated from TTFB",
    "Header 为估算 · Body 为正文":
        "Header is an estimate · Body is the payload",
    "存为环境变量": "Save as Environment Variable",

    # Mock 路由编辑
    "新建 Mock 路由": "New Mock Route", "编辑 Mock 路由": "Edit Mock Route",
    "新建条件规则": "New Condition Rule", "编辑条件规则": "Edit Condition Rule",
    "规则名称": "Rule name", "只是给自己看的备注，可以空着":
        "Just a note for yourself — can be empty",
    "条件来源": "Condition source", "比较方式": "Comparison",
    "「存在 / 不存在」不看值，只看有没有这个键":
        "“exists / missing” only checks the key, not the value",
    "命中后的响应体": "Body on match",
    "状态码要在 100 ~ 599 之间": "Status code must be 100–599",
    "填一下要比对的键名": "Enter the key to compare",
    "列表里显示的名字，随便写": "Shown in the list — call it anything",
    "延迟到时间后才会返回，用来测 Loading、骨架屏与超时。":
        "Responds only after the delay — good for loading states, skeletons and timeouts.",
    "响应体": "Response Body", "回显请求": "Echo Request",
    "条件响应": "Conditional Response",
    "路径要以 / 开头": "Path must start with /",
    "服务已停止。已经填好的路由仍然保留，重启后继续用。":
        "Server stopped. Your routes are kept — start it again to keep going.",
    "先启动服务，才有地址可复制": "Start the server first — there's no URL yet",
    "先启动服务，再试用这条路由": "Start the server, then try this route",
    "没有匹配的接口，换个关键词试试": "No endpoint matches — try another keyword",
    "键": "Key", "路径": "Path", "方法": "Method",
    "状态码": "Status code", "延迟（毫秒）": "Delay (ms)",
    "内容类型": "Content type", "以 / 开头；结尾 * 做前缀匹配":
        "Starts with /; a trailing * matches by prefix",
    "不是合法 JSON，没法格式化": "Not valid JSON — can't format",
    "状态码要填数字": "Status code must be a number",
    "延迟要填数字（毫秒）": "Delay must be a number (ms)",
    "提示：响应体不是合法 JSON，仍可保存":
        "Heads up: the body isn't valid JSON — you can still save it",
    "还没有规则。例如「请求头 token 等于 123 → 200」，没带 token 时返回 401。":
        "No rules yet. For example: “header token equals 123 → 200”, "
        "and a 401 when the token is missing.",
    "编辑规则": "Edit rule", "删除规则": "Delete rule",
    "根地址已复制": "Base URL copied",
    "等于": "equals",

    # 节点
    "测试当前分栏全部节点的延迟（速度仅供参考，不代表可用性与整体请求速度）":
        "Test latency for every node here (indicative only — not availability or throughput)",
    "从 tcping.cn 重新拉取完整节点列表": "Fetch the full node list again from tcping.cn",
    "添加代理节点": "Add Proxy Node",
    "地址，例如 socks5://127.0.0.1:1080": "Address, e.g. socks5://127.0.0.1:1080",
    "选择请求节点（默认从本地发出）": "Choose a node (defaults to direct)",
    "在线节点转发": "Relayed via node", "拉取失败 · 用缓存": "Fetch failed · using cache",
    "离线 · 点刷新节点": "Offline · hit Refresh Nodes",

    # 导入导出 / 文件对话框
    "导入导出": "Import / Export", "导入集合": "Import Collection", "导出集合": "Export Collection",
    "JSON (*.json);;所有文件 (*)": "JSON (*.json);;All Files (*)",
    "Markdown (*.md);;所有文件 (*)": "Markdown (*.md);;All Files (*)",

    # 云同步
    "请先填写数据库地址": "Enter the database URL first",
    "请先填写 Auth Token": "Enter the Auth Token first",
    "连接超时，检查网络或地址": "Connection timed out — check the network or URL",
    "返回的不是合法 JSON，地址可能不是 Turso 数据库":
        "The response isn't valid JSON — that may not be a Turso database",
    "Token 被拒绝（401/403），检查是否复制完整":
        "Token rejected (401/403) — make sure it was copied in full",
    "地址不对（404），确认是 https://<库名>-<组织>.turso.io":
        "Wrong URL (404) — should look like https://<db>-<org>.turso.io",

    # cURL 解析
    "命令为空，请粘贴完整的 curl 命令": "Empty command — paste a full curl command",
    "这不是 curl 命令，请粘贴以 curl 开头的命令":
        "That isn't a curl command — it should start with curl",
    "命令里没有 URL": "No URL in the command",

    # 网络层错误
    "请求地址为空": "Request URL is empty",
    "无效的 URL：{url}": "Invalid URL: {url}",
    "读取文件失败：{err}": "Couldn't read the file: {err}",
    "请求构造失败：{err}": "Couldn't build the request: {err}",
    "请求超时（{n}s）": "Request timed out ({n}s)",
    "在线节点不支持文件上传 / multipart，请切回本地直连或自建代理":
        "File uploads and multipart aren't supported through nodes — "
        "switch to direct or your own proxy",
    "请选择一个有效的二进制文件": "Choose a valid binary file",

    "环境": "Environment",
    "直接按下新的组合键。支持 ⌘ / ⌃ / ⌥ / ⇧ 与字母、数字、方向键、回车等。":
        "Just press the new combo. ⌘ / ⌃ / ⌥ / ⇧ work with letters, digits, arrows, Enter and more.",
    "每次请求都会重新生成，下面的值只是其中一次的结果。":
        "Regenerated on every request — what you see is one of those draws.",
    "回显兜底": "echo fallback", "未匹配": "no match",
    "带 token=123 返回 VIP 数据": "VIP payload when token=123",
    "节点校验计算超时": "Node handshake timed out",
    "URL 查询参数无法携带文件；文件上传请在「请求体 → Form 表单」里添加":
        "Query params can't carry files — use Body → Form to upload.",
})

# 第六轮：界面里由 f-string 拼出来的动态文案（toast、状态行、错误提示）。
# 统一走 trf()，模板带 {占位}，参数各自翻译。
_EN.update({
    "响应体为空": "The response body is empty",
    "... 仅显示前 {n} 字节，共 {m} 字节":
        "... showing the first {n} of {m} bytes",
    "节点 {name}": "Node {name}",
    "这是二进制内容（{type} · {size}）。\n请切换到「预览」查看；「原始」页里是十六进制内容。":
        "This is binary content ({type} · {size}).\nSwitch to Preview to look at it; "
        "the Raw tab holds the hex dump.",
    "\n\n⋯（共 {total}，此处只预览前 {shown}；完整内容请用「另存为」或「复制」）":
        "\n\n⋯ {total} in total, previewing the first {shown}. "
        "Use Save As or Copy for the whole thing.",
    "\n\n⋯（共 {total}，仅显示前 {shown}）":
        "\n\n⋯ {total} in total, showing the first {shown}",
    "过期 {when}": "expires {when}",
    "较上一次：+{added} 行 / -{removed} 行 · 状态 {was} → {now} · 耗时 {t0}ms → {t1}ms":
        "vs. last time: +{added} / -{removed} lines · status {was} → {now} · {t0}ms → {t1}ms",
    "可用的顶层字段：{keys}": "Top-level fields: {keys}",
    "路径无效：{kind} · {msg}": "Invalid path: {kind} · {msg}",
    "命中 {kind} · 路径 {path}": "Matched {kind} · path {path}",

    "✓ 合法 JSON · {n} 个字段": "✓ Valid JSON · {n} fields",
    "✓ 合法 JSON · {n} 项": "✓ Valid JSON · {n} items",
    "{p} 参数 · {h} 请求头": "{p} params · {h} headers",
    "{n} 条 Cookie 会合并成 Cookie 请求头":
        "{n} cookies will be merged into the Cookie header",
    "把上一次响应的 {n} 条 Set-Cookie 收进这张表":
        "Pull {n} Set-Cookie entries from the last response into this table",
    "上一次响应没有 Set-Cookie": "The last response had no Set-Cookie",
    "经由节点：{name}": "Via node: {name}",
    "从本机发出": "Sent from this machine",

    # Mock 状态
    "服务运行中：{url} —— 本机浏览器、脚本、别的设备都能连。":
        "Running at {url} — browsers, scripts and other devices on your network can reach it.",
    "服务运行中：{url} —— 本机任何工具都能连这个地址。":
        "Running at {url} — anything on this machine can connect.",
    "启动后：请求发到 http://127.0.0.1:<端口>/<路径>，本机的浏览器、脚本、别的设备都能连。":
        "Once running, point requests at http://127.0.0.1:<port>/<path> — browsers, scripts "
        "and other devices on your network can reach it.",
    "已停止本地服务，但端口 {port} 仍被其它程序占用（可能是另一个 Ocelot 实例）。":
        "Stopped, but port {port} is still taken by another process — possibly a second Ocelot.",
    "端口 {port} 上已经有一个 Ocelot Mock 服务在响（可能是另一次启动的 Ocelot，或上次没有正常退出）。要接管请先在那边停止，或直接点「启动服务」，会自动换端口。":
        "Another Ocelot mock server is answering on port {port} — likely a second instance or a "
        "previous run that didn't exit cleanly. Stop it there first, or just hit Start Server "
        "and a free port will be picked.",
    "端口 {port} 已被其它程序占用。点「启动服务」会自动挑一个空闲端口，实际地址会显示在这里。":
        "Port {port} is taken by another process. Start Server will pick a free one and show "
        "the actual address here.",
    "已复制 {path}": "Copied {path}",
    "运行中": "Running",
    "启动失败：{err}": "Couldn't start: {err}",
    "已启动 · {url}": "Running · {url}",
    "端口 {port} 已被另一个 Ocelot Mock 服务占用，本次改用 {alt}":
        "Port {port} is used by another Ocelot mock server — using {alt} instead",
    "端口 {port} 已被其它程序占用，本次改用 {alt}":
        "Port {port} is taken by another program — using {alt} instead",

    # 设置 / 快捷键
    "{keys} 原来是「{action}」的，已让位":
        "{keys} belonged to “{action}” — that one stepped aside",
    "已改为 {keys}": "Changed to {keys}",
    "已清除 {name} 的快捷键": "Cleared the shortcut for {name}",
    "当前版本 {v}": "This version · {v}",
    "已删除「{name}」": "Deleted “{name}”",

    # 节点
    "IPv4 节点 {n}": "IPv4 · {n}", "IPv6 节点 {n}": "IPv6 · {n}",
    "{scheme} 代理": "{scheme} proxy",
    "已载入 {n} 个节点": "Loaded {n} nodes",
    "已测 {n} 个节点 · 速度仅供参考，不代表可用性":
        "{n} nodes tested · latency is indicative only, not availability",
    "测速中 {done}/{total} · 速度不代表可用性":
        "Testing {done}/{total} · latency doesn't imply availability",
    "在线节点请求失败：{err}": "Node request failed: {err}",
    "节点返回无法解析：{err}": "Couldn't parse the node's reply: {err}",

    # cURL / 云同步 / 文档
    "{flag} 后面缺少参数": "{flag} is missing its value",
    "-{flag} 后面缺少参数": "-{flag} is missing its value",
    "连不上：{err}": "Can't connect: {err}",
    "连接正常 · {ms} ms": "Connected · {ms} ms",
    "连上了但没返回结果": "Connected, but nothing came back",
    "上传失败：{err}": "Upload failed: {err}",
    "恢复失败：{err}": "Restore failed: {err}",
    "数据格式不对：{err}": "Unexpected data: {err}",
    "生成失败：{err}": "Couldn't generate: {err}",
    "状态 {code} {reason}": "Status {code} {reason}",
    "已保存 {name}": "Saved {name}",
    "二进制内容 · {n} 字节 · 仅显示前 8 KB":
        "Binary · {n} bytes · first 8 KB only",
})

# 第七轮：导出的 Markdown 文档、Mock 404 说明这类「写给人看」的文案。
_EN.update({
    "概览": "Overview", "项目": "Item", "内容": "Value", "地址": "URL",
    "含义": "Meaning", "名称": "Name", "说明": "Notes", "响应": "Response",
    "Query 参数": "Query Params", "表单字段": "Form Fields",
    "鉴权": "Auth", "响应示例": "Response Example",
    "请求头 / 查询参数里带 API Key": "Sends the API key as a header or query param",
    "…（已截断，完整内容请在 Ocelot 里查看）":
        "… (truncated — open it in Ocelot for the full content)",
    "成功，响应体里带业务数据": "OK — the body carries your payload",
    "创建成功，通常返回新资源的 id": "Created — usually returns the new resource id",
    "参数错误或缺少必填字段": "Bad request — wrong or missing fields",
    "未登录 / 凭据失效": "Not signed in, or credentials expired",
    "已登录但没有权限": "Signed in, but not allowed",
    "资源不存在": "Not found",
    "触发限流，需要退避重试": "Rate limited — back off and retry",
    "服务端异常": "Server error",
    "存在": "exists", "不存在": "missing",
    "没有找到 {method} {path} 的 Mock 规则": "No mock route for {method} {path}",
    "在 Ocelot「Mock 服务」里新建一条，或把路径写成 /api/users/* 做前缀匹配":
        "Add one in Ocelot's Mock Server, or end the path with * to match by prefix.",
    "读取失败：{err}": "Couldn't read the file: {err}",
    # 前后置脚本 / 代码编辑 / 历史分组
    "前置脚本": "Pre-request Script", "后置脚本": "Post-response Script",
    "代码片段": "Code snippets",
    "环境变量：设置一个变量": "Environment: Set an environment variable",
    "环境变量：设置时间戳": "Environment: Set timestamp variable",
    "环境变量：设置随机数": "Environment: Set random number variable",
    "请求：添加一个请求头": "Request: Add a header",
    "控制台：打印一条消息": "Console: Print a message",
    "试运行": "Run test",
    "不联网，只在临时请求上执行当前脚本，查看日志与错误。":
        "Run the current script locally without sending a request, then show logs and errors.",
    "前置脚本在请求发送前用 JavaScript 运行。\n"
    "可修改 req.url、req.headers 和 req.params，或用 pw.env.set() 把值存入当前环境。":
        "Pre-request scripts run in JavaScript before the request is sent.\n"
        "Modify req.url, req.headers and req.params, or store values in the "
        "active environment with pw.env.set().",
    "后置脚本在收到响应后用 JavaScript 运行。\n"
    "可读取 res.status / res.body，解析结果，并用 pw.env.set() 把值存回当前环境。":
        "Post-response scripts run in JavaScript after the response arrives.\n"
        "Read res.status / res.body, parse JSON and save values back to the "
        "active environment with pw.env.set().",
    "✓ 运行成功 · 查看下方日志": "✓ Ran OK · see logs below",
    "Header 含状态行 · Body 为正文": "Header includes the status line · Body is the raw payload",
    "今天": "Today", "昨天": "Yesterday", "{n} 天前": "{n} days ago",
    # JWT / Inherit 认证
    "继承": "Inherit", "JWT": "JWT",
    "从所属集合继承认证配置。集合未设置认证时不带任何凭据。":
        "Inherit the auth settings from the parent collection. No credential is sent if "
        "the collection has none.",
    "当前集合未设置认证，请求将不带凭据。":
        "No auth configured on the parent collection; no credential will be sent.",
    "集合认证": "Collection auth", "集合认证：{kind}": "Collection auth: {kind}",
    "设置认证…": "Configure auth…",
    "这里的认证会被子请求通过「继承」使用；留空则以请求自己的认证为准。":
        "Auth set here is used by child requests via Inherit; leave it unset to use each "
        "request's own auth.",
    "集合认证已更新": "Collection auth updated",
    "算法": "Algorithm", "密钥": "Secret", "载荷": "Payload",
    "令牌": "Token", "自动生成": "Auto-generate", "手动输入": "Enter manually",
    "JWT 头": "JWT header", "签名": "Signature",
    "填写 Payload 与密钥后自动生成签名令牌，发送时作为 Authorization: Bearer <token> 携带。":
        "Fill in the payload and secret to auto-generate a signed token, sent as "
        "Authorization: Bearer <token>.",
    "直接粘贴一个现成的 JWT，发送时作为 Authorization: Bearer <token> 携带。":
        "Paste an existing JWT to be sent as Authorization: Bearer <token>.",
    "Payload 不是合法 JSON": "Payload is not valid JSON",
    "已生成 · {n} 字符": "Generated · {n} chars",
    "运行结果": "Run Result", "✓ 运行成功": "✓ Ran successfully",
    "运行成功": "Ran successfully",
    "运行失败": "Run failed", "（脚本没有输出日志）": "(No logs from the script)",
    "1小时内": "Within the last hour",
    "退出批量": "Exit Bulk Edit",
})


# 1.0.28：控制台、导入导出、标签重命名
_EN.update({
    # ---- 控制台
    "控制台": "Console",
    "{n} 条输出": "{n} lines",
    " · {w} 条警告": " · {w} warnings",
    "复制全部": "Copy all",
    "脚本里用 console.log() 打印的内容会显示在这里":
        "Anything logged with console.log() shows up here",
    "前置": "Pre", "后置": "Post",
    "脚本执行超过 {ms} 毫秒，已中止（检查是否有死循环）":
        "Script ran longer than {ms} ms and was stopped (check for an endless loop)",
    "第 {n} 行：{msg}": "Line {n}: {msg}",
    # ---- 脚本片段
    "环境变量：设置一个变量": "Env var: set a value",
    "环境变量：设置时间戳": "Env var: set a timestamp",
    "环境变量：设置随机数": "Env var: set a random number",
    "请求：添加一个请求头": "Request: add a header",
    "控制台：打印一条消息": "Console: log a message",
    "响应：打印状态与耗时": "Response: log status and time",
    "响应：解析 JSON 并取字段": "Response: parse JSON and read fields",
    "响应：把 token 存进环境": "Response: save a token to the environment",
    "断言：状态码为 200": "Test: status is 200",
    "断言：响应包含字段": "Test: response has a field",
    "代码片段": "Snippets",
    # ---- 导入 / 导出
    "返回": "Back", "导出": "Export",
    "导入 / 导出集合": "Import / Export Collections",
    "导出集合": "Export Collections",
    "从 Ocelot JSON 导入": "Import from Ocelot JSON",
    "Ocelot / Postman v2.1 兼容格式，保留脚本与认证":
        "Ocelot / Postman v2.1 compatible, keeps scripts and auth",
    "从 Postman 导入": "Import from Postman",
    "Collection v2.0 / v2.1 导出的 JSON": "JSON exported from Collection v2.0 / v2.1",
    "从 Apifox 导入": "Import from Apifox",
    "Apifox 导出的 JSON（Postman 兼容）": "JSON exported from Apifox (Postman compatible)",
    "从 Hoppscotch 导入": "Import from Hoppscotch",
    "Hoppscotch 集合导出的 JSON": "JSON exported from a Hoppscotch collection",
    "从 Insomnia 导入": "Import from Insomnia",
    "Insomnia 导出的 JSON（v4）": "JSON exported from Insomnia (v4)",
    "从 OpenAPI 导入": "Import from OpenAPI",
    "OpenAPI 3.x / Swagger 2.0，JSON 或 YAML": "OpenAPI 3.x / Swagger 2.0, JSON or YAML",
    "从 HAR 导入": "Import from HAR",
    "浏览器开发者工具导出的 .har": ".har exported from browser dev tools",
    "从剪贴板导入": "Import from clipboard",
    "自动识别 JSON 集合或 cURL 命令，直接粘过来":
        "Detects a JSON collection or a cURL command, right from the clipboard",
    "导出全部集合": "Export all collections",
    "Ocelot JSON / Postman / OpenAPI / HAR": "Ocelot JSON / Postman / OpenAPI / HAR",
    "导出为 Ocelot JSON": "Export as Ocelot JSON",
    "Postman v2.1 兼容，附 x-ocelot 元数据；保留脚本、认证、环境变量":
        "Postman v2.1 compatible, plus x-ocelot metadata; keeps scripts, auth and environments",
    "导出为 Postman v2.1": "Export as Postman v2.1",
    "最通用的集合格式，Postman / Apifox 可直接导入":
        "The most portable collection format; Postman / Apifox import it directly",
    "导出为 OpenAPI 3.1 (JSON)": "Export as OpenAPI 3.1 (JSON)",
    "接口文档格式，只保留路径、方法、参数与示例":
        "API documentation format: paths, methods, parameters and examples",
    "导出为 OpenAPI 3.1 (YAML)": "Export as OpenAPI 3.1 (YAML)",
    "同上，YAML 写法，适合放进代码仓库": "Same content in YAML, handy for a repository",
    "导出为 HAR": "Export as HAR",
    "抓包归档格式，适合给同事复现问题":
        "Network archive format, handy for reproducing an issue",
    "把文件拖到这里，或点击选择": "Drop a file here, or click to choose",
    "支持 .json / .yaml / .har，自动识别来源":
        "Supports .json / .yaml / .har; the source is detected automatically",
    "选择要导入的文件": "Choose a file to import",
    "集合文件 (*.json *.yaml *.yml *.har);;所有文件 (*)":
        "Collection files (*.json *.yaml *.yml *.har);;All files (*)",
    "导入": "Import",
    "✓ 已解析：{n} 个请求 · {size} 字节 {note}":
        "✓ Parsed: {n} requests · {size} bytes {note}",
    "（识别为 {fmt} 格式，已按实际格式解析）":
        " (detected as {fmt}, parsed accordingly)",
    "✓ 已导入 {n} 个请求": "✓ Imported {n} requests",
    "已导入 {n} 个请求": "Imported {n} requests",
    "已从剪贴板导入 {n} 个请求": "Imported {n} requests from the clipboard",
    "已从剪贴板导入 1 个请求": "Imported 1 request from the clipboard",
    "剪贴板是空的": "The clipboard is empty",
    "剪贴板内容不是可识别的集合": "The clipboard does not contain a known collection",
    "cURL 解析失败": "Could not parse the cURL command",
    "读取失败：{err}": "Read failed: {err}",
    "文件里没有可导入的请求": "No importable request found in the file",
    "导入只会新增集合，不会覆盖现有内容；重复导入会产生新的副本。":
        "Importing only adds collections; nothing is overwritten, repeated imports "
        "create duplicates.",
    "Ocelot JSON 与 Postman v2.1 是通用格式，别的工具可以直接导入；"
    "OpenAPI 导出会丢失脚本、认证凭据、未启用的请求项、重复路径与重复响应码。":
        "Ocelot JSON and Postman v2.1 are portable formats other tools can import. "
        "OpenAPI export drops scripts, auth credentials, disabled items, duplicate "
        "paths and duplicate response codes.",
    "✓ 已导出到 {path} · {size} 字节": "✓ Exported to {path} · {size} bytes",
    "✕ 导出失败：{err}": "✕ Export failed: {err}",
    # ---- 标签重命名
    "重命名": "Rename", "重命名…": "Rename…", "已重命名": "Renamed",
    "新建请求": "New Request",
    "复制为 cURL": "Copy as cURL",
    "关闭全部": "Close all",
    "删除": "Delete",
    "新建文件夹": "New Folder",
    # ---- 导入 / 导出结果页
    "导入完成": "Import complete",
    "导出完成": "Export complete",
    "完成": "Done",
    "在文件夹中显示": "Show in Folder",
    "重新发送": "Send again",
    "请求已修改 · 下面是上一次的响应": "Request changed · showing the previous response",
    "已导入 {n} 个请求": "Imported {n} requests",
    "来自 {fmt} · 已追加到集合列表末尾": "From {fmt} · appended to the end of your collections",
    "已导出 {name}": "Exported {name}",
    "文件名": "File",
    "大小": "Size",
    "位置": "Location",
    "请求": "Requests",
    "文件夹": "Folders",
    "前置脚本": "Pre-request scripts",
    "后置脚本": "Post-response scripts",
    "认证配置": "Auth",
    "环境变量": "Environments",
    "✓ 已识别 {fmt}：{detail}": "✓ Detected {fmt}: {detail}",
    "{n} 个请求": "{n} requests",
    "{n} 个文件夹": "{n} folders",
    "{n} 个{name}": "{n} {name}",
    "{n} 套环境变量": "{n} environments",
    "选择要导入的文件": "Choose a file to import",
    "读取失败：{err}": "Read failed: {err}",
    "文件里没有可导入的请求": "No importable requests in this file",
    "无法识别的文件格式：既不是 Postman / Apifox / Hoppscotch / Insomnia 集合，也不是 OpenAPI 或 HAR":
        "Unrecognized file: not a Postman / Apifox / Hoppscotch / Insomnia collection, nor OpenAPI or HAR",
    "这是一条 cURL 命令，请用「从剪贴板导入」":
        "This is a cURL command — use “Import from clipboard” instead",
    "这是环境变量文件，不是集合；请在「设置 → 环境变量」里导入":
        "This is an environment file, not a collection. Import it from Settings → Environments",
    "这是环境变量文件（Postman Environment），不是集合；集合请从 Collection 导出":
        "This is a Postman environment file, not a collection. Export the Collection instead",
    "集合是空的：文件里没有任何请求": "The collection is empty — no requests in this file",
    "识别为 Apifox 集合，但里面没有可导入的接口":
        "Detected an Apifox collection, but it contains no APIs",
    "将导出 {f} 个集合、{n} 个请求": "Exporting {f} collections, {n} requests",
    "还没有可导出的请求：先新建或导入一个集合":
        "Nothing to export yet — create or import a collection first",
    "还没有可导出的请求：先新建或导入一个集合。":
        "Nothing to export yet — create or import a collection first.",
})
