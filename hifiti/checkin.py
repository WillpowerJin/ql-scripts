#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HiFiNi 音乐磁场 (https://www.hifiti.com) 自动签到

cron: 0 8 * * *
new Env('HiFiNi签到');

策略：
  1. 优先用 Cookie 签到
  2. Cookie 失效（请登录）且配置了账号密码时，自动重新登录再签
  3. 从青龙 / 系统环境变量读取配置（也可本地 config.yaml）

青龙环境变量（账号）：
  HIFINI_ACCOUNTS  推荐。JSON 数组，支持 Cookie + 密码备用，多账号
  或下列按索引对齐的变量（& 分隔多账号）：
    HIFINI_COOKIE / HIFINI_USERNAME / HIFINI_PASSWORD
    HIFINI_NAME（可选） HIFINI_DOMAIN（可选，默认 www.hifiti.com）
  或仅密码：
    HIFINI_LOGIN = 域名|用户名|密码&...

青龙环境变量（Bark 通知）：
  BARK_URL   完整推送地址，如 https://api.day.app/你的Key/
  或 BARK_KEY + 可选 BARK_SERVER（默认 https://api.day.app）
  可选：BARK_GROUP / BARK_SOUND / BARK_ICON / BARK_LEVEL

依赖：requests
  青龙：依赖管理里添加 requests
  本地 yaml 配置可选：再装 PyYAML
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

DEFAULT_DOMAIN = "www.hifiti.com"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_BARK_SERVER = "https://api.day.app"
SCRIPT_DIR = Path(__file__).resolve().parent

logger = logging.getLogger("hifiti")


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

@dataclass
class Account:
    name: str
    cookie: str = ""
    username: str = ""
    password: str = ""
    domain: str = DEFAULT_DOMAIN

    def has_cookie(self) -> bool:
        return bool(self.cookie.strip())

    def has_password(self) -> bool:
        return bool(self.username.strip() and self.password)

    def auth_label(self) -> str:
        parts = []
        if self.has_cookie():
            parts.append("cookie")
        if self.has_password():
            parts.append("password")
        return "+".join(parts) if parts else "none"

    def normalize(self) -> None:
        self.domain = (
            self.domain.strip()
            .removeprefix("https://")
            .removeprefix("http://")
            .rstrip("/")
            or DEFAULT_DOMAIN
        )
        self.cookie = self.cookie.strip()
        self.username = self.username.strip()
        if self.cookie.lower().startswith("cookie:"):
            self.cookie = self.cookie.split(":", 1)[1].strip()


@dataclass
class NotifyConfig:
    # Bark：完整 URL 或 key+server
    bark_url: str = ""
    bark_key: str = ""
    bark_server: str = DEFAULT_BARK_SERVER
    bark_group: str = "HiFiNi"
    bark_sound: str = ""
    bark_icon: str = ""
    bark_level: str = ""  # active / timeSensitive / passive
    # 兼容旧配置
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
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    timeout: int = 20
    max_retries: int = 3
    retry_interval: int = 15
    user_agent: str = DEFAULT_UA


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _split_multi(value: str) -> list[str]:
    """青龙多账号：用 & 分隔。"""
    if not value:
        return []
    return [x.strip() for x in value.split("&") if x.strip()]


def _normalize_domain(domain: str) -> str:
    return (
        domain.strip()
        .removeprefix("https://")
        .removeprefix("http://")
        .rstrip("/")
        or DEFAULT_DOMAIN
    )


def _parse_accounts_json(raw: str) -> list[Account]:
    """
    HIFINI_ACCOUNTS JSON 示例：
    [
      {
        "name": "主号",
        "domain": "www.hifiti.com",
        "cookie": "bbs_sid=...; bbs_token=...",
        "username": "可选，Cookie 失效时备用",
        "password": "可选"
      }
    ]
    """
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("HIFINI_ACCOUNTS 必须是 JSON 数组")

    accounts: list[Account] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"HIFINI_ACCOUNTS[{i}] 必须是对象")
        acc = Account(
            name=str(item.get("name") or f"account_{i + 1}"),
            cookie=str(item.get("cookie") or ""),
            username=str(item.get("username") or item.get("email") or ""),
            password=str(item.get("password") or ""),
            domain=str(item.get("domain") or DEFAULT_DOMAIN),
        )
        acc.normalize()
        accounts.append(acc)
    return accounts


def _parse_accounts_from_env() -> list[Account]:
    """从环境变量组装账号列表（青龙主路径）。"""
    accounts: list[Account] = []

    # 1) JSON（推荐，Cookie + 密码备用最清晰）
    accounts_json = _env("HIFINI_ACCOUNTS")
    if accounts_json:
        accounts.extend(_parse_accounts_json(accounts_json))
        return accounts

    cookies = _split_multi(_env("HIFINI_COOKIE"))
    usernames = _split_multi(_env("HIFINI_USERNAME") or _env("HIFINI_USER"))
    passwords = _split_multi(_env("HIFINI_PASSWORD") or _env("HIFINI_PASS"))
    names = _split_multi(_env("HIFINI_NAME"))
    domains = _split_multi(_env("HIFINI_DOMAIN"))
    default_domain = domains[0] if len(domains) == 1 else DEFAULT_DOMAIN

    # 2) 按索引对齐：cookie / username / password
    n = max(len(cookies), len(usernames), len(passwords))
    if n > 0:
        for i in range(n):
            cookie = cookies[i] if i < len(cookies) else ""
            username = usernames[i] if i < len(usernames) else ""
            password = passwords[i] if i < len(passwords) else ""
            if len(domains) > 1:
                domain = domains[i] if i < len(domains) else default_domain
            else:
                domain = default_domain
            name = names[i] if i < len(names) else (
                username or f"account_{i + 1}"
            )
            acc = Account(
                name=name,
                cookie=cookie,
                username=username,
                password=password,
                domain=domain,
            )
            acc.normalize()
            accounts.append(acc)
        return accounts

    # 3) 仅密码登录：HIFINI_LOGIN=域名|用户名|密码&...
    login_list = _env("HIFINI_LOGIN")
    if login_list:
        for i, part in enumerate(_split_multi(login_list)):
            bits = part.split("|")
            if len(bits) != 3:
                raise ValueError(
                    f"HIFINI_LOGIN 第 {i + 1} 段格式错误，应为 域名|用户名|密码"
                )
            domain, username, password = bits
            acc = Account(
                name=names[i] if i < len(names) else username.strip(),
                username=username.strip(),
                password=password,
                domain=domain,
            )
            acc.normalize()
            accounts.append(acc)

    return accounts


def load_notify_from_env() -> NotifyConfig:
    bark_url = _env("BARK_URL") or _env("BARK_PUSH")
    bark_key = _env("BARK_KEY") or _env("BARK_DEVICE_KEY")
    # 若 BARK_URL 只填了 key（无 http），归到 bark_key
    if bark_url and not bark_url.startswith("http"):
        bark_key = bark_key or bark_url
        bark_url = ""

    return NotifyConfig(
        bark_url=bark_url,
        bark_key=bark_key,
        bark_server=_env("BARK_SERVER", DEFAULT_BARK_SERVER).rstrip("/"),
        bark_group=_env("BARK_GROUP", "HiFiNi"),
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

    for acc in accounts:
        if not acc.has_cookie() and not acc.has_password():
            raise ValueError(
                f"账号 [{acc.name}] 既无 Cookie 也无用户名密码，无法签到"
            )

    timeout = int(_env("HIFINI_TIMEOUT") or "20")
    max_retries = int(_env("HIFINI_MAX_RETRIES") or "3")
    retry_interval = int(_env("HIFINI_RETRY_INTERVAL") or "15")
    ua = _env("HIFINI_UA") or DEFAULT_UA

    return AppConfig(
        accounts=accounts,
        notify=load_notify_from_env(),
        timeout=timeout,
        max_retries=max_retries,
        retry_interval=retry_interval,
        user_agent=ua,
    )


def load_config_yaml(path: Path) -> AppConfig:
    try:
        import yaml
    except ImportError as e:
        raise ImportError(
            "本地 yaml 配置需要 PyYAML：pip install PyYAML"
        ) from e

    if not path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with path.open("r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    accounts: list[Account] = []
    for i, item in enumerate(raw.get("accounts") or []):
        if not isinstance(item, dict):
            raise ValueError(f"accounts[{i}] 格式错误")
        acc = Account(
            name=str(item.get("name") or f"account_{i + 1}"),
            cookie=str(item.get("cookie") or ""),
            username=str(item.get("username") or ""),
            password=str(item.get("password") or ""),
            domain=str(item.get("domain") or DEFAULT_DOMAIN),
        )
        acc.normalize()
        if not acc.has_cookie() and not acc.has_password():
            raise ValueError(f"账号 [{acc.name}] 未配置 cookie / username+password")
        accounts.append(acc)

    if not accounts:
        raise ValueError("配置中 accounts 为空")

    n = raw.get("notify") or {}
    # yaml 与环境变量合并：环境变量优先（方便青龙覆盖）
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
        else str(n.get("bark_group") or "HiFiNi"),
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
        timeout=int(raw.get("timeout") or 20),
        max_retries=int(raw.get("max_retries") or 3),
        retry_interval=int(raw.get("retry_interval") or 15),
        user_agent=str(raw.get("user_agent") or DEFAULT_UA),
    )


# ---------------------------------------------------------------------------
# 核心签到
# ---------------------------------------------------------------------------

class HiFiTiClient:
    def __init__(self, account: Account, cfg: AppConfig):
        self.account = account
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "text/plain, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self.base = f"https://{account.domain}"
        self.used_fallback_login = False

    def _common_headers(self) -> dict[str, str]:
        return {
            "Origin": self.base,
            "Referer": f"{self.base}/",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

    def reset_session(self) -> None:
        """清空 session（Cookie 失效后重新登录前调用）。"""
        self.session.cookies.clear()

    def login(self) -> None:
        acc = self.account
        if not acc.has_password():
            raise RuntimeError("未配置用户名密码，无法登录")

        logger.info("[%s] 访问首页...", acc.name)
        self.session.get(f"{self.base}/", timeout=self.cfg.timeout)

        password_md5 = hashlib.md5(acc.password.encode("utf-8")).hexdigest()
        logger.info("[%s] 使用账号密码登录 (user=%s)...", acc.name, acc.username)

        resp = self.session.post(
            f"{self.base}/user-login.htm",
            headers=self._common_headers(),
            data={"email": acc.username, "password": password_md5},
            timeout=self.cfg.timeout,
        )
        text = resp.text.strip()
        logger.debug("[%s] 登录响应: %s", acc.name, text)

        ok = "登录成功" in text
        if not ok:
            try:
                data = resp.json()
                msg = str(data.get("message") or "")
                if str(data.get("code")) == "0" or "成功" in msg:
                    ok = True
            except Exception:
                pass

        if not ok:
            raise RuntimeError(f"登录失败: {text[:200]}")

        logger.info("[%s] 登录成功", acc.name)

    def apply_cookie(self) -> None:
        cookie = self.account.cookie
        for pair in cookie.split(";"):
            pair = pair.strip()
            if not pair or "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            self.session.cookies.set(
                k.strip(), v.strip(), domain=self.account.domain
            )

        names = {c.name for c in self.session.cookies}
        missing = [x for x in ("bbs_sid", "bbs_token") if x not in names]
        if missing:
            logger.warning(
                "[%s] Cookie 中缺少 %s，签到可能失败",
                self.account.name,
                ", ".join(missing),
            )

    def fetch_gold(self) -> Optional[str]:
        """
        从个人中心 my.htm 读取当前金币余额。
        页面结构示例：
          <span class="text-muted">金币：</span><em ...>302</em>
        """
        try:
            resp = self.session.get(
                f"{self.base}/my.htm",
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                    "Referer": f"{self.base}/",
                },
                timeout=self.cfg.timeout,
            )
            html = resp.text
            if resp.status_code != 200 or "请登录" in html:
                logger.warning("[%s] 获取金币失败：页面异常或未登录", self.account.name)
                return None

            patterns = [
                r"金币：</span>\s*<em[^>]*>([^<]+)</em>",
                r"金币[：:]\s*</span>\s*<em[^>]*>([^<]+)</em>",
                r'金币</span></div><input[^>]*value="(\d+)"',
                r'value="(\d+)"[^>]*>\s*.{0,40}金币',
            ]
            for pat in patterns:
                m = re.search(pat, html, re.I | re.S)
                if m:
                    gold = m.group(1).strip()
                    if gold:
                        logger.info("[%s] 当前金币: %s", self.account.name, gold)
                        return gold

            logger.warning("[%s] 个人中心未解析到金币字段", self.account.name)
            return None
        except Exception as e:
            logger.warning("[%s] 获取金币异常: %s", self.account.name, e)
            return None

    def _attach_gold(self, result: dict[str, Any]) -> dict[str, Any]:
        """签到成功后附带金币余额，便于日志 / 通知展示。"""
        if not result.get("ok"):
            return result
        gold = self.fetch_gold()
        if gold is not None:
            result["gold"] = gold
        return result

    def sign(self) -> dict[str, Any]:
        resp = self.session.post(
            f"{self.base}/sg_sign.htm",
            headers=self._common_headers(),
            timeout=self.cfg.timeout,
        )
        raw = resp.text.strip()
        logger.debug("[%s] 签到原始响应: %s", self.account.name, raw)

        if resp.status_code >= 500 or "502 Bad Gateway" in raw or "503 Service" in raw:
            raise RuntimeError(f"服务器异常 HTTP {resp.status_code}: {raw[:120]}")

        message = raw
        code: Optional[str] = None
        try:
            data = json.loads(raw)
            message = str(data.get("message") or data.get("msg") or raw)
            code = str(data.get("code")) if "code" in data else None
        except json.JSONDecodeError:
            pass

        already = "今天已经签过" in message or "已经签过" in message
        need_login = "请登录" in message or "登录后再签到" in message
        risk = "操作存在风险" in message

        if need_login:
            return {
                "ok": False,
                "already": False,
                "message": message,
                "raw": raw,
                "error": "auth",
            }
        if risk:
            return {
                "ok": False,
                "already": False,
                "message": message,
                "raw": raw,
                "error": "risk",
            }
        if already:
            return {"ok": True, "already": True, "message": message, "raw": raw}
        if code == "0" or "成功" in message:
            return {"ok": True, "already": False, "message": message, "raw": raw}

        return {
            "ok": False,
            "already": False,
            "message": message,
            "raw": raw,
            "error": "unknown",
        }

    def _sign_with_retries(self) -> dict[str, Any]:
        last: dict[str, Any] = {
            "ok": False,
            "message": "未执行",
            "already": False,
            "raw": "",
        }
        for attempt in range(1, self.cfg.max_retries + 1):
            logger.info(
                "[%s] 第 %d/%d 次签到...",
                self.account.name,
                attempt,
                self.cfg.max_retries,
            )
            try:
                last = self.sign()
            except requests.RequestException as e:
                last = {
                    "ok": False,
                    "already": False,
                    "message": f"网络错误: {e}",
                    "raw": "",
                    "error": "network",
                }
                logger.warning("[%s] %s", self.account.name, last["message"])
            except RuntimeError as e:
                last = {
                    "ok": False,
                    "already": False,
                    "message": str(e),
                    "raw": "",
                    "error": "server",
                }
                logger.warning("[%s] %s", self.account.name, last["message"])

            if last.get("ok"):
                return last
            # auth 交给上层做密码回退，这里直接返回
            if last.get("error") == "auth":
                return last

            if attempt < self.cfg.max_retries:
                logger.info(
                    "[%s] 等待 %ds 后重试...",
                    self.account.name,
                    self.cfg.retry_interval,
                )
                time.sleep(self.cfg.retry_interval)
        return last

    def run(self) -> dict[str, Any]:
        """
        Cookie 优先 → 失败且可登录则密码重登再签。
        """
        acc = self.account
        result: dict[str, Any]

        if acc.has_cookie():
            logger.info("[%s] 使用 Cookie 签到", acc.name)
            self.apply_cookie()
            result = self._sign_with_retries()
            if result.get("ok"):
                result["via"] = "cookie"
                return self._attach_gold(result)

            if result.get("error") == "auth" and acc.has_password():
                logger.warning(
                    "[%s] Cookie 已失效，尝试账号密码重新登录...",
                    acc.name,
                )
                self.reset_session()
                try:
                    self.login()
                except Exception as e:
                    result["message"] = f"Cookie 失效，且密码登录失败: {e}"
                    result["via"] = "cookie→login_failed"
                    return result
                self.used_fallback_login = True
                result = self._sign_with_retries()
                result["via"] = "cookie→password"
                if result.get("ok"):
                    logger.info("[%s] 密码重登后签到成功", acc.name)
                    return self._attach_gold(result)
                return result

            result.setdefault("via", "cookie")
            return result

        # 仅密码
        if acc.has_password():
            try:
                self.login()
            except Exception as e:
                return {
                    "ok": False,
                    "already": False,
                    "message": f"登录失败: {e}",
                    "raw": "",
                    "error": "auth",
                    "via": "password",
                }
            result = self._sign_with_retries()
            result["via"] = "password"
            if result.get("ok"):
                return self._attach_gold(result)
            return result

        return {
            "ok": False,
            "already": False,
            "message": "未配置 Cookie 或账号密码",
            "raw": "",
            "error": "auth",
            "via": "none",
        }


# ---------------------------------------------------------------------------
# 通知：Bark 为主
# ---------------------------------------------------------------------------

def _build_bark_endpoint(cfg: NotifyConfig) -> Optional[str]:
    """
    返回 Bark 基础推送前缀（不含 title/body），例如：
      https://api.day.app/KEY
    """
    if cfg.bark_url:
        url = cfg.bark_url.strip().rstrip("/")
        # 用户可能贴了带占位的完整示例，去掉尾部空 path
        return url
    if cfg.bark_key:
        server = (cfg.bark_server or DEFAULT_BARK_SERVER).rstrip("/")
        return f"{server}/{cfg.bark_key.strip()}"
    return None


def send_bark(cfg: NotifyConfig, title: str, body: str) -> None:
    endpoint = _build_bark_endpoint(cfg)
    if not endpoint:
        return

    # POST JSON 更稳妥（支持换行、中文、额外参数）
    payload: dict[str, Any] = {
        "title": title,
        "body": body,
        "group": cfg.bark_group or "HiFiNi",
    }
    if cfg.bark_sound:
        payload["sound"] = cfg.bark_sound
    if cfg.bark_icon:
        payload["icon"] = cfg.bark_icon
    if cfg.bark_level:
        payload["level"] = cfg.bark_level

    # endpoint 可能是 https://api.day.app/KEY 或 https://api.day.app/KEY/
    post_url = endpoint if endpoint.endswith("/push") else endpoint
    # Bark 官方：POST https://api.day.app/KEY  {title, body, ...}
    # 也支持 GET /KEY/title/body

    try:
        r = requests.post(post_url, json=payload, timeout=15)
        if r.status_code >= 400:
            # 回退 GET
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
        m = re.match(r"sctp(\d+)t", key)
        if m:
            url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send"
        else:
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


def resolve_config(args: argparse.Namespace) -> AppConfig:
    # 显式 --config
    if args.config:
        return load_config_yaml(Path(args.config))

    # 青龙 / 环境变量优先
    env_cfg = load_config_from_env()
    if env_cfg is not None:
        logger.info(
            "已从环境变量加载 %d 个账号",
            len(env_cfg.accounts),
        )
        return env_cfg

    # 本地 config.yaml 兜底
    local = SCRIPT_DIR / "config.yaml"
    if local.is_file():
        logger.info("使用本地配置: %s", local)
        return load_config_yaml(local)

    raise FileNotFoundError(
        "未找到账号配置。\n"
        "青龙：请设置环境变量 HIFINI_ACCOUNTS 或 HIFINI_COOKIE / HIFINI_LOGIN\n"
        "本地：cp config.example.yaml config.yaml 并填写"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="HiFiNi 自动签到（青龙 / Bark）")
    parser.add_argument("-c", "--config", help="本地 yaml 配置路径（可选）")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    args = parser.parse_args()

    setup_logging(args.verbose)

    try:
        cfg = resolve_config(args)
    except Exception as e:
        logger.error("%s", e)
        return 2

    lines: list[str] = []
    any_fail = False

    for acc in cfg.accounts:
        logger.info(
            "======== 账号: %s (%s) ========",
            acc.name,
            acc.auth_label(),
        )
        try:
            result = HiFiTiClient(acc, cfg).run()
        except Exception as e:
            logger.exception("[%s] 未处理异常", acc.name)
            result = {
                "ok": False,
                "already": False,
                "message": str(e),
                "raw": "",
                "via": "error",
            }

        via = result.get("via") or ""
        via_tip = f" [{via}]" if via else ""
        gold = result.get("gold")
        gold_tip = f" | 金币: {gold}" if gold is not None else ""

        if result.get("ok"):
            tag = "已签过" if result.get("already") else "签到成功"
            line = (
                f"✅ [{acc.name}] {tag}{via_tip}: "
                f"{result.get('message')}{gold_tip}"
            )
            logger.info(line)
        else:
            any_fail = True
            line = f"❌ [{acc.name}] 签到失败{via_tip}: {result.get('message')}"
            logger.error(line)
        lines.append(line)

    summary = "\n".join(lines)
    print("\n======== 签到结果 ========\n" + summary)

    title = "HiFiNi 签到完成" if not any_fail else "HiFiNi 签到有失败"
    send_notify(cfg.notify, title, summary)

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
