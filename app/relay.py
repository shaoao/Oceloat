"""在线节点中继：节点列表拉取 + challenge/PoW/send 三段式转发。

节点来源是 tcping.cn/http-test 公开接口。节点本身不是代理 IP，而是由对方服务器
代替发出请求，所以这里走「先取挑战、算 nonce、再提交请求」的流程。
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QByteArray, QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

API = "https://www.tcping.cn/api/apitest"
NODES_URL = API + "/nodes"
UA = "Ocelot/1.0 (Node Relay)"


def fetch_nodes(timeout: int = 12) -> List[Dict[str, Any]]:
    """拉节点列表（同步，调用方放线程池）。返回统一字段的节点字典。"""
    req = urllib.request.Request(NODES_URL, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Referer": "https://www.tcping.cn/http-test",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    out: List[Dict[str, Any]] = []
    for n in data.get("nodes", []):
        unid = str(n.get("unid") or "")
        if not unid:
            continue
        out.append({
            "id": "r_" + unid,
            "unid": unid,
            "name": str(n.get("name") or unid[:8]),
            "carrier": str(n.get("group") or "在线节点"),
            "v4": bool(n.get("v4", True)),
            "v6": bool(n.get("v6", False)),
            "kind": "relay",
        })
    return out



def measure_relay(node: Dict[str, Any], timeout: int = 10) -> Optional[float]:
    """同步测一个在线节点的延迟（work 线程里调用）：challenge -> PoW -> send。

    返回服务端报告的毫秒数；失败返回 None。测速只反映这一次转发的往返，
    既不代表节点长期可用，也不代表对任意目标的整体请求速度。
    """
    payload = {
        "node": node.get("unid", ""), "ip_version": 6 if node.get("v6") else 4,
        "url": "https://www.tcping.cn/", "method": "GET", "params": [],
        "json": "", "headers": [], "content_type": "", "cookie": "",
    }

    def post(path: str, data: Dict[str, Any]) -> Dict[str, Any]:
        req = urllib.request.Request(
            API + path, data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8",
                     "User-Agent": UA, "Referer": "https://www.tcping.cn/http-test"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    challenge = post("/challenge", payload)
    nonce = solve_nonce(challenge)
    result = post("/send", {**payload, "challenge_id": challenge.get("challenge_id", ""),
                            "nonce": nonce})
    if not int(result.get("status") or 0):
        return None
    return float(result.get("ms") or 0) or None

def solve_nonce(challenge: Dict[str, Any]) -> str:
    """解 PoW：SHA256(challenge_id\\nsalt\\nrequest_hash\\n{i}) 前 difficulty 位为 0。"""
    n = int(challenge.get("difficulty") or 0)
    prefix = "{}\n{}\n{}\n".format(challenge.get("challenge_id", ""),
                                   challenge.get("salt", ""),
                                   challenge.get("request_hash", ""))
    for i in range(5_000_000):
        digest = hashlib.sha256((prefix + str(i)).encode("utf-8")).digest()
        zeros = 0
        for b in digest:
            if b:
                zeros += 8 - b.bit_length()
                break
            zeros += 8
        if zeros >= n:
            return str(i)
    raise RuntimeError("节点校验计算超时")


class RelayClient(QObject):
    """异步中继发送，信号与 ApiClient 保持一致。"""

    started = pyqtSignal()
    finished = pyqtSignal(object)     # Response
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self._reply: Optional[QNetworkReply] = None
        self._timer: Optional[QTimer] = None
        self._payload: Dict[str, Any] = {}
        self._stage = "challenge"
        self._timeout = 30

    @property
    def busy(self) -> bool:
        return self._reply is not None

    def abort(self) -> None:
        if self._reply is not None:
            self._reply.abort()

    def send(self, payload: Dict[str, Any], timeout: int = 30) -> None:
        self.abort()
        self._payload = dict(payload)
        self._stage = "challenge"
        self._timeout = timeout
        self.started.emit()
        self._post("/challenge", self._payload)

    def _post(self, path: str, payload: Dict[str, Any]) -> None:
        body = QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        req = QNetworkRequest(QUrl(API + path))
        req.setRawHeader(b"Content-Type", b"application/json; charset=utf-8")
        req.setRawHeader(b"User-Agent", UA.encode())
        reply = self.nam.post(req, body)
        self._reply = reply
        reply.finished.connect(self._on_finished)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: reply.abort() if reply is not None else None)
        self._timer.start(max(2, self._timeout) * 1000)

    def _on_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if self._timer is not None:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None
        if reply is None:
            return
        err = reply.error()
        raw = bytes(reply.readAll())
        reply.deleteLater()
        if err != QNetworkReply.NetworkError.NoError:
            text = raw.decode("utf-8", "replace").strip()
            try:
                text = json.loads(text).get("error") or text
            except Exception:  # noqa: BLE001
                pass
            self.failed.emit(f"在线节点请求失败：{text or reply.errorString()}")
            return
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"节点返回无法解析：{exc}")
            return

        if self._stage == "challenge":
            try:
                nonce = solve_nonce(data)
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(str(exc))
                return
            self._stage = "send"
            self._post("/send", {**self._payload,
                                 "challenge_id": data.get("challenge_id", ""),
                                 "nonce": nonce})
            return

        from .http_client import Response

        # 服务端的 body 是 JSON 字符串，二进制经过 UTF-8 替换会有损，
        # 这里尽量还原；图片等场景 UI 会提示改用本地直连。
        btext = data.get("body") or ""
        body = btext.encode("utf-8", "replace")
        headers = [(str(k), str(v)) for k, v in (data.get("headers") or {}).items()]
        ip = str(data.get("ip") or "")
        loc = str(data.get("ip_location") or "")
        node = str(data.get("node") or "")
        if ip:
            headers.append(("X-Relay-IP", ip))
        if loc:
            headers.append(("X-Relay-Location", loc))
        if node:
            headers.append(("X-Relay-Node", node))
        if data.get("truncated"):
            headers.append(("X-Relay-Truncated", "1"))
        ct = ""
        for k, v in headers:
            if k.lower() == "content-type":
                ct = v
                break
        status = int(data.get("status") or 0)
        resp = Response(
            status=status,
            reason="OK" if 200 <= status < 300 else ("错误" if status else ""),
            headers=headers, body=body,
            elapsed=int(float(data.get("ms") or 0)),
            size=int(data.get("body_size") or len(body)),
            url=str(data.get("final_url") or self._payload.get("url", "")),
            content_type=ct,
            error="" if status else str(data.get("error") or "在线节点未返回状态码"),
        )
        self.finished.emit(resp)
