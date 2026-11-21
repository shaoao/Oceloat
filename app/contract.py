"""接口契约：从响应生成 JSON Schema 骨架，并比对字段漂移。

零依赖：只生成描述结构的最小 Schema（type / properties / required / items），
不做完整 JSON Schema 规范校验。契约存在 Store.data["contracts"]，按
"METHOD path" 索引；同一个接口后续响应字段变多 / 变少 / 类型变化都能标出来。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

CACHE_KEY = "contracts"


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def infer(data: Any) -> Dict[str, Any]:
    """从 JSON 值推断一个最小 schema。数组取首元素作为样本。"""
    kind = _kind(data)
    out: Dict[str, Any] = {"type": kind}
    if kind == "object":
        props: Dict[str, Any] = {}
        for key, value in data.items():
            props[str(key)] = infer(value)
        out["properties"] = props
        out["required"] = sorted(props)
    elif kind == "array":
        sample = next((x for x in data if x is not None), None)
        out["items"] = infer(sample) if sample is not None else {"type": "unknown"}
    return out


def drift(schema: Dict[str, Any], data: Any, path: str = "") -> List[str]:
    """返回字段漂移说明列表。空列表表示与契约一致。"""
    if not isinstance(schema, dict) or not schema:
        return []
    expected = schema.get("type") or ""
    actual = _kind(data)
    issues: List[str] = []
    where = path or "$"
    if expected and expected not in ("unknown", actual):
        issues.append(f"{where}: 类型由 {expected} 变为 {actual}")
    if expected == "object" and isinstance(data, dict):
        props = schema.get("properties") or {}
        for key in sorted(set(props) - set(data)):
            issues.append(f"{where}.{key}: 字段消失")
        for key in sorted(set(data) - set(props)):
            issues.append(f"{where}.{key}: 新增字段")
        for key, sub in props.items():
            if key in data:
                issues.extend(drift(sub, data[key], f"{where}.{key}"))
    elif expected == "array" and isinstance(data, list):
        sub = schema.get("items") or {}
        if sub and data:
            issues.extend(drift(sub, data[0], f"{where}[0]"))
    return issues


def key_for(method: str, url: str) -> str:
    """用 method + path 做 key，去掉 query，避免同接口不同分页各存一份。"""
    from urllib.parse import urlsplit

    try:
        path = urlsplit(url or "").path or "/"
    except Exception:  # noqa: BLE001
        path = url or "/"
    return f"{str(method or 'GET').upper()} {path}"


def parse_json(body: bytes, content_type: str = "") -> Tuple[Optional[Any], str]:
    text = (body or b"").decode("utf-8", "replace").strip()
    if not text:
        return None, "响应体为空"
    try:
        return json.loads(text), ""
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def get_contract(store, key: str) -> Optional[Dict[str, Any]]:
    if store is None:
        return None
    data = getattr(store, "data", None)
    if not isinstance(data, dict):
        return None
    contracts = data.get(CACHE_KEY)
    if not isinstance(contracts, dict):
        return None
    item = contracts.get(key)
    return item if isinstance(item, dict) else None


def save_contract(store, key: str, schema: Dict[str, Any], sample: Any) -> None:
    if store is None:
        return
    data = getattr(store, "data", None)
    if not isinstance(data, dict):
        return
    contracts = data.get(CACHE_KEY)
    if not isinstance(contracts, dict):
        contracts = {}
        data[CACHE_KEY] = contracts
    contracts[key] = {"schema": schema, "sample": sample}
    try:
        store.save()
    except Exception:       # noqa: BLE001
        pass


def remove_contract(store, key: str) -> None:
    if store is None:
        return
    data = getattr(store, "data", None)
    if isinstance(data, dict) and isinstance(data.get(CACHE_KEY), dict):
        data[CACHE_KEY].pop(key, None)
        try:
            store.save()
        except Exception:       # noqa: BLE001
            pass
