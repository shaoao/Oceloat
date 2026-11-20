"""命令行跑集合：`python3 -m app.cli run payments.oce`。

为什么单独做一条命令行：
- 界面里点「运行集合」适合调接口，不适合放进 CI —— 机器上没有窗口；
- 这条命令只依赖标准库，不 import PyQt，服务器 / 容器里裸 Python 就能跑；
- 退出码是约定：0 全部通过，1 有请求失败，2 文件或参数有问题。
  接 CI 只要 `python3 -m app.cli run api/payments.oce --var base_url=$BASE` 一行。

用法::

    python3 -m app.cli run api/payments.oce --var base_url=https://api.example.com
    python3 -m app.cli run api/payments.oce --env Demo --json
    python3 -m app.cli list api/payments.oce
"""
from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import oce
from .store import body_content_type, body_mode, resolve_vars

OK, FAIL, SKIP = "ok", "fail", "skip"


# ---------------------------------------------------------------- 读集合
def env_vars(store, name: str = "") -> Dict[str, str]:
    """从本地存档里取一套环境变量（找不到就给空，CLI 不强依赖存档）。"""
    if store is None:
        return {}
    rows: List[Dict[str, Any]] = []
    envs = store.environments or []
    if name:
        picked = next((e for e in envs if str(e.get("name", "")).lower() == name.lower()), None)
        if picked is not None:
            rows = picked.get("vars") or []
    else:
        active = store.active_environment()
        if active:
            rows = active.get("vars") or []
    out = {str(r.get("key")): str(r.get("value", ""))
           for r in rows if r.get("key") and r.get("enabled", True)}
    for row in store.global_vars():
        out.setdefault(str(row.get("key")), str(row.get("value", "")))
    return out


def flatten(node: Dict[str, Any], trail: Tuple[str, ...] = ()) -> List[Tuple[str, Dict[str, Any]]]:
    """按顺序摊平请求，(路径, 请求)。"""
    out: List[Tuple[str, Dict[str, Any]]] = []
    for kid in node.get("children") or []:
        if kid.get("type") == "folder":
            out.extend(flatten(kid, trail + (str(kid.get("name") or ""),)))
        else:
            out.append(("/".join(trail), kid))
    return out


# ---------------------------------------------------------------- 发请求
def build(node: Dict[str, Any], variables: Dict[str, str]) -> Dict[str, Any]:
    """把请求节点摊成一次可直接发送的东西（不含 Qt）。"""
    def sub(text: Any) -> str:
        return resolve_vars(str(text or ""), variables)

    method = str(node.get("method") or "GET").upper()
    url = sub(node.get("url"))
    query = [(sub(k.get("key")), sub(k.get("value")))
             for k in node.get("params") or [] if k.get("enabled", True) and k.get("key")]
    if query:
        sep = "&" if "?" in url else "?"
        url = url + sep + urllib.parse.urlencode(query)

    headers: Dict[str, str] = {}
    for row in node.get("headers") or []:
        if row.get("enabled", True) and row.get("key"):
            headers[sub(row.get("key"))] = sub(row.get("value"))

    body_cfg = node.get("body") or {}
    mode = body_mode(body_cfg)
    data: Optional[bytes] = None
    if mode == "urlencoded":
        pairs = [(sub(r.get("key")), sub(r.get("value")))
                 for r in body_cfg.get("form") or [] if r.get("enabled", True)]
        data = urllib.parse.urlencode(pairs).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif mode == "form":
        return {"skip": "CLI 暂不发送 multipart/form-data（请用界面发文件上传）",
                "method": method, "url": url}
    elif mode == "binary":
        return {"skip": "CLI 暂不发送二进制文件体", "method": method, "url": url}
    elif mode in ("json", "xml", "html", "text", "raw"):
        raw = sub(body_cfg.get("raw"))
        if raw:
            data = raw.encode("utf-8")
            ct = body_content_type(body_cfg, charset=True)
            if ct:
                headers.setdefault("Content-Type", ct)

    auth = node.get("auth") or {}
    kind = auth.get("type") or "none"
    if kind == "bearer" and auth.get("token"):
        headers.setdefault("Authorization", "Bearer " + sub(auth.get("token")))
    elif kind == "basic":
        pair = f"{sub(auth.get('username'))}:{sub(auth.get('password'))}"
        headers.setdefault("Authorization", "Basic " + base64.b64encode(pair.encode()).decode())
    elif kind in ("apikey", "api_key") and auth.get("key"):
        key, value = sub(auth.get("key")), sub(auth.get("value"))
        if (auth.get("add_to") or "header") == "query":
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urllib.parse.quote(key)}={urllib.parse.quote(value)}"
        else:
            headers.setdefault(key, value)

    return {"method": method, "url": url, "headers": headers, "body": data,
            "name": str(node.get("name") or "")}


def send(spec: Dict[str, Any], timeout: float = 30.0,
         verify: bool = True) -> Dict[str, Any]:
    started = time.perf_counter()
    ctx = None
    if spec["url"].lower().startswith("https") and not verify:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(spec["url"], data=spec.get("body"),
                                 method=spec["method"], headers=spec["headers"])
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            blob = resp.read(2 * 1024 * 1024)
            return {"status": resp.status, "reason": resp.reason, "size": len(blob),
                    "elapsed": int((time.perf_counter() - started) * 1000), "state": OK}
    except urllib.error.HTTPError as exc:
        blob = b""
        try:
            blob = exc.read(2 * 1024 * 1024)
        except Exception:                       # noqa: BLE001
            pass
        return {"status": exc.code, "reason": str(exc.reason), "size": len(blob),
                "elapsed": int((time.perf_counter() - started) * 1000),
                "state": FAIL if exc.code >= 400 else OK}
    except Exception as exc:                    # noqa: BLE001 — 连不上就是失败
        return {"status": 0, "reason": str(exc), "size": 0,
                "elapsed": int((time.perf_counter() - started) * 1000), "state": FAIL}


# ---------------------------------------------------------------- 输出
def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def run(paths: List[Path], variables: Dict[str, str], timeout: float, verify: bool,
        as_json: bool, fail_fast: bool, show_list: bool) -> int:
    results: List[Dict[str, Any]] = []
    collections: List[str] = []
    for path in paths:
        node, err = oce.read_file(path)
        if node is None:
            print(f"✗ {path}: {err}", file=sys.stderr)
            return 2
        collections.append(str(node.get("name") or path.stem))
        for folder, req in flatten(node):
            jobs = results
            if show_list:
                print(f"{req.get('method', 'GET'):<6} {folder + '/' if folder else ''}"
                      f"{req.get('name')}")
                continue
            spec = build(req, variables)
            if spec.get("skip"):
                jobs.append({"name": spec.get("name"), "folder": folder,
                             "method": spec.get("method"), "url": spec.get("url"),
                             "status": 0, "elapsed": 0, "size": 0,
                             "state": SKIP, "reason": spec["skip"]})
                continue
            out = send(spec, timeout=timeout, verify=verify)
            out.update({"name": spec["name"], "folder": folder,
                        "method": spec["method"], "url": spec["url"]})
            jobs.append(out)
            if not as_json:
                mark = {"ok": "✓", "fail": "✗", "skip": "-"}[out["state"]]
                label = f"{folder}/{out['name']}" if folder else str(out["name"])
                status = out["status"] or "ERR"
                print(f"  {mark} {out['method']:<5} {label:<34} {status:<5} "
                      f"{out['elapsed']:>5}ms  {_human_size(out['size'])}"
                      + (f"  {out['reason']}" if out["state"] == FAIL else ""))
            if fail_fast and out["state"] == FAIL:
                break
        if fail_fast and any(r["state"] == FAIL for r in results):
            break

    if show_list:
        return 0
    passed = sum(1 for r in results if r["state"] == OK)
    failed = sum(1 for r in results if r["state"] == FAIL)
    skipped = sum(1 for r in results if r["state"] == SKIP)
    if as_json:
        print(json.dumps({"collections": collections, "results": results,
                          "passed": passed, "failed": failed, "skipped": skipped},
                         ensure_ascii=False, indent=2))
    else:
        head = " · ".join(collections)
        print(f"\n{head} — {len(results)} 个请求："
              f"{passed} 通过，{failed} 失败" + (f"，{skipped} 跳过" if skipped else ""))
    return 1 if failed else 0


# ---------------------------------------------------------------- 入口
def main(argv: Optional[List[str]] = None) -> int:
    # 只在真有存档时才读：CI 机器上不该因为跑一次命令就凭空生成一份 state.json
    defaults: Dict[str, str] = {}
    store = None
    try:
        from .store import STATE_FILE, Store

        if STATE_FILE.exists():
            store = Store.load()
            defaults = env_vars(store)
    except Exception:                           # noqa: BLE001 — 存档坏了也照跑
        store = None

    parser = argparse.ArgumentParser(
        prog="python3 -m app.cli",
        description="在命令行跑 Ocelot 集合（.oce），适合放进 CI。")
    sub = parser.add_subparsers(dest="cmd")
    for name in ("run", "list"):
        p = sub.add_parser(name, help="跑集合" if name == "run" else "只列出会跑哪些请求")
        p.add_argument("files", nargs="+", help="一个或多个 .oce 文件")
        p.add_argument("--var", action="append", default=[], metavar="K=V",
                       help="临时变量，可重复；优先级最高")
        p.add_argument("--env", default="", metavar="NAME",
                       help="用本地存档里的哪套环境变量（默认用当前激活的）")
        p.add_argument("--timeout", type=float, default=30.0, metavar="SEC")
        p.add_argument("--insecure", action="store_true", help="跳过 HTTPS 证书校验")
        p.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON")
        p.add_argument("--fail-fast", action="store_true", help="遇到第一个失败就停")
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0

    variables = dict(defaults)
    if args.env and store is not None:
        variables = env_vars(store, args.env) or variables
    for item in args.var:
        if "=" in item:
            key, value = item.split("=", 1)
            variables[key.strip()] = value

    paths = [Path(p).expanduser() for p in args.files]
    missing = [p for p in paths if not p.exists()]
    if missing:
        for p in missing:
            print(f"✗ 找不到文件：{p}", file=sys.stderr)
        return 2
    return run(paths, variables, args.timeout, not args.insecure,
               bool(args.as_json), bool(args.fail_fast), args.cmd == "list")


if __name__ == "__main__":
    raise SystemExit(main())
