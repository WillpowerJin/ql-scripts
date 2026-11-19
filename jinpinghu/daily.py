#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
今平湖（平湖新闻）阅读红包助手 — 帐密登录 / 自动阅读 / 自动抽奖

cron: 5 9 * * *
new Env('今平湖阅读红包');

流程（三套签名全部本地复现，零抓包依赖）：
  passport /web/init → /web/oauth/credential_auth（RSA 加密密码）→ authorization_code
  vapp /api/account/init → /api/zbtxz/login → session.id / account.id
  ya   /api/aosbase/_auth_appuserinit（MD5 签名）→ access_token（约 115 天，本地缓存）
  每篇新闻直接上报约 3 分钟阅读时长 → task_done → 抽奖（ac_sub 提交手机号）

  写操作必须带 Access-Api-Signature =
  appid;guid32;毫秒ts;md5(appid+guid+ts+getAASkey(appkey))，缺失返回 1000。

上车前置（手动完成一次）：
  1. App 验证码登录 → 点头像 → 账户信息 → 重置密码，把 手机号/密码 填进配置
  2. 首次提现前在 App 里绑定微信：
     首页 → 右下悬浮框 → 阅读任务 → 「首次提现请绑定微信」
     未绑定时 ac_sub 会被拒但仍扣抽奖次数，脚本会先检测，未绑定直接跳过

抽奖链路与 1007：
  _ac_detail 活动详情（验证配置 + 手机号表单）→ 过滑块拿 afs_tokenid
  → lotteryTake 埋点 → ac_sub（手机号随 collect_info 一次性提交，字段名动态读取）
  1007 只是通用码，msg 才是原因：
    none times       = 抽奖次数已耗尽
    "o a d w"/"o d d w" = 未中奖暗号（前端 checkPrizeIsEmpty 明确判为未中奖），
                        次数照扣、不生成中奖记录，属概率结果而非请求错误
  当天任务集实测有效期 09:00 ~ 23:59，即每天 09:00 换新任务。
  红包按整点限量发放，越晚抽越容易只剩积分，定时建议 09:00 后几分钟（如 5 9 * * *）。

多账号隔离：
  抽奖手机号在实例创建时按账号冻结，默认恒为本账号登录号；
  全局 JPH_LOTTERY_PHONE 仅单账号生效，多账号要单独指定用 JPH_LOTTERY_PHONE_MAP。
  ac_sub 前 assert_isolated() 硬校验手机号 / 登录态 / device_token / 滑块凭证
  都属于本账号，任一项不过立即中止（连埋点都不发）。

青龙环境变量：
  JPH / JPH_ACCOUNTS     必填  手机号#密码（多账号 & 或换行）
                              JPH_ACCOUNTS 也兼容旧格式 手机号@密码&...
                              JPH_ACCOUNTS 写 JSON 数组可带备注名
  JPH_THREADS           并发线程数，默认 3；0=全并发；1=串行
  JPH_DO_LOTTERY        1=任务后自动抽奖并提交手机号（默认）；0=只刷次数、绝不发 ac_sub
  JPH_FORCE_LOTTERY     1=忽略微信绑定检测强制抽奖（会白扣次数，慎用）
  JPH_LOTTERY_PHONE     抽奖弹窗手机号，默认=登录号；仅单账号生效
  JPH_LOTTERY_PHONE_MAP 按账号指定：登录号=抽奖号,登录号=抽奖号（多账号仅此方式）
  JPH_OCR               cv2（默认）/ ddddocr / remote（外部 ddddocr 服务）
  JPH_OCR_URL           外部 OCR 服务地址，默认 http://127.0.0.1:7777
  JPH_SLIDE_RETRY       滑块最大尝试轮数，默认 6
  JPH_READ_MS           强制阅读时长(毫秒)；默认 0=每篇直接上报约 3 分钟
  JPH_USE_AUDIO_DURATION 1=按该篇 audio_duration 计算（4/5/3 分钟）
  JPH_REAL_WAIT         真实等待秒数上限，默认 0（实测直接上报即可）
  JPH_AC_DETAIL         0=跳过活动详情请求，默认 1
  JPH_ACTIVITY_ID       强制当天任务集 id，默认按有效期自动发现
  JPH_MAIN_ACTIVITY_ID  强制主活动 id，默认从浮标入口自动发现
  JPH_CLIENT_ID         passport client_id，默认 10040
  JPH_TIMEOUT           请求超时秒，默认 25
  JPH_STATE_DIR         登录态缓存目录；青龙默认 /ql/data/jinpinghu
  JPH_DEBUG             1=打印详细响应
  DRY_RUN=1             等同 --dry-run：只读核验

通知（与 huazhu / jd 等共用）：
  青龙统一通知 → Bark → PushPlus
  BARK_URL 或 BARK_KEY [+ BARK_SERVER]；BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
  PUSHPLUS_TOKEN [+ PUSHPLUS_TOPIC]

依赖：requests cryptography
      默认 cv2 滑块方案另需 opencv-python-headless numpy
      也可 JPH_OCR=ddddocr（需 ddddocr）或 JPH_OCR=remote（外部服务，客户端无需 cv2）
      本地 yaml 配置另需 PyYAML
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import random
import re
import string
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

try:
    import requests
    from cryptography.hazmat.primitives import padding as sym_padding
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding as rsa_padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:
    print("❌ 缺少依赖：pip install requests cryptography")
    print("   青龙：【依赖管理】->【Python3】安装 requests cryptography")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 常量（来自 App / H5 抓包）
# ---------------------------------------------------------------------------

PASSPORT_BASE = "https://passport.tmuyun.com"
VAPP_BASE = "https://vapp.tmuyun.com"
YA_BASE = "https://ya.iyunxh.com"
STATIC2_BASE = "https://static2-ya.iyunxh.com"
H5_ORIGIN = "https://pinghu.y-h5.iyunxh.com"

DEFAULT_CLIENT_ID = "10040"
DEFAULT_OCR_URL = "http://127.0.0.1:7777"
DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "今平湖"
DEFAULT_TIMEOUT = 25
DEFAULT_THREADS = 3
DEFAULT_SLIDE_RETRY = 8
TOKEN_TTL = 100 * 86400  # access_token 实际约 115 天，100 天后主动刷新

RSA_PUB = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD6XO7e9YeAOs+cFqwa7ETJ+WXizPqQeXv68i5vqw"
    "9pFREsrqiBTRcg7wB0RIp3rJkDpaeVJLsZqYm5TW7FWx/iOiXFc+zCPvaKZric2dXCw27EvlH5rq+"
    "zwIPDAJHGAfnn1nmQH7wR3PCatEIb8pz5GFlTHMlluw4ZYmnOwg+thwIDAQAB"
)
UA_APP = "3.9.0;03C86867-6800-41B0-B151-AB1647128355859832320;iPhone17,3;IOS;27.3;Appstore;7.14.0"
# H5 页面内业务请求(ya.iyunxh.com)真机抓包 UA；ac_sub 涉及现金，风控比 task_done 严
UA_H5 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 27_3 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148;;"
    "xsb;xsb_jinpinghu;3.9.0;Appstore;native_app;7.14.0"
)

VAPP_SALT = "FR*r!isE5W"
TENANT_ID = "83"
APPID = "pinghu"
APPKEY = "ebac56c342f9b2b87efd0e2ef3f8c63e"
T_ID = "2442"
DEVICE_DT = "111101edcc98ce5cb57d1dea69f5d39a4e52"

AES_KEY = b"7Pf0cfZPHy1L7PS2PfCfP8r2BGi461LG"
AES_IV = b"8RsVKSCH8mQ4l7cu"

# 主活动按轮次变（如 11月第2轮），当天任务集每天变（如 11月18日 新闻任务）。
# 运行时由 buoy/list + _optionp_list 动态发现；下面三个只是接口失败时的兜底值。
MAIN_ACTIVITY_ID = "11106708"
DEFAULT_OPTIONP_ID = "33582"
DEFAULT_MODULE_ID = "41603"
REFERER = (
    H5_ORIGIN + "/module-study/pass-detail/pass-detail"
    "?pass_id=%s&activity_id=%s" % (DEFAULT_OPTIONP_ID, MAIN_ACTIVITY_ID)
)
LOTTERY_ID = "309810304931afb36b7308"
PHONE_FIELD = "phone_16115192egq"

ICONS = "📱📰🎬🎰💰🎁✨🌟"
IS_DEBUG = False

_STATE_LOCK = threading.RLock()   # 可重入：cache_token 外层持锁，load/save 内层也要加锁
_DEVICE_LOCK = threading.Lock()   # 保护下面两个全局去重集合
_ISSUED_DEVICE_TOKENS: set[str] = set()   # 本进程已发放的 device_token（跨账号不得重复）
_USED_SLIDE_TOKENS: set[str] = set()      # 已用于 ac_sub 的滑块凭证（跨账号不得复用）

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
# 打印 / 工具
# ---------------------------------------------------------------------------

def log(msg: str = "") -> None:
    print(msg, flush=True)


def _env(key: str, default: str = "") -> str:
    val = os.getenv(key)
    return val.strip() if val is not None and val.strip() != "" else default


def _flag(value: Any, default: bool = False) -> bool:
    """宽松布尔解析：1/true/yes 为真，0/false/no/off 为假。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in ("0", "false", "no", "off")


def _env_flag(key: str, default: bool = False) -> bool:
    return _flag(os.getenv(key), default)


def mask_mobile(mobile: str) -> str:
    mobile = (mobile or "").strip()
    if len(mobile) >= 7:
        return mobile[:3] + "****" + mobile[-4:]
    return mobile or "?"


def running_on_qinglong() -> bool:
    return bool(_env("QL_DATA_DIR")) or Path("/ql/data").is_dir()


def fmt_ts(value: Any) -> str:
    """服务端时间戳（秒）转本地时间，用于展示任务集有效期。"""
    try:
        return datetime.fromtimestamp(int(value)).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "?"


def randstr(n: int) -> str:
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def jbody(resp: requests.Response) -> dict:
    try:
        obj = resp.json()
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def ok(obj: Any) -> bool:
    """两套返回码：passport/vapp 用 code:0 (int)，iyunxh 用 code:'0' (str)。"""
    if not isinstance(obj, dict):
        return False
    code = obj.get("code")
    return code == 0 or code == "0" or obj.get("success") is True


class JphError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 账号与配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    phone: str
    password: str
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or mask_mobile(self.phone)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    threads: int = DEFAULT_THREADS
    do_lottery: bool = True
    force_lottery: bool = False
    lottery_phone: str = ""
    lottery_phone_map: dict[str, str] = field(default_factory=dict)
    ocr: str = "cv2"
    ocr_url: str = DEFAULT_OCR_URL
    slide_retry: int = DEFAULT_SLIDE_RETRY
    read_ms: int = 0
    use_audio_duration: bool = False
    real_wait: int = 0
    ac_detail: bool = True
    activity_id: str = ""
    main_activity_id: str = ""
    client_id: str = DEFAULT_CLIENT_ID
    timeout: int = DEFAULT_TIMEOUT
    inter_account_delay: int = 2
    state_dir: str = ""
    bark: dict[str, str] = field(default_factory=dict)
    pushplus: dict[str, str] = field(default_factory=dict)
    source: str = ""


def _split_accounts(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[&\n]", (raw or "").replace("\r", "")) if p.strip()]


def parse_accounts_json(raw: str) -> list[Account]:
    try:
        items = json.loads(raw)
    except Exception as e:
        raise JphError(f"JPH_ACCOUNTS JSON 解析失败: {e}") from e
    if not isinstance(items, list):
        raise JphError("JPH_ACCOUNTS 应为 JSON 数组")
    out: list[Account] = []
    for i, item in enumerate(items):
        if isinstance(item, dict):
            phone = str(item.get("phone") or item.get("mobile") or "").strip()
            password = str(item.get("password") or item.get("pwd") or "")
            name = str(item.get("name") or item.get("note") or "").strip()
        else:
            piece = str(item)
            phone, password, name = _split_piece(piece, "#" if "#" in piece and "@" not in piece else "@")
        if not phone or not password:
            log(f"⚠️ 第 {i + 1} 个账号缺少 phone/password，已跳过")
            continue
        out.append(Account(phone=phone, password=password, name=name))
    return out


def _split_piece(part: str, sep: str) -> tuple[str, str, str]:
    part = part.strip()
    if sep in part:
        phone, pwd = part.split(sep, 1)
        return phone.strip(), pwd.strip(), ""
    return "", "", ""


def parse_accounts_text(raw: str, sep: str) -> list[Account]:
    """手机号#密码（或旧格式 手机号@密码），多账号 & 或换行，密码可含 @。"""
    out: list[Account] = []
    for i, part in enumerate(_split_accounts(raw)):
        phone, password, _ = _split_piece(part, sep)
        if not phone or not password:
            log(f"⚠️ 第 {i + 1} 段格式错误，应为 手机号{sep}密码")
            continue
        out.append(Account(phone=phone, password=password))
    return out


def _accounts_from_env() -> list[Account]:
    for key, sep in (("JPH", "#"), ("JPH_ACCOUNTS", "@")):
        raw = _env(key)
        if not raw:
            continue
        if raw.lstrip().startswith("["):
            return parse_accounts_json(raw)
        if key == "JPH_ACCOUNTS" and "#" in raw and "@" not in raw:
            sep = "#"
        return parse_accounts_text(raw, sep)
    return []


def _parse_phone_map(value: Any) -> dict[str, str]:
    """JPH_LOTTERY_PHONE_MAP：登录手机号=抽奖手机号，多组用 , 或 & 分隔。"""
    out: dict[str, str] = {}
    if isinstance(value, dict):
        items = [f"{k}={v}" for k, v in value.items()]
    else:
        items = re.split(r"[&,]", str(value or ""))
    for seg in items:
        if "=" not in str(seg):
            continue
        k, v = str(seg).split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return out


def load_notify_config(raw: dict[str, Any]) -> dict[str, dict[str, str]]:
    """config.yaml 的 bark:/pushplus: 段 + BARK_*/PUSHPLUS_* 环境变量（环境变量优先）。"""
    raw_bark = raw.get("bark") if isinstance(raw.get("bark"), dict) else {}
    if not raw_bark and isinstance(raw.get("notify"), dict):
        raw_bark = raw["notify"]
    bark_url = _env("BARK_URL") or _env("BARK_PUSH") or str(raw_bark.get("url") or "")
    bark_key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY") or str(raw_bark.get("key") or "")
    if bark_url and not bark_url.startswith("http"):
        bark_key, bark_url = bark_key or bark_url, ""

    raw_pp = raw.get("pushplus") if isinstance(raw.get("pushplus"), dict) else {}
    return {
        "bark": {
            "url": bark_url.strip(),
            "key": bark_key.strip(),
            "server": (_env("BARK_SERVER") or str(raw_bark.get("server") or "") or DEFAULT_BARK_SERVER).rstrip("/"),
            "group": _env("BARK_GROUP") or str(raw_bark.get("group") or "") or DEFAULT_BARK_GROUP,
            "sound": _env("BARK_SOUND") or str(raw_bark.get("sound") or ""),
            "icon": _env("BARK_ICON") or str(raw_bark.get("icon") or ""),
            "level": _env("BARK_LEVEL") or str(raw_bark.get("level") or ""),
        },
        "pushplus": {
            "token": (_env("PUSHPLUS_TOKEN") or str(raw_pp.get("token") or "")).strip(),
            "topic": (_env("PUSHPLUS_TOPIC") or str(raw_pp.get("topic") or "")).strip(),
        },
    }


def _merge_str(env_key: str, yaml_val: Any, default: str = "") -> str:
    return _env(env_key) or str(yaml_val or "") or default


def _merge_int(env_key: str, yaml_val: Any, default: int) -> int:
    v = _env(env_key)
    if v:
        try:
            return int(v)
        except ValueError:
            pass
    try:
        return int(yaml_val)
    except (TypeError, ValueError):
        return default


def _apply_common(cfg: AppConfig, raw: dict[str, Any], source: str) -> AppConfig:
    """环境变量优先、yaml 次之，填充 AppConfig 的可调参数与通知。"""
    cfg.threads = _merge_int("JPH_THREADS", raw.get("threads"), DEFAULT_THREADS)
    cfg.do_lottery = _env_flag("JPH_DO_LOTTERY", _flag(raw.get("do_lottery"), True))
    cfg.force_lottery = _env_flag("JPH_FORCE_LOTTERY", _flag(raw.get("force_lottery"), False))
    cfg.lottery_phone = _merge_str("JPH_LOTTERY_PHONE", raw.get("lottery_phone"), "")
    cfg.lottery_phone_map = _parse_phone_map(
        _env("JPH_LOTTERY_PHONE_MAP") or raw.get("lottery_phone_map") or ""
    )
    cfg.ocr = (_merge_str("JPH_OCR", raw.get("ocr"), "cv2") or "cv2").lower()
    cfg.ocr_url = _merge_str("JPH_OCR_URL", raw.get("ocr_url"), DEFAULT_OCR_URL)
    cfg.slide_retry = _merge_int("JPH_SLIDE_RETRY", raw.get("slide_retry"), DEFAULT_SLIDE_RETRY)
    cfg.read_ms = _merge_int("JPH_READ_MS", raw.get("read_ms"), 0)
    cfg.use_audio_duration = _env_flag("JPH_USE_AUDIO_DURATION", _flag(raw.get("use_audio_duration"), False))
    cfg.real_wait = _merge_int("JPH_REAL_WAIT", raw.get("real_wait"), 0)
    cfg.ac_detail = _env_flag("JPH_AC_DETAIL", _flag(raw.get("ac_detail"), True))
    cfg.activity_id = _merge_str("JPH_ACTIVITY_ID", raw.get("activity_id"), "")
    cfg.main_activity_id = _merge_str("JPH_MAIN_ACTIVITY_ID", raw.get("main_activity_id"), "")
    cfg.client_id = _merge_str("JPH_CLIENT_ID", raw.get("client_id"), DEFAULT_CLIENT_ID)
    cfg.timeout = _merge_int("JPH_TIMEOUT", raw.get("timeout"), DEFAULT_TIMEOUT)
    cfg.inter_account_delay = _merge_int("JPH_INTER_ACCOUNT_DELAY", raw.get("inter_account_delay"), 2)
    cfg.state_dir = _merge_str("JPH_STATE_DIR", raw.get("state_dir"), "")
    notify = load_notify_config(raw)
    cfg.bark = notify["bark"]
    cfg.pushplus = notify["pushplus"]
    cfg.source = source
    return cfg


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _accounts_from_env()
    if not accounts:
        return None
    return _apply_common(AppConfig(accounts=accounts), {}, "environment variables")


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
            raise ValueError(f"accounts[{i}] 格式错误，应为 name/phone/password")
        phone = str(item.get("phone") or item.get("mobile") or "").strip()
        password = str(item.get("password") or item.get("pwd") or "")
        if not phone or not password:
            raise ValueError(f"accounts[{i}] 需要 phone + password")
        accounts.append(Account(
            phone=phone,
            password=password,
            name=str(item.get("name") or item.get("note") or "").strip(),
        ))
    if not accounts:
        raise ValueError(f"{path} 中 accounts 为空")

    return _apply_common(AppConfig(accounts=accounts), raw, str(path))


def resolve_config(args: argparse.Namespace) -> AppConfig:
    if args.config:
        return load_config_yaml(Path(args.config).expanduser())
    env_cfg = load_config_from_env()
    local = SCRIPT_DIR / "config.yaml"
    if env_cfg is not None:
        if local.is_file():
            log("📦 已用环境变量 JPH / JPH_ACCOUNTS，本地 config.yaml 不会被读取")
        return env_cfg
    if local.is_file():
        return load_config_yaml(local)
    raise FileNotFoundError(
        "未找到账号配置。青龙请设 JPH=手机号#密码；"
        "本地请 cp config.example.yaml config.yaml 后填写，或 python3 daily.py -c 路径"
    )


def resolve_state_dir(cfg: AppConfig) -> Path:
    if cfg.state_dir:
        p = Path(cfg.state_dir).expanduser()
        return p if p.is_absolute() else (SCRIPT_DIR / p)
    if _env("QL_DATA_DIR"):
        return Path(_env("QL_DATA_DIR")) / "jinpinghu"
    if Path("/ql/data").is_dir():
        return Path("/ql/data") / "jinpinghu"
    return SCRIPT_DIR / "state"


# ---------------------------------------------------------------------------
# access_token 本地缓存（约 115 天，避免每天重复登录触发 10400）
# ---------------------------------------------------------------------------

def read_token_store(path: Path) -> dict[str, Any]:
    with _STATE_LOCK:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}


def write_token_store(path: Path, data: dict[str, Any]) -> None:
    # 原子写：并发缓存 token 时避免另一个线程读到写了一半的 JSON
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _STATE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 签名 / 加密
# ---------------------------------------------------------------------------

def aes_encrypt(obj: Any) -> str:
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    padder = sym_padding.PKCS7(128).padder()
    raw = padder.update(raw) + padder.finalize()
    encryptor = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV)).encryptor()
    return base64.b64encode(encryptor.update(raw) + encryptor.finalize()).decode()


def quote_param(value: Any) -> str:
    return quote(str(value), safe="!'()*-._~").replace("%20", "+")


def yd_sign(params: dict[str, Any]) -> str:
    s = "&".join("%s=%s" % (k, quote_param(params[k])) for k in sorted(params))
    return hashlib.md5((s + "&appkey=" + APPKEY).encode()).hexdigest()


def aas_key() -> str:
    """getAASkey(appkey)：奇偶位拆成两组后拼接再 MD5。"""
    even = "".join(APPKEY[i] for i in range(0, len(APPKEY), 2))
    odd = "".join(APPKEY[i] for i in range(1, len(APPKEY), 2))
    return hashlib.md5((even + odd).encode()).hexdigest()


_AAS = aas_key()


def api_signature() -> str:
    """getHeadAS()：appid;guid32;毫秒ts;md5(appid+guid+ts+AASkey)。
    写操作(task_done/ac_sub 等)必须带，缺失会返回 1000。"""
    guid = randstr(32)
    ts = int(time.time() * 1000)
    return "%s;%s;%d;%s" % (
        APPID, guid, ts,
        hashlib.md5((APPID + guid + str(ts) + _AAS).encode()).hexdigest(),
    )


def vapp_headers(path: str, session_id: str = "", account_id: str = "") -> dict[str, str]:
    rid = str(uuid.uuid4()).upper()
    ts = str(int(time.time() * 1000))
    sig = hashlib.sha256(
        "&&".join([path, session_id, rid, ts, VAPP_SALT, TENANT_ID]).encode()
    ).hexdigest()
    return {
        "User-Agent": UA_APP,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "X-REQUEST-ID": rid,
        "X-TIMESTAMP": ts,
        "X-SIGNATURE": sig,
        "X-SESSION-ID": session_id,
        "X-ACCOUNT-ID": account_id,
        "X-TENANT-ID": TENANT_ID,
        "YI-TOKEN": "",
        "X-Auth-Token": "",
        "JSSDK_APP_ID": "",
        "JSSDK_FUNC_ID": "",
    }


# ---------------------------------------------------------------------------
# 滑块识别：cv2（默认）/ ddddocr / 外部 ddddocr 服务
#
# 外部服务接口（JPH_OCR=remote）：
#   POST {JPH_OCR_URL}/capcode
#   {"backImage": <背景图 base64>, "slidingImage": <滑块图 base64>}
#   -> {"result": <缺口 x，原图坐标>}
# ---------------------------------------------------------------------------

def _image_width(data: bytes) -> int:
    """不解码整图取宽度：PNG 直接读 IHDR，JPEG 扫 SOF 段。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big")
    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3):
            return int.from_bytes(data[i + 7:i + 9], "big")
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return 0


def _background_width(bg_bytes: bytes) -> int:
    try:
        import cv2
        import numpy as np
        return int(cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR).shape[1])
    except Exception:
        return _image_width(bg_bytes)


def _remote_slide(bg_bytes: bytes, block_bytes: bytes, url: str, timeout: int) -> tuple[float, int]:
    endpoint = (url or DEFAULT_OCR_URL).rstrip("/") + "/capcode"
    payload = {
        "backImage": base64.b64encode(bg_bytes).decode(),
        "slidingImage": base64.b64encode(block_bytes).decode(),
    }
    try:
        resp = requests.post(endpoint, json=payload, timeout=timeout)
        obj = resp.json() if resp.status_code < 400 else {}
    except Exception as e:
        raise RuntimeError(f"外部 OCR 请求失败: {e}") from e
    x = obj.get("result") if isinstance(obj, dict) else None
    if x is None:
        raise RuntimeError("外部 OCR 返回空 result")
    width = _background_width(bg_bytes)
    if not width:
        raise RuntimeError("背景图宽度未知")
    return float(x), width


def _ddddocr_slide(bg_bytes: bytes, block_bytes: bytes) -> tuple[float, int]:
    import ddddocr
    import numpy as np
    import cv2

    det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)
    res = det.slide_match(block_bytes, bg_bytes, simple_target=True)
    px = int(res.get("target_x", res.get("target", [0])[0]))
    width = int(cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR).shape[1])
    return float(px), width


def _cv2_slide(bg_bytes: bytes, block_bytes: bytes) -> tuple[float, list[float]]:
    """cv2 边缘模板匹配（实测可通过）。返回（主候选 x, 备选候选 x）。"""
    import cv2
    import numpy as np

    bg = cv2.imdecode(np.frombuffer(bg_bytes, np.uint8), cv2.IMREAD_COLOR)
    bl = cv2.imdecode(np.frombuffer(block_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if bg is None or bl is None or bl.shape[2] < 4:
        raise RuntimeError("滑块图片解码失败")
    alpha = bl[:, :, 3]
    ys, xs = np.where(alpha > 128)
    if not len(xs):
        raise RuntimeError("滑块透明区域为空")
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    tpl_edge = cv2.Canny(alpha[y0:y1, x0:x1], 50, 150)
    bg_edge = cv2.Canny(cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY), 50, 150)
    res = cv2.matchTemplate(bg_edge, tpl_edge, cv2.TM_CCOEFF_NORMED)
    flat = res.flatten()
    idx = np.argsort(flat)[::-1][:400]
    cand_px: list[int] = []
    for i in idx:
        _, x = np.unravel_index(i, res.shape)
        x = int(x)
        if all(abs(x - p) > 12 for p in cand_px):
            cand_px.append(x)
        if len(cand_px) >= 3:
            break
    width = bg.shape[1]
    vals = [round((px - x0) * 324.0 / width, 1) for px in cand_px]
    return (vals[0] if vals else 0.0), vals[1:]


def solve_slide(bg_bytes: bytes, block_bytes: bytes, cfg: AppConfig) -> tuple[float, list[float]]:
    """返回按显示宽度 324 换算后的滑块 x 值及备选候选。

    优先级：JPH_OCR=ddddocr / remote 指定的方案，失败则回退 cv2 边缘模板匹配。
    """
    mode = (cfg.ocr or "cv2").lower()
    if mode == "ddddocr":
        try:
            px, width = _ddddocr_slide(bg_bytes, block_bytes)
            return round(px * 324.0 / width, 1), []
        except Exception as e:
            log(f"⚠️ ddddocr 不可用，回退 cv2: {type(e).__name__}")

    if mode in ("remote", "api"):
        try:
            px, width = _remote_slide(bg_bytes, block_bytes, cfg.ocr_url, cfg.timeout)
            if px:
                return round(px * 324.0 / width, 1), []
        except Exception as e:
            log(f"⚠️ 外部 OCR 不可用，回退 cv2: {e}")

    return _cv2_slide(bg_bytes, block_bytes)


# ---------------------------------------------------------------------------
# 今平湖客户端
# ---------------------------------------------------------------------------

def allocate_device_token() -> str:
    """真机同款 20 位纯数字（13 位毫秒 + 7 位随机），全局去重保证多账号不撞设备。"""
    with _DEVICE_LOCK:
        for _ in range(100):
            token = str(int(time.time() * 1000)) + "".join(random.choice(string.digits) for _ in range(7))
            if token not in _ISSUED_DEVICE_TOKENS:
                _ISSUED_DEVICE_TOKENS.add(token)
                return token
    raise JphError("device_token 生成失败（去重耗尽）")


def freeze_lottery_phone(phone: str, cfg: AppConfig, account_count: int,
                         all_phones: list[str]) -> tuple[str, str]:
    """解析本账号在抽奖弹窗里要提交的手机号，返回 (号码, 来源)。

    隔离规则（防止 B 账号抽成 A 账号的手机号）：
      1. 默认恒等于该账号自己的登录手机号；
      2. 全局 JPH_LOTTERY_PHONE 仅在单账号时生效，多账号一律忽略；
      3. 多账号要单独指定，必须用按账号映射 JPH_LOTTERY_PHONE_MAP 或
         JPH_LOTTERY_PHONE_<登录手机号>；
      4. 任何账号的抽奖手机号都不允许等于另一个账号的登录手机号，撞上就回退。
    """
    others = {str(x) for x in all_phones if str(x) != str(phone)}
    mapped = cfg.lottery_phone_map.get(phone) or _env("JPH_LOTTERY_PHONE_" + phone)
    if mapped:
        chosen, source = str(mapped), "按账号映射"
    elif cfg.lottery_phone and account_count <= 1:
        chosen, source = cfg.lottery_phone, "JPH_LOTTERY_PHONE(单账号)"
    elif cfg.lottery_phone:
        chosen, source = phone, "登录账号(多账号忽略全局配置)"
    else:
        chosen, source = phone, "登录账号(默认)"
    if chosen in others:
        log(f"⚠️ 抽奖手机号 {mask_mobile(chosen)} 与另一个账号的登录号冲突，已回退为 {mask_mobile(phone)}")
        return phone, "登录账号(冲突回退)"
    return chosen, source


class JinpinghuClient:
    def __init__(self, account: Account, cfg: AppConfig, tag: str,
                 account_count: int, all_phones: list[str], token_path: Path):
        self.not_started = False
        self.phone = account.phone
        self.password = account.password
        self.name = account.label
        self.cfg = cfg
        self.tag = tag
        self.token_path = token_path

        self.session = requests.Session()   # 每账号独立会话，不共享 Cookie
        self.token = ""
        self.user_id = ""
        self.session_id = ""
        self.account_id = ""
        self.nick = ""
        self.portrait = ""
        self.device_token = allocate_device_token()
        self.lottery_phone, self.lottery_phone_src = freeze_lottery_phone(
            self.phone, cfg, account_count, all_phones
        )
        self.other_phones = {str(x) for x in all_phones if str(x) != str(self.phone)}
        self.lines: list[str] = []
        self.summary: dict[str, Any] = {}
        self.afs_tokenid = ""
        self.slide_fail_reason = ""
        self.slide_referer = REFERER
        self.api_dt = ""  # 服务端签发的 Access-Api-Dt（_auth_dt 接口，写操作校验）
        self.owner_token: Optional[str] = None
        self.owner_uid: Optional[str] = None

    # ---------- 日志 ----------
    def note(self, msg: str) -> None:
        self.lines.append(str(msg))
        log(f"[{self.tag}] {msg}")

    def debug(self, msg: str) -> None:
        if IS_DEBUG:
            log(f"[{self.tag}]    🔍 {str(msg)[:600]}")

    # ---------- 登录 ----------
    def login(self) -> None:
        # 多线程错峰，避免同 IP 瞬时并发触发 10400
        time.sleep(random.uniform(0.2, 1.4))
        r = self.session.get(
            PASSPORT_BASE + "/web/init",
            params={"client_id": self.cfg.client_id},
            headers={"User-Agent": UA_APP},
            timeout=self.cfg.timeout,
        )
        self.debug(r.text)
        if not ok(jbody(r)):
            raise JphError("passport init 失败: " + r.text[:120])

        pub = serialization.load_der_public_key(base64.b64decode(RSA_PUB))
        enc_pwd = base64.b64encode(pub.encrypt(self.password.encode(), rsa_padding.PKCS1v15())).decode()
        body = "client_id=%s&password=%s&phone_number=%s" % (
            self.cfg.client_id, quote(enc_pwd, safe=""), self.phone,
        )
        r = self.session.post(
            PASSPORT_BASE + "/web/oauth/credential_auth",
            data=body,
            headers={
                "User-Agent": UA_APP,
                "Content-Type": "application/x-www-form-urlencoded",
                "X-REQUEST-ID": str(uuid.uuid4()),
            },
            timeout=self.cfg.timeout,
        )
        obj = jbody(r)
        if not ok(obj):
            raise JphError("帐密登录失败: " + r.text[:160])
        code = obj["data"]["authorization_code"]["code"]

        oi, txt_i = self.vapp_post("/api/account/init")
        if not ok(oi) or not (oi.get("data") or {}).get("session"):
            raise JphError("account/init 失败: " + (txt_i or str(oi))[:160])
        anon = oi["data"]["session"]["id"]

        obj, txt_l = self.vapp_post("/api/zbtxz/login", data={"code": code}, session_id=anon)
        if not ok(obj) or not (obj.get("data") or {}).get("session"):
            raise JphError("App 登录失败: " + (txt_l or str(obj))[:160])
        data = obj["data"]
        self.session_id = data["session"]["id"]
        self.account_id = data["account"]["id"]
        self.nick = data["account"].get("nick_name", "")
        self.portrait = data["account"].get("image_url", "")

        r = self.session.get(
            VAPP_BASE + "/api/zbtxz/get_access_token",
            headers=vapp_headers("/api/zbtxz/get_access_token", self.session_id, self.account_id),
            timeout=self.cfg.timeout,
        )
        self.debug("get_access_token " + r.text[:120])

        payload = {
            "app_user_token": self.session_id,
            "user_id": self.account_id,
            "phone": self.phone,
            "user_name": self.nick,
            "portrait_url": self.portrait,
            "wx_openid": "",
            "wx_unionid": "",
            "appid": APPID,
            "noncestr": randstr(6),
            "timestamp": int(time.time()),
        }
        payload["signature"] = yd_sign(payload)
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": H5_ORIGIN,
            "Referer": H5_ORIGIN + "/",
            "Access-Token": "",
            "Access-T-Id": T_ID,
            "Access-T-Id-In": T_ID,
            "Access-User-Id": "0",
            "Access-Wxclient-Type": "wx_app",
            "Access-Api-Unique-Token": "1",
            "Access-Api-Dt": DEVICE_DT,
        }
        r = self.session.post(
            YA_BASE + "/api/aosbase/_auth_appuserinit", json=payload,
            headers=headers, timeout=self.cfg.timeout,
        )
        obj = jbody(r)
        if not ok(obj):
            raise JphError("换取 access_token 失败: " + r.text[:160])
        self.token = obj["data"]["access_token"]
        self.cache_token()
        self.summary["login"] = "帐密登录"
        self.note(f"🔑 帐密登录成功  session={self.session_id[:10]}…")
        self.ensure_api_dt()

    def vapp_post(self, path: str, data: Optional[dict[str, Any]] = None,
                  session_id: str = "", account_id: str = "") -> tuple[dict, str]:
        """vapp POST，带频控(10400)指数退避重试。"""
        obj, text = {}, ""
        for i in range(4):
            r = self.session.post(
                VAPP_BASE + path, data=data,
                headers=vapp_headers(path, session_id, account_id),
                timeout=self.cfg.timeout,
            )
            obj, text = jbody(r), r.text
            if ok(obj) and (obj.get("data") or {}).get("session"):
                return obj, text
            if obj.get("code") == 10400 or "频繁" in text:
                time.sleep(2 + i * 2 + random.random())
                continue
            break
        return obj, text

    # ---------- access_token 缓存 ----------
    def cache_token(self) -> None:
        with _STATE_LOCK:
            store = read_token_store(self.token_path)
            entry = store.get(self.phone) or {}
            if not isinstance(entry, dict):
                entry = {}
            entry.update({
                "token": self.token,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "account_id": self.account_id,
                "ts": int(time.time()),
            })
            store[self.phone] = entry
            write_token_store(self.token_path, store)

    # ---------- 服务端设备凭证（Access-Api-Dt） ----------
    def ensure_api_dt(self) -> None:
        """获取/复用服务端签发的 Access-Api-Dt（_auth_dt 原始串取 [32:68]）。

        App 端缓存 3 天；服务端改版（2026-11-18）后写操作会校验该头，
        用旧写死值会报 1003「缺少参数或者参数异常」。"""
        if self.api_dt:
            return
        store = read_token_store(self.token_path).get(self.phone) or {}
        cached = store.get("api_dt") if isinstance(store, dict) else None
        ts = int(store.get("api_dt_ts") or 0) if isinstance(store, dict) else 0
        if cached and time.time() - ts < 2 * 86400:
            self.api_dt = str(cached)
            return
        try:
            r = self.session.get(
                YA_BASE + "/api/aosbase/_auth_dt",
                headers=self.biz_headers(), timeout=self.cfg.timeout,
            )
            raw = (jbody(r).get("data") or "")
            if isinstance(raw, str) and len(raw) >= 68:
                self.api_dt = raw[32:68]
                with _STATE_LOCK:
                    store2 = read_token_store(self.token_path)
                    entry = store2.get(self.phone) or {}
                    if isinstance(entry, dict):
                        entry["api_dt"] = self.api_dt
                        entry["api_dt_ts"] = int(time.time())
                        store2[self.phone] = entry
                        write_token_store(self.token_path, store2)
                self.debug(f"_auth_dt 更新 Access-Api-Dt={self.api_dt[:8]}…")
            else:
                self.debug(f"_auth_dt 返回异常: {r.text[:120]}")
        except Exception as e:
            self.debug(f"_auth_dt {type(e).__name__}")

    def restore_token(self) -> bool:
        store = read_token_store(self.token_path).get(self.phone) or {}
        token = store.get("token")
        if not token or time.time() - int(store.get("ts") or 0) > TOKEN_TTL:
            return False
        self.token = token
        self.session_id = store.get("session_id", "")
        self.account_id = store.get("account_id", "")
        try:
            obj, _ = self.get("/api/aosbase/user_info")
            data = obj.get("data") or {}
            if data.get("id"):
                self.user_id = str(data["id"])
                self.summary["login"] = "缓存登录态"
                self.note("🔑 复用已缓存 access_token（免登录）")
                self.ensure_api_dt()
                return True
        except Exception:
            pass
        self.token = ""
        return False

    # ---------- 业务请求 ----------
    def biz_headers(self, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Origin": H5_ORIGIN,
            "Referer": H5_ORIGIN + "/",
            "Access-Token": self.token,
            "Access-User-Id": self.user_id or "0",
            "Access-T-Id": T_ID,
            "Access-T-Id-In": T_ID,
            "Access-Api-Unique-Token": "1",
            # 必须服务端 _auth_dt 签发（取 [32:68]）；2026-11-18 服务端改版后
            # 写死的旧值会让 task_done 报 1003「缺少参数或者参数异常」
            "Access-Api-Dt": self.api_dt or DEVICE_DT,
            "Access-Wxclient-Type": "wx_app",
            "Access-Api-Signature": api_signature(),
            # 真机 H5 页面请求指纹：ac_sub 涉及现金，风控比 task_done 严
            "User-Agent": UA_H5,
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-site",
            "Priority": "u=3, i",
        }
        if extra:
            headers.update(extra)
        return headers

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> tuple[dict, str]:
        r = self.session.get(YA_BASE + path, params=params, headers=self.biz_headers(),
                             timeout=self.cfg.timeout)
        self.debug(f"{path} {r.text[:300]}")
        return jbody(r), r.text

    def post(self, path: str, obj: Any) -> tuple[dict, str]:
        r = self.session.post(YA_BASE + path, json=obj, headers=self.biz_headers(),
                              timeout=self.cfg.timeout)
        self.debug(f"{path} {r.text[:300]}")
        return jbody(r), r.text

    def ensure_user(self) -> None:
        obj, _ = self.get("/api/aosbase/user_info")
        data = obj.get("data") or {}
        self.user_id = str(data.get("id", ""))
        if not self.user_id:
            raise JphError("user_info 获取失败")
        self.summary["uid"] = self.user_id
        self.summary["nick"] = data.get("name", "")
        self.note(f"👤 账号 uid={self.user_id}  昵称={data.get('name', '')}")

    # ---------- 滑块 ----------
    def pass_slide(self) -> bool:
        # referer 里的 pass_id 是当天任务集 ID（真机抓包实测），必须动态；
        ref = self.slide_referer or REFERER
        for attempt in range(1, max(1, self.cfg.slide_retry) + 1):
            ts = int(time.time())
            once = randstr(10)
            sig = aes_encrypt({"once": once, "referer": ref, "timestamp": ts, "type": "1"})
            query = "once=%s&referer=%s&timestamp=%d&type=1&signature=%s" % (
                once,
                quote(ref, safe=""),
                ts,
                quote(quote(sig, safe=""), safe=""),
            )
            r = self.session.get(YA_BASE + "/api/basemodule/_captcha_get?" + query,
                                 headers=self.biz_headers(), timeout=self.cfg.timeout)
            obj = jbody(r)
            data = obj.get("data") or {}
            token = data.get("token")
            if not token:
                self.debug("captcha_get: " + r.text[:200])
                continue
            try:
                bg_bytes = self.session.get(data["background"], timeout=self.cfg.timeout).content
                block_bytes = self.session.get(data["block"], timeout=self.cfg.timeout).content
                x, extra = solve_slide(bg_bytes, block_bytes, self.cfg)
            except Exception as e:
                self.note(f"❌ 滑块识别依赖缺失({type(e).__name__})，需 cv2/numpy、ddddocr 或外部 OCR 服务")
                self.slide_fail_reason = f"识别依赖缺失({type(e).__name__})"
                return False
            for xx in [x] + extra:
                track = [{"x": round(xx * (i + 1) / 8.0, 1), "y": 0, "time": 100} for i in range(8)]
                body = {
                    "token": token,
                    "data": aes_encrypt({"x": xx, "width": 324, "track": track}),
                    "referer": ref,
                    "type": "1",
                }
                rr = self.session.post(YA_BASE + "/api/basemodule/_captcha_check", json=body,
                                       headers=self.biz_headers(), timeout=self.cfg.timeout)
                oo = jbody(rr)
                if (oo.get("data") or {}).get("result") is True:
                    validate = oo["data"]["token"]
                    vb = {"validate": validate, "verif_type": 3, "afs_uuid": "", "source": "yundian"}
                    rv = self.session.post(YA_BASE + "/api/aosbasemodule/intelverifcode_check",
                                           json=vb, headers=self.biz_headers(), timeout=self.cfg.timeout)
                    ov = jbody(rv)
                    tokenid = (ov.get("data") or {}).get("tokenid")
                    if tokenid:
                        self.afs_tokenid = tokenid
                        self.note(f"🧩 滑块自动通过 (x={xx:.1f}, 第{attempt}轮) tokenid={tokenid[:8]}…")
                        return True
                # 同一 token 只允许校验一次，换下一候选需重新取图
                break
        self.note("⚠️ 滑块未通过，本轮跳过写操作")
        self.slide_fail_reason = "多次校验未通过"
        return False

    # ---------- 看新闻 / 视频 ----------
    def read_article(self, news_id: Any) -> int:
        """打开新闻/视频并上报阅读时长。

        用户实测每个视频看约 3 分钟，默认统一上报 180000ms + 随机抖动。
        JPH_READ_MS>0 强制覆盖；JPH_USE_AUDIO_DURATION=1 改为按该篇 audio_duration；
        JPH_REAL_WAIT>0 可开启真实等待（秒）。实测服务端只校验上报值，不需真实等待。
        """
        if not news_id:
            return 0
        read_ms = 180000 + random.randint(1000, 9000)
        try:
            path = "/api/article/detail/v2"
            qs = "?id=%s&tenantId=%s&url_Path=/webDetails/news" % (news_id, TENANT_ID)
            rd = self.session.get(
                VAPP_BASE + path + qs,
                headers=vapp_headers(path, self.session_id, self.account_id),
                timeout=self.cfg.timeout,
            )
            article = (jbody(rd).get("data") or {}).get("article") or {}
            try:
                duration_min = int(article.get("audio_duration") or 0)
            except (TypeError, ValueError):
                duration_min = 0
            for p, qs2 in (
                ("/api/article/grass", qs),
                ("/api/comment/list", "?channel_article_id=%s&size=20&sort_type=0" % news_id),
            ):
                self.session.get(
                    VAPP_BASE + p + qs2,
                    headers=vapp_headers(p, self.session_id, self.account_id),
                    timeout=self.cfg.timeout,
                )
            if self.cfg.read_ms > 0:
                read_ms = self.cfg.read_ms
            elif self.cfg.use_audio_duration and duration_min > 0:
                read_ms = duration_min * 60000 + random.randint(1000, 9000)

            for p, suffix in (
                ("/api/article/read_time",
                 "?channel_article_id=%s&is_end=1&read_time=%d" % (news_id, read_ms)),
                ("/api/article/audio_listen_duration",
                 "?channel_article_id=%s&duration=%d" % (news_id, read_ms)),
            ):
                self.session.get(
                    VAPP_BASE + p + suffix,
                    headers=vapp_headers(p, self.session_id, self.account_id),
                    timeout=self.cfg.timeout,
                )
            if self.cfg.real_wait > 0:
                time.sleep(min(self.cfg.real_wait, 180))
            self.debug(f"news={news_id} audio_duration={duration_min}min read_time={read_ms}ms")
        except Exception as e:
            self.debug(f"read_article {type(e).__name__}")
        return read_ms

    # ---------- 当天活动 / 任务集动态发现 ----------
    def discover_main_activity(self) -> str:
        """主活动 ID 按轮次变（如「看6分钟新闻 领现金红包（11月第2轮）」）。
        真机从 vapp /api/buoy/list 的浮标入口 module-study/home/home?...id=<id> 拿到。
        JPH_MAIN_ACTIVITY_ID 可强制指定；发现失败回退 MAIN_ACTIVITY_ID。"""
        if self.cfg.main_activity_id:
            return self.cfg.main_activity_id
        try:
            path = "/api/buoy/list"
            r = self.session.get(
                VAPP_BASE + path,
                headers=vapp_headers(path, self.session_id, self.account_id),
                timeout=self.cfg.timeout,
            )
            k = r.text.find("module-study/home/home")
            if k >= 0:
                m = re.search(r"id=(\d+)", r.text[k:k + 400])
                if m:
                    self.debug(f"buoy/list 主活动ID={m.group(1)}")
                    return m.group(1)
        except Exception as e:
            self.debug(f"buoy/list {type(e).__name__}")
        return MAIN_ACTIVITY_ID

    def resolve_optionp(self) -> tuple[str, str, str, str]:
        """动态解析当天任务集，返回 (任务集ID, module_id, 标题, 主活动ID)。

        _optionp_list 返回带 start_time/end_time/state 的每日任务集列表：
        今天是 {id:33582, m_id:41603, title:'11月18日 新闻任务'}，明天整个 id 都会换，
        任务内容(_task_list 的 news_id)也每天换 —— 这三处都不能写死。
        选中项同时写入 self.slide_referer，让滑块签名里的 pass_id 跟着当天走。
        """
        main = self.discover_main_activity()
        now = int(time.time())
        items: list[dict[str, Any]] = []
        try:
            obj, _ = self.get("/api/aoslearnfoot/_optionp_list", {"activity_id": main})
            items = obj.get("data") or []
        except Exception as e:
            self.debug(f"_optionp_list {type(e).__name__}")

        pick: Optional[dict[str, Any]] = None
        if self.cfg.activity_id:
            forced = self.cfg.activity_id
            pick = next((x for x in items if str(x.get("id")) == str(forced)), None)
            if pick is None:
                pick = {"id": forced, "m_id": DEFAULT_MODULE_ID, "title": "(JPH_ACTIVITY_ID 指定)"}
        if pick is None:
            for x in items:
                try:
                    st, en = int(x.get("start_time") or 0), int(x.get("end_time") or 0)
                except (TypeError, ValueError):
                    st = en = 0
                if st and en and st <= now <= en and str(x.get("state") or "1") != "0":
                    pick = x
                    break
        if pick is None and items:
            pick = next((x for x in items if str(x.get("state") or "1") != "0"), items[0])

        op_id = str((pick or {}).get("id") or DEFAULT_OPTIONP_ID)
        module_id = str((pick or {}).get("m_id") or DEFAULT_MODULE_ID)
        title = str((pick or {}).get("title") or "?")
        self.slide_referer = (
            H5_ORIGIN + "/module-study/pass-detail/pass-detail"
            "?pass_id=%s&activity_id=%s" % (op_id, main)
        )
        self.summary["optionp"] = title
        self.summary["optionp_window"] = "%s ~ %s" % (
            fmt_ts((pick or {}).get("start_time")),
            fmt_ts((pick or {}).get("end_time")),
        )
        # 任务集每天 09:00 才生效：早于开始时间跑定时，只读可以列任务，写操作要跳过
        try:
            start_ts = int((pick or {}).get("start_time") or 0)
        except (TypeError, ValueError):
            start_ts = 0
        self.not_started = bool(start_ts and now < start_ts)
        return op_id, module_id, title, main

    # ---------- 任务 ----------
    def do_tasks(self, dry: bool = False) -> int:
        op_id, module_id, op_title, main = self.resolve_optionp()
        self.note(
            f"📌 当天活动集: {op_title} (id={op_id} module={module_id} 主活动={main} "
            f"有效期={self.summary.get('optionp_window', '?')})"
        )

        obj, _ = self.get("/api/aoslearnfoot/optionp_detail", {"id": op_id})
        data = obj.get("data") or {}
        self.note(f"📋 活动: {data.get('title', '?')}  需完成 {data.get('task_num', '?')} 个任务")

        obj, text = self.get("/api/aosbasemodule/_task_list", {
            "offset": 0, "count": 30, "module_id": module_id, "activity_id": op_id,
        })
        tasks = obj.get("data") or []
        if not tasks:
            self.debug("task_list resp: " + text[:300])
            self.note("⚠️ 今天没有任务（可能活动未开始或已结束）")
            self.summary["tasks"] = "无任务"
            return 0
        self.note(f"📋 任务列表: {len(tasks)} 条")

        if dry:
            for t in tasks[:3]:
                self.note(f"   #{t.get('id')} {str(t.get('title', ''))[:26]} (今日已完成={t.get('user_done', '?')})")
            self.summary["tasks"] = f"只读 {len(tasks)} 条"
            return 0

        if getattr(self, "not_started", False):
            self.note("⏳ 今天任务集还没到生效时间（每天 09:00 刷新），本次跳过写操作")
            self.summary["tasks"] = "未到生效时间"
            return 0

        done_flag = ("1", "True", "true")
        already = sum(1 for t in tasks if str(t.get("user_done") or "0") in done_flag)
        if already:
            self.note(f"👌 今日已完成 {already}/{len(tasks)} 个任务，跳过重复提交")
        if already >= len(tasks):
            self.summary["tasks"] = f"今日已完成 {already}/{len(tasks)}"
            return 0
        if not self.pass_slide():
            self.summary["tasks"] = f"滑块未通过（{self.slide_fail_reason or '未知原因'}）"
            return 0

        done = 0
        for t in tasks:
            task_id = t.get("id")
            if str(t.get("user_done") or "0") in done_flag:
                continue
            news_id = ""
            try:
                news_id = json.loads(t.get("rule") or "{}").get("news_id", "")
            except Exception:
                pass
            oc, _ = self.post("/api/aosbasemodule/task_create", {"task_id": task_id})
            record_id = (oc.get("data") or {}).get("task_record_id")
            if not record_id:
                self.note(f"   ❌ 任务 {task_id} 创建失败: {oc.get('msg') or oc.get('code')}")
                continue
            read_ms = self.read_article(news_id)
            body = {
                "task_record_id": record_id,
                "collect_info": "",
                "afs_tokenid": self.afs_tokenid,
                "device_token": self.device_token,
            }
            od, _ = self.post("/api/aosbasemodule/task_done", body)
            if ok(od):
                lottery = (od.get("data") or {}).get("lottery") or {}
                done += 1
                self.note(f"   ✅ 任务 {task_id} 完成（上报 {read_ms / 60000.0:.1f} 分钟）  抽奖次数={lottery.get('num', '?')}")
                if lottery.get("id"):
                    self.summary["lottery_id"] = lottery["id"]
            else:
                self.note(f"   ❌ 任务 {task_id} 提交失败: {od.get('msg') or od.get('code')}")

        self.summary["tasks"] = f"本次 {done} / 共 {len(tasks)}"
        return done

    # ---------- 抽奖 / 提现手机号 ----------
    def wx_bind_ok(self, retries: int = 3) -> tuple[Optional[bool], str]:
        """提现微信绑定判定，三态返回 (state, info)：

        True  = 已绑定（bind=1 且 openid 非空）
        False = 明确未绑定
        None  = 查询失败（限流/异常且重试耗尽），状态未知

        user_appbindwx 有短时限流：连续调用会回 110110「访问过于频繁」且 data=""，
        必须退避重试，否则会被误判成未绑定而中止正常抽奖。
        """
        last = "查询无响应"
        for i in range(retries):
            try:
                obj, _ = self.get("/api/aosbase/user_appbindwx")
            except Exception as e:
                last = f"查询异常({type(e).__name__})"
                time.sleep(1.0 + i * 0.6)
                continue
            data = obj.get("data")
            code = str(obj.get("code"))
            if code != "0" or not isinstance(data, dict):
                last = f"接口 {code} {obj.get('msg') or ''}".strip()
                time.sleep(1.5 + i * 0.8)   # 110110 限流退避
                continue
            bind = data.get("bind")
            openid = str(data.get("openid") or "").strip()
            if str(bind) not in ("1", "True", "true"):
                return False, f"bind={bind}"
            if not openid:
                return False, "bind=1 但 openid 为空"
            return True, openid
        return None, last

    def assert_isolated(self, phone_field: str, phone: str, body: dict[str, Any]) -> bool:
        """发 ac_sub 前的账号隔离硬校验。任何一项不通过都直接中止，
        连埋点都不发 —— 宁可这次不抽，也绝不把 A 的手机号提交到 B 的抽奖上。"""
        def fail(why: str) -> bool:
            self.note(f"❌ 账号隔离校验失败（{why}）-> 已中止 ac_sub，未提交任何抽奖请求")
            return False

        if str(phone) != str(self.lottery_phone):
            return fail("抽奖手机号不是本账号冻结值")
        if str(phone) in self.other_phones:
            return fail("抽奖手机号撞上另一个账号的登录号")
        try:
            collect_info = json.loads(body.get("collect_info") or "{}")
        except Exception:
            return fail("collect_info 无法解析")
        if set(collect_info.keys()) != {phone_field} or str(collect_info.get(phone_field)) != str(phone):
            return fail("collect_info 里的手机号与本账号不一致")
        if not body.get("afs_tokenid"):
            return fail("缺少本账号滑块凭证")
        if body.get("device_token") != self.device_token:
            return fail("device_token 不属于本账号")
        headers = self.biz_headers()
        if self.owner_token is not None and (
            self.token != self.owner_token or str(self.user_id) != str(self.owner_uid)
        ):
            return fail("登录态在运行时被改写，已不属于本账号")
        if not self.token or headers.get("Access-Token") != self.token:
            return fail("请求头登录态不属于本账号")
        if str(headers.get("Access-User-Id")) != str(self.user_id):
            return fail("请求头 uid 不属于本账号")
        with _DEVICE_LOCK:
            tokenid = body.get("afs_tokenid")
            if tokenid in _USED_SLIDE_TOKENS:
                return fail("滑块凭证已被其它账号使用")
            _USED_SLIDE_TOKENS.add(tokenid)
        self.debug(f"账号隔离校验通过 phone={mask_mobile(phone)} device_token={self.device_token} token={self.token[:8]}…")
        return True

    def ac_detail(self, lottery_id: str) -> dict[str, Any]:
        """真机抽奖前必拉的活动详情（静态 CDN）：含 prevent_cheat 验证配置与手机号表单。
        返回 rule dict；失败返回 {}（不影响主流程，手机号字段回退到内置常量）。"""
        if not self.cfg.ac_detail:
            return {}
        try:
            url = f"{STATIC2_BASE}/api/static_3/aoslottery/_ac_detail/{lottery_id}.json"
            r = self.session.get(url, headers=self.biz_headers(), timeout=self.cfg.timeout)
            self.debug("_ac_detail " + r.text[:200])
            rule = (jbody(r).get("data") or {}).get("rule") or {}
            if isinstance(rule, str):
                rule = json.loads(rule)
            return rule if isinstance(rule, dict) else {}
        except Exception as e:
            self.debug(f"_ac_detail {type(e).__name__}")
            return {}

    def lottery(self, dry: bool = False) -> None:
        lottery_id = self.summary.get("lottery_id") or LOTTERY_ID
        # 真机抽奖前先拉活动详情：验证类型 + 领奖要手输的手机号表单字段。
        rule = self.ac_detail(lottery_id)
        options = (rule.get("collect") or {}).get("options") or []
        phone_field = str((options[0] or {}).get("id") or PHONE_FIELD) if options else PHONE_FIELD
        # 抽奖弹窗当场要输的手机号：用实例创建时按账号冻结的值，
        # 运行时绝不读全局 JPH_LOTTERY_PHONE，多账号并发不会串号。
        phone = self.lottery_phone
        self.note(
            "🎟️ 活动详情: 验证类型=%s 手机号字段=%s 抽奖手机号=%s(来源:%s)" % (
                (rule.get("prevent_cheat") or {}).get("verif_type", "?"),
                phone_field, mask_mobile(phone), self.lottery_phone_src,
            )
        )

        # 提现前置：必须已在 App/小程序里授权绑定提现微信。
        # 实测未绑定时 ac_sub 会被拒但仍扣掉抽奖次数，必须先检测，避免白扣。
        bound, info = self.wx_bind_ok()
        if bound is not True and not self.cfg.force_lottery:
            why = f"未绑定提现微信({info})" if bound is False else f"绑定状态未知({info})"
            self.note(
                f"⚠️ {why} -> 首页/右下悬浮框/阅读任务/首次提现请绑定微信；"
                "保守跳过抽奖以免白扣次数"
            )
            self.summary["lottery"] = "跳过（未绑微信）"
            return
        if self.cfg.force_lottery and bound is not True:
            self.note(f"⚠️ JPH_FORCE_LOTTERY=1 已绕过绑定检测({info})，本次请求可能白扣次数")

        obj, _ = self.get("/api/aoslottery/ac_lottery_times", {"id": lottery_id})
        data = obj.get("data") or {}
        times_text = f"总={data.get('all_remain')} 今日={data.get('day_remain')}"
        self.note(f"🎟️ 剩余抽奖次数: {times_text}")
        self.summary["lottery_times"] = times_text

        if dry or not self.cfg.do_lottery:
            self.summary["lottery"] = "只刷次数，不提交 ac_sub"
            return

        remain = int(data.get("all_remain") or data.get("day_remain") or 0)
        if remain <= 0:
            self.note("⚠️ 无可用抽奖次数，跳过")
            self.summary["lottery"] = "无可用次数"
            return

        # ac_sub 必须带 intelverifcode_check 滑块凭证(afs_tokenid)。
        # 任务已完成而跳过 do_tasks 时 afs_tokenid 为空，这里独立刷新一次。
        # 注意：1007「o d d w」不是缺凭证，是服务端未中奖暗号（见文件头说明）。
        self.afs_tokenid = ""
        if not self.pass_slide() or not self.afs_tokenid:
            self.note("⚠️ 抽奖前置滑块凭证未拿到，跳过 ac_sub 以免白扣次数")
            self.summary["lottery"] = f"滑块未通过（{self.slide_fail_reason or '未知原因'}）"
            return

        # 发奖前二次复核：防止查次数与提交之间绑定状态变化导致白扣。
        # 只把「明确未绑定」当中止条件；限流/异常重试耗尽属未知，沿用首次结果。
        if not self.cfg.force_lottery:
            bound2, info2 = self.wx_bind_ok()
            if bound2 is False:
                self.note(f"⚠️ 发奖前复核未绑定({info2})，中止 ac_sub 以免白扣次数")
                self.summary["lottery"] = "跳过（未绑微信）"
                return
            if bound2 is None:
                self.note(f"⚠️ 发奖前复核状态未知({info2})，沿用首次已绑定结果继续抽奖")

        body = {
            "id": lottery_id,
            "verif_uuid": "",
            "verif_code": "",
            "afs_tokenid": self.afs_tokenid,
            "collect_info": json.dumps({phone_field: phone}, separators=(",", ":")),
            "longitude": 0,
            "latitude": 0,
            "device_token": self.device_token,
        }
        # 隔离硬校验放在埋点之前：校验不通过连 lotteryTake 埋点都不发
        if not self.assert_isolated(phone_field, phone, body):
            self.summary["lottery"] = "隔离校验未通过"
            return

        # 真机在 ac_sub 前会上报 lotteryTake 行为埋点，且与抽奖共用同一个 device_token
        try:
            self.post("/api/aosstat/_event_sub", {
                "_need_stat": 0,
                "_need_task": 0,
                "_need_behavior": 1,
                "event": "lotteryTake",
                "action": "take",
                "brief": "抽奖提交",
                "client_type": 2,
                "module_id": "40602",
                "content_id": 10304931,
                "num": 1,
                "duration": 0,
                "column_id": 0,
                "column_title": "",
                "title": "新闻红包（11月第2轮）",
                "device_token": self.device_token,
                "user_id": int(self.user_id or 0),
                "phone_num": mask_mobile(phone),
                "page_path": "module-study/pass-detail/pass-detail",
                "version": "1.0.0",
            })
        except Exception:
            pass

        self.debug("ac_sub body=" + json.dumps(body, ensure_ascii=False))
        obj, raw = self.post("/api/aoslottery/ac_sub", body)
        if ok(obj):
            data = obj.get("data") or {}
            self.note(f"🎰 抽奖成功（已提交手机号 {mask_mobile(phone)}）: {data.get('title', '?')}  价值={data.get('value', '?')}")
            self.summary["lottery"] = f"中奖: {data.get('title', '?')}"
            return

        msg = str(obj.get("msg") or "")
        flat = msg.replace(" ", "")
        if flat in ("oadw", "oddw"):
            self.note(
                f"🎰 本次未中奖（服务端暗号 {msg}；前端 checkPrizeIsEmpty 把 o a d w 判为未中奖）。"
                f"领奖手机号 {mask_mobile(phone)} 已提交，次数正常消耗、无中奖记录，属概率结果非请求错误"
            )
            self.summary["lottery"] = "未中奖（o d d w）"
        elif "none" in msg:
            self.note(f"🎰 抽奖未发放({msg})；次数已消耗，领奖手机号 {mask_mobile(phone)}")
            self.summary["lottery"] = f"未发放（{msg}）"
        else:
            self.note(f"❌ 抽奖失败（注意：非 0 响应仍会扣掉次数）: {str(raw or obj)[:200]}")
            self.summary["lottery"] = "抽奖失败"

    # ---------- 入口 ----------
    def run(self, dry: bool = False, check: bool = False) -> None:
        if not self.restore_token():
            self.login()
        if not self.user_id:
            self.ensure_user()
            if self.token:
                self.cache_token()

        if check:
            bound, info = self.wx_bind_ok()
            self.summary["bind"] = (
                "已绑定" if bound is True else ("未绑定" if bound is False else f"未知（{info}）")
            )
            self.note(f"🔗 提现微信: {self.summary['bind']}")
            try:
                obj, _ = self.get("/api/aoslottery/ac_lottery_times", {"id": LOTTERY_ID})
                data = obj.get("data") or {}
                if data:
                    self.summary["lottery_times"] = f"总={data.get('all_remain')} 今日={data.get('day_remain')}"
                    self.note(f"🎟️ 剩余抽奖次数: {self.summary['lottery_times']}")
            except Exception:
                pass
            return

        # 冻结本账号登录态；ac_sub 前会复核，运行中被别的账号对象改写就立即中止
        self.owner_token, self.owner_uid = self.token, self.user_id
        self.do_tasks(dry=dry)

        # JPH_DO_LOTTERY=0 = 只刷抽奖次数、把机会留给用户在 App 里手动抽。
        # 这里连 lottery() 都不进，确保绝不会发出 ac_sub（机会只有一次，不容误扣）。
        if not dry and self.cfg.do_lottery:
            self.lottery()
        elif not dry:
            self.note("🎰 抽奖已关闭（JPH_DO_LOTTERY=0），次数保留给你手动抽")
            self.summary["lottery"] = "已关闭"


# ---------------------------------------------------------------------------
# 单账号执行
# ---------------------------------------------------------------------------

def run_account(index: int, account: Account, cfg: AppConfig, all_phones: list[str],
                token_path: Path, dry: bool, check: bool) -> dict[str, Any]:
    tag = "A%d" % index
    client = JinpinghuClient(account, cfg, tag, len(cfg.accounts), all_phones, token_path)
    log(f"[{tag}] 👤 {account.label}  {mask_mobile(account.phone)}")
    log(
        f"[{tag}] 🔐 账号隔离: 登录号={mask_mobile(account.phone)} "
        f"抽奖手机号={mask_mobile(client.lottery_phone)} (来源:{client.lottery_phone_src}) "
        f"device_token={client.device_token}"
    )
    try:
        client.run(dry=dry, check=check)
        result = {
            "label": account.label,
            "phone": account.phone,
            "ok": True,
            "summary": client.summary,
            "lines": client.lines,
        }
    except Exception as e:
        client.note(f"❌ 失败: {type(e).__name__}: {str(e)[:160]}")
        if IS_DEBUG:
            log(traceback.format_exc())
        result = {
            "label": account.label,
            "phone": account.phone,
            "ok": False,
            "summary": client.summary,
            "lines": client.lines,
            "error": f"{type(e).__name__}: {str(e)[:160]}",
        }
    finally:
        client.session.close()
    return result


# ---------------------------------------------------------------------------
# 汇总与通知（青龙统一通知 → Bark → PushPlus）
# ---------------------------------------------------------------------------

def build_summary(results: list[dict[str, Any]], mode: str) -> tuple[str, str]:
    total = len(results)
    ok_n = sum(1 for r in results if r.get("ok"))
    fail_n = total - ok_n
    now = datetime.now().strftime("%m-%d %H:%M")

    if total == 0:
        title = "今平湖 · 无账号"
    elif fail_n == 0:
        title = f"今平湖 {mode} ✅"
    elif ok_n == 0:
        title = f"今平湖 {mode} ❌"
    else:
        title = f"今平湖 {mode} ⚠️ {ok_n}/{total}"

    lines = [
        f"📰 今平湖 · 阅读红包（{mode}）",
        f"📅 {now}",
        "────────────────",
        "",
    ]
    for i, r in enumerate(results):
        icon = ICONS[i % len(ICONS)]
        summary = r.get("summary") or {}
        lines.append(f"{icon} 【{r.get('label') or '?'}】{mask_mobile(r.get('phone') or '')}")
        if not r.get("ok"):
            lines.append("   ❌ 状态：失败")
            lines.append(f"   💬 {r.get('error') or '未知错误'}")
        else:
            if summary.get("login"):
                lines.append(f"   🔑 登录：{summary['login']}")
            if summary.get("optionp"):
                window = f"（{summary['optionp_window']}）" if summary.get("optionp_window") else ""
                lines.append(f"   📌 活动集：{summary['optionp']}{window}")
            if summary.get("tasks"):
                lines.append(f"   ✅ 任务：{summary['tasks']}")
            if summary.get("lottery_times"):
                lines.append(f"   🎟️ 剩余次数：{summary['lottery_times']}")
            if summary.get("lottery"):
                lines.append(f"   🎰 抽奖：{summary['lottery']}")
            if summary.get("bind"):
                lines.append(f"   🔗 微信绑定：{summary['bind']}")
            if r.get("lines"):
                tail = r["lines"][-1]
                if tail and not any(tail in ln for ln in lines):
                    lines.append(f"   💬 {tail}")
        if i < total - 1:
            lines.append("")
    lines.extend([
        "",
        "────────────────",
        f"📦 账号 {total} · ✅{ok_n}  ❌{fail_n}",
    ])
    if fail_n == 0:
        lines.append("🎉 全部顺利")
    elif ok_n == 0:
        lines.append("😿 请检查账号密码 / 网络 / 滑块识别")
    else:
        lines.append("💡 部分账号见日志")
    return title, "\n".join(lines)


def send_notifications(cfg: AppConfig, title: str, content: str) -> None:
    """按优先级推送：青龙统一通知 → Bark → PushPlus。"""
    if _ql_notify:
        try:
            log("📣 通知状态: 正在调用青龙面板统一通知发送推送 🚀")
            _ql_notify(title, content)
            return
        except Exception:
            pass

    bark = cfg.bark or {}
    if bark.get("url") or bark.get("key"):
        endpoint = bark["url"].rstrip("/") if bark.get("url") else f"{bark['server']}/{bark['key']}"
        payload: dict[str, Any] = {
            "title": title[:200],
            "body": content[:3500],
            "group": bark.get("group") or DEFAULT_BARK_GROUP,
        }
        for opt in ("sound", "icon", "level"):
            if bark.get(opt):
                payload[opt] = bark[opt]
        try:
            r = requests.post(endpoint, json=payload, timeout=15)
            if r.status_code >= 400:  # 部分自建 Bark 服务不认 json body，退回 GET 形式
                requests.get(
                    f"{endpoint}/{quote(title[:100], safe='')}/{quote(content[:500], safe='')}",
                    timeout=15,
                )
            log("📣 通知状态: 已发送至 iOS Bark 推送 📱")
        except Exception as e:
            log(f"⚠️ Bark 发送失败: {e}")

    pp = cfg.pushplus or {}
    if pp.get("token"):
        try:
            requests.post(
                "https://www.pushplus.plus/send",
                json={
                    "token": pp["token"],
                    "title": title,
                    "content": content.replace("\n", "<br>"),
                    "template": "html",
                    "topic": pp.get("topic") or "",
                },
                timeout=15,
            )
            log("📣 通知状态: 已发送至 PushPlus 微信推送 💬")
        except Exception as e:
            log(f"⚠️ PushPlus 发送失败: {e}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="今平湖阅读红包助手（本地 config.yaml 或青龙环境变量）"
    )
    parser.add_argument("-c", "--config", default="", help="本地 config.yaml 路径（默认 ./config.yaml）")
    parser.add_argument("--dry-run", "--dry", dest="dry", action="store_true", help="只读核验，不做写操作")
    parser.add_argument("--check", "--check-only", dest="check", action="store_true",
                        help="仅登录并查询账号 / 微信绑定 / 抽奖次数")
    parser.add_argument("--debug", action="store_true", help="输出详细响应日志")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    global IS_DEBUG
    args = parse_args(argv)
    IS_DEBUG = args.debug or _env_flag("JPH_DEBUG")
    dry = args.dry or _env_flag("JPH_DRY") or _env_flag("DRY_RUN")
    check = args.check

    log("🚀 今平湖 · 阅读红包助手 daily.py")
    log(f"🖥️ 运行环境: {'青龙' if running_on_qinglong() else '本地'}")

    try:
        cfg = resolve_config(args)
    except Exception as e:
        log(f"❌ {e}")
        log("   青龙：JPH=手机号#密码[&手机号#密码]")
        log("   本地：cp config.example.yaml config.yaml 后填写")
        return 2

    log(f"📄 配置来源: {cfg.source or '?'}")
    log(f"🎛️ 模式: {'只读' if dry else ('核验' if check else '完整')}"
        f" | 抽奖={'开' if cfg.do_lottery else '关'}"
        f" | OCR={cfg.ocr}"
        f" | 线程={cfg.threads}")
    if cfg.bark.get("url") or cfg.bark.get("key"):
        log("📣 Bark 已配置")
    else:
        log("📣 未配置 BARK_URL/BARK_KEY（本地可写在 config.yaml 的 bark 段）")

    if len(cfg.accounts) > 1 and cfg.lottery_phone:
        log("⚠️ 多账号模式已忽略全局 JPH_LOTTERY_PHONE（会把同一手机号灌给所有账号）；"
            "每个账号默认只用自己登录号，如需单独指定请用 JPH_LOTTERY_PHONE_MAP")

    state_dir = resolve_state_dir(cfg)
    state_dir.mkdir(parents=True, exist_ok=True)
    token_path = state_dir / "access_token.json"
    log(f"💾 状态目录: {state_dir}")

    accounts = cfg.accounts
    threads = cfg.threads if cfg.threads > 0 else len(accounts)
    threads = max(1, min(threads, len(accounts)))
    all_phones = [a.phone for a in accounts]
    log(f"📋 共 {len(accounts)} 个账号，线程 {threads}")

    results: list[dict[str, Any]] = []

    def work(i: int, acc: Account) -> dict[str, Any]:
        return run_account(i, acc, cfg, all_phones, token_path, dry, check)

    if threads == 1:
        for i, acc in enumerate(accounts, 1):
            if i > 1 and cfg.inter_account_delay > 0:
                time.sleep(cfg.inter_account_delay)
            results.append(work(i, acc))
    else:
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = [pool.submit(work, i, acc) for i, acc in enumerate(accounts, 1)]
            for future in as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda r: r.get("phone", ""))
    title, body = build_summary(results, "只读" if dry else ("核验" if check else "任务"))
    log("")
    log("=" * 60)
    log(body)
    log("=" * 60)

    if not dry:
        send_notifications(cfg, title, body)
    else:
        log("📣 只读模式，跳过推送")
    log("🏁 全部完成")
    return 1 if any(not r.get("ok") for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("\n⚠️ 中断")
        sys.exit(130)
