"""集合 ↔ Git 文件夹：稳定导出、语义 diff、可选的 git 提交。

轻量优先：只用标准库（difflib / subprocess），没装 git 也能用 ——
那时对比的是文件夹里的上一版文件。
- 导出去掉 saved / checksum 这类每次都变的字段，键排序、缩进固定：
  同一份内容永远同一份文本，git diff 才干净。
- 语义 diff 以「请求」为单位：新增 / 删除 / 修改，修改再细到字段。
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FORMAT = "ocelot.git"
_VOLATILE = {"saved", "checksum", "response", "last_status", "last_elapsed", "ai_named"}
_FIELDS = [("method", "方法"), ("url", "地址"), ("params", "参数"), ("headers", "请求头"),
           ("cookies", "Cookies"), ("body", "请求体"), ("auth", "认证"),
           ("scripts", "脚本"), ("name", "名称"), ("note", "说明")]
_SECRET = re.compile(r"(token|secret|password|passwd|api[_-]?key|authorization|cookie)", re.I)


def _clean(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _clean(v) for k, v in node.items() if k not in _VOLATILE}
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


def file_name(node: Dict[str, Any]) -> str:
    """集合名 + id 尾巴：人能认出来，改名也能靠 id 找回同一个文件。"""
    name = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", str(node.get("name") or "")).strip("-")
    return f"{(name or 'collection')[:40]}.{str(node.get('id') or 'x')[-6:]}.ocelot.json"


def dumps(node: Dict[str, Any]) -> str:
    doc = {"format": FORMAT, "id": node.get("id"), "name": node.get("name") or "",
           "tree": _clean(node)}
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def loads(text: Optional[str]) -> Optional[Dict[str, Any]]:
    try:
        doc = json.loads(text or "")
    except ValueError:
        return None
    if isinstance(doc, dict) and doc.get("format") == FORMAT and isinstance(doc.get("tree"), dict):
        return doc["tree"]
    return None


def find_file(folder: Path, cid: str) -> Optional[Path]:
    tail = f".{str(cid)[-6:]}.ocelot.json"
    try:
        for p in Path(folder).glob("*.ocelot.json"):
            if p.name.endswith(tail):
                return p
    except OSError:
        pass
    return None


def write(folder: Path, node: Dict[str, Any]) -> Path:
    """原子写入；集合改了名就把旧文件名挪掉，不留两份。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / file_name(node)
    old = find_file(folder, node.get("id") or "")
    text = dumps(node)
    if old == target and target.read_text("utf-8") == text:
        return target                       # 内容没变：不碰文件，git / 编辑器都不会被惊动
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, target)
    if old and old != target and old.exists():
        old.unlink()
    return target


def _requests(tree: Optional[Dict[str, Any]]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    out: Dict[str, Tuple[str, Dict[str, Any]]] = {}

    def walk(node: Dict[str, Any], trail: str) -> None:
        for child in node.get("children") or []:
            if not isinstance(child, dict):
                continue
            if child.get("type") == "request":
                out[str(child.get("id"))] = (trail, child)
            else:
                walk(child, f"{trail}{child.get('name') or ''} / ")

    if tree:
        walk(tree, "")
    return out


def _short(value: Any, limit: int = 80) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    s = str(value if value is not None else "").replace("\n", "⏎ ")
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _mask(key: str, value: str) -> str:
    return "••••" if value and _SECRET.search(key or "") else value


def _kv_changes(old: List[Dict], new: List[Dict]) -> List[str]:
    def idx(rows):
        return {str(r.get("key")): r for r in rows or [] if isinstance(r, dict) and r.get("key")}
    a, b = idx(old), idx(new)
    out = [f"+ {k} = {_mask(k, _short(b[k].get('value'), 40))}" for k in b.keys() - a.keys()]
    out += [f"- {k}" for k in a.keys() - b.keys()]
    for k in a.keys() & b.keys():
        va, vb = a[k].get("value"), b[k].get("value")
        if va != vb:
            out.append(f"~ {k}: {_mask(k, _short(va, 30))} → {_mask(k, _short(vb, 30))}")
        elif a[k].get("enabled", True) != b[k].get("enabled", True):
            out.append(f"~ {k}: {'启用' if b[k].get('enabled', True) else '停用'}")
    return sorted(out, key=lambda s: s[2:])


def _field_changes(a: Dict[str, Any], b: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for key, label in _FIELDS:
        va, vb = a.get(key), b.get(key)
        if _clean(va) == _clean(vb) or (not va and not vb):
            continue
        if key in ("params", "headers", "cookies"):
            lines = _kv_changes(va or [], vb or [])
        elif key == "auth":
            ta, tb = (va or {}).get("type"), (vb or {}).get("type")
            lines = [f"{ta or 'none'} → {tb or 'none'}"] if ta != tb else ["凭据已修改（不显示明文）"]
        elif key == "body":
            ma, mb = (va or {}).get("mode"), (vb or {}).get("mode")
            lines = [f"模式 {ma} → {mb}"] if ma != mb else []
            ra, rb = (va or {}).get("raw") or "", (vb or {}).get("raw") or ""
            if ra != rb:
                lines += line_diff(ra, rb, context=1)[:30]
            if (va or {}).get("gql_vars") != (vb or {}).get("gql_vars"):
                lines.append("GraphQL 变量已修改")
            if not lines:
                lines = ["表单 / 文件已修改"]
        elif key == "scripts":
            lines = [f"{k} 已修改" for k in sorted(set(va or {}) | set(vb or {}))
                     if (va or {}).get(k) != (vb or {}).get(k)]
        else:
            lines = [f"{_short(va)} → {_short(vb)}"]
        if lines:
            out.append({"field": key, "label": label, "lines": lines})
    return out


def semantic_diff(old: Optional[Dict[str, Any]],
                  new: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{kind: added|removed|changed, name, method, path, changes:[{label, lines}]}]"""
    a, b = _requests(old), _requests(new)
    out: List[Dict[str, Any]] = []
    for kind, src, ids in (("added", b, b.keys() - a.keys()), ("removed", a, a.keys() - b.keys())):
        for rid in ids:
            trail, r = src[rid]
            out.append({"kind": kind, "id": rid, "name": r.get("name") or "", "path": trail,
                        "method": r.get("method") or "GET", "changes": []})
    for rid in a.keys() & b.keys():
        (ta, ra), (tb, rb) = a[rid], b[rid]
        changes = _field_changes(ra, rb)
        if ta != tb:
            changes.insert(0, {"field": "path", "label": "位置",
                               "lines": [f"{ta or '根目录'} → {tb or '根目录'}"]})
        if changes:
            out.append({"kind": "changed", "id": rid, "name": rb.get("name") or "",
                        "path": tb, "method": rb.get("method") or "GET", "changes": changes})
    order = {"changed": 0, "added": 1, "removed": 2}
    out.sort(key=lambda d: (order[d["kind"]], d["path"], d["name"]))
    return out


def line_diff(old: str, new: str, context: int = 3) -> List[str]:
    lines = difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=context)
    return [ln for ln in lines if not ln.startswith(("---", "+++"))]


def stats(items: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"added": 0, "removed": 0, "changed": 0}
    for it in items:
        out[it["kind"]] += 1
    return out


_GIT: Optional[str] = None


def git_path() -> Optional[str]:
    """真能用的 git。macOS 没装命令行工具时 /usr/bin/git 只是个弹安装框的桩，
    直接调会弹系统窗口 —— 先确认 CommandLineTools / Xcode 在，再 --version 试一次。"""
    global _GIT
    if _GIT is not None:
        return _GIT or None
    # 从 Finder 启动的 .app 拿不到终端里的 PATH，常见安装位置逐个兜底；
    # OCELOT_GIT 可以指定任意路径。
    for cand in (os.environ.get("OCELOT_GIT"), shutil.which("git"), "/opt/homebrew/bin/git",
                 "/usr/local/bin/git", "/Library/Developer/CommandLineTools/usr/bin/git",
                 "/Applications/Xcode.app/Contents/Developer/usr/bin/git",
                 os.path.expanduser("~/.local/bin/git"), "/opt/local/bin/git", "/usr/bin/git"):
        if not cand or not os.path.exists(cand):
            continue
        if cand == "/usr/bin/git" and not (
                os.path.exists("/Library/Developer/CommandLineTools/usr/bin/git")
                or os.path.exists("/Applications/Xcode.app")):
            continue
        try:
            r = subprocess.run([cand, "--version"], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0:
            _GIT = cand
            return cand
    _GIT = ""
    return None


def _git(folder: Path, *args: str, timeout: int = 15) -> Tuple[int, str]:
    exe = git_path()
    if not exe:
        return 127, "没有找到可用的 git（xcode-select --install 或 brew install git）"
    try:
        r = subprocess.run([exe, *args], cwd=str(folder), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return r.returncode, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout)).strip()


def is_repo(folder: Path) -> bool:
    return git_path() is not None and _git(folder, "rev-parse", "--is-inside-work-tree")[0] == 0


def branch(folder: Path) -> str:
    code, out = _git(folder, "rev-parse", "--abbrev-ref", "HEAD")
    return out if code == 0 else ""


def show_at(folder: Path, rev: str, path: Path) -> Optional[str]:
    """文件在某个提交里的内容；没提交过 / 没 git 返回 None。"""
    if not is_repo(folder):
        return None
    code, top = _git(folder, "rev-parse", "--show-toplevel")
    if code:
        return None
    try:
        rel = Path(path).resolve().relative_to(Path(top).resolve())
    except ValueError:
        return None
    code, out = _git(folder, "show", f"{rev}:{rel.as_posix()}")
    return out + "\n" if code == 0 else None


def log(folder: Path, path: Path, limit: int = 20) -> List[Dict[str, str]]:
    code, out = _git(folder, "log", f"-{limit}", "--format=%h%x1f%ar%x1f%an%x1f%s", "--", str(path))
    if code or not out:
        return []
    keys = ("hash", "when", "author", "subject")
    return [dict(zip(keys, ln.split("\x1f"))) for ln in out.splitlines() if ln.count("\x1f") == 3]


def commit(folder: Path, paths: List[Path], message: str) -> Tuple[bool, str]:
    if not is_repo(folder):
        code, out = _git(folder, "init")
        if code:
            return False, out
    code, out = _git(folder, "add", "--", *[str(p) for p in paths])
    if code:
        return False, out
    ident = []
    if _git(folder, "config", "user.email")[0] != 0:
        # 新机器常见：没配身份 git 会拒绝提交。只给这一次提交带上兜底身份，
        # 不改用户的全局配置。
        ident = ["-c", "user.name=Ocelot", "-c", "user.email=ocelot@localhost"]
    code, out = _git(folder, *ident, "commit", "-m", message or "Update collections",
                     "--", *[str(p) for p in paths])
    if code and ("nothing to commit" in out or "no changes added" in out):
        return True, "没有需要提交的改动"
    return code == 0, (out.splitlines()[0] if out else "")


def auto_write(settings: Dict[str, Any], collections: List[Dict[str, Any]]) -> None:
    """保存钩子：开了「保存时自动写入」就同步进文件夹；内容没变不碰文件。"""
    cfg = settings.get("git") or {}
    if not cfg.get("auto") or not cfg.get("dir"):
        return
    folder = Path(cfg["dir"])
    for node in collections:
        try:
            write(folder, node)
        except OSError:
            return
