#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
望潮 App ·「阅读有礼」自动阅读 + 抽奖

cron: 30 8 * * *
new Env('望潮阅读有礼');

流程（纯 HTTP，不依赖 ADB/UI）：
  1. 手机号 + 密码登录（RSA 加密密码 → passport → zbtxz 换 session）
     也可直接填 account_id + session_id（抓包备用）
  2. 登录阅读有礼 H5 会话
  3. 拉取当日任务列表，对未完成文章 SM2 上报已读
  4. 满额后可选抽奖

青龙环境变量（推荐手机号密码）：
  WANGCHAO_ACCOUNTS  JSON 数组
    [{"name":"主号","phone":"1xxxxxxxxxx","password":"xxx"}]
  或对齐变量（& 分隔多账号）：
    WANGCHAO_PHONE / WANGCHAO_PASSWORD / WANGCHAO_NAME

也支持旧方式（抓包 session）：
    account_id + session_id + device_id

可选：
  WANGCHAO_LOTTERY=0
  WANGCHAO_BASE_URL=https://xmt.taizhou.com.cn

青龙环境变量（Bark 通知，与 hifiti 共用）：
  BARK_URL   完整推送地址，如 https://api.day.app/你的Key/
  或 BARK_KEY + 可选 BARK_SERVER（默认 https://api.day.app）
  可选：BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

依赖：requests, gmssl, pycryptodomex（或 pycryptodome）, PyYAML(本地可选)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import random
import string
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

import requests

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

try:
    from gmssl import sm2
except ImportError as e:
    print("缺少 gmssl: pip install gmssl", file=sys.stderr)
    raise SystemExit(1) from e

try:
    from Cryptodome.Cipher import PKCS1_v1_5
    from Cryptodome.PublicKey import RSA
except ImportError:
    try:
        from Crypto.Cipher import PKCS1_v1_5  # type: ignore
        from Crypto.PublicKey import RSA  # type: ignore
    except ImportError as e:
        print(
            "缺少 pycryptodome/pycryptodomex: pip install pycryptodomex",
            file=sys.stderr,
        )
        raise SystemExit(1) from e

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "https://xmt.taizhou.com.cn"
DEFAULT_VAPP_URL = "https://vapp.taizhou.com.cn"
DEFAULT_PASSPORT_URL = "https://passport.tmuyun.com"
DEFAULT_LOTTERY_BASE = "https://srv-app.taizhou.com.cn"
DEFAULT_ACTIVITY_ID = 67
TENANT_ID = "64"
CLIENT_ID = "10019"
# vapp 请求签名密钥（写死在客户端）
VAPP_SIGN_SECRET = "FR*r!isE5W"
APP_VERSION = "8.0.2"

# passport 密码 RSA 公钥（PKCS#1）
PASSPORT_RSA_PUBLIC_KEY_B64 = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD6XO7e9YeAOs+cFqwa7ETJ+WXizP"
    "qQeXv68i5vqw9pFREsrqiBTRcg7wB0RIp3rJkDpaeVJLsZqYm5TW7FWx/iOiXFc+zC"
    "PvaKZric2dXCw27EvlH5rq+zwIPDAJHGAfnn1nmQH7wR3PCatEIb8pz5GFlTHMlluw"
    "4ZYmnOwg+thwIDAQAB"
)

# 阅读有礼 H5 SM2 公钥（sm-crypto doEncrypt cipherMode=1）
SM2_PUBLIC_KEY = (
    "04A50803A27F000D6B310607EBA2A1C899E82872C0B538CA41DB6F0183B4C7E1"
    "64DAFC6946ABF93C8AF1C0AD96D0E770D29264EF9F907DDBAE97A2A0BB1036D4AC"
)

DEFAULT_UA_WEB = (
    f"Mozilla/5.0 (Linux; Android 15; PKG110) AppleWebKit/537.36 "
    f"(KHTML, like Gecko) Version/4.0 Chrome/131.0.0.0 Mobile Safari/537.36;"
    f"xsb_wangchao;xsb_wangchao;{APP_VERSION};native_app"
)
DEFAULT_UA_APP = (
    f"{APP_VERSION};00000000-699e-76bc-ffff-ffff9e3d172a;"
    f"OPPO PKG110;Android;15;huawei"
)
DEFAULT_BARK_SERVER = "https://api.day.app"

SCRIPT_DIR = Path(__file__).resolve().parent
logger = logging.getLogger("wangchao")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class Account:
    name: str
    phone: str = ""
    password: str = ""
    account_id: str = ""
    session_id: str = ""
    device_id: str = "1"

    def has_password(self) -> bool:
        return bool(self.phone.strip() and self.password)

    def has_session(self) -> bool:
        return bool(self.account_id.strip() and self.session_id.strip())

    def ready(self) -> bool:
        return self.has_password() or self.has_session()


@dataclass
class NotifyConfig:
    """Bark 为主（与 hifiti 环境变量兼容）。"""

    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "望潮阅读有礼"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""  # active / timeSensitive / passive
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
    accounts: List[Account]
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    base_url: str = DEFAULT_BASE_URL
    vapp_url: str = DEFAULT_VAPP_URL
    passport_url: str = DEFAULT_PASSPORT_URL
    lottery_base: str = DEFAULT_LOTTERY_BASE
    activity_id: int = DEFAULT_ACTIVITY_ID
    do_lottery: bool = True
    timeout: int = 20
    click_cooldown: float = 8.0
    jitter: float = 1.5
    # 多账号间隔（秒），避免 /api/account/init 触发「操作过于频繁」
    account_interval: float = 20.0
    # init 限流时最大重试次数
    init_max_retries: int = 5
    log_level: str = "INFO"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _split_env(key: str) -> List[str]:
    raw = _env(key)
    if not raw:
        return []
    return [x.strip() for x in raw.split("&") if x.strip()]


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
        bark_group=_env("BARK_GROUP", "望潮阅读有礼"),
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        serverchan_key=_env("SERVERCHAN_KEY") or _env("PUSH_KEY"),
        webhook_url=_env("WEBHOOK_URL"),
    )


def _account_from_dict(item: Dict[str, Any], index: int) -> Account:
    return Account(
        name=str(item.get("name") or f"account-{index}"),
        phone=str(item.get("phone") or item.get("mobile") or item.get("username") or ""),
        password=str(item.get("password") or item.get("pwd") or ""),
        account_id=str(
            item.get("account_id")
            or item.get("accountId")
            or item.get("id")
            or ""
        ),
        session_id=str(item.get("session_id") or item.get("sessionId") or ""),
        device_id=str(
            item.get("device_id")
            or item.get("deviceId")
            or item.get("device_no")
            or "1"
        ),
    )


def load_accounts_from_env() -> List[Account]:
    raw = os.environ.get("WANGCHAO_ACCOUNTS", "").strip()
    if raw:
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError("WANGCHAO_ACCOUNTS 必须是 JSON 数组")
        return [_account_from_dict(x, i) for i, x in enumerate(data)]

    # 手机号密码
    phones = _split_env("WANGCHAO_PHONE")
    passwords = _split_env("WANGCHAO_PASSWORD")
    names = _split_env("WANGCHAO_NAME")
    if phones:
        accounts = []
        for i, phone in enumerate(phones):
            accounts.append(
                Account(
                    name=names[i] if i < len(names) else f"account-{i}",
                    phone=phone,
                    password=passwords[i] if i < len(passwords) else "",
                )
            )
        return accounts

    # 抓包 session 备用
    ids = _split_env("WANGCHAO_ACCOUNT_ID")
    sessions = _split_env("WANGCHAO_SESSION_ID")
    devices = _split_env("WANGCHAO_DEVICE_ID")
    if not ids:
        return []
    accounts = []
    for i, aid in enumerate(ids):
        accounts.append(
            Account(
                name=names[i] if i < len(names) else f"account-{i}",
                account_id=aid,
                session_id=sessions[i] if i < len(sessions) else "",
                device_id=devices[i] if i < len(devices) else "1",
            )
        )
    return accounts


def load_config(path: Optional[Path] = None) -> AppConfig:
    env_accounts = load_accounts_from_env()
    raw: Dict[str, Any] = {}
    cfg_path = path or (SCRIPT_DIR / "config.yaml")
    if cfg_path.exists():
        if yaml is None:
            raise RuntimeError("读取 config.yaml 需要 PyYAML: pip install PyYAML")
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    accounts = env_accounts
    if not accounts:
        for i, a in enumerate(raw.get("accounts") or []):
            accounts.append(_account_from_dict(a, i))

    if not accounts:
        raise ValueError(
            "未配置账号。请填写 phone/password，或 WANGCHAO_ACCOUNTS / config.yaml"
        )

    api = raw.get("api") or {}
    lottery = raw.get("lottery") or {}
    log = raw.get("log") or {}
    n = raw.get("notify") or {}

    do_lottery = True
    if _env("WANGCHAO_LOTTERY") in ("0", "false", "False"):
        do_lottery = False
    elif "enable" in lottery:
        do_lottery = bool(lottery.get("enable"))

    account_interval = float(
        _env("WANGCHAO_ACCOUNT_INTERVAL")
        or api.get("account_interval")
        or 20
    )
    init_max_retries = int(
        _env("WANGCHAO_INIT_RETRIES") or api.get("init_max_retries") or 5
    )

    # 环境变量优先于 yaml（方便青龙统一配 BARK_*）
    env_notify = load_notify_from_env()
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or str(n.get("bark_url") or ""),
        bark_key=env_notify.bark_key or str(n.get("bark_key") or ""),
        bark_server=(
            env_notify.bark_server
            if env_notify.bark_key or env_notify.bark_url
            else str(n.get("bark_server") or DEFAULT_BARK_SERVER)
        ).rstrip("/"),
        bark_group=(
            env_notify.bark_group
            if _env("BARK_GROUP")
            else str(n.get("bark_group") or "望潮阅读有礼")
        ),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
        serverchan_key=env_notify.serverchan_key
        or str(n.get("serverchan_key") or ""),
        webhook_url=env_notify.webhook_url or str(n.get("webhook_url") or ""),
    )

    return AppConfig(
        accounts=accounts,
        notify=notify,
        base_url=str(
            _env("WANGCHAO_BASE_URL") or api.get("base_url") or DEFAULT_BASE_URL
        ).rstrip("/"),
        vapp_url=str(api.get("vapp_url") or DEFAULT_VAPP_URL).rstrip("/"),
        passport_url=str(api.get("passport_url") or DEFAULT_PASSPORT_URL).rstrip(
            "/"
        ),
        lottery_base=str(lottery.get("base_url") or DEFAULT_LOTTERY_BASE).rstrip(
            "/"
        ),
        activity_id=int(lottery.get("activity_id") or DEFAULT_ACTIVITY_ID),
        do_lottery=do_lottery,
        timeout=int(api.get("timeout") or 20),
        click_cooldown=float(api.get("click_cooldown") or 8),
        jitter=float(api.get("jitter") or 1.5),
        account_interval=account_interval,
        init_max_retries=init_max_retries,
        log_level=str(_env("WANGCHAO_LOG_LEVEL") or log.get("level") or "INFO"),
    )


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 加解密 / 签名
# ---------------------------------------------------------------------------


def rsa_encrypt_password(password: str) -> str:
    """passport 密码：RSA PKCS1_v1_5 加密后 Base64。"""
    key = RSA.import_key(base64.b64decode(PASSPORT_RSA_PUBLIC_KEY_B64))
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def vapp_sign(path: str, session_id: str, request_id: str, ts: str) -> str:
    """
    X-SIGNATURE = SHA256(
      path && sessionId && requestId && timestamp && secret && tenantId
    )
    """
    raw = f"{path}&&{session_id}&&{request_id}&&{ts}&&{VAPP_SIGN_SECRET}&&{TENANT_ID}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sm2_encrypt_signature(payload: Dict[str, Any]) -> str:
    """H5 sm-crypto sm2.doEncrypt(msg, pubkey, 1) → C1C3C2 hex。"""
    msg = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    pub = SM2_PUBLIC_KEY[2:] if SM2_PUBLIC_KEY.startswith("04") else SM2_PUBLIC_KEY
    crypt = sm2.CryptSM2(public_key=pub, private_key=None, mode=1)
    enc = crypt.encrypt(msg.encode("utf-8"))
    if enc is None:
        raise RuntimeError("SM2 加密失败，请重试")
    if isinstance(enc, bytes):
        return enc.hex()
    return str(enc)


def _uuid_rid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------


class WangChaoClient:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_UA_WEB,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        self.userinfo: Dict[str, Any] = {}
        # 匿名 / 登录后的 vapp session（签名用）
        self.vapp_session_id: str = ""

    # ---- 通用 ----

    def _sleep(self, base: Optional[float] = None) -> None:
        t = self.cfg.click_cooldown if base is None else base
        t = max(0.0, t + random.uniform(0, self.cfg.jitter))
        if t > 0:
            time.sleep(t)

    def _parse(self, resp: requests.Response) -> Dict[str, Any]:
        try:
            data = resp.json()
        except Exception:
            logger.error("非 JSON HTTP %s: %s", resp.status_code, resp.text[:300])
            return {"code": -1, "msg": f"HTTP {resp.status_code}", "data": None}
        return data if isinstance(data, dict) else {"code": -1, "data": data}

    def _vapp_headers(
        self, path: str, session_id: Optional[str] = None, account_id: str = ""
    ) -> Dict[str, str]:
        sid = session_id if session_id is not None else self.vapp_session_id
        rid = _uuid_rid()
        ts = str(int(time.time() * 1000))
        headers = {
            "X-SESSION-ID": sid or "",
            "X-REQUEST-ID": rid,
            "X-TIMESTAMP": ts,
            "X-SIGNATURE": vapp_sign(path, sid or "", rid, ts),
            "X-TENANT-ID": TENANT_ID,
            "User-Agent": DEFAULT_UA_APP,
            "Content-Type": "application/x-www-form-urlencoded",
            "Cache-Control": "no-cache",
        }
        if account_id:
            headers["X-ACCOUNT-ID"] = account_id
        return headers

    # ---- 密码登录 ----

    def init_anonymous_session(self) -> str:
        """
        POST /api/account/init → 匿名 session（登录换票前置）。

        多账号连打会被限流 code=10400「操作过于频繁」，自动退避重试。
        """
        path = "/api/account/init"
        url = f"{self.cfg.vapp_url}{path}"
        max_retries = max(1, int(self.cfg.init_max_retries))
        last_data: Dict[str, Any] = {}

        for attempt in range(1, max_retries + 1):
            headers = self._vapp_headers(path, session_id="")
            resp = self.session.post(
                url, headers=headers, data="", timeout=self.cfg.timeout
            )
            data = self._parse(resp)
            last_data = data
            code = str(data.get("code"))
            if code == "0":
                sess = (data.get("data") or {}).get("session") or {}
                sid = str(sess.get("id") or "")
                if not sid:
                    raise RuntimeError(f"init 未返回 session.id: {data}")
                self.vapp_session_id = sid
                logger.info("[%s] 匿名 session=%s", self.account.name, sid)
                return sid

            msg = str(data.get("message") or data.get("msg") or "")
            # 10400 / 文案含「频繁」→ 限流，退避后重试
            rate_limited = code == "10400" or "频繁" in msg or "稍后再试" in msg
            if rate_limited and attempt < max_retries:
                # 15s, 25s, 35s… 加一点抖动
                wait = 10 + attempt * 10 + random.uniform(0, 3)
                logger.warning(
                    "[%s] init 限流 code=%s %s，%.0f 秒后重试 (%s/%s)",
                    self.account.name,
                    code,
                    msg,
                    wait,
                    attempt,
                    max_retries,
                )
                time.sleep(wait)
                continue
            raise RuntimeError(f"初始化 session 失败: {data}")

        raise RuntimeError(f"初始化 session 失败: {last_data}")

    def login_with_password(self) -> Tuple[str, str]:
        """
        手机号+密码 → (account_id, session_id)

        1) passport credential_auth（RSA 密码）
        2) vapp /api/zbtxz/login 用 authorization_code 换正式 session
        """
        phone = self.account.phone.strip()
        password = self.account.password
        if not phone or not password:
            raise ValueError("phone/password 为空")

        self.init_anonymous_session()

        enc_pwd = rsa_encrypt_password(password)
        auth_url = f"{self.cfg.passport_url}/web/oauth/credential_auth"
        headers = {
            "User-Agent": f"ANDROID;15;{CLIENT_ID};{APP_VERSION};1.0;null;PKG110",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "Cache-Control": "no-cache",
            "X-REQUEST-ID": _uuid_rid(),
        }
        form = {
            "client_id": CLIENT_ID,
            "password": enc_pwd,
            "phone_number": phone,
        }
        logger.info("[%s] passport 登录 phone=%s …", self.account.name, phone)
        resp = self.session.post(
            auth_url, headers=headers, data=form, timeout=self.cfg.timeout
        )
        data = self._parse(resp)
        if str(data.get("code")) not in ("0", "200"):
            msg = data.get("message") or data.get("msg") or resp.text[:200]
            raise RuntimeError(f"密码登录失败: {msg} (code={data.get('code')})")

        auth = (data.get("data") or {}).get("authorization_code") or {}
        code = auth.get("code") or data.get("data", {}).get("code")
        if not code:
            raise RuntimeError(f"未拿到 authorization_code: {data}")

        # 换正式 session
        path = "/api/zbtxz/login"
        url = f"{self.cfg.vapp_url}{path}"
        headers = self._vapp_headers(path, session_id=self.vapp_session_id)
        body = {
            "check_token": "",
            "code": code,
            "token": "",
            "type": "-1",
            "union_id": "",
        }
        resp2 = self.session.post(
            url, headers=headers, data=body, timeout=self.cfg.timeout
        )
        data2 = self._parse(resp2)
        if str(data2.get("code")) != "0":
            msg = data2.get("message") or data2.get("msg") or resp2.text[:200]
            raise RuntimeError(f"换取 session 失败: {msg}")

        payload = data2.get("data") or {}
        account_id = str((payload.get("account") or {}).get("id") or "")
        session_id = str((payload.get("session") or {}).get("id") or "")
        if not account_id or not session_id:
            raise RuntimeError(f"登录响应缺少 account/session: {data2}")

        self.account.account_id = account_id
        self.account.session_id = session_id
        self.vapp_session_id = session_id
        nick = (payload.get("account") or {}).get("nick_name") or ""
        logger.info(
            "[%s] 密码登录成功 nick=%s account_id=%s session_id=%s…",
            self.account.name,
            nick,
            account_id,
            session_id[:12],
        )
        return account_id, session_id

    def ensure_credentials(self) -> None:
        """优先密码登录；否则使用配置中的 session。"""
        if self.account.has_password():
            self.login_with_password()
            return
        if self.account.has_session():
            self.vapp_session_id = self.account.session_id
            logger.info(
                "[%s] 使用配置的 session account_id=%s",
                self.account.name,
                self.account.account_id,
            )
            return
        raise ValueError("账号未配置 phone/password 或 account_id/session_id")

    # ---- 阅读有礼 ----

    def gift_login(self) -> bool:
        """GET /prod-api/user-read/app/login"""
        url = f"{self.cfg.base_url}/prod-api/user-read/app/login"
        params = {
            "id": self.account.account_id,
            "sessionId": self.account.session_id,
            "deviceId": self.account.device_id or "1",
        }
        headers = {
            "User-Agent": DEFAULT_UA_WEB,
            "Referer": f"{self.cfg.base_url}/readingLuck-v5/",
            "X-Requested-With": "com.shangc.tiennews.taizhou",
        }
        logger.info("[%s] 登录阅读有礼 …", self.account.name)
        resp = self.session.get(
            url, params=params, headers=headers, timeout=self.cfg.timeout
        )
        data = self._parse(resp)
        if str(data.get("code")) == "200":
            self.userinfo = data.get("data") or {}
            logger.info(
                "[%s] 阅读有礼登录成功 name=%s needYz=%s cookies=%s",
                self.account.name,
                self.userinfo.get("name"),
                self.userinfo.get("needYz"),
                list(self.session.cookies.keys()),
            )
            if self.userinfo.get("needYz"):
                logger.warning(
                    "[%s] needYz=true，请先在 App 内完成验证码",
                    self.account.name,
                )
            return True
        msg = data.get("msg") or data.get("message") or resp.text[:200]
        logger.error("[%s] 阅读有礼登录失败 code=%s %s", self.account.name, data.get("code"), msg)
        return False

    @staticmethod
    def today_str() -> str:
        return datetime.now().strftime("%Y%m%d")

    def get_task(self) -> Optional[Dict[str, Any]]:
        day = self.today_str()
        url = f"{self.cfg.base_url}/prod-api/user-read/list/{day}"
        headers = {
            "User-Agent": DEFAULT_UA_WEB,
            "Referer": f"{self.cfg.base_url}/readingLuck-v5/",
            "X-Requested-With": "com.shangc.tiennews.taizhou",
        }
        resp = self.session.get(url, headers=headers, timeout=self.cfg.timeout)
        data = self._parse(resp)
        if str(data.get("code")) == "200":
            task = data.get("data") or {}
            logger.info(
                "[%s] 任务 %s 总计=%s 已完成=%s",
                self.account.name,
                day,
                task.get("sum"),
                task.get("completedCount"),
            )
            return task
        logger.error(
            "[%s] 获取任务失败: %s",
            self.account.name,
            data.get("msg") or data.get("message") or data,
        )
        return None

    def open_article_detail(self, news_id: Any) -> bool:
        """可选：打开 vapp 文章详情（带签名），更接近真实阅读。"""
        if not news_id:
            return False
        path = "/api/article/detail"
        url = f"{self.cfg.vapp_url}{path}"
        headers = self._vapp_headers(
            path,
            session_id=self.account.session_id,
            account_id=self.account.account_id,
        )
        resp = self.session.get(
            url, params={"id": news_id}, headers=headers, timeout=self.cfg.timeout
        )
        data = self._parse(resp)
        ok = str(data.get("code")) == "0" or data.get("message") == "success"
        if ok:
            title = (
                ((data.get("data") or {}).get("article") or {}).get("list_title")
                or ""
            )
            logger.info("[%s] 打开文章 newsId=%s %s", self.account.name, news_id, title)
        else:
            logger.debug(
                "[%s] 文章详情跳过/失败 newsId=%s %s",
                self.account.name,
                news_id,
                data.get("message") or data,
            )
        return ok

    def mark_read(self, article_id: Any) -> bool:
        """
        上报已读：/prod-api/already-read/article/new
        signature = SM2({timestamp, articleId, accountId})
        """
        payload = {
            "timestamp": int(time.time() * 1000),
            "articleId": article_id,
            "accountId": self.account.account_id,
        }
        signature = sm2_encrypt_signature(payload)
        url = f"{self.cfg.base_url}/prod-api/already-read/article/new"
        headers = {
            "User-Agent": DEFAULT_UA_WEB,
            "Referer": f"{self.cfg.base_url}/readingLuck-v5/",
            "X-Requested-With": "com.shangc.tiennews.taizhou",
        }
        resp = self.session.get(
            url, params={"signature": signature}, headers=headers, timeout=self.cfg.timeout
        )
        data = self._parse(resp)
        if str(data.get("code")) != "200":
            # 再试 POST form
            resp = self.session.post(
                url,
                data={"signature": signature},
                headers=headers,
                timeout=self.cfg.timeout,
            )
            data = self._parse(resp)

        if str(data.get("code")) == "200":
            logger.info("[%s] 已读成功 articleId=%s", self.account.name, article_id)
            return True
        logger.warning(
            "[%s] 已读失败 articleId=%s code=%s msg=%s",
            self.account.name,
            article_id,
            data.get("code"),
            data.get("msg") or data.get("message"),
        )
        return False

    def complete_reads(self, dry_run: bool = False) -> Dict[str, Any]:
        result = {
            "ok": False,
            "completed_before": 0,
            "completed_after": 0,
            "total": 0,
            "marked": 0,
            "failed": 0,
            "skipped": 0,
        }
        task = self.get_task()
        if not task:
            return result

        articles: List[Dict[str, Any]] = (
            task.get("articleIsReadList") or task.get("list") or []
        )
        total = int(task.get("sum") or len(articles) or 12)
        completed = int(task.get("completedCount") or 0)
        result["total"] = total
        result["completed_before"] = completed

        pending = [a for a in articles if not a.get("isRead")]
        logger.info(
            "[%s] 待完成 %s 篇 / 列表 %s",
            self.account.name,
            len(pending),
            len(articles),
        )

        if not pending:
            result["ok"] = completed >= total
            result["completed_after"] = completed
            result["skipped"] = len(articles)
            return result

        if dry_run:
            for a in pending:
                logger.info(
                    "[dry-run] articleId=%s newsId=%s title=%s",
                    a.get("id"),
                    a.get("newsId") or a.get("news_id"),
                    a.get("title") or a.get("list_title") or "",
                )
            result["ok"] = True
            result["skipped"] = len(pending)
            result["completed_after"] = completed
            return result

        for idx, article in enumerate(pending, 1):
            aid = article.get("id")
            news_id = article.get("newsId") or article.get("news_id")
            title = article.get("title") or article.get("list_title") or ""
            logger.info(
                "[%s] (%s/%s) %s id=%s",
                self.account.name,
                idx,
                len(pending),
                title,
                aid,
            )
            if aid is None:
                result["failed"] += 1
                continue

            # 先拉详情（失败不阻断）
            try:
                self.open_article_detail(news_id)
            except Exception as e:
                logger.debug("detail error: %s", e)
            time.sleep(random.uniform(1.0, 2.5))

            if self.mark_read(aid):
                result["marked"] += 1
            else:
                result["failed"] += 1

            if idx < len(pending):
                self._sleep()

        task2 = self.get_task()
        if task2:
            result["completed_after"] = int(task2.get("completedCount") or 0)
            result["total"] = int(task2.get("sum") or total)
        else:
            result["completed_after"] = result["completed_before"] + result["marked"]
        result["ok"] = result["completed_after"] >= result["total"]
        return result

    # ---- 抽奖 ----

    def lottery_draw(self) -> Dict[str, Any]:
        """
        抽奖站：loginWC → saveUpdate

        注意：
        - 旧接口 /save 已废弃，会固定返回「请重新打开APP参与抽奖」
        - 现行 H5 使用 /saveUpdate（circle-awsc 页，可附带阿里云 AWSC 滑块字段）
        """
        login_url = f"{self.cfg.lottery_base}/tzrb/user/loginWC"
        referer = (
            f"{self.cfg.lottery_base}/luckdraw-ra-1/"
            f"#/pages/luckdraw/circle-awsc?activityId={self.cfg.activity_id}"
        )
        headers = {
            "User-Agent": DEFAULT_UA_WEB,
            "Referer": referer,
            "X-Requested-With": "com.shangc.tiennews.taizhou",
            "Accept": "*/*",
        }
        resp = self.session.get(
            login_url,
            params={
                "accountId": self.account.account_id,
                "sessionId": self.account.session_id,
            },
            headers=headers,
            timeout=self.cfg.timeout,
        )
        data = self._parse(resp)
        if str(data.get("code")) != "200":
            msg = data.get("message") or data.get("msg") or data
            logger.error("[%s] 抽奖站登录失败: %s", self.account.name, msg)
            return {"ok": False, "msg": str(msg), "already": False}

        body = data.get("data")
        if isinstance(body, dict) and body.get("token"):
            self.session.headers["token"] = str(body["token"])

        # 现行接口：saveUpdate（旧 save 会误报「请重新打开APP」）
        draw_url = f"{self.cfg.lottery_base}/tzrb/userAwardRecordUpgrade/saveUpdate"
        form = {
            "activityId": str(self.cfg.activity_id),
            # AWSC 滑块字段；无滑块时先空着，服务端多数情况仍可处理（已抽/有次数）
            "sessionId": "",
            "sig": "",
            "token": "",
        }
        resp2 = self.session.post(
            draw_url,
            data=form,
            headers={
                **headers,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.cfg.lottery_base,
            },
            timeout=self.cfg.timeout,
        )
        data2 = self._parse(resp2)
        code = data2.get("code")
        msg = str(data2.get("msg") or data2.get("message") or "")
        prize = data2.get("data")

        already = any(
            k in msg for k in ("已抽", "明天再来", "已经参与", "次数用完", "没有抽奖")
        )
        ok = str(code) == "200" or already

        if str(code) == "200":
            logger.info("[%s] 抽奖成功 prize=%s msg=%s", self.account.name, prize, msg)
        elif already:
            logger.info("[%s] 今日已抽过: %s", self.account.name, msg)
        else:
            logger.warning("[%s] 抽奖 code=%s msg=%s", self.account.name, code, msg)
            if "重新打开" in msg or "APP" in msg:
                logger.warning(
                    "[%s] 若仍提示打开 APP，可能是活动页强校验滑块验证，"
                    "请在 App 内手动抽一次，或等待接口策略变化",
                    self.account.name,
                )

        # 最近记录
        try:
            hist = self.session.get(
                f"{self.cfg.lottery_base}/tzrb/userAwardRecordUpgrade/pageList",
                params={
                    "pageSize": 5,
                    "pageNum": 1,
                    "activityId": self.cfg.activity_id,
                },
                headers=headers,
                timeout=self.cfg.timeout,
            )
            hdata = self._parse(hist)
            records = ((hdata.get("data") or {}).get("records")) or []
            for rec in records[:5]:
                logger.info(
                    "  记录 %s %s",
                    rec.get("createTime"),
                    rec.get("awardName") or rec.get("prizeName"),
                )
        except Exception:
            pass

        return {
            "ok": ok,
            "code": code,
            "msg": msg,
            "prize": prize,
            "already": already,
        }


# ---------------------------------------------------------------------------
# 通知：Bark 为主（与 hifiti 共用 BARK_* 环境变量）
# ---------------------------------------------------------------------------


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

    payload: Dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.bark_group or "望潮阅读有礼",
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
        logger.info("Bark 通知: HTTP %s %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("Bark 通知失败: %s", e)


def send_serverchan(key: str, title: str, content: str) -> None:
    if key.startswith("sctp"):
        url = f"https://sctapi.ftqq.com/{key}.send"
    else:
        url = f"https://sctapi.ftqq.com/{key}.send"
    try:
        r = requests.post(
            url, json={"title": title, "desp": content}, timeout=10
        )
        logger.info("Server酱通知: %s", r.text[:200])
    except Exception as e:
        logger.warning("Server酱通知失败: %s", e)


def send_notify(cfg: NotifyConfig, title: str, content: str) -> None:
    if not cfg.enabled():
        logger.info("未配置通知渠道，跳过推送")
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
            logger.info("Webhook 通知: HTTP %s", r.status_code)
        except Exception as e:
            logger.warning("Webhook 通知失败: %s", e)


def format_summary(results: List[Dict[str, Any]], dry_run: bool = False) -> str:
    lines: List[str] = []
    if dry_run:
        lines.append("【dry-run】未实际上报/抽奖")
    for r in results:
        name = r.get("name") or "?"
        ok = r.get("ok")
        err = r.get("error") or ""
        read = r.get("read") or {}
        lot = r.get("lottery") or {}
        status = "✅" if ok else "❌"
        parts = [f"{status} [{name}]"]
        if read:
            parts.append(
                f"阅读 {read.get('completed_after', '?')}/{read.get('total', '?')}"
                f"（新完成 {read.get('marked', 0)}）"
            )
        if lot:
            if lot.get("already"):
                parts.append(f"抽奖: 今日已抽过（{lot.get('msg') or ''}）")
            elif lot.get("ok"):
                prize = lot.get("prize")
                msg = lot.get("msg") or "成功"
                parts.append(
                    f"抽奖: {msg}" + (f" prize={prize}" if prize is not None else "")
                )
            else:
                parts.append(f"抽奖失败: {lot.get('msg') or lot.get('code')}")
        if err:
            parts.append(f"错误: {err}")
        lines.append(" · ".join(parts) if len(parts) > 1 else parts[0])
    ok_n = sum(1 for r in results if r.get("ok"))
    lines.append(f"合计: {ok_n}/{len(results)} 成功")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_account(account: Account, cfg: AppConfig, dry_run: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "name": account.name,
        "ok": False,
        "read": None,
        "lottery": None,
        "error": "",
    }
    if not account.ready():
        out["error"] = "请配置 phone+password 或 account_id+session_id"
        logger.error("[%s] %s", account.name, out["error"])
        return out

    client = WangChaoClient(account, cfg)
    try:
        client.ensure_credentials()
        if not client.gift_login():
            out["error"] = "gift login failed"
            return out
        if client.userinfo.get("needYz"):
            out["error"] = "need verification (needYz)"
            return out

        read_result = client.complete_reads(dry_run=dry_run)
        out["read"] = read_result

        if (
            cfg.do_lottery
            and not dry_run
            and read_result.get("ok")
            and int(read_result.get("completed_after") or 0)
            >= int(read_result.get("total") or 12)
        ):
            logger.info("[%s] 阅读已满，抽奖 …", account.name)
            out["lottery"] = client.lottery_draw()
        elif cfg.do_lottery and not dry_run and not read_result.get("ok"):
            logger.info("[%s] 未完成全部阅读，跳过抽奖", account.name)

        out["ok"] = bool(read_result.get("ok"))
    except requests.RequestException as e:
        out["error"] = str(e)
        logger.exception("[%s] 网络错误: %s", account.name, e)
    except Exception as e:
        out["error"] = str(e)
        logger.exception("[%s] 异常: %s", account.name, e)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="望潮 · 阅读有礼")
    parser.add_argument(
        "-c", "--config", type=Path, default=SCRIPT_DIR / "config.yaml"
    )
    parser.add_argument("--dry-run", action="store_true", help="只登录并列任务")
    parser.add_argument("--no-lottery", action="store_true")
    parser.add_argument("--lottery-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(args.config if args.config.exists() else None)
    except Exception as e:
        print(f"配置错误: {e}", file=sys.stderr)
        print(
            "请配置 phone/password，例如:\n"
            '  WANGCHAO_ACCOUNTS=[{"name":"主号","phone":"1xxx","password":"xxx"}]\n'
            "或 cp config.example.yaml config.yaml",
            file=sys.stderr,
        )
        return 2

    if args.no_lottery:
        cfg.do_lottery = False

    setup_logging(cfg.log_level)
    logger.info(
        "望潮阅读有礼 | 账号=%s dry_run=%s lottery=%s",
        len(cfg.accounts),
        args.dry_run,
        cfg.do_lottery and not args.dry_run,
    )

    results = []
    n_acc = len(cfg.accounts)
    for idx, acc in enumerate(cfg.accounts):
        if idx > 0 and cfg.account_interval > 0:
            wait = cfg.account_interval + random.uniform(0, 3)
            logger.info(
                "多账号间隔 %.0f 秒后再跑 [%s]（%s/%s）…",
                wait,
                acc.name,
                idx + 1,
                n_acc,
            )
            time.sleep(wait)

        if args.lottery_only:
            client = WangChaoClient(acc, cfg)
            try:
                client.ensure_credentials()
                if not client.gift_login():
                    results.append(
                        {"name": acc.name, "ok": False, "error": "gift login failed"}
                    )
                    continue
                lot = client.lottery_draw()
                results.append(
                    {
                        "name": acc.name,
                        "ok": lot.get("ok"),
                        "lottery": lot,
                        "read": None,
                    }
                )
            except Exception as e:
                logger.exception("[%s] 异常: %s", acc.name, e)
                results.append({"name": acc.name, "ok": False, "error": str(e)})
        else:
            results.append(run_account(acc, cfg, dry_run=args.dry_run))

    ok_n = sum(1 for r in results if r.get("ok"))
    logger.info("完成: %s/%s 成功", ok_n, len(results))
    for r in results:
        read = r.get("read") or {}
        lot = r.get("lottery")
        logger.info(
            "  - %s ok=%s read=%s/%s marked=%s lottery=%s err=%s",
            r.get("name"),
            r.get("ok"),
            read.get("completed_after"),
            read.get("total"),
            read.get("marked"),
            (lot or {}).get("msg") if lot else "-",
            r.get("error") or "",
        )

    summary = format_summary(results, dry_run=args.dry_run)
    title = (
        f"望潮阅读有礼 {'成功' if ok_n == len(results) else '部分失败'}"
        f" ({ok_n}/{len(results)})"
    )
    # dry-run 默认不推送，避免调试刷屏；可用 WANGCHAO_NOTIFY_DRY_RUN=1 强制推
    if args.dry_run and _env("WANGCHAO_NOTIFY_DRY_RUN") not in ("1", "true", "True"):
        logger.info("dry-run 跳过通知（设 WANGCHAO_NOTIFY_DRY_RUN=1 可推送）")
    else:
        send_notify(cfg.notify, title, summary)

    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
