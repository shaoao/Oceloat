"""请求节点（类似 tcping 的节点测速 / 代理出口）。

两种用途：
1. 测速：对内置节点列表做 TCP 连接耗时探测，判断线路质量；
2. 出口：用户自己添加的 HTTP / SOCKS5 代理节点，选中后请求经由它发出。

默认永远是「本地直连」，不做任何手脚。
"""
from __future__ import annotations

import socket
import time
from typing import Any, Dict, List, Optional, Tuple

LOCAL_ID = "local"

# 内置节点：都是公开 DNS / anycast 地址，测速只做 TCP 握手，不发送任何业务数据
BUILTIN: List[Dict[str, Any]] = [
    {"id": "n_bj_ct", "name": "北京电信", "host": "219.141.136.10", "port": 53, "carrier": "电信", "v6": False},
    {"id": "n_zj_ct", "name": "浙江电信", "host": "202.96.96.68", "port": 53, "carrier": "电信", "v6": False},
    {"id": "n_hb_ct", "name": "湖北电信", "host": "202.103.24.68", "port": 53, "carrier": "电信", "v6": False},
    {"id": "n_sh_ct", "name": "上海电信", "host": "202.96.199.133", "port": 53, "carrier": "电信", "v6": False},
    {"id": "n_gz_ct", "name": "广东电信", "host": "61.144.56.100", "port": 53, "carrier": "电信", "v6": False},
    {"id": "n_bj_cu", "name": "北京联通", "host": "202.106.0.20", "port": 53, "carrier": "联通", "v6": False},
    {"id": "n_gz_cu", "name": "广东联通", "host": "221.5.88.88", "port": 53, "carrier": "联通", "v6": False},
    {"id": "n_sc_cu", "name": "四川联通", "host": "119.6.6.6", "port": 53, "carrier": "联通", "v6": False},
    {"id": "n_bj_cm", "name": "北京移动", "host": "211.136.17.107", "port": 53, "carrier": "移动", "v6": False},
    {"id": "n_gd_cm", "name": "广东移动", "host": "211.136.192.6", "port": 53, "carrier": "移动", "v6": False},
    {"id": "n_ali", "name": "阿里 DNS", "host": "223.5.5.5", "port": 53, "carrier": "公共", "v6": False},
    {"id": "n_ali2", "name": "阿里 DNS 备用", "host": "223.6.6.6", "port": 53, "carrier": "公共", "v6": False},
    {"id": "n_baidu", "name": "百度 DNS", "host": "180.76.76.76", "port": 53, "carrier": "公共", "v6": False},
    {"id": "n_tx", "name": "腾讯 DNS", "host": "119.29.29.29", "port": 53, "carrier": "公共", "v6": False},
    {"id": "n_114", "name": "114 DNS", "host": "114.114.114.114", "port": 53, "carrier": "公共", "v6": False},
    {"id": "n_cf", "name": "Cloudflare", "host": "1.1.1.1", "port": 53, "carrier": "海外", "v6": False},
    {"id": "n_google", "name": "Google DNS", "host": "8.8.8.8", "port": 53, "carrier": "海外", "v6": False},
    {"id": "n_quad9", "name": "Quad9", "host": "9.9.9.9", "port": 53, "carrier": "海外", "v6": False},
    {"id": "n_ali6", "name": "阿里 IPv6", "host": "2400:3200::1", "port": 53, "carrier": "公共", "v6": True},
    {"id": "n_tx6", "name": "腾讯 IPv6", "host": "2402:4e00::", "port": 53, "carrier": "公共", "v6": True},
    {"id": "n_next6", "name": "下一代 IPv6", "host": "240c::6644", "port": 53, "carrier": "公共", "v6": True},
    {"id": "n_cf6", "name": "Cloudflare IPv6", "host": "2606:4700:4700::1111", "port": 53,
     "carrier": "海外", "v6": True},
]


def tcp_ping(host: str, port: int = 53, timeout: float = 1.2) -> Optional[float]:
    """返回 TCP 建连耗时（毫秒），失败返回 None。"""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    t0 = time.perf_counter()
    try:
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
        return round((time.perf_counter() - t0) * 1000, 1)
    except Exception:  # noqa: BLE001
        return None


def _dns_query(qname: str = "www.baidu.com") -> bytes:
    head = b"\xab\xcd\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    q = b"".join(bytes([len(p)]) + p.encode() for p in qname.split(".")) + b"\x00"
    return head + q + b"\x00\x01\x00\x01"


def udp_ping(host: str, port: int = 53, timeout: float = 1.2) -> Optional[float]:
    """发一个真实 DNS 查询测往返时延（UDP 53 在公共 DNS 上几乎不会被墙）。"""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    t0 = time.perf_counter()
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(_dns_query(), (host, port))
            s.recvfrom(512)
        return round((time.perf_counter() - t0) * 1000, 1)
    except Exception:  # noqa: BLE001
        return None


def probe_node(node: Dict[str, Any], timeout: float = 1.2) -> Optional[float]:
    """先试 TCP 握手，不行就发 DNS 查询 —— 两种都失败才认为不可达。"""
    host = node.get("host") or ""
    port = int(node.get("port") or 53)
    if not host:
        return None
    if node.get("kind") == "proxy":
        return tcp_ping(host, port, timeout)
    return tcp_ping(host, port, timeout) or udp_ping(host, port, timeout)


def parse_proxy(text: str) -> Optional[Tuple[str, str, int]]:
    """把 `socks5://1.2.3.4:1080` / `1.2.3.4:8080` 解析成 (scheme, host, port)。"""
    raw = (text or "").strip()
    if not raw:
        return None
    scheme = "http"
    if "://" in raw:
        scheme, raw = raw.split("://", 1)
        scheme = scheme.lower()
    host, _, port = raw.rpartition(":")
    if not host:
        return None
    try:
        return scheme, host, int(port)
    except ValueError:
        return None


class NodeBook:
    """节点列表：本地直连 + 在线中继节点 + 用户自定义代理节点。"""

    def __init__(self, store) -> None:
        self.store = store

    # -------------------------------------------------- 在线节点缓存
    @property
    def remote(self) -> List[Dict[str, Any]]:
        return self.store.data.setdefault("remote_nodes", [])

    def set_remote(self, nodes: List[Dict[str, Any]]) -> None:
        self.store.data["remote_nodes"] = nodes
        self.store.data["remote_nodes_at"] = time.time()
        self.store.save()

    def remote_stale(self, max_age: int = 86400) -> bool:
        return (time.time() - float(self.store.data.get("remote_nodes_at") or 0)) > max_age

    # -------------------------------------------------- 数据
    @property
    def custom(self) -> List[Dict[str, Any]]:
        return self.store.data.setdefault("nodes", [])

    @property
    def current_id(self) -> str:
        return self.store.data.get("active_node") or LOCAL_ID

    def set_current(self, node_id: str) -> None:
        self.store.data["active_node"] = node_id
        self.store.save()

    def all_nodes(self) -> List[Dict[str, Any]]:
        local = [{"id": LOCAL_ID, "name": "本地直连", "carrier": "本机", "host": "", "port": 0,
                  "v6": False, "kind": "local"}]
        custom = [dict(n, kind="proxy") for n in self.custom]
        remote = [dict(n, kind="relay") for n in self.remote]
        if not remote:
            # 没网 / 没缓存时的离线兜底，只用于展示，不能当代理出口
            remote = [dict(n, kind="offline") for n in BUILTIN]
        return local + custom + remote

    def find(self, node_id: str) -> Optional[Dict[str, Any]]:
        for n in self.all_nodes():
            if n["id"] == node_id:
                return n
        return None

    def current(self) -> Dict[str, Any]:
        return self.find(self.current_id) or self.all_nodes()[0]

    def add_proxy(self, name: str, addr: str) -> Optional[Dict[str, Any]]:
        parsed = parse_proxy(addr)
        if parsed is None:
            return None
        scheme, host, port = parsed
        node = {
            "id": f"c_{int(time.time() * 1000) % 10 ** 9}",
            "name": name.strip() or f"{host}:{port}",
            "host": host, "port": port, "scheme": scheme, "carrier": "自定义",
            "v6": ":" in host, "addr": addr.strip(),
        }
        self.custom.append(node)
        self.store.save()
        return node

    def remove_proxy(self, node_id: str) -> None:
        self.store.data["nodes"] = [n for n in self.custom if n.get("id") != node_id]
        if self.current_id == node_id:
            self.set_current(LOCAL_ID)
        self.store.save()

    # -------------------------------------------------- 出口
    def proxy_url(self) -> str:
        """当前节点如果是代理，返回 host:port（供 QNetworkProxy 使用）。"""
        node = self.current()
        if node.get("kind") != "proxy":
            return ""
        scheme = node.get("scheme") or "http"
        host = node.get("host", "")
        port = node.get("port", 0)
        return f"{scheme}://{host}:{port}"
