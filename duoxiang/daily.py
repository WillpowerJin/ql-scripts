#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多象 签到 / 领活跃收益 / 整元提现

cron: 0 10 * * *
new Env('多象签到');

策略：
  1. 手机号+密码登录（HMAC 签名）
  2. 每日签到
  3. 领取昨天/前天活跃收益
  4. 余额按整元自动提现（可关；需支付宝+实名）
  5. 结果可推送 Bark / Server酱 / Webhook

青龙环境变量（账号）：
  DX_ACCOUNTS  推荐。JSON 数组
    [{"name":"主号","phone":"138...","password":"..."}]
  或兼容原脚本：
    DX = 手机号#密码，多账号用 @ 或 & 或换行
  或平行变量（& 分隔）：
    DX_USER / DX_PHONE + DX_PASS / DX_PASSWORD + DX_NAME

青龙环境变量（Bark，与仓库其它脚本共用）：
  BARK_URL / BARK_KEY / BARK_SERVER / BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

可选：
  DX_WITHDRAW=0           关闭自动提现（默认开）
  DX_TIMEOUT / DX_MAX_RETRIES / DX_RETRY_INTERVAL
  DX_INTER_ACCOUNT_DELAY_MIN / MAX   账号间隔秒（默认 30~60）
  DX_DEVICE_ID / DX_UA / DX_VERSION
  DX_TOKEN_CACHE          token 缓存路径
  SERVERCHAN_KEY / WEBHOOK_URL
  DRY_RUN=1               只登录+查资料，不签到/领奖/提现

依赖：requests
  青龙：依赖管理添加 requests
  本地 yaml：再装 PyYAML

注册：https://dx.qqdd.top/i/fWT7zC
逻辑来源：多象全自动.py（ql.xmox.cn）
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import random
import secrets
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests

cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 与 origin 一致：混淆还原后为固定 HMAC 密钥
_OBF_BYTES = [
    0x39, 0x28, 0x32, 0x25, 0x34, 0x3C, 0x33, 0x3A, 0x2, 0x3C, 0x33,
    0x39, 0x2F, 0x32, 0x34, 0x39, 0x2, 0x2F, 0x38, 0x2C, 0x28, 0x38,
    0x2E, 0x29, 0x2, 0x2E, 0x34, 0x3A, 0x33, 0x2, 0x2B, 0x6C,
]
SECRET = "".join(chr(b ^ 0x5D) for b in _OBF_BYTES)
assert SECRET == "duoxiang_android_request_sign_v1"

BASE_URL = "https://dx.qqdd.top"
DEFAULT_DEVICE_ID = "25C1D83B333A1393"
DEFAULT_VERSION = "1.8.2"
DEFAULT_VERSION_CODE = "182"
DEFAULT_UA = "Dart/3.11 (dart:io)"
DEFAULT_BARK_SERVER = "https://api.day.app"
SCRIPT_DIR = Path(__file__).resolve().parent

WITHDRAW_UNIT_FEN = 100
WITHDRAW_MIN_FEN = 100

logger = logging.getLogger("duoxiang")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    phone: str = ""
    password: str = ""
    token: str = ""  # 可选：已有 Bearer token

    def has_password(self) -> bool:
        return bool(self.phone.strip() and self.password)

    def has_token(self) -> bool:
        return bool(self.token.strip())

    def cache_key(self) -> str:
        if self.phone:
            return f"phone:{self.phone.strip()}"
        return f"name:{self.name}"

    def auth_label(self) -> str:
        parts = []
        if self.has_token():
            parts.append("token")
        if self.has_password():
            parts.append("password")
        return "+".join(parts) if parts else "none"

    def normalize(self) -> None:
        self.phone = self.phone.strip()
        self.token = self.token.strip()
        if self.token.lower().startswith("bearer "):
            self.token = self.token[7:].strip()
        if not self.name:
            self.name = self.phone or "account"


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "多象"
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
    withdraw_enabled: bool = True
    timeout: int = 15
    max_retries: int = 3
    retry_interval: int = 10
    inter_account_delay_min: float = 30.0
    inter_account_delay_max: float = 60.0
    delay_after_login_min: float = 5.0
    delay_after_login_max: float = 10.0
    device_id: str = DEFAULT_DEVICE_ID
    user_agent: str = DEFAULT_UA
    version: str = DEFAULT_VERSION
    version_code: str = DEFAULT_VERSION_CODE
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
    """多账号：@ & 换行。"""
    if not value:
        return []
    return [x.strip() for x in re_split_accounts(value) if x.strip()]


def re_split_accounts(value: str) -> list[str]:
    import re

    return re.split(r"[@&\n]", value)


def resolve_token_cache_path() -> Path:
    env = _env("DX_TOKEN_CACHE")
    if env:
        return Path(env).expanduser()
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "duoxiang_token_cache.json"
    return SCRIPT_DIR / "token_cache.json"


def load_token_cache() -> dict[str, Any]:
    path = resolve_token_cache_path()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_token_cache(cache: dict[str, Any]) -> None:
    path = resolve_token_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("💾 token 缓存写入失败: %s", e)


def cache_get_token(cache: dict[str, Any], account: Account) -> str:
    with cache_lock:
        entry = cache.get(account.cache_key()) or {}
        if isinstance(entry, dict):
            return str(entry.get("token") or "")
        return ""


def cache_set_token(cache: dict[str, Any], account: Account, token: str) -> None:
    with cache_lock:
        cache[account.cache_key()] = {
            "token": token,
            "name": account.name,
            "phone": account.phone,
            "ts": int(time.time()),
        }
        save_token_cache(cache)


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("DX_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"DX_ACCOUNTS[{i}] 必须是对象")
        phone = str(item.get("phone") or item.get("username") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        token = str(item.get("token") or "")
        name = str(item.get("name") or phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, token=token)
        acc.normalize()
        if not acc.has_password() and not acc.has_token():
            raise ValueError(f"DX_ACCOUNTS[{i}] 缺少手机号密码或 token")
        accounts.append(acc)
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    # 1) JSON
    accounts_json = _env("DX_ACCOUNTS")
    if accounts_json:
        return _parse_accounts_json(accounts_json)

    # 2) 原脚本 DX=手机号#密码@...
    dx = _env("DX")
    if dx:
        accounts: list[Account] = []
        for i, line in enumerate(_split_multi(dx)):
            if "#" not in line:
                raise ValueError(f"DX 第 {i + 1} 段格式错误，应为 手机号#密码")
            phone, pwd = line.split("#", 1)
            acc = Account(name=phone.strip(), phone=phone.strip(), password=pwd)
            acc.normalize()
            accounts.append(acc)
        return accounts

    # 3) 平行变量
    users = _split_multi(_env("DX_USER") or _env("DX_USERNAME") or _env("DX_PHONE"))
    passes = _split_multi(_env("DX_PASS") or _env("DX_PASSWORD"))
    names = _split_multi(_env("DX_NAME"))
    tokens = _split_multi(_env("DX_TOKEN"))
    n = max(len(users), len(passes), len(tokens))
    if n <= 0:
        return []
    accounts = []
    for i in range(n):
        phone = users[i] if i < len(users) else ""
        pwd = passes[i] if i < len(passes) else ""
        token = tokens[i] if i < len(tokens) else ""
        name = names[i] if i < len(names) else (phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, token=token)
        acc.normalize()
        if not acc.has_password() and not acc.has_token():
            raise ValueError(f"第 {i + 1} 个账号缺少密码或 token")
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
        bark_group=_env("BARK_GROUP", "多象"),
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
    # DX_WITHDRAW：原脚本默认开；0/false 关闭
    withdraw = _env("DX_WITHDRAW", "1").lower() not in ("0", "false", "no", "off")
    return AppConfig(
        accounts=accounts,
        withdraw_enabled=withdraw,
        timeout=int(_env("DX_TIMEOUT", "15")),
        max_retries=int(_env("DX_MAX_RETRIES", "3")),
        retry_interval=int(_env("DX_RETRY_INTERVAL", "10")),
        inter_account_delay_min=float(_env("DX_INTER_ACCOUNT_DELAY_MIN", "30")),
        inter_account_delay_max=float(_env("DX_INTER_ACCOUNT_DELAY_MAX", "60")),
        delay_after_login_min=float(_env("DX_DELAY_AFTER_LOGIN_MIN", "5")),
        delay_after_login_max=float(_env("DX_DELAY_AFTER_LOGIN_MAX", "10")),
        device_id=_env("DX_DEVICE_ID", DEFAULT_DEVICE_ID),
        user_agent=_env("DX_UA", DEFAULT_UA),
        version=_env("DX_VERSION", DEFAULT_VERSION),
        version_code=_env("DX_VERSION_CODE", DEFAULT_VERSION_CODE),
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
        token = str(item.get("token") or "")
        name = str(item.get("name") or phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, token=token)
        acc.normalize()
        if not acc.has_password() and not acc.has_token():
            raise ValueError(f"账号 [{acc.name}] 未配置 phone+password 或 token")
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
        else str(n.get("bark_group") or "多象"),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_notify.serverchan_key
        or str(n.get("serverchan_key") or ""),
        webhook_url=env_notify.webhook_url or str(n.get("webhook_url") or ""),
    )

    withdraw = True
    if _env("DX_WITHDRAW"):
        withdraw = _env("DX_WITHDRAW").lower() not in ("0", "false", "no", "off")
    elif "withdraw_enabled" in raw:
        withdraw = bool(raw.get("withdraw_enabled"))

    return AppConfig(
        accounts=accounts,
        withdraw_enabled=withdraw,
        timeout=int(_env("DX_TIMEOUT") or raw.get("timeout") or 15),
        max_retries=int(_env("DX_MAX_RETRIES") or raw.get("max_retries") or 3),
        retry_interval=int(
            _env("DX_RETRY_INTERVAL") or raw.get("retry_interval") or 10
        ),
        inter_account_delay_min=float(
            _env("DX_INTER_ACCOUNT_DELAY_MIN")
            or raw.get("inter_account_delay_min")
            or 30
        ),
        inter_account_delay_max=float(
            _env("DX_INTER_ACCOUNT_DELAY_MAX")
            or raw.get("inter_account_delay_max")
            or 60
        ),
        delay_after_login_min=float(
            _env("DX_DELAY_AFTER_LOGIN_MIN")
            or raw.get("delay_after_login_min")
            or 5
        ),
        delay_after_login_max=float(
            _env("DX_DELAY_AFTER_LOGIN_MAX")
            or raw.get("delay_after_login_max")
            or 10
        ),
        device_id=_env("DX_DEVICE_ID")
        or str(raw.get("device_id") or DEFAULT_DEVICE_ID),
        user_agent=_env("DX_UA") or str(raw.get("user_agent") or DEFAULT_UA),
        version=_env("DX_VERSION") or str(raw.get("version") or DEFAULT_VERSION),
        version_code=_env("DX_VERSION_CODE")
        or str(raw.get("version_code") or DEFAULT_VERSION_CODE),
        dry_run=_env_bool("DRY_RUN", bool(raw.get("dry_run", False))),
        notify=notify,
    )


# ---------------------------------------------------------------------------
# 签名
# ---------------------------------------------------------------------------

def _nonce() -> str:
    return "".join(format(secrets.randbelow(256), "02x") for _ in range(8))


def _stable_json(obj: Any) -> str:
    def normalize(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: normalize(v) for k, v in sorted(o.items())}
        if isinstance(o, list):
            return [normalize(x) for x in o]
        return o

    return json.dumps(normalize(obj), separators=(",", ":"), ensure_ascii=False)


def _body_hash(body: Any) -> str:
    if body is None:
        return ""
    return hashlib.sha256(_stable_json(body).encode("utf-8")).hexdigest()


def _canonical_query(params: Optional[dict[str, Any]]) -> str:
    if not isinstance(params, dict) or not params:
        return ""
    items = sorted(params.items(), key=lambda kv: (str(kv[0]), str(kv[1])))
    return "&".join(
        f"{quote(str(k), safe='')}"
        f"={quote(str(v), safe='')}"
        for k, v in items
    )


def sign_headers(
    method: str,
    url: str,
    headers: dict[str, str],
    body: Any = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    timestamp = str(int(time.time() * 1000))
    nonce = _nonce()
    path = urlparse(url).path or "/"
    auth = (headers.get("Authorization") or "").strip()
    token = auth[7:].strip() if auth.startswith("Bearer ") else auth
    device_id = (headers.get("X-Device-Id") or "").strip()

    parts = [
        "android",
        timestamp,
        nonce,
        method.upper(),
        path,
        _canonical_query(params),
        _body_hash(body),
        token,
        device_id,
    ]
    signing_string = "\n".join(parts)
    x_sign = hmac.new(
        SECRET.encode("utf-8"),
        signing_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    logger.debug("sign path=%s ts=%s nonce=%s", path, timestamp, nonce)
    return {
        "X-Client-Type": "android",
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Sign": x_sign,
    }


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class DuoXiangClient:
    def __init__(
        self,
        account: Account,
        cfg: AppConfig,
        cache: Optional[dict[str, Any]] = None,
    ):
        self.account = account
        self.cfg = cfg
        self.cache = cache if cache is not None else load_token_cache()
        self.session = requests.Session()
        self.token = ""

    def _base_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.cfg.user_agent,
            "Accept-Encoding": "gzip",
            "Version": self.cfg.version,
            "VersionCode": self.cfg.version_code,
            "X-Device-Os-Version": "9",
            "X-Device-Resolution": "1080x2256",
            "X-Device-Os-Name": "Android",
            "X-Device-Name": "10X",
            "X-Device-Platform": "android",
            "X-Device-Brand": "XIAOMI",
            "X-Device-Manufacturer": "XIAOMI",
            "X-Device-Id": self.cfg.device_id,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        params: Optional[dict[str, Any]] = None,
        need_auth: bool = True,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        headers = self._base_headers()
        if need_auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        headers.update(sign_headers(method, url, headers, body=body, params=params))

        last_err: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_retries + 1):
            try:
                if method.upper() == "GET":
                    resp = self.session.get(
                        url,
                        headers=headers,
                        params=params,
                        timeout=self.cfg.timeout,
                    )
                else:
                    resp = self.session.request(
                        method.upper(),
                        url,
                        headers=headers,
                        json=body,
                        params=params,
                        timeout=self.cfg.timeout,
                    )
                text = (resp.text or "")[:300]
                logger.debug(
                    "[%s] %s %s → HTTP %s %s",
                    self.account.name,
                    method.upper(),
                    path,
                    resp.status_code,
                    text,
                )
                try:
                    data = resp.json()
                except Exception:
                    return {
                        "ok": False,
                        "status": False,
                        "message": f"非 JSON HTTP {resp.status_code}: {text[:120]}",
                        "http": resp.status_code,
                        "raw": text,
                    }
                ok = bool(data.get("status") is True) and resp.status_code == 200
                return {
                    "ok": ok,
                    "status": data.get("status"),
                    "message": str(data.get("message") or ""),
                    "results": data.get("results"),
                    "http": resp.status_code,
                    "raw": data,
                }
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
        return {
            "ok": False,
            "status": False,
            "message": f"网络错误: {last_err}",
            "results": None,
        }

    def ensure_token(self) -> dict[str, Any]:
        acc = self.account
        if acc.has_token():
            self.token = acc.token
            if self._token_alive():
                logger.info("[%s] 🔑 使用配置 token", acc.name)
                return {"ok": True, "via": "token"}
            logger.info("[%s] 🔑 配置 token 失效", acc.name)

        cached = cache_get_token(self.cache, acc)
        if cached:
            self.token = cached
            if self._token_alive():
                logger.info("[%s] 💾 使用缓存 token", acc.name)
                return {"ok": True, "via": "cache"}
            logger.info("[%s] 💾 缓存 token 失效", acc.name)

        if not acc.has_password():
            return {"ok": False, "via": "none", "message": "无 token 且未配置密码"}

        r = self.login()
        if not r.get("ok"):
            return r
        return {"ok": True, "via": "password"}

    def _token_alive(self) -> bool:
        r = self._request("GET", "/api/user/profile")
        return bool(r.get("ok"))

    def login(self) -> dict[str, Any]:
        acc = self.account
        phone_mask = (
            acc.phone[:3] + "****" + acc.phone[-4:]
            if len(acc.phone) >= 7
            else acc.phone
        )
        logger.info("[%s] 📱 登录 %s…", acc.name, phone_mask)
        body = {"phone": acc.phone, "password": acc.password}
        # 登录不需要 Bearer
        self.token = ""
        r = self._request("POST", "/api/user/login", body=body, need_auth=False)
        if not r.get("ok"):
            return {
                "ok": False,
                "via": "password",
                "message": r.get("message") or "登录失败",
            }
        results = r.get("results") or {}
        token = str(results.get("token") or "")
        if not token:
            return {
                "ok": False,
                "via": "password",
                "message": "响应无 token",
            }
        self.token = token
        acc.token = token
        cache_set_token(self.cache, acc, token)
        logger.info("[%s] ✅ 登录成功", acc.name)
        return {"ok": True, "via": "password", "message": "登录成功"}

    def checkin(self) -> dict[str, Any]:
        r = self._request("POST", "/api/growth/checkin", body=None)
        results = r.get("results") or {}
        points = results.get("rewardPoints")
        streak = results.get("streakDays")
        msg = str(r.get("message") or "")
        already = any(w in msg for w in ("已签", "重复", "already", "今天已经"))
        if r.get("ok") or already:
            logger.info(
                "[%s] ✍️ 签到：%s 积分=%s 连续=%s",
                self.account.name,
                msg or "成功",
                points,
                streak,
            )
            return {
                "ok": True,
                "already": already or (not r.get("ok") and already),
                "message": msg or "签到成功",
                "points": points,
                "streak": streak,
            }
        logger.warning("[%s] ✍️ 签到失败：%s", self.account.name, msg)
        return {"ok": False, "already": False, "message": msg or "签到失败"}

    def invite_overview(self) -> Optional[dict[str, Any]]:
        r = self._request("GET", "/api/invite/overview")
        if not r.get("ok"):
            logger.warning(
                "[%s] 📋 邀请概览失败：%s",
                self.account.name,
                r.get("message"),
            )
            return None
        results = r.get("results")
        return results if isinstance(results, dict) else {}

    def claim_active_reward(self, offset_days: int) -> dict[str, Any]:
        label = {1: "昨天", 2: "前天"}.get(offset_days, f"d{offset_days}")
        r = self._request(
            "POST",
            "/api/invite/active-reward/claim",
            body={"offsetDays": int(offset_days)},
        )
        results = r.get("results") or {}
        msg = str(r.get("message") or "")
        if r.get("ok"):
            amount = results.get("amount")
            balance = results.get("balance")
            extra = []
            if amount is not None:
                try:
                    extra.append(f"到账 {float(amount) / 100:.2f} 元")
                except (TypeError, ValueError):
                    extra.append(f"到账 {amount}")
            if balance is not None:
                try:
                    extra.append(f"余额 {float(balance) / 100:.2f} 元")
                except (TypeError, ValueError):
                    extra.append(f"余额 {balance}")
            detail = ("，" + "，".join(extra)) if extra else ""
            logger.info(
                "[%s] 🎁 领取%s：%s%s",
                self.account.name,
                label,
                msg or "成功",
                detail,
            )
            return {
                "ok": True,
                "message": msg or "领取成功",
                "amount": amount,
                "balance": balance,
            }
        logger.info("[%s] 🎁 领取%s：%s", self.account.name, label, msg)
        return {"ok": False, "message": msg or "领取失败"}

    def claim_active_income(self) -> dict[str, Any]:
        overview = self.invite_overview()
        if overview is None:
            return {"ok": False, "claimed": 0, "message": "概览失败"}

        stats = overview.get("stats") or []
        if not isinstance(stats, list):
            stats = []

        targets = [s for s in stats if isinstance(s, dict) and s.get("canClaim") is True]
        if not targets:
            targets = [
                s
                for s in stats
                if isinstance(s, dict)
                and int(s.get("offsetDays") or -1) in (1, 2)
                and s.get("rewardPaid") is not True
                and float(s.get("totalRewardAmount") or 0) > 0
            ]

        if not targets:
            yest = next(
                (
                    s
                    for s in stats
                    if isinstance(s, dict) and int(s.get("offsetDays") or -1) == 1
                ),
                None,
            )
            if yest is not None:
                if yest.get("rewardPaid") is True:
                    msg = f"昨天收益已领取（{yest.get('reward')}）"
                else:
                    msg = f"昨天暂无可领（{yest.get('reward')}）"
            else:
                msg = "暂无可领取的活跃奖"
            logger.info("[%s] 🎁 %s", self.account.name, msg)
            return {"ok": True, "claimed": 0, "message": msg, "skipped": True}

        claimed = 0
        last_msg = ""
        for s in sorted(targets, key=lambda x: int(x.get("offsetDays") or 99)):
            od = int(s.get("offsetDays") or 0)
            if od not in (1, 2):
                continue
            label = s.get("label") or ({1: "昨天", 2: "前天"}.get(od, str(od)))
            logger.info(
                "[%s] 🎁 准备领取%s（%s）…",
                self.account.name,
                label,
                s.get("reward"),
            )
            cr = self.claim_active_reward(od)
            last_msg = str(cr.get("message") or "")
            if cr.get("ok"):
                claimed += 1
            time.sleep(random.uniform(1.0, 2.5))

        return {
            "ok": claimed > 0,
            "claimed": claimed,
            "message": f"领取 {claimed} 笔" if claimed else (last_msg or "未领到"),
        }

    def get_profile(self) -> Optional[dict[str, Any]]:
        r = self._request("GET", "/api/user/profile")
        if not r.get("ok"):
            logger.warning(
                "[%s] 👤 资料失败：%s", self.account.name, r.get("message")
            )
            return None
        results = r.get("results")
        return results if isinstance(results, dict) else {}

    def withdraw(self, amount_fen: int) -> dict[str, Any]:
        yuan = amount_fen / 100
        r = self._request(
            "POST",
            "/api/balance/withdraw",
            body={"amount": int(amount_fen)},
        )
        results = r.get("results") or {}
        msg = str(r.get("message") or "")
        if r.get("ok"):
            wno = results.get("withdrawNo") or results.get("orderNo") or ""
            extra = f"，单号 {wno}" if wno else ""
            logger.info(
                "[%s] 💸 提现成功：%s，%.2f 元%s",
                self.account.name,
                msg or "OK",
                yuan,
                extra,
            )
            return {"ok": True, "message": msg or "提现成功", "amount_fen": amount_fen}
        logger.warning("[%s] 💸 提现失败：%s", self.account.name, msg)
        return {"ok": False, "message": msg or "提现失败"}

    def auto_withdraw(self) -> dict[str, Any]:
        if not self.cfg.withdraw_enabled:
            logger.info("[%s] 💸 提现已关闭（DX_WITHDRAW=0）", self.account.name)
            return {"ok": True, "skipped": True, "message": "提现关闭"}

        profile = self.get_profile()
        if profile is None:
            return {"ok": False, "message": "无法获取资料"}

        try:
            balance = int(profile.get("balance") or 0)
        except (TypeError, ValueError):
            balance = 0
        alipay = str(profile.get("alipayAccount") or "").strip()
        real_name = str(
            profile.get("personalVerifiedName")
            or profile.get("realName")
            or ""
        ).strip()
        amount = (balance // WITHDRAW_UNIT_FEN) * WITHDRAW_UNIT_FEN

        logger.info(
            "[%s] 💸 余额 %.2f 元 · 支付宝=%s · 实名=%s",
            self.account.name,
            balance / 100,
            alipay or "未绑定",
            real_name or "未认证",
        )
        if not alipay:
            return {"ok": True, "skipped": True, "message": "未绑定支付宝"}
        if not real_name:
            return {"ok": True, "skipped": True, "message": "未实名"}
        if amount < WITHDRAW_MIN_FEN:
            return {
                "ok": True,
                "skipped": True,
                "message": f"不足1元（零头{balance % 100}分）",
                "balance_fen": balance,
            }

        logger.info(
            "[%s] 💸 申请提现 %.2f 元（整元）…",
            self.account.name,
            amount / 100,
        )
        wr = self.withdraw(amount)
        wr["balance_fen"] = balance
        return wr

    def run(self, *, login_only: bool = False) -> dict[str, Any]:
        acc = self.account
        result: dict[str, Any] = {
            "ok": False,
            "name": acc.name,
            "message": "",
            "via": "",
            "checkin": None,
            "claim": None,
            "withdraw": None,
            "balance_fen": None,
            "steps": [],
        }

        auth = self.ensure_token()
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

        if self.cfg.dry_run:
            profile = self.get_profile()
            if profile is not None:
                try:
                    result["balance_fen"] = int(profile.get("balance") or 0)
                except (TypeError, ValueError):
                    result["balance_fen"] = None
                result["ok"] = True
                result["message"] = (
                    f"dry-run 余额 "
                    f"{(result['balance_fen'] or 0) / 100:.2f} 元"
                )
            else:
                result["message"] = "dry-run 查资料失败"
            return result

        lo = min(self.cfg.delay_after_login_min, self.cfg.delay_after_login_max)
        hi = max(self.cfg.delay_after_login_min, self.cfg.delay_after_login_max)
        wait = random.uniform(lo, hi)
        logger.info("[%s] ⏳ 登录后等待 %.1fs 再签到…", acc.name, wait)
        time.sleep(wait)

        cr = self.checkin()
        result["checkin"] = cr
        result["steps"].append(
            "checkin:ok" if cr.get("ok") else f"checkin:fail:{cr.get('message')}"
        )

        time.sleep(random.uniform(2, 5))
        claim = self.claim_active_income()
        result["claim"] = claim
        result["steps"].append(
            f"claim:{claim.get('claimed') or 0}"
            if claim.get("ok") or claim.get("skipped")
            else f"claim:fail:{claim.get('message')}"
        )

        time.sleep(random.uniform(2, 4))
        wd = self.auto_withdraw()
        result["withdraw"] = wd
        if wd.get("balance_fen") is not None:
            result["balance_fen"] = wd.get("balance_fen")
        result["steps"].append(
            "withdraw:ok"
            if wd.get("ok") and not wd.get("skipped")
            else (
                f"withdraw:skip:{wd.get('message')}"
                if wd.get("skipped")
                else f"withdraw:fail:{wd.get('message')}"
            )
        )

        # 成功判定：登录成功且（签到成功或已签 / 领奖有进展 / 提现成功或合理跳过）
        result["ok"] = bool(
            cr.get("ok")
            or claim.get("ok")
            or claim.get("skipped")
            or (wd.get("ok") and not wd.get("skipped"))
            or wd.get("skipped")
        )
        if result["ok"]:
            parts = []
            if cr.get("ok"):
                parts.append("已签" if cr.get("already") else "签到")
            if claim.get("claimed"):
                parts.append(f"领收益×{claim['claimed']}")
            if wd.get("ok") and not wd.get("skipped"):
                parts.append("提现")
            elif wd.get("skipped"):
                parts.append(f"提现跳过({wd.get('message')})")
            result["message"] = " · ".join(parts) or "完成"
        else:
            result["message"] = (
                cr.get("message")
                or claim.get("message")
                or wd.get("message")
                or "失败"
            )

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
        lines.append(f"{'✅' if ok else '❌'} {name}")

        ck = r.get("checkin") or {}
        if ck:
            if ck.get("ok") and ck.get("already"):
                lines.append("   ✍️ 签到：今日已签")
            elif ck.get("ok"):
                pts = ck.get("points")
                st = ck.get("streak")
                extra = ""
                if pts is not None:
                    extra += f" +{pts}积分"
                if st is not None:
                    extra += f" · 连续{st}天"
                lines.append(f"   ✍️ 签到：成功{extra}")
            else:
                lines.append(f"   ✍️ 签到：失败 {ck.get('message') or ''}".rstrip())

        cl = r.get("claim") or {}
        if cl:
            if cl.get("claimed"):
                lines.append(f"   🎁 活跃收益：领 {cl.get('claimed')} 笔")
            elif cl.get("skipped") or cl.get("ok"):
                lines.append(f"   🎁 活跃收益：{cl.get('message') or '无'}")
            else:
                lines.append(f"   🎁 活跃收益：失败 {cl.get('message') or ''}".rstrip())

        wd = r.get("withdraw") or {}
        if wd:
            if wd.get("ok") and not wd.get("skipped"):
                fen = wd.get("amount_fen")
                yuan = f"{fen / 100:.2f} 元" if fen else ""
                lines.append(f"   💸 提现：成功 {yuan}".rstrip())
            elif wd.get("skipped"):
                lines.append(f"   💸 提现：跳过（{wd.get('message') or ''}）")
            else:
                lines.append(f"   💸 提现：失败 {wd.get('message') or ''}".rstrip())

        bal = r.get("balance_fen")
        if bal is not None:
            lines.append(f"   💰 余额：{bal / 100:.2f} 元")

        via = str(r.get("via") or "")
        if via:
            via_map = {
                "password": "密码登录",
                "token": "Token",
                "cache": "缓存 Token",
            }
            lines.append(f"   🔐 {via_map.get(via, via)}")

        if not ok and r.get("message"):
            msg = str(r["message"])
            short = msg if len(msg) <= 100 else msg[:97] + "…"
            lines.append(f"   ⚠️ {short}")

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
        return "多象签到"
    if ok_n == n:
        return f"多象签到 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"多象签到 ❌ 0/{n}"
    return f"多象签到 ⚠️ {ok_n}/{n}"


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
        "group": cfg.bark_group or "多象",
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
        import re

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
        "青龙：设置 DX_ACCOUNTS 或 DX（手机号#密码，多账号 @ 分隔）\n"
        "本地：cp config.example.yaml config.yaml 并填写"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="多象签到 / 领收益 / 提现（青龙 / Bark）")
    parser.add_argument("-c", "--config", help="本地 yaml 配置路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    parser.add_argument("--login-only", action="store_true", help="仅登录")
    parser.add_argument("--dry-run", action="store_true", help="登录后只查资料")
    parser.add_argument(
        "--no-withdraw", action="store_true", help="本次关闭自动提现"
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
    if args.no_withdraw:
        cfg.withdraw_enabled = False

    logger.info("📱 多象 · 签到领收益")
    logger.info(
        "   账号 %d 个 · 提现 %s · 通知 %s%s",
        len(cfg.accounts),
        "开" if cfg.withdraw_enabled else "关",
        "开" if cfg.notify.enabled() else "关",
        " · DRY_RUN" if cfg.dry_run else "",
    )

    cache = load_token_cache()
    account_results: list[tuple[str, dict[str, Any]]] = []

    for i, acc in enumerate(cfg.accounts):
        log_banner(f"👤 {acc.name}")
        logger.info("[%s] 🔐 鉴权：%s", acc.name, acc.auth_label())
        try:
            client = DuoXiangClient(acc, cfg, cache)
            result = client.run(login_only=bool(args.login_only))
        except Exception as e:
            logger.error("[%s] 💥 未处理异常: %s", acc.name, e)
            logger.debug("exception traceback", exc_info=True)
            result = {
                "ok": False,
                "message": str(e),
                "via": "error",
            }

        if result.get("ok"):
            logger.info("[%s] ✅ %s", acc.name, result.get("message") or "OK")
        else:
            logger.error("[%s] ❌ %s", acc.name, result.get("message") or "失败")

        account_results.append((acc.name, result))

        if i < len(cfg.accounts) - 1:
            lo = min(
                cfg.inter_account_delay_min, cfg.inter_account_delay_max
            )
            hi = max(
                cfg.inter_account_delay_min, cfg.inter_account_delay_max
            )
            delay = random.uniform(lo, hi)
            logger.info("⏳ 等待 %.1fs 后处理下一账号…", delay)
            time.sleep(delay)

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
