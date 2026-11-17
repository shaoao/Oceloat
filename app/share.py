"""分享辅助：把一次请求 / 响应变成可以贴到文档或群里的东西。

两件事：
1. `to_markdown()` 把请求 + 响应示例拼成一段 Markdown 接口文档 —— 不用手写；
2. `redact()` 把 token / cookie / 密码之类的值打码 —— 截图、贴群、发工单时不漏密钥。

刻意只依赖标准库与项目内的 codegen，不做任何网络请求。
"""
from __future__ import annotations

from . import i18n

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# 命中这些键名的值一律打码（大小写不敏感，包含匹配）
SECRET_HINTS = (
    "authorization", "cookie", "token", "secret", "password", "passwd",
    "api-key", "apikey", "api_key", "x-api-key", "session", "csrf",
    "access_key", "private_key", "client_secret", "signature", "ticket",
    "credential", "auth",
)

MASK = "••••••"

# "key": "value"  /  key=value  /  key: value  ——  JSON、表单、YAML 头都能覆盖
_KV_RE = re.compile(
    r'(?P<key>"?[A-Za-z0-9_.\-\[\]]{1,64}"?\s*[:=]\s*)(?P<val>"[^"\n]{0,400}"|'
    r"'[^'\n]{0,400}'|[^\s,;&}\n]{1,400})"
)
# Authorization: Bearer eyJ...
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._\-+/=]{6,}")
# eyJhbGciOi... 形状的裸 JWT
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")


def is_secret_key(key: str) -> bool:
    k = key.strip().strip('"\'[]').lower()
    return any(h in k for h in SECRET_HINTS)


def _keep_tail(value: str) -> str:
    """短值直接全打码；长值留末尾 4 位，方便对账「是不是同一把钥匙」。"""
    raw = value.strip().strip('"\'')
    if len(raw) < 12:
        return MASK
    return f"{MASK}{raw[-4:]}"


def redact_text(text: str) -> str:
    """把文本里看起来像密钥的值替换掉，其余内容原样保留（不改缩进/顺序）。"""
    if not text:
        return text

    def _kv(m: "re.Match[str]") -> str:
        key = m.group("key")
        name = key.split(":")[0].split("=")[0].strip().strip('"')
        if not is_secret_key(name):
            return m.group(0)
        val = m.group("val")
        quote = val[0] if val[:1] in ('"', "'") and val[-1:] == val[:1] else ""
        body = val[1:-1] if quote else val
        # Authorization: Bearer xxx —— 保留方案名，只打码凭据部分
        low = body.lower()
        if low in ("bearer", "basic", "token", "digest"):
            return m.group(0)          # 只截到方案名，交给下面的 Bearer 规则处理后半段
        for scheme in ("bearer ", "basic ", "token ", "digest "):
            if low.startswith(scheme):
                return f"{key}{body[:len(scheme)]}{MASK}"
        masked = _keep_tail(body)
        return f"{key}{quote}{masked}{quote}"

    out = _KV_RE.sub(_kv, text)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)} {MASK}", out)
    out = _JWT_RE.sub(MASK, out)
    return out


def redact_headers(headers: Iterable[Tuple[str, str]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for k, v in headers:
        out.append((k, _keep_tail(v) if is_secret_key(k) else v))
    return out


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _fence(lang: str, body: str) -> List[str]:
    body = body.strip("\n")
    return [f"```{lang}", body, "```"]


def _guess_lang(content_type: str, body: str) -> str:
    ct = (content_type or "").lower()
    if "json" in ct or body.lstrip()[:1] in ("{", "["):
        return "json"
    if "html" in ct:
        return "html"
    if "xml" in ct:
        return "xml"
    return "text"


def to_markdown(
    request: Dict[str, Any],
    response: Optional[Any] = None,
    env: Optional[Dict[str, str]] = None,
    body_limit: int = 4000,
    redact: bool = True,
) -> str:
    """请求 + 响应 → Markdown 接口文档。

    `response` 传 `http_client.Response` 即可；为 None 时只出请求部分（当作草稿文档）。
    """
    from .codegen import _prepare        # 复用同一套变量替换 / 参数拼接逻辑

    d = _prepare(request, env or {})
    title = (request.get("name") or "Untitled Request").strip()
    method = d["method"]
    url = d["url"]
    lines: List[str] = [f"# {title}", ""]
    lines.append(f"`{method}` {url}")
    lines.append("")

    # ---------------- 概览：先让人一眼看清是什么接口
    status = getattr(response, "status", 0) if response is not None else 0
    reason = (getattr(response, "reason", "") or "") if response is not None else ""
    elapsed = int(getattr(response, "elapsed", 0) or 0) if response is not None else 0
    size = int(getattr(response, "size", 0) or 0) if response is not None else 0
    ct = (getattr(response, "content_type", "") or "") if response is not None else ""
    lines += [
        "## " + i18n.tr("概览"), "",
        f"| {i18n.tr('项目')} | {i18n.tr('内容')} |", "| --- | --- |",
        f"| {i18n.tr('方法')} | `{method}` |",
        f"| {i18n.tr('地址')} | `{url}` |",
    ]
    if response is not None:
        lines.append(f"| {i18n.tr('状态')} | **{status} {reason}**".strip() + " |")
        lines.append(f"| {i18n.tr('耗时')} | {elapsed} ms |")
        lines.append(f"| {i18n.tr('体积')} | {_fmt_size(size)} |")
        if ct:
            lines.append(f"| {i18n.tr('内容类型')} | `{ct}` |")
    lines.append("")

    params = [(str(r.get("key")), str(r.get("value", "")))
              for r in request.get("params", [])
              if r.get("enabled", True) and r.get("key") and r.get("type") != "file"]
    if params:
        lines += ["## " + i18n.tr("Query 参数"), "",
                  f"| {i18n.tr('参数')} | {i18n.tr('值')} |", "| --- | --- |"]
        for k, v in params:
            lines.append(f"| `{k}` | {('`' + _keep_tail(v) + '`') if (redact and is_secret_key(k)) else v} |")
        lines.append("")

    headers = redact_headers(d["headers"]) if redact else d["headers"]
    if headers:
        lines += ["## " + i18n.tr("请求头"), "",
                  f"| Header | {i18n.tr('值')} |", "| --- | --- |"]
        for k, v in headers:
            lines.append(f"| `{k}` | {v} |")
        lines.append("")

    # ---------------- 鉴权：把 auth 配置翻译成人话
    auth = request.get("auth") or {}
    atype = (auth.get("type") or "none").lower()
    if atype != "none":
        token = auth.get("token") or auth.get("value") or ""
        if redact and token:
            token = _keep_tail(token)
        scheme = {"bearer": "Authorization: Bearer <token>",
                  "basic": "Authorization: Basic base64(user:password)",
                  "apikey": i18n.tr("请求头 / 查询参数里带 API Key"),
                  }.get(atype, atype)
        lines += ["## " + i18n.tr("鉴权"), "", f"{i18n.tr('类型')}：`{atype}`", "",
                  f"{i18n.tr('发送方式')}：`{scheme}`"]
        if token:
            lines.append("")
            lines.append(f"{i18n.tr('当前凭据')}：`{token}`")
        lines.append("")

    # ---------------- Cookies
    cookies = [(str(r.get("key")), str(r.get("value", "")))
               for r in request.get("cookies", [])
               if r.get("enabled", True) and r.get("key")]
    if cookies:
        lines += ["## Cookies", "", f"| {i18n.tr('名称')} | {i18n.tr('值')} |", "| --- | --- |"]
        for k, v in cookies:
            lines.append(f"| `{k}` | `{_keep_tail(v) if redact else v}` |")
        lines.append("")

    body_text = d["body"]
    if body_text:
        shown = redact_text(body_text) if redact else body_text
        lang = "json" if body_text.lstrip()[:1] in ("{", "[") else "text"
        lines += ["## " + i18n.tr("请求体"), ""] + _fence(lang, shown)
        lines.append("")
    elif d["form"]:
        lines += ["## " + i18n.tr("表单字段"), "",
                  f"| {i18n.tr('字段')} | {i18n.tr('值')} |", "| --- | --- |"]
        for k, v in d["form"]:
            lines.append(f"| `{k}` | {v if not (redact and is_secret_key(k)) else _keep_tail(v)} |")
        lines.append("")

    note = (request.get("note") or "").strip()
    if note:
        lines += ["## " + i18n.tr("说明"), "", "> " + note.replace("\n", " "), ""]

    if response is not None:
        err = getattr(response, "error", "") or ""
        lines += ["## " + i18n.tr("响应"), ""]
        if err:
            lines += [f"> {i18n.tr('请求失败')}：{err}", ""]
        else:
            bits = [f"**{status} {reason}**".strip(),
                    f"{i18n.tr('耗时')} {elapsed} ms",
                    f"{i18n.tr('体积')} {_fmt_size(size)}"]
            if ct:
                bits.append(f"`{ct}`")
            lines += [" · ".join(bits), ""]

        # 响应头（最多 12 条，太长就截断）
        heads = getattr(response, "headers", None) or []
        try:
            pairs = list(heads.items()) if isinstance(heads, dict) else list(heads)
            items = [(str(k), str(v)) for k, v in pairs[:12]]
        except Exception:       # noqa: BLE001
            items = []
        if items:
            lines += ["### " + i18n.tr("响应头"), "",
                      f"| Header | {i18n.tr('值')} |", "| --- | --- |"]
            for k, v in items:
                lines.append(f"| `{k}` | {str(v)[:120]} |")
            lines.append("")

        try:
            text = response.text() if hasattr(response, "text") else ""
        except Exception:       # noqa: BLE001 — 文档生成不能因为解码失败而中断
            text = ""
        if text:
            shown = redact_text(text) if redact else text
            truncated = len(shown) > body_limit
            if truncated:
                shown = shown[:body_limit].rstrip() + "\n" + i18n.tr("…（已截断，完整内容请在 Ocelot 里查看）")
            lines += ["### " + i18n.tr("响应示例"), ""] + _fence(_guess_lang(ct, text), shown)
            lines.append("")

        # 状态码语义：写文档时最容易被漏掉、但读的人最需要的一段
        lines += ["## " + i18n.tr("状态码"), "",
                  f"| {i18n.tr('状态码')} | {i18n.tr('含义')} |", "| --- | --- |"]
        lines.append(f"| {status} | {_status_meaning(status, reason)} |")
        for code, text_ in _COMMON_STATUS:
            if code != status:
                lines.append(f"| {code} | {i18n.tr(text_)} |")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


_COMMON_STATUS: List[Tuple[int, str]] = [
    (200, "成功，响应体里带业务数据"),
    (201, "创建成功，通常返回新资源的 id"),
    (400, "参数错误或缺少必填字段"),
    (401, "未登录 / 凭据失效"),
    (403, "已登录但没有权限"),
    (404, "资源不存在"),
    (429, "触发限流，需要退避重试"),
    (500, "服务端异常"),
]


def _status_meaning(status: int, reason: str = "") -> str:
    for code, text_ in _COMMON_STATUS:
        if code == status:
            return text_
    if reason:
        return reason
    if 200 <= status < 300:
        return "成功"
    if 300 <= status < 400:
        return "重定向"
    if 400 <= status < 500:
        return "客户端错误"
    if status >= 500:
        return "服务端错误"
    return "未知状态"


def to_share_text(
    request: Dict[str, Any],
    response: Optional[Any] = None,
    env: Optional[Dict[str, str]] = None,
) -> str:
    """贴到群里的极简版本：一行方法 URL + 状态 + 关键响应头 + 响应体前 800 字。"""
    from .codegen import _prepare

    d = _prepare(request, env or {})
    lines = [f"{d['method']} {d['url']}"]
    if response is not None:
        lines.append(f"{getattr(response, 'status', 0)} {getattr(response, 'reason', '')}".strip())
        try:
            text = response.text()
        except Exception:       # noqa: BLE001
            text = ""
        if text:
            lines.append("")
            lines.append(redact_text(text[:800]))
    return "\n".join(lines)


def json_key_diff(old: Any, new: Any, path: str = "", out: Optional[List[str]] = None) -> List[str]:
    """只比结构不比值：新增 / 缺失 / 类型变化，用来发现接口悄悄改字段。"""
    if out is None:
        out = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in new:
            if k not in old:
                out.append(f"+ {path}.{k}" if path else f"+ {k}")
            else:
                json_key_diff(old[k], new[k], f"{path}.{k}" if path else k, out)
        for k in old:
            if k not in new:
                out.append(f"- {path}.{k}" if path else f"- {k}")
    elif isinstance(old, list) and isinstance(new, list):
        if old and new:
            json_key_diff(old[0], new[0], f"{path}[0]", out)
    elif type(old) is not type(new) and old is not None and new is not None:
        out.append(f"~ {path}: {type(old).__name__} → {type(new).__name__}")
    return out


def schema_keys(data: Any, prefix: str = "", depth: int = 2, out: Optional[List[str]] = None) -> List[str]:
    """列出响应结构里的键路径，用于写文档时快速看清字段。"""
    if out is None:
        out = []
    if depth <= 0:
        return out
    if isinstance(data, dict):
        for k, v in data.items():
            p = f"{prefix}.{k}" if prefix else k
            out.append(p)
            schema_keys(v, p, depth - 1, out)
    elif isinstance(data, list) and data:
        schema_keys(data[0], f"{prefix}[0]", depth - 1, out)
    return out


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:       # noqa: BLE001
        return None
