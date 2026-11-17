"""JWT 认证：用 Python 标准库生成签名令牌，零额外依赖。

支持 HS256 / HS384 / HS512；payload 与密钥都走环境变量解析，
所以可以在 claims 里写 {{token}} 这类占位符，发送时再取值。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict, Tuple

from .store import resolve_vars

_ALGS = {
    "HS256": hashlib.sha256,
    "HS384": hashlib.sha384,
    "HS512": hashlib.sha512,
}
ALGORITHMS = list(_ALGS)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(payload_text: str, secret: str, alg: str = "HS256",
             env_vars: Dict[str, str] | None = None,
             error_hint: str = "Payload is not valid JSON") -> Tuple[str, str]:
    """返回 (token, error)。成功时 error 为空串。"""
    env = env_vars or {}
    alg = alg if alg in _ALGS else "HS256"
    try:
        payload = json.loads(resolve_vars(payload_text or "{}", env))
        if not isinstance(payload, dict):
            payload = {"value": payload}
    except Exception:
        return "", error_hint

    header = {"alg": alg, "typ": "JWT"}
    seg_head = _b64url(json.dumps(header, separators=(",", ":"),
                                  ensure_ascii=False).encode("utf-8"))
    seg_body = _b64url(json.dumps(payload, separators=(",", ":"),
                                  ensure_ascii=False).encode("utf-8"))
    signing = f"{seg_head}.{seg_body}".encode("ascii")
    key = resolve_vars(secret or "", env).encode("utf-8")
    sig = hmac.new(key, signing, _ALGS[alg]).digest()
    return f"{seg_head}.{seg_body}.{_b64url(sig)}", ""


def decode_jwt_claims(token: str) -> Dict[str, Any]:
    """只读解析 payload 用于界面预览；验签在服务端做，这里不校验。"""
    try:
        seg = (token or "").split(".")
        if len(seg) < 2:
            return {}
        pad = "=" * (-len(seg[1]) % 4)
        raw = base64.urlsafe_b64decode(seg[1] + pad)
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
