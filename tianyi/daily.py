#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电信营业厅（天翼）签到 + 金豆任务 + 宠物喂养 + 金豆转盘

cron: 30 8 * * *
new Env('电信营业厅签到');

基于社区脚本「电信任务加转盘」重写为仓库统一风格：
  手机号 + 服务密码 + AndroidID 走 appgologin.189.cn 统一认证，
  换取 jt-sign Ticket 后依次执行签到、任务、喂食宠物、查询金豆、转盘抽奖。

青龙环境变量（账号，必填，多账号 & 或换行）：
  TIANYI_ACCOUNTS  JSON 数组（推荐，name 即备注）
    [{"name":"主号","phone":"138...","password":"...","android_id":"..."}]
  或 chinaTelecomAccount / TIANYI_ACCOUNT：
    手机号#服务密码#AndroidID
    手机号#服务密码#AndroidID#备注
    手机号#服务密码##备注          # 不带 AndroidID（已有缓存 Token 时可不填）

可选：
  TIANYI_TIMEOUT              请求超时秒（默认 15）
  TIANYI_LIVE_ROUNDS          每个直播任务观看轮数（默认 11；0 关闭）
  TIANYI_LIVE_INTERVAL        每轮观看间隔秒（默认 15）
  TIANYI_FEED_TIMES           宠物喂食次数上限（默认 10）
  TIANYI_INTER_ACCOUNT_DELAY  账号间隔秒（默认 3）
  TIANYI_STATE_DIR            状态目录（默认 /ql/data/tianyi 或脚本旁 state/）

通知（与 hifiti / huazhu 等共用）：
  BARK_URL 或 BARK_KEY [+ BARK_SERVER]
  BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
  PUSHPLUS_TOKEN / PUSHPLUS_TOPIC
  青龙环境自动调用 notify.py

依赖：requests pycryptodome certifi（本地 yaml 再装 PyYAML）
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

try:
    import certifi
    import requests
    from Crypto.Cipher import AES, DES3, PKCS1_v1_5
    from Crypto.PublicKey import RSA
    from Crypto.Util.Padding import pad, unpad
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context
except ImportError as exc:
    print(f"❌ 缺少依赖（{exc}）：pip install requests pycryptodome certifi")
    print("   青龙：【依赖管理】 -> 【Python3】安装 requests pycryptodome certifi")
    sys.exit(1)

try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning

    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 常量（接口与密钥来自原脚本）
# ---------------------------------------------------------------------------

APP_NAME = "电信营业厅"
VERSION = "1.0.0"

LOGIN_URL = "https://appgologin.189.cn:9031/login/client/userLoginNormal"
LOGIN_XML_URL = "https://appgologin.189.cn:9031/map/clientXML"
UNIFIED_LOGIN_URL = "https://wapact.189.cn:9001/unified/user/login"

SIGN_BASE = "https://wappark.189.cn/jt-sign"
SIGN_SSO_URL = f"{SIGN_BASE}/ssoHomLogin"
SIGN_SUBMIT_URL = f"{SIGN_BASE}/webSign/sign"
SIGN_HOME_URL = f"{SIGN_BASE}/webSign/homepage"
SIGN_EXCHANGE_URL = f"{SIGN_BASE}/webSign/exchangePrize"
SIGN_STATUS_URL = f"{SIGN_BASE}/api/home/userStatusInfo"
SIGN_CONTINUE_URL = f"{SIGN_BASE}/webSign/continueSignDays"
SIGN_REWARD_URL = f"{SIGN_BASE}/paradise/receiveReward"
SIGN_OPEN_MSG_URL = f"{SIGN_BASE}/paradise/openMsg"
SIGN_POLYMERIZE_URL = f"{SIGN_BASE}/webSign/polymerize"
SIGN_FOOD_URL = f"{SIGN_BASE}/paradise/food"
SIGN_PET_URL = f"{SIGN_BASE}/paradise/getParadiseInfo"
SIGN_COIN_URL = f"{SIGN_BASE}/api/home/userCoinInfo"

SHARE_GOLD_URL = "https://appfuwu.189.cn:9021/query/sharingGetGold"
XBK_BASE = "https://xbk.189.cn/xbkapi"

TURNTABLE_QUERY_URL = "https://wapact.189.cn:9001/gateway/golden/api/queryTurnTable"
TURNTABLE_CHECK_URL = "https://wapact.189.cn:9001/gateway/standQuery/detail/check"
TURNTABLE_LOTTERY_URL = "https://wapact.189.cn:9001/gateway/golden/api/lottery"

LOGIN_RSA_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB
-----END PUBLIC KEY-----"""

DATA_RSA_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC+ugG5A8cZ3FqUKDwM57GM4io6JGcStivT8UdGt67PEOihLZTw3P7371+N47PrmsCpnTRzbTgcupKtUv8ImZalYk65dU8rjC/ridwhw9ffW2LBwvkEnDkkKKRi2liWIItDftJVBiWOh17o6gfbPoNrWORcAdcbpk2L+udld5kZNwIDAQAB
-----END PUBLIC KEY-----"""

MALL_RSA_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDIPOHtjs6p4sTlpFvrx+ESsYkEvyT4JB/dcEbU6C8+yclpcmWEvwZFymqlKQq89laSH4IxUsPJHKIOiYAMzNibhED1swzecH5XLKEAJclopJqoO95o8W63Euq6K+AKMzyZt1SEqtZ0mXsN8UPnuN/5aoB3kbPLYpfEwBbhto6yrwIDAQAB
-----END PUBLIC KEY-----"""

DES3_KEY = b"1234567`90koiuyhgtfrdews"
AES_DEFAULT_KEY = b"34d7cb0bcdf07523"
AES_LOGIN_KEY = "telecom_wap_2018"

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; U; Android 12; zh-cn) AppleWebKit/533.1 "
    "(KHTML, like Gecko) Version/5.0 Mobile Safari/533.1"
)
LOGIN_UA = "P216010901"

DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "电信营业厅"
DEFAULT_TIMEOUT = 15
DEFAULT_LIVE_ROUNDS = 11
DEFAULT_LIVE_INTERVAL = 15
DEFAULT_FEED_TIMES = 10
DEFAULT_INTER_ACCOUNT_DELAY = 3

MISSING_CONFIG_HINT = (
    "❌ 未找到账号配置。\n"
    "📝 青龙：设置 chinaTelecomAccount = 手机号#服务密码#AndroidID（多账号 & 或换行）\n"
    "📝 本地：cp config.example.yaml config.yaml 并填写"
)

IS_DEBUG = False

# 青龙面板统一通知
_ql_notify = None
try:
    from notify import send as _ql_notify  # type: ignore
except Exception:
    try:
        from utils.notify import send as _ql_notify  # type: ignore
    except Exception:
        _ql_notify = None


# ---------------------------------------------------------------------------
# 日志与小工具
# ---------------------------------------------------------------------------

def log(msg: str = "") -> None:
    print(msg, flush=True)


def debug(msg: str) -> None:
    if IS_DEBUG:
        print(f"🔍 [DEBUG] {msg}", flush=True)


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def mask_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if len(phone) >= 7:
        return f"{phone[:3]}****{phone[-4:]}"
    return phone or "未知"


BASE36_CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"


def base36_encode(value: int) -> str:
    if value <= 0:
        return "0"
    out = ""
    while value:
        value, remainder = divmod(value, 36)
        out = BASE36_CHARS[remainder] + out
    return out


def generate_device_id() -> str:
    """与星播客 H5 的 x_device_id 格式一致：d_<base36 毫秒>_<10 位随机>。"""
    stamp = base36_encode(int(time.time() * 1000))
    suffix = "".join(random.choice(BASE36_CHARS) for _ in range(10))
    return f"d_{stamp}_{suffix}"


def timestamp_str() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def shift_encode(text: str) -> str:
    """原脚本的字符位移（每个字符 +2）。"""
    return "".join(chr(ord(ch) + 2) for ch in text)


def response_message(res: Any) -> str:
    if not isinstance(res, dict):
        return ""
    return str(
        res.get("resoultMsg")
        or res.get("msg")
        or res.get("message")
        or res.get("errorMessage")
        or ""
    )


def result_code(res: Any) -> str:
    if not isinstance(res, dict):
        return ""
    for key in ("resoultCode", "code"):
        if key in res and res[key] is not None:
            return str(res[key])
    return ""


# ---------------------------------------------------------------------------
# 加密
# ---------------------------------------------------------------------------

def encrypt_des3(text: str) -> str:
    cipher = DES3.new(DES3_KEY, DES3.MODE_CBC, 8 * b"\0")
    return cipher.encrypt(pad(str(text).encode(), 8)).hex()


def decrypt_des3(text: str) -> str:
    cipher = DES3.new(DES3_KEY, DES3.MODE_CBC, 8 * b"\0")
    return unpad(cipher.decrypt(bytes.fromhex(text)), 8).decode()


def encrypt_aes(data: Any, key: Any = AES_DEFAULT_KEY, b64: bool = False) -> str:
    if isinstance(data, (dict, list)):
        data = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    cipher = AES.new(key if isinstance(key, bytes) else key.encode(), AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(str(data).encode(), 16))
    if b64:
        return base64.b64encode(encrypted).decode()
    return encrypted.hex()


def encrypt_rsa(data: Any, key_type: str = "data", out: str = "hex") -> str:
    key_map = {"data": DATA_RSA_KEY, "mall": MALL_RSA_KEY}
    cipher = PKCS1_v1_5.new(RSA.import_key(key_map[key_type]))
    if isinstance(data, (dict, list)):
        data = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    text = str(data)
    chunks = [text[i : i + 32].encode() for i in range(0, len(text), 32)]
    if out == "b64":
        return base64.b64encode(b"".join(cipher.encrypt(chunk) for chunk in chunks)).decode()
    return "".join(cipher.encrypt(chunk).hex() for chunk in chunks)


def encrypt_login_rsa(data: str) -> str:
    cipher = PKCS1_v1_5.new(RSA.import_key(LOGIN_RSA_KEY))
    return base64.b64encode(cipher.encrypt(data.encode())).decode()


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    phone: str
    password: str
    android_id: str = ""


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = DEFAULT_BARK_GROUP
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""
    pushplus_token: str = ""
    pushplus_topic: str = ""

    def bark_enabled(self) -> bool:
        return bool(self.bark_url or self.bark_key)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    timeout: int = DEFAULT_TIMEOUT
    live_rounds: int = DEFAULT_LIVE_ROUNDS
    live_interval: int = DEFAULT_LIVE_INTERVAL
    feed_times: int = DEFAULT_FEED_TIMES
    inter_account_delay: int = DEFAULT_INTER_ACCOUNT_DELAY
    state_dir: str = ""
    user_agent: str = DEFAULT_UA


def _normalize_bark(url: str, key: str) -> tuple[str, str]:
    url, key = (url or "").strip(), (key or "").strip()
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    return url, key


def load_notify_from_env() -> NotifyConfig:
    bark_url, bark_key = _normalize_bark(
        _env("BARK_URL") or _env("BARK_PUSH"),
        _env("BARK_KEY") or _env("BARK_DEVICE_KEY"),
    )
    return NotifyConfig(
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=_env("BARK_GROUP", DEFAULT_BARK_GROUP) or DEFAULT_BARK_GROUP,
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
        pushplus_token=_env("PUSHPLUS_TOKEN"),
        pushplus_topic=_env("PUSHPLUS_TOPIC"),
    )


def _parse_account_item(item: dict[str, Any], index: int) -> Optional[Account]:
    phone = str(item.get("phone") or item.get("mobile") or item.get("phoneNum") or "").strip()
    password = str(item.get("password") or item.get("pwd") or "").strip()
    if not phone or not password:
        return None
    name = str(
        item.get("name") or item.get("note") or item.get("remark") or f"账号{index}"
    ).strip()
    android_id = str(
        item.get("android_id") or item.get("androidId") or item.get("device_id") or ""
    ).strip()
    return Account(name=name, phone=phone, password=password, android_id=android_id)


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("TIANYI_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"TIANYI_ACCOUNTS[{i}] 必须是对象")
        acc = _parse_account_item(item, i + 1)
        if acc:
            accounts.append(acc)
    return accounts


def _parse_account_line(line: str, index: int) -> Optional[Account]:
    parts = line.split("#", 3)
    phone = parts[0].strip()
    password = parts[1].strip() if len(parts) > 1 else ""
    android_id = parts[2].strip() if len(parts) > 2 else ""
    name = parts[3].strip() if len(parts) > 3 else ""
    if not phone or not password:
        return None
    return Account(
        name=name or f"账号{index}",
        phone=phone,
        password=password,
        android_id=android_id,
    )


def _parse_accounts_from_env() -> list[Account]:
    raw_json = _env("TIANYI_ACCOUNTS")
    if raw_json:
        try:
            accounts = _parse_accounts_json(raw_json)
            if accounts:
                return accounts
        except Exception as exc:
            log(f"⚠️ TIANYI_ACCOUNTS 解析失败，回退到分隔字符串：{exc}")

    raw = (
        _env("chinaTelecomAccount")
        or _env("TIANYI_ACCOUNT")
        or _env("TELECOM_ACCOUNTS")
    )
    accounts = []
    for i, line in enumerate(re.split(r"[&\n]", raw), 1):
        line = line.strip()
        if not line:
            continue
        acc = _parse_account_line(line, i)
        if acc:
            accounts.append(acc)
    return accounts


def _merge_accounts(*groups: list[Account]) -> list[Account]:
    seen: set[str] = set()
    merged: list[Account] = []
    for group in groups:
        for acc in group:
            if not acc.phone or not acc.password or acc.phone in seen:
                continue
            seen.add(acc.phone)
            merged.append(acc)
    return merged


def _default_state_dir() -> str:
    override = _env("TIANYI_STATE_DIR")
    if override:
        return override
    if Path("/ql/data").is_dir():
        return "/ql/data/tianyi"
    return str(SCRIPT_DIR / "state")


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("本地 yaml 配置需要 PyYAML：pip install PyYAML") from exc
    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or [], 1):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i - 1}] 格式错误")
        acc = _parse_account_item(item, i)
        if acc:
            accounts.append(acc)

    # 兼容 bark: 与 notify:（bark_url / bark_key）两种写法
    bark = raw.get("bark") or raw.get("notify") or {}
    pushplus = raw.get("pushplus") or {}
    env_notify = load_notify_from_env()
    bark_url, bark_key = _normalize_bark(
        str(bark.get("url") or bark.get("bark_url") or ""),
        str(bark.get("key") or bark.get("bark_key") or ""),
    )
    notify = NotifyConfig(
        bark_url=env_notify.bark_url or bark_url,
        bark_key=env_notify.bark_key or bark_key,
        bark_server=(env_notify.bark_server if env_notify.bark_enabled() else str(bark.get("server") or DEFAULT_BARK_SERVER)).rstrip("/"),
        bark_group=_env("BARK_GROUP") or str(bark.get("group") or DEFAULT_BARK_GROUP),
        bark_sound=env_notify.bark_sound or str(bark.get("sound") or ""),
        bark_icon=env_notify.bark_icon or str(bark.get("icon") or ""),
        bark_level=env_notify.bark_level or str(bark.get("level") or ""),
        pushplus_token=env_notify.pushplus_token or str(pushplus.get("token") or ""),
        pushplus_topic=env_notify.pushplus_topic or str(pushplus.get("topic") or ""),
    )
    return AppConfig(
        accounts=accounts,
        notify=notify,
        timeout=int(raw.get("timeout") or DEFAULT_TIMEOUT),
        live_rounds=(
            int(raw["live_rounds"])
            if raw.get("live_rounds") is not None
            else DEFAULT_LIVE_ROUNDS
        ),
        live_interval=int(raw.get("live_interval") or DEFAULT_LIVE_INTERVAL),
        feed_times=int(raw.get("feed_times") or DEFAULT_FEED_TIMES),
        inter_account_delay=int(raw.get("inter_account_delay") or DEFAULT_INTER_ACCOUNT_DELAY),
        state_dir=str(raw.get("state_dir") or ""),
        user_agent=str(raw.get("user_agent") or DEFAULT_UA),
    )


def resolve_config(config_path: Optional[str] = None) -> AppConfig:
    yaml_path = Path(config_path).expanduser() if config_path else SCRIPT_DIR / "config.yaml"
    yaml_cfg = load_config_yaml(yaml_path) if yaml_path.is_file() else None

    env_accounts = _parse_accounts_from_env()
    yaml_accounts = list(yaml_cfg.accounts) if yaml_cfg else []
    accounts = _merge_accounts(env_accounts, yaml_accounts)
    if not accounts:
        raise FileNotFoundError(MISSING_CONFIG_HINT)

    cfg = yaml_cfg or AppConfig()
    cfg.accounts = accounts
    if yaml_cfg is None:
        cfg.notify = load_notify_from_env()

    cfg.timeout = _env_int("TIANYI_TIMEOUT", cfg.timeout)
    cfg.live_rounds = _env_int("TIANYI_LIVE_ROUNDS", cfg.live_rounds)
    cfg.live_interval = _env_int("TIANYI_LIVE_INTERVAL", cfg.live_interval)
    cfg.feed_times = _env_int("TIANYI_FEED_TIMES", cfg.feed_times)
    cfg.inter_account_delay = _env_int("TIANYI_INTER_ACCOUNT_DELAY", cfg.inter_account_delay)
    cfg.state_dir = _env("TIANYI_STATE_DIR") or cfg.state_dir or _default_state_dir()
    cfg.user_agent = _env("TIANYI_UA") or cfg.user_agent or DEFAULT_UA
    return cfg


# ---------------------------------------------------------------------------
# 本地状态（Token 缓存）
# ---------------------------------------------------------------------------

def _state_file(cfg: AppConfig) -> Path:
    return Path(cfg.state_dir).expanduser() / "token_cache.json"


def load_state(cfg: AppConfig) -> dict[str, Any]:
    path = _state_file(cfg)
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        debug(f"读取状态缓存失败: {exc}")
    return {}


def save_state(cfg: AppConfig, state: dict[str, Any]) -> None:
    path = _state_file(cfg)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log(f"⚠️ 写入状态缓存失败: {exc}")


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

class LegacySSLAdapter(HTTPAdapter):
    """电信部分网关仍使用旧版 TLS 套件。"""

    def init_poolmanager(self, *args: Any, **kwargs: Any) -> Any:
        ctx = create_urllib3_context(ciphers="DEFAULT@SECLEVEL=1:!aNULL:!eNULL:!MD5")
        ctx.check_hostname = False
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


class TelecomClient:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.verify = certifi.where()
        self.session.headers.update({"User-Agent": cfg.user_agent or DEFAULT_UA})
        self.session.mount("https://", LegacySSLAdapter())

    def api(self, url: str, method: str = "POST", *, raw: bool = False, headers: Optional[dict[str, str]] = None, **kwargs: Any) -> Any:
        request_headers = dict(headers or {})
        for attempt in range(3):
            try:
                resp = self.session.request(
                    method,
                    url,
                    timeout=self.cfg.timeout,
                    headers=request_headers,
                    **kwargs,
                )
                if raw:
                    return resp.text
                try:
                    data = resp.json()
                except ValueError:
                    debug(f"响应非 JSON: {url} -> {resp.text[:120]}")
                    return {}
                return data if isinstance(data, dict) else {}
            except Exception as exc:
                if attempt < 2:
                    debug(f"请求异常，重试 {attempt + 1}/2: {exc}")
                    time.sleep(1.0 * (attempt + 1))
                    continue
                log(f"⚠️ 请求异常: {url} -> {exc}")
                return "" if raw else {}
        return "" if raw else {}

    # --- 登录 ---

    def _fresh_login(self, account: Account) -> Optional[dict[str, Any]]:
        if not account.android_id:
            log(
                f"❌ [{account.name}] 缺少 AndroidID，格式应为 "
                "手机号#服务密码#AndroidID（已有缓存 Token 时可省略）"
            )
            return None

        masked = mask_phone(account.phone)
        log(f"📡 [登录] {masked} 正在请求新 Token…")
        timestamp = timestamp_str()
        android_shift = shift_encode(account.android_id)
        body = {
            "headerInfos": {
                "code": "userLoginNormal",
                "timestamp": timestamp,
                "broadAccount": "",
                "broadToken": "",
                "clientType": "#13.1.0#channel38#Xiaomi 22021211RC#",
                "provinceCode": "",
                "shopId": "20002",
                "source": "110003",
                "sourcePassword": "Sid98s",
                "token": "",
                "userLoginName": shift_encode(account.phone),
            },
            "content": {
                "attach": "test",
                "fieldData": {
                    "signSignatureString": "",
                    "loginType": "4",
                    "accountType": "",
                    "loginAuthCipherAsymmertric": encrypt_login_rsa(
                        f"iPhone 14 15.4.{account.android_id[:12]}"
                        f"{account.phone}{timestamp}{account.password}0$$$0."
                    ),
                    "deviceUid": "",
                    "phoneNum": shift_encode(account.phone),
                    "isChinatelecom": "",
                    "systemVersion": "12",
                    "androidId": android_shift,
                    "loginAuthCipher": "",
                    "authentication": shift_encode(account.password),
                },
            },
        }
        res = self.api(LOGIN_URL, json=body, headers={"User-Agent": LOGIN_UA})
        response_data = (res.get("responseData") or {}) if isinstance(res, dict) else {}
        login_data = response_data.get("data") or {}
        login_result = login_data.get("loginSuccessResult")
        if (
            not isinstance(login_result, dict)
            or not login_result.get("token")
            or not login_result.get("userId")
        ):
            code = response_data.get("resultCode", "")
            desc = response_data.get("resultDesc") or response_message(res) or "无响应数据"
            log(f"❌ [登录失败] {masked} [{code}] {desc}")
            return None

        log(f"✅ [登录] {masked} 新 Token 获取成功")
        return {
            **login_result,
            "rawAndroidId": account.android_id,
            "androidId": android_shift,
        }

    def _get_ticket(self, account: Account, token: str, user_id: str) -> tuple[Optional[str], bool]:
        xml = (
            "<Request><HeaderInfos>"
            f"<Code>getSingle</Code><Timestamp>{timestamp_str()}</Timestamp>"
            "<BroadAccount></BroadAccount><BroadToken></BroadToken>"
            "<ClientType>#9.6.1#channel50#iPhone 14 Pro Max#</ClientType>"
            "<ShopId>20002</ShopId><Source>110003</Source>"
            "<SourcePassword>Sid98s</SourcePassword>"
            f"<Token>{token}</Token><UserLoginName>{account.phone}</UserLoginName>"
            "</HeaderInfos><Content><Attach>test</Attach><FieldData>"
            f"<TargetId>{encrypt_des3(user_id)}</TargetId><Url>4a6862274835b451</Url>"
            "</FieldData></Content></Request>"
        )
        res_xml = self.api(
            LOGIN_XML_URL,
            data=xml,
            headers={"Content-Type": "application/xml"},
            raw=True,
        )
        masked = mask_phone(account.phone)
        if isinstance(res_xml, str) and ("过期" in res_xml or "校验错误" in res_xml):
            log(f"🔁 [Token失效] {masked} 将重新登录")
            return None, True
        if not isinstance(res_xml, str) or "<Ticket>" not in res_xml:
            log(f"❌ [Ticket异常] {masked} 响应: {str(res_xml)[:100]}")
            return None, False
        try:
            ticket = res_xml.split("<Ticket>")[1].split("</Ticket>")[0]
            return decrypt_des3(ticket), False
        except Exception as exc:
            log(f"❌ [Ticket解析失败] {masked}: {exc}")
            return None, False

    def _unified_login(self, uid: str) -> str:
        body = encrypt_aes(
            {
                "ticket": uid,
                "backUrl": "https%3A%2F%2Fwapact.189.cn%3A9001",
                "platformCode": "P201010301",
                "loginType": 2,
            },
            AES_LOGIN_KEY,
            b64=True,
        )
        res = self.api(
            UNIFIED_LOGIN_URL,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        if isinstance(res, dict) and str(res.get("code")) == "0":
            token = str((res.get("biz") or {}).get("token") or "")
            if token:
                return f"Bearer {token}"
        debug(f"统一登录未获取 Bearer: {response_message(res)}")
        return ""

    def login(self, account: Account, state: dict[str, Any], retry: bool = True) -> Optional[dict[str, Any]]:
        cached = state.get(account.phone)
        if not isinstance(cached, dict):
            cached = {}

        if not (cached.get("token") and cached.get("userId")):
            fresh = self._fresh_login(account)
            if not fresh:
                return None
            state[account.phone] = fresh
            save_state(self.cfg, state)
            cached = fresh
        else:
            debug(f"[登录] {mask_phone(account.phone)} 使用缓存 Token")

        uid, expired = self._get_ticket(account, str(cached["token"]), str(cached["userId"]))
        if expired:
            state.pop(account.phone, None)
            save_state(self.cfg, state)
            if retry:
                return self.login(account, state, retry=False)
            return None
        if not uid:
            return None

        user = {**cached, "uid": uid, "phoneNbr": account.phone}
        authorization = self._unified_login(uid)
        if authorization:
            user["Authorization"] = authorization
        else:
            log(f"⚠️ [{mask_phone(account.phone)}] 未获取转盘 Bearer，抽奖将跳过")
        return user


# ---------------------------------------------------------------------------
# 单账号任务流程
# ---------------------------------------------------------------------------

class AccountRunner:
    def __init__(
        self,
        client: TelecomClient,
        account: Account,
        cfg: AppConfig,
        state: dict[str, Any],
    ):
        self.client = client
        self.account = account
        self.cfg = cfg
        self.state = state
        self.user: dict[str, Any] = {}
        self._xtoken = ""
        self._device_id = ""

    @property
    def masked(self) -> str:
        return mask_phone(self.account.phone)

    def _signed(self, path: str, payload: dict[str, Any], sign_key: str) -> Any:
        return self.client.api(
            f"{SIGN_BASE}/{path}",
            json={"para": encrypt_rsa(payload)},
            headers={"sign": sign_key},
        )

    def run(self, check_only: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.account.name,
            "phone": self.masked,
            "ok": False,
            "sign": "",
            "awards": [],
            "tasks": [],
            "feed": "",
            "pet": "",
            "coin": "",
            "coin_note": "",
            "draws": 0,
            "prizes": [],
            "message": "",
        }

        log(f"🔐 [{self.account.name}] 登录 {self.masked}")
        user = self.client.login(self.account, self.state, retry=True)
        if not user:
            result["message"] = "登录失败（检查手机号 / 服务密码 / AndroidID）"
            log(f"❌ [{self.account.name}] {result['message']}")
            return result
        self.user = user
        log(f"👤 [{self.account.name}] {self.masked} 登录成功")

        sso = self.client.api(SIGN_SSO_URL, method="GET", params={"ticket": self.user["uid"]})
        sign_key = str(sso.get("sign") or "") if isinstance(sso, dict) else ""
        if not sign_key:
            result["message"] = "jt-sign SSO 失败，无法签到"
            log(f"❌ [{self.account.name}] {result['message']}")
            return result

        if check_only:
            self._query_pet(result, sign_key)
            self._query_coin(result, sign_key)
            result["ok"] = True
            result["message"] = "账号正常"
            return result

        sign_ok = self._sign(result, sign_key)
        self._awards(result, sign_key)
        self._tasks(result, sign_key)
        self._feed(result, sign_key)
        self._query_pet(result, sign_key)
        self._query_coin(result, sign_key)
        self._lottery(result)

        result["ok"] = sign_ok
        result["message"] = "签到完成" if sign_ok else "签到未成功"
        log(f"{'✅' if sign_ok else '⚠️'} [{self.account.name}] {result['message']}")
        return result

    # --- 签到与奖励 ---

    def _sign(self, result: dict[str, Any], sign_key: str) -> bool:
        res = self.client.api(
            SIGN_SUBMIT_URL,
            json={"encode": encrypt_aes({"phone": self.account.phone, "date": int(time.time() * 1000)})},
            headers={"sign": sign_key},
        )
        if not isinstance(res, dict) or not res:
            result["sign"] = "无响应"
            log(f"❌ [签到] {self.masked} 无响应")
            return False
        message = response_message(res) or "成功"
        result["sign"] = message
        failed = any(word in message for word in ("失败", "错误", "异常", "过期", "无效", "未登录"))
        log(f"{'✅' if not failed else '⚠️'} [签到] {self.masked}: {message}")
        return not failed

    def _awards(self, result: dict[str, Any], sign_key: str) -> None:
        checks = (
            ("api/home/userStatusInfo", "signDay", ["7"], "连签"),
            ("webSign/continueSignDays", "continueSignDays", ["15", "28"], "累签"),
        )
        for path, key, days_list, label in checks:
            res = self._signed(path, {"phone": self.account.phone}, sign_key)
            if not isinstance(res, dict):
                continue
            data = res.get("data")
            days = data.get(key) if isinstance(data, dict) and key in data else res.get(key, 0)
            days = str(days)
            log(f"📅 [{label}] {self.masked}: {days} 天")
            if days in days_list:
                exchange = self._signed(
                    "webSign/exchangePrize",
                    {"phone": self.account.phone, "type": days},
                    sign_key,
                )
                message = response_message(exchange) or "已领取"
                result["awards"].append(f"{label} {days} 天：{message}")
                log(f"🎁 [领奖] {self.masked} {label} {days} 天: {message}")

    # --- 任务列表 ---

    def _tasks(self, result: dict[str, Any], sign_key: str) -> None:
        tasks = self._signed(
            "webSign/homepage",
            {"phone": self.account.phone, "shopId": "20001", "type": "hg_qd_zrwzjd"},
            sign_key,
        )
        if not isinstance(tasks, dict):
            log(f"❌ [任务] {self.masked} 任务列表获取失败")
            return
        items = ((tasks.get("data") or {}).get("biz") or {}).get("adItems") or []
        for task in items:
            if str(task.get("taskState")) not in ("0", "1"):
                continue
            title = self._task_title(task)
            content = str(task.get("contentOne") or "")

            message = ""
            if content == "3":
                if not task.get("rewardId"):
                    continue
                res = self._signed(
                    "paradise/receiveReward",
                    {"phone": self.account.phone, "rewardId": task["rewardId"]},
                    sign_key,
                )
                message = response_message(res) or "已领取"
            elif content == "5":
                res = self._signed(
                    "paradise/openMsg",
                    {"phone": self.account.phone},
                    sign_key,
                )
                message = response_message(res) or "已打开"
            elif content == "6":
                res = self.client.api(
                    SHARE_GOLD_URL,
                    json={
                        "headerInfos": {
                            "code": "sharingGetGold",
                            "timestamp": timestamp_str(),
                            "broadAccount": "",
                            "broadToken": "",
                            "clientType": "#9.6.1#channel50#iPhone 14 Pro Max#",
                            "shopId": "20002",
                            "source": "110003",
                            "sourcePassword": "Sid98s",
                            "token": self.user.get("token", ""),
                            "userLoginName": self.user.get("phoneNbr", ""),
                        },
                        "content": {
                            "attach": "test",
                            "fieldData": {
                                "shareSource": "3",
                                "userId": self.user.get("userId", ""),
                                "account": shift_encode(self.user.get("phoneNbr", "")),
                            },
                        },
                    },
                )
                message = response_message(res) or "已分享"
            elif content in ("10", "13"):
                message = self._watch_live()
            elif content == "18":
                res = self._signed(
                    "webSign/polymerize",
                    {"phone": self.account.phone, "jobId": task.get("taskId")},
                    sign_key,
                )
                message = response_message(res) or "已完成"
            else:
                continue

            if message:
                result["tasks"].append(f"{title}：{message}")
                log(f"📝 [任务] {self.masked} {title}: {message}")
            time.sleep(2)

    @staticmethod
    def _task_title(task: dict[str, Any]) -> str:
        text = str(task.get("title") or "").strip()
        return text.split()[0] if text else "任务"

    def _x_device_id(self) -> str:
        if self._device_id:
            return self._device_id
        cached = self.state.get("_x_device_id")
        if isinstance(cached, str) and cached:
            self._device_id = cached
            return cached
        self._device_id = generate_device_id()
        self.state["_x_device_id"] = self._device_id
        save_state(self.cfg, self.state)
        return self._device_id

    def _fetch_xtoken(self) -> str:
        device_id = self._x_device_id()
        try:
            resp = self.client.session.get(
                f"{XBK_BASE}/api/auth/jump",
                params={
                    "userID": self.user.get("uid", ""),
                    "version": "9.3.3",
                    "type": "room",
                    "l": "renwu",
                },
                headers={"X-Device-Id": device_id},
                allow_redirects=False,
                timeout=self.cfg.timeout,
            )
        except Exception as exc:
            log(f"⚠️ [直播] 获取跳转失败: {exc}")
            return ""
        match = re.search(r"usercode=([A-Za-z0-9_\-]+)", resp.headers.get("location") or "")
        if not match:
            return ""
        token_res = self.client.api(
            f"{XBK_BASE}/api/auth/userinfo/codeToken",
            json={"usercode": match.group(1)},
            headers={"X-Device-Id": device_id},
        )
        if isinstance(token_res, dict) and str(token_res.get("code")) == "0":
            return str((token_res.get("data") or {}).get("token") or "")
        debug(f"[直播] codeToken 失败: {response_message(token_res) or result_code(token_res)}")
        return ""

    def _watch_live(self) -> str:
        if self.cfg.live_rounds <= 0:
            return "已关闭直播观看"
        if not self._xtoken:
            self._xtoken = self._fetch_xtoken()
        if not self._xtoken:
            return "未获取直播 Token，跳过"

        device_id = self._x_device_id()
        headers = {
            "Authorization": f"Bearer {encrypt_rsa(self._xtoken, 'mall', 'b64')}",
            "X-Device-Id": device_id,
        }
        done = 0
        for _ in range(self.cfg.live_rounds):
            live_id = random.randint(1000, 1999)
            init = self.client.api(
                f"{XBK_BASE}/lteration/liveTask/index/watchLiveInit",
                json={"period": 1, "liveId": live_id},
                headers=headers,
            )
            if not isinstance(init, dict) or str(init.get("code")) != "0":
                break
            time.sleep(self.cfg.live_interval)
            watched = self.client.api(
                f"{XBK_BASE}/lteration/liveTask/index/watchLive",
                json={"period": 1, "liveId": live_id, "key": init.get("data")},
                headers=headers,
            )
            if not isinstance(watched, dict) or str(watched.get("code")) != "0":
                break
            done += 1
            log(f"📺 [直播] {self.masked} 观看直播[{live_id}]成功")
        return f"观看直播 {done} 次" if done else "观看直播未成功"

    # --- 宠物 / 金豆 / 抽奖 ---

    def _feed(self, result: dict[str, Any], sign_key: str) -> None:
        count = 0
        for i in range(self.cfg.feed_times):
            res = self._signed("paradise/food", {"phone": self.account.phone}, sign_key)
            message = response_message(res)
            if not message or "最大" in message:
                break
            count += 1
            log(f"🍖 [喂食] {self.masked} 第{i + 1}次: {message}")
            time.sleep(1)
        result["feed"] = f"{count} 次" if count else "无需喂食 / 已达上限"

    def _query_pet(self, result: dict[str, Any], sign_key: str) -> None:
        res = self._signed("paradise/getParadiseInfo", {"phone": self.account.phone}, sign_key)
        if isinstance(res, dict) and result_code(res) == "0":
            level_info = (res.get("userInfo") or {}).get("levelInfoMap") or {}
            if level_info:
                result["pet"] = (
                    f"Lv.{level_info.get('level', 0)}"
                    f"（成长 {level_info.get('growthValue', 0)}"
                    f"/{level_info.get('fullGrowthCoinValue', 0)}）"
                )
            else:
                result["pet"] = "未返回等级数据"
        else:
            result["pet"] = f"查询失败：{response_message(res) or result_code(res) or '无响应'}"
        log(f"🐾 [宠物] {self.masked} {result['pet']}")

    def _query_coin(self, result: dict[str, Any], sign_key: str) -> None:
        res = self._signed("api/home/userCoinInfo", {"phone": self.account.phone}, sign_key)
        if isinstance(res, dict) and result_code(res) == "0":
            result["coin"] = str(res.get("totalCoin") or 0)
            amount_ex = res.get("amountEx")
            if amount_ex:
                expire = ""
                try:
                    if res.get("expireDate"):
                        expire = datetime.fromtimestamp(int(res["expireDate"]) / 1000).strftime("%Y-%m")
                except Exception:
                    expire = ""
                result["coin_note"] = f"{expire}月底将过期 {amount_ex} 金豆"
            log(f"🪙 [金豆] {self.masked} 余额: {result['coin']}")
            if result["coin_note"]:
                log(f"⏳ [金豆] {self.masked} {result['coin_note']}")
        else:
            result["coin"] = f"查询失败：{response_message(res) or result_code(res) or '无响应'}"
            log(f"🪙 [金豆] {self.masked} {result['coin']}")

    def _lottery(self, result: dict[str, Any]) -> None:
        authorization = self.user.get("Authorization")
        if not authorization:
            return

        headers = {"Authorization": authorization}
        table = self.client.api(
            TURNTABLE_QUERY_URL,
            method="GET",
            params={"userType": 1, "_": int(time.time() * 1000)},
            headers=headers,
        )
        if not isinstance(table, dict) or str(table.get("code")) != "0":
            log(f"⚠️ [抽奖] {self.masked} 转盘查询失败: {response_message(table) or '无响应'}")
            return
        activity_id = ((table.get("biz") or {}).get("wzTurntable") or {}).get("code")
        if not activity_id:
            log(f"⚠️ [抽奖] {self.masked} 未获取活动 ID")
            return

        check = self.client.api(
            TURNTABLE_CHECK_URL,
            method="GET",
            params={"activityId": activity_id},
            headers=headers,
        )
        info = ((check.get("biz") or {}).get("resultInfo") or {}) if isinstance(check, dict) else {}
        try:
            remaining = int(info.get("userMaximum") or 0) - int(info.get("userCount") or 0)
        except (TypeError, ValueError):
            remaining = 0
        remaining = max(0, remaining)
        result["draws"] = remaining
        log(f"🎰 [抽奖] {self.masked} 可抽 {remaining} 次")

        for _ in range(remaining):
            lottery = self.client.api(
                TURNTABLE_LOTTERY_URL,
                json={"activityId": activity_id},
                headers=headers,
            )
            prize = ""
            if isinstance(lottery, dict):
                prize = str(
                    ((lottery.get("biz") or {}).get("resultInfo") or {}).get("title") or ""
                )
            if prize:
                result["prizes"].append(prize)
                log(f"🎁 [抽奖] {self.masked} 抽奖结果: {prize}")
            else:
                log(f"🎁 [抽奖] {self.masked} 未中奖 / 次数已用完")
            time.sleep(2)


# ---------------------------------------------------------------------------
# 汇总与通知
# ---------------------------------------------------------------------------

def _join_items(items: list[str], limit: int = 6) -> str:
    if not items:
        return ""
    if len(items) <= limit:
        return "；".join(items)
    return "；".join(items[:limit]) + f"；等 {len(items)} 项"


def format_summary(results: list[dict[str, Any]], check_only: bool = False) -> str:
    lines = [f"📅 {datetime.now().strftime('%m-%d %H:%M')}", ""]
    ok_count = sum(1 for item in results if item.get("ok"))
    for i, res in enumerate(results):
        lines.append(f"{'✅' if res.get('ok') else '❌'} {res.get('name') or '账号'}")
        lines.append(f"   👤 账号：{res.get('phone') or '未知'}")
        if check_only:
            if res.get("ok"):
                if res.get("pet"):
                    lines.append(f"   🐾 宠物：{res['pet']}")
                if res.get("coin"):
                    lines.append(f"   🪙 金豆：{res['coin']}")
            elif res.get("message"):
                lines.append(f"   ⚠️ {res['message']}")
        else:
            lines.append(f"   ✍️ 签到：{res.get('sign') or '未执行'}")
            if res.get("awards"):
                lines.append(f"   🎁 奖励：{_join_items(res['awards'], 4)}")
            if res.get("tasks"):
                lines.append(f"   📋 任务：{_join_items(res['tasks'])}")
            if res.get("feed"):
                lines.append(f"   🍖 喂食：{res['feed']}")
            if res.get("pet"):
                lines.append(f"   🐾 宠物：{res['pet']}")
            if res.get("coin"):
                coin = res["coin"]
                if res.get("coin_note"):
                    coin += f"（{res['coin_note']}）"
                lines.append(f"   🪙 金豆：{coin}")
            if res.get("draws"):
                prize_text = _join_items(res.get("prizes") or [], 6) or "未中奖"
                lines.append(f"   🎰 抽奖：{res['draws']} 次 · {prize_text}")
            if not res.get("ok") and res.get("message"):
                lines.append(f"   ⚠️ {res['message']}")
        if i < len(results) - 1:
            lines.append("")
    lines.append("")
    lines.append("────────")
    if ok_count == len(results):
        lines.append(f"📊 合计：{ok_count}/{len(results)} 全部成功 🎉")
    elif ok_count == 0:
        lines.append(f"📊 合计：0/{len(results)} 全部失败")
    else:
        lines.append(f"📊 合计：成功 {ok_count} · 失败 {len(results) - ok_count}")
    return "\n".join(lines)


def format_notify_title(results: list[dict[str, Any]], check_only: bool = False) -> str:
    action = "查询" if check_only else "签到"
    ok_count = sum(1 for item in results if item.get("ok"))
    total = len(results)
    if total == 0:
        return f"{APP_NAME} 每日{action}"
    if ok_count == total:
        return f"{APP_NAME} {action} ✅ {ok_count}/{total}"
    if ok_count == 0:
        return f"{APP_NAME} {action} ❌ 0/{total}"
    return f"{APP_NAME} {action} ⚠️ {ok_count}/{total}"


def send_notifications(cfg: AppConfig, results: list[dict[str, Any]], check_only: bool = False) -> None:
    title = format_notify_title(results, check_only)
    content = format_summary(results, check_only)

    # 1. 青龙面板统一通知
    if _ql_notify:
        try:
            log("📣 通知状态: 正在调用青龙面板统一通知发送推送 🚀")
            _ql_notify(title, content)
            return
        except Exception as exc:
            debug(f"青龙通知发送失败: {exc}")

    # 2. Bark
    if cfg.notify.bark_enabled():
        endpoint = (
            cfg.notify.bark_url.rstrip("/")
            if cfg.notify.bark_url
            else f"{cfg.notify.bark_server.rstrip('/')}/{cfg.notify.bark_key}"
        )
        payload: dict[str, Any] = {
            "title": title,
            "body": content,
            "group": cfg.notify.bark_group or DEFAULT_BARK_GROUP,
        }
        for option in ("bark_sound", "bark_icon", "bark_level"):
            value = getattr(cfg.notify, option)
            if value:
                payload[option.replace("bark_", "")] = value
        try:
            resp = requests.post(endpoint, json=payload, timeout=15)
            if resp.status_code >= 400:
                requests.get(
                    f"{endpoint}/{quote(title, safe='')}/{quote(content, safe='')}",
                    timeout=15,
                )
            log("📣 通知状态: 已发送至 iOS Bark 推送 📱")
        except Exception as exc:
            log(f"⚠️ Bark 推送失败: {exc}")
    else:
        log("📣 未配置 BARK_URL / BARK_KEY，跳过 Bark 推送")

    # 3. PushPlus
    if cfg.notify.pushplus_token:
        try:
            requests.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": cfg.notify.pushplus_token,
                    "title": title,
                    "content": content.replace("\n", "<br>"),
                    "template": "html",
                    "topic": cfg.notify.pushplus_topic or "",
                },
                timeout=15,
            )
            log("📣 通知状态: 已发送至 PushPlus 微信推送 💬")
        except Exception as exc:
            log(f"⚠️ PushPlus 推送失败: {exc}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="电信营业厅签到 + 金豆任务 + 转盘")
    parser.add_argument("--config", help="本地 yaml 配置路径")
    parser.add_argument("--check", action="store_true", help="仅登录并查询宠物/金豆，不签到、不做任务、不抽奖")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    args = parser.parse_args(argv)

    global IS_DEBUG
    IS_DEBUG = args.debug or _env("DEBUG") in ("1", "true", "yes")

    log("=" * 50)
    log(f"📱 {APP_NAME} v{VERSION} " + ("（仅查询）" if args.check else ""))
    log(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 50)

    try:
        cfg = resolve_config(args.config)
    except FileNotFoundError as exc:
        log(str(exc) or MISSING_CONFIG_HINT)
        return 1
    except Exception as exc:
        log(f"❌ 读取配置失败: {exc}")
        return 1

    log(f"👥 共 {len(cfg.accounts)} 个账号")
    state = load_state(cfg)
    results: list[dict[str, Any]] = []

    for i, account in enumerate(cfg.accounts):
        log("=" * 50)
        log(f"🚀 开始执行 {account.name}（{mask_phone(account.phone)}）")
        runner = AccountRunner(TelecomClient(cfg), account, cfg, state)
        results.append(runner.run(check_only=args.check))
        if i < len(cfg.accounts) - 1 and cfg.inter_account_delay > 0:
            log(f"⏳ 等待 {cfg.inter_account_delay} 秒后执行下一个账号…")
            time.sleep(cfg.inter_account_delay)

    summary = format_summary(results, check_only=args.check)
    log("\n" + summary)
    log("\n🎊 所有账号任务执行完成!")

    send_notifications(cfg, results, check_only=args.check)
    return 0 if any(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
