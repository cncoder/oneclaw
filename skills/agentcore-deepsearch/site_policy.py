#!/usr/bin/env python3
"""自回归站点抓取清单 —— 哪些站用哪个方法能抓、哪些抓不到，每次实测后自动回写。

核心思想：抓取方法的成败是经验数据，不是凭记忆。每抓一次就记一笔（域名 × 方法 × 成败），
下次抓同域名时直接读历史，优先走"上次成功的方法"，跳过"上次失败的方法"。越用越准。

存储：~/.agentcore-deepsearch/site_policy.json（不进 git，每台机器自己积累）
结构：{ "reddit.com": {"http":{"ok":0,"fail":3}, "browser":{"ok":0,"fail":2}, "cdp":{"ok":5,"fail":0},
                       "best":"cdp", "updated":"<epoch>"} }

种子清单（SEED）：已知结论，开箱即用，之后被实测数据覆盖。
"""

import json
import os
from urllib.parse import urlparse

_STORE = os.path.expanduser("~/.agentcore-deepsearch/site_policy.json")

# 种子：实测/社区已知的封闭源，默认首选方法。实测数据会逐步覆盖它。
# cdp = 本机登录 Chrome;browser = AWS 云端;http = 直连。
SEED = {
    # 封数据中心 IP、需登录态 → 只有本机 CDP 能过（实测 Reddit 验证）
    "reddit.com": "cdp",
    "x.com": "cdp",
    "twitter.com": "cdp",
    "facebook.com": "cdp",
    "instagram.com": "cdp",
    "linkedin.com": "cdp",
    "xiaohongshu.com": "cdp",
    "zhihu.com": "cdp",
    "weibo.com": "cdp",
    # 强 JS / 反爬但不需登录 → 云端浏览器够
    "google.com": "browser",      # 搜索结果页重 JS + 反爬
    "bing.com": "browser",
    # 静态友好 → 直连 HTTP 最省
    "wikipedia.org": "http",
    "github.com": "http",
    "docs.aws.amazon.com": "http",
    "stackoverflow.com": "http",
}


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().split(":")[0]
        # 归一到主域：news.ycombinator.com → ycombinator.com;www.reddit.com → reddit.com
        parts = host.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    except Exception:
        return url


def _load() -> dict:
    try:
        with open(_STORE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict):
    try:
        os.makedirs(os.path.dirname(_STORE), exist_ok=True)
        tmp = _STORE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STORE)
    except Exception:
        pass  # 清单写失败不能拖垮抓取


def preferred_method(url: str) -> str | None:
    """这个域名优先用哪个方法抓。先看实测历史，再看种子，都没有返回 None（走默认混合链）。"""
    dom = _domain(url)
    data = _load()
    rec = data.get(dom)
    if rec and rec.get("best"):
        return rec["best"]
    return SEED.get(dom)


def record(url: str, method: str, ok: bool, clock):
    """回写一次实测结果。clock：传入的时间戳函数返回值（脚本环境禁 Date.now，由调用方提供）。"""
    dom = _domain(url)
    data = _load()
    rec = data.setdefault(dom, {})
    m = rec.setdefault(method, {"ok": 0, "fail": 0})
    m["ok" if ok else "fail"] += 1
    # 重算 best：成功率最高且有过成功的方法
    best, best_score = None, -1.0
    for meth, c in rec.items():
        if not isinstance(c, dict) or "ok" not in c:
            continue
        total = c["ok"] + c["fail"]
        if total == 0 or c["ok"] == 0:
            continue
        score = c["ok"] / total
        if score > best_score:
            best, best_score = meth, score
    if best:
        rec["best"] = best
    rec["updated"] = clock
    _save(data)


def snapshot() -> dict:
    """当前清单全貌（给 browser_status / 调试看）。"""
    return _load()
