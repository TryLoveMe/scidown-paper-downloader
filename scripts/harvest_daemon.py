#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收割守护: 监控 ~/Downloads 的新 PDF, 题名匹配后自动改名入库 pdfs_本轮补下载/
用法: python3 收割守护.py [最长运行分钟数, 默认 120]
"""
import json, os, re, shutil, subprocess, sys, time, unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
NEWDIR = os.environ.get("SCIDOWN_LIBRARY", os.path.join(BASE, "..", "library"))
DL = os.environ.get("SCIDOWN_WATCH_DIR", os.path.expanduser("~/Downloads"))
LOG = os.path.join(BASE, "..", "harvest.log")
START = time.time()

SUBS = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
        "₆": "6", "₇": "7", "₈": "8", "₉": "9", "⁴": "4", "‑": "-", "–": "-"}


def norm(s):
    s = unicodedata.normalize("NFKC", s)
    for k, v in SUBS.items():
        s = s.replace(k, v)
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def title_words(title):
    s = unicodedata.normalize("NFKC", title)
    for k, v in SUBS.items():
        s = s.replace(k, v)
    return [w for w in re.findall(r"[A-Za-z0-9]+", s) if len(w) >= 3][:8]


def pdf_text(path, pages=2):
    try:
        r = subprocess.run(["pdftotext", "-l", str(pages), path, "-"],
                           capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def match_task(path, tasks):
    """返回 (task, 命中数) 命中最高的任务"""
    text = pdf_text(path)
    if not text or len(text) < 50:
        return None, 0, "pdftotext无输出"
    np_ = norm(text)
    best, best_hit = None, 0
    for t in tasks:
        words = title_words(t["title"])
        hit = sum(1 for w in words if w in np_)
        if hit > best_hit:
            best, best_hit = t, hit
    if best and best_hit >= max(3, int(len(title_words(best["title"])) * 0.6)):
        return best, best_hit, "ok"
    return best, best_hit, "题名不匹配"


def author_year(path):
    text = re.sub(r"\s+", " ", pdf_text(path))
    year = ""
    t2 = re.sub(r"10\.\d{4,9}/\S+", " ", text)
    m = re.search(r"\b(19[89]\d|20[0-2]\d)\b", t2)
    if m:
        year = m.group(1)
    return year


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    limit_min = float(sys.argv[1]) if len(sys.argv) > 1 else 120
    tf = os.environ.get("SCIDOWN_TASKS", os.path.join(BASE, "..", "examples", "tasks.json"))
    tasks = json.load(open(tf, encoding="utf-8")) if os.path.exists(tf) else []
    done_nos = {f.split("_")[0] for f in os.listdir(NEWDIR)}
    todo = [t for t in tasks if t["no"] not in done_nos]
    seen = set()
    log(f"收割守护启动: 监控 {DL}, 待匹配 {len(todo)} 篇 (缺 {[t['no'] for t in todo]})")
    while (time.time() - START) < limit_min * 60:
        try:
            for f in sorted(os.listdir(DL)):
                p = os.path.join(DL, f)
                if f in seen or not f.lower().endswith(".pdf"):
                    continue
                if time.time() - os.path.getmtime(p) > 600:  # 只看10分钟内的
                    seen.add(f)
                    continue
                # 等文件写完
                try:
                    if os.path.getsize(p) < 10000:
                        continue
                    time.sleep(2)
                    if os.path.getsize(p) < 10000:
                        continue
                except OSError:
                    continue
                seen.add(f)
                t, hit, note = match_task(p, todo)
                if t and note == "ok":
                    no = t["no"]
                    text = re.sub(r"\s+", " ", pdf_text(p))
                    ym = re.search(r"\b(19[89]\d|20[0-2]\d)\b", re.sub(r"10\.\d{4,9}/\S+", " ", text))
                    year = ym.group(1) if ym else ""
                    # 作者: 标题末4词定位
                    tw = [w.lower() for w in title_words(t["title"])][-4:]
                    author = "Unknown"
                    if tw:
                        pat = r"[\s\S]{0,40}?".join(re.escape(w) for w in tw)
                        mm = re.search(pat, text.lower())
                        if mm:
                            ctx = text[mm.end():mm.end() + 120]
                            names = re.findall(r"[A-Z][A-Za-zÀ-ſ'’\-]+(?:\s+[A-Z][A-Za-zÀ-ſ'’\-]+){0,3}", ctx)
                            if names:
                                author = re.sub(r"[^A-Za-zÀ-ſ'’\-]", "", names[0].split()[-1])
                    slug = "_".join(re.findall(r"[A-Za-z0-9]+", t["title"]))[:75].rstrip("_")
                    name = f"{no}_文献{int(no)+164}_{author}_{year}_{slug}.pdf"
                    shutil.move(p, os.path.join(NEWDIR, name))
                    todo = [x for x in todo if x["no"] != no]
                    log(f"✓ [{no}] {f[:40]} -> {name}")
                else:
                    log(f"? 无法匹配: {f[:50]} (最近命中: {t['no'] if t else '-'} {hit}词, {note})")
        except Exception as e:
            log(f"! 异常 {e}")
        if not todo:
            log("全部匹配完成, 守护退出")
            break
        time.sleep(20)
    log(f"守护结束. 剩余未匹配: {[t['no'] for t in todo]}")


if __name__ == "__main__":
    main()
