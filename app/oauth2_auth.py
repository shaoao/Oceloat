"""OAuth 2.0 / OIDC 认证：标准库实现，零额外依赖。

支持：客户端凭证、密码、授权码 + PKCE、手动 Token；自动缓存、过期前刷新、
OIDC discovery、client_secret_basic、state 校验。
token 缓存在 Store.data["oauth_tokens"]，以 token_url + client_id + scope + grant +
用户名（password grant）为键；过期前 60 秒自动刷新。刷新失败返回错误，
由调用方显示在控制台，绝不静默发送无认证请求。
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

GRANTS = ["client_credentials", "password", "authorization_code", "implicit"]
GRANT_LABELS = {
    "client_credentials": "客户端凭证",
    "password": "密码",
    "authorization_code": "授权码（PKCE）",
    "implicit": "手动 Token",
}
MANUAL_GRANTS = ("implicit", "manual")

# 缓存条目字段：access_token / refresh_token / expires_at / token_type
CACHE_KEY = "oauth_tokens"


def _resolve(v: Any, env: Dict[str, str]) -> str:
    text = str(v or "")
    for name, value in (env or {}).items():
        text = text.replace("{{" + name + "}}", str(value))
    return text


def _cache_key(auth: Dict[str, Any], env: Dict[str, str]) -> str:
    keys = ("oauth_token_url", "oauth_client_id", "oauth_scope", "oauth_grant")
    # password grant 必须把用户名算进键，否则换用户会复用上一个用户的 token
    if str(auth.get("oauth_grant") or "") == "password":
        keys += ("oauth_username",)
    raw = "|".join(_resolve(auth.get(k, ""), env) for k in keys)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{digest}:{auth.get('oauth_grant') or 'client_credentials'}"


def _store_cache(store) -> Dict[str, Any]:
    if store is None:
        return {}
    data = getattr(store, "data", None)
    if not isinstance(data, dict):
        return {}
    cache = data.get(CACHE_KEY)
    if not isinstance(cache, dict):
        cache = {}
        data[CACHE_KEY] = cache
    return cache


def cached_entry(auth: Dict[str, Any], store, env: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """取原始缓存条目（即使已过期）——刷新 token 要靠它。"""
    entry = _store_cache(store).get(_cache_key(auth, env))
    return entry if isinstance(entry, dict) else None


def cached_token(auth: Dict[str, Any], store, env: Dict[str, str]) -> Optional[Dict[str, Any]]:
    entry = cached_entry(auth, store, env)
    if not entry or not entry.get("access_token"):
        return None
    expires = float(entry.get("expires_at") or 0)
    # expires_at=0 表示服务端没给过期时间：用 1 小时兜底，避免每次都重新换 token
    if expires and time.time() > expires - 60:
        return None
    if not expires and time.time() > float(entry.get("cached_at") or 0) + 3500:
        return None
    return entry


def _expiry(data: Dict[str, Any]) -> float:
    """兼容 expires_in / expires_at / exp 三种服务端返回。"""
    now = time.time()
    if data.get("expires_in") not in (None, ""):
        try:
            return now + float(data["expires_in"])
        except (TypeError, ValueError):
            pass
    for key in ("expires_at", "exp"):
        if data.get(key) not in (None, ""):
            try:
                value = float(data[key])
                return value + now if value < 1_000_000_000 else value
            except (TypeError, ValueError):
                pass
    return 0.0


def save_token(auth: Dict[str, Any], store, env: Dict[str, str],
               data: Dict[str, Any]) -> None:
    if store is None:
        return
    entry = dict(data)
    entry.setdefault("cached_at", time.time())
    entry["expires_at"] = _expiry(data)
    _store_cache(store)[_cache_key(auth, env)] = entry
    # 关键：把服务端轮换出来的 refresh_token 回填到请求配置，否则刷新永远是死代码
    if data.get("refresh_token"):
        auth["oauth_refresh_token"] = str(data["refresh_token"])
    if data.get("access_token"):
        auth["oauth_access_token"] = str(data["access_token"])
    try:
        store.save()
    except Exception:       # noqa: BLE001 - 缓存写失败不影响本次请求
        pass


def clear_token(auth: Dict[str, Any], store, env: Dict[str, str]) -> None:
    _store_cache(store).pop(_cache_key(auth, env), None)


def pkce(verifier: str = "") -> Tuple[str, str]:
    """返回 (verifier, challenge)。verifier 为空或非法时生成一个新的。"""
    if not verifier or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier):
        verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorize_url_with_state(auth: Dict[str, Any], env: Dict[str, str]
                             ) -> Tuple[str, str, str]:
    """返回 (授权 URL, verifier, state)。调用方必须把后两者写回配置。"""
    auth_url = _resolve(auth.get("oauth_auth_url"), env)
    if not auth_url:
        return "", "", ""
    verifier, challenge = pkce(_resolve(auth.get("oauth_code_verifier"), env))
    state = _resolve(auth.get("oauth_state"), env) or secrets.token_urlsafe(16)
    params = {
        "response_type": "code",
        "client_id": _resolve(auth.get("oauth_client_id"), env),
        "redirect_uri": _resolve(auth.get("oauth_redirect_uri"), env),
        "scope": _resolve(auth.get("oauth_scope"), env),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    sep = "&" if "?" in auth_url else "?"
    return (auth_url + sep + urllib.parse.urlencode(
        {k: v for k, v in params.items() if v})), verifier, state


def authorize_url(auth: Dict[str, Any], env: Dict[str, str]) -> str:
    """兼容旧 API：只返回 URL（不回写 verifier/state，建议用上面的版本）。"""
    return authorize_url_with_state(auth, env)[0]


def discover(issuer: str, timeout: int = 10) -> Tuple[Dict[str, str], str]:
    """OIDC discovery：从 issuer 拉 authorization/token/jwks 地址。"""
    issuer = (issuer or "").strip().rstrip("/")
    if not issuer.startswith(("http://", "https://")):
        return {}, "Issuer 要以 http(s):// 开头"
    url = issuer + "/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(url, timeout=max(1, min(int(timeout or 10), 30))) as res:
            data = json.loads(res.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return {}, f"OIDC 发现失败：{exc}"
    if not isinstance(data, dict):
        return {}, "OIDC 发现响应不是 JSON 对象"
    return {
        "oauth_auth_url": str(data.get("authorization_endpoint") or ""),
        "oauth_token_url": str(data.get("token_endpoint") or ""),
        "jwks_uri": str(data.get("jwks_uri") or ""),
    }, ""


def _http_form(url: str, fields: Dict[str, str], timeout: int,
               headers: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """POST 表单，返回 (响应体, 错误)。同步调用，超时有硬上限。"""
    if not url:
        return "", "Token 地址为空"
    body = urllib.parse.urlencode({k: str(v or "") for k, v in fields.items()}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json, application/x-www-form-urlencoded")
    for key, value in (headers or {}).items():
        req.add_header(key, str(value))
    try:
        with urllib.request.urlopen(req, timeout=max(1, min(int(timeout or 10), 60))) as res:
            return res.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        return "", f"HTTP {exc.code}: {detail}"
    except Exception as exc:  # noqa: BLE001
        return "", str(exc)


def _parse_token(body: str) -> Tuple[Dict[str, Any], str]:
    body = (body or "").strip()
    if not body:
        return {}, "Token 响应为空"
    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            return {}, "Token 响应不是 JSON 对象"
        return data, ""
    except Exception:  # noqa: BLE001
        pass
    try:
        parsed = urllib.parse.parse_qs(body, keep_blank_values=True)
        return {k: v[-1] for k, v in parsed.items()}, ""
    except Exception as exc:  # noqa: BLE001
        return {}, f"无法解析 Token 响应：{exc}"


def fetch_token(auth: Dict[str, Any], env: Dict[str, str], timeout: int = 10,
                refresh: bool = False) -> Tuple[Dict[str, Any], str]:
    """按 grant 换取 token。返回 (token 数据, 错误)。"""
    grant = _resolve(auth.get("oauth_grant") or "client_credentials", env)
    token_url = _resolve(auth.get("oauth_token_url"), env)
    client_id = _resolve(auth.get("oauth_client_id"), env)
    client_secret = _resolve(auth.get("oauth_client_secret"), env)
    fields: Dict[str, str] = {"grant_type": grant}
    headers: Dict[str, str] = {}

    if refresh:
        fields["grant_type"] = "refresh_token"
        # effective() 会把缓存里的 refresh_token 回填到 auth，这里只认配置值
        fields["refresh_token"] = _resolve(auth.get("oauth_refresh_token"), env)
        if not fields["refresh_token"]:
            return {}, "没有可用的 Refresh Token"
    elif grant in ("client_credentials", "authorization_code"):
        fields["client_id"] = client_id
        fields["client_secret"] = client_secret
    elif grant == "password":
        fields.update(username=_resolve(auth.get("oauth_username"), env),
                      password=_resolve(auth.get("oauth_password"), env),
                      client_id=client_id, client_secret=client_secret)
    elif grant in MANUAL_GRANTS:
        return {}, "手动 Token 模式不请求 Token 地址"

    # client_secret_basic：凭证放 Header，不放 form
    basic = str(auth.get("oauth_token_auth_method") or "client_secret_post")
    if basic == "client_secret_basic" and client_id:
        pair = f"{client_id}:{client_secret}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(pair).decode("ascii")
        fields.pop("client_id", None)
        fields.pop("client_secret", None)

    scope = _resolve(auth.get("oauth_scope"), env)
    if scope:
        fields["scope"] = scope
    if grant == "authorization_code" and not refresh:
        fields["code"] = _resolve(auth.get("oauth_code"), env)
        fields["redirect_uri"] = _resolve(auth.get("oauth_redirect_uri"), env)
        verifier, _ = pkce(_resolve(auth.get("oauth_code_verifier"), env))
        fields["code_verifier"] = verifier

    body, err = _http_form(token_url, fields, timeout, headers)
    if err:
        return {}, err
    data, err = _parse_token(body)
    if err:
        return {}, err
    expected = _resolve(auth.get("oauth_state"), env)
    returned = _resolve(auth.get("oauth_state_returned") or data.get("state"), env)
    if expected and returned and expected != returned:
        return {}, "OAuth state 不匹配，可能遭受 CSRF"
    if not data.get("access_token"):
        return {}, "Token 响应里没有 access_token"
    return data, ""


def apply_token(auth: Dict[str, Any], env: Dict[str, str],
                token: str) -> Dict[str, Any]:
    """把 token 归一化成现有认证管线认识的结构，复用 bearer / apikey 注入。"""
    placement = str(auth.get("oauth_token_placement") or "header")
    if placement == "query":
        return {"type": "apikey", "key": str(auth.get("oauth_token_key") or "access_token"),
                "value": token, "add_to": "query"}
    return {"type": "bearer", "token": token}


def effective(auth: Dict[str, Any], store, env: Dict[str, str],
              timeout: int = 10) -> Tuple[Dict[str, Any], str]:
    """给 ApiClient._effective_auth 用：拿缓存 / 刷新 / 新取 token。"""
    grant = str(auth.get("oauth_grant") or "client_credentials")
    if grant in MANUAL_GRANTS:
        token = _resolve(auth.get("oauth_access_token"), env)
        if not token:
            return {"type": "none"}, "请先粘贴 Access Token"
        return apply_token(auth, env, token), ""

    entry = cached_token(auth, store, env)
    if entry is None:
        stale = cached_entry(auth, store, env) or {}
        refresh_token = _resolve(auth.get("oauth_refresh_token") or
                                 stale.get("refresh_token"), env)
        if refresh_token:
            auth["oauth_refresh_token"] = refresh_token
        use_refresh = bool(refresh_token) and str(auth.get("oauth_use_refresh", True)) not in (
            "0", "false", "False")
        data, err = fetch_token(auth, env, timeout, refresh=use_refresh)
        if err and use_refresh:
            # refresh token 失效就退回完整授权（授权码可能已用过，失败由调用方提示）
            data, err = fetch_token(auth, env, timeout, refresh=False)
        if err:
            return {"type": "none"}, err
        save_token(auth, store, env, data)
        entry = cached_token(auth, store, env) or data
    return apply_token(auth, env, str(entry.get("access_token") or "")), ""
