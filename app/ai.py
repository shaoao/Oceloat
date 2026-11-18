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

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "glm": {
        "name": "智谱 GLM",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash-250414",
        "doc": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "key_hint": "在智谱开放平台「API Keys」里创建，形如 xxxxxxxx.yyyyyyyy",
    },
}

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
    return {
        "provider": provider if provider in PROVIDERS else "glm",
        "provider_name": preset["name"],
        "base": (raw.get("base_url") or "").strip().rstrip("/") or preset["base"],
        "model": (raw.get("model") or "").strip() or preset["default_model"],
        "api_key": (raw.get("api_key") or "").strip(),
        "custom_models": list(raw.get("custom_models") or []),
    }


def models_for(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """默认模型 + 用户自加的模型，去重保序。"""
    out = [dict(m) for m in MODELS]
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
