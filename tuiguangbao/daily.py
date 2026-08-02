#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
推广宝 每日看广告领奖

cron: 0 9 * * *
new Env('推广宝每日广告');

策略：
  1. 账号密码登录 Discuz（拿 _auth Cookie）
  2. 可选绑定邀请码
  3. 循环：查进度 → 冷却 → next_ad → 模拟观看 → complete_ad → 满额 claim
  4. 结果可推送 Bark / Server酱 / Webhook

青龙环境变量（账号）：
  TGB_ACCOUNTS  推荐。JSON 数组
    [{"name":"主号","phone":"138...","password":"..."}]
  或兼容原 JS：
    TGB = 手机号#密码，多账号用 & 或换行
  或平行变量（& 分隔）：
    TGB_USER / TGB_PASS / TGB_NAME

青龙环境变量（Bark，与仓库其它脚本共用）：
  BARK_URL / BARK_KEY / BARK_SERVER / BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

可选：
  TGB_INVITE_CODE / TGB_TIMEOUT / TGB_MAX_RETRIES / TGB_RETRY_INTERVAL
  TGB_AD_WATCH_SECONDS / TGB_INTER_ACCOUNT_DELAY / TGB_UA
  TGB_SESSION_CACHE / SERVERCHAN_KEY / WEBHOOK_URL
  DRY_RUN=1  只登录+查进度，不看广告不领奖

依赖：requests
  青龙：依赖管理添加 requests
  本地 yaml：再装 PyYAML

注册/邀请：https://tg.suewammes.com/plugin.php?id=xigua_hh&ac=invite&idu=23253622
逻辑来源：推广宝每日 2.5 修复版（Discuz 插件 view/sign）
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 16; V2426A Build/BP2A.250605.031.A3_V000L1; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/134.0.6998.135 "
    "Mobile Safari/537.36 TuiGuangBaoAndroid/1.0.2"
)
DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_INVITE_CODE = "000GHFAV"
SCRIPT_DIR = Path(__file__).resolve().parent

HOST = "https://tg.suewammes.com"
BASE_PLUGIN = f"{HOST}/plugin.php?id=view&modac=sign"
LOGIN_URL = f"{HOST}/member.php?mod=logging&action=login&loginsubmit=yes&mobile=2"
LOGIN_PAGE_URL = f"{HOST}/member.php?mod=logging&action=login&mobile=2"
BIND_YQ_URL = f"{HOST}/plugin.php?id=xigua_hh:bindcode"
REFERER_INVITE = f"{HOST}/plugin.php?id=xigua_hh&ac=invite"

logger = logging.getLogger("tuiguangbao")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    phone: str = ""
    password: str = ""
    cookie: str = ""  # 可选：直接注入会话，免登

    def has_password(self) -> bool:
        return bool(self.phone.strip() and self.password)

    def has_cookie(self) -> bool:
        return bool(self.cookie.strip())

    def cache_key(self) -> str:
        if self.phone:
            return f"phone:{self.phone.strip()}"
        return f"name:{self.name}"

    def auth_label(self) -> str:
        parts = []
        if self.has_cookie():
            parts.append("cookie")
        if self.has_password():
            parts.append("password")
        return "+".join(parts) if parts else "none"

    def normalize(self) -> None:
        self.phone = self.phone.strip()
        self.cookie = self.cookie.strip()
        if self.cookie.lower().startswith("cookie:"):
            self.cookie = self.cookie.split(":", 1)[1].strip()
        if not self.name:
            self.name = self.phone or "account"


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "推广宝"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""
    serverchan_key: str = ""
    webhook_url: str = ""

    def enabled(self) -> bool:
        return bool(
            self.bark_url
            or self.bark_key
            or self.serverchan_key
            or self.webhook_url
        )


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    invite_code: str = DEFAULT_INVITE_CODE
    timeout: int = 15
    max_retries: int = 3
    retry_interval: int = 10
    ad_watch_seconds: int = 22
    inter_account_delay: int = 6
    inter_ad_delay_min: float = 3.0
    inter_ad_delay_max: float = 6.0
    max_ad_loops: int = 50
    user_agent: str = DEFAULT_UA
    dry_run: bool = False
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "on", "y")


def _split_multi(value: str) -> list[str]:
    """青龙多账号：& 或换行。"""
    if not value:
        return []
    return [x.strip() for x in re.split(r"[&\n]", value) if x.strip()]


def resolve_session_cache_path() -> Path:
    env = _env("TGB_SESSION_CACHE")
    if env:
        return Path(env).expanduser()
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "tuiguangbao_session_cache.json"
    return SCRIPT_DIR / "session_cache.json"


def load_session_cache() -> dict[str, Any]:
    path = resolve_session_cache_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_session_cache(cache: dict[str, Any]) -> None:
    path = resolve_session_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("💾 会话缓存写入失败: %s", e)


def cache_get_cookie(cache: dict[str, Any], account: Account) -> str:
    with cache_lock:
        entry = cache.get(account.cache_key()) or {}
        if isinstance(entry, dict):
            return str(entry.get("cookie") or "")
        return ""


def cache_set_cookie(cache: dict[str, Any], account: Account, cookie: str) -> None:
    with cache_lock:
        cache[account.cache_key()] = {
            "cookie": cookie,
            "name": account.name,
            "phone": account.phone,
            "ts": int(time.time()),
        }
        save_session_cache(cache)


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("TGB_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"TGB_ACCOUNTS[{i}] 必须是对象")
        phone = str(item.get("phone") or item.get("username") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        cookie = str(item.get("cookie") or "")
        name = str(item.get("name") or phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, cookie=cookie)
        acc.normalize()
        if not acc.has_password() and not acc.has_cookie():
            raise ValueError(f"TGB_ACCOUNTS[{i}] 缺少手机号密码或 cookie")
        accounts.append(acc)
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    accounts: list[Account] = []

    # 1) JSON
    accounts_json = _env("TGB_ACCOUNTS")
    if accounts_json:
        return _parse_accounts_json(accounts_json)

    # 2) 原 JS：TGB=手机号#密码
    tgb = _env("TGB")
    if tgb:
        for i, line in enumerate(_split_multi(tgb)):
            parts = line.split("#", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1]:
                raise ValueError(f"TGB 第 {i + 1} 段格式错误，应为 手机号#密码")
            phone, pwd = parts[0].strip(), parts[1]
            acc = Account(name=phone, phone=phone, password=pwd)
            acc.normalize()
            accounts.append(acc)
        return accounts

    # 3) 平行变量
    users = _split_multi(_env("TGB_USER") or _env("TGB_USERNAME") or _env("TGB_PHONE"))
    passes = _split_multi(_env("TGB_PASS") or _env("TGB_PASSWORD"))
    names = _split_multi(_env("TGB_NAME"))
    cookies = _split_multi(_env("TGB_COOKIE"))
    n = max(len(users), len(passes), len(cookies))
    if n <= 0:
        return accounts
    for i in range(n):
        phone = users[i] if i < len(users) else ""
        pwd = passes[i] if i < len(passes) else ""
        cookie = cookies[i] if i < len(cookies) else ""
        name = names[i] if i < len(names) else (phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, cookie=cookie)
        acc.normalize()
        if not acc.has_password() and not acc.has_cookie():
            raise ValueError(f"第 {i + 1} 个账号缺少密码或 cookie")
        accounts.append(acc)
    return accounts


def load_notify_from_env() -> NotifyConfig:
    bark_url = _env("BARK_URL") or _env("BARK_PUSH")
    bark_key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""

    return NotifyConfig(
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=_env("BARK_GROUP", "推广宝"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env("SERVERCHAN_KEY") or _env("PUSH_KEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _parse_accounts_from_env()
    if not accounts:
        return None
    return AppConfig(
        accounts=accounts,
        invite_code=_env("TGB_INVITE_CODE", DEFAULT_INVITE_CODE),
        timeout=int(_env("TGB_TIMEOUT", "15")),
        max_retries=int(_env("TGB_MAX_RETRIES", "3")),
        retry_interval=int(_env("TGB_RETRY_INTERVAL", "10")),
        ad_watch_seconds=int(_env("TGB_AD_WATCH_SECONDS", "22")),
        inter_account_delay=int(_env("TGB_INTER_ACCOUNT_DELAY", "6")),
        inter_ad_delay_min=float(_env("TGB_INTER_AD_DELAY_MIN", "3")),
        inter_ad_delay_max=float(_env("TGB_INTER_AD_DELAY_MAX", "6")),
        max_ad_loops=int(_env("TGB_MAX_AD_LOOPS", "50")),
        user_agent=_env("TGB_UA", DEFAULT_UA),
        dry_run=_env_bool("DRY_RUN", False),
        notify=load_notify_from_env(),
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 配置需要 PyYAML：pip install PyYAML") from e

    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        phone = str(item.get("phone") or item.get("username") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        cookie = str(item.get("cookie") or "")
        name = str(item.get("name") or phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, cookie=cookie)
        acc.normalize()
        if not acc.has_password() and not acc.has_cookie():
            raise ValueError(f"账号 [{acc.name}] 未配置 phone+password 或 cookie")
        accounts.append(acc)

    if not accounts:
        raise ValueError("配置中 accounts 为空")

    n = raw.get("notify") or {}
    env_notify = load_notify_from_env()
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or str(n.get("bark_url") or ""),
        bark_key=env_notify.bark_key or str(n.get("bark_key") or ""),
        bark_server=(
            env_notify.bark_server
            if env_notify.bark_key or env_notify.bark_url
            else str(n.get("bark_server") or DEFAULT_BARK_SERVER)
        ).rstrip("/"),
        bark_group=env_notify.bark_group
        if _env("BARK_GROUP")
        else str(n.get("bark_group") or "推广宝"),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_notify.serverchan_key
        or str(n.get("serverchan_key") or ""),
        webhook_url=env_notify.webhook_url or str(n.get("webhook_url") or ""),
    )

    return AppConfig(
        accounts=accounts,
        invite_code=_env("TGB_INVITE_CODE")
        or str(raw.get("invite_code") or DEFAULT_INVITE_CODE),
        timeout=int(_env("TGB_TIMEOUT") or raw.get("timeout") or 15),
        max_retries=int(_env("TGB_MAX_RETRIES") or raw.get("max_retries") or 3),
        retry_interval=int(
            _env("TGB_RETRY_INTERVAL") or raw.get("retry_interval") or 10
        ),
        ad_watch_seconds=int(
            _env("TGB_AD_WATCH_SECONDS") or raw.get("ad_watch_seconds") or 22
        ),
        inter_account_delay=int(
            _env("TGB_INTER_ACCOUNT_DELAY") or raw.get("inter_account_delay") or 6
        ),
        inter_ad_delay_min=float(
            _env("TGB_INTER_AD_DELAY_MIN") or raw.get("inter_ad_delay_min") or 3
        ),
        inter_ad_delay_max=float(
            _env("TGB_INTER_AD_DELAY_MAX") or raw.get("inter_ad_delay_max") or 6
        ),
        max_ad_loops=int(_env("TGB_MAX_AD_LOOPS") or raw.get("max_ad_loops") or 50),
        user_agent=_env("TGB_UA") or str(raw.get("user_agent") or DEFAULT_UA),
        dry_run=_env_bool("DRY_RUN", bool(raw.get("dry_run", False))),
        notify=notify,
    )


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def extract_formhash(html: str) -> Optional[str]:
    m = re.search(
        r'name="formhash"[^>]*value=["\']([0-9a-f]{8})["\']', html, re.I
    )
    if not m:
        m = re.search(
            r'formhash["\']?\s*[:=]\s*["\']?([0-9a-f]{8})["\']?', html, re.I
        )
    return m.group(1) if m else None


def cookie_header_from_session(session: requests.Session) -> str:
    parts = []
    for c in session.cookies:
        try:
            s = f"{c.name}={c.value}"
            s.encode("latin-1")
            parts.append(s)
        except UnicodeEncodeError:
            continue
    return "; ".join(parts)


def apply_cookie_header(session: requests.Session, cookie: str) -> None:
    session.cookies.clear()
    for pair in cookie.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        session.cookies.set(k.strip(), v.strip())


def has_auth_cookie(session: requests.Session) -> bool:
    for c in session.cookies:
        if c.name.endswith("_auth") and c.value:
            return True
    return False


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class HttpClient:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "*/*",
                "x-requested-with": "XMLHttpRequest",
                "sec-ch-ua-platform": '"Android"',
                "sec-ch-ua": (
                    '"Chromium";v="134", "Not:A-Brand";v="24", '
                    '"Android WebView";v="134"'
                ),
                "sec-ch-ua-mobile": "?1",
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "accept-encoding": "gzip, deflate",
                "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": REFERER_INVITE,
            }
        )

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.cfg.timeout)
        last_err: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                return self.session.request(method, url, **kwargs)
            except requests.RequestException as e:
                last_err = e
                logger.warning(
                    "🌐 请求失败（%d/%d）: %s", attempt, self.cfg.max_retries, e
                )
                if attempt < self.cfg.max_retries:
                    time.sleep(self.cfg.retry_interval)
        raise last_err or RuntimeError("请求重试耗尽")

    def reset(self) -> None:
        self.session.cookies.clear()


# ---------------------------------------------------------------------------
# 业务
# ---------------------------------------------------------------------------

class TuiGuangBaoClient:
    def __init__(
        self,
        account: Account,
        cfg: AppConfig,
        cache: Optional[dict[str, Any]] = None,
    ):
        self.account = account
        self.cfg = cfg
        self.cache = cache if cache is not None else load_session_cache()
        self.http = HttpClient(cfg)
        self.auth_via = ""

    def _post_form(self, url: str, data: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "origin": HOST,
        }
        resp = self.http.request(
            "POST", url, data=data, headers=headers, allow_redirects=False
        )
        text = (resp.text or "").strip()
        if text.startswith("{") or text.startswith("["):
            try:
                body = resp.json()
                if isinstance(body, dict):
                    return body
            except json.JSONDecodeError:
                pass
        return {"_raw": text, "_status": resp.status_code, "code": -1, "msg": text[:200]}

    def ensure_session(self) -> dict[str, Any]:
        """Cookie 配置 → 缓存 → 密码登录。"""
        acc = self.account

        if acc.has_cookie():
            apply_cookie_header(self.http.session, acc.cookie)
            if has_auth_cookie(self.http.session) or self._session_alive():
                self.auth_via = "cookie"
                logger.info("[%s] 🍪 使用配置 Cookie", acc.name)
                return {"ok": True, "via": "cookie"}

        cached = cache_get_cookie(self.cache, acc)
        if cached:
            apply_cookie_header(self.http.session, cached)
            if has_auth_cookie(self.http.session) and self._session_alive():
                self.auth_via = "cache"
                logger.info("[%s] 💾 使用缓存会话", acc.name)
                return {"ok": True, "via": "cache"}
            logger.info("[%s] 💾 缓存会话失效", acc.name)

        if not acc.has_password():
            return {
                "ok": False,
                "via": "none",
                "message": "无可用会话且未配置密码",
            }

        try:
            self.login()
            self.auth_via = "password"
            cookie = cookie_header_from_session(self.http.session)
            cache_set_cookie(self.cache, acc, cookie)
            acc.cookie = cookie
            return {"ok": True, "via": "password"}
        except Exception as e:
            return {"ok": False, "via": "password", "message": str(e)}

    def _session_alive(self) -> bool:
        """轻量探活：任务 status 是否 JSON。"""
        try:
            resp = self.http.request("GET", f"{BASE_PLUGIN}&submodac=status")
            ct = resp.headers.get("content-type", "")
            text = resp.text or ""
            if "loginform" in text and "application/json" not in ct:
                return False
            data = resp.json()
            return str(data.get("code")) == "0"
        except Exception:
            return False

    def login(self) -> None:
        """Discuz 手机版密码登录（对齐 JS 2.5：校验 _auth Cookie）。"""
        acc = self.account
        logger.info("[%s] 📱 提交登录 %s…", acc.name, acc.phone[:3] + "****" + acc.phone[-4:] if len(acc.phone) >= 7 else acc.phone)

        self.http.reset()
        page_resp = self.http.request("GET", LOGIN_PAGE_URL)
        formhash = extract_formhash(page_resp.text or "")
        logger.debug(
            "[%s] 登录页 HTTP %s formhash=%s",
            acc.name,
            page_resp.status_code,
            formhash,
        )
        if not formhash:
            raise RuntimeError("获取登录 formhash 失败")

        data = {
            "formhash": formhash,
            "referer": f"{HOST}/plugin.php?id=xigua_hb&id=xigua_hb&needlogin=1&mobile=2",
            "fastloginfield": "username",
            "cookietime": "2592000",
            "username": acc.phone,
            "password": acc.password,
        }
        headers = {
            "origin": HOST,
            "upgrade-insecure-requests": "1",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        login_resp = self.http.request(
            "POST",
            LOGIN_URL,
            data=data,
            headers=headers,
            allow_redirects=False,
        )
        self.http.session.cookies.update(login_resp.cookies)

        # 与 JS 一致：只要 Cookie 含 *_auth 即视为成功
        if not has_auth_cookie(self.http.session):
            body = login_resp.text or ""
            m = re.search(
                r"密码错误|账号不存在|登录失败|密码为空|验证码错误|登录尝试次数过多",
                body,
            )
            err = m.group(0) if m else f"未知错误(HTTP {login_resp.status_code})"
            logger.debug("[%s] 登录失败体: %s", acc.name, body[:400])
            raise RuntimeError(f"登录验证失败：{err}")

        logger.info("[%s] ✅ 登录成功", acc.name)

    def get_formhash(self) -> Optional[str]:
        try:
            text = self.http.request("GET", BASE_PLUGIN).text or ""
            fh = extract_formhash(text)
            if fh:
                logger.debug("[%s] 🔑 formhash=%s", self.account.name, fh)
                return fh
            if "登录账号" in text or "loginform" in text:
                raise RuntimeError("未登录，请检查账号密码")
            raise RuntimeError("提取不到 formhash")
        except Exception as e:
            logger.error("[%s] ❌ 获取 formhash 失败: %s", self.account.name, e)
            return None

    def bind_yq_code(self) -> dict[str, Any]:
        if not self.cfg.invite_code:
            return {"ok": True, "message": "无邀请码，跳过"}
        fh = self.get_formhash()
        if not fh:
            return {"ok": False, "message": "获取 formhash 失败"}
        try:
            ret = self._post_form(
                BIND_YQ_URL,
                {"formhash": fh, "yqcode": self.cfg.invite_code},
            )
            code = ret.get("code")
            msg = str(ret.get("msg") or "")
            if str(code) == "0":
                logger.info(
                    "[%s] 🎊 邀请码 %s 绑定成功",
                    self.account.name,
                    self.cfg.invite_code,
                )
                return {"ok": True, "message": "绑定成功"}
            if msg == "不能自己":
                logger.info("[%s] ⚠️ %s", self.account.name, msg)
                return {"ok": True, "message": msg}
            logger.info("[%s] ℹ️ 邀请码绑定：%s", self.account.name, msg or ret)
            return {"ok": False, "message": msg or str(ret)}
        except Exception as e:
            logger.error("[%s] ❌ 绑定邀请码异常：%s", self.account.name, e)
            return {"ok": False, "message": str(e)}

    def get_task_status(self) -> Optional[dict[str, Any]]:
        try:
            resp = self.http.request("GET", f"{BASE_PLUGIN}&submodac=status")
            ct = resp.headers.get("content-type", "")
            text = resp.text or ""
            if "loginform" in text and "json" not in ct.lower():
                raise RuntimeError("登录态失效，请重新登录")
            data = resp.json()
            if str(data.get("code")) != "0":
                raise RuntimeError(f"code:{data.get('code')} {data.get('msg') or ''}")
            body = data.get("data")
            return body if isinstance(body, dict) else {}
        except Exception as e:
            logger.error("[%s] ❌ 查任务失败：%s", self.account.name, e)
            return None

    def get_next_ad_token(self) -> Optional[dict[str, Any]]:
        try:
            fh = self.get_formhash()
            if not fh:
                raise RuntimeError("获取 formhash 失败")
            ret = self._post_form(f"{BASE_PLUGIN}&submodac=next_ad", {"formhash": fh})
            if str(ret.get("code")) != "0":
                raise RuntimeError(ret.get("msg") or "获取广告失败")
            data = ret.get("data")
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.error("[%s] ❌ 获取广告 Token 失败：%s", self.account.name, e)
            return None

    def submit_ad_complete(self, token: str) -> Optional[dict[str, Any]]:
        try:
            fh = self.get_formhash()
            if not fh:
                raise RuntimeError("获取 formhash 失败")
            ret = self._post_form(
                f"{BASE_PLUGIN}&submodac=complete_ad",
                {"formhash": fh, "token": token},
            )
            if str(ret.get("code")) != "0":
                raise RuntimeError(ret.get("msg") or "广告上报失败")
            data = ret.get("data")
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error("[%s] ❌ 广告上报失败：%s", self.account.name, e)
            return None

    def claim_reward(self) -> dict[str, Any]:
        try:
            fh = self.get_formhash()
            if not fh:
                return {"ok": False, "message": "获取 formhash 失败"}
            ret = self._post_form(f"{BASE_PLUGIN}&submodac=claim", {"formhash": fh})
            msg = str(ret.get("msg") or "")
            logger.info("[%s] 🎁 领奖返回：%s", self.account.name, msg or ret)
            ok = str(ret.get("code")) == "0" or any(
                w in msg for w in ("成功", "领取", "已领")
            )
            return {
                "ok": ok,
                "message": msg or ("OK" if ok else "领奖失败"),
                "data": ret.get("data"),
                "raw": ret,
            }
        except Exception as e:
            logger.error("[%s] ❌ 领奖失败：%s", self.account.name, e)
            return {"ok": False, "message": str(e)}

    def run(self, *, login_only: bool = False) -> dict[str, Any]:
        acc = self.account
        result: dict[str, Any] = {
            "ok": False,
            "name": acc.name,
            "message": "",
            "via": "",
            "viewed": 0,
            "target": 0,
            "claimed": False,
            "ads_done": 0,
            "steps": [],
        }

        auth = self.ensure_session()
        result["via"] = str(auth.get("via") or "")
        if not auth.get("ok"):
            result["message"] = str(auth.get("message") or "登录失败")
            result["steps"].append(f"auth:fail:{result['message']}")
            return result
        result["steps"].append(f"auth:{result['via']}")

        if login_only:
            result["ok"] = True
            result["message"] = "登录成功"
            return result

        time.sleep(1.5)
        self.bind_yq_code()
        result["steps"].append("bind_invite")

        if self.cfg.dry_run:
            st = self.get_task_status()
            if st:
                result["viewed"] = int(st.get("viewed_count") or 0)
                result["target"] = int(st.get("target_count") or 0)
                result["claimed"] = bool(st.get("claimed"))
                result["ok"] = True
                result["message"] = (
                    f"dry-run 进度 {result['viewed']}/{result['target']}"
                )
            else:
                result["message"] = "dry-run 查进度失败"
            return result

        for loop in range(max(1, self.cfg.max_ad_loops)):
            task_info = self.get_task_status()
            if not task_info:
                # 会话可能过期 → 密码重登一次
                if acc.has_password() and loop == 0:
                    logger.info("[%s] 🔄 任务查询失败，尝试重登…", acc.name)
                    try:
                        self.login()
                        cache_set_cookie(
                            self.cache,
                            acc,
                            cookie_header_from_session(self.http.session),
                        )
                        result["via"] = "password→relogin"
                        task_info = self.get_task_status()
                    except Exception as e:
                        result["message"] = f"重登失败: {e}"
                        break
                if not task_info:
                    result["message"] = result["message"] or "获取任务状态失败"
                    break

            viewed = int(task_info.get("viewed_count") or 0)
            target = int(task_info.get("target_count") or 0)
            countdown = int(task_info.get("countdown_seconds") or 0)
            can_claim = bool(task_info.get("can_claim"))
            claimed = bool(task_info.get("claimed"))

            result["viewed"] = viewed
            result["target"] = target
            result["claimed"] = claimed

            logger.info(
                "[%s] 📊 进度：%d/%d | 可领奖:%s | 今日已领取:%s",
                acc.name,
                viewed,
                target,
                can_claim,
                claimed,
            )

            if can_claim and not claimed:
                logger.info("[%s] 🎉 任务已满，准备领奖", acc.name)
                time.sleep(2)
                cr = self.claim_reward()
                if cr.get("ok"):
                    result["ok"] = True
                    result["claimed"] = True
                    result["message"] = cr.get("message") or "领奖成功"
                    result["steps"].append("claim:ok")
                else:
                    result["message"] = cr.get("message") or "领奖失败"
                    result["steps"].append(f"claim:fail:{result['message']}")
                break

            if claimed:
                result["ok"] = True
                result["message"] = "今日已领取"
                result["steps"].append("already_claimed")
                logger.info("[%s] ✅ 今日已领取", acc.name)
                break

            if target > 0 and viewed >= target:
                result["ok"] = True
                result["message"] = "今日任务全部完成"
                result["steps"].append("done_no_claim")
                logger.info("[%s] ✅ 今日任务全部完成", acc.name)
                break

            if countdown > 0:
                wait = min(countdown, 600)
                logger.info("[%s] ⏳ 冷却等待 %d 秒", acc.name, wait)
                time.sleep(wait)

            ad = self.get_next_ad_token()
            if not ad:
                result["message"] = "获取广告失败"
                result["steps"].append("next_ad:fail")
                break

            token = str(ad.get("token") or "")
            if not token:
                result["message"] = "广告 Token 为空"
                break

            logger.info(
                "[%s] ▶ Token=%s… 模拟观看 %ds",
                acc.name,
                token[:16],
                self.cfg.ad_watch_seconds,
            )
            time.sleep(max(0, self.cfg.ad_watch_seconds))

            new_task = self.submit_ad_complete(token)
            if new_task is None:
                result["message"] = "广告上报失败"
                result["steps"].append("complete_ad:fail")
                break

            result["ads_done"] = int(result.get("ads_done") or 0) + 1
            nv = new_task.get("viewed_count", viewed)
            logger.info("[%s] ✅ 上报成功，完成数：%s", acc.name, nv)
            result["viewed"] = int(nv or viewed)

            lo = min(self.cfg.inter_ad_delay_min, self.cfg.inter_ad_delay_max)
            hi = max(self.cfg.inter_ad_delay_min, self.cfg.inter_ad_delay_max)
            time.sleep(random.uniform(lo, hi))

        if not result["message"]:
            result["message"] = "执行未完成（循环结束）"
        if result["ok"]:
            logger.info("[%s] 💚 本号完成：%s", acc.name, result["message"])
        else:
            logger.warning("[%s] 💔 本号结束：%s", acc.name, result["message"])
        return result


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

def format_summary(account_results: list[tuple[str, dict[str, Any]]]) -> str:
    from datetime import datetime as _dt

    lines: list[str] = []
    lines.append(f"📅 {_dt.now().strftime('%m-%d %H:%M')}")
    lines.append("")

    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    fail_n = len(account_results) - ok_n

    for i, (name, r) in enumerate(account_results):
        ok = bool(r.get("ok"))
        viewed = r.get("viewed", 0)
        target = r.get("target", 0)
        claimed = bool(r.get("claimed"))
        ads = r.get("ads_done") or 0
        msg = str(r.get("message") or "").strip()
        via = str(r.get("via") or "")

        lines.append(f"{'✅' if ok else '❌'} {name}")
        lines.append(f"   📊 进度：{viewed}/{target}" + (f" · 本轮看广告 {ads}" if ads else ""))
        if claimed:
            lines.append("   💰 今日已领奖")
        elif ok:
            lines.append(f"   ✅ {msg or '完成'}")
        else:
            short = msg if len(msg) <= 100 else msg[:97] + "…"
            lines.append(f"   ❌ {short}")
        if via:
            via_map = {
                "password": "密码登录",
                "cookie": "Cookie",
                "cache": "缓存会话",
                "password→relogin": "密码重登",
            }
            lines.append(f"   🔐 {via_map.get(via, via)}")

        if i < len(account_results) - 1:
            lines.append("")

    lines.append("")
    lines.append("────────")
    if fail_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(account_results)} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(account_results)} 全部失败")
    else:
        lines.append(
            f"📊 合计：成功 {ok_n} · 失败 {fail_n}（共 {len(account_results)} 号）"
        )
    return "\n".join(lines)


def format_notify_title(account_results: list[tuple[str, dict[str, Any]]]) -> str:
    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    n = len(account_results)
    if n == 0:
        return "推广宝每日广告"
    if ok_n == n:
        return f"推广宝每日广告 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"推广宝每日广告 ❌ 0/{n}"
    return f"推广宝每日广告 ⚠️ {ok_n}/{n}"


def _build_bark_endpoint(cfg: NotifyConfig) -> Optional[str]:
    if cfg.bark_url:
        return cfg.bark_url.strip().rstrip("/")
    if cfg.bark_key:
        server = (cfg.bark_server or DEFAULT_BARK_SERVER).rstrip("/")
        return f"{server}/{cfg.bark_key.strip()}"
    return None


def send_bark(cfg: NotifyConfig, title: str, body: str) -> None:
    endpoint = _build_bark_endpoint(cfg)
    if not endpoint:
        return
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.bark_group or "推广宝",
    }
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level

    post_url = endpoint if endpoint.endswith("/push") else endpoint
    try:
        r = requests.post(post_url, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint.rstrip('/')}/"
                f"{quote(title, safe='')}/"
                f"{quote(body, safe='')}"
            )
            r = requests.get(get_url, timeout=15)
        logger.info("📣 Bark 已推送（HTTP %s）", r.status_code)
    except Exception as e:
        logger.warning("📣 Bark 推送失败: %s", e)


def send_serverchan(key: str, title: str, content: str) -> None:
    if key.startswith("sctp"):
        m = re.match(r"sctp(\d+)t", key)
        if m:
            url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send"
        else:
            url = f"https://sctapi.ftqq.com/{key}.send"
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        requests.post(url, json={"title": title, "desp": content}, timeout=10)
        logger.info("📣 Server酱 已推送")
    except Exception as e:
        logger.warning("📣 Server酱推送失败: %s", e)


def send_notify(cfg: NotifyConfig, title: str, content: str) -> None:
    if not cfg.enabled():
        logger.info("📣 未配置 Bark/通知渠道，跳过推送")
        return
    if cfg.bark_url or cfg.bark_key:
        send_bark(cfg, title, content)
    if cfg.serverchan_key:
        send_serverchan(cfg.serverchan_key, title, content)
    if cfg.webhook_url:
        try:
            r = requests.post(
                cfg.webhook_url,
                json={"title": title, "content": content},
                timeout=10,
            )
            logger.info("📣 Webhook 已推送（HTTP %s）", r.status_code)
        except Exception as e:
            logger.warning("📣 Webhook 推送失败: %s", e)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def log_banner(title: str) -> None:
    logger.info("──────── %s ────────", title)


def resolve_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        return load_config_yaml(Path(args.config))

    env_cfg = load_config_from_env()
    if env_cfg is not None:
        logger.info("📦 已从环境变量加载 %d 个账号", len(env_cfg.accounts))
        return env_cfg

    local = SCRIPT_DIR / "config.yaml"
    if local.is_file():
        logger.info("📦 使用本地配置: %s", local)
        return load_config_yaml(local)

    raise FileNotFoundError(
        "未找到账号配置。\n"
        "青龙：设置 TGB_ACCOUNTS 或 TGB 或 TGB_USER/TGB_PASS\n"
        "本地：cp config.example.yaml config.yaml 并填写"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="推广宝每日看广告领奖（青龙 / Bark）")
    parser.add_argument("-c", "--config", help="本地 yaml 配置路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    parser.add_argument(
        "--login-only", action="store_true", help="仅登录/探活，不看广告"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="登录后只查进度（同 DRY_RUN=1）"
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("❌ %s", e)
        return 2

    if args.dry_run:
        cfg.dry_run = True

    logger.info("🚀 推广宝 · 每日看广告")
    logger.info(
        "   账号 %d 个 · 通知 %s · 邀请码 %s · 观看 %ds%s",
        len(cfg.accounts),
        "开" if cfg.notify.enabled() else "关",
        cfg.invite_code,
        cfg.ad_watch_seconds,
        " · DRY_RUN" if cfg.dry_run else "",
    )

    cache = load_session_cache()
    account_results: list[tuple[str, dict[str, Any]]] = []

    for i, acc in enumerate(cfg.accounts):
        log_banner(f"👤 {acc.name}")
        logger.info("[%s] 🔐 鉴权配置：%s", acc.name, acc.auth_label())
        try:
            client = TuiGuangBaoClient(acc, cfg, cache)
            result = client.run(login_only=bool(args.login_only))
        except Exception as e:
            logger.error("[%s] 💥 未处理异常: %s", acc.name, e)
            logger.debug("exception traceback", exc_info=True)
            result = {
                "ok": False,
                "message": str(e),
                "viewed": 0,
                "target": 0,
                "claimed": False,
                "via": "error",
            }

        if result.get("ok"):
            logger.info("[%s] ✅ %s", acc.name, result.get("message") or "OK")
        else:
            logger.error("[%s] ❌ %s", acc.name, result.get("message") or "失败")

        account_results.append((acc.name, result))

        if i < len(cfg.accounts) - 1:
            logger.info(
                "⏳ 等待 %d 秒后执行下一账号…", cfg.inter_account_delay
            )
            time.sleep(max(0, cfg.inter_account_delay))

    summary = format_summary(account_results)
    title = format_notify_title(account_results)

    logger.info("")
    log_banner("执行结果")
    for line in summary.splitlines():
        logger.info("%s", line)

    send_notify(cfg.notify, title, summary)

    any_fail = any(not r.get("ok") for _, r in account_results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
