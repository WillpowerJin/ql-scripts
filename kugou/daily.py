#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
酷狗概念版金币任务（多账号）

cron: 5 0 * * *
new Env('酷狗概念版任务');

基于社区脚本「酷狗概念版跑25W金币多账号 v3.5」重写为仓库统一风格：
  签到 + 全量任务满链翻倍 + 1105 定时领取 + 翻牌活动 + 福利中心 + 听歌上报。

青龙环境变量（账号，必填）：
  KUGOU_ACCOUNTS  JSON 数组（推荐，name 即备注）
    [{"name":"主号","token":"...","userid":"...","mid":"...","dfid":"...","devid":"..."}]
  或兼容原脚本变量：KGGNB / kggnb / KGGNB_TASK / kugou_token / kwtx / KWTX
    多账号用 & 或换行分隔
    标准：备注#token#userid#mid#dfid#devid[#t2][#uni_verify_str]
    简写：备注#token#userid       （缺少 mid/dfid 时按 token 自动推导）
    键值：token=xxx;userid=yyy;mid=zzz;dfid=www;devid=vvv

模式（命令行参数）：
  （默认）   全量任务 + 1105 循环 + 翻牌（可能持续数小时）
  --once     只做一轮任务，跳过 1105 循环（较快）
  --info     仅查询账号、金币、签到和任务进度
  --flip     仅执行翻牌活动
  --welfare  仅执行福利中心
  --assist   <share_code> 翻牌助力
  --test     仅做签名自检
  --serial   多账号串行（默认并发）

可选环境变量：
  KUGOU_MAX_WORKERS        并发账号数上限（默认 10）
  KUGOU_SERIAL=1           强制串行
  KUGOU_LOOP_ROUNDS        1105 最大轮数（默认 40）
  KUGOU_LOOP_MAX_WAIT      1105 单次最大等待秒（默认 1200）
  KUGOU_DOUBLE_MAX         翻倍链上限（默认 12）
  KUGOU_DELAY              任务间隔，格式 "1.2-2.5"
  KUGOU_TIMEOUT            请求超时秒（默认 25）
  KUGOU_RETRY              请求重试次数（默认 1）
  KUGOU_LOCK=0             关闭防并发锁

通知（与仓库其它脚本共用）：
  BARK_URL 或 BARK_KEY [+ BARK_SERVER]
  BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL
  PUSHPLUS_TOKEN / PUSHPLUS_TOPIC
  青龙环境自动调用 notify.py

依赖：requests（本地 yaml 再装 PyYAML）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import string
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

try:
    import requests
except ImportError:
    print("❌ 缺少依赖：pip install requests")
    print("   青龙：【依赖管理】->【Python3】安装 requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# 常量（来自原脚本）
# ---------------------------------------------------------------------------

APP_NAME = "酷狗概念版"
VERSION = "3.6.0"

BASE = "https://gateway.kugou.com"
UA = (
    "Mozilla/5.0 (Linux; Android 14; 2203121C Build/UKQ1.231003.002; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/118.0.0.0 "
    "Mobile Safari/537.36 KugouYouth"
)

SALT = "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"
TICKET_SALT = "t6us8yan^mEtWj7P"
YOUTH_APPID = "3114"
YOUTH_CLIENTVER = "12520"
YOUTH_CHANNEL = "12520"
YOUTH_ACT_ID = 352
CONCEPTS_ACT_SIGN = "holiday_lucky_card"

DEFAULT_DELAY_MIN = 1.2
DEFAULT_DELAY_MAX = 2.5
DEFAULT_TIMEOUT = 25
DEFAULT_RETRY = 1
DEFAULT_DOUBLE_MAX = 12
DEFAULT_DOUBLE_DELAY = 1.5
DEFAULT_LOOP_ROUNDS = 40
DEFAULT_LOOP_MAX_WAIT = 1200
DEFAULT_MAX_WORKERS = 10
DEFAULT_LOCK_TTL = 3600

DEFAULT_SKIP_TASKIDS = [2124]
DEFAULT_TASK_LOOP_CAPS = {9: 60, 45: 15, 2022: 4, 1105: 35, 1107: 10}

DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "酷狗概念版"

MISSING_CONFIG_HINT = (
    "❌ 未找到有效的酷狗账号配置。\n"
    "📝 青龙：设置 KUGOU_ACCOUNTS（JSON），或 KGGNB=备注#token#userid#mid#dfid#devid\n"
    "📝 本地：cp config.example.yaml config.yaml 并填写 token / userid"
)

RE_MID = re.compile(r"^[0-9A-Za-z]{36,64}$")

# 福利中心只读接口
WELFARE_READ = [
    ("/v1/invite/share_act_info", None, "GET"),
    ("/v1/invite/award_tips", {"show_box": 1}, "GET"),
    ("/v2/invite/award_list", {"last_id": 0}, "GET"),
    ("/v1/invite/get_invitation_code", None, "GET"),
    ("/v1/invite/get_user_invite_list", {"last_id": 0}, "GET"),
    ("/v1/invite/rank_list", {"is_prev": 0}, "GET"),
    ("/v5/user/get_account_stat", {"supper_sign": 0}, "GET"),
    ("/v1/activity/get_listen_song_task", {"source_id": 18, "get_stats": 1}, "GET"),
    ("/v1/ad/get_ad_vip_time", None, "GET"),
    ("/v1/free_package/get_vip_task", None, "GET"),
    ("/v1/popup/check_popup", None, "GET"),
]
ID_KEYS = {"box_id", "bsid", "period_id", "record_id", "invitation_code", "free_state", "is_new_user", "award_id"}

IS_DEBUG = False
_log_lock = threading.Lock()

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
# 日志
# ---------------------------------------------------------------------------

def log(msg: str = "", tag: str = "") -> None:
    prefix = f"[{tag}] " if tag else ""
    with _log_lock:
        print(f"{prefix}{msg}", flush=True)


def debug(msg: str, tag: str = "") -> None:
    if IS_DEBUG:
        log(f"🔍 {msg}", tag)


# ---------------------------------------------------------------------------
# 账号与配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    remark: str
    token: str
    userid: str
    mid: str = ""
    dfid: str = ""
    devid: str = ""
    t2: str = ""
    uni_verify_str: str = ""
    appid: str = YOUTH_APPID
    clientver: str = YOUTH_CLIENTVER
    channel: str = YOUTH_CHANNEL

    def normalize(self) -> "Account":
        self.remark = (self.remark or self.userid or "").strip()
        self.token = self.token.strip()
        self.userid = self.userid.strip()
        self.mid = self.mid.strip() or derive_mid(self.token)
        self.dfid = self.dfid.strip() or derive_dfid(self.token)
        self.devid = self.devid.strip()
        self.t2 = self.t2.strip()
        self.uni_verify_str = self.uni_verify_str.strip()
        self.appid = (self.appid or YOUTH_APPID).strip()
        self.clientver = (self.clientver or YOUTH_CLIENTVER).strip()
        self.channel = (self.channel or YOUTH_CHANNEL).strip()
        return self

    def identity(self) -> tuple[str, str]:
        return self.userid, self.token


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
    skip_taskids: list[int] = field(default_factory=lambda: list(DEFAULT_SKIP_TASKIDS))
    task_loop_caps: dict[int, int] = field(default_factory=lambda: dict(DEFAULT_TASK_LOOP_CAPS))
    delay_min: float = DEFAULT_DELAY_MIN
    delay_max: float = DEFAULT_DELAY_MAX
    timeout: int = DEFAULT_TIMEOUT
    retry: int = DEFAULT_RETRY
    double_max: int = DEFAULT_DOUBLE_MAX
    double_delay: float = DEFAULT_DOUBLE_DELAY
    loop_rounds: int = DEFAULT_LOOP_ROUNDS
    loop_max_wait: int = DEFAULT_LOOP_MAX_WAIT
    concurrent: bool = True
    max_workers: int = DEFAULT_MAX_WORKERS
    lock: bool = True
    lock_file: str = os.path.join(tempfile.gettempdir(), "kugou_task_v3.lock")
    lock_ttl: int = DEFAULT_LOCK_TTL
    send_ticket: bool = True
    send_clienttime_ms: bool = True
    send_user_label: bool = True
    user_agent: str = UA


def derive_mid(token: str) -> str:
    value = int(hashlib.md5(("kg-mid:" + str(token)).encode()).hexdigest(), 16)
    return str(value % (10 ** 39)).zfill(39)


def derive_dfid(token: str) -> str:
    digest = hashlib.sha256(("kg-dfid:" + str(token)).encode()).hexdigest()
    pool = string.ascii_letters + string.digits
    return "".join(pool[int(digest[i * 2 : i * 2 + 2], 16) % len(pool)] for i in range(23))


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


def _env_int(name: str, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() not in ("0", "false", "no", "off")


def _parse_delay(value: str, default: tuple[float, float]) -> tuple[float, float]:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[-,~ ]\s*(\d+(?:\.\d+)?)\s*", value or "")
    if not match:
        return default
    low, high = float(match.group(1)), float(match.group(2))
    return (low, high) if low <= high else (high, low)


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


def _account_from_kv(line: str) -> Optional[Account]:
    kv: dict[str, str] = {}
    for item in re.split(r"[;,]+", line):
        if "=" in item:
            key, value = item.split("=", 1)
            kv[key.strip().lower()] = value.strip()
    token, userid = kv.get("token", ""), kv.get("userid", "")
    if not token or not userid:
        return None
    remark = kv.get("remark") or kv.get("nickname") or f"账号_{userid}"
    return Account(
        remark=remark,
        token=token,
        userid=userid,
        mid=kv.get("mid", ""),
        dfid=kv.get("dfid", ""),
        devid=kv.get("devid", ""),
        t2=kv.get("t2", ""),
        uni_verify_str=kv.get("uni_verify_str", ""),
        appid=kv.get("appid", YOUTH_APPID),
        clientver=kv.get("clientver", YOUTH_CLIENTVER),
        channel=kv.get("channel", YOUTH_CHANNEL),
    ).normalize()


def _account_from_hash_line(line: str) -> Optional[Account]:
    parts = [x.strip() for x in line.split("#")]
    parts = [x for x in parts if x]
    if len(parts) < 2:
        return None

    # 兼容缺少备注、直接 token#userid 的写法
    if (
        len(parts[0]) == 32
        and all(c in string.hexdigits for c in parts[0])
        and len(parts) > 1
        and parts[1].isdigit()
    ):
        parts = [f"账号_{parts[1]}"] + parts

    remark, token = parts[0], parts[1]
    account = Account(remark=remark, token=token, userid="")
    rest = parts[2:]
    if len(rest) >= 2 and RE_MID.match(rest[1]):
        account.userid = rest[0]
        account.mid = rest[1]
        account.dfid = rest[2] if len(rest) > 2 else ""
        account.devid = rest[3] if len(rest) > 3 else ""
        account.t2 = rest[4] if len(rest) > 4 else ""
        account.uni_verify_str = rest[5] if len(rest) > 5 else ""
    else:
        account.userid = rest[0] if rest else ""
        if len(rest) > 1 and RE_MID.match(rest[1]):
            account.mid = rest[1]
            account.dfid = rest[2] if len(rest) > 2 else ""
            account.devid = rest[3] if len(rest) > 3 else ""

    if not account.token or not account.userid:
        return None
    if account.token in ("填写", "xxx") or account.userid in ("填写", "xxx"):
        return None
    return account.normalize()


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("KUGOU_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"KUGOU_ACCOUNTS[{i}] 必须是对象")
        token = str(item.get("token") or "").strip()
        userid = str(item.get("userid") or item.get("user_id") or "").strip()
        if not token or not userid:
            continue
        remark = str(
            item.get("name") or item.get("remark") or item.get("note") or f"账号{i + 1}"
        ).strip()
        accounts.append(
            Account(
                remark=remark,
                token=token,
                userid=userid,
                mid=str(item.get("mid") or ""),
                dfid=str(item.get("dfid") or ""),
                devid=str(item.get("devid") or ""),
                t2=str(item.get("t2") or ""),
                uni_verify_str=str(item.get("uni_verify_str") or ""),
                appid=str(item.get("appid") or YOUTH_APPID),
                clientver=str(item.get("clientver") or YOUTH_CLIENTVER),
                channel=str(item.get("channel") or YOUTH_CHANNEL),
            ).normalize()
        )
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    raw_json = _env("KUGOU_ACCOUNTS")
    if raw_json:
        try:
            accounts = _parse_accounts_json(raw_json)
            if accounts:
                return accounts
        except Exception as exc:
            log(f"⚠️ KUGOU_ACCOUNTS 解析失败，回退到 KGGNB：{exc}")

    raw = ""
    for key in ("KGGNB", "kggnb", "KGGNB_TASK", "kugou_token", "kwtx", "KWTX"):
        value = _env(key)
        if value:
            raw = value
            break
    raw = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r", "\n")

    accounts: list[Account] = []
    for part in re.split(r"[&\n]+", raw):
        line = part.strip()
        if not line or line.startswith("#"):
            continue
        if "#" not in line and ("token=" in line or "userid=" in line):
            account = _account_from_kv(line)
        else:
            account = _account_from_hash_line(line)
        if account:
            accounts.append(account)
    return accounts


def _merge_accounts(*groups: list[Account]) -> list[Account]:
    seen: set[tuple[str, str]] = set()
    merged: list[Account] = []
    for group in groups:
        for account in group:
            ident = account.identity()
            if ident in seen:
                continue
            seen.add(ident)
            merged.append(account)
    return merged


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
        token = str(item.get("token") or "").strip()
        userid = str(item.get("userid") or "").strip()
        if not token or not userid:
            continue
        accounts.append(
            Account(
                remark=str(item.get("name") or item.get("remark") or f"账号{i}"),
                token=token,
                userid=userid,
                mid=str(item.get("mid") or ""),
                dfid=str(item.get("dfid") or ""),
                devid=str(item.get("devid") or ""),
                t2=str(item.get("t2") or ""),
                uni_verify_str=str(item.get("uni_verify_str") or ""),
                appid=str(item.get("appid") or YOUTH_APPID),
                clientver=str(item.get("clientver") or YOUTH_CLIENTVER),
                channel=str(item.get("channel") or YOUTH_CHANNEL),
            ).normalize()
        )

    delay_text = str(raw.get("delay") or "")
    if delay_text:
        delay_min, delay_max = _parse_delay(
            delay_text, (DEFAULT_DELAY_MIN, DEFAULT_DELAY_MAX)
        )
    else:
        delay_min = float(raw.get("delay_min") or DEFAULT_DELAY_MIN)
        delay_max = float(raw.get("delay_max") or DEFAULT_DELAY_MAX)
        if delay_min > delay_max:
            delay_min, delay_max = delay_max, delay_min

    caps_raw = raw.get("task_loop_caps") or {}
    caps = dict(DEFAULT_TASK_LOOP_CAPS)
    if isinstance(caps_raw, dict):
        caps.update({int(k): int(v) for k, v in caps_raw.items()})

    skip_raw = raw.get("skip_taskids")
    skip_ids = [int(x) for x in skip_raw] if isinstance(skip_raw, list) else list(DEFAULT_SKIP_TASKIDS)

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
        bark_server=(
            env_notify.bark_server
            if env_notify.bark_enabled()
            else str(bark.get("server") or DEFAULT_BARK_SERVER)
        ).rstrip("/"),
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
        skip_taskids=skip_ids,
        task_loop_caps=caps,
        delay_min=delay_min,
        delay_max=delay_max,
        timeout=int(raw.get("timeout") or DEFAULT_TIMEOUT),
        retry=int(raw.get("retry") if raw.get("retry") is not None else DEFAULT_RETRY),
        double_max=int(raw.get("double_max") or DEFAULT_DOUBLE_MAX),
        double_delay=float(raw.get("double_delay") or DEFAULT_DOUBLE_DELAY),
        loop_rounds=int(raw.get("loop_rounds") or DEFAULT_LOOP_ROUNDS),
        loop_max_wait=int(raw.get("loop_max_wait") or DEFAULT_LOOP_MAX_WAIT),
        concurrent=bool(raw.get("concurrent", True)),
        max_workers=int(raw.get("max_workers") or DEFAULT_MAX_WORKERS),
        lock=bool(raw.get("lock", True)),
        lock_file=str(raw.get("lock_file") or os.path.join(tempfile.gettempdir(), "kugou_task_v3.lock")),
        lock_ttl=int(raw.get("lock_ttl") or DEFAULT_LOCK_TTL),
        send_ticket=bool(raw.get("send_ticket", True)),
        send_clienttime_ms=bool(raw.get("send_clienttime_ms", True)),
        send_user_label=bool(raw.get("send_user_label", True)),
        user_agent=str(raw.get("user_agent") or UA),
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

    if _env("KGGNB_SERIAL") in ("1", "true", "True"):
        cfg.concurrent = False
    if _env("KUGOU_SERIAL") in ("1", "true", "True"):
        cfg.concurrent = False
    cfg.max_workers = _env_int("KUGOU_MAX_WORKERS", cfg.max_workers, 1, 32)
    cfg.loop_rounds = _env_int("KUGOU_LOOP_ROUNDS", cfg.loop_rounds, 1, 200)
    cfg.loop_max_wait = _env_int("KUGOU_LOOP_MAX_WAIT", cfg.loop_max_wait, 0, 7200)
    cfg.double_max = _env_int("KUGOU_DOUBLE_MAX", cfg.double_max, 0, 50)
    if _env("KUGOU_DELAY"):
        cfg.delay_min, cfg.delay_max = _parse_delay(
            _env("KUGOU_DELAY"), (cfg.delay_min, cfg.delay_max)
        )
    cfg.timeout = _env_int("KUGOU_TIMEOUT", cfg.timeout, 5, 120)
    cfg.retry = _env_int("KUGOU_RETRY", cfg.retry, 0, 5)
    cfg.lock = _env_bool("KUGOU_LOCK", cfg.lock)
    cfg.lock_file = _env("KUGOU_LOCK_FILE") or cfg.lock_file
    return cfg


# ---------------------------------------------------------------------------
# 签名
# ---------------------------------------------------------------------------

def make_sign(params: dict[str, Any], raw_body: Optional[str] = None) -> str:
    joined = "".join(f"{key}={params[key]}" for key in sorted(params.keys()))
    if raw_body:
        joined += raw_body
    return hashlib.md5((SALT + joined + SALT).encode("utf-8")).hexdigest()


def make_ticket(userid: str, taskid: Any) -> str:
    raw = f"{userid}{int(taskid)}{int(time.time())}{TICKET_SALT}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def self_test() -> bool:
    params = {
        "appid": "3116", "clientver": "11571",
        "dfid": "1J9A8J1ZDCDy4OPWYB4Yj6c2",
        "mid": "117031343721896449724314978024697721034",
        "srcappid": "2919", "token": "T", "userid": "2247744797", "uuid": "-",
    }
    got = make_sign(params)
    sample = (
        "appid=3116clientver=11571dfid=1J9A8J1ZDCDy4OPWYB4Yj6c2"
        "mid=117031343721896449724314978024697721034srcappid=2919"
        "token=Tuserid=2247744797uuid=-"
    )
    expected = hashlib.md5((SALT + sample + SALT).encode()).hexdigest()
    if got != expected:
        log("❌ 签名自检失败")
        return False
    log(f"✅ 签名自检通过: {got}")
    return True


# ---------------------------------------------------------------------------
# 酷狗客户端
# ---------------------------------------------------------------------------

def resp_ok(resp: Any) -> bool:
    return int((resp or {}).get("status") or 0) == 1


def resp_err(resp: Any) -> str:
    resp = resp or {}
    return str(
        resp.get("error")
        or resp.get("error_msg")
        or resp.get("errmsg")
        or f"errcode={resp.get('errcode')} error_code={resp.get('error_code')}"
    )


def find_values(obj: Any, names: set[str], out: Optional[dict[str, list[Any]]] = None, depth: int = 0) -> dict[str, list[Any]]:
    if out is None:
        out = {}
    if depth > 8:
        return out
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in names and not isinstance(value, (dict, list)):
                out.setdefault(key, [])
                if value not in out[key]:
                    out[key].append(value)
            find_values(value, names, out, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            find_values(item, names, out, depth + 1)
    return out


class KugouClient:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.session = requests.Session()
        self.request_count = 0

    def log(self, msg: str) -> None:
        log(msg, self.account.remark)

    def sleep_rand(self) -> None:
        time.sleep(random.uniform(self.cfg.delay_min, self.cfg.delay_max))

    def _request(self, url: str, raw: Optional[str], method: str) -> dict[str, Any]:
        headers = {
            "User-Agent": self.cfg.user_agent,
            "Content-Type": "application/json; charset=utf-8",
            "KG-CLIENTTIMEMS": str(int(time.time() * 1000)),
        }
        if self.account.devid:
            headers["KG-DEVID"] = self.account.devid

        last_error = ""
        for attempt in range(self.cfg.retry + 1):
            try:
                self.request_count += 1
                resp = self.session.request(
                    method,
                    url,
                    data=raw.encode("utf-8") if raw else None,
                    headers=headers,
                    timeout=self.cfg.timeout,
                )
                try:
                    data = resp.json()
                except ValueError:
                    raise RuntimeError(f"HTTP {resp.status_code}: {(resp.text or '')[:200]}")
                return data if isinstance(data, dict) else {}
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                debug(f"请求异常 {method} {url.split('?')[0]}: {exc}", self.account.remark)
                if attempt < self.cfg.retry:
                    time.sleep(1.5 + attempt * 1.5)
        raise RuntimeError(f"{method} {url.split('?')[0]} 失败 -> {last_error}")

    def make_ticket(self, taskid: Any) -> str:
        return make_ticket(self.account.userid, taskid)

    def api(self, path: str, params: Optional[dict[str, Any]] = None, data: Optional[dict[str, Any]] = None, method: str = "GET") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "appid": self.account.appid,
            "clientver": self.account.clientver,
            "clienttime": str(int(time.time() * 1000)),
            "mid": self.account.mid,
            "uuid": self.account.mid or "-",
            "dfid": self.account.dfid,
            "srcappid": "2919",
            "userid": self.account.userid,
            "token": self.account.token,
            "channel": self.account.channel,
        }
        if params:
            payload.update({key: str(value) for key, value in params.items()})
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data is not None else None
        payload["signature"] = make_sign(payload, raw)
        url = f"{BASE}/yutc{path}?{urlencode(payload)}"
        return self._request(url, raw, method)

    def youth_api(self, path: str, params: Optional[dict[str, Any]] = None, data: Optional[dict[str, Any]] = None, method: str = "GET") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "appid": self.account.appid,
            "clientver": self.account.clientver,
            "clienttime": str(int(time.time() * 1000)),
            "mid": self.account.mid or "-",
            "uuid": self.account.mid or "-",
            "dfid": self.account.dfid or "-",
            "srcappid": "2919",
            "userid": self.account.userid,
            "token": self.account.token,
            "channel": self.account.channel,
        }
        if params:
            payload.update({key: str(value) for key, value in params.items() if value is not None})
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data is not None else None
        payload["signature"] = make_sign(payload, raw)
        url = f"{BASE}/youth{path}?{urlencode(payload)}"
        return self._request(url, raw, method)

    def concepts_api(self, path: str, params: Optional[dict[str, Any]] = None, data: Optional[dict[str, Any]] = None, method: str = "GET") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "appid": self.account.appid,
            "clientver": self.account.clientver,
            "clienttime": str(int(time.time() * 1000)),
            "mid": self.account.mid or "-",
            "uuid": self.account.mid or "-",
            "dfid": self.account.dfid or "-",
            "srcappid": "2919",
            "userid": self.account.userid,
            "token": self.account.token,
            "channel": self.account.channel,
        }
        if params:
            payload.update({key: str(value) for key, value in params.items() if value is not None})
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data is not None else None
        payload["signature"] = make_sign(payload, raw)
        url = f"{BASE}/concepts{path}?{urlencode(payload)}"
        return self._request(url, raw, method)

    # --- 基础接口 ---

    def get_infos(self) -> dict[str, Any]:
        return self.api(
            "/youth/v1/system/infos",
            params={
                "from": "client",
                "with_top_cards": 1,
                "spec": 15,
                "channel": self.account.channel,
                "source": 18,
                "appver": 1000,
                "retain_task_count": 0,
                "pagename": "netearn",
            },
        )

    def get_account(self) -> dict[str, Any]:
        resp = self.api("/youth/v1/user/info")
        if not resp_ok(resp) or not isinstance(resp.get("data"), dict):
            raise RuntimeError(f"user/info 异常: {resp_err(resp)}")
        return resp["data"]

    def get_sign_state(self) -> dict[str, Any]:
        resp = self.api("/youth/v1/task/sign_state")
        if not resp_ok(resp) or not isinstance(resp.get("data"), dict):
            raise RuntimeError(f"sign_state 异常: {resp_err(resp)}")
        return resp["data"]

    def get_task_info(self, taskid: Any) -> dict[str, Any]:
        return self.api(
            "/youth/v1/task/info",
            params={"taskid": taskid, "source": "18", "pagename": "taskcenter", "appver": "1000"},
        )

    def do_signon(self) -> tuple[bool, str]:
        state = self.get_sign_state()
        today = next((item for item in state.get("list", []) if item.get("today") == 1), None)
        if not today:
            return False, "未找到今日签到项"
        if today.get("state") != 0:
            return False, f"今日已签到 (state={today.get('state')})"
        code = today.get("code")
        try:
            self.api("/youth/v1/task/check_risk", params={"taskid": 100001})
        except Exception:
            pass
        self.sleep_rand()
        resp = self.api(
            "/youth/v1/task/signon",
            params={"taskid": "100001", "from": "client"},
            data={"code": code, "source": 18},
            method="POST",
        )
        if resp.get("status") == 1:
            return True, f"签到成功 (code={code})"
        return False, f"签到失败: {resp_err(resp)}"

    # --- 任务满链提交 ---

    def submit_task_full(self, tid: Any, show_coins: Any) -> tuple[int, dict[str, Any], str]:
        """提交任务并吃完整个翻倍链，返回 (总金币, 主响应, 错误说明)。"""
        body: dict[str, Any] = {
            "appver": 1000,
            "taskid": tid,
            "show_coins": int(show_coins or 0),
            "source": 18,
        }
        if self.cfg.send_clienttime_ms:
            body["clienttime_ms"] = int(time.time() * 1000)
        if self.cfg.send_user_label:
            body["user_label"] = {}
        if self.account.t2:
            body["t2"] = self.account.t2
        if self.account.uni_verify_str:
            body["uni_verify_str"] = self.account.uni_verify_str
        if self.cfg.send_ticket:
            body["ticket"] = self.make_ticket(tid)

        try:
            resp = self.api("/youth/v1/task/submit", data=body, method="POST")
        except Exception as exc:
            return 0, {}, str(exc)

        if resp.get("status") != 1:
            return 0, resp, resp_err(resp)

        data = resp.get("data") or {}
        total = int((data.get("awards") or {}).get("coins") or 0)
        if total <= 0 and not data.get("double_code"):
            return 0, resp, ""

        double_code = data.get("double_code")
        round_no = 0
        while double_code and round_no < self.cfg.double_max:
            round_no += 1
            time.sleep(self.cfg.double_delay)
            try:
                double_body = dict(body)
                double_body["double_code"] = double_code
                double_body["double_award_type"] = 2
                double_body["use_uni_award"] = 1
                double_body["clienttime_ms"] = int(time.time() * 1000)
                double_body["ticket"] = self.make_ticket(tid)
                double_resp = self.api("/youth/v1/task/submit", data=double_body, method="POST")
            except Exception as exc:
                self.log(f"      ! 翻倍 #{round_no} 异常: {exc}")
                break
            if double_resp.get("status") != 1:
                break
            double_data = double_resp.get("data") or {}
            coins = int((double_data.get("awards") or {}).get("coins") or 0)
            if coins <= 0:
                break
            total += coins
            double_code = double_data.get("double_code")
        return total, resp, ""

    # --- 收割 ---

    def collect_tasks(self) -> int:
        infos = self.get_infos()
        if infos.get("status") != 1:
            raise RuntimeError(f"system/infos 异常: {resp_err(infos)}")
        tasks = (infos.get("data") or {}).get("tasks") or []

        self.log("  ── 每日签到 ──")
        try:
            ok, message = self.do_signon()
            self.log(("    ✓ " if ok else "    · ") + message)
        except Exception as exc:
            self.log(f"    ! 签到异常: {exc}")

        self.log("  ── 扫描可领任务 ──")
        todo: list[tuple[Any, str, int, int]] = []
        for task in tasks:
            profile = task.get("profile") or {}
            state = task.get("state") or {}
            tid = profile.get("taskid")
            if tid in self.cfg.skip_taskids or tid == 1:
                continue
            if not profile.get("open", 1):
                continue
            done = int(state.get("done_count") or 0)
            cap = int(state.get("max_done_count") or profile.get("max_done_count") or 0)
            if cap and done >= cap:
                continue
            if tid == 1105:
                continue
            if tid == 1107:
                chances = (state.get("lottery") or {}).get("chances", 0)
                if not chances or int(chances) <= 0:
                    continue
            show = int(profile.get("show_coins") or profile.get("award_coins") or 0)
            if tid == 9:
                show = 200
            elif tid == 2022:
                show = 100
            elif tid == 45:
                show = 200
            rest = (cap - done) if cap else 1
            todo.append((tid, profile.get("name") or "", show, rest))

        if not todo:
            self.log("    · 暂无可领任务")
            return 0

        total = 0
        for tid, name, show_coins, rest in todo:
            limit = self.cfg.task_loop_caps.get(tid, rest)
            rounds = min(rest, limit) if limit else rest
            got_task = 0
            for index in range(rounds):
                coins, _resp, err = self.submit_task_full(tid, show_coins)
                if coins <= 0:
                    if index == 0:
                        self.log(f"    · [{tid}]{name}: {err or '无奖励'}")
                    break
                got_task += coins
                self.log(f"    ✓ [{tid}]{name} #{index + 1} +{coins}")
                self.sleep_rand()
            total += got_task
            if got_task:
                self.log(f"    Σ [{tid}]{name} 共 +{got_task}")

        self.log(f"  ── 本轮任务累计 +{total} 金币 ──")
        return total

    def loop_1105(self, max_rounds: Optional[int] = None, max_wait: Optional[int] = None) -> int:
        max_rounds = int(max_rounds or self.cfg.loop_rounds)
        max_wait = int(max_wait if max_wait is not None else self.cfg.loop_max_wait)
        start: Optional[int]
        try:
            start = int((self.get_account().get("account") or {}).get("balance_coins") or 0)
        except Exception:
            start = None

        self.log(f"  ── 1105 循环（最多 {max_rounds} 轮）──")
        got_total = 0
        for index in range(1, max_rounds + 1):
            try:
                resp = self.get_task_info(1105)
            except Exception as exc:
                self.log(f"    ! 第{index}轮查询失败: {exc}")
                break
            data = resp.get("data") or {}
            state = data.get("state") or {}
            profile = data.get("profile") or {}
            done = int(state.get("done_count") or 0)
            cap = int(state.get("max_done_count") or profile.get("max_done_count") or 0)
            next_award = state.get("next_award_time")
            server_time = int(state.get("server_time") or time.time())
            show_coins = int(state.get("coins") or profile.get("award_coins") or 200)
            if cap and done >= cap:
                self.log(f"    · 1105 今日已满 {done}/{cap}，停止")
                break
            wait = (int(next_award) - server_time) if next_award else 0
            wait = max(0, wait)
            if wait > max_wait:
                self.log(f"    · 冷却剩 {wait}s 超上限，停止（done={done}/{cap}）")
                break
            if wait > 0:
                self.log(f"    · 等 {wait + 3}s 到点（done={done}/{cap}）")
                time.sleep(wait + 3)
            coins, resp, err = self.submit_task_full(1105, show_coins)
            if resp.get("status") != 1:
                self.log(f"    · 第{index}轮失败: {err}")
                time.sleep(5)
                continue
            got_total += coins
            self.log(f"    ✓ 第{index}轮 +{coins}（累计 +{got_total}）")
            self.sleep_rand()

        if start is not None:
            try:
                end = int((self.get_account().get("account") or {}).get("balance_coins") or 0)
                self.log(f"  ── 1105 结束：{start} -> {end}（净增 {end - start}）──")
            except Exception:
                pass
        return got_total

    # --- 翻牌 ---

    def holiday_flip(self) -> int:
        self.log("  ── 翻牌测运势（holiday_card）──")
        try:
            resp = self.concepts_api("/v1/holiday_card/info", params={"act_sign": CONCEPTS_ACT_SIGN})
        except Exception as exc:
            self.log(f"    ! 查询失败: {exc}")
            return 0
        if not resp_ok(resp):
            self.log(f"    · info 异常: {resp_err(resp)}")
            return 0
        data = resp.get("data") or {}
        state = data.get("state") or ""
        current = int(data.get("current_round") or 0)
        top = int(data.get("max_round") or 3)
        if state.startswith("FROZEN"):
            self.log(f"    · 已冻结（{state}），解冻 share_code={data.get('share_code')}")
            return 0

        got = 0
        for round_no in range(current + 1, top + 1):
            try:
                draw = self.concepts_api(
                    "/v1/holiday_card/draw",
                    data={"act_sign": CONCEPTS_ACT_SIGN, "round": round_no},
                    method="POST",
                )
            except Exception as exc:
                self.log(f"    ! 第{round_no}轮异常: {exc}")
                break
            if not resp_ok(draw):
                break
            round_data = draw.get("data") or {}
            seconds = int(round_data.get("reward_seconds") or 0)
            got += seconds
            self.log(f"    ✓ 第{round_no}轮: {round_data.get('prize_name')} +{seconds}s")
            if round_data.get("award_handler") == "no_award":
                try:
                    again = self.concepts_api("/v1/holiday_card/info", params={"act_sign": CONCEPTS_ACT_SIGN})
                    state2 = (again.get("data") or {}).get("state") or ""
                    if state2.startswith("FROZEN"):
                        self.log(f"    · 冻结于 {state2}，share_code={(again.get('data') or {}).get('share_code')}")
                        break
                except Exception:
                    pass
            time.sleep(2)
        self.log(f"  ── 翻牌结束 +{got} 秒 VIP（≈{got / 86400:.2f} 天）──")
        return got

    def holiday_assist(self, share_code: str) -> dict[str, Any]:
        self.log(f"  ── 翻牌助力 {share_code} ──")
        try:
            resp = self.concepts_api("/v1/holiday_card/assist", data={"share_code": share_code}, method="POST")
            self.log(f"    {'✓' if resp_ok(resp) else '·'} {'' if resp_ok(resp) else resp_err(resp)}")
            return resp
        except Exception as exc:
            self.log(f"    ! 异常: {exc}")
            return {}

    # --- 福利中心 ---

    def welfare_scan(self) -> dict[str, Any]:
        self.log("  ── 福利中心扫描 ──")
        results: dict[str, Any] = {}
        for path, params, method in WELFARE_READ:
            try:
                resp = self.youth_api(path, params=params, method=method)
                results[path] = resp
                if resp_ok(resp):
                    data = resp.get("data")
                    brief = (
                        ",".join(list(data.keys())[:8])
                        if isinstance(data, dict)
                        else f"list[{len(data)}]" if isinstance(data, list) else ""
                    )
                    self.log(f"    ✓ {path}  {brief}")
                else:
                    self.log(f"    · {path}  {resp_err(resp)}")
            except Exception as exc:
                self.log(f"    ! {path} 异常: {exc}")
            time.sleep(1)
        return results

    def welfare_claim(self, scan: dict[str, Any]) -> None:
        ids: dict[str, list[Any]] = {}
        for resp in scan.values():
            for key, values in find_values(resp, ID_KEYS).items():
                ids.setdefault(key, [])
                for value in values:
                    if value not in ids[key]:
                        ids[key].append(value)
        self.log(f"    发现 id: { {key: values[:3] for key, values in ids.items()} }")

        try:
            resp = self.youth_api("/v1/invite/task_report", method="POST")
            if resp_ok(resp):
                self.log(f"    ✓ task_report: {json.dumps(resp.get('data'), ensure_ascii=False)[:120]}")
            else:
                self.log(f"    · task_report: {resp_err(resp)}")
        except Exception as exc:
            self.log(f"    ! task_report 异常: {exc}")
        time.sleep(1)

        try:
            resp = self.youth_api("/v5/user/get_account_stat", params={"supper_sign": 0})
            if resp_ok(resp):
                for item in ((resp.get("data") or {}).get("signin_list") or []):
                    if int(item.get("receive_status") or 0) == 0 and item.get("period_id"):
                        reward = self.youth_api(
                            "/v1/activity/receive_new_user_vip",
                            data={"period_id": item["period_id"]},
                            method="POST",
                        )
                        ok = resp_ok(reward)
                        self.log(f"    {'✓' if ok else '·'} 新人VIP period={item['period_id']} {'' if ok else resp_err(reward)}")
                        time.sleep(1)
        except Exception as exc:
            self.log(f"    ! 新人VIP 异常: {exc}")

        for box_id in ids.get("box_id", [])[:10]:
            if not box_id:
                continue
            try:
                resp = self.youth_api("/v1/invite/open_blind_box", params={"box_id": box_id}, method="POST")
                self.log(f"    {'✓' if resp_ok(resp) else '·'} 盲盒 {box_id} {'' if resp_ok(resp) else resp_err(resp)}")
            except Exception as exc:
                self.log(f"    ! 盲盒异常: {exc}")
            time.sleep(1)

        for bsid in ids.get("bsid", [])[:10]:
            if not bsid:
                continue
            try:
                resp = self.youth_api(
                    "/v1/lottery/draw",
                    params={"act_id": YOUTH_ACT_ID},
                    data={"bsid": bsid},
                    method="POST",
                )
                self.log(f"    {'✓' if resp_ok(resp) else '·'} 抽奖 {bsid} {'' if resp_ok(resp) else resp_err(resp)}")
            except Exception as exc:
                self.log(f"    ! 抽奖异常: {exc}")
            time.sleep(1)

        try:
            resp = self.youth_api("/v1/invite/receive_rank_award", method="POST")
            if resp_ok(resp):
                self.log(f"    ✓ 排行榜奖励: {json.dumps(resp.get('data'), ensure_ascii=False)[:120]}")
            else:
                self.log(f"    · 排行榜奖励: {resp_err(resp)}")
        except Exception as exc:
            self.log(f"    ! 排行榜异常: {exc}")

    def welfare_flow(self) -> None:
        scan = self.welfare_scan()
        self.welfare_claim(scan)

    def listen_song_report(self) -> int:
        songs = [937093, 3146767, 116505, 6015206, 967613]
        ok = 0
        for song_id in songs[:2]:
            try:
                resp = self.youth_api("/v2/report/listen_song", data={"mixsongid": song_id}, method="POST")
                if resp_ok(resp):
                    ok += 1
            except Exception:
                pass
            time.sleep(1)
        if ok:
            self.log(f"    ✓ 听歌上报 {ok} 次")
        return ok

    # --- 信息 ---

    def show_info(self) -> None:
        account = self.get_account()
        data = account.get("account") or {}
        self.log(f"  余额 : {data.get('balance_coins')} 金币 (≈ {float(data.get('cash') or 0):.2f} 元)")
        self.log(f"  累计 : {data.get('total_coins')}")
        state = self.get_sign_state()
        today = next((item for item in state.get("list", []) if item.get("today") == 1), None)
        self.log(f"  签到 : {'今日已签' if today and today.get('state') != 0 else '今日未签'}")
        infos = self.get_infos()
        if not resp_ok(infos):
            raise RuntimeError(f"system/infos 异常: {resp_err(infos)}")
        server_ts = int((infos.get("data") or {}).get("ts") or time.time())
        self.log("  任务:")
        for task in (infos.get("data") or {}).get("tasks", []):
            profile, state = task.get("profile") or {}, task.get("state") or {}
            tid = profile.get("taskid")
            done = int(state.get("done_count") or 0)
            cap = int(state.get("max_done_count") or 0)
            flag = "可领" if (not cap or done < cap) else "已满"
            extra = ""
            if tid == 1105 and state.get("next_award_time"):
                left = int(state["next_award_time"]) - server_ts
                if left > 0:
                    extra = f"  冷却 {left // 60}m{left % 60}s"
            self.log(f"        [{str(tid):>6}] {str(profile.get('name', ''))[:14]:<14} {done}/{cap} {flag}{extra}")


# ---------------------------------------------------------------------------
# 单账号流程
# ---------------------------------------------------------------------------

class AccountRunner:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.client = KugouClient(account, cfg)

    def run(self, mode: str, bind_code: Optional[str] = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "remark": self.account.remark,
            "userid": self.account.userid,
            "ok": False,
            "before": 0,
            "after": 0,
            "gain": 0,
            "task_coins": 0,
            "loop_coins": 0,
            "flip_seconds": 0,
            "requests": 0,
            "err": "",
        }
        self.client.log(f"━━━ 账号 [{self.account.remark}] userid={self.account.userid} ━━━")

        if mode == "info":
            self.client.show_info()
            result["ok"] = True
            result["requests"] = self.client.request_count
            return result

        if mode == "flip":
            result["flip_seconds"] = self.client.holiday_flip()
            result["ok"] = True
            result["requests"] = self.client.request_count
            return result

        if mode == "assist":
            if not bind_code:
                result["err"] = "缺少 share_code 参数"
                self.client.log("  ! --assist 需要 share_code 参数")
                return result
            resp = self.client.holiday_assist(bind_code)
            result["ok"] = resp_ok(resp)
            if not result["ok"]:
                result["err"] = resp_err(resp)
            result["requests"] = self.client.request_count
            return result

        if mode == "welfare":
            self.client.welfare_flow()
            result["ok"] = True
            result["requests"] = self.client.request_count
            return result

        try:
            before = int((self.client.get_account().get("account") or {}).get("balance_coins") or 0)
            result["before"] = before
            self.client.log(f"  起始金币: {before}")
        except Exception as exc:
            result["err"] = f"读取余额失败(Token失效): {exc}"
            self.client.log(f"  ! {result['err']}")
            return result

        try:
            self.client.listen_song_report()
        except Exception as exc:
            self.client.log(f"  ! 听歌上报异常(忽略): {exc}")

        try:
            self.client.welfare_flow()
        except Exception as exc:
            self.client.log(f"  ! 福利中心异常(忽略): {exc}")

        try:
            result["task_coins"] = self.client.collect_tasks()
        except Exception as exc:
            self.client.log(f"  ! 任务流程异常: {exc}")

        if mode == "run":
            try:
                result["loop_coins"] = self.client.loop_1105()
            except Exception as exc:
                self.client.log(f"  ! 1105 循环异常: {exc}")

        try:
            result["flip_seconds"] = self.client.holiday_flip()
        except Exception as exc:
            self.client.log(f"  ! 翻牌异常: {exc}")

        try:
            after = int((self.client.get_account().get("account") or {}).get("balance_coins") or 0)
            result["after"] = after
            result["gain"] = max(0, after - before)
            result["ok"] = True
            self.client.log(
                f"  结束金币: {after}   本次净增 +{after - before}  ({(after - before) / 10000.0:.2f} 元)"
            )
        except Exception as exc:
            self.client.log(f"  ! 读取余额失败: {exc}")
            result["after"] = before + result["task_coins"] + result["loop_coins"]
            result["gain"] = result["after"] - before
            result["ok"] = True

        result["requests"] = self.client.request_count
        return result


# ---------------------------------------------------------------------------
# 防并发锁
# ---------------------------------------------------------------------------

def acquire_lock(cfg: AppConfig) -> bool:
    if not cfg.lock:
        return True
    path = cfg.lock_file
    try:
        if os.path.exists(path):
            age = time.time() - os.path.getmtime(path)
            try:
                pid = int(Path(path).read_text(encoding="utf-8").strip().split()[0])
            except Exception:
                pid = 0
            if pid and pid != os.getpid():
                try:
                    os.kill(pid, 0)
                    alive = True
                except ProcessLookupError:
                    alive = False
                except PermissionError:
                    alive = True
                if alive:
                    return False
            elif age < cfg.lock_ttl:
                return False
        Path(path).write_text(f"{os.getpid()} {int(time.time())}", encoding="utf-8")
        return True
    except OSError:
        return True


def release_lock(cfg: AppConfig) -> None:
    if not cfg.lock:
        return
    try:
        os.remove(cfg.lock_file)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 汇总与通知
# ---------------------------------------------------------------------------

def _fmt_gain(value: Any) -> str:
    try:
        coins = int(value or 0)
    except (TypeError, ValueError):
        coins = 0
    return f"+{coins} 金币 ≈ {coins / 10000.0:.2f} 元"


def format_summary(results: list[dict[str, Any]], mode: str) -> str:
    lines = [f"📅 {datetime.now().strftime('%m-%d %H:%M')}", ""]
    ok_count = sum(1 for item in results if item.get("ok"))
    total_gain = sum(int(item.get("gain") or 0) for item in results)

    lines.append(f"📊 账号：成功 {ok_count}/{len(results)}")
    if mode in ("run", "once"):
        lines.append(f"💰 合计：{_fmt_gain(total_gain)}")
    lines.append("")

    for i, result in enumerate(results):
        lines.append(f"{'✅' if result.get('ok') else '❌'} {result.get('remark') or result.get('userid') or f'账号{i + 1}'}")
        lines.append(f"   👤 userid：{result.get('userid') or '未知'}")
        if result.get("ok"):
            if mode in ("run", "once"):
                lines.append(
                    f"   💰 金币：{result.get('before')} → {result.get('after')} "
                    f"（{_fmt_gain(result.get('gain'))}）"
                )
                if result.get("task_coins"):
                    lines.append(f"   🌾 任务：+{result['task_coins']} 金币")
                if result.get("loop_coins"):
                    lines.append(f"   ⏰ 挂机：+{result['loop_coins']} 金币")
            if result.get("flip_seconds"):
                seconds = int(result["flip_seconds"])
                lines.append(f"   🎴 翻牌：+{seconds} 秒 VIP（≈{seconds / 86400:.2f} 天）")
            if mode == "info":
                lines.append("   ℹ️ 账号信息已输出到日志")
        else:
            lines.append(f"   ⚠️ {result.get('err') or '执行失败'}")
        if result.get("requests"):
            lines.append(f"   📡 请求数：{result['requests']}")
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


def format_notify_title(results: list[dict[str, Any]], mode: str) -> str:
    ok_count = sum(1 for item in results if item.get("ok"))
    total = len(results)
    if mode == "info":
        action = "信息查询"
    elif mode == "flip":
        action = "翻牌"
    elif mode == "welfare":
        action = "福利中心"
    elif mode == "assist":
        action = "助力"
    else:
        action = "金币任务"
    if total == 0:
        return f"{APP_NAME} {action}"
    if ok_count == total:
        return f"{APP_NAME} {action} ✅ {ok_count}/{total}"
    if ok_count == 0:
        return f"{APP_NAME} {action} ❌ 0/{total}"
    return f"{APP_NAME} {action} ⚠️ {ok_count}/{total}"


def send_notifications(cfg: AppConfig, results: list[dict[str, Any]], mode: str) -> None:
    title = format_notify_title(results, mode)
    content = format_summary(results, mode)

    if _ql_notify:
        try:
            log("📣 通知状态: 正在调用青龙面板统一通知发送推送 🚀")
            _ql_notify(title, content)
            return
        except Exception as exc:
            debug(f"青龙通知发送失败: {exc}")

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

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="酷狗概念版金币任务（多账号）")
    parser.add_argument("--config", help="本地 yaml 配置路径")
    parser.add_argument("--info", action="store_true", help="仅查询账号、金币、签到和任务进度")
    parser.add_argument("--once", action="store_true", help="只做一轮任务，跳过 1105 循环")
    parser.add_argument("--tasks-only", action="store_true", help="同 --once")
    parser.add_argument("--flip", action="store_true", help="仅执行翻牌活动")
    parser.add_argument("--welfare", action="store_true", help="仅执行福利中心")
    parser.add_argument("--assist", metavar="SHARE_CODE", help="翻牌助力")
    parser.add_argument("--test", action="store_true", help="仅做签名自检")
    parser.add_argument("--serial", action="store_true", help="多账号串行执行")
    parser.add_argument("--parallel", action="store_true", help="多账号并发执行（默认）")
    parser.add_argument("--debug", action="store_true", help="输出调试日志")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    global IS_DEBUG
    IS_DEBUG = args.debug or _env("DEBUG") == "1"

    log("=" * 62)
    log(f"🎵 {APP_NAME} v{VERSION}")
    log(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 62)

    if args.test:
        return 0 if self_test() else 1

    try:
        cfg = resolve_config(args.config)
    except FileNotFoundError as exc:
        log(str(exc) or MISSING_CONFIG_HINT)
        return 1
    except Exception as exc:
        log(f"❌ 读取配置失败: {exc}")
        return 1

    if args.serial:
        cfg.concurrent = False
    if args.parallel:
        cfg.concurrent = True

    if args.info:
        mode = "info"
    elif args.flip:
        mode = "flip"
    elif args.welfare:
        mode = "welfare"
    elif args.assist:
        mode = "assist"
    elif args.once or args.tasks_only:
        mode = "once"
    else:
        mode = "run"

    if mode in ("run", "once", "flip", "welfare"):
        if not self_test():
            return 1

    log(f"👥 共 {len(cfg.accounts)} 个账号，模式：{mode}")

    if not acquire_lock(cfg):
        log("已有实例在运行，退出")
        return 0

    results: list[dict[str, Any]] = []
    try:
        if cfg.concurrent and len(cfg.accounts) > 1:
            max_workers = min(len(cfg.accounts), cfg.max_workers)
            log(f"⚡ 多账号并发执行（并发数: {max_workers}）")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(AccountRunner(account, cfg).run, mode, args.assist)
                    for account in cfg.accounts
                ]
                for account, future in zip(cfg.accounts, futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:
                        log(f"❌ [{account.remark}] 执行异常: {exc}")
                        results.append(
                            {
                                "remark": account.remark,
                                "userid": account.userid,
                                "ok": False,
                                "err": str(exc),
                            }
                        )
        else:
            log("ℹ️ 串行执行")
            for index, account in enumerate(cfg.accounts, 1):
                log(f"── 账号 {index}/{len(cfg.accounts)} ──")
                try:
                    results.append(AccountRunner(account, cfg).run(mode, args.assist))
                except Exception as exc:
                    log(f"❌ [{account.remark}] 执行失败: {exc}")
                    results.append(
                        {
                            "remark": account.remark,
                            "userid": account.userid,
                            "ok": False,
                            "err": str(exc),
                        }
                    )
                if index < len(cfg.accounts):
                    time.sleep(random.uniform(2, 5))
    finally:
        release_lock(cfg)

    summary = format_summary(results, mode)
    log("\n" + summary)
    send_notifications(cfg, results, mode)
    return 0 if any(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
