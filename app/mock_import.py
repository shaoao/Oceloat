"""把现成的接口描述文件变成 Mock 路由。

三个来源都能吃：
1. **OpenAPI 3 / Swagger 2** —— 取 `paths` 里每个方法，用 responses 里的示例或
   schema 生成一份像样的 JSON；分组用 `tags[0]`（没有就用路径第一段）。
2. **Postman v2.x 集合** —— 递归 `item`，文件夹名拼成 `父/子` 分组；
   请求自带的 example response 直接拿来当响应体。
3. **Ocelot / 通用 JSON** —— 只要有 `paths` 或 `item` 就按上面两套处理。

生成的每条路由都是 mock_server 认识的普通字典，不依赖网络、不写文件。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

MAX_ROUTES = 400          # 一次导入的上限：再多面板也翻不动
SAMPLE_DEPTH = 6

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")


# ---------------------------------------------------------------- 造示例数据
def _sample(schema: Any, depth: int = 0, defs: Optional[Dict[str, Any]] = None) -> Any:
    """根据 JSON Schema 造一份示例值；认不出来的类型给个合理的默认值。"""
    defs = defs or {}
    if not isinstance(schema, dict) or depth > SAMPLE_DEPTH:
        return None
    if "$ref" in schema:
        name = str(schema["$ref"]).rsplit("/", 1)[-1]
        return _sample(defs.get(name) or {}, depth + 1, defs)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if schema.get("enum"):
        return schema["enum"][0]
    # allOf 合并、oneOf/anyOf 取第一个
    for key in ("allOf", "oneOf", "anyOf"):
        if schema.get(key):
            parts = schema[key]
            if key == "allOf":
                merged: Dict[str, Any] = {}
                for part in parts:
                    got = _sample(part, depth + 1, defs)
                    if isinstance(got, dict):
                        merged.update(got)
                return merged
            return _sample(parts[0], depth + 1, defs)
    kind = str(schema.get("type") or ("object" if "properties" in schema else "string"))
    if kind == "object":
        props = schema.get("properties") or {}
        return {k: _sample(v, depth + 1, defs) for k, v in props.items()}
    if kind == "array":
        item = _sample(schema.get("items") or {"type": "string"}, depth + 1, defs)
        return [item] if item is not None else []
    if kind == "integer":
        return int(schema.get("minimum") or 1)
    if kind == "number":
        return float(schema.get("minimum") or 1)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    fmt = str(schema.get("format") or "")
    if fmt in ("date-time", "datetime"):
        return "2026-01-01T09:30:00Z"
    if fmt == "date":
        return "2026-01-01"
    if fmt == "uuid":
        return "3f7a1c2e-8b64-4a11-9f52-0d5c6b7a8e90"
    if fmt in ("email",):
        return "user@example.com"
    if fmt in ("uri", "url"):
        return "https://example.com/item"
    return schema.get("title") or "string"


def _pretty(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return "{}"


def _norm_path(raw: str) -> str:
    """统一成 `/api/users/:id` 这种形式，并去掉末尾斜杠。"""
    path = (raw or "/").strip()
    if "://" in path:
        path = urlsplit(path).path or "/"
    path = path.split("?")[0].split("#")[0]
    if not path.startswith("/"):
        path = "/" + path
    # OpenAPI 的 {id} 在 Mock 里当成前缀通配更实用
    path = re.sub(r"\{[^}]+\}", "*", path)
    return path or "/"


# ---------------------------------------------------------------- OpenAPI
def _openapi_response(op: Dict[str, Any], defs: Dict[str, Any]) -> "tuple[int, str, str]":
    """挑一个最像「成功」的响应：优先 2xx，其次 default，最后 200 空对象。"""
    responses = op.get("responses") or {}
    status = 200
    payload: Any = {"code": 0, "message": "ok", "data": {}}
    for code in sorted(responses, key=lambda c: (not str(c).startswith("2"), str(c))):
        resp = responses.get(code) or {}
        if isinstance(resp, dict) and "$ref" in resp:
            resp = defs.get(str(resp["$ref"]).rsplit("/", 1)[-1]) or {}
        content = resp.get("content") if isinstance(resp, dict) else None
        if isinstance(content, dict) and content:
            ctype = next(iter(content))
            body = content.get(ctype) or {}
            if isinstance(body, dict):
                if "example" in body:
                    payload = body["example"]
                elif body.get("examples"):
                    first = next(iter(body["examples"].values()))
                    payload = first.get("value") if isinstance(first, dict) else first
                else:
                    payload = _sample(body.get("schema") or {}, 0, defs)
        elif isinstance(resp, dict) and (resp.get("examples") or resp.get("schema")):
            # Swagger 2 的写法
            examples = resp.get("examples") or {}
            if examples:
                payload = examples.get("application/json") or next(iter(examples.values()))
            else:
                payload = _sample(resp.get("schema") or {}, 0, defs)
        try:
            status = int(code)
        except (TypeError, ValueError):
            status = 200
        break
    if payload is None:
        payload = {}
    if isinstance(payload, (dict, list)):
        return status, _pretty(payload), "application/json"
    return status, str(payload), "text/plain; charset=utf-8"


def routes_from_openapi(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """OpenAPI 3 / Swagger 2 → 路由列表。"""
    defs: Dict[str, Any] = {}
    for key in ("components", "definitions"):
        block = data.get(key)
        if isinstance(block, dict):
            if key == "components":
                defs.update(block.get("schemas") or {})
            else:
                defs.update(block)
    out: List[Dict[str, Any]] = []
    paths = data.get("paths")
    if not isinstance(paths, dict):
        return out
    for raw_path, item in paths.items():
        if not isinstance(item, dict):
            continue
        path_group = _norm_path(raw_path).strip("/").split("/")[0] or "默认"
        for method in _METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            tags = op.get("tags") or []
            group = str(tags[0]) if tags else path_group.title()
            status, body, ctype = _openapi_response(op, defs)
            summary = (op.get("summary") or op.get("operationId")
                       or f"{method.upper()} {raw_path}")
            out.append({
                "id": "",
                "name": str(summary)[:60],
                "group": group,
                "method": method.upper(),
                "path": _norm_path(raw_path),
                "status": status,
                "content_type": ctype,
                "body": body,
                "delay": 0,
                "echo": False,
                "enabled": True,
                "rules": [],
            })
            if len(out) >= MAX_ROUTES:
                return out
    return out


# ---------------------------------------------------------------- Postman
def _postman_body(req: Dict[str, Any]) -> str:
    body = req.get("body") if isinstance(req, dict) else None
    if not isinstance(body, dict):
        return _pretty({"code": 0, "message": "ok", "data": {}})
    if body.get("mode") == "raw":
        raw = body.get("raw") or ""
        try:
            return _pretty(json.loads(raw))
        except (TypeError, ValueError):
            return raw or _pretty({"code": 0})
    if body.get("mode") == "urlencoded":
        pairs = {p.get("key"): p.get("value") for p in body.get("urlencoded") or []
                 if p.get("key")}
        return _pretty(pairs)
    return _pretty({"code": 0, "message": "ok", "data": {}})


def routes_from_postman(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Postman v2.x 集合 → 路由列表，文件夹名自动拼成分组。"""
    out: List[Dict[str, Any]] = []

    def walk(items: List[Any], trail: List[str]) -> None:
        for node in items:
            if not isinstance(node, dict) or len(out) >= MAX_ROUTES:
                return
            if isinstance(node.get("item"), list):
                walk(node["item"], trail + [str(node.get("name") or "分组")])
                continue
            req = node.get("request")
            if not isinstance(req, dict):
                continue
            url = req.get("url")
            if isinstance(url, dict):
                raw = url.get("raw") or "/" + "/".join(url.get("path") or [])
            else:
                raw = str(url or "/")
            status, body, ctype = 200, _postman_body(req), "application/json"
            examples = node.get("response") or []
            if examples and isinstance(examples[0], dict):
                first = examples[0]
                try:
                    status = int(first.get("code") or 200)
                except (TypeError, ValueError):
                    status = 200
                if first.get("body"):
                    body = str(first["body"])
                headers = first.get("header") or []
                for h in headers if isinstance(headers, list) else []:
                    if str(h.get("key", "")).lower() == "content-type" and h.get("value"):
                        ctype = str(h["value"])
            out.append({
                "id": "",
                "name": str(node.get("name") or f"{req.get('method', 'GET')} {raw}")[:60],
                "group": "/".join(trail),
                "method": str(req.get("method") or "GET").upper(),
                "path": _norm_path(raw),
                "status": status,
                "content_type": ctype,
                "body": body,
                "delay": 0,
                "echo": False,
                "enabled": True,
                "rules": [],
            })

    walk(data.get("item") or [], [str(data.get("info", {}).get("name") or "Postman")])
    return out


# ---------------------------------------------------------------- 入口
def routes_from_document(text: str) -> "tuple[List[Dict[str, Any]], str]":
    """自动识别来源，返回 (路由, 来源名字)。识别不了就抛 ValueError。"""
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("不是合法 JSON，暂时只支持 JSON 格式的 OpenAPI / Postman 文件") from exc
    if not isinstance(data, dict):
        raise ValueError("文件内容不是一个对象，无法识别")
    if isinstance(data.get("paths"), dict):
        routes = routes_from_openapi(data)
        kind = "Swagger 2" if str(data.get("swagger") or "").startswith("2") else "OpenAPI"
        return routes, kind
    if isinstance(data.get("item"), list):
        return routes_from_postman(data), "Postman"
    raise ValueError("没找到 paths（OpenAPI）或 item（Postman），无法导入")


def route_from_request(method: str, url: str, body: str = "", name: str = "",
                       group: str = "一键 Mock", status: int = 200,
                       content_type: str = "application/json") -> Dict[str, Any]:
    """从一条真实请求造 Mock 路由：只取 path，查询参数不参与匹配（更宽松）。"""
    path = _norm_path(url)
    return {
        "id": "",
        "name": (name or f"{method.upper()} {path}")[:60],
        "group": group,
        "method": (method or "GET").upper(),
        "path": path,
        "status": int(status or 200),
        "content_type": content_type or "application/json",
        "body": body or _pretty({"code": 0, "message": "ok", "data": {}}),
        "delay": 0,
        "echo": False,
        "enabled": True,
        "rules": [],
    }
