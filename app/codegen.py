"""请求代码生成：cURL / Python requests / JavaScript fetch / HTTPie。"""
from __future__ import annotations

import base64
import json
import shlex
from typing import Any, Dict, List, Optional, Tuple

from .store import body_content_type, body_mode, resolve_vars


def _prepare(req: Dict[str, Any], env: Dict[str, str]) -> Dict[str, Any]:
    url = resolve_vars(req.get("url", ""), env).strip()
    if url and "://" not in url:
        url = "http://" + url
    headers: List[Tuple[str, str]] = []
    for row in req.get("headers", []):
        if row.get("enabled", True) and row.get("key"):
            headers.append((resolve_vars(str(row["key"]), env),
                            resolve_vars(str(row.get("value", "")), env)))

    params = [(resolve_vars(str(r["key"]), env), resolve_vars(str(r.get("value", "")), env))
              for r in req.get("params", [])
              if r.get("enabled", True) and r.get("key") and r.get("type") != "file"]
    if params:
        from urllib.parse import parse_qsl, urlencode, urlsplit

        # 地址里已经写了的同名同值参数不再追加一遍 —— 否则生成的代码和文档里
        # 会出现 ?verbose=true&verbose=true 这种重复（粘贴到别处还会误导人）
        try:
            existing = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        except ValueError:
            existing = {}
        fresh = [(k, v) for k, v in params if existing.get(k) != v]
        if fresh:
            sep = "" if url.endswith(("?", "&")) else ("&" if "?" in url else "?")
            url = url + sep + urlencode(fresh)

    auth = req.get("auth") or {}
    atype = auth.get("type", "none")
    if atype == "bearer" and auth.get("token"):
        headers.append(("Authorization", f"Bearer {resolve_vars(auth['token'], env)}"))
    elif atype == "basic":
        pair = f"{auth.get('username', '')}:{auth.get('password', '')}".encode()
        headers.append(("Authorization", "Basic " + base64.b64encode(pair).decode()))
    elif atype == "apikey" and auth.get("key") and auth.get("add_to") == "header":
        headers.append((auth["key"], resolve_vars(auth.get("value", ""), env)))

    # Cookie 页里的行合并进一条 Cookie 头：表在前、手写头在后，
    # 与真实发送顺序一致，复制出来的代码和点「发送」的结果才对得上。
    cookie_pairs = [(resolve_vars(str(r["key"]), env), resolve_vars(str(r.get("value", "")), env))
                    for r in req.get("cookies", [])
                    if r.get("enabled", True) and r.get("key")]
    if cookie_pairs:
        jar = "; ".join(f"{k}={v}" for k, v in cookie_pairs)
        for i, (k, v) in enumerate(headers):
            if k.lower() == "cookie":
                headers[i] = (k, f"{jar}; {v}" if v else jar)
                break
        else:
            headers.append(("Cookie", jar))

    bdata = req.get("body") or {}
    mode = body_mode(bdata)
    body: Optional[str] = None
    form: List[Tuple[str, str]] = []
    files: List[Tuple[str, str]] = []
    if mode == "graphql":
        from .graphql import payload_text

        body = resolve_vars(payload_text(bdata), env)
        if not any(k.lower() == "content-type" for k, _ in headers):
            headers.append(("Content-Type", "application/json"))
    elif mode in ("json", "text", "xml", "html"):
        body = resolve_vars(bdata.get("raw", "") or "", env)
        if not any(k.lower() == "content-type" for k, _ in headers):
            headers.append(("Content-Type", body_content_type(bdata)))
    elif mode == "urlencoded":
        form = [(resolve_vars(str(r["key"]), env), resolve_vars(str(r.get("value", "")), env))
                for r in bdata.get("form", [])
                if r.get("enabled", True) and r.get("key") and r.get("type") != "file"]
        if not any(k.lower() == "content-type" for k, _ in headers):
            headers.append(("Content-Type", "application/x-www-form-urlencoded"))
    elif mode == "form":
        for r in bdata.get("form", []):
            if not r.get("enabled", True) or not r.get("key"):
                continue
            val = resolve_vars(str(r.get("value", "")), env)
            if r.get("type") == "file" or val.startswith("@"):
                path = val[1:].strip() if val.startswith("@") else val.strip()
                files.append((resolve_vars(str(r["key"]), env), path))
            else:
                form.append((resolve_vars(str(r["key"]), env), val))
    elif mode == "binary":
        path = bdata.get("file") or ""
        if path:
            files.append(("file", path))

    return {
        "url": url, "method": (req.get("method") or "GET").upper(),
        "headers": headers, "body": body, "form": form, "files": files,
        "mode": mode, "auth": auth,
    }


def to_curl(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    parts = [f"curl -X {d['method']}"]
    parts.append(shlex.quote(d["url"]))
    for k, v in d["headers"]:
        parts.append(f"-H {shlex.quote(f'{k}: {v}')}")
    if d["body"] is not None:
        parts.append(f"--data-raw {shlex.quote(d['body'])}")
    for k, v in d["form"]:
        parts.append(f"--data-urlencode {shlex.quote(f'{k}={v}')}")
    for k, path in d["files"]:
        parts.append(f"-F {shlex.quote(f'{k}=@{path}')}")
    insecure = not (settings or {}).get("verify_ssl", True)
    if insecure:
        parts.append("-k")
    follow = (settings or {}).get("follow_redirects", True)
    if not follow:
        parts.append("--max-redirs 0")
    return " \\\n  ".join(parts)


def to_python(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = ["import requests", ""]
    lines.append(f'url = "{d["url"]}"')
    if d["headers"]:
        lines.append("headers = {")
        for k, v in d["headers"]:
            lines.append(f'    "{k}": {json.dumps(v, ensure_ascii=False)},')
        lines.append("}")
    if d["mode"] == "json" and d["body"]:
        lines.append("")
        lines.append("payload = " + (d["body"] or "{}"))
        lines.append("")
        lines.append("resp = requests.request(")
        lines.append(f'    "{d["method"]}", url, headers=headers, json=payload, timeout=30,')
        lines.append(f'    verify={bool(settings.get("verify_ssl", True)) if settings else True},')
        lines.append(")")
    else:
        data_arg = "data=payload" if (d["body"] is not None or d["form"]) else ""
        lines.append("payload = {")
        for k, v in d["form"]:
            lines.append(f'    "{k}": {json.dumps(v, ensure_ascii=False)},')
        lines.append("}")
        lines.append("")
        lines.append(f'resp = requests.request("{d["method"]}", url, headers=headers, {data_arg} timeout=30)')
    lines.append("")
    lines.append('print(resp.status_code, resp.reason)')
    lines.append("print(resp.text)")
    return "\n".join(lines)


def to_js(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    obj = {"method": d["method"]}
    if d["headers"]:
        obj["headers"] = {k: v for k, v in d["headers"]}
    if d["body"] is not None:
        obj["body"] = d["body"]
    elif d["form"]:
        obj["body"] = "new URLSearchParams({" + ", ".join(
            f'{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}' for k, v in d["form"]) + "}).toString()"
    body = json.dumps(obj, indent=2, ensure_ascii=False)
    # body 字段若为原始 JSON 文本，去掉外层引号以保持可执行
    if d["body"] is not None:
        body = body.replace(json.dumps(d["body"], ensure_ascii=False), "JSON.stringify(" + d["body"] + ")")
    return (
        f'const res = await fetch("{d["url"]}", {body});\n'
        "const text = await res.text();\n"
        "console.log(res.status, text);"
    )


def to_httpie(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    parts = ["http", d["method"], shlex.quote(d["url"])]
    for k, v in d["headers"]:
        parts.append(shlex.quote(f"{k}:{v}"))
    for k, v in d["form"]:
        parts.append(shlex.quote(f"{k}={v}"))
    for k, path in d["files"]:
        parts.append(shlex.quote(f"{k}@{path}"))
    cmd = " \\\n  ".join(parts)
    if d["body"]:
        cmd += " <<< " + shlex.quote(d["body"])
    return cmd


# ---------------------------------------------------------------- 更多常用语言


def to_go(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = ['package main', '', 'import (', '    "fmt"', '    "io"', '    "net/http"', '    "strings"', ')', '',
             'func main() {']
    hdr = ", ".join(f'"{k}": {{"{v}"}}' for k, v in d["headers"])
    if hdr:
        lines += [f'    headers := http.Header{{{hdr}}}', '']
    body_expr = "nil"
    if d["body"] is not None:
        body_expr = f'strings.NewReader({json.dumps(d["body"], ensure_ascii=False)})'
    elif d["form"]:
        pairs = "&".join(f'{k}={v}' for k, v in d["form"])
        lines.append(f'    payload := strings.NewReader({json.dumps(pairs, ensure_ascii=False)})')
        body_expr = "payload"
    lines += [f'    req, _ := http.NewRequest("{d["method"]}", {json.dumps(d["url"], ensure_ascii=False)}, {body_expr})']
    if hdr:
        lines.append('    req.Header = headers')
    lines += ['    client := &http.Client{}', '    resp, err := client.Do(req)',
              '    if err != nil { panic(err) }', '    defer resp.Body.Close()',
              '    data, _ := io.ReadAll(resp.Body)', '    fmt.Println(resp.Status)',
              '    fmt.Println(string(data))', '}']
    return "\n".join(lines)


def to_java(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = ['import java.net.http.*;', 'import java.net.*;', 'import java.nio.charset.StandardCharsets;',
             '', 'public class ReqlyRequest {', '    public static void main(String[] args) throws Exception {',
             f'        var uri = URI.create({json.dumps(d["url"], ensure_ascii=False)});',
             f'        var builder = HttpRequest.newBuilder(uri).method(',
             f'            "{d["method"]}", ',
             f'            HttpRequest.BodyPublishers.{("ofString(" + json.dumps(d["body"], ensure_ascii=False) + ")") if d["body"] is not None else "noBody()"}),']
    for k, v in d["headers"]:
        lines.append(f'        builder.header({json.dumps(k, ensure_ascii=False)}, {json.dumps(v, ensure_ascii=False)});')
    lines += ['        var client = HttpClient.newHttpClient();',
              '        var response = client.send(builder.build(), HttpResponse.BodyHandlers.ofString());',
              '        System.out.println(response.statusCode());',
              '        System.out.println(response.body());', '    }', '}']
    return "\n".join(lines)


def to_php(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = ['<?php', '$ch = curl_init();',
             f'curl_setopt($ch, CURLOPT_URL, {json.dumps(d["url"], ensure_ascii=False)});',
             f'curl_setopt($ch, CURLOPT_CUSTOMREQUEST, "{d["method"]}");',
             'curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);']
    if d["headers"]:
        lines.append('curl_setopt($ch, CURLOPT_HTTPHEADER, ' +
                     json.dumps([f"{k}: {v}" for k, v in d["headers"]], ensure_ascii=False) + ');')
    if d["body"] is not None:
        lines.append(f'curl_setopt($ch, CURLOPT_POSTFIELDS, {json.dumps(d["body"], ensure_ascii=False)});')
    verify = bool((settings or {}).get("verify_ssl", True))
    lines += [f'curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, {"true" if verify else "false"});',
              '$response = curl_exec($ch);', 'echo curl_getinfo($ch, CURLINFO_RESPONSE_CODE) . PHP_EOL;',
              'echo $response . PHP_EOL;', 'curl_close($ch);']
    return "\n".join(lines)


def to_csharp(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = ['using System;', 'using System.Net.Http;', 'using System.Text;', '',
             'var client = new HttpClient();',
             f'var request = new HttpRequestMessage(new HttpMethod("{d["method"]}"), '
             f'{json.dumps(d["url"], ensure_ascii=False)});']
    for k, v in d["headers"]:
        lines.append(f'request.Headers.TryAddWithoutValidation({json.dumps(k, ensure_ascii=False)}, '
                     f'{json.dumps(v, ensure_ascii=False)});')
    if d["body"] is not None:
        lines.append(f'request.Content = new StringContent({json.dumps(d["body"], ensure_ascii=False)}, '
                     'Encoding.UTF8, "application/json");')
    lines += ['var response = await client.SendAsync(request);',
              'Console.WriteLine((int)response.StatusCode);',
              'Console.WriteLine(await response.Content.ReadAsStringAsync());']
    return "\n".join(lines)


def to_kotlin(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = ['import kotlinx.coroutines.*', 'import java.net.URL', '', 'fun main() = runBlocking {',
             f'    val url = URL({json.dumps(d["url"], ensure_ascii=False)})']
    hdr = ", ".join(f'"{k}" to "{v}"' for k, v in d["headers"])
    if hdr:
        lines.append(f'    val headers = mapOf({hdr})')
    body = json.dumps(d["body"] or "", ensure_ascii=False)
    lines += [f'    val body = {body}',
              '    val conn = url.openConnection() as HttpURLConnection',
              f'    conn.requestMethod = "{d["method"]}"']
    if hdr:
        lines.append('    headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }')
    lines += ['    if (body.isNotEmpty()) {', '        conn.doOutput = true',
              '        conn.outputStream.use { it.write(body.toByteArray()) }', '    }',
              '    println(conn.responseCode)', '    println(conn.inputStream.bufferedReader().readText())', '}']
    return "\n".join(lines)


def to_powershell(req: Dict[str, Any], env: Dict[str, str], settings: Optional[Dict] = None) -> str:
    d = _prepare(req, env)
    lines = [f'$url = {json.dumps(d["url"], ensure_ascii=False)}',
             '$headers = @{']
    for k, v in d["headers"]:
        lines.append(f'    "{k}" = "{v}"')
    lines += ['}', f'$response = Invoke-WebRequest -Uri $url -Method {d["method"]} -Headers $headers']
    if d["body"] is not None:
        lines.insert(-1, f'$body = {json.dumps(d["body"], ensure_ascii=False)}')
        lines[-1] += ' -Body $body'
    lines += ['Write-Output $response.StatusCode', 'Write-Output $response.Content']
    return "\n".join(lines)


LANGUAGES = [
    ("curl", "cURL", to_curl, "shell"),
    ("python", "Python", to_python, "python"),
    ("js", "JavaScript", to_js, "javascript"),
    ("httpie", "HTTPie", to_httpie, "shell"),
    ("go", "Go", to_go, "go"),
    ("java", "Java", to_java, "java"),
    ("php", "PHP", to_php, "php"),
    ("csharp", "C#", to_csharp, "csharp"),
    ("kotlin", "Kotlin", to_kotlin, "kotlin"),
    ("powershell", "PowerShell", to_powershell, "powershell"),
]
