"""模块化 JSON 存储。

以前所有东西都塞在一个 ``state.json`` 里。文件越大，一次写到一半被强杀 /
断电，丢的是全部；想手动修也只能对着一个几 MB 的 JSON 啃。现在拆成三层：

    state.json              索引 + 设置 / 环境 / 历史 / 回收站这些「小数据」
    collections/<id>.json   每个顶层集合一份，互不牵连
    backups/                滚动快照（索引、单个集合、整包）

几条硬规矩：

* 写文件一律 ``tmp + fsync + rename``：断电最多留下一个 ``.tmp``，不会出现半个 JSON。
* 每个集合文件自带 ``checksum``（对 tree 做规范化哈希）。读的时候对不上，
  说明文件被截断或改坏了 —— 隔离它，翻这个集合自己的备份。
* **索引最后写**。模块先落地，索引没跟上也只是「索引旧一点」，
  下次读文件为准；反过来（索引新、文件旧）才会真丢东西。
* 索引里的 sha 只用来判断「要不要重写」，不当作正确性依据：
  用户拿编辑器手改文件是合法操作，改完照收。
* 备份有份数和时间上限，``collections/`` 里被删掉的文件挪进 backups，
  所以这层永远不会自己长成第二个仓库。
* 集合文件读不出来时，**只跳过这一个**，别的集合照常打开，绝不让一个坏文件
  把整份数据带走。
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = 2
INDEX_FORMAT = "ocelot.index"
INDEX_NAME = "state.json"
MODULES_DIR = "collections"
BACKUP_DIR = "backups"
QUARANTINE_DIR = "corrupted"

# 单个集合的软上限：超过只在资源管理器里提示，不拦着用户保存 —— 数据是用户的。
MAX_MODULE_BYTES = 16 * 1024 * 1024
# 变化最勤、体积最大的两块单独成文件：写一次历史只碰 history.json，
# 索引和集合文件都不用动。``trash_ops`` 跟回收站同一份，恢复时要一起看。
LIST_MODULES = {"history": "history.json", "trash": "trash.json"}
# 这两个的备份策略不一样：历史每发一次请求就变，备份只留「十分钟前的版本」；
# 回收站平时不动，但里面是用户删掉的东西，所以每次变更都留。
LIST_BACKUP_EVERY = {"history": 600, "trash": 0}
LIST_BACKUP_KEEP = {"history": 1, "trash": 2}
# 纯缓存的东西（远端共享列表、命令面板的命中次数）再单独一个文件：
# 丢了不影响任何数据，也不该跟设置挤在一份索引里。
SIDE_FILE = "cache.json"
# 缓存类字段：都不值得进索引，丢了也只是「下次慢一点」。
# drafts 是误关标签时留 60 秒的草稿，过期自己就没，所以也放这里。
SIDE_FIELDS = ("remote_nodes", "remote_nodes_at", "palette_hits", "drafts")
# 每个集合 / 索引各留几份备份、最快多久一份
BACKUPS_KEEP = 5
BACKUP_EVERY = 600
# 整包快照：保留份数与最短间隔（这份是「全部文件都没了」时的兜底）
SNAPSHOT_KEEP = 3
SNAPSHOT_EVERY = 1800
# 备份目录总预算，超了从最旧的开始删（最早的那份永远留着）
BACKUP_BUDGET = 96 * 1024 * 1024
# 被删掉的集合文件留几份
RETIRED_KEEP = 10


def now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def digest(value: Any) -> str:
    """规范化哈希：键排序、去空格，同一份内容永远同一个值。"""
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def _fsync_dir(path: Path) -> None:
    """目录也刷一下：rename 之后目录项落盘，断电才不会「文件在、名字没了」。"""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def atomic_write(path: Path, text: str) -> None:
    """原子写：先写 .tmp 并 fsync，再 rename 覆盖。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def count_requests(node: Any) -> int:
    stack = [node]
    total = 0
    while stack:
        cur = stack.pop()
        if not isinstance(cur, dict):
            continue
        if cur.get("type") == "request":
            total += 1
        stack.extend(cur.get("children") or [])
    return total


def _is_tree(value: Any) -> bool:
    return isinstance(value, dict) and value.get("type") in ("folder", "request")


class Storage:
    """把一份内存里的 ``data`` 摊到磁盘上，再原样拼回来。"""

    def __init__(self, index_path: Path):
        self.index_path = Path(index_path)
        self.root = self.index_path.parent
        self.modules = self.root / MODULES_DIR
        self.backups = self.root / BACKUP_DIR
        self.bad = self.root / QUARANTINE_DIR

        self._digests: Dict[str, str] = {}      # 集合 id -> 上次写出去的内容指纹
        self._files: Dict[str, str] = {}        # 集合 id -> 文件名
        self._index_key: Optional[str] = None   # 索引内容（不含 saved），用来判断要不要重写
        self._backed: Dict[str, float] = {}     # 集合 id -> 上次备份时间
        self._last_index_backup = 0.0
        self._last_snapshot = 0.0
        self.needs_write = False                # 迁移 / 修复之后，让 Store 立刻落一次盘
        self.migrated = False                   # 这次读的是不是老的单文件存档
        self.fresh = False                      # 全新的数据目录（要放示例数据）
        self.note: Optional[str] = None         # 一句给界面看的说明
        self.last_report: Dict[str, Any] = {}
        self.retired: List[str] = []            # 本次写到磁盘时被挪走的旧文件

    # ------------------------------------------------------------ 路径
    @property
    def relative_root(self) -> Path:
        return self.root

    def _file_name(self, cid: str, used: set) -> str:
        known = self._files.get(cid)
        if known and known not in used:
            return known
        safe = "".join(ch for ch in str(cid) if ch.isalnum() or ch in "-_")[:40] or "collection"
        name = f"{safe}.json"
        n = 2
        while name in used:
            name = f"{safe}-{n}.json"
            n += 1
        return name

    # ------------------------------------------------------------ 读
    def read(self) -> Tuple[Dict[str, Any], Optional[str]]:
        """读出完整数据。读不出来的单份文件会被跳过，并在 note 里说清。"""
        notes: List[str] = []
        payload: Optional[Dict[str, Any]] = None
        lists: Dict[str, Any] = {}
        legacy = False

        if self.index_path.exists():
            raw = read_json(self.index_path)
            if isinstance(raw, dict) and isinstance(raw.get("collections"), list) \
                    and any(_is_tree(n) for n in raw["collections"][:3]):
                legacy = True                       # 1.0.73 及更早的单文件存档
                payload = raw
            elif isinstance(raw, dict) and isinstance(raw.get("index"), list):
                payload = raw
            else:
                bad = self._quarantine(self.index_path)
                notes.append("索引文件损坏，已隔离" + (f"（{bad.name}）" if bad else ""))
        if payload is None:
            found = self._newest_snapshot()
            if found is not None:
                payload = found[0]
                notes.append(f"已从整包快照恢复（{found[1].name}）")
                legacy = isinstance(payload.get("collections"), list) and \
                    any(_is_tree(n) for n in (payload.get("collections") or [])[:3])
            else:
                payload = {}
                self.fresh = True

        data: Dict[str, Any] = {k: v for k, v in payload.items()
                                if k not in ("index", "format", "schema", "saved",
                                             "lists", "files")}
        data.pop("files", None)      # 1.0.73 的 .oce 关联表，功能已撤掉
        if legacy:
            nodes = [n for n in (payload.get("collections") or []) if _is_tree(n)]
            notes.append("已从单文件存档拆成按集合分文件")
            self.needs_write = True
            self.migrated = True
        else:
            nodes, extra = self._read_modules(payload.get("index") or [])
            notes.extend(extra)
            lists, list_notes = self._read_lists(payload.get("lists") or [])
            notes.extend(list_notes)
            lists.update(self._read_side())

        data["collections"] = nodes
        for key, value in (lists or {}).items():
            data[key] = value
        if notes:
            self.note = "；".join(notes)
        self._seed_state(nodes, payload.get("index") or [])
        return data, self.note

    def _seed_state(self, nodes: List[Dict[str, Any]], entries: List[Any]) -> None:
        """记下「磁盘上现在是什么样」，下一次写只动真正变了的文件。"""
        by_id = {str(e.get("id")): e for e in entries if isinstance(e, dict)}
        for node in nodes:
            cid = str(node.get("id") or "")
            if not cid:
                continue
            meta = by_id.get(cid) or {}
            fname = meta.get("file")
            if fname:
                self._files[cid] = fname
            path = self.modules / (fname or f"{cid}.json")
            if path.exists():
                self._digests[cid] = digest(node)
        snaps = self._snapshots()
        if snaps:
            self._last_snapshot = snaps[0][1]

    def _read_modules(self, entries: List[Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
        nodes: List[Dict[str, Any]] = []
        notes: List[str] = []
        used_files: set = set()
        seen_ids: set = set()

        for meta in entries:
            if not isinstance(meta, dict):
                continue
            cid = str(meta.get("id") or "")
            fname = str(meta.get("file") or "")
            if not fname and cid:
                fname = f"{cid}.json"
            if not fname:
                continue
            used_files.add(fname)
            path = self.modules / fname
            node, problem = self._read_module(path)
            if node is None:
                node = self._recover_module(cid)
                if node is not None:
                    notes.append(f"「{meta.get('name') or cid}」从备份恢复")
                else:
                    if problem != "missing":
                        self._quarantine(path)
                    notes.append(f"「{meta.get('name') or cid}」读不出来，已跳过")
                    continue
            if not node.get("id"):
                node["id"] = cid or hashlib.sha1(fname.encode()).hexdigest()[:10]
            if node["id"] in seen_ids:
                node["id"] = hashlib.sha1((fname + node["id"]).encode()).hexdigest()[:10]
            seen_ids.add(node["id"])
            self._files[node["id"]] = fname
            nodes.append(node)

        # 索引里没有、但磁盘上躺着的集合文件（索引从旧备份回来时会这样）：
        # 挂回去，比默默无视安全得多。
        orphans = 0
        try:
            for path in sorted(self.modules.glob("*.json")):
                if path.name in used_files:
                    continue
                node, _problem = self._read_module(path)
                if node is None:
                    continue
                cid = str(node.get("id") or "")
                if cid in seen_ids:
                    continue
                if not cid:
                    node["id"] = path.stem
                    cid = node["id"]
                seen_ids.add(cid)
                self._files[cid] = path.name
                nodes.append(node)
                orphans += 1
        except OSError:
            pass
        if orphans:
            notes.append(f"找回 {orphans} 个未登记的集合")
            self.needs_write = True
        return nodes, notes

    def _read_lists(self, entries: List[Any]) -> Tuple[Dict[str, Any], List[str]]:
        """历史 / 回收站：各自一个文件，读坏了就空着，不影响别的。"""
        out: Dict[str, Any] = {}
        notes: List[str] = []
        meta_by_key = {str(e.get("key")): e for e in entries if isinstance(e, dict)}
        for key, default_name in LIST_MODULES.items():
            meta = meta_by_key.get(key) or {}
            fname = str(meta.get("file") or default_name)
            path = self.root / fname
            label = "历史" if key == "history" else "回收站"
            raw = read_json(path) if path.exists() else None
            valid = isinstance(raw, dict) and isinstance(raw.get("items"), list)
            if path.exists() and not valid:
                # 先隔离（留证据），再谈恢复：坏文件留在原地只会被下一次写覆盖
                self._quarantine(path)
                notes.append(f"{label}读不出来，已隔离")
            if not valid:
                raw = self._recover_list(key)
                if raw is not None:
                    notes.append(f"{label}从备份恢复")
            digest_want = (raw or {}).get("checksum")
            items = (raw or {}).get("items")
            if not isinstance(items, list):
                items = []
            if digest_want and digest(items) != digest_want:
                notes.append(f"{label}被外部改过，照常读取")
            out[key] = items
            if key == "trash":
                ops = (raw or {}).get("ops")
                out["trash_ops"] = ops if isinstance(ops, list) else []
            self._digests[f"list:{key}"] = digest(items)
        return out, notes

    def _read_side(self) -> Dict[str, Any]:
        path = self.root / SIDE_FILE
        raw = read_json(path) if path.exists() else None
        if not isinstance(raw, dict):
            if path.exists():
                self._quarantine(path)
            return {}
        out = {k: raw[k] for k in SIDE_FIELDS if k in raw}
        self._digests["side"] = digest(out)
        return out

    def _write_side(self, data: Dict[str, Any], report: Dict[str, Any]) -> None:
        payload = {k: data[k] for k in SIDE_FIELDS if k in data}
        fingerprint = digest(payload)
        path = self.root / SIDE_FILE
        if self._digests.get("side") == fingerprint and path.exists():
            return
        body = {"format": "ocelot.cache", "schema": SCHEMA,
                "saved": round(time.time(), 3), "checksum": fingerprint, "data": payload}
        try:
            atomic_write(path, json.dumps(body, ensure_ascii=False, indent=2))
            self._digests["side"] = fingerprint
        except OSError as exc:
            report["errors"].append(f"{SIDE_FILE}: {exc}")

    def _recover_list(self, key: str) -> Optional[Dict[str, Any]]:
        for path in self._list_backups(key):
            raw = read_json(path)
            if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                return raw
        return None

    def _list_backups(self, key: str) -> List[Path]:
        try:
            items = list(self.backups.glob(f"list-{key}-*.json"))
        except OSError:
            return []
        return sorted(items, key=lambda p: p.stat().st_mtime if p.exists() else 0,
                      reverse=True)

    def _read_module(self, path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
        """返回 (节点, 状态)。状态只用于决定要不要报警。"""
        if not path.exists():
            return None, "missing"
        raw = read_json(path)
        if raw is None:
            return None, "broken"
        if isinstance(raw, dict) and isinstance(raw.get("tree"), dict):
            tree = raw["tree"]
            want = raw.get("checksum")
            if want and digest(tree) != want:
                # 内容合法但指纹不符：多半是用户手改过 / 别的工具格式化过。
                # 收下，不打扰 —— 丢数据比「规范」重要得多。
                return tree, "edited"
            return tree, "ok"
        if _is_tree(raw):
            return raw, "ok"                    # 裸节点（手写文件）也认
        return None, "broken"

    def _recover_module(self, cid: str) -> Optional[Dict[str, Any]]:
        if not cid:
            return None
        for path in self._module_backups(cid):
            node, _ = self._read_module(path)
            if node is not None:
                return node
        return None

    def _module_backups(self, cid: str) -> List[Path]:
        safe = "".join(ch for ch in str(cid) if ch.isalnum() or ch in "-_")[:40]
        try:
            items = list(self.backups.glob(f"col-{safe}-*.json"))
        except OSError:
            return []
        return sorted(items, key=lambda p: p.stat().st_mtime if p.exists() else 0,
                      reverse=True)

    def _snapshots(self) -> List[Tuple[Path, float]]:
        try:
            items = list(self.backups.glob("full-*.json"))
        except OSError:
            return []
        out = [(p, p.stat().st_mtime) for p in items if p.exists()]
        return sorted(out, key=lambda pair: pair[1], reverse=True)

    def _newest_snapshot(self) -> Optional[Tuple[Dict[str, Any], Path]]:
        for path, _ts in self._snapshots():
            data = read_json(path)
            if isinstance(data, dict) and isinstance(data.get("collections"), list):
                return data, path
        return None

    # ------------------------------------------------------------ 写
    def write(self, data: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
        report: Dict[str, Any] = {"written": 0, "kept": 0, "retired": 0,
                                  "errors": [], "oversize": [], "at": time.time()}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self.modules.mkdir(parents=True, exist_ok=True)
            self.backups.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            report["errors"].append(str(exc))
            self.last_report = report
            return report
        with self._lock():

            nodes = data.get("collections")
            if not isinstance(nodes, list):
                nodes = []
                data["collections"] = nodes

            entries: List[Dict[str, Any]] = []
            used: set = set()
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                cid = str(node.get("id") or "")
                if not cid:
                    cid = hashlib.sha1(json.dumps(node, sort_keys=True,
                                                  default=str).encode()).hexdigest()[:10]
                    node["id"] = cid
                fname = self._file_name(cid, used)
                used.add(fname)
                self._files[cid] = fname
                path = self.modules / fname
                fingerprint = digest(node)

                fresh = force or self._digests.get(cid) != fingerprint or not path.exists()
                if fresh:
                    text = self._module_text(node, fingerprint)
                    size = len(text.encode("utf-8"))
                    if size > MAX_MODULE_BYTES:
                        report["oversize"].append({"id": cid, "name": node.get("name"),
                                                   "bytes": size})
                    self._backup_module(cid, path, force=force)
                    try:
                        atomic_write(path, text)
                    except OSError as exc:
                        report["errors"].append(f"{fname}: {exc}")
                        continue
                    self._digests[cid] = fingerprint
                    report["written"] += 1
                else:
                    report["kept"] += 1

                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                entries.append({"id": cid, "name": node.get("name") or "",
                                "file": fname, "sha": fingerprint[:16], "bytes": size,
                                "requests": count_requests(node)})

            # 内存里没有的集合文件：挪进备份（不是删），出事还能捡回来
            try:
                leftovers = [p for p in self.modules.glob("*.json") if p.name not in used]
            except OSError:
                leftovers = []
            retired: List[str] = []
            for path in sorted(leftovers):
                try:
                    self._retire(path)
                    retired.append(path.name)
                    self._digests.pop(path.stem, None)
                except OSError:
                    pass
            report["retired"] = len(retired)
            self.retired = retired

            self._write_side(data, report)
            list_entries = self._write_lists(data, report)

            index = {k: v for k, v in data.items()
                     if k not in ("collections", "history", "trash", "trash_ops")
                     and k not in SIDE_FIELDS}
            index.update({"format": INDEX_FORMAT, "schema": SCHEMA,
                          "saved": time.time(), "index": entries,
                          "lists": list_entries})
            text = json.dumps(index, ensure_ascii=False, indent=2)
            key = json.dumps({k: v for k, v in index.items() if k != "saved"},
                             ensure_ascii=False, sort_keys=True)
            if force or key != self._index_key or not self.index_path.exists():
                self._backup_index()
                try:
                    atomic_write(self.index_path, text)
                    self._index_key = key
                except OSError as exc:
                    report["errors"].append(f"index: {exc}")

            self._maybe_snapshot(data, force=force)
            self._prune_backups()
        self.needs_write = False
        self.last_report = report
        return report

    def _write_lists(self, data: Dict[str, Any], report: Dict[str, Any]) -> List[Dict[str, Any]]:
        entries: List[Dict[str, Any]] = []
        for key, fname in LIST_MODULES.items():
            items = data.get(key)
            if not isinstance(items, list):
                items = []
            payload: Dict[str, Any] = {"items": items}
            if key == "trash":
                ops = data.get("trash_ops")
                payload["ops"] = ops if isinstance(ops, list) else []
            fingerprint = digest(items)
            path = self.root / fname
            if self._digests.get(f"list:{key}") != fingerprint or not path.exists():
                body = {"format": "ocelot.list", "schema": SCHEMA, "key": key,
                        "saved": round(time.time(), 3), "checksum": fingerprint, **payload}
                text = json.dumps(body, ensure_ascii=False, indent=2)
                self._backup_list(key, path)
                try:
                    atomic_write(path, text)
                    self._digests[f"list:{key}"] = fingerprint
                    report["written"] += 1
                except OSError as exc:
                    report["errors"].append(f"{fname}: {exc}")
            else:
                report["kept"] += 1
            # 索引里只记「有这个文件」：条数和体积每次都变，写进去会让索引白白重写
            entries.append({"key": key, "file": fname})
        return entries

    def _backup_list(self, key: str, path: Path) -> None:
        if not path.exists():
            return
        every = LIST_BACKUP_EVERY.get(key, BACKUP_EVERY)
        keep = LIST_BACKUP_KEEP.get(key, 2)
        last = self._backed.get(f"list:{key}", 0.0)
        if every and time.time() - last < every:
            return
        target = self.backups / f"list-{key}-{now_stamp()}.json"
        if target.exists():
            target = target.with_name(
                f"list-{key}-{now_stamp()}-{int(time.time() * 1000) % 1000}.json")
        try:
            shutil.copy2(path, target)
        except OSError:
            return
        self._backed[f"list:{key}"] = time.time()
        self._prune_prefix(f"list-{key}-", keep)

    def _module_text(self, node: Dict[str, Any], fingerprint: str) -> str:
        payload = {
            "format": "ocelot.collection",
            "schema": SCHEMA,
            "id": node.get("id"),
            "name": node.get("name") or "",
            "saved": round(time.time(), 3),
            "checksum": fingerprint,
            "requests": count_requests(node),
            "tree": node,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------ 备份
    def _backup_module(self, cid: str, path: Path, force: bool = False) -> None:
        if not path.exists():
            return
        last = self._backed.get(cid, 0.0)
        if not force and time.time() - last < BACKUP_EVERY:
            return
        safe = "".join(ch for ch in str(cid) if ch.isalnum() or ch in "-_")[:40]
        target = self.backups / f"col-{safe}-{now_stamp()}.json"
        if target.exists():
            target = target.with_name(f"col-{safe}-{now_stamp()}-{int(time.time() * 1000) % 1000}.json")
        try:
            shutil.copy2(path, target)
        except OSError:
            return
        self._backed[cid] = time.time()
        self._prune_prefix(f"col-{safe}-", BACKUPS_KEEP)

    def _backup_index(self) -> None:
        if not self.index_path.exists():
            return
        if time.time() - self._last_index_backup < BACKUP_EVERY:
            return
        target = self.backups / f"state-{now_stamp()}.json"
        if target.exists():
            target = target.with_name(f"state-{now_stamp()}-{int(time.time() * 1000) % 1000}.json")
        try:
            shutil.copy2(self.index_path, target)
        except OSError:
            return
        self._last_index_backup = time.time()
        self._prune_prefix("state-", BACKUPS_KEEP)

    def snapshot(self, data: Dict[str, Any], force: bool = True) -> Optional[Path]:
        """整包快照：一份文件里装着全部内容，做灾难兜底与云端上传。"""
        target = self.backups / f"full-{now_stamp()}.json"
        if target.exists():
            target = target.with_name(
                f"full-{now_stamp()}-{int(time.time() * 1000) % 1000}.json")
        try:
            self.backups.mkdir(parents=True, exist_ok=True)
            atomic_write(target, self.snapshot_text(data))
        except OSError:
            return None
        self._last_snapshot = time.time()
        self._prune_prefix("full-", SNAPSHOT_KEEP)
        return target

    def _maybe_snapshot(self, data: Dict[str, Any], force: bool = False) -> None:
        if not force and time.time() - self._last_snapshot < SNAPSHOT_EVERY:
            return
        self.snapshot(data, force=True)

    @staticmethod
    def snapshot_text(data: Dict[str, Any]) -> str:
        """云端 / 整包快照用的扁平结构：跟内存里的 data 一样，直接能读。"""
        payload = {k: v for k, v in data.items()}
        payload.setdefault("app", "Ocelot")
        payload["schema"] = SCHEMA
        payload["saved"] = round(time.time(), 3)
        payload["format"] = "ocelot.snapshot"
        return json.dumps(payload, ensure_ascii=False)

    def _retire(self, path: Path) -> None:
        target = self.backups / f"removed-{now_stamp()}-{path.name}"
        if target.exists():
            target = target.with_name(
                f"removed-{now_stamp()}-{int(time.time() * 1000) % 1000}-{path.name}")
        shutil.move(str(path), str(target))
        self._prune_prefix("removed-", RETIRED_KEEP)

    def _prune_prefix(self, prefix: str, keep: int) -> None:
        try:
            items = sorted(self.backups.glob(prefix + "*"),
                           key=lambda p: p.stat().st_mtime if p.exists() else 0,
                           reverse=True)
        except OSError:
            return
        for old in items[keep:]:
            try:
                old.unlink()
            except OSError:
                pass

    def _prune_backups(self) -> None:
        """总量预算：超了从最旧的删，最早那一份永远留。"""
        try:
            items = sorted((p for p in self.backups.glob("*.json")),
                           key=lambda p: p.stat().st_mtime if p.exists() else 0,
                           reverse=True)
        except OSError:
            return
        total = 0
        for i, path in enumerate(items):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total += size
            if i > 0 and total > BACKUP_BUDGET:
                try:
                    path.unlink()
                    total -= size
                except OSError:
                    pass

    def _quarantine(self, path: Path) -> Optional[Path]:
        if not path.exists():
            return None
        self.bad.mkdir(parents=True, exist_ok=True)
        target = self.bad / f"{path.name}-{now_stamp()}"
        try:
            shutil.move(str(path), str(target))
        except OSError:
            return None
        try:
            for old in sorted(self.bad.glob("*"),
                              key=lambda p: p.stat().st_mtime, reverse=True)[20:]:
                old.unlink()
        except OSError:
            pass
        return target

    @contextlib.contextmanager
    def _lock(self):
        """两个实例同时写会互相覆盖，用个建议锁挡一下；拿不到也照写，不阻塞使用。"""
        handle = None
        try:
            handle = open(self.root / ".lock", "a+")
            try:
                import fcntl

                for _ in range(6):
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except OSError:
                        time.sleep(0.02)
            except ImportError:
                pass
        except OSError:
            handle = None
        try:
            yield
        finally:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass

    # ------------------------------------------------------------ 检查 / 修复
    def stats(self) -> Dict[str, Any]:
        entries = []
        try:
            raw = read_json(self.index_path) or {}
            entries = raw.get("index") or []
        except Exception:  # noqa: BLE001
            entries = []
        modules = []
        for meta in entries:
            if not isinstance(meta, dict):
                continue
            path = self.modules / str(meta.get("file") or "")
            try:
                stat = path.stat()
                size, mtime = stat.st_size, stat.st_mtime
            except OSError:
                size, mtime = 0, 0
            modules.append({"id": meta.get("id"), "name": meta.get("name") or "",
                            "file": str(meta.get("file") or ""), "bytes": size,
                            "mtime": mtime, "requests": meta.get("requests") or 0})
        try:
            backups = [p for p in self.backups.glob("*.json") if p.exists()]
            backup_bytes = sum(p.stat().st_size for p in backups)
        except OSError:
            backups, backup_bytes = [], 0
        lists = []
        for key, fname in list(LIST_MODULES.items()) + [("cache", SIDE_FILE)]:
            path = self.root / fname
            try:
                stat = path.stat()
                lists.append({"key": key, "file": fname, "bytes": stat.st_size,
                              "mtime": stat.st_mtime})
            except OSError:
                lists.append({"key": key, "file": fname, "bytes": 0, "mtime": 0})
        index_bytes = self.index_path.stat().st_size if self.index_path.exists() else 0
        return {
            "index": {"path": str(self.index_path), "bytes": index_bytes},
            "modules": modules,
            "lists": lists,
            "module_bytes": sum(m["bytes"] for m in modules)
            + sum(item["bytes"] for item in lists),
            "backup_count": len(backups),
            "backup_bytes": backup_bytes,
            "total": index_bytes + sum(m["bytes"] for m in modules) + backup_bytes,
        }

    def verify(self) -> Dict[str, Any]:
        """逐个文件验一遍：缺了 / 坏了 / 指纹对不上，都算问题。"""
        problems: List[Dict[str, str]] = []
        warnings: List[Dict[str, str]] = []
        checked = 0
        if not self.index_path.exists():
            # 全新装、还没落过盘：没有文件不是「对不上」，别吓人
            return {"checked": 0, "problems": [], "warnings": [], "orphans": [],
                    "ok": True, "empty": True}
        try:
            raw = read_json(self.index_path) or {}
            entries = raw.get("index") or []
        except Exception:  # noqa: BLE001
            entries = []
        for meta in entries:
            if not isinstance(meta, dict):
                continue
            fname = str(meta.get("file") or "")
            path = self.modules / fname
            checked += 1
            if not path.exists():
                problems.append({"file": fname, "why": "文件不见了"})
                continue
            node, state = self._read_module(path)
            if node is None:
                problems.append({"file": fname, "why": "内容读不出来"})
            elif state == "edited":
                warnings.append({"file": fname, "why": "内容被外部改过，照常读取"})
        for key, fname in list(LIST_MODULES.items()) + [("cache", SIDE_FILE)]:
            path = self.root / fname
            if key == "cache" and not path.exists():
                continue          # 缓存本来就可以没有，不算问题
            checked += 1
            if not path.exists():
                problems.append({"file": fname, "why": "文件不见了"})
                continue
            raw = read_json(path)
            ok_shape = (isinstance(raw, dict) and isinstance(raw.get("items"), list)
                        if key in LIST_MODULES else isinstance(raw, dict))
            if not ok_shape:
                problems.append({"file": fname, "why": "内容读不出来"})
        try:
            known = {str(m.get("file")) for m in entries if isinstance(m, dict)}
            orphans = [p.name for p in self.modules.glob("*.json")
                       if p.name not in known]
        except OSError:
            orphans = []
        return {"checked": checked, "problems": problems, "warnings": warnings,
                "orphans": orphans, "ok": not problems and not orphans}

    def repair(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """按内存里这份内容把磁盘重写一遍：索引重建、模块重算指纹。"""
        self._digests.clear()
        self._files.clear()
        self._index_key = None
        self._backed.clear()
        self.snapshot(data, force=True)
        report = self.write(data, force=True)
        self.needs_write = False
        return report

    # ------------------------------------------------------------ 恢复
    def replace_all(self, data: Dict[str, Any]) -> Tuple[bool, str]:
        """用一份外部快照（云端 / 备份）整体替换本机内容。"""
        if not isinstance(data, dict):
            return False, "这不是一份能用的快照"
        nodes = data.get("collections")
        if not isinstance(nodes, list) or not any(_is_tree(n) for n in nodes):
            return False, "这份快照里没有集合"
        clean = {k: v for k, v in data.items()
                 if k not in ("format", "schema", "saved", "index")}
        report = self.write(clean, force=True)
        if report.get("errors"):
            return False, report["errors"][0]
        return True, ""
