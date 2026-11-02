#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东 Cookie 获取工具（Chrome DevTools 协议）。

用法：python3 get_cookie.py

流程：
  1. 启动一个带调试端口的 Chrome（独立 profile ~/.cache/jd-chrome-profile，
     不影响日常浏览器；Chrome 136+ 禁止默认 profile 开调试端口，所以必须独立）
  2. 在该 Chrome 窗口里用**手机号+短信验证码**登录京东
     （2026 年起京东 PC 网页登录改发 thor，只有移动版登录页
     plogin.m.jd.com 仍会签发脚本所需的 pt_key/pt_pin）
  3. 脚本轮询到 pt_key/pt_pin 后自动写入 jd/config.yaml，并验证登录有效性

注意：短信登录成功后页面可能仍显示"未登录"，属正常现象，
脚本以浏览器 Cookie 仓库为准，会自动继续。

之后每次 Cookie 失效重跑一次本脚本即可。
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import yaml

try:
    import websocket  # websocket-client
except ImportError:
    print("缺少依赖：pip install websocket-client")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.yaml")
CDP_PORT = 9222
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
PROFILE_DIR = os.path.expanduser("~/.cache/jd-chrome-profile")
# 2026 年起京东 PC 网页登录改发 thor；只有移动版登录页仍签发 pt_key/pt_pin
LOGIN_URL = "https://plogin.m.jd.com/login/login?appid=300&returnurl=https%3A%2F%2Fm.jd.com%2F"
JD_COOKIE_URLS = ["https://www.jd.com/", "https://m.jd.com/", "https://api.m.jd.com/"]
WAIT_TIMEOUT = 300  # 最长等待登录 5 分钟
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]


def find_chrome() -> str:
    for name in CHROME_NAMES:
        path = shutil.which(name)
        if path:
            return path
    sys.exit("未找到 Chrome/Chromium，请先安装")


def cdp_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{CDP_BASE}/json/version", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def launch_chrome():
    chrome = find_chrome()
    print(f"[*] 启动 Chrome（独立 profile: {PROFILE_DIR}）...")
    subprocess.Popen(
        [chrome, f"--remote-debugging-port={CDP_PORT}",
         f"--user-data-dir={PROFILE_DIR}",
         "--remote-allow-origins=*",  # 仅作用于本脚本启动的独立 profile 实例
         "--no-first-run", "--no-default-browser-check",
         "--disable-session-crashed-bubble", LOGIN_URL],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if cdp_alive():
            return
        time.sleep(1)
    sys.exit("Chrome 调试端口启动失败；若 9222 被占用请先关闭占用进程")


def list_pages() -> list:
    with urllib.request.urlopen(f"{CDP_BASE}/json", timeout=5) as r:
        return [p for p in json.load(r) if p.get("type") == "page"]


def open_page(url: str) -> str:
    """在浏览器里新开标签页，返回其 page id。"""
    req = urllib.request.Request(f"{CDP_BASE}/json/new?{url}", method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)["id"]
    except Exception:
        pass
    req = urllib.request.Request(f"{CDP_BASE}/json/new?{url}", method="GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)["id"]


def get_jd_cookies() -> dict:
    """通过 CDP 读取京东 Cookie（含 httpOnly），返回 {name: (value, expires)}。

    优先用浏览器级 Storage.getCookies（整个 cookie jar，不受页面分区影响）；
    失败时退回页面级 Network.getCookies。
    """
    try:
        ver = json.load(urllib.request.urlopen(f"{CDP_BASE}/json/version", timeout=5))
        ws = websocket.create_connection(ver["webSocketDebuggerUrl"], timeout=10,
                                         suppress_origin=True)
        try:
            ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
            deadline = time.time() + 10
            while time.time() < deadline:
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    return {c["name"]: (c["value"], c.get("expires", 0))
                            for c in msg["result"]["cookies"]
                            if "jd.com" in c.get("domain", "")}
        finally:
            ws.close()
    except Exception:
        pass
    pages = list_pages()
    page = next((p for p in pages if "jd.com" in (p.get("url") or "")), None)
    if not page:
        page_id = open_page("https://m.jd.com/")
        pages = list_pages()
        page = next(p for p in pages if p["id"] == page_id)
        time.sleep(2)
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=10,
                                     suppress_origin=True)  # Chrome 111+ 拒绝带 Origin 的 WS
    try:
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        ws.send(json.dumps({"id": 2, "method": "Network.getCookies",
                            "params": {"urls": JD_COOKIE_URLS}}))
        deadline = time.time() + 10
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("id") == 2:
                return {c["name"]: (c["value"], c.get("expires", 0))
                        for c in msg["result"]["cookies"]}
        raise TimeoutError("CDP 读取 Cookie 超时")
    finally:
        ws.close()


def wait_for_login() -> tuple:
    """轮询直到拿到 pt_key/pt_pin，返回 (完整 cookie 串, pt_key_expires)。

    写入的是**全量 jd.com Cookie**（不只是 pt_key/pt_pin）：京喜系等接口会
    校验 thor / pt_st / wqmnx1 等辅助会话 Cookie，只带两个值会报「13 未登录」。
    """
    deadline = time.time() + WAIT_TIMEOUT
    print("[*] 请在弹出的 Chrome 窗口里用「手机号+短信验证码」登录京东；")
    print("[i] 登录成功后页面可能仍显示未登录，不用管——脚本以 Cookie 为准，会自动继续")
    while time.time() < deadline:
        try:
            cookies = get_jd_cookies()
        except Exception:
            time.sleep(3)
            continue
        if "pt_key" in cookies and "pt_pin" in cookies:
            expires = cookies["pt_key"][1]
            cookie = ";".join(f"{name}={value}" for name, (value, _) in cookies.items()) + ";"
            return cookie, expires
        time.sleep(3)
    sys.exit("等待登录超时（5 分钟），请重新运行本脚本")


def verify(cookie: str) -> bool:
    """用业务接口（hs 签到查询）验证 Cookie：me-api 对 H5 会话会误报 1001。"""
    import requests
    try:
        resp = requests.post(
            "https://api.m.jd.com/api?functionId=jdh_bm_getKitTask",
            headers={"Cookie": cookie,
                     "User-Agent": "jdapp;iPhone;4.2;12.6.3;;network/wifi;model/iPhone13,2;"
                                   "appBuild/168800;brand/apple;Mozilla/5.0 (iPhone; CPU iPhone "
                                   "OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
                     "Referer": "https://laputa.jd.com/", "Origin": "https://laputa.jd.com",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"functionId": "jdh_bm_getKitTask", "appid": "jdh-middle",
                  "body": '{"m_patch_appKey":"250520900001","groupCode":"openkits","channel":"jdhapp"}'},
            timeout=15, allow_redirects=False)
        data = resp.json()
        return str(data.get("code")) == "0" and isinstance(data.get("result"), dict)
    except Exception:
        return False


def write_config(cookie: str):
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    cookies = cfg.get("cookies") or []
    pin = cookie.split("pt_pin=")[1].rstrip(";")
    cookies = [c for c in cookies if f"pt_pin={pin}" not in str(c)]  # 同账号去重
    cookies.insert(0, cookie)
    cfg["cookies"] = cookies
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def main():
    if not cdp_alive():
        launch_chrome()
    else:
        print(f"[*] 检测到已开启调试端口的 Chrome（:{CDP_PORT}），直接使用")
    cookie, expires = wait_for_login()
    pin = cookie.split("pt_pin=")[1].rstrip(";")
    print(f"[+] 已获取 Cookie：pt_pin={pin[:2]}***{pin[-2:] if len(pin) > 4 else ''}")
    if expires > 0:
        print(f"[i] pt_key 有效期至 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires))}")
    print("[*] 验证 Cookie 有效性…")
    if verify(cookie):
        print("[+] 验证通过，Cookie 可用于签到")
    else:
        print("[!] 验证未通过（可能网络波动），已照常写入，签到时以实际结果为准")
    write_config(cookie)
    print(f"[+] 已写入 {CONFIG_PATH}（其他配置项保持不变）")
    print("[i] 提示：不要在该 Chrome 窗口里点“退出登录”，退出会使 pt_key 立即失效")


if __name__ == "__main__":
    main()
