"""AWS Signature V4：标准库实现，零额外依赖。

按 AWS 官方算法对「最终请求」签名：method、canonical URI、canonical query、
canonical headers、payload hash。每次请求都重新签（时间戳不同，禁止缓存）。
form-data / binary 这类拿不到完整字节的 body 用 UNSIGNED-PAYLOAD 兜底。
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import urllib.parse
from typing import Any, Dict, Iterable, List, Tuple

EMPTY_HASH = hashlib.sha256(b"").hexdigest()


def _resolve(v: Any, env: Dict[str, str]) -> str:
    text = str(v or "")
    for name, value in (env or {}).items():
        text = text.replace("{{" + name + "}}", str(value))
    return text


def _quote_uri(path: str) -> str:
    """路径按段编码，保留 /；AWS 要求每个段都做 RFC3986 编码。"""
    path = path or "/"
    return "/".join(urllib.parse.quote(seg, safe="-_.~") for seg in path.split("/"))


def _canonical_query(query: str) -> str:
    """解析 query 后按 key/value 排序再编码，重复 key 保留。"""
    pairs = urllib.parse.parse_qsl(query or "", keep_blank_values=True)
    encoded = [(urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~"))
               for k, v in pairs]
    encoded.sort(key=lambda kv: (kv[0], kv[1]))
    return "&".join(f"{k}={v}" for k, v in encoded)


def sign(method: str, url: str, headers: Iterable[Tuple[str, str]],
         payload: bytes, auth: Dict[str, Any], env: Dict[str, str]
         ) -> Tuple[List[Tuple[str, str]], str]:
    """返回 (要追加的签名头列表, 错误)。headers 是最终请求已有的头。"""
    access = _resolve(auth.get("aws_access_key_id") or "", env)
    secret = _resolve(auth.get("aws_secret_access_key") or "", env)
    region = _resolve(auth.get("aws_region") or "us-east-1", env)
    service = _resolve(auth.get("aws_service") or "execute-api", env)
    token = _resolve(auth.get("aws_session_token") or "", env)
    if not access or not secret:
        return [], "AWS SigV4 需要 Access Key ID 与 Secret Access Key"

    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if not host:
        return [], "AWS SigV4 无法从 URL 解析主机名"
    if parsed.port:
        host = f"{host}:{parsed.port}"

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    payload_hash = EMPTY_HASH if payload is None else hashlib.sha256(payload).hexdigest()
    if str(auth.get("aws_sign_body", True)).lower() in ("0", "false", "no"):
        payload_hash = "UNSIGNED-PAYLOAD"

    # 收集需要签名的头：host + x-amz-date + x-amz-content-sha256 + 现有头
    signed: Dict[str, str] = {}
    for key, value in headers or []:
        name = str(key).strip().lower()
        if not name or name in ("authorization", "x-amz-date", "x-amz-content-sha256"):
            continue
        signed[name] = " ".join(str(value).split())
    signed["host"] = host
    signed["x-amz-content-sha256"] = payload_hash
    signed["x-amz-date"] = amz_date
    if token:
        signed["x-amz-security-token"] = token
    names = sorted(signed)
    canonical_headers = "".join(f"{k}:{signed[k]}\n" for k in names)
    signed_headers = ";".join(names)

    canonical = "\n".join([
        method.upper(),
        _quote_uri(urllib.parse.unquote(parsed.path) or "/"),
        _canonical_query(parsed.query),
        canonical_headers,
        signed_headers,
        payload_hash,
    ])
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    ])

    def hmac_key(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    key = hmac_key(("AWS4" + secret).encode("utf-8"), datestamp)
    key = hmac_key(key, region)
    key = hmac_key(key, service)
    key = hmac_key(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
                     f"SignedHeaders={signed_headers}, Signature={signature}")
    out: List[Tuple[str, str]] = [
        ("X-Amz-Date", amz_date),
        ("X-Amz-Content-Sha256", payload_hash),
        ("Authorization", authorization),
    ]
    if token:
        out.insert(0, ("X-Amz-Security-Token", token))
    return out, ""
