#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paper_dl.py — CLI 入口:按 DOI 下载文献 PDF(单篇/批量)
========================================================
路线: bban 缓存直链 → zy9 模式 → (可选)登录态网关
用法:
    python3 paper_dl.py 10.1007/s11033-018-4323-4
    python3 paper_dl.py -f dois.txt -o ~/papers --delay 5
    python3 paper_dl.py <DOI> --title "论文标题"     # 提供标题则做题名核对
选项:
    --cookie-file PATH   Scidown 会话 cookie(未收录文献的网关路线需要)
    --test               只探测不落盘
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scidown_lib as L


def load_cookie_session(path):
    if path and os.path.exists(path):
        return L.ScidownSession(path)
    return None


def download_one(doi, out_dir, title=None, sess=None, dry=False):
    r = {"doi": doi, "ok": False}
    # 路线1: bban 缓存
    b, url, st = L.download_cached(doi)
    if b:
        r.update(ok=True, route="bban-cache", url=url, size=len(b))
    # 路线2: zy9 模式
    if not b:
        b, st = L.fetch_pdf(L.ZY9.format(doi=doi), referer="http://down.sciokk.cn/", engine="auto")
        if b:
            r.update(ok=True, route="zy9-direct", size=len(b))
    # 路线3: 登录态网关
    if not b and sess:
        res = sess.resolve(doi)
        r["resolve"] = res
        if res["ok"]:
            b, st = L.download_gateway(res["url"])
            if b:
                r.update(ok=True, route=f"gateway-{res['backend']}", size=len(b))
        elif res["gated"]:
            r["note"] = "触发顶象防护, 请稍后或人工处理"
    if not b:
        r["status"] = str(st)
        return r
    r["sha256_16"] = hashlib.sha256(b).hexdigest()[:16]
    if dry:
        r["note"] = "dry-run, 未落盘"
        return r
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, f".tmp_{L.safe_name(doi)}.pdf")
    open(tmp, "wb").write(b)
    tstr = L.pdf_text(tmp)
    if title:
        ok, note = L.verify_title(tstr, title, as_text=True)
        if not ok:
            os.remove(tmp)
            r.update(ok=False, reason=f"题名核对未通过({note}), 已丢弃")
            return r
        r["verify"] = note
    name = L.make_filename("", title or doi, tstr)
    if name.startswith("_"):
        name = name[1:]
    dest = os.path.join(out_dir, name)
    os.replace(tmp, dest)
    r["file"] = dest
    return r


def main():
    ap = argparse.ArgumentParser(description="DOI 文献下载(bb缓存→zy9→登录网关)")
    ap.add_argument("dois", nargs="*")
    ap.add_argument("-f", "--file", help="DOI 清单文件(每行一个)")
    ap.add_argument("-o", "--out", default="papers")
    ap.add_argument("--delay", type=float, default=5.0)
    ap.add_argument("--title", help="单篇时提供标题用于题名核对")
    ap.add_argument("--cookie-file", default=os.path.expanduser("~/.scidown-mcp/scidown_cookies.txt"))
    ap.add_argument("--test", action="store_true", help="只探测不落盘")
    a = ap.parse_args()

    dois = list(a.dois)
    if a.file:
        text = open(a.file, encoding="utf-8").read()
        dois += L.parse_doi_list(text)
    dois = [d for d in dois if L.valid_doi(d)]
    if not dois:
        ap.error("请提供合法 DOI")
    sess = load_cookie_session(a.cookie_file)
    results = []
    for i, doi in enumerate(dois):
        r = download_one(doi, a.out, title=a.title, sess=sess, dry=a.test)
        mark = "✓" if r.get("ok") else "✗"
        print(f"[{i+1}/{len(dois)}] {mark} {doi} {r.get('route','')} "
              f"{r.get('file', r.get('reason', r.get('status','')))}", flush=True)
        results.append(r)
        if i < len(dois) - 1:
            time.sleep(a.delay)
    ok = sum(1 for r in results if r.get("ok"))
    print(f"完成 {ok}/{len(results)}")
    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
