#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scidown-mcp-server.py — 文献下载 MCP 服务器(纯 Python, 零第三方依赖)
=======================================================================

基于 open-access.shop / Scidown 生态的文献 PDF 下载工具集。
仅使用 Python 标准库 + requests(核心逻辑需要) + poppler 的 pdftotext(可选, 用于题名核对)。

接入方式(stdio):
    {
      "mcpServers": {
        "scidown-paper": {
          "command": "python3",
          "args": ["/path/to/mcp-server/server.py"],
          "env": {"SCIDOWN_DL_HOME": "~/.scidown-mcp"}
        }
      }
    }

工具一览
--------
无需登录:
    download_paper(doi, out_dir?, title?)    单篇下载(bb缓存直链→zy9模式探测→登录网关)
    batch_download(dois, out_dir?, delay?)   批量下载(限速, 单次最多10篇)
    probe_patterns(doi)                      无登录探测 bban/zy9 两种模式直链状态
    make_workbench(dois, out_file?)          生成人工点击下载工作台 HTML(浏览器过CF)
    library_status()                         库存盘点
    harvest_downloads(source_dir?, tasks?)   从下载文件夹按题名收割入库
会话相关:
    scidown_status()                         登录态检查
    scidown_captcha()                        获取登录图形验证码(base64 PNG, 供视觉AI识读)
    scidown_login(username, password, code)  登录并持久化会话
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))  # 同目录放一份 lib 也能用

try:
    import scidown_lib as L
except ImportError:
    sys.stderr.write("[scidown-mcp] 未找到 scidown_lib.py, 请与 server.py 同目录或位于 ../scripts\n")
    raise

HOME = os.path.expanduser(os.environ.get("SCIDOWN_DL_HOME", "~/.scidown-mcp"))
COOKIE_FILE = os.path.join(HOME, "scidown_cookies.txt")
TASKS_FILE = os.path.join(HOME, "tasks.json")
LIB_DIR = os.path.join(HOME, "library")
os.makedirs(HOME, exist_ok=True)
os.makedirs(LIB_DIR, exist_ok=True)

SESSION = L.ScidownSession(COOKIE_FILE)

# ================================================================= 工具实现

def _save_pdf(no, doi, title, content, out_dir):
    out_dir = out_dir or LIB_DIR
    os.makedirs(out_dir, exist_ok=True)
    text = L.pdf_text  # noqa: F841 (占位, 实际用临时文件提取)
    tmp = os.path.join(out_dir, f".tmp_{no or 'x'}.pdf")
    with open(tmp, "wb") as f:
        f.write(content)
    tstr = L.pdf_text(tmp)
    if title:
        ok, note = L.verify_title(tstr, expected_title=title, as_text=True)
        if not ok:
            os.remove(tmp)
            return None, f"题名核对未通过({note}), 已丢弃。如确认无误可带 skip_verify=true 重试"
    else:
        note = "未提供标题, 跳过题名核对"
    author, year = L.extract_author_year(tstr, title or doi)
    slug = "_".join(re.findall(r"[A-Za-z0-9]+", L._nfkc(title or doi)))[:75].rstrip("_")
    name = f"{no or ''}{'' if not no else '_'}{L.safe_name(author)}_{year}_{L.safe_name(slug)}.pdf"
    dest = os.path.join(out_dir, name)
    os.replace(tmp, dest)
    sha = hashlib.sha256(content).hexdigest()[:16]
    return dest, f"{note}; {len(content)//1024}KB; sha256:{sha}"


def t_download_paper(args):
    doi = args["doi"].strip()
    if not L.valid_doi(doi):
        return {"error": f"DOI 不合法: {doi}"}
    title = args.get("title")
    out_dir = args.get("out_dir") or LIB_DIR
    skip_verify = args.get("skip_verify", False)
    # 1. 缓存直链
    b, url, st = L.download_cached(doi)
    if b:
        dest, note = _save_pdf("", doi, title, b, out_dir)
        if dest:
            return {"ok": True, "route": "bban-cache", "url": url, "file": dest, "note": note}
        return {"ok": False, "route": "bban-cache", "reason": note}
    # 2. zy9 模式直链(curl 引擎, 少数情形可过)
    b, st2 = L.fetch_pdf(L.ZY9.format(doi=doi), referer="http://down.sciokk.cn/", engine="auto")
    if b:
        dest, note = _save_pdf("", doi, title, b, out_dir)
        if dest:
            return {"ok": True, "route": "zy9-direct", "file": dest, "note": note}
    # 3. 登录态网关
    if not SESSION.is_logged_in():
        return {"ok": False, "reason": "缓存与zy9均未命中; 网关路线需要登录",
                "hint": "调用 scidown_captcha() 获取验证码图片 → 识读 → scidown_login() 后重试"}
    r = SESSION.resolve(doi)
    if r["gated"]:
        return {"ok": False, "reason": "触发顶象防护(IP 风控)", "hint": "等待冷却或人工浏览器过滑块"}
    if not r["url"]:
        return {"ok": False, "reason": "解析为空: " + r["note"]}
    b, st3 = L.download_gateway(r["url"])
    if not b:
        return {"ok": False, "reason": f"网关下载失败 HTTP {st3}", "gateway": r["url"],
                "hint": "zdwe/zy9/lanzou 后端可能需要真实浏览器; 可用 make_workbench() 生成人工点击页"}
    dest, note = _save_pdf("", doi, title, b, out_dir)
    if dest:
        return {"ok": True, "route": f"gateway-{r['backend']}", "file": dest, "note": note}
    return {"ok": False, "reason": note}


def t_batch_download(args):
    dois = [d.strip() for d in args["dois"] if L.valid_doi(d.strip())][: int(args.get("max", 10))]
    delay = float(args.get("delay", 5.0))
    out = []
    for i, doi in enumerate(dois):
        r = t_download_paper({"doi": doi, "title": (args.get("titles") or {}).get(doi),
                              "out_dir": args.get("out_dir"),
                              "skip_verify": args.get("skip_verify", False)})
        out.append({"doi": doi, **r})
        if i < len(dois) - 1:
            time.sleep(delay)
    ok_n = sum(1 for r in out if r.get("ok"))
    return {"summary": f"{ok_n}/{len(out)}", "results": out,
            "note": "单次最多处理 max 篇, 剩余请再次调用以免触发风控"}


def t_probe_patterns(args):
    doi = args["doi"].strip()
    out = {}
    b, url, st = L.download_cached(doi)
    out["bban_cache"] = {"url": url, "status": (str(st)) if b else str(st),
                         "ok": bool(b)}
    b2, st2 = L.fetch_pdf(L.ZY9.format(doi=doi) + "?download=true",
                          referer="http://down.sciokk.cn/", engine="curl")
    out["zy9_direct"] = {"url": L.ZY9.format(doi=doi), "status": str(st2), "ok": bool(b2)}
    out["hint"] = "两者都失败时: 该文献在 zy9/bban 缓存外, 需登录解析(zdwe网关/蓝奏云)或人工浏览器"
    return out


def t_scidown_status(args):
    return {"logged_in": SESSION.is_logged_in(),
            "cookie_file": COOKIE_FILE,
            "cookie_exists": os.path.exists(COOKIE_FILE)}


def t_scidown_captcha(args):
    b64 = SESSION.get_login_captcha_b64()
    return {"image_base64_png": b64,
            "hint": "这是4位图形验证码(可能含字母)。用视觉能力识读后, 将文本传给 scidown_login"}


def t_scidown_login(args):
    ok, note = SESSION.login(args["username"], args["password"], args["code"])
    return {"ok": ok, "note": note, "cookie_file": COOKIE_FILE if ok else None,
            "hint": "" if ok else "验证码错误或账号密码错误; 可重新 scidown_captcha() 换一张"}


def t_library_status(args):
    lib = args.get("out_dir") or LIB_DIR
    files = sorted(f for f in os.listdir(lib) if f.endswith(".pdf")) if os.path.isdir(lib) else []
    tasks = []
    if os.path.exists(TASKS_FILE):
        tasks = json.load(open(TASKS_FILE, encoding="utf-8"))
    done_nos = {f.split("_")[0] for f in files}
    missing = [t["no"] for t in tasks if t.get("no") and t["no"] not in done_nos] if tasks else []
    return {"library": lib, "pdf_count": len(files), "files": files,
            "tasks_registered": len(tasks), "tasks_missing": missing}


def t_harvest_downloads(args):
    src = os.path.expanduser(args.get("source_dir", "~/Downloads"))
    out_dir = args.get("out_dir") or LIB_DIR
    tasks = args.get("tasks")
    if not tasks and os.path.exists(TASKS_FILE):
        tasks = json.load(open(TASKS_FILE, encoding="utf-8"))
    moved, unmatched = [], []
    for f in sorted(os.listdir(src)):
        if not f.lower().endswith(".pdf"):
            continue
        p = os.path.join(src, f)
        try:
            if time.time() - os.path.getmtime(p) > 86400:
                continue
            if os.path.getsize(p) < 10000:
                continue
        except OSError:
            continue
        if not tasks:
            unmatched.append({"file": f, "reason": "未注册任务清单(tasks.json), 无法按题名归属"})
            continue
        text = L.pdf_text(p)
        best, hit = None, 0
        for t in tasks:
            words = L.title_words(t["title"])
            h = sum(1 for w in words if w in L.norm_text(text))
            if h > hit:
                best, hit = t, h
        need = max(3, int(len(L.title_words(best["title"])) * 0.6)) if best else 99
        if best and hit >= need:
            author, year = L.extract_author_year(text, best["title"])
            slug = "_".join(re.findall(r"[A-Za-z0-9]+", L._nfkc(best["title"])))[:75].rstrip("_")
            name = f"{best['no']}_{L.safe_name(author)}_{year}_{L.safe_name(slug)}.pdf"
            shutil.move(p, os.path.join(out_dir, name))
            moved.append({"no": best["no"], "from": f, "to": name})
        else:
            unmatched.append({"file": f, "reason": f"最高命中 {hit} 词不足"})
    return {"moved": moved, "unmatched": unmatched, "library": out_dir}


def t_make_workbench(args):
    dois = args["dois"]
    out_file = args.get("out_file") or os.path.join(HOME, "workbench.html")
    rows = []
    for i, doi in enumerate(dois, 1):
        bban = L.BBAN.format(doi=doi)
        zy9 = L.ZY9.format(doi=doi) + "?download=true"
        rows.append(f"<tr><td class='no'>{i}</td><td>{doi}</td>"
                    f"<td><a class='a' target='_blank' href='{bban}'>① 缓存直链</a>"
                    f"<a class='b' target='_blank' href='{zy9}'>② zy9线路</a></td></tr>")
    html = ("<!DOCTYPE html><html lang=\"zh\"><head><meta charset=\"utf-8\">"
            "<title>下载工作台</title><style>"
            "body{font-family:sans-serif;max-width:860px;margin:30px auto;padding:0 16px}"
            "td{border:1px solid #ddd;padding:10px}table{border-collapse:collapse;width:100%}"
            ".no{font-weight:700;color:#2c7;text-align:center}"
            "a{display:inline-block;margin:3px;padding:8px 14px;border-radius:6px;color:#fff;text-decoration:none}"
            ".a{background:#2c7}.b{background:#c81}"
            ".note{background:#fff8e1;border:1px solid #f0d264;border-radius:8px;padding:12px;line-height:1.7}"
            "</style></head><body><h2>下载工作台</h2><div class='note'>"
            "逐篇点击 ①,404 则点 ②。出现 Cloudflare 五秒盾请等待自动通过。"
            "PDF 将下载到浏览器默认下载文件夹, 之后可用 harvest_downloads() 收割入库。</div>"
            "<table>" + "".join(rows) + "</table></body></html>")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html)
    try:  # macOS 顺手打开
        subprocess.Popen(["open", out_file])
    except Exception:
        pass
    return {"ok": True, "file": out_file, "count": len(dois),
            "usage": "用浏览器逐篇点击下载后, 调用 harvest_downloads() 收割入库"}


def t_register_tasks(args):
    """注册任务清单(编号/标题/DOI), 供 library_status 与 harvest_downloads 使用"""
    tasks = args["tasks"]
    json.dump(tasks, open(TASKS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return {"ok": True, "file": TASKS_FILE, "count": len(tasks)}


# ================================================================= 工具定义

TOOLS = [
    {"name": "download_paper",
     "description": "下载单篇文献 PDF(DOI)。三级路线: bban缓存直链 → zy9模式 → 登录态zdwe网关。带题名核对。",
     "inputSchema": {"type": "object", "properties": {
         "doi": {"type": "string", "description": "文献 DOI, 如 10.1007/s11033-018-4323-4"},
         "title": {"type": "string", "description": "论文标题(用于题名核对, 强烈建议提供)"},
         "out_dir": {"type": "string", "description": "保存目录, 默认 ~/.scidown-mcp/library"},
         "skip_verify": {"type": "boolean", "description": "跳过题名核对"}},
         "required": ["doi"]}},
    {"name": "batch_download",
     "description": "批量下载多篇(限速防风控, 单次默认最多10篇, 剩余分批调用)。",
     "inputSchema": {"type": "object", "properties": {
         "dois": {"type": "array", "items": {"type": "string"}},
         "titles": {"type": "object", "description": "{doi: title} 题名映射"},
         "out_dir": {"type": "string"}, "delay": {"type": "number"},
         "max": {"type": "number", "description": "单次上限, 默认10"}},
         "required": ["dois"]}},
    {"name": "probe_patterns",
     "description": "无登录探测某 DOI 在 bban/zy9 两个固定模式直链上的可用性。",
     "inputSchema": {"type": "object", "properties": {"doi": {"type": "string"}}, "required": ["doi"]}},
    {"name": "scidown_status",
     "description": "检查 Scidown 登录态。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "scidown_captcha",
     "description": "获取 Scidown 登录图形验证码(base64 PNG)。供有视觉能力的模型识读。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "scidown_login",
     "description": "登录 Scidown(用于未收录文献的网关解析路线)。会话约30分钟过期。",
     "inputSchema": {"type": "object", "properties": {
         "username": {"type": "string"}, "password": {"type": "string"}, "code": {"type": "string"}},
         "required": ["username", "password", "code"]}},
    {"name": "library_status",
     "description": "盘点文献库: 已有 PDF 清单 + 注册任务中缺失的编号。",
     "inputSchema": {"type": "object", "properties": {"out_dir": {"type": "string"}}}},
    {"name": "harvest_downloads",
     "description": "从下载文件夹收割 PDF: 按题名匹配任务清单, 自动改名入库。",
     "inputSchema": {"type": "object", "properties": {
         "source_dir": {"type": "string", "description": "默认 ~/Downloads"},
         "out_dir": {"type": "string"},
         "tasks": {"type": "array", "description": "[{no,title,doi}], 缺省用已注册清单"}}}},
    {"name": "make_workbench",
     "description": "生成人工点击下载工作台 HTML(自动用默认浏览器打开)。适用于脚本被CF/风控拦截时, 由人点击、AI收割。",
     "inputSchema": {"type": "object", "properties": {
         "dois": {"type": "array", "items": {"type": "string"}},
         "out_file": {"type": "string"}}, "required": ["dois"]}},
    {"name": "register_tasks",
     "description": "注册任务清单 [{no,title,doi}] 到本地, 供 library_status/harvest_downloads 使用。",
     "inputSchema": {"type": "object", "properties": {
         "tasks": {"type": "array", "items": {"type": "object"}}, "required": ["tasks"]}}},
]

DISPATCH = {
    "download_paper": t_download_paper,
    "batch_download": t_batch_download,
    "probe_patterns": t_probe_patterns,
    "scidown_status": t_scidown_status,
    "scidown_captcha": t_scidown_captcha,
    "scidown_login": t_scidown_login,
    "library_status": t_library_status,
    "harvest_downloads": t_harvest_downloads,
    "make_workbench": t_make_workbench,
    "register_tasks": t_register_tasks,
}

# ================================================================= MCP stdio 骨架

def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(req):
    method = req.get("method", "")
    id_ = req.get("id")
    if method == "initialize":
        return reply(id_, {
            "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "scidown-paper-downloader", "version": "1.0.0"},
        })
    if method == "notifications/initialized" or id_ is None:
        return None  # 通知无需应答
    if method == "ping":
        return reply(id_, {})
    if method == "tools/list":
        return reply(id_, {"tools": TOOLS})
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("arguments", {})
        fn = DISPATCH.get(name)
        if not fn:
            return reply(id_, {"error": {"code": -32602, "message": f"未知工具 {name}"}})
        try:
            result = fn(args)
            return reply(id_, {"content": [{"type": "text",
                                            "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                               "isError": bool(isinstance(result, dict) and result.get("error"))})
        except Exception as e:
            sys.stderr.write(traceback.format_exc())
            return reply(id_, {"content": [{"type": "text", "text": f"工具异常: {e}"}], "isError": True})
    if id_ is not None:
        return reply(id_, {"error": {"code": -32601, "message": f"未知方法 {method}"}})


def main():
    sys.stderr.write("[scidown-mcp] server started on stdio\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(req, list):  # 批量帧
            for r in req:
                out = handle(r)
                if out:
                    sys.stdout.write(out + "\n") if isinstance(out, str) else None
            continue
        out = handle(req)
        if isinstance(out, str):
            sys.stdout.write(out + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
