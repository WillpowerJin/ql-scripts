#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里云开发者社区 日常任务

cron: 0 7,13 * * *
new Env('阿里云开发者社区');

策略：
  1. 优先 Cookie；无 Cookie 时用「用户名/手机号 + 密码」登录拿会话
  2. 12 点前：多社区签到、点赞/收藏/分享/评论等
  3. 12 点后：领待收积分、领签到奖、取消点赞/收藏
  4. 可选：场景实验、视频、库存查询
  5. 配置读青龙环境变量（本地也可 config.yaml）
  6. 结果可推送 Bark / Server酱 / Webhook

青龙环境变量（账号）：
  ALIYUN_ACCOUNTS  推荐 JSON 数组
    [{"name":"主号","username":"邮箱或用户名","password":"..."}]
    或 [{"name":"主号","phone":"138...","password":"..."}]
    或 [{"name":"主号","cookie":"login_aliyunid_ticket=...; ..."}]
  或 ALIYUN_WEB_DATA / aliyunWeb_data  Cookie，多账号 @ 或 & 分隔
  或平行变量（& 分隔）：
    ALIYUN_USER / ALIYUN_PHONE + ALIYUN_PASS + ALIYUN_COOKIE + ALIYUN_NAME

兼容原脚本变量名：
  aliyunWeb_data / aliyunWeb_time / aliyunWeb_scene / aliyunWeb_stock / aliyunWeb_video

可选：
  ALIYUN_TIME=12          上下午分界小时（1-23）
  ALIYUN_SCENE=0          场景实验（默认关）
  ALIYUN_VIDEO=0          视频任务（默认关）
  ALIYUN_STOCK=0          打印积分商城库存（默认关）
  ALIYUN_TIMEOUT / ALIYUN_MAX_RETRIES / ALIYUN_RETRY_INTERVAL
  ALIYUN_SESSION_CACHE
  BARK_* / SERVERCHAN_KEY / WEBHOOK_URL
  DRY_RUN=1

依赖：requests
  青龙：依赖管理添加 requests
  本地 yaml：再装 PyYAML

说明：
  - 密码登录走阿里云通行证；若触发滑块/二次验证，请在浏览器登录后改用 Cookie。
  - Cookie 获取：阿里云 APP → 首页 → 积分商城，或浏览器登录 developer.aliyun.com 后复制。
  - 逻辑参考 leiyiyan/resource aliyun_web.js（已混淆），本实现为可读 Python 重写。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests

cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

BASE = "https://developer.aliyun.com"
API = f"{BASE}/developer/api"
UCC = "https://ucc.aliyun.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_BARK_SERVER = "https://api.day.app"
SCRIPT_DIR = Path(__file__).resolve().parent

# 多社区签到（与原脚本 taskGroup 对齐）
TASK_GROUPS: list[dict[str, str]] = [
    {"code": "", "name": "我的社区"},
    {"code": "ecs", "name": "弹性计算"},
    {"code": "computenest", "name": "计算巢"},
    {"code": "yitian", "name": "倚天"},
    {"code": "wuying", "name": "无影"},
    {"code": "cloudnative", "name": "云原生"},
    {"code": "storage", "name": "云存储"},
    {"code": "database", "name": "数据库"},
    {"code": "polardb", "name": "PolarDB"},
    {"code": "modelscope", "name": "ModelScope"},
    {"code": "vision", "name": "视觉智能"},
    {"code": "dns", "name": "DNS"},
    {"code": "iot", "name": "物联网"},
    {"code": "aliyun_linux", "name": "Alibaba Cloud Linux"},
    {"code": "tongyi", "name": "通义"},
]

logger = logging.getLogger("aliyun_dev")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    username: str = ""  # 用户名或邮箱
    phone: str = ""
    password: str = ""
    cookie: str = ""

    def login_id(self) -> str:
        return (self.phone or self.username or "").strip()

    def has_password(self) -> bool:
        return bool(self.login_id() and self.password)

    def has_cookie(self) -> bool:
        return bool(self.cookie.strip())

    def cache_key(self) -> str:
        lid = self.login_id()
        if lid:
            return f"id:{lid}"
        if self.name:
            return f"name:{self.name}"
        return f"ck:{hashlib.md5(self.cookie.encode()).hexdigest()[:12]}"

    def auth_label(self) -> str:
        parts = []
        if self.has_cookie():
            parts.append("cookie")
        if self.has_password():
            parts.append("password")
        return "+".join(parts) if parts else "none"

    def normalize(self) -> None:
        self.username = self.username.strip()
        self.phone = self.phone.strip()
        self.cookie = self.cookie.strip()
        if self.cookie.lower().startswith("cookie:"):
            self.cookie = self.cookie.split(":", 1)[1].strip()
        if not self.name:
            self.name = self.login_id() or f"account"


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "阿里云社区"
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
    split_hour: int = 12
    # 场景/视频默认开（轻量版，多一点积分来源）
    enable_scene: bool = True
    enable_video: bool = True
    enable_stock: bool = False
    timeout: int = 30
    max_retries: int = 3
    retry_interval: int = 8
    inter_account_delay: float = 3.0
    user_agent: str = DEFAULT_UA
    dry_run: bool = False
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_any(*names: str, default: str = "") -> str:
    for n in names:
        v = _env(n)
        if v:
            return v
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "on", "y")


def _split_multi(value: str) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r"[@&\n]", value) if x.strip()]


def resolve_session_cache_path() -> Path:
    env = _env("ALIYUN_SESSION_CACHE")
    if env:
        return Path(env).expanduser()
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "aliyun_dev_session_cache.json"
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
            "login_id": account.login_id(),
            "ts": int(time.time()),
        }
        save_session_cache(cache)


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("ALIYUN_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"ALIYUN_ACCOUNTS[{i}] 必须是对象")
        user = str(
            item.get("username")
            or item.get("user")
            or item.get("email")
            or item.get("account")
            or ""
        )
        phone = str(item.get("phone") or item.get("mobile") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        # 原抓包 / 原脚本字段 token 实际是整段 Cookie
        cookie = str(
            item.get("cookie")
            or item.get("ck")
            or item.get("token")
            or ""
        )
        name = str(
            item.get("name")
            or item.get("userName")
            or item.get("userId")
            or phone
            or user
            or f"account_{i + 1}"
        )
        # userName 形如 aliyun3806162228-10886 时也可作备注
        if not user and item.get("userName"):
            user = str(item.get("userName") or "")
        acc = Account(
            name=name, username=user, phone=phone, password=pwd, cookie=cookie
        )
        acc.normalize()
        if not acc.has_cookie() and not acc.has_password():
            raise ValueError(
                f"ALIYUN_ACCOUNTS[{i}] 需配置 cookie/token 或 username/phone+password"
            )
        accounts.append(acc)
    return accounts


def _first_set_env(*names: str) -> tuple[str, str]:
    """返回 (变量名, 值)；都未设置则 ("", "")。"""
    for n in names:
        v = _env(n)
        if v:
            return n, v
    return "", ""


def _parse_accounts_from_env() -> tuple[list[Account], str]:
    """
    从环境变量解析账号。
    返回 (accounts, source_label)，source_label 便于日志定位。
    """
    # 1) JSON
    j_name, j = _first_set_env("ALIYUN_ACCOUNTS", "ALIYUN_DEV_ACCOUNTS")
    if j:
        return _parse_accounts_json(j), j_name

    # 2) 原脚本 Cookie 串（纯 Cookie 时账号名会是 cookie_1）
    ck_name, ck_raw = _first_set_env(
        "ALIYUN_WEB_DATA", "aliyunWeb_data", "ALIYUN_COOKIE"
    )
    if ck_raw and not _env("ALIYUN_USER") and not _env("ALIYUN_PHONE"):
        accounts = []
        for i, part in enumerate(_split_multi(ck_raw)):
            if "#" in part and "login_" not in part and "=" not in part.split("#", 1)[0]:
                left, pwd = part.split("#", 1)
                left = left.strip()
                if re.fullmatch(r"1\d{10}", left):
                    acc = Account(name=left, phone=left, password=pwd.strip())
                else:
                    acc = Account(name=left, username=left, password=pwd.strip())
            else:
                # 给个短指纹方便确认是哪份 Cookie
                fp = hashlib.md5(part.encode()).hexdigest()[:6]
                acc = Account(name=f"cookie_{i + 1}_{fp}", cookie=part)
            acc.normalize()
            accounts.append(acc)
        return accounts, ck_name

    # 3) 平行变量
    users = _split_multi(_env_any("ALIYUN_USER", "ALIYUN_USERNAME", "ALIYUN_EMAIL"))
    phones = _split_multi(_env_any("ALIYUN_PHONE", "ALIYUN_MOBILE"))
    passes = _split_multi(_env_any("ALIYUN_PASS", "ALIYUN_PASSWORD"))
    cookies = _split_multi(
        _env_any("ALIYUN_COOKIE", "ALIYUN_WEB_DATA", "aliyunWeb_data")
    )
    names = _split_multi(_env("ALIYUN_NAME"))
    n = max(len(users), len(phones), len(passes), len(cookies))
    if n <= 0:
        return [], ""
    accounts = []
    for i in range(n):
        user = users[i] if i < len(users) else ""
        phone = phones[i] if i < len(phones) else ""
        pwd = passes[i] if i < len(passes) else ""
        cookie = cookies[i] if i < len(cookies) else ""
        name = names[i] if i < len(names) else (phone or user or f"account_{i + 1}")
        acc = Account(
            name=name,
            username=user,
            phone=phone,
            password=pwd,
            cookie=cookie,
        )
        acc.normalize()
        if not acc.has_cookie() and not acc.has_password():
            raise ValueError(f"第 {i + 1} 个账号缺少 cookie 或密码")
        accounts.append(acc)
    return accounts, "ALIYUN_USER/PHONE/COOKIE"


def load_notify_from_env() -> NotifyConfig:
    bark_url = _env_any("BARK_URL", "BARK_PUSH")
    bark_key = _env_any("BARK_KEY", "BARK_DEVICE_KEY")
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""
    return NotifyConfig(
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=_env("BARK_GROUP", "阿里云社区"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env_any("SERVERCHAN_KEY", "PUSH_KEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def _parse_bool_env(*names: str, default: bool = False) -> bool:
    for n in names:
        v = _env(n)
        if v:
            return v.lower() in ("1", "true", "yes", "on", "y")
    return default


def load_config_from_env() -> Optional[tuple[AppConfig, str]]:
    """成功时返回 (AppConfig, 环境变量来源名)。"""
    accounts, source = _parse_accounts_from_env()
    if not accounts:
        return None
    try:
        split_hour = int(_env_any("ALIYUN_TIME", "aliyunWeb_time", default="12"))
    except ValueError:
        split_hour = 12
    split_hour = max(1, min(23, split_hour))
    cfg = AppConfig(
        accounts=accounts,
        split_hour=split_hour,
        enable_scene=_parse_bool_env("ALIYUN_SCENE", "aliyunWeb_scene", default=True),
        enable_video=_parse_bool_env("ALIYUN_VIDEO", "aliyunWeb_video", default=True),
        enable_stock=_parse_bool_env("ALIYUN_STOCK", "aliyunWeb_stock", default=False),
        timeout=int(_env("ALIYUN_TIMEOUT", "30")),
        max_retries=int(_env("ALIYUN_MAX_RETRIES", "3")),
        retry_interval=int(_env("ALIYUN_RETRY_INTERVAL", "8")),
        inter_account_delay=float(_env("ALIYUN_INTER_ACCOUNT_DELAY", "3")),
        user_agent=_env("ALIYUN_UA", DEFAULT_UA),
        dry_run=_env_bool("DRY_RUN", False),
        notify=load_notify_from_env(),
    )
    return cfg, source or "env"


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError("本地 yaml 需要 PyYAML：pip install PyYAML") from e
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        user = str(
            item.get("username")
            or item.get("user")
            or item.get("email")
            or item.get("account")
            or ""
        )
        phone = str(item.get("phone") or item.get("mobile") or "")
        pwd = str(item.get("password") or item.get("pwd") or "")
        cookie = str(item.get("cookie") or item.get("ck") or "")
        name = str(item.get("name") or phone or user or f"account_{i + 1}")
        acc = Account(
            name=name, username=user, phone=phone, password=pwd, cookie=cookie
        )
        acc.normalize()
        if not acc.has_cookie() and not acc.has_password():
            raise ValueError(f"账号 [{acc.name}] 需 cookie 或 账号+密码")
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
        else str(n.get("bark_group") or "阿里云社区"),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_notify.serverchan_key
        or str(n.get("serverchan_key") or ""),
        webhook_url=env_notify.webhook_url or str(n.get("webhook_url") or ""),
    )

    try:
        split_hour = int(
            _env_any("ALIYUN_TIME", "aliyunWeb_time")
            or raw.get("split_hour")
            or 12
        )
    except (TypeError, ValueError):
        split_hour = 12

    return AppConfig(
        accounts=accounts,
        split_hour=max(1, min(23, split_hour)),
        enable_scene=_parse_bool_env("ALIYUN_SCENE", "aliyunWeb_scene")
        if _env_any("ALIYUN_SCENE", "aliyunWeb_scene")
        else bool(raw.get("enable_scene", True)),
        enable_video=_parse_bool_env("ALIYUN_VIDEO", "aliyunWeb_video")
        if _env_any("ALIYUN_VIDEO", "aliyunWeb_video")
        else bool(raw.get("enable_video", True)),
        enable_stock=_parse_bool_env("ALIYUN_STOCK", "aliyunWeb_stock")
        if _env_any("ALIYUN_STOCK", "aliyunWeb_stock")
        else bool(raw.get("enable_stock", False)),
        timeout=int(_env("ALIYUN_TIMEOUT") or raw.get("timeout") or 30),
        max_retries=int(_env("ALIYUN_MAX_RETRIES") or raw.get("max_retries") or 3),
        retry_interval=int(
            _env("ALIYUN_RETRY_INTERVAL") or raw.get("retry_interval") or 8
        ),
        inter_account_delay=float(
            _env("ALIYUN_INTER_ACCOUNT_DELAY")
            or raw.get("inter_account_delay")
            or 3
        ),
        user_agent=_env("ALIYUN_UA") or str(raw.get("user_agent") or DEFAULT_UA),
        dry_run=_env_bool("DRY_RUN", bool(raw.get("dry_run", False))),
        notify=notify,
    )


# ---------------------------------------------------------------------------
# HTTP / Cookie 工具
# ---------------------------------------------------------------------------

def cookie_header(session: requests.Session) -> str:
    parts = []
    for c in session.cookies:
        try:
            s = f"{c.name}={c.value}"
            s.encode("latin-1")
            parts.append(s)
        except UnicodeEncodeError:
            continue
    return "; ".join(parts)


def apply_cookie(session: requests.Session, cookie: str) -> None:
    """注入 Cookie。不绑死 domain，避免 CookieJar 丢弃跨子域字段。"""
    session.cookies.clear()
    for pair in cookie.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        name, val = k.strip(), v.strip()
        if not name:
            continue
        # 不设 domain，由 requests 随请求 Host 带上；另写一份 .aliyun.com 兜底
        session.cookies.set(name, val)
        try:
            session.cookies.set(name, val, domain=".aliyun.com", path="/")
        except Exception:
            pass


def looks_like_session(cookie: str) -> bool:
    low = cookie.lower()
    keys = (
        "login_aliyunid",
        "login_aliyunid_ticket",
        "aliyun_login",
        "login_aliyunid_csrf",
        "cna",
        "h_csrf",
        "c_csrf",
        "isg=",
    )
    return any(k in low for k in keys) or ("=" in cookie and len(cookie) > 40)


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class AliyunDevClient:
    def __init__(
        self,
        account: Account,
        cfg: AppConfig,
        cache: Optional[dict[str, Any]] = None,
    ):
        self.account = account
        self.cfg = cfg
        self.cache = cache if cache is not None else load_session_cache()
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": f"{BASE}/",
                "Origin": BASE,
            }
        )
        self.auth_via = ""
        self.ck_ok = False
        self.stats: dict[str, Any] = {
            "sign_ok": 0,
            "sign_skip": 0,
            "like": 0,
            "fav": 0,
            "share": 0,
            "comment": 0,
            "ebook": 0,
            "ask_vote": 0,
            "scene": 0,
            "video": 0,
            "score_got": 0,
            "score_before": None,
            "score_now": None,
            "score_delta": 0,
            "pending": None,
        }

    def _sleep(self, a: float = 1.0, b: float = 2.0) -> None:
        time.sleep(random.uniform(a, b))

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        data: Any = None,
        json_body: Any = None,
        headers: Optional[dict[str, str]] = None,
        allow_redirects: bool = True,
        raw: bool = False,
    ) -> Any:
        if url.startswith("/"):
            url = BASE + url
        hdrs = dict(self.session.headers)
        # 优先使用完整 Cookie 头（与手机抓包一致）
        if self.account.cookie and "Cookie" not in (headers or {}):
            hdrs["Cookie"] = self.account.cookie
        elif "Cookie" not in hdrs:
            ch = cookie_header(self.session)
            if ch:
                hdrs["Cookie"] = ch
        if headers:
            hdrs.update(headers)
        last_err: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                resp = self.session.request(
                    method.upper(),
                    url,
                    params=params,
                    data=data,
                    json=json_body,
                    headers=hdrs,
                    timeout=self.cfg.timeout,
                    allow_redirects=allow_redirects,
                )
                logger.debug(
                    "[%s] %s %s → %s %s",
                    self.account.name,
                    method.upper(),
                    url[:80],
                    resp.status_code,
                    (resp.text or "")[:160],
                )
                if raw:
                    return resp
                ct = resp.headers.get("content-type", "")
                text = resp.text or ""
                if "json" in ct or text.strip().startswith(("{", "[")):
                    try:
                        return resp.json()
                    except Exception:
                        return {"_raw": text, "_status": resp.status_code}
                return {"_raw": text, "_status": resp.status_code, "_html": True}
            except requests.RequestException as e:
                last_err = e
                logger.warning(
                    "[%s] 🌐 请求失败（%d/%d）: %s",
                    self.account.name,
                    attempt,
                    self.cfg.max_retries,
                    e,
                )
                if attempt < self.cfg.max_retries:
                    time.sleep(self.cfg.retry_interval)
        raise last_err or RuntimeError("请求失败")

    # ----- 鉴权 -----

    def ensure_session(self) -> dict[str, Any]:
        acc = self.account
        cookie_tried = False
        cookie_dead_msg = ""

        if acc.has_cookie() and looks_like_session(acc.cookie):
            cookie_tried = True
            apply_cookie(self.session, acc.cookie)
            # 同时强制请求头携带完整 Cookie（防止 jar 丢字段）
            self.session.headers["Cookie"] = acc.cookie
            if self._session_alive():
                self.auth_via = "cookie"
                self.ck_ok = True
                logger.info("[%s] 🍪 使用配置 Cookie", acc.name)
                return {"ok": True, "via": "cookie"}
            cookie_dead_msg = "配置 Cookie 已失效（接口返回未登录）"
            logger.warning("[%s] 🍪 %s", acc.name, cookie_dead_msg)

        cached = cache_get_cookie(self.cache, acc)
        if cached and looks_like_session(cached):
            cookie_tried = True
            apply_cookie(self.session, cached)
            self.session.headers["Cookie"] = cached
            if self._session_alive():
                self.auth_via = "cache"
                self.ck_ok = True
                logger.info("[%s] 💾 使用缓存会话", acc.name)
                return {"ok": True, "via": "cache"}
            logger.warning("[%s] 💾 缓存会话失效", acc.name)

        if acc.has_password():
            lr = self.login_with_password()
            if lr.get("ok"):
                self.auth_via = "password"
                self.ck_ok = True
                cookie = cookie_header(self.session)
                cache_set_cookie(self.cache, acc, cookie)
                acc.cookie = cookie
                self.session.headers["Cookie"] = cookie
                return lr
            # 密码失败时，若之前有失效 Cookie，拼上说明
            if cookie_tried:
                lr = dict(lr)
                lr["message"] = (
                    f"{lr.get('message') or '密码登录失败'}；"
                    f"且 {cookie_dead_msg or 'Cookie 不可用'}。"
                    "请重新从手机/浏览器抓取 Cookie。"
                )
            return lr

        if cookie_tried:
            tip = (
                f"{cookie_dead_msg or 'Cookie 失效'}。"
                "请更新环境变量/配置里的 Cookie 后重试。"
            )
            # 若环境变量覆盖了本地 config.yaml，特别提示
            local_cfg = SCRIPT_DIR / "config.yaml"
            if local_cfg.is_file() and load_config_from_env() is not None:
                tip += (
                    " 注意：当前优先使用了【环境变量】里的 Cookie，"
                    "本地 config.yaml 被忽略；"
                    "可 unset aliyunWeb_data ALIYUN_WEB_DATA ALIYUN_COOKIE ALIYUN_ACCOUNTS "
                    "后改用 config.yaml，或直接更新环境变量为最新 Cookie。"
                )
            else:
                tip += (
                    " 请重新登录 developer.aliyun.com 或阿里云 APP 积分商城后更新 Cookie。"
                )
            return {"ok": False, "via": "cookie", "message": tip}

        return {
            "ok": False,
            "via": "none",
            "message": "未配置 Cookie/token，也未配置账号密码",
        }

    def _session_alive(self) -> bool:
        try:
            data = self.request("GET", f"{API}/my/user/getUser")
            if isinstance(data, dict):
                # 成功通常有 data / code==200 / 用户字段
                if data.get("data") or data.get("success") is True:
                    return True
                code = str(data.get("code") or "")
                if code in ("200", "0", "SUCCESS"):
                    return True
                msg = str(data.get("message") or data.get("msg") or "")
                if any(w in msg for w in ("未登录", "登录", "401", "未授权", "login")):
                    return False
                # 有时返回业务体
                if "nickname" in data or "userId" in str(data.get("data") or ""):
                    return True
            score = self.get_user_score()
            return score is not None
        except Exception:
            return False

    def login_with_password(self) -> dict[str, Any]:
        """
        尝试阿里云通行证密码登录。
        注意：线上常触发滑块/短信；失败时请改用 Cookie。
        """
        acc = self.account
        login_id = acc.login_id()
        logger.info(
            "[%s] 📱 尝试密码登录 %s…",
            acc.name,
            login_id[:3] + "****" + login_id[-2:] if len(login_id) > 6 else login_id,
        )
        self.session.cookies.clear()

        # 1) 拉登录页拿 csrf
        login_pages = [
            "https://account.aliyun.com/login/login.htm",
            "https://account.aliyun.com/login/login.htm?oauth_callback="
            + quote(BASE + "/", safe=""),
        ]
        csrf = ""
        for page in login_pages:
            try:
                r = self.session.get(page, timeout=self.cfg.timeout)
                for c in self.session.cookies:
                    if "csrf" in c.name.lower() and c.value:
                        csrf = c.value
                        break
                m = re.search(
                    r'login_aliyunid_csrf["\']?\s*[:=]\s*["\']([^"\']+)',
                    r.text or "",
                )
                if m:
                    csrf = m.group(1)
                if csrf:
                    break
            except requests.RequestException as e:
                logger.debug("[%s] 登录页失败 %s: %s", acc.name, page, e)

        # 2) 常见 newlogin 接口
        endpoints = [
            "https://account.aliyun.com/newlogin/login.do",
            "https://passport.aliyun.com/newlogin/login.do",
            "https://accounts.aliyun.com/newlogin/login.do",
        ]
        # 密码：明文 + MD5 双尝试
        pwd_plain = acc.password
        pwd_md5 = hashlib.md5(pwd_plain.encode("utf-8")).hexdigest()

        bodies = [
            {
                "loginId": login_id,
                "password": pwd_plain,
                "appName": "aliyun",
                "appEntrance": "default",
                "umidToken": "",
                "isMobile": "true" if re.fullmatch(r"1\d{10}", login_id) else "false",
            },
            {
                "loginId": login_id,
                "password2": pwd_md5,
                "appName": "aliyun",
                "appEntrance": "default",
            },
            {
                "login_id": login_id,
                "password": pwd_plain,
                "login_aliyunid_csrf": csrf,
            },
        ]

        last_msg = "未知错误"
        for ep in endpoints:
            for body in bodies:
                try:
                    headers = {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Origin": "https://account.aliyun.com",
                        "Referer": "https://account.aliyun.com/login/login.htm",
                        "X-Requested-With": "XMLHttpRequest",
                    }
                    if csrf:
                        headers["X-XSRF-TOKEN"] = csrf
                        body = dict(body)
                        body.setdefault("login_aliyunid_csrf", csrf)
                        body.setdefault("_csrf", csrf)

                    resp = self.session.post(
                        ep,
                        data=body,
                        headers=headers,
                        timeout=self.cfg.timeout,
                        allow_redirects=True,
                    )
                    text = resp.text or ""
                    logger.debug(
                        "[%s] login %s → %s %s",
                        acc.name,
                        ep,
                        resp.status_code,
                        text[:200],
                    )

                    # 解析 JSON
                    data: Any = None
                    try:
                        data = resp.json()
                    except Exception:
                        if text.strip().startswith("{"):
                            try:
                                data = json.loads(text)
                            except Exception:
                                data = None

                    if isinstance(data, dict):
                        # 阿里风控：rgv587 / sm 滑块页
                        if data.get("rgv587_flag") or "bixi.alicdn.com/punish" in text:
                            last_msg = (
                                "密码登录触发滑块/风控（rgv587），无法自动完成。"
                                "请在浏览器或 APP 登录后，把 Cookie 写到 config.yaml 的 cookie 字段"
                                "（或环境变量 aliyunWeb_data / ALIYUN_ACCOUNTS.token）"
                            )
                            logger.warning("[%s] ⚠️ %s", acc.name, last_msg)
                            return {
                                "ok": False,
                                "via": "password",
                                "message": last_msg,
                                "need_captcha": True,
                            }
                        content = data.get("content") or data.get("data") or data
                        if isinstance(content, dict):
                            # 成功标志
                            if content.get("success") or content.get("hasError") is False:
                                if self._after_login_probe():
                                    logger.info("[%s] ✅ 密码登录成功", acc.name)
                                    return {
                                        "ok": True,
                                        "via": "password",
                                        "message": "登录成功",
                                    }
                            title = str(
                                content.get("titleMsg")
                                or content.get("msg")
                                or content.get("message")
                                or data.get("message")
                                or ""
                            )
                            if title:
                                last_msg = title
                            # captcha
                            if any(
                                w in (title + text)
                                for w in ("滑块", "验证码", "captcha", "二次验证", "短信")
                            ):
                                last_msg = f"需要验证码/滑块：{title or '请改用 Cookie'}"
                                logger.warning("[%s] ⚠️ %s", acc.name, last_msg)
                                return {
                                    "ok": False,
                                    "via": "password",
                                    "message": last_msg,
                                    "need_captcha": True,
                                }

                    # Cookie 侧成功判定
                    if self._has_login_ticket() and self._after_login_probe():
                        logger.info("[%s] ✅ 密码登录成功（Cookie）", acc.name)
                        return {
                            "ok": True,
                            "via": "password",
                            "message": "登录成功",
                        }

                    # 从 HTML 提取错误
                    m = re.search(
                        r"密码错误|账号不存在|用户名或密码| ass|验证码|冻结",
                        text,
                    )
                    if m:
                        last_msg = m.group(0)
                except requests.RequestException as e:
                    last_msg = str(e)
                    logger.debug("[%s] login err: %s", acc.name, e)

        # 再探一次 developer 域
        try:
            self.session.get(BASE + "/", timeout=self.cfg.timeout)
            self.session.get(f"{API}/my/user/getUser", timeout=self.cfg.timeout)
        except requests.RequestException:
            pass
        if self._session_alive():
            logger.info("[%s] ✅ 密码登录后会话可用", acc.name)
            return {"ok": True, "via": "password", "message": "登录成功"}

        msg = (
            f"密码登录失败：{last_msg}。"
            "阿里云常强制滑块/短信，建议浏览器登录 developer.aliyun.com 后把 Cookie "
            "写入配置（或 aliyunWeb_data）。"
        )
        logger.error("[%s] ❌ %s", acc.name, msg)
        return {"ok": False, "via": "password", "message": msg}

    def _has_login_ticket(self) -> bool:
        names = {c.name for c in self.session.cookies}
        return any(
            "login_aliyunid" in n or "aliyun_login" in n or "ticket" in n.lower()
            for n in names
        )

    def _after_login_probe(self) -> bool:
        try:
            self.session.get(
                BASE + "/",
                timeout=self.cfg.timeout,
                headers={"Referer": "https://account.aliyun.com/"},
            )
            return self._session_alive()
        except Exception:
            return False

    # ----- 业务 API -----

    def get_user_score(self) -> Optional[int]:
        try:
            data = self.request(
                "GET", f"{API}/my/score/getUserScore", params={"appCode": "developer"}
            )
            if not isinstance(data, dict):
                return None
            d = data.get("data")
            if isinstance(d, (int, float)):
                return int(d)
            if isinstance(d, dict) and "score" in d:
                return int(d.get("score") or 0)
            if data.get("code") in (200, "200", 0, "0") and d is not None:
                try:
                    return int(d)
                except (TypeError, ValueError):
                    pass
            return None
        except Exception as e:
            logger.debug("[%s] getUserScore: %s", self.account.name, e)
            return None

    def get_pending_score(self) -> Optional[int]:
        try:
            data = self.request(
                "GET",
                f"{API}/score/pending/getUserTotalPendingScore",
                params={"appCode": "developer"},
            )
            if isinstance(data, dict) and data.get("data") is not None:
                return int(data.get("data") or 0)
        except Exception as e:
            logger.debug("[%s] pending: %s", self.account.name, e)
        return None

    def receive_all_pending(self) -> dict[str, Any]:
        try:
            data = self.request(
                "GET",
                f"{API}/score/pending/receiveAllPendingScore",
                params={"appCode": "developer"},
            )
            got = None
            if isinstance(data, dict):
                got = data.get("data")
                msg = str(data.get("message") or data.get("msg") or "")
                ok = data.get("code") in (200, "200", 0, "0", None) or bool(got)
                if got is not None:
                    try:
                        self.stats["score_got"] = int(got)
                    except (TypeError, ValueError):
                        pass
                logger.info(
                    "[%s] 🎉 领取待收积分：%s",
                    self.account.name,
                    got if got is not None else msg or data,
                )
                return {"ok": ok, "got": got, "message": msg}
        except Exception as e:
            logger.warning("[%s] 领取待收积分失败: %s", self.account.name, e)
        return {"ok": False, "message": "领取失败"}

    def get_sign_detail(self, excode: str) -> Optional[str]:
        """返回 taskGroupId。"""
        try:
            data = self.request(
                "GET",
                f"{API}/sign/getUserSpaceSignInDetail",
                params={"excode": excode},
            )
            if isinstance(data, dict):
                d = data.get("data") or {}
                if isinstance(d, dict):
                    tid = d.get("taskGroupId")
                    return str(tid) if tid is not None else None
        except Exception as e:
            logger.debug("[%s] sign detail %s: %s", self.account.name, excode, e)
        return None

    def get_tasks(self, group_id: str) -> dict[str, Any]:
        """解析当日签到任务（字段为 gmtStart/gmtEnd，不是 startTime）。"""
        try:
            data = self.request(
                "GET", f"{API}/task/getTaskGroup", params={"groupId": group_id}
            )
            if not isinstance(data, dict):
                return {}
            d = data.get("data") or {}
            task_list = d.get("taskList") or []
            now = int(time.time() * 1000)
            for t in task_list:
                if not isinstance(t, dict):
                    continue
                try:
                    st = int(
                        t.get("gmtStart")
                        or t.get("gmtEnableStart")
                        or t.get("startTime")
                        or 0
                    )
                    et = int(
                        t.get("gmtEnd")
                        or t.get("gmtEnableEnd")
                        or t.get("endTime")
                        or 0
                    )
                except (TypeError, ValueError):
                    continue
                if st and et and not (st <= now <= et):
                    continue
                fr = str(t.get("finishRule") or "").replace("&quot;", '"')
                try:
                    rule = json.loads(fr)
                    actions = rule.get("actions") or []
                    if not actions:
                        continue
                    a0 = actions[0]
                    out: dict[str, Any] = {
                        "actionCode": a0.get("actionCode") or a0.get("code"),
                        "objectId": a0.get("objectId"),
                    }
                    if a0.get("bizCategory"):
                        out["bizCategory"] = a0.get("bizCategory")
                    return out
                except Exception:
                    continue
            return {}
        except Exception as e:
            logger.debug("[%s] getTasks: %s", self.account.name, e)
            return {}

    def signin(self, task_body: dict[str, Any], name: str) -> bool:
        if not task_body:
            logger.info("[%s] ✅ 签到 - %s: 该社区无签到任务", self.account.name, name)
            self.stats["sign_skip"] += 1
            return True
        try:
            data = self.request(
                "POST",
                f"{API}/task/actionLog",
                json_body=task_body,
                headers={"Content-Type": "application/json;charset=UTF-8"},
            )
            msg = ""
            ok = False
            if isinstance(data, dict):
                msg = str(data.get("message") or data.get("msg") or "")
                code = str(data.get("code") or "")
                ok = data.get("success") is True or code in ("200", "0")
                # 已签到也算成功
                if any(w in msg for w in ("已完成", "已签", "重复", "已经")):
                    ok = True
            if ok:
                logger.info(
                    "[%s] ✅ 签到 - %s: %s", self.account.name, name, msg or "OK"
                )
                self.stats["sign_ok"] += 1
                return True
            logger.info(
                "[%s] ℹ️ 签到 - %s: %s",
                self.account.name,
                name,
                msg or data,
            )
            self.stats["sign_skip"] += 1
            return False
        except Exception as e:
            logger.warning("[%s] ⛔️ 签到失败 %s: %s", self.account.name, name, e)
            return False

    def assess_bonus(self, group_id: str) -> bool:
        try:
            data = self.request(
                "GET",
                f"{API}/sign/assessSignInBonusQualification",
                params={"taskGroupId": group_id},
            )
            if isinstance(data, dict):
                return bool(data.get("data"))
        except Exception:
            pass
        return False

    def receive_bonus(self, group_id: str, name: str) -> bool:
        try:
            data = self.request(
                "POST",
                f"{API}/sign/receiveSignInBonus",
                json_body={"taskGroupId": group_id},
                headers={"Content-Type": "application/json;charset=UTF-8"},
            )
            if isinstance(data, dict):
                code = str(data.get("code") or "")
                pts = data.get("data")
                msg = str(data.get("message") or "")
                if code in ("200", "0") or pts is not None:
                    logger.info(
                        "[%s] 🎁 签到奖 %s: 获得 %s 积分",
                        self.account.name,
                        name,
                        pts if pts is not None else msg,
                    )
                    if isinstance(pts, (int, float)):
                        self.stats["score_got"] = int(
                            self.stats.get("score_got") or 0
                        ) + int(pts)
                    return True
                logger.info(
                    "[%s] 🎁 签到奖 %s: %s", self.account.name, name, msg or data
                )
        except Exception as e:
            logger.warning("[%s] 签到奖失败 %s: %s", self.account.name, name, e)
        return False

    def get_csrf(self, referer_path: str = "") -> str:
        try:
            headers = {}
            if referer_path:
                headers["Referer"] = f"{BASE}/{referer_path}"
            data = self.request("GET", f"{BASE}/csrfToken", headers=headers)
            if isinstance(data, dict) and data.get("token"):
                return str(data["token"])
            # cookie 里找
            for c in self.session.cookies:
                if c.name in ("c_csrf", "h_csrf") and c.value:
                    return c.value
        except Exception as e:
            logger.debug("[%s] csrf: %s", self.account.name, e)
        m = re.search(r"c_csrf=([^;]+)", cookie_header(self.session))
        return m.group(1) if m else ""

    def get_ucc_csrf(self) -> str:
        try:
            cb = f"jsonp_{int(time.time() * 1000)}_{random.randint(10000, 99999)}"
            data = self.request(
                "GET",
                f"{UCC}/uccPagingComponent/getUser",
                params={"uccCsrfToken": "", "callback": cb},
                headers={"Referer": f"{BASE}/"},
            )
            raw = ""
            if isinstance(data, dict) and data.get("_raw"):
                raw = str(data["_raw"])
            elif isinstance(data, dict):
                # 可能已是 json
                d = data.get("data") or {}
                if isinstance(d, dict) and d.get("uccCsrfToken"):
                    return str(d["uccCsrfToken"])
            text = raw or json.dumps(data, ensure_ascii=False)
            i, j = text.find("{"), text.rfind("}")
            if i >= 0 and j > i:
                obj = json.loads(text[i : j + 1])
                tok = (obj.get("data") or {}).get("uccCsrfToken")
                if tok:
                    return str(tok)
        except Exception as e:
            logger.debug("[%s] ucc csrf: %s", self.account.name, e)
        return ""

    def like_or_not(
        self, object_id: str, action_code: str, status: int
    ) -> bool:
        """
        action_code: 点赞/收藏/分享 对应业务码
        status: 0=操作 1=取消
        """
        try:
            ucc = self.get_ucc_csrf()
            cb = f"jsonp_{int(time.time() * 1000)}_{random.randint(10000, 99999)}"
            self.request(
                "GET",
                f"{UCC}/uccPagingComponent/likeOrNotLike",
                params={
                    "bizCategory": "yq-article",
                    "actionCode": action_code,
                    "objectId": object_id,
                    "status": status,
                    "uccCsrfToken": ucc,
                    "callback": cb,
                },
                headers={"Referer": f"{BASE}/"},
            )
            label = {
                "aliyun-public-like": "点赞",
                "aliyun-public-favorite": "收藏",
                "aliyun-public-share": "分享",
            }.get(action_code, action_code)
            op = "取消" if status == 1 else ""
            logger.info(
                "[%s] ✅ 文章%s%s: %s",
                self.account.name,
                op,
                label,
                object_id,
            )
            if status == 0:
                if "like" in action_code:
                    self.stats["like"] += 1
                elif "favorite" in action_code:
                    self.stats["fav"] += 1
                elif "share" in action_code:
                    self.stats["share"] += 1
            return True
        except Exception as e:
            logger.warning("[%s] 互动失败: %s", self.account.name, e)
            return False

    def add_comment(self, object_id: str) -> bool:
        try:
            ucc = self.get_ucc_csrf()
            cb = f"jsonp_{int(time.time() * 1000)}_{random.randint(10000, 99999)}"
            content = quote("学习了，感谢分享", safe="")
            self.request(
                "GET",
                f"{UCC}/uccPagingComponent/addComment",
                params={
                    "content": content,
                    "objectId": object_id,
                    "bizCategory": "yq-comment-type-article",
                    "commentType": 0,
                    "sourceAppCode": "developer",
                    "sourceBizCategory": "yq-article",
                    "uccCsrfToken": ucc,
                    "callback": cb,
                },
                headers={"Referer": f"{BASE}/"},
            )
            logger.info("[%s] ✅ 文章评论: %s", self.account.name, object_id)
            self.stats["comment"] += 1
            return True
        except Exception as e:
            logger.warning("[%s] 评论失败: %s", self.account.name, e)
            return False

    def get_hot_article_id(self) -> Optional[str]:
        """从热门文章页解析 data-id。"""
        try:
            page = random.randint(1, 5)
            data = self.request(
                "GET",
                f"{BASE}/group/aliware/article_hot",
                params={"pageNum": page},
            )
            html = ""
            if isinstance(data, dict):
                html = str(data.get("_raw") or "")
            ids = re.findall(r'data-id=["\'](\d+)["\']', html)
            if not ids:
                # 备用：API 列表
                return None
            aid = random.choice(ids)
            logger.info("[%s] ✅ 随机文章 id: %s", self.account.name, aid)
            return aid
        except Exception as e:
            logger.debug("[%s] get article: %s", self.account.name, e)
            return None

    def get_favors(self) -> list[dict[str, Any]]:
        try:
            data = self.request(
                "GET",
                f"{API}/my/subscribe/listUserFavor",
                params={"pageNum": 1, "pageSize": 10, "type": 1},
            )
            if isinstance(data, dict):
                d = data.get("data") or {}
                lst = d.get("list") if isinstance(d, dict) else None
                if isinstance(lst, list):
                    return [x for x in lst if isinstance(x, dict)]
        except Exception as e:
            logger.debug("[%s] favors: %s", self.account.name, e)
        return []

    def list_stock(self) -> None:
        try:
            data = self.request(
                "GET",
                f"{API}/lm/getGroupItems",
                params={"pageNum": 1, "pageSize": 50},
            )
            if not isinstance(data, dict):
                return
            d = data.get("data") or {}
            lst = d.get("list") if isinstance(d, dict) else None
            if not lst:
                return
            logger.info("[%s] 📦 积分商城库存：", self.account.name)
            for it in lst[:20]:
                if not isinstance(it, dict):
                    continue
                title = re.sub(
                    r"【.*?】", "", str(it.get("itemTitle") or "")
                )
                logger.info(
                    "   🎁 %s: %s【库存 %s】",
                    title,
                    it.get("points") or it.get("itemPoints"),
                    it.get("stock") or it.get("itemStock"),
                )
        except Exception as e:
            logger.debug("[%s] stock: %s", self.account.name, e)

    # ----- 扩展任务 -----

    def get_hot_article_ids(self, pages: int = 3, limit: int = 12) -> list[str]:
        ids: list[str] = []
        for p in range(1, max(1, pages) + 1):
            try:
                data = self.request(
                    "GET",
                    f"{BASE}/group/aliware/article_hot",
                    params={"pageNum": p},
                )
                html = str(data.get("_raw") or "") if isinstance(data, dict) else ""
                ids.extend(re.findall(r'data-id=["\'](\d+)["\']', html))
            except Exception:
                continue
            self._sleep(0.3, 0.6)
        # 去重保序
        out: list[str] = []
        seen: set[str] = set()
        for i in ids:
            if i not in seen:
                seen.add(i)
                out.append(i)
            if len(out) >= limit:
                break
        return out

    def rate_ebooks(self, count: int = 3) -> int:
        ok_n = 0
        try:
            page = random.randint(1, 8)
            data = self.request(
                "GET", f"{BASE}/ebook/index/__0_0_0_{page}"
            )
            html = str(data.get("_raw") or "") if isinstance(data, dict) else ""
            eids = list(dict.fromkeys(re.findall(r"/ebook/(\d+)", html)))
            for eid in eids[:count]:
                csrf = self.get_csrf(f"ebook/{eid}")
                body = {
                    "eBookId": int(eid),
                    "score": 10,
                    "content": random.choice(
                        ("很棒的一本书", "内容不错值得一读", "受益匪浅感谢分享")
                    ),
                }
                headers = {
                    "Content-Type": "application/json;charset=UTF-8",
                    "Referer": f"{BASE}/ebook/{eid}",
                }
                params = {"p_csrf": csrf} if csrf else None
                r = self.request(
                    "POST",
                    f"{API}/ebook/mark/add",
                    params=params,
                    json_body=body,
                    headers=headers,
                )
                if isinstance(r, dict) and (
                    r.get("success") is True or str(r.get("code")) == "200"
                ):
                    ok_n += 1
                    logger.info("[%s] 📚 评价电子书 %s", self.account.name, eid)
                else:
                    logger.debug(
                        "[%s] ebook %s: %s",
                        self.account.name,
                        eid,
                        r.get("message") if isinstance(r, dict) else r,
                    )
                self._sleep(0.4, 0.8)
        except Exception as e:
            logger.debug("[%s] rate_ebooks: %s", self.account.name, e)
        self.stats["ebook"] = ok_n
        return ok_n

    def vote_asks(self, count: int = 3) -> int:
        ok_n = 0
        try:
            data = self.request("GET", f"{BASE}/ask", params={"pageNum": 1})
            html = str(data.get("_raw") or "") if isinstance(data, dict) else ""
            aids = list(dict.fromkeys(re.findall(r"/ask/(\d+)", html)))
            for aid in aids[:count]:
                page = self.request("GET", f"{BASE}/ask/{aid}")
                ph = str(page.get("_raw") or "") if isinstance(page, dict) else ""
                ans = re.findall(r'data-id=["\'](\d+)["\']', ph)
                csrf = self.get_csrf(f"ask/{aid}")
                if not ans or not csrf:
                    continue
                r = self.request(
                    "POST",
                    f"{API}/my/ask/voteAnswer",
                    params={"p_csrf": csrf},
                    json_body={"id": int(ans[0]), "votes": 1},
                    headers={
                        "Content-Type": "application/json;charset=UTF-8",
                        "Referer": f"{BASE}/ask/{aid}",
                    },
                )
                if isinstance(r, dict) and (
                    r.get("success") is True or str(r.get("code")) == "200"
                ):
                    ok_n += 1
                    logger.info(
                        "[%s] 👍 问答点赞 ask=%s ans=%s",
                        self.account.name,
                        aid,
                        ans[0],
                    )
                self._sleep(0.4, 0.8)
        except Exception as e:
            logger.debug("[%s] vote_asks: %s", self.account.name, e)
        self.stats["ask_vote"] = ok_n
        return ok_n

    def do_scene_once(self) -> bool:
        """轻量体验一个实验场景（开始即记分相关）。"""
        try:
            r = self.request(
                "GET",
                "https://developer.aliyun.com/adc/api/getSceneList",
                params={
                    "tags": ",",
                    "difficulty": "",
                    "orderBy": "1",
                    "pageNum": str(random.randint(1, 5)),
                    "pageSize": "10",
                },
                headers={"Referer": "https://developer.aliyun.com/adc/labs/"},
            )
            lst = ((r or {}).get("data") or {}).get("list") if isinstance(r, dict) else None
            if not lst:
                return False
            scene = random.choice(lst)
            sid = str(scene.get("id") or "")
            if not sid:
                return False
            csrf = ""
            for pair in (self.account.cookie or "").split(";"):
                if "c_csrf=" in pair:
                    csrf = pair.split("=", 1)[1].strip()
                    break
            if not csrf:
                csrf = self.get_csrf()
            self.request(
                "GET",
                "https://developer.aliyun.com/adc/api/getSceneStartPageInfoById",
                params={"id": sid},
                headers={
                    "Referer": f"https://developer.aliyun.com/adc/scenario/exp/{sid}"
                },
            )
            self._sleep(0.5, 1.0)
            start = self.request(
                "POST",
                "https://developer.aliyun.com/adc/api/startSceneById",
                params={"p_csrf": csrf} if csrf else None,
                data={"id": sid, "resourceFrom": "2"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "H_csrf": csrf,
                    "X-XSRF-TOKEN": csrf,
                    "Referer": f"https://developer.aliyun.com/adc/scenario/exp/{sid}",
                },
            )
            ok = isinstance(start, dict) and (
                start.get("success") is True or str(start.get("code")) == "200"
            )
            logger.info(
                "[%s] 🧪 场景体验 %s: %s",
                self.account.name,
                (scene.get("name") or sid)[:30],
                "OK" if ok else start,
            )
            self._sleep(1.0, 2.0)
            # 尝试结束（失败可忽略）
            try:
                self.request(
                    "POST",
                    "https://developer.aliyun.com/adc/api/closeSceneById",
                    params={"p_csrf": csrf} if csrf else None,
                    json_body={"sceneId": sid, "forceClose": "true"},
                    headers={
                        "Content-Type": "application/json;charset=UTF-8",
                        "H_csrf": csrf,
                        "X-XSRF-TOKEN": csrf,
                        "Referer": f"https://developer.aliyun.com/adc/scenario/exp/{sid}",
                    },
                )
            except Exception:
                pass
            self.stats["scene"] = 1 if ok else 0
            return ok
        except Exception as e:
            logger.debug("[%s] scene: %s", self.account.name, e)
            return False

    def do_video_once(self) -> bool:
        """轻量视频/直播心跳。"""
        try:
            page = self.request("GET", f"{BASE}/live/")
            html = str(page.get("_raw") or "") if isinstance(page, dict) else ""
            vids = list(dict.fromkeys(re.findall(r"/live/(\d+)", html)))
            if not vids:
                vids = ["254876"]
            vid = random.choice(vids[:8])
            cb = f"jsonp_{int(time.time() * 1000)}"
            for path in ("detail", "view", "play", "online"):
                params: dict[str, Any] = {
                    "_": str(int(time.time() * 1000)),
                    "callback": cb,
                    "version": "1.1.23",
                    "id": vid,
                }
                if path in ("play", "online", "view"):
                    params["sessionId"] = hashlib.md5(
                        f"{vid}{time.time()}".encode()
                    ).hexdigest()[:16]
                self.request(
                    "GET",
                    f"{UCC}/api/ucc/live/open/{path}",
                    params=params,
                    headers={"Referer": f"{BASE}/live/{vid}"},
                )
                self._sleep(0.2, 0.4)
            logger.info("[%s] 🎬 视频/直播心跳 live=%s", self.account.name, vid)
            self.stats["video"] = 1
            return True
        except Exception as e:
            logger.debug("[%s] video: %s", self.account.name, e)
            return False

    # ----- 流程 -----

    def run_earn_tasks(self) -> None:
        """
        赚分任务（每次运行都做，不限上下午）：
        签到 → 文章互动 → 电子书 → 问答 → 可选场景/视频 → 收待领积分
        """
        logger.info("[%s] 🎯 赚分任务开始", self.account.name)
        score_before = self.get_user_score()
        self.stats["score_before"] = score_before

        # 1) 多社区签到 + 领签到奖
        for g in TASK_GROUPS:
            gid = self.get_sign_detail(g["code"])
            if not gid:
                self.stats["sign_skip"] += 1
                continue
            tasks = self.get_tasks(gid)
            self.signin(tasks, g["name"])
            self._sleep(0.6, 1.2)
            if self.assess_bonus(gid):
                self.receive_bonus(gid, g["name"])
                self._sleep(0.5, 1.0)

        # 2) 文章：点赞/收藏/分享/评论（加量）
        article_ids = self.get_hot_article_ids(pages=3, limit=8)
        logger.info(
            "[%s] 📝 文章互动 %d 篇", self.account.name, len(article_ids)
        )
        for i, aid in enumerate(article_ids):
            self.like_or_not(aid, "aliyun-public-like", 0)
            self._sleep(0.35, 0.7)
            self.like_or_not(aid, "aliyun-public-favorite", 0)
            self._sleep(0.35, 0.7)
            self.like_or_not(aid, "aliyun-public-share", 0)
            self._sleep(0.35, 0.7)
            # 前 3 篇评论（评论需审核，积分可能延迟到待领取）
            if i < 3:
                self.add_comment(aid)
                self._sleep(0.5, 1.0)

        # 3) 电子书评价
        self.rate_ebooks(count=3)
        self._sleep(0.5, 1.0)

        # 4) 问答点赞
        self.vote_asks(count=3)
        self._sleep(0.5, 1.0)

        # 5) 场景 / 视频（默认开启轻量版，可配置关闭）
        if self.cfg.enable_scene:
            self.do_scene_once()
            self._sleep(0.5, 1.0)
        if self.cfg.enable_video:
            self.do_video_once()
            self._sleep(0.5, 1.0)

        if self.cfg.enable_stock:
            self.list_stock()

        # 6) 收待领取积分（多等一会，互动积分可能延迟入账）
        self._sleep(1.5, 2.5)
        pending_before = self.get_pending_score()
        logger.info("[%s] ⏳ 待领取积分: %s", self.account.name, pending_before)
        for _ in range(3):
            self.receive_all_pending()
            self._sleep(0.8, 1.2)
        pending_after = self.get_pending_score()
        self.stats["pending"] = pending_after

        score = self.get_user_score()
        self.stats["score_now"] = score
        try:
            delta = int(score or 0) - int(score_before or 0)
        except (TypeError, ValueError):
            delta = 0
        self.stats["score_delta"] = delta
        logger.info(
            "[%s] 📊 积分 %s → %s（本次 %+d）· 待领 %s→%s",
            self.account.name,
            score_before,
            score,
            delta,
            pending_before,
            pending_after,
        )

    def run_cleanup(self) -> None:
        """取消点赞/收藏，释放额度（建议下午或赚分后执行）。"""
        logger.info("[%s] 🧹 清理互动记录", self.account.name)
        favors = self.get_favors()
        if not favors:
            logger.info("[%s] 无收藏记录可清理", self.account.name)
            return
        logger.info("[%s] 取消收藏/点赞 %d 条", self.account.name, len(favors))
        for it in favors:
            oid = str(
                it.get("objectId") or it.get("id") or it.get("articleId") or ""
            )
            if not oid:
                continue
            self.like_or_not(oid, "aliyun-public-like", 1)
            self._sleep(0.35, 0.7)
            self.like_or_not(oid, "aliyun-public-favorite", 1)
            self._sleep(0.35, 0.7)

    def run(self, *, force_phase: Optional[str] = None) -> dict[str, Any]:
        acc = self.account
        result: dict[str, Any] = {
            "ok": False,
            "name": acc.name,
            "message": "",
            "via": "",
            "phase": "",
            "stats": {},
        }

        auth = self.ensure_session()
        result["via"] = str(auth.get("via") or "")
        if not auth.get("ok"):
            result["message"] = str(auth.get("message") or "鉴权失败")
            return result

        if self.cfg.dry_run:
            score = self.get_user_score()
            result["ok"] = score is not None
            result["message"] = (
                f"dry-run 积分={score}" if result["ok"] else "dry-run 会话无效"
            )
            result["stats"] = {"score_now": score}
            return result

        # am = 只赚分（含领待收积分）；pm/full/auto = 赚分 + 清理互动
        # 默认 auto 固定完整版，方便 7 点 / 13 点同一套 cron
        if force_phase == "am":
            phase = "am"
        elif force_phase in ("pm", "full"):
            phase = force_phase
        else:
            phase = "full"

        result["phase"] = phase
        try:
            # 完整版核心：签到/互动/… + 领取待收积分（金币）
            self.run_earn_tasks()
            if phase in ("pm", "full"):
                self.run_cleanup()
            result["ok"] = True
            delta = self.stats.get("score_delta") or 0
            result["message"] = (
                f"完整任务完成 · 积分 {self.stats.get('score_now')}（{delta:+d}）"
            )
        except Exception as e:
            result["message"] = str(e)
            logger.error("[%s] 💥 任务异常: %s", acc.name, e)
            result["ok"] = (
                self.stats.get("sign_ok", 0) > 0
                or self.stats.get("score_got", 0) > 0
                or int(self.stats.get("score_delta") or 0) > 0
            )

        result["stats"] = dict(self.stats)
        return result


# ---------------------------------------------------------------------------
# 通知
# ---------------------------------------------------------------------------

def format_summary(account_results: list[tuple[str, dict[str, Any]]]) -> str:
    lines: list[str] = []
    lines.append(f"📅 {datetime.now().strftime('%m-%d %H:%M')}")
    lines.append("")
    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    fail_n = len(account_results) - ok_n

    for i, (name, r) in enumerate(account_results):
        ok = bool(r.get("ok"))
        st = r.get("stats") or {}
        phase = r.get("phase") or ""
        lines.append(f"{'✅' if ok else '❌'} {name}")
        if phase:
            phase_map = {"am": "赚分", "pm": "赚分+清理", "full": "赚分+清理"}
            lines.append(f"   🕐 模式：{phase_map.get(phase, phase)}")
        if st.get("sign_ok") or st.get("sign_skip"):
            lines.append(
                f"   ✍️ 签到：成功 {st.get('sign_ok') or 0} · 跳过 {st.get('sign_skip') or 0}"
            )
        inter = []
        if st.get("like"):
            inter.append(f"赞{st['like']}")
        if st.get("fav"):
            inter.append(f"藏{st['fav']}")
        if st.get("share"):
            inter.append(f"享{st['share']}")
        if st.get("comment"):
            inter.append(f"评{st['comment']}")
        if st.get("ebook"):
            inter.append(f"书{st['ebook']}")
        if st.get("ask_vote"):
            inter.append(f"问{st['ask_vote']}")
        if st.get("scene"):
            inter.append("场景")
        if st.get("video"):
            inter.append("视频")
        if inter:
            lines.append(f"   👍 互动：{'/'.join(inter)}")
        if st.get("score_got"):
            lines.append(f"   🎁 领取入账：{st['score_got']} 分")
        if st.get("score_delta") is not None:
            lines.append(f"   📈 本次变化：{int(st.get('score_delta') or 0):+d}")
        if st.get("pending") is not None:
            lines.append(f"   ⏳ 待领取：{st['pending']}")
        if st.get("score_now") is not None:
            lines.append(f"   💰 当前积分：{st['score_now']}")
        via = str(r.get("via") or "")
        if via:
            via_map = {
                "password": "密码登录",
                "cookie": "Cookie",
                "cache": "缓存会话",
            }
            lines.append(f"   🔐 {via_map.get(via, via)}")
        if not ok and r.get("message"):
            msg = str(r["message"])
            lines.append(f"   ⚠️ {msg[:120]}")
        if i < len(account_results) - 1:
            lines.append("")

    lines.append("")
    lines.append("────────")
    if fail_n == 0:
        lines.append(f"📊 合计：{ok_n}/{len(account_results)} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：0/{len(account_results)} 全部失败")
    else:
        lines.append(
            f"📊 合计：成功 {ok_n} · 失败 {fail_n}（共 {len(account_results)} 号）"
        )
    return "\n".join(lines)


def format_notify_title(account_results: list[tuple[str, dict[str, Any]]]) -> str:
    ok_n = sum(1 for _, r in account_results if r.get("ok"))
    n = len(account_results)
    if n == 0:
        return "阿里云社区"
    if ok_n == n:
        return f"阿里云社区 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"阿里云社区 ❌ 0/{n}"
    return f"阿里云社区 ⚠️ {ok_n}/{n}"


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
        "group": cfg.bark_group or "阿里云社区",
    }
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
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
        url = (
            f"https://{m.group(1)}.push.ft07.com/send/{key}.send"
            if m
            else f"https://sctapi.ftqq.com/{key}.send"
        )
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        requests.post(url, json={"title": title, "desp": content}, timeout=10)
        logger.info("📣 Server酱 已推送")
    except Exception as e:
        logger.warning("📣 Server酱失败: %s", e)


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
            logger.warning("📣 Webhook 失败: %s", e)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def log_banner(title: str) -> None:
    logger.info("──────── %s ────────", title)


def _warn_password_only_accounts(cfg: AppConfig) -> None:
    """无 Cookie 仅密码时提前提醒，避免用户误以为「脚本坏了」。"""
    for acc in cfg.accounts:
        if acc.has_cookie():
            continue
        if acc.has_password():
            logger.warning(
                "[%s] ⚠️ 当前只配置了账号密码、没有 Cookie。"
                "阿里云密码登录几乎必触发滑块，极可能失败；"
                "请把 Cookie 写到 accounts[].cookie（或环境变量 aliyunWeb_data）。",
                acc.name,
            )


def resolve_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        cfg = load_config_yaml(Path(args.config))
        _warn_password_only_accounts(cfg)
        return cfg
    env_pack = load_config_from_env()
    if env_pack is not None:
        env_cfg, source = env_pack
        for acc in env_cfg.accounts:
            ck_len = len(acc.cookie)
            logger.info(
                "📦 环境变量 %s → 账号 [%s] auth=%s cookie长度=%d",
                source,
                acc.name,
                acc.auth_label(),
                ck_len,
            )
        local = SCRIPT_DIR / "config.yaml"
        if local.is_file():
            logger.warning(
                "📦 本地存在 %s，但环境变量优先，config.yaml 不会被读取。"
                "若要用本地 Cookie：unset %s 后重跑。",
                local,
                source,
            )
        _warn_password_only_accounts(env_cfg)
        return env_cfg
    local = SCRIPT_DIR / "config.yaml"
    if local.is_file():
        logger.info("📦 使用本地配置: %s", local)
        cfg = load_config_yaml(local)
        _warn_password_only_accounts(cfg)
        return cfg
    raise FileNotFoundError(
        "未找到账号配置。\n"
        "青龙：ALIYUN_ACCOUNTS（推荐含 cookie/token）或 aliyunWeb_data=Cookie\n"
        "本地：config.yaml 里 accounts[].cookie=整段Cookie\n"
        "注意：仅 username+password 会被滑块拦截，不能当主登录方式"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="阿里云开发者社区日常任务")
    parser.add_argument("-c", "--config", help="本地 yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只验登录/积分")
    parser.add_argument(
        "--phase",
        choices=("auto", "am", "pm", "full"),
        default="auto",
        help="auto/full=完整版(赚分+领积分+清理)；am=只赚分领积分；pm=同完整版",
    )
    parser.add_argument("--login-only", action="store_true", help="只登录")
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("❌ %s", e)
        return 2

    if args.dry_run:
        cfg.dry_run = True

    logger.info("☁️ 阿里云开发者社区")
    logger.info(
        "   账号 %d · 分界 %d 点 · 场景 %s · 视频 %s · 通知 %s%s",
        len(cfg.accounts),
        cfg.split_hour,
        "开" if cfg.enable_scene else "关",
        "开" if cfg.enable_video else "关",
        "开" if cfg.notify.enabled() else "关",
        " · DRY_RUN" if cfg.dry_run else "",
    )

    cache = load_session_cache()
    account_results: list[tuple[str, dict[str, Any]]] = []

    for i, acc in enumerate(cfg.accounts):
        log_banner(f"👤 {acc.name}")
        logger.info("[%s] 🔐 鉴权配置：%s", acc.name, acc.auth_label())
        try:
            client = AliyunDevClient(acc, cfg, cache)
            if args.login_only:
                auth = client.ensure_session()
                result = {
                    "ok": bool(auth.get("ok")),
                    "message": auth.get("message") or ("登录成功" if auth.get("ok") else "失败"),
                    "via": auth.get("via") or "",
                    "phase": "",
                    "stats": {"score_now": client.get_user_score() if auth.get("ok") else None},
                }
            else:
                force = None if args.phase == "auto" else args.phase
                result = client.run(force_phase=force)
        except Exception as e:
            logger.error("[%s] 💥 %s", acc.name, e)
            logger.debug("traceback", exc_info=True)
            result = {"ok": False, "message": str(e), "via": "error", "stats": {}}

        if result.get("ok"):
            logger.info("[%s] ✅ %s", acc.name, result.get("message") or "OK")
        else:
            logger.error("[%s] ❌ %s", acc.name, result.get("message") or "失败")

        account_results.append((acc.name, result))
        if i < len(cfg.accounts) - 1:
            time.sleep(max(0.0, cfg.inter_account_delay))

    summary = format_summary(account_results)
    title = format_notify_title(account_results)
    logger.info("")
    log_banner("执行结果")
    for line in summary.splitlines():
        logger.info("%s", line)
    send_notify(cfg.notify, title, summary)

    return 1 if any(not r.get("ok") for _, r in account_results) else 0


if __name__ == "__main__":
    sys.exit(main())
