"""云同步：把本机 state.json 存进 Turso（libsql）实现多机同步。

只依赖标准库：Turso 提供 HTTP pipeline 接口，一次 POST 就能跑一组 SQL，
不需要装 libsql 驱动，也不会给这个轻量工具塞进新依赖。

用法：
    c = TursoClient(url, token)
    ok, msg, latency = c.test()
    c.push(text)          # 覆盖云端快照
    text, msg = c.pull()  # 取回云端快照
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, List, Optional, Tuple

from PyQt6.QtCore import QThread, pyqtSignal

TABLE = "ocelot_sync"
KEY = "state"


def normalize_url(raw: str) -> str:
    """把用户可能粘贴的任何形式统一成 https 基地址。"""
    url = (raw or "").strip().rstrip("/")
    if not url:
        return ""
    for prefix in ("libsql://", "wss://", "ws://"):
        if url.startswith(prefix):
            url = "https://" + url[len(prefix):]
            break
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not url.startswith("https://"):
        url = "https://" + url
    return url


def _arg(value: Any) -> dict:
    if isinstance(value, bool):
        return {"type": "integer", "value": "1" if value else "0"}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if value is None:
        return {"type": "null"}
    return {"type": "text", "value": str(value)}


def _value(cell: Optional[dict]) -> Any:
    if not cell:
        return None
    t = cell.get("type")
    v = cell.get("value")
    if t in ("integer", "float") and v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    if t == "null":
        return None
    if t == "blob":
        return v
    return v


class CloudError(Exception):
    pass


class TursoClient:
    def __init__(self, url: str, token: str, timeout: int = 12):
        self.url = normalize_url(url)
        self.token = (token or "").strip()
        self.timeout = timeout

    # ------------------------------------------------------------ 底层
    def _post(self, statements: List[Tuple[str, List[Any]]]) -> dict:
        if not self.url:
            raise CloudError("请先填写数据库地址")
        if not self.token:
            raise CloudError("请先填写 Auth Token")
        payload = {"requests": [{"type": "execute",
                                 "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}
                                for sql, args in statements]}
        payload["requests"].append({"type": "close"})
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url + "/v2/pipeline", data=body, method="POST",
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (401, 403):
                raise CloudError("Token 被拒绝（401/403），检查是否复制完整") from exc
            if exc.code == 404:
                raise CloudError("地址不对（404），确认是 https://<库名>-<组织>.turso.io") from exc
            raise CloudError(f"HTTP {exc.code} {detail}".strip()) from exc
        except urllib.error.URLError as exc:
            raise CloudError(f"连不上：{exc.reason}") from exc
        except TimeoutError as exc:
            raise CloudError("连接超时，检查网络或地址") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise CloudError("返回的不是合法 JSON，地址可能不是 Turso 数据库") from exc
        return data

    @staticmethod
    def _rows(data: dict, index: int = 0) -> List[List[Any]]:
        results = data.get("results") or []
        if index >= len(results):
            return []
        entry = results[index]
        if entry.get("type") != "ok":
            err = entry.get("error") or {}
            raise CloudError(err.get("message") or "SQL 执行失败")
        resp = entry.get("response") or {}
        result = resp.get("result") or {}
        rows = result.get("rows") or []
        return [[_value(cell) for cell in row] for row in rows]

    # ------------------------------------------------------------ 业务
    def test(self) -> Tuple[bool, str, int]:
        started = time.perf_counter()
        rows = self._rows(self._post([("SELECT 1", [])]))
        ms = int((time.perf_counter() - started) * 1000)
        if not rows:
            return False, "连上了但没返回结果", ms
        return True, f"连接正常 · {ms} ms", ms

    def ensure_table(self) -> None:
        self._post([(
            f"CREATE TABLE IF NOT EXISTS {TABLE} ("
            "  k TEXT PRIMARY KEY,"
            "  v TEXT NOT NULL,"
            "  updated_at INTEGER NOT NULL"
            ")", [])])

    def push(self, text: str) -> Tuple[bool, str, int]:
        stamp = int(time.time())
        self.ensure_table()
        self._post([(
            f"INSERT INTO {TABLE}(k, v, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
            [KEY, text, stamp])])
        return True, "已上传到云端", stamp

    def pull(self) -> Tuple[Optional[str], int]:
        self.ensure_table()
        rows = self._rows(self._post([(
            f"SELECT v, updated_at FROM {TABLE} WHERE k = ?", [KEY])]))
        if not rows or not rows[0]:
            return None, 0
        stamp = int(rows[0][1] or 0) if len(rows[0]) > 1 else 0
        return str(rows[0][0]), stamp


class CloudWorker(QThread):
    """在后台跑一次同步动作，UI 不卡。返回 (ok, message, payload)。"""

    done = pyqtSignal(bool, str, object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102
        try:
            ok, msg, data = self._fn()
        except CloudError as exc:
            ok, msg, data = False, str(exc), None
        except Exception as exc:  # noqa: BLE001
            ok, msg, data = False, f"{type(exc).__name__}: {exc}", None
        self.done.emit(ok, msg, data)


def client_for(settings: dict) -> TursoClient:
    return TursoClient(settings.get("turso_url", ""), settings.get("turso_token", ""))
