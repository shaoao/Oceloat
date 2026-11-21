"""AWS Signature V4：标准库实现，零额外依赖。

按 AWS 官方算法对「最终请求」签名：method、canonical URI、canonical query、
canonical headers、payload hash。每次请求都重新签（时间戳不同，禁止缓存）。
form-data / binary 这类拿不到完整字节的 body 用 UNSIGNED-PAYLOAD。

额外提供：区域 / 服务自动推断、签名明细（canonical request / string to sign）、
预签名 URL。全部只依赖标准库。
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Tuple

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


def infer_service_region(url: str) -> Tuple[str, str]:
    """从 AWS 主机名推断 service / region，猜不出时给保守默认值。"""
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    if not host:
        return "execute-api", "us-east-1"
    service = "execute-api"
    if re.match(r"^s3[.-]", host) or ".s3." in host or host.endswith(".s3.amazonaws.com"):
        service = "s3"
    elif host.startswith("ec2.") or ".ec2." in host:
        service = "ec2"
    elif host.startswith("lambda.") or ".lambda." in host:
        service = "lambda"
    elif host.startswith("es.") or ".es." in host:
        service = "es"
    elif host.startswith("sqs.") or ".sqs." in host:
        service = "sqs"
    match = re.search(r"(?:^|\.)([a-z]{2}(?:-gov)?-[a-z]+-\d)(?:\.|$)", host)
    region = match.group(1) if match else "us-east-1"
    return service, region


def sign_with_detail(method: str, url: str, headers: Iterable[Tuple[str, str]],
                     payload: Optional[bytes], auth: Dict[str, Any],
                     env: Dict[str, str], unsigned_payload: bool = False
                     ) -> Tuple[List[Tuple[str, str]], str, Dict[str, str]]:
    """返回 (签名头, 错误, 明细)。明细给 UI 排障用，不参与发送。"""
    access = _resolve(auth.get("aws_access_key_id"), env)
    secret = _resolve(auth.get("aws_secret_access_key"), env)
    region = _resolve(auth.get("aws_region") or "us-east-1", env)
    service = _resolve(auth.get("aws_service") or "execute-api", env)
    token = _resolve(auth.get("aws_session_token"), env)
    if not access or not secret:
        return [], "AWS SigV4 需要 Access Key ID 与 Secret Access Key", {}
    if not region or not service:
        service, region = infer_service_region(url)

    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if not host:
        return [], "AWS SigV4 无法从 URL 解析主机名", {}
    if parsed.port:
        host = f"{host}:{parsed.port}"

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    if unsigned_payload or str(auth.get("aws_sign_body", True)).lower() in (
            "0", "false", "no"):
        payload_hash = "UNSIGNED-PAYLOAD"
    else:
        payload_hash = hashlib.sha256(payload or b"").hexdigest()

    # 收集要签名的头。用户手写 Host 时以它为准，避免「签一个 Host、发另一个」。
    signed: Dict[str, str] = {}
    for key, value in headers or []:
        name = str(key).strip().lower()
        if not name or name in ("authorization", "x-amz-date", "x-amz-content-sha256"):
            continue
        signed[name] = " ".join(str(value).split())
    signed.setdefault("host", host)
    signed["x-amz-content-sha256"] = payload_hash
    signed["x-amz-date"] = amz_date
    if token:
        signed["x-amz-security-token"] = token
    names = sorted(signed)
    canonical_headers = "".join(f"{k}:{signed[k]}\n" for k in names)
    signed_headers = ";".join(names)
    canonical_uri = _quote_uri(urllib.parse.unquote(parsed.path) or "/")
    canonical_query = _canonical_query(parsed.query)

    canonical = "\n".join([
        method.upper(), canonical_uri, canonical_query,
        canonical_headers, signed_headers, payload_hash,
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
    detail = {
        "canonical": canonical,
        "string_to_sign": string_to_sign,
        "signature": signature,
        "scope": scope,
        "payload_hash": payload_hash,
        "signed_headers": signed_headers,
        "region": region,
        "service": service,
    }
    return out, "", detail


def sign(method: str, url: str, headers: Iterable[Tuple[str, str]],
         payload: Optional[bytes], auth: Dict[str, Any], env: Dict[str, str]
         ) -> Tuple[List[Tuple[str, str]], str]:
    """兼容旧 API：只返回 (签名头, 错误)。"""
    out, err, _detail = sign_with_detail(method, url, headers, payload, auth, env)
    return out, err


def presign(method: str, url: str, expires: int, auth: Dict[str, Any],
            env: Dict[str, str]) -> Tuple[str, str]:
    """生成预签名 URL（GET 下载 / S3 临时授权常用），标准库实现。"""
    access = _resolve(auth.get("aws_access_key_id"), env)
    secret = _resolve(auth.get("aws_secret_access_key"), env)
    region = _resolve(auth.get("aws_region") or "us-east-1", env)
    service = _resolve(auth.get("aws_service") or "execute-api", env)
    token = _resolve(auth.get("aws_session_token"), env)
    if not access or not secret:
        return "", "AWS 预签名需要 Access Key ID 与 Secret Access Key"
    try:
        expires = int(expires or 3600)
    except (TypeError, ValueError):
        return "", "有效期必须是秒数"
    expires = max(1, min(expires, 604800))

    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if not host:
        return "", "AWS 预签名无法从 URL 解析主机名"
    if parsed.port:
        host = f"{host}:{parsed.port}"
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"

    pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    pairs = [(k, v) for k, v in pairs if not k.startswith("X-Amz-")]
    pairs += [
        ("X-Amz-Algorithm", "AWS4-HMAC-SHA256"),
        ("X-Amz-Credential", f"{access}/{scope}"),
        ("X-Amz-Date", amz_date),
        ("X-Amz-Expires", str(expires)),
        ("X-Amz-SignedHeaders", "host" + (";x-amz-security-token" if token else "")),
    ]
    if token:
        pairs.append(("X-Amz-Security-Token", token))
    canonical_query = _canonical_query(urllib.parse.urlencode(pairs))
    headers = {"host": host}
    if token:
        headers["x-amz-security-token"] = token
    canonical_headers = "".join(f"{k}:{headers[k]}\n" for k in sorted(headers))
    canonical = "\n".join([
        method.upper(), _quote_uri(urllib.parse.unquote(parsed.path) or "/"),
        canonical_query, canonical_headers, ";".join(sorted(headers)),
        "UNSIGNED-PAYLOAD",
    ])
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
    query = canonical_query + "&X-Amz-Signature=" + signature
    return parsed._replace(query=query).geturl(), ""
