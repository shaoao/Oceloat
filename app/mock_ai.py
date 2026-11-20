"""Mock 的 AI 能力：用一句话生成路由 / 响应体 / 测试用例。

约束和 ai.py 保持一致：只拼提示词、只做输出清洗，真正发请求仍走 ai.start()，
所以 Key、模型、流式回调这些都复用同一套设置，不需要第二份配置。

输出格式我们说了算 —— 让模型吐一个固定 schema 的 JSON 数组，解析失败就报
一句人话（「模型没按格式返回，重试一次」），不做花式的自动修复。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

MAX_ROUTES = 20
MAX_CASES = 30
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

_SYS_ROUTES = (
    "你是一个 Mock 服务配置助手。根据用户的业务描述，生成一组 HTTP Mock 路由。\n"
    "只输出 JSON 数组，不要 Markdown 代码块、不要解释。数组每一项的字段：\n"
    '  "name": 6~16 字的中文名，说明这个接口做什么；\n'
    '  "group": 分组名，用「模块/子模块」表示层级，例如 "订单/支付"；\n'
    '  "method": GET/POST/PUT/PATCH/DELETE 之一；\n'
    '  "path": 必须以 / 开头，路径参数用 * 结尾表示前缀匹配，例如 /api/orders/*；\n'
    '  "status": 整数状态码，正常接口用 200；\n'
    '  "body": 响应体的 JSON 对象（不要写成字符串），字段要真实、有中文内容、'
    "至少 6 个字段，列表接口要给出 3~5 条数据；\n"
    '  "delay": 0。\n'
    "要求：接口之间要有内在联系（列表、详情、创建、删除），字段命名一致；"
    "不要输出注释、不要输出多余文字。"
)

_SYS_CASES = (
    "你是一个接口测试工程师。根据给定的 Mock 路由，生成可以直接执行的测试用例。\n"
    "只输出 JSON 数组，不要 Markdown 代码块、不要解释。数组每一项的字段：\n"
    '  "name": 用例名，说明测什么；\n'
    '  "method": HTTP 方法；\n'
    '  "path": 请求路径（可以带查询参数）；\n'
    '  "headers": 请求头对象，没有就 {}；\n'
    '  "body": 请求体字符串，GET 用 ""；\n'
    '  "expect_status": 期望状态码；\n'
    '  "note": 一句话说明断言重点。\n'
    "要求：覆盖正常、参数缺失、边界、鉴权失败四类场景，数量 6~12 条。"
)


_SYS_BODY = (
    "你是 Mock 服务的数据生成器。根据用户的描述，写一段「响应体模板」，只输出模板本身，"
    "不要 Markdown 代码块、不要解释。模板规则（必须用上，不是普通 JSON）：\n"
    "1) 静态字段直接写；随机字段用占位符：{{@name}} {{@cname}} {{@email}} {{@phone}} "
    "{{@city}} {{@company}} {{@uuid}} {{@now}} {{@date}} {{@timestamp}} {{@bool}} "
    "{{@int(1,99)}} {{@float(1,999)}} {{@pick(a,b,c)}} {{@lorem(6)}} {{@avatar(80,80)}}；\n"
    "2) 需要多条数据时用循环，不要手写重复行：\n"
    "   \"list\": [{{for size}}{\"id\": {{@row}}, \"name\": \"{{@cname}}\"}{{/for}}]\n"
    "   循环体不要写逗号，展开时引擎会自动补；循环里可以用 {{@i}}（本次第几条）、"
    "{{@row}}（跨页连续行号）；\n"
    "3) 列表接口要分页：{{for size}} 会按 ?size= 展开，{{@page}} 是当前页，"
    "{{@size}} 是每页条数，{{@total(86)}} 是总数；\n"
    "4) 字段名和值都要像真实业务（价格、时间、状态、枚举都用得上），"
    "至少 5 个字段；金额用数字并保留两位小数；\n"
    "5) 输出必须是合法 JSON（占位符与循环指令不算破坏 JSON）。\n"
    "示例：\n"
    '{"code":0,"message":"ok","data":{"page":{{@page}},"size":{{@size}},'
    '"total":{{@total(86)}},"list":[{{for size}}{"id":{{@row}},"title":"{{@lorem(8)}}",'
    '"author":"{{@cname}}","price":{{@float(9,999)}},"on_sale":{{@bool}},'
    '"created_at":"{{@date}}"}{{/for}}]}}'
)

# AI 面板里的常用例子：点一下就把描述填进去，不用自己组织语言。
BODY_PRESETS = [
    ("分页列表", "分页的商品列表：每页按 ?size 条，包含 id、标题、作者、价格、是否上架、创建时间，"
                 "外层带 page / size / total"),
    ("用户资料", "单个用户资料：中文昵称、邮箱、手机号、城市、头像、会员等级、注册时间"),
    ("订单详情", "一笔订单的详情：订单号、下单时间、商品明细循环 3 条（名称 / 单价 / 数量 / 小计）、"
                 "总金额、状态枚举、收货地址"),
    ("20 条数组", "一个 20 条的数组，每项包含 id、名称、状态、金额、时间"),
    ("401 错误", "鉴权失败的标准错误体：code、错误码、中文提示、请求 id"),
    ("嵌套树", "一个两级分类树：顶级分类带 children，每个分类里有 3 个子分类"),
]

# 「例子」区直接插入的模板片段（不经过模型，点一下就有）。
BODY_SNIPPETS = [
    ("分页列表（模板）",
     '{\n  "code": 0,\n  "message": "ok",\n  "data": {\n'
     '    "page": {{@page}},\n    "size": {{@size}},\n    "total": {{@total(86)}},\n'
     '    "list": [\n{{for size}}\n'
     '      {"id": {{@row}}, "title": "{{@lorem(8)}}", "author": "{{@cname}}", '
     '"price": {{@float(9, 1999)}}, "on_sale": {{@bool}}, "created_at": "{{@date}}"}\n'
     '{{/for}}\n    ]\n  }\n}'),
    ("循环 5 条",
     '{\n  "items": [\n{{for 5}}\n'
     '    {"id": {{@i}}, "name": "{{@cname}}", "amount": {{@float(10, 999)}}}\n'
     '{{/for}}\n  ]\n}'),
    ("条件字段",
     '{\n  "code": 0,\n  "data": {\n    "user": {"id": {{@id}}},\n'
     '    "vip": {{@bool}},\n    "expires_at": "{{@date}}"\n  }\n}'),
]


def messages_for_body(description: str, path: str = "", method: str = "GET",
                      existing: str = "") -> List[Dict[str, str]]:
    """让模型直接产出一段可保存的响应体模板。"""
    parts = [f"接口：{method.upper()} {path or '/'}", f"要求：{description.strip()}"]
    if existing.strip():
        parts.append("现有响应体（在此基础上改，保留其中有用的字段）：\n"
                     + existing.strip()[:2000])
    return [{"role": "system", "content": _SYS_BODY},
            {"role": "user", "content": "\n\n".join(parts)}]


def parse_body(text: str) -> str:
    """把模型输出清成一段模板文本；JSON 会重新缩进，看起来整齐。"""
    from .ai import clean_json

    raw = clean_json(text).strip()
    if not raw:
        raise ValueError("模型没有返回内容")
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return raw            # 带循环指令时可能解析不了，原样返回仍然可用
    return json.dumps(data, ensure_ascii=False, indent=2)


def messages_for_routes(description: str, count: int = 6,
                        existing: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    parts = [f"业务描述：{description.strip()}",
             f"请生成大约 {max(1, min(count, MAX_ROUTES))} 条路由。"]
    if existing:
        names = [f"{r.get('method')} {r.get('path')}" for r in existing[:20]]
        parts.append("已有路由（不要重复，可补充缺失的）：\n" + "\n".join(names))
    return [{"role": "system", "content": _SYS_ROUTES},
            {"role": "user", "content": "\n\n".join(parts)}]


def messages_for_cases(routes: List[Dict[str, Any]], extra: str = "") -> List[Dict[str, str]]:
    lines = []
    for r in routes[:40]:
        line = f"{r.get('method')} {r.get('path')} → {r.get('status')} {r.get('name')}"
        if r.get("group"):
            line = f"[{r['group']}] " + line
        lines.append(line)
    user = "现有 Mock 路由：\n" + "\n".join(lines)
    if extra.strip():
        user += "\n\n补充要求：" + extra.strip()
    return [{"role": "system", "content": _SYS_CASES},
            {"role": "user", "content": user}]


# ---------------------------------------------------------------- 解析
def _load_array(text: str) -> List[Any]:
    from .ai import clean_json

    raw = clean_json(text)
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        # 模型偶尔会用单引号或尾逗号，做一次温和的补救
        fixed = re.sub(r",\s*([}\]])", r"\1", raw.replace("'", '"'))
        try:
            data = json.loads(fixed)
        except (TypeError, ValueError) as exc:
            raise ValueError("模型返回的不是合法 JSON，再试一次通常就好了") from exc
    if isinstance(data, dict):
        data = data.get("routes") or data.get("cases") or data.get("data") or []
    if not isinstance(data, list):
        raise ValueError("模型没有返回数组")
    return data


def _body_text(value: Any) -> str:
    if isinstance(value, str):
        try:
            return json.dumps(json.loads(value), ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(value)


def parse_routes(text: str, default_group: str = "AI 生成") -> List[Dict[str, Any]]:
    """把模型输出清成路由列表；字段不合法就丢掉那一条，不整批失败。"""
    out: List[Dict[str, Any]] = []
    for item in _load_array(text):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        if not path.startswith("/"):
            path = "/" + path
        method = str(item.get("method") or "GET").upper()
        if method not in _METHODS:
            method = "GET"
        try:
            status = int(item.get("status") or 200)
        except (TypeError, ValueError):
            status = 200
        if not 100 <= status <= 599:
            status = 200
        body = item.get("body")
        out.append({
            "id": "",
            "name": str(item.get("name") or f"{method} {path}")[:60],
            "group": str(item.get("group") or default_group)[:80],
            "method": method,
            "path": path,
            "status": status,
            "content_type": "application/json",
            "body": _body_text(body) if body is not None else "{}",
            "delay": 0,
            "echo": False,
            "enabled": True,
            "rules": [],
        })
        if len(out) >= MAX_ROUTES:
            break
    if not out:
        raise ValueError("一条有效路由都没解析出来")
    return out


def parse_cases(text: str) -> List[Dict[str, Any]]:
    """把模型输出清成测试用例列表。"""
    out: List[Dict[str, Any]] = []
    for item in _load_array(text):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip() or "/"
        if not path.startswith("/"):
            path = "/" + path
        headers = item.get("headers")
        try:
            expect = int(item.get("expect_status") or 200)
        except (TypeError, ValueError):
            expect = 200
        out.append({
            "name": str(item.get("name") or f"{path}")[:60],
            "method": str(item.get("method") or "GET").upper(),
            "path": path,
            "headers": headers if isinstance(headers, dict) else {},
            "body": str(item.get("body") or ""),
            "expect_status": expect,
            "note": str(item.get("note") or "")[:120],
        })
        if len(out) >= MAX_CASES:
            break
    if not out:
        raise ValueError("一条用例都没解析出来")
    return out


def case_as_curl(case: Dict[str, Any], base: str) -> str:
    """把一条用例变成能直接粘到终端的 curl。"""
    url = base.rstrip("/") + case.get("path", "/")
    parts = [f"curl -X {case.get('method', 'GET')} '{url}'"]
    for key, value in (case.get("headers") or {}).items():
        parts.append(f"  -H '{key}: {value}'")
    body = case.get("body") or ""
    if body:
        escaped = body.replace("'", "'\\''")
        parts.append(f"  -d '{escaped}'")
    return " \\\n".join(parts)
