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

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections import OrderedDict
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

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "glm": {
        "name": "智谱 GLM",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash-250414",
        "doc": "https://bigmodel.cn/usercenter/proj-mgmt/apikeys",
        "key_hint": "在智谱开放平台「API Keys」里创建，形如 xxxxxxxx.yyyyyyyy",
        "models": MODELS,
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
    # 只保留智谱一家：provider / key_by_provider 是旧版本遗留，读一次保证老配置不丢。
    keys = raw.get("key_by_provider") or {}
    api_key = str(keys.get("glm") or "").strip() or (raw.get("api_key") or "").strip()
    return {
        "provider": "glm",
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
    preset = PROVIDERS["glm"]
    base = MODELS
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
    "你是 API 调试工具里的测试数据生成器。用户会给出字段名、接口上下文和可选要求。"
    "产出一份可直接发送的 JSON：\n"
    "1. 键名严格照抄给定字段，顺序一致；不新增字段、不漏字段；\n"
    "2. 值要像这个接口真实会收到的数据：根据字段名和 URL 语义推断业务含义"
    "（user_id 用短数字，created_at 用 ISO8601，email/phone/url 符合格式且彼此一致，"
    "金额是正数两位小数，状态值用接口语义里合理的枚举）；\n"
    "3. 字段之间有逻辑关系时保持一致（例如 start_at 早于 end_at，姓名与邮箱对应）；\n"
    "4. 不确定语义的字段用简短、类型正确的占位值，不要写「测试」「test123」这类敷衍值；\n"
    "5. 只输出 JSON 本身，不要解释、不要 Markdown 围栏。"
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


# ---------------------------------------------------------------- 响应分析
# 按当前页签切换关注点：同一份响应在「响应头」和「时间线」里该说的话完全不同。
_SYS_ANALYZE_BASE = (
    "你是资深 API 调试与线上排障专家，正在为专业开发者分析一次真实请求。"
    "只依据给定事实下结论，禁止脑补接口文档里没有的约定；每个判断都要点出具体字段名和值。\n"
    "铁律（违反任意一条都算不合格）：\n"
    "1）HTTP 状态码是传输层结果：2xx 一律判定请求成功。"
    "绝不因为响应体里出现 code:1 / code:1001 之类数字就说「返回错误码」。"
    "业务 code 必须结合 msg / message / success / data / error 判断："
    "msg 是祝福语或正常文案、data 有内容、success 非 false 时，判为成功，"
    "并说明该服务用 code 表示业务子状态；只有 msg 明确报错、success=false、"
    "或 data 为空且伴随错误文案时才判业务失败，并原样引用错误文案。\n"
    "2）先结论、后证据。结论一句话，给出明确判定（成功 / 业务失败 / 传输失败 / 需人工确认）"
    "和最关键的一条证据，不许模棱两可。\n"
    "3）每个发现写成「现象（字段=值）→ 影响 → 依据」，级别只用：阻断 / 警告 / 提示 / 正常，"
    "按严重程度排序。不做无证据的猜测，不写教科书式清单。\n"
    "4）没异常就直说「未发现异常」，并列出支撑判断的字段与值；不为凑字数制造问题。\n"
    "5）建议必须可执行：指明改哪个字段 / 头部 / 参数、改成什么、为什么；"
    "涉及安全与性能要标出风险等级，不写「建议查看文档」这类空话。\n"
    "输出格式（简体中文 Markdown，不要一级标题，全文 350-600 字）：\n"
    "## 结论\n一句话判定 + 一句最关键证据。\n"
    "## 关键发现\n按严重程度排序 3-6 条，每条以 `- **级别｜短标题**：` 开头，"
    "随后用反引号写出 `字段=值`，再说影响；没有发现就写一条"
    "`- **正常｜未发现异常**：` 并给出支撑字段。\n"
    "## 逐项解读\n按「当前查看的页面」关注点逐条分析，引用具体字段 / 头部 / 数值，4-8 条。\n"
    "## 排查建议\n用 `1.` 编号写 1-3 条动作，每条指明改什么、改成什么、为什么；"
    "没有问题写「无需调整」。"
)

_TAB_FOCUS = {
    "pretty": "关注点：响应体的业务语义与数据质量。判断 code / msg / data 是否自洽，"
              "字段是否缺失、为 null 或类型漂移，分页与时间戳是否合理，"
              "是否有 token / 密码 / 身份证等敏感信息明文回显；指出哪些字段能证明成功或失败。",
    "tree": "关注点：JSON 树形结构。指出层级是否过深、数组元素是否同构、"
            "键名风格是否一致、空值与类型漂移出现在哪一层、是否有大数组会拖慢前端渲染；"
            "给出能直接照着取值的层级路径。",
    "raw": "关注点：原始报文。核对编码与 BOM、换行符、Content-Type 与实际内容是否匹配，"
           "检查转义异常、截断痕迹、gzip / chunked 残留；从正文首几行推断真实格式与解析风险。",
    "headers": "关注点：响应头。逐项解释 Content-Type / Cache-Control / ETag / Last-Modified / "
               "Set-Cookie / Access-Control-Allow-Origin / Content-Encoding / Location / Server / "
               "Strict-Transport-Security；重点指出缓存策略是否自相矛盾、CORS 能否放行当前源、"
               "安全头缺失、压缩与长连接对性能的影响，并给出具体头部改法。",
    "cookies": "关注点：Cookies。逐个分析名称、Domain / Path 作用域、expires 与 Max-Age、"
               "Secure / HttpOnly / SameSite 组合，指出会话固定、跨站携带、过期失效风险；"
               "按风险等级给出属性修改建议。",
    "console": "关注点：脚本控制台。逐条分析前置脚本对请求方法 / 头部 / 参数的改动、"
               "后置脚本提取了哪些变量、每条断言通过还是失败、错误堆栈指向哪一行；"
               "定位到具体脚本行号并给出可直接替换的修法。",
    "preview": "关注点：预览。判断响应能否被正确渲染，说明适合的预览方式；"
               "若是图片 / 音视频 / PDF，指出格式、体积、解码失败或加载超时的具体原因，"
               "并区分是内容问题还是头部声明问题。",
    "diff": "关注点：与基准响应的差异。逐项列出新增 / 删除 / 值变化的字段及变化量，"
            "结合字段语义区分正常波动与回归；指出受影响的下游逻辑范围，"
            "并标明最可疑的一次变化。",
    "extract": "关注点：JSON 路径提取。判断给定路径是否指向预期值、返回类型是否符合下游用法、"
               "路径是否依赖数组下标而脆弱；给出更稳的等价写法（过滤条件 / 取首个匹配 / "
               "空值兜底），并说明原路径在什么数据下会取错。",
    "timeline": "关注点：时间线。分解 DNS / TCP / TLS / 请求发送 / 等待首字节 / 内容传输各段耗时，"
                "找出最慢环节与离群点，分析耗时趋势与抖动，比较多次请求是否持续变慢；"
                "结合状态码与响应体大小判断是服务端慢、网络慢还是本地处理慢，"
                "指出最可疑的一次并给排查动作。",
    "error": "关注点：请求没有拿到正常响应。依据错误文案与阶段区分 DNS 解析失败、"
             "连接被拒、TLS 证书 / 协议不匹配、超时、代理配置、CORS 预检被拦、"
             "本地脚本异常；给出最可能的原因排序和 1-3 步可立即执行的排查动作。",
}


def messages_for_analysis(ctx: Dict[str, Any]) -> List[Dict[str, str]]:
    """把「当前页签 + 请求 + 响应」打包成一次差异化分析对话。"""
    tab = str(ctx.get("tab") or "pretty")
    focus = _TAB_FOCUS.get(tab, _TAB_FOCUS["pretty"])
    parts = [
        f"当前查看的页面：{ctx.get('tab_label') or tab}（key={tab}）",
        focus,  # _TAB_FOCUS 的值本身已带「关注点：」前缀，别再拼一层
    ]
    req = ctx.get("request") or {}
    if req:
        lines = [f"请求：{str(req.get('method') or 'GET').upper()} {req.get('url') or '(未知地址)'}"]
        for h in (req.get("headers") or [])[:12]:
            if h.get("key"):
                lines.append(f"  请求头 {h['key']}: {str(h.get('value', ''))[:120]}")
        for p in (req.get("params") or [])[:12]:
            if p.get("key"):
                lines.append(f"  参数 {p['key']}={str(p.get('value', ''))[:120]}")
        body = str((req.get("body") or {}).get("raw") or "")[:500]
        if body.strip():
            lines.append("  请求体（截断）：" + body.strip())
        parts.append("\n".join(lines))

    meta = [f"HTTP {ctx.get('status') or 0} {ctx.get('reason') or ''}".strip()]
    if ctx.get("elapsed_ms"):
        meta.append(f"耗时 {ctx['elapsed_ms']} ms")
    if ctx.get("size"):
        meta.append(f"体积 {ctx['size']} B")
    if ctx.get("content_type"):
        meta.append(f"类型 {ctx['content_type']}")
    parts.append("响应概况：" + " · ".join(meta))

    for label, key, limit in (
        ("响应头", "headers", 2200), ("Cookies", "cookies", 1800),
        ("控制台日志", "console", 2200), ("对比差异", "diff", 2200),
        ("时间线", "timeline", 1800), ("提取结果", "extract", 900),
        ("预览信息", "preview", 900),
    ):
        value = ctx.get(key)
        if not value:
            continue
        text = value if isinstance(value, str) else json.dumps(
            value, ensure_ascii=False, indent=2, default=str)
        parts.append(f"{label}：\n{text.strip()[:limit]}")

    body = str(ctx.get("body") or "").strip()
    if body:
        # 分析页签不是正文时也要给一份截断正文，避免 AI 脱离数据说话
        parts.append("响应正文（截断）：\n" + body[:2600])
    if ctx.get("error"):
        parts.append("错误信息：" + str(ctx["error"]).strip()[:1000])
    return [{"role": "system", "content": _SYS_ANALYZE_BASE},
            {"role": "user", "content": "\n\n".join(parts)}]


# ---------------------------------------------------------------- 分析结果缓存
# 同一「页签 + 请求 + 响应」再看一次不必重新烧 token；但缓存只在内存里，
# 有条数上限和过期时间，窗口一关就跟着释放，不会越攒越多。
def analysis_key(ctx: Dict[str, Any]) -> str:
    """给一次分析上下文算指纹。长正文截断即可——提示词本来也只看这段。"""
    req = ctx.get("request") or {}
    payload = {
        "tab": ctx.get("tab"),
        "status": ctx.get("status"),
        "reason": ctx.get("reason"),
        "method": str(req.get("method") or "").upper(),
        "url": req.get("url"),
        "req_headers": req.get("headers"),
        "req_params": req.get("params"),
        "req_body": str((req.get("body") or {}).get("raw") or "")[:1500],
        "body": str(ctx.get("body") or "")[:4000],
        "headers": ctx.get("headers"),
        "cookies": ctx.get("cookies"),
        "console": ctx.get("console"),
        "diff": str(ctx.get("diff") or "")[:2000],
        "extract": ctx.get("extract"),
        "timeline": ctx.get("timeline"),
        "preview": ctx.get("preview"),
        "error": ctx.get("error"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()


class AnalysisCache:
    """有限容量的分析结果缓存：LRU 淘汰 + TTL 过期 + 显式清空。"""

    MAX = 8          # 最多留 8 份分析（每份 1~2KB，内存占用可忽略但有硬上限）
    TTL = 30 * 60    # 30 分钟没人看就当过期，避免「一直存着」

    def __init__(self) -> None:
        self._data: "OrderedDict[str, tuple]" = OrderedDict()

    def get(self, key: str) -> Optional[str]:
        hit = self._data.get(key)
        if hit is None:
            return None
        ts, text = hit
        if time.time() - ts > self.TTL:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return text

    def put(self, key: str, text: str) -> None:
        if not text:
            return
        self._data[key] = (time.time(), text)
        self._data.move_to_end(key)
        self._prune()

    def clear(self) -> None:
        self._data.clear()

    def _prune(self) -> None:
        now = time.time()
        for key in [k for k, (ts, _text) in self._data.items() if now - ts > self.TTL]:
            self._data.pop(key, None)
        while len(self._data) > self.MAX:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)


_SYS_DOC = (
    "你是资深 API 文档作者。用户给你一次真实请求与响应，请补写自动文档最缺的「人话解释」。"
    "只输出 Markdown，不要一级标题，不要重复已有参数表的条目。\n"
    "结构固定为三个二级标题：\n"
    "## 接口说明：2-4 句，说清这个接口解决什么问题、什么时候调用、请求体关键约束；\n"
    "## 参数含义：只解释真正需要解释的字段（枚举、格式、条件必填、易混淆项），"
    "每条写「字段名：含义 + 取值建议」；\n"
    "## 常见错误：从响应证据出发列出可能的失败场景与对应处理，不要列教科书式清单。\n"
    "严格按证据写：响应里没有的字段不编造，业务 code 的含义按 msg/data 判断。"
    "总长度 250-450 字，语言与用户一致。"
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
    "给一个 HTTP 请求起一个让人一眼看懂的名字。只输出名字本身，不要引号、标点或解释。\n"
    "规则：1) 用「动作 + 对象」或业务含义命名，例如「查询用户订单」「提交登录」；"
    "2) 不超过 10 个汉字（英文不超过 3 个单词）；3) 禁止照抄 URL 末段、"
    "禁止「获取接口」「API 请求」这类空话；4) 同名路径但方法不同要体现动作差异。"
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
