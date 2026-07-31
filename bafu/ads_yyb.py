#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八富生活 - 看广告赚金币（YYB 取微信 code 协议版）

cron: 35 6 * * *
new Env('八富看广告');

依赖：requests

环境变量：
  YYB_GO          必填。code 服务地址@openid(ref)，多账号换行
                  例：https://xxxx.example.com@owNAX6mkpZiXq4i9EP_tXp1KnxEk
  BARK_URL / BARK_KEY   通知（与 hifiti / bilibili / fanghua 共用）
  BARK_SERVER / BARK_GROUP  可选
  BFSH_INVITER_CODE     邀请码，默认 U75803F7
  BFSH_FORCE_REBIND=0   不强制改绑邀请人
  BFSH_SESSION          可选，注入会话 JSON 或文件路径
  DRY_RUN=1             只查询不 complete

说明：
  - 登录依赖第三方 YYB GO 的 /wxapp/getCode、/wxapp/getPhoneNumber
  - complete 使用本地 Feistel(token) + needLogin 时附带 wx.login code
  - 首次验证可能需在微信小程序内手动看 1 次广告
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ---------- SSL：默认不校验证书（与源脚本一致，小程序链路常见） ----------
_ORIG_REQUEST = requests.Session.request


def _patched_request(self, *args, **kwargs):
    kwargs.setdefault("verify", False)
    return _ORIG_REQUEST(self, *args, **kwargs)


requests.Session.request = _patched_request


def _mount_retry(session, retries=2):
    retry = urllib3.util.retry.Retry(
        total=retries,
        backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = requests.adapters.HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)


# ---------- 配置 ----------
SCRIPT_DIR = Path(__file__).resolve().parent
APPID = "wxb9be8e4f98c3fbe5"
PORTAL = "https://bafunet.com/portal-server"
WX_REWARD_AD_UNIT_ID = "adunit-43caae09a5474fc9"
UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.30(0x18001e22) "
    "NetType/WIFI Language/zh_CN"
)

AD_WATCH_SECONDS = 30
AD_GAP_MIN = 5
AD_GAP_EXTRA = 3
AD_CHECK_GAP = 2

DEFAULT_BARK_SERVER = "https://api.day.app"
ACCOUNT_ICONS = "🍺🍷🍸🍹🥂🍶🧉☕🍵🥃"
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "True", "yes")
INVITER_CODE = os.environ.get("BFSH_INVITER_CODE", "U75803F7").strip() or "U75803F7"
FORCE_REBIND = os.environ.get("BFSH_FORCE_REBIND", "1").strip() != "0"


def resolve_session_cache_path() -> Path:
    env = (os.environ.get("BAFU_SESSION_CACHE") or "").strip()
    if env:
        return Path(env).expanduser()
    ql = (os.environ.get("QL_DATA_DIR") or "").strip()
    if ql:
        return Path(ql) / "bafu_session_cache.json"
    if Path("/ql/data").is_dir():
        return Path("/ql/data/bafu_session_cache.json")
    return SCRIPT_DIR / "bafu_session_cache.json"


def log(msg: str = "") -> None:
    print(msg, flush=True)


# ---------- adpid ----------
def get_server_adpid() -> int:
    s = WX_REWARD_AD_UNIT_ID
    if s.startswith("adunit-"):
        s = s[len("adunit-") :]
    sub = s[4:12]
    return int(sub, 16)


# ---------- Feistel ----------
MASK32 = (1 << 32) - 1
MASK64 = (1 << 64) - 1
DELTA = 0x9E3779B97F4A7C15


def _rotl32(x, r):
    return ((x << r) | (x >> (32 - r))) & MASK32


def _rotl64(x, r):
    return ((x << r) | (x >> (64 - r))) & MASK64


def _feistel_round(v, k):
    u = (v ^ (k & MASK32)) & MASK32
    u = _rotl32(u, 7)
    u = (0x9E3779B9 * u) & MASK32
    u = (u ^ (u >> 13)) & MASK32
    u = _rotl32(u, 3)
    return u & MASK32


def feistel_encrypt(ad_id, user_id) -> str:
    ad_id = int(ad_id) & MASK64
    user_id = int(user_id) & MASK64
    keys = [user_id]
    cur = user_id
    for g in range(1, 12):
        cur = (_rotl64(cur, 13) ^ (DELTA * g)) & MASK64
        keys.append(cur)
    f = (ad_id >> 32) & MASK32
    a = ad_id & MASK32
    for g in range(12):
        v = (f ^ _feistel_round(a, keys[g])) & MASK32
        f = a
        a = v
    result = ((a << 32) | f) & MASK64
    if result >= (1 << 63):
        result -= 1 << 64
    return str(result)


# ---------- Bark（与 hifiti / fanghua / bilibili 对齐） ----------
def _bark_endpoint() -> Optional[str]:
    url = (os.environ.get("BARK_URL") or os.environ.get("BARK_PUSH") or "").strip()
    key = (os.environ.get("BARK_KEY") or os.environ.get("BARK_DEVICE_KEY") or "").strip()
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    if url:
        return url.rstrip("/")
    if key:
        server = (
            os.environ.get("BARK_SERVER") or DEFAULT_BARK_SERVER
        ).strip().rstrip("/")
        return f"{server}/{key}"
    return None


def send_bark(title: str, body: str) -> None:
    endpoint = _bark_endpoint()
    if not endpoint:
        log("  ℹ️ 未配置 BARK_URL/BARK_KEY，跳过推送")
        return
    if not endpoint.startswith("http"):
        endpoint = f"{DEFAULT_BARK_SERVER.rstrip('/')}/{endpoint}"
    group = (os.environ.get("BARK_GROUP") or "八富看广告").strip() or "八富看广告"
    payload = {
        "title": title[:200],
        "body": body[:3500],
        "group": group,
    }
    sound = (os.environ.get("BARK_SOUND") or "").strip()
    if sound:
        payload["sound"] = sound
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint.rstrip('/')}/"
                f"{quote(title[:100], safe='')}/"
                f"{quote(body[:500], safe='')}"
            )
            r = requests.get(get_url, params={"group": group}, timeout=15)
        ok = r.status_code < 400
        log(f"  📣 Bark {'已推送' if ok else '失败'}（HTTP {r.status_code}）")
        if not ok:
            log(f"  Bark 响应: {(r.text or '')[:200]}")
    except Exception as e:
        log(f"  ⚠️ Bark 推送失败: {e}")


# ---------- YYB GO ----------
def parse_yyb_go_env(line: str | None = None):
    if line is None:
        env = os.environ.get("YYB_GO", "").strip()
    else:
        env = line.strip()
    if not env:
        return None, None
    if "@" in env:
        host_port, ref = env.split("@", 1)
        return host_port.strip(), ref.strip()
    return env, None


def get_yyb_wechat_code(ref, host_port, appid=APPID):
    if not host_port:
        log("  ❌ host_port 为空")
        return None
    if not host_port.startswith("http://") and not host_port.startswith("https://"):
        host_port = "http://" + host_port
    url = f"{host_port.rstrip('/')}/wxapp/getCode"
    try:
        resp = requests.post(
            url, json={"ref": ref, "app_id": appid}, timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            code = (data.get("data") or {}).get("result", {}).get("code")
            if code:
                return code
            log(f"  ⚠️ YYB GO 返回 code 为空: {data}")
        else:
            log(f"  ⚠️ YYB GO 失败: {resp.status_code} - {resp.text[:100]}")
    except Exception as e:
        log(f"  ⚠️ YYB GO 异常: {e}")
    return None


def get_yyb_phone_code(ref, host_port, appid=APPID):
    if not host_port:
        return None
    if not host_port.startswith("http://") and not host_port.startswith("https://"):
        host_port = "http://" + host_port
    url = f"{host_port.rstrip('/')}/wxapp/getPhoneNumber"
    try:
        resp = requests.post(
            url, json={"ref": ref, "app_id": appid}, timeout=15
        )
        if resp.status_code == 200:
            data = resp.json()
            code = (data.get("data") or {}).get("result", {}).get("code")
            if code:
                return code
            log(f"  ⚠️ YYB phone code 为空: {data}")
        else:
            log(f"  ⚠️ YYB phone code HTTP {resp.status_code}")
    except Exception as e:
        log(f"  ⚠️ YYB phone code 异常: {e}")
    return None


def load_accounts():
    accounts = []
    yyb_go_raw = os.environ.get("YYB_GO", "").strip()
    if yyb_go_raw:
        for line in yyb_go_raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            host_port, ref = parse_yyb_go_env(line)
            if ref and host_port:
                accounts.append(
                    {
                        "openid": ref,
                        "display_name": ref[:8] + "...",
                        "source": "yyb_go",
                        "ref": ref,
                        "host_port": host_port,
                    }
                )
                log(f"  📥 YYB_GO 账号: {ref[:8]}...")
            else:
                log(f"  ⚠️ YYB_GO 格式错误: {line}")

    if not accounts:
        env = os.environ.get("BFSH_TOKEN", "").strip()
        if env:
            for line in env.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "#" in line:
                    openid, name = line.split("#", 1)
                else:
                    openid, name = line, line[:6]
                accounts.append(
                    {
                        "openid": openid.strip(),
                        "display_name": name.strip(),
                        "source": "env",
                    }
                )
    return accounts


# ---------- 缓存 ----------
def load_cache():
    path = resolve_session_cache_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        legacy = SCRIPT_DIR / "bfsh_session_cache.json"
        try:
            return json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            return {}


def save_cache(data):
    path = resolve_session_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log(f"  ⚠️ 写缓存失败: {e}")


def ok_resp(data):
    if not isinstance(data, dict):
        return False
    if data.get("_error") or data.get("error"):
        return False
    code = data.get("code")
    return code in (None, 0, 200)


def _need_first_verify(msg):
    return msg and "首次验证" in str(msg)


# ---------- 账号 ----------
class BafuAccount:
    def __init__(self, acc):
        self.openid = acc.get("openid")
        self.display_name = acc.get("display_name") or self.openid or "?"
        self.source = acc.get("source")
        self.ref = acc.get("ref") or self.openid
        self.host_port = acc.get("host_port")
        self.jsessionid = ""
        self.tenant_id = ""
        self.user_id = ""
        self.code = None
        self.err = ""
        self.uc = ""
        self.session = requests.Session()
        _mount_retry(self.session)

    def _build_url(self, path):
        url = PORTAL + path
        if self.jsessionid:
            if "?" in url:
                url = url.replace("?", f";jsessionid={self.jsessionid}?", 1)
            else:
                url += f";jsessionid={self.jsessionid}"
        return url

    def _headers(self):
        h = {
            "User-Agent": UA,
            "xweb_xhr": "1",
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": f"https://servicewechat.com/{APPID}/26/page-frame.html",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if self.tenant_id:
            h["X-Tenant-ID"] = self.tenant_id
        return h

    def _req(self, method, path, params=None, json_body=None):
        url = self._build_url(path)
        try:
            r = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=self._headers(),
                timeout=20,
            )
        except Exception as e:
            return None, {}, str(e)
        sid = r.headers.get("sid") or r.headers.get("Sid")
        if not sid:
            for c in self.session.cookies:
                if "JSESSIONID" in c.name.upper():
                    sid = c.value
                    break
        if sid:
            self.jsessionid = sid
            self.session.cookies.clear()
        uc = r.headers.get("token") or r.headers.get("Token")
        if uc:
            self.uc = uc
        try:
            data = r.json()
        except Exception:
            data = {"_error": f"非JSON:{r.status_code}", "_text": r.text[:200]}
        return data, r.headers, None

    def _get_wechat_code(self):
        if not self.ref or not self.host_port:
            log("  ❌ 缺少 ref / host_port")
            return None
        return get_yyb_wechat_code(self.ref, self.host_port, APPID)

    def _get_phone_code(self):
        if not self.ref or not self.host_port:
            return None
        return get_yyb_phone_code(self.ref, self.host_port, APPID)

    def _open_anon_session(self, code):
        data, _, err = self._req(
            "GET",
            "/platform-user/getOpenidAnon",
            params={"code": code, "gzh": "false"},
        )
        if err or (data or {}).get("_error"):
            self.err = f"getOpenidAnon 失败: {err or (data or {}).get('_error')}"
            return False
        if not self.jsessionid:
            self.err = "getOpenidAnon 未返回 jsessionid"
            return False
        return True

    def _load_tenant(self):
        cfg, _, _ = self._req(
            "GET",
            "/user/getMallConfigAnon",
            params={"code": "1001", "clientType": "mp-weixin"},
        )
        if ok_resp(cfg) and isinstance((cfg or {}).get("data"), dict):
            self.tenant_id = cfg["data"].get("$tenantId", "") or ""
        return True

    def _get_base_info(self):
        data, _, err = self._req("GET", "/user/getBaseInfoAnon")
        if err or (data or {}).get("_error"):
            return None
        if ok_resp(data):
            return data.get("data") or {}
        return None

    def _phone_login(self):
        wxcode = self._get_phone_code()
        if not wxcode:
            log("  ⚠️ 未获取到手机号授权 code")
            return False
        log(f"  📱 手机号 code: {wxcode[:20]}...")
        payload = {
            "wxCode": wxcode,
            "type": "N",
            "parentId": "",
            "clientType": "mp-weixin",
        }
        data, _, err = self._req("POST", "/phoneLogin", json_body=payload)
        if err:
            log(f"  ⚠️ phoneLogin 异常: {err}")
            return False
        if ok_resp(data):
            log("  ✅ phoneLogin 成功")
            return True
        log(f"  ⚠️ phoneLogin 失败: {(data or {}).get('msg') or (data or {}).get('code')}")
        return False

    def _load_injected(self):
        raw = os.environ.get("BFSH_SESSION", "").strip()
        if not raw:
            return False
        try:
            try:
                data = json.loads(raw)
            except Exception:
                with open(raw, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            return False
        entry = data.get(self.openid) if self.openid else None
        if not isinstance(entry, dict) and len(data) == 1:
            entry = list(data.values())[0]
        if isinstance(entry, dict) and entry.get("jsessionid") and entry.get("user_id"):
            self.jsessionid = entry["jsessionid"]
            self.tenant_id = entry.get("tenant_id", "")
            self.user_id = str(entry["user_id"])
            log("  🔑 使用 BFSH_SESSION 注入会话")
            return True
        return False

    def _save(self, cache):
        if not self.openid:
            return
        cache[self.openid] = {
            "jsessionid": self.jsessionid,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
        }
        save_cache(cache)

    def login(self, force=False):
        cache = load_cache()
        if not force and self.openid and self.openid in cache:
            c = cache[self.openid]
            if c.get("jsessionid") and c.get("user_id"):
                self.jsessionid = c["jsessionid"]
                self.tenant_id = c.get("tenant_id", "")
                self.user_id = c["user_id"]
                if self._get_base_info() is not None and self.user_id:
                    return True
                log("  🔄 缓存会话失效，重新登录")

        code = self._get_wechat_code()
        if not code:
            log("  ❌ 无法获取 wx.login code（检查 YYB_GO）")
        else:
            self.code = code
            log(f"  ✅ wx.login code: {code[:10]}...")
            if self._open_anon_session(code):
                self._load_tenant()
                if self._phone_login():
                    info = self._get_base_info()
                    if info and info.get("id"):
                        self.user_id = str(info["id"])
                        self._save(cache)
                        log(f"  ✅ 登录成功 user_id={self.user_id}")
                        return True
                    log("  ⚠️ phoneLogin 后无 user id")
                info = self._get_base_info()
                if info and info.get("id"):
                    self.user_id = str(info["id"])
                    self._save(cache)
                    log(f"  ✅ 匿名会话 user_id={self.user_id}")
                    return True
                log("  ⚠️ 未获取到 user_id")

        if self._load_injected():
            return True
        if self.openid and self.openid in cache:
            c = cache[self.openid]
            if c.get("user_id"):
                self.user_id = c["user_id"]
                return True

        self.err = "无法获得用户 id：请检查 YYB_GO"
        log(f"  ❌ {self.err}")
        return False

    def refresh_session(self):
        return self.login(force=True)

    def check_limit(self, adpid):
        data, _, err = self._req("GET", "/ad/checkLimit", params={"adpid": adpid})
        if err or (data or {}).get("_error"):
            return None
        d = (data or {}).get("data") or {}
        return {
            "count": int(d.get("count", 0) or 0),
            "limited": bool(d.get("limited", False)),
            "totalAds": int(d.get("totalAds", 10) or 10),
            "adProfit": d.get("adProfit", 0),
            "needLogin": bool(d.get("needLogin", False)),
            "id": d.get("id"),
            "msg": (data or {}).get("msg") or (data or {}).get("message") or "",
            "code": (data or {}).get("code"),
        }

    def complete(self, adpid, ad_task_id, need_login):
        if not self.user_id:
            log("  ❌ 缺少 user_id")
            return False, "缺少 user_id"
        token = feistel_encrypt(ad_task_id, self.user_id)
        path = f"/ad/complete?token={token}&adpid={adpid}"
        if need_login and self.code:
            path += f"&code={self.code}"
        data, _, err = self._req("POST", path, json_body={})
        if err:
            return False, err
        if ok_resp(data):
            return True, (data or {}).get("msg") or "ok"
        return False, (
            (data or {}).get("msg")
            or (data or {}).get("message")
            or str(data)[:80]
        )

    def _get_inviter(self):
        data, _, err = self._req("GET", "/user/getInviter")
        if err or (data or {}).get("_error"):
            return "error", err or (data or {}).get("_error")
        code = (data or {}).get("code")
        if code == 200 and (data or {}).get("data"):
            return "bound", data["data"]
        if code in (401, "401"):
            return "unauth", None
        return "unbound", None

    def _set_inviter(self, code=INVITER_CODE):
        data, _, err = self._req("POST", "/user/setInviter", params={"code": code})
        if err or (data or {}).get("_error"):
            return False, err or (data or {}).get("_error")
        if (data or {}).get("code") == 200:
            return True, (data or {}).get("msg") or "ok"
        return False, (data or {}).get("msg") or str((data or {}).get("code"))

    def ensure_inviter(self):
        kind, payload = self._get_inviter()
        if kind == "unauth":
            self.login(force=True)
            kind, payload = self._get_inviter()
        if kind == "error":
            log(f"  ⚠️ 查询邀请人失败: {payload}")
            return "查询失败"
        already = payload if kind == "bound" else None
        if already and not FORCE_REBIND:
            name = already.get("nickname") or already.get("phone") or "?"
            log(f"  🤝 已绑定: {name}")
            return f"已绑定:{name}"
        if already:
            name = already.get("nickname") or already.get("phone") or "?"
            log(f"  🤝 已有邀请人: {name}（将尝试改绑）")
        else:
            log("  🔗 未绑定邀请人")
        if DRY_RUN:
            return "待绑定(查)"
        ok, msg = self._set_inviter()
        if ok:
            k2, d2 = self._get_inviter()
            if k2 == "bound":
                nm = d2.get("nickname") or d2.get("phone") or "?"
                log(f"  ✅ 已绑定邀请人: {nm}")
                return f"已绑定:{nm}"
            return "绑定存疑"
        if "hasCycleInvite" in str(msg):
            log(f"  ℹ️ 本账号即邀请码持有者（{INVITER_CODE}），跳过")
            return "本人邀请码"
        if "errorReq" in str(msg):
            return "不可改绑"
        log(f"  ⚠️ 绑定邀请人失败: {msg}")
        return f"绑定失败:{msg}"

    def run(self):
        result: dict[str, Any] = {"name": self.display_name, "watched": 0}
        if not self.login():
            log(f"  ❌ 登录失败: {self.err or '登录失败'}")
            result["errors"] = [self.err or "登录失败"]
            return result

        result["inviter"] = self.ensure_inviter()
        adpid = get_server_adpid()
        log(
            f"  🔑 就绪 | user_id={self.user_id} | adpid={adpid}"
            + (f" | tenant={self.tenant_id}" if self.tenant_id else "")
        )

        watched = 0
        while True:
            info = self.check_limit(adpid)
            if info is None:
                result.setdefault("errors", []).append("查询广告上限失败")
                break
            if _need_first_verify(info.get("msg")):
                log(f"  ⚠️ 需首次验证: {info.get('msg')}")
                log("  💡 请在微信小程序「八富生活」内手动看 1 次广告")
                result["skipped"] = "需完成首次验证"
                break

            count = info["count"]
            total = info["totalAds"]
            log(
                f"  📺 进度 {count}/{total} | limited={info['limited']} "
                f"| needLogin={info['needLogin']} | adId={info['id']}"
            )
            if info["limited"] or count >= total:
                log("  ✅ 今日广告已达上限")
                break

            if DRY_RUN:
                remaining = max(0, total - count)
                log(f"  🔍 DRY_RUN: 将观看 {remaining} 个（不实际 complete）")
                result["watched"] = remaining
                result["dry_run"] = True
                break

            if info["needLogin"]:
                fresh = self._get_wechat_code()
                if fresh:
                    self.code = fresh
                    log("  🔑 刷新 wx.login code")
                elif not self.refresh_session():
                    result.setdefault("errors", []).append(
                        "needLogin 且无法获取 code"
                    )
                    break

            time.sleep(random.uniform(AD_CHECK_GAP, AD_CHECK_GAP + 1))
            info2 = self.check_limit(adpid)
            if info2 is None:
                result.setdefault("errors", []).append("第二次 checkLimit 失败")
                break
            ad_task_id = info2["id"]
            log(f"  📺 观看广告 adTaskId={ad_task_id}...")
            watch_time = AD_WATCH_SECONDS + random.uniform(1, 5)
            log(f"  ⏳ 等待 {watch_time:.0f}s...")
            time.sleep(watch_time)

            ok, msg = self.complete(adpid, ad_task_id, info2["needLogin"])
            if ok:
                watched += 1
                log(f"  ✅ 完成第 {watched} 个: {msg}")
            elif _need_first_verify(msg):
                log(f"  ⚠️ 首次验证: {msg}")
                result["skipped"] = "需完成首次验证"
                break
            elif "时间不足" in str(msg) or "不足" in str(msg):
                log(f"  ⚠️ {msg}")
                result.setdefault("errors", []).append(f"时间不足:{msg}")
                time.sleep(random.uniform(AD_GAP_MIN, AD_GAP_MIN + AD_GAP_EXTRA))
                continue
            else:
                log(f"  ⚠️ 完成失败: {msg}")
                result.setdefault("errors", []).append(f"完成失败:{msg}")
                time.sleep(random.uniform(AD_GAP_MIN, AD_GAP_MIN + AD_GAP_EXTRA))
                continue

            gap = random.uniform(AD_GAP_MIN, AD_GAP_MIN + AD_GAP_EXTRA)
            log(f"  💤 间隔 {gap:.1f}s")
            time.sleep(gap)

        result["watched"] = watched
        return result


def push_summary(results):
    if not results:
        return
    lines = ["📣 八富看广告 汇总", "─" * 28]
    for i, r in enumerate(results):
        icon = ACCOUNT_ICONS[i % len(ACCOUNT_ICONS)]
        name = r.get("name", "?")
        line = f"{icon} {name}"
        if r.get("skipped"):
            line += f"  ⏭️ {r['skipped']}"
        elif r.get("errors"):
            line += "  ⚠️ " + "; ".join(r["errors"])
        else:
            watched = r.get("watched", 0)
            if r.get("dry_run"):
                line += f"  🔍 将看{watched}个"
            else:
                line += f"  观看{watched}个✓"
        inv = r.get("inviter")
        if inv:
            line += f"  | 邀请:{inv}"
        lines.append(line)
        lines.append("─" * 28)
    text = "\n".join(lines)
    log("")
    log(text)
    send_bark("八富看广告", text)


def main() -> int:
    log("🚀 八富看广告 ads_yyb")
    log(f"📁 会话缓存: {resolve_session_cache_path()}")
    if _bark_endpoint():
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY")
    if DRY_RUN:
        log("🔍 DRY_RUN：只查询不 complete")
    adpid = get_server_adpid()
    log(f"🎯 adpid={adpid}")

    accounts = load_accounts()
    if not accounts:
        log("❌ 未配置账号：请设置 YYB_GO")
        log("   格式: YYB_GO=https://code服务地址@openid")
        log("   多账号换行")
        send_bark("八富看广告 · 失败", "未配置 YYB_GO")
        return 1

    log(f"📋 {len(accounts)} 个账号（来源：{accounts[0]['source']}）")
    results = []
    for idx, acc in enumerate(accounts, 1):
        log(f"▶ [{idx}/{len(accounts)}] {acc.get('display_name')}")
        a = BafuAccount(acc)
        try:
            r = a.run()
        except Exception as e:
            r = {"name": a.display_name, "errors": [f"异常: {e}"]}
            log(f"  ❌ 异常: {e}")
        results.append(r)

    push_summary(results)
    log("🏁 全部完成")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n⚠️ 用户中断")
        sys.exit(130)
