#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
电信 AI 奇遇活动助手（自动创作任务 + 自动领奖 + 积分兑换 / 抽奖）

cron: 0 */6 * * *
new Env('电信AI奇遇');

基于社区脚本重写（原作者 Alexin），与仓库其它项目统一风格：
  账密登录 → 电信统一认证换 Ticket → 爱音乐 SSO → 按模式执行任务。

模式 DIANXIN_MODE：
  auto    （默认）每期用免费额度做满 340 分；满 1000 分兑换 10 元话费；
          兑换后当月多余积分抽奖；最后一期攒不满则抽光防清零
  draw    全抽奖：不攒兑换，每轮积分全部投入抽奖
  save    只攒分：满 1000 兑换 10 元话费，不抽奖
  observe 只查询：仅登录查询，不做任务（新账号建议先跑这个验证登录）

青龙环境变量 DIANXIN（必填，多账号 & 或换行）：
  手机号#密码
  手机号#密码#AndroidID          # 16 位十六进制，模拟真实设备可避开 3006 风控
  手机号#密码#AndroidID#备注
  手机号#密码##备注              # 不带 AndroidID 只带备注（中间留空）

兼容旧变量：chinaTelecomAccount / AI096_ACCOUNTS / CAILING_ACCOUNTS

可选：
  DIANXIN_MAKE_COUNT     单轮制作上限（默认 17；每期上限 340 分 / 每次 20 分）
  DIANXIN_MAKE_INTERVAL  制作提交最小间隔秒（默认 20，防 10007 频控）
  DIANXIN_MAX_DRAWS      单轮抽奖上限（默认 10）
  DIANXIN_PROXY_API      代理提取 API，一号一 IP 防频控（不配置则直连）
  DIANXIN_INVITE_CODE    活动邀请码（默认沿用原脚本内置值）
  DIANXIN_NOTE           全局备注，进 Bark 标题
  DIANXIN_STATE_DIR      状态/缓存目录（青龙默认 /ql/data/dianxin）

通知（与 hifiti / fun / quark 等共用）：
  BARK_URL 或 BARK_KEY [+ BARK_SERVER]
  BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

依赖：requests pycryptodome certifi（本地 yaml 再装 PyYAML）
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import secrets
import string
import sys
import time
import xml.etree.ElementTree as telecom_et
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

try:
    import requests
    import certifi
    from Crypto.Cipher import AES, DES3, PKCS1_v1_5
    from Crypto.Util.Padding import pad, unpad
    from Crypto.PublicKey import RSA
    from requests.adapters import HTTPAdapter
    from urllib3.util.ssl_ import create_urllib3_context
except ImportError:
    print("❌ 缺少依赖：pip install requests pycryptodome certifi")
    print("   青龙：【依赖管理】->【Python3】安装 requests pycryptodome certifi")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
CST = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# 常量（活动网关，来自原脚本）
# ---------------------------------------------------------------------------

BASE_URL = "https://ai.imusic.cn"
ACTIVITY = "ai119"
DEFAULT_CHANNEL = "156000008410"
# 原脚本内置的活动邀请码（官方 H5 入场校验与会话绑定用，可用 DIANXIN_INVITE_CODE 覆盖）
DEFAULT_INVITE_CODE = base64.b64decode(
    "OWVhNDQzYjJhZjNjZDY5ODhkNTJmNzc4NmYwYzdmMjE3NzI5YjViN2ViMmMxMTFmNzg1NmQzM2JiNTUyYWNjZQ=="
).decode()
DEFAULT_ACTIVITY_URL = (
    f"{BASE_URL}/h5v/fusion/ai-luck-winnew"
    f"?cc={DEFAULT_CHANNEL}&isshare=0&invitationCode={DEFAULT_INVITE_CODE}"
)
PHONE_AWARDS = {"16320105", "16320205", "16320305"}  # 1 元话费奖品
FINAL_DRAW_DATE = datetime(2027, 1, 12, tzinfo=CST)  # 活动最后一期

DEFAULT_MAKE_COUNT = 17
DEFAULT_MAKE_INTERVAL = 20
DEFAULT_MAX_DRAWS = 10
DEFAULT_TIMEOUT = 25
DEFAULT_BARK = "https://api.day.app"
DEFAULT_BARK_GROUP = "电信AI奇遇"

ICONS = "📱🎨🎬🎰💰🎁✨🌟"


def log(msg: str = "") -> None:
    print(msg, flush=True)


def _env(key: str, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    v = _env(key)
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        return default


def mask_mobile(m: str) -> str:
    m = (m or "").strip()
    if len(m) >= 7:
        return m[:3] + "****" + m[-4:]
    return m or "?"


def running_on_qinglong() -> bool:
    return bool(_env("QL_DATA_DIR")) or Path("/ql/data").is_dir()


# ---------------------------------------------------------------------------
# 账号与配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    mobile: str
    password: str
    android_id: str = ""
    note: str = ""

    @property
    def label(self) -> str:
        return self.note or mask_mobile(self.mobile)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    mode: str = "auto"
    make_count: int = DEFAULT_MAKE_COUNT
    make_interval: int = DEFAULT_MAKE_INTERVAL
    max_draws: int = DEFAULT_MAX_DRAWS
    proxy_api: str = ""
    invite_code: str = DEFAULT_INVITE_CODE
    note: str = ""
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK
    bark_group: str = DEFAULT_BARK_GROUP
    bark_sound: str = ""
    state_dir: str = ""
    source: str = ""  # env / yaml，仅日志


def parse_accounts(raw: str) -> list[Account]:
    """
    手机号#密码
    手机号#密码#AndroidID
    手机号#密码#AndroidID#备注
    手机号#密码##备注
    多账号 & 或换行
    """
    out: list[Account] = []
    for i, part in enumerate(re.split(r"[&\n]", (raw or "").replace("\r", ""))):
        part = part.strip()
        if not part or part.startswith("#") or "#" not in part:
            continue
        segs = part.split("#")
        mobile = segs[0].strip()
        password = segs[1].strip()  # 密码占第 2 段，不含 '#'
        extra = [s.strip() for s in segs[2:]]
        android_id = ""
        note = ""
        # 第 3 段是 16 位十六进制 → AndroidID；为空字符串则是占位（手机号#密码##备注）
        if extra and re.fullmatch(r"[0-9a-fA-F]{16}", extra[0]):
            android_id = extra.pop(0)
        elif extra and extra[0] == "":
            extra.pop(0)
        if extra:
            note = extra[-1]
        if not re.fullmatch(r"1[3-9]\d{9}", mobile) or not password:
            log(f"⚠️ 第 {i + 1} 段格式错误，应为 手机号#密码[#AndroidID][#备注]")
            continue
        out.append(Account(mobile=mobile, password=password, android_id=android_id, note=note))
    return out


def _accounts_from_env() -> list[Account]:
    raw = _env("DIANXIN")
    if raw:
        return parse_accounts(raw)
    # 兼容原脚本的变量名
    for key in ("chinaTelecomAccount", "AI096_ACCOUNTS", "CAILING_ACCOUNTS"):
        raw = _env(key)
        if raw:
            return parse_accounts(raw)
    return []


def _notify_from_env() -> dict[str, str]:
    url = _env("BARK_URL") or _env("BARK_PUSH")
    key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    return {
        "bark_url": url,
        "bark_key": key,
        "bark_server": _env("BARK_SERVER") or DEFAULT_BARK,
        "bark_group": _env("BARK_GROUP"),
        "bark_sound": _env("BARK_SOUND"),
    }


def _valid_mode(mode: str) -> str:
    mode = (mode or "auto").strip().lower()
    return mode if mode in ("auto", "draw", "save", "observe") else "auto"


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _accounts_from_env()
    if not accounts:
        return None
    n = _notify_from_env()
    return AppConfig(
        accounts=accounts,
        mode=_valid_mode(_env("DIANXIN_MODE") or _env("IMUSIC_MODE") or "auto"),
        make_count=_env_int("DIANXIN_MAKE_COUNT", _env_int("IMUSIC_MAKE_COUNT", DEFAULT_MAKE_COUNT)),
        make_interval=_env_int("DIANXIN_MAKE_INTERVAL", _env_int("IMUSIC_MAKE_INTERVAL", DEFAULT_MAKE_INTERVAL)),
        max_draws=_env_int("DIANXIN_MAX_DRAWS", _env_int("IMUSIC_MAX_DRAWS", DEFAULT_MAX_DRAWS)),
        proxy_api=_env("DIANXIN_PROXY_API") or _env("IMUSIC_PROXY_API") or _env("AI096_PROXY_API"),
        invite_code=_env("DIANXIN_INVITE_CODE") or DEFAULT_INVITE_CODE,
        note=_env("DIANXIN_NOTE"),
        bark_url=n["bark_url"],
        bark_key=n["bark_key"],
        bark_server=(n["bark_server"] or DEFAULT_BARK).rstrip("/"),
        bark_group=n["bark_group"] or DEFAULT_BARK_GROUP,
        bark_sound=n["bark_sound"],
        state_dir=_env("DIANXIN_STATE_DIR"),
        source="env",
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
        mobile = str(item.get("mobile") or item.get("phone") or "").strip()
        password = str(item.get("password") or item.get("pwd") or "")
        if not mobile or not password:
            raise ValueError(f"accounts[{i}] 需要 mobile + password")
        accounts.append(
            Account(
                mobile=mobile,
                password=password,
                android_id=str(item.get("android_id") or "").strip(),
                note=str(item.get("name") or item.get("note") or "").strip(),
            )
        )
    if not accounts:
        raise ValueError(f"{path} 中 accounts 为空")

    n = raw.get("notify") if isinstance(raw.get("notify"), dict) else {}
    env_n = _notify_from_env()
    bark_url = env_n["bark_url"] or str(n.get("bark_url") or "")
    bark_key = env_n["bark_key"] or str(n.get("bark_key") or "")
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""

    return AppConfig(
        accounts=accounts,
        mode=_valid_mode(_env("DIANXIN_MODE") or str(raw.get("mode") or "auto")),
        make_count=_env_int("DIANXIN_MAKE_COUNT", int(raw.get("make_count") or DEFAULT_MAKE_COUNT)),
        make_interval=_env_int("DIANXIN_MAKE_INTERVAL", int(raw.get("make_interval") or DEFAULT_MAKE_INTERVAL)),
        max_draws=_env_int("DIANXIN_MAX_DRAWS", int(raw.get("max_draws") or DEFAULT_MAX_DRAWS)),
        proxy_api=_env("DIANXIN_PROXY_API") or str(raw.get("proxy_api") or ""),
        invite_code=_env("DIANXIN_INVITE_CODE") or str(raw.get("invite_code") or "") or DEFAULT_INVITE_CODE,
        note=_env("DIANXIN_NOTE") or str(raw.get("note") or ""),
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=(env_n["bark_server"] if (env_n["bark_url"] or env_n["bark_key"]) else str(n.get("bark_server") or DEFAULT_BARK)).rstrip("/"),
        bark_group=env_n["bark_group"] or str(n.get("bark_group") or "") or DEFAULT_BARK_GROUP,
        bark_sound=env_n["bark_sound"] or str(n.get("bark_sound") or ""),
        state_dir=_env("DIANXIN_STATE_DIR") or str(raw.get("state_dir") or ""),
        source=str(path),
    )


def resolve_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        return load_config_yaml(Path(args.config))
    env_cfg = load_config_from_env()
    local = SCRIPT_DIR / "config.yaml"
    if env_cfg is not None:
        if local.is_file():
            log("📦 已用环境变量 DIANXIN，本地 config.yaml 不会被读取")
        return env_cfg
    if local.is_file():
        return load_config_yaml(local)
    raise FileNotFoundError(
        "未找到账号配置。青龙请设环境变量 DIANXIN=手机号#密码；"
        f"本地请 cp config.example.yaml config.yaml 后填写，或 python3 daily.py -c 路径"
    )


def resolve_state_dir(cfg: Optional[AppConfig] = None) -> Path:
    if cfg and cfg.state_dir:
        p = Path(cfg.state_dir).expanduser()
        return p if p.is_absolute() else (SCRIPT_DIR / p)
    env = _env("DIANXIN_STATE_DIR")
    if env:
        return Path(env).expanduser()
    ql_data = _env("QL_DATA_DIR")
    if ql_data:
        return Path(ql_data) / "dianxin"
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "dianxin"
    return SCRIPT_DIR / "state"


# ---------------------------------------------------------------------------
# Bark（与仓库其它项目共用 BARK_*）
# ---------------------------------------------------------------------------

_ACTIVE_CFG: Optional[AppConfig] = None


def bark_endpoint(cfg: Optional[AppConfig] = None) -> Optional[str]:
    cfg = cfg or _ACTIVE_CFG
    url = (cfg.bark_url if cfg else "") or _env("BARK_URL") or _env("BARK_PUSH")
    key = (cfg.bark_key if cfg else "") or _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    if url and not url.startswith("http"):
        key = key or url
        url = ""
    if url:
        return url.rstrip("/")
    if key:
        server = (cfg.bark_server if cfg else "") or _env("BARK_SERVER") or DEFAULT_BARK
        return f"{server.rstrip('/')}/{key}"
    return None


def send_bark(title: str, body: str, cfg: Optional[AppConfig] = None) -> None:
    cfg = cfg or _ACTIVE_CFG
    ep = bark_endpoint(cfg)
    if not ep:
        log("📣 未配置 BARK_URL/BARK_KEY，跳过推送")
        return
    group = (cfg.bark_group if cfg else "") or _env("BARK_GROUP") or DEFAULT_BARK_GROUP
    payload: dict[str, Any] = {
        "title": title[:200],
        "body": body[:3500],
        "group": group,
    }
    sound = (cfg.bark_sound if cfg else "") or _env("BARK_SOUND")
    if sound:
        payload["sound"] = sound
    try:
        r = requests.post(ep, json=payload, timeout=15)
        if r.status_code >= 400:
            get_url = f"{ep}/{quote(title[:100], safe='')}/{quote(body[:500], safe='')}"
            r = requests.get(get_url, params={"group": group}, timeout=15)
        ok = r.status_code < 400
        log(f"📣 Bark {'已推送' if ok else '失败'}（HTTP {r.status_code}）")
        if not ok:
            log(f"   响应: {(r.text or '')[:200]}")
    except Exception as e:
        log(f"📣 Bark 失败: {e}")


# ---------------------------------------------------------------------------
# 代理（可选，防 10007 同 IP 频控）
# ---------------------------------------------------------------------------

class ProxyManager:
    def __init__(self, api_url: str):
        self.api_url = (api_url or "").strip()
        self.enabled = bool(self.api_url)
        self.used: set[str] = set()

    def get_proxy(self) -> Optional[str]:
        if not self.enabled:
            return None
        for _ in range(3):
            try:
                res = requests.get(self.api_url, timeout=10)
                if res.status_code == 200:
                    for p in (line.strip() for line in res.text.splitlines() if line.strip()):
                        if ":" in p and p not in self.used:
                            self.used.add(p)
                            log(f"🌐 [代理] 获取到新 IP: {p}")
                            return p if "://" in p else f"http://{p}"
            except Exception as e:
                log(f"⚠️ [代理] 提取异常: {e}")
            time.sleep(1)
        log("⚠️ [代理] 暂时无法获取，回退直连")
        return None


# ---------------------------------------------------------------------------
# 爱音乐协议加密（AES-CBC，请求/响应两套 key/iv 派生）
# ---------------------------------------------------------------------------

def _md(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _bearer(token: str) -> str:
    token = str(token or "").strip()
    return token if not token or token.lower().startswith("bearer ") else "Bearer " + token


def encryption_context(timestamp: Optional[str] = None, random_value: Optional[str] = None) -> dict[str, str]:
    timestamp = str(timestamp if timestamp is not None else time.time_ns() // 1000000)
    random_value = random_value or "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    key = _md(_b64(_md(timestamp) + random_value) + random_value)
    return {"imencrypt": "1", "imtimestamp": timestamp, "imrandomnum": random_value, "imencryptkey": key}


def _cipher(headers: dict[str, str], response: bool = False) -> Any:
    t, r, k = (headers[x] for x in ("imtimestamp", "imrandomnum", "imencryptkey"))
    if response:
        key, iv = _md(_b64(t) + k + _md(r)), _md(_b64(r) + k + _md(t))
    else:
        key, iv = _md(_b64(r) + _md(t) + k), _md(_b64(t) + _md(r) + k)
    return AES.new(key[:16].encode("ascii"), AES.MODE_CBC, iv[:16].encode("ascii"))


def encrypt_payload(payload: Any, headers: dict[str, str]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.b64encode(_cipher(headers).encrypt(pad(raw, 16))).decode("ascii")


def decrypt_payload(payload: str, headers: dict[str, str], response: bool = True) -> Any:
    raw = base64.b64decode(payload, validate=True)
    return json.loads(unpad(_cipher(headers, response).decrypt(raw), 16).decode("utf-8"))


class ImusicError(RuntimeError):
    pass


class ImusicApiError(ImusicError):
    def __init__(self, code: Any, api: str = ""):
        value = str(code) if isinstance(code, (str, int)) and not isinstance(code, bool) else ""
        self.code = value if re.fullmatch(r"[0-9]{1,8}", value) else "unknown"
        self.api = api if isinstance(api, str) else "未知接口"
        if self.code == "0007":
            self.description = "爱音乐登录已失效，正在自动重建会话"
        elif self.code == "10003" and "Redeem" in self.api:
            self.description = "话费兑换库存不足"
        elif self.code == "10013":
            self.description = "服务端返回业务错误，可尝试自愈重试"
        else:
            self.description = "服务端未返回成功结果"
        super().__init__(f"接口异常：{self.api}；返回码 {self.code}；{self.description}")


# ---------------------------------------------------------------------------
# 电信统一认证（账密 → Ticket）
# ---------------------------------------------------------------------------

KEYS = {
    "login_rsa": "-----BEGIN PUBLIC KEY-----\nMIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBkLT15ThVgz6/NOl6s8GNPofdWzWbCkWnkaAm7O2LjkM1H7dMvzkiqdxU02jamGRHLX/ZNMCXHnPcW/sDhiFCBN18qFvy8g6VYb9QtroI09e176s+ZCtiv7hbin2cCTj99iUpnEloZm19lwHyo69u5UMiPMpq0/XKBO8lYhN/gwIDAQAB\n-----END PUBLIC KEY-----",
    "des3": b"1234567`90koiuyhgtfrdews",
}


def encrypt_des3(data: str, mode: str = "enc") -> str:
    cipher = DES3.new(KEYS["des3"], DES3.MODE_CBC, bytes([0] * 8))
    if mode == "enc":
        return cipher.encrypt(pad(data.encode(), 8)).hex()
    return unpad(cipher.decrypt(bytes.fromhex(data)), 8).decode()


def encrypt_rsa(data: str) -> str:
    cipher = PKCS1_v1_5.new(RSA.import_key(KEYS["login_rsa"]))
    return base64.b64encode(cipher.encrypt(data.encode())).decode()


def telecom_encode(s: Any) -> str:
    return "".join((chr(ord(c) + 2) for c in str(s)))


class CustomSSLAdapter(HTTPAdapter):
    def init_poolmanager(self, *args: Any, **kwargs: Any) -> None:
        ctx = create_urllib3_context(ciphers="DEFAULT@SECLEVEL=1:!aNULL:!eNULL:!MD5")
        ctx.check_hostname = False
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def get_telecom_session(proxy: Optional[str] = None) -> requests.Session:
    s = requests.Session()
    s.verify = certifi.where()
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    s.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Mobile Safari/537.36"})
    s.mount("https://", CustomSSLAdapter())
    return s


def telecom_login(acc: Account, cache_dict: Optional[dict] = None, proxy: Optional[str] = None) -> Optional[str]:
    """电信账密登录 → 换 Ticket。优先用缓存 token，失效再走账密。"""
    cached = (cache_dict or {}).get(acc.mobile, {})
    s = get_telecom_session(proxy)
    try:
        if cached.get("token") and cached.get("userId"):
            ticket = _telecom_get_ticket(s, acc.mobile, cached)
            if ticket:
                log("   🔑 电信缓存凭证有效，直接换到 Ticket")
                return ticket
            log("   ⚠️ 电信缓存凭证失效，重新账密登录")

        stamp = datetime.now(CST).strftime("%Y%m%d%H%M%S")
        use_android = bool(re.fullmatch(r"[0-9a-fA-F]{16}", acc.android_id)) if acc.android_id else False
        if use_android:
            # 携带真实 AndroidID：模拟小米设备，全新环境登录避开 3006 风控
            client_type = "#11.0.0#channel8#Xiaomi 20#"
            cipher_head = f"Xiaomi 20 8.0.0.{acc.android_id[:12]}"
            system_version = "8.0.0"
            device_uid = ""
            is_chinatelecom = ""
        else:
            device_id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            client_type = "#10.5.0#channel50#iPhone 14 Pro Max#"
            cipher_head = f"iPhone 14 15.4.{device_id[:12]}"
            system_version = "15.4.0"
            device_uid = device_id
            is_chinatelecom = "0"

        cipher_text = f"{cipher_head}{acc.mobile}{stamp}{acc.password}0$$$0."
        fields = {
            "loginType": "4",
            "accountType": "",
            "loginAuthCipherAsymmertric": encrypt_rsa(cipher_text),
            "deviceUid": device_uid,
            "phoneNum": telecom_encode(acc.mobile),
            "isChinatelecom": is_chinatelecom,
            "systemVersion": system_version,
            "authentication": telecom_encode(acc.password),
        }
        if use_android:
            fields["androidId"] = telecom_encode(acc.android_id)
            fields["loginAuthCipher"] = ""

        body = {
            "headerInfos": {
                "code": "userLoginNormal", "timestamp": stamp, "broadAccount": "",
                "broadToken": "", "clientType": client_type, "shopId": "20002",
                "source": "110003", "sourcePassword": "Sid98s", "token": "",
                "userLoginName": telecom_encode(acc.mobile),
            },
            "content": {"attach": "test", "fieldData": fields},
        }
        res = s.post("https://appgologin.189.cn:9031/login/client/userLoginNormal", json=body, timeout=15)
        res_data = res.json()
        succ = res_data.get("responseData", {}).get("data", {}).get("loginSuccessResult")
        if not succ or not succ.get("token"):
            log(f"   ❌ 电信账密验证失败: {res_data.get('responseData', {}).get('resultDesc') or res_data}")
            return None
        if cache_dict is not None:
            cache_dict[acc.mobile] = succ
        log(f"   ✅ 电信账密登录成功（{'Android 设备' if use_android else '随机 iPhone 指纹'}）")
        return _telecom_get_ticket(s, acc.mobile, succ)
    finally:
        s.close()


def _telecom_get_ticket(session: requests.Session, mobile: str, cached_info: dict) -> Optional[str]:
    stamp = datetime.now(CST).strftime("%Y%m%d%H%M%S")
    root = telecom_et.Element("Request")
    header = telecom_et.SubElement(root, "HeaderInfos")
    for k, v in {
        "Code": "getSingle", "Timestamp": stamp, "BroadAccount": "", "BroadToken": "",
        "ClientType": "#9.6.1#channel50#iPhone 14 Pro Max#", "ShopId": "20002",
        "Source": "110003", "SourcePassword": "Sid98s", "Token": cached_info["token"],
        "UserLoginName": mobile,
    }.items():
        telecom_et.SubElement(header, k).text = str(v)
    content = telecom_et.SubElement(root, "Content")
    telecom_et.SubElement(content, "Attach").text = "test"
    fields = telecom_et.SubElement(content, "FieldData")
    telecom_et.SubElement(fields, "TargetId").text = encrypt_des3(str(cached_info["userId"]))
    telecom_et.SubElement(fields, "Url").text = "4a6862274835b451"
    xml_data = telecom_et.tostring(root, encoding="utf-8")

    res = session.post(
        "https://appgologin.189.cn:9031/map/clientXML",
        data=xml_data,
        headers={"Content-Type": "application/xml; charset=UTF-8"},
        timeout=15,
    )
    tk_match = re.search(r"<Ticket>(.*?)</Ticket>", res.text)
    if not tk_match:
        return None
    try:
        return encrypt_des3(tk_match.group(1), "dec")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 爱音乐客户端
# ---------------------------------------------------------------------------

class ImusicClient:
    def __init__(self, mobile: str, invite_code: str, proxy: Optional[str] = None):
        self.mobile = mobile
        self.channel_id = DEFAULT_CHANNEL
        self.token = ""
        self.ticket: Optional[str] = None
        self.encryption_headers = encryption_context()
        self.activity_sid = ""
        self.invite_code = invite_code
        self.invite_entry_done = False
        self.identity_verified = False
        self.session = requests.Session()
        if proxy:
            self.session.proxies = {"http": proxy, "https": proxy}
        app_user_agent = (
            "CtClient;13.3.0;Android;14;V2203A;"
            + _b64(mobile[-6:]).rstrip("=")
            + "!#!"
            + _b64(mobile[:5]).rstrip("=")
        )
        self.session.headers.update({
            "User-Agent": app_user_agent,
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE_URL,
            "X-Requested-With": "com.ct.client",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": f"{BASE_URL}/h5v/fusion/ai-luck-winnew?cc={self.channel_id}&ca=w7x6",
        })
        self.session.cookies.set("cc", self.channel_id, domain="ai.imusic.cn", path="/")
        self.session.cookies.set("loginState", "true", domain="ai.imusic.cn", path="/")

    def close(self) -> None:
        self.session.close()

    # ---- 基础请求 ----

    def _params(self, params: Optional[dict]) -> dict:
        data = {"channelId": self.channel_id, "portal": "45", "mobile": self.mobile}
        data.update(params or {})
        return data

    def _post(self, path: str, payload: dict, encrypted: bool, encrypted_response: bool, plain_query: bool = False) -> Any:
        headers: dict[str, str] = {} if encrypted or plain_query else {"Content-Type": "application/json;charset=UTF-8"}
        if self.token:
            headers["Authorization"] = self.token
        kwargs: dict[str, Any] = {}
        if encrypted:
            headers.update(self.encryption_headers)
            kwargs["params"] = {"formData": encrypt_payload(payload, headers)}
        elif plain_query:
            kwargs["params"] = payload
        else:
            kwargs["json"] = payload
        try:
            response = self.session.post(BASE_URL + path, headers=headers, timeout=DEFAULT_TIMEOUT, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise ImusicError("爱音乐请求连接失败或超时") from None

        if response.status_code != 200:
            raise ImusicError(f"爱音乐请求失败，HTTP {response.status_code}")
        # 网关会在响应头里轮换新 token
        auth_header = response.headers.get("authorization") or response.headers.get("Authorization")
        if auth_header and auth_header.strip():
            new_bearer = _bearer(auth_header)
            if len(new_bearer) > 10:
                self.token = new_bearer
        try:
            data = response.json()
        except ValueError:
            data = response.text.strip()
        if isinstance(data, str) and encrypted_response:
            try:
                data = decrypt_payload(data, headers)
            except Exception:
                raise ImusicError("爱音乐响应解密失败")
        if not isinstance(data, dict):
            raise ImusicError("爱音乐响应格式异常")
        if str(data.get("code", data.get("returnCode", ""))) == "0007":
            self.identity_verified = False
            raise ImusicApiError("0007", payload.get("apiName", path))
        return data

    def api(self, api_name: str, params: Optional[dict] = None, encrypted_response: bool = True) -> Any:
        payload = self._params(params)
        payload["apiName"] = api_name
        return self._post(
            "/hapi/en/api" if encrypted_response else "/hapi/de/api",
            payload,
            encrypted_response,
            encrypted_response,
            plain_query=not encrypted_response,
        )

    def direct(self, path: str, params: Optional[dict] = None, encrypted: bool = True, encrypted_response: Optional[bool] = None) -> Any:
        if encrypted_response is None:
            encrypted_response = encrypted
        return self._post(path, self._params(params), encrypted, encrypted_response, plain_query=not encrypted)

    # ---- 登录与会话 ----

    def refresh_login(self, ticket: Optional[str] = None) -> dict:
        if ticket:
            self.ticket = ticket
        use_ticket = ticket or self.ticket
        payload = {"portal": "45", "channelId": self.channel_id}
        payload.update({"ticket": use_ticket} if use_ticket else {"user118100cn": "user118100cn"})
        self.identity_verified = False
        data = self._post("/vapi/vue_login/sso_login_v2", payload, False, False)
        if str(data.get("returnCode")) != "0000" or not data.get("token"):
            raise ImusicError("爱音乐登录刷新失败，请更新该账号的凭证")
        if str(data.get("mobile", "")) != self.mobile:
            self.token = ""
            self.session.cookies.clear()
            raise ImusicError("爱音乐会话手机号与当前账号不一致")
        self.token = _bearer(data["token"])
        self.identity_verified = True
        return data

    def open_activity_page(self) -> None:
        if not self.identity_verified:
            raise ImusicError("账号身份未经核对")
        if self.activity_sid:
            return
        self.session.cookies.set("cc", self.channel_id, domain="ai.imusic.cn", path="/")
        self.session.cookies.set("loginState", "true", domain="ai.imusic.cn", path="/")
        try:
            self.session.get(DEFAULT_ACTIVITY_URL, timeout=20, allow_redirects=True)
            self.activity_sid = next(
                (c.value for c in self.session.cookies if c.name == "imusic" and c.domain.lstrip(".") == "ai.imusic.cn"),
                "",
            )
        except Exception:
            self.activity_sid = ""
        if not self.activity_sid:
            self.activity_sid = f"118100{int(time.time() * 1000)}"
            self.session.cookies.set("imusic", self.activity_sid, domain="ai.imusic.cn", path="/")

    def activity_event(self, name: str, value: str) -> Any:
        if not self.identity_verified or not self.activity_sid:
            self.activity_sid = f"118100{int(time.time() * 1000)}"
        return self._post("/vapi/vue_stat/sendMessage", self._params({
            "invitationCode": self.invite_code or DEFAULT_INVITE_CODE,
            "actname": name,
            "actparam": value + "_ca_w7x6",
            "sid": self.activity_sid,
        }), True, True)

    def decrypt_invite_code(self, code: str) -> Any:
        code = str(code or "").strip()
        if not code:
            return {}
        payload = {
            "activityId": ACTIVITY,
            "mobile": code,
            "type": 2,
            "invitationCode": code,
            "apiName": "diy/DiyVideoApi/getEncryptDecryptMobile",
            "channelId": self.channel_id,
            "portal": "45",
        }
        return self._post("/hapi/en/api", payload, True, True)

    def mark_invite_entry(self) -> bool:
        """官方通道入场校验与会话绑定（跟随原脚本内置邀请码链路）。"""
        if not self.invite_code or self.invite_entry_done:
            return True
        self.invite_entry_done = True
        try:
            info = self.decrypt_invite_code(self.invite_code)
            if str(info.get("code")) == "0000" and info.get("data"):
                inviter = str(info.get("data")).split("|")[0]
                if inviter:
                    self.activity_event(
                        "activity_vring_sharinglink_h5_20260128",
                        f"activityID_{ACTIVITY}_templateID_null_vidioID_null_分享人手机号_{inviter}"
                        f"_接收人手机号_{self.mobile}_templateconfID_null_entrance_{self.channel_id}",
                    )
                    log("   ✅ 官方通道入场校验与会话绑定完成")
                    return True
        except Exception:
            pass
        return False


# ---------------------------------------------------------------------------
# 活动业务
# ---------------------------------------------------------------------------

_MAKE_GATE = {"last": 0.0}


def pace_make_submission(interval: float) -> None:
    if interval > 0:
        wait = _MAKE_GATE["last"] + interval - time.time()
        if wait > 0:
            time.sleep(wait)
    _MAKE_GATE["last"] = time.time()


def _num(value: Any) -> int:
    return int(str(value))


def date_conv(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ImusicError("日期格式未知")
    try:
        r = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ImusicError("日期格式解析异常")
    return r.replace(tzinfo=CST) if r.tzinfo is None else r.astimezone(CST)


def checked(response: Any, api: str = "") -> Any:
    if not isinstance(response, dict) or str(response.get("code")) != "0000":
        raise ImusicApiError(response.get("code") if isinstance(response, dict) else None, api)
    return response.get("data")


def creation_points(records: list, issue: dict) -> int:
    start, end = date_conv(issue["startTime"]), date_conv(issue["endTime"])
    total = 0
    for item in records:
        when = date_conv(item.get("createDate"))
        if not start <= when <= end:
            continue
        amount = _num(item.get("score"))
        if amount <= 0 or str(item.get("scoreType")) in {"-1", "-2"}:
            continue
        desc = str(item.get("scoreDesc", ""))
        if "制作" in desc or "创作" in desc:
            total += amount
    return total


@dataclass
class RunOptions:
    mode: str = "auto"
    execute: bool = True  # observe 模式为 False，全程只读
    make_count: int = DEFAULT_MAKE_COUNT
    make_interval: int = DEFAULT_MAKE_INTERVAL
    max_draws: int = DEFAULT_MAX_DRAWS


class Activity:
    def __init__(self, client: ImusicClient, options: RunOptions, state_path: Path):
        self.client = client
        self.options = options
        self.state_path = Path(state_path)
        self.state = json.loads(self.state_path.read_text(encoding="utf-8")) if self.state_path.exists() else {}
        self.state.setdefault("claims", [])
        self._final_issue = False

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def api(self, name: str, **params: Any) -> Any:
        api = "act/LaborApi/" + name
        return checked(self.client.api(api, {"activityId": ACTIVITY, **params}), api)

    def records(self, name: str) -> list:
        rows: list = []
        for page in range(1, 10):
            data = self.api(name, pageNo=page, pageSize=10)
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                break
            batch = data["list"]
            rows.extend(batch)
            if len(batch) < 10:
                break
        return rows

    def score(self) -> tuple[int, int]:
        data = self.api("getOperationTotalScoreOrRemainingScore")
        return _num(data["totalScore"]), _num(data["remainingScore"])

    def quota(self) -> Any:
        return checked(self.client.api("ismp/IsmpApi/queryAiMakePkgInfo", {"aid": ACTIVITY}), "ismp/IsmpApi/queryAiMakePkgInfo")

    def mutate(self, kind: str, call: Any) -> Any:
        if not self.options.execute:
            raise ImusicError("observe 模式只读，不能更改数据")
        res = call()
        return checked(res, kind)

    def notify_tickets(self) -> None:
        try:
            rows = self.records("getOperationMyTickets")
            log(f"   🎫 查询到券码 {len(rows)} 个")
            for row in rows:
                if str(row.get("useStatus")) == "1":
                    log(f"   🎉 发现中奖券码: {row.get('prizeName', '活动奖品')}！请在活动中核对收货信息")
        except Exception:
            pass

    def claim_phone_bills(self) -> int:
        """自动领取中奖的 1 元话费（state 里记 awardId 防重复提交）。"""
        claimed = 0
        try:
            rows = self.records("getOperationPrizeRecordList")
            for row in rows:
                if str(row.get("awardIndex")) in PHONE_AWARDS and str(row.get("status")) == "0":
                    award_id = row.get("awardId")
                    if award_id and str(award_id) not in self.state["claims"]:
                        if self.options.execute:
                            self.mutate(
                                "act/LaborApi/extractPhoneBill",
                                lambda: self.client.api("act/LaborApi/extractPhoneBill", {"activityId": ACTIVITY, "awardId": award_id}),
                            )
                            self.state["claims"].append(str(award_id))
                            self.save()
                            log("   🎁 成功提交 1 元中奖话费领取！")
                            claimed += 1
        except Exception as e:
            log(f"   ⚠️ 领取话费记录查询异常: {e}")
        return claimed

    def template(self) -> dict:
        """读取活动推荐模板，优选纯文本免传图的视频模板。"""
        data = checked(
            self.client.api(
                "diy/DiyVideoApi/queryActRecommendTemplateList",
                {"activityId": "ai119_4", "pageNo": 1, "pageSize": 50},
                encrypted_response=False,
            ),
            "diy/DiyVideoApi/queryActRecommendTemplateList",
        )
        rows = data.get("list", [])
        ready = [
            r for r in rows
            if r.get("mediaType") == "video" and _num(r.get("imageCount", -1)) == 0 and r.get("userWords") and r.get("templateId")
        ]
        if not ready:
            raise ImusicError("未找到免素材的可制作视频模板")
        chosen = ready[0]
        log(f"   🎬 选用视频模板：{chosen.get('videoName')} ({chosen.get('templateConfId')})")
        return chosen

    def make_payload(self, template: dict) -> dict:
        name = str(template["videoName"]) + datetime.now(CST).strftime("%H%M%S") + secrets.token_hex(2)
        payload = {key: "" for key in (
            "openId", "makeId", "background", "userPhotos", "inviterMobile", "arrangeId",
            "aiGatewayImagMakeId", "fromType", "sessionId", "voice", "videoOwnerCode",
            "videoResourceCode", "workId", "imageMakeType", "songId", "imageRate", "productionType",
        )}
        payload.update(
            aid=ACTIVITY,
            templateId=template["templateId"],
            templateConfId=template["templateConfId"],
            userWords=template["userWords"],
            templateName=name,
            videoName=name,
            aiPack=0,
            autoOrderUgc=0,
        )
        return payload

    def prepare_make(self, template: dict) -> None:
        """制作前严格执行官方链路：页面入口状态同步、额度锁与模板详情查询。"""
        self.client.open_activity_page()
        self.client.mark_invite_entry()
        channel = self.client.channel_id
        try:
            self.client.activity_event("page_vring_index", f"玩转AI赢手机_activityID_{ACTIVITY}_entrance_{channel}")
            checked(
                self.client.api("ismp/IsmpApi/queryAiMakePkgInfo", {"templateId": template["templateId"], "aid": ACTIVITY}),
                "ismp/IsmpApi/queryAiMakePkgInfo",
            )
            checked(
                self.client.direct(
                    "/hapi/diy_video/imu/query_template_info",
                    {"templateConfId": template["templateConfId"], "templateId": template["templateId"]},
                    encrypted=False,
                ),
                "/hapi/diy_video/imu/query_template_info",
            )
            param = f"activityID_{ACTIVITY}_templateID_{template['templateId']}_entrance_{channel}_templateconfID_{template['templateConfId']}"
            self.client.activity_event("activity_vring_make_1.9", "_" + param)
            self.client.activity_event("activity_2511AI-makeonekey_1.6", param)
        except Exception:
            pass

    def make(self, issue: dict) -> int:
        if self.options.make_count == 0 or not self.options.execute:
            return 0
        points = creation_points(self.records("getOperationRecordList"), issue)
        left = max(0, (340 - points) // 20)
        quota = self.quota()
        count = min(self.options.make_count, left, max(0, _num(quota.get("privilegeVrbtAIVideoLeftNum", 0))))
        log(f"   📊 本期已获制作积分 {points}/340；本轮计划制作 {count} 次")
        if not count:
            return 0

        template = self.template()
        completed = 0
        for idx in range(count):
            completed_this = False
            for auth_retry in range(2):
                self.prepare_make(template)
                payload = self.make_payload(template)
                pace_make_submission(self.options.make_interval)
                try:
                    res = self.client.direct("/hapi/diy_video/au/template_make_add_v2", payload)
                    data = checked(res, "/hapi/diy_video/au/template_make_add_v2")
                    make_id = data.get("makeId") if isinstance(data, dict) else (data if isinstance(data, (str, int)) else None)
                    completed += 1
                    completed_this = True
                    log(f"   ✅ 第 {idx + 1}/{count} 次视频制作提交成功 (makeId: {make_id})")
                    time.sleep(3)
                    break
                except ImusicApiError as e:
                    if e.code == "10007":
                        log("   ⚠️ 遇到 10007 同 IP 高频频控，停止后续制作")
                        return completed
                    elif e.code == "0007":
                        if auth_retry == 0:
                            log("   ⚠️ 制作提交返回 0007（登录态未通过），正在重建会话重试…")
                            self.client.refresh_login()
                            self.client.activity_sid = ""
                            time.sleep(1)
                            continue
                        else:
                            log("   ⚠️ 重建会话后仍返回 0007，跳过当前制作")
                            break
                    elif e.code == "10013":
                        log("   ⚠️ 遇到 10013 错误，尝试自愈刷新凭据后重试…")
                        self.client.refresh_login()
                        time.sleep(1)
                        continue
                    else:
                        log(f"   ⚠️ 制作接口返回: {e}")
                        break
            if not completed_this:
                break
        return completed

    def draw_points(self, reserve: int = 0) -> int:
        total, remaining = self.score()
        available = max(0, (remaining - reserve) // 20)
        limit = min(self.options.max_draws, available)
        if limit <= 0 or not self.options.execute:
            return 0
        log(f"   🎰 准备积分抽奖，预计最多 {limit} 次…")
        draw_count = 0
        for i in range(limit):
            try:
                res = self.client.api("act/LaborApi/operationIntegralLottery", {"activityId": ACTIVITY})
                data = checked(res, "act/LaborApi/operationIntegralLottery")
                name = str(data.get("awardName", "无中奖"))
                log(f"   🎁 抽奖第 {i + 1} 次结果：{name}")
                draw_count += 1
                time.sleep(2)
            except Exception as e:
                log(f"   ⚠️ 抽奖中断: {e}")
                break
        return draw_count

    def spend(self) -> int:
        """积分消费：auto/save 满 1000 兑换 10 元话费；auto 兑换后多余的抽奖；draw 全抽。"""
        total, remaining = self.score()
        if remaining >= 1000 and self.options.mode in ("auto", "save") and self.options.execute:
            log("   💸 当前积分满 1000 点，正在申请兑换 10 元话费…")
            try:
                res = self.client.api("act/LaborApi/operationIntegralRedeemPrize", {"activityId": ACTIVITY})
                checked(res, "act/LaborApi/operationIntegralRedeemPrize")
                log("   🎉 10 元话费兑换申请成功！")
            except ImusicApiError as e:
                if e.code == "10003":
                    log("   ℹ️ 10 元话费当前库存不足，次月自动再试")
                else:
                    log(f"   ⚠️ 话费兑换返回: {e}")

        draws = 0
        if self.options.mode == "draw":
            draws = self.draw_points(0)
        elif self.options.mode == "auto":
            if self._final_issue and remaining < 1000:
                draws = self.draw_points(0)  # 最后一期攒不满，抽光防清零
            elif remaining > 1000:
                draws = self.draw_points(1000)  # 兑换后多余的抽掉
        return draws

    def run(self) -> dict[str, Any]:
        if not self.client.identity_verified:
            self.client.refresh_login()
        self.client.open_activity_page()
        self.client.mark_invite_entry()
        issue = self.api("getOperationCurrentIssueInfo")
        self._final_issue = any(
            date_conv(issue.get(k)) >= FINAL_DRAW_DATE for k in ("drawTime", "endTime") if issue.get(k)
        )
        b_total, b_rem = self.score()
        log(f"   📌 当前活动期：{issue.get('issueName')} | 累计获点 {b_total} | 当前可用积分 {b_rem}")

        self.notify_tickets()
        claimed = self.claim_phone_bills()
        makes = self.make(issue)
        draws = self.spend()
        claimed += self.claim_phone_bills()

        a_total, a_rem = self.score()
        log(f"   🏁 本号完成：积分 {b_rem} → {a_rem}（累计获点 {a_total}）")
        return {
            "label": mask_mobile(self.client.mobile),
            "ok": True,
            "issue": issue.get("issueName"),
            "makes": makes,
            "score_change": f"{b_rem}→{a_rem}",
            "score_total": a_total,
            "draws": draws,
            "bill_claimed": claimed,
            "remark": "已完成全部任务" if self.options.execute else "observe 只查询",
        }


# ---------------------------------------------------------------------------
# 汇总通知
# ---------------------------------------------------------------------------

def build_bark(results: list[dict[str, Any]], note: str) -> tuple[str, str]:
    now = datetime.now(CST).strftime("%m-%d %H:%M")
    n = len(results)
    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = n - ok_n
    note_s = f" · {note}" if note else ""

    if n == 0:
        title = f"电信AI奇遇{note_s}"
    elif fail_n == 0:
        title = f"电信AI奇遇 ✅{note_s}"
    elif ok_n == 0:
        title = f"电信AI奇遇 ❌{note_s}"
    else:
        title = f"电信AI奇遇 ⚠️ {ok_n}/{n}{note_s}"

    lines = ["📶 电信 AI 奇遇 · 任务汇总"]
    if note:
        lines.append(f"🏷️ 备注：{note}")
    lines.append(f"📅 {now}")
    lines.append("────────────────")
    lines.append("")

    for i, r in enumerate(results):
        icon = ICONS[i % len(ICONS)]
        lines.append(f"{icon} 【{r.get('label') or '?'}】")
        if not r.get("ok"):
            err = str(r.get("error") or "失败")
            if len(err) > 90:
                err = err[:87] + "…"
            lines.append("   ❌ 状态：失败")
            lines.append(f"   💬 {err}")
        else:
            if r.get("issue"):
                lines.append(f"   📌 期数：{r['issue']}")
            lines.append(f"   💰 积分：{r.get('score_change', '-')}（累计 {r.get('score_total', '?')}）")
            lines.append(f"   🎬 制作：{r.get('makes', 0)} 次")
            if r.get("draws"):
                lines.append(f"   🎰 抽奖：{r['draws']} 次")
            if r.get("bill_claimed"):
                lines.append(f"   🎁 话费：领取 {r['bill_claimed']} 笔")
            if r.get("remark") and r["remark"] != "已完成全部任务":
                lines.append(f"   💬 {r['remark']}")
        if i < n - 1:
            lines.append("")

    lines.append("")
    lines.append("────────────────")
    lines.append(f"📦 账号 {n} · ✅{ok_n}  ❌{fail_n}")
    if fail_n == 0:
        lines.append("🎉 全部顺利")
    elif ok_n == 0:
        lines.append("😿 请检查账号密码 / 网络 / 风控（建议补 AndroidID）")
    else:
        lines.append("💡 部分账号见日志")
    return title, "\n".join(lines)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run_account(acc: Account, cfg: AppConfig, options: RunOptions,
                proxy: Optional[str], telecom_cache: dict, state_dir: Path) -> dict[str, Any]:
    log("")
    log("=" * 40)
    log(f"👤 {acc.label}  ({mask_mobile(acc.mobile)})"
        f"{'  | AndroidID ' + acc.android_id[:6] + '…' if acc.android_id else ''}")

    client: Optional[ImusicClient] = None
    try:
        log("   🔑 电信统一认证换取 Ticket…")
        ticket = telecom_login(acc, telecom_cache, proxy)
        if not ticket:
            raise ImusicError("获取电信登录 Ticket 失败，跳过该账号")

        client = ImusicClient(acc.mobile, cfg.invite_code, proxy=proxy)
        client.refresh_login(ticket=ticket)
        log("   ✅ 爱音乐会话校验通过")

        activity = Activity(client, options, state_dir / f"{acc.mobile}.json")
        return activity.run()
    finally:
        if client:
            client.close()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="电信 AI 奇遇：自动任务 / 领奖 / 兑换（本地 yaml 或青龙环境变量）")
    p.add_argument("-c", "--config", default="", help="本地 config.yaml 路径（默认 ./config.yaml）")
    p.add_argument("--observe", action="store_true", help="只查询不动手（等同 DIANXIN_MODE=observe）")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    global _ACTIVE_CFG
    args = parse_args(argv)
    log("🚀 电信 AI 奇遇 daily.py")
    log(f"🖥️ 运行环境: {'青龙' if running_on_qinglong() else '本地'}")

    try:
        cfg = resolve_config(args)
    except Exception as e:
        log(f"❌ {e}")
        log("   青龙：DIANXIN=手机号#密码[#AndroidID][#备注]")
        log("   本地：cp config.example.yaml config.yaml 后填写")
        send_bark("电信AI奇遇 ❌", f"❌ 未配置账号\n{e}")
        return 1

    if args.observe:
        cfg.mode = "observe"
    _ACTIVE_CFG = cfg

    options = RunOptions(
        mode=cfg.mode,
        execute=cfg.mode != "observe",
        make_count=cfg.make_count,
        make_interval=cfg.make_interval,
        max_draws=cfg.max_draws,
    )

    log(f"📄 配置来源: {cfg.source or '?'}")
    log(f"🎛️ 模式: {cfg.mode} | 制作上限 {cfg.make_count} | 间隔 {cfg.make_interval}s | 抽奖上限 {cfg.max_draws}")
    if cfg.note:
        log(f"🏷️ 全局备注: {cfg.note}")
    if bark_endpoint(cfg):
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY（本地可写在 config.yaml 的 notify）")

    state_dir = resolve_state_dir(cfg)
    state_dir.mkdir(parents=True, exist_ok=True)
    log(f"💾 状态目录: {state_dir}")
    telecom_cache_file = state_dir / "telecom_cache.json"
    telecom_cache: dict = {}
    if telecom_cache_file.exists():
        try:
            telecom_cache = json.loads(telecom_cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    proxy_mgr = ProxyManager(cfg.proxy_api)
    if proxy_mgr.enabled:
        log("🌐 已配置代理 API，一号一 IP")

    log(f"📋 共 {len(cfg.accounts)} 个账号")
    results: list[dict[str, Any]] = []
    for i, acc in enumerate(cfg.accounts, 1):
        log(f"\n▶ [{i}/{len(cfg.accounts)}]")
        proxy = proxy_mgr.get_proxy()
        try:
            results.append(run_account(acc, cfg, options, proxy, telecom_cache, state_dir))
        except Exception as e:
            log(f"   ❌ 异常: {e}")
            results.append({"label": acc.label, "ok": False, "error": str(e)})
        if i < len(cfg.accounts):
            time.sleep(2.0)

    try:
        telecom_cache_file.write_text(json.dumps(telecom_cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"⚠️ 电信凭证缓存写入失败: {e}")

    title, body = build_bark(results, cfg.note)
    log("")
    log(body)
    send_bark(title, body, cfg)
    log("\n🏁 全部完成")
    fail = sum(1 for r in results if not r.get("ok"))
    return 1 if fail else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n⚠️ 中断")
        sys.exit(130)
