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


def apply_language(root) -> None:
    """遍历控件树应用当前语言。可反复调用，来回切换不失真。

    优先用 findChildren 递归拿控件 —— 自己顺着 children() 走会漏掉「后来才挂进布局」
    的那一支（比如堆叠页里的滚动内容），表现就是同一页一半英文一半中文。
    """
    from PyQt6.QtCore import QObject
    from PyQt6.QtWidgets import QWidget

    _translate_object(root)
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
            _translate_object(obj)
            try:
                for child in obj.children():
                    if isinstance(child, QObject):
                        stack.append(child)
            except RuntimeError:  # noqa: BLE001
                continue
        return
    for w in widgets:
        try:
            _translate_object(w)
        except RuntimeError:      # 控件已经被销毁
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

