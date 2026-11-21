"""GraphQL 纯逻辑：请求体组装、Schema 内省、补全上下文、变量同步、查询骨架。

不依赖 Qt，能被发送层 / 代码生成 / 导入导出 / 测试直接调用。
存储形状（挂在 request.body 上，与其它 body 模式共存，不新增顶层字段）：
    {"mode": "graphql", "raw": <query>, "gql_vars": <变量 JSON 文本>, "gql_op": <操作名>}
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

INTROSPECTION = (
    "query IntrospectionQuery{__schema{queryType{name}mutationType{name}"
    "subscriptionType{name}types{kind name description "
    "fields(includeDeprecated:true){name description isDeprecated "
    "args{name type{...T}}type{...T}}"
    "inputFields{name type{...T}}enumValues(includeDeprecated:true){name}}}}"
    "fragment T on __Type{kind name ofType{kind name ofType{kind name "
    "ofType{kind name ofType{kind name}}}}}"
)

def _t(template: str, **kw) -> str:
    try:
        from .i18n import trf
        return trf(template, **kw)
    except ImportError:
        return template.format(**kw)


_OP_RE = re.compile(r"\b(query|mutation|subscription)\s+([_A-Za-z]\w*)")
_VAR_RE = re.compile(r"\$([_A-Za-z]\w*)\s*:\s*([\[\]!\w]+)")
_STR_RE = re.compile(r'"""[\s\S]*?"""|"(?:[^"\\\n]|\\.)*"|#[^\n]*')


# ---------------------------------------------------------------- 请求体
def operations(query: str) -> List[str]:
    """文档里具名操作的名字（按出现顺序）。"""
    return [m.group(2) for m in _OP_RE.finditer(_strip(query or ""))]


def payload(body: Dict[str, Any]) -> Dict[str, Any]:
    """body → 标准 GraphQL over HTTP 载荷。变量写坏时原样带字符串，由服务端报错，
    不在本地静默吞掉（否则用户看不出变量为什么没生效）。"""
    query = body.get("raw") or ""
    out: Dict[str, Any] = {"query": query}
    text = (body.get("gql_vars") or "").strip()
    if text:
        try:
            out["variables"] = json.loads(text)
        except ValueError:
            out["variables"] = text
    op = (body.get("gql_op") or "").strip()
    ops = operations(query)
    if op and op in ops:
        out["operationName"] = op
    elif len(ops) > 1:
        out["operationName"] = ops[0]
    return out


def payload_text(body: Dict[str, Any]) -> str:
    return json.dumps(payload(body), ensure_ascii=False)


def check(query: str, variables: str = "") -> str:
    """轻量校验：括号配对 + 变量 JSON。返回空串表示通过，否则给一句人话。"""
    src = _strip(query or "")
    if not src.strip():
        return ""
    stack: List[Tuple[str, int]] = []
    pairs = {"}": "{", ")": "(", "]": "["}
    for i, ch in enumerate(src):
        if ch in "{([":
            stack.append((ch, i))
        elif ch in pairs:
            if not stack or stack[-1][0] != pairs[ch]:
                return _t("第 {n} 行多了一个 {ch}", n=src.count(chr(10), 0, i) + 1, ch=ch)
            stack.pop()
    if stack:
        ch, i = stack[-1]
        return _t("第 {n} 行的 {ch} 没有闭合", n=src.count(chr(10), 0, i) + 1, ch=ch)
    if (variables or "").strip():
        try:
            if not isinstance(json.loads(variables), dict):
                return _t("变量必须是 JSON 对象")
        except ValueError as exc:
            return _t("变量 JSON 有误：{msg}（第 {n} 行）", msg=exc.msg, n=exc.lineno)
    return ""


def sync_variables(query: str, variables: str) -> str:
    """按查询里声明的 $变量 补齐变量 JSON：缺的按类型给占位值，多余的保留。"""
    try:
        data = json.loads(variables) if (variables or "").strip() else {}
        if not isinstance(data, dict):
            data = {}
    except ValueError:
        return variables
    for name, typ in _VAR_RE.findall(_strip(query or "")):
        data.setdefault(name, _placeholder(typ))
    return json.dumps(data, ensure_ascii=False, indent=2) if data else ""


def _placeholder(typ: str) -> Any:
    base = typ.strip("[]!")
    if typ.lstrip().startswith("["):
        return []
    return {"Int": 0, "Float": 0.0, "Boolean": False}.get(base, "")


def pretty(query: str) -> str:
    """按花括号层级重排缩进；字符串和注释原样保留。"""
    out: List[str] = []
    depth = 0
    for line in (query or "").splitlines():
        s = line.strip()
        if not s:
            if out and out[-1]:
                out.append("")
            continue
        bare = _strip(s)
        lead = len(bare) - len(bare.lstrip("})"))
        out.append("  " * max(0, depth - lead) + s)
        depth = max(0, depth + bare.count("{") + bare.count("(")
                    - bare.count("}") - bare.count(")"))
    return "\n".join(out).strip() + "\n"


def _strip(text: str) -> str:
    """把字符串 / 注释换成等长空白，括号统计和正则不会被里面的内容干扰。"""
    return _STR_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group()), text)


# ---------------------------------------------------------------- Schema
class Schema:
    """内省结果的精简索引：类型名 → 字段表。只留补全和骨架要用的东西。"""

    def __init__(self, raw: Dict[str, Any]):
        data = raw.get("data", raw) if isinstance(raw, dict) else {}
        sch = (data or {}).get("__schema") or {}
        self.roots = {k: ((sch.get(f"{k}Type") or {}).get("name") or "")
                      for k in ("query", "mutation", "subscription")}
        self.types: Dict[str, Dict[str, Any]] = {}
        for t in sch.get("types") or []:
            name = t.get("name") or ""
            if not name or name.startswith("__"):
                continue
            fields = {}
            for f in (t.get("fields") or t.get("inputFields") or []):
                fields[f["name"]] = {
                    "type": _type_name(f.get("type")),
                    "sig": _type_sig(f.get("type")),
                    "args": [(a["name"], _type_sig(a.get("type"))) for a in f.get("args") or []],
                    "desc": (f.get("description") or "").strip(),
                    "deprecated": bool(f.get("isDeprecated")),
                }
            self.types[name] = {"kind": t.get("kind"), "fields": fields,
                                "enum": [e["name"] for e in t.get("enumValues") or []]}
        if not self.roots["query"]:
            raise ValueError(_t("返回内容里没有 __schema，服务端可能关闭了内省"))

    def fields(self, type_name: str) -> Dict[str, Dict[str, Any]]:
        return (self.types.get(type_name) or {}).get("fields") or {}

    def is_leaf(self, type_name: str) -> bool:
        return (self.types.get(type_name) or {}).get("kind") in (None, "SCALAR", "ENUM")

    def counts(self) -> Tuple[int, int]:
        return len(self.fields(self.roots["query"])), len(self.fields(self.roots["mutation"]))

    def summary(self, limit: int = 60) -> str:
        """给 AI 看的 Schema 摘要：根字段 + 签名，控制在几 KB。"""
        lines = []
        for kind in ("query", "mutation"):
            for name, f in list(self.fields(self.roots[kind]).items())[:limit]:
                args = ", ".join(f"{a}: {t}" for a, t in f["args"])
                lines.append(f"{kind} {name}({args}): {f['sig']}")
        return "\n".join(lines)


def _type_name(t: Optional[Dict[str, Any]]) -> str:
    while t and t.get("ofType") and not t.get("name"):
        t = t["ofType"]
    return (t or {}).get("name") or ""


def _type_sig(t: Optional[Dict[str, Any]]) -> str:
    if not t:
        return ""
    kind = t.get("kind")
    if kind == "NON_NULL":
        return _type_sig(t.get("ofType")) + "!"
    if kind == "LIST":
        return "[" + _type_sig(t.get("ofType")) + "]"
    return t.get("name") or ""


# ---------------------------------------------------------------- 补全
def context_type(schema: Schema, text: str, pos: int) -> Optional[str]:
    """光标所在选择集对应的类型名。顺着花括号往外找「字段名 {」链，逐层解析。

    片段（fragment X on T / ... on T）直接以 T 为起点；找不到就回到根类型。
    返回 None 表示光标在参数括号里或无法判断，此时不弹补全。
    """
    src = _strip(text[:pos])
    if src.count("(") > src.count(")"):
        return None
    chain: List[str] = []
    depth = 0
    i = len(src) - 1
    while i >= 0:
        ch = src[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth:
                depth -= 1
            else:
                head = src[:i].rstrip()
                head = re.sub(r"\([^()]*\)\s*$", "", head).rstrip()
                head = re.sub(r"(@\w+(\([^()]*\))?\s*)+$", "", head).rstrip()
                m = re.search(r"(?:\bon\s+([_A-Za-z]\w*)|([_A-Za-z]\w*))$", head)
                if not m:
                    chain.append("")            # 匿名 { ... }：即查询根
                    break
                if m.group(1):
                    chain.append("on:" + m.group(1))
                    break
                word = m.group(2)
                before = head[:m.start()].rstrip()
                if word in ("query", "mutation", "subscription") or \
                        re.search(r"\b(query|mutation|subscription)$", before):
                    chain.append("root:" + (word if word in schema.roots else
                                            before.split()[-1]))
                    break
                chain.append(word)
        i -= 1
    if not chain:
        return None
    top = chain.pop()
    if top.startswith("on:"):
        cur = top[3:]
    elif top.startswith("root:"):
        cur = schema.roots.get(top[5:]) or schema.roots["query"]
    elif top == "":
        cur = schema.roots["query"]
    else:
        chain.append(top)
        cur = schema.roots["query"]
    for field in reversed(chain):
        f = schema.fields(cur).get(_alias_target(field))
        if not f:
            return None
        cur = f["type"]
    return cur


def _alias_target(word: str) -> str:
    return word.split(":")[-1].strip()


def suggest(schema: Schema, text: str, pos: int, limit: int = 40) -> Tuple[str, List[Dict[str, Any]]]:
    """(当前前缀, 候选列表)。候选按「前缀匹配 > 包含」排序，弃用字段沉底。"""
    m = re.search(r"[_A-Za-z]\w*$", text[:pos])
    prefix = m.group() if m else ""
    owner = context_type(schema, text, pos - len(prefix))
    if not owner:
        return prefix, []
    low = prefix.lower()
    rows = []
    for name, f in schema.fields(owner).items():
        n = name.lower()
        if low and low not in n:
            continue
        rank = (0 if n.startswith(low) else 1, f["deprecated"], name)
        rows.append((rank, {"name": name, **f, "leaf": schema.is_leaf(f["type"])}))
    rows.sort(key=lambda r: r[0])
    return prefix, [r[1] for r in rows[:limit]]


def skeleton(schema: Schema, field: str, kind: str = "query", depth: int = 2) -> str:
    """根字段 → 一份可直接发的查询：必填参数提为变量，子字段展开标量到 depth 层。"""
    root = schema.roots.get(kind) or ""
    f = schema.fields(root).get(field)
    if not f:
        return ""
    required = [(a, t) for a, t in f["args"] if t.endswith("!")]
    decl = ", ".join(f"${a}: {t}" for a, t in required)
    call = ", ".join(f"{a}: ${a}" for a, _ in required)
    name = field[:1].upper() + field[1:]
    head = f"{kind} {name}" + (f"({decl})" if decl else "")
    body = _selection(schema, f["type"], depth, 2)
    line = f"  {field}" + (f"({call})" if call else "")
    return f"{head} {{\n{line}{(' ' + body) if body else ''}\n}}\n"


def _selection(schema: Schema, type_name: str, depth: int, indent: int) -> str:
    if schema.is_leaf(type_name) or depth <= 0:
        return ""
    pad = " " * (indent + 2)
    lines = []
    for name, f in schema.fields(type_name).items():
        if f["deprecated"] or any(t.endswith("!") for _, t in f["args"]):
            continue
        if schema.is_leaf(f["type"]):
            lines.append(pad + name)
        elif depth > 1:
            sub = _selection(schema, f["type"], depth - 1, indent + 2)
            if sub:
                lines.append(f"{pad}{name} {sub}")
        if len(lines) >= 12:
            break
    if not lines:
        lines.append(pad + "__typename")
    return "{\n" + "\n".join(lines) + "\n" + " " * indent + "}"


def response_errors(body: bytes) -> List[str]:
    """HTTP 200 但 GraphQL 报错是最常见的坑：把 errors[].message 摘出来。"""
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except (ValueError, AttributeError):
        return []
    errs = data.get("errors") if isinstance(data, dict) else None
    if not isinstance(errs, list):
        return []
    out = []
    for e in errs[:5]:
        if isinstance(e, dict):
            loc = (e.get("locations") or [{}])[0]
            where = _t("（第 {n} 行）", n=loc.get("line")) if loc.get("line") else ""
            out.append(str(e.get("message") or e) + where)
    return out
