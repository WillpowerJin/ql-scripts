#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""京东 h5st 5.3 本地签名桥（quickjs + 京东官方 js_security_v3_lite SDK）。

原理与 LazingLuo/LazingLuo_Loon-Rules 的 jd-signin.js（Loon 脚本）一致：
在 JS 沙箱里补一份浏览器环境（navigator/document/localStorage/XHR...），
运行京东官方 SDK，SDK 的 XMLHttpRequest 只被允许访问
https://cactus.jd.com/request_algo（京东官方算法 bootstrap，不携带 Cookie），
初始化后通过 signSync() 本地生成 h5st。

指纹稳定性：SDK 把 fp 等状态写进 localStorage，本模块把 localStorage
持久化到 jd/.sdk_storage.json，保证同一账号跨天是同一“设备”，降低风控概率。

用法：
    from h5st import SignerPool
    pool = SignerPool(storage_path=".sdk_storage.json")
    signer = pool.get(pin, "c1e85", ua, cookie, referer)
    h5st = signer.sign({"appid": ..., "body": sha256, "client": ..., ...})
"""
import hashlib
import json
import os
import pathlib
import time

import quickjs
import requests

BASE_DIR = pathlib.Path(__file__).resolve().parent
VENDOR_JS = BASE_DIR / "vendor" / "js_security_v3_lite_0.1.5.js"
VENDOR_URL = "https://storage.360buyimg.com/webcontainer/js_security_v3_lite_0.1.5.js"
REQUEST_ALGO_URL = "https://cactus.jd.com/request_algo"


def _load_vendor_js() -> str:
    """读取京东官方签名 SDK；本地缺失时从京东 CDN 补齐（如青龙订阅只同步了 py 文件）。"""
    if not VENDOR_JS.exists():
        VENDOR_JS.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(VENDOR_URL, timeout=30)
        resp.raise_for_status()
        text = resp.text
        if not text.startswith("var ParamsSignLite"):
            raise RuntimeError("京东 SDK 下载内容异常")
        VENDOR_JS.write_text(text, encoding="utf-8")
    return VENDOR_JS.read_text(encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _browser_js(ua: str, cookie: str, referer: str, storage: dict) -> str:
    """浏览器环境 shim（对齐 LazingLuo farmInstallBrowser）。"""
    return f"""
// quickjs 不支持 legacy RegExp.$1..$9，补 polyfill（京东 SDK 依赖 test() 后读 RegExp.$1）
(function() {{
  function update(m) {{ for (var i = 1; i <= 9; i++) {{ try {{ RegExp['$' + i] = (m && m[i] !== undefined) ? String(m[i]) : ''; }} catch (e) {{}} }} }}
  var oExec = RegExp.prototype.exec;
  RegExp.prototype.test = function(s) {{ var m = oExec.call(this, String(s)); update(m); return !!m; }};
  RegExp.prototype.exec = function(s) {{ var m = oExec.call(this, String(s)); update(m); return m; }};
  var oMatch = String.prototype.match;
  String.prototype.match = function(re) {{ var m = oMatch.call(this, re); if (m) update(m); return m; }};
}})();
var __ua = {json.dumps(ua)};
var __cookie = {json.dumps(cookie)};
var __ref = {json.dumps(referer)};
var __storage = {json.dumps(storage)};
var localStorage = {{
  getItem: function(k) {{ return Object.prototype.hasOwnProperty.call(__storage, k) ? __storage[k] : null; }},
  setItem: function(k, v) {{ __storage[k] = String(v); __saveStorage(JSON.stringify(__storage)); }},
  removeItem: function(k) {{ delete __storage[k]; __saveStorage(JSON.stringify(__storage)); }}
}};
var atob = function(input) {{
  var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  var s = String(input).replace(/\\s/g, '').replace(/=+$/, '');
  var bits = 0, value = 0, out = '';
  for (var i = 0; i < s.length; i++) {{
    var n = alphabet.indexOf(s[i]);
    if (n < 0) throw new Error('Base64 编码无效');
    value = value << 6 | n; bits += 6;
    if (bits >= 8) {{ bits -= 8; out += String.fromCharCode(value >>> bits & 255); }}
  }}
  return out;
}};
var btoa = function(input) {{
  var alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  var s = String(input), out = '';
  for (var i = 0; i < s.length; i += 3) {{
    var a = s.charCodeAt(i), b = s.charCodeAt(i + 1), c = s.charCodeAt(i + 2);
    if (a > 255 || b > 255 || c > 255) throw new Error('非 Latin1 编码');
    var n = a << 16 | (b || 0) << 8 | (c || 0);
    out += alphabet[n >>> 18 & 63] + alphabet[n >>> 12 & 63] +
           (i + 1 < s.length ? alphabet[n >>> 6 & 63] : '=') +
           (i + 2 < s.length ? alphabet[n & 63] : '=');
  }}
  return out;
}};
var navigator = {{ userAgent: __ua, language: 'zh-CN', languages: ['zh-CN'], platform: 'iPhone', cookieEnabled: true }};
var location = {{ href: __ref, origin: 'https://pro.m.jd.com', hostname: 'pro.m.jd.com', protocol: 'https:' }};
var document = {{
  cookie: __cookie,
  documentElement: {{}},
  createElement: function() {{ return {{ style: {{}}, getContext: function() {{ return null; }} }}; }},
  getElementsByTagName: function() {{ return []; }},
  addEventListener: function() {{}}
}};
var screen = {{ width: 420, height: 912, colorDepth: 24 }};
var innerWidth = 420, innerHeight = 912, devicePixelRatio = 3;
var Element = function Element() {{}};
var crypto = {{ getRandomValues: function(arr) {{ var s = __urandom(arr.length); for (var i = 0; i < arr.length; i++) arr[i] = s.charCodeAt(i); return arr; }} }};
// SDK 的 XHR 仅允许访问京东官方 request_algo，且不携带 Cookie
var XMLHttpRequest = function() {{
  this.readyState = 0; this.status = 0; this.__headers = {{}};
}};
XMLHttpRequest.prototype.open = function(method, url) {{
  if (method !== 'POST' || url !== '{REQUEST_ALGO_URL}') throw new Error('签名服务地址不符');
  this.__url = url; this.readyState = 1;
}};
XMLHttpRequest.prototype.setRequestHeader = function(k, v) {{
  var kk = String(k).toLowerCase();
  if (kk !== 'accept' && kk !== 'content-type') throw new Error('签名服务请求头不符: ' + k);
  this.__headers[kk] = v;
}};
XMLHttpRequest.prototype.getResponseHeader = function(k) {{
  return String(k).toLowerCase() === 'content-type' ? 'application/json' : null;
}};
XMLHttpRequest.prototype.getAllResponseHeaders = function() {{ return 'content-type: application/json\\r\\n'; }};
XMLHttpRequest.prototype.abort = function() {{}};
XMLHttpRequest.prototype.send = function(data) {{
  var r = JSON.parse(__requestAlgo(this.__url, String(data)));
  this.status = r.status; this.responseText = r.body; this.readyState = 4;
  if (this.onreadystatechange) this.onreadystatechange();
}};
var window = globalThis; var self = globalThis;
// 简易定时器事件循环，由 Python 侧 __pumpTimers 驱动
var __timers = [], __timerSeq = 0;
function setTimeout(fn, ms) {{ var id = ++__timerSeq; __timers.push({{ id: id, fn: fn, due: Date.now() + (ms || 0) }}); return id; }}
function clearTimeout(id) {{ __timers = __timers.filter(function(t) {{ return t.id !== id; }}); }}
function __pumpTimers() {{
  for (var i = 0; i < 200; i++) {{
    var now = Date.now(), due = __timers.filter(function(t) {{ return t.due <= now; }});
    if (!due.length) break;
    __timers = __timers.filter(function(t) {{ return t.due > now; }});
    due.forEach(function(t) {{ try {{ t.fn(); }} catch (e) {{}} }});
  }}
}}
"""


class Signer:
    """单个 (账号, appId) 的 h5st 签名器。"""

    def __init__(self, app_id: str, ua: str, cookie: str, referer: str,
                 storage: dict, on_storage_change):
        self.app_id = app_id
        self._on_storage_change = on_storage_change
        self.ctx = quickjs.Context()
        # request_algo 不带 Cookie（与官方 SDK 行为一致）
        self._http = requests.Session()
        self._http.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": ua,
            "Referer": referer.split("?")[0],
        })
        self.ctx.add_callable("__requestAlgo", self._request_algo)
        self.ctx.add_callable("__saveStorage", self._save_storage)
        self.ctx.add_callable("__urandom", lambda n: os.urandom(int(n)).decode("latin-1"))
        self.ctx.eval(_browser_js(ua, cookie, referer, storage))
        self.ctx.eval(_load_vendor_js())
        self.ctx.eval(
            "var __signer = new ParamsSignLite({appId: " + json.dumps(app_id) + ", beta: false, onSign: function() {}});\n"
            "__signer._$rgo = function() { return Promise.resolve(); };"  # 禁用 SDK 定时重复 bootstrap
        )
        self._init()

    # ---- quickjs <-> python 桥 ----
    def _save_storage(self, text: str):
        self._on_storage_change(json.loads(text))

    def _request_algo(self, url: str, body: str) -> str:
        resp = self._http.post(url, data=body.encode("utf-8"), timeout=15)
        return json.dumps({"status": resp.status_code, "body": resp.text})

    def _pump(self, timeout_s: float = 30.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            jobs = self.ctx.execute_pending_job()
            self.ctx.eval("__pumpTimers()")
            if not jobs:
                return
        raise TimeoutError("quickjs 事件循环超时")

    # ---- 生命周期 ----
    def _init(self):
        """干签初始化指纹，再经 request_algo 取服务端 token。"""
        self.ctx.eval(
            "try { __signer.signSync({appid:'init',body:'" + "0" * 64 +
            "',client:'apple',clientVersion:'1.0.0',functionId:'init',t:String(Date.now())}); } catch (e) {}"
        )
        self.ctx.eval(
            "var __initDone = false, __initErr = '';"
            "__signer._$ram().then(function() { __initDone = true; }, "
            "function(e) { __initErr = String(e); __initDone = true; });"
        )
        self._pump()
        if not self.ctx.get("__initDone"):
            raise RuntimeError("签名初始化未完成（request_algo 无响应）")
        err = self.ctx.get("__initErr")
        if err:
            raise RuntimeError(f"签名初始化失败: {err}")
        # 验证服务端 token 已就位（h5st 第 4 段非空）
        probe = self.sign({
            "appid": "init", "body": "0" * 64, "client": "apple",
            "clientVersion": "1.0.0", "functionId": "init", "t": str(int(time.time() * 1000)),
        }, validate=False)
        if len(probe.split(";")) >= 4 and not probe.split(";")[3]:
            raise RuntimeError("request_algo 未返回有效服务端 token")

    def sign(self, sign_input: dict, validate: bool = True) -> str:
        self.ctx.eval("var __out = __signer.signSync(" + json.dumps(sign_input) + ");")
        self._pump()
        h5st = self.ctx.eval("__out && __out.h5st")
        if not isinstance(h5st, str) or not h5st:
            raise RuntimeError("signSync 未返回 h5st")
        if validate:
            parts = h5st.split(";")
            if len(parts) != 10 or parts[2] != self.app_id:
                raise RuntimeError("h5st 输出格式异常")
        return h5st


class SignerPool:
    """按 (pin, appId) 复用签名器，localStorage 持久化到磁盘。"""

    def __init__(self, storage_path: str = None):
        self.storage_path = pathlib.Path(storage_path or BASE_DIR / ".sdk_storage.json")
        self._store = self._load()
        self._signers = {}

    def _load(self) -> dict:
        try:
            return json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self):
        tmp = self.storage_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._store), encoding="utf-8")
        tmp.replace(self.storage_path)

    def get(self, pin: str, app_id: str, ua: str, cookie: str,
            referer: str = "https://pro.m.jd.com/") -> Signer:
        key = f"{pin}|{app_id}"
        if key not in self._signers:
            slot = self._store.setdefault(pin, {}).setdefault(app_id, {})

            def on_change(values, p=pin, a=app_id):
                self._store[p][a] = values
                self._save()

            self._signers[key] = Signer(app_id, ua, cookie, referer, slot, on_change)
        return self._signers[key]


if __name__ == "__main__":
    # 自检测试：初始化一个签名器并检查 h5st 结构（不调用任何业务接口）
    pool = SignerPool()
    ua = ("jdapp;iPhone;4.2;12.6.3;00000000000000000000000000000000;"
          "network/wifi;model/iPhone13,2;appBuild/168800;brand/apple;"
          "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")
    signer = pool.get("selftest_pin", "c1e85", ua, "pt_pin=selftest_pin;pt_key=dummy;")
    h5st = signer.sign({
        "appid": "signed_wh5_ihub", "body": sha256_text('{"activityId":"2775"}'),
        "client": "apple", "clientVersion": "12.6.3",
        "functionId": "bean_deliverySign_home", "t": str(int(time.time() * 1000)),
    })
    parts = h5st.split(";")
    assert len(parts) == 10, f"h5st 段数异常: {len(parts)}"
    print(f"[OK] h5st 生成成功：版本 {parts[5]}，fp {parts[1][:8]}…，token {parts[3][:8]}…")
