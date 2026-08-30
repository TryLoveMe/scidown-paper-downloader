#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scidown_lib.py — open-access.shop / Scidown 文献下载生态核心库
=================================================================

逆向还原的完整链路(2026-08 实测):

    open-access.shop (搜索页, 支持 DOI/标题/作者)
      └─ "Download" 弹窗 → Choose download method
           ├─ Scidown cloud drive  → scidown.cn/lx.php?lx=http://92.223.124.29/<关键词>.opjc
           │     └─ 中转确认页 (勾协议, 置 download_agreed cookie) → lxapp.php
           │           └─ 302/JS 跳 scixue.php?doi=<DOI>   (真实解析在这里)
           │                 ├─ 未登录: 「取回本地」表单 action=/wangpan/login.php, a=""  ← 死路
           │                 └─ 已登录: 服务器按文献选择存储后端, a=<最终直链>:
           │                      ├─ 缓存命中: http://zy9.xeak.top/pdf/<DOI>.pdf      (Cloudflare 挡脚本)
           │                      │            https://sci.bban.top/pdf/<DOI>.pdf?download=true (公开 CDN, 脚本可下 ★)
           │                      ├─ 机构代理: http://zdwe.sciokk.cn/https/<webvpn-hex>/content/pdf/<DOI>.pdf?auth_key=<时间戳签名>
           │                      │            (无 CF, curl 可直下 ★; auth_key 有效期约1小时, 每次解析重新生成)
           │                      └─ 蓝奏云:   https://gosci.lanzouq.com/<id>  (需浏览器二次点击「普通下载」)
           └─ Lool/Bitta 等其余选项基本是死链(pan.epicgames.com 连不上, beatport 是真站被 CF 拦)

    ⚠ zy9 与 bban 的地址模式是固定的, 可不经过 scidown 直接构造!
    ⚠ IP 请求过频会被 DingXiang 顶象防护拦截(verify.php 滑块), 且会"降级"返回空解析。
    ⚠ scidown 登录会话很短(约30分钟), cookie 含明文账号(dlus/dlps, 勾了记住密码时)。

仅供个人学习科研使用, 请遵守目标网站服务条款与版权法规。
"""

import hashlib
import json
import os
import re
import subprocess
import time
import unicodedata
from urllib.parse import quote

import requests

try:
    requests.packages.urllib3.disable_warnings()
except Exception:
    pass

# ---------------------------------------------------------------- 常量

UA_CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
# down.sciokk.cn 对 UA 做白名单, 必须带 360 浏览器标记
UA_360 = UA_CHROME + " QIHU 360SE"

SCIDOWN = "https://www.scidown.cn"
SRC_OPJC = "http://92.223.124.29/{key}.opjc"          # open-access.shop 的提货凭证地址
BBAN = "https://sci.bban.top/pdf/{doi}.pdf?download=true"   # 分流线路2 (公开)
ZY9 = "http://zy9.xeak.top/pdf/{doi}.pdf"              # 主线路1 (CF 挡脚本, 浏览器可过)
GATEWAY = "zdwe.sciokk.cn"                             # WebVPN 网关 host (登录解析后出现)

TIMEOUT = 60
PDF_MAGIC = b"%PDF"
# 顶象防护页特征
GATE_MARKS = ("btn-popup", "安全防护系统", "myCaptcha", "verify.php")

_SUBS = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
         "₆": "6", "₇": "7", "₈": "8", "₉": "9", "⁴": "4", "‑": "-", "–": "-"}


# ---------------------------------------------------------------- 文本工具

def _nfkc(s):
    s = unicodedata.normalize("NFKC", s)
    for k, v in _SUBS.items():
        s = s.replace(k, v)
    return s


def norm_text(s):
    return re.sub(r"[^a-z0-9]+", "", _nfkc(s).lower())


def title_words(title):
    return [w.lower() for w in re.findall(r"[A-Za-z0-9]+", _nfkc(title)) if len(w) >= 3][:8]


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


# ---------------------------------------------------------------- PDF 校验/核对

def is_pdf_bytes(b):
    return b is not None and len(b) > 10000 and b[:1024].find(PDF_MAGIC) != -1


def pdf_text(path, pages=2):
    """pdftotext 提取前 N 页文本(需系统安装 poppler)。无 poppler 时返回空串。"""
    try:
        r = subprocess.run(["pdftotext", "-l", str(pages), path, "-"],
                           capture_output=True, timeout=60)
        return r.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def verify_title(path_or_text, expected_title, as_text=False):
    """题名核对: 标题前8个有效词至少60%出现在 PDF 前两页。返回 (ok, 详情)"""
    text = path_or_text if as_text else pdf_text(path_or_text)
    if not text or len(text) < 50:
        return False, "pdftotext 无输出(未安装 poppler?)"
    np_ = norm_text(text)
    words = title_words(expected_title)
    if not words:
        return False, "标题无有效词"
    hit = sum(1 for w in words if w in np_)
    return hit >= max(3, int(len(words) * 0.6)), f"命中 {hit}/{len(words)} 词"


def extract_author_year(text, title):
    """从页面文本提取 (第一作者姓氏, 年份)。启发式: 标题末4词定位→后随作者行。"""
    ws = re.sub(r"\s+", " ", text)
    year = ""
    m = re.search(r"\b(19[89]\d|20[0-2]\d)\b", re.sub(r"10\.\d{4,9}/\S+", " ", ws))
    if m:
        year = m.group(1)
    author = "Unknown"
    tw = [w.lower() for w in title_words(title)][-4:]
    if tw:
        pat = r"[\s\S]{0,40}?".join(re.escape(w) for w in tw)
        mm = re.search(pat, ws.lower())
        if mm:
            ctx = ws[mm.end():mm.end() + 120]
            names = re.findall(r"[A-Z][A-Za-zÀ-ſ'’\-]+(?:\s+[A-Z][A-Za-zÀ-ſ'’\-]+){0,3}", ctx)
            if names:
                author = re.sub(r"[^A-Za-zÀ-ſ'’\-]", "", names[0].split()[-1])
    return author, year


def make_filename(no, title, pdf_text_str):
    """按 编号_作者_年份_标题.pdf 规范命名"""
    author, year = extract_author_year(pdf_text_str, title)
    slug = "_".join(re.findall(r"[A-Za-z0-9]+", _nfkc(title)))[:75].rstrip("_")
    return f"{no}_{safe_name(author)}_{year}_{safe_name(slug)}.pdf"


# ---------------------------------------------------------------- 会话

class ScidownSession:
    """scidown 登录会话管理(cookie 持久化, 登录, 解析)"""

    def __init__(self, cookie_file=None):
        self.cookie_file = cookie_file
        self.s = requests.Session()
        self.s.verify = False
        self.s.headers.update({"User-Agent": UA_CHROME})
        if cookie_file and os.path.exists(cookie_file):
            self.load_cookies(cookie_file)

    # ---- cookie 持久化(简单行式: 每行 name=value) ----
    def load_cookies(self, path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            for kv in line.split(";"):
                if "=" in kv:
                    k, v = kv.strip().split("=", 1)
                    self.s.cookies.set(k, v, domain="www.scidown.cn")

    def save_cookies(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("; ".join(f"{c.name}={c.value}" for c in self.s.cookies))

    # ---- 登录相关 ----
    def login_page(self):
        return self.s.get(f"{SCIDOWN}/wangpan/login.php", timeout=TIMEOUT)

    def get_login_captcha_b64(self):
        """登录图形验证码(wangpan/999.jpg)。返回 base64 PNG(供有视觉能力的 AI/人识别)"""
        r = self.s.get(f"{SCIDOWN}/wangpan/999.jpg", timeout=TIMEOUT)
        import base64
        return base64.b64encode(r.content).decode()

    def login(self, username, password, captcha_code, remember=True):
        """POST 登录。成功返回 True 并刷新 cookie。"""
        r = self.s.post(
            f"{SCIDOWN}/wangpan/login.php",
            data={"username": username, "pwd": password,
                  "vercode": captcha_code, **({"remember": "1"} if remember else {})},
            timeout=TIMEOUT,
            headers={"Referer": f"{SCIDOWN}/wangpan/login.php"})
        ok = self.is_logged_in()
        if ok and self.cookie_file:
            self.save_cookies(self.cookie_file)
        return ok, f"HTTP {r.status_code}"

    def is_logged_in(self):
        try:
            r = self.s.get(f"{SCIDOWN}/wangpan/index.php", timeout=TIMEOUT, allow_redirects=False)
            return r.status_code == 200 and ("login.php" not in r.headers.get("Location", ""))
        except requests.RequestException:
            return False

    # ---- 解析链 ----
    def resolve(self, key, referer_pause=2.5):
        """
        登录态解析。key 可以是 DOI 或标题(与 open-access.shop 的 .opjc 关键词一致)。
        返回 dict: {ok, url(最终直链|None), backend(zdwe/zy9/lanzou/bban/空), gated(是否触发防护), note}
        """
        furl = SRC_OPJC.format(key=key)
        r1 = self.s.get(f"{SCIDOWN}/lx.php?lx=" + quote(furl, safe=""), timeout=TIMEOUT)
        if any(mk in r1.text for mk in GATE_MARKS):
            return {"ok": False, "url": None, "backend": None, "gated": True, "note": "触发顶象防护"}
        time.sleep(referer_pause)
        r3 = self.s.get(f"{SCIDOWN}/scixue.php?doi={key}", timeout=TIMEOUT,
                        headers={"Referer": f"{SCIDOWN}/lx.php"})
        if any(mk in r3.text for mk in GATE_MARKS):
            return {"ok": False, "url": None, "backend": None, "gated": True, "note": "触发顶象防护"}
        if "请求信息有误" in r3.text:
            return {"ok": False, "url": None, "backend": None, "gated": False,
                    "note": "scixue 拒绝(lx.php 会话未建立或 IP 被降级)"}
        m = re.search(r'name="a"[^>]*value="([^"]+)"', r3.text)
        url = m.group(1) if m else ""
        if not url:
            return {"ok": False, "url": None, "backend": "空", "gated": False,
                    "note": "解析为空(IP 被降级/未收录)"}
        backend = ("zdwe" if "zdwe.sciokk.cn" in url
                   else "lanzou" if "lanzou" in url
                   else "zy9" if "zy9.xeak.top" in url
                   else "other")
        return {"ok": True, "url": url, "backend": backend, "gated": False, "note": "ok"}


# ---------------------------------------------------------------- 下载器

def fetch_pdf(url, referer=None, ua=UA_CHROME, engine="auto", timeout=TIMEOUT):
    """
    带校验地下载 PDF。返回 (bytes|None, status)。
    engine: auto(requests) | curl(requests 被 CF 拒时 curl 的 TLS 指纹可能通过)
    """
    headers = {"User-Agent": ua}
    if referer:
        headers["Referer"] = referer
    if engine in ("auto", "requests"):
        try:
            r = requests.get(url, headers=headers, timeout=timeout, verify=False)
            if r.status_code == 200 and is_pdf_bytes(r.content):
                return r.content, 200
            if engine == "requests":
                return None, r.status_code
        except requests.RequestException as e:
            if engine == "requests":
                return None, str(e)
    # curl 兜底(不同 TLS 指纹)
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", ua]
    if referer:
        cmd += ["-e", referer]
    cmd += [url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 30)
        if r.returncode == 0 and is_pdf_bytes(r.stdout):
            return r.stdout, 200
        return None, f"curl rc={r.returncode} len={len(r.stdout)}"
    except subprocess.TimeoutExpired:
        return None, "curl timeout"


def download_cached(doi, referer=None):
    """路径1: 缓存直链(bban 公开 CDN)。requests 失败自动换 curl 引擎。返回 (bytes|None, url, status)"""
    url = BBAN.format(doi=doi)
    b, st = fetch_pdf(url, referer=referer, engine="requests")
    if not b:
        b, st = fetch_pdf(url, referer=referer, engine="curl")
    return (b, url, st) if b else (None, url, st)


def download_gateway(url, referer="http://down.sciokk.cn/sci/down1.php"):
    """路径3: 登录解析出的网关直链(zdwe 签名地址)。curl 引擎优先。"""
    return fetch_pdf(url, referer=referer, ua=UA_CHROME, engine="auto", timeout=120)


# ---------------------------------------------------------------- DOI 工具

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def valid_doi(s):
    return bool(DOI_RE.match(s.strip()))


def parse_doi_list(text):
    """从文本提取 DOI(每行一个或混排)。返回保序去重列表"""
    out, seen = [], set()
    for m in re.finditer(r"10\.\d{4,9}/[^\s|,，;；\"']+", text):
        d = m.group(0).rstrip(".")
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out
