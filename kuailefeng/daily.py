#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快乐蜂（BuzzBee）抽奖脚本 — 手机号 + 密码登录

cron: 0 9 * * *
new Env('快乐蜂抽奖');

流程：
  1. 手机号 + 密码登录（密码 RSA 加密）获取 z-token 与 Cookie
  2. 请求 /v1/turntables/free 三次（默认间隔随机 5–8 秒）
  3. 循环：GET /v1/turntables/check 取 idHash（必要时 /ad）→ POST /v1/turntables/{idHash}
     （每轮间隔随机 5–8 秒，按 /check 自适应到用完）

青龙环境变量（账号）：
  KLF_ACCOUNTS  推荐。JSON 数组
    [{"name":"主号","phone":"138...","password":"..."}]
  或：
    KLF = 手机号#密码，多账号用 & 或换行
  或平行变量（& 分隔）：
    KLF_PHONE / KLF_PASSWORD / KLF_NAME

兼容原 JS（可选，免登）：
  klekey = z-token#cookie

可选：
  KLF_FREE_TIMES / KLF_AD_TIMES
  KLF_AD_TIMES=0（默认）按 /check 自适应抽到今日用完；>0 为安全上限
  KLF_AD_INTERVAL_MIN / KLF_AD_INTERVAL_MAX  抽奖随机间隔秒（默认 5–8）
  KLF_AD_INTERVAL  若单独设置则为固定间隔（覆盖 min/max）
  KLF_TIMEOUT / KLF_INTER_ACCOUNT_DELAY / KLF_TOKEN_CACHE
  KLF_TOKEN_STYLE  token 头格式：auto（默认）/ raw / bearer
  DRY_RUN=1  只登录，不抽奖

通知（与 hifiti / quark 等共用）：
  BARK_URL 或 BARK_KEY [+ BARK_SERVER]
  BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

依赖：
  requests
  cryptography  （RSA 加密密码）
  本地 yaml 可选：PyYAML
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:  # pragma: no cover
    serialization = None  # type: ignore
    padding = None  # type: ignore

SCRIPT_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("kuailefeng")

# ---------------------------------------------------------------------------
# 常量（来自 App / H5 抓包）
# ---------------------------------------------------------------------------

API_BASE = "https://klf-api.lingdangshuo.com"
# H5 登录同域也可：https://klf.lingdangshuo.com/api
LOGIN_PATH = "/auth/password/login"
FREE_PATH = "/v1/turntables/free"
AD_PATH = "/v1/turntables/ad"
CHECK_PATH = "/v1/turntables/check"
CONFIG_PATH = "/v1/turntables/config"

# free / turn 接口沿用原 JS 固定密文
# 密码登录（z-client=2 + Bearer JWT）下，广告抽奖应走 GET /check 取 idHash，
# 不要再硬编码 POST /ad 的 advertisementId/stepId（错误参数会直接 5000 系统异常）
FREE_BODY = "GCTkzi72o4/SXui0WOkH3Q=="
TURN_BODY = FREE_BODY
DEFAULT_ADVERTISEMENT_ID = 1
DEFAULT_STEP_ID = 110

# /check 返回的 state（观测值，便于日志）
CHECK_STATE_CAN_DRAW = 3  # 可抽奖（带 idHash）
CHECK_STATE_EXHAUSTED = 5  # 今日次数用完

# H5 前端内嵌的 RSA 公钥（JSEncrypt / PKCS1 v1.5）
RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCdNGCB0MdU+oX75mJYHuqYee9j"
    "NlFNj5RtRK4bmEWFu9uXnqzVQHcVILOzeS9KsB0tyefvk+kUjgCP5Zy+OfEw/oKG"
    "/cxCxLxsGqXhiyQE6Kzngx/m4gXnx+XdaMCcpqgmY0b7kS4+zULkRLkaSD07x5Qp"
    "WxchCvZ7a+uPNQG6ZQIDAQAB"
)

APP_UA = "BuzzBee/1.1.9 (iPhone; iOS 26.5; Scale/3.00)"
H5_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
    "Mobile/15E148 Safari/604.1"
)

DEFAULT_FREE_TIMES = 3
# 0 = 按 /check 自适应抽到今日用完；>0 作为安全上限
DEFAULT_AD_TIMES = 0
# 每轮抽奖随机间隔（秒），防固定节奏被检测
DEFAULT_AD_INTERVAL_MIN = 5.0
DEFAULT_AD_INTERVAL_MAX = 8.0
# 兼容旧配置名
DEFAULT_FREE_INTERVAL = 6
DEFAULT_AD_INTERVAL = 0  # 0 表示使用 min/max 随机
# ad_times=0 时的硬上限，防止异常状态死循环
AD_MAX_SAFETY = 100
DEFAULT_TIMEOUT = 20
DEFAULT_INTER_ACCOUNT_DELAY = 5

DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "快乐蜂抽奖"

# 业务码（便于日志）
CODE_OK = 200
CODE_FREE_USED = 5621  # 免费抽奖次数已用完
CODE_TURN_USED = 5612  # 抽奖已被使用
CODE_SYS_ERR = 5000  # 系统异常（常见于缺设备头）


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    phone: str = ""
    password: str = ""
    z_token: str = ""  # 可选：直接用抓包 token
    cookie: str = ""  # 可选：直接用抓包 cookie

    def has_password(self) -> bool:
        return bool(self.phone.strip() and self.password)

    def has_token(self) -> bool:
        return bool(self.z_token.strip() and self.cookie.strip())

    def cache_key(self) -> str:
        if self.phone:
            return f"phone:{self.phone.strip()}"
        return f"name:{self.name}"

    def normalize(self) -> None:
        self.phone = self.phone.strip()
        self.z_token = self.z_token.strip()
        self.cookie = self.cookie.strip()
        if self.cookie.lower().startswith("cookie:"):
            self.cookie = self.cookie.split(":", 1)[1].strip()
        # 兼容 Bearer 前缀
        if self.z_token.lower().startswith("bearer "):
            self.z_token = self.z_token[7:].strip()
        if not self.name:
            self.name = self.phone or "account"


@dataclass
class BarkConfig:
    url: str = ""
    key: str = ""
    server: str = DEFAULT_BARK_SERVER
    group: str = DEFAULT_BARK_GROUP
    sound: str = ""
    icon: str = ""
    level: str = ""

    def enabled(self) -> bool:
        return bool(self.url or self.key)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    free_times: int = DEFAULT_FREE_TIMES
    free_interval: float = DEFAULT_FREE_INTERVAL  # 仅当未用随机区间时兼容
    ad_times: int = DEFAULT_AD_TIMES
    # 抽奖间隔：优先 ad_interval_min/max 随机；ad_interval>0 时固定
    ad_interval: float = DEFAULT_AD_INTERVAL
    ad_interval_min: float = DEFAULT_AD_INTERVAL_MIN
    ad_interval_max: float = DEFAULT_AD_INTERVAL_MAX
    timeout: int = DEFAULT_TIMEOUT
    inter_account_delay: int = DEFAULT_INTER_ACCOUNT_DELAY
    dry_run: bool = False
    # auto | raw | bearer
    # auto: 密码登录用 Bearer；klekey/缓存抓包 token 用 raw（与原 App JS 一致）
    token_style: str = "auto"
    advertisement_id: int = DEFAULT_ADVERTISEMENT_ID
    step_id: int = DEFAULT_STEP_ID
    bark: BarkConfig = field(default_factory=BarkConfig)

    def draw_interval_range(self) -> tuple[float, float]:
        """返回 (lo, hi) 秒；lo==hi 表示固定间隔。"""
        if self.ad_interval and self.ad_interval > 0:
            v = float(self.ad_interval)
            return v, v
        lo = float(self.ad_interval_min)
        hi = float(self.ad_interval_max)
        if hi < lo:
            lo, hi = hi, lo
        if lo < 0:
            lo = 0.0
        if hi < lo:
            hi = lo
        return lo, hi


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    v = _env(name)
    if not v:
        return default
    return v.lower() in ("1", "true", "yes", "on", "y")


def _pick_int(*candidates: Any, default: int) -> int:
    """取第一个非 None / 非空字符串的候选并 int；支持 0。"""
    for c in candidates:
        if c is None:
            continue
        if isinstance(c, str) and not c.strip():
            continue
        try:
            return int(c)
        except (TypeError, ValueError):
            continue
    return default


def _pick_float(*candidates: Any, default: float) -> float:
    for c in candidates:
        if c is None:
            continue
        if isinstance(c, str) and not c.strip():
            continue
        try:
            return float(c)
        except (TypeError, ValueError):
            continue
    return default


def sleep_random(lo: float, hi: float, *, label: str = "抽奖") -> float:
    """随机等待 [lo, hi] 秒，返回实际等待秒数。"""
    if hi < lo:
        lo, hi = hi, lo
    delay = float(lo) if hi <= lo else random.uniform(lo, hi)
    delay = max(0.0, delay)
    logger.info("⏳ %s间隔随机等待 %.1f 秒（范围 %.0f–%.0f）", label, delay, lo, hi)
    if delay > 0:
        time.sleep(delay)
    return delay


def load_bark_config(
    *,
    raw_notify: Optional[dict[str, Any]] = None,
) -> BarkConfig:
    """从环境变量（及可选 yaml notify 段）加载 Bark，与其它项目共用 BARK_*。"""
    raw_notify = raw_notify or {}
    url = _env("BARK_URL") or _env("BARK_PUSH") or str(raw_notify.get("bark_url") or "")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY") or str(raw_notify.get("bark_key") or "")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    group = _env("BARK_GROUP") or str(raw_notify.get("bark_group") or "") or DEFAULT_BARK_GROUP
    server = (
        _env("BARK_SERVER")
        or str(raw_notify.get("bark_server") or "")
        or DEFAULT_BARK_SERVER
    ).rstrip("/")
    return BarkConfig(
        url=url.strip(),
        key=key.strip(),
        server=server,
        group=group,
        sound=_env("BARK_SOUND") or str(raw_notify.get("bark_sound") or ""),
        icon=_env("BARK_ICON") or str(raw_notify.get("bark_icon") or ""),
        level=_env("BARK_LEVEL") or str(raw_notify.get("bark_level") or ""),
    )


def _bark_endpoint(cfg: BarkConfig) -> Optional[str]:
    if cfg.url:
        return cfg.url.strip().rstrip("/")
    if cfg.key:
        return f"{cfg.server.rstrip('/')}/{cfg.key.strip()}"
    return None


def send_bark(cfg: BarkConfig, title: str, body: str) -> None:
    endpoint = _bark_endpoint(cfg)
    if not endpoint:
        return
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.group or DEFAULT_BARK_GROUP,
    }
    if cfg.sound:
        payload["sound"] = cfg.sound
    if cfg.icon:
        payload["icon"] = cfg.icon
    if cfg.level:
        payload["level"] = cfg.level
    try:
        r = requests.post(endpoint, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = (
                f"{endpoint}/{quote(title, safe='')}/{quote(body, safe='')}"
            )
            r = requests.get(get_url, timeout=15)
        logger.info("📣 Bark 已推送（HTTP %s）", r.status_code)
        logger.debug("Bark 响应: %s", r.text[:200])
    except Exception as e:
        logger.warning("📣 Bark 推送失败: %s", e)


def _split_multi(value: str) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r"[&\n]", value) if x.strip()]


def resolve_token_cache_path() -> Path:
    env = _env("KLF_TOKEN_CACHE")
    if env:
        return Path(env).expanduser()
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "kuailefeng_token_cache.json"
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
        logger.warning("token 缓存写入失败: %s", e)


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("KLF_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"KLF_ACCOUNTS[{i}] 必须是对象")
        phone = str(item.get("phone") or item.get("mobile") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        z_token = str(item.get("z_token") or item.get("token") or "")
        cookie = str(item.get("cookie") or "")
        name = str(item.get("name") or phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, z_token=z_token, cookie=cookie)
        acc.normalize()
        if not acc.has_password() and not acc.has_token():
            raise ValueError(f"KLF_ACCOUNTS[{i}] 缺少手机号密码或 z_token#cookie")
        accounts.append(acc)
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    accounts_json = _env("KLF_ACCOUNTS")
    if accounts_json:
        return _parse_accounts_json(accounts_json)

    # KLF=手机号#密码
    klf = _env("KLF") or _env("KLF_USER")
    if klf and "#" in klf and not klf.strip().startswith("{"):
        # 若像 klekey（token 很长），留给后面 klekey 处理；带手机号形态优先
        accounts: list[Account] = []
        for i, line in enumerate(_split_multi(klf)):
            parts = line.split("#", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1]:
                raise ValueError(f"KLF 第 {i + 1} 段格式错误，应为 手机号#密码")
            left, right = parts[0].strip(), parts[1]
            # 手机号形态
            if re.fullmatch(r"1\d{10}", left):
                acc = Account(name=left, phone=left, password=right)
            else:
                # 兼容原 klekey: z-token#cookie
                acc = Account(name=f"token_{i + 1}", z_token=left, cookie=right)
            acc.normalize()
            accounts.append(acc)
        return accounts

    # 原 JS 环境变量 klekey = z-token#cookie
    klekey = _env("klekey") or _env("KLEKEY")
    if klekey:
        accounts = []
        for i, line in enumerate(_split_multi(klekey)):
            parts = line.split("#", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                raise ValueError(f"klekey 第 {i + 1} 段格式错误，应为 z-token#cookie")
            acc = Account(
                name=f"klekey_{i + 1}",
                z_token=parts[0].strip(),
                cookie=parts[1].strip(),
            )
            acc.normalize()
            accounts.append(acc)
        return accounts

    phones = _split_multi(_env("KLF_PHONE") or _env("KLF_MOBILE"))
    passwords = _split_multi(_env("KLF_PASSWORD") or _env("KLF_PASS"))
    names = _split_multi(_env("KLF_NAME"))
    n = max(len(phones), len(passwords))
    if n <= 0:
        return []
    accounts = []
    for i in range(n):
        phone = phones[i] if i < len(phones) else ""
        pwd = passwords[i] if i < len(passwords) else ""
        name = names[i] if i < len(names) else (phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd)
        acc.normalize()
        if not acc.has_password():
            raise ValueError(f"第 {i + 1} 个账号缺少手机号或密码")
        accounts.append(acc)
    return accounts


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _parse_accounts_from_env()
    if not accounts:
        return None
    style = (_env("KLF_TOKEN_STYLE", "auto") or "auto").lower()
    if style not in ("auto", "raw", "bearer"):
        style = "auto"
    return AppConfig(
        accounts=accounts,
        free_times=_pick_int(_env("KLF_FREE_TIMES"), default=DEFAULT_FREE_TIMES),
        free_interval=_pick_float(
            _env("KLF_FREE_INTERVAL"), default=float(DEFAULT_FREE_INTERVAL)
        ),
        ad_times=_pick_int(_env("KLF_AD_TIMES"), default=DEFAULT_AD_TIMES),
        ad_interval=_pick_float(_env("KLF_AD_INTERVAL"), default=float(DEFAULT_AD_INTERVAL)),
        ad_interval_min=_pick_float(
            _env("KLF_AD_INTERVAL_MIN"), default=DEFAULT_AD_INTERVAL_MIN
        ),
        ad_interval_max=_pick_float(
            _env("KLF_AD_INTERVAL_MAX"), default=DEFAULT_AD_INTERVAL_MAX
        ),
        timeout=_pick_int(_env("KLF_TIMEOUT"), default=DEFAULT_TIMEOUT),
        inter_account_delay=_pick_int(
            _env("KLF_INTER_ACCOUNT_DELAY"), default=DEFAULT_INTER_ACCOUNT_DELAY
        ),
        dry_run=_env_bool("DRY_RUN", False),
        token_style=style,
        advertisement_id=_pick_int(
            _env("KLF_ADVERTISEMENT_ID"), default=DEFAULT_ADVERTISEMENT_ID
        ),
        step_id=_pick_int(_env("KLF_STEP_ID"), default=DEFAULT_STEP_ID),
        bark=load_bark_config(),
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
        phone = str(item.get("phone") or item.get("mobile") or item.get("user") or "")
        pwd = str(item.get("password") or item.get("pwd") or item.get("pass") or "")
        z_token = str(item.get("z_token") or item.get("token") or "")
        cookie = str(item.get("cookie") or "")
        name = str(item.get("name") or phone or f"account_{i + 1}")
        acc = Account(name=name, phone=phone, password=pwd, z_token=z_token, cookie=cookie)
        acc.normalize()
        if not acc.has_password() and not acc.has_token():
            raise ValueError(f"账号 [{acc.name}] 未配置 phone+password 或 z_token+cookie")
        accounts.append(acc)

    if not accounts:
        raise ValueError("配置中 accounts 为空")

    style = (
        _env("KLF_TOKEN_STYLE")
        or str(raw.get("token_style") or "auto")
    ).lower()
    if style not in ("auto", "raw", "bearer"):
        style = "auto"

    notify_raw = raw.get("notify") if isinstance(raw.get("notify"), dict) else {}
    return AppConfig(
        accounts=accounts,
        free_times=_pick_int(
            _env("KLF_FREE_TIMES"), raw.get("free_times"), default=DEFAULT_FREE_TIMES
        ),
        free_interval=_pick_float(
            _env("KLF_FREE_INTERVAL"),
            raw.get("free_interval"),
            default=float(DEFAULT_FREE_INTERVAL),
        ),
        ad_times=_pick_int(
            _env("KLF_AD_TIMES"), raw.get("ad_times"), default=DEFAULT_AD_TIMES
        ),
        ad_interval=_pick_float(
            _env("KLF_AD_INTERVAL"),
            raw.get("ad_interval"),
            default=float(DEFAULT_AD_INTERVAL),
        ),
        ad_interval_min=_pick_float(
            _env("KLF_AD_INTERVAL_MIN"),
            raw.get("ad_interval_min"),
            default=DEFAULT_AD_INTERVAL_MIN,
        ),
        ad_interval_max=_pick_float(
            _env("KLF_AD_INTERVAL_MAX"),
            raw.get("ad_interval_max"),
            default=DEFAULT_AD_INTERVAL_MAX,
        ),
        timeout=_pick_int(
            _env("KLF_TIMEOUT"), raw.get("timeout"), default=DEFAULT_TIMEOUT
        ),
        inter_account_delay=_pick_int(
            _env("KLF_INTER_ACCOUNT_DELAY"),
            raw.get("inter_account_delay"),
            default=DEFAULT_INTER_ACCOUNT_DELAY,
        ),
        dry_run=_env_bool("DRY_RUN", bool(raw.get("dry_run") or False)),
        token_style=style,
        advertisement_id=_pick_int(
            _env("KLF_ADVERTISEMENT_ID"),
            raw.get("advertisement_id"),
            default=DEFAULT_ADVERTISEMENT_ID,
        ),
        step_id=_pick_int(
            _env("KLF_STEP_ID"), raw.get("step_id"), default=DEFAULT_STEP_ID
        ),
        bark=load_bark_config(raw_notify=notify_raw),
    )


# ---------------------------------------------------------------------------
# RSA
# ---------------------------------------------------------------------------

def rsa_encrypt_password(password: str) -> str:
    """使用前端同款 RSA 公钥加密密码，返回 Base64。"""
    if serialization is None or padding is None:
        raise RuntimeError(
            "缺少 cryptography 库，请安装: pip install cryptography"
        )
    pem = (
        b"-----BEGIN PUBLIC KEY-----\n"
        + b"\n".join(
            RSA_PUBLIC_KEY_B64[i : i + 64].encode()
            for i in range(0, len(RSA_PUBLIC_KEY_B64), 64)
        )
        + b"\n-----END PUBLIC KEY-----\n"
    )
    key = serialization.load_pem_public_key(pem)
    encrypted = key.encrypt(password.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode("ascii")


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

class KlfClient:
    def __init__(
        self,
        account: Account,
        timeout: int = DEFAULT_TIMEOUT,
        token_style: str = "auto",
    ):
        self.account = account
        self.timeout = timeout
        # auto | raw | bearer；resolve 后写入 _resolved_token_style
        self.token_style_pref = (token_style or "auto").lower()
        self._resolved_token_style = "raw"
        # password | klekey | cache
        self.auth_source = "klekey"
        self.session = requests.Session()
        self.token = account.z_token
        self.refresh_token = ""
        self.expired: Optional[int] = None

    def _normalize_token(self, token: str) -> str:
        tok = (token or "").strip()
        if tok.lower().startswith("bearer "):
            tok = tok[7:].strip()
        return tok

    def _resolve_token_style(self) -> str:
        pref = self.token_style_pref
        if pref in ("raw", "bearer"):
            return pref
        # auto：密码登录走 H5 的 Bearer；App 抓包 klekey 走裸 token
        if self.auth_source == "password":
            return "bearer"
        # 缓存若未记录来源：JWT(eyJ...) 基本是密码/H5 登录产物，用 Bearer
        tok = self._normalize_token(self.token)
        if tok.startswith("eyJ") and self.account.has_password():
            return "bearer"
        if tok.startswith("eyJ") and self.auth_source in ("cache", "password"):
            return "bearer"
        return "raw"

    def _z_token_header(self) -> str:
        tok = self._normalize_token(self.token)
        style = self._resolved_token_style
        if style == "bearer":
            return f"Bearer {tok}"
        return tok

    def _login_headers(self) -> dict[str, str]:
        # 登录用 H5 风格（z-client=2），App 头登录会 401
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "User-Agent": H5_UA,
            "z-client": "2",
            "z-version": "1.0.0",
            "Origin": "https://klf.lingdangshuo.com",
            "Referer": "https://klf.lingdangshuo.com/",
        }

    def _api_headers(self) -> dict[str, str]:
        """业务接口请求头。

        密码登录 JWT 必须：
          - z-client=2
          - z-token=Bearer <jwt>
          - 同时带上 App 设备头（z-device / z-os / z-version=1.1.9 等）
        缺设备头时服务端常返回 code=5000「系统异常」。

        App 抓包 klekey：z-client=1 + 裸 token。
        """
        style = self._resolved_token_style
        use_bearer = style == "bearer" or self.auth_source == "password"

        if use_bearer:
            # 混合头：H5 鉴权 + App 设备信息（实测 free/ad 必需）
            headers = {
                "Host": "klf-api.lingdangshuo.com",
                "Accept": "*/*",
                "Accept-Language": "zh-Hans-CN;q=1",
                "Content-Type": "application/json",
                "User-Agent": APP_UA,
                "Connection": "keep-alive",
                "z-client": "2",
                "z-version": "1.1.9",
                "z-os": "2",
                "z-os-version": "26.5",
                "z-store": "1",
                "z-device": "209076",
            }
        else:
            # 原 JS App 头（klekey）
            headers = {
                "Host": "klf-api.lingdangshuo.com",
                "z-os-version": "26.5",
                "z-store": "1",
                "Accept": "*/*",
                "Accept-Language": "zh-Hans-CN;q=1",
                "z-client": "1",
                "Content-Type": "application/json",
                "User-Agent": APP_UA,
                "Connection": "keep-alive",
                "z-device": "209076",
                "z-version": "1.1.9",
                "z-os": "2",
            }

        if self.token:
            headers["z-token"] = self._z_token_header()
        cookie_str = "; ".join(
            f"{k}={v}" for k, v in self.session.cookies.get_dict().items()
        )
        if cookie_str:
            headers["Cookie"] = cookie_str
        return headers

    def login(self) -> dict[str, Any]:
        if not self.account.has_password():
            raise RuntimeError("未配置手机号和密码，无法登录")
        enc_pwd = rsa_encrypt_password(self.account.password)
        url = f"{API_BASE}{LOGIN_PATH}"
        body = {"mobile": self.account.phone, "password": enc_pwd}
        logger.info("🔐 [%s] 登录中: %s", self.account.name, self.account.phone)
        resp = self.session.post(
            url,
            headers=self._login_headers(),
            json=body,
            timeout=self.timeout,
        )
        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(f"登录响应非 JSON: HTTP {resp.status_code} {resp.text[:200]}")

        code = data.get("code")
        if code != 200:
            raise RuntimeError(f"登录失败 code={code} msg={data.get('msg')}")

        payload = data.get("data") or {}
        token = self._normalize_token(str(payload.get("token") or ""))
        if not token:
            raise RuntimeError(f"登录成功但未返回 token: {data}")

        self.token = token
        self.refresh_token = str(payload.get("refreshToken") or "")
        self.expired = payload.get("expired")
        self.auth_source = "password"
        self._resolved_token_style = self._resolve_token_style()
        # session 已自动保存 acw_tc 等 cookie
        cookie_str = "; ".join(f"{k}={v}" for k, v in self.session.cookies.get_dict().items())
        logger.info(
            "✅ [%s] 登录成功 token=%s... style=%s cookie=%s",
            self.account.name,
            token[:16],
            self._resolved_token_style,
            cookie_str[:40] + ("..." if len(cookie_str) > 40 else ""),
        )
        return payload

    def apply_cached_auth(self, entry: dict[str, Any]) -> bool:
        token = self._normalize_token(str(entry.get("token") or ""))
        cookie = str(entry.get("cookie") or "")
        expired = entry.get("expired")
        if not token:
            return False
        # expired 为毫秒时间戳时，提前 2 分钟视为过期
        if expired is not None:
            try:
                exp = int(expired)
                if exp > 10_000_000_000:  # ms
                    if time.time() * 1000 >= exp - 120_000:
                        return False
                else:
                    if time.time() >= exp - 120:
                        return False
            except (TypeError, ValueError):
                pass
        self.token = token
        self.refresh_token = str(entry.get("refresh_token") or "")
        self.expired = expired if isinstance(expired, int) else None
        # 缓存里记录的来源 / 风格
        self.auth_source = str(entry.get("auth_source") or "cache")
        cached_style = str(entry.get("token_style") or "").lower()
        if cached_style in ("raw", "bearer"):
            self._resolved_token_style = cached_style
        else:
            self._resolved_token_style = self._resolve_token_style()
        if cookie:
            for part in cookie.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, v = part.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip())
        return True

    def dump_auth_for_cache(self) -> dict[str, Any]:
        cookie_str = "; ".join(
            f"{k}={v}" for k, v in self.session.cookies.get_dict().items()
        )
        return {
            "token": self._normalize_token(self.token),
            "refresh_token": self.refresh_token,
            "expired": self.expired,
            "cookie": cookie_str,
            "phone": self.account.phone,
            "name": self.account.name,
            "auth_source": self.auth_source,
            "token_style": self._resolved_token_style,
            "ts": int(time.time()),
        }

    def ensure_auth(self, cache: dict[str, Any]) -> None:
        # 1) 账号直接配置了 token+cookie（原 klekey / 抓包）
        if self.account.has_token():
            self.token = self._normalize_token(self.account.z_token)
            self.auth_source = "klekey"
            self._resolved_token_style = self._resolve_token_style()
            for part in self.account.cookie.split(";"):
                part = part.strip()
                if not part or "=" not in part:
                    continue
                k, v = part.split("=", 1)
                self.session.cookies.set(k.strip(), v.strip())
            logger.info(
                "🔑 [%s] 使用配置的 z-token + cookie，style=%s",
                self.account.name,
                self._resolved_token_style,
            )
            return

        # 2) 缓存
        entry = cache.get(self.account.cache_key())
        if isinstance(entry, dict) and self.apply_cached_auth(entry):
            logger.info(
                "🔑 [%s] 使用缓存 token，style=%s source=%s z-client=%s",
                self.account.name,
                self._resolved_token_style,
                self.auth_source,
                self._api_headers().get("z-client"),
            )
            # 回写 style，避免旧缓存下次又判错
            cache[self.account.cache_key()] = self.dump_auth_for_cache()
            save_token_cache(cache)
            return

        # 3) 密码登录
        self.login()
        cache[self.account.cache_key()] = self.dump_auth_for_cache()
        save_token_cache(cache)

    def _is_auth_error(self, status: int, data: Any) -> bool:
        if status == 401:
            return True
        if isinstance(data, dict):
            code = data.get("code")
            # 1004 Token解析失败；1049/1060 登录态失效类
            if code in (401, 1004, 1049, 1060):
                return True
            msg = str(data.get("msg") or "")
            if any(k in msg for k in ("Token", "token", "非法访问", "未登录", "登录")):
                return True
        return False

    def _flip_token_style(self) -> bool:
        """切换 raw/bearer（同时会切换 z-client 1/2），成功切换返回 True。"""
        cur = self._resolved_token_style
        nxt = "raw" if cur == "bearer" else "bearer"
        if nxt == cur:
            return False
        self._resolved_token_style = nxt
        logger.warning(
            "[%s] 鉴权失败，切换 z-token 格式: %s -> %s（并切换 z-client）后重试",
            self.account.name,
            cur,
            nxt,
        )
        return True

    def _do_post(
        self,
        path: str,
        *,
        raw_body: Optional[str] = None,
        json_body: Any = None,
        allow_style_retry: bool = True,
    ) -> tuple[int, Any]:
        url = f"{API_BASE}{path}"
        headers = self._api_headers()
        ztok = headers.get("z-token") or ""
        logger.info(
            "[%s] POST %s | z-client=%s style=%s z-version=%s token=%s...",
            self.account.name,
            path,
            headers.get("z-client"),
            self._resolved_token_style,
            headers.get("z-version"),
            ztok[:28],
        )
        kwargs: dict[str, Any] = {
            "headers": headers,
            "timeout": self.timeout,
        }
        if json_body is not None:
            kwargs["json"] = json_body
        elif raw_body is not None:
            kwargs["data"] = raw_body

        resp = self.session.post(url, **kwargs)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}

        if allow_style_retry and self._is_auth_error(resp.status_code, data):
            logger.warning(
                "[%s] 鉴权错误 HTTP %s => %s",
                self.account.name,
                resp.status_code,
                _short(data, 200),
            )
            if self._flip_token_style():
                return self._do_post(
                    path,
                    raw_body=raw_body,
                    json_body=json_body,
                    allow_style_retry=False,
                )
        return resp.status_code, data

    def _post_raw(self, path: str, body: str, *, allow_style_retry: bool = True) -> tuple[int, Any]:
        return self._do_post(path, raw_body=body, allow_style_retry=allow_style_retry)

    def _post_json(self, path: str, body: Any, *, allow_style_retry: bool = True) -> tuple[int, Any]:
        return self._do_post(path, json_body=body, allow_style_retry=allow_style_retry)

    def _do_get(self, path: str, *, allow_style_retry: bool = True) -> tuple[int, Any]:
        url = f"{API_BASE}{path}"
        headers = self._api_headers()
        ztok = headers.get("z-token") or ""
        logger.info(
            "[%s] GET %s | z-client=%s style=%s z-version=%s token=%s...",
            self.account.name,
            path,
            headers.get("z-client"),
            self._resolved_token_style,
            headers.get("z-version"),
            ztok[:28],
        )
        resp = self.session.get(url, headers=headers, timeout=self.timeout)
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}

        if allow_style_retry and self._is_auth_error(resp.status_code, data):
            logger.warning(
                "[%s] 鉴权错误 HTTP %s => %s",
                self.account.name,
                resp.status_code,
                _short(data, 200),
            )
            if self._flip_token_style():
                return self._do_get(path, allow_style_retry=False)
        return resp.status_code, data

    @staticmethod
    def _parse_check_payload(data: Any) -> dict[str, Any]:
        """从 /check 或嵌套 turntableCheck 中抽出统一结构。"""
        if not isinstance(data, dict):
            return {}
        payload = data.get("data")
        if not isinstance(payload, dict):
            return {}
        if isinstance(payload.get("turntableCheck"), dict):
            return payload["turntableCheck"]
        return payload

    def fetch_check(self) -> tuple[int, Any, dict[str, Any]]:
        """GET /v1/turntables/check，返回 (http_status, raw_json, check_dict)。"""
        status, data = self._do_get(CHECK_PATH)
        check = self._parse_check_payload(data) if isinstance(data, dict) and data.get("code") == CODE_OK else {}
        return status, data, check

    def request_ad_id_hash(
        self,
        *,
        advertisement_id: int,
        step_id: int,
    ) -> tuple[int, Any, Optional[str]]:
        """POST /ad 换 idHash（仅当 /check 给出 stepId 时使用）。"""
        payload = {"advertisementId": advertisement_id, "stepId": step_id}
        status, data = self._post_json(AD_PATH, payload)
        id_hash = None
        if isinstance(data, dict):
            body = data.get("data")
            if isinstance(body, dict):
                id_hash = body.get("idHash") or body.get("id_hash")
            # 有的版本把 check 嵌在 data.turntableCheck
            if not id_hash:
                nested = self._parse_check_payload(data)
                id_hash = nested.get("idHash") or nested.get("id_hash")
        return status, data, str(id_hash) if id_hash else None

    def request_free(
        self,
        times: int,
        *,
        interval_lo: float,
        interval_hi: float,
    ) -> list[Any]:
        results = []
        for i in range(1, times + 1):
            logger.info("🎁 [FREE %s/%s] POST %s", i, times, FREE_PATH)
            status, data = self._post_raw(FREE_PATH, FREE_BODY)
            logger.info("🎁 [FREE %s] HTTP %s => %s", i, status, _short(data))
            results.append(data)
            if isinstance(data, dict):
                code = data.get("code")
                if code == CODE_OK:
                    gift = data.get("data") if isinstance(data.get("data"), dict) else {}
                    logger.info(
                        "🎉 [FREE %s] 免费抽奖成功 giftId=%s",
                        i,
                        (gift or {}).get("giftId"),
                    )
                elif code == CODE_FREE_USED:
                    logger.info("😴 [FREE] 免费次数已用完，跳过剩余 free 请求")
                    break
                elif code == CODE_SYS_ERR:
                    logger.warning(
                        "⚠️ [FREE] 系统异常(5000)。若持续出现，请确认使用了设备头 z-device/z-os"
                    )
            if i < times:
                sleep_random(interval_lo, interval_hi, label="免费抽奖")
        return results

    def draw_with_id_hash(self, id_hash: str) -> tuple[int, Any]:
        path = f"/v1/turntables/{id_hash}"
        return self._post_raw(path, TURN_BODY)

    def ad_loop(
        self,
        times: int,
        *,
        interval_lo: float,
        interval_hi: float,
        advertisement_id: int = DEFAULT_ADVERTISEMENT_ID,
        step_id: int = DEFAULT_STEP_ID,
    ) -> list[Any]:
        """广告/剩余抽奖：按 GET /check 状态自适应，有次数才继续。

        正确流程（密码登录 / App 均可）：
          1) GET /v1/turntables/check
          2) 若有 idHash → POST /v1/turntables/{idHash} 开奖
          3) 若仅有 stepId → 再 POST /ad(advertisementId, stepId) 换 idHash
          4) state=5 或明确「次数用完」→ 结束

        times:
          - 0  ：抽到 /check 说今日用完为止（硬上限 AD_MAX_SAFETY）
          - >0 ：最多抽 times 次，仍会在用完时提前结束

        每轮间隔在 [interval_lo, interval_hi] 秒随机。
        """
        results: list[Any] = []
        consecutive_fail = 0
        max_rounds = AD_MAX_SAFETY if times <= 0 else times
        adaptive = times <= 0
        success_draws = 0
        gift_ids: list[Any] = []
        i = 0

        if interval_lo == interval_hi:
            interval_desc = f"固定 {interval_lo:.0f}s"
        else:
            interval_desc = f"随机 {interval_lo:.0f}–{interval_hi:.0f}s"
        logger.info(
            "🎰 [%s] 广告抽奖模式: %s（上限 %s，间隔 %s）",
            self.account.name,
            "按 /check 自适应至用完" if adaptive else f"最多 {max_rounds} 次",
            max_rounds,
            interval_desc,
        )

        while i < max_rounds:
            i += 1
            cap_label = "∞" if adaptive else str(max_rounds)
            logger.info("🔄 ========== 抽奖循环 %s/%s ==========", i, cap_label)
            status, raw_check, check = self.fetch_check()
            logger.info("🔎 [%s] /check HTTP %s => %s", i, status, _short(raw_check))

            if isinstance(raw_check, dict) and raw_check.get("code") in (401, 1004, 1049, 1060):
                raise AuthExpiredError(f"/check 鉴权失败: {raw_check}")

            state = check.get("state")
            message = str(check.get("message") or "")
            id_hash = check.get("idHash") or check.get("id_hash")
            check_step_id = check.get("stepId")

            if state == CHECK_STATE_EXHAUSTED or (
                not id_hash and ("用完" in message or "明天" in message)
            ):
                logger.info(
                    "😴 [%s] 抽奖次数已用完，停止（本轮成功 %s 次）: state=%s msg=%s",
                    i,
                    success_draws,
                    state,
                    message.replace("\n", " / "),
                )
                results.append({"step": "check", "exhausted": True, "data": raw_check})
                break

            # check 未直接给 idHash，但给了 stepId → 走 /ad 换票
            if not id_hash and check_step_id is not None:
                try:
                    sid = int(check_step_id)
                except (TypeError, ValueError):
                    sid = step_id
                logger.info(
                    "📺 [%s] check 无 idHash，尝试 /ad advertisementId=%s stepId=%s",
                    i,
                    advertisement_id,
                    sid,
                )
                ad_status, ad_data, id_hash = self.request_ad_id_hash(
                    advertisement_id=advertisement_id,
                    step_id=sid,
                )
                logger.info("📺 [%s] /ad HTTP %s => %s", i, ad_status, _short(ad_data))
                if isinstance(ad_data, dict) and ad_data.get("code") in (401, 1004, 1049, 1060):
                    raise AuthExpiredError(f"/ad 鉴权失败: {ad_data}")
                results.append({"step": "ad", "data": ad_data, "idHash": id_hash})
                if not id_hash:
                    consecutive_fail += 1
                    if consecutive_fail >= 3:
                        logger.warning("⚠️ [%s] 连续无法获取 idHash，停止广告抽奖", i)
                        break
                    if i < max_rounds:
                        sleep_random(interval_lo, interval_hi, label="广告抽奖")
                    continue

            if not id_hash:
                # 兼容：个别账号 check 不吐 idHash 时，用配置 stepId 试一次 /ad
                if state == CHECK_STATE_CAN_DRAW or not check:
                    logger.info(
                        "📺 [%s] check 未返回 idHash，回退 /ad(default stepId=%s)",
                        i,
                        step_id,
                    )
                    ad_status, ad_data, id_hash = self.request_ad_id_hash(
                        advertisement_id=advertisement_id,
                        step_id=step_id,
                    )
                    logger.info("📺 [%s] /ad HTTP %s => %s", i, ad_status, _short(ad_data))
                    results.append({"step": "ad_fallback", "data": ad_data, "idHash": id_hash})
                if not id_hash:
                    logger.error(
                        "❌ [%s] 未获取到 idHash（state=%s msg=%s）。"
                        "若 /ad 返回 5000，说明 advertisementId/stepId 与账号当前任务不匹配，"
                        "应以 /check 为准，勿写死参数。",
                        i,
                        state,
                        message.replace("\n", " / "),
                    )
                    results.append({"step": "check", "data": raw_check, "error": "no_idHash"})
                    consecutive_fail += 1
                    if consecutive_fail >= 3:
                        logger.warning("⚠️ [%s] 连续失败，停止广告抽奖", i)
                        break
                    if i < max_rounds:
                        sleep_random(interval_lo, interval_hi, label="广告抽奖")
                    continue

            consecutive_fail = 0
            logger.info("🎯 [%s] idHash=%s 请求开奖", i, id_hash)
            status2, second = self.draw_with_id_hash(str(id_hash))
            logger.info("🎲 [%s] 抽奖 HTTP %s => %s", i, status2, _short(second))
            if isinstance(second, dict) and second.get("code") == CODE_OK:
                gift = second.get("data") if isinstance(second.get("data"), dict) else {}
                gift_id = (gift or {}).get("giftId")
                success_draws += 1
                if gift_id is not None:
                    gift_ids.append(gift_id)
                logger.info(
                    "🎉 [%s] 抽奖成功 giftId=%s（累计成功 %s）",
                    i,
                    gift_id,
                    success_draws,
                )
            elif isinstance(second, dict) and second.get("code") == CODE_TURN_USED:
                logger.info("♻️ [%s] 该 idHash 已使用", i)
            results.append({"idHash": id_hash, "check": raw_check, "turn": second})

            if i < max_rounds:
                sleep_random(interval_lo, interval_hi, label="广告抽奖")
        else:
            # while 正常耗尽上限（未 break）
            logger.warning(
                "⚠️ [%s] 已达抽奖上限 %s 次（成功 %s），若仍有次数可调大 KLF_AD_TIMES 或保持 0 自适应",
                self.account.name,
                max_rounds,
                success_draws,
            )

        logger.info(
            "🏁 [%s] 广告抽奖结束：尝试 %s 轮，成功 %s 次",
            self.account.name,
            i,
            success_draws,
        )
        return {
            "rounds": i,
            "success_draws": success_draws,
            "gift_ids": gift_ids,
            "items": results,
        }


class AuthExpiredError(Exception):
    pass


def _short(obj: Any, limit: int = 400) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "..."


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _count_free_ok(free_results: Any) -> int:
    if not isinstance(free_results, list):
        return 0
    n = 0
    for item in free_results:
        if isinstance(item, dict) and item.get("code") == CODE_OK:
            n += 1
    return n


def _ad_stats(ad_results: Any) -> tuple[int, list[Any], bool]:
    """返回 (成功次数, giftIds, 是否今日已用完)。"""
    success = 0
    gifts: list[Any] = []
    exhausted = False
    items: list[Any] = []
    if isinstance(ad_results, dict):
        try:
            success = int(ad_results.get("success_draws") or 0)
        except (TypeError, ValueError):
            success = 0
        if isinstance(ad_results.get("gift_ids"), list):
            gifts = list(ad_results["gift_ids"])
        if isinstance(ad_results.get("items"), list):
            items = ad_results["items"]
    elif isinstance(ad_results, list):
        items = ad_results

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("exhausted"):
            exhausted = True
        turn = item.get("turn")
        if isinstance(turn, dict) and turn.get("code") == CODE_OK:
            if not isinstance(ad_results, dict) or "success_draws" not in ad_results:
                success += 1
            data = turn.get("data") if isinstance(turn.get("data"), dict) else {}
            gid = (data or {}).get("giftId")
            if gid is not None and gid not in gifts:
                gifts.append(gid)
    return success, gifts, exhausted


def run_account(account: Account, cfg: AppConfig, cache: dict[str, Any]) -> dict[str, Any]:
    client = KlfClient(account, timeout=cfg.timeout, token_style=cfg.token_style)
    summary: dict[str, Any] = {
        "name": account.name,
        "phone": account.phone,
        "ok": False,
        "free_ok": 0,
        "ad_ok": 0,
        "gift_ids": [],
        "exhausted": False,
    }
    interval_lo, interval_hi = cfg.draw_interval_range()

    try:
        client.ensure_auth(cache)
    except Exception as e:
        summary["error"] = f"登录失败: {e}"
        logger.error("❌ [%s] %s", account.name, summary["error"])
        return summary

    if cfg.dry_run:
        summary["ok"] = True
        summary["dry_run"] = True
        summary["token_style"] = client._resolved_token_style
        logger.info(
            "🧪 [%s] DRY_RUN，跳过抽奖（z-token style=%s）",
            account.name,
            client._resolved_token_style,
        )
        return summary

    def _do_draw() -> None:
        logger.info(
            "🎁 [%s] === 免费抽奖 %s 次（间隔 %.0f–%.0fs）===",
            account.name,
            cfg.free_times,
            interval_lo,
            interval_hi,
        )
        free_results = client.request_free(
            cfg.free_times,
            interval_lo=interval_lo,
            interval_hi=interval_hi,
        )
        summary["free"] = free_results
        summary["free_ok"] = _count_free_ok(free_results)

        ad_mode = (
            "按 /check 自适应至用完"
            if cfg.ad_times <= 0
            else f"最多 {cfg.ad_times} 次"
        )
        logger.info(
            "🎰 [%s] === 广告抽奖（%s，间隔 %.0f–%.0fs）===",
            account.name,
            ad_mode,
            interval_lo,
            interval_hi,
        )
        ad_results = client.ad_loop(
            cfg.ad_times,
            interval_lo=interval_lo,
            interval_hi=interval_hi,
            advertisement_id=cfg.advertisement_id,
            step_id=cfg.step_id,
        )
        summary["ad"] = ad_results
        ad_ok, gifts, exhausted = _ad_stats(ad_results)
        summary["ad_ok"] = ad_ok
        summary["gift_ids"] = gifts
        summary["exhausted"] = exhausted
        summary["ok"] = True
        summary["token_style"] = client._resolved_token_style
        cache[account.cache_key()] = client.dump_auth_for_cache()
        save_token_cache(cache)

    try:
        _do_draw()
    except AuthExpiredError as e:
        logger.warning("🔄 [%s] %s，尝试重新登录", account.name, e)
        cache.pop(account.cache_key(), None)
        save_token_cache(cache)
        try:
            client.login()
            cache[account.cache_key()] = client.dump_auth_for_cache()
            save_token_cache(cache)
            _do_draw()
            summary["relogin"] = True
        except Exception as e2:
            summary["error"] = f"重登后仍失败: {e2}"
            logger.error("❌ [%s] %s", account.name, summary["error"])
    except Exception as e:
        summary["error"] = str(e)
        logger.exception("❌ [%s] 执行异常: %s", account.name, e)

    return summary


def format_notify_title(results: list[dict[str, Any]]) -> str:
    ok_n = sum(1 for r in results if r.get("ok") and not r.get("error"))
    n = len(results)
    if n == 0:
        return "快乐蜂抽奖"
    if ok_n == n:
        return f"快乐蜂抽奖 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"快乐蜂抽奖 ❌ 0/{n}"
    return f"快乐蜂抽奖 ⚠️ {ok_n}/{n}"


def format_notify_body(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    total_free = 0
    total_ad = 0
    for r in results:
        name = r.get("name") or "账号"
        free_ok = int(r.get("free_ok") or 0)
        ad_ok = int(r.get("ad_ok") or 0)
        total_free += free_ok
        total_ad += ad_ok
        gifts = r.get("gift_ids") or []
        if r.get("error"):
            lines.append(f"❌ {name}")
            lines.append(f"   失败：{r.get('error')}")
            continue
        if r.get("dry_run"):
            lines.append(f"🧪 {name}  dry-run")
            continue
        mark = "✅" if r.get("ok") else "❌"
        lines.append(f"{mark} {name}")
        lines.append(f"   🎁 免费成功：{free_ok}")
        lines.append(f"   🎰 广告成功：{ad_ok}")
        if gifts:
            lines.append(f"   🎁 giftId：{', '.join(str(g) for g in gifts)}")
        if r.get("exhausted"):
            lines.append("   😴 今日次数已用完")
        if r.get("relogin"):
            lines.append("   🔄 中途重登后完成")
    lines.append("")
    ok_n = sum(1 for r in results if r.get("ok") and not r.get("error"))
    fail_n = len(results) - ok_n
    lines.append(f"📊 账号：成功 {ok_n} · 失败 {fail_n}（共 {len(results)}）")
    lines.append(f"🎲 抽奖：免费 {total_free} · 广告 {total_ad}")
    return "\n".join(lines)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="快乐蜂抽奖（手机号+密码）")
    parser.add_argument(
        "-c",
        "--config",
        default="",
        help="本地 config.yaml 路径（默认 ./config.yaml）",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只登录不抽奖")
    args = parser.parse_args(argv)
    setup_logging(args.verbose)

    cfg = load_config_from_env()
    if cfg is None:
        cfg_path = Path(args.config) if args.config else SCRIPT_DIR / "config.yaml"
        if cfg_path.is_file():
            cfg = load_config_yaml(cfg_path)
        else:
            logger.error(
                "❌ 未找到账号配置。请设置环境变量 KLF_ACCOUNTS / KLF=手机号#密码，"
                "或创建 %s",
                SCRIPT_DIR / "config.yaml",
            )
            return 1

    if args.dry_run:
        cfg.dry_run = True

    lo, hi = cfg.draw_interval_range()
    logger.info(
        "🐝 快乐蜂抽奖启动 · 账号 %s · 间隔 %s",
        len(cfg.accounts),
        f"{lo:.0f}s" if lo == hi else f"{lo:.0f}–{hi:.0f}s 随机",
    )

    cache = load_token_cache()
    results: list[dict[str, Any]] = []
    for idx, acc in enumerate(cfg.accounts):
        logger.info("👤 >>>>>>>> 账号 %s/%s: %s <<<<<<<<", idx + 1, len(cfg.accounts), acc.name)
        results.append(run_account(acc, cfg, cache))
        if idx < len(cfg.accounts) - 1 and cfg.inter_account_delay > 0:
            logger.info("⏳ 账号间等待 %s 秒...", cfg.inter_account_delay)
            time.sleep(cfg.inter_account_delay)

    ok_n = sum(1 for r in results if r.get("ok") and not r.get("error"))
    fail_n = len(results) - ok_n
    logger.info("🏁 === 全部完成：成功 %s / 失败 %s / 共 %s ===", ok_n, fail_n, len(results))
    for r in results:
        if r.get("error"):
            logger.info("  ❌ %s: %s", r.get("name"), r.get("error"))
        else:
            logger.info(
                "  ✅ %s: free=%s ad=%s%s",
                r.get("name"),
                r.get("free_ok", 0),
                r.get("ad_ok", 0),
                " (dry-run)" if r.get("dry_run") else "",
            )

    title = format_notify_title(results)
    body = format_notify_body(results)
    if cfg.bark.enabled():
        send_bark(cfg.bark, title, body)
    else:
        logger.info("📣 未配置 Bark（BARK_URL / BARK_KEY），跳过推送")

    return 0 if fail_n == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
