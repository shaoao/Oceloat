"""AI 能力：大模型客户端 + 提示词，供生成测试数据、解释报错等功能使用。

三条硬约束：
1. 只用标准库（urllib），不引入 openai SDK —— 装个 API Key 就能用，不加重安装包；
2. 流式读取 SSE，边生成边回调 —— 打字机效果，体感就是「快」；
3. 模型是数据表（PROVIDERS / MODELS），加新模型只加一行，不用改逻辑。

配置存在 store.settings["ai"]：
    {"provider": "glm", "api_key": "...", "model": "glm-4-flash-250414",
     "base_url": "", "custom_models": [{"id": "...", "label": "..."}]}
base_url 留空就用服务商默认，填了就覆盖（自建网关 / 中转站都能接）。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from . import i18n

# ---------------------------------------------------------------- 服务商与模型

# 默认清单全部是免费/低价模型：先给能直接用的，再给要思考的。
# badge / desc 直接渲染成设置页里的模型卡片，加模型只要往这里加一条。
MODELS: List[Dict[str, Any]] = [
    {"id": "glm-4-flash-250414", "label": "GLM-4-Flash", "badge": "250414",
     "desc": "默认 · 快照固定，最快最稳", "free": True},
    {"id": "glm-4-flash", "label": "GLM-4-Flash", "badge": "latest",
     "desc": "跟随官方默认版，会随官方升级", "free": True},
    {"id": "glm-4.5", "label": "GLM-4.5", "badge": "会思考",
     "desc": "推理更强，思考过程更细", "free": True},
    {"id": "glm-4.1v", "label": "GLM-4.1V", "badge": "原生思考",
     "desc": "最严谨，但慢，适合绕的问题", "free": True},
]

# DeepSeek 与 GLM 共用同一套 OpenAI 兼容协议，区别只在 base 与模型名。
# 每个服务商可以带自己的模型表（没有就回落到 MODELS），加服务商 = 加一段配置。
DEEPSEEK_MODELS: List[Dict[str, Any]] = [
    {"id": "deepseek-chat", "label": "DeepSeek-V3", "badge": "通用",
     "desc": "默认 · 快，写代码与生成数据都稳"},
    {"id": "deepseek-reasoner", "label": "DeepSeek-R1", "badge": "推理",
     "desc": "先想再答，复杂问题更准，略慢"},
]

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "glm": {
        "name": "智谱 GLM",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash-250414",
        "doc": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "key_hint": "在智谱开放平台「API Keys」里创建，形如 xxxxxxxx.yyyyyyyy",
        "models": MODELS,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "doc": "https://platform.deepseek.com/api_keys",
        "key_hint": "在 DeepSeek 控制台「API Keys」里创建，形如 sk-xxxxxxxx",
        "models": DEEPSEEK_MODELS,
    },
}


def config(store: Any = None) -> Dict[str, Any]:
    """把设置读成一份可直接用的配置（含默认值兜底）。"""
    if store is None:
        try:
            from .store import Store

            store = Store.active()
        except Exception:  # noqa: BLE001
            store = None
    raw = dict((store.settings.get("ai") if store else {}) or {})
    provider = raw.get("provider") or "glm"
    preset = PROVIDERS.get(provider) or PROVIDERS["glm"]
    # Key 按服务商分开存：GLM 与 DeepSeek 的 Key 格式不同，来回切不该互相覆盖。
    # api_key 是 1.0.51 的旧字段，保留作 glm 的兼容读。
    keys = raw.get("key_by_provider") or {}
    api_key = str(keys.get(provider) or "").strip()
    if not api_key and provider == "glm":
        api_key = (raw.get("api_key") or "").strip()
    return {
        "provider": provider if provider in PROVIDERS else "glm",
        "provider_name": preset["name"],
        "base": (raw.get("base_url") or "").strip().rstrip("/") or preset["base"],
        "model": (raw.get("model") or "").strip() or preset["default_model"],
        "api_key": api_key,
        "custom_models": list(raw.get("custom_models") or []),
        # 总开关：填了 Key 也可以随时关掉，所有入口一起停用，不用删 Key
        "enabled": bool(raw.get("enabled", True)),
    }


def models_for(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """当前服务商的模型 + 用户自加的模型，去重保序。"""
    preset = PROVIDERS.get(cfg.get("provider") or "glm") or PROVIDERS["glm"]
    base = preset.get("models") or MODELS
    out = [dict(m) for m in base]
    seen = {m["id"] for m in out}
    for m in cfg.get("custom_models") or []:
        mid = str((m or {}).get("id") or "").strip()
        if mid and mid not in seen:
            seen.add(mid)
            out.append({"id": mid, "label": (m.get("label") or mid),
                        "badge": "自定义", "desc": "自定义模型 ID", "custom": True})
    return out


def ready(cfg: Optional[Dict[str, Any]] = None) -> tuple:
    """(是否可用, 原因)。原因直接可以显示给用户。"""
    cfg = cfg or config()
    if not cfg.get("enabled", True):
        return False, i18n.tr("AI 已在设置里关闭")
    if not cfg.get("api_key"):
        return False, i18n.tr("还没填 API Key")
    if not cfg.get("model"):
        return False, i18n.tr("还没选模型")
    return True, ""


# ---------------------------------------------------------------- 错误翻译

def _explain_http(code: int, detail: str) -> str:
    detail = (detail or "").strip()
    short = detail[:180]
    if code in (401, 403):
        return i18n.tr("API Key 无效或没有权限，请到设置 → AI 里重新粘贴")
    if code == 404:
        return i18n.tr("接口或模型不存在，检查模型 ID 与服务地址")
    if code == 429:
        return i18n.tr("请求太频繁或免费额度用完了，稍等一会儿再试")
    if code == 400 and ("model" in short.lower() or "1211" in short):
        return i18n.tr("模型名不被接受，换一个模型试试")
    if 500 <= code < 600:
        return i18n.trf("服务端出错（HTTP {code}），通常是临时的，重试即可", code=code)
    return i18n.trf("请求失败（HTTP {code}）{detail}", code=code,
                    detail=("：" + short) if short else "")


# ---------------------------------------------------------------- 流式对话


def _endpoint(base: str) -> str:
    base = (base or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


class Chat(QThread):
    """一次流式对话。信号都在主线程回调，调用方不必自己管线程安全。

    chunk(文本片段) → done(完整文本) / failed(人话错误)
    """

    chunk = pyqtSignal(str)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, messages: List[Dict[str, str]], cfg: Optional[Dict[str, Any]] = None,
                 max_tokens: int = 1200, temperature: float = 0.4, timeout: int = 60,
                 parent=None):
        super().__init__(parent)
        self.messages = messages
        self.cfg = cfg or config()
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self._stop = False
        self._buf = ""

    def cancel(self) -> None:
        self._stop = True

    # -------------------------------------------------- 内部
    def _payload(self, stream: bool) -> bytes:
        body = {
            "model": self.cfg.get("model"),
            "messages": self.messages,
            "stream": stream,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _request(self, stream: bool) -> urllib.request.Request:
        return urllib.request.Request(
            _endpoint(self.cfg.get("base", "")), data=self._payload(stream), method="POST",
            headers={
                "Authorization": "Bearer " + self.cfg.get("api_key", ""),
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
            })

    def run(self) -> None:  # noqa: D401
        if not self.cfg.get("api_key"):
            self.failed.emit(i18n.tr("还没填 API Key，请到设置 → AI 里填一个"))
            return
        try:
            self._run_stream()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            self.failed.emit(_explain_http(exc.code, detail))
        except urllib.error.URLError as exc:
            self.failed.emit(i18n.trf("连不上模型服务：{err}", err=exc.reason))
        except TimeoutError:
            self.failed.emit(i18n.tr("连接超时，检查网络或代理"))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(i18n.trf("生成失败：{err}", err=exc))

    def _run_stream(self) -> None:
        with urllib.request.urlopen(self._request(True), timeout=self.timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "event-stream" not in ctype:
                # 有的网关直接回整包 JSON：按非流式处理，效果一样，只是没有打字机感
                raw = resp.read().decode("utf-8", "replace")
                text = _text_from_json(raw)
                if text:
                    self.chunk.emit(text)
                    self._buf = text
                    self.done.emit(text)
                else:
                    self.failed.emit(i18n.tr("模型返回了空内容，换个说法再试"))
                return
            for raw in resp:
                if self._stop:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data in ("[DONE]", ""):
                    continue
                piece = _delta_text(data)
                if piece:
                    self._buf += piece
                    self.chunk.emit(piece)
        if self._stop:
            return
        if self._buf.strip():
            self.done.emit(self._buf)
        else:
            self.failed.emit(i18n.tr("模型返回了空内容，换个说法再试"))


def _delta_text(data: str) -> str:
    try:
        obj = json.loads(data)
    except Exception:  # noqa: BLE001
        return ""
    choices = obj.get("choices") or [{}]
    c = choices[0] or {}
    delta = c.get("delta") or c.get("message") or {}
    return str(delta.get("content") or "")


def _text_from_json(raw: str) -> str:
    try:
        obj = json.loads(raw)
    except Exception:  # noqa: BLE001
        return ""
    if obj.get("error"):
        return ""
    choices = obj.get("choices") or [{}]
    return str(((choices[0] or {}).get("message") or {}).get("content") or "")


# ---------------------------------------------------------------- 提示词

_SYS_JSON = (
    "你是 API 调试工具的测试数据生成器。"
    "根据给定的字段名生成一份真实、合理、可直接发送的 JSON 对象。"
    "要求：键名与给定字段完全一致；值类型符合字段语义（id 用数字或短字符串，"
    "时间用 ISO8601，邮箱/手机号/地址/URL 要像真的）；不要嵌套多余层级；"
    "只输出 JSON 本身，不要解释、不要 markdown 代码块。"
)

_SYS_ERROR = (
    "你是 API 调试助手。用户会给你一次失败的 HTTP 请求信息。"
    "用简体中文简明解释失败原因，再给出 1-3 条可执行的修复建议。"
    "总长度不超过 150 字，不要客套、不要重复请求内容，直接说结论。"
)


def messages_for_json(keys: List[str], method: str = "GET", url: str = "",
                      note: str = "", existing: str = "") -> List[Dict[str, str]]:
    """按字段名生成 JSON：字段来自请求体现有的键或参数表的键。"""
    parts = [f"请求：{method.upper()} {url or '(未填写地址)'}"]
    if keys:
        parts.append("需要生成的字段：" + json.dumps(keys, ensure_ascii=False))
    else:
        parts.append("没有给定字段：请按这个接口的用途，自己设计 3-6 个合理的字段并给值。")
    if existing.strip():
        parts.append("当前请求体（可参考风格，字段以给定字段为准）：\n"
                     + existing.strip()[:1200])
    if note.strip():
        parts.append("额外要求：" + note.strip())
    return [{"role": "system", "content": _SYS_JSON},
            {"role": "user", "content": "\n".join(parts)}]


def messages_for_error(method: str, url: str, status: int = 0, detail: str = "",
                       body: str = "") -> List[Dict[str, str]]:
    parts = [f"请求：{method.upper()} {url or '(未知地址)'}"]
    parts.append(f"结果：{('HTTP ' + str(status)) if status else '请求没有拿到响应'}")
    if detail.strip():
        parts.append("错误信息：" + detail.strip()[:600])
    if body.strip():
        parts.append("响应内容（截断）：\n" + body.strip()[:1200])
    return [{"role": "system", "content": _SYS_ERROR},
            {"role": "user", "content": "\n".join(parts)}]


# 脚本生成：把可用 API 写死在提示词里，模型没有空间「自由发挥」，
# 也只能产出这个沙箱里真正能跑的东西（没有 require / fetch / import）。
_SYS_SCRIPT = (
    "你是 API 调试工具里的 JavaScript 脚本助手，负责写「{where}」里的代码。"
    "默认把用户的话当成代码需求：直接写一段能跑的 JavaScript 去完成它。\n"
    "输出规则：\n"
    "1. 只输出 JavaScript 代码本身 —— 不要 Markdown 代码块标记、不要解释段落；\n"
    "2. 优先用下面列出的运行时 API；沙箱里没有 require / import / fetch / DOM / setTimeout，"
    "遇到这类思路就用等价写法绕过去，而不是拒绝写；\n"
    "3. 需求说得不完整就按最合理的理解补全，不要反问、不要说「做不到」；\n"
    "4. 需要输出信息就用 console.log，代码保持简短可读。\n"
    "可用 API：\n{api}"
)

_API_PRE = (
    "req.url / req.method / req.headers / req.params / req.body / req.cookies\n"
    "req.setHeader(name, value) / req.getHeader(name) / req.removeHeader(name)\n"
    "req.setParam(name, value) / req.removeParam(name) / req.setBody(text)\n"
    "req.json()\n"
    "pw.env.get(name) / pw.env.set(name, value) / pw.env.unset(name) / pw.env.has(name)\n"
    "pw.env.resolve(\"{{token}}\") / pw.env.toObject()\n"
    "console.log / info / warn / error\n"
    "test(name, function () { ... })"
)

_API_POST = (
    "res.status / res.statusText / res.time / res.body / res.headers\n"
    "res.getHeader(name) / res.setHeader(name, value) / res.removeHeader(name)\n"
    "res.json()\n"
    "pw.env.get(name) / pw.env.set(name, value) / pw.env.has(name) / pw.env.resolve(text)\n"
    "console.log / info / warn / error\n"
    "test(name, function () { ... })"
)


def messages_for_script(ask: str, kind: str = "pre", method: str = "GET", url: str = "",
                        body: str = "") -> List[Dict[str, str]]:
    """把一句需求变成脚本。kind=pre 只能碰 req / pw，post 还能读 res。"""
    where = "前置脚本（请求发送前执行）" if kind == "pre" else "后置脚本（收到响应后执行）"
    api = _API_PRE if kind == "pre" else _API_POST
    system = _SYS_SCRIPT.format(where=where, api=api)
    ctx = [f"请求：{method.upper()} {url or '(未填写地址)'}"]
    if body.strip():
        ctx.append("请求体（截断）：\n" + body.strip()[:800])
    ctx.append("需求：" + (ask or "").strip()[:600])
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n".join(ctx)}]


_SYS_DOC = (
    "你是技术文档编辑。用户给你一个 HTTP 请求和它的响应，请补写接口文档里最容易被漏掉的部分。"
    "只输出 Markdown，不要重复已有的参数表，不要输出一级标题。"
    "结构固定为三个二级标题：## 接口说明（2-4 句：做什么、什么时候用）、"
    "## 参数含义（只解释真正需要解释的字段，用列表）、"
    "## 常见错误（列出可能的失败情况与处理，用列表）。"
    "语言与用户一致（中文就写中文）；总长度不超过 400 字；不要编造响应里没有的字段。"
)


def messages_for_doc(method: str, url: str, name: str = "", params: str = "",
                     body: str = "", response: str = "") -> List[Dict[str, str]]:
    parts = [f"接口：{name or '(未命名)'} · {method.upper()} {url or '(未知地址)'}"]
    if params.strip():
        parts.append("参数与请求头（截断）：\n" + params.strip()[:900])
    if body.strip():
        parts.append("请求体（截断）：\n" + body.strip()[:900])
    if response.strip():
        parts.append("响应示例（截断）：\n" + response.strip()[:1600])
    else:
        parts.append("还没有响应示例，只写接口说明与常见错误。")
    return [{"role": "system", "content": _SYS_DOC},
            {"role": "user", "content": "\n".join(parts)}]


_SYS_NAME = (
    "给一个 HTTP 请求起名字。只输出名字本身：不超过 12 个汉字（英文用 3 个单词内），"
    "不要引号、不要句号、不要解释、不要 Markdown。"
)


def messages_for_name(method: str, url: str, body: str = "") -> List[Dict[str, str]]:
    parts = [f"{method.upper()} {url or '(未知地址)'}"]
    if body.strip():
        parts.append("请求体（截断）：\n" + body.strip()[:500])
    return [{"role": "system", "content": _SYS_NAME},
            {"role": "user", "content": "\n".join(parts)}]


# ---------------------------------------------------------------- 小工具

def clean_json(text: str) -> str:
    """把模型输出清成纯 JSON：去 ``` 围栏、去掉首尾多余说明。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()
    starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not starts:
        return s
    start = min(starts)
    end = max(s.rfind("}"), s.rfind("]"))
    if end > start:
        return s[start:end + 1]
    return s[start:]


def clean_code(text: str) -> str:
    """模型输出 → 可直接塞进脚本编辑器的代码：去围栏、去掉首尾的解释性文字。"""
    s = (text or "").strip()
    if "```" in s:
        parts = s.split("```")
        # 取最长的一段：通常是围栏里的代码；短段多是语言标记或结尾说明
        s = max(parts[1:] or [s], key=len)
        if s[:12].lower().startswith(("javascript", "js\n", "js\n")):
            s = s.split("\n", 1)[1] if "\n" in s else ""
    lines = [ln.rstrip() for ln in s.strip().split("\n")]
    # 去掉「以下是脚本」这类开场白：第一行不是代码特征就丢
    while lines and lines[0].strip() and not any(
            ch in lines[0] for ch in "=();{}[]\"'`/"):
        lines.pop(0)
    return "\n".join(lines).strip()


def clean_line(text: str, limit: int = 24) -> str:
    """模型输出 → 单行文本（名字、标题）：取第一行、去引号、限长。"""
    for line in (text or "").split("\n"):
        s = line.strip().strip("`\"'“”‘’。.,")
        if s:
            return s[:limit]
    return ""


def json_keys(text: str, limit: int = 24) -> List[str]:
    """从现有请求体里取字段名（只取第一层），拿不到就返回空。"""
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        return [str(k) for k in list(data.keys())[:limit]]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return [str(k) for k in list(data[0].keys())[:limit]]
    return []


def start(messages: List[Dict[str, str]], on_chunk=None, on_done=None, on_error=None,
          cfg: Optional[Dict[str, Any]] = None, **kwargs) -> Optional[Chat]:
    """起一次对话；没配好 Key 时直接回调错误并返回 None，调用方不用判空两次。"""
    cfg = cfg or config()
    ok, why = ready(cfg)
    if not ok:
        if on_error:
            on_error(why)
        return None
    chat = Chat(messages, cfg, **kwargs)
    if on_chunk:
        chat.chunk.connect(on_chunk)
    if on_done:
        chat.done.connect(on_done)
    if on_error:
        chat.failed.connect(on_error)
    # 线程结束后自行回收，调用方只留引用即可
    chat.finished.connect(chat.deleteLater)
    chat.start()
    return chat
