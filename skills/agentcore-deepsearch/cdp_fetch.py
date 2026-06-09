#!/usr/bin/env python3
"""CDP 抓取后端：连本机已登录的 Chrome（9222），用真人登录态 + 住宅 IP + 真实指纹抓页面。

专治封闭源（Reddit / X / 小红书 / 需登录的站）—— 这些站封数据中心 IP，
云端浏览器抓不到，但本机登录态的 Chrome 一把过。实测 Reddit blocked:false。

绕系统代理（封闭源校验 IP，走代理会暴露）。失败安静返回，由上层决定回退。
"""

import json
import os
import time
import urllib.request

CDP_BASE = os.environ.get("DEEPSEARCH_CDP_URL", "http://127.0.0.1:9222")
CDP_WAIT = float(os.environ.get("DEEPSEARCH_CDP_WAIT", "6"))  # 给 JS 渲染的时间


def _no_proxy_opener():
    # 封闭源按 IP 校验，必须绕系统代理直连本机 9222
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def cdp_available() -> bool:
    """本机 Chrome 调试端口活着吗。"""
    try:
        op = _no_proxy_opener()
        r = op.open(f"{CDP_BASE}/json/version", timeout=4)
        json.load(r)
        return True
    except Exception:
        return False


def fetch_cdp(url: str, wait: float | None = None) -> tuple[str, str | None]:
    """用本机登录 Chrome 开新 tab 抓 url，返回 (text, error)。抓完关掉该 tab。"""
    try:
        import websocket  # websocket-client
    except Exception as e:
        return ("", f"cdp_import_error: {e} (pip install websocket-client)")

    op = _no_proxy_opener()
    tab_id = None
    try:
        # 新版 Chrome /json/new 要求 PUT
        req = urllib.request.Request(f"{CDP_BASE}/json/new?{url}", method="PUT")
        tab = json.load(op.open(req, timeout=10))
        tab_id = tab["id"]
        ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=35)

        def cmd(i, method, params=None):
            ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == i:
                    return m

        cmd(1, "Page.enable")
        time.sleep(wait if wait is not None else CDP_WAIT)
        # 取整页可见文本（document.body.innerText：已渲染、已过登录态）
        expr = "document.body ? document.body.innerText : ''"
        res = cmd(2, "Runtime.evaluate", {"expression": expr, "returnByValue": True})
        ws.close()
        text = (res.get("result", {}).get("result", {}) or {}).get("value", "") or ""
        if not text.strip():
            return ("", "cdp_empty")
        return (text, None)
    except Exception as e:
        return ("", f"cdp_error: {e}")
    finally:
        # 抓完关 tab，别在 Abel 浏览器里堆垃圾
        if tab_id:
            try:
                op.open(f"{CDP_BASE}/json/close/{tab_id}", timeout=5)
            except Exception:
                pass
