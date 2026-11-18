#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
顺丰速运日常积分任务

cron: 0 8 * * *
new Env('顺丰速运日常任务');

相对 v1.3：
  - 保留 APP / 新签到 / 小程序签到、积分任务 list/finish/fetch、生活特权领券
  - 增加社区仍有效的 超值福利签到；丰蜜 / 会员日仅在接口仍开放时执行，结束或无资格则跳过
  - 登录只用 sfsyUrl / session cookie（抓积分页）；内地 APP 是短信验证码，没有手机号+密码
  - 日志带 emoji；配置了 BARK_URL / BARK_KEY 时推送 Bark 摘要

青龙环境变量（账号）：
  SFSY_ACCOUNTS  JSON 数组（推荐，name 即备注）
  或 sfsyUrl / SFSY_URL / SFSY_COOKIE（& 或换行分隔；值末尾 #备注）
  或平行变量 SFSY_NAME（与上面按下标对齐）

青龙环境变量（Bark，与 hifiti 相同契约）：
  BARK_URL  或  BARK_KEY + 可选 BARK_SERVER
  可选：BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

依赖：requests
本地 yaml 可选：PyYAML
"""

from __future__ import annotations

import argparse
import hashlib
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
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests

try:
    from requests.packages.urllib3.exceptions import InsecureRequestWarning

    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    pass

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
APP_NAME = "顺丰速运"
VERSION = "1.4.0"

MCS_HOST = "mcs-mimp-web.sf-express.com"
MCS_ORIGIN = f"https://{MCS_HOST}"
MCS_TOKEN = "wwesldfs29aniversaryvdld29"
MCS_SYS_CODE = "MCS-MIMP-CORE"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/98.0.4758.102 Safari/537.36 NetType/WIFI "
    "MicroMessenger/7.0.20.1781(0x6700143B) WindowsWechat(0x63090551) XWEB/6945 Flue"
)

DEFAULT_BARK_SERVER = "https://api.day.app"
DEFAULT_BARK_GROUP = "顺丰速运"
DEFAULT_TIMEOUT = 15

SKIP_TASKS_DEFAULT = [
    "用行业模板寄件下单",
    "用积分兑任意礼品",
    "参与积分活动",
    "每月累计寄件",
    "完成每月任务",
    "去使用AI寄件",
]

ACTIVITY_SKIP_MARKERS = (
    "活动结束",
    "活动已结束",
    "活动已下线",
    "没有资格",
    "不在活动时间",
    "已过期",
    "未到活动时间",
    "活动尚未开始",
)

MISSING_CONFIG_HINT = (
    "❌ 未找到账号配置。\n"
    "📝 青龙：设置 SFSY_ACCOUNTS，或 sfsyUrl / SFSY_URL / SFSY_COOKIE"
    "（抓 App/小程序「我的→积分」页）\n"
    "📝 本地：cp config.example.yaml config.yaml 并填写"
)

# 积分 / 活动接口（供构造与测试）
URL_APP_SIGN = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~integralTaskSignPlusService~getUnFetchPointAndDiscount"
)
URL_NEW_SIGN = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~integralSignV2Service~sign"
)
URL_MINI_SIGN = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~integralTaskSignPlusService~automaticSignFetchPackage"
)
URL_TASK_LIST = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~integralTaskStrategyService~queryPointTaskAndSignFromES"
)
URL_TASK_FINISH = (
    f"{MCS_ORIGIN}/mcs-mimp/commonRoutePost/memberEs/taskRecord/finishTask"
)
URL_TASK_FETCH = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~integralTaskStrategyService~fetchIntegral"
)
URL_WELFARE_LIST = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberGoods~mallGoodsLifeService~list"
)
URL_WELFARE_ORDER = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberGoods~pointMallService~createOrder"
)
URL_SUPER_WELFARE = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberActLengthy~redPacketActivityService~superWelfare~receiveRedPacket"
)
URL_HONEY_INDEX = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~receiveExchangeIndexService~indexData"
)
URL_HONEY_TASK = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~receiveExchangeIndexService~taskDetail"
)
URL_HONEY_RECEIVE = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~receiveExchangeIndexService~receiveHoney"
)
URL_HONEY_FINISH = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/~memberEs~taskRecord~finishTask"
)
URL_MEMBER_DAY_INDEX = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~memberDayIndexService~index"
)
URL_MEMBER_DAY_LOTTERY = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~memberDayLotteryService~lottery"
)
URL_MEMBER_DAY_TASKS = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~activityTaskService~taskList"
)
URL_MEMBER_DAY_FETCH = (
    f"{MCS_ORIGIN}/mcs-mimp/commonPost/"
    "~memberNonactivity~activityTaskService~fetchMixTaskReward"
)

# 社区探活后保留 / 明确不引入的活动
EXTRA_METHOD_CATALOG: list[dict[str, str]] = [
    {
        "name": "超值福利签到",
        "status": "kept",
        "reason": "社区常规接口，未登录时仍返回 100111 而非活动结束",
        "url": URL_SUPER_WELFARE,
    },
    {
        "name": "采蜜/丰蜜",
        "status": "kept",
        "reason": "季度循环活动，接口仍开放；活动结束/无资格时跳过",
        "url": URL_HONEY_INDEX,
    },
    {
        "name": "会员日",
        "status": "kept",
        "reason": "每月 26–28 日窗口；接口仍开放，窗口外或无资格跳过",
        "url": URL_MEMBER_DAY_INDEX,
    },
    {
        "name": "端午/年终集卡/周年庆/32周年游戏",
        "status": "deferred",
        "reason": "季节活动已过期，不引入",
        "url": "",
    },
]


# ---------------------------------------------------------------------------
# 小工具（测试直接驱动这些函数）
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _split_multi(value: str) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in re.split(r"[&\n]", value) if x.strip()]


def mask_mobile(phone: str) -> str:
    phone = (phone or "").strip()
    if len(phone) >= 7:
        return phone[:3] + "****" + phone[7:]
    return phone or "未知"


def generate_device_id(characters: str = "abcdef0123456789") -> str:
    out = []
    for ch in "xxxxxxxx-xxxx-xxxx":
        out.append(random.choice(characters) if ch == "x" else ch)
    return "".join(out)


def build_mcs_sign(
    timestamp: Optional[str] = None,
    *,
    token: str = MCS_TOKEN,
    sys_code: str = MCS_SYS_CODE,
) -> dict[str, str]:
    """MCS-MIMP 请求签名。"""
    ts = timestamp or str(int(round(time.time() * 1000)))
    raw = f"token={token}&timestamp={ts}&sysCode={sys_code}"
    return {
        "sysCode": sys_code,
        "timestamp": ts,
        "signature": hashlib.md5(raw.encode()).hexdigest(),
    }


def is_activity_skip_message(message: str) -> bool:
    text = message or ""
    return any(m in text for m in ACTIVITY_SKIP_MARKERS)


def is_member_day_window(day: Optional[int] = None) -> bool:
    d = datetime.now().day if day is None else int(day)
    return 26 <= d <= 28


def build_super_welfare_request() -> tuple[str, dict[str, Any]]:
    return URL_SUPER_WELFARE, {"channel": "czflqdlhbxcx"}


def build_honey_index_request(invite_user_id: str = "") -> tuple[str, dict[str, Any]]:
    return URL_HONEY_INDEX, {"inviteUserId": invite_user_id or ""}


def build_member_day_index_request(invite_user_id: str = "") -> tuple[str, dict[str, Any]]:
    return URL_MEMBER_DAY_INDEX, {"inviteUserId": invite_user_id or ""}


def build_mini_sign_request() -> tuple[str, dict[str, Any]]:
    return URL_MINI_SIGN, {"comeFrom": "vioin", "channelFrom": "WEIXIN"}


def build_task_list_request(channel_type: str, device_id: str) -> tuple[str, dict[str, Any]]:
    return URL_TASK_LIST, {"channelType": str(channel_type), "deviceId": device_id}


def build_task_finish_request(task_code: str) -> tuple[str, dict[str, Any]]:
    return URL_TASK_FINISH, {"taskCode": task_code}


def build_task_fetch_request(
    strategy_id: Any, task_id: str, task_code: str, device_id: str
) -> tuple[str, dict[str, Any]]:
    return URL_TASK_FETCH, {
        "strategyId": strategy_id,
        "taskId": task_id,
        "taskCode": task_code,
        "deviceId": device_id,
    }


def is_mcs_auth_error(payload: Optional[dict[str, Any]]) -> bool:
    """积分中心 100111 / 用户信息失效：cookie 不是 MCS session 或已过期。"""
    if not payload:
        return False
    msg = str(payload.get("errorMessage") or "")
    code = str(payload.get("errorCode") or "")
    return code == "100111" or "用户信息失效" in msg


def classify_extra_api_response(payload: Optional[dict[str, Any]]) -> str:
    """
    将活动接口响应归类：live / skip / unknown
    未登录(100111)视为接口仍存活。
    """
    if not payload:
        return "unknown"
    msg = str(payload.get("errorMessage") or "")
    code = str(payload.get("errorCode") or "")
    if payload.get("success"):
        return "live"
    if is_activity_skip_message(msg):
        return "skip"
    if code == "100111" or "用户信息失效" in msg or "请登录" in msg:
        return "live"
    return "unknown"


def parse_cookie_string(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    text = unquote((raw or "").strip())
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    for item in re.split(r";\s*", text):
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            cookies[k] = v
    return cookies


def looks_like_cookie(raw: str) -> bool:
    text = unquote((raw or "").strip())
    if not text:
        return False
    if text.startswith("http://") or text.startswith("https://"):
        return False
    return text.startswith("sessionId=") or "_login_mobile_=" in text or "sessionId=" in text


def split_session_and_name(raw: str) -> tuple[str, str]:
    """
    从「session#备注」拆出值和备注。最后一个 # 之后视为备注
    （备注里不要带 / 或 http，以免和 URL 片段混淆）。
    """
    text = (raw or "").strip()
    if "#" not in text:
        return text, ""
    value, note = text.rsplit("#", 1)
    value, note = value.strip(), note.strip()
    if not value or not note:
        return text, ""
    if "/" in note or note.lower().startswith("http"):
        return text, ""
    if not (looks_like_cookie(value) or value.startswith("http://") or value.startswith("https://")):
        return text, ""
    return value, note


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    sfsy_url: str = ""
    cookie: str = ""

    def has_session(self) -> bool:
        return bool(self.sfsy_url.strip() or self.cookie.strip())

    def normalize(self) -> None:
        self.sfsy_url = self.sfsy_url.strip()
        self.cookie = self.cookie.strip()
        if self.cookie.lower().startswith("cookie:"):
            self.cookie = self.cookie.split(":", 1)[1].strip()
        # 有人把 cookie 填进 sfsy_url
        if self.sfsy_url and looks_like_cookie(self.sfsy_url) and not self.cookie:
            self.cookie = unquote(self.sfsy_url)
            self.sfsy_url = ""


def select_login_mode(account: Account) -> str:
    """仅 session：sfsyUrl 或 cookie。内地 APP 没有手机号+密码。"""
    if account.has_session():
        return "session"
    return "none"


def account_identity(account: Account) -> str:
    """同一手机号 / sessionId 视为同一账号，避免环境变量与 yaml 重复跑。"""
    blob = account.cookie or ""
    if not looks_like_cookie(blob) and looks_like_cookie(account.sfsy_url):
        blob = account.sfsy_url
    cookies = parse_cookie_string(blob)
    mobile = cookies.get("_login_mobile_") or ""
    if mobile:
        return f"mobile:{mobile}"
    sid = cookies.get("sessionId") or ""
    if sid:
        return f"sid:{sid}"
    if account.sfsy_url.strip():
        return f"url:{account.sfsy_url.strip()}"
    if account.cookie.strip():
        return f"cookie:{account.cookie.strip()}"
    return f"name:{account.name}"


def merge_accounts(*groups: list[Account]) -> list[Account]:
    seen: set[str] = set()
    out: list[Account] = []
    for group in groups:
        for acc in group:
            if not acc.has_session():
                continue
            ident = account_identity(acc)
            if ident in seen:
                continue
            seen.add(ident)
            out.append(acc)
    return out


@dataclass
class NotifyConfig:
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = DEFAULT_BARK_GROUP
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""

    def enabled(self) -> bool:
        return bool(self.bark_url or self.bark_key)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    timeout: int = DEFAULT_TIMEOUT
    skip_tasks: list[str] = field(default_factory=lambda: list(SKIP_TASKS_DEFAULT))
    proxy_api_url: str = ""
    user_agent: str = DEFAULT_UA


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
        bark_group=_env("BARK_GROUP", DEFAULT_BARK_GROUP) or DEFAULT_BARK_GROUP,
        bark_sound=_env("BARK_SOUND"),
        bark_icon=_env("BARK_ICON"),
        bark_level=_env("BARK_LEVEL"),
    )


def build_bark_endpoint(cfg: NotifyConfig) -> Optional[str]:
    """返回 Bark 基础推送前缀（不含 title/body），与 hifiti 相同。"""
    if cfg.bark_url:
        return cfg.bark_url.strip().rstrip("/")
    if cfg.bark_key:
        server = (cfg.bark_server or DEFAULT_BARK_SERVER).rstrip("/")
        return f"{server}/{cfg.bark_key.strip()}"
    return None


def send_bark(cfg: NotifyConfig, title: str, body: str) -> None:
    endpoint = build_bark_endpoint(cfg)
    if not endpoint:
        return
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.bark_group or DEFAULT_BARK_GROUP,
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
        print(f"📣 Bark 已推送（HTTP {r.status_code}）")
    except Exception as e:
        print(f"⚠️ Bark 推送失败: {e}")


def _parse_accounts_json(raw: str) -> list[Account]:
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("SFSY_ACCOUNTS 必须是 JSON 数组")
    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"SFSY_ACCOUNTS[{i}] 必须是对象")
        acc = Account(
            name=str(
                item.get("name")
                or item.get("note")
                or item.get("remark")
                or f"账号{i + 1}"
            ),
            sfsy_url=str(item.get("sfsy_url") or item.get("url") or ""),
            cookie=str(item.get("cookie") or ""),
        )
        acc.normalize()
        accounts.append(acc)
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    accounts_json = _env("SFSY_ACCOUNTS")
    if accounts_json:
        return _parse_accounts_json(accounts_json)

    urls = _split_multi(_env("sfsyUrl") or _env("SFSY_URL"))
    cookies = _split_multi(_env("SFSY_COOKIE"))
    names = _split_multi(_env("SFSY_NAME"))

    n = max(len(urls), len(cookies))
    accounts: list[Account] = []
    if n > 0:
        for i in range(n):
            raw_url = urls[i] if i < len(urls) else ""
            raw_cookie = cookies[i] if i < len(cookies) else ""
            url, url_note = split_session_and_name(raw_url)
            cookie, cookie_note = split_session_and_name(raw_cookie)
            aligned = names[i] if i < len(names) else ""
            acc = Account(
                name=aligned or url_note or cookie_note or f"账号{i + 1}",
                sfsy_url=url,
                cookie=cookie,
            )
            acc.normalize()
            accounts.append(acc)
    return accounts


def load_config_from_env() -> Optional[AppConfig]:
    accounts = _parse_accounts_from_env()
    if not accounts:
        return None
    return AppConfig(
        accounts=accounts,
        notify=load_notify_from_env(),
        timeout=int(_env("SFSY_TIMEOUT") or str(DEFAULT_TIMEOUT)),
        proxy_api_url=_env("SF_PROXY_API_URL"),
        user_agent=_env("SFSY_UA") or DEFAULT_UA,
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
        acc = Account(
            name=str(
                item.get("name")
                or item.get("note")
                or item.get("remark")
                or f"账号{i + 1}"
            ),
            sfsy_url=str(item.get("sfsy_url") or item.get("url") or ""),
            cookie=str(item.get("cookie") or ""),
        )
        acc.normalize()
        if acc.has_session():
            accounts.append(acc)

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
        bark_group=_env("BARK_GROUP") or str(n.get("bark_group") or DEFAULT_BARK_GROUP),
        bark_sound=env_notify.bark_sound or str(n.get("bark_sound") or ""),
        bark_icon=env_notify.bark_icon or str(n.get("bark_icon") or ""),
        bark_level=env_notify.bark_level or str(n.get("bark_level") or ""),
    )
    return AppConfig(
        accounts=accounts,
        notify=notify,
        timeout=int(raw.get("timeout") or DEFAULT_TIMEOUT),
        skip_tasks=list(raw.get("skip_tasks") or SKIP_TASKS_DEFAULT),
        proxy_api_url=str(raw.get("proxy_api_url") or _env("SF_PROXY_API_URL")),
        user_agent=str(raw.get("user_agent") or DEFAULT_UA),
    )


def resolve_config(config_path: Optional[str] = None) -> AppConfig:
    yaml_path = Path(config_path) if config_path else SCRIPT_DIR / "config.yaml"
    yaml_cfg: Optional[AppConfig] = None
    if yaml_path.is_file():
        yaml_cfg = load_config_yaml(yaml_path)

    env_accounts = _parse_accounts_from_env()
    yaml_accounts = list(yaml_cfg.accounts) if yaml_cfg else []
    accounts = merge_accounts(env_accounts, yaml_accounts)
    if not accounts:
        raise FileNotFoundError(MISSING_CONFIG_HINT)

    if yaml_cfg is not None:
        yaml_cfg.accounts = accounts
        if env_accounts:
            print(f"📦 已合并账号：环境变量 + config.yaml，共 {len(accounts)} 个")
        return yaml_cfg

    return AppConfig(
        accounts=accounts,
        notify=load_notify_from_env(),
        timeout=int(_env("SFSY_TIMEOUT") or str(DEFAULT_TIMEOUT)),
        proxy_api_url=_env("SF_PROXY_API_URL"),
        user_agent=_env("SFSY_UA") or DEFAULT_UA,
    )


# ---------------------------------------------------------------------------
# HTTP 客户端
# ---------------------------------------------------------------------------

def _is_retryable_network_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    ) or any(
        key in text
        for key in (
            "nameresolutionerror",
            "failed to resolve",
            "temporary failure in name resolution",
            "no address associated",
            "max retries exceeded",
        )
    )


class SFClient:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.verify = False
        self.headers = {
            "Host": MCS_HOST,
            "user-agent": cfg.user_agent or DEFAULT_UA,
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "accept-language": "zh-CN,zh",
            "platform": "MINI_PROGRAM",
        }
        if cfg.proxy_api_url:
            try:
                pr = requests.get(cfg.proxy_api_url, timeout=10)
                text = pr.text.strip()
                if text and ":" in text:
                    proxy = text if text.startswith("http") else f"http://{text}"
                    self.session.proxies = {"http": proxy, "https": proxy}
                    print(f"✅ 已设置代理")
            except Exception as e:
                print(f"⚠️ 获取代理失败，直连: {e}")

    def apply_cookies(self, cookies: dict[str, str]) -> None:
        for k, v in cookies.items():
            self.session.cookies.set(k, v, domain=MCS_HOST)

    def login_session(self, account: Account) -> tuple[bool, str, str]:
        raw = account.cookie or account.sfsy_url
        if not raw:
            return False, "", ""
        try:
            decoded = unquote(raw)
            if looks_like_cookie(decoded):
                cookies = parse_cookie_string(decoded)
                self.apply_cookies(cookies)
                phone = cookies.get("_login_mobile_", "")
                user_id = cookies.get("_login_user_id_", "")
                if not phone:
                    return False, "", ""
                if not self._mcs_session_alive():
                    print(
                        "❌ cookie 不是有效的积分中心 session（错误或已过期）。"
                        "请重新抓 App/小程序「我的→积分」页的 sfsyUrl/cookie"
                    )
                    return False, user_id, phone
                return True, user_id, phone
            last_exc: Optional[BaseException] = None
            for attempt in range(3):
                try:
                    self.session.get(
                        decoded,
                        headers={
                            "Host": MCS_HOST,
                            "user-agent": self.cfg.user_agent or DEFAULT_UA,
                            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            "upgrade-insecure-requests": "1",
                            "platform": "MINI_PROGRAM",
                        },
                        timeout=self.cfg.timeout,
                    )
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    if attempt < 2 and _is_retryable_network_error(e):
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    raise
            if last_exc:
                raise last_exc
            cookies = self.session.cookies.get_dict()
            phone = cookies.get("_login_mobile_", "")
            user_id = cookies.get("_login_user_id_", "")
            if not phone:
                return False, "", ""
            if not self._mcs_session_alive():
                print("❌ sfsyUrl 未换到有效积分 session，请重新抓积分页")
                return False, user_id, phone
            return True, user_id, phone
        except Exception as e:
            print(f"❌ session 登录异常: {e}")
            return False, "", ""

    def _mcs_session_alive(self) -> bool:
        """积分中心认不认当前 cookie。官网 token 拼出来的会回 100111。"""
        resp = self.request(
            URL_TASK_LIST,
            {"channelType": "1", "deviceId": generate_device_id()},
        )
        if resp is None:
            # 网络失败时不误杀本地 cookie
            return True
        if resp.get("success"):
            return True
        return not is_mcs_auth_error(resp)

    def request(
        self,
        url: str,
        data: Optional[dict[str, Any]] = None,
        *,
        platform: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> Optional[dict[str, Any]]:
        headers = dict(self.headers)
        headers.update(build_mcs_sign())
        if platform:
            headers["platform"] = platform
        if extra_headers:
            headers.update(extra_headers)
        last_error: Optional[BaseException] = None
        for attempt in range(3):
            try:
                resp = self.session.post(
                    url, headers=headers, json=data or {}, timeout=self.cfg.timeout
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_error = e
                if attempt < 2 and _is_retryable_network_error(e):
                    wait = 1.5 * (attempt + 1)
                    print(f"⚠️ 请求失败，{wait:.1f}s 后重试 ({attempt + 1}/3): {e}")
                    time.sleep(wait)
                    continue
                print(f"⚠️ 请求失败: {e}")
                return None
        print(f"⚠️ 请求失败: {last_error}")
        return None


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------

class TaskRunner:
    def __init__(self, client: SFClient, cfg: AppConfig, user_id: str):
        self.http = client
        self.cfg = cfg
        self.user_id = user_id
        self.total_points = 0
        self.task_id = ""
        self.task_code = ""
        self.strategy_id: Any = 0
        self.title = ""

    def _extract_task_id(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            if "_ug_view_param" in params:
                ug = json.loads(unquote(params["_ug_view_param"][0]))
                if "taskId" in ug:
                    return str(ug["taskId"])
            if "_ug_view_param=" in url:
                json_str = url.split("_ug_view_param=", 1)[1]
                ug = json.loads(unquote(json_str))
                if "taskId" in ug:
                    return str(ug["taskId"])
        except Exception:
            return ""
        return ""

    def _set_task(self, task: dict[str, Any]) -> None:
        self.task_id = str(task.get("taskId") or "")
        self.task_code = str(task.get("taskCode") or "")
        try:
            self.strategy_id = int(task.get("strategyId") or 0)
        except Exception:
            self.strategy_id = task.get("strategyId") or 0
        self.title = str(task.get("title") or "未知任务")
        if not self.task_code and task.get("buttonRedirect"):
            extracted = self._extract_task_id(str(task["buttonRedirect"]))
            if extracted:
                self.task_code = extracted

    def app_sign_in(self) -> tuple[bool, str]:
        print("📝 [APP签到] 开始")
        resp = self.http.request(URL_APP_SIGN, {}, platform="SFAPP")
        if resp and resp.get("success"):
            obj = resp.get("obj") or []
            if isinstance(obj, list) and obj:
                names = [str(i.get("packetName") or "未知奖励") for i in obj]
                print(f"✨ [APP签到] 签到成功，获得【{', '.join(names)}】")
            else:
                print("📝 [APP签到] 今日已签到或无可领取奖励")
            return True, ""
        err = (resp or {}).get("errorMessage") or "请求失败"
        if "没有待领取礼包" in str(err):
            print("📝 [APP签到] 二次领取…")
            time.sleep(1)
            resp2 = self.http.request(URL_APP_SIGN, {}, platform="SFAPP")
            if resp2 and resp2.get("success"):
                obj2 = resp2.get("obj") or []
                if isinstance(obj2, list) and obj2:
                    names = [str(i.get("packetName") or "未知奖励") for i in obj2]
                    print(f"✨ [APP签到] 二次领取成功，获得【{', '.join(names)}】")
                else:
                    print("📝 [APP签到] 二次领取完成，无可领取奖励")
                return True, ""
            err = (resp2 or {}).get("errorMessage") or err
        print(f"❌ [APP签到] 失败: {err}")
        return False, str(err)

    def new_sign_in(self) -> tuple[bool, str]:
        print("📝 [新签到] 开始")
        resp = self.http.request(URL_NEW_SIGN, {}, platform="SFAPP")
        if resp and resp.get("success"):
            obj = resp.get("obj") or {}
            award = obj.get("award") or {}
            if obj.get("signed") and award:
                print(
                    f"✨ [新签到] 签到成功，连续第{obj.get('dayCount', 0)}天，"
                    f"获得【{award.get('giftBagName', '未知奖励')}】"
                )
            elif obj.get("signed"):
                print(f"📝 [新签到] 今日已签到，连续第{obj.get('dayCount', 0)}天")
            else:
                print("📝 [新签到] 签到完成")
            return True, ""
        err = (resp or {}).get("errorMessage") or "请求失败"
        print(f"❌ [新签到] 失败: {err}")
        return False, str(err)

    def mini_sign_in(self) -> tuple[bool, str]:
        print("📝 [小程序签到] 开始")
        url, data = build_mini_sign_request()
        resp = self.http.request(url, data)
        if resp and resp.get("success"):
            obj = resp.get("obj") or {}
            count_day = obj.get("countDay", 0)
            packets = obj.get("integralTaskSignPackageVOList") or []
            if packets:
                name = packets[0].get("packetName", "未知奖励")
                print(f"✨ [小程序签到] 成功，获得【{name}】，本周累计【{count_day + 1}】天")
            else:
                print(f"📝 [小程序签到] 今日已签到，本周累计【{count_day + 1}】天")
            return True, ""
        err = (resp or {}).get("errorMessage") or "请求失败"
        print(f"❌ [小程序签到] 失败: {err}")
        return False, str(err)

    def super_welfare(self) -> tuple[str, str]:
        """返回 (status, detail)，status=ok/skip/fail。"""
        print("🎁 [超值福利签到] 开始")
        url, data = build_super_welfare_request()
        resp = self.http.request(url, data)
        if resp and resp.get("success"):
            obj = resp.get("obj") or {}
            gifts = list(obj.get("giftList") or [])
            gifts.extend(obj.get("extraGiftList") or [])
            names = ", ".join(str(g.get("giftName") or "") for g in gifts if g)
            status = "领取成功" if obj.get("receiveStatus") == 1 else "已领取过"
            print(f"🎉 [超值福利签到] {status}: {names or '无礼包名'}")
            return "ok", names or status
        err = (resp or {}).get("errorMessage") or "请求失败"
        if is_activity_skip_message(str(err)):
            print(f"⏭️ [超值福利签到] 跳过: {err}")
            return "skip", str(err)
        print(f"❌ [超值福利签到] 失败: {err}")
        return "fail", str(err)

    def get_task_list(self) -> list[dict[str, Any]]:
        all_tasks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for channel in ("1", "2", "3", "4", "01", "02", "03", "04"):
            url, data = build_task_list_request(channel, generate_device_id())
            resp = self.http.request(url, data)
            if not (resp and resp.get("success") and resp.get("obj")):
                continue
            if channel in {"1", "01"}:
                self.total_points = int(resp["obj"].get("totalPoint") or self.total_points or 0)
            for task in resp["obj"].get("taskTitleLevels") or []:
                code = str(task.get("taskCode") or "")
                if not code and task.get("buttonRedirect"):
                    code = self._extract_task_id(str(task["buttonRedirect"]))
                    if code:
                        task["taskCode"] = code
                if not code or code in seen:
                    continue
                seen.add(code)
                all_tasks.append(task)
        return all_tasks

    def execute_task(self) -> bool:
        url, data = build_task_finish_request(self.task_code)
        resp = self.http.request(url, data)
        return bool(resp and resp.get("success"))

    def receive_task_reward(self) -> bool:
        url, data = build_task_fetch_request(
            self.strategy_id, self.task_id, self.task_code, generate_device_id()
        )
        resp = self.http.request(url, data)
        if resp and resp.get("success"):
            print(f"🎁 [{self.title}] 奖励领取成功")
            return True
        return False

    def get_welfare_list(self) -> list[dict[str, Any]]:
        resp = self.http.request(
            URL_WELFARE_LIST,
            {"memGrade": 3, "categoryCode": "SHTQ", "showCode": "SHTQWNTJ"},
        )
        if not (resp and resp.get("success")):
            return []
        found: list[dict[str, Any]] = []
        for module in resp.get("obj") or []:
            for goods in module.get("goodsList") or []:
                if goods.get("exchangeStatus") == 1 or int(goods.get("exchangeTimesLimit") or 0) >= 1:
                    found.append(goods)
        return found

    def receive_welfare(self, goods: dict[str, Any]) -> bool:
        resp = self.http.request(
            URL_WELFARE_ORDER,
            {
                "from": "Point_Mall",
                "orderSource": "POINT_MALL_EXCHANGE",
                "goodsNo": goods.get("goodsNo"),
                "quantity": 1,
                "taskCode": self.task_code,
            },
        )
        name = goods.get("goodsName") or goods.get("showName") or "生活特权"
        if resp and resp.get("success"):
            print(f"✨ 成功领取生活特权: {name}")
            return True
        err = (resp or {}).get("errorMessage") or "请求失败"
        print(f"❌ 领取生活特权失败: {name} - {err}")
        return False

    def handle_welfare_task(self) -> bool:
        print("📝 正在获取生活特权列表…")
        items = self.get_welfare_list()
        if not items:
            print("⚠️ 没有可领取的生活特权")
            return False
        print(f"🎯 找到 {len(items)} 个可领取的生活特权")
        for goods in items:
            if not goods.get("goodsNo"):
                continue
            if self.receive_welfare(goods):
                return True
            time.sleep(1)
        return False

    def run_point_tasks(self) -> tuple[int, int]:
        print("-" * 50)
        print("📝 正在获取积分任务列表…")
        tasks = self.get_task_list()
        if not tasks:
            print("❌ 获取任务列表失败")
            return 0, 0
        before = self.total_points
        print(f"💰 执行前积分: 【{before}】")
        for task in tasks:
            title = str(task.get("title") or "未知任务")
            status = task.get("status")
            if status == 3:
                print(f"✅ {title} - 已完成")
                continue
            if title in self.cfg.skip_tasks:
                print(f"⏭️ [{title}] 已跳过")
                continue
            self._set_task(task)
            if not self.task_code:
                print(f"⚠️ {title} - 无法提取 taskCode，跳过")
                continue
            print(f"🎯 发现任务: {title} (状态: {status})")
            if "领任意生活特权福利" in title:
                if self.handle_welfare_task():
                    time.sleep(2)
                    if self.execute_task():
                        print(f"✅ [{title}] 提交成功")
                        time.sleep(2)
                        self.receive_task_reward()
                else:
                    print(f"⚠️ {title} - 无法完成, 跳过")
                time.sleep(2)
                continue
            if status == 1:
                if "连签7天" in title and "process" in task:
                    try:
                        current, total = map(int, str(task["process"]).split("/"))
                        if current < total:
                            print(f"📝 【{title}】进度: {task['process']}，还需{total - current}天")
                            continue
                    except Exception:
                        pass
                if self.execute_task():
                    print(f"✅ [{title}] 提交成功")
                    time.sleep(2)
                    status = 2
                else:
                    print(f"⚠️ 任务执行失败: {title}")
                    continue
            if status == 2:
                if self.receive_task_reward():
                    continue
                if self.execute_task():
                    print(f"✅ [{title}] 提交成功")
                    time.sleep(2)
                    self.receive_task_reward()
            time.sleep(2)
        self.get_task_list()
        after = self.total_points or before
        print(f"💰 执行后积分: 【{after}】")
        return before, after

    def honey_flow(self) -> tuple[str, str]:
        print("🍯 [采蜜/丰蜜] 开始")
        url, data = build_honey_index_request(self.user_id)
        resp = self.http.request(url, data, extra_headers={"channel": "wxwdsj"})
        if not resp:
            print("⚠️ [采蜜/丰蜜] 无响应，跳过")
            return "skip", "无响应"
        err = str(resp.get("errorMessage") or "")
        if is_activity_skip_message(err) or classify_extra_api_response(resp) == "skip":
            print(f"⏭️ [采蜜/丰蜜] 跳过: {err or '活动不可用'}")
            return "skip", err or "活动不可用"
        if not resp.get("success"):
            print(f"⏭️ [采蜜/丰蜜] 跳过: {err or '未成功'}")
            return "skip", err or "未成功"
        obj = resp.get("obj") or {}
        honey = obj.get("usableHoney")
        end_time = obj.get("activityEndTime") or ""
        print(f"🍯 当前丰蜜: 【{honey}】  本期结束: {end_time or '未知'}")
        if end_time:
            try:
                if datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S") < datetime.now():
                    print("⏭️ [采蜜/丰蜜] 活动已过结束时间，跳过")
                    return "skip", f"已结束 {end_time}"
            except Exception:
                pass
        for item in obj.get("taskDetail") or []:
            task_type = item.get("type") or item.get("taskType")
            recv = self.http.request(
                URL_HONEY_RECEIVE,
                {"taskType": task_type},
                extra_headers={"channel": "wxwdsj"},
            )
            if recv and recv.get("success"):
                print(f"✨ [丰蜜] 收取 {task_type} 成功")
            elif recv and is_activity_skip_message(str(recv.get("errorMessage") or "")):
                print(f"⏭️ [丰蜜] 收取跳过: {recv.get('errorMessage')}")
                return "skip", str(recv.get("errorMessage"))
            time.sleep(1)
        detail = self.http.request(URL_HONEY_TASK, {}, extra_headers={"channel": "wxwdsj"})
        if detail and detail.get("success"):
            for item in (detail.get("obj") or {}).get("list") or []:
                if item.get("status") == 3:
                    continue
                code = item.get("taskCode")
                if not code:
                    continue
                fin = self.http.request(URL_HONEY_FINISH, {"taskCode": code})
                if fin and fin.get("success"):
                    print(f"✅ [丰蜜任务] {item.get('taskType')} 提交成功")
                time.sleep(1)
        return "ok", f"丰蜜={honey}"

    def member_day_flow(self) -> tuple[str, str]:
        if not is_member_day_window():
            print("⏭️ [会员日] 今日不在 26–28 日窗口，跳过")
            return "skip", "不在活动窗口"
        print("🎭 [会员日] 开始")
        url, data = build_member_day_index_request(self.user_id)
        resp = self.http.request(url, data)
        if not resp:
            print("⚠️ [会员日] 无响应，跳过")
            return "skip", "无响应"
        err = str(resp.get("errorMessage") or "")
        if is_activity_skip_message(err) or classify_extra_api_response(resp) == "skip":
            print(f"⏭️ [会员日] 跳过: {err or '无资格/已结束'}")
            return "skip", err or "无资格"
        if not resp.get("success"):
            print(f"⏭️ [会员日] 跳过: {err or '未成功'}")
            return "skip", err or "未成功"
        lottery_num = int((resp.get("obj") or {}).get("lotteryNum") or 0)
        print(f"🎁 会员日可抽奖 {lottery_num} 次")
        for _ in range(min(lottery_num, 10)):
            lot = self.http.request(URL_MEMBER_DAY_LOTTERY, {})
            if lot and lot.get("success"):
                print(f"🎁 会员日抽奖: {(lot.get('obj') or {}).get('productName', '空气')}")
            elif lot and is_activity_skip_message(str(lot.get("errorMessage") or "")):
                return "skip", str(lot.get("errorMessage"))
            time.sleep(1)
        tasks_resp = self.http.request(
            URL_MEMBER_DAY_TASKS,
            {"activityCode": "MEMBER_DAY", "channelType": "MINI_PROGRAM"},
        )
        if tasks_resp and tasks_resp.get("success"):
            skip_types = {
                "SEND_SUCCESS",
                "INVITEFRIENDS_PARTAKE_ACTIVITY",
                "OPEN_SVIP",
                "OPEN_NEW_EXPRESS_CARD",
                "OPEN_FAMILY_CARD",
                "CHARGE_NEW_EXPRESS_CARD",
                "INTEGRAL_EXCHANGE",
            }
            for task in tasks_resp.get("obj") or []:
                if task.get("status") == 1:
                    self.http.request(
                        URL_MEMBER_DAY_FETCH,
                        {
                            "taskType": task.get("taskType"),
                            "activityCode": "MEMBER_DAY",
                            "channelType": "MINI_PROGRAM",
                        },
                    )
                elif task.get("status") == 2 and task.get("taskType") not in skip_types:
                    rest = int(task.get("restFinishTime") or 1)
                    for _ in range(min(rest, 3)):
                        if task.get("taskCode"):
                            self.http.request(URL_HONEY_FINISH, {"taskCode": task["taskCode"]})
                        time.sleep(1)
        return "ok", f"抽奖{lottery_num}次"


# ---------------------------------------------------------------------------
# 账号执行 / 摘要
# ---------------------------------------------------------------------------

def run_account(account: Account, cfg: AppConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": account.name,
        "ok": False,
        "via": select_login_mode(account),
        "phone": "",
        "points_before": 0,
        "points_after": 0,
        "points_earned": 0,
        "message": "",
        "extras": {},
    }
    client = SFClient(cfg)

    if result["via"] != "session":
        result["message"] = "未配置 sfsyUrl / cookie（内地 APP 无手机号+密码登录）"
        print(f"❌ [{account.name}] {result['message']}")
        return result

    print(f"🔐 [{account.name}] 使用 sfsyUrl / cookie 登录")
    ok, user_id, phone = client.login_session(account)
    if not ok:
        result["message"] = "cookie/url 登录失败，未拿到 _login_mobile_"
        print(f"❌ [{account.name}] {result['message']}")
        return result

    result["phone"] = phone
    print(f"👤 [{account.name}] 【{mask_mobile(phone)}】登录成功")
    time.sleep(random.uniform(0.8, 2.0))
    runner = TaskRunner(client, cfg, user_id)
    runner.app_sign_in()
    time.sleep(1)
    runner.new_sign_in()
    time.sleep(1)
    runner.mini_sign_in()
    time.sleep(1)
    sw_status, sw_detail = runner.super_welfare()
    result["extras"]["超值福利签到"] = {"status": sw_status, "detail": sw_detail}
    time.sleep(1)
    before, after = runner.run_point_tasks()
    result["points_before"] = before
    result["points_after"] = after
    result["points_earned"] = after - before
    honey_status, honey_detail = runner.honey_flow()
    result["extras"]["采蜜/丰蜜"] = {"status": honey_status, "detail": honey_detail}
    md_status, md_detail = runner.member_day_flow()
    result["extras"]["会员日"] = {"status": md_status, "detail": md_detail}
    result["ok"] = True
    result["message"] = f"积分 {before} → {after}（+{after - before}）"
    print(f"✅ [{account.name}] {result['message']}")
    return result


def format_summary(results: list[dict[str, Any]]) -> str:
    lines = [f"📅 {datetime.now().strftime('%m-%d %H:%M')}", ""]
    ok_n = sum(1 for r in results if r.get("ok"))
    for i, r in enumerate(results):
        head = f"{'✅' if r.get('ok') else '❌'} {r.get('name') or '账号'}"
        lines.append(head)
        phone = mask_mobile(str(r.get("phone") or ""))
        lines.append(f"   👤 账号：{phone}")
        lines.append(f"   🔐 方式：{r.get('via') or 'none'}")
        if r.get("ok"):
            lines.append(
                f"   💰 积分：{r.get('points_before')} → {r.get('points_after')} "
                f"（+{r.get('points_earned')}）"
            )
            for name, extra in (r.get("extras") or {}).items():
                mark = {"ok": "✨", "skip": "⏭️", "fail": "❌"}.get(
                    str(extra.get("status")), "📝"
                )
                lines.append(f"   {mark} {name}：{extra.get('detail') or extra.get('status')}")
        else:
            msg = str(r.get("message") or "失败")
            lines.append(f"   ⚠️ {msg[:160]}")
        if i < len(results) - 1:
            lines.append("")
    lines.append("")
    lines.append("────────")
    if ok_n == len(results):
        lines.append(f"📊 合计：{ok_n}/{len(results)} 全部成功 🎉")
    elif ok_n == 0:
        lines.append(f"📊 合计：0/{len(results)} 全部失败")
    else:
        lines.append(f"📊 合计：成功 {ok_n} · 失败 {len(results) - ok_n}")
    return "\n".join(lines)


def format_notify_title(results: list[dict[str, Any]]) -> str:
    ok_n = sum(1 for r in results if r.get("ok"))
    n = len(results)
    if n == 0:
        return f"{APP_NAME} 日常任务"
    if ok_n == n:
        return f"{APP_NAME} 日常任务 ✅ {ok_n}/{n}"
    if ok_n == 0:
        return f"{APP_NAME} 日常任务 ❌ 0/{n}"
    return f"{APP_NAME} 日常任务 ⚠️ {ok_n}/{n}"


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="顺丰速运日常积分任务")
    parser.add_argument("--config", help="本地 yaml 配置路径")
    args = parser.parse_args(argv)

    print("=" * 50)
    print(f"🎉 {APP_NAME} 日常任务 v{VERSION}")
    print(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    try:
        cfg = resolve_config(args.config)
    except FileNotFoundError as e:
        print(str(e) or MISSING_CONFIG_HINT)
        return 1
    except Exception as e:
        print(f"❌ 读取配置失败: {e}")
        return 1

    print(f"📱 共 {len(cfg.accounts)} 个账号")
    results: list[dict[str, Any]] = []
    for i, acc in enumerate(cfg.accounts):
        print("=" * 50)
        print(f"🚀 开始执行 {acc.name}")
        results.append(run_account(acc, cfg))
        if i < len(cfg.accounts) - 1:
            print("⏳ 等待 2 秒后执行下一个账号…")
            time.sleep(2)

    summary = format_summary(results)
    print("\n" + summary)
    print("\n🎊 所有账号任务执行完成!")

    if cfg.notify.enabled():
        send_bark(cfg.notify, format_notify_title(results), summary)
    else:
        print("📣 未配置 BARK_URL / BARK_KEY，跳过推送")
    return 0 if any(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
