#!/usr/bin/env python3
"""AI 深度搜索：用 CDP 驱动本机已登录的 Perplexity / Gemini，提问并取回带引用的报告。

为什么用它：Perplexity / Gemini 自己会做"先广后深 + 多源综合 + 带引用"，直接拿成品报告，
比自己拼 web_search + 抓取省事。本机 your-chrome-profile 已登录两者（含 Pro）。

用法：
    python3 ask.py perplexity "你的问题"
    python3 ask.py gemini "你的问题"
    python3 ask.py perplexity "问题" --wait 35    # 复杂问题给更久生成时间

依赖：websocket-client；本机 Chrome 开了 --remote-debugging-port=9222 且已登录目标站。
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request

os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"
CDP = os.environ.get("DEEPSEARCH_CDP_URL", "http://127.0.0.1:9222")
_OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 每个源：提问 URL 模板 + 答案区选择器 + 默认等待秒数
ENGINES = {
    "perplexity": {
        "url": lambda q: "https://www.perplexity.ai/search?q=" + urllib.parse.quote(q),
        "selector": ".prose, [class*=prose]",
        "wait": 25,
    },
    "gemini": {
        # Gemini 不吃 URL query，要在输入框打字提交，单独处理
        "url": lambda q: "https://gemini.google.com/app",
        "selector": "[class*=model-response], message-content, .markdown",
        "wait": 30,
    },
}


def _ws(target):
    import websocket
    return websocket.create_connection(target["webSocketDebuggerUrl"], timeout=90)


def _new_tab(url):
    req = urllib.request.Request(f"{CDP}/json/new?{url}", method="PUT")
    return json.load(_OP.open(req, timeout=10))


def _close(tab_id):
    try:
        _OP.open(f"{CDP}/json/close/{tab_id}", timeout=5)
    except Exception:
        pass


def _eval(ws, i, expr):
    ws.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True,
                                   "awaitPromise": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == i:
            return (m.get("result", {}).get("result", {}) or {}).get("value")


def ask_perplexity(q, wait):
    eng = ENGINES["perplexity"]
    tab = _new_tab(eng["url"](q))
    try:
        ws = _ws(tab)
        ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        time.sleep(wait)
        expr = (
            "(()=>{const e=[...document.querySelectorAll(%r)];"
            "return e.map(x=>x.innerText).join('\\n').slice(0,8000);})()" % eng["selector"]
        )
        ans = _eval(ws, 2, expr) or ""
        ws.close()
        return ans
    finally:
        _close(tab["id"])


def ask_gemini(q, wait, deep=False):
    eng = ENGINES["gemini"]
    tab = _new_tab(eng["url"](q))
    try:
        ws = _ws(tab)
        ws.send(json.dumps({"id": 1, "method": "Page.enable"}))
        time.sleep(6)  # 等输入框加载
        # Deep Research 藏在"上传和工具"菜单里：先展开菜单，再点 Deep Research。
        # aria-label 在"选择"/"取消选择"间切换，已选中(含"取消选择")就不重复点。
        if deep:
            open_menu = (
                "(()=>{const b=[...document.querySelectorAll('button,[role=button]')]"
                ".find(e=>/上传和工具|upload.*tool|^tools$/i.test(e.getAttribute('aria-label')||e.innerText||''));"
                "if(b){b.click();return 'MENU_OPEN';}return 'NO_MENU';})()"
            )
            _eval(ws, 10, open_menu)
            time.sleep(2)
            click_dr = (
                "(()=>{const b=[...document.querySelectorAll('button,[role=button],[role=menuitem],[role=menuitemcheckbox]')]"
                ".find(e=>/deep research|深度研究/i.test((e.innerText||'')+(e.getAttribute('aria-label')||'')));"
                "if(!b) return 'DR_NOT_FOUND';"
                "const a=b.getAttribute('aria-label')||'';"
                "const on=/取消选择|deselect|selected/i.test(a);"
                "if(!on){b.click();return 'DR_CLICKED';}return 'DR_ALREADY_ON';})()"
            )
            _eval(ws, 11, click_dr)
            time.sleep(2)
        # 在 Gemini 输入框打字并回车提交
        qj = json.dumps(q)
        type_expr = (
            "(()=>{const box=document.querySelector('div[contenteditable=true], rich-textarea div[contenteditable]');"
            "if(!box) return 'NO_INPUT';"
            "box.focus();"
            "document.execCommand('insertText', false, %s);"
            "return 'TYPED';})()" % qj
        )
        r = _eval(ws, 2, type_expr)
        if r == "NO_INPUT":
            ws.close()
            return "[gemini] 找不到输入框，可能未登录或页面结构变了"
        time.sleep(1)
        # 回车提交
        for i, key in [(3, "keyDown"), (4, "keyUp")]:
            ws.send(json.dumps({"id": i, "method": "Input.dispatchKeyEvent",
                                "params": {"type": key, "key": "Enter",
                                           "code": "Enter", "windowsVirtualKeyCode": 13}}))
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == i:
                    break
        answer_expr = (
            "(()=>{const e=[...document.querySelectorAll(%r)];"
            "if(!e.length) return '';"
            "return e[e.length-1].innerText.slice(0,8000);})()" % eng["selector"]
        )

        if deep:
            # Deep Research：先出 plan，要点"Start research"确认，再跑几分钟，最后出报告。
            # plan 渲染时间不定，轮询等按钮出现再点（最多等 90s），别固定 sleep 一次就点。
            start_btn = (
                "(()=>{const b=[...document.querySelectorAll('button,[role=button]')]"
                ".find(e=>/start research|开始研究|begin research/i.test((e.innerText||'')+(e.getAttribute('aria-label')||'')));"
                "if(b){b.click();return 'STARTED';}return 'NO_BTN';})()"
            )
            sr = "NO_BTN"
            for _ in range(9):  # 9×10s = 90s
                time.sleep(10)
                sr = _eval(ws, 6, start_btn)
                if sr == "STARTED":
                    break
            # 轮询等报告完成。关键：先确认"研究中"，只有从"研究中"翻到"有报告"才算完。
            # 不能只看长度稳定 —— "Researching websites..." 中间态会暂时不涨，会误判。
            deadline = wait if wait and wait > 180 else 900  # deep 默认给到 15 分钟
            waited, last_len, stable, seen_researching = 0, 0, 0, False
            while waited < deadline:
                time.sleep(20); waited += 20
                st = _eval(ws, 7, "(()=>{const t=document.body?document.body.innerText:'';"
                    "return JSON.stringify({len:t.length,"
                    # 还在研究：出现这些词说明进行中。这是主判据。
                    "researching:/researching|正在研究|研究中|browsing the web|reading|分析中|starting now|i'?ll let you know|feel free to leave/i.test(t),"
                    # 完成强信号：明确的导出/分享报告动作（研究中途不会有）
                    "done:/导出到.*文档|export to|share report|查看来源|添加后续问题|add follow-?up/i.test(t)});})()")
                try:
                    import json as _j; s = _j.loads(st)
                except Exception:
                    s = {}
                sys.stderr.write(f"[deep poll] waited={waited}s len={s.get('len')} "
                                 f"researching={s.get('researching')} done={s.get('done')} "
                                 f"seen={seen_researching} stable={stable}\n")
                sys.stderr.flush()
                if s.get("researching"):
                    seen_researching = True
                # 报告完成的真信号：researching 消失 + 出现导出/来源等完成标志
                if seen_researching and not s.get("researching") and s.get("done"):
                    break
                cur = s.get("len", 0)
                # researching 仍在但内容长时间不涨 = 报告在后台异步生成，当前 tab 不会自刷。
                # 实测：Deep Research 完成后报告在独立视图，轮询当前 tab 抓不到 → 不傻等。
                if abs(cur - last_len) < 50:
                    stable += 1
                else:
                    stable = 0
                last_len = cur
                if stable >= 9:  # 连续 180s 静止：当前 tab 不会再变，停止轮询
                    break
            time.sleep(3)
            # 尝试抓报告（宽选择器）
            ans = _eval(ws, 9, answer_expr) or ""
            if len(ans) < 800:
                ans = _eval(ws, 12,
                    "(()=>{const e=[...document.querySelectorAll('[class*=response],[class*=report],message-content,.markdown')];"
                    "return e.length?e[e.length-1].innerText.slice(0,12000):'';})()") or ans
            # 关键：deep 模式不关 tab —— 报告异步生成，留在 Chrome 里供 Abel/后续查看
            if len(ans) > 800 and not _eval(ws, 13, "/researching|正在研究|starting now/i.test(document.body.innerText)"):
                ws.close()
                return f"[Deep Research 用时约 {waited}s] start={sr}\n\n{ans}"
            ws.close()
            return (f"[Deep Research 已在后台启动(start={sr})，约 {waited}s 后当前页仍在研究中]\n"
                    "研究报告在后台异步生成，当前 tab 不会自动刷新出完整报告。\n"
                    "**报告已留在本机 Chrome 的 Gemini tab 里**——几分钟后去那个 tab 直接看，"
                    "或用 chrome-cdp 重新读那个 tab 抓最终报告。\n"
                    "想要程序化拿结果，建议改用普通 ai-search（不带 --deep）或 agentcore-deepsearch 纵深抓。")

        time.sleep(wait)
        ans = _eval(ws, 5, answer_expr) or ""
        ws.close()
        return ans
    finally:
        _close(tab["id"])


def main():
    if len(sys.argv) < 3:
        print("用法: python3 ask.py {perplexity|gemini} \"问题\" [--wait N]")
        sys.exit(1)
    engine, q = sys.argv[1], sys.argv[2]
    deep = "--deep" in sys.argv  # Gemini Deep Research 深度报告模式
    wait = ENGINES.get(engine, {}).get("wait", 25)
    if deep and "--wait" not in sys.argv:
        wait = 120  # Deep Research 要跑几分钟,默认给足
    if "--wait" in sys.argv:
        wait = int(sys.argv[sys.argv.index("--wait") + 1])
    if engine == "perplexity":
        out = ask_perplexity(q, wait)
    elif engine == "gemini":
        out = ask_gemini(q, wait, deep=deep)
    else:
        print(f"未知源: {engine}（支持 perplexity / gemini）")
        sys.exit(1)
    if not out or len(out) < 50:
        print(f"[{engine}] 没拿到答案（可能未登录/生成超时/页面结构变化）。原始长度: {len(out or '')}")
        sys.exit(2)
    print(out)


if __name__ == "__main__":
    main()
